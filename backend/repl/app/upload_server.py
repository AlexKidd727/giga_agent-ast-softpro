import io
import json
import mimetypes
import os
import urllib.parse
import uuid
import plotly
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Request, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv
from pydantic import BaseModel

from langgraph_sdk import get_client
from .user_files_utils import get_user_file_path, get_user_files_dir, resolve_file_path, _validate_user_id

# Локальная версия get_user_id_from_request для upload_server
# (модуль giga_agent недоступен в контейнере repl)
async def get_user_id_from_request(request: Request) -> Optional[str]:
    """
    Извлекает user_id из запроса:
    1. Из заголовка X-User-ID (если передан фронтендом)
    2. Из токена в заголовке Authorization (упрощенная версия без БД)
    
    Args:
        request: FastAPI Request объект
        
    Returns:
        user_id если найден, иначе None
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Логируем все заголовки для отладки
    all_headers = dict(request.headers)
    logger.info(f"🔍 upload_server: Все заголовки запроса: {list(all_headers.keys())}")
    logger.info(f"🔍 upload_server: Все заголовки (полные): {dict(all_headers)}")
    logger.info(f"🔍 upload_server: X-User-ID: {request.headers.get('X-User-ID')}")
    logger.info(f"🔍 upload_server: X_User_ID: {request.headers.get('X_User_ID')}")
    logger.info(f"🔍 upload_server: x-user-id: {request.headers.get('x-user-id')}")
    logger.info(f"🔍 upload_server: x_user_id: {request.headers.get('x_user_id')}")
    logger.info(f"🔍 upload_server: HTTP_X_USER_ID: {request.headers.get('HTTP_X_USER_ID')}")
    
    # 1. Пытаемся извлечь из заголовка X-User-ID
    # Nginx преобразует заголовки с дефисами: X-User-ID -> X_User_ID
    # Также проверяем все возможные варианты имени заголовка
    x_user_id = (
        request.headers.get("X-User-ID") or 
        request.headers.get("X_User_ID") or
        request.headers.get("x-user-id") or
        request.headers.get("x_user_id") or
        request.headers.get("HTTP_X_USER_ID")
    )
    if x_user_id:
        user_id = x_user_id.strip()
        if user_id and user_id not in ["default_user", "anonymous", "guest", ""]:
            logger.info(f"✅ upload_server: user_id получен из заголовка: {user_id}")
            return user_id
    
    # 2. Пытаемся извлечь из токена (упрощенная версия)
    # В полной версии здесь была бы проверка токена через БД,
    # но для upload_server достаточно заголовка X-User-ID
    authorization = request.headers.get("Authorization")
    if authorization and authorization.startswith("Bearer "):
        # В упрощенной версии просто возвращаем None
        # Если нужна полная проверка токена, нужно подключаться к БД
        pass
    
    return None

load_dotenv("../../.env")

# Определяем пути до создания app
FILES_DIR = os.environ.get("FILES_DIR", "files")
RUNS_DIR = os.environ.get("RUNS_DIR", "runs")
METADATA_FILE = os.path.join(FILES_DIR, ".files_metadata.json")
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(RUNS_DIR, exist_ok=True)

FILE_TYPES = {"image", "plotly_graph", "html", "text", "audio", "other"}

if not Path(FILES_DIR).exists():
    Path(FILES_DIR).mkdir(parents=True, exist_ok=True)


# Расширения архивов для исключения
ARCHIVE_EXTENSIONS = {
    '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz',
    '.tar.gz', '.tar.bz2', '.tar.xz', '.tgz', '.tbz2',
    '.cab', '.iso', '.dmg', '.pkg', '.deb', '.rpm',
    '.ar', '.cpio', '.shar', '.lbr', '.mar', '.sbx',
    '.ace', '.lzh', '.lha', '.z', '.arc', '.wim'
}


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


def is_archive_file(filename: str) -> bool:
    """Проверяет, является ли файл архивом (включая составные расширения)"""
    filename_lower = filename.lower()
    # Проверяем составные расширения сначала
    for ext in ['.tar.gz', '.tar.bz2', '.tar.xz', '.tgz', '.tbz2']:
        if filename_lower.endswith(ext):
            return True
    # Проверяем простые расширения
    file_ext = Path(filename).suffix.lower()
    return file_ext in ARCHIVE_EXTENSIONS


def scan_files_directory():
    """
    Сканирует папку files и добавляет отсутствующие файлы в метаданные
    
    ВАЖНО: Сканирует только папки пользователей (user_id), не общую папку
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("📚 scan_files_directory: Начало сканирования папки files")
        
        if not os.path.exists(FILES_DIR):
            logger.warning(f"📚 scan_files_directory: Папка {FILES_DIR} не существует")
            return
        
        metadata_dict = load_metadata()
        updated = False
        files_scanned = 0
        files_added = 0
        files_skipped = 0
        
        # Сканируем папку files
        # КРИТИЧЕСКИ ВАЖНО: Сканируем только папки пользователей
        for root, dirs, files in os.walk(FILES_DIR):
            # Пропускаем скрытые файлы и папки
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            # Исключаем папку projects
            if 'projects' in dirs:
                dirs.remove('projects')
                logger.info(f"📚 scan_files_directory: Пропущена папка projects в {root}")
            
            # КРИТИЧЕСКИ ВАЖНО: Если мы в корне FILES_DIR, сканируем только папки пользователей
            # (папки, которые не являются служебными)
            if root == FILES_DIR:
                # В корне оставляем только папки, которые могут быть user_id
                # (не служебные папки типа projects, .files_metadata.json и т.д.)
                dirs[:] = [d for d in dirs if d not in ['projects', '.files_metadata.json']]
            
            for filename in files:
                if filename.startswith('.') or filename == '.files_metadata.json':
                    continue
                
                file_path = os.path.join(root, filename)
                normalized_path = os.path.normpath(file_path)
                
                if not os.path.isfile(file_path):
                    continue
                
                # Проверяем, является ли файл архивом
                if is_archive_file(filename):
                    files_skipped += 1
                    logger.debug(f"📚 scan_files_directory: Пропущен архив: {filename}")
                    continue
                
                files_scanned += 1
                
                # Проверяем, есть ли файл в метаданных
                if normalized_path not in metadata_dict:
                    # Получаем информацию о файле
                    file_stat = os.stat(file_path)
                    file_size = file_stat.st_size
                    mtime = file_stat.st_mtime
                    
                    # Определяем тип файла
                    mime_type, _ = mimetypes.guess_type(file_path)
                    file_type = "other"
                    if mime_type:
                        if mime_type.startswith("image/"):
                            file_type = "image"
                        elif mime_type.startswith("text/"):
                            file_type = "text"
                        elif mime_type == "application/pdf":
                            file_type = "pdf"
                        elif mime_type.startswith("audio/"):
                            file_type = "audio"
                        elif mime_type.startswith("video/"):
                            file_type = "video"
                    
                    # Добавляем файл в метаданные с категорией "текстовые данные" по умолчанию
                    metadata_dict[normalized_path] = {
                        "description": None,
                        "tags": [],
                        "category": "текстовые данные",
                        "uploaded_at": datetime.fromtimestamp(mtime).isoformat(),
                        "updated_at": None,
                    }
                    
                    files_added += 1
                    updated = True
                    logger.info(f"📚 scan_files_directory: Добавлен файл в метаданные: {filename}")
        
        if updated:
            save_metadata(metadata_dict)
            logger.info(f"✅ scan_files_directory: Сканирование завершено. Просмотрено: {files_scanned}, добавлено: {files_added}, пропущено (архивы/projects): {files_skipped}")
        else:
            logger.info(f"✅ scan_files_directory: Сканирование завершено. Просмотрено: {files_scanned}, добавлено: {files_added}, пропущено (архивы/projects): {files_skipped}")
            
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"❌ scan_files_directory: Ошибка при сканировании: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Обработчик жизненного цикла приложения"""
    import logging
    logger = logging.getLogger(__name__)
    
    # Startup
    logger.info("🚀 upload_server: Запуск сервера...")
    scan_files_directory()
    logger.info("✅ upload_server: Сервер запущен")
    
    yield
    
    # Shutdown
    logger.info("🛑 upload_server: Остановка сервера...")


