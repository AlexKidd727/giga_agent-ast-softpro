"""
Узлы для OAuth авторизации Google Calendar
"""

import logging
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.oauth_manager import oauth_manager
from ..utils.storage import storage

logger = logging.getLogger(__name__)

@tool
async def oauth_connect(user_id: str, state: Annotated[dict, InjectedState]):
    """
    Инициация подключения к Google Calendar через OAuth Device Flow
    
    Args:
        user_id: Идентификатор пользователя (можно использовать любой уникальный ID)
    """
    try:
        result = await oauth_manager.start_device_flow(user_id)
        
        if 'error' in result:
            return {
                "error": True,
                "message": f"❌ {result['error']}: {result.get('details', '')}"
            }
        
        user_code = result['user_code']
        verification_url = result['verification_url']
        expires_in = result.get('expires_in', 1800)
        
        message = f"""🔐 **Подключение к Google Calendar**

📋 **Инструкция:**
1. Откройте ссылку: {verification_url}
2. Введите код: **{user_code}**
3. Разрешите доступ к календарю
4. После подтверждения используйте команду "завершить подключение календаря"

⏰ Код действителен {expires_in // 60} минут.

💡 **Что это дает:**
- Создание событий в календаре
- Просмотр предстоящих встреч
- Управление расписанием через чат"""
        
        return {
            "message": message,
            "user_code": user_code,
            "verification_url": verification_url
        }
        
    except Exception as e:
        logger.error(f"Ошибка OAuth connect: {e}")
        return {
            "error": True,
            "message": f"❌ Ошибка подключения: {str(e)}"
        }

@tool
async def oauth_complete(user_id: str, state: Annotated[dict, InjectedState]):
    """
    Завершение подключения к Google Calendar после подтверждения на странице Google
    
    Args:
        user_id: Идентификатор пользователя
    """
    try:
        result = await oauth_manager.poll_device_token(user_id)
        
        if 'error' in result:
            return {
                "error": True,
                "message": f"❌ {result['error']}: {result.get('details', '')}"
            }
        
        if 'pending' in result:
            return {
                "pending": True,
                "message": result['message']
            }
        
        # Успешное завершение
        return {
            "success": True,
            "message": """✅ **Google Calendar подключен!**

🎉 Теперь вы можете:
- Создавать события: "создай встречу завтра в 15:00"
- Просматривать календарь: "покажи мои встречи на завтра"
- Управлять событиями: "перенеси встречу на час позже"

📅 По умолчанию используется основной календарь. 
Вы можете изменить это через настройки календаря."""
        }
        
    except Exception as e:
        logger.error(f"Ошибка OAuth complete: {e}")
        return {
            "error": True,
            "message": f"❌ Ошибка завершения подключения: {str(e)}"
        }

@tool
async def oauth_status(user_id: str, state: Annotated[dict, InjectedState]):
    """
    Проверка статуса авторизации в Google Calendar
    
    Args:
        user_id: Идентификатор пользователя
    """
    try:
        is_authenticated = oauth_manager.is_authenticated(user_id)
        
        if is_authenticated:
            profile = storage.get_user_profile(user_id)
            calendar_id = storage.get_user_calendar_id(user_id)
            
            message = f"""✅ **Google Calendar подключен**

📊 **Статус подключения:**
- Авторизация: ✅ Активна
- Календарь: {calendar_id}
- Последнее обновление: {profile.get('last_updated', 'неизвестно') if profile else 'неизвестно'}

🔧 **Доступные команды:**
- "покажи календарь"
- "создай событие"
- "отключить календарь" """
        else:
            message = """❌ **Google Calendar не подключен**

🔗 Для подключения используйте команду: "подключить календарь"

💡 После подключения вы сможете:
- Создавать события в календаре
- Просматривать расписание
- Управлять встречами"""
        
        return {
            "authenticated": is_authenticated,
            "message": message
        }
        
    except Exception as e:
        logger.error(f"Ошибка OAuth status: {e}")
        return {
            "error": True,
            "message": f"❌ Ошибка проверки статуса: {str(e)}"
        }

@tool
async def oauth_disconnect(user_id: str, state: Annotated[dict, InjectedState]):
    """
    Отключение от Google Calendar (удаление токенов)
    
    Args:
        user_id: Идентификатор пользователя
    """
    try:
        oauth_manager.revoke_access(user_id)
        
        return {
            "success": True,
            "message": """🔓 **Google Calendar отключен**

✅ Все токены доступа удалены
🗑️ Локальные данные очищены

💡 Для повторного подключения используйте команду: "подключить календарь" """
        }
        
    except Exception as e:
        logger.error(f"Ошибка OAuth disconnect: {e}")
        return {
            "error": True,
            "message": f"❌ Ошибка отключения: {str(e)}"
        }
