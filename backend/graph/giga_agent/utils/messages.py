"""
Утилиты для работы с сообщениями LangChain.
Включает фильтрацию, валидацию и очистку истории сообщений.
"""
import logging
import re
import json
import uuid
from typing import List, Dict, Set, Optional, Any, Tuple
from langchain_core.messages import ToolMessage, AIMessage, HumanMessage, BaseMessage

logger = logging.getLogger(__name__)


# Паттерны для парсинга некорректных форматов tool_calls
# Формат 1: <function=name> <parameter=key>value</parameter> ... </function>
MALFORMED_FUNCTION_PATTERN = re.compile(
    r'<function[=\s]+([^>]+)>\s*(.*?)\s*(?:</function>|</tool_call>|$)',
    re.DOTALL | re.IGNORECASE
)
MALFORMED_PARAMETER_PATTERN = re.compile(
    r'<parameter[=\s]+([^>]+)>\s*(.*?)\s*</parameter>',
    re.DOTALL | re.IGNORECASE
)

# Формат 2: <tool_call> {"name": "...", "arguments": {...}} </tool_call>
TOOL_CALL_JSON_PATTERN = re.compile(
    r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
    re.DOTALL | re.IGNORECASE
)

# Список моделей, которые могут генерировать некорректные форматы tool_calls
MODELS_WITH_MALFORMED_TOOL_CALLS = [
    "xiaomi/mimo",
    "qwen/qwen",
    "deepseek/deepseek-reasoner-v3-0324:free",  # Некоторые версии
]


def is_model_with_malformed_tool_calls(model_id: str) -> bool:
    """
    Проверяет, известна ли модель как генерирующая некорректные форматы tool_calls.
    """
    if not model_id:
        return False
    model_lower = model_id.lower()
    return any(pattern in model_lower for pattern in MODELS_WITH_MALFORMED_TOOL_CALLS)


