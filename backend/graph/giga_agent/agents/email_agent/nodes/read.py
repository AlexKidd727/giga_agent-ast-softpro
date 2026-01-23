"""
Узел для чтения писем
"""

import logging
import re
import html as html_module
import hashlib
from typing import Dict, List, Optional
from langchain_core.tools import tool

from giga_agent.agents.email_agent.utils.imap_client import IMAPClient
from giga_agent.agents.email_agent.utils.email_parser import parse_email_message
from giga_agent.agents.email_agent.utils.storage import EmailStorage

logger = logging.getLogger(__name__)


def calculate_email_hash(message_id: str, email_account: str, folder: str, subject: str = "", from_email: str = "", date: str = "") -> str:
    """
    Вычисляет уникальный хэш для письма на основе его идентификаторов
    
    Args:
        message_id: ID сообщения в почтовой системе
        email_account: Email адрес ящика
        folder: Папка, в которой находится письмо
        subject: Тема письма (опционально, для дополнительной уникальности)
        from_email: Отправитель (опционально)
        date: Дата письма (опционально)
    
    Returns:
        Хэш-строка для уникальной идентификации письма
    """
    # Создаем строку для хэширования из всех идентификаторов
    hash_string = f"{message_id}|{email_account}|{folder}|{subject}|{from_email}|{date}"
    # Вычисляем SHA256 хэш
    hash_obj = hashlib.sha256(hash_string.encode('utf-8'))
    return hash_obj.hexdigest()[:16]  # Возвращаем первые 16 символов для удобства


