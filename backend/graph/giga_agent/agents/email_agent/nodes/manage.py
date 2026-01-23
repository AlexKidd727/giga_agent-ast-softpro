"""
Узел для управления почтовыми ящиками
"""

import logging
from typing import Dict, List, Optional
from langchain_core.tools import tool

from giga_agent.agents.email_agent.utils.imap_client import IMAPClient
from giga_agent.agents.email_agent.utils.storage import EmailStorage
from giga_agent.agents.email_agent.nodes.read import _read_emails_impl

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


@tool
async def bulk_delete_emails(
    email_hashes: List[str],
    email_account: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Массовое удаление писем по списку хэшей или message_id
    
    Args:
        email_hashes: Список хэшей писем или message_id для удаления
        email_account: Email адрес ящика
        state: Состояние агента (содержит loaded_emails)
    
    Returns:
        Результат массового удаления
    """
    try:
        logger.info(f"[EMAIL_MANAGE] bulk_delete_emails вызван: email_hashes count={len(email_hashes) if email_hashes else 0}, email_account={email_account}")
        
        if not email_hashes:
            return "❌ Не указаны хэши писем для удаления. Передайте список хэшей или message_id."
        
        if not state or not isinstance(state, dict):
            return "❌ Ошибка: состояние не найдено"
        
        # Получаем загруженные письма из state (используем хэш как основной идентификатор)
        loaded_emails_by_hash = state.get("loaded_emails_by_hash", {})  # Основной индекс по хэшу
        loaded_emails = state.get("loaded_emails", {})  # По номеру (для обратной совместимости)
        
        # Если письма не загружены, автоматически загружаем последние 10 писем
        if not loaded_emails_by_hash and not loaded_emails:
            logger.info(f"[EMAIL_MANAGE] bulk_delete_emails: письма не загружены, автоматически загружаем последние 10 писем")
            try:
                # Автоматически загружаем последние 10 писем для поиска по хэшу
                read_result, email_ids_map = await _read_emails_impl(
                    email_account=email_account,
                    folder="inbox",
                    unread_only=False,  # Читаем все письма (включая прочитанные)
                    limit=10,  # Загружаем последние 10 писем
                    state=state
                )
                
                # Обновляем загруженные письма из state (они уже сохранены в _read_emails_impl)
                loaded_emails_by_hash = state.get("loaded_emails_by_hash", {})
                loaded_emails = state.get("loaded_emails", {})
                
                logger.info(f"[EMAIL_MANAGE] bulk_delete_emails: автоматически загружено {len(loaded_emails_by_hash)} писем по хэшу и {len(loaded_emails)} по номеру")
                
                # Если после загрузки все еще нет писем, возвращаем ошибку
                if not loaded_emails_by_hash and not loaded_emails:
                    return "❌ Не удалось загрузить письма. Проверьте подключение к почтовому ящику."
            except Exception as e:
                logger.error(f"[EMAIL_MANAGE] bulk_delete_emails: ошибка при автоматической загрузке писем: {e}", exc_info=True)
                return f"❌ Ошибка при автоматической загрузке писем: {str(e)}"
        
        # Получаем секреты
        secrets = state.get("secrets", [])
        if not secrets:
            return "❌ Не найдена конфигурация почтового ящика."
        
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        if not config:
            return "❌ Не найдена конфигурация почтового ящика."
        
        # Создаем словарь для быстрого поиска по хэшу или message_id
        # Используем loaded_emails_by_hash как основной источник
        emails_by_hash = loaded_emails_by_hash.copy() if loaded_emails_by_hash else {}
        emails_by_message_id = {}
        emails_by_number = {}  # Для поиска по номеру
        
        # Дополняем из loaded_emails (по номеру) если нужно
        for idx, email_info in loaded_emails.items():
            email_hash = email_info.get('email_hash', '')
            message_id = email_info.get('message_id', '')
            if email_hash and email_hash not in emails_by_hash:
                emails_by_hash[email_hash] = email_info
            if message_id:
                emails_by_message_id[message_id] = email_info
            emails_by_number[idx] = email_info
        
        # Находим письма для удаления
        # Поддерживаем поиск по хэшу (основной), номеру (для обратной совместимости) или message_id
        emails_to_delete = []
        not_found_identifiers = []
        
        for identifier in email_hashes:
            email_info = None
            identifier_lower = identifier.lower() if isinstance(identifier, str) else str(identifier).lower()
            
            # Сначала ищем по хэшу (основной идентификатор) - точное совпадение
            if identifier in emails_by_hash:
                email_info = emails_by_hash[identifier]
                logger.info(f"[EMAIL_MANAGE] bulk_delete_emails: найдено письмо по хэшу: {identifier}")
            # Также пробуем поиск без учета регистра
            elif identifier_lower in {k.lower(): v for k, v in emails_by_hash.items()}:
                for k, v in emails_by_hash.items():
                    if k.lower() == identifier_lower:
                        email_info = v
                        logger.info(f"[EMAIL_MANAGE] bulk_delete_emails: найдено письмо по хэшу (без учета регистра): {identifier} -> {k}")
                        break
            # Затем по номеру (для обратной совместимости)
            elif identifier in emails_by_number:
                email_info = emails_by_number[identifier]
                logger.info(f"[EMAIL_MANAGE] bulk_delete_emails: найдено письмо по номеру: {identifier}")
            # Затем по message_id
            elif identifier in emails_by_message_id:
                email_info = emails_by_message_id[identifier]
                logger.info(f"[EMAIL_MANAGE] bulk_delete_emails: найдено письмо по message_id: {identifier}")
            
            if email_info:
                emails_to_delete.append(email_info)
            else:
                not_found_identifiers.append(identifier)
                logger.warning(f"[EMAIL_MANAGE] bulk_delete_emails: не найдено письмо с идентификатором: {identifier}")
                logger.debug(f"[EMAIL_MANAGE] bulk_delete_emails: доступные хэши (первые 5): {list(emails_by_hash.keys())[:5]}")
                logger.debug(f"[EMAIL_MANAGE] bulk_delete_emails: доступные номера: {list(emails_by_number.keys())[:5]}")
        
        if not emails_to_delete:
            error_msg = "❌ Не найдено ни одного письма для удаления по указанным идентификаторам.\n\n"
            error_msg += f"Искали: {email_hashes}\n"
            if not_found_identifiers:
                error_msg += f"Не найдены: {not_found_identifiers}\n"
            error_msg += "\n💡 **Подсказка:**\n"
            error_msg += "• Убедитесь, что письма загружены командой \"прочитать письма\"\n"
            error_msg += "• Используйте ID (хэш) из списка загруженных писем\n"
            error_msg += "• Или используйте номера писем из текущего списка (1, 2, 3...)\n"
            if loaded_emails_by_hash:
                sample_hashes = list(loaded_emails_by_hash.keys())[:3]
                error_msg += f"• Примеры доступных ID: {', '.join(sample_hashes)}\n"
            return error_msg
        
        logger.info(f"[EMAIL_MANAGE] bulk_delete_emails: найдено {len(emails_to_delete)} писем для удаления")
        
        # Подключаемся к IMAP и удаляем письма
        async with IMAPClient(
            host=config["imap_host"],
            email=config["email"],
            password=config["password"]
        ) as client:
            deleted_count = 0
            failed_count = 0
            failed_subjects = []
            
            for email_info in emails_to_delete:
                message_id_bytes = email_info.get('message_id_bytes')
                folder = email_info.get('folder', 'inbox')
                subject = email_info.get('subject', 'Без темы')
                
                if not message_id_bytes:
                    logger.warning(f"[EMAIL_MANAGE] bulk_delete_emails: не найден message_id_bytes для письма {subject}")
                    failed_count += 1
                    failed_subjects.append(subject)
                    continue
                
                # Выбираем папку
                await client.select_folder(folder)
                
                # Преобразуем message_id в bytes если нужно
                if isinstance(message_id_bytes, str):
                    try:
                        message_id_bytes = message_id_bytes.encode()
                    except:
                        pass
                
                # Удаляем письмо в корзину
                success = await client.move_to_trash(message_id_bytes, folder)
                
                if success:
                    deleted_count += 1
                    logger.info(f"[EMAIL_MANAGE] bulk_delete_emails: успешно удалено письмо: {subject}")
                else:
                    failed_count += 1
                    failed_subjects.append(subject)
                    logger.warning(f"[EMAIL_MANAGE] bulk_delete_emails: не удалось удалить письмо: {subject}")
            
            # Формируем результат
            result = f"✅ **Массовое удаление завершено**\n\n"
            result += f"Успешно удалено: {deleted_count} из {len(emails_to_delete)}\n"
            
            if failed_count > 0:
                result += f"Не удалось удалить: {failed_count}\n"
                if failed_subjects:
                    result += f"Проблемные письма: {', '.join(failed_subjects[:5])}"
                    if len(failed_subjects) > 5:
                        result += f" и еще {len(failed_subjects) - 5}"
            
            return result
            
    except Exception as e:
        logger.error(f"Ошибка массового удаления писем: {e}", exc_info=True)
        return f"❌ Ошибка массового удаления: {str(e)}"


@tool
async def bulk_move_to_spam(
    email_hashes: List[str],
    email_account: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Массовый перенос писем в папку Spam по списку хэшей или message_id
    
    Args:
        email_hashes: Список хэшей писем или message_id для переноса в spam
        email_account: Email адрес ящика
        state: Состояние агента (содержит loaded_emails)
    
    Returns:
        Результат массового переноса в spam
    """
    try:
        logger.info(f"[EMAIL_MANAGE] bulk_move_to_spam вызван: email_hashes count={len(email_hashes) if email_hashes else 0}, email_account={email_account}")
        
        if not email_hashes:
            return "❌ Не указаны хэши писем для переноса в spam. Передайте список хэшей или message_id."
        
        if not state or not isinstance(state, dict):
            return "❌ Ошибка: состояние не найдено"
        
        # Получаем загруженные письма из state (используем хэш как основной идентификатор)
        loaded_emails_by_hash = state.get("loaded_emails_by_hash", {}) if state and isinstance(state, dict) else {}  # Основной индекс по хэшу
        loaded_emails = state.get("loaded_emails", {}) if state and isinstance(state, dict) else {}  # По номеру (для обратной совместимости)
        
        logger.info(f"[EMAIL_MANAGE] bulk_move_to_spam: loaded_emails_by_hash count={len(loaded_emails_by_hash)}, loaded_emails count={len(loaded_emails)}")
        logger.info(f"[EMAIL_MANAGE] bulk_move_to_spam: ищем письма по идентификаторам: {email_hashes}")
        
        # Если письма не загружены, автоматически загружаем последние 10 писем
        if not loaded_emails_by_hash and not loaded_emails:
            logger.info(f"[EMAIL_MANAGE] bulk_move_to_spam: письма не загружены, автоматически загружаем последние 10 писем")
            try:
                # Автоматически загружаем последние 10 писем для поиска по хэшу
                read_result, email_ids_map = await _read_emails_impl(
                    email_account=email_account,
                    folder="inbox",
                    unread_only=False,  # Читаем все письма (включая прочитанные)
                    limit=10,  # Загружаем последние 10 писем
                    state=state
                )
                
                # Обновляем загруженные письма из state (они уже сохранены в _read_emails_impl)
                loaded_emails_by_hash = state.get("loaded_emails_by_hash", {})
                loaded_emails = state.get("loaded_emails", {})
                
                logger.info(f"[EMAIL_MANAGE] bulk_move_to_spam: автоматически загружено {len(loaded_emails_by_hash)} писем по хэшу и {len(loaded_emails)} по номеру")
                
                # Если после загрузки все еще нет писем, возвращаем ошибку
                if not loaded_emails_by_hash and not loaded_emails:
                    return "❌ Не удалось загрузить письма. Проверьте подключение к почтовому ящику."
            except Exception as e:
                logger.error(f"[EMAIL_MANAGE] bulk_move_to_spam: ошибка при автоматической загрузке писем: {e}", exc_info=True)
                return f"❌ Ошибка при автоматической загрузке писем: {str(e)}"
        
        # Получаем секреты
        secrets = state.get("secrets", [])
        if not secrets:
            return "❌ Не найдена конфигурация почтового ящика."
        
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        if not config:
            return "❌ Не найдена конфигурация почтового ящика."
        
        # Создаем словарь для быстрого поиска по хэшу или message_id
        emails_by_hash = loaded_emails_by_hash.copy() if loaded_emails_by_hash else {}
        emails_by_message_id = {}
        emails_by_number = {}  # Для поиска по номеру
        
        # Дополняем из loaded_emails (по номеру) если нужно
        for idx, email_info in loaded_emails.items():
            email_hash = email_info.get('email_hash', '')
            message_id = email_info.get('message_id', '')
            if email_hash and email_hash not in emails_by_hash:
                emails_by_hash[email_hash] = email_info
            if message_id:
                emails_by_message_id[message_id] = email_info
            emails_by_number[idx] = email_info
        
        # Находим письма для переноса
        # Поддерживаем поиск по хэшу (основной), номеру (для обратной совместимости) или message_id
        emails_to_move = []
        not_found_identifiers = []
        
        for identifier in email_hashes:
            email_info = None
            identifier_lower = identifier.lower() if isinstance(identifier, str) else str(identifier).lower()
            
            # Сначала ищем по хэшу (основной идентификатор) - точное совпадение
            if identifier in emails_by_hash:
                email_info = emails_by_hash[identifier]
                logger.info(f"[EMAIL_MANAGE] bulk_move_to_spam: найдено письмо по хэшу: {identifier}")
            # Также пробуем поиск без учета регистра
            elif identifier_lower in {k.lower(): v for k, v in emails_by_hash.items()}:
                for k, v in emails_by_hash.items():
                    if k.lower() == identifier_lower:
                        email_info = v
                        logger.info(f"[EMAIL_MANAGE] bulk_move_to_spam: найдено письмо по хэшу (без учета регистра): {identifier} -> {k}")
                        break
            # Затем по номеру (для обратной совместимости)
            elif identifier in emails_by_number:
                email_info = emails_by_number[identifier]
                logger.info(f"[EMAIL_MANAGE] bulk_move_to_spam: найдено письмо по номеру: {identifier}")
            # Затем по message_id
            elif identifier in emails_by_message_id:
                email_info = emails_by_message_id[identifier]
                logger.info(f"[EMAIL_MANAGE] bulk_move_to_spam: найдено письмо по message_id: {identifier}")
            
            if email_info:
                emails_to_move.append(email_info)
            else:
                not_found_identifiers.append(identifier)
                logger.warning(f"[EMAIL_MANAGE] bulk_move_to_spam: не найдено письмо с идентификатором: {identifier}")
                logger.debug(f"[EMAIL_MANAGE] bulk_move_to_spam: доступные хэши (первые 5): {list(emails_by_hash.keys())[:5]}")
                logger.debug(f"[EMAIL_MANAGE] bulk_move_to_spam: доступные номера: {list(emails_by_number.keys())[:5]}")
        
        if not emails_to_move:
            error_msg = "❌ Не найдено ни одного письма для переноса в spam по указанным идентификаторам.\n\n"
            error_msg += f"Искали: {email_hashes}\n"
            if not_found_identifiers:
                error_msg += f"Не найдены: {not_found_identifiers}\n"
            error_msg += "\n💡 **Подсказка:**\n"
            error_msg += "• Убедитесь, что письма загружены командой \"прочитать письма\"\n"
            error_msg += "• Используйте ID (хэш) из списка загруженных писем\n"
            error_msg += "• Или используйте номера писем из текущего списка (1, 2, 3...)\n"
            if loaded_emails_by_hash:
                sample_hashes = list(loaded_emails_by_hash.keys())[:3]
                error_msg += f"• Примеры доступных ID: {', '.join(sample_hashes)}\n"
            return error_msg
        
        logger.info(f"[EMAIL_MANAGE] bulk_move_to_spam: найдено {len(emails_to_move)} писем для переноса в spam")
        
        # Подключаемся к IMAP и переносим письма
        async with IMAPClient(
            host=config["imap_host"],
            email=config["email"],
            password=config["password"]
        ) as client:
            moved_count = 0
            failed_count = 0
            failed_subjects = []
            
            for email_info in emails_to_move:
                message_id_bytes = email_info.get('message_id_bytes')
                folder = email_info.get('folder', 'inbox')
                subject = email_info.get('subject', 'Без темы')
                
                if not message_id_bytes:
                    logger.warning(f"[EMAIL_MANAGE] bulk_move_to_spam: не найден message_id_bytes для письма {subject}")
                    failed_count += 1
                    failed_subjects.append(subject)
                    continue
                
                # Выбираем папку
                await client.select_folder(folder)
                
                # Преобразуем message_id в bytes если нужно
                if isinstance(message_id_bytes, str):
                    try:
                        message_id_bytes = message_id_bytes.encode()
                    except:
                        pass
                
                # Переносим письмо в spam
                success = await client.move_to_spam(message_id_bytes)
                
                if success:
                    moved_count += 1
                    logger.info(f"[EMAIL_MANAGE] bulk_move_to_spam: успешно перенесено в spam письмо: {subject}")
                else:
                    failed_count += 1
                    failed_subjects.append(subject)
                    logger.warning(f"[EMAIL_MANAGE] bulk_move_to_spam: не удалось перенести в spam письмо: {subject}")
            
            # Формируем результат
            result = f"✅ **Массовый перенос в spam завершен**\n\n"
            result += f"Успешно перенесено: {moved_count} из {len(emails_to_move)}\n"
            
            if failed_count > 0:
                result += f"Не удалось перенести: {failed_count}\n"
                if failed_subjects:
                    result += f"Проблемные письма: {', '.join(failed_subjects[:5])}"
                    if len(failed_subjects) > 5:
                        result += f" и еще {len(failed_subjects) - 5}"
            
            return result
            
    except Exception as e:
        logger.error(f"Ошибка массового переноса в spam: {e}", exc_info=True)
        return f"❌ Ошибка массового переноса в spam: {str(e)}"