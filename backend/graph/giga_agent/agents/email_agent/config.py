"""
Конфигурация Email Agent
"""

from typing import TypedDict, Annotated, Optional, List, Dict, Any
from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.utils.llm import load_llm

llm = load_llm().with_config(tags=["nostream"])


class EmailAgentState(TypedDict):
    """Состояние Email Agent"""
    messages: Annotated[List[AnyMessage], add_messages]
    user_request: str
    user_id: str
    email_account: Optional[str]  # Выбранный ящик
    action: str  # read, filter, send, manage
    result: Optional[str]
    error: Optional[str]
    # Хранилище загруженных писем для навигации
    loaded_emails: Optional[Dict[str, Any]]  # Словарь с загруженными письмами: {index: {msg_id, folder, email_account, ...}}
    current_email_index: Optional[int]  # Текущий индекс просматриваемого письма

