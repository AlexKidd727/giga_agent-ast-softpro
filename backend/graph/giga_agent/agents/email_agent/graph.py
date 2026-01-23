"""
Граф Email Agent
"""

import logging
from typing import Annotated, Optional
import re
from datetime import datetime, timedelta, date

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langgraph.constants import START, END
from langgraph.graph import StateGraph

from giga_agent.agents.email_agent.config import EmailAgentState
from giga_agent.agents.email_agent.nodes.read import (
    read_emails, 
    get_email_content,
    show_email_full,
    show_next_email,
    show_previous_email,
    delete_email,
    search_emails
)
from giga_agent.agents.email_agent.nodes.filter import filter_emails, check_email_filters
from giga_agent.agents.email_agent.nodes.send import send_email, reply_to_email
from giga_agent.agents.email_agent.nodes.manage import (
    list_email_accounts,
    get_email_folders,
    test_email_connection,
    bulk_delete_emails,
    bulk_move_to_spam
)
from giga_agent.utils.request_normalizer import normalize_request

logger = logging.getLogger(__name__)


# Внутренняя функция без декоратора @tool для использования в графе
async def _email_agent_impl(
    user_request: str,
    email_account: Optional[str] = None,
    user_id: str = "default_user",
    state: Optional[dict] = None
):
    """
    Агент для работы с почтовыми ящиками
    
    Обрабатывает запросы пользователя связанные с почтой:
    
    ЧТЕНИЕ ПИСЕМ:
    - Прочитать письма (прочитать письма, показать непрочитанные)
    - Поиск писем (найти письма с ключевым словом, найти письма от отправителя)
    - Просмотр письма (показать письмо 1, показать следующее/предыдущее)
    - Каждое письмо имеет уникальный ID (хэш) - ПОСТОЯННЫЙ идентификатор и номер - позицию в списке
    
    МАССОВЫЕ ОПЕРАЦИИ С ПИСЬМАМИ (ВАЖНО!):
    - Массовое удаление: "удалить письма 1, 2, 3" или "удалить письма по ID 242e709c24272aa7, bf52e7433a3200f9"
    - Массовый перенос в spam: "перенести в spam письма 1, 2, 3" или "перенести в spam по ID 242e709c24272aa7, bf52e7433a3200f9"
    - Можно указывать номера писем (1, 2, 3) или ID (хэш) писем из списка загруженных писем
    - Примеры: 
      * "удалить письма 1, 2, 3, 5" - удаление по номерам из текущего списка
      * "удалить письма по ID 242e709c24272aa7, bf52e7433a3200f9" - удаление по постоянным ID (РЕКОМЕНДУЕТСЯ)
      * "перенести в spam письма 1-5" - перенос диапазона по номерам
      * "перенести в spam по ID 242e709c24272aa7" - перенос по постоянному ID
    
    ОТПРАВКА ПИСЕМ:
    - Отправка писем (отправить письмо, ответить)
    
    УПРАВЛЕНИЕ ЯЩИКАМИ:
    - Список ящиков, папки, настройки
    
    ВАЖНО: 
    - При загрузке писем каждое письмо получает уникальный ID (хэш) - это ПОСТОЯННЫЙ идентификатор
    - ID не меняется при изменении списка писем, в отличие от номеров (1, 2, 3...)
    - Для массовых операций РЕКОМЕНДУЕТСЯ использовать ID вместо номеров для надежности
    - ID отображается в списке писем как "🆔 ID: {hash} (постоянный идентификатор)"
    - НЕ удаляйте письма по одному, если нужно удалить несколько - используйте массовое удаление!
    
    Args:
        user_request: Запрос пользователя (например, "прочитать письма", "удалить письма по ID 242e709c24272aa7, bf52e7433a3200f9", "отправить письмо")
        email_account: Email адрес ящика (если не указан, используется первый доступный)
        user_id: Идентификатор пользователя
    """
    
    logger.info(f"[EMAIL_AGENT] _email_agent_impl вызван: user_request='{user_request}', email_account={email_account}, user_id={user_id}")
    logger.info(f"[EMAIL_AGENT] _email_agent_impl: state type={type(state)}, state is None={state is None}")
    
    # Инициализируем state если он None
    if state is None:
        state = {}
    
    # Инициализируем loaded_emails и current_email_index если их нет
    if not isinstance(state, dict):
        state = {}
    
    if "loaded_emails" not in state:
        state["loaded_emails"] = {}
    if "current_email_index" not in state:
        state["current_email_index"] = None
    
    if state:
        logger.info(f"[EMAIL_AGENT] _email_agent_impl: state keys={list(state.keys()) if isinstance(state, dict) else 'N/A'}")
        secrets = state.get("secrets", []) if isinstance(state, dict) else []
        secrets_count = len(secrets) if isinstance(secrets, list) else 0
        logger.info(f"[EMAIL_AGENT] _email_agent_impl: получено секретов из state: {secrets_count}")
        if secrets_count > 0:
            secret_names = [s.get("name", "unknown") for s in secrets[:10]]
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: имена секретов (первые 10): {secret_names}")
            email_related = [s.get("name", "") for s in secrets if any(kw in s.get("name", "").lower() for kw in ["email", "mail", "imap", "smtp"])]
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: email-связанных секретов: {len(email_related)}")
            if email_related:
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: email-связанные секреты (первые 10): {email_related[:10]}")
        else:
            logger.warning(f"[EMAIL_AGENT] _email_agent_impl: ВНИМАНИЕ! Секреты не найдены в state или список пуст")
    else:
        logger.warning(f"[EMAIL_AGENT] _email_agent_impl: ВНИМАНИЕ! state равен None")
    
    try:
        user_input = user_request.lower()
        
        # УМНОЕ КЭШИРОВАНИЕ: Проверяем, есть ли кэшированный инструмент для этого запроса
        from giga_agent.utils.query_pattern_cache import get_cache_service
        cache_service = get_cache_service()
        cached_tool = None
        cache_metrics = None
        try:
            cached_tool, cache_metrics = await cache_service.get_cached_tool(user_request, user_id)
        except Exception as e:
            logger.warning(f"[EMAIL_AGENT] Ошибка при получении кэша: {e}", exc_info=True)
        
        if cached_tool and cache_metrics and cache_metrics.cache_hit:
            logger.info(f"[EMAIL_AGENT] Найден кэшированный инструмент для запроса: {cached_tool.tool_name}")
            # Используем кэшированный инструмент напрямую
            # Определяем, какой инструмент нужно вызвать
            if cached_tool.tool_name == "read_emails":
                # Вызываем read_emails с кэшированными параметрами
                cached_params = cached_tool.tool_params
                result = await read_emails.ainvoke({
                    "email_account": cached_params.get("email_account"),
                    "folder": cached_params.get("folder", "inbox"),
                    "unread_only": cached_params.get("unread_only", True),
                    "limit": cached_params.get("limit", 20),
                    "state": state
                })
                # Проверяем успешность вызова (нет ошибок в результате)
                is_success = not result.startswith("❌") if result else False
                if is_success:
                    # Обновляем счетчик успешных использований
                    await cache_service.save_successful_tool_call(
                        query=user_request,
                        tool_name="read_emails",
                        tool_params=cached_params,
                        user_id=user_id,
                        is_success=True
                    )
                return result
            elif cached_tool.tool_name == "search_emails":
                # Вызываем search_emails с кэшированными параметрами
                cached_params = cached_tool.tool_params
                result = await search_emails.ainvoke({
                    "keywords": cached_params.get("keywords"),
                    "from_email": cached_params.get("from_email"),
                    "email_account": cached_params.get("email_account"),
                    "folder": cached_params.get("folder", "inbox"),
                    "search_in": cached_params.get("search_in", "TEXT"),
                    "limit": cached_params.get("limit", 20),
                    "state": state
                })
                is_success = not result.startswith("❌") if result else False
                if is_success:
                    await cache_service.save_successful_tool_call(
                        query=user_request,
                        tool_name="search_emails",
                        tool_params=cached_params,
                        user_id=user_id,
                        is_success=True
                    )
                return result
            # Добавьте другие инструменты по необходимости
        
        # ВАЖНО: Извлекаем email_account из запроса пользователя, если он указан
        # Пользователь может указать ящик в формате: "из ящика alexis", "ящик alexis", "alexis"
        # или полный email: "alexis@ts-group.ru"
        if not email_account:
            # Ищем паттерны типа "из ящика alexis", "ящик alexis", "alexis@ts-group.ru"
            account_patterns = [
                r'из\s+ящика\s+([a-zA-Z0-9._%+-@]+)',  # "из ящика alexis" или "из ящика alexis@ts-group.ru"
                r'ящик[:\s]+([a-zA-Z0-9._%+-@]+)',  # "ящик alexis" или "ящик alexis@ts-group.ru"
                r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',  # Полный email адрес
            ]
            
            for pattern in account_patterns:
                account_match = re.search(pattern, user_request, re.IGNORECASE)
                if account_match:
                    potential_account = account_match.group(1).strip()
                    logger.info(f"[EMAIL_AGENT] _email_agent_impl: найдено упоминание ящика в запросе: '{potential_account}'")
                    
                    # Если это полный email адрес, используем его напрямую
                    if "@" in potential_account and "." in potential_account:
                        email_account = potential_account
                        logger.info(f"[EMAIL_AGENT] _email_agent_impl: используется полный email адрес: {email_account}")
                        break
                    else:
                        # Если это только имя (например, "alexis"), ищем соответствующий email в секретах
                        secrets = state.get("secrets", []) if state and isinstance(state, dict) else []
                        if secrets:
                            from giga_agent.agents.email_agent.utils.storage import EmailStorage
                            found_email = EmailStorage.find_email_account_by_name(secrets, potential_account)
                            if found_email:
                                email_account = found_email
                                logger.info(f"[EMAIL_AGENT] _email_agent_impl: найден ящик по имени '{potential_account}': {email_account}")
                                break
                            else:
                                logger.warning(f"[EMAIL_AGENT] _email_agent_impl: не найден ящик по имени '{potential_account}' в секретах")
        
        # Поиск писем (должно быть перед удалением и показом)
        if any(phrase in user_input for phrase in [
            "найти письма", "поиск писем", "найти письмо", "поиск письма",
            "найти с ключевым словом", "найти от", "поиск по", "найти по"
        ]):
            folder = "inbox"
            keywords = None
            from_email = None
            search_in = "TEXT"
            limit = 20
            
            # Извлекаем папку
            if "папка" in user_input:
                folder_match = re.search(r'папка[:\s]+(\w+)', user_request, re.IGNORECASE)
                if folder_match:
                    folder = folder_match.group(1)
            
            # Извлекаем email отправителя
            # Паттерны: "от example@mail.com", "отправитель example@mail.com", "from example@mail.com"
            from_patterns = [
                r'от\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'отправитель[:\s]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'from\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
            ]
            for pattern in from_patterns:
                from_match = re.search(pattern, user_request, re.IGNORECASE)
                if from_match:
                    from_email = from_match.group(1)
                    break
            
            # Извлекаем ключевые слова
            # Паттерны: "с ключевым словом 'X'", "ключевое слово 'X'", "слово 'X'", "содержит 'X'"
            keyword_patterns = [
                r'с\s+ключевым\s+словом[:\s]+["\']([^"\']+)["\']',
                r'ключевое\s+слово[:\s]+["\']([^"\']+)["\']',
                r'слово[:\s]+["\']([^"\']+)["\']',
                r'содержит[:\s]+["\']([^"\']+)["\']',
                r'с\s+ключевым\s+словом[:\s]+(\w+)',
                r'ключевое\s+слово[:\s]+(\w+)',
                r'слово[:\s]+(\w+)',
                r'содержит[:\s]+(\w+)'
            ]
            for pattern in keyword_patterns:
                keyword_match = re.search(pattern, user_request, re.IGNORECASE)
                if keyword_match:
                    keywords = keyword_match.group(1)
                    break
            
            # Если ключевые слова не найдены в кавычках, пробуем найти просто слова после "найти"
            if not keywords:
                # Ищем паттерн типа "найти письма важные" или "найти письма про оплату"
                simple_keyword_match = re.search(r'найти\s+письма\s+(?:с|про|о|по)\s+([^от]+?)(?:\s+от|\s*$)', user_request, re.IGNORECASE)
                if simple_keyword_match:
                    keywords = simple_keyword_match.group(1).strip()
                else:
                    # Пробуем найти слова после "найти письма" до "от" или конца строки
                    simple_match = re.search(r'найти\s+письма\s+([^от]+?)(?:\s+от|\s*$)', user_request, re.IGNORECASE)
                    if simple_match:
                        potential_keywords = simple_match.group(1).strip()
                        # Проверяем, что это не email адрес
                        if '@' not in potential_keywords and len(potential_keywords) > 2:
                            keywords = potential_keywords
            
            # Определяем где искать (в теме или теле)
            if "в теме" in user_input or "по теме" in user_input or "subject" in user_input:
                search_in = "SUBJECT"
            elif "в теле" in user_input or "в тексте" in user_input or "body" in user_input:
                search_in = "BODY"
            
            # Извлекаем лимит
            if "количество" in user_input or "limit" in user_input or "сколько" in user_input:
                limit_match = re.search(r'(\d+)', user_request)
                if limit_match:
                    limit = min(int(limit_match.group(1)), 20)
            
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: поиск писем: keywords={keywords}, from_email={from_email}, folder={folder}, search_in={search_in}, limit={limit}")
            result = await search_emails.ainvoke({
                "keywords": keywords,
                "from_email": from_email,
                "email_account": email_account,
                "folder": folder,
                "search_in": search_in,
                "limit": limit,
                "state": state
            })
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: результат поиска получен")
            
            # УМНОЕ КЭШИРОВАНИЕ: Сохраняем успешный вызов в кэш
            if result and not result.startswith("❌"):
                tool_params = {
                    "keywords": keywords,
                    "from_email": from_email,
                    "email_account": email_account,
                    "folder": folder,
                    "search_in": search_in,
                    "limit": limit
                }
                await cache_service.save_successful_tool_call(
                    query=user_request,
                    tool_name="search_emails",
                    tool_params=tool_params,
                    user_id=user_id,
                    is_success=True
                )
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: успешный вызов search_emails сохранен в кэш")
            elif result and result.startswith("❌"):
                # Проверяем, был ли кэш до вызова
                if cached_tool:
                    tool_params = {
                        "keywords": keywords,
                        "from_email": from_email,
                        "email_account": email_account,
                        "folder": folder,
                        "search_in": search_in,
                        "limit": limit
                    }
                    await cache_service.save_successful_tool_call(
                        query=user_request,
                        tool_name="search_emails",
                        tool_params=tool_params,
                        user_id=user_id,
                        is_success=False
                    )
                    logger.warning(f"[EMAIL_AGENT] _email_agent_impl: неудачный вызов search_emails зафиксирован в кэше")
            
            return result
        
        # Массовое удаление писем (проверяем сначала массовые операции)
        if any(phrase in user_input for phrase in [
            "удалить письма", "удалить письмо", "удалить", "в корзину", 
            "удалить текущее", "удалить следующее", "удалить предыдущее", "стереть письмо"
        ]):
            # Проверяем, есть ли несколько номеров или хэшей для массового удаления
            # Паттерны: "удалить письма 1, 2, 3", "удалить письма 1-5", "удалить письма по хэшам abc, def"
            bulk_numbers = []
            bulk_hashes = []
            
            # Ищем несколько номеров через запятую или дефис
            numbers_match = re.findall(r'(\d+)', user_request)
            
            # Определяем массовое удаление по нескольким признакам:
            # 1. Есть слово "письма" (множественное) и несколько номеров
            # 2. Есть запятая между номерами
            # 3. Есть диапазон через дефис
            # 4. Найдено несколько номеров в запросе
            
            is_bulk_by_plural = "письма" in user_input and len(numbers_match) > 1
            is_bulk_by_comma = "," in user_request and len(numbers_match) > 1
            is_bulk_by_range = bool(re.search(r'(\d+)\s*-\s*(\d+)', user_request))
            
            if is_bulk_by_plural or is_bulk_by_comma or is_bulk_by_range or len(numbers_match) > 1:
                # Если есть "письма" (множественное число) и несколько номеров - это массовое удаление
                if is_bulk_by_plural:
                    bulk_numbers = [int(n) for n in numbers_match]
                    logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовое удаление по множественному числу: {bulk_numbers}")
                # Или диапазон "1-5"
                elif is_bulk_by_range:
                    range_match = re.search(r'(\d+)\s*-\s*(\d+)', user_request)
                    if range_match:
                        start = int(range_match.group(1))
                        end = int(range_match.group(2))
                        bulk_numbers = list(range(start, end + 1))
                        logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовое удаление по диапазону: {bulk_numbers}")
                # Или несколько номеров через запятую
                elif is_bulk_by_comma:
                    bulk_numbers = [int(n) for n in numbers_match]
                    logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовое удаление по запятой: {bulk_numbers}")
                # Или просто несколько номеров подряд
                elif len(numbers_match) > 1:
                    bulk_numbers = [int(n) for n in numbers_match]
                    logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовое удаление по нескольким номерам: {bulk_numbers}")
            
            # Ищем хэши (всегда, не только при наличии слова "хэш")
            # Ищем хэши в тексте (16-символьные hex строки, которые являются ID писем)
            # Паттерн: последовательность из 16 hex символов (a-f0-9), может быть разделена запятыми или пробелами
            # Ищем все 16-символьные hex строки в запросе
            hash_pattern = r'\b([a-f0-9]{16})\b'
            hash_matches = re.findall(hash_pattern, user_request, re.IGNORECASE)
            if hash_matches:
                bulk_hashes = hash_matches
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: найдены хэши в запросе (автоматически): {bulk_hashes}")
            
            # Также ищем хэши после слов "ID", "по ID", "хэш", "hash" для более точного поиска
            if "id" in user_input or "хэш" in user_input or "hash" in user_input or "по id" in user_input:
                # Ищем все хэши после ключевых слов (могут быть через запятую)
                # Паттерн: "по ID" или "ID" затем один или несколько хэшей через запятую
                id_section_pattern = r'(?:по\s+)?(?:id|хэш|hash)[:\s]+([a-f0-9]{16}(?:\s*,\s*[a-f0-9]{16})*)'
                id_section_match = re.search(id_section_pattern, user_request, re.IGNORECASE)
                if id_section_match:
                    # Извлекаем все хэши из найденной секции
                    hash_section = id_section_match.group(1)
                    # Ищем все хэши в этой секции
                    section_hashes = re.findall(r'([a-f0-9]{16})', hash_section, re.IGNORECASE)
                    if section_hashes:
                        bulk_hashes.extend(section_hashes)
                        logger.info(f"[EMAIL_AGENT] _email_agent_impl: найдены хэши после ключевых слов: {section_hashes}")
                
                # Альтернативный подход: ищем все хэши в строке после "по ID" или "ID"
                # Более простой паттерн - находим секцию после ключевых слов и извлекаем все хэши
                after_id_pattern = r'(?:по\s+)?(?:id|хэш|hash)[:\s]+(.+?)(?:\s|$)'
                after_id_match = re.search(after_id_pattern, user_request, re.IGNORECASE)
                if after_id_match:
                    after_id_text = after_id_match.group(1)
                    # Ищем все 16-символьные хэши в этой секции
                    after_id_hashes = re.findall(r'([a-f0-9]{16})', after_id_text, re.IGNORECASE)
                    if after_id_hashes:
                        bulk_hashes.extend(after_id_hashes)
                        logger.info(f"[EMAIL_AGENT] _email_agent_impl: найдены хэши в секции после ключевых слов: {after_id_hashes}")
                
                # Также ищем отдельные хэши после "ID:", "хэш:" и т.д.
                id_patterns = [
                    r'(?:id|хэш|hash)[:\s]+([a-f0-9]{16})',
                    r'по\s+(?:id|хэш|hash)[:\s]+([a-f0-9]{16})',
                ]
                for pattern in id_patterns:
                    id_matches = re.findall(pattern, user_request, re.IGNORECASE)
                    if id_matches:
                        bulk_hashes.extend(id_matches)
                        logger.info(f"[EMAIL_AGENT] _email_agent_impl: найдены хэши по паттерну {pattern}: {id_matches}")
            
            # Удаляем дубликаты и пустые значения
            if bulk_hashes:
                bulk_hashes = list(set([h for h in bulk_hashes if h and len(h) == 16]))
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: уникальные хэши (после очистки): {bulk_hashes}")
            
            # Если найдены множественные идентификаторы - используем массовое удаление
            if bulk_numbers or bulk_hashes:
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовое удаление: numbers={bulk_numbers}, hashes={bulk_hashes}")
                # Получаем загруженные письма для преобразования номеров в хэши
                # Используем хэш как основной идентификатор
                loaded_emails_by_hash = state.get("loaded_emails_by_hash", {}) if state and isinstance(state, dict) else {}
                loaded_emails = state.get("loaded_emails", {}) if state and isinstance(state, dict) else {}
                
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовое удаление - loaded_emails_by_hash count={len(loaded_emails_by_hash)}, loaded_emails count={len(loaded_emails)}")
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовое удаление - bulk_numbers={bulk_numbers}, bulk_hashes={bulk_hashes}")
                
                email_identifiers = []
                
                # Преобразуем номера в хэши (основной идентификатор)
                for num in bulk_numbers:
                    email_key = str(num)
                    if email_key in loaded_emails:
                        email_info = loaded_emails[email_key]
                        # Используем хэш как основной идентификатор (постоянный)
                        identifier = email_info.get('email_hash')
                        if identifier:
                            email_identifiers.append(identifier)
                            logger.info(f"[EMAIL_AGENT] _email_agent_impl: номер {num} -> хэш {identifier}")
                        else:
                            # Fallback на message_id если хэш отсутствует
                            identifier = email_info.get('message_id')
                            if identifier:
                                email_identifiers.append(identifier)
                                logger.info(f"[EMAIL_AGENT] _email_agent_impl: номер {num} -> message_id {identifier}")
                            else:
                                logger.warning(f"[EMAIL_AGENT] _email_agent_impl: номер {num} - не найден хэш и message_id")
                    else:
                        logger.warning(f"[EMAIL_AGENT] _email_agent_impl: номер {num} не найден в loaded_emails")
                
                # Добавляем хэши напрямую (они уже являются постоянными идентификаторами)
                email_identifiers.extend(bulk_hashes)
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: итоговые идентификаторы для удаления: {email_identifiers}")
                
                if email_identifiers:
                    result = await bulk_delete_emails.ainvoke({
                        "email_hashes": email_identifiers,
                        "email_account": email_account,
                        "state": state
                    })
                    return result
                else:
                    error_msg = "❌ Не найдены письма для массового удаления.\n\n"
                    error_msg += f"Искали номера: {bulk_numbers}\n"
                    error_msg += f"Искали хэши: {bulk_hashes}\n"
                    error_msg += f"Загружено писем: {len(loaded_emails)} (по номеру), {len(loaded_emails_by_hash)} (по хэшу)\n"
                    error_msg += "\n💡 **Подсказка:**\n"
                    error_msg += "• Убедитесь, что письма загружены командой \"прочитать письма\"\n"
                    error_msg += "• Используйте ID (хэш) из списка загруженных писем\n"
                    if loaded_emails_by_hash:
                        sample_hashes = list(loaded_emails_by_hash.keys())[:3]
                        error_msg += f"• Примеры доступных ID: {', '.join(sample_hashes)}\n"
                    return error_msg
            
            # Одиночное удаление (старая логика)
            email_number = None
            number_match = re.search(r'письмо\s*(?:номер|#|№)?\s*(\d+)', user_request, re.IGNORECASE)
            if number_match:
                email_number = int(number_match.group(1))
            
            # Определяем действие
            if "следующее" in user_input:
                # Получаем текущий индекс и увеличиваем на 1
                if state and isinstance(state, dict):
                    current_index = state.get("current_email_index")
                    if current_index is not None:
                        email_number = current_index + 1
                    else:
                        email_number = 1
                else:
                    email_number = 1
            elif "предыдущее" in user_input:
                # Получаем текущий индекс и уменьшаем на 1
                if state and isinstance(state, dict):
                    current_index = state.get("current_email_index")
                    if current_index is not None and current_index > 1:
                        email_number = current_index - 1
                    else:
                        return "❌ Нет предыдущего письма для удаления"
                else:
                    return "❌ Нет загруженных писем"
            elif "текущее" in user_input:
                # Используем текущий индекс
                if state and isinstance(state, dict):
                    current_index = state.get("current_email_index")
                    if current_index is not None:
                        email_number = current_index
                    else:
                        return "❌ Нет текущего письма. Сначала просмотрите письмо."
                else:
                    return "❌ Нет загруженных писем"
            
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: удаление письма номер {email_number}")
            result = await delete_email.ainvoke({
                "email_number": email_number,
                "email_account": email_account,
                "state": state
            })
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: результат удаления получен")
            return result
        
        # Массовый перенос в spam
        if any(phrase in user_input for phrase in [
            "перенести в spam", "пометить как spam", "в spam", "переместить в spam",
            "spam письма", "спам письма", "пометить письма как spam"
        ]):
            # Аналогично массовому удалению
            bulk_numbers = []
            bulk_hashes = []
            
            numbers_match = re.findall(r'(\d+)', user_request)
            
            # Определяем массовый перенос по нескольким признакам
            is_bulk_by_plural = "письма" in user_input and len(numbers_match) > 1
            is_bulk_by_comma = "," in user_request and len(numbers_match) > 1
            is_bulk_by_range = bool(re.search(r'(\d+)\s*-\s*(\d+)', user_request))
            
            if is_bulk_by_plural or is_bulk_by_comma or is_bulk_by_range or len(numbers_match) > 1:
                if is_bulk_by_plural:
                    bulk_numbers = [int(n) for n in numbers_match]
                    logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовый перенос в spam по множественному числу: {bulk_numbers}")
                elif is_bulk_by_range:
                    range_match = re.search(r'(\d+)\s*-\s*(\d+)', user_request)
                    if range_match:
                        start = int(range_match.group(1))
                        end = int(range_match.group(2))
                        bulk_numbers = list(range(start, end + 1))
                        logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовый перенос в spam по диапазону: {bulk_numbers}")
                elif is_bulk_by_comma:
                    bulk_numbers = [int(n) for n in numbers_match]
                    logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовый перенос в spam по запятой: {bulk_numbers}")
                elif len(numbers_match) > 1:
                    bulk_numbers = [int(n) for n in numbers_match]
                    logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовый перенос в spam по нескольким номерам: {bulk_numbers}")
            
            # Ищем хэши (всегда, не только при наличии слова "хэш")
            # Ищем хэши в тексте (16-символьные hex строки)
            hash_pattern = r'\b([a-f0-9]{16})\b'
            hash_matches = re.findall(hash_pattern, user_request, re.IGNORECASE)
            if hash_matches:
                bulk_hashes = hash_matches
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: найдены хэши для spam (автоматически): {bulk_hashes}")
            
            # Также ищем хэши после слов "ID", "по ID", "хэш", "hash"
            if "id" in user_input or "хэш" in user_input or "hash" in user_input or "по id" in user_input:
                # Ищем все хэши после ключевых слов (могут быть через запятую)
                # Альтернативный подход: ищем все хэши в строке после "по ID" или "ID"
                after_id_pattern = r'(?:по\s+)?(?:id|хэш|hash)[:\s]+(.+?)(?:\s|$)'
                after_id_match = re.search(after_id_pattern, user_request, re.IGNORECASE)
                if after_id_match:
                    after_id_text = after_id_match.group(1)
                    # Ищем все 16-символьные хэши в этой секции
                    after_id_hashes = re.findall(r'([a-f0-9]{16})', after_id_text, re.IGNORECASE)
                    if after_id_hashes:
                        bulk_hashes.extend(after_id_hashes)
                        logger.info(f"[EMAIL_AGENT] _email_agent_impl: найдены хэши для spam в секции после ключевых слов: {after_id_hashes}")
                
                # Также ищем отдельные хэши после "ID:", "хэш:" и т.д.
                id_patterns = [
                    r'(?:id|хэш|hash)[:\s]+([a-f0-9]{16})',
                    r'по\s+(?:id|хэш|hash)[:\s]+([a-f0-9]{16})',
                ]
                for pattern in id_patterns:
                    id_matches = re.findall(pattern, user_request, re.IGNORECASE)
                    if id_matches:
                        bulk_hashes.extend(id_matches)
                        logger.info(f"[EMAIL_AGENT] _email_agent_impl: найдены хэши для spam по паттерну {pattern}: {id_matches}")
            
            # Удаляем дубликаты и пустые значения
            if bulk_hashes:
                bulk_hashes = list(set([h for h in bulk_hashes if h and len(h) == 16]))
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: уникальные хэши для spam (после очистки): {bulk_hashes}")
            
            if bulk_numbers or bulk_hashes:
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовый перенос в spam: numbers={bulk_numbers}, hashes={bulk_hashes}")
                # Используем хэш как основной идентификатор
                loaded_emails_by_hash = state.get("loaded_emails_by_hash", {}) if state and isinstance(state, dict) else {}
                loaded_emails = state.get("loaded_emails", {}) if state and isinstance(state, dict) else {}
                
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: массовый перенос в spam - loaded_emails_by_hash count={len(loaded_emails_by_hash)}, loaded_emails count={len(loaded_emails)}")
                
                email_identifiers = []
                
                # Преобразуем номера в хэши (основной идентификатор)
                for num in bulk_numbers:
                    email_key = str(num)
                    if email_key in loaded_emails:
                        email_info = loaded_emails[email_key]
                        # Используем хэш как основной идентификатор (постоянный)
                        identifier = email_info.get('email_hash')
                        if identifier:
                            email_identifiers.append(identifier)
                            logger.info(f"[EMAIL_AGENT] _email_agent_impl: номер {num} -> хэш {identifier} (spam)")
                        else:
                            # Fallback на message_id если хэш отсутствует
                            identifier = email_info.get('message_id')
                            if identifier:
                                email_identifiers.append(identifier)
                                logger.info(f"[EMAIL_AGENT] _email_agent_impl: номер {num} -> message_id {identifier} (spam)")
                            else:
                                logger.warning(f"[EMAIL_AGENT] _email_agent_impl: номер {num} - не найден хэш и message_id (spam)")
                    else:
                        logger.warning(f"[EMAIL_AGENT] _email_agent_impl: номер {num} не найден в loaded_emails (spam)")
                
                # Добавляем хэши напрямую (они уже являются постоянными идентификаторами)
                email_identifiers.extend(bulk_hashes)
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: итоговые идентификаторы для spam: {email_identifiers}")
                
                if email_identifiers:
                    result = await bulk_move_to_spam.ainvoke({
                        "email_hashes": email_identifiers,
                        "email_account": email_account,
                        "state": state
                    })
                    return result
                else:
                    error_msg = "❌ Не найдены письма для переноса в spam.\n\n"
                    error_msg += f"Искали номера: {bulk_numbers}\n"
                    error_msg += f"Искали хэши: {bulk_hashes}\n"
                    error_msg += f"Загружено писем: {len(loaded_emails)} (по номеру), {len(loaded_emails_by_hash)} (по хэшу)\n"
                    error_msg += "\n💡 **Подсказка:**\n"
                    error_msg += "• Убедитесь, что письма загружены командой \"прочитать письма\"\n"
                    error_msg += "• Используйте ID (хэш) из списка загруженных писем\n"
                    if loaded_emails_by_hash:
                        sample_hashes = list(loaded_emails_by_hash.keys())[:3]
                        error_msg += f"• Примеры доступных ID: {', '.join(sample_hashes)}\n"
                    return error_msg
        
        # Показ полного текста письма (должно быть перед общим "чтение писем")
        elif any(phrase in user_input for phrase in [
            "показать письмо", "показать текст письма", "полный текст письма",
            "показать следующее", "следующее письмо", "показать предыдущее", "предыдущее письмо",
            "письмо номер", "письмо #", "письмо №"
        ]):
            # Извлекаем номер письма
            email_number = None
            number_match = re.search(r'письмо\s*(?:номер|#|№)?\s*(\d+)', user_request, re.IGNORECASE)
            if number_match:
                email_number = int(number_match.group(1))
            
            # Определяем действие
            if "следующее" in user_input or "далее" in user_input:
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: показ следующего письма")
                result = await show_next_email.ainvoke({
                    "email_account": email_account,
                    "state": state
                })
            elif "предыдущее" in user_input or "назад" in user_input:
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: показ предыдущего письма")
                result = await show_previous_email.ainvoke({
                    "email_account": email_account,
                    "state": state
                })
            elif email_number:
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: показ письма номер {email_number}")
                result = await show_email_full.ainvoke({
                    "email_number": email_number,
                    "email_account": email_account,
                    "state": state
                })
            else:
                # Если номер не указан, показываем первое письмо
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: показ первого письма (номер не указан)")
                result = await show_email_full.ainvoke({
                    "email_number": 1,
                    "email_account": email_account,
                    "state": state
                })
            
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: результат показа письма получен")
            return result
        
        # Чтение писем
        elif any(phrase in user_input for phrase in [
            "прочитать письма", "показать письма", "письма", "непрочитанные",
            "новые письма", "входящие", "inbox", "прочитать", "читать",
            "последнее письмо", "последние письма", "последнее", "последние"
        ]):
            # Извлекаем параметры
            folder = "inbox"
            unread_only = True
            limit = 20  # Увеличиваем лимит по умолчанию до 20
            
            # Обработка запросов "последнее письмо" или "последние письма"
            if "последнее письмо" in user_input or ("последнее" in user_input and "письмо" in user_input):
                # Показываем только одно последнее письмо
                limit = 1
                unread_only = False  # Показываем все письма, чтобы найти последнее
            elif "последние письма" in user_input or ("последние" in user_input and "письма" in user_input):
                # Показываем несколько последних писем (до 20)
                limit = 20
                unread_only = False  # Показываем все письма, чтобы найти последние
            
            if "папка" in user_input:
                folder_match = re.search(r'папка[:\s]+(\w+)', user_request, re.IGNORECASE)
                if folder_match:
                    folder = folder_match.group(1)
            
            if "все" in user_input or "all" in user_input:
                unread_only = False
            
            if "количество" in user_input or "limit" in user_input or "сколько" in user_input:
                limit_match = re.search(r'(\d+)', user_request)
                if limit_match:
                    limit = min(int(limit_match.group(1)), 20)  # Ограничиваем максимум 20
            
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: вызов read_emails с параметрами: email_account={email_account}, folder={folder}, unread_only={unread_only}, limit={limit}")
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: передаем state в read_emails: state type={type(state)}, has_secrets={'secrets' in state if state and isinstance(state, dict) else False}")
            result = await read_emails.ainvoke({
                "email_account": email_account,
                "folder": folder,
                "unread_only": unread_only,
                "limit": limit,
                "state": state
            })
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: read_emails вернул результат длиной {len(result) if result else 0} символов")
            
            # УМНОЕ КЭШИРОВАНИЕ: Сохраняем успешный вызов в кэш
            if result and not result.startswith("❌"):
                # Вызов успешен, сохраняем в кэш
                tool_params = {
                    "email_account": email_account,
                    "folder": folder,
                    "unread_only": unread_only,
                    "limit": limit
                }
                await cache_service.save_successful_tool_call(
                    query=user_request,
                    tool_name="read_emails",
                    tool_params=tool_params,
                    user_id=user_id,
                    is_success=True
                )
                logger.info(f"[EMAIL_AGENT] _email_agent_impl: успешный вызов read_emails сохранен в кэш")
            elif result and result.startswith("❌"):
                # Вызов неудачен, сохраняем как неудачу (если паттерн уже был в кэше)
                if cached_tool:
                    tool_params = {
                        "email_account": email_account,
                        "folder": folder,
                        "unread_only": unread_only,
                        "limit": limit
                    }
                    await cache_service.save_successful_tool_call(
                        query=user_request,
                        tool_name="read_emails",
                        tool_params=tool_params,
                        user_id=user_id,
                        is_success=False
                    )
                    logger.warning(f"[EMAIL_AGENT] _email_agent_impl: неудачный вызов read_emails зафиксирован в кэше")
            
            return result
        
        # Фильтрация
        elif any(phrase in user_input for phrase in [
            "фильтр", "фильтрация", "отфильтровать", "проверить спам",
            "обработать письма", "сортировать", "настройки фильтрации"
        ]):
            if "настройки" in user_input or "конфигурация" in user_input:
                result = await check_email_filters.ainvoke({
                    "email_account": email_account,
                    "state": state
                })
            else:
                folder = "inbox"
                if "папка" in user_input:
                    folder_match = re.search(r'папка[:\s]+(\w+)', user_request, re.IGNORECASE)
                    if folder_match:
                        folder = folder_match.group(1)
                
                result = await filter_emails.ainvoke({
                    "email_account": email_account,
                    "folder": folder,
                    "auto_move_spam": True,
                    "state": state
                })
            return result
        
        # Отправка
        elif any(phrase in user_input for phrase in [
            "отправить", "отправь", "написать письмо", "напиши письмо",
            "отправить email", "send email", "ответить", "ответ"
        ]):
            # Пытаемся извлечь параметры
            to_match = re.search(r'к\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', user_request, re.IGNORECASE)
            subject_match = re.search(r'тема[:\s]+["\']([^"\']+)["\']', user_request, re.IGNORECASE)
            body_match = re.search(r'текст[:\s]+["\']([^"\']+)["\']', user_request, re.IGNORECASE)
            
            if not to_match:
                return """❌ **Отправка письма**

Для отправки письма укажите:
• Получатель (к example@mail.com)
• Тема (тема: "Тема письма")
• Текст (текст: "Текст письма")

Пример: "отправить письмо к example@mail.com тема: 'Привет' текст: 'Это тестовое письмо'"
"""
            
            to = to_match.group(1)
            subject = subject_match.group(1) if subject_match else "Без темы"
            body = body_match.group(1) if body_match else user_request
            
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: вызов send_email с параметрами: to={to}, subject={subject}, email_account={email_account}")
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: передаем state в send_email: state type={type(state)}, has_secrets={'secrets' in state if state and isinstance(state, dict) else False}")
            result = await send_email.ainvoke({
                "to": to,
                "subject": subject,
                "body": body,
                "email_account": email_account,
                "state": state
            })
            logger.info(f"[EMAIL_AGENT] _email_agent_impl: send_email вернул результат")
            return result
        
        # Создание событий в календаре
        elif any(phrase in user_input for phrase in [
            "создать событие", "создать встречу", "добавить в календарь", "запланировать",
            "создай событие", "добавь событие", "добавь встречу", "создай встречу",
            "поставить событие", "поставь событие", "поставить встречу", "поставь встречу"
        ]):
            # Импортируем функцию создания события
            from giga_agent.agents.calendar_agent.nodes.simple_events import simple_create_event
            
            # Извлекаем название события
            title = "Событие"
            title_match = re.search(r'["\']([^"\']+)["\']', user_request)
            if title_match:
                title = title_match.group(1)
            else:
                # Ищем название после "событие" или "встречу"
                title_patterns = [
                    r'(?:событие|встречу|добавь|создай|поставь)\s+([^0-9]+?)(?:\s+на\s+|\s+в\s+\d|$|с\s+\d|по\s+\d)',
                    r'([^0-9]+?)(?:\s+на\s+завтра|\s+на\s+сегодня|\s+в\s+\d|\s+с\s+\d|\s+по\s+\d)',
                ]
                for pattern in title_patterns:
                    match = re.search(pattern, user_input, re.IGNORECASE)
                    if match:
                        potential_title = match.group(1).strip()
                        potential_title = re.sub(r'\b(событие|встречу|добавь|создай|поставь|на|в|новое)\b', '', potential_title, flags=re.IGNORECASE).strip()
                        if potential_title and len(potential_title) > 1:
                            title = potential_title
                            break
            
            # Определяем категорию события для установки времени по умолчанию
            category = None
            if any(word in user_input for word in ["работа", "рабочее", "рабочий", "рабочая"]):
                category = "работа"
            elif any(word in user_input for word in ["учеба", "учебное", "учебный", "учебная", "занятие", "лекция", "семинар"]):
                category = "учеба"
            elif any(word in user_input for word in ["отпуск", "отъезд", "поездка", "командировка", "выезд"]):
                category = "отпуск"
            
            # Извлекаем даты и время
            start_datetime = None
            end_datetime = None
            
            # Словарь месяцев
            months = {
                'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
                'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
                'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
            }
            
            # Проверяем диапазон дат (отпуск с 15 по 25)
            date_range_match = re.search(r'с\s+(\d{1,2})\s+по\s+(\d{1,2})', user_input)
            if date_range_match:
                start_day = int(date_range_match.group(1))
                end_day = int(date_range_match.group(2))
                
                # Ищем месяц и год
                month = None
                year = datetime.now().year
                
                # Проверяем месяц в текстовом формате
                for month_name, month_num in months.items():
                    if month_name in user_input:
                        month = month_num
                        break
                
                # Если месяц не найден, проверяем числовой формат
                if not month:
                    month_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', user_request)
                    if month_match:
                        month = int(month_match.group(2))
                        year = int(month_match.group(3))
                    else:
                        month = datetime.now().month
                        year = datetime.now().year
                
                # Создаем события для каждого дня в диапазоне
                events_created = []
                for day in range(start_day, end_day + 1):
                    try:
                        event_date = date(year, month, day)
                        date_str = event_date.strftime("%d.%m.%Y")
                        
                        # Определяем название события для каждого дня
                        day_title = title
                        if day == start_day and any(word in user_input for word in ["вылет", "отъезд", "выезд"]):
                            day_title = "Вылет" if "вылет" in user_input else "Отъезд"
                        elif day == end_day and any(word in user_input for word in ["прилет", "приезд", "возвращение"]):
                            day_title = "Прилет" if "прилет" in user_input else "Приезд"
                        elif category == "отпуск":
                            day_title = "Отпуск"
                        
                        # Время для отпуска/отъезда: с 00:00 до 23:59
                        if category == "отпуск" or any(word in user_input for word in ["отпуск", "отъезд", "поездка"]):
                            start_time = "00:00"
                            end_time = "23:59"
                        else:
                            # Время по умолчанию для работы/учебы: с 9:00 до 19:00
                            start_time = "09:00"
                            end_time = "19:00"
                        
                        start_datetime = f"{date_str} {start_time}"
                        end_datetime = f"{date_str} {end_time}"
                        
                        # Создаем событие
                        result = await simple_create_event.ainvoke({
                            "title": day_title,
                            "start_datetime": start_datetime,
                            "end_datetime": end_datetime,
                            "description": f"Событие создано через Email Agent",
                            "user_name": "",
                            "user_username": "",
                            "user_id": user_id,
                            "state": state
                        })
                        
                        if result.get("success"):
                            events_created.append(f"✅ {day_title} на {date_str}")
                        else:
                            events_created.append(f"❌ Ошибка создания события на {date_str}: {result.get('message', 'Неизвестная ошибка')}")
                    except ValueError as e:
                        events_created.append(f"❌ Ошибка даты для дня {day}: {str(e)}")
                
                if events_created:
                    return f"""📅 **Создано событий: {len([e for e in events_created if e.startswith('✅')])}**

{chr(10).join(events_created)}"""
                else:
                    return "❌ Не удалось создать события"
            
            # Обработка одиночного события
            # Проверяем "сегодня"
            if "сегодня" in user_input:
                today = datetime.now()
                date_str = today.strftime("%d.%m.%Y")
                
                # Ищем время
                time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2))
                    start_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                    
                    # Ищем длительность
                    duration_match = re.search(r'(?:длительностью|на|до)\s+(\d+)\s*(?:час|часа|часов|ч|минут|мин|минуты)', user_input)
                    if duration_match:
                        duration = int(duration_match.group(1))
                        if "минут" in duration_match.group(0) or "мин" in duration_match.group(0):
                            end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(minutes=duration)
                        else:
                            end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=duration)
                        end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                    else:
                        # Время по умолчанию в зависимости от категории
                        if category in ["работа", "учеба"]:
                            end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=10)  # До 19:00 если началось в 9:00
                            if end_dt.hour > 19:
                                end_dt = end_dt.replace(hour=19, minute=0)
                            end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                        else:
                            # По умолчанию 1 час
                            end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=1)
                            end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                else:
                    # Если время не указано, используем время по умолчанию
                    if category in ["работа", "учеба"]:
                        start_datetime = f"{date_str} 09:00"
                        end_datetime = f"{date_str} 19:00"
                    else:
                        start_datetime = f"{date_str} 00:00"
                        end_datetime = f"{date_str} 23:59"
            
            # Проверяем "завтра"
            elif "завтра" in user_input:
                tomorrow = datetime.now() + timedelta(days=1)
                date_str = tomorrow.strftime("%d.%m.%Y")
                
                # Ищем время
                time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2))
                    start_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                    
                    # Ищем длительность
                    duration_match = re.search(r'(?:длительностью|на|до)\s+(\d+)\s*(?:час|часа|часов|ч|минут|мин|минуты)', user_input)
                    if duration_match:
                        duration = int(duration_match.group(1))
                        if "минут" in duration_match.group(0) or "мин" in duration_match.group(0):
                            end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(minutes=duration)
                        else:
                            end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=duration)
                        end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                    else:
                        # Время по умолчанию в зависимости от категории
                        if category in ["работа", "учеба"]:
                            end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=10)
                            if end_dt.hour > 19:
                                end_dt = end_dt.replace(hour=19, minute=0)
                            end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                        else:
                            # По умолчанию 1 час
                            end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=1)
                            end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                else:
                    # Если время не указано, используем время по умолчанию
                    if category in ["работа", "учеба"]:
                        start_datetime = f"{date_str} 09:00"
                        end_datetime = f"{date_str} 19:00"
                    else:
                        start_datetime = f"{date_str} 00:00"
                        end_datetime = f"{date_str} 23:59"
            
            # Проверяем конкретную дату в формате "дд.мм.гггг"
            if not start_datetime:
                date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', user_request)
                if date_match:
                    day = int(date_match.group(1))
                    month = int(date_match.group(2))
                    year = int(date_match.group(3))
                    date_str = f"{day:02d}.{month:02d}.{year}"
                    
                    # Ищем время
                    time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2))
                        start_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                        
                        # Ищем длительность
                        duration_match = re.search(r'(?:длительностью|на|до)\s+(\d+)\s*(?:час|часа|часов|ч|минут|мин|минуты)', user_input)
                        if duration_match:
                            duration = int(duration_match.group(1))
                            if "минут" in duration_match.group(0) or "мин" in duration_match.group(0):
                                end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(minutes=duration)
                            else:
                                end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=duration)
                            end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                        else:
                            # Время по умолчанию в зависимости от категории
                            if category in ["работа", "учеба"]:
                                end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=10)
                                if end_dt.hour > 19:
                                    end_dt = end_dt.replace(hour=19, minute=0)
                                end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                            else:
                                # По умолчанию 1 час
                                end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=1)
                                end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                    else:
                        # Если время не указано, используем время по умолчанию
                        if category in ["работа", "учеба"]:
                            start_datetime = f"{date_str} 09:00"
                            end_datetime = f"{date_str} 19:00"
                        else:
                            start_datetime = f"{date_str} 00:00"
                            end_datetime = f"{date_str} 23:59"
                            all_day = True
            
            # Проверяем дату в формате "20 сентября 2025 года"
            if not start_datetime:
                date_pattern = r'(\d{1,2})\s+(' + '|'.join(months.keys()) + r')\s+(\d{4})\s+года'
                date_match = re.search(date_pattern, user_input)
                if date_match:
                    day = int(date_match.group(1))
                    month_name = date_match.group(2)
                    year = int(date_match.group(3))
                    month = months[month_name]
                    date_str = f"{day:02d}.{month:02d}.{year}"
                    
                    # Ищем время
                    time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2))
                        start_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                        
                        # Ищем длительность
                        duration_match = re.search(r'(?:длительностью|на|до)\s+(\d+)\s*(?:час|часа|часов|ч|минут|мин|минуты)', user_input)
                        if duration_match:
                            duration = int(duration_match.group(1))
                            if "минут" in duration_match.group(0) or "мин" in duration_match.group(0):
                                end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(minutes=duration)
                            else:
                                end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=duration)
                            end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                        else:
                            # Время по умолчанию в зависимости от категории
                            if category in ["работа", "учеба"]:
                                end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=10)
                                if end_dt.hour > 19:
                                    end_dt = end_dt.replace(hour=19, minute=0)
                                end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                            else:
                                # По умолчанию 1 час
                                end_dt = datetime.strptime(start_datetime, "%d.%m.%Y %H:%M") + timedelta(hours=1)
                                end_datetime = end_dt.strftime("%d.%m.%Y %H:%M")
                    else:
                        # Если время не указано, используем время по умолчанию
                        if category in ["работа", "учеба"]:
                            start_datetime = f"{date_str} 09:00"
                            end_datetime = f"{date_str} 19:00"
                        else:
                            start_datetime = f"{date_str} 00:00"
                            end_datetime = f"{date_str} 23:59"
                            all_day = True
            
            # Если удалось извлечь все параметры, создаем событие
            if start_datetime and end_datetime:
                try:
                    result = await simple_create_event.ainvoke({
                        "title": title,
                        "start_datetime": start_datetime,
                        "end_datetime": end_datetime,
                        "description": f"Событие создано через Email Agent",
                        "user_name": "",
                        "user_username": "",
                        "user_id": user_id,
                        "state": state
                    })
                    return result.get("message", str(result))
                except Exception as e:
                    logger.error(f"Ошибка создания события: {e}")
                    return f"❌ Ошибка создания события: {str(e)}"
            else:
                return f"""📋 **Создание события**

Не удалось извлечь полную информацию о событии из запроса: "{user_request}"

Для создания события укажите:
• Название события (в кавычках или после слова "событие")
• Дату (завтра, сегодня или конкретную дату)
• Время (в формате ЧЧ:ММ) или длительность

Примеры:
• "добавь событие 'забег Оксаны' на завтра в 12:00"
• "создай встречу на завтра в 15:00 длительностью 2 часа"
• "добавь событие на 20.01.2025 в 10:00"
• "поставь отпуск с 15 по 25 января"
• "создай событие работа на завтра" (будет с 9:00 до 19:00)

Извлеченные данные:
• Название: {title}
• Время начала: {start_datetime or 'не определено'}
• Время окончания: {end_datetime or 'не определено'}"""
        
        # Управление
        elif any(phrase in user_input for phrase in [
            "список ящиков", "ящики", "папки", "настройки", "проверить подключение",
            "тест подключения", "статус", "конфигурация", "folders"
        ]):
            if "список" in user_input or "ящики" in user_input:
                result = await list_email_accounts.ainvoke({"state": state})
            elif "папки" in user_input or "folders" in user_input:
                result = await get_email_folders.ainvoke({
                    "email_account": email_account,
                    "state": state
                })
            elif "проверить" in user_input or "тест" in user_input or "подключение" in user_input:
                result = await test_email_connection.ainvoke({
                    "email_account": email_account,
                    "state": state
                })
            else:
                result = await list_email_accounts.ainvoke({"state": state})
            return result
        
        # По умолчанию - показываем помощь
        else:
            return """📧 **Email Agent - Помощь**

Доступные команды:

**Чтение писем:**
• "прочитать письма" - показать непрочитанные письма (до 20)
• "показать все письма" - показать все письма (до 20)
• "последнее письмо" - показать последнее письмо
• "последние письма" - показать последние письма (до 20)
• "письма в папке Spam" - письма из указанной папки

**Просмотр полного текста:**
• "показать письмо 1" - показать полный текст письма номер 1
• "показать письмо 2" - показать полный текст письма номер 2
• "показать следующее" - показать следующее письмо
• "показать предыдущее" - показать предыдущее письмо

**Поиск писем:**
• "найти письма с ключевым словом 'важно'" - поиск по ключевым словам
• "найти письма от example@mail.com" - поиск по отправителю
• "найти письма от example@mail.com с ключевым словом 'важно'" - комбинированный поиск
• "найти письма в теме 'оплата'" - поиск только в теме письма
• "найти письма в папке Spam с ключевым словом 'спам'" - поиск в указанной папке

**Удаление писем:**
• "удалить письмо 1" - удалить письмо номер 1 в корзину
• "удалить письмо 2" - удалить письмо номер 2 в корзину
• "удалить текущее" - удалить текущее просматриваемое письмо
• "удалить следующее" - удалить следующее письмо
• "удалить предыдущее" - удалить предыдущее письмо

**Фильтрация:**
• "отфильтровать письма" - применить фильтры
• "настройки фильтрации" - показать настройки

**Отправка:**
• "отправить письмо к example@mail.com тема: 'Тема' текст: 'Текст'"

**Создание событий в календаре:**
• "создай событие 'название' на завтра в 12:00" - создать событие на завтра
• "добавь встречу на сегодня в 15:00 длительностью 2 часа" - событие с указанной длительностью
• "поставь событие работа на завтра" - событие работы (с 9:00 до 19:00 по умолчанию)
• "создай событие учеба на 20.01.2025" - событие учебы (с 9:00 до 19:00 по умолчанию)
• "поставь отпуск с 15 по 25 января" - отпуск на несколько дней (с 00:00 до 23:59 каждый день)
• "добавь событие на завтра в 10:00 длительностью 30 минут" - событие с длительностью в минутах

**Управление:**
• "список ящиков" - показать доступные ящики
• "папки" - показать папки в ящике
• "проверить подключение" - тест подключения
"""
            
    except Exception as e:
        logger.error(f"[EMAIL_AGENT] _email_agent_impl: ОШИБКА в email_agent: {e}", exc_info=True)
        logger.error(f"[EMAIL_AGENT] _email_agent_impl: Параметры при ошибке: user_request='{user_request}', email_account={email_account}, user_id={user_id}")
        logger.error(f"[EMAIL_AGENT] _email_agent_impl: state при ошибке: type={type(state)}, keys={list(state.keys()) if state and isinstance(state, dict) else 'N/A'}")
        return f"❌ Ошибка обработки запроса: {str(e)}"


