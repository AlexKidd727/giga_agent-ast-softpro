"""
Сервис для работы с кодексами из базы данных
Загружает кодексы в память при старте и предоставляет быстрый доступ
"""

from typing import Dict, List, Optional, Tuple
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from giga_agent.agents.lawyer_agent.utils.codex_models import (
    Codex, CodexSection, CodexChapter, CodexArticle,
    get_session, create_engine_instance
)
from sqlalchemy import func, case
import logging
import re
from giga_agent.agents.lawyer_agent.utils.legal_terms import (
    rank_and_filter_query, clean_query, get_priority_keywords,
    get_word_info, PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW
)

logger = logging.getLogger(__name__)

# Маппинг всех вариантов написания кодексов к полным названиям из БД
# Используется для нормализации названий перед поиском в БД
CODEX_NAME_NORMALIZATION = {
    # Уголовный кодекс - все падежи и варианты
    'ук': 'Уголовный кодекс Российской Федерации',
    'ук рф': 'Уголовный кодекс Российской Федерации',
    'уголовный кодекс': 'Уголовный кодекс Российской Федерации',
    'уголовного кодекса': 'Уголовный кодекс Российской Федерации',  # Родительный падеж
    'уголовному кодексу': 'Уголовный кодекс Российской Федерации',  # Дательный падеж
    'уголовным кодексом': 'Уголовный кодекс Российской Федерации',  # Творительный падеж
    'уголовном кодексе': 'Уголовный кодекс Российской Федерации',  # Предложный падеж
    'уголовный кодекс рф': 'Уголовный кодекс Российской Федерации',
    'уголовного кодекса рф': 'Уголовный кодекс Российской Федерации',
    'уголовному кодексу рф': 'Уголовный кодекс Российской Федерации',
    'уголовным кодексом рф': 'Уголовный кодекс Российской Федерации',
    'уголовном кодексе рф': 'Уголовный кодекс Российской Федерации',
    'уголовный кодекс российской федерации': 'Уголовный кодекс Российской Федерации',
    'уголовного кодекса российской федерации': 'Уголовный кодекс Российской Федерации',
    
    # Уголовно-процессуальный кодекс - все падежи и варианты
    'упк': 'Уголовно-процессуальный кодекс Российской Федерации',
    'упк рф': 'Уголовно-процессуальный кодекс Российской Федерации',
    'уголовно-процессуальный кодекс': 'Уголовно-процессуальный кодекс Российской Федерации',
    'уголовно-процессуального кодекса': 'Уголовно-процессуальный кодекс Российской Федерации',
    'уголовно-процессуальному кодексу': 'Уголовно-процессуальный кодекс Российской Федерации',
    'уголовно-процессуальным кодексом': 'Уголовно-процессуальный кодекс Российской Федерации',
    'уголовно-процессуальном кодексе': 'Уголовно-процессуальный кодекс Российской Федерации',
    'уголовно-процессуальный кодекс рф': 'Уголовно-процессуальный кодекс Российской Федерации',
    'уголовно-процессуального кодекса рф': 'Уголовно-процессуальный кодекс Российской Федерации',
    'уголовно-процессуальный кодекс российской федерации': 'Уголовно-процессуальный кодекс Российской Федерации',
    
    # Гражданский кодекс - все падежи и варианты
    'гк': 'Гражданский кодекс Российской Федерации',
    'гк рф': 'Гражданский кодекс Российской Федерации',
    'гражданский кодекс': 'Гражданский кодекс Российской Федерации',
    'гражданского кодекса': 'Гражданский кодекс Российской Федерации',
    'гражданскому кодексу': 'Гражданский кодекс Российской Федерации',
    'гражданским кодексом': 'Гражданский кодекс Российской Федерации',
    'гражданском кодексе': 'Гражданский кодекс Российской Федерации',
    'гражданский кодекс рф': 'Гражданский кодекс Российской Федерации',
    'гражданского кодекса рф': 'Гражданский кодекс Российской Федерации',
    'гражданский кодекс российской федерации': 'Гражданский кодекс Российской Федерации',
    
    # Гражданский процессуальный кодекс - все падежи и варианты
    'гпк': 'Гражданский процессуальный кодекс Российской Федерации',
    'гпк рф': 'Гражданский процессуальный кодекс Российской Федерации',
    'гражданский процессуальный кодекс': 'Гражданский процессуальный кодекс Российской Федерации',
    'гражданского процессуального кодекса': 'Гражданский процессуальный кодекс Российской Федерации',
    'гражданскому процессуальному кодексу': 'Гражданский процессуальный кодекс Российской Федерации',
    'гражданским процессуальным кодексом': 'Гражданский процессуальный кодекс Российской Федерации',
    'гражданском процессуальном кодексе': 'Гражданский процессуальный кодекс Российской Федерации',
    'гражданский процессуальный кодекс рф': 'Гражданский процессуальный кодекс Российской Федерации',
    'гражданского процессуального кодекса рф': 'Гражданский процессуальный кодекс Российской Федерации',
    'гражданский процессуальный кодекс российской федерации': 'Гражданский процессуальный кодекс Российской Федерации',
    
    # Арбитражный процессуальный кодекс - все падежи и варианты
    'апк': 'Арбитражный процессуальный кодекс Российской Федерации',
    'апк рф': 'Арбитражный процессуальный кодекс Российской Федерации',
    'арбитражный процессуальный кодекс': 'Арбитражный процессуальный кодекс Российской Федерации',
    'арбитражного процессуального кодекса': 'Арбитражный процессуальный кодекс Российской Федерации',
    'арбитражному процессуальному кодексу': 'Арбитражный процессуальный кодекс Российской Федерации',
    'арбитражным процессуальным кодексом': 'Арбитражный процессуальный кодекс Российской Федерации',
    'арбитражном процессуальном кодексе': 'Арбитражный процессуальный кодекс Российской Федерации',
    'арбитражный процессуальный кодекс рф': 'Арбитражный процессуальный кодекс Российской Федерации',
    'арбитражного процессуального кодекса рф': 'Арбитражный процессуальный кодекс Российской Федерации',
    'арбитражный процессуальный кодекс российской федерации': 'Арбитражный процессуальный кодекс Российской Федерации',
    
    # Кодекс административного судопроизводства
    'кас': 'Кодекс административного судопроизводства Российской Федерации',
    'кас рф': 'Кодекс административного судопроизводства Российской Федерации',
    'кодекс административного судопроизводства': 'Кодекс административного судопроизводства Российской Федерации',
    'кодекс административного судопроизводства рф': 'Кодекс административного судопроизводства Российской Федерации',
    'кодекс административного судопроизводства российской федерации': 'Кодекс административного судопроизводства Российской Федерации',
    
    # Кодекс об административных правонарушениях
    'коап': 'Кодекс Российской Федерации об административных правонарушениях',
    'коап рф': 'Кодекс Российской Федерации об административных правонарушениях',
    'кодекс об административных правонарушениях': 'Кодекс Российской Федерации об административных правонарушениях',
    'кодекс об административных правонарушениях рф': 'Кодекс Российской Федерации об административных правонарушениях',
    'кодекс об административных правонарушениях российской федерации': 'Кодекс Российской Федерации об административных правонарушениях',
    'кодекс российской федерации об административных правонарушениях': 'Кодекс Российской Федерации об административных правонарушениях',
    
    # Трудовой кодекс - все падежи и варианты
    'тк': 'Трудовой кодекс Российской Федерации',
    'тк рф': 'Трудовой кодекс Российской Федерации',
    'трудовой кодекс': 'Трудовой кодекс Российской Федерации',
    'трудового кодекса': 'Трудовой кодекс Российской Федерации',
    'трудовому кодексу': 'Трудовой кодекс Российской Федерации',
    'трудовым кодексом': 'Трудовой кодекс Российской Федерации',
    'трудовом кодексе': 'Трудовой кодекс Российской Федерации',
    'трудовой кодекс рф': 'Трудовой кодекс Российской Федерации',
    'трудового кодекса рф': 'Трудовой кодекс Российской Федерации',
    'трудовой кодекс российской федерации': 'Трудовой кодекс Российской Федерации',
    
    # Налоговый кодекс - все падежи и варианты
    'нк': 'Налоговый кодекс Российской Федерации',
    'нк рф': 'Налоговый кодекс Российской Федерации',
    'налоговый кодекс': 'Налоговый кодекс Российской Федерации',
    'налогового кодекса': 'Налоговый кодекс Российской Федерации',
    'налоговому кодексу': 'Налоговый кодекс Российской Федерации',
    'налоговым кодексом': 'Налоговый кодекс Российской Федерации',
    'налоговом кодексе': 'Налоговый кодекс Российской Федерации',
    'налоговый кодекс рф': 'Налоговый кодекс Российской Федерации',
    'налогового кодекса рф': 'Налоговый кодекс Российской Федерации',
    'налоговый кодекс российской федерации': 'Налоговый кодекс Российской Федерации',
    
    # Семейный кодекс
    'ск': 'Семейный кодекс Российской Федерации',
    'ск рф': 'Семейный кодекс Российской Федерации',
    'семейный кодекс': 'Семейный кодекс Российской Федерации',
    'семейный кодекс рф': 'Семейный кодекс Российской Федерации',
    'семейный кодекс российской федерации': 'Семейный кодекс Российской Федерации',
    
    # Жилищный кодекс
    'жк': 'Жилищный кодекс Российской Федерации',
    'жк рф': 'Жилищный кодекс Российской Федерации',
    'жилищный кодекс': 'Жилищный кодекс Российской Федерации',
    'жилищный кодекс рф': 'Жилищный кодекс Российской Федерации',
    'жилищный кодекс российской федерации': 'Жилищный кодекс Российской Федерации',
    
    # Земельный кодекс
    'зк': 'Земельный кодекс Российской Федерации',
    'зк рф': 'Земельный кодекс Российской Федерации',
    'земельный кодекс': 'Земельный кодекс Российской Федерации',
    'земельный кодекс рф': 'Земельный кодекс Российской Федерации',
    'земельный кодекс российской федерации': 'Земельный кодекс Российской Федерации',
    
    # Градостроительный кодекс
    'грк': 'Градостроительный кодекс Российской Федерации',
    'грк рф': 'Градостроительный кодекс Российской Федерации',
    'градостроительный кодекс': 'Градостроительный кодекс Российской Федерации',
    'градостроительный кодекс рф': 'Градостроительный кодекс Российской Федерации',
    'градостроительный кодекс российской федерации': 'Градостроительный кодекс Российской Федерации',
    
    # Конституция Российской Федерации - все падежи и варианты
    'конституция': 'Конституция Российской Федерации',
    'конституция рф': 'Конституция Российской Федерации',
    'конституции рф': 'Конституция Российской Федерации',
    'конституции российской федерации': 'Конституция Российской Федерации',
    'конституция российской федерации': 'Конституция Российской Федерации',
    'конституции': 'Конституция Российской Федерации',
}

