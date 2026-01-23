import asyncio
import io
import json
import os
import uuid
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import SQLModel, Field, select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import inspect, text
from pydantic import BaseModel

from langgraph_sdk import get_client
import httpx

from giga_agent.utils.env import load_project_env
from giga_agent.utils.llm import is_llm_image_inline, upload_file_with_retry, get_agent_env

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
    
    # Предпочтения пользователя (JSON строка)
    user_preferences: Optional[str] = None  # JSON строка с предпочтениями пользователя
    
    # Признак администратора
    is_admin: bool = Field(default=False, index=True)  # Является ли пользователь администратором


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


class Secret(SQLModel, table=True):
    """Модель секрета пользователя (API ключи, токены, пароли и т.д.)"""
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True, foreign_key="user.id")  # Владелец секрета
    name: str = Field(index=True)  # Название секрета (например, "api_key", "github_token")
    value: str = Field()  # Значение секрета
    description: Optional[str] = None  # Описание секрета
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class Chat(SQLModel, table=True):
    """Модель сохраненного чата пользователя"""
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True, foreign_key="user.id")  # Владелец чата
    thread_id: str = Field(index=True, unique=True)  # ID потока LangGraph
    title: str = Field()  # Название чата
    first_message: Optional[str] = None  # Первое сообщение
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ChatMessage(SQLModel, table=True):
    """Модель сообщения в чате (история общения)"""
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True, foreign_key="user.id")  # Владелец сообщения
    thread_id: str = Field(index=True)  # ID потока LangGraph (может быть несколько сообщений на один thread_id)
    role: str = Field()  # 'user' или 'assistant'
    content: str = Field()  # Содержимое сообщения
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class DeferredTask(SQLModel, table=True):
    """Модель отложенной задачи для админа"""
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True, foreign_key="user.id")  # Владелец задачи (админ)
    message: str = Field()  # Текст запроса пользователя
    priority: int = Field(default=0, index=True)  # Приоритет задачи (чем выше, тем важнее)
    status: str = Field(default="pending", index=True)  # Статус: pending, processing, completed, failed, revision
    task_type: str = Field(default="deferred", index=True)  # Тип задачи: "deferred" (отложенный) или "recurring" (регулярный)
    thread_id: Optional[str] = Field(default=None, index=True)  # ID потока LangGraph для выполнения задачи
    result_data: Optional[str] = Field(default=None)  # JSON строка с результатами выполнения
    error_message: Optional[str] = Field(default=None)  # Сообщение об ошибке, если задача провалилась
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), index=True)
    started_at: Optional[str] = Field(default=None)  # Время начала обработки
    completed_at: Optional[str] = Field(default=None)  # Время завершения обработки
    # Поля для регулярных задач
    schedule: Optional[str] = Field(default=None, index=True)  # Cron выражение или интервал для регулярных задач
    next_run_at: Optional[str] = Field(default=None, index=True)  # Время следующего выполнения регулярной задачи
    last_run_at: Optional[str] = Field(default=None)  # Время последнего выполнения регулярной задачи
    # Дополнительные данные для выполнения задачи (настройки, файлы и т.д.)
    task_config: Optional[str] = Field(default=None)  # JSON строка с конфигурацией задачи


# --- Настройка асинхронного движка и сессии ---
# Используем PostgreSQL из переменных окружения или дефолтное значение
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@aegra-postgres:5432/postgres"
)

# Создаем синхронный URL для миграций (убираем +asyncpg)
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")

engine: AsyncEngine = create_async_engine(
    DATABASE_URL, echo=True
)
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

# --- Выполняем миграции СИНХРОННО при импорте модуля ---
# Это критически важно - миграции должны выполниться ДО создания FastAPI приложения
def run_sync_migrations():
    """Выполняет миграции синхронно при импорте модуля"""
    try:
        from sqlalchemy import create_engine, inspect as sync_inspect, text as sync_text
        
        # Импортируем модели для создания таблиц
        from giga_agent.utils.query_pattern_cache import QueryPatternCache, Base
        
        # Создаем синхронный движок для миграций
        sync_engine = create_engine(SYNC_DATABASE_URL, echo=False)
        
        # Используем begin() для автоматического коммита транзакции
        with sync_engine.begin() as conn:
            # Проверяем, существует ли таблица user
            inspector = sync_inspect(sync_engine)
            tables = inspector.get_table_names()
            
            if "user" in tables:
                # Проверяем, существуют ли колонки user_preferences и is_admin
                columns = [col["name"] for col in inspector.get_columns("user")]
                if "user_preferences" not in columns:
                    # Добавляем колонку user_preferences
                    conn.execute(sync_text("ALTER TABLE \"user\" ADD COLUMN user_preferences TEXT DEFAULT '{}'"))
                    print("✅ Миграция (sync): Колонка 'user_preferences' добавлена в таблицу 'user'")
                else:
                    print("✅ Миграция (sync): Колонка 'user_preferences' уже существует")
                
                # Проверяем и добавляем колонку is_admin
                if "is_admin" not in columns:
                    # Добавляем колонку is_admin
                    conn.execute(sync_text("ALTER TABLE \"user\" ADD COLUMN is_admin BOOLEAN DEFAULT FALSE"))
                    print("✅ Миграция (sync): Колонка 'is_admin' добавлена в таблицу 'user'")
                else:
                    print("✅ Миграция (sync): Колонка 'is_admin' уже существует")
            else:
                print("ℹ️ Миграция (sync): Таблица 'user' еще не существует, будет создана через SQLModel")
            
            # Миграция для таблицы query_pattern_cache: создание таблицы для кэширования паттернов запросов
            if "query_pattern_cache" not in tables:
                # Создаем таблицу через Base.metadata
                try:
                    QueryPatternCache.__table__.create(bind=sync_engine, checkfirst=True)
                    print("✅ Миграция (sync): Таблица 'query_pattern_cache' создана")
                except Exception as e:
                    print(f"⚠️ Ошибка при создании таблицы 'query_pattern_cache': {e}")
            else:
                print("✅ Миграция (sync): Таблица 'query_pattern_cache' уже существует")
            
            # Миграция для таблицы deferredtask: добавление полей для регулярных задач
            if "deferredtask" in tables:
                deferredtask_columns = [col["name"] for col in inspector.get_columns("deferredtask")]
                
                # Добавляем поле task_type
                if "task_type" not in deferredtask_columns:
                    conn.execute(sync_text("ALTER TABLE deferredtask ADD COLUMN task_type VARCHAR DEFAULT 'deferred'"))
                    conn.execute(sync_text("CREATE INDEX IF NOT EXISTS idx_deferredtask_task_type ON deferredtask(task_type)"))
                    print("✅ Миграция (sync): Колонка 'task_type' добавлена в таблицу 'deferredtask'")
                else:
                    print("✅ Миграция (sync): Колонка 'task_type' уже существует")
                
                # Добавляем поле schedule
                if "schedule" not in deferredtask_columns:
                    conn.execute(sync_text("ALTER TABLE deferredtask ADD COLUMN schedule VARCHAR"))
                    conn.execute(sync_text("CREATE INDEX IF NOT EXISTS idx_deferredtask_schedule ON deferredtask(schedule)"))
                    print("✅ Миграция (sync): Колонка 'schedule' добавлена в таблицу 'deferredtask'")
                else:
                    print("✅ Миграция (sync): Колонка 'schedule' уже существует")
                
                # Добавляем поле next_run_at
                if "next_run_at" not in deferredtask_columns:
                    conn.execute(sync_text("ALTER TABLE deferredtask ADD COLUMN next_run_at VARCHAR"))
                    conn.execute(sync_text("CREATE INDEX IF NOT EXISTS idx_deferredtask_next_run_at ON deferredtask(next_run_at)"))
                    print("✅ Миграция (sync): Колонка 'next_run_at' добавлена в таблицу 'deferredtask'")
                else:
                    print("✅ Миграция (sync): Колонка 'next_run_at' уже существует")
                
                # Добавляем поле last_run_at
                if "last_run_at" not in deferredtask_columns:
                    conn.execute(sync_text("ALTER TABLE deferredtask ADD COLUMN last_run_at VARCHAR"))
                    print("✅ Миграция (sync): Колонка 'last_run_at' добавлена в таблицу 'deferredtask'")
                else:
                    print("✅ Миграция (sync): Колонка 'last_run_at' уже существует")
            else:
                print("ℹ️ Миграция (sync): Таблица 'deferredtask' еще не существует, будет создана через SQLModel")
        
        sync_engine.dispose()
    except Exception as e:
        print(f"⚠️ Ошибка при выполнении синхронных миграций: {e}")
        import traceback
        traceback.print_exc()
        # Не прерываем запуск, но логируем ошибку

# Выполняем миграции сразу при импорте модуля (ДО создания FastAPI приложения)
run_sync_migrations()


