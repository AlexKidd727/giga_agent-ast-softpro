"""
Граф агента кодера для генерации проектов
"""

import asyncio
import json
import os
import uuid
import zipfile
import tempfile
from typing import Literal, Optional, Annotated
from pathlib import Path

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message
from langgraph.prebuilt import InjectedState
from langgraph_sdk import get_client

from giga_agent.agents.coder_agent.config import CoderState, llm, ConfigSchema
from giga_agent.agents.coder_agent.nodes.analyze import analyze_node
from giga_agent.agents.coder_agent.nodes.generate import generate_node
from giga_agent.agents.coder_agent.prompts.ru import CODER_AGENT_PROMPT
from giga_agent.utils.lang import LANG
from giga_agent.utils.env import load_project_env
from giga_agent.utils.messages import filter_tool_messages

load_project_env()


async def agent(state: CoderState, config: RunnableConfig):
    """Основной узел агента - обрабатывает запросы пользователя"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", CODER_AGENT_PROMPT),
        MessagesPlaceholder("messages")
    ]).partial(language=LANG)
    
    # Инструменты для агента
    from giga_agent.agents.coder_agent.tools import analyze_project, generate_project, done
    
    chain = prompt | llm.bind_tools(
        [analyze_project, generate_project, done],
        parallel_tool_calls=False
    )
    
    resp = await chain.ainvoke(
        {"messages": filter_tool_messages(state.get("agent_messages", []))},
        config={"callbacks": []},
    )
    
    if config["configurable"].get("print_messages", False):
        resp.pretty_print()
    
    return {
        "agent_messages": resp,
    }


async def done_node(state: CoderState, config: RunnableConfig):
    """Узел завершения - создает архив проекта"""
    resp = state["agent_messages"][-1]
    
    if resp.tool_calls and resp.tool_calls[0]["name"] == "done":
        done_str = resp.tool_calls[0]["args"].get("message", "Проект готов")
        action = resp.tool_calls[0]
    else:
        done_str = resp.content if hasattr(resp, 'content') else "Проект готов"
        action = {}
    
    # Создаем архив проекта, если есть файлы
    project_files = state.get("project_files", {})
    project_id = config["configurable"].get("project_id", str(uuid.uuid4()))
    
    archive_path = None
    if project_files and config["configurable"].get("save_files", False):
        try:
            # Создаем временный архив
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
                temp_zip_path = temp_zip.name
            
            with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path, content in project_files.items():
                    zipf.writestr(file_path, content)
            
            # Сохраняем архив в папку projects
            projects_dir = Path("projects")
            projects_dir.mkdir(exist_ok=True)
            archive_path = projects_dir / f"{project_id}.zip"
            
            # Перемещаем временный файл
            import shutil
            shutil.move(temp_zip_path, str(archive_path))
            
        except Exception as e:
            print(f"[CODER AGENT] Ошибка создания архива: {e}")
    
    return {
        "agent_messages": ToolMessage(
            tool_call_id=action.get("id", str(uuid.uuid4())),
            content=json.dumps({
                "success": True,
                "message": done_str,
                "project_id": project_id,
                "files_count": len(project_files),
                "archive_path": str(archive_path) if archive_path else None
            }, ensure_ascii=False),
        ),
        "done": done_str,
    }


def router(state: CoderState) -> Literal["analyze", "generate", "done_node", "__end__"]:
    """Маршрутизатор для выбора следующего узла"""
    tools_calls = state["agent_messages"][-1].tool_calls
    if tools_calls:
        tool_name = tools_calls[0]["name"]
        if tool_name == "analyze_project":
            return "analyze"
        elif tool_name == "generate_project":
            return "generate"
        elif tool_name == "done":
            return "done_node"
        else:
            return "__end__"
    else:
        return "__end__"


# Создание графа
workflow = StateGraph(CoderState, ConfigSchema)

workflow.add_node("agent", agent)
workflow.add_node("analyze", analyze_node)
workflow.add_node("generate", generate_node)
workflow.add_node("done_node", done_node)

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", router)
workflow.add_edge("analyze", "agent")
workflow.add_edge("generate", "agent")
workflow.add_edge("done_node", "__end__")

graph = workflow.compile()


@tool(parse_docstring=True)
async def coder_agent(
    task: str,
    programming_language: Optional[str] = None,
    database: Optional[str] = None,
    selected_technologies: Optional[list] = None,
    thread_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None,
):
    """
    Генерирует проект на основе требований пользователя.
    Анализирует требования, создает структуру проекта и генерирует все файлы.
    
    Args:
        task: Детальное описание проекта, который нужно создать
        programming_language: Язык программирования (Python, NodeJS, JavaScript, PHP, Java, GoLang и т.д.)
        database: База данных (MySQL, SQLite, PostgreSQL, MariaDB)
        selected_technologies: Список выбранных технологий (RAG, LLM, FAISS, ChromaDB, HTML, CSS и т.д.)
        thread_id: ID предыдущего потока для продолжения работы над проектом
    """
    client = get_client(url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024"))
    
    if not thread_id:
        thread = await client.threads.create()
        thread_id = thread["thread_id"]
    
    result_state = {}
    # Удалена неиспользуемая строка с небезопасным обращением к state
    # action = state["messages"][-1].tool_calls[0]  # Могла вызывать TypeError если state=None или messages пуст
    
    # Формируем входные данные
    input_data = {
        "agent_messages": [
            {
                "role": "user",
                "content": task
            }
        ],
        "task": task,
        "project_prompt": task,
        "programming_language": programming_language,
        "database": database,
        "selected_technologies": selected_technologies or [],
        "project_structure": [],
        "project_files": {},
        "generation_status": {"status": "pending"}
    }
    
    async for chunk in client.runs.stream(
        thread_id=thread_id,
        if_not_exists="create",
        assistant_id="coder",
        input=input_data,
        stream_mode=["values", "updates"],
        on_disconnect="cancel",
    ):
        if chunk.event == "values":
            result_state = chunk.data
        elif chunk.event == "updates":
            if "agent" in chunk.data:
                message = chunk.data["agent"]["agent_messages"]
                if message.get("tool_calls"):
                    tool_name = message["tool_calls"][0]["name"]
                    if tool_name != "done":
                        push_ui_message(
                            "agent_execution",
                            {
                                "agent": "coder_agent",
                                "node": tool_name,
                            },
                        )
    
    # Формируем результат
    project_files = result_state.get("project_files", {})
    generation_status = result_state.get("generation_status", {})
    done_message = result_state.get("done", "Проект готов")
    
    # Формируем сообщение с результатами
    result_text = f"{done_message}\n\n"
    result_text += f"Создано файлов: {len(project_files)}\n"
    
    if project_files:
        result_text += "\nСтруктура проекта:\n"
        for file_path in sorted(project_files.keys()):
            result_text += f"- {file_path}\n"
    
    return {
        "text": result_text,
        "message": f"{done_message}. Проект содержит {len(project_files)} файлов. "
                   f"Используй thread_id '{thread_id}' для продолжения работы над проектом.",
        "thread_id": thread_id,
        "project_files": project_files,
        "generation_status": generation_status
    }


__all__ = ["coder_agent", "graph"]