# Внутренняя функция для чтения писем без декоратора @tool
# Используется для прямого вызова из других функций, чтобы гарантировать сохранение state
async def _read_emails_impl(
    email_account: Optional[str] = None,
    folder: str = "inbox",
    unread_only: bool = True,
    limit: int = 20,
    state: Optional[Dict] = None
) -> tuple[str, Dict]:
    """
    Внутренняя реализация чтения писем (без декоратора @tool)
    
    Returns:
        tuple: (результат в виде строки, email_ids_map для сохранения в state)
    """
    try:
        logger.info(f"[EMAIL_READ] _read_emails_impl вызван: email_account={email_account}, folder={folder}, unread_only={unread_only}, limit={limit}")
        # Получаем конфигурацию из секретов
        logger.info(f"[EMAIL_READ] _read_emails_impl: state type={type(state)}, state keys={list(state.keys()) if state and isinstance(state, dict) else 'N/A'}")
        secrets = state.get("secrets", []) if state and isinstance(state, dict) else []
        secrets_count = len(secrets) if secrets else 0
        logger.info(f"[EMAIL_READ] _read_emails_impl: получено секретов: {secrets_count}")
        
        if not secrets:
            logger.warning(f"[EMAIL_READ] _read_emails_impl: ВНИМАНИЕ! Секреты не найдены в state")
            return ("❌ Не найдена конфигурация почтового ящика. Убедитесь, что секреты настроены правильно. Проверьте, что секреты добавлены в настройках проекта.", {})
        
        logger.info(f"[EMAIL_READ] _read_emails_impl: вызываем EmailStorage.get_email_config_from_secrets с email_account={email_account}")
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        
        if not config:
            # Получаем список всех секретов для отладки
            secret_names = [s.get("name", "unknown") for s in secrets[:20]]
            logger.warning(f"[EMAIL_READ] _read_emails_impl: ВНИМАНИЕ! Конфигурация не найдена. Доступные секреты (первые 20): {secret_names}")
            return ("❌ Не найдена конфигурация почтового ящика. Убедитесь, что секреты настроены правильно. Проверьте наличие секретов с именами, содержащими 'email', 'mail', 'imap', 'smtp'.", {})
        
        logger.info(f"[EMAIL_READ] _read_emails_impl: конфигурация найдена: email={config.get('email')}, imap_host={config.get('imap_host')}, smtp_host={config.get('smtp_host')}")
        
        if not EmailStorage.validate_config(config):
            logger.error(f"[EMAIL_READ] _read_emails_impl: ОШИБКА! Конфигурация не прошла валидацию")
            return ("❌ Неверная конфигурация почтового ящика.", {})
        
        # Подключаемся к IMAP
        logger.info(f"[EMAIL_READ] _read_emails_impl: подключаемся к IMAP: host={config['imap_host']}, email={config['email']}")
        async with IMAPClient(
            host=config["imap_host"],
            email=config["email"],
            password=config["password"]
        ) as client:
            logger.info(f"[EMAIL_READ] _read_emails_impl: успешно подключились к IMAP")
            # Выбираем папку
            if not await client.select_folder(folder):
                return (f"❌ Не удалось выбрать папку {folder}", {})
            
            # Получаем список писем
            # Если unread_only=True, сначала ищем непрочитанные
            # Если непрочитанных нет, автоматически ищем все письма (включая прочитанные)
            if unread_only:
                message_ids = await client.search_unseen()
                logger.info(f"[EMAIL_READ] _read_emails_impl: найдено непрочитанных писем: {len(message_ids) if message_ids else 0}")
                # Если непрочитанных нет, автоматически ищем все письма (включая прочитанные)
                if not message_ids:
                    logger.info(f"[EMAIL_READ] _read_emails_impl: непрочитанных писем нет, ищем все письма (включая прочитанные)")
                    message_ids = await client.search_all(folder)
                    logger.info(f"[EMAIL_READ] _read_emails_impl: найдено всех писем (включая прочитанные): {len(message_ids) if message_ids else 0}")
            else:
                message_ids = await client.search_all(folder)
            
            if not message_ids:
                return (f"📭 Нет писем в папке {folder}", {})
            
            # IMAP возвращает письма от старых к новым, разворачиваем список для получения самых свежих
            message_ids = list(reversed(message_ids))
            logger.info(f"[EMAIL_READ] _read_emails_impl: список писем развернут, всего писем: {len(message_ids)}")
            
            # Ограничиваем количество (максимум 20) - берем первые N самых свежих
            max_limit = min(limit, 20)
            message_ids = message_ids[:max_limit]
            logger.info(f"[EMAIL_READ] _read_emails_impl: ограничено до {max_limit} самых свежих писем")
            
            # Читаем письма и сохраняем их ID для навигации
            emails = []
            email_ids_map = {}  # Словарь для сохранения связи между индексом и message_id
            
            for idx, msg_id in enumerate(message_ids, 1):
                msg = await client.fetch_message(msg_id)
                if msg:
                    parsed = parse_email_message(msg)
                    # Сохраняем message_id в parsed данных для последующего использования
                    msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                    parsed['_message_id'] = msg_id_str
                    parsed['_message_id_bytes'] = msg_id
                    
                    # Вычисляем уникальный хэш для письма
                    subject = parsed.get('subject', 'Без темы')
                    from_email = parsed.get('from', 'Неизвестно')
                    date = parsed.get('date', '')
                    email_hash = calculate_email_hash(
                        message_id=msg_id_str,
                        email_account=email_account or '',
                        folder=folder,
                        subject=subject,
                        from_email=from_email,
                        date=date
                    )
                    parsed['_email_hash'] = email_hash
                    
                    emails.append(parsed)
                    # Сохраняем в map для навигации (индекс начинается с 1)
                    email_ids_map[str(idx)] = {
                        'message_id': msg_id_str,
                        'message_id_bytes': msg_id,
                        'email_hash': email_hash,  # Добавляем хэш для уникальной идентификации
                        'folder': folder,
                        'email_account': email_account,
                        'subject': subject,
                        'from': from_email,
                        'date': date
                    }
            
            if not emails:
                return (f"📭 Не удалось прочитать письма из папки {folder}", {})
            
            # Сортируем письма по дате (от новых к старым) для гарантии правильного порядка
            # Парсим дату из строки и сортируем
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone
            
            def get_email_date(email_data):
                """Извлекает дату из письма для сортировки"""
                date_str = email_data.get('date', '')
                if not date_str:
                    # Возвращаем минимальную дату с UTC timezone для совместимости с offset-aware datetime
                    return datetime.min.replace(tzinfo=timezone.utc)
                try:
                    # Парсим дату из RFC 2822 формата (возвращает offset-aware datetime)
                    parsed_date = parsedate_to_datetime(date_str)
                    # Если дата не имеет timezone, добавляем UTC
                    if parsed_date.tzinfo is None:
                        return parsed_date.replace(tzinfo=timezone.utc)
                    return parsed_date
                except Exception:
                    # Если не удалось распарсить, возвращаем минимальную дату с UTC timezone
                    return datetime.min.replace(tzinfo=timezone.utc)
            
            # Сортируем от новых к старым (reverse=True)
            emails.sort(key=get_email_date, reverse=True)
            logger.info(f"[EMAIL_READ] _read_emails_impl: письма отсортированы по дате (от новых к старым)")
            
            # Обновляем email_ids_map после сортировки
            # Создаем двойную структуру: по номеру (для навигации) и по хэшу (для постоянной идентификации)
            email_ids_map = {}  # По номеру (для обратной совместимости)
            email_hash_map = {}  # По хэшу (основной идентификатор)
            
            for idx, email_data in enumerate(emails, 1):
                msg_id = email_data.get('_message_id_bytes')
                email_hash = email_data.get('_email_hash', '')
                
                if msg_id:
                    email_info = {
                        'message_id': email_data.get('_message_id', ''),
                        'message_id_bytes': msg_id,
                        'email_hash': email_hash,  # Сохраняем хэш
                        'folder': folder,
                        'email_account': email_account,
                        'subject': email_data.get('subject', 'Без темы'),
                        'from': email_data.get('from', 'Неизвестно'),
                        'date': email_data.get('date', ''),
                        'position': idx  # Позиция в текущем списке (может меняться)
                    }
                    
                    # Сохраняем по номеру (для обратной совместимости)
                    email_ids_map[str(idx)] = email_info
                    
                    # Сохраняем по хэшу (основной идентификатор - постоянный)
                    if email_hash:
                        email_hash_map[email_hash] = email_info
            
            # Сохраняем загруженные письма в state для навигации
            if state and isinstance(state, dict):
                state['loaded_emails'] = email_ids_map  # По номеру (для обратной совместимости)
                state['loaded_emails_by_hash'] = email_hash_map  # По хэшу (основной идентификатор)
                state['current_email_index'] = None  # Сбрасываем текущий индекс
                logger.info(f"[EMAIL_READ] _read_emails_impl: сохранено {len(email_ids_map)} писем в state (по номеру) и {len(email_hash_map)} по хэшу")
            
            # Формируем результат
            result = f"📧 **Найдено писем: {len(emails)}**\n\n"
            
            for i, email_data in enumerate(emails, 1):
                email_hash = email_data.get('_email_hash', '')
                result += f"**{i}. {email_data['subject']}**\n"
                # Показываем хэш как основной постоянный идентификатор
                if email_hash:
                    result += f"🆔 ID: {email_hash} (постоянный идентификатор)\n"
                result += f"От: {email_data['from']}\n"
                result += f"Дата: {email_data['date']}\n"
                
                if email_data['has_attachments']:
                    result += f"Вложений: {email_data['attachment_count']}\n"
                
                # Показываем начало текста
                text_preview = email_data['text'][:200] if email_data['text'] else ""
                if text_preview:
                    result += f"Текст: {text_preview}...\n"
                
                result += "\n"
            
            # Добавляем подсказку о навигации
            result += "\n💡 **Навигация и операции:**\n"
            result += "• Для просмотра: \"показать письмо 1\" или \"показать письмо по ID abc123...\"\n"
            result += "• Для удаления: \"удалить письма 1, 2, 3\" или \"удалить письма по ID abc123..., def456...\"\n"
            result += "• Для переноса в spam: \"перенести в spam письма 1, 2, 3\" или \"перенести в spam по ID abc123...\"\n"
            result += "• **Важно:** ID (хэш) - постоянный идентификатор письма, номер - позиция в текущем списке\n"
            
            return (result, email_ids_map)
            
    except Exception as e:
        logger.error(f"Ошибка чтения писем в _read_emails_impl: {e}", exc_info=True)
        return (f"❌ Ошибка чтения писем: {str(e)}", {})


