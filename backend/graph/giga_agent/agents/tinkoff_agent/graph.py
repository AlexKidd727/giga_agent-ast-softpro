"""
Граф Tinkoff Trading Agent
"""

import logging
import re
from typing import Annotated, TypedDict
from datetime import datetime, timedelta

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import InjectedState
from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message

from giga_agent.agents.tinkoff_agent.nodes.portfolio import get_portfolio, get_positions, get_balance, get_portfolio_summary, get_all_accounts, get_portfolio_all_accounts, get_positions_all_accounts
from giga_agent.agents.tinkoff_agent.nodes.orders import (
    place_market_order, place_limit_order, get_orders, cancel_order,
    buy_market, sell_market, buy_limit, sell_limit
)
from giga_agent.agents.tinkoff_agent.nodes.instruments import (
    search_instrument, get_instrument_info, get_current_price, 
    find_figi_by_ticker, get_instrument_details
)
from giga_agent.agents.tinkoff_agent.nodes.operations import (
    get_operations, get_operations_today, get_operations_week, 
    get_operations_month, get_operations_by_type, get_operations_summary
)
from giga_agent.agents.tinkoff_agent.nodes.charts import (
    create_ticker_chart, get_available_timeframes, get_popular_tickers,
    search_ticker_info, create_multiple_charts, get_current_price
)

logger = logging.getLogger(__name__)

def parse_date_from_request(user_request: str) -> tuple[str, str]:
    """
    Парсинг дат из запроса пользователя
    
    Args:
        user_request: Запрос пользователя
        
    Returns:
        tuple: (from_date, to_date) в формате YYYY-MM-DD
    """
    user_request_lower = user_request.lower()
    
    # Паттерны для поиска дат
    date_patterns = [
        r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})',
        r'(\d{1,2})\.(\d{1,2})\.(\d{4})',
        r'(\d{4})-(\d{1,2})-(\d{1,2})',
        r'(\d{1,2})/(\d{1,2})/(\d{4})'
    ]
    
    # Словарь месяцев
    months = {
        'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
        'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
        'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
    }
    
    found_date = None
    
    # Ищем дату в запросе
    for pattern in date_patterns:
        match = re.search(pattern, user_request_lower)
        if match:
            if 'января' in pattern or 'февраля' in pattern:  # Русские названия месяцев
                day, month_name, year = match.groups()
                month = months[month_name]
                found_date = datetime(int(year), month, int(day))
            else:  # Числовые форматы
                groups = match.groups()
                if len(groups) == 3:
                    if pattern.endswith(r'(\d{4})'):  # DD.MM.YYYY или DD/MM/YYYY
                        day, month, year = groups
                        found_date = datetime(int(year), int(month), int(day))
                    else:  # YYYY-MM-DD
                        year, month, day = groups
                        found_date = datetime(int(year), int(month), int(day))
            break
    
    # Если дата найдена, определяем период
    if found_date:
        # Проверяем ключевые слова для определения типа запроса
        if any(word in user_request_lower for word in ['после', 'с', 'от']):
            # Запрос "после даты" - от найденной даты до сегодня
            from_date = found_date.strftime("%Y-%m-%d")
            to_date = datetime.now().strftime("%Y-%m-%d")
        elif any(word in user_request_lower for word in ['до', 'по']):
            # Запрос "до даты" - от начала года до найденной даты
            from_date = datetime(found_date.year, 1, 1).strftime("%Y-%m-%d")
            to_date = found_date.strftime("%Y-%m-%d")
        else:
            # По умолчанию - только указанная дата
            from_date = found_date.strftime("%Y-%m-%d")
            to_date = found_date.strftime("%Y-%m-%d")
        
        return from_date, to_date
    
    # Если дата не найдена, возвращаем значения по умолчанию
    return None, None

class TinkoffAgentState(TypedDict):
    """Состояние агента Tinkoff"""
    messages: Annotated[list, "Список сообщений"]
    user_request: str
    user_id: str
    current_step: str
    error: str

# Создаем список всех доступных инструментов
TINKOFF_TOOLS = [
    # Портфель
    get_portfolio,
    get_positions,
    get_balance,
    get_portfolio_summary,
    get_all_accounts,
    get_portfolio_all_accounts,
    get_positions_all_accounts,
    
    # Инструменты
    search_instrument,
    get_instrument_info,
    get_current_price,
    find_figi_by_ticker,
    get_instrument_details,
    
    # Ордера
    place_market_order,
    place_limit_order,
    get_orders,
    cancel_order,
    buy_market,
    sell_market,
    buy_limit,
    sell_limit,
    
    # Операции
    get_operations,
    get_operations_today,
    get_operations_week,
    get_operations_month,
    get_operations_by_type,
    get_operations_summary,
    
    # Графики
    create_ticker_chart,
    get_available_timeframes,
    get_popular_tickers,
    search_ticker_info,
    create_multiple_charts,
    get_current_price,
]

