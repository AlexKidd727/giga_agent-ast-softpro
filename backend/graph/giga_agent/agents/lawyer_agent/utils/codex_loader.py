"""
Модуль для загрузки кодексов из файлов в базу данных
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime
from giga_agent.agents.lawyer_agent.utils.codex_models import (
    Codex, CodexSection, CodexChapter, CodexArticle,
    init_database, get_session
)
import logging

logger = logging.getLogger(__name__)

# Месяцы для парсинга дат
MONTHS_RU = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
    'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
    'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'май': 5, 'июн': 6,
    'июл': 7, 'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12
}

class CodexLoader:
    """Класс для загрузки кодексов из файлов в БД"""
    
    def __init__(self, knowledge_base_path: Path, legal_extractor=None):
        """
        Args:
            knowledge_base_path: Путь к базе знаний (где находятся файлы кодексов)
            legal_extractor: Опциональный LegalDataExtractor для LLM-парсинга метаданных
        """
        self.knowledge_base_path = Path(knowledge_base_path)
        self.engine = init_database()
        self.session = get_session(self.engine)
        self.legal_extractor = legal_extractor
    
    @staticmethod
    def get_priority_level_from_folder(folder_name: str) -> str:
        """
        Определяет уровень приоритета по имени папки
        
        Простая система уровней: 0 (самый высокий), 1, 2 (по умолчанию), 3 (низкий)
        
        Args:
            folder_name: Имя папки
            
        Returns:
            Уровень приоритета: '0', '1', '2', '3'
        """
        folder_lower = folder_name.lower().strip()
        
        # Уровень 0 - самый высокий приоритет
        if any(keyword in folder_lower for keyword in ['уровень 0', 'level 0', 'приоритет 0', 'priority 0', 'уроверь 0']):
            return '0'
        if folder_lower in ['0']:
            return '0'
        
        # Уровень 1 - высокий приоритет
        if any(keyword in folder_lower for keyword in ['уровень 1', 'level 1', 'приоритет 1', 'priority 1', 'уроверь 1']):
            return '1'
        if folder_lower in ['1']:
            return '1'
        
        # Уровень 3 - низкий приоритет
        if any(keyword in folder_lower for keyword in ['уровень 3', 'level 3', 'приоритет 3', 'priority 3', 'уроверь 3']):
            return '3'
        if folder_lower in ['3']:
            return '3'
        
        # Уровень 2 - средний приоритет (по умолчанию)
        # Также обрабатываем старые названия для обратной совместимости
        if any(keyword in folder_lower for keyword in ['уровень 2', 'level 2', 'приоритет 2', 'priority 2', 'уроверь 2',
                                                        'уровень 0а', 'level 0а', '0а', '0a',  # Старые названия
                                                        'уровень 1а', 'level 1а', '1а', '1a']):  # Старые названия
            return '2'
        
        # Если не найдено совпадение, возвращаем уровень 2 по умолчанию
        return '2'
    
    def load_codex_from_file(self, file_path: Path, codex_name: str, 
                            short_name: Optional[str] = None,
                            abbreviation: Optional[str] = None,
                            priority_level: str = '2') -> Optional[Codex]:
        """
        Загружает кодекс из файла в БД
        
        Args:
            file_path: Путь к файлу кодекса
            codex_name: Полное название кодекса
            short_name: Краткое название
            abbreviation: Аббревиатура
            
        Returns:
            Объект Codex или None при ошибке
        """
        try:
            logger.info(f"[{codex_name}] Начало загрузки кодекса...")
            
            # Проверяем существование файла
            if not file_path.exists():
                logger.error(f"[{codex_name}] Файл не найден: {file_path}")
                return None
            
            # Получаем дату модификации файла
            file_mtime = file_path.stat().st_mtime
            file_modified_date = datetime.fromtimestamp(file_mtime).isoformat()
            
            # Сначала читаем начало файла для парсинга метаданных (для проверки по всем реквизитам)
            encodings = ['windows-1251', 'utf-8', 'cp1251', 'latin-1']
            content_preview = None
            used_encoding = None
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content_preview = f.read(2000)  # Читаем первые 2000 символов для парсинга метаданных
                    # Удаляем boilerplate текст КонсультантПлюс из превью
                    content_preview = self._remove_consultant_plus_boilerplate(content_preview)
                    used_encoding = encoding
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            
            # Парсим метаданные из начала файла
            metadata = {}
            if content_preview:
                metadata = self._parse_document_metadata(content_preview)
            
            # Проверяем, существует ли документ в БД по ВСЕМ реквизитам одновременно
            # Используем комбинацию реквизитов для более точной проверки
            from sqlalchemy import and_
            
            # Ищем документ по комбинации реквизитов (приоритет: более точные комбинации)
            existing_codex = None
            
            # 1. Сначала проверяем по пути к файлу (самый точный признак)
            if not existing_codex:
                existing_codex = self.session.query(Codex).filter(
                    Codex.file_path == str(file_path)
                ).first()
                if existing_codex:
                    logger.debug(f"[{codex_name}] Найден документ в БД по пути к файлу")
            
            # 2. Если есть метаданные, проверяем по комбинации всех реквизитов
            if not existing_codex and metadata:
                # Приоритет 1: тип + номер + дата (самая точная комбинация)
                if metadata.get('doc_type') and metadata.get('doc_number') and metadata.get('doc_date'):
                    existing_codex = self.session.query(Codex).filter(
                        and_(
                            Codex.doc_type == metadata['doc_type'],
                            Codex.doc_number == metadata['doc_number'],
                            Codex.doc_date == metadata['doc_date']
                        )
                    ).first()
                    if existing_codex:
                        logger.info(f"[{codex_name}] Найден документ в БД по комбинации: тип + номер + дата")
                
                # Приоритет 2: тип + номер
                if not existing_codex and metadata.get('doc_type') and metadata.get('doc_number'):
                    existing_codex = self.session.query(Codex).filter(
                        and_(
                            Codex.doc_type == metadata['doc_type'],
                            Codex.doc_number == metadata['doc_number']
                        )
                    ).first()
                    if existing_codex:
                        logger.info(f"[{codex_name}] Найден документ в БД по комбинации: тип + номер")
                
                # Приоритет 3: тип + дата
                if not existing_codex and metadata.get('doc_type') and metadata.get('doc_date'):
                    existing_codex = self.session.query(Codex).filter(
                        and_(
                            Codex.doc_type == metadata['doc_type'],
                            Codex.doc_date == metadata['doc_date']
                        )
                    ).first()
                    if existing_codex:
                        logger.info(f"[{codex_name}] Найден документ в БД по комбинации: тип + дата")
                
                # Приоритет 4: номер + дата
                if not existing_codex and metadata.get('doc_number') and metadata.get('doc_date'):
                    existing_codex = self.session.query(Codex).filter(
                        and_(
                            Codex.doc_number == metadata['doc_number'],
                            Codex.doc_date == metadata['doc_date']
                        )
                    ).first()
                    if existing_codex:
                        logger.info(f"[{codex_name}] Найден документ в БД по комбинации: номер + дата")
                
                # Приоритет 5: название из файла (если оно достаточно уникальное)
                if not existing_codex and metadata.get('doc_parsed_name') and len(metadata['doc_parsed_name']) > 30:
                    existing_codex = self.session.query(Codex).filter(
                        Codex.doc_parsed_name == metadata['doc_parsed_name']
                    ).first()
                    if existing_codex:
                        logger.info(f"[{codex_name}] Найден документ в БД по названию из файла")
            
            # 3. Если не нашли по метаданным, проверяем по имени кодекса (для обратной совместимости)
            # ВАЖНО: Если кодекс найден по имени, но путь к файлу отличается, это может быть другая часть кодекса
            # В таком случае нужно объединить данные, а не пропустить загрузку
            # НО: Нужно проверить метаданные, чтобы убедиться, что это действительно части одного кодекса
            if not existing_codex and codex_name:
                existing_codex = self.session.query(Codex).filter(
                    Codex.name == codex_name
                ).first()
                if existing_codex:
                    # Проверяем, отличается ли путь к файлу
                    if existing_codex.file_path and existing_codex.file_path != str(file_path):
                        # Это может быть другая часть кодекса, но нужно проверить метаданные
                        # Если есть метаданные в новом файле, проверяем совпадение
                        should_merge = True
                        if metadata:
                            # Если у существующего кодекса есть метаданные, проверяем совпадение
                            if existing_codex.doc_type and metadata.get('doc_type'):
                                if existing_codex.doc_type != metadata['doc_type']:
                                    # Разные типы документов - это разные кодексы!
                                    logger.warning(f"[{codex_name}] Найден кодекс по имени, но тип документа отличается (БД: {existing_codex.doc_type}, новый: {metadata['doc_type']})")
                                    logger.warning(f"[{codex_name}] Это РАЗНЫЕ кодексы, НЕ объединяем! Создаем новый документ.")
                                    existing_codex = None
                                    should_merge = False
                            elif existing_codex.doc_number and metadata.get('doc_number'):
                                if existing_codex.doc_number != metadata['doc_number']:
                                    # Разные номера документов - это разные кодексы!
                                    logger.warning(f"[{codex_name}] Найден кодекс по имени, но номер документа отличается (БД: {existing_codex.doc_number}, новый: {metadata['doc_number']})")
                                    logger.warning(f"[{codex_name}] Это РАЗНЫЕ кодексы, НЕ объединяем! Создаем новый документ.")
                                    existing_codex = None
                                    should_merge = False
                        
                        if should_merge:
                            # Это другая часть кодекса - нужно объединить данные
                            logger.info(f"[{codex_name}] Найден кодекс по имени, но путь к файлу отличается (БД: {existing_codex.file_path}, новый: {file_path})")
                            logger.info(f"[{codex_name}] Это другая часть кодекса, объединяем данные...")
                            # Используем существующий кодекс, но не пропускаем загрузку - обновим данные
                            # existing_codex уже установлен, продолжим обработку ниже
                    else:
                        logger.debug(f"[{codex_name}] Найден документ в БД по имени кодекса (тот же файл)")
            
            if existing_codex:
                # Проверяем дату модификации файла
                db_modified_date = existing_codex.file_modified_date
                
                # Определяем порядок приоритетов для сравнения (0 - самый высокий, 3 - самый низкий)
                priority_order = {'0': 0, '1': 1, '2': 2, '3': 3}
                # Обратная совместимость со старыми уровнями
                old_priority_map = {'0а': 1, '1а': 3}
                current_priority_str = existing_codex.priority_level
                if current_priority_str in old_priority_map:
                    current_priority_str = str(old_priority_map[current_priority_str])
                new_priority_str = priority_level
                if new_priority_str in old_priority_map:
                    new_priority_str = str(old_priority_map[new_priority_str])
                
                current_priority_value = priority_order.get(current_priority_str, 2)
                new_priority_value = priority_order.get(new_priority_str, 2)
                
                # ВАЖНО: Если путь к файлу отличается, это другая часть кодекса - НЕ пропускаем загрузку
                is_different_file = existing_codex.file_path and existing_codex.file_path != str(file_path)
                
                if db_modified_date and file_modified_date <= db_modified_date and not is_different_file:
                    # Файл не изменился (и это тот же файл), но можем обновить приоритет, если новый выше
                    if new_priority_value < current_priority_value:
                        logger.info(f"[{codex_name}] Файл не изменился, но обновляем приоритет: {existing_codex.priority_level} -> {new_priority_str}")
                        existing_codex.priority_level = new_priority_str
                        self.session.commit()
                        logger.info(f"[{codex_name}] ✓ Приоритет обновлен, используем данные из БД")
                        return (existing_codex, 'skipped')
                    else:
                        logger.info(f"[{codex_name}] Файл не изменился (БД: {db_modified_date}, файл: {file_modified_date}), пропускаем загрузку")
                        logger.info(f"[{codex_name}] ✓ Используем данные из БД (приоритет: {existing_codex.priority_level})")
                        # Возвращаем кортеж (codex, status) для отслеживания статистики
                        return (existing_codex, 'skipped')
                
                # Если это другой файл (часть кодекса), продолжаем загрузку для объединения данных
                if is_different_file:
                    logger.info(f"[{codex_name}] Обнаружена другая часть кодекса (файл: {file_path.name}), объединяем данные...")
                    # НЕ удаляем старые данные, а добавляем новые к существующим
                    codex = existing_codex
                    # Обновляем приоритет, если новый выше текущего
                    if new_priority_value < current_priority_value:
                        codex.priority_level = new_priority_str
                        logger.info(f"[{codex_name}] Приоритет обновлен: {existing_codex.priority_level} -> {new_priority_str}")
                    else:
                        logger.info(f"[{codex_name}] Приоритет сохранен: {codex.priority_level} (новый: {new_priority_str} ниже)")
                    # Обновляем краткое название и аббревиатуру, если они переданы
                    if short_name:
                        # Убеждаемся, что краткое название содержит "РФ" для российских кодексов
                        if short_name and not short_name.endswith(' РФ') and not short_name.endswith(' ЕАЭС'):
                            # Проверяем, является ли это российским кодексом
                            if 'российской федерации' in codex_name.lower() or 'рф' in codex_name.lower():
                                # Если краткое название не содержит "РФ", добавляем его
                                if abbreviation and short_name == abbreviation:
                                    codex.short_name = f"{short_name} РФ"
                                    logger.info(f"[{codex_name}] Краткое название обновлено: {short_name} -> {short_name} РФ")
                                else:
                                    codex.short_name = short_name
                            else:
                                codex.short_name = short_name
                        else:
                            codex.short_name = short_name
                    if abbreviation:
                        codex.abbreviation = abbreviation
                    # Обновляем путь к файлу (сохраняем оба пути через запятую или используем последний)
                    # Для простоты используем последний файл, но можно было бы хранить список
                    codex.file_path = str(file_path)
                    codex.file_modified_date = file_modified_date
                    update_status = 'updated'
                    # НЕ удаляем старые данные - добавляем новые к существующим
                    logger.info(f"[{codex_name}] Объединяем данные из файла {file_path.name} с существующими данными кодекса")
                    # Продолжаем обработку ниже для парсинга и добавления новых статей/глав/разделов
                else:
                    # Это тот же файл, но он обновлен
                    logger.info(f"[{codex_name}] Файл обновлен (БД: {db_modified_date}, файл: {file_modified_date}), обновляем кодекс...")
                    codex = existing_codex
                    # Обновляем приоритет, если новый выше текущего
                    if new_priority_value < current_priority_value:
                        codex.priority_level = new_priority_str
                        logger.info(f"[{codex_name}] Приоритет обновлен: {existing_codex.priority_level} -> {new_priority_str}")
                    else:
                        logger.info(f"[{codex_name}] Приоритет сохранен: {codex.priority_level} (новый: {new_priority_str} ниже)")
                    # Обновляем краткое название и аббревиатуру, если они переданы
                    if short_name:
                        # Убеждаемся, что краткое название содержит "РФ" для российских кодексов
                        if short_name and not short_name.endswith(' РФ') and not short_name.endswith(' ЕАЭС'):
                            # Проверяем, является ли это российским кодексом
                            if 'российской федерации' in codex_name.lower() or 'рф' in codex_name.lower():
                                # Если краткое название не содержит "РФ", добавляем его
                                if abbreviation and short_name == abbreviation:
                                    codex.short_name = f"{short_name} РФ"
                                    logger.info(f"[{codex_name}] Краткое название обновлено: {short_name} -> {short_name} РФ")
                                else:
                                    codex.short_name = short_name
                            else:
                                codex.short_name = short_name
                        else:
                            codex.short_name = short_name
                    if abbreviation:
                        codex.abbreviation = abbreviation
                    update_status = 'updated'
                    # Удаляем старые данные перед обновлением (только если это тот же файл)
                    logger.info(f"[{codex_name}] Удаление старых данных...")
                    articles_count = self.session.query(CodexArticle).filter_by(codex_id=codex.id).count()
                    chapters_count = self.session.query(CodexChapter).filter_by(codex_id=codex.id).count()
                    sections_count = self.session.query(CodexSection).filter_by(codex_id=codex.id).count()
                    
                    self.session.query(CodexArticle).filter_by(codex_id=codex.id).delete()
                    self.session.query(CodexChapter).filter_by(codex_id=codex.id).delete()
                    self.session.query(CodexSection).filter_by(codex_id=codex.id).delete()
                    logger.info(f"[{codex_name}] Удалено: {articles_count} статей, {chapters_count} глав, {sections_count} разделов")
            else:
                update_status = 'loaded'
                logger.info(f"[{codex_name}] Создание новой записи кодекса...")
                # Нормализуем уровень приоритета (конвертируем старые значения)
                normalized_priority = priority_level
                old_priority_map = {'0а': '1', '1а': '3'}
                if normalized_priority in old_priority_map:
                    normalized_priority = old_priority_map[normalized_priority]
                
                # Убеждаемся, что краткое название содержит "РФ" для российских кодексов
                final_short_name = short_name
                if short_name and not short_name.endswith(' РФ') and not short_name.endswith(' ЕАЭС'):
                    # Проверяем, является ли это российским кодексом
                    if 'российской федерации' in codex_name.lower() or 'рф' in codex_name.lower():
                        # Если краткое название не содержит "РФ", добавляем его
                        if abbreviation and short_name == abbreviation:
                            final_short_name = f"{short_name} РФ"
                            logger.info(f"[{codex_name}] Краткое название дополнено: {short_name} -> {final_short_name}")
                        # Если short_name уже содержит что-то кроме аббревиатуры, оставляем как есть
                        elif len(short_name) > len(abbreviation) if abbreviation else True:
                            final_short_name = short_name
                        else:
                            final_short_name = f"{short_name} РФ"
                            logger.info(f"[{codex_name}] Краткое название дополнено: {short_name} -> {final_short_name}")
                
                codex = Codex(
                    name=codex_name,
                    short_name=final_short_name,
                    abbreviation=abbreviation,
                    file_path=str(file_path),
                    file_modified_date=file_modified_date,
                    priority_level=normalized_priority
                )
                self.session.add(codex)
                self.session.flush()
            
            # Читаем и обрабатываем файл только если нужно обновить или загрузить
            
            # Если мы уже читали начало файла для парсинга метаданных, используем ту же кодировку
            # Иначе читаем весь файл
            if content_preview and used_encoding:
                logger.info(f"[{codex_name}] Чтение файла: {file_path.name}...")
                file_size = file_path.stat().st_size
                logger.info(f"[{codex_name}] Размер файла: {file_size / 1024 / 1024:.2f} MB")
                
                # Читаем весь файл в той же кодировке
                try:
                    with open(file_path, 'r', encoding=used_encoding) as f:
                        content = f.read()
                    # Удаляем boilerplate текст КонсультантПлюс
                    content = self._remove_consultant_plus_boilerplate(content)
                    logger.info(f"[{codex_name}] Файл прочитан в кодировке: {used_encoding}")
                except Exception as e:
                    logger.error(f"[{codex_name}] Ошибка при чтении файла в кодировке {used_encoding}: {e}")
                    return None
            else:
                # Если не читали начало файла, читаем весь файл
                logger.info(f"[{codex_name}] Чтение файла: {file_path.name}...")
                file_size = file_path.stat().st_size
                logger.info(f"[{codex_name}] Размер файла: {file_size / 1024 / 1024:.2f} MB")
                
                # Пробуем разные кодировки, начиная с Windows-1251
                encodings = ['windows-1251', 'utf-8', 'cp1251', 'latin-1']
                content = None
                used_encoding = None
                
                for encoding in encodings:
                    try:
                        with open(file_path, 'r', encoding=encoding) as f:
                            content = f.read()
                        # Удаляем boilerplate текст КонсультантПлюс
                        content = self._remove_consultant_plus_boilerplate(content)
                        used_encoding = encoding
                        logger.debug(f"[{codex_name}] Файл успешно прочитан в кодировке: {encoding}")
                        break
                    except UnicodeDecodeError:
                        continue
                    except Exception as e:
                        logger.warning(f"[{codex_name}] Ошибка при чтении в кодировке {encoding}: {e}")
                        continue
                
                if content is None:
                    logger.error(f"[{codex_name}] Не удалось прочитать файл ни в одной из кодировок: {encodings}")
                    return None
                
                if used_encoding:
                    logger.info(f"[{codex_name}] Файл прочитан в кодировке: {used_encoding}")
                
                # Парсим метаданные из всего файла (если еще не парсили)
                if not metadata:
                    metadata = self._parse_document_metadata(content)
            
            logger.info(f"[{codex_name}] Файл прочитан: {len(content)} символов")
            codex.full_text = content
            codex.file_modified_date = file_modified_date  # Обновляем дату модификации
            codex.file_path = str(file_path)  # Обновляем путь на случай, если он изменился
            
            # Обновляем метаданные документа (если еще не были установлены)
            if metadata:
                logger.info(f"[{codex_name}] Обновление метаданных документа...")
            if metadata:
                if metadata.get('doc_type'):
                    codex.doc_type = metadata['doc_type']
                    logger.info(f"[{codex_name}] Тип документа: {metadata['doc_type']}")
                if metadata.get('doc_number'):
                    codex.doc_number = metadata['doc_number']
                    logger.info(f"[{codex_name}] Номер документа: {metadata['doc_number']}")
                if metadata.get('doc_date'):
                    codex.doc_date = metadata['doc_date']
                    logger.info(f"[{codex_name}] Дата документа: {metadata['doc_date']}")
                if metadata.get('doc_parsed_name'):
                    codex.doc_parsed_name = metadata['doc_parsed_name']
                    logger.info(f"[{codex_name}] Название из файла: {metadata['doc_parsed_name'][:100]}...")
                if metadata.get('doc_authority'):
                    codex.doc_authority = metadata['doc_authority']
                    logger.info(f"[{codex_name}] Государственный орган: {metadata['doc_authority']}")
            
            # Парсим структуру кодекса
            logger.info(f"[{codex_name}] Парсинг структуры кодекса...")
            parse_result = self._parse_codex_structure(codex, content)
            
            if parse_result:
                sections_count, chapters_count, articles_count = parse_result
                logger.info(f"[{codex_name}] ✓ Парсинг завершен: {sections_count} разделов, {chapters_count} глав, {articles_count} статей")
            
            logger.info(f"[{codex_name}] Сохранение в БД...")
            self.session.commit()
            logger.info(f"[{codex_name}] ✓ Кодекс успешно загружен в БД (дата модификации: {file_modified_date})")
            return (codex, update_status)
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"[{codex_name}] ✗ Ошибка загрузки кодекса: {e}")
            import traceback
            logger.error(f"[{codex_name}] Трассировка ошибки:\n{traceback.format_exc()}")
            return None
    
    def _parse_codex_structure(self, codex: Codex, content: str):
        """Парсит структуру кодекса (разделы, главы, статьи)"""
        content_lower = content.lower()
        
        logger.info(f"[{codex.name}] Поиск разделов, глав и статей...")
        
        # Находим все разделы (с поддержкой многострочных названий)
        # Сначала находим позиции всех разделов, глав и статей для определения границ
        section_positions = []
        chapter_positions = []
        article_positions = []
        
        # Находим все разделы
        section_pattern = r'(?:Раздел|РАЗДЕЛ)\s+([IVX]+|[А-Я]+|\d+)\s*\.?\s*'
        for match in re.finditer(section_pattern, content, re.MULTILINE | re.IGNORECASE):
            section_positions.append(match.start())
        
        # Находим все главы
        chapter_pattern = r'(?:Глава|ГЛАВА)\s+(\d+(?:\.\d+)?)\s*\.?\s*'
        for match in re.finditer(chapter_pattern, content, re.MULTILINE | re.IGNORECASE):
            chapter_positions.append(match.start())
        
        # Находим все статьи
        article_pattern = r'Статья\s+(\d+(?:\.\d+)?(?:\.\d+)?)\s*\.?\s*'
        for match in re.finditer(article_pattern, content, re.MULTILINE | re.IGNORECASE):
            article_positions.append(match.start())
        
        # Объединяем все позиции для определения границ названий
        all_positions = sorted(set(section_positions + chapter_positions + article_positions))
        
        # Функция для извлечения многострочного названия
        def extract_multiline_title(start_pos, title_start_pos):
            """Извлекает название до следующей структуры (раздел/глава/статья)"""
            # Находим следующую позицию структуры после текущей
            next_pos = len(content)
            for pos in all_positions:
                if pos > start_pos:
                    next_pos = pos
                    break
            
            # Берем текст от начала названия до следующей структуры
            title_text = content[title_start_pos:next_pos]
            
            # Убираем лишние пробелы и переносы строк в начале и конце
            title_text = title_text.strip()
            
            # Удаляем пустые строки в начале и конце
            lines = title_text.split('\n')
            # Убираем пустые строки в начале
            while lines and not lines[0].strip():
                lines.pop(0)
            # Убираем пустые строки в конце
            while lines and not lines[-1].strip():
                lines.pop()
            
            # Объединяем строки, но сохраняем структуру (заменяем множественные переносы на один)
            title_text = '\n'.join(lines)
            title_text = re.sub(r'\n\s*\n+', ' ', title_text)  # Множественные переносы -> пробел
            title_text = re.sub(r'\s+', ' ', title_text)  # Множественные пробелы -> один пробел
            
            return title_text.strip()
        
        # Находим разделы с многострочными названиями
        section_matches = []
        for match in re.finditer(section_pattern, content, re.MULTILINE | re.IGNORECASE):
            section_num = match.group(1).strip()
            title_start = match.end()
            section_title = extract_multiline_title(match.start(), title_start)
            section_matches.append((match.start(), section_num, section_title))
        
        # Находим главы с многострочными названиями
        chapter_matches = []
        for match in re.finditer(chapter_pattern, content, re.MULTILINE | re.IGNORECASE):
            chapter_num = match.group(1).strip()
            title_start = match.end()
            chapter_title = extract_multiline_title(match.start(), title_start)
            chapter_matches.append((match.start(), chapter_num, chapter_title))
        
        # Находим статьи (название обычно в одной строке)
        article_matches = []
        article_pattern_full = r'Статья\s+(\d+(?:\.\d+)?(?:\.\d+)?)\s*\.?\s*([^\n\r]*)'
        for match in re.finditer(article_pattern_full, content, re.MULTILINE | re.IGNORECASE):
            article_num = match.group(1).strip()
            article_title = match.group(2).strip() if match.group(2) else ''
            article_title = re.sub(r'^[.\s]+|[.\s]+$', '', article_title)
            article_matches.append((match.start(), article_num, article_title))
        
        logger.info(f"[{codex.name}] Найдено: {len(section_matches)} разделов, {len(chapter_matches)} глав, {len(article_matches)} статей")
        
        # Создаем словари для быстрого поиска
        sections_dict = {}
        chapters_dict = {}
        
        # Обрабатываем разделы
        if section_matches:
            logger.info(f"[{codex.name}] Обработка разделов: 0/{len(section_matches)}...")
        for i, (start_pos, section_num, section_title) in enumerate(section_matches):
            section_title = re.sub(r'^[.\s]+|[.\s]+$', '', section_title)
            
            end_pos = section_matches[i + 1][0] if i + 1 < len(section_matches) else len(content)
            
            # Проверяем, существует ли уже раздел с таким номером (для объединения частей кодекса)
            existing_section = self.session.query(CodexSection).filter(
                and_(
                    CodexSection.codex_id == codex.id,
                    CodexSection.number == section_num
                )
            ).first()
            
            if existing_section:
                # Раздел уже существует - обновляем его или пропускаем (в зависимости от логики)
                # Для объединения частей кодекса обновляем контент, если он длиннее
                if len(content[start_pos:end_pos]) > len(existing_section.content or ''):
                    existing_section.content = content[start_pos:end_pos]
                    existing_section.title = section_title
                    logger.debug(f"[{codex.name}] Обновлен раздел {section_num}")
                section = existing_section
            else:
                # Создаем новый раздел
                section = CodexSection(
                    codex_id=codex.id,
                    number=section_num,
                    title=section_title,
                    content=content[start_pos:end_pos],
                    order_index=i
                )
                self.session.add(section)
            self.session.flush()
            sections_dict[start_pos] = section
            
            if (i + 1) % 10 == 0 or (i + 1) == len(section_matches):
                logger.info(f"[{codex.name}] Обработка разделов: {i + 1}/{len(section_matches)} ({((i + 1) / len(section_matches) * 100):.1f}%)")
        
        # Обрабатываем главы
        if chapter_matches:
            logger.info(f"[{codex.name}] Обработка глав: 0/{len(chapter_matches)}...")
        for i, (start_pos, chapter_num, chapter_title) in enumerate(chapter_matches):
            chapter_title = re.sub(r'^[.\s]+|[.\s]+$', '', chapter_title)
            
            end_pos = chapter_matches[i + 1][0] if i + 1 < len(chapter_matches) else len(content)
            
            # Определяем, к какому разделу относится глава
            section_id = None
            for section_pos, section in sorted(sections_dict.items()):
                if section_pos < start_pos:
                    section_id = section.id
                else:
                    break
            
            # Проверяем, существует ли уже глава с таким номером (для объединения частей кодекса)
            existing_chapter = self.session.query(CodexChapter).filter(
                and_(
                    CodexChapter.codex_id == codex.id,
                    CodexChapter.number == chapter_num,
                    CodexChapter.section_id == section_id
                )
            ).first()
            
            if existing_chapter:
                # Глава уже существует - обновляем ее или пропускаем
                if len(content[start_pos:end_pos]) > len(existing_chapter.content or ''):
                    existing_chapter.content = content[start_pos:end_pos]
                    existing_chapter.title = chapter_title
                    logger.debug(f"[{codex.name}] Обновлена глава {chapter_num}")
                chapter = existing_chapter
            else:
                # Создаем новую главу
                chapter = CodexChapter(
                    codex_id=codex.id,
                    section_id=section_id,
                    number=chapter_num,
                    title=chapter_title,
                    content=content[start_pos:end_pos],
                    order_index=i
                )
                self.session.add(chapter)
            self.session.flush()
            chapters_dict[start_pos] = chapter
            
            if (i + 1) % 20 == 0 or (i + 1) == len(chapter_matches):
                logger.info(f"[{codex.name}] Обработка глав: {i + 1}/{len(chapter_matches)} ({((i + 1) / len(chapter_matches) * 100):.1f}%)")
        
        # Обрабатываем статьи
        if article_matches:
            logger.info(f"[{codex.name}] Обработка статей: 0/{len(article_matches)}...")
        for i, (start_pos, article_num, article_title) in enumerate(article_matches):
            article_title = re.sub(r'^[.\s]+|[.\s]+$', '', article_title)
            
            end_pos = article_matches[i + 1][0] if i + 1 < len(article_matches) else len(content)
            
            article_content = content[start_pos:end_pos].strip()
            article_content = self._clean_article_content(article_content)
            
            # Определяем, к какой главе относится статья
            chapter_id = None
            chapter_obj = None
            for chapter_pos, chapter in sorted(chapters_dict.items()):
                if chapter_pos < start_pos:
                    chapter_id = chapter.id
                    chapter_obj = chapter
                else:
                    break
            
            # Определяем, к какому разделу относится статья
            section_id = None
            section_obj = None
            for section_pos, section in sorted(sections_dict.items()):
                if section_pos < start_pos:
                    section_id = section.id
                    section_obj = section
                else:
                    break
            
            # Формируем полную структуру для поиска
            # Получаем информацию о кодексе, разделе и главе
            codex_name = codex.name
            section_number = section_obj.number if section_obj else None
            section_title = section_obj.title if section_obj else None
            chapter_number = chapter_obj.number if chapter_obj else None
            chapter_title = chapter_obj.title if chapter_obj else None
            
            # Формируем полный путь структуры для поиска
            structure_parts = [codex_name]
            if section_number and section_title:
                structure_parts.append(f"Раздел {section_number}. {section_title}")
            if chapter_number and chapter_title:
                structure_parts.append(f"Глава {chapter_number}. {chapter_title}")
            structure_parts.append(f"Статья {article_num}")
            if article_title:
                structure_parts.append(article_title)
            full_structure_path = " > ".join(structure_parts)
            
            # Проверяем, существует ли уже статья с таким номером (для объединения частей кодекса)
            existing_article = self.session.query(CodexArticle).filter(
                and_(
                    CodexArticle.codex_id == codex.id,
                    CodexArticle.number == article_num
                )
            ).first()
            
            if existing_article:
                # Статья уже существует - обновляем ее или пропускаем
                # Для объединения частей кодекса обновляем контент, если он длиннее или отличается
                if len(article_content) > len(existing_article.content or ''):
                    existing_article.content = article_content
                    existing_article.title = article_title
                    existing_article.section_id = section_id
                    existing_article.chapter_id = chapter_id
                    existing_article.section_number = section_number
                    existing_article.section_title = section_title
                    existing_article.chapter_number = chapter_number
                    existing_article.chapter_title = chapter_title
                    existing_article.full_structure_path = full_structure_path
                    logger.debug(f"[{codex.name}] Обновлена статья {article_num}")
                article = existing_article
            else:
                # Создаем новую статью
                article = CodexArticle(
                    codex_id=codex.id,
                    priority_level=codex.priority_level,  # Наследуем уровень приоритета от кодекса
                    chapter_id=chapter_id,
                    section_id=section_id,
                    number=article_num,
                    title=article_title,
                    content=article_content,
                    order_index=i,
                    # Заполняем поля полной структуры
                    codex_name=codex_name,
                    section_number=section_number,
                    section_title=section_title,
                    chapter_number=chapter_number,
                    chapter_title=chapter_title,
                    part_number=None,  # Пока не парсим части
                    part_title=None,
                    paragraph_number=None,  # Пока не парсим параграфы
                    paragraph_title=None,
                    full_structure_path=full_structure_path
                )
                self.session.add(article)
            
            # Показываем прогресс каждые 50 статей или на последней
            if (i + 1) % 50 == 0 or (i + 1) == len(article_matches):
                progress = ((i + 1) / len(article_matches) * 100)
                logger.info(f"[{codex.name}] Обработка статей: {i + 1}/{len(article_matches)} ({progress:.1f}%)")
        
        self.session.flush()
        
        # Возвращаем статистику
        return (len(sections_dict), len(chapters_dict), len(article_matches))
    
    def _parse_metadata_with_llm(self, header_text: str) -> Optional[Dict[str, str]]:
        """
        Парсит метаданные документа через LLM
        
        Args:
            header_text: Первые 20 строк документа
            
        Returns:
            Словарь с метаданными или None при ошибке
        """
        if not self.legal_extractor:
            return None
        
        try:
            prompt = f"""Проанализируй начало юридического документа и извлеки его реквизиты.

