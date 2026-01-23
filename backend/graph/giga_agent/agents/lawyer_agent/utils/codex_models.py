"""
Модели базы данных для работы с кодексами
Используется SQLAlchemy для работы с SQLite/PostgreSQL
"""

from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()

class Codex(Base):
    """Модель кодекса"""
    __tablename__ = 'codexes'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(500), nullable=False, unique=True, index=True)  # Полное название кодекса
    short_name = Column(String(100), nullable=True, index=True)  # Краткое название (УПК РФ, ГПК РФ и т.д.)
    abbreviation = Column(String(50), nullable=True, index=True)  # Аббревиатура (УПК, ГПК, АПК и т.д.)
    full_text = Column(Text, nullable=True)  # Полный текст кодекса (опционально, для быстрого доступа)
    file_path = Column(String(1000), nullable=True)  # Путь к исходному файлу
    file_modified_date = Column(String(50), nullable=True)  # Дата/время модификации файла (ISO format)
    priority_level = Column(String(10), nullable=True, default='2', index=True)  # Уровень приоритета: '0' (высший), '1', '2' (по умолчанию), '3' (низкий)
    # Реквизиты документа, извлеченные из начала файла
    doc_type = Column(String(200), nullable=True, index=True)  # Тип документа (Федеральный закон, Постановление и т.д.)
    doc_number = Column(String(100), nullable=True, index=True)  # Номер документа (№ 123-ФЗ и т.д.)
    doc_date = Column(String(50), nullable=True, index=True)  # Дата документа (от 01.01.2024 и т.д.)
    doc_parsed_name = Column(String(500), nullable=True)  # Название, извлеченное из начала файла
    doc_authority = Column(String(200), nullable=True, index=True)  # Государственный орган, принявший документ (Государственная Дума РФ и т.д.)
    created_at = Column(String(50), default=lambda: datetime.utcnow().isoformat())
    updated_at = Column(String(50), default=lambda: datetime.utcnow().isoformat(), onupdate=lambda: datetime.utcnow().isoformat())
    
    # Связи
    sections = relationship('CodexSection', back_populates='codex', cascade='all, delete-orphan', lazy='dynamic')
    chapters = relationship('CodexChapter', back_populates='codex', cascade='all, delete-orphan', lazy='dynamic')
    articles = relationship('CodexArticle', back_populates='codex', cascade='all, delete-orphan', lazy='dynamic')
    
    def to_dict(self):
        """Преобразует объект в словарь"""
        return {
            'id': self.id,
            'name': self.name,
            'short_name': self.short_name,
            'abbreviation': self.abbreviation,
            'file_path': self.file_path,
            'file_modified_date': self.file_modified_date,
            'priority_level': self.priority_level,
            'doc_type': self.doc_type,
            'doc_number': self.doc_number,
            'doc_date': self.doc_date,
            'doc_parsed_name': self.doc_parsed_name,
            'doc_authority': self.doc_authority,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }

class CodexSection(Base):
    """Модель раздела кодекса"""
    __tablename__ = 'codex_sections'
    
    id = Column(Integer, primary_key=True)
    codex_id = Column(Integer, ForeignKey('codexes.id', ondelete='CASCADE'), nullable=False, index=True)
    number = Column(String(50), nullable=True)  # Номер раздела (римские цифры или текст)
    title = Column(String(500), nullable=True)  # Название раздела
    content = Column(Text, nullable=True)  # Содержимое раздела
    order_index = Column(Integer, nullable=True)  # Порядок в кодексе
    
    # Связи
    codex = relationship('Codex', back_populates='sections')
    chapters = relationship('CodexChapter', back_populates='section', cascade='all, delete-orphan', lazy='dynamic')
    
    __table_args__ = (
        Index('idx_codex_section', 'codex_id', 'number'),
    )
    
    def to_dict(self):
        """Преобразует объект в словарь"""
        return {
            'id': self.id,
            'codex_id': self.codex_id,
            'number': self.number,
            'title': self.title,
            'content': self.content,
            'order_index': self.order_index
        }

