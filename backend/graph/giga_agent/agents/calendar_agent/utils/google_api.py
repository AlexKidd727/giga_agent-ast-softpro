"""
Клиент для работы с Google Calendar API
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import httpx

from ..config import (
    GOOGLE_CALENDAR_EVENTS_ENDPOINT,
    GOOGLE_CALENDAR_LIST_ENDPOINT,
    DEFAULT_TIMEZONE
)
from .oauth_manager import oauth_manager
from .storage import storage

logger = logging.getLogger(__name__)

class GoogleCalendarClient:
    """Клиент для работы с Google Calendar API"""
    
    def __init__(self):
        self.oauth = oauth_manager
    
    async def _make_api_request(self, user_id: str, method: str, url: str, 
                              params: Optional[Dict] = None, 
                              data: Optional[Dict] = None) -> Dict[str, Any]:
        """Выполнение запроса к Google Calendar API"""
        access_token = await self.oauth.get_valid_access_token(user_id)
        
        if not access_token:
            return {
                "error": "Пользователь не авторизован",
                "details": "Необходимо пройти авторизацию через Google"
            }
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method.upper() == 'GET':
                    response = await client.get(url, headers=headers, params=params)
                elif method.upper() == 'POST':
                    response = await client.post(url, headers=headers, json=data)
                elif method.upper() == 'PUT':
                    response = await client.put(url, headers=headers, json=data)
                elif method.upper() == 'PATCH':
                    response = await client.patch(url, headers=headers, json=data)
                elif method.upper() == 'DELETE':
                    response = await client.delete(url, headers=headers)
                else:
                    return {"error": f"Неподдерживаемый HTTP метод: {method}"}
                
                if response.status_code in [200, 201]:
                    return response.json()
                elif response.status_code == 204:
                    return {"success": True}
                else:
                    error_text = response.text
                    logger.error(f"API Error {response.status_code}: {error_text}")
                    
                    try:
                        error_data = response.json()
                        return {
                            "error": f"Google API Error: {response.status_code}",
                            "details": error_data.get('error', {}).get('message', error_text)
                        }
                    except:
                        return {
                            "error": f"Google API Error: {response.status_code}",
                            "details": error_text
                        }
                        
        except Exception as e:
            logger.error(f"Ошибка API запроса: {e}")
            return {
                "error": "Ошибка соединения с Google Calendar",
                "details": str(e)
            }
    
    async def list_calendars(self, user_id: str) -> Dict[str, Any]:
        """Получение списка календарей пользователя"""
        return await self._make_api_request(
            user_id, 'GET', GOOGLE_CALENDAR_LIST_ENDPOINT
        )
    
    async def list_events(self, user_id: str, calendar_id: Optional[str] = None,
                         max_results: int = 10, time_min: Optional[str] = None,
                         time_max: Optional[str] = None) -> Dict[str, Any]:
        """Получение списка событий из календаря"""
        if not calendar_id:
            calendar_id = storage.get_user_calendar_id(user_id)
        
        params = {
            'maxResults': max_results,
            'singleEvents': True,
            'orderBy': 'startTime'
        }
        
        # Устанавливаем временные рамки
        if not time_min:
            time_min = datetime.now().isoformat() + 'Z'
        if time_min:
            params['timeMin'] = time_min
        if time_max:
            params['timeMax'] = time_max
        
        url = GOOGLE_CALENDAR_EVENTS_ENDPOINT.format(calendarId=calendar_id)
        return await self._make_api_request(user_id, 'GET', url, params=params)
    
    async def create_event(self, user_id: str, title: str, description: str = "",
                          start_datetime: str = "", end_datetime: str = "",
                          all_day: bool = False, calendar_id: Optional[str] = None) -> Dict[str, Any]:
        """Создание события в календаре"""
        if not calendar_id:
            calendar_id = storage.get_user_calendar_id(user_id)
        
        # Формируем данные события
        event_data = {
            'summary': title,
            'description': description
        }
        
        if all_day:
            # Событие на весь день
            try:
                start_date = datetime.fromisoformat(start_datetime.replace('Z', '+00:00')).date()
                end_date = datetime.fromisoformat(end_datetime.replace('Z', '+00:00')).date()
                
                event_data['start'] = {'date': start_date.isoformat()}
                event_data['end'] = {'date': end_date.isoformat()}
            except ValueError as e:
                return {
                    "error": "Неверный формат даты",
                    "details": f"Ошибка парсинга даты: {e}"
                }
        else:
            # Событие с конкретным временем
            event_data['start'] = {
                'dateTime': start_datetime,
                'timeZone': DEFAULT_TIMEZONE
            }
            event_data['end'] = {
                'dateTime': end_datetime,
                'timeZone': DEFAULT_TIMEZONE
            }
        
        url = GOOGLE_CALENDAR_EVENTS_ENDPOINT.format(calendarId=calendar_id)
        return await self._make_api_request(user_id, 'POST', url, data=event_data)
    
    async def update_event(self, user_id: str, event_id: str, title: Optional[str] = None,
                          description: Optional[str] = None, start_datetime: Optional[str] = None,
                          end_datetime: Optional[str] = None, calendar_id: Optional[str] = None) -> Dict[str, Any]:
        """Обновление события в календаре"""
        if not calendar_id:
            calendar_id = storage.get_user_calendar_id(user_id)
        
        # Сначала получаем текущее событие
        url = f"{GOOGLE_CALENDAR_EVENTS_ENDPOINT.format(calendarId=calendar_id)}/{event_id}"
        current_event = await self._make_api_request(user_id, 'GET', url)
        
        if 'error' in current_event:
            return current_event
        
        # Обновляем только переданные поля
        update_data = {}
        if title is not None:
            update_data['summary'] = title
        if description is not None:
            update_data['description'] = description
        if start_datetime is not None:
            update_data['start'] = {
                'dateTime': start_datetime,
                'timeZone': DEFAULT_TIMEZONE
            }
        if end_datetime is not None:
            update_data['end'] = {
                'dateTime': end_datetime,
                'timeZone': DEFAULT_TIMEZONE
            }
        
        return await self._make_api_request(user_id, 'PATCH', url, data=update_data)
    
    async def delete_event(self, user_id: str, event_id: str, 
                          calendar_id: Optional[str] = None) -> Dict[str, Any]:
        """Удаление события из календаря"""
        if not calendar_id:
            calendar_id = storage.get_user_calendar_id(user_id)
        
        url = f"{GOOGLE_CALENDAR_EVENTS_ENDPOINT.format(calendarId=calendar_id)}/{event_id}"
        return await self._make_api_request(user_id, 'DELETE', url)
    
    async def get_event(self, user_id: str, event_id: str,
                       calendar_id: Optional[str] = None) -> Dict[str, Any]:
        """Получение конкретного события"""
        if not calendar_id:
            calendar_id = storage.get_user_calendar_id(user_id)
        
        url = f"{GOOGLE_CALENDAR_EVENTS_ENDPOINT.format(calendarId=calendar_id)}/{event_id}"
        return await self._make_api_request(user_id, 'GET', url)
    
    def format_event_time(self, time_data: Dict) -> str:
        """Форматирование времени события для отображения"""
        if 'dateTime' in time_data:
            # Событие с конкретным временем
            try:
                dt = datetime.fromisoformat(time_data['dateTime'].replace('Z', '+00:00'))
                return dt.strftime('%d.%m.%Y %H:%M')
            except ValueError:
                return time_data['dateTime']
        elif 'date' in time_data:
            # Событие на весь день
            try:
                date_obj = datetime.fromisoformat(time_data['date']).date()
                return date_obj.strftime('%d.%m.%Y')
            except ValueError:
                return time_data['date']
        else:
            return 'неизвестно'
    
    def format_events_list(self, events_data: Dict) -> str:
        """Форматирование списка событий для отображения"""
        if 'error' in events_data:
            return f"❌ {events_data['error']}: {events_data.get('details', '')}"
        
        events = events_data.get('items', [])
        if not events:
            return "📅 События не найдены"
        
        result = "📅 **События в календаре:**\n\n"
        
        for event in events:
            summary = event.get('summary', 'Без названия')
            start = event.get('start', {})
            end = event.get('end', {})
            
            start_time = self.format_event_time(start)
            end_time = self.format_event_time(end)
            
            result += f"• **{summary}**\n"
            result += f"  ⏰ {start_time} - {end_time}\n"
            
            if event.get('description'):
                desc = event['description'][:100]
                if len(event['description']) > 100:
                    desc += "..."
                result += f"  📝 {desc}\n"
            
            if event.get('location'):
                result += f"  📍 {event['location']}\n"
            
            result += "\n"
        
        return result

# Глобальный экземпляр клиента
calendar_client = GoogleCalendarClient()
