"""
Context offloading (Этап 2 из ROMA_OPTIMIZE.MD)

Зачем:
- большие результаты инструментов раздувают историю сообщений и тратят токены
- вместо "простыней" в ToolMessage сохраняем полный результат на диск (FILES_DIR),
  а в контекст кладём краткое превью + ссылку на файл (через /files/...)

Важно:
- FILES_DIR в docker-compose смонтирован как /files и проксируется через upload_server -> /files/<path>
- фронт умеет открывать пути, начинающиеся с /files/ (см. MessageAttachment.tsx)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union


JsonLike = Union[Dict[str, Any], list, str, int, float, bool, None]


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_files_dir() -> Path:
    # Примечание: в docker-compose.yml FILES_DIR=/files и volume ./files:/files
    return Path(os.getenv("FILES_DIR", "/files"))


def _safe_component(value: str, max_len: int = 80) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        return "unknown"
    return value[:max_len]


def _json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        return json.dumps({"_non_serializable": str(obj)}, ensure_ascii=False, indent=2)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True)
class OffloadResult:
    # Путь, который понимает фронт: /files/<...>
    url_path: str
    # Абсолютный путь внутри контейнера (FILES_DIR/...)
    abs_path: str
    # Размер исходного JSON/текста (в символах)
    original_chars: int
    # sha256 от исходного текста (для отладки/идемпотентности)
    sha256: str


def maybe_offload_tool_payload(
    *,
    payload: Any,
    store_payload: Optional[Any] = None,
    tool_name: str,
    tool_call_id: str,
    thread_id: Optional[str],
    existing_tool_attachments: Optional[list],
) -> Tuple[Any, list, Optional[OffloadResult]]:
    """
    Если payload слишком большой, сохраняем полный текст в FILES_DIR/offloads/...
    Возвращаем:
    - новый payload (короткий summary)
    - обновлённые tool_attachments (добавлен файл со ссылкой)
    - метаданные offload или None

    Примечания:
    - Вложения для фронта должны содержать file_id/path, который начинается с /files/
    - MIME type ставим text/plain, чтобы фронт показал как "текстовый файл"
    """
    threshold_chars = _env_int("GIGA_AGENT_CONTEXT_OFFLOAD_THRESHOLD_CHARS", 20_000)
    preview_chars = _env_int("GIGA_AGENT_CONTEXT_OFFLOAD_PREVIEW_CHARS", 2_000)

    # Что сохраняем на диск (может отличаться от payload, который кладём в контекст)
    # Примечание: payload может быть уже "подрезан" политикой tool_graph.py, но store_payload — полный оригинал.
    to_store = payload if store_payload is None else store_payload

    # Приводим к строке для измерения и сохранения
    if isinstance(to_store, str):
        text = to_store
        ext = "txt"
    else:
        text = _json_dumps(to_store)
        ext = "json"

    if len(text) <= threshold_chars:
        return payload, (existing_tool_attachments or []), None

    files_dir = get_files_dir()
    safe_tool = _safe_component(tool_name)
    safe_thread = _safe_component(thread_id or "no_thread", max_len=120)
    safe_call = _safe_component(tool_call_id, max_len=120)
    ts = time.strftime("%Y%m%d_%H%M%S")

    rel_dir = Path("offloads") / safe_thread / safe_tool
    abs_dir = files_dir / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{ts}_{safe_call}.{ext}"
    abs_path = abs_dir / filename

    # Пишем атомарно: сначала во временный, затем replace
    tmp_path = abs_path.with_suffix(abs_path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8", errors="replace")
    tmp_path.replace(abs_path)

    url_path = f"/files/{rel_dir.as_posix()}/{filename}"
    off = OffloadResult(
        url_path=url_path,
        abs_path=str(abs_path),
        original_chars=len(text),
        sha256=_sha256_text(text),
    )

    preview = text[:preview_chars]
    # Формируем компактный payload для контекста
    new_payload: Any
    if isinstance(payload, dict):
        new_payload = dict(payload)  # shallow copy, ничего не удаляем без явного намерения
        # КРИТИЧЕСКИ ВАЖНО: сохраняем giga_attachments, если они есть в payload
        # Они уже обработаны в tool_graph.py и добавлены в tool_attachments,
        # но нужно сохранить их в new_payload для совместимости
        if "giga_attachments" in payload:
            # giga_attachments уже обработаны, но сохраняем ссылку на них
            # чтобы фронтенд мог их найти
            new_payload["giga_attachments"] = payload["giga_attachments"]
        new_payload["offloaded"] = True
        new_payload["offload_path"] = off.url_path
        new_payload["offload_original_chars"] = off.original_chars
        new_payload["offload_sha256"] = off.sha256
        # Сообщение для LLM: что полный вывод вынесен в файл
        # Важно: превью оставляем маленьким, чтобы не тратить токены.
        new_payload["offload_preview"] = preview
    else:
        new_payload = {
            "offloaded": True,
            "offload_path": off.url_path,
            "offload_original_chars": off.original_chars,
            "offload_sha256": off.sha256,
            "offload_preview": preview,
        }

    tool_attachments = list(existing_tool_attachments or [])
    tool_attachments.append(
        {
            "type": "text/plain",
            # В ToolMessage.tsx берётся file_id||path и передаётся в MessageAttachment
            "file_id": off.url_path,
        }
    )

    return new_payload, tool_attachments, off

