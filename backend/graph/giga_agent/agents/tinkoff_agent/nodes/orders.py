"""
Узлы для работы с ордерами в Tinkoff
"""

import logging
from typing import Annotated, Dict, Any, List
from decimal import Decimal

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.tinkoff_client import get_tinkoff_client

# Импорты для Tinkoff API
try:
    from tinkoff.invest.schemas import OrderDirection, OrderType
    TINKOFF_SCHEMAS_AVAILABLE = True
except ImportError:
    try:
        from tinkoff_invest.models.order import OperationType as OrderDirection, OrderType
        TINKOFF_SCHEMAS_AVAILABLE = True
    except ImportError:
        TINKOFF_SCHEMAS_AVAILABLE = False
        OrderDirection = None
        OrderType = None

logger = logging.getLogger(__name__)

def format_money(money_value) -> str:
    """Форматирование денежной суммы"""
    if money_value is None:
        return "0.00"
    
    # Если это объект с units и nano
    if hasattr(money_value, 'units') and hasattr(money_value, 'nano'):
        return f"{money_value.units}.{money_value.nano:09d}".rstrip('0').rstrip('.')
    
    # Если это число
    return f"{float(money_value):.2f}"

def validate_quantity(quantity: int, lot: int) -> int:
    """Проверка и корректировка количества с учетом лотности"""
    if quantity <= 0:
        raise ValueError("Количество должно быть положительным")
    
    # Округляем до ближайшего лота
    adjusted_quantity = (quantity // lot) * lot
    if adjusted_quantity == 0:
        adjusted_quantity = lot
    
    return adjusted_quantity

def validate_price(price: float) -> float:
    """Проверка цены"""
    if price <= 0:
        raise ValueError("Цена должна быть положительной")
    
    return float(price)

@tool
async def place_market_order(figi: str, quantity: int, direction: str) -> str:
    """
    Размещение рыночного ордера
    
    Args:
        figi: FIGI инструмента
        quantity: Количество (будет скорректировано с учетом лотности)
        direction: Направление (buy/sell, покупка/продажа)
    
    Returns:
        Строка с результатом размещения ордера
    """
    try:
        client = get_tinkoff_client()
        
        # Получаем информацию об инструменте для проверки лотности
        instrument = await client.get_instrument_by_figi(figi)
        if not instrument:
            return f"❌ Инструмент с FIGI '{figi}' не найден"
        
        lot = instrument.get('lot', 1)
        ticker = instrument.get('ticker', 'N/A')
        name = instrument.get('name', 'N/A')
        
        # Корректируем количество с учетом лотности
        adjusted_quantity = validate_quantity(quantity, lot)
        
        if adjusted_quantity != quantity:
            logger.info(f"Количество скорректировано с {quantity} до {adjusted_quantity} (лот: {lot})")
        
        # Размещаем ордер
        order = await client.place_market_order(figi, adjusted_quantity, direction)
        
        result = f"✅ **РЫНОЧНЫЙ ОРДЕР РАЗМЕЩЕН:**\n\n"
        result += f"**Инструмент:** {ticker} ({name})\n"
        result += f"**FIGI:** {figi}\n"
        result += f"**Направление:** {direction}\n"
        result += f"**Количество:** {adjusted_quantity} (лот: {lot})\n"
        result += f"**ID ордера:** {order['order_id']}\n"
        result += f"**Статус:** {order['execution_report_status']}\n"
        
        if order.get('executed_order_price'):
            result += f"**Цена исполнения:** {format_money(order['executed_order_price'])}\n"
        
        if order.get('total_order_amount'):
            result += f"**Сумма:** {format_money(order['total_order_amount'])}\n"
        
        if order.get('executed_commission'):
            result += f"**Комиссия:** {format_money(order['executed_commission'])}\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при размещении рыночного ордера: {e}")
        return f"❌ Ошибка при размещении рыночного ордера: {str(e)}"