app = FastAPI(lifespan=lifespan)

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # кому разрешаем
    allow_credentials=True,  # передавать ли куки/креденшалы
    allow_methods=["*"],  # какие HTTP-методы
    allow_headers=["*"],  # какие заголовки
)


# Модели для метаданных файлов
class FileMetadata(BaseModel):
    path: str
    name: str
    size: int
    file_type: str
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    uploaded_at: str
    updated_at: Optional[str] = None


# Функции для работы с метаданными
def load_metadata() -> Dict[str, Dict[str, Any]]:
    """Загружает метаданные файлов из JSON файла"""
    if not os.path.exists(METADATA_FILE):
        return {}
    try:
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_metadata(metadata: Dict[str, Dict[str, Any]]):
    """Сохраняет метаданные файлов в JSON файл"""
    try:
        with open(METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except IOError as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка сохранения метаданных: {e}")


def get_file_metadata(file_path: str) -> Optional[Dict[str, Any]]:
    """Получает метаданные для конкретного файла"""
    metadata = load_metadata()
    # Нормализуем путь для поиска
    normalized_path = os.path.normpath(file_path)
    return metadata.get(normalized_path)


def set_file_metadata(file_path: str, metadata: Dict[str, Any]):
    """Устанавливает метаданные для файла"""
    all_metadata = load_metadata()
    normalized_path = os.path.normpath(file_path)
    all_metadata[normalized_path] = metadata
    save_metadata(all_metadata)


def uniquify(path):
    filename, extension = os.path.splitext(path)
    counter = 1

    while os.path.exists(path):
        path = filename + " (" + str(counter) + ")" + extension
        counter += 1

    return path


def _safe_join(base: str, relative: str) -> str:
    relative = (relative or "").replace("\\", "/").lstrip("/")
    candidate = os.path.normpath(os.path.join(base, relative))
    base_abs = os.path.abspath(base)
    cand_abs = os.path.abspath(candidate)
    if not (cand_abs == base_abs or cand_abs.startswith(base_abs + os.sep)):
        raise HTTPException(status_code=400, detail="Недопустимый путь")
    return candidate


def _detect_image_mime(path: str) -> Optional[str]:
    try:
        from PIL import Image

        with Image.open(path) as img:
            img.verify()
            mime = Image.MIME.get(img.format)
            return mime
    except Exception:
        return None


async def upload_image(path: str) -> dict:
    from PIL import Image, ImageOps
    import httpx

    api_url_base = os.getenv("GIGA_AGENT_API", "").rstrip("/")
    if not api_url_base:
        raise RuntimeError("GIGA_AGENT_API is not set")
    url = f"{api_url_base}/upload/image/"

    # Определяем, является ли исходный файл JPEG
    is_jpeg = False
    try:
        with Image.open(path) as im:
            is_jpeg = im.format == "JPEG"
    except Exception:
        is_jpeg = path.lower().endswith((".jpg", ".jpeg"))

    if is_jpeg:
        # Если уже JPEG — отправляем как есть, без перекодирования
        async with httpx.AsyncClient(timeout=60) as client:
            with open(path, "rb") as f:
                response = await client.post(
                    url,
                    files={
                        "file": (
                            os.path.basename(path),
                            f,
                            "image/jpeg",
                        )
                    },
                )
        response.raise_for_status()
        return response.json()

    # Иначе конвертируем в JPEG и уменьшаем при необходимости
    image = ImageOps.exif_transpose(Image.open(path))
    max_side = 1024
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.LANCZOS)

    buf = io.BytesIO()
    image.convert("RGB").save(
        buf,
        format="JPEG",
        quality=85,
        optimize=True,
        progressive=True,
    )
    buf.seek(0)

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            url,
            files={
                "file": (
                    f"{uuid.uuid4()}.jpg",
                    buf,
                    "image/jpeg",
                )
            },
        )
    response.raise_for_status()
    return response.json()


