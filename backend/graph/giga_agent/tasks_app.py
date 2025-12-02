import asyncio
import io
import json
import os
import uuid
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import SQLModel, Field, select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel

from langgraph_sdk import get_client

from giga_agent.utils.env import load_project_env
from giga_agent.utils.llm import is_llm_image_inline, upload_file_with_retry

load_project_env()


# --- Модель данных ---
class Task(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    json_data: str = Field(default_factory=lambda: str("{}"))
    steps: int = Field(default=10, nullable=False)
    sorting: int = Field(default=None, nullable=False, index=True)
    active: bool = Field(default=False, nullable=False)


class User(SQLModel, table=True):
    """Модель пользователя с индивидуальными токенами"""
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    username: str = Field(unique=True, index=True)
    email: Optional[str] = None
    password: Optional[str] = None  # Пароль для аутентификации (в будущем можно хешировать)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    
    # Токены хранятся в JSON формате
    tinkoff_token: Optional[str] = None
    tinkoff_account_id: Optional[str] = None
    tinkoff_sandbox: bool = Field(default=False)
    
    github_token: Optional[str] = None
    
    google_calendar_credentials: Optional[str] = None  # Путь к файлу или JSON строка
    google_calendar_id: Optional[str] = None


class Session(SQLModel, table=True):
    """Модель сессии пользователя"""
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True, foreign_key="user.id")
    token: str = Field(unique=True, index=True)  # Токен сессии
    expires_at: str = Field()  # Время истечения сессии (ISO format)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class EmailAccount(SQLModel, table=True):
    """Модель почтового ящика пользователя"""
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True, foreign_key="user.id")  # Владелец ящика
    email: str = Field(index=True)  # Email адрес
    password: str = Field()  # Пароль от почтового ящика
    smtp_host: str = Field()  # SMTP сервер
    smtp_port: int = Field(default=587)  # SMTP порт
    imap_host: str = Field()  # IMAP сервер
    imap_port: int = Field(default=993)  # IMAP порт
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# --- Настройка асинхронного движка и сессии ---
# Используем PostgreSQL из переменных окружения или дефолтное значение
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@aegra-postgres:5432/postgres"
)
engine: AsyncEngine = create_async_engine(
    DATABASE_URL, echo=True
)
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


# --- Создаем таблицы ---
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    
    # Инициализация пользователя-админа
    await init_admin_user()
    
    async with AsyncSessionLocal() as session:
        # Считаем, сколько строк в таблице Task
        result = await session.execute(select(func.count()).select_from(Task))
        count_tasks = result.scalar_one()  # возвращает 0, если пусто
        # Если таблица Task пуста, подгружаем JSON-дамп
        if count_tasks == 0:
            # Предположим, файл dump.json лежит в той же директории, что и скрипт
            dump_path = os.path.join(os.path.dirname(__file__), "dump.json")
            if os.path.exists(dump_path):
                # Читаем список объектов из JSON
                with open(dump_path, "r", encoding="utf-8") as f:
                    data_list = await asyncio.to_thread(json.load, fp=f)

                # Проходим по каждому элементу массива
                for item in data_list:
                    # Извлекаем поля из JSON-объекта.
                    # Если в JSON не указан id, сгенерируем новый.
                    _id = item.get("id", str(uuid4()))

                    # Если в дампе json_data — это вложенный объект,
                    # сериализуем его в строку:
                    _json_data = item.get("json_data", {})
                    json_str = json.dumps(_json_data, ensure_ascii=False)

                    # Считываем остальные поля, или ставим дефолт
                    _steps = item.get("steps", 10)
                    _sorting = item.get("sorting", None)
                    _active = item.get("active", False)

                    # Если sorting не указан в JSON или равен None,
                    # можно установить next_sorting
                    if _sorting is None:
                        # Здесь мы вызываем вашу функцию next_sorting,
                        # передавая текущую сессию
                        _sorting = await next_sorting(session)

                    # Создаём объект Task и добавляем в сессию
                    task = Task(
                        id=_id,
                        json_data=json_str,
                        steps=_steps,
                        sorting=_sorting,
                        active=_active,
                    )
                    session.add(task)

                await session.commit()
            else:
                print(f"Файл {dump_path} не найден, пропускаем загрузку")


