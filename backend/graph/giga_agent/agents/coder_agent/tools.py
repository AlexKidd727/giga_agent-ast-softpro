"""
Инструменты для агента кодера
"""

from langchain_core.tools import tool


@tool(parse_docstring=True)
async def analyze_project(additional_info: str = ""):
    """
    Анализирует требования к проекту и создает структуру проекта
    
    Args:
        additional_info: Дополнительная информация для анализа
    """
    pass


@tool(parse_docstring=True)
async def generate_project(additional_info: str = ""):
    """
    Генерирует файлы проекта на основе созданной структуры
    
    Args:
        additional_info: Дополнительная информация для генерации
    """
    pass


@tool(parse_docstring=True)
async def done(message: str = "Проект готов"):
    """
    Завершает работу над проектом и создает архив
    
    Args:
        message: Сообщение о завершении
    """
    pass

