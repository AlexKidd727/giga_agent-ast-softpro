"""
Узлы для работы с портфелем в Tinkoff
"""

import logging
from typing import Annotated, Dict, Any, List
from datetime import datetime

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
        # Правильное форматирование для nano
        nano_str = f"{money_value.nano:09d}"
        # Убираем лишние нули справа
        nano_str = nano_str.rstrip('0')
        if not nano_str:
            return f"{money_value.units}.00"
        else:
            # Исправляем проблему с отрицательными nano
            if money_value.units < 0 and money_value.nano > 0:
                # Если units отрицательный, а nano положительный, нужно скорректировать
                return f"{money_value.units}.{nano_str}"
            else:
                return f"{money_value.units}.{nano_str}"
    
    # Если это строка, пытаемся преобразовать
    if isinstance(money_value, str):
        try:
            # Исправляем проблему с двойными точками и неправильным форматом
            clean_str = money_value.replace('..', '.')
            # Исправляем формат типа "-1216.-63" -> "-1216.63" (сохраняем знак минус!)
            if '.-' in clean_str:
                clean_str = clean_str.replace('.-', '.')
            # Дополнительная очистка для случаев типа "-1216.-63" (сохраняем знак минус!)
            import re
            # Исправляем формат "-1216.-63" -> "-1216.63"
            clean_str = re.sub(r'(-?\d+)\.-(\d+)', r'\1.\2', clean_str)
            return f"{float(clean_str):.2f}"
        except ValueError:
            return "0.00"
    
    # Если это число
    try:
        return f"{float(money_value):.2f}"
    except (ValueError, TypeError):
        return "0.00"

def format_quantity(quantity_value) -> str:
    """Форматирование количества (сохраняем знак для шорт позиций)"""
    if quantity_value is None:
        return "0"
    
    # Если это объект с units и nano
    if hasattr(quantity_value, 'units') and hasattr(quantity_value, 'nano'):
        # Для количества обычно nano = 0, поэтому просто units (сохраняем знак!)
        if quantity_value.nano == 0:
            return str(quantity_value.units)
        else:
            # Если есть nano, форматируем как дробное число (сохраняем знак!)
            nano_str = f"{quantity_value.nano:09d}"
            nano_str = nano_str.rstrip('0')
            if not nano_str:
                return str(quantity_value.units)
            else:
                return f"{quantity_value.units}.{nano_str}"
    
    # Если это строка или число (сохраняем знак!)
    try:
        return str(int(float(quantity_value)))
    except (ValueError, TypeError):
        return "0"

async def format_portfolio_positions(positions: List[Dict[str, Any]]) -> str:
    """Форматирование позиций портфеля"""
    if not positions:
        return "Позиции не найдены"
    
    result = []
    for pos in positions:
        figi = pos.get('figi', 'N/A')
        quantity = pos.get('quantity', 0)
        current_price = pos.get('current_price')
        expected_yield = pos.get('expected_yield')
        
        # Получаем информацию об инструменте
        try:
            client = get_tinkoff_client()
            instrument_info = await client.get_instrument_by_figi(figi)
            if instrument_info:
                ticker = instrument_info.get('ticker', 'N/A')
                name = instrument_info.get('name', 'N/A')
                currency = instrument_info.get('currency', 'RUB')
                lot = instrument_info.get('lot', 1)  # Лотность инструмента
                instrument_type = instrument_info.get('instrument_type', 'N/A')
            else:
                ticker = 'N/A'
                name = 'N/A'
                currency = 'RUB'
                lot = 1
                instrument_type = 'N/A'
        except:
            ticker = 'N/A'
            name = 'N/A'
            currency = 'RUB'
            lot = 1
            instrument_type = 'N/A'
        
        # Переводим тип инструмента на русский язык
        type_translation = {
            'share': 'акция',
            'shares': 'акция', 
            'bond': 'облигация',
            'bonds': 'облигация',
            'etf': 'ETF',
            'currency': 'валюта',
            'future': 'фьючерс',
            'futures': 'фьючерс'
        }
        translated_type = type_translation.get(instrument_type.lower(), instrument_type)
        
        position_info = f"📊 {ticker} ({name})\n"
        position_info += f"   FIGI: {figi}\n"
        position_info += f"   Тип: {translated_type}\n"
        
        # Специальная обработка количества с пояснением о шорт позиции
        quantity_str = format_quantity(quantity)
        if quantity_str.startswith('-'):
            position_info += f"   Количество: {quantity_str} (лотность: {lot}) - ШОРТ позиция\n"
        else:
            position_info += f"   Количество: {quantity_str} (лотность: {lot})\n"
        
        if current_price:
            position_info += f"   Текущая цена: {format_money(current_price)} {currency}\n"
            
            # Рассчитываем итоговую стоимость позиции с учетом лотности
            try:
                qty_value = float(format_quantity(quantity))
                price_value = float(format_money(current_price))
                total_value = qty_value * price_value
                position_info += f"   💰 Итоговая стоимость: {total_value:.2f} {currency}\n"
            except (ValueError, TypeError):
                position_info += f"   💰 Итоговая стоимость: не удалось рассчитать\n"
        
        if expected_yield:
            position_info += f"   Доходность: {format_money(expected_yield)} {currency}\n"
        
        result.append(position_info)
    
    return "\n".join(result)