async def init_admin_user():
    """Инициализация пользователя-админа с токенами из переменных окружения"""
    async with AsyncSessionLocal() as session:
        # Проверяем, существует ли уже админ
        result = await session.execute(select(User).where(User.username == "admin"))
        admin_user = result.scalar_one_or_none()
        
        if not admin_user:
            # Создаем админа
            admin_user = User(
                username="admin",
                email="admin@example.com",
                password="admin123",  # Пароль для аутентификации (рекомендуется изменить)
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                # Заполняем токены из переменных окружения
                tinkoff_token=os.getenv("TINKOFF_TOKEN"),
                tinkoff_account_id=os.getenv("TINKOFF_ACCOUNT_ID"),
                tinkoff_sandbox=os.getenv("TINKOFF_SANDBOX", "false").lower() == "true",
                github_token=os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN"),
                google_calendar_credentials=os.getenv("GOOGLE_CALENDAR_CREDENTIALS"),
                google_calendar_id=os.getenv("CALENDAR_ID")
            )
            session.add(admin_user)
            await session.commit()
            print("✅ Пользователь-админ 'admin' создан с токенами из переменных окружения")
        else:
            # Обновляем токены админа из переменных окружения, если они изменились
            updated = False
            if os.getenv("TINKOFF_TOKEN") and admin_user.tinkoff_token != os.getenv("TINKOFF_TOKEN"):
                admin_user.tinkoff_token = os.getenv("TINKOFF_TOKEN")
                updated = True
            if os.getenv("TINKOFF_ACCOUNT_ID") and admin_user.tinkoff_account_id != os.getenv("TINKOFF_ACCOUNT_ID"):
                admin_user.tinkoff_account_id = os.getenv("TINKOFF_ACCOUNT_ID")
                updated = True
            if os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN") and admin_user.github_token != os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN"):
                admin_user.github_token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
                updated = True
            if os.getenv("GOOGLE_CALENDAR_CREDENTIALS") and admin_user.google_calendar_credentials != os.getenv("GOOGLE_CALENDAR_CREDENTIALS"):
                admin_user.google_calendar_credentials = os.getenv("GOOGLE_CALENDAR_CREDENTIALS")
                updated = True
            if os.getenv("CALENDAR_ID") and admin_user.google_calendar_id != os.getenv("CALENDAR_ID"):
                admin_user.google_calendar_id = os.getenv("CALENDAR_ID")
                updated = True
            
            # Обновляем пароль, если он не установлен
            if not admin_user.password:
                admin_user.password = "admin123"
                updated = True
            
            if updated:
                admin_user.updated_at = datetime.now().isoformat()
                session.add(admin_user)
                await session.commit()
                print("✅ Пользователь-админ 'admin' обновлен (токены и/или пароль)")
            else:
                print("ℹ️ Пользователь-админ 'admin' уже существует")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    # Clean up connections


# Запускаем инициализацию при старте
app = FastAPI(lifespan=lifespan)


# Вспомогательная функция для получения следующего sorting
async def next_sorting(session: AsyncSession) -> int:
    result = await session.execute(select(func.max(Task.sorting)))
    max_sort = result.scalar_one_or_none()
    return (max_sort or 0) + 1


# 1) Создать задачу
@app.post("/tasks/", response_model=Task)
async def create_task():
    async with AsyncSessionLocal() as session:
        task = Task(json_data=json.dumps({"message": "", "attachments": []}))
        task.sorting = await next_sorting(session)
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task


# 2) Получить все задачи (сортируя по полю sorting)
@app.get("/tasks/")
async def list_tasks():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Task).order_by(Task.sorting))
        tasks = result.scalars().all()
        new_tasks = []
        for task in tasks:
            new_task = task.dict()
            new_task["json_data"] = json.loads(task.json_data)
            new_tasks.append(new_task)
        return new_tasks


# 3) Получить конкретную задачу
@app.get("/tasks/{task_id}/", response_model=Task)
async def get_task(task_id: str):
    async with AsyncSessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        return task


# 4) Обновить задачу (json_data и/или steps)
class TaskUpdate(SQLModel):
    json_data: Optional[dict] = None
    steps: Optional[int] = None
    sorting: Optional[int] = None
    active: Optional[bool] = None


