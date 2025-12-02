import copy
import json
import os
import re
import traceback
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
    load_llm,
    TOOLS_AGENT_CHECKS,
    run_checks,
)
from giga_agent.prompts.few_shots import FEW_SHOTS_ORIGINAL, FEW_SHOTS_UPDATED
from giga_agent.prompts.main_prompt import SYSTEM_PROMPT
from giga_agent.repl_tools.utils import describe_repl_tool
from giga_agent.tool_server.tool_client import ToolClient
from giga_agent.tool_server.utils import transform_tool
from giga_agent.tools.rag import get_rag_info
from giga_agent.utils.env import load_project_env
from giga_agent.utils.jupyter import JupyterClient, prepend_code
from giga_agent.utils.lang import LANG
from giga_agent.utils.langgraph import inject_tool_args_compat
from giga_agent.utils.mcp import process_mcp_content
from giga_agent.utils.llm import is_llm_gigachat
from giga_agent.utils.deepseek_adapter import (
    convert_messages_for_deepseek,
    ensure_reasoning_content_in_messages,
)
# Применяем патч для langchain-deepseek/langchain-openai
try:
    from giga_agent.utils.deepseek_patch import patch_langchain_deepseek
    patch_langchain_deepseek()
except Exception as e:
    import logging
    logging.getLogger(__name__).warning(f"Не удалось применить патч для DeepSeek: {e}")

load_project_env()

llm = load_llm(is_main=True)

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


def generate_user_info(state: AgentState):
    lang = ""
    if not LANG.startswith("ru"):
        lang = f"\nВыбранный язык пользователя: {LANG}\n"
    instructions = ""
    if not state["messages"]:
        instructions = state.get("instructions", "")
    return f"<user_info>\nТекущая дата: {datetime.today().strftime('%d.%m.%Y %H:%M')}{lang}{instructions}</user_info>"


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


