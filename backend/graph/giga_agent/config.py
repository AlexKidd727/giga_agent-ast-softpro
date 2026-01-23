import asyncio
import json
import os
from typing import TypedDict, Annotated, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.agents.browser_use import browser_task
from giga_agent.agents.calendar_agent.graph import calendar_agent
from giga_agent.agents.career_agent.graph import career_agent
from giga_agent.agents.coder_agent.graph import coder_agent, coder_plan, coder_generate
from giga_agent.agents.email_agent.graph import email_agent
from giga_agent.agents.social_media_agent.graph import social_media_agent
from giga_agent.agents.gis_agent.graph import city_explore
from giga_agent.agents.landing_agent.graph import create_landing
from giga_agent.agents.lean_canvas import lean_canvas
from giga_agent.agents.meme_agent.graph import create_meme
# Временно отключен pc_agent
# from giga_agent.agents.pc_agent.graph import pc_agent
from giga_agent.agents.pc_agent.nodes.files import read_file
from giga_agent.agents.podcast.graph import podcast_generate
from giga_agent.agents.presentation_agent.graph import generate_presentation
from giga_agent.agents.researcher.graph import researcher_agent
from giga_agent.agents.tinkoff_agent.graph import tinkoff_agent
from giga_agent.agents.lawyer_agent.graph import lawyer_agent, prepare_response_document
from giga_agent.repl_tools.llm import summarize
from giga_agent.repl_tools.sentiment import get_embeddings, predict_sentiments
from giga_agent.tools.another import ask_about_image, gen_image, search
from giga_agent.tools.github import (
    create_github_repository,
    get_pull_request,
    get_workflow_runs,
    list_pull_requests,
    publish_project_to_github,
)
from giga_agent.tools.rag import get_documents, has_collections
from giga_agent.tools.repl import shell
from giga_agent.tools.salute import salute_say
from giga_agent.tools.scraper import get_urls
from giga_agent.tools.stt import transcribe_audio, transcribe_audio_from_url
from giga_agent.tools.document_reader import read_document
from giga_agent.tools.vk import vk_get_comments, vk_get_last_comments, vk_get_posts
from giga_agent.tools.weather import weather, weather_openmeteo
from giga_agent.tools.mysql import mysql_query
from giga_agent.tools.personalize import personalize
from giga_agent.tools.archive_tools import extract_archive, list_archive_contents
from giga_agent.tools.code_review import code_review
from giga_agent.tools.file_analysis import send_file_to_repl, send_file_to_llm, send_archive_files_to_repl
from giga_agent.tools.tool_registry import list_available_tools, get_tool_details
# OpenRouter tools (опционально, если модуль доступен)
try:
    from giga_agent.tools.openrouter_tools import (
        get_openrouter_models,
        check_openrouter_limits,
        get_current_openrouter_model,
        switch_openrouter_model,
        test_openrouter_model,
        reset_to_startup_openrouter_model,
        # Алиасы инструментов (для совместимости с разными названиями)
        openrouter_models,
        switch_model,
    )
except ImportError:
    # Если модуль недоступен, создаем заглушки
    get_openrouter_models = None
    check_openrouter_limits = None
    get_current_openrouter_model = None
    switch_openrouter_model = None
    test_openrouter_model = None
    reset_to_startup_openrouter_model = None
    openrouter_models = None
    switch_model = None
# Provider tools (переключение между провайдерами LLM)
try:
    from giga_agent.tools.provider_tools import (
        switch_provider,
        get_current_provider,
        list_providers,
    )
except ImportError:
    # Если модуль недоступен, создаем заглушки
    switch_provider = None
    get_current_provider = None
    list_providers = None
from giga_agent.utils.env import load_project_env
from giga_agent.utils.llm import load_llm
from giga_agent.utils.types import Collection
from giga_agent.utils.user_tokens import (
    has_user_tinkoff_token,
    has_user_github_token,
    has_user_google_calendar_credentials,
    has_user_email_config,
    has_user_mysql_config
)

BASEDIR = os.path.abspath(os.path.dirname(__file__))

load_project_env()


class Secret(TypedDict):
    name: str
    value: str
    description: Optional[str]


