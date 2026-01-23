"""
Клиент для работы с MCP сервером сайта
"""

import logging
from typing import Optional, Dict, Any, List
import httpx
import json

logger = logging.getLogger(__name__)


class MCPWebsiteClient:
    """Клиент для работы с сайтом через MCP сервер"""
    
    def __init__(self, mcp_server_name: str = "website_mcp", mcp_tools: Optional[List[Dict]] = None):
        """
        Инициализация клиента MCP для работы с сайтом
        
        Args:
            mcp_server_name: Имя MCP сервера для сайта
            mcp_tools: Список доступных MCP инструментов (из state["mcp_tools"])
        """
        self.mcp_server_name = mcp_server_name
        self.mcp_tools = mcp_tools or []
        self._available_tools = {}
        
        # Инициализируем доступные инструменты из mcp_tools
        for tool in self.mcp_tools:
            tool_name = tool.get("name", "")
            if "website" in tool_name.lower() or "site" in tool_name.lower() or "cms" in tool_name.lower():
                self._available_tools[tool_name] = tool
    
    def get_available_tools(self) -> List[str]:
        """Возвращает список доступных инструментов MCP для работы с сайтом"""
        return list(self._available_tools.keys())
    
    async def call_mcp_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        mcp_tools: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Вызывает MCP инструмент для работы с сайтом
        
        Args:
            tool_name: Имя инструмента MCP
            args: Аргументы для инструмента
            mcp_tools: Список доступных MCP инструментов (если не указан, используется self.mcp_tools)
        
        Returns:
            Результат выполнения инструмента
        """
        try:
            # Обновляем список инструментов, если передан
            if mcp_tools:
                self.mcp_tools = mcp_tools
                self._available_tools = {}
                for tool in mcp_tools:
                    tool_name_check = tool.get("name", "")
                    if "website" in tool_name_check.lower() or "site" in tool_name_check.lower() or "cms" in tool_name_check.lower():
                        self._available_tools[tool_name_check] = tool
            
            # Проверяем доступность инструмента
            if tool_name not in self._available_tools:
                available = list(self._available_tools.keys())
                return {
                    "success": False,
                    "error": f"Инструмент '{tool_name}' не найден. Доступные инструменты: {available}"
                }
            
            tool_info = self._available_tools[tool_name]
            
            # MCP инструменты вызываются через основной граф агента
            # Здесь мы только подготавливаем информацию для вызова
            # Фактический вызов происходит через state["mcp_tools"] в tool_graph.py
            
            return {
                "success": True,
                "tool_name": tool_name,
                "tool_info": tool_info,
                "args": args,
                "message": f"Инструмент '{tool_name}' подготовлен к вызову через MCP"
            }
        except Exception as e:
            logger.error(f"Ошибка вызова MCP инструмента '{tool_name}': {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def publish_via_mcp(
        self,
        title: str,
        content: str,
        mcp_tools: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Публикует пост на сайте через MCP инструмент
        
        Args:
            title: Заголовок поста
            content: Содержимое поста
            mcp_tools: Список доступных MCP инструментов
        """
        # Ищем подходящий инструмент для публикации
        publish_tools = [
            "publish_post",
            "create_post",
            "website_publish",
            "cms_publish",
            "add_post"
        ]
        
        available_tools = self.get_available_tools() if not mcp_tools else [
            t.get("name") for t in mcp_tools 
            if "website" in t.get("name", "").lower() or "site" in t.get("name", "").lower() or "cms" in t.get("name", "").lower()
        ]
        
        # Ищем подходящий инструмент
        tool_name = None
        for tool in available_tools:
            if any(pt in tool.lower() for pt in publish_tools):
                tool_name = tool
                break
        
        if not tool_name:
            # Используем первый доступный инструмент для сайта
            if available_tools:
                tool_name = available_tools[0]
            else:
                return {
                    "success": False,
                    "error": "Не найдено доступных MCP инструментов для публикации на сайте"
                }
        
        args = {
            "title": title,
            "content": content
        }
        
        return await self.call_mcp_tool(tool_name, args, mcp_tools)
    
    async def update_via_mcp(
        self,
        post_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        mcp_tools: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Обновляет пост на сайте через MCP инструмент
        
        Args:
            post_id: ID поста для обновления
            title: Новый заголовок (опционально)
            content: Новое содержимое (опционально)
            mcp_tools: Список доступных MCP инструментов
        """
        # Ищем подходящий инструмент для обновления
        update_tools = [
            "update_post",
            "edit_post",
            "website_update",
            "cms_update",
            "modify_post"
        ]
        
        available_tools = self.get_available_tools() if not mcp_tools else [
            t.get("name") for t in mcp_tools 
            if "website" in t.get("name", "").lower() or "site" in t.get("name", "").lower() or "cms" in t.get("name", "").lower()
        ]
        
        # Ищем подходящий инструмент
        tool_name = None
        for tool in available_tools:
            if any(ut in tool.lower() for ut in update_tools):
                tool_name = tool
                break
        
        if not tool_name:
            return {
                "success": False,
                "error": "Не найдено доступных MCP инструментов для обновления поста на сайте"
            }
        
        args = {
            "post_id": post_id
        }
        
        if title is not None:
            args["title"] = title
        if content is not None:
            args["content"] = content
        
        return await self.call_mcp_tool(tool_name, args, mcp_tools)

