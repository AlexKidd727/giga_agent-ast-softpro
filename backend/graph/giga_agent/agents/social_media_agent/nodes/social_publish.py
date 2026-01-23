"""
Узлы для публикации в социальных сетях
"""

import logging
import os
from typing import Dict, Optional, List, Any
import re

from giga_agent.agents.social_media_agent.utils.social_clients import (
    VKClient,
    FacebookClient,
    TelegramClient,
    TwitterClient,
    InstagramClient
)

logger = logging.getLogger(__name__)


async def publish_vk_post(
    message: str,
    attachments: Optional[List[str]] = None,
    group_id: Optional[int] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Публикует пост в VK
    
    Args:
        message: Текст поста
        attachments: Список вложений
        group_id: ID группы
        state: Состояние агента с секретами
    """
    try:
        secrets = state.get("secrets", []) if state else []
        
        # Ищем токен VK
        vk_token = None
        vk_api_version = "5.131"
        
        for secret in secrets:
            name = secret.get("name", "").lower()
            if "vk" in name and "token" in name:
                vk_token = secret.get("value")
            elif "vk" in name and "version" in name:
                vk_api_version = secret.get("value", "5.131")
        
        if not vk_token:
            return "❌ Ошибка: Не найден VK Access Token в секретах"
        
        client = VKClient(vk_token, vk_api_version)
        result = await client.publish_post(message, attachments, group_id)
        
        if result.get("success"):
            return f"✅ {result.get('message')}\n🆔 Post ID: {result.get('post_id')}"
        else:
            return f"❌ Ошибка публикации в VK: {result.get('error')}"
    except Exception as e:
        logger.error(f"Ошибка публикации в VK: {e}")
        return f"❌ Ошибка публикации в VK: {str(e)}"


async def publish_facebook_post(
    message: str,
    page_id: Optional[str] = None,
    state: Optional[Dict] = None
) -> str:
    """
    Публикует пост в Facebook
    
    Args:
        message: Текст поста
        page_id: ID страницы
        state: Состояние агента с секретами
    """
    try:
        secrets = state.get("secrets", []) if state else []
        
        # Ищем токен Facebook
        fb_token = None
        fb_page_id = None
        
        for secret in secrets:
            name = secret.get("name", "").lower()
            if "facebook" in name and "token" in name:
                fb_token = secret.get("value")
            elif "facebook" in name and "page" in name and "id" in name:
                fb_page_id = secret.get("value")
        
        if not fb_token:
            return "❌ Ошибка: Не найден Facebook Access Token в секретах"
        
        target_page_id = page_id or fb_page_id
        if not target_page_id:
            return "❌ Ошибка: Не указан Page ID для Facebook"
        
        client = FacebookClient(fb_token, target_page_id)
        result = await client.publish_post(message, target_page_id)
        
        if result.get("success"):
            return f"✅ {result.get('message')}\n🆔 Post ID: {result.get('post_id')}"
        else:
            return f"❌ Ошибка публикации в Facebook: {result.get('error')}"
    except Exception as e:
        logger.error(f"Ошибка публикации в Facebook: {e}")
        return f"❌ Ошибка публикации в Facebook: {str(e)}"


async def publish_telegram_message(
    text: str,
    channel_id: str,
    photo_url: Optional[str] = None,
    video_url: Optional[str] = None,
    parse_mode: str = "HTML",
    state: Optional[Dict] = None
) -> str:
    """
    Публикует сообщение в Telegram канал
    
    Args:
        text: Текст сообщения
        channel_id: ID или username канала
        photo_url: URL изображения
        video_url: URL видео
        parse_mode: Режим форматирования
        state: Состояние агента с секретами
    """
    try:
        # Удаляем markdown разметку из текста перед отправкой в Telegram
        from giga_agent.utils.markdown_utils import strip_markdown
        clean_text = strip_markdown(text)
        logger.info(f"📝 publish_telegram_message: Удалена markdown разметка (длина: {len(text)} -> {len(clean_text)})")
        
        secrets = state.get("secrets", []) if state else []
        
        # Ищем токен Telegram бота для публикации (отдельный от токена интерфейсного бота)
        bot_token = None
        
        # Сначала ищем в секретах (приоритет: TELEGRAM_PUBLISH_BOT_TOKEN, затем TELEGRAM_BOT_TOKEN)
        for secret in secrets:
            name = secret.get("name", "").lower()
            # Ищем токен для публикации
            if "telegram" in name and ("publish" in name or "channel" in name) and "token" in name:
                bot_token = secret.get("value")
                logger.info("✅ Telegram Publish Bot Token найден в секретах")
                break
        
        # Если не найден токен для публикации, ищем общий токен в секретах
        if not bot_token:
            for secret in secrets:
                name = secret.get("name", "").lower()
                if "telegram" in name and "token" in name:
                    bot_token = secret.get("value")
                    logger.info("✅ Telegram Bot Token найден в секретах (используется общий токен)")
                    break
        
        # Если не найден в секретах, проверяем переменные окружения
        # Приоритет: TELEGRAM_PUBLISH_BOT_TOKEN (для публикации), затем TELEGRAM_BOT_TOKEN (общий)
        if not bot_token:
            bot_token = os.getenv("TELEGRAM_PUBLISH_BOT_TOKEN")
            if bot_token:
                logger.info("✅ Telegram Publish Bot Token найден в переменной окружения TELEGRAM_PUBLISH_BOT_TOKEN")
        
        # Если токен для публикации не найден, используем общий токен (для обратной совместимости)
        if not bot_token:
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            if bot_token:
                logger.warning("⚠️ Используется общий TELEGRAM_BOT_TOKEN для публикации. Рекомендуется использовать отдельный TELEGRAM_PUBLISH_BOT_TOKEN")
        
        if not bot_token:
            return "❌ Ошибка: Не найден Telegram Bot Token для публикации. Проверьте секреты или переменные окружения TELEGRAM_PUBLISH_BOT_TOKEN (рекомендуется) или TELEGRAM_BOT_TOKEN"
        
        client = TelegramClient(bot_token)
        result = await client.send_message(channel_id, clean_text, parse_mode, photo_url, video_url)
        
        if result.get("success"):
            return f"✅ {result.get('message')}\n🆔 Message ID: {result.get('message_id')}"
        else:
            return f"❌ Ошибка отправки в Telegram: {result.get('error')}"
    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")
        return f"❌ Ошибка отправки в Telegram: {str(e)}"


async def publish_twitter_post(
    text: str,
    state: Optional[Dict] = None
) -> str:
    """
    Публикует твит
    
    Args:
        text: Текст твита
        state: Состояние агента с секретами
    """
    try:
        if len(text) > 280:
            return "❌ Ошибка: Текст твита превышает 280 символов"
        
        secrets = state.get("secrets", []) if state else []
        
        # Ищем токены Twitter
        bearer_token = None
        api_key = None
        api_secret = None
        access_token = None
        access_token_secret = None
        
        for secret in secrets:
            name = secret.get("name", "").lower()
            if "twitter" in name:
                if "bearer" in name:
                    bearer_token = secret.get("value")
                elif "api_key" in name:
                    api_key = secret.get("value")
                elif "api_secret" in name:
                    api_secret = secret.get("value")
                elif "access_token" in name and "secret" not in name:
                    access_token = secret.get("value")
                elif "access_token_secret" in name:
                    access_token_secret = secret.get("value")
        
        if not bearer_token and not (api_key and access_token):
            return "❌ Ошибка: Не найдены Twitter токены в секретах"
        
        client = TwitterClient(bearer_token, api_key, api_secret, access_token, access_token_secret)
        result = await client.publish_tweet(text)
        
        if result.get("success"):
            return f"✅ {result.get('message')}\n🆔 Tweet ID: {result.get('tweet_id')}"
        else:
            return f"❌ Ошибка публикации в Twitter: {result.get('error')}"
    except Exception as e:
        logger.error(f"Ошибка публикации в Twitter: {e}")
        return f"❌ Ошибка публикации в Twitter: {str(e)}"


async def publish_instagram_post(
    image_url: str,
    caption: str,
    state: Optional[Dict] = None
) -> str:
    """
    Публикует пост в Instagram
    
    Args:
        image_url: URL изображения
        caption: Подпись к посту
        state: Состояние агента с секретами
    """
    try:
        secrets = state.get("secrets", []) if state else []
        
        # Ищем токен Instagram
        ig_token = None
        ig_user_id = None
        
        for secret in secrets:
            name = secret.get("name", "").lower()
            if "instagram" in name and "token" in name:
                ig_token = secret.get("value")
            elif "instagram" in name and "user" in name and "id" in name:
                ig_user_id = secret.get("value")
        
        if not ig_token:
            return "❌ Ошибка: Не найден Instagram Access Token в секретах"
        
        if not ig_user_id:
            return "❌ Ошибка: Не указан Instagram User ID в секретах"
        
        client = InstagramClient(ig_token, ig_user_id)
        result = await client.publish_post(image_url, caption)
        
        if result.get("success"):
            return f"✅ {result.get('message')}\n🆔 Media ID: {result.get('media_id')}"
        else:
            return f"❌ Ошибка публикации в Instagram: {result.get('error')}"
    except Exception as e:
        logger.error(f"Ошибка публикации в Instagram: {e}")
        return f"❌ Ошибка публикации в Instagram: {str(e)}"

