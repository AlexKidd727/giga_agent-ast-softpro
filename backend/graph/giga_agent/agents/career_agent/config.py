"""
Конфигурация карьерного агента
"""

from typing import Annotated, TypedDict, Optional
from typing_extensions import NotRequired
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage


class CareerAgentState(TypedDict):
    """Состояние карьерного агента"""
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str
    resume_data: NotRequired[Optional[dict]]  # Данные резюме пользователя
    current_vacancy: NotRequired[Optional[dict]]  # Текущая анализируемая вакансия
    search_results: NotRequired[Optional[list]]  # Результаты поиска вакансий
    skill_match_result: NotRequired[Optional[dict]]  # Результат сопоставления навыков
    improvement_plan: NotRequired[Optional[dict]]  # План улучшения резюме
    qualification_plan: NotRequired[Optional[dict]]  # План повышения квалификации
    secrets: NotRequired[Optional[list]]  # Секреты пользователя (телефон и т.д.)
    auth_waiting_for_code: NotRequired[Optional[bool]]  # Флаг ожидания кода из SMS
    auth_session_id: NotRequired[Optional[str]]  # ID сессии для авторизации

