"""
Утилиты для работы с сайтами поиска работы
"""

import logging
import re
from typing import Dict, Optional, List
from urllib.parse import urlencode, quote

logger = logging.getLogger(__name__)


class JobSiteConfig:
    """Конфигурация для сайтов поиска работы"""
    
    SITES = {
        "hh.ru": {
            "base_url": "https://hh.ru",
            "search_url": "https://hh.ru/search/vacancy",
            "login_url": "https://hh.ru/account/login",
            "search_params": {
                "text": "{query}",
                "area": "{area}",  # 1 - Москва, 2 - СПб
                "salary": "{salary}",
                "experience": "{experience}",  # noExperience, between1And3, between3And6, moreThan6
                "schedule": "{schedule}",  # fullDay, shift, flexible, remote, flyInFlyOut
            },
            "selectors": {
                "vacancy_card": ".vacancy-serp-item",
                "vacancy_title": ".vacancy-serp-item__title a",
                "vacancy_salary": ".vacancy-serp-item__compensation",
                "vacancy_company": ".vacancy-serp-item__meta-info-company a",
                "vacancy_description": ".vacancy-serp-item__snippet",
                "vacancy_link": ".vacancy-serp-item__title a",
            }
        },
        "rabota.ru": {
            "base_url": "https://rabota.ru",
            "search_url": "https://rabota.ru/vacancy/search",
            "login_url": "https://rabota.ru/login",
            "search_params": {
                "query": "{query}",
                "region": "{region}",
                "salary": "{salary}",
            },
            "selectors": {
                "vacancy_card": ".vacancy-preview-card",
                "vacancy_title": ".vacancy-preview-card__title a",
                "vacancy_salary": ".vacancy-preview-card__salary",
                "vacancy_company": ".vacancy-preview-card__company-name",
                "vacancy_description": ".vacancy-preview-card__description",
                "vacancy_link": ".vacancy-preview-card__title a",
            }
        },
        "avito": {
            "base_url": "https://www.avito.ru",
            "search_url": "https://www.avito.ru/rossiya/vakansii",
            "login_url": "https://www.avito.ru/profile/login",
            "search_params": {
                "q": "{query}",
                "p": "{page}",
            },
            "selectors": {
                "vacancy_card": ".item",
                "vacancy_title": ".item-title a",
                "vacancy_salary": ".item-price",
                "vacancy_company": ".item-company",
                "vacancy_description": ".item-description",
                "vacancy_link": ".item-title a",
            }
        },
        "getmatch.ru": {
            "base_url": "https://getmatch.ru",
            "search_url": "https://getmatch.ru/vacancies",
            "login_url": "https://getmatch.ru/login",
            "search_params": {
                "q": "{query}",
            },
            "selectors": {
                "vacancy_card": ".vacancy-card",
                "vacancy_title": ".vacancy-card__title a",
                "vacancy_salary": ".vacancy-card__salary",
                "vacancy_company": ".vacancy-card__company",
                "vacancy_description": ".vacancy-card__description",
                "vacancy_link": ".vacancy-card__title a",
            }
        }
    }
    
    @classmethod
    def get_site_config(cls, site_name: str) -> Optional[Dict]:
        """Получает конфигурацию для сайта"""
        # Нормализуем имя сайта
        site_name_lower = site_name.lower()
        for key, config in cls.SITES.items():
            if key in site_name_lower or site_name_lower in key:
                return config
        return None
    
    @classmethod
    def build_search_url(cls, site_name: str, query: str, **kwargs) -> Optional[str]:
        """Строит URL для поиска вакансий"""
        config = cls.get_site_config(site_name)
        if not config:
            return None
        
        search_url = config["search_url"]
        params = {}
        
        # Заполняем параметры поиска
        for param_key, param_template in config["search_params"].items():
            param_value = kwargs.get(param_key.replace("{", "").replace("}", ""))
            if param_value:
                params[param_key] = param_template.format(**kwargs, query=query)
            else:
                # Если значение не указано, используем шаблон с query
                params[param_key] = param_template.format(query=query, **kwargs)
        
        # Формируем URL
        if "?" in search_url:
            url = f"{search_url}&{urlencode(params)}"
        else:
            url = f"{search_url}?{urlencode(params)}"
        
        return url


