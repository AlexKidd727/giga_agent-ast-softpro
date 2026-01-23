"""
Клиенты для работы с API веб-сайтов (CMS)
"""

import logging
import httpx
from typing import Optional, Dict, List, Any
import base64

logger = logging.getLogger(__name__)


class WordPressClient:
    """Клиент для работы с WordPress REST API"""
    
    def __init__(self, site_url: str, api_token: str):
        self.site_url = site_url.rstrip('/')
        self.api_token = api_token
        self.base_url = f"{self.site_url}/wp-json/wp/v2"
    
    async def publish_post(
        self,
        title: str,
        content: str,
        status: str = "publish",
        categories: Optional[List[int]] = None,
        tags: Optional[List[int]] = None,
        featured_image_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Публикует пост на WordPress сайте
        
        Args:
            title: Заголовок поста
            content: Содержимое поста (HTML)
            status: Статус публикации (publish, draft, pending)
            categories: Список ID категорий
            tags: Список ID тегов
            featured_image_id: ID изображения для обложки
        """
        try:
            url = f"{self.base_url}/posts"
            headers = {
                "Authorization": f"Basic {self.api_token}",
                "Content-Type": "application/json"
            }
            
            data = {
                "title": title,
                "content": content,
                "status": status
            }
            
            if categories:
                data["categories"] = categories
            
            if tags:
                data["tags"] = tags
            
            if featured_image_id:
                data["featured_media"] = featured_image_id
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                
                return {
                    "success": True,
                    "post_id": result.get("id"),
                    "post_url": result.get("link"),
                    "message": f"Пост успешно опубликован на WordPress: {result.get('link')}"
                }
        except Exception as e:
            logger.error(f"Ошибка публикации в WordPress: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def update_post(
        self,
        post_id: int,
        title: Optional[str] = None,
        content: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Обновляет пост на WordPress сайте
        
        Args:
            post_id: ID поста для обновления
            title: Новый заголовок (если None - не обновляется)
            content: Новое содержимое (если None - не обновляется)
        """
        try:
            url = f"{self.base_url}/posts/{post_id}"
            headers = {
                "Authorization": f"Basic {self.api_token}",
                "Content-Type": "application/json"
            }
            
            data = {}
            if title is not None:
                data["title"] = title
            if content is not None:
                data["content"] = content
            
            if not data:
                return {
                    "success": False,
                    "error": "Не указаны данные для обновления"
                }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                
                return {
                    "success": True,
                    "post_id": result.get("id"),
                    "post_url": result.get("link"),
                    "message": f"Пост успешно обновлен: {result.get('link')}"
                }
        except Exception as e:
            logger.error(f"Ошибка обновления в WordPress: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class DrupalClient:
    """Клиент для работы с Drupal REST API"""
    
    def __init__(self, site_url: str, api_token: str):
        self.site_url = site_url.rstrip('/')
        self.api_token = api_token
        self.base_url = f"{self.site_url}/node"
    
    async def publish_post(
        self,
        title: str,
        content: str,
        content_type: str = "article"
    ) -> Dict[str, Any]:
        """
        Публикует пост на Drupal сайте
        
        Args:
            title: Заголовок поста
            content: Содержимое поста
            content_type: Тип контента (article, page и т.д.)
        """
        try:
            url = f"{self.base_url}"
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            data = {
                "type": [{"target_id": content_type}],
                "title": [{"value": title}],
                "body": [{"value": content, "format": "full_html"}]
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                
                return {
                    "success": True,
                    "node_id": result.get("nid", [{}])[0].get("value") if isinstance(result.get("nid"), list) else result.get("nid"),
                    "message": "Пост успешно опубликован на Drupal"
                }
        except Exception as e:
            logger.error(f"Ошибка публикации в Drupal: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class CustomCMSClient:
    """Клиент для работы с кастомным CMS API"""
    
    def __init__(self, api_url: str, api_token: str):
        self.api_url = api_url.rstrip('/')
        self.api_token = api_token
    
    async def publish_post(
        self,
        title: str,
        content: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Публикует пост через кастомный CMS API
        
        Args:
            title: Заголовок поста
            content: Содержимое поста
            **kwargs: Дополнительные параметры для API
        """
        try:
            url = f"{self.api_url}/posts"  # Предполагаемый endpoint
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }
            
            data = {
                "title": title,
                "content": content,
                **kwargs
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                
                return {
                    "success": True,
                    "post_id": result.get("id"),
                    "message": "Пост успешно опубликован через кастомный CMS"
                }
        except Exception as e:
            logger.error(f"Ошибка публикации через кастомный CMS: {e}")
            return {
                "success": False,
                "error": str(e)
            }

