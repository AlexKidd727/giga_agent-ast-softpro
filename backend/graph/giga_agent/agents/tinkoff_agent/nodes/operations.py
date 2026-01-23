"""
Узлы для работы с операциями в Tinkoff
"""

import logging
from typing import Annotated, Dict, Any, List
from datetime import datetime, timedelta

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.tinkoff_client import get_tinkoff_client

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

async def format_operations(operations: List[Dict[str, Any]], max_operations: int = 50) -> str:
    """
    Форматирование списка операций с ограничением количества и информацией об инструментах
    
    Args:
        operations: Список операций
        max_operations: Максимальное количество операций для отображения
    """
    if not operations:
        return "Операции не найдены"
    
    # Ограничиваем количество операций для предотвращения превышения лимита контекста
    limited_operations = operations[:max_operations]
    
    result = []
    for i, op in enumerate(limited_operations, 1):
        op_info = f"**{i}. Операция #{op.get('id', 'N/A')}**\n"
        op_info += f"   Тип: {op.get('operation_type', 'N/A')}\n"
        
        # Получаем информацию об инструменте по FIGI
        figi = op.get('figi', 'N/A')
        if figi and figi != 'N/A':
            try:
                from ..utils.tinkoff_client import get_tinkoff_client
                client = get_tinkoff_client()
                instrument_info = await client.get_instrument_by_figi(figi)
                if instrument_info:
                    ticker = instrument_info.get('ticker', 'N/A')
                    name = instrument_info.get('name', 'N/A')
                    op_info += f"   📊 {ticker} - {name}\n"
                else:
                    op_info += f"   FIGI: {figi}\n"
            except Exception as e:
                logger.warning(f"Не удалось получить информацию об инструменте {figi}: {e}")
                op_info += f"   FIGI: {figi}\n"
        else:
            op_info += f"   FIGI: {figi}\n"
        
        op_info += f"   Количество: {op.get('quantity', 'N/A')}\n"
        op_info += f"   Цена: {format_money(op.get('price', 0))}\n"
        op_info += f"   Сумма: {format_money(op.get('payment', 0))}\n"
        op_info += f"   Валюта: {op.get('currency', 'RUB')}\n"
        op_info += f"   Статус: {op.get('state', 'N/A')}\n"
        op_info += f"   Дата: {op.get('date', 'N/A')}\n"
        
        if op.get('trades'):
            op_info += f"   Сделки: {len(op['trades'])}\n"
        
        result.append(op_info)
    
    # Добавляем информацию о том, что показаны не все операции
    if len(operations) > max_operations:
        result.append(f"\n**Показано {max_operations} из {len(operations)} операций. Для просмотра всех операций уточните период.**")
    
    return "\n".join(result)

@tool
async def get_operations(from_date: str = None, to_date: str = None) -> str:
    """
    Получение операций за период
    
    Args:
        from_date: Дата начала (YYYY-MM-DD), по умолчанию - 30 дней назад
        to_date: Дата окончания (YYYY-MM-DD), по умолчанию - сегодня
    
    Returns:
        Строка со списком операций
    """
    try:
        client = get_tinkoff_client()
        
        # Устанавливаем даты по умолчанию
        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d")
        
        if not from_date:
            from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        # Логируем запрашиваемые даты для отладки
        logger.info(f"Запрос операций с {from_date} по {to_date}")
        
        operations = client.get_operations(from_date, to_date)
        
        if not operations:
            return f"📊 **ОПЕРАЦИИ за период {from_date} - {to_date}:** Операции не найдены"
        
        result = f"📊 **ОПЕРАЦИИ за период {from_date} - {to_date} ({len(operations)}):**\n\n"
        result += await format_operations(operations, max_operations=50)
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении операций: {e}")
        return f"❌ Ошибка при получении операций: {str(e)}"

