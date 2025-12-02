"""
Узлы для работы с событиями через простую авторизацию Google Calendar
"""

import logging
from datetime import datetime, timedelta
from typing import Annotated, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.simple_auth import SimpleGoogleCalendarAuth

logger = logging.getLogger(__name__)

@tool
async def simple_create_event(
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    user_name: str = "",
    user_username: str = "",
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None
):
    """
    Создание события в Google Calendar через простую авторизацию
    
    Args:
        title: Название события
        start_datetime: Дата и время начала в формате "дд.мм.гггг чч:мм" (например, "20.01.2025 15:00")
        end_datetime: Дата и время окончания в формате "дд.мм.гггг чч:мм" (например, "20.01.2025 16:00")
        description: Описание события (необязательно)
        user_name: Имя пользователя (необязательно)
        user_username: Username пользователя (необязательно)
        user_id: ID пользователя для получения credentials из БД
        state: Состояние графа (для извлечения user_id, если не передан явно)
    """
    try:
        # Извлекаем user_id из состояния, если не передан явно
        if not user_id and state:
            user_id = state.get("user_id")
        
        # Создаем экземпляр с user_id
        calendar_auth = SimpleGoogleCalendarAuth(user_id=user_id)
        
        if not calendar_auth.is_authenticated():
            return {
                "error": True,
                "message": "❌ **Google Calendar не настроен**\n\nНеобходимо настроить service account для работы с календарем"
            }
        
        result = calendar_auth.create_event(
            title=title,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            description=description,
            user_name=user_name,
            user_username=user_username
        )
        
        if result.get("error"):
            return {
                "error": True,
                "message": f"❌ **Ошибка создания события:**\n{result['message']}"
            }
        
        return {
            "success": True,
            "message": f"""✅ **Событие создано успешно!**

📋 **{title}**
⏰ {start_datetime} - {end_datetime}"""
        }
        
    except Exception as e:
        logger.error(f"Ошибка создания события: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка создания события:** {str(e)}"
        }

@tool
async def simple_list_events(
    max_results: int = 10,
    days_ahead: int = 7,
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None
):
    """
    Получение списка событий из Google Calendar
    
    Args:
        max_results: Максимальное количество событий (по умолчанию 10)
        days_ahead: Количество дней вперед для поиска событий (по умолчанию 7)
        user_id: ID пользователя для получения credentials из БД
        state: Состояние графа (для извлечения user_id, если не передан явно)
    """
    try:
        # Извлекаем user_id из состояния, если не передан явно
        if not user_id and state:
            user_id = state.get("user_id")
        
        # Создаем экземпляр с user_id
        calendar_auth = SimpleGoogleCalendarAuth(user_id=user_id)
        
        if not calendar_auth.is_authenticated():
            return {
                "error": True,
                "message": "❌ **Google Calendar не настроен**\n\nНеобходимо настроить service account для работы с календарем"
            }
        
        # Устанавливаем временные рамки с правильной временной зоной
        now = datetime.now()
        time_min = now.isoformat() + 'Z'  # Добавляем Z для UTC
        time_max = (now + timedelta(days=days_ahead)).isoformat() + 'Z'
        
        result = calendar_auth.list_events(
            max_results=max_results,
            time_min=time_min
        )
        
        if result.get("error"):
            return {
                "error": True,
                "message": f"❌ **Ошибка получения событий:**\n{result['message']}"
            }
        
        events = result.get("events", [])
        if not events:
            return {
                "success": True,
                "message": "📅 **События не найдены**\n\nНа ближайшие дни запланированных событий нет."
            }
        
        message = f"📅 **События в календаре ({len(events)}):**\n\n"
        
        for i, event in enumerate(events, 1):
            message += f"{i}. **{event['title']}**\n"
            message += f"   ⏰ {event['time']}\n"
            if event.get('description'):
                desc = event['description'][:100]
                if len(event['description']) > 100:
                    desc += "..."
                message += f"   📝 {desc}\n"
            message += "\n"
        
        return {
            "success": True,
            "message": message,
            "events_count": len(events)
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения событий: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения событий:** {str(e)}"
        }

