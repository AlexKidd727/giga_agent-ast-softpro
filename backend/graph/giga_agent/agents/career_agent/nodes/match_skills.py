"""
Узел для сопоставления навыков резюме с требованиями вакансии
"""

import logging
from typing import Dict
from langchain_core.messages import AIMessage

from giga_agent.agents.career_agent.config import CareerAgentState
from giga_agent.agents.career_agent.utils.skill_matcher import SkillMatcher
from giga_agent.agents.career_agent.utils.storage import storage

logger = logging.getLogger(__name__)


async def match_skills_node(state: CareerAgentState) -> Dict:
    """
    Сопоставляет навыки из резюме с требованиями вакансии
    
    ВАЖНО: Использует резюме и вакансии, сохраненные в БД с привязкой к user_id.
    """
    try:
        # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из state
        user_id = state.get("user_id")
        if not user_id or user_id in ["default_user", "anonymous", "guest"]:
            return {
                "messages": [AIMessage(
                    content="Ошибка: не указан user_id. Сопоставление навыков требует аутентификации пользователя."
                )]
            }
        
        # Получаем данные резюме из state или из БД
        resume_data = state.get("resume_data")
        if not resume_data:
            # Пытаемся загрузить из БД
            resume_data = storage.get_user_resume(user_id)
            if not resume_data:
                return {
                    "messages": [AIMessage(
                        content="Сначала необходимо проанализировать резюме. Используйте команду 'проанализируй резюме'"
                    )]
                }
        
        # Получаем текущую вакансию из state или из БД
        current_vacancy = state.get("current_vacancy")
        if not current_vacancy:
            # Пытаемся взять из последних результатов поиска
            search_results = state.get("search_results", [])
            if search_results:
                current_vacancy = search_results[0]
            else:
                # Пытаемся загрузить последние вакансии из БД для этого пользователя
                user_vacancies = storage.get_user_vacancies(user_id)
                if user_vacancies:
                    current_vacancy = user_vacancies[-1]  # Берем последнюю
                else:
                    return {
                        "messages": [AIMessage(
                            content="Необходимо выбрать вакансию для сопоставления. Сначала выполните поиск вакансий."
                        )]
                    }
        
        # Извлекаем навыки из резюме
        resume_skills = resume_data.get("skills", [])
        if not resume_skills:
            return {
                "messages": [AIMessage(
                    content="В резюме не найдено навыков. Убедитесь, что резюме было правильно проанализировано."
                )]
            }
        
        # Извлекаем требования из вакансии
        vacancy_requirements = ""
        if isinstance(current_vacancy, dict):
            vacancy_requirements = current_vacancy.get("requirements", "") or current_vacancy.get("description", "")
        else:
            vacancy_requirements = str(current_vacancy)
        
        if not vacancy_requirements:
            return {
                "messages": [AIMessage(
                    content="Не удалось извлечь требования из вакансии."
                )]
            }
        
        # Выполняем сопоставление
        matcher = SkillMatcher()
        match_result = matcher.match_skills(resume_skills, vacancy_requirements)
        
        if "error" in match_result:
            return {
                "messages": [AIMessage(content=f"Ошибка сопоставления: {match_result['error']}")]
            }
        
        # Формируем ответ
        match_percentage = match_result.get("match_percentage", 0)
        matched_skills = match_result.get("matched_skills", [])
        missing_skills = match_result.get("missing_skills", [])
        recommendations = match_result.get("recommendations", [])
        
        result_text = f"""**Результат сопоставления навыков**

**Процент соответствия: {match_percentage}%**

**Совпадающие навыки ({len(matched_skills)}):**
"""
        for skill in matched_skills[:10]:
            result_text += f"- {skill.get('resume', skill.get('required', ''))}\n"
        
        if missing_skills:
            result_text += f"\n**Недостающие навыки ({len(missing_skills)}):**\n"
            for skill in missing_skills[:10]:
                result_text += f"- {skill}\n"
        
        if recommendations:
            result_text += "\n**Рекомендации:**\n"
            for rec in recommendations:
                result_text += f"- {rec}\n"
        
        logger.info(f"Сопоставление навыков завершено. Соответствие: {match_percentage}%")
        
        return {
            "messages": [AIMessage(content=result_text)],
            "skill_match_result": match_result,
            "current_vacancy": current_vacancy
        }
        
    except Exception as e:
        error_msg = f"Ошибка при сопоставлении навыков: {e}"
        logger.error(error_msg)
        return {
            "messages": [AIMessage(content=error_msg)]
        }

