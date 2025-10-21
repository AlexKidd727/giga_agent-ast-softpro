import os
from typing import Annotated

import aiohttp
from langchain_core.tools import tool
import requests

from giga_agent.utils.types import Collection


@tool(
    description="""Семантический поиск по базе знаний пользователя через векторный поиск.

Используй для поиска информации из документов пользователя. Формулируй query как естественный вопрос.
При недостатке информации делай повторные запросы с другими формулировками.
Всегда цитируй источники (ID документа) в ответах."""
)
async def get_documents(
    collection_uuid: Annotated[str, "UUID-коллекции"],
    query: Annotated[str, "Поисковый запрос для поиска релевантных документов"],
    limit: Annotated[int, "Количество документов, которые возвращаются"] = 10,
) -> str:
    rag_url = os.getenv("LANGCONNECT_API_URL")
    access_token = os.getenv("LANGCONNECT_API_SECRET_TOKEN")
    if rag_url.endswith("/"):
        rag_url = rag_url[:-1]
    search_endpoint = f"{rag_url}/collections/{collection_uuid}/documents/search"
    payload = {"query": query, "limit": limit}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                search_endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as search_response:
                search_response.raise_for_status()
                documents = await search_response.json()
        formatted_docs = "Найденные части документов: \n"

        for doc in documents:
            doc_id = doc.get("id", "unknown")
            content = doc.get("page_content", "")
            formatted_docs += (
                f'  <document id="{doc_id}">\n    {content}\n  </document>\n'
            )

        return (
            formatted_docs
            + "Если информации недостаточно, попробуй расширить запрос и вызвать get_documents повторно"
        )
    except Exception as e:
        return f"<all-documents>\n  <error>{str(e)}</error>\n</all-documents>"


def has_collections():
    rag_url = os.getenv("LANGCONNECT_API_URL")
    access_token = os.getenv("LANGCONNECT_API_SECRET_TOKEN")
    if not rag_url or not access_token:
        return False
    if rag_url.endswith("/"):
        rag_url = rag_url[:-1]
    try:
        collection_endpoint = f"{rag_url}/collections/"
        collections = requests.get(
            collection_endpoint, headers={"Authorization": f"Bearer {access_token}"}
        )
        collections = collections.json()
        return len(collections) > 0
    except Exception as e:
        return False


RAG_PROMPT = """
====
БАЗА ЗНАНИЙ

У тебя есть доступ к документам пользователя через инструмент get_documents.
ВСЕГДА проверяй информацию в базе знаний перед ответом, даже если уверен в своих знаниях.

ДОСТУПНЫЕ КОЛЛЕКЦИИ:
{0}

СТРАТЕГИЯ РАБОТЫ:

1. ПРОСТЫЕ ЗАПРОСЫ (конкретный факт/процедура):
   • Сформулируй query как естественный вопрос с ключевыми терминами
   • Начни с limit=5-10
   • Если результат неполный → переформулируй (синонимы, другой угол)
   • Для смежных коллекций делай отдельные запросы

2. КОМПЛЕКСНЫЙ АНАЛИЗ (изучи договор/риски/подводные камни):
   • Шаг 1: Обзорный запрос → определи структуру и ключевые термины
   • Шаг 2: Декомпозиция на аспекты (условия, ограничения, обязательства, риски, процедуры, стоимость)
   • Шаг 3: Серия целевых запросов по каждому аспекту
   • Шаг 4: Структурированный отчет:
     - Резюме и выводы
     - Ключевые условия/риски с цитатами
     - Вопросы для уточнения
     - Таблица основных параметров

ЦИТИРОВАНИЕ: Всегда указывай ID документа и, если есть, раздел/пункт/страницу.

"""


def get_rag_info(collections: list[Collection]):
    if not collections:
        return ""
    descriptions = []
    for collection in collections:
        description = (
            f"Название коллекции: {collection['name']}\nUUID: {collection['uuid']}"
        )
        if collection.get("metadata", {}).get("description"):
            description += (
                f"\nОписание коллекции: {collection['metadata']['description']}"
            )
        descriptions.append(description)
    return RAG_PROMPT.format("\n---\n".join(descriptions))
