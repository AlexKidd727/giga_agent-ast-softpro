"""
Узел для анализа требований и создания структуры проекта
"""

import json
import re
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig

from giga_agent.agents.coder_agent.config import CoderState, llm
from giga_agent.agents.coder_agent.prompts.ru import ANALYSIS_PROMPT
from giga_agent.utils.lang import LANG


def should_exclude_db_file(file_path: str) -> bool:
    """Проверяет, нужно ли исключить файл базы данных"""
    if not file_path:
        return False
    
    # Расширения файлов баз данных
    db_extensions = ['.db', '.sqlite', '.sqlite3', '.db3', '.sdb', '.sl3']
    
    # Имена файлов баз данных
    db_filenames = ['database.db', 'data.db', 'app.db', 'users.db', 'config.db']
    
    # Проверяем расширение
    for ext in db_extensions:
        if file_path.lower().endswith(ext):
            return True
    
    # Проверяем имя файла
    import os
    filename = os.path.basename(file_path).lower()
    for db_name in db_filenames:
        if filename == db_name:
            return True
    
    # Проверяем путь на наличие папок баз данных
    path_parts = file_path.lower().replace('\\', '/').split('/')
    db_folders = ['database', 'db', 'data', 'sqlite']
    for folder in db_folders:
        if folder in path_parts:
            return True
    
    return False


