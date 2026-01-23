"""
Инструменты для работы с реестром инструментов.
Позволяют получить краткий список доступных инструментов и детальную информацию о конкретных инструментах.
"""

import json
from typing import Annotated, Optional
from langchain_core.tools import tool
from pydantic import Field

# НЕ импортируем SERVICE_TOOLS, AGENTS, TOOLS здесь, чтобы избежать циклического импорта
# Вместо этого используем ленивую загрузку внутри функций


# Категории инструментов для группировки
TOOL_CATEGORIES = {
    "file_operations": {
        "name": "Работа с файлами",
        "description": "Чтение, запись, анализ файлов и архивов",
        "tools": ["read_file", "read_document", "list_archive_contents", "extract_archive", 
                 "send_file_to_repl", "send_file_to_llm", "send_archive_files_to_repl", "code_review"]
    },
    "search_research": {
        "name": "Поиск и исследование",
        "description": "Поиск информации в интернете и базах знаний",
        "tools": ["search", "get_urls", "get_documents", "researcher_agent"]
    },
    "code_development": {
        "name": "Разработка кода",
        "description": "Создание, анализ и ревью кода",
        "tools": ["python", "shell", "coder_agent", "code_review"]
    },
    "agents": {
        "name": "Специализированные агенты",
        "description": "Агенты для решения специфических задач",
        "tools": ["tinkoff_agent", "calendar_agent", "email_agent", "career_agent", 
                 "lawyer_agent", "pc_agent", "social_media_agent"]
    },
    "media": {
        "name": "Медиа и контент",
        "description": "Генерация изображений, презентаций, мемов и другого контента",
        "tools": ["gen_image", "ask_about_image", "generate_presentation", "create_landing", 
                 "create_meme", "podcast_generate"]
    },
    "integrations": {
        "name": "Интеграции",
        "description": "Интеграции с внешними сервисами",
        "tools": ["vk_get_posts", "vk_get_comments", "weather", "mysql_query", 
                 "get_workflow_runs", "list_pull_requests", "create_github_repository"]
    },
    "audio_video": {
        "name": "Аудио и видео",
        "description": "Работа с аудио и видео контентом",
        "tools": ["transcribe_audio", "transcribe_audio_from_url"]
    },
    "utilities": {
        "name": "Утилиты",
        "description": "Вспомогательные инструменты",
        "tools": ["personalize", "salute_say", "browser_task", "city_explore", "lean_canvas", 
                 "list_available_tools", "get_tool_details"]
    }
}


def get_tool_category(tool_name: str) -> str:
    """Определяет категорию инструмента по его имени"""
    for category, info in TOOL_CATEGORIES.items():
        if tool_name in info["tools"]:
            return category
    return "other"


def get_all_tools_registry() -> dict:
    """
    Создает реестр всех доступных инструментов с краткой информацией.
    Возвращает словарь с категориями и инструментами.
    
    Использует ленивую загрузку для избежания циклических импортов.
    """
    # Ленивый импорт для избежания циклических зависимостей
    from giga_agent.config import TOOLS
    
    registry = {
        "categories": {},
        "tools": {},
        "total_count": 0
    }
    
    # Собираем все инструменты из TOOLS (который объединяет SERVICE_TOOLS и AGENTS)
    all_tools = []
    
    # Используем TOOLS, который уже содержит все инструменты
    for tool_obj in TOOLS:
        if tool_obj:
            all_tools.append(tool_obj)
    
    # Группируем по категориям
    for tool_obj in all_tools:
        if not tool_obj:
            continue
            
        tool_name = getattr(tool_obj, 'name', None) or str(tool_obj)
        if not tool_name:
            continue
        
        category = get_tool_category(tool_name)
        
        # Получаем краткое описание
        description = ""
        if hasattr(tool_obj, 'description'):
            description = tool_obj.description
        elif hasattr(tool_obj, '__doc__') and tool_obj.__doc__:
            # Берем первую строку из docstring
            description = tool_obj.__doc__.split('\n')[0].strip()
        
        # Ограничиваем длину описания для краткого списка
        if len(description) > 100:
            description = description[:97] + "..."
        
        # Добавляем в категорию
        if category not in registry["categories"]:
            registry["categories"][category] = {
                "name": TOOL_CATEGORIES.get(category, {}).get("name", "Другое"),
                "description": TOOL_CATEGORIES.get(category, {}).get("description", ""),
                "tools": []
            }
        
        registry["categories"][category]["tools"].append(tool_name)
        
        # Сохраняем информацию об инструменте
        registry["tools"][tool_name] = {
            "name": tool_name,
            "category": category,
            "short_description": description,
            "tool_object": tool_obj  # Сохраняем ссылку на объект для получения деталей
        }
    
    registry["total_count"] = len(registry["tools"])
    return registry


# Глобальный реестр (кэшируется)
_tools_registry_cache = None


def get_tools_registry():
    """Получает кэшированный реестр инструментов"""
    global _tools_registry_cache
    if _tools_registry_cache is None:
        _tools_registry_cache = get_all_tools_registry()
    return _tools_registry_cache


