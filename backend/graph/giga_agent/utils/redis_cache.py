"""
Утилита для кэширования user_id в Redis по thread_id и управления сеансами пользователей
Гарантирует постоянный доступ к user_id даже если он не передается в configurable

Структура данных в Redis:
- user_session:{user_id} -> JSON с информацией о сеансе пользователя
- thread_user_id:{thread_id} -> user_id (для быстрого поиска)
"""
import os
import json
import logging
from typing import Optional, List
from datetime import datetime, timedelta

try:
    import redis.asyncio as redis
except ImportError:
    try:
        import redis
        # Для синхронного redis создаем обертку
        redis = None
    except ImportError:
        redis = None

logger = logging.getLogger(__name__)
# Убеждаемся, что логирование настроено
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Глобальное подключение к Redis (инициализируется при первом использовании)
_redis_client = None


async def get_redis_client():
    """
    Получить клиент Redis. Создает подключение при первом вызове.
    
    Returns:
        Redis клиент или None, если Redis недоступен
    """
    global _redis_client
    
    if _redis_client is not None:
        return _redis_client
    
    if redis is None:
        logger.warning("⚠️ Redis библиотека не установлена, кэширование user_id недоступно")
        return None
    
    try:
        redis_uri = os.getenv("REDIS_URI", "redis://localhost:6379")
        logger.info(f"🔍 Попытка подключения к Redis: {redis_uri}")
        _redis_client = redis.from_url(redis_uri, decode_responses=True)
        # Проверяем подключение
        ping_result = await _redis_client.ping()
        if ping_result:
            logger.info("✅ Подключение к Redis установлено для кэширования user_id")
            # Проверяем, что можем записать и прочитать тестовое значение
            test_key = "redis_connection_test"
            await _redis_client.setex(test_key, 10, "test_value")
            test_value = await _redis_client.get(test_key)
            if test_value == "test_value":
                logger.info("✅ Redis работает корректно, тестовая запись/чтение успешны")
            else:
                logger.warning(f"⚠️ Redis подключен, но тестовая запись/чтение не прошли: получено '{test_value}' вместо 'test_value'")
            await _redis_client.delete(test_key)
        else:
            logger.error("❌ Redis ping вернул False")
            _redis_client = None
            return None
        return _redis_client
    except Exception as e:
        logger.error(f"❌ Не удалось подключиться к Redis для кэширования user_id: {e}", exc_info=True)
        _redis_client = None
        return None


async def cache_user_id_for_thread(thread_id: str, user_id: str, ttl: int = 86400) -> bool:
    """
    Сохранить user_id в Redis для конкретного thread_id.
    
    Args:
        thread_id: Идентификатор потока
        user_id: Идентификатор пользователя
        ttl: Время жизни кэша в секундах (по умолчанию 24 часа)
        
    Returns:
        True если успешно сохранено, False в противном случае
    """
    if not thread_id or not user_id:
        return False
    
    try:
        client = await get_redis_client()
        if not client:
            return False
        
        key = f"thread_user_id:{thread_id}"
        await client.setex(key, ttl, user_id)
        logger.debug(f"💾 user_id={user_id} сохранен в Redis для thread_id={thread_id} (TTL={ttl}s)")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении user_id в Redis: {e}")
        return False


async def get_user_id_from_thread_cache(thread_id: str) -> Optional[str]:
    """
    Получить user_id из Redis кэша по thread_id.
    
    Args:
        thread_id: Идентификатор потока
        
    Returns:
        user_id если найден в кэше, иначе None
    """
    if not thread_id:
        return None
    
    try:
        client = await get_redis_client()
        if not client:
            return None
        
        key = f"thread_user_id:{thread_id}"
        user_id = await client.get(key)
        
        if user_id:
            logger.debug(f"🔍 user_id={user_id} найден в Redis кэше для thread_id={thread_id}")
            return user_id
        else:
            logger.debug(f"🔍 user_id не найден в Redis кэше для thread_id={thread_id}")
            return None
    except Exception as e:
        logger.error(f"❌ Ошибка при получении user_id из Redis: {e}")
        return None


async def clear_user_id_cache(thread_id: str) -> bool:
    """
    Удалить user_id из кэша Redis для конкретного thread_id.
    
    Args:
        thread_id: Идентификатор потока
        
    Returns:
        True если успешно удалено, False в противном случае
    """
    if not thread_id:
        return False
    
    try:
        client = await get_redis_client()
        if not client:
            return False
        
        key = f"thread_user_id:{thread_id}"
        await client.delete(key)
        logger.debug(f"🗑️ user_id удален из Redis кэша для thread_id={thread_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении user_id из Redis: {e}")
        return False


