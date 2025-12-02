"""
Граф Email Agent
"""

import logging
from typing import Annotated, Optional
import re

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
    test_email_connection
)

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
    - Чтение писем (прочитать письма, показать непрочитанные)
    - Фильтрация писем (отфильтровать, проверить спам)
    - Отправка писем (отправить письмо, ответить)
    - Управление ящиками (список ящиков, папки, настройки)
    
    Args:
        user_request: Запрос пользователя (например, "прочитать письма", "отправить письмо")
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
            return result
        
        # Удаление письма (должно быть перед показом письма)
        if any(phrase in user_input for phrase in [
            "удалить письмо", "удалить", "в корзину", "удалить текущее",
            "удалить следующее", "удалить предыдущее", "стереть письмо"
        ]):
            # Извлекаем номер письма
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
    
    Обрабатывает запросы пользователя связанные с почтой:
    - Чтение писем (прочитать письма, показать непрочитанные)
    - Фильтрация писем (отфильтровать, проверить спам)
    - Отправка писем (отправить письмо, ответить)
    - Управление ящиками (список ящиков, папки, настройки)
    
    Args:
        user_request: Запрос пользователя (например, "прочитать письма", "отправить письмо")
        email_account: Email адрес ящика (если не указан, используется первый доступный)
        user_id: Идентификатор пользователя
    """
    # Добавляем логирование для отладки
    logger.info(f"[EMAIL_AGENT] email_agent tool вызван: user_request='{user_request}', email_account={email_account}, user_id={user_id}")
    logger.info(f"[EMAIL_AGENT] email_agent tool: state type={type(state)}, state is None={state is None}")
    if state and isinstance(state, dict):
        logger.info(f"[EMAIL_AGENT] email_agent tool: state keys={list(state.keys())}")
    
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
    if user_id and user_id != "default_user":
        try:
            logger.info(f"[EMAIL_AGENT] email_agent tool: начинаем загрузку секретов из БД для user_id={user_id}")
            from giga_agent.utils.user_tokens import get_user_email_accounts_secrets
            email_secrets = await get_user_email_accounts_secrets(user_id)
            if email_secrets:
                secrets = email_secrets
                logger.info(f"[EMAIL_AGENT] email_agent tool: УСПЕШНО загружено {len(email_secrets)} секретов почтовых ящиков из БД для user_id={user_id}")
                # Логируем имена загруженных секретов
                secret_names = [s.get("name", "unknown") for s in email_secrets[:10]]
                logger.info(f"[EMAIL_AGENT] email_agent tool: имена загруженных секретов (первые 10): {secret_names}")
            else:
                logger.warning(f"[EMAIL_AGENT] email_agent tool: ВНИМАНИЕ! Не найдено почтовых ящиков в БД для user_id={user_id}")
        except Exception as e:
            logger.error(f"[EMAIL_AGENT] email_agent tool: ОШИБКА при загрузке почтовых ящиков из БД: {e}", exc_info=True)
    
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


