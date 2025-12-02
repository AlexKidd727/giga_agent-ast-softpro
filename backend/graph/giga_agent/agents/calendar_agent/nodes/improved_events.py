"""
Улучшенные узлы для работы с событиями, включая прошедшие события
"""

import logging
from datetime import datetime, timedelta
from typing import Annotated, Optional, Dict, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.simple_auth import simple_calendar_auth

logger = logging.getLogger(__name__)


@tool
async def improved_list_events(
    max_results: int = 50,
    days_back: int = 30,
    include_past: bool = True,
    state: Annotated[dict, InjectedState] = None
):
    """
    Улучшенное получение списка событий с возможностью поиска прошедших событий
    
    Args:
        max_results: Максимальное количество событий
        days_back: Количество дней назад для поиска (по умолчанию 30)
        include_past: Включать ли прошедшие события (по умолчанию True)
    """
    try:
        if not simple_calendar_auth.is_authenticated():
            return {
                "error": True,
                "message": "❌ **Google Calendar не настроен**\n\nНеобходимо настроить service account для работы с календарем"
            }
        
        # Определяем time_min в зависимости от параметра include_past
        if include_past:
            # Ищем события с days_back дней назад
            now = datetime.now()
            time_min = (now - timedelta(days=days_back)).isoformat() + 'Z'
        else:
            # Ищем только будущие события (как раньше)
            time_min = datetime.now().isoformat() + 'Z'
        
        # Получаем события через Google API
        events_result = simple_calendar_auth.service.events().list(
            calendarId=simple_calendar_auth.calendar_id,
            timeMin=time_min,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        
        events = events_result.get("items", [])
        
        if not events:
            period_desc = f"за последние {days_back} дней" if include_past else "в будущем"
            return {
                "success": True,
                "message": f"📅 События не найдены {period_desc}",
                "events": []
            }
        
        # Форматируем события
        formatted_events = []
        now = datetime.now()
        
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            
            try:
                if 'T' in start:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(simple_calendar_auth.moscow_tz)
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00')).astimezone(simple_calendar_auth.moscow_tz)
                    time_str = f"{start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}"
                    is_past = start_dt < now
                else:
                    start_dt = datetime.fromisoformat(start).date()
                    time_str = f"{start_dt.strftime('%d.%m.%Y')} (весь день)"
                    is_past = start_dt < now.date()
            except:
                time_str = f"{start} - {end}"
                is_past = False
            
            formatted_events.append({
                "id": event.get("id"),
                "title": event.get("summary", "Без названия"),
                "description": event.get("description", ""),
                "location": event.get("location", ""),
                "time": time_str,
                "start_date": start,
                "end_date": end,
                "is_past": is_past
            })
        
        # Сортируем события: сначала будущие, потом прошедшие
        formatted_events.sort(key=lambda x: (x["is_past"], x["start_date"]))
        
        # Подсчитываем статистику
        past_count = sum(1 for event in formatted_events if event["is_past"])
        future_count = len(formatted_events) - past_count
        
        period_desc = f"за последние {days_back} дней" if include_past else "в будущем"
        message = f"📅 Найдено {len(formatted_events)} событий {period_desc}"
        if include_past and past_count > 0:
            message += f" (прошедших: {past_count}, будущих: {future_count})"
        
        return {
            "success": True,
            "message": message,
            "events": formatted_events,
            "past_count": past_count,
            "future_count": future_count
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения событий: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения событий:** {str(e)}"
        }


@tool
async def search_events_by_keywords(
    keywords: str,
    max_results: int = 50,
    days_back: int = 30,
    include_past: bool = True,
    state: Annotated[dict, InjectedState] = None
):
    """
    Поиск событий по ключевым словам с возможностью поиска в прошедших событиях
    
    Args:
        keywords: Ключевые слова для поиска (через запятую)
        max_results: Максимальное количество событий
        days_back: Количество дней назад для поиска
        include_past: Включать ли прошедшие события
    """
    try:
        # Сначала получаем все события
        events_result = await improved_list_events.ainvoke({
            "max_results": max_results,
            "days_back": days_back,
            "include_past": include_past
        })
        
        if events_result.get("error"):
            return events_result
        
        all_events = events_result.get("events", [])
        
        if not all_events:
            return {
                "success": True,
                "message": f"📅 События не найдены для поиска по ключевым словам: {keywords}",
                "events": []
            }
        
        # Разбиваем ключевые слова
        keyword_list = [kw.strip().lower() for kw in keywords.split(",")]
        
        # Ищем события по ключевым словам
        matching_events = []
        for event in all_events:
            title = event.get("title", "").lower()
            description = event.get("description", "").lower()
            
            # Проверяем, содержит ли событие хотя бы одно ключевое слово
            if any(keyword in title or keyword in description for keyword in keyword_list):
                matching_events.append(event)
        
        if not matching_events:
            return {
                "success": True,
                "message": f"📅 События с ключевыми словами '{keywords}' не найдены",
                "events": []
            }
        
        # Подсчитываем статистику
        past_count = sum(1 for event in matching_events if event.get("is_past", False))
        future_count = len(matching_events) - past_count
        
        message = f"🔍 Найдено {len(matching_events)} событий с ключевыми словами '{keywords}'"
        if include_past and past_count > 0:
            message += f" (прошедших: {past_count}, будущих: {future_count})"
        
        return {
            "success": True,
            "message": message,
            "events": matching_events,
            "past_count": past_count,
            "future_count": future_count,
            "keywords": keywords
        }
        
    except Exception as e:
        logger.error(f"Ошибка поиска событий по ключевым словам: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка поиска событий:** {str(e)}"
        }


@tool
async def delete_events_by_keywords(
    keywords: str,
    days_back: int = 30,
    include_past: bool = True,
    confirm: bool = False,
    state: Annotated[dict, InjectedState] = None
):
    """
    Удаление событий по ключевым словам с возможностью поиска в прошедших событиях
    
    Args:
        keywords: Ключевые слова для поиска (через запятую)
        days_back: Количество дней назад для поиска
        include_past: Включать ли прошедшие события
        confirm: Подтверждение удаления (по умолчанию False для безопасности)
    """
    try:
        if not confirm:
            return {
                "error": True,
                "message": f"⚠️ **Подтверждение требуется**\n\nДля удаления событий с ключевыми словами '{keywords}' установите параметр confirm=True"
            }
        
        # Сначала ищем события
        search_result = await search_events_by_keywords.ainvoke({
            "keywords": keywords,
            "max_results": 100,
            "days_back": days_back,
            "include_past": include_past
        })
        
        if search_result.get("error"):
            return search_result
        
        events_to_delete = search_result.get("events", [])
        
        if not events_to_delete:
            return {
                "success": True,
                "message": f"📅 События с ключевыми словами '{keywords}' не найдены для удаления"
            }
        
        # Удаляем найденные события
        deleted_count = 0
        failed_count = 0
        deleted_events = []
        
        for event in events_to_delete:
            event_id = event.get("id")
            event_title = event.get("title")
            
            try:
                # Используем существующую функцию удаления
                from .simple_events import simple_delete_event
                delete_result = await simple_delete_event.ainvoke({
                    "event_id": event_id
                })
                
                if delete_result.get("success"):
                    deleted_count += 1
                    deleted_events.append({
                        "title": event_title,
                        "id": event_id,
                        "time": event.get("time", "")
                    })
                else:
                    failed_count += 1
                    logger.error(f"Ошибка удаления события {event_title}: {delete_result.get('message')}")
                    
            except Exception as e:
                failed_count += 1
                logger.error(f"Исключение при удалении события {event_title}: {e}")
        
        # Формируем результат
        if deleted_count > 0:
            message = f"✅ **Удалено {deleted_count} событий** с ключевыми словами '{keywords}'\n\n"
            for event in deleted_events:
                message += f"🗑️ **{event['title']}** ({event['time']})\n"
            
            if failed_count > 0:
                message += f"\n⚠️ Не удалось удалить {failed_count} событий"
            
            return {
                "success": True,
                "message": message,
                "deleted_count": deleted_count,
                "failed_count": failed_count,
                "deleted_events": deleted_events
            }
        else:
            return {
                "error": True,
                "message": f"❌ **Не удалось удалить события** с ключевыми словами '{keywords}'"
            }
        
    except Exception as e:
        logger.error(f"Ошибка удаления событий по ключевым словам: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка удаления событий:** {str(e)}"
        }