@tool
async def place_limit_order(figi: str, quantity: int, price: float, direction: str) -> str:
    """
    Размещение лимитного ордера
    
    Args:
        figi: FIGI инструмента
        quantity: Количество (будет скорректировано с учетом лотности)
        price: Цена
        direction: Направление (buy/sell, покупка/продажа)
    
    Returns:
        Строка с результатом размещения ордера
    """
    try:
        client = get_tinkoff_client()
        
        # Получаем информацию об инструменте для проверки лотности
        instrument = await client.get_instrument_by_figi(figi)
        if not instrument:
            return f"❌ Инструмент с FIGI '{figi}' не найден"
        
        lot = instrument.get('lot', 1)
        ticker = instrument.get('ticker', 'N/A')
        name = instrument.get('name', 'N/A')
        currency = instrument.get('currency', 'RUB')
        
        # Корректируем количество с учетом лотности
        adjusted_quantity = validate_quantity(quantity, lot)
        
        # Проверяем цену
        validated_price = validate_price(price)
        
        if adjusted_quantity != quantity:
            logger.info(f"Количество скорректировано с {quantity} до {adjusted_quantity} (лот: {lot})")
        
        # Размещаем ордер
        order = await client.place_limit_order(figi, adjusted_quantity, validated_price, direction)
        
        result = f"✅ **ЛИМИТНЫЙ ОРДЕР РАЗМЕЩЕН:**\n\n"
        result += f"**Инструмент:** {ticker} ({name})\n"
        result += f"**FIGI:** {figi}\n"
        result += f"**Направление:** {direction}\n"
        result += f"**Количество:** {adjusted_quantity} (лот: {lot})\n"
        result += f"**Цена:** {validated_price} {currency}\n"
        result += f"**ID ордера:** {order['order_id']}\n"
        result += f"**Статус:** {order['execution_report_status']}\n"
        
        if order.get('executed_order_price'):
            result += f"**Цена исполнения:** {format_money(order['executed_order_price'])}\n"
        
        if order.get('total_order_amount'):
            result += f"**Сумма:** {format_money(order['total_order_amount'])}\n"
        
        if order.get('executed_commission'):
            result += f"**Комиссия:** {format_money(order['executed_commission'])}\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при размещении лимитного ордера: {e}")
        return f"❌ Ошибка при размещении лимитного ордера: {str(e)}"

@tool
async def get_orders() -> str:
    """
    Получение списка активных ордеров
    
    Returns:
        Строка со списком активных ордеров
    """
    try:
        client = get_tinkoff_client()
        orders = await client.get_orders()
        
        if not orders:
            return "📋 **АКТИВНЫЕ ОРДЕРА:** Ордера не найдены"
        
        result = f"📋 **АКТИВНЫЕ ОРДЕРА ({len(orders)}):**\n\n"
        
        for i, order in enumerate(orders, 1):
            result += f"**{i}. Ордер #{order['order_id']}**\n"
            result += f"   FIGI: {order['figi']}\n"
            result += f"   Направление: {order['direction']}\n"
            result += f"   Тип: {order['order_type']}\n"
            result += f"   Количество: {order['lots_requested']} (исполнено: {order['lots_executed']})\n"
            
            if order.get('initial_order_price'):
                result += f"   Цена: {format_money(order['initial_order_price'])}\n"
            
            if order.get('executed_order_price'):
                result += f"   Цена исполнения: {format_money(order['executed_order_price'])}\n"
            
            result += f"   Статус: {order['execution_report_status']}\n"
            result += f"   Дата: {order['order_date']}\n"
            result += "\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении ордеров: {e}")
        return f"❌ Ошибка при получении ордеров: {str(e)}"

@tool
async def cancel_order(order_id: str) -> str:
    """
    Отмена ордера
    
    Args:
        order_id: ID ордера для отмены
    
    Returns:
        Строка с результатом отмены ордера
    """
    try:
        client = get_tinkoff_client()
        result = await client.cancel_order(order_id)
        
        response = f"✅ **ОРДЕР ОТМЕНЕН:**\n\n"
        response += f"**ID ордера:** {order_id}\n"
        response += f"**Статус:** {result['execution_report_status']}\n"
        response += f"**Время:** {result['time']}\n"
        
        return response
        
    except Exception as e:
        logger.error(f"Ошибка при отмене ордера {order_id}: {e}")
        return f"❌ Ошибка при отмене ордера: {str(e)}"

@tool
async def buy_market(figi: str, quantity: int) -> str:
    """
    Покупка по рыночной цене
    
    Args:
        figi: FIGI инструмента
        quantity: Количество
    
    Returns:
        Строка с результатом покупки
    """
    return await place_market_order.ainvoke({"figi": figi, "quantity": quantity, "direction": "buy"})

@tool
async def sell_market(figi: str, quantity: int) -> str:
    """
    Продажа по рыночной цене
    
    Args:
        figi: FIGI инструмента
        quantity: Количество
    
    Returns:
        Строка с результатом продажи
    """
    return await place_market_order.ainvoke({"figi": figi, "quantity": quantity, "direction": "sell"})

@tool
async def buy_limit(figi: str, quantity: int, price: float) -> str:
    """
    Покупка по лимитной цене
    
    Args:
        figi: FIGI инструмента
        quantity: Количество
        price: Цена
    
    Returns:
        Строка с результатом покупки
    """
    return await place_limit_order(figi, quantity, price, "buy")

@tool
async def sell_limit(figi: str, quantity: int, price: float) -> str:
    """
    Продажа по лимитной цене
    
    Args:
        figi: FIGI инструмента
        quantity: Количество
        price: Цена
    
    Returns:
        Строка с результатом продажи
    """
    return await place_limit_order(figi, quantity, price, "sell")