"""
Граф Social Media Agent
"""

import logging
import os
from typing import Annotated, Optional
import re

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langgraph.constants import START, END
from langgraph.graph import StateGraph

from giga_agent.agents.social_media_agent.config import SocialMediaAgentState
from giga_agent.agents.social_media_agent.nodes.social_publish import (
    publish_vk_post,
    publish_facebook_post,
    publish_telegram_message,
    publish_twitter_post,
    publish_instagram_post
)
from giga_agent.agents.social_media_agent.nodes.website_publish import (
    publish_website_post,
    update_website_page
)

logger = logging.getLogger(__name__)


# Внутренняя функция без декоратора @tool для использования в графе
async def _social_media_agent_impl(
    user_request: str,
    platform: Optional[str] = None,
    user_id: str = "default_user",
    state: Optional[dict] = None
):
    """
    Агент для работы с социальными сетями и веб-сайтами
    
    Обрабатывает запросы пользователя связанные с:
    
    ПОЛУЧЕНИЕ НОВОСТЕЙ С САЙТА:
    - "получить последнюю новость с сайта" - используй MCP инструменты из state["mcp_tools"]
    - "взять новость с сайта и опубликовать в Telegram" - сначала получи новость через MCP, затем опубликуй
    - Для получения новостей используй доступные MCP инструменты (list_news, get_news, get_latest_news и т.д.)
    
    ПУБЛИКАЦИЯ В СОЦ. СЕТЯХ:
    - VK: "опубликовать в VK", "пост в вк"
    - Facebook: "опубликовать в Facebook", "пост в фейсбук"
    - Instagram: "опубликовать в Instagram", "пост в инстаграм"
    - Twitter: "опубликовать в Twitter", "твит"
    - Telegram: "опубликовать в Telegram", "отправить в телеграм", "вывести в телеграм"
    
    ПУБЛИКАЦИЯ НА САЙТЕ:
    - WordPress: "опубликовать на сайте", "добавить новость на сайт"
    - Drupal: "опубликовать в Drupal"
    - Кастомный CMS: "опубликовать через API"
    - MCP: "опубликовать через MCP", "использовать MCP для публикации"
    
    ОБНОВЛЕНИЕ СТРАНИЦ:
    - "обновить страницу на сайте", "изменить пост на сайте"
    
    ВАЖНО: Если пользователь просит "взять новость с сайта и опубликовать в Telegram":
    1. Сначала используй MCP инструменты из state["mcp_tools"] для получения новости (list_news, get_latest_news и т.д.)
    2. Затем опубликуй полученную новость в Telegram используя publish_telegram_message
    
    Args:
        user_request: Запрос пользователя
        platform: Платформа (vk, facebook, instagram, twitter, telegram, website)
        user_id: Идентификатор пользователя
        state: Состояние агента с секретами и MCP инструментами
    """
    
    logger.info(f"[SOCIAL_MEDIA_AGENT] _social_media_agent_impl вызван: user_request='{user_request}', platform={platform}, user_id={user_id}")
    
    # Инициализируем state если он None
    if state is None:
        state = {}
    
    try:
        user_input = user_request.lower()

        # Извлекаем текст поста из запроса заранее.
        # Примечание: дальше (в ветке "взять новость...") используется post_text.
        # Раньше здесь была логическая ошибка: post_text использовался до присваивания,
        # что могло приводить к UnboundLocalError и повторным попыткам на уровне главного агента.
        post_text = None
        
        # 1. ПРИОРИТЕТ: Ищем текст после ключевых слов "новость", "сообщение", "текст"
        # Это важно, чтобы не взять первое совпадение в кавычках, если есть явное указание
        text_patterns = [
            r'новость[:\s]+["\']([^"\']+)["\']',  # "новость: 'текст'" - текст в кавычках после "новость:"
            r'новость[:\s]+([^"\']+?)(?:\s+в\s+|\s+на\s+|$)',  # "новость: текст" - текст без кавычек после "новость:"
            r'сообщение[:\s]+["\']([^"\']+)["\']',  # "сообщение: 'текст'"
            r'сообщение[:\s]+([^"\']+?)(?:\s+в\s+|\s+на\s+|$)',  # "сообщение: текст"
            r'текст[:\s]+["\']([^"\']+)["\']',  # "текст: 'текст'"
            r'текст[:\s]+([^"\']+?)(?:\s+в\s+|\s+на\s+|$)',  # "текст: текст"
            r'пост[:\s]+["\']([^"\']+)["\']',  # "пост: 'текст'"
            r'пост[:\s]+([^"\']+?)(?:\s+в\s+|\s+на\s+|$)',  # "пост: текст"
            r'твит[:\s]+["\']([^"\']+)["\']',  # "твит: 'текст'"
            r'твит[:\s]+([^"\']+?)(?:\s+в\s+|\s+на\s+|$)',  # "твит: текст"
            r'публикация[:\s]+["\']([^"\']+)["\']',  # "публикация: 'текст'"
            r'публикация[:\s]+([^"\']+?)(?:\s+в\s+|\s+на\s+|$)',  # "публикация: текст"
        ]
        for pattern in text_patterns:
            match = re.search(pattern, user_request, re.IGNORECASE)
            if match:
                post_text = match.group(1).strip()
                # Удаляем лишние слова в конце (если они попали)
                post_text = re.sub(
                    r'\s+(в|на|канале|телеграм|сайт|vk|facebook|instagram|twitter).*$', 
                    '', 
                    post_text, 
                    flags=re.IGNORECASE
                ).strip()
                logger.info(
                    f"[SOCIAL_MEDIA_AGENT] Текст извлечен по паттерну '{pattern}': "
                    f"'{post_text[:100]}...' (длина: {len(post_text)})"
                )
                break

        # 2. Если не нашли по ключевым словам, ищем последнее совпадение в кавычках
        # (последнее, потому что первое может быть частью команды, например, название канала)
        if not post_text:
            all_quoted = re.findall(r'["\']([^"\']+)["\']', user_request)
            if all_quoted:
                # Берем последнее совпадение (обычно это и есть текст для публикации)
                post_text = all_quoted[-1].strip()
                logger.info(
                    f"[SOCIAL_MEDIA_AGENT] Текст извлечен из последних кавычек: "
                    f"'{post_text[:100]}...' (длина: {len(post_text)})"
                )

        # 3. Ищем текст после "опубликовать", "отправить", "добавить"
        if not post_text:
            action_patterns = [
                r'(?:опубликовать|отправить|добавить)[:\s]+["\']?([^"\']+?)(?:["\']|в\s+телеграм|на\s+сайт|в\s+vk|в\s+facebook|в\s+instagram|в\s+twitter|\s*$)',
            ]
            for pattern in action_patterns:
                match = re.search(pattern, user_request, re.IGNORECASE)
                if match:
                    post_text = match.group(1).strip()
                    # Удаляем лишние слова в конце
                    post_text = re.sub(
                        r'\s+(в|на|канале|телеграм|сайт|vk|facebook|instagram|twitter).*$', 
                        '', 
                        post_text, 
                        flags=re.IGNORECASE
                    ).strip()
                    logger.info(f"[SOCIAL_MEDIA_AGENT] Текст извлечен по паттерну действия: '{post_text}'")
                    break

        # 4. Если не нашли, используем весь запрос как текст, но удаляем команды
        if not post_text:
            # Удаляем команды из текста
            post_text = re.sub(
                r'\b(опубликовать|отправить|добавить|пост|твит|в|на|vk|facebook|instagram|twitter|telegram|сайт|website|канале|новость)\b',
                '',
                user_request,
                flags=re.IGNORECASE
            ).strip()
            logger.info(f"[SOCIAL_MEDIA_AGENT] Текст извлечен из всего запроса (после удаления команд): '{post_text}'")

        # Логируем финальный текст
        if post_text:
            logger.info(
                f"[SOCIAL_MEDIA_AGENT] Финальный текст для публикации: "
                f"'{post_text[:100]}...' (длина: {len(post_text)})"
            )
        
        # ВАЖНО: Обработка запросов на получение новости с сайта и публикацию в Telegram
        # Распознаем запросы типа "взять новость с сайта и опубликовать в Telegram"
        if any(phrase in user_input for phrase in ["взять новость", "получить новость", "последняя новость", "взять с сайта", "получить с сайта", "вывести новость"]):
            # Проверяем, есть ли текст для публикации (если пользователь уже получил новость)
            # Если текста нет, возвращаем инструкцию для основного агента
            if not post_text or not post_text.strip():
                mcp_tools = state.get("mcp_tools", []) if state else []
                
                if mcp_tools:
                    # Ищем подходящий MCP инструмент для получения новостей
                    news_tools = [tool for tool in mcp_tools if any(keyword in tool.get("name", "").lower() for keyword in ["news", "новость", "post", "get", "list"])]
                    
                    if news_tools:
                        tool_names = [tool.get("name", "") for tool in news_tools]
                        return f"""ℹ️ Для получения новости с сайта и публикации в Telegram:

1. Сначала используй MCP инструмент для получения последней новости:
   - Доступные инструменты: {', '.join(tool_names)}
   - Рекомендуется использовать инструмент с 'latest' или 'list' в названии
   - Пример: вызови инструмент '{tool_names[0]}' с параметрами limit=1

2. Затем используй social_media_agent для публикации полученной новости в Telegram:
   - Формат: "опубликовать в Telegram: '[текст новости]'"
   - Или: "вывести в телеграм: '[текст новости]'"

Альтернативно, если у тебя уже есть текст новости, просто используй:
"опубликовать в Telegram: '[текст новости]'"
"""
                    else:
                        return "❌ Ошибка: Не найдено MCP инструментов для получения новостей. Убедитесь, что MCP сервер подключен и имеет инструменты для работы с новостями (list_news, get_latest_news и т.д.)."
                else:
                    return "❌ Ошибка: MCP инструменты не доступны. Убедитесь, что MCP сервер подключен в конфигурации GIGA_AGENT_MCP_CONFIG."
        
        # Определяем платформу из запроса, если не указана явно
        if not platform:
            if any(word in user_input for word in ["vk", "вк", "вконтакте"]):
                platform = "vk"
            elif any(word in user_input for word in ["facebook", "фейсбук", "фб"]):
                platform = "facebook"
            elif any(word in user_input for word in ["instagram", "инстаграм", "инста"]):
                platform = "instagram"
            elif any(word in user_input for word in ["twitter", "твиттер", "твит"]):
                platform = "twitter"
            elif any(word in user_input for word in ["telegram", "телеграм", "тг"]):
                platform = "telegram"
            elif any(word in user_input for word in ["сайт", "website", "wordpress", "drupal", "cms", "mcp"]):
                platform = "website"
        
        # Примечание: логика извлечения post_text перенесена выше (см. комментарий),
        # чтобы post_text был доступен для ветки "взять новость...".
        
        # Извлекаем заголовок для сайта
        title_match = re.search(r'заголовок[:\s]+["\']([^"\']+)["\']', user_request, re.IGNORECASE)
        title = title_match.group(1) if title_match else None
        
        # Если заголовок не найден, используем первые слова текста
        if not title and post_text:
            title = post_text[:50] + "..." if len(post_text) > 50 else post_text
        
        # ПУБЛИКАЦИЯ В VK
        if platform == "vk" or (not platform and any(word in user_input for word in ["vk", "вк"])):
            if not post_text:
                return "❌ Ошибка: Не указан текст поста для публикации в VK"
            
            # Извлекаем ID группы, если указан
            group_id = None
            group_match = re.search(r'группа[:\s]+(\d+)', user_request, re.IGNORECASE)
            if group_match:
                group_id = int(group_match.group(1))
            
            result = await publish_vk_post(post_text, None, group_id, state)
            return result
        
        # ПУБЛИКАЦИЯ В FACEBOOK
        elif platform == "facebook" or (not platform and any(word in user_input for word in ["facebook", "фейсбук"])):
            if not post_text:
                return "❌ Ошибка: Не указан текст поста для публикации в Facebook"
            
            result = await publish_facebook_post(post_text, None, state)
            return result
        
        # ПУБЛИКАЦИЯ В TELEGRAM
        elif platform == "telegram" or (not platform and any(word in user_input for word in ["telegram", "телеграм"])):
            if not post_text:
                return "❌ Ошибка: Не указан текст сообщения для отправки в Telegram"
            
            # Извлекаем ID канала
            channel_match = re.search(r'канал[:\s]+([@\w-]+)', user_request, re.IGNORECASE)
            channel_id = channel_match.group(1) if channel_match else None
            
            if not channel_id:
                # Пытаемся найти в секретах
                secrets = state.get("secrets", []) if state else []
                for secret in secrets:
                    name = secret.get("name", "").lower()
                    if "telegram" in name and "channel" in name:
                        channel_id = secret.get("value")
                        break
                
                # Если не найден в секретах, проверяем переменную окружения
                if not channel_id:
                    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")
                    if channel_id:
                        logger.info("✅ Telegram Channel ID найден в переменной окружения TELEGRAM_CHANNEL_ID")
                
                if not channel_id:
                    return "❌ Ошибка: Не указан ID канала Telegram. Укажите: канал: @channel_name или установите TELEGRAM_CHANNEL_ID в переменных окружения"
            
            result = await publish_telegram_message(post_text, channel_id, None, None, "HTML", state)
            return result
        
        # ПУБЛИКАЦИЯ В TWITTER
        elif platform == "twitter" or (not platform and any(word in user_input for word in ["twitter", "твиттер", "твит"])):
            if not post_text:
                return "❌ Ошибка: Не указан текст твита"
            
            result = await publish_twitter_post(post_text, state)
            return result
        
        # ПУБЛИКАЦИЯ В INSTAGRAM
        elif platform == "instagram" or (not platform and any(word in user_input for word in ["instagram", "инстаграм"])):
            if not post_text:
                return "❌ Ошибка: Не указан текст подписи для Instagram"
            
            # Для Instagram нужен URL изображения
            image_match = re.search(r'изображение[:\s]+([^\s]+)', user_request, re.IGNORECASE)
            image_url = image_match.group(1) if image_match else None
            
            if not image_url:
                return "❌ Ошибка: Для публикации в Instagram требуется URL изображения. Укажите: изображение: URL"
            
            result = await publish_instagram_post(image_url, post_text, state)
            return result
        
        # ПУБЛИКАЦИЯ НА САЙТЕ
        elif platform == "website" or (not platform and any(word in user_input for word in ["сайт", "website", "wordpress", "drupal", "cms"])):
            if not post_text:
                return "❌ Ошибка: Не указан текст поста для публикации на сайте"
            
            # Определяем тип CMS
            cms_type = "wordpress"
            use_mcp = False
            
            # Если пользователь явно просит использовать MCP
            if "mcp" in user_input.lower():
                cms_type = "mcp"
                use_mcp = True
                
                # Проверяем доступные MCP инструменты
                mcp_tools = state.get("mcp_tools", []) if state else []
                logger.info(f"[SOCIAL_MEDIA_AGENT] Запрос на использование MCP. Доступно MCP инструментов: {len(mcp_tools)}")
                
                if mcp_tools:
                    mcp_names = [tool.get("name", "unknown") for tool in mcp_tools]
                    logger.info(f"[SOCIAL_MEDIA_AGENT] Доступные MCP инструменты: {mcp_names}")
                    
                    # Ищем подходящие инструменты для работы с сайтом
                    website_tools = []
                    for tool in mcp_tools:
                        tool_name = tool.get("name", "").lower()
                        tool_desc = tool.get("description", "").lower()
                        # Ищем инструменты для работы с сайтом/новостями
                        if any(keyword in tool_name or keyword in tool_desc for keyword in ["news", "новость", "post", "publish", "create", "website", "site", "cms", "article"]):
                            website_tools.append(tool)
                    
                    if website_tools:
                        logger.info(f"[SOCIAL_MEDIA_AGENT] Найдено {len(website_tools)} подходящих MCP инструментов для сайта")
                        # Используем первый подходящий инструмент
                        tool_name = website_tools[0].get("name")
                        logger.info(f"[SOCIAL_MEDIA_AGENT] Используем MCP инструмент: {tool_name}")
                    else:
                        # Если нет подходящих инструментов, сообщаем пользователю
                        available_names = ", ".join(mcp_names)
                        return f"""ℹ️ MCP инструменты доступны, но нет подходящих для публикации на сайте.

Доступные MCP инструменты: {available_names}

Для публикации на сайте через MCP нужен MCP сервер с инструментами для работы с сайтом (например, create_news, publish_post, add_article и т.д.).

Попробуйте:
1. Настроить MCP сервер с инструментами для работы с сайтом
2. Или использовать обычную публикацию через API (WordPress, Drupal)"""
            elif "drupal" in user_input:
                cms_type = "drupal"
            elif "custom" in user_input or "кастом" in user_input:
                cms_type = "custom"
            
            # Извлекаем статус публикации
            status = "publish"
            if "черновик" in user_input or "draft" in user_input:
                status = "draft"
            elif "ожидание" in user_input or "pending" in user_input:
                status = "pending"
            
            result = await publish_website_post(
                title or "Новый пост",
                post_text,
                cms_type,
                status,
                None,
                None,
                None,
                use_mcp,
                state
            )
            return result
        
        # ОБНОВЛЕНИЕ СТРАНИЦЫ НА САЙТЕ
        elif any(word in user_input for word in ["обновить", "изменить", "редактировать", "update", "edit"]):
            # Извлекаем ID страницы
            page_id_match = re.search(r'(?:страница|страницу|post|page|id)[:\s]+(\d+)', user_request, re.IGNORECASE)
            page_id = int(page_id_match.group(1)) if page_id_match else None
            
            if not page_id:
                return "❌ Ошибка: Не указан ID страницы для обновления. Укажите: страница: ID"
            
            # Определяем тип CMS
            cms_type = "wordpress"
            use_mcp = False
            
            if "mcp" in user_input:
                cms_type = "mcp"
                use_mcp = True
            elif "drupal" in user_input:
                cms_type = "drupal"
            
            result = await update_website_page(page_id, post_text, title, cms_type, use_mcp, state)
            return result
        
        # По умолчанию - показываем помощь
        else:
            mcp_tools = state.get("mcp_tools", []) if state else []
            news_tools = [tool.get("name", "") for tool in mcp_tools if any(keyword in tool.get("name", "").lower() for keyword in ["news", "новость", "post", "get", "list"])]
            
            help_text = """📱 **Social Media Agent - Помощь**

Доступные команды:

**ПОЛУЧЕНИЕ НОВОСТЕЙ С САЙТА И ПУБЛИКАЦИЯ:**
• "взять последнюю новость с сайта и опубликовать в Telegram" - получит новость через MCP и опубликует
• "получить новость с сайта и вывести в телеграм" - получит новость через MCP и опубликует
• Для получения новостей используй доступные MCP инструменты, затем social_media_agent для публикации

**Публикация в социальных сетях:**
• "опубликовать в Telegram: 'Текст сообщения'" - прямая публикация в Telegram
• "вывести в телеграм: 'Текст сообщения'" - публикация в Telegram
• "опубликовать в VK: 'Текст поста'" - публикация в VK
• "пост в Facebook: 'Текст поста'" - публикация в Facebook
• "твит: 'Текст твита'" - публикация в Twitter
• "пост в Instagram изображение: URL подпись: 'Текст'" - публикация в Instagram

**Публикация на сайте:**
• "опубликовать на сайте заголовок: 'Заголовок' текст: 'Содержимое'" - публикация на WordPress
• "добавить новость на сайт через MCP: 'Текст'" - публикация через MCP сервер
• "публикация в Drupal: 'Текст'" - публикация в Drupal

**Обновление страницы:**
• "обновить страницу ID: 123 текст: 'Новый текст'" - обновление страницы на сайте
"""
            
            if news_tools:
                help_text += f"\n**Доступные MCP инструменты для получения новостей:**\n"
                for tool_name in news_tools:
                    help_text += f"• {tool_name}\n"
                help_text += "\n**Как использовать для получения новости и публикации:**\n"
                help_text += f"1. Вызови MCP инструмент '{news_tools[0]}' для получения последней новости\n"
                help_text += "2. Используй social_media_agent для публикации полученной новости в Telegram\n"
                help_text += "   Формат: \"опубликовать в Telegram: '[текст новости]'\"\n"
            
            help_text += "\n**Примечания:**\n"
            help_text += "• Для работы требуется настройка секретов (токены API) в настройках пользователя\n"
            help_text += "• Для MCP требуется подключенный MCP сервер с инструментами для работы с сайтом\n"
            help_text += "• Текст можно указывать в кавычках или после ключевых слов (текст:, сообщение:, пост:)\n"
            
            return help_text
    
    except Exception as e:
        logger.error(f"[SOCIAL_MEDIA_AGENT] _social_media_agent_impl: ОШИБКА: {e}", exc_info=True)
        return f"❌ Ошибка обработки запроса: {str(e)}"


