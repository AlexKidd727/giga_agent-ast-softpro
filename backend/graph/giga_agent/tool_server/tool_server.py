import os
import traceback
import logging
import random
import string
from contextlib import asynccontextmanager
import asyncio
from typing import Optional

from fastapi import FastAPI, Body
# Опциональный импорт langchain-gigachat (может быть не установлен)
try:
    from langchain_gigachat.utils.function_calling import convert_to_gigachat_tool
    GIGACHAT_AVAILABLE = True
except ImportError:
    GIGACHAT_AVAILABLE = False
    # Заглушка для случая, когда gigachat не установлен
    def convert_to_gigachat_tool(tool):
        # Возвращаем стандартный формат инструмента
        return {"function": {
            "name": tool.name if hasattr(tool, "name") else str(tool),
            "description": tool.description if hasattr(tool, "description") else "",
            "parameters": tool.args_schema.schema() if hasattr(tool, "args_schema") and hasattr(tool.args_schema, "schema") else {}
        }}

from langgraph_sdk.client import get_client
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt.tool_node import _handle_tool_error, ToolNode
from pydantic_core import ValidationError
from fastapi.responses import JSONResponse
import httpx

from giga_agent.tool_server.utils import transform_schema, transform_tool
from giga_agent.utils.env import load_project_env
from giga_agent.utils.langgraph import inject_tool_args_compat
from giga_agent.config import TOOLS, REPL_TOOLS, AGENT_MAP
from giga_agent.mcp_registry import (
    load_mcp_config_from_db,
    sanitize_mcp_config_for_logging,
)

# Настройка логирования для диагностики MCP
logger = logging.getLogger(__name__)

tool_map = {}
repl_tool_map = {}
config = {}

load_project_env()

_mcp_reload_lock = asyncio.Lock()

# Примечание:
# При первом подключении MultiServerMCPClient может делать несколько сетевых шагов/handshake.
# На практике в lifespan лучше иметь большой таймаут, иначе мы получаем ложные TimeoutError
# и MCP инструменты вообще не поднимаются.
MCP_CONNECT_TIMEOUT_SECONDS = float(os.getenv("GIGA_AGENT_MCP_CONNECT_TIMEOUT_SECONDS", "120"))


def _augment_mcp_server_config(server_config: dict) -> dict:
    """
    Нормализует server_config (без принудительной подмены заголовков).

    ВАЖНО (2026-01-17):
    Ранее тут пытались принудительно выставлять Accept: "application/json, text/event-stream".
    Но часть MCP реализаций (FastMCP) использует session-id flow и может возвращать SSE/требовать
    особый handshake. `langchain_mcp_adapters` умеет договариваться сам — поэтому не вмешиваемся
    в заголовки, чтобы не ломать транспорт/сессии.
    """
    cfg = dict(server_config or {})
    headers = cfg.get("headers")
    if not isinstance(headers, dict):
        headers = {}
    else:
        headers = dict(headers)
    cfg["headers"] = headers
    return cfg


def _parse_first_json_from_event_stream(text: str) -> dict:
    """
    Мини-парсер text/event-stream: ищем первую строку вида `data: {...}` и парсим JSON.
    """
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            try:
                import json

                return json.loads(payload)
            except Exception:
                return {}
    return {}


def _format_exception_group(e: BaseException) -> str:
    """
    Делает читаемую строку для ExceptionGroup/любого исключения.
    """
    parts: list[str] = [f"{type(e).__name__}: {e}"]
    excs = getattr(e, "exceptions", None)
    if isinstance(excs, (list, tuple)):
        parts.append(f"sub_exceptions={len(excs)}")
        for i, sub in enumerate(excs[:5], 1):
            parts.append(f"[{i}] {type(sub).__name__}: {sub}")
    return " | ".join(parts)


def _get_mcp_tools_blocking(mcp_config: dict) -> list:
    """
    Блокирующая загрузка MCP tools в отдельном потоке.

    Почему так:
    В практике `MultiServerMCPClient.get_tools()` иногда ведёт себя нестабильно/зависает в uvicorn
    lifespan loop, при этом стабильно работает в отдельном процессе/через `uv run python`.
    Запуск в отдельном потоке со своим `asyncio.run()` устраняет конфликт контекстов.
    """
    async def _inner() -> list:
        """
        Грузим MCP tools несколькими группами, чтобы изолировать проблемные сочетания серверов.

        Наблюдение:
        - `pc_management` (host.docker.internal) стабильно работает отдельно,
          но в общем TaskGroup иногда падает с 502.
        """
        cfg = mcp_config or {}
        group_host = {k: v for k, v in cfg.items() if "host.docker.internal" in str((v or {}).get("url", ""))}
        group_other = {k: v for k, v in cfg.items() if k not in group_host}

        groups: list[dict] = []
        if group_other:
            groups.append(group_other)
        if group_host:
            groups.append(group_host)

        all_tools: list = []
        for idx, group in enumerate(groups, 1):
            # Retry внутри потока/loop: на практике некоторые MCP могут дать временный 502.
            last_err: Optional[BaseException] = None
            for attempt in range(1, 4):
                try:
                    client = MultiServerMCPClient({k: _augment_mcp_server_config(v) for k, v in group.items()})
                    part = await client.get_tools()
                    if part:
                        all_tools.extend(part)
                    last_err = None
                    break
                except BaseException as e:
                    last_err = e
                    # небольшая пауза перед повтором
                    await asyncio.sleep(0.4)
            if last_err is not None:
                try:
                    logger.error(f"[MCP] (thread) get_tools group#{idx} failed after retries: {_format_exception_group(last_err)}")
                except Exception:
                    pass
        return all_tools

    if not mcp_config:
        return []
    return asyncio.run(_inner())


