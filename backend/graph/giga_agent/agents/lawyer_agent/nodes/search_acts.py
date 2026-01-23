"""
Узел для поиска правовых актов и формирования контекста
"""

import logging
from typing import Dict, Any
from giga_agent.agents.lawyer_agent.config import LawyerAgentState
from giga_agent.agents.lawyer_agent.utils.rag_utils import map_query_to_codex, remove_anchor_words
from giga_agent.agents.lawyer_agent.utils.codex_service import CodexService
from giga_agent.agents.lawyer_agent.utils.legal_terms import rank_and_filter_query, PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW
from giga_agent.agents.lawyer_agent.utils.vector_store import vector_search
from giga_agent.agents.lawyer_agent.utils.db_manager import ensure_databases_initialized
import re

logger = logging.getLogger(__name__)

# Глобальный экземпляр сервиса (инициализируется при первом использовании)
_codex_service = None

def get_codex_service() -> CodexService:
    """Получает или создает экземпляр CodexService"""
    global _codex_service
    if _codex_service is None:
        try:
            # Убеждаемся, что БД инициализированы
            logger.info("Проверка и инициализация БД...")
            ensure_databases_initialized(force_reload=False)
            
            _codex_service = CodexService()
            logger.info("CodexService инициализирован")
        except Exception as e:
            logger.error(f"Ошибка инициализации CodexService: {e}")
            raise
    return _codex_service