# Создаем промпт для агента
TINKOFF_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Ты - эксперт по торговле через Tinkoff Invest API. Твоя задача - помочь пользователю с торговыми операциями.

У тебя есть полный доступ к аккаунту Tinkoff Invest пользователя.

Ты можешь показывать реальный портфель, искать инструменты, размещать ордера и выполнять другие торговые операции.

Доступные функции:

**ПОРТФЕЛЬ:**
- get_portfolio - показать полный портфель пользователя
- get_positions - показать позиции в портфеле (по умолчанию для команд "портфель", "позиции", "акции")
- get_balance - показать баланс счета
- get_portfolio_summary - краткая сводка по портфелю (для команд "сводка", "итоги", "стоимость портфеля")

**ОПЕРАЦИИ (приоритет над портфелем):**
- get_operations - операции за период (для команд "последних 5 операций", "последние операции")
- get_operations_today - операции за сегодня
- get_operations_week - операции за неделю  
- get_operations_month - операции за месяц (по умолчанию для команд "операции", "сделки", "история")

**ИНСТРУМЕНТЫ:**
- search_instrument(ticker, instrument_type) - поиск инструмента по тикеру
- get_instrument_info(figi) - информация об инструменте по FIGI
- get_current_price(figi) - текущая цена инструмента
- find_figi_by_ticker(ticker) - найти FIGI по тикеру
- get_instrument_details(ticker) - детальная информация по тикеру

**ОРДЕРА:**
- place_market_order(figi, quantity, direction) - рыночный ордер
- place_limit_order(figi, quantity, price, direction) - лимитный ордер
- get_orders - список активных ордеров
- cancel_order(order_id) - отмена ордера
- buy_market(figi, quantity) - покупка по рынку
- sell_market(figi, quantity) - продажа по рынку
- buy_limit(figi, quantity, price) - покупка по лимиту
- sell_limit(figi, quantity, price) - продажа по лимиту

**ОПЕРАЦИИ:**
- get_operations(from_date, to_date) - операции за период
- get_operations_today - операции за сегодня
- get_operations_week - операции за неделю
- get_operations_month - операции за месяц
- get_operations_by_type(type, from_date, to_date) - операции по типу

**ГРАФИКИ:**
- create_ticker_chart(ticker, timeframe, num_candles) - создать график по тикеру
- get_available_timeframes - получить доступные таймфреймы
- get_popular_tickers - получить список популярных российских акций
- search_ticker_info(ticker) - найти информацию об инструменте
- create_multiple_charts(tickers, timeframe, num_candles) - создать графики для нескольких тикеров
- get_current_price(ticker) - получить текущую цену инструмента
- get_operations_summary(from_date, to_date) - сводка по операциям

**ВАЖНО:**
1. Всегда проверяй лотность инструмента перед размещением ордера
2. Для поиска инструментов используй search_instrument или find_figi_by_ticker
3. Для ордеров direction может быть: "buy", "sell", "покупка", "продажа"
4. Даты в формате YYYY-MM-DD
5. Будь внимателен к валютам и комиссиям

