"""
Узел для авторизации через browser-service с использованием номера телефона из секретов
"""

import logging
from typing import Dict
from langchain_core.messages import AIMessage, HumanMessage
from giga_agent.agents.career_agent.config import CareerAgentState
from giga_agent.agents.browser_use import browser_task

logger = logging.getLogger(__name__)


def get_phone_from_secrets(user_id: str, secrets: list) -> str:
    """
    Получает номер телефона из секретов пользователя.
    
    Args:
        user_id: Идентификатор пользователя
        secrets: Список секретов пользователя
    
    Returns:
        Номер телефона или None
    """
    # Ищем номер телефона в секретах по различным возможным именам
    phone_keywords = ["phone", "телефон", "phone_number", "номер_телефона", "mobile", "мобильный"]
    
    for secret in secrets:
        name = secret.get("name", "").lower()
        value = secret.get("value", "").strip()
        
        # Проверяем, содержит ли имя секрета ключевые слова
        if any(keyword in name for keyword in phone_keywords) and value:
            # Очищаем номер от лишних символов, оставляем только цифры и +
            cleaned_phone = ''.join(c for c in value if c.isdigit() or c == '+')
            if cleaned_phone:
                logger.info(f"[REQUEST_AUTH] Найден номер телефона в секрете '{secret.get('name')}': {cleaned_phone[:5]}***")
                return cleaned_phone
    
    logger.warning(f"[REQUEST_AUTH] Номер телефона не найден в секретах пользователя {user_id}")
    return None


