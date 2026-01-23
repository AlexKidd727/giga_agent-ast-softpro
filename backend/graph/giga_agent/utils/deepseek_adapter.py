"""
Адаптер для DeepSeek API 3.2, который правильно обрабатывает reasoning_content.

В DeepSeek 3.2 reasoning_content должен быть на верхнем уровне assistant сообщения,
а не в additional_kwargs. Этот модуль предоставляет функции для правильной
сериализации сообщений перед отправкой в API.
"""

import logging
from typing import List, Any, Dict
from langchain_core.messages import AIMessage, BaseMessage

logger = logging.getLogger(__name__)


def convert_messages_for_deepseek(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    """
    Преобразует сообщения LangChain в формат, требуемый DeepSeek API 3.2.
    
    Для assistant сообщений reasoning_content должен быть на верхнем уровне,
    а не в additional_kwargs.
    
    Args:
        messages: Список сообщений LangChain
        
    Returns:
        Список словарей в формате DeepSeek API
    """
    converted = []
    
    for msg in messages:
        if isinstance(msg, AIMessage) or (hasattr(msg, 'type') and msg.type == "ai"):
            # Для assistant сообщений
            msg_dict = {
                "role": "assistant",
                "content": getattr(msg, 'content', '') or None,
            }
            
            # КРИТИЧЕСКИ ВАЖНО: reasoning_content должен быть на верхнем уровне
            # Сначала проверяем additional_kwargs
            additional_kwargs = getattr(msg, 'additional_kwargs', {})
            if isinstance(additional_kwargs, dict):
                reasoning_content = additional_kwargs.get('reasoning_content', "")
            else:
                reasoning_content = ""
            
            # Также проверяем атрибут верхнего уровня (если используется DeepSeekAIMessage)
            if hasattr(msg, 'reasoning_content'):
                reasoning_content = getattr(msg, 'reasoning_content', "") or reasoning_content
            
            # Устанавливаем reasoning_content на верхний уровень
            # DeepSeek API требует это поле, даже если оно пустое
            msg_dict["reasoning_content"] = reasoning_content if reasoning_content else None
            
            # Добавляем tool_calls, если есть
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                msg_dict["tool_calls"] = msg.tool_calls
                
            converted.append(msg_dict)
            
        elif hasattr(msg, 'type') and msg.type == "human":
            # Для user сообщений
            converted.append({
                "role": "user",
                "content": getattr(msg, 'content', '') or "",
            })
            
        elif hasattr(msg, 'type') and msg.type == "system":
            # Для system сообщений
            converted.append({
                "role": "system",
                "content": getattr(msg, 'content', '') or "",
            })
            
        elif hasattr(msg, 'type') and msg.type == "tool":
            # Для tool сообщений
            converted.append({
                "role": "tool",
                "content": getattr(msg, 'content', '') or "",
                "tool_call_id": getattr(msg, 'tool_call_id', ''),
            })
        else:
            # Для других типов сообщений используем стандартную сериализацию
            try:
                msg_dict = msg.dict()
                converted.append(msg_dict)
            except Exception as e:
                logger.warning(f"Не удалось сериализовать сообщение типа {type(msg)}: {e}")
                # Пытаемся создать базовое сообщение
                converted.append({
                    "role": "user" if not hasattr(msg, 'type') else "assistant",
                    "content": str(getattr(msg, 'content', '')),
                })
    
    return converted


def ensure_reasoning_content_in_messages(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Гарантирует наличие reasoning_content во всех assistant сообщениях.
    
    Args:
        messages: Список сообщений LangChain
        
    Returns:
        Список сообщений с гарантированным reasoning_content
    """
    processed = []
    
    for msg in messages:
        if isinstance(msg, AIMessage) or (hasattr(msg, 'type') and msg.type == "ai"):
            # Убеждаемся, что additional_kwargs существует и является dict
            if not hasattr(msg, 'additional_kwargs') or not isinstance(msg.additional_kwargs, dict):
                msg.additional_kwargs = {}
            
            # Устанавливаем reasoning_content, если его нет
            if "reasoning_content" not in msg.additional_kwargs:
                msg.additional_kwargs["reasoning_content"] = ""
                logger.debug(f"Установлен reasoning_content для сообщения")
        
        processed.append(msg)
    
    return processed

