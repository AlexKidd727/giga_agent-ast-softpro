"""
Браузерный сервис для автоматизации браузера через WebSocket API
Поддерживает ручную авторизацию и автоматизацию действий на сайтах
Возвращает скриншоты, HTML страницы и структурированные данные (текст, таблицы, ссылки)
"""

import asyncio
import json
import logging
import os
from typing import Optional, Dict, Any, List
from urllib.parse import unquote
import re

import websockets
from websockets.exceptions import ConnectionClosed, InvalidMessage
from aiohttp import web

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Настраиваем логирование для websockets - подавляем ошибки невалидных соединений
websockets_logger = logging.getLogger("websockets.server")
websockets_logger.setLevel(logging.ERROR)  # Показываем только ERROR и выше, игнорируем WARNING/INFO/DEBUG

# Добавляем фильтр для подавления ошибок невалидных HTTP запросов
class WebSocketErrorFilter(logging.Filter):
    """Фильтр для подавления ошибок невалидных WebSocket соединений"""
    def filter(self, record):
        # Подавляем ошибки, связанные с невалидными HTTP запросами или закрытыми соединениями
        error_msg = record.getMessage()
        if any(keyword in error_msg for keyword in [
            "did not receive a valid HTTP request",
            "connection closed while reading HTTP request line",
            "line without CRLF",
            "opening handshake failed",
            "InvalidMessage"
        ]):
            return False  # Не логируем эти ошибки
        return True

websockets_logger.addFilter(WebSocketErrorFilter())

# Глобальное хранилище браузерных контекстов
browser_contexts: Dict[str, Any] = {}

# Хранилище куков для сессий
session_cookies: Dict[str, List[Dict[str, Any]]] = {}


async def install_playwright():
    """Устанавливает браузеры Playwright при первом запуске"""
    try:
        from playwright.async_api import async_playwright
        import subprocess
        import sys
        
        # Проверяем, установлены ли браузеры
        try:
            playwright = await async_playwright().start()
            await playwright.chromium.launch(headless=True)
            await playwright.stop()
            logger.info("✅ Браузеры Playwright уже установлены")
        except Exception:
            logger.info("📦 Установка браузеров Playwright...")
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                logger.info("✅ Браузеры Playwright установлены")
            else:
                logger.error(f"❌ Ошибка установки браузеров: {result.stderr}")
    except ImportError:
        logger.warning("⚠️ Playwright не установлен, будет использован fallback режим")


