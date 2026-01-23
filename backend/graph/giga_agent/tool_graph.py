import copy
import json
import os
import re
import traceback
import random
import string
from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from genson import SchemaBuilder

from langchain_core.messages import (
    ToolMessage,
    AIMessage,
    BaseMessage,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph
from langgraph.constants import END
from langgraph.prebuilt.tool_node import _handle_tool_error, ToolNode
from langgraph.store.base import BaseStore
from langgraph.types import interrupt
from langgraph.config import RunnableConfig

from giga_agent.config import (
    AgentState,
    REPL_TOOLS,
    SERVICE_TOOLS,
    AGENT_MAP,
    TOOLS,
    TOOLS_AGENT_CHECKS,
    run_checks,
)
from giga_agent.request_classifier_graph import classify_request_node
from giga_agent.utils.task_type import normalize_task_type, task_type_from_request_classification
from giga_agent.utils.llm import load_llm
from giga_agent.prompts.few_shots import FEW_SHOTS_ORIGINAL, FEW_SHOTS_UPDATED
from giga_agent.prompts.main_prompt import SYSTEM_PROMPT
from giga_agent.prompts.modular_prompt import build_optimized_prompt, detect_modules_needed
from giga_agent.repl_tools.utils import describe_repl_tool
from giga_agent.tool_server.tool_client import ToolClient
from giga_agent.tool_server.utils import transform_tool, transform_schema
from giga_agent.tools.rag import get_rag_info
from giga_agent.utils.env import load_project_env
from giga_agent.utils.jupyter import JupyterClient, prepend_code
from giga_agent.utils.lang import LANG
from giga_agent.utils.langgraph import inject_tool_args_compat
from giga_agent.utils.mcp import process_mcp_content
from giga_agent.utils.llm import is_llm_gigachat, get_agent_env
from giga_agent.utils.deepseek_adapter import (
    convert_messages_for_deepseek,
    ensure_reasoning_content_in_messages,
)
# Глобальная система кэширования запросов
from giga_agent.utils.query_pattern_cache import (
    check_query_cache,
    save_to_query_cache,
    get_cache_service,
    CachedToolCall,
    CacheMetrics,
)
import time as _time  # Для измерения времени выполнения

# Применяем патч для langchain-deepseek/langchain-openai
try:
    from giga_agent.utils.deepseek_patch import patch_langchain_deepseek
    patch_langchain_deepseek()
except Exception as e:
    import logging
    logging.getLogger(__name__).warning(f"Не удалось применить патч для DeepSeek: {e}")

# Применяем патч для Mistral tool call IDs через OpenRouter
try:
    from giga_agent.utils.mistral_tool_call_patch import patch_langchain_mistral_tool_calls
    patch_langchain_mistral_tool_calls()
except Exception as e:
    import logging
    logging.getLogger(__name__).warning(f"Не удалось применить патч для Mistral tool call IDs: {e}")

load_project_env()

llm = load_llm(is_main=True)


def get_model_name(tag: str = None) -> str:
    """
    Получает название модели из переменных окружения
    
    Args:
        tag: Тег модели (например, "repl", "coder", "fast")
    
    Returns:
        Название модели или "неизвестно"
    """
    env_key = get_agent_env(tag) if tag else "GIGA_AGENT_LLM"
    model_str = os.getenv(env_key, "")
    if not model_str:
        return "неизвестно"
    
    # Форматируем название модели для отображения
    if model_str.startswith("openrouter:"):
        model_id = model_str.replace("openrouter:", "")
        # Форматируем название модели
        if "qwen" in model_id.lower():
            if "qwen3-coder" in model_id.lower():
                return f"Qwen 3 Coder ({model_id})"
            return f"Qwen ({model_id})"
        elif "mistral" in model_id.lower():
            return f"Mistral ({model_id})"
        elif "deepseek" in model_id.lower():
            return f"DeepSeek ({model_id})"
        return model_id
    elif model_str.startswith("gigachat:"):
        return f"GigaChat ({model_str.replace('gigachat:', '')})"
    elif model_str.startswith("openai:"):
        return f"OpenAI ({model_str.replace('openai:', '')})"
    elif "deepseek" in model_str.lower():
        return f"DeepSeek ({model_str})"
    else:
        return model_str

# Функция для проверки, используется ли DeepSeek модель
def is_deepseek_model():
    """Проверяет, используется ли DeepSeek модель"""
    llm_str = os.getenv("GIGA_AGENT_LLM", "")
    return "deepseek" in llm_str.lower() if llm_str else False


# УДАЛЕН: Кастомный класс DeepSeekAIMessage вызывал ошибки с Pydantic
# Вместо этого используем обычный AIMessage и полагаемся на патч в deepseek_patch.py
# который обрабатывает reasoning_content на уровне payload перед отправкой в API


def generate_repl_tools_description():
    repl_tools = []
    for repl_tool in REPL_TOOLS:
        repl_tools.append(describe_repl_tool(repl_tool))
    service_tools = [tool.name for tool in SERVICE_TOOLS]
    repl_tools = "\n".join(repl_tools)
    return f"""В коде есть дополнительные функции:
```
{repl_tools}
```
Также ты можешь вызвать из кода следующие функции: {service_tools}. Аргументы и описания этих функций описаны в твоих функциях!
Вызывай эти методы, только через именованные агрументы"""


# Статический промпт (полный, для fallback)
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
    ]
    + (
        FEW_SHOTS_ORIGINAL
        if os.getenv("REPL_FROM_MESSAGE", "1") == "1"
        else FEW_SHOTS_UPDATED
    )
    + [MessagesPlaceholder("messages", optional=True)]
).partial(repl_inner_tools=generate_repl_tools_description(), language=LANG)


def create_optimized_prompt(user_query: str, user_instructions: str = "", user_secrets: str = "", rag_info: str = "", request_classification: str = None) -> ChatPromptTemplate:
    """
    Создает оптимизированный промпт на основе запроса пользователя.
    Загружает только необходимые модули, экономя до 97% токенов.
    
    Args:
        user_query: Запрос пользователя
        user_instructions: Инструкции пользователя
        user_secrets: Секреты пользователя
        rag_info: RAG информация
        request_classification: Классификация запроса (simple_question, complex_question, simple_task, complex_task)
        
    Returns:
        ChatPromptTemplate с оптимизированным промптом
    """
    import logging
    logger = logging.getLogger(__name__)
    from datetime import datetime
    
    # Строим оптимизированный промпт с учетом классификации
    optimized_system_prompt = build_optimized_prompt(
        query=user_query,
        current_date=datetime.now().strftime("%d.%m.%Y %H:%M"),
        rag_info=rag_info,
        user_instructions=user_instructions,
        user_secrets=user_secrets,
        language=LANG,
        repl_inner_tools=generate_repl_tools_description(),
        request_classification=request_classification,
    )
    
    # Создаем ChatPromptTemplate
    # ОПТИМИЗАЦИЯ: Для simple_question не добавляем few_shots (экономия токенов)
    # Также не добавляем few_shots если modules пусто (простое приветствие)
    messages_list = [("system", optimized_system_prompt)]
    
    # Проверяем, нужно ли добавлять few_shots
    # Не добавляем для simple_question или если это простое приветствие (modules пусто)
    should_add_few_shots = request_classification != "simple_question"
    
    if should_add_few_shots:
        # Для простых вопросов не добавляем few_shots
        messages_list.extend(
            FEW_SHOTS_ORIGINAL
            if os.getenv("REPL_FROM_MESSAGE", "1") == "1"
            else FEW_SHOTS_UPDATED
        )
    else:
        logger.info(f"[create_optimized_prompt] Пропускаем few_shots для simple_question (экономия токенов)")
    
    messages_list.append(MessagesPlaceholder("messages", optional=True))
    
    optimized_prompt = ChatPromptTemplate.from_messages(messages_list)
    
    return optimized_prompt


# Флаг для включения/выключения оптимизации промпта
# PROMPT_OPTIMIZATION=1 - использовать оптимизированный промпт
# PROMPT_OPTIMIZATION=0 - использовать полный промпт (по умолчанию для безопасности)
PROMPT_OPTIMIZATION_ENABLED = os.getenv("PROMPT_OPTIMIZATION", "0") == "1"