class AgentState(TypedDict):  # noqa: D101
    messages: Annotated[list[AnyMessage], add_messages]
    kernel_id: str
    tool_call_index: int
    tools: list
    collections: list[Collection]
    mcp_tools: list[dict[str, dict]]
    instructions: str
    secrets: list[Secret]
    user_id: Optional[str]  # Идентификатор пользователя для доступа к его данным
    request_classification: Optional[str]  # Классификация типа запроса: simple_question, complex_question, simple_task, complex_task
    # Примечание (ROMA optimization, stage-1):
    # MECE тип задачи (RETRIEVE/THINK/WRITE/CODE_INTERPRET/IMAGE_GENERATION) для выбора модели/инструментов.
    task_type: Optional[str]


llm = load_llm()

if os.getenv("REPL_FROM_MESSAGE", "1") == "1":
    from giga_agent.tools.repl.message_tool import python
else:
    from giga_agent.tools.repl.args_tool import python


# Парсинг MCP конфигурации с обработкой ошибок
_mcp_config_str = os.getenv("GIGA_AGENT_MCP_CONFIG", "{}").strip()
try:
    MCP_CONFIG = json.loads(_mcp_config_str) if _mcp_config_str else {}
except json.JSONDecodeError as e:
    print(f"[ERROR] Невалидный JSON в GIGA_AGENT_MCP_CONFIG: {e}")
    print(f"[ERROR] Значение: {_mcp_config_str}")
    print("[ERROR] Используется пустая конфигурация MCP. Проверьте формат JSON в .docker.env")
    MCP_CONFIG = {}

TOOLS_REQUIRED_ENVS = {
    # OpenRouter tools
    "get_openrouter_models": ["OPENROUTER_API_KEY"],
    "check_openrouter_limits": ["OPENROUTER_API_KEY"],
    "get_current_openrouter_model": ["OPENROUTER_API_KEY"],
    "switch_openrouter_model": ["OPENROUTER_API_KEY"],
    "test_openrouter_model": ["OPENROUTER_API_KEY"],
    "reset_to_startup_openrouter_model": ["OPENROUTER_API_KEY"],
    # Алиасы OpenRouter tools
    "openrouter_models": ["OPENROUTER_API_KEY"],
    "switch_model": ["OPENROUTER_API_KEY"],
    # Provider tools (переключение между провайдерами)
    "switch_provider": [],  # Проверка ключей внутри тула
    "get_current_provider": [],  # Не требует ключей
    "list_providers": [],  # Не требует ключей
    gen_image.name: ["IMAGE_GEN_NAME"],
    get_urls.name: ["TAVILY_API_KEY"],
    search.name: ["TAVILY_API_KEY"],
    lean_canvas.name: [],
    generate_presentation.name: ["IMAGE_GEN_NAME"],
    create_landing.name: ["IMAGE_GEN_NAME"],
    podcast_generate.name: ["SALUTE_SPEECH"],
    create_meme.name: ["IMAGE_GEN_NAME"],
    city_explore.name: ["TWOGIS_TOKEN"],
    calendar_agent.name: [],  # Google Calendar - опциональные переменные окружения
    # pc_agent.name: [],  # PC Agent - не требует переменных окружения (временно отключен)
    tinkoff_agent.name: [],  # Tinkoff Agent - опциональные переменные окружения
    email_agent.name: [],  # Email Agent - использует секреты из state["secrets"]
    vk_get_posts.name: ["VK_TOKEN"],
    vk_get_comments.name: ["VK_TOKEN"],
    vk_get_last_comments.name: ["VK_TOKEN"],
    get_workflow_runs.name: ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    list_pull_requests.name: ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    get_pull_request.name: ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    create_github_repository.name: ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    publish_project_to_github.name: ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    researcher_agent.name: ["TAVILY_API_KEY"],
    browser_task.name: ["DONT_NEED_RIGHT_NOW"],
    get_documents.name: [
        "LANGCONNECT_API_URL",
        "LANGCONNECT_API_SECRET_TOKEN",
    ],
    salute_say.name: ["SALUTE_SPEECH"],
    mysql_query.name: [],  # MySQL Tool - использует секреты из state["secrets"]
}

TOOLS_AGENT_CHECKS = {get_documents.name: [has_collections]}


async def run_checks(tool_name: str, state: AgentState):
    for check in TOOLS_AGENT_CHECKS[tool_name]:
        if callable(check) and not check(state):
            return False
        if asyncio.iscoroutinefunction(check) and not await check(state):
            return False
    return True


