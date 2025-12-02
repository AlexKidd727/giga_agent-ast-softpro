"""
Конфигурация агента кодера
"""

from typing import TypedDict, Annotated, List, Dict, Optional
from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.utils.env import load_project_env
from giga_agent.utils.llm import load_llm

load_project_env()

llm = load_llm().with_config(tags=["nostream"])


class ConfigSchema(TypedDict):
    """Схема конфигурации для агента кодера"""
    save_files: bool
    print_messages: bool
    project_id: Optional[str]


class CoderState(TypedDict):
    """Состояние агента кодера"""
    task: str  # Задача/требования к проекту
    agent_messages: Annotated[list[AnyMessage], add_messages]  # Сообщения агента
    project_prompt: str  # Промпт проекта
    programming_language: Optional[str]  # Язык программирования
    database: Optional[str]  # База данных
    selected_technologies: List[str]  # Выбранные технологии
    project_structure: List[Dict]  # Структура проекта (файлы и папки)
    project_files: Dict[str, str]  # Сгенерированные файлы {file_path: content}
    analysis_messages: Annotated[list[AnyMessage], add_messages]  # Сообщения анализа
    generation_status: Dict  # Статус генерации
    done: Optional[str]  # Сообщение о завершении

