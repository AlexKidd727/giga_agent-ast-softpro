"""
Узел для управления почтовыми ящиками
"""

import logging
from typing import Dict, List, Optional
from langchain_core.tools import tool

from giga_agent.agents.email_agent.utils.imap_client import IMAPClient
from giga_agent.agents.email_agent.utils.storage import EmailStorage

logger = logging.getLogger(__name__)


@tool
async def list_email_accounts(state: Optional[Dict] = None) -> str:
    """
    Получение списка доступных почтовых ящиков
    
    Args:
        state: Состояние агента
    
    Returns:
        Список доступных ящиков
    """
    try:
        logger.info(f"[EMAIL_MANAGE] list_email_accounts вызван")
        secrets = state.get("secrets", []) if state and isinstance(state, dict) else []
        secrets_count = len(secrets) if secrets else 0
        logger.info(f"[EMAIL_MANAGE] list_email_accounts: получено секретов: {secrets_count}")
        if not secrets:
            logger.warning(f"[EMAIL_MANAGE] list_email_accounts: ВНИМАНИЕ! Секреты не найдены в state")
            return "📭 Нет настроенных почтовых ящиков. Настройте секреты для доступа к почте."
        
        logger.info(f"[EMAIL_MANAGE] list_email_accounts: вызываем EmailStorage.get_all_email_accounts")
        accounts = EmailStorage.get_all_email_accounts(secrets)
        logger.info(f"[EMAIL_MANAGE] list_email_accounts: найдено ящиков: {len(accounts)}")
        
        if not accounts:
            return "📭 Нет настроенных почтовых ящиков. Настройте секреты для доступа к почте."
        
        result = f"📧 **Доступные почтовые ящики ({len(accounts)}):**\n\n"
        for i, account in enumerate(accounts, 1):
            result += f"{i}. {account}\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка получения списка ящиков: {e}")
        return f"❌ Ошибка: {str(e)}"


@tool
async def get_email_folders(
    email_account: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Получение списка папок в почтовом ящике
    
    Args:
        email_account: Email адрес ящика
        state: Состояние агента
    
    Returns:
        Список папок
    """
    try:
        logger.info(f"[EMAIL_MANAGE] get_email_folders вызван: email_account={email_account}")
        secrets = state.get("secrets", []) if state and isinstance(state, dict) else []
        secrets_count = len(secrets) if secrets else 0
        logger.info(f"[EMAIL_MANAGE] get_email_folders: получено секретов: {secrets_count}")
        if not secrets:
            logger.warning(f"[EMAIL_MANAGE] get_email_folders: ВНИМАНИЕ! Секреты не найдены в state")
            return "❌ Не найдена конфигурация почтового ящика. Убедитесь, что секреты настроены правильно."
        
        logger.info(f"[EMAIL_MANAGE] get_email_folders: вызываем EmailStorage.get_email_config_from_secrets с email_account={email_account}")
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        
        if not config:
            logger.warning(f"[EMAIL_MANAGE] get_email_folders: ВНИМАНИЕ! Конфигурация не найдена")
            return "❌ Не найдена конфигурация почтового ящика."
        
        logger.info(f"[EMAIL_MANAGE] get_email_folders: конфигурация найдена: email={config.get('email')}, imap_host={config.get('imap_host')}")
        logger.info(f"[EMAIL_MANAGE] get_email_folders: подключаемся к IMAP: host={config['imap_host']}, email={config['email']}")
        async with IMAPClient(
            host=config["imap_host"],
            email=config["email"],
            password=config["password"]
        ) as client:
            logger.info(f"[EMAIL_MANAGE] get_email_folders: успешно подключились к IMAP")
            folders = await client.get_folders()
            
            if not folders:
                return f"📁 Не удалось получить список папок для {config['email']}"
            
            result = f"📁 **Папки в ящике {config['email']} ({len(folders)}):**\n\n"
            for folder in folders:
                result += f"- {folder}\n"
            
            return result
            
    except Exception as e:
        logger.error(f"Ошибка получения списка папок: {e}")
        return f"❌ Ошибка: {str(e)}"


@tool
async def test_email_connection(
    email_account: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Проверка подключения к почтовому ящику
    
    Args:
        email_account: Email адрес ящика
        state: Состояние агента
    
    Returns:
        Результат проверки подключения
    """
    try:
        logger.info(f"[EMAIL_MANAGE] test_email_connection вызван: email_account={email_account}")
        secrets = state.get("secrets", []) if state and isinstance(state, dict) else []
        secrets_count = len(secrets) if secrets else 0
        logger.info(f"[EMAIL_MANAGE] test_email_connection: получено секретов: {secrets_count}")
        if not secrets:
            logger.warning(f"[EMAIL_MANAGE] test_email_connection: ВНИМАНИЕ! Секреты не найдены в state")
            return "❌ Не найдена конфигурация почтового ящика. Убедитесь, что секреты настроены правильно."
        
        logger.info(f"[EMAIL_MANAGE] test_email_connection: вызываем EmailStorage.get_email_config_from_secrets с email_account={email_account}")
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        
        if not config:
            logger.warning(f"[EMAIL_MANAGE] test_email_connection: ВНИМАНИЕ! Конфигурация не найдена")
            return "❌ Не найдена конфигурация почтового ящика."
        
        logger.info(f"[EMAIL_MANAGE] test_email_connection: конфигурация найдена: email={config.get('email')}, imap_host={config.get('imap_host')}, smtp_host={config.get('smtp_host')}")
        
        if not EmailStorage.validate_config(config):
            logger.error(f"[EMAIL_MANAGE] test_email_connection: ОШИБКА! Конфигурация не прошла валидацию")
            return "❌ Неверная конфигурация почтового ящика."
        
        # Проверяем IMAP подключение
        logger.info(f"[EMAIL_MANAGE] test_email_connection: подключаемся к IMAP: host={config['imap_host']}, email={config['email']}")
        async with IMAPClient(
            host=config["imap_host"],
            email=config["email"],
            password=config["password"]
        ) as client:
            logger.info(f"[EMAIL_MANAGE] test_email_connection: успешно подключились к IMAP")
            folders = await client.get_folders()
            
            result = f"✅ **Подключение успешно**\n\n"
            result += f"Email: {config['email']}\n"
            result += f"IMAP сервер: {config['imap_host']}\n"
            result += f"Найдено папок: {len(folders)}\n"
            
            return result
            
    except Exception as e:
        logger.error(f"Ошибка проверки подключения: {e}")
        return f"❌ Ошибка подключения: {str(e)}"

