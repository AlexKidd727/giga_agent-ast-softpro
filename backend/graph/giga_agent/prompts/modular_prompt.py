"""
Модульная система промптов для оптимизации размера контекста.

Вместо одного большого промпта (13500+ токенов), система загружает
только необходимые модули в зависимости от типа запроса.
"""

from typing import List, Set, Optional
import logging

logger = logging.getLogger(__name__)


# ============================================================
# БАЗОВЫЙ МОДУЛЬ (всегда загружается) ~800 токенов (оптимизирован)
# ============================================================
CORE_PROMPT = """Текущая дата: {current_date}

Ты - GigaAgent, интеллектуальный ассистент.

**Основные правила:**
1. Отвечай кратко и по существу
2. Используй инструменты для выполнения задач (если они доступны)
3. Не придумывай данные - если не знаешь, скажи об этом
4. Жди результата инструмента перед продолжением

{rag_info}
{user_instructions}
{user_secrets}

Язык общения: **{language}**
"""


# ============================================================
# МОДУЛЬ РАЗМЫШЛЕНИЙ (для сложных задач) ~800 токенов
# ============================================================
THINKING_MODULE = """
**РЕЖИМ РАЗМЫШЛЕНИЯ**
Перед любым действием используй <thinking>:
1. Что нужно сделать?
2. Какой инструмент подходит?
3. Есть ли все параметры?
После </thinking> вызывай инструмент.

Пример:
```
<thinking>
Пользователь просит показать портфель. Это задача для tinkoff_agent.
</thinking>
Вызываю tinkoff_agent.
```
"""


# ============================================================
# МОДУЛЬ TINKOFF (для ЛИЧНОГО портфеля) ~600 токенов
# ============================================================
TINKOFF_MODULE = """
**TINKOFF_AGENT** - работа с ЛИЧНЫМ брокерским счетом Tinkoff Invest
Используй ТОЛЬКО для:
- МОЙ портфель, МОИ позиции, МОИ акции
- Графики тикеров (SBER, GAZP, IRKT, SPCE и т.д.)
- Ордера, операции, котировки из Tinkoff

*** КРИТИЧЕСКИ ВАЖНО - ПРАВИЛО #1 (для ВСЕХ моделей, включая DeepSeek): ***
При вызове tinkoff_agent передавай запрос пользователя ДОСЛОВНО, БЕЗ ИЗМЕНЕНИЙ!
НЕ расширяй запрос, НЕ добавляй информацию, НЕ перефразируй, НЕ добавляй детали!
Сохраняй оригинальную формулировку запроса пользователя ПОЛНОСТЬЮ!

Примеры ПРАВИЛЬНОГО использования:
- Пользователь: "покажи мой портфель акций" 
  -> tinkoff_agent(user_request="покажи мой портфель акций")
  
- Пользователь: "график SBER" 
  -> tinkoff_agent(user_request="график SBER")
  
- Пользователь: "покажи график SPCE" 
  -> tinkoff_agent(user_request="покажи график SPCE")
  
- Пользователь: "купи 10 акций GAZP" 
  -> tinkoff_agent(user_request="купи 10 акций GAZP")

*** НЕПРАВИЛЬНО (НЕ ДЕЛАЙ ТАК!): ***
- Пользователь: "покажи график SPCE"
  НЕПРАВИЛЬНО: tinkoff_agent(user_request="Покажи график акций Virgin Galactic (SPCE) за последний месяц с техническими индикаторами")
  ПРАВИЛЬНО: tinkoff_agent(user_request="покажи график SPCE")

- Пользователь: "график SBER"
  НЕПРАВИЛЬНО: tinkoff_agent(user_request="Покажи график акций Сбербанка (SBER) за последний месяц")
  ПРАВИЛЬНО: tinkoff_agent(user_request="график SBER")

**ПОВТОРЯЮ ДЛЯ ЯСНОСТИ (это критически важно!):**
1. Передавай запрос пользователя ДОСЛОВНО, БЕЗ ИЗМЕНЕНИЙ!
2. НЕ расширяй запрос, НЕ добавляй информацию, НЕ перефразируй!
3. НЕ добавляй названия компаний (Virgin Galactic, Сбербанк и т.д.)!
4. НЕ добавляй временные периоды (за последний месяц, за год и т.д.)!
5. НЕ добавляй технические детали (с индикаторами, с объемами и т.д.)!
6. Сохраняй оригинальную формулировку запроса пользователя ПОЛНОСТЬЮ!

Если пользователь написал "покажи график SPCE", передавай именно "покажи график SPCE", а НЕ "Покажи график акций Virgin Galactic (SPCE) за последний месяц с техническими индикаторами"!

**КРИТИЧЕСКИ ВАЖНО - ОБРАБОТКА РЕЗУЛЬТАТОВ:**
Если tinkoff_agent возвращает результат с "status": "success" и "giga_attachments", это означает, что график УЖЕ создан!
Если результат содержит "chart_created": true - график УЖЕ создан!
НЕ вызывай tinkoff_agent повторно! НЕ пытайся создать график снова!
Просто сообщи пользователю, что график успешно создан и показывается в giga_attachments.
"""


