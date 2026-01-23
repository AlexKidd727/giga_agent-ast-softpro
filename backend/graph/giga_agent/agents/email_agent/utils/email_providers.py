"""
Типовые настройки для основных почтовых серверов
Автоматическое определение IMAP/SMTP хостов и портов по домену email
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# Словарь с настройками почтовых провайдеров
# Ключ - домен или часть домена email
# Значение - словарь с настройками {imap_host, imap_port, smtp_host, smtp_port}
EMAIL_PROVIDERS = {
    # Gmail
    "gmail.com": {
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
    },
    # Yandex
    "yandex.ru": {
        "imap_host": "imap.yandex.ru",
        "imap_port": 993,
        "smtp_host": "smtp.yandex.ru",
        "smtp_port": 465,
    },
    "ya.ru": {
        "imap_host": "imap.yandex.ru",
        "imap_port": 993,
        "smtp_host": "smtp.yandex.ru",
        "smtp_port": 465,
    },
    # Mail.ru
    "mail.ru": {
        "imap_host": "imap.mail.ru",
        "imap_port": 993,
        "smtp_host": "smtp.mail.ru",
        "smtp_port": 465,
    },
    "inbox.ru": {
        "imap_host": "imap.mail.ru",
        "imap_port": 993,
        "smtp_host": "smtp.mail.ru",
        "smtp_port": 465,
    },
    "list.ru": {
        "imap_host": "imap.mail.ru",
        "imap_port": 993,
        "smtp_host": "smtp.mail.ru",
        "smtp_port": 465,
    },
    "bk.ru": {
        "imap_host": "imap.mail.ru",
        "imap_port": 993,
        "smtp_host": "smtp.mail.ru",
        "smtp_port": 465,
    },
    # Hoster.ru
    "hoster.ru": {
        "imap_host": "imap.hoster.ru",
        "imap_port": 993,
        "smtp_host": "smtp.hoster.ru",
        "smtp_port": 587,
    },
    # Outlook/Hotmail
    "outlook.com": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
    },
    "hotmail.com": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
    },
    "live.com": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
    },
    "msn.com": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
    },
    # Yahoo
    "yahoo.com": {
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": 587,
    },
    "yahoo.co.uk": {
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": 587,
    },
    # ProtonMail
    "protonmail.com": {
        "imap_host": "127.0.0.1",  # Требует ProtonMail Bridge
        "imap_port": 1143,
        "smtp_host": "127.0.0.1",
        "smtp_port": 1025,
    },
    "proton.me": {
        "imap_host": "127.0.0.1",  # Требует ProtonMail Bridge
        "imap_port": 1143,
        "smtp_host": "127.0.0.1",
        "smtp_port": 1025,
    },
    # Rambler
    "rambler.ru": {
        "imap_host": "imap.rambler.ru",
        "imap_port": 993,
        "smtp_host": "smtp.rambler.ru",
        "smtp_port": 465,
    },
    # iCloud
    "icloud.com": {
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "smtp_host": "smtp.mail.me.com",
        "smtp_port": 587,
    },
    "me.com": {
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "smtp_host": "smtp.mail.me.com",
        "smtp_port": 587,
    },
    # AOL
    "aol.com": {
        "imap_host": "imap.aol.com",
        "imap_port": 993,
        "smtp_host": "smtp.aol.com",
        "smtp_port": 587,
    },
}


def get_email_provider_settings(email: str) -> Optional[Dict[str, any]]:
    """
    Получение типовых настроек для почтового провайдера по email адресу
    
    Args:
        email: Email адрес (например, user@example.com)
    
    Returns:
        Словарь с настройками {imap_host, imap_port, smtp_host, smtp_port} или None
    """
    if not email or "@" not in email:
        logger.warning(f"[EMAIL_PROVIDERS] get_email_provider_settings: неверный формат email: {email}")
        return None
    
    # Извлекаем домен из email
    domain = email.lower().split("@")[1].strip()
    logger.info(f"[EMAIL_PROVIDERS] get_email_provider_settings: извлечен домен из {email}: {domain}")
    
    # Прямое совпадение домена
    if domain in EMAIL_PROVIDERS:
        settings = EMAIL_PROVIDERS[domain]
        logger.info(f"[EMAIL_PROVIDERS] get_email_provider_settings: найдены настройки для {domain}: imap_host={settings['imap_host']}, smtp_host={settings['smtp_host']}")
        return settings.copy()
    
    # Проверяем части домена (например, для user@mail.yandex.ru)
    domain_parts = domain.split(".")
    for i in range(len(domain_parts)):
        # Проверяем поддомены (mail.yandex.ru -> yandex.ru)
        subdomain = ".".join(domain_parts[i:])
        if subdomain in EMAIL_PROVIDERS:
            settings = EMAIL_PROVIDERS[subdomain]
            logger.info(f"[EMAIL_PROVIDERS] get_email_provider_settings: найдены настройки для поддомена {subdomain}: imap_host={settings['imap_host']}, smtp_host={settings['smtp_host']}")
            return settings.copy()
    
    logger.info(f"[EMAIL_PROVIDERS] get_email_provider_settings: настройки для домена {domain} не найдены")
    return None


def get_default_email_settings(email: str) -> Dict[str, any]:
    """
    Получение настроек для email адреса (типовые или значения по умолчанию)
    
    Args:
        email: Email адрес
    
    Returns:
        Словарь с настройками {imap_host, imap_port, smtp_host, smtp_port}
        Если типовые настройки не найдены, возвращает значения по умолчанию
    """
    provider_settings = get_email_provider_settings(email)
    
    if provider_settings:
        return provider_settings
    
    # Если настройки не найдены, пытаемся определить по домену
    if "@" in email:
        domain = email.lower().split("@")[1].strip()
        # Пытаемся сформировать стандартные имена серверов
        # Например, для example.com -> imap.example.com и smtp.example.com
        default_settings = {
            "imap_host": f"imap.{domain}",
            "imap_port": 993,
            "smtp_host": f"smtp.{domain}",
            "smtp_port": 587,
        }
        logger.info(f"[EMAIL_PROVIDERS] get_default_email_settings: используем стандартные настройки для {domain}: imap_host={default_settings['imap_host']}, smtp_host={default_settings['smtp_host']}")
        return default_settings
    
    # Последний вариант - значения по умолчанию
    default_settings = {
        "imap_host": "imap.hoster.ru",
        "imap_port": 993,
        "smtp_host": "smtp.hoster.ru",
        "smtp_port": 587,
    }
    logger.warning(f"[EMAIL_PROVIDERS] get_default_email_settings: используем настройки по умолчанию (hoster.ru)")
    return default_settings

