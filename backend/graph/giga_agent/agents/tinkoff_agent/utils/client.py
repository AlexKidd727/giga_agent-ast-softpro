"""
Клиент для работы с Tinkoff Invest API
"""

import logging
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

try:
    # Основной импорт - tinkoff.invest (работающий вариант)
    from tinkoff.invest import Client, AsyncClient
    from tinkoff.invest.exceptions import RequestError
    from tinkoff.invest.schemas import OrderDirection, OrderType
    TINKOFF_AVAILABLE = True
    print("✅ Используется tinkoff.invest")
except ImportError:
    try:
        # Альтернативный импорт - официальная библиотека
        from tinkoff_invest import ProductionSession, SandboxSession
        from tinkoff_invest.exceptions import RequestProcessingError
        from tinkoff_invest.models.order import OperationType, OrderType
        TINKOFF_AVAILABLE = True
        # Для совместимости создаем алиасы
        Client = ProductionSession
        AsyncClient = ProductionSession
        RequestError = RequestProcessingError
        OrderDirection = OperationType
        print("✅ Используется tinkoff_invest")
    except ImportError:
        try:
            # Еще один альтернативный импорт
            from tinkoff_investments import Client, AsyncClient
            from tinkoff_investments.exceptions import RequestError
            from tinkoff_investments.schemas import OrderDirection, OrderType
            TINKOFF_AVAILABLE = True
            print("✅ Используется tinkoff_investments")
        except ImportError:
            TINKOFF_AVAILABLE = False
            Client = None
            AsyncClient = None
            RequestError = Exception
            OrderDirection = None
            OrderType = None
            print("❌ Tinkoff API недоступен")

from ..config import TINKOFF_TOKEN, TINKOFF_ACCOUNT_ID, TINKOFF_SANDBOX

logger = logging.getLogger(__name__)

class TinkoffClient:
    """Обертка для Tinkoff Invest API клиента"""
    
    def __init__(self):
        if not TINKOFF_AVAILABLE:
            raise ImportError("Пакет tinkoff-investments не установлен")
        
        self.token = TINKOFF_TOKEN
        self.account_id = TINKOFF_ACCOUNT_ID
        self.sandbox = TINKOFF_SANDBOX
        
        if not self.token:
            raise ValueError("TINKOFF_TOKEN не настроен")
        
        if not self.account_id:
            raise ValueError("TINKOFF_ACCOUNT_ID не настроен")
    
    @asynccontextmanager
    async def get_async_client(self):
        """Получение асинхронного клиента"""
        try:
            if self.sandbox:
                async with AsyncClient(
                    self.token, 
                    target="sandbox-invest-public-api.tinkoff.ru:443",
                    app_name="giga-agent"
                ) as client:
                    yield client
            else:
                async with AsyncClient(self.token, app_name="giga-agent") as client:
                    yield client
        except Exception as e:
            logger.error(f"Ошибка создания async клиента: {e}")
            raise
    
    def get_sync_client(self):
        """Получение синхронного клиента"""
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
            logger.error(f"Ошибка создания sync клиента: {e}")
            raise
    
    async def safe_api_call(self, func, *args, **kwargs):
        """Безопасный вызов API с обработкой ошибок"""
        try:
            result = await func(*args, **kwargs)
            return {"success": True, "data": result}
        except RequestError as e:
            logger.error(f"Ошибка API Tinkoff: {e}")
            error_details = str(e)
            
            # Определяем тип ошибки для пользователя
            if "insufficient funds" in error_details.lower():
                user_error = "Недостаточно средств на счете"
            elif "invalid instrument" in error_details.lower():
                user_error = "Инструмент не найден или недоступен"
            elif "market closed" in error_details.lower():
                user_error = "Рынок закрыт"
            elif "unauthorized" in error_details.lower():
                user_error = "Неверный токен авторизации"
            else:
                user_error = "Ошибка API Tinkoff"
            
            return {
                "success": False, 
                "error": user_error,
                "details": error_details
            }
        except Exception as e:
            logger.error(f"Неожиданная ошибка: {e}")
            return {
                "success": False,
                "error": "Неожиданная ошибка", 
                "details": str(e)
            }
    
    def check_connection(self) -> Dict[str, Any]:
        """Проверка подключения к Tinkoff API"""
        try:
            # Создаем клиент с правильными параметрами
            if self.sandbox:
                client = Client(
                    self.token, 
                    target="sandbox-invest-public-api.tinkoff.ru:443",
                    app_name="giga-agent"
                )
            else:
                client = Client(self.token, app_name="giga-agent")
            
            # Используем контекстный менеджер для доступа к сервисам
            with client as c:
                try:
                    accounts = c.users.get_accounts()
                    account_found = False
                    
                    for account in accounts.accounts:
                        if account.id == self.account_id:
                            account_found = True
                            break
                    
                    return {
                        "success": True,
                        "sandbox_mode": self.sandbox,
                        "account_found": account_found,
                        "account_id": self.account_id,
                        "accounts_count": len(accounts.accounts)
                    }
                    
                except Exception as e:
                    logger.error(f"Ошибка при получении аккаунтов: {e}")
                    return {
                        "success": False,
                        "error": f"Не удалось получить аккаунты: {str(e)}"
                    }
                
        except Exception as e:
            logger.error(f"Ошибка проверки подключения: {e}")
            return {
                "success": False,
                "error": str(e)
            }

# Глобальный экземпляр клиента
_tinkoff_client = None

def get_tinkoff_client() -> Optional[TinkoffClient]:
    """Получение клиента Tinkoff"""
    global _tinkoff_client
    
    if not TINKOFF_AVAILABLE:
        logger.error("Tinkoff Invest API недоступен - пакет не установлен")
        return None
    
    if _tinkoff_client is None:
        try:
            _tinkoff_client = TinkoffClient()
        except Exception as e:
            logger.error(f"Не удалось создать Tinkoff клиент: {e}")
            return None
    
    return _tinkoff_client