# ============================================================
# МОДУЛЬ FINANCIAL (для информации о рынках и тикерах) ~500 токенов
# ============================================================
FINANCIAL_MODULE = """
**PROCESS_FINANCIAL_QUESTION** - финансовый консультант по фондовым рынкам и криптовалюте
Используй для ИНФОРМАЦИИ о рынках, тикерах, анализа:
- Информация по тикеру (AAPL, TSLA, SPCE, BTC, ETH)
- "Что происходит с акцией X?"
- Новости, события, влияние на цену
- Сравнение активов/секторов
- Обзор рынка, тренды, прогнозы

Примеры:
- "покажи информацию по акции SPCE" -> process_financial_question
- "что происходит с AAPL?" -> process_financial_question
- "сравни SBER и GAZP" -> process_financial_question
- "новости по криптовалюте" -> process_financial_question

**КРИТИЧНО**: Если нужна ИНФОРМАЦИЯ о тикере (не из личного портфеля) - используй process_financial_question!
"""


# ============================================================
# МОДУЛЬ EMAIL (для почтовых запросов) ~500 токенов
# ============================================================
EMAIL_MODULE = """
**EMAIL_AGENT** - Агент для работы с почтовыми ящиками

Используй для: чтение/отправка писем, управление ящиками.

ВАЖНО: Параметр называется user_request (НЕ query, НЕ task_type, НЕ action)!

ПРАВИЛЬНЫЙ ФОРМАТ ВЫЗОВА:
email_agent(user_request="покажи последние письма из ящика alexis")
email_agent(user_request="прочитать письма", email_account="alexis@example.com")
email_agent(user_request="отправить письмо на test@example.com с темой 'Привет'")

Примеры запросов:
- "покажи письма" -> email_agent(user_request="покажи письма")
- "отправь письмо на test@mail.ru" -> email_agent(user_request="отправь письмо на test@mail.ru")
- "непрочитанные письма" -> email_agent(user_request="непрочитанные письма")
- "покажи последние письма из ящика alexis" -> email_agent(user_request="покажи последние письма из ящика alexis")

КРИТИЧНО: Всегда передавай запрос пользователя в параметр user_request!
"""


# ============================================================
# МОДУЛЬ PC MANAGEMENT (для работы с ПК) ~500 токенов
# ============================================================
PC_MODULE = """
**PC MANAGEMENT (MCP)**
Инструменты для работы с компьютером пользователя (Windows):

- `search_files` - поиск файлов/папок
- `list_directory` - содержимое директории
- `open_file` / `read_file` / `create_file` - работа с файлами
- `run_program` - запуск программ
- `get_system_info` - информация о системе
- `get_process_list` / `kill_process` - управление процессами
- `open_windows` / `close_window` - управление окнами

**ВАЖНО**: Только для дисков C:, D: и т.д., НЕ для Docker-контейнера!
"""


# ============================================================
# МОДУЛЬ PYTHON/CODE (для кода) ~400 токенов
# ============================================================
CODE_MODULE = """
**PYTHON**
Используй `python` для: расчеты, графики, анализ данных, работа с файлами.

Правила:
- Сохраняй файлы в /home/jupyter/
- Для графиков: `![название](attachment:путь)`
- Для скачивания: `[ссылка](file:/home/jupyter/путь)`
- Переменные сохраняются между вызовами (Jupyter)
- Для кластеризации: UMAP + HDBSCAN
{repl_inner_tools}
"""