# Создаем узел графа
async def email_agent_node(state: EmailAgentState) -> dict:
    """Узел графа для email_agent"""
    logger.info(f"[EMAIL_AGENT] email_agent_node вызван: state type={type(state)}")
    user_request = state.get("user_request", "")
    email_account = state.get("email_account")
    user_id = state.get("user_id", "default_user")
    logger.info(f"[EMAIL_AGENT] email_agent_node: user_request='{user_request}', email_account={email_account}, user_id={user_id}")
    
    # Создаем словарь state для передачи в функцию
    # EmailAgentState не содержит secrets, поэтому получаем пустой список
    # Секреты должны передаваться через InjectedState при вызове email_agent как tool
    tool_state = state.get("secrets", []) if hasattr(state, "get") and isinstance(state, dict) else []
    logger.info(f"[EMAIL_AGENT] email_agent_node: tool_state type={type(tool_state)}, length={len(tool_state) if isinstance(tool_state, list) else 'N/A'}")
    
    # Формируем state для передачи в _email_agent_impl
    # Если tool_state это список, оборачиваем его в словарь с ключом "secrets"
    # Если это не список, создаем словарь с пустым списком секретов
    if isinstance(tool_state, list):
        impl_state = {"secrets": tool_state}
        logger.info(f"[EMAIL_AGENT] email_agent_node: сформирован impl_state с {len(tool_state)} секретами")
    else:
        logger.warning(f"[EMAIL_AGENT] email_agent_node: ВНИМАНИЕ! tool_state не является списком: {type(tool_state)}")
        impl_state = {"secrets": []}
    
    logger.info(f"[EMAIL_AGENT] email_agent_node: передаем impl_state в _email_agent_impl: has_secrets={'secrets' in impl_state}, secrets_count={len(impl_state.get('secrets', []))}")
    result = await _email_agent_impl(
        user_request=user_request,
        email_account=email_account,
        user_id=user_id,
        state=impl_state
    )
    
    logger.info(f"[EMAIL_AGENT] email_agent_node: _email_agent_impl вернул результат")
    return {"result": result, "error": None}


