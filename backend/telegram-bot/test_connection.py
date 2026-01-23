"""Тестовый скрипт для проверки подключения к LangGraph API"""
import asyncio
import os
import httpx
from langgraph_sdk import get_client

async def test_langgraph_connection():
    """Проверяет подключение к LangGraph API"""
    langgraph_url = os.getenv("LANGGRAPH_API_URL", "http://langgraph-api:8000")
    
    print(f"Проверка подключения к LangGraph API: {langgraph_url}")
    
    # Проверка через HTTP
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Пробуем разные эндпоинты
            endpoints = ["/health", "/", "/assistants"]
            for endpoint in endpoints:
                try:
                    url = f"{langgraph_url}{endpoint}"
                    response = await client.get(url, timeout=5.0)
                    print(f"  ✅ {endpoint}: {response.status_code}")
                except Exception as e:
                    print(f"  ❌ {endpoint}: {str(e)[:100]}")
    except Exception as e:
        print(f"❌ Ошибка HTTP подключения: {e}")
    
    # Проверка через LangGraph SDK
    try:
        client = get_client(url=langgraph_url)
        # Пробуем получить список ассистентов
        assistants = await client.assistants.list()
        print(f"✅ LangGraph SDK подключение успешно")
        print(f"   Найдено ассистентов: {len(assistants.get('assistants', []))}")
    except Exception as e:
        print(f"❌ Ошибка LangGraph SDK: {e}")

if __name__ == "__main__":
    asyncio.run(test_langgraph_connection())