# Создаем узел графа
async def social_media_agent_node(state: SocialMediaAgentState) -> dict:
    """Узел графа для social_media_agent"""
    logger.info(f"[SOCIAL_MEDIA_AGENT] social_media_agent_node вызван")
    user_request = state.get("user_request", "")
    platform = state.get("platform")
    user_id = state.get("user_id", "default_user")
    
    # Получаем секреты и MCP инструменты из state
    tool_state = {}
    if hasattr(state, "get"):
        # Получаем секреты
        secrets = state.get("secrets", [])
        tool_state["secrets"] = secrets if isinstance(secrets, list) else []
        
        # Получаем MCP инструменты (если доступны)
        mcp_tools = state.get("mcp_tools", [])
        tool_state["mcp_tools"] = mcp_tools if isinstance(mcp_tools, list) else []
    
    result = await _social_media_agent_impl(
        user_request=user_request,
        platform=platform,
        user_id=user_id,
        state=tool_state
    )
    
    return {"result": result, "error": None}


# Создаем граф
def create_social_media_graph():
    """Создание графа social_media_agent"""
    
    workflow = StateGraph(SocialMediaAgentState)
    
    # Добавляем узел
    workflow.add_node("social_media_agent", social_media_agent_node)
    
    # Добавляем ребра
    workflow.add_edge(START, "social_media_agent")
    workflow.add_edge("social_media_agent", END)
    
    # Компилируем граф
    return workflow.compile()


