"""
Утилиты для безопасной записи сгенерированных файлов на диск и упаковки в ZIP.
"""

from __future__ import annotations

import os
import json
import zipfile
from pathlib import Path
from typing import Dict, Tuple, Any, Optional


def _safe_relpath(rel_path: str) -> str:
    # Нормализуем разделители и запрещаем выход из корня проекта
    p = (rel_path or "").replace("\\", "/").lstrip("/")
    parts = [part for part in p.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError(f"Небезопасный путь (path traversal): {rel_path}")
    return "/".join(parts)


def write_project_files(project_dir: Path, project_files: Dict[str, str]) -> Tuple[int, int]:
    """
    Пишет файлы в project_dir.
    Returns: (files_count, total_bytes)
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    files_count = 0

    for rel_path, content in (project_files or {}).items():
        safe_rel = _safe_relpath(rel_path)
        if not safe_rel:
            continue
        target = project_dir / safe_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (content or "").encode("utf-8")
        target.write_bytes(data)
        total_bytes += len(data)
        files_count += 1

    return files_count, total_bytes


def make_zip_from_dir(project_dir: Path, zip_path: Path) -> int:
    """
    Упаковывает project_dir в zip_path.
    Returns: zip_size bytes
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in project_dir.rglob("*"):
            if file_path.is_dir():
                continue
            arcname = file_path.relative_to(project_dir).as_posix()
            zf.write(file_path, arcname=arcname)

    return int(zip_path.stat().st_size) if zip_path.exists() else 0


def get_files_dir() -> Path:
    # Совместимо с существующими агентами (например, tinkoff charts)
    return Path(os.environ.get("FILES_DIR", "files"))


def read_json(path: Path) -> Optional[dict]:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


