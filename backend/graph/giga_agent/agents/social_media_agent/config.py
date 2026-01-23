"""
Конфигурация Social Media Agent
"""

from typing import TypedDict, Annotated, Optional, List, Dict, Any
from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.utils.llm import load_llm

llm = load_llm().with_config(tags=["nostream"])


class SocialMediaAgentState(TypedDict):
    """Состояние Social Media Agent"""
    messages: Annotated[List[AnyMessage], add_messages]
    user_request: str
    user_id: str
    platform: Optional[str]  # Платформа: vk, facebook, instagram, twitter, telegram, website
    action: str  # publish, update, schedule, analytics, manage
    result: Optional[str]
    error: Optional[str]
    # Хранилище для загруженных постов
    loaded_posts: Optional[Dict[str, Any]]  # Словарь с загруженными постами
    current_post_index: Optional[int]  # Текущий индекс просматриваемого поста

