"""
Граф карьерного агента
"""

import logging
from typing import Annotated, Optional, Literal
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langgraph.constants import START, END
from langgraph.graph import StateGraph

from giga_agent.agents.career_agent.config import CareerAgentState
from giga_agent.agents.career_agent.prompts import CAREER_AGENT_PROMPT
from giga_agent.agents.career_agent.nodes.analyze_resume import analyze_resume_node
from giga_agent.agents.career_agent.nodes.search_vacancies import search_vacancies_node
from giga_agent.agents.career_agent.nodes.match_skills import match_skills_node
from giga_agent.agents.career_agent.nodes.improve_resume import improve_resume_node
from giga_agent.agents.career_agent.nodes.qualification_plan import create_qualification_plan_node
from giga_agent.agents.career_agent.nodes.request_auth import request_auth_node
from giga_agent.utils.request_normalizer import normalize_request

logger = logging.getLogger(__name__)

async def entry_node(state: CareerAgentState):
    """
    Входной узел графа.
    
    Примечание:
    Раньше граф всегда стартовал с analyze_resume, из-за чего запросы вроде
    "авторизуй на hh.ru" или "найди вакансии" сначала пытались анализировать
    "резюме" и могли приводить к лишним действиям/ошибкам и повторным попыткам
    на уровне основного агента.
    
    Этот узел ничего не делает — только позволяет применить router к исходному
    сообщению пользователя (HumanMessage) до выполнения тяжелых узлов.
    """
    return state


def router(state: CareerAgentState) -> str:
    """Маршрутизация на основе запроса пользователя"""
    messages = state.get("messages", [])
    if not messages:
        return "__end__"
    
    last_message = messages[-1]
    user_request = last_message.content if hasattr(last_message, 'content') else str(last_message)
    user_request_lower = user_request.lower()
    
    # Определяем, какую функцию нужно выполнить
    
    # КРИТИЧЕСКИ ВАЖНО: Обработка запросов на авторизацию
    if any(keyword in user_request_lower for keyword in [
        "авторизуй", "авторизация", "войди", "вход", "login", "авторизуйся",
        "зайди на сайт", "открой сайт", "войди на сайт", "авторизуй на сайте"
    ]):
        # Если запрос на авторизацию, используем request_auth_node
        # который использует телефон из секретов пользователя и запрашивает код через сообщение
        return "request_auth"
    
    if any(keyword in user_request_lower for keyword in ["проанализируй резюме", "анализ резюме", "изучи резюме"]):
        if "резюме" in user_request_lower and not any(kw in user_request_lower for kw in ["улучш", "план", "поиск", "ваканс"]):
            return "analyze_resume"
    
    if any(keyword in user_request_lower for keyword in ["найди вакансии", "поиск вакансий", "вакансии", "найти работу"]):
        return "search_vacancies"
    
    if any(keyword in user_request_lower for keyword in ["отклик", "откликнуться", "отправить отклик", "подать заявку"]):
        # Отклики требуют авторизации, используем search_vacancies для проверки и авторизации
        return "search_vacancies"
    
    if any(keyword in user_request_lower for keyword in ["сопоставь навыки", "сравни навыки", "соответствие навыков"]):
        # Примечание: сопоставление требует резюме; если его еще нет — сначала анализируем.
        if not state.get("resume_data"):
            return "analyze_resume"
        return "match_skills"
    
    if any(keyword in user_request_lower for keyword in ["улучши резюме", "улучшение резюме", "рекомендации по резюме"]):
        # Примечание: улучшение требует резюме; если его еще нет — сначала анализируем.
        if not state.get("resume_data"):
            return "analyze_resume"
        return "improve_resume"
    
    if any(keyword in user_request_lower for keyword in ["план повышения", "план обучения", "план развития", "квалификация"]):
        # Примечание: план обычно строится от резюме; если его еще нет — сначала анализируем.
        if not state.get("resume_data"):
            return "analyze_resume"
        return "qualification_plan"
    
    # По умолчанию анализируем резюме, если его еще нет
    if not state.get("resume_data"):
        return "analyze_resume"
    
    return "__end__"


# Создание графа
workflow = StateGraph(CareerAgentState)

# Добавляем узлы
workflow.add_node("entry", entry_node)
workflow.add_node("analyze_resume", analyze_resume_node)
workflow.add_node("request_auth", request_auth_node)
workflow.add_node("search_vacancies", search_vacancies_node)
workflow.add_node("match_skills", match_skills_node)
workflow.add_node("improve_resume", improve_resume_node)
workflow.add_node("qualification_plan", create_qualification_plan_node)