# ========== УПРАВЛЕНИЕ СЕАНСАМИ ПОЛЬЗОВАТЕЛЕЙ ==========

async def create_user_session(user_id: str, ttl: int = 2592000) -> bool:
    """
    Создать сеанс пользователя в Redis при логине.
    Если сеанс уже существует, он будет перезаписан новым (с пустым списком потоков).
    
    Args:
        user_id: Идентификатор пользователя
        ttl: Время жизни сеанса в секундах (по умолчанию 30 дней)
        
    Returns:
        True если успешно создано, False в противном случае
    """
    logger.info(f"🔍 create_user_session вызвана: user_id={user_id}, ttl={ttl}")
    
    if not user_id:
        logger.warning("⚠️ create_user_session: user_id пустой, возвращаем False")
        return False
    
    try:
        client = await get_redis_client()
        if not client:
            logger.error("❌ create_user_session: Redis клиент недоступен")
            return False
        
        logger.info(f"🔍 create_user_session: Redis клиент получен, создаем сеанс для user_id={user_id}")
        
        session_key = f"user_session:{user_id}"
        
        # Проверяем, существует ли уже сеанс
        existing_session = await client.get(session_key)
        if existing_session:
            try:
                existing_data = json.loads(existing_session)
                existing_threads = existing_data.get("threads", [])
                logger.info(f"🔍 Обнаружен существующий сеанс для user_id={user_id} с {len(existing_threads)} потоками, перезаписываем")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"⚠️ Обнаружен существующий сеанс с некорректными данными для user_id={user_id}, перезаписываем. Ошибка: {e}")
        
        expires_at = (datetime.now() + timedelta(seconds=ttl)).isoformat()
        
        session_data = {
            "user_id": user_id,
            "threads": [],  # Список thread_id, связанных с этим сеансом (начинаем с пустого)
            "created_at": datetime.now().isoformat(),
            "expires_at": expires_at
        }
        
        session_json = json.dumps(session_data)
        logger.debug(f"🔍 create_user_session: Сохраняем данные: key={session_key}, data={session_json}")
        
        result = await client.setex(session_key, ttl, session_json)
        logger.info(f"✅ Сеанс пользователя создан в Redis: user_id={user_id}, expires_at={expires_at}, setex_result={result}")
        
        # Проверяем, что данные действительно сохранились
        verify_data = await client.get(session_key)
        if verify_data:
            logger.info(f"✅ create_user_session: Проверка сохранения успешна, данные в Redis: {verify_data[:100]}...")
        else:
            logger.error(f"❌ create_user_session: Данные не сохранились в Redis после setex!")
        
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при создании сеанса пользователя в Redis: {e}", exc_info=True)
        return False


async def add_thread_to_user_session(user_id: str, thread_id: str) -> bool:
    """
    Добавить thread_id в сеанс пользователя при создании потока.
    
    Args:
        user_id: Идентификатор пользователя
        thread_id: Идентификатор потока
        
    Returns:
        True если успешно добавлено, False в противном случае
    """
    if not user_id or not thread_id:
        return False
    
    try:
        client = await get_redis_client()
        if not client:
            return False
        
        session_key = f"user_session:{user_id}"
        
        # Получаем текущий сеанс
        session_json = await client.get(session_key)
        if not session_json:
            # Если сеанс не существует, создаем новый
            logger.warning(f"⚠️ Сеанс пользователя {user_id} не найден, создаем новый")
            await create_user_session(user_id)
            session_json = await client.get(session_key)
            if not session_json:
                return False
        
        session_data = json.loads(session_json)
        
        # Добавляем thread_id в список, если его еще нет
        if thread_id not in session_data.get("threads", []):
            session_data.setdefault("threads", []).append(thread_id)
            
            # Обновляем сеанс в Redis
            ttl = await client.ttl(session_key)
            if ttl > 0:
                await client.setex(session_key, ttl, json.dumps(session_data))
            else:
                # Если TTL истек, создаем новый сеанс
                await create_user_session(user_id)
                session_data = json.loads(await client.get(session_key))
                session_data.setdefault("threads", []).append(thread_id)
                await client.setex(session_key, 2592000, json.dumps(session_data))
            
            logger.info(f"✅ thread_id={thread_id} добавлен в сеанс пользователя user_id={user_id}")
        
        # Также сохраняем обратную связь thread_id -> user_id для быстрого поиска
        await cache_user_id_for_thread(thread_id, user_id)
        
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при добавлении thread_id в сеанс пользователя: {e}")
        return False