@app.put("/tasks/{task_id}/", response_model=Task)
async def update_task(task_id: str, task_update: TaskUpdate):
    async with AsyncSessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        if task_update.json_data is not None:
            task.json_data = json.dumps(task_update.json_data, ensure_ascii=False)
        if task_update.steps is not None:
            task.steps = task_update.steps
        if task_update.sorting is not None:
            task.sorting = task_update.sorting
        if task_update.active is not None:
            task.active = task_update.active
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task


# 5) Удалить задачу
@app.delete("/tasks/{task_id}/", status_code=204)
async def delete_task(task_id: str):
    async with AsyncSessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        await session.delete(task)
        await session.commit()


@app.get("/html/{html_id}/", response_class=HTMLResponse)
async def get_html(html_id: str):
    client = get_client(url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024"))
    result = await client.store.get_item(("html",), key=html_id)
    if result:
        return HTMLResponse(content=result["value"]["data"], status_code=200)
    else:
        raise HTTPException(404, "Page not found")


@app.post("/upload/image/")
async def upload_image(file: UploadFile = File(...)):
    file_bytes = await file.read()
    if is_llm_image_inline():
        uploaded_id = await upload_file_with_retry(
            (
                f"{uuid.uuid4()}.jpg",
                io.BytesIO(file_bytes),
            )
        )
    else:
        uploaded_id = str(uuid.uuid4())
    return {"id": uploaded_id}


# ========== USER MANAGEMENT API ==========

class UserCreate(SQLModel):
    username: str
    email: Optional[str] = None
    password: Optional[str] = None


class UserUpdate(SQLModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    tinkoff_token: Optional[str] = None
    tinkoff_account_id: Optional[str] = None
    tinkoff_sandbox: Optional[bool] = None
    github_token: Optional[str] = None
    google_calendar_credentials: Optional[str] = None
    google_calendar_id: Optional[str] = None


class UserResponse(SQLModel):
    id: str
    username: str
    email: Optional[str] = None
    created_at: str
    updated_at: str
    has_tinkoff_token: bool = False
    has_github_token: bool = False
    has_google_calendar: bool = False


@app.post("/users/", response_model=UserResponse)
async def create_user(user_data: UserCreate):
    """Создать нового пользователя"""
    async with AsyncSessionLocal() as session:
        # Проверяем, существует ли пользователь с таким username
        result = await session.execute(select(User).where(User.username == user_data.username))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(status_code=400, detail="User with this username already exists")
        
        # Проверяем, что пароль указан
        if not user_data.password or not user_data.password.strip():
            raise HTTPException(status_code=400, detail="Password is required")
        
        user = User(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password.strip(),  # Убираем пробелы в начале и конце
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        
        # Создаем сеанс пользователя в Redis при регистрации
        # (после регистрации обычно идет автоматический вход)
        try:
            from giga_agent.utils.redis_cache import create_user_session
            await create_user_session(user.id, ttl=2592000)
        except Exception as e:
            # Логируем ошибку, но не прерываем процесс регистрации
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"⚠️ Не удалось создать сеанс в Redis при регистрации: {e}")
        
        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            created_at=user.created_at,
            updated_at=user.updated_at,
            has_tinkoff_token=bool(user.tinkoff_token),
            has_github_token=bool(user.github_token),
            has_google_calendar=bool(user.google_calendar_credentials)
        )


@app.get("/users/", response_model=list[UserResponse])
async def list_users():
    """Получить список всех пользователей"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        return [
            UserResponse(
                id=user.id,
                username=user.username,
                email=user.email,
                created_at=user.created_at,
                updated_at=user.updated_at,
                has_tinkoff_token=bool(user.tinkoff_token),
                has_github_token=bool(user.github_token),
                has_google_calendar=bool(user.google_calendar_credentials)
            )
            for user in users
        ]


@app.get("/users/{user_id}/", response_model=UserResponse)
async def get_user(user_id: str):
    """Получить пользователя по ID"""
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            created_at=user.created_at,
            updated_at=user.updated_at,
            has_tinkoff_token=bool(user.tinkoff_token),
            has_github_token=bool(user.github_token),
            has_google_calendar=bool(user.google_calendar_credentials)
        )


@app.get("/users/username/{username}/", response_model=UserResponse)
async def get_user_by_username(username: str):
    """Получить пользователя по username"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            created_at=user.created_at,
            updated_at=user.updated_at,
            has_tinkoff_token=bool(user.tinkoff_token),
            has_github_token=bool(user.github_token),
            has_google_calendar=bool(user.google_calendar_credentials)
        )


