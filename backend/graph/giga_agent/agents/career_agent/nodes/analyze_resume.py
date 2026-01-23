"""
Узел для анализа резюме
"""

import logging
from typing import Dict
from langchain_core.messages import AIMessage

from giga_agent.agents.career_agent.config import CareerAgentState
from giga_agent.agents.career_agent.utils.resume_parser import ResumeParser
from giga_agent.agents.career_agent.utils.storage import storage

logger = logging.getLogger(__name__)


async def analyze_resume_node(state: CareerAgentState) -> Dict:
    """
    Анализирует резюме пользователя
    
    Извлекает информацию о навыках, опыте, образовании и т.д.
    ВАЖНО: Все данные сохраняются с привязкой к user_id для изоляции между пользователями.
    """
    try:
        messages = state.get("messages", [])
        if not messages:
            return state
        
        # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из state
        user_id = state.get("user_id")
        if not user_id or user_id in ["default_user", "anonymous", "guest"]:
            return {
                "messages": [AIMessage(
                    content="Ошибка: не указан user_id. Анализ резюме требует аутентификации пользователя."
                )]
            }
        
        # Получаем последнее сообщение пользователя
        last_message = messages[-1]
        user_request = last_message.content if hasattr(last_message, 'content') else str(last_message)
        
        # Инициализируем парсер
        parser = ResumeParser()
        
        # Пытаемся найти путь к файлу резюме в запросе или в state
        resume_file_path = None
        resume_text = None
        
        # Проверяем, есть ли в запросе упоминание файла
        if "файл" in user_request.lower() or "резюме" in user_request.lower():
            # В реальной реализации здесь бы была логика получения файла из вложений
            # Пока используем текст из запроса
            resume_text = user_request
        
        # Если нет явного указания, пытаемся использовать текст как резюме
        if not resume_text and not resume_file_path:
            resume_text = user_request
        
        # Парсим резюме
        resume_data = await parser.parse_resume(
            resume_text=resume_text,
            resume_file_path=resume_file_path
        )
        
        if "error" in resume_data:
            error_msg = f"Ошибка анализа резюме: {resume_data['error']}"
            logger.error(error_msg)
            return {
                "messages": [AIMessage(content=error_msg)]
            }
        
        # КРИТИЧЕСКИ ВАЖНО: Сохраняем резюме в БД с привязкой к user_id
        storage.save_user_resume(user_id, resume_data)
        logger.info(f"💾 Резюме сохранено в БД для пользователя {user_id}")
        
        # Формируем ответ
        skills_count = len(resume_data.get("skills", []))
        experience_count = len(resume_data.get("experience", []))
        education_count = len(resume_data.get("education", []))
        
        analysis_text = f"""**Анализ резюме завершен**

**Найдено:**
- Навыков: {skills_count}
- Мест работы: {experience_count}
- Образовательных учреждений: {education_count}

**Навыки:**
{', '.join(resume_data.get('skills', [])[:10])}{'...' if len(resume_data.get('skills', [])) > 10 else ''}

**Краткое описание:**
{resume_data.get('summary', 'Не указано')[:200]}

**Контактная информация:**
{', '.join([f"{k}: {v}" for k, v in resume_data.get('contacts', {}).items()]) if resume_data.get('contacts') else 'Не указано'}

Резюме успешно проанализировано и сохранено для дальнейшей работы."""
        
        logger.info(f"Резюме проанализировано для пользователя {user_id}. Навыков: {skills_count}")
        
        return {
            "messages": [AIMessage(content=analysis_text)],
            "resume_data": resume_data
        }
        
    except Exception as e:
        error_msg = f"Ошибка при анализе резюме: {e}"
        logger.error(error_msg)
        return {
            "messages": [AIMessage(content=error_msg)]
        }

