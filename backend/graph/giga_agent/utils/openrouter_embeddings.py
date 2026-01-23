"""
Модуль для работы с эмбеддингами через OpenRouter.ai API

Поддерживает:
- Создание эмбеддингов для одного текста
- Создание эмбеддингов для списка текстов
- Совместимость с интерфейсом langchain Embeddings
"""

import os
import logging
import requests
from typing import List, Optional, Union
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# Попытка импорта базового класса из langchain
try:
    from langchain.embeddings.base import Embeddings
    LANGCHAIN_EMBEDDINGS_AVAILABLE = True
except ImportError:
    # Fallback для старых версий langchain
    try:
        from langchain_core.embeddings import Embeddings
        LANGCHAIN_EMBEDDINGS_AVAILABLE = True
    except ImportError:
        # Если langchain не установлен, создаем базовый класс
        class Embeddings(ABC):
            """Базовый класс для эмбеддингов"""
            @abstractmethod
            def embed_query(self, text: str) -> List[float]:
                """Создание эмбеддинга для одного текста"""
                pass
            
            @abstractmethod
            def embed_documents(self, texts: List[str]) -> List[List[float]]:
                """Создание эмбеддингов для списка текстов"""
                pass
        LANGCHAIN_EMBEDDINGS_AVAILABLE = False


