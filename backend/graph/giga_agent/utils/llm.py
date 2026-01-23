import asyncio
import os
import logging
from typing import Dict, Optional, Literal
import inspect

import httpx
from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings

# Опциональный импорт ChatOpenAI для OpenRouter
try:
    from langchain_openai import ChatOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    ChatOpenAI = None
    OPENAI_AVAILABLE = False

from giga_agent.utils.env import load_project_env
from giga_agent.utils.proxy_settings import get_proxy_url_for_http_clients
from giga_agent.utils.types import FileTypes
from giga_agent.utils.task_type import normalize_task_type

# Опциональный импорт langchain-gigachat (может быть не установлен)
try:
    from gigachat.exceptions import ResponseError
    from langchain_gigachat import GigaChat, GigaChatEmbeddings
    GIGACHAT_AVAILABLE = True
except ImportError:
    GigaChat = None
    GigaChatEmbeddings = None
    ResponseError = Exception
    GIGACHAT_AVAILABLE = False

# Опциональный импорт менеджера моделей OpenRouter
try:
    from giga_agent.utils.openrouter_model_manager import OpenRouterModelManager
    OPENROUTER_MANAGER_AVAILABLE = True
except ImportError:
    OpenRouterModelManager = None
    OPENROUTER_MANAGER_AVAILABLE = False

GIGACHAT_PROVIDER = "gigachat:"
OPENROUTER_PROVIDER = "openrouter:"
DEEPSEEK_PROVIDER = "deepseek:"
OPENAI_PROVIDER = "openai:"

logger = logging.getLogger(__name__)

# Опциональный импорт эмбеддингов OpenRouter
try:
    from giga_agent.utils.openrouter_embeddings import OpenRouterEmbeddings, load_openrouter_embeddings
    OPENROUTER_EMBEDDINGS_AVAILABLE = True
except ImportError:
    OpenRouterEmbeddings = None
    load_openrouter_embeddings = None
    OPENROUTER_EMBEDDINGS_AVAILABLE = False

load_project_env()

# Глобальный экземпляр менеджера моделей OpenRouter
_openrouter_model_manager: Optional[OpenRouterModelManager] = None


def get_openrouter_model_manager() -> Optional[OpenRouterModelManager]:
    """Получение глобального экземпляра менеджера моделей OpenRouter"""
    global _openrouter_model_manager
    
    if not OPENROUTER_MANAGER_AVAILABLE:
        return None
    
    if _openrouter_model_manager is None:
        try:
            api_key = os.getenv("OPENROUTER_API_KEY")
            if api_key:
                _openrouter_model_manager = OpenRouterModelManager(api_key=api_key)
                # НЕ применяем глобальную модель автоматически при инициализации
                # Теперь модели привязаны к пользователям и применяются через apply_persisted_openrouter_model
        except Exception as e:
            logger.warning(f"Не удалось инициализировать менеджер моделей OpenRouter: {e}")
    
    return _openrouter_model_manager


def apply_persisted_openrouter_model(tag: str = None, user_id: Optional[str] = None) -> bool:
    """
    Применение сохраненной модели OpenRouter к переменным окружения
    
    Вызывается при загрузке LLM для восстановления выбранной пользователем модели.
    
    Args:
        tag: Тег модели (None для основной модели GIGA_AGENT_LLM)
        user_id: ID пользователя (если None, применяется глобальная модель)
        
    Returns:
        True если модель была применена, False если нет
    """
    manager = get_openrouter_model_manager()
    if manager:
        return manager.apply_persisted_model_to_env(tag=tag, user_id=user_id)
    return False


def set_user_openrouter_model(user_id: str, model_id: str) -> bool:
    """
    Установка модели OpenRouter для конкретного пользователя
    
    Args:
        user_id: ID пользователя
        model_id: ID модели OpenRouter (например, mistralai/devstral-2512:free)
        
    Returns:
        True если успешно, False в противном случае
    """
    manager = get_openrouter_model_manager()
    if manager:
        return manager.set_user_model(user_id, model_id)
    return False


def get_user_openrouter_model(user_id: str) -> Optional[str]:
    """
    Получение текущей модели OpenRouter для пользователя
    
    Args:
        user_id: ID пользователя
        
    Returns:
        ID модели или None
    """
    manager = get_openrouter_model_manager()
    if manager:
        return manager.get_persisted_model(user_id=user_id)
    return None


def clear_user_openrouter_model(user_id: str):
    """
    Очистка модели OpenRouter для пользователя (сброс к дефолтной)
    
    Args:
        user_id: ID пользователя
    """
    manager = get_openrouter_model_manager()
    if manager:
        manager.clear_persisted_model(user_id=user_id)


def get_agent_env(tag: str = None):
    if tag is None:
        return "GIGA_AGENT_LLM"
    else:
        return f"GIGA_AGENT_LLM_{tag.upper()}"