class CodexChapter(Base):
    """Модель главы кодекса"""
    __tablename__ = 'codex_chapters'
    
    id = Column(Integer, primary_key=True)
    codex_id = Column(Integer, ForeignKey('codexes.id', ondelete='CASCADE'), nullable=False, index=True)
    section_id = Column(Integer, ForeignKey('codex_sections.id', ondelete='SET NULL'), nullable=True, index=True)
    number = Column(String(50), nullable=True)  # Номер главы
    title = Column(String(500), nullable=True)  # Название главы
    content = Column(Text, nullable=True)  # Содержимое главы
    order_index = Column(Integer, nullable=True)  # Порядок в кодексе/разделе
    
    # Связи
    codex = relationship('Codex', back_populates='chapters')
    section = relationship('CodexSection', back_populates='chapters')
    articles = relationship('CodexArticle', back_populates='chapter', cascade='all, delete-orphan', lazy='dynamic')
    
    __table_args__ = (
        Index('idx_codex_chapter', 'codex_id', 'number'),
        Index('idx_section_chapter', 'section_id', 'number'),
    )
    
    def to_dict(self):
        """Преобразует объект в словарь"""
        return {
            'id': self.id,
            'codex_id': self.codex_id,
            'section_id': self.section_id,
            'number': self.number,
            'title': self.title,
            'content': self.content,
            'order_index': self.order_index
        }

class CodexArticle(Base):
    """Модель статьи кодекса"""
    __tablename__ = 'codex_articles'
    
    id = Column(Integer, primary_key=True)
    codex_id = Column(Integer, ForeignKey('codexes.id', ondelete='CASCADE'), nullable=False, index=True)
    chapter_id = Column(Integer, ForeignKey('codex_chapters.id', ondelete='SET NULL'), nullable=True, index=True)
    section_id = Column(Integer, ForeignKey('codex_sections.id', ondelete='SET NULL'), nullable=True, index=True)
    number = Column(String(50), nullable=False, index=True)  # Номер статьи (может быть "389.1", "75" и т.д.)
    title = Column(String(500), nullable=True)  # Название статьи
    content = Column(Text, nullable=False)  # Содержимое статьи
    order_index = Column(Integer, nullable=True)  # Порядок в кодексе/главе
    
    # Поля для хранения полной структуры (для быстрого поиска без JOIN)
    codex_name = Column(String(500), nullable=True, index=True)  # Название кодекса
    section_number = Column(String(50), nullable=True, index=True)  # Номер раздела
    section_title = Column(String(500), nullable=True)  # Название раздела
    chapter_number = Column(String(50), nullable=True, index=True)  # Номер главы
    chapter_title = Column(String(500), nullable=True)  # Название главы
    part_number = Column(String(50), nullable=True, index=True)  # Номер части (если есть)
    part_title = Column(String(500), nullable=True)  # Название части (если есть)
    paragraph_number = Column(String(50), nullable=True, index=True)  # Номер параграфа (если есть)
    paragraph_title = Column(String(500), nullable=True)  # Название параграфа (если есть)
    full_structure_path = Column(Text, nullable=True, index=True)  # Полный путь структуры для поиска
    priority_level = Column(String(10), nullable=True, default='2', index=True)  # Уровень приоритета: '0' (высший), '1', '2' (по умолчанию), '3' (низкий) (наследуется от кодекса)
    
    # Связи
    codex = relationship('Codex', back_populates='articles')
    chapter = relationship('CodexChapter', back_populates='articles')
    section = relationship('CodexSection')
    
    __table_args__ = (
        Index('idx_codex_article', 'codex_id', 'number'),
        Index('idx_chapter_article', 'chapter_id', 'number'),
        Index('idx_article_number', 'number'),
        Index('idx_codex_name', 'codex_name'),
        Index('idx_section_number', 'section_number'),
        Index('idx_chapter_number', 'chapter_number'),
        Index('idx_full_structure_path', 'full_structure_path'),
    )
    
    def to_dict(self):
        """Преобразует объект в словарь"""
        return {
            'id': self.id,
            'codex_id': self.codex_id,
            'chapter_id': self.chapter_id,
            'section_id': self.section_id,
            'number': self.number,
            'title': self.title,
            'content': self.content,
            'order_index': self.order_index,
            'codex_name': self.codex_name,
            'section_number': self.section_number,
            'section_title': self.section_title,
            'chapter_number': self.chapter_number,
            'chapter_title': self.chapter_title,
            'part_number': self.part_number,
            'part_title': self.part_title,
            'paragraph_number': self.paragraph_number,
            'paragraph_title': self.paragraph_title,
            'full_structure_path': self.full_structure_path,
            'priority_level': self.priority_level
        }