def parse_search_request(request: str) -> Dict:
    """
    Парсит запрос пользователя для извлечения параметров поиска
    
    Примеры:
    - "найди вакансии Python разработчика на hh.ru"
    - "поиск работы JavaScript в Москве"
    - "вакансии Java разработчика с зарплатой от 200000"
    """
    params = {
        "query": "",
        "site": None,
        "area": None,
        "salary": None,
        "experience": None,
        "schedule": None,
    }
    
    request_lower = request.lower()
    
    # Извлекаем должность/запрос
    # Убираем служебные слова
    query_keywords = [
        "найди", "найти", "поиск", "ищу", "искать", "вакансии", "вакансию",
        "работу", "работы", "работа", "разработчик", "разработчика"
    ]
    
    # Извлекаем технологии/должности
    tech_keywords = {
        "python": "Python разработчик",
        "javascript": "JavaScript разработчик",
        "js": "JavaScript разработчик",
        "java": "Java разработчик",
        "php": "PHP разработчик",
        "c++": "C++ разработчик",
        "c#": "C# разработчик",
        "go": "Go разработчик",
        "rust": "Rust разработчик",
        "ruby": "Ruby разработчик",
        "swift": "Swift разработчик",
        "kotlin": "Kotlin разработчик",
        "react": "React разработчик",
        "vue": "Vue.js разработчик",
        "angular": "Angular разработчик",
        "node": "Node.js разработчик",
        "backend": "Backend разработчик",
        "frontend": "Frontend разработчик",
        "fullstack": "Fullstack разработчик",
        "devops": "DevOps инженер",
        "qa": "QA инженер",
        "тестировщик": "QA инженер",
        "аналитик": "Аналитик",
        "менеджер": "Менеджер проектов",
    }
    
    found_query = None
    for keyword, position in tech_keywords.items():
        if keyword in request_lower:
            found_query = position
            break
    
    if not found_query:
        # Пытаемся извлечь запрос вручную
        # Ищем слова после "вакансии" или "найти"
        for keyword in ["вакансии", "найти", "найди", "ищу"]:
            if keyword in request_lower:
                idx = request_lower.find(keyword)
                # Берем следующие 3-5 слов
                words = request_lower[idx:].split()[:5]
                # Убираем служебные слова
                query_words = [w for w in words if w not in query_keywords and w not in ["на", "в", "с", "от", "до"]]
                if query_words:
                    found_query = " ".join(query_words).capitalize()
                    break
    
    params["query"] = found_query or "разработчик"
    
    # Извлекаем сайт
    if "hh.ru" in request_lower or "headhunter" in request_lower:
        params["site"] = "hh.ru"
    elif "rabota.ru" in request_lower or "работа.ру" in request_lower:
        params["site"] = "rabota.ru"
    elif "avito" in request_lower:
        params["site"] = "avito"
    elif "getmatch" in request_lower or "getmatch.ru" in request_lower:
        params["site"] = "getmatch.ru"
    else:
        # По умолчанию используем hh.ru
        params["site"] = "hh.ru"
    
    # Извлекаем локацию
    if "москв" in request_lower or "мск" in request_lower:
        params["area"] = "1"  # Москва для hh.ru
        params["region"] = "moscow"
    elif "спб" in request_lower or "питер" in request_lower or "санкт-петербург" in request_lower:
        params["area"] = "2"  # СПб для hh.ru
        params["region"] = "spb"
    elif "удален" in request_lower or "remote" in request_lower:
        params["schedule"] = "remote"
    
    # Извлекаем зарплату
    salary_match = re.search(r'(?:от|from)\s*(\d+)', request_lower)
    if salary_match:
        params["salary"] = salary_match.group(1)
    
    # Извлекаем опыт
    if "без опыта" in request_lower or "no experience" in request_lower:
        params["experience"] = "noExperience"
    elif "1-3" in request_lower or "1 до 3" in request_lower:
        params["experience"] = "between1And3"
    elif "3-6" in request_lower or "3 до 6" in request_lower:
        params["experience"] = "between3And6"
    elif "более 6" in request_lower or "больше 6" in request_lower:
        params["experience"] = "moreThan6"
    
    return params