def parse_html_to_structured_data(html_content: str, url: str = "") -> Dict[str, Any]:
    """
    Парсит HTML в структурированный JSON формат.
    Извлекает текст, таблицы, ссылки и другую структурированную информацию.
    
    Args:
        html_content: HTML содержимое страницы
        url: URL страницы (для формирования абсолютных ссылок)
    
    Returns:
        Словарь с структурированными данными:
        {
            "text": "основной текст страницы",
            "tables": [{"headers": [...], "rows": [[...], ...]}, ...],
            "links": [{"text": "...", "url": "...", "href": "..."}, ...],
            "headings": [{"level": 1-6, "text": "..."}, ...],
            "images": [{"src": "...", "alt": "..."}, ...],
            "forms": [{"action": "...", "method": "...", "fields": [...]}, ...]
        }
    """
    try:
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Удаляем скрипты и стили
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        
        result = {
            "text": "",
            "tables": [],
            "links": [],
            "headings": [],
            "images": [],
            "forms": []
        }
        
        # Извлекаем основной текст
        text_parts = []
        for element in soup.find_all(['p', 'div', 'span', 'li', 'td', 'th']):
            text = element.get_text(strip=True)
            if text and len(text) > 3:  # Игнорируем очень короткие тексты
                text_parts.append(text)
        result["text"] = " ".join(text_parts[:1000])  # Ограничиваем размер
        
        # Извлекаем заголовки
        for i in range(1, 7):
            for heading in soup.find_all(f'h{i}'):
                text = heading.get_text(strip=True)
                if text:
                    result["headings"].append({
                        "level": i,
                        "text": text
                    })
        
        # Извлекаем таблицы
        for table in soup.find_all('table'):
            table_data = {
                "headers": [],
                "rows": []
            }
            
            # Ищем заголовки
            thead = table.find('thead')
            if thead:
                for th in thead.find_all(['th', 'td']):
                    header_text = th.get_text(strip=True)
                    if header_text:
                        table_data["headers"].append(header_text)
            else:
                # Если нет thead, берем первую строку
                first_row = table.find('tr')
                if first_row:
                    for th in first_row.find_all(['th', 'td']):
                        header_text = th.get_text(strip=True)
                        if header_text:
                            table_data["headers"].append(header_text)
            
            # Извлекаем строки данных
            tbody = table.find('tbody') or table
            for tr in tbody.find_all('tr'):
                row = []
                for td in tr.find_all(['td', 'th']):
                    cell_text = td.get_text(strip=True)
                    row.append(cell_text)
                if row:
                    table_data["rows"].append(row)
            
            if table_data["headers"] or table_data["rows"]:
                result["tables"].append(table_data)
        
        # Извлекаем ссылки
        for link in soup.find_all('a', href=True):
            link_text = link.get_text(strip=True)
            href = link.get('href', '')
            
            # Преобразуем относительные ссылки в абсолютные
            if href and not href.startswith(('http://', 'https://', 'mailto:', 'tel:', '#')):
                if url:
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
            
            if link_text or href:
                result["links"].append({
                    "text": link_text,
                    "url": href,
                    "href": link.get('href', '')
                })
        
        # Извлекаем изображения
        for img in soup.find_all('img', src=True):
            src = img.get('src', '')
            alt = img.get('alt', '')
            
            # Преобразуем относительные ссылки в абсолютные
            if src and not src.startswith(('http://', 'https://', 'data:')):
                if url:
                    from urllib.parse import urljoin
                    src = urljoin(url, src)
            
            result["images"].append({
                "src": src,
                "alt": alt
            })
        
        # Извлекаем формы
        for form in soup.find_all('form'):
            form_data = {
                "action": form.get('action', ''),
                "method": form.get('method', 'get').lower(),
                "fields": []
            }
            
            # Преобразуем относительные action в абсолютные
            if form_data["action"] and not form_data["action"].startswith(('http://', 'https://')):
                if url:
                    from urllib.parse import urljoin
                    form_data["action"] = urljoin(url, form_data["action"])
            
            # Извлекаем поля формы
            for input_field in form.find_all(['input', 'textarea', 'select']):
                field_data = {
                    "type": input_field.get('type', input_field.name),
                    "name": input_field.get('name', ''),
                    "value": input_field.get('value', ''),
                    "placeholder": input_field.get('placeholder', ''),
                    "required": input_field.has_attr('required')
                }
                
                if input_field.name == 'textarea':
                    field_data["value"] = input_field.get_text(strip=True)
                elif input_field.name == 'select':
                    options = []
                    for option in input_field.find_all('option'):
                        options.append({
                            "value": option.get('value', ''),
                            "text": option.get_text(strip=True),
                            "selected": option.has_attr('selected')
                        })
                    field_data["options"] = options
                
                form_data["fields"].append(field_data)
            
            if form_data["action"] or form_data["fields"]:
                result["forms"].append(form_data)
        
        return result
    
    except ImportError:
        logger.warning("BeautifulSoup не установлен. Установите: pip install beautifulsoup4")
        # Возвращаем базовую структуру без парсинга
        return {
            "text": re.sub(r'<[^>]+>', '', html_content)[:5000],  # Простое удаление тегов
            "tables": [],
            "links": [],
            "headings": [],
            "images": [],
            "forms": []
        }
    except Exception as e:
        logger.error(f"Ошибка при парсинге HTML: {e}", exc_info=True)
        return {
            "text": "",
            "tables": [],
            "links": [],
            "headings": [],
            "images": [],
            "forms": [],
            "error": str(e)
        }


