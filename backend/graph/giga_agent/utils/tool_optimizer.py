"""
Оптимизатор инструментов для уменьшения размера контекста

Сокращает описания инструментов и их параметров, сохраняя только необходимую информацию
для вызова инструментов, что позволяет значительно уменьшить размер контекста.
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Максимальная длина описания инструмента (в символах)
MAX_TOOL_DESCRIPTION_LENGTH = 150

# Максимальная длина описания параметра (в символах)
MAX_PARAM_DESCRIPTION_LENGTH = 80


def truncate_description(description: str, max_length: int) -> str:
    """Обрезает описание до максимальной длины"""
    if not description:
        return ""
    if len(description) <= max_length:
        return description
    # Обрезаем до последнего пробела перед max_length, чтобы не обрывать слово
    truncated = description[:max_length]
    last_space = truncated.rfind(' ')
    if last_space > max_length * 0.7:  # Если пробел не слишком далеко от конца
        return truncated[:last_space] + "..."
    return truncated + "..."


def optimize_tool_description(tool: Dict[str, Any]) -> Dict[str, Any]:
    """
    Оптимизирует описание инструмента, сокращая его до минимума.
    
    Сохраняет:
    - Название инструмента
    - Краткое описание (до MAX_TOOL_DESCRIPTION_LENGTH символов)
    - Параметры с типами и краткими описаниями
    
    Удаляет:
    - Длинные описания
    - Примеры использования
    - Дополнительные метаданные
    """
    optimized = {
        "name": tool.get("name", ""),
        "description": "",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }
    
    # Оптимизируем описание инструмента
    original_description = tool.get("description", "")
    if original_description:
        # Берем первое предложение или первые MAX_TOOL_DESCRIPTION_LENGTH символов
        # Удаляем примеры и длинные пояснения
        description = original_description.split('\n')[0]  # Первая строка
        description = description.split('.')[0]  # Первое предложение
        description = description.split('Примеры:')[0]  # До примеров
        description = description.split('Examples:')[0]  # До примеров (англ)
        description = description.strip()
        
        # Обрезаем до максимальной длины
        optimized["description"] = truncate_description(description, MAX_TOOL_DESCRIPTION_LENGTH)
    else:
        optimized["description"] = "Инструмент без описания"
    
    # Оптимизируем параметры
    parameters = tool.get("parameters", {})
    if isinstance(parameters, dict):
        optimized_params = {
            "type": "object",
            "properties": {},
            "required": parameters.get("required", [])
        }
        
        properties = parameters.get("properties", {})
        if isinstance(properties, dict):
            for param_name, param_schema in properties.items():
                if not isinstance(param_schema, dict):
                    continue
                
                optimized_param = {
                    "type": param_schema.get("type", "string")
                }
                
                # Оптимизируем описание параметра
                param_description = param_schema.get("description", "")
                if param_description:
                    # Берем первое предложение
                    desc = param_description.split('.')[0]
                    desc = desc.split('\n')[0]
                    desc = desc.strip()
                    optimized_param["description"] = truncate_description(desc, MAX_PARAM_DESCRIPTION_LENGTH)
                
                # Сохраняем только критически важные поля
                if "enum" in param_schema:
                    optimized_param["enum"] = param_schema["enum"]
                if "default" in param_schema:
                    optimized_param["default"] = param_schema["default"]
                
                optimized_params["properties"][param_name] = optimized_param
        
        optimized["parameters"] = optimized_params
    
    return optimized


def optimize_tools_list(tools: List[Dict[str, Any]], enable_optimization: bool = True) -> List[Dict[str, Any]]:
    """
    Оптимизирует список инструментов для уменьшения размера контекста.
    
    Args:
        tools: Список инструментов для оптимизации
        enable_optimization: Включить ли оптимизацию (можно отключить через переменную окружения)
    
    Returns:
        Оптимизированный список инструментов
    """
    import os
    
    # Проверяем переменную окружения для отключения оптимизации
    if os.environ.get("TOOL_OPTIMIZATION_ENABLED", "1") != "1":
        enable_optimization = False
    
    if not enable_optimization:
        return tools
    
    optimized_tools = []
    original_total_size = 0
    optimized_total_size = 0
    
    for tool in tools:
        if not isinstance(tool, dict):
            optimized_tools.append(tool)
            continue
        
        # Подсчитываем размер оригинального инструмента
        import json
        original_size = len(json.dumps(tool, ensure_ascii=False, default=str))
        original_total_size += original_size
        
        # Оптимизируем
        optimized_tool = optimize_tool_description(tool)
        optimized_tools.append(optimized_tool)
        
        # Подсчитываем размер оптимизированного инструмента
        optimized_size = len(json.dumps(optimized_tool, ensure_ascii=False, default=str))
        optimized_total_size += optimized_size
    
    if original_total_size > 0:
        reduction_percent = (1 - optimized_total_size / original_total_size) * 100
        logger.info(
            f"[TOOL_OPTIMIZATION] Оптимизировано {len(tools)} инструментов: "
            f"{original_total_size} -> {optimized_total_size} символов "
            f"({reduction_percent:.1f}% сокращение)"
        )
    
    return optimized_tools
