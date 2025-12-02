"""
Узлы для работы с событиями в Google Calendar
"""

import logging
from datetime import datetime, timedelta
from typing import Annotated, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.google_api import calendar_client
from ..utils.oauth_manager import oauth_manager

logger = logging.getLogger(__name__)

@tool
async def create_event(
    user_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    all_day: bool = False,
    state: Annotated[dict, InjectedState] = None
):
    """
    Создание события в Google Calendar
    
    Args:
        user_id: Идентификатор пользователя
        title: Название события
        start_datetime: Дата и время начала в формате ISO (например, 2024-01-15T10:00:00)
        end_datetime: Дата и время окончания в формате ISO (например, 2024-01-15T11:00:00)
        description: Описание события (необязательно)
        all_day: Событие на весь день (по умолчанию False)
    """
    try:
        # Проверяем авторизацию
        if not oauth_manager.is_authenticated(user_id):
            return {
                "error": True,
                "message": "❌ **Не подключен Google Calendar**\n\nДля создания событий сначала подключите календарь командой: \"подключить календарь\""
            }
        
        # Создаем событие
        result = await calendar_client.create_event(
            user_id=user_id,
            title=title,
            description=description,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            all_day=all_day
        )
        
        if 'error' in result:
            return {
                "error": True,
                "message": f"❌ **Ошибка создания события:**\n{result['error']}\n\n📝 {result.get('details', '')}"
            }
        
        event_id = result.get('id', 'неизвестно')
        event_link = result.get('htmlLink', '')
        
        # Форматируем время для отображения
        try:
            start_dt = datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_datetime.replace('Z', '+00:00'))
            
            if all_day:
                time_info = f"📅 {start_dt.strftime('%d.%m.%Y')}"
            else:
                time_info = f"⏰ {start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}"
        except:
            time_info = f"⏰ {start_datetime} - {end_datetime}"
        
        message = f"""✅ **Событие создано успешно!**

📋 **{title}**
{time_info}"""
        
        if description:
            message += f"\n📝 {description}"
        
        if event_link:
            message += f"\n\n🔗 [Открыть в Google Calendar]({event_link})"
        
        message += f"\n\n🆔 ID события: `{event_id}`"
        
        return {
            "success": True,
            "message": message,
            "event_id": event_id,
            "event_link": event_link
        }
        
    except Exception as e:
        logger.error(f"Ошибка создания события: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка создания события:** {str(e)}"
        }

@tool
async def list_events(
    user_id: str,
    max_results: int = 10,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None
):
    """
    Получение списка событий из Google Calendar
    
    Args:
        user_id: Идентификатор пользователя
        max_results: Максимальное количество событий (по умолчанию 10)
        time_min: Минимальная дата в формате ISO (по умолчанию - сейчас)
        time_max: Максимальная дата в формате ISO (необязательно)
    """
    try:
        # Проверяем авторизацию
        if not oauth_manager.is_authenticated(user_id):
            return {
                "error": True,
                "message": "❌ **Не подключен Google Calendar**\n\nДля просмотра событий сначала подключите календарь командой: \"подключить календарь\""
            }
        
        # Получаем события
        result = await calendar_client.list_events(
            user_id=user_id,
            max_results=max_results,
            time_min=time_min,
            time_max=time_max
        )
        
        if 'error' in result:
            return {
                "error": True,
                "message": f"❌ **Ошибка получения событий:**\n{result['error']}\n\n📝 {result.get('details', '')}"
            }
        
        # Форматируем список событий
        formatted_events = calendar_client.format_events_list(result)
        
        return {
            "success": True,
            "message": formatted_events,
            "events_count": len(result.get('items', []))
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения событий: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения событий:** {str(e)}"
        }