async def _probe_mcp_tools_list_http(server_name: str, server_cfg: dict) -> tuple[list[str], Optional[str]]:
    """
    Ручной probe MCP (HTTP):
    - initialize (получаем mcp-session-id, если сервер его выдаёт)
    - tools/list (с session-id если требуется)

    Нужен для корректного server->tools маппинга и статуса в /mcp_servers_info.

    ВАЖНО: trust_env=False — внутренние/локальные сервисы не должны ходить через proxy.
    """
    url = (server_cfg or {}).get("url") or ""
    if not isinstance(url, str) or not url:
        return [], "missing url"
    headers = (server_cfg or {}).get("headers") or {}
    if not isinstance(headers, dict):
        headers = {}
    headers = dict(headers)

    # Многие MCP (FastMCP) требуют, чтобы клиент принимал и JSON, и event-stream.
    headers.setdefault("Accept", "application/json, text/event-stream")

    init_payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "giga_agent-dev", "version": "0"},
        },
    }
    tools_payload = {"jsonrpc": "2.0", "id": "2", "method": "tools/list", "params": {}}

    session_id: Optional[str] = None
    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        r1 = await client.post(url, json=init_payload, headers=headers)
        if r1.status_code != 200:
            return [], f"initialize HTTP {r1.status_code}: {r1.text[:200]}"

        session_id = r1.headers.get("mcp-session-id") or r1.headers.get("Mcp-Session-Id")
        # Если вернулся event-stream, всё равно ок (session-id в header)

        headers2 = dict(headers)
        if session_id:
            headers2["Mcp-Session-Id"] = session_id

        r2 = await client.post(url, json=tools_payload, headers=headers2)
        if r2.status_code != 200:
            return [], f"tools/list HTTP {r2.status_code}: {r2.text[:200]}"

        data: dict
        ct = (r2.headers.get("content-type") or "").lower()
        if "text/event-stream" in ct:
            data = _parse_first_json_from_event_stream(r2.text)
        else:
            try:
                data = r2.json()
            except Exception:
                data = {}

        tools = ((data.get("result") or {}).get("tools") or []) if isinstance(data, dict) else []
        if not isinstance(tools, list):
            return [], "tools/list: invalid response format"
        names: list[str] = []
        for t in tools:
            if isinstance(t, dict) and isinstance(t.get("name"), str):
                names.append(t["name"])
        return names, None