# ============================================================
# МОДУЛЬ ПОИСКА ~300 токенов
# ============================================================
SEARCH_MODULE = """
**ПОИСК**
- `search` - быстрый поиск (макс 6 слов в запросе)
- `researcher_agent` - глубокое исследование
- `get_urls` - анализ веб-страниц

Разбивай сложные запросы на простые. Если не находит - переведи на английский.
"""


# ============================================================
# МОДУЛЬ ЮРИСТА ~200 токенов
# ============================================================
LAWYER_MODULE = """
**LAWYER_AGENT**
Используй для юридических вопросов: кодексы (УК, ГК, ТК, НК, КоАП), 
статьи законов, права и обязанности, судебные процедуры.
"""


# ============================================================
# МОДУЛЬ КАРЬЕРЫ ~200 токенов  
# ============================================================
CAREER_MODULE = """
**CAREER_AGENT**
Используй для: анализ резюме, поиск вакансий, отклики, 
авторизация на hh.ru/Работа.ру, подготовка к собеседованию.
"""


# ============================================================
# МОДУЛЬ МЕДИА ~300 токенов
# ============================================================
MEDIA_MODULE = """
**МЕДИА-ИНСТРУМЕНТЫ**
- `gen_image` - генерация изображений
- `ask_about_image` - анализ изображений
- `transcribe_audio` - распознавание речи
- `generate_presentation` - создание презентаций
- `create_landing` - создание веб-страниц
"""


# ============================================================
# МОДУЛЬ ОБРАБОТКИ РЕЗУЛЬТАТОВ ~400 токенов
# ============================================================
RESULTS_MODULE = """
**ОБРАБОТКА РЕЗУЛЬТАТОВ АГЕНТОВ**
Когда агент возвращает результат:

1. `status: "success"` или `"success": true` - задача ВЫПОЛНЕНА, сообщи пользователю
2. `giga_attachments` - файлы созданы, покажутся автоматически
3. `chart_created: true` - график УЖЕ создан, НЕ создавайте его повторно!
4. Строка с данными - прочитай и покажи пользователю

**КРИТИЧЕСКИ ВАЖНО:**
- Если результат содержит "status": "success" и "giga_attachments" - задача ВЫПОЛНЕНА!
- Если результат содержит "chart_created": true - график УЖЕ создан, НЕ вызывай агента повторно!
- НЕ вызывай агента повторно после успешного результата!
- Просто сообщи пользователю, что задача выполнена и результат доступен в giga_attachments.
"""


# ============================================================
# МОДУЛЬ DEPLOYHUB (для работы с VPS проектами) ~400 токенов
# ============================================================
DEPLOYHUB_MODULE = """
**DEPLOYHUB MCP** - управление проектами на VPS серверах
Инструменты для работы с VPS проектами из DeployHub (НЕ путать с list_projects сайта!):

- `deployhub_list_projects` - список всех VPS проектов (IP, домен, тип деплоя, статус)
- `deployhub_get_project` - информация о VPS проекте по ID
- `deployhub_search_projects` - поиск VPS проектов по имени/домену/IP
- `deployhub_list_hostings` - список хостинг-провайдеров
- `deployhub_get_uploads` - история загрузок проекта
- `deployhub_stats` - статистика по базе VPS проектов
- `deployhub_get_deploy_data` - данные для деплоя (с паролями)

Примеры:
- "покажи мои проекты на VPS" -> deployhub_list_projects
- "найди проект ast-softpro" -> deployhub_search_projects
- "информация о проекте 5" -> deployhub_get_project
- "список хостингов" -> deployhub_list_hostings

**КРИТИЧНО**: Для VPS проектов используй deployhub_* инструменты, НЕ list_projects!
"""


