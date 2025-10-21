# Инструменты в GigaAgent

## Расположение инструментов в репозитории

Мы поддерживаем три уровня инструментов:

* **LLM‑tools** — функции, которые модель может вызывать напрямую через tool‑calling при выполнении графа. Реализуются в бэкенде графа ([`backend/graph/giga_agent/tools`](backend/graph/giga_agent/tools)), регистрация/включение — в [`config.py`](backend/graph/giga_agent/config.py). Возвращают компактные, сериализуемые результаты. Также могут быть вызваны из REPL-среды.
* **REPL‑tools** — функции, доступные коду, исполняемому в изолированном REPL. Их задача — дать возможность вызова бэкенд-логики с секретами (токены, env-переменные). Сейчас repl-тулы позволяют вызывать LLM: получать эмбеддинги, делать суммаризацию, анализ и пр. Мы импортируем такие функции в окружение REPL (см. папку [`backend/repl`](backend/repl)).
* **ToolServer** — серверная прослойка для вызовов, где нужны секреты (API‑ключи/токены) или доступ к внутренней инфраструктуре. И LLM‑tools, и REPL‑tools при необходимости проксируют такие операции через ToolServer; секреты остаются на стороне бэкенда (код сервера — в [`backend/graph`](backend/graph), см. таргет `make run_tool_server` в корне).

---

## Готовые инструменты&#x20;

### Поиск и веб‑данные

* **search** — интернет‑поиск через Tavily.

  * **Файл(ы):** [`backend/graph/giga_agent/tools/another.py`](backend/graph/giga_agent/tools/another.py)
  * **ENV:** `TAVILY_API_KEY`
* **get\_urls** — получить URL/контент по результатам поиска.

  * **Файл(ы):** [`backend/graph/giga_agent/tools/scraper.py`](backend/graph/giga_agent/tools/scraper.py)
  * **ENV:** `TAVILY_API_KEY`

### GitHub

* **list\_pull\_requests** — список PR в репозитории.
* **get\_pull\_request** — детали PR.
* **get\_workflow\_runs** — статусы GitHub Actions.

  * **Файл(ы):** [`backend/graph/giga_agent/tools/github.py`](backend/graph/giga_agent/tools/github.py)
  * **ENV:** `GITHUB_TOKEN`

### ВКонтакте (VK)

* **vk\_get\_posts**, **vk\_get\_comments**, **vk\_get\_last\_comments** — выборки постов/комментариев.

  * **Файл(ы):** [`backend/graph/giga_agent/tools/vk.py`](backend/graph/giga_agent/tools/vk.py)
  * **ENV:** ключи VK (service token / app credentials) `VK_TOKEN`

### Погода

* **weather** — сводка/прогноз через OpenWeatherMap.

  * **Файл(ы):** [`backend/graph/giga_agent/tools/weather.py`](backend/graph/giga_agent/tools/weather.py)
  * **ENV:** `OPENWEATHERMAP_API_KEY`

### Генерация изображений

* **generate\_image** — провайдеры: GigaChat Kandinsky / FusionBrain (Kandinsky 3.0) / OpenAI DALL‑E or gpt-image-1.

  * **Файл(ы):** [`backend/graph/giga_agent/tools/another.py`](backend/graph/giga_agent/tools/another.py)
  * **ENV:** `IMAGE_GEN_NAME` + ключи провайдера (`MAIN_GIGACHAT_*` или `KANDINSKY_API_KEY`/`KANDINSKY_SECRET_KEY` или `OPENAI_API_KEY`)

> Примечание: если ключи/ENV не заданы, связанные **service‑tools автоматически отключаются** (не попадут в список доступных для модели).

---

## Как добавить **новый LLM‑tool**

**TL;DR:** файл в [`backend/graph/giga_agent/tools/`](backend/graph/giga_agent/tools/) → регистрация в `config.py` → ENV (если нужно) → `make build_graph` → перезапуск.

1. **Создайте модуль**
   Например, `backend/graph/giga_agent/tools/my_tool.py`

2. **Опишите tool** (через LangChain Tool или простую функцию‑обёртку):

```python
# backend/graph/giga_agent/tools/my_tool.py
from typing import TypedDict, Optional
from langchain_core.tools import tool

class MyToolArgs(TypedDict, total=False):
    query: str
    limit: Optional[int]

@tool("my_tool", args_schema=MyToolArgs)
def my_tool(query: str, limit: int | None = None) -> str:
    """Короткое точное описание для модели: что делает тул и когда его вызывать."""
    # 1) валидация
    # 2) вызов внешних API/ToolServer
    # 3) возврат краткого результата (LLM «раскроет» в ответ)
    return "..."
```

3. **Зарегистрируйте тул** в [`backend/graph/giga_agent/config.py`](backend/graph/giga_agent/config.py):

* добавьте имя в `SERVICE_TOOLS`;
* если тул зависит от ENV — добавьте в `TOOLS_REQUIRED_ENVS` (включение/отключение по наличию ключей).

4. **ENV**, если требуется: пропишите переменные в `.env`/`.docker.env` (см. `env_examples/`).

5. **Соберите граф и перезапустите**:

```bash
make build_graph
# docker compose up -d   # или локальные команды запуска
```

6. **Проверьте** в UI (чат): модель должна увидеть `my_tool` по имени/описанию и уметь его вызвать.

---

## Как добавить **новый REPL‑tool**

**TL;DR:** функция в `backend/repl/repl_tools/…` → импорт в инициализацию REPL → (опц.) доступ к API через ToolServer → перезапуск REPL.

1. **Разместите функцию**
   например, `backend/repl/repl_tools/my_repl_tool.py`, затем импортируйте её там, где формируется исполняемый неймспейс REPL.

2. **ENV**, если нужно: добавьте в `.env`/`.docker.env`.
3. **Зарегистрируйте тул** в [`backend/graph/giga_agent/config.py`](backend/graph/giga_agent/config.py):

* добавьте имя в `REPL_TOOLS`;

4. **Соберите граф и перезапустите**:

```bash
make build_graph
# docker compose up -d   # или локальные команды запуска
```

> Типовые REPL‑тулы: `predict_sentiments`, `get_embeddings`, `summarize` — доступны коду, который LLM пишет в REPL, и под капотом сами ходят в LLM/API.

---

## Управление доступностью

* Без нужных ключей сервисные тулы **автоматически скрываются** (через `TOOLS_REQUIRED_ENVS`).
* Списки активных тулов и агентов централизованно задаются в `config.py` (`TOOLS`, `AGENTS`, `SERVICE_TOOLS`).

---

## Быстрые ссылки

* Каталог LLM‑tools: [`backend/graph/giga_agent/tools/`](backend/graph/giga_agent/tools)
* Регистрация/включение: [`backend/graph/giga_agent/config.py`](backend/graph/giga_agent/config.py)
* REPL‑сервис: `backend/repl/…` (добавляйте в `repl_tools/`)
* Примеры настройки ENV для GigaChat/OpenAI: [`env_examples/`](env_examples)
* Субагенты: [`SUBAGENTS.md`](SUBAGENTS.md)