async def _load_mcp_tools_per_server(mcp_config: dict) -> tuple[list, dict, list]:
    """
    Загружает MCP инструменты по одному серверу, чтобы недоступный сервер не "обнулял" остальные.

    Пример проблемы:
    `finance` недоступен -> общий `MultiServerMCPClient.get_tools()` падает -> `web-site` перестаёт определяться,
    хотя отдельно `web-site` возвращает инструменты.
    """
    mcp_tools: list = []
    servers_tools_map: dict = {}
    failed_servers: list = []

    for server_name, server_cfg in (mcp_config or {}).items():
        try:
            server_tools = await asyncio.wait_for(
                asyncio.to_thread(_get_mcp_tools_blocking, {server_name: server_cfg}),
                timeout=MCP_CONNECT_TIMEOUT_SECONDS,
            )
            servers_tools_map[server_name] = server_tools or []
            if server_tools:
                mcp_tools.extend(server_tools)
        except asyncio.TimeoutError:
            servers_tools_map[server_name] = []
            failed_servers.append(
                {
                    "name": server_name,
                    "url": (server_cfg or {}).get("url", "N/A"),
                    "error": f"Timeout - сервер не отвечает в течение {MCP_CONNECT_TIMEOUT_SECONDS:g} секунд",
                    "error_type": "TimeoutError",
                }
            )
        except Exception as e:
            servers_tools_map[server_name] = []
            failed_servers.append(
                {
                    "name": server_name,
                    "url": (server_cfg or {}).get("url", "N/A"),
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )

    return mcp_tools, servers_tools_map, failed_servers


async def reload_mcp_from_db() -> dict:
    """
    Hot-reload MCP:
    - перечитать mcp_server из БД (seed при пустой таблице)
    - переподключиться к MCP серверам
    - пересобрать tool_node/tool_map/config в памяти

    Примечание:
    - Значения токенов в логах не показываем (используем sanitize_mcp_config_for_logging).
    - Реализация сделана отдельно от startup-логики, чтобы избежать рестарта сервиса.
    """
    async with _mcp_reload_lock:
        mcp_config = load_mcp_config_from_db(seed_if_empty=True)
        safe_cfg = sanitize_mcp_config_for_logging(mcp_config)
        logger.info(f"[MCP] Hot-reload: MCP_CONFIG(DB): {safe_cfg}")

        mcp_tools = []
        failed_servers = []
        servers_tools_map = {}

        # Загружаем инструменты по одному серверу, чтобы падение одного не ломало остальные.
        if mcp_config:
            try:
                mcp_tools, servers_tools_map, failed_servers = await _load_mcp_tools_per_server(mcp_config)
            except Exception as e:
                logger.error(f"[MCP] Hot-reload: load_mcp_tools_per_server failed: {_format_exception_group(e)}")
                mcp_tools, servers_tools_map, failed_servers = [], {}, []

        # Нормализация MCP инструментов (как при старте)
        for mcp_tool in mcp_tools:
            try:
                original_name = mcp_tool.name
                mcp_tool.name = mcp_tool.name.replace("-", "_")
                if original_name != mcp_tool.name:
                    logger.debug(f"[MCP] Hot-reload: rename {original_name} -> {mcp_tool.name}")
                if isinstance(mcp_tool.args_schema, dict):
                    mcp_tool.args_schema = transform_schema(mcp_tool.args_schema)
            except Exception as tool_error:
                logger.error(f"[MCP] Hot-reload: ошибка обработки инструмента {getattr(mcp_tool, 'name', 'unknown')}: {tool_error}")
                continue

        # Пересобираем tool_node + карты
        tools = TOOLS + mcp_tools
        config["tool_node"] = ToolNode(tools=tools)

        tool_map.clear()
        for tool in tools:
            tool_map[tool.name] = tool

        repl_tool_map.clear()
        for tool in REPL_TOOLS:
            repl_tool_map[tool.__name__] = tool

        config["mcp_tools"] = mcp_tools
        config["servers_tools_map"] = servers_tools_map

        # Пересобираем mcp_servers_info (для /mcp_servers_info)
        config["mcp_servers_info"] = []
        for server_name, server_config in mcp_config.items():
            server_tools = servers_tools_map.get(server_name, [])
            status = "connected" if len(server_tools) > 0 else "unknown"
            if server_name in [s["name"] for s in failed_servers]:
                status = "failed"
            server_info = {
                "name": server_name,
                "url": server_config.get("url", "N/A"),
                "transport": server_config.get("transport", "http"),
                "status": status,
                "tools_count": len(server_tools),
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description if hasattr(t, "description") else "",
                    }
                    for t in server_tools
                ],
            }
            failed_server = next((s for s in failed_servers if s["name"] == server_name), None)
            if failed_server:
                server_info["error"] = failed_server.get("error")
            config["mcp_servers_info"].append(server_info)

        return {
            "mcp_servers": list(mcp_config.keys()),
            "mcp_tools_count": len(mcp_tools),
            "failed_servers": failed_servers,
        }


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализация MCP клиента с логированием и обработкой ошибок
    mcp_tools = []
    
    try:
        # Примечание:
        # MCP конфиг теперь читается из БД (таблица mcp_server).
        # Если таблица пустая — автоматически делаем seed из GIGA_AGENT_MCP_CONFIG (.docker.env/env_file).
        mcp_config = load_mcp_config_from_db(seed_if_empty=True)

        # ВАЖНО: не логируем токены/Authorization — выводим только маскированный конфиг.
        safe_cfg = sanitize_mcp_config_for_logging(mcp_config)
        print(f"[MCP] Инициализация MCP клиента. MCP_CONFIG(DB): {safe_cfg}")
        logger.info(f"[MCP] Инициализация MCP клиента. MCP_CONFIG(DB): {safe_cfg}")
        
        if not mcp_config or len(mcp_config) == 0:
            print("[MCP] MCP_CONFIG пуст (БД). MCP инструменты не будут загружены.")
            print("[MCP] Заполните таблицу mcp_server (или задайте GIGA_AGENT_MCP_CONFIG для seed при пустой таблице).")
            logger.warning("[MCP] MCP_CONFIG пуст (БД). MCP инструменты не будут загружены.")
            logger.warning("[MCP] Заполните таблицу mcp_server (или задайте GIGA_AGENT_MCP_CONFIG для seed при пустой таблице).")
        else:
            print(f"[MCP] Подключение к {len(mcp_config)} MCP сервер(ам): {list(mcp_config.keys())}")
            logger.info(f"[MCP] Подключение к {len(mcp_config)} MCP сервер(ам): {list(mcp_config.keys())}")
            
            # ВАЖНО:
            # Для MCP серверов типа FastMCP корректнее и стабильнее подключаться одним MultiServerMCPClient
            # (он сам управляет session-id flow). Отдельные клиенты "по одному серверу" в практике
            # давали ложные timeout/502.
            failed_servers = []
            servers_tools_map = {}

            try:
                mcp_tools, servers_tools_map, failed_servers = await _load_mcp_tools_per_server(mcp_config)
            except Exception as e:
                logger.error(f"[MCP] load_mcp_tools_per_server failed: {_format_exception_group(e)}")
                mcp_tools, servers_tools_map, failed_servers = [], {}, []
            
            # Логируем итоговый результат
            if mcp_tools:
                tool_names = [tool.name for tool in mcp_tools]
                print(f"[MCP] ✅ Итого получено {len(mcp_tools)} инструментов от {len(mcp_config) - len(failed_servers)}/{len(mcp_config)} серверов")
                print(f"[MCP]    Инструменты: {tool_names}")
                logger.info(f"[MCP] ✅ Итого получено {len(mcp_tools)} инструментов от {len(mcp_config) - len(failed_servers)}/{len(mcp_config)} серверов")
            else:
                print(f"[MCP] ⚠️ Не удалось получить инструменты ни от одного сервера")
                logger.warning(f"[MCP] ⚠️ Не удалось получить инструменты ни от одного сервера")
            
            if failed_servers:
                print(f"[MCP] ⚠️ Не удалось подключиться к {len(failed_servers)} серверу(ам):")
                for failed in failed_servers:
                    print(f"[MCP]    - {failed['name']} ({failed['url']}): {failed['error_type']}")
                logger.warning(f"[MCP] ⚠️ Не удалось подключиться к {len(failed_servers)} серверу(ам)")
        
        # Обрабатываем полученные MCP инструменты
        for mcp_tool in mcp_tools:
            try:
                original_name = mcp_tool.name
                mcp_tool.name = mcp_tool.name.replace("-", "_")
                if original_name != mcp_tool.name:
                    logger.debug(f"[MCP] Переименован инструмент: {original_name} -> {mcp_tool.name}")
                    
                if isinstance(mcp_tool.args_schema, dict):
                    mcp_tool.args_schema = transform_schema(mcp_tool.args_schema)
            except Exception as tool_error:
                logger.error(f"[MCP] Ошибка при обработке инструмента {mcp_tool.name}: {tool_error}")
                # Продолжаем обработку остальных инструментов
                continue
        
        # Создаем финальный список инструментов
        tools = TOOLS + mcp_tools
        print(f"[MCP] Всего инструментов загружено: {len(TOOLS)} базовых + {len(mcp_tools)} MCP = {len(tools)}")
        logger.info(f"[MCP] Всего инструментов загружено: {len(TOOLS)} базовых + {len(mcp_tools)} MCP = {len(tools)}")
        
        # Проверяем наличие career_agent в TOOLS
        career_agent_found = any(tool.name == "career_agent" for tool in TOOLS if hasattr(tool, 'name'))
        if career_agent_found:
            print(f"[TOOL_SERVER] ✅ career_agent найден в TOOLS")
            logger.info(f"[TOOL_SERVER] ✅ career_agent найден в TOOLS")
        else:
            tool_names = [tool.name for tool in TOOLS if hasattr(tool, 'name')]
            print(f"[TOOL_SERVER] ⚠️ career_agent НЕ найден в TOOLS. Доступные инструменты: {tool_names[:10]}...")
            logger.warning(f"[TOOL_SERVER] ⚠️ career_agent НЕ найден в TOOLS. Доступные инструменты: {tool_names[:10]}...")
        
        # Проверяем наличие lawyer_agent в TOOLS
        lawyer_agent_found = any(tool.name == "lawyer_agent" for tool in TOOLS if hasattr(tool, 'name'))
        if lawyer_agent_found:
            print(f"[TOOL_SERVER] ✅ lawyer_agent найден в TOOLS")
            logger.info(f"[TOOL_SERVER] ✅ lawyer_agent найден в TOOLS")
        else:
            tool_names = [tool.name for tool in TOOLS if hasattr(tool, 'name')]
            print(f"[TOOL_SERVER] ⚠️ lawyer_agent НЕ найден в TOOLS. Доступные инструменты: {tool_names[:10]}...")
            logger.warning(f"[TOOL_SERVER] ⚠️ lawyer_agent НЕ найден в TOOLS. Доступные инструменты: {tool_names[:10]}...")
        
        # Проверяем наличие switch_provider в TOOLS
        switch_provider_found = any(tool.name == "switch_provider" for tool in TOOLS if hasattr(tool, 'name'))
        if switch_provider_found:
            print(f"[TOOL_SERVER] ✅ switch_provider найден в TOOLS")
            logger.info(f"[TOOL_SERVER] ✅ switch_provider найден в TOOLS")
        else:
            tool_names = [tool.name for tool in TOOLS if hasattr(tool, 'name')]
            print(f"[TOOL_SERVER] ⚠️ switch_provider НЕ найден в TOOLS. Доступные инструменты: {tool_names[:20]}...")
            logger.warning(f"[TOOL_SERVER] ⚠️ switch_provider НЕ найден в TOOLS. Доступные инструменты: {tool_names[:20]}...")
        
        config["tool_node"] = ToolNode(tools=tools)
        for tool in tools:
            tool_map[tool.name] = tool
            # Логируем загрузку career_agent
            if hasattr(tool, 'name') and tool.name == "career_agent":
                print(f"[TOOL_SERVER] ✅ career_agent загружен в tool_map: {tool.name}, тип: {type(tool)}")
                logger.info(f"[TOOL_SERVER] ✅ career_agent загружен в tool_map: {tool.name}, тип: {type(tool)}")
            # Логируем загрузку lawyer_agent
            if hasattr(tool, 'name') and tool.name == "lawyer_agent":
                print(f"[TOOL_SERVER] ✅ lawyer_agent загружен в tool_map: {tool.name}, тип: {type(tool)}")
                logger.info(f"[TOOL_SERVER] ✅ lawyer_agent загружен в tool_map: {tool.name}, тип: {type(tool)}")
            # Логируем загрузку switch_provider
            if hasattr(tool, 'name') and tool.name == "switch_provider":
                print(f"[TOOL_SERVER] ✅ switch_provider загружен в tool_map: {tool.name}, тип: {type(tool)}")
                logger.info(f"[TOOL_SERVER] ✅ switch_provider загружен в tool_map: {tool.name}, тип: {type(tool)}")
        for tool in REPL_TOOLS:
            repl_tool_map[tool.__name__] = tool
        
        # Сохраняем список MCP инструментов отдельно для доступа через API
        config["mcp_tools"] = mcp_tools
        
        # Сохраняем информацию о серверах и их статусе для API
        config["mcp_servers_info"] = []
        config["servers_tools_map"] = servers_tools_map  # Сохраняем маппинг сервер -> инструменты
        
        for server_name, server_config in mcp_config.items():
            server_tools = servers_tools_map.get(server_name, [])
            server_info = {
                "name": server_name,
                "url": server_config.get("url", "N/A"),
                "transport": server_config.get("transport", "http"),
                "status": "connected" if len(server_tools) > 0 else ("failed" if server_name in [s["name"] for s in failed_servers] else "unknown"),
                "tools_count": len(server_tools),
                "tools": [{
                    "name": tool.name,
                    "description": tool.description if hasattr(tool, 'description') else "",
                } for tool in server_tools]
            }
            # Добавляем информацию об ошибке, если сервер не подключен
            if server_name in [s["name"] for s in failed_servers]:
                failed_server = next((s for s in failed_servers if s["name"] == server_name), None)
                if failed_server:
                    server_info["error"] = failed_server.get("error", "Unknown error")
            config["mcp_servers_info"].append(server_info)
        
        print(f"[MCP] Инициализация завершена. Загружено {len(tool_map)} инструментов в tool_map")
        logger.info(f"[MCP] Инициализация завершена. Загружено {len(tool_map)} инструментов в tool_map")
        
        # Проверяем, что career_agent и switch_provider в tool_map
        if "career_agent" in tool_map:
            print(f"[TOOL_SERVER] ✅ career_agent доступен в tool_map")
            logger.info(f"[TOOL_SERVER] ✅ career_agent доступен в tool_map")
        else:
            print(f"[TOOL_SERVER] ❌ career_agent НЕ найден в tool_map!")
            logger.error(f"[TOOL_SERVER] ❌ career_agent НЕ найден в tool_map!")
            # Выводим список всех инструментов для отладки
            all_tool_names = list(tool_map.keys())
            print(f"[TOOL_SERVER] Доступные инструменты в tool_map ({len(all_tool_names)}): {all_tool_names[:20]}...")
            logger.info(f"[TOOL_SERVER] Доступные инструменты в tool_map ({len(all_tool_names)}): {all_tool_names[:20]}...")
        
        if "switch_provider" in tool_map:
            print(f"[TOOL_SERVER] ✅ switch_provider доступен в tool_map")
            logger.info(f"[TOOL_SERVER] ✅ switch_provider доступен в tool_map")
        else:
            print(f"[TOOL_SERVER] ⚠️ switch_provider НЕ доступен в tool_map. Доступные: {list(tool_map.keys())[:20]}...")
            logger.warning(f"[TOOL_SERVER] ⚠️ switch_provider НЕ доступен в tool_map. Доступные: {list(tool_map.keys())[:20]}...")
        
        # Проверяем, что lawyer_agent в tool_map
        if "lawyer_agent" in tool_map:
            print(f"[TOOL_SERVER] ✅ lawyer_agent доступен в tool_map")
            logger.info(f"[TOOL_SERVER] ✅ lawyer_agent доступен в tool_map")
        else:
            print(f"[TOOL_SERVER] ❌ lawyer_agent НЕ найден в tool_map!")
            logger.error(f"[TOOL_SERVER] ❌ lawyer_agent НЕ найден в tool_map!")
            all_tool_names = list(tool_map.keys())
            print(f"[TOOL_SERVER] Доступные инструменты в tool_map ({len(all_tool_names)}): {all_tool_names[:20]}...")
            logger.info(f"[TOOL_SERVER] Доступные инструменты в tool_map ({len(all_tool_names)}): {all_tool_names[:20]}...")
        
        if mcp_tools:
            mcp_tool_names = [tool.name for tool in mcp_tools]
            print(f"[MCP] MCP инструменты сохранены: {mcp_tool_names}")
            logger.info(f"[MCP] MCP инструменты сохранены: {mcp_tool_names}")
        
    except Exception as e:
        import traceback as tb
        print(f"[MCP] КРИТИЧЕСКАЯ ОШИБКА при инициализации MCP: {e}")
        print(f"[MCP] Traceback: {tb.format_exc()}")
        logger.error(f"[MCP] Критическая ошибка при инициализации MCP: {e}")
        logger.error(f"[MCP] Traceback: {tb.format_exc()}")
        # Продолжаем работу без MCP инструментов
        tools = TOOLS
        config["tool_node"] = ToolNode(tools=tools)
        for tool in tools:
            tool_map[tool.name] = tool
            # Логируем загрузку career_agent
            if hasattr(tool, 'name') and tool.name == "career_agent":
                print(f"[TOOL_SERVER] ✅ career_agent загружен в tool_map (без MCP): {tool.name}, тип: {type(tool)}")
                logger.info(f"[TOOL_SERVER] ✅ career_agent загружен в tool_map (без MCP): {tool.name}, тип: {type(tool)}")
        for tool in REPL_TOOLS:
            repl_tool_map[tool.__name__] = tool
        print("[MCP] Продолжаем работу без MCP инструментов")
        logger.warning("[MCP] Продолжаем работу без MCP инструментов")
        
        # Проверяем, что career_agent в tool_map
        if "career_agent" in tool_map:
            print(f"[TOOL_SERVER] ✅ career_agent доступен в tool_map (без MCP)")
            logger.info(f"[TOOL_SERVER] ✅ career_agent доступен в tool_map (без MCP)")
        else:
            print(f"[TOOL_SERVER] ❌ career_agent НЕ найден в tool_map (без MCP)!")
            logger.error(f"[TOOL_SERVER] ❌ career_agent НЕ найден в tool_map (без MCP)!")
    
    yield
    
    # Очистка при завершении
    repl_tool_map.clear()
    tool_map.clear()
    config.clear()
    logger.info("[MCP] Очистка ресурсов завершена")


