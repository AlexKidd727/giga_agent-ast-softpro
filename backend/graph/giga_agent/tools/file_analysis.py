"""
Инструменты для отправки файлов на анализ в LLM и REPL Jupyter
с изоляцией по user_id
"""

import os
import json
import logging
import base64
import mimetypes
from pathlib import Path
from typing import Annotated, Optional, List, Dict, Any
from io import BytesIO

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import Field

logger = logging.getLogger(__name__)

# Путь к папке с файлами проекта
FILES_DIR = os.getenv("FILES_DIR", "/files")

# Импортируем утилиты для работы с файлами пользователей
try:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../repl/app"))
    from user_files_utils import resolve_file_path, get_user_files_dir, get_user_file_path
except ImportError:
    # Fallback если модуль недоступен
    def resolve_file_path(file_path, user_id=None):
        clean_path = file_path.lstrip("/")
        potential_paths = [
            os.path.join(FILES_DIR, clean_path),
            file_path,
            os.path.abspath(file_path),
        ]
        if user_id:
            potential_paths.insert(0, os.path.join(FILES_DIR, user_id, os.path.basename(clean_path)))
        for path in potential_paths:
            if os.path.exists(path):
                return Path(path)
        return None
    
    def get_user_files_dir(user_id):
        if user_id:
            return Path(FILES_DIR) / user_id
        return Path(FILES_DIR)
    
    def get_user_file_path(user_id, filename):
        if user_id:
            return Path(FILES_DIR) / user_id / filename
        return Path(FILES_DIR) / filename

# Импортируем утилиты для работы с REPL
try:
    from giga_agent.utils.jupyter import REPLUploader, RunUploadFile, JupyterClient
    from giga_agent.tools.document_reader import read_document
except ImportError:
    REPLUploader = None
    RunUploadFile = None
    JupyterClient = None
    read_document = None
    logger.warning("REPL утилиты недоступны, некоторые функции могут не работать")