# ============================================================
# МОДУЛЬ DEPLOY AGENT (для деплоя на VPS) ~400 токенов
# ============================================================
DEPLOY_AGENT_MODULE = """
**DEPLOY_AGENT** - деплой приложений на VPS серверы
Используй для развертывания проектов на удаленных серверах:

- Настройка сервера (установка пакетов, firewall)
- Docker/Docker Compose деплой
- Настройка NGINX (reverse proxy, static files)
- SSL сертификаты через Certbot/Let's Encrypt
- Управление сервисами (systemd)

Примеры:
- "задеплой проект на VPS" -> deploy_agent_tool
- "настрой nginx для домена" -> deploy_agent_tool
- "получи SSL сертификат" -> deploy_agent_tool
- "перезапусти docker контейнер" -> deploy_agent_tool

**ВАЖНО**: Для получения данных проекта сначала используй DeployHub MCP (get_project_for_deploy)!
"""


# ============================================================
# МОДУЛЬ ПЕРЕКЛЮЧЕНИЯ ПРОВАЙДЕРОВ LLM ~400 токенов
# ============================================================
PROVIDER_MODULE = """
**ПЕРЕКЛЮЧЕНИЕ ПРОВАЙДЕРОВ LLM**

**КРИТИЧЕСКИ ВАЖНО**: Когда пользователь просит переключить провайдера (например, "переключи провайдера на deepseek", "переключи на openai", "используй deepseek"), ВСЕГДА используй инструмент `switch_provider`!

Система поддерживает три провайдера LLM:
1. OpenRouter (openrouter) - через OpenRouter.ai, множество моделей
2. DeepSeek (deepseek) - прямой API, модель deepseek-reasoner
3. OpenAI (openai) - прямой API, модель gpt-4o

**Инструменты для переключения провайдеров:**
- `switch_provider` - **ОСНОВНОЙ инструмент для переключения провайдера**. Используй его, когда пользователь просит:
  - "переключи провайдера на deepseek/openai/openrouter"
  - "переключи на deepseek/openai/openrouter"
  - "используй deepseek/openai/openrouter"
  - "смени провайдера на ..."
- `get_current_provider` - получение информации о текущем провайдере и модели
- `list_providers` - получение списка доступных провайдеров с информацией о них

**НЕ используй `get_openrouter_models` для переключения провайдера!** Это инструмент только для получения списка моделей OpenRouter, а не для переключения провайдера.

Примеры:
- "переключи провайдера на deepseek" -> switch_provider(provider="deepseek")
- "переключи на openai" -> switch_provider(provider="openai")
- "используй deepseek" -> switch_provider(provider="deepseek")
- "какой провайдер сейчас" -> get_current_provider()
- "список провайдеров" -> list_providers()
"""


# ============================================================
# МОДУЛЬ OPENROUTER (для управления моделями OpenRouter) ~300 токенов
# ============================================================
OPENROUTER_MODULE = """
**УПРАВЛЕНИЕ МОДЕЛЯМИ OPENROUTER**
Система использует модели OpenRouter.ai. Инструменты для управления:

- `openrouter_models` / `get_openrouter_models` - список доступных моделей с их ID
- `switch_model` / `switch_openrouter_model` - переключение на другую модель OpenRouter
- `get_current_openrouter_model` - текущая модель OpenRouter
- `check_openrouter_limits` - лимиты API

**ВАЖНО**: Эти инструменты работают ТОЛЬКО с моделями OpenRouter. Для переключения между провайдерами (DeepSeek, OpenAI, OpenRouter) используй `switch_provider`!

**ВАЖНО**: Для смены модели OpenRouter сначала получи список доступных моделей через `openrouter_models`,
затем используй точный model_id (например, `google/gemma-3-27b-it:free`) для `switch_model`.

Примеры:
- "смени модель на Gemma" -> openrouter_models (чтобы найти точный ID), затем switch_model
- "какие модели доступны" -> openrouter_models
- "текущая модель" -> get_current_openrouter_model
"""


# ============================================================
# ДРУГИЕ ИНСТРУМЕНТЫ ~200 токенов
# ============================================================
OTHER_TOOLS_MODULE = """
**ДРУГИЕ ИНСТРУМЕНТЫ**
- `weather` - погода
- `calendar_agent` - Google Calendar
- `browser_task` - автоматизация браузера
- `mysql_query` - SQL запросы
- `personalize` - сохранение предпочтений пользователя
- `get_documents` - RAG база знаний
"""


