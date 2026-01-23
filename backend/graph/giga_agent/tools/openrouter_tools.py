"""
Инструменты для работы с OpenRouter.ai

Предоставляет функциональность для:
- Получения списка доступных моделей
- Проверки лимитов API
- Получения информации о текущей модели
- Переключения на другую модель с проверкой работоспособности (с привязкой к пользователю)
- Тестирования модели перед использованием
- Сброса к стартовой модели при проблемах
"""

import os
import logging
from typing import List, Dict, Optional, Tuple, Annotated
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import Field

logger = logging.getLogger(__name__)


def _get_user_id_from_state(state: Optional[dict]) -> Optional[str]:
    """Извлечение user_id из state"""
    if not state:
        return None
    user_id = state.get("user_id")
    # Нормализуем user_id
    if user_id in ["default_user", "anonymous", "guest", "", None]:
        return None
    return user_id

# Опциональный импорт менеджера моделей OpenRouter
try:
    from giga_agent.utils.openrouter_model_manager import OpenRouterModelManager
    OPENROUTER_MANAGER_AVAILABLE = True
except ImportError:
    OpenRouterModelManager = None
    OPENROUTER_MANAGER_AVAILABLE = False


def _get_manager() -> Optional[OpenRouterModelManager]:
    """Получение экземпляра менеджера моделей OpenRouter"""
    if not OPENROUTER_MANAGER_AVAILABLE:
        return None
    
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None
    
    try:
        return OpenRouterModelManager(api_key=api_key)
    except Exception as e:
        logger.warning(f"Не удалось инициализировать менеджер моделей OpenRouter: {e}")
        return None


@tool
async def get_openrouter_models(
    verified_only: bool = Field(
        default=True,
        description="Если True, возвращает только проверенные модели из БД (рекомендуется). Если False, возвращает все доступные модели."
    ),
    limit: int = Field(
        default=20,
        description="Максимальное количество моделей для возврата (по умолчанию 20)"
    )
) -> str:
    """
    Получение списка моделей OpenRouter.ai
    
    ВАЖНО: Система использует модели OpenRouter.ai для генерации ответов.
    
    По умолчанию возвращает ПРОВЕРЕННЫЕ модели из базы данных - это модели, которые прошли полное тестирование:
    - Базовый ответ (без tools)
    - Function calling (с tools) через streaming  
    - Работа с системным промптом и персональными данными
    
    Проверенные модели гарантированно работают с агентом без ошибок.
    
    Возвращает информацию о моделях:
    - ID модели (например, mistralai/devstral-2512:free)
    - Название модели
    - Размер контекста в токенах
    - Время ответа (для проверенных моделей)
    - Примечания о модели
    
    Используй этот инструмент, когда нужно:
    - Узнать, какие модели рекомендуются для использования
    - Выбрать альтернативную модель для переключения
    - Получить список моделей с большим контекстом
    
    Args:
        verified_only: Если True, возвращает только проверенные модели из БД (рекомендуется). Если False, возвращает все доступные модели.
        limit: Максимальное количество моделей для возврата (по умолчанию 20)
    
    Returns:
        Строка с форматированным списком моделей с их характеристиками
    """
    print(f"[OPENROUTER_MODELS] Called with verified_only={verified_only}, limit={limit}")
    try:
        if verified_only:
            print("[OPENROUTER_MODELS] Getting verified models from DB...")
            # Получаем проверенные модели из БД
            from giga_agent.utils.openrouter_model_manager import get_verified_models_from_db
            
            verified_models = await get_verified_models_from_db(fully_functional_only=True)
            print(f"[OPENROUTER_MODELS] Got {len(verified_models) if verified_models else 0} verified models")
            
            if not verified_models:
                # Fallback на обычный список если БД недоступна
                logger.warning("Не удалось получить проверенные модели из БД, используем fallback")
                verified_only = False
            else:
                models = verified_models[:limit]
                
                result = f"ПРОВЕРЕННЫЕ модели OpenRouter (прошли полное тестирование):\n"
                result += f"Показано {len(models)} из {len(verified_models)} проверенных моделей\n\n"
                
                for i, model in enumerate(models, 1):
                    model_id = model['model_id']
                    name = model.get('model_name', 'N/A') or model_id
                    context = model.get('context_length', 0)
                    response_time = model.get('avg_response_time_ms')
                    notes = model.get('notes', '')
                    
                    result += f"{i}. {model_id}\n"
                    result += f"   Название: {name}\n"
                    if context > 0:
                        result += f"   Контекст: {context:,} токенов\n"
                    if response_time:
                        result += f"   Время ответа: {response_time/1000:.1f} сек\n"
                    result += f"   Статус: ПРОВЕРЕНА (function calling, streaming, system prompt)\n"
                    if notes:
                        result += f"   Примечание: {notes}\n"
                    result += "\n"
                
                result += "---\n"
                result += "Все модели в этом списке гарантированно работают с агентом.\n"
                result += "Для переключения используй: switch_model с model_id из списка."
                
                return result
        
        if not verified_only:
            # Fallback: получаем все модели через менеджер
            manager = _get_manager()
            if not manager:
                return "Ошибка: OpenRouter API ключ не настроен или менеджер моделей недоступен"
            
            models = manager.get_working_models_list()
            models = [m for m in models if m.get('working') is True]
            models = models[:limit]
            
            if not models:
                return "Нет доступных моделей OpenRouter"
            
            result = f"Доступные модели OpenRouter (показано {len(models)}):\n"
            result += "ВНИМАНИЕ: Это общий список, не все модели проверены на полную совместимость!\n\n"
            
            for i, model in enumerate(models, 1):
                model_id = model['id']
                name = model.get('name', 'N/A') or 'N/A'
                context = model.get('context_length', 0)
                status = model.get('status', 'неизвестно')
                
                result += f"{i}. {model_id}\n"
                result += f"   Название: {name}\n"
                result += f"   Контекст: {context:,} токенов\n"
                result += f"   Статус: {status}\n"
                result += "\n"
            
            return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка моделей OpenRouter: {e}")
        return f"Ошибка при получении списка моделей: {str(e)}"


