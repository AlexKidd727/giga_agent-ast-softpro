"""
Глобальная система умного кэширования паттернов запросов пользователя
Запоминает успешные вызовы инструментов для конкретных запросов
Использует Redis для быстрого доступа и PostgreSQL для долговременного хранения

ГЛОБАЛЬНОЕ КЭШИРОВАНИЕ:
- Работает для ВСЕХ агентов и инструментов (tinkoff, email, calendar и др.)
- Интегрируется в tool_graph.py на уровне classify_request -> before_agent
- При повторных запросах пропускает LLM и вызывает инструмент напрямую

Структура:
- Redis: быстрый доступ к кэшу (TTL: 1 час)
- PostgreSQL: долговременное хранение паттернов и инструментов

Метрики производительности:
- Логирует время выполнения для анализа ускорения
- Отмечает cache hit/miss для мониторинга эффективности
"""

import os
import json
import hashlib
import logging
import re
import time
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, field

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, Index, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from giga_agent.utils.redis_cache import get_redis_client

logger = logging.getLogger(__name__)
# Убеждаемся, что логирование настроено
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# База для моделей
Base = declarative_base()


class QueryPatternCache(Base):
    """Модель для хранения паттернов запросов и соответствующих инструментов"""
    __tablename__ = "query_pattern_cache"
    
    id = Column(Integer, primary_key=True, index=True)
    # Хэш паттерна запроса для быстрого поиска
    pattern_hash = Column(String(64), unique=True, nullable=False, index=True)
    # Нормализованный паттерн запроса (нижний регистр, без лишних пробелов)
    pattern_normalized = Column(Text, nullable=False, index=True)
    # Оригинальный пример запроса
    original_query = Column(Text, nullable=False)
    # Название инструмента, который успешно использовался
    tool_name = Column(String(255), nullable=False, index=True)
    # Параметры инструмента в JSON формате
    tool_params = Column(Text, nullable=True)
    # Количество успешных использований
    success_count = Column(Integer, default=0, nullable=False)
    # Количество неудачных использований (если паттерн перестал работать)
    failure_count = Column(Integer, default=0, nullable=False)
    # Последнее успешное использование
    last_success_at = Column(DateTime, nullable=True)
    # Дата создания записи
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Дата последнего обновления
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    # Активна ли запись (можно отключить, если паттерн перестал работать)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    # Идентификатор пользователя (опционально, для персональных паттернов)
    user_id = Column(String(255), nullable=True, index=True)
    # Среднее время выполнения инструмента (для метрик)
    avg_execution_time_ms = Column(Float, nullable=True)
    # Категория/агент инструмента (tinkoff, email, calendar и т.д.)
    tool_category = Column(String(100), nullable=True, index=True)
    
    # Индексы для быстрого поиска
    __table_args__ = (
        Index('idx_pattern_hash_active', 'pattern_hash', 'is_active'),
        Index('idx_user_pattern', 'user_id', 'pattern_hash'),
        Index('idx_tool_name_active', 'tool_name', 'is_active'),
        Index('idx_tool_category', 'tool_category', 'is_active'),
    )


@dataclass
class CachedToolCall:
    """Структура данных для кэшированного вызова инструмента"""
    tool_name: str
    tool_params: Dict[str, Any]
    pattern_hash: str
    success_count: int
    last_success_at: Optional[datetime]
    avg_execution_time_ms: Optional[float] = None
    tool_category: Optional[str] = None
    cache_source: str = "unknown"  # "redis" или "postgres" - откуда был получен кэш


@dataclass
class CacheMetrics:
    """Метрики производительности кэша"""
    cache_hit: bool = False
    cache_source: Optional[str] = None  # "redis", "postgres", None
    lookup_time_ms: float = 0.0
    tool_execution_time_ms: float = 0.0
    total_time_ms: float = 0.0
    saved_time_ms: float = 0.0  # Примерная экономия времени (vs LLM call)