# ============================================================
# ОПРЕДЕЛЕНИЕ РЕЛЕВАНТНЫХ МОДУЛЕЙ
# ============================================================

# Ключевые слова для определения нужных модулей
# ВАЖНО: порядок проверки имеет значение - более специфичные паттерны первыми
MODULE_KEYWORDS = {
    # provider - переключение провайдеров LLM (ПРОВЕРЯЕТСЯ ПЕРВЫМ, т.к. более специфично)
    "provider": ["переключи провайдера", "переключи на", "переключи провайдер",
                 "смени провайдера", "смени провайдер", "поменяй провайдера",
                 "используй deepseek", "используй openai", "используй openrouter",
                 "переключись на deepseek", "переключись на openai", "переключись на openrouter",
                 "какой провайдер", "текущий провайдер", "список провайдеров",
                 "провайдер deepseek", "провайдер openai", "провайдер openrouter",
                 "deepseek", "openai", "gpt-4o", "gpt-4", "gpt-3.5"],
    # openrouter - управление моделями OpenRouter (НЕ провайдеры!)
    "openrouter": ["смени модель", "переключи модель", "сменить модель", "поменяй модель",
                   "какие модели", "доступные модели", "список модел", "список моделей",
                   "покажи модели", "модель openrouter", "проверенные модели",
                   "gemma", "mistral", "devstral", "llama", "qwen",
                   "текущая модель", "какая модель", "лимиты api", "лимиты модел",
                   "gpt-oss", "nemotron", "xiaomi", "mimo"],
    # deployhub - проекты на VPS серверах
    "deployhub": ["vps", "проект на vps", "мои проекты", "список проектов",
                  "deployhub", "хостинг", "сервер", "проекты на сервер",
                  "покажи проекты", "мои сайты", "домен", "деплой"],
    # deploy_agent - деплой на VPS
    "deploy_agent": ["задеплой", "развернуть", "деплой", "deploy", 
                     "настрой nginx", "ssl сертификат", "certbot",
                     "docker compose", "перезапусти контейнер"],
    # financial - информация О тикерах/рынках (не личный портфель)
    # Проверяется ПЕРЕД tinkoff, т.к. более специфичный
    "financial": ["информаци по акци", "что происходит с", "новости по", 
                  "сравни акци", "прогноз по", "анализ акци", "обзор рынк",
                  "криптовалют", "btc", "eth", "bitcoin", "ethereum",
                  "spce", "aapl", "tsla", "msft", "amzn", "nvda", "meta",
                  "что с акци", "как дела у", "перспектив", "стоит ли покупать"],
    # tinkoff - ЛИЧНЫЙ портфель пользователя
    "tinkoff": ["мой портфель", "мои позиции", "мои акции", "моих акций",
                "портфель акций", "позиции", "ордер", 
                "график", "tinkoff", "купи", "продай", "котировк",
                "покажи портфель", "открой портфель"],
    "email": ["письм", "почт", "email", "mail", "ящик", "отправ", "inbox"],
    "pc": ["файл", "папк", "директор", "программ", "процесс", "окно", "окна",
           "диск", "открой", "запусти", "найди файл", "найди папк", "систем"],
    "code": ["код", "python", "скрипт", "данны", "расчет", "таблиц",
             "excel", "csv", "фильтр", "сортир"],
    "search": ["найди", "поиск", "search", "исследован", "узнай",
               "что такое", "как работает", "расскажи о", "расскажи про"],
    "lawyer": ["закон", "кодекс", "статья", "право", "суд", "иск", "юрид",
               "ук рф", "гк рф", "тк рф", "нк рф", "коап"],
    "career": ["резюме", "вакансия", "работ", "hh.ru", "собеседован", "карьер"],
    "media": ["изображен", "картинк", "фото", "презентац", "аудио", "видео",
              "генерир", "создай картин", "сделай фото"],
}