@tool
async def get_portfolio(user_id: str = "default_user", state: Annotated[dict, InjectedState] = None) -> str:
    """
    Получение полной информации о портфеле пользователя
    
    Args:
        user_id: Идентификатор пользователя (необязательно)
        state: Состояние графа (для извлечения user_id, если не передан явно)
    
    Returns:
        Строка с информацией о портфеле
    """
    try:
        # Извлекаем user_id из состояния, если не передан явно
        if user_id == "default_user" and state:
            user_id = state.get("user_id", "default_user")
        
        client = get_tinkoff_client(user_id=user_id if user_id != "default_user" else None)
        portfolio = await client.get_portfolio()
        
        result = "📈 **ПОРТФЕЛЬ ПОЛЬЗОВАТЕЛЯ**\n\n"
        
        # Подсчитываем общую стоимость портфеля
        total_portfolio_value = 0
        try:
            total_portfolio_value += float(format_money(portfolio.get('total_amount_shares')))
            total_portfolio_value += float(format_money(portfolio.get('total_amount_bonds')))
            total_portfolio_value += float(format_money(portfolio.get('total_amount_etf')))
            total_portfolio_value += float(format_money(portfolio.get('total_amount_currencies')))
            total_portfolio_value += float(format_money(portfolio.get('total_amount_futures')))
        except (ValueError, TypeError):
            total_portfolio_value = 0
        
        # Общая информация
        result += f"💰 **Общая стоимость портфеля:** {total_portfolio_value:.2f} RUB\n\n"
        result += "📊 **Детализация по типам:**\n"
        result += f"   Акции: {format_money(portfolio.get('total_amount_shares'))} RUB\n"
        result += f"   Облигации: {format_money(portfolio.get('total_amount_bonds'))} RUB\n"
        result += f"   ETF: {format_money(portfolio.get('total_amount_etf'))} RUB\n"
        
        # Специальная обработка валюты с пояснением о долге
        currencies_amount = format_money(portfolio.get('total_amount_currencies'))
        if currencies_amount.startswith('-'):
            result += f"   Валюты: {currencies_amount} RUB (долг)\n"
        else:
            result += f"   Валюты: {currencies_amount} RUB\n"
            
        result += f"   Фьючерсы: {format_money(portfolio.get('total_amount_futures'))} RUB\n"
        
        expected_yield = portfolio.get('expected_yield')
        if expected_yield:
            result += f"   Ожидаемая доходность: {format_money(expected_yield)} RUB\n"
        
        result += "\n"
        
        # Позиции
        positions = portfolio.get('positions', [])
        if positions:
            result += "📊 **ПОЗИЦИИ:**\n\n"
            result += await format_portfolio_positions(positions)
        else:
            result += "📊 **ПОЗИЦИИ:** Позиции не найдены\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении портфеля: {e}")
        return f"❌ Ошибка при получении портфеля: {str(e)}"