@tool(parse_docstring=True)
async def send_file_to_repl(
    file_path: Annotated[
        str,
        Field(description="Путь к файлу для отправки в REPL. Может быть локальным путем или относительным путем от папки пользователя"),
    ],
    target_path: Annotated[
        Optional[str],
        Field(
            description="Путь назначения в REPL (относительно папки пользователя в REPL). Если не указан, используется имя исходного файла",
            default=None
        ),
    ] = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Отправляет файл в REPL Jupyter для анализа и работы с данными.
    Файл будет доступен в изолированной среде пользователя в REPL.
    
    Args:
        file_path: Путь к файлу (локальный путь или относительный путь от папки пользователя)
        target_path: Путь назначения в REPL (относительно папки пользователя). Если не указан, используется имя исходного файла
    
    Returns:
        JSON строка с информацией о результате:
        {
            "success": true/false,
            "file_path": путь к файлу в REPL,
            "message": описание результата
        }
    
    Examples:
        - send_file_to_repl("data.csv")
        - send_file_to_repl("740cd143-0353-4360-a3d6-a8cb86e00ef6/data.csv", target_path="analysis/data.csv")
    """
    import json
    
    if not REPLUploader or not RunUploadFile:
        return json.dumps({
            "success": False,
            "file_path": None,
            "message": "REPL утилиты недоступны. Убедитесь, что сервис REPL запущен."
        }, ensure_ascii=False)
    
    try:
        # Получаем user_id из state
        user_id = None
        thread_id = None
        if state:
            user_id = state.get("user_id")
            thread_id = state.get("thread_id")
            if user_id in ["default_user", "anonymous", "guest", ""]:
                user_id = None
        
        if not thread_id:
            return json.dumps({
                "success": False,
                "file_path": None,
                "message": "thread_id не найден в state. Файлы можно отправлять только в контексте активной сессии."
            }, ensure_ascii=False)
        
        # Разрешаем путь к файлу
        resolved_path = resolve_file_path(file_path, user_id)
        
        if not resolved_path or not resolved_path.exists():
            # Пробуем найти файл в других местах
            clean_path = file_path.lstrip("/")
            potential_paths = []
            
            # Если путь содержит user_id в начале
            if "/" in clean_path:
                parts = clean_path.split("/", 1)
                if len(parts) == 2:
                    path_user_id, filename = parts
                    if len(path_user_id) > 20:  # UUID обычно длиннее 20 символов
                        potential_paths.append(Path(FILES_DIR) / path_user_id / filename)
                        if user_id and user_id != path_user_id:
                            potential_paths.append(Path(FILES_DIR) / user_id / filename)
            
            potential_paths.extend([
                Path(FILES_DIR) / clean_path,
                Path(file_path),
            ])
            
            if os.path.isabs(file_path):
                potential_paths.append(Path(file_path))
            
            if user_id:
                if "/" in clean_path:
                    potential_paths.insert(0, Path(FILES_DIR) / user_id / clean_path)
                else:
                    filename = os.path.basename(clean_path)
                    potential_paths.insert(0, Path(FILES_DIR) / user_id / filename)
            
            # Пробуем нормализованные варианты
            try:
                from user_files_utils import normalize_filename
                normalized_path = normalize_filename(clean_path)
                if normalized_path != clean_path:
                    potential_paths.append(Path(FILES_DIR) / normalized_path)
                    if user_id:
                        filename = os.path.basename(normalized_path)
                        potential_paths.append(Path(FILES_DIR) / user_id / filename)
                        if "/" in clean_path:
                            potential_paths.insert(0, Path(FILES_DIR) / user_id / normalized_path)
                        else:
                            potential_paths.insert(0, Path(FILES_DIR) / user_id / filename)
            except:
                pass
            
            resolved_path = None
            for path in potential_paths:
                try:
                    normalized_path = path.resolve() if path.is_absolute() else path
                    if normalized_path.exists():
                        resolved_path = normalized_path
                        break
                except (OSError, ValueError):
                    continue
            
            if not resolved_path:
                return json.dumps({
                    "success": False,
                    "file_path": None,
                    "message": f"Файл не найден: {file_path}"
                }, ensure_ascii=False)
        
        # Читаем содержимое файла
        try:
            with open(resolved_path, 'rb') as f:
                file_content = f.read()
        except Exception as e:
            return json.dumps({
                "success": False,
                "file_path": None,
                "message": f"Ошибка при чтении файла: {str(e)}"
            }, ensure_ascii=False)
        
        # Определяем тип файла
        file_ext = resolved_path.suffix.lower()
        file_type = "other"
        if file_ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg']:
            file_type = "image"
        elif file_ext in ['.txt', '.csv', '.json', '.xml', '.md']:
            file_type = "text"
        elif file_ext in ['.html', '.htm']:
            file_type = "html"
        elif file_ext in ['.mp3', '.wav', '.ogg', '.flac']:
            file_type = "audio"
        
        # Определяем путь назначения
        if target_path:
            repl_path = target_path.lstrip("/")
        else:
            # Используем имя файла, но с префиксом user_id для изоляции
            if user_id:
                repl_path = f"{user_id}/{resolved_path.name}"
            else:
                repl_path = resolved_path.name
        
        # Создаем объект для загрузки
        upload_file = RunUploadFile(
            path=repl_path,
            file_type=file_type,
            content=file_content
        )
        
        # Загружаем файл в REPL
        uploader = REPLUploader()
        uploaded_files = await uploader.upload_run_files([upload_file], thread_id)
        
        if uploaded_files:
            uploaded_file = uploaded_files[0]
            return json.dumps({
                "success": True,
                "file_path": uploaded_file.get("path", repl_path),
                "message": f"Файл успешно отправлен в REPL: {repl_path}"
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "success": False,
                "file_path": None,
                "message": "Не удалось загрузить файл в REPL"
            }, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"Ошибка при отправке файла в REPL: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "success": False,
            "file_path": None,
            "message": error_msg
        }, ensure_ascii=False)


@tool(parse_docstring=True)
async def send_file_to_llm(
    file_path: Annotated[
        str,
        Field(description="Путь к файлу для анализа в LLM. Может быть локальным путем или относительным путем от папки пользователя"),
    ],
    analysis_query: Annotated[
        Optional[str],
        Field(
            description="Вопрос или задача для анализа файла. Если не указан, будет выполнен общий анализ содержимого",
            default=None
        ),
    ] = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Отправляет файл на анализ в LLM. Файл читается и отправляется в LLM для анализа.
    Поддерживаются различные форматы файлов (текстовые, документы, изображения и т.д.).
    
    Args:
        file_path: Путь к файлу (локальный путь или относительный путь от папки пользователя)
        analysis_query: Вопрос или задача для анализа файла. Если не указан, будет выполнен общий анализ
    
    Returns:
        JSON строка с результатом анализа:
        {
            "success": true/false,
            "file_path": путь к файлу,
            "content_preview": превью содержимого (первые N символов),
            "analysis": результат анализа от LLM,
            "message": описание результата
        }
    
    Examples:
        - send_file_to_llm("document.pdf")
        - send_file_to_llm("data.csv", analysis_query="Проанализируй структуру данных и найди аномалии")
    """
    import json
    
    if not read_document:
        return json.dumps({
            "success": False,
            "file_path": None,
            "content_preview": None,
            "analysis": None,
            "message": "Инструмент read_document недоступен"
        }, ensure_ascii=False)
    
    try:
        # Получаем user_id из state
        user_id = None
        if state:
            user_id = state.get("user_id")
            if user_id in ["default_user", "anonymous", "guest", ""]:
                user_id = None
        
        # Разрешаем путь к файлу
        resolved_path = resolve_file_path(file_path, user_id)
        
        if not resolved_path or not resolved_path.exists():
            # Пробуем найти файл в других местах (та же логика, что и в send_file_to_repl)
            clean_path = file_path.lstrip("/")
            potential_paths = []
            
            if "/" in clean_path:
                parts = clean_path.split("/", 1)
                if len(parts) == 2:
                    path_user_id, filename = parts
                    if len(path_user_id) > 20:
                        potential_paths.append(Path(FILES_DIR) / path_user_id / filename)
                        if user_id and user_id != path_user_id:
                            potential_paths.append(Path(FILES_DIR) / user_id / filename)
            
            potential_paths.extend([
                Path(FILES_DIR) / clean_path,
                Path(file_path),
            ])
            
            if os.path.isabs(file_path):
                potential_paths.append(Path(file_path))
            
            if user_id:
                if "/" in clean_path:
                    potential_paths.insert(0, Path(FILES_DIR) / user_id / clean_path)
                else:
                    filename = os.path.basename(clean_path)
                    potential_paths.insert(0, Path(FILES_DIR) / user_id / filename)
            
            # Пробуем нормализованные варианты
            try:
                from user_files_utils import normalize_filename
                normalized_path = normalize_filename(clean_path)
                if normalized_path != clean_path:
                    potential_paths.append(Path(FILES_DIR) / normalized_path)
                    if user_id:
                        filename = os.path.basename(normalized_path)
                        potential_paths.append(Path(FILES_DIR) / user_id / filename)
                        if "/" in clean_path:
                            potential_paths.insert(0, Path(FILES_DIR) / user_id / normalized_path)
                        else:
                            potential_paths.insert(0, Path(FILES_DIR) / user_id / filename)
            except:
                pass
            
            resolved_path = None
            for path in potential_paths:
                try:
                    normalized_path = path.resolve() if path.is_absolute() else path
                    if normalized_path.exists():
                        resolved_path = normalized_path
                        break
                except (OSError, ValueError):
                    continue
            
            if not resolved_path:
                return json.dumps({
                    "success": False,
                    "file_path": file_path,
                    "content_preview": None,
                    "analysis": None,
                    "message": f"Файл не найден: {file_path}"
                }, ensure_ascii=False)
        
        # Читаем содержимое файла с помощью read_document
        try:
            # Используем read_document для чтения различных форматов
            document_content = await read_document(str(resolved_path), state=state)
            
            # Если read_document вернул строку, используем её
            if isinstance(document_content, str):
                content_text = document_content
            else:
                # Если это dict, пытаемся извлечь текст
                content_text = str(document_content)
            
            # Ограничиваем размер превью
            content_preview = content_text[:1000] + "..." if len(content_text) > 1000 else content_text
            
            # Если указан запрос для анализа, используем LLM для анализа
            if analysis_query:
                from giga_agent.utils.llm import load_llm
                
                # Загружаем LLM с учетом user_id
                llm = load_llm(user_id=user_id)
                
                # Формируем промпт для анализа
                prompt = f"""Проанализируй следующий файл и ответь на вопрос пользователя.

Вопрос пользователя: {analysis_query}

Содержимое файла ({resolved_path.name}):
{content_text[:50000]}  # Ограничиваем размер для LLM

Проведи детальный анализ и ответь на вопрос пользователя."""
                
                # Получаем анализ от LLM
                analysis_result = await llm.ainvoke(prompt)
                
                if hasattr(analysis_result, 'content'):
                    analysis = analysis_result.content
                else:
                    analysis = str(analysis_result)
            else:
                # Общий анализ содержимого
                analysis = f"Файл успешно прочитан. Размер: {len(content_text)} символов. Тип: {resolved_path.suffix}"
            
            return json.dumps({
                "success": True,
                "file_path": str(resolved_path),
                "content_preview": content_preview,
                "analysis": analysis,
                "message": f"Файл успешно проанализирован: {resolved_path.name}"
            }, ensure_ascii=False)
            
        except Exception as e:
            error_msg = f"Ошибка при чтении файла: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return json.dumps({
                "success": False,
                "file_path": str(resolved_path),
                "content_preview": None,
                "analysis": None,
                "message": error_msg
            }, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"Ошибка при отправке файла на анализ в LLM: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "success": False,
            "file_path": file_path,
            "content_preview": None,
            "analysis": None,
            "message": error_msg
        }, ensure_ascii=False)


