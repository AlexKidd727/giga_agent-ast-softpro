"""
Узел для отправки писем
"""

import logging
from typing import Dict, List, Optional
from langchain_core.tools import tool

from giga_agent.agents.email_agent.utils.smtp_client import SMTPClient
from giga_agent.agents.email_agent.utils.storage import EmailStorage

logger = logging.getLogger(__name__)


@tool
async def send_email(
    to: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
    cc: Optional[List[str]] = None,
    email_account: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Отправка письма
    
    Args:
        to: Email получателя
        subject: Тема письма
        body: Текст письма
        html_body: HTML версия письма (опционально)
        cc: Список получателей копии (опционально)
        email_account: Email адрес отправителя (если не указан, используется первый доступный)
        state: Состояние агента
    
    Returns:
        Результат отправки
    """
    try:
        logger.info(f"[EMAIL_SEND] send_email вызван: to={to}, subject={subject}, email_account={email_account}")
        secrets = state.get("secrets", []) if state and isinstance(state, dict) else []
        secrets_count = len(secrets) if secrets else 0
        logger.info(f"[EMAIL_SEND] send_email: получено секретов: {secrets_count}")
        if not secrets:
            logger.warning(f"[EMAIL_SEND] send_email: ВНИМАНИЕ! Секреты не найдены в state")
            return "❌ Не найдена конфигурация почтового ящика для отправки. Убедитесь, что секреты настроены правильно."
        
        logger.info(f"[EMAIL_SEND] send_email: вызываем EmailStorage.get_email_config_from_secrets с email_account={email_account}")
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        
        if not config:
            logger.warning(f"[EMAIL_SEND] send_email: ВНИМАНИЕ! Конфигурация не найдена")
            return "❌ Не найдена конфигурация почтового ящика для отправки."
        
        logger.info(f"[EMAIL_SEND] send_email: конфигурация найдена: email={config.get('email')}, imap_host={config.get('imap_host')}, smtp_host={config.get('smtp_host')}")
        
        # Определяем SMTP хост и порт
        smtp_host = config.get("smtp_host")
        if not smtp_host:
            # Пытаемся определить по IMAP хосту
            imap_host = config.get("imap_host", "")
            logger.info(f"[EMAIL_SEND] send_email: smtp_host не найден, пытаемся определить из imap_host={imap_host}")
            if "imap." in imap_host:
                smtp_host = imap_host.replace("imap.", "smtp.")
                logger.info(f"[EMAIL_SEND] send_email: определен smtp_host из imap_host: {smtp_host}")
            else:
                logger.error(f"[EMAIL_SEND] send_email: ОШИБКА! Не указан SMTP сервер и не удалось определить из imap_host")
                return "❌ Не указан SMTP сервер. Укажите smtp_host в конфигурации."
        else:
            logger.info(f"[EMAIL_SEND] send_email: используем smtp_host из конфигурации: {smtp_host}")
        
        smtp_port = config.get("smtp_port", 587)
        logger.info(f"[EMAIL_SEND] send_email: используем smtp_port: {smtp_port}")
        
        logger.info(f"[EMAIL_SEND] send_email: подключаемся к SMTP: host={smtp_host}, port={smtp_port}, email={config['email']}")
        async with SMTPClient(
            host=smtp_host,
            port=smtp_port,
            email=config["email"],
            password=config["password"]
        ) as client:
            logger.info(f"[EMAIL_SEND] send_email: успешно подключились к SMTP")
            success = await client.send_email(
                to=to,
                subject=subject,
                body=body,
                html_body=html_body,
                cc=cc
            )
            
            if success:
                return f"✅ Письмо успешно отправлено от {config['email']} к {to}"
            else:
                return f"❌ Не удалось отправить письмо"
                
    except Exception as e:
        logger.error(f"Ошибка отправки письма: {e}")
        return f"❌ Ошибка отправки письма: {str(e)}"


@tool
async def reply_to_email(
    original_subject: str,
    original_from: str,
    body: str,
    html_body: Optional[str] = None,
    email_account: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Ответ на письмо
    
    Args:
        original_subject: Тема оригинального письма
        original_from: Отправитель оригинального письма
        body: Текст ответа
        html_body: HTML версия ответа (опционально)
        email_account: Email адрес отправителя
        state: Состояние агента
    
    Returns:
        Результат отправки ответа
    """
    try:
        logger.info(f"[EMAIL_SEND] reply_to_email вызван: original_subject={original_subject}, original_from={original_from}, email_account={email_account}")
        secrets = state.get("secrets", []) if state and isinstance(state, dict) else []
        secrets_count = len(secrets) if secrets else 0
        logger.info(f"[EMAIL_SEND] reply_to_email: получено секретов: {secrets_count}")
        if not secrets:
            logger.warning(f"[EMAIL_SEND] reply_to_email: ВНИМАНИЕ! Секреты не найдены в state")
            return "❌ Не найдена конфигурация почтового ящика для отправки. Убедитесь, что секреты настроены правильно."
        
        logger.info(f"[EMAIL_SEND] reply_to_email: вызываем EmailStorage.get_email_config_from_secrets с email_account={email_account}")
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        
        if not config:
            logger.warning(f"[EMAIL_SEND] reply_to_email: ВНИМАНИЕ! Конфигурация не найдена")
            return "❌ Не найдена конфигурация почтового ящика для отправки."
        
        logger.info(f"[EMAIL_SEND] reply_to_email: конфигурация найдена: email={config.get('email')}, smtp_host={config.get('smtp_host')}")
        
        smtp_host = config.get("smtp_host")
        if not smtp_host:
            imap_host = config.get("imap_host", "")
            logger.info(f"[EMAIL_SEND] reply_to_email: smtp_host не найден, пытаемся определить из imap_host={imap_host}")
            if "imap." in imap_host:
                smtp_host = imap_host.replace("imap.", "smtp.")
                logger.info(f"[EMAIL_SEND] reply_to_email: определен smtp_host из imap_host: {smtp_host}")
            else:
                logger.error(f"[EMAIL_SEND] reply_to_email: ОШИБКА! Не указан SMTP сервер")
                return "❌ Не указан SMTP сервер."
        else:
            logger.info(f"[EMAIL_SEND] reply_to_email: используем smtp_host из конфигурации: {smtp_host}")
        
        smtp_port = config.get("smtp_port", 587)
        logger.info(f"[EMAIL_SEND] reply_to_email: используем smtp_port: {smtp_port}")
        
        # Формируем информацию об оригинальном письме
        original_msg = {
            "subject": original_subject,
            "from": original_from
        }
        
        async with SMTPClient(
            host=smtp_host,
            port=smtp_port,
            email=config["email"],
            password=config["password"]
        ) as client:
            success = await client.reply_to_email(
                original_msg=original_msg,
                body=body,
                html_body=html_body
            )
            
            if success:
                return f"✅ Ответ успешно отправлен от {config['email']} к {original_from}"
            else:
                return f"❌ Не удалось отправить ответ"
                
    except Exception as e:
        logger.error(f"Ошибка отправки ответа: {e}")
        return f"❌ Ошибка отправки ответа: {str(e)}"