def detect_modules_needed(query: str, tools_available: List[str] = None, request_classification: str = None) -> Set[str]:
    """
    Определяет, какие модули промпта нужны для данного запроса.
    
    Args:
        query: Запрос пользователя
        tools_available: Список доступных инструментов
        request_classification: Классификация запроса (simple_question, complex_question, simple_task, complex_task)
        
    Returns:
        Множество названий нужных модулей
    """
    query_lower = query.lower().strip()
    modules_needed = set()
    
    # КРИТИЧЕСКИ ВАЖНО: Сначала проверяем на простые приветствия и математику
    # Это нужно делать ПЕРВЫМ, чтобы не добавлять лишние модули для простых запросов
    simple_greetings = ["привет", "здравствуй", "добрый день", "доброе утро", "добрый вечер", 
                       "как дела", "как поживаешь", "что нового", "помоги", "помощь", 
                       "спасибо", "благодарю", "ок", "хорошо", "понял", "да", "нет"]
    simple_math = ["сколько будет", "сколько это", "дважды два", "два плюс два", 
                  "три плюс", "два умножить", "дважды", "плюс", "минус", "умножить"]
    
    words_count = len(query_lower.split())
    
    # Если это простое приветствие (короткое, до 5 слов) - минимум модулей
    if words_count <= 5 and any(greeting in query_lower for greeting in simple_greetings):
        logger.info(f"[DETECT_MODULES] simple greeting detected ({words_count} words) - using minimal prompt (no modules)")
        return set()  # Только CORE_PROMPT
    
    # Если это простой математический вопрос (до 8 слов) - минимум модулей
    if words_count <= 8 and any(math_q in query_lower for math_q in simple_math):
        logger.info(f"[DETECT_MODULES] simple math question detected ({words_count} words) - using minimal prompt (no modules)")
        return set()  # Только CORE_PROMPT
    
    # ВАЖНО: Теперь проверяем ключевые слова для модулей (email, tinkoff и т.д.)
    # Это нужно делать ПОСЛЕ проверки на простые приветствия, чтобы не пропустить нужные модули
    # Проверяем ключевые слова для определения модулей
    # Порядок важен - более специфичные модули проверяются первыми
    # КРИТИЧЕСКИ ВАЖНО: provider проверяется ПЕРВЫМ, т.к. "переключи провайдера" более специфично, чем "openrouter"
    # Проверяем provider отдельно ПЕРЕД остальными модулями
    provider_keywords = MODULE_KEYWORDS.get("provider", [])
    for kw in provider_keywords:
        if kw in query_lower:
            modules_needed.add("provider")
            logger.info(f"[DETECT_MODULES] Provider module detected by keyword: '{kw}'")
            break
    
    # Проверяем остальные модули (но пропускаем provider, т.к. уже проверили)
    for module, keywords in MODULE_KEYWORDS.items():
        if module == "provider":  # Пропускаем provider, т.к. уже проверили
            continue
        for kw in keywords:
            if kw in query_lower:
                modules_needed.add(module)
                break
    
    # ОПТИМИЗАЦИЯ: Для simple_question используем минимальный промпт
    # НО только если не найдены специфичные модули (email, tinkoff и т.д.)
    # Если найден специфичный модуль - значит нужны инструменты, не используем минимальный промпт
    if request_classification == "simple_question" and not modules_needed:
        # Для простых вопросов БЕЗ специфичных модулей используем только CORE_PROMPT
        # Не добавляем никаких модулей для экономии токенов
        logger.info(f"[DETECT_MODULES] simple_question без специфичных модулей - using minimal prompt (no modules)")
        return set()  # Возвращаем пустое множество - только CORE_PROMPT
    
    # Если не определили конкретный модуль - добавляем базовые
    if not modules_needed:
        # Для вопросов - поиск
        if "?" in query or any(w in query_lower for w in ["что", "как", "почему", "зачем", "когда", "где", "кто"]):
            modules_needed.add("search")
        # По умолчанию - thinking и other для базового покрытия
        modules_needed.add("thinking")
        modules_needed.add("other")
        # Также добавляем search для общих запросов
        modules_needed.add("search")
    
    # Всегда добавляем модуль обработки результатов (кроме простых вопросов без модулей)
    modules_needed.add("results")
    
    # Логируем для отладки
    logger.debug(f"[DETECT_MODULES] query='{query[:50]}...' classification='{request_classification}' modules={modules_needed}")
    
    return modules_needed