def has_required_envs(tool) -> bool:
    """Проверяет, что для `tool` установлены все обязательные переменные окружения.

    Если тул не указан в `TOOLS_REQUIRED_ENVS`, считаем, что у него нет обязательных
    переменных окружения и включаем его.
    """
    required_env_names = TOOLS_REQUIRED_ENVS.get(tool.name)
    if required_env_names is None:
        return True
    for env_name in required_env_names:
        if isinstance(env_name, str):
            if not os.getenv(env_name):
                return False
        elif callable(env_name):
            if not env_name():
                return False
    return True


def filter_tools_by_env(tools: list) -> list:
    """Возвращает список тулов, прошедших проверку обязательных env переменных."""
    return [tool for tool in tools if has_required_envs(tool)]


# Маппинг инструментов на требуемые токены пользователя
TOOLS_REQUIRED_USER_TOKENS = {
    tinkoff_agent.name: "tinkoff",
    calendar_agent.name: "google_calendar",
    email_agent.name: "email",
    mysql_query.name: "mysql",
    get_workflow_runs.name: "github",
    list_pull_requests.name: "github",
    get_pull_request.name: "github",
    create_github_repository.name: "github",
    publish_project_to_github.name: "github",
}

# Инструменты, доступные только администратору
# ВАЖНО: Используем строковое имя инструмента, так как в filter_tools_by_user_tokens
# инструменты приходят как словари с ключом "name"
ADMIN_ONLY_TOOLS = {
    social_media_agent.name,  # Ожидаемое имя: "social_media_agent"
}

# MCP инструменты, доступные только администратору
# Список инструментов, которые требуют прав администратора для использования
# Можно настроить через переменную окружения GIGA_AGENT_MCP_ADMIN_ONLY_TOOLS
# Формат: JSON массив строк с именами инструментов, например: ["create_news", "update_news", "delete_news"]
_mcp_admin_only_tools_str = os.getenv("GIGA_AGENT_MCP_ADMIN_ONLY_TOOLS", "[]").strip()
try:
    MCP_ADMIN_ONLY_TOOLS = set(json.loads(_mcp_admin_only_tools_str) if _mcp_admin_only_tools_str else [])
except json.JSONDecodeError as e:
    print(f"[ERROR] Невалидный JSON в GIGA_AGENT_MCP_ADMIN_ONLY_TOOLS: {e}")
    print(f"[ERROR] Значение: {_mcp_admin_only_tools_str}")
    print("[ERROR] Используется пустой список. Проверьте формат JSON в .docker.env")
    MCP_ADMIN_ONLY_TOOLS = set()

# Если переменная не задана, используем значения по умолчанию для инструментов работы с сайтом
if not MCP_ADMIN_ONLY_TOOLS:
    # По умолчанию инструменты для публикации/изменения контента на сайте требуют прав администратора
    MCP_ADMIN_ONLY_TOOLS = {
        "create_news", "update_news", "delete_news",
        "create_blog_post", "update_blog_post", "delete_blog_post",
        "create_project", "update_project", "delete_project",
        "create_service", "update_service", "delete_service",
    }


async def is_admin_user(user_id: Optional[str] = None) -> bool:
    """
    Проверяет, является ли пользователь администратором.
    Администратор определяется по полю is_admin в БД.
    
    Args:
        user_id: ID пользователя (UUID) или username для проверки
    
    Returns:
        True если пользователь является администратором, False иначе
    """
    if not user_id:
        return False
    
    try:
        from giga_agent.tasks_app import User, AsyncSessionLocal
        from sqlmodel import select
        import uuid
        
        async with AsyncSessionLocal() as session:
            user = None
            
            # Сначала пытаемся найти по ID (если user_id - это UUID)
            try:
                # Проверяем, является ли user_id валидным UUID
                uuid.UUID(user_id)
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
            except (ValueError, AttributeError):
                # Если user_id не UUID, ищем по username
                pass
            
            # Если не нашли по ID, ищем по username
            if not user:
                result = await session.execute(select(User).where(User.username == user_id))
                user = result.scalar_one_or_none()
            
            if user:
                # Используем поле is_admin, если оно есть, иначе fallback на username == "alexis"
                if hasattr(user, 'is_admin'):
                    return user.is_admin
                else:
                    # Fallback для старых БД без поля is_admin
                    return user.username == "alexis"
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"⚠️ Ошибка при проверке прав администратора для user_id={user_id}: {e}")
    
    return False


