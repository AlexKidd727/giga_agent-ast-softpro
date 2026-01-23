#!/usr/bin/env python3
"""Тест HTTP API для работы с куками"""
import asyncio
import aiohttp
import json

async def test_http_api():
    """Тестирует HTTP API endpoints"""
    base_url = "http://localhost:7071/api/cookies"
    
    async with aiohttp.ClientSession() as session:
        # Тест 1: Получение куков (должно быть пусто)
        print("1. Тест GET /api/cookies/get")
        async with session.get(f"{base_url}/get?session_id=test") as resp:
            data = await resp.json()
            print(f"   Ответ: {json.dumps(data, indent=2, ensure_ascii=False)}")
            assert data["success"] == True
            assert data["cookies_count"] == 0
        
        # Тест 2: Установка куков
        print("\n2. Тест POST /api/cookies/set")
        test_cookies = [
            {
                "name": "test_cookie",
                "value": "test_value",
                "domain": "example.com",
                "path": "/"
            }
        ]
        async with session.post(
            f"{base_url}/set",
            json={
                "session_id": "test",
                "cookies": test_cookies,
                "siteUrl": "https://example.com"
            }
        ) as resp:
            data = await resp.json()
            print(f"   Ответ: {json.dumps(data, indent=2, ensure_ascii=False)}")
            assert data["success"] == True
            assert data["cookies_count"] == 1
        
        # Тест 3: Получение установленных куков
        print("\n3. Тест GET /api/cookies/get (после установки)")
        async with session.get(f"{base_url}/get?session_id=test") as resp:
            data = await resp.json()
            print(f"   Ответ: {json.dumps(data, indent=2, ensure_ascii=False)}")
            assert data["success"] == True
            assert data["cookies_count"] == 1
            assert len(data["cookies"]) == 1
            assert data["cookies"][0]["name"] == "test_cookie"
        
        print("\n✅ Все тесты пройдены успешно!")

if __name__ == "__main__":
    asyncio.run(test_http_api())

