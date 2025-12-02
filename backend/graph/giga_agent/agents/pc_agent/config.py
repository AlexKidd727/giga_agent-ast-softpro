"""
Конфигурация PC Management Agent
"""

import os
import platform
from pathlib import Path

def get_pc_agent_llm():
    """Получить LLM для PC агента (отложенный импорт)"""
    from giga_agent.utils.llm import load_llm
    return load_llm().with_config(tags=["nostream"])

# Определяем ОС
IS_WINDOWS = platform.system() == "Windows"

# Пути пользователя
USER_PROFILE = os.path.expanduser("~")
DESKTOP_PATH = os.path.join(USER_PROFILE, "Desktop")
DOCUMENTS_PATH = os.path.join(USER_PROFILE, "Documents")
DOWNLOADS_PATH = os.path.join(USER_PROFILE, "Downloads")

# Системные пути Windows
if IS_WINDOWS:
    PROGRAM_FILES = os.environ.get('ProgramFiles', 'C:\\Program Files')
    PROGRAM_FILES_X86 = os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')
    SYSTEM_DRIVE = os.environ.get('SystemDrive', 'C:')
    TEMP_DIR = os.environ.get('TEMP', 'C:\\Temp')
    APPDATA = os.environ.get('APPDATA', os.path.join(USER_PROFILE, 'AppData', 'Roaming'))
    LOCALAPPDATA = os.environ.get('LOCALAPPDATA', os.path.join(USER_PROFILE, 'AppData', 'Local'))
else:
    # Для других ОС
    PROGRAM_FILES = "/usr/bin"
    PROGRAM_FILES_X86 = "/usr/bin"
    SYSTEM_DRIVE = "/"
    TEMP_DIR = "/tmp"
    APPDATA = os.path.join(USER_PROFILE, ".config")
    LOCALAPPDATA = os.path.join(USER_PROFILE, ".local")

# Настройки безопасности
ALLOWED_EXTENSIONS = {
    # Текстовые файлы
    '.txt', '.md', '.json', '.xml', '.csv', '.log',
    # Документы
    '.doc', '.docx', '.pdf', '.xls', '.xlsx', '.ppt', '.pptx',
    # Изображения
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.ico',
    # Видео
    '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv',
    # Аудио
    '.mp3', '.wav', '.flac', '.aac', '.ogg',
    # Архивы
    '.zip', '.rar', '.7z', '.tar', '.gz',
    # Код
    '.py', '.js', '.html', '.css', '.cpp', '.java', '.cs', '.php',
    # Исполняемые (только просмотр)
    '.exe', '.msi', '.bat', '.cmd', '.ps1'
}

# Запрещенные для выполнения расширения
DANGEROUS_EXTENSIONS = {
    '.exe', '.msi', '.bat', '.cmd', '.ps1', '.vbs', '.js', '.jar', 
    '.scr', '.com', '.pif', '.reg', '.dll', '.sys'
}

# Популярные программы Windows
COMMON_PROGRAMS = {
    'notepad': 'notepad.exe',
    'блокнот': 'notepad.exe',
    'calculator': 'calc.exe',
    'калькулятор': 'calc.exe',
    'paint': 'mspaint.exe',
    'paint': 'mspaint.exe',
    'командная строка': 'cmd.exe',
    'cmd': 'cmd.exe',
    'powershell': 'powershell.exe',
    'explorer': 'explorer.exe',
    'проводник': 'explorer.exe',
    'control': 'control.exe',
    'панель управления': 'control.exe',
    'msconfig': 'msconfig.exe',
    'regedit': 'regedit.exe',
    'registry': 'regedit.exe',
    'реестр': 'regedit.exe',
    'taskmgr': 'taskmgr.exe',
    'диспетчер задач': 'taskmgr.exe',
    'task manager': 'taskmgr.exe'
}

# Настройки поиска файлов
SEARCH_PATHS = [
    DESKTOP_PATH,
    DOCUMENTS_PATH,
    DOWNLOADS_PATH,
    PROGRAM_FILES,
    PROGRAM_FILES_X86,
    APPDATA,
    LOCALAPPDATA
]

# Ограничения безопасности
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_SEARCH_RESULTS = 50
MAX_PROCESS_LIST = 100

# Настройки для операций с файлами
FILE_OPERATIONS = {
    'create': True,
    'read': True,
    'update': True,
    'delete': False,  # Отключено для безопасности
    'execute': False,  # Отключено для безопасности
    'move': True,
    'copy': True
}