# --- Создаем таблицы ---
async def init_db():
    """Инициализация базы данных: создание всех таблиц при первичном запуске"""
    print("🔄 Инициализация базы данных...")
    
    # Проверяем, существует ли БД и какие таблицы есть
    try:
        inspector = inspect(engine.sync_engine)
        existing_tables = inspector.get_table_names()
        
        if not existing_tables:
            print("📝 Первичное создание базы данных - создаем все таблицы через SQLModel...")
        else:
            print(f"📊 База данных уже содержит таблицы: {existing_tables}")
            print("ℹ️ Проверяем необходимость обновления структур...")
    except Exception as e:
        print(f"⚠️ Ошибка при проверке существующих таблиц: {e}")
        existing_tables = []
    
    # Создаем все таблицы через SQLModel (это безопасно - не пересоздает существующие)
    async with engine.begin() as conn:
        # SQLModel.metadata.create_all создает только отсутствующие таблицы
        await conn.run_sync(SQLModel.metadata.create_all)
    
    print("✅ Все таблицы созданы/проверены через SQLModel")
    
    # Проверяем и добавляем колонки user_preferences и is_admin, если таблица user существует, но колонок нет
    try:
        inspector = inspect(engine.sync_engine)
        tables = inspector.get_table_names()
        
        if "user" in tables:
            columns = [col["name"] for col in inspector.get_columns("user")]
            if "user_preferences" not in columns:
                # Добавляем колонку user_preferences (миграция для существующей БД)
                async with engine.begin() as conn:
                    await conn.execute(
                        text("ALTER TABLE \"user\" ADD COLUMN user_preferences TEXT DEFAULT '{}'")
                    )
                print("✅ Колонка 'user_preferences' добавлена в таблицу 'user' (миграция)")
            else:
                print("✅ Колонка 'user_preferences' уже существует в таблице 'user'")
            
            # Проверяем и добавляем колонку is_admin
            if "is_admin" not in columns:
                # Добавляем колонку is_admin (миграция для существующей БД)
                async with engine.begin() as conn:
                    await conn.execute(
                        text("ALTER TABLE \"user\" ADD COLUMN is_admin BOOLEAN DEFAULT FALSE")
                    )
                print("✅ Колонка 'is_admin' добавлена в таблицу 'user' (миграция)")
            else:
                print("✅ Колонка 'is_admin' уже существует в таблице 'user'")
    except Exception as e:
        print(f"⚠️ Ошибка при проверке/добавлении колонок 'user_preferences' и 'is_admin': {e}")
        import traceback
        traceback.print_exc()
    
    # Проверяем и создаем таблицу chatmessage, если её нет
    try:
        inspector = inspect(engine.sync_engine)
        tables = inspector.get_table_names()
        
        if "chatmessage" not in tables:
            # Создаем таблицу chatmessage
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=[ChatMessage.__table__]))
            print("✅ Таблица 'chatmessage' создана")
        else:
            # Проверяем, что все колонки на месте
            columns = [col["name"] for col in inspector.get_columns("chatmessage")]
            required_columns = ["id", "user_id", "thread_id", "role", "content", "created_at"]
            missing_columns = [col for col in required_columns if col not in columns]
            
            if missing_columns:
                print(f"⚠️ В таблице 'chatmessage' отсутствуют колонки: {missing_columns}")
            else:
                print("✅ Таблица 'chatmessage' существует и содержит все необходимые колонки")
    except Exception as e:
        print(f"⚠️ Ошибка при проверке таблицы 'chatmessage': {e}")
        # Пытаемся создать таблицу принудительно
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=[ChatMessage.__table__]))
            print("✅ Таблица 'chatmessage' создана принудительно")
        except Exception as create_error:
            print(f"❌ Не удалось создать таблицу 'chatmessage': {create_error}")
    
    # Явная миграция для таблицы чатов (убеждаемся, что она создана)
    try:
        # Проверяем, существует ли таблица chat
        inspector = inspect(engine.sync_engine)
        tables = inspector.get_table_names()
        
        if "chat" not in tables:
            # Если таблицы нет, создаем её явно
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=[Chat.__table__]))
            print("✅ Таблица 'chat' создана")
        else:
            # Проверяем, что все колонки на месте
            columns = [col["name"] for col in inspector.get_columns("chat")]
            required_columns = ["id", "user_id", "thread_id", "title", "created_at", "updated_at"]
            missing_columns = [col for col in required_columns if col not in columns]
            
            if missing_columns:
                print(f"⚠️ В таблице 'chat' отсутствуют колонки: {missing_columns}")
                # В этом случае нужно будет создать миграцию Alembic
                # Пока просто предупреждаем
            else:
                print("✅ Таблица 'chat' существует и содержит все необходимые колонки")
    except Exception as e:
        print(f"⚠️ Ошибка при проверке таблицы 'chat': {e}")
        # Пытаемся создать таблицу принудительно
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=[Chat.__table__]))
            print("✅ Таблица 'chat' создана принудительно")
        except Exception as create_error:
            print(f"❌ Не удалось создать таблицу 'chat': {create_error}")
    
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
    # Убеждаемся, что колонки user_preferences и is_admin существуют перед запросом
    try:
        inspector = inspect(engine.sync_engine)
        if "user" in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns("user")]
            if "user_preferences" not in columns:
                # Добавляем колонку, если её нет
                async with engine.begin() as conn:
                    await conn.execute(
                        text("ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS user_preferences TEXT DEFAULT '{}'")
                    )
                print("✅ Колонка 'user_preferences' добавлена в таблицу 'user' (перед init_admin_user)")
            if "is_admin" not in columns:
                # Добавляем колонку is_admin, если её нет
                async with engine.begin() as conn:
                    await conn.execute(
                        text("ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE")
                    )
                print("✅ Колонка 'is_admin' добавлена в таблицу 'user'")
                # Обновляем inspector после добавления колонки
                inspector = inspect(engine.sync_engine)
                columns = [col["name"] for col in inspector.get_columns("user")]
        else:
            # Если таблицы user еще нет, она будет создана через SQLModel с полем is_admin
            print("ℹ️ Таблица 'user' еще не существует, будет создана через SQLModel")
    except Exception as e:
        print(f"⚠️ Ошибка при проверке колонок перед init_admin_user: {e}")
        import traceback
        traceback.print_exc()
    
    async with AsyncSessionLocal() as session:
        # Проверяем, есть ли уже пользователи в БД
        all_users_result = await session.execute(select(User).order_by(User.created_at))
        all_users = all_users_result.scalars().all()
        
        # ВАЖНО: Автоматически назначаем первого пользователя администратором
        # Это гарантирует, что при первом запуске или обновлении на VPS
        # первый пользователь всегда будет иметь права администратора
        # Это работает автоматически без ручных команд SQL
        if all_users:
            # Находим первого пользователя (по дате создания)
            first_user = all_users[0]
            
            # Проверяем, есть ли хотя бы один администратор
            admins_result = await session.execute(select(User).where(User.is_admin == True))
            admins = admins_result.scalars().all()
            
            # Если нет ни одного администратора, первый пользователь автоматически становится админом
            # Это важно при обновлении на VPS, когда поле is_admin было добавлено позже
            if len(admins) == 0:
                first_user.is_admin = True
                first_user.updated_at = datetime.now().isoformat()
                await session.commit()
                print(f"✅ Первый пользователь '{first_user.username}' (ID: {first_user.id}) автоматически назначен администратором (нет других админов)")
            elif not first_user.is_admin:
                # Если первый пользователь не является админом, но есть другие админы - оставляем как есть
                # Это нормальная ситуация, когда админ был назначен вручную
                print(f"ℹ️ Первый пользователь '{first_user.username}' не является администратором, но есть другие админы ({len(admins)})")
        
        # Проверяем, существует ли уже админ с username "alexis" (для обратной совместимости)
        result = await session.execute(select(User).where(User.username == "alexis"))
        admin_user = result.scalar_one_or_none()
        
        if not admin_user:
            # Создаем админа "alexis" только если его нет (для обратной совместимости)
            admin_user = User(
                username="alexis",
                email="alexis@ts-group.ru",
                password="admin123",  # Пароль для аутентификации
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                is_admin=True,  # Первый пользователь автоматически админ
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
            print("✅ Пользователь-админ 'alexis' создан с токенами из переменных окружения")
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
                print("✅ Пользователь-админ 'alexis' обновлен (токены и/или пароль)")
            else:
                print("ℹ️ Пользователь-админ 'alexis' уже существует")


# --- Миграция базы данных ---
async def run_migrations():
    """Выполняет миграции базы данных ДО запуска приложения"""
    try:
        async with engine.begin() as conn:
            # Проверяем, существует ли таблица user
            inspector = inspect(engine.sync_engine)
            tables = inspector.get_table_names()
            
            if "user" in tables:
                # Проверяем, существует ли колонка user_preferences
                columns = [col["name"] for col in inspector.get_columns("user")]
                if "user_preferences" not in columns:
                    # Добавляем колонку user_preferences
                    await conn.execute(
                        text("ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS user_preferences TEXT DEFAULT '{}'")
                    )
                    print("✅ Миграция: Колонка 'user_preferences' добавлена в таблицу 'user'")
                else:
                    print("✅ Миграция: Колонка 'user_preferences' уже существует")
            
            # Проверяем, существует ли таблица chatmessage
            if "chatmessage" not in tables:
                # Создаем таблицу chatmessage
                await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=[ChatMessage.__table__]))
                print("✅ Миграция: Таблица 'chatmessage' создана")
            else:
                print("✅ Миграция: Таблица 'chatmessage' уже существует")
                
    except Exception as e:
        print(f"⚠️ Ошибка при выполнении миграций: {e}")
        # Не прерываем запуск, но логируем ошибку
        import traceback
        traceback.print_exc()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ВАЖНО: Сначала выполняем миграции, потом инициализацию БД
    await run_migrations()
    await init_db()
    yield
    # Clean up connections


# Запускаем инициализацию при старте
app = FastAPI(lifespan=lifespan)

# Глобальный обработчик ошибок для гарантии JSON ответов
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    """Обработчик HTTP исключений - всегда возвращает JSON"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """Обработчик ошибок валидации - всегда возвращает JSON"""
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Глобальный обработчик всех исключений - всегда возвращает JSON"""
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"❌ Необработанное исключение: {type(exc).__name__}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Внутренняя ошибка сервера: {str(exc)}"}
    )

# Глобальное состояние обработки задач (по user_id)
task_processing_state: Dict[str, bool] = {}  # user_id -> is_processing
task_processing_tasks: Dict[str, asyncio.Task] = {}  # user_id -> background_task


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


@app.get("/api/model-info")
async def get_model_info(user_id: str = None):
    """Получение информации о текущей активной модели"""
    try:
        # ВАЖНО: Сначала проверяем Redis для всех провайдеров (deepseek, openai, openrouter)
        # Это обеспечивает правильное отображение провайдера после переключения
        llm_str = None
        try:
            import redis
            redis_uri = os.getenv("REDIS_URI", "redis://localhost:6379")
            redis_client = redis.from_url(redis_uri, decode_responses=True)
            env_key = get_agent_env()
            redis_key = f"provider:llm:{env_key}"
            saved_llm_str = redis_client.get(redis_key)
            if saved_llm_str:
                llm_str = saved_llm_str
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"[MODEL_INFO] ✅ Используется модель из Redis: {redis_key} = {llm_str}")
            else:
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"[MODEL_INFO] ⚠️ В Redis нет значения для ключа: {redis_key}")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"[MODEL_INFO] Не удалось получить модель из Redis: {e}")
        
        # Если в Redis нет значения, проверяем OpenRouter модели
        if not llm_str:
            try:
                from giga_agent.utils.llm import get_user_openrouter_model, get_openrouter_model_manager
                
                # Проверяем пользовательскую модель
                if user_id:
                    user_model = get_user_openrouter_model(user_id)
                    if user_model:
                        llm_str = f"openrouter:{user_model}"
                
                # Если нет пользовательской модели, проверяем глобальную из менеджера
                if not llm_str:
                    manager = get_openrouter_model_manager()
                    if manager and manager.current_model:
                        llm_str = f"openrouter:{manager.current_model}"
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"[MODEL_INFO] Не удалось получить модель OpenRouter: {e}")
        
        # Fallback на переменную окружения
        if not llm_str:
            llm_str = os.getenv(get_agent_env())
        
        if not llm_str:
            return {
                "model": "unknown",
                "displayName": "Модель не настроена",
                "provider": "unknown"
            }
        
        # Определяем провайдера
        provider = "unknown"
        display_name = llm_str
        
        if llm_str.startswith("gigachat:"):
            provider = "gigachat"
            display_name = llm_str.replace("gigachat:", "GigaChat ")
        elif llm_str.startswith("openrouter:"):
            provider = "openrouter"
            model_id = llm_str.replace("openrouter:", "")
            # Форматируем название модели
            display_name = model_id
            if "mistralai" in model_id:
                display_name = model_id.replace("mistralai/", "Mistral ").replace("devstral-", "Devstral ").replace(":free", " (free)")
            elif "google" in model_id:
                display_name = model_id.replace("google/", "Google ").replace(":free", " (free)")
            elif "meta-llama" in model_id:
                display_name = model_id.replace("meta-llama/", "Meta ").replace(":free", " (free)")
            elif "deepseek" in model_id.lower():
                display_name = model_id.replace("deepseek/", "DeepSeek ").replace(":free", " (free)")
        elif llm_str.startswith("deepseek:"):
            # Поддержка префикса deepseek:
            provider = "deepseek"
            model_id = llm_str.replace("deepseek:", "")
            # Форматируем название модели
            if model_id == "deepseek-reasoner":
                display_name = "DeepSeek Chat"
            elif model_id == "deepseek-reasoner":
                display_name = "DeepSeek Reasoner"
            else:
                display_name = model_id.replace("deepseek-", "DeepSeek ").replace("deepseek/", "DeepSeek ")
        elif llm_str.startswith("openai:"):
            # Поддержка префикса openai:
            provider = "openai"
            model_id = llm_str.replace("openai:", "")
            # Форматируем название модели
            if model_id.startswith("gpt-4o"):
                display_name = "GPT-4o"
            elif model_id.startswith("gpt-4"):
                display_name = f"GPT-4 {model_id.replace('gpt-4', '').replace('-', ' ').strip() or 'Turbo'}"
            elif model_id.startswith("gpt-3.5"):
                display_name = "GPT-3.5 Turbo"
            else:
                display_name = f"OpenAI {model_id}"
        elif "deepseek" in llm_str.lower():
            # Старый формат без префикса
            provider = "deepseek"
            display_name = llm_str.replace("deepseek-", "DeepSeek ").replace("deepseek/", "DeepSeek ")
        else:
            provider = "other"
            display_name = llm_str
        
        return {
            "model": llm_str,
            "displayName": display_name,
            "provider": provider
        }
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка при получении информации о модели: {e}")
        return {
            "model": "unknown",
            "displayName": "Ошибка загрузки",
            "provider": "unknown"
        }


