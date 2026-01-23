"""
Утилиты для работы с Markdown
"""

import re
import logging
from typing import Optional

try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    markdown = None
    logging.getLogger(__name__).warning("markdown не установлен. Установите: pip install markdown")

logger = logging.getLogger(__name__)


def markdown_to_html(text: str) -> str:
    """
    Преобразует Markdown текст в HTML
    
    Args:
        text: Текст в формате Markdown
        
    Returns:
        Текст в формате HTML
    """
    if not text:
        return ""
    
    if not MARKDOWN_AVAILABLE:
        logger.warning("markdown не установлен, возвращаем текст как есть")
        return text
    
    try:
        # Используем markdown с расширениями для лучшей поддержки
        md = markdown.Markdown(extensions=['extra', 'codehilite', 'nl2br'])
        html = md.convert(text)
        return html
    except Exception as e:
        logger.error(f"Ошибка преобразования markdown в HTML: {e}")
        # В случае ошибки возвращаем исходный текст
        return text


def strip_markdown(text: str) -> str:
    """
    Удаляет Markdown разметку из текста, оставляя только чистый текст
    
    Args:
        text: Текст с Markdown разметкой
        
    Returns:
        Текст без Markdown разметки
    """
    if not text:
        return ""
    
    try:
        # Удаляем заголовки (# ## ### и т.д.)
        text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)
        
        # Удаляем жирный текст (**text** или __text__)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        
        # Удаляем курсив (*text* или _text_)
        text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', text)
        text = re.sub(r'(?<!_)_([^_]+)_(?!_)', r'\1', text)
        
        # Удаляем зачеркнутый текст (~~text~~)
        text = re.sub(r'~~([^~]+)~~', r'\1', text)
        
        # Удаляем ссылки [text](url) -> text
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        
        # Удаляем изображения ![alt](url) -> alt
        text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)
        
        # Удаляем inline код `code` -> code
        text = re.sub(r'`([^`]+)`', r'\1', text)
        
        # Удаляем блоки кода ```language\ncode\n```
        text = re.sub(r'```[\w]*\n[\s\S]*?```', '', text)
        
        # Удаляем списки (-, *, +, 1.)
        text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)
        
        # Удаляем цитаты (> text)
        text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
        
        # Удаляем горизонтальные линии (---, ***, ___)
        text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)
        
        # Удаляем таблицы (| col1 | col2 |)
        text = re.sub(r'\|[^|]+\|', '', text)
        
        # Удаляем лишние пробелы и переносы строк
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()
        
        return text
    except Exception as e:
        logger.error(f"Ошибка удаления markdown разметки: {e}")
        # В случае ошибки возвращаем исходный текст
        return text

