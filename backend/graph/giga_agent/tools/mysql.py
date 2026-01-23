"""
Tool для работы с базой данных MySQL.
Использует секреты пользователя: MySQL_host, MySQL_user, MySQL_password, MySQL_database.
"""

import logging
from typing import Optional, Dict, Any, List, Annotated
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

logger = logging.getLogger(__name__)

try:
    import aiomysql
    AIOMYSQL_AVAILABLE = True
except ImportError:
    AIOMYSQL_AVAILABLE = False
    logger.warning("aiomysql не установлен. Установите его: pip install aiomysql")


async def _get_mysql_config(user_id: Optional[str] = None, state: Optional[dict] = None) -> Dict[str, str]:
    """
    Получает конфигурацию MySQL из секретов пользователя.
    
    Args:
        user_id: Идентификатор пользователя
        state: Состояние графа (для извлечения секретов)
    
    Returns:
        Словарь с конфигурацией: host, user, password, database
    
    Raises:
        ValueError: Если не найдены необходимые секреты
    """
    if not state:
        raise ValueError("state не передан, невозможно получить секреты MySQL")
    
    secrets = state.get("secrets", [])
    if not secrets:
        raise ValueError("Секреты не найдены в state. Убедитесь, что секреты загружены для пользователя.")
    
    # Ищем необходимые секреты
    config = {}
    for secret in secrets:
        name = secret.get("name", "")
        value = secret.get("value", "")
        
        if name == "MySQL_host" or name == "mysql_host":
            config["host"] = value
        elif name == "MySQL_user" or name == "mysql_user":
            config["user"] = value
        elif name == "MySQL_password" or name == "mysql_password":
            config["password"] = value
        elif name == "MySQL_database" or name == "mysql_database":
            config["database"] = value
    
    # Проверяем наличие всех необходимых параметров
    required = ["host", "user", "password", "database"]
    missing = [key for key in required if key not in config or not config[key]]
    
    if missing:
        raise ValueError(
            f"Не найдены необходимые секреты MySQL: {', '.join(missing)}. "
            f"Убедитесь, что в секретах пользователя есть: MySQL_host, MySQL_user, MySQL_password, MySQL_database"
        )
    
    return config


@tool(parse_docstring=True)
async def mysql_query(
    query: str,
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Выполняет SQL запрос к базе данных MySQL.
    Использует секреты пользователя для подключения: MySQL_host, MySQL_user, MySQL_password, MySQL_database.
    
    Args:
        query: SQL запрос для выполнения (SELECT, INSERT, UPDATE, DELETE и т.д.)
        user_id: Идентификатор пользователя (для логирования)
        state: Состояние графа (для извлечения секретов MySQL)
    
    Returns:
        Результат выполнения запроса в виде строки. Для SELECT запросов возвращает таблицу с данными.
        Для других запросов возвращает информацию о количестве затронутых строк.
    
    Raises:
        ValueError: Если не найдены необходимые секреты или произошла ошибка при выполнении запроса
    """
    if not AIOMYSQL_AVAILABLE:
        return "Ошибка: библиотека aiomysql не установлена. Установите её: pip install aiomysql"
    
    if not query or not query.strip():
        return "Ошибка: SQL запрос не может быть пустым"
    
    # Получаем конфигурацию из секретов
    try:
        config = await _get_mysql_config(user_id=user_id, state=state)
    except ValueError as e:
        return f"Ошибка конфигурации: {str(e)}"
    
    # Подключаемся к базе данных и выполняем запрос
    connection = None
    try:
        # Подключение к MySQL
        connection = await aiomysql.connect(
            host=config["host"],
            user=config["user"],
            password=config["password"],
            db=config["database"],
            charset='utf8mb4',
            cursorclass=aiomysql.DictCursor
        )
        
        async with connection.cursor() as cursor:
            # Выполняем запрос
            await cursor.execute(query)
            
            # Определяем тип запроса
            query_upper = query.strip().upper()
            is_select = query_upper.startswith("SELECT") or query_upper.startswith("SHOW") or query_upper.startswith("DESCRIBE") or query_upper.startswith("DESC")
            
            if is_select:
                # Для SELECT запросов получаем результаты
                rows = await cursor.fetchall()
                
                if not rows:
                    return "Запрос выполнен успешно. Результатов не найдено."
                
                # Форматируем результаты в таблицу
                if isinstance(rows[0], dict):
                    # Если это словари (DictCursor)
                    columns = list(rows[0].keys())
                    result_lines = []
                    
                    # Заголовок таблицы
                    header = " | ".join(str(col) for col in columns)
                    result_lines.append(header)
                    result_lines.append("-" * len(header))
                    
                    # Данные
                    for row in rows:
                        row_values = [str(row.get(col, "")) for col in columns]
                        result_lines.append(" | ".join(row_values))
                    
                    return "\n".join(result_lines)
                else:
                    # Если это кортежи
                    return "\n".join(str(row) for row in rows)
            else:
                # Для других запросов (INSERT, UPDATE, DELETE и т.д.)
                await connection.commit()
                affected_rows = cursor.rowcount
                return f"Запрос выполнен успешно. Затронуто строк: {affected_rows}"
    
    except aiomysql.Error as e:
        error_msg = f"Ошибка MySQL: {str(e)}"
        logger.error(f"MySQL ошибка при выполнении запроса: {error_msg}")
        return error_msg
    except Exception as e:
        error_msg = f"Неожиданная ошибка: {str(e)}"
        logger.error(f"Ошибка при выполнении MySQL запроса: {error_msg}", exc_info=True)
        return error_msg
    finally:
        if connection:
            connection.close()
            await connection.ensure_closed()