@app.post("/api/openrouter/clear-cache")
async def clear_openrouter_cache(
    user_id: str = None,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False))
):
    """
    Очистка кэша OpenRouter (модели пользователя и глобальной модели).
    
    Если указан user_id - очищает только модель этого пользователя.
    Если user_id не указан - очищает глобальную модель и модель текущего пользователя.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Логируем начало выполнения
    logger.info("=" * 80)
    logger.info("[clear-cache] ========== НАЧАЛО ОЧИСТКИ КЭША ==========")
    logger.info(f"[clear-cache] Получен запрос на очистку кэша, user_id параметр: {user_id}")
    
    try:
        # Получаем user_id из токена, если не передан явно
        current_user_id = user_id
        logger.info(f"[clear-cache] Начальный current_user_id: {current_user_id}")
        if not current_user_id and credentials:
            logger.info("[clear-cache] Получение user_id из токена...")
            async for session in get_session():
                user = await get_current_user(credentials, session)
                if user:
                    current_user_id = user.id
                    logger.info(f"[clear-cache] Получен user_id из токена: {current_user_id}")
                break
        
        logger.info(f"[clear-cache] Финальный current_user_id: {current_user_id}")
        cleared_items = []
        
        # Значения по умолчанию для провайдера и модели
        DEFAULT_MODEL = "mistralai/devstral-2512:free"
        DEFAULT_PROVIDER = "openrouter"
        DEFAULT_LLM_STR = f"{DEFAULT_PROVIDER}:{DEFAULT_MODEL}"
        
        # Очищаем кэш в Redis
        logger.info("[clear-cache] Начало блока очистки кэша в Redis...")
        try:
            logger.info("[clear-cache] Импорт модулей...")
            from giga_agent.utils.llm import clear_user_openrouter_model, get_openrouter_model_manager
            from giga_agent.utils.redis_cache import get_redis_client
            logger.info("[clear-cache] Модули успешно импортированы")
            
            # Очищаем модель пользователя
            if current_user_id:
                logger.info(f"[clear-cache] Очистка модели пользователя: {current_user_id}")
                clear_user_openrouter_model(current_user_id)
                cleared_items.append(f"user_model:{current_user_id}")
                logger.info(f"[clear-cache] ✅ Очищена модель пользователя: {current_user_id}")
            else:
                logger.info("[clear-cache] current_user_id не установлен, пропускаем очистку модели пользователя")
            
            # Очищаем глобальную модель
            try:
                redis = await get_redis_client()
                if redis:
                    # Удаляем глобальную модель
                    result = await redis.delete("openrouter:current_model")
                    cleared_items.append(f"current_model (deleted={result})")
                    logger.info(f"[clear-cache] Очищена глобальная модель (deleted={result})")
                    
                    # Также удаляем модель пользователя из Redis напрямую
                    if current_user_id:
                        user_key = f"openrouter:user_model:{current_user_id}"
                        result2 = await redis.delete(user_key)
                        cleared_items.append(f"user_redis_model (deleted={result2})")
                        logger.info(f"[clear-cache] Удален ключ {user_key} (deleted={result2})")
                else:
                    logger.warning("[clear-cache] Redis клиент не доступен")
            except Exception as redis_err:
                logger.warning(f"[clear-cache] Не удалось очистить глобальную модель из Redis: {redis_err}", exc_info=True)
            
            # Сбрасываем менеджер моделей и очищаем файл состояния
            manager = get_openrouter_model_manager()
            if manager:
                manager.current_model = None
                # Очищаем current_model в switching_state
                if hasattr(manager, 'switching_state'):
                    manager.switching_state["current_model"] = None
                    # Сохраняем очищенное состояние в файл
                    try:
                        if hasattr(manager, 'state_file') and manager.state_file:
                            import json
                            manager.state_file.parent.mkdir(parents=True, exist_ok=True)
                            with open(manager.state_file, 'w', encoding='utf-8') as f:
                                json.dump(manager.switching_state, f, ensure_ascii=False, indent=2)
                            cleared_items.append("state_file")
                            logger.info(f"[clear-cache] Очищен файл состояния: {manager.state_file}")
                    except Exception as file_err:
                        logger.warning(f"[clear-cache] Не удалось очистить файл состояния: {file_err}")
                cleared_items.append("manager_state")
                logger.info("[clear-cache] Сброшено состояние менеджера моделей")
            
            # Сбрасываем LLM singleton для перезагрузки модели
            try:
                from giga_agent.utils.llm import reset_llm_singleton
                reset_llm_singleton(tag=None, is_main=True)
                reset_llm_singleton(tag=None, is_main=False)
                cleared_items.append("llm_singleton")
                logger.info("[clear-cache] Сброшен LLM singleton")
            except Exception as singleton_err:
                logger.warning(f"[clear-cache] Не удалось сбросить LLM singleton: {singleton_err}")
            
            # ПОЛНАЯ ОЧИСТКА ВСЕХ КЭШЕЙ
            try:
                from giga_agent.utils.redis_cache import get_redis_client
                redis = await get_redis_client()
                if redis:
                    # 1. Удаляем ВСЕ ключи query_pattern_cache в Redis
                    keys = await redis.keys("query_pattern_cache:*")
                    if keys:
                        deleted_count = await redis.delete(*keys)
                        cleared_items.append(f"query_cache_redis (deleted={deleted_count})")
                        logger.info(f"[clear-cache] Удалено {deleted_count} ключей query_pattern_cache из Redis")
                    
                    # 2. Удаляем ВСЕ ключи openrouter в Redis
                    or_keys = await redis.keys("openrouter:*")
                    if or_keys:
                        or_deleted = await redis.delete(*or_keys)
                        cleared_items.append(f"openrouter_redis (deleted={or_deleted})")
                        logger.info(f"[clear-cache] Удалено {or_deleted} ключей openrouter из Redis")
                    
                    # 3. Удаляем кэш user sessions (кроме текущего)
                    session_keys = await redis.keys("user_session:*")
                    if session_keys and current_user_id:
                        # Оставляем только текущую сессию
                        current_session_key = f"user_session:{current_user_id}"
                        keys_to_delete = [k for k in session_keys if k != current_session_key]
                        if keys_to_delete:
                            sess_deleted = await redis.delete(*keys_to_delete)
                            cleared_items.append(f"other_sessions_redis (deleted={sess_deleted})")
                    
                    # 4. Удаляем tool_calls кэш
                    tool_keys = await redis.keys("tool_call:*")
                    if tool_keys:
                        tool_deleted = await redis.delete(*tool_keys)
                        cleared_items.append(f"tool_calls_redis (deleted={tool_deleted})")
                
                # ПОЛНАЯ ОЧИСТКА PostgreSQL query_pattern_cache
                try:
                    from sqlalchemy import text
                    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
                    from sqlalchemy.orm import sessionmaker
                    import os
                    
                    db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@aegra-postgres:5432/postgres")
                    engine = create_async_engine(db_url, echo=False)
                    async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
                    
                    async with async_session_factory() as session:
                        # Удаляем ВСЕ записи из query_pattern_cache (полный сброс)
                        result = await session.execute(
                            text("DELETE FROM query_pattern_cache")
                        )
                        await session.commit()
                        cleared_items.append(f"query_cache_postgres_ALL (deleted={result.rowcount})")
                        logger.info(f"[clear-cache] ПОЛНАЯ ОЧИСТКА: удалено {result.rowcount} записей query_pattern_cache из PostgreSQL")
                except Exception as pg_err:
                    logger.warning(f"[clear-cache] Не удалось очистить query_pattern_cache в PostgreSQL: {pg_err}")
                
                # После ПОЛНОЙ очистки - устанавливаем провайдер openrouter и модель по умолчанию
                try:
                    # Устанавливаем провайдер openrouter в Redis
                    from giga_agent.utils.llm import get_agent_env
                    env_key = get_agent_env()
                    redis_key = f"provider:llm:{env_key}"
                    
                    if redis:
                        # Сохраняем провайдер и модель в Redis
                        await redis.set(redis_key, DEFAULT_LLM_STR)
                        # Проверяем, что значение действительно сохранено
                        saved_value = await redis.get(redis_key)
                        if saved_value == DEFAULT_LLM_STR:
                            cleared_items.append(f"set_provider:{DEFAULT_PROVIDER}")
                            cleared_items.append(f"set_model:{DEFAULT_MODEL}")
                            logger.info(f"[clear-cache] ✅ Установлен провайдер {DEFAULT_PROVIDER} с моделью {DEFAULT_MODEL} в Redis: {redis_key} = {DEFAULT_LLM_STR} (проверено: {saved_value})")
                        else:
                            logger.error(f"[clear-cache] ❌ ОШИБКА: Значение в Redis не совпадает! Ожидалось: {DEFAULT_LLM_STR}, получено: {saved_value}")
                            cleared_items.append(f"ERROR:redis_mismatch")
                        
                        # Также устанавливаем модель пользователя в openrouter кэш
                        if current_user_id:
                            user_key = f"openrouter:user_model:{current_user_id}"
                            await redis.set(user_key, DEFAULT_MODEL)
                            cleared_items.append(f"set_user_model:{DEFAULT_MODEL}")
                            logger.info(f"[clear-cache] Установлена модель пользователя {current_user_id}: {DEFAULT_MODEL}")
                    
                    # Также устанавливаем в переменную окружения (если возможно)
                    try:
                        import os
                        os.environ[env_key] = DEFAULT_LLM_STR
                        logger.info(f"[clear-cache] Установлена переменная окружения {env_key} = {DEFAULT_LLM_STR}")
                    except Exception as env_err:
                        logger.debug(f"[clear-cache] Не удалось установить переменную окружения (это нормально в Docker): {env_err}")
                    
                    # Сбрасываем singleton для применения нового провайдера
                    try:
                        from giga_agent.utils.llm import reset_all_llm_singletons_for_env
                        reset_all_llm_singletons_for_env(env_key)
                        cleared_items.append("reset_llm_singleton")
                        logger.info(f"[clear-cache] Сброшены все singleton для {env_key}")
                    except Exception as reset_err:
                        logger.warning(f"[clear-cache] Не удалось сбросить singleton: {reset_err}")
                        
                except Exception as set_err:
                    logger.warning(f"[clear-cache] Не удалось установить провайдер и модель по умолчанию: {set_err}", exc_info=True)
                    
            except Exception as cache_err:
                logger.warning(f"[clear-cache] Не удалось очистить кэши: {cache_err}")
            
        except ImportError as ie:
            logger.error(f"[clear-cache] ❌❌❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать модули: {ie}", exc_info=True)
            import traceback
            logger.error(f"[clear-cache] Traceback:\n{traceback.format_exc()}")
        
        logger.info(f"[clear-cache] ========== ЗАВЕРШЕНИЕ ОЧИСТКИ КЭША ==========")
        logger.info(f"[clear-cache] Итоговые cleared_items: {cleared_items}")
        logger.info(f"[clear-cache] Провайдер: {DEFAULT_PROVIDER}, Модель: {DEFAULT_MODEL}")
        logger.info("=" * 80)
        
        return {
            "success": True,
            "message": f"ПОЛНЫЙ СБРОС выполнен. Все кэши очищены. Провайдер: {DEFAULT_PROVIDER}, Модель: {DEFAULT_MODEL}",
            "cleared_items": cleared_items,
            "user_id": current_user_id,
            "default_provider": DEFAULT_PROVIDER,
            "default_model": DEFAULT_MODEL
        }
        
    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"[clear-cache] ❌❌❌ КРИТИЧЕСКАЯ ОШИБКА при очистке кэша: {e}", exc_info=True)
        logger.error("=" * 80)
        raise HTTPException(status_code=500, detail=f"Ошибка при очистке кэша: {str(e)}")


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
    user_preferences: Optional[str] = None  # JSON строка с предпочтениями пользователя
    is_admin: Optional[bool] = None  # Изменение статуса администратора (только для админов)


class UserResponse(SQLModel):
    id: str
    username: str
    email: Optional[str] = None
    created_at: str
    updated_at: str
    has_tinkoff_token: bool = False
    has_github_token: bool = False
    has_google_calendar: bool = False
    is_admin: bool = False  # Признак администратора


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
    is_admin: bool = False


class UserInfoResponse(BaseModel):
    user_id: str
    username: str
    email: Optional[str] = None
    is_admin: bool = False


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> User:
    """Получить текущего пользователя по токену"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not credentials:
        logger.warning("[AUTH] get_current_user: credentials отсутствуют")
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    token = credentials.credentials
    logger.debug(f"[AUTH] get_current_user: получен токен, длина={len(token) if token else 0}, первые 10 символов={token[:10] if token else 'N/A'}")
    
    async with AsyncSessionLocal() as session:
        # Ищем сессию по токену
        result = await session.execute(select(Session).where(Session.token == token))
        session_obj = result.scalar_one_or_none()
        
        if not session_obj:
            logger.warning(f"[AUTH] get_current_user: сессия не найдена для токена (первые 10 символов: {token[:10] if token else 'N/A'})")
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        logger.debug(f"[AUTH] get_current_user: сессия найдена, user_id={session_obj.user_id}, expires_at={session_obj.expires_at}")
        
        # Проверяем срок действия
        expires_at = datetime.fromisoformat(session_obj.expires_at)
        if datetime.now() > expires_at:
            # Удаляем истекшую сессию
            logger.warning(f"[AUTH] get_current_user: сессия истекла, expires_at={expires_at}, now={datetime.now()}")
            await session.delete(session_obj)
            await session.commit()
            raise HTTPException(status_code=401, detail="Сессия истекла")
        
        # Получаем пользователя
        user = await session.get(User, session_obj.user_id)
        if not user:
            logger.error(f"[AUTH] get_current_user: пользователь не найден, user_id={session_obj.user_id}")
            raise HTTPException(status_code=401, detail="Пользователь не найден")
        
        logger.debug(f"[AUTH] get_current_user: пользователь найден, user_id={user.id}, username={user.username}")
        
        # Явно отсоединяем объект User от сессии перед возвратом
        # Это гарантирует, что объект будет работать правильно после закрытия сессии
        # и все атрибуты будут доступны даже после ROLLBACK
        session.expunge(user)
        
        return user


# ========== USER MANAGEMENT API ==========

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
        
        # Проверяем, есть ли уже пользователи в БД (первый пользователь автоматически админ)
        all_users_result = await session.execute(select(User))
        all_users = all_users_result.scalars().all()
        is_first_user = len(all_users) == 0
        
        user = User(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password.strip(),  # Убираем пробелы в начале и конце
            is_admin=is_first_user,  # Первый пользователь автоматически становится админом
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
            has_google_calendar=bool(user.google_calendar_credentials),
            is_admin=user.is_admin if hasattr(user, 'is_admin') else False
        )


