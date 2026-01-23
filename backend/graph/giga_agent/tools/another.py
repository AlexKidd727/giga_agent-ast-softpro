import base64
import os
import uuid
import re
from typing import List, Optional, Tuple
import httpx
from httpx import HTTPStatusError

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import (
    RunnableParallel,
    RunnablePassthrough,
)
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from pydantic import Field

from langgraph_sdk import get_client

from giga_agent.utils.jupyter import REPLUploader, RunUploadFile
from giga_agent.utils.llm import is_llm_image_inline, load_llm, upload_file_with_retry
from giga_agent.generators.image import load_image_gen
from giga_agent.generators.image.openai import SUPPORTED_IMAGE_SIZES as OPENAI_SUPPORTED_SIZES
from giga_agent.generators.image.openrouter import OPENROUTER_ASPECT_RATIOS, SUPPORTED_IMAGE_SIZES as OPENROUTER_SUPPORTED_SIZES
from giga_agent.prompts.image import IMAGE_PROMPT


@tool
async def ask_followup_question(
    question: str = Field(description="Дополнительные вопросы пользователю"),
):
    """Используй это, если тебе не хватает какой-либо информации для выполнения задачи пользователя."""
    pass


@tool
async def search(queries: List[str] = Field(description="Список поисковых запросов (ОБЯЗАТЕЛЬНО список, даже для одного запроса)")):
    """ВНИМАНИЕ: Это инструмент ПОСЛЕДНЕГО РЕЗОРТА для поиска информации в интернете.
    
    КРИТИЧЕСКИ ВАЖНО: Параметр называется `queries` (множественное число) и должен быть СПИСКОМ строк, даже для одного запроса.
    ПРАВИЛЬНО: {"queries": ["Александр Беляев биография"]}
    НЕПРАВИЛЬНО: {"query": "Александр Беляев биография"} - это вызовет ошибку валидации!
    
    ПЕРЕД использованием этого инструмента ОБЯЗАТЕЛЬНО проверь, есть ли внутренние инструменты для решения задачи:
    - Для исследования и анализа: используй `researcher_agent` - он более эффективен и использует внутренние источники
    - Для работы с кодом: используй `coder_agent`, `coder_plan`, `coder_generate` - они имеют доступ к кодовой базе
    - Для работы с документами: используй `read_document`, `get_documents` - они работают с локальными документами
    - Для работы с GitHub: используй `get_workflow_runs`, `list_pull_requests`, `get_pull_request` и другие GitHub инструменты
    - Для работы с базой данных: используй `mysql_query` если нужны данные из БД
    - Для работы с файлами: используй Python код в REPL для работы с локальными файлами
    
    Используй `search` ТОЛЬКО если:
    1. Нужна актуальная информация из интернета, которой нет во внутренних источниках
    2. Все внутренние инструменты уже проверены и не подходят
    3. Пользователь явно просит поискать в интернете
    
    Этот инструмент выдает суммаризированные результаты поиска с сохранением ссылок на источники.
    Не забывай что можешь запросить информацию у пользователя с помощью `ask_followup_question`.
    Обязательно разбивай сложные запросы на более легкие.
    При формировании ответа обязательно прикладывай полные ссылки на источники, которые ты получил из инструмента `search`
    
    ВАЖНО: После использования простого поиска (search) предложи пользователю возможность провести глубокое исследование через researcher_agent, если он хочет получить более детальную информацию.
    Например: "Если нужна более подробная информация, я могу провести глубокое исследование этой темы."
    
    Примеры правильного использования:
    - Один запрос: search({"queries": ["Александр Беляев биография"]})
    - Несколько запросов: search({"queries": ["Александр Беляев", "творчество Беляева"]})
    """
    import logging
    logger = logging.getLogger(__name__)
    
    search = TavilySearch()
    
    # Выполняем поиск для всех запросов
    raw_results = await search.abatch(
        [
            {
                "query": query.strip(),
            }
            for query in queries
        ]
    )
    
    # Обрабатываем результаты для каждого запроса
    summarized_results = []
    
    for query_idx, query in enumerate(queries):
        query = query.strip()
        raw_result = raw_results[query_idx] if query_idx < len(raw_results) else None
        
        if not raw_result:
            summarized_results.append({
                "query": query,
                "summary": f"По запросу '{query}' результаты не найдены.",
                "sources": []
            })
            continue
        
        # Извлекаем результаты из структуры TavilySearch
        # TavilySearch может возвращать словарь с ключом "results" или список результатов
        results_list = []
        if isinstance(raw_result, dict):
            if "results" in raw_result:
                results_list = raw_result.get("results", [])
            elif "content" in raw_result or "url" in raw_result:
                # Если это один результат напрямую
                results_list = [raw_result]
        elif isinstance(raw_result, list):
            results_list = raw_result
        
        if not results_list:
            summarized_results.append({
                "query": query,
                "summary": f"По запросу '{query}' результаты не найдены.",
                "sources": []
            })
            continue
        
        # Собираем информацию из всех результатов
        all_content = []
        sources = []
        
        for idx, result_item in enumerate(results_list):
            if isinstance(result_item, dict):
                title = result_item.get("title", f"Результат {idx + 1}")
                url = result_item.get("url", "")
                content = result_item.get("content", "")
                
                if url:
                    sources.append({"title": title, "url": url})
                
                if content:
                    # Формируем текст с указанием источника
                    source_text = f"[Источник {len(sources)}: {title}]\n{content}"
                    all_content.append(source_text)
        
        if not all_content:
            summarized_results.append({
                "query": query,
                "summary": f"По запросу '{query}' найдено {len(results_list)} результатов, но содержимое недоступно.",
                "sources": sources
            })
            continue
        
        # Создаем суммаризацию с использованием LLM
        try:
            llm = load_llm(tag="fast")
            
            # Формируем промпт для суммаризации
            content_text = "\n\n---\n\n".join(all_content)
            
            summary_prompt = f"""Проведи суммаризацию результатов поиска по запросу: "{query}"

Результаты поиска:
{content_text}

Требования к суммаризации:
1. Создай краткое, но информативное резюме всех найденных результатов
2. Объедини информацию из разных источников в связный текст
3. Выдели ключевые факты и важную информацию
4. Сохрани все ссылки на источники в формате [Название источника](URL)
5. Если информация из разных источников противоречива, укажи это
6. Ответ должен быть на русском языке, если запрос был на русском

Суммаризация:"""
            
            summary = (await llm.ainvoke([("system", summary_prompt)])).content
            
            # Добавляем список источников в конец суммаризации
            if sources:
                summary += "\n\n**Источники:**\n"
                for idx, source in enumerate(sources, 1):
                    summary += f"{idx}. [{source['title']}]({source['url']})\n"
            
            summarized_results.append({
                "query": query,
                "summary": summary,
                "sources": sources,
                "results_count": len(results_list)
            })
            
            logger.info(f"✅ Поиск по запросу '{query}': найдено {len(results_list)} результатов, создана суммаризация")
            
        except Exception as e:
            logger.error(f"❌ Ошибка при суммаризации результатов поиска для запроса '{query}': {e}")
            # В случае ошибки возвращаем первые результаты без суммаризации, но со ссылками
            fallback_summary = f"Найдено {len(results_list)} результатов по запросу '{query}':\n\n"
            for idx, source in enumerate(sources[:5], 1):  # Показываем первые 5 источников
                fallback_summary += f"{idx}. [{source['title']}]({source['url']})\n"
            
            if len(sources) > 5:
                fallback_summary += f"\n... и еще {len(sources) - 5} источников\n"
            
            summarized_results.append({
                "query": query,
                "summary": fallback_summary,
                "sources": sources,
                "results_count": len(results_list)
            })
    
    # Если был только один запрос, возвращаем результат напрямую
    if len(summarized_results) == 1:
        return summarized_results[0]
    
    # Если было несколько запросов, возвращаем список результатов
    return summarized_results


