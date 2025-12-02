"""
Узел для фильтрации писем
"""

import logging
from typing import Dict, List, Optional
from langchain_core.tools import tool

from giga_agent.agents.email_agent.utils.imap_client import IMAPClient
from giga_agent.agents.email_agent.utils.storage import EmailStorage

logger = logging.getLogger(__name__)


@tool
async def filter_emails(
    email_account: Optional[str] = None,
    folder: str = "inbox",
    auto_move_spam: bool = True,
    state: Optional[Dict] = None
) -> str:
    """
    Фильтрация писем (в настоящее время функция не выполняет фильтрацию)
    
    Args:
        email_account: Email адрес ящика
        folder: Папка для фильтрации (по умолчанию "inbox")
        auto_move_spam: Автоматически перемещать спам в папку Spam
        state: Состояние агента
    
    Returns:
        Результат фильтрации
    """
    try:
        secrets = state.get("secrets", []) if state else []
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        
        if not config:
            return "❌ Не найдена конфигурация почтового ящика."
        
        return "ℹ️ Фильтрация писем в настоящее время не настроена. Настройки фильтрации были удалены."
            
    except Exception as e:
        logger.error(f"Ошибка фильтрации писем: {e}")
        return f"❌ Ошибка фильтрации: {str(e)}"


@tool
async def check_email_filters(
    email_account: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Просмотр настроек фильтрации для ящика
    
    Args:
        email_account: Email адрес ящика
        state: Состояние агента
    
    Returns:
        Информация о настройках фильтрации
    """
    try:
        secrets = state.get("secrets", []) if state and isinstance(state, dict) else []
        if not secrets:
            logger.warning("check_email_filters: секреты не найдены в state")
            return "❌ Не найдена конфигурация почтового ящика. Убедитесь, что секреты настроены правильно."
        
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        
        if not config:
            return "❌ Не найдена конфигурация почтового ящика."
        
        result = f"📋 **Настройки фильтрации для {config['email']}**\n\n"
        result += "ℹ️ Фильтрация писем в настоящее время не настроена.\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка получения настроек фильтрации: {e}")
        return f"❌ Ошибка: {str(e)}"

