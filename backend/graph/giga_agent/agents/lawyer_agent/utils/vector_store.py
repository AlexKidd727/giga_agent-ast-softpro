"""
Утилиты для работы с векторным хранилищем (FAISS)
Поддерживает облачные API эмбеддингов (Hugging Face, Cohere, OpenAI) 
и внешний микросервис эмбеддингов (embeddings-service из d:\Python\mcp\)
"""

import logging
import sys
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

# Добавляем путь к виртуальному окружению, если он существует (для Docker)
venv_path = Path("/.venv/lib/python3.11/site-packages")
if venv_path.exists() and str(venv_path) not in sys.path:
    sys.path.insert(0, str(venv_path))

logger = logging.getLogger(__name__)

# Глобальные переменные для кэширования
_vector_store = None
_embeddings = None


def get_embeddings():
    """
    Получает или создает экземпляр embeddings для векторного поиска
    
    Приоритет:
    1. Облачные эмбеддинги (Hugging Face, Cohere, OpenAI) - если установлены API ключи
    2. Внешний микросервис эмбеддингов (embeddings-service из d:\Python\mcp\)
    
    Returns:
        Экземпляр embeddings (CloudEmbeddingsWrapper или HTTPEmbeddingsWrapper) или None
    """
    global _embeddings
    
    if _embeddings is not None:
        return _embeddings
    
    # Примечание: Сначала пробуем облачные эмбеддинги
    try:
        from giga_agent.agents.lawyer_agent.utils.cloud_embeddings import (
            get_cloud_embeddings_provider,
            CloudEmbeddingsWrapper
        )
        
        cloud_provider = get_cloud_embeddings_provider()
        if cloud_provider is not None:
            logger.info("Используются облачные эмбеддинги")
            _embeddings = CloudEmbeddingsWrapper(cloud_provider)
            
            # Тестируем облачные эмбеддинги
            try:
                test_text = "Тест эмбеддингов"
                test_embedding = _embeddings.embed_query(test_text)
                
                if test_embedding and len(test_embedding) > 0:
                    logger.info(f"Облачные эмбеддинги успешно инициализированы")
                    logger.info(f"Размер эмбеддинга: {len(test_embedding)}")
                    return _embeddings
            except Exception as e:
                error_msg = str(e)
                # Если это ошибка 410 (endpoint больше не поддерживается), логируем как предупреждение
                if "410" in error_msg or "endpoint больше не поддерживается" in error_msg:
                    logger.warning(f"Облачные эмбеддинги недоступны (старый endpoint больше не поддерживается): {e}")
                    logger.info("Переключаемся на локальные модели...")
                else:
                    logger.warning(f"Ошибка тестирования облачных эмбеддингов: {e}, пробуем локальные")
    except ImportError as e:
        logger.debug(f"Модуль cloud_embeddings недоступен: {e}")
    except Exception as e:
        logger.warning(f"Ошибка инициализации облачных эмбеддингов: {e}, пробуем локальные")
    
    # Примечание: Пробуем использовать внешний микросервис эмбеддингов (d:\Python\mcp\embeddings-service)
    logger.info("Пробуем подключиться к внешнему микросервису эмбеддингов...")
    try:
        from giga_agent.agents.lawyer_agent.utils.http_embeddings import HTTPEmbeddingsWrapper
        
        # Внешний сервис запускается отдельно из d:\Python\mcp\
        embeddings_service_url = os.getenv("EMBEDDINGS_SERVICE_API", "http://host.docker.internal:9094")
        http_embeddings = HTTPEmbeddingsWrapper(base_url=embeddings_service_url)
        
        # Тестируем микросервис
        try:
            test_text = "Тест эмбеддингов"
            test_embedding = http_embeddings.embed_query(test_text)
            
            if test_embedding and len(test_embedding) > 0:
                logger.info(f"Внешний микросервис эмбеддингов успешно подключен: {embeddings_service_url}")
                logger.info(f"Размер эмбеддинга: {len(test_embedding)}")
                _embeddings = http_embeddings
                return _embeddings
        except Exception as e:
            logger.error(f"Ошибка подключения к микросервису эмбеддингов ({embeddings_service_url}): {e}")
            logger.error("Убедитесь, что embeddings-service запущен из d:\\Python\\mcp\\")
    except ImportError as e:
        logger.debug(f"Модуль http_embeddings недоступен: {e}")
    except Exception as e:
        logger.error(f"Ошибка инициализации микросервиса эмбеддингов: {e}")
    
    logger.warning("Не удалось подключиться к эмбеддингам (ни облачным, ни через внешний микросервис)")
    logger.warning("Запустите embeddings-service из d:\\Python\\mcp\\ командой: docker-compose up -d embeddings-service")
    return None


