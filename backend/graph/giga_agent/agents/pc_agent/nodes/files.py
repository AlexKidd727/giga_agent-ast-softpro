"""
Узлы для файловых операций PC Management Agent
"""

import os
import logging
from typing import Annotated
from datetime import datetime

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.file_utils import (
    safe_read_file, find_files_recursive, get_directory_contents,
    create_text_file, validate_file_operation
)
from ..utils.system_utils import is_safe_path, format_file_size
from ..config import SEARCH_PATHS, DESKTOP_PATH, DOCUMENTS_PATH, DOWNLOADS_PATH

logger = logging.getLogger(__name__)

@tool
async def search_files(
    pattern: str,
    directory: str = None,
    file_type: str = None,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Поиск файлов по паттерну
    
    Args:
        pattern: Паттерн для поиска в названии файла
        directory: Директория для поиска (необязательно, по умолчанию - все разрешенные)
        file_type: Тип файла для фильтрации (text, image, video, audio, document, code)
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        if not pattern or len(pattern) < 2:
            return {
                "error": True,
                "message": "❌ **Паттерн поиска должен содержать минимум 2 символа**"
            }
        
        # Определяем директории для поиска
        search_dirs = []
        if directory:
            if is_safe_path(directory):
                search_dirs = [directory]
            else:
                return {
                    "error": True,
                    "message": f"❌ **Доступ к директории '{directory}' запрещен**"
                }
        else:
            # Поиск в стандартных директориях
            search_dirs = [DESKTOP_PATH, DOCUMENTS_PATH, DOWNLOADS_PATH]
        
        all_results = []
        
        # Поиск в каждой директории
        for search_dir in search_dirs:
            if os.path.exists(search_dir):
                results = find_files_recursive(search_dir, pattern, file_type)
                
                # Фильтруем ошибки
                valid_results = [r for r in results if "error" not in r]
                all_results.extend(valid_results)
        
        if not all_results:
            search_locations = ", ".join([os.path.basename(d) for d in search_dirs])
            return {
                "success": True,
                "message": f"🔍 **Поиск '{pattern}'**\n\nФайлы не найдены в: {search_locations}\n\n💡 Попробуйте изменить паттерн поиска",
                "results_count": 0
            }
        
        # Ограничиваем и сортируем результаты
        all_results = sorted(all_results, key=lambda x: x.get('modified', 0), reverse=True)[:20]
        
        # Форматируем результаты
        message = f"🔍 **Найдено файлов: {len(all_results)}** (паттерн: '{pattern}')\n\n"
        
        for i, file_info in enumerate(all_results[:10], 1):
            icon = {
                'text': '📄', 'code': '💻', 'image': '🖼️', 
                'video': '🎬', 'audio': '🎵', 'document': '📋', 
                'archive': '📦', 'executable': '⚙️'
            }.get(file_info.get('category', 'unknown'), '📄')
            
            message += f"{icon} **{file_info['name']}**\n"
            message += f"  📁 `{file_info['directory']}`\n"
            message += f"  📏 {file_info['size']}"
            
            if file_info.get('safe_to_read'):
                message += " | 📖 Можно прочитать"
            
            message += "\n\n"
        
        if len(all_results) > 10:
            message += f"... и еще {len(all_results) - 10} файлов"
        
        return {
            "success": True,
            "message": message,
            "results_count": len(all_results),
            "files": all_results[:10]
        }
        
    except Exception as e:
        logger.error(f"Ошибка поиска файлов: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка поиска файлов:** {str(e)}"
        }

@tool
async def open_file(
    file_path: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Открытие файла системным приложением
    
    Args:
        file_path: Путь к файлу для открытия
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        if not is_safe_path(file_path):
            return {
                "error": True,
                "message": f"❌ **Доступ к файлу запрещен:** {file_path}"
            }
        
        if not os.path.exists(file_path):
            return {
                "error": True,
                "message": f"❌ **Файл не найден:** {file_path}"
            }
        
        if not os.path.isfile(file_path):
            return {
                "error": True,
                "message": f"❌ **Указанный путь не является файлом:** {file_path}"
            }
        
        # Открываем файл
        try:
            import subprocess
            subprocess.run(["start", "", file_path], shell=True, check=True)
            
            return {
                "success": True,
                "message": f"✅ **Файл открыт:** `{os.path.basename(file_path)}`\n\n📁 **Путь:** {file_path}",
                "file_path": file_path,
                "file_name": os.path.basename(file_path)
            }
            
        except subprocess.CalledProcessError as e:
            return {
                "error": True,
                "message": f"❌ **Ошибка открытия файла:** {str(e)}"
            }
            
    except Exception as e:
        logger.error(f"Ошибка открытия файла {file_path}: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка открытия файла:** {str(e)}"
        }

@tool
async def read_file(
    file_path: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Чтение содержимого текстового файла
    
    Args:
        file_path: Путь к файлу для чтения
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        content = safe_read_file(file_path)
        
        # Проверяем, не вернулась ли ошибка
        if content.startswith("❌"):
            return {
                "error": True,
                "message": content
            }
        
        return {
            "success": True,
            "message": content,
            "file_path": file_path,
            "file_name": os.path.basename(file_path)
        }
        
    except Exception as e:
        logger.error(f"Ошибка чтения файла {file_path}: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка чтения файла:** {str(e)}"
        }

@tool
async def create_file(
    file_path: str,
    content: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Создание текстового файла
    
    Args:
        file_path: Путь для создания файла
        content: Содержимое файла
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        success, message = create_text_file(file_path, content)
        
        if success:
            file_size = len(content.encode('utf-8'))
            return {
                "success": True,
                "message": f"✅ **Файл создан:** `{os.path.basename(file_path)}`\n\n📁 **Путь:** {file_path}\n📏 **Размер:** {format_file_size(file_size)}",
                "file_path": file_path,
                "file_name": os.path.basename(file_path),
                "file_size": file_size
            }
        else:
            return {
                "error": True,
                "message": f"❌ **{message}**"
            }
            
    except Exception as e:
        logger.error(f"Ошибка создания файла {file_path}: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка создания файла:** {str(e)}"
        }

@tool
async def file_info(
    file_path: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Получение информации о файле или директории
    
    Args:
        file_path: Путь к файлу или директории
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        if not is_safe_path(file_path):
            return {
                "error": True,
                "message": f"❌ **Доступ к пути запрещен:** {file_path}"
            }
        
        if not os.path.exists(file_path):
            return {
                "error": True,
                "message": f"❌ **Путь не найден:** {file_path}"
            }
        
        stat = os.stat(file_path)
        is_dir = os.path.isdir(file_path)
        
        # Форматируем время
        created_time = datetime.fromtimestamp(stat.st_ctime).strftime("%d.%m.%Y %H:%M")
        modified_time = datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M")
        
        if is_dir:
            # Информация о директории
            try:
                contents = os.listdir(file_path)
                files_count = len([f for f in contents if os.path.isfile(os.path.join(file_path, f))])
                dirs_count = len([f for f in contents if os.path.isdir(os.path.join(file_path, f))])
                
                message = f"""📁 **Информация о папке**

📛 **Имя:** `{os.path.basename(file_path)}`
📍 **Путь:** `{file_path}`

📊 **Содержимое:**
• Файлов: {files_count}
• Папок: {dirs_count}
• Всего элементов: {len(contents)}

📅 **Даты:**
• Создано: {created_time}
• Изменено: {modified_time}"""
                
            except PermissionError:
                message = f"""📁 **Информация о папке**

📛 **Имя:** `{os.path.basename(file_path)}`
📍 **Путь:** `{file_path}`

❌ **Нет доступа к содержимому папки**

📅 **Даты:**
• Создано: {created_time}
• Изменено: {modified_time}"""
        else:
            # Информация о файле
            from ..utils.file_utils import get_file_type
            category, mime_type = get_file_type(file_path)
            
            message = f"""📄 **Информация о файле**

📛 **Имя:** `{os.path.basename(file_path)}`
📍 **Путь:** `{file_path}`

📏 **Размер:** {format_file_size(stat.st_size)}
🏷️ **Тип:** {category}
📋 **MIME:** {mime_type}
📄 **Расширение:** {os.path.splitext(file_path)[1] or 'нет'}

📅 **Даты:**
• Создано: {created_time}
• Изменено: {modified_time}"""
            
            # Дополнительная информация для текстовых файлов
            if category in ['text', 'code'] and stat.st_size <= 1024 * 1024:  # 1MB
                message += "\n\n💡 **Файл можно прочитать с помощью инструмента read_file**"
        
        return {
            "success": True,
            "message": message,
            "file_path": file_path,
            "is_directory": is_dir,
            "size": stat.st_size
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения информации о файле {file_path}: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения информации:** {str(e)}"
        }

@tool
async def list_directory(
    directory: str = None,
    show_hidden: bool = False,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Получение содержимого директории
    
    Args:
        directory: Путь к директории (необязательно, по умолчанию - домашняя папка)
        show_hidden: Показывать скрытые файлы (необязательно)
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        if directory is None:
            directory = os.path.expanduser("~")
        
        contents = get_directory_contents(directory, show_hidden)
        
        # Проверяем на ошибки
        if contents and "error" in contents[0]:
            return {
                "error": True,
                "message": f"❌ **{contents[0]['error']}**"
            }
        
        if not contents:
            return {
                "success": True,
                "message": f"📁 **Директория пуста:** `{os.path.basename(directory)}`\n\n📍 **Путь:** {directory}",
                "directory": directory,
                "items_count": 0
            }
        
        # Сортируем: сначала папки, потом файлы
        directories = [item for item in contents if item.get('is_directory', False)]
        files = [item for item in contents if not item.get('is_directory', False)]
        
        message = f"📁 **Содержимое папки:** `{os.path.basename(directory)}`\n\n📍 **Путь:** {directory}\n\n"
        
        # Показываем папки
        if directories:
            message += f"📂 **Папки ({len(directories)}):**\n"
            for dir_item in directories[:15]:  # Ограничиваем вывод
                name = dir_item['name']
                if len(name) > 50:
                    name = name[:47] + "..."
                message += f"• {name}\n"
            
            if len(directories) > 15:
                message += f"... и еще {len(directories) - 15} папок\n"
            message += "\n"
        
        # Показываем файлы
        if files:
            message += f"📄 **Файлы ({len(files)}):**\n"
            for file_item in files[:15]:  # Ограничиваем вывод
                icon = {
                    'text': '📄', 'code': '💻', 'image': '🖼️', 
                    'video': '🎬', 'audio': '🎵', 'document': '📋', 
                    'archive': '📦', 'executable': '⚙️'
                }.get(file_item.get('category', 'unknown'), '📄')
                
                name = file_item['name']
                if len(name) > 40:
                    name = name[:37] + "..."
                
                message += f"{icon} {name} ({file_item['size_formatted']})\n"
            
            if len(files) > 15:
                message += f"... и еще {len(files) - 15} файлов\n"
        
        message += f"\n📊 **Итого:** {len(directories)} папок, {len(files)} файлов"
        
        return {
            "success": True,
            "message": message,
            "directory": directory,
            "items_count": len(contents),
            "directories_count": len(directories),
            "files_count": len(files)
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения содержимого директории {directory}: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения содержимого директории:** {str(e)}"
        }
