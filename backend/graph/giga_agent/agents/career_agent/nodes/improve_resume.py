"""
Узел для улучшения резюме
"""

import logging
from typing import Dict
from langchain_core.messages import AIMessage

from giga_agent.agents.career_agent.config import CareerAgentState
from giga_agent.agents.career_agent.utils.storage import storage

logger = logging.getLogger(__name__)


async def improve_resume_node(state: CareerAgentState) -> Dict:
    """
    Генерирует рекомендации по улучшению резюме под конкретную вакансию
    
    ВАЖНО: Использует резюме и вакансии, сохраненные в БД с привязкой к user_id.
    """
    try:
        # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из state
        user_id = state.get("user_id")
        if not user_id or user_id in ["default_user", "anonymous", "guest"]:
            return {
                "messages": [AIMessage(
                    content="Ошибка: не указан user_id. Улучшение резюме требует аутентификации пользователя."
                )]
            }
        
        # Получаем данные резюме из state или из БД
        resume_data = state.get("resume_data")
        if not resume_data:
            resume_data = storage.get_user_resume(user_id)
            if not resume_data:
                return {
                    "messages": [AIMessage(
                        content="Сначала необходимо проанализировать резюме. Используйте команду 'проанализируй резюме'"
                    )]
                }
        
        # Получаем текущую вакансию
        current_vacancy = state.get("current_vacancy")
        skill_match_result = state.get("skill_match_result")
        
        if not current_vacancy and not skill_match_result:
            return {
                "messages": [AIMessage(
                    content="Для улучшения резюме необходимо сначала выполнить сопоставление навыков с вакансией."
                )]
            }
        
        # Формируем рекомендации на основе сопоставления
        recommendations = []
        
        if skill_match_result:
            missing_skills = skill_match_result.get("missing_skills", [])
            if missing_skills:
                recommendations.append(
                    f"**Добавить навыки:** Рекомендуется добавить в резюме следующие навыки: "
                    f"{', '.join(missing_skills[:5])}"
                )
        
        # Общие рекомендации
        recommendations.extend([
            "**Оптимизация ключевых слов:** Используйте ключевые слова из описания вакансии в резюме",
            "**Структура:** Убедитесь, что резюме имеет четкую структуру: контакты, краткое описание, опыт, навыки, образование",
            "**Опыт работы:** Опишите опыт работы с акцентом на достижения и результаты, используя цифры и метрики",
            "**Краткость:** Резюме должно быть лаконичным (1-2 страницы), но информативным"
        ])
        
        # Формируем ответ
        result_text = "**Рекомендации по улучшению резюме:**\n\n"
        for i, rec in enumerate(recommendations, 1):
            result_text += f"{i}. {rec}\n"
        
        result_text += "\n**Следующие шаги:**\n"
        result_text += "1. Обновите резюме согласно рекомендациям\n"
        result_text += "2. Повторно проанализируйте резюме\n"
        result_text += "3. Выполните сопоставление навыков снова для проверки улучшения"
        
        logger.info("Рекомендации по улучшению резюме сформированы")
        
        return {
            "messages": [AIMessage(content=result_text)],
            "improvement_plan": {
                "recommendations": recommendations,
                "created_at": ""
            }
        }
        
    except Exception as e:
        error_msg = f"Ошибка при формировании рекомендаций: {e}"
        logger.error(error_msg)
        return {
            "messages": [AIMessage(content=error_msg)]
        }