# Добавляем ребра
workflow.add_edge(START, "entry")
workflow.add_conditional_edges(
    "entry",
    router,
    {
        "analyze_resume": "analyze_resume",
        "request_auth": "request_auth",
        "search_vacancies": "search_vacancies",
        "match_skills": "match_skills",
        "improve_resume": "improve_resume",
        "qualification_plan": "qualification_plan",
        "__end__": END
    }
)
workflow.add_conditional_edges(
    "analyze_resume",
    router,
    {
        "analyze_resume": "analyze_resume",
        "request_auth": "request_auth",
        "search_vacancies": "search_vacancies",
        "match_skills": "match_skills",
        "improve_resume": "improve_resume",
        "qualification_plan": "qualification_plan",
        "__end__": END
    }
)
workflow.add_conditional_edges(
    "request_auth",
    router,
    {
        "analyze_resume": "analyze_resume",
        "request_auth": "request_auth",
        "search_vacancies": "search_vacancies",
        "match_skills": "match_skills",
        "improve_resume": "improve_resume",
        "qualification_plan": "qualification_plan",
        "__end__": END
    }
)
workflow.add_conditional_edges(
    "search_vacancies",
    router,
    {
        "analyze_resume": "analyze_resume",
        "search_vacancies": "search_vacancies",
        "match_skills": "match_skills",
        "improve_resume": "improve_resume",
        "qualification_plan": "qualification_plan",
        "__end__": END
    }
)
workflow.add_conditional_edges(
    "match_skills",
    router,
    {
        "analyze_resume": "analyze_resume",
        "search_vacancies": "search_vacancies",
        "match_skills": "match_skills",
        "improve_resume": "improve_resume",
        "qualification_plan": "qualification_plan",
        "__end__": END
    }
)
workflow.add_conditional_edges(
    "improve_resume",
    router,
    {
        "analyze_resume": "analyze_resume",
        "search_vacancies": "search_vacancies",
        "match_skills": "match_skills",
        "improve_resume": "improve_resume",
        "qualification_plan": "qualification_plan",
        "__end__": END
    }
)
workflow.add_conditional_edges(
    "qualification_plan",
    router,
    {
        "analyze_resume": "analyze_resume",
        "search_vacancies": "search_vacancies",
        "match_skills": "match_skills",
        "improve_resume": "improve_resume",
        "qualification_plan": "qualification_plan",
        "__end__": END
    }
)

# Компилируем граф
graph = workflow.compile()


