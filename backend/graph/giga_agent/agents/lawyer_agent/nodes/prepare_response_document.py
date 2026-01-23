"""
Узел для подготовки ответных документов (отзывов, возражений, ответов на претензии)
"""

import logging
import re
from typing import Dict, Any, List, Optional
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage

from giga_agent.agents.lawyer_agent.config import LawyerAgentState
from giga_agent.agents.lawyer_agent.utils.paths import get_vector_store_folder, get_project_root
from giga_agent.agents.lawyer_agent.utils.codex_service import CodexService
from giga_agent.agents.lawyer_agent.utils.legal_terms import rank_and_filter_query, PRIORITY_HIGH, PRIORITY_MEDIUM
from giga_agent.agents.lawyer_agent.nodes.search_acts import get_codex_service
from giga_agent.utils.llm import load_llm

logger = logging.getLogger(__name__)

# Инициализируем LLM один раз
_llm = None

def get_llm():
    """Получает или создает экземпляр LLM"""
    global _llm
    if _llm is None:
        _llm = load_llm().with_config(tags=["nostream"])
    return _llm


def load_base_rules() -> str:
    """
    Загружает базовые правила из base_rules.txt
    
    Returns:
        Содержимое файла base_rules.txt или пустая строка
    """
    try:
        vector_store_folder = get_vector_store_folder()
        base_rules_path = vector_store_folder / 'base_rules.txt'
        
        if base_rules_path.exists():
            with open(base_rules_path, 'r', encoding='utf-8') as f:
                rules = f.read()
            logger.info(f"[PREPARE_RESPONSE] Загружены базовые правила из {base_rules_path}")
            return rules
        else:
            logger.warning(f"[PREPARE_RESPONSE] Файл базовых правил не найден: {base_rules_path}")
            return ""
    except Exception as e:
        logger.error(f"[PREPARE_RESPONSE] Ошибка загрузки базовых правил: {e}")
        return ""


def extract_keywords_from_document(document_text: str) -> List[str]:
    """
    Извлекает ключевые слова из исходного документа
    
    Args:
        document_text: Текст исходного документа
        
    Returns:
        Список ключевых слов
    """
    try:
        # Используем ранжирование из legal_terms
        ranked_words = rank_and_filter_query(document_text)
        high_priority = [base for base, priority in ranked_words if priority == PRIORITY_HIGH][:10]
        medium_priority = [base for base, priority in ranked_words if priority == PRIORITY_MEDIUM][:15]
        
        # Объединяем и убираем дубликаты
        keywords = list(dict.fromkeys(high_priority + medium_priority))
        
        # Фильтруем стоп-слова
        stop_words = {'исковое', 'заявление', 'претензия', 'жалоба', 'отзыв', 'возражение', 
                     'истец', 'ответчик', 'суд', 'дело', 'требование', 'требования'}
        filtered_keywords = [kw for kw in keywords if kw.lower() not in stop_words and len(kw.strip()) > 3]
        
        logger.info(f"[PREPARE_RESPONSE] Извлечено ключевых слов: {len(filtered_keywords)}")
        return filtered_keywords
    except Exception as e:
        logger.error(f"[PREPARE_RESPONSE] Ошибка извлечения ключевых слов: {e}")
        return []


def determine_document_type(document_text: str) -> str:
    """
    Определяет тип исходного документа
    
    Args:
        document_text: Текст документа
        
    Returns:
        Тип документа: 'исковое_заявление', 'претензия', 'жалоба' или 'неизвестно'
    """
    text_lower = document_text.lower()
    
    if 'исковое заявление' in text_lower or 'исковое' in text_lower:
        return 'исковое_заявление'
    elif 'претензия' in text_lower:
        return 'претензия'
    elif 'апелляционная жалоба' in text_lower or 'апелляционн' in text_lower:
        return 'апелляционная_жалоба'
    elif 'кассационная жалоба' in text_lower or 'кассационн' in text_lower:
        return 'кассационная_жалоба'
    elif 'жалоба' in text_lower:
        return 'жалоба'
    else:
        return 'неизвестно'