@app.put("/users/{user_id}/", response_model=UserResponse)
async def update_user(user_id: str, user_update: UserUpdate):
    """Обновить данные пользователя"""
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Обновляем поля
        if user_update.username is not None:
            # Проверяем уникальность username
            if user_update.username != user.username:
                result = await session.execute(select(User).where(User.username == user_update.username))
                existing_user = result.scalar_one_or_none()
                if existing_user:
                    raise HTTPException(status_code=400, detail="User with this username already exists")
            user.username = user_update.username
        
        if user_update.email is not None:
            user.email = user_update.email
        
        if user_update.password is not None:
            # Обрезаем пробелы и проверяем, что пароль не пустой
            password_trimmed = user_update.password.strip() if user_update.password else ""
            if not password_trimmed:
                raise HTTPException(status_code=400, detail="Password cannot be empty")
            user.password = password_trimmed
        
        if user_update.tinkoff_token is not None:
            user.tinkoff_token = user_update.tinkoff_token
        
        if user_update.tinkoff_account_id is not None:
            user.tinkoff_account_id = user_update.tinkoff_account_id
        
        if user_update.tinkoff_sandbox is not None:
            user.tinkoff_sandbox = user_update.tinkoff_sandbox
        
        if user_update.github_token is not None:
            user.github_token = user_update.github_token
        
        if user_update.google_calendar_credentials is not None:
            user.google_calendar_credentials = user_update.google_calendar_credentials
        
        if user_update.google_calendar_id is not None:
            user.google_calendar_id = user_update.google_calendar_id
        
        user.updated_at = datetime.now().isoformat()
        
        session.add(user)
        await session.commit()
        await session.refresh(user)
        
        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            created_at=user.created_at,
            updated_at=user.updated_at,
            has_tinkoff_token=bool(user.tinkoff_token),
            has_github_token=bool(user.github_token),
            has_google_calendar=bool(user.google_calendar_credentials)
        )


@app.delete("/users/{user_id}/", status_code=204)
async def delete_user(user_id: str):
    """Удалить пользователя"""
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        await session.delete(user)
        await session.commit()


@app.get("/users/{user_id}/tokens/")
async def get_user_tokens(user_id: str):
    """Получить токены пользователя (без самих значений для безопасности)"""
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "has_tinkoff_token": bool(user.tinkoff_token),
            "has_github_token": bool(user.github_token),
            "has_google_calendar": bool(user.google_calendar_credentials),
            "tinkoff_account_id": user.tinkoff_account_id,
            "tinkoff_sandbox": user.tinkoff_sandbox,
            "google_calendar_id": user.google_calendar_id
        }


# ========== АУТЕНТИФИКАЦИЯ ==========

security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    username: str
    email: Optional[str] = None
    expires_at: str


