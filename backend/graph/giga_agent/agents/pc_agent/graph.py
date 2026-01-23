"""
Граф PC Management Agent
"""

import logging
from typing import Annotated, TypedDict

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import InjectedState
from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message

from giga_agent.agents.pc_agent.nodes.system import get_system_info, run_program, list_programs, get_process_list, kill_process
from giga_agent.agents.pc_agent.nodes.files import search_files, open_file, create_file, read_file, file_info, list_directory
from giga_agent.agents.pc_agent.nodes.windows import open_windows, close_window, get_window_info, minimize_window, maximize_window

logger = logging.getLogger(__name__)

# Инструменты управления ПК
# ВАЖНО: Эти инструменты определены здесь для экспорта, но они должны использоваться
# ТОЛЬКО через MCP сервер pc_management, а не напрямую!
# Не вызывайте эти инструменты напрямую через .ainvoke() или .invoke()!
# Используйте их через MCP сервер pc_management через tool_client.aexecute()
PC_TOOLS = [
    # Системные операции
    get_system_info,
    run_program,
    list_programs,
    get_process_list,
    kill_process,
    # Файловые операции
    search_files,
    open_file,
    create_file,
    read_file,
    file_info,
    list_directory,
    # Операции с окнами
    open_windows,
    close_window,
    get_window_info,
    minimize_window,
    maximize_window
]