async def get_user_id_from_session_by_thread(thread_id: str) -> Optional[str]:
    """
    Получить user_id из сеанса пользователя по thread_id.
    Сначала проверяет прямую связь thread_id -> user_id, затем ищет в сеансах.
    
    Args:
        thread_id: Идентификатор потока
        
    Returns:
        user_id если найден, иначе None
    """
    if not thread_id:
        return None
    
    try:
        client = await get_redis_client()
        if not client:
            return None
        
        # Сначала проверяем прямую связь (быстрее)
        direct_key = f"thread_user_id:{thread_id}"
        user_id = await client.get(direct_key)
        if user_id:
            logger.debug(f"🔍 user_id={user_id} найден по прямой связи для thread_id={thread_id}")
            return user_id
        
        # Если прямой связи нет, ищем в сеансах пользователей
        # Получаем все ключи сеансов
        session_keys = await client.keys("user_session:*")
        
        for session_key in session_keys:
            session_json = await client.get(session_key)
            if not session_json:
                continue
            
            try:
                session_data = json.loads(session_json)
                threads = session_data.get("threads", [])
                
                if thread_id in threads:
                    user_id = session_data.get("user_id")
                    if user_id:
                        logger.info(f"✅ user_id={user_id} найден в сеансе для thread_id={thread_id}")
                        # Сохраняем прямую связь для будущих запросов
                        await cache_user_id_for_thread(thread_id, user_id)
                        return user_id
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"⚠️ Ошибка при парсинге сеанса {session_key}: {e}")
                continue
        
        logger.debug(f"🔍 user_id не найден в сеансах для thread_id={thread_id}")
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка при получении user_id из сеанса: {e}")
        return None


async def get_user_session(user_id: str) -> Optional[dict]:
    """
    Получить информацию о сеансе пользователя.
    
    Args:
        user_id: Идентификатор пользователя
        
    Returns:
        Словарь с данными сеанса или None
    """
    if not user_id:
        return None
    
    try:
        client = await get_redis_client()
        if not client:
            return None
        
        session_key = f"user_session:{user_id}"
        session_json = await client.get(session_key)
        
        if session_json:
            return json.loads(session_json)
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка при получении сеанса пользователя: {e}")
        return None


async def delete_user_session(user_id: str) -> bool:
    """
    Удалить сеанс пользователя из Redis (при выходе).
    
    Args:
        user_id: Идентификатор пользователя
        
    Returns:
        True если успешно удалено, False в противном случае
    """
    logger.info(f"🔍 delete_user_session вызвана: user_id={user_id}")
    
    if not user_id:
        logger.warning("⚠️ delete_user_session: user_id пустой, возвращаем False")
        return False
    
    try:
        client = await get_redis_client()
        if not client:
            logger.error("❌ delete_user_session: Redis клиент недоступен")
            return False
        
        logger.info(f"🔍 delete_user_session: Redis клиент получен, удаляем сеанс для user_id={user_id}")
        
        session_key = f"user_session:{user_id}"
        session_json = await client.get(session_key)
        
        if session_json:
            logger.info(f"🔍 delete_user_session: Найден сеанс для user_id={user_id}, удаляем")
            # Удаляем прямые связи thread_id -> user_id для всех потоков сеанса
            try:
                session_data = json.loads(session_json)
                threads = session_data.get("threads", [])
                logger.info(f"🔍 delete_user_session: Найдено {len(threads)} потоков в сеансе")
                
                for thread_id in threads:
                    await clear_user_id_cache(thread_id)
                    logger.debug(f"🔍 delete_user_session: Удалена прямая связь для thread_id={thread_id}")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"⚠️ delete_user_session: Ошибка при парсинге сеанса: {e}, продолжаем удаление")
            
            # Удаляем сам сеанс
            delete_result = await client.delete(session_key)
            logger.info(f"🗑️ Сеанс пользователя удален из Redis: user_id={user_id}, delete_result={delete_result}")
            
            # Проверяем, что сеанс действительно удален
            verify = await client.get(session_key)
            if verify is None:
                logger.info(f"✅ delete_user_session: Проверка удаления успешна, сеанс удален из Redis")
            else:
                logger.error(f"❌ delete_user_session: Сеанс не удален из Redis! Данные все еще присутствуют")
            
            return True
        else:
            logger.info(f"🔍 delete_user_session: Сеанс для user_id={user_id} не найден в Redis (возможно, уже удален)")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении сеанса пользователя: {e}", exc_info=True)
        return False