class UserInfoResponse(BaseModel):
    user_id: str
    username: str
    email: Optional[str] = None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> User:
    """Получить текущего пользователя по токену"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    token = credentials.credentials
    
    async with AsyncSessionLocal() as session:
        # Ищем сессию по токену
        result = await session.execute(select(Session).where(Session.token == token))
        session_obj = result.scalar_one_or_none()
        
        if not session_obj:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        # Проверяем срок действия
        expires_at = datetime.fromisoformat(session_obj.expires_at)
        if datetime.now() > expires_at:
            # Удаляем истекшую сессию
            await session.delete(session_obj)
            await session.commit()
            raise HTTPException(status_code=401, detail="Сессия истекла")
        
        # Получаем пользователя
        user = await session.get(User, session_obj.user_id)
        if not user:
            raise HTTPException(status_code=401, detail="Пользователь не найден")
        
        # Явно отсоединяем объект User от сессии перед возвратом
        # Это гарантирует, что объект будет работать правильно после закрытия сессии
        # и все атрибуты будут доступны даже после ROLLBACK
        session.expunge(user)
        
        return user


@app.post("/auth/login", response_model=LoginResponse)
async def login(login_data: LoginRequest):
    """Вход в систему (поддерживает вход по username или email)"""
    async with AsyncSessionLocal() as session:
        # Ищем пользователя по username или email
        login_identifier = login_data.username.strip()
        result = await session.execute(
            select(User).where(
                (User.username == login_identifier) | (User.email == login_identifier)
            )
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        
        # Проверяем, что у пользователя установлен пароль
        if not user.password:
            raise HTTPException(status_code=401, detail="Пароль не установлен для этого пользователя. Обратитесь к администратору.")
        
        # Проверяем пароль (простая проверка, в будущем можно добавить хеширование)
        # Обрезаем пробелы для корректного сравнения
        stored_password = user.password.strip() if user.password else ""
        provided_password = login_data.password.strip() if login_data.password else ""
        
        if stored_password != provided_password:
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        
        # Удаляем все старые сессии пользователя перед созданием новой
        # Это предотвращает накопление сессий и возможные конфликты
        old_sessions_result = await session.execute(
            select(Session).where(Session.user_id == user.id)
        )
        old_sessions = old_sessions_result.scalars().all()
        for old_session in old_sessions:
            await session.delete(old_session)
        
        # Удаляем старый сеанс из Redis перед созданием нового
        # Это гарантирует, что при новом входе создается свежий сеанс
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🔍 Логин: Удаляем старый сеанс из Redis для user_id={user.id}")
        try:
            from giga_agent.utils.redis_cache import delete_user_session
            delete_result = await delete_user_session(user.id)
            logger.info(f"🔍 Логин: Результат удаления старого сеанса: {delete_result}")
        except Exception as e:
            # Логируем ошибку, но не прерываем процесс логина
            logger.error(f"❌ Не удалось удалить старый сеанс из Redis при логине: {e}", exc_info=True)
        
        # Создаем новую сессию
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(days=30)  # Сессия на 30 дней
        
        session_obj = Session(
            user_id=user.id,
            token=token,
            expires_at=expires_at.isoformat()
        )
        session.add(session_obj)
        await session.commit()
        
        # Создаем новый сеанс пользователя в Redis для кэширования
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🔍 Логин: Создаем новый сеанс в Redis для user_id={user.id}")
        try:
            from giga_agent.utils.redis_cache import create_user_session
            # Создаем сеанс с TTL 30 дней (2592000 секунд)
            create_result = await create_user_session(user.id, ttl=2592000)
            logger.info(f"🔍 Логин: Результат создания нового сеанса: {create_result}")
        except Exception as e:
            # Логируем ошибку, но не прерываем процесс логина
            logger.error(f"❌ Не удалось создать сеанс в Redis при логине: {e}", exc_info=True)
        
        return LoginResponse(
            token=token,
            user_id=user.id,
            username=user.username,
            email=user.email,
            expires_at=expires_at.isoformat()
        )


@app.post("/auth/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """Выход из системы"""
    async with AsyncSessionLocal() as session:
        # Находим и удаляем все сессии пользователя
        result = await session.execute(
            select(Session).where(Session.user_id == current_user.id)
        )
        sessions = result.scalars().all()
        
        for session_obj in sessions:
            await session.delete(session_obj)
        
        await session.commit()
        
        # Удаляем сеанс пользователя из Redis
        try:
            from giga_agent.utils.redis_cache import delete_user_session
            await delete_user_session(current_user.id)
        except Exception as e:
            # Логируем ошибку, но не прерываем процесс выхода
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"⚠️ Не удалось удалить сеанс из Redis при выходе: {e}")
        
        return {"message": "Выход выполнен успешно"}


@app.get("/auth/me", response_model=UserInfoResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Получить информацию о текущем пользователе"""
    return UserInfoResponse(
        user_id=current_user.id,
        username=current_user.username,
        email=current_user.email
    )


# ========== REDIS СЕССИИ ==========

class ThreadUserRequest(BaseModel):
    thread_id: str


@app.post("/api/redis/session/create")
async def create_redis_session(current_user: User = Depends(get_current_user)):
    """Создать сеанс пользователя в Redis (вызывается при авторизации)"""
    try:
        from giga_agent.utils.redis_cache import create_user_session
        result = await create_user_session(current_user.id, ttl=2592000)
        if result:
            return {"success": True, "message": f"Сеанс пользователя {current_user.id} создан в Redis"}
        else:
            raise HTTPException(status_code=500, detail="Не удалось создать сеанс в Redis")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Ошибка при создании сеанса в Redis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при создании сеанса в Redis: {str(e)}")