# Функции для работы с БД
def get_database_url():
    """
    Получает URL базы данных для кодексов.
    ВАЖНО: Кодексы всегда используют SQLite, независимо от DATABASE_URL.
    Это необходимо, так как код синхронный, а DATABASE_URL может указывать на asyncpg.
    """
    # ВАЖНО: Кодексы всегда используют SQLite (как в lawyer_helpers_base)
    # Это гарантирует синхронную работу без проблем с asyncpg
    from giga_agent.agents.lawyer_agent.utils.paths import get_codex_db_path
    db_file = get_codex_db_path()
    db_url = f'sqlite:///{db_file}'
    logger.debug(f"[codex_models] Используется SQLite для кодексов: {db_file}")
    return db_url

def create_engine_instance():
    """Создает экземпляр engine для работы с БД кодексов (всегда SQLite)"""
    db_url = get_database_url()
    # Кодексы всегда используют SQLite, поэтому проверяем только SQLite
    if db_url.startswith('sqlite'):
        # Для SQLite отключаем проверку внешних ключей при создании
        engine = create_engine(db_url, echo=False, connect_args={'check_same_thread': False})
    else:
        # Если по какой-то причине не SQLite, создаем engine как есть
        logger.warning(f"[codex_models] Неожиданный тип БД для кодексов: {db_url[:50]}...")
        engine = create_engine(db_url, echo=False)
    return engine

def init_database():
    """Инициализирует базу данных (создает таблицы)"""
    engine = create_engine_instance()
    Base.metadata.create_all(engine)
    
    # Миграции: добавляем колонки, если их нет
    _migrate_add_file_modified_date(engine)
    _migrate_add_structure_fields(engine)
    _migrate_add_priority_level(engine)
    _migrate_add_document_metadata_fields(engine)
    
    return engine

def _migrate_add_file_modified_date(engine):
    """Добавляет колонку file_modified_date в таблицу codexes, если её нет"""
    from sqlalchemy import inspect, text
    
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('codexes')]
        
        if 'file_modified_date' not in columns:
            logger.info("Миграция: добавление колонки file_modified_date в таблицу codexes...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE codexes ADD COLUMN file_modified_date VARCHAR(50)"))
            logger.info("Миграция: колонка file_modified_date успешно добавлена")
        else:
            logger.debug("Колонка file_modified_date уже существует")
    except Exception as e:
        # Если таблицы еще нет, это нормально - она будет создана при create_all
        error_str = str(e).lower()
        if 'no such table' not in error_str and 'does not exist' not in error_str:
            logger.warning(f"Ошибка при проверке/добавлении колонки file_modified_date: {e}")