Отвечай на русском языке, будь дружелюбным и профессиональным."""),
    MessagesPlaceholder(variable_name="messages"),
])

def router(state: TinkoffAgentState) -> TinkoffAgentState:
    """Маршрутизатор для определения следующего шага"""
    last_message = state["messages"][-1]
    
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        state["current_step"] = "tool_call"
    else:
        # Если нет tool_calls, обрабатываем запрос пользователя
        user_request = state.get("user_request", "").lower()
        
        # Проверяем запросы об операциях ПЕРВЫМИ (более специфичные)
        if any(word in user_request for word in ["операции", "операций", "сделки", "сделок", "транзакции", "транзакций", "история", "последних", "последние"]):
            # Создаем вызов инструмента для получения операций
            from langchain_core.messages import AIMessage
            
            # Сначала пытаемся парсить конкретные даты из запроса
            from_date, to_date = parse_date_from_request(user_request)
            
            # Определяем какой инструмент вызывать для операций
            if any(word in user_request for word in ["сегодня", "день"]):
                tool_name = "get_operations_today"
                tool_args = {"user_id": state.get("user_id", "default_user")}
                content = "Получаю операции за сегодня..."
            elif any(word in user_request for word in ["неделя", "неделю", "недели"]):
                tool_name = "get_operations_week"
                tool_args = {"user_id": state.get("user_id", "default_user")}
                content = "Получаю операции за неделю..."
            elif any(word in user_request for word in ["месяц", "месяца"]):
                tool_name = "get_operations_month"
                tool_args = {"user_id": state.get("user_id", "default_user")}
                content = "Получаю операции за месяц..."
            elif from_date and to_date:
                # Если найдены конкретные даты, используем get_operations с этими датами
                tool_name = "get_operations"
                tool_args = {
                    "user_id": state.get("user_id", "default_user"),
                    "from_date": from_date,
                    "to_date": to_date
                }
                content = f"Получаю операции за период {from_date} - {to_date}..."
            elif any(word in user_request for word in ["последних", "последние", "5", "10", "несколько"]):
                # Для запросов типа "последних 5 операций" используем get_operations с ограничением
                # Ограничиваем период последними 30 днями вместо всего года
                to_date = datetime.now().strftime("%Y-%m-%d")
                from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                tool_name = "get_operations"
                tool_args = {
                    "user_id": state.get("user_id", "default_user"),
                    "from_date": from_date,
                    "to_date": to_date
                }
                content = "Получаю последние операции за 30 дней..."
            else:
                # По умолчанию показываем операции за месяц
                tool_name = "get_operations_month"
                tool_args = {"user_id": state.get("user_id", "default_user")}
                content = "Получаю операции за месяц..."
            
            ai_message = AIMessage(
                content=content,
                tool_calls=[{
                    "name": tool_name,
                    "args": tool_args,
                    "id": "operations_call_1"
                }]
            )
            state["messages"].append(ai_message)
            state["current_step"] = "tool_call"
        elif any(word in user_request for word in ["портфель", "портфолио", "портфели", "позиции", "акции", "акций"]):
            # Создаем вызов инструмента для получения портфеля
            from langchain_core.messages import AIMessage
            
            # Определяем какой инструмент вызывать
            if any(word in user_request for word in ["все счета", "всех счетов", "по всем счетам", "все портфели", "всех портфелей", "все портфолио", "всех портфолио", "портфели акций", "портфолио акций"]):
                tool_name = "get_portfolio_all_accounts"
                tool_args = {}
                content = "Получаю портфолио по всем вашим счетам..."
            elif any(word in user_request for word in ["счета", "список счетов", "мои счета", "какие счета"]):
                tool_name = "get_all_accounts"
                tool_args = {}
                content = "Получаю список всех ваших счетов..."
            elif any(word in user_request for word in ["сводка", "итоги", "общая", "стоимость", "прибыль", "убыток", "сколько", "какова", "цена портфеля", "текущая прибыль", "текущий убыток"]):
                tool_name = "get_portfolio_summary"
                tool_args = {"user_id": state.get("user_id", "default_user")}
                content = "Получаю сводку по вашему портфелю..."
            else:
                # По умолчанию показываем детальные позиции по всем счетам
                tool_name = "get_positions_all_accounts"
                tool_args = {}
                content = "Получаю детальные позиции по всем вашим счетам..."
            
            ai_message = AIMessage(
                content=content,
                tool_calls=[{
                    "name": tool_name,
                    "args": tool_args,
                    "id": "portfolio_call_1"
                }]
            )
            state["messages"].append(ai_message)
            state["current_step"] = "tool_call"
        elif any(word in user_request for word in ["график", "chart", "свечи", "candles", "покажи график", "нарисуй график", "создай график", "отобрази график", "покажи график", "отрисуй график"]) and not any(phrase in user_request for phrase in ["выглядит следующим образом", "получился такой", "создан успешно", "graph:", "![График"]):
            # Создание графика по названию компании или тикеру
            from langchain_core.messages import AIMessage
            
            # Извлекаем название компании/тикер из запроса - улучшенная логика
            company_name = None
            timeframe = "1day"  # По умолчанию дневной таймфрейм
            num_candles = 40    # По умолчанию 40 свечей
            
            # Исключаем служебные слова
            exclude_words = [
                "график", "chart", "свечи", "candles", "покажи", "нарисуй", 
                "для", "по", "компании", "акций", "акции", "тикер", "ticker"
            ]
            
            # Сначала пытаемся найти тикер (короткое слово в верхнем регистре)
            words = user_request.split()
            ticker_found = None
            
            for word in words:
                word_upper = word.upper().strip('.,!?;:')
                # Тикер - это короткое слово (2-5 символов) из букв в верхнем регистре
                if (len(word_upper) >= 2 and len(word_upper) <= 5 and 
                    word_upper.isalpha() and word_upper.isupper() and
                    word_upper not in ["ГРАФИК", "CHART", "ПОКАЖИ", "СОЗДАЙ", "ДЛЯ", "АКЦИИ", "ТИКЕР", "НАРИСУЙ", "ОТОБРАЗИ"]):
                    ticker_found = word_upper
                    break
            
            if ticker_found:
                company_name = ticker_found
            else:
                # Если тикер не найден, пытаемся найти название компании
                words_lower = user_request.lower().split()
                company_words = []
                
                for word in words_lower:
                    word_clean = word.strip('.,!?;:')
                    if len(word_clean) >= 3 and word_clean.isalpha() and word_clean not in exclude_words:
                        company_words.append(word_clean)
                
                # Собираем название компании из найденных слов
                if company_words:
                    # Если есть несколько слов, берем все (для составных названий)
                    company_name = " ".join(company_words)
                else:
                    # Если название не найдено, используем SBER по умолчанию
                    company_name = "SBER"
            
            # Проверяем таймфрейм в запросе
            if any(word in user_request.lower() for word in ["1min", "1 мин", "минута"]):
                timeframe = "1min"
            elif any(word in user_request.lower() for word in ["15min", "15 мин", "15 минут"]):
                timeframe = "15min"
            elif any(word in user_request.lower() for word in ["1hour", "1 час", "час"]):
                timeframe = "1hour"
            elif any(word in user_request.lower() for word in ["1day", "1 день", "день", "дневной"]):
                timeframe = "1day"
            
            ai_message = AIMessage(
                content=f"Создаю график для {company_name} ({timeframe})...",
                tool_calls=[{
                    "name": "create_ticker_chart",
                    "args": {
                        "ticker": company_name,
                        "timeframe": timeframe,
                        "num_candles": num_candles
                    },
                    "id": "chart_call_1"
                }]
            )
            state["messages"].append(ai_message)
            state["current_step"] = "tool_call"
        elif any(word in user_request for word in ["продай", "продать", "sell"]):
            # Обработка команд продажи
            from langchain_core.messages import AIMessage
            
            # Извлекаем информацию из запроса
            quantity = 1  # По умолчанию 1 лот
            ticker = None
            
            # Ищем количество в запросе
            import re
            quantity_match = re.search(r'(\d+)\s*(?:лот|штук|акций)', user_request)
            if quantity_match:
                quantity = int(quantity_match.group(1))
            
            # Ищем тикер или название компании
            # Список популярных тикеров для поиска
            popular_tickers = ["SBER", "GAZP", "LKOH", "ROSN", "TCSG", "MGNT", "YNDX", "MTSS", "GMKN", "AFKS", "NVTK", "TATN", "ALRS", "CHMF", "IRKT", "MTLR"]
            for ticker_name in popular_tickers:
                if ticker_name.lower() in user_request.lower():
                    ticker = ticker_name
                    break
            
            # Если не найден тикер, ищем по названиям компаний
            if not ticker:
                if "мечел" in user_request.lower():
                    ticker = "MTLR"
                elif "сбер" in user_request.lower():
                    ticker = "SBER"
                elif "газпром" in user_request.lower():
                    ticker = "GAZP"
                elif "лукойл" in user_request.lower():
                    ticker = "LKOH"
                elif "роснефть" in user_request.lower():
                    ticker = "ROSN"
                elif "тинькофф" in user_request.lower():
                    ticker = "TCSG"
                elif "магнит" in user_request.lower():
                    ticker = "MGNT"
                elif "яндекс" in user_request.lower():
                    ticker = "YNDX"
                elif "мтс" in user_request.lower():
                    ticker = "MTSS"
                elif "норникель" in user_request.lower():
                    ticker = "GMKN"
                elif "система" in user_request.lower():
                    ticker = "AFKS"
                elif "новатэк" in user_request.lower():
                    ticker = "NVTK"
                elif "татнефть" in user_request.lower():
                    ticker = "TATN"
                elif "алроса" in user_request.lower():
                    ticker = "ALRS"
                elif "северсталь" in user_request.lower():
                    ticker = "CHMF"
                elif "яковлев" in user_request.lower():
                    ticker = "IRKT"
            
            if ticker:
                # Сначала ищем FIGI для тикера
                ai_message = AIMessage(
                    content=f"Ищу FIGI для {ticker} и размещаю ордер на продажу {quantity} лот...",
                    tool_calls=[{
                        "name": "find_figi_by_ticker",
                        "args": {"ticker": ticker, "instrument_type": "shares"},
                        "id": "find_figi_call_1"
                    }]
                )
                state["messages"].append(ai_message)
                state["current_step"] = "tool_call"
            else:
                # Если не найден тикер, показываем портфель
                ai_message = AIMessage(
                    content="Не удалось определить инструмент для продажи. Показываю ваш портфель...",
                    tool_calls=[{
                        "name": "get_positions",
                        "args": {"user_id": state.get("user_id", "default_user")},
                        "id": "portfolio_call_1"
                    }]
                )
                state["messages"].append(ai_message)
                state["current_step"] = "tool_call"
        elif any(word in user_request for word in ["купи", "купить", "buy"]):
            # Обработка команд покупки
            from langchain_core.messages import AIMessage
            
            # Извлекаем информацию из запроса
            quantity = 1  # По умолчанию 1 лот
            ticker = None
            
            # Ищем количество в запросе
            import re
            quantity_match = re.search(r'(\d+)\s*(?:лот|штук|акций)', user_request)
            if quantity_match:
                quantity = int(quantity_match.group(1))
            
            # Ищем тикер или название компании
            popular_tickers = ["SBER", "GAZP", "LKOH", "ROSN", "TCSG", "MGNT", "YNDX", "MTSS", "GMKN", "AFKS", "NVTK", "TATN", "ALRS", "CHMF", "IRKT", "MTLR"]
            for ticker_name in popular_tickers:
                if ticker_name.lower() in user_request.lower():
                    ticker = ticker_name
                    break
            
            # Если не найден тикер, ищем по названиям компаний
            if not ticker:
                if "мечел" in user_request.lower():
                    ticker = "MTLR"
                elif "сбер" in user_request.lower():
                    ticker = "SBER"
                elif "газпром" in user_request.lower():
                    ticker = "GAZP"
                elif "лукойл" in user_request.lower():
                    ticker = "LKOH"
                elif "роснефть" in user_request.lower():
                    ticker = "ROSN"
                elif "тинькофф" in user_request.lower():
                    ticker = "TCSG"
                elif "магнит" in user_request.lower():
                    ticker = "MGNT"
                elif "яндекс" in user_request.lower():
                    ticker = "YNDX"
                elif "мтс" in user_request.lower():
                    ticker = "MTSS"
                elif "норникель" in user_request.lower():
                    ticker = "GMKN"
                elif "система" in user_request.lower():
                    ticker = "AFKS"
                elif "новатэк" in user_request.lower():
                    ticker = "NVTK"
                elif "татнефть" in user_request.lower():
                    ticker = "TATN"
                elif "алроса" in user_request.lower():
                    ticker = "ALRS"
                elif "северсталь" in user_request.lower():
                    ticker = "CHMF"
                elif "яковлев" in user_request.lower():
                    ticker = "IRKT"
            
            if ticker:
                # Сначала ищем FIGI для тикера
                ai_message = AIMessage(
                    content=f"Ищу FIGI для {ticker} и размещаю ордер на покупку {quantity} лот...",
                    tool_calls=[{
                        "name": "find_figi_by_ticker",
                        "args": {"ticker": ticker, "instrument_type": "shares"},
                        "id": "find_figi_call_1"
                    }]
                )
                state["messages"].append(ai_message)
                state["current_step"] = "tool_call"
            else:
                # Если не найден тикер, показываем портфель
                ai_message = AIMessage(
                    content="Не удалось определить инструмент для покупки. Показываю ваш портфель...",
                    tool_calls=[{
                        "name": "get_positions",
                        "args": {"user_id": state.get("user_id", "default_user")},
                        "id": "portfolio_call_1"
                    }]
                )
                state["messages"].append(ai_message)
                state["current_step"] = "tool_call"
        elif any(word in user_request for word in ["найди", "поиск", "sber", "тикер"]):
            # Поиск инструмента
            from langchain_core.messages import AIMessage
            ai_message = AIMessage(
                content="Ищу инструмент...",
                tool_calls=[{
                    "name": "search_instrument",
                    "args": {"ticker": "SBER", "instrument_type": "shares"},
                    "id": "search_call_1"
                }]
            )
            state["messages"].append(ai_message)
            state["current_step"] = "tool_call"
        else:
            state["current_step"] = "done"
    
    return state

async def tool_call(state: TinkoffAgentState) -> TinkoffAgentState:
    """Обработка вызова инструмента"""
    last_message = state["messages"][-1]
    
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        state["error"] = "Нет вызовов инструментов для обработки"
        return state
    
    tool_calls = last_message.tool_calls
    tool_messages = []
    
    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        
        try:
            # Находим нужный инструмент
            tool_func = None
            for tool in TINKOFF_TOOLS:
                if tool.name == tool_name:
                    tool_func = tool
                    break
            
            if not tool_func:
                error_msg = f"Инструмент {tool_name} не найден"
                tool_messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call["id"]))
                continue
            
            # Вызываем инструмент
            if tool_func.coroutine:
                result = await tool_func.ainvoke(tool_args)
            else:
                result = tool_func.invoke(tool_args)
            
            # Специальная обработка для создания графиков
            logger.info(f"🔧 TOOL_CALL: tool_name={tool_name}, result_type={type(result)}, result_keys={list(result.keys()) if isinstance(result, dict) else 'not_dict'}")
            if tool_name == "create_ticker_chart" and isinstance(result, dict) and result.get("success") and result.get("chart_base64"):
                # Создаем attachment для графика
                import uuid
                file_id = str(uuid.uuid4())
                
                # Создаем короткое сообщение без base64 данных
                short_result = {
                    "success": result.get("success"),
                    "message": result.get("message", "График создан успешно"),
                    "ticker": result.get("ticker"),
                    "timeframe": result.get("timeframe"),
                    "num_candles": result.get("num_candles")
                }
                
                # Создаем ToolMessage с attachment
                tool_message = ToolMessage(
                    content=str(short_result), 
                    tool_call_id=tool_call["id"],
                    additional_kwargs={
                        "tool_attachments": [{
                            "type": "image/png",
                            "file_id": file_id
                        }]
                    }
                )
                
                # Сохраняем base64 данные в state для последующего сохранения в store
                if "chart_attachments" not in state:
                    state["chart_attachments"] = {}
                state["chart_attachments"][file_id] = {
                    "file_id": file_id,
                    "type": "image/png",
                    "data": result["chart_base64"]
                }
                
                # Обновляем state с chart_attachments
                state["chart_attachments"] = state["chart_attachments"]
                
                tool_messages.append(tool_message)
            else:
                tool_messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))
            
            # Если это поиск FIGI и в запросе была команда продажи/покупки, выполняем торговую операцию
            if tool_name == "find_figi_by_ticker" and result and "FIGI:" in str(result):
                user_request = state.get("user_request", "").lower()
                
                # Извлекаем FIGI из результата
                import re
                figi_match = re.search(r'FIGI: `([^`]+)`', str(result))
                if figi_match:
                    figi = figi_match.group(1)
                    
                    # Извлекаем количество
                    quantity = 1
                    quantity_match = re.search(r'(\d+)\s*(?:лот|штук|акций)', user_request)
                    if quantity_match:
                        quantity = int(quantity_match.group(1))
                    
                    # Определяем направление операции
                    if any(word in user_request for word in ["продай", "продать", "sell"]):
                        # Выполняем продажу
                        from langchain_core.messages import AIMessage
                        sell_message = AIMessage(
                            content=f"Размещаю рыночный ордер на продажу {quantity} лот...",
                            tool_calls=[{
                                "name": "sell_market",
                                "args": {"figi": figi, "quantity": quantity},
                                "id": "sell_market_call_1"
                            }]
                        )
                        state["messages"].append(sell_message)
                        
                        # Выполняем продажу
                        try:
                            from giga_agent.agents.tinkoff_agent.nodes.orders import sell_market
                            sell_result = await sell_market.ainvoke({"figi": figi, "quantity": quantity})
                            tool_messages.append(ToolMessage(content=str(sell_result), tool_call_id="sell_market_call_1"))
                        except Exception as e:
                            error_msg = f"Ошибка при продаже: {str(e)}"
                            tool_messages.append(ToolMessage(content=error_msg, tool_call_id="sell_market_call_1"))
                    
                    elif any(word in user_request for word in ["купи", "купить", "buy"]):
                        # Выполняем покупку
                        from langchain_core.messages import AIMessage
                        buy_message = AIMessage(
                            content=f"Размещаю рыночный ордер на покупку {quantity} лот...",
                            tool_calls=[{
                                "name": "buy_market",
                                "args": {"figi": figi, "quantity": quantity},
                                "id": "buy_market_call_1"
                            }]
                        )
                        state["messages"].append(buy_message)
                        
                        # Выполняем покупку
                        try:
                            from giga_agent.agents.tinkoff_agent.nodes.orders import buy_market
                            buy_result = await buy_market.ainvoke({"figi": figi, "quantity": quantity})
                            tool_messages.append(ToolMessage(content=str(buy_result), tool_call_id="buy_market_call_1"))
                        except Exception as e:
                            error_msg = f"Ошибка при покупке: {str(e)}"
                            tool_messages.append(ToolMessage(content=error_msg, tool_call_id="buy_market_call_1"))
            
        except Exception as e:
            error_msg = f"Ошибка при выполнении {tool_name}: {str(e)}"
            logger.error(error_msg)
            tool_messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call["id"]))
    
    state["messages"].extend(tool_messages)
    return state

def done_node(state: TinkoffAgentState) -> TinkoffAgentState:
    """Финальный узел"""
    return state

# Создаем граф
def create_tinkoff_agent():
    """Создание агента Tinkoff"""
    
    # Создаем граф
    workflow = StateGraph(TinkoffAgentState)
    
    # Добавляем узлы
    workflow.add_node("router", router)
    workflow.add_node("tool_call", tool_call)
    workflow.add_node("done", done_node)
    
    # Добавляем ребра
    workflow.add_edge(START, "router")
    workflow.add_conditional_edges(
        "router",
        lambda state: state.get("current_step", "done"),
        {
            "tool_call": "tool_call",
            "done": "done"
        }
    )
    workflow.add_edge("tool_call", "done")
    
    # Компилируем граф
    app = workflow.compile()
    
    return app

# Создаем агента
tinkoff_agent_app = create_tinkoff_agent()

@tool
async def tinkoff_agent(user_request: str, user_id: str = "default_user", **kwargs) -> dict:
    """
    Агент для торговли через Tinkoff Invest API
    
    Обрабатывает запросы пользователя связанные с торговлей:
    - Просмотр портфеля и позиций
    - Размещение ордеров на покупку/продажу
    - Управление активными ордерами
    - Поиск и анализ инструментов
    - Проверка текущих цен
    - Просмотр операций за период
    - **Создание графиков по тикерам и компаниям** (например, "покажи график IRKT", "график для SBER", "создай график для Газпрома")
    
    **ВАЖНО**: Для запросов на построение графиков по тикерам акций или названиям компаний (например, "покажи график IRKT", "график для SBER", "создай график для Газпрома") ОБЯЗАТЕЛЬНО используй этот агент. Он умеет строить графики свечей с объемами для любых российских акций.
    
    Args:
        user_request: Запрос пользователя (например, "показать портфель", "купить SBER", "покажи график IRKT")
        user_id: Идентификатор пользователя (необязательно)
    
    Returns:
        Ответ агента с результатами выполнения запроса (для графиков возвращает изображение графика)
    """
    try:
        logger.info(f"🔧 TINKOFF_AGENT: Получен запрос: {user_request}, user_id: {user_id}, kwargs: {kwargs}")
        
        # Обрабатываем случай, когда аргументы приходят в неправильном формате
        if isinstance(user_request, dict):
            # Если user_request это словарь, извлекаем нужные поля
            actual_request = user_request.get("user_request", str(user_request))
            actual_user_id = user_request.get("user_id", user_id)
            logger.info(f"🔧 TINKOFF_AGENT: Обработан словарь, actual_request: {actual_request}")
        else:
            actual_request = user_request
            actual_user_id = user_id
            
        # Создаем начальное состояние
        initial_state = {
            "messages": [HumanMessage(content=actual_request)],
            "user_request": actual_request,
            "user_id": actual_user_id,
            "current_step": "router",
            "error": None
        }
        
        # Проверяем, если это запрос на создание графика, вызываем напрямую
        if any(word in actual_request.lower() for word in ["график", "chart", "создай график", "покажи график"]):
            logger.info(f"🔧 TINKOFF_AGENT: Прямой вызов create_ticker_chart для: {actual_request}")
            
            # Извлекаем тикер из запроса - улучшенная логика
            import re
            ticker = None
            
            # Сначала пытаемся найти тикер после ключевых слов (более гибкое регулярное выражение)
            # Ищем тикер после слов: график, chart, для, покажи график и т.д.
            ticker_match = re.search(r'(?:график|chart|для|для акции|для тикера|покажи график|создай график)\s+([A-Z]{2,5})\b', actual_request, re.IGNORECASE)
            if ticker_match:
                ticker = ticker_match.group(1).upper()
            else:
                # Ищем тикер в конце запроса или в любом месте как отдельное слово
                # Сначала пробуем найти тикер в конце запроса (после всех служебных слов)
                ticker_match_end = re.search(r'\b([A-Z]{2,5})\b(?:\s*$|\.|,|!|\?)', actual_request, re.IGNORECASE)
                if ticker_match_end:
                    potential_ticker = ticker_match_end.group(1).upper()
                    # Проверяем, что это не служебное слово
                    if (potential_ticker not in ["ГРАФИК", "CHART", "ПОКАЖИ", "СОЗДАЙ", "ДЛЯ", "АКЦИИ", "ТИКЕР", "НАРИСУЙ", "ОТОБРАЗИ"] and
                        potential_ticker.isalpha()):
                        ticker = potential_ticker
                
                # Если не нашли, ищем тикер в запросе - короткое слово в верхнем регистре (2-5 букв)
                if not ticker:
                    words = actual_request.split()
                    for word in words:
                        word_upper = word.upper().strip('.,!?;:')
                        # Тикер - это короткое слово (2-5 символов) из букв в верхнем регистре
                        if (len(word_upper) >= 2 and len(word_upper) <= 5 and 
                            word_upper.isalpha() and word_upper.isupper() and
                            word_upper not in ["ГРАФИК", "CHART", "ПОКАЖИ", "СОЗДАЙ", "ДЛЯ", "АКЦИИ", "ТИКЕР", "НАРИСУЙ", "ОТОБРАЗИ"]):
                            ticker = word_upper
                            break
            
            # Если тикер не найден, используем значение по умолчанию
            if not ticker:
                ticker = "GAZP"  # По умолчанию
                logger.warning(f"🔧 TINKOFF_AGENT: Тикер не найден в запросе, используется {ticker}")
            else:
                logger.info(f"🔧 TINKOFF_AGENT: Извлечен тикер: {ticker}")
            
            # Вызываем create_ticker_chart напрямую
            from giga_agent.agents.tinkoff_agent.nodes.charts import create_ticker_chart
            chart_result = await create_ticker_chart.ainvoke({
                "ticker": ticker,
                "timeframe": "1day",
                "num_candles": 40
            })
            
            if chart_result.get("success") and chart_result.get("giga_attachments"):
                logger.info(f"🔧 TINKOFF_AGENT: Прямой вызов успешен, giga_attachments: {len(chart_result['giga_attachments'])}")
                return {
                    "status": "success",
                    "message": f"График для {ticker} успешно создан",
                    "giga_attachments": chart_result["giga_attachments"]
                }
            else:
                logger.error(f"🔧 TINKOFF_AGENT: Прямой вызов не удался: {chart_result}")
                # Продолжаем выполнение через обычный граф агента
        
        # Запускаем агента
        result = await tinkoff_agent_app.ainvoke(initial_state)
        
        # Извлекаем ответ
        if result.get("error"):
            return {
                "status": "error",
                "message": f"❌ Ошибка: {result['error']}",
                "data": None
            }
        
        # Возвращаем последнее сообщение
        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, 'content'):
                # Проверяем, есть ли giga_attachments в последнем сообщении
                response_data = {
                    "user_request": user_request,
                    "user_id": user_id,
                    "timestamp": datetime.now().isoformat()
                }
                
                # Проверяем, есть ли chart_attachments в result
                chart_attachments = result.get("chart_attachments", {})
                giga_attachments = []
                
                if chart_attachments:
                    # Преобразуем chart_attachments в giga_attachments
                    for file_id, attachment_data in chart_attachments.items():
                        giga_attachments.append(attachment_data)
                
                # Также проверяем giga_attachments в сообщениях (для прямых вызовов инструментов)
                for message in messages:
                    # Проверяем additional_kwargs
                    if hasattr(message, 'additional_kwargs') and message.additional_kwargs:
                        if 'giga_attachments' in message.additional_kwargs:
                            giga_attachments.extend(message.additional_kwargs['giga_attachments'])
                    
                    # Проверяем, есть ли giga_attachments в content (если это ToolMessage)
                    if hasattr(message, 'content') and isinstance(message.content, str):
                        # Ищем giga_attachments в строковом представлении
                        if 'giga_attachments' in message.content:
                            try:
                                import ast
                                # Пытаемся извлечь giga_attachments из строки
                                content_dict = ast.literal_eval(message.content)
                                if isinstance(content_dict, dict) and 'giga_attachments' in content_dict:
                                    giga_attachments.extend(content_dict['giga_attachments'])
                            except:
                                pass
                    
                    # Проверяем, есть ли giga_attachments в самом объекте сообщения
                    if hasattr(message, 'giga_attachments'):
                        giga_attachments.extend(message.giga_attachments)
                    
                    # Проверяем, есть ли giga_attachments в дополнительных атрибутах
                    if hasattr(message, '__dict__'):
                        for attr_name, attr_value in message.__dict__.items():
                            if attr_name == 'giga_attachments' and isinstance(attr_value, list):
                                giga_attachments.extend(attr_value)
                
                logger.info(f"🔧 TINKOFF_AGENT: chart_attachments: {len(chart_attachments)}, giga_attachments: {len(giga_attachments)}")
                
                # Формируем понятное сообщение для главного агента
                # Если есть giga_attachments (графики), сообщаем об успешном создании
                if giga_attachments:
                    # Проверяем, есть ли информация о тикере в сообщениях или данных
                    ticker_info = ""
                    for message in messages:
                        if hasattr(message, 'content') and isinstance(message.content, str):
                            # Пытаемся найти тикер в сообщении
                            ticker_match = re.search(r'(?:тикер|ticker|график для|для)\s+([A-Z]+)', message.content, re.IGNORECASE)
                            if ticker_match:
                                ticker_info = f" для {ticker_match.group(1)}"
                                break
                    
                    message_text = f"График{ticker_info} успешно создан и готов к отображению"
                else:
                    # Используем содержимое последнего сообщения, если нет attachments
                    message_text = last_message.content if hasattr(last_message, 'content') else "Запрос обработан успешно"
                
                result_dict = {
                    "status": "success",
                    "message": message_text,
                    "data": response_data
                }
                
                # Добавляем giga_attachments на верхний уровень для обработки tool_graph.py
                if giga_attachments:
                    result_dict["giga_attachments"] = giga_attachments
                
                return result_dict
        
        # Если нет сообщений, возвращаем общий ответ
        return {
            "status": "success",
            "message": "✅ Запрос обработан успешно",
            "data": {
                "user_request": user_request,
                "user_id": user_id,
                "timestamp": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Ошибка в tinkoff_agent: {e}")
        return {
            "status": "error",
            "message": f"❌ Ошибка агента: {str(e)}",
            "data": None
        }

# Создаем граф для экспорта
graph = create_tinkoff_agent()