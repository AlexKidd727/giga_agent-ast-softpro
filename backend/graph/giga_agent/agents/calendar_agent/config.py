"""
Конфигурация Google Calendar Agent
"""

import os

def get_calendar_agent_llm():
    """Получить LLM для Calendar агента (отложенный импорт)"""
    from giga_agent.utils.llm import load_llm
    return load_llm().with_config(tags=["nostream"])

# Google OAuth настройки
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8502/auth/google/callback")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events"
]

# Google Calendar API endpoints
GOOGLE_OAUTH_DEVICE_ENDPOINT = 'https://oauth2.googleapis.com/device/code'
GOOGLE_OAUTH_TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
GOOGLE_CALENDAR_EVENTS_ENDPOINT = 'https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events'
GOOGLE_CALENDAR_LIST_ENDPOINT = 'https://www.googleapis.com/calendar/v3/users/me/calendarList'

# Временная зона по умолчанию
DEFAULT_TIMEZONE = "Europe/Moscow"