@app.post("/api/redis/thread/{thread_id}")
async def add_thread_to_redis_session(
    thread_id: str,
    current_user: User = Depends(get_current_user)
):
    """Добавить thread_id в сеанс пользователя в Redis (вызывается при создании потока)"""
    try:
        from giga_agent.utils.redis_cache import add_thread_to_user_session
        result = await add_thread_to_user_session(current_user.id, thread_id)
        if result:
            return {
                "success": True,
                "message": f"thread_id {thread_id} добавлен в сеанс пользователя {current_user.id}",
                "user_id": current_user.id,
                "thread_id": thread_id
            }
        else:
            raise HTTPException(status_code=500, detail="Не удалось добавить thread_id в сеанс")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Ошибка при добавлении thread_id в сеанс: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при добавлении thread_id в сеанс: {str(e)}")


class UserTokensResponse(BaseModel):
    """Ответ с токенами пользователя (только для текущего пользователя)"""
    tinkoff_token: Optional[str] = None
    tinkoff_account_id: Optional[str] = None
    tinkoff_sandbox: bool = False
    github_token: Optional[str] = None
    google_calendar_credentials: Optional[str] = None
    google_calendar_id: Optional[str] = None


@app.get("/auth/me/tokens", response_model=UserTokensResponse)
async def get_current_user_tokens(current_user: User = Depends(get_current_user)):
    """Получить токены текущего пользователя"""
    return UserTokensResponse(
        tinkoff_token=current_user.tinkoff_token,
        tinkoff_account_id=current_user.tinkoff_account_id,
        tinkoff_sandbox=current_user.tinkoff_sandbox,
        github_token=current_user.github_token,
        google_calendar_credentials=current_user.google_calendar_credentials,
        google_calendar_id=current_user.google_calendar_id
    )


# ========== ПОЧТОВЫЕ ЯЩИКИ ==========

class EmailAccountResponse(BaseModel):
    """Ответ с информацией о почтовом ящике"""
    id: str
    email: str
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int
    created_at: str
    updated_at: str


class EmailAccountCreateRequest(BaseModel):
    """Запрос на создание почтового ящика"""
    email: str
    password: str
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None


class EmailAccountUpdateRequest(BaseModel):
    """Запрос на обновление почтового ящика"""
    email: Optional[str] = None
    password: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None


@app.get("/email-accounts/", response_model=list[EmailAccountResponse])
async def get_user_email_accounts(current_user: User = Depends(get_current_user)):
    """Получить список почтовых ящиков текущего пользователя"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(EmailAccount)
            .where(EmailAccount.user_id == current_user.id)
            .order_by(EmailAccount.created_at.desc())
        )
        accounts = result.scalars().all()
        
        return [
            EmailAccountResponse(
                id=account.id,
                email=account.email,
                smtp_host=account.smtp_host,
                smtp_port=account.smtp_port,
                imap_host=account.imap_host,
                imap_port=account.imap_port,
                created_at=account.created_at,
                updated_at=account.updated_at
            )
            for account in accounts
        ]


@app.post("/email-accounts/", response_model=EmailAccountResponse)
async def create_email_account(
    account_data: EmailAccountCreateRequest,
    current_user: User = Depends(get_current_user)
):
    """Создать новый почтовый ящик"""
    async with AsyncSessionLocal() as session:
        # Проверяем, не существует ли уже ящик с таким email у этого пользователя
        existing = await session.execute(
            select(EmailAccount).where(
                EmailAccount.user_id == current_user.id,
                EmailAccount.email == account_data.email
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="Почтовый ящик с таким email уже существует"
            )
        
        # Если хосты и порты не указаны, используем типовые настройки
        from giga_agent.agents.email_agent.utils.email_providers import get_default_email_settings
        
        default_settings = get_default_email_settings(account_data.email)
        
        imap_host = account_data.imap_host or default_settings["imap_host"]
        imap_port = account_data.imap_port or default_settings["imap_port"]
        smtp_host = account_data.smtp_host or default_settings["smtp_host"]
        smtp_port = account_data.smtp_port or default_settings["smtp_port"]
        
        new_account = EmailAccount(
            user_id=current_user.id,
            email=account_data.email,
            password=account_data.password,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            imap_host=imap_host,
            imap_port=imap_port
        )
        
        session.add(new_account)
        await session.commit()
        await session.refresh(new_account)
        
        return EmailAccountResponse(
            id=new_account.id,
            email=new_account.email,
            smtp_host=new_account.smtp_host,
            smtp_port=new_account.smtp_port,
            imap_host=new_account.imap_host,
            imap_port=new_account.imap_port,
            created_at=new_account.created_at,
            updated_at=new_account.updated_at
        )


@app.get("/email-accounts/{account_id}/", response_model=EmailAccountResponse)
async def get_email_account(
    account_id: str,
    current_user: User = Depends(get_current_user)
):
    """Получить почтовый ящик по ID"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(EmailAccount).where(
                EmailAccount.id == account_id,
                EmailAccount.user_id == current_user.id
            )
        )
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(status_code=404, detail="Почтовый ящик не найден")
        
        return EmailAccountResponse(
            id=account.id,
            email=account.email,
            smtp_host=account.smtp_host,
            smtp_port=account.smtp_port,
            imap_host=account.imap_host,
            imap_port=account.imap_port,
            created_at=account.created_at,
            updated_at=account.updated_at
        )


