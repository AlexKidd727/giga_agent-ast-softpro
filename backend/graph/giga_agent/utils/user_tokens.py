"""
Утилита для получения токенов пользователя из базы данных
"""

import os
import json
import logging
from typing import Optional, Dict, Any
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

try:
    from giga_agent.tasks_app import User, AsyncSessionLocal
except ImportError:
    # Если импорт не удался (например, при первом запуске), используем fallback
    User = None
    AsyncSessionLocal = None

logger = logging.getLogger(__name__)

# Список специальных значений user_id, которые должны обрабатываться как None
# Работа только после аутентификации - невалидные значения отклоняются
INVALID_USER_IDS = {"anonymous", "default_user", "guest", "public", ""}


def _normalize_user_id(user_id: Optional[str] = None) -> Optional[str]:
    """
    Нормализует user_id, обрабатывая специальные значения как None.
    Работа только после аутентификации - невалидные значения возвращают None.
    
    Args:
        user_id: Идентификатор пользователя
        
    Returns:
        None если user_id является специальным значением, иначе возвращает user_id
    """
    if not user_id:
        return None
    
    user_id_str = str(user_id).strip().lower()
    if user_id_str in INVALID_USER_IDS:
        logger.warning(f"⚠️ Обнаружен невалидный user_id: '{user_id}' - работа только после аутентификации")
        return None
    
    return user_id


async def get_user_tinkoff_token(user_id: Optional[str] = None) -> Optional[str]:
    """
    Получить Tinkoff токен пользователя.
    Работа только после аутентификации - если user_id невалидный, возвращает None.
    """
    # Нормализуем user_id - невалидные значения (anonymous и т.д.) преобразуются в None
    user_id = _normalize_user_id(user_id)
    
    # Если user_id невалидный или отсутствует - нет работы без аутентификации
    if not user_id:
        return None
    
    if not AsyncSessionLocal or not User:
        return None
    
    try:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            if user and user.tinkoff_token:
                return user.tinkoff_token
            return None
    except Exception as e:
        # Проверяем, является ли ошибка связанной с отсутствием таблицы
        error_str = str(e).lower()
        if "no such table" in error_str or "table" in error_str and "does not exist" in error_str:
            logger.warning(f"⚠️ Таблица user не существует в БД: {e}")
        else:
            logger.error(f"Ошибка при получении Tinkoff токена для пользователя {user_id}: {e}")
        return None


async def get_user_github_token(user_id: Optional[str] = None) -> Optional[str]:
    """
    Получить GitHub токен пользователя.
    Работа только после аутентификации - если user_id невалидный, возвращает None.
    """
    # Нормализуем user_id - невалидные значения (anonymous и т.д.) преобразуются в None
    user_id = _normalize_user_id(user_id)
    
    # Если user_id невалидный или отсутствует - нет работы без аутентификации
    if not user_id:
        return None
    
    if not AsyncSessionLocal or not User:
        return None
    
    try:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            if user and user.github_token:
                return user.github_token
            return None
    except Exception as e:
        # Проверяем, является ли ошибка связанной с отсутствием таблицы
        error_str = str(e).lower()
        if "no such table" in error_str or "table" in error_str and "does not exist" in error_str:
            logger.warning(f"⚠️ Таблица user не существует в БД: {e}")
        else:
            logger.error(f"Ошибка при получении GitHub токена для пользователя {user_id}: {e}")
        return None


async def get_user_google_calendar_credentials(user_id: Optional[str] = None) -> Optional[str]:
    """
    Получить путь к Google Calendar credentials файлу пользователя.
    Работа только после аутентификации - если user_id невалидный, возвращает None.
    """
    # Нормализуем user_id - невалидные значения (anonymous и т.д.) преобразуются в None
    user_id = _normalize_user_id(user_id)
    
    # Если user_id невалидный или отсутствует - нет работы без аутентификации
    if not user_id:
        return None
    
    if not AsyncSessionLocal or not User:
        return None
    
    try:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            if user and user.google_calendar_credentials:
                return user.google_calendar_credentials
            return None
    except Exception as e:
        # Проверяем, является ли ошибка связанной с отсутствием таблицы
        error_str = str(e).lower()
        if "no such table" in error_str or "table" in error_str and "does not exist" in error_str:
            logger.warning(f"⚠️ Таблица user не существует в БД: {e}")
        else:
            logger.error(f"Ошибка при получении Google Calendar credentials для пользователя {user_id}: {e}")
        return None


