"""
Узел для поиска вакансий с интеграцией browser_task
"""

import logging
import json
from typing import Dict, Optional, List
from langchain_core.messages import AIMessage

from giga_agent.agents.career_agent.config import CareerAgentState
from giga_agent.agents.career_agent.utils.vacancy_parser import VacancyParser
from giga_agent.agents.career_agent.utils.storage import storage
from giga_agent.agents.career_agent.utils.job_sites import (
    parse_search_request,
    build_browser_task_for_search,
    build_browser_task_for_auth,
    JobSiteConfig
)
from giga_agent.agents.browser_use import browser_task

logger = logging.getLogger(__name__)


async def search_vacancies_node(state: CareerAgentState) -> Dict:
    """
    Ищет вакансии на выбранных сайтах с использованием browser_task
    
    ВАЖНО: 
    - Все найденные вакансии сохраняются с привязкой к user_id
    - Использует browser_task для реального поиска на сайтах
    - Обрабатывает аутентификацию через отдельное окно браузера
    """
    try:
        messages = state.get("messages", [])
        if not messages:
            return state
        
        # Получаем последнее сообщение пользователя
        last_message = messages[-1]
        user_request = last_message.content if hasattr(last_message, 'content') else str(last_message)
        user_request_lower = user_request.lower()
        
        # КРИТИЧЕСКИ ВАЖНО: Проверяем, является ли запрос запросом на авторизацию
        is_auth_request = any(keyword in user_request_lower for keyword in [
            "авторизуй", "авторизация", "войди", "вход", "login", "авторизуйся",
            "зайди на сайт", "открой сайт", "войди на сайт", "авторизуй на сайте"
        ])
        
        # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из state
        # Для запросов на авторизацию разрешаем работу без валидного user_id
        user_id = state.get("user_id")
        if not user_id or user_id in ["default_user", "anonymous", "guest"]:
            if is_auth_request:
                # Для авторизации используем временный user_id
                user_id = "temp_auth_user"
                logger.info(f"[SEARCH_VACANCIES] Используется временный user_id для авторизации: {user_id}")
            else:
                return {
                    "messages": [AIMessage(
                        content="Ошибка: не указан user_id. Поиск вакансий требует аутентификации пользователя."
                    )]
                }
        
        # Извлекаем параметры поиска из запроса
        search_params = parse_search_request(user_request)
        site_name = search_params.get("site", "hh.ru")
        
        # Если это запрос на авторизацию, используем специальную задачу
        if is_auth_request:
            logger.info(f"[SEARCH_VACANCIES] Запрос на авторизацию на {site_name} для пользователя {user_id}")
            
            # Строим задачу для авторизации
            browser_task_text = build_browser_task_for_auth(site_name)
            
            # Вызываем browser_task для авторизации
            try:
                browser_result = await browser_task.ainvoke(browser_task_text)
                
                if isinstance(browser_result, dict):
                    if browser_result.get("error"):
                        error_msg = browser_result.get("error", "Неизвестная ошибка")
                        return {
                            "messages": [AIMessage(
                                content=f"❌ Ошибка при авторизации на {site_name}: {error_msg}\n\n"
                                       f"Попробуйте:\n"
                                       f"1. Убедитесь, что браузер запущен\n"
                                       f"2. Проверьте подключение к интернету\n"
                                       f"3. Убедитесь, что учетные данные правильные"
                            )]
                        }
                    
                    if browser_result.get("success"):
                        return {
                            "messages": [AIMessage(
                                content=f"✅ **Авторизация на {site_name} выполнена успешно!**\n\n"
                                       f"Теперь вы можете:\n"
                                       f"- Искать вакансии\n"
                                       f"- Отправлять отклики\n"
                                       f"- Управлять резюме\n\n"
                                       f"Сессия сохранена для последующих запросов."
                            )]
                        }
                
                return {
                    "messages": [AIMessage(
                        content=f"✅ Авторизация на {site_name} завершена. Теперь можно искать вакансии и отправлять отклики."
                    )]
                }
                
            except Exception as e:
                logger.error(f"[SEARCH_VACANCIES] Ошибка при авторизации: {e}", exc_info=True)
                return {
                    "messages": [AIMessage(
                        content=f"❌ Ошибка при авторизации на {site_name}: {e}\n\n"
                               f"Проверьте, что браузер запущен и доступен."
                    )]
                }
        
        logger.info(f"[SEARCH_VACANCIES] Поиск вакансий для пользователя {user_id}: {search_params}")
        
        # Строим задачу для browser_task (включает проверку и авторизацию при необходимости)
        browser_task_text = build_browser_task_for_search(site_name, search_params)
        
        # Вызываем browser_task для поиска вакансий
        logger.info(f"[SEARCH_VACANCIES] Запуск browser_task для поиска на {site_name}")
        try:
            # browser_task принимает task как строку
            browser_result = await browser_task.ainvoke(browser_task_text)
        except Exception as e:
            logger.error(f"[SEARCH_VACANCIES] Ошибка при вызове browser_task: {e}", exc_info=True)
            browser_result = {"error": str(e)}
        
        # Обрабатываем результат browser_task
        vacancies = []
        
        if isinstance(browser_result, dict):
            if browser_result.get("error"):
                error_msg = browser_result.get("error", "Неизвестная ошибка")
                logger.error(f"[SEARCH_VACANCIES] Ошибка browser_task: {error_msg}")
                return {
                    "messages": [AIMessage(
                        content=f"Ошибка при поиске вакансий: {error_msg}\n\n"
                               f"Попробуйте:\n"
                               f"1. Убедитесь, что браузер запущен\n"
                               f"2. Проверьте подключение к интернету\n"
                               f"3. Попробуйте другой сайт поиска работы"
                    )]
                }
            
            # Если browser_task вернул успешный результат, пытаемся извлечь вакансии
            if browser_result.get("success"):
                message = browser_result.get("message", "")
                # Пытаемся извлечь вакансии из сообщения или результата
                # В реальной реализации browser_task должен возвращать структурированные данные
                vacancies = _extract_vacancies_from_browser_result(browser_result, site_name)
        elif isinstance(browser_result, str):
            # Если результат - строка, пытаемся извлечь вакансии из текста
            vacancies = _extract_vacancies_from_text(browser_result, site_name)
        
        # Если вакансии не найдены через browser_task, используем fallback
        if not vacancies:
            logger.warning(f"[SEARCH_VACANCIES] Вакансии не найдены через browser_task, используем fallback")
            # Fallback: используем get_urls для получения информации о вакансиях
            from giga_agent.tools.scraper import get_urls
            
            search_url = JobSiteConfig.build_search_url(site_name, search_params.get("query", ""), **search_params)
            if search_url:
                try:
                    urls_result = await get_urls.ainvoke({"urls": [search_url]})
                    if isinstance(urls_result, dict) and "data" in urls_result:
                        data = urls_result["data"]
                        if isinstance(data, dict) and "results" in data:
                            results = data["results"]
                            if isinstance(results, list):
                                # Извлекаем вакансии из результатов
                                vacancies = _extract_vacancies_from_urls_results(results, site_name)
                except Exception as e:
                    logger.error(f"[SEARCH_VACANCIES] Ошибка при использовании get_urls: {e}")
        
        # Если вакансии все еще не найдены, возвращаем инструкцию
        if not vacancies:
            return {
                "messages": [AIMessage(
                    content=f"**Поиск вакансий на {site_name}**\n\n"
                           f"Запрос: {search_params.get('query', 'разработчик')}\n\n"
                           f"Для поиска вакансий:\n"
                           f"1. Откройте сайт {site_name} в браузере\n"
                           f"2. Войдите в аккаунт (если требуется)\n"
                           f"3. Выполните поиск по запросу: '{search_params.get('query', 'разработчик')}'\n"
                           f"4. Сообщите мне о найденных вакансиях или скопируйте ссылки на них\n\n"
                           f"Или попробуйте другой сайт поиска работы."
                )]
            }
        
        # Парсим каждую вакансию
        parser = VacancyParser()
        parsed_vacancies = []
        for vacancy in vacancies:
            try:
                parsed = parser.parse_vacancy_from_text(
                    vacancy.get("description", ""),
                    vacancy.get("source_url", "")
                )
                parsed["title"] = vacancy.get("title", parsed.get("title", "Вакансия"))
                parsed["source_url"] = vacancy.get("source_url", parsed.get("source_url", ""))
                
                # КРИТИЧЕСКИ ВАЖНО: Сохраняем вакансию в БД с привязкой к user_id
                vacancy_id = storage.save_user_vacancy(user_id, parsed)
                parsed["id"] = vacancy_id
                parsed_vacancies.append(parsed)
            except Exception as e:
                logger.error(f"[SEARCH_VACANCIES] Ошибка парсинга вакансии: {e}")
                continue
        
        # Формируем ответ
        result_text = f"**Найдено вакансий: {len(parsed_vacancies)}**\n\n"
        for i, vacancy in enumerate(parsed_vacancies[:10], 1):  # Показываем первые 10
            result_text += f"{i}. **{vacancy.get('title', 'Вакансия')}**\n"
            if vacancy.get('salary'):
                salary_info = vacancy['salary']
                if salary_info.get('min'):
                    result_text += f"   💰 Зарплата: от {salary_info['min']} {salary_info.get('currency', 'RUB')}\n"
            if vacancy.get('company'):
                result_text += f"   🏢 Компания: {vacancy['company']}\n"
            if vacancy.get('source_url'):
                result_text += f"   🔗 [Ссылка на вакансию]({vacancy['source_url']})\n"
            if vacancy.get('description'):
                desc = vacancy['description'][:200] + "..." if len(vacancy['description']) > 200 else vacancy['description']
                result_text += f"   📝 {desc}\n"
            result_text += "\n"
        
        if len(parsed_vacancies) > 10:
            result_text += f"\n... и еще {len(parsed_vacancies) - 10} вакансий\n"
        
        logger.info(f"[SEARCH_VACANCIES] Найдено вакансий для пользователя {user_id}: {len(parsed_vacancies)}")
        
        return {
            "messages": [AIMessage(content=result_text)],
            "search_results": parsed_vacancies
        }
        
    except Exception as e:
        error_msg = f"Ошибка при поиске вакансий: {e}"
        logger.error(f"[SEARCH_VACANCIES] {error_msg}", exc_info=True)
        return {
            "messages": [AIMessage(content=error_msg)]
        }


