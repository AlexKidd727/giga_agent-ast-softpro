"""
Файловые утилиты для PC Management Agent
Основано на коде из evi-run-main/jarvis/jarvis_ai/utils/file_utils.py
"""

import os
import mimetypes
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from ..config import (
    ALLOWED_EXTENSIONS, DANGEROUS_EXTENSIONS, MAX_FILE_SIZE, 
    MAX_SEARCH_RESULTS, SEARCH_PATHS
)
from .system_utils import is_safe_path, format_file_size

logger = logging.getLogger(__name__)

def safe_read_file(file_path: str, max_size: int = MAX_FILE_SIZE) -> str:
    """Безопасное чтение файла с ограничениями"""
    try:
        # Проверки безопасности
        if not is_safe_path(file_path):
            return "❌ Доступ к файлу запрещен по соображениям безопасности"
        
        if not os.path.exists(file_path):
            return "❌ Файл не найден"
        
        if not os.path.isfile(file_path):
            return "❌ Указанный путь не является файлом"
        
        # Проверяем размер файла
        file_size = os.path.getsize(file_path)
        if file_size > max_size:
            return f"❌ Файл слишком большой ({format_file_size(file_size)}). Максимум: {format_file_size(max_size)}"
        
        # Проверяем расширение
        extension = Path(file_path).suffix.lower()
        if extension and extension not in ALLOWED_EXTENSIONS:
            return f"❌ Тип файла не поддерживается: {extension}"
        
        # Читаем файл
        try:
            # Пробуем как текстовый файл с разными кодировками
            encodings = ['utf-8', 'cp1251', 'latin-1']
            content = None
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                # Пробуем как бинарный файл
                with open(file_path, 'rb') as f:
                    binary_content = f.read(1024)  # Читаем первые 1KB
                    return f"📄 **Бинарный файл**\n\nПервые 1024 байта:\n{binary_content.hex()}"
            
            # Ограничиваем вывод для больших файлов
            if len(content) > 10000:
                content = content[:10000] + "\n\n... (файл обрезан, показаны первые 10000 символов)"
            
            return f"📄 **Содержимое файла**: `{os.path.basename(file_path)}`\n\n```\n{content}\n```"
            
        except PermissionError:
            return "❌ Нет прав доступа к файлу"
        except Exception as e:
            return f"❌ Ошибка чтения файла: {str(e)}"
            
    except Exception as e:
        logger.error(f"Ошибка безопасного чтения файла {file_path}: {e}")
        return f"❌ Ошибка: {str(e)}"

def get_file_type(file_path: str) -> Tuple[str, str]:
    """Получение типа файла и его MIME-типа"""
    try:
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = "unknown"
        
        file_extension = Path(file_path).suffix.lower()
        
        # Определяем категорию файла
        if file_extension in ['.txt', '.md', '.log', '.json', '.xml', '.csv']:
            category = "text"
        elif file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg']:
            category = "image"
        elif file_extension in ['.mp4', '.avi', '.mkv', '.mov', '.wmv']:
            category = "video"
        elif file_extension in ['.mp3', '.wav', '.flac', '.aac', '.ogg']:
            category = "audio"
        elif file_extension in ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']:
            category = "document"
        elif file_extension in ['.zip', '.rar', '.7z', '.tar', '.gz']:
            category = "archive"
        elif file_extension in ['.exe', '.msi', '.bat', '.cmd']:
            category = "executable"
        elif file_extension in ['.py', '.js', '.html', '.css', '.cpp', '.java']:
            category = "code"
        else:
            category = "unknown"
        
        return category, mime_type
        
    except Exception as e:
        logger.warning(f"Ошибка определения типа файла {file_path}: {e}")
        return "unknown", "unknown"

def validate_file_operation(file_path: str, operation: str) -> Tuple[bool, str]:
    """Валидация файловой операции"""
    try:
        # Проверяем безопасность пути
        if not is_safe_path(file_path):
            return False, "Путь находится вне разрешенных директорий"
        
        # Проверяем операцию
        if operation not in ['read', 'create', 'update', 'copy', 'move']:
            return False, f"Неподдерживаемая операция: {operation}"
        
        # Для существующих файлов
        if os.path.exists(file_path):
            # Проверяем тип файла
            extension = Path(file_path).suffix.lower()
            
            if operation in ['create', 'update'] and extension in DANGEROUS_EXTENSIONS:
                return False, f"Операция {operation} запрещена для файлов типа {extension}"
            
            # Проверяем размер
            if operation == 'read':
                file_size = os.path.getsize(file_path)
                if file_size > MAX_FILE_SIZE:
                    return False, f"Файл слишком большой: {format_file_size(file_size)}"
        
        return True, "OK"
        
    except Exception as e:
        return False, f"Ошибка валидации: {str(e)}"

