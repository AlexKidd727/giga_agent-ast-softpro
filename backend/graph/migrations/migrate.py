#!/usr/bin/env python3
"""
Скрипт миграции базы данных
Выполняет миграции ТОЛЬКО для обновления существующей БД.
При первичном создании БД все структуры создаются через SQLModel в init_db().
"""
import os
import sys
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

# Получаем URL базы данных из переменных окружения
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@aegra-postgres:5432/postgres"
)

# Убираем +asyncpg если есть (для синхронных миграций)
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")

def run_migrations():
    """Выполняет миграции базы данных ТОЛЬКО для обновления существующей БД"""
    print("🔄 Проверка необходимости миграций...")
    
    try:
        # Создаем синхронный движок для миграций
        engine = create_engine(SYNC_DATABASE_URL, echo=False)
        
        # Ждем, пока база данных станет доступна
        max_retries = 30
        retry_count = 0
        while retry_count < max_retries:
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                print("✅ Подключение к базе данных установлено")
                break
            except OperationalError as e:
                retry_count += 1
                if retry_count >= max_retries:
                    print(f"❌ Не удалось подключиться к базе данных после {max_retries} попыток")
                    sys.exit(1)
                print(f"⏳ Ожидание подключения к базе данных... ({retry_count}/{max_retries})")
                import time
                time.sleep(2)
        
        # Проверяем, существует ли БД и какие таблицы есть
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        # Если БД пустая (нет таблиц) - создаем базовые таблицы, которые нужны для aegra
        if not tables:
            print("ℹ️ База данных пуста. Создаем базовые таблицы для aegra...")
            
            with engine.begin() as conn:
                # Создаем таблицу assistant (обязательна для aegra/langgraph_service)
                print("📝 Создание таблицы 'assistant'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS assistant (
                            assistant_id VARCHAR PRIMARY KEY,
                            name VARCHAR NOT NULL,
                            description VARCHAR,
                            graph_id VARCHAR NOT NULL,
                            config TEXT DEFAULT '{}',
                            context TEXT DEFAULT '{}',
                            user_id VARCHAR,
                            version INTEGER DEFAULT 1,
                            metadata TEXT DEFAULT '{}',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_assistant_graph_id ON assistant(graph_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_assistant_user_id ON assistant(user_id)"))
                print("✅ Таблица 'assistant' создана")
                
                # Создаем таблицу thread (обязательна для aegra)
                print("📝 Создание таблицы 'thread'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS thread (
                            thread_id VARCHAR PRIMARY KEY,
                            status VARCHAR DEFAULT 'idle',
                            metadata_json JSONB DEFAULT '{}',
                            user_id VARCHAR,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_thread_user_id ON thread(user_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_thread_status ON thread(status)"))
                print("✅ Таблица 'thread' создана")
                
                # Создаем таблицу runs (обязательна для aegra)
                print("📝 Создание таблицы 'runs'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS runs (
                            run_id VARCHAR PRIMARY KEY,
                            thread_id VARCHAR,
                            assistant_id VARCHAR,
                            status VARCHAR DEFAULT 'pending',
                            input JSONB DEFAULT '{}',
                            config JSONB DEFAULT '{}',
                            context JSONB DEFAULT '{}',
                            output JSONB DEFAULT 'null',
                            error_message VARCHAR,
                            user_id VARCHAR,
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_runs_thread_id ON runs(thread_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_runs_assistant_id ON runs(assistant_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_runs_user_id ON runs(user_id)"))
                print("✅ Таблица 'runs' создана")
                
                # Создаем таблицу checkpoint (для хранения состояний langgraph)
                print("📝 Создание таблицы 'checkpoint'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS checkpoint (
                            checkpoint_id VARCHAR PRIMARY KEY,
                            thread_id VARCHAR REFERENCES thread(thread_id),
                            checkpoint_ns VARCHAR DEFAULT '',
                            parent_checkpoint_id VARCHAR,
                            checkpoint BYTEA,
                            metadata_json JSONB DEFAULT '{}',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_checkpoint_thread_id ON checkpoint(thread_id)"))
                print("✅ Таблица 'checkpoint' создана")
                
                # Создаем таблицу checkpoint_writes (для записей checkpoint)
                print("📝 Создание таблицы 'checkpoint_writes'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS checkpoint_writes (
                            thread_id VARCHAR,
                            checkpoint_ns VARCHAR DEFAULT '',
                            checkpoint_id VARCHAR,
                            task_id VARCHAR,
                            idx INTEGER,
                            channel VARCHAR,
                            type VARCHAR,
                            blob BYTEA,
                            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                        )
                    """)
                )
                print("✅ Таблица 'checkpoint_writes' создана")
                
                # Создаем таблицу checkpoint_blobs (для blob данных)
                print("📝 Создание таблицы 'checkpoint_blobs'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS checkpoint_blobs (
                            thread_id VARCHAR,
                            checkpoint_ns VARCHAR DEFAULT '',
                            channel VARCHAR,
                            version VARCHAR,
                            type VARCHAR,
                            blob BYTEA,
                            PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
                        )
                    """)
                )
                print("✅ Таблица 'checkpoint_blobs' создана")
                
                # Создаем таблицу run_events (для событий выполнения)
                # ВАЖНО: id - VARCHAR, т.к. приложение использует составные ID вида "run_id_event_N"
                print("📝 Создание таблицы 'run_events'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS run_events (
                            id VARCHAR PRIMARY KEY,
                            run_id VARCHAR NOT NULL,
                            seq INTEGER DEFAULT 0,
                            event VARCHAR NOT NULL,
                            data JSONB DEFAULT '{}',
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_run_events_created_at ON run_events(created_at)"))
                print("✅ Таблица 'run_events' создана")
            
            print("✅ Базовые таблицы aegra созданы. Остальные структуры будут созданы при первом запуске через SQLModel.")
            engine.dispose()
            return 0
        
        print(f"📊 Найдено таблиц в БД: {len(tables)}")
        migrations_applied = False
        
        # Выполняем миграции только если БД уже существует
        with engine.begin() as conn:
            # Миграция 0: Создание базовых таблиц aegra (assistant, thread, run, checkpoint, etc.)
            # Эти таблицы используются langgraph_service
            
            # 0.1: Таблица assistant
            if "assistant" not in tables:
                print("📝 Миграция 0.1: Создание таблицы 'assistant'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS assistant (
                            assistant_id VARCHAR PRIMARY KEY,
                            name VARCHAR NOT NULL,
                            description VARCHAR,
                            graph_id VARCHAR NOT NULL,
                            config TEXT DEFAULT '{}',
                            context TEXT DEFAULT '{}',
                            user_id VARCHAR,
                            version INTEGER DEFAULT 1,
                            metadata TEXT DEFAULT '{}',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_assistant_graph_id ON assistant(graph_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_assistant_user_id ON assistant(user_id)"))
                print("✅ Миграция 0.1: Таблица 'assistant' создана")
                migrations_applied = True
            else:
                print("✅ Миграция 0.1: Таблица 'assistant' уже существует")
            
            # 0.2: Таблица thread
            if "thread" not in tables:
                print("📝 Миграция 0.2: Создание таблицы 'thread'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS thread (
                            thread_id VARCHAR PRIMARY KEY,
                            status VARCHAR DEFAULT 'idle',
                            metadata_json JSONB DEFAULT '{}',
                            user_id VARCHAR,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_thread_user_id ON thread(user_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_thread_status ON thread(status)"))
                print("✅ Миграция 0.2: Таблица 'thread' создана")
                migrations_applied = True
            else:
                print("✅ Миграция 0.2: Таблица 'thread' уже существует")
            
            # 0.3: Таблица runs (во множественном числе - как требует aegra)
            if "runs" not in tables:
                print("📝 Миграция 0.3: Создание таблицы 'runs'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS runs (
                            run_id VARCHAR PRIMARY KEY,
                            thread_id VARCHAR,
                            assistant_id VARCHAR,
                            status VARCHAR DEFAULT 'pending',
                            input JSONB DEFAULT '{}',
                            config JSONB DEFAULT '{}',
                            context JSONB DEFAULT '{}',
                            output JSONB DEFAULT 'null',
                            error_message VARCHAR,
                            user_id VARCHAR,
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_runs_thread_id ON runs(thread_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_runs_assistant_id ON runs(assistant_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_runs_user_id ON runs(user_id)"))
                print("✅ Миграция 0.3: Таблица 'runs' создана")
                migrations_applied = True
            else:
                print("✅ Миграция 0.3: Таблица 'runs' уже существует")
            
            # 0.4: Таблица checkpoint
            if "checkpoint" not in tables:
                print("📝 Миграция 0.4: Создание таблицы 'checkpoint'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS checkpoint (
                            checkpoint_id VARCHAR PRIMARY KEY,
                            thread_id VARCHAR,
                            checkpoint_ns VARCHAR DEFAULT '',
                            parent_checkpoint_id VARCHAR,
                            checkpoint BYTEA,
                            metadata_json JSONB DEFAULT '{}',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_checkpoint_thread_id ON checkpoint(thread_id)"))
                print("✅ Миграция 0.4: Таблица 'checkpoint' создана")
                migrations_applied = True
            else:
                print("✅ Миграция 0.4: Таблица 'checkpoint' уже существует")
            
            # 0.5: Таблица checkpoint_writes
            if "checkpoint_writes" not in tables:
                print("📝 Миграция 0.5: Создание таблицы 'checkpoint_writes'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS checkpoint_writes (
                            thread_id VARCHAR,
                            checkpoint_ns VARCHAR DEFAULT '',
                            checkpoint_id VARCHAR,
                            task_id VARCHAR,
                            idx INTEGER,
                            channel VARCHAR,
                            type VARCHAR,
                            blob BYTEA,
                            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                        )
                    """)
                )
                print("✅ Миграция 0.5: Таблица 'checkpoint_writes' создана")
                migrations_applied = True
            else:
                print("✅ Миграция 0.5: Таблица 'checkpoint_writes' уже существует")
            
            # 0.6: Таблица checkpoint_blobs
            if "checkpoint_blobs" not in tables:
                print("📝 Миграция 0.6: Создание таблицы 'checkpoint_blobs'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS checkpoint_blobs (
                            thread_id VARCHAR,
                            checkpoint_ns VARCHAR DEFAULT '',
                            channel VARCHAR,
                            version VARCHAR,
                            type VARCHAR,
                            blob BYTEA,
                            PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
                        )
                    """)
                )
                print("✅ Миграция 0.6: Таблица 'checkpoint_blobs' создана")
                migrations_applied = True
            else:
                print("✅ Миграция 0.6: Таблица 'checkpoint_blobs' уже существует")
            
            # 0.7: Таблица run_events (для событий выполнения)
            # ВАЖНО: id - VARCHAR, т.к. приложение использует составные ID вида "run_id_event_N"
            if "run_events" not in tables:
                print("📝 Миграция 0.7: Создание таблицы 'run_events'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS run_events (
                            id VARCHAR PRIMARY KEY,
                            run_id VARCHAR NOT NULL,
                            seq INTEGER DEFAULT 0,
                            event VARCHAR NOT NULL,
                            data JSONB DEFAULT '{}',
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_run_events_created_at ON run_events(created_at)"))
                print("✅ Миграция 0.7: Таблица 'run_events' создана")
                migrations_applied = True
            else:
                print("✅ Миграция 0.7: Таблица 'run_events' уже существует")
            
            # Миграция 1: Добавление колонки user_preferences в таблицу user (если таблица существует)
            if "user" in tables:
                columns = [col["name"] for col in inspector.get_columns("user")]
                if "user_preferences" not in columns:
                    print("📝 Миграция 1: Добавление колонки 'user_preferences' в таблицу 'user'...")
                    conn.execute(
                        text("ALTER TABLE \"user\" ADD COLUMN user_preferences TEXT DEFAULT '{}'")
                    )
                    print("✅ Миграция 1: Колонка 'user_preferences' успешно добавлена")
                    migrations_applied = True
                else:
                    print("✅ Миграция 1: Колонка 'user_preferences' уже существует")
            else:
                print("ℹ️ Миграция 1: Таблица 'user' не существует, будет создана через SQLModel")
            
            # Миграция 2: Создание таблицы chatmessage (только если её нет, но БД уже существует)
            if "chatmessage" not in tables:
                print("📝 Миграция 2: Создание таблицы 'chatmessage'...")
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS chatmessage (
                            id VARCHAR PRIMARY KEY,
                            user_id VARCHAR NOT NULL,
                            thread_id VARCHAR NOT NULL,
                            role VARCHAR NOT NULL,
                            content TEXT NOT NULL,
                            created_at VARCHAR NOT NULL
                        )
                    """)
                )
                # Создаем индексы
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_chatmessage_user_id ON chatmessage(user_id)")
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_chatmessage_thread_id ON chatmessage(thread_id)")
                )
                print("✅ Миграция 2: Таблица 'chatmessage' успешно создана")
                migrations_applied = True
            else:
                print("✅ Миграция 2: Таблица 'chatmessage' уже существует")
            
            # Миграция 3: Добавление полей для регулярных задач в таблицу deferredtask
            if "deferredtask" in tables:
                deferredtask_columns = [col["name"] for col in inspector.get_columns("deferredtask")]
                
                # Добавляем поле task_type
                if "task_type" not in deferredtask_columns:
                    print("📝 Миграция 3.1: Добавление колонки 'task_type' в таблицу 'deferredtask'...")
                    conn.execute(
                        text("ALTER TABLE deferredtask ADD COLUMN task_type VARCHAR DEFAULT 'deferred'")
                    )
                    # Создаем индекс для task_type
                    conn.execute(
                        text("CREATE INDEX IF NOT EXISTS idx_deferredtask_task_type ON deferredtask(task_type)")
                    )
                    print("✅ Миграция 3.1: Колонка 'task_type' успешно добавлена")
                    migrations_applied = True
                else:
                    print("✅ Миграция 3.1: Колонка 'task_type' уже существует")
                
                # Добавляем поле schedule
                if "schedule" not in deferredtask_columns:
                    print("📝 Миграция 3.2: Добавление колонки 'schedule' в таблицу 'deferredtask'...")
                    conn.execute(
                        text("ALTER TABLE deferredtask ADD COLUMN schedule VARCHAR")
                    )
                    # Создаем индекс для schedule
                    conn.execute(
                        text("CREATE INDEX IF NOT EXISTS idx_deferredtask_schedule ON deferredtask(schedule)")
                    )
                    print("✅ Миграция 3.2: Колонка 'schedule' успешно добавлена")
                    migrations_applied = True
                else:
                    print("✅ Миграция 3.2: Колонка 'schedule' уже существует")
                
                # Добавляем поле next_run_at
                if "next_run_at" not in deferredtask_columns:
                    print("📝 Миграция 3.3: Добавление колонки 'next_run_at' в таблицу 'deferredtask'...")
                    conn.execute(
                        text("ALTER TABLE deferredtask ADD COLUMN next_run_at VARCHAR")
                    )
                    # Создаем индекс для next_run_at
                    conn.execute(
                        text("CREATE INDEX IF NOT EXISTS idx_deferredtask_next_run_at ON deferredtask(next_run_at)")
                    )
                    print("✅ Миграция 3.3: Колонка 'next_run_at' успешно добавлена")
                    migrations_applied = True
                else:
                    print("✅ Миграция 3.3: Колонка 'next_run_at' уже существует")
                
                # Добавляем поле last_run_at
                if "last_run_at" not in deferredtask_columns:
                    print("📝 Миграция 3.4: Добавление колонки 'last_run_at' в таблицу 'deferredtask'...")
                    conn.execute(
                        text("ALTER TABLE deferredtask ADD COLUMN last_run_at VARCHAR")
                    )
                    print("✅ Миграция 3.4: Колонка 'last_run_at' успешно добавлена")
                    migrations_applied = True
                else:
                    print("✅ Миграция 3.4: Колонка 'last_run_at' уже существует")
            else:
                print("ℹ️ Миграция 3: Таблица 'deferredtask' не существует, будет создана через SQLModel")
        
        # ========== МИГРАЦИЯ 4: Таблица openrouter_verified_models ==========
        print("\n📝 Миграция 4: Проверка таблицы 'openrouter_verified_models'...")
        
        if "openrouter_verified_models" not in tables:
            print("📝 Создание таблицы 'openrouter_verified_models'...")
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS openrouter_verified_models (
                            id SERIAL PRIMARY KEY,
                            model_id VARCHAR(255) NOT NULL UNIQUE,
                            model_name VARCHAR(500),
                            context_length INTEGER DEFAULT 0,
                            is_fully_functional BOOLEAN DEFAULT FALSE,
                            supports_function_calling BOOLEAN DEFAULT FALSE,
                            supports_streaming BOOLEAN DEFAULT FALSE,
                            supports_system_prompt BOOLEAN DEFAULT FALSE,
                            has_data_policy_issue BOOLEAN DEFAULT FALSE,
                            avg_response_time_ms FLOAT,
                            last_test_basic BOOLEAN,
                            last_test_function_calling BOOLEAN,
                            last_test_system_prompt BOOLEAN,
                            test_error_message TEXT,
                            tested_at TIMESTAMP,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            notes TEXT,
                            deprecation_date TIMESTAMP
                        )
                    """)
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ovm_model_id ON openrouter_verified_models(model_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ovm_fully_functional ON openrouter_verified_models(is_fully_functional)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ovm_function_calling ON openrouter_verified_models(supports_function_calling)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ovm_deprecation_date ON openrouter_verified_models(deprecation_date)"))
                print("✅ Таблица 'openrouter_verified_models' создана")
                migrations_applied = True
        else:
            print("✅ Миграция 4: Таблица 'openrouter_verified_models' уже существует")
            
            # Проверяем наличие поля deprecation_date
            columns = [col["name"] for col in inspector.get_columns("openrouter_verified_models")]
            if "deprecation_date" not in columns:
                print("📝 Миграция 4.1: Добавление колонки 'deprecation_date' в таблицу 'openrouter_verified_models'...")
                with engine.begin() as conn:
                    conn.execute(
                        text("ALTER TABLE openrouter_verified_models ADD COLUMN deprecation_date TIMESTAMP")
                    )
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ovm_deprecation_date ON openrouter_verified_models(deprecation_date)"))
                    print("✅ Миграция 4.1: Колонка 'deprecation_date' успешно добавлена")
                    migrations_applied = True
            else:
                print("✅ Миграция 4.1: Колонка 'deprecation_date' уже существует")
        
        engine.dispose()
        
        if migrations_applied:
            print("✅ Миграции успешно применены!")
        else:
            print("✅ Все структуры актуальны, миграции не требуются.")
        
        return 0
        
    except Exception as e:
        print(f"❌ Ошибка при выполнении миграций: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(run_migrations())

