"""
Узлы для работы с инструментами в Tinkoff
"""

import logging
from typing import Annotated, Dict, Any, List

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.tinkoff_client import get_tinkoff_client

logger = logging.getLogger(__name__)

@tool
async def search_instrument(ticker: str, instrument_type: str = "shares") -> str:
    """
    Поиск инструмента по тикеру (универсальный поиск через API)
    
    Args:
        ticker: Тикер инструмента (например, "SBER", "GAZP", "MTLR")
        instrument_type: Тип инструмента (shares, bonds, etfs)
    
    Returns:
        Строка с информацией о найденных инструментах
    """
    try:
        client = get_tinkoff_client()
        if not client:
            return f"❌ Tinkoff клиент недоступен"
        
        # Всегда используем API для поиска
        instruments = client.search_instruments(ticker, instrument_type)
        
        if not instruments:
            # Если не найдено в основном типе, пробуем другие типы
            alternative_types = ["shares", "bonds", "etfs", "currencies"]
            for alt_type in alternative_types:
                if alt_type != instrument_type:
                    try:
                        alt_instruments = client.search_instruments(ticker, alt_type)
                        if alt_instruments:
                            instruments = alt_instruments
                            break
                    except Exception:
                        continue
            
            if not instruments:
                return f"❌ Инструменты с тикером '{ticker}' не найдены ни в одном типе"
        
        result = f"🔍 **НАЙДЕННЫЕ ИНСТРУМЕНТЫ для '{ticker}':**\n\n"
        
        for i, instrument in enumerate(instruments, 1):
            result += f"**{i}. {instrument['ticker']}**\n"
            result += f"   Название: {instrument['name']}\n"
            result += f"   FIGI: {instrument['figi']}\n"
            result += f"   Валюта: {instrument.get('currency', 'N/A')}\n"
            result += f"   Лот: {instrument.get('lot', 'N/A')}\n"
            result += f"   Тип: {instrument['instrument_type']}\n"
            result += f"   Минимальный шаг цены: {instrument.get('min_price_increment', 'N/A')}\n"
            result += "\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при поиске инструмента {ticker}: {e}")
        return f"❌ Ошибка при поиске инструмента: {str(e)}"

@tool
async def get_instrument_info(figi: str) -> str:
    """
    Получение подробной информации об инструменте по FIGI
    
    Args:
        figi: FIGI инструмента
    
    Returns:
        Строка с подробной информацией об инструменте
    """
    try:
        client = get_tinkoff_client()
        instrument = await client.get_instrument_by_figi(figi)
        
        if not instrument:
            return f"❌ Инструмент с FIGI '{figi}' не найден"
        
        result = f"📊 **ИНФОРМАЦИЯ ОБ ИНСТРУМЕНТЕ:**\n\n"
        result += f"**Тикер:** {instrument['ticker']}\n"
        result += f"**Название:** {instrument['name']}\n"
        result += f"**FIGI:** {instrument['figi']}\n"
        result += f"**Валюта:** {instrument['currency']}\n"
        result += f"**Лот:** {instrument['lot']}\n"
        result += f"**Тип:** {instrument['instrument_type']}\n"
        result += f"**Минимальный шаг цены:** {instrument['min_price_increment']}\n"
        
        # Получаем текущую цену
        try:
            price_info = await client.get_current_price(figi)
            if price_info:
                result += f"\n💰 **ТЕКУЩАЯ ЦЕНА:**\n"
                result += f"   Цена: {price_info['price']} {instrument['currency']}\n"
                result += f"   Время: {price_info['time']}\n"
        except Exception as e:
            logger.warning(f"Не удалось получить цену для {figi}: {e}")
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении информации об инструменте {figi}: {e}")
        return f"❌ Ошибка при получении информации об инструменте: {str(e)}"

@tool
async def get_current_price(figi: str) -> str:
    """
    Получение текущей цены инструмента
    
    Args:
        figi: FIGI инструмента
    
    Returns:
        Строка с текущей ценой
    """
    try:
        client = get_tinkoff_client()
        price_info = await client.get_current_price(figi)
        
        if not price_info:
            return f"❌ Не удалось получить цену для FIGI '{figi}'"
        
        # Получаем информацию об инструменте для валюты
        try:
            instrument = await client.get_instrument_by_figi(figi)
            currency = instrument['currency'] if instrument else 'RUB'
        except:
            currency = 'RUB'
        
        result = f"💰 **ТЕКУЩАЯ ЦЕНА:**\n\n"
        result += f"**FIGI:** {figi}\n"
        result += f"**Цена:** {price_info['price']} {currency}\n"
        result += f"**Время:** {price_info['time']}\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении цены для {figi}: {e}")
        return f"❌ Ошибка при получении цены: {str(e)}"

