"""
Граф агента кодера для генерации проектов
"""

import asyncio
import json
import os
import uuid
import zipfile
import tempfile
from typing import Literal, Optional, Annotated, Any
from pathlib import Path

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message
from langgraph.prebuilt import InjectedState

from giga_agent.agents.coder_agent.config import CoderState, llm, ConfigSchema
from giga_agent.utils.llm import get_agent_env
from giga_agent.agents.coder_agent.nodes.analyze import analyze_node
from giga_agent.agents.coder_agent.nodes.generate import generate_node
from giga_agent.agents.coder_agent.prompts.ru import CODER_AGENT_PROMPT
from giga_agent.agents.coder_agent.pipeline import plan_project, generate_project_files
from giga_agent.agents.coder_agent.utils.filesystem import (
    get_files_dir,
    write_project_files,
    make_zip_from_dir,
    read_json,
    write_json,
)
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
    
    # Примечание:
    # Для стабильности на DeepSeek лучше принудительно требовать tool-calls,
    # иначе модель иногда отвечает текстом и граф завершается с 0 файлов.
    # У разных провайдеров bind_tools может не поддерживать tool_choice, поэтому делаем fallback.
    try:
        bound_llm = llm.bind_tools(
            [analyze_project, generate_project, done],
            parallel_tool_calls=False,
            tool_choice="required",
        )
    except TypeError:
        bound_llm = llm.bind_tools(
            [analyze_project, generate_project, done],
            parallel_tool_calls=False,
        )
    chain = prompt | bound_llm
    
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
    
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Параметр называется task (НЕ query, НЕ user_request, НЕ action)!
    Всегда передавай описание проекта в параметр task.
    
    ПРАВИЛЬНЫЙ ФОРМАТ ВЫЗОВА:
    coder_agent(task="создать веб-приложение на Python с Flask")
    coder_agent(task="разработать REST API для управления задачами", programming_language="Python")
    
    НЕПРАВИЛЬНО (НЕ ДЕЛАЙ ТАК):
    ❌ coder_agent(query="создать проект") - параметр query не существует!
    ❌ coder_agent(user_request="создать проект") - параметр user_request не существует!
    ❌ coder_agent(action="generate") - параметр action не существует!
    
    Args:
        task: Детальное описание проекта, который нужно создать
        programming_language: Язык программирования (Python, NodeJS, JavaScript, PHP, Java, GoLang и т.д.)
        database: База данных (MySQL, SQLite, PostgreSQL, MariaDB)
        selected_technologies: Список выбранных технологий (RAG, LLM, FAISS, ChromaDB, HTML, CSS и т.д.)
        thread_id: ID предыдущего потока для продолжения работы над проектом
    """
    # Примечание:
    # Ранее инструмент пытался вызывать сам себя через LangGraph API (runs.stream, assistant_id="coder").
    # На практике это часто приводит к "тишине" стрима и таймаутам/0 файлов.
    # Для надежности запускаем локальный граф напрямую.
    #
    # thread_id оставляем в интерфейсе для совместимости (его может передавать фронтенд),
    # но локальный запуск не использует его.

    result_state: dict = {}

    # Формируем входное состояние для локального графа
    input_state: CoderState = {
        "agent_messages": [HumanMessage(content=task)],
        "task": task,
        "project_prompt": task,
        "programming_language": programming_language,
        "database": database,
        "selected_technologies": selected_technologies or [],
        "project_structure": [],
        "project_files": {},
        "analysis_messages": [],
        "generation_status": {"status": "pending"},
        "done": None,
    }

    # Таймаут на весь локальный запуск
    timeout_seconds = int(os.getenv("CODER_AGENT_TIMEOUT", "1800"))
    save_files = os.getenv("CODER_AGENT_SAVE_FILES", "0") == "1"
    project_id = str(uuid.uuid4())

    try:
        async with asyncio.timeout(timeout_seconds):
            result_state = await graph.ainvoke(
                input_state,
                config={
                    "configurable": {
                        "save_files": save_files,
                        "print_messages": False,
                        "project_id": project_id,
                    }
                },
            )
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        return {
            "text": f"Ошибка при генерации проекта: {str(e)}",
            "message": f"Произошла ошибка при генерации проекта: {str(e)}",
            "thread_id": thread_id,
            "project_files": result_state.get("project_files", {}) if isinstance(result_state, dict) else {},
            "generation_status": {
                "status": "error",
                "message": str(e),
                "traceback": error_trace,
            },
        }

    # Формируем результат
    project_files = result_state.get("project_files", {}) if isinstance(result_state, dict) else {}
    generation_status = result_state.get("generation_status", {}) if isinstance(result_state, dict) else {}
    done_message = result_state.get("done", "Проект готов") if isinstance(result_state, dict) else "Проект готов"
    
    # Формируем сообщение с результатами
    result_text = f"{done_message}\n\n"
    result_text += f"Создано файлов: {len(project_files)}\n"
    
    if project_files:
        result_text += "\nСтруктура проекта:\n"
        for file_path in sorted(project_files.keys()):
            result_text += f"- {file_path}\n"
    
    # Получаем название модели для coder_agent
    coder_model_str = os.getenv(get_agent_env("coder"), "")
    if coder_model_str:
        if coder_model_str.startswith("openrouter:"):
            model_id = coder_model_str.replace("openrouter:", "")
            if "qwen3-coder" in model_id.lower():
                model_name = f"Qwen 3 Coder ({model_id})"
            elif "qwen" in model_id.lower():
                model_name = f"Qwen ({model_id})"
            else:
                model_name = model_id
        else:
            model_name = coder_model_str
    else:
        model_name = "неизвестно"
    
    return {
        "text": result_text,
        "message": f"{done_message}. Проект содержит {len(project_files)} файлов. "
                   f"Используй thread_id '{thread_id}' для продолжения работы над проектом.",
        "thread_id": thread_id,
        "project_files": project_files,
        "generation_status": generation_status,
        "model_name": model_name  # Добавляем название модели в результаты
    }


__all__ = ["coder_agent", "graph"]


@tool(parse_docstring=True)
async def coder_plan(
    task: str,
    programming_language: Optional[str] = None,
    database: Optional[str] = None,
    selected_technologies: Optional[list] = None,
) -> dict:
    """
    Создает ТЗ/схему проекта: дерево файлов + описания (без генерации кода).

    Args:
        task: Требования к проекту
        programming_language: Язык программирования (например, Python)
        database: База данных (например, SQLite)
        selected_technologies: Технологии (например, ["Flask","SQLite","HTML","CSS"])
    """
    project_id = str(uuid.uuid4())
    structure, raw_text = await plan_project(
        llm=llm,
        task=task,
        programming_language=programming_language,
        database=database,
        selected_technologies=selected_technologies,
    )
    return {
        "success": True,
        "project_id": project_id,
        "project_structure": structure,
        "raw_plan": raw_text,
        "message": f"Схема проекта готова. Файлов в схеме: {len(structure)}. project_id={project_id}",
    }


@tool(parse_docstring=True)
async def coder_generate(
    task: str,
    project_id: Optional[str] = None,
    project_structure: Optional[list] = None,
    programming_language: Optional[str] = None,
    database: Optional[str] = None,
    selected_technologies: Optional[list] = None,
    user_adjustments: Optional[str] = None,
    confirm: bool = False,
    step_mode: bool = False,
    auto_confirm: bool = False,
    file_path_to_generate: Optional[str] = None,
    file_adjustments: Optional[str] = None,
    create_zip: bool = True,
) -> dict:
    """
    Генерирует файлы проекта по схеме, сохраняет их в папку и (опционально) упаковывает в ZIP.

    Двухшаговый режим (с подтверждением):
    - Если confirm=False: инструмент ТОЛЬКО возвращает схему (план) и просит пользователя подтвердить или внести правки.
    - Если confirm=True: инструмент генерирует файлы по схеме (с учетом user_adjustments, если переданы).

    Поведение:
    - Если project_structure не передан: сначала строится схема (как coder_plan), затем генерируются файлы.
    - Файлы пишутся на диск в FILES_DIR/projects/<project_id>/...
    - ZIP (если create_zip=True) сохраняется в FILES_DIR/<project_id>.zip и доступен по пути /files/<project_id>.zip

    Args:
        task: Требования к проекту
        project_id: Идентификатор проекта (если не задан — будет сгенерирован)
        project_structure: Схема проекта (список файлов). Если не задана — будет построена ИИ.
        programming_language: Язык программирования
        database: База данных
        selected_technologies: Технологии
        user_adjustments: Поправки пользователя к схеме/логике (будут учтены при (пере)планировании)
        confirm: Подтверждение пользователем генерации по схеме. Если False — вернется только план.
        step_mode: Если True — генерация идет по одному файлу за вызов (с подтверждением на каждый файл).
        auto_confirm: Если True и step_mode=True — подтверждения на файл не требуются (идем автоматически).
        file_path_to_generate: Какой файл генерировать в step_mode (если не задан — будет выбран следующий).
        file_adjustments: Поправки пользователя к конкретному файлу (учитываются при генерации этого файла).
        create_zip: Создавать ZIP архив (по умолчанию True)
    """
    project_id = project_id or str(uuid.uuid4())

    # Примечание:
    # Пользователь может дать правки к плану. Для простоты добавляем их к task,
    # чтобы LLM учел их при планировании/генерации.
    effective_task = task
    if user_adjustments and user_adjustments.strip():
        effective_task = (
            f"{task}\n\n"
            f"Поправки пользователя (ОБЯЗАТЕЛЬНО учесть):\n{user_adjustments.strip()}\n"
        )

    # 1) Если схема не передана — создаем (или пересоздаем с учетом правок)
    if not project_structure:
        project_structure, _raw = await plan_project(
            llm=llm,
            task=effective_task,
            programming_language=programming_language,
            database=database,
            selected_technologies=selected_technologies,
        )

    # 1.1) Двухшаговый режим: если не подтверждено — возвращаем план и просим подтверждение
    if not confirm:
        structure_lines = "\n".join(
            [f"- {item.get('path')}: {item.get('description','')}" for item in (project_structure or [])]
        )
        return {
            "success": True,
            "status": "needs_confirmation",
            "project_id": project_id,
            "project_structure": project_structure,
            "message": (
                "Схема проекта подготовлена. Подтвердите генерацию или пришлите поправки.\n\n"
                "Чтобы продолжить, повторно вызовите coder_generate с параметром confirm=true.\n"
                "Если хотите правки — передайте user_adjustments.\n\n"
                "СХЕМА:\n"
                f"{structure_lines}"
            ),
        }

    # 2) Генерация кода по схеме
    project_files, generation_errors = await generate_project_files(
        llm=llm,
        task=effective_task,
        project_structure=project_structure,
        programming_language=programming_language,
        database=database,
        selected_technologies=selected_technologies,
    )

    # 3) Запись файлов на диск в files/projects/<project_id>/
    files_dir = get_files_dir()
    project_dir = files_dir / "projects" / project_id

    # Пошаговый режим: сохраняем/читаем прогресс между вызовами
    state_path = project_dir / ".coder_state.json"

    if step_mode:
        # 0) Сохраняем основу состояния (план + общие параметры)
        existing_state = read_json(state_path) or {}
        generated_files = set(existing_state.get("generated_files", []))

        # Фиксируем актуальный план и task
        write_json(
            state_path,
            {
                "project_id": project_id,
                "task": effective_task,
                "programming_language": programming_language,
                "database": database,
                "selected_technologies": selected_technologies or [],
                "project_structure": project_structure,
                "generated_files": sorted(list(generated_files)),
            },
        )

        # 1) Определяем следующий файл
        all_paths = [item.get("path") for item in (project_structure or []) if item.get("path")]
        remaining = [p for p in all_paths if p and p not in generated_files]
        if not remaining:
            # Уже всё готово — можно собрать zip
            zip_url_path = None
            zip_size = 0
            attachments: list[dict[str, Any]] = []
            if create_zip:
                zip_filename = f"{project_id}.zip"
                zip_path = files_dir / zip_filename
                zip_size = make_zip_from_dir(project_dir, zip_path)
                zip_url_path = f"/files/{zip_filename}"
                attachments.append(
                    {
                        "type": "application/zip",
                        "file_id": str(uuid.uuid4()),
                        "path": zip_url_path,
                        "file_size": zip_size,
                    }
                )
            return {
                "success": True,
                "status": "completed",
                "project_id": project_id,
                "message": f"Все файлы сгенерированы. ZIP: {zip_url_path}" if zip_url_path else "Все файлы сгенерированы.",
                "zip_path": zip_url_path,
                "zip_size": zip_size,
                "giga_attachments": attachments,
            }

        target_file = file_path_to_generate or remaining[0]
        # Считаем мета по файлу из структуры
        file_info = next((x for x in project_structure if x.get("path") == target_file), None) or {}

        if not auto_confirm and not confirm:
            return {
                "success": True,
                "status": "needs_file_confirmation",
                "project_id": project_id,
                "next_file": {
                    "path": target_file,
                    "description": file_info.get("description", ""),
                    "functions": file_info.get("functions", []),
                },
                "remaining_files": remaining,
                "generated_files": sorted(list(generated_files)),
                "message": (
                    f"Готов сгенерировать файл: {target_file}\n"
                    "Подтвердите генерацию (confirm=true) или передайте file_adjustments.\n"
                    "Если хотите автогенерацию без подтверждений — вызовите с auto_confirm=true."
                ),
            }

        # 2) Генерируем ОДИН файл
        file_task = effective_task
        if file_adjustments and file_adjustments.strip():
            file_task = (
                f"{effective_task}\n\n"
                f"Поправки к файлу {target_file} (ОБЯЗАТЕЛЬНО учесть):\n{file_adjustments.strip()}\n"
            )

        one_file_structure = [
            {"path": target_file, "description": file_info.get("description", ""), "functions": file_info.get("functions", [])}
        ]

        one_file_map, generation_errors = await generate_project_files(
            llm=llm,
            task=file_task,
            project_structure=one_file_structure,
            programming_language=programming_language,
            database=database,
            selected_technologies=selected_technologies,
        )

        # Пишем только этот файл
        files_count, total_bytes = write_project_files(project_dir, one_file_map)
        if files_count > 0:
            generated_files.add(target_file)
            write_json(
                state_path,
                {
                    **(read_json(state_path) or {}),
                    "generated_files": sorted(list(generated_files)),
                },
            )

        # 3) Возвращаем статус + что осталось
        remaining_after = [p for p in all_paths if p and p not in generated_files]
        return {
            "success": True,
            "status": "file_generated" if files_count > 0 else "file_failed",
            "project_id": project_id,
            "file": target_file,
            "written_files_count": files_count,
            "written_bytes": total_bytes,
            "generation_errors": generation_errors,
            "remaining_files": remaining_after,
            "generated_files": sorted(list(generated_files)),
            "message": (
                f"Файл {target_file} {'сгенерирован' if files_count > 0 else 'не удалось сгенерировать'}.\n"
                f"Осталось файлов: {len(remaining_after)}"
            ),
        }

    # Не пошаговый режим: пишем все файлы сразу
    files_count, total_bytes = write_project_files(project_dir, project_files)

    # 4) ZIP + ссылка
    attachments: list[dict[str, Any]] = []
    zip_url_path = None
    zip_size = 0
    if create_zip and files_count > 0:
        zip_filename = f"{project_id}.zip"
        zip_path = files_dir / zip_filename
        zip_size = make_zip_from_dir(project_dir, zip_path)
        zip_url_path = f"/files/{zip_filename}"
        attachments.append(
            {
                "type": "application/zip",
                "file_id": str(uuid.uuid4()),
                "path": zip_url_path,
                "file_size": zip_size,
            }
        )

    msg_parts = [
        f"Проект сгенерирован. project_id={project_id}",
        f"Файлов: {files_count}",
        f"Папка проекта: {project_dir.as_posix()}",
    ]
    if zip_url_path:
        msg_parts.append(f"ZIP: {zip_url_path}")
    if generation_errors:
        msg_parts.append(f"Ошибок генерации: {len(generation_errors)} (см. поле generation_errors)")

    return {
        "success": True,
        "project_id": project_id,
        "project_structure": project_structure,
        "project_files": project_files,
        "generation_errors": generation_errors,
        "files_count": files_count,
        "total_bytes": total_bytes,
        "project_dir": project_dir.as_posix(),
        "zip_path": zip_url_path,
        "zip_size": zip_size,
        "giga_attachments": attachments,
        "message": "\n".join(msg_parts),
    }

