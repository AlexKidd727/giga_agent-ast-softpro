"""
Узлы для работы с календарями в Google Calendar
"""

import logging
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.google_api import calendar_client
from ..utils.oauth_manager import oauth_manager
from ..utils.storage import storage

logger = logging.getLogger(__name__)

@tool
async def list_calendars(user_id: str, state: Annotated[dict, InjectedState]):
    """
    Получение списка доступных календарей пользователя
    
    Args:
        user_id: Идентификатор пользователя
    """
    try:
        # Проверяем авторизацию
        if not oauth_manager.is_authenticated(user_id):
            return {
                "error": True,
                "message": "❌ **Не подключен Google Calendar**\n\nДля просмотра календарей сначала подключите календарь командой: \"подключить календарь\""
            }
        
        # Получаем список календарей
        result = await calendar_client.list_calendars(user_id)
        
        if 'error' in result:
            return {
                "error": True,
                "message": f"❌ **Ошибка получения календарей:**\n{result['error']}\n\n📝 {result.get('details', '')}"
            }
        
        calendars = result.get('items', [])
        if not calendars:
            return {
                "success": True,
                "message": "📅 Календари не найдены"
            }
        
        # Текущий активный календарь
        current_calendar_id = storage.get_user_calendar_id(user_id)
        
        # Форматируем список календарей
        message = "📅 **Доступные календари:**\n\n"
        
        for calendar in calendars:
            calendar_id = calendar.get('id', 'неизвестно')
            summary = calendar.get('summary', 'Без названия')
            description = calendar.get('description', '')
            access_role = calendar.get('accessRole', 'unknown')
            
            # Отмечаем текущий календарь
            marker = "✅ " if calendar_id == current_calendar_id else "📋 "
            
            message += f"{marker}**{summary}**\n"
            message += f"  🆔 `{calendar_id}`\n"
            message += f"  🔑 Доступ: {access_role}\n"
            
            if description:
                desc = description[:100]
                if len(description) > 100:
                    desc += "..."
                message += f"  📝 {desc}\n"
            
            message += "\n"
        
        message += f"💡 **Текущий календарь:** {current_calendar_id}\n"
        message += "🔧 Для смены календаря используйте: \"установить календарь [ID]\""
        
        return {
            "success": True,
            "message": message,
            "calendars_count": len(calendars),
            "current_calendar": current_calendar_id
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения календарей: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения календарей:** {str(e)}"
        }

@tool
async def set_calendar(user_id: str, calendar_id: str, state: Annotated[dict, InjectedState]):
    """
    Установка активного календаря для пользователя
    
    Args:
        user_id: Идентификатор пользователя
        calendar_id: ID календаря для установки (например, 'primary' или email)
    """
    try:
        # Проверяем авторизацию
        if not oauth_manager.is_authenticated(user_id):
            return {
                "error": True,
                "message": "❌ **Не подключен Google Calendar**\n\nДля смены календаря сначала подключите календарь командой: \"подключить календарь\""
            }
        
        # Проверяем, существует ли календарь
        calendars_result = await calendar_client.list_calendars(user_id)
        
        if 'error' in calendars_result:
            return {
                "error": True,
                "message": f"❌ **Ошибка проверки календаря:**\n{calendars_result['error']}"
            }
        
        calendars = calendars_result.get('items', [])
        calendar_exists = False
        calendar_name = calendar_id
        
        for calendar in calendars:
            if calendar.get('id') == calendar_id:
                calendar_exists = True
                calendar_name = calendar.get('summary', calendar_id)
                break
        
        if not calendar_exists:
            available_calendars = [cal.get('id', 'неизвестно') for cal in calendars]
            return {
                "error": True,
                "message": f"""❌ **Календарь не найден**

🔍 Календарь `{calendar_id}` не найден в вашем аккаунте.

📋 **Доступные календари:**
{chr(10).join([f"• {cal_id}" for cal_id in available_calendars])}

💡 Используйте команду \"показать календари\" для просмотра полного списка."""
            }
        
        # Устанавливаем календарь
        storage.set_user_calendar_id(user_id, calendar_id)
        
        return {
            "success": True,
            "message": f"""✅ **Календарь установлен**

📅 **Активный календарь:** {calendar_name}
🆔 **ID:** `{calendar_id}`

💡 Теперь все операции будут выполняться с этим календарем:
- Создание событий
- Просмотр расписания
- Редактирование встреч"""
        }
        
    except Exception as e:
        logger.error(f"Ошибка установки календаря: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка установки календаря:** {str(e)}"
        }

@tool
async def get_calendar_info(user_id: str, state: Annotated[dict, InjectedState]):
    """
    Получение информации о текущем активном календаре
    
    Args:
        user_id: Идентификатор пользователя
    """
    try:
        # Проверяем авторизацию
        if not oauth_manager.is_authenticated(user_id):
            return {
                "error": True,
                "message": "❌ **Не подключен Google Calendar**\n\nДля просмотра информации сначала подключите календарь командой: \"подключить календарь\""
            }
        
        current_calendar_id = storage.get_user_calendar_id(user_id)
        
        # Получаем список календарей для поиска информации о текущем
        calendars_result = await calendar_client.list_calendars(user_id)
        
        if 'error' in calendars_result:
            return {
                "error": True,
                "message": f"❌ **Ошибка получения информации:**\n{calendars_result['error']}"
            }
        
        calendars = calendars_result.get('items', [])
        current_calendar_info = None
        
        for calendar in calendars:
            if calendar.get('id') == current_calendar_id:
                current_calendar_info = calendar
                break
        
        if not current_calendar_info:
            return {
                "error": True,
                "message": f"❌ **Текущий календарь не найден**\n\nКалендарь `{current_calendar_id}` больше недоступен."
            }
        
        # Формируем информацию о календаре
        name = current_calendar_info.get('summary', 'Без названия')
        description = current_calendar_info.get('description', '')
        access_role = current_calendar_info.get('accessRole', 'unknown')
        time_zone = current_calendar_info.get('timeZone', 'неизвестно')
        
        message = f"""📅 **Информация о календаре**

**{name}**
🆔 ID: `{current_calendar_id}`
🔑 Доступ: {access_role}
🌍 Часовой пояс: {time_zone}"""
        
        if description:
            message += f"\n📝 Описание: {description}"
        
        # Получаем статистику событий (ближайшие 10)
        events_result = await calendar_client.list_events(user_id, max_results=5)
        if 'error' not in events_result:
            events_count = len(events_result.get('items', []))
            message += f"\n\n📊 **Статистика:**"
            message += f"\n• Ближайших событий: {events_count}"
        
        message += f"\n\n🔧 **Доступные действия:**"
        message += f"\n• \"создать событие\" - добавить встречу"
        message += f"\n• \"показать события\" - просмотр расписания"
        message += f"\n• \"показать календари\" - список всех календарей"
        
        return {
            "success": True,
            "message": message,
            "calendar_info": current_calendar_info
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения информации о календаре: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения информации:** {str(e)}"
        }