def _migrate_add_structure_fields(engine):
    """Добавляет поля структуры в таблицу codex_articles, если их нет"""
    from sqlalchemy import inspect, text
    
    try:
        inspector = inspect(engine)
        # Проверяем, существует ли таблица
        if 'codex_articles' not in inspector.get_table_names():
            logger.debug("Таблица codex_articles еще не существует, миграция не требуется")
            return
        
        columns = [col['name'] for col in inspector.get_columns('codex_articles')]
        
        # Список полей для добавления
        new_fields = [
            ('codex_name', 'VARCHAR(500)'),
            ('section_number', 'VARCHAR(50)'),
            ('section_title', 'VARCHAR(500)'),
            ('chapter_number', 'VARCHAR(50)'),
            ('chapter_title', 'VARCHAR(500)'),
            ('part_number', 'VARCHAR(50)'),
            ('part_title', 'VARCHAR(500)'),
            ('paragraph_number', 'VARCHAR(50)'),
            ('paragraph_title', 'VARCHAR(500)'),
            ('full_structure_path', 'TEXT'),
        ]
        
        added_fields = []
        for field_name, field_type in new_fields:
            if field_name not in columns:
                try:
                    logger.info(f"Миграция: добавление колонки {field_name} в таблицу codex_articles...")
                    with engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE codex_articles ADD COLUMN {field_name} {field_type}"))
                    added_fields.append(field_name)
                    logger.info(f"Миграция: колонка {field_name} успешно добавлена")
                except Exception as field_error:
                    logger.warning(f"Ошибка при добавлении колонки {field_name}: {field_error}")
            else:
                logger.debug(f"Колонка {field_name} уже существует")
        
        # Создаем индексы для новых полей
        if added_fields:
            try:
                # Для SQLite нужно создавать индексы отдельно
                index_fields = ['codex_name', 'section_number', 'chapter_number', 'full_structure_path']
                for field_name in index_fields:
                    if field_name in added_fields:
                        try:
                            index_name = f'idx_article_{field_name}'
                            with engine.begin() as conn:
                                # Проверяем, существует ли индекс
                                result = conn.execute(text(
                                    f"SELECT name FROM sqlite_master WHERE type='index' AND name='{index_name}'"
                                )).fetchone()
                                if not result:
                                    conn.execute(text(
                                        f"CREATE INDEX {index_name} ON codex_articles({field_name})"
                                    ))
                                    logger.info(f"Миграция: создан индекс {index_name}")
                        except Exception as idx_error:
                            logger.warning(f"Ошибка при создании индекса для {field_name}: {idx_error}")
            except Exception as idx_error:
                logger.warning(f"Ошибка при создании индексов: {idx_error}")
        
        if added_fields:
            logger.info(f"Миграция: добавлено полей структуры: {', '.join(added_fields)}")
        else:
            logger.debug("Миграция: все поля структуры уже существуют")
            
    except Exception as e:
        # Если таблицы еще нет, это нормально - она будет создана при create_all
        error_str = str(e).lower()
        if 'no such table' not in error_str and 'does not exist' not in error_str:
            logger.warning(f"Ошибка при проверке/добавлении полей структуры: {e}")

