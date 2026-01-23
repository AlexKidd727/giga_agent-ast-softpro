"""
MECE TaskType (по мотивам ROMA).

Примечание (зачем этот модуль):
- В проекте уже есть классификация запроса на 4 класса (simple/complex question/task),
  но для экономии токенов и более точного выбора модели/инструментов полезнее иметь
  MECE типы задач (RETRIEVE/THINK/WRITE/CODE_INTERPRET/IMAGE_GENERATION).

TODO(roma-optimize, stage-1):
- Использовать TaskType для выбора модели и набора инструментов (policy routing).
- Постепенно заменить "request_classification" на "task_type" там, где это безопасно.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class TaskType(str, Enum):
    """MECE классификация задач."""

    RETRIEVE = "RETRIEVE"  # External data acquisition (search, APIs, RAG)
    THINK = "THINK"  # Analysis/reasoning/decision making
    WRITE = "WRITE"  # Content generation/synthesis
    CODE_INTERPRET = "CODE_INTERPRET"  # Code execution, data processing, REPL
    IMAGE_GENERATION = "IMAGE_GENERATION"  # Visual content creation

    @classmethod
    def from_string(cls, value: str) -> "TaskType":
        if not value:
            raise ValueError("TaskType value is empty")
        return cls(value.strip().upper())


def normalize_task_type(value: Optional[str]) -> Optional[str]:
    """
    Нормализует строку task_type до канонического значения Enum или возвращает None.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return TaskType.from_string(value).value
    except Exception:
        return None


def task_type_from_request_classification(request_classification: Optional[str]) -> str:
    """
    Fallback-маппинг старой 4-классовой классификации в MECE TaskType.

    Примечание:
    - "simple_question" чаще всего THINK (ответ без инструментов)
    - "complex_question" = RETRIEVE (нужен поиск/данные)
    - "simple_task" = CODE_INTERPRET (часто файл/REPL/инструмент)
    - "complex_task" = THINK (многошаговые задачи, часто требуют планирования/агрегации)
    """
    rc = (request_classification or "").strip().lower()
    if rc == "simple_question":
        return TaskType.THINK.value
    if rc == "complex_question":
        return TaskType.RETRIEVE.value
    if rc == "simple_task":
        return TaskType.CODE_INTERPRET.value
    # default
    return TaskType.THINK.value

