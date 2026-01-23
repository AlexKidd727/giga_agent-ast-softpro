"""
Утилиты для работы с окнами Windows
Основано на коде из evi-run-main/jarvis/jarvis_ai/windows/windows_agent.py
"""

import os
import logging
from typing import List, Dict, Any, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None
    logger = logging.getLogger(__name__)
    logger.warning("psutil не установлен. Некоторые функции PC agent будут недоступны.")

from ..config import IS_WINDOWS, MAX_PROCESS_LIST

logger = logging.getLogger(__name__)

def _check_psutil():
    """Проверка доступности psutil"""
    if not PSUTIL_AVAILABLE:
        raise ImportError("psutil не установлен. Установите: pip install psutil")

# Импорты для Windows
if IS_WINDOWS:
    try:
        import win32gui
        import win32con
        import win32process
        WIN32_AVAILABLE = True
    except ImportError:
        WIN32_AVAILABLE = False
        logger.warning("Win32 модули недоступны. Функции работы с окнами ограничены.")
else:
    WIN32_AVAILABLE = False

def get_window_list() -> List[Dict[str, Any]]:
    """Получает список открытых окон"""
    if not IS_WINDOWS or not WIN32_AVAILABLE:
        return [{"error": "Функция доступна только для Windows с установленными win32 модулями"}]
    
    try:
        windows = []
        
        def enum_windows_callback(hwnd, windows_list):
            if win32gui.IsWindowVisible(hwnd):
                window_text = win32gui.GetWindowText(hwnd)
                if window_text:  # Только окна с заголовками
                    try:
                        # Получаем информацию о процессе
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        if not PSUTIL_AVAILABLE:
                            return True  # Пропускаем это окно, если psutil недоступен
                        process = psutil.Process(pid)
                        
                        # Получаем размеры и позицию окна
                        rect = win32gui.GetWindowRect(hwnd)
                        
                        window_info = {
                            "hwnd": hwnd,
                            "title": window_text,
                            "pid": pid,
                            "process_name": process.name(),
                            "rect": {
                                "left": rect[0],
                                "top": rect[1],
                                "right": rect[2],
                                "bottom": rect[3],
                                "width": rect[2] - rect[0],
                                "height": rect[3] - rect[1]
                            },
                            "is_minimized": win32gui.IsIconic(hwnd),
                            "is_maximized": win32gui.IsZoomed(hwnd)
                        }
                        windows_list.append(window_info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            return True
        
        win32gui.EnumWindows(enum_windows_callback, windows)
        
        # Ограничиваем количество результатов
        return windows[:MAX_PROCESS_LIST]
        
    except Exception as e:
        logger.error(f"Ошибка получения списка окон: {e}")
        return [{"error": str(e)}]

def find_window_by_title(title_pattern: str) -> List[Dict[str, Any]]:
    """Находит окна по паттерну в заголовке"""
    if not IS_WINDOWS or not WIN32_AVAILABLE:
        return [{"error": "Функция доступна только для Windows с установленными win32 модулями"}]
    
    try:
        windows = get_window_list()
        if windows and "error" in windows[0]:
            return windows
        
        matching_windows = []
        pattern_lower = title_pattern.lower()
        
        for window in windows:
            if pattern_lower in window["title"].lower():
                matching_windows.append(window)
        
        return matching_windows
        
    except Exception as e:
        logger.error(f"Ошибка поиска окон по заголовку {title_pattern}: {e}")
        return [{"error": str(e)}]

def is_program_running(program_name: str) -> Dict[str, Any]:
    """Проверяет, запущена ли программа"""
    try:
        running_processes = []
        program_lower = program_name.lower()
        
        if not PSUTIL_AVAILABLE:
            return []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                if program_lower in proc.info['name'].lower():
                    running_processes.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return {
            "is_running": len(running_processes) > 0,
            "processes": running_processes,
            "count": len(running_processes)
        }
        
    except Exception as e:
        logger.error(f"Ошибка проверки запуска программы {program_name}: {e}")
        return {"error": str(e), "is_running": False}

def close_window_by_hwnd(hwnd: int) -> Dict[str, Any]:
    """Закрывает окно по handle"""
    if not IS_WINDOWS or not WIN32_AVAILABLE:
        return {"success": False, "error": "Функция доступна только для Windows"}
    
    try:
        # Проверяем, что окно существует
        if not win32gui.IsWindow(hwnd):
            return {"success": False, "error": "Окно не найдено"}
        
        # Получаем заголовок для логирования
        window_title = win32gui.GetWindowText(hwnd)
        
        # Отправляем сообщение закрытия
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        
        return {
            "success": True,
            "message": f"Команда закрытия отправлена окну: {window_title}",
            "hwnd": hwnd,
            "title": window_title
        }
        
    except Exception as e:
        logger.error(f"Ошибка закрытия окна {hwnd}: {e}")
        return {"success": False, "error": str(e)}

def minimize_window_by_hwnd(hwnd: int) -> Dict[str, Any]:
    """Сворачивает окно по handle"""
    if not IS_WINDOWS or not WIN32_AVAILABLE:
        return {"success": False, "error": "Функция доступна только для Windows"}
    
    try:
        if not win32gui.IsWindow(hwnd):
            return {"success": False, "error": "Окно не найдено"}
        
        window_title = win32gui.GetWindowText(hwnd)
        
        # Сворачиваем окно
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        
        return {
            "success": True,
            "message": f"Окно свернуто: {window_title}",
            "hwnd": hwnd,
            "title": window_title
        }
        
    except Exception as e:
        logger.error(f"Ошибка сворачивания окна {hwnd}: {e}")
        return {"success": False, "error": str(e)}

def maximize_window_by_hwnd(hwnd: int) -> Dict[str, Any]:
    """Разворачивает окно по handle"""
    if not IS_WINDOWS or not WIN32_AVAILABLE:
        return {"success": False, "error": "Функция доступна только для Windows"}
    
    try:
        if not win32gui.IsWindow(hwnd):
            return {"success": False, "error": "Окно не найдено"}
        
        window_title = win32gui.GetWindowText(hwnd)
        
        # Разворачиваем окно
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        
        return {
            "success": True,
            "message": f"Окно развернуто: {window_title}",
            "hwnd": hwnd,
            "title": window_title
        }
        
    except Exception as e:
        logger.error(f"Ошибка разворачивания окна {hwnd}: {e}")
        return {"success": False, "error": str(e)}

def restore_window_by_hwnd(hwnd: int) -> Dict[str, Any]:
    """Восстанавливает окно по handle"""
    if not IS_WINDOWS or not WIN32_AVAILABLE:
        return {"success": False, "error": "Функция доступна только для Windows"}
    
    try:
        if not win32gui.IsWindow(hwnd):
            return {"success": False, "error": "Окно не найдено"}
        
        window_title = win32gui.GetWindowText(hwnd)
        
        # Восстанавливаем окно
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        
        return {
            "success": True,
            "message": f"Окно восстановлено: {window_title}",
            "hwnd": hwnd,
            "title": window_title
        }
        
    except Exception as e:
        logger.error(f"Ошибка восстановления окна {hwnd}: {e}")
        return {"success": False, "error": str(e)}

def get_window_info_by_hwnd(hwnd: int) -> Dict[str, Any]:
    """Получает подробную информацию об окне"""
    if not IS_WINDOWS or not WIN32_AVAILABLE:
        return {"error": "Функция доступна только для Windows"}
    
    try:
        if not win32gui.IsWindow(hwnd):
            return {"error": "Окно не найдено"}
        
        # Получаем основную информацию
        window_title = win32gui.GetWindowText(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        
        # Получаем информацию о процессе
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        
        try:
            process = psutil.Process(pid)
            process_info = {
                "name": process.name(),
                "cpu_percent": process.cpu_percent(),
                "memory_percent": process.memory_percent(),
                "status": process.status()
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            process_info = {"error": "Нет доступа к информации о процессе"}
        
        return {
            "hwnd": hwnd,
            "title": window_title,
            "pid": pid,
            "process": process_info,
            "rect": {
                "left": rect[0],
                "top": rect[1],
                "right": rect[2],
                "bottom": rect[3],
                "width": rect[2] - rect[0],
                "height": rect[3] - rect[1]
            },
            "is_visible": win32gui.IsWindowVisible(hwnd),
            "is_minimized": win32gui.IsIconic(hwnd),
            "is_maximized": win32gui.IsZoomed(hwnd),
            "is_enabled": win32gui.IsWindowEnabled(hwnd)
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения информации об окне {hwnd}: {e}")
        return {"error": str(e)}