Текст начала документа:
{header_text}

Извлеки следующие реквизиты документа:
1. doc_type - тип документа (например: "Федеральный закон", "Постановление", "Приказ", "Кодекс", "Конституция" и т.д.)
2. doc_parsed_name - полное название документа (без типа и реквизитов)
3. doc_number - номер документа (например: "123-ФЗ", "456", "N 789" и т.д.)
4. doc_date - дата документа (в формате как указано в документе, например: "01.01.2024", "1 января 2024 г." и т.д.)
5. doc_authority - государственный орган, принявший документ (например: "Государственная Дума РФ", "Правительство РФ", "Президент РФ" и т.д.)

ВАЖНО:
- Если реквизит не найден, укажи null для этого поля
- Название документа должно быть без типа документа и реквизитов (номера, даты)
- Тип документа должен быть стандартным (Федеральный закон, Постановление, Приказ, Кодекс и т.д.)
- Номер документа должен быть в том формате, как указан в документе
- Дата должна быть в том формате, как указана в документе
- Для законов и кодексов гос. орган обычно: "Государственная Дума РФ"
- Для постановлений: "Правительство РФ"
- Для приказов: соответствующий министерство или ведомство
- Если гос. орган не указан явно, но это закон или кодекс, укажи "Государственная Дума РФ"