def _extract_vacancies_from_browser_result(browser_result: Dict, site_name: str) -> List[Dict]:
    """Извлекает вакансии из результата browser_task"""
    vacancies = []
    
    # Если browser_task возвращает структурированные данные
    if "vacancies" in browser_result:
        vacancies = browser_result["vacancies"]
    elif "data" in browser_result:
        data = browser_result["data"]
        if isinstance(data, list):
            vacancies = data
        elif isinstance(data, dict) and "vacancies" in data:
            vacancies = data["vacancies"]
    
    return vacancies


def _extract_vacancies_from_text(text: str, site_name: str) -> List[Dict]:
    """Извлекает вакансии из текстового результата"""
    vacancies = []
    
    # Пытаемся найти JSON в тексте
    import re
    json_match = re.search(r'\{.*"vacancies".*\}', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            if "vacancies" in data:
                vacancies = data["vacancies"]
        except:
            pass
    
    return vacancies


def _extract_vacancies_from_urls_results(results: List[Dict], site_name: str) -> List[Dict]:
    """Извлекает вакансии из результатов get_urls"""
    vacancies = []
    
    for result in results:
        if not isinstance(result, dict):
            continue
        
        # Извлекаем информацию о вакансии из результата
        content = result.get("content", "")
        url = result.get("url", "")
        
        if not content or not url:
            continue
        
        # Пытаемся найти название вакансии в контенте
        title = None
        salary = None
        
        # Простой парсинг для hh.ru
        if "hh.ru" in site_name or "headhunter" in site_name:
            # Ищем паттерны в HTML/тексте
            import re
            title_match = re.search(r'<h[1-6][^>]*>(.*?)</h[1-6]>', content, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()
            
            salary_match = re.search(r'(\d+[\s\d]*)\s*(?:руб|RUB|₽)', content, re.IGNORECASE)
            if salary_match:
                salary = {"min": salary_match.group(1).replace(" ", ""), "currency": "RUB"}
        
        if title or url:
            vacancies.append({
                "title": title or "Вакансия",
                "description": content[:500] if content else "",
                "salary": salary,
                "source_url": url
            })
    
    return vacancies