async def get_user_preferences(user_id: Optional[str]) -> Optional[str]:
    """
    Получает предпочтения пользователя из базы данных.
    
    Безопасность:
    - Эта функция вызывается только из контекста агента, где user_id уже проверен в before_agent
    - user_id должен быть получен из аутентифицированной сессии пользователя
    - Функция не должна вызываться напрямую с произвольным user_id
    - Фильтрует невалидные user_id (anonymous, default_user)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # ВАЖНО: Фильтруем невалидные user_id для безопасности
    if not user_id or user_id == "anonymous" or user_id == "default_user":
        logger.debug(f"[PREFERENCES] Пропуск загрузки предпочтений: невалидный user_id={user_id}")
        return None
    
    try:
        from giga_agent.tasks_app import AsyncSessionLocal, User
        from sqlmodel import select
        
        logger.info(f"[PREFERENCES] Загрузка предпочтений для user_id={user_id}")
        async with AsyncSessionLocal() as session:
            # ВАЖНО: Получаем предпочтения только для указанного user_id
            # user_id должен быть получен из аутентифицированной сессии в before_agent
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                logger.info(f"[PREFERENCES] Пользователь найден: user_id={user_id}, user_preferences exists={user.user_preferences is not None}")
                if user.user_preferences:
                    logger.info(f"[PREFERENCES] Предпочтения загружены, длина={len(user.user_preferences)}, первые 200 символов: {user.user_preferences[:200]}")
                    return user.user_preferences
                else:
                    logger.info(f"[PREFERENCES] Предпочтения пустые для user_id={user_id}")
            else:
                logger.warning(f"[PREFERENCES] Пользователь не найден: user_id={user_id}")
    except Exception as e:
        logger.error(f"[PREFERENCES] Ошибка получения предпочтений пользователя {user_id}: {e}", exc_info=True)
    
    return None


async def save_chat_message(user_id: str, thread_id: str, role: str, content: str):
    """Сохраняет сообщение в историю чата"""
    if not user_id or user_id == "anonymous" or user_id == "default_user":
        return
    
    try:
        from giga_agent.tasks_app import AsyncSessionLocal, ChatMessage
        
        async with AsyncSessionLocal() as session:
            chat_message = ChatMessage(
                user_id=user_id,
                thread_id=thread_id,
                role=role,
                content=content,
                created_at=datetime.now().isoformat()
            )
            session.add(chat_message)
            await session.commit()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Не удалось сохранить сообщение в историю для user_id={user_id}, thread_id={thread_id}: {e}")


async def get_chat_history(user_id: str, thread_id: Optional[str] = None, limit: int = 50):
    """Получает историю сообщений пользователя"""
    if not user_id or user_id == "anonymous" or user_id == "default_user":
        return []
    
    try:
        from giga_agent.tasks_app import AsyncSessionLocal, ChatMessage
        from sqlmodel import select, func, desc
        
        async with AsyncSessionLocal() as session:
            query = select(ChatMessage).where(ChatMessage.user_id == user_id)
            if thread_id:
                query = query.where(ChatMessage.thread_id == thread_id)
            query = query.order_by(desc(ChatMessage.created_at)).limit(limit)
            
            result = await session.execute(query)
            messages = result.scalars().all()
            
            # Возвращаем в хронологическом порядке (старые первыми)
            return [
                {"role": msg.role, "content": msg.content}
                for msg in reversed(messages)
            ]
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Не удалось получить историю сообщений для user_id={user_id}, thread_id={thread_id}: {e}")
    
    return []


async def generate_user_info(state: AgentState, user_id: Optional[str] = None):
    """
    Генерирует информацию о пользователе, включая предпочтения.
    
    Безопасность:
    - user_id должен быть получен из аутентифицированной сессии в before_agent
    - Предпочтения загружаются только для указанного user_id
    - Пользователь не может получить предпочтения других пользователей
    """
    lang = ""
    if not LANG.startswith("ru"):
        lang = f"\nВыбранный язык пользователя: {LANG}\n"
    instructions = ""
    if not state["messages"]:
        instructions = state.get("instructions", "")
    
    # ВАЖНО: Получаем предпочтения только для указанного user_id
    # user_id должен быть получен из аутентифицированной сессии
    preferences_text = ""
    import logging
    logger = logging.getLogger(__name__)
    
    if user_id:
        logger.info(f"[PREFERENCES] generate_user_info: загрузка предпочтений для user_id={user_id}")
        preferences = await get_user_preferences(user_id)
        if preferences:
            logger.info(f"[PREFERENCES] generate_user_info: предпочтения получены, длина={len(preferences)}")
            try:
                # Парсим JSON для красивого отображения
                prefs_dict = json.loads(preferences)
                logger.info(f"[PREFERENCES] generate_user_info: JSON распарсен, тип={type(prefs_dict)}, ключи={list(prefs_dict.keys()) if isinstance(prefs_dict, dict) else 'N/A'}")
                
                # Поддержка нового формата: если есть поле basePreferences, используем его
                # Иначе используем весь объект (старый формат)
                if isinstance(prefs_dict, dict) and 'basePreferences' in prefs_dict:
                    base_prefs = prefs_dict.get('basePreferences', {})
                    logger.info(f"[PREFERENCES] generate_user_info: найден новый формат, basePreferences тип={type(base_prefs)}, ключи={list(base_prefs.keys()) if isinstance(base_prefs, dict) else 'N/A'}")
                    if base_prefs and isinstance(base_prefs, dict):
                        prefs_formatted = ", ".join([f"{k}: {v}" for k, v in base_prefs.items()])
                        preferences_text = f"\nБазовые предпочтения пользователя: {prefs_formatted}\nЕсли в запросе не хватает информации, используй эти предпочтения."
                        logger.info(f"[PREFERENCES] generate_user_info: предпочтения отформатированы из basePreferences, количество={len(base_prefs)}")
                else:
                    # Старый формат: весь объект - это предпочтения
                    # Фильтруем служебные поля (settings, mcpServers, mcpServerTools)
                    filtered_prefs = {k: v for k, v in prefs_dict.items() 
                                     if k not in ['settings', 'mcpServers', 'mcpServerTools', 'basePreferences']}
                    logger.info(f"[PREFERENCES] generate_user_info: старый формат, отфильтровано предпочтений={len(filtered_prefs)}, ключи={list(filtered_prefs.keys())}")
                    if filtered_prefs:
                        prefs_formatted = ", ".join([f"{k}: {v}" for k, v in filtered_prefs.items()])
                        preferences_text = f"\nБазовые предпочтения пользователя: {prefs_formatted}\nЕсли в запросе не хватает информации, используй эти предпочтения."
                        logger.info(f"[PREFERENCES] generate_user_info: предпочтения отформатированы из старого формата")
            except json.JSONDecodeError as e:
                # Если JSON невалидный, просто показываем как есть
                logger.error(f"[PREFERENCES] generate_user_info: ошибка парсинга JSON: {e}, preferences={preferences[:200]}")
                preferences_text = f"\nБазовые предпочтения пользователя: {preferences}\nЕсли в запросе не хватает информации, используй эти предпочтения."
        else:
            logger.info(f"[PREFERENCES] generate_user_info: предпочтения не найдены для user_id={user_id}")
    
    return f"<user_info>\nТекущая дата: {datetime.today().strftime('%d.%m.%Y %H:%M')}{lang}{instructions}{preferences_text}</user_info>"


def get_code_arg(message):
    regex = r"```python(.+?)```"
    matches = re.findall(regex, message, re.DOTALL)
    if matches:
        return "\n".join(matches).strip()


client = JupyterClient()


def extract_thread_id_from_config(config) -> tuple[Optional[str], Optional[str]]:
    """
    Безопасно извлекает thread_id и checkpoint_id из config.
    Проверяет несколько источников: configurable, metadata, прямые атрибуты.
    
    Args:
        config: Конфигурация (может быть dict или RunnableConfig)
        
    Returns:
        Кортеж (thread_id, checkpoint_id) или (None, None) если не найдены
    """
    thread_id = None
    checkpoint_id = None
    
    if not config:
        return None, None
    
    if isinstance(config, dict):
        # Сначала проверяем configurable (основной источник в LangGraph API)
        configurable = config.get("configurable", {})
        if isinstance(configurable, dict):
            thread_id = configurable.get("thread_id")
            checkpoint_id = configurable.get("checkpoint_id")
        
        # Если не нашли, проверяем metadata
        if not thread_id:
            metadata = config.get("metadata", {})
            if isinstance(metadata, dict):
                thread_id = metadata.get("thread_id")
                if not checkpoint_id:
                    checkpoint_id = metadata.get("checkpoint_id")
        
        # Если не нашли, проверяем прямой доступ
        if not thread_id:
            thread_id = config.get("thread_id")
        if not checkpoint_id:
            checkpoint_id = config.get("checkpoint_id")
    else:
        # Если это объект RunnableConfig
        # Сначала проверяем configurable (основной источник в LangGraph API)
        configurable = getattr(config, "configurable", {}) or {}
        if isinstance(configurable, dict):
            thread_id = configurable.get("thread_id")
            checkpoint_id = configurable.get("checkpoint_id")
        
        # Если не нашли, проверяем metadata
        if not thread_id:
            metadata = getattr(config, "metadata", {}) or {}
            if isinstance(metadata, dict):
                thread_id = metadata.get("thread_id")
                if not checkpoint_id:
                    checkpoint_id = metadata.get("checkpoint_id")
        
        # Проверяем прямые атрибуты
        if not thread_id:
            thread_id = getattr(config, "thread_id", None)
        if not checkpoint_id:
            checkpoint_id = getattr(config, "checkpoint_id", None)
    
    return thread_id, checkpoint_id


def _read_file_content_safely(file_path: str, max_size: int = 10000, user_id: Optional[str] = None) -> Optional[str]:
    """
    Безопасное чтение содержимого текстового файла с учетом user_id.
    Возвращает содержимое файла или None, если файл не может быть прочитан.
    
    ВАЖНО: Если указан user_id, файл ищется только в папке пользователя.
    """
    import mimetypes
    from pathlib import Path
    
    try:
        # КРИТИЧЕСКИ ВАЖНО: Если указан user_id, ищем файл в папке пользователя
        if user_id and user_id not in ["default_user", "anonymous", "guest", ""]:
            try:
                import sys
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../repl/app"))
                from user_files_utils import resolve_file_path
                resolved = resolve_file_path(file_path, user_id)
                if resolved and resolved.exists():
                    file_path = str(resolved)
            except ImportError:
                # Если модуль недоступен, продолжаем с исходным путем
                pass
        
        # Проверяем существование файла
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            return None
        
        # Проверяем размер файла
        file_size = os.path.getsize(file_path)
        if file_size > 5 * 1024 * 1024:  # 5MB - слишком большой для автоматического чтения
            return None
        
        # Определяем тип файла
        mime_type, _ = mimetypes.guess_type(file_path)
        file_extension = Path(file_path).suffix.lower()
        
        # Список текстовых расширений, которые можно читать
        text_extensions = [
            '.txt', '.md', '.json', '.csv', '.log', '.py', '.js', '.ts', '.tsx', 
            '.html', '.css', '.xml', '.yaml', '.yml', '.ini', '.conf', '.cfg',
            '.sh', '.bat', '.ps1', '.sql', '.php', '.java', '.cpp', '.c', '.h',
            '.go', '.rs', '.rb', '.pl', '.lua', '.r', '.m', '.swift', '.kt'
        ]
        
        # Проверяем, является ли файл текстовым
        is_text_file = (
            file_extension in text_extensions or
            (mime_type and mime_type.startswith('text/')) or
            mime_type in ['application/json', 'application/xml', 'application/javascript']
        )
        
        if not is_text_file:
            return None
        
        # Читаем файл с разными кодировками
        encodings = ['utf-8', 'cp1251', 'latin-1', 'iso-8859-1']
        content = None
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        if content is None:
            return None
        
        # Ограничиваем размер содержимого
        if len(content) > max_size:
            content = content[:max_size] + f"\n\n... (файл обрезан, показаны первые {max_size} символов из {len(content)})"
        
        return content
        
    except (PermissionError, OSError, Exception) as e:
        # Логируем ошибку, но не прерываем выполнение
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Не удалось прочитать файл {file_path}: {e}")
        return None


async def simple_response_node(state: AgentState, config: RunnableConfig = None) -> dict:
    """
    Узел для обработки простых запросов (simple_question).
    Сразу обращается к LLM без инструментов и возвращает готовый ответ.
    """
    import logging
    from langchain_core.messages import HumanMessage, AIMessage
    from giga_agent.utils.llm import load_llm
    from giga_agent.prompts.modular_prompt import CORE_PROMPT
    from datetime import datetime
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    
    logger = logging.getLogger(__name__)
    
    # Получаем классификацию запроса
    request_classification = state.get("request_classification", "complex_task")
    
    # Этот узел вызывается только для простых приветствий (роутер уже проверил)
    # Но на всякий случай проверяем еще раз
    request_classification = state.get("request_classification", "complex_task")
    if request_classification != "simple_question":
        logger.info(f"[simple_response_node] Classification is '{request_classification}', not simple_question - skipping")
        return {}
    
    # Получаем последнее сообщение пользователя
    messages = state.get("messages", [])
    if not messages:
        logger.warning("[simple_response_node] No messages found, skipping")
        return {}
    
    last_user_message = None
    for msg in reversed(messages):
        if hasattr(msg, 'type') and msg.type == "human":
            last_user_message = msg.content if hasattr(msg, 'content') else str(msg)
            break
    
    if not last_user_message:
        logger.warning("[simple_response_node] No user message found, skipping")
        return {}
    
    # Извлекаем чистый запрос (убираем теги)
    import re as _re
    clean_query_match = _re.search(r'<task>(.*?)</task>', last_user_message, _re.IGNORECASE | _re.DOTALL)
    if clean_query_match:
        clean_query = clean_query_match.group(1).strip()
    else:
        clean_query = _re.sub(r'<user_info>.*', '', last_user_message, flags=_re.IGNORECASE | _re.DOTALL).strip()[:200]
    
    # Проверяем, что это действительно простое приветствие
    clean_query_lower = clean_query.lower().strip()
    simple_greetings = ["привет", "здравствуй", "добрый день", "доброе утро", "добрый вечер", 
                       "как дела", "как поживаешь", "что нового", "помоги", "помощь", 
                       "спасибо", "благодарю", "ок", "хорошо", "понял", "да", "нет"]
    words_count = len(clean_query_lower.split())
    is_simple_greeting = words_count <= 5 and any(greeting in clean_query_lower for greeting in simple_greetings)
    
    # ВАЖНО: Если это не простое приветствие, но запрос попал сюда - возвращаем пустой dict
    # чтобы граф продолжил выполнение через before_agent
    if not is_simple_greeting:
        logger.info(f"[simple_response_node] Query '{clean_query}' is not a simple greeting, returning empty dict to continue graph")
        return {}
    
    logger.info(f"[simple_response_node] Processing simple greeting: '{clean_query}'")
    
    try:
        # Создаем минимальный промпт только с CORE_PROMPT
        current_date = datetime.now().strftime("%d.%m.%Y %H:%M")
        minimal_prompt_text = CORE_PROMPT.format(
            current_date=current_date,
            rag_info="",
            user_instructions="",
            user_secrets="",
            language="Русский",
            repl_inner_tools="",
        )
        
        # Создаем промпт без few_shots и без инструментов
        minimal_prompt = ChatPromptTemplate.from_messages([
            ("system", minimal_prompt_text),
            MessagesPlaceholder("messages", optional=True)
        ])
        
        # Загружаем LLM без инструментов
        user_id = state.get("user_id")
        simple_llm = load_llm(tag=None, is_main=True, user_id=user_id)
        
        # Вызываем LLM с минимальным промптом
        logger.info(f"[simple_response_node] Calling LLM with minimal prompt (no tools, no few_shots)")
        response = await (minimal_prompt | simple_llm).ainvoke({"messages": [HumanMessage(content=clean_query)]})
        
        # Извлекаем ответ
        if hasattr(response, 'content'):
            answer = response.content
        else:
            answer = str(response)
        
        logger.info(f"[simple_response_node] Got response from LLM: '{answer[:100]}...'")
        
        # Добавляем ответ в messages
        ai_message = AIMessage(content=answer)
        new_messages = list(messages) + [ai_message]
        
        # Возвращаем только сообщения, очистку инструментов делаем в отдельном узле cleanup_tools
        return {
            "messages": new_messages,
        }
        
    except Exception as e:
        logger.error(f"[simple_response_node] Error processing simple response: {e}", exc_info=True)
        # В случае ошибки возвращаем пустой dict, чтобы граф продолжил выполнение
        return {}


async def before_agent(state: AgentState, config: RunnableConfig = None):
    from giga_agent.config import filter_tools_by_user_tokens
    import logging
    
    # Инициализируем logger в начале функции, до его использования
    logger = logging.getLogger(__name__)
    
    # Классификация запроса теперь выполняется в отдельном узле classify_request_node
    # Здесь мы просто используем классификацию из state
    # Примечание: не используем эмоджи в логах/терминале (Windows окружение)
    print("[before_agent] start")
    logger.info("[before_agent] start")
    
    # Получаем классификацию из state (должна быть установлена узлом classify_request_node)
    request_classification = state.get("request_classification", "complex_task")
    print(f"[before_agent] request_classification='{request_classification}'")
    logger.info(f"[before_agent] request_classification='{request_classification}'")
    
    # Если классификации нет, устанавливаем по умолчанию (на случай, если узел классификации не выполнился)
    if "request_classification" not in state:
        state["request_classification"] = "complex_task"
        logger.warning("[before_agent] request_classification missing in state, fallback to 'complex_task'")

    # Примечание (ROMA optimization, stage-1):
    # task_type должен приходить из classify_request_node; если нет — выводим его из request_classification.
    task_type = normalize_task_type(state.get("task_type"))
    if not task_type:
        task_type = task_type_from_request_classification(request_classification)
        state["task_type"] = task_type
        logger.info(f"[before_agent] task_type missing -> derived='{task_type}' from request_classification='{request_classification}'")

    # ВАЖНО: дальше по коду используется messages/user_input.
    # Раньше они задавались в старой части before_agent; после рефакторинга их нужно инициализировать явно.
    messages = state.get("messages", [])
    user_input = None

    tool_client = ToolClient()
    kernel_id = state.get("kernel_id")
    # КРИТИЧЕСКИ ВАЖНО: Всегда перезагружаем инструменты для каждого нового запроса
    # Не используем кэшированные tools из state, чтобы избежать загрузки ненужных инструментов
    # после предыдущих запросов (например, после вызова tinkoff_agent для простого вопроса)
    tools = await tool_client.get_tools()
    if not kernel_id:
        kernel_id = (await client.start_kernel())["id"]
        await client.execute(kernel_id, "function_results = []\nSECRETS = {}")
    
    
    # Инициализируем переменные для файлов и выбранных элементов
    user_input_saved = None
    file_prompt = ""
    selected_prompt = ""
    
    # Проверяем, что список сообщений не пуст и последнее сообщение существует
    if not messages:
        logger.warning("[before_agent] messages is empty, skipping")
        # Гарантируем наличие tools в state, чтобы избежать KeyError в agent
        if "tools" not in state:
            # Инициализируем tools, если их нет
            if not tools:
                tools = await tool_client.get_tools()
            # Применяем оптимизацию даже для пустых сообщений (на всякий случай)
            # Но только если есть классификация
            request_classification = state.get("request_classification", "complex_task")
            if request_classification in ("simple_task", "complex_task"):
                # Базовые инструменты по умолчанию
                basic_tool_names = ["read_file", "read_document", "list_archive_contents", "extract_archive", "list_available_tools", "get_tool_details", "python", "shell"]
                tools = [tool for tool in tools if isinstance(tool, dict) and tool.get("name") in basic_tool_names]
                logger.info(f"[before_agent] Applied basic filter for empty messages: {len(tools)} tools")
            state["tools"] = tools
        return state
    
    last_message = messages[-1]
    
    if last_message.type == "human":
        user_input = last_message.content
        logger.info(f"[before_agent] contains 'покажи': {user_input and 'покажи' in user_input}")
        logger.info(f"[before_agent] contains 'открыть': {user_input and 'открыть' in user_input}")
        
        # Логируем информацию о файлах-вложениях
        additional_kwargs = getattr(last_message, "additional_kwargs", None) or {}
        logger.info(f"[before_agent] additional_kwargs keys: {list(additional_kwargs.keys())}")
        files = additional_kwargs.get("files", [])
        logger.info(f"[before_agent] files count: {len(files)}")
        if files:
            for idx, file in enumerate(files):
                logger.info(f"[before_agent] file #{idx + 1}: {file}")
                logger.info(f"[before_agent]   - path: {file.get('path', 'N/A')}")
                logger.info(f"[before_agent]   - file_type: {file.get('file_type', 'N/A')}")
                logger.info(f"[before_agent]   - size: {file.get('size', 'N/A')}")
                logger.info(f"[before_agent]   - image_path: {file.get('image_path', 'N/A')}")
        else:
            logger.warning("[before_agent] files not found in additional_kwargs.files")
        
        file_prompt_list = []
        for idx, file in enumerate(files):
            file_path = file.get('path', '')
            file_info = f"""Файл загружен по пути: '{file_path}'"""
            
            # КРИТИЧЕСКИ ВАЖНО: Получаем user_id для поиска файла в папке пользователя
            # user_id будет получен позже в before_agent, но пока используем из state если есть
            current_user_id = None
            if state and "user_id" in state:
                current_user_id = state.get("user_id")
            
            # Пытаемся прочитать содержимое текстовых файлов с учетом user_id
            file_content = _read_file_content_safely(file_path, max_size=10000, user_id=current_user_id)
            if file_content:
                file_name = os.path.basename(file_path)
                file_info += f"\n\n📄 **Содержимое файла `{file_name}`:**\n```\n{file_content}\n```"
                logger.info(f"✅ Прочитано содержимое файла: {file_path} ({len(file_content)} символов)")
            else:
                # Если не удалось прочитать, проверяем, является ли это изображением
                if "image_path" in file:
                    file_info += f"\nФайл является изображением его можно отобразить с помощью: '![алт-текст](attachment:{file['image_path']})'."
                else:
                    # Для файлов, которые не удалось прочитать, добавляем подсказку
                    file_info += f"\n💡 Для просмотра содержимого файла используй инструмент read_file с путем: '{file_path}'"
            
            file_prompt_list.append(file_info)
        
        file_prompt = (
            "<files_data>" + "\n----\n".join(file_prompt_list) + "</files_data>"
            if len(file_prompt_list)
            else ""
        )
        selected = last_message.additional_kwargs.get("selected", {})
        selected_items = []
        for key, value in selected.items():
            selected_items.append(f"""![{value}](attachment:{key})""")
        if selected_items:
            selected_items_str = "\n".join(selected_items)
            selected_prompt = (
                f"Пользователь указал на следующие вложения: \n{selected_items_str}"
            )
        # Сохраняем user_input для использования после получения user_id
        user_input_saved = user_input
    
    # ВАЖНО: Всегда сначала пытаемся получить user_id из Redis по thread_id
    # Это гарантирует, что мы используем актуальный user_id из кэша, даже если в config приходит 'anonymous'
    user_id = None
    user_id_from_config = None
    user_id_from_state = None
    thread_id = None
    
    logger.info(f"🔍 before_agent: Начало извлечения user_id. config type: {type(config)}, config is None: {config is None}")
    
    # Сначала извлекаем thread_id из config для запроса к Redis
    if config:
        if isinstance(config, dict):
            configurable = config.get("configurable", {})
            if isinstance(configurable, dict):
                thread_id = configurable.get("thread_id")
            if not thread_id:
                metadata = config.get("metadata", {})
                thread_id = metadata.get("thread_id") if metadata else None
            if not thread_id:
                thread_id = config.get("thread_id")
        else:
            configurable = getattr(config, "configurable", {}) or {}
            if isinstance(configurable, dict):
                thread_id = configurable.get("thread_id")
            if not thread_id:
                metadata = getattr(config, "metadata", {}) or {}
                thread_id = metadata.get("thread_id")
            if not thread_id:
                thread_id = getattr(config, "thread_id", None)
    
    # Пытаемся получить user_id из Redis по thread_id (ВСЕГДА, независимо от значения в config)
    if thread_id:
        logger.info(f"🔍 thread_id найден: {thread_id}, пытаемся получить user_id из Redis (приоритетный источник)")
        try:
            from giga_agent.utils.redis_cache import get_user_id_from_session_by_thread
            cached_user_id = await get_user_id_from_session_by_thread(thread_id)
            if cached_user_id:
                user_id = cached_user_id
                logger.info(f"✅ user_id={user_id} получен из Redis для thread_id={thread_id}")
            else:
                logger.info(f"🔍 user_id не найден в Redis для thread_id={thread_id}, будем использовать значение из config/state")
        except Exception as redis_error:
            logger.warning(f"⚠️ Ошибка при получении user_id из Redis: {redis_error}, используем значение из config/state", exc_info=True)
    else:
        logger.info(f"🔍 thread_id не найден, невозможно получить user_id из Redis, используем значение из config/state")
    
    # Если user_id не найден в Redis, извлекаем из config
    if not user_id and config:
        if isinstance(config, dict):
            configurable_dict = config.get("configurable", {})
            user_id_from_config = configurable_dict.get("user_id") if configurable_dict else None
            logger.info(f"🔍 Извлечение user_id из dict config. configurable.user_id={user_id_from_config}")
            
            # Проверяем langgraph_auth_user как fallback (но только если там не 'anonymous')
            if not user_id_from_config and isinstance(configurable_dict, dict):
                langgraph_auth = configurable_dict.get("langgraph_auth_user")
                if langgraph_auth and isinstance(langgraph_auth, dict):
                    auth_identity = langgraph_auth.get("identity")
                    if auth_identity and str(auth_identity).strip().lower() != 'anonymous':
                        user_id_from_config = auth_identity
                        logger.info(f"🔍 user_id извлечен из langgraph_auth_user.identity: {user_id_from_config}")
            
            if not user_id_from_config:
                user_id_from_config = config.get("metadata", {}).get("user_id")
                logger.info(f"🔍 Проверка metadata.user_id={user_id_from_config}")
        else:
            configurable = getattr(config, "configurable", {}) or {}
            metadata = getattr(config, "metadata", {}) or {}
            user_id_from_config = configurable.get("user_id") or metadata.get("user_id")
            
            # Проверяем langgraph_auth_user как fallback
            if not user_id_from_config and isinstance(configurable, dict):
                langgraph_auth = configurable.get("langgraph_auth_user")
                if langgraph_auth and isinstance(langgraph_auth, dict):
                    auth_identity = langgraph_auth.get("identity")
                    if auth_identity and str(auth_identity).strip().lower() != 'anonymous':
                        user_id_from_config = auth_identity
                        logger.info(f"🔍 user_id извлечен из langgraph_auth_user.identity: {user_id_from_config}")
            
            logger.info(f"🔍 Извлечение user_id из RunnableConfig: user_id={user_id_from_config}")
        
        if user_id_from_config:
            user_id = user_id_from_config
            logger.info(f"🔍 user_id={user_id} получен из config")
    
    # Если user_id все еще не найден, пытаемся извлечь из state
    if not user_id and state:
        user_id_from_state = state.get("user_id")
        if user_id_from_state:
            user_id = user_id_from_state
            logger.info(f"🔍 user_id={user_id} найден в state")
    
    # Нормализуем user_id - невалидные значения (anonymous и т.д.) преобразуются в None
    from giga_agent.utils.user_tokens import _normalize_user_id
    user_id_before_normalize = user_id
    user_id = _normalize_user_id(user_id)
    
    if user_id:
        logger.info(f"🔍 user_id нормализован и валиден: {user_id_before_normalize} → {user_id}")
    else:
        logger.info(f"🔍 user_id нормализован в None: {user_id_before_normalize} → None (невалидное значение или отсутствует)")
        
        # Если после нормализации user_id стал None, снова пытаемся получить из Redis
        # (на случай, если в config был 'anonymous', но в Redis есть валидный user_id)
        if thread_id:
            logger.info(f"🔍 user_id стал None после нормализации, повторно пытаемся получить из Redis для thread_id={thread_id}")
            try:
                from giga_agent.utils.redis_cache import get_user_id_from_session_by_thread
                cached_user_id = await get_user_id_from_session_by_thread(thread_id)
                if cached_user_id:
                    user_id = cached_user_id
                    logger.info(f"✅ user_id={user_id} восстановлен из Redis после нормализации для thread_id={thread_id}")
                else:
                    logger.warning(f"⚠️ user_id не найден в Redis после нормализации для thread_id={thread_id}")
            except Exception as redis_error:
                logger.warning(f"⚠️ Ошибка при повторном получении user_id из Redis: {redis_error}", exc_info=True)
    
    # Логируем для отладки
    if not user_id:
        # Собираем подробную информацию для отладки
        debug_info = {
            "config_type": str(type(config)),
            "config_keys": list(config.keys()) if isinstance(config, dict) else 'N/A',
            "configurable": config.get('configurable', {}) if isinstance(config, dict) else getattr(config, 'configurable', 'N/A'),
            "metadata": config.get('metadata', {}) if isinstance(config, dict) else getattr(config, 'metadata', 'N/A'),
            "state_keys": list(state.keys()) if isinstance(state, dict) else 'N/A',
            "state_user_id": state.get('user_id') if state and isinstance(state, dict) else 'N/A',
        }
        
        # Пытаемся извлечь thread_id для дополнительной информации
        # ВАЖНО: В LangGraph API thread_id обычно находится в config.configurable.thread_id
        thread_id_debug = None
        if config:
            if isinstance(config, dict):
                # Сначала проверяем configurable.thread_id
                configurable = config.get("configurable", {})
                if isinstance(configurable, dict):
                    thread_id_debug = configurable.get("thread_id")
                # Если не нашли, проверяем metadata.thread_id
                if not thread_id_debug:
                    thread_id_debug = config.get("metadata", {}).get("thread_id")
            else:
                # Сначала проверяем configurable.thread_id
                configurable = getattr(config, "configurable", {}) or {}
                if isinstance(configurable, dict):
                    thread_id_debug = configurable.get("thread_id")
                # Если не нашли, проверяем metadata.thread_id
                if not thread_id_debug:
                    metadata = getattr(config, "metadata", {}) or {}
                    thread_id_debug = metadata.get("thread_id")
        debug_info["thread_id"] = thread_id_debug
        
        # Проверяем, был ли user_id 'anonymous' до нормализации
        was_anonymous = user_id_before_normalize and str(user_id_before_normalize).strip().lower() == 'anonymous'
        
        # ВРЕМЕННОЕ РЕШЕНИЕ: Разрешаем работу без user_id с предупреждением
        # Это позволит системе работать, пока фронтенд не начнет передавать user_id
        # ВАЖНО: Это небезопасно и должно быть исправлено на фронтенде!
        # Проверяем, есть ли user_id в Redis для этого thread_id
        has_cached_user_id = False
        if thread_id_debug:
            try:
                from giga_agent.utils.redis_cache import get_user_id_from_session_by_thread
                cached_user_id = await get_user_id_from_session_by_thread(thread_id_debug)
                if cached_user_id:
                    has_cached_user_id = True
                    logger.info(f"✅ Найден user_id в Redis для thread_id={thread_id_debug}, но не используется из-за 'anonymous' в config")
            except Exception as e:
                logger.debug(f"🔍 Не удалось проверить Redis для thread_id={thread_id_debug}: {e}")
        
        # Если user_id не найден, но есть thread_id, разрешаем работу с предупреждением
        # Это временное решение до исправления фронтенда
        if thread_id_debug:
            logger.warning(
                f"⚠️ ВНИМАНИЕ: user_id не найден или невалидный для thread_id={thread_id_debug}. "
                f"Разрешаем работу без user_id с предупреждением. "
                f"Это временное решение - убедитесь, что фронтенд передает user_id в config.configurable.user_id. "
                f"Некоторые функции могут быть ограничены без user_id."
            )
            # НЕ устанавливаем user_id = None, так как это вызовет ошибки дальше в коде
            # Вместо этого просто пропускаем проверку и продолжаем работу
            # Код дальше должен проверять наличие user_id перед использованием
    
    # Обновляем сообщение пользователя с информацией о предпочтениях (если это новое сообщение)
    if messages and messages[-1].type == "human" and user_input_saved:
        user_info = await generate_user_info(state, user_id)
        messages[-1].content = f"<task>{user_input_saved}</task> Активно планируй и следуй своему плану! Действуй по простым шагам!{user_info}\n{file_prompt}\n{selected_prompt}\nСледующий шаг: "
        
        # Сохраняем сообщение пользователя в историю
        if user_id and thread_id:
            await save_chat_message(user_id, thread_id, "user", user_input_saved)
        
        # Загружаем историю сообщений из БД и добавляем в контекст (если это новый thread или история пуста)
        # В LangGraph история уже хранится в checkpoint'ах, поэтому загружаем из БД только если:
        # 1. В state нет сообщений (кроме текущего) - это новый thread
        # 2. Или если нужно дополнить историю из БД для долгосрочной памяти
        if user_id and thread_id:
            # Загружаем историю только если в state нет сообщений (кроме текущего)
            # Это означает, что это новый thread и нужно загрузить историю из БД
            if len(state["messages"]) <= 1:
                history = await get_chat_history(user_id, thread_id, limit=20)
                if history:
                    # Добавляем историю в начало messages (кроме последнего сообщения пользователя)
                    from langchain_core.messages import HumanMessage, AIMessage
                    history_messages = []
                    for msg in history:
                        if msg["role"] == "user":
                            history_messages.append(HumanMessage(content=msg["content"]))
                        elif msg["role"] == "assistant":
                            history_messages.append(AIMessage(content=msg["content"]))
                    
                    # Вставляем историю перед последним сообщением
                    if history_messages and messages:
                        last_message = messages[-1]
                        state["messages"] = history_messages + [last_message]
                        messages = state["messages"]  # Обновляем локальную переменную
                        logger.info(f"📚 Загружено {len(history_messages)} сообщений из истории БД для user_id={user_id}, thread_id={thread_id}")
        else:
            # Примечание:
            # Ранее здесь всегда падали с ValueError при user_id отсутствует/anonymous.
            # Это ломает базовый сценарий работы (включая генерацию проектов и выдачу ZIP),
            # особенно если фронт по какой-то причине не пробросил user_id.
            #
            # Управление поведением через env:
            # - GIGA_AGENT_ALLOW_ANONYMOUS: "1" (по умолчанию) разрешает работу без user_id
            #   (ограничения: без секретов, без персональных предпочтений/истории и т.п.)
            # - GIGA_AGENT_ALLOW_ANONYMOUS: "0" возвращает прежнее строгое поведение (ошибка)
            allow_anonymous = os.getenv("GIGA_AGENT_ALLOW_ANONYMOUS", "1") == "1"

            if allow_anonymous:
                logger.warning(
                    f"⚠️ Работа без user_id разрешена (GIGA_AGENT_ALLOW_ANONYMOUS=1). "
                    f"Исходный user_id: {user_id_before_normalize}, thread_id={thread_id_debug or 'не указан'}. "
                    f"Некоторые функции будут ограничены (история/секреты/персональные данные)."
                )
                # Продолжаем выполнение без user_id (user_id остается None)
            else:
                # Строгий режим: для последующих запросов требуем user_id
                error_message = "user_id обязателен для выполнения запроса. Пользователь должен быть аутентифицирован."
                if was_anonymous:
                    error_message += (
                        f"\n\n❌ Обнаружен невалидный user_id 'anonymous'. "
                        f"Это означает, что фронтенд не передал user_id в config.configurable.user_id.\n\n"
                        f"🔧 Решение:\n"
                        f"1. Убедитесь, что пользователь аутентифицирован на фронтенде\n"
                        f"2. Проверьте, что useUserConfig() возвращает корректный user_id\n"
                        f"3. Убедитесь, что config.configurable.user_id передается в useStream()\n"
                        f"4. Thread ID: {thread_id_debug or 'не указан'}\n"
                        f"5. Проверьте консоль браузера на наличие ошибок аутентификации"
                    )
                elif thread_id_debug:
                    error_message += (
                        f"\n\n❌ user_id не найден для thread_id: {thread_id_debug}\n\n"
                        f"🔧 Решение:\n"
                        f"1. Убедитесь, что user_id сохранен в Redis для этого thread_id\n"
                        f"2. Или передайте user_id в config.configurable.user_id при создании запроса\n"
                        f"3. Проверьте, что пользователь аутентифицирован"
                    )
                else:
                    error_message += (
                        "\n\n❌ Thread ID не найден в запросе.\n\n"
                        "🔧 Решение:\n"
                        "1. Убедитесь, что запрос содержит корректный thread_id\n"
                        "2. Передайте user_id в config.configurable.user_id\n"
                        "3. Проверьте, что пользователь аутентифицирован"
                    )

                logger.error(
                    f"❌ user_id не найден или невалидный в config и state (строгий режим). "
                    f"Исходный user_id до нормализации: {user_id_before_normalize}, "
                    f"Thread ID: {thread_id_debug or 'не указан'}. "
                    f"Отладочная информация: {debug_info}"
                )
                raise ValueError(error_message)
    if user_id:
        logger.info(f"✅ user_id извлечен и валидирован: {user_id}")
        
        # Сохраняем user_id и thread_id в state для последующих запросов
        # Это гарантирует, что даже если configurable не передается, user_id будет доступен
        if state and isinstance(state, dict):
            state["user_id"] = user_id
            if thread_id:
                state["thread_id"] = thread_id
            logger.debug(f"💾 user_id сохранен в state для последующих запросов: {user_id}")
        
        # Сохраняем user_id в Redis кэш по thread_id для постоянного доступа
        try:
            # Извлекаем thread_id из config - проверяем несколько источников
            # ВАЖНО: В LangGraph API thread_id обычно находится в config.configurable.thread_id,
            # а не в config.metadata.thread_id, поэтому проверяем сначала configurable
            thread_id = None
            if config:
                if isinstance(config, dict):
                    # Сначала проверяем configurable.thread_id (основной источник в LangGraph API)
                    configurable = config.get("configurable", {})
                    if isinstance(configurable, dict):
                        thread_id = configurable.get("thread_id")
                    # Если не нашли, проверяем metadata.thread_id
                    if not thread_id:
                        metadata = config.get("metadata", {})
                        thread_id = metadata.get("thread_id") if metadata else None
                    # Если не нашли, проверяем прямой доступ к thread_id
                    if not thread_id:
                        thread_id = config.get("thread_id")
                else:
                    # Если это объект RunnableConfig
                    # Сначала проверяем configurable.thread_id (основной источник в LangGraph API)
                    configurable = getattr(config, "configurable", {}) or {}
                    if isinstance(configurable, dict):
                        thread_id = configurable.get("thread_id")
                    # Если не нашли, проверяем metadata.thread_id
                    if not thread_id:
                        metadata = getattr(config, "metadata", {}) or {}
                        thread_id = metadata.get("thread_id")
                    # Проверяем другие атрибуты
                    if not thread_id:
                        thread_id = getattr(config, "thread_id", None)
            
            if thread_id:
                # Добавляем thread_id в сеанс пользователя (создаст сеанс, если его нет)
                from giga_agent.utils.redis_cache import add_thread_to_user_session
                success = await add_thread_to_user_session(user_id, thread_id)
                if success:
                    logger.debug(f"💾 thread_id={thread_id} добавлен в сеанс пользователя user_id={user_id}")
                else:
                    logger.warning(f"⚠️ Не удалось добавить thread_id в сеанс пользователя для user_id={user_id}, thread_id={thread_id}")
            else:
                logger.debug(f"🔍 thread_id не найден в config, невозможно добавить в сеанс пользователя")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при попытке сохранить user_id в Redis кэш: {e}", exc_info=True)
    else:
        # user_id не найден, но мы разрешили работу для первого запроса
        logger.warning(f"⚠️ Работа без user_id - некоторые функции могут быть ограничены")
    
    # БЕЗОПАСНОСТЬ: Секреты должны быть привязаны к пользователю
    # Очищаем секреты из state и загружаем только для текущего user_id
    # Это гарантирует, что секреты других пользователей недоступны
    secrets = []
    
    # Загружаем секреты только для текущего пользователя из БД
    # Загружаем секреты из таблицы Secret и из EmailAccount (для обратной совместимости)
    if user_id:
        try:
            from giga_agent.utils.user_tokens import get_all_user_secrets
            all_secrets = await get_all_user_secrets(user_id)
            if all_secrets:
                secrets.extend(all_secrets)
                logger.info(f"🔐 Загружено {len(all_secrets)} секретов из БД для user_id={user_id} (из таблиц Secret и EmailAccount)")
            else:
                logger.debug(f"🔍 Секреты не найдены для user_id={user_id}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при загрузке секретов из БД: {e}", exc_info=True)
    else:
        logger.warning("⚠️ user_id не найден, секреты не загружены")
    
    # Логируем загруженные секреты для отладки
    logger.debug(f"🔍 before_agent: Загружено секретов для user_id={user_id}: {len(secrets) if secrets else 0}")
    if secrets:
        # Логируем имена секретов (без значений для безопасности)
        secret_names = [s.get("name", "unknown") for s in secrets[:10]]
        logger.debug(f"🔍 before_agent: Имена секретов (первые 10): {secret_names}")
        # Проверяем наличие email-связанных секретов
        email_related = [s.get("name", "") for s in secrets if any(kw in s.get("name", "").lower() for kw in ["email", "mail", "imap", "smtp"])]
        if email_related:
            logger.info(f"📧 Найдено email-связанных секретов: {len(email_related)} - {email_related[:5]}")
        else:
            logger.warning("⚠️ Не найдено секретов, связанных с email (имена должны содержать 'email', 'mail', 'imap' или 'smtp')")
    
    # Обновляем секреты в state
    if secrets:
        state["secrets"] = secrets
        logger.debug(f"✅ before_agent: Обновлено секретов в state: {len(secrets)}")
    else:
        logger.warning("⚠️ before_agent: Секреты не найдены или пусты")
    
    # КРИТИЧЕСКИ ВАЖНО: Проверяем текущий запрос на простые вопросы БЕЗ ключевых слов
    # Для таких запросов не загружаем инструменты вообще, чтобы экономить токены
    last_user_message = None
    if messages:
        for msg in reversed(messages):
            if hasattr(msg, 'type') and msg.type == "human":
                last_user_message = msg.content if hasattr(msg, 'content') else str(msg)
                break
    
    # КРИТИЧЕСКИ ВАЖНО: Проверяем текущий запрос на наличие ключевых слов для инструментов
    # Для запросов БЕЗ ключевых слов не загружаем инструменты вообще, чтобы экономить токены
    needs_tools = True
    if last_user_message:
        query_lower = last_user_message.lower() if last_user_message else ""
        
        # Проверяем наличие ключевых слов для всех агентов
        email_keywords = ["письм", "почт", "email", "mail", "ящик"]
        tinkoff_keywords = ["портфель", "акци", "tinkoff", "купи", "продай", "котировк", "график", "цена", "стоимость"]
        calendar_keywords = ["календар", "событи", "встреч", "запланир", "напоминан", "день рождени", "дата"]
        pc_keywords = ["файл", "папк", "директор", "открой", "запусти", "процесс"]
        coder_keywords = ["код", "python", "скрипт", "программ", "создай код"]
        researcher_keywords = ["найди", "поиск", "исследован", "узнай", "расскажи о"]
        # Добавляем ключевые слова для простого поиска (search tool)
        search_keywords = ["расскажи", "расскажи про", "расскажи о", "биография", "творчество", "информация о", "кто такой", "что такое"]
        lawyer_keywords = ["закон", "кодекс", "статья", "право", "суд", "иск"]
        career_keywords = ["резюме", "вакансия", "работ", "hh.ru", "собеседован"]
        
        # Проверка на тикеры акций
        ticker_pattern = r'\b[A-Z]{2,5}\b'
        has_ticker = False
        re_module = __import__('re')
        has_ticker = bool(re_module.search(ticker_pattern, last_user_message))
        
        # Проверяем наличие ключевых слов
        has_keywords = (
            any(kw in query_lower for kw in email_keywords) or
            any(kw in query_lower for kw in tinkoff_keywords) or
            any(kw in query_lower for kw in calendar_keywords) or
            any(kw in query_lower for kw in pc_keywords) or
            any(kw in query_lower for kw in coder_keywords) or
            any(kw in query_lower for kw in researcher_keywords) or
            any(kw in query_lower for kw in search_keywords) or
            any(kw in query_lower for kw in lawyer_keywords) or
            any(kw in query_lower for kw in career_keywords) or
            has_ticker
        )
        
        # Для simple_question без ключевых слов - не нужны инструменты
        # Для других классификаций также проверяем, но более мягко
        filtered_tools = None  # Инициализируем переменную
        if request_classification == "simple_question" and not has_keywords:
            needs_tools = False
            filtered_tools = []
            logger.info(f"[before_agent] OPTIMIZATION: simple_question без ключевых слов - очищаем инструменты")
        elif request_classification == "simple_question" and has_keywords:
            # Для simple_question с ключевыми словами - используем унифицированную логику поиска
            use_simple_search, use_deep_research = _determine_search_type(messages, last_user_message)
            
            # Проверяем, нужен ли только простой поиск (без других агентов)
            needs_only_search = use_simple_search and not (
                any(kw in query_lower for kw in email_keywords) or
                any(kw in query_lower for kw in tinkoff_keywords) or
                any(kw in query_lower for kw in calendar_keywords) or
                any(kw in query_lower for kw in pc_keywords) or
                any(kw in query_lower for kw in coder_keywords) or
                any(kw in query_lower for kw in lawyer_keywords) or
                any(kw in query_lower for kw in career_keywords) or
                has_ticker
            )
            
            if needs_only_search:
                # Для простого поиска загружаем только search, не все инструменты
                logger.info(f"[before_agent] OPTIMIZATION: simple_question с простым поиском (после приветствия) - загружаем только search")
                # Фильтруем инструменты, оставляя только search
                filtered_tools = [tool for tool in tools if isinstance(tool, dict) and tool.get("name") == "search"]
                logger.info(f"[before_agent] OPTIMIZATION: Отфильтровано до {len(filtered_tools)} инструментов (только search)")
                needs_tools = False  # Пропускаем дальнейшую фильтрацию
            elif use_deep_research:
                # Для глубокого исследования загружаем только researcher_agent
                logger.info(f"[before_agent] OPTIMIZATION: simple_question с глубоким исследованием - загружаем только researcher_agent")
                filtered_tools = [tool for tool in tools if isinstance(tool, dict) and tool.get("name") == "researcher_agent"]
                logger.info(f"[before_agent] OPTIMIZATION: Отфильтровано до {len(filtered_tools)} инструментов (только researcher_agent)")
                needs_tools = False  # Пропускаем дальнейшую фильтрацию
        elif request_classification in ("simple_task", "complex_task") and not has_keywords:
            # Для задач без ключевых слов тоже можно оптимизировать, но оставляем базовые инструменты
            # Это обрабатывается дальше в коде
            logger.info(f"[before_agent] OPTIMIZATION: {request_classification} без ключевых слов - будет применена фильтрация")
    
    # Фильтруем инструменты по токенам пользователя
    if needs_tools:
        logger.info(f"🔍 Начинаю фильтрацию инструментов: всего {len(tools)} инструментов, user_id={user_id}")
        filtered_tools = await filter_tools_by_user_tokens(tools, user_id=user_id, secrets=secrets)
        logger.info(f"📊 Фильтрация завершена: {len(filtered_tools)} инструментов доступны")
    elif filtered_tools is None:
        # Для простых вопросов без ключевых слов - не загружаем инструменты
        filtered_tools = []
        logger.info(f"[before_agent] OPTIMIZATION: Пропускаем загрузку инструментов для простого вопроса")
    
    # Применяем дополнительные проверки
    final_filtered_tools = []
    mcp_tools_in_filtered = []
    # Если инструменты не нужны (простой вопрос без ключевых слов), пропускаем обработку
    if needs_tools:
        for tool in filtered_tools:
            tool_name = tool.get("name", "")
            # Проверяем, является ли инструмент MCP инструментом
            # MCP инструменты обычно имеют inputSchema с определенной структурой
            if tool.get("inputSchema") and isinstance(tool.get("inputSchema"), dict):
                # Это может быть MCP инструмент
                mcp_tools_in_filtered.append(tool_name)
            
            if tool["name"] in TOOLS_AGENT_CHECKS:
                if not await run_checks(tool_name=tool["name"], state=state):
                    continue
            final_filtered_tools.append(tool)
    
    if mcp_tools_in_filtered:
        logger.info(f"📦 before_agent: Найдено {len(mcp_tools_in_filtered)} потенциальных MCP инструментов в filtered_tools: {mcp_tools_in_filtered[:10]}")
    
    # Формируем возвращаемый state с сохранением user_id и secrets
    # Проверяем, что есть сообщения перед формированием результата
    if not messages:
        logger.error("❌ before_agent: Нет сообщений для возврата, возвращаем пустой state")
        return state
    
    # Получаем MCP инструменты из tool_server
    # MCP инструменты уже включены в общий список tools через tool_server,
    # но для совместимости с agent() нужно их также добавить в state["mcp_tools"]
    mcp_tools_list = []
    
    # Известные MCP инструменты (можно расширить список)
    known_mcp_tools = ["process_financial_question"]
    
    # Пытаемся получить MCP инструменты через отдельный эндпоинт
    try:
        logger.info(f"📦 before_agent: Запрос MCP инструментов через tool_client (base_url: {tool_client.base_url})")
        mcp_tools_response = await tool_client.get_mcp_tools()
        logger.info(f"📦 before_agent: Ответ от get_mcp_tools(): тип={type(mcp_tools_response)}, длина={len(mcp_tools_response) if isinstance(mcp_tools_response, list) else 'N/A'}")
        if mcp_tools_response and len(mcp_tools_response) > 0:
            mcp_tools_list = mcp_tools_response
            logger.info(f"📦 before_agent: Получено {len(mcp_tools_list)} MCP инструментов из tool_server через /mcp_tools")
            if mcp_tools_list:
                mcp_names = [tool.get("name", "unknown") for tool in mcp_tools_list]
                logger.info(f"📦 before_agent: MCP инструменты: {mcp_names}")
                # Проверяем наличие create_news
                if any(tool.get("name") == "create_news" for tool in mcp_tools_list):
                    logger.info(f"✅ before_agent: Инструмент 'create_news' найден в MCP инструментах!")
                else:
                    logger.warning(f"⚠️ before_agent: Инструмент 'create_news' НЕ найден в MCP инструментах")
        else:
            logger.warning(f"⚠️ before_agent: get_mcp_tools() вернул пустой список или None")
    except Exception as e:
        logger.error(f"❌ before_agent: Ошибка при получении MCP инструментов через API: {type(e).__name__}: {str(e)}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()[:500]}")
    
    # Если не получилось через API, извлекаем MCP инструменты из общего списка tools
    if not mcp_tools_list:
        for tool in final_filtered_tools:
            tool_name = tool.get("name", "")
            if tool_name in known_mcp_tools:
                mcp_tools_list.append(tool)
                logger.debug(f"🔍 before_agent: Найден MCP инструмент в общем списке: {tool_name}")
        
        if mcp_tools_list:
            logger.info(f"📦 before_agent: Извлечено {len(mcp_tools_list)} MCP инструментов из общего списка tools")
    
    # Логируем итоговое количество инструментов для отладки
    logger.info(f"[before_agent] OPTIMIZATION RESULT: Сохраняем {len(final_filtered_tools)} инструментов в state")
    if final_filtered_tools:
        tool_names = [tool.get("name", "unknown") for tool in final_filtered_tools[:10]]
        logger.info(f"[before_agent] Инструменты в state: {tool_names}")
    else:
        logger.info(f"[before_agent] OPTIMIZATION: final_filtered_tools пуст - инструменты очищены для экономии токенов")
    
    # КРИТИЧЕСКИ ВАЖНО: Для простых вопросов без ключевых слов гарантируем пустой список инструментов
    if not needs_tools:
        final_filtered_tools = []
        logger.info(f"[before_agent] OPTIMIZATION: Принудительно очищаем инструменты (needs_tools=False)")
    
    result_state = {
        "messages": [messages[-1]],
        "kernel_id": kernel_id,
        "tools": final_filtered_tools,  # Для простых вопросов без ключевых слов будет пустой список
    }
    
    # Фильтруем MCP инструменты по правам доступа перед добавлением в state
    from giga_agent.config import MCP_ADMIN_ONLY_TOOLS, is_admin_user
    user_id = state.get("user_id")
    
    filtered_mcp_tools = []
    if mcp_tools_list:
        for tool in mcp_tools_list:
            tool_name = tool.get("name", "")
            if tool_name in MCP_ADMIN_ONLY_TOOLS:
                is_admin = await is_admin_user(user_id)
                if is_admin:
                    filtered_mcp_tools.append(tool)
                    logger.info(f"✅ before_agent: MCP инструмент '{tool_name}' добавлен (пользователь является администратором)")
                else:
                    logger.warning(f"❌ before_agent: MCP инструмент '{tool_name}' НЕ добавлен (требуются права администратора, user_id={user_id})")
            else:
                # Инструмент доступен всем пользователям
                filtered_mcp_tools.append(tool)
    
    # Добавляем отфильтрованные MCP инструменты в state
    if filtered_mcp_tools:
        result_state["mcp_tools"] = filtered_mcp_tools
        logger.info(f"✅ before_agent: Добавлено {len(filtered_mcp_tools)} MCP инструментов в state (отфильтровано из {len(mcp_tools_list) if mcp_tools_list else 0})")
    else:
        result_state["mcp_tools"] = []
        logger.debug(f"ℹ️ before_agent: MCP инструменты не найдены или отфильтрованы, добавляем пустой список")
    
    # Сохраняем user_id в возвращаемом state, если он был найден
    if user_id:
        result_state["user_id"] = user_id
        logger.debug(f"💾 user_id добавлен в возвращаемый state: {user_id}")
    
    # Сохраняем secrets в возвращаемом state
    if secrets:
        result_state["secrets"] = secrets
        logger.debug(f"💾 secrets добавлены в возвращаемый state: {len(secrets)} секретов")
    else:
        # Даже если секретов нет, добавляем пустой список для консистентности
        result_state["secrets"] = []
        logger.debug(f"💾 пустой список secrets добавлен в возвращаемый state")
    
    return result_state


NOTES_PROMPT = """
====

ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ

