"""
Узел для составления плана повышения квалификации
"""

import logging
from typing import Dict, List
from langchain_core.messages import AIMessage

from giga_agent.agents.career_agent.config import CareerAgentState
from giga_agent.agents.career_agent.utils.storage import storage

logger = logging.getLogger(__name__)


async def create_qualification_plan_node(state: CareerAgentState) -> Dict:
    """
    Составляет индивидуальный план повышения квалификации под выбранную вакансию
    
    ВАЖНО: Использует резюме и результаты сопоставления, сохраненные в БД с привязкой к user_id.
    """
    try:
        # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из state
        user_id = state.get("user_id")
        if not user_id or user_id in ["default_user", "anonymous", "guest"]:
            return {
                "messages": [AIMessage(
                    content="Ошибка: не указан user_id. Составление плана повышения квалификации требует аутентификации пользователя."
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
        
        # Получаем результат сопоставления навыков
        skill_match_result = state.get("skill_match_result")
        if not skill_match_result:
            return {
                "messages": [AIMessage(
                    content="Для составления плана повышения квалификации необходимо сначала выполнить сопоставление навыков с вакансией."
                )]
            }
        
        missing_skills = skill_match_result.get("missing_skills", [])
        if not missing_skills:
            return {
                "messages": [AIMessage(
                    content="Отлично! У вас есть все необходимые навыки для этой вакансии. "
                           "Рекомендуется сосредоточиться на углублении существующих знаний."
                )]
            }
        
        # Формируем план обучения для каждого недостающего навыка
        learning_plan = []
        
        for skill in missing_skills[:10]:  # Ограничиваем 10 навыками
            skill_plan = _create_skill_learning_plan(skill)
            learning_plan.append(skill_plan)
        
        # Формируем ответ
        result_text = f"""**План повышения квалификации**

**Недостающие навыки для изучения: {len(missing_skills)}**

"""
        
        for i, plan in enumerate(learning_plan, 1):
            result_text += f"**{i}. {plan['skill']}**\n"
            result_text += f"   Приоритет: {plan['priority']}\n"
            result_text += f"   Оценка времени: {plan['estimated_time']}\n"
            result_text += f"   Рекомендации:\n"
            for rec in plan['recommendations']:
                result_text += f"   - {rec}\n"
            result_text += "\n"
        
        result_text += "\n**Общие рекомендации:**\n"
        result_text += "- Начните с навыков высокого приоритета\n"
        result_text += "- Практикуйтесь на реальных проектах\n"
        result_text += "- Отслеживайте прогресс и обновляйте резюме по мере освоения навыков\n"
        result_text += "- Рассмотрите возможность получения сертификатов для подтверждения навыков"
        
        logger.info(f"План повышения квалификации создан для {len(missing_skills)} навыков")
        
        return {
            "messages": [AIMessage(content=result_text)],
            "qualification_plan": {
                "skills": learning_plan,
                "total_skills": len(missing_skills),
                "created_at": ""
            }
        }
        
    except Exception as e:
        error_msg = f"Ошибка при составлении плана повышения квалификации: {e}"
        logger.error(error_msg)
        return {
            "messages": [AIMessage(content=error_msg)]
        }


def _create_skill_learning_plan(skill: str) -> Dict:
    """Создает план обучения для конкретного навыка"""
    skill_lower = skill.lower()
    
    # Определяем приоритет и время обучения на основе навыка
    priority = "Средний"
    estimated_time = "2-4 недели"
    
    # Популярные технологии и их планы обучения
    learning_resources = {
        'python': {
            'priority': 'Высокий',
            'time': '3-6 недель',
            'courses': ['Python для начинающих', 'Django/Flask для веб-разработки'],
            'practice': 'Создайте несколько проектов: веб-приложение, API, скрипты автоматизации',
            'books': ['"Изучаем Python" Марк Лутц', '"Автоматизация рутинных задач с помощью Python"']
        },
        'javascript': {
            'priority': 'Высокий',
            'time': '4-8 недель',
            'courses': ['JavaScript основы', 'React/Vue для фронтенда', 'Node.js для бэкенда'],
            'practice': 'Создайте интерактивные веб-приложения, используйте фреймворки',
            'books': ['"Вы не знаете JS" Кайл Симпсон']
        },
        'docker': {
            'priority': 'Средний',
            'time': '1-2 недели',
            'courses': ['Docker основы', 'Docker Compose'],
            'practice': 'Контейнеризуйте существующие приложения',
            'books': ['"Docker и Kubernetes" Джеймс Тернбулл']
        },
        'kubernetes': {
            'priority': 'Средний',
            'time': '3-4 недели',
            'courses': ['Kubernetes основы', 'Kubernetes для разработчиков'],
            'practice': 'Разверните приложение в Kubernetes кластере',
            'books': ['"Kubernetes в действии" Марко Лукша']
        },
        'aws': {
            'priority': 'Средний',
            'time': '4-6 недель',
            'courses': ['AWS Certified Solutions Architect', 'AWS для разработчиков'],
            'practice': 'Разверните приложение на AWS, используйте различные сервисы',
            'books': ['"AWS Well-Architected Framework"']
        }
    }
    
    # Ищем подходящий план
    plan = None
    for key, value in learning_resources.items():
        if key in skill_lower:
            plan = value
            break
    
    # Если не нашли, используем общий план
    if not plan:
        plan = {
            'priority': priority,
            'time': estimated_time,
            'courses': [f'Курсы по {skill}'],
            'practice': f'Практикуйтесь в использовании {skill} на реальных проектах',
            'books': [f'Изучите документацию и книги по {skill}']
        }
    
    recommendations = [
        f"Пройдите курс: {plan['courses'][0]}" if plan['courses'] else f"Изучите основы {skill}",
        plan['practice'],
        f"Прочитайте: {plan['books'][0]}" if plan['books'] else f"Изучите документацию {skill}"
    ]
    
    return {
        "skill": skill,
        "priority": plan['priority'],
        "estimated_time": plan['time'],
        "recommendations": recommendations
    }

