# Social Media Agent

Агент для работы с социальными сетями и веб-сайтами.

## Функционал

### Публикация в социальных сетях

- **VK (ВКонтакте)**: Публикация постов на стене пользователя или группы
- **Facebook**: Публикация постов на странице
- **Instagram**: Публикация постов с изображениями
- **Twitter**: Публикация твитов
- **Telegram**: Отправка сообщений в каналы и группы

### Публикация на веб-сайтах

- **WordPress**: Публикация постов через REST API
- **Drupal**: Публикация контента через REST API
- **Кастомные CMS**: Публикация через кастомный API
- **MCP сервер**: Публикация через Model Context Protocol сервер

### Обновление контента

- Обновление постов на сайтах
- Редактирование страниц

## Настройка

### Секреты для социальных сетей

Для работы с социальными сетями необходимо добавить соответствующие токены в секреты пользователя:

#### VK
- `VK_ACCESS_TOKEN` - Access Token VK API
- `VK_API_VERSION` - Версия API (по умолчанию 5.131)

#### Facebook
- `FACEBOOK_ACCESS_TOKEN` - Access Token Facebook Graph API
- `FACEBOOK_PAGE_ID` - ID страницы Facebook

#### Instagram
- `INSTAGRAM_ACCESS_TOKEN` - Access Token Instagram Graph API
- `INSTAGRAM_USER_ID` - User ID Instagram

#### Twitter
- `TWITTER_BEARER_TOKEN` - Bearer Token Twitter API v2
- Или `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_TOKEN_SECRET`

#### Telegram
- `TELEGRAM_PUBLISH_BOT_TOKEN` - Token бота Telegram для публикации новостей (рекомендуется, отдельный от интерфейсного бота)
- `TELEGRAM_BOT_TOKEN` - Token бота Telegram (используется как fallback, если `TELEGRAM_PUBLISH_BOT_TOKEN` не указан)
- `TELEGRAM_CHANNEL_ID` - ID или username канала (например, @channel_name)

### Секреты для веб-сайтов

#### WordPress
- `WORDPRESS_API_TOKEN` - Application Password или токен
- `WORDPRESS_SITE_URL` - URL сайта WordPress

#### Drupal
- `DRUPAL_API_TOKEN` - API Token Drupal
- `DRUPAL_SITE_URL` - URL сайта Drupal

#### Кастомный CMS
- `CUSTOM_CMS_API_TOKEN` - API Token
- `CUSTOM_CMS_API_URL` - URL API

### Настройка MCP сервера

Для работы через MCP сервер необходимо:

1. Настроить MCP сервер в `.docker.env`:
```bash
GIGA_AGENT_MCP_CONFIG={"website_mcp": {"transport": "sse", "url": "http://your-mcp-server:port/mcp"}}
```

2. Убедиться, что MCP сервер предоставляет инструменты для работы с сайтом:
   - `publish_post` / `create_post` / `website_publish`
   - `update_post` / `edit_post` / `website_update`

## Примеры использования

### Публикация в VK
```
опубликовать в VK: 'Привет, это тестовый пост!'
```

### Публикация в Facebook
```
пост в Facebook: 'Новости проекта'
```

### Отправка в Telegram
```
отправить в Telegram канал: @my_channel текст: 'Важное объявление'
```

### Публикация на сайте (WordPress)
```
опубликовать на сайте заголовок: 'Новая новость' текст: 'Содержимое новости'
```

### Публикация через MCP
```
добавить новость на сайт через MCP: 'Текст новости'
```

### Обновление страницы
```
обновить страницу ID: 123 текст: 'Обновленное содержимое'
```

## Архитектура

```
social_media_agent/
├── __init__.py
├── config.py              # Конфигурация и состояние
├── graph.py               # Основной граф агента
├── nodes/
│   ├── __init__.py
│   ├── social_publish.py   # Публикация в соц. сетях
│   └── website_publish.py # Публикация на сайтах
└── utils/
    ├── __init__.py
    ├── social_clients.py   # Клиенты для соц. сетей
    ├── website_clients.py  # Клиенты для CMS
    └── mcp_client.py       # Клиент для MCP
```

## Интеграция

Агент зарегистрирован в `backend/graph/giga_agent/config.py` и доступен как инструмент `social_media_agent`.

Использование в основном агенте:
```python
from giga_agent.agents.social_media_agent.graph import social_media_agent

# Вызов агента
result = await social_media_agent.ainvoke({
    "user_request": "опубликовать в VK: 'Текст поста'",
    "platform": "vk",
    "user_id": "user123",
    "state": {...}
})
```

## Примечания

- Все токены и секреты хранятся в зашифрованном виде в базе данных
- MCP инструменты автоматически доступны через `state["mcp_tools"]`
- Агент автоматически определяет платформу из текста запроса, если не указана явно
- Поддерживается извлечение текста поста из различных форматов запросов

