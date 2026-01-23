"""
Утилиты для работы с путями к файлам и папкам
"""

import os
from pathlib import Path
import sys


def get_project_root() -> Path:
    """Получает корень проекта"""
    if hasattr(sys, '_MEIPASS'):
        # Если запущено из PyInstaller
        return Path(sys.executable).parent
    else:
        # Обычный запуск - корень проекта
        # Путь: backend/graph/giga_agent/agents/lawyer_agent/utils/paths.py
        # Нужно подняться на 6 уровней вверх до корня проекта
        return Path(__file__).parent.parent.parent.parent.parent.parent.parent


def get_law_folder() -> Path:
    """
    Получает путь к папке law для текстовых файлов актов
    
    Returns:
        Path к папке law
    """
    project_root = get_project_root()
    law_folder = project_root / 'law'
    law_folder.mkdir(exist_ok=True)
    return law_folder


def get_vector_store_folder() -> Path:
    """
    Получает путь к папке vector_store для векторной БД
    
    Returns:
        Path к папке vector_store
    """
    project_root = get_project_root()
    vector_store_folder = project_root / 'vector_store'
    vector_store_folder.mkdir(exist_ok=True)
    return vector_store_folder


def get_codex_db_path() -> Path:
    """
    Получает путь к файлу БД кодексов в vector_store
    
    Returns:
        Path к файлу codexes.db
    """
    vector_store_folder = get_vector_store_folder()
    return vector_store_folder / 'codexes.db'