@app.put("/email-accounts/{account_id}/", response_model=EmailAccountResponse)
async def update_email_account(
    account_id: str,
    account_data: EmailAccountUpdateRequest,
    current_user: User = Depends(get_current_user)
):
    """Обновить почтовый ящик"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(EmailAccount).where(
                EmailAccount.id == account_id,
                EmailAccount.user_id == current_user.id
            )
        )
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(status_code=404, detail="Почтовый ящик не найден")
        
        # Проверяем, не занят ли новый email другим ящиком
        if account_data.email and account_data.email != account.email:
            existing = await session.execute(
                select(EmailAccount).where(
                    EmailAccount.user_id == current_user.id,
                    EmailAccount.email == account_data.email,
                    EmailAccount.id != account_id
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=400,
                    detail="Почтовый ящик с таким email уже существует"
                )
        
        # Если email изменился и настройки не указаны явно, используем типовые настройки
        if account_data.email and account_data.email != account.email:
            from giga_agent.agents.email_agent.utils.email_providers import get_default_email_settings
            default_settings = get_default_email_settings(account_data.email)
            # Обновляем настройки только если они не указаны явно
            if account_data.imap_host is None:
                account.imap_host = default_settings["imap_host"]
            if account_data.imap_port is None:
                account.imap_port = default_settings["imap_port"]
            if account_data.smtp_host is None:
                account.smtp_host = default_settings["smtp_host"]
            if account_data.smtp_port is None:
                account.smtp_port = default_settings["smtp_port"]
        
        # Обновляем поля
        if account_data.email is not None:
            account.email = account_data.email
        if account_data.password is not None:
            account.password = account_data.password
        if account_data.smtp_host is not None:
            account.smtp_host = account_data.smtp_host
        if account_data.smtp_port is not None:
            account.smtp_port = account_data.smtp_port
        if account_data.imap_host is not None:
            account.imap_host = account_data.imap_host
        if account_data.imap_port is not None:
            account.imap_port = account_data.imap_port
        
        account.updated_at = datetime.now().isoformat()
        
        await session.commit()
        await session.refresh(account)
        
        return EmailAccountResponse(
            id=account.id,
            email=account.email,
            smtp_host=account.smtp_host,
            smtp_port=account.smtp_port,
            imap_host=account.imap_host,
            imap_port=account.imap_port,
            created_at=account.created_at,
            updated_at=account.updated_at
        )


@app.delete("/email-accounts/{account_id}/", status_code=204)
async def delete_email_account(
    account_id: str,
    current_user: User = Depends(get_current_user)
):
    """Удалить почтовый ящик"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(EmailAccount).where(
                EmailAccount.id == account_id,
                EmailAccount.user_id == current_user.id
            )
        )
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(status_code=404, detail="Почтовый ящик не найден")
        
        await session.delete(account)
        await session.commit()