async def before_agent(state: AgentState, config: RunnableConfig = None):
    from giga_agent.config import filter_tools_by_user_tokens
    import logging
    
    # Инициализируем logger в начале функции, до его использования
    logger = logging.getLogger(__name__)
    
    tool_client = ToolClient()
    kernel_id = state.get("kernel_id")
    tools = state.get("tools")
    if not kernel_id:
        kernel_id = (await client.start_kernel())["id"]
        await client.execute(kernel_id, "function_results = []\nSECRETS = {}")
    if not tools:
        tools = await tool_client.get_tools()
    if state["messages"][-1].type == "human":
        user_input = state["messages"][-1].content
        # Логируем оригинальный запрос пользователя для отладки
        logger.info(f"🔍 before_agent: Получен запрос пользователя: '{user_input}'")
        logger.info(f"🔍 before_agent: Содержит 'покажи': {user_input and 'покажи' in user_input}")
        logger.info(f"🔍 before_agent: Содержит 'открыть': {user_input and 'открыть' in user_input}")
        files = state["messages"][-1].additional_kwargs.get("files", [])
        file_prompt = []
        for idx, file in enumerate(files):
            file_prompt.append(f"""Файл загружен по пути: '{file['path']}'""")
            if "image_path" in file:
                file_prompt[
                    -1
                ] += f"\nФайл является изображением его можно отобразить с помощью: '![алт-текст](attachment:{file['image_path']})'."
        file_prompt = (
            "<files_data>" + "\n----\n".join(file_prompt) + "</files_data>"
            if len(file_prompt)
            else ""
        )
        selected = state["messages"][-1].additional_kwargs.get("selected", {})
        selected_items = []
        for key, value in selected.items():
            selected_items.append(f"""![{value}](attachment:{key})""")
        selected_prompt = ""
        if selected_items:
            selected_items = "\n".join(selected_items)
            selected_prompt = (
                f"Пользователь указал на следующие вложения: \n{selected_items}"
            )
        state["messages"][
            -1
        ].content = f"<task>{user_input}</task> Активно планируй и следуй своему плану! Действуй по простым шагам!{generate_user_info(state)}\n{file_prompt}\n{selected_prompt}\nСледующий шаг: "
    
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
        else:
            # Для последующих запросов требуем user_id
            # Формируем более информативное сообщение об ошибке
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
                f"❌ user_id не найден или невалидный в config и state. "
                f"Исходный user_id до нормализации: {user_id_before_normalize}, "
                f"Thread ID: {thread_id_debug or 'не указан'}. "
                f"Отладочная информация: {debug_info}"
            )
            raise ValueError(error_message)
    if user_id:
        logger.info(f"✅ user_id извлечен и валидирован: {user_id}")
        
        # Сохраняем user_id в state для последующих запросов
        # Это гарантирует, что даже если configurable не передается, user_id будет доступен
        if state and isinstance(state, dict):
            state["user_id"] = user_id
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
    if user_id:
        try:
            from giga_agent.utils.user_tokens import get_user_email_accounts_secrets
            email_secrets = await get_user_email_accounts_secrets(user_id)
            if email_secrets:
                secrets.extend(email_secrets)
                logger.info(f"📧 Загружено {len(email_secrets)} секретов почтовых ящиков из БД для user_id={user_id}")
            else:
                logger.debug(f"🔍 Секреты почтовых ящиков не найдены для user_id={user_id}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при загрузке почтовых ящиков из БД: {e}", exc_info=True)
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
    
    # Фильтруем инструменты по токенам пользователя
    logger.info(f"🔍 Начинаю фильтрацию инструментов: всего {len(tools)} инструментов, user_id={user_id}")
    filtered_tools = await filter_tools_by_user_tokens(tools, user_id=user_id, secrets=secrets)
    logger.info(f"📊 Фильтрация завершена: {len(filtered_tools)} инструментов доступны")
    
    # Применяем дополнительные проверки
    final_filtered_tools = []
    for tool in filtered_tools:
        if tool["name"] in TOOLS_AGENT_CHECKS:
            if not await run_checks(tool_name=tool["name"], state=state):
                continue
        final_filtered_tools.append(tool)
    
    # Формируем возвращаемый state с сохранением user_id и secrets
    result_state = {
        "messages": [state["messages"][-1]],
        "kernel_id": kernel_id,
        "tools": final_filtered_tools,
    }
    
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


async def agent(state: AgentState):
    mcp_tools = [
        transform_tool(
            {
                "name": tool["name"],
                "description": tool.get("description", "."),
                "parameters": tool.get("inputSchema", {}),
            }
        )
        for tool in state.get("mcp_tools", [])
    ]
    ch = (
        prompt | llm.bind_tools(state["tools"] + mcp_tools, parallel_tool_calls=False)
    ).with_retry()
    # Очищаем историю сообщений для DeepSeek API
    # DeepSeek требует reasoning_content для assistant сообщений в thinking mode
    # Создаем новые объекты сообщений с правильной структурой вместо модификации in-place
    cleaned_messages = []
    import logging
    logger = logging.getLogger(__name__)
    
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
        logger.debug(f"🔍 DeepSeek модель обнаружена, обрабатываем {len(state['messages'])} сообщений для reasoning_content")
        
        for idx, msg in enumerate(state["messages"]):
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
        cleaned_messages = state["messages"]
    
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
    
    try:
        message = await ch.ainvoke(
            {
                "messages": cleaned_messages,
                "rag_info": get_rag_info(state.get("collections", [])),
                "user_instructions": get_user_notes(state),
                "user_secrets": await get_user_secrets(state),
            }
        )
    except Exception as e:
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
        raise
    message.additional_kwargs.pop("function_call", None)
    message.additional_kwargs["rendered"] = True
    
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
            
            # Проверяем, что reasoning_content является строкой и не пустой
            if reasoning_content and isinstance(reasoning_content, str) and reasoning_content.strip():
                # Убеждаемся, что message.content является строкой
                if not isinstance(message.content, str):
                    message.content = str(message.content) if message.content else ""
                
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
    
    return {"messages": [message]}