async def execute_browser_task(task: str, session_id: str) -> Dict[str, Any]:
    """
    Выполняет задачу в браузере
    
    Args:
        task: Текст задачи для выполнения
        session_id: ID сессии для сохранения контекста браузера
    
    Returns:
        Результат выполнения задачи
    """
    try:
        from playwright.async_api import async_playwright, Browser, BrowserContext, Page
        
        logger.info(f"[{session_id}] Начало выполнения задачи: {task[:100]}...")
        
        # Получаем или создаем контекст браузера для сессии
        if session_id not in browser_contexts:
            playwright = await async_playwright().start()
            # Определяем режим работы браузера
            # В Docker ОБЯЗАТЕЛЬНО используем headless режим (нет X server)
            # Для ручной авторизации можно использовать VNC или X11 forwarding
            headless_mode = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
            
            browser = await playwright.chromium.launch(
                headless=headless_mode,  # В Docker обычно headless=True
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage'
                ]
            )
            # Получаем куки для сессии, если они есть
            cookies = session_cookies.get(session_id, [])
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            # Добавляем куки в контекст, если они есть
            if cookies:
                await context.add_cookies(cookies)
                logger.info(f"[{session_id}] Добавлено {len(cookies)} куков в контекст браузера")
            
            browser_contexts[session_id] = {
                'playwright': playwright,
                'browser': browser,
                'context': context,
                'page': None
            }
            logger.info(f"[{session_id}] Создан новый контекст браузера")
        
        session_data = browser_contexts[session_id]
        context: BrowserContext = session_data['context']
        
        # Создаем или используем существующую страницу
        if session_data['page'] is None:
            page = await context.new_page()
            session_data['page'] = page
        else:
            page: Page = session_data['page']
        
        # Парсим задачу и выполняем действия
        task_lower = task.lower()
        
        # Проверяем, является ли это задачей на авторизацию
        is_auth_task = any(keyword in task_lower for keyword in [
            "авторизуй", "авторизация", "войди", "вход", "login", "авторизуйся",
            "зайди на сайт", "открой сайт", "войди на сайт", "авторизуй на сайте"
        ])
        
        # Извлекаем URL сайта из задачи
        site_url = None
        if "hh.ru" in task_lower:
            site_url = "https://hh.ru"
        elif "работа.ру" in task_lower or "rabota.ru" in task_lower:
            site_url = "https://rabota.ru"
        elif "avito" in task_lower:
            site_url = "https://www.avito.ru"
        else:
            # Пытаемся найти URL в тексте задачи
            import re
            url_pattern = r'https?://[^\s]+'
            urls = re.findall(url_pattern, task)
            if urls:
                site_url = urls[0]
        
        if not site_url:
            return {
                "type": "error",
                "message": "Не удалось определить URL сайта из задачи. Укажите явно сайт (hh.ru, Работа.ру и т.д.)"
            }
        
        # Открываем сайт
        logger.info(f"[{session_id}] Открываем {site_url}")
        await page.goto(site_url, wait_until='networkidle', timeout=30000)
        
        # Получаем HTML содержимое страницы
        html_content = await page.content()
        
        # Парсим HTML в структурированный JSON
        structured_data = parse_html_to_structured_data(html_content, site_url)
        logger.info(f"[{session_id}] HTML распарсен: {len(structured_data.get('text', ''))} символов текста, "
                   f"{len(structured_data.get('tables', []))} таблиц, "
                   f"{len(structured_data.get('links', []))} ссылок")
        
        # Делаем скриншот
        screenshot = await page.screenshot(full_page=False)
        import base64
        screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
        
        if is_auth_task:
            # Извлекаем номер телефона из задачи
            phone_number = None
            import re
            # Ищем номер телефона в задаче (формат: +7XXXXXXXXXX или 8XXXXXXXXXX)
            phone_patterns = [
                r'\+?7\d{10}',  # +7XXXXXXXXXX или 7XXXXXXXXXX
                r'8\d{10}',     # 8XXXXXXXXXX
                r'номер телефона[:\s]+([+\d\s\-\(\)]+)',  # "номер телефона: +7..."
            ]
            for pattern in phone_patterns:
                match = re.search(pattern, task)
                if match:
                    phone_number = match.group(0) if match.lastindex is None else match.group(1)
                    # Очищаем номер от лишних символов
                    phone_number = ''.join(c for c in phone_number if c.isdigit() or c == '+')
                    if phone_number:
                        break
            
            # Для авторизации открываем страницу входа
            login_url = site_url.rstrip('/') + '/account/login'
            if "hh.ru" in site_url:
                login_url = "https://hh.ru/account/login"
            elif "rabota.ru" in site_url:
                login_url = "https://rabota.ru/login"
            elif "avito.ru" in site_url:
                login_url = "https://www.avito.ru/profile/login"
            
            logger.info(f"[{session_id}] Открываем страницу входа: {login_url}")
            try:
                await page.goto(login_url, wait_until='networkidle', timeout=30000)
            except Exception as e:
                logger.warning(f"[{session_id}] Ошибка загрузки страницы входа: {e}, пробуем базовый URL")
                await page.goto(site_url, wait_until='networkidle', timeout=30000)
            
            # Сохраняем начальные cookies
            cookies = await context.cookies()
            cookies_file = f"/tmp/browser_cookies_{session_id}.json"
            with open(cookies_file, 'w') as f:
                json.dump(cookies, f)
            logger.info(f"[{session_id}] Начальные cookies сохранены в {cookies_file}")
            
            # Если номер телефона найден, пытаемся автоматически заполнить форму
            if phone_number:
                logger.info(f"[{session_id}] Найден номер телефона, начинаю авторизацию: {phone_number[:3]}***{phone_number[-2:]}")
                
                try:
                    # Ждем загрузки страницы
                    await page.wait_for_load_state('networkidle', timeout=10000)
                    
                    # Ищем поле ввода телефона (различные селекторы для разных сайтов)
                    phone_selectors = [
                        'input[type="tel"]',
                        'input[name*="phone"]',
                        'input[name*="Phone"]',
                        'input[placeholder*="телефон"]',
                        'input[placeholder*="Телефон"]',
                        'input[id*="phone"]',
                        'input[id*="Phone"]',
                        '#phone',
                        '#Phone',
                        'input[data-qa="phone-input"]',
                        'input[data-qa="login-input"]',
                    ]
                    
                    phone_input = None
                    for selector in phone_selectors:
                        try:
                            phone_input = await page.wait_for_selector(selector, timeout=3000)
                            if phone_input:
                                logger.info(f"[{session_id}] Найдено поле ввода телефона: {selector}")
                                break
                        except:
                            continue
                    
                    if phone_input:
                        # Вводим номер телефона
                        await phone_input.fill(phone_number)
                        logger.info(f"[{session_id}] Номер телефона введен")
                        
                        # Ищем и нажимаем кнопку отправки/получения кода
                        submit_selectors = [
                            'button[type="submit"]',
                            'button:has-text("Получить код")',
                            'button:has-text("Отправить")',
                            'button:has-text("Войти")',
                            'button[data-qa="submit"]',
                            'button[data-qa="login-submit"]',
                            'button.login-button',
                            'button.submit-button',
                        ]
                        
                        submit_button = None
                        for selector in submit_selectors:
                            try:
                                submit_button = await page.query_selector(selector)
                                if submit_button:
                                    # Проверяем, что кнопка видима
                                    is_visible = await submit_button.is_visible()
                                    if is_visible:
                                        logger.info(f"[{session_id}] Найдена кнопка отправки: {selector}")
                                        break
                            except:
                                continue
                        
                        if submit_button:
                            await submit_button.click()
                            logger.info(f"[{session_id}] Кнопка отправки нажата, ожидаю код из SMS")
                            
                            # Ждем появления поля для ввода кода
                            await asyncio.sleep(2)  # Даем время на отправку SMS
                            
                            # Делаем скриншот
                            screenshot = await page.screenshot(full_page=False)
                            screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                            
                            # Сохраняем состояние ожидания кода
                            browser_contexts[session_id]['waiting_for_code'] = True
                            
                            return {
                                "type": "action",
                                "action": f"Номер телефона введен, отправлен запрос на получение кода",
                                "screenshot_base64": screenshot_base64,
                                "html": html_content,
                                "structured_data": structured_data,
                                "message": f"✅ Номер телефона {phone_number[:3]}***{phone_number[-2:]} введен.\n\n"
                                          f"📱 Код из SMS отправлен. Пожалуйста, введите код из SMS.",
                                "requires_code": True,
                                "session_id": session_id
                            }
                        else:
                            logger.warning(f"[{session_id}] Кнопка отправки не найдена")
                    else:
                        logger.warning(f"[{session_id}] Поле ввода телефона не найдено")
                        
                except Exception as e:
                    logger.error(f"[{session_id}] Ошибка при автоматическом заполнении формы: {e}", exc_info=True)
            
            # Если автоматическое заполнение не удалось, возвращаем обычное сообщение
            # Получаем HTML и структурированные данные для страницы входа
            html_content = await page.content()
            structured_data = parse_html_to_structured_data(html_content, login_url)
            
            screenshot = await page.screenshot(full_page=False)
            screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
            
            return {
                "type": "action",
                "action": f"Открыта страница входа на {site_url}.",
                "screenshot_base64": screenshot_base64,
                "html": html_content,
                "structured_data": structured_data,
                "message": f"✅ Страница входа открыта на {site_url}.\n\n"
                          f"Пожалуйста, авторизуйтесь вручную."
            }
        
        # Для других задач выполняем поиск или другие действия
        # Здесь можно добавить логику для парсинга задачи и выполнения действий
        
        return {
            "type": "done",
            "success": True,
            "message": f"Задача выполнена: открыт {site_url}",
            "screenshot_base64": screenshot_base64,
            "html": html_content,
            "structured_data": structured_data,
            "url": site_url
        }
        
    except ImportError:
        logger.error("Playwright не установлен. Установите: pip install playwright && playwright install chromium")
        return {
            "type": "error",
            "message": "Браузерный движок недоступен. Playwright не установлен."
        }
    except Exception as e:
        logger.error(f"[{session_id}] Ошибка выполнения задачи: {e}", exc_info=True)
        return {
            "type": "error",
            "message": f"Ошибка выполнения задачи: {str(e)}"
        }