@tool(parse_docstring=True)
async def send_archive_files_to_repl(
    archive_path: Annotated[
        str,
        Field(description="Путь к архиву для извлечения и отправки файлов в REPL"),
    ],
    extract_to: Annotated[
        Optional[str],
        Field(
            description="Папка для распаковки (относительно папки пользователя). Если не указана, создается папка с именем архива",
            default=None
        ),
    ] = None,
    file_pattern: Annotated[
        Optional[str],
        Field(
            description="Шаблон для фильтрации файлов (например, '*.csv', '*.json'). Если не указан, отправляются все файлы",
            default=None
        ),
    ] = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Извлекает архив и отправляет все файлы (или отфильтрованные по шаблону) в REPL Jupyter.
    Удобно для массовой загрузки файлов из архива в REPL для анализа.
    
    Args:
        archive_path: Путь к архиву
        extract_to: Папка для распаковки (относительно папки пользователя)
        file_pattern: Шаблон для фильтрации файлов (например, '*.csv', '*.json')
    
    Returns:
        JSON строка с информацией о загруженных файлах:
        {
            "success": true/false,
            "extracted_files": [список путей к распакованным файлам],
            "uploaded_files": [список путей к загруженным в REPL файлам],
            "message": описание результата
        }
    
    Examples:
        - send_archive_files_to_repl("data.zip")
        - send_archive_files_to_repl("archive.zip", file_pattern="*.csv")
    """
    import json
    import fnmatch
    
    try:
        # Сначала извлекаем архив
        from giga_agent.tools.archive_tools import extract_archive
        
        extract_result = await extract_archive(archive_path, extract_to, state)
        extract_data = json.loads(extract_result)
        
        if not extract_data.get("success"):
            return json.dumps({
                "success": False,
                "extracted_files": [],
                "uploaded_files": [],
                "message": f"Не удалось извлечь архив: {extract_data.get('message', 'Неизвестная ошибка')}"
            }, ensure_ascii=False)
        
        extracted_files = extract_data.get("extracted_files", [])
        extract_dir = extract_data.get("extract_dir")
        
        # Фильтруем файлы по шаблону, если указан
        if file_pattern:
            filtered_files = [f for f in extracted_files if fnmatch.fnmatch(os.path.basename(f), file_pattern)]
        else:
            filtered_files = extracted_files
        
        # Отправляем каждый файл в REPL
        uploaded_files = []
        errors = []
        
        for file_rel_path in filtered_files:
            try:
                # Формируем полный путь к файлу
                if extract_dir:
                    full_path = os.path.join(FILES_DIR, extract_dir, file_rel_path)
                else:
                    full_path = os.path.join(FILES_DIR, file_rel_path)
                
                # Отправляем файл в REPL
                upload_result = await send_file_to_repl(full_path, state=state)
                upload_data = json.loads(upload_result)
                
                if upload_data.get("success"):
                    uploaded_files.append(upload_data.get("file_path"))
                else:
                    errors.append(f"{file_rel_path}: {upload_data.get('message')}")
            except Exception as e:
                errors.append(f"{file_rel_path}: {str(e)}")
        
        return json.dumps({
            "success": True,
            "extracted_files": extracted_files,
            "uploaded_files": uploaded_files,
            "errors": errors if errors else None,
            "message": f"Загружено {len(uploaded_files)} из {len(filtered_files)} файлов в REPL"
        }, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"Ошибка при отправке файлов из архива в REPL: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "success": False,
            "extracted_files": [],
            "uploaded_files": [],
            "message": error_msg
        }, ensure_ascii=False)
