"""
Клиент для работы с Tinkoff Invest API
"""

import logging
import os
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from decimal import Decimal

try:
    # Основной импорт - tinkoff.invest (работающий вариант)
    from tinkoff.invest import Client, AsyncClient
    from tinkoff.invest.exceptions import RequestError
    from tinkoff.invest.schemas import OrderDirection, OrderType, InstrumentType
    # Для совместимости создаем алиас
    OperationType = OrderDirection
    TINKOFF_AVAILABLE = True
    print("✅ tinkoff_client.py использует tinkoff.invest")
except ImportError:
    try:
        # Альтернативный импорт - официальная библиотека
        from tinkoff_invest import ProductionSession, SandboxSession
        from tinkoff_invest.exceptions import RequestProcessingError
        from tinkoff_invest.models.order import OperationType, OrderType
        from tinkoff_invest.models.instrument import InstrumentType
        from tinkoff_invest.models.portfolio import PortfolioPosition
        from tinkoff_invest.models.operation import Operation
        # Для совместимости создаем алиас
        OrderDirection = OperationType
        TINKOFF_AVAILABLE = True
        print("✅ tinkoff_client.py использует tinkoff_invest")
    except ImportError:
        TINKOFF_AVAILABLE = False
        ProductionSession = None
        SandboxSession = None
        RequestProcessingError = Exception
        OperationType = None
        OrderType = None
        InstrumentType = None
        PortfolioPosition = None
        Operation = None
        print("❌ tinkoff_client.py - Tinkoff API недоступен")

logger = logging.getLogger(__name__)

def format_money(amount) -> str:
    """Форматирование денежной суммы"""
    if amount is None:
        return "0.00"
    
    if hasattr(amount, 'units') and hasattr(amount, 'nano'):
        # Tinkoff Quotation format
        return f"{amount.units}.{amount.nano:09d}".rstrip('0').rstrip('.')
    elif isinstance(amount, (int, float, Decimal)):
        return f"{float(amount):.2f}"
    else:
        return str(amount)

