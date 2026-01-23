import functools
import json
import os

import aiohttp
import requests
from pydantic import BaseModel, Field


class ToolExecuteException(Exception):
    pass


class ToolNotFoundException(Exception):
    pass


class ToolClient(BaseModel):
    base_url: str = Field(
        default_factory=lambda: os.getenv("TOOL_CLIENT_API", "http://127.0.0.1:8811")
    )
    thread_id: str = ""
    checkpoint_id: str = ""

    def set_state_data(self, thread_id: str, checkpoint_id: str):
        self.thread_id = thread_id
        self.checkpoint_id = checkpoint_id

    async def aexecute(self, tool_name, kwargs):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/{tool_name}",
                json={
                    "kwargs": kwargs,
                    "thread_id": self.thread_id,
                    "checkpoint_id": self.checkpoint_id,
                },
                timeout=600.0,
            ) as res:
                if res.status == 200:
                    data = (await res.json())["data"]
                    try:
                        data = json.loads(data)
                    except Exception:
                        pass
                    return data
                elif res.status == 404:
                    raise ToolNotFoundException((await res.json()))
                else:
                    raise ToolExecuteException((await res.json()))

    def execute(self, tool_name, kwargs):
        url = f"{self.base_url}/{tool_name}"
        try:
            response = requests.post(
                url,
                json={
                    "kwargs": kwargs,
                    "thread_id": self.thread_id,
                    "checkpoint_id": self.checkpoint_id,
                },
                timeout=600.0,
            )
        except requests.RequestException as e:
            # Ошибка сети или таймаут
            raise ToolExecuteException(str(e))

        if response.status_code == 200:
            data = response.json()["data"]
            try:
                data = json.loads(data)
            except Exception:
                pass
            return data
        elif response.status_code == 404:
            # Инструмент не найден
            raise ToolNotFoundException(response.json())
        else:
            # Любая другая ошибка выполнения
            raise ToolExecuteException(response.json())

    async def get_tools(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/tools",
                timeout=600.0,
            ) as res:
                if res.status != 200:
                    # Если статус не 200, логируем и возвращаем пустой список
                    error_text = await res.text()
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"[TOOL_CLIENT] Ошибка при получении инструментов: статус {res.status}, ответ: {error_text}")
                    return []
                
                data = await res.json()
                # Новый формат (при ошибках): {"tools": [...], "errors": [...]}
                # Старый формат (без ошибок): [...]
                if isinstance(data, dict) and "tools" in data:
                    # Если есть ошибки, логируем их, но все равно возвращаем инструменты
                    if "errors" in data and data["errors"]:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"[TOOL_CLIENT] При получении инструментов были ошибки: {data['errors']}")
                    return data["tools"]
                # Если это список (старый формат или новый без ошибок), возвращаем как есть
                elif isinstance(data, list):
                    return data
                else:
                    # Неожиданный формат, логируем и возвращаем пустой список
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"[TOOL_CLIENT] Неожиданный формат ответа от /tools: {type(data)}")
                    return []
    
    async def get_mcp_tools(self):
        """Получает только MCP инструменты из tool_server"""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/mcp_tools",
                timeout=600.0,
            ) as res:
                if res.status == 200:
                    return await res.json()
                else:
                    # Если эндпоинт не найден, возвращаем пустой список
                    return []

    def call_tool(self, func):
        """
        Декоратор для методов ToolClient:
        - берёт имя функции как название инструмента,
        - собирает все именованные аргументы в dict,
        - вызывает self.execute(tool_name, kwargs) и возвращает результат.
        """

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if args:
                raise TypeError(
                    f"Tool method '{func.__name__}' accepts named keyword arguments only"
                )
            # имя инструмента — само имя метода
            tool_name = func.__name__
            return self.execute(tool_name, kwargs)

        return wrapper


if __name__ == "__main__":
    from langgraph_sdk import get_sync_client

    client = get_sync_client(url="http://localhost:8502/graph/")
    print(
        client.threads.get_state(
            thread_id="51ebef72-5a32-47ad-96c3-88d89c3cfb6d",
            checkpoint_id="1f0a4fd7-8074-6983-8001-70b29856dfc5",
        )
    )
    # tool_client = ToolClient(base_url="http://127.0.0.1:8811")
    #
    # @tool_client.call_tool
    # def predict_sentiments(**kwargs):
    #     pass
    #
    # async def main():
    #     # client = JupyterClient(
    #     #     base_url=os.getenv("JUPYTER_CLIENT_API", "http://127.0.0.1:9090")
    #     # )
    #     # tool_client.set_state({"kernel_id": (await client.start_kernel())["id"]})
    #     print(predict_sentiments(texts=["крутой товар"]))
    #
    # asyncio.run(main())
