"""
Утилита для работы с облачным API эмбеддингов
Поддерживает Hugging Face Inference API, Cohere, OpenAI и другие сервисы
"""

import os
import logging
import httpx
from typing import List, Optional, Dict, Any
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class EmbeddingsProvider(ABC):
    """Базовый класс для провайдеров эмбеддингов"""
    
    @abstractmethod
    async def embed_query(self, text: str) -> List[float]:
        """Создает эмбеддинг для одного текста"""
        pass
    
    @abstractmethod
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Создает эмбеддинги для списка текстов"""
        pass


class HuggingFaceEmbeddingsProvider(EmbeddingsProvider):
    """Провайдер для Hugging Face Inference API"""
    
    def __init__(self, api_key: Optional[str] = None, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        # Используем стандартную переменную HF_TOKEN (совместима с huggingface_hub для STT)
        # Также поддерживаем HUGGINGFACE_API_KEY для обратной совместимости
        self.api_key = api_key or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HUGGINGFACE_HUB_TOKEN")
        self.model_name = model_name
        # Используем Inference API для embeddings
        # Старый endpoint api-inference.huggingface.co больше не поддерживается
        # Используем прямой endpoint модели (может работать через router автоматически)
        # Альтернатива: использовать Text Embeddings Inference API если доступен
        self.api_url = f"https://api-inference.huggingface.co/models/{model_name}"
        self.timeout = 30.0
        
        if not self.api_key:
            logger.warning("HF_TOKEN (или HUGGINGFACE_API_KEY) не установлен. Некоторые функции могут быть недоступны.")
    
    async def embed_query(self, text: str) -> List[float]:
        """Создает эмбеддинг для одного текста"""
        return (await self.embed_documents([text]))[0]
    
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Создает эмбеддинги для списка текстов"""
        if not self.api_key:
            raise ValueError("HF_TOKEN (или HUGGINGFACE_API_KEY) не установлен")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        results = []
        
        # Hugging Face API может обрабатывать несколько текстов за раз
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # Используем правильный формат для Inference API
                # Для sentence-transformers моделей отправляем тексты как inputs
                # Модель автоматически вернет эмбеддинги
                payload = {"inputs": texts}
                
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    json=payload
                )
                
                if response.status_code == 200:
                    embeddings = response.json()
                    # Обрабатываем разные форматы ответа
                    if isinstance(embeddings, list):
                        # Если список списков - это несколько эмбеддингов
                        if len(embeddings) > 0 and isinstance(embeddings[0], list):
                            results = embeddings
                        # Если список чисел - это один эмбеддинг
                        elif len(embeddings) > 0 and isinstance(embeddings[0], (int, float)):
                            results = [embeddings]
                        else:
                            results = embeddings if isinstance(embeddings[0], list) else [embeddings]
                    else:
                        # Если не список, оборачиваем в список
                        results = [embeddings] if not isinstance(embeddings, list) else embeddings
                elif response.status_code == 503:
                    # Модель загружается, ждем и повторяем
                    logger.info("Модель загружается, повторяем запрос через 10 секунд...")
                    import asyncio
                    await asyncio.sleep(10)
                    return await self.embed_documents(texts)
                elif response.status_code == 410:
                    # Старый endpoint больше не поддерживается
                    # Hugging Face изменил API, старый endpoint api-inference.huggingface.co больше не работает
                    # Для embeddings лучше использовать локальные модели или Inference Endpoints
                    error_msg = (
                        f"Hugging Face API endpoint больше не поддерживается (410). "
                        f"Старый endpoint api-inference.huggingface.co заменен на router API. "
                        f"Рекомендуется использовать локальные модели или настроить Inference Endpoints."
                    )
                    logger.warning(error_msg)
                    raise RuntimeError(error_msg)
                else:
                    error_msg = f"Ошибка Hugging Face API: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)
                    
            except httpx.TimeoutException:
                logger.error("Таймаут при запросе к Hugging Face API")
                raise
            except Exception as e:
                logger.error(f"Ошибка при запросе к Hugging Face API: {e}")
                raise
        
        return results