def get_vector_store(create_if_missing: bool = True):
    """
    Загружает векторное хранилище из vector_store
    
    Args:
        create_if_missing: Если True и хранилища нет, создает его из БД
        
    Returns:
        Экземпляр FAISS или None, если не удалось загрузить
    """
    global _vector_store
    
    if _vector_store is not None:
        return _vector_store
    
    try:
        from giga_agent.agents.lawyer_agent.utils.paths import get_vector_store_folder
        
        vector_store_path = get_vector_store_folder()
        faiss_file = vector_store_path / "index.faiss"
        pkl_file = vector_store_path / "index.pkl"
        
        # Проверяем наличие файлов
        if not faiss_file.exists() or not pkl_file.exists():
            logger.warning(f"Файлы векторного хранилища не найдены в {vector_store_path}")
            if create_if_missing:
                logger.info("Создание векторного хранилища из статей БД...")
                try:
                    # Импортируем функцию создания векторного хранилища
                    from giga_agent.agents.lawyer_agent.utils.db_manager import create_vector_store_from_db
                    create_vector_store_from_db()
                    # Пробуем загрузить снова
                    if faiss_file.exists() and pkl_file.exists():
                        logger.info("Векторное хранилище создано, загружаем...")
                    else:
                        logger.warning("Не удалось создать векторное хранилище")
                        return None
                except Exception as e:
                    logger.error(f"Ошибка создания векторного хранилища: {e}")
                    import traceback
                    logger.error(f"Трассировка:\n{traceback.format_exc()}")
                    return None
            else:
                logger.info("Ожидаемые файлы: index.faiss, index.pkl")
                return None
        
        # Получаем embeddings
        embeddings = get_embeddings()
        if embeddings is None:
            logger.warning("Не удалось загрузить embeddings, векторный поиск недоступен")
            return None
        
        # Загружаем FAISS
        try:
            from langchain_community.vectorstores import FAISS
        except ImportError:
            from langchain.vectorstores import FAISS
        
        logger.info(f"Загрузка векторного хранилища из {vector_store_path}")
        _vector_store = FAISS.load_local(
            str(vector_store_path.absolute()),
            embeddings,
            allow_dangerous_deserialization=True
        )
        
        logger.info(f"Векторное хранилище успешно загружено. Размер: {_vector_store.index.ntotal}")
        return _vector_store
        
    except Exception as e:
        logger.error(f"Ошибка загрузки векторного хранилища: {e}")
        import traceback
        logger.error(f"Детали ошибки:\n{traceback.format_exc()}")
        return None


def vector_search(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Выполняет векторный поиск по запросу
    
    Args:
        query: Запрос для поиска
        top_k: Количество результатов для возврата
        
    Returns:
        Список найденных документов с метаданными
    """
    vector_store = get_vector_store()
    if vector_store is None:
        logger.warning("Векторное хранилище недоступно, возвращаем пустой список")
        return []
    
    try:
        # Выполняем поиск
        docs = vector_store.similarity_search_with_score(query, k=top_k)
        
        results = []
        for doc, score in docs:
            results.append({
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": float(score)
            })
        
        logger.info(f"Векторный поиск нашел {len(results)} документов")
        return results
        
    except Exception as e:
        logger.error(f"Ошибка при векторном поиске: {e}")
        return []