@tool
async def read_emails(
    email_account: Optional[str] = None,
    folder: str = "inbox",
    unread_only: bool = True,
    limit: int = 20,
    state: Optional[Dict] = None
) -> str:
    """
    Чтение писем из почтового ящика
    
    Args:
        email_account: Email адрес ящика (если не указан, используется первый доступный)
        folder: Папка для чтения (по умолчанию "inbox")
        unread_only: Читать только непрочитанные письма (по умолчанию True)
        limit: Максимальное количество писем для чтения (по умолчанию 20, максимум 20)
        state: Состояние агента (для доступа к секретам)
    
    Returns:
        Строка с информацией о письмах
    """
    # Используем внутреннюю реализацию
    result, _ = await _read_emails_impl(
        email_account=email_account,
        folder=folder,
        unread_only=unread_only,
        limit=limit,
        state=state
    )
    return result


@tool
async def get_email_content(
    email_account: Optional[str] = None,
    message_id: Optional[str] = None,
    folder: str = "inbox",
    state: Optional[Dict] = None
) -> str:
    """
    Получение полного содержимого письма
    
    Args:
        email_account: Email адрес ящика
        message_id: ID письма (если не указан, берется первое непрочитанное)
        folder: Папка для поиска
        state: Состояние агента
    
    Returns:
        Полное содержимое письма
    """
    try:
        logger.info(f"[EMAIL_READ] get_email_content вызван: email_account={email_account}, message_id={message_id}, folder={folder}")
        secrets = state.get("secrets", []) if state and isinstance(state, dict) else []
        secrets_count = len(secrets) if secrets else 0
        logger.info(f"[EMAIL_READ] get_email_content: получено секретов: {secrets_count}")
        if not secrets:
            logger.warning(f"[EMAIL_READ] get_email_content: ВНИМАНИЕ! Секреты не найдены в state")
            return "❌ Не найдена конфигурация почтового ящика. Убедитесь, что секреты настроены правильно."
        
        logger.info(f"[EMAIL_READ] get_email_content: вызываем EmailStorage.get_email_config_from_secrets с email_account={email_account}")
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        
        if not config:
            logger.warning(f"[EMAIL_READ] get_email_content: ВНИМАНИЕ! Конфигурация не найдена")
            return "❌ Не найдена конфигурация почтового ящика."
        
        logger.info(f"[EMAIL_READ] get_email_content: конфигурация найдена: email={config.get('email')}, imap_host={config.get('imap_host')}")
        logger.info(f"[EMAIL_READ] get_email_content: подключаемся к IMAP: host={config['imap_host']}, email={config['email']}")
        async with IMAPClient(
            host=config["imap_host"],
            email=config["email"],
            password=config["password"]
        ) as client:
            logger.info(f"[EMAIL_READ] get_email_content: успешно подключились к IMAP")
            await client.select_folder(folder)
            
            # Если ID не указан, берем самое свежее письмо
            # Сначала ищем непрочитанное, если нет - берем последнее из всех (включая прочитанные)
            if not message_id:
                message_ids = await client.search_unseen()
                logger.info(f"[EMAIL_READ] get_email_content: найдено непрочитанных писем: {len(message_ids) if message_ids else 0}")
                # Если непрочитанных нет, ищем все письма (включая прочитанные)
                if not message_ids:
                    logger.info(f"[EMAIL_READ] get_email_content: непрочитанных писем нет, ищем все письма (включая прочитанные)")
                    message_ids = await client.search_all(folder)
                    logger.info(f"[EMAIL_READ] get_email_content: найдено всех писем (включая прочитанные): {len(message_ids) if message_ids else 0}")
                    if not message_ids:
                        return "❌ Нет писем в папке"
                # Разворачиваем список, чтобы взять самое свежее письмо (последнее в списке IMAP)
                message_ids = list(reversed(message_ids))
                logger.info(f"[EMAIL_READ] get_email_content: список писем развернут, берем самое свежее")
                message_id_bytes = message_ids[0]
            else:
                message_id_bytes = message_id.encode() if isinstance(message_id, str) else message_id
            
            msg = await client.fetch_message(message_id_bytes)
            if not msg:
                return "❌ Не удалось получить письмо"
            
            parsed = parse_email_message(msg)
            
            result = f"**Тема:** {parsed['subject']}\n"
            result += f"**От:** {parsed['from']}\n"
            result += f"**Кому:** {parsed['to']}\n"
            result += f"**Дата:** {parsed['date']}\n\n"
            
            if parsed['text']:
                result += f"**Текст:**\n{parsed['text']}\n\n"
            
            if parsed['html']:
                result += f"**HTML:**\n{parsed['html'][:500]}...\n\n"
            
            if parsed['has_attachments']:
                result += f"**Вложения ({parsed['attachment_count']}):**\n"
                for att in parsed['attachments']:
                    result += f"- {att['filename']} ({att['content_type']}, {att['size']} байт)\n"
            
            return result
            
    except Exception as e:
        logger.error(f"Ошибка получения содержимого письма: {e}")
        return f"❌ Ошибка: {str(e)}"


