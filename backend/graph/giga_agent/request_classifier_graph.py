"""
Граф для классификации типа запроса пользователя.

Примечание (ROMA optimization, stage-1):
Помимо старой 4-классовой классификации (simple/complex question/task),
добавляем MECE task_type (RETRIEVE/THINK/WRITE/CODE_INTERPRET/IMAGE_GENERATION),
чтобы затем выбирать модель и набор инструментов более экономно и точнее.
"""
import logging
import json
from typing import Literal

from langchain_core.messages import HumanMessage
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.config import RunnableConfig

from giga_agent.config import AgentState
from giga_agent.utils.llm import load_llm
from giga_agent.utils.task_type import (
    normalize_task_type,
    task_type_from_request_classification,
)

logger = logging.getLogger(__name__)

# Промпт для классификации запроса пользователя
# Важно: просим JSON, чтобы один вызов возвращал и request_classification, и task_type.
REQUEST_CLASSIFICATION_PROMPT = """Ты - классификатор запросов пользователя. Твоя задача - определить тип запроса.

Проанализируй запрос пользователя и выбери ОДИН из следующих типов:

1. "simple_question" - простой вопрос, на который можно ответить сразу без поиска информации и без использования инструментов (например: "Привет", "Как дела?", "Что такое Python?")

2. "complex_question" - сложный вопрос, требующий поиска информации перед ответом (например: "Какая погода в Москве?", "Найди информацию о...", "Что происходит в мире?")

3. "simple_task" - простая задача, требующая одного вызова инструмента (например: "Создай файл test.txt", "Покажи содержимое файла", "Выполни код: print('hello')")

4. "complex_task" - сложная задача, требующая множественных вызовов инструментов или работы агента (например: "Создай веб-приложение", "Проанализируй код и исправь ошибки", "Сгенерируй проект")

Также выбери MECE тип задачи task_type (ОДИН из):
- "RETRIEVE" (поиск/получение данных извне, RAG, API)
- "THINK" (анализ/сравнение/логика без обязательных инструментов)
- "WRITE" (создание текста/документа/контента)
- "CODE_INTERPRET" (код/REPL/обработка данных)
- "IMAGE_GENERATION" (генерация изображений/визуализаций)

ВАЖНО: Верни ТОЛЬКО JSON без пояснений. Формат:
{{"request_classification":"simple_question|complex_question|simple_task|complex_task","task_type":"RETRIEVE|THINK|WRITE|CODE_INTERPRET|IMAGE_GENERATION"}}

Запрос пользователя: {user_request}
"""


def _parse_classifier_json(raw: str) -> dict:
    """
    Безопасный парсер JSON от LLM.

    Примечание:
    - Если модель вернула "лишний текст", пытаемся вытащить первый JSON-объект.
    - Никогда не падаем; возвращаем {} при ошибке.
    """
    if not raw or not isinstance(raw, str):
        return {}
    s = raw.strip()
    # Быстрый путь: чистый JSON
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    # Попытка вытащить {...}
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(s[start : end + 1])
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