def env_has_model(tag: str | None) -> bool:
    """
    Проверяет, задана ли модель в env для указанного tag.

    Примечание:
    - tag=None => проверяем GIGA_AGENT_LLM
    - tag='coder' => GIGA_AGENT_LLM_CODER и т.п.
    """
    key = get_agent_env(tag)
    val = os.getenv(key)
    return bool(val and str(val).strip())


def choose_llm_tag_for_task_type(task_type: str | None) -> str | None:
    """
    Policy выбора tag для load_llm() по MECE task_type.

    Примечание (ROMA optimization, stage-1):
    - Если специализированная env-переменная не задана, возвращаем None (fallback на основную модель).
    - Маппинг: RETRIEVE -> FAST (если задан), CODE_INTERPRET -> CODER (если задан), IMAGE_GENERATION -> IMAGE (если задан).
    """
    tt = normalize_task_type(task_type)
    if not tt:
        return None

    # RETRIEVE: предпочитаем быстрый/дешёвый профиль (GIGA_AGENT_LLM_FAST), если он задан
    if tt == "RETRIEVE":
        return "fast" if env_has_model("fast") else None

    # CODE_INTERPRET: предпочитаем coder профиль, если он задан
    if tt == "CODE_INTERPRET":
        return "coder" if env_has_model("coder") else None

    # IMAGE_GENERATION: отдельная модель (если используется текстовая LLM для управления image tool)
    if tt == "IMAGE_GENERATION":
        return "image" if env_has_model("image") else None

    # THINK/WRITE: по умолчанию используем основную модель (None)
    return None


def load_gigachat(tag: str = None, is_main: bool = False):
    if not GIGACHAT_AVAILABLE:
        raise ImportError(
            "langchain-gigachat не установлен. "
            "Установите его для использования GigaChat моделей: pip install langchain-gigachat"
        )
    llm_str = os.getenv(get_agent_env(tag))
    kwargs = {}
    if is_main:
        kwargs = dict(
            timeout=os.getenv("MAIN_GIGACHAT_TIMEOUT", 70),
            user=os.getenv("MAIN_GIGACHAT_USER"),
            password=os.getenv("MAIN_GIGACHAT_PASSWORD"),
            credentials=os.getenv("MAIN_GIGACHAT_CREDENTIALS"),
            scope=os.getenv("MAIN_GIGACHAT_SCOPE"),
            base_url=os.getenv("MAIN_GIGACHAT_BASE_URL"),
            top_p=os.getenv("MAIN_GIGACHAT_TOP_P", 0.5),
            verbose=os.getenv("MAIN_GIGACHAT_VERBOSE", "False"),
        )
    return GigaChat(
        model=llm_str[len(GIGACHAT_PROVIDER) :],
        profanity_check=False,
        verify_ssl_certs=False,
        max_tokens=1280000,
        **kwargs,
    )


def load_gigachat_embeddings():
    if not GIGACHAT_AVAILABLE:
        raise ImportError(
            "langchain-gigachat не установлен. "
            "Установите его для использования GigaChat embeddings: pip install langchain-gigachat"
        )
    llm_str = os.getenv("GIGA_AGENT_EMBEDDINGS")
    return GigaChatEmbeddings(
        model=llm_str[len(GIGACHAT_PROVIDER) :],
    )


def is_llm_gigachat(tag: str = None):
    llm_str = os.getenv(get_agent_env(tag))
    return llm_str.startswith(GIGACHAT_PROVIDER)


# Singletons cache
_LLM_SINGLETONS: Dict[str, object] = {}
_EMBEDDINGS_SINGLETON: Optional[object] = None


def reset_llm_singleton(tag: str = None, is_main: bool = False) -> None:
    """
    Сбрасывает кэш singleton LLM для указанного env key.

    Нужно, когда мы динамически меняем модель (например, при OpenRouter 429),
    иначе load_llm() вернет старый инстанс из _LLM_SINGLETONS.
    """
    env_key = get_agent_env(tag)
    singleton_key = ("MAIN_" + env_key) if is_main else env_key
    _LLM_SINGLETONS.pop(singleton_key, None)


def reset_all_llm_singletons_for_env(env_key: str) -> None:
    """
    Сбрасывает ВСЕ варианты singleton LLM для указанного env_key.
    Это включает все комбинации is_main, user_id и т.д.
    
    Используется при переключении провайдера, чтобы гарантировать,
    что все закэшированные экземпляры LLM будут пересозданы.
    """
    keys_to_remove = [k for k in list(_LLM_SINGLETONS.keys()) if env_key in k]
    for key in keys_to_remove:
        _LLM_SINGLETONS.pop(key, None)
        logger.info(f"[LLM] Удален singleton: {key}")