@tool
async def simple_get_available_slots(
    date: str,
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None
):
    """
    Получение доступных временных слотов на указанную дату
    
    Args:
        date: Дата в формате "гггг-мм-дд" (например, "2025-01-20")
        user_id: ID пользователя для получения credentials из БД
        state: Состояние графа (для извлечения user_id, если не передан явно)
    """
    try:
        # Извлекаем user_id из состояния, если не передан явно
        if not user_id and state:
            user_id = state.get("user_id")
        
        # Создаем экземпляр с user_id
        calendar_auth = SimpleGoogleCalendarAuth(user_id=user_id)
        
        if not calendar_auth.is_authenticated():
            return {
                "error": True,
                "message": "❌ **Google Calendar не настроен**\n\nНеобходимо настроить service account для работы с календарем"
            }
        
        available_slots = calendar_auth.get_available_time_slots(date)
        
        if not available_slots:
            return {
                "success": True,
                "message": f"📅 **На {date} нет доступных слотов**\n\nВсе время занято или дата в прошлом."
            }
        
        # Форматируем дату для отображения
        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%d.%m.%Y")
        except:
            formatted_date = date
        
        message = f"📅 **Доступные слоты на {formatted_date}:**\n\n"
        
        # Группируем слоты по строкам
        for i in range(0, len(available_slots), 4):
            row_slots = available_slots[i:i+4]
            message += " ".join([f"`{slot}`" for slot in row_slots]) + "\n"
        
        message += f"\n✅ Всего доступно: {len(available_slots)} слотов"
        
        return {
            "success": True,
            "message": message,
            "available_slots": available_slots,
            "slots_count": len(available_slots)
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения слотов: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения слотов:** {str(e)}"
        }

@tool
async def simple_delete_event(
    event_id: str,
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None
):
    """
    Удаление события из Google Calendar
    
    Args:
        event_id: ID события для удаления
        user_id: ID пользователя для получения credentials из БД
        state: Состояние графа (для извлечения user_id, если не передан явно)
    """
    try:
        # Извлекаем user_id из состояния, если не передан явно
        if not user_id and state:
            user_id = state.get("user_id")
        
        # Создаем экземпляр с user_id
        calendar_auth = SimpleGoogleCalendarAuth(user_id=user_id)
        
        if not calendar_auth.is_authenticated():
            return {
                "error": True,
                "message": "❌ **Google Calendar не настроен**\n\nНеобходимо настроить service account для работы с календарем"
            }
        
        result = calendar_auth.delete_event(event_id)
        
        if result.get("error"):
            return {
                "error": True,
                "message": f"❌ **Ошибка удаления события:**\n{result['message']}"
            }
        
        return {
            "success": True,
            "message": f"""✅ **Событие удалено**

🗑️ Событие с ID `{event_id}` удалено из календаря"""
        }
        
    except Exception as e:
        logger.error(f"Ошибка удаления события: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка удаления события:** {str(e)}"
        }

@tool
async def simple_find_event_by_title(
    title: str,
    max_results: int = 10,
    days_ahead: int = 30,
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None
):
    """
    Поиск события по названию в Google Calendar
    
    Args:
        title: Название события для поиска
        max_results: Максимальное количество результатов (по умолчанию 10)
        days_ahead: Количество дней вперед для поиска (по умолчанию 30)
        user_id: ID пользователя для получения credentials из БД
        state: Состояние графа (для извлечения user_id, если не передан явно)
    """
    try:
        # Извлекаем user_id из состояния, если не передан явно
        if not user_id and state:
            user_id = state.get("user_id")
        
        # Создаем экземпляр с user_id
        calendar_auth = SimpleGoogleCalendarAuth(user_id=user_id)
        
        if not calendar_auth.is_authenticated():
            return {
                "error": True,
                "message": "❌ **Google Calendar не настроен**\n\nНеобходимо настроить service account для работы с календарем"
            }
        
        result = calendar_auth.find_event_by_title(title, max_results, days_ahead)
        
        if result.get("error"):
            return {
                "error": True,
                "message": f"❌ **Ошибка поиска события:**\n{result['message']}"
            }
        
        events = result.get("events", [])
        if not events:
            return result
        
        message = f"📅 **Найдено {len(events)} событий с названием '{title}':**\n\n"
        
        for i, event in enumerate(events, 1):
            message += f"{i}. **{event['title']}**\n"
            message += f"   ⏰ {event['time']}\n"
            message += f"   🆔 ID: `{event['id']}`\n"
            if event.get('description'):
                desc = event['description'][:100]
                if len(event['description']) > 100:
                    desc += "..."
                message += f"   📝 {desc}\n"
            message += "\n"
        
        return {
            "success": True,
            "message": message,
            "events": events,
            "events_count": len(events)
        }
        
    except Exception as e:
        logger.error(f"Ошибка поиска события: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка поиска события:** {str(e)}"
        }