@app.get("/users/", response_model=list[UserResponse])
async def list_users(current_user: User = Depends(get_current_user)):
    """Получить список всех пользователей (только для администраторов)"""
    # Проверяем права администратора
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    
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
                has_google_calendar=bool(user.google_calendar_credentials),
                is_admin=user.is_admin if hasattr(user, 'is_admin') else False
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
            has_google_calendar=bool(user.google_calendar_credentials),
            is_admin=user.is_admin if hasattr(user, 'is_admin') else False
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
            has_google_calendar=bool(user.google_calendar_credentials),
            is_admin=user.is_admin if hasattr(user, 'is_admin') else False
        )


@app.put("/users/{user_id}/", response_model=UserResponse)
async def update_user(
    user_id: str, 
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user)
):
    """Обновить данные пользователя"""
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Проверяем права на изменение is_admin (только админы могут менять статус админа)
        if user_update.is_admin is not None:
            if not is_admin_user(current_user):
                raise HTTPException(
                    status_code=403, 
                    detail="Только администраторы могут изменять статус администратора"
                )
            
            # Проверяем, что не пытаются снять последнего админа
            if user.is_admin and not user_update.is_admin:
                # Подсчитываем количество админов
                admins_result = await session.execute(select(User).where(User.is_admin == True))
                admins = admins_result.scalars().all()
                if len(admins) <= 1:
                    raise HTTPException(
                        status_code=400,
                        detail="Невозможно снять последнего администратора. В системе должен быть хотя бы один администратор."
                    )
            
            user.is_admin = user_update.is_admin
        
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
        
        if user_update.user_preferences is not None:
            user.user_preferences = user_update.user_preferences
        
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
            has_google_calendar=bool(user.google_calendar_credentials),
            is_admin=user.is_admin if hasattr(user, 'is_admin') else False
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
            expires_at=expires_at.isoformat(),
            is_admin=user.is_admin if hasattr(user, 'is_admin') else False
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
        email=current_user.email,
        is_admin=current_user.is_admin if hasattr(current_user, 'is_admin') else False
    )


# ========== REDIS СЕССИИ ==========

class ThreadUserRequest(BaseModel):
    thread_id: str


