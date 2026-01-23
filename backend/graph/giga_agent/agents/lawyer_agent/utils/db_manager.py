"""
Менеджер для автоматической загрузки и обновления БД кодексов и векторного хранилища
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from giga_agent.agents.lawyer_agent.utils.paths import get_law_folder, get_vector_store_folder
from giga_agent.agents.lawyer_agent.utils.codex_loader import CodexLoader
from giga_agent.agents.lawyer_agent.utils.codex_models import init_database
from giga_agent.agents.lawyer_agent.utils.vector_store import get_embeddings, get_vector_store

logger = logging.getLogger(__name__)


def ensure_databases_initialized(force_reload: bool = False) -> Dict[str, Any]:
    """
    Обеспечивает инициализацию БД кодексов и векторного хранилища
    
    Логика:
    1. Проверяет наличие codexes.db
    2. Если БД нет или force_reload=True, загружает кодексы из папки law/
    3. Проверяет наличие новых файлов и обновляет БД
    4. Проверяет наличие векторного хранилища
    5. Если векторного хранилища нет, создает его из статей БД
    
    Args:
        force_reload: Если True, перезагружает все данные
        
    Returns:
        Словарь со статистикой инициализации
    """
    stats = {
        'codex_db_exists': False,
        'codex_db_created': False,
        'codex_db_updated': False,
        'vector_store_exists': False,
        'vector_store_created': False,
        'codexes_loaded': 0,
        'articles_loaded': 0,
        'errors': []
    }
    
    try:
        # Инициализируем БД (создает таблицы, если их нет)
        logger.info("Инициализация структуры БД...")
        init_database()
        stats['codex_db_exists'] = True
        
        # Проверяем наличие БД файла
        from giga_agent.agents.lawyer_agent.utils.paths import get_codex_db_path
        db_path = get_codex_db_path()
        
        # Проверяем папку law для текстовых файлов
        law_folder = get_law_folder()
        
        if not law_folder.exists():
            logger.warning(f"Папка law не найдена: {law_folder}")
            logger.info("Создана пустая папка law. Разместите текстовые файлы кодексов в law/акты/")
            return stats
        
        # Ищем текстовые файлы в папке law
        txt_files = list(law_folder.rglob("*.txt"))
        
        if not txt_files:
            logger.warning(f"Текстовые файлы не найдены в {law_folder}")
            logger.info("Разместите текстовые файлы кодексов в law/акты/ или law/")
            # Если БД нет, создаем пустую структуру
            if not db_path.exists():
                logger.info("Создана пустая БД. Добавьте текстовые файлы кодексов в law/ для загрузки.")
            return stats
        
        logger.info(f"Найдено текстовых файлов: {len(txt_files)}")
        
        # Проверяем, нужно ли загружать/обновлять БД
        need_load = force_reload or not db_path.exists()
        
        if need_load or _has_new_files(txt_files, db_path):
            logger.info("Начинаем загрузку/обновление кодексов в БД...")
            
            # Создаем CodexLoader (передаем корневую папку law как knowledge_base_path)
            loader = CodexLoader(law_folder)
            
            try:
                # Загружаем все кодексы
                # Ищем папки с уровнями приоритета или просто папку акты
                codex_dir = law_folder / 'акты'
                if not codex_dir.exists():
                    codex_dir = law_folder
                
                # Загружаем кодексы
                loader.load_all_codexes(codex_dir)
                
                # Коммитим изменения
                loader.session.commit()
                
                stats['codex_db_created'] = True
                stats['codex_db_updated'] = True
                logger.info("Кодексы успешно загружены в БД")
                
            except Exception as e:
                logger.error(f"Ошибка загрузки кодексов: {e}")
                import traceback
                logger.error(f"Трассировка:\n{traceback.format_exc()}")
                stats['errors'].append(f"Ошибка загрузки кодексов: {str(e)}")
                loader.session.rollback()
            finally:
                loader.close()
        
        # Проверяем векторное хранилище
        vector_store_folder = get_vector_store_folder()
        faiss_file = vector_store_folder / "index.faiss"
        pkl_file = vector_store_folder / "index.pkl"
        
        stats['vector_store_exists'] = faiss_file.exists() and pkl_file.exists()
        
        if not stats['vector_store_exists'] or force_reload:
            logger.info("Создание векторного хранилища из статей БД...")
            
            try:
                create_vector_store_from_db()
                stats['vector_store_created'] = True
                logger.info("Векторное хранилище успешно создано")
            except Exception as e:
                logger.error(f"Ошибка создания векторного хранилища: {e}")
                stats['errors'].append(f"Ошибка создания векторного хранилища: {str(e)}")
        
        return stats
        
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")
        import traceback
        logger.error(f"Трассировка:\n{traceback.format_exc()}")
        stats['errors'].append(f"Критическая ошибка: {str(e)}")
        return stats


def _has_new_files(txt_files: list, db_path: Path) -> bool:
    """
    Проверяет, есть ли новые или измененные файлы
    
    Args:
        txt_files: Список путей к текстовым файлам
        db_path: Путь к БД
        
    Returns:
        True, если есть новые или измененные файлы
    """
    if not db_path.exists():
        return True
    
    try:
        from giga_agent.agents.lawyer_agent.utils.codex_models import get_session, Codex
        from giga_agent.agents.lawyer_agent.utils.codex_models import create_engine_instance
        
        engine = create_engine_instance()
        session = get_session(engine)
        
        # Получаем все файлы из БД с датами модификации
        codexes = session.query(Codex).filter(Codex.file_path.isnot(None)).all()
        db_files = {codex.file_path: codex.file_modified_date for codex in codexes}
        
        # Проверяем каждый файл
        for txt_file in txt_files:
            file_path_str = str(txt_file)
            
            # Если файла нет в БД - новый файл
            if file_path_str not in db_files:
                session.close()
                return True
            
            # Проверяем дату модификации
            file_mtime = txt_file.stat().st_mtime
            file_modified_date = datetime.fromtimestamp(file_mtime).isoformat()
            
            if file_modified_date != db_files[file_path_str]:
                session.close()
                return True
        
        session.close()
        return False
        
    except Exception as e:
        logger.warning(f"Ошибка проверки новых файлов: {e}, считаем что есть новые файлы")
        return True


def create_vector_store_from_db():
    """
    Создает векторное хранилище из статей в БД
    """
    from giga_agent.agents.lawyer_agent.utils.codex_service import CodexService
    from giga_agent.agents.lawyer_agent.utils.codex_models import CodexArticle, Codex
    from giga_agent.agents.lawyer_agent.utils.paths import get_vector_store_folder
    
    try:
        from langchain_community.vectorstores import FAISS
    except ImportError:
        from langchain.vectorstores import FAISS
    
    try:
        from langchain_core.documents import Document
    except ImportError:
        from langchain.schema import Document
    
    # Получаем embeddings
    from giga_agent.agents.lawyer_agent.utils.vector_store import get_embeddings
    embeddings = get_embeddings()
    if embeddings is None:
        raise RuntimeError("Не удалось загрузить embeddings для векторного хранилища")
    
    # Получаем CodexService
    codex_service = CodexService()
    
    if not codex_service.session:
        raise RuntimeError("CodexService не инициализирован")
    
    # Получаем все статьи из БД
    logger.info("Загрузка статей из БД для создания векторного хранилища...")
    articles = codex_service.session.query(CodexArticle).join(Codex).all()
    
    if not articles:
        logger.warning("Статьи не найдены в БД, создаем пустое векторное хранилище")
        vector_store = FAISS.from_texts(["База знаний пуста"], embeddings)
    else:
        logger.info(f"Найдено статей: {len(articles)}")
        
        # Создаем Document объекты из статей
        chunks = []
        for article in articles:
            try:
                codex = codex_service.codexes_cache.get(article.codex_id)
                if not codex:
                    codex = codex_service.session.query(Codex).filter_by(id=article.codex_id).first()
                
                if not codex:
                    continue
                
                # Формируем текст статьи
                article_text = f"Статья {article.number}"
                if article.title:
                    article_text += f". {article.title}"
                article_text += f"\n\n{article.content}"
                
                # Формируем метаданные
                metadata = {
                    'level': 'Кодексы и законы',
                    'chunk_type': 'article',
                    'article_id': article.id,
                    'article_number': article.number,
                    'article_title': article.title,
                    'codex_id': codex.id,
                    'codex_name': codex.name,
                    'codex_abbreviation': codex.abbreviation or codex.short_name,
                    'priority_level': article.priority_level or codex.priority_level or '2',
                    'source': f"{codex.name} - Статья {article.number}",
                    'filename': f"{codex.name} - Статья {article.number}",
                }
                
                # Добавляем структуру, если есть
                if article.section_number:
                    metadata['section_number'] = article.section_number
                    metadata['section_title'] = article.section_title
                if article.chapter_number:
                    metadata['chapter_number'] = article.chapter_number
                    metadata['chapter_title'] = article.chapter_title
                if article.full_structure_path:
                    metadata['full_structure_path'] = article.full_structure_path
                
                doc = Document(page_content=article_text, metadata=metadata)
                chunks.append(doc)
                
            except Exception as e:
                logger.debug(f"Ошибка обработки статьи {article.id}: {e}")
                continue
        
        logger.info(f"Создано документов для индексирования: {len(chunks)}")
        
        # Создаем векторное хранилище батчами
        batch_size = 1000
        if len(chunks) == 0:
            vector_store = FAISS.from_texts(["База знаний пуста"], embeddings)
        else:
            # Создаем из первого батча
            first_batch = chunks[:batch_size]
            logger.info(f"Создание векторного хранилища из {len(first_batch)} документов...")
            vector_store = FAISS.from_documents(first_batch, embeddings)
            
            # Добавляем остальные батчи
            remaining_chunks = chunks[batch_size:]
            if remaining_chunks:
                logger.info(f"Добавление оставшихся {len(remaining_chunks)} документов...")
                for i in range(0, len(remaining_chunks), batch_size):
                    batch = remaining_chunks[i:i + batch_size]
                    vector_store.add_documents(batch)
                    if (i // batch_size + 1) % 10 == 0:
                        logger.info(f"Обработано {min(i + batch_size, len(remaining_chunks))} / {len(remaining_chunks)} документов")
        
        logger.info(f"Векторное хранилище создано. Всего документов: {vector_store.index.ntotal}")
    
    # Сохраняем векторное хранилище
    vector_store_path = get_vector_store_folder()
    logger.info(f"Сохранение векторного хранилища в {vector_store_path}...")
    vector_store.save_local(str(vector_store_path.absolute()), allow_dangerous_deserialization=True)
    logger.info("Векторное хранилище сохранено")