async def check_auth_status(session_id: str) -> Dict[str, Any]:
    """Проверяет статус авторизации на странице"""
    try:
        from playwright.async_api import Page
        
        if session_id not in browser_contexts:
            return {"type": "error", "message": "Сессия не найдена"}
        
        session_data = browser_contexts[session_id]
        page: Page = session_data.get('page')
        
        if not page:
            return {"type": "error", "message": "Страница не открыта"}
        
        # Проверяем признаки авторизации
        url = page.url
        title = await page.title()
        
        # Проверяем наличие элементов, указывающих на авторизацию
        auth_indicators = [
            'button:has-text("Выйти")',
            'button:has-text("Logout")',
            '[data-qa="account-menu"]',
            '.account-menu',
            'a[href*="/logout"]'
        ]
        
        is_authenticated = False
        for selector in auth_indicators:
            try:
                element = await page.query_selector(selector)
                if element:
                    is_authenticated = True
                    break
            except:
                continue
        
        # Сохраняем cookies если авторизованы
        if is_authenticated:
            context = session_data['context']
            cookies = await context.cookies()
            cookies_file = f"/tmp/browser_cookies_{session_id}.json"
            with open(cookies_file, 'w') as f:
                json.dump(cookies, f)
            logger.info(f"[{session_id}] ✅ Авторизация подтверждена, cookies сохранены")
        
        # Получаем HTML и структурированные данные
        html_content = await page.content()
        structured_data = parse_html_to_structured_data(html_content, url)
        
        screenshot = await page.screenshot(full_page=False)
        import base64
        screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
        
        return {
            "type": "auth_status",
            "is_authenticated": is_authenticated,
            "url": url,
            "title": title,
            "screenshot_base64": screenshot_base64,
            "html": html_content,
            "structured_data": structured_data,
            "message": "✅ Авторизация успешна!" if is_authenticated else "⏳ Ожидаю авторизации..."
        }
        
    except Exception as e:
        logger.error(f"[{session_id}] Ошибка проверки авторизации: {e}")
        return {
            "type": "error",
            "message": f"Ошибка проверки авторизации: {str(e)}"
        }


