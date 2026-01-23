"""
HTTP клиент для работы с микросервисом локальных эмбеддингов.
Обеспечивает совместимость с LangChain Embeddings интерфейсом.
"""

import logging
import os
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
import asyncio

import httpx

logger = logging.getLogger(__name__)


class HTTPEmbeddingsWrapper:
    """
    Обертка для HTTP API микросервиса эмбеддингов.
    Обеспечивает совместимость с LangChain Embeddings интерфейсом.
    """

    def __init__(self, base_url: Optional[str] = None):
        """
        Инициализация HTTP клиента для эмбеддингов.
        
        Args:
            base_url: URL микросервиса эмбеддингов (по умолчанию из переменной окружения)
        """
        self.base_url = base_url or os.getenv(
            "EMBEDDINGS_SERVICE_API",
            "http://embeddings-service:9094"
        )
        # Убираем завершающий слэш, если есть
        self.base_url = self.base_url.rstrip("/")
        self.timeout = 30.0
        
        logger.info(f"HTTPEmbeddingsWrapper инициализирован с URL: {self.base_url}")

    def embed_query(self, text: str) -> List[float]:
        """
        Синхронный метод для получения эмбеддинга одного текста.
        
        Args:
            text: Текст для эмбеддинга
            
        Returns:
            Список чисел (эмбеддинг)
        """
        # Используем ThreadPoolExecutor для выполнения async функции в синхронном контексте
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Если event loop уже запущен, используем ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, self.aembed_query(text))
                    return future.result(timeout=self.timeout)
            else:
                return loop.run_until_complete(self.aembed_query(text))
        except RuntimeError:
            # Если event loop не запущен, создаем новый
            return asyncio.run(self.aembed_query(text))

    async def aembed_query(self, text: str) -> List[float]:
        """
        Асинхронный метод для получения эмбеддинга одного текста.
        
        Args:
            text: Текст для эмбеддинга
            
        Returns:
            Список чисел (эмбеддинг)
        """
        url = f"{self.base_url}/api/embed_query"
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json={"text": text}
                )
                response.raise_for_status()
                data = response.json()
                return data["embedding"]
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP ошибка при получении эмбеддинга: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Ошибка при получении эмбеддинга: {e}")
            raise

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Синхронный метод для получения эмбеддингов нескольких текстов.
        
        Args:
            texts: Список текстов для эмбеддинга
            
        Returns:
            Список списков чисел (эмбеддинги)
        """
        # Используем ThreadPoolExecutor для выполнения async функции в синхронном контексте
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Если event loop уже запущен, используем ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, self.aembed_documents(texts))
                    return future.result(timeout=self.timeout * len(texts))
            else:
                return loop.run_until_complete(self.aembed_documents(texts))
        except RuntimeError:
            # Если event loop не запущен, создаем новый
            return asyncio.run(self.aembed_documents(texts))

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Асинхронный метод для получения эмбеддингов нескольких текстов.
        
        Args:
            texts: Список текстов для эмбеддинга
            
        Returns:
            Список списков чисел (эмбеддинги)
        """
        url = f"{self.base_url}/api/embed_documents"
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout * len(texts)) as client:
                response = await client.post(
                    url,
                    json={"texts": texts}
                )
                response.raise_for_status()
                data = response.json()
                return data["embeddings"]
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP ошибка при получении эмбеддингов: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Ошибка при получении эмбеддингов: {e}")
            raise
