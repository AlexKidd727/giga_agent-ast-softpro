"""
Менеджер OAuth авторизации для Google Calendar
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
import httpx

from ..config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_SCOPES,
    GOOGLE_OAUTH_DEVICE_ENDPOINT,
    GOOGLE_OAUTH_TOKEN_ENDPOINT
)
from .storage import storage

logger = logging.getLogger(__name__)

class OAuthManager:
    """Управление OAuth авторизацией для Google Calendar"""
    
    def __init__(self):
        self.client_id = GOOGLE_CLIENT_ID
        self.client_secret = GOOGLE_CLIENT_SECRET
        self.scopes = " ".join(GOOGLE_SCOPES)
    
    async def start_device_flow(self, user_id: str) -> Dict[str, Any]:
        """Инициация Device Flow для авторизации"""
        if not self.client_id:
            return {
                "error": "Google Client ID не настроен",
                "details": "Добавьте GOOGLE_CLIENT_ID в переменные окружения"
            }
        
        try:
            data = {
                'client_id': self.client_id,
                'scope': self.scopes
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(GOOGLE_OAUTH_DEVICE_ENDPOINT, data=data)
                
                if response.status_code != 200:
                    error_text = response.text
                    logger.error(f"Ошибка Device Flow: {response.status_code} {error_text}")
                    return {
                        "error": f"Ошибка инициации авторизации: {response.status_code}",
                        "details": error_text
                    }
                
                device_data = response.json()
                
                # Сохраняем данные Device Flow
                storage.save_device_code(user_id, device_data)
                
                return {
                    "success": True,
                    "user_code": device_data.get('user_code'),
                    "verification_url": device_data.get('verification_url', device_data.get('verification_uri')),
                    "expires_in": device_data.get('expires_in', 1800),
                    "interval": device_data.get('interval', 5)
                }
                
        except Exception as e:
            logger.error(f"Ошибка Device Flow: {e}")
            return {
                "error": "Ошибка соединения с Google",
                "details": str(e)
            }
    
    async def poll_device_token(self, user_id: str) -> Dict[str, Any]:
        """Опрос токена в рамках Device Flow"""
        device_data = storage.get_device_code(user_id)
        
        if not device_data:
            return {
                "error": "Device Flow не инициирован",
                "details": "Сначала используйте start_device_flow"
            }
        
        device_code = device_data.get('device_code')
        if not device_code:
            return {
                "error": "Device code не найден",
                "details": "Данные Device Flow повреждены"
            }
        
        try:
            data = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'device_code': device_code,
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(GOOGLE_OAUTH_TOKEN_ENDPOINT, data=data)
                response_data = response.json()
                
                if response.status_code != 200:
                    error = response_data.get('error', 'unknown_error')
                    
                    if error in ['authorization_pending', 'slow_down']:
                        return {
                            "pending": True,
                            "message": "⏳ Подтвердите доступ на странице Google и повторите запрос"
                        }
                    
                    return {
                        "error": f"Ошибка авторизации: {error}",
                        "details": response_data.get('error_description', 'Неизвестная ошибка')
                    }
                
                # Успешная авторизация - сохраняем токены
                storage.save_user_tokens(user_id, response_data)
                storage.clear_device_code(user_id)
                
                return {
                    "success": True,
                    "message": "✅ Авторизация завершена успешно"
                }
                
        except Exception as e:
            logger.error(f"Ошибка опроса токена: {e}")
            return {
                "error": "Ошибка получения токена",
                "details": str(e)
            }
    
    async def refresh_access_token(self, user_id: str) -> Optional[str]:
        """Обновление токена доступа"""
        tokens = storage.get_user_tokens(user_id)
        
        if not tokens or 'refresh_token' not in tokens:
            logger.warning(f"Нет refresh_token для пользователя {user_id}")
            return None
        
        try:
            data = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'refresh_token': tokens['refresh_token'],
                'grant_type': 'refresh_token'
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(GOOGLE_OAUTH_TOKEN_ENDPOINT, data=data)
                
                if response.status_code != 200:
                    error_text = response.text
                    logger.error(f"Ошибка обновления токена: {response.status_code} {error_text}")
                    return None
                
                token_data = response.json()
                
                if 'error' in token_data:
                    logger.error(f"Ошибка обновления токена: {token_data}")
                    return None
                
                # Обновляем токены
                updated_tokens = tokens.copy()
                updated_tokens['access_token'] = token_data['access_token']
                
                # Обновляем refresh_token если он был предоставлен
                if 'refresh_token' in token_data:
                    updated_tokens['refresh_token'] = token_data['refresh_token']
                
                storage.save_user_tokens(user_id, updated_tokens)
                
                logger.info(f"🔄 Токен обновлен для пользователя {user_id}")
                return token_data['access_token']
                
        except Exception as e:
            logger.error(f"Ошибка обновления токена: {e}")
            return None
    
    async def get_valid_access_token(self, user_id: str) -> Optional[str]:
        """Получение валидного токена доступа"""
        if not storage.is_token_valid(user_id):
            # Пытаемся обновить токен
            return await self.refresh_access_token(user_id)
        
        tokens = storage.get_user_tokens(user_id)
        return tokens.get('access_token') if tokens else None
    
    def is_authenticated(self, user_id: str) -> bool:
        """Проверка авторизации пользователя"""
        return storage.is_token_valid(user_id)
    
    def revoke_access(self, user_id: str):
        """Отзыв доступа (удаление токенов)"""
        storage.delete_user_data(user_id)
        logger.info(f"🔐 Доступ отозван для пользователя {user_id}")

# Глобальный экземпляр менеджера OAuth
oauth_manager = OAuthManager()