def _migrate_add_priority_level(engine):
    """Добавляет поле priority_level в таблицы codexes и codex_articles, если его нет"""
    from sqlalchemy import inspect, text
    
    try:
        inspector = inspect(engine)
        
        # Миграция для таблицы codexes
        if 'codexes' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('codexes')]
            if 'priority_level' not in columns:
                logger.info("Миграция: добавление колонки priority_level в таблицу codexes...")
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE codexes ADD COLUMN priority_level VARCHAR(10) DEFAULT '1'"))
                    # Устанавливаем уровень '1' для всех существующих записей
                    conn.execute(text("UPDATE codexes SET priority_level = '1' WHERE priority_level IS NULL"))
                    # Создаем индекс
                    try:
                        conn.execute(text("CREATE INDEX idx_codex_priority_level ON codexes(priority_level)"))
                    except Exception:
                        pass  # Индекс может уже существовать
                logger.info("Миграция: колонка priority_level успешно добавлена в codexes")
            else:
                logger.debug("Колонка priority_level уже существует в codexes")
        
        # Миграция для таблицы codex_articles
        if 'codex_articles' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('codex_articles')]
            if 'priority_level' not in columns:
                logger.info("Миграция: добавление колонки priority_level в таблицу codex_articles...")
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE codex_articles ADD COLUMN priority_level VARCHAR(10) DEFAULT '1'"))
                    # Устанавливаем уровень '1' для всех существующих записей
                    conn.execute(text("UPDATE codex_articles SET priority_level = '1' WHERE priority_level IS NULL"))
                    # Создаем индекс
                    try:
                        conn.execute(text("CREATE INDEX idx_article_priority_level ON codex_articles(priority_level)"))
                    except Exception:
                        pass  # Индекс может уже существовать
                logger.info("Миграция: колонка priority_level успешно добавлена в codex_articles")
            else:
                logger.debug("Колонка priority_level уже существует в codex_articles")
                
    except Exception as e:
        error_str = str(e).lower()
        if 'no such table' not in error_str and 'does not exist' not in error_str:
            logger.warning(f"Ошибка при проверке/добавлении колонки priority_level: {e}")

def _migrate_add_document_metadata_fields(engine):
    """Добавляет поля метаданных документа в таблицу codexes, если их нет"""
    from sqlalchemy import inspect, text
    
    try:
        inspector = inspect(engine)
        
        if 'codexes' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('codexes')]
            
            # Список полей для добавления
            new_fields = [
                ('doc_type', 'VARCHAR(200)'),
                ('doc_number', 'VARCHAR(100)'),
                ('doc_date', 'VARCHAR(50)'),
                ('doc_parsed_name', 'VARCHAR(500)'),
                ('doc_authority', 'VARCHAR(200)'),
            ]
            
            added_fields = []
            for field_name, field_type in new_fields:
                if field_name not in columns:
                    try:
                        logger.info(f"Миграция: добавление колонки {field_name} в таблицу codexes...")
                        with engine.begin() as conn:
                            conn.execute(text(f"ALTER TABLE codexes ADD COLUMN {field_name} {field_type}"))
                        added_fields.append(field_name)
                        logger.info(f"Миграция: колонка {field_name} успешно добавлена")
                    except Exception as field_error:
                        logger.warning(f"Ошибка при добавлении колонки {field_name}: {field_error}")
                else:
                    logger.debug(f"Колонка {field_name} уже существует")
            
            # Создаем индексы для новых полей
            if added_fields:
                index_fields = ['doc_type', 'doc_number', 'doc_date', 'doc_authority']
                for field_name in index_fields:
                    if field_name in added_fields:
                        try:
                            index_name = f'idx_codex_{field_name}'
                            with engine.begin() as conn:
                                result = conn.execute(text(
                                    f"SELECT name FROM sqlite_master WHERE type='index' AND name='{index_name}'"
                                )).fetchone()
                                if not result:
                                    conn.execute(text(
                                        f"CREATE INDEX {index_name} ON codexes({field_name})"
                                    ))
                                    logger.info(f"Миграция: создан индекс {index_name}")
                        except Exception as idx_error:
                            logger.warning(f"Ошибка при создании индекса для {field_name}: {idx_error}")
            
            if added_fields:
                logger.info(f"Миграция: добавлено полей метаданных: {', '.join(added_fields)}")
            else:
                logger.debug("Миграция: все поля метаданных уже существуют")
                
    except Exception as e:
        error_str = str(e).lower()
        if 'no such table' not in error_str and 'does not exist' not in error_str:
            logger.warning(f"Ошибка при проверке/добавлении полей метаданных: {e}")

def get_session(engine=None):
    """Создает сессию для работы с БД"""
    if engine is None:
        engine = create_engine_instance()
    Session = sessionmaker(bind=engine)
    return Session()