async def get_user_google_calendar_id(user_id: Optional[str] = None) -> Optional[str]:
    """
    Получить ID календаря пользователя.
    Работа только после аутентификации - если user_id невалидный, возвращает None.
    """
    # Нормализуем user_id - невалидные значения (anonymous и т.д.) преобразуются в None
    user_id = _normalize_user_id(user_id)
    
    # Если user_id невалидный или отсутствует - нет работы без аутентификации
    if not user_id:
        return None
    
    if not AsyncSessionLocal or not User:
        return None
    
    try:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            if user and user.google_calendar_id:
                return user.google_calendar_id
            return None
    except Exception as e:
        # Проверяем, является ли ошибка связанной с отсутствием таблицы
        error_str = str(e).lower()
        if "no such table" in error_str or "table" in error_str and "does not exist" in error_str:
            logger.warning(f"⚠️ Таблица user не существует в БД: {e}")
        else:
            logger.error(f"Ошибка при получении Google Calendar ID для пользователя {user_id}: {e}")
        return None


async def get_user_tinkoff_config(user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Получить полную конфигурацию Tinkoff для пользователя.
    Работа только после аутентификации - если user_id невалидный, возвращает пустую конфигурацию.
    Возвращает словарь с token, account_id, sandbox.
    """
    config = {
        "token": None,
        "account_id": None,
        "sandbox": False
    }
    
    # Нормализуем user_id - невалидные значения (anonymous и т.д.) преобразуются в None
    user_id = _normalize_user_id(user_id)
    
    # Если user_id невалидный или отсутствует - нет работы без аутентификации
    if not user_id:
        return config
    
    if not AsyncSessionLocal or not User:
        return config
    
    try:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            if user:
                config["token"] = user.tinkoff_token
                config["account_id"] = user.tinkoff_account_id
                config["sandbox"] = user.tinkoff_sandbox if user.tinkoff_sandbox is not None else False
    except Exception as e:
        # Проверяем, является ли ошибка связанной с отсутствием таблицы
        error_str = str(e).lower()
        if "no such table" in error_str or "table" in error_str and "does not exist" in error_str:
            logger.warning(f"⚠️ Таблица user не существует в БД: {e}")
        else:
            logger.error(f"Ошибка при получении конфигурации Tinkoff для пользователя {user_id}: {e}")
    
    return config


async def _get_admin_user_id() -> Optional[str]:
    """
    Получить ID пользователя-админа (admin) из БД.
    Используется как fallback, если user_id не указан.
    """
    if not AsyncSessionLocal or not User:
        return None
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.username == "admin"))
            admin_user = result.scalar_one_or_none()
            if admin_user:
                return admin_user.id
    except Exception as e:
        # Проверяем, является ли ошибка связанной с отсутствием таблицы
        error_str = str(e).lower()
        if "no such table" in error_str or "table" in error_str and "does not exist" in error_str:
            logger.warning(f"⚠️ Таблица user не существует в БД. База данных не инициализирована: {e}")
        else:
            logger.error(f"Ошибка при получении ID админа: {e}")
    
    return None


async def has_user_tinkoff_token(user_id: Optional[str] = None) -> bool:
    """
    Проверить наличие Tinkoff токена у пользователя.
    Работа только после аутентификации - если user_id невалидный, возвращает False.
    Возвращает True только если токен есть в БД у пользователя.
    """
    # Нормализуем user_id - невалидные значения (anonymous и т.д.) преобразуются в None
    user_id = _normalize_user_id(user_id)
    
    # Если user_id невалидный или отсутствует - нет работы без аутентификации
    if not user_id:
        return False
    
    if not AsyncSessionLocal or not User:
        return False
    
    try:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            if not user:
                logger.warning(f"❌ Пользователь с user_id={user_id} не найден в БД")
                return False
            
            has_token = user.tinkoff_token is not None and user.tinkoff_token.strip() != ""
            token_preview = user.tinkoff_token[:10] + "..." if user.tinkoff_token else "None"
            logger.info(
                f"🔍 Проверка Tinkoff токена для user_id={user_id} (username={user.username}): "
                f"has_token={has_token}, token_preview={token_preview}"
            )
            
            return has_token
    except Exception as e:
        # Проверяем, является ли ошибка связанной с отсутствием таблицы
        error_str = str(e).lower()
        if "no such table" in error_str or "table" in error_str and "does not exist" in error_str:
            logger.warning(f"⚠️ Таблица user не существует в БД: {e}")
        else:
            logger.error(f"❌ Ошибка при проверке Tinkoff токена для пользователя {user_id}: {e}", exc_info=True)
        return False


async def has_user_github_token(user_id: Optional[str] = None) -> bool:
    """
    Проверить наличие GitHub токена у пользователя.
    Работа только после аутентификации - если user_id невалидный, возвращает False.
    Возвращает True только если токен есть в БД у пользователя.
    """
    # Нормализуем user_id - невалидные значения (anonymous и т.д.) преобразуются в None
    user_id = _normalize_user_id(user_id)
    
    # Если user_id невалидный или отсутствует - нет работы без аутентификации
    if not user_id:
        return False
    
    if not AsyncSessionLocal or not User:
        return False
    
    try:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            return user is not None and user.github_token is not None and user.github_token.strip() != ""
    except Exception as e:
        # Проверяем, является ли ошибка связанной с отсутствием таблицы
        error_str = str(e).lower()
        if "no such table" in error_str or "table" in error_str and "does not exist" in error_str:
            logger.warning(f"⚠️ Таблица user не существует в БД: {e}")
        else:
            logger.error(f"Ошибка при проверке GitHub токена для пользователя {user_id}: {e}")
        return False


async def has_user_google_calendar_credentials(user_id: Optional[str] = None) -> bool:
    """
    Проверить наличие Google Calendar credentials у пользователя.
    Работа только после аутентификации - если user_id невалидный, возвращает False.
    Возвращает True только если credentials есть в БД у пользователя.
    """
    # Нормализуем user_id - невалидные значения (anonymous и т.д.) преобразуются в None
    user_id = _normalize_user_id(user_id)
    
    # Если user_id невалидный или отсутствует - нет работы без аутентификации
    if not user_id:
        return False
    
    if not AsyncSessionLocal or not User:
        return False
    
    try:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            return user is not None and user.google_calendar_credentials is not None and user.google_calendar_credentials.strip() != ""
    except Exception as e:
        # Проверяем, является ли ошибка связанной с отсутствием таблицы
        error_str = str(e).lower()
        if "no such table" in error_str or "table" in error_str and "does not exist" in error_str:
            logger.warning(f"⚠️ Таблица user не существует в БД: {e}")
        else:
            logger.error(f"Ошибка при проверке Google Calendar credentials для пользователя {user_id}: {e}")
        return False


async def get_user_email_accounts_secrets(user_id: Optional[str] = None) -> list:
    """
    Получить почтовые ящики пользователя из БД и преобразовать их в формат секретов.
    Работа только после аутентификации - если user_id невалидный, возвращает пустой список.
    
    Args:
        user_id: Идентификатор пользователя
    
    Returns:
        Список секретов в формате [{"name": "...", "value": "...", "description": "..."}, ...]
    """
    # Нормализуем user_id - невалидные значения (anonymous и т.д.) преобразуются в None
    user_id = _normalize_user_id(user_id)
    
    # Если user_id невалидный или отсутствует - нет работы без аутентификации
    if not user_id:
        return []
    
    if not AsyncSessionLocal:
        return []
    
    try:
        logger.info(f"[USER_TOKENS] get_user_email_accounts_secrets: начинаем загрузку для user_id={user_id}")
        from giga_agent.tasks_app import EmailAccount
        from sqlmodel import select
        
        secrets = []
        async with AsyncSessionLocal() as session:
            # Загружаем все почтовые ящики пользователя
            logger.info(f"[USER_TOKENS] get_user_email_accounts_secrets: выполняем запрос к БД для user_id={user_id}")
            result = await session.execute(
                select(EmailAccount).where(EmailAccount.user_id == user_id)
            )
            email_accounts = result.scalars().all()
            logger.info(f"[USER_TOKENS] get_user_email_accounts_secrets: найдено почтовых ящиков в БД: {len(email_accounts)}")
            
            # Флаг для отслеживания первого ящика (для общих секретов)
            is_first_account = True
            
            for account in email_accounts:
                logger.info(f"[USER_TOKENS] get_user_email_accounts_secrets: обрабатываем ящик: email={account.email}, imap_host={account.imap_host}, smtp_host={account.smtp_host}, imap_port={account.imap_port}, smtp_port={account.smtp_port}")
                # Формируем ключи для поиска (email адрес с заменой @ и . на _)
                account_lower = account.email.lower().replace("@", "_").replace(".", "_")
                
                # Email адрес
                secrets.append({
                    "name": f"{account_lower}_email",
                    "value": account.email,
                    "description": f"Email адрес почтового ящика {account.email}"
                })
                secrets.append({
                    "name": "email_account",
                    "value": account.email,
                    "description": f"Email адрес почтового ящика {account.email}"
                })
                
                # Пароль
                secrets.append({
                    "name": f"{account_lower}_password",
                    "value": account.password,
                    "description": f"Пароль почтового ящика {account.email}"
                })
                # Также добавляем общий email_password для совместимости (только для первого ящика)
                if is_first_account:
                    secrets.append({
                        "name": "email_password",
                        "value": account.password,
                        "description": "Пароль почтового ящика (общий)"
                    })
                
                # IMAP хост
                secrets.append({
                    "name": f"{account_lower}_imap_host",
                    "value": account.imap_host,
                    "description": f"IMAP сервер для {account.email}"
                })
                # Также добавляем общий imap_host для совместимости (только для первого ящика)
                if is_first_account:
                    secrets.append({
                        "name": "imap_host",
                        "value": account.imap_host,
                        "description": "IMAP сервер (общий)"
                    })
                
                # SMTP хост
                secrets.append({
                    "name": f"{account_lower}_smtp_host",
                    "value": account.smtp_host,
                    "description": f"SMTP сервер для {account.email}"
                })
                # Также добавляем общий smtp_host для совместимости (только для первого ящика)
                if is_first_account:
                    secrets.append({
                        "name": "smtp_host",
                        "value": account.smtp_host,
                        "description": "SMTP сервер (общий)"
                    })
                
                # IMAP порт
                secrets.append({
                    "name": f"{account_lower}_imap_port",
                    "value": str(account.imap_port),
                    "description": f"IMAP порт для {account.email}"
                })
                # Также добавляем общий imap_port для совместимости (только для первого ящика)
                if is_first_account:
                    secrets.append({
                        "name": "imap_port",
                        "value": str(account.imap_port),
                        "description": "IMAP порт (общий)"
                    })
                
                # SMTP порт
                secrets.append({
                    "name": f"{account_lower}_smtp_port",
                    "value": str(account.smtp_port),
                    "description": f"SMTP порт для {account.email}"
                })
                # Также добавляем общий smtp_port для совместимости (только для первого ящика)
                if is_first_account:
                    secrets.append({
                        "name": "smtp_port",
                        "value": str(account.smtp_port),
                        "description": "SMTP порт (общий)"
                    })
                
                # После первого ящика сбрасываем флаг
                is_first_account = False
            
            logger.info(f"[USER_TOKENS] get_user_email_accounts_secrets: УСПЕШНО загружено {len(email_accounts)} почтовых ящиков для user_id={user_id}, создано {len(secrets)} секретов")
            # Логируем имена созданных секретов
            secret_names = [s.get("name", "unknown") for s in secrets[:20]]
            logger.info(f"[USER_TOKENS] get_user_email_accounts_secrets: имена созданных секретов (первые 20): {secret_names}")
            return secrets
            
    except Exception as e:
        # Проверяем, является ли ошибка связанной с отсутствием таблицы
        error_str = str(e).lower()
        if "no such table" in error_str or "table" in error_str and "does not exist" in error_str:
            logger.warning(f"[USER_TOKENS] get_user_email_accounts_secrets: ВНИМАНИЕ! Таблица emailaccount не существует в БД: {e}")
        else:
            logger.error(f"[USER_TOKENS] get_user_email_accounts_secrets: ОШИБКА при получении почтовых ящиков для пользователя {user_id}: {e}", exc_info=True)
        return []


def has_user_email_config(secrets: list) -> bool:
    """
    Проверить наличие конфигурации почтовых ящиков у пользователя.
    Проверяет наличие секретов с email конфигурацией в state["secrets"].
    
    Args:
        secrets: Список секретов из state["secrets"]
    
    Returns:
        True если найдена хотя бы одна конфигурация email ящика
    """
    if not secrets:
        return False
    
    # Ищем секреты, связанные с почтой
    for secret in secrets:
        name = secret.get("name", "").lower()
        value = secret.get("value", "")
        
        # Проверяем наличие email адреса и пароля
        if ("email" in name or "mail" in name) and "@" in value and "." in value:
            # Проверяем наличие пароля для этого email
            account_lower = value.lower().replace("@", "_").replace(".", "_")
            for sec in secrets:
                sec_name = sec.get("name", "").lower()
                if f"{account_lower}_password" in sec_name or "email_password" in sec_name:
                    sec_value = sec.get("value", "")
                    if sec_value and sec_value.strip():
                        # Проверяем наличие imap_host
                        for sec2 in secrets:
                            sec2_name = sec2.get("name", "").lower()
                            if f"{account_lower}_imap_host" in sec2_name or "imap_host" in sec2_name:
                                sec2_value = sec2.get("value", "")
                                if sec2_value and sec2_value.strip():
                                    return True
    
    return False