async def analyze_node(state: CoderState, config: RunnableConfig):
    """Анализирует требования и создает структуру проекта"""
    from langchain_core.messages import ToolMessage
    
    # Получаем последнее сообщение агента с tool_call
    agent_messages = state.get("agent_messages", [])
    if not agent_messages:
        return {
            "generation_status": {
                "status": "error",
                "message": "Нет сообщений от агента"
            }
        }
    
    last_message = agent_messages[-1]
    tool_calls = getattr(last_message, 'tool_calls', [])
    
    if not tool_calls or tool_calls[0]["name"] != "analyze_project":
        return {
            "generation_status": {
                "status": "error",
                "message": "Неверный вызов инструмента"
            }
        }
    
    tool_call_id = tool_calls[0].get("id", "")
    additional_info = tool_calls[0].get("args", {}).get("additional_info", "")
    
    project_prompt = state.get("project_prompt", state.get("task", ""))
    if additional_info:
        project_prompt += f"\nДополнительная информация: {additional_info}"
    
    programming_language = state.get("programming_language", "")
    database = state.get("database", "")
    technologies = state.get("selected_technologies", [])
    technologies_str = ', '.join(technologies) if technologies else 'нет'
    
    # Формируем промпт для анализа
    prompt = ChatPromptTemplate.from_messages([
        ("system", ANALYSIS_PROMPT),
        MessagesPlaceholder("messages")
    ]).partial(
        language=LANG,
        project_prompt=project_prompt,
        programming_language=programming_language or "не указан",
        database=database or "нет",
        technologies=technologies_str
    )
    
    chain = prompt | llm
    
    # Получаем сообщения для анализа
    analysis_messages = state.get("analysis_messages", [])
    if not analysis_messages:
        analysis_messages = [HumanMessage(content=project_prompt)]
    
    try:
        # Вызываем LLM для анализа
        response = await chain.ainvoke({
            "messages": analysis_messages
        })
        
        # Парсим ответ и извлекаем структуру проекта
        content = response.content if hasattr(response, 'content') else str(response)
        
        # Пытаемся найти JSON в ответе
        project_structure = []
        
        # Ищем JSON блок - более надежный способ
        # Ищем начало JSON объекта
        json_start = content.find('{')
        if json_start != -1:
            # Ищем конец JSON объекта
            brace_count = 0
            json_end = -1
            for i, char in enumerate(content[json_start:], start=json_start):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        break
            
            if json_end > json_start:
                try:
                    json_str = content[json_start:json_end]
                    parsed = json.loads(json_str)
                    project_structure = parsed.get("structure", [])
                except json.JSONDecodeError as e:
                    # Пытаемся найти JSON другим способом
                    # Ищем блоки с "structure"
                    structure_match = re.search(r'"structure"\s*:\s*\[(.*?)\]', content, re.DOTALL)
                    if structure_match:
                        # Пытаемся извлечь элементы массива
                        items_text = structure_match.group(1)
                        # Ищем отдельные объекты
                        item_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
                        items = re.findall(item_pattern, items_text)
                        for item_str in items:
                            try:
                                item = json.loads(item_str)
                                project_structure.append(item)
                            except:
                                pass
        
        # Если не нашли JSON, пытаемся извлечь структуру из текста
        if not project_structure:
            # Ищем паттерны типа "path: описание" или файловые пути
            lines = content.split('\n')
            for line in lines:
                # Ищем пути файлов
                path_patterns = [
                    r'["\']([^"\']+\.(py|js|ts|java|go|php|html|css|json|md|txt|yml|yaml))["\']',
                    r'path["\']?\s*[:=]\s*["\']?([^"\'\s]+)["\']?',
                    r'([a-zA-Z0-9_\-/\\]+\.(py|js|ts|java|go|php|html|css|json|md|txt|yml|yaml))'
                ]
                for pattern in path_patterns:
                    matches = re.finditer(pattern, line, re.IGNORECASE)
                    for match in matches:
                        file_path = match.group(1) if match.lastindex >= 1 else match.group(0)
                        if file_path and not should_exclude_db_file(file_path):
                            # Проверяем, что это не просто расширение
                            if '.' in file_path and len(file_path) > 3:
                                project_structure.append({
                                    "path": file_path,
                                    "description": line.strip(),
                                    "functions": []
                                })
                                break
        
        # Фильтруем файлы баз данных и дубликаты
        filtered_structure = []
        seen_paths = set()
        for item in project_structure:
            file_path = item.get("path", "").strip()
            if file_path and file_path not in seen_paths and not should_exclude_db_file(file_path):
                # Пропускаем папки
                if not file_path.endswith('/') and not file_path.endswith('\\'):
                    filtered_structure.append(item)
                    seen_paths.add(file_path)
        
        # Если структура пустая, создаем базовую структуру
        if not filtered_structure:
            if programming_language and programming_language.lower() == "python":
                filtered_structure = [
                    {"path": "main.py", "description": "Главный файл приложения", "functions": ["main"]},
                    {"path": "requirements.txt", "description": "Зависимости проекта", "functions": []},
                    {"path": "README.md", "description": "Документация проекта", "functions": []}
                ]
            elif programming_language and programming_language.lower() in ["nodejs", "javascript"]:
                filtered_structure = [
                    {"path": "index.js", "description": "Главный файл приложения", "functions": ["main"]},
                    {"path": "package.json", "description": "Конфигурация проекта", "functions": []},
                    {"path": "README.md", "description": "Документация проекта", "functions": []}
                ]
            else:
                # Базовая структура по умолчанию
                filtered_structure = [
                    {"path": "main.py", "description": "Главный файл приложения", "functions": ["main"]},
                    {"path": "README.md", "description": "Документация проекта", "functions": []}
                ]
        
        # Формируем ответ для агента
        structure_text = "\n".join([
            f"- {item['path']}: {item.get('description', '')}"
            for item in filtered_structure
        ])
        
        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=json.dumps({
                "success": True,
                "message": f"Структура проекта создана: {len(filtered_structure)} файлов",
                "structure": filtered_structure,
                "structure_text": structure_text
            }, ensure_ascii=False)
        )
        
        return {
            "analysis_messages": analysis_messages + [response],
            "agent_messages": [tool_message],
            "project_structure": filtered_structure,
            "generation_status": {
                "status": "analyzed",
                "message": f"Структура проекта создана: {len(filtered_structure)} файлов",
                "total_files": len(filtered_structure)
            }
        }
        
    except Exception as e:
        error_msg = f"Ошибка анализа проекта: {str(e)}"
        print(f"[CODER AGENT] {error_msg}")
        return {
            "agent_messages": [ToolMessage(
                tool_call_id=tool_call_id,
                content=json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)
            )],
            "generation_status": {
                "status": "error",
                "message": error_msg
            }
        }