Верни ТОЛЬКО валидный JSON в следующем формате:
{{
    "doc_type": "тип документа или null",
    "doc_parsed_name": "название документа или null",
    "doc_number": "номер документа или null",
    "doc_date": "дата документа или null",
    "doc_authority": "государственный орган или null"
}}

Ответ (только JSON, без дополнительного текста):"""

            response = self.legal_extractor.generate_text(prompt)
            
            if not response:
                return None
            
            # Извлекаем JSON из ответа (может быть обернут в markdown или текст)
            response_clean = response.strip()
            
            # Убираем markdown код блоки, если есть
            if response_clean.startswith('```'):
                # Находим начало JSON
                json_start = response_clean.find('{')
                json_end = response_clean.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    response_clean = response_clean[json_start:json_end]
            else:
                # Ищем JSON в тексте
                json_start = response_clean.find('{')
                json_end = response_clean.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    response_clean = response_clean[json_start:json_end]
            
            # Парсим JSON
            try:
                metadata = json.loads(response_clean)
                
                # Очищаем значения (убираем null, пустые строки)
                result = {}
                for key in ['doc_type', 'doc_parsed_name', 'doc_number', 'doc_date', 'doc_authority']:
                    value = metadata.get(key)
                    if value and value != 'null' and value != 'None' and str(value).strip():
                        result[key] = str(value).strip()
                
                # Автоматически устанавливаем гос. орган для законов и кодексов, если не указан
                if result.get('doc_type'):
                    doc_type_lower = result['doc_type'].lower()
                    if ('закон' in doc_type_lower or 'кодекс' in doc_type_lower) and not result.get('doc_authority'):
                        result['doc_authority'] = 'Государственная Дума РФ'
                        logger.info(f"Автоматически установлен гос. орган для {result['doc_type']}: Государственная Дума РФ")
                
                return result if result else None
                
            except json.JSONDecodeError as e:
                logger.warning(f"Ошибка парсинга JSON от LLM: {e}, ответ: {response_clean[:200]}")
                return None
                
        except Exception as e:
            logger.warning(f"Ошибка при LLM-парсинге метаданных: {e}")
            return None
    
    def _parse_document_metadata(self, content: str) -> Dict[str, str]:
        """
        Парсит метаданные документа из начала файла
        
        Сначала пытается использовать LLM для парсинга первых 20 строк,
        если LLM недоступен или не вернул результат, использует регулярные выражения.
        
        Извлекает:
        - Название документа (doc_parsed_name)
        - Тип документа (doc_type)
        - Номер документа (doc_number)
        - Дата документа (doc_date)
        
        Args:
            content: Содержимое файла
            
        Returns:
            Словарь с метаданными
        """
        metadata = {}
        
        if not content or len(content) < 50:
            return metadata
        
        # Пробуем использовать LLM для парсинга первых 20 строк
        if self.legal_extractor:
            try:
                # Берем первые 20 строк документа
                lines = content.split('\n')[:20]
                header_text = '\n'.join(lines)
                
                # Удаляем boilerplate текст КонсультантПлюс
                header_text = self._remove_consultant_plus_boilerplate(header_text)
                
                if len(header_text.strip()) > 50:
                    llm_metadata = self._parse_metadata_with_llm(header_text)
                    if llm_metadata:
                        logger.info(f"Метаданные извлечены через LLM: {list(llm_metadata.keys())}")
                        return llm_metadata
            except Exception as e:
                logger.warning(f"Ошибка при LLM-парсинге метаданных, используем fallback: {e}")
        
        # Fallback: используем старую логику с регулярными выражениями
        # Берем первые 3000 символов для парсинга метаданных
        header = content[:3000]
        
        try:
            # 1. Извлекаем название документа
            # Сначала проверяем наличие разделителей секций (как в Pascal коде)
            lines = header.split('\n')
            title_lines = []
            found_name_section = False
            found_type = False
            in_name_section = False
            
            # Разделители секций (как в Pascal коде)
            section_markers = {
                'название документа': 'name',
                'публикация документа': 'pub',
                'текст документа': 'text',
                'изменения в документе': 'add'
            }
            
            for i, line in enumerate(lines[:30]):  # Увеличено до 30 строк
                line_original = line
                line = line.strip()
                
                # Проверяем разделители секций
                line_lower = line.lower()
                for marker, section_type in section_markers.items():
                    if marker in line_lower:
                        if section_type == 'name':
                            in_name_section = True
                            found_name_section = True
                            title_lines = []  # Начинаем собирать название заново
                            continue
                        elif section_type in ['pub', 'text', 'add']:
                            in_name_section = False
                            break
                
                # Если мы в секции названия, собираем строки
                if in_name_section:
                    if line and not any(marker in line_lower for marker in section_markers.keys()):
                        # Пропускаем строки-разделители (типа "--------")
                        if not re.match(r'^[-=\s]+$', line):
                            # Пропускаем boilerplate текст КонсультантПлюс
                            if 'консультантплюс' not in line_lower and 'документ предоставлен' not in line_lower:
                                title_lines.append(line)
                    continue
                
                # Если не в секции названия, используем старую логику
                if not line:
                    # Пустые строки пропускаем, но не останавливаем сбор (если еще не начали)
                    if not title_lines:
                        continue
                    else:
                        # Если уже собрали строки, пустая строка может быть разделителем
                        break
                
                # Проверяем, есть ли тип документа в строке
                if re.search(r'^(Федеральный\s+закон|ФЗ|Постановление|Приказ|Распоряжение|Решение|Определение)', line, re.IGNORECASE):
                    found_type = True
                    # Если тип документа найден, название может быть в этой же строке или в следующей
                    # Пробуем извлечь название из той же строки
                    match = re.search(r'^(?:Федеральный\s+закон|ФЗ|Постановление|Приказ|Распоряжение|Решение|Определение)[:\s]+(.{20,300})', line, re.IGNORECASE)
                    if match:
                        potential_title = match.group(1).strip()
                        # Убираем реквизиты из конца более тщательно
                        potential_title = re.sub(r'\s+от\s+\d+.*$', '', potential_title, flags=re.IGNORECASE)
                        potential_title = re.sub(r'\s+№\s+[^\s]+.*$', '', potential_title, flags=re.IGNORECASE)
                        potential_title = re.sub(r'\s+\([^)]*\)\s*$', '', potential_title)  # Убираем скобки с номером
                        if len(potential_title) > 15:
                            title_lines.append(potential_title)
                            # Проверяем следующую строку, может быть продолжение
                            if i + 1 < len(lines):
                                next_line = lines[i + 1].strip()
                                if next_line and len(next_line) > 10 and not re.search(r'^\s*(от|№|дата|принят|утвержден)', next_line, re.IGNORECASE):
                                    # Следующая строка может быть продолжением названия
                                    continue
                            break
                    # Или название в следующей строке
                    continue
                
                # Останавливаемся на строках-разделителях
                if re.match(r'^[-=\s]{10,}$', line):
                    if title_lines:
                        break
                    continue
                
                # Останавливаемся на строках с реквизитами
                if re.search(r'^\s*(от|№|дата|принят|утвержден)', line, re.IGNORECASE):
                    if title_lines:
                        break
                    continue
                
                # Останавливаемся на структурных элементах
                if re.search(r'^\s*(раздел|глава|статья|часть|параграф)', line, re.IGNORECASE):
                    if title_lines:
                        break
                    continue
                
                # Проверяем, что строка не является датой или номером
                if re.search(r'^\d+[.\s/-]\d+', line):  # Дата в формате 01.01.2024
                    if title_lines:
                        break
                    continue
                if re.search(r'^№\s*\d+', line, re.IGNORECASE):  # Номер
                    if title_lines:
                        break
                    continue
                
                # Если тип документа уже найден, следующая непустая строка - это название
                if found_type:
                    if len(line) > 15:
                        title_lines.append(line)
                        # Может быть несколько строк названия
                        continue
                    else:
                        if title_lines:
                            break
                        continue
                
                # Если тип документа еще не найден, собираем строки (но только если они похожи на название)
                # Проверяем, что строка начинается с заглавной буквы и достаточно длинная
                # Пропускаем boilerplate текст КонсультантПлюс
                if re.match(r'^[А-ЯЁ]', line) and len(line) > 15:
                    if 'консультантплюс' not in line_lower and 'документ предоставлен' not in line_lower:
                        title_lines.append(line)
                elif title_lines:
                    # Если уже собрали строки, но текущая не подходит, останавливаемся
                    break
            
            if title_lines:
                # Объединяем строки названия
                title = ' '.join(title_lines)
                # Очищаем от лишних символов
                title = re.sub(r'\s+', ' ', title)
                title = title.strip()
                # Пропускаем boilerplate текст КонсультантПлюс
                if 'консультантплюс' in title.lower() or 'документ предоставлен' in title.lower():
                    title_lines = []  # Сбрасываем, чтобы не использовать boilerplate
                    title = None
                else:
                    # Убираем реквизиты из названия, если они попали (более тщательно)
                    title = re.sub(r'\s+от\s+\d+.*$', '', title, flags=re.IGNORECASE)
                    title = re.sub(r'\s+№\s+[^\s]+.*$', '', title, flags=re.IGNORECASE)
                    title = re.sub(r'\s+\([^)]*\)\s*$', '', title)  # Убираем скобки с номером в конце
                    title = re.sub(r'\s+г\.\s*$', '', title, flags=re.IGNORECASE)  # Убираем "г." в конце
                    # Убираем тип документа из начала, если он там есть
                    title = re.sub(r'^(?:Федеральный\s+закон|ФЗ|Постановление|Приказ|Распоряжение|Решение|Определение)[:\s]+', '', title, flags=re.IGNORECASE)
                    title = title.strip()
                    # Убираем лишние разделители в начале и конце
                    title = re.sub(r'^[:\s\-]+', '', title)
                    title = re.sub(r'[:\s\-]+$', '', title)
                    if len(title) > 10 and len(title) < 400:
                        metadata['doc_parsed_name'] = title
            
            # Если не нашли многострочное название, пробуем паттерны
            if 'doc_parsed_name' not in metadata:
                title_patterns = [
                    # Кодексы (улучшенный паттерн)
                    r'^([А-ЯЁ][А-ЯЁа-яё\s\-]{15,200}кодекс[^\n]{0,150})',
                    # Федеральные законы (улучшенные паттерны)
                    r'^(?:Федеральный\s+закон|ФЗ)[:\s]+([^\n]{20,300})(?=\s*\n\s*(?:от|№|Дата|Глава|Статья|РАЗДЕЛ|Раздел|Принят|Утвержден))',
                    r'^(Федеральный\s+закон\s+[^\n]{15,300})',
                    r'^(ФЗ\s+[^\n]{15,300})',
                    # Постановления, приказы и т.д. (улучшенные паттерны)
                    r'^(?:Постановление|Приказ|Распоряжение|Решение|Определение)[:\s]+([^\n]{20,300})(?=\s*\n\s*(?:от|№|Дата|Глава|Статья|РАЗДЕЛ|Раздел|Принят|Утвержден))',
                    r'^(Постановление\s+[^\n]{15,300})',
                    r'^(Приказ\s+[^\n]{15,300})',
                    r'^(Распоряжение\s+[^\n]{15,300})',
                    r'^(Решение\s+[^\n]{15,300})',
                    r'^(Определение\s+[^\n]{15,300})',
                    # Общие паттерны (улучшенные)
                    r'^(О\s+[^\n]{15,300})(?=\s*\n\s*(?:от|№|Дата|Глава|Статья|РАЗДЕЛ|Раздел|Принят|Утвержден))',
                    r'^(Об\s+[^\n]{15,300})(?=\s*\n\s*(?:от|№|Дата|Глава|Статья|РАЗДЕЛ|Раздел|Принят|Утвержден))',
                    # Длинные заголовки с заглавной буквы (улучшенный)
                    r'^([А-ЯЁ][А-ЯЁа-яё\s\-]{20,350})(?=\s*\n\s*(?:от|№|Дата|Глава|Статья|РАЗДЕЛ|Раздел|Принят|Утвержден|Публикация|Текст))',
                    # Паттерн для документов, начинающихся с "О внесении"
                    r'^(О\s+внесении\s+[^\n]{15,300})(?=\s*\n\s*(?:от|№|Дата|в|изменений))',
                    r'^(Об\s+утверждении\s+[^\n]{15,300})(?=\s*\n\s*(?:от|№|Дата))',
                ]
                
                for pattern in title_patterns:
                    match = re.search(pattern, header, re.MULTILINE | re.IGNORECASE | re.DOTALL)
                    if match:
                        title = match.group(1).strip()
                        # Пропускаем boilerplate текст КонсультантПлюс
                        if 'консультантплюс' in title.lower() or 'документ предоставлен' in title.lower():
                            continue
                        # Очищаем от лишних символов и переносов строк
                        title = re.sub(r'\s+', ' ', title)
                        title = re.sub(r'\n+', ' ', title)
                        # Убираем лишние пробелы
                        title = ' '.join(title.split())
                        # Убираем реквизиты из названия (более тщательно)
                        title = re.sub(r'\s+от\s+\d+.*$', '', title, flags=re.IGNORECASE)
                        title = re.sub(r'\s+№\s+[^\s]+.*$', '', title, flags=re.IGNORECASE)
                        title = re.sub(r'\s+\([^)]*\)\s*$', '', title)  # Убираем скобки с номером
                        title = re.sub(r'\s+г\.\s*$', '', title, flags=re.IGNORECASE)  # Убираем "г."
                        # Убираем тип документа из начала, если он там есть
                        title = re.sub(r'^(?:Федеральный\s+закон|ФЗ|Постановление|Приказ|Распоряжение|Решение|Определение)[:\s]+', '', title, flags=re.IGNORECASE)
                        title = title.strip()
                        # Убираем лишние разделители
                        title = re.sub(r'^[:\s\-]+', '', title)
                        title = re.sub(r'[:\s\-]+$', '', title)
                        if len(title) > 15 and len(title) < 400:
                            metadata['doc_parsed_name'] = title
                            break
            
            # 2. Извлекаем тип документа
            # Сначала проверяем первую строку
            first_line = header.split('\n')[0].strip() if header else ""
            
            doc_type_patterns = [
                (r'^(Федеральный\s+закон|ФЗ)', 'Федеральный закон'),
                (r'^\s*(Федеральный\s+закон|ФЗ)', 'Федеральный закон'),  # С пробелами в начале
                (r'(?:^|\n)\s*(Постановление)', 'Постановление'),
                (r'(?:^|\n)\s*(Приказ)', 'Приказ'),
                (r'(?:^|\n)\s*(Распоряжение)', 'Распоряжение'),
                (r'(?:^|\n)\s*(Решение)', 'Решение'),
                (r'(?:^|\n)\s*(Определение)', 'Определение'),
                (r'(?:^|\n)\s*([А-ЯЁ][А-ЯЁа-яё\s\-]+кодекс)', 'Кодекс'),
                (r'(?:^|\n)\s*(Исковое\s+заявление)', 'Исковое заявление'),
                (r'(?:^|\n)\s*(Отзыв)', 'Отзыв'),
                (r'(?:^|\n)\s*(Претензия)', 'Претензия'),
                (r'(?:^|\n)\s*(Жалоба)', 'Жалоба'),
            ]
            
            # Проверяем паттерны в заголовке
            for pattern, doc_type in doc_type_patterns:
                match = re.search(pattern, header, re.MULTILINE | re.IGNORECASE)
                if match:
                    metadata['doc_type'] = doc_type
                    break
            
            # Если не нашли, проверяем первую строку отдельно
            if 'doc_type' not in metadata:
                if re.search(r'^Федеральный\s+закон|^ФЗ', first_line, re.IGNORECASE):
                    metadata['doc_type'] = 'Федеральный закон'
                elif re.search(r'^Постановление', first_line, re.IGNORECASE):
                    metadata['doc_type'] = 'Постановление'
                elif re.search(r'^Приказ', first_line, re.IGNORECASE):
                    metadata['doc_type'] = 'Приказ'
                elif re.search(r'кодекс', first_line, re.IGNORECASE):
                    metadata['doc_type'] = 'Кодекс'
            
            # 3. Извлекаем номер документа (улучшенная логика на основе Delphi кода)
            # Сначала ищем номер после типа документа или в начале строки с реквизитами
            number_patterns = [
                # Номер после типа документа: "Федеральный закон № 123-ФЗ"
                r'(?:Федеральный\s+закон|ФЗ|Постановление|Приказ|Распоряжение|Решение|Определение)[^\n]*?№\s*([^\s\n,]+?)(?:\s+от|\s+дата|$|\s+г\.|\n|$)',
                # Номер в строке с реквизитами: "от 01.01.2024 № 123-ФЗ"
                r'(?:от|дата)[^\n]*?№\s*([^\s\n,]+?)(?:\s+от|\s+дата|$|\s+г\.|\n|$)',
                # Стандартный формат: № 123-ФЗ
                r'№\s*(\d+[-\s]?[А-ЯЁ]?[-\s]?[Фф]З)',  # № 123-ФЗ
                # Номер в скобках после названия: "О чем-то (123-ФЗ)"
                r'\(([А-ЯЁ]?\d+[-\s]?[А-ЯЁ]?[-\s]?[Фф]З?)\)',
                # Номер без дефиса: № 123
                r'№\s*(\d+)(?:\s+от|\s+дата|$|\s+г\.|\n|$)',
                # Номер в тексте: "номер 123-ФЗ"
                r'номер[:\s]+([^\s\n,]+)',
                # Номер без символа №: 123-ФЗ (только если есть дефис и ФЗ)
                r'(?<!№\s)(\d+[-\s]?[А-ЯЁ]?[-\s]?[Фф]З)(?:\s+от|\s+дата|$|\s+г\.|\n|$)',
            ]
            
            for pattern in number_patterns:
                match = re.search(pattern, header, re.IGNORECASE | re.MULTILINE)
                if match:
                    number = match.group(1).strip()
                    # Проверяем, что это не номер судебного участка, дела, страницы и т.д.
                    exclude_patterns = [
                        r'участка',
                        r'дела',
                        r'страницы',
                        r'стр\.',
                        r'страниц',
                        r'пункт',
                        r'статья',
                        r'глава',
                        r'раздел',
                    ]
                    is_excluded = False
                    for excl_pattern in exclude_patterns:
                        if re.search(excl_pattern, number, re.IGNORECASE):
                            is_excluded = True
                            break
                    
                    if not is_excluded:
                        # Очищаем номер от пробелов, но сохраняем дефисы и буквы
                        number = re.sub(r'\s+', '', number)
                        # Проверяем, что номер не слишком короткий (минимум 1 символ) и не слишком длинный
                        if len(number) > 0 and len(number) < 50:
                            # Проверяем, что номер содержит хотя бы одну цифру
                            if re.search(r'\d', number):
                                metadata['doc_number'] = number
                                break
            
            # 4. Извлекаем дату документа (улучшенная логика на основе Delphi кода)
            # Приоритет: дата после "от" или "дата", затем дата с "г.", затем дата в строке с реквизитами
            date_patterns = [
                # Формат: "от 01.01.2024" или "дата: 01.01.2024" (приоритетный формат)
                r'(?:^|\n)\s*(?:от|дата)[:\s]+([0-9]{1,2}[.\s/-][0-9]{1,2}[.\s/-][0-9]{2,4})',
                r'(?:^|\n)\s*(?:от|дата)[:\s]+(\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4})',
                r'(?:^|\n)\s*(?:от|дата)[:\s]+(\d{1,2}\s+(?:янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[а-я]*\s+\d{4})',
                # Формат: "01.01.2024 г." или "1 января 2024 г." (с "г.")
                r'([0-9]{1,2}[.\s/-][0-9]{1,2}[.\s/-][0-9]{2,4})(?:\s+г\.)',
                r'(\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4})(?:\s+г\.)',
                r'(\d{1,2}\s+(?:янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[а-я]*\s+\d{4})(?:\s+г\.)',
                # Формат: "принят 01.01.2024" или "утвержден 1 января 2024"
                r'(?:принят|утвержден)[^\n]*?([0-9]{1,2}[.\s/-][0-9]{1,2}[.\s/-][0-9]{2,4})',
                r'(?:принят|утвержден)[^\n]*?(\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4})',
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, header, re.IGNORECASE | re.MULTILINE)
                if match:
                    date = match.group(1).strip()
                    # Очищаем дату от лишних пробелов
                    date = re.sub(r'\s+', ' ', date)
                    # Проверяем, что это действительно дата (содержит цифры)
                    # И что дата не является частью номера документа
                    if re.search(r'\d', date) and len(date) > 5 and len(date) < 50:
                        # Проверяем, что это не номер (например, "123-ФЗ")
                        if not re.search(r'^\d+[-\s]?[А-ЯЁ]?[-\s]?[Фф]З?$', date, re.IGNORECASE):
                            metadata['doc_date'] = date
                            break
            
            # 5. Извлекаем государственный орган (если указан явно)
            authority_patterns = [
                r'принят[аы]?\s+(?:Государственной\s+Думой|Госдумой|ГД)',
                r'принят[аы]?\s+(?:Правительством|Правительством\s+РФ)',
                r'принят[аы]?\s+(?:Президентом|Президентом\s+РФ)',
                r'утвержден[аы]?\s+(?:Правительством|Правительством\s+РФ)',
                r'утвержден[аы]?\s+(?:Президентом|Президентом\s+РФ)',
                r'Государственная\s+Дума',
                r'Правительство\s+РФ',
                r'Президент\s+РФ',
            ]
            
            for pattern in authority_patterns:
                match = re.search(pattern, header, re.IGNORECASE | re.MULTILINE)
                if match:
                    authority_text = match.group(0).strip()
                    # Нормализуем название
                    if 'дум' in authority_text.lower() or 'гд' in authority_text.lower():
                        metadata['doc_authority'] = 'Государственная Дума РФ'
                    elif 'правительств' in authority_text.lower():
                        metadata['doc_authority'] = 'Правительство РФ'
                    elif 'президент' in authority_text.lower():
                        metadata['doc_authority'] = 'Президент РФ'
                    break
            
            # Автоматически устанавливаем гос. орган для законов и кодексов, если не указан
            if metadata.get('doc_type') and not metadata.get('doc_authority'):
                doc_type_lower = metadata['doc_type'].lower()
                if 'закон' in doc_type_lower or 'кодекс' in doc_type_lower:
                    metadata['doc_authority'] = 'Государственная Дума РФ'
                    logger.debug(f"Автоматически установлен гос. орган для {metadata['doc_type']}: Государственная Дума РФ")
                        
        except Exception as e:
            logger.warning(f"Ошибка при парсинге метаданных документа: {e}")
        
        return metadata
    
    def _remove_consultant_plus_boilerplate(self, content: str) -> str:
        """
        Удаляет boilerplate текст КонсультантПлюс из начала файла
        
        Удаляет блоки вида:
        ============================
        Документ предоставлен КонсультантПлюс
        www.consultant.ru
        ============================
        
        Args:
            content: Содержимое файла
            
        Returns:
            Очищенное содержимое
        """
        if not content:
            return content
        
        # Паттерн для поиска и удаления boilerplate блока
        # Ищем блоки с разделителями "====" и текстом "Документ предоставлен КонсультантПлюс"
        patterns = [
            # Полный блок с разделителями
            r'={10,}\s*\n\s*Документ предоставлен КонсультантПлюс\s*\n\s*www\.consultant\.ru\s*\n\s*={10,}\s*\n?',
            # Вариант без www.consultant.ru
            r'={10,}\s*\n\s*Документ предоставлен КонсультантПлюс\s*\n\s*={10,}\s*\n?',
            # Вариант с другими разделителями
            r'-{10,}\s*\n\s*Документ предоставлен КонсультантПлюс\s*\n\s*www\.consultant\.ru\s*\n\s*-{10,}\s*\n?',
            # Просто строка "Документ предоставлен КонсультантПлюс" в начале файла
            r'^\s*Документ предоставлен КонсультантПлюс\s*\n\s*www\.consultant\.ru\s*\n?',
        ]
        
        cleaned_content = content
        for pattern in patterns:
            cleaned_content = re.sub(pattern, '', cleaned_content, flags=re.MULTILINE | re.IGNORECASE)
        
        # Удаляем множественные пустые строки в начале
        cleaned_content = re.sub(r'^\s*\n+', '', cleaned_content)
        
        return cleaned_content
    
    def _clean_article_content(self, content: str) -> str:
        """Очищает содержимое статьи от лишних символов"""
        # Удаляем множественные пробелы
        content = re.sub(r'\s+', ' ', content)
        # Удаляем пробелы в начале и конце строк
        content = content.strip()
        return content
    
    def load_all_codexes(self, codex_dir: Optional[Path] = None):
        """Загружает все кодексы из указанной директории"""
        if codex_dir is None:
            codex_dir = self.knowledge_base_path / 'акты' / 'кодексы'
        
        if not codex_dir.exists():
            logger.warning(f"Директория кодексов не найдена: {codex_dir}")
            return
        
        logger.info("=" * 80)
        logger.info("НАЧАЛО ЗАГРУЗКИ ДОКУМЕНТОВ В БД")
        logger.info("=" * 80)
        logger.info(f"Директория: {codex_dir}")
        
        # Статистика загрузки
        stats = {
            'total': 0,
            'loaded': 0,      # Загружено впервые
            'updated': 0,      # Обновлено (файл изменился)
            'skipped': 0,     # Пропущено (файл не изменился)
            'failed': 0       # Ошибки загрузки
        }
        
        # Маппинг файлов к кодексам
        # Ключи - варианты поиска в имени файла (в нижнем регистре)
        codex_mapping = {
            # Уголовно-процессуальный кодекс
            'упк': {
                'name': 'Уголовно-процессуальный кодекс Российской Федерации',
                'short_name': 'УПК РФ',
                'abbreviation': 'УПК',
                'keywords': ['уголовно-процессуальный', 'упк']
            },
            # Гражданский процессуальный кодекс
            'гпк': {
                'name': 'Гражданский процессуальный кодекс Российской Федерации',
                'short_name': 'ГПК РФ',
                'abbreviation': 'ГПК',
                'keywords': ['гражданский процессуальный', 'гпк']
            },
            # Арбитражный процессуальный кодекс
            'апк': {
                'name': 'Арбитражный процессуальный кодекс Российской Федерации',
                'short_name': 'АПК РФ',
                'abbreviation': 'АПК',
                'keywords': ['арбитражный процессуальный', 'апк']
            },
            # Уголовный кодекс
            'ук': {
                'name': 'Уголовный кодекс Российской Федерации',
                'short_name': 'УК РФ',
                'abbreviation': 'УК',
                'keywords': ['уголовный кодекс', 'ук', 'уголовный кодекс российской федерации']
            },
            # Гражданский кодекс (части)
            'гк': {
                'name': 'Гражданский кодекс Российской Федерации',
                'short_name': 'ГК РФ',
                'abbreviation': 'ГК',
                'keywords': ['гражданский кодекс', 'гк', 'гражданский кодекс российской федерации']
            },
            # Трудовой кодекс
            'тк': {
                'name': 'Трудовой кодекс Российской Федерации',
                'short_name': 'ТК РФ',
                'abbreviation': 'ТК',
                'keywords': ['трудовой кодекс', 'тк', 'трудовой кодекс российской федерации']
            },
            # Налоговый кодекс (части)
            'нк': {
                'name': 'Налоговый кодекс Российской Федерации',
                'short_name': 'НК РФ',
                'abbreviation': 'НК',
                'keywords': ['налоговый кодекс', 'нк', 'налоговый кодекс российской федерации']
            },
            # КоАП
            'коап': {
                'name': 'Кодекс Российской Федерации об административных правонарушениях',
                'short_name': 'КоАП РФ',
                'abbreviation': 'КоАП',
                'keywords': ['кодекс об административных правонарушениях', 'коап', 'административных правонарушениях']
            },
            # КАС
            'кас': {
                'name': 'Кодекс административного судопроизводства Российской Федерации',
                'short_name': 'КАС РФ',
                'abbreviation': 'КАС',
                'keywords': ['кодекс административного судопроизводства', 'кас', 'административного судопроизводства']
            },
            # Бюджетный кодекс
            'бк': {
                'name': 'Бюджетный кодекс Российской Федерации',
                'short_name': 'БК РФ',
                'abbreviation': 'БК',
                'keywords': ['бюджетный кодекс', 'бк', 'бюджетный кодекс российской федерации']
            },
            # Водный кодекс
            'водный': {
                'name': 'Водный кодекс Российской Федерации',
                'short_name': 'ВК РФ',
                'abbreviation': 'ВК',
                'keywords': ['водный кодекс', 'водный кодекс российской федерации']
            },
            # Воздушный кодекс
            'воздушный': {
                'name': 'Воздушный кодекс Российской Федерации',
                'short_name': 'ВзК РФ',
                'abbreviation': 'ВзК',
                'keywords': ['воздушный кодекс', 'воздушный кодекс российской федерации']
            },
            # Градостроительный кодекс
            'градостроительный': {
                'name': 'Градостроительный кодекс Российской Федерации',
                'short_name': 'ГрК РФ',
                'abbreviation': 'ГрК',
                'keywords': ['градостроительный кодекс', 'градостроительный кодекс российской федерации']
            },
            # Жилищный кодекс
            'жилищный': {
                'name': 'Жилищный кодекс Российской Федерации',
                'short_name': 'ЖК РФ',
                'abbreviation': 'ЖК',
                'keywords': ['жилищный кодекс', 'жк', 'жилищный кодекс российской федерации']
            },
            # Земельный кодекс
            'земельный': {
                'name': 'Земельный кодекс Российской Федерации',
                'short_name': 'ЗК РФ',
                'abbreviation': 'ЗК',
                'keywords': ['земельный кодекс', 'зк', 'земельный кодекс российской федерации']
            },
            # Кодекс внутреннего водного транспорта
            'внутреннего водного транспорта': {
                'name': 'Кодекс внутреннего водного транспорта Российской Федерации',
                'short_name': 'КВВТ РФ',
                'abbreviation': 'КВВТ',
                'keywords': ['кодекс внутреннего водного транспорта', 'внутреннего водного транспорта']
            },
            # Кодекс торгового мореплавания
            'торгового мореплавания': {
                'name': 'Кодекс торгового мореплавания Российской Федерации',
                'short_name': 'КТМ РФ',
                'abbreviation': 'КТМ',
                'keywords': ['кодекс торгового мореплавания', 'торгового мореплавания']
            },
            # Лесной кодекс
            'лесной': {
                'name': 'Лесной кодекс Российской Федерации',
                'short_name': 'ЛК РФ',
                'abbreviation': 'ЛК',
                'keywords': ['лесной кодекс', 'лк', 'лесной кодекс российской федерации']
            },
            # Семейный кодекс
            'семейный': {
                'name': 'Семейный кодекс Российской Федерации',
                'short_name': 'СК РФ',
                'abbreviation': 'СК',
                'keywords': ['семейный кодекс', 'ск', 'семейный кодекс российской федерации']
            },
            # Таможенный кодекс ЕАЭС
            'таможенный': {
                'name': 'Таможенный кодекс Евразийского экономического союза',
                'short_name': 'ТК ЕАЭС',
                'abbreviation': 'ТК ЕАЭС',
                'keywords': ['таможенный кодекс', 'таможенный кодекс евразийского', 'таможенный кодекс еаэс']
            },
            # Уголовно-исполнительный кодекс
            'уголовно-исполнительный': {
                'name': 'Уголовно-исполнительный кодекс Российской Федерации',
                'short_name': 'УИК РФ',
                'abbreviation': 'УИК',
                'keywords': ['уголовно-исполнительный кодекс', 'уик', 'уголовно-исполнительный кодекс российской федерации']
            },
        }
        # NOTE: Дополнительная проверка ключевых слов, чтобы сокращения (например, "ск") совпадали только по отдельным словам.
        def _keyword_matches_filename(file_name_lower: str, keyword: str) -> bool:
            if not keyword:
                return False
            normalized_keyword = keyword.lower().strip()
            if not normalized_keyword:
                return False
            if len(normalized_keyword) <= 3 and ' ' not in normalized_keyword and '-' not in normalized_keyword:
                pattern = rf'(?<![a-zа-я0-9]){re.escape(normalized_keyword)}(?![a-zа-я0-9])'
                return re.search(pattern, file_name_lower) is not None
            return normalized_keyword in file_name_lower
        
        # Определяем уровень приоритета по имени папки
        priority_level = self.get_priority_level_from_folder(codex_dir.name)
        logger.info(f"Определен уровень приоритета для папки '{codex_dir.name}': {priority_level} (0-самый высокий, 3-низкий)")
        
        # Ищем файлы кодексов
        codex_files = list(codex_dir.glob('*.txt'))
        total_files = len(codex_files)
        
        if total_files == 0:
            logger.warning(f"Текстовые файлы (.txt) не найдены в директории: {codex_dir}")
            return
        
        logger.info(f"Найдено текстовых файлов: {total_files}")
        logger.info("-" * 80)
        
        for idx, file_path in enumerate(codex_files, 1):
            stats['total'] += 1
            file_name_lower = file_path.name.lower()
            
            logger.info(f"\n[{idx}/{total_files}] Обработка файла: {file_path.name}")
            
            # Определяем кодекс по имени файла
            codex_info = None
            best_match = None
            best_match_length = 0
            
            # Сначала ищем по ключевым словам (более точное совпадение)
            for key, info in codex_mapping.items():
                keywords = info.get('keywords', [key])
                for keyword in keywords:
                    if _keyword_matches_filename(file_name_lower, keyword):
                        # Выбираем самое длинное совпадение для точности
                        if len(keyword) > best_match_length:
                            best_match = info
                            best_match_length = len(keyword)
            
            if best_match:
                codex_info = best_match
            else:
                # Если не нашли по ключевым словам, пробуем по коротким ключам
                for key, info in codex_mapping.items():
                    if _keyword_matches_filename(file_name_lower, key):
                        codex_info = info
                        break
            
            if codex_info:
                logger.info(f"[{idx}/{total_files}] Определен кодекс: {codex_info['name']}")
                result = self.load_codex_from_file(
                    file_path,
                    codex_info['name'],
                    codex_info['short_name'],
                    codex_info['abbreviation'],
                    priority_level=priority_level
                )
                if result:
                    # result может быть (codex, status) или просто codex (для обратной совместимости)
                    if isinstance(result, tuple):
                        codex, status = result
                        stats[status] += 1
                        if status == 'loaded':
                            logger.info(f"[{idx}/{total_files}] ✓ Загружен впервые: {codex_info['name']}")
                        elif status == 'updated':
                            logger.info(f"[{idx}/{total_files}] ✓ Обновлен: {codex_info['name']}")
                        elif status == 'skipped':
                            logger.info(f"[{idx}/{total_files}] ⊘ Пропущен (файл не изменился): {codex_info['name']}")
                    else:
                        # Старый формат (для обратной совместимости)
                        stats['loaded'] += 1
                        logger.info(f"[{idx}/{total_files}] ✓ Успешно загружен: {codex_info['name']}")
                else:
                    stats['failed'] += 1
                    logger.error(f"[{idx}/{total_files}] ✗ Ошибка загрузки: {codex_info['name']}")
            else:
                # Файл не найден в маппинге кодексов - используем парсинг метаданных из начала файла
                logger.info(f"[{idx}/{total_files}] Файл не найден в маппинге кодексов, используем парсинг метаданных...")
                try:
                    # Специальная обработка для Конституции РФ
                    # Если имя файла содержит "конституция", используем правильное название
                    # ВАЖНО: Проверяем, что это именно Конституция, а не другой кодекс
                    is_constitution = (
                        'конституция' in file_name_lower and 
                        ('рф' in file_name_lower or 'российской федерации' in file_name_lower) and
                        'конституционный суд' not in file_name_lower and 
                        'кс рф' not in file_name_lower and
                        'кодекс' not in file_name_lower and  # Исключаем другие кодексы
                        'административн' not in file_name_lower  # Исключаем КоАП
                    )
                    if is_constitution:
                        codex_name = 'Конституция Российской Федерации'
                        logger.info(f"[{idx}/{total_files}] Определено название по имени файла: {codex_name}")
                        # Загружаем документ с правильным названием
                        result = self.load_codex_from_file(
                            file_path,
                            codex_name,
                            short_name='Конституция РФ',
                            abbreviation='Конституция РФ',
                            priority_level=priority_level
                        )
                        if result:
                            if isinstance(result, tuple):
                                codex, status = result
                                stats[status] += 1
                                if status == 'loaded':
                                    logger.info(f"[{idx}/{total_files}] ✓ Загружен впервые: {codex_name}")
                                elif status == 'updated':
                                    logger.info(f"[{idx}/{total_files}] ✓ Обновлен: {codex_name}")
                                elif status == 'skipped':
                                    logger.info(f"[{idx}/{total_files}] ⊘ Пропущен (файл не изменился): {codex_name}")
                            else:
                                stats['loaded'] += 1
                                logger.info(f"[{idx}/{total_files}] ✓ Успешно загружен: {codex_name}")
                        else:
                            stats['failed'] += 1
                            logger.error(f"[{idx}/{total_files}] ✗ Ошибка загрузки: {codex_name}")
                        continue
                    
                    # Читаем начало файла для парсинга метаданных
                    encodings = ['windows-1251', 'utf-8', 'cp1251', 'latin-1']
                    content_preview = None
                    for encoding in encodings:
                        try:
                            with open(file_path, 'r', encoding=encoding) as f:
                                content_preview = f.read(2000)  # Читаем первые 2000 символов
                            # Удаляем boilerplate текст КонсультантПлюс из превью
                            content_preview = self._remove_consultant_plus_boilerplate(content_preview)
                            break
                        except (UnicodeDecodeError, Exception):
                            continue
                    
                    if content_preview:
                        # Парсим метаданные
                        metadata = self._parse_document_metadata(content_preview)
                        
                        # Определяем название документа
                        # НЕ используем doc_type как название (это тип, а не название)
                        doc_name = None
                        
                        # Проверяем, что название не является boilerplate текстом КонсультантПлюс
                        if metadata.get('doc_parsed_name'):
                            parsed_name = metadata['doc_parsed_name']
                            # Пропускаем boilerplate названия
                            if 'консультантплюс' not in parsed_name.lower() and 'документ предоставлен' not in parsed_name.lower():
                                doc_name = parsed_name
                                # Убираем тип документа из начала названия, если он там есть
                                doc_type = metadata.get('doc_type', '')
                                if doc_type and doc_name.startswith(doc_type):
                                    doc_name = doc_name[len(doc_type):].strip()
                                    # Убираем возможные разделители в начале
                                    doc_name = re.sub(r'^[:\s\-]+', '', doc_name)
                        
                        # 2. Если название не найдено, пробуем извлечь из начала файла
                        if not doc_name or len(doc_name) < 15:
                            # Ищем полное название после типа документа
                            lines = content_preview.split('\n')[:15]
                            for i, line in enumerate(lines):
                                line = line.strip()
                                if not line:
                                    continue
                                # Пропускаем строки с boilerplate текстом
                                if 'консультантплюс' in line.lower() or 'документ предоставлен' in line.lower():
                                    continue
                                # Пропускаем строки с типом документа
                                if re.search(r'^(Федеральный\s+закон|ФЗ|Постановление|Приказ)', line, re.IGNORECASE):
                                    # Следующая строка может быть названием
                                    if i + 1 < len(lines):
                                        next_line = lines[i + 1].strip()
                                        if next_line and len(next_line) > 15:
                                            # Проверяем, что это не реквизиты и не boilerplate
                                            if not re.search(r'^(от|№|дата|принят|утвержден)', next_line, re.IGNORECASE):
                                                if 'консультантплюс' not in next_line.lower() and 'документ предоставлен' not in next_line.lower():
                                                    doc_name = next_line
                                                    break
                                    # Или название может быть в той же строке после типа
                                    match = re.search(r'^(?:Федеральный\s+закон|ФЗ|Постановление|Приказ)[:\s]+(.{20,300})', line, re.IGNORECASE)
                                    if match:
                                        potential_name = match.group(1).strip()
                                        # Пропускаем boilerplate
                                        if 'консультантплюс' not in potential_name.lower() and 'документ предоставлен' not in potential_name.lower():
                                            # Убираем реквизиты из конца
                                            potential_name = re.sub(r'\s+от\s+\d+.*$', '', potential_name, flags=re.IGNORECASE)
                                            potential_name = re.sub(r'\s+№\s+[^\s]+.*$', '', potential_name, flags=re.IGNORECASE)
                                            if len(potential_name) > 15:
                                                doc_name = potential_name
                                                break
                        
                        # 3. Если название все еще не найдено, используем имя файла (без расширения)
                        if not doc_name or len(doc_name) < 10:
                            doc_name = file_path.stem
                            # Очищаем имя файла от лишнего
                            doc_name = re.sub(r'\(ред\.\s+от.*?\)', '', doc_name, flags=re.IGNORECASE)
                            doc_name = re.sub(r'\s+', ' ', doc_name).strip()
                        
                        codex_name = doc_name
                        
                        logger.info(f"[{idx}/{total_files}] Определено название из метаданных: {codex_name[:100]}")
                        
                        # Загружаем документ с названием из метаданных
                        result = self.load_codex_from_file(
                            file_path,
                            codex_name,
                            short_name=None,
                            abbreviation=None,
                            priority_level=priority_level
                        )
                        
                        if result:
                            if isinstance(result, tuple):
                                codex, status = result
                                stats[status] += 1
                                if status == 'loaded':
                                    logger.info(f"[{idx}/{total_files}] ✓ Загружен впервые: {codex_name[:100]}")
                                elif status == 'updated':
                                    logger.info(f"[{idx}/{total_files}] ✓ Обновлен: {codex_name[:100]}")
                                elif status == 'skipped':
                                    logger.info(f"[{idx}/{total_files}] ⊘ Пропущен (файл не изменился): {codex_name[:100]}")
                            else:
                                stats['loaded'] += 1
                                logger.info(f"[{idx}/{total_files}] ✓ Успешно загружен: {codex_name[:100]}")
                        else:
                            stats['failed'] += 1
                            logger.error(f"[{idx}/{total_files}] ✗ Ошибка загрузки: {codex_name[:100]}")
                    else:
                        stats['failed'] += 1
                        logger.error(f"[{idx}/{total_files}] ✗ Не удалось прочитать файл для парсинга метаданных: {file_path.name}")
                except Exception as e:
                    stats['failed'] += 1
                    logger.error(f"[{idx}/{total_files}] ✗ Ошибка при обработке файла {file_path.name}: {e}")
                    import traceback
                    logger.debug(f"Трассировка ошибки:\n{traceback.format_exc()}")
            
            logger.info("-" * 80)
        
        self.session.commit()
        
        logger.info("=" * 80)
        logger.info("ЗАГРУЗКА ДОКУМЕНТОВ ЗАВЕРШЕНА")
        logger.info("=" * 80)
        logger.info(f"Всего файлов: {stats['total']}")
        logger.info(f"Загружено впервые: {stats['loaded']}")
        logger.info(f"Обновлено: {stats['updated']}")
        logger.info(f"Пропущено (не изменились): {stats['skipped']}")
        logger.info(f"Ошибок: {stats['failed']}")
        logger.info("=" * 80)
    
    def import_from_folders_with_levels(self, base_dir: Path):
        """
        Импортирует кодексы из папок с уровнями приоритета
        
        Структура папок:
        - base_dir/
          - уровень 0/ (или level 0, 0) - самый высокий приоритет
          - уровень 1/ (или level 1, 1) - высокий приоритет
          - уровень 2/ (или level 2, 2) - средний приоритет (по умолчанию)
          - уровень 3/ (или level 3, 3) - низкий приоритет
        
        Args:
            base_dir: Базовая директория с папками уровней
        """
        if not base_dir.exists():
            logger.warning(f"Базовая директория не найдена: {base_dir}")
            return
        
        logger.info("=" * 80)
        logger.info("НАЧАЛО ИМПОРТА ДОКУМЕНТОВ ИЗ ВСЕХ ПАПОК")
        logger.info("=" * 80)
        logger.info(f"Базовая директория: {base_dir}")
        logger.info("Обрабатываются ВСЕ папки в базовой директории")
        
        # Ищем все подпапки (обрабатываем ВСЕ папки, не только с уровнями)
        folders = [d for d in base_dir.iterdir() if d.is_dir()]
        
        if not folders:
            logger.warning(f"Папки не найдены в: {base_dir}")
            logger.info("Ожидаемая структура папок:")
            logger.info("  - уровень 0/ (или level 0, 0) - самый высокий приоритет")
            logger.info("  - уровень 1/ (или level 1, 1) - высокий приоритет")
            logger.info("  - уровень 2/ (или level 2, 2) - средний приоритет (по умолчанию)")
            logger.info("  - уровень 3/ (или level 3, 3) - низкий приоритет")
            logger.info("  - любые другие папки будут обработаны с уровнем приоритета 2 (по умолчанию)")
            return
        
        logger.info(f"Найдено папок: {len(folders)}")
        logger.info("Список найденных папок:")
        for folder in folders:
            logger.info(f"  - {folder.name}")
        
        # Сортируем папки по уровню приоритета (0, 1, 2, 3)
        priority_order = {'0': 0, '1': 1, '2': 2, '3': 3}
        
        folders_with_priority = []
        for folder in folders:
            priority = self.get_priority_level_from_folder(folder.name)
            folders_with_priority.append((priority_order.get(priority, 2), priority, folder))
            logger.info(f"  {folder.name} -> уровень приоритета: {priority}")
        
        folders_with_priority.sort(key=lambda x: x[0])
        
        logger.info("")
        logger.info("Порядок обработки папок (по приоритету, от высшего к низшему):")
        for idx, (order, priority, folder) in enumerate(folders_with_priority, 1):
            logger.info(f"  {idx}. {folder.name} (уровень: {priority}, приоритет: {order})")
        
        logger.info("")
        logger.info("ВАЖНО: Кодексы не будут повторно импортированы, если:")
        logger.info("  - Файл уже загружен в БД (проверка по имени и пути)")
        logger.info("  - Файл не изменился (проверка по дате модификации)")
        logger.info("  - Приоритет будет обновлен только если новый уровень выше текущего")
        logger.info("")
        
        # Импортируем из каждой папки
        total_processed = 0
        for order, priority, folder in folders_with_priority:
            logger.info("")
            logger.info("-" * 80)
            logger.info(f"[{total_processed + 1}/{len(folders_with_priority)}] Обработка папки: {folder.name} (уровень приоритета: {priority})")
            logger.info("-" * 80)
            try:
                self.load_all_codexes(folder)
                total_processed += 1
                logger.info(f"✓ Папка '{folder.name}' обработана успешно")
            except Exception as e:
                logger.error(f"✗ Ошибка при обработке папки '{folder.name}': {e}")
                import traceback
                logger.error(f"Трассировка ошибки:\n{traceback.format_exc()}")
                # Продолжаем обработку остальных папок
                continue
        
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"ИМПОРТ ДОКУМЕНТОВ ИЗ ВСЕХ ПАПОК ЗАВЕРШЕН")
        logger.info(f"Обработано папок: {total_processed}/{len(folders_with_priority)}")
        logger.info("=" * 80)
    
    def close(self):
        """Закрывает сессию"""
        self.session.close()