@tool
async def suggest_plan(query: str):
    """Придумывает план для выполнения задачи пользователя. Используй при первом запросе пользователя, когда у тебя нет плана или его нужно пересоздать

    Args:
        query: Задача пользователя
    """
    llm = load_llm().with_config(tags=["nostream"])

    return (
        await llm.ainvoke(
            [
                (
                    "system",
                    f"""Ты — GigaAssistant, высококвалифицированный инженер-программист с обширными знаниями в программировании на Python, фреймворков.

====

РАЗМЫШЛЕНИЯ (thinking)
Ты должен всегда размышлять над задачей пользователя и ответами инструментов. Также ты должен стараться смотреть на задачу пользователя с разных точек зрения.
Обязательно детальной прописывай в каждом сообщение свои размышления. Также проверяй результаты выполнения инструментов и рефлексируй их результаты.
Для этого используй XML тэг <thinking>. В этом теге ты должен записывать свои размышления и планирование как ты будешь решать задачу пользователя.

Перед тем как предпринимать какие‑либо действия или отвечать пользователю после получения результатов работы инструментов, используй тэг <thinking> как черновик, чтобы:
- перечислить конкретные правила, которые относятся к текущему запросу;
- проверить, собрана ли вся необходимая информация;
- убедиться, что запланированное действие соответствует всем политикам;
- перебрать результаты работы инструментов и убедиться в их корректности.

====

КОД (python)
Помни, что при работе с кодом, ты должен стараться работать по шагам. Допустим сначала узнать какие есть колонки в таблице перед работой с ней. 
Также помни, что все переменные между вызовами сохраняются, так как код выполняется в Jupyter среде.
Не формулируй выводы в коде! Если ты уже закончил работу с данными, тогда либо пиши это сообщением, либо используй другие инструменты

===

СИНТЕЗ РЕЧИ (speak)
Если ты хочешь использовать синтез речи, формулируй его простым языком. Используй обращение во 2 лице (на ты). 
Обязательно используй простой пацанский жаргон!!! Или заказчик не поймет

===

ИНСТРУМЕНТЫ И ИХ ПРИОРИТЕТЫ:
1. ВНУТРЕННИЕ ИНСТРУМЕНТЫ (используй в первую очередь):
   - `researcher_agent` - для исследования и анализа (предпочтительнее чем search)
   - `coder_agent`, `coder_plan`, `coder_generate` - для работы с кодом
   - `read_document`, `get_documents` - для работы с документами
   - GitHub инструменты (`get_workflow_runs`, `list_pull_requests`, и т.д.) - для работы с GitHub
   - `mysql_query` - для работы с базой данных
   - Python код в REPL - для работы с файлами и данными
   - `email_agent` - для работы с почтой
   - `calendar_agent` - для работы с календарем
   - `lawyer_agent` - для юридических вопросов
   - `tinkoff_agent` - для финансовых операций

2. ПОИСК (search) - используй ТОЛЬКО как последний резорт:
   - Используй ТОЛЬКО если все внутренние инструменты проверены и не подходят
   - Используй ТОЛЬКО если нужна актуальная информация из интернета, которой нет во внутренних источниках
   - Всегда разделяй сложные запросы на легкие и используй поиск итеративно
   - Допустим если тебя просят найти перечисления объектов, то сделай по отдельному запросу на каждый объект
   - Но если же тебя просят найти объекты вместе, тогда разделения на несколько запросов не должно происходить
   - Если тебя просят найти информацию за период дат, помни, что ты также можешь разбить сложный запрос на несколько простых

====

АНАЛИЗ ИЗОБРАЖЕНИЙ (ask_about_image)
В результате выполнения кода, тебе могут возвращаться изображения. Если тебе нужно узнать информацию по ним используй инструмент ask_about_image с детальным вопросом по изображению, который нужно задать, чтобы выполнить задачу пользователя.
Используй при анализе только те id или ссылки, которые у тебя есть. Ни в коем случае не придумывай их!!!

====

ПАМЯТЬ
Если пользователь сказал какие-либо факты о себе или ты узнал что-то новое, запиши это в своей памяти. Также используй её чтобы подтягивать эти данные

====

Думай как scrum мастер.
У тебя стоит задача придумать самый оптимальный план для выполнения задачи исходя из тех инструментов, которые у тебя есть.
У тебя из инструментов есть: ВНУТРЕННИЕ ИНСТРУМЕНТЫ (researcher_agent, coder_agent, read_document, GitHub инструменты, mysql_query, email_agent, calendar_agent, lawyer_agent, tinkoff_agent и др.), КОД, СИНТЕЗ РЕЧИ, ПОИСК (только как последний резорт), АНАЛИЗ ИЗОБРАЖЕНИЙ, ПАМЯТЬ
ВАЖНО: Всегда предпочитай внутренние инструменты поиску. Используй поиск только если все внутренние инструменты проверены и не подходят.
Обязательно при продумывании плана опирайся на правила каждого из инструментов.
Ты должен вернуть только нумерированный план, который оптимально решит задачу пользователя.
Задача пользователя: "{query}"
Придумай только план!
Нумерированный План: """,
                )
            ]
        )
    ).content