# Создаем экземпляр графа
graph = create_social_media_graph()


# @tool декоратор для экспорта как инструмента
@tool
async def social_media_agent(
    user_request: str,
    platform: Optional[str] = None,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Агент для работы с социальными сетями и веб-сайтами
    
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Параметр называется user_request (НЕ query, НЕ task_type, НЕ action)!
    Всегда передавай запрос пользователя в параметр user_request.
    
    ПРАВИЛЬНЫЙ ФОРМАТ ВЫЗОВА:
    social_media_agent(user_request="взять последнюю новость с сайта и опубликовать в Telegram")
    social_media_agent(user_request="опубликовать в Telegram: 'Текст сообщения'")
    social_media_agent(user_request="опубликовать на сайте заголовок: 'Заголовок' текст: 'Содержимое'")
    
    НЕПРАВИЛЬНО (НЕ ДЕЛАЙ ТАК):
    ❌ social_media_agent(query="опубликовать в Telegram") - параметр query не существует!
    ❌ social_media_agent(action="publish") - параметр action не существует!
    
    Публикует посты в социальных сетях (VK, Facebook, Instagram, Twitter, Telegram)
    и на веб-сайтах (WordPress, Drupal, кастомные CMS, через MCP).
    
    ВАЖНО: Агент умеет получать новости с сайта и публиковать их в соц. сетях!
    
    Поддерживает:
    - ПОЛУЧЕНИЕ НОВОСТЕЙ С САЙТА через MCP инструменты и публикацию в Telegram/VK/другие платформы
    - Публикацию постов в соц. сетях (VK, Facebook, Instagram, Twitter, Telegram)
    - Публикацию новостей на сайтах через API
    - Публикацию через MCP сервер
    - Обновление страниц на сайтах
    
    Примеры использования:
    - "взять последнюю новость с сайта и опубликовать в Telegram" - получит новость через MCP и опубликует в Telegram
    - "получить новость с сайта и вывести в телеграм" - получит новость через MCP и опубликует в Telegram
    - "опубликовать в Telegram: 'Текст сообщения'" - прямая публикация текста в Telegram
    - "опубликовать на сайте заголовок: 'Заголовок' текст: 'Содержимое'" - публикация на сайте
    
    Args:
        user_request: Запрос пользователя (например, "взять новость с сайта и опубликовать в Telegram")
        platform: Платформа (vk, facebook, instagram, twitter, telegram, website) - опционально
        user_id: Идентификатор пользователя
    """
    logger.info(f"[SOCIAL_MEDIA_AGENT] social_media_agent tool вызван: user_request='{user_request}', platform={platform}, user_id={user_id}")
    
    # Получаем user_id из state, если он не передан явно
    if (not user_id or user_id == "default_user") and state and isinstance(state, dict):
        user_id_from_state = state.get("user_id")
        if user_id_from_state and user_id_from_state != "default_user":
            user_id = user_id_from_state
    
    # Загружаем секреты для текущего пользователя
    secrets = []
    if user_id and user_id != "default_user":
        try:
            from giga_agent.utils.user_tokens import get_all_user_secrets
            all_secrets = await get_all_user_secrets(user_id)
            if all_secrets:
                secrets = all_secrets
                logger.info(f"[SOCIAL_MEDIA_AGENT] Загружено {len(all_secrets)} секретов для user_id={user_id}")
        except Exception as e:
            logger.error(f"[SOCIAL_MEDIA_AGENT] Ошибка загрузки секретов: {e}")
    
    # Обновляем state с секретами и MCP инструментами
    if state and isinstance(state, dict):
        state["secrets"] = secrets
        # MCP инструменты уже должны быть в state["mcp_tools"] из tool_graph.py
        # Если mcp_tools не переданы, инициализируем пустым списком
        if "mcp_tools" not in state:
            state["mcp_tools"] = []
    
    # Вызываем внутреннюю реализацию
    return await _social_media_agent_impl(
        user_request=user_request,
        platform=platform,
        user_id=user_id,
        state=state
    )