def determine_response_type(document_type: str) -> str:
    """
    Определяет тип ответного документа на основе типа исходного
    
    Args:
        document_type: Тип исходного документа
        
    Returns:
        Тип ответного документа
    """
    mapping = {
        'исковое_заявление': 'отзыв_на_исковое_заявление',
        'претензия': 'ответ_на_претензию',
        'апелляционная_жалоба': 'отзыв_на_апелляционную_жалобу',
        'кассационная_жалоба': 'отзыв_на_кассационную_жалобу',
        'жалоба': 'отзыв_на_жалобу'
    }
    return mapping.get(document_type, 'отзыв')


def search_relevant_context(keywords: List[str], document_text: str) -> str:
    """
    Ищет релевантный контекст из БД кодексов по ключевым словам
    
    Args:
        keywords: Список ключевых слов
        document_text: Текст исходного документа для дополнительного контекста
        
    Returns:
        Релевантный контекст из кодексов
    """
    try:
        codex_service = get_codex_service()
        context_parts = []
        
        # Определяем кодексы, которые могут быть релевантны
        # Анализируем текст документа для определения кодексов
        text_lower = document_text.lower()
        codex_keywords = {
            'Гражданский кодекс Российской Федерации': ['гражданск', 'договор', 'обязательств', 'взыскани', 'возмещени'],
            'Гражданский процессуальный кодекс Российской Федерации': ['исковое', 'суд', 'процесс', 'рассмотрен', 'производств'],
            'Арбитражный процессуальный кодекс Российской Федерации': ['арбитражн', 'арбитраж', 'предпринимател'],
            'Уголовный кодекс Российской Федерации': ['уголовн', 'преступлен', 'наказан'],
            'Уголовно-процессуальный кодекс Российской Федерации': ['уголовн', 'процесс', 'следств'],
            'Трудовой кодекс Российской Федерации': ['трудов', 'работ', 'увольнен'],
            'Налоговый кодекс Российской Федерации': ['налог', 'налогов'],
        }
        
        # Определяем релевантные кодексы
        relevant_codexes = []
        for codex_name, codex_keywords_list in codex_keywords.items():
            if any(kw in text_lower for kw in codex_keywords_list):
                relevant_codexes.append(codex_name)
        
        # Если не определили кодексы, используем общие
        if not relevant_codexes:
            relevant_codexes = [
                'Гражданский кодекс Российской Федерации',
                'Гражданский процессуальный кодекс Российской Федерации'
            ]
        
        # Ищем статьи в релевантных кодексах
        for codex_name in relevant_codexes[:3]:  # Ограничиваем до 3 кодексов
            try:
                codex = codex_service.get_codex_by_name(codex_name)
                if codex:
                    # Ищем статьи по ключевым словам
                    articles = codex_service.search_articles_by_keywords(codex, keywords[:10], limit=5)
                    if articles:
                        context_parts.append(f"\n=== {codex_name} ===")
                        for article in articles[:3]:  # Берем первые 3 статьи
                            article_text = f"Статья {article.number}"
                            if article.title:
                                article_text += f". {article.title}"
                            article_text += f"\n{article.content[:500]}"
                            context_parts.append(article_text)
            except Exception as e:
                logger.warning(f"[PREPARE_RESPONSE] Ошибка поиска в кодексе {codex_name}: {e}")
                continue
        
        context = "\n".join(context_parts)
        logger.info(f"[PREPARE_RESPONSE] Найден контекст из кодексов, длина: {len(context)} символов")
        return context
        
    except Exception as e:
        logger.error(f"[PREPARE_RESPONSE] Ошибка поиска контекста: {e}")
        return ""