def build_browser_task_for_search(site_name: str, search_params: Dict) -> str:
    """
    Строит задачу для browser_task для поиска вакансий
    
    ВАЖНО: Для надежной работы включает:
    1. Открытие сайта
    2. Проверку необходимости входа
    3. Ожидание аутентификации пользователя (если требуется)
    4. Выполнение поиска
    5. Парсинг результатов
    
    Улучшения для надежности:
    - Явная проверка состояния аутентификации
    - Ожидание загрузки элементов
    - Обработка ошибок и повторные попытки
    - Сохранение cookies для последующих запросов
    """
    config = JobSiteConfig.get_site_config(site_name)
    if not config:
        return f"Открой сайт {site_name} и найди вакансии по запросу '{search_params.get('query', 'разработчик')}'"
    
    search_url = JobSiteConfig.build_search_url(site_name, search_params.get("query", ""), **search_params)
    query = search_params.get("query", "разработчик")
    
    task_parts = [
        f"Задача: Найти вакансии '{query}' на сайте {site_name}",
        "",
        f"ВАЖНО: Для полноценного поиска вакансий и отправки откликов на {site_name} ОБЯЗАТЕЛЬНО требуется авторизация!",
        "Без входа на сайт вы не сможете:",
        "- Видеть все доступные вакансии",
        "- Отправлять отклики на вакансии",
        "- Управлять резюме",
        "- Получать уведомления о новых вакансиях",
        "",
        "ШАГ 1: Открытие сайта",
        f"1. Открой сайт {config['base_url']}",
        "2. Подожди полной загрузки страницы (минимум 3 секунды)",
        "3. Проверь, не требуется ли подтверждение капчи",
        "",
        "ШАГ 2: Проверка и выполнение аутентификации (КРИТИЧЕСКИ ВАЖНО!)",
        "1. Проверь наличие элементов входа/регистрации на странице",
        "2. Если видишь кнопки 'Войти', 'Вход', 'Login', 'Войти в личный кабинет' или форму входа:",
        "   - Это означает, что требуется аутентификация",
        "   - ЗНАЧИТ: НУЖНО ВОЙТИ НА САЙТ!",
        "   - Открой страницу входа в НОВОМ окне/вкладке браузера",
        "   - URL страницы входа: " + config.get("login_url", config["base_url"] + "/login"),
        f"   - Сообщи пользователю: 'Пожалуйста, авторизуйтесь на сайте {site_name} в открытом окне браузера'",
        "   - Подожди, пока пользователь авторизуется вручную (введет логин/email и пароль)",
        "   - Подожди 5-10 секунд после того, как пользователь нажал кнопку входа",
        "   - Проверь успешность входа по следующим признакам:",
        "     * Исчезла форма входа",
        "     * Появилась информация о пользователе (имя, аватар, email)",
        "     * Появилась кнопка 'Выйти' или 'Logout'",
        "     * URL изменился на главную страницу или личный кабинет",
        "     * В меню появились пункты 'Мои отклики', 'Мои резюме' и т.д.",
        "   - Если вход успешен, вернись на основную страницу",
        "   - Сохрани cookies и информацию о сессии для последующих запросов",
        "3. Если вход не требуется (уже авторизован), переходи к следующему шагу",
        "",
        "ШАГ 3: Переход к поиску",
        f"1. Перейди на страницу поиска: {search_url}",
        "2. Подожди загрузки страницы (минимум 3 секунды)",
        "3. Если перенаправило на страницу входа, вернись к ШАГУ 2",
        "",
        "ШАГ 4: Выполнение поиска",
        f"1. Найди поле поиска на странице",
        f"2. Введи запрос: '{query}'",
        "3. Нажми кнопку поиска или Enter",
        "4. Подожди загрузки результатов (минимум 5 секунд)",
        "5. Прокрути страницу вниз, чтобы загрузить все результаты",
        "",
        "ШАГ 5: Извлечение информации о вакансиях",
        "Для каждой найденной вакансии извлеки:",
        "  - Название вакансии (текст ссылки или заголовка)",
        "  - Зарплата (если указана, в формате: от X до Y или X-Y)",
        "  - Название компании",
        "  - Краткое описание (первые 200-300 символов)",
        "  - Полная ссылка на вакансию (href атрибут)",
        "",
        "ШАГ 6: Сохранение результатов",
        "1. Сохрани все найденные вакансии в формате JSON:",
        "   {",
        '     "vacancies": [',
        "       {",
        '         "title": "Название вакансии",',
        '         "salary": {"min": "150000", "max": "200000", "currency": "RUB"},',
        '         "company": "Название компании",',
        '         "description": "Описание вакансии",',
        '         "source_url": "https://..."',
        "       }",
        "     ]",
        "   }",
        "2. Если есть пагинация, перейди на следующую страницу (максимум 3 страницы)",
        "3. Повтори извлечение для следующих страниц",
        "",
        "ВАЖНО:",
        "- Если возникла ошибка, опиши её подробно",
        "- Если требуется капча, сообщи об этом",
        "- Если сайт требует JavaScript, убедись что он включен",
        "- Сохраняй cookies для последующих запросов",
    ]
    
    return "\n".join(task_parts)


