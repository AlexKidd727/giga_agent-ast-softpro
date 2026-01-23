"""
Инструменты для работы с архивами (ZIP, RAR, TAR)
"""

import os
import logging
import zipfile
import tarfile
import shutil
from pathlib import Path
from typing import Annotated, Optional, List, Dict
from tempfile import TemporaryDirectory

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
    from user_files_utils import resolve_file_path, get_user_files_dir, get_user_file_path, normalize_filename
except ImportError:
    # Fallback если модуль недоступен
    def normalize_filename(filename):
        import re
        normalized = re.sub(r'\s+\(', '(', filename)
        normalized = re.sub(r'\(\s+', '(', normalized)
        normalized = re.sub(r'\s+\)', ')', normalized)
        return normalized
    
    def resolve_file_path(file_path, user_id=None):
        # Убираем начальный слеш если есть
        clean_path = file_path.lstrip("/")
        
        # Пробуем разные варианты путей
        potential_paths = [
            os.path.join(FILES_DIR, clean_path),  # Относительно FILES_DIR
            file_path,  # Как есть
            os.path.abspath(file_path),  # Абсолютный путь
        ]
        
        # Если есть user_id и путь содержит его, пробуем найти файл
        if user_id and user_id in clean_path:
            potential_paths.insert(0, os.path.join(FILES_DIR, clean_path))
        
        # Также пробуем нормализованные варианты (для совместимости с загруженными файлами)
        normalized_clean_path = normalize_filename(clean_path)
        if normalized_clean_path != clean_path:
            potential_paths.append(os.path.join(FILES_DIR, normalized_clean_path))
            if user_id:
                filename = os.path.basename(normalized_clean_path)
                potential_paths.append(os.path.join(FILES_DIR, user_id, filename))
        
        # Проверяем каждый путь
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


