"""
Узлы для публикации на веб-сайте
"""

import logging
from typing import Dict, Optional, List, Any

from giga_agent.agents.social_media_agent.utils.website_clients import (
    WordPressClient,
    DrupalClient,
    CustomCMSClient
)
from giga_agent.agents.social_media_agent.utils.mcp_client import MCPWebsiteClient

logger = logging.getLogger(__name__)


async def publish_website_post(
    title: str,
    content: str,
    cms_type: str = "wordpress",
    status: str = "publish",
    categories: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    featured_image_id: Optional[int] = None,
    use_mcp: bool = False,
    state: Optional[Dict] = None
) -> str:
    """
    Публикует пост на веб-сайте
    
    Args:
        title: Заголовок поста
        content: Содержимое поста
        cms_type: Тип CMS (wordpress, drupal, custom, mcp)
        status: Статус публикации
        categories: Список категорий
        tags: Список тегов
        featured_image_id: ID изображения для обложки
        use_mcp: Использовать MCP сервер для публикации
        state: Состояние агента с секретами и MCP инструментами
    """
    try:
        # Преобразуем markdown в HTML для публикации на сайте
        from giga_agent.utils.markdown_utils import markdown_to_html
        html_content = markdown_to_html(content)
        logger.info(f"📝 publish_website_post: Преобразовано markdown в HTML (длина: {len(content)} -> {len(html_content)})")
        
        # Если указано использование MCP
        if use_mcp or cms_type == "mcp":
            mcp_tools = state.get("mcp_tools", []) if state else []
            if not mcp_tools:
                return "❌ Ошибка: MCP инструменты не доступны. Убедитесь, что MCP сервер подключен."
            
            mcp_client = MCPWebsiteClient(mcp_tools=mcp_tools)
            # Для MCP передаем уже преобразованный HTML контент
            result = await mcp_client.publish_via_mcp(title, html_content, mcp_tools)
            
            if result.get("success"):
                return f"✅ Пост подготовлен к публикации через MCP\n🔧 Инструмент: {result.get('tool_name')}\n📝 {result.get('message')}"
            else:
                return f"❌ Ошибка публикации через MCP: {result.get('error')}"
        
        # Обычная публикация через API
        secrets = state.get("secrets", []) if state else []
        
        if cms_type == "wordpress":
            # Ищем токен WordPress
            wp_token = None
            wp_url = None
            
            for secret in secrets:
                name = secret.get("name", "").lower()
                if "wordpress" in name:
                    if "token" in name or "api" in name:
                        wp_token = secret.get("value")
                    elif "url" in name or "site" in name:
                        wp_url = secret.get("value")
            
            if not wp_token or not wp_url:
                return "❌ Ошибка: Не найдены WordPress API Token или Site URL в секретах"
            
            client = WordPressClient(wp_url, wp_token)
            # Используем преобразованный HTML контент
            result = await client.publish_post(
                title, html_content, status, 
                [int(c) for c in categories] if categories else None,
                [int(t) for t in tags] if tags else None,
                featured_image_id
            )
            
            if result.get("success"):
                return f"✅ {result.get('message')}\n🔗 URL: {result.get('post_url')}"
            else:
                return f"❌ Ошибка публикации в WordPress: {result.get('error')}"
        
        elif cms_type == "drupal":
            # Ищем токен Drupal
            drupal_token = None
            drupal_url = None
            
            for secret in secrets:
                name = secret.get("name", "").lower()
                if "drupal" in name:
                    if "token" in name or "api" in name:
                        drupal_token = secret.get("value")
                    elif "url" in name or "site" in name:
                        drupal_url = secret.get("value")
            
            if not drupal_token or not drupal_url:
                return "❌ Ошибка: Не найдены Drupal API Token или Site URL в секретах"
            
            client = DrupalClient(drupal_url, drupal_token)
            # Используем преобразованный HTML контент
            result = await client.publish_post(title, html_content)
            
            if result.get("success"):
                return f"✅ {result.get('message')}\n🆔 Node ID: {result.get('node_id')}"
            else:
                return f"❌ Ошибка публикации в Drupal: {result.get('error')}"
        
        elif cms_type == "custom":
            # Ищем токен кастомного CMS
            custom_token = None
            custom_url = None
            
            for secret in secrets:
                name = secret.get("name", "").lower()
                if "cms" in name or "custom" in name:
                    if "token" in name or "api" in name:
                        custom_token = secret.get("value")
                    elif "url" in name or "api" in name:
                        custom_url = secret.get("value")
            
            if not custom_token or not custom_url:
                return "❌ Ошибка: Не найдены Custom CMS API Token или API URL в секретах"
            
            client = CustomCMSClient(custom_url, custom_token)
            # Используем преобразованный HTML контент
            result = await client.publish_post(title, html_content)
            
            if result.get("success"):
                return f"✅ {result.get('message')}\n🆔 Post ID: {result.get('post_id')}"
            else:
                return f"❌ Ошибка публикации через Custom CMS: {result.get('error')}"
        
        else:
            return f"❌ Ошибка: Неподдерживаемый тип CMS: {cms_type}"
    
    except Exception as e:
        logger.error(f"Ошибка публикации на сайте: {e}")
        return f"❌ Ошибка публикации на сайте: {str(e)}"