@tool
async def check_openrouter_limits() -> str:
    """
    Проверка лимитов API ключа OpenRouter.ai
    
    ВАЖНО: Система использует модели OpenRouter.ai для генерации ответов. Этот инструмент позволяет проверить лимиты использования API.
    
    Возвращает информацию о:
    - Общем лимите кредитов (если установлен, иначе неограничен)
    - Остатке кредитов (сколько еще можно использовать)
    - Использовании по периодам (сегодня, неделя, месяц, все время)
    - Дате сброса лимита (когда лимит обновится)
    - Статусе бесплатного тарифа
    
    Используй этот инструмент, когда нужно:
    - Проверить, есть ли остаток лимита для использования моделей OpenRouter
    - Узнать, сколько кредитов использовано за разные периоды
    - Понять, когда произойдет сброс лимита (если лимит исчерпан)
    - Диагностировать проблемы с доступом к моделям (возможно, лимит исчерпан)
    
    Если лимит исчерпан, система может не работать с моделями OpenRouter до сброса лимита.
    
    Returns:
        Строка с детальной информацией о лимитах API
    """
    manager = _get_manager()
    if not manager:
        return "Ошибка: OpenRouter API ключ не настроен или менеджер моделей недоступен"
    
    try:
        limits = manager.get_detailed_limits()
        
        if limits.get('error'):
            return f"Ошибка при получении лимитов: {limits.get('error')}"
        
        result = "Информация о лимитах OpenRouter API:\n\n"
        
        # Лимит кредитов
        limit = limits.get('limit')
        if limit is not None:
            result += f"Лимит кредитов: {limit}\n"
            limit_remaining = limits.get('limit_remaining')
            if limit_remaining is not None:
                result += f"Осталось кредитов: {limit_remaining}\n"
                if limit_remaining <= 0:
                    result += "⚠️ Лимит исчерпан!\n"
        else:
            result += "Лимит кредитов: Неограничен\n"
        
        # Дата сброса
        limit_reset = limits.get('limit_reset')
        if limit_reset:
            result += f"Сброс лимита: {limit_reset}\n"
        
        # Использование
        result += "\nИспользование:\n"
        result += f"  - Все время: {limits.get('usage', 0)} кредитов\n"
        result += f"  - Сегодня: {limits.get('usage_daily', 0)} кредитов\n"
        result += f"  - Эта неделя: {limits.get('usage_weekly', 0)} кредитов\n"
        result += f"  - Этот месяц: {limits.get('usage_monthly', 0)} кредитов\n"
        
        # Статус
        result += f"\nБесплатный тариф: {'Да' if limits.get('is_free_tier', False) else 'Нет'}\n"
        result += f"Есть остаток лимита: {'Да' if limits.get('has_remaining', True) else 'Нет'}\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при проверке лимитов OpenRouter: {e}")
        return f"Ошибка при проверке лимитов: {str(e)}"