async def handle_websocket(websocket):
    """
    Обрабатывает WebSocket соединение (обертка для websockets 15.0.1)
    
    Формат URL: ws://localhost:7070/ws?task=<задача>&session_id=<id>
    """
    # В websockets 15.0.1 path доступен через websocket.path
    path = getattr(websocket, 'path', '')
    if not path:
        # Пробуем получить из request
        request = getattr(websocket, 'request', None)
        if request:
            path = getattr(request, 'path', '') or str(getattr(request, 'raw_path', b'').decode('utf-8', errors='ignore'))
    
    await _handle_websocket_internal(websocket, path)


async def _handle_websocket_internal(websocket, path):
    """
    Внутренний обработчик WebSocket соединения
    """
    session_id = "default"
    task = None
    
    try:
        logger.info(f"[{session_id}] WebSocket path: '{path}'")
        
        # Парсим параметры из пути
        if path and "?" in path:
            query_string = path.split("?")[1]
            params = dict(param.split("=") for param in query_string.split("&") if "=" in param)
            task = unquote(params.get("task", ""))
            session_id = params.get("session_id", "default")
            logger.debug(f"[{session_id}] Параметры из URL: task={task[:50] if task else 'None'}, session_id={session_id}")
        
        logger.info(f"[{session_id}] Новое WebSocket соединение, задача: {task[:100] if task else 'None'}...")
        
        # Если задача передана в URL, выполняем её сразу
        if task:
            result = await execute_browser_task(task, session_id)
            await websocket.send(json.dumps(result))
            
            # Если это задача на авторизацию, периодически проверяем статус
            if result.get("type") == "action" and "авторизуйтесь" in result.get("message", "").lower():
                # Ждем авторизации, проверяя каждые 5 секунд
                for _ in range(60):  # Максимум 5 минут ожидания
                    await asyncio.sleep(5)
                    auth_status = await check_auth_status(session_id)
                    await websocket.send(json.dumps(auth_status))
                    
                    if auth_status.get("is_authenticated"):
                        await websocket.send(json.dumps({
                            "type": "done",
                            "success": True,
                            "message": "✅ Авторизация выполнена успешно! Сессия сохранена."
                        }))
                        break
        
        # Ожидаем сообщения от клиента
        async for message in websocket:
            try:
                data = json.loads(message)
                command = data.get("command")
                
                if command == "execute_task":
                    task_text = data.get("task", "")
                    result = await execute_browser_task(task_text, session_id)
                    await websocket.send(json.dumps(result))
                
                elif command == "check_auth":
                    auth_status = await check_auth_status(session_id)
                    await websocket.send(json.dumps(auth_status))
                
                elif command == "enter_code":
                    # Команда для ввода кода из SMS
                    code = data.get("code", "").strip()
                    if not code:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Код не указан"
                        }))
                        continue
                    
                    logger.info(f"[{session_id}] Получен код для ввода: {code[:2]}***")
                    
                    if session_id not in browser_contexts:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Сессия не найдена"
                        }))
                        continue
                    
                    session_data = browser_contexts[session_id]
                    page: Page = session_data.get('page')
                    
                    if not page:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Страница не открыта"
                        }))
                        continue
                    
                    try:
                        # Ищем поле ввода кода
                        code_selectors = [
                            'input[type="text"][name*="code"]',
                            'input[type="text"][name*="Code"]',
                            'input[type="text"][name*="sms"]',
                            'input[type="text"][name*="SMS"]',
                            'input[type="text"][name*="verification"]',
                            'input[type="text"][placeholder*="код"]',
                            'input[type="text"][placeholder*="Код"]',
                            'input[type="text"][placeholder*="SMS"]',
                            'input[id*="code"]',
                            'input[id*="Code"]',
                            'input[id*="sms"]',
                            'input[id*="SMS"]',
                            'input[data-qa="code-input"]',
                            'input[data-qa="sms-code"]',
                            '#code',
                            '#Code',
                            '#sms-code',
                        ]
                        
                        code_input = None
                        for selector in code_selectors:
                            try:
                                code_input = await page.wait_for_selector(selector, timeout=3000)
                                if code_input:
                                    logger.info(f"[{session_id}] Найдено поле ввода кода: {selector}")
                                    break
                            except:
                                continue
                        
                        if not code_input:
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": "Поле ввода кода не найдено на странице"
                            }))
                            continue
                        
                        # Вводим код
                        await code_input.fill(code)
                        logger.info(f"[{session_id}] Код введен")
                        
                        # Ищем и нажимаем кнопку подтверждения
                        confirm_selectors = [
                            'button[type="submit"]',
                            'button:has-text("Подтвердить")',
                            'button:has-text("Войти")',
                            'button:has-text("Отправить")',
                            'button[data-qa="submit"]',
                            'button[data-qa="confirm"]',
                            'button.confirm-button',
                            'button.submit-button',
                        ]
                        
                        confirm_button = None
                        for selector in confirm_selectors:
                            try:
                                confirm_button = await page.query_selector(selector)
                                if confirm_button:
                                    is_visible = await confirm_button.is_visible()
                                    if is_visible:
                                        logger.info(f"[{session_id}] Найдена кнопка подтверждения: {selector}")
                                        break
                            except:
                                continue
                        
                        if confirm_button:
                            await confirm_button.click()
                            logger.info(f"[{session_id}] Кнопка подтверждения нажата")
                            
                            # Ждем завершения авторизации
                            await asyncio.sleep(3)
                            
                            # Проверяем статус авторизации
                            auth_status = await check_auth_status(session_id)
                            
                            if auth_status.get("is_authenticated"):
                                # Сохраняем cookies
                                context = session_data['context']
                                cookies = await context.cookies()
                                cookies_file = f"/tmp/browser_cookies_{session_id}.json"
                                with open(cookies_file, 'w') as f:
                                    json.dump(cookies, f)
                                logger.info(f"[{session_id}] ✅ Авторизация успешна, cookies сохранены")
                                
                                # Убираем флаг ожидания кода
                                browser_contexts[session_id]['waiting_for_code'] = False
                                
                                # Получаем HTML и структурированные данные после авторизации
                                html_content = await page.content()
                                structured_data = parse_html_to_structured_data(html_content, page.url)
                                
                                screenshot = await page.screenshot(full_page=False)
                                screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                                
                                await websocket.send(json.dumps({
                                    "type": "done",
                                    "success": True,
                                    "message": "✅ Авторизация выполнена успешно! Сессия сохранена.",
                                    "screenshot_base64": screenshot_base64,
                                    "html": html_content,
                                    "structured_data": structured_data,
                                    "url": page.url
                                }))
                            else:
                                # Получаем HTML и структурированные данные
                                html_content = await page.content()
                                structured_data = parse_html_to_structured_data(html_content, page.url)
                                
                                screenshot = await page.screenshot(full_page=False)
                                screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                                
                                await websocket.send(json.dumps({
                                    "type": "action",
                                    "message": "Код введен, проверяю авторизацию...",
                                    "screenshot_base64": screenshot_base64,
                                    "html": html_content,
                                    "structured_data": structured_data,
                                    "url": page.url
                                }))
                        else:
                            logger.warning(f"[{session_id}] Кнопка подтверждения не найдена")
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": "Кнопка подтверждения не найдена"
                            }))
                    
                    except Exception as e:
                        logger.error(f"[{session_id}] Ошибка при вводе кода: {e}", exc_info=True)
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": f"Ошибка при вводе кода: {str(e)}"
                        }))
                
                elif command == "close":
                    # Закрываем браузер для сессии
                    if session_id in browser_contexts:
                        session_data = browser_contexts[session_id]
                        browser = session_data.get('browser')
                        playwright = session_data.get('playwright')
                        if browser:
                            await browser.close()
                        if playwright:
                            await playwright.stop()
                        del browser_contexts[session_id]
                        logger.info(f"[{session_id}] Браузер закрыт")
                    await websocket.send(json.dumps({"type": "done", "message": "Браузер закрыт"}))
                
            except json.JSONDecodeError:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Неверный формат JSON"
                }))
            except Exception as e:
                logger.error(f"[{session_id}] Ошибка обработки сообщения: {e}", exc_info=True)
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": f"Ошибка: {str(e)}"
                }))
    
    except ConnectionClosed:
        logger.debug(f"[{session_id}] WebSocket соединение закрыто клиентом")
    except (InvalidMessage, EOFError) as e:
        # Это нормально - клиент может закрыть соединение до завершения handshake
        # или отправить невалидный запрос (например, обычный HTTP вместо WebSocket)
        # Не логируем как ошибку, это обычная ситуация
        logger.debug(f"[{session_id}] Невалидное WebSocket соединение (возможно, обычный HTTP запрос): {type(e).__name__}")
    except Exception as e:
        # Логируем только серьезные ошибки
        error_type = type(e).__name__
        error_msg = str(e)
        # Игнорируем ошибки, связанные с невалидными HTTP запросами или закрытыми соединениями
        if any(keyword in error_type or keyword in error_msg for keyword in [
            "InvalidMessage", "EOFError", "connection closed", "did not receive a valid HTTP"
        ]):
            logger.debug(f"[{session_id}] Соединение закрыто или невалидный запрос: {error_type}")
        else:
            logger.error(f"[{session_id}] Ошибка WebSocket: {e}", exc_info=True)