def parse_malformed_tool_calls(content: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Парсит некорректные форматы tool_calls из текста ответа модели.
    
    Поддерживаемые форматы:
    1. <function=name> <parameter=key>value</parameter> ... </function>
    2. <tool_call> {"name": "...", "arguments": {...}} </tool_call>
    
    Args:
        content: Текст ответа модели
        
    Returns:
        Tuple[str, List[Dict]]: (очищенный текст без tool_calls, список распарсенных tool_calls)
    """
    if not content:
        return content, []
    
    tool_calls = []
    cleaned_content = content
    
    # Формат 1: <function=name> <parameter=key>value</parameter> ... </function>
    for match in MALFORMED_FUNCTION_PATTERN.finditer(content):
        try:
            func_name = match.group(1).strip()
            params_text = match.group(2)
            
            # Парсим параметры
            arguments = {}
            for param_match in MALFORMED_PARAMETER_PATTERN.finditer(params_text):
                param_name = param_match.group(1).strip()
                param_value = param_match.group(2).strip()
                arguments[param_name] = param_value
            
            tool_call = {
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "name": func_name,
                "args": arguments,
            }
            tool_calls.append(tool_call)
            
            # Удаляем из текста
            cleaned_content = cleaned_content.replace(match.group(0), "").strip()
            
            logger.info(f"[parse_malformed] Распарсен tool_call формата 1: {func_name}({list(arguments.keys())})")
            
        except Exception as e:
            logger.warning(f"[parse_malformed] Ошибка парсинга формата 1: {e}")
    
    # Формат 2: <tool_call> {"name": "...", "arguments": {...}} </tool_call>
    for match in TOOL_CALL_JSON_PATTERN.finditer(content):
        try:
            json_str = match.group(1)
            data = json.loads(json_str)
            
            tool_call = {
                "id": data.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                "name": data.get("name", ""),
                "args": data.get("arguments", data.get("args", {})),
            }
            
            if tool_call["name"]:
                tool_calls.append(tool_call)
                cleaned_content = cleaned_content.replace(match.group(0), "").strip()
                logger.info(f"[parse_malformed] Распарсен tool_call формата 2: {tool_call['name']}")
                
        except json.JSONDecodeError as e:
            logger.warning(f"[parse_malformed] Ошибка парсинга JSON в формате 2: {e}")
        except Exception as e:
            logger.warning(f"[parse_malformed] Ошибка парсинга формата 2: {e}")
    
    return cleaned_content, tool_calls


def fix_malformed_ai_message(message: AIMessage, model_id: str = None) -> AIMessage:
    """
    Исправляет AI сообщение с некорректным форматом tool_calls.
    
    Если модель вывела tool_calls в текстовом формате вместо структурированного,
    эта функция извлечет их из текста и создаст правильное сообщение.
    
    Args:
        message: AI сообщение для исправления
        model_id: ID модели (опционально, для логирования)
        
    Returns:
        Исправленное AI сообщение
    """
    content = getattr(message, 'content', '') or ''
    existing_tool_calls = getattr(message, 'tool_calls', None) or []
    
    # Если уже есть tool_calls, не трогаем
    if existing_tool_calls:
        return message
    
    # Проверяем, есть ли в тексте признаки tool_calls
    if '<function' not in content.lower() and '<tool_call>' not in content.lower():
        return message
    
    # Парсим tool_calls из текста
    cleaned_content, parsed_tool_calls = parse_malformed_tool_calls(content)
    
    if not parsed_tool_calls:
        return message
    
    logger.info(f"[fix_malformed] Исправлено {len(parsed_tool_calls)} tool_calls из текста (model={model_id})")
    
    # Создаем новое сообщение с правильными tool_calls
    try:
        new_message = AIMessage(
            content=cleaned_content or "",
            additional_kwargs=getattr(message, 'additional_kwargs', {}) or {},
            tool_calls=parsed_tool_calls,
            id=getattr(message, 'id', None),
            response_metadata=getattr(message, 'response_metadata', None) or {},
        )
        return new_message
    except Exception as e:
        logger.error(f"[fix_malformed] Ошибка создания исправленного сообщения: {e}")
        return message


def filter_tool_messages(messages):
    """
    Фильтрует tool messages, оставляя только те, которые имеют соответствующий tool_call.
    """
    filtered_messages = []
    for idx, msg in enumerate(messages):
        if isinstance(msg, ToolMessage):
            if idx - 1 <= 0:
                continue
            ai_message_tool_called = (
                messages[idx - 1].additional_kwargs.get("function_call")
                or messages[idx - 1].tool_calls
            )
            if not ai_message_tool_called:
                continue
        filtered_messages.append(msg)
    return filtered_messages


def filter_tool_calls(message):
    """
    Удаляет tool_calls из сообщения.
    """
    last_mes = message.model_copy()
    last_mes.tool_calls = None
    last_mes.additional_kwargs["function_call"] = None
    last_mes.additional_kwargs["functions_state_id"] = None
    if "tool_calls" in last_mes.additional_kwargs:
        if not last_mes.content:
            last_mes.content = "."
        del last_mes.additional_kwargs["tool_calls"]
    return last_mes


def validate_and_fix_tool_call_pairs(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Валидирует и исправляет историю сообщений, чтобы каждый tool_call имел соответствующий tool response.
    
    Проблема: Mistral API требует, чтобы количество tool_calls и tool responses совпадало.
    Ошибка: "Not the same number of function calls and responses"
    
    Эта функция:
    1. Собирает все tool_call IDs из AI сообщений
    2. Собирает все tool_call_id из ToolMessage
    3. Удаляет "осиротевшие" tool_calls (без ответа) и tool responses (без вызова)
    
    Args:
        messages: Список сообщений
        
    Returns:
        Очищенный список сообщений с валидными парами tool_call/tool_response
    """
    if not messages:
        return messages
    
    # Шаг 1: Собираем все tool_call IDs и их индексы
    tool_call_ids_by_msg: Dict[int, Set[str]] = {}  # msg_idx -> set of tool_call_ids
    all_tool_call_ids: Set[str] = set()
    
    for idx, msg in enumerate(messages):
        if isinstance(msg, AIMessage) or (hasattr(msg, 'type') and msg.type == "ai"):
            tool_calls = getattr(msg, 'tool_calls', None) or []
            if tool_calls:
                ids_in_msg = set()
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tc_id = tc.get('id') or tc.get('tool_call_id')
                        if tc_id:
                            ids_in_msg.add(tc_id)
                            all_tool_call_ids.add(tc_id)
                if ids_in_msg:
                    tool_call_ids_by_msg[idx] = ids_in_msg
    
    # Шаг 2: Собираем все tool_call_id из ToolMessage
    tool_response_ids: Set[str] = set()
    tool_response_by_id: Dict[str, int] = {}  # tool_call_id -> msg_idx
    
    for idx, msg in enumerate(messages):
        if isinstance(msg, ToolMessage) or (hasattr(msg, 'type') and msg.type == "tool"):
            tool_call_id = getattr(msg, 'tool_call_id', None)
            if tool_call_id:
                tool_response_ids.add(tool_call_id)
                tool_response_by_id[tool_call_id] = idx
    
    # Шаг 3: Находим несоответствия
    orphan_tool_calls = all_tool_call_ids - tool_response_ids  # tool_calls без ответов
    orphan_tool_responses = tool_response_ids - all_tool_call_ids  # ответы без tool_calls
    
    if orphan_tool_calls:
        logger.warning(f"[validate_tool_pairs] Найдено {len(orphan_tool_calls)} tool_calls без ответов: {list(orphan_tool_calls)[:5]}")
    
    if orphan_tool_responses:
        logger.warning(f"[validate_tool_pairs] Найдено {len(orphan_tool_responses)} tool responses без вызовов: {list(orphan_tool_responses)[:5]}")
    
    # Если нет проблем, возвращаем как есть
    if not orphan_tool_calls and not orphan_tool_responses:
        logger.debug("[validate_tool_pairs] История сообщений валидна")
        return messages
    
    # Шаг 4: Создаем очищенный список сообщений
    cleaned_messages = []
    
    for idx, msg in enumerate(messages):
        # Обработка AI сообщений с tool_calls
        if isinstance(msg, AIMessage) or (hasattr(msg, 'type') and msg.type == "ai"):
            tool_calls = getattr(msg, 'tool_calls', None) or []
            
            if tool_calls and idx in tool_call_ids_by_msg:
                # Фильтруем tool_calls, оставляя только те, у которых есть ответы
                valid_tool_calls = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tc_id = tc.get('id') or tc.get('tool_call_id')
                        if tc_id and tc_id not in orphan_tool_calls:
                            valid_tool_calls.append(tc)
                        elif tc_id:
                            logger.info(f"[validate_tool_pairs] Удален orphan tool_call: {tc.get('name', 'unknown')} (id={tc_id[:20]}...)")
                
                if valid_tool_calls:
                    # Создаем новое сообщение с отфильтрованными tool_calls
                    try:
                        new_msg = AIMessage(
                            content=getattr(msg, 'content', '') or '',
                            additional_kwargs=getattr(msg, 'additional_kwargs', {}) or {},
                            tool_calls=valid_tool_calls,
                            id=getattr(msg, 'id', None),
                            response_metadata=getattr(msg, 'response_metadata', None) or {},
                        )
                        cleaned_messages.append(new_msg)
                    except Exception as e:
                        logger.error(f"[validate_tool_pairs] Ошибка при создании AIMessage: {e}")
                        # Если не удалось создать новое сообщение, модифицируем существующее
                        msg.tool_calls = valid_tool_calls
                        cleaned_messages.append(msg)
                else:
                    # Все tool_calls были orphan, добавляем сообщение без tool_calls
                    # но только если есть content
                    content = getattr(msg, 'content', '') or ''
                    if content and content.strip():
                        try:
                            new_msg = AIMessage(
                                content=content,
                                additional_kwargs=getattr(msg, 'additional_kwargs', {}) or {},
                                tool_calls=[],
                                id=getattr(msg, 'id', None),
                                response_metadata=getattr(msg, 'response_metadata', None) or {},
                            )
                            cleaned_messages.append(new_msg)
                            logger.info(f"[validate_tool_pairs] AI сообщение {idx} сохранено без tool_calls (все были orphan)")
                        except Exception as e:
                            logger.error(f"[validate_tool_pairs] Ошибка при создании AIMessage без tool_calls: {e}")
                    else:
                        logger.info(f"[validate_tool_pairs] AI сообщение {idx} пропущено (нет content и все tool_calls orphan)")
            else:
                # Нет tool_calls или нет проблем
                cleaned_messages.append(msg)
        
        # Обработка ToolMessage
        elif isinstance(msg, ToolMessage) or (hasattr(msg, 'type') and msg.type == "tool"):
            tool_call_id = getattr(msg, 'tool_call_id', None)
            
            if tool_call_id and tool_call_id in orphan_tool_responses:
                # Этот ToolMessage не имеет соответствующего tool_call
                logger.info(f"[validate_tool_pairs] Удален orphan ToolMessage (tool_call_id={tool_call_id[:20]}...)")
                continue
            
            cleaned_messages.append(msg)
        
        # Другие типы сообщений
        else:
            cleaned_messages.append(msg)
    
    logger.info(f"[validate_tool_pairs] Очищено: {len(messages)} -> {len(cleaned_messages)} сообщений")
    
    return cleaned_messages


def ensure_tool_call_response_order(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Проверяет и исправляет порядок сообщений: tool response должен идти сразу после соответствующего tool_call.
    
    Некоторые API (например, Mistral) требуют, чтобы tool response шел сразу после AI сообщения с tool_call.
    
    Args:
        messages: Список сообщений
        
    Returns:
        Список сообщений с правильным порядком
    """
    if not messages:
        return messages
    
    # Собираем tool_calls и их позиции
    tool_call_positions: Dict[str, int] = {}  # tool_call_id -> position of AI message
    
    for idx, msg in enumerate(messages):
        if isinstance(msg, AIMessage) or (hasattr(msg, 'type') and msg.type == "ai"):
            tool_calls = getattr(msg, 'tool_calls', None) or []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    tc_id = tc.get('id') or tc.get('tool_call_id')
                    if tc_id:
                        tool_call_positions[tc_id] = idx
    
    # Проверяем порядок tool responses
    issues_found = False
    for idx, msg in enumerate(messages):
        if isinstance(msg, ToolMessage) or (hasattr(msg, 'type') and msg.type == "tool"):
            tool_call_id = getattr(msg, 'tool_call_id', None)
            if tool_call_id and tool_call_id in tool_call_positions:
                expected_pos = tool_call_positions[tool_call_id]
                # ToolMessage должен идти после AI сообщения с tool_call
                if idx <= expected_pos:
                    issues_found = True
                    logger.warning(f"[ensure_order] ToolMessage на позиции {idx} идет до/на AI сообщения с tool_call на позиции {expected_pos}")
    
    if not issues_found:
        return messages
    
    # Если есть проблемы с порядком, пересортируем
    # Группируем сообщения: AI с tool_calls -> соответствующие ToolMessages -> остальные
    result = []
    processed_tool_responses: Set[int] = set()
    
    for idx, msg in enumerate(messages):
        if idx in processed_tool_responses:
            continue
            
        if isinstance(msg, AIMessage) or (hasattr(msg, 'type') and msg.type == "ai"):
            result.append(msg)
            
            # Ищем соответствующие ToolMessages
            tool_calls = getattr(msg, 'tool_calls', None) or []
            tool_call_ids = set()
            for tc in tool_calls:
                if isinstance(tc, dict):
                    tc_id = tc.get('id') or tc.get('tool_call_id')
                    if tc_id:
                        tool_call_ids.add(tc_id)
            
            # Добавляем все ToolMessages для этих tool_calls
            for tool_idx, tool_msg in enumerate(messages):
                if tool_idx in processed_tool_responses:
                    continue
                if isinstance(tool_msg, ToolMessage) or (hasattr(tool_msg, 'type') and tool_msg.type == "tool"):
                    tool_call_id = getattr(tool_msg, 'tool_call_id', None)
                    if tool_call_id and tool_call_id in tool_call_ids:
                        result.append(tool_msg)
                        processed_tool_responses.add(tool_idx)
        
        elif isinstance(msg, ToolMessage) or (hasattr(msg, 'type') and msg.type == "tool"):
            if idx not in processed_tool_responses:
                result.append(msg)
                processed_tool_responses.add(idx)
        else:
            result.append(msg)
    
    logger.info(f"[ensure_order] Порядок сообщений исправлен")
    return result


def sanitize_message_history(messages: List[BaseMessage], model_id: str = None) -> List[BaseMessage]:
    """
    Комплексная санитизация истории сообщений.
    
    Выполняет:
    1. Исправление некорректных форматов tool_calls (для проблемных моделей)
    2. Валидацию пар tool_call/tool_response
    3. Проверку порядка сообщений
    
    Args:
        messages: Список сообщений
        model_id: ID модели (опционально, для определения нужно ли исправлять форматы)
        
    Returns:
        Очищенный и валидный список сообщений
    """
    if not messages:
        return messages
    
    logger.debug(f"[sanitize] Начало санитизации: {len(messages)} сообщений")
    
    # Шаг 0: Исправление некорректных форматов tool_calls
    # Применяем для последнего AI сообщения, если оно содержит текстовые tool_calls
    fixed_messages = []
    for msg in messages:
        if isinstance(msg, AIMessage) or (hasattr(msg, 'type') and msg.type == "ai"):
            fixed_msg = fix_malformed_ai_message(msg, model_id)
            fixed_messages.append(fixed_msg)
        else:
            fixed_messages.append(msg)
    messages = fixed_messages
    
    # Шаг 1: Валидация пар tool_call/tool_response
    messages = validate_and_fix_tool_call_pairs(messages)
    
    # Шаг 2: Проверка порядка
    messages = ensure_tool_call_response_order(messages)
    
    logger.debug(f"[sanitize] Завершено: {len(messages)} сообщений")
    
    return messages
