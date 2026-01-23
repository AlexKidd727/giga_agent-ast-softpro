"""
Утилиты для работы с файлами пользователей с изоляцией по user_id
"""

import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Путь к папке с файлами
FILES_DIR = os.environ.get("FILES_DIR", "files")


def _validate_user_id(user_id: Optional[str]) -> str:
    """
    Валидирует и нормализует user_id
    
    Args:
        user_id: Идентификатор пользователя
        
    Returns:
        Валидный user_id
        
    Raises:
        ValueError: Если user_id невалидный
    """
    if not user_id or user_id.strip() in ["", "default_user", "anonymous", "guest"]:
        raise ValueError(f"Невалидный user_id: {user_id}. Файлы должны быть привязаны к конкретному пользователю.")
    
    # Очищаем user_id от небезопасных символов
    user_id_clean = user_id.strip()
    # Удаляем небезопасные символы для использования в пути
    unsafe_chars = ['/', '\\', '..', '<', '>', ':', '"', '|', '?', '*']
    for char in unsafe_chars:
        if char in user_id_clean:
            raise ValueError(f"user_id содержит небезопасные символы: {char}")
    
    return user_id_clean


def get_user_files_dir(user_id: Optional[str]) -> Path:
    """
    Получает путь к папке файлов пользователя
    
    Args:
        user_id: Идентификатор пользователя
        
    Returns:
        Path к папке файлов пользователя
        
    Raises:
        ValueError: Если user_id невалидный
    """
    user_id = _validate_user_id(user_id)
    user_dir = Path(FILES_DIR) / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def get_user_file_path(user_id: Optional[str], filename: str) -> Path:
    """
    Получает полный путь к файлу пользователя
    
    Args:
        user_id: Идентификатор пользователя
        filename: Имя файла
        
    Returns:
        Path к файлу пользователя
        
    Raises:
        ValueError: Если user_id невалидный или filename содержит небезопасные символы
    """
    user_id = _validate_user_id(user_id)
    
    # Проверяем filename на небезопасные символы
    if '..' in filename or '/' in filename or '\\' in filename:
        raise ValueError(f"Недопустимое имя файла: {filename}")
    
    user_dir = get_user_files_dir(user_id)
    return user_dir / filename


def normalize_filename(filename: str) -> str:
    """
    Нормализует имя файла, убирая пробелы перед скобками.
    Например: "archive (5).zip" -> "archive(5).zip"
    
    Args:
        filename: Исходное имя файла
        
    Returns:
        Нормализованное имя файла
    """
    import re
    # Убираем пробелы перед скобками: "archive (5).zip" -> "archive(5).zip"
    normalized = re.sub(r'\s+\(', '(', filename)
    # Также убираем пробелы после скобок, если они есть: "archive( 5 ).zip" -> "archive(5).zip"
    normalized = re.sub(r'\(\s+', '(', normalized)
    normalized = re.sub(r'\s+\)', ')', normalized)
    return normalized