class TinkoffClient:
    """Клиент для работы с Tinkoff Invest API"""
    
    def __init__(self, account_id: Optional[str] = None, token: Optional[str] = None, sandbox: Optional[bool] = None):
        if not TINKOFF_AVAILABLE:
            raise ImportError("Пакет tinkoff_invest не установлен")
        
        # Если токен передан явно, используем его, иначе из переменной окружения
        self.token = token or os.getenv("TINKOFF_TOKEN")
        
        # Если sandbox передан явно, используем его, иначе из переменной окружения
        if sandbox is not None:
            self.sandbox = sandbox
        else:
            self.sandbox = os.getenv("TINKOFF_SANDBOX", "false").lower() == "true"
        
        # Если account_id не передан, используем из переменной окружения
        if account_id:
            self.account_id = str(account_id)
        else:
            self.account_id = os.getenv("TINKOFF_ACCOUNT_ID")
            if self.account_id:
                self.account_id = str(self.account_id)
        
        if not self.token:
            raise ValueError("TINKOFF_TOKEN не настроен")
        
        logger.info(f"TinkoffClient инициализирован: sandbox={self.sandbox}, account_id={self.account_id}")
    
    def get_client(self):
        """Получение клиента Tinkoff Invest"""
        try:
            if self.sandbox:
                client = Client(
                    self.token, 
                    target="sandbox-invest-public-api.tinkoff.ru:443",
                    app_name="giga-agent"
                )
            else:
                client = Client(self.token, app_name="giga-agent")
            
            return client
        except Exception as e:
            logger.error(f"Ошибка при создании клиента: {e}")
            raise
    
    def get_account_id(self) -> str:
        """Получение account_id (автоматически получает первый доступный счет, если не установлен)"""
        if self.account_id:
            return self.account_id
        
        # Если account_id не установлен, получаем первый доступный счет
        accounts = self.get_accounts()
        if not accounts:
            raise ValueError("Нет доступных счетов")
        
        account_id = accounts[0]["id"]
        logger.info(f"Используем первый доступный счет: {account_id}")
        return account_id
    
    def get_accounts(self) -> List[Dict[str, Any]]:
        """Получение всех счетов пользователя"""
        try:
            with self.get_client() as client:
                accounts = client.users.get_accounts()
                
                result = []
                for account in accounts.accounts:
                    account_data = {
                        "id": account.id,
                        "type": str(account.type),
                        "name": account.name,
                        "status": str(account.status),
                        "opened_date": account.opened_date.isoformat() if account.opened_date else None,
                        "access_level": str(account.access_level)
                    }
                    result.append(account_data)
                
                return result
        except Exception as e:
            logger.error(f"Ошибка при получении счетов: {e}")
            raise
    
    async def get_portfolio_all_accounts(self) -> Dict[str, Any]:
        """Получение портфолио по всем счетам"""
        try:
            accounts = self.get_accounts()
            all_portfolios = {}
            total_value = 0
            
            for account in accounts:
                account_id = account["id"]
                account_name = account["name"]
                account_type = account["type"]
                
                # Создаем временный клиент для этого счета
                temp_client = TinkoffClient(account_id=account_id)
                portfolio = await temp_client.get_portfolio()
                
                all_portfolios[account_id] = {
                    "account_name": account_name,
                    "account_type": account_type,
                    "portfolio": portfolio
                }
                
                # Подсчитываем общую стоимость
                try:
                    total_value += float(format_money(portfolio.get('total_amount_shares')))
                    total_value += float(format_money(portfolio.get('total_amount_bonds')))
                    total_value += float(format_money(portfolio.get('total_amount_etf')))
                    total_value += float(format_money(portfolio.get('total_amount_currencies')))
                    total_value += float(format_money(portfolio.get('total_amount_futures')))
                except (ValueError, TypeError):
                    pass
            
            return {
                "total_value": total_value,
                "accounts": all_portfolios
            }
        except Exception as e:
            logger.error(f"Ошибка при получении портфолио по всем счетам: {e}")
            raise
    
    def search_instruments(self, query: str, instrument_type: str = "shares") -> List[Dict[str, Any]]:
        """Поиск инструментов по запросу"""
        try:
            with self.get_client() as client:
                # Определяем тип инструмента
                if instrument_type.lower() == "shares":
                    inst_type = InstrumentType.INSTRUMENT_TYPE_SHARE
                elif instrument_type.lower() == "bonds":
                    inst_type = InstrumentType.INSTRUMENT_TYPE_BOND
                elif instrument_type.lower() == "etfs":
                    inst_type = InstrumentType.INSTRUMENT_TYPE_ETF
                else:
                    inst_type = InstrumentType.INSTRUMENT_TYPE_SHARE
                
                # Поиск инструментов
                response = client.instruments.find_instrument(query=query)
                
                results = []
                for instrument in response.instruments:
                    if instrument.instrument_type == inst_type:
                        results.append({
                            "figi": instrument.figi,
                            "ticker": instrument.ticker,
                            "name": instrument.name,
                            "currency": instrument.currency,
                            "lot": instrument.lot,
                            "min_price_increment": instrument.min_price_increment,
                            "instrument_type": str(instrument.instrument_type)
                        })
                
                return results
        except Exception as e:
            logger.error(f"Ошибка при поиске инструментов: {e}")
            raise
    
    async def get_instrument_by_figi(self, figi: str) -> Optional[Dict[str, Any]]:
        """Получение информации об инструменте по FIGI"""
        try:
            with self.get_client() as client:
                from tinkoff.invest.schemas import InstrumentIdType
                
                instrument_response = client.instruments.get_instrument_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI, 
                    id=figi
                )
                
                if instrument_response and instrument_response.instrument:
                    instrument = instrument_response.instrument
                    return {
                        "figi": instrument.figi,
                        "ticker": instrument.ticker,
                        "name": instrument.name,
                        "currency": instrument.currency,
                        "lot": instrument.lot,
                        "min_price_increment": instrument.min_price_increment,
                        "instrument_type": str(instrument.instrument_type)
                    }
                return None
        except Exception as e:
            logger.error(f"Ошибка при получении инструмента по FIGI {figi}: {e}")
            return None
    
    def get_current_price(self, figi: str) -> Optional[Dict[str, Any]]:
        """Получение текущей цены инструмента"""
        try:
            with self.get_client() as client:
                last_prices = client.market_data.get_last_prices(figi=[figi])
                
                if last_prices and len(last_prices) > 0:
                    price = last_prices[0]
                    return {
                        "figi": price.figi,
                        "price": price.price,
                        "time": price.time
                    }
                return None
        except Exception as e:
            logger.error(f"Ошибка при получении цены для {figi}: {e}")
            return None
    
    async def get_portfolio(self) -> Dict[str, Any]:
        """Получение портфеля"""
        try:
            account_id = self.get_account_id()
            
            with self.get_client() as client:
                portfolio = client.operations.get_portfolio(account_id=account_id)
                
                positions = []
                for position in portfolio.positions:
                    pos_data = {
                        "figi": position.figi,
                        "quantity": position.quantity,
                        "average_position_price": position.average_position_price,
                        "expected_yield": position.expected_yield,
                        "current_nkd": position.current_nkd,
                        "instrument_type": str(position.instrument_type)
                    }
                    
                    # Добавляем поля только если они существуют
                    if hasattr(position, 'average_position_price_pt'):
                        pos_data["average_position_price_pt"] = position.average_position_price_pt
                    if hasattr(position, 'current_price'):
                        pos_data["current_price"] = position.current_price
                    if hasattr(position, 'current_price_pt'):
                        pos_data["current_price_pt"] = position.current_price_pt
                    
                    positions.append(pos_data)
                
                return {
                    "total_amount_shares": portfolio.total_amount_shares,
                    "total_amount_bonds": portfolio.total_amount_bonds,
                    "total_amount_etf": portfolio.total_amount_etf,
                    "total_amount_currencies": portfolio.total_amount_currencies,
                    "total_amount_futures": portfolio.total_amount_futures,
                    "expected_yield": portfolio.expected_yield,
                    "positions": positions
                }
        except Exception as e:
            logger.error(f"Ошибка при получении портфеля: {e}")
            raise
    
    async def place_market_order(self, figi: str, quantity: int, direction: str) -> Dict[str, Any]:
        """Размещение рыночного ордера"""
        try:
            with self.get_client() as client:
                # Определяем направление
                if direction.lower() in ["buy", "покупка", "купить"]:
                    operation_type = OrderDirection.ORDER_DIRECTION_BUY
                elif direction.lower() in ["sell", "продажа", "продать"]:
                    operation_type = OrderDirection.ORDER_DIRECTION_SELL
                else:
                    raise ValueError(f"Неизвестное направление: {direction}")
                
                # Размещаем ордер (используем правильную структуру из примера)
                response = client.orders.post_order(
                    figi=figi,
                    quantity=quantity,
                    account_id=self.get_account_id(),
                    direction=operation_type,
                    order_type=OrderType.ORDER_TYPE_MARKET
                )
                
                # Возвращаем упрощенную структуру с основными полями
                return {
                    "order_id": response.order_id,
                    "execution_report_status": response.execution_report_status.value,
                    "executed_order_price": response.executed_order_price,
                    "total_order_amount": response.total_order_amount,
                    "figi": response.figi,
                    "direction": response.direction.value,
                    "order_type": response.order_type.value,
                    "lots_executed": response.lots_executed,
                    "lots_requested": response.lots_requested,
                    "message": response.message
                }
        except Exception as e:
            logger.error(f"Ошибка при размещении рыночного ордера: {e}")
            raise
    
    def place_limit_order(self, figi: str, quantity: int, price: float, direction: str) -> Dict[str, Any]:
        """Размещение лимитного ордера"""
        try:
            with self.get_client() as client:
                # Определяем направление
                if direction.lower() in ["buy", "покупка", "купить"]:
                    operation_type = OrderDirection.ORDER_DIRECTION_BUY
                elif direction.lower() in ["sell", "продажа", "продать"]:
                    operation_type = OrderDirection.ORDER_DIRECTION_SELL
                else:
                    raise ValueError(f"Неизвестное направление: {direction}")
                
                # Размещаем ордер
                order = client.orders.post_order(
                    figi=figi,
                    quantity=quantity,
                    price=price,
                    direction=operation_type,
                    account_id=self.get_account_id(),
                    order_type=OrderType.LIMIT
                )
                
                return {
                    "order_id": order.order_id,
                    "execution_report_status": order.execution_report_status.value,
                    "executed_order_price": order.executed_order_price,
                    "total_order_amount": order.total_order_amount,
                    "initial_order_price": order.initial_order_price,
                    "initial_commission": order.initial_commission,
                    "executed_commission": order.executed_commission,
                    "aci_value": order.aci_value,
                    "figi": order.figi,
                    "direction": order.direction.value,
                    "initial_security_price": order.initial_security_price,
                    "currency": order.currency,
                    "order_type": order.order_type.value,
                    "order_date": order.order_date
                }
        except Exception as e:
            logger.error(f"Ошибка при размещении лимитного ордера: {e}")
            raise
    
    def get_operations(self, from_date: str, to_date: str) -> List[Dict[str, Any]]:
        """Получение операций за период"""
        try:
            from datetime import datetime
            
            # Преобразуем строки в объекты datetime (без timezone для совместимости с API)
            from_dt = datetime.strptime(from_date, "%Y-%m-%d")
            from_dt = from_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            
            to_dt = datetime.strptime(to_date, "%Y-%m-%d")
            to_dt = to_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            with self.get_client() as client:
                # Используем правильные параметры для API
                operations_response = client.operations.get_operations(
                    account_id=self.get_account_id(),
                    from_=from_dt,
                    to=to_dt
                )
                
                # Получаем операции из ответа
                operations = operations_response.operations
                
                results = []
                for operation in operations:
                    # Безопасно обрабатываем дату
                    operation_date = str(operation.date)
                    
                    # Безопасно обрабатываем enum поля
                    state_value = operation.state.value if hasattr(operation.state, 'value') else str(operation.state)
                    instrument_type_value = operation.instrument_type.value if hasattr(operation.instrument_type, 'value') else str(operation.instrument_type)
                    type_value = operation.type.value if hasattr(operation.type, 'value') else str(operation.type)
                    operation_type_value = operation.operation_type.value if hasattr(operation.operation_type, 'value') else str(operation.operation_type)
                    
                    # Безопасно обрабатываем payment
                    payment_value = None
                    if hasattr(operation, 'payment') and operation.payment:
                        if hasattr(operation.payment, 'units') and hasattr(operation.payment, 'nano'):
                            payment_value = operation.payment.units + operation.payment.nano / 1000000000
                        else:
                            payment_value = str(operation.payment)
                    
                    # Безопасно обрабатываем price
                    price_value = None
                    if hasattr(operation, 'price') and operation.price:
                        if hasattr(operation.price, 'units') and hasattr(operation.price, 'nano'):
                            price_value = operation.price.units + operation.price.nano / 1000000000
                        else:
                            price_value = str(operation.price)
                    
                    results.append({
                        "id": getattr(operation, 'id', None),
                        "parent_operation_id": getattr(operation, 'parent_operation_id', None),
                        "currency": getattr(operation, 'currency', None),
                        "payment": payment_value,
                        "price": price_value,
                        "state": state_value,
                        "quantity": getattr(operation, 'quantity', None),
                        "quantity_rest": getattr(operation, 'quantity_rest', None),
                        "figi": getattr(operation, 'figi', None),
                        "instrument_type": instrument_type_value,
                        "date": operation_date,
                        "type": type_value,
                        "operation_type": operation_type_value,
                        "trades": getattr(operation, 'trades', None),
                        "asset_uid": getattr(operation, 'asset_uid', None),
                        "position_uid": getattr(operation, 'position_uid', None)
                    })
                
                return results
        except Exception as e:
            logger.error(f"Ошибка при получении операций: {e}")
            raise
    
    def get_orders(self) -> List[Dict[str, Any]]:
        """Получение активных ордеров"""
        try:
            with self.get_client() as client:
                orders = client.orders.get_orders(account_id=self.get_account_id())
                
                results = []
                for order in orders:
                    results.append({
                        "order_id": order.order_id,
                        "execution_report_status": order.execution_report_status.value,
                        "lots_requested": order.lots_requested,
                        "lots_executed": order.lots_executed,
                        "initial_order_price": order.initial_order_price,
                        "executed_order_price": order.executed_order_price,
                        "total_order_amount": order.total_order_amount,
                        "average_position_price": order.average_position_price,
                        "initial_commission": order.initial_commission,
                        "executed_commission": order.executed_commission,
                        "figi": order.figi,
                        "direction": order.direction.value,
                        "initial_security_price": order.initial_security_price,
                        "currency": order.currency,
                        "order_type": order.order_type.value,
                        "order_date": order.order_date,
                        "instrument_uid": order.instrument_uid
                    })
                
                return results
        except Exception as e:
            logger.error(f"Ошибка при получении ордеров: {e}")
            raise
    
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Отмена ордера"""
        try:
            with self.get_client() as client:
                result = client.orders.cancel_order(
                    account_id=self.get_account_id(),
                    order_id=order_id
                )
                
                return {
                    "time": result.time,
                    "execution_report_status": result.execution_report_status.value
                }
        except Exception as e:
            logger.error(f"Ошибка при отмене ордера {order_id}: {e}")
            raise

# Глобальный экземпляр клиента (для обратной совместимости)
_tinkoff_client = None
# Кэш клиентов по user_id
_user_clients: Dict[str, TinkoffClient] = {}

def get_tinkoff_client(user_id: Optional[str] = None, token: Optional[str] = None, account_id: Optional[str] = None, sandbox: Optional[bool] = None, state: Optional[Dict] = None) -> TinkoffClient:
    """
    Получение экземпляра клиента Tinkoff
    
    Args:
        user_id: ID пользователя для получения токенов из БД
        token: Токен Tinkoff (если передан, используется вместо получения из БД)
        account_id: ID счета (если передан, используется вместо получения из БД)
        sandbox: Режим sandbox (если передан, используется вместо получения из БД)
        state: Состояние графа (для извлечения user_id, если не передан явно)
    """
    global _tinkoff_client, _user_clients
    
    # Если user_id не передан, но есть state, извлекаем из состояния
    if not user_id and state:
        user_id = state.get("user_id")
    
    # Если передан user_id, используем токены пользователя
    if user_id:
        # Проверяем кэш
        if user_id in _user_clients:
            return _user_clients[user_id]
        
        # Получаем токены пользователя синхронно
        try:
            from giga_agent.utils.user_tokens_sync import get_user_tinkoff_config_sync
            user_config = get_user_tinkoff_config_sync(user_id)
            
            # Создаем клиент с токенами пользователя
            client = TinkoffClient(
                account_id=account_id or user_config.get("account_id"),
                token=token or user_config.get("token"),
                sandbox=sandbox if sandbox is not None else user_config.get("sandbox", False)
            )
            _user_clients[user_id] = client
            return client
        except Exception as e:
            logger.warning(f"Не удалось получить токены пользователя {user_id}, используем глобальный клиент: {e}")
            # Fallback на глобальный клиент
    
    # Если передан token явно, создаем новый клиент
    if token:
        return TinkoffClient(account_id=account_id, token=token, sandbox=sandbox)
    
    # Используем глобальный клиент (для обратной совместимости)
    if _tinkoff_client is None:
        _tinkoff_client = TinkoffClient(account_id=account_id, sandbox=sandbox)
    return _tinkoff_client
