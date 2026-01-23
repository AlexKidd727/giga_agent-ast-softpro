"""
Патч для langchain-openai для правильной генерации tool call IDs для Mistral API через OpenRouter.

Mistral API требует, чтобы tool call IDs были длиной 9 символов и содержали только буквы и цифры (a-z, A-Z, 0-9).
LangChain может генерировать IDs в неправильном формате (например, "123").
"""

import logging
import random
import string
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Флаг для отслеживания, применен ли патч
_patch_applied = False


def generate_mistral_tool_call_id() -> str:
    """
    Генерирует tool call ID для Mistral API.
    Mistral требует ID длиной 9 символов, содержащий только буквы и цифры (a-z, A-Z, 0-9).
    """
    return ''.join(random.choices(string.ascii_letters + string.digits, k=9))


def normalize_tool_call_id(tool_call_id: str) -> str:
    """
    Нормализует tool call ID для соответствия требованиям Mistral API.
    """
    if tool_call_id and len(tool_call_id) == 9 and tool_call_id.isalnum():
        return tool_call_id
    # Генерируем новый ID, если текущий не соответствует требованиям
    return generate_mistral_tool_call_id()


def patch_langchain_mistral_tool_calls():
    """
    Применяет патч к langchain-openai для правильной генерации tool call IDs для Mistral API.
    
    Этот патч модифицирует метод _get_request_payload, который создает payload для API запроса,
    чтобы tool call IDs соответствовали требованиям Mistral API.
    """
    global _patch_applied
    
    if _patch_applied:
        logger.debug("Патч для Mistral tool call IDs уже применен")
        return
    
    try:
        import langchain_openai.chat_models.base as openai_base
        
        if not hasattr(openai_base, 'ChatOpenAI'):
            logger.error("❌ Класс ChatOpenAI не найден в langchain_openai.chat_models.base")
            return
        
        if not hasattr(openai_base.ChatOpenAI, '_get_request_payload'):
            logger.error("❌ Метод _get_request_payload не найден в ChatOpenAI")
            return
        
        original_get_request_payload = openai_base.ChatOpenAI._get_request_payload
        logger.info(f"✅ Найден метод _get_request_payload в ChatOpenAI: {original_get_request_payload}")
        
        # Создаем патченный метод
        def patched_get_request_payload(
            self,
            input_,
            *,
            stop=None,
            **kwargs
        ):
            """Патченный метод для создания payload с нормализованными tool call IDs для Mistral API"""
            # Получаем model_name для проверки, является ли это Mistral моделью
            model_name = getattr(self, 'model_name', '') or getattr(self, 'model', '')
            base_url = getattr(self, 'openai_api_base', '') or getattr(self, 'base_url', '')
            
            # Проверяем, является ли это Mistral моделью через OpenRouter
            is_openrouter = 'openrouter.ai' in str(base_url).lower()
            is_mistral = 'mistral' in str(model_name).lower()
            is_mistral_via_openrouter = is_openrouter and is_mistral
            
            # Логируем всегда для отладки
            logger.info(f"🔧 ПАТЧ MISTRAL ВЫЗВАН: model={model_name}, base_url={base_url}, is_openrouter={is_openrouter}, is_mistral={is_mistral}, is_mistral_via_openrouter={is_mistral_via_openrouter}")
            
            # Вызываем оригинальный метод
            payload = original_get_request_payload(self, input_, stop=stop, **kwargs)
            
            # Логируем структуру payload для отладки
            if is_mistral_via_openrouter:
                logger.info(f"🔍 MISTRAL PATCH: payload type={type(payload)}, is_dict={isinstance(payload, dict)}, has_messages={'messages' in payload if isinstance(payload, dict) else False}")
                if isinstance(payload, dict) and 'messages' in payload:
                    logger.info(f"🔍 MISTRAL PATCH: payload['messages'] type={type(payload['messages'])}, len={len(payload['messages']) if isinstance(payload['messages'], list) else 'N/A'}")
                # Проверяем также tools в payload
                if isinstance(payload, dict):
                    logger.info(f"🔍 MISTRAL PATCH: payload keys={list(payload.keys())}")
                    if 'tools' in payload:
                        logger.info(f"🔍 MISTRAL PATCH: payload['tools'] type={type(payload['tools'])}, len={len(payload['tools']) if isinstance(payload['tools'], list) else 'N/A'}")
            
            # Нормализуем tool call IDs для Mistral API
            # ВАЖНО: tool_calls могут быть как в assistant сообщениях (ответ от модели), 
            # так и в tool сообщениях (tool_call_id должен соответствовать ID в assistant сообщении)
            if is_mistral_via_openrouter and isinstance(payload, dict) and 'messages' in payload:
                messages = payload['messages']
                normalized_count = 0
                
                # Словарь для маппинга старых ID на новые (для синхронизации tool_call_id в ToolMessage)
                id_mapping = {}
                
                logger.info(f"🔍 MISTRAL PATCH: Обрабатываю {len(messages)} сообщений для нормализации tool call IDs")
                
                # ПЕРВЫЙ ПРОХОД: Нормализуем tool_calls в assistant сообщениях и создаем маппинг
                for idx, msg in enumerate(messages):
                    if not isinstance(msg, dict):
                        continue
                    
                    msg_role = msg.get('role')
                    
                    # Обработка assistant сообщений с tool_calls
                    if msg_role == 'assistant' and 'tool_calls' in msg:
                        tool_calls = msg.get('tool_calls', [])
                        if not isinstance(tool_calls, list):
                            logger.debug(f"🔍 MISTRAL PATCH: tool_calls не является списком, пропускаю")
                            continue
                        
                        logger.info(f"🔍 MISTRAL PATCH: Найдено {len(tool_calls)} tool calls в сообщении {idx}")
                        
                        normalized_tool_calls = []
                        for tool_call_idx, tool_call in enumerate(tool_calls):
                            if not isinstance(tool_call, dict):
                                logger.debug(f"🔍 MISTRAL PATCH: Tool call {tool_call_idx} не является словарем, пропускаю")
                                normalized_tool_calls.append(tool_call)
                                continue
                            
                            tool_call_id = tool_call.get('id', '')
                            original_id = tool_call_id
                            
                            logger.info(f"🔍 MISTRAL PATCH: Tool call {tool_call_idx}, original_id='{original_id}', len={len(original_id)}, isalnum={original_id.isalnum() if original_id else False}")
                            
                            # Нормализуем ID
                            normalized_id = normalize_tool_call_id(tool_call_id)
                            
                            if normalized_id != original_id:
                                logger.warning(
                                    f"⚠️ MISTRAL PATCH: Tool call ID '{original_id}' (len={len(original_id)}) не соответствует требованиям Mistral, "
                                    f"заменяю на '{normalized_id}' (len={len(normalized_id)})"
                                )
                                # Сохраняем маппинг для обновления tool_call_id в ToolMessage
                                id_mapping[original_id] = normalized_id
                                tool_call = tool_call.copy()
                                tool_call['id'] = normalized_id
                                normalized_count += 1
                            else:
                                logger.debug(f"✅ MISTRAL PATCH: Tool call ID '{original_id}' уже соответствует требованиям")
                            
                            normalized_tool_calls.append(tool_call)
                        
                        # Заменяем tool_calls на нормализованные
                        msg['tool_calls'] = normalized_tool_calls
                        logger.info(f"✅ MISTRAL PATCH: Заменены tool_calls в сообщении {idx}")
                
                # ВТОРОЙ ПРОХОД: Обновляем tool_call_id в tool сообщениях согласно маппингу
                if id_mapping:
                    logger.info(f"🔍 MISTRAL PATCH: Обновляю tool_call_id в tool сообщениях согласно маппингу: {id_mapping}")
                    for idx, msg in enumerate(messages):
                        if not isinstance(msg, dict):
                            continue
                        
                        msg_role = msg.get('role')
                        
                        # Обработка tool сообщений - обновляем tool_call_id согласно маппингу
                        if msg_role == 'tool' and 'tool_call_id' in msg:
                            tool_call_id = msg.get('tool_call_id', '')
                            if tool_call_id in id_mapping:
                                new_id = id_mapping[tool_call_id]
                                logger.warning(
                                    f"⚠️ MISTRAL PATCH: Обновляю tool_call_id в tool message {idx} с '{tool_call_id}' на '{new_id}' "
                                    f"для соответствия нормализованному ID из assistant сообщения"
                                )
                                msg['tool_call_id'] = new_id
                                normalized_count += 1
                            else:
                                # Если tool_call_id не в маппинге, но не соответствует требованиям, нормализуем
                                normalized_id = normalize_tool_call_id(tool_call_id)
                                if normalized_id != tool_call_id:
                                    logger.warning(
                                        f"⚠️ MISTRAL PATCH: Tool message {idx} имеет tool_call_id '{tool_call_id}' (len={len(tool_call_id)}), "
                                        f"нормализую до '{normalized_id}' (len={len(normalized_id)})"
                                    )
                                    msg['tool_call_id'] = normalized_id
                                    normalized_count += 1
                
                if normalized_count > 0:
                    logger.info(f"✅ MISTRAL PATCH: Нормализовано {normalized_count} tool call IDs для Mistral API")
                    # Убеждаемся, что изменения сохранены
                    payload['messages'] = messages
                else:
                    logger.info(f"ℹ️ MISTRAL PATCH: Не найдено tool calls для нормализации")
            
            return payload
        
        # Применяем патч к классу ChatOpenAI
        openai_base.ChatOpenAI._get_request_payload = patched_get_request_payload
        logger.info(f"✅ Патч для _get_request_payload применен к ChatOpenAI для Mistral API")
        
        # Проверяем, что патч применен
        if openai_base.ChatOpenAI._get_request_payload == patched_get_request_payload:
            logger.info(f"✅ Патч успешно применен и проверен для ChatOpenAI")
        else:
            logger.error(f"❌ ОШИБКА: Патч не применен к ChatOpenAI!")
        
        _patch_applied = True
        logger.info(f"✅ Флаг _patch_applied установлен в True")
                
    except ImportError as e:
        logger.warning(f"⚠️  Не удалось импортировать langchain_openai: {e}")
    except Exception as e:
        logger.error(f"❌ Ошибка при применении патча для Mistral tool call IDs: {e}", exc_info=True)


def unpatch_langchain_mistral_tool_calls():
    """Откатывает патч (если нужно)"""
    global _patch_applied
    
    if not _patch_applied:
        return
    
    try:
        import langchain_openai.chat_models.base as openai_base
        
        # Восстанавливаем оригинальные методы
        # (Это требует сохранения оригинальных методов, что не реализовано в упрощенной версии)
        logger.warning("⚠️  Откат патча не реализован полностью")
        _patch_applied = False
        
    except Exception as e:
        logger.error(f"❌ Ошибка при откате патча: {e}")


# Автоматически применяем патч при импорте модуля
try:
    logger.info("🔧 Попытка автоматически применить патч для Mistral tool call IDs при импорте модуля")
    patch_langchain_mistral_tool_calls()
    logger.info("✅ Автоматическое применение патча для Mistral tool call IDs завершено")
except Exception as e:
    logger.error(f"❌ Не удалось автоматически применить патч для Mistral tool call IDs: {e}", exc_info=True)
