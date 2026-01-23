"""
Граф юридического агента
Упрощенная версия - вся логика внутри инструмента, без LangGraph
"""

import logging
from typing import Annotated
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import Field

from giga_agent.agents.lawyer_agent.nodes.search_acts import search_acts_node
from giga_agent.agents.lawyer_agent.nodes.generate_answer import generate_answer_node
from giga_agent.agents.lawyer_agent.nodes.prepare_response_document import prepare_response_document_node
from giga_agent.utils.request_normalizer import normalize_request

logger = logging.getLogger(__name__)


@tool(parse_docstring=True)
async def lawyer_agent(
    user_request: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Юридический помощник - специализированный агент для работы с правовыми актами и кодексами.
    
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Параметр называется user_request (НЕ query, НЕ task_type, НЕ action)!
    Всегда передавай запрос пользователя в параметр user_request.
    
    ПРАВИЛЬНЫЙ ФОРМАТ ВЫЗОВА:
    lawyer_agent(user_request="расскажи про подачу апелляционной жалобы по уголовному делу")
    lawyer_agent(user_request="статья 389.1 УПК РФ")
    lawyer_agent(user_request="какие права у обвиняемого")
    
    НЕПРАВИЛЬНО (НЕ ДЕЛАЙ ТАК):
    ❌ lawyer_agent(query="расскажи про апелляцию") - параметр query не существует!
    ❌ lawyer_agent(action="search_law") - параметр action не существует!
    
    Основные функции:
    1. ПОИСК ПРАВОВЫХ АКТОВ:
       - Определение кодекса по запросу пользователя
       - Поиск релевантных статей в кодексах
       - Извлечение контекста из найденных статей
       Примеры: "расскажи про подачу апелляционной жалобы по уголовному делу", 
                "как обжаловать решение суда по гражданскому делу"
    
    2. АНАЛИЗ ПРАВОВЫХ НОРМ:
       - Поиск статей по ключевым словам
       - Извлечение релевантных фрагментов
       - Формирование контекста для ответа
       Примеры: "статья 389.1 УПК РФ", "порядок подачи иска в суд"
    
    3. ОТВЕТЫ НА ЮРИДИЧЕСКИЕ ВОПРОСЫ:
       - Генерация ответов на основе найденных правовых актов
       - Ссылки на конкретные статьи кодексов
       - Структурированная подача информации
       Примеры: "какие права у обвиняемого", "сроки обжалования приговора"
    
    Поддерживаемые кодексы:
    - Уголовный кодекс (УК РФ)
    - Уголовно-процессуальный кодекс (УПК РФ)
    - Гражданский кодекс (ГК РФ)
    - Гражданский процессуальный кодекс (ГПК РФ)
    - Арбитражный процессуальный кодекс (АПК РФ)
    - Трудовой кодекс (ТК РФ)
    - Налоговый кодекс (НК РФ)
    - Кодекс об административных правонарушениях (КоАП РФ)
    - Кодекс административного судопроизводства (КАС РФ)
    - И другие кодексы Российской Федерации
    
    ВАЖНО:
    - Папка с текстовыми файлами актов: law/ в корне проекта
    - Векторная база данных кодексов: vector_store/codexes.db
    - Агент автоматически определяет кодекс по запросу
    - Все данные сохраняются с привязкой к user_id для изоляции между пользователями
    
    Args:
        user_request: Запрос пользователя с описанием юридического вопроса
        user_id: Идентификатор пользователя (обязателен для сохранения данных)
    """
    
    logger.info(f"[LAWYER_AGENT] Вызван: user_request='{user_request[:100]}', user_id='{user_id}'")
    
    # Нормализуем запрос: преобразуем неточные запросы в точные и понятные
    normalized_request, normalization_metadata = normalize_request("lawyer", user_request)
    if normalization_metadata.get("normalized", False):
        logger.info(f"[LAWYER_AGENT] Запрос нормализован: '{user_request}' -> '{normalized_request}'")
        user_request = normalized_request
    
    try:
        # Формируем начальное состояние
        initial_state = {
            "messages": [{"role": "user", "content": user_request}],
            "user_id": user_id,
            "query": user_request,
            "mapped_codexes": None,
            "context_terms": [],
            "found_articles": [],
            "context_snippet": None,
            "answer": None
        }
        
        # Шаг 1: Поиск актов (вся логика внутри функции)
        logger.info("[LAWYER_AGENT] Шаг 1: Поиск актов...")
        state_after_search = search_acts_node(initial_state)
        
        # Шаг 2: Генерация ответа на основе найденного контекста
        logger.info("[LAWYER_AGENT] Шаг 2: Генерация ответа...")
        final_state = generate_answer_node(state_after_search)
        
        # Возвращаем ответ
        answer = final_state.get("answer")
        if not answer:
            answer = "Не удалось сформировать ответ. Попробуйте уточнить запрос."
        
        logger.info(f"[LAWYER_AGENT] Ответ сформирован, длина: {len(answer)} символов")
        
        return answer
        
    except Exception as e:
        logger.error(f"[LAWYER_AGENT] Ошибка при выполнении: {e}", exc_info=True)
        return f"Произошла ошибка при обработке запроса: {str(e)}"


@tool(parse_docstring=False)
async def prepare_response_document(
    document_text: Annotated[
        str,
        Field(description="Текст исходного документа (исковое заявление, претензия, жалоба)")
    ],
    user_id: Annotated[
        str,
        Field(description="Идентификатор пользователя (обязателен для сохранения данных)", default="default_user")
    ] = "default_user",
    state: Annotated[dict, InjectedState] = None
) -> str:
    """Инструмент для подготовки ответных документов (отзывов, возражений, ответов на претензии).
    
    Анализирует исходный документ (исковое заявление, претензию, жалобу) и готовит ответный документ 
    с противоположной позицией, используя релевантные статьи кодексов из БД.
    
    Основные функции:
    - Анализ исходного документа: определение типа, извлечение ключевых слов, анализ позиции автора
    - Поиск релевантного контекста: автоматическое определение кодексов, поиск статей по ключевым словам
    - Подготовка ответного документа: отзыв на исковое заявление, ответ на претензию, отзыв на жалобу
    - Использование базовых правил из base_rules.txt для рекомендаций по написанию отзывов
    - Занятие противоположной позиции с обоснованными возражениями
    
    Структура ответного документа включает: шапку, название, основания для возражений (подсудность, 
    срок исковой давности, правильность определения ответчика), правовые основания, просительную часть.
    """
    
    logger.info(f"[PREPARE_RESPONSE] Вызван: длина документа={len(document_text)}, user_id='{user_id}'")
    
    try:
        # Формируем начальное состояние
        initial_state = {
            "messages": [{"role": "user", "content": document_text}],
            "user_id": user_id,
            "query": document_text,
            "document_text": document_text,
            "mapped_codexes": None,
            "context_terms": [],
            "found_articles": [],
            "context_snippet": None,
            "answer": None,
            "response_document": None
        }
        
        # Вызываем узел подготовки ответного документа
        logger.info("[PREPARE_RESPONSE] Подготовка ответного документа...")
        final_state = prepare_response_document_node(initial_state)
        
        # Возвращаем подготовленный документ
        response_document = final_state.get("response_document")
        if not response_document:
            response_document = "Не удалось подготовить ответный документ. Проверьте корректность исходного документа."
        
        logger.info(f"[PREPARE_RESPONSE] Ответный документ подготовлен, длина: {len(response_document)} символов")
        
        return response_document
        
    except Exception as e:
        logger.error(f"[PREPARE_RESPONSE] Ошибка при подготовке ответного документа: {e}", exc_info=True)
        return f"Произошла ошибка при подготовке ответного документа: {str(e)}"
