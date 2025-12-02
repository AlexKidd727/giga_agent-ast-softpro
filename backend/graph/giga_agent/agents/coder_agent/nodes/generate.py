"""
Узел для генерации файлов проекта
"""

import json
import re
import os
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig

from giga_agent.agents.coder_agent.config import CoderState, llm
from giga_agent.agents.coder_agent.prompts.ru import GENERATION_PROMPT
from giga_agent.agents.coder_agent.utils.code_cleaner import clean_generated_code
from giga_agent.utils.lang import LANG


async def generate_node(state: CoderState, config: RunnableConfig):
    """Генерирует файлы проекта"""
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
    
    if not tool_calls or tool_calls[0]["name"] != "generate_project":
        return {
            "generation_status": {
                "status": "error",
                "message": "Неверный вызов инструмента"
            }
        }
    
    tool_call_id = tool_calls[0].get("id", "")
    additional_info = tool_calls[0].get("args", {}).get("additional_info", "")
    
    project_structure = state.get("project_structure", [])
    if not project_structure:
        return {
            "agent_messages": [ToolMessage(
                tool_call_id=tool_call_id,
                content=json.dumps({
                    "success": False,
                    "error": "Структура проекта не создана. Сначала выполните анализ проекта."
                }, ensure_ascii=False)
            )],
            "generation_status": {
                "status": "error",
                "message": "Структура проекта не создана"
            }
        }
    
    project_prompt = state.get("project_prompt", state.get("task", ""))
    if additional_info:
        project_prompt += f"\nДополнительная информация: {additional_info}"
    
    programming_language = state.get("programming_language", "")
    database = state.get("database", "")
    technologies = state.get("selected_technologies", [])
    technologies_str = ', '.join(technologies) if technologies else 'нет'
    
    project_files = state.get("project_files", {})
    generation_status = state.get("generation_status", {})
    
    # Определяем, сколько файлов нужно сгенерировать
    files_to_generate = [
        f for f in project_structure 
        if f.get("path") and f["path"] not in project_files 
        and not f["path"].endswith('/') and not f["path"].endswith('\\')
    ]
    
    if not files_to_generate:
        # Все файлы уже сгенерированы
        return {
            "agent_messages": [ToolMessage(
                tool_call_id=tool_call_id,
                content=json.dumps({
                    "success": True,
                    "message": f"Все файлы уже сгенерированы: {len(project_files)}/{len(project_structure)}"
                }, ensure_ascii=False)
            )],
            "generation_status": {
                "status": "completed",
                "message": f"Генерация завершена! Создано файлов: {len(project_files)}/{len(project_structure)}",
                "completed_files": list(project_files.keys()),
                "total_files": len(project_structure)
            }
        }
    
    # Генерируем файлы по одному
    generated_count = 0
    errors = []
    
    for file_info in files_to_generate:
        file_path = file_info.get("path", "")
        if not file_path:
            continue
        
        try:
            file_description = file_info.get("description", "")
            functions = file_info.get("functions", [])
            functions_str = ', '.join(functions) if isinstance(functions, list) else str(functions)
            
            # Формируем структуру проекта для контекста
            structure_str = '\n'.join([
                f"{f.get('path', '')} - {f.get('description', '')}"
                for f in project_structure
            ])
            
            # Формируем промпт для генерации
            prompt = ChatPromptTemplate.from_messages([
                ("system", GENERATION_PROMPT),
                MessagesPlaceholder("messages")
            ]).partial(
                language=LANG,
                file_path=file_path,
                file_description=file_description,
                functions=functions_str,
                project_prompt=project_prompt,
                programming_language=programming_language or "не указан",
                database=database or "нет",
                technologies=technologies_str,
                project_structure=structure_str
            )
            
            chain = prompt | llm
            
            # Вызываем LLM для генерации
            response = await chain.ainvoke({
                "messages": [HumanMessage(content=f"Сгенерируй код для файла {file_path}")]
            })
            
            # Получаем сгенерированный код
            generated_code = response.content if hasattr(response, 'content') else str(response)
            
            # Очищаем код от markdown разметки
            cleaned_code = clean_generated_code(generated_code, file_path)
            
            if cleaned_code:
                # Сохраняем файл
                project_files[file_path] = cleaned_code
                generated_count += 1
            else:
                errors.append(f"Пустой код для файла {file_path}")
                
        except Exception as e:
            error_msg = f"Ошибка генерации файла {file_path}: {str(e)}"
            errors.append(error_msg)
            print(f"[CODER AGENT] {error_msg}")
    
    # Обновляем статус
    total_generated = len(project_files)
    total_files = len(project_structure)
    
    if total_generated >= total_files:
        status = "completed"
        message = f"Генерация завершена! Создано файлов: {total_generated}/{total_files}"
    else:
        status = "generating"
        message = f"Сгенерировано файлов: {total_generated}/{total_files}"
        if errors:
            message += f" (ошибок: {len(errors)})"
    
    generation_status = {
        "status": status,
        "message": message,
        "completed_files": list(project_files.keys()),
        "total_files": total_files,
        "errors": errors if errors else None
    }
    
    # Формируем ответ для агента
    result_content = {
        "success": True,
        "message": message,
        "generated_this_step": generated_count,
        "total_generated": total_generated,
        "total_files": total_files
    }
    
    if errors:
        result_content["errors"] = errors[:5]  # Ограничиваем количество ошибок
    
    return {
        "agent_messages": [ToolMessage(
            tool_call_id=tool_call_id,
            content=json.dumps(result_content, ensure_ascii=False)
        )],
        "project_files": project_files,
        "generation_status": generation_status
    }