@tool
async def get_all_accounts() -> str:
    """
    Получение списка всех счетов пользователя
    
    Returns:
        Строка с информацией о всех счетах
    """
    try:
        client = get_tinkoff_client()
        accounts = client.get_accounts()
        
        if not accounts:
            return "📋 **СЧЕТА:** Счета не найдены"
        
        result = "📋 **ВСЕ СЧЕТА ПОЛЬЗОВАТЕЛЯ**\n\n"
        
        for i, account in enumerate(accounts, 1):
            result += f"**{i}. {account['name']}**\n"
            result += f"   ID: {account['id']}\n"
            result += f"   Тип: {account['type']}\n"
            result += f"   Статус: {account['status']}\n"
            if account['opened_date']:
                result += f"   Дата открытия: {account['opened_date']}\n"
            result += f"   Уровень доступа: {account['access_level']}\n\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении счетов: {e}")
        return f"❌ Ошибка при получении счетов: {str(e)}"

@tool
async def get_portfolio_all_accounts() -> str:
    """
    Получение портфолио по всем счетам пользователя
    
    Returns:
        Строка с информацией о портфолио по всем счетам
    """
    try:
        client = get_tinkoff_client()
        all_portfolios = await client.get_portfolio_all_accounts()
        
        result = "📈 **ПОРТФЕЛЬ ПО ВСЕМ СЧЕТАМ**\n\n"
        result += f"💰 **Общая стоимость всех портфелей:** {all_portfolios['total_value']:.2f} RUB\n\n"
        
        for account_id, account_data in all_portfolios['accounts'].items():
            portfolio = account_data['portfolio']
            account_name = account_data['account_name']
            account_type = account_data['account_type']
            
            result += f"🏦 **{account_name}** ({account_type})\n"
            result += f"   ID счета: {account_id}\n"
            
            # Подсчитываем стоимость этого счета
            account_value = 0
            try:
                account_value += float(format_money(portfolio.get('total_amount_shares')))
                account_value += float(format_money(portfolio.get('total_amount_bonds')))
                account_value += float(format_money(portfolio.get('total_amount_etf')))
                account_value += float(format_money(portfolio.get('total_amount_currencies')))
                account_value += float(format_money(portfolio.get('total_amount_futures')))
            except (ValueError, TypeError):
                pass
            
            result += f"   💰 Стоимость: {account_value:.2f} RUB\n"
            result += f"   📊 Акции: {format_money(portfolio.get('total_amount_shares'))} RUB\n"
            result += f"   📊 Облигации: {format_money(portfolio.get('total_amount_bonds'))} RUB\n"
            result += f"   📊 ETF: {format_money(portfolio.get('total_amount_etf'))} RUB\n"
            
            # Позиции
            positions = portfolio.get('positions', [])
            if positions:
                result += f"   📋 Позиций: {len(positions)}\n"
            else:
                result += f"   📋 Позиций: 0\n"
            
            result += "\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении портфолио по всем счетам: {e}")
        return f"❌ Ошибка при получении портфолио по всем счетам: {str(e)}"

