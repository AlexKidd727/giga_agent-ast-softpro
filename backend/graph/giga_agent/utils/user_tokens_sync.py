"""
Синхронная утилита для получения токенов пользователя из переменных окружения
Используется в синхронных контекстах (узлы графа)
ВНИМАНИЕ: Для получения токенов из PostgreSQL используйте асинхронные функции из user_tokens.py
"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def _get_user_from_db(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Синхронное получение пользователя из БД.
    ВНИМАНИЕ: SQLite удален, используйте асинхронные функции из user_tokens.py для работы с PostgreSQL.
    Эта функция всегда возвращает None и используется только для fallback на переменные окружения.
    """
    logger.warning(f"⚠️ _get_user_from_db: SQLite удален. Используйте асинхронные функции из user_tokens.py для работы с PostgreSQL. user_id={user_id}")
    return None


def get_user_tinkoff_token_sync(user_id: Optional[str] = None) -> Optional[str]:
    """
    Синхронное получение Tinkoff токена пользователя.
    Если user_id не указан, возвращает токен из переменной окружения.
    """
    if not user_id:
        return os.getenv("TINKOFF_TOKEN")
    
    user = _get_user_from_db(user_id)
    if user and user.get("tinkoff_token"):
        return user["tinkoff_token"]
    
    # Fallback на переменную окружения
    return os.getenv("TINKOFF_TOKEN")


def get_user_github_token_sync(user_id: Optional[str] = None) -> Optional[str]:
    """
    Синхронное получение GitHub токена пользователя.
    Если user_id не указан, возвращает токен из переменной окружения.
    """
    if not user_id:
        return os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    
    user = _get_user_from_db(user_id)
    if user and user.get("github_token"):
        return user["github_token"]
    
    # Fallback на переменную окружения
    return os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")


def get_user_google_calendar_credentials_sync(user_id: Optional[str] = None) -> Optional[str]:
    """
    Синхронное получение пути к Google Calendar credentials файлу пользователя.
    Если user_id не указан, возвращает путь из переменной окружения.
    """
    if not user_id:
        return os.getenv("GOOGLE_CALENDAR_CREDENTIALS")
    
    user = _get_user_from_db(user_id)
    if user and user.get("google_calendar_credentials"):
        return user["google_calendar_credentials"]
    
    # Fallback на переменную окружения
    return os.getenv("GOOGLE_CALENDAR_CREDENTIALS")


def get_user_google_calendar_id_sync(user_id: Optional[str] = None) -> Optional[str]:
    """
    Синхронное получение ID календаря пользователя.
    Если user_id не указан, возвращает ID из переменной окружения.
    """
    if not user_id:
        return os.getenv("CALENDAR_ID")
    
    user = _get_user_from_db(user_id)
    if user and user.get("google_calendar_id"):
        return user["google_calendar_id"]
    
    # Fallback на переменную окружения
    return os.getenv("CALENDAR_ID")


def get_user_tinkoff_config_sync(user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Синхронное получение полной конфигурации Tinkoff для пользователя.
    Возвращает словарь с token, account_id, sandbox.
    """
    config = {
        "token": None,
        "account_id": None,
        "sandbox": False
    }
    
    if not user_id:
        config["token"] = os.getenv("TINKOFF_TOKEN")
        config["account_id"] = os.getenv("TINKOFF_ACCOUNT_ID")
        config["sandbox"] = os.getenv("TINKOFF_SANDBOX", "false").lower() == "true"
        return config
    
    user = _get_user_from_db(user_id)
    if user:
        config["token"] = user.get("tinkoff_token") or os.getenv("TINKOFF_TOKEN")
        config["account_id"] = user.get("tinkoff_account_id") or os.getenv("TINKOFF_ACCOUNT_ID")
        config["sandbox"] = bool(user.get("tinkoff_sandbox")) if user.get("tinkoff_sandbox") is not None else (os.getenv("TINKOFF_SANDBOX", "false").lower() == "true")
    else:
        # Fallback на переменные окружения
        config["token"] = os.getenv("TINKOFF_TOKEN")
        config["account_id"] = os.getenv("TINKOFF_ACCOUNT_ID")
        config["sandbox"] = os.getenv("TINKOFF_SANDBOX", "false").lower() == "true"
    
    return config