@app.post("/upload/run")
async def upload_run(
    files: List[UploadFile] = File(...),
    paths: Optional[List[str]] = Form(default=None),
    types: List[str] = Form(...),
    thread_id: str = Form(...),
):
    saved = []
    # Валидация соответствия размеров списков
    if not types or len(types) != len(files):
        raise HTTPException(
            status_code=400,
            detail="Количество элементов 'types' должно совпадать с количеством 'files'",
        )
    try:
        for idx, file in enumerate(files):
            if paths and idx < len(paths) and paths[idx]:
                rel = paths[idx]
            else:
                rel = file.filename

            rel = urllib.parse.unquote(rel)
            # Нормализуем имя файла (убираем пробелы перед скобками)
            rel = normalize_filename(rel)
            dest_path = _safe_join(_safe_join(RUNS_DIR, thread_id), rel)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            with open(dest_path, "wb") as out:
                while chunk := await file.read(1024 * 1024):
                    out.write(chunk)

            # Определяем тип файла на основе обязательного параметра
            t = (types[idx] or "").strip().lower()
            if t not in FILE_TYPES:
                raise HTTPException(status_code=400, detail=f"Недопустимый тип: {t}")
            file_type = t
            image_id = None
            image_path = None
            if file_type == "image":
                data = await upload_image(dest_path)
                image_id = data["id"]
                image_path = dest_path
            elif file_type == "plotly_graph":
                with open(dest_path, "r") as f:
                    plot_json = f.read()
                plot = plotly.io.from_json(plot_json)
                img = plotly.io.to_image(plot, format="jpg")
                img_path = ".".join(dest_path.split(".")[:-1]) + ".jpg"
                with open(img_path, "wb") as f:
                    f.write(img)
                data = await upload_image(img_path)
                image_id = data["id"]
                image_path = img_path
            file_metadata = {
                "path": dest_path,
                "size": os.path.getsize(dest_path),
                "file_type": file_type,
                "image_id": image_id,
                "image_path": image_path,
            }
            saved.append(file_metadata)
            client = get_client(
                url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024")
            )
            await client.store.put_item(
                ("attachments",),
                dest_path,
                file_metadata,
                ttl=None,
                index=False,
            )
    finally:
        for f in files:
            await f.close()
    return {"saved": saved}


