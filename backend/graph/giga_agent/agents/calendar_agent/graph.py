"""
Граф Google Calendar Agent (Service Account)
"""

import logging
from typing import Annotated, TypedDict
from datetime import datetime, timedelta

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import InjectedState
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message

from giga_agent.agents.calendar_agent.nodes.simple_events import (
    simple_create_event, simple_list_events, simple_get_available_slots, 
    simple_delete_event, simple_calendar_status, simple_find_event_by_title,
    simple_update_event
)

from giga_agent.agents.calendar_agent.nodes.improved_events import (
    improved_list_events, search_events_by_keywords, delete_events_by_keywords
)
from giga_agent.agents.calendar_agent.nodes.events import bulk_create_events
from giga_agent.utils.request_normalizer import normalize_request

logger = logging.getLogger(__name__)

# Инструменты календаря (Service Account)
CALENDAR_TOOLS = [
    simple_create_event,
    simple_list_events,
    simple_get_available_slots,
    simple_delete_event,
    simple_calendar_status,
    # Улучшенные инструменты
    improved_list_events,
    search_events_by_keywords,
    delete_events_by_keywords,
]

@tool
async def calendar_agent(
    user_request: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Агент для работы с Google Calendar через Service Account
    
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Параметр называется user_request (НЕ query, НЕ task_type, НЕ action)!
    Всегда передавай запрос пользователя в параметр user_request.
    
    ПРАВИЛЬНЫЙ ФОРМАТ ВЫЗОВА:
    calendar_agent(user_request="показать события")
    calendar_agent(user_request="создать событие 'Встреча' на 1 января 2026 в 12:00")
    calendar_agent(user_request="добавь события 'Выходные' с 1 по 7 января 2026")
    
    НЕПРАВИЛЬНО (НЕ ДЕЛАЙ ТАК):
    ❌ calendar_agent(query="показать события") - параметр query не существует!
    ❌ calendar_agent(action="get_events") - параметр action не существует!
    
    Обрабатывает запросы пользователя связанные с календарем:
    
    ПРОСМОТР СОБЫТИЙ:
    - Просмотр событий и расписания (показать события, мои встречи, расписание)
    - Поиск событий по ключевым словам
    - Получение свободных слотов
    
    СОЗДАНИЕ СОБЫТИЙ:
    - Одиночное событие: "создать событие 'Название' на 1 января 2026 в 12:00"
    - Событие на весь день: "добавить событие 'Выходной' на 1 января 2026 весь день"
    - Событие с периодом времени: "создать событие 'Встреча' на 1 января 2026 с 10:00 до 12:00"
    
    МАССОВОЕ СОЗДАНИЕ СОБЫТИЙ (АВТОМАТИЧЕСКОЕ - ВАЖНО!):
    Агент автоматически распознает периоды и создает события на каждый день:
    - "добавь события 'Новогодние выходные' с 1 по 7 января 2026 года" - создаст 7 событий на каждый день
    - "создать события 'Отпуск' с 01.01.2026 по 07.01.2026" - создаст события на каждый день
    - "добавить события 'Выходные' с 1 по 7 января 2026 весь день" - создаст события на весь день
    - Форматы дат: "1 января 2026", "01.01.2026", "с 1 по 7 января 2026 года"
    
    МАССОВОЕ СОЗДАНИЕ ИЗ ТАБЛИЦЫ:
    Для массового создания событий из таблицы передайте список событий в формате JSON в поле `events_to_create` в `state`.
    Пример запроса: "массовое создание событий из таблицы"
    Пример данных в `state['events_to_create']`:
    [
        {"title": "Встреча 1", "start_datetime": "2024-01-15T10:00:00", "end_datetime": "2024-01-15T11:00:00", "description": "Обсуждение проекта"},
        {"title": "Обед", "start_datetime": "2024-01-15T13:00:00", "end_datetime": "2024-01-15T14:00:00", "all_day": False}
    ]
    
    УПРАВЛЕНИЕ СОБЫТИЯМИ:
    - Обновление событий
    - Удаление событий
    - Проверка статуса календаря
    
    ВАЖНО: 
    - При указании периода (например, "с 1 по 7 января") агент автоматически создает события на каждый день
    - Если время не указано, событие создается на весь день (00:00 - 23:59)
    - Если указано только время начала, окончание устанавливается через час или до конца дня
    - Для массового создания из таблицы передавайте список событий с полями: title, start_datetime, end_datetime, description (опционально), all_day (опционально)
    
    Args:
        user_request: Запрос пользователя (например, "показать события", "создать событие", "массовое добавление событий")
        user_id: Идентификатор пользователя (необязательно)
    """
    
    try:
        # Нормализуем запрос: преобразуем неточные запросы в точные и понятные
        normalized_request, normalization_metadata = normalize_request("calendar", user_request)
        if normalization_metadata.get("normalized", False):
            logger.info(f"[CALENDAR_AGENT] Запрос нормализован: '{user_request}' -> '{normalized_request}'")
            user_request = normalized_request
        
        user_input = user_request.lower()
        print(f"🔍 CALENDAR AGENT: Received request: '{user_request}' -> '{user_input}'")
        
        # Команды работы с событиями
        if any(phrase in user_input for phrase in ["показать события", "мои встречи", "расписание", "календарь на", "что запланировано", "события на", "месяц вперед", "на месяц", "список событий", "события вперед", "30 дней"]):
            print("🔍 CALENDAR AGENT: Matched events listing pattern")
            # Определяем количество дней для показа
            days_ahead = 30  # по умолчанию месяц
            if "неделя" in user_input or "неделю" in user_input:
                days_ahead = 7
            elif "день" in user_input or "дня" in user_input:
                days_ahead = 1
            elif "месяц" in user_input or "месяца" in user_input:
                days_ahead = 30
            
            result = await simple_list_events.ainvoke({"days_ahead": days_ahead})
            return result
        
        # Массовое создание событий (проверяем сначала массовые операции)
        elif any(phrase in user_input for phrase in [
            "массовое создание", "массовое добавление", "создать события из таблицы", 
            "добавить несколько событий", "создать несколько событий", "массовое добавление событий",
            "создать события по таблице", "добавить события из таблицы"
        ]):
            # Пытаемся извлечь список событий из запроса или state
            events_list = None
            
            # Проверяем, есть ли список событий в state или в запросе
            if state and isinstance(state, dict):
                events_list = state.get("events_list") or state.get("events")
            
            # Если список не найден, пытаемся извлечь из текста запроса
            if not events_list:
                # Можно попробовать парсить JSON или таблицу из запроса
                import json
                try:
                    # Ищем JSON в запросе
                    json_match = re.search(r'\[.*?\]', user_request, re.DOTALL)
                    if json_match:
                        events_list = json.loads(json_match.group(0))
                except:
                    pass
            
            if events_list and isinstance(events_list, list) and len(events_list) > 0:
                logger.info(f"[CALENDAR_AGENT] массовое создание событий: найдено {len(events_list)} событий")
                # Получаем user_id из state если не передан
                if not user_id or user_id == "default_user":
                    user_id = state.get("user_id", "default_user") if state and isinstance(state, dict) else "default_user"
                
                result = await bulk_create_events.ainvoke({
                    "user_id": user_id,
                    "events": events_list,
                    "state": state
                })
                return result
            else:
                return "❌ Для массового создания событий необходимо передать список/таблицу событий. Каждое событие должно содержать поля: title, start_datetime, end_datetime (и опционально description, all_day)."
            
        elif any(phrase in user_input for phrase in ["создать событие", "создать встречу", "добавить в календарь", "запланировать", "создай событие", "добавь событие", "добавь встречу", "создай встречу", "добавь новое событие", "добавь новое события", "добавь события", "создать события"]):
            # Пытаемся извлечь информацию о событии из запроса
            from datetime import datetime, timedelta, date
            import re
            
            # Сначала проверяем, есть ли период (например, "с 1 по 7 января")
            # Словарь месяцев
            months = {
                'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
                'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
                'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
            }
            
            # Ищем период: "с 1 по 7 января 2026 года" или "с 1 по 7 января"
            period_pattern = r'с\s+(\d{1,2})\s+по\s+(\d{1,2})\s+(' + '|'.join(months.keys()) + r')(?:\s+(\d{4}))?(?:\s+года)?'
            period_match = re.search(period_pattern, user_input, re.IGNORECASE)
            
            if period_match:
                # Найден период - создаем события на каждый день
                start_day = int(period_match.group(1))
                end_day = int(period_match.group(2))
                month_name = period_match.group(3)
                year_str = period_match.group(4)
                
                # Определяем год
                if year_str:
                    year = int(year_str)
                else:
                    # Если год не указан, используем текущий или следующий
                    current_year = datetime.now().year
                    current_month = datetime.now().month
                    month_num = months[month_name]
                    if month_num < current_month or (month_num == current_month and start_day < datetime.now().day):
                        year = current_year + 1
                    else:
                        year = current_year
                
                month = months[month_name]
                
                # Извлекаем название события
                title = "Событие"
                if '"' in user_request:
                    title_match = re.search(r'"([^"]*)"', user_request)
                    if title_match:
                        title = title_match.group(1)
                else:
                    # Ищем название перед или после периода
                    title_pattern = r'([^"]+?)(?:\s+с\s+\d|\s+на\s+\d|$)'
                    title_match = re.search(title_pattern, user_input)
                    if title_match:
                        potential_title = title_match.group(1).strip()
                        # Очищаем от служебных слов
                        potential_title = re.sub(r'\b(создать|создай|добавить|добавь|событие|события|встречу|встречи|в\s+календарь|на)\b', '', potential_title, flags=re.IGNORECASE).strip()
                        if potential_title and len(potential_title) > 1:
                            title = potential_title
                
                # Проверяем, указано ли "весь день" или время
                all_day = "весь день" in user_input or "целый день" in user_input or "на весь день" in user_input
                start_time = "00:00"
                end_time = "23:59"
                
                # Ищем время начала и окончания
                time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                if time_match and not all_day:
                    start_time = f"{int(time_match.group(1)):02d}:{int(time_match.group(2)):02d}"
                    # Ищем время окончания
                    time_matches = re.findall(r'(\d{1,2}):(\d{2})', user_input)
                    if len(time_matches) > 1:
                        end_time = f"{int(time_matches[1][0]):02d}:{int(time_matches[1][1]):02d}"
                    else:
                        # По умолчанию - до конца дня
                        end_time = "23:59"
                
                # Создаем список событий на каждый день
                events_list = []
                for day in range(start_day, end_day + 1):
                    try:
                        event_date = date(year, month, day)
                        start_datetime = f"{day:02d}.{month:02d}.{year} {start_time}"
                        end_datetime = f"{day:02d}.{month:02d}.{year} {end_time}"
                        
                        events_list.append({
                            'title': title,
                            'start_datetime': start_datetime,
                            'end_datetime': end_datetime,
                            'all_day': all_day,
                            'description': f"Событие создано через GigaChat Agent"
                        })
                    except ValueError:
                        # Пропускаем невалидные даты (например, 32 января)
                        logger.warning(f"[CALENDAR_AGENT] пропущена невалидная дата: {day}.{month}.{year}")
                        continue
                
                if events_list:
                    logger.info(f"[CALENDAR_AGENT] найдено {len(events_list)} дней для создания событий '{title}'")
                    # Получаем user_id из state если не передан
                    if not user_id or user_id == "default_user":
                        user_id = state.get("user_id", "default_user") if state and isinstance(state, dict) else "default_user"
                    
                    result = await bulk_create_events.ainvoke({
                        "user_id": user_id,
                        "events": events_list,
                        "state": state
                    })
                    return result
                else:
                    return "❌ Не удалось создать события: невалидные даты в периоде."
            
            # Извлекаем название события (для одиночного события)
            title = "Событие"
            
            # Ищем текст в кавычках (приоритетный способ)
            if '"' in user_request:
                title_match = re.search(r'"([^"]*)"', user_request)
                if title_match:
                    title = title_match.group(1)
            # Ищем после слова "названием"
            elif "названием" in user_input:
                title_match = re.search(r'названием\s+"([^"]*)"', user_input)
                if title_match:
                    title = title_match.group(1)
            # Ищем после слова "событие" или "встречу" до времени или даты
            else:
                # Паттерн для поиска названия события после "событие" или "встречу"
                title_patterns = [
                    r'(?:событие|встречу|добавь|создай)\s+([^0-9]+?)(?:\s+на\s+|\s+в\s+\d|$)',
                    r'(?:добавь|создай)\s+([^0-9]+?)(?:\s+на\s+|\s+в\s+\d|$)',
                    r'([^0-9]+?)(?:\s+на\s+завтра|\s+на\s+сегодня|\s+в\s+\d)',
                    # Специальный паттерн для "добавь новое события на завтра на 12:00 'название'"
                    r'добавь\s+новое\s+события?\s+на\s+[^0-9]*?\s+на\s+\d{1,2}:\d{2}\s+["\']([^"\']+)["\']',
                    # Паттерн для "добавь событие 'название' на завтра в 12:00"
                    r'добавь\s+событие\s+["\']([^"\']+)["\']\s+на\s+завтра'
                ]
                
                for pattern in title_patterns:
                    title_match = re.search(pattern, user_input, re.IGNORECASE)
                    if title_match:
                        potential_title = title_match.group(1).strip()
                        # Очищаем от лишних слов
                        potential_title = re.sub(r'\b(событие|встречу|добавь|создай|на|в|новое|новые)\b', '', potential_title, flags=re.IGNORECASE).strip()
                        if potential_title and len(potential_title) > 1:
                            title = potential_title
                            break
            
            # Определяем дату и время
            start_datetime = None
            end_datetime = None
            
            # Проверяем "сегодня"
            if "сегодня" in user_input:
                today = datetime.now()
                date_str = today.strftime("%d.%m.%Y")
                
                # Ищем время
                time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2))
                    start_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                    
                    # Конец события через час
                    end_hour = hour + 1
                    if end_hour >= 24:
                        end_hour = 0
                        end_date = today + timedelta(days=1)
                        end_date_str = end_date.strftime("%d.%m.%Y")
                    else:
                        end_date_str = date_str
                    end_datetime = f"{end_date_str} {end_hour:02d}:{minute:02d}"
            
            # Проверяем "завтра"
            elif "завтра" in user_input:
                tomorrow = datetime.now() + timedelta(days=1)
                date_str = tomorrow.strftime("%d.%m.%Y")
                
                # Ищем время
                time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2))
                    start_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                    
                    # Конец события через час
                    end_hour = hour + 1
                    if end_hour >= 24:
                        end_hour = 0
                        end_date = tomorrow + timedelta(days=1)
                        end_date_str = end_date.strftime("%d.%m.%Y")
                    else:
                        end_date_str = date_str
                    end_datetime = f"{end_date_str} {end_hour:02d}:{minute:02d}"
            
            # Проверяем конкретную дату в формате "20 сентября 2025 года" или "1 января 2026"
            if not start_datetime:
                # Словарь месяцев (уже определен выше, но на всякий случай)
                if 'months' not in locals():
                    months = {
                        'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
                        'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
                        'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
                    }
                
                # Ищем паттерн "20 сентября 2025 года" или "1 января 2026"
                date_pattern = r'(\d{1,2})\s+(' + '|'.join(months.keys()) + r')(?:\s+(\d{4}))?(?:\s+года)?'
                date_match = re.search(date_pattern, user_input)
                
                if date_match:
                    day = int(date_match.group(1))
                    month_name = date_match.group(2)
                    year_str = date_match.group(3)
                    
                    # Определяем год
                    if year_str:
                        year = int(year_str)
                    else:
                        # Если год не указан, используем текущий или следующий
                        current_year = datetime.now().year
                        current_month = datetime.now().month
                        month_num = months[month_name]
                        if month_num < current_month or (month_num == current_month and day < datetime.now().day):
                            year = current_year + 1
                        else:
                            year = current_year
                    
                    month = months[month_name]
                    date_str = f"{day:02d}.{month:02d}.{year}"
                    
                    # Проверяем, указано ли "весь день"
                    all_day_event = "весь день" in user_input or "целый день" in user_input or "на весь день" in user_input
                    
                    # Ищем время начала и окончания
                    time_matches = list(re.finditer(r'(\d{1,2}):(\d{2})', user_input))
                    
                    if all_day_event:
                        # Событие на весь день
                        start_datetime = f"{date_str} 00:00"
                        end_datetime = f"{date_str} 23:59"
                    elif time_matches:
                        # Есть указание времени
                        first_time = time_matches[0]
                        hour = int(first_time.group(1))
                        minute = int(first_time.group(2))
                        start_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                        
                        # Ищем время окончания
                        if len(time_matches) > 1:
                            # Есть второе время - используем его как время окончания
                            second_time = time_matches[1]
                            end_hour = int(second_time.group(1))
                            end_minute = int(second_time.group(2))
                            end_datetime = f"{date_str} {end_hour:02d}:{end_minute:02d}"
                        elif "до" in user_input or "по" in user_input:
                            # Ищем время после "до" или "по"
                            end_time_match = re.search(r'(?:до|по)\s+(\d{1,2}):(\d{2})', user_input)
                            if end_time_match:
                                end_hour = int(end_time_match.group(1))
                                end_minute = int(end_time_match.group(2))
                                end_datetime = f"{date_str} {end_hour:02d}:{end_minute:02d}"
                            else:
                                # По умолчанию - до конца дня
                                end_datetime = f"{date_str} 23:59"
                        else:
                            # Конец события через час (по умолчанию)
                            end_hour = hour + 1
                            if end_hour >= 24:
                                end_hour = 0
                                event_date = date(year, month, day)
                                end_date = event_date + timedelta(days=1)
                                end_date_str = end_date.strftime("%d.%m.%Y")
                            else:
                                end_date_str = date_str
                            end_datetime = f"{end_date_str} {end_hour:02d}:{minute:02d}"
                    else:
                        # Время не указано - создаем на весь день
                        start_datetime = f"{date_str} 00:00"
                        end_datetime = f"{date_str} 23:59"
            
            # Проверяем конкретную дату в формате "дд.мм.гггг"
            if not start_datetime:
                # Ищем период в формате "01.01.2026 - 07.01.2026" или "с 01.01.2026 по 07.01.2026"
                period_ddmm_pattern = r'(?:с\s+)?(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(?:по|до|-)\s+(\d{1,2})\.(\d{1,2})\.(\d{4})'
                period_ddmm_match = re.search(period_ddmm_pattern, user_input)
                
                if period_ddmm_match:
                    # Найден период в формате дд.мм.гггг
                    start_day = int(period_ddmm_match.group(1))
                    start_month = int(period_ddmm_match.group(2))
                    start_year = int(period_ddmm_match.group(3))
                    end_day = int(period_ddmm_match.group(4))
                    end_month = int(period_ddmm_match.group(5))
                    end_year = int(period_ddmm_match.group(6))
                    
                    # Извлекаем название события
                    if '"' in user_request:
                        title_match = re.search(r'"([^"]*)"', user_request)
                        if title_match:
                            title = title_match.group(1)
                    
                    # Проверяем, указано ли "весь день"
                    all_day = "весь день" in user_input or "целый день" in user_input or "на весь день" in user_input
                    start_time = "00:00"
                    end_time = "23:59"
                    
                    # Ищем время
                    time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                    if time_match and not all_day:
                        start_time = f"{int(time_match.group(1)):02d}:{int(time_match.group(2)):02d}"
                        time_matches = re.findall(r'(\d{1,2}):(\d{2})', user_input)
                        if len(time_matches) > 1:
                            end_time = f"{int(time_matches[1][0]):02d}:{int(time_matches[1][1]):02d}"
                    
                    # Создаем список событий на каждый день
                    events_list = []
                    start_date_obj = date(start_year, start_month, start_day)
                    end_date_obj = date(end_year, end_month, end_day)
                    current_date = start_date_obj
                    
                    while current_date <= end_date_obj:
                        date_str = current_date.strftime("%d.%m.%Y")
                        start_datetime = f"{date_str} {start_time}"
                        end_datetime = f"{date_str} {end_time}"
                        
                        events_list.append({
                            'title': title,
                            'start_datetime': start_datetime,
                            'end_datetime': end_datetime,
                            'all_day': all_day,
                            'description': f"Событие создано через GigaChat Agent"
                        })
                        
                        current_date += timedelta(days=1)
                    
                    if events_list:
                        logger.info(f"[CALENDAR_AGENT] найдено {len(events_list)} дней для создания событий '{title}' (формат дд.мм.гггг)")
                        # Получаем user_id из state если не передан
                        if not user_id or user_id == "default_user":
                            user_id = state.get("user_id", "default_user") if state and isinstance(state, dict) else "default_user"
                        
                        result = await bulk_create_events.ainvoke({
                            "user_id": user_id,
                            "events": events_list,
                            "state": state
                        })
                        return result
                
                # Одиночная дата в формате "дд.мм.гггг"
                date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', user_input)
                if date_match:
                    day = int(date_match.group(1))
                    month = int(date_match.group(2))
                    year = int(date_match.group(3))
                    date_str = f"{day:02d}.{month:02d}.{year}"
                    
                    # Проверяем, указано ли "весь день"
                    all_day_event = "весь день" in user_input or "целый день" in user_input or "на весь день" in user_input
                    
                    # Ищем время начала и окончания
                    time_matches = list(re.finditer(r'(\d{1,2}):(\d{2})', user_input))
                    
                    if all_day_event:
                        # Событие на весь день
                        start_datetime = f"{date_str} 00:00"
                        end_datetime = f"{date_str} 23:59"
                    elif time_matches:
                        # Есть указание времени
                        first_time = time_matches[0]
                        hour = int(first_time.group(1))
                        minute = int(first_time.group(2))
                        start_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                        
                        # Ищем время окончания
                        if len(time_matches) > 1:
                            # Есть второе время - используем его как время окончания
                            second_time = time_matches[1]
                            end_hour = int(second_time.group(1))
                            end_minute = int(second_time.group(2))
                            end_datetime = f"{date_str} {end_hour:02d}:{end_minute:02d}"
                        elif "до" in user_input or "по" in user_input:
                            # Ищем время после "до" или "по"
                            end_time_match = re.search(r'(?:до|по)\s+(\d{1,2}):(\d{2})', user_input)
                            if end_time_match:
                                end_hour = int(end_time_match.group(1))
                                end_minute = int(end_time_match.group(2))
                                end_datetime = f"{date_str} {end_hour:02d}:{end_minute:02d}"
                            else:
                                # По умолчанию - до конца дня
                                end_datetime = f"{date_str} 23:59"
                        else:
                            # Конец события через час (по умолчанию)
                            end_hour = hour + 1
                            if end_hour >= 24:
                                end_hour = 0
                                event_date = date(year, month, day)
                                end_date = event_date + timedelta(days=1)
                                end_date_str = end_date.strftime("%d.%m.%Y")
                            else:
                                end_date_str = date_str
                            end_datetime = f"{end_date_str} {end_hour:02d}:{minute:02d}"
                    else:
                        # Время не указано - создаем на весь день
                        start_datetime = f"{date_str} 00:00"
                        end_datetime = f"{date_str} 23:59"
            
            # Если удалось извлечь все параметры, создаем событие
            if start_datetime and end_datetime:
                try:
                    result = await simple_create_event.ainvoke({
                        "title": title,
                        "start_datetime": start_datetime,
                        "end_datetime": end_datetime,
                        "description": f"Событие создано через GigaChat Agent",
                        "user_name": "",
                        "user_username": ""
                    })
                    return result
                except Exception as e:
                    logger.error(f"Ошибка создания события: {e}")
                    return f"❌ Ошибка создания события: {str(e)}"
            else:
                # Если не удалось извлечь время, попробуем создать событие с дефолтными параметрами
                if "завтра" in user_input or "сегодня" in user_input:
                    # Пытаемся извлечь только время без даты
                    time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2))
                        
                        if "завтра" in user_input:
                            tomorrow = datetime.now() + timedelta(days=1)
                            date_str = tomorrow.strftime("%d.%m.%Y")
                        else:  # сегодня
                            today = datetime.now()
                            date_str = today.strftime("%d.%m.%Y")
                        
                        start_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                        end_datetime = f"{date_str} {hour+1:02d}:{minute:02d}"
                        
                        try:
                            result = await simple_create_event.ainvoke({
                                "title": title,
                                "start_datetime": start_datetime,
                                "end_datetime": end_datetime,
                                "description": f"Событие создано через GigaChat Agent",
                                "user_name": "",
                                "user_username": ""
                            })
                            return result
                        except Exception as e:
                            logger.error(f"Ошибка создания события: {e}")
                            return f"❌ Ошибка создания события: {str(e)}"
                
                # Если не удалось извлечь дату, но есть название и время - пробуем создать на сегодня/завтра
                if title and title != "Событие":
                    # Пытаемся найти хотя бы время
                    time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2))
                        
                        # Определяем дату (по умолчанию - завтра, если не указано)
                        if "сегодня" in user_input:
                            today = datetime.now()
                            date_str = today.strftime("%d.%m.%Y")
                        elif "завтра" in user_input:
                            tomorrow = datetime.now() + timedelta(days=1)
                            date_str = tomorrow.strftime("%d.%m.%Y")
                        else:
                            # По умолчанию - завтра
                            tomorrow = datetime.now() + timedelta(days=1)
                            date_str = tomorrow.strftime("%d.%m.%Y")
                        
                        start_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                        end_datetime = f"{date_str} {hour+1:02d}:{minute:02d}"
                        
                        try:
                            result = await simple_create_event.ainvoke({
                                "title": title,
                                "start_datetime": start_datetime,
                                "end_datetime": end_datetime,
                                "description": f"Событие создано через GigaChat Agent",
                                "user_name": "",
                                "user_username": ""
                            })
                            return result
                        except Exception as e:
                            logger.error(f"Ошибка создания события: {e}")
                            return f"❌ Ошибка создания события: {str(e)}"
                
                return f"""📋 **Создание события**

Не удалось извлечь полную информацию о событии из запроса: "{user_request}"

Для создания события укажите:
• Название события (в кавычках или после слова "событие")
• Дату (завтра, сегодня или конкретную дату, например "1 января 2026" или "01.01.2026")
• Время (в формате ЧЧ:ММ, опционально)

Примеры:
• "добавь событие 'Новогодние выходные' с 1 по 7 января 2026 года"
• "создай событие 'Встреча' на 1 января 2026 в 12:00"
• "добавь событие 'Выходной' на 1 января 2026 весь день"

Примеры:
• "добавь событие 'забег Оксаны' на завтра в 12:00"
• "создай встречу на завтра в 15:00"
• "добавь событие на 20.01.2025 в 10:00"

Извлеченные данные:
• Название: {title}
• Время начала: {start_datetime or 'не определено'}
• Время окончания: {end_datetime or 'не определено'}"""
            
        elif any(phrase in user_input for phrase in ["свободные слоты", "доступное время", "когда свободен", "свободное время"]):
            # Извлекаем дату из запроса
            date = None
            for word in user_input.split():
                if len(word) == 10 and word.count('-') == 2:  # формат YYYY-MM-DD
                    date = word
                    break
                elif len(word) == 10 and word.count('.') == 2:  # формат DD.MM.YYYY
                    try:
                        from datetime import datetime
                        date_obj = datetime.strptime(word, "%d.%m.%Y")
                        date = date_obj.strftime("%Y-%m-%d")
                        break
                    except:
                        pass
            
            if not date:
                return "❌ **Укажите дату**\n\nПример: 'показать свободные слоты на 2025-01-20' или 'свободное время на 20.01.2025'"
            
            result = await simple_get_available_slots.ainvoke({"date": date})
            return result
            
        elif any(phrase in user_input for phrase in ["статус календар", "проверить календарь", "подключен ли календарь", "календарь подключен"]):
            result = await simple_calendar_status.ainvoke({})
            return result
            
        elif any(phrase in user_input for phrase in ["удалить событие", "удали событие", "отменить событие", "удалить встречу"]):
            # Проверяем, есть ли ID события в запросе
            import re
            event_id_match = re.search(r'id[:\s]+([a-zA-Z0-9_\-]+)', user_input)
            
            if event_id_match:
                # Удаление по ID
                event_id = event_id_match.group(1)
                result = await simple_delete_event.ainvoke({"event_id": event_id})
                return result.get("message", str(result))
            
            # Извлекаем название события из запроса
            title_match = re.search(r'["\']([^"\']+)["\']', user_request)
            if not title_match:
                # Пытаемся извлечь название после "событие" или "встречу"
                title_patterns = [
                    r'(?:удалить|удали|отменить)\s+(?:событие|встречу)\s+["\']([^"\']+)["\']',
                    r'(?:удалить|удали|отменить)\s+(?:событие|встречу)\s+([а-яё\w\s]+?)(?:\s|$|подтверждаю|да)',
                    r'(?:удалить|удали|отменить)\s+([а-яё\w\s]+?)(?:\s+событие|\s+встречу|$)',
                ]
                for pattern in title_patterns:
                    match = re.search(pattern, user_input, re.IGNORECASE)
                    if match:
                        title_match = match
                        break
            
            if title_match:
                # Удаление по названию
                event_title = title_match.group(1).strip()
                # Сначала ищем событие
                search_result = await simple_find_event_by_title.ainvoke({
                    "title": event_title,
                    "max_results": 5
                })
                
                if search_result.get("error") or not search_result.get("events"):
                    return f"❌ **Событие не найдено**\n\nСобытие с названием '{event_title}' не найдено в календаре."
                
                events = search_result.get("events", [])
                if len(events) == 1:
                    # Одно событие - удаляем сразу
                    event_id = events[0]["id"]
                    result = await simple_delete_event.ainvoke({"event_id": event_id})
                    return result.get("message", str(result))
                else:
                    # Несколько событий - показываем список
                    message = f"📅 **Найдено {len(events)} событий с названием '{event_title}':**\n\n"
                    for i, event in enumerate(events, 1):
                        message += f"{i}. **{event['title']}** - {event['time']} (ID: `{event['id']}`)\n"
                    message += f"\n💡 Укажите ID события для удаления, например:\n\"удалить событие id {events[0]['id']}\""
                    return message
            
            # Извлекаем ключевые слова из запроса (старый способ)
            keywords = extract_keywords_from_request(user_input)
            if not keywords:
                return """🗑️ **Удаление события**

Для удаления событий укажите:
• Название события в кавычках: "удалить событие 'название'"
• ID события: "удалить событие id abc123"
• Ключевые слова: "удалить событие с git"

⚠️ Внимание: Удаление требует подтверждения!"""
            
            # Проверяем, есть ли подтверждение
            has_confirm = any(phrase in user_input for phrase in ["подтверждаю", "да", "yes", "удалить"])
            
            if not has_confirm:
                return f"""⚠️ **Подтверждение удаления требуется**

Вы хотите удалить события с ключевыми словами: **{keywords}**

Для подтверждения добавьте "подтверждаю" или "да" к запросу, например:
"удалить события с {keywords} подтверждаю"

⚠️ Это действие нельзя отменить!"""
            
            result = await delete_events_by_keywords.ainvoke({
                "keywords": keywords,
                "days_back": 30,
                "include_past": True,
                "confirm": True
            })
            return result
        
        elif any(phrase in user_input for phrase in ["перенести событие", "перенеси событие", "перенести встречу", "перенеси встречу", "изменить время", "измени время"]):
            # Извлекаем ID события
            import re
            event_id_match = re.search(r'id[:\s]+([a-zA-Z0-9_\-]+)', user_input)
            
            # Извлекаем название события
            title_match = re.search(r'["\']([^"\']+)["\']', user_request)
            if not title_match:
                title_patterns = [
                    r'(?:перенести|перенеси|изменить|измени)\s+(?:событие|встречу)\s+["\']([^"\']+)["\']',
                    r'(?:перенести|перенеси|изменить|измени)\s+(?:событие|встречу)\s+([а-яё\w\s]+?)(?:\s+на|\s+в\s+\d)',
                ]
                for pattern in title_patterns:
                    match = re.search(pattern, user_input, re.IGNORECASE)
                    if match:
                        title_match = match
                        break
            
            event_id = None
            if event_id_match:
                event_id = event_id_match.group(1)
            elif title_match:
                # Ищем событие по названию
                event_title = title_match.group(1).strip()
                search_result = await simple_find_event_by_title.ainvoke({
                    "title": event_title,
                    "max_results": 1
                })
                
                if search_result.get("error") or not search_result.get("events"):
                    return f"❌ **Событие не найдено**\n\nСобытие с названием '{event_title}' не найдено в календаре."
                
                events = search_result.get("events", [])
                if len(events) > 1:
                    return f"❌ **Найдено несколько событий**\n\nНайдено {len(events)} событий с таким названием. Укажите ID события."
                
                event_id = events[0]["id"]
            
            if not event_id:
                return """📅 **Перенос события**

Для переноса события укажите:
• Название события в кавычках: "перенести событие 'название' на завтра в 15:00"
• ID события: "перенести событие id abc123 на завтра в 15:00"

Примеры:
• "перенести событие 'встреча' на завтра в 14:00"
• "перенеси встречу id abc123 на 20.01.2025 в 10:00"
"""
            
            # Извлекаем новую дату и время
            new_datetime = None
            new_end_datetime = None
            
            # Проверяем "на завтра"
            if "завтра" in user_input:
                tomorrow = datetime.now() + timedelta(days=1)
                date_str = tomorrow.strftime("%d.%m.%Y")
                
                time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2))
                    new_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                    new_end_datetime = f"{date_str} {hour+1:02d}:{minute:02d}"
            
            # Проверяем "на сегодня"
            elif "сегодня" in user_input:
                today = datetime.now()
                date_str = today.strftime("%d.%m.%Y")
                
                time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2))
                    new_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                    new_end_datetime = f"{date_str} {hour+1:02d}:{minute:02d}"
            
            # Проверяем конкретную дату
            if not new_datetime:
                date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', user_input)
                if date_match:
                    day = int(date_match.group(1))
                    month = int(date_match.group(2))
                    year = int(date_match.group(3))
                    date_str = f"{day:02d}.{month:02d}.{year}"
                    
                    time_match = re.search(r'(\d{1,2}):(\d{2})', user_input)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2))
                        new_datetime = f"{date_str} {hour:02d}:{minute:02d}"
                        new_end_datetime = f"{date_str} {hour+1:02d}:{minute:02d}"
            
            if not new_datetime:
                return f"""❌ **Не указано новое время**

Укажите новую дату и время для события, например:
• "перенести событие id {event_id} на завтра в 15:00"
• "перенеси встречу id {event_id} на 20.01.2025 в 10:00"
"""
            
            # Переносим событие
            result = await simple_update_event.ainvoke({
                "event_id": event_id,
                "start_datetime": new_datetime,
                "end_datetime": new_end_datetime
            })
            
            if isinstance(result, dict):
                return result.get("message", str(result))
            return result
        
        elif any(phrase in user_input for phrase in ["найти событие", "найди событие", "поиск события"]):
            # Извлекаем название события
            import re
            title_match = re.search(r'["\']([^"\']+)["\']', user_request)
            if not title_match:
                title_patterns = [
                    r'(?:найти|найди|поиск)\s+(?:событие|встречу)\s+["\']([^"\']+)["\']',
                    r'(?:найти|найди|поиск)\s+(?:событие|встречу)\s+([а-яё\w\s]+?)(?:\s|$)',
                    r'(?:найти|найди|поиск)\s+([а-яё\w\s]+?)(?:\s+событие|\s+встречу|$)',
                ]
                for pattern in title_patterns:
                    match = re.search(pattern, user_input, re.IGNORECASE)
                    if match:
                        title_match = match
                        break
            
            if not title_match:
                return """🔍 **Поиск события**

Для поиска события укажите название, например:
• "найти событие 'встреча'"
• "найди событие с git"
• "поиск события встреча"
"""
            
            event_title = title_match.group(1).strip()
            result = await simple_find_event_by_title.ainvoke({
                "title": event_title,
                "max_results": 10
            })
            
            if isinstance(result, dict):
                return result.get("message", str(result))
            return result
            
        else:
            print("🔍 CALENDAR AGENT: No pattern matched, returning help")
            return """📅 **Улучшенный Google Calendar Agent**

Доступные команды:
• "показать события" - показать список событий (включая прошедшие)
• "показать события на месяц" - события на месяц вперед
• "показать события на неделю" - события на неделю
• "найти событие 'название'" - поиск события по названию
• "удалить событие 'название'" - удаление события по названию
• "удалить событие id abc123" - удаление события по ID
• "перенести событие 'название' на завтра в 15:00" - перенос события
• "перенести событие id abc123 на 20.01.2025 в 10:00" - перенос по ID
• "создать событие" - создать новое событие
• "свободные слоты на [дата]" - показать доступное время
• "статус календаря" - проверить подключение

Примеры:
• "покажи все события включая прошлые"
• "найди событие 'встреча'"
• "удали событие 'встреча'"
• "перенести событие 'встреча' на завтра в 14:00"
• "удали событие id abc123def456"
• "свободные слоты на 20.01.2025"
• "создай встречу на завтра в 15:00"

🆕 Новые возможности:
• Поиск событий по названию
• Удаление событий по названию или ID
• Перенос событий на другое время
• Обновление событий"""
            
    except Exception as e:
        logger.error(f"Ошибка в calendar_agent: {e}")
        return f"❌ Ошибка обработки запроса: {str(e)}"

# Создаем промпт для агента
CALENDAR_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Ты - эксперт по работе с Google Calendar через Service Account.

Твоя задача - помочь пользователю с управлением календарем:
- Показывать события и расписание
- Создавать новые события
- Проверять статус подключения
- Показывать свободные временные слоты

Используй улучшенные инструменты для работы с прошедшими событиями.
Всегда отвечай на русском языке и будь дружелюбным."""),
    MessagesPlaceholder("messages"),
])