@tool(parse_docstring=True)
async def list_available_tools(
    category: Annotated[
        Optional[str],
        Field(
            description="Фильтр по категории. Если не указан, возвращаются все инструменты. "
                       "Доступные категории: file_operations, search_research, code_development, "
                       "agents, media, integrations, audio_video, utilities",
            default=None
        )
    ] = None,
) -> str:
    """
    Возвращает краткий список всех доступных инструментов, сгруппированных по категориям.
    
    Это "дешевый" в токенах способ узнать, какие инструменты доступны в системе.
    Для получения детальной информации о конкретном инструменте используйте get_tool_details.
    
    Args:
        category: Опциональный фильтр по категории. Если указан, возвращаются только инструменты из этой категории.
    
    Returns:
        JSON строка с кратким списком инструментов:
        {
            "total_count": общее количество инструментов,
            "categories": {
                "category_name": {
                    "name": "Название категории",
                    "description": "Описание категории",
                    "tools": ["tool1", "tool2", ...]
                }
            },
            "tools": {
                "tool_name": {
                    "name": "название",
                    "category": "категория",
                    "short_description": "краткое описание"
                }
            }
        }
    
    Examples:
        - list_available_tools()  # Все инструменты
        - list_available_tools(category="file_operations")  # Только инструменты для работы с файлами
    """
    try:
        registry = get_tools_registry()
        
        # Если указана категория, фильтруем
        if category:
            if category not in registry["categories"]:
                return json.dumps({
                    "success": False,
                    "message": f"Категория '{category}' не найдена. Доступные категории: {', '.join(registry['categories'].keys())}"
                }, ensure_ascii=False)
            
            filtered_registry = {
                "total_count": len(registry["categories"][category]["tools"]),
                "categories": {
                    category: registry["categories"][category]
                },
                "tools": {
                    tool_name: registry["tools"][tool_name]
                    for tool_name in registry["categories"][category]["tools"]
                    if tool_name in registry["tools"]
                }
            }
            return json.dumps(filtered_registry, ensure_ascii=False, default=str)
        
        # Возвращаем все инструменты
        # Удаляем tool_object из вывода, чтобы не сериализовать объекты
        output_registry = {
            "total_count": registry["total_count"],
            "categories": registry["categories"],
            "tools": {
                tool_name: {
                    "name": info["name"],
                    "category": info["category"],
                    "short_description": info["short_description"]
                }
                for tool_name, info in registry["tools"].items()
            }
        }
        
        return json.dumps(output_registry, ensure_ascii=False, default=str)
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка при получении списка инструментов: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "message": f"Ошибка при получении списка инструментов: {str(e)}"
        }, ensure_ascii=False)


@tool(parse_docstring=True)
async def get_tool_details(
    tool_name: Annotated[
        str,
        Field(description="Название инструмента, для которого нужно получить детальную информацию")
    ],
) -> str:
    """
    Возвращает детальную информацию о конкретном инструменте, включая полное описание, параметры и примеры использования.
    
    Используйте этот инструмент после list_available_tools, когда нужно узнать подробности о конкретном инструменте.
    
    Args:
        tool_name: Название инструмента (например, "read_file", "search", "tinkoff_agent")
    
    Returns:
        JSON строка с детальной информацией об инструменте:
        {
            "success": true/false,
            "tool_name": "название",
            "category": "категория",
            "description": "полное описание",
            "parameters": {
                "param_name": {
                    "type": "тип",
                    "description": "описание",
                    "required": true/false
                }
            },
            "examples": ["пример1", "пример2"],
            "message": "описание результата"
        }
    
    Examples:
        - get_tool_details("read_file")
        - get_tool_details("search")
        - get_tool_details("tinkoff_agent")
    """
    try:
        registry = get_tools_registry()
        
        if tool_name not in registry["tools"]:
            # Пробуем найти похожие инструменты
            similar = [name for name in registry["tools"].keys() if tool_name.lower() in name.lower() or name.lower() in tool_name.lower()]
            message = f"Инструмент '{tool_name}' не найден."
            if similar:
                message += f" Возможно, вы имели в виду: {', '.join(similar[:5])}"
            else:
                message += f" Используйте list_available_tools() для просмотра всех доступных инструментов."
            
            return json.dumps({
                "success": False,
                "tool_name": tool_name,
                "message": message
            }, ensure_ascii=False)
        
        tool_info = registry["tools"][tool_name]
        tool_obj = tool_info.get("tool_object")
        
        if not tool_obj:
            # Если объект инструмента недоступен, возвращаем хотя бы краткую информацию
            return json.dumps({
                "success": True,
                "tool_name": tool_name,
                "category": tool_info.get("category", "unknown"),
                "description": tool_info.get("short_description", "Описание недоступно"),
                "parameters": {},
                "message": f"Информация об инструменте '{tool_name}' (детальные параметры недоступны)"
            }, ensure_ascii=False)
        
        # Получаем полное описание
        full_description = ""
        if hasattr(tool_obj, 'description'):
            full_description = tool_obj.description
        elif hasattr(tool_obj, '__doc__') and tool_obj.__doc__:
            full_description = tool_obj.__doc__.strip()
        
        # Получаем параметры
        parameters = {}
        if hasattr(tool_obj, 'args_schema') and tool_obj.args_schema:
            schema = tool_obj.args_schema
            if hasattr(schema, 'schema'):
                schema_dict = schema.schema()
                if 'properties' in schema_dict:
                    for param_name, param_info in schema_dict['properties'].items():
                        parameters[param_name] = {
                            "type": param_info.get("type", "unknown"),
                            "description": param_info.get("description", ""),
                            "required": param_name in schema_dict.get("required", [])
                        }
        
        # Формируем результат
        result = {
            "success": True,
            "tool_name": tool_name,
            "category": tool_info["category"],
            "description": full_description,
            "parameters": parameters,
            "message": f"Детальная информация об инструменте '{tool_name}'"
        }
        
        return json.dumps(result, ensure_ascii=False, default=str)
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка при получении деталей инструмента {tool_name}: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "tool_name": tool_name,
            "message": f"Ошибка при получении деталей инструмента: {str(e)}"
        }, ensure_ascii=False)
