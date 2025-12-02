"""
Middleware для автоматического извлечения user_id из токена аутентификации
и добавления его в config для всех запросов к графу
"""
import logging
from typing import Optional, Dict, Any
from fastapi import Request, Header
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from giga_agent.tasks_app import Session, User, AsyncSessionLocal
except ImportError:
    Session = None
    User = None
    AsyncSessionLocal = None

logger = logging.getLogger(__name__)


async def extract_user_id_from_token(
    authorization: Optional[str] = Header(None)
) -> Optional[str]:
    """
    Извлекает user_id из токена аутентификации в заголовке Authorization.
    
    Args:
        authorization: Заголовок Authorization в формате "Bearer <token>"
        
    Returns:
        user_id если токен валидный, иначе None
    """
    if not authorization:
        return None
    
    # Извлекаем токен из заголовка
    if not authorization.startswith("Bearer "):
        return None
    
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return None
    
    if not AsyncSessionLocal or not Session or not User:
        return None
    
    try:
        async with AsyncSessionLocal() as session:
            # Ищем сессию по токену
            result = await session.execute(
                select(Session).where(Session.token == token)
            )
            session_obj = result.scalar_one_or_none()
            
            if not session_obj:
                return None
            
            # Проверяем срок действия
            from datetime import datetime
            expires_at = datetime.fromisoformat(session_obj.expires_at)
            if datetime.now() > expires_at:
                return None
            
            # Возвращаем user_id
            return session_obj.user_id
    except Exception as e:
        logger.error(f"Ошибка при извлечении user_id из токена: {e}")
        return None


async def get_user_id_from_request(
    request: Request,
    config: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Извлекает user_id из запроса несколькими способами:
    1. Из заголовка X-User-ID (если передан фронтендом)
    2. Из токена в заголовке Authorization
    3. Из config.configurable.user_id (если передан)
    
    Args:
        request: FastAPI Request объект
        config: Конфигурация запроса (может содержать configurable)
        
    Returns:
        user_id если найден, иначе None
    """
    user_id = None
    
    # 1. Пытаемся извлечь из заголовка X-User-ID
    x_user_id = request.headers.get("X-User-ID")
    if x_user_id:
        user_id = x_user_id.strip()
        logger.debug(f"🔍 user_id извлечен из заголовка X-User-ID: {user_id}")
        return user_id
    
    # 2. Пытаемся извлечь из токена
    authorization = request.headers.get("Authorization")
    if authorization:
        user_id = await extract_user_id_from_token(authorization)
        if user_id:
            logger.debug(f"🔍 user_id извлечен из токена: {user_id}")
            return user_id
    
    # 3. Пытаемся извлечь из config
    if config:
        configurable = config.get("configurable", {})
        if isinstance(configurable, dict):
            user_id = configurable.get("user_id")
            if user_id:
                logger.debug(f"🔍 user_id извлечен из config.configurable: {user_id}")
                return user_id
    
    return None

