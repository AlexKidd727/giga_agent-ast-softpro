"""
Простая авторизация Google Calendar через Service Account
По образцу из проекта sterligov/main
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo

try:
    from googleapiclient.discovery import build
    from google.oauth2 import service_account
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    build = None
    service_account = None
    logger = logging.getLogger(__name__)
    logger.warning("google-api-python-client не установлен. Calendar agent будет недоступен.")

logger = logging.getLogger(__name__)

class SimpleGoogleCalendarAuth:
    """Простая авторизация Google Calendar через Service Account"""
    
    def __init__(self, user_id: Optional[str] = None):
        """
        Инициализация авторизации Google Calendar
        
        Args:
            user_id: ID пользователя для получения credentials из БД
        """
        # Получаем credentials пользователя синхронно
        if user_id:
            try:
                from giga_agent.utils.user_tokens_sync import (
                    get_user_google_calendar_credentials_sync,
                    get_user_google_calendar_id_sync
                )
                self.service_account_file = get_user_google_calendar_credentials_sync(user_id) or os.getenv("GOOGLE_CALENDAR_CREDENTIALS", "service_account.json")
                self.calendar_id = get_user_google_calendar_id_sync(user_id) or os.getenv("CALENDAR_ID", "primary")
            except Exception as e:
                logger.warning(f"Не удалось получить credentials пользователя {user_id}, используем глобальные: {e}")
                self.service_account_file = os.getenv("GOOGLE_CALENDAR_CREDENTIALS", "service_account.json")
                self.calendar_id = os.getenv("CALENDAR_ID", "primary")
        else:
            self.service_account_file = os.getenv("GOOGLE_CALENDAR_CREDENTIALS", "service_account.json")
            self.calendar_id = os.getenv("CALENDAR_ID", "primary")
        
        self.scopes = ['https://www.googleapis.com/auth/calendar']
        self.service = None
        self.moscow_tz = ZoneInfo("Europe/Moscow")
        
        # Инициализируем сервис
        self._init_service()
    
    def _init_service(self):
        """Инициализация Google Calendar сервиса"""
        if not GOOGLE_API_AVAILABLE:
            logger.error("Google API библиотеки не установлены. Установите: pip install google-api-python-client google-auth")
            self.service = None
            return
            
        try:
            if not os.path.exists(self.service_account_file):
                logger.error(f"Файл service account не найден: {self.service_account_file}")
                return
            
            credentials = service_account.Credentials.from_service_account_file(
                self.service_account_file, 
                scopes=self.scopes
            )
            self.service = build('calendar', 'v3', credentials=credentials)
            logger.info("✅ Google Calendar сервис инициализирован")
            
        except Exception as e:
            logger.error(f"Ошибка инициализации Google Calendar сервиса: {e}")
            self.service = None
    
    def is_authenticated(self) -> bool:
        """Проверка авторизации"""
        return self.service is not None
    
    def get_available_time_slots(self, date_str: str) -> List[str]:
        """Получение доступных временных слотов на дату"""
        if not self.is_authenticated():
            logger.error("Google Calendar не авторизован")
            return []
        
        # Генерируем все возможные слоты с 8:00 до 22:00
        all_slots = [
            datetime.strptime(f"{date_str} {hour:02d}:00", "%Y-%m-%d %H:%M").replace(tzinfo=self.moscow_tz)
            for hour in range(8, 23)
        ]
        
        today_str = datetime.now(self.moscow_tz).strftime("%Y-%m-%d")
        
        # Если это сегодня, исключаем прошедшее время
        if date_str == today_str:
            now_time = datetime.now(self.moscow_tz)
            all_slots = [slot for slot in all_slots if slot > now_time]
        
        if not all_slots:
            return []
        
        start_dt = all_slots[0]
        end_dt = all_slots[-1] + timedelta(hours=1)
        
        try:
            # Получаем события из календаря
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_dt.isoformat(),
                timeMax=end_dt.isoformat(),
                singleEvents=True,
                orderBy="startTime"
            ).execute()
            
            events = events_result.get("items", [])
            
            free_slots = []
            
            for slot in all_slots:
                slot_end = slot + timedelta(hours=1)
                conflict = False
                
                for event in events:
                    event_start_str = event["start"].get("dateTime", event["start"].get("date"))
                    event_end_str = event["end"].get("dateTime", event["end"].get("date"))
                    
                    try:
                        event_start = datetime.fromisoformat(event_start_str).astimezone(self.moscow_tz)
                        event_end = datetime.fromisoformat(event_end_str).astimezone(self.moscow_tz)
                    except Exception:
                        continue
                    
                    if event_start < slot_end and event_end > slot:
                        conflict = True
                        break
                
                if not conflict:
                    free_slots.append(slot.strftime("%H:%M"))
            
            return free_slots
            
        except Exception as e:
            logger.error(f"Ошибка при получении событий календаря: {e}")
            return []
    
    def create_event(self, title: str, start_datetime: str, end_datetime: str, 
                    description: str = "", user_name: str = "", user_username: str = "") -> Dict[str, Any]:
        """Создание события в календаре"""
        if not self.is_authenticated():
            return {
                "error": True,
                "message": "Google Calendar не авторизован"
            }
        
        try:
            # Парсим дату и время начала
            session_date = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M").replace(tzinfo=self.moscow_tz)
            start_date_str = session_date.isoformat()
            
            # Парсим дату и время окончания
            if end_datetime:
                try:
                    end_date = datetime.strptime(end_datetime, "%d.%m.%Y %H:%M").replace(tzinfo=self.moscow_tz)
                    end_date_str = end_date.isoformat()
                except ValueError:
                    # Если не удалось распарсить end_datetime, используем start_datetime + 1 час
                    end_date_str = (session_date + timedelta(hours=1)).isoformat()
            else:
                # Если end_datetime не передан, используем start_datetime + 1 час
                end_date_str = (session_date + timedelta(hours=1)).isoformat()
            
            # Формируем название события
            if title and title.strip():
                # Если передан title, используем его
                summary = title.strip()
            elif user_username:
                summary = f"Сессия с @{user_username} ({user_name})"
            elif user_name:
                summary = f"Сессия с {user_name}"
            else:
                summary = "Событие"
            
            event = {
                'summary': summary,
                'description': description,
                'start': {'dateTime': start_date_str, 'timeZone': 'Europe/Moscow'},
                'end': {'dateTime': end_date_str, 'timeZone': 'Europe/Moscow'},
            }
            
            created_event = self.service.events().insert(
                calendarId=self.calendar_id, 
                body=event
            ).execute()
            
            return {
                "success": True,
                "message": f"Сессия забронирована на {session_date.strftime('%d.%m.%Y %H:%M')}",
                "event_id": created_event.get('id'),
                "html_link": created_event.get('htmlLink')
            }
            
        except Exception as e:
            logger.error(f"Ошибка создания события: {e}")
            return {
                "error": True,
                "message": f"Ошибка создания события: {str(e)}"
            }
    
    def list_events(self, max_results: int = 10, time_min: Optional[str] = None) -> Dict[str, Any]:
        """Получение списка событий"""
        if not self.is_authenticated():
            return {
                "error": True,
                "message": "Google Calendar не авторизован"
            }
        
        try:
            if not time_min:
                time_min = datetime.now(self.moscow_tz).isoformat()
            
            # Убеждаемся, что time_min имеет правильный формат
            if not time_min.endswith('Z') and not '+' in time_min:
                time_min = time_min + 'Z'
            
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=time_min,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime"
            ).execute()
            
            events = events_result.get("items", [])
            
            if not events:
                return {
                    "success": True,
                    "message": "📅 События не найдены",
                    "events": []
                }
            
            formatted_events = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                
                try:
                    if 'T' in start:
                        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(self.moscow_tz)
                        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00')).astimezone(self.moscow_tz)
                        time_str = f"{start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}"
                    else:
                        start_dt = datetime.fromisoformat(start).date()
                        time_str = f"{start_dt.strftime('%d.%m.%Y')} (весь день)"
                except:
                    time_str = f"{start} - {end}"
                
                formatted_events.append({
                    "title": event.get('summary', 'Без названия'),
                    "time": time_str,
                    "description": event.get('description', ''),
                    "id": event.get('id')
                })
            
            return {
                "success": True,
                "message": f"📅 Найдено {len(formatted_events)} событий",
                "events": formatted_events
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения событий: {e}")
            return {
                "error": True,
                "message": f"Ошибка получения событий: {str(e)}"
            }
    
    def delete_event(self, event_id: str) -> Dict[str, Any]:
        """Удаление события"""
        if not self.is_authenticated():
            return {
                "error": True,
                "message": "Google Calendar не авторизован"
            }
        
        try:
            self.service.events().delete(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            
            return {
                "success": True,
                "message": f"Событие {event_id} удалено"
            }
            
        except Exception as e:
            logger.error(f"Ошибка удаления события: {e}")
            return {
                "error": True,
                "message": f"Ошибка удаления события: {str(e)}"
            }
    
    def find_event_by_title(self, title: str, max_results: int = 10, days_ahead: int = 30) -> Dict[str, Any]:
        """Поиск события по названию"""
        if not self.is_authenticated():
            return {
                "error": True,
                "message": "Google Calendar не авторизован"
            }
        
        try:
            now = datetime.now(self.moscow_tz)
            time_min = now.isoformat()
            time_max = (now + timedelta(days=days_ahead)).isoformat()
            
            # Убеждаемся, что time_min имеет правильный формат
            if not time_min.endswith('Z') and not '+' in time_min:
                time_min = time_min + 'Z'
            if not time_max.endswith('Z') and not '+' in time_max:
                time_max = time_max + 'Z'
            
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results * 2,  # Берем больше, чтобы найти по названию
                singleEvents=True,
                orderBy="startTime"
            ).execute()
            
            events = events_result.get("items", [])
            
            # Ищем события, содержащие title в названии
            matching_events = []
            title_lower = title.lower()
            
            for event in events:
                event_title = event.get('summary', '').lower()
                if title_lower in event_title or event_title in title_lower:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    end = event['end'].get('dateTime', event['end'].get('date'))
                    
                    try:
                        if 'T' in start:
                            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(self.moscow_tz)
                            end_dt = datetime.fromisoformat(end.replace('Z', '+00:00')).astimezone(self.moscow_tz)
                            time_str = f"{start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}"
                        else:
                            start_dt = datetime.fromisoformat(start).date()
                            time_str = f"{start_dt.strftime('%d.%m.%Y')} (весь день)"
                    except:
                        time_str = f"{start} - {end}"
                    
                    matching_events.append({
                        "title": event.get('summary', 'Без названия'),
                        "time": time_str,
                        "description": event.get('description', ''),
                        "id": event.get('id'),
                        "start": start,
                        "end": end
                    })
                    
                    if len(matching_events) >= max_results:
                        break
            
            if not matching_events:
                return {
                    "success": True,
                    "message": f"📅 События с названием '{title}' не найдены",
                    "events": []
                }
            
            return {
                "success": True,
                "message": f"📅 Найдено {len(matching_events)} событий с названием '{title}'",
                "events": matching_events
            }
            
        except Exception as e:
            logger.error(f"Ошибка поиска события: {e}")
            return {
                "error": True,
                "message": f"Ошибка поиска события: {str(e)}"
            }
    
    def update_event(self, event_id: str, title: Optional[str] = None, 
                    start_datetime: Optional[str] = None, 
                    end_datetime: Optional[str] = None,
                    description: Optional[str] = None) -> Dict[str, Any]:
        """Обновление/перенос события"""
        if not self.is_authenticated():
            return {
                "error": True,
                "message": "Google Calendar не авторизован"
            }
        
        try:
            # Сначала получаем текущее событие
            event = self.service.events().get(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            
            if not event:
                return {
                    "error": True,
                    "message": f"Событие с ID {event_id} не найдено"
                }
            
            # Обновляем только переданные поля
            if title is not None:
                event['summary'] = title
            
            if description is not None:
                event['description'] = description
            
            if start_datetime is not None:
                # Парсим дату и время из формата "дд.мм.гггг чч:мм"
                try:
                    dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M")
                    dt = dt.replace(tzinfo=self.moscow_tz)
                    event['start'] = {
                        'dateTime': dt.isoformat(),
                        'timeZone': 'Europe/Moscow'
                    }
                except ValueError:
                    return {
                        "error": True,
                        "message": f"Неверный формат даты начала: {start_datetime}. Используйте формат 'дд.мм.гггг чч:мм'"
                    }
            
            if end_datetime is not None:
                # Парсим дату и время из формата "дд.мм.гггг чч:мм"
                try:
                    dt = datetime.strptime(end_datetime, "%d.%m.%Y %H:%M")
                    dt = dt.replace(tzinfo=self.moscow_tz)
                    event['end'] = {
                        'dateTime': dt.isoformat(),
                        'timeZone': 'Europe/Moscow'
                    }
                except ValueError:
                    return {
                        "error": True,
                        "message": f"Неверный формат даты окончания: {end_datetime}. Используйте формат 'дд.мм.гггг чч:мм'"
                    }
            
            # Обновляем событие
            updated_event = self.service.events().update(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=event
            ).execute()
            
            # Форматируем время для ответа
            start = updated_event['start'].get('dateTime', updated_event['start'].get('date'))
            end = updated_event['end'].get('dateTime', updated_event['end'].get('date'))
            
            try:
                if 'T' in start:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(self.moscow_tz)
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00')).astimezone(self.moscow_tz)
                    time_str = f"{start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}"
                else:
                    start_dt = datetime.fromisoformat(start).date()
                    time_str = f"{start_dt.strftime('%d.%m.%Y')} (весь день)"
            except:
                time_str = f"{start} - {end}"
            
            return {
                "success": True,
                "message": f"""✅ **Событие обновлено**

📋 **{updated_event.get('summary', 'Без названия')}**
⏰ {time_str}""",
                "event_id": event_id
            }
            
        except Exception as e:
            logger.error(f"Ошибка обновления события: {e}")
            return {
                "error": True,
                "message": f"Ошибка обновления события: {str(e)}"
            }
    
    def get_nearest_dates(self, n: int = 12) -> List[str]:
        """Получение ближайших дат"""
        now = datetime.now(self.moscow_tz)
        return [(now + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]

# Глобальный экземпляр простой авторизации
simple_calendar_auth = SimpleGoogleCalendarAuth()