class QueryPatternCacheService:
    """Сервис для работы с кэшем паттернов запросов"""
    
    def __init__(self):
        self.redis_prefix = "query_pattern_cache:"
        self.redis_ttl = 3600  # 1 час в Redis
        self._sync_engine = None
        self._async_engine = None
        self._sync_session = None
        self._async_session = None
    
    def _get_sync_engine(self):
        """Получить синхронный движок PostgreSQL"""
        if self._sync_engine is None:
            database_url = os.getenv(
                "DATABASE_URL",
                "postgresql+asyncpg://postgres:postgres@aegra-postgres:5432/postgres"
            )
            sync_url = database_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
            self._sync_engine = create_engine(sync_url, echo=False)
            # Создаем таблицу, если её нет
            Base.metadata.create_all(bind=self._sync_engine)
        return self._sync_engine
    
    def _get_sync_session(self) -> Session:
        """Получить синхронную сессию PostgreSQL"""
        if self._sync_session is None:
            engine = self._get_sync_engine()
            SessionLocal = sessionmaker(bind=engine)
            self._sync_session = SessionLocal()
        return self._sync_session
    
    async def _get_async_engine(self):
        """Получить асинхронный движок PostgreSQL"""
        if self._async_engine is None:
            database_url = os.getenv(
                "DATABASE_URL",
                "postgresql+asyncpg://postgres:postgres@aegra-postgres:5432/postgres"
            )
            self._async_engine = create_async_engine(database_url, echo=False)
            # Создаем таблицу, если её нет (асинхронно)
            async with self._async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        return self._async_engine
    
    async def _get_async_session(self) -> AsyncSession:
        """Получить асинхронную сессию PostgreSQL"""
        if self._async_session is None:
            engine = await self._get_async_engine()
            AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
            self._async_session = AsyncSessionLocal()
        return self._async_session
    
    @staticmethod
    def normalize_query(query: str) -> str:
        """
        Нормализует запрос для сравнения:
        - Извлекает только текст запроса пользователя (удаляет системные промпты)
        - Приводит к нижнему регистру
        - Убирает лишние пробелы
        - Заменяет множественные пробелы на один
        """
        if not query:
            return ""
        
        # Извлекаем текст из тега <task>...</task> если он есть
        task_match = re.search(r'<task>(.*?)</task>', query, re.IGNORECASE | re.DOTALL)
        if task_match:
            query = task_match.group(1)
        else:
            # Если нет тега <task>, пробуем убрать системные промпты другими способами
            # Убираем все что после <user_info>, <system>, </task> и подобных тегов
            query = re.sub(r'<user_info>.*', '', query, flags=re.IGNORECASE | re.DOTALL)
            query = re.sub(r'<system>.*', '', query, flags=re.IGNORECASE | re.DOTALL)
            query = re.sub(r'активно планируй.*', '', query, flags=re.IGNORECASE | re.DOTALL)
        
        normalized = query.lower().strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized
    
    @staticmethod
    def calculate_pattern_hash(normalized_query: str, user_id: Optional[str] = None) -> str:
        """
        Вычисляет хэш паттерна запроса
        
        Args:
            normalized_query: Нормализованный запрос
            user_id: Идентификатор пользователя (опционально)
        
        Returns:
            SHA256 хэш в hex формате
        """
        # Если указан user_id, включаем его в хэш для персональных паттернов
        if user_id:
            data = f"{user_id}:{normalized_query}"
        else:
            data = normalized_query
        return hashlib.sha256(data.encode('utf-8')).hexdigest()
    
    async def get_cached_tool(
        self,
        query: str,
        user_id: Optional[str] = None
    ) -> Tuple[Optional[CachedToolCall], CacheMetrics]:
        """
        Получить кэшированный инструмент для запроса
        
        Args:
            query: Запрос пользователя
            user_id: Идентификатор пользователя (опционально)
        
        Returns:
            Tuple[CachedToolCall или None, CacheMetrics] - кэш и метрики поиска
        """
        start_time = time.time()
        metrics = CacheMetrics()
        
        try:
            # Нормализуем запрос
            normalized = self.normalize_query(query)
            pattern_hash = self.calculate_pattern_hash(normalized, user_id)
            
            # Сначала проверяем Redis (быстрый доступ)
            redis_client = await get_redis_client()
            if redis_client:
                redis_key = f"{self.redis_prefix}{pattern_hash}"
                cached_data = await redis_client.get(redis_key)
                if cached_data:
                    try:
                        data = json.loads(cached_data)
                        metrics.cache_hit = True
                        metrics.cache_source = "redis"
                        metrics.lookup_time_ms = (time.time() - start_time) * 1000
                        
                        logger.info(f"[QUERY_CACHE] CACHE HIT (Redis) tool='{data['tool_name']}' query='{normalized[:50]}...' lookup={metrics.lookup_time_ms:.1f}ms")
                        
                        return CachedToolCall(
                            tool_name=data['tool_name'],
                            tool_params=data['tool_params'],
                            pattern_hash=pattern_hash,
                            success_count=data.get('success_count', 0),
                            last_success_at=datetime.fromisoformat(data['last_success_at']) if data.get('last_success_at') else None,
                            avg_execution_time_ms=data.get('avg_execution_time_ms'),
                            tool_category=data.get('tool_category'),
                            cache_source="redis"
                        ), metrics
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"[QUERY_CACHE] Ошибка парсинга данных из Redis: {e}")
            
            # Если в Redis нет, проверяем PostgreSQL
            async_session = await self._get_async_session()
            try:
                from sqlalchemy import select
                result = await async_session.execute(
                    select(QueryPatternCache).where(
                        QueryPatternCache.pattern_hash == pattern_hash,
                        QueryPatternCache.is_active == True
                    )
                )
                cached_record = result.scalar_one_or_none()
                
                if cached_record:
                    metrics.cache_hit = True
                    metrics.cache_source = "postgres"
                    metrics.lookup_time_ms = (time.time() - start_time) * 1000
                    
                    logger.info(f"[QUERY_CACHE] CACHE HIT (PostgreSQL) tool='{cached_record.tool_name}' query='{normalized[:50]}...' lookup={metrics.lookup_time_ms:.1f}ms success_count={cached_record.success_count}")
                    
                    # Сохраняем в Redis для быстрого доступа
                    if redis_client:
                        redis_key = f"{self.redis_prefix}{pattern_hash}"
                        cache_data = {
                            'tool_name': cached_record.tool_name,
                            'tool_params': json.loads(cached_record.tool_params) if cached_record.tool_params else {},
                            'pattern_hash': pattern_hash,
                            'success_count': cached_record.success_count,
                            'last_success_at': cached_record.last_success_at.isoformat() if cached_record.last_success_at else None,
                            'avg_execution_time_ms': cached_record.avg_execution_time_ms,
                            'tool_category': cached_record.tool_category
                        }
                        await redis_client.setex(
                            redis_key,
                            self.redis_ttl,
                            json.dumps(cache_data)
                        )
                    
                    return CachedToolCall(
                        tool_name=cached_record.tool_name,
                        tool_params=json.loads(cached_record.tool_params) if cached_record.tool_params else {},
                        pattern_hash=pattern_hash,
                        success_count=cached_record.success_count,
                        last_success_at=cached_record.last_success_at,
                        avg_execution_time_ms=cached_record.avg_execution_time_ms,
                        tool_category=cached_record.tool_category,
                        cache_source="postgres"
                    ), metrics
            finally:
                await async_session.close()
            
            metrics.lookup_time_ms = (time.time() - start_time) * 1000
            logger.info(f"[QUERY_CACHE] CACHE MISS query='{normalized[:50]}...' lookup={metrics.lookup_time_ms:.1f}ms")
            return None, metrics
            
        except Exception as e:
            metrics.lookup_time_ms = (time.time() - start_time) * 1000
            logger.error(f"[QUERY_CACHE] Ошибка при получении кэша: {e}", exc_info=True)
            return None, metrics
    
    async def save_successful_tool_call(
        self,
        query: str,
        tool_name: str,
        tool_params: Dict[str, Any],
        user_id: Optional[str] = None,
        is_success: bool = True,
        execution_time_ms: Optional[float] = None,
        tool_category: Optional[str] = None
    ) -> bool:
        """
        Сохранить успешный вызов инструмента для запроса
        
        Args:
            query: Запрос пользователя
            tool_name: Название инструмента
            tool_params: Параметры инструмента
            user_id: Идентификатор пользователя (опционально)
            is_success: Успешен ли вызов (True) или неудачен (False)
            execution_time_ms: Время выполнения инструмента в мс (для метрик)
            tool_category: Категория инструмента (tinkoff, email, calendar и т.д.)
        
        Returns:
            True если успешно сохранено, False в противном случае
        """
        try:
            # Нормализуем запрос
            normalized = self.normalize_query(query)
            pattern_hash = self.calculate_pattern_hash(normalized, user_id)
            
            # Автоопределение категории по имени инструмента, если не указана
            if not tool_category:
                tool_category = self._detect_tool_category(tool_name)
            
            async_session = await self._get_async_session()
            try:
                from sqlalchemy import select
                
                # Ищем существующую запись
                result = await async_session.execute(
                    select(QueryPatternCache).where(
                        QueryPatternCache.pattern_hash == pattern_hash
                    )
                )
                cached_record = result.scalar_one_or_none()
                
                if cached_record:
                    # Обновляем существующую запись
                    if is_success:
                        cached_record.success_count += 1
                        cached_record.last_success_at = datetime.utcnow()
                        cached_record.failure_count = 0  # Сбрасываем счетчик неудач при успехе
                        
                        # Обновляем среднее время выполнения
                        if execution_time_ms is not None:
                            if cached_record.avg_execution_time_ms is not None:
                                # Скользящее среднее
                                cached_record.avg_execution_time_ms = (
                                    cached_record.avg_execution_time_ms * 0.8 + execution_time_ms * 0.2
                                )
                            else:
                                cached_record.avg_execution_time_ms = execution_time_ms
                        
                        logger.info(f"[QUERY_CACHE] CACHE UPDATE tool='{tool_name}' query='{normalized[:50]}...' success_count={cached_record.success_count} exec_time={execution_time_ms:.1f}ms" if execution_time_ms else f"[QUERY_CACHE] CACHE UPDATE tool='{tool_name}' query='{normalized[:50]}...' success_count={cached_record.success_count}")
                    else:
                        cached_record.failure_count += 1
                        # Если слишком много неудач, деактивируем паттерн
                        if cached_record.failure_count >= 3:
                            cached_record.is_active = False
                            logger.warning(f"[QUERY_CACHE] Паттерн деактивирован из-за множественных неудач: {normalized[:50]}...")
                    
                    cached_record.updated_at = datetime.utcnow()
                    if not cached_record.tool_params or cached_record.tool_name != tool_name:
                        cached_record.tool_name = tool_name
                        cached_record.tool_params = json.dumps(tool_params)
                    
                    # Обновляем категорию, если указана
                    if tool_category and not cached_record.tool_category:
                        cached_record.tool_category = tool_category
                else:
                    # Создаем новую запись
                    if is_success:
                        cached_record = QueryPatternCache(
                            pattern_hash=pattern_hash,
                            pattern_normalized=normalized,
                            original_query=query,
                            tool_name=tool_name,
                            tool_params=json.dumps(tool_params),
                            success_count=1,
                            failure_count=0,
                            last_success_at=datetime.utcnow(),
                            is_active=True,
                            user_id=user_id,
                            avg_execution_time_ms=execution_time_ms,
                            tool_category=tool_category
                        )
                        async_session.add(cached_record)
                        logger.info(f"[QUERY_CACHE] CACHE NEW tool='{tool_name}' category='{tool_category}' query='{normalized[:50]}...' exec_time={execution_time_ms:.1f}ms" if execution_time_ms else f"[QUERY_CACHE] CACHE NEW tool='{tool_name}' category='{tool_category}' query='{normalized[:50]}...'")
                    else:
                        # Не создаем запись для неудачных вызовов
                        logger.debug(f"[QUERY_CACHE] Пропущено сохранение неудачного вызова для нового паттерна: {normalized[:50]}...")
                        return False
                
                await async_session.commit()
                
                # Обновляем Redis
                redis_client = await get_redis_client()
                if redis_client and cached_record:
                    redis_key = f"{self.redis_prefix}{pattern_hash}"
                    cache_data = {
                        'tool_name': cached_record.tool_name,
                        'tool_params': json.loads(cached_record.tool_params) if cached_record.tool_params else {},
                        'pattern_hash': pattern_hash,
                        'success_count': cached_record.success_count,
                        'last_success_at': cached_record.last_success_at.isoformat() if cached_record.last_success_at else None,
                        'avg_execution_time_ms': cached_record.avg_execution_time_ms,
                        'tool_category': cached_record.tool_category
                    }
                    await redis_client.setex(
                        redis_key,
                        self.redis_ttl,
                        json.dumps(cache_data)
                    )
                
                return True
                
            finally:
                await async_session.close()
                
        except Exception as e:
            logger.error(f"[QUERY_CACHE] Ошибка при сохранении кэша: {e}", exc_info=True)
            return False
    
    @staticmethod
    def _detect_tool_category(tool_name: str) -> str:
        """Определяет категорию инструмента по его имени"""
        tool_name_lower = tool_name.lower()
        
        # Tinkoff/Trading инструменты
        if any(kw in tool_name_lower for kw in ['portfolio', 'tinkoff', 'position', 'balance', 'order', 'instrument', 'operation', 'ticker', 'chart']):
            return 'tinkoff'
        
        # Email инструменты
        if any(kw in tool_name_lower for kw in ['email', 'mail', 'smtp', 'imap', 'inbox']):
            return 'email'
        
        # Calendar инструменты
        if any(kw in tool_name_lower for kw in ['calendar', 'event', 'meeting', 'schedule']):
            return 'calendar'
        
        # Code/Python инструменты
        if any(kw in tool_name_lower for kw in ['python', 'code', 'repl', 'execute']):
            return 'code'
        
        # File инструменты
        if any(kw in tool_name_lower for kw in ['file', 'read', 'write', 'upload', 'download']):
            return 'file'
        
        # Web/Search инструменты
        if any(kw in tool_name_lower for kw in ['web', 'search', 'browser', 'scrape']):
            return 'web'
        
        # GitHub инструменты
        if any(kw in tool_name_lower for kw in ['github', 'git', 'repo', 'commit']):
            return 'github'
        
        return 'other'
    
    async def find_similar_pattern(
        self,
        query: str,
        user_id: Optional[str] = None,
        similarity_threshold: float = 0.7
    ) -> Optional[CachedToolCall]:
        """
        Найти похожий паттерн в кэше (для случаев, когда точного совпадения нет)
        
        Args:
            query: Запрос пользователя
            user_id: Идентификатор пользователя (опционально)
            similarity_threshold: Порог схожести (0.0-1.0)
        
        Returns:
            CachedToolCall или None
        """
        # TODO: Реализовать поиск похожих паттернов с использованием
        # алгоритмов схожести строк (например, Levenshtein distance)
        # Пока возвращаем None
        return None
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """
        Получить статистику кэша
        
        Returns:
            Словарь со статистикой
        """
        try:
            async_session = await self._get_async_session()
            try:
                from sqlalchemy import select, func
                
                # Общее количество записей
                total_result = await async_session.execute(
                    select(func.count(QueryPatternCache.id))
                )
                total_count = total_result.scalar() or 0
                
                # Активные записи
                active_result = await async_session.execute(
                    select(func.count(QueryPatternCache.id)).where(QueryPatternCache.is_active == True)
                )
                active_count = active_result.scalar() or 0
                
                # По категориям
                category_result = await async_session.execute(
                    select(
                        QueryPatternCache.tool_category,
                        func.count(QueryPatternCache.id),
                        func.sum(QueryPatternCache.success_count)
                    ).where(QueryPatternCache.is_active == True).group_by(QueryPatternCache.tool_category)
                )
                categories = {}
                for row in category_result:
                    cat_name = row[0] or 'unknown'
                    categories[cat_name] = {
                        'patterns': row[1],
                        'total_hits': row[2] or 0
                    }
                
                return {
                    'total_patterns': total_count,
                    'active_patterns': active_count,
                    'categories': categories
                }
            finally:
                await async_session.close()
        except Exception as e:
            logger.error(f"[QUERY_CACHE] Ошибка при получении статистики: {e}")
            return {'error': str(e)}


