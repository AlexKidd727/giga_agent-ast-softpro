"""
Узел для генерации ответа на основе найденного контекста
"""

import logging
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage

from giga_agent.agents.lawyer_agent.config import LawyerAgentState
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


def generate_answer_node(state: LawyerAgentState) -> Dict[str, Any]:
    """
    Узел для генерации ответа на основе найденного контекста
    
    Использует LLM для формирования ответа на основе:
    - Исходного запроса пользователя
    - Найденных статей кодексов
    - Извлеченного контекста
    """
    query = state.get("query", "")
    context_snippet = state.get("context_snippet", "")
    found_articles = state.get("found_articles", [])
    mapped_codexes = state.get("mapped_codexes", [])
    
    logger.info(f"[LAWYER_AGENT] Генерация ответа для запроса: {query[:100]}")
    
    try:
        # Формируем промпт для LLM
        if context_snippet:
            # Формируем список найденных статей
            articles_info = ""
            if found_articles:
                articles_info = "\n\nНайденные статьи:\n"
                for article in found_articles[:10]:  # Берем первые 10 статей
                    codex_name = article.get('codex_name', 'Неизвестный кодекс')
                    article_num = article.get('number', '')
                    article_title = article.get('title', 'без названия')
                    articles_info += f"- {codex_name}, Статья {article_num}: {article_title}\n"
            
            system_prompt = """Ты - квалифицированный юридический помощник. Твоя задача - давать точные и структурированные ответы на юридические вопросы на основе предоставленного контекста из правовых актов.

Инструкции:
1. Давай точный и структурированный ответ на основе предоставленного контекста
2. Ссылайся на конкретные статьи кодексов с указанием их номеров
3. Если информации недостаточно, честно укажи это
4. Используй юридическую терминологию корректно
5. Отвечай на русском языке
6. Структурируй ответ для лучшей читаемости (используй списки, абзацы)
7. Если в контексте есть конкретные процедуры или сроки, обязательно укажи их"""
            
            user_prompt = f"""Вопрос пользователя: {query}

Контекст из правовых актов:
{context_snippet}
{articles_info}

Ответь на вопрос пользователя на основе предоставленного контекста."""
            
            # Вызываем LLM
            llm = get_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = llm.invoke(messages)
            answer = response.content if hasattr(response, 'content') else str(response)
            
        else:
            answer = f"""К сожалению, не удалось найти релевантную информацию в правовых актах по запросу "{query}".

Попробуйте уточнить запрос или указать конкретный кодекс (например, УК РФ, ГПК РФ, АПК РФ и т.д.)."""
        
        logger.info(f"[LAWYER_AGENT] Ответ сгенерирован, длина: {len(answer)} символов")
        
        return {
            **state,
            "answer": answer
        }
        
    except Exception as e:
        logger.error(f"[LAWYER_AGENT] Ошибка при генерации ответа: {e}", exc_info=True)
        # Возвращаем базовый ответ с контекстом, если LLM недоступен
        if context_snippet:
            answer = f"""На основе анализа правовых актов по вашему запросу "{query}":

{context_snippet[:1000]}

Примечание: При генерации ответа произошла ошибка. Выше представлен найденный контекст из правовых актов."""
        else:
            answer = f"""К сожалению, не удалось найти релевантную информацию в правовых актах по запросу "{query}".

Попробуйте уточнить запрос или указать конкретный кодекс."""
        
        return {
            **state,
            "answer": answer
        }