# Создаем граф (упрощенная версия, как в calendar_agent)
def create_email_graph():
    """Создание графа email_agent"""
    
    workflow = StateGraph(EmailAgentState)
    
    # Добавляем узел
    workflow.add_node("email_agent", email_agent_node)
    
    # Добавляем ребра
    workflow.add_edge(START, "email_agent")
    workflow.add_edge("email_agent", END)
    
    # Компилируем граф
    return workflow.compile()


# Создаем экземпляр графа
graph = create_email_graph()


# @tool декоратор для экспорта как инструмента
@tool
async def email_agent(
    user_request: str,
    email_account: Optional[str] = None,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Агент для работы с почтовыми ящиками
    
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Параметр называется user_request (НЕ query, НЕ task_type, НЕ action, НЕ state)!
    Всегда передавай запрос пользователя в параметр user_request.
    
    ПРАВИЛЬНЫЙ ФОРМАТ ВЫЗОВА:
    email_agent(user_request="покажи последние письма из ящика alexis")
    email_agent(user_request="прочитать письма", email_account="alexis@example.com")
    email_agent(user_request="отправить письмо на test@example.com")
    
    НЕПРАВИЛЬНО (НЕ ДЕЛАЙ ТАК):
    ❌ email_agent(query="покажи письма") - параметр query не существует!
    ❌ email_agent(action="get_emails") - параметр action не существует!
    ❌ email_agent(task_type="RETRIEVE") - параметр task_type не существует!
    
    Обрабатывает запросы пользователя связанные с почтой:
    
    ЧТЕНИЕ ПИСЕМ:
    - Прочитать письма (прочитать письма, показать непрочитанные)
    - Поиск писем (найти письма с ключевым словом, найти письма от отправителя)
    - Просмотр письма (показать письмо 1, показать следующее/предыдущее)
    - Каждое письмо имеет уникальный ID (хэш) - ПОСТОЯННЫЙ идентификатор и номер - позицию в списке
    
    МАССОВЫЕ ОПЕРАЦИИ С ПИСЬМАМИ (ВАЖНО!):
    - Массовое удаление: "удалить письма 1, 2, 3" или "удалить письма по ID 242e709c24272aa7, bf52e7433a3200f9"
    - Массовый перенос в spam: "перенести в spam письма 1, 2, 3" или "перенести в spam по ID 242e709c24272aa7, bf52e7433a3200f9"
    - Можно указывать номера писем (1, 2, 3) или ID (хэш) писем из списка загруженных писем
    - Примеры: 
      * "удалить письма 1, 2, 3, 5" - удаление по номерам из текущего списка
      * "удалить письма по ID 242e709c24272aa7, bf52e7433a3200f9" - удаление по постоянным ID (РЕКОМЕНДУЕТСЯ)
      * "перенести в spam письма 1-5" - перенос диапазона по номерам
      * "перенести в spam по ID 242e709c24272aa7" - перенос по постоянному ID
    
    ОТПРАВКА ПИСЕМ:
    - Отправка писем (отправить письмо, ответить)
    
    УПРАВЛЕНИЕ ЯЩИКАМИ:
    - Список ящиков, папки, настройки
    
    ВАЖНО: 
    - При загрузке писем каждое письмо получает уникальный ID (хэш) - это ПОСТОЯННЫЙ идентификатор
    - ID не меняется при изменении списка писем, в отличие от номеров (1, 2, 3...)
    - Для массовых операций РЕКОМЕНДУЕТСЯ использовать ID вместо номеров для надежности
    - ID отображается в списке писем как "🆔 ID: {hash} (постоянный идентификатор)"
    - НЕ удаляйте письма по одному, если нужно удалить несколько - используйте массовое удаление!
    
    ПРИМЕРЫ ПРАВИЛЬНОГО ВЫЗОВА:
    - email_agent(user_request="покажи последние письма из ящика alexis")
    - email_agent(user_request="прочитать письма", email_account="alexis@example.com")
    - email_agent(user_request="отправить письмо на test@example.com с темой 'Привет'")
    
    Args:
        user_request: Запрос пользователя (ОБЯЗАТЕЛЬНЫЙ параметр! НЕ query, НЕ task_type). Например: "покажи последние письма", "прочитать письма", "отправить письмо"
        email_account: Email адрес ящика (опционально, если не указан, используется первый доступный)
        user_id: Идентификатор пользователя (опционально, по умолчанию "default_user")
    """
    # Добавляем логирование для отладки
    logger.info(f"[EMAIL_AGENT] email_agent tool вызван: user_request='{user_request}', email_account={email_account}, user_id={user_id}")
    logger.info(f"[EMAIL_AGENT] email_agent tool: state type={type(state)}, state is None={state is None}")
    if state and isinstance(state, dict):
        logger.info(f"[EMAIL_AGENT] email_agent tool: state keys={list(state.keys())}")
    
    # Нормализуем запрос: преобразуем неточные запросы в точные и понятные
    normalized_request, normalization_metadata = normalize_request("email", user_request)
    if normalization_metadata.get("normalized", False):
        logger.info(f"[EMAIL_AGENT] Запрос нормализован: '{user_request}' -> '{normalized_request}'")
        user_request = normalized_request
    
    # Получаем user_id из state, если он не передан явно или равен "default_user"
    if (not user_id or user_id == "default_user") and state and isinstance(state, dict):
        user_id_from_state = state.get("user_id")
        if user_id_from_state and user_id_from_state != "default_user":
            user_id = user_id_from_state
            logger.info(f"[EMAIL_AGENT] email_agent tool: user_id получен из state: {user_id}")
    
    # БЕЗОПАСНОСТЬ: Секреты должны быть привязаны к пользователю
    # Очищаем секреты из state и загружаем только для текущего user_id
    # Это гарантирует, что секреты других пользователей недоступны
    secrets = []
    
    # Загружаем секреты только для текущего пользователя из БД
    # Загружаем секреты из таблицы Secret и из EmailAccount (для обратной совместимости)
    if user_id and user_id != "default_user":
        try:
            logger.info(f"[EMAIL_AGENT] email_agent tool: начинаем загрузку секретов из БД для user_id={user_id}")
            from giga_agent.utils.user_tokens import get_all_user_secrets
            all_secrets = await get_all_user_secrets(user_id)
            if all_secrets:
                secrets = all_secrets
                logger.info(f"[EMAIL_AGENT] email_agent tool: УСПЕШНО загружено {len(all_secrets)} секретов из БД для user_id={user_id} (из таблиц Secret и EmailAccount)")
                # Логируем имена загруженных секретов
                secret_names = [s.get("name", "unknown") for s in all_secrets[:10]]
                logger.info(f"[EMAIL_AGENT] email_agent tool: имена загруженных секретов (первые 10): {secret_names}")
            else:
                logger.warning(f"[EMAIL_AGENT] email_agent tool: ВНИМАНИЕ! Не найдено секретов в БД для user_id={user_id}")
        except Exception as e:
            logger.error(f"[EMAIL_AGENT] email_agent tool: ОШИБКА при загрузке секретов из БД: {e}", exc_info=True)
    
    # Обновляем state с загруженными секретами (только для текущего пользователя)
    if state and isinstance(state, dict):
        state["secrets"] = secrets
        secrets_count = len(secrets) if isinstance(secrets, list) else 0
        logger.info(f"[EMAIL_AGENT] email_agent tool: обновлено секретов в state: {secrets_count}")
        
        # Если секреты не найдены или список пуст, логируем предупреждение
        if secrets_count == 0:
            logger.warning(f"[EMAIL_AGENT] email_agent tool: ВНИМАНИЕ! Секреты не найдены для user_id={user_id}")
        
        if secrets and len(secrets) > 0:
            # Логируем имена первых секретов (без значений)
            secret_names = [s.get("name", "unknown") for s in secrets[:10]]
            logger.info(f"[EMAIL_AGENT] email_agent tool: секреты в state (имена, первые 10): {secret_names}")
            # Проверяем наличие email-связанных секретов
            email_related = [s.get("name", "") for s in secrets if any(kw in s.get("name", "").lower() for kw in ["email", "mail", "imap", "smtp"])]
            if email_related:
                logger.info(f"[EMAIL_AGENT] email_agent tool: найдено email-связанных секретов: {len(email_related)} - {email_related[:10]}")
            else:
                logger.warning(f"[EMAIL_AGENT] email_agent tool: ВНИМАНИЕ! Не найдено email-связанных секретов в списке")
        else:
            logger.warning(f"[EMAIL_AGENT] email_agent tool: ВНИМАНИЕ! Секреты отсутствуют или список пуст после всех попыток загрузки")
    else:
        logger.warning(f"[EMAIL_AGENT] email_agent tool: ВНИМАНИЕ! state не является словарем или равен None: {type(state)}")
        # Создаем пустой state с пустым списком секретов
        if not state:
            state = {"secrets": []}
            logger.warning(f"[EMAIL_AGENT] email_agent tool: создан пустой state с пустым списком секретов")
        else:
            # Обновляем state с загруженными секретами (только для текущего пользователя)
            state["secrets"] = secrets
    
    # Логируем финальное состояние перед вызовом _email_agent_impl
    final_secrets_count = len(state.get("secrets", [])) if state and isinstance(state, dict) else 0
    logger.info(f"[EMAIL_AGENT] email_agent tool: финальное состояние перед вызовом _email_agent_impl: secrets_count={final_secrets_count}")
    
    # Просто вызываем внутреннюю реализацию
    return await _email_agent_impl(
        user_request=user_request,
        email_account=email_account,
        user_id=user_id,
        state=state
    )