# HTTP handlers для работы с куками
async def handle_set_cookies(request: web.Request) -> web.Response:
    """HTTP endpoint для установки куков для сессии"""
    try:
        data = await request.json()
        session_id = data.get("session_id", "default")
        cookies = data.get("cookies", [])
        site_url = data.get("siteUrl", "")
        
        # Преобразуем куки в формат Playwright, если они в строковом формате
        if isinstance(cookies, str):
            # Парсим куки из строки (формат: "name=value; domain=.example.com; path=/")
            cookie_list = []
            for cookie_str in cookies.split(";"):
                cookie_str = cookie_str.strip()
                if "=" in cookie_str:
                    parts = cookie_str.split("=", 1)
                    cookie_name = parts[0].strip()
                    cookie_value = parts[1].strip()
                    
                    # Извлекаем домен из site_url
                    from urllib.parse import urlparse
                    parsed_url = urlparse(site_url)
                    domain = parsed_url.netloc
                    if domain.startswith("www."):
                        domain = domain[4:]
                    
                    cookie_list.append({
                        "name": cookie_name,
                        "value": cookie_value,
                        "domain": domain,
                        "path": "/",
                    })
            cookies = cookie_list
        elif isinstance(cookies, list):
            # Убеждаемся, что куки в правильном формате
            cookie_list = []
            for cookie in cookies:
                if isinstance(cookie, dict):
                    cookie_list.append(cookie)
                elif isinstance(cookie, str):
                    # Парсим строку куки
                    if "=" in cookie:
                        parts = cookie.split("=", 1)
                        cookie_name = parts[0].strip()
                        cookie_value = parts[1].strip()
                        from urllib.parse import urlparse
                        parsed_url = urlparse(site_url)
                        domain = parsed_url.netloc
                        if domain.startswith("www."):
                            domain = domain[4:]
                        cookie_list.append({
                            "name": cookie_name,
                            "value": cookie_value,
                            "domain": domain,
                            "path": "/",
                        })
            cookies = cookie_list
        
        session_cookies[session_id] = cookies
        logger.info(f"[{session_id}] Сохранено {len(cookies)} куков для сессии")
        
        # Если контекст браузера уже создан, обновляем куки
        if session_id in browser_contexts:
            context = browser_contexts[session_id].get('context')
            if context:
                try:
                    await context.add_cookies(cookies)
                    logger.info(f"[{session_id}] Куки добавлены в существующий контекст")
                except Exception as e:
                    logger.warning(f"[{session_id}] Не удалось добавить куки в контекст: {e}")
        
        return web.json_response({
            "success": True,
            "message": f"Куки сохранены для сессии {session_id}",
            "cookies_count": len(cookies)
        })
    except Exception as e:
        logger.error(f"Ошибка при установке куков: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "message": f"Ошибка: {str(e)}"
        }, status=500)