def load_llm(tag: str = None, is_main: bool = False, user_id: Optional[str] = None):
    """
    Загрузка LLM модели
    
    Args:
        tag: Тег модели (None для основной модели GIGA_AGENT_LLM)
        is_main: Флаг основной модели
        user_id: ID пользователя для загрузки персональной модели OpenRouter
    """
    env_key = get_agent_env(tag)
    # TODO: Поправить логику загрузки LLM кредов (сейчас это вообще что-то страшное)
    
    # Для пользовательских моделей используем отдельный ключ singleton
    singleton_key = env_key
    if is_main:
        singleton_key = "MAIN_" + singleton_key
    if user_id:
        singleton_key = f"USER_{user_id}_" + singleton_key
    
    # ВАЖНО: Для OpenRouter моделей с user_id проверяем, не изменилась ли модель в Redis
    # Это позволяет динамически переключать модели без перезапуска сервиса
    llm_str = os.getenv(env_key)
    if llm_str and llm_str.startswith("openrouter:") and user_id:
        # Получаем текущую модель пользователя из Redis
        current_user_model = get_user_openrouter_model(user_id)
        
        # Проверяем, есть ли уже закэшированный singleton
        if singleton_key in _LLM_SINGLETONS:
            # Получаем модель из закэшированного singleton
            cached_llm = _LLM_SINGLETONS[singleton_key]
            cached_model = getattr(cached_llm, 'model_name', None) or getattr(cached_llm, 'model', None)
            
            # Если модель в Redis изменилась или была удалена, пересоздаем LLM
            if current_user_model:
                # Модель в Redis есть - проверяем, совпадает ли с закэшированной
                if cached_model and current_user_model not in str(cached_model):
                    logger.info(f"[LLM] Модель пользователя {user_id} изменилась: {cached_model} -> {current_user_model}, пересоздаем LLM")
                    del _LLM_SINGLETONS[singleton_key]
            else:
                # Модели в Redis нет - используем дефолтную, сбрасываем кэш
                default_model = os.getenv(env_key, "").replace("openrouter:", "")
                if cached_model and default_model and default_model not in str(cached_model):
                    logger.info(f"[LLM] Модель пользователя {user_id} сброшена на дефолтную: {cached_model} -> {default_model}, пересоздаем LLM")
                    del _LLM_SINGLETONS[singleton_key]
    
    # ВАЖНО: Перед загрузкой LLM проверяем, есть ли сохраненная модель в Redis
    # Это обеспечивает персистентность выбора модели между сессиями чата
    # Сначала проверяем Redis для всех провайдеров (deepseek, openai, openrouter)
    saved_llm_str_from_redis = None
    try:
        import redis
        redis_uri = os.getenv("REDIS_URI", "redis://localhost:6379")
        redis_client = redis.from_url(redis_uri, decode_responses=True)
        redis_key = f"provider:llm:{env_key}"
        saved_llm_str_from_redis = redis_client.get(redis_key)
        if saved_llm_str_from_redis:
            # Применяем сохраненную модель из Redis
            current_llm_str = os.getenv(env_key, "")
            if current_llm_str != saved_llm_str_from_redis:
                try:
                    os.environ[env_key] = saved_llm_str_from_redis
                    logger.info(f"[LLM] Применена сохраненная модель из Redis: {env_key} = {saved_llm_str_from_redis} (было: {current_llm_str})")
                    # ВАЖНО: Если значение из Redis отличается, сбрасываем ВСЕ singleton для этого env_key
                    # чтобы гарантировать, что все варианты (с user_id, без user_id, is_main=True/False) будут пересозданы
                    reset_all_llm_singletons_for_env(env_key)
                except (ValueError, TypeError, OSError):
                    # Если не удалось установить в os.environ, используем значение из Redis напрямую
                    logger.warning(f"[LLM] Не удалось установить {env_key} из Redis, используем значение напрямую")
                    llm_str = saved_llm_str_from_redis
                    # Также сбрасываем все singleton, если значение изменилось
                    reset_all_llm_singletons_for_env(env_key)
    except Exception as e:
        logger.debug(f"[LLM] Не удалось проверить Redis для {env_key}: {e}")
    
    # Проверяем singleton ПОСЛЕ применения значения из Redis
    # ВАЖНО: Проверяем singleton только после применения значения из Redis,
    # чтобы гарантировать, что используется актуальная модель
    if singleton_key in _LLM_SINGLETONS:
        # Дополнительная проверка: убеждаемся, что закэшированный singleton соответствует текущему значению
        cached_llm = _LLM_SINGLETONS[singleton_key]
        cached_model_str = getattr(cached_llm, 'model_name', None) or getattr(cached_llm, 'model', None) or ""
        current_llm_str_final = os.getenv(env_key, "")
        # Если текущее значение изменилось (например, из Redis), но singleton еще не обновлен, сбрасываем его
        if saved_llm_str_from_redis and saved_llm_str_from_redis not in str(cached_model_str):
            logger.info(f"[LLM] Singleton {singleton_key} не соответствует значению из Redis, сбрасываем")
            _LLM_SINGLETONS.pop(singleton_key, None)
        else:
            return cached_llm
    
    # Для OpenRouter также применяем сохраненную модель пользователя (если есть)
    # НО ТОЛЬКО если в Redis нет сохраненного значения для другого провайдера
    llm_str = os.getenv(env_key)
    if llm_str and llm_str.startswith("openrouter:"):
        # Применяем сохраненную модель пользователя, если она есть
        # ВАЖНО: Не применяем, если в Redis сохранен другой провайдер (deepseek, openai)
        if saved_llm_str_from_redis and not saved_llm_str_from_redis.startswith("openrouter:"):
            logger.info(f"[LLM] Пропускаем применение модели OpenRouter пользователя, т.к. в Redis сохранен другой провайдер: {saved_llm_str_from_redis}")
        else:
            persisted_applied = apply_persisted_openrouter_model(tag=tag, user_id=user_id)
            if persisted_applied:
                # Перечитываем значение после применения
                new_llm_str = os.getenv(env_key)
                if new_llm_str != llm_str:
                    logger.info(f"[LLM] Применена сохраненная модель пользователя {user_id}: {llm_str} -> {new_llm_str}")
                    llm_str = new_llm_str
                else:
                    # Сохраненная модель совпадает с текущей, не логируем
                    pass
    
    if llm_str is None:
        raise RuntimeError(f"{env_key} is empty! Fill it with your model")

    # Проверяем OpenRouter ПЕРЕД другими проверками, чтобы гарантировать правильную обработку
    if llm_str and (llm_str.startswith("openrouter:") or llm_str.startswith(OPENROUTER_PROVIDER)):
        # Поддержка моделей OpenRouter.ai
        # Формат: openrouter:model_id (например, openrouter:mistralai/devstral-2512:free)
        # Примечание:
        # OpenRouter использует OpenAI-совместимый API, поэтому используем формат openai/model_id
        # с установкой base_url на https://openrouter.ai/api/v1
        # API ключ должен быть установлен в переменной окружения OPENROUTER_API_KEY.
        # Также можно указать OPENROUTER_BASE_URL, OPENROUTER_HTTP_REFERER, OPENROUTER_X_TITLE.
        #
        # Параметры управляются через env:
        # - GIGA_AGENT_LLM_TIMEOUT (сек), общий таймаут на запрос к LLM
        # - GIGA_AGENT_LLM_MAX_RETRIES, количество ретраев на сетевые/транзиентные ошибки
        # - OPENROUTER_TIMEOUT (сек), fallback-таймаут для OpenRouter моделей (если общий не задан)
        # - OPENROUTER_MAX_RETRIES, fallback-ретраи для OpenRouter моделей (если общий не задан)
        # - OPENROUTER_MAX_FAILURES, количество неудач перед переключением модели (по умолчанию 3)
        # - OPENROUTER_RETRY_AFTER_SECONDS, время блокировки модели после неудач (по умолчанию 300)
        
        # Проверяем наличие API ключа
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY не установлен. "
                "Установите его в переменных окружения для использования моделей OpenRouter."
            )
        
        # Извлекаем model_id из формата openrouter:model_id
        preferred_model_id = llm_str[len(OPENROUTER_PROVIDER):] if llm_str.startswith(OPENROUTER_PROVIDER) else llm_str[len("openrouter:"):]
        
        # Получаем менеджер моделей для автоматического переключения
        model_manager = get_openrouter_model_manager()
        
        # Определяем модель для использования (с учетом доступности)
        # ВАЖНО: При явно установленной модели (например, при сбросе к стартовой) используем её напрямую
        # Автоматическое переключение происходит только при ошибках во время выполнения
        if model_manager:
            # Проверяем, доступна ли предпочтительная модель
            if model_manager._is_model_available(preferred_model_id):
                model_id = preferred_model_id
            else:
                # Если предпочтительная модель недоступна, пытаемся найти альтернативу
                # Но только если это не явно установленная стартовая модель
                model_id = model_manager.get_available_model(preferred_model=preferred_model_id)
                if not model_id:
                    # Если нет альтернатив, все равно пытаемся использовать предпочтительную
                    # (она может быть временно недоступна, но попытка стоит того)
                    logger.warning(f"Предпочтительная модель {preferred_model_id} недоступна, но используем её (может быть временная проблема)")
                    model_id = preferred_model_id
                elif model_id != preferred_model_id:
                    logger.info(f"Используется модель {model_id} вместо {preferred_model_id} (предпочтительная недоступна)")
        else:
            model_id = preferred_model_id
        
        # Получаем base_url (по умолчанию https://openrouter.ai/api/v1)
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        
        # Настройки таймаутов и ретраев
        timeout_s = os.getenv("GIGA_AGENT_LLM_TIMEOUT")
        if timeout_s is None:
            timeout_s = os.getenv("OPENROUTER_TIMEOUT", "60")  # По умолчанию 60 секунд для OpenRouter
        timeout = float(timeout_s) if timeout_s else 60

        max_retries_s = os.getenv("GIGA_AGENT_LLM_MAX_RETRIES")
        if max_retries_s is None:
            max_retries_s = os.getenv("OPENROUTER_MAX_RETRIES", "3")  # По умолчанию 3 ретрая
        max_retries = int(max_retries_s) if max_retries_s else 3

        # Используем ChatOpenAI напрямую с base_url для OpenRouter
        # OpenRouter использует OpenAI-совместимый API
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "langchain-openai не установлен. "
                "Установите его для использования моделей OpenRouter: pip install langchain-openai"
            )
        
        # Получаем дополнительные заголовки для OpenRouter
        http_referer = os.getenv("OPENROUTER_HTTP_REFERER")
        x_title = os.getenv("OPENROUTER_X_TITLE")
        
        # Формируем заголовки для запросов
        default_headers = {}
        if http_referer:
            default_headers["HTTP-Referer"] = http_referer
        if x_title:
            default_headers["X-Title"] = x_title
        
        # Создаем ChatOpenAI с настройками для OpenRouter
        llm_kwargs = {
            "model": model_id,
            "api_key": openrouter_api_key,
            "base_url": base_url,
            "timeout": timeout,
            "max_retries": max_retries,
        }

        # ВАЖНО (proxy policy):
        # Прокси используем только для OpenAI/OpenRouter (не глобально через HTTP_PROXY).
        proxy_url = get_proxy_url_for_http_clients()
        if proxy_url and ChatOpenAI is not None:
            try:
                params = inspect.signature(ChatOpenAI.__init__).parameters
                # Некоторые версии langchain_openai принимают http_client/http_async_client.
                if "http_client" in params:
                    llm_kwargs["http_client"] = httpx.Client(proxy=proxy_url, timeout=timeout)
                if "http_async_client" in params:
                    llm_kwargs["http_async_client"] = httpx.AsyncClient(proxy=proxy_url, timeout=timeout)
            except Exception:
                # Если сигнатуру не удалось определить — не вмешиваемся.
                pass
        
        # Добавляем заголовки если они есть
        if default_headers:
            llm_kwargs["default_headers"] = default_headers
        
        try:
            llm = ChatOpenAI(**llm_kwargs)
            
            # Записываем успешное использование модели
            if model_manager:
                model_manager.record_model_success(model_id)
        except Exception as e:
            # При ошибке инициализации записываем неудачу и пытаемся переключиться
            if model_manager:
                error_msg = str(e)
                model_manager.record_model_failure(model_id, error=error_msg)
                
                # Пытаемся получить следующую доступную модель
                next_model = model_manager.get_next_model(model_id)
                if next_model:
                    logger.warning(
                        f"Ошибка при инициализации модели {model_id}: {error_msg}. "
                        f"Переключение на {next_model}"
                    )
                    # Рекурсивно пытаемся загрузить следующую модель
                    # Обновляем переменную окружения для следующей попытки
                    original_llm_str = os.getenv(env_key)
                    os.environ[env_key] = f"openrouter:{next_model}"
                    try:
                        llm = load_llm(tag=tag, is_main=is_main)
                        # Для is_main оставляем новую модель (не восстанавливаем оригинальную)
                        # Для других тегов восстанавливаем оригинальную модель
                        if not is_main and original_llm_str:
                            os.environ[env_key] = original_llm_str
                        return llm
                    except Exception as retry_error:
                        # Если следующая модель тоже не работает, пытаемся вернуться к стартовой
                        logger.error(
                            f"Критическая ошибка: следующая модель {next_model} тоже не работает: {retry_error}. "
                            f"Попытка вернуться к стартовой модели."
                        )
                        # Пытаемся получить стартовую модель из openrouter_tools
                        try:
                            from giga_agent.tools.openrouter_tools import _get_startup_model
                            startup_model = _get_startup_model()
                            if startup_model and startup_model.startswith("openrouter:"):
                                startup_model_id = startup_model.replace("openrouter:", "")
                                # Проверяем, что стартовая модель доступна
                                if model_manager._is_model_available(startup_model_id):
                                    logger.warning(f"Автоматический сброс к стартовой модели: {startup_model}")
                                    os.environ[env_key] = startup_model
                                    reset_llm_singleton(tag=tag, is_main=is_main)
                                    try:
                                        llm = load_llm(tag=tag, is_main=is_main)
                                        return llm
                                    except Exception as startup_error:
                                        logger.error(f"Критическая ошибка: не удалось загрузить стартовую модель: {startup_error}")
                        except Exception as startup_reset_error:
                            logger.error(f"Ошибка при попытке сброса к стартовой модели: {startup_reset_error}")
                        
                        # Если не удалось восстановить стартовую модель, пробуем еще раз с оригинальной
                        if original_llm_str:
                            os.environ[env_key] = original_llm_str
                        raise RuntimeError(
                            f"Не удалось инициализировать модель OpenRouter {model_id} и переключиться на {next_model}: {retry_error}. "
                            "Проверьте правильность формата модели (openrouter:model_id) и наличие OPENROUTER_API_KEY."
                        ) from retry_error
                        # Восстанавливаем оригинальное значение
                        if original_llm_str:
                            os.environ[env_key] = original_llm_str
                        return llm
                    except Exception as retry_error:
                        # Восстанавливаем оригинальное значение
                        if original_llm_str:
                            os.environ[env_key] = original_llm_str
                        raise RuntimeError(
                            f"Не удалось инициализировать модель OpenRouter {model_id} и переключиться на {next_model}: {retry_error}. "
                            "Проверьте правильность формата модели (openrouter:model_id) и наличие OPENROUTER_API_KEY."
                        ) from retry_error
                else:
                    raise RuntimeError(
                        f"Не удалось инициализировать модель OpenRouter {model_id}: {e}. "
                        "Нет других доступных моделей для переключения."
                    ) from e
            else:
                raise RuntimeError(
                    f"Не удалось инициализировать модель OpenRouter {llm_str}: {e}. "
                    "Проверьте правильность формата модели (openrouter:model_id) и наличие OPENROUTER_API_KEY."
                ) from e
    elif llm_str.startswith(GIGACHAT_PROVIDER):
        llm = load_gigachat(tag=tag, is_main=is_main)
    elif llm_str.startswith(DEEPSEEK_PROVIDER):
        # Поддержка моделей DeepSeek через прямой API
        # Формат: deepseek:model_id (например, deepseek:deepseek-reasoner)
        # API ключ должен быть установлен в переменной окружения DEEPSEEK_API_KEY
        
        # Проверяем наличие API ключа
        deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        if not deepseek_api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY не установлен. "
                "Установите его в переменных окружения для использования моделей DeepSeek."
            )
        
        # Извлекаем model_id из формата deepseek:model_id
        model_id = llm_str[len(DEEPSEEK_PROVIDER):]
        
        # Настройки таймаутов и ретраев
        timeout_s = os.getenv("GIGA_AGENT_LLM_TIMEOUT")
        if timeout_s is None:
            timeout_s = os.getenv("DEEPSEEK_TIMEOUT", "300")  # По умолчанию 300 секунд для DeepSeek
        timeout = float(timeout_s) if timeout_s else 300

        max_retries_s = os.getenv("GIGA_AGENT_LLM_MAX_RETRIES")
        if max_retries_s is None:
            max_retries_s = os.getenv("DEEPSEEK_MAX_RETRIES", "3")  # По умолчанию 3 ретрая
        max_retries = int(max_retries_s) if max_retries_s else 3
        
        # Используем init_chat_model для DeepSeek
        init_kwargs = {
            "timeout": timeout,
            "request_timeout": timeout,
            "max_retries": max_retries,
        }
        
        # Устанавливаем API ключ через переменную окружения для init_chat_model
        # (langchain-deepseek использует DEEPSEEK_API_KEY из env)
        try:
            llm = init_chat_model(model_id, **init_kwargs)
        except ImportError as e:
            msg = str(e)
            if "langchain_deepseek" in msg or "langchain-deepseek" in msg:
                raise ImportError(
                    "Не установлен пакет 'langchain-deepseek', необходимый для DeepSeek моделей. "
                    "Установите зависимости (например, 'pip install -U langchain-deepseek') "
                    "или проверьте, что окружение backend/graph использует корректный venv."
                ) from e
            raise
        except Exception as e:
            # Fallback без kwargs
            try:
                llm = init_chat_model(model_id)
            except Exception as fallback_error:
                raise RuntimeError(
                    f"Не удалось инициализировать модель DeepSeek {model_id}: {fallback_error}. "
                    "Проверьте правильность формата модели (deepseek:model_id) и наличие DEEPSEEK_API_KEY."
                ) from fallback_error
    elif llm_str.startswith(OPENAI_PROVIDER):
        # Поддержка моделей OpenAI через прямой API
        # Формат: openai:model_id (например, openai:gpt-4o)
        # API ключ должен быть установлен в переменной окружения OPENAI_API_KEY
        
        # Проверяем наличие API ключа
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY не установлен. "
                "Установите его в переменных окружения для использования моделей OpenAI."
            )
        
        # Извлекаем model_id из формата openai:model_id
        model_id = llm_str[len(OPENAI_PROVIDER):]
        
        # Настройки таймаутов и ретраев
        timeout_s = os.getenv("GIGA_AGENT_LLM_TIMEOUT")
        if timeout_s is None:
            timeout_s = os.getenv("OPENAI_TIMEOUT", "60")  # По умолчанию 60 секунд для OpenAI
        timeout = float(timeout_s) if timeout_s else 60

        max_retries_s = os.getenv("GIGA_AGENT_LLM_MAX_RETRIES")
        if max_retries_s is None:
            max_retries_s = os.getenv("OPENAI_MAX_RETRIES", "3")  # По умолчанию 3 ретрая
        max_retries = int(max_retries_s) if max_retries_s else 3
        
        # Используем ChatOpenAI для OpenAI
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "langchain-openai не установлен. "
                "Установите его для использования моделей OpenAI: pip install langchain-openai"
            )
        
        # Создаем ChatOpenAI с настройками для OpenAI
        llm_kwargs = {
            "model": model_id,
            "api_key": openai_api_key,
            "timeout": timeout,
            "max_retries": max_retries,
        }
        
        # ВАЖНО (proxy policy):
        # Прокси используем только для OpenAI/OpenRouter (не глобально через HTTP_PROXY).
        proxy_url = get_proxy_url_for_http_clients()
        if proxy_url and ChatOpenAI is not None:
            try:
                params = inspect.signature(ChatOpenAI.__init__).parameters
                # Некоторые версии langchain_openai принимают http_client/http_async_client.
                if "http_client" in params:
                    llm_kwargs["http_client"] = httpx.Client(proxy=proxy_url, timeout=timeout)
                if "http_async_client" in params:
                    llm_kwargs["http_async_client"] = httpx.AsyncClient(proxy=proxy_url, timeout=timeout)
            except Exception:
                # Если сигнатуру не удалось определить — не вмешиваемся.
                pass
        
        try:
            llm = ChatOpenAI(**llm_kwargs)
        except Exception as e:
            raise RuntimeError(
                f"Не удалось инициализировать модель OpenAI {model_id}: {e}. "
                "Проверьте правильность формата модели (openai:model_id) и наличие OPENAI_API_KEY."
            ) from e
    else:
        # Примечание:
        # В проекте сменили локальные LLM на DeepSeek (deepseek-reasoner 3.2).
        # Чтобы избежать "вечных" зависаний, задаем разумные таймауты и (по возможности) ретраи.
        #
        # Параметры управляются через env:
        # - GIGA_AGENT_LLM_TIMEOUT (сек), общий таймаут на запрос к LLM
        # - GIGA_AGENT_LLM_MAX_RETRIES, количество ретраев на сетевые/транзиентные ошибки
        # - DEEPSEEK_TIMEOUT (сек), fallback-таймаут для deepseek моделей (если общий не задан)
        # - DEEPSEEK_MAX_RETRIES, fallback-ретраи для deepseek моделей (если общий не задан)
        is_deepseek = "deepseek" in llm_str.lower()
        timeout_s = os.getenv("GIGA_AGENT_LLM_TIMEOUT")
        if timeout_s is None and is_deepseek:
            timeout_s = os.getenv("DEEPSEEK_TIMEOUT")
        timeout = float(timeout_s) if timeout_s else None

        max_retries_s = os.getenv("GIGA_AGENT_LLM_MAX_RETRIES")
        if max_retries_s is None and is_deepseek:
            max_retries_s = os.getenv("DEEPSEEK_MAX_RETRIES")
        max_retries = int(max_retries_s) if max_retries_s else None

        # Для DeepSeek моделей можем попытаться передать параметры (если библиотека их поддерживает).
        # Важно: init_chat_model у разных провайдеров принимает разные kwargs, поэтому делаем fallback.
        init_kwargs = {}
        if timeout is not None:
            # Разные реализации могут ожидать timeout или request_timeout.
            init_kwargs["timeout"] = timeout
            init_kwargs["request_timeout"] = timeout
        if max_retries is not None:
            init_kwargs["max_retries"] = max_retries

        def _init_with_fallback():
            try:
                return init_chat_model(llm_str, **init_kwargs)
            except TypeError:
                # Провайдер не поддержал kwargs
                return init_chat_model(llm_str)

        try:
            llm = _init_with_fallback()
        except ImportError as e:
            # Примечание:
            # Для deepseek моделей langchain требует установленный пакет langchain-deepseek.
            # В dev-окружениях бывает, что зависимости не подтянулись — дадим понятное сообщение.
            msg = str(e)
            if is_deepseek and ("langchain_deepseek" in msg or "langchain-deepseek" in msg):
                raise ImportError(
                    "Не установлен пакет 'langchain-deepseek', необходимый для DeepSeek моделей. "
                    "Установите зависимости (например, 'pip install -U langchain-deepseek') "
                    "или проверьте, что окружение backend/graph использует корректный venv."
                ) from e
            raise
        except Exception as e:
            # Последний fallback без kwargs
            # НО: не используем для OpenRouter, так как он требует специальной обработки
            if llm_str.startswith(OPENROUTER_PROVIDER):
                raise RuntimeError(
                    f"Не удалось инициализировать модель OpenRouter {llm_str}: {e}. "
                    "Проверьте правильность формата модели (openrouter:model_id) и наличие OPENROUTER_API_KEY."
                ) from e
            llm = init_chat_model(llm_str)

    _LLM_SINGLETONS[singleton_key] = llm
    return llm