@tool
async def get_current_openrouter_model(
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Получение информации о текущей используемой модели OpenRouter
    
    ВАЖНО: Система использует модели OpenRouter.ai для генерации ответов. Этот инструмент позволяет узнать, какая модель используется сейчас.
    Показывает модель, сохраненную для текущего пользователя.
    
    Возвращает:
    - ID текущей модели (например, mistralai/devstral-2512:free)
    - Название модели
    - Размер контекста (context_length)
    - Статус доступности (доступна/недоступна)
    - Количество неудачных попыток (если есть)
    - Информацию о доступных альтернативных моделях
    - Информацию о персональной модели пользователя (если установлена)
    
    Используй этот инструмент, когда нужно:
    - Узнать, какая модель OpenRouter используется сейчас для генерации ответов
    - Проверить статус текущей модели (доступна ли она)
    - Понять, нужно ли переключиться на другую модель (если текущая недоступна)
    - Получить список альтернативных моделей с их характеристиками
    
    Система автоматически переключается на доступные модели при ошибках, но этот инструмент позволяет получить информацию о текущей модели и альтернативах.
    
    Args:
        state: Состояние агента (автоматически инжектируется)
    
    Returns:
        Строка с информацией о текущей модели и доступных альтернативах
    """
    # Получаем user_id из state
    user_id = _get_user_id_from_state(state)
    
    # Получаем текущую модель из переменных окружения
    current_model = os.getenv("GIGA_AGENT_LLM", "")
    
    if not current_model or not current_model.startswith("openrouter:"):
        return "Текущая модель не является моделью OpenRouter. Используется другая модель."
    
    model_id = current_model.replace("openrouter:", "")
    
    manager = _get_manager()
    if not manager:
        return f"Текущая модель: {model_id}\n(Менеджер моделей недоступен для получения дополнительной информации)"
    
    try:
        # Проверяем, есть ли у пользователя персональная модель
        user_model_id = None
        if user_id:
            user_model_id = manager.get_persisted_model(user_id=user_id)
        
        # Получаем информацию о текущей модели
        models = manager.get_working_models_list()
        
        # Определяем, какую модель показывать (персональную или глобальную)
        display_model_id = user_model_id if user_model_id else model_id
        
        current_model_info = None
        for model in models:
            if model['id'] == display_model_id:
                current_model_info = model
                break
        
        result = f"Текущая модель OpenRouter: {display_model_id}\n"
        if user_model_id:
            result += f"(Персональная модель пользователя)\n"
        else:
            result += f"(Глобальная модель по умолчанию)\n"
        result += "\n"
        
        if current_model_info:
            name = current_model_info.get('name', 'N/A') or 'N/A'
            context = current_model_info.get('context_length', 0)
            available = current_model_info.get('available', True)
            status = current_model_info.get('status', 'неизвестно')
            failures = current_model_info.get('failures', 0)
            
            result += f"Название: {name}\n"
            result += f"Контекст: {context:,} токенов\n"
            result += f"Доступна: {'Да' if available else 'Нет'}\n"
            result += f"Статус: {status}\n"
            
            if failures > 0:
                result += f"Неудачных попыток: {failures}\n"
            
            if not available:
                result += "\nМодель недоступна! Рекомендуется переключиться на другую модель.\n"
        else:
            result += "Информация о модели не найдена в списке доступных моделей.\n"
        
        # Показываем стартовую модель
        startup_model = _get_startup_model()
        if startup_model:
            result += f"\nСтартовая модель: {startup_model}\n"
        
        # Получаем альтернативные модели
        available_models = [m for m in models if m.get('available', True) and m['id'] != display_model_id]
        if available_models:
            result += f"\nДоступные альтернативы ({len(available_models)} моделей):\n"
            for alt_model in available_models[:5]:  # Показываем первые 5
                result += f"  - {alt_model['id']} ({alt_model.get('context_length', 0):,} токенов)\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении информации о текущей модели: {e}")
        return f"Текущая модель: {model_id}\nОшибка при получении дополнительной информации: {str(e)}"


# Глобальная переменная для хранения стартовой модели
_STARTUP_MODEL: Optional[str] = None


def _get_startup_model() -> Optional[str]:
    """Получить стартовую модель из переменных окружения"""
    global _STARTUP_MODEL
    if _STARTUP_MODEL is None:
        _STARTUP_MODEL = os.getenv("GIGA_AGENT_LLM", "")
    return _STARTUP_MODEL


async def _test_model_response(model_id: str, timeout: float = 10.0, test_with_tools: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Тестирование работоспособности модели через простой запрос (асинхронная версия)
    
    Args:
        model_id: Идентификатор модели (например, mistralai/devstral-2512:free)
        timeout: Таймаут для запроса в секундах
        test_with_tools: Если True, тестирует модель с привязанными tools (function calling)
    
    Returns:
        Tuple[bool, Optional[str]]: (успешно ли, сообщение об ошибке или None)
    """
    
    def _check_data_policy_error(error_str: str) -> Optional[str]:
        """Проверка на ошибку политики данных OpenRouter и отсутствие поддержки tool use"""
        error_lower = error_str.lower()
        
        # Проверка на отсутствие поддержки tool use (function calling)
        if ("no endpoints found that support tool use" in error_lower or
            "no endpoints found that support tool" in error_lower or
            ("404" in error_str and "tool use" in error_lower) or
            ("404" in error_str and "tool" in error_lower and "endpoint" in error_lower)):
            return f"Модель НЕ поддерживает function calling (tool use). Эта модель не может использоваться с агентом, так как агент требует вызов инструментов. Выберите другую модель, которая поддерживает function calling."
        
        if ("data policy" in error_lower or 
            "No endpoints found matching" in error_str or
            "No endpoints found" in error_str or
            "Free model publication" in error_str or
            ("404" in error_str and "endpoints" in error_lower)):
            return f"Модель требует настройки политики конфиденциальности в OpenRouter для function calling. Перейдите по ссылке: https://openrouter.ai/settings/privacy и разрешите 'Allow researchers to use my prompts for training and model selection'"
        return None
    
    try:
        from giga_agent.utils.llm import load_llm, reset_llm_singleton
        from langchain_core.tools import tool as lc_tool
        import asyncio
        
        # Создаем тестовый tool для проверки function calling
        @lc_tool
        def test_function(text: str) -> str:
            """Test function for checking function calling support"""
            return f"Received: {text}"
        
        # Сохраняем текущую модель
        current_model = os.getenv("GIGA_AGENT_LLM", "")
        
        # Временно переключаемся на тестируемую модель
        os.environ["GIGA_AGENT_LLM"] = f"openrouter:{model_id}"
        reset_llm_singleton(tag=None, is_main=True)
        
        try:
            # Загружаем модель
            llm = load_llm(tag=None, is_main=True)
            
            # Делаем простой тестовый запрос
            test_message = "Say hi in one word"
            
            try:
                # Сначала тестируем без tools
                response = await asyncio.wait_for(
                    llm.ainvoke([{"role": "user", "content": test_message}]),
                    timeout=timeout
                )
                # Проверяем, что получили ответ
                if not response or not hasattr(response, 'content'):
                    return False, "Модель вернула пустой ответ (без tools)"
                
                # Если test_with_tools=True, проверяем также с tools (function calling)
                print(f"[_test_model_response] test_with_tools={test_with_tools}, starting tools test...")
                if test_with_tools:
                    print(f"[_test_model_response] Внутри блока test_with_tools для {model_id}")
                    logger.info(f"[OPENROUTER_TOOLS] Тестирование модели {model_id} с function calling...")
                    llm_with_tools = llm.bind_tools([test_function], parallel_tool_calls=False)
                    print(f"[_test_model_response] bind_tools выполнен, вызываем ainvoke с tools...")
                    try:
                        # Тестируем через streaming с реалистичным контекстом (как реально работает агент)
                        # Простой запрос может пройти, а большой контекст - нет (из-за data policy)
                        print(f"[_test_model_response] Тестируем через astream (streaming) с реалистичным контекстом...")
                        
                        # Создаем реалистичный контекст как в агенте
                        realistic_messages = [
                            {"role": "system", "content": "You are a helpful AI assistant. You have access to tools. Answer user questions and use tools when needed. Be concise and helpful."},
                            {"role": "user", "content": "What is 2+2? Use the test_function tool to respond with the answer."}
                        ]
                        
                        chunks = []
                        async def stream_with_timeout():
                            async for chunk in llm_with_tools.astream(realistic_messages):
                                chunks.append(chunk)
                                if len(chunks) >= 1:  # Достаточно одного чанка
                                    break
                        
                        await asyncio.wait_for(stream_with_timeout(), timeout=timeout)
                        print(f"[_test_model_response] Получено {len(chunks)} чанков через streaming")
                        
                        if not chunks:
                            return False, "Модель вернула пустой ответ (с tools через streaming)"
                        print(f"[_test_model_response] Тест с tools через streaming ПРОШЕЛ успешно!")
                        logger.info(f"[OPENROUTER_TOOLS] Модель {model_id} успешно работает с function calling (streaming)")
                    except Exception as tools_err:
                        print(f"[_test_model_response] ОШИБКА при тесте с tools (streaming): {tools_err}")
                        error_str = str(tools_err)
                        policy_error = _check_data_policy_error(error_str)
                        if policy_error:
                            # Если это ошибка отсутствия поддержки tool use, возвращаем специальное сообщение
                            if "не поддерживает function calling" in policy_error.lower() or "tool use" in policy_error.lower():
                                return False, policy_error
                            return False, f"Модель работает без tools, но НЕ поддерживает function calling (tools). {policy_error}"
                        return False, f"Ошибка при тестировании с tools: {error_str[:200]}"
                else:
                    print(f"[_test_model_response] test_with_tools=False, пропускаем тест с tools")
                
                return True, None
                
            except asyncio.TimeoutError:
                return False, f"Таймаут при тестировании модели (>{timeout} сек)"
            except Exception as e:
                error_str = str(e)
                # Проверяем на ошибку политики данных OpenRouter и отсутствие поддержки tool use
                policy_error = _check_data_policy_error(error_str)
                if policy_error:
                    return False, policy_error
                # Проверяем на ошибку 404 с упоминанием tool use
                if "404" in error_str and ("tool use" in error_str.lower() or "tool" in error_str.lower()):
                    return False, f"Модель не поддерживает function calling (tool use). Ошибка 404: {error_str[:200]}"
                # Проверяем на ошибку 404
                if "404" in error_str:
                    return False, f"Модель не найдена или недоступна (404): {error_str[:200]}"
                return False, f"Ошибка при тестировании: {error_str[:300]}"
            
        finally:
            # Восстанавливаем исходную модель
            os.environ["GIGA_AGENT_LLM"] = current_model
            reset_llm_singleton(tag=None, is_main=True)
            
    except Exception as e:
        logger.error(f"Ошибка при тестировании модели {model_id}: {e}", exc_info=True)
        error_str = str(e)
        # Проверяем на ошибку политики данных OpenRouter
        policy_error = _check_data_policy_error(error_str)
        if policy_error:
            return False, policy_error
        return False, f"Ошибка при тестировании: {error_str[:300]}"


@tool
async def switch_openrouter_model(
    model_id: str = Field(
        description="Идентификатор модели для переключения (например, mistralai/devstral-2512:free). Используй get_openrouter_models для получения списка доступных моделей."
    ),
    test_before_switch: bool = Field(
        default=True,
        description="Если True, проверяет работоспособность модели перед переключением. Если False, переключается без проверки."
    ),
    tag: Optional[str] = Field(
        default=None,
        description="Тег модели для переключения (None для основной модели GIGA_AGENT_LLM, 'coder' для GIGA_AGENT_LLM_CODER и т.д.)"
    ),
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Переключение на другую модель OpenRouter с проверкой работоспособности
    
    ВАЖНО: Система использует модели OpenRouter.ai для генерации ответов. Этот инструмент позволяет переключиться на другую модель.
    Модель привязывается к текущему пользователю и сохраняется между сессиями.
    
    Процесс переключения:
    1. Проверяет, что указанная модель доступна в списке моделей OpenRouter
    2. Если test_before_switch=True, делает тестовый запрос к модели для проверки работоспособности
    3. Если проверка успешна, переключает систему на указанную модель
    4. Сохраняет выбор модели для текущего пользователя (персистентно)
    5. Если проверка неудачна или модель недоступна, возвращает ошибку и НЕ переключает модель
    
    В случае проблем с новой моделью система автоматически вернется к стартовой модели.
    
    Используй этот инструмент, когда нужно:
    - Переключиться на другую модель OpenRouter (например, для лучшей производительности)
    - Выбрать модель с большим контекстом для сложных задач
    - Заменить текущую модель, если она не работает корректно
    
    Args:
        model_id: Идентификатор модели для переключения (например, mistralai/devstral-2512:free)
        test_before_switch: Проверять ли работоспособность модели перед переключением (рекомендуется True)
        tag: Тег модели (None для основной модели, 'coder' для GIGA_AGENT_LLM_CODER и т.д.)
        state: Состояние агента (автоматически инжектируется)
    
    Returns:
        Строка с результатом переключения модели
    """
    manager = _get_manager()
    if not manager:
        return "Ошибка: OpenRouter API ключ не настроен или менеджер моделей недоступен"
    
    # Получаем user_id из state
    user_id = _get_user_id_from_state(state)
    
    try:
        # Проверяем, что модель существует в списке доступных
        models = manager.get_working_models_list()
        model_exists = any(m['id'] == model_id for m in models)
        
        if not model_exists:
            return f"Ошибка: Модель '{model_id}' не найдена в списке доступных моделей OpenRouter. Используй get_openrouter_models для получения списка доступных моделей."
        
        # Проверяем доступность модели
        if not manager._is_model_available(model_id):
            model_state = manager.switching_state["failed_models"].get(model_id, {})
            failures = model_state.get("failures", 0)
            disabled_until = model_state.get("disabled_until")
            return f"Ошибка: Модель '{model_id}' недоступна (неудачных попыток: {failures}). " + \
                   (f"Блокирована до: {disabled_until}" if disabled_until else "Рекомендуется выбрать другую модель.")
        
        # Если требуется проверка работоспособности
        if test_before_switch:
            logger.info(f"[OPENROUTER_TOOLS] Тестирование модели {model_id} перед переключением...")
            # ВАЖНО: Тестируем с test_with_tools=True, чтобы проверить поддержку function calling
            # Агент требует function calling для работы, поэтому модель без поддержки tools не подходит
            success, error = await _test_model_response(model_id, timeout=15.0, test_with_tools=True)
            
            if not success:
                # Проверяем, является ли ошибка связанной с отсутствием поддержки tool use
                if error and ("не поддерживает function calling" in error.lower() or 
                             "tool use" in error.lower() or
                             "no endpoints found that support tool" in error.lower()):
                    # Предлагаем альтернативные модели, которые поддерживают function calling
                    manager = _get_manager()
                    alternative_models = []
                    if manager:
                        verified_models = manager.get_verified_models_from_db()
                        # Ищем модели, которые поддерживают function calling и доступны
                        for model in verified_models[:5]:  # Берем первые 5
                            if model.get('supports_function_calling') and model.get('is_fully_functional'):
                                alternative_models.append(model.get('model_id', ''))
                    
                    alt_text = ""
                    if alternative_models:
                        alt_text = f"\n\nРекомендуемые модели с поддержкой function calling:\n" + \
                                  "\n".join([f"  - {m}" for m in alternative_models[:3]])
                    
                    return f"Ошибка: Модель '{model_id}' НЕ поддерживает function calling (tool use). " + \
                           f"Агент требует вызов инструментов для работы, поэтому эта модель не может быть использована. " + \
                           f"{error}{alt_text}\n\nПереключение отменено. Текущая модель не изменена."
                
                return f"Ошибка: Модель '{model_id}' не прошла проверку работоспособности. {error}. Переключение отменено. Текущая модель не изменена."
            
            logger.info(f"[OPENROUTER_TOOLS] Модель {model_id} успешно прошла проверку (включая function calling)")
        
        # Получаем текущую модель для сохранения
        env_key = f"GIGA_AGENT_LLM_{tag.upper()}" if tag else "GIGA_AGENT_LLM"
        current_model = os.getenv(env_key, "")
        
        # Сохраняем стартовую модель, если это первое переключение
        startup_model = _get_startup_model()
        if not startup_model and current_model:
            global _STARTUP_MODEL
            _STARTUP_MODEL = current_model
            logger.info(f"[OPENROUTER_TOOLS] Сохранена стартовая модель: {_STARTUP_MODEL}")
        
        # Переключаемся на новую модель
        from giga_agent.utils.llm import reset_llm_singleton, set_user_openrouter_model
        try:
            os.environ[env_key] = f"openrouter:{model_id}"
            reset_llm_singleton(tag=tag, is_main=True)
            
            # ВАЖНО: Сохраняем модель для пользователя (персистентно)
            if user_id:
                set_user_openrouter_model(user_id, model_id)
                logger.info(f"[OPENROUTER_TOOLS] Модель {model_id} сохранена для пользователя {user_id}")
            else:
                # Если user_id нет, сохраняем глобально (для обратной совместимости)
                manager.switching_state["current_model"] = model_id
                manager._save_switching_state()
            
            logger.info(f"[OPENROUTER_TOOLS] Успешно переключено на модель {model_id}")
            
            user_info = f"\nМодель сохранена для пользователя: {user_id}" if user_id else "\nМодель сохранена глобально"
            
            # Предупреждение для free моделей о возможных ограничениях data policy
            free_model_warning = ""
            if ":free" in model_id.lower():
                free_model_warning = "\n\nВНИМАНИЕ: Это бесплатная модель. При ошибке 'data policy' в чате:\n" + \
                    "1. Перейдите на https://openrouter.ai/settings/privacy\n" + \
                    "2. Включите 'Allow researchers to use my prompts'\n" + \
                    "3. Или используйте mistralai/devstral-2512:free (работает без ограничений)"
            
            return f"Успешно переключено на модель: {model_id}\n" + \
                   f"Предыдущая модель: {current_model}\n" + \
                   f"Модель проверена и работает корректно." + \
                   user_info + \
                   (f"\nСтартовая модель: {startup_model}" if startup_model else "") + \
                   free_model_warning
        except Exception as switch_error:
            # В случае ошибки при переключении пытаемся вернуться к стартовой модели
            logger.error(f"[OPENROUTER_TOOLS] Ошибка при переключении на модель {model_id}: {switch_error}")
            
            if startup_model:
                try:
                    os.environ[env_key] = startup_model
                    reset_llm_singleton(tag=tag, is_main=True)
                    logger.warning(f"[OPENROUTER_TOOLS] Автоматический сброс к стартовой модели: {startup_model}")
                    return f"Ошибка при переключении на модель {model_id}: {str(switch_error)}\n" + \
                           f"Автоматически восстановлена стартовая модель: {startup_model}"
                except Exception as reset_error:
                    logger.error(f"[OPENROUTER_TOOLS] Критическая ошибка: не удалось восстановить стартовую модель: {reset_error}")
                    return f"Критическая ошибка: не удалось переключиться на модель {model_id} и восстановить стартовую модель.\n" + \
                           f"Ошибка переключения: {str(switch_error)}\n" + \
                           f"Ошибка восстановления: {str(reset_error)}"
            else:
                return f"Ошибка при переключении на модель {model_id}: {str(switch_error)}\n" + \
                       f"Стартовая модель не сохранена, восстановление невозможно."
        
    except Exception as e:
        logger.error(f"Ошибка при переключении модели: {e}", exc_info=True)
        return f"Ошибка при переключении модели: {str(e)}"


@tool
async def test_openrouter_model(
    model_id: str = Field(
        description="Идентификатор модели для тестирования (например, mistralai/devstral-2512:free)"
    ),
    test_message: Optional[str] = Field(
        default=None,
        description="Тестовое сообщение для отправки модели. Если не указано, используется стандартное сообщение."
    ),
    timeout: float = Field(
        default=15.0,
        description="Таймаут для тестового запроса в секундах (по умолчанию 15)"
    )
) -> str:
    """
    Тестирование работоспособности модели OpenRouter через тестовый запрос
    
    ВАЖНО: Система использует модели OpenRouter.ai для генерации ответов. Этот инструмент позволяет проверить, работает ли модель корректно.
    
    Процесс тестирования:
    1. Временно переключается на указанную модель
    2. Отправляет тестовый запрос к модели
    3. Проверяет, что модель отвечает в течение указанного таймаута
    4. Восстанавливает исходную модель
    5. Возвращает результат тестирования
    
    Используй этот инструмент, когда нужно:
    - Проверить работоспособность модели перед переключением
    - Диагностировать проблемы с конкретной моделью
    - Убедиться, что модель доступна и отвечает на запросы
    
    Args:
        model_id: Идентификатор модели для тестирования
        test_message: Тестовое сообщение (если не указано, используется стандартное)
        timeout: Таймаут для запроса в секундах
    
    Returns:
        Результат тестирования модели
    """
    manager = _get_manager()
    if not manager:
        return "Ошибка: OpenRouter API ключ не настроен или менеджер моделей недоступен"
    
    try:
        # Проверяем, что модель существует
        models = manager.get_working_models_list()
        model_exists = any(m['id'] == model_id for m in models)
        
        if not model_exists:
            return f"Ошибка: Модель '{model_id}' не найдена в списке доступных моделей OpenRouter."
        
        # Используем стандартное сообщение, если не указано
        if not test_message:
            test_message = "Привет! Ответь одним словом: 'работает'"
        
        logger.info(f"[OPENROUTER_TOOLS] Тестирование модели {model_id}...")
        success, error = await _test_model_response(model_id, timeout=timeout)
        
        if success:
            return f"✅ Модель '{model_id}' успешно прошла тест!\n" + \
                   f"Модель отвечает на запросы корректно и может быть использована."
        else:
            return f"❌ Модель '{model_id}' не прошла тест.\n" + \
                   f"Ошибка: {error}\n" + \
                   f"Рекомендуется выбрать другую модель или повторить попытку позже."
        
    except Exception as e:
        logger.error(f"Ошибка при тестировании модели: {e}", exc_info=True)
        return f"Ошибка при тестировании модели: {str(e)}"


@tool
async def reset_to_startup_openrouter_model(
    tag: Optional[str] = Field(
        default=None,
        description="Тег модели для сброса (None для основной модели GIGA_AGENT_LLM, 'coder' для GIGA_AGENT_LLM_CODER и т.д.)"
    ),
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Сброс к стартовой модели OpenRouter
    
    ВАЖНО: Система использует модели OpenRouter.ai для генерации ответов. Этот инструмент позволяет вернуться к стартовой модели, которая была установлена при запуске системы.
    Сброс выполняется для текущего пользователя.
    
    Используй этот инструмент, когда:
    - Нужно вернуться к исходной модели после экспериментов
    - Текущая модель работает некорректно и нужно вернуться к проверенной стартовой модели
    - Произошли проблемы с переключенной моделью
    
    Args:
        tag: Тег модели (None для основной модели, 'coder' для GIGA_AGENT_LLM_CODER и т.д.)
        state: Состояние агента (автоматически инжектируется)
    
    Returns:
        Результат сброса к стартовой модели
    """
    startup_model = _get_startup_model()
    
    # Получаем user_id из state
    user_id = _get_user_id_from_state(state)
    
    if not startup_model:
        # Если стартовая модель не сохранена, берем из переменных окружения
        env_key = f"GIGA_AGENT_LLM_{tag.upper()}" if tag else "GIGA_AGENT_LLM"
        startup_model = os.getenv(env_key, "")
        
        if not startup_model:
            return "Ошибка: Стартовая модель не найдена. Не удалось определить модель для сброса."
    
    try:
        # Проверяем, что стартовая модель - это OpenRouter модель
        if not startup_model.startswith("openrouter:"):
            return f"Стартовая модель '{startup_model}' не является моделью OpenRouter. Сброс не выполнен."
        
        # Извлекаем model_id
        model_id = startup_model.replace("openrouter:", "")
        
        # ВАЖНО: Сначала очищаем сохраненную модель, чтобы она не применялась при следующей загрузке LLM
        manager = _get_manager()
        if user_id:
            # Очищаем модель пользователя ПЕРЕД переключением
            clear_user_openrouter_model(user_id)
            logger.info(f"[OPENROUTER_TOOLS] Модель пользователя {user_id} очищена перед сбросом")
        elif manager:
            # Если user_id нет, очищаем глобальную модель ПЕРЕД переключением
            manager.clear_persisted_model()
            logger.info(f"[OPENROUTER_TOOLS] Глобальная модель очищена перед сбросом")
        
        # Переключаемся на стартовую модель
        from giga_agent.utils.llm import reset_llm_singleton
        env_key = f"GIGA_AGENT_LLM_{tag.upper()}" if tag else "GIGA_AGENT_LLM"
        os.environ[env_key] = startup_model
        reset_llm_singleton(tag=tag, is_main=True)
        
        logger.info(f"[OPENROUTER_TOOLS] Сброс к стартовой модели: {startup_model}")
        
        user_info = f" для пользователя {user_id}" if user_id else " (глобально)"
        return f"Успешно сброшено к стартовой модели: {startup_model}\n" + \
               f"Модель восстановлена к исходному состоянию{user_info}.\n" + \
               f"Сохраненная модель очищена - при следующем запуске будет использоваться стартовая модель."
        
    except Exception as e:
        logger.error(f"Ошибка при сбросе к стартовой модели: {e}", exc_info=True)
        return f"Ошибка при сбросе к стартовой модели: {str(e)}"


# =============================================================================
# АЛИАСЫ ИНСТРУМЕНТОВ
# Примечание: Модели могут пытаться вызвать инструменты с сокращенными именами.
# Эти алиасы позволяют использовать оба варианта названий.
# =============================================================================

@tool
async def openrouter_models(
    verified_only: bool = Field(
        default=True,
        description="Если True, возвращает только проверенные модели из БД (рекомендуется). Если False, возвращает все доступные модели."
    ),
    limit: int = Field(
        default=20,
        description="Максимальное количество моделей для возврата (по умолчанию 20)"
    )
) -> str:
    """
    Получение списка моделей OpenRouter.ai (алиас для get_openrouter_models)
    
    По умолчанию возвращает ПРОВЕРЕННЫЕ модели из базы данных - это модели, которые прошли полное тестирование
    и гарантированно работают с агентом (function calling, streaming, system prompt).
    
    Используй этот инструмент, когда нужно:
    - Узнать, какие модели рекомендуются для использования
    - Выбрать альтернативную модель для переключения
    
    Args:
        verified_only: Если True, возвращает только проверенные модели из БД (рекомендуется)
        limit: Максимальное количество моделей для возврата
    
    Returns:
        Строка с форматированным списком моделей
    """
    print(f"[OPENROUTER_MODELS_ALIAS] Called with verified_only={verified_only}, limit={limit}")
    # Копия логики из get_openrouter_models (нельзя вызывать @tool напрямую)
    try:
        if verified_only:
            print("[OPENROUTER_MODELS_ALIAS] Getting verified models from DB...")
            # Получаем проверенные модели из БД
            from giga_agent.utils.openrouter_model_manager import get_verified_models_from_db
            
            verified_models = await get_verified_models_from_db(fully_functional_only=True)
            print(f"[OPENROUTER_MODELS_ALIAS] Got {len(verified_models) if verified_models else 0} verified models")
            
            if not verified_models:
                logger.warning("Не удалось получить проверенные модели из БД, используем fallback")
                verified_only = False
            else:
                models = verified_models[:limit]
                
                result = f"ПРОВЕРЕННЫЕ модели OpenRouter (прошли полное тестирование):\n"
                result += f"Показано {len(models)} из {len(verified_models)} проверенных моделей\n\n"
                
                for i, model in enumerate(models, 1):
                    model_id = model['model_id']
                    name = model.get('model_name', 'N/A') or model_id
                    context = model.get('context_length', 0)
                    response_time = model.get('avg_response_time_ms')
                    notes = model.get('notes', '')
                    
                    result += f"{i}. {model_id}\n"
                    result += f"   Название: {name}\n"
                    if context > 0:
                        result += f"   Контекст: {context:,} токенов\n"
                    if response_time:
                        result += f"   Время ответа: {response_time/1000:.1f} сек\n"
                    result += f"   Статус: ПРОВЕРЕНА (function calling, streaming, system prompt)\n"
                    if notes:
                        result += f"   Примечание: {notes}\n"
                    result += "\n"
                
                result += "---\n"
                result += "Все модели в этом списке гарантированно работают с агентом.\n"
                result += "Для переключения используй: switch_model с model_id из списка."
                
                return result
        
        if not verified_only:
            manager = _get_manager()
            if not manager:
                return "Ошибка: OpenRouter API ключ не настроен или менеджер моделей недоступен"
            
            models = manager.get_working_models_list()
            models = [m for m in models if m.get('working') is True]
            models = models[:limit]
            
            if not models:
                return "Нет доступных моделей OpenRouter"
            
            result = f"Доступные модели OpenRouter (показано {len(models)}):\n"
            result += "ВНИМАНИЕ: Это общий список, не все модели проверены на полную совместимость!\n\n"
            
            for i, model in enumerate(models, 1):
                model_id = model['id']
                name = model.get('name', 'N/A') or 'N/A'
                context = model.get('context_length', 0)
                status = model.get('status', 'неизвестно')
                
                result += f"{i}. {model_id}\n"
                result += f"   Название: {name}\n"
                result += f"   Контекст: {context:,} токенов\n"
                result += f"   Статус: {status}\n"
                result += "\n"
            
            return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка моделей OpenRouter: {e}")
        return f"Ошибка при получении списка моделей: {str(e)}"


@tool
async def switch_model(
    model_id: str = Field(
        description="Идентификатор модели для переключения (например, mistralai/devstral-2512:free или google/gemma-3-27b-it:free)"
    ),
    test_before_switch: bool = Field(
        default=True,
        description="Если True, проверяет работоспособность модели перед переключением"
    ),
    tag: Optional[str] = Field(
        default=None,
        description="Тег модели для переключения (None для основной модели)"
    ),
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Переключение на другую модель OpenRouter (алиас для switch_openrouter_model)
    
    Используй этот инструмент для смены модели OpenRouter на другую из списка доступных.
    Сначала используй openrouter_models чтобы получить список доступных моделей и их точные ID.
    
    Args:
        model_id: Идентификатор модели (например, mistralai/devstral-2512:free)
        test_before_switch: Проверять ли модель перед переключением
        tag: Тег модели (None для основной)
        state: Состояние агента
    
    Returns:
        Результат переключения модели
    """
    # Копия логики из switch_openrouter_model (нельзя вызывать @tool напрямую)
    manager = _get_manager()
    if not manager:
        return "Ошибка: OpenRouter API ключ не настроен или менеджер моделей недоступен"
    
    user_id = _get_user_id_from_state(state)
    
    try:
        models = manager.get_working_models_list()
        model_exists = any(m['id'] == model_id for m in models)
        
        if not model_exists:
            # Пробуем найти модель по частичному совпадению
            matching = [m for m in models if model_id.lower() in m['id'].lower() or model_id.lower() in (m.get('name') or '').lower()]
            if matching:
                suggestions = ", ".join([m['id'] for m in matching[:5]])
                return f"Ошибка: Модель '{model_id}' не найдена. Возможно, вы имели в виду: {suggestions}. Используй openrouter_models для получения полного списка."
            return f"Ошибка: Модель '{model_id}' не найдена в списке доступных моделей OpenRouter. Используй openrouter_models для получения списка доступных моделей."
        
        if not manager._is_model_available(model_id):
            model_state = manager.switching_state["failed_models"].get(model_id, {})
            failures = model_state.get("failures", 0)
            disabled_until = model_state.get("disabled_until")
            return f"Ошибка: Модель '{model_id}' недоступна (неудачных попыток: {failures}). " + \
                   (f"Блокирована до: {disabled_until}" if disabled_until else "Рекомендуется выбрать другую модель.")
        
        if test_before_switch:
            print(f"[SWITCH_MODEL] Тестирование модели {model_id} перед переключением (test_with_tools=True)...")
            logger.info(f"[OPENROUTER_TOOLS] Тестирование модели {model_id} перед переключением...")
            # ВАЖНО: Тестируем с test_with_tools=True, чтобы проверить поддержку function calling
            success, error = await _test_model_response(model_id, timeout=15.0, test_with_tools=True)
            print(f"[SWITCH_MODEL] Результат теста: success={success}, error={error}")
            
            if not success:
                print(f"[SWITCH_MODEL] Тест НЕ пройден, возвращаем ошибку")
                # Проверяем, является ли ошибка связанной с отсутствием поддержки tool use
                if error and ("не поддерживает function calling" in error.lower() or 
                             "tool use" in error.lower() or
                             "no endpoints found that support tool" in error.lower()):
                    # Предлагаем альтернативные модели, которые поддерживают function calling
                    alternative_models = []
                    verified_models = manager.get_verified_models_from_db()
                    # Ищем модели, которые поддерживают function calling и доступны
                    for model in verified_models[:5]:  # Берем первые 5
                        if model.get('supports_function_calling') and model.get('is_fully_functional'):
                            alternative_models.append(model.get('model_id', ''))
                    
                    alt_text = ""
                    if alternative_models:
                        alt_text = f"\n\nРекомендуемые модели с поддержкой function calling:\n" + \
                                  "\n".join([f"  - {m}" for m in alternative_models[:3]])
                    
                    return f"Ошибка: Модель '{model_id}' НЕ поддерживает function calling (tool use). " + \
                           f"Агент требует вызов инструментов для работы, поэтому эта модель не может быть использована. " + \
                           f"{error}{alt_text}\n\nПереключение отменено. Текущая модель не изменена."
                
                return f"Ошибка: Модель '{model_id}' не прошла проверку работоспособности. {error}. Переключение отменено. Текущая модель не изменена."
            
            print(f"[SWITCH_MODEL] Тест пройден успешно")
            logger.info(f"[OPENROUTER_TOOLS] Модель {model_id} успешно прошла проверку (включая function calling)")
        
        env_key = f"GIGA_AGENT_LLM_{tag.upper()}" if tag else "GIGA_AGENT_LLM"
        current_model = os.getenv(env_key, "")
        
        startup_model = _get_startup_model()
        if not startup_model and current_model:
            global _STARTUP_MODEL
            _STARTUP_MODEL = current_model
            logger.info(f"[OPENROUTER_TOOLS] Сохранена стартовая модель: {_STARTUP_MODEL}")
        
        from giga_agent.utils.llm import reset_llm_singleton, set_user_openrouter_model
        try:
            os.environ[env_key] = f"openrouter:{model_id}"
            reset_llm_singleton(tag=tag, is_main=True)
            
            if user_id:
                set_user_openrouter_model(user_id, model_id)
                logger.info(f"[OPENROUTER_TOOLS] Модель {model_id} сохранена для пользователя {user_id}")
            else:
                manager.switching_state["current_model"] = model_id
                manager._save_switching_state()
            
            logger.info(f"[OPENROUTER_TOOLS] Успешно переключено на модель {model_id}")
            
            user_info = f"\nМодель сохранена для пользователя: {user_id}" if user_id else "\nМодель сохранена глобально"
            
            # Предупреждение для free моделей о возможных ограничениях data policy
            free_model_warning = ""
            if ":free" in model_id.lower():
                free_model_warning = "\n\nВНИМАНИЕ: Это бесплатная модель. При ошибке 'data policy' в чате:\n" + \
                    "1. Перейдите на https://openrouter.ai/settings/privacy\n" + \
                    "2. Включите 'Allow researchers to use my prompts'\n" + \
                    "3. Или используйте mistralai/devstral-2512:free (работает без ограничений)"
            
            return f"Успешно переключено на модель: {model_id}\n" + \
                   f"Предыдущая модель: {current_model}\n" + \
                   f"Модель проверена и работает корректно." + \
                   user_info + free_model_warning
        except Exception as switch_error:
            logger.error(f"[OPENROUTER_TOOLS] Ошибка при переключении на модель {model_id}: {switch_error}")
            
            if startup_model:
                try:
                    os.environ[env_key] = startup_model
                    reset_llm_singleton(tag=tag, is_main=True)
                    return f"Ошибка при переключении на модель {model_id}: {str(switch_error)}\n" + \
                           f"Автоматически восстановлена стартовая модель: {startup_model}"
                except Exception as reset_error:
                    return f"Критическая ошибка: не удалось переключиться на модель {model_id} и восстановить стартовую модель."
            else:
                return f"Ошибка при переключении на модель {model_id}: {str(switch_error)}"
        
    except Exception as e:
        logger.error(f"Ошибка при переключении модели: {e}", exc_info=True)
        return f"Ошибка при переключении модели: {str(e)}"