def build_browser_task_for_auth(site_name: str) -> str:
    """
    Строит задачу для browser_task для аутентификации на сайте
    
    ВАЖНО: Открывает отдельное окно для входа, чтобы пользователь мог авторизоваться
    
    Улучшения для надежности:
    - Явная проверка успешности входа
    - Ожидание загрузки элементов
    - Обработка различных форм входа
    - Сохранение сессии
    """
    config = JobSiteConfig.get_site_config(site_name)
    if not config:
        return f"Открой сайт {site_name} и войди в аккаунт"
    
    login_url = config.get("login_url", config["base_url"])
    
    task_parts = [
        f"Задача: Авторизация на сайте {site_name}",
        "",
        "ЗАЧЕМ НУЖНА АВТОРИЗАЦИЯ:",
        f"Авторизация на {site_name} необходима для:",
        "- Полноценного поиска вакансий (без входа доступны только ограниченные результаты)",
        "- Отправки откликов на вакансии (без входа отклики невозможны)",
        "- Управления резюме (загрузка, редактирование, публикация)",
        "- Просмотра детальной информации о вакансиях",
        "- Получения уведомлений о новых подходящих вакансиях",
        "- Отслеживания статуса откликов",
        "",
        "ШАГ 1: Открытие страницы входа",
        f"1. Открой сайт {site_name} в НОВОМ окне/вкладке браузера",
        f"2. Перейди на страницу входа: {login_url}",
        "3. Подожди полной загрузки страницы (минимум 3 секунды)",
        "4. Проверь, что форма входа видна на странице",
        "",
        "ШАГ 2: Ожидание авторизации пользователя",
        f"1. Сообщи пользователю: 'Пожалуйста, авторизуйтесь на сайте {site_name} в открытом окне браузера'",
        "2. Объясни пользователю, что нужно:",
        "   - Ввести логин/email в поле для входа",
        "   - Ввести пароль в поле для пароля",
        "   - Нажать кнопку 'Войти', 'Login' или 'Войти в личный кабинет'",
        "   - Пройти двухфакторную аутентификацию (если требуется)",
        "   - Решить капчу (если требуется)",
        "3. Подожди, пока пользователь выполнит все эти действия",
        "4. НЕ закрывай окно браузера до завершения авторизации!",
        "",
        "ШАГ 3: Проверка успешности входа",
        "1. Подожди 5-10 секунд после нажатия кнопки входа",
        "2. Внимательно проверь признаки успешного входа:",
        "   - Исчезла форма входа",
        "   - Появилась информация о пользователе (имя, аватар, email)",
        "   - Появилась кнопка 'Выйти' или 'Logout' в правом верхнем углу",
        "   - URL изменился на главную страницу или личный кабинет",
        "   - В меню появились пункты 'Мои отклики', 'Мои резюме', 'Профиль' и т.д.",
        "   - В правом верхнем углу появился аватар или имя пользователя",
        "3. Если ВСЕ эти признаки присутствуют - вход успешен!",
        "4. Если вход успешен:",
        "   - Сохрани cookies и информацию о сессии",
        f"   - Сообщи: 'Авторизация на {site_name} выполнена успешно!'",
        "   - Вернись на основную страницу",
        "5. Если вход не удался:",
        "   - Проверь наличие сообщения об ошибке на странице",
        "   - Сообщи пользователю об ошибке и её причине",
        "   - Предложи повторить попытку или проверить учетные данные",
        "",
        "ВАЖНО:",
        "- НЕ закрывай окно браузера до завершения авторизации",
        "- Сохраняй ВСЕ cookies для последующих запросов",
        "- Если требуется капча, дождись её решения пользователем",
        "- Если требуется подтверждение email/SMS, дождись его",
        "- Если требуется двухфакторная аутентификация, дождись ввода кода",
        "- После успешной авторизации сессия будет сохранена для будущих запросов",
    ]
    
    return "\n".join(task_parts)