@tool
async def show_email_full(
    email_number: Optional[int] = None,
    email_account: Optional[str] = None,
    folder: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Показать полный текст письма по номеру из загруженного списка
    
    Args:
        email_number: Номер письма из списка (начинается с 1)
        email_account: Email адрес ящика
        folder: Папка (если не указана, берется из сохраненных данных)
        state: Состояние агента (содержит loaded_emails)
    
    Returns:
        Полный текст письма
    """
    try:
        logger.info(f"[EMAIL_READ] show_email_full вызван: email_number={email_number}, email_account={email_account}, folder={folder}")
        
        if not state or not isinstance(state, dict):
            return "❌ Ошибка: состояние не найдено"
        
        # Получаем загруженные письма из state
        loaded_emails = state.get("loaded_emails", {})
        
        # Если загруженных писем нет, автоматически загружаем их
        if not loaded_emails:
            logger.info(f"[EMAIL_READ] show_email_full: loaded_emails пуст, автоматически загружаем письма")
            # Автоматически загружаем письма
            try:
                # Используем folder из параметра или inbox по умолчанию
                search_folder = folder or "inbox"
                logger.info(f"[EMAIL_READ] show_email_full: автоматическая загрузка писем из папки {search_folder}")
                
                # Вызываем _read_emails_impl напрямую для загрузки писем (гарантирует сохранение в state)
                read_result, email_ids_map = await _read_emails_impl(
                    email_account=email_account,
                    folder=search_folder,
                    unread_only=False,  # Загружаем все письма
                    limit=20,
                    state=state
                )
                
                # Проверяем, что письма загружены
                loaded_emails = state.get("loaded_emails", {})
                if not loaded_emails:
                    logger.warning(f"[EMAIL_READ] show_email_full: письма не загружены в state после вызова _read_emails_impl")
                    return "❌ Не удалось автоматически загрузить письма. Попробуйте сначала выполнить команду \"прочитать письма\""
                
                logger.info(f"[EMAIL_READ] show_email_full: автоматически загружено {len(loaded_emails)} писем")
            except Exception as e:
                logger.error(f"[EMAIL_READ] show_email_full: ошибка при автоматической загрузке писем: {e}", exc_info=True)
                return f"❌ Ошибка при автоматической загрузке писем: {str(e)}. Попробуйте сначала выполнить команду \"прочитать письма\""
        
        # Если номер не указан, берем текущий индекс или первое письмо
        if email_number is None:
            current_index = state.get("current_email_index")
            if current_index is not None:
                email_number = current_index
            else:
                # Берем первое письмо
                email_number = 1
        
        email_key = str(email_number)
        if email_key not in loaded_emails:
            return f"❌ Письмо с номером {email_number} не найдено. Доступны номера: {', '.join(sorted(loaded_emails.keys(), key=int))}"
        
        email_info = loaded_emails[email_key]
        message_id_bytes = email_info.get('message_id_bytes')
        folder = folder or email_info.get('folder', 'inbox')
        email_account = email_account or email_info.get('email_account')
        
        if not message_id_bytes:
            return f"❌ Ошибка: не найден ID письма {email_number}"
        
        # Получаем секреты
        secrets = state.get("secrets", [])
        if not secrets:
            return "❌ Не найдена конфигурация почтового ящика."
        
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        if not config:
            return "❌ Не найдена конфигурация почтового ящика."
        
        # Подключаемся к IMAP и получаем письмо
        async with IMAPClient(
            host=config["imap_host"],
            email=config["email"],
            password=config["password"]
        ) as client:
            await client.select_folder(folder)
            
            # Преобразуем message_id в bytes если нужно
            if isinstance(message_id_bytes, str):
                try:
                    message_id_bytes = message_id_bytes.encode()
                except:
                    pass
            
            msg = await client.fetch_message(message_id_bytes)
            if not msg:
                return f"❌ Не удалось получить письмо {email_number}"
            
            parsed = parse_email_message(msg)
            
            # Обновляем текущий индекс в state
            state["current_email_index"] = email_number
            
            # Формируем результат
            result = f"📧 **Письмо {email_number} из {len(loaded_emails)}**\n\n"
            result += f"**Тема:** {parsed['subject']}\n"
            result += f"**От:** {parsed['from']}\n"
            result += f"**Кому:** {parsed['to']}\n"
            result += f"**Дата:** {parsed['date']}\n\n"
            
            # Показываем текстовую версию, если она есть
            if parsed['text']:
                result += f"**Текст:**\n{parsed['text']}\n\n"
            
            # Показываем полный HTML, если он есть
            if parsed['html']:
                # Если есть текст, показываем HTML как дополнительную информацию
                # Если текста нет, показываем HTML как основной контент
                if parsed['text']:
                    result += f"**HTML (полный текст):**\n{parsed['html']}\n\n"
                else:
                    # Если текста нет, пытаемся извлечь текст из HTML
                    try:
                        # Простое извлечение текста из HTML (удаляем теги)
                        html_text = parsed['html']
                        # Удаляем скрипты и стили
                        html_text = re.sub(r'<script[^>]*>.*?</script>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
                        html_text = re.sub(r'<style[^>]*>.*?</style>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
                        # Заменяем <br> и <p> на переносы строк
                        html_text = re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)
                        html_text = re.sub(r'</p>', '\n\n', html_text, flags=re.IGNORECASE)
                        html_text = re.sub(r'<p[^>]*>', '', html_text, flags=re.IGNORECASE)
                        # Удаляем все остальные теги
                        html_text = re.sub(r'<[^>]+>', '', html_text)
                        # Декодируем HTML-сущности
                        html_text = html_module.unescape(html_text)
                        # Очищаем лишние пробелы
                        html_text = re.sub(r'\n\s*\n\s*\n+', '\n\n', html_text)
                        html_text = html_text.strip()
                        
                        if html_text:
                            result += f"**Текст (извлечен из HTML):**\n{html_text}\n\n"
                        result += f"**HTML (полный текст):**\n{parsed['html']}\n\n"
                    except Exception as e:
                        # Если не удалось извлечь текст, просто показываем HTML
                        logger.warning(f"[EMAIL_READ] show_email_full: не удалось извлечь текст из HTML: {e}")
                        result += f"**HTML (полный текст):**\n{parsed['html']}\n\n"
            
            if parsed['has_attachments']:
                result += f"**Вложения ({parsed['attachment_count']}):**\n"
                for att in parsed['attachments']:
                    result += f"- {att['filename']} ({att['content_type']}, {att['size']} байт)\n"
                result += "\n"
            
            # Добавляем навигацию
            result += "\n💡 **Навигация:**\n"
            if email_number > 1:
                result += f"• Предыдущее письмо: \"показать письмо {email_number - 1}\" или \"показать предыдущее\"\n"
            if email_number < len(loaded_emails):
                result += f"• Следующее письмо: \"показать письмо {email_number + 1}\" или \"показать следующее\"\n"
            
            return result
            
    except Exception as e:
        logger.error(f"Ошибка показа полного текста письма: {e}", exc_info=True)
        return f"❌ Ошибка: {str(e)}"


@tool
async def show_next_email(
    email_account: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Показать следующее письмо из загруженного списка
    
    Args:
        email_account: Email адрес ящика
        state: Состояние агента
    
    Returns:
        Полный текст следующего письма
    """
    try:
        if not state or not isinstance(state, dict):
            return "❌ Ошибка: состояние не найдено"
        
        loaded_emails = state.get("loaded_emails", {})
        
        # Если загруженных писем нет, автоматически загружаем их
        if not loaded_emails:
            logger.info(f"[EMAIL_READ] show_next_email: loaded_emails пуст, автоматически загружаем письма")
            try:
                # Вызываем _read_emails_impl напрямую для загрузки писем (гарантирует сохранение в state)
                await _read_emails_impl(
                    email_account=email_account,
                    folder="inbox",
                    unread_only=False,
                    limit=20,
                    state=state
                )
                loaded_emails = state.get("loaded_emails", {})
                if not loaded_emails:
                    return "❌ Не удалось автоматически загрузить письма. Попробуйте сначала выполнить команду \"прочитать письма\""
            except Exception as e:
                logger.error(f"[EMAIL_READ] show_next_email: ошибка при автоматической загрузке: {e}", exc_info=True)
                return f"❌ Ошибка при автоматической загрузке писем: {str(e)}"
        
        current_index = state.get("current_email_index")
        if current_index is None:
            # Если текущий индекс не установлен, берем первое письмо
            next_index = 1
        else:
            next_index = current_index + 1
        
        # Проверяем, что следующее письмо существует
        if str(next_index) not in loaded_emails:
            return f"❌ Это последнее письмо. Всего писем: {len(loaded_emails)}"
        
        # Вызываем show_email_full с следующим индексом
        return await show_email_full.ainvoke({
            "email_number": next_index,
            "email_account": email_account,
            "state": state
        })
        
    except Exception as e:
        logger.error(f"Ошибка показа следующего письма: {e}", exc_info=True)
        return f"❌ Ошибка: {str(e)}"


@tool
async def show_previous_email(
    email_account: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Показать предыдущее письмо из загруженного списка
    
    Args:
        email_account: Email адрес ящика
        state: Состояние агента
    
    Returns:
        Полный текст предыдущего письма
    """
    try:
        if not state or not isinstance(state, dict):
            return "❌ Ошибка: состояние не найдено"
        
        loaded_emails = state.get("loaded_emails", {})
        
        # Если загруженных писем нет, автоматически загружаем их
        if not loaded_emails:
            logger.info(f"[EMAIL_READ] show_previous_email: loaded_emails пуст, автоматически загружаем письма")
            try:
                # Вызываем _read_emails_impl напрямую для загрузки писем (гарантирует сохранение в state)
                await _read_emails_impl(
                    email_account=email_account,
                    folder="inbox",
                    unread_only=False,
                    limit=20,
                    state=state
                )
                loaded_emails = state.get("loaded_emails", {})
                if not loaded_emails:
                    return "❌ Не удалось автоматически загрузить письма. Попробуйте сначала выполнить команду \"прочитать письма\""
            except Exception as e:
                logger.error(f"[EMAIL_READ] show_previous_email: ошибка при автоматической загрузке: {e}", exc_info=True)
                return f"❌ Ошибка при автоматической загрузке писем: {str(e)}"
        
        current_index = state.get("current_email_index")
        if current_index is None:
            # Если текущий индекс не установлен, берем последнее письмо
            prev_index = len(loaded_emails)
        else:
            prev_index = current_index - 1
        
        # Проверяем, что предыдущее письмо существует
        if prev_index < 1:
            return f"❌ Это первое письмо. Всего писем: {len(loaded_emails)}"
        
        if str(prev_index) not in loaded_emails:
            return f"❌ Письмо с номером {prev_index} не найдено"
        
        # Вызываем show_email_full с предыдущим индексом
        return await show_email_full.ainvoke({
            "email_number": prev_index,
            "email_account": email_account,
            "state": state
        })
        
    except Exception as e:
        logger.error(f"Ошибка показа предыдущего письма: {e}", exc_info=True)
        return f"❌ Ошибка: {str(e)}"


@tool
async def delete_email(
    email_number: Optional[int] = None,
    email_account: Optional[str] = None,
    folder: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Удалить письмо в корзину по номеру из загруженного списка
    
    Args:
        email_number: Номер письма из списка (начинается с 1)
        email_account: Email адрес ящика
        folder: Папка (если не указана, берется из сохраненных данных)
        state: Состояние агента (содержит loaded_emails)
    
    Returns:
        Результат удаления
    """
    try:
        logger.info(f"[EMAIL_READ] delete_email вызван: email_number={email_number}, email_account={email_account}, folder={folder}")
        
        if not state or not isinstance(state, dict):
            return "❌ Ошибка: состояние не найдено"
        
        # Получаем загруженные письма из state
        loaded_emails = state.get("loaded_emails", {})
        
        # Если загруженных писем нет, автоматически загружаем их
        if not loaded_emails:
            logger.info(f"[EMAIL_READ] delete_email: loaded_emails пуст, автоматически загружаем письма")
            try:
                # Вызываем _read_emails_impl напрямую для загрузки писем (гарантирует сохранение в state)
                await _read_emails_impl(
                    email_account=email_account,
                    folder=folder or "inbox",
                    unread_only=False,
                    limit=20,
                    state=state
                )
                loaded_emails = state.get("loaded_emails", {})
                if not loaded_emails:
                    return "❌ Не удалось автоматически загрузить письма. Попробуйте сначала выполнить команду \"прочитать письма\""
            except Exception as e:
                logger.error(f"[EMAIL_READ] delete_email: ошибка при автоматической загрузке: {e}", exc_info=True)
                return f"❌ Ошибка при автоматической загрузке писем: {str(e)}"
        
        # Если номер не указан, берем текущий индекс
        if email_number is None:
            current_index = state.get("current_email_index")
            if current_index is not None:
                email_number = current_index
            else:
                return "❌ Укажите номер письма для удаления. Например: \"удалить письмо 1\""
        
        email_key = str(email_number)
        if email_key not in loaded_emails:
            return f"❌ Письмо с номером {email_number} не найдено. Доступны номера: {', '.join(sorted(loaded_emails.keys(), key=int))}"
        
        email_info = loaded_emails[email_key]
        message_id_bytes = email_info.get('message_id_bytes')
        folder = folder or email_info.get('folder', 'inbox')
        email_account = email_account or email_info.get('email_account')
        subject = email_info.get('subject', 'Без темы')
        
        if not message_id_bytes:
            return f"❌ Ошибка: не найден ID письма {email_number}"
        
        # Получаем секреты
        secrets = state.get("secrets", [])
        if not secrets:
            return "❌ Не найдена конфигурация почтового ящика."
        
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        if not config:
            return "❌ Не найдена конфигурация почтового ящика."
        
        # Подключаемся к IMAP и удаляем письмо
        async with IMAPClient(
            host=config["imap_host"],
            email=config["email"],
            password=config["password"]
        ) as client:
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
                # Удаляем письмо из loaded_emails в state
                if email_key in loaded_emails:
                    del loaded_emails[email_key]
                
                # Обновляем индексы в loaded_emails (сдвигаем номера)
                # Создаем новый словарь с обновленными индексами
                new_loaded_emails = {}
                current_idx = 1
                for key in sorted(loaded_emails.keys(), key=int):
                    if int(key) < email_number:
                        new_loaded_emails[str(current_idx)] = loaded_emails[key]
                        current_idx += 1
                    elif int(key) > email_number:
                        new_loaded_emails[str(current_idx)] = loaded_emails[key]
                        current_idx += 1
                
                state["loaded_emails"] = new_loaded_emails
                
                # Обновляем текущий индекс если нужно
                current_email_index = state.get("current_email_index")
                if current_email_index == email_number:
                    # Если удалили текущее письмо, переходим на предыдущее или следующее
                    if email_number > 1:
                        state["current_email_index"] = email_number - 1
                    elif new_loaded_emails:
                        state["current_email_index"] = 1
                    else:
                        state["current_email_index"] = None
                elif current_email_index and current_email_index > email_number:
                    # Сдвигаем текущий индекс, если удалили письмо с меньшим номером
                    state["current_email_index"] = current_email_index - 1
                
                result = f"✅ Письмо {email_number} \"{subject}\" успешно удалено в корзину\n\n"
                result += f"Осталось писем в списке: {len(new_loaded_emails)}\n"
                
                if new_loaded_emails:
                    result += "\n💡 Вы можете продолжить просмотр оставшихся писем."
                
                return result
            else:
                return f"❌ Не удалось удалить письмо {email_number} \"{subject}\""
            
    except Exception as e:
        logger.error(f"Ошибка удаления письма: {e}", exc_info=True)
        return f"❌ Ошибка удаления: {str(e)}"


@tool
async def search_emails(
    keywords: Optional[str] = None,
    from_email: Optional[str] = None,
    email_account: Optional[str] = None,
    folder: str = "inbox",
    search_in: str = "TEXT",
    limit: int = 20,
    state: Optional[Dict] = None
) -> str:
    """
    Поиск писем по ключевым словам и/или от конкретного отправителя
    
    Args:
        keywords: Ключевые слова для поиска (в теме или теле письма)
        from_email: Email адрес отправителя для поиска
        email_account: Email адрес ящика
        folder: Папка для поиска (по умолчанию "inbox")
        search_in: Где искать ключевые слова: "SUBJECT" (только тема), "BODY" (только тело), "TEXT" (тема и тело)
        limit: Максимальное количество писем (по умолчанию 20, максимум 20)
        state: Состояние агента (для доступа к секретам)
    
    Returns:
        Строка с информацией о найденных письмах
    """
    try:
        logger.info(f"[EMAIL_READ] search_emails вызван: keywords={keywords}, from_email={from_email}, folder={folder}, search_in={search_in}, limit={limit}")
        
        if not keywords and not from_email:
            return "❌ Укажите ключевые слова для поиска или email адрес отправителя. Например: \"найти письма с ключевым словом 'важно'\" или \"найти письма от example@mail.com\""
        
        # Получаем конфигурацию из секретов
        secrets = state.get("secrets", []) if state and isinstance(state, dict) else []
        if not secrets:
            return "❌ Не найдена конфигурация почтового ящика. Убедитесь, что секреты настроены правильно."
        
        config = EmailStorage.get_email_config_from_secrets(secrets, email_account)
        if not config:
            return "❌ Не найдена конфигурация почтового ящика."
        
        if not EmailStorage.validate_config(config):
            return "❌ Неверная конфигурация почтового ящика."
        
        # Подключаемся к IMAP
        async with IMAPClient(
            host=config["imap_host"],
            email=config["email"],
            password=config["password"]
        ) as client:
            # Выбираем папку
            if not await client.select_folder(folder):
                return f"❌ Не удалось выбрать папку {folder}"
            
            # Выполняем поиск
            if keywords and from_email:
                # Комбинированный поиск
                message_ids = await client.search_combined(
                    from_email=from_email,
                    keywords=keywords,
                    folder=folder,
                    search_in=search_in
                )
            elif from_email:
                # Поиск только по отправителю
                message_ids = await client.search_by_from(from_email, folder)
            elif keywords:
                # Поиск только по ключевым словам
                message_ids = await client.search_by_keywords(keywords, folder, search_in)
            else:
                return "❌ Укажите ключевые слова или email адрес отправителя"
            
            if not message_ids:
                search_info = []
                if from_email:
                    search_info.append(f"от {from_email}")
                if keywords:
                    search_info.append(f"с ключевым словом '{keywords}'")
                return f"📭 Не найдено писем в папке {folder} {' и '.join(search_info)}"
            
            logger.info(f"[EMAIL_READ] search_emails: найдено писем: {len(message_ids)}")
            
            # IMAP возвращает письма от старых к новым, разворачиваем список
            message_ids = list(reversed(message_ids))
            
            # Ограничиваем количество (максимум 20)
            max_limit = min(limit, 20)
            message_ids = message_ids[:max_limit]
            logger.info(f"[EMAIL_READ] search_emails: ограничено до {max_limit} самых свежих писем")
            
            # Читаем письма
            emails = []
            email_ids_map = {}
            
            for idx, msg_id in enumerate(message_ids, 1):
                msg = await client.fetch_message(msg_id)
                if msg:
                    parsed = parse_email_message(msg)
                    msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                    parsed['_message_id'] = msg_id_str
                    parsed['_message_id_bytes'] = msg_id
                    
                    # Вычисляем уникальный хэш для письма
                    subject = parsed.get('subject', 'Без темы')
                    from_email = parsed.get('from', 'Неизвестно')
                    date = parsed.get('date', '')
                    email_hash = calculate_email_hash(
                        message_id=msg_id_str,
                        email_account=email_account or '',
                        folder=folder,
                        subject=subject,
                        from_email=from_email,
                        date=date
                    )
                    parsed['_email_hash'] = email_hash
                    
                    emails.append(parsed)
                    
                    # Сохраняем в map для навигации
                    email_ids_map[str(idx)] = {
                        'message_id': msg_id_str,
                        'message_id_bytes': msg_id,
                        'email_hash': email_hash,  # Добавляем хэш
                        'folder': folder,
                        'email_account': email_account,
                        'subject': subject,
                        'from': from_email,
                        'date': date
                    }
            
            if not emails:
                return f"📭 Не удалось прочитать найденные письма из папки {folder}"
            
            # Сортируем письма по дате (от новых к старым)
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone
            
            def get_email_date(email_data):
                """Извлекает дату из письма для сортировки"""
                date_str = email_data.get('date', '')
                if not date_str:
                    # Возвращаем минимальную дату с UTC timezone для совместимости с offset-aware datetime
                    return datetime.min.replace(tzinfo=timezone.utc)
                try:
                    # Парсим дату из RFC 2822 формата (возвращает offset-aware datetime)
                    parsed_date = parsedate_to_datetime(date_str)
                    # Если дата не имеет timezone, добавляем UTC
                    if parsed_date.tzinfo is None:
                        return parsed_date.replace(tzinfo=timezone.utc)
                    return parsed_date
                except Exception:
                    # Если не удалось распарсить, возвращаем минимальную дату с UTC timezone
                    return datetime.min.replace(tzinfo=timezone.utc)
            
            emails.sort(key=get_email_date, reverse=True)
            
            # Обновляем email_ids_map после сортировки
            # Создаем двойную структуру: по номеру и по хэшу
            email_ids_map = {}  # По номеру
            email_hash_map = {}  # По хэшу (основной идентификатор)
            
            for idx, email_data in enumerate(emails, 1):
                msg_id = email_data.get('_message_id_bytes')
                email_hash = email_data.get('_email_hash', '')
                
                if msg_id:
                    email_info = {
                        'message_id': email_data.get('_message_id', ''),
                        'message_id_bytes': msg_id,
                        'email_hash': email_hash,
                        'folder': folder,
                        'email_account': email_account,
                        'subject': email_data.get('subject', 'Без темы'),
                        'from': email_data.get('from', 'Неизвестно'),
                        'date': email_data.get('date', ''),
                        'position': idx
                    }
                    
                    email_ids_map[str(idx)] = email_info
                    
                    # Сохраняем по хэшу (основной идентификатор)
                    if email_hash:
                        email_hash_map[email_hash] = email_info
            
            # Сохраняем найденные письма в state для навигации
            if state and isinstance(state, dict):
                state['loaded_emails'] = email_ids_map  # По номеру
                state['loaded_emails_by_hash'] = email_hash_map  # По хэшу
                state['current_email_index'] = None
                logger.info(f"[EMAIL_READ] search_emails: сохранено {len(email_ids_map)} писем (по номеру) и {len(email_hash_map)} по хэшу")
            
            # Формируем результат
            search_info = []
            if from_email:
                search_info.append(f"от {from_email}")
            if keywords:
                search_info.append(f"с ключевым словом '{keywords}'")
            
            result = f"🔍 **Найдено писем: {len(emails)}** ({' и '.join(search_info)})\n\n"
            
            for i, email_data in enumerate(emails, 1):
                email_hash = email_data.get('_email_hash', '')
                result += f"**{i}. {email_data['subject']}**\n"
                # Показываем хэш как основной постоянный идентификатор
                if email_hash:
                    result += f"🆔 ID: {email_hash} (постоянный идентификатор)\n"
                result += f"От: {email_data['from']}\n"
                result += f"Дата: {email_data['date']}\n"
                
                if email_data['has_attachments']:
                    result += f"Вложений: {email_data['attachment_count']}\n"
                
                # Показываем начало текста
                text_preview = email_data['text'][:200] if email_data['text'] else ""
                if text_preview:
                    result += f"Текст: {text_preview}...\n"
                
                result += "\n"
            
            # Добавляем подсказку о навигации
            result += "\n💡 **Навигация и операции:**\n"
            result += "• Для просмотра: \"показать письмо 1\" или \"показать письмо по ID abc123...\"\n"
            result += "• Для удаления: \"удалить письма 1, 2, 3\" или \"удалить письма по ID abc123..., def456...\"\n"
            result += "• Для переноса в spam: \"перенести в spam письма 1, 2, 3\" или \"перенести в spam по ID abc123...\"\n"
            result += "• **Важно:** ID (хэш) - постоянный идентификатор письма, номер - позиция в текущем списке\n"
            
            return result
            
    except Exception as e:
        logger.error(f"Ошибка поиска писем: {e}", exc_info=True)
        return f"❌ Ошибка поиска писем: {str(e)}"

