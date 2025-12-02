"""
Системные утилиты для PC Management Agent
Основано на коде из evi-run-main/jarvis/jarvis_ai/utils/system_utils.py
"""

import os
import subprocess
import shutil
import platform
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None
    logger = logging.getLogger(__name__)
    logger.warning("psutil не установлен. Некоторые функции PC agent будут недоступны.")

from ..config import (
    IS_WINDOWS, COMMON_PROGRAMS, PROGRAM_FILES, PROGRAM_FILES_X86,
    SEARCH_PATHS, DANGEROUS_EXTENSIONS, MAX_PROCESS_LIST
)

logger = logging.getLogger(__name__)

def _check_psutil():
    """Проверка доступности psutil"""
    if not PSUTIL_AVAILABLE:
        raise ImportError("psutil не установлен. Установите: pip install psutil")

def get_installed_programs() -> List[str]:
    """Получает список установленных программ"""
    programs = []
    
    if not IS_WINDOWS:
        return ["Функция доступна только для Windows"]
    
    try:
        # Сначала добавляем популярные программы
        programs.extend(COMMON_PROGRAMS.keys())
        
        # Попытка получить программы из реестра
        try:
            import winreg
            registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
            
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path) as key:
                for i in range(0, winreg.QueryInfoKey(key)[0]):
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                            if display_name and display_name not in programs:
                                programs.append(display_name)
                    except (FileNotFoundError, OSError):
                        continue
        except ImportError:
            logger.warning("winreg недоступен, используются только популярные программы")
        except Exception as e:
            logger.warning(f"Ошибка получения программ из реестра: {e}")
        
        # Поиск исполняемых файлов в Program Files
        for program_dir in [PROGRAM_FILES, PROGRAM_FILES_X86]:
            if os.path.exists(program_dir):
                try:
                    for item in os.listdir(program_dir):
                        item_path = os.path.join(program_dir, item)
                        if os.path.isdir(item_path) and item not in programs:
                            programs.append(item)
                except PermissionError:
                    continue
        
        return sorted(list(set(programs)))
        
    except Exception as e:
        logger.error(f"Ошибка получения установленных программ: {e}")
        return ["Ошибка получения списка программ"]

def find_program_by_name(name: str) -> Optional[str]:
    """Находит путь к программе по названию"""
    try:
        name_lower = name.lower()
        
        # Проверяем популярные программы
        if name_lower in COMMON_PROGRAMS:
            return COMMON_PROGRAMS[name_lower]
        
        # Поиск в PATH
        program_path = shutil.which(name)
        if program_path:
            return program_path
        
        # Поиск в стандартных директориях
        search_dirs = [PROGRAM_FILES, PROGRAM_FILES_X86]
        
        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
                
            for root, dirs, files in os.walk(search_dir):
                # Ограничиваем глубину поиска
                level = root.replace(search_dir, '').count(os.sep)
                if level >= 3:
                    dirs[:] = []  # Не углубляемся дальше
                    continue
                
                for file in files:
                    if (name_lower in file.lower() and 
                        file.lower().endswith(('.exe', '.bat', '.cmd'))):
                        return os.path.join(root, file)
        
        return None
        
    except Exception as e:
        logger.error(f"Ошибка поиска программы {name}: {e}")
        return None

def is_safe_path(file_path: str) -> bool:
    """Проверяет, является ли путь безопасным для операций"""
    try:
        # Преобразуем в абсолютный путь
        abs_path = os.path.abspath(file_path)
        
        # Проверяем, что путь не выходит за пределы безопасных директорий
        safe_dirs = [
            os.path.abspath(path) for path in SEARCH_PATHS
        ]
        
        # Добавляем временные директории
        safe_dirs.extend([
            os.path.abspath(os.path.expanduser("~")),
            os.path.abspath(os.environ.get('TEMP', '/tmp')),
        ])
        
        for safe_dir in safe_dirs:
            try:
                # Проверяем, начинается ли путь с безопасной директории
                if abs_path.startswith(safe_dir):
                    return True
            except Exception:
                continue
        
        return False
        
    except Exception as e:
        logger.warning(f"Ошибка проверки безопасности пути {file_path}: {e}")
        return False

