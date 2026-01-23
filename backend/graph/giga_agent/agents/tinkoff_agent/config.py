"""
Конфигурация Tinkoff Trading Agent
"""

import os
from decimal import Decimal

def get_tinkoff_agent_llm():
    """Получить LLM для Tinkoff агента (отложенный импорт)"""
    from giga_agent.utils.llm import load_llm
    return load_llm().with_config(tags=["nostream"])

# Tinkoff API настройки
TINKOFF_TOKEN = os.getenv("TINKOFF_TOKEN")
TINKOFF_ACCOUNT_ID = os.getenv("TINKOFF_ACCOUNT_ID")
TINKOFF_SANDBOX = os.getenv("TINKOFF_SANDBOX", "true").lower() == "true"

# Настройки безопасности торговли
MAX_ORDER_AMOUNT = Decimal(os.getenv("TINKOFF_MAX_ORDER_AMOUNT", "100000"))  # 100k рублей
MIN_ORDER_AMOUNT = Decimal(os.getenv("TINKOFF_MIN_ORDER_AMOUNT", "1000"))    # 1k рублей
MAX_POSITION_SIZE = Decimal(os.getenv("TINKOFF_MAX_POSITION_SIZE", "500000"))  # 500k рублей

# API endpoints
TINKOFF_INVEST_API_URL = "https://invest-public-api.tinkoff.ru/rest"
TINKOFF_SANDBOX_API_URL = "https://sandbox-invest-public-api.tinkoff.ru/rest"

# Справочник популярных российских акций
POPULAR_STOCKS = {
    "SBER": {"name": "Сбербанк", "figi": "BBG004S68598"},
    "GAZP": {"name": "Газпром", "figi": "BBG004730N88"},
    "LKOH": {"name": "Лукойл", "figi": "BBG00F9XX7H4"},
    "ROSN": {"name": "Роснефть", "figi": "BBG004S683W7"},
    "TCSG": {"name": "Тинькофф", "figi": "BBG00RPRPX12"},
    "MGNT": {"name": "Магнит", "figi": "BBG008F2T3T2"},
    "YNDX": {"name": "Яндекс", "figi": "BBG00F6NKQX3"},
    "MTSS": {"name": "МТС", "figi": "BBG004731354"},
    "GMKN": {"name": "ГМК Норникель", "figi": "BBG004730ZJ9"},
    "AFKS": {"name": "АФК Система", "figi": "BBG004S68614"},
    "NVTK": {"name": "Новатэк", "figi": "BBG000B9XRY4"},
    "TATN": {"name": "Татнефть", "figi": "BBG000B9X8T8"},
    "ALRS": {"name": "АЛРОСА", "figi": "BBG004S68473"},
    "CHMF": {"name": "Северсталь", "figi": "BBG000Q7Y2C0"},
    "IRKT": {"name": "Яковлев", "figi": "BBG000FWGSZ5"},  # Иркут (ОАО "Компания Сухой")
    "MTLR": {"name": "Мечел", "figi": "BBG000B9XRY4"}  # Мечел (временно, будет получен через API)
}

# Справочник валют
POPULAR_CURRENCIES = {
    "RUB": {"name": "Российский рубль", "figi": "RUB000UTSTOM"},
    "USD": {"name": "Доллар США", "figi": "BBG0013HGFT4"},
    "EUR": {"name": "Евро", "figi": "BBG0013HJJ31"},
    "CNY": {"name": "Китайский юань", "figi": "BBG0013HRTL0"},
    "GBP": {"name": "Британский фунт", "figi": "BBG0013HQ5K0"},
    "CHF": {"name": "Швейцарский франк", "figi": "BBG0013J7V24"},
    "JPY": {"name": "Японская йена", "figi": "BBG0013J12N1"}
}

# Настройки риск-менеджмента
RISK_SETTINGS = {
    "max_daily_loss": Decimal("50000"),      # Максимальный дневной убыток
    "max_position_count": 10,                # Максимальное количество позиций
    "stop_loss_percent": Decimal("0.05"),   # Стоп-лосс 5%
    "take_profit_percent": Decimal("0.15"),  # Тейк-профит 15%
}