class OpenRouterEmbeddings(Embeddings):
    """
    Класс для работы с эмбеддингами через OpenRouter.ai API
    
    Пример использования:
        embeddings = OpenRouterEmbeddings(
            api_key="sk-or-v1-...",
            model="openai/text-embedding-3-small"
        )
        vector = embeddings.embed_query("Привет, мир!")
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "openai/text-embedding-3-small",
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: int = 60,
        max_retries: int = 3,
        http_referer: Optional[str] = None,
        x_title: Optional[str] = None
    ):
        """
        Инициализация OpenRouterEmbeddings
        
        Args:
            api_key: API ключ OpenRouter (если None, берется из OPENROUTER_API_KEY)
            model: Идентификатор модели эмбеддингов (по умолчанию openai/text-embedding-3-small)
            base_url: Базовый URL API (по умолчанию https://openrouter.ai/api/v1)
            timeout: Таймаут запроса в секундах
            max_retries: Максимальное количество повторных попыток
            http_referer: HTTP-Referer заголовок (опционально)
            x_title: X-Title заголовок (опционально)
        """
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY не установлен. "
                "Установите его в переменных окружения для использования эмбеддингов OpenRouter."
            )
        
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        
        # Формируем заголовки
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        if http_referer:
            self.headers["HTTP-Referer"] = http_referer
        elif os.getenv("OPENROUTER_HTTP_REFERER"):
            self.headers["HTTP-Referer"] = os.getenv("OPENROUTER_HTTP_REFERER")
        
        if x_title:
            self.headers["X-Title"] = x_title
        elif os.getenv("OPENROUTER_X_TITLE"):
            self.headers["X-Title"] = os.getenv("OPENROUTER_X_TITLE")
        
        # URL для эмбеддингов
        self.embeddings_url = f"{self.base_url}/embeddings"
        
        logger.info(f"OpenRouterEmbeddings инициализирован с моделью {self.model}")
    
    def _create_embedding(
        self,
        input_data: Union[str, List[str]],
        retry_count: int = 0
    ) -> List[List[float]]:
        """
        Создание эмбеддингов через OpenRouter API
        
        Args:
            input_data: Текст или список текстов для создания эмбеддингов
            retry_count: Текущее количество попыток
            
        Returns:
            Список эмбеддингов (каждый эмбеддинг - список float)
        """
        payload = {
            "model": self.model,
            "input": input_data
        }
        
        try:
            response = requests.post(
                self.embeddings_url,
                headers=self.headers,
                json=payload,
                timeout=self.timeout
            )
            
            response.raise_for_status()
            data = response.json()
            
            # Проверяем структуру ответа
            if "data" not in data:
                raise ValueError(f"Неожиданная структура ответа API: {data}")
            
            # Извлекаем эмбеддинги
            embeddings = []
            for item in data["data"]:
                if "embedding" not in item:
                    raise ValueError(f"Эмбеддинг не найден в ответе: {item}")
                embeddings.append(item["embedding"])
            
            return embeddings
            
        except requests.exceptions.RequestException as e:
            if retry_count < self.max_retries:
                logger.warning(
                    f"Ошибка при создании эмбеддингов (попытка {retry_count + 1}/{self.max_retries}): {e}"
                )
                # Экспоненциальная задержка перед повтором
                import time
                time.sleep(2 ** retry_count)
                return self._create_embedding(input_data, retry_count + 1)
            else:
                logger.error(f"Не удалось создать эмбеддинги после {self.max_retries} попыток: {e}")
                raise RuntimeError(
                    f"Ошибка при создании эмбеддингов через OpenRouter API: {e}"
                ) from e
        except (ValueError, KeyError) as e:
            logger.error(f"Ошибка при обработке ответа API: {e}")
            raise RuntimeError(
                f"Ошибка при обработке ответа OpenRouter API: {e}"
            ) from e
    
    def embed_query(self, text: str) -> List[float]:
        """
        Создание эмбеддинга для одного текста
        
        Args:
            text: Текст для создания эмбеддинга
            
        Returns:
            Список чисел (вектор эмбеддинга)
        """
        if not text or not text.strip():
            raise ValueError("Текст не может быть пустым")
        
        embeddings = self._create_embedding(text)
        
        if not embeddings or len(embeddings) == 0:
            raise RuntimeError("API вернул пустой список эмбеддингов")
        
        return embeddings[0]
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Создание эмбеддингов для списка текстов
        
        Args:
            texts: Список текстов для создания эмбеддингов
            
        Returns:
            Список списков чисел (каждый внутренний список - вектор эмбеддинга)
        """
        if not texts:
            return []
        
        # Фильтруем пустые тексты
        non_empty_texts = [text for text in texts if text and text.strip()]
        
        if not non_empty_texts:
            raise ValueError("Все тексты пустые")
        
        # Если один текст, используем embed_query для совместимости
        if len(non_empty_texts) == 1:
            return [self.embed_query(non_empty_texts[0])]
        
        # Для нескольких текстов отправляем батч-запрос
        embeddings = self._create_embedding(non_empty_texts)
        
        if len(embeddings) != len(non_empty_texts):
            raise RuntimeError(
                f"Количество эмбеддингов ({len(embeddings)}) не совпадает с "
                f"количеством текстов ({len(non_empty_texts)})"
            )
        
        return embeddings
    
    async def aembed_query(self, text: str) -> List[float]:
        """
        Асинхронное создание эмбеддинга для одного текста
        
        Args:
            text: Текст для создания эмбеддинга
            
        Returns:
            Список чисел (вектор эмбеддинга)
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed_query, text)
    
    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Асинхронное создание эмбеддингов для списка текстов
        
        Args:
            texts: Список текстов для создания эмбеддингов
            
        Returns:
            Список списков чисел (каждый внутренний список - вектор эмбеддинга)
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed_documents, texts)


def load_openrouter_embeddings(
    model: Optional[str] = None,
    api_key: Optional[str] = None
) -> OpenRouterEmbeddings:
    """
    Функция для загрузки эмбеддингов OpenRouter
    
    Args:
        model: Идентификатор модели (если None, берется из GIGA_AGENT_EMBEDDINGS)
        api_key: API ключ (если None, берется из OPENROUTER_API_KEY)
    
    Returns:
        Экземпляр OpenRouterEmbeddings
    """
    # Если модель не указана, пытаемся извлечь из GIGA_AGENT_EMBEDDINGS
    if model is None:
        emb_str = os.getenv("GIGA_AGENT_EMBEDDINGS", "")
        if emb_str.startswith("openrouter:"):
            model = emb_str[len("openrouter:"):]
        elif emb_str.startswith("openrouter/"):
            model = emb_str[len("openrouter/"):]
        else:
            # Используем модель по умолчанию
            model = os.getenv("OPENROUTER_EMBEDDINGS_MODEL", "openai/text-embedding-3-small")
    
    return OpenRouterEmbeddings(api_key=api_key, model=model)