@tool
async def update_event(
    user_id: str,
    event_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None
):
    """
    Обновление события в Google Calendar
    
    Args:
        user_id: Идентификатор пользователя
        event_id: ID события для обновления
        title: Новое название события (необязательно)
        description: Новое описание события (необязательно)
        start_datetime: Новая дата и время начала в формате ISO (необязательно)
        end_datetime: Новая дата и время окончания в формате ISO (необязательно)
    """
    try:
        # Проверяем авторизацию
        if not oauth_manager.is_authenticated(user_id):
            return {
                "error": True,
                "message": "❌ **Не подключен Google Calendar**\n\nДля обновления событий сначала подключите календарь командой: \"подключить календарь\""
            }
        
        # Обновляем событие
        result = await calendar_client.update_event(
            user_id=user_id,
            event_id=event_id,
            title=title,
            description=description,
            start_datetime=start_datetime,
            end_datetime=end_datetime
        )
        
        if 'error' in result:
            return {
                "error": True,
                "message": f"❌ **Ошибка обновления события:**\n{result['error']}\n\n📝 {result.get('details', '')}"
            }
        
        event_title = result.get('summary', 'Событие')
        event_link = result.get('htmlLink', '')
        
        message = f"""✅ **Событие обновлено!**

📋 **{event_title}**"""
        
        if title:
            message += f"\n📝 Название изменено"
        if description is not None:
            message += f"\n📝 Описание обновлено"
        if start_datetime or end_datetime:
            message += f"\n⏰ Время изменено"
        
        if event_link:
            message += f"\n\n🔗 [Открыть в Google Calendar]({event_link})"
        
        return {
            "success": True,
            "message": message,
            "event_id": event_id
        }
        
    except Exception as e:
        logger.error(f"Ошибка обновления события: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка обновления события:** {str(e)}"
        }

@tool
async def delete_event(
    user_id: str,
    event_id: str,
    state: Annotated[dict, InjectedState] = None
):
    """
    Удаление события из Google Calendar
    
    Args:
        user_id: Идентификатор пользователя
        event_id: ID события для удаления
    """
    try:
        # Проверяем авторизацию
        if not oauth_manager.is_authenticated(user_id):
            return {
                "error": True,
                "message": "❌ **Не подключен Google Calendar**\n\nДля удаления событий сначала подключите календарь командой: \"подключить календарь\""
            }
        
        # Сначала получаем информацию о событии
        event_info = await calendar_client.get_event(user_id, event_id)
        event_title = event_info.get('summary', 'Событие') if 'error' not in event_info else 'Событие'
        
        # Удаляем событие
        result = await calendar_client.delete_event(user_id, event_id)
        
        if 'error' in result:
            return {
                "error": True,
                "message": f"❌ **Ошибка удаления события:**\n{result['error']}\n\n📝 {result.get('details', '')}"
            }
        
        return {
            "success": True,
            "message": f"""✅ **Событие удалено**

🗑️ **{event_title}** удалено из календаря

📋 ID события: `{event_id}`"""
        }
        
    except Exception as e:
        logger.error(f"Ошибка удаления события: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка удаления события:** {str(e)}"
        }

@tool
async def get_event_details(
    user_id: str,
    event_id: str,
    state: Annotated[dict, InjectedState] = None
):
    """
    Получение подробной информации о событии
    
    Args:
        user_id: Идентификатор пользователя
        event_id: ID события
    """
    try:
        # Проверяем авторизацию
        if not oauth_manager.is_authenticated(user_id):
            return {
                "error": True,
                "message": "❌ **Не подключен Google Calendar**\n\nДля просмотра событий сначала подключите календарь командой: \"подключить календарь\""
            }
        
        # Получаем событие
        result = await calendar_client.get_event(user_id, event_id)
        
        if 'error' in result:
            return {
                "error": True,
                "message": f"❌ **Событие не найдено:**\n{result['error']}\n\n📝 {result.get('details', '')}"
            }
        
        # Форматируем информацию о событии
        title = result.get('summary', 'Без названия')
        description = result.get('description', '')
        location = result.get('location', '')
        
        start = result.get('start', {})
        end = result.get('end', {})
        start_time = calendar_client.format_event_time(start)
        end_time = calendar_client.format_event_time(end)
        
        created = result.get('created', '')
        updated = result.get('updated', '')
        event_link = result.get('htmlLink', '')
        
        message = f"""📋 **Детали события**

**{title}**
⏰ {start_time} - {end_time}"""
        
        if description:
            message += f"\n📝 {description}"
        
        if location:
            message += f"\n📍 {location}"
        
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                message += f"\n📅 Создано: {created_dt.strftime('%d.%m.%Y %H:%M')}"
            except:
                pass
        
        if event_link:
            message += f"\n\n🔗 [Открыть в Google Calendar]({event_link})"
        
        message += f"\n\n🆔 ID: `{event_id}`"
        
        return {
            "success": True,
            "message": message,
            "event_data": result
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения события: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения события:** {str(e)}"
        }