def resolve_file_path(file_path: str, user_id: Optional[str] = None) -> Optional[Path]:
    """
    Разрешает путь к файлу с учетом user_id
    
    Сначала пытается найти файл в папке пользователя, затем в общей папке (для обратной совместимости)
    Поддерживает пути с подпапками, пробелами и специальными символами (например, "user_id/archive (5).zip")
    Автоматически нормализует имена файлов (убирает пробелы перед скобками) для совместимости с загруженными файлами
    
    Args:
        file_path: Путь к файлу (может быть относительным или абсолютным)
        user_id: Идентификатор пользователя (опционально)
        
    Returns:
        Path к файлу или None, если файл не найден
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.debug(f"[resolve_file_path] Ищем файл: {file_path}, user_id: {user_id}")
    
    # Убираем начальный слеш если есть
    clean_path = file_path.lstrip("/")
    file_path_obj = Path(file_path)
    
    # Если путь абсолютный и существует, возвращаем его
    if file_path_obj.is_absolute() and file_path_obj.exists():
        return file_path_obj
    
    # Список потенциальных путей для проверки
    potential_paths = []
    
    # Если путь содержит подпапки (например, "user_id/filename")
    if "/" in clean_path:
        parts = clean_path.split("/", 1)
        if len(parts) == 2:
            path_user_id, filename = parts
            # Нормализуем имя файла (убираем пробелы перед скобками)
            normalized_filename = normalize_filename(filename)
            
            # Если первая часть похожа на UUID (user_id), пробуем найти файл в его папке
            if len(path_user_id) > 20:  # UUID обычно длиннее 20 символов
                # Пробуем с оригинальным именем
                potential_paths.append(Path(FILES_DIR) / path_user_id / filename)
                # Пробуем с нормализованным именем (если отличается)
                if normalized_filename != filename:
                    potential_paths.append(Path(FILES_DIR) / path_user_id / normalized_filename)
                # Также пробуем с указанным user_id из параметра
                if user_id and user_id != path_user_id:
                    potential_paths.append(Path(FILES_DIR) / user_id / filename)
                    if normalized_filename != filename:
                        potential_paths.append(Path(FILES_DIR) / user_id / normalized_filename)
    
    # Если указан user_id, пробуем найти в папке пользователя
    if user_id:
        try:
            # Если путь содержит подпапки, используем весь путь относительно папки пользователя
            if "/" in clean_path:
                # Пробуем с оригинальным путем
                potential_paths.insert(0, Path(FILES_DIR) / user_id / clean_path)
                # Пробуем с нормализованным путем (если отличается)
                normalized_clean_path = normalize_filename(clean_path)
                if normalized_clean_path != clean_path:
                    potential_paths.insert(0, Path(FILES_DIR) / user_id / normalized_clean_path)
            else:
                # Иначе используем только имя файла
                original_name = file_path_obj.name
                normalized_name = normalize_filename(original_name)
                potential_paths.insert(0, Path(FILES_DIR) / user_id / original_name)
                # Пробуем с нормализованным именем (если отличается)
                if normalized_name != original_name:
                    potential_paths.insert(0, Path(FILES_DIR) / user_id / normalized_name)
        except ValueError:
            # Невалидный user_id, пропускаем
            pass
    
    # Добавляем стандартные варианты путей
    potential_paths.extend([
        Path(FILES_DIR) / clean_path,  # Относительно FILES_DIR
        Path(FILES_DIR) / file_path_obj.name,  # Только имя файла в FILES_DIR
        file_path_obj,  # Как есть (может быть относительным)
    ])
    
    # Также пробуем нормализованные варианты
    normalized_clean_path = normalize_filename(clean_path)
    if normalized_clean_path != clean_path:
        potential_paths.append(Path(FILES_DIR) / normalized_clean_path)
    
    normalized_name = normalize_filename(file_path_obj.name)
    if normalized_name != file_path_obj.name:
        potential_paths.append(Path(FILES_DIR) / normalized_name)
    
    # Если путь выглядит как абсолютный, пробуем его
    if os.path.isabs(file_path):
        potential_paths.append(Path(file_path))
    
    # Проверяем каждый путь
    for path in potential_paths:
        try:
            # Нормализуем путь и проверяем существование
            # Path правильно обрабатывает пробелы и специальные символы
            if path.exists():
                logger.debug(f"[resolve_file_path] Файл найден: {path}")
                return path
        except (OSError, ValueError) as e:
            # Пропускаем невалидные пути
            logger.debug(f"[resolve_file_path] Путь невалиден: {path}, ошибка: {e}")
            continue
    
    logger.warning(f"[resolve_file_path] Файл не найден: {file_path}, проверено путей: {len(potential_paths)}")
    return None


def list_user_files(user_id: Optional[str]) -> list[dict]:
    """
    Получает список файлов пользователя
    
    Args:
        user_id: Идентификатор пользователя
        
    Returns:
        Список словарей с информацией о файлах
    """
    try:
        user_dir = get_user_files_dir(user_id)
        files = []
        
        for file_path in user_dir.iterdir():
            if file_path.is_file() and not file_path.name.startswith('.'):
                files.append({
                    "name": file_path.name,
                    "path": str(file_path),
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime
                })
        
        return files
    except ValueError as e:
        logger.error(f"Ошибка при получении списка файлов пользователя: {e}")
        return []

