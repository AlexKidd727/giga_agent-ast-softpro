import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Body
from langchain_gigachat.utils.function_calling import convert_to_gigachat_tool
from langgraph_sdk.client import get_client
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt.tool_node import _handle_tool_error, ToolNode
from pydantic_core import ValidationError
from fastapi.responses import JSONResponse

from giga_agent.tool_server.utils import transform_schema, transform_tool
from giga_agent.utils.env import load_project_env
from giga_agent.utils.langgraph import inject_tool_args_compat
from giga_agent.config import MCP_CONFIG, TOOLS, REPL_TOOLS, AGENT_MAP

tool_map = {}
repl_tool_map = {}
config = {}

load_project_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = MultiServerMCPClient(MCP_CONFIG)
    # mcp_tools = [transform_tool(tool) for tool in await client.get_tools()]
    mcp_tools = await client.get_tools()
    for mcp_tool in mcp_tools:
        mcp_tool.name = mcp_tool.name.replace("-", "_")
        if isinstance(mcp_tool.args_schema, dict):
            mcp_tool.args_schema = transform_schema(mcp_tool.args_schema)
    tools = TOOLS + mcp_tools
    config["tool_node"] = ToolNode(tools=tools)
    for tool in tools:
        tool_map[tool.name] = tool
    for tool in REPL_TOOLS:
        repl_tool_map[tool.__name__] = tool
    yield
    repl_tool_map.clear()
    tool_map.clear()
    config.clear()


app = FastAPI(lifespan=lifespan)
langgraph_client = get_client(url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024"))


@app.post("/{tool_name}")
async def call_tool(tool_name: str, payload: dict = Body(...)):
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
            
            # Используем прямой метод inject_tool_args, если доступен (как в оригинале)
            # Это автоматически добавляет state для параметров с InjectedState
            if hasattr(config["tool_node"], "inject_tool_args"):
                injected_args = config["tool_node"].inject_tool_args(
                    {"name": tool.name, "args": kwargs, "id": "123"}, state, None
                )["args"]
            else:
                # Fallback на compat версию, если прямой метод недоступен
                injection_payload = inject_tool_args_compat(
                    config["tool_node"],
                    {"name": tool.name, "args": kwargs, "id": "123"},
                    state,
                    None,
                )
                injected_args = injection_payload["args"]
            
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
                tool_schema = convert_to_gigachat_tool(tool)["function"]
                return JSONResponse(
                    status_code=500,
                    content=f"Ошибка в заполнении функции!\n{content}\nЗаполни параметры функции по следующей схеме: {tool_schema}",
                )
            # Создаем graph_config только если thread_id указан
            graph_config = None
            if thread_id:
                graph_config = {
                    "configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}
                }
            
            # Вызываем инструмент с config только если он указан
            if graph_config:
                data = await tool_map[tool_name].ainvoke(injected_args, config=graph_config)
            else:
                data = await tool_map[tool_name].ainvoke(injected_args)
            return {"data": data}
        except Exception as e:
            traceback.print_exc()
            return JSONResponse(
                status_code=500, content=_handle_tool_error(e, flag=True)
            )
    else:
        return JSONResponse(
            status_code=404, content=f"Tool with name {tool_name} not found!"
        )


@app.get("/tools")
async def get_tools():
    tools = []
    for tool in tool_map.values():
        tools.append(convert_to_gigachat_tool(tool)["function"])
    return tools
