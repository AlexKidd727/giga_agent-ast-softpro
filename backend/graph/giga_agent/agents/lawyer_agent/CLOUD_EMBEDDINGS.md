# Облачные эмбеддинги для lawyer_agent

## Описание

`lawyer_agent` теперь поддерживает использование облачных API для создания эмбеддингов вместо локальных моделей. Это позволяет:
- Не загружать большие модели локально
- Использовать более качественные модели
- Экономить ресурсы сервера

## Поддерживаемые провайдеры

### 1. Hugging Face (локальные модели, рекомендуется)
- **Статус**: Inference API endpoint больше не поддерживается (410)
- **Рекомендация**: Используйте локальные модели через `HuggingFaceEmbeddings`
- **Модели**: Мультиязычные модели sentence-transformers (загружаются автоматически)
- **Цена**: Бесплатно (локально)
- **Альтернатива**: Настройте Inference Endpoints для облачного использования
- **Получить ключ**: https://huggingface.co/settings/tokens (для загрузки моделей)

### 2. Cohere Embed API
- **Лимит**: 1000 запросов/месяц бесплатно
- **Модели**: embed-multilingual-v3.0 (1024 dim)
- **Цена**: Бесплатно до лимита, затем $0.0001/1K токенов
- **Получить ключ**: https://dashboard.cohere.com/api-keys

### 3. OpenAI Embeddings API
- **Лимит**: Зависит от tier (бесплатный tier - 3 RPM)
- **Модели**: text-embedding-3-small (1536 dim, $0.00002/1K токенов)
- **Цена**: От $0.00002/1K токенов
- **Получить ключ**: https://platform.openai.com/api-keys
- **Прокси**: Поддерживается через `AI_PROXY_HOST`, `AI_PROXY_USERNAME`, `AI_PROXY_PASSWORD`, `AI_PROXY_PORT`

## Настройка

### Приоритет выбора провайдера

Система автоматически выбирает провайдера по приоритету:
1. `COHERE_API_KEY` → Cohere (рекомендуется для облачных эмбеддингов)
2. `OPENAI_API_KEY` → OpenAI (если уже используете OpenAI)
3. `HF_TOKEN` (или `HUGGINGFACE_API_KEY`) → Локальные модели Hugging Face (fallback)
4. Если ни один ключ не установлен → локальные модели (fallback)

**Важно:** 
- Hugging Face Inference API endpoint больше не поддерживается (старый endpoint возвращает 410)
- Для Hugging Face рекомендуется использовать локальные модели (автоматически загружаются)
- `HF_TOKEN` используется для загрузки моделей из Hugging Face Hub (для STT и локальных эмбеддингов)
- Для облачных эмбеддингов рекомендуется использовать Cohere или OpenAI

### Переменные окружения

Добавьте в ваш `.env` или `.docker.env` файл:

```bash
# Hugging Face Token (универсальный для STT и Embeddings API)
# Используется для загрузки моделей STT и для Embeddings API
HF_TOKEN=your_huggingface_token_here
HUGGINGFACE_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

# Альтернативные переменные (для обратной совместимости):
# HUGGINGFACE_API_KEY=your_huggingface_token_here
# HUGGINGFACE_HUB_TOKEN=your_huggingface_token_here

# Cohere (альтернатива)
COHERE_API_KEY=your_cohere_token_here
COHERE_EMBEDDING_MODEL=embed-multilingual-v3.0

# OpenAI (если уже используете OpenAI для LLM)
OPENAI_API_KEY=your_openai_token_here
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# AI PROXY SETTINGS (для OpenAI API через прокси, опционально)
AI_PROXY_HOST=your_proxy_host
AI_PROXY_USERNAME=your_proxy_username
AI_PROXY_PASSWORD=your_proxy_password
AI_PROXY_PORT=8080
```

### Примеры моделей

#### Hugging Face
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dim, быстрая)
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (768 dim, качественная)
- `intfloat/multilingual-e5-base` (768 dim, высокое качество)

#### Cohere
- `embed-multilingual-v3.0` (1024 dim, мультиязычная)

#### OpenAI
- `text-embedding-3-small` (1536 dim, дешевая)
- `text-embedding-3-large` (3072 dim, качественная)
- `text-embedding-ada-002` (1536 dim, старая модель)

## Использование

После настройки переменных окружения, `lawyer_agent` автоматически будет использовать облачные эмбеддинги. Никаких изменений в коде не требуется.

### Проверка работы

Система логирует используемый провайдер при инициализации:
```
INFO: Используется Hugging Face Inference API для эмбеддингов
INFO: Облачные эмбеддинги успешно инициализированы
INFO: Размер эмбеддинга: 384
```

## Fallback на локальные модели

Если облачные API недоступны или не настроены, система автоматически переключается на локальные модели HuggingFaceEmbeddings:
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`
- `intfloat/multilingual-e5-base`

## Рекомендации

1. **Для начала**: Используйте Hugging Face Inference API - бесплатно до 1000 запросов/день
2. **Для продакшена**: Рассмотрите Cohere или OpenAI для больших объемов
3. **Для экономии**: Используйте локальные модели, если есть GPU и достаточно ресурсов

## Стоимость

Примерная стоимость для 1M токенов:
- **Hugging Face**: Бесплатно (до лимита), затем ~$100
- **Cohere**: Бесплатно (до лимита), затем ~$100
- **OpenAI text-embedding-3-small**: ~$20
- **OpenAI text-embedding-3-large**: ~$130

## Технические детали

- Все провайдеры поддерживают батчинг для эффективности
- Автоматическая обработка таймаутов и ошибок
- Кэширование провайдера для избежания повторной инициализации
- Совместимость с интерфейсом LangChain через `CloudEmbeddingsWrapper`