async def request_auth_node(state: CareerAgentState) -> Dict:
    """
    Выполняет авторизацию через browser-service с использованием номера телефона из секретов.
    Процесс:
    1. Получает номер телефона из секретов пользователя
    2. Запускает browser-service для начала авторизации по телефону
    3. Запрашивает код из SMS у пользователя через сообщение
    4. Передает код в browser-service для ввода
    """
    messages = state.get("messages", [])
    if not messages:
        return {
            "messages": [AIMessage(content="Ошибка: нет сообщений для обработки")]
        }
    
    last_message = messages[-1]
    user_request = last_message.content if hasattr(last_message, 'content') else str(last_message)
    user_request_lower = user_request.lower()
    
    # Проверяем, не является ли это кодом из SMS (4-6 цифр)
    import re
    code_match = re.search(r'\b\d{4,6}\b', user_request.strip())
    waiting_for_code = state.get("auth_waiting_for_code", False)
    auth_session_id = state.get("auth_session_id")
    
    if code_match and waiting_for_code and auth_session_id:
        # Это код из SMS, передаем его в browser-service
        code = code_match.group(0)
        logger.info(f"[REQUEST_AUTH] Получен код из SMS: {code[:2]}***")
        
        try:
            # Используем browser_task для передачи кода
            # Формируем задачу для передачи кода
            browser_task_text = f"Введи код {code} для завершения авторизации"
            
            # Вызываем browser_task с кодом
            # Для этого нужно использовать прямой вызов WebSocket, так как browser_task не поддерживает параметр code
            # Вместо этого используем специальную команду через browser_task
            import os
            import websockets
            import json
            
            browser_service_host = os.getenv("BROWSER_SERVICE_HOST", "browser-service")
            browser_service_port = os.getenv("BROWSER_SERVICE_PORT", "7070")
            url = f"ws://{browser_service_host}:{browser_service_port}/ws?session_id={auth_session_id}"
            
            try:
                async with websockets.connect(url) as ws:
                    # Отправляем команду ввода кода
                    await ws.send(json.dumps({
                        "command": "enter_code",
                        "code": code,
                        "session_id": auth_session_id
                    }))
                    
                    # Ждем ответа
                    result = None
                    async for message in ws:
                        data = json.loads(message)
                        msg_type = data.get("type")
                        if msg_type == "error":
                            result = {"error": data.get("message")}
                            break
                        if msg_type == "done":
                            result = {"success": data.get("success"), "message": data.get("message")}
                            break
                    
                    if result and result.get("success"):
                        # Убираем флаги ожидания кода
                        return {
                            "messages": [AIMessage(
                                content=f"✅ Авторизация на сайте выполнена успешно!\n\n"
                                       f"Сессия сохранена для последующих запросов."
                            )],
                            "auth_waiting_for_code": False,
                            "auth_session_id": None
                        }
                    else:
                        error_msg = result.get("error", "Неизвестная ошибка") if result else "Ошибка при вводе кода"
                        return {
                            "messages": [AIMessage(
                                content=f"❌ Ошибка при вводе кода: {error_msg}\n\n"
                                       f"Попробуйте ввести код еще раз."
                            )]
                        }
            except Exception as e:
                logger.error(f"[REQUEST_AUTH] Ошибка при передаче кода в browser-service: {e}", exc_info=True)
                return {
                    "messages": [AIMessage(
                        content=f"❌ Ошибка при вводе кода: {str(e)}"
                    )]
                }
        except Exception as e:
            logger.error(f"[REQUEST_AUTH] Ошибка при обработке кода: {e}", exc_info=True)
            return {
                "messages": [AIMessage(
                    content=f"❌ Ошибка при обработке кода: {str(e)}"
                )]
            }
    
    # Извлекаем URL сайта из запроса
    site_url = None
    if "hh.ru" in user_request_lower:
        site_url = "https://hh.ru"
    elif "работа.ру" in user_request_lower or "rabota.ru" in user_request_lower:
        site_url = "https://rabota.ru"
    elif "avito" in user_request_lower:
        site_url = "https://www.avito.ru"
    else:
        # Пытаемся извлечь URL из текста
        url_match = re.search(r'https?://[^\s]+', user_request)
        if url_match:
            site_url = url_match.group(0)
    
    if not site_url:
        return {
            "messages": [AIMessage(
                content="❌ Не удалось определить сайт для авторизации. Укажите сайт явно (например, hh.ru, Работа.ру)."
            )]
        }
    
    user_id = state.get("user_id", "default")
    session_id = f"{user_id}_{site_url.replace('https://', '').replace('http://', '').replace('/', '_')}"
    
    logger.info(f"[REQUEST_AUTH] Запрос авторизации на {site_url} для пользователя {user_id}, сессия: {session_id}")
    
    # Получаем секреты пользователя
    secrets = state.get("secrets", [])
    if not secrets:
        # Пытаемся загрузить секреты, если их нет в state
        try:
            from giga_agent.utils.user_tokens import get_all_user_secrets
            secrets = await get_all_user_secrets(user_id)
            logger.info(f"[REQUEST_AUTH] Загружено {len(secrets)} секретов для пользователя {user_id}")
        except Exception as e:
            logger.error(f"[REQUEST_AUTH] Ошибка при загрузке секретов: {e}", exc_info=True)
            return {
                "messages": [AIMessage(
                    content="❌ Ошибка при загрузке секретов пользователя. Убедитесь, что вы авторизованы."
                )]
            }
    
    # Получаем номер телефона из секретов
    phone_number = get_phone_from_secrets(user_id, secrets)
    
    if not phone_number:
        return {
            "messages": [AIMessage(
                content="❌ Номер телефона не найден в ваших секретах. "
                       "Пожалуйста, добавьте номер телефона в секреты пользователя "
                       "(например, с именем 'phone' или 'телефон')."
            )]
        }
    
    # Формируем задачу для browser-service
    # Задача будет включать номер телефона и инструкции по авторизации
    # ВАЖНО: Добавляем session_id в задачу, чтобы browser-service использовал правильную сессию
    browser_task_text = (
        f"Авторизуйся на {site_url} по номеру телефона {phone_number}. "
        f"Открой страницу входа, введи номер телефона {phone_number}, "
        f"запроси код из SMS и жди ввода кода от пользователя. "
        f"session_id: {session_id}"
    )
    
    logger.info(f"[REQUEST_AUTH] Запуск browser-service для авторизации на {site_url}")
    
    try:
        # Запускаем browser-service для начала авторизации
        # browser-service должен открыть страницу входа, ввести номер телефона и запросить код
        browser_result = await browser_task.ainvoke(browser_task_text)
        
        if browser_result.get("error"):
            error_msg = browser_result.get("error", "Неизвестная ошибка")
            logger.error(f"[REQUEST_AUTH] Ошибка browser-service: {error_msg}")
            return {
                "messages": [AIMessage(
                    content=f"❌ Ошибка при запуске авторизации: {error_msg}"
                )]
            }
        
        # Проверяем, требуется ли код
        if browser_result.get("requires_code"):
            # Сохраняем состояние ожидания кода
            return {
                "messages": [AIMessage(
                    content=f"✅ Начата авторизация на {site_url}.\n\n"
                           f"Номер телефона: {phone_number[:3]}***{phone_number[-2:]}\n\n"
                           f"📱 Пожалуйста, введите код из SMS, который пришел на ваш телефон."
                )],
                "auth_waiting_for_code": True,
                "auth_session_id": browser_result.get("session_id", session_id)
            }
        
        # Если авторизация завершена сразу (не должно быть, но на всякий случай)
        if browser_result.get("success"):
            return {
                "messages": [AIMessage(
                    content=f"✅ Авторизация на {site_url} выполнена успешно!"
                )]
            }
        
        # Если browser-service вернул обычное сообщение
        return {
            "messages": [AIMessage(
                content=browser_result.get("message", "Авторизация начата")
            )]
        }
        
    except Exception as e:
        logger.error(f"[REQUEST_AUTH] Ошибка при вызове browser-service: {e}", exc_info=True)
        return {
            "messages": [AIMessage(
                content=f"❌ Ошибка при выполнении авторизации: {str(e)}"
            )]
        }
