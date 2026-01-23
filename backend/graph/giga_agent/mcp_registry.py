"""
giga_agent.mcp_registry

Примечание (2026-01-17):
Цель модуля — хранить конфигурацию MCP серверов в БД и использовать её при старте сервисов.
Требование: убрать зависимость от подключения MCP из браузера (CORS/proxy) и перейти к server-side загрузке.

Поведение:
- Источник истины: таблица `mcp_server` в Postgres.
- Если таблица пуста — делаем seed из `GIGA_AGENT_MCP_CONFIG` (обычно приходит из `.docker.env` через env_file),
  а если env переменная не задана — пытаемся аккуратно прочитать `.docker.env` из репозитория.

Важно:
- НИКОГДА не логируем значения токенов/Authorization в открытом виде.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import create_engine, text


MCP_TABLE_NAME = "mcp_server"


@dataclass(frozen=True)
class McpServerRow:
    name: str
    transport: str
    url: str
    headers: Dict[str, str]
    enabled: bool


def _now_iso() -> str:
    return datetime.now().isoformat()


def _get_sync_database_url() -> str:
    """
    Берём DATABASE_URL из окружения и приводим к sync URL для SQLAlchemy create_engine.

    Примечание:
    В проекте используется async URL вида postgresql+asyncpg://...
    Для sync операций в миграциях/seed используем postgresql://...
    """
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@aegra-postgres:5432/postgres",
    )
    return db_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")


def _find_repo_file_upwards(filename: str) -> Optional[Path]:
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        candidate = p / filename
        if candidate.is_file():
            return candidate
    return None


def _read_env_value_from_dotenv_file(dotenv_path: Path, key: str) -> Optional[str]:
    """
    Мини-парсер .env/.docker.env:
    - игнорируем пустые строки и комментарии
    - берём строку формата KEY=VALUE
    - НЕ делаем сложный парсинг кавычек (в проекте MCP JSON хранится одной строкой)
    """
    try:
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()
    except Exception:
        return None
    return None


def _load_mcp_config_from_env_or_docker_env() -> Dict[str, Any]:
    """
    Возвращает dict конфигурации MCP из:
    1) env: GIGA_AGENT_MCP_CONFIG
    2) fallback: файл .docker.env (если найден)
    """
    raw = (os.getenv("GIGA_AGENT_MCP_CONFIG") or "").strip()
    if not raw:
        dotenv = _find_repo_file_upwards(".docker.env")
        if dotenv:
            raw = (_read_env_value_from_dotenv_file(dotenv, "GIGA_AGENT_MCP_CONFIG") or "").strip()

    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        # Невалидный JSON — возвращаем пусто, чтобы не ломать старт
        return {}
    return {}


def sanitize_mcp_config_for_logging(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Маскирует любые заголовки, похожие на авторизационные.
    Примечание: не логируем токены/пароли.
    """
    safe: Dict[str, Any] = {}
    for name, sc in (cfg or {}).items():
        if not isinstance(sc, dict):
            safe[name] = sc
            continue
        sc_safe = dict(sc)
        headers = sc_safe.get("headers")
        if isinstance(headers, dict):
            masked = {}
            for hk, hv in headers.items():
                if hk.lower() in {"authorization", "proxy-authorization", "x-api-key"}:
                    masked[hk] = "***"
                else:
                    # Также маскируем слишком длинные значения на всякий случай
                    masked[hk] = "***" if isinstance(hv, str) and len(hv) > 64 else hv
            sc_safe["headers"] = masked
        safe[name] = sc_safe
    return safe


