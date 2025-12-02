import asyncio
import json
import os
from typing import TypedDict, Annotated, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.agents.browser_use import browser_task
from giga_agent.agents.calendar_agent.graph import calendar_agent
from giga_agent.agents.coder_agent.graph import coder_agent
from giga_agent.agents.email_agent.graph import email_agent
from giga_agent.agents.gis_agent.graph import city_explore
from giga_agent.agents.landing_agent.graph import create_landing
from giga_agent.agents.lean_canvas import lean_canvas
from giga_agent.agents.meme_agent.graph import create_meme
# Временно отключен pc_agent
# from giga_agent.agents.pc_agent.graph import pc_agent
from giga_agent.agents.podcast.graph import podcast_generate
from giga_agent.agents.presentation_agent.graph import generate_presentation
from giga_agent.agents.researcher.graph import researcher_agent
from giga_agent.agents.tinkoff_agent.graph import tinkoff_agent
from giga_agent.repl_tools.llm import summarize
from giga_agent.repl_tools.sentiment import get_embeddings, predict_sentiments
from giga_agent.tools.another import ask_about_image, gen_image, search
from giga_agent.tools.github import (
    get_pull_request,
    get_workflow_runs,
    list_pull_requests,
)
from giga_agent.tools.rag import get_documents, has_collections
from giga_agent.tools.repl import shell
from giga_agent.tools.salute import salute_say
from giga_agent.tools.scraper import get_urls
from giga_agent.tools.vk import vk_get_comments, vk_get_last_comments, vk_get_posts
from giga_agent.tools.weather import weather
from giga_agent.utils.env import load_project_env
from giga_agent.utils.llm import load_llm
from giga_agent.utils.types import Collection
from giga_agent.utils.user_tokens import (
    has_user_tinkoff_token,
    has_user_github_token,
    has_user_google_calendar_credentials,
    has_user_email_config
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


llm = load_llm()

if os.getenv("REPL_FROM_MESSAGE", "1") == "1":
    from giga_agent.tools.repl.message_tool import python
else:
    from giga_agent.tools.repl.args_tool import python


MCP_CONFIG = json.loads(os.getenv("GIGA_AGENT_MCP_CONFIG", "{}").strip())

TOOLS_REQUIRED_ENVS = {
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
    researcher_agent.name: ["TAVILY_API_KEY"],
    browser_task.name: ["DONT_NEED_RIGHT_NOW"],
    get_documents.name: [
        "LANGCONNECT_API_URL",
        "LANGCONNECT_API_SECRET_TOKEN",
    ],
    salute_say.name: ["SALUTE_SPEECH"],
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
    get_workflow_runs.name: "github",
    list_pull_requests.name: "github",
    get_pull_request.name: "github",
}


async def has_required_user_token(tool_name: str, user_id: Optional[str] = None, secrets: Optional[list] = None) -> bool:
    """
    Проверяет наличие требуемого токена у пользователя для инструмента.
    Возвращает True только если токен есть у пользователя (без fallback на env).
    Если user_id не указан, пытается найти админа по username "admin".
    
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
    
    for tool in tools:
        # tools приходят как словари с ключом "name"
        tool_name = tool.get("name") if isinstance(tool, dict) else (tool.name if hasattr(tool, "name") else None)
        
        if not tool_name:
            # Если не удалось определить имя, пропускаем
            logger.warning(f"⚠️ Не удалось определить имя инструмента: tool type={type(tool)}, tool={tool}")
            continue
        
        logger.debug(f"🔍 Проверяю инструмент: name='{tool_name}', type={type(tool)}")
        
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
        salute_say,
        # VK TOOLS
        vk_get_posts,
        vk_get_comments,
        vk_get_last_comments,
        # GITHUB TOOLS
        get_workflow_runs,
        list_pull_requests,
        get_pull_request,
    ]
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
        email_agent,
    ]
)

TOOLS = (
    [
        # REPL
        python,
        shell,
    ]
    + AGENTS
    + SERVICE_TOOLS
)


REPL_TOOLS = [predict_sentiments, summarize, get_embeddings]

AGENT_MAP = {agent.name: agent for agent in AGENTS}