@tool(parse_docstring=True)
async def list_archive_contents(
    file_path: Annotated[
        str,
        Field(description="Путь к архиву для просмотра содержимого. Может быть локальным путем или относительным путем от папки пользователя"),
    ],
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Показывает содержимое архива (ZIP, RAR, TAR, TAR.GZ, TAR.BZ2) без распаковки.
    
    ВАЖНО: Используйте этот инструмент для просмотра содержимого архивов (.zip, .rar, .tar и т.д.).
    Не используйте list_directory или read_file для архивов - они не работают с архивами.
    
    Поддерживаемые форматы:
    - ZIP (.zip)
    - TAR (.tar)
    - TAR.GZ (.tar.gz, .tgz)
    - TAR.BZ2 (.tar.bz2)
    - RAR (.rar) - требует установки unrar или rarfile
    
    Args:
        file_path: Путь к архиву (локальный путь или относительный путь от папки пользователя, например "tasks.zip" или "740cd143-0353-4360-a3d6-a8cb86e00ef6/tasks.zip")
    
    Returns:
        JSON строка с информацией о файлах в архиве:
        {
            "success": true/false,
            "archive_path": путь к архиву,
            "total_files": количество файлов,
            "total_size": общий размер в байтах,
            "files": [
                {
                    "name": имя файла,
                    "size": размер в байтах,
                    "compressed_size": сжатый размер (если доступен),
                    "is_dir": является ли директорией,
                    "date": дата модификации
                }
            ],
            "message": описание результата
        }
    
    Examples:
        - list_archive_contents("project.zip")
        - list_archive_contents("740cd143-0353-4360-a3d6-a8cb86e00ef6/archive.zip")
        - list_archive_contents("740cd143-0353-4360-a3d6-a8cb86e00ef6/archive (5).zip")  # Поддерживаются пробелы и скобки
    """
    import json
    from datetime import datetime
    
    try:
        # Убираем кавычки из пути, если они есть (проблема парсинга LLM)
        file_path = file_path.strip().strip("'\"")
        
        # Получаем user_id из state
        user_id = None
        if state:
            user_id = state.get("user_id")
            if user_id in ["default_user", "anonymous", "guest", ""]:
                user_id = None
        
        # Разрешаем путь к архиву
        # Сначала пробуем использовать resolve_file_path
        resolved_path = resolve_file_path(file_path, user_id)
        
        if not resolved_path or not resolved_path.exists():
            # Пробуем найти файл в других местах
            clean_path = file_path.lstrip("/")
            potential_paths = []
            
            # Если путь содержит user_id в начале (например, "740cd143-0353-4360-a3d6-a8cb86e00ef6/archive (3).zip")
            if "/" in clean_path:
                parts = clean_path.split("/", 1)
                if len(parts) == 2:
                    path_user_id, filename = parts
                    # Если первая часть похожа на UUID (user_id), пробуем найти файл в его папке
                    if len(path_user_id) > 20:  # UUID обычно длиннее 20 символов
                        # Пробуем путь с user_id из пути
                        potential_paths.append(Path(FILES_DIR) / path_user_id / filename)
                        # Также пробуем с указанным user_id из state
                        if user_id and user_id != path_user_id:
                            potential_paths.append(Path(FILES_DIR) / user_id / filename)
            
            # Добавляем стандартные варианты путей
            potential_paths.extend([
                Path(FILES_DIR) / clean_path,  # Относительно FILES_DIR
                Path(file_path),  # Как есть (может быть относительным)
            ])
            
            # Если путь выглядит как абсолютный, пробуем его
            if os.path.isabs(file_path):
                potential_paths.append(Path(file_path))
            
            # Если есть user_id, пробуем найти в его папке
            if user_id:
                # Если путь содержит подпапки, используем весь путь относительно папки пользователя
                if "/" in clean_path:
                    potential_paths.insert(0, Path(FILES_DIR) / user_id / clean_path)
                else:
                    # Иначе используем только имя файла
                    filename = os.path.basename(clean_path)
                    potential_paths.insert(0, Path(FILES_DIR) / user_id / filename)
            
            # Пробуем нормализованные варианты
            try:
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
                    # Нормализуем путь и проверяем существование
                    normalized_path = path.resolve() if path.is_absolute() else path
                    if normalized_path.exists():
                        resolved_path = normalized_path
                        break
                except (OSError, ValueError):
                    # Пропускаем невалидные пути
                    continue
            
            if not resolved_path:
                return json.dumps({
                    "success": False,
                    "archive_path": file_path,
                    "total_files": 0,
                    "total_size": 0,
                    "files": [],
                    "message": f"Архив не найден: {file_path}. Проверьте правильность пути. Убедитесь, что файл находится в папке пользователя или в общей папке /files."
                }, ensure_ascii=False)
        
        archive_path = str(resolved_path)
        
        # Определяем формат архива
        file_ext = resolved_path.suffix.lower()
        
        # Получаем список файлов в зависимости от формата
        files_info = []
        total_size = 0
        
        if file_ext == '.zip':
            files_info, total_size = await _list_zip_contents(archive_path)
        elif file_ext in ['.tar']:
            files_info, total_size = await _list_tar_contents(archive_path)
        elif file_ext in ['.gz', '.tgz'] or resolved_path.name.endswith('.tar.gz'):
            files_info, total_size = await _list_tar_gz_contents(archive_path)
        elif file_ext == '.bz2' or resolved_path.name.endswith('.tar.bz2'):
            files_info, total_size = await _list_tar_bz2_contents(archive_path)
        elif file_ext == '.rar':
            files_info, total_size = await _list_rar_contents(archive_path)
        else:
            return json.dumps({
                "success": False,
                "archive_path": archive_path,
                "total_files": 0,
                "total_size": 0,
                "files": [],
                "message": f"Неподдерживаемый формат архива: {file_ext}. Поддерживаются: ZIP, TAR, TAR.GZ, TAR.BZ2, RAR"
            }, ensure_ascii=False)
        
        return json.dumps({
            "success": True,
            "archive_path": archive_path,
            "total_files": len(files_info),
            "total_size": total_size,
            "files": files_info,
            "message": f"Архив содержит {len(files_info)} файлов(а), общий размер: {total_size} байт"
        }, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"Ошибка при чтении архива {file_path}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "success": False,
            "archive_path": file_path,
            "total_files": 0,
            "total_size": 0,
            "files": [],
            "message": error_msg
        }, ensure_ascii=False)


@tool(parse_docstring=True)
async def extract_archive(
    file_path: Annotated[
        str,
        Field(description="Путь к архиву для распаковки. Может быть локальным путем или относительным путем от папки пользователя"),
    ],
    extract_to: Annotated[
        Optional[str],
        Field(
            description="Папка для распаковки. Может быть абсолютным путем (начинается с /) или относительным путем от папки пользователя. Если не указана, создается папка с именем архива",
            default=None
        ),
    ] = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Распаковывает архив (ZIP, RAR, TAR, TAR.GZ, TAR.BZ2) и делает файлы доступными для анализа.
    
    ВАЖНО: Используйте этот инструмент для распаковки архивов (.zip, .rar, .tar и т.д.).
    После распаковки используйте read_file или read_document для чтения распакованных файлов.
    
    Поддерживаемые форматы:
    - ZIP (.zip)
    - TAR (.tar)
    - TAR.GZ (.tar.gz, .tgz)
    - TAR.BZ2 (.tar.bz2)
    - RAR (.rar) - требует установки unrar или rarfile
    
    Распакованные файлы сохраняются в папке пользователя и доступны для дальнейшего анализа.
    
    Args:
        file_path: Путь к архиву (локальный путь или относительный путь от папки пользователя, например "tasks.zip" или "740cd143-0353-4360-a3d6-a8cb86e00ef6/tasks.zip")
        extract_to: Папка для распаковки. Может быть абсолютным путем (начинается с /) или относительным путем от папки пользователя. Если не указана, создается папка с именем архива без расширения
    
    Returns:
        JSON строка с информацией о распакованных файлах:
        {
            "success": true/false,
            "extracted_files": [список путей к распакованным файлам],
            "extract_dir": путь к папке с распакованными файлами,
            "total_files": количество файлов,
            "message": описание результата
        }
    
    Examples:
        - extract_archive("project.zip")
        - extract_archive("/files/my_project.zip", extract_to="my_project")
        - extract_archive("archive.zip", extract_to="/home/jupyter")  # Абсолютный путь
        - extract_archive("740cd143-0353-4360-a3d6-a8cb86e00ef6/archive (5).zip")  # Поддерживаются пробелы и скобки
    """
    import json
    
    try:
        # Убираем кавычки из пути, если они есть (проблема парсинга LLM)
        file_path = file_path.strip().strip("'\"")
        
        # Получаем user_id из state
        user_id = None
        if state:
            user_id = state.get("user_id")
            if user_id in ["default_user", "anonymous", "guest", ""]:
                user_id = None
        
        # Разрешаем путь к архиву
        # Сначала пробуем использовать resolve_file_path
        resolved_path = resolve_file_path(file_path, user_id)
        
        if not resolved_path or not resolved_path.exists():
            # Пробуем найти файл в других местах
            clean_path = file_path.lstrip("/")
            potential_paths = []
            
            # Если путь содержит user_id в начале (например, "740cd143-0353-4360-a3d6-a8cb86e00ef6/archive (3).zip")
            if "/" in clean_path:
                parts = clean_path.split("/", 1)
                if len(parts) == 2:
                    path_user_id, filename = parts
                    # Если первая часть похожа на UUID (user_id), пробуем найти файл в его папке
                    if len(path_user_id) > 20:  # UUID обычно длиннее 20 символов
                        # Пробуем путь с user_id из пути
                        potential_paths.append(Path(FILES_DIR) / path_user_id / filename)
                        # Также пробуем с указанным user_id из state
                        if user_id and user_id != path_user_id:
                            potential_paths.append(Path(FILES_DIR) / user_id / filename)
            
            # Добавляем стандартные варианты путей
            potential_paths.extend([
                Path(FILES_DIR) / clean_path,  # Относительно FILES_DIR
                Path(file_path),  # Как есть (может быть относительным)
            ])
            
            # Если путь выглядит как абсолютный, пробуем его
            if os.path.isabs(file_path):
                potential_paths.append(Path(file_path))
            
            # Если есть user_id, пробуем найти в его папке
            if user_id:
                # Если путь содержит подпапки, используем весь путь относительно папки пользователя
                if "/" in clean_path:
                    potential_paths.insert(0, Path(FILES_DIR) / user_id / clean_path)
                else:
                    # Иначе используем только имя файла
                    filename = os.path.basename(clean_path)
                    potential_paths.insert(0, Path(FILES_DIR) / user_id / filename)
            
            # Пробуем нормализованные варианты
            try:
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
                    # Нормализуем путь и проверяем существование
                    normalized_path = path.resolve() if path.is_absolute() else path
                    if normalized_path.exists():
                        resolved_path = normalized_path
                        break
                except (OSError, ValueError):
                    # Пропускаем невалидные пути
                    continue
            
            if not resolved_path:
                return json.dumps({
                    "success": False,
                    "extracted_files": [],
                    "extract_dir": None,
                    "total_files": 0,
                    "message": f"Архив не найден: {file_path}. Проверьте правильность пути."
                }, ensure_ascii=False)
        
        archive_path = str(resolved_path)
        
        # Определяем формат архива
        file_ext = resolved_path.suffix.lower()
        archive_name = resolved_path.stem  # Имя без расширения
        
        # Определяем папку для распаковки
        if extract_to:
            # Если extract_to начинается с /, это абсолютный путь
            if extract_to.startswith('/'):
                extract_dir = Path(extract_to)
            elif user_id:
                extract_dir = get_user_files_dir(user_id) / extract_to.lstrip('/')
            else:
                extract_dir = Path(FILES_DIR) / extract_to.lstrip('/')
        else:
            # Создаем папку с именем архива
            if user_id:
                extract_dir = get_user_files_dir(user_id) / archive_name
            else:
                extract_dir = Path(FILES_DIR) / archive_name
        
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        extracted_files = []
        
        # Распаковываем в зависимости от формата
        if file_ext == '.zip':
            extracted_files = await _extract_zip(archive_path, extract_dir)
        elif file_ext in ['.tar']:
            extracted_files = await _extract_tar(archive_path, extract_dir)
        elif file_ext in ['.gz', '.tgz'] or resolved_path.name.endswith('.tar.gz'):
            extracted_files = await _extract_tar_gz(archive_path, extract_dir)
        elif file_ext == '.bz2' or resolved_path.name.endswith('.tar.bz2'):
            extracted_files = await _extract_tar_bz2(archive_path, extract_dir)
        elif file_ext == '.rar':
            extracted_files = await _extract_rar(archive_path, extract_dir)
        else:
            return json.dumps({
                "success": False,
                "extracted_files": [],
                "extract_dir": None,
                "total_files": 0,
                "message": f"Неподдерживаемый формат архива: {file_ext}. Поддерживаются: ZIP, TAR, TAR.GZ, TAR.BZ2, RAR"
            }, ensure_ascii=False)
        
        # Нормализуем пути для возврата
        # Если путь находится в FILES_DIR, возвращаем относительный путь
        # Если путь вне FILES_DIR (абсолютный), возвращаем абсолютный путь
        try:
            extract_dir.relative_to(FILES_DIR)
            # Путь внутри FILES_DIR - возвращаем относительный
            relative_extract_dir = os.path.relpath(str(extract_dir), FILES_DIR)
            relative_files = [os.path.relpath(str(f), FILES_DIR) for f in extracted_files]
        except ValueError:
            # Путь вне FILES_DIR - возвращаем абсолютные пути
            relative_extract_dir = str(extract_dir.resolve())
            relative_files = [str(f.resolve()) for f in extracted_files]
        
        return json.dumps({
            "success": True,
            "extracted_files": relative_files,
            "extract_dir": relative_extract_dir,
            "total_files": len(extracted_files),
            "message": f"Архив успешно распакован. Распаковано файлов: {len(extracted_files)}. Папка: {relative_extract_dir}"
        }, ensure_ascii=False)
        
    except Exception as e:
        error_msg = f"Ошибка при распаковке архива {file_path}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "success": False,
            "extracted_files": [],
            "extract_dir": None,
            "total_files": 0,
            "message": error_msg
        }, ensure_ascii=False)