def format_file_size(size_bytes: int) -> str:
    """Форматирует размер файла в читаемый вид"""
    try:
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        
        while size >= 1024.0 and i < len(size_names) - 1:
            size /= 1024.0
            i += 1
        
        return f"{size:.1f} {size_names[i]}"
        
    except Exception:
        return f"{size_bytes} B"

def get_system_statistics() -> Dict[str, Any]:
    """Получает статистику системы"""
    if not PSUTIL_AVAILABLE:
        return {
            "error": "psutil не установлен. Установите: pip install psutil",
            "cpu": {"count": "N/A", "percent": "N/A", "frequency": None},
            "memory": {"total": "N/A", "available": "N/A", "used": "N/A", "percent": "N/A"},
            "disk": []
        }
    
    try:
        # Информация о CPU
        cpu_info = {
            "count": psutil.cpu_count(),
            "percent": psutil.cpu_percent(interval=1),
            "frequency": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None
        }
        
        # Информация о памяти
        memory = psutil.virtual_memory()
        memory_info = {
            "total": format_file_size(memory.total),
            "available": format_file_size(memory.available),
            "used": format_file_size(memory.used),
            "percent": memory.percent
        }
        
        # Информация о дисках
        disk_info = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disk_info.append({
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "fstype": partition.fstype,
                    "total": format_file_size(usage.total),
                    "used": format_file_size(usage.used),
                    "free": format_file_size(usage.free),
                    "percent": (usage.used / usage.total * 100) if usage.total > 0 else 0
                })
            except PermissionError:
                continue
        
        # Информация о сети
        network = psutil.net_io_counters() if PSUTIL_AVAILABLE else None
        network_info = {
            "bytes_sent": format_file_size(network.bytes_sent),
            "bytes_recv": format_file_size(network.bytes_recv),
            "packets_sent": network.packets_sent,
            "packets_recv": network.packets_recv
        }
        
        return {
            "cpu": cpu_info,
            "memory": memory_info,
            "disks": disk_info,
            "network": network_info,
            "boot_time": psutil.boot_time() if PSUTIL_AVAILABLE else None,
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor()
            }
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения статистики системы: {e}")
        return {"error": str(e)}

def get_process_info(pid: Optional[int] = None, name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Получает информацию о процессах"""
    try:
        processes = []
        count = 0
        
        if not PSUTIL_AVAILABLE:
            return []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
            try:
                if count >= MAX_PROCESS_LIST:
                    break
                
                proc_info = proc.info
                
                # Фильтрация по PID
                if pid is not None and proc_info['pid'] != pid:
                    continue
                
                # Фильтрация по имени
                if name is not None and name.lower() not in proc_info['name'].lower():
                    continue
                
                # Получаем дополнительную информацию
                try:
                    memory_info = proc.memory_info()
                    proc_info.update({
                        'memory_rss': format_file_size(memory_info.rss),
                        'memory_vms': format_file_size(memory_info.vms),
                        'create_time': proc.create_time(),
                        'num_threads': proc.num_threads()
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                
                processes.append(proc_info)
                count += 1
                
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        return processes
        
    except Exception as e:
        logger.error(f"Ошибка получения информации о процессах: {e}")
        return [{"error": str(e)}]

def is_executable_safe(file_path: str) -> bool:
    """Проверяет, безопасно ли выполнять файл"""
    try:
        # Проверяем расширение
        extension = Path(file_path).suffix.lower()
        if extension in DANGEROUS_EXTENSIONS:
            return False
        
        # Проверяем путь
        if not is_safe_path(file_path):
            return False
        
        # Проверяем размер файла
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            if size > 100 * 1024 * 1024:  # 100 MB
                return False
        
        return True
        
    except Exception:
        return False