@tool
async def simple_update_event(
    event_id: str,
    title: Optional[str] = None,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    description: Optional[str] = None,
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None
):
    """
    Обновление/перенос события в Google Calendar
    
    Args:
        event_id: ID события для обновления
        title: Новое название события (необязательно)
        start_datetime: Новая дата и время начала в формате "дд.мм.гггг чч:мм" (необязательно)
        end_datetime: Новая дата и время окончания в формате "дд.мм.гггг чч:мм" (необязательно)
        description: Новое описание события (необязательно)
        user_id: ID пользователя для получения credentials из БД
        state: Состояние графа (для извлечения user_id, если не передан явно)
    """
    try:
        # Извлекаем user_id из состояния, если не передан явно
        if not user_id and state:
            user_id = state.get("user_id")
        
        # Создаем экземпляр с user_id
        calendar_auth = SimpleGoogleCalendarAuth(user_id=user_id)
        
        if not calendar_auth.is_authenticated():
            return {
                "error": True,
                "message": "❌ **Google Calendar не настроен**\n\nНеобходимо настроить service account для работы с календарем"
            }
        
        result = calendar_auth.update_event(
            event_id=event_id,
            title=title,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            description=description
        )
        
        if result.get("error"):
            return {
                "error": True,
                "message": f"❌ **Ошибка обновления события:**\n{result['message']}"
            }
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка обновления события: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка обновления события:** {str(e)}"
        }

@tool
async def simple_calendar_status(
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None
):
    """
    Проверка статуса подключения к Google Calendar
    
    Args:
        user_id: ID пользователя для получения credentials из БД
        state: Состояние графа (для извлечения user_id, если не передан явно)
    """
    try:
        # Извлекаем user_id из состояния, если не передан явно
        if not user_id and state:
            user_id = state.get("user_id")
        
        # Создаем экземпляр с user_id
        calendar_auth = SimpleGoogleCalendarAuth(user_id=user_id)
        is_authenticated = calendar_auth.is_authenticated()
        
        if is_authenticated:
            message = """✅ **Google Calendar подключен**

🔧 **Статус подключения:**
- Авторизация: ✅ Активна (Service Account)
- Календарь: Настроен
- Доступ: Полный

📋 **Доступные команды:**
- "создай событие" - создать новое событие
- "покажи события" - показать список событий  
- "покажи свободные слоты" - показать доступное время
- "удали событие" - удалить событие по ID
- "перенеси событие" - перенести событие на другое время
- "найди событие" - найти событие по названию"""
        else:
            message = """❌ **Google Calendar не настроен**

🔧 **Для настройки необходимо:**
1. Создать Service Account в Google Cloud Console
2. Скачать JSON файл с ключами
3. Установить переменные окружения:
   - GOOGLE_CALENDAR_CREDENTIALS=путь_к_файлу.json
   - CALENDAR_ID=id_календаря

💡 После настройки вы сможете:
- Создавать события в календаре
- Просматривать расписание
- Управлять встречами"""
        
        return {
            "authenticated": is_authenticated,
            "message": message
        }
        
    except Exception as e:
        logger.error(f"Ошибка проверки статуса: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка проверки статуса:** {str(e)}"
        }