@tool
async def get_positions_all_accounts() -> str:
    """
    Получение детальных позиций по всем счетам пользователя
    
    Returns:
        Строка с детальной информацией о позициях по всем счетам
    """
    try:
        client = get_tinkoff_client()
        all_portfolios = await client.get_portfolio_all_accounts()
        
        result = "📈 **ПОЗИЦИИ ПО ВСЕМ СЧЕТАМ**\n\n"
        result += f"💰 **Общая стоимость всех портфелей:** {all_portfolios['total_value']:.2f} RUB\n\n"
        
        for account_id, account_data in all_portfolios['accounts'].items():
            portfolio = account_data['portfolio']
            account_name = account_data['account_name']
            account_type = account_data['account_type']
            
            result += f"🏦 **{account_name}** ({account_type})\n"
            result += f"   ID счета: {account_id}\n"
            
            # Подсчитываем стоимость этого счета
            account_value = 0
            try:
                account_value += float(format_money(portfolio.get('total_amount_shares')))
                account_value += float(format_money(portfolio.get('total_amount_bonds')))
                account_value += float(format_money(portfolio.get('total_amount_etf')))
                account_value += float(format_money(portfolio.get('total_amount_currencies')))
                account_value += float(format_money(portfolio.get('total_amount_futures')))
            except (ValueError, TypeError):
                pass
            
            result += f"   💰 Стоимость: {account_value:.2f} RUB\n"
            result += f"   📊 Акции: {format_money(portfolio.get('total_amount_shares'))} RUB\n"
            result += f"   📊 Облигации: {format_money(portfolio.get('total_amount_bonds'))} RUB\n"
            result += f"   📊 ETF: {format_money(portfolio.get('total_amount_etf'))} RUB\n"
            
            # Детальные позиции
            positions = portfolio.get('positions', [])
            if positions:
                result += f"   📋 Позиций: {len(positions)}\n\n"
                
                # Показываем детали каждой позиции
                for position in positions:
                    figi = position.get('figi', 'N/A')
                    quantity = position.get('quantity', 0)
                    average_price = position.get('average_position_price', 0)
                    current_price = position.get('current_price', 0)
                    expected_yield = position.get('expected_yield', 0)
                    
                    # Получаем информацию об инструменте по FIGI
                    ticker = "N/A"
                    name = "N/A"
                    instrument_type = "N/A"
                    currency = "RUB"  # По умолчанию RUB
                    
                    if figi != 'N/A':
                        try:
                            instrument_info = await client.get_instrument_by_figi(figi)
                            if instrument_info:
                                ticker = instrument_info.get('ticker', 'N/A')
                                name = instrument_info.get('name', 'N/A')
                                instrument_type = instrument_info.get('instrument_type', 'N/A')
                                currency = instrument_info.get('currency', 'RUB')
                        except Exception as e:
                            logger.warning(f"Не удалось получить информацию об инструменте {figi}: {e}")
                    
                    # Переводим тип инструмента на русский язык
                    type_translation = {
                        'share': 'акция',
                        'shares': 'акция', 
                        'bond': 'облигация',
                        'bonds': 'облигация',
                        'etf': 'ETF',
                        'currency': 'валюта',
                        'future': 'фьючерс',
                        'futures': 'фьючерс'
                    }
                    translated_type = type_translation.get(instrument_type.lower(), instrument_type)
                    
                    # Форматируем цены и количество
                    avg_price_str = format_money(average_price)
                    curr_price_str = format_money(current_price)
                    yield_str = format_money(expected_yield)
                    quantity_str = format_quantity(quantity)
                    
                    result += f"   📊 **{ticker}** ({name})\n"
                    result += f"      FIGI: {figi}\n"
                    result += f"      Тип: {translated_type}\n"
                    result += f"      Количество: {quantity_str}\n"
                    result += f"      Средняя цена: {avg_price_str} {currency}\n"
                    result += f"      Текущая цена: {curr_price_str} {currency}\n"
                    result += f"      Доходность: {yield_str} {currency}\n\n"
            else:
                result += f"   📋 Позиций: 0\n\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении позиций по всем счетам: {e}")
        return f"❌ Ошибка при получении позиций по всем счетам: {str(e)}"

@tool
async def get_positions(user_id: str = "default_user") -> str:
    """
    Получение информации о позициях в портфеле
    
    Args:
        user_id: Идентификатор пользователя (необязательно)
    
    Returns:
        Строка с информацией о позициях
    """
    try:
        client = get_tinkoff_client()
        portfolio = await client.get_portfolio()
        
        positions = portfolio.get('positions', [])
        if not positions:
            return "📊 **ПОЗИЦИИ:** Позиции не найдены"
        
        # Подсчитываем общую стоимость портфеля на основе позиций
        total_portfolio_value = 0
        for position in positions:
            try:
                quantity = position.get('quantity', 0)
                current_price = position.get('current_price')
                figi = position.get('figi')
                
                if current_price and quantity and figi:
                    # Получаем информацию об инструменте для лотности
                    try:
                        instrument_info = await client.get_instrument_by_figi(figi)
                        lot = instrument_info.get('lot', 1) if instrument_info else 1
                    except:
                        lot = 1
                    
                    # Получаем числовые значения
                    qty_value = float(format_quantity(quantity))
                    price_value = float(format_money(current_price))
                    
                    # Считаем стоимость позиции с учетом лотности (учитываем знак количества)
                    position_value = qty_value * price_value
                    total_portfolio_value += position_value
                    
            except (ValueError, TypeError, AttributeError):
                continue
        
        result = f"💰 **Общая стоимость портфеля:** {total_portfolio_value:.2f} RUB\n\n"
        result += "📊 **ПОЗИЦИИ В ПОРТФЕЛЕ:**\n\n"
        result += await format_portfolio_positions(positions)
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении позиций: {e}")
        return f"❌ Ошибка при получении позиций: {str(e)}"