app = FastAPI(lifespan=lifespan)
langgraph_client = get_client(url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024"))


@app.get("/tools")
async def get_tools():
    """Получение списка всех доступных инструментов"""
    try:
        tools = []
        career_agent_in_list = False
        errors = []
        
        for tool in tool_map.values():
            try:
                tool_dict = convert_to_gigachat_tool(tool)["function"]
                
                # КРИТИЧЕСКИ ВАЖНО: Применяем transform_schema к parameters для исправления type: null
                # Это гарантирует, что схема всегда имеет type: "object" для OpenAI API
                if "parameters" in tool_dict and isinstance(tool_dict["parameters"], dict):
                    tool_dict["parameters"] = transform_schema(tool_dict["parameters"])
                    # Дополнительная проверка: убеждаемся, что type: "object"
                    if tool_dict["parameters"].get("type") != "object":
                        logger.warning(f"[TOOL_SERVER] Исправляю type для инструмента {tool_dict.get('name', 'unknown')}: {tool_dict['parameters'].get('type')} -> object")
                        tool_dict["parameters"]["type"] = "object"
                        if "properties" not in tool_dict["parameters"]:
                            tool_dict["parameters"]["properties"] = {}
                
                tools.append(tool_dict)
                # Проверяем наличие career_agent в списке
                if tool_dict.get("name") == "career_agent":
                    career_agent_in_list = True
                    logger.info(f"[TOOL_SERVER] ✅ career_agent найден в списке инструментов для /tools")
            except Exception as e:
                # Логируем ошибку для конкретного инструмента, но продолжаем обработку остальных
                tool_name = getattr(tool, 'name', 'unknown') if hasattr(tool, 'name') else str(tool)
                error_msg = f"Ошибка при обработке инструмента {tool_name}: {str(e)}"
                logger.error(f"[TOOL_SERVER] {error_msg}")
                logger.error(f"[TOOL_SERVER] Traceback: {traceback.format_exc()}")
                errors.append(error_msg)
                # Пропускаем проблемный инструмент, но продолжаем обработку остальных
        
        if not career_agent_in_list:
            logger.warning(f"[TOOL_SERVER] ⚠️ career_agent НЕ найден в списке инструментов для /tools")
            # Выводим список всех инструментов для отладки
            tool_names = [t.get("name", "unknown") for t in tools]
            logger.info(f"[TOOL_SERVER] Доступные инструменты в /tools ({len(tool_names)}): {tool_names[:20]}...")
        
        logger.info(f"[TOOL_SERVER] Возвращено {len(tools)} инструментов через /tools")
        
        # Для обратной совместимости возвращаем список напрямую, если нет ошибок
        # Если есть ошибки, возвращаем объект с полями tools и errors
        if errors:
            logger.warning(f"[TOOL_SERVER] При обработке инструментов произошло {len(errors)} ошибок")
            return JSONResponse(content={"tools": tools, "errors": errors})
        
        # Возвращаем список напрямую для обратной совместимости
        return tools
    except Exception as e:
        # Критическая ошибка - возвращаем JSON с описанием ошибки
        error_msg = f"Критическая ошибка при получении списка инструментов: {str(e)}"
        logger.error(f"[TOOL_SERVER] {error_msg}")
        logger.error(f"[TOOL_SERVER] Traceback: {traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={
                "error": error_msg,
                "tools": [],
                "traceback": traceback.format_exc() if os.getenv("DEBUG", "0") == "1" else None
            }
        )

