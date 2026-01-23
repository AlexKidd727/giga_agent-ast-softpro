"""
Парсер резюме (PDF, DOCX, TXT)
"""

import logging
import re
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


class ResumeParser:
    """Парсер для извлечения информации из резюме"""
    
    def __init__(self):
        self.skills_keywords = [
            'навыки', 'skills', 'компетенции', 'умения', 'технологии',
            'технологический стек', 'tech stack', 'технологии и инструменты'
        ]
        self.experience_keywords = [
            'опыт работы', 'experience', 'трудовой опыт', 'работа',
            'места работы', 'employment history'
        ]
        self.education_keywords = [
            'образование', 'education', 'учебные заведения', 'вуз',
            'университет', 'институт'
        ]
    
    async def parse_resume(
        self,
        resume_text: Optional[str] = None,
        resume_file_path: Optional[str] = None
    ) -> Dict:
        """
        Парсит резюме из текста или файла
        
        Args:
            resume_text: Текст резюме
            resume_file_path: Путь к файлу резюме (PDF, DOCX, TXT)
        
        Returns:
            Словарь с извлеченной информацией
        """
        try:
            # Если передан путь к файлу, читаем его
            if resume_file_path:
                text = await self._read_file(resume_file_path)
            elif resume_text:
                text = resume_text
            else:
                return {"error": "Не указан текст резюме или путь к файлу"}
            
            # Извлекаем информацию
            result = {
                "skills": self._extract_skills(text),
                "experience": self._extract_experience(text),
                "education": self._extract_education(text),
                "contacts": self._extract_contacts(text),
                "summary": self._extract_summary(text),
                "languages": self._extract_languages(text),
                "certifications": self._extract_certifications(text),
                "raw_text": text
            }
            
            logger.info(f"Резюме успешно распарсено. Найдено навыков: {len(result['skills'])}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка парсинга резюме: {e}")
            return {"error": str(e)}
    
    async def _read_file(self, file_path: str) -> str:
        """Читает файл резюме используя инструмент read_document"""
        path = Path(file_path)
        
        # Используем универсальный инструмент для чтения документов
        try:
            from giga_agent.tools.document_reader import read_document
            
            # Вызываем инструмент напрямую (он async функция)
            result = await read_document(file_path=str(path))
            
            # Проверяем, не вернулась ли ошибка
            if isinstance(result, str) and (result.startswith("Ошибка") or result.startswith("Не удалось")):
                logger.error(f"Ошибка чтения файла через read_document: {result}")
                raise ValueError(result)
            
            return result
        except ImportError:
            # Fallback на старый способ, если инструмент недоступен
            logger.warning("Инструмент read_document недоступен, используем fallback")
            if path.suffix.lower() == '.txt':
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                raise ValueError(f"Неподдерживаемый формат файла: {path.suffix}. Используйте read_document инструмент.")
    
    def _extract_skills(self, text: str) -> List[str]:
        """Извлекает навыки из текста"""
        skills = []
        text_lower = text.lower()
        
        # Ищем секцию с навыками
        for keyword in self.skills_keywords:
            pattern = rf'{keyword}[:\s]*([^\n]+(?:\n[^\n]+)*?)(?=\n\s*\n|\n[A-ZА-Я]|$)'
            match = re.search(pattern, text_lower, re.IGNORECASE | re.MULTILINE)
            if match:
                skills_text = match.group(1)
                # Разбиваем на отдельные навыки
                skills_list = re.split(r'[,;•\-\n]', skills_text)
                skills.extend([s.strip() for s in skills_list if s.strip() and len(s.strip()) > 2])
                break
        
        # Если не нашли секцию, ищем упоминания технологий в тексте
        if not skills:
            # Популярные технологии
            tech_keywords = [
                'python', 'java', 'javascript', 'typescript', 'react', 'vue', 'angular',
                'node.js', 'django', 'flask', 'fastapi', 'postgresql', 'mysql', 'mongodb',
                'docker', 'kubernetes', 'aws', 'azure', 'git', 'linux', 'sql', 'html', 'css'
            ]
            for tech in tech_keywords:
                if tech.lower() in text_lower:
                    skills.append(tech)
        
        return list(set(skills))  # Убираем дубликаты
    
    def _extract_experience(self, text: str) -> List[Dict]:
        """Извлекает опыт работы"""
        experience = []
        text_lower = text.lower()
        
        # Ищем секцию с опытом
        for keyword in self.experience_keywords:
            pattern = rf'{keyword}[:\s]*([^\n]+(?:\n[^\n]+)*?)(?=\n\s*\n|\n[A-ZА-Я]|$)'
            match = re.search(pattern, text_lower, re.IGNORECASE | re.MULTILINE)
            if match:
                exp_text = match.group(1)
                # Пытаемся найти периоды работы
                date_pattern = r'(\d{4}|\d{2}\.\d{4})[-\s]+(\d{4}|\d{2}\.\d{4}|настоящее время|н\.в\.|по\s+настоящее)'
                dates = re.findall(date_pattern, exp_text, re.IGNORECASE)
                if dates:
                    experience.append({
                        "period": dates[0],
                        "description": exp_text[:500]  # Первые 500 символов
                    })
                break
        
        return experience
    
    def _extract_education(self, text: str) -> List[Dict]:
        """Извлекает образование"""
        education = []
        text_lower = text.lower()
        
        # Ищем секцию с образованием
        for keyword in self.education_keywords:
            pattern = rf'{keyword}[:\s]*([^\n]+(?:\n[^\n]+)*?)(?=\n\s*\n|\n[A-ZА-Я]|$)'
            match = re.search(pattern, text_lower, re.IGNORECASE | re.MULTILINE)
            if match:
                edu_text = match.group(1)
                education.append({
                    "description": edu_text[:500]
                })
                break
        
        return education
    
    def _extract_contacts(self, text: str) -> Dict:
        """Извлекает контактную информацию"""
        contacts = {}
        
        # Email
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        email_match = re.search(email_pattern, text)
        if email_match:
            contacts["email"] = email_match.group(0)
        
        # Телефон
        phone_pattern = r'(\+7|8)?[\s\-]?\(?(\d{3})\)?[\s\-]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})'
        phone_match = re.search(phone_pattern, text)
        if phone_match:
            contacts["phone"] = phone_match.group(0)
        
        # Telegram
        telegram_pattern = r'@?[a-zA-Z0-9_]{5,32}'
        telegram_match = re.search(rf'telegram[:\s]*{telegram_pattern}', text, re.IGNORECASE)
        if telegram_match:
            contacts["telegram"] = telegram_match.group(0)
        
        return contacts
    
    def _extract_summary(self, text: str) -> str:
        """Извлекает краткое описание (summary/about)"""
        summary_keywords = ['о себе', 'about', 'summary', 'краткая информация', 'профиль']
        
        for keyword in summary_keywords:
            pattern = rf'{keyword}[:\s]*([^\n]+(?:\n[^\n]+)*?)(?=\n\s*\n|\n[A-ZА-Я]|$)'
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip()[:500]
        
        # Если не нашли, берем первые 300 символов
        return text[:300].strip()
    
    def _extract_languages(self, text: str) -> List[str]:
        """Извлекает языки"""
        languages = []
        text_lower = text.lower()
        
        language_keywords = ['языки', 'languages', 'владение языками']
        for keyword in language_keywords:
            pattern = rf'{keyword}[:\s]*([^\n]+)'
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                lang_text = match.group(1)
                # Популярные языки
                common_languages = ['русский', 'english', 'английский', 'немецкий', 'французский', 'испанский']
                for lang in common_languages:
                    if lang.lower() in lang_text:
                        languages.append(lang)
                break
        
        return languages
    
    def _extract_certifications(self, text: str) -> List[str]:
        """Извлекает сертификаты"""
        certifications = []
        text_lower = text.lower()
        
        cert_keywords = ['сертификат', 'certificate', 'certification', 'сертификация']
        for keyword in cert_keywords:
            pattern = rf'{keyword}[:\s]*([^\n]+)'
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                cert_text = match.group(1)
                certifications.append(cert_text.strip())
        
        return certifications