@tool
async def pc_agent(
    user_request: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Агент для управления компьютером на Windows
    
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Параметр называется user_request (НЕ query, НЕ task_type, НЕ action)!
    Всегда передавай запрос пользователя в параметр user_request.
    
    ПРАВИЛЬНЫЙ ФОРМАТ ВЫЗОВА:
    pc_agent(user_request="запустить блокнот")
    pc_agent(user_request="найти файл test.txt")
    pc_agent(user_request="показать системную информацию")
    
    НЕПРАВИЛЬНО (НЕ ДЕЛАЙ ТАК):
    ❌ pc_agent(query="запустить блокнот") - параметр query не существует!
    ❌ pc_agent(action="run_program") - параметр action не существует!
    
    ВАЖНО: Этот агент предоставляет инструкции по использованию инструментов PC Management,
    но НЕ вызывает их напрямую! Все инструменты PC Management (get_system_info, run_program,
    search_files, read_file и т.д.) должны вызываться напрямую из MCP сервера pc_management.
    
    Обрабатывает запросы пользователя связанные с управлением ПК:
    - Системная информация и управление процессами
    - Запуск программ и приложений
    - Работа с файловой системой
    - Управление окнами приложений
    - Поиск и открытие файлов
    
    Args:
        user_request: Запрос пользователя (например, "запустить блокнот", "найти файл test.txt")
        user_id: Идентификатор пользователя (необязательно)
    
    Примечание: Инструменты PC Management доступны через MCP сервер pc_management и должны
    вызываться напрямую, а не через этот агент.
    """
    
    try:
        user_input = user_request.lower()
        
        # Проверка: если запрос о портфеле акций или финансовых инструментах, 
        # то это не для pc_agent, а для tinkoff_agent
        financial_keywords = ["портфель акций", "портфель пользователя", "портфели акций", 
                             "позиции в портфеле", "мои акции", "акции пользователя",
                             "портфель", "акций", "акции", "тикер", "инвестиции", "tinkoff"]
        if any(keyword in user_input for keyword in financial_keywords):
            return """📈 **Это запрос о финансовом портфеле!**

Для работы с портфелем акций, позициями и инвестициями используйте агент **tinkoff_agent**, а не pc_agent.

Пример: tinkoff_agent("открыть портфель акций пользователя", user_id="ваш_id")

**pc_agent** предназначен только для:
- Управления файлами на компьютере
- Запуска программ
- Работы с системой Windows
- Управления окнами"""
        
        # Системные команды
        # ВАЖНО: Инструменты PC Management должны вызываться через MCP сервер pc_management, а не напрямую!
        # pc_agent только предоставляет инструкции, но не вызывает инструменты напрямую
        if any(phrase in user_input for phrase in ["системная информация", "информация о системе", "характеристики компьютера", "система"]):
            return """🖥️ **Информация о системе**

Для получения информации о системе используйте инструмент **get_system_info** из MCP сервера pc_management напрямую.

**ВАЖНО**: Не вызывайте инструменты PC Management через pc_agent! Используйте их напрямую из MCP сервера pc_management.

Пример вызова: get_system_info()"""
            
        elif any(phrase in user_input for phrase in ["список программ", "установленные программы", "программы"]):
            return """📋 **Список программ**

Для получения списка установленных программ используйте инструмент **list_programs** из MCP сервера pc_management напрямую.

**ВАЖНО**: Не вызывайте инструменты PC Management через pc_agent! Используйте их напрямую из MCP сервера pc_management.

Пример вызова: list_programs()"""
            
        elif any(phrase in user_input for phrase in ["процессы", "запущенные процессы", "диспетчер задач"]):
            return """📊 **Список процессов**

Для получения списка запущенных процессов используйте инструмент **get_process_list** из MCP сервера pc_management напрямую.

**ВАЖНО**: Не вызывайте инструменты PC Management через pc_agent! Используйте их напрямую из MCP сервера pc_management.

Пример вызова: get_process_list()"""
        
        # Команды запуска программ
        elif user_input.startswith("запустить ") or user_input.startswith("открыть программу "):
            program_name = user_input.replace("запустить ", "").replace("открыть программу ", "").strip()
            return f"""🚀 **Запуск программы**

Для запуска программы используйте инструмент run_program с параметрами:
• program_name: Название программы ({program_name})
• user_id: Ваш ID пользователя

Пример: запустить "{program_name}\""""
            
        elif user_input.startswith("завершить процесс ") or user_input.startswith("убить процесс "):
            process_name = user_input.replace("завершить процесс ", "").replace("убить процесс ", "").strip()
            return f"""⚠️ **Завершение процесса**

Для завершения процесса используйте инструмент kill_process с параметрами:
• process_identifier: PID или имя процесса ({process_name})
• user_id: Ваш ID пользователя

⚠️ **Внимание:** Завершение процессов может привести к потере данных!"""
        
        # Файловые команды
        elif any(phrase in user_input for phrase in ["найти файл", "поиск файл", "искать файл"]):
            return """🔍 **Поиск файлов**

Для поиска файлов используйте инструмент search_files с параметрами:
• pattern: Паттерн для поиска в названии файла
• directory: Директория для поиска (необязательно)
• file_type: Тип файла (text, image, video, audio, document, code)
• user_id: Ваш ID пользователя

Пример: найти все файлы с "test" в названии"""
            
        elif user_input.startswith("открыть файл ") or (user_input.startswith("открыть ") and 
            not any(keyword in user_input for keyword in ["портфель", "акций", "акции", "позиции", "инвестиции"])):
            file_name = user_input.replace("открыть файл ", "").replace("открыть ", "").strip()
            return f"""📂 **Открытие файла**

Для открытия файла используйте инструмент open_file с параметрами:
• file_path: Полный путь к файлу
• user_id: Ваш ID пользователя

Сначала найдите файл "{file_name}" с помощью search_files"""
            
        elif user_input.startswith("прочитать файл ") or user_input.startswith("содержимое файла "):
            file_name = user_input.replace("прочитать файл ", "").replace("содержимое файла ", "").strip()
            return f"""📖 **Чтение файла**

Для чтения содержимого файла используйте инструмент read_file с параметрами:
• file_path: Полный путь к файлу
• user_id: Ваш ID пользователя

Сначала найдите файл "{file_name}" с помощью search_files"""
            
        elif user_input.startswith("создать файл ") or user_input.startswith("новый файл "):
            file_name = user_input.replace("создать файл ", "").replace("новый файл ", "").strip()
            return f"""✏️ **Создание файла**

Для создания файла используйте инструмент create_file с параметрами:
• file_path: Путь для создания файла (например, Desktop/{file_name})
• content: Содержимое файла
• user_id: Ваш ID пользователя

Пример: создать текстовый файл с заметками"""
            
        elif any(phrase in user_input for phrase in ["содержимое папки", "список файлов", "что в папке", "показать папку"]):
            return """📁 **Просмотр содержимого папки**

Для просмотра содержимого папки используйте инструмент list_directory с параметрами:
• directory: Путь к папке (необязательно, по умолчанию - домашняя папка)
• show_hidden: Показывать скрытые файлы (необязательно)
• user_id: Ваш ID пользователя

Пример: показать содержимое папки Desktop"""
        
        # Команды работы с окнами
        # ВАЖНО: Инструменты PC Management должны вызываться через MCP сервер pc_management, а не напрямую!
        elif any(phrase in user_input for phrase in ["открытые окна", "список окон", "окна", "активные окна"]):
            return """🪟 **Список окон**

Для получения списка открытых окон используйте инструмент **open_windows** из MCP сервера pc_management напрямую.

**ВАЖНО**: Не вызывайте инструменты PC Management через pc_agent! Используйте их напрямую из MCP сервера pc_management.

Пример вызова: open_windows()"""
            
        elif user_input.startswith("закрыть окно ") or user_input.startswith("закрыть "):
            window_name = user_input.replace("закрыть окно ", "").replace("закрыть ", "").strip()
            return f"""❌ **Закрытие окна**

Для закрытия окна используйте инструмент close_window с параметрами:
• window_identifier: HWND окна или часть заголовка ({window_name})
• user_id: Ваш ID пользователя

Сначала получите список окон с помощью open_windows"""
            
        elif user_input.startswith("свернуть окно ") or user_input.startswith("свернуть "):
            window_name = user_input.replace("свернуть окно ", "").replace("свернуть ", "").strip()
            return f"""📉 **Сворачивание окна**

Для сворачивания окна используйте инструмент minimize_window с параметрами:
• window_identifier: HWND окна или часть заголовка ({window_name})
• user_id: Ваш ID пользователя

Сначала получите список окон с помощью open_windows"""
            
        elif user_input.startswith("развернуть окно ") or user_input.startswith("развернуть "):
            window_name = user_input.replace("развернуть окно ", "").replace("развернуть ", "").strip()
            return f"""📈 **Разворачивание окна**

Для разворачивания окна используйте инструмент maximize_window с параметрами:
• window_identifier: HWND окна или часть заголовка ({window_name})
• user_id: Ваш ID пользователя

Сначала получите список окон с помощью open_windows"""
        
        # Если команда не распознана
        else:
            return """🖥️ **PC Management Agent**

🎛️ **Системные операции:**
• "системная информация" - характеристики компьютера
• "список программ" - установленные приложения
• "процессы" - запущенные процессы
• "запустить [программа]" - запуск приложения
• "завершить процесс [имя]" - остановка процесса

📁 **Файловые операции:**
• "найти файл [название]" - поиск файлов
• "открыть файл [путь]" - открытие файла
• "прочитать файл [путь]" - чтение содержимого
• "создать файл [название]" - создание нового файла
• "содержимое папки [путь]" - просмотр директории

🪟 **Управление окнами:**
• "открытые окна" - список активных окон
• "закрыть окно [название]" - закрытие окна
• "свернуть окно [название]" - сворачивание
• "развернуть окно [название]" - разворачивание

🔧 **Доступные инструменты:**
• get_system_info - информация о системе
• run_program - запуск программ
• list_programs - список программ
• get_process_list - список процессов
• kill_process - завершение процессов
• search_files - поиск файлов
• open_file - открытие файлов
• read_file - чтение файлов
• create_file - создание файлов
• list_directory - содержимое папок
• open_windows - список окон
• close_window - закрытие окон
• minimize_window - сворачивание окон
• maximize_window - разворачивание окон
• get_window_info - информация об окне

💡 **Популярные программы:**
блокнот, калькулятор, проводник, командная строка, диспетчер задач

⚠️ **Безопасность:** Все операции проходят проверку безопасности. Доступ к системным файлам ограничен."""
        
    except Exception as e:
        logger.error(f"Ошибка в pc_agent: {e}")
        return f"❌ **Ошибка PC агента:** {str(e)}\n\nПопробуйте еще раз или обратитесь к администратору."

# Состояние для графа PC управления
class PCState(TypedDict):
    messages: Annotated[list, "messages"]
    user_id: str
    current_directory: str
    system_info: dict

# Создание полноценного агента PC управления
def create_pc_agent():
    """Создает полноценный агент PC управления с графом"""
    
    def agent_node(state: PCState):
        """Основной узел агента PC управления"""
        user_input = state["messages"][-1].content if state["messages"] else ""
        user_id = state.get("user_id", "default_user")
        
        # Обработка запросов пользователя
        if any(phrase in user_input.lower() for phrase in ["система", "информация", "процессы"]):
            return {"messages": [HumanMessage(content="Получение системной информации...")]}
        elif any(phrase in user_input.lower() for phrase in ["файлы", "поиск", "папка"]):
            return {"messages": [HumanMessage(content="Работа с файловой системой...")]}
        elif any(phrase in user_input.lower() for phrase in ["окна", "программы", "запуск"]):
            return {"messages": [HumanMessage(content="Управление программами и окнами...")]}
        else:
            return {"messages": [HumanMessage(content="💻 PC Management Agent готов к работе!")]}
    
    def router(state: PCState):
        """Маршрутизатор для выбора следующего узла"""
        if not state["messages"]:
            return "done"
        
        last_message = state["messages"][-1].content.lower()
        
        if "система" in last_message or "процессы" in last_message:
            return "system"
        elif "файлы" in last_message or "поиск" in last_message:
            return "files"
        elif "окна" in last_message or "программы" in last_message:
            return "windows"
        else:
            return "done"
    
    def system_node(state: PCState):
        """Узел для работы с системой"""
        return {"messages": [HumanMessage(content="🔧 Системный узел активирован")]}
    
    def files_node(state: PCState):
        """Узел для работы с файлами"""
        return {"messages": [HumanMessage(content="📁 Файловый узел активирован")]}
    
    def windows_node(state: PCState):
        """Узел для работы с окнами"""
        return {"messages": [HumanMessage(content="🪟 Узел управления окнами активирован")]}
    
    def done_node(state: PCState):
        """Завершающий узел"""
        return {"messages": [HumanMessage(content="✅ PC Management Agent готов к использованию!")]}
    
    # Создание графа
    workflow = StateGraph(PCState)
    
    # Добавление узлов
    workflow.add_node("agent", agent_node)
    workflow.add_node("system", system_node)
    workflow.add_node("files", files_node)
    workflow.add_node("windows", windows_node)
    workflow.add_node("done", done_node)
    
    # Добавление рёбер
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", router)
    workflow.add_edge("system", "done")
    workflow.add_edge("files", "done")
    workflow.add_edge("windows", "done")
    workflow.add_edge("done", "__end__")
    
    return workflow.compile()

# Создание графа
graph = create_pc_agent()

# Экспорт всех инструментов PC управления
__all__ = [
    "pc_agent",
    "graph",
    "create_pc_agent",
    "PC_TOOLS",
    "get_system_info", 
    "run_program", 
    "list_programs", 
    "get_process_list", 
    "kill_process",
    "search_files", 
    "open_file", 
    "create_file", 
    "read_file", 
    "file_info", 
    "list_directory",
    "open_windows", 
    "close_window", 
    "get_window_info", 
    "minimize_window", 
    "maximize_window"
]