async def has_required_user_token(tool_name: str, user_id: Optional[str] = None, secrets: Optional[list] = None) -> bool:
    """
    Проверяет наличие требуемого токена у пользователя для инструмента.
    Возвращает True только если токен есть у пользователя (без fallback на env).
    Если user_id не указан, пытается найти админа по username "alexis".
    
    Args:
        tool_name: Название инструмента
        user_id: ID пользователя
        secrets: Список секретов из state["secrets"]
    
    Returns:
        True если токен есть у пользователя, False иначе
    """
    required_token_type = TOOLS_REQUIRED_USER_TOKENS.get(tool_name)
    
    if not required_token_type:
        # Инструмент не требует токена пользователя
        return True
    
    # Если user_id не указан, функции has_user_*_token сами попытаются найти админа
    # Поэтому не возвращаем False сразу, а передаем None в функции проверки
    
    if required_token_type == "tinkoff":
        return await has_user_tinkoff_token(user_id)
    elif required_token_type == "github":
        return await has_user_github_token(user_id)
    elif required_token_type == "google_calendar":
        return await has_user_google_calendar_credentials(user_id)
    elif required_token_type == "email":
        return has_user_email_config(secrets or [])
    elif required_token_type == "mysql":
        return has_user_mysql_config(secrets or [])
    
    return True


async def filter_tools_by_user_tokens(tools: list, user_id: Optional[str] = None, secrets: Optional[list] = None) -> list:
    """
    Фильтрует инструменты на основе наличия токенов у пользователя.
    Инструменты, требующие токены, доступны только если у пользователя есть соответствующие токены.
    
    Args:
        tools: Список инструментов (словари с ключом "name")
        user_id: ID пользователя
        secrets: Список секретов из state["secrets"]
    
    Returns:
        Отфильтрованный список инструментов
    """
    import logging
    logger = logging.getLogger(__name__)
    
    filtered = []
    logger.info(f"🔍 Начинаю проверку {len(tools)} инструментов. TOOLS_REQUIRED_USER_TOKENS keys: {list(TOOLS_REQUIRED_USER_TOKENS.keys())}")
    logger.info(f"🔍 ADMIN_ONLY_TOOLS: {ADMIN_ONLY_TOOLS}")
    logger.info(f"🔍 social_media_agent.name: {social_media_agent.name}")
    
    # Выводим все имена инструментов для отладки
    tool_names_list = []
    for tool in tools:
        tool_name = tool.get("name") if isinstance(tool, dict) else (tool.name if hasattr(tool, "name") else None)
        if tool_name:
            tool_names_list.append(tool_name)
    logger.info(f"🔍 Список всех инструментов для проверки ({len(tool_names_list)}): {tool_names_list[:20]}...")  # Показываем первые 20
    
    for tool in tools:
        # tools приходят как словари с ключом "name"
        tool_name = tool.get("name") if isinstance(tool, dict) else (tool.name if hasattr(tool, "name") else None)
        
        if not tool_name:
            # Если не удалось определить имя, пропускаем
            logger.warning(f"⚠️ Не удалось определить имя инструмента: tool type={type(tool)}, tool={tool}")
            continue
        
        logger.debug(f"🔍 Проверяю инструмент: name='{tool_name}', type={type(tool)}")
        
        # Проверяем, доступен ли инструмент только админу (обычные инструменты)
        if tool_name in ADMIN_ONLY_TOOLS:
            is_admin = await is_admin_user(user_id)
            logger.info(
                f"🔍 Проверка прав администратора для инструмента '{tool_name}': "
                f"user_id={user_id}, is_admin={is_admin}, ADMIN_ONLY_TOOLS={ADMIN_ONLY_TOOLS}"
            )
            if is_admin:
                filtered.append(tool)
                logger.info(f"✅ Инструмент '{tool_name}' добавлен (пользователь является администратором)")
            else:
                logger.warning(f"❌ Инструмент '{tool_name}' НЕ добавлен (требуются права администратора, user_id={user_id}, is_admin={is_admin})")
            continue
        
        # Проверяем, доступен ли MCP инструмент только админу
        if tool_name in MCP_ADMIN_ONLY_TOOLS:
            is_admin = await is_admin_user(user_id)
            logger.info(
                f"🔍 Проверка прав администратора для MCP инструмента '{tool_name}': "
                f"user_id={user_id}, is_admin={is_admin}, MCP_ADMIN_ONLY_TOOLS={MCP_ADMIN_ONLY_TOOLS}"
            )
            if is_admin:
                filtered.append(tool)
                logger.info(f"✅ MCP инструмент '{tool_name}' добавлен (пользователь является администратором)")
            else:
                logger.warning(f"❌ MCP инструмент '{tool_name}' НЕ добавлен (требуются права администратора, user_id={user_id}, is_admin={is_admin})")
            continue
        
        if tool_name in TOOLS_REQUIRED_USER_TOKENS:
            # Проверяем наличие токена у пользователя
            has_token = await has_required_user_token(tool_name, user_id, secrets)
            logger.info(
                f"🔍 Проверка токена для инструмента '{tool_name}': "
                f"user_id={user_id}, has_token={has_token}, "
                f"required_token_type={TOOLS_REQUIRED_USER_TOKENS.get(tool_name)}"
            )
            if has_token:
                filtered.append(tool)
                logger.info(f"✅ Инструмент '{tool_name}' добавлен (токен найден)")
            else:
                logger.warning(f"❌ Инструмент '{tool_name}' НЕ добавлен (токен не найден для user_id={user_id})")
            # Если токена нет, инструмент не добавляется (недоступен для пользователя)
        else:
            # Инструмент не требует токена пользователя, добавляем его
            filtered.append(tool)
    
    logger.info(f"📊 Фильтрация инструментов завершена: {len(filtered)} из {len(tools)} инструментов доступны")
    return filtered


