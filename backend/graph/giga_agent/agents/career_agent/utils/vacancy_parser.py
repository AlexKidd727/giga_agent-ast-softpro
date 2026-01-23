"""
Парсер вакансий с сайтов поиска работы
"""

import logging
from typing import Dict, List, Optional
import re

logger = logging.getLogger(__name__)


class VacancyParser:
    """Парсер для извлечения информации о вакансиях"""
    
    def __init__(self):
        pass
    
    def parse_vacancy_from_text(self, vacancy_text: str, source_url: Optional[str] = None) -> Dict:
        """
        Парсит информацию о вакансии из текста
        
        Args:
            vacancy_text: Текст описания вакансии
            source_url: URL вакансии
        
        Returns:
            Словарь с информацией о вакансии
        """
        try:
            result = {
                "title": self._extract_title(vacancy_text),
                "description": vacancy_text,
                "requirements": self._extract_requirements(vacancy_text),
                "skills": self._extract_skills(vacancy_text),
                "salary": self._extract_salary(vacancy_text),
                "experience": self._extract_experience_requirement(vacancy_text),
                "location": self._extract_location(vacancy_text),
                "employment_type": self._extract_employment_type(vacancy_text),
                "source_url": source_url or ""
            }
            
            logger.info(f"Вакансия успешно распарсена: {result['title']}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка парсинга вакансии: {e}")
            return {"error": str(e)}
    
    def _extract_title(self, text: str) -> str:
        """Извлекает заголовок вакансии"""
        # Ищем заголовок в начале текста (обычно первая строка или в тегах h1-h3)
        lines = text.split('\n')
        for line in lines[:5]:  # Проверяем первые 5 строк
            line = line.strip()
            if line and len(line) < 200:  # Заголовок обычно не очень длинный
                # Убираем лишние символы
                line = re.sub(r'^[#*\-]+\s*', '', line)
                if line:
                    return line[:200]
        
        return "Вакансия"
    
    def _extract_requirements(self, text: str) -> str:
        """Извлекает требования"""
        requirements_keywords = [
            'требования', 'requirements', 'требуется', 'необходимо',
            'обязательно', 'должен', 'должны', 'нужно'
        ]
        
        text_lower = text.lower()
        for keyword in requirements_keywords:
            pattern = rf'{keyword}[:\s]*([^\n]+(?:\n[^\n]+)*?)(?=\n\s*\n|\n[A-ZА-Я]|$)'
            match = re.search(pattern, text_lower, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip()
        
        # Если не нашли секцию, возвращаем весь текст
        return text[:1000]
    
    def _extract_skills(self, text: str) -> List[str]:
        """Извлекает требуемые навыки"""
        skills = []
        text_lower = text.lower()
        
        # Популярные технологии
        tech_keywords = [
            'python', 'java', 'javascript', 'typescript', 'react', 'vue', 'angular',
            'node.js', 'django', 'flask', 'fastapi', 'postgresql', 'mysql', 'mongodb',
            'docker', 'kubernetes', 'aws', 'azure', 'git', 'linux', 'sql', 'html', 'css',
            'c++', 'c#', 'go', 'rust', 'php', 'ruby', 'swift', 'kotlin'
        ]
        
        for tech in tech_keywords:
            pattern = r'\b' + re.escape(tech.lower()) + r'\b'
            if re.search(pattern, text_lower):
                skills.append(tech)
        
        return list(set(skills))
    
    def _extract_salary(self, text: str) -> Dict:
        """Извлекает информацию о зарплате"""
        salary_info = {}
        text_lower = text.lower()
        
        # Паттерны для зарплаты
        salary_patterns = [
            r'(\d+[\s,.]?\d*)\s*[-–—]?\s*(\d+[\s,.]?\d*)?\s*(руб|₽|rub|usd|\$|долл|eur|€|евро)',
            r'от\s*(\d+[\s,.]?\d*)\s*(руб|₽|rub|usd|\$|долл|eur|€|евро)',
            r'до\s*(\d+[\s,.]?\d*)\s*(руб|₽|rub|usd|\$|долл|eur|€|евро)',
        ]
        
        for pattern in salary_patterns:
            match = re.search(pattern, text_lower)
            if match:
                groups = match.groups()
                if len(groups) >= 2:
                    salary_info["min"] = groups[0].replace(' ', '').replace(',', '')
                    if groups[1] and groups[1].isdigit():
                        salary_info["max"] = groups[1].replace(' ', '').replace(',', '')
                    if len(groups) >= 3:
                        currency = groups[-1]
                        if 'руб' in currency or '₽' in currency or 'rub' in currency:
                            salary_info["currency"] = "RUB"
                        elif 'usd' in currency or '$' in currency or 'долл' in currency:
                            salary_info["currency"] = "USD"
                        elif 'eur' in currency or '€' in currency or 'евро' in currency:
                            salary_info["currency"] = "EUR"
                    break
        
        return salary_info
    
    def _extract_experience_requirement(self, text: str) -> str:
        """Извлекает требования к опыту"""
        text_lower = text.lower()
        
        experience_patterns = [
            r'опыт\s+работы\s+(\d+)\s*(год|лет|года)',
            r'(\d+)\s*(год|лет|года)\s+опыта',
            r'без\s+опыта',
            r'junior|middle|senior|lead',
        ]
        
        for pattern in experience_patterns:
            match = re.search(pattern, text_lower)
            if match:
                return match.group(0)
        
        return ""
    
    def _extract_location(self, text: str) -> str:
        """Извлекает локацию"""
        # Популярные города
        cities = [
            'москва', 'санкт-петербург', 'спб', 'новосибирск', 'екатеринбург',
            'казань', 'нижний новгород', 'челябинск', 'самара', 'омск',
            'ростов-на-дону', 'уфа', 'красноярск', 'воронеж', 'пермь'
        ]
        
        text_lower = text.lower()
        for city in cities:
            if city in text_lower:
                return city.capitalize()
        
        return ""
    
    def _extract_employment_type(self, text: str) -> str:
        """Извлекает тип занятости"""
        text_lower = text.lower()
        
        if 'удален' in text_lower or 'remote' in text_lower or 'home office' in text_lower:
            return "remote"
        elif 'офис' in text_lower or 'очно' in text_lower:
            return "office"
        elif 'гибрид' in text_lower or 'hybrid' in text_lower:
            return "hybrid"
        
        return ""

