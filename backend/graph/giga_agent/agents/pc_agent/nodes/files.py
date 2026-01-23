"""
Узлы для файловых операций PC Management Agent
"""

import os
import logging
import shutil
from typing import Annotated
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.file_utils import (
    safe_read_file, find_files_recursive, get_directory_contents,
    create_text_file, validate_file_operation, get_file_type
)
from ..utils.system_utils import is_safe_path, format_file_size
from ..config import SEARCH_PATHS, DESKTOP_PATH, DOCUMENTS_PATH, DOWNLOADS_PATH, MAX_SEARCH_RESULTS, MAX_FILE_SIZE, IS_WINDOWS

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
        directory: Директория для поиска (необязательно). Если не указана, выполняется глобальный поиск по всем доступным дискам (C:, D:, E: и т.д.)
        file_type: Тип файла для фильтрации (text, image, video, audio, document, code) или "directory" для поиска папок
        user_id: Идентификатор пользователя (необязательно)
    
    Примечание: При глобальном поиске (без указания directory) системные директории (Windows, Program Files и т.д.) автоматически исключаются из результатов.
    """
    try:
        if not pattern or len(pattern) < 2:
            return {
                "error": True,
                "message": "❌ **Паттерн поиска должен содержать минимум 2 символа**"
            }
        
        # Определяем директории для поиска
        search_dirs = []
        global_search = False
        
        if directory:
            # Если директория явно указана, проверяем только, что это не системная директория
            from ..utils.system_utils import is_system_directory
            if is_system_directory(directory):
                return {
                    "error": True,
                    "message": f"❌ **Доступ к системной директории '{directory}' запрещен по соображениям безопасности**"
                }
            # Проверяем, что директория существует
            if not os.path.exists(directory):
                return {
                    "error": True,
                    "message": f"❌ **Директория '{directory}' не существует**"
                }
            if not os.path.isdir(directory):
                return {
                    "error": True,
                    "message": f"❌ **Путь '{directory}' не является директорией**"
                }
            # Разрешаем поиск в явно указанной директории (пропускаем проверку is_safe_path)
            search_dirs = [directory]
            global_search = True  # Пропускаем проверку безопасности для явно указанных путей
            logger.info(f"Поиск в указанной директории: {directory}")
        else:
            # Глобальный поиск по всем доступным дискам
            from ..utils.system_utils import get_available_drives
            drives = get_available_drives()
            if drives:
                search_dirs = drives
                global_search = True
                logger.info(f"Глобальный поиск по дискам: {drives}")
            else:
                # Fallback: поиск в стандартных директориях
                search_dirs = [DESKTOP_PATH, DOCUMENTS_PATH, DOWNLOADS_PATH]
        
        all_results = []
        
        # Поиск в каждой директории
        for search_dir in search_dirs:
            if os.path.exists(search_dir):
                # Для глобального поиска и явно указанных директорий пропускаем проверку безопасности
                results = find_files_recursive(search_dir, pattern, file_type, skip_safe_check=global_search)
                
                # Фильтруем ошибки
                valid_results = [r for r in results if "error" not in r]
                all_results.extend(valid_results)
                
                # Ограничиваем количество результатов для глобального поиска
                if global_search and len(all_results) >= MAX_SEARCH_RESULTS:
                    break
        
        if not all_results:
            if global_search:
                search_locations = ", ".join([d.rstrip("\\/") for d in search_dirs])
                search_type = "папок" if file_type and file_type.lower() == "directory" else "файлов"
                return {
                    "success": True,
                    "message": f"🔍 **Поиск {search_type} '{pattern}'**\n\n{search_type.capitalize()} не найдены на дисках: {search_locations}\n\n💡 Попробуйте изменить паттерн поиска или укажите конкретную директорию",
                    "results_count": 0
                }
            else:
                search_locations = ", ".join([os.path.basename(d) for d in search_dirs])
                search_type = "папок" if file_type and file_type.lower() == "directory" else "файлов"
                return {
                    "success": True,
                    "message": f"🔍 **Поиск {search_type} '{pattern}'**\n\n{search_type.capitalize()} не найдены в: {search_locations}\n\n💡 Попробуйте изменить паттерн поиска",
                    "results_count": 0
                }
        
        # Ограничиваем и сортируем результаты
        all_results = sorted(all_results, key=lambda x: x.get('modified', 0), reverse=True)[:20]
        
        # Определяем тип результатов для сообщения
        search_type = "папок" if file_type and file_type.lower() == "directory" else "файлов"
        search_scope = "на всех дисках" if global_search else ""
        
        # Форматируем результаты
        message = f"🔍 **Найдено {search_type}: {len(all_results)}** {search_scope}(паттерн: '{pattern}')\n\n"
        
        for i, file_info in enumerate(all_results[:10], 1):
            # Определяем иконку в зависимости от типа
            if file_info.get('is_directory') or file_info.get('category') == 'directory':
                icon = '📁'
            else:
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
    Открытие файла системным приложением через ассоциированную программу
    
    Args:
        file_path: Путь к файлу для открытия
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        from ..utils.system_utils import is_system_directory
        
        # Проверяем, что файл существует
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
        
        # Проверяем только, что путь не является системной директорией (для безопасности)
        # Для открытия файлов не требуется проверка is_safe_path, так как открытие не изменяет файл
        abs_path = os.path.abspath(file_path)
        if is_system_directory(os.path.dirname(abs_path)):
            return {
                "error": True,
                "message": f"❌ **Доступ к файлу в системной директории запрещен:** {file_path}"
            }
        
        # Открываем файл через ассоциированное приложение
        try:
            if IS_WINDOWS:
                # Используем os.startfile для Windows - автоматически использует ассоциированное приложение
                os.startfile(file_path)
            else:
                # Для Linux/Mac используем xdg-open или open
                import subprocess
                if shutil.which('xdg-open'):
                    subprocess.Popen(['xdg-open', file_path])
                elif shutil.which('open'):
                    subprocess.Popen(['open', file_path])
                else:
                    return {
                        "error": True,
                        "message": "❌ **Не найдена программа для открытия файлов**"
                    }
            
            return {
                "success": True,
                "message": f"✅ **Файл открыт:** `{os.path.basename(file_path)}`\n\n📁 **Путь:** {file_path}",
                "file_path": file_path,
                "file_name": os.path.basename(file_path)
            }
            
        except Exception as e:
            # Если os.startfile не сработал, пробуем через subprocess
            try:
                import subprocess
                if IS_WINDOWS:
                    subprocess.Popen(['start', '', file_path], shell=True)
                else:
                    if shutil.which('xdg-open'):
                        subprocess.Popen(['xdg-open', file_path])
                    elif shutil.which('open'):
                        subprocess.Popen(['open', file_path])
                
                return {
                    "success": True,
                    "message": f"✅ **Файл открыт:** `{os.path.basename(file_path)}`\n\n📁 **Путь:** {file_path}",
                    "file_path": file_path,
                    "file_name": os.path.basename(file_path)
                }
            except Exception as e2:
                return {
                    "error": True,
                    "message": f"❌ **Ошибка открытия файла:** {str(e2)}"
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
        file_path: Путь к файлу для чтения (может быть относительным путем от папки пользователя)
        user_id: Идентификатор пользователя (необязательно, также берется из state)
    """
    try:
        # Получаем user_id из state, если не указан явно
        effective_user_id = None
        if state:
            state_user_id = state.get("user_id")
            if state_user_id and state_user_id not in ["default_user", "anonymous", "guest", ""]:
                effective_user_id = state_user_id
                user_id = state_user_id
        elif user_id and user_id not in ["default_user", "anonymous", "guest", ""]:
            effective_user_id = user_id
        
        logger.info(f"[read_file] Ищем файл: {file_path}, user_id: {effective_user_id}")
        
        # Используем resolve_file_path для поиска файла с учетом user_id и нормализации
        resolved_path = None
        actual_file_path = file_path
        
        try:
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../repl/app"))
            from user_files_utils import resolve_file_path
            
            resolved_path = resolve_file_path(file_path, effective_user_id)
            
            if resolved_path:
                logger.info(f"[read_file] resolve_file_path вернул: {resolved_path}, exists: {resolved_path.exists()}")
                # Если файл найден через resolve_file_path, используем его
                if resolved_path.exists():
                    actual_file_path = str(resolved_path)
                    logger.info(f"[read_file] Файл найден: {actual_file_path}")
                else:
                    logger.warning(f"[read_file] Файл не существует по пути: {resolved_path}")
            else:
                logger.warning(f"[read_file] resolve_file_path вернул None для пути: {file_path}")
        except ImportError as e:
            # Fallback: пробуем найти файл вручную
            logger.warning(f"[read_file] Модуль user_files_utils недоступен: {e}, используем исходный путь: {file_path}")
        except Exception as e:
            logger.warning(f"[read_file] Ошибка при разрешении пути файла {file_path}: {e}, используем исходный путь")
        
        # Проверяем существование файла перед чтением
        if not os.path.exists(actual_file_path):
            logger.error(f"[read_file] Файл не существует: {actual_file_path}")
            # Пробуем найти файл в других местах
            potential_paths = [
                actual_file_path,
                os.path.join(os.environ.get("FILES_DIR", "files"), actual_file_path.lstrip("/")),
            ]
            if effective_user_id:
                potential_paths.insert(0, os.path.join(os.environ.get("FILES_DIR", "files"), effective_user_id, os.path.basename(actual_file_path)))
            
            for path in potential_paths:
                if os.path.exists(path):
                    logger.info(f"[read_file] Файл найден по альтернативному пути: {path}")
                    actual_file_path = path
                    break
            else:
                return {
                    "error": True,
                    "message": f"Файл '{file_path}' не существует. Проверенные пути: {potential_paths}"
                }
        
        content = safe_read_file(actual_file_path)
        
        # Проверяем, не вернулась ли ошибка
        if content.startswith("❌"):
            logger.error(f"[read_file] Ошибка чтения файла: {content}")
            return {
                "error": True,
                "message": content
            }
        
        logger.info(f"[read_file] Файл успешно прочитан: {actual_file_path}")
        return {
            "success": True,
            "message": content,
            "file_path": actual_file_path,
            "file_name": os.path.basename(actual_file_path)
        }
        
    except Exception as e:
        logger.error(f"[read_file] Критическая ошибка чтения файла {file_path}: {e}", exc_info=True)
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
        
        # Если директория явно указана, проверяем только, что это не системная директория
        from ..utils.system_utils import is_system_directory
        if is_system_directory(directory):
            return {
                "error": True,
                "message": f"❌ **Доступ к системной директории '{directory}' запрещен по соображениям безопасности**"
            }
        
        # Проверяем, что директория существует
        if not os.path.exists(directory):
            return {
                "error": True,
                "message": f"❌ **Директория '{directory}' не существует**"
            }
        
        if not os.path.isdir(directory):
            return {
                "error": True,
                "message": f"❌ **Путь '{directory}' не является директорией**"
            }
        
        # Используем get_directory_contents, но с пропуском проверки безопасности для явно указанных путей
        # Для этого нужно модифицировать get_directory_contents или использовать обходной путь
        # Пока используем прямое чтение директории, если путь не проходит is_safe_path
        if not is_safe_path(directory):
            # Если путь не безопасный, но не системный, читаем напрямую
            try:
                entries = os.listdir(directory)
                contents = []
                for entry in sorted(entries):
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
                return {
                    "error": True,
                    "message": f"❌ **Нет прав доступа к директории '{directory}'**"
                }
        else:
            contents = get_directory_contents(directory, show_hidden)
        
        # Проверяем на ошибки
        if contents and len(contents) > 0 and "error" in contents[0]:
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