SERVICE_TOOLS = filter_tools_by_env(
    [
        get_documents,
        weather,
        weather_openmeteo,  # Резервный инструмент погоды (Open-Meteo, без ключа)
        salute_say,
        # STT TOOLS (Speech-to-Text)
        transcribe_audio,
        transcribe_audio_from_url,
        # VK TOOLS
        vk_get_posts,
        vk_get_comments,
        vk_get_last_comments,
        # GITHUB TOOLS
        get_workflow_runs,
        list_pull_requests,
        get_pull_request,
        create_github_repository,
        publish_project_to_github,
        # MYSQL TOOL
        mysql_query,
        # PERSONALIZATION TOOL
        personalize,
        # ARCHIVE TOOLS
        extract_archive,
        list_archive_contents,
        # FILE ANALYSIS TOOLS
        send_file_to_repl,
        send_file_to_llm,
        send_archive_files_to_repl,
        # CODE REVIEW TOOL
        code_review,
        # TOOL REGISTRY TOOLS (для работы с реестром инструментов)
        list_available_tools,
        get_tool_details,
    ]
    + ([tool for tool in [
        get_openrouter_models, 
        check_openrouter_limits, 
        get_current_openrouter_model,
        switch_openrouter_model,
        test_openrouter_model,
        reset_to_startup_openrouter_model,
        # Алиасы OpenRouter tools (для совместимости с разными названиями)
        openrouter_models,
        switch_model,
    ] if tool is not None])
    + ([tool for tool in [
        switch_provider,
        get_current_provider,
        list_providers,
    ] if tool is not None])
)

AGENTS = filter_tools_by_env(
    [
        ask_about_image,
        gen_image,
        get_urls,
        search,
        lean_canvas,
        generate_presentation,
        create_landing,
        podcast_generate,
        create_meme,
        city_explore,
        browser_task,
        researcher_agent,
        # Новые субагенты
        tinkoff_agent,
        calendar_agent,
        # pc_agent,  # Временно отключен
        coder_agent,
        coder_plan,
        coder_generate,
        email_agent,
        social_media_agent,
        career_agent,
        lawyer_agent,
        prepare_response_document,
    ]
)

TOOLS = (
    [
        # Документы
        read_document,
        read_file,  # Инструмент для чтения текстовых файлов
        # REPL
        python,
        shell,
    ]
    + AGENTS
    + SERVICE_TOOLS
)


REPL_TOOLS = [predict_sentiments, summarize, get_embeddings]

AGENT_MAP = {agent.name: agent for agent in AGENTS}
