"""
Инструменты для переключения между провайдерами LLM

Предоставляет функциональность для:
- Переключения между провайдерами: OpenRouter, DeepSeek (прямой), OpenAI (прямой)
- Получения информации о текущем провайдере
- Получения списка доступных провайдеров
"""

import os
import logging
from typing import Optional, Literal
from langchain_core.tools import tool
from pydantic import Field

logger = logging.getLogger(__name__)

# Глобальный синхронный клиент Redis для сохранения настроек провайдера
# ВАЖНО: Не кэшируем клиент глобально, так как при первой неудачной попытке подключения
# он может остаться None навсегда. Вместо этого пытаемся подключиться каждый раз,
# но используем глобальную переменную для оптимизации повторных вызовов.
_sync_redis_client = None
_redis_client_error = False  # Флаг, что Redis недоступен (чтобы не пытаться каждый раз)


def _get_redis_client():
    """Получение синхронного клиента Redis"""
    global _sync_redis_client, _redis_client_error
    
    # Если клиент уже создан и работает, возвращаем его
    if _sync_redis_client is not None:
        try:
            _sync_redis_client.ping()
            return _sync_redis_client
        except Exception:
            # Если клиент перестал работать, сбрасываем его
            _sync_redis_client = None
    
    # Если ранее была ошибка и это не была временная проблема, не пытаемся снова
    # (но все равно пытаемся, так как Redis может стать доступным позже)
    
    try:
        import redis
        redis_uri = os.getenv("REDIS_URI", "redis://localhost:6379")
        logger.debug(f"[PROVIDER_TOOLS] Попытка подключения к Redis: {redis_uri}")
        client = redis.from_url(redis_uri, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        # Проверяем подключение
        client.ping()
        _sync_redis_client = client
        _redis_client_error = False
        logger.info(f"[PROVIDER_TOOLS] Синхронное подключение к Redis установлено: {redis_uri}")
        return _sync_redis_client
    except ImportError as e:
        if not _redis_client_error:
            logger.warning(f"[PROVIDER_TOOLS] Redis библиотека не установлена: {e}")
            _redis_client_error = True
        return None
    except Exception as e:
        if not _redis_client_error:
            logger.warning(f"[PROVIDER_TOOLS] Не удалось подключиться к Redis: {type(e).__name__}: {e}")
            _redis_client_error = True
        return None

# Провайдеры
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_OPENAI = "openai"

# Модели по умолчанию для каждого провайдера
DEFAULT_MODELS = {
    PROVIDER_OPENROUTER: "mistralai/devstral-2512:free",
    PROVIDER_DEEPSEEK: "deepseek-reasoner",
    PROVIDER_OPENAI: "gpt-4o",  # Используем gpt-4o вместо gpt-4.2-pro (которой может не быть)
}


def _get_user_id_from_state(state: Optional[dict]) -> Optional[str]:
    """Извлечение user_id из state"""
    if not state:
        return None
    user_id = state.get("user_id")
    # Нормализуем user_id
    if user_id in ["default_user", "anonymous", "guest", "", None]:
        return None
    return user_id


def _get_current_provider(tag: Optional[str] = None) -> tuple[str, str]:
    """
    Получает текущий провайдер и модель из переменной окружения или Redis
    
    Args:
        tag: Тег модели (None для основной модели GIGA_AGENT_LLM)
    
    Returns:
        tuple: (provider, model) где provider может быть 'openrouter', 'deepseek', 'openai'
    """
    # Нормализуем tag - убеждаемся, что это строка или None
    if tag is not None and not isinstance(tag, str):
        tag = str(tag) if tag else None
    env_key = "GIGA_AGENT_LLM" if tag is None else f"GIGA_AGENT_LLM_{tag.upper()}"
    
    # Сначала проверяем переменную окружения
    llm_str = os.getenv(env_key, "")
    
    # ВАЖНО: Всегда проверяем Redis, так как в Docker контейнерах переменные окружения могут быть read-only,
    # и значения сохраняются только в Redis. Если значение в Redis отличается от os.environ, используем Redis.
    # Используем тот же подход, что и в llm.py - импортируем redis внутри try-except
    try:
        import redis
        redis_uri = os.getenv("REDIS_URI", "redis://localhost:6379")
        redis_client = redis.from_url(redis_uri, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        redis_key = f"provider:llm:{env_key}"
        saved_llm_str = redis_client.get(redis_key)
        if saved_llm_str:
            # Если значение в Redis отличается от os.environ, используем значение из Redis
            if llm_str != saved_llm_str:
                logger.info(f"[GET_CURRENT_PROVIDER] Значение в Redis отличается от os.environ: Redis={saved_llm_str}, os.environ={llm_str}, используем Redis")
                llm_str = saved_llm_str
                # Пытаемся применить значение из Redis в os.environ для совместимости
                try:
                    os.environ[env_key] = saved_llm_str
                except (ValueError, TypeError, OSError):
                    # Если не удалось установить в os.environ, используем значение из Redis напрямую
                    logger.debug(f"[GET_CURRENT_PROVIDER] Не удалось установить {env_key} из Redis в os.environ, используем значение напрямую")
            elif not llm_str:
                # Если переменная окружения пустая, используем значение из Redis
                llm_str = saved_llm_str
                logger.debug(f"[GET_CURRENT_PROVIDER] Переменная окружения пустая, получено значение из Redis: {env_key} = {llm_str}")
                # Пытаемся применить значение из Redis в os.environ для совместимости
                try:
                    os.environ[env_key] = saved_llm_str
                except (ValueError, TypeError, OSError):
                    pass
    except ImportError:
        # Redis библиотека не установлена - это нормально, используем только os.environ
        logger.debug(f"[GET_CURRENT_PROVIDER] Redis библиотека не установлена, используем только os.environ")
    except Exception as e:
        # Ошибка подключения к Redis - используем только os.environ
        logger.debug(f"[GET_CURRENT_PROVIDER] Не удалось проверить Redis для {env_key}: {type(e).__name__}: {e}")
    
    if not llm_str:
        return "unknown", ""
    
    if llm_str.startswith("openrouter:"):
        model = llm_str.replace("openrouter:", "")
        return PROVIDER_OPENROUTER, model
    elif llm_str.startswith("deepseek:"):
        model = llm_str.replace("deepseek:", "")
        return PROVIDER_DEEPSEEK, model
    elif llm_str.startswith("openai:"):
        model = llm_str.replace("openai:", "")
        return PROVIDER_OPENAI, model
    elif "deepseek" in llm_str.lower():
        # Старый формат без префикса
        return PROVIDER_DEEPSEEK, llm_str
    elif llm_str.startswith("gpt-") or "openai" in llm_str.lower():
        # Старый формат без префикса для OpenAI
        return PROVIDER_OPENAI, llm_str
    else:
        # По умолчанию считаем OpenRouter
        return PROVIDER_OPENROUTER, llm_str


def _switch_provider(provider: str, model: Optional[str] = None, tag: Optional[str] = None) -> str:
    """
    Переключает провайдер LLM
    
    Args:
        provider: Провайдер ('openrouter', 'deepseek', 'openai')
        model: Модель (опционально, если не указана, используется модель по умолчанию)
        tag: Тег модели (None для основной модели GIGA_AGENT_LLM)
    
    Returns:
        str: Сообщение о результате переключения
    """
    # Нормализуем tag - убеждаемся, что это строка или None
    if tag is not None and not isinstance(tag, str):
        tag = str(tag) if tag else None
    env_key = "GIGA_AGENT_LLM" if tag is None else f"GIGA_AGENT_LLM_{tag.upper()}"
    
    # Определяем модель
    if model is None:
        model = DEFAULT_MODELS.get(provider)
        if model is None:
            return f"Ошибка: неизвестный провайдер {provider}"
    
    # Формируем строку модели в зависимости от провайдера
    if provider == PROVIDER_OPENROUTER:
        llm_str = f"openrouter:{model}"
        # Проверяем наличие API ключа
        if not os.getenv("OPENROUTER_API_KEY"):
            return "Ошибка: OPENROUTER_API_KEY не установлен в .docker.env"
    elif provider == PROVIDER_DEEPSEEK:
        llm_str = f"deepseek:{model}"
        # Проверяем наличие API ключа
        if not os.getenv("DEEPSEEK_API_KEY"):
            return "Ошибка: DEEPSEEK_API_KEY не установлен в .docker.env"
    elif provider == PROVIDER_OPENAI:
        llm_str = f"openai:{model}"
        # Проверяем наличие API ключа
        if not os.getenv("OPENAI_API_KEY"):
            return "Ошибка: OPENAI_API_KEY не установлен в .docker.env"
    else:
        return f"Ошибка: неизвестный провайдер {provider}. Доступны: {PROVIDER_OPENROUTER}, {PROVIDER_DEEPSEEK}, {PROVIDER_OPENAI}"
    
    # Сохраняем старое значение для отката при ошибке
    old_llm_str = os.getenv(env_key, "")
    
    try:
        # Устанавливаем новое значение в переменную окружения
        # ВАЖНО: В Docker контейнере переменные окружения могут быть read-only,
        # поэтому также сохраняем в Redis для персистентности
        try:
            # Пробуем установить переменную окружения
            os.environ[env_key] = llm_str
            logger.info(f"[SWITCH_PROVIDER] Установлена переменная окружения {env_key} = {llm_str}")
        except (ValueError, TypeError, OSError) as env_error:
            # Если не удалось установить переменную окружения напрямую,
            # используем Redis для сохранения (если доступен)
            logger.warning(f"[SWITCH_PROVIDER] Не удалось установить {env_key} напрямую: {env_error}, пробуем Redis")
            redis_client = _get_redis_client()
            if redis_client:
                redis_key = f"provider:llm:{env_key}"
                redis_client.set(redis_key, llm_str)
                logger.info(f"[SWITCH_PROVIDER] Сохранено в Redis: {redis_key} = {llm_str}")
            else:
                return f"Ошибка: не удалось установить {env_key} и Redis недоступен. Попробуйте перезапустить контейнер с новой переменной окружения."
        
        # Также сохраняем в Redis для персистентности (даже если os.environ работает)
        redis_client = _get_redis_client()
        if redis_client:
            redis_key = f"provider:llm:{env_key}"
            redis_client.set(redis_key, llm_str)
            logger.debug(f"[SWITCH_PROVIDER] Дополнительно сохранено в Redis: {redis_key} = {llm_str}")
        
        # Сбрасываем singleton для перезагрузки модели
        # ВАЖНО: Сбрасываем ВСЕ варианты singleton (с is_main=True и is_main=False, с user_id и без)
        from giga_agent.utils.llm import reset_all_llm_singletons_for_env
        env_key = "GIGA_AGENT_LLM" if tag is None else f"GIGA_AGENT_LLM_{tag.upper()}"
        reset_all_llm_singletons_for_env(env_key)
        logger.info(f"[SWITCH_PROVIDER] Сброшены все singleton для {env_key}")
        
        # Пытаемся загрузить модель для проверки
        from giga_agent.utils.llm import load_llm
        try:
            load_llm(tag=tag, is_main=False)
            return f"Успешно переключено на провайдер {provider} с моделью {model}"
        except Exception as e:
            # Откатываем изменения при ошибке
            if old_llm_str:
                os.environ[env_key] = old_llm_str
            return f"Ошибка при переключении на {provider}: {str(e)}"
    except Exception as e:
        # Откатываем изменения при ошибке
        if old_llm_str:
            os.environ[env_key] = old_llm_str
        return f"Ошибка при переключении провайдера: {str(e)}"


@tool
async def switch_provider(
    provider: Literal["openrouter", "deepseek", "openai"] = Field(
        ...,
        description="Провайдер для переключения: 'openrouter' (через OpenRouter.ai), 'deepseek' (прямой API DeepSeek), 'openai' (прямой API OpenAI)"
    ),
    model: Optional[str] = Field(
        default=None,
        description="Модель для использования (опционально). Если не указана, используется модель по умолчанию для провайдера. Для openrouter: например 'mistralai/devstral-2512:free', для deepseek: 'deepseek-reasoner', для openai: 'gpt-4o'"
    ),
    tag: Optional[str] = Field(
        default=None,
        description="Тег модели (опционально). None для основной модели GIGA_AGENT_LLM, 'fast' для GIGA_AGENT_LLM_FAST, 'coder' для GIGA_AGENT_LLM_CODER и т.д."
    )
) -> str:
    """
    Переключение провайдера LLM
    
    КРИТИЧЕСКИ ВАЖНО: Используй ЭТОТ инструмент (switch_provider), когда пользователь просит:
    - "переключи провайдера на deepseek"
    - "переключи на openai"
    - "используй deepseek"
    - "переключись на openrouter"
    - "смени провайдера на ..."
    
    НЕ используй get_openrouter_models или другие инструменты для переключения провайдера!
    
    ВАЖНО: Система поддерживает три провайдера LLM:
    1. OpenRouter (openrouter) - через OpenRouter.ai, требует OPENROUTER_API_KEY
    2. DeepSeek (deepseek) - прямой API, требует DEEPSEEK_API_KEY, модель deepseek-reasoner
    3. OpenAI (openai) - прямой API, требует OPENAI_API_KEY, модель gpt-4o
    
    Используй этот инструмент, когда нужно:
    - Переключиться на другой провайдер LLM (например, на deepseek, openai, openrouter)
    - Изменить модель для текущего провайдера
    - Выбрать более быстрый или более мощный провайдер в зависимости от задачи
    
    Примеры использования:
    - switch_provider(provider="deepseek") - переключить на DeepSeek
    - switch_provider(provider="openai") - переключить на OpenAI
    - switch_provider(provider="openrouter") - переключить на OpenRouter
    
    Args:
        provider: Провайдер для переключения ('openrouter', 'deepseek', 'openai')
        model: Модель для использования (опционально). Если не указана, используется модель по умолчанию
        tag: Тег модели (опционально). None для основной модели
    
    Returns:
        Сообщение о результате переключения
    """
    # Нормализуем параметры - извлекаем значения из Field объектов, если нужно
    if hasattr(provider, 'default'):
        provider = provider.default if provider.default is not ... else None
    if hasattr(model, 'default'):
        model = model.default if model.default is not ... else None
    if hasattr(tag, 'default'):
        tag = tag.default if tag.default is not ... else None
    
    # Дополнительная нормализация - если это строки, оставляем как есть
    if not isinstance(provider, str):
        provider = str(provider) if provider else None
    if model is not None and not isinstance(model, str):
        model = str(model) if model else None
    if tag is not None and not isinstance(tag, str):
        tag = str(tag) if tag else None
    
    logger.info(f"[SWITCH_PROVIDER] Переключение на провайдер {provider}, модель {model}, тег {tag}")
    
    try:
        result = _switch_provider(provider, model, tag)
        logger.info(f"[SWITCH_PROVIDER] Результат: {result}")
        return result
    except Exception as e:
        error_msg = f"Ошибка при переключении провайдера: {str(e)}"
        logger.error(f"[SWITCH_PROVIDER] {error_msg}")
        return error_msg


@tool
async def get_current_provider(
    tag: Optional[str] = Field(
        default=None,
        description="Тег модели (опционально). None для основной модели GIGA_AGENT_LLM"
    )
) -> str:
    """
    Получение информации о текущем провайдере LLM
    
    ВАЖНО: Система поддерживает три провайдера LLM:
    1. OpenRouter (openrouter) - через OpenRouter.ai
    2. DeepSeek (deepseek) - прямой API DeepSeek
    3. OpenAI (openai) - прямой API OpenAI
    
    Используй этот инструмент, когда нужно:
    - Узнать, какой провайдер используется сейчас
    - Проверить текущую модель
    - Получить информацию для принятия решения о переключении
    
    Args:
        tag: Тег модели (опционально). None для основной модели
    
    Returns:
        Информация о текущем провайдере и модели
    """
    logger.info(f"[GET_CURRENT_PROVIDER] Запрос информации о провайдере, тег: {tag}")
    
    try:
        env_key = "GIGA_AGENT_LLM" if tag is None else f"GIGA_AGENT_LLM_{tag.upper()}"
        llm_str = os.getenv(env_key, "")
        
        if not llm_str:
            return f"Ошибка: {env_key} не установлена"
        
        provider, model = _get_current_provider(tag)
        
        # Проверяем наличие API ключей
        api_key_status = {}
        if provider == PROVIDER_OPENROUTER:
            api_key_status["OPENROUTER_API_KEY"] = "установлен" if os.getenv("OPENROUTER_API_KEY") else "не установлен"
        elif provider == PROVIDER_DEEPSEEK:
            api_key_status["DEEPSEEK_API_KEY"] = "установлен" if os.getenv("DEEPSEEK_API_KEY") else "не установлен"
        elif provider == PROVIDER_OPENAI:
            api_key_status["OPENAI_API_KEY"] = "установлен" if os.getenv("OPENAI_API_KEY") else "не установлен"
        
        result = f"Текущий провайдер: {provider}\n"
        result += f"Модель: {model}\n"
        result += f"Полная строка: {llm_str}\n"
        if api_key_status:
            for key, status in api_key_status.items():
                result += f"{key}: {status}\n"
        
        return result
    except Exception as e:
        error_msg = f"Ошибка при получении информации о провайдере: {str(e)}"
        logger.error(f"[GET_CURRENT_PROVIDER] {error_msg}")
        return error_msg


@tool
async def list_providers() -> str:
    """
    Получение списка доступных провайдеров LLM
    
    ВАЖНО: Система поддерживает три провайдера LLM:
    1. OpenRouter (openrouter) - через OpenRouter.ai, множество моделей
    2. DeepSeek (deepseek) - прямой API, модель deepseek-reasoner
    3. OpenAI (openai) - прямой API, модель gpt-4o
    
    Используй этот инструмент, когда нужно:
    - Узнать, какие провайдеры доступны
    - Проверить наличие API ключей для каждого провайдера
    - Выбрать провайдер для переключения
    
    Returns:
        Список доступных провайдеров с информацией о них
    """
    logger.info("[LIST_PROVIDERS] Запрос списка провайдеров")
    
    try:
        result = "Доступные провайдеры LLM:\n\n"
        
        # OpenRouter
        result += "1. OpenRouter (openrouter)\n"
        result += "   Описание: Провайдер через OpenRouter.ai, множество моделей\n"
        result += f"   Модель по умолчанию: {DEFAULT_MODELS[PROVIDER_OPENROUTER]}\n"
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        result += f"   OPENROUTER_API_KEY: {'установлен' if openrouter_key else 'не установлен'}\n"
        result += "\n"
        
        # DeepSeek
        result += "2. DeepSeek (deepseek)\n"
        result += "   Описание: Прямой API DeepSeek\n"
        result += f"   Модель по умолчанию: {DEFAULT_MODELS[PROVIDER_DEEPSEEK]}\n"
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        result += f"   DEEPSEEK_API_KEY: {'установлен' if deepseek_key else 'не установлен'}\n"
        result += "\n"
        
        # OpenAI
        result += "3. OpenAI (openai)\n"
        result += "   Описание: Прямой API OpenAI\n"
        result += f"   Модель по умолчанию: {DEFAULT_MODELS[PROVIDER_OPENAI]}\n"
        openai_key = os.getenv("OPENAI_API_KEY")
        result += f"   OPENAI_API_KEY: {'установлен' if openai_key else 'не установлен'}\n"
        result += "\n"
        
        result += "Для переключения используй: switch_provider с указанием провайдера\n"
        
        return result
    except Exception as e:
        error_msg = f"Ошибка при получении списка провайдеров: {str(e)}"
        logger.error(f"[LIST_PROVIDERS] {error_msg}")
        return error_msg