def prepare_response_document_node(state: LawyerAgentState) -> Dict[str, Any]:
    """
    Узел для подготовки ответного документа (отзыва, возражений, ответа на претензию)
    
    Логика:
    1. Определяет тип исходного документа
    2. Извлекает ключевые слова из документа
    3. Ищет релевантный контекст из БД кодексов
    4. Загружает base_rules.txt
    5. Генерирует ответный документ с противоположной позицией
    """
    query = state.get("query", "")
    document_text = state.get("document_text", "")
    
    # Если document_text не передан, пытаемся извлечь из query
    if not document_text and query:
        document_text = query
    
    if not document_text:
        logger.warning("[PREPARE_RESPONSE] Нет текста документа для обработки")
        return {
            **state,
            "response_document": "Ошибка: не предоставлен текст исходного документа для подготовки ответа."
        }
    
    logger.info(f"[PREPARE_RESPONSE] Начало подготовки ответного документа, длина исходного: {len(document_text)} символов")
    
    try:
        # Шаг 1: Определение типа документа
        document_type = determine_document_type(document_text)
        response_type = determine_response_type(document_type)
        logger.info(f"[PREPARE_RESPONSE] Тип исходного документа: {document_type}, тип ответа: {response_type}")
        
        # Шаг 2: Извлечение ключевых слов
        keywords = extract_keywords_from_document(document_text)
        logger.info(f"[PREPARE_RESPONSE] Извлечено ключевых слов: {len(keywords)}")
        
        # Шаг 3: Поиск релевантного контекста из БД кодексов
        codex_context = search_relevant_context(keywords, document_text)
        
        # Шаг 4: Загрузка базовых правил
        base_rules = load_base_rules()
        
        # Шаг 5: Формирование промпта для генерации ответного документа
        system_prompt = """Ты - опытный юрист-судебник с юридическим стажем более 15 лет. Твоя задача - подготовить ответный документ (отзыв, возражения или ответ на претензию) на основе предоставленного исходного документа.

ВАЖНЫЕ ПРИНЦИПЫ:
1. Ты должен занять ПРОТИВОПОЛОЖНУЮ позицию по отношению к исходному документу
2. Подготовь обоснованные возражения против требований/позиции из исходного документа
3. Используй юридическую терминологию корректно
4. Ссылайся на конкретные статьи кодексов
5. Структурируй документ правильно (шапка, основания, просительная часть)
6. Избегай фраз, которые подтверждают позицию автора исходного документа
7. Используй нейтральные формулировки
8. Оптимальный размер документа - 5-6 листов
9. Оспаривай требования и по праву, и по размеру

СТРУКТУРА ОТВЕТНОГО ДОКУМЕНТА:
1. Шапка (наименование суда, стороны, номер дела)
2. Название документа (Отзыв на исковое заявление / Ответ на претензию)
3. Основания для возражений:
   - Проверка подсудности
   - Проверка срока исковой давности
   - Правильность определения ответчика
   - Основания для оставления без рассмотрения или прекращения производства
   - Исполнение обязательств (если применимо)
4. Правовые основания (ссылки на статьи кодексов)
5. Просительная часть

Отвечай на русском языке. Форматируй документ правильно."""
        
        user_prompt = f"""Исходный документ:
{document_text[:3000]}

Тип ответного документа: {response_type}

Ключевые слова из исходного документа: {', '.join(keywords[:20])}

Релевантный контекст из кодексов:
{codex_context[:2000]}

Базовые правила подготовки отзывов и возражений:
{base_rules[:2000]}

Задача: Подготовь {response_type.replace('_', ' ')} с противоположной позицией по отношению к исходному документу. 
Используй найденный контекст из кодексов для обоснования возражений. 
Следуй базовым правилам подготовки отзывов и возражений."""
        
        # Шаг 6: Генерация ответного документа через LLM
        llm = get_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        logger.info("[PREPARE_RESPONSE] Генерация ответного документа через LLM...")
        response = llm.invoke(messages)
        response_document = response.content if hasattr(response, 'content') else str(response)
        
        logger.info(f"[PREPARE_RESPONSE] Ответный документ сгенерирован, длина: {len(response_document)} символов")
        
        return {
            **state,
            "response_document": response_document,
            "response_type": response_type,
            "document_type": document_type,
            "keywords": keywords,
            "codex_context": codex_context
        }
        
    except Exception as e:
        logger.error(f"[PREPARE_RESPONSE] Ошибка при подготовке ответного документа: {e}", exc_info=True)
        return {
            **state,
            "response_document": f"Произошла ошибка при подготовке ответного документа: {str(e)}"
        }

