import json
import logging
import asyncio

from langchain_core.tools import tool
from urllib.parse import quote
from langgraph.graph.ui import push_ui_message
import websockets

logger = logging.getLogger(__name__)


@tool(parse_docstring=False)
async def browser_task(task: str):
    """
    Открывает браузер и выполняет задачу, которую ты поставишь ему.
    Может быть полезно, если нужно сделать какие-то действия на сайте.

    Args:
        task: Полный текст задачи
    """
    import os
    
    # Определяем URL браузерного сервиса
    # В Docker используем имя сервиса, локально - localhost
    browser_service_host = os.getenv("BROWSER_SERVICE_HOST", "browser-service")
    browser_service_port = os.getenv("BROWSER_SERVICE_PORT", "7070")
    
    # Извлекаем session_id из задачи, если указан
    session_id = "default"
    import re
    session_match = re.search(r'session_id[:\s]+(\w+)', task, re.IGNORECASE)
    if session_match:
        session_id = session_match.group(1)
    
    # Проверяем, запущены ли мы в Docker
    # Если переменная окружения не установлена, пробуем подключиться к browser-service
    # Если не получается, пробуем localhost
    url = f"ws://{browser_service_host}:{browser_service_port}/ws?task={quote(task)}&session_id={session_id}"
    
    push_ui_message(
        "agent_execution",
        {"agent": "browser_task", "node_text": "Запускаю браузер"},
    )
    
    try:
        # Используем asyncio.wait_for для совместимости с разными версиями asyncio
        async def _connect_and_process():
            async with websockets.connect(url) as ws:
                async for message in ws:
                    data = json.loads(message)

                    msg_type = data.get("type")
                    if msg_type == "error":
                        return {"error": data.get("message")}
                    if msg_type == "done":
                        return {
                            "success": data.get("success"), 
                            "message": data.get("message"),
                            "html": data.get("html"),
                            "structured_data": data.get("structured_data"),
                            "screenshot_base64": data.get("screenshot_base64"),
                            "url": data.get("url")
                        }
                    
                    # Проверяем, требуется ли код
                    if data.get("requires_code"):
                        return {
                            "requires_code": True,
                            "message": data.get("message"),
                            "session_id": data.get("session_id", session_id),
                            "html": data.get("html"),
                            "structured_data": data.get("structured_data"),
                            "screenshot_base64": data.get("screenshot_base64")
                        }

                    # Промежуточные данные шага
                    push_ui_message(
                        "agent_execution",
                        {
                            "agent": "browser_task",
                            "node_text": data.get("action"),
                            "image": data.get("screenshot_base64"),
                        },
                    )
        
        return await asyncio.wait_for(_connect_and_process(), timeout=300.0)  # 5 минут для авторизации
    except asyncio.TimeoutError:
        return {
            "error": "Таймаут при выполнении задачи. Возможно, задача требует больше времени для выполнения."
        }
    except (ConnectionRefusedError, OSError) as e:
        # Если не удалось подключиться к browser-service, пробуем localhost
        if browser_service_host != "localhost":
            logger.warning(f"Не удалось подключиться к {browser_service_host}, пробуем localhost")
            url = f"ws://localhost:{browser_service_port}/ws?task={quote(task)}"
            try:
                # Используем asyncio.wait_for для совместимости с разными версиями asyncio
                async def _connect_and_process():
                    async with websockets.connect(url) as ws:
                        async for message in ws:
                            data = json.loads(message)
                            msg_type = data.get("type")
                            if msg_type == "error":
                                return {"error": data.get("message")}
                            if msg_type == "done":
                                return {"success": data.get("success"), "message": data.get("message")}
                            push_ui_message(
                                "agent_execution",
                                {
                                    "agent": "browser_task",
                                    "node_text": data.get("action"),
                                    "image": data.get("screenshot_base64"),
                                },
                            )
                
                return await asyncio.wait_for(_connect_and_process(), timeout=300.0)  # 5 минут для авторизации
            except asyncio.TimeoutError:
                return {
                    "error": "Таймаут при выполнении задачи. Возможно, задача требует больше времени для выполнения."
                }
            except Exception as e2:
                return {
                    "error": f"Не удалось подключиться к браузерному сервису. "
                            f"Убедитесь, что browser-service запущен. "
                            f"Ошибка: {str(e2)}"
                }
        else:
            return {
                "error": f"Не удалось подключиться к браузерному сервису на {url}. "
                        f"Убедитесь, что browser-service запущен. "
                        f"Ошибка: {str(e)}"
            }