async def update_website_page(
    page_id: int,
    content: Optional[str] = None,
    title: Optional[str] = None,
    cms_type: str = "wordpress",
    use_mcp: bool = False,
    state: Optional[Dict] = None
) -> str:
    """
    Обновляет страницу на веб-сайте
    
    Args:
        page_id: ID страницы для обновления
        content: Новое содержимое
        title: Новый заголовок
        cms_type: Тип CMS
        use_mcp: Использовать MCP сервер
        state: Состояние агента
    """
    try:
        # Преобразуем markdown в HTML для обновления на сайте (если content указан)
        html_content = None
        if content:
            from giga_agent.utils.markdown_utils import markdown_to_html
            html_content = markdown_to_html(content)
            logger.info(f"📝 update_website_page: Преобразовано markdown в HTML (длина: {len(content)} -> {len(html_content)})")
        
        # Если указано использование MCP
        if use_mcp or cms_type == "mcp":
            mcp_tools = state.get("mcp_tools", []) if state else []
            if not mcp_tools:
                return "❌ Ошибка: MCP инструменты не доступны"
            
            mcp_client = MCPWebsiteClient(mcp_tools=mcp_tools)
            # Для MCP передаем уже преобразованный HTML контент
            result = await mcp_client.update_via_mcp(str(page_id), title, html_content, mcp_tools)
            
            if result.get("success"):
                return f"✅ Страница подготовлена к обновлению через MCP\n🔧 Инструмент: {result.get('tool_name')}\n📝 {result.get('message')}"
            else:
                return f"❌ Ошибка обновления через MCP: {result.get('error')}"
        
        # Обычное обновление через API
        secrets = state.get("secrets", []) if state else []
        
        if cms_type == "wordpress":
            wp_token = None
            wp_url = None
            
            for secret in secrets:
                name = secret.get("name", "").lower()
                if "wordpress" in name:
                    if "token" in name or "api" in name:
                        wp_token = secret.get("value")
                    elif "url" in name or "site" in name:
                        wp_url = secret.get("value")
            
            if not wp_token or not wp_url:
                return "❌ Ошибка: Не найдены WordPress API Token или Site URL в секретах"
            
            client = WordPressClient(wp_url, wp_token)
            # Используем преобразованный HTML контент
            result = await client.update_post(page_id, title, html_content)
            
            if result.get("success"):
                return f"✅ {result.get('message')}\n🔗 URL: {result.get('post_url')}"
            else:
                return f"❌ Ошибка обновления в WordPress: {result.get('error')}"
        
        else:
            return f"❌ Ошибка: Обновление для CMS типа '{cms_type}' пока не поддерживается"
    
    except Exception as e:
        logger.error(f"Ошибка обновления страницы: {e}")
        return f"❌ Ошибка обновления страницы: {str(e)}"

