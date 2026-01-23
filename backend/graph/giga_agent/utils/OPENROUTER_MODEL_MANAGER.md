# Менеджер моделей OpenRouter с автоматическим переключением

## Описание

Модуль `openrouter_model_manager.py` предоставляет функциональность для автоматического управления моделями OpenRouter, включая:

- Автоматическое переключение на следующую доступную модель при ошибках
- Кэширование работоспособности моделей
- Отслеживание неудачных попыток использования моделей
- Получение списка рабочих бесплатных моделей
- Проверка лимитов API

## Установка

Модуль использует существующий модуль `openrouter_free_models.py` и не требует дополнительных зависимостей.

## Использование

### Базовое использование

```python
from giga_agent.utils.openrouter_model_manager import OpenRouterModelManager

# Инициализация менеджера
api_key = os.getenv("OPENROUTER_API_KEY")
manager = OpenRouterModelManager(api_key=api_key)

# Получение доступной модели
available_model = manager.get_available_model(preferred_model="mistralai/devstral-2512:free")
```

### Получение списка рабочих моделей

```python
# Получение списка всех рабочих моделей с информацией о доступности
working_models = manager.get_working_models_list()

for model in working_models:
    print(f"{model['id']}: доступна={model['available']}, неудач={model['failures']}")
```

### Проверка лимитов API

```python
# Получение детальной информации о лимитах
limits = manager.get_detailed_limits()

print(f"Лимит: {limits['limit']}")
print(f"Осталось: {limits['limit_remaining']}")
print(f"Использовано сегодня: {limits['usage_daily']}")
print(f"Есть остаток: {limits['has_remaining']}")
```

### Запись неудач и переключение

```python
# При ошибке использования модели
try:
    # ... использование модели ...
    manager.record_model_success(model_id)
except Exception as e:
    # Записываем неудачу
    manager.record_model_failure(model_id, error=str(e))
    
    # Получаем следующую доступную модель
    next_model = manager.get_next_model(model_id)
    if next_model:
        print(f"Переключение на {next_model}")
```

## Интеграция с load_llm()

Менеджер автоматически интегрирован в функцию `load_llm()` из `llm.py`. При использовании моделей OpenRouter:

1. Система автоматически проверяет доступность предпочтительной модели
2. Если модель недоступна, автоматически переключается на следующую доступную
3. При ошибках инициализации автоматически переключается на следующую модель
4. Успешное использование модели сбрасывает счетчик неудач

### Настройка через переменные окружения

```env
# Количество неудач перед переключением модели (по умолчанию 3)
OPENROUTER_MAX_FAILURES=3

# Время блокировки модели после неудач в секундах (по умолчанию 300 = 5 минут)
OPENROUTER_RETRY_AFTER_SECONDS=300
```

## API Reference

### OpenRouterModelManager

#### Методы

- `get_available_model(preferred_model: Optional[str] = None) -> Optional[str]`
  - Получение доступной модели для использования
  - Если указана предпочтительная модель и она доступна, возвращает её
  - Иначе возвращает первую доступную модель из списка рабочих

- `get_next_model(current_model: str) -> Optional[str]`
  - Получение следующей модели для переключения
  - Записывает текущую модель как недоступную
  - Возвращает следующую доступную модель

- `record_model_failure(model_id: str, error: Optional[str] = None)`
  - Запись неудачной попытки использования модели
  - При достижении максимума неудач блокирует модель на время

- `record_model_success(model_id: str)`
  - Запись успешного использования модели
  - Сбрасывает счетчик неудач

- `get_working_models_list() -> List[Dict]`
  - Получение списка рабочих моделей с информацией о доступности
  - Возвращает список словарей с полной информацией о моделях

- `get_detailed_limits() -> Dict`
  - Получение детальной информации о лимитах API
  - Возвращает словарь с информацией о лимитах и использовании

- `reset_model_failures(model_id: str)`
  - Сброс счетчика неудач для модели
  - Разблокирует модель

- `get_switching_history(limit: int = 20) -> List[Dict]`
  - Получение истории переключений моделей

## Примеры использования

### Пример 1: Получение списка доступных моделей

```python
from giga_agent.utils.openrouter_model_manager import OpenRouterModelManager

manager = OpenRouterModelManager()

# Получаем список всех рабочих моделей
models = manager.get_working_models_list()

print("Доступные модели:")
for model in models:
    if model['available']:
        print(f"  ✓ {model['id']} - {model['name']}")
        print(f"    Контекст: {model['context_length']:,} токенов")
```

### Пример 2: Проверка лимитов и переключение при необходимости

```python
from giga_agent.utils.openrouter_model_manager import OpenRouterModelManager

manager = OpenRouterModelManager()

# Проверяем лимиты
limits = manager.get_detailed_limits()

if not limits['has_remaining']:
    print("⚠ Лимит API исчерпан!")
    print(f"Сброс: {limits['limit_reset']}")
else:
    print(f"✓ Осталось кредитов: {limits['limit_remaining']}")
```

### Пример 3: Автоматическое переключение при ошибке

```python
from giga_agent.utils.openrouter_model_manager import OpenRouterModelManager
from giga_agent.utils.llm import load_llm

manager = OpenRouterModelManager()

# Пытаемся загрузить модель
try:
    llm = load_llm()
    # Используем модель
    response = llm.invoke("Привет!")
    manager.record_model_success(llm.model_name)
except Exception as e:
    # При ошибке переключаемся на следующую модель
    current_model = os.getenv("GIGA_AGENT_LLM", "").replace("openrouter:", "")
    next_model = manager.get_next_model(current_model)
    
    if next_model:
        print(f"Переключение на {next_model}")
        os.environ["GIGA_AGENT_LLM"] = f"openrouter:{next_model}"
        llm = load_llm()
    else:
        print("Нет доступных моделей для переключения")
```

## Тестирование

Для тестирования функциональности используйте скрипт:

```bash
python test_openrouter_manager.py
```

Скрипт проверяет:
- Инициализацию менеджера
- Получение лимитов API
- Получение списка рабочих моделей
- Получение доступной модели
- Историю переключений

## Примечания

- Менеджер автоматически обновляет список моделей раз в сутки
- Модели блокируются на 5 минут после 3 неудачных попыток (настраивается)
- История переключений хранится в файле `model_switching_state.json`
- Состояние моделей сохраняется между перезапусками приложения