# Создаем граф
def create_calendar_graph():
    """Создание графа calendar_agent"""
    
    # Определяем состояние
    class CalendarAgentState(TypedDict):
        messages: Annotated[list, "Список сообщений"]
        user_request: str
        user_id: str
        current_step: str
        error: str

    # Создаем граф
    workflow = StateGraph(CalendarAgentState)
    
    # Добавляем узлы
    workflow.add_node("calendar_agent", calendar_agent)
    
    # Добавляем ребра
    workflow.add_edge(START, "calendar_agent")
    workflow.add_edge("calendar_agent", END)
    
    # Компилируем граф
    return workflow.compile()

def extract_keywords_from_request(user_input: str) -> str:
    """Извлекает ключевые слова из запроса пользователя"""
    # Ищем паттерны типа "с git", "с github", "с монтаж"
    import re
    
    # Паттерны для извлечения ключевых слов
    patterns = [
        r"с\s+([а-яё\w\s]+?)(?:\s|$|подтверждаю|да)",
        r"по\s+([а-яё\w\s]+?)(?:\s|$|подтверждаю|да)",
        r"содержащие\s+([а-яё\w\s]+?)(?:\s|$|подтверждаю|да)",
        r"включающие\s+([а-яё\w\s]+?)(?:\s|$|подтверждаю|да)"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, user_input, re.IGNORECASE)
        if match:
            keywords = match.group(1).strip()
            # Очищаем от лишних слов
            keywords = re.sub(r'\b(события?|событие)\b', '', keywords, flags=re.IGNORECASE).strip()
            if keywords:
                return keywords
    
    return ""


# Создаем экземпляр графа
graph = create_calendar_graph()