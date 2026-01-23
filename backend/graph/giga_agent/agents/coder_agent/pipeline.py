"""
Пайплайн "кодера" без внутренних tool-calls.

Зачем:
- Старый поток через LLM->tools->router иногда завершался без tool_calls (0 файлов)
- А вызов через langgraph_sdk stream мог "молчать" и зависать

Этот модуль реализует 2 шага:
1) plan_project: генерация структуры (ТЗ/схема файлов)
2) generate_project_files: генерация содержимого файлов по структуре
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple, Any

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from giga_agent.agents.coder_agent.prompts.ru import ANALYSIS_PROMPT, GENERATION_PROMPT
from giga_agent.agents.coder_agent.utils.code_cleaner import clean_generated_code
from giga_agent.utils.lang import LANG


def _should_exclude_db_file(file_path: str) -> bool:
    if not file_path:
        return False
    db_extensions = [".db", ".sqlite", ".sqlite3", ".db3", ".sdb", ".sl3"]
    for ext in db_extensions:
        if file_path.lower().endswith(ext):
            return True
    return False


def _normalize_structure(structure: List[dict]) -> List[dict]:
    filtered: List[dict] = []
    seen = set()
    for item in structure or []:
        path = (item.get("path") or "").strip()
        if not path:
            continue
        if path.endswith("/") or path.endswith("\\"):
            continue
        if _should_exclude_db_file(path):
            continue
        if path in seen:
            continue
        seen.add(path)
        filtered.append(
            {
                "path": path,
                "description": item.get("description", ""),
                "functions": item.get("functions", []) if isinstance(item.get("functions", []), list) else [],
            }
        )
    return filtered


def _extract_structure_from_text(text: str) -> List[dict]:
    content = text or ""
    # 1) Попытка: найти JSON-объект целиком
    json_start = content.find("{")
    if json_start != -1:
        brace_count = 0
        json_end = -1
        for i, ch in enumerate(content[json_start:], start=json_start):
            if ch == "{":
                brace_count += 1
            elif ch == "}":
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break
        if json_end > json_start:
            try:
                parsed = json.loads(content[json_start:json_end])
                if isinstance(parsed, dict) and isinstance(parsed.get("structure"), list):
                    return parsed["structure"]
            except json.JSONDecodeError:
                pass

    # 2) Попытка: вытащить "structure": [...]
    m = re.search(r'"structure"\s*:\s*\[(.*?)\]', content, re.DOTALL)
    if m:
        items_text = m.group(1)
        item_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
        items = re.findall(item_pattern, items_text)
        out: List[dict] = []
        for item_str in items:
            try:
                obj = json.loads(item_str)
                if isinstance(obj, dict):
                    out.append(obj)
            except Exception:
                continue
        if out:
            return out

    # 3) Fallback: по строкам искать похожие на пути
    out: List[dict] = []
    for line in content.splitlines():
        path_patterns = [
            r'["\']([^"\']+\.(py|js|ts|html|css|json|md|txt|yml|yaml))["\']',
            r'([a-zA-Z0-9_\-/\\]+\.(py|js|ts|html|css|json|md|txt|yml|yaml))',
        ]
        for pattern in path_patterns:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                file_path = match.group(1) if match.lastindex else match.group(0)
                if file_path and not _should_exclude_db_file(file_path) and len(file_path) > 3:
                    out.append({"path": file_path, "description": line.strip(), "functions": []})
                    break
    return out


async def plan_project(
    *,
    llm,
    task: str,
    programming_language: Optional[str],
    database: Optional[str],
    selected_technologies: Optional[list],
) -> Tuple[List[dict], str]:
    """Возвращает (project_structure, raw_llm_text)."""
    technologies = selected_technologies or []
    technologies_str = ", ".join([str(t) for t in technologies]) if technologies else "нет"
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", ANALYSIS_PROMPT),
            MessagesPlaceholder("messages"),
        ]
    ).partial(
        language=LANG,
        project_prompt=task,
        programming_language=programming_language or "не указан",
        database=database or "нет",
        technologies=technologies_str,
    )
    # Примечание: DeepSeek/прокси могут рвать соединение (RemoteProtocolError).
    # Поэтому добавляем автоматические ретраи на уровне runnable.
    chain = (prompt | llm).with_retry(stop_after_attempt=3)
    resp = await chain.ainvoke({"messages": [HumanMessage(content=task)]})
    text = resp.content if hasattr(resp, "content") else str(resp)
    structure = _extract_structure_from_text(text)
    structure = _normalize_structure(structure)
    return structure, text


async def generate_project_files(
    *,
    llm,
    task: str,
    project_structure: List[dict],
    programming_language: Optional[str],
    database: Optional[str],
    selected_technologies: Optional[list],
) -> Tuple[Dict[str, str], List[dict]]:
    """Генерирует {path: content} по схеме."""
    technologies = selected_technologies or []
    technologies_str = ", ".join([str(t) for t in technologies]) if technologies else "нет"
    structure_str = "\n".join(
        [f"{f.get('path', '')} - {f.get('description', '')}" for f in project_structure]
    )

    out: Dict[str, str] = {}
    errors: List[dict] = []
    for file_info in project_structure:
        file_path = file_info.get("path", "")
        if not file_path or file_path in out:
            continue
        file_description = file_info.get("description", "")
        functions = file_info.get("functions", [])
        functions_str = ", ".join(functions) if isinstance(functions, list) else str(functions)

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", GENERATION_PROMPT),
                MessagesPlaceholder("messages"),
            ]
        ).partial(
            language=LANG,
            file_path=file_path,
            file_description=file_description,
            functions=functions_str,
            project_prompt=task,
            programming_language=programming_language or "не указан",
            database=database or "нет",
            technologies=technologies_str,
            project_structure=structure_str,
        )
        chain = (prompt | llm).with_retry(stop_after_attempt=3)
        try:
            resp = await chain.ainvoke(
                {"messages": [HumanMessage(content=f"Сгенерируй код для файла {file_path}")]}
            )
            raw_code = resp.content if hasattr(resp, "content") else str(resp)
            cleaned = clean_generated_code(raw_code, file_path)
            if cleaned:
                out[file_path] = cleaned
            else:
                errors.append(
                    {"file": file_path, "error": "empty_content_after_clean", "details": "Пустой код после очистки"}
                )
        except Exception as e:
            # Не роняем весь проект из-за одного файла
            errors.append({"file": file_path, "error": type(e).__name__, "details": str(e)})
            continue
    return out, errors