@app.post("/upload/")
async def upload(
    request: Request,
    file: UploadFile = File(...)
):
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Логируем начало обработки запроса
        logger.info(f"🔍 upload_server: Начало обработки загрузки файла: {file.filename}")
        logger.info(f"🔍 upload_server: Все заголовки запроса: {list(request.headers.keys())}")
        
        # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из запроса
        user_id = None
        if request:
            user_id = await get_user_id_from_request(request)
        
        logger.info(f"🔍 upload_server: user_id после get_user_id_from_request: {user_id}")
        
        if not user_id:
            # Если user_id не найден, возвращаем ошибку
            logger.error("❌ upload_server: user_id не найден в запросе. Требуется аутентификация.")
            logger.error(f"❌ upload_server: Все заголовки: {dict(request.headers)}")
            raise HTTPException(
                status_code=401,
                detail="Требуется аутентификация для загрузки файлов"
            )
        
        logger.info(f"📎 upload_server: Получен файл для загрузки: {file.filename}, content_type: {file.content_type}, user_id: {user_id}")
        
        # Нормализуем имя файла (убираем пробелы перед скобками)
        normalized_filename = normalize_filename(file.filename)
        if normalized_filename != file.filename:
            logger.info(f"📎 upload_server: Имя файла нормализовано: '{file.filename}' -> '{normalized_filename}'")
        
        # Сохраняем файл в папку пользователя с нормализованным именем
        user_file_path = get_user_file_path(user_id, normalized_filename)
        # Делаем уникальное имя, если файл уже существует
        path = uniquify(str(user_file_path))
        logger.info(f"📎 upload_server: Сохранение файла по пути: {path}")
        
        with open(path, "wb") as f:
            while contents := file.file.read(1024 * 1024):
                f.write(contents)
        
        file_size = os.path.getsize(path)
        logger.info(f"📎 upload_server: Файл сохранен, размер: {file_size} байт")
        
        if file.content_type.startswith("image/"):
            logger.info(f"📎 upload_server: Файл является изображением, загружаем через upload_image")
            data = await upload_image(path)
            # Возвращаем относительный путь от FILES_DIR и имя файла для фронтенда
            relative_path = os.path.relpath(path, FILES_DIR)
            file_metadata = {
                "path": relative_path,
                "name": normalized_filename,  # Используем нормализованное имя
                "size": file_size,
                "file_type": "image",
                "image_id": data.get("id"),
                "image_path": relative_path,
            }
            logger.info(f"📎 upload_server: Метаданные изображения: {file_metadata}")
            
            client = get_client(
                url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024")
            )
            await client.store.put_item(
                ("attachments",),
                path,
                file_metadata,
                ttl=None,
                index=False,
            )
            logger.info(f"📎 upload_server: Метаданные сохранены в store")
            return file_metadata
        else:
            logger.info(f"📎 upload_server: Файл не является изображением, возвращаем путь и имя файла")
            # Возвращаем относительный путь от FILES_DIR и имя файла для фронтенда
            relative_path = os.path.relpath(path, FILES_DIR)
            return {
                "path": relative_path,
                "name": normalized_filename,  # Используем нормализованное имя
                "size": file_size
            }
    except Exception as e:
        logger.error(f"❌ upload_server: Ошибка при загрузке файла: {e}", exc_info=True)
        raise e
    finally:
        file.file.close()