Эти инструкции уточняют стиль и ожидания пользователя. Ты ОБЯЗАН учитывать их при выполнении каждой задачи.

---
{0}
---

====
"""

SECRETS_PROMPTS = """
====

СЕКРЕТЫ (SECRETS)

Пользователь предоставил тебе доступ к конфиденциальным данным (токенам, API ключам, паролям и другим секретам).

# Правила работы с секретами

1. **Доступ в коде**: Все секреты доступны в инструменте `python` через словарь `SECRETS`.
2. **Синтаксис использования**: 
   ```python
   # Получение значения секрета
   api_key = SECRETS["название_секрета"]
   token = SECRETS["github_token"]
   ```
3. **БЕЗОПАСНОСТЬ (КРИТИЧНО)**:
   - НИКОГДА не выводи значения секретов в открытом виде
   - НИКОГДА не включай значения секретов в print(), return или любой другой вывод
   - НИКОГДА не передавай значения секретов в сообщениях пользователю
   - МОЖНО упоминать названия секретов (например: "Использую секрет 'api_key'")
   - МОЖНО упоминать описания секретов
   - МОЖНО говорить о типе секрета (токен, пароль, ключ)
4. **Обработка ошибок**: Если секрет не найден, сообщи пользователю название отсутствующего секрета, но НЕ его значение.

# Доступные секреты

{0}
====
"""


def get_user_notes(state: AgentState):
    instructions = os.getenv("GIGA_AGENT_USER_NOTES", "") + state.get(
        "instructions", ""
    )
    if instructions:
        return NOTES_PROMPT.format(instructions)
    return ""


async def get_user_secrets(state: AgentState):
    user_secrets = state.get("secrets", [])
    if not user_secrets:
        return ""
    secret_parts = []
    code_parts = []
    for user_secret in user_secrets:
        name = user_secret.get("name")
        value = user_secret.get("value")
        description = user_secret.get("description")
        if not name or not value:
            continue
        secret_part = (
            f"Название: {user_secret['name']}\nЗначение: {user_secret['value'][:4]}..."
        )
        if description:
            secret_part += f"\nОписание: {description}"
        secret_parts.append(secret_part)
        code_parts.append(f"SECRETS['{name}'] = '{value}'")
    await client.execute(state.get("kernel_id"), "\n".join(code_parts))
    return SECRETS_PROMPTS.format("\n".join(secret_parts))


# Промпт для классификации запроса пользователя
REQUEST_CLASSIFICATION_PROMPT = """Ты - классификатор запросов пользователя. Твоя задача - определить тип запроса.

Проанализируй запрос пользователя и выбери ОДИН из следующих типов:

1. "simple_question" - простой вопрос, на который можно ответить сразу без поиска информации и без использования инструментов (например: "Привет", "Как дела?", "Что такое Python?")

2. "complex_question" - сложный вопрос, требующий поиска информации перед ответом (например: "Какая погода в Москве?", "Найди информацию о...", "Что происходит в мире?")

3. "simple_task" - простая задача, требующая одного вызова инструмента (например: "Создай файл test.txt", "Покажи содержимое файла", "Выполни код: print('hello')")

4. "complex_task" - сложная задача, требующая множественных вызовов инструментов или работы агента (например: "Создай веб-приложение", "Проанализируй код и исправь ошибки", "Сгенерируй проект")

ВАЖНО: Отвечай ТОЛЬКО одним словом из списка: simple_question, complex_question, simple_task, complex_task

Запрос пользователя: {user_request}

Тип запроса:"""


async def classify_user_request(user_request: str) -> str:
    """
    Классифицирует запрос пользователя для оптимизации загрузки инструментов
    
    Args:
        user_request: Запрос пользователя
    
    Returns:
        Тип запроса: "simple_question", "complex_question", "simple_task", "complex_task"
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: Начало классификации
    # Используем print() для гарантированного вывода в Docker logs
    print(f"🔍🔍🔍 classify_user_request: НАЧАЛО КЛАССИФИКАЦИИ")
    print(f"🔍🔍🔍 classify_user_request: Получен запрос пользователя: '{user_request}'")
    print(f"🔍🔍🔍 classify_user_request: Длина запроса: {len(user_request) if user_request else 0} символов")
    logger.info(f"🔍🔍🔍 classify_user_request: НАЧАЛО КЛАССИФИКАЦИИ")
    logger.info(f"🔍🔍🔍 classify_user_request: Получен запрос пользователя: '{user_request}'")
    logger.info(f"🔍🔍🔍 classify_user_request: Длина запроса: {len(user_request) if user_request else 0} символов")
    
    if not user_request or not user_request.strip():
        logger.warning("⚠️ classify_user_request: Пустой запрос, возвращаем complex_task")
        return "complex_task"
    
    try:
        # КРИТИЧЕСКИ ВАЖНО: Используем LLM БЕЗ инструментов для классификации
        # Загружаем свежий экземпляр LLM без привязки инструментов для минимального использования токенов
        # Используем tag=None чтобы получить базовую модель без дополнительных настроек
        logger.info("🔍🔍🔍 classify_user_request: Загружаем LLM для классификации (tag=None, is_main=False)")
        classification_llm = load_llm(tag=None, is_main=False)
        
        # Убеждаемся, что у LLM нет привязанных инструментов
        # Проверяем наличие bound_tools и удаляем их если есть
        if hasattr(classification_llm, 'bound_tools'):
            if classification_llm.bound_tools:
                logger.warning("⚠️ classify_user_request: LLM имеет привязанные инструменты, пытаемся их удалить")
                # Пытаемся использовать unbind_tools если доступен
                if hasattr(classification_llm, 'unbind_tools'):
                    classification_llm = classification_llm.unbind_tools()
                    logger.info("🔍🔍🔍 classify_user_request: Инструменты успешно удалены через unbind_tools")
                else:
                    # Если unbind_tools недоступен, загружаем новый экземпляр
                    logger.warning("⚠️ classify_user_request: unbind_tools недоступен, загружаем новый экземпляр")
                    classification_llm = load_llm(tag=None, is_main=False)
            else:
                logger.info("🔍🔍🔍 classify_user_request: LLM не имеет привязанных инструментов - ОК")
        else:
            logger.info("🔍🔍🔍 classify_user_request: LLM не имеет атрибута bound_tools - ОК")
        
        # Дополнительная проверка: убеждаемся, что нет bind_tools в конфигурации
        if hasattr(classification_llm, 'get_graph') or hasattr(classification_llm, 'bind_tools'):
            # Если это Runnable с возможностью bind_tools, создаем простой вызов без bind
            logger.info("🔍🔍🔍 classify_user_request: LLM имеет методы bind_tools/get_graph, но не используем их")
            pass
        
        # Создаем простой промпт для классификации
        prompt = REQUEST_CLASSIFICATION_PROMPT.format(user_request=user_request)
        logger.info(f"🔍🔍🔍 classify_user_request: Сформирован промпт для классификации (длина: {len(prompt)} символов)")
        logger.info(f"🔍🔍🔍 classify_user_request: Промпт (первые 500 символов): {prompt[:500]}")
        
        # Вызываем LLM без инструментов для быстрой классификации
        # Используем простой HumanMessage без дополнительных параметров
        from langchain_core.messages import HumanMessage
        logger.info("🔍🔍🔍 classify_user_request: Отправляем запрос к LLM БЕЗ инструментов для классификации")
        response = await classification_llm.ainvoke([HumanMessage(content=prompt)])
        
        # Извлекаем ответ
        raw_response = response.content if hasattr(response, 'content') else str(response)
        classification = raw_response.strip().lower()
        
        logger.info(f"🔍🔍🔍 classify_user_request: Получен ответ от LLM: '{raw_response}'")
        logger.info(f"🔍🔍🔍 classify_user_request: Обработанный ответ (lower, strip): '{classification}'")
        
        # Проверяем, что ответ валидный
        valid_types = ["simple_question", "complex_question", "simple_task", "complex_task"]
        logger.info(f"🔍🔍🔍 classify_user_request: Валидные типы: {valid_types}")
        
        if classification in valid_types:
            print(f"✅✅✅ classify_user_request: Запрос '{user_request}' классифицирован как '{classification}' (точное совпадение)")
            logger.info(f"✅✅✅ classify_user_request: Запрос '{user_request}' классифицирован как '{classification}' (точное совпадение)")
            return classification
        else:
            # Если ответ не валидный, пытаемся найти тип в ответе
            logger.info(f"🔍🔍🔍 classify_user_request: Ответ '{classification}' не является точным совпадением, ищем вхождение типов...")
            for valid_type in valid_types:
                if valid_type in classification:
                    logger.info(f"✅✅✅ classify_user_request: Найден тип '{valid_type}' в ответе '{classification}' (вхождение)")
                    return valid_type
            
            # Если не нашли, возвращаем complex_task по умолчанию
            print(f"⚠️⚠️⚠️ classify_user_request: Не удалось определить тип из ответа '{classification}' (raw: '{raw_response}'), используем complex_task по умолчанию")
            print(f"⚠️⚠️⚠️ classify_user_request: Исходный запрос был: '{user_request}'")
            logger.warning(f"⚠️⚠️⚠️ classify_user_request: Не удалось определить тип из ответа '{classification}' (raw: '{raw_response}'), используем complex_task по умолчанию")
            logger.warning(f"⚠️⚠️⚠️ classify_user_request: Исходный запрос был: '{user_request}'")
            return "complex_task"
            
    except Exception as e:
        import traceback
        logger.error(f"❌❌❌ classify_user_request: ОШИБКА при классификации запроса '{user_request}': {e}", exc_info=True)
        logger.error(f"❌❌❌ classify_user_request: Traceback: {traceback.format_exc()}")
        # В случае ошибки возвращаем complex_task для безопасности
        return "complex_task"


def _is_simple_greeting(message: str) -> bool:
    """Проверяет, является ли сообщение простым приветствием"""
    if not message:
        return False
    message_lower = message.lower().strip()
    simple_greetings = ["привет", "здравствуй", "добрый день", "доброе утро", "добрый вечер", 
                       "как дела", "как поживаешь", "что нового", "помоги", "помощь", 
                       "спасибо", "благодарю", "ок", "хорошо", "понял", "да", "нет"]
    words_count = len(message_lower.split())
    return words_count <= 5 and any(greeting in message_lower for greeting in simple_greetings)


def _determine_search_type(messages: list, current_query: str) -> tuple[bool, bool]:
    """
    Определяет тип поиска на основе истории сообщений и текущего запроса.
    
    Returns:
        (use_simple_search, use_deep_research): 
        - use_simple_search: True если нужен простой поиск (search)
        - use_deep_research: True если нужен глубокий исследователь (researcher_agent)
    """
    if not current_query:
        return False, False
    
    query_lower = current_query.lower()
    
    # Ключевые слова для глубокого исследования (явные указания на глубокий анализ)
    deep_research_keywords = ["подробно", "исследование", "изучи", "глубоко", "детально", 
                              "полный анализ", "комплексное исследование", "детальный анализ",
                              "проведи исследование", "сделай исследование"]
    
    # Ключевые слова для простого поиска
    simple_search_keywords = ["найди", "поищи", "расскажи", "расскажи про", "расскажи о", 
                              "кто такой", "что такое", "информация о", "биография", "творчество"]
    
    # ПРИОРИТЕТ 1: Если есть явные ключевые слова для глубокого исследования - используем researcher_agent
    has_deep_keywords = any(kw in query_lower for kw in deep_research_keywords)
    if has_deep_keywords:
        return False, True
    
    # ПРИОРИТЕТ 2: Если есть ключевые слова для простого поиска - используем search
    # (независимо от того, было приветствие или нет)
    has_simple_keywords = any(kw in query_lower for kw in simple_search_keywords)
    if has_simple_keywords:
        # Проверяем историю сообщений
        # Если перед текущим запросом было простое приветствие - точно используем простой поиск
        if len(messages) >= 2:
            # Ищем предыдущее сообщение пользователя
            for i in range(len(messages) - 2, -1, -1):
                msg = messages[i]
                if hasattr(msg, 'type') and msg.type == "human":
                    prev_user_message = msg.content if hasattr(msg, 'content') else str(msg)
                    if _is_simple_greeting(prev_user_message):
                        # Предыдущее сообщение было приветствием - используем простой поиск
                        return True, False
        
        # Если запрос сразу начинается с поискового запроса (без приветствия) - тоже используем простой поиск
        # Глубокое исследование только при явных указаниях (ключевые слова выше)
        return True, False
    
    return False, False


