"""
Конфигурация юридического агента
"""

from typing import Annotated, TypedDict, Optional, List
from typing_extensions import NotRequired
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage


class LawyerAgentState(TypedDict):
    """Состояние юридического агента"""
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str
    query: NotRequired[Optional[str]]  # Исходный запрос пользователя
    mapped_codexes: NotRequired[Optional[List[str]]]  # Определенные кодексы
    context_terms: NotRequired[Optional[List[str]]]  # Ключевые слова для поиска
    found_articles: NotRequired[Optional[List[dict]]]  # Найденные статьи
    context_snippet: NotRequired[Optional[str]]  # Извлеченный контекст
    answer: NotRequired[Optional[str]]  # Сгенерированный ответ
    document_text: NotRequired[Optional[str]]  # Текст исходного документа для подготовки ответа
    response_document: NotRequired[Optional[str]]  # Подготовленный ответный документ
    response_type: NotRequired[Optional[str]]  # Тип ответного документа
    document_type: NotRequired[Optional[str]]  # Тип исходного документа
    keywords: NotRequired[Optional[List[str]]]  # Ключевые слова из исходного документа
    codex_context: NotRequired[Optional[str]]  # Релевантный контекст из кодексов

