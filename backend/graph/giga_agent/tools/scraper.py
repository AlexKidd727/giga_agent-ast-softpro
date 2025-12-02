import asyncio
import os
import logging
from typing import Annotated

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_tavily import TavilyExtract
from langgraph.prebuilt import InjectedState

from giga_agent.utils.env import load_project_env
from giga_agent.utils.llm import load_llm, is_llm_image_inline, is_llm_gigachat
from giga_agent.utils.messages import filter_tool_calls

logger = logging.getLogger(__name__)

llm = load_llm(tag="fast").bind(top_p=0.3).with_config(tags=["nostream"])

PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Ты — опытный копирайтер-аналитик.
Тебе предоставлены выгрузки с сайта (тексты, таблицы, изображения).

**Твоя задача:**

1. Проанализировать весь полученный материал.
2. Отобрать только то, что напрямую относится к поставленной задаче.
3. Сформировать итоговый ответ для пользователя, который:

   * содержит релевантные фрагменты текста;
   * включает нужные таблицы (с сохранением структуры);
   * прикрепляет важные изображения (с короткой подписью к каждой) `![alt-текст](ссылка)`.

**Требования к результату:**

* Ничего лишнего: только данные, важные для решения задачи.
* Ясные, лаконичные формулировки, без воды.
* Если источник неясен — укажи пометку «(источник неизвестен)».
* Соблюдай единый стиль оформления:

  * заголовки — **полужирные**,
  * подзаголовки — *курсив*,
  * таблицы — в Markdown,
  * изображения — обязательно в формате `![alt-текст](ссылка)`
""",
        ),
        MessagesPlaceholder("messages"),
    ]
)

scrape_sem = asyncio.Semaphore(4)


async def url_response_to_llm(messages, response):
    """
    Обрабатывает ответ от Tavily и отправляет его в LLM для анализа.
    
    Args:
        messages: Список сообщений для контекста
        response: Ответ от Tavily с данными страницы
    
    Returns:
        Словарь с результатом обработки или информацией об ошибке
    """
    try:
        extract_ch = PROMPT | llm
        
        # Проверяем, что messages не пустой перед обращением к messages[-1]
        if not messages:
            # Если сообщений нет, создаем пустое сообщение
            last_mes = HumanMessage(content=".")
        else:
            last_mes = filter_tool_calls(messages[-1])

        # Безопасно получаем данные из response
        # В оригинале использовался весь объект response, преобразованный в строку
        # Проверяем наличие ключа "content", если его нет - используем весь объект
        if isinstance(response, dict):
            response_content = response.get("content", str(response))
        else:
            response_content = str(response)

        message = HumanMessage(
            content=f"""**Твоя задача:**

1. Проанализировать материал ниже.
2. Отобрать только то, что напрямую относится к поставленной задаче.
3. Сформировать исходя из материала короткий ответ для пользователя, который:

   * содержит релевантные фрагменты текста;
   * включает нужные таблицы (с сохранением структуры);
   * прикрепляет важные изображения (с короткой подписью к каждой) `![alt-текст](ссылка)`.

**Требования к результату:**

* Ничего лишнего: только данные, важные для решения задачи.
* Ясные, лаконичные формулировки, без воды.
* Если источник неясен — укажи пометку «(источник неизвестен)».
* Соблюдай единый стиль оформления:

  * заголовки — **полужирные**,
  * подзаголовки — *курсив*,
  * таблицы — в Markdown,
  * изображения — обязательно в формате ![alt-текст](ссылка)
  
Материал 
----
{response_content}
----
Дай краткую информацию исходя из материала следуя своей инструкции по форматированию ответа"""
        )
        async with scrape_sem:
            resp = await extract_ch.ainvoke(
                {"messages": (messages[:-1] if messages else []) + [last_mes, message]}
            )
        # Безопасно извлекаем url и images из response
        url = response.get("url", "") if isinstance(response, dict) else ""
        images = response.get("images", []) if isinstance(response, dict) else []
        
        return {
            "url": url,
            "images": images,
            "result": resp.content,
        }
    except Exception as e:
        # Логируем ошибку для отладки
        url = response.get("url", "unknown") if isinstance(response, dict) else "unknown"
        logger.error(f"Ошибка при обработке URL {url}: {str(e)}", exc_info=True)
        # Возвращаем информацию об ошибке в JSON-сериализуемом формате
        return {
            "url": url if isinstance(response, dict) else "",
            "images": response.get("images", []) if isinstance(response, dict) else [],
            "result": f"Ошибка при обработке страницы: {str(e)}",
            "error": str(e),
            "error_type": type(e).__name__,
        }


@tool
async def get_urls(urls: list[str], state: Annotated[dict, InjectedState] = None):
    """
    Скачивает список URLs и отдает результат со страницы. Используй это когда тебе нужно узнать информацию по ссылке.
    Также это может возвращать изображения. Ты можешь их вставлять так ![alt](url)

    Args:
        urls: Список urls для скачивания
    """
    try:
        extract = TavilyExtract()

        response = await extract.ainvoke(
            {"urls": urls, "include_images": False, "extract_depth": "basic"}
        )
        
        # Проверяем наличие результатов
        if not response or "results" not in response:
            logger.warning(f"Tavily не вернул результаты для URLs: {urls}")
            return {
                "results": [{"error": "Не удалось получить данные со страниц", "urls": urls}],
                "attention": "\nНе удалось получить данные со страниц. Проверьте доступность ссылок.",
            }
        
        if is_llm_gigachat():
            await llm._client.aget_token()
        
        tasks = []
        for result in response.get("results", []):
            # Если state не передан, используем пустой список сообщений
            messages = state["messages"] if state and "messages" in state else []
            tasks.append(url_response_to_llm(messages, result))

        # Собираем результаты с обработкой исключений
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Преобразуем исключения в JSON-сериализуемый формат
        processed_results = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                # Преобразуем исключение в словарь
                error_info = {
                    "error": str(result),
                    "error_type": type(result).__name__,
                    "url": urls[idx] if idx < len(urls) else "unknown",
                    "images": [],
                    "result": f"Ошибка при обработке страницы: {str(result)}",
                }
                processed_results.append(error_info)
                logger.error(f"Ошибка при обработке URL {urls[idx] if idx < len(urls) else 'unknown'}: {str(result)}", exc_info=True)
            else:
                processed_results.append(result)
        
        return {
            "results": processed_results,
            "attention": "\nИспользуй результаты в своем ответе. Не забудь вставить изображения из результатов, которые ты посчитаешь были бы полезны пользователю! Следующим образом `![alt-текст](ссылка)`",
        }
    except Exception as e:
        # Обрабатываем критические ошибки
        logger.error(f"Критическая ошибка в get_urls: {str(e)}", exc_info=True)
        return {
            "results": [{
                "error": str(e),
                "error_type": type(e).__name__,
                "urls": urls,
                "images": [],
                "result": f"Критическая ошибка при обработке ссылок: {str(e)}",
            }],
            "attention": f"\nПроизошла ошибка при обработке ссылок: {str(e)}",
        }