class CohereEmbeddingsProvider(EmbeddingsProvider):
    """Провайдер для Cohere Embed API"""
    
    def __init__(self, api_key: Optional[str] = None, model_name: str = "embed-multilingual-v3.0"):
        self.api_key = api_key or os.getenv("COHERE_API_KEY")
        self.model_name = model_name
        self.api_url = "https://api.cohere.ai/v1/embed"
        self.timeout = 30.0
        
        if not self.api_key:
            logger.warning("COHERE_API_KEY не установлен")
    
    async def embed_query(self, text: str) -> List[float]:
        """Создает эмбеддинг для одного текста"""
        return (await self.embed_documents([text]))[0]
    
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Создает эмбеддинги для списка текстов"""
        if not self.api_key:
            raise ValueError("COHERE_API_KEY не установлен")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Cohere поддерживает до 96 текстов за запрос
        batch_size = 96
        all_embeddings = []
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                
                try:
                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        json={
                            "texts": batch,
                            "model": self.model_name,
                            "input_type": "search_document" if len(batch) > 1 else "search_query"
                        }
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        all_embeddings.extend(data.get("embeddings", []))
                    else:
                        error_msg = f"Ошибка Cohere API: {response.status_code} - {response.text}"
                        logger.error(error_msg)
                        raise RuntimeError(error_msg)
                        
                except httpx.TimeoutException:
                    logger.error("Таймаут при запросе к Cohere API")
                    raise
                except Exception as e:
                    logger.error(f"Ошибка при запросе к Cohere API: {e}")
                    raise
        
        return all_embeddings


class OpenAIEmbeddingsProvider(EmbeddingsProvider):
    """Провайдер для OpenAI Embeddings API"""
    
    def __init__(self, api_key: Optional[str] = None, model_name: str = "text-embedding-3-small"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model_name
        self.api_url = "https://api.openai.com/v1/embeddings"
        self.timeout = 30.0
        
        # Настройки прокси для OpenAI API
        self.proxy_host = os.getenv("AI_PROXY_HOST")
        self.proxy_username = os.getenv("AI_PROXY_USERNAME")
        self.proxy_password = os.getenv("AI_PROXY_PASSWORD")
        self.proxy_port = os.getenv("AI_PROXY_PORT", "8080")  # Порт по умолчанию
        
        # Формируем URL прокси, если настройки есть
        self.proxy_url = None
        if self.proxy_host:
            # Проверяем, есть ли порт в host
            if ":" not in self.proxy_host:
                # Добавляем порт, если не указан
                proxy_address = f"{self.proxy_host}:{self.proxy_port}"
            else:
                proxy_address = self.proxy_host
            
            if self.proxy_username and self.proxy_password:
                # Прокси с аутентификацией
                # Экранируем специальные символы в username и password
                from urllib.parse import quote
                safe_username = quote(self.proxy_username, safe='')
                safe_password = quote(self.proxy_password, safe='')
                self.proxy_url = f"http://{safe_username}:{safe_password}@{proxy_address}"
            else:
                # Прокси без аутентификации
                self.proxy_url = f"http://{proxy_address}"
        
        if not self.api_key:
            logger.warning("OPENAI_API_KEY не установлен")
    
    async def embed_query(self, text: str) -> List[float]:
        """Создает эмбеддинг для одного текста"""
        return (await self.embed_documents([text]))[0]
    
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Создает эмбеддинги для списка текстов"""
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY не установлен")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # OpenAI поддерживает до 2048 текстов за запрос
        batch_size = 2048
        all_embeddings = []
        
        # Настраиваем прокси, если указан
        # В httpx прокси передается через параметр proxy (единственное число)
        # Можно передать строку для всех протоколов или словарь с ключами "http://" и "https://"
        proxy_config = None
        if self.proxy_url:
            # Используем строку - httpx автоматически применит для всех протоколов
            proxy_config = self.proxy_url
            logger.info(f"Используется прокси для OpenAI API: {self.proxy_host}")
        
        async with httpx.AsyncClient(timeout=self.timeout, proxy=proxy_config) as client:
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                
                try:
                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        json={
                            "input": batch,
                            "model": self.model_name
                        }
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        # Сортируем по индексу, так как OpenAI может вернуть в другом порядке
                        embeddings_dict = {item["index"]: item["embedding"] for item in data["data"]}
                        batch_embeddings = [embeddings_dict[i] for i in range(len(batch))]
                        all_embeddings.extend(batch_embeddings)
                    else:
                        error_msg = f"Ошибка OpenAI API: {response.status_code} - {response.text}"
                        logger.error(error_msg)
                        raise RuntimeError(error_msg)
                        
                except httpx.TimeoutException:
                    logger.error("Таймаут при запросе к OpenAI API")
                    raise
                except Exception as e:
                    logger.error(f"Ошибка при запросе к OpenAI API: {e}")
                    raise
        
        return all_embeddings