@app.post("/api/redis/session/create")
async def create_redis_session(current_user: User = Depends(get_current_user)):
    """Создать сеанс пользователя в Redis (вызывается при авторизации)"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        from giga_agent.utils.redis_cache import create_user_session
        logger.info(f"🔍 create_redis_session: попытка создания сеанса для user_id={current_user.id}")
        result = await create_user_session(current_user.id, ttl=2592000)
        if result:
            logger.info(f"✅ create_redis_session: сеанс создан для user_id={current_user.id}")
            return {"success": True, "message": f"Сеанс пользователя {current_user.id} создан в Redis"}
        else:
            logger.warning(f"⚠️ create_redis_session: не удалось создать сеанс для user_id={current_user.id} (Redis может быть недоступен)")
            # Не выбрасываем ошибку, если Redis недоступен - это не критично для работы системы
            return {"success": False, "message": "Redis недоступен, сеанс не создан (не критично)"}
    except HTTPException:
        # Пробрасываем HTTPException как есть
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка при создании сеанса в Redis для user_id={current_user.id}: {e}", exc_info=True)
        # Не выбрасываем ошибку, если Redis недоступен - это не критично для работы системы
        return {"success": False, "message": f"Redis недоступен: {str(e)} (не критично)"}


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
    user_preferences: Optional[str] = None  # JSON строка с предпочтениями пользователя


@app.get("/auth/me/tokens", response_model=UserTokensResponse)
async def get_current_user_tokens(current_user: User = Depends(get_current_user)):
    """
    Получить токены текущего пользователя.
    
    Безопасность:
    - Требует аутентификации через get_current_user
    - Использует endpoint /auth/me/tokens - возвращает только данные текущего пользователя
    - Предпочтения возвращаются только для текущего пользователя
    """
    # ВАЖНО: current_user уже содержит данные текущего аутентифицированного пользователя
    return UserTokensResponse(
        tinkoff_token=current_user.tinkoff_token,
        tinkoff_account_id=current_user.tinkoff_account_id,
        tinkoff_sandbox=current_user.tinkoff_sandbox,
        github_token=current_user.github_token,
        google_calendar_credentials=current_user.google_calendar_credentials,
        google_calendar_id=current_user.google_calendar_id,
        user_preferences=current_user.user_preferences  # Предпочтения текущего пользователя
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


# ========== ПРЕДПОЧТЕНИЯ ПОЛЬЗОВАТЕЛЯ ==========

class UserPreferencesResponse(BaseModel):
    """Ответ с предпочтениями пользователя"""
    user_preferences: Optional[str] = None  # JSON строка с предпочтениями


class UserPreferencesUpdateRequest(BaseModel):
    """Запрос на обновление предпочтений пользователя"""
    user_preferences: Optional[str] = None  # JSON строка с предпочтениями


@app.get("/auth/me/preferences", response_model=UserPreferencesResponse)
async def get_current_user_preferences(current_user: User = Depends(get_current_user)):
    """
    Получить предпочтения текущего пользователя.
    
    ВАЖНО: Каждый пользователь получает ТОЛЬКО свои индивидуальные настройки.
    Пользователь определяется автоматически по токену аутентификации через get_current_user.
    Настройки хранятся в поле user_preferences таблицы user для конкретного пользователя.
    
    Безопасность:
    - Требует аутентификации через get_current_user
    - Использует endpoint /auth/me/preferences - возвращает только предпочтения текущего пользователя
    - Пользователь не может получить предпочтения других пользователей
    - Изоляция данных гарантируется на уровне БД (каждая запись user имеет свой user_preferences)
    """
    try:
        # ВАЖНО: current_user уже содержит данные текущего аутентифицированного пользователя
        # Токен из заголовка Authorization автоматически определяет, какого пользователя вернуть
        return UserPreferencesResponse(
            user_preferences=current_user.user_preferences
        )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Ошибка при получении предпочтений для user_id={current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при получении предпочтений: {str(e)}")


@app.put("/auth/me/preferences", response_model=UserPreferencesResponse)
async def update_current_user_preferences(
    preferences_data: UserPreferencesUpdateRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Обновить предпочтения текущего пользователя.
    
    ВАЖНО: Каждый пользователь может обновить ТОЛЬКО свои индивидуальные настройки.
    Пользователь определяется автоматически по токену аутентификации через get_current_user.
    Настройки сохраняются в поле user_preferences таблицы user для конкретного пользователя.
    При смене пользователя (другой токен) настройки автоматически загружаются для нового пользователя.
    
    Безопасность:
    - Требует аутентификации через get_current_user
    - Использует endpoint /auth/me/preferences - обновляет только предпочтения текущего пользователя
    - Обновляет предпочтения только для пользователя с ID = current_user.id
    - Пользователь не может обновить предпочтения других пользователей
    - Изоляция данных гарантируется на уровне БД (каждая запись user имеет свой user_preferences)
    """
    async with AsyncSessionLocal() as session:
        # ВАЖНО: Получаем пользователя по ID текущего аутентифицированного пользователя
        # Токен из заголовка Authorization автоматически определяет, какого пользователя обновить
        user = await session.get(User, current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Обновляем предпочтения только для текущего пользователя
        # Это гарантирует, что каждый пользователь изменяет только свои настройки
        if preferences_data.user_preferences is not None:
            # Проверяем, что это валидный JSON (если не пусто)
            if preferences_data.user_preferences.strip():
                try:
                    json.loads(preferences_data.user_preferences)
                except json.JSONDecodeError:
                    raise HTTPException(status_code=400, detail="user_preferences must be valid JSON")
            # ВАЖНО: Обновляем предпочтения только для текущего пользователя
            # Настройки сохраняются в поле user_preferences конкретной записи user в БД
            user.user_preferences = preferences_data.user_preferences
        
        user.updated_at = datetime.now().isoformat()
        
        await session.commit()
        await session.refresh(user)
        
        return UserPreferencesResponse(
            user_preferences=user.user_preferences
        )


# ========== СЕКРЕТЫ ==========

class SecretResponse(BaseModel):
    """Ответ с информацией о секрете"""
    id: str
    name: str
    value: str
    description: Optional[str] = None
    created_at: str
    updated_at: str


class SecretCreateRequest(BaseModel):
    """Запрос на создание секрета"""
    name: str
    value: str
    description: Optional[str] = None


class SecretUpdateRequest(BaseModel):
    """Запрос на обновление секрета"""
    name: Optional[str] = None
    value: Optional[str] = None
    description: Optional[str] = None


@app.get("/secrets/", response_model=list[SecretResponse])
async def get_user_secrets(current_user: User = Depends(get_current_user)):
    """
    Получить список секретов текущего пользователя.
    
    Безопасность: 
    - Требует аутентификации через get_current_user
    - Фильтрует секреты только по user_id текущего пользователя
    - Пользователь не может получить секреты других пользователей
    """
    async with AsyncSessionLocal() as session:
        # ВАЖНО: Фильтруем только секреты текущего пользователя
        result = await session.execute(
            select(Secret)
            .where(Secret.user_id == current_user.id)
            .order_by(Secret.created_at.desc())
        )
        secrets = result.scalars().all()
        
        return [
            SecretResponse(
                id=secret.id,
                name=secret.name,
                value=secret.value,
                description=secret.description,
                created_at=secret.created_at,
                updated_at=secret.updated_at
            )
            for secret in secrets
        ]


@app.post("/secrets/", response_model=SecretResponse)
async def create_secret(
    secret_data: SecretCreateRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Создать новый секрет.
    
    Безопасность:
    - Требует аутентификации через get_current_user
    - Секрет автоматически привязывается к текущему пользователю (user_id=current_user.id)
    - Проверка уникальности имени секрета только в рамках текущего пользователя
    """
    async with AsyncSessionLocal() as session:
        # ВАЖНО: Проверяем уникальность только среди секретов текущего пользователя
        existing = await session.execute(
            select(Secret).where(
                Secret.user_id == current_user.id,
                Secret.name == secret_data.name
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="Секрет с таким именем уже существует"
            )
        
        # ВАЖНО: Секрет создается с user_id текущего пользователя
        new_secret = Secret(
            user_id=current_user.id,  # Привязка к текущему пользователю
            name=secret_data.name,
            value=secret_data.value,
            description=secret_data.description
        )
        
        session.add(new_secret)
        await session.commit()
        await session.refresh(new_secret)
        
        return SecretResponse(
            id=new_secret.id,
            name=new_secret.name,
            value=new_secret.value,
            description=new_secret.description,
            created_at=new_secret.created_at,
            updated_at=new_secret.updated_at
        )


@app.get("/secrets/{secret_id}/", response_model=SecretResponse)
async def get_secret(
    secret_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Получить секрет по ID.
    
    Безопасность:
    - Требует аутентификации через get_current_user
    - Проверяет, что секрет принадлежит текущему пользователю
    - Если секрет принадлежит другому пользователю, вернет 404 (не найден)
    """
    async with AsyncSessionLocal() as session:
        # ВАЖНО: Проверяем и ID секрета, и принадлежность текущему пользователю
        result = await session.execute(
            select(Secret).where(
                Secret.id == secret_id,
                Secret.user_id == current_user.id  # Защита от доступа к чужим секретам
            )
        )
        secret = result.scalar_one_or_none()
        
        # Если секрет не найден или принадлежит другому пользователю - возвращаем 404
        if not secret:
            raise HTTPException(status_code=404, detail="Секрет не найден")
        
        return SecretResponse(
            id=secret.id,
            name=secret.name,
            value=secret.value,
            description=secret.description,
            created_at=secret.created_at,
            updated_at=secret.updated_at
        )


@app.put("/secrets/{secret_id}/", response_model=SecretResponse)
async def update_secret(
    secret_id: str,
    secret_data: SecretUpdateRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Обновить секрет.
    
    Безопасность:
    - Требует аутентификации через get_current_user
    - Проверяет, что секрет принадлежит текущему пользователю
    - Пользователь не может обновить секреты других пользователей
    """
    async with AsyncSessionLocal() as session:
        # ВАЖНО: Проверяем принадлежность секрета текущему пользователю
        result = await session.execute(
            select(Secret).where(
                Secret.id == secret_id,
                Secret.user_id == current_user.id  # Защита от изменения чужих секретов
            )
        )
        secret = result.scalar_one_or_none()
        
        if not secret:
            raise HTTPException(status_code=404, detail="Секрет не найден")
        
        # Проверяем уникальность имени, если оно изменяется
        if secret_data.name and secret_data.name != secret.name:
            existing = await session.execute(
                select(Secret).where(
                    Secret.user_id == current_user.id,
                    Secret.name == secret_data.name,
                    Secret.id != secret_id
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=400,
                    detail="Секрет с таким именем уже существует"
                )
        
        # Обновляем поля
        if secret_data.name is not None:
            secret.name = secret_data.name
        if secret_data.value is not None:
            secret.value = secret_data.value
        if secret_data.description is not None:
            secret.description = secret_data.description
        
        secret.updated_at = datetime.now().isoformat()
        
        await session.commit()
        await session.refresh(secret)
        
        return SecretResponse(
            id=secret.id,
            name=secret.name,
            value=secret.value,
            description=secret.description,
            created_at=secret.created_at,
            updated_at=secret.updated_at
        )


@app.delete("/secrets/{secret_id}/", status_code=204)
async def delete_secret(
    secret_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Удалить секрет.
    
    Безопасность:
    - Требует аутентификации через get_current_user
    - Проверяет, что секрет принадлежит текущему пользователю
    - Пользователь не может удалить секреты других пользователей
    """
    async with AsyncSessionLocal() as session:
        # ВАЖНО: Проверяем принадлежность секрета текущему пользователю
        result = await session.execute(
            select(Secret).where(
                Secret.id == secret_id,
                Secret.user_id == current_user.id  # Защита от удаления чужих секретов
            )
        )
        secret = result.scalar_one_or_none()
        
        if not secret:
            raise HTTPException(status_code=404, detail="Секрет не найден")
        
        await session.delete(secret)
        await session.commit()


# ========== ЭКСПОРТ/ИМПОРТ НАСТРОЕК ==========

class SettingsExportResponse(BaseModel):
    """Ответ с экспортированными настройками"""
    tokens: Dict[str, Any] = {}
    email_accounts: list = []
    preferences: Optional[str] = None
    secrets: list = []
    export_date: str
    version: str = "1.0"


class SettingsImportRequest(BaseModel):
    """Запрос на импорт настроек"""
    tokens: Optional[Dict[str, Any]] = None
    email_accounts: Optional[list] = None
    preferences: Optional[str] = None
    secrets: Optional[list] = None
    overwrite: bool = False  # Перезаписывать ли существующие настройки


@app.get("/settings/export", response_model=SettingsExportResponse)
async def export_settings(current_user: User = Depends(get_current_user)):
    """
    Экспортировать все настройки пользователя.
    
    Безопасность:
    - Требует аутентификации через get_current_user
    - Экспортирует только настройки текущего пользователя
    - Все данные фильтруются по user_id текущего пользователя
    """
    async with AsyncSessionLocal() as session:
        # Экспортируем токены (из объекта current_user - уже принадлежат текущему пользователю)
        tokens = {
            "tinkoff_token": current_user.tinkoff_token,
            "tinkoff_account_id": current_user.tinkoff_account_id,
            "tinkoff_sandbox": current_user.tinkoff_sandbox,
            "github_token": current_user.github_token,
            "google_calendar_credentials": current_user.google_calendar_credentials,
            "google_calendar_id": current_user.google_calendar_id,
        }
        
        # ВАЖНО: Экспортируем только почтовые ящики текущего пользователя
        email_accounts_result = await session.execute(
            select(EmailAccount).where(EmailAccount.user_id == current_user.id)
        )
        email_accounts = [
            {
                "email": account.email,
                "password": account.password,
                "smtp_host": account.smtp_host,
                "smtp_port": account.smtp_port,
                "imap_host": account.imap_host,
                "imap_port": account.imap_port,
            }
            for account in email_accounts_result.scalars().all()
        ]
        
        # ВАЖНО: Экспортируем предпочтения только текущего пользователя
        preferences = current_user.user_preferences
        
        # ВАЖНО: Экспортируем только секреты текущего пользователя
        secrets_result = await session.execute(
            select(Secret).where(Secret.user_id == current_user.id)
        )
        secrets = [
            {
                "name": secret.name,
                "value": secret.value,
                "description": secret.description,
            }
            for secret in secrets_result.scalars().all()
        ]
        
        return SettingsExportResponse(
            tokens=tokens,
            email_accounts=email_accounts,
            preferences=preferences,
            secrets=secrets,
            export_date=datetime.now().isoformat(),
            version="1.0"
        )


@app.post("/settings/import")
async def import_settings(
    import_data: SettingsImportRequest,
    current_user: User = Depends(get_current_user)
):
    """Импортировать настройки пользователя"""
    async with AsyncSessionLocal() as session:
        user = await session.get(User, current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        imported_count = 0
        
        # Импортируем токены
        if import_data.tokens:
            if import_data.overwrite or not user.tinkoff_token:
                user.tinkoff_token = import_data.tokens.get("tinkoff_token")
            if import_data.overwrite or not user.tinkoff_account_id:
                user.tinkoff_account_id = import_data.tokens.get("tinkoff_account_id")
            if import_data.tokens.get("tinkoff_sandbox") is not None:
                user.tinkoff_sandbox = import_data.tokens.get("tinkoff_sandbox", False)
            if import_data.overwrite or not user.github_token:
                user.github_token = import_data.tokens.get("github_token")
            if import_data.overwrite or not user.google_calendar_credentials:
                user.google_calendar_credentials = import_data.tokens.get("google_calendar_credentials")
            if import_data.overwrite or not user.google_calendar_id:
                user.google_calendar_id = import_data.tokens.get("google_calendar_id")
            imported_count += 1
        
        # Импортируем почтовые ящики
        if import_data.email_accounts:
            for account_data in import_data.email_accounts:
                # Проверяем, существует ли уже ящик с таким email
                existing = await session.execute(
                    select(EmailAccount).where(
                        EmailAccount.user_id == current_user.id,
                        EmailAccount.email == account_data.get("email")
                    )
                )
                existing_account = existing.scalar_one_or_none()
                
                if existing_account and import_data.overwrite:
                    # Обновляем существующий
                    existing_account.password = account_data.get("password", existing_account.password)
                    existing_account.smtp_host = account_data.get("smtp_host", existing_account.smtp_host)
                    existing_account.smtp_port = account_data.get("smtp_port", existing_account.smtp_port)
                    existing_account.imap_host = account_data.get("imap_host", existing_account.imap_host)
                    existing_account.imap_port = account_data.get("imap_port", existing_account.imap_port)
                    existing_account.updated_at = datetime.now().isoformat()
                elif not existing_account:
                    # Создаем новый
                    from giga_agent.agents.email_agent.utils.email_providers import get_default_email_settings
                    default_settings = get_default_email_settings(account_data.get("email", ""))
                    
                    new_account = EmailAccount(
                        user_id=current_user.id,
                        email=account_data.get("email"),
                        password=account_data.get("password", ""),
                        smtp_host=account_data.get("smtp_host") or default_settings["smtp_host"],
                        smtp_port=account_data.get("smtp_port") or default_settings["smtp_port"],
                        imap_host=account_data.get("imap_host") or default_settings["imap_host"],
                        imap_port=account_data.get("imap_port") or default_settings["imap_port"],
                    )
                    session.add(new_account)
                    imported_count += 1
        
        # ВАЖНО: Импортируем предпочтения только для текущего пользователя
        if import_data.preferences is not None:
            if import_data.preferences.strip():
                try:
                    json.loads(import_data.preferences)
                    # Обновляем предпочтения только для текущего пользователя (user.id == current_user.id)
                    if import_data.overwrite or not user.user_preferences:
                        user.user_preferences = import_data.preferences
                        imported_count += 1
                except json.JSONDecodeError:
                    raise HTTPException(status_code=400, detail="preferences must be valid JSON")
            elif import_data.overwrite:
                # Очищаем предпочтения только для текущего пользователя
                user.user_preferences = None
                imported_count += 1
        
        # ВАЖНО: Импортируем секреты только для текущего пользователя
        if import_data.secrets:
            for secret_data in import_data.secrets:
                # Проверяем, существует ли уже секрет с таким именем у текущего пользователя
                existing = await session.execute(
                    select(Secret).where(
                        Secret.user_id == current_user.id,  # Только секреты текущего пользователя
                        Secret.name == secret_data.get("name")
                    )
                )
                existing_secret = existing.scalar_one_or_none()
                
                if existing_secret and import_data.overwrite:
                    # Обновляем существующий секрет текущего пользователя
                    existing_secret.value = secret_data.get("value", existing_secret.value)
                    existing_secret.description = secret_data.get("description", existing_secret.description)
                    existing_secret.updated_at = datetime.now().isoformat()
                    imported_count += 1
                elif not existing_secret:
                    # Создаем новый секрет с привязкой к текущему пользователю
                    new_secret = Secret(
                        user_id=current_user.id,  # ВАЖНО: Секрет привязывается к текущему пользователю
                        name=secret_data.get("name", ""),
                        value=secret_data.get("value", ""),
                        description=secret_data.get("description")
                    )
                    session.add(new_secret)
                    imported_count += 1
        
        user.updated_at = datetime.now().isoformat()
        await session.commit()
        
        return {
            "message": "Настройки успешно импортированы",
            "imported_items": imported_count
        }


# ========== ЧАТЫ ==========

class ChatResponse(BaseModel):
    """Ответ с информацией о чате"""
    id: str
    thread_id: str
    title: str
    first_message: Optional[str] = None
    created_at: str
    updated_at: str


class ChatCreateRequest(BaseModel):
    """Запрос на создание чата"""
    thread_id: str
    title: str
    first_message: Optional[str] = None


class ChatUpdateRequest(BaseModel):
    """Запрос на обновление чата"""
    title: Optional[str] = None
    first_message: Optional[str] = None


@app.get("/api/chats/", response_model=list[ChatResponse])
async def get_user_chats(current_user: User = Depends(get_current_user)):
    """Получить все чаты текущего пользователя, отсортированные по дате обновления (новые сверху)"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Chat).where(
                    Chat.user_id == current_user.id
                ).order_by(Chat.updated_at.desc())
            )
            chats = result.scalars().all()
            
            return [
                ChatResponse(
                    id=chat.id,
                    thread_id=chat.thread_id,
                    title=chat.title,
                    first_message=chat.first_message,
                    created_at=chat.created_at,
                    updated_at=chat.updated_at
                )
                for chat in chats
            ]
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"❌ Ошибка при получении чатов для user_id={current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при получении чатов: {str(e)}")


@app.post("/api/chats/", response_model=ChatResponse)
async def create_chat(
    chat_data: ChatCreateRequest,
    current_user: User = Depends(get_current_user)
):
    """Создать новый чат или обновить существующий"""
    async with AsyncSessionLocal() as session:
        # Проверяем, существует ли уже чат с таким thread_id
        existing_result = await session.execute(
            select(Chat).where(
                Chat.thread_id == chat_data.thread_id,
                Chat.user_id == current_user.id
            )
        )
        existing_chat = existing_result.scalar_one_or_none()
        
        if existing_chat:
            # Обновляем существующий чат
            existing_chat.title = chat_data.title
            if chat_data.first_message is not None:
                existing_chat.first_message = chat_data.first_message
            existing_chat.updated_at = datetime.now().isoformat()
            
            await session.commit()
            await session.refresh(existing_chat)
            
            return ChatResponse(
                id=existing_chat.id,
                thread_id=existing_chat.thread_id,
                title=existing_chat.title,
                first_message=existing_chat.first_message,
                created_at=existing_chat.created_at,
                updated_at=existing_chat.updated_at
            )
        else:
            # Создаем новый чат
            new_chat = Chat(
                user_id=current_user.id,
                thread_id=chat_data.thread_id,
                title=chat_data.title,
                first_message=chat_data.first_message
            )
            
            session.add(new_chat)
            await session.commit()
            await session.refresh(new_chat)
            
            return ChatResponse(
                id=new_chat.id,
                thread_id=new_chat.thread_id,
                title=new_chat.title,
                first_message=new_chat.first_message,
                created_at=new_chat.created_at,
                updated_at=new_chat.updated_at
            )


@app.put("/api/chats/{thread_id}/", response_model=ChatResponse)
async def update_chat(
    thread_id: str,
    chat_data: ChatUpdateRequest,
    current_user: User = Depends(get_current_user)
):
    """Обновить чат по thread_id"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Chat).where(
                Chat.thread_id == thread_id,
                Chat.user_id == current_user.id
            )
        )
        chat = result.scalar_one_or_none()
        
        if not chat:
            raise HTTPException(status_code=404, detail="Чат не найден")
        
        # Обновляем поля
        if chat_data.title is not None:
            chat.title = chat_data.title
        if chat_data.first_message is not None:
            chat.first_message = chat_data.first_message
        
        chat.updated_at = datetime.now().isoformat()
        
        await session.commit()
        await session.refresh(chat)
        
        return ChatResponse(
            id=chat.id,
            thread_id=chat.thread_id,
            title=chat.title,
            first_message=chat.first_message,
            created_at=chat.created_at,
            updated_at=chat.updated_at
        )


@app.delete("/api/chats/{thread_id}/", status_code=204)
async def delete_chat(
    thread_id: str,
    current_user: User = Depends(get_current_user)
):
    """Удалить чат по thread_id"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Chat).where(
                Chat.thread_id == thread_id,
                Chat.user_id == current_user.id
            )
        )
        chat = result.scalar_one_or_none()
        
        if not chat:
            raise HTTPException(status_code=404, detail="Чат не найден")
        
        await session.delete(chat)
        await session.commit()


# ========== ОТЛОЖЕННЫЕ ЗАДАЧИ ДЛЯ АДМИНА ==========

def is_admin_user(user: User) -> bool:
    """Проверка, является ли пользователь админом"""
    return user.is_admin if hasattr(user, 'is_admin') else (user.username == "alexis")


class MCPServerInfo(BaseModel):
    name: str
    url: str
    transport: str
    status: str  # "connected", "failed", "unknown"
    tools_count: int
    tools: List[Dict[str, Any]]
    error: Optional[str] = None


# ===== MCP REGISTRY (CRUD) =====
class MCPServerRegistryItem(BaseModel):
    """Строка реестра MCP серверов (для админки)."""
    name: str
    url: str
    transport: str = "http"
    enabled: bool = True
    # Примечание: headers возвращаем маскированными (Authorization=***),
    # но в CRUD запросах позволяем передавать headers целиком (админ).
    headers: Optional[Dict[str, str]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MCPServerRegistryUpsertRequest(BaseModel):
    name: str
    url: str
    transport: str = "http"
    enabled: bool = True
    headers: Optional[Dict[str, str]] = None


class MCPServerRegistryEnableRequest(BaseModel):
    enabled: bool


# Кэш для health-проверок MCP серверов
# Ограничиваем частоту запросов: не чаще 1 раза в минуту
_mcp_servers_cache: Optional[List[MCPServerInfo]] = None
_mcp_servers_cache_timestamp: Optional[datetime] = None
_mcp_servers_cache_ttl = timedelta(seconds=60)  # 1 минута


@app.get("/admin/mcp-servers/", response_model=List[MCPServerInfo])
async def get_mcp_servers_info(current_user: User = Depends(get_current_user)):
    """Получить информацию о MCP серверах и их инструментах (только для администраторов)
    
    Использует кэширование для ограничения частоты health-проверок: не чаще 1 раза в минуту.
    """
    # Проверяем права администратора
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    
    global _mcp_servers_cache, _mcp_servers_cache_timestamp
    
    # Проверяем, можно ли использовать кэш
    now = datetime.now()
    if (_mcp_servers_cache is not None and 
        _mcp_servers_cache_timestamp is not None and 
        (now - _mcp_servers_cache_timestamp) < _mcp_servers_cache_ttl):
        # Возвращаем данные из кэша
        return _mcp_servers_cache
    
    # Кэш устарел или отсутствует, обновляем данные
    try:
        # Получаем информацию о серверах из tool_server
        tool_server_url_env = os.getenv("TOOL_SERVER_URL")
        tool_server_url_default = "http://tool_server:9091"
        tool_server_candidates = []
        if tool_server_url_env:
            tool_server_candidates.append(tool_server_url_env)
        tool_server_candidates.append(tool_server_url_default)
        # Убираем дубли, сохраняем порядок
        seen = set()
        tool_server_candidates = [u for u in tool_server_candidates if not (u in seen or seen.add(u))]
        
        servers_info = []
        
        tool_server_data_ok = False
        last_error: Optional[str] = None
        try:
            # ВАЖНО (proxy):
            # В проекте могут быть выставлены HTTP_PROXY/HTTPS_PROXY (через AI_PROXY_*).
            # Для внутренних Docker сервисов (tool_server) прокси НЕ должен использоваться,
            # иначе возможны 502/timeout при попытке обратиться к имени "tool_server".
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                for base_url in tool_server_candidates:
                    mcp_servers_info_url = f"{base_url}/mcp_servers_info"
                    try:
                        response = await client.get(mcp_servers_info_url)
                    except Exception as e:
                        last_error = f"tool_server request error via {base_url}: {type(e).__name__}: {e}"
                        continue

                    if response.status_code == 200:
                        tool_server_data_ok = True
                        servers_data = response.json()
                        for server_data in servers_data:
                            servers_info.append(MCPServerInfo(
                                name=server_data.get("name", "unknown"),
                                url=server_data.get("url", "N/A"),
                                transport=server_data.get("transport", "http"),
                                status=server_data.get("status", "unknown"),
                                tools_count=server_data.get("tools_count", 0),
                                tools=server_data.get("tools", []),
                                error=server_data.get("error")
                            ))
                        break
                    else:
                        last_error = f"tool_server /mcp_servers_info returned HTTP {response.status_code} via {base_url}"
        except Exception as e:
            # Если не удалось получить информацию, используем fallback из БД (mcp_server)
            from giga_agent.mcp_registry import load_mcp_config_from_db
            mcp_cfg = load_mcp_config_from_db(seed_if_empty=True)
            for server_name, server_config in mcp_cfg.items():
                servers_info.append(MCPServerInfo(
                    name=server_name,
                    url=server_config.get("url", "N/A"),
                    transport=server_config.get("transport", "http"),
                    status="unknown",
                    tools_count=0,
                    tools=[],
                    error=str(e)
                ))
        # Если с tool_server не удалось получить данные (все URL не 200) — fallback из БД
        if not tool_server_data_ok and not servers_info:
            from giga_agent.mcp_registry import load_mcp_config_from_db
            mcp_cfg = load_mcp_config_from_db(seed_if_empty=True)
            for server_name, server_config in mcp_cfg.items():
                servers_info.append(MCPServerInfo(
                    name=server_name,
                    url=server_config.get("url", "N/A"),
                    transport=server_config.get("transport", "http"),
                    status="unknown",
                    tools_count=0,
                    tools=[],
                    error=last_error or "tool_server /mcp_servers_info unavailable"
                ))
        
        # Обновляем кэш ТОЛЬКО если получили данные от tool_server (200).
        # Примечание: если ушли в fallback (unknown/0), лучше не кэшировать,
        # чтобы UI мог сразу повторить запрос после исправления проблемы.
        if tool_server_data_ok:
            _mcp_servers_cache = servers_info
            _mcp_servers_cache_timestamp = now
        
        return servers_info
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения информации о MCP серверах: {str(e)}")


@app.get("/admin/mcp-servers/registry/", response_model=List[MCPServerRegistryItem])
async def list_mcp_servers_registry(current_user: User = Depends(get_current_user)):
    """Реестр MCP серверов (CRUD): источник истины — таблица mcp_server."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    from giga_agent.mcp_registry import list_mcp_servers
    return [MCPServerRegistryItem(**row) for row in list_mcp_servers(include_disabled=True)]


@app.post("/admin/mcp-servers/registry/", response_model=MCPServerRegistryItem)
async def upsert_mcp_server_registry(
    payload: MCPServerRegistryUpsertRequest,
    current_user: User = Depends(get_current_user),
):
    """Создать/обновить MCP сервер в реестре."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")

    name = (payload.name or "").strip()
    url = (payload.url or "").strip()
    transport = (payload.transport or "http").strip() or "http"
    if not name:
        raise HTTPException(status_code=400, detail="name обязателен")
    if not url:
        raise HTTPException(status_code=400, detail="url обязателен")
    if transport not in {"http", "sse"}:
        raise HTTPException(status_code=400, detail="transport должен быть 'http' или 'sse'")

    from giga_agent.mcp_registry import upsert_mcp_server, list_mcp_servers
    upsert_mcp_server(
        name=name,
        url=url,
        transport=transport,
        headers=payload.headers or {},
        enabled=bool(payload.enabled),
    )
    # Возвращаем актуальную строку (с маскированными headers)
    rows = list_mcp_servers(include_disabled=True)
    row = next((r for r in rows if r.get("name") == name), None)
    if not row:
        raise HTTPException(status_code=500, detail="Не удалось прочитать запись после сохранения")
    # Сбрасываем кэш health
    global _mcp_servers_cache, _mcp_servers_cache_timestamp
    _mcp_servers_cache = None
    _mcp_servers_cache_timestamp = None
    return MCPServerRegistryItem(**row)


@app.put("/admin/mcp-servers/registry/{name}/enabled/", response_model=MCPServerRegistryItem)
async def set_mcp_server_registry_enabled(
    name: str,
    payload: MCPServerRegistryEnableRequest,
    current_user: User = Depends(get_current_user),
):
    """Включить/выключить MCP сервер."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    from giga_agent.mcp_registry import set_mcp_server_enabled, list_mcp_servers
    ok = set_mcp_server_enabled(name, bool(payload.enabled))
    if not ok:
        raise HTTPException(status_code=404, detail="MCP сервер не найден")
    rows = list_mcp_servers(include_disabled=True)
    row = next((r for r in rows if r.get("name") == name), None)
    if not row:
        raise HTTPException(status_code=500, detail="Не удалось прочитать запись после обновления")
    global _mcp_servers_cache, _mcp_servers_cache_timestamp
    _mcp_servers_cache = None
    _mcp_servers_cache_timestamp = None
    return MCPServerRegistryItem(**row)


@app.delete("/admin/mcp-servers/registry/{name}/", response_model=Dict[str, Any])
async def delete_mcp_server_registry(name: str, current_user: User = Depends(get_current_user)):
    """Удалить MCP сервер из реестра."""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    from giga_agent.mcp_registry import delete_mcp_server
    ok = delete_mcp_server(name)
    if not ok:
        raise HTTPException(status_code=404, detail="MCP сервер не найден")
    global _mcp_servers_cache, _mcp_servers_cache_timestamp
    _mcp_servers_cache = None
    _mcp_servers_cache_timestamp = None
    return {"deleted": True, "name": name}


@app.post("/admin/mcp-servers/reload/", response_model=Dict[str, Any])
async def reload_mcp_servers(current_user: User = Depends(get_current_user)):
    """
    Hot-reload MCP в tool_server:
    - tool_server перечитывает конфиг из БД
    - переподключает MCP серверы
    - обновляет список MCP инструментов
    """
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    tool_server_url = os.getenv("TOOL_SERVER_URL", "http://tool_server:9091")
    reload_url = f"{tool_server_url}/mcp_reload"
    try:
        # ВАЖНО (proxy): не используем env-proxy для обращения к internal tool_server.
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            resp = await client.post(reload_url)
            if resp.status_code != 200:
                raise HTTPException(status_code=500, detail=f"tool_server reload failed: {resp.status_code} {resp.text}")
            data = resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка reload MCP: {str(e)}")

    # Сбрасываем health-cache, чтобы /admin/mcp-servers/ показал актуальное состояние
    global _mcp_servers_cache, _mcp_servers_cache_timestamp
    _mcp_servers_cache = None
    _mcp_servers_cache_timestamp = None
    return {"reloaded": True, "tool_server": data}

class DeferredTaskCreateRequest(BaseModel):
    """Запрос на создание отложенной задачи"""
    message: str
    priority: int = 0
    task_type: str = "deferred"  # "deferred" или "recurring"
    task_config: Optional[Dict[str, Any]] = None  # Дополнительная конфигурация задачи


class DeferredTaskResponse(BaseModel):
    """Ответ с информацией об отложенной задаче"""
    id: str
    user_id: str
    message: str
    priority: int
    status: str
    task_type: str
    thread_id: Optional[str] = None
    result_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    schedule: Optional[str] = None
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    task_config: Optional[Dict[str, Any]] = None


class DeferredTaskUpdateRequest(BaseModel):
    """Запрос на обновление отложенной задачи"""
    status: Optional[str] = None
    result_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    thread_id: Optional[str] = None


def calculate_next_run(schedule: str, interval: Optional[str] = None) -> Optional[str]:
    """Вычисляет следующее время выполнения на основе cron выражения или интервала"""
    if not schedule:
        return None
    
    try:
        # Пробуем использовать croniter, если доступен
        try:
            from croniter import croniter
            now = datetime.now()
            cron = croniter(schedule, now)
            next_run = cron.get_next(datetime)
            return next_run.isoformat()
        except ImportError:
            # Если croniter не установлен, используем простую логику для базовых интервалов
            now = datetime.now()
            if interval == "daily":
                # Ежедневно в указанное время (из cron выражения)
                # Парсим час и минуту из cron "минута час * * *"
                parts = schedule.split()
                if len(parts) >= 2:
                    try:
                        minute = int(parts[0]) if parts[0] != "*" else 0
                        hour = int(parts[1]) if parts[1] != "*" else 9
                        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        if next_run <= now:
                            next_run += timedelta(days=1)
                        return next_run.isoformat()
                    except (ValueError, IndexError):
                        # Если не удалось распарсить, используем дефолтное время (9:00)
                        next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
                        if next_run <= now:
                            next_run += timedelta(days=1)
                        return next_run.isoformat()
            elif interval == "weekly":
                # Еженедельно в указанный день недели
                parts = schedule.split()
                if len(parts) >= 5:
                    try:
                        minute = int(parts[0]) if parts[0] != "*" else 0
                        hour = int(parts[1]) if parts[1] != "*" else 9
                        weekday = int(parts[4]) if parts[4] != "*" else 0  # 0 = понедельник
                        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        days_ahead = weekday - next_run.weekday()
                        if days_ahead <= 0:
                            days_ahead += 7
                        next_run += timedelta(days=days_ahead)
                        return next_run.isoformat()
                    except (ValueError, IndexError):
                        # Если не удалось распарсить, используем дефолтное время (понедельник 9:00)
                        next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
                        days_ahead = 0 - next_run.weekday()
                        if days_ahead <= 0:
                            days_ahead += 7
                        next_run += timedelta(days=days_ahead)
                        return next_run.isoformat()
            elif interval == "monthly":
                # Ежемесячно в указанное число
                parts = schedule.split()
                if len(parts) >= 3:
                    try:
                        minute = int(parts[0]) if parts[0] != "*" else 0
                        hour = int(parts[1]) if parts[1] != "*" else 9
                        day = int(parts[2]) if parts[2] != "*" else 1
                        next_run = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
                        if next_run <= now:
                            # Переходим на следующий месяц
                            if next_run.month == 12:
                                next_run = next_run.replace(year=next_run.year + 1, month=1)
                            else:
                                next_run = next_run.replace(month=next_run.month + 1)
                        return next_run.isoformat()
                    except (ValueError, IndexError):
                        # Если не удалось распарсить, используем дефолтное время (1 число 9:00)
                        next_run = now.replace(day=1, hour=9, minute=0, second=0, microsecond=0)
                        if next_run <= now:
                            if next_run.month == 12:
                                next_run = next_run.replace(year=next_run.year + 1, month=1)
                            else:
                                next_run = next_run.replace(month=next_run.month + 1)
                        return next_run.isoformat()
            elif interval == "custom":
                # Для кастомного cron выражения пытаемся использовать базовую логику
                # Если не получается, возвращаем None (пользователь должен установить croniter)
                parts = schedule.split()
                if len(parts) >= 2:
                    try:
                        minute = int(parts[0]) if parts[0] != "*" else 0
                        hour = int(parts[1]) if parts[1] != "*" else 9
                        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        if next_run <= now:
                            next_run += timedelta(days=1)
                        return next_run.isoformat()
                    except (ValueError, IndexError):
                        pass
            
            # Если не удалось распарсить, возвращаем None
            return None
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"[DEFERRED_TASKS] Ошибка при вычислении next_run_at: {e}")
        return None


@app.post("/deferred-tasks/", response_model=DeferredTaskResponse)
async def create_deferred_task(
    task_data: DeferredTaskCreateRequest,
    current_user: User = Depends(get_current_user)
):
    """Создать отложенную или регулярную задачу (только для админа)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ разрешен только администратору")
    
    async with AsyncSessionLocal() as session:
        task_config_json = json.dumps(task_data.task_config, ensure_ascii=False) if task_data.task_config else None
        
        # Извлекаем параметры расписания для регулярных задач
        schedule = None
        next_run_at = None
        if task_data.task_type == "recurring" and task_data.task_config:
            recurring_config = task_data.task_config.get("recurring", {})
            schedule = recurring_config.get("schedule", "")
            interval = recurring_config.get("interval", "custom")
            if schedule:
                next_run_at = calculate_next_run(schedule, interval)
        
        new_task = DeferredTask(
            user_id=current_user.id,
            message=task_data.message,
            priority=task_data.priority,
            task_type=task_data.task_type,
            task_config=task_config_json,
            schedule=schedule,
            next_run_at=next_run_at,
            status="pending"  # Явно устанавливаем статус
        )
        
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[DEFERRED_TASKS] Создание задачи: user_id={current_user.id}, message={task_data.message[:50]}, priority={task_data.priority}, type={task_data.task_type}, status=pending")
        
        session.add(new_task)
        await session.commit()
        await session.refresh(new_task)
        
        logger.info(f"[DEFERRED_TASKS] Задача создана: id={new_task.id}, status={new_task.status}, type={new_task.task_type}")
        
        result_data = json.loads(new_task.result_data) if new_task.result_data else None
        task_config = json.loads(new_task.task_config) if new_task.task_config else None
        
        return DeferredTaskResponse(
            id=new_task.id,
            user_id=new_task.user_id,
            message=new_task.message,
            priority=new_task.priority,
            status=new_task.status,
            task_type=new_task.task_type,
            thread_id=new_task.thread_id,
            result_data=result_data,
            error_message=new_task.error_message,
            created_at=new_task.created_at,
            started_at=new_task.started_at,
            completed_at=new_task.completed_at,
            schedule=new_task.schedule,
            next_run_at=new_task.next_run_at,
            last_run_at=new_task.last_run_at,
            task_config=task_config
        )


@app.get("/deferred-tasks/", response_model=list[DeferredTaskResponse])
async def list_deferred_tasks(
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Получить список отложенных задач (только для админа)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ разрешен только администратору")
    
    async with AsyncSessionLocal() as session:
        query = select(DeferredTask).where(DeferredTask.user_id == current_user.id)
        
        if status:
            query = query.where(DeferredTask.status == status)
        
        # Сортируем по приоритету (убывание) и по времени создания (FIFO)
        query = query.order_by(DeferredTask.priority.desc(), DeferredTask.created_at.asc())
        
        result = await session.execute(query)
        tasks = result.scalars().all()
        
        return [
            DeferredTaskResponse(
                id=task.id,
                user_id=task.user_id,
                message=task.message,
                priority=task.priority,
                status=task.status,
                task_type=task.task_type,
                thread_id=task.thread_id,
                result_data=json.loads(task.result_data) if task.result_data else None,
                error_message=task.error_message,
                created_at=task.created_at,
                started_at=task.started_at,
                completed_at=task.completed_at,
                schedule=task.schedule,
                next_run_at=task.next_run_at,
                last_run_at=task.last_run_at,
                task_config=json.loads(task.task_config) if task.task_config else None
            )
            for task in tasks
        ]


@app.get("/deferred-tasks/status/")
async def get_task_processing_status(current_user: User = Depends(get_current_user)):
    """Получить статус обработки задач (только для админа)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ разрешен только администратору")
    
    user_id = current_user.id
    is_running = task_processing_state.get(user_id, False)
    
    # Подсчитываем статистику задач
    async with AsyncSessionLocal() as session:
        all_tasks_result = await session.execute(
            select(DeferredTask).where(DeferredTask.user_id == user_id)
        )
        all_tasks = all_tasks_result.scalars().all()
        
        pending_count = sum(1 for t in all_tasks if t.status == "pending")
        processing_count = sum(1 for t in all_tasks if t.status == "processing")
        completed_count = sum(1 for t in all_tasks if t.status == "completed")
        failed_count = sum(1 for t in all_tasks if t.status == "failed")
        revision_count = sum(1 for t in all_tasks if t.status == "revision")
    
    return {
        "is_running": is_running,
        "statistics": {
            "total": len(all_tasks),
            "pending": pending_count,
            "processing": processing_count,
            "completed": completed_count,
            "failed": failed_count,
            "revision": revision_count,
        }
    }


@app.post("/deferred-tasks/check-status/")
async def check_and_update_task_status(current_user: User = Depends(get_current_user)):
    """Проверить и обновить статусы задач со статусом processing (только для админа)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ разрешен только администратору")
    
    user_id = current_user.id
    langgraph_client = get_client(url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024"))
    
    updated_count = 0
    async with AsyncSessionLocal() as session:
        # Получаем все задачи со статусом processing
        result = await session.execute(
            select(DeferredTask).where(
                DeferredTask.user_id == user_id,
                DeferredTask.status == "processing",
                DeferredTask.thread_id.isnot(None)
            )
        )
        processing_tasks = result.scalars().all()
        
        for task in processing_tasks:
            try:
                # Проверяем статус потока
                runs = await langgraph_client.runs.list(thread_id=task.thread_id, limit=1)
                if runs and len(runs) > 0:
                    last_run = runs[0]
                    run_status = last_run.get("status", "unknown")
                    
                    # Если поток завершен и есть результат, помечаем задачу как completed
                    if run_status in ["success", "completed"]:
                        # Проверяем, есть ли результат в result_data
                        if task.result_data:
                            result_data = json.loads(task.result_data)
                            # Проверяем наличие markdown или last_response
                            if result_data.get("markdown") or result_data.get("last_response") or result_data.get("messages"):
                                task.status = "completed"
                                if not task.completed_at:
                                    task.completed_at = datetime.now().isoformat()
                                await session.commit()
                                updated_count += 1
                                _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Обновлен статус задачи {task.id} на 'completed'")
            except Exception as e:
                _deferred_tasks_logger.error(f"[DEFERRED_TASKS] Ошибка при проверке статуса задачи {task.id}: {e}")
                continue
    
    return {"updated": updated_count, "message": f"Обновлено задач: {updated_count}"}


@app.get("/deferred-tasks/{task_id}/", response_model=DeferredTaskResponse)
async def get_deferred_task(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """Получить отложенную задачу по ID (только для админа)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ разрешен только администратору")
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DeferredTask).where(
                DeferredTask.id == task_id,
                DeferredTask.user_id == current_user.id
            )
        )
        task = result.scalar_one_or_none()
        
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        
        result_data = json.loads(task.result_data) if task.result_data else None
        task_config = json.loads(task.task_config) if task.task_config else None
        
        return DeferredTaskResponse(
            id=task.id,
            user_id=task.user_id,
            message=task.message,
            priority=task.priority,
            status=task.status,
            task_type=task.task_type,
            thread_id=task.thread_id,
            result_data=result_data,
            error_message=task.error_message,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            schedule=task.schedule,
            next_run_at=task.next_run_at,
            last_run_at=task.last_run_at,
            task_config=task_config
        )