# @tool(parse_docstring=True)
@tool
async def ask_about_image(image_path: str, question: str):
    """Анализирует изображение. Используй если нужно узнать информацию по изображению
    Используй этот инструмент итеративно, если в ответе недостаточно информации, сделай уточняющий запрос!

    Args:
        image_path: Путь до изображения (в директориях /runs/, /files/)
        question: Запрос для анализа изображения. Детально пропиши все, что ты хочешь узнать от изображения. Это полноценный промпт к V-LLM, поэтому используй все мощности нейросетей!
    """
    llm = load_llm().with_config(tags=["nostream"])

    if image_path.startswith("attachment:"):
        image_path = image_path[len("attachment:") :]
    if not image_path.startswith("/runs/") and not image_path.startswith("/files/"):
        return "image_id должен хранить путь до него"
    client = get_client(url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024"))
    try:
        data = (await client.store.get_item(("attachments",), key=image_path))["value"]
    except HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Изображение c ID {image_path} не найдено"
        else:
            raise e
    if not data.get("image_id") and not data.get("image_path"):
        return "Вложение не возможно проанализировать с помощью анализа изображений!"
    if is_llm_image_inline():
        return (
            (
                await llm.ainvoke(
                    [
                        HumanMessage(
                            content=question,
                            additional_kwargs={"attachments": [data.get("image_id")]},
                        ),
                    ]
                )
            ).content
            + "\nИспользуй этот инструмент итеративно, если в ответе недостаточно информации, сделай уточняющий запрос!"
        )
    else:
        async with httpx.AsyncClient() as client:
            FRONT_BASE_URL = os.getenv("FRONT_BASE_URL", "http://front:80/files")
            resp = await client.get(f"{FRONT_BASE_URL}{data['image_path']}")
            img_content = base64.b64encode(resp.content).decode()
        return (
            (
                await llm.ainvoke(
                    [
                        HumanMessage(
                            content=[
                                {
                                    "type": "text",
                                    "text": question,
                                },
                                {
                                    "type": "image",
                                    "source_type": "base64",
                                    "data": img_content,
                                    "mime_type": "image/png",
                                },
                            ]
                        ),
                    ]
                )
            ).content
            + "\nИспользуй этот инструмент итеративно, если в ответе недостаточно информации, сделай уточняющий запрос!"
        )


def parse_quality_from_theme(theme: str) -> Optional[str]:
    """
    Парсит указание качества изображения из темы.
    
    Поддерживаемые фразы:
    - "1K", "1k", "стандартное качество", "стандартное разрешение" -> "1K"
    - "2K", "2k", "высокое качество", "высокое разрешение" -> "2K"
    - "4K", "4k", "максимальное качество", "максимальное разрешение", "наивысшее качество" -> "4K"
    
    Args:
        theme: Тема изображения с возможными указаниями качества
        
    Returns:
        "1K", "2K", "4K" или None, если качество не указано
    """
    theme_lower = theme.lower()
    
    # Проверяем "4K" варианты первыми (максимальное качество)
    if re.search(r'\b(4k|4\s*k|максимальн|наивысш|лучш)\w*\s*(качеств|разрешен)', theme_lower) or \
       re.search(r'\b4\s*k\b', theme_lower):
        return "4K"
    
    # Проверяем "2K" варианты
    if re.search(r'\b(2k|2\s*k|высок)\w*\s*(качеств|разрешен)', theme_lower) or \
       re.search(r'\b2\s*k\b', theme_lower):
        return "2K"
    
    # Проверяем "1K" варианты (стандартное качество)
    if re.search(r'\b(1k|1\s*k|стандартн)\w*\s*(качеств|разрешен)', theme_lower) or \
       re.search(r'\b1\s*k\b', theme_lower):
        return "1K"
    
    return None


def parse_aspect_ratio_from_theme(theme: str, model_name: str = "dall-e-3") -> Optional[Tuple[int, int]]:
    """
    Парсит фразы о формате изображения из темы и возвращает размеры (width, height).
    
    Поддерживаемые фразы:
    - "квадратный рисунок", "квадратное изображение" -> квадрат
    - "широкий рисунок", "широкое изображение" -> landscape
    - "узкий рисунок", "узкое изображение" -> portrait
    - "очень широкий", "очень широкое" -> самый широкий из доступных
    - "очень высокий", "очень высокое" -> самый высокий из доступных
    
    Args:
        theme: Тема изображения с возможными указаниями формата
        model_name: Название модели для определения доступных размеров
        
    Returns:
        Tuple[int, int] или None, если формат не указан
    """
    theme_lower = theme.lower()
    
    # Определяем доступные размеры для модели
    lower = model_name.lower()
    supported = None
    
    # Проверяем, используется ли OpenRouter
    is_openrouter = "openrouter" in lower or "/" in model_name
    
    if is_openrouter:
        # Используем форматы OpenRouter
        supported = list(OPENROUTER_ASPECT_RATIOS.values())
    else:
        # Используем форматы OpenAI
        for key, sizes in OPENAI_SUPPORTED_SIZES.items():
            if key in lower:
                supported = sizes
                break
        if supported is None and "dalle-2" in lower:
            supported = OPENAI_SUPPORTED_SIZES["dall-e-2"]
        if supported is None:
            supported = OPENAI_SUPPORTED_SIZES["dall-e-3"]
    
    # Ищем фразы о формате
    # ВАЖНО: Проверяем "очень" варианты ПЕРВЫМИ, чтобы они имели приоритет
    
    # Очень широкий (максимальный landscape)
    if re.search(r'\bочень\s+широк\w+', theme_lower):
        landscape_sizes = [(w, h) for w, h in supported if w > h]
        if landscape_sizes:
            # Берем самый широкий (с максимальным соотношением сторон)
            return max(landscape_sizes, key=lambda s: s[0] / s[1])
    
    # Очень высокий (максимальный portrait)
    if re.search(r'\bочень\s+высок\w+', theme_lower):
        portrait_sizes = [(w, h) for w, h in supported if h > w]
        if portrait_sizes:
            # Берем самый высокий (с максимальным соотношением сторон)
            return max(portrait_sizes, key=lambda s: s[1] / s[0])
    
    # Квадратный формат (с поддержкой фраз без слова "рисунок")
    if re.search(r'\b(квадратн|квадрат)\w*\s*(рисунок|изображение|картинка|фото)', theme_lower) or \
       re.search(r'\b(квадратн|квадрат)\w*\b', theme_lower):
        # Ищем квадратный размер
        square_sizes = [(w, h) for w, h in supported if w == h]
        if square_sizes:
            # Берем самый большой квадратный размер
            return max(square_sizes, key=lambda s: s[0])
    
    # Широкий (обычный landscape, не "очень")
    if re.search(r'\bширок\w+\s*(рисунок|изображение|картинка|фото)', theme_lower) or \
       (re.search(r'\bширок\w+\b', theme_lower) and not re.search(r'\bочень\s+широк', theme_lower)):
        landscape_sizes = [(w, h) for w, h in supported if w > h]
        if landscape_sizes:
            # Берем средний landscape размер (не самый широкий)
            if len(landscape_sizes) > 1:
                # Сортируем по соотношению сторон и берем средний
                sorted_landscape = sorted(landscape_sizes, key=lambda s: s[0] / s[1])
                return sorted_landscape[len(sorted_landscape) // 2]
            return landscape_sizes[0]
    
    # Узкий (обычный portrait, не "очень")
    if re.search(r'\bузк\w+\s*(рисунок|изображение|картинка|фото)', theme_lower) or \
       (re.search(r'\bузк\w+\b', theme_lower) and not re.search(r'\bочень\s+узк', theme_lower)):
        portrait_sizes = [(w, h) for w, h in supported if h > w]
        if portrait_sizes:
            # Берем средний portrait размер (не самый высокий)
            if len(portrait_sizes) > 1:
                # Сортируем по соотношению сторон и берем средний
                sorted_portrait = sorted(portrait_sizes, key=lambda s: s[1] / s[0])
                return sorted_portrait[len(sorted_portrait) // 2]
            return portrait_sizes[0]
    
    return None


@tool
async def gen_image(theme: str, config: RunnableConfig):
    """
    Генерирует изображение

    Args:
        theme: Тема для генерации изображения
    """
    llm = load_llm().with_config(tags=["nostream"])

    # Парсим формат и качество из темы
    # Сначала загружаем генератор, чтобы получить имя модели
    generator = load_image_gen()
    # Получаем имя модели из генератора
    model_name = getattr(generator, 'model', 'dall-e-3')
    # Определяем, является ли генератор OpenRouter
    is_openrouter_gen = generator.__class__.__name__ == 'OpenRouterImageGen'
    # Для определения формата используем полное имя модели (с провайдером, если есть)
    # чтобы parse_aspect_ratio_from_theme могла определить, что это OpenRouter
    parsed_size = parse_aspect_ratio_from_theme(theme, model_name)
    # Парсим качество (только для OpenRouter)
    parsed_quality = parse_quality_from_theme(theme) if is_openrouter_gen else None
    
    # Формируем сообщение для промпта с учетом формата
    format_hint = ""
    if parsed_size:
        width, height = parsed_size
        if width == height:
            format_hint = " Важно: пользователь хочет квадратное изображение (одинаковая ширина и высота)."
        elif width > height:
            format_hint = f" Важно: пользователь хочет широкое изображение (ширина больше высоты, соотношение примерно {width}:{height})."
        else:
            format_hint = f" Важно: пользователь хочет высокое/узкое изображение (высота больше ширины, соотношение примерно {width}:{height})."
    
    img_chain = (
        IMAGE_PROMPT
        | llm
        | RunnableParallel(
            {"message": RunnablePassthrough(), "json": JsonOutputParser()}
        )
    ).with_retry()
    
    await generator.init()
    
    user_message = f'Тема изображения: "{theme}". Улучши её.{format_hint}'
    if parsed_size:
        user_message += f" Используй размеры: ширина {parsed_size[0]}, высота {parsed_size[1]}."
    if parsed_quality:
        quality_names = {"1K": "стандартное", "2K": "высокое", "4K": "максимальное"}
        quality_name = quality_names.get(parsed_quality, parsed_quality)
        user_message += f" Важно: пользователь хочет {quality_name} качество ({parsed_quality})."
    
    response = await img_chain.ainvoke(
        {"messages": [("user", user_message)]}
    )
    i = response["json"]["image"]
    
    # Если формат был указан, используем его вместо того, что вернул LLM
    if parsed_size:
        i["width"] = parsed_size[0]
        i["height"] = parsed_size[1]
    
    # Генерируем изображение с учетом качества (только для OpenRouter)
    if is_openrouter_gen:
        # Для OpenRouter передаем quality (если указано, иначе будет использовано значение по умолчанию 1K)
        image_data = await generator.generate_image(
            i["description"], i["width"], i["height"], quality=parsed_quality
        )
    else:
        # Для других провайдеров quality не поддерживается
        image_data = await generator.generate_image(
            i["description"], i["width"], i["height"]
        )
    uploader = REPLUploader()
    upload_files = [
        RunUploadFile(
            path=f"images/{uuid.uuid4()}.png",
            file_type="image",
            content=base64.b64decode(image_data),
        )
    ]
    upload_resp = await uploader.upload_run_files(
        upload_files, config["configurable"]["thread_id"]
    )
    uploaded = upload_resp[0] if upload_resp else {}
    
    # Преобразуем upload_resp в формат giga_attachments с file_id и type
    giga_attachments = []
    for item in upload_resp:
        if isinstance(item, dict):
            # Создаем attachment в формате, который ожидает tool_graph.py
            file_id = str(uuid.uuid4())  # Генерируем уникальный file_id
            attachment = {
                "type": "image/png",  # Тип файла
                "file_id": file_id,  # Уникальный идентификатор файла
                "path": item.get("path"),  # Путь к файлу
                "file_size": item.get("size"),  # Размер файла
            }
            # Если есть image_id, добавляем его
            if item.get("image_id"):
                attachment["image_id"] = item["image_id"]
            giga_attachments.append(attachment)
    
    return {
        "image_description": i["description"],
        "message": f'В результате выполнения было сгенерировано изображение {uploaded.get("path", "изображение")}. Покажи его пользователю через "![описание изображения](attachment:{uploaded.get("path", "")})"',
        "giga_attachments": giga_attachments,
    }


@tool(parse_docstring=True)
def Think(thought: str) -> str:
    """
    Используется для рассуждений

    Args:
        thought: Короткое рассуждение
    """
    return f"thought='{thought}'"