@tool
async def get_balance(user_id: str = "default_user") -> str:
    """
    Получение информации о балансе счета
    
    Args:
        user_id: Идентификатор пользователя (необязательно)
    
    Returns:
        Строка с информацией о балансе
    """
    try:
        client = get_tinkoff_client()
        portfolio = await client.get_portfolio()
        
        result = "💰 **БАЛАНС СЧЕТА:**\n\n"
        
        # Общая стоимость по типам инструментов
        result += "📈 **Стоимость по типам:**\n"
        result += f"   Акции: {format_money(portfolio.get('total_amount_shares'))} RUB\n"
        result += f"   Облигации: {format_money(portfolio.get('total_amount_bonds'))} RUB\n"
        result += f"   ETF: {format_money(portfolio.get('total_amount_etf'))} RUB\n"
        result += f"   Валюты: {format_money(portfolio.get('total_amount_currencies'))} RUB\n"
        result += f"   Фьючерсы: {format_money(portfolio.get('total_amount_futures'))} RUB\n"
        
        # Ожидаемая доходность
        expected_yield = portfolio.get('expected_yield')
        if expected_yield:
            result += f"\n📊 **Ожидаемая доходность:** {format_money(expected_yield)} RUB\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении баланса: {e}")
        return f"❌ Ошибка при получении баланса: {str(e)}"

@tool
async def get_portfolio_summary(user_id: str = "default_user") -> str:
    """
    Получение краткой сводки по портфелю
    
    Args:
        user_id: Идентификатор пользователя (необязательно)
    
    Returns:
        Строка с краткой сводкой по портфелю
    """
    try:
        client = get_tinkoff_client()
        portfolio = await client.get_portfolio()
        
        result = "📊 **СВОДКА ПО ПОРТФЕЛЮ:**\n\n"
        
        # Подсчитываем общую стоимость на основе позиций
        total_value = 0
        positions = portfolio.get('positions', [])
        
        for position in positions:
            try:
                quantity = position.get('quantity', 0)
                current_price = position.get('current_price')
                figi = position.get('figi')
                
                if current_price and quantity and figi:
                    # Получаем информацию об инструменте для лотности
                    try:
                        instrument_info = await client.get_instrument_by_figi(figi)
                        lot = instrument_info.get('lot', 1) if instrument_info else 1
                    except:
                        lot = 1
                    
                    # Получаем числовые значения
                    qty_value = float(format_quantity(quantity))
                    price_value = float(format_money(current_price))
                    
                    # Считаем стоимость позиции с учетом лотности (учитываем знак количества)
                    position_value = qty_value * price_value
                    total_value += position_value
                    
            except (ValueError, TypeError, AttributeError):
                continue
        
        result += f"💰 **Общая стоимость портфеля:** {total_value:.2f} RUB\n"
        
        # Добавляем детализацию по типам инструментов
        result += "\n📊 **Детализация по типам:**\n"
        result += f"   Акции: {format_money(portfolio.get('total_amount_shares'))} RUB\n"
        result += f"   Облигации: {format_money(portfolio.get('total_amount_bonds'))} RUB\n"
        result += f"   ETF: {format_money(portfolio.get('total_amount_etf'))} RUB\n"
        
        # Специальная обработка валюты с пояснением о долге
        currencies_amount = format_money(portfolio.get('total_amount_currencies'))
        if currencies_amount.startswith('-'):
            result += f"   Валюты: {currencies_amount} RUB (долг)\n"
        else:
            result += f"   Валюты: {currencies_amount} RUB\n"
            
        result += f"   Фьючерсы: {format_money(portfolio.get('total_amount_futures'))} RUB\n"
        
        # Количество позиций
        positions = portfolio.get('positions', [])
        result += f"📈 **Количество позиций:** {len(positions)}\n"
        
        # Ожидаемая доходность
        expected_yield = portfolio.get('expected_yield')
        if expected_yield:
            try:
                yield_value = float(format_money(expected_yield))
                result += f"📊 **Ожидаемая доходность:** {yield_value:.2f} RUB\n"
                
                # Процент доходности
                if total_value > 0:
                    yield_percent = (yield_value / total_value) * 100
                    result += f"📈 **Процент доходности:** {yield_percent:.2f}%\n"
            except (ValueError, TypeError):
                result += f"📊 **Ожидаемая доходность:** {format_money(expected_yield)} RUB\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении сводки по портфелю: {e}")
        return f"❌ Ошибка при получении сводки по портфелю: {str(e)}"