async def _extract_zip(archive_path: str, extract_dir: Path) -> List[Path]:
    """Распаковывает ZIP архив"""
    extracted_files = []
    
    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
        # Получаем список всех файлов
        file_list = zip_ref.namelist()
        
        # Распаковываем все файлы
        for file_info in zip_ref.infolist():
            # Безопасность: проверяем на path traversal
            if '..' in file_info.filename or file_info.filename.startswith('/'):
                logger.warning(f"Пропущен небезопасный путь в архиве: {file_info.filename}")
                continue
            
            # Извлекаем файл
            zip_ref.extract(file_info, extract_dir)
            extracted_path = extract_dir / file_info.filename
            
            if extracted_path.is_file():
                extracted_files.append(extracted_path)
    
    return extracted_files


async def _extract_tar(archive_path: str, extract_dir: Path) -> List[Path]:
    """Распаковывает TAR архив"""
    extracted_files = []
    
    with tarfile.open(archive_path, 'r') as tar_ref:
        # Безопасность: проверяем все пути перед извлечением
        members = []
        for member in tar_ref.getmembers():
            # Проверяем на path traversal
            if '..' in member.name or member.name.startswith('/'):
                logger.warning(f"Пропущен небезопасный путь в архиве: {member.name}")
                continue
            members.append(member)
        
        tar_ref.extractall(extract_dir, members=members)
        
        # Собираем список распакованных файлов
        for member in members:
            extracted_path = extract_dir / member.name
            if extracted_path.is_file():
                extracted_files.append(extracted_path)
    
    return extracted_files