async def handle_get_cookies(request: web.Request) -> web.Response:
    """HTTP endpoint для получения куков сессии"""
    try:
        session_id = request.query.get("session_id", "default")
        cookies = session_cookies.get(session_id, [])
        
        return web.json_response({
            "success": True,
            "session_id": session_id,
            "cookies": cookies,
            "cookies_count": len(cookies)
        })
    except Exception as e:
        logger.error(f"Ошибка при получении куков: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "message": f"Ошибка: {str(e)}"
        }, status=500)


async def handle_extract_cookies(request: web.Request) -> web.Response:
    """HTTP endpoint для извлечения куков из открытого браузера"""
    try:
        data = await request.json()
        session_id = data.get("sessionId", data.get("session_id", "default"))
        site_url = data.get("siteUrl", data.get("site_url", ""))
        
        if not site_url:
            return web.json_response({
                "success": False,
                "message": "Не указан URL сайта"
            }, status=400)
        
        # Получаем контекст браузера для сессии
        if session_id not in browser_contexts:
            return web.json_response({
                "success": False,
                "message": f"Браузер не открыт для сессии {session_id}. Сначала откройте сайт."
            }, status=404)
        
        session_data = browser_contexts[session_id]
        context = session_data.get('context')
        
        if not context:
            return web.json_response({
                "success": False,
                "message": "Контекст браузера не найден"
            }, status=404)
        
        # Получаем все куки из контекста
        cookies = await context.cookies()
        
        # Сохраняем куки для сессии
        session_cookies[session_id] = cookies
        
        logger.info(f"[{session_id}] Извлечено {len(cookies)} куков из браузера")
        
        return web.json_response({
            "success": True,
            "cookies": cookies,
            "cookies_count": len(cookies),
            "session_id": session_id
        })
    except Exception as e:
        logger.error(f"Ошибка при извлечении куков: {e}", exc_info=True)
        return web.json_response({
            "success": False,
            "message": f"Ошибка: {str(e)}"
        }, status=500)


