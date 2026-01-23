"""
Утилита для нормализации неточных запросов пользователя в точные и понятные для субагентов.

Каждый агент может использовать эту утилиту для преобразования неточных запросов
в структурированные и понятные для себя запросы, сохраняя при этом оригинальный запрос.
"""

import re
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def normalize_tinkoff_request(original_request: str) -> Tuple[str, Dict]:
    """
    Нормализует запрос для tinkoff_agent.
    
    Преобразует неточные запросы в точные:
    - "покажи график SPCE" -> "покажи график SPCE" (без изменений, если уже точный)
    - "график Virgin Galactic" -> "покажи график SPCE" (извлекает тикер)
    - "мой портфель акций" -> "покажи мой портфель акций"
    - "купи 10 штук Сбербанка" -> "купи 10 акций SBER"
    
    Args:
        original_request: Оригинальный запрос пользователя
        
    Returns:
        Tuple[нормализованный_запрос, метаданные]
    """
    request_lower = original_request.lower().strip()
    metadata = {
        "original_request": original_request,
        "normalized": False,
        "extracted_info": {}
    }
    
    # Если запрос уже достаточно точный (короткий и содержит тикер или ключевые слова), возвращаем как есть
    if len(original_request.split()) <= 5 and any(word in request_lower for word in ["график", "портфель", "купи", "продай", "sber", "gazp", "spce"]):
        metadata["normalized"] = False
        return original_request, metadata
    
    normalized = original_request
    
    # Нормализация запросов на графики
    if any(word in request_lower for word in ["график", "chart", "график для", "покажи график"]):
        # Извлекаем тикер из запроса
        ticker = None
        
        # Словарь соответствий названий компаний и тикеров
        company_to_ticker = {
            "сбербанк": "SBER",
            "сбер": "SBER",
            "газпром": "GAZP",
            "газ": "GAZP",
            "virgin galactic": "SPCE",
            "virgin": "SPCE",
            "яндекс": "YNDX",
            "яндекса": "YNDX",
            "лукойл": "LKOH",
            "норникель": "GMKN",
            "норильский никель": "GMKN",
            "росатом": "ROSATOM",
            "ростех": "ROSTEC",
        }
        
        # Ищем тикер в запросе
        # Сначала ищем прямые тикеры (2-5 заглавных букв)
        ticker_match = re.search(r'\b([A-ZА-Я]{2,5})\b', original_request)
        if ticker_match:
            potential_ticker = ticker_match.group(1).upper()
            if potential_ticker.isalpha() and len(potential_ticker) >= 2:
                ticker = potential_ticker
        
        # Если не нашли тикер, ищем по названию компании
        if not ticker:
            for company, ticker_code in company_to_ticker.items():
                if company in request_lower:
                    ticker = ticker_code
                    metadata["extracted_info"]["company_name"] = company
                    break
        
        # Если нашли тикер, нормализуем запрос
        if ticker:
            if "график" not in request_lower:
                normalized = f"покажи график {ticker}"
            else:
                # Заменяем название компании на тикер
                for company, ticker_code in company_to_ticker.items():
                    if company in request_lower:
                        normalized = re.sub(rf'\b{re.escape(company)}\b', ticker_code, normalized, flags=re.IGNORECASE)
                        break
                # Если в запросе нет тикера, добавляем его
                if ticker not in normalized.upper():
                    normalized = f"покажи график {ticker}"
            
            metadata["normalized"] = True
            metadata["extracted_info"]["ticker"] = ticker
    
    # Нормализация запросов на портфель
    elif any(word in request_lower for word in ["портфель", "позиции", "мои акции", "моих акций"]):
        if "покажи" not in request_lower and "показать" not in request_lower:
            normalized = f"покажи {normalized}"
        if "мой" not in request_lower and "мои" not in request_lower:
            normalized = normalized.replace("портфель", "мой портфель")
        metadata["normalized"] = True
    
    # Нормализация запросов на покупку/продажу
    elif any(word in request_lower for word in ["купи", "купить", "продай", "продать"]):
        # Нормализуем количество
        normalized = re.sub(r'(\d+)\s*(штук|шт|акций|акции)', r'\1 акций', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'(\d+)\s*(штук|шт)', r'\1 акций', normalized, flags=re.IGNORECASE)
        
        # Нормализуем названия компаний в тикеры
        company_to_ticker = {
            "сбербанк": "SBER",
            "сбер": "SBER",
            "газпром": "GAZP",
            "газ": "GAZP",
        }
        for company, ticker in company_to_ticker.items():
            if company in request_lower:
                normalized = re.sub(rf'\b{re.escape(company)}\b', ticker, normalized, flags=re.IGNORECASE)
                metadata["extracted_info"]["ticker"] = ticker
                break
        
        metadata["normalized"] = True
    
    metadata["normalized_request"] = normalized
    return normalized, metadata


