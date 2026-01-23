"""
Вспомогательные функции для Tinkoff агента
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from ..config import MAX_ORDER_AMOUNT, MIN_ORDER_AMOUNT, POPULAR_STOCKS

logger = logging.getLogger(__name__)

def find_stock_by_ticker(ticker: str) -> dict:
    """
    Поиск инструмента по тикеру сначала в справочнике, затем через API
    
    Args:
        ticker: Тикер инструмента (например, SBER, IRKT)
        
    Returns:
        dict: Информация об инструменте {"name": str, "figi": str} или None
    """
    ticker_upper = ticker.upper()
    
    # Сначала ищем в локальном справочнике
    if ticker_upper in POPULAR_STOCKS:
        return POPULAR_STOCKS[ticker_upper]
    
    # Если не найдено в справочнике, ищем через API
    try:
        from ..utils.client import get_tinkoff_client
        
        client = get_tinkoff_client()
        if not client:
            logger.warning("Tinkoff клиент недоступен для поиска")
            return None
            
        with client.get_sync_client() as api_client:
            # Ищем среди акций
            try:
                shares_response = api_client.instruments.shares()
                
                for share in shares_response.instruments:
                    if share.ticker.upper() == ticker_upper:
                        return {
                            "name": share.name,
                            "figi": share.figi,
                            "ticker": share.ticker
                        }
            except Exception as e:
                logger.warning(f"Ошибка поиска акций через API: {e}")
                
            # Если не найдено среди акций, ищем среди ETF
            try:
                etfs_response = api_client.instruments.etfs()
                
                for etf in etfs_response.instruments:
                    if etf.ticker.upper() == ticker_upper:
                        return {
                            "name": etf.name,
                            "figi": etf.figi,
                            "ticker": etf.ticker
                        }
            except Exception as e:
                logger.warning(f"Ошибка поиска ETF через API: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка поиска инструмента {ticker} через API: {e}")
    
    return None

def money_value_to_float(money_value: Any) -> float:
    """Конвертация MoneyValue в float"""
    try:
        if hasattr(money_value, 'units') and hasattr(money_value, 'nano'):
            return float(money_value.units + money_value.nano / 1_000_000_000)
        elif isinstance(money_value, dict):
            units = money_value.get('units', 0)
            nano = money_value.get('nano', 0)
            return float(units + nano / 1_000_000_000)
        else:
            return float(money_value)
    except (ValueError, TypeError):
        logger.warning(f"Не удалось конвертировать {money_value} в float")
        return 0.0

def quotation_to_float(quotation: Any) -> float:
    """Конвертация Quotation в float"""
    try:
        if hasattr(quotation, 'units') and hasattr(quotation, 'nano'):
            return float(quotation.units + quotation.nano / 1_000_000_000)
        elif isinstance(quotation, dict):
            units = quotation.get('units', 0)
            nano = quotation.get('nano', 0)
            return float(units + nano / 1_000_000_000)
        else:
            return float(quotation)
    except (ValueError, TypeError):
        logger.warning(f"Не удалось конвертировать {quotation} в float")
        return 0.0

def format_money(amount: float, currency: str = "RUB") -> str:
    """Форматирование денежной суммы"""
    if currency == "RUB":
        symbol = "₽"
    elif currency == "USD":
        symbol = "$"
    elif currency == "EUR":
        symbol = "€"
    else:
        symbol = currency
    
    # Форматируем с разделителями тысяч
    if abs(amount) >= 1000000:
        # Миллионы
        return f"{amount / 1000000:.2f}M {symbol}"
    elif abs(amount) >= 1000:
        # Тысячи
        return f"{amount / 1000:.1f}k {symbol}"
    else:
        return f"{amount:.2f} {symbol}"

def validate_order_amount(amount: float) -> Tuple[bool, str]:
    """Валидация суммы ордера"""
    try:
        amount_decimal = Decimal(str(amount))
        
        if amount_decimal <= 0:
            return False, "Сумма ордера должна быть положительной"
        
        if amount_decimal < MIN_ORDER_AMOUNT:
            return False, f"Сумма ордера {format_money(amount)} меньше минимальной {format_money(float(MIN_ORDER_AMOUNT))}"
        
        if amount_decimal > MAX_ORDER_AMOUNT:
            return False, f"Сумма ордера {format_money(amount)} больше максимальной {format_money(float(MAX_ORDER_AMOUNT))}"
        
        return True, "OK"
    except (ValueError, TypeError):
        return False, "Некорректный формат суммы"

def validate_quantity(quantity: int) -> Tuple[bool, str]:
    """Валидация количества акций"""
    if not isinstance(quantity, int) or quantity <= 0:
        return False, "Количество должно быть положительным целым числом"
    
    if quantity > 10000:
        return False, "Слишком большое количество акций (максимум 10,000)"
    
    return True, "OK"

def find_stock_by_ticker(ticker: str) -> Optional[Dict[str, str]]:
    """Поиск акции по тикеру через API (универсальный поиск)"""
    ticker_upper = ticker.upper()
    
    # Всегда используем API для поиска, не полагаемся на локальный справочник
    try:
        from ..utils.client import get_tinkoff_client
        
        client = get_tinkoff_client()
        if not client:
            logger.warning("Tinkoff клиент недоступен для поиска через API")
            return None
        
        # Используем универсальный поиск через search_instruments
        instruments = client.search_instruments(ticker_upper, "shares")
        if instruments:
            instrument = instruments[0]  # Берем первый найденный
            logger.info(f"Найден инструмент {ticker_upper} через API: {instrument['name']}")
            return {
                "ticker": instrument['ticker'],
                "name": instrument['name'],
                "figi": instrument['figi']
            }
        
        # Если не найдено среди акций, пробуем другие типы
        for instrument_type in ["bonds", "etfs", "currencies"]:
            try:
                instruments = client.search_instruments(ticker_upper, instrument_type)
                if instruments:
                    instrument = instruments[0]
                    logger.info(f"Найден инструмент {ticker_upper} типа {instrument_type} через API: {instrument['name']}")
                    return {
                        "ticker": instrument['ticker'],
                        "name": instrument['name'],
                        "figi": instrument['figi']
                    }
            except Exception as e:
                logger.warning(f"Ошибка поиска {instrument_type} через API: {e}")
                continue
                
    except Exception as e:
        logger.warning(f"Ошибка поиска через API для тикера {ticker}: {e}")
    
    return None

def format_portfolio_positions(positions: List[Any]) -> str:
    """Форматирование позиций портфеля для отображения"""
    if not positions:
        return "📈 **Портфель пуст**\n\nНет открытых позиций"
    
    result = "📈 **Портфель:**\n\n"
    total_value = 0.0
    
    for pos in positions:
        try:
            # Получаем данные позиции
            figi = getattr(pos, 'figi', 'Unknown')
            quantity = quotation_to_float(getattr(pos, 'quantity', 0))
            
            # Пропускаем валютные позиции с нулевым количеством
            if quantity == 0:
                continue
            
            # Ищем инструмент в справочнике
            instrument_name = "Unknown"
            ticker = "Unknown"
            
            # Сначала ищем в справочнике акций
            for stock_ticker, stock_info in POPULAR_STOCKS.items():
                if stock_info["figi"] == figi:
                    instrument_name = stock_info["name"]
                    ticker = stock_ticker
                    break
            else:
                # Ищем в справочнике валют
                from ..config import POPULAR_CURRENCIES
                for currency_ticker, currency_info in POPULAR_CURRENCIES.items():
                    if currency_info["figi"] == figi:
                        instrument_name = currency_info["name"]
                        ticker = currency_ticker
                        break
                else:
                    # Если не найдено в справочниках, запрашиваем через API
                    try:
                        from ..nodes.instruments import get_instrument_by_figi
                        instrument_info = get_instrument_by_figi(figi)
                        if instrument_info:
                            instrument_name = instrument_info["name"]
                            ticker = instrument_info["ticker"]
                    except Exception as e:
                        logger.warning(f"Не удалось получить инструмент по FIGI {figi}: {e}")
            
            # Рыночная стоимость
            current_price = quotation_to_float(getattr(pos, 'current_price', 0))
            market_value = quantity * current_price
            total_value += market_value
            
            # Средняя цена покупки
            average_price = quotation_to_float(getattr(pos, 'average_position_price', 0))
            
            # P&L
            pnl = market_value - (quantity * average_price) if average_price > 0 else 0
            pnl_percent = (pnl / (quantity * average_price) * 100) if average_price > 0 else 0
            
            # Форматируем строку позиции
            pnl_emoji = "📈" if pnl >= 0 else "📉"
            pnl_color = "🟢" if pnl >= 0 else "🔴"
            
            result += f"**{ticker}** ({instrument_name})\n"
            result += f"  📊 Количество: {quantity:.0f} шт.\n"
            result += f"  💰 Цена: {format_money(current_price)}\n"
            result += f"  💎 Стоимость: {format_money(market_value)}\n"
            result += f"  {pnl_emoji} P&L: {pnl_color} {format_money(pnl)} ({pnl_percent:+.2f}%)\n\n"
            
        except Exception as e:
            logger.warning(f"Ошибка обработки позиции: {e}")
            continue
    
    result += f"💼 **Общая стоимость портфеля:** {format_money(total_value)}"
    
    return result

def format_order_info(order: Any) -> str:
    """Форматирование информации об ордере"""
    try:
        order_id = getattr(order, 'order_id', 'Unknown')
        figi = getattr(order, 'figi', 'Unknown')
        direction = getattr(order, 'direction', 'Unknown')
        order_type = getattr(order, 'order_type', 'Unknown')
        lots_requested = getattr(order, 'lots_requested', 0)
        lots_executed = getattr(order, 'lots_executed', 0)
        
        # Цена
        initial_order_price = quotation_to_float(getattr(order, 'initial_order_price', 0))
        executed_order_price = quotation_to_float(getattr(order, 'executed_order_price', 0))
        
        # Статус
        execution_report_status = getattr(order, 'execution_report_status', 'Unknown')
        
        # Находим название инструмента
        instrument_name = "Unknown"
        ticker = "Unknown"
        
        # Ищем в справочнике акций
        for stock_ticker, stock_info in POPULAR_STOCKS.items():
            if stock_info["figi"] == figi:
                instrument_name = stock_info["name"]
                ticker = stock_ticker
                break
        else:
            # Ищем в справочнике валют
            from ..config import POPULAR_CURRENCIES
            for currency_ticker, currency_info in POPULAR_CURRENCIES.items():
                if currency_info["figi"] == figi:
                    instrument_name = currency_info["name"]
                    ticker = currency_ticker
                    break
        
        # Определяем эмодзи для направления
        direction_emoji = "🟢" if direction == OrderDirection.ORDER_DIRECTION_BUY else "🔴"
        direction_text = "Покупка" if direction == OrderDirection.ORDER_DIRECTION_BUY else "Продажа"
        
        # Статус ордера
        status_emoji = {
            "EXECUTION_REPORT_STATUS_FILL": "✅",
            "EXECUTION_REPORT_STATUS_NEW": "🔵", 
            "EXECUTION_REPORT_STATUS_CANCELLED": "❌",
            "EXECUTION_REPORT_STATUS_REJECTED": "🚫"
        }.get(str(execution_report_status), "❓")
        
        result = f"{direction_emoji} **{direction_text} {ticker}** {status_emoji}\n"
        result += f"  🆔 ID: `{order_id}`\n"
        result += f"  📊 Лоты: {lots_executed}/{lots_requested}\n"
        result += f"  💰 Цена: {format_money(initial_order_price)}\n"
        
        if executed_order_price > 0 and executed_order_price != initial_order_price:
            result += f"  ✅ Исполнено по: {format_money(executed_order_price)}\n"
        
        return result
        
    except Exception as e:
        logger.warning(f"Ошибка форматирования ордера: {e}")
        return f"Ордер {getattr(order, 'order_id', 'Unknown')}"

def calculate_lot_size(price: float, amount: float) -> int:
    """Расчет количества лотов по сумме"""
    if price <= 0:
        return 0
    
    lots = int(amount / price)
    return max(1, lots)  # Минимум 1 лот

def format_instrument_info(instrument: Any) -> str:
    """Форматирование информации об инструменте"""
    try:
        ticker = getattr(instrument, 'ticker', 'Unknown')
        name = getattr(instrument, 'name', 'Unknown')
        figi = getattr(instrument, 'figi', 'Unknown')
        currency = getattr(instrument, 'currency', 'Unknown')
        lot = getattr(instrument, 'lot', 1)
        
        # Минимальный шаг цены
        min_price_increment = quotation_to_float(getattr(instrument, 'min_price_increment', 0))
        
        result = f"📈 **{ticker}** - {name}\n"
        result += f"  🆔 FIGI: `{figi}`\n"
        result += f"  💱 Валюта: {currency}\n"
        result += f"  📦 Лот: {lot} шт.\n"
        result += f"  📏 Шаг цены: {min_price_increment}\n"
        
        return result
        
    except Exception as e:
        logger.warning(f"Ошибка форматирования инструмента: {e}")
        return "Ошибка получения информации об инструменте"