async def tool_call(state: AgentState, config: RunnableConfig, store: BaseStore):
    import logging
    logger = logging.getLogger(__name__)
    
    action = copy.deepcopy(state["messages"][-1].tool_calls[0])
    is_frontend_tool = False
    file_ids = []  # Инициализируем file_ids в начале функции
    for tool in state.get("mcp_tools", []):
        if tool.get("name") == action.get("name"):
            is_frontend_tool = True
            break
    if is_frontend_tool:
        value = interrupt(
            {
                "type": "tool_call",
                "tool_name": action.get("name"),
                "args": action.get("args"),
            }
        )
    else:
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
            action["args"]["code"] = get_code_arg(state["messages"][-1].content)
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
                        "id": "123",
                    },
                    state,
                    None,
                )
                injected_args = injection_payload["args"]
                logger.debug(f"🔍 После инъекции для {tool_name}: injected_args keys={list(injected_args.keys())}")
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
                            "id": "123",
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
                # Для остальных инструментов используем tool_client
                result = await tool_client.aexecute(tool_name, action.get("args"))
            try:
                result = json.loads(result)
            except Exception as e:
                pass
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

        if result:
            add_data = {
                "data": result,
                "message": message
                + f"Результат функции сохранен в переменную `function_results[{tool_call_index}]['data']` ",
            }
            await client.execute(
                state.get("kernel_id"), f"function_results.append({repr(add_data)})"
            )
            if (
                len(json.dumps(result, ensure_ascii=False)) > 10000 * 4
                and action.get("name") not in AGENT_MAP
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
                result = {"result": result, "message": message}
            add_data = result
        tool_attachments = []
        # file_ids уже инициализирован в начале функции
        if isinstance(result, dict) and "giga_attachments" in result:
            add_data = result
            attachments = result.pop("giga_attachments")
            file_ids = [attachment["file_id"] for attachment in attachments]
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
                attachment_path = attachment.get("path") or attachment.get("file_url_path") or attachment["file_id"]
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
                    await store.aput(
                        ("attachments",),
                        attachment["file_id"],
                        store_attachment,
                        ttl=None,
                        index=False,
                    )

                tool_attachments.append(
                    {
                        "type": attachment["type"],
                        "file_id": attachment["file_id"],
                    }
                )
        # КРИТИЧЕСКИ ВАЖНО для DeepSeek: создаем ToolMessage с минимальными additional_kwargs
        # Для DeepSeek API нужно удалить additional_kwargs при сериализации, но оставить для фронтенда
        # Патч в deepseek_patch.py удалит additional_kwargs при создании payload
        is_deepseek = is_deepseek_model()
        
        # Создаем ToolMessage с tool_attachments для фронтенда
        # Патч удалит additional_kwargs при отправке в DeepSeek API
        message = ToolMessage(
            tool_call_id=action.get("id", str(uuid4())),
            content=json.dumps(add_data, ensure_ascii=False),
            additional_kwargs={"tool_attachments": tool_attachments} if tool_attachments else {},
        )
        
        if is_deepseek:
            logger.debug(f"🔧 ToolMessage создан для DeepSeek с tool_attachments={len(tool_attachments)}, патч удалит additional_kwargs при сериализации")
    except Exception as e:
        traceback.print_exc()
        message = ToolMessage(
            tool_call_id=action.get("id", str(uuid4())),
            content=_handle_tool_error(e, flag=True),
        )

    return {
        "messages": [message],
        "tool_call_index": tool_call_index,
        "file_ids": file_ids,
    }


def router(state: AgentState) -> Literal["tool_call", "__end__"]:
    if state["messages"][-1].tool_calls:
        return "tool_call"
    else:
        return "__end__"


workflow = StateGraph(AgentState)
workflow.add_node(before_agent)
workflow.add_node(agent)
workflow.add_node(tool_call)
workflow.add_edge("__start__", "before_agent")
workflow.add_edge("before_agent", "agent")
workflow.add_conditional_edges("agent", router)
workflow.add_edge("tool_call", "agent")


graph = workflow.compile()