async def _extract_tar_gz(archive_path: str, extract_dir: Path) -> List[Path]:
    """Распаковывает TAR.GZ архив"""
    extracted_files = []
    
    with tarfile.open(archive_path, 'r:gz') as tar_ref:
        members = []
        for member in tar_ref.getmembers():
            if '..' in member.name or member.name.startswith('/'):
                logger.warning(f"Пропущен небезопасный путь в архиве: {member.name}")
                continue
            members.append(member)
        
        tar_ref.extractall(extract_dir, members=members)
        
        for member in members:
            extracted_path = extract_dir / member.name
            if extracted_path.is_file():
                extracted_files.append(extracted_path)
    
    return extracted_files


async def _extract_tar_bz2(archive_path: str, extract_dir: Path) -> List[Path]:
    """Распаковывает TAR.BZ2 архив"""
    extracted_files = []
    
    with tarfile.open(archive_path, 'r:bz2') as tar_ref:
        members = []
        for member in tar_ref.getmembers():
            if '..' in member.name or member.name.startswith('/'):
                logger.warning(f"Пропущен небезопасный путь в архиве: {member.name}")
                continue
            members.append(member)
        
        tar_ref.extractall(extract_dir, members=members)
        
        for member in members:
            extracted_path = extract_dir / member.name
            if extracted_path.is_file():
                extracted_files.append(extracted_path)
    
    return extracted_files