async def main():
    """Запускает WebSocket и HTTP серверы"""
    # Устанавливаем браузеры при первом запуске
    await install_playwright()
    
    host = os.getenv("BROWSER_SERVICE_HOST", "0.0.0.0")
    port = int(os.getenv("BROWSER_SERVICE_PORT", "7070"))
    
    logger.info(f"🚀 Запуск браузерного сервиса на {host}:{port}")
    
    # Создаем HTTP приложение для работы с куками
    http_app = web.Application()
    
    # Middleware для CORS
    @web.middleware
    async def cors_middleware(request, handler):
        # Обрабатываем preflight запросы
        if request.method == 'OPTIONS':
            response = web.Response()
        else:
            response = await handler(request)
        
        # Добавляем CORS заголовки
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    http_app.middlewares.append(cors_middleware)
    
    http_app.router.add_post("/api/cookies/set", handle_set_cookies)
    http_app.router.add_get("/api/cookies/get", handle_get_cookies)
    http_app.router.add_post("/api/cookies/extract", handle_extract_cookies)
    
    # Запускаем HTTP сервер
    http_runner = web.AppRunner(http_app)
    await http_runner.setup()
    http_site = web.TCPSite(http_runner, host, port + 1)  # HTTP на порту 7071
    await http_site.start()
    logger.info(f"✅ HTTP API запущен на http://{host}:{port + 1}/api/cookies")
    
    # Настраиваем обработку ошибок для WebSocket сервера
    # Ошибки невалидных HTTP запросов подавляются через WebSocketErrorFilter
    # В websockets 15.0.1 path передается как второй аргумент автоматически
    async with websockets.serve(
        handle_websocket, 
        host, 
        port,
        # Игнорируем ошибки закрытых соединений
        close_timeout=10,
        ping_interval=20,
        ping_timeout=10
    ):
        logger.info(f"✅ Браузерный сервис запущен на ws://{host}:{port}/ws")
        logger.info(f"📝 Ожидание WebSocket соединений...")
        await asyncio.Future()  # Бесконечное ожидание


if __name__ == "__main__":
    asyncio.run(main())