async def agent(state: AgentState):
    import logging
    import asyncio
    logger = logging.getLogger(__name__)
    
    # Проверяем, что есть сообщения в state
    messages = state.get("messages", [])
    if not messages:
        logger.warning("[agent] Список сообщений пуст, возвращаем state без изменений")
        return state
    
    # Получаем классификацию запроса из state
    request_classification = state.get("request_classification", "complex_task")
    # MECE тип задачи (может отсутствовать на старых состояниях)
    task_type = normalize_task_type(state.get("task_type")) or task_type_from_request_classification(request_classification)
    state["task_type"] = task_type
    print(f"[agent] Получена классификация запроса из state: '{request_classification}'")
    logger.info(f"[agent] Получена классификация запроса из state: '{request_classification}'")
    
    # Получаем последнее сообщение пользователя для логирования
    last_user_message = None
    if messages:
        for msg in reversed(messages):
            if hasattr(msg, 'type') and msg.type == "human":
                last_user_message = msg.content if hasattr(msg, 'content') else str(msg)
                break
    print(f"[agent] Последний запрос пользователя: '{last_user_message}'")
    print(f"[agent] Классификация: '{request_classification}'")
    logger.info(f"[agent] task_type='{task_type}'")
    logger.info(f"[agent] Последний запрос пользователя: '{last_user_message}'")
    logger.info(f"[agent] Классификация: '{request_classification}'")
    
    # ========== ГЛОБАЛЬНАЯ ПРОВЕРКА КЭША ЗАПРОСОВ ==========
    # Кэш используется ТОЛЬКО сразу после сообщения пользователя (HumanMessage)
    # После работы инструментов кэш НЕ проверяется - результат передается в LLM
    user_id = state.get("user_id")
    
    # Проверяем, что последнее сообщение - это HumanMessage (сообщение пользователя)
    # Только в этом случае используем кэш
    last_message_is_human = False
    if messages:
        last_msg = messages[-1]
        msg_type = getattr(last_msg, 'type', None)
        # Логируем для диагностики
        logger.info(f"[QUERY_CACHE] Проверка: последнее сообщение type='{msg_type}', class={type(last_msg).__name__}, всего сообщений: {len(messages)}")
        print(f"[QUERY_CACHE] Проверка: последнее сообщение type='{msg_type}', class={type(last_msg).__name__}")
        if msg_type == "human":
            last_message_is_human = True
            logger.info(f"[QUERY_CACHE] Последнее сообщение - HumanMessage, проверяем кэш")
    
    if not last_message_is_human:
        logger.info(f"[QUERY_CACHE] Пропускаем кэш - последнее сообщение не от пользователя")
        print(f"[QUERY_CACHE] Пропускаем кэш - последнее сообщение не от пользователя (type={getattr(messages[-1], 'type', 'unknown') if messages else 'no messages'})")
    
    if last_message_is_human and last_user_message and request_classification in ("simple_task", "complex_question", "complex_task"):
        try:
            # Проверяем кэш
            cached_tool, cache_metrics = await check_query_cache(last_user_message, user_id)
            
            if cached_tool and cache_metrics.cache_hit:
                # Исключаем критические инструменты из кэширования - они должны всегда выполняться
                # switch_model и openrouter_models требуют актуального тестирования модели
                # Инструменты чтения файлов не кэшируются, так как содержимое файлов может изменяться
                NON_CACHEABLE_TOOLS = {
                    'switch_model', 'openrouter_models', 'get_current_openrouter_model', 'check_openrouter_limits',
                    'read_file', 'read_document', 'send_file_to_repl', 'send_file_to_llm', 'send_archive_files_to_repl',
                    'extract_archive', 'list_archive_contents', 'code_review', 'transcribe_audio', 'transcribe_audio_from_url'
                }
                if cached_tool.tool_name in NON_CACHEABLE_TOOLS:
                    logger.info(f"[QUERY_CACHE] SKIP CACHE - tool '{cached_tool.tool_name}' is non-cacheable (critical tool)")
                    print(f"[QUERY_CACHE] SKIP CACHE - tool '{cached_tool.tool_name}' is non-cacheable")
                    # НЕ используем кэш для критических инструментов - продолжаем обычную обработку через LLM
                else:
                    logger.info(f"[QUERY_CACHE] CACHE HIT! tool='{cached_tool.tool_name}' source='{cache_metrics.cache_source}' lookup={cache_metrics.lookup_time_ms:.1f}ms success_count={cached_tool.success_count}")
                    print(f"[QUERY_CACHE] CACHE HIT! tool='{cached_tool.tool_name}' source='{cache_metrics.cache_source}'")
                    
                    # Получаем параметры из кэша
                    tool_params = cached_tool.tool_params.copy() if cached_tool.tool_params else {}
                    
                    # Для агентов (tinkoff_agent, email_agent и т.д.) обновляем user_request
                    # на текущий запрос пользователя (он мог немного измениться)
                    is_agent_tool = cached_tool.tool_name and cached_tool.tool_name.endswith("_agent")
                    if is_agent_tool:
                        # Извлекаем чистый запрос без системных тегов
                        from giga_agent.utils.query_pattern_cache import QueryPatternCacheService
                        clean_query = QueryPatternCacheService.normalize_query(last_user_message)
                        tool_params["user_request"] = clean_query
                        logger.info(f"[QUERY_CACHE] Agent tool: set user_request='{clean_query[:50]}...'")
                    
                    # Создаем искусственный tool_call на основе кэша
                    # Это позволяет использовать стандартный flow через tool_call узел
                    # ID должен быть 9 символов для совместимости с Mistral API
                    tool_call_id = generate_mistral_tool_call_id()
                    cached_tool_call = {
                        "name": cached_tool.tool_name,
                        "args": tool_params,
                        "id": tool_call_id,
                    }
                    logger.info(f"[QUERY_CACHE] Generated tool_call_id: {tool_call_id}")
                    
                    # Создаем AIMessage с tool_calls
                    # Примечание: AIMessage импортирован в начале файла
                    cached_ai_message = AIMessage(
                        content=f"[CACHED] Использую кэшированный инструмент '{cached_tool.tool_name}'",
                        tool_calls=[cached_tool_call]
                    )
                    
                    logger.info(f"[QUERY_CACHE] Возвращаем кэшированный tool_call: {cached_tool.tool_name}")
                    
                    return {
                        "messages": [cached_ai_message],
                    }
            else:
                logger.info(f"[QUERY_CACHE] CACHE MISS lookup={cache_metrics.lookup_time_ms:.1f}ms")
                
        except Exception as e:
            logger.warning(f"[QUERY_CACHE] Ошибка при проверке кэша: {e}")
            # Продолжаем обычную обработку
    # ========== КОНЕЦ ПРОВЕРКИ КЭША ==========
    
    # Преобразуем MCP инструменты из state в формат для bind_tools
    # Важно: гарантируем, что схема всегда имеет type: "object" для OpenAI API
    # Загружаем MCP инструменты:
    # - для complex_task: все MCP инструменты из state["mcp_tools"]
    # - для RETRIEVE/complex_question: только whitelist (например, finance MCP)
    # Примечание: иначе система "не использует" finance MCP, потому что tool не попадает в bind_tools.
    mcp_tools = []
    finance_mcp_whitelist = {"process_financial_question"}

    # ОПТИМИЗАЦИЯ: Для simple_task и complex_question не загружаем MCP инструменты
    # Они не нужны для простых задач и поисковых запросов
    if request_classification == "complex_task":
        logger.info(f"🔍🔍🔍 agent: Классификация = 'complex_task', загружаем MCP инструменты...")
        mcp_tools_count_before = len(state.get("mcp_tools", []))
        logger.info(f"🔍🔍🔍 agent: MCP инструментов в state: {mcp_tools_count_before}")
        for tool in state.get("mcp_tools", []):
            try:
                # Получаем inputSchema, если он есть
                input_schema = tool.get("inputSchema", {})
                
                # Если inputSchema пустой или None, создаем базовую схему
                if not input_schema or not isinstance(input_schema, dict):
                    input_schema = {"type": "object", "properties": {}}
                
                # КРИТИЧЕСКИ ВАЖНО: Применяем transform_schema перед transform_tool
                # Это гарантирует исправление type: null на type: "object"
                input_schema = transform_schema(input_schema)
                
                # Дополнительная проверка после transform_schema
                if input_schema.get("type") != "object":
                    logger.warning(f"⚠️ agent: Исправляю type для inputSchema инструмента {tool.get('name', 'unknown')}: {input_schema.get('type')} -> object")
                    input_schema["type"] = "object"
                    if "properties" not in input_schema:
                        input_schema["properties"] = {}
                
                # Преобразуем инструмент с гарантией type: "object"
                transformed = transform_tool(
                    {
                        "name": tool["name"],
                        "description": tool.get("description", "."),
                        "parameters": input_schema,
                    }
                )
                
                # Дополнительная валидация: убеждаемся, что parameters имеет type: "object"
                parameters = transformed.get("parameters", {})
                if not isinstance(parameters, dict):
                    parameters = {"type": "object", "properties": {}}
                
                # Критическая проверка: type должен быть "object", не "null"
                if parameters.get("type") != "object":
                    logger.warning(f"⚠️ agent: Исправляю type для parameters инструмента {tool.get('name', 'unknown')}: {parameters.get('type')} -> object")
                    parameters["type"] = "object"
                    if "properties" not in parameters:
                        parameters["properties"] = {}
                
                transformed["parameters"] = parameters
                
                # Финальная проверка перед добавлением в список
                if transformed.get("parameters", {}).get("type") != "object":
                    logger.error(f"❌ agent: КРИТИЧЕСКАЯ ОШИБКА: type все еще не 'object' для инструмента {tool.get('name', 'unknown')}")
                    # Принудительно устанавливаем type: "object"
                    transformed["parameters"] = {"type": "object", "properties": {}}
                
                mcp_tools.append(transformed)
                
            except Exception as e:
                logger.error(f"❌ Ошибка при преобразовании MCP инструмента {tool.get('name', 'unknown')}: {e}")
                import traceback
                logger.error(f"❌ Traceback: {traceback.format_exc()}")
                # Пропускаем проблемный инструмент, но продолжаем обработку остальных
                continue
        
        logger.info(f"🔍🔍🔍 agent: Загружено MCP инструментов: {len(mcp_tools)}")
        if len(mcp_tools) > 0:
            logger.info(f"🔍🔍🔍 agent: Первые 5 MCP инструментов: {[tool.get('name', 'unknown') for tool in mcp_tools[:5]]}")
    elif task_type == "RETRIEVE":
        # Для RETRIEVE запросов (включая простые вопросы по тикерам) разрешаем минимальный whitelist MCP инструментов.
        # Сейчас это finance MCP: process_financial_question.
        mcp_state_tools = state.get("mcp_tools", []) or []
        allowed = [t for t in mcp_state_tools if t.get("name") in finance_mcp_whitelist]
        if allowed:
            logger.info(f"[agent] RETRIEVE: добавляю MCP whitelist tools: {[t.get('name') for t in allowed]}")
            for tool in allowed:
                try:
                    input_schema = tool.get("inputSchema", {}) or {"type": "object", "properties": {}}
                    input_schema = transform_schema(input_schema)
                    transformed = transform_tool(
                        {
                            "name": tool["name"],
                            "description": tool.get("description", "."),
                            "parameters": input_schema,
                        }
                    )
                    parameters = transformed.get("parameters", {}) or {"type": "object", "properties": {}}
                    if parameters.get("type") != "object":
                        parameters["type"] = "object"
                        parameters.setdefault("properties", {})
                    transformed["parameters"] = parameters
                    mcp_tools.append(transformed)
                except Exception as e:
                    logger.error(f"❌ agent: Ошибка при преобразовании MCP whitelist инструмента {tool.get('name', 'unknown')}: {e}")
        else:
            logger.info("[agent] RETRIEVE: MCP whitelist инструментов не найдено в state")
    else:
        logger.info(f"🔍🔍🔍 agent: Классификация = '{request_classification}' (не 'complex_task'), MCP инструменты НЕ загружаются")
    
    # Безопасный доступ к tools с проверкой
    # ВАЖНО: tools уже должны быть отфильтрованы в before_agent на основе ключевых слов
    tools = state.get("tools", [])
    if not tools:
        logger.warning("⚠️ agent: tools отсутствуют в state, используем пустой список")
        tools = []
    
    # КРИТИЧЕСКАЯ ПРОВЕРКА: Для simple_question без ключевых слов принудительно очищаем tools
    # Это защита от случаев, когда фильтрация в before_agent не сработала
    if request_classification == "simple_question":
        query_lower_check = last_user_message.lower() if last_user_message else ""
        # Проверяем наличие ключевых слов для инструментов
        has_keywords_check = (
            any(kw in query_lower_check for kw in ["письм", "почт", "email", "mail", "ящик"]) or
            any(kw in query_lower_check for kw in ["портфель", "акци", "tinkoff", "купи", "продай", "котировк", "график", "цена"]) or
            any(kw in query_lower_check for kw in ["календар", "событи", "встреч", "запланир"]) or
            any(kw in query_lower_check for kw in ["файл", "папк", "директор", "открой", "запусти"]) or
            any(kw in query_lower_check for kw in ["код", "python", "скрипт", "программ"]) or
            any(kw in query_lower_check for kw in ["найди", "поиск", "исследован", "узнай"]) or
            any(kw in query_lower_check for kw in ["закон", "кодекс", "статья", "право"]) or
            any(kw in query_lower_check for kw in ["резюме", "вакансия", "работ"])
        )
        # Проверка на тикеры акций
        import re as _re_check
        ticker_pattern_check = r'\b[A-Z]{2,5}\b'
        has_ticker_check = bool(_re_check.search(ticker_pattern_check, last_user_message)) if last_user_message else False
        
        if not has_keywords_check and not has_ticker_check:
            # Простое приветствие без ключевых слов - очищаем tools
            logger.warning(f"⚠️⚠️⚠️ agent: КРИТИЧЕСКАЯ ЗАЩИТА! simple_question без ключевых слов, но tools={len(tools)} - ПРИНУДИТЕЛЬНО очищаем!")
            tools = []
            mcp_tools = []
            logger.info(f"✅✅✅ agent: После принудительной очистки: tools={len(tools)}, mcp_tools={len(mcp_tools)}")
    
    # Логируем количество инструментов из state (уже отфильтрованных в before_agent)
    tools_count_before = len(tools)
    mcp_tools_count_before_filter = len(mcp_tools)
    logger.info(f"🔍🔍🔍 agent: Инструментов из state (уже отфильтрованы в before_agent): tools={tools_count_before}, mcp_tools={mcp_tools_count_before_filter}")
    
    if tools:
        tool_names = [tool.get("name", "unknown") if isinstance(tool, dict) else "unknown" for tool in tools[:10]]
        logger.info(f"🔍🔍🔍 agent: Инструменты из state: {tool_names}")
    
    # КРИТИЧЕСКИ ВАЖНО: Проверяем ключевые слова для ВСЕХ типов запросов
    # Это позволяет корректно определять нужные инструменты независимо от классификации
    query_lower = last_user_message.lower() if last_user_message else ""
    needed_tool_names = set()
    
    # Email агент
    if any(kw in query_lower for kw in ["письм", "почт", "email", "mail", "ящик"]):
        needed_tool_names.add("email_agent")
        logger.info(f"[agent] Detected email keywords - adding email_agent")
    
    # Calendar агент
    if any(kw in query_lower for kw in ["календар", "событи", "встреч", "запланир", "напоминан", "день рождени", "дата"]):
        needed_tool_names.add("calendar_agent")
        logger.info(f"[agent] Detected calendar keywords - adding calendar_agent")
    
    # Tinkoff агент (включая графики акций и тикеры)
    tinkoff_keywords = ["портфель", "акци", "tinkoff", "купи", "продай", "котировк", "график", "цена", "стоимость"]
    # Проверка на тикеры акций (SPCE, AAPL, TSLA и т.д. - обычно 2-5 заглавных букв)
    # ВАЖНО: используем глобальный re из начала файла (строка 4: import re)
    # Не используем локальный _re, чтобы избежать конфликта с import re as _re дальше в функции
    ticker_pattern = r'\b[A-Z]{2,5}\b'
    has_ticker = False
    if last_user_message:
        # Используем глобальный модуль re, импортированный в начале файла
        # Используем __import__ для явного доступа к глобальному модулю
        re_module = __import__('re')
        has_ticker = bool(re_module.search(ticker_pattern, last_user_message))
    
    if any(kw in query_lower for kw in tinkoff_keywords) or has_ticker:
        needed_tool_names.add("tinkoff_agent")
        logger.info(f"[agent] Detected tinkoff keywords or ticker - adding tinkoff_agent (has_ticker={has_ticker})")
    
    # PC агент
    if any(kw in query_lower for kw in ["файл", "папк", "директор", "открой", "запусти", "процесс"]):
        needed_tool_names.add("pc_agent")
        logger.info(f"[agent] Detected pc keywords - adding pc_agent")
    
    # Coder агент
    if any(kw in query_lower for kw in ["код", "python", "скрипт", "программ", "создай код"]):
        needed_tool_names.add("coder_agent")
        logger.info(f"[agent] Detected code keywords - adding coder_agent")
    
    # УНИФИЦИРОВАННАЯ ЛОГИКА ПОИСКА
    # Определяем тип поиска на основе истории сообщений и ключевых слов
    use_simple_search, use_deep_research = _determine_search_type(messages, last_user_message)
    
    if use_simple_search:
        # Простой поиск - добавляем search
        needed_tool_names.add("search")
        logger.info(f"[agent] Detected simple search request (after greeting) - adding search")
    elif use_deep_research:
        # Глубокое исследование - добавляем researcher_agent
        needed_tool_names.add("researcher_agent")
        logger.info(f"[agent] Detected deep research request - adding researcher_agent")
    elif any(kw in query_lower for kw in ["найди", "поиск", "исследован", "узнай", "расскажи о", "расскажи про", "расскажи"]):
        # Fallback: если не определили тип, но есть поисковые ключевые слова - используем глубокого исследователя
        needed_tool_names.add("researcher_agent")
        logger.info(f"[agent] Detected research keywords (fallback) - adding researcher_agent")
    
    # Lawyer агент
    if any(kw in query_lower for kw in ["закон", "кодекс", "статья", "право", "суд", "иск"]):
        needed_tool_names.add("lawyer_agent")
        logger.info(f"[agent] Detected lawyer keywords - adding lawyer_agent")
    
    # Career агент
    if any(kw in query_lower for kw in ["резюме", "вакансия", "работ", "hh.ru", "собеседован"]):
        needed_tool_names.add("career_agent")
        logger.info(f"[agent] Detected career keywords - adding career_agent")
    
    # Фильтруем инструменты на основе классификации И найденных ключевых слов
    # Для simple_question - не загружаем инструменты (ответ только от LLM), ЕСЛИ нет ключевых слов
    # Для complex_question - загружаем поисковые инструменты + найденные агенты
    # Для simple_task - загружаем базовые инструменты + найденные агенты
    # Для complex_task - загружаем все инструменты, НО приоритет найденным агентам
    
    if request_classification == "simple_question":
        # Для простых вопросов не загружаем инструменты, ЕСЛИ нет ключевых слов
        if not needed_tool_names:
            logger.info(f"✅✅✅ agent: Классификация = 'simple_question' без специфичных модулей - НЕ загружаем инструменты")
            logger.info(f"✅✅✅ agent: Запрос пользователя: '{last_user_message}'")
            tools = []
            mcp_tools = []
            logger.info(f"✅✅✅ agent: После фильтрации: tools={len(tools)}, mcp_tools={len(mcp_tools)}")
        else:
            # Есть ключевые слова - загружаем только нужные агенты + базовые инструменты
            logger.info(f"✅✅✅ agent: simple_question НО найдены ключевые слова для модулей - загружаем инструменты")
            
            # Используем унифицированную логику поиска
            use_simple_search, use_deep_research = _determine_search_type(messages, last_user_message)
            
            basic_tool_names = ["read_file", "read_document", "list_archive_contents", "extract_archive", "list_available_tools", "get_tool_details", "python", "shell"]
            # Если нужен простой поиск, добавляем только search
            if use_simple_search:
                basic_tool_names.append("search")
                logger.info(f"[agent] simple_question: Detected simple search - adding search tool only")
            # Если нужен глубокий исследователь, он уже добавлен в needed_tool_names выше
            
            all_needed = needed_tool_names | set(basic_tool_names)
            tools = [tool for tool in tools if isinstance(tool, dict) and tool.get("name") in all_needed]
            mcp_tools = []
            logger.info(f"✅✅✅ agent: После фильтрации: tools={len(tools)}, mcp_tools={len(mcp_tools)}, tool_names={[t.get('name') for t in tools]}")
    elif request_classification == "complex_question":
        # Для сложных вопросов загружаем поисковые инструменты + найденные агенты
        logger.info(f"✅✅✅ agent: Классификация = 'complex_question' - загружаем поисковые + найденные агенты")
        logger.info(f"✅✅✅ agent: Запрос пользователя: '{last_user_message}'")
        search_tool_names = ["search", "get_urls", "researcher_agent", "get_documents"]
        # Объединяем поисковые инструменты с найденными агентами
        all_needed = set(search_tool_names) | needed_tool_names
        tools = [tool for tool in tools if isinstance(tool, dict) and tool.get("name") in all_needed]
        mcp_tools = []  # MCP инструменты не нужны для поиска
        logger.info(f"✅✅✅ agent: После фильтрации: tools={len(tools)}, mcp_tools={len(mcp_tools)}")
    elif request_classification == "simple_task":
        # Для простых задач загружаем базовые инструменты + найденные агенты
        logger.info(f"✅✅✅ agent: Классификация = 'simple_task' - загружаем базовые + найденные агенты")
        logger.info(f"✅✅✅ agent: Запрос пользователя: '{last_user_message}'")
        
        basic_tool_names = ["read_file", "read_document", "list_archive_contents", "extract_archive", "python", "shell"]
        all_needed = needed_tool_names | set(basic_tool_names)
        tools = [tool for tool in tools if isinstance(tool, dict) and tool.get("name") in all_needed]
        logger.info(f"[simple_task] Filtered tools to: {all_needed}")
        
        mcp_tools = []  # MCP инструменты не нужны для простых задач
        logger.info(f"✅✅✅ agent: После фильтрации: tools={len(tools)}, mcp_tools={len(mcp_tools)}")
    else:
        # Для complex_task - загружаем все инструменты, НО приоритет найденным агентам
        # Если найдены специфичные агенты, фильтруем инструменты, оставляя только нужные + базовые
        if needed_tool_names:
            logger.info(f"⚠️⚠️⚠️ agent: Классификация = '{request_classification}' с найденными агентами - фильтруем инструменты")
            logger.info(f"⚠️⚠️⚠️ agent: Запрос пользователя: '{last_user_message}'")
            basic_tool_names = ["read_file", "read_document", "list_archive_contents", "extract_archive", "python", "shell", "search", "get_urls"]
            all_needed = needed_tool_names | set(basic_tool_names)
            tools = [tool for tool in tools if isinstance(tool, dict) and tool.get("name") in all_needed]
            logger.info(f"[complex_task] Filtered tools to: {all_needed} (from {tools_count_before} total)")
        else:
            # Не найдены специфичные агенты - загружаем все инструменты
            logger.info(f"⚠️⚠️⚠️ agent: Классификация = '{request_classification}' без специфичных агентов - загружаем ВСЕ инструменты")
            logger.info(f"⚠️⚠️⚠️ agent: Запрос пользователя: '{last_user_message}'")
        # mcp_tools уже загружены выше
        logger.info(f"⚠️⚠️⚠️ agent: После фильтрации: tools={len(tools)}, mcp_tools={len(mcp_tools)}")
    
    # КРИТИЧЕСКИ ВАЖНО: Обрабатываем все инструменты из tools для исправления type: null
    # MCP инструменты могут попадать в tools через /tools эндпоинт
    processed_tools = []
    for tool in tools:
        try:
            # Проверяем, есть ли parameters в инструменте
            if isinstance(tool, dict) and "parameters" in tool:
                parameters = tool.get("parameters", {})
                if isinstance(parameters, dict):
                    # Применяем transform_schema для исправления type: null
                    parameters = transform_schema(parameters)
                    # Дополнительная проверка
                    if parameters.get("type") != "object":
                        logger.warning(f"⚠️ agent: Исправляю type для инструмента {tool.get('name', 'unknown')} из tools: {parameters.get('type')} -> object")
                        parameters["type"] = "object"
                        if "properties" not in parameters:
                            parameters["properties"] = {}
                    tool = tool.copy()
                    tool["parameters"] = parameters
                    
                    # Финальная проверка перед добавлением
                    if tool.get("parameters", {}).get("type") != "object":
                        logger.error(f"❌ agent: КРИТИЧЕСКАЯ ОШИБКА: type все еще не 'object' для инструмента {tool.get('name', 'unknown')} из tools")
                        tool["parameters"] = {"type": "object", "properties": {}}
            processed_tools.append(tool)
        except Exception as e:
            logger.error(f"❌ agent: Ошибка при обработке инструмента {tool.get('name', 'unknown') if isinstance(tool, dict) else 'unknown'} из tools: {e}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
            # Пропускаем проблемный инструмент, но продолжаем обработку остальных
            continue
    
    # Некоторые провайдеры (например, Xiaomi) валидируют tools и падают, если есть дубликаты имен.
    # Дедуплицируем инструменты по name, сохраняя порядок (берём первое вхождение).
    def _dedupe_tools_by_name(tool_list: list) -> list:
        seen: set[str] = set()
        deduped: list = []
        for t in tool_list:
            if not isinstance(t, dict):
                deduped.append(t)
                continue
            n = t.get("name")
            if not n:
                deduped.append(t)
                continue
            if n in seen:
                logger.warning(f"[agent] duplicate tool name detected, dropping: {n}")
                continue
            seen.add(n)
            deduped.append(t)
        return deduped

    processed_tools = _dedupe_tools_by_name(processed_tools)
    mcp_tools = _dedupe_tools_by_name(mcp_tools)

    # Финальная проверка всех инструментов перед передачей в bind_tools
    all_tools = processed_tools + mcp_tools
    all_tools = _dedupe_tools_by_name(all_tools)
    
    # ОПТИМИЗАЦИЯ: Сокращаем описания инструментов для уменьшения размера контекста
    try:
        from giga_agent.utils.tool_optimizer import optimize_tools_list
        all_tools = optimize_tools_list(all_tools, enable_optimization=True)
    except Exception as opt_err:
        logger.warning(f"[TOOL_OPTIMIZATION] Ошибка оптимизации инструментов: {opt_err}, используем оригинальные")
    for tool in all_tools:
        if isinstance(tool, dict):
            tool_name = tool.get("name", "unknown")
            parameters = tool.get("parameters", {})
            if isinstance(parameters, dict) and parameters.get("type") != "object":
                logger.error(f"❌ agent: КРИТИЧЕСКАЯ ОШИБКА перед bind_tools: инструмент {tool_name} имеет type={parameters.get('type')}, исправляю на 'object'")
                tool["parameters"] = {"type": "object", "properties": {}}
    
    # Логируем количество инструментов для диагностики
    logger.info(f"🔧🔧🔧 agent: Передаю в bind_tools {len(processed_tools)} обычных инструментов + {len(mcp_tools)} MCP инструментов = {len(all_tools)} всего")
    logger.info(f"🔧🔧🔧 agent: Классификация запроса: '{request_classification}'")
    logger.info(f"🔧🔧🔧 agent: Запрос пользователя: '{last_user_message}'")
    if len(all_tools) > 50:
        logger.warning(f"⚠️⚠️⚠️ agent: ВНИМАНИЕ! Загружено {len(all_tools)} инструментов (очень много!)")
        logger.warning(f"⚠️⚠️⚠️ agent: Это может привести к большому расходу токенов!")
        if request_classification != "complex_task":
            logger.error(f"❌❌❌ agent: ОШИБКА! Загружено {len(all_tools)} инструментов при классификации '{request_classification}' (должно быть меньше!)")
    
    # Проверяем, был ли ПОСЛЕДНИЙ шаг именно python REPL.
    # Важно: не переключаемся на REPL-модель просто из-за того, что "когда-то" раньше вызывался python —
    # иначе модель для REPL начинает использоваться для обычного диалога и ловит 429 на free-endpoint'ах.
    def _last_step_was_python_repl(msgs: list) -> bool:
        if not msgs:
            return False
        # Если последнее сообщение — человеческое, значит текущий ответ не является "сразу после tool".
        last = msgs[-1]
        if getattr(last, "type", None) == "human":
            return False
        # Если последнее сообщение — tool, пытаемся связать его с предыдущим AI tool_call=python.
        if isinstance(last, ToolMessage) or getattr(last, "type", None) == "tool":
            tool_call_id = getattr(last, "tool_call_id", None)
            # Ищем ближайшее AI сообщение с tool_calls и совпадающим id/name
            for prev in reversed(msgs[:-1][-10:]):
                if isinstance(prev, AIMessage):
                    tool_calls = getattr(prev, "tool_calls", None) or []
                    for tc in tool_calls:
                        if not isinstance(tc, dict):
                            continue
                        if tc.get("name") != "python":
                            continue
                        if tool_call_id and (tc.get("id") == tool_call_id or tc.get("tool_call_id") == tool_call_id):
                            return True
            # Fallback по контенту (на случай отсутствия id)
            content = str(getattr(last, "content", "")).lower()
            return "python" in content
        return False

    use_repl_model = _last_step_was_python_repl(messages)
    if use_repl_model:
        logger.info("[agent] last step was python REPL -> using REPL model")
    
    # ВАЖНО: Получаем user_id для загрузки персональной модели пользователя
    current_user_id = state.get("user_id")
    if current_user_id and current_user_id not in ["default_user", "anonymous", "guest", "", None]:
        logger.info(f"[agent] Загрузка модели для пользователя: {current_user_id}")
    else:
        current_user_id = None
        logger.debug("[agent] user_id не найден или невалидный, используем глобальную модель")
    
    # Выбираем модель:
    # - для REPL используем GIGA_AGENT_LLM_REPL (tag="repl")
    # - иначе используем policy по task_type (например, RETRIEVE -> tag="fast", CODE_INTERPRET -> tag="coder"),
    #   с безопасным fallback на основную модель.
    if use_repl_model:
        current_llm = load_llm(tag="repl", is_main=True, user_id=current_user_id)
        model_name = get_model_name(tag="repl")
        repl_model_str = os.getenv("GIGA_AGENT_LLM_REPL", "не установлена")
        logger.info(f"[agent] REPL model: {repl_model_str}")
    else:
        from giga_agent.utils.llm import choose_llm_tag_for_task_type
        chosen_tag = choose_llm_tag_for_task_type(task_type)
        if chosen_tag:
            current_llm = load_llm(tag=chosen_tag, is_main=True, user_id=current_user_id)
            model_name = get_model_name(tag=chosen_tag)
            logger.info(f"[agent] task_type routing: task_type={task_type} -> tag={chosen_tag}")
        else:
            # ВАЖНО: Загружаем модель с user_id для использования персональной модели
            current_llm = load_llm(tag=None, is_main=True, user_id=current_user_id)
            model_name = get_model_name()
            main_model_str = os.getenv("GIGA_AGENT_LLM", "не установлена")
            # Логируем тип загруженной LLM для диагностики
            llm_type = type(current_llm).__name__
            llm_model = getattr(current_llm, 'model_name', None) or getattr(current_llm, 'model', None) or "неизвестно"
            logger.info(f"[agent] Используется модель: {main_model_str} (user_id={current_user_id}) -> LLM тип: {llm_type}, модель: {llm_model}")
    
    # Сохраняем название модели в state для использования в tool_call
    state["current_model_name"] = model_name
    
    # ========== ВЫБОР ПРОМПТА (оптимизированный или полный) ==========
    # Если включена оптимизация промпта, используем модульную систему
    # Это экономит до 97% токенов системного промпта
    if PROMPT_OPTIMIZATION_ENABLED and last_user_message:
        try:
            # Извлекаем чистый запрос пользователя из <task> тега для определения модулей
            # last_user_message может содержать <task>запрос</task> и <user_info>...</user_info>
            import re as _re
            clean_query_match = _re.search(r'<task>(.*?)</task>', last_user_message, _re.IGNORECASE | _re.DOTALL)
            if clean_query_match:
                clean_query = clean_query_match.group(1).strip()
            else:
                # Если нет тега <task>, берем первые 200 символов до <user_info>
                clean_query = _re.sub(r'<user_info>.*', '', last_user_message, flags=_re.IGNORECASE | _re.DOTALL).strip()[:200]
            
            # КРИТИЧЕСКИ ВАЖНО: Проверяем на простые приветствия ПЕРЕД всеми остальными проверками
            # Это нужно для максимальной экономии токенов
            clean_query_lower = clean_query.lower().strip()
            simple_greetings = ["привет", "здравствуй", "добрый день", "доброе утро", "добрый вечер", 
                               "как дела", "как поживаешь", "что нового", "помоги", "помощь", 
                               "спасибо", "благодарю", "ок", "хорошо", "понял", "да", "нет"]
            words_count = len(clean_query_lower.split())
            is_simple_greeting = words_count <= 5 and any(greeting in clean_query_lower for greeting in simple_greetings)
            
            # Получаем классификацию запроса для оптимизации промпта
            request_classification = state.get("request_classification", "complex_task")
            
            # Если это простое приветствие, принудительно устанавливаем simple_question
            if is_simple_greeting:
                request_classification = "simple_question"
                logger.info(f"[PROMPT_OPTIMIZATION] Detected simple greeting - forcing simple_question classification")
            
            # Определяем какие модули нужны на основе ЧИСТОГО запроса и классификации
            modules = detect_modules_needed(clean_query, request_classification=request_classification)
            logger.info(f"[PROMPT_OPTIMIZATION] Clean query: '{clean_query[:50]}...', classification: '{request_classification}', модули: {modules}")
            print(f"[PROMPT_OPTIMIZATION] Query: '{clean_query[:30]}...' Classification: '{request_classification}' Modules: {modules}")
            
            # Получаем user_instructions для промпта (user_secrets и rag_info добавляются через payload)
            _user_instructions = get_user_notes(state)
            _rag_info = get_rag_info(state.get("collections", []))
            
            # Для simple_question или если modules пусто (простое приветствие) не добавляем RAG и user_instructions (экономия токенов)
            if request_classification == "simple_question" or len(modules) == 0 or is_simple_greeting:
                _user_instructions = ""
                _rag_info = ""
                reason = "simple_question" if request_classification == "simple_question" else ("simple greeting" if is_simple_greeting else "empty modules")
                logger.info(f"[PROMPT_OPTIMIZATION] {reason} - skipping RAG and user_instructions for token savings")
            
            current_prompt = create_optimized_prompt(
                user_query=clean_query,
                user_instructions=_user_instructions,
                user_secrets="",  # Секреты добавляются через payload, не дублируем
                rag_info=_rag_info,
                request_classification=request_classification,
            )
        except Exception as e:
            logger.warning(f"[PROMPT_OPTIMIZATION] Ошибка при создании оптимизированного промпта: {e}, используем полный")
            import traceback
            traceback.print_exc()
            current_prompt = prompt
    else:
        current_prompt = prompt
        if not PROMPT_OPTIMIZATION_ENABLED:
            logger.debug("[PROMPT_OPTIMIZATION] Оптимизация отключена (PROMPT_OPTIMIZATION=0)")
    # ========== КОНЕЦ ВЫБОРА ПРОМПТА ==========
    
    # Настраиваем retry для обработки таймаутов и сетевых ошибок
    # Используем стандартный retry с увеличенным количеством попыток для таймаутов
    # ОПТИМИЗАЦИЯ: Для simple_question не используем bind_tools (инструменты не нужны)
    # НО если инструменты загружены (all_tools не пуст), значит они нужны - используем bind_tools
    # Получаем request_classification из state для проверки
    request_classification_for_bind = state.get("request_classification", "complex_task")
    if request_classification_for_bind == "simple_question" and len(all_tools) == 0:
        logger.info(f"[agent] OPTIMIZATION: simple_question без инструментов - НЕ используем bind_tools (экономия токенов)")
        print(f"[agent] OPTIMIZATION: simple_question - skipping bind_tools for token savings")
        ch = (current_prompt | current_llm).with_retry(stop_after_attempt=3)
    else:
        if request_classification_for_bind == "simple_question" and len(all_tools) > 0:
            logger.info(f"[agent] simple_question с инструментами ({len(all_tools)} tools) - используем bind_tools")
        else:
            logger.info(f"[agent] Classification: '{request_classification_for_bind}' - using bind_tools with {len(all_tools)} tools")
        ch = (
            current_prompt | current_llm.bind_tools(all_tools, parallel_tool_calls=False)
        ).with_retry(stop_after_attempt=3)
    # Очищаем историю сообщений для DeepSeek API
    # DeepSeek требует reasoning_content для assistant сообщений в thinking mode
    # Создаем новые объекты сообщений с правильной структурой вместо модификации in-place
    cleaned_messages = []
    
    # Проверяем, используется ли DeepSeek модель
    is_deepseek = is_deepseek_model()
    
    # Функция для гарантированной установки reasoning_content
    def ensure_reasoning_content(msg, idx):
        """Гарантирует наличие reasoning_content в assistant сообщении"""
        try:
            # Проверяем, является ли сообщение assistant сообщением
            is_ai_message = (
                (hasattr(msg, 'type') and msg.type == "ai") or
                isinstance(msg, AIMessage) or
                (hasattr(msg, '__class__') and 'AIMessage' in str(msg.__class__))
            )
            
            if is_ai_message:
                # Получаем existing additional_kwargs или создаем новый dict
                existing_kwargs = getattr(msg, 'additional_kwargs', None)
                if existing_kwargs is None:
                    existing_kwargs = {}
                if not isinstance(existing_kwargs, dict):
                    existing_kwargs = {}
                
                # КРИТИЧЕСКИ ВАЖНО: Для DeepSeek API reasoning_content должен быть
                # в additional_kwargs. Устанавливаем пустую строку, если отсутствует
                if "reasoning_content" not in existing_kwargs:
                    existing_kwargs["reasoning_content"] = ""
                    logger.debug(f"🔧 Установлен reasoning_content для сообщения {idx} (был отсутствует)")
                
                # Устанавливаем additional_kwargs обратно в сообщение
                msg.additional_kwargs = existing_kwargs
                return True
        except Exception as e:
            logger.warning(f"⚠️  Ошибка при установке reasoning_content для сообщения {idx}: {e}")
        return False
    
    # Обрабатываем сообщения только если используется DeepSeek модель
    if is_deepseek:
        logger.debug(f"🔍 DeepSeek модель обнаружена, обрабатываем {len(messages)} сообщений для reasoning_content")
        
        for idx, msg in enumerate(messages):
            try:
                # Проверяем, является ли сообщение assistant сообщением
                # Проверяем как через type, так и через isinstance для надежности
                is_ai_message = (
                    (hasattr(msg, 'type') and msg.type == "ai") or
                    isinstance(msg, AIMessage) or
                    (hasattr(msg, '__class__') and 'AIMessage' in str(msg.__class__))
                )
                
                if is_ai_message:
                    # Получаем existing additional_kwargs или создаем новый dict
                    existing_kwargs = getattr(msg, 'additional_kwargs', None)
                    if existing_kwargs is None:
                        existing_kwargs = {}
                    if not isinstance(existing_kwargs, dict):
                        existing_kwargs = {}
                    
                    # Создаем копию additional_kwargs с reasoning_content
                    new_kwargs = copy.deepcopy(existing_kwargs)
                    
                    # КРИТИЧЕСКИ ВАЖНО: Для DeepSeek API reasoning_content должен быть
                    # как в additional_kwargs, так и на верхнем уровне сообщения при сериализации
                    # Устанавливаем reasoning_content в additional_kwargs
                    if "reasoning_content" not in new_kwargs:
                        new_kwargs["reasoning_content"] = ""
                        logger.debug(f"🔧 Сообщение {idx}: reasoning_content был отсутствует, установлен пустой")
                    
                    # Получаем content безопасно
                    msg_content = getattr(msg, 'content', '') or ''
                    
                    # Создаем новый AIMessage с правильной структурой
                    # Патч в deepseek_patch.py обработает reasoning_content при создании payload
                    new_msg = AIMessage(
                        content=msg_content,
                        additional_kwargs=new_kwargs,
                        tool_calls=getattr(msg, 'tool_calls', None),
                        tool_call_id=getattr(msg, 'tool_call_id', None),
                        id=getattr(msg, 'id', None),
                        response_metadata=getattr(msg, 'response_metadata', None) or {},
                    )
                    
                    # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Убеждаемся, что reasoning_content установлен
                    # Проверяем и устанавливаем еще раз после создания объекта
                    if not hasattr(new_msg, 'additional_kwargs') or not isinstance(new_msg.additional_kwargs, dict):
                        new_msg.additional_kwargs = {}
                    if "reasoning_content" not in new_msg.additional_kwargs:
                        new_msg.additional_kwargs["reasoning_content"] = ""
                        logger.debug(f"🔧 Сообщение {idx}: reasoning_content установлен после создания AIMessage")
                    
                    # ФИНАЛЬНАЯ ПРОВЕРКА перед добавлением
                    if "reasoning_content" not in new_msg.additional_kwargs:
                        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Сообщение {idx} все еще не имеет reasoning_content после всех проверок!")
                        new_msg.additional_kwargs["reasoning_content"] = ""
                    
                    cleaned_messages.append(new_msg)
                    logger.debug(f"✅ Обработано assistant сообщение {idx}: reasoning_content в additional_kwargs={new_msg.additional_kwargs.get('reasoning_content', 'ОТСУТСТВУЕТ')}")
                elif isinstance(msg, ToolMessage) or (hasattr(msg, 'type') and msg.type == "tool"):
                    # Обработка ToolMessage для DeepSeek API
                    # КРИТИЧЕСКИ ВАЖНО: ToolMessage не должен иметь reasoning_content
                    # Но нужно убедиться, что он имеет правильный формат для DeepSeek API
                    
                    # Получаем content безопасно
                    tool_content = getattr(msg, 'content', '') or ''
                    
                    # Получаем tool_call_id
                    tool_call_id = getattr(msg, 'tool_call_id', '')
                    
                    # Очищаем additional_kwargs от полей, которые могут вызвать проблемы
                    existing_kwargs = getattr(msg, 'additional_kwargs', None)
                    if existing_kwargs is None:
                        existing_kwargs = {}
                    if not isinstance(existing_kwargs, dict):
                        existing_kwargs = {}
                    
                    # Создаем очищенный additional_kwargs
                    cleaned_kwargs = {}
                    
                    # Оставляем только tool_attachments, если они есть (для фронтенда)
                    if 'tool_attachments' in existing_kwargs:
                        cleaned_kwargs['tool_attachments'] = existing_kwargs['tool_attachments']
                    
                    # УДАЛЯЕМ reasoning_content, если он случайно попал в ToolMessage
                    if 'reasoning_content' in existing_kwargs:
                        logger.warning(f"⚠️  ToolMessage {idx}: обнаружен reasoning_content в additional_kwargs, удаляем")
                    
                    # Создаем новый ToolMessage с очищенной структурой
                    new_tool_msg = ToolMessage(
                        content=tool_content,
                        tool_call_id=tool_call_id,
                        additional_kwargs=cleaned_kwargs,
                        id=getattr(msg, 'id', None),
                    )
                    
                    cleaned_messages.append(new_tool_msg)
                    logger.debug(f"✅ Обработано tool сообщение {idx}: content_length={len(str(tool_content))}, tool_call_id={tool_call_id[:20] if tool_call_id else 'N/A'}")
                else:
                    # Для других типов сообщений (human, system) просто добавляем как есть
                    cleaned_messages.append(msg)
            except Exception as e:
                # Если произошла ошибка при обработке сообщения, логируем и добавляем оригинал
                logger.error(f"❌ Ошибка при обработке сообщения {idx} в истории: {e}, тип: {type(msg)}")
                # Если это assistant сообщение, все равно пытаемся добавить reasoning_content
                if is_deepseek:
                    ensure_reasoning_content(msg, idx)
                cleaned_messages.append(msg)
        
        # ФИНАЛЬНАЯ ПРОВЕРКА: Убеждаемся, что ВСЕ assistant сообщения имеют reasoning_content
        # Это критически важно для DeepSeek API
        for idx, msg in enumerate(cleaned_messages):
            is_ai_msg = (
                (hasattr(msg, 'type') and msg.type == "ai") or
                isinstance(msg, AIMessage) or
                (hasattr(msg, '__class__') and 'AIMessage' in str(msg.__class__))
            )
            if is_ai_msg:
                if not hasattr(msg, 'additional_kwargs') or not isinstance(msg.additional_kwargs, dict):
                    msg.additional_kwargs = {}
                if "reasoning_content" not in msg.additional_kwargs:
                    logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Сообщение {idx} в финальной проверке не имеет reasoning_content!")
                    msg.additional_kwargs["reasoning_content"] = ""
                else:
                    logger.debug(f"✅ Финальная проверка сообщения {idx}: reasoning_content присутствует")
    else:
        # Если не DeepSeek, просто используем сообщения как есть
        cleaned_messages = messages
    
    # ВАЖНО: Валидация пар tool_call/tool_response для всех моделей
    # Особенно критично для Mistral API, который требует соответствия количества tool_calls и responses
    # Ошибка: "Not the same number of function calls and responses"
    # Также исправляет некорректные форматы tool_calls для проблемных моделей (xiaomi/mimo и др.)
    try:
        from giga_agent.utils.messages import sanitize_message_history
        original_count = len(cleaned_messages)
        # Передаем model_name для определения нужно ли исправлять форматы tool_calls
        cleaned_messages = sanitize_message_history(cleaned_messages, model_id=model_name)
        if len(cleaned_messages) != original_count:
            logger.info(f"[agent] Санитизация истории: {original_count} -> {len(cleaned_messages)} сообщений")
    except Exception as e:
        logger.warning(f"[agent] Ошибка при санитизации истории сообщений: {e}")
    
    # Логируем информацию о сообщениях перед отправкой в API (только для DeepSeek)
    if is_deepseek:
        msg_types = {}
        for msg in cleaned_messages:
            msg_type = getattr(msg, 'type', 'unknown')
            msg_types[msg_type] = msg_types.get(msg_type, 0) + 1
        logger.info(f"📤 Отправка в DeepSeek API: {len(cleaned_messages)} сообщений, типы: {msg_types}")
        
        # Логируем детали tool сообщений
        tool_msgs = [msg for msg in cleaned_messages if isinstance(msg, ToolMessage) or (hasattr(msg, 'type') and msg.type == "tool")]
        if tool_msgs:
            logger.info(f"📤 Tool сообщений в запросе: {len(tool_msgs)}")
            for idx, tool_msg in enumerate(tool_msgs):
                content_len = len(str(getattr(tool_msg, 'content', '')))
                tool_call_id = getattr(tool_msg, 'tool_call_id', 'N/A')
                logger.debug(f"  ToolMessage {idx}: content_len={content_len}, tool_call_id={tool_call_id[:30] if tool_call_id != 'N/A' else 'N/A'}")
    
    def _is_openrouter_rate_limit(exc: Exception) -> bool:
        try:
            import openai  # type: ignore
            if isinstance(exc, openai.RateLimitError):
                return True
        except Exception:
            pass
        s = str(exc)
        return ("Error code: 429" in s) or ("RateLimitError" in type(exc).__name__)

    def _get_openrouter_model_id_from_env(env_key: str) -> Optional[str]:
        val = os.getenv(env_key, "")
        if not val:
            return None
        if val.startswith("openrouter:"):
            return val.replace("openrouter:", "", 1)
        return None

    payload = {
        "messages": cleaned_messages,
        "current_date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "rag_info": get_rag_info(state.get("collections", [])),
        "user_instructions": get_user_notes(state),
        "user_secrets": await get_user_secrets(state),
    }

    def _is_openrouter_data_policy_error(exc: Exception) -> bool:
        """Проверка на ошибку политики данных OpenRouter (404)"""
        s = str(exc)
        # Проверяем различные варианты ошибки
        is_data_policy = (
            "data policy" in s.lower() or 
            "No endpoints found matching" in s or
            "No endpoints found" in s or
            ("404" in s and "endpoints" in s.lower()) or
            ("404" in s and "policy" in s.lower()) or
            "Free model publication" in s
        )
        if is_data_policy:
            logger.warning(f"[agent] Обнаружена ошибка data policy: {s[:200]}")
        return is_data_policy
    
    def _fallback_to_startup_model(env_key: str, tag: Optional[str], error_msg: str):
        """Fallback на стартовую модель при критических ошибках"""
        # Приоритет fallback моделей:
        # 1. GIGA_AGENT_LLM_FALLBACK - явно указанная fallback модель
        # 2. GIGA_AGENT_LLM_STARTUP - стартовая модель
        # 3. GIGA_AGENT_LLM_DEFAULT - модель по умолчанию
        # 4. Devstral как последний вариант
        startup_model = (
            os.getenv("GIGA_AGENT_LLM_FALLBACK") or 
            os.getenv("GIGA_AGENT_LLM_STARTUP") or 
            os.getenv("GIGA_AGENT_LLM_DEFAULT") or
            "openrouter:mistralai/devstral-2512:free"
        )
        
        logger.warning(f"[agent] {error_msg}. Fallback на стартовую модель: {startup_model}")
        os.environ[env_key] = startup_model
        
        try:
            from giga_agent.utils.llm import reset_llm_singleton, clear_user_openrouter_model
            reset_llm_singleton(tag=tag, is_main=True)
            # Очищаем сохраненную модель пользователя, чтобы не повторять ошибку
            user_id = state.get("user_id")
            if user_id and user_id not in ["default_user", "anonymous", "guest", "", None]:
                clear_user_openrouter_model(user_id)
                logger.info(f"[agent] Очищена сохраненная модель для пользователя {user_id}")
        except Exception as reset_err:
            logger.error(f"[agent] Ошибка при сбросе модели: {reset_err}")
        
        return startup_model

    # ========== АНАЛИЗ КОНТЕКСТА ==========
    # Анализируем размер контекста перед отправкой в LLM
    try:
        from giga_agent.utils.context_analyzer import analyze_and_log_context
        
        # Определяем какой промпт используется
        if PROMPT_OPTIMIZATION_ENABLED and last_user_message:
            # Получаем оптимизированный промпт для анализа
            _opt_prompt = build_optimized_prompt(
                query=last_user_message,
                current_date=datetime.now().strftime("%d.%m.%Y %H:%M"),
                rag_info=payload.get("rag_info", ""),
                user_instructions=payload.get("user_instructions", ""),
                user_secrets=payload.get("user_secrets", ""),
                language=LANG,
                repl_inner_tools=generate_repl_tools_description(),
            )
            _sys_prompt = _opt_prompt
            prompt_type = "OPTIMIZED"
        else:
            from giga_agent.prompts.main_prompt import SYSTEM_PROMPT as _SYS_PROMPT
            _sys_prompt = _SYS_PROMPT
            prompt_type = "FULL"
        
        # Получаем список инструментов для анализа
        tools_for_analysis = all_tools if 'all_tools' in dir() else []
        
        analyze_and_log_context(
            messages=cleaned_messages,
            system_prompt=_sys_prompt,
            user_instructions=payload.get("user_instructions", "") if prompt_type == "FULL" else "",
            rag_info=payload.get("rag_info", "") if prompt_type == "FULL" else "",
            user_secrets=payload.get("user_secrets", "") if prompt_type == "FULL" else "",
            tools=tools_for_analysis,
            model_name=f"{model_name} [{prompt_type}]",
            user_query=last_user_message[:100] if last_user_message else "",
            save=True
        )
    except Exception as ctx_err:
        logger.warning(f"[CONTEXT_ANALYSIS] Ошибка анализа контекста: {ctx_err}")
    # ========== КОНЕЦ АНАЛИЗА КОНТЕКСТА ==========

    try:
        message = await ch.ainvoke(payload)
    except Exception as e:
        # Логируем все ошибки для диагностики
        logger.error(f"[agent] Ошибка при вызове LLM: {type(e).__name__}: {str(e)[:500]}")
        
        # Детальное логирование ошибки для DeepSeek
        if is_deepseek:
            logger.error(f"❌ ОШИБКА при вызове DeepSeek API: {type(e).__name__}: {str(e)}")
            logger.error(f"❌ Количество сообщений в запросе: {len(cleaned_messages)}")
            # Логируем структуру последних сообщений
            for idx, msg in enumerate(cleaned_messages[-5:], start=len(cleaned_messages)-5):
                msg_type = getattr(msg, 'type', 'unknown')
                logger.error(f"  Сообщение {idx}: type={msg_type}, class={type(msg).__name__}")
                if isinstance(msg, ToolMessage) or msg_type == "tool":
                    content_preview = str(getattr(msg, 'content', ''))[:100]
                    logger.error(f"    content preview: {content_preview}...")
                    logger.error(f"    tool_call_id: {getattr(msg, 'tool_call_id', 'N/A')}")
                    logger.error(f"    additional_kwargs keys: {list(getattr(msg, 'additional_kwargs', {}).keys())}")
        
        # Обработка ошибки политики данных OpenRouter (404)
        # Эта ошибка возникает, когда модель требует настройки политики конфиденциальности
        if _is_openrouter_data_policy_error(e):
            logger.error(f"[agent] OpenRouter data policy error: {e}")
            
            # Определяем env_key и tag
            env_key_in_use = "GIGA_AGENT_LLM_REPL" if use_repl_model else "GIGA_AGENT_LLM"
            tag_in_use = "repl" if use_repl_model else None
            
            # Fallback на стартовую модель
            startup_model = _fallback_to_startup_model(
                env_key_in_use, 
                tag_in_use, 
                f"Модель требует настройки политики конфиденциальности OpenRouter"
            )
            
            # Пробуем снова со стартовой моделью (без user_id, так как это fallback)
            try:
                from giga_agent.utils.llm import load_llm as _load_llm
                fallback_llm = _load_llm(tag=tag_in_use, is_main=True, user_id=None)
                ch_fallback = (prompt | fallback_llm.bind_tools(all_tools, parallel_tool_calls=False)).with_retry(stop_after_attempt=2)
                message = await ch_fallback.ainvoke(payload)
                state["current_model_name"] = get_model_name(tag=tag_in_use)
                logger.info(f"[agent] Успешно переключено на fallback модель: {startup_model}")
            except Exception as fallback_err:
                logger.error(f"[agent] Fallback модель тоже не работает: {fallback_err}")
                raise
        # OpenRouter 429: пауза 60с -> повтор -> если снова 429, перебираем free модели по списку.
        elif not _is_openrouter_rate_limit(e):
            raise

        logger.warning(f"[agent] OpenRouter rate limited (first): {type(e).__name__}: {e}")

        sleep_s = int(os.getenv("OPENROUTER_RATE_LIMIT_SLEEP_SECONDS", "60"))
        await asyncio.sleep(float(sleep_s))

        try:
            message = await ch.ainvoke(payload)
        except Exception as e2:
            if not _is_openrouter_rate_limit(e2):
                raise

            logger.warning(f"[agent] OpenRouter rate limited (second): {type(e2).__name__}: {e2}")

            # Определяем какой env_key сейчас используется и какой tag для load_llm нужен
            env_key_in_use = "GIGA_AGENT_LLM_REPL" if use_repl_model else "GIGA_AGENT_LLM"
            tag_in_use = "repl" if use_repl_model else None
            current_model_id = _get_openrouter_model_id_from_env(env_key_in_use)

            # Сколько моделей максимум перебираем (за одну попытку ответа)
            max_models = int(os.getenv("OPENROUTER_FALLBACK_MAX_MODELS", "5"))

            next_model_id = None
            try:
                from giga_agent.utils.llm import get_openrouter_model_manager, reset_llm_singleton
                mgr = get_openrouter_model_manager()
                if mgr and current_model_id:
                    # Быстро "выключаем" модель, даже если OPENROUTER_MAX_FAILURES>1:
                    # добиваем счётчик до max_failures, чтобы она стала недоступной для get_available_model().
                    for _ in range(max(1, mgr.max_failures)):
                        mgr.record_model_failure(current_model_id, error=str(e2))
                    next_model_id = mgr.get_available_model(preferred_model=None)

                    # Перебираем дальше, если next_model_id совпал (на случай странного состояния)
                    tried = 0
                    while next_model_id == current_model_id and tried < max_models:
                        for _ in range(max(1, mgr.max_failures)):
                            mgr.record_model_failure(current_model_id, error="rate_limited")
                        next_model_id = mgr.get_available_model(preferred_model=None)
                        tried += 1

                    if next_model_id:
                        os.environ[env_key_in_use] = f"openrouter:{next_model_id}"
                        # Сбрасываем кэш, иначе load_llm вернет старый инстанс
                        reset_llm_singleton(tag=tag_in_use, is_main=True)

            except Exception as switch_err:
                logger.warning(f"[agent] model switching failed: {switch_err}")

            # Если не удалось выбрать следующую модель — fallback для REPL на MAIN (без перебора)
            if not next_model_id and use_repl_model:
                logger.warning("[agent] no next free model for REPL; fallback to MAIN model after 429")
                # ВАЖНО: Загружаем свежую модель вместо использования глобальной переменной llm
                # Это гарантирует, что используется актуальная модель из Redis
                main_llm = load_llm(tag=None, is_main=True, user_id=current_user_id)
                ch_main = (prompt | main_llm.bind_tools(all_tools, parallel_tool_calls=False)).with_retry(stop_after_attempt=2)
                message = await ch_main.ainvoke(payload)
                state["current_model_name"] = get_model_name()
                # успешно — выходим
            else:
                if not next_model_id:
                    raise

                logger.warning(f"[agent] switching to next free model: {next_model_id}")

                # Загружаем новый LLM и пробуем (до max_models, на случай если и он 429)
                last_exc: Optional[Exception] = None
                for attempt in range(max_models):
                    try:
                        from giga_agent.utils.llm import load_llm as _load_llm
                        # При fallback на другие модели не используем user_id (это аварийное переключение)
                        current_llm = _load_llm(tag=tag_in_use, is_main=True, user_id=None)
                        ch_switched = (prompt | current_llm.bind_tools(all_tools, parallel_tool_calls=False)).with_retry(stop_after_attempt=2)
                        message = await ch_switched.ainvoke(payload)
                        # сохраняем название модели в state
                        state["current_model_name"] = get_model_name(tag=tag_in_use)
                        last_exc = None
                        break
                    except Exception as e3:
                        last_exc = e3
                        if not _is_openrouter_rate_limit(e3):
                            raise
                        # 429 снова — следующая модель
                        try:
                            from giga_agent.utils.llm import get_openrouter_model_manager, reset_llm_singleton
                            mgr = get_openrouter_model_manager()
                            bad = _get_openrouter_model_id_from_env(env_key_in_use)
                            if mgr and bad:
                                for _ in range(max(1, mgr.max_failures)):
                                    mgr.record_model_failure(bad, error=str(e3))
                                nm = mgr.get_available_model(preferred_model=None)
                                if nm:
                                    os.environ[env_key_in_use] = f"openrouter:{nm}"
                                    reset_llm_singleton(tag=tag_in_use, is_main=True)
                                    logger.warning(f"[agent] 429 again, switching to next free model: {nm}")
                        except Exception:
                            pass
                        await asyncio.sleep(1.0)

                if last_exc is not None:
                    raise last_exc
    message.additional_kwargs.pop("function_call", None)
    message.additional_kwargs["rendered"] = True
    
    # ВАЖНО: Исправляем некорректные форматы tool_calls для проблемных моделей
    # Некоторые модели (xiaomi/mimo, qwen и др.) выводят tool_calls в текстовом формате
    # вместо структурированного JSON, например: <function=name> <parameter=key>value</parameter>
    try:
        from giga_agent.utils.messages import fix_malformed_ai_message
        if isinstance(message, AIMessage) or (hasattr(message, 'type') and message.type == "ai"):
            original_tool_calls = getattr(message, 'tool_calls', None) or []
            message = fix_malformed_ai_message(message, model_id=model_name)
            new_tool_calls = getattr(message, 'tool_calls', None) or []
            if not original_tool_calls and new_tool_calls:
                logger.info(f"[agent] Исправлены некорректные tool_calls из текста: {len(new_tool_calls)} вызовов")
    except Exception as e:
        logger.warning(f"[agent] Ошибка при исправлении некорректных tool_calls: {e}")
    
    # КРИТИЧЕСКИ ВАЖНО: Нормализуем tool call IDs для Mistral API через OpenRouter
    # Mistral требует, чтобы tool call IDs были длиной 9 символов (a-z, A-Z, 0-9)
    # LangChain может генерировать IDs в неправильном формате (например, "123")
    llm_str = os.getenv("GIGA_AGENT_LLM", "")
    is_openrouter_mistral = llm_str.startswith("openrouter:") and "mistral" in llm_str.lower()
    if is_openrouter_mistral and hasattr(message, 'tool_calls') and message.tool_calls:
        logger.info(f"🔧 Нормализация tool call IDs для Mistral API (найдено {len(message.tool_calls)} tool calls)")
        normalized_tool_calls = []
        for tool_call in message.tool_calls:
            tool_call_id = tool_call.get("id", "")
            # Проверяем, соответствует ли ID требованиям Mistral
            if not (tool_call_id and len(tool_call_id) == 9 and tool_call_id.isalnum()):
                # Генерируем правильный ID
                new_id = generate_mistral_tool_call_id()
                logger.warning(f"⚠️ Tool call ID '{tool_call_id}' не соответствует требованиям Mistral, заменяю на '{new_id}'")
                tool_call = tool_call.copy() if isinstance(tool_call, dict) else dict(tool_call)
                tool_call["id"] = new_id
            normalized_tool_calls.append(tool_call)
        # Заменяем tool_calls на нормализованные
        message.tool_calls = normalized_tool_calls
        logger.debug(f"✅ Tool call IDs нормализованы для Mistral API")
    
    # КРИТИЧЕСКИ ВАЖНО: Для DeepSeek API 3.2 reasoning_content должен быть в additional_kwargs
    # для правильной обработки в следующем раунде диалога
    if is_deepseek:
        # Убеждаемся, что новое сообщение от агента имеет reasoning_content
        if not hasattr(message, 'additional_kwargs') or not isinstance(message.additional_kwargs, dict):
            message.additional_kwargs = {}
        
        # Если reasoning_content отсутствует, устанавливаем пустую строку
        if "reasoning_content" not in message.additional_kwargs:
            message.additional_kwargs["reasoning_content"] = ""
            logger.debug("🔧 Установлен reasoning_content для нового сообщения от агента")
    
    # Обрабатываем reasoning_content от DeepSeek API
    # Если модель вернула reasoning_content, добавляем его в content для отображения на фронтенде
    # Также гарантируем, что reasoning_content присутствует в additional_kwargs для истории
    try:
        # Проверяем, что это AIMessage и content является строкой
        if hasattr(message, 'type') and message.type == "ai":
            # Инициализируем additional_kwargs если его нет
            if not hasattr(message, 'additional_kwargs') or not isinstance(message.additional_kwargs, dict):
                message.additional_kwargs = {}
            
            # Безопасно получаем reasoning_content
            reasoning_content = message.additional_kwargs.get("reasoning_content", "")
            
            # Убеждаемся, что message.content является строкой
            if not isinstance(message.content, str):
                message.content = str(message.content) if message.content else ""
            
            # Проверяем, весь ли текст находится внутри <thinking></thinking>
            # Если да, и есть разделитель "---", то применяем его для разделения рассуждений и основного ответа
            import re
            thinking_match = re.search(r'<thinking>([\s\S]*?)</thinking>', message.content)
            is_entirely_in_thinking = (
                thinking_match and 
                thinking_match.group(0).strip() == message.content.strip()
            )
            
            # Применяем разделитель "---" только если весь текст в <thinking>
            if is_entirely_in_thinking and "---" in message.content:
                # Извлекаем содержимое из <thinking>
                thinking_content = thinking_match.group(1).strip()
                # Разделяем по "---"
                parts = thinking_content.split("---", 1)
                reasoning_part = parts[0].strip()
                main_content = parts[1].strip() if len(parts) > 1 else ""
                
                if reasoning_part and main_content:
                    # Форматируем рассуждения в теги <thinking> и добавляем основной ответ
                    thinking_block = f"<thinking>\n{reasoning_part}\n</thinking>\n\n"
                    message.content = thinking_block + main_content
                    # Сохраняем reasoning_part в additional_kwargs для истории
                    message.additional_kwargs["reasoning_content"] = reasoning_part
                    logger.debug("✅ Обнаружен разделитель '---' внутри <thinking> - рассуждения выделены в блок <thinking>")
                elif reasoning_part:
                    # Если есть только рассуждения, оставляем как есть
                    message.content = message.content
                else:
                    # Если до "---" ничего нет, убираем <thinking> и оставляем только основной контент
                    message.content = main_content
            # Проверяем, что reasoning_content является строкой и не пустой
            elif reasoning_content and isinstance(reasoning_content, str) and reasoning_content.strip():
                # КРИТИЧЕСКИ ВАЖНО: Если content пустой или содержит только reasoning_content,
                # значит весь ответ попал в reasoning_content (например, после обобщения)
                # В этом случае reasoning_content становится основным контентом
                content_is_empty = not message.content or message.content.strip() == ""
                content_is_only_reasoning = message.content.strip() == reasoning_content.strip()
                
                if content_is_empty or content_is_only_reasoning:
                    # Весь ответ в reasoning_content - делаем его основным контентом
                    # и не добавляем блок <thinking>
                    message.content = reasoning_content.strip()
                    # Очищаем reasoning_content, так как он теперь в основном контенте
                    message.additional_kwargs["reasoning_content"] = ""
                    logger.debug("✅ Обнаружен случай, когда весь ответ в reasoning_content - перенесен в основной контент")
                else:
                    # Обычный случай: есть и reasoning_content, и основной контент
                    # Форматируем reasoning_content в теги <thinking> и добавляем в начало content
                    thinking_block = f"<thinking>\n{reasoning_content.strip()}\n</thinking>\n\n"
                    # Добавляем только если его еще нет в content
                    if "<thinking>" not in message.content:
                        message.content = thinking_block + message.content
                    # Сохраняем reasoning_content в additional_kwargs для истории
                    message.additional_kwargs["reasoning_content"] = reasoning_content
            else:
                # Если reasoning_content отсутствует или пуст, устанавливаем пустую строку
                # Это необходимо для DeepSeek API, чтобы избежать ошибки "Missing reasoning_content field"
                if "reasoning_content" not in message.additional_kwargs:
                    message.additional_kwargs["reasoning_content"] = ""
    except Exception as e:
        # Если произошла ошибка при обработке reasoning_content, логируем и продолжаем
        logger.warning(f"⚠️  Ошибка при обработке reasoning_content: {e}")
        # Убеждаемся, что reasoning_content присутствует даже при ошибке
        if hasattr(message, 'type') and message.type == "ai":
            if not hasattr(message, 'additional_kwargs') or not isinstance(message.additional_kwargs, dict):
                message.additional_kwargs = {}
            if "reasoning_content" not in message.additional_kwargs:
                message.additional_kwargs["reasoning_content"] = ""
    
    # Сохраняем ответ агента в историю
    try:
        # Получаем user_id и thread_id из state
        user_id = state.get("user_id")
        thread_id = state.get("thread_id")
        
        # Сохраняем только если есть user_id и thread_id и это не системное сообщение
        if user_id and user_id != "anonymous" and user_id != "default_user" and thread_id:
            # Получаем content сообщения
            content = str(message.content) if hasattr(message, 'content') else ""
            
            # Сохраняем только если content не пустой
            if content.strip():
                await save_chat_message(user_id, thread_id, "assistant", content)
                logger.debug(f"💾 Сохранен ответ агента в историю для user_id={user_id}, thread_id={thread_id}")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось сохранить ответ агента в историю: {e}")
    
    # Возвращаем только сообщение, очистку инструментов делаем в отдельном узле cleanup_tools
    return {"messages": [message]}


async def cleanup_tools_node(state: AgentState) -> dict:
    """
    Узел очистки инструментов после выдачи ответа пользователю.
    Вызывается перед завершением графа для очистки инструментов из state.
    Это предотвращает накопление инструментов в контексте для следующих запросов.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[cleanup_tools_node] OPTIMIZATION: Очищаем инструменты из state после выдачи ответа")
    
    # Очищаем инструменты из state
    return {
        "tools": [],  # Очищаем инструменты после ответа
        "mcp_tools": [],  # Очищаем MCP инструменты после ответа
    }


def generate_mistral_tool_call_id() -> str:
    """
    Генерирует tool call ID для Mistral API.
    Mistral требует ID длиной 9 символов, содержащий только буквы и цифры (a-z, A-Z, 0-9).
    """
    return ''.join(random.choices(string.ascii_letters + string.digits, k=9))


def get_tool_call_id(action: dict) -> str:
    """
    Получает tool call ID из action, или генерирует новый, если его нет.
    Для Mistral API ID должен быть длиной 9 символов (a-z, A-Z, 0-9).
    """
    tool_id = action.get("id", "")
    # Проверяем, соответствует ли ID требованиям Mistral (9 символов, только буквы и цифры)
    if tool_id and len(tool_id) == 9 and tool_id.isalnum():
        return tool_id
    # Если ID не соответствует требованиям, генерируем новый
    return generate_mistral_tool_call_id()


async def tool_call(state: AgentState, config: RunnableConfig, store: BaseStore):
    import logging
    logger = logging.getLogger(__name__)
    
    # Проверяем, что есть сообщения и последнее сообщение содержит tool_calls
    messages = state.get("messages", [])
    if not messages:
        logger.error("❌ tool_call: Список сообщений пуст")
        return state
    
    last_message = messages[-1]
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        logger.error("❌ tool_call: Последнее сообщение не содержит tool_calls")
        return state
    
    action = copy.deepcopy(last_message.tool_calls[0])
    is_frontend_tool = False
    file_ids = []  # Инициализируем file_ids в начале функции
    
    # Проверяем, является ли вызываемый инструмент MCP инструментом из tool_server
    # MCP инструменты из tool_server должны вызываться через tool_client, а не через фронтенд
    mcp_tools = state.get("mcp_tools", [])
    logger.info(f"🔍 tool_call: Проверяем MCP инструменты. Всего MCP инструментов в state: {len(mcp_tools)}")
    if mcp_tools:
        mcp_names = [tool.get("name", "unknown") for tool in mcp_tools]
        logger.info(f"🔍 tool_call: Доступные MCP инструменты: {mcp_names}")
    
    tool_name = action.get("name")
    logger.info(f"🔍 tool_call: Вызываемый инструмент: {tool_name}")
    
    # Проверяем, является ли инструмент MCP инструментом из tool_server
    # MCP инструменты из tool_server НЕ должны вызываться через фронтенд (is_frontend_tool = False)
    # Они должны вызываться через tool_client.aexecute()
    is_mcp_tool_from_server = False
    for tool in mcp_tools:
        if tool.get("name") == tool_name:
            is_mcp_tool_from_server = True
            logger.info(f"✅ tool_call: Инструмент '{tool_name}' найден в MCP инструментах из tool_server")
            break
    
    # is_frontend_tool используется только для инструментов, которые должны вызываться через фронтенд
    # (например, инструменты из модального окна MCP на фронтенде)
    # MCP инструменты из tool_server НЕ должны устанавливать is_frontend_tool = True
    # Они должны вызываться через tool_client.aexecute() в блоке else (строка 1601)
    
    if not is_mcp_tool_from_server:
        logger.debug(f"ℹ️ tool_call: Инструмент '{tool_name}' не является MCP инструментом из tool_server")
    
    # Для MCP инструментов из tool_server не создаем interrupt, они будут вызваны через tool_client
    # interrupt создается только для инструментов, которые должны вызываться через фронтенд
    value = interrupt({"type": "approve"})
    tool_client = ToolClient()
    if value.get("type") == "comment":
        # Проверяем, есть ли сообщение от пользователя
        user_message = value.get("message", "").strip()
        if not user_message:
            # Если сообщения нет, значит пользователь отменил действие
            return {
                "messages": ToolMessage(
                    tool_call_id=action.get("id", str(uuid4())),
                    content=json.dumps(
                        {
                            "message": "Пользователь отменил выполнение инструмента. Не выполняй этот инструмент."
                        },
                        ensure_ascii=False,
                    ),
                )
            }
        else:
            # Если есть сообщение, передаем его как комментарий
            return {
                "messages": ToolMessage(
                    tool_call_id=action.get("id", str(uuid4())),
                    content=json.dumps(
                        {
                            "message": f'Пользователь оставил комментарий к твоему вызову инструмента. Прочитай его и реши, как действовать дальше: "{user_message}"'
                        },
                        ensure_ascii=False,
                    ),
                )
            }
    tool_call_index = state.get("tool_call_index", -1)
    if action.get("name") == "python" and not is_frontend_tool:
        if os.getenv("REPL_FROM_MESSAGE", "1") == "1":
            action["args"]["code"] = get_code_arg(last_message.content)
        else:
            # На случай если гига отправить в аргумент ```python(.+)``` строку
            code_arg = get_code_arg(action["args"].get("code"))
            if code_arg:
                action["args"]["code"] = code_arg
        if "code" not in action["args"] or not action["args"]["code"]:
            return {
                "messages": ToolMessage(
                    tool_call_id=action.get("id", str(uuid4())),
                    content=json.dumps(
                        {"message": "Напиши код в своем сообщении!"},
                        ensure_ascii=False,
                    ),
                )
            }
        # Безопасно извлекаем thread_id и checkpoint_id из config
        thread_id, checkpoint_id = extract_thread_id_from_config(config)
        if not thread_id:
            logger.error(f"❌ thread_id не найден в config для prepend_code")
            raise ValueError("thread_id обязателен для выполнения prepend_code")
        action["args"]["code"] = prepend_code(
            action["args"]["code"],
            state,
            thread_id,
            checkpoint_id or "",
        )
    try:
        tool_attachments = []
        if not is_frontend_tool:
            message = ""
            state_ = copy.deepcopy(state)
            state_.pop("messages")
            # Безопасно извлекаем thread_id и checkpoint_id из config
            thread_id, checkpoint_id = extract_thread_id_from_config(config)
            if not thread_id:
                logger.error(f"❌ thread_id не найден в config для set_state_data")
                raise ValueError("thread_id обязателен для выполнения set_state_data")
            tool_client.set_state_data(
                thread_id, checkpoint_id or ""
            )
            tool_name = action.get("name")
            
            # Логируем информацию о вызове инструмента
            logger.info(f"🔍 tool_call: Вызов инструмента '{tool_name}'")
            logger.info(f"🔍 tool_call: tool_name в AGENT_MAP: {tool_name in AGENT_MAP}")
            if tool_name in AGENT_MAP:
                logger.info(f"✅ tool_call: '{tool_name}' найден в AGENT_MAP, обрабатываем как агент")
            else:
                logger.info(f"ℹ️ tool_call: '{tool_name}' не в AGENT_MAP, будет вызван через tool_client")
            
            # Проверяем, требует ли инструмент инъекцию state (python или агенты)
            if tool_name in AGENT_MAP:
                # Логируем информацию о state перед инъекцией
                logger.debug(f"🔍 Вызов агента {tool_name}: state type={type(state)}, state keys={list(state.keys()) if isinstance(state, dict) else 'N/A'}")
                if isinstance(state, dict) and "secrets" in state:
                    secrets_count = len(state.get("secrets", [])) if isinstance(state.get("secrets"), list) else 0
                    logger.info(f"📧 State содержит {secrets_count} секретов для {tool_name}")
                elif isinstance(state, dict):
                    logger.warning(f"⚠️ State не содержит 'secrets' для {tool_name}, keys={list(state.keys())}")
                
                # Для агентов используем инъекцию параметров
                tool_node = ToolNode(tools=list(AGENT_MAP.values()))
                injection_payload = inject_tool_args_compat(
                    tool_node,
                    {
                        "name": tool_name,
                        "args": action.get("args"),
                        "id": get_tool_call_id(action),
                    },
                    state,
                    None,
                )
                injected_args = injection_payload["args"]
                logger.debug(f"🔍 После инъекции для {tool_name}: injected_args keys={list(injected_args.keys())}")
                
                # НОРМАЛИЗАЦИЯ ПАРАМЕТРОВ ДЛЯ ИНСТРУМЕНТОВ
                # Многие модели ошибочно передают неправильные параметры
                # Преобразуем их автоматически для лучшей совместимости
                
                # Нормализация для инструмента search
                if tool_name == "search":
                    # search использует queries (список), но модели часто передают query (строка)
                    if "queries" not in injected_args or not injected_args.get("queries"):
                        if "query" in injected_args and injected_args["query"]:
                            # Преобразуем query в queries (список)
                            query_value = injected_args["query"]
                            if isinstance(query_value, str):
                                injected_args["queries"] = [query_value]
                            elif isinstance(query_value, list):
                                injected_args["queries"] = query_value
                            else:
                                injected_args["queries"] = [str(query_value)]
                            del injected_args["query"]
                            logger.info(f"🔧 Нормализация: для search параметр 'query' преобразован в 'queries' (список)")
                        else:
                            # Если нет ни queries, ни query, пытаемся найти в других параметрах
                            alternative_params = ["search_query", "q", "text", "request"]
                            queries_value = None
                            found_param = None
                            
                            for alt_param in alternative_params:
                                if alt_param in injected_args and injected_args[alt_param]:
                                    queries_value = injected_args[alt_param]
                                    found_param = alt_param
                                    logger.info(f"🔧 Нормализация: для search найден параметр '{alt_param}' вместо queries, преобразуем")
                                    break
                            
                            if queries_value:
                                if isinstance(queries_value, str):
                                    injected_args["queries"] = [queries_value]
                                elif isinstance(queries_value, list):
                                    injected_args["queries"] = queries_value
                                else:
                                    injected_args["queries"] = [str(queries_value)]
                                if found_param:
                                    del injected_args[found_param]
                                logger.info(f"✅ Нормализация: параметр '{found_param}' преобразован в queries для search")
                
                # НОРМАЛИЗАЦИЯ ПАРАМЕТРОВ ДЛЯ АГЕНТОВ
                # Многие модели ошибочно передают query, action, task_type вместо правильных параметров
                # Преобразуем их автоматически для лучшей совместимости
                if tool_name and tool_name.endswith("_agent"):
                    # Специальная обработка для агентов с разными параметрами
                    if tool_name == "coder_agent":
                        # coder_agent использует task вместо user_request
                        if "task" not in injected_args or not injected_args.get("task"):
                            alternative_params = ["query", "action", "user_request", "request", "message", "text"]
                            task_value = None
                            found_param = None
                            
                            for alt_param in alternative_params:
                                if alt_param in injected_args and injected_args[alt_param]:
                                    task_value = injected_args[alt_param]
                                    found_param = alt_param
                                    logger.info(f"🔧 Нормализация: для {tool_name} найден параметр '{alt_param}' вместо task, преобразуем")
                                    break
                            
                            if task_value:
                                injected_args["task"] = task_value
                                if found_param and found_param != "state":
                                    del injected_args[found_param]
                                logger.info(f"✅ Нормализация: параметр '{found_param}' преобразован в task для {tool_name}")
                    elif tool_name == "researcher_agent":
                        # researcher_agent использует question вместо user_request
                        if "question" not in injected_args or not injected_args.get("question"):
                            alternative_params = ["query", "action", "user_request", "request", "message", "text"]
                            question_value = None
                            found_param = None
                            
                            for alt_param in alternative_params:
                                if alt_param in injected_args and injected_args[alt_param]:
                                    question_value = injected_args[alt_param]
                                    found_param = alt_param
                                    logger.info(f"🔧 Нормализация: для {tool_name} найден параметр '{alt_param}' вместо question, преобразуем")
                                    break
                            
                            if question_value:
                                injected_args["question"] = question_value
                                if found_param and found_param != "state":
                                    del injected_args[found_param]
                                logger.info(f"✅ Нормализация: параметр '{found_param}' преобразован в question для {tool_name}")
                    else:
                        # Для остальных агентов используется user_request
                        if "user_request" not in injected_args or not injected_args.get("user_request"):
                            # Пытаемся найти запрос в других параметрах
                            alternative_params = ["query", "action", "task", "request", "message", "text"]
                            user_request_value = None
                            found_param = None
                            
                            for alt_param in alternative_params:
                                if alt_param in injected_args and injected_args[alt_param]:
                                    user_request_value = injected_args[alt_param]
                                    found_param = alt_param
                                    logger.info(f"🔧 Нормализация: для {tool_name} найден параметр '{alt_param}' вместо user_request, преобразуем")
                                    break
                            
                            if user_request_value:
                                # Преобразуем найденный параметр в user_request
                                injected_args["user_request"] = user_request_value
                                # Удаляем старый параметр (кроме state, который нужен)
                                if found_param and found_param != "state":
                                    del injected_args[found_param]
                                logger.info(f"✅ Нормализация: параметр '{found_param}' преобразован в user_request для {tool_name}")
                            else:
                                # Если не нашли альтернативный параметр, но есть запрос пользователя в сообщениях
                                # Пытаемся извлечь его из последнего сообщения пользователя
                                messages = state.get("messages", [])
                                for msg in reversed(messages):
                                    if hasattr(msg, 'type') and msg.type == "human":
                                        user_query = msg.content if hasattr(msg, 'content') else str(msg)
                                        if user_query and len(user_query.strip()) > 0:
                                            injected_args["user_request"] = user_query.strip()
                                            logger.info(f"✅ Нормализация: user_request извлечен из сообщения пользователя для {tool_name}")
                                            break
                
                # Явно проверяем и добавляем state, если он не был инжектирован
                # (для случаев, когда InjectedState не работает автоматически)
                # Проверяем сигнатуру функции, чтобы понять, нужен ли state
                import inspect
                from typing import get_origin, get_args, Annotated
                try:
                    from langgraph.prebuilt import InjectedState
                except ImportError:
                    InjectedState = None
                
                agent_tool = AGENT_MAP[tool_name]
                needs_state = False
                try:
                    # Для инструментов, определенных через @tool, нужно получить исходную функцию
                    # Обычно она доступна через agent_tool.func или agent_tool.coroutine
                    func_to_check = None
                    if hasattr(agent_tool, 'func'):
                        func_to_check = agent_tool.func
                    elif hasattr(agent_tool, 'coroutine'):
                        func_to_check = agent_tool.coroutine
                    elif hasattr(agent_tool, '__wrapped__'):
                        func_to_check = agent_tool.__wrapped__
                    elif callable(agent_tool):
                        func_to_check = agent_tool
                    
                    if func_to_check:
                        sig = inspect.signature(func_to_check)
                        # Проверяем, есть ли параметр state в сигнатуре
                        for param_name, param in sig.parameters.items():
                            if param_name == "state":
                                needs_state = True
                                # Также проверяем, есть ли InjectedState в аннотации
                                annotation = param.annotation
                                if annotation is not inspect.Parameter.empty:
                                    try:
                                        origin = get_origin(annotation)
                                        if origin is Annotated and InjectedState:
                                            args = get_args(annotation)
                                            if len(args) > 1 and InjectedState in args[1:]:
                                                logger.debug(f"✅ Найден InjectedState для параметра state в {tool_name}")
                                    except (TypeError, AttributeError):
                                        pass
                                break
                except (ValueError, TypeError, AttributeError) as e:
                    logger.debug(f"⚠️ Ошибка при проверке сигнатуры для {tool_name}: {e}")
                    # Если не удалось проверить сигнатуру, проверяем, был ли state инжектирован
                    needs_state = "state" in injected_args
                
                # Если state нужен, но не был инжектирован или равен None, добавляем его явно
                if needs_state and ("state" not in injected_args or injected_args.get("state") is None):
                    logger.info(f"🔧 Явно добавляем state для инструмента {tool_name}")
                    injected_args["state"] = state
                elif needs_state:
                    logger.info(f"✅ State уже присутствует для инструмента {tool_name}")
                    # Проверяем, что state содержит secrets
                    injected_state = injected_args.get("state")
                    if isinstance(injected_state, dict) and "secrets" in injected_state:
                        secrets_count = len(injected_state.get("secrets", [])) if isinstance(injected_state.get("secrets"), list) else 0
                        logger.info(f"📧 Инжектированный state содержит {secrets_count} секретов")
                    elif isinstance(injected_state, dict):
                        logger.warning(f"⚠️ Инжектированный state не содержит 'secrets', keys={list(injected_state.keys())}")
                else:
                    logger.info(f"ℹ️ Инструмент {tool_name} не требует state")
                
                result = await AGENT_MAP[tool_name].ainvoke(injected_args)
            elif tool_name == "python":
                # Для python также используем инъекцию параметров, так как он требует state
                # Логируем информацию о state перед инъекцией
                logger.debug(f"🐍 Вызов python tool: state type={type(state)}, state keys={list(state.keys()) if isinstance(state, dict) else 'N/A'}")
                if isinstance(state, dict) and "secrets" in state:
                    secrets_count = len(state.get("secrets", [])) if isinstance(state.get("secrets"), list) else 0
                    logger.info(f"📧 State содержит {secrets_count} секретов для python tool")
                elif isinstance(state, dict):
                    logger.warning(f"⚠️ State не содержит 'secrets' для python tool, keys={list(state.keys())}")
                
                python_tools = [tool for tool in TOOLS if tool.name == "python"]
                if not python_tools:
                    # Если инструмент не найден, используем обычный вызов
                    logger.warning("⚠️ Python tool не найден в TOOLS, используем tool_client")
                    result = await tool_client.aexecute(tool_name, action.get("args"))
                else:
                    python_tool = python_tools[0]
                    tool_node = ToolNode(tools=[python_tool])
                    injection_payload = inject_tool_args_compat(
                        tool_node,
                        {
                            "name": tool_name,
                            "args": action.get("args"),
                            "id": get_tool_call_id(action),
                        },
                        state,
                        None,
                    )
                    injected_args = injection_payload["args"]
                    logger.debug(f"🐍 После инъекции для python: injected_args keys={list(injected_args.keys())}")
                    
                    # ЯВНАЯ ГАРАНТИЯ: проверяем и добавляем state, если он не был инжектирован
                    # Python tool ОБЯЗАТЕЛЬНО требует state (Annotated[dict, InjectedState])
                    # Это КРИТИЧЕСКИ ВАЖНО - python tool не может работать без state!
                    if "state" not in injected_args or injected_args.get("state") is None:
                        logger.warning("⚠️ State не был инжектирован для python tool, добавляем явно")
                        injected_args["state"] = state
                        logger.info("✅ State добавлен явно для python tool")
                    else:
                        logger.info("✅ State уже присутствует для python tool")
                        # Проверяем, что state содержит необходимые поля
                        injected_state = injected_args.get("state")
                        if isinstance(injected_state, dict):
                            if "kernel_id" not in injected_state:
                                logger.warning(f"⚠️ State для python не содержит 'kernel_id', keys={list(injected_state.keys())}")
                            else:
                                logger.debug(f"✅ State содержит kernel_id: {injected_state.get('kernel_id')}")
                            if "secrets" in injected_state:
                                secrets_count = len(injected_state.get("secrets", [])) if isinstance(injected_state.get("secrets"), list) else 0
                                logger.info(f"📧 Инжектированный state содержит {secrets_count} секретов")
                    
                    # ФИНАЛЬНАЯ ПРОВЕРКА: гарантируем, что state точно присутствует
                    if "state" not in injected_args:
                        logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: State отсутствует для python tool после всех проверок!")
                        injected_args["state"] = state  # Принудительно добавляем
                    elif injected_args.get("state") is None:
                        logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: State равен None для python tool!")
                        injected_args["state"] = state  # Принудительно добавляем
                    else:
                        logger.info("✅ ФИНАЛЬНАЯ ПРОВЕРКА: State гарантированно присутствует для python tool")
                    
                    # Также гарантируем наличие code
                    if "code" not in injected_args:
                        logger.warning("⚠️ Code не найден в injected_args для python, добавляем из action")
                        injected_args["code"] = action.get("args", {}).get("code")
                    
                    logger.info(f"🐍 Вызываем python tool с args keys: {list(injected_args.keys())}")
                    result = await python_tool.ainvoke(injected_args)
            else:
                # Проверяем, является ли инструмент обычным tool из TOOLS, который требует state
                # (например, personalize требует InjectedState)
                tool_from_tools = None
                logger.info(f"🔍 tool_call: Проверяем наличие инструмента {tool_name} в TOOLS (всего {len(TOOLS)} инструментов)")
                for tool in TOOLS:
                    if hasattr(tool, 'name') and tool.name == tool_name:
                        tool_from_tools = tool
                        logger.info(f"✅ tool_call: Инструмент {tool_name} найден в TOOLS")
                        break
                
                if not tool_from_tools:
                    logger.info(f"ℹ️ tool_call: Инструмент {tool_name} не найден в TOOLS, будет вызван через tool_client")
                
                # Если инструмент найден в TOOLS и требует state, вызываем его напрямую с инжекцией
                if tool_from_tools:
                    import inspect
                    from typing import get_origin, get_args, Annotated
                    try:
                        from langgraph.prebuilt import InjectedState
                    except ImportError:
                        InjectedState = None
                    
                    # Проверяем, требует ли инструмент state
                    needs_state = False
                    try:
                        func_to_check = None
                        # Для инструментов, определенных через @tool, func может быть None, используем coroutine
                        if hasattr(tool_from_tools, 'func') and tool_from_tools.func is not None:
                            func_to_check = tool_from_tools.func
                        elif hasattr(tool_from_tools, 'coroutine') and tool_from_tools.coroutine is not None:
                            func_to_check = tool_from_tools.coroutine
                        elif hasattr(tool_from_tools, '__wrapped__') and tool_from_tools.__wrapped__ is not None:
                            func_to_check = tool_from_tools.__wrapped__
                        elif callable(tool_from_tools):
                            func_to_check = tool_from_tools
                        
                        if func_to_check:
                            sig = inspect.signature(func_to_check)
                            for param_name, param in sig.parameters.items():
                                if param_name == "state":
                                    needs_state = True
                                    annotation = param.annotation
                                    if annotation is not inspect.Parameter.empty:
                                        try:
                                            origin = get_origin(annotation)
                                            if origin is Annotated and InjectedState:
                                                args = get_args(annotation)
                                                if len(args) > 1 and InjectedState in args[1:]:
                                                    logger.info(f"✅ Найден InjectedState для параметра state в {tool_name}")
                                        except (TypeError, AttributeError):
                                            pass
                                    break
                    except (ValueError, TypeError, AttributeError) as e:
                        logger.debug(f"⚠️ Ошибка при проверке сигнатуры для {tool_name}: {e}")
                    
                    # Если инструмент требует state, вызываем его напрямую с инжекцией
                    if needs_state:
                        logger.info(f"🔧 tool_call: Инструмент {tool_name} требует state (needs_state=True), вызываем напрямую с инжекцией")
                        tool_node = ToolNode(tools=[tool_from_tools])
                        injection_payload = inject_tool_args_compat(
                            tool_node,
                            {
                                "name": tool_name,
                                "args": action.get("args"),
                                    "id": get_tool_call_id(action),
                            },
                            state,
                            None,
                        )
                        injected_args = injection_payload["args"]
                        
                        # Гарантируем наличие state
                        if "state" not in injected_args or injected_args.get("state") is None:
                            logger.warning(f"⚠️ State не был инжектирован для {tool_name}, добавляем явно")
                            injected_args["state"] = state
                        else:
                            logger.info(f"✅ State уже присутствует для {tool_name}")
                        
                        try:
                            result = await tool_from_tools.ainvoke(injected_args)
                            logger.info(f"✅ tool_call: Инструмент {tool_name} выполнен успешно с инжекцией state")
                        except Exception as e:
                            logger.error(f"❌ tool_call: Ошибка при вызове инструмента {tool_name}: {type(e).__name__}: {str(e)}")
                            logger.error(f"❌ tool_call: Traceback: {traceback.format_exc()[:500]}")
                            raise
                    else:
                        logger.info(f"ℹ️ tool_call: Инструмент {tool_name} не требует state (needs_state=False)")
                        # Инструмент не требует state, используем tool_client
                        logger.info(f"🔧 tool_call: Вызов инструмента {tool_name} через tool_client.aexecute()")
                        tool_args = action.get("args", {}).copy()
                        try:
                            result = await tool_client.aexecute(tool_name, tool_args)
                            logger.info(f"✅ tool_call: Инструмент {tool_name} выполнен успешно, результат: {type(result)}, длина: {len(str(result)) if result else 0}")
                        except Exception as e:
                            logger.error(f"❌ tool_call: Ошибка при вызове инструмента {tool_name}: {type(e).__name__}: {str(e)}")
                            logger.error(f"❌ tool_call: Traceback: {traceback.format_exc()[:500]}")
                            raise
                else:
                    # Для остальных инструментов (MCP и т.д.) используем tool_client
                    logger.info(f"🔧 tool_call: Вызов MCP инструмента {tool_name} через tool_client.aexecute()")
                    
                    # Проверяем права доступа для MCP инструментов, требующих прав администратора
                    from giga_agent.config import MCP_ADMIN_ONLY_TOOLS, is_admin_user
                    user_id_from_state = state.get("user_id")
                    
                    if tool_name in MCP_ADMIN_ONLY_TOOLS:
                        is_admin = await is_admin_user(user_id_from_state)
                        logger.info(
                            f"🔒 tool_call: Проверка прав администратора для MCP инструмента '{tool_name}': "
                            f"user_id={user_id_from_state}, is_admin={is_admin}"
                        )
                        if not is_admin:
                            error_msg = (
                                f"Инструмент '{tool_name}' доступен только администраторам. "
                                f"Обратитесь к администратору для получения доступа."
                            )
                            logger.warning(f"❌ tool_call: Доступ запрещен для MCP инструмента '{tool_name}': user_id={user_id_from_state}, is_admin={is_admin}")
                            return {
                                "messages": ToolMessage(
                                    tool_call_id=action.get("id", str(uuid4())),
                                    content=json.dumps(
                                        {
                                            "error": error_msg,
                                            "message": error_msg
                                        },
                                        ensure_ascii=False,
                                    ),
                                )
                            }
                        logger.info(f"✅ tool_call: Доступ разрешен для MCP инструмента '{tool_name}' (пользователь является администратором)")
                    
                    # Обрабатываем аргументы перед вызовом
                    tool_args = action.get("args", {}).copy()
                    
                    # Для create_news и create_blog_post преобразуем markdown в HTML для content
                    if tool_name in ["create_news", "create_blog_post", "update_news", "update_blog_post"]:
                        from giga_agent.utils.markdown_utils import markdown_to_html
                        if "content" in tool_args and tool_args["content"]:
                            original_content = tool_args["content"]
                            tool_args["content"] = markdown_to_html(original_content)
                            logger.info(f"📝 tool_call: Преобразовано markdown в HTML для {tool_name} (длина: {len(original_content)} -> {len(tool_args['content'])})")
                    
                    logger.info(f"🔧 tool_call: Аргументы: {list(tool_args.keys())}")
                    try:
                        result = await tool_client.aexecute(tool_name, tool_args)
                        logger.info(f"✅ tool_call: MCP инструмент {tool_name} выполнен успешно, результат: {type(result)}, длина: {len(str(result)) if result else 0}")
                    except Exception as e:
                        logger.error(f"❌ tool_call: Ошибка при вызове MCP инструмента {tool_name}: {type(e).__name__}: {str(e)}")
                        logger.error(f"❌ tool_call: Traceback: {traceback.format_exc()[:500]}")
                        raise  # Пробрасываем ошибку дальше
            try:
                result = json.loads(result)
            except Exception as e:
                logger.debug(f"ℹ️ tool_call: Результат не является JSON, используем как есть: {type(result)}")
                pass
            
            # Fallback логика для инструмента weather: если токен недоступен, сначала пробуем второй инструмент, потом поиск
            if tool_name == "weather" and result:
                # Проверяем, является ли результат строкой с ошибкой о токене
                result_str = result if isinstance(result, str) else str(result)
                # Проверяем наличие ошибки о недоступности токена (различные варианты сообщений)
                is_token_error = (
                    "Не задан OWM_API_KEY" in result_str or 
                    ("OWM_API_KEY" in result_str and "не задан" in result_str.lower()) or
                    "OWM_API_KEY" in result_str and ("установи" in result_str.lower() or "установите" in result_str.lower())
                )
                if is_token_error:
                    logger.info(f"🔍 tool_call: Обнаружена ошибка токена для weather, пробуем fallback через weather_openmeteo")
                    
                    # Шаг 1: Пробуем второй инструмент погоды (Open-Meteo)
                    try:
                        # Получаем аргументы из action для формирования запроса
                        city = action.get("args", {}).get("city", "")
                        units = action.get("args", {}).get("units", "c")
                        lang = action.get("args", {}).get("lang", "ru")
                        
                        # Находим инструмент weather_openmeteo в TOOLS
                        weather_openmeteo_tool = None
                        for tool in TOOLS:
                            if hasattr(tool, 'name') and tool.name == "weather_openmeteo":
                                weather_openmeteo_tool = tool
                                break
                        
                        if weather_openmeteo_tool:
                            logger.info(f"🔍 tool_call: Вызываем weather_openmeteo с city={city}, units={units}, lang={lang}")
                            # Вызываем второй инструмент погоды
                            weather_alt_result = await weather_openmeteo_tool.ainvoke({
                                "city": city,
                                "units": units,
                                "lang": lang
                            })
                            
                            # Проверяем, успешно ли выполнился второй инструмент
                            # Результат должен быть строкой и не содержать ошибок
                            is_success = (
                                isinstance(weather_alt_result, str) and 
                                weather_alt_result and
                                "ошибка" not in weather_alt_result.lower() and
                                "error" not in weather_alt_result.lower() and
                                "не найден" not in weather_alt_result.lower() and
                                "not found" not in weather_alt_result.lower() and
                                "таймаут" not in weather_alt_result.lower() and
                                "timeout" not in weather_alt_result.lower()
                            )
                            
                            if is_success:
                                # Успешно получили погоду через второй инструмент
                                result = weather_alt_result
                                logger.info(f"✅ tool_call: Fallback через weather_openmeteo выполнен успешно, длина результата: {len(str(result))}")
                            else:
                                # Второй инструмент тоже не сработал, переходим к поиску
                                logger.info(f"⚠️ tool_call: weather_openmeteo не вернул успешный результат, переходим к поиску")
                                raise Exception("weather_openmeteo failed, trying search")
                        else:
                            logger.warning(f"⚠️ tool_call: Инструмент weather_openmeteo не найден в TOOLS, переходим к поиску")
                            raise Exception("weather_openmeteo not found, trying search")
                            
                    except Exception as alt_weather_error:
                        # Если второй инструмент не сработал, используем поиск
                        logger.info(f"🔍 tool_call: weather_openmeteo не сработал ({str(alt_weather_error)}), используем fallback через search")
                        
                        # Шаг 2: Пробуем поиск
                        try:
                            # Получаем аргументы из action для формирования поискового запроса
                            city = action.get("args", {}).get("city", "")
                            units = action.get("args", {}).get("units", "c")
                            lang = action.get("args", {}).get("lang", "ru")
                            
                            # Формируем поисковый запрос о погоде
                            if lang == "ru" or lang.startswith("ru"):
                                search_query = f"погода {city}" if city else "погода"
                            else:
                                search_query = f"weather {city}" if city else "weather"
                            
                            # Находим инструмент search в TOOLS
                            search_tool = None
                            for tool in TOOLS:
                                if hasattr(tool, 'name') and tool.name == "search":
                                    search_tool = tool
                                    break
                            
                            if search_tool:
                                logger.info(f"🔍 tool_call: Вызываем search с запросом: {search_query}")
                                # Вызываем search инструмент
                                search_result = await search_tool.ainvoke({"queries": [search_query]})
                                
                                # Форматируем результат поиска для замены результата weather
                                # TavilySearch возвращает список результатов для каждого запроса
                                if isinstance(search_result, list) and len(search_result) > 0:
                                    # Берем первый результат поиска (первый запрос)
                                    first_result = search_result[0]
                                    
                                    # TavilySearch может возвращать словарь с ключами results или напрямую список результатов
                                    if isinstance(first_result, dict):
                                        # Проверяем, есть ли ключ "results" (структура TavilySearch)
                                        if "results" in first_result:
                                            results_list = first_result.get("results", [])
                                            if results_list and len(results_list) > 0:
                                                # Берем первый результат из списка
                                                result_item = results_list[0]
                                                search_content = result_item.get("content", "")
                                                search_url = result_item.get("url", "")
                                                
                                                # Формируем сообщение с результатами поиска
                                                fallback_message = f"Информация о погоде в {city} (получено через поиск, так как специальный инструмент недоступен):\n\n"
                                                if search_content:
                                                    fallback_message += f"{search_content}\n\n"
                                                if search_url:
                                                    fallback_message += f"Источник: {search_url}\n"
                                                
                                                result = fallback_message
                                                logger.info(f"✅ tool_call: Fallback через search выполнен успешно, длина результата: {len(result)}")
                                            else:
                                                result = f"Информация о погоде в {city} (получено через поиск, но результаты не найдены)"
                                        else:
                                            # Прямая структура результата
                                            search_content = first_result.get("content", "")
                                            search_url = first_result.get("url", "")
                                            
                                            # Формируем сообщение с результатами поиска
                                            fallback_message = f"Информация о погоде в {city} (получено через поиск, так как специальный инструмент недоступен):\n\n"
                                            if search_content:
                                                fallback_message += f"{search_content}\n\n"
                                            if search_url:
                                                fallback_message += f"Источник: {search_url}\n"
                                            
                                            result = fallback_message
                                            logger.info(f"✅ tool_call: Fallback через search выполнен успешно, длина результата: {len(result)}")
                                    else:
                                        # Если результат не словарь, преобразуем в строку
                                        result = f"Информация о погоде в {city} (получено через поиск): {str(first_result)}"
                                else:
                                    # Если результат пустой или не список
                                    result = f"Информация о погоде в {city} (получено через поиск, но результаты не найдены)"
                            else:
                                logger.warning(f"⚠️ tool_call: Инструмент search не найден в TOOLS, fallback недоступен")
                        except Exception as search_error:
                            logger.error(f"❌ tool_call: Ошибка при выполнении fallback через search: {type(search_error).__name__}: {str(search_error)}")
                            logger.error(f"❌ tool_call: Traceback: {traceback.format_exc()[:500]}")
                            # В случае ошибки fallback оставляем оригинальный результат
        else:
            # Безопасно извлекаем thread_id из config
            thread_id, _ = extract_thread_id_from_config(config)
            if not thread_id:
                logger.error(f"❌ thread_id не найден в config для process_mcp_content")
                raise ValueError("thread_id обязателен для выполнения process_mcp_content")
            result, tool_attachments, message = await process_mcp_content(
                value.get("result", {}).get("content", {}),
                thread_id,
            )
        tool_call_index += 1

        # УБРАНО: Проверка requires_browser_auth и прерывание
        # Авторизация теперь обрабатывается через request_auth_node в career_agent
        # без использования модальных окон и прерываний
        # Используется телефон из секретов пользователя и запрос кода через сообщение

        if result:
            # Получаем название модели из state (сохранено в agent функции)
            model_name = state.get("current_model_name", get_model_name())
            add_data = {
                "data": result,
                "message": message
                + f"Результат функции сохранен в переменную `function_results[{tool_call_index}]['data']` ",
                "model_name": model_name,  # Добавляем название модели в результаты
            }
            await client.execute(
                state.get("kernel_id"), f"function_results.append({repr(add_data)})"
            )
            # Для read_document не ограничиваем размер результата, так как это содержимое документа
            if (
                len(json.dumps(result, ensure_ascii=False)) > 10000 * 4
                and action.get("name") not in AGENT_MAP
                and action.get("name") != "read_document"
            ):
                schema = SchemaBuilder()
                schema.add_object(obj=add_data.pop("data"))
                add_data[
                    "message"
                ] += f"Результат функции вышел слишком длинным изучи результат функции в переменной с помощью python. Схема данных:\n"
                add_data["schema"] = schema.to_schema()
            if action.get("name") == "get_urls":
                add_data["message"] += result.pop("attention")
        else:
            if message:
                # Получаем название модели из state (сохранено в agent функции)
                model_name = state.get("current_model_name", get_model_name())
                result = {"result": result, "message": message, "model_name": model_name}
            add_data = result
            # Если add_data не содержит model_name, добавляем его
            if isinstance(add_data, dict) and "model_name" not in add_data:
                model_name = state.get("current_model_name", get_model_name())
                add_data["model_name"] = model_name

        # Этап 2 (ROMA_OPTIMIZE.MD): сохраняем "полный" результат до любых обрезок.
        # Примечание: ниже по коду add_data может мутироваться (truncate_large_strings и т.п.).
        # Мы НЕ удаляем и не меняем существующую логику — только сохраняем копию для offloading.
        add_data_full = None
        try:
            add_data_full = copy.deepcopy(add_data)
        except Exception:
            add_data_full = add_data  # fallback: хоть что-то для сохранения
        tool_attachments = []
        # file_ids уже инициализирован в начале функции
        # Сохраняем giga_attachments перед обработкой, чтобы они не потерялись при offloading
        saved_giga_attachments = None
        if isinstance(result, dict) and "giga_attachments" in result:
            add_data = result
            attachments = result.pop("giga_attachments")
            # Сохраняем копию giga_attachments для восстановления после offloading
            saved_giga_attachments = attachments.copy()
            # Безопасно извлекаем file_id из attachment (может отсутствовать)
            file_ids = [attachment.get("file_id") for attachment in attachments if attachment.get("file_id")]
            for attachment in attachments:
                attachment_type = attachment.get("type", "")
                # Определяем file_type для фронтенда
                file_type = "other"
                if attachment_type.startswith("image/"):
                    file_type = "image"
                elif attachment_type.startswith("audio/"):
                    file_type = "audio"
                elif attachment_type == "text/html":
                    file_type = "html"
                elif attachment_type.startswith("text/"):
                    file_type = "text"
                
                # Создаем объект для сохранения в store с нужными полями
                # Используем path из attachment, если он есть (для файлов, сохраненных на диске)
                # Иначе используем file_id как path для совместимости
                attachment_path = attachment.get("path") or attachment.get("file_url_path") or attachment.get("file_id") or f"attachment_{id(attachment)}"
                store_attachment = {
                    **attachment,
                    "file_type": file_type,
                    "path": attachment_path,
                }
                
                # Логируем информацию о attachment для отладки
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"🔧 ATTACHMENT: type={attachment_type}, file_type={file_type}, path={attachment_path}, has_data={'data' in attachment}, data_size={len(attachment.get('data', '')) if 'data' in attachment else 0}, file_size={attachment.get('file_size', 'N/A')}")
                
                if attachment_type == "text/html":
                    await store.aput(
                        ("html",),
                        attachment["file_id"],
                        store_attachment,
                        ttl=None,
                        index=False,
                    )
                elif attachment_type.startswith("audio/"):
                    await store.aput(
                        ("audio",),
                        attachment["file_id"],
                        store_attachment,
                        ttl=None,
                        index=False,
                    )
                else:
                    # Используем attachment_path вместо attachment["file_id"] для безопасности
                    # Если attachment_path начинается с /files/, сохраняем файл в store с ключом file_id
                    # чтобы фронтенд мог найти его по file_id, а также использовать путь напрямую
                    # Если путь начинается с /files/, также сохраняем по file_id для совместимости
                    if attachment_path.startswith("/files/") and attachment.get("file_id"):
                        # Сохраняем файл в store с ключом file_id для поиска по file_id
                        await store.aput(
                            ("attachments",),
                            attachment.get("file_id"),
                            store_attachment,
                            ttl=None,
                            index=False,
                        )
                    # Всегда сохраняем также по attachment_path для прямого доступа по пути
                    await store.aput(
                        ("attachments",),
                        attachment_path,
                        store_attachment,
                        ttl=None,
                        index=False,
                    )

                # В tool_attachments используем attachment_path, если он начинается с /files/
                # чтобы фронтенд мог использовать путь напрямую (MessageAttachment.tsx строки 88-98)
                # Иначе используем file_id для поиска в store
                tool_attachment_file_id = attachment_path if attachment_path.startswith("/files/") else (attachment.get("file_id") or attachment_path)
                tool_attachments.append(
                    {
                        "type": attachment.get("type", "unknown"),
                        "file_id": tool_attachment_file_id,
                    }
                )
        
        # ИСКЛЮЧАЕМ СОДЕРЖИМОЕ ФАЙЛОВ ИЗ КОНТЕКСТА для предотвращения превышения лимита токенов
        # Ограничиваем размер содержимого файлов в ToolMessage
        tool_name = action.get("name", "")
        
        # Список инструментов и агентов, которые генерируют большие результаты (код, документы, отчеты, поиск)
        # Для них увеличиваем лимиты, чтобы можно было получать полные результаты
        LARGE_RESULT_TOOLS = [
            # Агенты генерации кода/файлов
            "coder_agent",
            "coder_plan", 
            "coder_generate",
            # Агенты генерации контента
            "researcher_agent",
            "lawyer_agent",
            "prepare_response_document",
            "generate_presentation",
            "create_landing",
            "podcast_generate",
            # Поисковые инструменты
            "search",
            "get_urls",
            "get_documents",
            # Инструменты чтения
            "read_document",
            # MCP инструменты с большими результатами (финансовый консультант, аналитика)
            "process_financial_question",
            # Агенты с большими результатами (портфель, email и т.д.)
            "tinkoff_agent",
            "email_agent",
            "career_agent",
            # Другие инструменты с большими результатами
            "mysql_query",
            # Инструменты реестра инструментов (не должны обрезаться)
            "list_available_tools",
            "get_tool_details",
        ]
        
        # Для инструментов с большими результатами увеличиваем лимит содержимого файла
        if tool_name in LARGE_RESULT_TOOLS:
            MAX_FILE_CONTENT_LENGTH = 500000  # Увеличенный лимит для инструментов, генерирующих большие результаты
        else:
            MAX_FILE_CONTENT_LENGTH = 2000  # Максимальная длина содержимого файла в ToolMessage (в символах)
        
        # Проверяем, является ли это инструментом чтения файлов
        file_reading_tools = ["read_file", "open_file", "read", "read_document"]
        is_file_reading_tool = tool_name in file_reading_tools
        
        if is_file_reading_tool and isinstance(add_data, dict):
            # Для инструментов чтения файлов ограничиваем содержимое
            if "message" in add_data and isinstance(add_data["message"], str):
                message_content = add_data["message"]
                if len(message_content) > MAX_FILE_CONTENT_LENGTH:
                    # Обрезаем содержимое и добавляем предупреждение
                    truncated_content = message_content[:MAX_FILE_CONTENT_LENGTH]
                    # Пытаемся найти информацию о файле для более информативного сообщения
                    file_path = add_data.get("file_path", add_data.get("file_name", "файл"))
                    file_name = os.path.basename(file_path) if isinstance(file_path, str) else str(file_path)
                    add_data["message"] = (
                        f"📄 **Содержимое файла**: `{file_name}`\n\n"
                        f"⚠️ **ВНИМАНИЕ**: Содержимое файла слишком большое ({len(message_content)} символов). "
                        f"Показаны первые {MAX_FILE_CONTENT_LENGTH} символов.\n\n"
                        f"```\n{truncated_content}\n```\n\n"
                        f"... (файл обрезан, полное содержимое доступно через инструмент read_file)"
                    )
                    logger.info(f"✂️ Обрезано содержимое файла в ToolMessage: {len(message_content)} -> {MAX_FILE_CONTENT_LENGTH} символов для инструмента {tool_name}")
            
            # Также ограничиваем содержимое в поле "data", если оно есть
            if "data" in add_data and isinstance(add_data["data"], dict):
                if "message" in add_data["data"] and isinstance(add_data["data"]["message"], str):
                    data_message = add_data["data"]["message"]
                    if len(data_message) > MAX_FILE_CONTENT_LENGTH:
                        truncated_data = data_message[:MAX_FILE_CONTENT_LENGTH]
                        file_path = add_data["data"].get("file_path", add_data["data"].get("file_name", "файл"))
                        file_name = os.path.basename(file_path) if isinstance(file_path, str) else str(file_path)
                        add_data["data"]["message"] = (
                            f"📄 **Содержимое файла**: `{file_name}`\n\n"
                            f"⚠️ **ВНИМАНИЕ**: Содержимое файла слишком большое ({len(data_message)} символов). "
                            f"Показаны первые {MAX_FILE_CONTENT_LENGTH} символов.\n\n"
                            f"```\n{truncated_data}\n```\n\n"
                            f"... (файл обрезан, полное содержимое доступно через инструмент read_file)"
                        )
        
        # Также ограничиваем общий размер add_data для всех инструментов
        # Это предотвращает превышение лимита контекста при накоплении ToolMessage в истории
        # Для инструментов, генерирующих большие результаты, увеличиваем лимит
        # Список LARGE_RESULT_TOOLS определен выше
        if tool_name in LARGE_RESULT_TOOLS:
            MAX_TOOL_MESSAGE_LENGTH = 500000  # Увеличенный лимит для инструментов, генерирующих большие результаты (код, документы, отчеты, поиск)
        else:
            MAX_TOOL_MESSAGE_LENGTH = 5000  # Максимальная длина всего ToolMessage (в символах JSON)
        
        # Рекурсивно обрезаем большие строки в add_data
        def truncate_large_strings(obj, max_length=MAX_TOOL_MESSAGE_LENGTH, current_path=""):
            """Рекурсивно обрезает большие строки в структуре данных"""
            if isinstance(obj, dict):
                total_size = 0
                for key, value in obj.items():
                    new_path = f"{current_path}.{key}" if current_path else key
                    if isinstance(value, str) and len(value) > 2000:
                        # Для инструментов с большими результатами не обрезаем строки в data/message, так как это содержимое документа/кода/отчета
                        # Для остальных инструментов обрезаем строки длиннее 2000 символов
                        if tool_name in LARGE_RESULT_TOOLS and (key == "data" or "data" in new_path or "message" in new_path):
                            # Для инструментов с большими результатами не обрезаем содержимое
                            pass
                        else:
                            truncated = value[:2000] + f"\n\n... (обрезано, было {len(value)} символов) ..."
                            obj[key] = truncated
                            logger.debug(f"✂️ Обрезана строка в {new_path}: {len(value)} -> {len(truncated)} символов")
                    elif isinstance(value, (dict, list)):
                        truncate_large_strings(value, max_length, new_path)
                    if isinstance(value, str):
                        total_size += len(value)
                # Если общий размер все еще слишком большой, обрезаем message более агрессивно
                if total_size > max_length and "message" in obj and isinstance(obj["message"], str):
                    original_message = obj["message"]
                    if len(original_message) > 1000:
                        message_start = original_message[:500]
                        message_end = original_message[-200:] if len(original_message) > 700 else ""
                        obj["message"] = f"{message_start}\n\n... (сообщение обрезано, {len(original_message)} символов) ...\n\n{message_end}"
                        logger.info(f"✂️ Агрессивно обрезано message в ToolMessage для инструмента {tool_name}: {len(original_message)} -> {len(obj['message'])} символов")
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    new_path = f"{current_path}[{idx}]"
                    truncate_large_strings(item, max_length, new_path)
        
        # Применяем обрезку к add_data (только если это словарь)
        if isinstance(add_data, dict):
            truncate_large_strings(add_data, MAX_TOOL_MESSAGE_LENGTH)
        elif isinstance(add_data, str) and len(add_data) > MAX_TOOL_MESSAGE_LENGTH:
            # Если add_data - это просто строка, обрезаем её
            original_length = len(add_data)
            add_data = add_data[:MAX_TOOL_MESSAGE_LENGTH] + f"\n\n... (обрезано, было {original_length} символов) ..."
            logger.info(f"✂️ Обрезана строка add_data для инструмента {tool_name}: {original_length} -> {len(add_data)} символов")
        
        # Финальная проверка размера JSON
        try:
            add_data_json = json.dumps(add_data, ensure_ascii=False)
        except (TypeError, ValueError):
            # Если не удается сериализовать, преобразуем в строку
            add_data_json = str(add_data)
            if len(add_data_json) > MAX_TOOL_MESSAGE_LENGTH:
                add_data = str(add_data)[:MAX_TOOL_MESSAGE_LENGTH] + f"\n\n... (обрезано) ..."
                add_data_json = str(add_data)

        # Этап 2 (ROMA_OPTIMIZE.MD): Context offloading.
        # Если результат большой — сохраняем полный вывод на диск (FILES_DIR=/files)
        # и добавляем ссылку как attachment (/files/offloads/...), чтобы фронт мог открыть/скачать файл.
        # Примечание: offload не должен ломать пайплайн, поэтому любые ошибки подавляем.
        try:
            from giga_agent.utils.context_offload import maybe_offload_tool_payload

            # Группируем offload по thread_id (если доступен)
            thread_id_for_offload, _ = extract_thread_id_from_config(config)
            add_data, tool_attachments, off = maybe_offload_tool_payload(
                payload=add_data,
                store_payload=add_data_full,
                tool_name=tool_name or "unknown_tool",
                tool_call_id=get_tool_call_id(action) or "unknown_call",
                thread_id=thread_id_for_offload,
                existing_tool_attachments=tool_attachments,
            )
            # Восстанавливаем giga_attachments в add_data после offloading, если они были сохранены
            # Это нужно для того, чтобы фронтенд мог их найти в payload
            if saved_giga_attachments and isinstance(add_data, dict):
                add_data["giga_attachments"] = saved_giga_attachments
            if off:
                logger.info(
                    f"[context_offload] tool={tool_name} chars={off.original_chars} path={off.url_path}"
                )
                # Пересчитываем JSON строку (теперь должна быть маленькой)
                try:
                    add_data_json = json.dumps(add_data, ensure_ascii=False)
                except Exception:
                    add_data_json = str(add_data)
        except Exception as e:
            logger.warning(f"[context_offload] skipped: {type(e).__name__}: {e}")
        
        # Исключаем list_available_tools и get_tool_details из финальной обрезки
        # Эти инструменты должны возвращать полные данные для корректной работы системы
        if len(add_data_json) > MAX_TOOL_MESSAGE_LENGTH and tool_name not in ["list_available_tools", "get_tool_details"]:
            # Если после всех обрезок размер все еще слишком большой, заменяем на минимальное описание
            if isinstance(add_data, dict):
                tool_result_summary = {
                    "message": f"⚠️ Результат инструмента {tool_name} слишком большой ({len(add_data_json)} символов). "
                               f"Содержимое было обрезано для предотвращения превышения лимита контекста. "
                               f"Используйте инструмент повторно для получения полных данных.",
                    "tool_name": tool_name,
                    "original_size": len(add_data_json),
                    "truncated": True
                }
                # Сохраняем только критически важные поля, если они есть
                if "success" in add_data:
                    tool_result_summary["success"] = add_data["success"]
                if "error" in add_data:
                    tool_result_summary["error"] = add_data["error"]
                # Сохраняем model_name, если он есть
                if "model_name" in add_data:
                    tool_result_summary["model_name"] = add_data["model_name"]
                add_data = tool_result_summary
                logger.warning(f"⚠️ ToolMessage для инструмента {tool_name} был полностью обрезан из-за размера: {len(add_data_json)} символов")
        
        # КРИТИЧЕСКИ ВАЖНО для DeepSeek: создаем ToolMessage с минимальными additional_kwargs
        # Для DeepSeek API нужно удалить additional_kwargs при сериализации, но оставить для фронтенда
        # Патч в deepseek_patch.py удалит additional_kwargs при создании payload
        is_deepseek = is_deepseek_model()
        
        # Создаем ToolMessage с tool_attachments для фронтенда
        # Патч удалит additional_kwargs при отправке в DeepSeek API
        message = ToolMessage(
            tool_call_id=get_tool_call_id(action),
            content=json.dumps(add_data, ensure_ascii=False),
            additional_kwargs={"tool_attachments": tool_attachments} if tool_attachments else {},
        )
        
        if is_deepseek:
            logger.debug(f"[tool_call] ToolMessage создан для DeepSeek с tool_attachments={len(tool_attachments)}, патч удалит additional_kwargs при сериализации")
        
        # ========== СОХРАНЕНИЕ В ГЛОБАЛЬНЫЙ КЭШ ==========
        # Сохраняем успешный вызов инструмента для будущего кэширования
        # Получаем исходный запрос пользователя из state
        try:
            original_user_query = None
            state_messages = state.get("messages", [])
            for msg in reversed(state_messages):
                if hasattr(msg, 'type') and msg.type == "human":
                    original_user_query = msg.content if hasattr(msg, 'content') else str(msg)
                    break
            
            if original_user_query and tool_name:
                # Определяем успешность выполнения
                is_success = True
                if isinstance(add_data, dict):
                    if add_data.get("error") or add_data.get("success") is False:
                        is_success = False
                
                if is_success:
                    # Исключаем критические инструменты из сохранения в кэш
                    # switch_model и openrouter_models должны всегда выполняться с тестированием
                    # Инструменты чтения файлов не кэшируются, так как содержимое файлов может изменяться
                    NON_CACHEABLE_TOOLS = {
                        'switch_model', 'openrouter_models', 'get_current_openrouter_model', 'check_openrouter_limits',
                        'read_file', 'read_document', 'send_file_to_repl', 'send_file_to_llm', 'send_archive_files_to_repl',
                        'extract_archive', 'list_archive_contents', 'code_review', 'transcribe_audio', 'transcribe_audio_from_url'
                    }
                    if tool_name in NON_CACHEABLE_TOOLS:
                        logger.info(f"[QUERY_CACHE] SKIP SAVE - tool '{tool_name}' is non-cacheable (critical tool)")
                    else:
                        # Получаем время выполнения (если есть)
                        exec_time_ms = state.get("_tool_execution_time_ms")
                        
                        # Сохраняем в кэш асинхронно (не блокируем основной поток)
                        user_id = state.get("user_id")
                        tool_args = action.get("args", {})
                        
                        # Для агентов (tinkoff_agent, email_agent и т.д.) ВСЕГДА сохраняем user_request
                        # так как они требуют этот параметр для работы
                        is_agent_tool = tool_name and tool_name.endswith("_agent")
                        
                        if is_agent_tool:
                            # Для агентов сохраняем user_request = исходный запрос пользователя
                            cacheable_params = {"user_request": original_user_query}
                            logger.info(f"[QUERY_CACHE] Agent tool detected, saving user_request param")
                        else:
                            # Фильтруем параметры - не кэшируем динамические данные
                            # (например, code в python инструменте, конкретные ID и т.д.)
                            cacheable_params = {}
                            non_cacheable_keys = {"code", "content", "body", "text", "message", "data"}
                            for key, value in tool_args.items():
                                if key.lower() not in non_cacheable_keys:
                                    cacheable_params[key] = value
                        
                        # Сохраняем в кэш
                        await save_to_query_cache(
                            query=original_user_query,
                            tool_name=tool_name,
                            tool_params=cacheable_params,
                            user_id=user_id,
                            execution_time_ms=exec_time_ms,
                        )
                        logger.info(f"[QUERY_CACHE] CACHE SAVE tool='{tool_name}' params={list(cacheable_params.keys())} query='{original_user_query[:50]}...'")
        except Exception as cache_err:
            logger.warning(f"[QUERY_CACHE] Ошибка при сохранении в кэш: {cache_err}")
        # ========== КОНЕЦ СОХРАНЕНИЯ В КЭШ ==========
        
    except Exception as e:
        traceback.print_exc()
        error_content = _handle_tool_error(e, flag=True)
        
        # Улучшенная обработка ошибок валидации для всех агентов
        # Показываем модели правильный формат с примерами
        if "validation error" in str(e).lower() or "field required" in str(e).lower():
            if tool_name == "email_agent":
                # Специальная обработка для email_agent
                error_content = (
                    f"Ошибка валидации: {error_content}\n\n"
                    f"⚠️ ВАЖНО: Для email_agent параметр называется user_request (НЕ query, НЕ task_type, НЕ action)!\n\n"
                    f"ПРАВИЛЬНЫЙ ФОРМАТ:\n"
                    f'email_agent(user_request="покажи последние письма из ящика alexis")\n'
                    f'email_agent(user_request="прочитать письма", email_account="alexis@example.com")\n\n'
                    f"Исправь вызов, используя параметр user_request с запросом пользователя."
                )
            elif tool_name == "coder_agent":
                # Специальная обработка для coder_agent
                error_content = (
                    f"Ошибка валидации: {error_content}\n\n"
                    f"⚠️ ВАЖНО: Для coder_agent параметр называется task (НЕ query, НЕ user_request, НЕ action)!\n\n"
                    f"ПРАВИЛЬНЫЙ ФОРМАТ:\n"
                    f'coder_agent(task="создать веб-приложение на Python с Flask")\n'
                    f'coder_agent(task="разработать REST API", programming_language="Python")\n\n'
                    f"Исправь вызов, используя параметр task с описанием проекта."
                )
            elif tool_name == "search":
                # Специальная обработка для search
                error_content = (
                    f"Ошибка валидации: {error_content}\n\n"
                    f"⚠️ ВАЖНО: Для search параметр называется queries (множественное число, СПИСОК строк), НЕ query!\n\n"
                    f"ПРАВИЛЬНЫЙ ФОРМАТ:\n"
                    f'search(queries=["Александр Беляев биография"])\n'
                    f'search(queries=["поиск информации", "дополнительный запрос"])\n\n'
                    f"НЕПРАВИЛЬНО (вызовет ошибку):\n"
                    f'search(query="Александр Беляев биография")\n\n'
                    f"Исправь вызов, используя параметр queries со списком запросов, даже для одного запроса."
                )
            elif tool_name == "researcher_agent":
                # Специальная обработка для researcher_agent
                error_content = (
                    f"Ошибка валидации: {error_content}\n\n"
                    f"⚠️ ВАЖНО: Для researcher_agent параметр называется question (НЕ query, НЕ user_request, НЕ action)!\n\n"
                    f"ПРАВИЛЬНЫЙ ФОРМАТ:\n"
                    f'researcher_agent(question="исследуй тему искусственного интеллекта")\n'
                    f'researcher_agent(question="создай отчет о современных технологиях блокчейн")\n\n'
                    f"Исправь вызов, используя параметр question с вопросом/запросом."
                )
            elif tool_name and tool_name.endswith("_agent"):
                # Для остальных агентов используется user_request
                error_content = (
                    f"Ошибка валидации: {error_content}\n\n"
                    f"⚠️ ВАЖНО: Для агентов (например, {tool_name}) параметр называется user_request!\n\n"
                    f"ПРАВИЛЬНЫЙ ФОРМАТ:\n"
                    f'{tool_name}(user_request="запрос пользователя")\n\n'
                    f"Исправь вызов, используя параметр user_request."
                )
        
        message = ToolMessage(
            tool_call_id=get_tool_call_id(action),
            content=error_content,
        )
        
        # ========== ПОМЕТКА КЭША КАК НЕУСПЕШНОГО ПРИ ОШИБКЕ ==========
        # Если это был кэшированный вызов и он завершился с ошибкой,
        # помечаем запись в кэше как неуспешную
        try:
            cache_hit = state.get("cache_hit", False)
            if cache_hit:
                original_user_query = None
                state_messages = state.get("messages", [])
                for msg in reversed(state_messages):
                    if hasattr(msg, 'type') and msg.type == "human":
                        original_user_query = msg.content if hasattr(msg, 'content') else str(msg)
                        break
                
                if original_user_query and tool_name:
                    user_id = state.get("user_id")
                    cache_service = get_cache_service()
                    await cache_service.save_successful_tool_call(
                        query=original_user_query,
                        tool_name=tool_name,
                        tool_params={},
                        user_id=user_id,
                        is_success=False
                    )
                    logger.warning(f"[QUERY_CACHE] Marked cache as FAILED for tool='{tool_name}' due to error")
        except Exception as cache_err:
            logger.warning(f"[QUERY_CACHE] Error marking cache as failed: {cache_err}")
        # ========== КОНЕЦ ПОМЕТКИ КЭША ==========

    return {
        "messages": [message],
        "tool_call_index": tool_call_index,
        "file_ids": file_ids,
    }


def router(state: AgentState) -> Literal["tool_call", "cleanup_tools"]:
    messages = state.get("messages", [])
    if not messages:
        return "cleanup_tools"
    
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tool_call"
    else:
        # Нет tool_calls - значит агент выдал финальный ответ, нужно очистить инструменты
        return "cleanup_tools"


def simple_response_router(state: AgentState) -> Literal["simple_response", "before_agent"]:
    """
    Роутер после классификации запроса.
    Если simple_question И это действительно простое приветствие - идем в simple_response_node для быстрого ответа.
    Иначе - идем в before_agent для обычной обработки.
    """
    request_classification = state.get("request_classification", "complex_task")
    
    # Если это не simple_question, сразу идем в before_agent
    if request_classification != "simple_question":
        return "before_agent"
    
    # Для simple_question проверяем, что это действительно простое приветствие
    # Если нет - идем в before_agent (может потребоваться email_agent и т.д.)
    messages = state.get("messages", [])
    if not messages:
        return "before_agent"
    
    # Извлекаем последнее сообщение пользователя
    last_user_message = None
    for msg in reversed(messages):
        if hasattr(msg, 'type') and msg.type == "human":
            last_user_message = msg.content if hasattr(msg, 'content') else str(msg)
            break
    
    if not last_user_message:
        return "before_agent"
    
    # Извлекаем чистый запрос (убираем теги)
    import re as _re
    clean_query_match = _re.search(r'<task>(.*?)</task>', last_user_message, _re.IGNORECASE | _re.DOTALL)
    if clean_query_match:
        clean_query = clean_query_match.group(1).strip()
    else:
        clean_query = _re.sub(r'<user_info>.*', '', last_user_message, flags=_re.IGNORECASE | _re.DOTALL).strip()[:200]
    
    # ВАЖНО: Проверяем наличие ключевых слов для инструментов
    # Если есть ключевые слова для email, tinkoff и т.д. - идем в before_agent
    clean_query_lower = clean_query.lower().strip()
    
    # Email агент
    email_keywords = ["письм", "почт", "email", "mail", "ящик"]
    if any(kw in clean_query_lower for kw in email_keywords):
        return "before_agent"
    
    # Calendar агент
    calendar_keywords = ["календар", "событи", "встреч", "запланир", "напоминан", "день рождени", "дата"]
    if any(kw in clean_query_lower for kw in calendar_keywords):
        return "before_agent"
    
    # Tinkoff агент (включая графики акций и тикеры)
    tinkoff_keywords = ["портфель", "акци", "tinkoff", "купи", "продай", "котировк", "график", "цена", "стоимость"]
    # Проверка на тикеры акций (SPCE, AAPL, TSLA и т.д. - обычно 2-5 заглавных букв)
    # ВАЖНО: используем глобальный re из начала файла (строка 4: import re)
    ticker_pattern = r'\b[A-Z]{2,5}\b'
    has_ticker = False
    if last_user_message:
        # Используем глобальный модуль re, импортированный в начале файла
        re_module = __import__('re')
        has_ticker = bool(re_module.search(ticker_pattern, last_user_message))
    
    if any(kw in clean_query_lower for kw in tinkoff_keywords) or has_ticker:
        return "before_agent"
    
    # PC агент
    pc_keywords = ["файл", "папк", "директор", "открой", "запусти", "процесс"]
    if any(kw in clean_query_lower for kw in pc_keywords):
        return "before_agent"
    
    # Coder агент
    coder_keywords = ["код", "python", "скрипт", "программ", "создай код"]
    if any(kw in clean_query_lower for kw in coder_keywords):
        return "before_agent"
    
    # Researcher агент
    researcher_keywords = ["найди", "поиск", "исследован", "узнай", "расскажи о"]
    if any(kw in clean_query_lower for kw in researcher_keywords):
        return "before_agent"
    
    # Lawyer агент
    lawyer_keywords = ["закон", "кодекс", "статья", "право", "суд", "иск"]
    if any(kw in clean_query_lower for kw in lawyer_keywords):
        return "before_agent"
    
    # Career агент
    career_keywords = ["резюме", "вакансия", "работ", "hh.ru", "собеседован"]
    if any(kw in clean_query_lower for kw in career_keywords):
        return "before_agent"
    
    # Другие инструменты
    other_keywords = ["проект", "vps", "деплой", "развернуть"]
    if any(kw in clean_query_lower for kw in other_keywords):
        return "before_agent"
    
    # Проверяем, что это действительно простое приветствие
    simple_greetings = ["привет", "здравствуй", "добрый день", "доброе утро", "добрый вечер", 
                       "как дела", "как поживаешь", "что нового", "помоги", "помощь", 
                       "спасибо", "благодарю", "ок", "хорошо", "понял", "да", "нет"]
    words_count = len(clean_query_lower.split())
    is_simple_greeting = words_count <= 5 and any(greeting in clean_query_lower for greeting in simple_greetings)
    
    # Если это простое приветствие - идем в simple_response
    # Иначе - идем в before_agent (может быть simple_question, но требует инструментов)
    if is_simple_greeting:
        return "simple_response"
    else:
        return "before_agent"


workflow = StateGraph(AgentState)
# Добавляем узел классификации запроса как первый узел
workflow.add_node("classify_request", classify_request_node)
workflow.add_node("simple_response", simple_response_node)
workflow.add_node(before_agent)
workflow.add_node(agent)
workflow.add_node(tool_call)
workflow.add_node("cleanup_tools", cleanup_tools_node)
# Классификация запроса - первый узел в цепочке обработки
workflow.add_edge("__start__", "classify_request")
# После классификации проверяем, нужен ли простой ответ
workflow.add_conditional_edges(
    "classify_request",
    simple_response_router,
    {
        "simple_response": "simple_response",
        "before_agent": "before_agent",
    }
)
# Если simple_response вернул ответ, завершаем граф
# НО если simple_response вернул пустой dict (не простое приветствие), продолжаем через before_agent
def simple_response_continue_router(state: AgentState) -> Literal["cleanup_tools", "before_agent"]:
    """
    Роутер после simple_response_node.
    Если simple_response_node вернул ответ (messages обновлены) - идем в cleanup_tools для очистки инструментов.
    Если вернул пустой dict (не простое приветствие) - продолжаем через before_agent.
    """
    messages = state.get("messages", [])
    # Проверяем, есть ли последнее сообщение от AI (значит simple_response_node обработал запрос)
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, 'type') and last_msg.type == "ai":
            # Есть ответ от AI - идем в cleanup_tools для очистки инструментов перед завершением
            return "cleanup_tools"
    
    # Нет ответа - продолжаем через before_agent
    return "before_agent"

workflow.add_conditional_edges(
    "simple_response",
    simple_response_continue_router,
    {
        "cleanup_tools": "cleanup_tools",
        "before_agent": "before_agent",
    }
)
# Обычный путь обработки
workflow.add_edge("before_agent", "agent")
workflow.add_conditional_edges("agent", router, {
    "tool_call": "tool_call",
    "cleanup_tools": "cleanup_tools",
})
workflow.add_edge("tool_call", "agent")
workflow.add_edge("cleanup_tools", END)


graph = workflow.compile()