def ensure_mcp_table_exists() -> None:
    """
    Создаёт таблицу `mcp_server`, если её нет.
    Делаем это безопасно и идемпотентно (IF NOT EXISTS), т.к. таблица нужна и tool_server.
    """
    engine = create_engine(_get_sync_database_url(), echo=False)
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {MCP_TABLE_NAME} (
        id VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL UNIQUE,
        transport VARCHAR NOT NULL DEFAULT 'http',
        url TEXT NOT NULL,
        headers_json TEXT,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at VARCHAR NOT NULL,
        updated_at VARCHAR NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_{MCP_TABLE_NAME}_enabled ON {MCP_TABLE_NAME}(enabled);
    """
    with engine.begin() as conn:
        # SQLAlchemy не любит несколько стейтментов в некоторых драйверах, но для Postgres обычно ок.
        # На всякий случай выполняем по отдельности.
        for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
            conn.execute(text(stmt))
    engine.dispose()


def seed_mcp_table_if_empty() -> int:
    """
    Если таблица пуста — сидим её из GIGA_AGENT_MCP_CONFIG.
    Возвращает количество вставленных строк.
    """
    ensure_mcp_table_exists()
    engine = create_engine(_get_sync_database_url(), echo=False)
    inserted = 0
    with engine.begin() as conn:
        count = conn.execute(text(f"SELECT COUNT(*) FROM {MCP_TABLE_NAME}")).scalar() or 0
        if int(count) > 0:
            return 0

        cfg = _load_mcp_config_from_env_or_docker_env()
        if not cfg:
            return 0

        now = _now_iso()
        for server_name, server_cfg in cfg.items():
            if not isinstance(server_name, str) or not isinstance(server_cfg, dict):
                continue
            url = str(server_cfg.get("url", "")).strip()
            if not url:
                continue
            transport = str(server_cfg.get("transport", "http")).strip() or "http"
            headers = server_cfg.get("headers") if isinstance(server_cfg.get("headers"), dict) else None
            headers_json = json.dumps(headers or {}, ensure_ascii=False)
            conn.execute(
                text(
                    f"""
                    INSERT INTO {MCP_TABLE_NAME}
                        (id, name, transport, url, headers_json, enabled, created_at, updated_at)
                    VALUES
                        (:id, :name, :transport, :url, :headers_json, TRUE, :created_at, :updated_at)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "name": server_name,
                    "transport": transport,
                    "url": url,
                    "headers_json": headers_json,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            inserted += 1
    engine.dispose()
    return inserted


def load_mcp_config_from_db(seed_if_empty: bool = True) -> Dict[str, Dict[str, Any]]:
    """
    Возвращает MCP_CONFIG в формате, который ожидает MultiServerMCPClient:
      { "name": {"transport": "...", "url": "...", "headers": {...}} }
    """
    ensure_mcp_table_exists()
    if seed_if_empty:
        seed_mcp_table_if_empty()

    engine = create_engine(_get_sync_database_url(), echo=False)
    out: Dict[str, Dict[str, Any]] = {}
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT name, transport, url, headers_json, enabled
                FROM {MCP_TABLE_NAME}
                WHERE enabled = TRUE
                ORDER BY name
                """
            )
        ).fetchall()
        for r in rows:
            name = r[0]
            transport = r[1] or "http"
            url = r[2]
            headers_json = r[3] or "{}"
            try:
                headers = json.loads(headers_json) if headers_json else {}
            except json.JSONDecodeError:
                headers = {}
            if not isinstance(headers, dict):
                headers = {}
            out[str(name)] = {"transport": str(transport), "url": str(url), "headers": headers}
    engine.dispose()
    return out


def list_mcp_servers(include_disabled: bool = True) -> list[dict[str, Any]]:
    """
    Возвращает строки реестра MCP серверов из БД (для админки).
    headers_json возвращаем как dict, но значения авторизации маскируем.
    """
    ensure_mcp_table_exists()
    engine = create_engine(_get_sync_database_url(), echo=False)
    out: list[dict[str, Any]] = []
    with engine.begin() as conn:
        where = "" if include_disabled else "WHERE enabled = TRUE"
        rows = conn.execute(
            text(
                f"""
                SELECT name, transport, url, headers_json, enabled, created_at, updated_at
                FROM {MCP_TABLE_NAME}
                {where}
                ORDER BY name
                """
            )
        ).fetchall()
        for r in rows:
            name, transport, url, headers_json, enabled, created_at, updated_at = r
            try:
                headers = json.loads(headers_json) if headers_json else {}
            except json.JSONDecodeError:
                headers = {}
            if not isinstance(headers, dict):
                headers = {}
            masked_cfg = sanitize_mcp_config_for_logging(
                {str(name): {"transport": transport, "url": url, "headers": headers}}
            )
            masked_headers = (masked_cfg.get(str(name), {}) or {}).get("headers") or {}
            out.append(
                {
                    "name": str(name),
                    "transport": str(transport or "http"),
                    "url": str(url),
                    "headers": masked_headers,
                    "enabled": bool(enabled),
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
    engine.dispose()
    return out


def upsert_mcp_server(
    *,
    name: str,
    transport: str,
    url: str,
    headers: Optional[dict[str, str]] = None,
    enabled: bool = True,
) -> None:
    """
    Создаёт или обновляет MCP сервер в реестре.
    Примечание: headers храним как JSON строку (в будущем лучше заменить на secret-ref/шифрование).
    """
    ensure_mcp_table_exists()
    engine = create_engine(_get_sync_database_url(), echo=False)
    now = _now_iso()
    headers_json = json.dumps(headers or {}, ensure_ascii=False)
    with engine.begin() as conn:
        existing = conn.execute(
            text(f"SELECT id FROM {MCP_TABLE_NAME} WHERE name = :name"),
            {"name": name},
        ).fetchone()
        if existing:
            conn.execute(
                text(
                    f"""
                    UPDATE {MCP_TABLE_NAME}
                    SET transport = :transport,
                        url = :url,
                        headers_json = :headers_json,
                        enabled = :enabled,
                        updated_at = :updated_at
                    WHERE name = :name
                    """
                ),
                {
                    "name": name,
                    "transport": transport or "http",
                    "url": url,
                    "headers_json": headers_json,
                    "enabled": bool(enabled),
                    "updated_at": now,
                },
            )
        else:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {MCP_TABLE_NAME}
                        (id, name, transport, url, headers_json, enabled, created_at, updated_at)
                    VALUES
                        (:id, :name, :transport, :url, :headers_json, :enabled, :created_at, :updated_at)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "transport": transport or "http",
                    "url": url,
                    "headers_json": headers_json,
                    "enabled": bool(enabled),
                    "created_at": now,
                    "updated_at": now,
                },
            )
    engine.dispose()


def delete_mcp_server(name: str) -> bool:
    """Удаляет MCP сервер по имени. Возвращает True если удалили, иначе False."""
    ensure_mcp_table_exists()
    engine = create_engine(_get_sync_database_url(), echo=False)
    deleted = 0
    with engine.begin() as conn:
        res = conn.execute(
            text(f"DELETE FROM {MCP_TABLE_NAME} WHERE name = :name"),
            {"name": name},
        )
        deleted = getattr(res, "rowcount", 0) or 0
    engine.dispose()
    return deleted > 0


def set_mcp_server_enabled(name: str, enabled: bool) -> bool:
    """Включает/выключает MCP сервер. Возвращает True если обновили, иначе False."""
    ensure_mcp_table_exists()
    engine = create_engine(_get_sync_database_url(), echo=False)
    now = _now_iso()
    updated = 0
    with engine.begin() as conn:
        res = conn.execute(
            text(
                f"""
                UPDATE {MCP_TABLE_NAME}
                SET enabled = :enabled, updated_at = :updated_at
                WHERE name = :name
                """
            ),
            {"name": name, "enabled": bool(enabled), "updated_at": now},
        )
        updated = getattr(res, "rowcount", 0) or 0
    engine.dispose()
    return updated > 0