@app.get("/mcp_tools")
async def get_mcp_tools():
    """Возвращает только MCP инструменты в формате для state["mcp_tools"]"""
    mcp_tools_list = config.get("mcp_tools", [])
    result = []
    for tool in mcp_tools_list:
        try:
            # Получаем args_schema и применяем transform_schema для гарантии type: "object"
            args_schema = tool.args_schema if hasattr(tool, 'args_schema') and isinstance(tool.args_schema, dict) else {}
            
            # КРИТИЧЕСКИ ВАЖНО: Применяем transform_schema для исправления type: null
            # Это гарантирует, что схема всегда имеет type: "object" для OpenAI API
            if args_schema:
                args_schema = transform_schema(args_schema)
            else:
                # Если схема пустая, создаем базовую схему объекта
                args_schema = {"type": "object", "properties": {}}
            
            # Дополнительная проверка: убеждаемся, что type: "object"
            if args_schema.get("type") != "object":
                logger.warning(f"[MCP] Исправляю type для инструмента {tool.name}: {args_schema.get('type')} -> object")
                args_schema["type"] = "object"
                if "properties" not in args_schema:
                    args_schema["properties"] = {}
            
            # Преобразуем инструмент в формат для state
            tool_dict = {
                "name": tool.name,
                "description": tool.description if hasattr(tool, 'description') else "",
                "inputSchema": args_schema
            }
            result.append(tool_dict)
        except Exception as e:
            logger.error(f"[MCP] Ошибка при преобразовании MCP инструмента {tool.name}: {e}")
            import traceback
            logger.error(f"[MCP] Traceback: {traceback.format_exc()}")
            continue
    logger.info(f"[MCP] Возвращено {len(result)} MCP инструментов через /mcp_tools")
    return result

