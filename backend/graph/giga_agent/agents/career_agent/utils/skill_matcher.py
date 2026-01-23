"""
Сопоставление навыков из резюме с требованиями вакансии
"""

import logging
from typing import Dict, List, Tuple
import re

logger = logging.getLogger(__name__)


class SkillMatcher:
    """Класс для сопоставления навыков"""
    
    def __init__(self):
        # Словарь синонимов и вариантов написания навыков
        self.skill_synonyms = {
            'python': ['python', 'питон', 'python3', 'python 3'],
            'javascript': ['javascript', 'js', 'ecmascript', 'node.js', 'nodejs'],
            'java': ['java', 'java ee', 'java se'],
            'react': ['react', 'react.js', 'reactjs'],
            'vue': ['vue', 'vue.js', 'vuejs'],
            'angular': ['angular', 'angular.js', 'angularjs'],
            'sql': ['sql', 'mysql', 'postgresql', 'postgres', 'oracle', 'mssql'],
            'docker': ['docker', 'docker-compose', 'docker compose'],
            'kubernetes': ['kubernetes', 'k8s', 'kube'],
            'git': ['git', 'github', 'gitlab', 'bitbucket'],
            'linux': ['linux', 'unix', 'ubuntu', 'debian', 'centos'],
            'aws': ['aws', 'amazon web services', 'amazon aws'],
            'azure': ['azure', 'microsoft azure'],
            'html': ['html', 'html5'],
            'css': ['css', 'css3', 'scss', 'sass', 'less'],
        }
    
    def match_skills(
        self,
        resume_skills: List[str],
        vacancy_requirements: str
    ) -> Dict:
        """
        Сопоставляет навыки из резюме с требованиями вакансии
        
        Args:
            resume_skills: Список навыков из резюме
            vacancy_requirements: Текст требований вакансии
        
        Returns:
            Словарь с результатами сопоставления
        """
        try:
            # Извлекаем требуемые навыки из описания вакансии
            required_skills = self._extract_skills_from_text(vacancy_requirements)
            
            # Нормализуем навыки
            normalized_resume_skills = self._normalize_skills(resume_skills)
            normalized_required_skills = self._normalize_skills(required_skills)
            
            # Находим совпадения
            matched_skills = []
            missing_skills = []
            
            for req_skill in normalized_required_skills:
                found = False
                for res_skill in normalized_resume_skills:
                    if self._skills_match(req_skill, res_skill):
                        matched_skills.append({
                            "required": req_skill,
                            "resume": res_skill,
                            "match_type": "exact" if req_skill.lower() == res_skill.lower() else "synonym"
                        })
                        found = True
                        break
                
                if not found:
                    missing_skills.append(req_skill)
            
            # Находим дополнительные навыки в резюме
            additional_skills = []
            for res_skill in normalized_resume_skills:
                found = False
                for req_skill in normalized_required_skills:
                    if self._skills_match(req_skill, res_skill):
                        found = True
                        break
                if not found:
                    additional_skills.append(res_skill)
            
            # Рассчитываем процент соответствия
            match_percentage = self._calculate_match_percentage(
                len(matched_skills),
                len(normalized_required_skills)
            )
            
            result = {
                "match_percentage": match_percentage,
                "matched_skills": matched_skills,
                "missing_skills": missing_skills,
                "additional_skills": additional_skills,
                "total_required": len(normalized_required_skills),
                "total_matched": len(matched_skills),
                "total_missing": len(missing_skills),
                "recommendations": self._generate_recommendations(matched_skills, missing_skills)
            }
            
            logger.info(f"Сопоставление навыков завершено. Соответствие: {match_percentage}%")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка сопоставления навыков: {e}")
            return {"error": str(e)}
    
    def _extract_skills_from_text(self, text: str) -> List[str]:
        """Извлекает навыки из текста требований"""
        skills = []
        text_lower = text.lower()
        
        # Популярные технологии и навыки
        all_skills = []
        for skill, synonyms in self.skill_synonyms.items():
            all_skills.extend(synonyms)
        
        # Ищем упоминания навыков в тексте
        for skill in all_skills:
            # Ищем слово целиком (не часть другого слова)
            pattern = r'\b' + re.escape(skill.lower()) + r'\b'
            if re.search(pattern, text_lower):
                # Добавляем основной вариант навыка
                main_skill = next(k for k, v in self.skill_synonyms.items() if skill in v)
                if main_skill not in skills:
                    skills.append(main_skill)
        
        # Также ищем общие паттерны (например, "знание Python", "опыт работы с React")
        skill_patterns = [
            r'знание\s+([a-zа-я]+)',
            r'опыт\s+работы\s+с\s+([a-zа-я]+)',
            r'владение\s+([a-zа-я]+)',
            r'([a-zа-я]+)\s+разработка',
        ]
        
        for pattern in skill_patterns:
            matches = re.findall(pattern, text_lower)
            for match in matches:
                if len(match) > 2 and match not in skills:
                    skills.append(match)
        
        return skills
    
    def _normalize_skills(self, skills: List[str]) -> List[str]:
        """Нормализует навыки (приводит к единому виду)"""
        normalized = []
        for skill in skills:
            skill_lower = skill.lower().strip()
            # Ищем в словаре синонимов
            found = False
            for main_skill, synonyms in self.skill_synonyms.items():
                if skill_lower in synonyms or skill_lower == main_skill:
                    if main_skill not in normalized:
                        normalized.append(main_skill)
                    found = True
                    break
            
            if not found:
                # Добавляем как есть, если не нашли в словаре
                if skill_lower not in normalized:
                    normalized.append(skill_lower)
        
        return normalized
    
    def _skills_match(self, skill1: str, skill2: str) -> bool:
        """Проверяет, совпадают ли навыки (с учетом синонимов)"""
        skill1_lower = skill1.lower()
        skill2_lower = skill2.lower()
        
        # Точное совпадение
        if skill1_lower == skill2_lower:
            return True
        
        # Проверка через словарь синонимов
        for main_skill, synonyms in self.skill_synonyms.items():
            if skill1_lower in synonyms and skill2_lower in synonyms:
                return True
            if skill1_lower == main_skill and skill2_lower in synonyms:
                return True
            if skill2_lower == main_skill and skill1_lower in synonyms:
                return True
        
        # Частичное совпадение (одно слово содержит другое)
        if skill1_lower in skill2_lower or skill2_lower in skill1_lower:
            return True
        
        return False
    
    def _calculate_match_percentage(self, matched: int, total: int) -> int:
        """Рассчитывает процент соответствия"""
        if total == 0:
            return 100
        return int((matched / total) * 100)
    
    def _generate_recommendations(
        self,
        matched_skills: List[Dict],
        missing_skills: List[str]
    ) -> List[str]:
        """Генерирует рекомендации на основе сопоставления"""
        recommendations = []
        
        if missing_skills:
            recommendations.append(
                f"Рекомендуется изучить следующие навыки: {', '.join(missing_skills[:5])}"
            )
        
        if len(matched_skills) > 0:
            recommendations.append(
                f"У вас есть {len(matched_skills)} совпадающих навыков из требуемых"
            )
        
        if len(missing_skills) > len(matched_skills):
            recommendations.append(
                "Рекомендуется сосредоточиться на изучении недостающих навыков перед откликом"
            )
        
        return recommendations