@tool(parse_docstring=True)
async def career_agent(
    user_request: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Карьерный помощник (Career Assistant) - специализированный агент для помощи в трудоустройстве.
    
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Параметр называется user_request (НЕ query, НЕ task_type, НЕ action)!
    Всегда передавай запрос пользователя в параметр user_request.
    
    ПРАВИЛЬНЫЙ ФОРМАТ ВЫЗОВА:
    career_agent(user_request="проанализируй мое резюме")
    career_agent(user_request="найди вакансии Python разработчика на hh.ru")
    career_agent(user_request="авторизуй на hh.ru")
    
    НЕПРАВИЛЬНО (НЕ ДЕЛАЙ ТАК):
    ❌ career_agent(query="проанализируй резюме") - параметр query не существует!
    ❌ career_agent(action="analyze_resume") - параметр action не существует!
    
    КРИТИЧЕСКИ ВАЖНО: Используй этот агент для ВСЕХ запросов, связанных с карьерой, трудоустройством, резюме, вакансиями и собеседованиями!
    
    Основные функции:
    1. АВТОРИЗАЦИЯ НА САЙТАХ ПОИСКА РАБОТЫ:
       - Авторизация на hh.ru, Работа.ру, Avito Работа, getmatch.ru и других сайтах
       - Открытие страницы входа в отдельном окне браузера
       - Ожидание ручной авторизации пользователя
       - Сохранение сессии для последующих запросов
       Примеры: "авторизуй на hh.ru", "войди на сайт Работа.ру", "используй карьерного помощника для авторизации"
    
    2. АНАЛИЗ РЕЗЮМЕ:
       - Изучение резюме пользователя (PDF, DOCX, TXT или текст)
       - Извлечение ключевой информации: навыки, опыт, образование, контакты
       - Оценка сильных и слабых сторон резюме
       Примеры: "проанализируй мое резюме", "изучи мое резюме", "анализ резюме"
    
    3. ПОИСК ВАКАНСИЙ:
       - Подбор вакансий на выбранных сайтах (hh.ru, Работа.ру, Avito Работа, LinkedIn и др.)
       - Фильтрация по критериям: должность, зарплата, опыт, локация
       - Анализ релевантности вакансий
       - Автоматическая авторизация при необходимости
       Примеры: "найди вакансии Python разработчика на hh.ru", "подбери вакансии на Работа.ру", "поиск работы"
    
    4. ОТПРАВКА ОТКЛИКОВ:
       - Отправка откликов на найденные вакансии
       - Загрузка резюме при необходимости
       - Отслеживание статуса откликов
       Примеры: "откликнись на вакансию", "подай заявку", "отправь отклик"
    
    5. СОПОСТАВЛЕНИЕ НАВЫКОВ:
       - Сравнение навыков из резюме с требованиями вакансии
       - Расчет процента соответствия
       - Выявление недостающих навыков
       - Рекомендации по улучшению соответствия
       Примеры: "сопоставь мои навыки с вакансией", "проверь соответствие резюме вакансии"
    
    6. УЛУЧШЕНИЕ РЕЗЮМЕ:
       - Рекомендации по улучшению резюме под конкретную вакансию
       - Предложения по формулировкам
       - Оптимизация ключевых слов
       - Улучшение структуры и оформления
       Примеры: "улучши мое резюме", "оптимизируй резюме под вакансию"
    
    7. ПЛАН ПОВЫШЕНИЯ КВАЛИФИКАЦИИ:
       - Составление индивидуального плана развития под выбранную вакансию
       - Определение недостающих навыков
       - Рекомендации по обучению (курсы, книги, практика)
       - Оценка времени на освоение навыков
       - Приоритизация навыков для изучения
       Примеры: "составь план обучения", "что нужно изучить для вакансии", "план повышения квалификации"
    
    ВАЖНО:
    - Для работы с сайтами поиска работы ОБЯЗАТЕЛЬНО требуется авторизация!
    - Агент автоматически выполнит авторизацию через browser_task, если это необходимо
    - Все данные сохраняются с привязкой к user_id для изоляции между пользователями
    
    Args:
        user_request: Запрос пользователя с описанием задачи (может включать ссылки на вакансии, упоминания о собеседованиях и т.д.)
        user_id: Идентификатор пользователя (обязателен для сохранения данных)
    """
    
    logger.info(f"[CAREER_AGENT] Вызван: user_request='{user_request}', user_id={user_id}")
    
    # Нормализуем запрос: преобразуем неточные запросы в точные и понятные
    normalized_request, normalization_metadata = normalize_request("career", user_request)
    if normalization_metadata.get("normalized", False):
        logger.info(f"[CAREER_AGENT] Запрос нормализован: '{user_request}' -> '{normalized_request}'")
        user_request = normalized_request
    
    try:
        # Инициализируем state если он None
        if state is None:
            state = {}
        
        # КРИТИЧЕСКИ ВАЖНО: Проверяем запрос на авторизацию
        # Авторизация теперь обрабатывается через request_auth_node без прерываний
        
        # КРИТИЧЕСКИ ВАЖНО: Проверяем и нормализуем user_id
        # Пытаемся получить user_id из state (который уже должен быть установлен в before_agent)
        if not user_id or user_id in ["default_user", "anonymous", "guest", ""]:
            # 1. Пытаемся получить из state (приоритетный источник - state уже содержит нормализованный user_id из сессии)
            user_id = state.get("user_id")
            logger.info(f"[CAREER_AGENT] user_id из state: {user_id}")
            
            # 2. Если не найден в state, пытаемся получить из Redis по thread_id
            if (not user_id or user_id in ["default_user", "anonymous", "guest", ""]) and state:
                thread_id = state.get("thread_id")
                if not thread_id:
                    # Пытаемся извлечь thread_id из config, если он передан через InjectedState
                    # (в некоторых случаях thread_id может быть в config, а не в state)
                    pass
                
                if thread_id:
                    try:
                        from giga_agent.utils.redis_cache import get_user_id_from_session_by_thread
                        cached_user_id = await get_user_id_from_session_by_thread(thread_id)
                        if cached_user_id:
                            user_id = cached_user_id
                            logger.info(f"[CAREER_AGENT] user_id={user_id} получен из Redis для thread_id={thread_id}")
                    except Exception as e:
                        logger.warning(f"[CAREER_AGENT] Ошибка при получении user_id из Redis: {e}")
            
            # 3. Нормализуем user_id (убираем невалидные значения)
            if user_id:
                from giga_agent.utils.user_tokens import _normalize_user_id
                user_id_before = user_id
                user_id = _normalize_user_id(user_id)
                if user_id != user_id_before:
                    logger.info(f"[CAREER_AGENT] user_id нормализован: {user_id_before} → {user_id}")
            
            # 4. Если user_id все еще невалидный и это не запрос на авторизацию
            # (запросы на авторизацию уже обработаны выше)
            if not user_id or user_id in ["default_user", "anonymous", "guest", ""]:
                logger.warning(f"[CAREER_AGENT] Невалидный user_id: {user_id}. Требуется аутентификация.")
                return {
                    "status": "error",
                    "message": "Ошибка: требуется аутентификация пользователя. Укажите валидный user_id."
                }
        
        # Импортируем HumanMessage
        from langchain_core.messages import HumanMessage
        
        # Загружаем данные пользователя из БД, если их нет в state
        from giga_agent.agents.career_agent.utils.storage import storage
        
        # Загружаем резюме из БД, если его нет в state
        resume_data = state.get("resume_data")
        if not resume_data:
            resume_data = storage.get_user_resume(user_id)
        
        # Загружаем последние вакансии из БД, если их нет в state
        search_results = state.get("search_results")
        if not search_results:
            user_vacancies = storage.get_user_vacancies(user_id)
            if user_vacancies:
                search_results = user_vacancies[-5:]  # Последние 5 вакансий
        
        # Загружаем секреты из основного state или из БД
        secrets = state.get("secrets", []) if state else []
        if not secrets and user_id:
            try:
                from giga_agent.utils.user_tokens import get_all_user_secrets
                secrets = await get_all_user_secrets(user_id)
                logger.info(f"[CAREER_AGENT] Загружено {len(secrets)} секретов для user_id={user_id}")
            except Exception as e:
                logger.warning(f"[CAREER_AGENT] Ошибка при загрузке секретов: {e}")
        
        # Формируем начальное состояние
        initial_state: CareerAgentState = {
            "messages": [HumanMessage(content=user_request)],
            "user_id": user_id,  # КРИТИЧЕСКИ ВАЖНО: Всегда передаем валидный user_id
            "resume_data": resume_data,
            "current_vacancy": state.get("current_vacancy") if state else None,
            "search_results": search_results,
            "skill_match_result": state.get("skill_match_result") if state else None,
            "improvement_plan": state.get("improvement_plan") if state else None,
            "qualification_plan": state.get("qualification_plan") if state else None,
            "secrets": secrets,  # Передаем секреты для авторизации
            "auth_waiting_for_code": state.get("auth_waiting_for_code", False) if state else False,
            "auth_session_id": state.get("auth_session_id") if state else None
        }
        
        # Запускаем граф
        # ВАЖНО: Прерывания из подграфа должны обрабатываться основным графом
        # Используем astream для поддержки прерываний
        result_state = None
        config = {"recursion_limit": 50}  # Увеличиваем лимит рекурсии для обработки прерываний
        
        async for event in graph.astream(initial_state, config=config):
            # Собираем последнее состояние из каждого события
            for node_name, node_state in event.items():
                result_state = node_state
                # Проверяем наличие прерывания
                if "__interrupt__" in node_state:
                    interrupt_data = node_state.get("__interrupt__")
                    logger.info(f"[CAREER_AGENT] Обнаружено прерывание в узле {node_name}: {interrupt_data}")
                    # Прерывание будет обработано основным графом через поток
                    # Не прерываем выполнение, продолжаем собирать состояние
        
        # Если result_state все еще None, используем начальное состояние
        if result_state is None:
            result_state = initial_state
        
        # Извлекаем последнее сообщение
        messages = result_state.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, 'content'):
                response_text = last_message.content
            else:
                response_text = str(last_message)
        else:
            response_text = "Задача выполнена"
        
        logger.info(f"[CAREER_AGENT] Завершен успешно")
        
        return {
            "status": "success",
            "message": response_text,
            "resume_data": result_state.get("resume_data"),
            "search_results": result_state.get("search_results"),
            "skill_match_result": result_state.get("skill_match_result"),
            "improvement_plan": result_state.get("improvement_plan"),
            "qualification_plan": result_state.get("qualification_plan")
        }
        
    except Exception as e:
        error_msg = f"Ошибка в карьерном агенте: {e}"
        logger.error(f"[CAREER_AGENT] {error_msg}")
        return {
            "status": "error",
            "message": error_msg
        }