def search_acts_node(state: LawyerAgentState) -> Dict[str, Any]:
    """
    Узел для поиска правовых актов по запросу пользователя
    
    Логика:
    1. Определяет кодекс(ы) по запросу
    2. Очищает запрос от слов-якорей
    3. Формирует ключевые слова для поиска
    4. Ищет статьи в кодексах
    5. Извлекает релевантный контекст
    """
    # Используем query из state, если он есть, иначе извлекаем из messages
    query = state.get("query", "")
    
    if not query:
        messages = state.get("messages", [])
        logger.info(f"[LAWYER_AGENT] Извлечение запроса из messages. Тип messages: {type(messages)}, длина: {len(messages) if messages else 0}")
        if messages:
            last_message = messages[-1]
            logger.info(f"[LAWYER_AGENT] Тип last_message: {type(last_message)}, содержимое: {str(last_message)[:200]}")
            # Обрабатываем как словарь или объект
            if isinstance(last_message, dict):
                query = last_message.get("content", "")
                if not query:
                    query = str(last_message)
            elif hasattr(last_message, 'content'):
                query = last_message.content
            else:
                query = str(last_message)
    
    # Очищаем запрос от лишних символов
    if isinstance(query, str):
        query = query.strip()
    
    if not query:
        logger.warning("[LAWYER_AGENT] Нет запроса для поиска")
        return {
            **state,
            "query": "",
            "context_snippet": None,
            "found_articles": []
        }
    
    logger.info(f"[LAWYER_AGENT] Поиск актов для запроса: {query}")
    
    try:
        # Шаг 1: Маппинг кодекса
        mapped_codexes, anchor_words = map_query_to_codex(query)
        logger.info(f"[LAWYER_AGENT] Определенные кодексы: {mapped_codexes}")
        
        if not mapped_codexes:
            logger.warning("[LAWYER_AGENT] Кодекс не определен через маппинг")
            return {
                **state,
                "query": query,
                "mapped_codexes": None,
                "context_terms": [],
                "found_articles": [],
                "context_snippet": None
            }
        
        primary_codex_name = mapped_codexes[0]
        
        # Шаг 2: Очистка запроса от слов-якорей
        cleaned_query = remove_anchor_words(query, anchor_words)
        logger.info(f"[LAWYER_AGENT] Очищенный запрос: {cleaned_query}")
        
        # Шаг 3: Формирование ключевых слов
        query_words = re.findall(r'\b\w{5,}\b', cleaned_query.lower())
        context_terms_list = []
        context_terms_list.extend(query_words[:10])
        
        # Убираем название кодекса из ключевых слов
        if primary_codex_name:
            codex_lower = primary_codex_name.lower()
            codex_words = re.findall(r'\b\w{4,}\b', codex_lower)
            stop_words = {'кодекс', 'российской', 'федерации', 'российская', 'российский', 'российское'}
            codex_words = [w for w in codex_words if w not in stop_words]
            
            context_terms_list = [t for t in context_terms_list 
                                if not any(cw in t.lower() for cw in codex_words)]
        
        # Убираем слова-якоря
        if anchor_words:
            anchor_words_lower = [aw.lower() for aw in anchor_words]
            filtered_context_terms = []
            for term in context_terms_list:
                term_lower = term.lower()
                is_anchor = False
                for anchor_word in anchor_words_lower:
                    if anchor_word == term_lower or anchor_word in term_lower or term_lower in anchor_word:
                        is_anchor = True
                        break
                    anchor_parts = re.findall(r'\b\w{4,}\b', anchor_word)
                    term_parts = re.findall(r'\b\w{4,}\b', term_lower)
                    if any(ap in term_parts for ap in anchor_parts):
                        is_anchor = True
                        break
                if not is_anchor:
                    filtered_context_terms.append(term)
            context_terms_list = filtered_context_terms
        
        # Убираем дубликаты и короткие слова
        context_terms_list = [t for t in context_terms_list if t and len(t.strip()) > 3]
        context_terms_list = list(dict.fromkeys(context_terms_list))
        
        # Используем ранжирование из legal_terms
        ranked_words = rank_and_filter_query(cleaned_query)
        high_priority = [base for base, priority in ranked_words if priority == PRIORITY_HIGH][:5]
        medium_priority = [base for base, priority in ranked_words if priority == PRIORITY_MEDIUM][:7]
        low_priority = [base for base, priority in ranked_words if priority == PRIORITY_LOW][:3]
        
        # Объединяем ранжированные слова с извлеченными
        final_keywords = list(dict.fromkeys(high_priority + medium_priority + low_priority + context_terms_list))
        
        # Фильтруем стоп-слова (как в lawyer_helpers_base, строки 6786-6789)
        keyword_stop_words = {'найди', 'найти', 'статья', 'статью', 'расскажи', 'подскажи', 'прошу', 'покажи', 
                             'про', 'как', 'что', 'для', 'это', 'или', 'быть', 'имеет', 'может', 'кодекс',
                             'кодекса', 'кодексу', 'кодексом', 'кодексе', 'российской', 'федерации'}
        filtered_keywords = [kw for kw in final_keywords 
                            if kw.lower() not in keyword_stop_words and len(kw.strip()) > 2]
        
        # Если после фильтрации осталось мало слов, добавляем обратно некоторые важные
        if len(filtered_keywords) < 3 and len(final_keywords) > len(filtered_keywords):
            # Добавляем обратно высокоприоритетные слова, даже если они в стоп-словах
            for kw in high_priority:
                if kw not in filtered_keywords and len(kw.strip()) > 2:
                    filtered_keywords.append(kw)
        
        final_keywords = filtered_keywords if filtered_keywords else final_keywords
        
        logger.info(f"[LAWYER_AGENT] Итоговые ключевые слова (после фильтрации стоп-слов): {final_keywords}")
        
        # Шаг 4: Инициализация CodexService
        codex_service = get_codex_service()
        
        # Шаг 5: Поиск кодекса
        codex = codex_service.get_codex_by_name(primary_codex_name)
        if not codex:
            logger.warning(f"[LAWYER_AGENT] Кодекс '{primary_codex_name}' не найден в БД")
            return {
                **state,
                "query": query,
                "mapped_codexes": mapped_codexes,
                "context_terms": final_keywords,
                "found_articles": [],
                "context_snippet": None
            }
        
        logger.info(f"[LAWYER_AGENT] Кодекс найден: {codex.name}")
        
        # Шаг 5.5: ПРИОРИТЕТНЫЙ ПОИСК - извлечение номера статьи и прямой поиск в БД
        # Используем расширенные паттерны из lawyer_helpers_base для надежного извлечения номера статьи
        article_number = None
        query_lower = query.lower()
        article_patterns = [
            r'статья\s+(\d+(?:\.\d+)?)',  # "статья 335", "статья 335.1"
            r'ст\.\s*(\d+(?:\.\d+)?)',     # "ст. 335", "ст.335"
            r'ст\s+(\d+(?:\.\d+)?)',       # "ст 335"
            r'(\d+(?:\.\d+)?)\s+статья',   # "335 статья"
            r'статья\s+№\s*(\d+(?:\.\d+)?)',  # "статья № 335"
            r'№\s*(\d+(?:\.\d+)?)\s+статья',  # "№ 335 статья"
            # Добавляем паттерн для случая, когда число стоит перед названием кодекса
            r'\b(\d{3,}(?:\.\d+)?)\s+(?:ук|уголовный|упк|гпк|апк|гк|тк|нк|коап|кас)',  # "335 УК", "335 Уголовный кодекс"
            r'\b(\d{3,}(?:\.\d+)?)\s+(?:рф|кодекс)',  # "335 РФ", "335 кодекс"
        ]
        
        for pattern in article_patterns:
            match = re.search(pattern, query_lower, re.IGNORECASE)
            if match:
                article_number = match.group(1).strip()
                logger.info(f"[LAWYER_AGENT] Обнаружен номер статьи в запросе: {article_number} (паттерн: {pattern})")
                break
        
        # Если не нашли через паттерны, пробуем найти просто число из 3+ цифр в начале запроса
        # Это для случаев типа "335 УК РФ" или "337 Уголовный кодекс"
        if not article_number:
            # Ищем число из 3+ цифр, которое может быть номером статьи
            number_match = re.search(r'\b(\d{3,}(?:\.\d+)?)\b', query_lower)
            if number_match:
                potential_number = number_match.group(1)
                # Проверяем, что это не год (1900-2100) и не слишком большое число
                if not (1900 <= int(potential_number.split('.')[0]) <= 2100):
                    # Проверяем, что после числа идет что-то связанное с кодексом
                    number_pos = number_match.start()
                    text_after = query_lower[number_pos + len(potential_number):].strip()
                    codex_indicators = ['ук', 'уголовный', 'упк', 'гпк', 'апк', 'гк', 'тк', 'нк', 'коап', 'кас', 'рф', 'кодекс', 'статья']
                    if any(indicator in text_after[:20] for indicator in codex_indicators):
                        article_number = potential_number
                        logger.info(f"[LAWYER_AGENT] Обнаружен номер статьи в запросе (по контексту): {article_number}")
        
        # ПРИОРИТЕТ: Если есть кодекс и номер статьи, используем прямой поиск в БД
        # Это обеспечивает однозначность и точность поиска (как в lawyer_helpers_base)
        articles = []
        article_found_by_number = False
        if article_number:
            logger.info(f"[LAWYER_AGENT] ЯВНОЕ УКАЗАНИЕ: кодекс='{codex.name}', статья={article_number} - используем прямой поиск в БД")
            try:
                article = codex_service.find_article(codex, article_number)
                if article:
                    logger.info(f"[LAWYER_AGENT] ✓ Найдена статья {article_number} в кодексе '{codex.name}' через прямой поиск в БД")
                    articles = [article]
                    article_found_by_number = True
                else:
                    logger.warning(f"[LAWYER_AGENT] ✗ Статья {article_number} не найдена в кодексе '{codex.name}' в БД")
                    # ВАЖНО: Если номер статьи явно указан, но статья не найдена,
                    # НЕ продолжаем поиск по ключевым словам - это может привести к неправильным результатам
                    # Возвращаем пустой результат с предупреждением
                    return {
                        **state,
                        "query": query,
                        "mapped_codexes": mapped_codexes,
                        "context_terms": final_keywords,
                        "found_articles": [],
                        "context_snippet": f"Статья {article_number} не найдена в кодексе '{codex.name}'. Проверьте правильность номера статьи."
                    }
            except Exception as e:
                logger.error(f"[LAWYER_AGENT] Ошибка прямого поиска статьи в БД: {e}")
                import traceback
                logger.error(f"[LAWYER_AGENT] Детали ошибки:\n{traceback.format_exc()}")
                # При ошибке тоже не продолжаем поиск по ключевым словам
                return {
                    **state,
                    "query": query,
                    "mapped_codexes": mapped_codexes,
                    "context_terms": final_keywords,
                    "found_articles": [],
                    "context_snippet": f"Ошибка при поиске статьи {article_number}: {str(e)}"
                }
        
        # Шаг 6: Поиск статей по ключевым словам (только если номер статьи НЕ был указан)
        # ВАЖНО: Если кодекс определен, но номер статьи НЕ указан, ищем по ключевым словам
        # Это соответствует логике из lawyer_helpers_base (строки 6820-6843)
        if not articles and not article_number:
            # Если кодекс определен, но нет номера статьи, ищем по ключевым словам
            if codex and not article_number:
                logger.info(f"[LAWYER_AGENT] Кодекс определен, но номер статьи не указан. Поиск по ключевым словам: {final_keywords[:5]}...")
            else:
                logger.info(f"[LAWYER_AGENT] Поиск статей по ключевым словам: {final_keywords[:5]}...")
            
            articles = codex_service.search_articles_by_keywords(codex, final_keywords, limit=10)
            logger.info(f"[LAWYER_AGENT] Найдено статей: {len(articles)}")
            
            if not articles:
                logger.warning(f"[LAWYER_AGENT] Статьи не найдены. Пробуем поиск по упрощенным ключевым словам...")
                # Пробуем поиск только по высокоприоритетным словам
                if high_priority:
                    articles = codex_service.search_articles_by_keywords(codex, high_priority, limit=10)
                    logger.info(f"[LAWYER_AGENT] Найдено статей по высокоприоритетным словам: {len(articles)}")
                
                # Если все еще не найдено, пробуем поиск по medium_priority
                if not articles and medium_priority:
                    articles = codex_service.search_articles_by_keywords(codex, medium_priority, limit=10)
                    logger.info(f"[LAWYER_AGENT] Найдено статей по среднеприоритетным словам: {len(articles)}")
        
        # Преобразуем статьи в словари
        found_articles = []
        for article in articles:
            found_articles.append({
                "number": article.number,
                "title": article.title,
                "content": article.content[:2000],  # Ограничиваем длину
                "codex_name": codex.name
            })
        
        # Если найдена статья по номеру, формируем контекст сразу и возвращаем результат
        # (как в lawyer_helpers_base - приоритет прямого поиска)
        if article_number and articles:
            logger.info(f"[LAWYER_AGENT] Статья найдена по номеру, формируем контекст из найденной статьи")
            snippet_parts = []
            for article in articles:
                article_text = f"Статья {article.number}. {article.title}\n\n{article.content}" if article.title else f"Статья {article.number}\n\n{article.content}"
                snippet_parts.append(article_text)
            
            context_snippet = "\n\n".join(snippet_parts)
            logger.info(f"[LAWYER_AGENT] Контекст извлечен из статьи по номеру, длина: {len(context_snippet)} символов")
            
            return {
                **state,
                "query": query,
                "mapped_codexes": mapped_codexes,
                "context_terms": final_keywords,
                "found_articles": found_articles,
                "context_snippet": context_snippet
            }
        
        # Шаг 7: Дополнительный векторный поиск (если доступен)
        vector_results = []
        try:
            vector_results = vector_search(query, top_k=3)
            if vector_results:
                logger.info(f"[LAWYER_AGENT] Векторный поиск нашел {len(vector_results)} документов")
        except Exception as e:
            logger.warning(f"[LAWYER_AGENT] Ошибка векторного поиска: {e}")
        
        # Шаг 8: Извлечение релевантного фрагмента
        context_snippet = None
        snippet_parts = []
        
        # Добавляем результаты из векторного поиска
        if vector_results:
            snippet_parts.append("=== Результаты векторного поиска ===")
            for result in vector_results[:3]:
                content = result.get("content", "")
                metadata = result.get("metadata", {})
                score = result.get("score", 0.0)
                snippet_parts.append(f"[Релевантность: {score:.3f}]")
                if metadata:
                    snippet_parts.append(f"Метаданные: {metadata}")
                snippet_parts.append(content[:800])  # Первые 800 символов
                snippet_parts.append("---")
        
        # Добавляем результаты поиска по ключевым словам
        if articles:
            if snippet_parts:
                snippet_parts.append("\n=== Результаты поиска по ключевым словам ===")
            for article in articles[:5]:  # Берем первые 5 статей
                snippet_parts.append(f"Статья {article.number}")
                if article.title:
                    snippet_parts.append(f"Название: {article.title}")
                snippet_parts.append(article.content[:1000])  # Первые 1000 символов
                snippet_parts.append("---")
        
        if snippet_parts:
            context_snippet = "\n\n".join(snippet_parts)
            logger.info(f"[LAWYER_AGENT] Контекст извлечен, длина: {len(context_snippet)} символов")
        
        # Убеждаемся, что context_snippet установлен (даже если пустой)
        if context_snippet is None:
            context_snippet = ""
        
        return {
            **state,
            "query": query,
            "mapped_codexes": mapped_codexes,
            "context_terms": final_keywords,
            "found_articles": found_articles if found_articles else [],
            "context_snippet": context_snippet
        }
        
    except Exception as e:
        logger.error(f"[LAWYER_AGENT] Ошибка при поиске актов: {e}", exc_info=True)
        return {
            **state,
            "query": query,
            "mapped_codexes": None,
            "context_terms": [],
            "found_articles": [],
            "context_snippet": None
        }