def get_module_content(module_name: str) -> str:
    """Возвращает содержимое модуля по имени"""
    modules = {
        "thinking": THINKING_MODULE,
        "tinkoff": TINKOFF_MODULE,
        "financial": FINANCIAL_MODULE,
        "email": EMAIL_MODULE,
        "pc": PC_MODULE,
        "code": CODE_MODULE,
        "search": SEARCH_MODULE,
        "lawyer": LAWYER_MODULE,
        "career": CAREER_MODULE,
        "media": MEDIA_MODULE,
        "results": RESULTS_MODULE,
        "other": OTHER_TOOLS_MODULE,
        "deployhub": DEPLOYHUB_MODULE,
        "deploy_agent": DEPLOY_AGENT_MODULE,
        "provider": PROVIDER_MODULE,
        "openrouter": OPENROUTER_MODULE,
    }
    return modules.get(module_name, "")


def build_optimized_prompt(
    query: str,
    current_date: str,
    rag_info: str = "",
    user_instructions: str = "",
    user_secrets: str = "",
    language: str = "Русский",
    repl_inner_tools: str = "",
    tools_available: List[str] = None,
    force_modules: List[str] = None,
    request_classification: str = None,
) -> str:
    """
    Собирает оптимизированный промпт из нужных модулей.
    
    Args:
        query: Запрос пользователя
        current_date: Текущая дата
        rag_info: RAG информация
        user_instructions: Инструкции пользователя
        user_secrets: Секреты пользователя
        language: Язык общения
        repl_inner_tools: Внутренние инструменты REPL
        tools_available: Доступные инструменты
        force_modules: Принудительно добавить модули
        request_classification: Классификация запроса (simple_question, complex_question, simple_task, complex_task)
        
    Returns:
        Оптимизированный промпт
    """
    # Определяем нужные модули с учетом классификации
    modules_needed = detect_modules_needed(query, tools_available, request_classification)
    
    # Добавляем принудительные модули
    if force_modules:
        modules_needed.update(force_modules)
    
    # ОПТИМИЗАЦИЯ: Для простых приветствий (пустые модули) не добавляем repl_inner_tools
    # Это экономит много токенов
    if len(modules_needed) == 0:
        repl_inner_tools = ""
        logger.info(f"[build_optimized_prompt] Empty modules - skipping repl_inner_tools for token savings")
    
    # Собираем промпт
    prompt_parts = [CORE_PROMPT]
    
    # Добавляем релевантные модули
    # ВАЖНО: Если modules_needed пусто (для простых приветствий), не добавляем никаких модулей
    for module in modules_needed:
        content = get_module_content(module)
        if content:
            prompt_parts.append(content)
    
    # Собираем итоговый промпт
    # Если modules_needed пусто, full_prompt будет содержать только CORE_PROMPT
    full_prompt = "\n\n".join(prompt_parts)
    
    # Подставляем переменные
    full_prompt = full_prompt.format(
        current_date=current_date,
        rag_info=rag_info,
        user_instructions=user_instructions,
        user_secrets=user_secrets,
        language=language,
        repl_inner_tools=repl_inner_tools,
    )
    
    tokens_estimate = len(full_prompt) // 4
    logger.info(f"[MODULAR_PROMPT] Query: {query[:50]}... Classification: {request_classification} Modules: {modules_needed} Tokens: ~{tokens_estimate}")
    
    # Логируем экономию для simple_question
    if request_classification == "simple_question":
        logger.info(f"[MODULAR_PROMPT] OPTIMIZATION: simple_question - minimal prompt (~{tokens_estimate} tokens, no modules, no tools)")
    
    return full_prompt


def estimate_tokens(text: str) -> int:
    """Приблизительная оценка токенов (4 символа = 1 токен)"""
    return len(text) // 4


def get_prompt_stats(prompt: str, modules: Set[str]) -> dict:
    """Возвращает статистику промпта"""
    tokens = estimate_tokens(prompt)
    return {
        "tokens_estimate": tokens,
        "chars": len(prompt),
        "modules": list(modules),
        "modules_count": len(modules),
    }