def find_files_recursive(directory: str, pattern: str, file_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Рекурсивный поиск файлов с ограничениями"""
    try:
        found_files = []
        pattern_lower = pattern.lower()
        
        # Проверяем безопасность директории
        if not is_safe_path(directory):
            return [{"error": "Директория находится вне разрешенных путей"}]
        
        if not os.path.exists(directory):
            return [{"error": "Директория не существует"}]
        
        if not os.path.isdir(directory):
            return [{"error": "Указанный путь не является директорией"}]
        
        # Поиск файлов
        for root, dirs, files in os.walk(directory):
            # Ограничиваем глубину поиска
            level = root.replace(directory, '').count(os.sep)
            if level >= 5:  # Максимум 5 уровней вложенности
                dirs[:] = []
                continue
            
            # Исключаем системные директории
            dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in ['__pycache__', 'node_modules']]
            
            for file in files:
                if len(found_files) >= MAX_SEARCH_RESULTS:
                    break
                
                # Проверяем соответствие паттерну
                if pattern_lower not in file.lower():
                    continue
                
                file_path = os.path.join(root, file)
                
                try:
                    # Получаем информацию о файле
                    stat = os.stat(file_path)
                    category, mime_type = get_file_type(file_path)
                    
                    # Фильтр по типу файла
                    if file_type and category != file_type.lower():
                        continue
                    
                    file_info = {
                        "name": file,
                        "path": file_path,
                        "directory": root,
                        "size": format_file_size(stat.st_size),
                        "size_bytes": stat.st_size,
                        "modified": stat.st_mtime,
                        "category": category,
                        "mime_type": mime_type,
                        "extension": Path(file).suffix.lower(),
                        "safe_to_read": category in ['text', 'code'] and stat.st_size <= MAX_FILE_SIZE
                    }
                    
                    found_files.append(file_info)
                    
                except (PermissionError, OSError):
                    continue
            
            if len(found_files) >= MAX_SEARCH_RESULTS:
                break
        
        return found_files
        
    except Exception as e:
        logger.error(f"Ошибка поиска файлов в {directory}: {e}")
        return [{"error": str(e)}]

def get_directory_contents(directory: str, show_hidden: bool = False) -> List[Dict[str, Any]]:
    """Получение содержимого директории"""
    try:
        # Проверяем безопасность
        if not is_safe_path(directory):
            return [{"error": "Директория находится вне разрешенных путей"}]
        
        if not os.path.exists(directory):
            return [{"error": "Директория не существует"}]
        
        if not os.path.isdir(directory):
            return [{"error": "Указанный путь не является директорией"}]
        
        contents = []
        
        try:
            entries = os.listdir(directory)
            
            for entry in sorted(entries):
                # Пропускаем скрытые файлы если не запрошены
                if not show_hidden and entry.startswith('.'):
                    continue
                
                entry_path = os.path.join(directory, entry)
                
                try:
                    stat = os.stat(entry_path)
                    is_dir = os.path.isdir(entry_path)
                    
                    item_info = {
                        "name": entry,
                        "path": entry_path,
                        "is_directory": is_dir,
                        "size": 0 if is_dir else stat.st_size,
                        "size_formatted": "папка" if is_dir else format_file_size(stat.st_size),
                        "modified": stat.st_mtime,
                        "extension": "" if is_dir else Path(entry).suffix.lower()
                    }
                    
                    if not is_dir:
                        category, mime_type = get_file_type(entry_path)
                        item_info.update({
                            "category": category,
                            "mime_type": mime_type,
                            "safe_to_read": category in ['text', 'code'] and stat.st_size <= MAX_FILE_SIZE
                        })
                    
                    contents.append(item_info)
                    
                except (PermissionError, OSError) as e:
                    contents.append({
                        "name": entry,
                        "path": entry_path,
                        "error": f"Нет доступа: {str(e)}"
                    })
        
        except PermissionError:
            return [{"error": "Нет прав доступа к директории"}]
        
        return contents
        
    except Exception as e:
        logger.error(f"Ошибка получения содержимого директории {directory}: {e}")
        return [{"error": str(e)}]

def create_text_file(file_path: str, content: str) -> Tuple[bool, str]:
    """Создание текстового файла"""
    try:
        # Проверки безопасности
        valid, error = validate_file_operation(file_path, 'create')
        if not valid:
            return False, error
        
        # Проверяем, что это текстовый файл
        extension = Path(file_path).suffix.lower()
        if extension and extension not in ['.txt', '.md', '.json', '.csv', '.log', '.py', '.js', '.html', '.css']:
            return False, f"Создание файлов типа {extension} не поддерживается"
        
        # Проверяем размер содержимого
        if len(content.encode('utf-8')) > MAX_FILE_SIZE:
            return False, f"Содержимое слишком большое. Максимум: {format_file_size(MAX_FILE_SIZE)}"
        
        # Создаем директорию если не существует
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        
        # Записываем файл
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return True, f"Файл создан: {file_path}"
        
    except PermissionError:
        return False, "Нет прав для создания файла"
    except Exception as e:
        return False, f"Ошибка создания файла: {str(e)}"