@app.put("/deferred-tasks/{task_id}/", response_model=DeferredTaskResponse)
async def update_deferred_task(
    task_id: str,
    task_update: DeferredTaskUpdateRequest,
    current_user: User = Depends(get_current_user)
):
    """Обновить отложенную задачу (только для админа)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ разрешен только администратору")
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DeferredTask).where(
                DeferredTask.id == task_id,
                DeferredTask.user_id == current_user.id
            )
        )
        task = result.scalar_one_or_none()
        
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        
        # Обновляем поля
        if task_update.status is not None:
            old_status = task.status
            task.status = task_update.status
            
            # Устанавливаем started_at при переходе в processing
            if task_update.status == "processing" and not task.started_at:
                task.started_at = datetime.now().isoformat()
            
            # Устанавливаем completed_at при завершении (completed, failed, revision)
            if task_update.status in ["completed", "failed", "revision"] and not task.completed_at:
                task.completed_at = datetime.now().isoformat()
            
            # При возврате из revision в pending сбрасываем completed_at и started_at
            if old_status == "revision" and task_update.status == "pending":
                task.completed_at = None
                task.started_at = None
                task.error_message = None  # Очищаем ошибку при возврате в очередь
        
        if task_update.result_data is not None:
            task.result_data = json.dumps(task_update.result_data, ensure_ascii=False)
        
        if task_update.error_message is not None:
            task.error_message = task_update.error_message
        
        if task_update.thread_id is not None:
            task.thread_id = task_update.thread_id
        
        await session.commit()
        await session.refresh(task)
        
        result_data = json.loads(task.result_data) if task.result_data else None
        task_config = json.loads(task.task_config) if task.task_config else None
        
        return DeferredTaskResponse(
            id=task.id,
            user_id=task.user_id,
            message=task.message,
            priority=task.priority,
            status=task.status,
            task_type=task.task_type,
            thread_id=task.thread_id,
            result_data=result_data,
            error_message=task.error_message,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            schedule=task.schedule,
            next_run_at=task.next_run_at,
            last_run_at=task.last_run_at,
            task_config=task_config
        )


@app.delete("/deferred-tasks/{task_id}/")
async def delete_deferred_task(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """Удалить отложенную задачу (только для админа)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ разрешен только администратору")
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DeferredTask).where(
                DeferredTask.id == task_id,
                DeferredTask.user_id == current_user.id
            )
        )
        task = result.scalar_one_or_none()
        
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        
        await session.delete(task)
        await session.commit()
        
        return {"message": "Задача успешно удалена", "id": task_id}