def normalize_codex_name(codex_name: str) -> str:
    """
    Нормализует название кодекса к полному названию из БД.
    
    Преобразует все варианты написания (УК, Уголовный кодекс) 
    в полное название (Уголовный кодекс Российской Федерации).
    
    Args:
        codex_name: Название кодекса в любом варианте
        
    Returns:
        Нормализованное полное название кодекса или исходное название, если не найдено
    """
    if not codex_name:
        return codex_name
    
    # Нормализуем: убираем лишние пробелы, приводим к нижнему регистру
    normalized = codex_name.strip().lower()
    
    # Ищем точное совпадение
    if normalized in CODEX_NAME_NORMALIZATION:
        return CODEX_NAME_NORMALIZATION[normalized]
    
    # Если не найдено точное совпадение, возвращаем исходное название
    # (возможно, это уже полное название или название, которого нет в маппинге)
    return codex_name

class CodexService:
    # Простая система уровней: 0 (самый высокий) > 1 > 2 (по умолчанию) > 3 (низкий)
    PRIORITY_ORDER = {'0': 0, '1': 1, '2': 2, '3': 3}
    
    @classmethod
    def get_priority_value(cls, priority_level: Optional[str]) -> int:
        """
        Возвращает числовое значение приоритета для сортировки
        
        Args:
            priority_level: Уровень приоритета ('0', '1', '2', '3')
            
        Returns:
            Числовое значение (меньше = выше приоритет)
        """
        if priority_level is None:
            return 2  # По умолчанию уровень 2
        # Обратная совместимость со старыми уровнями
        old_priority_map = {'0а': 1, '1а': 3}
        if priority_level in old_priority_map:
            priority_level = str(old_priority_map[priority_level])
        return cls.PRIORITY_ORDER.get(priority_level, 2)
    
    # Маппинг синонимов для юридических терминов (на уровне класса)
    SYNONYMS_MAP = {
        'подач': ['подач', 'подача', 'подачи', 'подачу', 'подачей', 'подаче', 'подачам', 'подачами', 'подачах'],
        'апелляц': ['апелляц', 'апелляция', 'апелляционный', 'апелляционной', 'апелляционное', 'апелляционным', 
                   'апелляционными', 'апелляционном', 'апелляционной', 'апелляционную', 'апелляционным'],
        'кассац': ['кассац', 'кассация', 'кассационный', 'кассационной', 'кассационное', 'кассационным',
                  'кассационными', 'кассационном', 'кассационной', 'кассационную', 'кассационным',
                  'кассационную', 'кассационной', 'кассационное'],
        'надзорн': ['надзорн', 'надзор', 'надзорный', 'надзорной', 'надзорное', 'надзорным',
                   'надзорными', 'надзорном', 'надзорной', 'надзорную', 'надзорным',
                   'надзорную', 'надзорной', 'надзорное'],
        'жалоб': ['жалоб', 'жалоба', 'жалобы', 'жалобу', 'жалобой', 'жалобе', 'жалобам', 'жалобами', 'жалобах',
                 'обжалован', 'обжалование', 'обжалования', 'обжалованию', 'обжалованием', 'обжаловании',
                 'обжаловать', 'обжалует', 'обжалуют', 'обжалуется', 'обжалуются'],
        'обжалован': ['обжалован', 'обжалование', 'обжалования', 'обжалованию', 'обжалованием', 'обжаловании',
                     'обжаловать', 'обжалует', 'обжалуют', 'обжалуется', 'обжалуются', 'жалоб', 'жалоба', 'жалобы'],
    }
    
    @classmethod
    def _get_reverse_synonyms(cls):
        """Создает обратный маппинг синонимов"""
        reverse_synonyms = {}
        for base, variants in cls.SYNONYMS_MAP.items():
            for variant in variants:
                reverse_synonyms[variant.lower()] = base
        return reverse_synonyms
    
    def get_base_form(self, word: str) -> str:
        """Получает базовую форму слова (универсальный алгоритм)"""
        if len(word) <= 3:
            return word
        
        word_lower = word.lower()
        
        # Получаем обратный маппинг синонимов
        reverse_synonyms = self._get_reverse_synonyms()
        
        # Сначала проверяем маппинг синонимов
        if word_lower in reverse_synonyms:
            return reverse_synonyms[word_lower]
        
        # Универсальный алгоритм: убираем типичные окончания русского языка
        # Порядок важен: сначала длинные окончания, потом короткие
        endings = [
            # Причастия и деепричастия
            'ющимися', 'ющимися', 'ющихся', 'ющихся', 'ющими', 'ющими',
            # Прилагательные и причастия (множественное число)
            'ыми', 'ими', 'ых', 'их', 'ые', 'ие',
            # Прилагательные и причастия (единственное число, разные падежи)
            'ая', 'ое', 'ый', 'ий', 'ой', 'ую', 'ую', 'ей',
            # Существительные (разные падежи)
            'ами', 'ах', 'ам', 'ей', 'ем', 'ом', 'ой', 'ую', 'ую',
            # Глаголы (разные формы)
            'ется', 'ются', 'ется', 'ются', 'ется', 'ются',
            'ется', 'ются', 'ется', 'ются', 'ется', 'ются',
            # Общие окончания
            'а', 'о', 'е', 'и', 'у', 'ы', 'ю', 'я',
        ]
        
        # Убираем окончания, начиная с самых длинных
        for ending in sorted(endings, key=len, reverse=True):
            if len(word) > len(ending) + 3 and word_lower.endswith(ending):
                base = word_lower[:-len(ending)]
                # Проверяем, что базовая форма имеет смысл (не слишком короткая)
                if len(base) >= 4:
                    return base
        
        # Если не удалось убрать окончание, возвращаем слово как есть
        return word_lower
    
    def __init__(self):
        """Инициализирует сервис и загружает кодексы в память"""
        try:
            logger.info("Инициализация CodexService...")
            
            # Инициализируем БД (создаем таблицы, если их нет)
            from .codex_models import init_database
            logger.info("Инициализация базы данных кодексов...")
            self.engine = init_database()
            logger.info("База данных инициализирована")
            
            # Создаем сессию
            self.session = get_session(self.engine)
            logger.info("Сессия БД создана")
            
            self.codexes_cache: Dict[str, Codex] = {}
            self.codexes_by_abbreviation: Dict[str, Codex] = {}
            
            # Загружаем кодексы в память
            self._load_codexes_to_cache()
        except Exception as e:
            logger.error(f"Критическая ошибка инициализации CodexService: {e}")
            import traceback
            logger.error(f"Трассировка ошибки:\n{traceback.format_exc()}")
            # Устанавливаем пустые значения, чтобы не падал RAGService
            self.engine = None
            self.session = None
            self.codexes_cache = {}
            self.codexes_by_abbreviation = {}
    
    def _load_codexes_to_cache(self):
        """Загружает все кодексы в память при старте"""
        if not self.session:
            logger.error("Сессия БД не инициализирована, невозможно загрузить кодексы")
            return
            
        try:
            logger.info("=" * 60)
            logger.info("ЗАГРУЗКА КОДЕКСОВ В ПАМЯТЬ")
            logger.info("=" * 60)
            
            codexes = self.session.query(Codex).all()
            total_codexes = len(codexes)
            
            if total_codexes == 0:
                logger.warning("В БД не найдено кодексов. Запустите load_codexes_to_db.py для загрузки.")
                logger.info("=" * 60)
                return
            
            logger.info(f"Найдено кодексов в БД: {total_codexes}")
            
            for idx, codex in enumerate(codexes, 1):
                self.codexes_cache[codex.name] = codex
                if codex.abbreviation:
                    self.codexes_by_abbreviation[codex.abbreviation.upper()] = codex
                if codex.short_name:
                    self.codexes_by_abbreviation[codex.short_name.upper()] = codex
                
                # Получаем статистику по кодексу
                try:
                    articles_count = self.session.query(CodexArticle).filter_by(codex_id=codex.id).count()
                    chapters_count = self.session.query(CodexChapter).filter_by(codex_id=codex.id).count()
                    sections_count = self.session.query(CodexSection).filter_by(codex_id=codex.id).count()
                    
                    logger.info(f"[{idx}/{total_codexes}] ✓ {codex.name} ({codex.abbreviation or codex.short_name or 'N/A'}) - "
                              f"{sections_count} разделов, {chapters_count} глав, {articles_count} статей")
                except Exception as stats_error:
                    logger.warning(f"[{idx}/{total_codexes}] ✓ {codex.name} ({codex.abbreviation or codex.short_name or 'N/A'}) - "
                                 f"ошибка получения статистики: {stats_error}")
            
            logger.info("=" * 60)
            logger.info(f"✓ Загружено кодексов в память: {len(self.codexes_cache)}")
            logger.info("=" * 60)
        except Exception as e:
            logger.error(f"Ошибка загрузки кодексов в память: {e}")
            import traceback
            logger.error(f"Трассировка ошибки:\n{traceback.format_exc()}")
            # Не пробрасываем исключение, чтобы не падал RAGService
    
    def get_codex_by_name(self, codex_name: str) -> Optional[Codex]:
        """
        Получает кодекс по названию с улучшенным поиском.
        Приоритет поиска:
        1. Нормализация названия к полному названию из БД
        2. Точное совпадение в кэше
        3. Точное совпадение по аббревиатуре в кэше
        4. Точное совпадение в БД (name, short_name, abbreviation)
        5. Частичное совпадение в БД (только если точное не найдено)
        """
        if not codex_name:
            return None
        
        # ШАГ 0: Нормализуем название кодекса к полному названию из БД
        # Это преобразует "УК", "Уголовный кодекс" в "Уголовный кодекс Российской Федерации"
        normalized_name = normalize_codex_name(codex_name)
        
        # ШАГ 1: Пробуем найти в кэше по точному совпадению (сначала нормализованное, потом исходное)
        if normalized_name in self.codexes_cache:
            return self.codexes_cache[normalized_name]
        if codex_name in self.codexes_cache:
            return self.codexes_cache[codex_name]
        
        # ШАГ 2: Пробуем найти по аббревиатуре в кэше (сначала нормализованное, потом исходное)
        normalized_upper = normalized_name.upper()
        codex_name_upper = codex_name.upper()
        if normalized_upper in self.codexes_by_abbreviation:
            return self.codexes_by_abbreviation[normalized_upper]
        if codex_name_upper in self.codexes_by_abbreviation:
            return self.codexes_by_abbreviation[codex_name_upper]
        
        # ШАГ 3: Ищем точное совпадение в БД (приоритет нормализованному названию)
        # Сначала ищем по нормализованному названию, потом по исходному
        codex = self.session.query(Codex).filter(
            or_(
                Codex.name == normalized_name,
                Codex.short_name == normalized_name,
                Codex.abbreviation == normalized_name,
                Codex.name == codex_name,
                Codex.short_name == codex_name,
                Codex.abbreviation == codex_name,
                Codex.name.ilike(normalized_name),  # Без учета регистра, но без wildcards
                Codex.short_name.ilike(normalized_name),
                Codex.abbreviation.ilike(normalized_name),
                Codex.name.ilike(codex_name),
                Codex.short_name.ilike(codex_name),
                Codex.abbreviation.ilike(codex_name)
            )
        ).first()
        
        # ШАГ 4: Если точное совпадение не найдено, ищем частичное (только для длинных названий)
        if not codex and len(codex_name) > 5:
            # Для частичного поиска используем более строгие условия
            # Ищем только если название кодекса содержит искомую строку как целое слово или начало
            codex = self.session.query(Codex).filter(
                or_(
                    Codex.name.ilike(f'{codex_name}%'),  # Начинается с
                    Codex.name.ilike(f'% {codex_name}%'),  # Содержит как отдельное слово
                    Codex.short_name.ilike(f'{codex_name}%'),
                    Codex.short_name.ilike(f'% {codex_name}%'),
                    Codex.abbreviation.ilike(f'{codex_name}%')
                )
            ).first()
        
        # ШАГ 5: Если все еще не найдено, используем частичный поиск, но с более строгими условиями
        if not codex:
            # Для коротких аббревиатур (2-3 символа) используем более строгий поиск
            # чтобы не находить неправильные кодексы (например, "УК" не должен находить "ГрК")
            if len(codex_name) <= 3:
                # Для коротких аббревиатур ищем только точное совпадение в abbreviation или short_name
                # НЕ ищем в полном названии, чтобы избежать ложных совпадений
                codex = self.session.query(Codex).filter(
                    or_(
                        Codex.abbreviation.ilike(codex_name),
                        Codex.short_name.ilike(f'%{codex_name}%')
                    )
                ).first()
            else:
                # Для длинных названий используем частичный поиск, но с проверкой на релевантность
                # Ищем только если искомое название содержит ключевые слова кодекса
                codex = self.session.query(Codex).filter(
                    or_(
                        Codex.name.ilike(f'%{codex_name}%'),
                        Codex.short_name.ilike(f'%{codex_name}%'),
                        Codex.abbreviation.ilike(f'%{codex_name}%')
                    )
                ).first()
                
                # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: если нашли кодекс, проверяем его релевантность
                # Исключаем явно неправильные совпадения
                if codex:
                    codex_name_lower = codex_name.lower()
                    codex_found_name_lower = codex.name.lower() if codex.name else ''
                    codex_found_abbr_lower = codex.abbreviation.lower() if codex.abbreviation else ''
                    
                    # Список ключевых слов для исключения ложных совпадений
                    # Если ищем "УК" или "Уголовный", не должны находить "Градостроительный"
                    exclusion_keywords = {
                        'ук': ['градостроительный', 'грк'],
                        'уголовный': ['градостроительный', 'грк'],
                        'гражданский': ['градостроительный', 'грк'],
                        'гк': ['градостроительный', 'грк'],
                    }
                    
                    # Проверяем, не является ли найденный кодекс ложным совпадением
                    for search_key, exclude_list in exclusion_keywords.items():
                        if search_key in codex_name_lower:
                            for exclude_word in exclude_list:
                                if exclude_word in codex_found_name_lower or exclude_word in codex_found_abbr_lower:
                                    logger.warning(f"Исключено ложное совпадение: искали '{codex_name}', нашли '{codex.name}' (содержит '{exclude_word}')")
                                    codex = None
                                    break
                            if not codex:
                                break
        
        if codex:
            # Добавляем в кэш для быстрого доступа в будущем
            self.codexes_cache[codex.name] = codex
            if codex.abbreviation:
                self.codexes_by_abbreviation[codex.abbreviation.upper()] = codex
            if codex.short_name:
                self.codexes_by_abbreviation[codex.short_name.upper()] = codex
            logger.debug(f"Найден кодекс: '{codex.name}' (abbreviation: '{codex.abbreviation}', short_name: '{codex.short_name}') по запросу '{codex_name}'")
        else:
            logger.warning(f"Кодекс '{codex_name}' не найден в БД")
        
        return codex
    
    def find_chapter(self, codex: Codex, chapter_number: str) -> Optional[CodexChapter]:
        """Находит главу по номеру"""
        # Пробуем разные варианты номера
        chapter = self.session.query(CodexChapter).filter(
            and_(
                CodexChapter.codex_id == codex.id,
                or_(
                    CodexChapter.number == chapter_number,
                    CodexChapter.number == chapter_number.replace('.', ''),
                    CodexChapter.number.like(f'{chapter_number}%')
                )
            )
        ).first()
        
        return chapter
    
    def find_section(self, codex: Codex, section_name: str) -> Optional[CodexSection]:
        """Находит раздел по названию или номеру"""
        section_name_lower = section_name.lower()
        
        # Ищем по номеру или названию
        section = self.session.query(CodexSection).filter(
            and_(
                CodexSection.codex_id == codex.id,
                or_(
                    CodexSection.number.ilike(f'%{section_name}%'),
                    CodexSection.title.ilike(f'%{section_name}%')
                )
            )
        ).first()
        
        return section
    
    def find_article(self, codex: Codex, article_number: str) -> Optional[CodexArticle]:
        """
        Находит статью по номеру.
        Пробует разные варианты номера для надежности.
        """
        if not article_number:
            return None
        
        # Нормализуем номер статьи (убираем лишние пробелы)
        article_number = article_number.strip()
        
        logger.info(f"[find_article] Ищем статью '{article_number}' в кодексе '{codex.name}' (ID: {codex.id})")
        
        # ШАГ 1: Точное совпадение
        article = self.session.query(CodexArticle).filter(
            and_(
                CodexArticle.codex_id == codex.id,
                CodexArticle.number == article_number
            )
        ).first()
        
        if article:
            logger.info(f"[find_article] ✓ Найдена статья {article_number} по точному совпадению (ID: {article.id})")
            return article
        
        # ШАГ 2: Совпадение без учета регистра (если номер содержит буквы)
        article = self.session.query(CodexArticle).filter(
            and_(
                CodexArticle.codex_id == codex.id,
                CodexArticle.number.ilike(article_number)
            )
        ).first()
        
        if article:
            logger.info(f"[find_article] ✓ Найдена статья {article_number} по совпадению без учета регистра (ID: {article.id})")
            return article
        
        # ШАГ 3: Поиск с учетом возможных вариантов формата (например, "338" и "338.0")
        # Убираем ведущие нули и пробуем разные варианты
        normalized_number = article_number.lstrip('0') if article_number.lstrip('0') else article_number
        
        if normalized_number != article_number:
            article = self.session.query(CodexArticle).filter(
                and_(
                    CodexArticle.codex_id == codex.id,
                    CodexArticle.number == normalized_number
                )
            ).first()
            
            if article:
                logger.debug(f"Найдена статья {article_number} по нормализованному номеру {normalized_number}")
                return article
        
        # ШАГ 4: Поиск по началу номера (для случаев типа "338.1" и "338")
        if '.' in article_number:
            base_number = article_number.split('.')[0]
            article = self.session.query(CodexArticle).filter(
                and_(
                    CodexArticle.codex_id == codex.id,
                    CodexArticle.number.like(f'{base_number}%')
                )
            ).first()
            
            if article:
                logger.debug(f"Найдена статья {article_number} по базовому номеру {base_number}")
                return article
        
        # Проверяем, есть ли вообще статьи в этом кодексе
        total_articles = self.session.query(CodexArticle).filter(CodexArticle.codex_id == codex.id).count()
        logger.warning(f"[find_article] ✗ Статья {article_number} не найдена в кодексе {codex.name} (ID: {codex.id}). Всего статей в кодексе: {total_articles}")
        
        # Показываем примеры номеров статей для отладки
        if total_articles > 0:
            sample_articles = self.session.query(CodexArticle.number).filter(
                CodexArticle.codex_id == codex.id
            ).limit(10).all()
            sample_numbers = [str(a[0]) for a in sample_articles]
            logger.info(f"[find_article] Примеры номеров статей в кодексе: {', '.join(sample_numbers)}")
        
        return None
    
    def search_articles_by_keywords(self, codex: Codex, keywords: List[str], 
                                   limit: int = 10) -> List[CodexArticle]:
        """
        Ищет статьи по ключевым словам с приоритетом:
        1. Сначала ищет все слова вместе (без окончаний, в любом порядке)
        2. Потом убирает по одному слову и повторяет
        3. Продолжает, пока слова остались
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not keywords:
            logger.warning(f"[Поиск статей] Пустой список ключевых слов для кодекса {codex.name}")
            return []
        
        import re
        from sqlalchemy import and_, or_
        
        logger.info(f"[Поиск статей] Начало поиска в кодексе '{codex.name}'")
        logger.info(f"[Поиск статей] Входные ключевые слова ({len(keywords)}): {', '.join(keywords[:10])}")
        
        # Проверяем, является ли запрос номером статьи
        query_text = ' '.join(keywords) if isinstance(keywords, list) else str(keywords)
        query_lower = query_text.lower().strip()
        
        # Проверяем, является ли запрос числом (номером статьи)
        article_match = re.search(r'статья\s+(\d+(?:\.\d+)?)', query_lower)
        if article_match:
            article_number = article_match.group(1)
            logger.info(f"[Поиск статей] Обнаружен номер статьи: {article_number}")
            # Ищем конкретную статью
            article = self.find_article(codex, article_number)
            if article:
                logger.info(f"[Поиск статей] ✓ Найдена статья {article_number}: {article.title[:50] if article.title else 'без названия'}")
                return [article]
            else:
                logger.warning(f"[Поиск статей] Статья {article_number} не найдена в кодексе")
        
        # Используем новый модуль legal_terms для ранжирования и фильтрации
        if isinstance(keywords, list):
            query_text = ' '.join(keywords)
        else:
            query_text = str(keywords)
        
        # Получаем ранжированные ключевые слова с приоритетами
        ranked_words = rank_and_filter_query(query_text)
        
        # Сортируем по приоритету: сначала HIGH, потом MEDIUM, потом LOW
        # Берем до 15 слов, приоритизируя высокоприоритетные
        high_priority = [base for base, priority in ranked_words if priority == PRIORITY_HIGH][:5]
        medium_priority = [base for base, priority in ranked_words if priority == PRIORITY_MEDIUM][:7]
        low_priority = [base for base, priority in ranked_words if priority == PRIORITY_LOW][:3]
        
        base_keywords = high_priority + medium_priority + low_priority
        
        if not base_keywords:
            logger.warning(f"[Поиск статей] После ранжирования и фильтрации не осталось ключевых слов")
            return []
        
        logger.info(f"[Поиск статей] Ранжированные ключевые слова:")
        logger.info(f"  HIGH ({len(high_priority)}): {', '.join(high_priority)}")
        logger.info(f"  MEDIUM ({len(medium_priority)}): {', '.join(medium_priority)}")
        logger.info(f"  LOW ({len(low_priority)}): {', '.join(low_priority)}")
        logger.info(f"  Всего: {len(base_keywords)} слов")
        
        # Получаем маппинги синонимов для использования в функции поиска
        reverse_synonyms = self._get_reverse_synonyms()
        synonyms_map = self.SYNONYMS_MAP
        
        # Функция для поиска статей по набору ключевых слов
        def search_by_keyword_set(keyword_set, step_name="неизвестный шаг"):
            if not keyword_set:
                logger.debug(f"[Поиск статей] [{step_name}] Пустой набор ключевых слов")
                return []
            
            logger.info(f"[Поиск статей] [{step_name}] Поиск по набору ({len(keyword_set)} слов): {', '.join(keyword_set[:5])}")
            
            # Формируем условия для поиска всех слов вместе (в любом порядке)
            # Ищем статьи, где все слова присутствуют (в заголовке или содержании)
            conditions = [CodexArticle.codex_id == codex.id]
            
            # Для каждого слова создаем условие, что оно есть в заголовке или содержании
            # Учитываем синонимы из маппинга
            keyword_conditions = []
            for keyword in keyword_set:
                # Получаем все варианты слова (включая синонимы)
                keyword_variants = [keyword]
                if keyword in synonyms_map:
                    keyword_variants.extend(synonyms_map[keyword])
                elif keyword in reverse_synonyms:
                    base = reverse_synonyms[keyword]
                    if base in synonyms_map:
                        keyword_variants.extend(synonyms_map[base])
                
                # Создаем условие для всех вариантов слова
                variant_conditions = []
                for variant in keyword_variants:
                    variant_lower = f'%{variant}%'
                    variant_conditions.append(
                        or_(
                            CodexArticle.title.ilike(variant_lower),
                            CodexArticle.content.ilike(variant_lower)
                        )
                    )
                
                # Объединяем все варианты через OR (слово может быть в любом варианте)
                if variant_conditions:
                    keyword_conditions.append(or_(*variant_conditions))
            
            # Ищем статьи, содержащие все слова из набора
            # Сначала пробуем найти статьи, где слова есть в названии (более релевантные)
            articles = self.session.query(CodexArticle).filter(
                and_(
                    CodexArticle.codex_id == codex.id,
                    *keyword_conditions  # Все условия должны выполняться (AND)
                )
            ).order_by(
                # Приоритет: сначала статьи с более высоким уровнем приоритета
                case(
                    (CodexArticle.priority_level == '0', 0),
                    (CodexArticle.priority_level == '1', 1),
                    (CodexArticle.priority_level == '2', 2),
                    (CodexArticle.priority_level == '3', 3),
                    # Обратная совместимость со старыми уровнями
                    (CodexArticle.priority_level == '0а', 1),
                    (CodexArticle.priority_level == '1а', 3),
                    else_=2  # По умолчанию уровень 2
                ),
                # Затем статьи, где ключевые слова в названии
                CodexArticle.title.ilike(f'%{keyword_set[0]}%').desc() if keyword_set else None,
                CodexArticle.order_index
            ).limit(limit).all()
            
            # Если нашли статьи, сортируем их по релевантности (количество совпадений в названии)
            if articles:
                def relevance_score(article):
                    score = 0
                    title_lower = (article.title or '').lower()
                    content_lower = article.content.lower()
                    for keyword in keyword_set:
                        if keyword in title_lower:
                            score += 10  # Большой вес для совпадения в названии
                        if keyword in content_lower:
                            score += 1   # Меньший вес для совпадения в содержании
                    return score
                
                articles = sorted(articles, key=relevance_score, reverse=True)
            
            if articles:
                logger.info(f"[Поиск статей] [{step_name}] ✓ Найдено {len(articles)} статей со всеми словами:")
                for art in articles[:5]:
                    logger.info(f"  - Статья {art.number}: {art.title[:60] if art.title else 'без названия'}")
                return articles
            else:
                logger.debug(f"[Поиск статей] [{step_name}] Не найдено статей со всеми словами")
            
            # Если не нашли со всеми словами, пробуем поиск по частям слов (без окончаний)
            if len(keyword_set) > 0:
                logger.debug(f"[Поиск статей] [{step_name}] Пробуем поиск по частям слов...")
                keyword_part_conditions = []
                for keyword in keyword_set:
                    if len(keyword) > 4:
                        # Берем первые 4 символа для поиска по частям
                        keyword_part = keyword[:4]
                        keyword_part_lower = f'%{keyword_part}%'
                        keyword_part_conditions.append(
                            or_(
                                CodexArticle.title.ilike(keyword_part_lower),
                                CodexArticle.content.ilike(keyword_part_lower)
                            )
                        )
                
                if keyword_part_conditions:
                    articles = self.session.query(CodexArticle).filter(
                        and_(
                            CodexArticle.codex_id == codex.id,
                            *keyword_part_conditions
                        )
                    ).order_by(
                case(
                    (CodexArticle.priority_level == '0', 0),
                    (CodexArticle.priority_level == '1', 1),
                    (CodexArticle.priority_level == '2', 2),
                    (CodexArticle.priority_level == '3', 3),
                    # Обратная совместимость со старыми уровнями
                    (CodexArticle.priority_level == '0а', 1),
                    (CodexArticle.priority_level == '1а', 3),
                    else_=2
                ),
                CodexArticle.order_index
            ).limit(limit).all()
                    
                    if articles:
                        logger.info(f"[Поиск статей] [{step_name}] ✓ Найдено {len(articles)} статей по частям слов")
                        return articles
            
            return []
        
        # Шаг 1: Ищем все слова вместе
        logger.info(f"[Поиск статей] === ШАГ 1: Поиск всех слов вместе ({len(base_keywords)} слов) ===")
        articles = search_by_keyword_set(base_keywords, f"ШАГ 1: все {len(base_keywords)} слов")
        
        # Если нашли мало статей (меньше 5) или нет статей с ключевыми словами в названии,
        # продолжаем поиск, убирая слова по одному
        min_articles_threshold = 5
        should_continue = False
        
        if not articles:
            should_continue = True
            logger.info(f"[Поиск статей] ШАГ 1: Статьи не найдены, продолжаем поиск")
        elif len(articles) < min_articles_threshold:
            # Проверяем релевантность: есть ли статьи с ключевыми словами в названии
            articles_with_keywords_in_title = 0
            for art in articles:
                title_lower = (art.title or '').lower()
                if any(kw in title_lower for kw in base_keywords):
                    articles_with_keywords_in_title += 1
            
            logger.info(f"[Поиск статей] ШАГ 1: Найдено {len(articles)} статей, из них {articles_with_keywords_in_title} с ключевыми словами в названии")
            
            # Продолжаем поиск, если:
            # 1. Мало статей с ключевыми словами в названии (меньше 2)
            # 2. Или вообще мало статей (меньше 5)
            if articles_with_keywords_in_title < 2 or len(articles) < 3:
                should_continue = True
                logger.info(f"[Поиск статей] ШАГ 1: Продолжаем поиск для улучшения результатов")
        
        if articles and not should_continue:
            return articles
        
        # Шаг 2 и далее: Последовательно убираем по одному слову и ищем
        # Продолжаем, пока есть хотя бы 2 слова
        current_keywords = base_keywords.copy()
        step_num = 2
        best_articles = articles if articles else None
        
        while len(current_keywords) >= 2:
            logger.info(f"[Поиск статей] === ШАГ {step_num}: Убираем по одному слову, осталось {len(current_keywords)} слов ===")
            
            # Пробуем убрать каждое слово по очереди
            found_articles = None
            for skip_idx in range(len(current_keywords)):
                # Создаем набор без одного слова
                reduced_keywords = [kw for idx, kw in enumerate(current_keywords) if idx != skip_idx]
                step_name = f"ШАГ {step_num}: без слова '{current_keywords[skip_idx]}' ({len(reduced_keywords)} из {len(current_keywords)})"
                
                articles = search_by_keyword_set(reduced_keywords, step_name)
                if articles:
                    # Если нашли больше статей или статьи с ключевыми словами в названии, используем их
                    if not found_articles or len(articles) > len(found_articles):
                        found_articles = articles
                    # Если нашли статью с ключевыми словами в названии, предпочитаем её
                    elif found_articles:
                        for art in articles:
                            title_lower = (art.title or '').lower()
                            if any(kw in title_lower for kw in reduced_keywords):
                                found_articles = articles
                                break
            
            if found_articles:
                # Проверяем релевантность: количество статей с ключевыми словами в названии
                articles_with_keywords = sum(1 for art in found_articles 
                                           if any(kw in (art.title or '').lower() for kw in reduced_keywords))
                best_with_keywords = sum(1 for art in best_articles 
                                        if any(kw in (art.title or '').lower() for kw in base_keywords)) if best_articles else 0
                
                logger.info(f"[Поиск статей] ШАГ {step_num}: Найдено {len(found_articles)} статей, из них {articles_with_keywords} с ключевыми словами в названии (лучший результат: {best_with_keywords})")
                
                # Если нашли много статей (10+), это хороший результат, даже если не все с ключевыми словами в названии
                if len(found_articles) >= 10:
                    best_articles = found_articles
                    logger.info(f"[Поиск статей] ШАГ {step_num}: Найдено много статей ({len(found_articles)}), используем их")
                    return found_articles
                
                # Если нашли статьи с ключевыми словами в названии, и их больше чем в предыдущих результатах
                if articles_with_keywords > best_with_keywords:
                    best_articles = found_articles
                    logger.info(f"[Поиск статей] ШАГ {step_num}: Найдено {articles_with_keywords} статей с ключевыми словами в названии (лучше чем {best_with_keywords}), обновляем лучший результат")
                    # Если нашли достаточно релевантных статей (3+ с ключевыми словами в названии), останавливаемся
                    if articles_with_keywords >= 3:
                        logger.info(f"[Поиск статей] ШАГ {step_num}: Найдено достаточно релевантных статей, останавливаем поиск")
                        return found_articles
                # Если нашли больше статей и они достаточно релевантны
                elif not best_articles or (len(found_articles) > len(best_articles) and articles_with_keywords >= 2):
                    best_articles = found_articles
                    logger.info(f"[Поиск статей] ШАГ {step_num}: Найдено {len(found_articles)} статей ({articles_with_keywords} с ключевыми словами), обновляем лучший результат")
                    # Если нашли достаточно статей с ключевыми словами, останавливаемся
                    if articles_with_keywords >= 3:
                        logger.info(f"[Поиск статей] ШАГ {step_num}: Найдено достаточно релевантных статей, останавливаем поиск")
                        return found_articles
                else:
                    logger.info(f"[Поиск статей] ШАГ {step_num}: Найденные статьи не лучше текущего лучшего результата, продолжаем поиск")
            
            # Если не нашли лучших статей, убираем первое слово и продолжаем
            if len(current_keywords) > 1:
                removed_word = current_keywords.pop(0)
                logger.info(f"[Поиск статей] ШАГ {step_num}: Не найдено лучших статей, убираем слово '{removed_word}', осталось {len(current_keywords)} слов")
                step_num += 1
            else:
                break
        
        # Возвращаем лучшие найденные статьи (если есть)
        if best_articles:
            logger.info(f"[Поиск статей] Возвращаем лучшие найденные статьи: {len(best_articles)} статей")
            return best_articles
        
        # Шаг 3: Если ничего не нашли, пробуем поиск по отдельным словам (OR)
        logger.info(f"[Поиск статей] === ШАГ 3: Поиск по отдельным словам (OR) ===")
        keyword_conditions = []
        for keyword in base_keywords[:10]:  # Берем первые 10 слов
            keyword_lower = f'%{keyword}%'
            keyword_conditions.append(
                or_(
                    CodexArticle.title.ilike(keyword_lower),
                    CodexArticle.content.ilike(keyword_lower)
                )
            )
        
        if keyword_conditions:
            logger.info(f"[Поиск статей] [ШАГ 3: OR] Поиск статей, содержащих хотя бы одно из слов: {', '.join(base_keywords[:5])}")
            articles = self.session.query(CodexArticle).filter(
                and_(
                    CodexArticle.codex_id == codex.id,
                    or_(*keyword_conditions)  # Хотя бы одно слово
                )
            ).order_by(
                case(
                    (CodexArticle.priority_level == '0', 0),
                    (CodexArticle.priority_level == '1', 1),
                    (CodexArticle.priority_level == '2', 2),
                    (CodexArticle.priority_level == '3', 3),
                    # Обратная совместимость со старыми уровнями
                    (CodexArticle.priority_level == '0а', 1),
                    (CodexArticle.priority_level == '1а', 3),
                    else_=2
                ),
                CodexArticle.order_index
            ).limit(limit).all()
            
            if articles:
                logger.info(f"[Поиск статей] [ШАГ 3: OR] ✓ Найдено {len(articles)} статей:")
                for art in articles[:5]:
                    logger.info(f"  - Статья {art.number}: {art.title[:60] if art.title else 'без названия'}")
                return articles
        
        logger.warning(f"[Поиск статей] ✗ Статьи не найдены ни одним из методов поиска")
        return []
    
    def get_chapter_content(self, codex: Codex, chapter_number: str) -> Optional[str]:
        """Получает содержимое главы"""
        chapter = self.find_chapter(codex, chapter_number)
        if chapter:
            return chapter.content
        return None
    
    def get_section_content(self, codex: Codex, section_name: str) -> Optional[str]:
        """Получает содержимое раздела"""
        section = self.find_section(codex, section_name)
        if section:
            return section.content
        return None
    
    def search_sections_by_keywords(self, codex: Codex, keywords: List[str]) -> List[CodexSection]:
        """Ищет разделы по ключевым словам в названии"""
        from sqlalchemy import or_, and_
        
        if not keywords:
            return []
        
        # Используем базовые формы ключевых слов (как в search_articles_by_keywords)
        base_keywords = []
        for keyword in keywords:
            base_form = self.get_base_form(keyword)
            if base_form and len(base_form) > 3:
                base_keywords.append(base_form)
        
        if not base_keywords:
            return []
        
        # Формируем условия поиска
        conditions = []
        for keyword in base_keywords:
            keyword_lower = f'%{keyword.lower()}%'
            conditions.append(
                or_(
                    CodexSection.title.ilike(keyword_lower),
                    CodexSection.number.ilike(keyword_lower)
                )
            )
        
        # Ищем разделы, содержащие хотя бы одно ключевое слово
        sections = self.session.query(CodexSection).filter(
            and_(
                CodexSection.codex_id == codex.id,
                or_(*conditions)
            )
        ).all()
        
        return sections
    
    def search_chapters_by_keywords(self, codex: Codex, keywords: List[str]) -> List[CodexChapter]:
        """Ищет главы по ключевым словам в названии"""
        from sqlalchemy import or_, and_
        
        if not keywords:
            return []
        
        # Используем базовые формы ключевых слов (как в search_articles_by_keywords)
        base_keywords = []
        for keyword in keywords:
            base_form = self.get_base_form(keyword)
            if base_form and len(base_form) > 3:
                base_keywords.append(base_form)
        
        if not base_keywords:
            return []
        
        # Формируем условия поиска
        conditions = []
        for keyword in base_keywords:
            keyword_lower = f'%{keyword.lower()}%'
            conditions.append(
                or_(
                    CodexChapter.title.ilike(keyword_lower),
                    CodexChapter.number.ilike(keyword_lower)
                )
            )
        
        # Ищем главы, содержащие хотя бы одно ключевое слово
        chapters = self.session.query(CodexChapter).filter(
            and_(
                CodexChapter.codex_id == codex.id,
                or_(*conditions)
            )
        ).all()
        
        return chapters
    
    def get_all_articles_from_section(self, section: CodexSection, max_length: int = 5000) -> str:
        """Получает все статьи из раздела по порядку"""
        # Получаем все статьи раздела, отсортированные по order_index
        articles = self.session.query(CodexArticle).filter(
            CodexArticle.section_id == section.id
        ).order_by(
            case(
                (CodexArticle.priority_level == '0', 0),
                (CodexArticle.priority_level == '0а', 1),
                (CodexArticle.priority_level == '1', 2),
                (CodexArticle.priority_level == '1а', 3),
                else_=2
            ),
            CodexArticle.order_index.asc(),
            CodexArticle.number.asc()
        ).all()
        
        snippets = []
        total_length = 0
        
        for article in articles:
            article_text = f"Статья {article.number}. {article.title}\n\n{article.content}" if article.title else f"Статья {article.number}\n\n{article.content}"
            if total_length + len(article_text) <= max_length:
                snippets.append(article_text)
                total_length += len(article_text)
                logger.info(f"[Извлечение фрагмента] Добавлена статья {article.number} из раздела (длина: {len(article_text)}, всего: {total_length})")
            else:
                remaining = max_length - total_length
                if remaining > 200:
                    snippets.append(article_text[:remaining])
                    logger.info(f"[Извлечение фрагмента] Добавлена часть статьи {article.number} (длина: {remaining})")
                break
        
        if snippets:
            return '\n\n'.join(snippets)
        return None
    
    def get_all_articles_from_chapter(self, chapter: CodexChapter, max_length: int = 5000) -> str:
        """Получает все статьи из главы по порядку"""
        # Получаем все статьи главы, отсортированные по order_index
        articles = self.session.query(CodexArticle).filter(
            CodexArticle.chapter_id == chapter.id
        ).order_by(
            case(
                (CodexArticle.priority_level == '0', 0),
                (CodexArticle.priority_level == '0а', 1),
                (CodexArticle.priority_level == '1', 2),
                (CodexArticle.priority_level == '1а', 3),
                else_=2
            ),
            CodexArticle.order_index.asc(),
            CodexArticle.number.asc()
        ).all()
        
        snippets = []
        total_length = 0
        
        for article in articles:
            article_text = f"Статья {article.number}. {article.title}\n\n{article.content}" if article.title else f"Статья {article.number}\n\n{article.content}"
            if total_length + len(article_text) <= max_length:
                snippets.append(article_text)
                total_length += len(article_text)
                logger.info(f"[Извлечение фрагмента] Добавлена статья {article.number} из главы (длина: {len(article_text)}, всего: {total_length})")
            else:
                remaining = max_length - total_length
                if remaining > 200:
                    snippets.append(article_text[:remaining])
                    logger.info(f"[Извлечение фрагмента] Добавлена часть статьи {article.number} (длина: {remaining})")
                break
        
        if snippets:
            return '\n\n'.join(snippets)
        return None
    
    def extract_relevant_snippet(self, codex: Codex, section_names: Optional[List[str]] = None,
                                 context_terms: Optional[List[str]] = None,
                                 max_length: int = 5000) -> Tuple[Optional[str], Optional[List['CodexArticle']]]:
        """
        Извлекает релевантный фрагмент из кодекса.
        Порядок поиска:
        1. По разделам (по ключевым словам в названиях)
        2. По главам (по ключевым словам в названиях)
        3. По статьям (по ключевым словам)
        
        Если найден раздел/глава, возвращаются все статьи из него по порядку.
        
        Args:
            codex: Кодекс
            section_names: Названия разделов/глав для поиска
            context_terms: Ключевые слова для поиска
            max_length: Максимальная длина фрагмента
            
        Returns:
            Кортеж (текст фрагмента, список статей) или (None, None)
        """
        # ШАГ 1: Поиск по явно указанным разделам/главам
        if section_names:
            for section_name in section_names:
                # Пробуем найти главу
                chapter = self.find_chapter(codex, section_name)
                if chapter:
                    logger.info(f"[Извлечение фрагмента] Найдена глава: {chapter.number} - {chapter.title}")
                    # Получаем все статьи из главы
                    articles = self.session.query(CodexArticle).filter(
                        CodexArticle.chapter_id == chapter.id
                    ).order_by(
            case(
                (CodexArticle.priority_level == '0', 0),
                (CodexArticle.priority_level == '0а', 1),
                (CodexArticle.priority_level == '1', 2),
                (CodexArticle.priority_level == '1а', 3),
                else_=2
            ),
            CodexArticle.order_index.asc(),
            CodexArticle.number.asc()
        ).all()
                    snippet = self.get_all_articles_from_chapter(chapter, max_length)
                    if snippet:
                        logger.info(f"[Извлечение фрагмента] ✓ Получены все статьи из главы, длина: {len(snippet)} символов")
                        return snippet, articles
                
                # Пробуем найти раздел
                section = self.find_section(codex, section_name)
                if section:
                    logger.info(f"[Извлечение фрагмента] Найден раздел: {section.number} - {section.title}")
                    # Получаем все статьи из раздела
                    articles = self.session.query(CodexArticle).filter(
                        CodexArticle.section_id == section.id
                    ).order_by(
            case(
                (CodexArticle.priority_level == '0', 0),
                (CodexArticle.priority_level == '0а', 1),
                (CodexArticle.priority_level == '1', 2),
                (CodexArticle.priority_level == '1а', 3),
                else_=2
            ),
            CodexArticle.order_index.asc(),
            CodexArticle.number.asc()
        ).all()
                    snippet = self.get_all_articles_from_section(section, max_length)
                    if snippet:
                        logger.info(f"[Извлечение фрагмента] ✓ Получены все статьи из раздела, длина: {len(snippet)} символов")
                        return snippet, articles
        
        # ШАГ 2: Поиск разделов по ключевым словам
        if context_terms:
            logger.info(f"[Извлечение фрагмента] ШАГ 2: Поиск разделов по ключевым словам...")
            sections = self.search_sections_by_keywords(codex, context_terms)
            if sections:
                logger.info(f"[Извлечение фрагмента] ✓ Найдено {len(sections)} разделов по ключевым словам")
                # Берем первый найденный раздел
                section = sections[0]
                logger.info(f"[Извлечение фрагмента] Используем раздел: {section.number} - {section.title}")
                # Получаем все статьи из раздела
                articles = self.session.query(CodexArticle).filter(
                    CodexArticle.section_id == section.id
                ).order_by(
            case(
                (CodexArticle.priority_level == '0', 0),
                (CodexArticle.priority_level == '0а', 1),
                (CodexArticle.priority_level == '1', 2),
                (CodexArticle.priority_level == '1а', 3),
                else_=2
            ),
            CodexArticle.order_index.asc(),
            CodexArticle.number.asc()
        ).all()
                snippet = self.get_all_articles_from_section(section, max_length)
                if snippet:
                    logger.info(f"[Извлечение фрагмента] ✓ Получены все статьи из раздела, длина: {len(snippet)} символов")
                    return snippet, articles
            
            # ШАГ 3: Поиск глав по ключевым словам
            logger.info(f"[Извлечение фрагмента] ШАГ 3: Поиск глав по ключевым словам...")
            chapters = self.search_chapters_by_keywords(codex, context_terms)
            if chapters:
                logger.info(f"[Извлечение фрагмента] ✓ Найдено {len(chapters)} глав по ключевым словам")
                # Берем первую найденную главу
                chapter = chapters[0]
                logger.info(f"[Извлечение фрагмента] Используем главу: {chapter.number} - {chapter.title}")
                # Получаем все статьи из главы
                articles = self.session.query(CodexArticle).filter(
                    CodexArticle.chapter_id == chapter.id
                ).order_by(
            case(
                (CodexArticle.priority_level == '0', 0),
                (CodexArticle.priority_level == '0а', 1),
                (CodexArticle.priority_level == '1', 2),
                (CodexArticle.priority_level == '1а', 3),
                else_=2
            ),
            CodexArticle.order_index.asc(),
            CodexArticle.number.asc()
        ).all()
                snippet = self.get_all_articles_from_chapter(chapter, max_length)
                if snippet:
                    logger.info(f"[Извлечение фрагмента] ✓ Получены все статьи из главы, длина: {len(snippet)} символов")
                    return snippet, articles
            
            # ШАГ 4: Поиск статей по ключевым словам
            logger.info(f"[Извлечение фрагмента] ШАГ 4: Поиск статей по ключевым словам...")
            articles = self.search_articles_by_keywords(codex, context_terms, limit=10)
            if articles:
                logger.info(f"[Извлечение фрагмента] ✓ Найдено {len(articles)} статей, формируем фрагмент...")
                # Объединяем содержимое найденных статей с указанием номеров статей
                snippets = []
                total_length = 0
                for article in articles:
                    article_text = f"Статья {article.number}. {article.title}\n\n{article.content}" if article.title else f"Статья {article.number}\n\n{article.content}"
                    if total_length + len(article_text) <= max_length:
                        snippets.append(article_text)
                        total_length += len(article_text)
                        logger.info(f"[Извлечение фрагмента] Добавлена статья {article.number} (длина: {len(article_text)}, всего: {total_length})")
                    else:
                        remaining = max_length - total_length
                        if remaining > 200:
                            snippets.append(article_text[:remaining])
                            logger.info(f"[Извлечение фрагмента] Добавлена часть статьи {article.number} (длина: {remaining})")
                        break
                
                if snippets:
                    result = '\n\n'.join(snippets)
                    logger.info(f"[Извлечение фрагмента] ✓ Фрагмент сформирован, длина: {len(result)} символов")
                    return result, articles
            else:
                logger.warning(f"[Извлечение фрагмента] ✗ Статьи по ключевым словам не найдены")
        else:
            logger.warning(f"[Извлечение фрагмента] Ключевые слова не предоставлены")
        
        # Если ничего не найдено, возвращаем None (не начало кодекса)
        logger.warning(f"[Извлечение фрагмента] ✗ Релевантный фрагмент не найден")
        return None, None
    
    def get_codex_document_dict(self, codex: Codex, content: str, 
                                section_hint: Optional[str] = None,
                                articles: Optional[List['CodexArticle']] = None) -> Dict:
        """
        Формирует словарь документа для RAG сервиса
        
        Args:
            codex: Кодекс
            content: Содержимое документа
            section_hint: Подсказка о разделе/главе
            articles: Список статей, из которых сформирован контент (для извлечения структуры)
            
        Returns:
            Словарь документа в формате RAG
        """
        metadata = {
            'doc_title': codex.name,
            'codex_name': codex.name,
            'doc_type': 'Кодекс',
            'level': 'Кодексы и законы',
            'source': f'db://codex/{codex.id}',
            'filename': f'{codex.abbreviation or codex.short_name or "codex"}.txt'
        }
        
        if section_hint:
            metadata['section_hint'] = section_hint
        
        # Если передан список статей, извлекаем информацию о структуре из первой статьи
        if articles and len(articles) > 0:
            first_article = articles[0]
            # Добавляем информацию о структуре из статьи
            if first_article.section_number:
                metadata['section_number'] = first_article.section_number
            if first_article.section_title:
                metadata['section_title'] = first_article.section_title
            if first_article.chapter_number:
                metadata['chapter_number'] = first_article.chapter_number
            if first_article.chapter_title:
                metadata['chapter_title'] = first_article.chapter_title
            if first_article.number:
                metadata['article_number'] = first_article.number
            if first_article.full_structure_path:
                metadata['full_structure_path'] = first_article.full_structure_path
        
        return {
            'content': content,
            'metadata': metadata,
            'score': 1.0,
            'found_via': 'codex_db'
        }
    
    def search_articles_by_section(self, codex: Codex, section_number: Optional[str] = None, 
                                   section_title: Optional[str] = None, limit: int = 100) -> List[CodexArticle]:
        """
        Ищет статьи по разделу, используя новые поля структуры
        
        Args:
            codex: Кодекс
            section_number: Номер раздела
            section_title: Название раздела (или часть названия)
            limit: Максимальное количество результатов
            
        Returns:
            Список статей
        """
        conditions = [CodexArticle.codex_id == codex.id]
        
        if section_number:
            conditions.append(CodexArticle.section_number == section_number)
        
        if section_title:
            conditions.append(CodexArticle.section_title.ilike(f'%{section_title}%'))
        
        articles = self.session.query(CodexArticle).filter(
            and_(*conditions)
        ).order_by(CodexArticle.order_index).limit(limit).all()
        
        return articles
    
    def search_articles_by_chapter(self, codex: Codex, chapter_number: Optional[str] = None,
                                  chapter_title: Optional[str] = None, limit: int = 100) -> List[CodexArticle]:
        """
        Ищет статьи по главе, используя новые поля структуры
        
        Args:
            codex: Кодекс
            chapter_number: Номер главы
            chapter_title: Название главы (или часть названия)
            limit: Максимальное количество результатов
            
        Returns:
            Список статей
        """
        conditions = [CodexArticle.codex_id == codex.id]
        
        if chapter_number:
            conditions.append(CodexArticle.chapter_number == chapter_number)
        
        if chapter_title:
            conditions.append(CodexArticle.chapter_title.ilike(f'%{chapter_title}%'))
        
        articles = self.session.query(CodexArticle).filter(
            and_(*conditions)
        ).order_by(CodexArticle.order_index).limit(limit).all()
        
        return articles
    
    def search_articles_by_structure(self, codex: Codex, section_number: Optional[str] = None,
                                    section_title: Optional[str] = None,
                                    chapter_number: Optional[str] = None,
                                    chapter_title: Optional[str] = None,
                                    limit: int = 100) -> List[CodexArticle]:
        """
        Ищет статьи по структуре (раздел и/или глава), используя новые поля
        
        Args:
            codex: Кодекс
            section_number: Номер раздела
            section_title: Название раздела (или часть названия)
            chapter_number: Номер главы
            chapter_title: Название главы (или часть названия)
            limit: Максимальное количество результатов
            
        Returns:
            Список статей
        """
        conditions = [CodexArticle.codex_id == codex.id]
        
        if section_number:
            conditions.append(CodexArticle.section_number == section_number)
        
        if section_title:
            conditions.append(CodexArticle.section_title.ilike(f'%{section_title}%'))
        
        if chapter_number:
            conditions.append(CodexArticle.chapter_number == chapter_number)
        
        if chapter_title:
            conditions.append(CodexArticle.chapter_title.ilike(f'%{chapter_title}%'))
        
        articles = self.session.query(CodexArticle).filter(
            and_(*conditions)
        ).order_by(CodexArticle.order_index).limit(limit).all()
        
        return articles
    
    def search_articles_by_structure_path(self, codex: Codex, structure_path: str, 
                                        limit: int = 100) -> List[CodexArticle]:
        """
        Ищет статьи по полному пути структуры
        
        Args:
            codex: Кодекс
            structure_path: Путь структуры для поиска (например, "Раздел I" или "Глава 39")
            limit: Максимальное количество результатов
            
        Returns:
            Список статей
        """
        articles = self.session.query(CodexArticle).filter(
            and_(
                CodexArticle.codex_id == codex.id,
                CodexArticle.full_structure_path.ilike(f'%{structure_path}%')
            )
        ).order_by(CodexArticle.order_index).limit(limit).all()
        
        return articles
    
    def close(self):
        """Закрывает сессию"""
        self.session.close()

