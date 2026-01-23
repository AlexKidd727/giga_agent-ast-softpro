"""
Узлы для PC Management Agent
"""

from .system import get_system_info, run_program, list_programs, get_process_list, kill_process
from .files import search_files, open_file, create_file, read_file, file_info, list_directory
from .windows import open_windows, close_window, get_window_info, minimize_window, maximize_window

__all__ = [
    # Системные операции
    "get_system_info", 
    "run_program", 
    "list_programs", 
    "get_process_list", 
    "kill_process",
    # Файловые операции
    "search_files", 
    "open_file", 
    "create_file", 
    "read_file", 
    "file_info", 
    "list_directory",
    # Операции с окнами
    "open_windows", 
    "close_window", 
    "get_window_info", 
    "minimize_window", 
    "maximize_window"
]