@app.get("/mcp_servers_info")
async def get_mcp_servers_info():
    """Возвращает информацию о MCP серверах и их инструментах"""
    servers_info = config.get("mcp_servers_info", [])
    
    # Информация уже содержит инструменты для каждого сервера
    # Просто возвращаем её
    logger.info(f"[MCP] Возвращено {len(servers_info)} MCP серверов через /mcp_servers_info")
    return servers_info


@app.post("/mcp_reload")
async def mcp_reload():
    """Hot-reload MCP конфигурации/инструментов (используется админкой)."""
    result = await reload_mcp_from_db()
    return {"ok": True, **result}

@app.post("/{tool_name}")
async def call_tool(tool_name: str, payload: dict = Body(...)):
    # Логируем попытку вызова инструмента
    logger.info(f"[TOOL_CALL] Попытка вызова инструмента: {tool_name}")
    logger.info(f"[TOOL_CALL] Инструмент в tool_map: {tool_name in tool_map}")
    logger.info(f"[TOOL_CALL] Инструмент в repl_tool_map: {tool_name in repl_tool_map}")
    if tool_name in tool_map:
        tool_obj = tool_map[tool_name]
        logger.info(f"[TOOL_CALL] Инструмент найден в tool_map, тип: {type(tool_obj)}, имя: {getattr(tool_obj, 'name', 'N/A')}")
        # Проверяем, является ли это MCP инструментом
        mcp_tools_list = config.get("mcp_tools", [])
        is_mcp = any(tool.name == tool_name for tool in mcp_tools_list)
        logger.info(f"[TOOL_CALL] Является ли MCP инструментом: {is_mcp}")
    elif tool_name in repl_tool_map:
        logger.info(f"[TOOL_CALL] Инструмент найден в repl_tool_map")
    
    if tool_name in tool_map or tool_name in repl_tool_map:
        if tool_name in AGENT_MAP:
            return JSONResponse(
                status_code=500,
                content=f"Ты пытался вызвать '{tool_name}'. "
                f"Нельзя вызывать '{tool_name}' из кода! Вызывай их через function_call",
            )
        try:
            if tool_name in repl_tool_map:
                kwargs = payload.get("kwargs")
                return JSONResponse({"data": await repl_tool_map[tool_name](**kwargs)})
            tool = tool_map[tool_name]
            kwargs = payload.get("kwargs")
            thread_id = payload.get("thread_id")
            checkpoint_id = payload.get("checkpoint_id")
            
            # Всегда пытаемся получить state из thread (как в оригинале, но с обработкой ошибок)
            try:
                if thread_id:
                    state = (
                        await langgraph_client.threads.get_state(
                            thread_id=thread_id, checkpoint_id=checkpoint_id
                        )
                    )["values"]
                else:
                    # Если thread_id отсутствует, используем пустой state
                    state = {}
            except Exception as e:
                # Если поток не существует (404) или другая ошибка, используем пустое состояние
                error_str = str(e)
                if "404" in error_str or "Not Found" in error_str:
                    state = {}
                else:
                    # Для других ошибок также используем пустой state, чтобы не ломать работу
                    state = {}
            
            # Генерируем правильный tool call ID для Mistral API (9 символов, a-z, A-Z, 0-9)
            # Используем временный ID для инъекции аргументов (это не отправляется в API)
            temp_tool_call_id = ''.join(random.choices(string.ascii_letters + string.digits, k=9))
            
            # Используем прямой метод inject_tool_args, если доступен (как в оригинале)
            # Это автоматически добавляет state для параметров с InjectedState
            if hasattr(config["tool_node"], "inject_tool_args"):
                injected_args = config["tool_node"].inject_tool_args(
                    {"name": tool.name, "args": kwargs, "id": temp_tool_call_id}, state, None
                )["args"]
            else:
                # Fallback на compat версию, если прямой метод недоступен
                injection_payload = inject_tool_args_compat(
                    config["tool_node"],
                    {"name": tool.name, "args": kwargs, "id": temp_tool_call_id},
                    state,
                    None,
                )
                injected_args = injection_payload["args"]
            
            # Проверяем, требует ли инструмент state (InjectedState)
            # Это важно для инструментов типа personalize, которые требуют state для работы
            import inspect
            from typing import get_origin, get_args, Annotated
            try:
                from langgraph.prebuilt import InjectedState
            except ImportError:
                InjectedState = None
            
            needs_state = False
            try:
                func_to_check = None
                # Для инструментов, определенных через @tool, func может быть None, используем coroutine
                if hasattr(tool, 'func') and tool.func is not None:
                    func_to_check = tool.func
                elif hasattr(tool, 'coroutine') and tool.coroutine is not None:
                    func_to_check = tool.coroutine
                elif hasattr(tool, '__wrapped__') and tool.__wrapped__ is not None:
                    func_to_check = tool.__wrapped__
                elif callable(tool):
                    func_to_check = tool
                
                if func_to_check:
                    sig = inspect.signature(func_to_check)
                    for param_name, param in sig.parameters.items():
                        if param_name == "state":
                            needs_state = True
                            annotation = param.annotation
                            if annotation is not inspect.Parameter.empty:
                                try:
                                    origin = get_origin(annotation)
                                    if origin is Annotated and InjectedState:
                                        args = get_args(annotation)
                                        if len(args) > 1 and InjectedState in args[1:]:
                                            logger.info(f"[TOOL_CALL] ✅ Найден InjectedState для параметра state в {tool_name}")
                                except (TypeError, AttributeError):
                                    pass
                            break
            except (ValueError, TypeError, AttributeError) as e:
                logger.debug(f"[TOOL_CALL] ⚠️ Ошибка при проверке сигнатуры для {tool_name}: {e}")
            
            # Если инструмент требует state, но state пустой или отсутствует, пытаемся получить его из thread
            if needs_state and (not state or state == {}):
                logger.warning(f"[TOOL_CALL] ⚠️ Инструмент {tool_name} требует state, но state пустой, пытаемся получить из thread")
                if thread_id:
                    try:
                        state = (
                            await langgraph_client.threads.get_state(
                                thread_id=thread_id, checkpoint_id=checkpoint_id
                            )
                        )["values"]
                        logger.info(f"[TOOL_CALL] ✅ State получен из thread для {tool_name}")
                    except Exception as e:
                        logger.error(f"[TOOL_CALL] ❌ Не удалось получить state из thread для {tool_name}: {e}")
                        # Если не удалось получить state, но инструмент его требует, возвращаем ошибку
                        return JSONResponse(
                            status_code=500,
                            content="Ошибка: не удалось получить состояние агента. Предпочтение не сохранено.",
                        )
                else:
                    logger.error(f"[TOOL_CALL] ❌ Инструмент {tool_name} требует state, но thread_id отсутствует")
                    return JSONResponse(
                        status_code=500,
                        content="Ошибка: не удалось получить состояние агента. Предпочтение не сохранено.",
                    )
            
            # Гарантируем наличие state для инструментов, которые его требуют
            if needs_state:
                if "state" not in injected_args or injected_args.get("state") is None:
                    logger.warning(f"[TOOL_CALL] ⚠️ State не был инжектирован для {tool_name}, добавляем явно")
                    injected_args["state"] = state
                else:
                    logger.info(f"[TOOL_CALL] ✅ State уже присутствует для {tool_name}")
            
            # НОРМАЛИЗАЦИЯ ПАРАМЕТРОВ ДЛЯ АГЕНТОВ
            # Многие модели ошибочно передают query, action, task_type вместо правильных параметров
            # Преобразуем их автоматически для лучшей совместимости
            if tool_name and tool_name.endswith("_agent"):
                # Специальная обработка для агентов с разными параметрами
                if tool_name == "coder_agent":
                    # coder_agent использует task вместо user_request
                    if "task" not in injected_args or not injected_args.get("task"):
                        alternative_params = ["query", "action", "user_request", "request", "message", "text"]
                        task_value = None
                        found_param = None
                        
                        for alt_param in alternative_params:
                            if alt_param in injected_args and injected_args[alt_param]:
                                task_value = injected_args[alt_param]
                                found_param = alt_param
                                logger.info(f"[TOOL_CALL] 🔧 Нормализация: для {tool_name} найден параметр '{alt_param}' вместо task, преобразуем")
                                break
                        
                        if task_value:
                            injected_args["task"] = task_value
                            if found_param and found_param != "state":
                                del injected_args[found_param]
                            logger.info(f"[TOOL_CALL] ✅ Нормализация: параметр '{found_param}' преобразован в task для {tool_name}")
                elif tool_name == "researcher_agent":
                    # researcher_agent использует question вместо user_request
                    if "question" not in injected_args or not injected_args.get("question"):
                        alternative_params = ["query", "action", "user_request", "request", "message", "text"]
                        question_value = None
                        found_param = None
                        
                        for alt_param in alternative_params:
                            if alt_param in injected_args and injected_args[alt_param]:
                                question_value = injected_args[alt_param]
                                found_param = alt_param
                                logger.info(f"[TOOL_CALL] 🔧 Нормализация: для {tool_name} найден параметр '{alt_param}' вместо question, преобразуем")
                                break
                        
                        if question_value:
                            injected_args["question"] = question_value
                            if found_param and found_param != "state":
                                del injected_args[found_param]
                            logger.info(f"[TOOL_CALL] ✅ Нормализация: параметр '{found_param}' преобразован в question для {tool_name}")
                else:
                    # Для остальных агентов используется user_request
                    if "user_request" not in injected_args or not injected_args.get("user_request"):
                        # Пытаемся найти запрос в других параметрах
                        alternative_params = ["query", "action", "task", "request", "message", "text"]
                        user_request_value = None
                        found_param = None
                        
                        for alt_param in alternative_params:
                            if alt_param in injected_args and injected_args[alt_param]:
                                user_request_value = injected_args[alt_param]
                                found_param = alt_param
                                logger.info(f"[TOOL_CALL] 🔧 Нормализация: для {tool_name} найден параметр '{alt_param}' вместо user_request, преобразуем")
                                break
                        
                        if user_request_value:
                            # Преобразуем найденный параметр в user_request
                            injected_args["user_request"] = user_request_value
                            # Удаляем старый параметр (кроме state, который нужен)
                            if found_param and found_param != "state":
                                del injected_args[found_param]
                            logger.info(f"[TOOL_CALL] ✅ Нормализация: параметр '{found_param}' преобразован в user_request для {tool_name}")
            
            # Для python добавляем code и гарантируем наличие state и config
            # (на случай, если inject_tool_args не добавил их автоматически)
            if tool.name == "python":
                injected_args["code"] = kwargs.get("code")
                # Гарантируем, что state добавлен (для валидации)
                if "state" not in injected_args:
                    injected_args["state"] = state
                # config будет передан при вызове ainvoke, но для валидации нужен заглушка
                if "config" not in injected_args:
                    from langchain_core.runnables import RunnableConfig
                    injected_args["config"] = RunnableConfig()
            
            try:
                tool._to_args_and_kwargs(injected_args, None)
            except ValidationError as e:
                content = _handle_tool_error(e, flag=True)
                
                # Улучшенная обработка ошибок валидации для всех агентов
                if tool_name == "email_agent":
                    # Специальная обработка для email_agent
                    error_msg = (
                        f"Ошибка валидации: {content}\n\n"
                        f"⚠️ ВАЖНО: Для email_agent параметр называется user_request (НЕ query, НЕ task_type, НЕ action)!\n\n"
                        f"ПРАВИЛЬНЫЙ ФОРМАТ:\n"
                        f'email_agent(user_request="покажи последние письма из ящика alexis")\n'
                        f'email_agent(user_request="прочитать письма", email_account="alexis@example.com")\n\n'
                        f"Исправь вызов, используя параметр user_request с запросом пользователя."
                    )
                elif tool_name == "coder_agent":
                    # Специальная обработка для coder_agent
                    error_msg = (
                        f"Ошибка валидации: {content}\n\n"
                        f"⚠️ ВАЖНО: Для coder_agent параметр называется task (НЕ query, НЕ user_request, НЕ action)!\n\n"
                        f"ПРАВИЛЬНЫЙ ФОРМАТ:\n"
                        f'coder_agent(task="создать веб-приложение на Python с Flask")\n'
                        f'coder_agent(task="разработать REST API", programming_language="Python")\n\n'
                        f"Исправь вызов, используя параметр task с описанием проекта."
                    )
                elif tool_name == "researcher_agent":
                    # Специальная обработка для researcher_agent
                    error_msg = (
                        f"Ошибка валидации: {content}\n\n"
                        f"⚠️ ВАЖНО: Для researcher_agent параметр называется question (НЕ query, НЕ user_request, НЕ action)!\n\n"
                        f"ПРАВИЛЬНЫЙ ФОРМАТ:\n"
                        f'researcher_agent(question="исследуй тему искусственного интеллекта")\n'
                        f'researcher_agent(question="создай отчет о современных технологиях блокчейн")\n\n'
                        f"Исправь вызов, используя параметр question с вопросом/запросом."
                    )
                elif tool_name and tool_name.endswith("_agent"):
                    # Для остальных агентов используется user_request
                    error_msg = (
                        f"Ошибка валидации: {content}\n\n"
                        f"⚠️ ВАЖНО: Для агентов (например, {tool_name}) параметр называется user_request!\n\n"
                        f"ПРАВИЛЬНЫЙ ФОРМАТ:\n"
                        f'{tool_name}(user_request="запрос пользователя")\n\n'
                        f"Исправь вызов, используя параметр user_request."
                    )
                else:
                    tool_schema = convert_to_gigachat_tool(tool)["function"]
                    error_msg = f"Ошибка в заполнении функции!\n{content}\nЗаполни параметры функции по следующей схеме: {tool_schema}"
                
                return JSONResponse(
                    status_code=500,
                    content=error_msg,
                )
            # Создаем graph_config только если thread_id указан
            graph_config = None
            if thread_id:
                graph_config = {
                    "configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}
                }
            
            # Вызываем инструмент с config только если он указан
            logger.info(f"[TOOL_CALL] Вызов инструмента {tool_name} с args: {list(injected_args.keys())}")
            try:
                if graph_config:
                    data = await tool_map[tool_name].ainvoke(injected_args, config=graph_config)
                else:
                    data = await tool_map[tool_name].ainvoke(injected_args)
                logger.info(f"[TOOL_CALL] Инструмент {tool_name} выполнен успешно, тип результата: {type(data)}")
                return {"data": data}
            except Exception as invoke_error:
                logger.error(f"[TOOL_CALL] Ошибка при вызове инструмента {tool_name}: {type(invoke_error).__name__}: {str(invoke_error)}")
                import traceback
                logger.error(f"[TOOL_CALL] Traceback: {traceback.format_exc()}")
                raise  # Пробрасываем ошибку дальше для обработки в общем except
        except Exception as e:
            logger.error(f"[TOOL_CALL] Общая ошибка при обработке инструмента {tool_name}: {type(e).__name__}: {str(e)}")
            traceback.print_exc()
            error_content = _handle_tool_error(e, flag=True)
            logger.error(f"[TOOL_CALL] Содержимое ошибки: {error_content[:500]}")
            return JSONResponse(
                status_code=500, content=error_content
            )
    else:
        return JSONResponse(
            status_code=404, content=f"Tool with name {tool_name} not found!"
        )
