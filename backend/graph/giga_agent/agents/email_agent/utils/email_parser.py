"""
Утилиты для парсинга писем
"""

import email
from email.header import decode_header
from typing import Dict, List, Optional, Tuple
import base64


def decode_mime_words(s: str) -> str:
    """
    Декодирование MIME заголовков
    
    Args:
        s: Строка для декодирования
    
    Returns:
        Декодированная строка
    """
    if not s:
        return ""
    
    decoded_parts = decode_header(s)
    decoded_str = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            if encoding:
                decoded_str += part.decode(encoding, errors='ignore')
            else:
                decoded_str += part.decode('utf-8', errors='ignore')
        else:
            decoded_str += part
    
    return decoded_str


def get_email_text(msg: email.message.EmailMessage) -> Tuple[str, str]:
    """
    Извлечение текста и HTML из письма
    
    Args:
        msg: Объект письма
    
    Returns:
        Кортеж (текст, html)
    """
    text_content = ""
    html_content = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            # Пропускаем вложения
            if "attachment" in content_disposition:
                continue
            
            payload = part.get_payload(decode=True)
            if payload:
                try:
                    charset = part.get_content_charset() or 'utf-8'
                    decoded = payload.decode(charset, errors='ignore')
                    
                    if content_type == "text/plain":
                        text_content += decoded
                    elif content_type == "text/html":
                        html_content += decoded
                except Exception as e:
                    # Если не удалось декодировать, пробуем utf-8
                    try:
                        decoded = payload.decode('utf-8', errors='ignore')
                        if content_type == "text/plain":
                            text_content += decoded
                        elif content_type == "text/html":
                            html_content += decoded
                    except:
                        pass
    else:
        # Простое письмо
        payload = msg.get_payload(decode=True)
        if payload:
            try:
                charset = msg.get_content_charset() or 'utf-8'
                decoded = payload.decode(charset, errors='ignore')
                content_type = msg.get_content_type()
                
                if content_type == "text/plain":
                    text_content = decoded
                elif content_type == "text/html":
                    html_content = decoded
            except Exception as e:
                try:
                    decoded = payload.decode('utf-8', errors='ignore')
                    content_type = msg.get_content_type()
                    if content_type == "text/plain":
                        text_content = decoded
                    elif content_type == "text/html":
                        html_content = decoded
                except:
                    pass
    
    return text_content, html_content


def get_email_attachments(msg: email.message.EmailMessage) -> List[Dict]:
    """
    Извлечение вложений из письма
    
    Args:
        msg: Объект письма
    
    Returns:
        Список словарей с информацией о вложениях
    """
    attachments = []
    
    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            
            if "attachment" in content_disposition:
                filename = part.get_filename()
                if filename:
                    filename = decode_mime_words(filename)
                    payload = part.get_payload(decode=True)
                    
                    attachments.append({
                        "filename": filename,
                        "content_type": part.get_content_type(),
                        "size": len(payload) if payload else 0,
                        "data": payload
                    })
    
    return attachments


def parse_email_message(msg: email.message.EmailMessage) -> Dict:
    """
    Парсинг письма в структурированный формат
    
    Args:
        msg: Объект письма
    
    Returns:
        Словарь с информацией о письме
    """
    # Декодируем заголовки
    subject = decode_mime_words(msg.get("Subject", ""))
    from_addr = decode_mime_words(msg.get("From", ""))
    to_addr = decode_mime_words(msg.get("To", ""))
    cc_addr = decode_mime_words(msg.get("Cc", ""))
    date = msg.get("Date", "")
    message_id = msg.get("Message-ID", "")
    
    # Извлекаем текст и HTML
    text_content, html_content = get_email_text(msg)
    
    # Извлекаем вложения
    attachments = get_email_attachments(msg)
    
    return {
        "subject": subject,
        "from": from_addr,
        "to": to_addr,
        "cc": cc_addr,
        "date": date,
        "message_id": message_id,
        "text": text_content,
        "html": html_content,
        "attachments": [
            {
                "filename": att["filename"],
                "content_type": att["content_type"],
                "size": att["size"]
            }
            for att in attachments
        ],
        "has_attachments": len(attachments) > 0,
        "attachment_count": len(attachments)
    }


def check_keywords_in_email(msg: email.message.EmailMessage, keywords: List[str]) -> bool:
    """
    Проверка наличия ключевых слов в письме
    
    Args:
        msg: Объект письма
        keywords: Список ключевых слов для поиска
    
    Returns:
        True если найдено хотя бы одно ключевое слово
    """
    # Проверяем тему
    subject = msg.get("Subject", "").lower()
    for keyword in keywords:
        if keyword.lower() in subject:
            return True
    
    # Проверяем тело письма
    text_content, _ = get_email_text(msg)
    text_lower = text_content.lower()
    
    for keyword in keywords:
        if keyword.lower() in text_lower:
            return True
    
    return False


def check_white_emails(msg: email.message.EmailMessage, white_emails: List[str]) -> bool:
    """
    Проверка отправителя по белому списку
    
    Args:
        msg: Объект письма
        white_emails: Список email адресов белого списка
    
    Returns:
        True если отправитель в белом списке
    """
    from_addr = msg.get("From", "").lower()
    
    for white_email in white_emails:
        if white_email.lower() in from_addr:
            return True
    
    return False


def check_black_keywords(msg: email.message.EmailMessage, black_keywords: List[str]) -> bool:
    """
    Проверка наличия ключевых слов из черного списка в теме
    
    Args:
        msg: Объект письма
        black_keywords: Список ключевых слов черного списка
    
    Returns:
        True если найдено ключевое слово из черного списка
    """
    subject = msg.get("Subject", "").lower()
    
    for keyword in black_keywords:
        if keyword.lower() in subject:
            return True
    
    return False

