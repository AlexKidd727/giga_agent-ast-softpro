"""Инструменты для распознавания речи через STT сервис."""

import os
from pathlib import Path
from typing import Annotated

import aiohttp
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import Field

# Импортируем утилиты для работы с файлами пользователей
try:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../repl/app"))
    from user_files_utils import resolve_file_path, get_user_files_dir
except ImportError:
    # Fallback если модуль недоступен
    def resolve_file_path(file_path, user_id=None):
        # Простой fallback - ищем в общей папке
        potential_path = os.path.join(FILES_DIR, file_path.lstrip("/"))
        if os.path.exists(potential_path):
            return Path(potential_path)
        if os.path.exists(file_path):
            return Path(file_path)
        return None
    def get_user_files_dir(user_id):
        return Path(FILES_DIR)

STT_SERVICE_URL = os.getenv("STT_SERVICE_API", "http://stt-service:9093")
# Путь к папке с файлами проекта
FILES_DIR = os.getenv("FILES_DIR", "/files")


@tool(parse_docstring=True)
async def transcribe_audio(
    file_path: Annotated[
        str,
        Field(description="Путь к аудиофайлу для распознавания. Может быть локальным путем или URL"),
    ],
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Распознает речь из аудиофайла на русском языке.
    
    Поддерживаемые форматы: WAV, MP3, FLAC, OGG
    Рекомендуемый формат: моно 16-bit PCM WAV при 8 кГц
    
    Args:
        file_path: Путь к аудиофайлу (локальный путь в файловой системе или URL)
    
    Returns:
        Распознанный текст из аудиофайла
    """
    stt_url = f"{STT_SERVICE_URL}/api/transcribe"
    
    # Определяем, является ли file_path URL или локальным путем
    is_url = file_path.startswith(("http://", "https://"))
    
    try:
        if is_url:
            # Если это URL, сначала скачиваем файл
            async with aiohttp.ClientSession() as session:
                async with session.get(file_path, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        return f"Ошибка загрузки файла по URL {file_path}: статус {resp.status}"
                    audio_data = await resp.read()
        else:
            # Если это локальный путь
            # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из state для поиска файла в папке пользователя
            user_id = None
            if state:
                user_id = state.get("user_id")
                # Нормализуем user_id
                if user_id in ["default_user", "anonymous", "guest", ""]:
                    user_id = None
            
            # Пытаемся найти файл с учетом user_id
            resolved_path = resolve_file_path(file_path, user_id)
            
            if resolved_path and resolved_path.exists():
                found_path = str(resolved_path)
            else:
                # Fallback: проверяем несколько возможных мест с нормализацией имен
                clean_path = file_path.lstrip("/")
                possible_paths = [
                    file_path,
                    os.path.join(FILES_DIR, clean_path),
                    os.path.join("files", clean_path),
                ]
                
                # Если путь начинается с /files/, убираем префикс и ищем в FILES_DIR
                if file_path.startswith("/files/"):
                    possible_paths.insert(1, os.path.join(FILES_DIR, file_path[7:]))
                
                # Пробуем нормализованные варианты
                try:
                    from user_files_utils import normalize_filename
                    normalized_path = normalize_filename(clean_path)
                    if normalized_path != clean_path:
                        possible_paths.append(os.path.join(FILES_DIR, normalized_path))
                        if user_id:
                            filename = os.path.basename(normalized_path)
                            possible_paths.append(os.path.join(FILES_DIR, user_id, filename))
                except:
                    pass
                
                # Если есть user_id, пробуем найти в его папке
                if user_id:
                    filename = os.path.basename(clean_path)
                    possible_paths.insert(0, os.path.join(FILES_DIR, user_id, filename))
                    # Пробуем с нормализованным именем
                    try:
                        from user_files_utils import normalize_filename
                        normalized_name = normalize_filename(filename)
                        if normalized_name != filename:
                            possible_paths.insert(0, os.path.join(FILES_DIR, user_id, normalized_name))
                    except:
                        pass
                
                found_path = None
                for path in possible_paths:
                    if os.path.exists(path) and os.path.isfile(path):
                        found_path = path
                        break
                
                if found_path is None:
                    return f"Файл не найден: {file_path}. Проверенные пути: {', '.join(possible_paths)}"
            
            with open(found_path, "rb") as f:
                audio_data = f.read()
        
        # Отправляем файл на распознавание
        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            data.add_field(
                "file",
                audio_data,
                filename=os.path.basename(file_path) if not is_url else "audio_file",
                content_type="audio/wav",
            )
            
            async with session.post(
                stt_url,
                data=data,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    return f"Ошибка распознавания речи: статус {resp.status}, детали: {error_text}"
                
                result = await resp.json()
                text = result.get("text", "")
                phrases = result.get("phrases", [])
                
                if not text:
                    return "Не удалось распознать речь из аудиофайла. Возможно, файл пуст или содержит только шум."
                
                # Форматируем результат с информацией о фразах
                if phrases and len(phrases) > 1:
                    result_text = f"Распознанный текст:\n{text}\n\n"
                    result_text += "Фразы с таймингами:\n"
                    for i, phrase in enumerate(phrases, 1):
                        start = phrase.get("start_time", 0)
                        end = phrase.get("end_time", 0)
                        phrase_text = phrase.get("text", "")
                        result_text += f"{i}. [{start:.2f}s - {end:.2f}s] {phrase_text}\n"
                    return result_text
                
                return f"Распознанный текст: {text}"
                
    except aiohttp.ClientError as exc:
        return f"Ошибка подключения к STT сервису: {exc}"
    except FileNotFoundError:
        return f"Файл не найден: {file_path}"
    except Exception as exc:
        return f"Неожиданная ошибка при распознавании речи: {exc}"


@tool(parse_docstring=True)
async def transcribe_audio_from_url(
    url: Annotated[
        str,
        Field(description="URL аудиофайла для распознавания"),
    ],
) -> str:
    """
    Распознает речь из аудиофайла по URL на русском языке.
    
    Поддерживаемые форматы: WAV, MP3, FLAC, OGG
    Рекомендуемый формат: моно 16-bit PCM WAV при 8 кГц
    
    Args:
        url: URL аудиофайла для распознавания
    
    Returns:
        Распознанный текст из аудиофайла
    """
    return await transcribe_audio(url)

