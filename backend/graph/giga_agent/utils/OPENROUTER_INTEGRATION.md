# Интеграция OpenRouter.ai

## Описание

Проект поддерживает использование бесплатных моделей через OpenRouter.ai. Модуль `openrouter_free_models.py` предоставляет функциональность для:
- Получения списка бесплатных моделей через API
- Автоматического обновления списка раз в сутки
- Тестирования моделей на работоспособность
- Управления состоянием моделей

## Установка

1. Убедитесь, что установлены необходимые зависимости:
```bash
pip install openai requests
```

2. Установите API ключ OpenRouter в переменных окружения:
```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

Или добавьте в `.docker.env`:
```
OPENROUTER_API_KEY=sk-or-v1-...
```

## Использование

### В проекте

Для использования модели OpenRouter в проекте, установите в `.docker.env`:

```env
GIGA_AGENT_LLM=openrouter:mistralai/devstral-2512:free
GIGA_AGENT_LLM_FAST=openrouter:mistralai/devstral-2512:free
OPENROUTER_API_KEY=sk-or-v1-...
```

### Формат модели

Модели OpenRouter указываются в формате:
```
openrouter:model_id
```

Например:
- `openrouter:mistralai/devstral-2512:free` - бесплатная модель Mistral Devstral
- `openrouter:google/gemma-3-27b-it:free` - бесплатная модель Google Gemma

### Тестирование моделей

Для тестирования доступных бесплатных моделей запустите:

```bash
python test_openrouter_models.py
```

Скрипт:
1. Загружает список бесплатных моделей из API
2. Тестирует их работоспособность
3. Выбирает лучшую модель по приоритету (работающие модели с наибольшим context_length)
4. Выводит рекомендацию для использования в проекте

### Работающие модели

По результатам последнего тестирования, работающие бесплатные модели:
- `mistralai/devstral-2512:free` (262,144 токенов) - **рекомендуется**
- `xiaomi/mimo-v2-flash:free`
- `qwen/qwen3-coder:free`
- `kwaipilot/kat-coder-pro:free`
- `tngtech/deepseek-r1t-chimera:free`
- `google/gemma-3-27b-it:free`
- `meta-llama/llama-3.2-3b-instruct:free`
- `meta-llama/llama-3.3-70b-instruct:free`
- `nousresearch/hermes-3-llama-3.1-405b:free`
- `qwen/qwen-2.5-vl-7b-instruct:free`
- `google/gemma-3n-e4b-it:free`

## Настройка таймаутов и ретраев

Для моделей OpenRouter можно настроить таймауты и количество повторных попыток:

```env
# Общие настройки для всех LLM
GIGA_AGENT_LLM_TIMEOUT=60
GIGA_AGENT_LLM_MAX_RETRIES=3

# Специфичные настройки для OpenRouter (используются, если общие не заданы)
OPENROUTER_TIMEOUT=60
OPENROUTER_MAX_RETRIES=3
```

## Использование модуля OpenRouterFreeModels

```python
from giga_agent.utils.openrouter_free_models import OpenRouterFreeModels

# Инициализация
api_key = os.getenv("OPENROUTER_API_KEY")
manager = OpenRouterFreeModels(api_key, config_dir="./openrouter_data")

# Обновление списка моделей
added, removed, all_models = manager.update_models_list()

# Получение работающих моделей
working_models = [m for m in manager.get_enabled_models() 
                  if manager.get_model_info(m).get('working', False)]

# Тестирование модели
success, error = manager.test_model("mistralai/devstral-2512:free")

# Получение информации о модели
model_info = manager.get_model_info("mistralai/devstral-2512:free")
print(f"Контекст: {model_info.get('context_length', 0)} токенов")
```

## Примечания

- Бесплатные модели имеют лимиты на количество запросов (обычно 20 запросов в минуту, 50-1000 в день в зависимости от баланса)
- Модели с суффиксом `:free` являются бесплатными
- Рекомендуется использовать модель `mistralai/devstral-2512:free` как наиболее стабильную с большим контекстом