@tool
async def find_figi_by_ticker(ticker: str, instrument_type: str = "shares") -> str:
    """
    Поиск FIGI по тикеру (сначала проверяем портфель, потом API)
    
    Args:
        ticker: Тикер инструмента
        instrument_type: Тип инструмента (shares, bonds, etfs)
    
    Returns:
        Строка с FIGI найденных инструментов
    """
    try:
        client = get_tinkoff_client()
        if not client:
            return f"❌ Tinkoff клиент недоступен"
        
        # Сначала проверяем портфель - если инструмент уже есть в портфеле, берем FIGI оттуда
        try:
            from ..nodes.portfolio import get_positions
            positions_result = await get_positions.ainvoke({"user_id": "default_user"})
            
            if "MTLR" in str(positions_result) or ticker.upper() in str(positions_result):
                # Ищем FIGI в результатах портфеля
                import re
                figi_pattern = rf'{ticker.upper()}\s*\([^)]+\)\s*\n\s*FIGI:\s*([A-Z0-9]+)'
                figi_match = re.search(figi_pattern, str(positions_result))
                
                if figi_match:
                    figi = figi_match.group(1)
                    result = f"🔍 **FIGI для тикера '{ticker}' (найден в портфеле):**\n\n"
                    result += f"**1. {ticker.upper()}**\n"
                    result += f"   FIGI: `{figi}`\n"
                    result += f"   Название: Найден в портфеле\n"
                    result += f"   Тип: shares\n"
                    result += f"   Источник: портфель\n"
                    result += "\n"
                    return result
        except Exception as e:
            logger.warning(f"Не удалось проверить портфель для {ticker}: {e}")
        
        # Если не найден в портфеле, ищем через API
        instruments = client.search_instruments(ticker, instrument_type)
        
        if not instruments:
            # Если не найдено в основном типе, пробуем другие типы
            alternative_types = ["shares", "bonds", "etfs", "currencies"]
            for alt_type in alternative_types:
                if alt_type != instrument_type:
                    try:
                        alt_instruments = client.search_instruments(ticker, alt_type)
                        if alt_instruments:
                            instruments = alt_instruments
                            break
                    except Exception:
                        continue
            
            if not instruments:
                return f"❌ FIGI для тикера '{ticker}' не найден ни в портфеле, ни в API"
        
        result = f"🔍 **FIGI для тикера '{ticker}' (найден через API):**\n\n"
        
        for i, instrument in enumerate(instruments, 1):
            result += f"**{i}. {instrument['ticker']}**\n"
            result += f"   FIGI: `{instrument['figi']}`\n"
            result += f"   Название: {instrument['name']}\n"
            result += f"   Тип: {instrument['instrument_type']}\n"
            result += f"   Валюта: {instrument.get('currency', 'N/A')}\n"
            result += f"   Лот: {instrument.get('lot', 'N/A')}\n"
            result += f"   Источник: API\n"
            result += "\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при поиске FIGI для {ticker}: {e}")
        return f"❌ Ошибка при поиске FIGI: {str(e)}"

@tool
async def get_instrument_details(ticker: str, instrument_type: str = "shares") -> str:
    """
    Получение детальной информации об инструменте по тикеру
    
    Args:
        ticker: Тикер инструмента
        instrument_type: Тип инструмента (shares, bonds, etfs)
    
    Returns:
        Строка с детальной информацией об инструменте
    """
    try:
        client = get_tinkoff_client()
        instruments = client.search_instruments(ticker, instrument_type)
        
        if not instruments:
            return f"❌ Инструмент с тикером '{ticker}' не найден"
        
        # Берем первый найденный инструмент
        instrument = instruments[0]
        figi = instrument['figi']
        
        result = f"📊 **ДЕТАЛЬНАЯ ИНФОРМАЦИЯ ОБ ИНСТРУМЕНТЕ:**\n\n"
        result += f"**Тикер:** {instrument['ticker']}\n"
        result += f"**Название:** {instrument['name']}\n"
        result += f"**FIGI:** {instrument['figi']}\n"
        result += f"**Валюта:** {instrument['currency']}\n"
        result += f"**Лот:** {instrument['lot']}\n"
        result += f"**Тип:** {instrument['instrument_type']}\n"
        result += f"**Минимальный шаг цены:** {instrument['min_price_increment']}\n"
        
        # Получаем текущую цену
        try:
            price_info = await client.get_current_price(figi)
            if price_info:
                result += f"\n💰 **ТЕКУЩАЯ ЦЕНА:**\n"
                result += f"   Цена: {price_info['price']} {instrument['currency']}\n"
                result += f"   Время: {price_info['time']}\n"
        except Exception as e:
            logger.warning(f"Не удалось получить цену для {figi}: {e}")
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении детальной информации для {ticker}: {e}")
        return f"❌ Ошибка при получении детальной информации: {str(e)}"