async def classify_request_node(state: AgentState, config: RunnableConfig = None) -> dict:
    """
    Узел графа для классификации типа запроса пользователя.
    
    Args:
        state: Состояние агента с сообщениями
        config: Конфигурация выполнения
    
    Returns:
        Словарь с полем request_classification
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Получаем сообщения из state
    messages = state.get("messages", [])
    
    # Проверяем, есть ли уже классификация в state
    existing_classification = state.get("request_classification")
    existing_task_type = normalize_task_type(state.get("task_type"))
    if existing_classification and existing_task_type:
        logger.info(
            f"[classify_request_node] using existing classification: '{existing_classification}', "
            f"task_type='{existing_task_type}'"
        )
        return {"request_classification": existing_classification, "task_type": existing_task_type}
    
    # Извлекаем последнее сообщение пользователя
    user_input = None
    if messages:
        for msg in reversed(messages):
            if hasattr(msg, 'type') and msg.type == "human":
                user_input = msg.content if hasattr(msg, 'content') else str(msg)
                break
    
    if not user_input or not user_input.strip():
        logger.warning("⚠️ classify_request_node: Пустой запрос, возвращаем complex_task")
        # Fallback: complex_task -> THINK
        return {"request_classification": "complex_task", "task_type": "THINK"}
    
    # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: Начало классификации
    # Примечание: не используем эмоджи в логах/терминале (Windows окружение)
    print("[classify_request_node] start")
    print(f"[classify_request_node] user_input='{user_input}'")
    print(f"[classify_request_node] user_input_len={len(user_input) if user_input else 0}")
    logger.info("[classify_request_node] start")
    logger.info(f"[classify_request_node] user_input='{user_input}'")
    logger.info(f"[classify_request_node] user_input_len={len(user_input) if user_input else 0}")
    
    try:
        # КРИТИЧЕСКИ ВАЖНО: Используем LLM БЕЗ инструментов для классификации
        # Загружаем свежий экземпляр LLM без привязки инструментов для минимального использования токенов
        # Используем tag=None чтобы получить базовую модель без дополнительных настроек
        logger.info("[classify_request_node] loading LLM for classification (tag=None, is_main=False)")
        classification_llm = load_llm(tag=None, is_main=False)
        
        # Убеждаемся, что у LLM нет привязанных инструментов
        # Проверяем наличие bound_tools и удаляем их если есть
        if hasattr(classification_llm, 'bound_tools'):
            if classification_llm.bound_tools:
                logger.warning("⚠️ classify_request_node: LLM имеет привязанные инструменты, пытаемся их удалить")
                # Пытаемся использовать unbind_tools если доступен
                if hasattr(classification_llm, 'unbind_tools'):
                    classification_llm = classification_llm.unbind_tools()
                    logger.info("[classify_request_node] tools removed via unbind_tools")
                else:
                    # Если unbind_tools недоступен, загружаем новый экземпляр
                    logger.warning("⚠️ classify_request_node: unbind_tools недоступен, загружаем новый экземпляр")
                    classification_llm = load_llm(tag=None, is_main=False)
            else:
                logger.info("[classify_request_node] LLM has no bound tools - OK")
        else:
            logger.info("[classify_request_node] LLM has no bound_tools attr - OK")
        
        # Дополнительная проверка: убеждаемся, что нет bind_tools в конфигурации
        if hasattr(classification_llm, 'get_graph') or hasattr(classification_llm, 'bind_tools'):
            # Если это Runnable с возможностью bind_tools, создаем простой вызов без bind
            logger.info("[classify_request_node] LLM has bind_tools/get_graph, not used")
            pass
        
        # Создаем простой промпт для классификации
        prompt = REQUEST_CLASSIFICATION_PROMPT.format(user_request=user_input)
        logger.info(f"[classify_request_node] prompt_len={len(prompt)}")
        logger.info(f"[classify_request_node] prompt_head={prompt[:500]}")
        
        # Вызываем LLM без инструментов для быстрой классификации
        # Используем простой HumanMessage без дополнительных параметров
        logger.info("[classify_request_node] sending to LLM without tools")
        response = await classification_llm.ainvoke([HumanMessage(content=prompt)])
        
        # Извлекаем ответ
        raw_response = response.content if hasattr(response, 'content') else str(response)
        parsed = _parse_classifier_json(raw_response)
        classification = str(parsed.get("request_classification", "")).strip().lower()
        task_type = normalize_task_type(str(parsed.get("task_type", "")).strip())
        
        logger.info(f"[classify_request_node] raw_response='{raw_response}'")
        logger.info(f"[classify_request_node] normalized_request_classification='{classification}'")
        logger.info(f"[classify_request_node] normalized_task_type='{task_type}'")
        
        # Проверяем, что ответ валидный
        valid_types = ["simple_question", "complex_question", "simple_task", "complex_task"]
        logger.info(f"[classify_request_node] valid_types={valid_types}")
        
        if classification not in valid_types:
            # Fallback для старого поведения: иногда модель возвращает слово вместо JSON
            # (или возвращает лишний текст). Пытаемся найти подстроку.
            logger.info("[classify_request_node] request_classification not exact match; trying substring search")
            for valid_type in valid_types:
                if valid_type in classification:
                    classification = valid_type
                    break

        if classification not in valid_types:
            logger.warning(
                f"[classify_request_node] could not parse request_classification from response, "
                f"defaulting to complex_task; raw='{raw_response}'"
            )
            classification = "complex_task"

        if not task_type:
            # Если task_type не пришёл или не распарсился — выводим его из request_classification
            task_type = task_type_from_request_classification(classification)

        print(f"[classify_request_node] classified='{classification}', task_type='{task_type}'")
        logger.info(f"[classify_request_node] classified='{classification}', task_type='{task_type}'")
        return {"request_classification": classification, "task_type": task_type}
            
    except Exception as e:
        import traceback
        logger.error(f"❌❌❌ classify_request_node: ОШИБКА при классификации запроса '{user_input}': {e}", exc_info=True)
        logger.error(f"❌❌❌ classify_request_node: Traceback: {traceback.format_exc()}")
        # В случае ошибки возвращаем complex_task для безопасности
        return {"request_classification": "complex_task", "task_type": "THINK"}


# Создание графа классификации запроса
request_classifier_workflow = StateGraph(AgentState)
request_classifier_workflow.add_node("classify_request", classify_request_node)
request_classifier_workflow.add_edge(START, "classify_request")
request_classifier_workflow.add_edge("classify_request", END)

# Компилируем граф
request_classifier_graph = request_classifier_workflow.compile()