def normalize_email_request(original_request: str) -> Tuple[str, Dict]:
    """
    Нормализует запрос для email_agent.
    
    Преобразует неточные запросы в точные:
    - "письма" -> "покажи письма"
    - "непрочитанные" -> "покажи непрочитанные письма"
    - "отправь письмо" -> "отправить письмо"
    
    Args:
        original_request: Оригинальный запрос пользователя
        
    Returns:
        Tuple[нормализованный_запрос, метаданные]
    """
    request_lower = original_request.lower().strip()
    metadata = {
        "original_request": original_request,
        "normalized": False,
        "extracted_info": {}
    }
    
    normalized = original_request
    
    # Если запрос уже содержит действие, возвращаем как есть
    if any(word in request_lower for word in ["покажи", "показать", "прочитать", "отправить", "отправь", "найди", "найти"]):
        metadata["normalized"] = False
        return original_request, metadata
    
    # Нормализация запросов на чтение
    if any(word in request_lower for word in ["письма", "письмо", "почта", "email", "mail"]):
        if "непрочитан" in request_lower:
            normalized = "покажи непрочитанные письма"
        elif "последн" in request_lower:
            normalized = "покажи последние письма"
        else:
            normalized = "покажи письма"
        metadata["normalized"] = True
    
    # Нормализация запросов на отправку
    elif any(word in request_lower for word in ["отправ", "написать", "напиши"]):
        if "отправить" not in request_lower and "отправь" not in request_lower:
            normalized = normalized.replace("написать", "отправить").replace("напиши", "отправить")
        metadata["normalized"] = True
    
    metadata["normalized_request"] = normalized
    return normalized, metadata


def normalize_career_request(original_request: str) -> Tuple[str, Dict]:
    """
    Нормализует запрос для career_agent.
    
    Преобразует неточные запросы в точные:
    - "вакансии" -> "найди вакансии"
    - "резюме" -> "проанализируй мое резюме"
    - "hh" -> "авторизуй на hh.ru"
    
    Args:
        original_request: Оригинальный запрос пользователя
        
    Returns:
        Tuple[нормализованный_запрос, метаданные]
    """
    request_lower = original_request.lower().strip()
    metadata = {
        "original_request": original_request,
        "normalized": False,
        "extracted_info": {}
    }
    
    normalized = original_request
    
    # Если запрос уже содержит действие, возвращаем как есть
    if any(word in request_lower for word in ["найди", "найти", "проанализируй", "авторизуй", "войди"]):
        metadata["normalized"] = False
        return original_request, metadata
    
    # Нормализация запросов на поиск вакансий
    if any(word in request_lower for word in ["вакансии", "вакансия", "работа", "работу"]):
        if "найди" not in request_lower and "найти" not in request_lower:
            normalized = f"найди {normalized}"
        metadata["normalized"] = True
    
    # Нормализация запросов на анализ резюме
    elif any(word in request_lower for word in ["резюме", "cv"]):
        if "проанализируй" not in request_lower and "анализ" not in request_lower:
            normalized = f"проанализируй мое резюме"
        metadata["normalized"] = True
    
    # Нормализация запросов на авторизацию
    elif any(word in request_lower for word in ["hh", "hh.ru", "работа.ру", "работа ру"]):
        if "авторизуй" not in request_lower and "войди" not in request_lower:
            if "hh" in request_lower:
                normalized = "авторизуй на hh.ru"
            elif "работа" in request_lower:
                normalized = "авторизуй на Работа.ру"
        metadata["normalized"] = True
    
    metadata["normalized_request"] = normalized
    return normalized, metadata