@app.get("/deferred-tasks/next/", response_model=Optional[DeferredTaskResponse])
async def get_next_deferred_task(
    current_user: User = Depends(get_current_user)
):
    """Получить следующую задачу для обработки (только для админа, FIFO по приоритету)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ разрешен только администратору")
    
    import logging
    logger = logging.getLogger(__name__)
    
    async with AsyncSessionLocal() as session:
        # Сначала проверим, сколько всего задач у пользователя и их статусы
        all_tasks_result = await session.execute(
            select(DeferredTask).where(DeferredTask.user_id == current_user.id)
        )
        all_tasks = all_tasks_result.scalars().all()
        logger.info(f"[DEFERRED_TASKS] Всего задач для user_id={current_user.id}: {len(all_tasks)}")
        for t in all_tasks:
            logger.info(f"[DEFERRED_TASKS] Задача {t.id}: status={t.status}, priority={t.priority}")
        
        # Получаем задачу с наивысшим приоритетом и самым ранним временем создания среди pending
        result = await session.execute(
            select(DeferredTask)
            .where(
                DeferredTask.user_id == current_user.id,
                DeferredTask.status == "pending"
            )
            .order_by(DeferredTask.priority.desc(), DeferredTask.created_at.asc())
            .limit(1)
        )
        task = result.scalar_one_or_none()
        
        if not task:
            logger.info(f"[DEFERRED_TASKS] Нет задач со статусом 'pending' для user_id={current_user.id}")
            # FastAPI автоматически возвращает 404 для None в Optional, поэтому используем Response
            from fastapi.responses import JSONResponse
            return JSONResponse(content=None, status_code=200)
        
        result_data = json.loads(task.result_data) if task.result_data else None
        task_config = json.loads(task.task_config) if task.task_config else None
        
        return DeferredTaskResponse(
            id=task.id,
            user_id=task.user_id,
            message=task.message,
            priority=task.priority,
            status=task.status,
            task_type=task.task_type,
            thread_id=task.thread_id,
            result_data=result_data,
            error_message=task.error_message,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            schedule=task.schedule,
            next_run_at=task.next_run_at,
            last_run_at=task.last_run_at,
            task_config=task_config
        )


# ========== УПРАВЛЕНИЕ ОБРАБОТКОЙ ЗАДАЧ НА СЕРВЕРЕ ==========

# Глобальное состояние обработки задач (по user_id)
task_processing_state: Dict[str, bool] = {}  # user_id -> is_processing
task_processing_tasks: Dict[str, asyncio.Task] = {}  # user_id -> background_task

import logging
_deferred_tasks_logger = logging.getLogger(__name__)


async def process_deferred_tasks_worker(user_id: str):
    """Фоновая задача для обработки отложенных и регулярных задач пользователя"""
    _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Запуск обработчика задач для user_id={user_id}")
    
    langgraph_client = get_client(url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024"))
    
    while task_processing_state.get(user_id, False):
        try:
            async with AsyncSessionLocal() as session:
                now = datetime.now()
                
                # Сначала проверяем регулярные задачи, которые готовы к выполнению
                recurring_result = await session.execute(
                    select(DeferredTask)
                    .where(
                        DeferredTask.user_id == user_id,
                        DeferredTask.task_type == "recurring",
                        DeferredTask.next_run_at.isnot(None),
                        DeferredTask.next_run_at <= now.isoformat()
                    )
                    .order_by(DeferredTask.priority.desc(), DeferredTask.next_run_at.asc())
                    .limit(1)
                )
                recurring_task = recurring_result.scalar_one_or_none()
                
                # Если есть регулярная задача, готовящаяся к выполнению, сбрасываем её статус в pending
                if recurring_task and recurring_task.status != "pending":
                    recurring_task.status = "pending"
                    await session.commit()
                    await session.refresh(recurring_task)
                
                # Получаем следующую задачу со статусом pending
                # Для регулярных задач также проверяем, что next_run_at <= now
                result = await session.execute(
                    select(DeferredTask)
                    .where(
                        DeferredTask.user_id == user_id,
                        DeferredTask.status == "pending",
                        # Для регулярных задач проверяем, что время выполнения наступило
                        # Для отложенных задач next_run_at будет None
                        (
                            (DeferredTask.task_type == "recurring") & (DeferredTask.next_run_at <= now.isoformat())
                        ) | (DeferredTask.task_type == "deferred")
                    )
                    .order_by(DeferredTask.priority.desc(), DeferredTask.created_at.asc())
                    .limit(1)
                )
                task = result.scalar_one_or_none()
                
                if not task:
                    # Нет задач, ждем перед следующей проверкой
                    await asyncio.sleep(2)
                    continue
                
                _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Начинаем обработку задачи {task.id} для user_id={user_id}")
                
                # Обновляем статус задачи на processing
                task.status = "processing"
                task.started_at = datetime.now().isoformat()
                await session.commit()
                await session.refresh(task)
                
                thread_id = None
                try:
                    # Создаем поток LangGraph
                    thread = await langgraph_client.threads.create()
                    thread_id = thread["thread_id"]
                    
                    # Обновляем thread_id задачи
                    task.thread_id = thread_id
                    await session.commit()
                    
                    # Парсим конфигурацию задачи
                    task_config = json.loads(task.task_config) if task.task_config else {}
                    task_files = task_config.get("files", [])
                    task_selected = task_config.get("selected", {})
                    
                    # Формируем сообщение
                    from langchain_core.messages import HumanMessage
                    message = HumanMessage(
                        content=task.message,
                        additional_kwargs={
                            "user_input": task.message,
                            "files": task_files,
                            "selected": task_selected,
                        }
                    )
                    
                    # Отправляем задачу в поток
                    configurable = {"user_id": user_id}
                    
                    _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Отправляем задачу {task.id} в поток LangGraph, thread_id={thread_id}")
                    
                    result_state = {}
                    last_chunk_event = None
                    async for chunk in langgraph_client.runs.stream(
                        thread_id=thread_id,
                        assistant_id="chat",
                        input={"messages": [message]},
                        stream_mode=["values"],
                        on_disconnect="continue",
                        config={"configurable": configurable},
                    ):
                        last_chunk_event = chunk.event
                        if chunk.event == "values":
                            result_state = chunk.data
                            _deferred_tasks_logger.debug(f"[DEFERRED_TASKS] Получен chunk с values для задачи {task.id}")
                    
                    _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Поток завершен для задачи {task.id}, последнее событие: {last_chunk_event}")
                    
                    # Проверяем статус потока перед помечанием как completed
                    # НЕ помечаем задачу как completed сразу - оставляем статус processing
                    # Задача будет помечена как completed только когда пользователь откроет чат и увидит результат
                    # Или можно проверить статус через runs.list, но это может быть не точно
                    
                    # Получаем результат
                    messages = result_state.get("messages", [])
                    _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Получено сообщений для задачи {task.id}: {len(messages)}")
                    
                    last_ai_message = None
                    for msg in reversed(messages):
                        if hasattr(msg, "type") and msg.type == "ai":
                            last_ai_message = msg
                            break
                        elif isinstance(msg, dict) and msg.get("type") == "ai":
                            last_ai_message = msg
                            break
                    
                    # Извлекаем содержимое последнего AI сообщения
                    last_response = ""
                    if last_ai_message:
                        if isinstance(last_ai_message, dict):
                            # Если это словарь, извлекаем content
                            last_response = last_ai_message.get("content", "")
                            # Если content - это список (для сообщений с частями), объединяем
                            if isinstance(last_response, list):
                                last_response = " ".join(str(part) for part in last_response)
                        elif hasattr(last_ai_message, "content"):
                            # Если это объект с атрибутом content
                            last_response = last_ai_message.content
                            if isinstance(last_response, list):
                                last_response = " ".join(str(part) for part in last_response)
                    
                    # Проверяем, есть ли результат (AI сообщение)
                    # Если есть результат, помечаем задачу как completed
                    if last_ai_message and last_response:
                        # Сохраняем markdown текст результата (не JSON)
                        # last_response уже содержит markdown текст от AI
                        markdown_result = last_response
                        
                        # Если last_response - это строка, используем её напрямую
                        # Если это список, объединяем части
                        if isinstance(markdown_result, list):
                            markdown_result = "\n".join(str(part) for part in markdown_result)
                        elif not isinstance(markdown_result, str):
                            markdown_result = str(markdown_result)
                        
                        # Сохраняем markdown текст в result_data как строку
                        # Для совместимости сохраняем и метаданные в JSON формате, но основной контент - markdown
                        result_data = {
                            "markdown": markdown_result,
                            "thread_id": thread_id,
                            "completed_at": datetime.now().isoformat(),
                            "message_count": len(messages),
                        }
                        
                        # Обновляем задачу как завершенную
                        task.status = "completed"
                        task.completed_at = datetime.now().isoformat()
                        # Сохраняем markdown в result_data как JSON строку (для совместимости с БД)
                        task.result_data = json.dumps(result_data, ensure_ascii=False)
                        
                        # Если это регулярная задача, обновляем next_run_at и сбрасываем статус в pending
                        if task.task_type == "recurring" and task.schedule:
                            task.last_run_at = datetime.now().isoformat()
                            # Парсим конфигурацию для получения интервала
                            task_config_dict = json.loads(task.task_config) if task.task_config else {}
                            recurring_config = task_config_dict.get("recurring", {})
                            interval = recurring_config.get("interval", "custom")
                            # Вычисляем следующее время выполнения
                            next_run = calculate_next_run(task.schedule, interval)
                            if next_run:
                                task.next_run_at = next_run
                                task.status = "pending"  # Сбрасываем статус для следующего выполнения
                                _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Регулярная задача {task.id} будет выполнена снова в {next_run}")
                            else:
                                _deferred_tasks_logger.warning(f"[DEFERRED_TASKS] Не удалось вычислить next_run_at для регулярной задачи {task.id}")
                        
                        await session.commit()
                        
                        _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Задача {task.id} успешно завершена, сохранен markdown результат, статус: '{task.status}'")
                    else:
                        # Если нет результата, сохраняем промежуточные данные, но статус остается processing
                        result_data = {
                            "markdown": last_response if last_response else "Ожидание результата...",
                            "thread_id": thread_id,
                            "stream_completed_at": datetime.now().isoformat(),
                            "message_count": len(messages),
                        }
                        
                        task.result_data = json.dumps(result_data, ensure_ascii=False)
                        # Статус остается "processing" - возможно, поток еще работает
                        await session.commit()
                        
                        _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Поток для задачи {task.id} завершен, но нет AI ответа, сохранено {len(messages)} сообщений, статус остается 'processing'")
                    
                except Exception as e:
                    # Обработка ошибок
                    error_message = str(e)
                    _deferred_tasks_logger.error(f"[DEFERRED_TASKS] Ошибка при обработке задачи {task.id}: {error_message}")
                    
                    # Сохраняем thread_id даже при ошибке, если он был создан
                    if thread_id:
                        task.thread_id = thread_id
                    
                    task.status = "failed"
                    task.error_message = error_message
                    await session.commit()
            
            # Небольшая задержка перед следующей задачей
            await asyncio.sleep(1)
            
        except Exception as e:
            _deferred_tasks_logger.error(f"[DEFERRED_TASKS] Ошибка в обработчике задач для user_id={user_id}: {e}")
            await asyncio.sleep(5)  # Ждем перед повтором при ошибке
    
    _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Остановка обработчика задач для user_id={user_id}")


@app.post("/deferred-tasks/start/")
async def start_task_processing(current_user: User = Depends(get_current_user)):
    """Запустить обработку отложенных задач (только для админа)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ разрешен только администратору")
    
    user_id = current_user.id
    
    if task_processing_state.get(user_id, False):
        return {"status": "already_running", "message": "Обработка задач уже запущена"}
    
    # Запускаем фоновую задачу
    task_processing_state[user_id] = True
    background_task = asyncio.create_task(process_deferred_tasks_worker(user_id))
    task_processing_tasks[user_id] = background_task
    
    _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Запущена обработка задач для user_id={user_id}")
    
    return {"status": "started", "message": "Обработка задач запущена"}


@app.post("/deferred-tasks/stop/")
async def stop_task_processing(current_user: User = Depends(get_current_user)):
    """Остановить обработку отложенных задач (только для админа)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Доступ разрешен только администратору")
    
    user_id = current_user.id
    
    if not task_processing_state.get(user_id, False):
        return {"status": "not_running", "message": "Обработка задач не запущена"}
    
    # Останавливаем фоновую задачу
    task_processing_state[user_id] = False
    
    if user_id in task_processing_tasks:
        task = task_processing_tasks[user_id]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        del task_processing_tasks[user_id]
    
    _deferred_tasks_logger.info(f"[DEFERRED_TASKS] Остановлена обработка задач для user_id={user_id}")
    
    return {"status": "stopped", "message": "Обработка задач остановлена"}