# Глобальный экземпляр провайдера
_embeddings_provider: Optional[EmbeddingsProvider] = None


def get_cloud_embeddings_provider() -> Optional[EmbeddingsProvider]:
    """
    Получает или создает экземпляр провайдера облачных эмбеддингов
    
    Приоритет выбора провайдера:
    1. HUGGINGFACE_API_KEY -> HuggingFaceEmbeddingsProvider
    2. COHERE_API_KEY -> CohereEmbeddingsProvider
    3. OPENAI_API_KEY -> OpenAIEmbeddingsProvider
    
    Returns:
        Экземпляр EmbeddingsProvider или None, если нет доступных API ключей
    """
    global _embeddings_provider
    
    if _embeddings_provider is not None:
        return _embeddings_provider
    
    # Определяем провайдера по наличию API ключей
    # Используем стандартную переменную HF_TOKEN (совместима с huggingface_hub для STT)
    huggingface_key = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HUGGINGFACE_HUB_TOKEN")
    cohere_key = os.getenv("COHERE_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if huggingface_key:
        logger.info("Используется Hugging Face Inference API для эмбеддингов")
        model_name = os.getenv("HUGGINGFACE_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        _embeddings_provider = HuggingFaceEmbeddingsProvider(api_key=huggingface_key, model_name=model_name)
    elif cohere_key:
        logger.info("Используется Cohere Embed API для эмбеддингов")
        model_name = os.getenv("COHERE_EMBEDDING_MODEL", "embed-multilingual-v3.0")
        _embeddings_provider = CohereEmbeddingsProvider(api_key=cohere_key, model_name=model_name)
    elif openai_key:
        logger.info("Используется OpenAI Embeddings API для эмбеддингов")
        model_name = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        _embeddings_provider = OpenAIEmbeddingsProvider(api_key=openai_key, model_name=model_name)
    else:
        logger.warning("Не найдены API ключи для облачных эмбеддингов. Установите HF_TOKEN (или HUGGINGFACE_API_KEY), COHERE_API_KEY или OPENAI_API_KEY")
        return None
    
    return _embeddings_provider


class CloudEmbeddingsWrapper:
    """
    Обертка для облачных эмбеддингов, совместимая с интерфейсом LangChain
    """
    
    def __init__(self, provider: EmbeddingsProvider):
        self.provider = provider
    
    def embed_query(self, text: str) -> List[float]:
        """Синхронный метод для совместимости с LangChain (использует asyncio)"""
        import asyncio
        import concurrent.futures
        
        # Проверяем, запущен ли event loop
        try:
            loop = asyncio.get_running_loop()
            # Если loop уже запущен, используем ThreadPoolExecutor для выполнения в отдельном потоке
            def run_async():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(self.provider.embed_query(text))
                finally:
                    new_loop.close()
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_async)
                return future.result()
        except RuntimeError:
            # Нет запущенного loop, создаем новый
            return asyncio.run(self.provider.embed_query(text))
    
    async def aembed_query(self, text: str) -> List[float]:
        """Асинхронный метод для создания эмбеддинга"""
        return await self.provider.embed_query(text)
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Синхронный метод для совместимости с LangChain"""
        import asyncio
        import concurrent.futures
        
        # Проверяем, запущен ли event loop
        try:
            loop = asyncio.get_running_loop()
            # Если loop уже запущен, используем ThreadPoolExecutor для выполнения в отдельном потоке
            def run_async():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(self.provider.embed_documents(texts))
                finally:
                    new_loop.close()
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_async)
                return future.result()
        except RuntimeError:
            # Нет запущенного loop, создаем новый
            return asyncio.run(self.provider.embed_documents(texts))
    
    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """Асинхронный метод для создания эмбеддингов"""
        return await self.provider.embed_documents(texts)