@app.get("/api/knowledge/files")
async def list_knowledge_files(request: Request):
    """
    Получает список файлов пользователя из папки files с их метаданными
    
    ВАЖНО: Возвращает только файлы текущего пользователя
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из запроса
        user_id = await get_user_id_from_request(request)
        
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Требуется аутентификация для доступа к файлам"
            )
        
        files_list = []
        metadata_dict = load_metadata()
        
        # Получаем папку пользователя
        user_dir = get_user_files_dir(user_id)
        if not user_dir.exists():
            return JSONResponse(content={"files": []})
        
        # Сканируем только папку пользователя
        for root, dirs, files in os.walk(user_dir):
            # Пропускаем скрытые файлы и папки
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            # Исключаем папку projects (как в scan_files_directory)
            if 'projects' in dirs:
                dirs.remove('projects')
                logger.info(f"📚 list_knowledge_files: Пропущена папка projects в {root}")
            
            for filename in files:
                if filename.startswith('.') or filename == '.files_metadata.json':
                    continue
                
                file_path = os.path.join(root, filename)
                relative_path = os.path.relpath(file_path, FILES_DIR)
                normalized_path = os.path.normpath(file_path)
                
                if not os.path.isfile(file_path):
                    continue
                
                # Проверяем, является ли файл архивом (как в scan_files_directory)
                if is_archive_file(filename):
                    logger.info(f"📚 list_knowledge_files: Пропущен архив: {filename}")
                    continue
                
                # Дополнительная проверка: пропускаем файлы из папки projects (проверяем и полный, и относительный путь)
                # Используем os.path.normpath для нормализации путей с разными разделителями
                path_parts = os.path.normpath(normalized_path).split(os.sep)
                relative_parts = os.path.normpath(relative_path).split(os.sep)
                # Проверяем, что 'projects' находится в пути (не в начале, не в конце, а как отдельная папка)
                if 'projects' in path_parts or 'projects' in relative_parts:
                    logger.info(f"📚 list_knowledge_files: Пропущен файл из папки projects: {filename} (path: {relative_path}, normalized: {normalized_path})")
                    continue
                
                # Получаем базовую информацию о файле
                file_size = os.path.getsize(file_path)
                mime_type, _ = mimetypes.guess_type(file_path)
                file_stat = os.stat(file_path)
                
                # Получаем метаданные из JSON
                file_metadata = metadata_dict.get(normalized_path, {})
                
                # Определяем тип файла
                file_type = "other"
                if mime_type:
                    if mime_type.startswith("image/"):
                        file_type = "image"
                    elif mime_type.startswith("text/"):
                        file_type = "text"
                    elif mime_type == "application/pdf":
                        file_type = "pdf"
                    elif mime_type.startswith("audio/"):
                        file_type = "audio"
                    elif mime_type.startswith("video/"):
                        file_type = "video"
                
                file_info = {
                    "path": relative_path,
                    "full_path": normalized_path,
                    "name": filename,
                    "size": file_size,
                    "file_type": file_type,
                    "mime_type": mime_type or "application/octet-stream",
                    "modified_at": datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
                    "description": file_metadata.get("description"),
                    "tags": file_metadata.get("tags", []),
                    "category": file_metadata.get("category"),
                    "uploaded_at": file_metadata.get("uploaded_at", datetime.fromtimestamp(file_stat.st_mtime).isoformat()),
                }
                
                files_list.append(file_info)
        
        # Сортируем по дате изменения (новые первыми)
        files_list.sort(key=lambda x: x["modified_at"], reverse=True)
        
        logger.info(f"📚 list_knowledge_files: Найдено {len(files_list)} файлов")
        
        # Добавляем заголовки для предотвращения кэширования
        response = JSONResponse(content={"files": files_list})
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Ошибка при получении списка файлов: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при получении списка файлов: {str(e)}")


@app.post("/api/knowledge/files/upload")
async def upload_knowledge_file(
    request: Request,
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    category: Optional[str] = Form(None)
):
    """Загружает файл в папку files с метаданными (описание, теги, категория)"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из запроса
        user_id = await get_user_id_from_request(request)
        
        if not user_id:
            logger.error("❌ upload_knowledge_file: user_id не найден в запросе. Требуется аутентификация.")
            raise HTTPException(
                status_code=401,
                detail="Требуется аутентификация для загрузки файлов"
            )
        
        logger.info(f"📚 upload_knowledge_file: Получен файл: {file.filename}, user_id: {user_id}")
        
        # Нормализуем имя файла (убираем пробелы перед скобками)
        normalized_filename = normalize_filename(file.filename)
        if normalized_filename != file.filename:
            logger.info(f"📚 upload_knowledge_file: Имя файла нормализовано: '{file.filename}' -> '{normalized_filename}'")
        
        # Сохраняем файл в папку пользователя с нормализованным именем
        user_file_path = get_user_file_path(user_id, normalized_filename)
        path = uniquify(str(user_file_path))
        logger.info(f"📚 upload_knowledge_file: Сохранение файла по пути: {path}")
        
        with open(path, "wb") as f:
            while contents := file.file.read(1024 * 1024):
                f.write(contents)
        
        file_size = os.path.getsize(path)
        normalized_path = os.path.normpath(path)
        
        # Парсим теги (разделенные запятыми)
        tags_list = []
        if tags:
            tags_list = [tag.strip() for tag in tags.split(",") if tag.strip()]
        
        # Сохраняем метаданные
        metadata = {
            "description": description,
            "tags": tags_list,
            "category": category,
            "uploaded_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        set_file_metadata(normalized_path, metadata)
        
        # Определяем тип файла
        mime_type, _ = mimetypes.guess_type(path)
        file_type = "other"
        if mime_type:
            if mime_type.startswith("image/"):
                file_type = "image"
            elif mime_type.startswith("text/"):
                file_type = "text"
            elif mime_type == "application/pdf":
                file_type = "pdf"
            elif mime_type.startswith("audio/"):
                file_type = "audio"
            elif mime_type.startswith("video/"):
                file_type = "video"
        
        relative_path = os.path.relpath(path, FILES_DIR)
        
        result = {
            "path": relative_path,
            "full_path": normalized_path,
            "name": normalized_filename,  # Используем нормализованное имя
            "size": file_size,
            "file_type": file_type,
            "mime_type": mime_type or "application/octet-stream",
            "description": description,
            "tags": tags_list,
            "category": category,
            "uploaded_at": metadata["uploaded_at"],
        }
        
        logger.info(f"✅ upload_knowledge_file: Файл успешно загружен: {result}")
        return JSONResponse(content=result)
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Ошибка при загрузке файла: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке файла: {str(e)}")
    finally:
        file.file.close()


@app.put("/api/knowledge/files/{file_path:path}/metadata")
async def update_file_metadata(
    file_path: str,
    request: Request,
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    category: Optional[str] = Form(None)
):
    """
    Обновляет метаданные файла пользователя
    
    ВАЖНО: Файл должен принадлежать текущему пользователю
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из запроса
        user_id = await get_user_id_from_request(request)
        
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Требуется аутентификация для доступа к файлам"
            )
        
        # Проверяем, что файл находится в папке пользователя
        resolved_path = resolve_file_path(file_path, user_id)
        if not resolved_path or not resolved_path.exists():
            raise HTTPException(status_code=404, detail="Файл не найден")
        
        # Проверяем, что файл действительно в папке пользователя
        user_dir = get_user_files_dir(user_id)
        try:
            resolved_path.relative_to(user_dir)
        except ValueError:
            # Файл не в папке пользователя
            raise HTTPException(status_code=403, detail="Access denied")
        
        full_path = str(resolved_path)
        
        # Парсим теги
        tags_list = []
        if tags:
            tags_list = [tag.strip() for tag in tags.split(",") if tag.strip()]
        
        # Загружаем существующие метаданные
        existing_metadata = get_file_metadata(full_path) or {}
        
        # Обновляем метаданные
        metadata = {
            "description": description if description is not None else existing_metadata.get("description"),
            "tags": tags_list if tags is not None else existing_metadata.get("tags", []),
            "category": category if category is not None else existing_metadata.get("category"),
            "uploaded_at": existing_metadata.get("uploaded_at", datetime.now().isoformat()),
            "updated_at": datetime.now().isoformat(),
        }
        
        set_file_metadata(full_path, metadata)
        
        logger.info(f"✅ update_file_metadata: Метаданные обновлены для {file_path}")
        return JSONResponse(content={"success": True, "metadata": metadata})
        
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Ошибка при обновлении метаданных: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при обновлении метаданных: {str(e)}")


@app.get("/files/offloads/{file_path:path}")
async def download_offload_file(file_path: str, request: Request):
    """
    Получает файл из папки offloads (выгруженные данные инструментов).
    
    Путь: /files/offloads/{thread_id}/{tool_name}/{filename}
    
    ВАЖНО: Файлы offloads доступны без аутентификации, так как они привязаны к thread_id.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Проверяем, что путь не содержит опасных символов
        if ".." in file_path or file_path.startswith("/"):
            raise HTTPException(status_code=400, detail="Некорректный путь к файлу")
        
        # Формируем полный путь к файлу
        full_path = Path(FILES_DIR) / "offloads" / file_path
        logger.info(f"[download_offload_file] Запрос файла: {file_path}, полный путь: {full_path}")
        
        if not full_path.exists() or not full_path.is_file():
            logger.warning(f"[download_offload_file] Файл не найден: {full_path}")
            raise HTTPException(status_code=404, detail="Файл не найден")
        
        # Определяем MIME-тип по расширению
        mime_type, _ = mimetypes.guess_type(str(full_path))
        if not mime_type:
            mime_type = "application/octet-stream"
        
        # JSON файлы отдаем как application/json для корректной обработки на фронте
        if full_path.suffix.lower() == ".json":
            mime_type = "application/json"

        # Выбираем режим отдачи: inline для JSON (графики), image/* и application/pdf
        if mime_type == "application/json" or mime_type.startswith("image/") or mime_type == "application/pdf":
            disposition = "inline"
        else:
            disposition = "attachment"

        logger.info(f"[download_offload_file] Отдаем файл: {full_path}, mime: {mime_type}")
        return FileResponse(
            path=str(full_path),
            media_type=mime_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{full_path.name}"'
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[download_offload_file] Ошибка при загрузке файла {file_path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке файла: {str(e)}")


@app.get("/files/{filename:path}")
async def download_file(filename: str, request: Request):
    """
    Получает файл.
    
    Логика поиска файла:
    1. Если файл - это график (*_chart_*.png), ищем в корневой папке FILES_DIR (публичный доступ)
    2. Иначе требуем аутентификацию и ищем в папке пользователя
    
    ВАЖНО: Графики tinkoff_agent сохраняются в корневую папку FILES_DIR,
    поэтому для них не требуется аутентификация.
    """
    import logging
    import re
    logger = logging.getLogger(__name__)
    
    # Проверяем, является ли файл графиком (публичный доступ)
    # Паттерн: ticker_chart_timeframe_timestamp.png (например: spce_chart_1day_20260118_194931.png)
    chart_pattern = re.compile(r'^[a-z0-9]+_chart_[a-z0-9]+_\d{8}_\d{6}\.png$', re.IGNORECASE)
    
    if chart_pattern.match(filename):
        # Это график - публичный доступ без аутентификации
        logger.info(f"[download_file] Запрос публичного графика: {filename}")
        
        file_path = Path(FILES_DIR) / filename
        
        if not file_path.exists() or not file_path.is_file():
            logger.warning(f"[download_file] График не найден: {file_path}")
            raise HTTPException(status_code=404, detail="Файл не найден")
        
        return FileResponse(
            path=str(file_path),
            media_type="image/png",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"'
            },
        )
    
    # Для остальных файлов требуем аутентификацию
    # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из запроса
    user_id = await get_user_id_from_request(request)
    
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Требуется аутентификация для доступа к файлам"
        )
    
    try:
        # Ищем файл только в папке пользователя
        user_file_path = get_user_file_path(user_id, filename)
        if not user_file_path.exists() or not user_file_path.is_file():
            raise HTTPException(status_code=404, detail="Файл не найден")
        
        file_path = str(user_file_path)

        # Определяем MIME-тип по расширению
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        # Выбираем режим отдачи: inline для image/* и application/pdf, иначе attachment
        if mime_type.startswith("image/") or mime_type == "application/pdf":
            disposition = "inline"
        else:
            disposition = "attachment"

        return FileResponse(
            path=file_path,
            media_type=mime_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{os.path.basename(file_path)}"'
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка при загрузке файла {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке файла: {str(e)}")