# Глобальный экземпляр сервиса
_cache_service = None


def get_cache_service() -> QueryPatternCacheService:
    """Получить глобальный экземпляр сервиса кэширования"""
    global _cache_service
    if _cache_service is None:
        _cache_service = QueryPatternCacheService()
    return _cache_service


async def check_query_cache(query: str, user_id: Optional[str] = None) -> Tuple[Optional[CachedToolCall], CacheMetrics]:
    """
    Удобная функция для проверки кэша запроса
    
    Args:
        query: Запрос пользователя
        user_id: Идентификатор пользователя (опционально)
    
    Returns:
        Tuple[CachedToolCall или None, CacheMetrics]
    """
    cache_service = get_cache_service()
    return await cache_service.get_cached_tool(query, user_id)


async def save_to_query_cache(
    query: str,
    tool_name: str,
    tool_params: Dict[str, Any],
    user_id: Optional[str] = None,
    execution_time_ms: Optional[float] = None,
    tool_category: Optional[str] = None
) -> bool:
    """
    Удобная функция для сохранения в кэш запроса
    
    Args:
        query: Запрос пользователя
        tool_name: Название инструмента
        tool_params: Параметры инструмента
        user_id: Идентификатор пользователя (опционально)
        execution_time_ms: Время выполнения в мс
        tool_category: Категория инструмента
    
    Returns:
        True если успешно сохранено
    """
    cache_service = get_cache_service()
    return await cache_service.save_successful_tool_call(
        query=query,
        tool_name=tool_name,
        tool_params=tool_params,
        user_id=user_id,
        is_success=True,
        execution_time_ms=execution_time_ms,
        tool_category=tool_category
    )