async def _extract_rar(archive_path: str, extract_dir: Path) -> List[Path]:
    """Распаковывает RAR архив"""
    extracted_files = []
    
    try:
        # Пробуем использовать rarfile (Python библиотека)
        try:
            import rarfile
            with rarfile.RarFile(archive_path) as rar_ref:
                for file_info in rar_ref.infolist():
                    if '..' in file_info.filename or file_info.filename.startswith('/'):
                        logger.warning(f"Пропущен небезопасный путь в архиве: {file_info.filename}")
                        continue
                    
                    rar_ref.extract(file_info, extract_dir)
                    extracted_path = extract_dir / file_info.filename
                    if extracted_path.is_file():
                        extracted_files.append(extracted_path)
        except ImportError:
            # Пробуем использовать unrar через командную строку
            import subprocess
            result = subprocess.run(
                ['unrar', 'x', '-o+', archive_path, str(extract_dir)],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                # Пробуем rar вместо unrar
                result = subprocess.run(
                    ['rar', 'x', '-o+', archive_path, str(extract_dir)],
                    capture_output=True,
                    text=True
                )
            
            if result.returncode == 0:
                # Собираем список распакованных файлов
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        extracted_files.append(Path(root) / file)
            else:
                raise Exception(f"Не удалось распаковать RAR архив. Установите unrar или rarfile: pip install rarfile")
    except Exception as e:
        logger.error(f"Ошибка при распаковке RAR: {e}")
        raise Exception(f"Ошибка при распаковке RAR архива: {str(e)}. Установите rarfile: pip install rarfile или unrar")
    
    return extracted_files


# ========== Функции для просмотра содержимого архивов без распаковки ==========

async def _list_zip_contents(archive_path: str) -> tuple[List[Dict], int]:
    """Получает список файлов в ZIP архиве без распаковки"""
    files_info = []
    total_size = 0
    
    try:
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                # Пропускаем небезопасные пути
                if '..' in file_info.filename or file_info.filename.startswith('/'):
                    continue
                
                is_dir = file_info.filename.endswith('/')
                file_size = file_info.file_size
                compressed_size = file_info.compress_size
                
                # Форматируем дату
                date_str = None
                if file_info.date_time:
                    try:
                        date_obj = datetime(*file_info.date_time)
                        date_str = date_obj.isoformat()
                    except:
                        pass
                
                files_info.append({
                    "name": file_info.filename,
                    "size": file_size,
                    "compressed_size": compressed_size,
                    "is_dir": is_dir,
                    "date": date_str
                })
                
                if not is_dir:
                    total_size += file_size
    except Exception as e:
        logger.error(f"Ошибка при чтении ZIP архива: {e}")
        raise
    
    return files_info, total_size


async def _list_tar_contents(archive_path: str) -> tuple[List[Dict], int]:
    """Получает список файлов в TAR архиве без распаковки"""
    files_info = []
    total_size = 0
    
    try:
        with tarfile.open(archive_path, 'r') as tar_ref:
            for member in tar_ref.getmembers():
                # Пропускаем небезопасные пути
                if '..' in member.name or member.name.startswith('/'):
                    continue
                
                is_dir = member.isdir()
                file_size = member.size if member.isfile() else 0
                
                # Форматируем дату
                date_str = None
                if member.mtime:
                    try:
                        date_obj = datetime.fromtimestamp(member.mtime)
                        date_str = date_obj.isoformat()
                    except:
                        pass
                
                files_info.append({
                    "name": member.name,
                    "size": file_size,
                    "compressed_size": None,  # TAR не сжимает, только упаковывает
                    "is_dir": is_dir,
                    "date": date_str
                })
                
                if not is_dir:
                    total_size += file_size
    except Exception as e:
        logger.error(f"Ошибка при чтении TAR архива: {e}")
        raise
    
    return files_info, total_size


async def _list_tar_gz_contents(archive_path: str) -> tuple[List[Dict], int]:
    """Получает список файлов в TAR.GZ архиве без распаковки"""
    files_info = []
    total_size = 0
    
    try:
        with tarfile.open(archive_path, 'r:gz') as tar_ref:
            for member in tar_ref.getmembers():
                # Пропускаем небезопасные пути
                if '..' in member.name or member.name.startswith('/'):
                    continue
                
                is_dir = member.isdir()
                file_size = member.size if member.isfile() else 0
                
                # Форматируем дату
                date_str = None
                if member.mtime:
                    try:
                        date_obj = datetime.fromtimestamp(member.mtime)
                        date_str = date_obj.isoformat()
                    except:
                        pass
                
                files_info.append({
                    "name": member.name,
                    "size": file_size,
                    "compressed_size": None,  # Размер после сжатия gzip не доступен напрямую
                    "is_dir": is_dir,
                    "date": date_str
                })
                
                if not is_dir:
                    total_size += file_size
    except Exception as e:
        logger.error(f"Ошибка при чтении TAR.GZ архива: {e}")
        raise
    
    return files_info, total_size


async def _list_tar_bz2_contents(archive_path: str) -> tuple[List[Dict], int]:
    """Получает список файлов в TAR.BZ2 архиве без распаковки"""
    files_info = []
    total_size = 0
    
    try:
        with tarfile.open(archive_path, 'r:bz2') as tar_ref:
            for member in tar_ref.getmembers():
                # Пропускаем небезопасные пути
                if '..' in member.name or member.name.startswith('/'):
                    continue
                
                is_dir = member.isdir()
                file_size = member.size if member.isfile() else 0
                
                # Форматируем дату
                date_str = None
                if member.mtime:
                    try:
                        date_obj = datetime.fromtimestamp(member.mtime)
                        date_str = date_obj.isoformat()
                    except:
                        pass
                
                files_info.append({
                    "name": member.name,
                    "size": file_size,
                    "compressed_size": None,  # Размер после сжатия bz2 не доступен напрямую
                    "is_dir": is_dir,
                    "date": date_str
                })
                
                if not is_dir:
                    total_size += file_size
    except Exception as e:
        logger.error(f"Ошибка при чтении TAR.BZ2 архива: {e}")
        raise
    
    return files_info, total_size


async def _list_rar_contents(archive_path: str) -> tuple[List[Dict], int]:
    """Получает список файлов в RAR архиве без распаковки"""
    files_info = []
    total_size = 0
    
    try:
        # Пробуем использовать rarfile (Python библиотека)
        try:
            import rarfile
            with rarfile.RarFile(archive_path) as rar_ref:
                for file_info in rar_ref.infolist():
                    # Пропускаем небезопасные пути
                    if '..' in file_info.filename or file_info.filename.startswith('/'):
                        continue
                    
                    is_dir = file_info.is_dir()
                    file_size = file_info.file_size if not is_dir else 0
                    compressed_size = file_info.compress_size if not is_dir else None
                    
                    # Форматируем дату
                    date_str = None
                    if hasattr(file_info, 'date_time') and file_info.date_time:
                        try:
                            date_obj = datetime(*file_info.date_time)
                            date_str = date_obj.isoformat()
                        except:
                            pass
                    
                    files_info.append({
                        "name": file_info.filename,
                        "size": file_size,
                        "compressed_size": compressed_size,
                        "is_dir": is_dir,
                        "date": date_str
                    })
                    
                    if not is_dir:
                        total_size += file_size
        except ImportError:
            # Если rarfile не установлен, пробуем через командную строку
            import subprocess
            result = subprocess.run(
                ['unrar', 'l', archive_path],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                # Пробуем rar вместо unrar
                result = subprocess.run(
                    ['rar', 'l', archive_path],
                    capture_output=True,
                    text=True
                )
            
            if result.returncode == 0:
                # Парсим вывод команды (базовый парсинг)
                lines = result.stdout.split('\n')
                for line in lines:
                    # Простой парсинг - можно улучшить
                    if line.strip() and not line.startswith('---'):
                        parts = line.split()
                        if len(parts) >= 4:
                            try:
                                size = int(parts[2]) if parts[2].isdigit() else 0
                                filename = ' '.join(parts[4:]) if len(parts) > 4 else parts[-1]
                                files_info.append({
                                    "name": filename,
                                    "size": size,
                                    "compressed_size": None,
                                    "is_dir": False,
                                    "date": None
                                })
                                total_size += size
                            except:
                                pass
            else:
                raise Exception(f"Не удалось прочитать RAR архив. Установите unrar или rarfile: pip install rarfile")
    except Exception as e:
        logger.error(f"Ошибка при чтении RAR архива: {e}")
        raise Exception(f"Ошибка при чтении RAR архива: {str(e)}. Установите rarfile: pip install rarfile или unrar")
    
    return files_info, total_size
