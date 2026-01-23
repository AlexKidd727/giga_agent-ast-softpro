"""
Клиенты для работы с API социальных сетей
"""

import logging
import httpx
from typing import Optional, Dict, List, Any
import base64

logger = logging.getLogger(__name__)


class VKClient:
    """Клиент для работы с VK API"""
    
    def __init__(self, access_token: str, api_version: str = "5.131"):
        self.access_token = access_token
        self.api_version = api_version
        self.base_url = "https://api.vk.com/method"
    
    async def publish_post(
        self,
        message: str,
        attachments: Optional[List[str]] = None,
        group_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Публикует пост в VK
        
        Args:
            message: Текст поста
            attachments: Список вложений (фото, видео, документы)
            group_id: ID группы (если None - публикация на стену пользователя)
        """
        try:
            url = f"{self.base_url}/wall.post"
            params = {
                "access_token": self.access_token,
                "v": self.api_version,
                "message": message,
            }
            
            if group_id:
                params["owner_id"] = -group_id  # Отрицательное значение для групп
            
            if attachments:
                params["attachments"] = ",".join(attachments)
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                if "error" in data:
                    raise Exception(f"VK API Error: {data['error'].get('error_msg', 'Unknown error')}")
                
                return {
                    "success": True,
                    "post_id": data.get("response", {}).get("post_id"),
                    "message": "Пост успешно опубликован в VK"
                }
        except Exception as e:
            logger.error(f"Ошибка публикации в VK: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class FacebookClient:
    """Клиент для работы с Facebook Graph API"""
    
    def __init__(self, access_token: str, page_id: Optional[str] = None):
        self.access_token = access_token
        self.page_id = page_id
        self.base_url = "https://graph.facebook.com/v18.0"
    
    async def publish_post(
        self,
        message: str,
        page_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Публикует пост в Facebook
        
        Args:
            message: Текст поста
            page_id: ID страницы (если None - используется self.page_id)
        """
        try:
            target_page_id = page_id or self.page_id
            if not target_page_id:
                raise Exception("Page ID не указан")
            
            url = f"{self.base_url}/{target_page_id}/feed"
            params = {
                "access_token": self.access_token,
                "message": message,
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                return {
                    "success": True,
                    "post_id": data.get("id"),
                    "message": "Пост успешно опубликован в Facebook"
                }
        except Exception as e:
            logger.error(f"Ошибка публикации в Facebook: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class TelegramClient:
    """Клиент для работы с Telegram Bot API"""
    
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        photo_url: Optional[str] = None,
        video_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Отправляет сообщение в Telegram канал/группу
        
        Args:
            chat_id: ID или username канала (например, @channel_name или -1001234567890)
            text: Текст сообщения
            parse_mode: Режим форматирования (HTML, Markdown)
            photo_url: URL изображения (опционально)
            video_url: URL видео (опционально)
        """
        try:
            if photo_url:
                # Отправка фото с подписью
                url = f"{self.base_url}/sendPhoto"
                params = {
                    "chat_id": chat_id,
                    "photo": photo_url,
                    "caption": text,
                    "parse_mode": parse_mode
                }
            elif video_url:
                # Отправка видео с подписью
                url = f"{self.base_url}/sendVideo"
                params = {
                    "chat_id": chat_id,
                    "video": video_url,
                    "caption": text,
                    "parse_mode": parse_mode
                }
            else:
                # Отправка текстового сообщения
                url = f"{self.base_url}/sendMessage"
                params = {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode
                }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                if not data.get("ok"):
                    raise Exception(f"Telegram API Error: {data.get('description', 'Unknown error')}")
                
                return {
                    "success": True,
                    "message_id": data.get("result", {}).get("message_id"),
                    "message": "Сообщение успешно отправлено в Telegram"
                }
        except Exception as e:
            logger.error(f"Ошибка отправки в Telegram: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class TwitterClient:
    """Клиент для работы с Twitter API v2"""
    
    def __init__(
        self,
        bearer_token: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        access_token_secret: Optional[str] = None
    ):
        self.bearer_token = bearer_token
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.base_url = "https://api.twitter.com/2"
    
    async def publish_tweet(
        self,
        text: str
    ) -> Dict[str, Any]:
        """
        Публикует твит
        
        Args:
            text: Текст твита (максимум 280 символов)
        """
        try:
            if len(text) > 280:
                raise Exception("Текст твита превышает 280 символов")
            
            url = f"{self.base_url}/tweets"
            headers = {
                "Authorization": f"Bearer {self.bearer_token}" if self.bearer_token else None,
                "Content-Type": "application/json"
            }
            
            # Удаляем None значения из headers
            headers = {k: v for k, v in headers.items() if v is not None}
            
            data = {
                "text": text
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                
                return {
                    "success": True,
                    "tweet_id": result.get("data", {}).get("id"),
                    "message": "Твит успешно опубликован"
                }
        except Exception as e:
            logger.error(f"Ошибка публикации в Twitter: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class InstagramClient:
    """Клиент для работы с Instagram Basic Display API / Instagram Graph API"""
    
    def __init__(self, access_token: str, user_id: Optional[str] = None):
        self.access_token = access_token
        self.user_id = user_id
        self.base_url = "https://graph.instagram.com"
    
    async def publish_post(
        self,
        image_url: str,
        caption: str
    ) -> Dict[str, Any]:
        """
        Публикует пост в Instagram
        
        Args:
            image_url: URL изображения
            caption: Подпись к посту
        """
        try:
            if not self.user_id:
                raise Exception("User ID не указан")
            
            # Создаем контейнер для медиа
            container_url = f"{self.base_url}/{self.user_id}/media"
            params = {
                "access_token": self.access_token,
                "image_url": image_url,
                "caption": caption
            }
            
            async with httpx.AsyncClient() as client:
                # Создаем контейнер
                response = await client.post(container_url, params=params)
                response.raise_for_status()
                container_data = response.json()
                container_id = container_data.get("id")
                
                if not container_id:
                    raise Exception("Не удалось создать контейнер для медиа")
                
                # Публикуем контейнер
                publish_url = f"{self.base_url}/{self.user_id}/media_publish"
                publish_params = {
                    "access_token": self.access_token,
                    "creation_id": container_id
                }
                
                publish_response = await client.post(publish_url, params=publish_params)
                publish_response.raise_for_status()
                publish_data = publish_response.json()
                
                return {
                    "success": True,
                    "media_id": publish_data.get("id"),
                    "message": "Пост успешно опубликован в Instagram"
                }
        except Exception as e:
            logger.error(f"Ошибка публикации в Instagram: {e}")
            return {
                "success": False,
                "error": str(e)
            }