@tool
async def get_operations_today() -> str:
    """
    Получение операций за сегодня
    
    Returns:
        Строка со списком операций за сегодня
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        return await get_operations(from_date=today, to_date=today)
        
    except Exception as e:
        logger.error(f"Ошибка при получении операций за сегодня: {e}")
        return f"❌ Ошибка при получении операций за сегодня: {str(e)}"

@tool
async def get_operations_week() -> str:
    """
    Получение операций за последнюю неделю
    
    Returns:
        Строка со списком операций за неделю
    """
    try:
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        return await get_operations(from_date=from_date, to_date=to_date)
        
    except Exception as e:
        logger.error(f"Ошибка при получении операций за неделю: {e}")
        return f"❌ Ошибка при получении операций за неделю: {str(e)}"

@tool
async def get_operations_month() -> str:
    """
    Получение операций за последний месяц
    
    Returns:
        Строка со списком операций за месяц
    """
    try:
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        return await get_operations(from_date=from_date, to_date=to_date)
        
    except Exception as e:
        logger.error(f"Ошибка при получении операций за месяц: {e}")
        return f"❌ Ошибка при получении операций за месяц: {str(e)}"

@tool
async def get_operations_by_type(operation_type: str, from_date: str = None, to_date: str = None) -> str:
    """
    Получение операций определенного типа за период
    
    Args:
        operation_type: Тип операции (например, "Buy", "Sell", "BrokerCommission")
        from_date: Дата начала (YYYY-MM-DD), по умолчанию - 30 дней назад
        to_date: Дата окончания (YYYY-MM-DD), по умолчанию - сегодня
    
    Returns:
        Строка со списком операций определенного типа
    """
    try:
        client = get_tinkoff_client()
        
        # Устанавливаем даты по умолчанию
        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d")
        
        if not from_date:
            from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        operations = client.get_operations(from_date, to_date)
        
        # Фильтруем по типу операции
        filtered_operations = [
            op for op in operations 
            if op.get('operation_type', '').lower() == operation_type.lower()
        ]
        
        if not filtered_operations:
            return f"📊 **ОПЕРАЦИИ типа '{operation_type}' за период {from_date} - {to_date}:** Операции не найдены"
        
        result = f"📊 **ОПЕРАЦИИ типа '{operation_type}' за период {from_date} - {to_date} ({len(filtered_operations)}):**\n\n"
        result += await format_operations(filtered_operations, max_operations=50)
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении операций по типу: {e}")
        return f"❌ Ошибка при получении операций по типу: {str(e)}"

@tool
def get_operations_summary(from_date: str = None, to_date: str = None) -> str:
    """
    Получение сводки по операциям за период
    
    Args:
        from_date: Дата начала (YYYY-MM-DD), по умолчанию - 30 дней назад
        to_date: Дата окончания (YYYY-MM-DD), по умолчанию - сегодня
    
    Returns:
        Строка со сводкой по операциям
    """
    try:
        client = get_tinkoff_client()
        
        # Устанавливаем даты по умолчанию
        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d")
        
        if not from_date:
            from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        operations = client.get_operations(from_date, to_date)
        
        if not operations:
            return f"📊 **СВОДКА ПО ОПЕРАЦИЯМ за период {from_date} - {to_date}:** Операции не найдены"
        
        # Подсчитываем статистику
        total_operations = len(operations)
        operation_types = {}
        total_amount = 0
        
        for op in operations:
            op_type = op.get('operation_type', 'Unknown')
            operation_types[op_type] = operation_types.get(op_type, 0) + 1
            
            payment = op.get('payment', 0)
            if payment:
                total_amount += float(format_money(payment))
        
        result = f"📊 **СВОДКА ПО ОПЕРАЦИЯМ за период {from_date} - {to_date}:**\n\n"
        result += f"**Общее количество операций:** {total_operations}\n"
        result += f"**Общая сумма:** {total_amount:.2f} RUB\n\n"
        
        result += "**По типам операций:**\n"
        for op_type, count in sorted(operation_types.items()):
            result += f"   {op_type}: {count}\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении сводки по операциям: {e}")
        return f"❌ Ошибка при получении сводки по операциям: {str(e)}"