def load_embeddings():
    global _EMBEDDINGS_SINGLETON

    if _EMBEDDINGS_SINGLETON is not None:
        return _EMBEDDINGS_SINGLETON

    emb_str = os.getenv("GIGA_AGENT_EMBEDDINGS")
    if emb_str is None:
        raise RuntimeError("GIGA_AGENT_EMBEDDINGS is empty! Fill it with your model")

    # Проверяем OpenRouter ПЕРЕД другими проверками
    if emb_str and (emb_str.startswith("openrouter:") or emb_str.startswith(OPENROUTER_PROVIDER)):
        # Поддержка эмбеддингов OpenRouter.ai
        # Формат: openrouter:model_id (например, openrouter:openai/text-embedding-3-small)
        # API ключ должен быть установлен в переменной окружения OPENROUTER_API_KEY.
        #
        # Параметры управляются через env:
        # - OPENROUTER_EMBEDDINGS_MODEL, модель по умолчанию (если не указана в GIGA_AGENT_EMBEDDINGS)
        # - OPENROUTER_TIMEOUT (сек), таймаут для запросов (по умолчанию 60)
        # - OPENROUTER_MAX_RETRIES, количество ретраев (по умолчанию 3)
        # - OPENROUTER_HTTP_REFERER, HTTP-Referer заголовок (опционально)
        # - OPENROUTER_X_TITLE, X-Title заголовок (опционально)
        
        if not OPENROUTER_EMBEDDINGS_AVAILABLE:
            raise ImportError(
                "Модуль openrouter_embeddings не доступен. "
                "Проверьте, что файл backend/graph/giga_agent/utils/openrouter_embeddings.py существует."
            )
        
        # Проверяем наличие API ключа
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY не установлен. "
                "Установите его в переменных окружения для использования эмбеддингов OpenRouter."
            )
        
        # Извлекаем model_id из формата openrouter:model_id
        model_id = emb_str[len(OPENROUTER_PROVIDER):] if emb_str.startswith(OPENROUTER_PROVIDER) else emb_str[len("openrouter:"):]
        
        # Настройки таймаутов и ретраев
        timeout_s = os.getenv("OPENROUTER_TIMEOUT", "60")
        timeout = float(timeout_s) if timeout_s else 60
        
        max_retries_s = os.getenv("OPENROUTER_MAX_RETRIES", "3")
        max_retries = int(max_retries_s) if max_retries_s else 3
        
        # Получаем base_url
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        
        try:
            embeddings = OpenRouterEmbeddings(
                api_key=openrouter_api_key,
                model=model_id,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries
            )
            logger.info(f"Эмбеддинги OpenRouter загружены с моделью {model_id}")
        except Exception as e:
            raise RuntimeError(
                f"Не удалось инициализировать эмбеддинги OpenRouter {emb_str}: {e}. "
                "Проверьте правильность формата модели (openrouter:model_id) и наличие OPENROUTER_API_KEY."
            ) from e
    elif emb_str.startswith(GIGACHAT_PROVIDER):
        embeddings = load_gigachat_embeddings()
    else:
        embeddings = init_embeddings(emb_str)

    _EMBEDDINGS_SINGLETON = embeddings
    return embeddings


def is_llm_image_inline():
    llm_str = os.getenv("GIGA_AGENT_LLM")
    if llm_str is None:
        raise RuntimeError("GIGA_AGENT_LLM is empty! Fill it with your model")
    return llm_str.startswith(GIGACHAT_PROVIDER)


async def upload_file_with_retry(
    file: FileTypes, purpose: Literal["general", "assistant"] = "general", retries=3
):
    llm = load_llm()
    retry = 0
    while retry < retries:
        try:
            file = await llm.aupload_file(file, purpose)
            return file.id_
        except ResponseError as e:
            if e.args[1] != 504:
                raise e
            else:
                retry += 1
            await asyncio.sleep(0.5)