def normalize_calendar_request(original_request: str) -> Tuple[str, Dict]:
    """
    Нормализует запрос для calendar_agent.
    
    Преобразует неточные запросы в точные:
    - "события" -> "покажи события"
    - "встреча завтра" -> "создать событие 'Встреча' на [завтра]"
    
    Args:
        original_request: Оригинальный запрос пользователя
        
    Returns:
        Tuple[нормализованный_запрос, метаданные]
    """
    request_lower = original_request.lower().strip()
    metadata = {
        "original_request": original_request,
        "normalized": False,
        "extracted_info": {}
    }
    
    normalized = original_request
    
    # Если запрос уже содержит действие, возвращаем как есть
    if any(word in request_lower for word in ["покажи", "показать", "создать", "добавить", "добавь"]):
        metadata["normalized"] = False
        return original_request, metadata
    
    # Нормализация запросов на просмотр
    if any(word in request_lower for word in ["события", "событие", "встречи", "встреча", "расписание"]):
        if "покажи" not in request_lower and "показать" not in request_lower:
            normalized = f"покажи {normalized}"
        metadata["normalized"] = True
    
    # Нормализация запросов на создание (базовая)
    elif any(word in request_lower for word in ["создать", "добавить", "добавь", "запланировать"]):
        if "событие" not in request_lower and "встреч" not in request_lower:
            normalized = f"создать событие '{normalized}'"
        metadata["normalized"] = True
    
    metadata["normalized_request"] = normalized
    return normalized, metadata


def normalize_lawyer_request(original_request: str) -> Tuple[str, Dict]:
    """
    Нормализует запрос для lawyer_agent.
    
    Преобразует неточные запросы в точные:
    - "статья 158" -> "найди статью 158 УК РФ"
    - "права работника" -> "найди информацию о правах работника"
    
    Args:
        original_request: Оригинальный запрос пользователя
        
    Returns:
        Tuple[нормализованный_запрос, метаданные]
    """
    request_lower = original_request.lower().strip()
    metadata = {
        "original_request": original_request,
        "normalized": False,
        "extracted_info": {}
    }
    
    normalized = original_request
    
    # Если запрос уже содержит действие, возвращаем как есть
    if any(word in request_lower for word in ["найди", "найти", "покажи", "расскажи", "объясни"]):
        metadata["normalized"] = False
        return original_request, metadata
    
    # Нормализация запросов на поиск статей
    article_match = re.search(r'статья\s+(\d+)', request_lower)
    if article_match:
        article_num = article_match.group(1)
        # Определяем кодекс по контексту
        codex = "УК РФ"  # По умолчанию
        if any(word in request_lower for word in ["трудов", "работ"]):
            codex = "ТК РФ"
        elif any(word in request_lower for word in ["гражданск", "договор"]):
            codex = "ГК РФ"
        elif any(word in request_lower for word in ["налог", "налогообложен"]):
            codex = "НК РФ"
        
        normalized = f"найди статью {article_num} {codex}"
        metadata["extracted_info"]["article"] = article_num
        metadata["extracted_info"]["codex"] = codex
        metadata["normalized"] = True
    
    # Нормализация общих юридических запросов
    elif any(word in request_lower for word in ["права", "обязанности", "закон", "кодекс"]):
        if "найди" not in request_lower and "найти" not in request_lower:
            normalized = f"найди информацию о {normalized}"
        metadata["normalized"] = True
    
    metadata["normalized_request"] = normalized
    return normalized, metadata


def normalize_request(agent_type: str, original_request: str) -> Tuple[str, Dict]:
    """
    Универсальная функция нормализации запросов для всех агентов.
    
    Args:
        agent_type: Тип агента (tinkoff, email, career, calendar, lawyer)
        original_request: Оригинальный запрос пользователя
        
    Returns:
        Tuple[нормализованный_запрос, метаданные]
    """
    normalizers = {
        "tinkoff": normalize_tinkoff_request,
        "email": normalize_email_request,
        "career": normalize_career_request,
        "calendar": normalize_calendar_request,
        "lawyer": normalize_lawyer_request,
    }
    
    normalizer = normalizers.get(agent_type.lower())
    if normalizer:
        try:
            normalized, metadata = normalizer(original_request)
            logger.info(f"[REQUEST_NORMALIZER] {agent_type}: '{original_request}' -> '{normalized}' (normalized={metadata.get('normalized', False)})")
            return normalized, metadata
        except Exception as e:
            logger.warning(f"[REQUEST_NORMALIZER] Ошибка нормализации для {agent_type}: {e}")
            return original_request, {"original_request": original_request, "normalized": False, "error": str(e)}
    else:
        logger.warning(f"[REQUEST_NORMALIZER] Неизвестный тип агента: {agent_type}")
        return original_request, {"original_request": original_request, "normalized": False, "error": f"Unknown agent type: {agent_type}"}
