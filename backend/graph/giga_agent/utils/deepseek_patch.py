"""
Патч для langchain-openai/langchain-deepseek для правильной обработки reasoning_content.

Этот модуль патчит методы сериализации сообщений, чтобы reasoning_content
передавался на верхнем уровне assistant сообщения, как требует DeepSeek API 3.2.
"""

import json
import logging
from typing import Any, Dict, List
from langchain_core.messages import AIMessage, BaseMessage

logger = logging.getLogger(__name__)

# Флаг для отслеживания, применен ли патч
_patch_applied = False


def patch_langchain_deepseek():
    """
    Применяет патч к langchain-openai для правильной обработки reasoning_content.
    
    Этот патч модифицирует метод _get_request_payload, который создает payload для API запроса,
    чтобы reasoning_content передавался на верхнем уровне assistant сообщения.
    """
    global _patch_applied
    
    if _patch_applied:
        logger.debug("Патч уже применен")
        return
    
    try:
        # Сначала пытаемся патчить langchain_deepseek, так как именно он используется
        try:
            import langchain_deepseek.chat_models as deepseek_base
            if hasattr(deepseek_base, 'ChatDeepSeek'):
                deepseek_class = deepseek_base.ChatDeepSeek
                if hasattr(deepseek_class, '_get_request_payload'):
                    original_get_request_payload = deepseek_class._get_request_payload
                    logger.info(f"✅ Найден метод _get_request_payload в ChatDeepSeek: {original_get_request_payload}")
                    target_class = deepseek_class
                    target_name = "ChatDeepSeek"
                else:
                    raise AttributeError("ChatDeepSeek не имеет _get_request_payload")
            else:
                raise AttributeError("ChatDeepSeek не найден")
        except (ImportError, AttributeError) as e:
            logger.warning(f"⚠️  Не удалось найти langchain_deepseek, пытаемся патчить langchain_openai: {e}")
            # Fallback к langchain_openai
            import langchain_openai.chat_models.base as openai_base
            
            if not hasattr(openai_base, 'ChatOpenAI'):
                logger.error("❌ Класс ChatOpenAI не найден в langchain_openai.chat_models.base")
                return
            
            has_method = hasattr(openai_base.ChatOpenAI, '_get_request_payload')
            if has_method:
                original_get_request_payload = openai_base.ChatOpenAI._get_request_payload
                logger.info(f"✅ Найден метод _get_request_payload в ChatOpenAI: {original_get_request_payload}")
                target_class = openai_base.ChatOpenAI
                target_name = "ChatOpenAI"
            else:
                logger.error("❌ Метод _get_request_payload не найден в ChatOpenAI")
                return
        
        # Создаем патченный метод
        def patched_get_request_payload(
            self,
            input_,
            *,
            stop=None,
            **kwargs
        ):
            """Патченный метод для создания payload с поддержкой reasoning_content для DeepSeek"""
            # Логируем вызов патченного метода
            model_name = getattr(self, 'model_name', '') or getattr(self, 'model', '')
            is_deepseek = 'deepseek' in str(model_name).lower()
            logger.info(f"🔧 ПАТЧ ВЫЗВАН: model={model_name}, is_deepseek={is_deepseek}")
            
            # Вызываем оригинальный метод
            # Для ChatDeepSeek это вызовет super()._get_request_payload() внутри оригинального метода
            payload = original_get_request_payload(self, input_, stop=stop, **kwargs)
            
            logger.info(f"🔧 ПАТЧ: payload keys={list(payload.keys()) if isinstance(payload, dict) else 'not_dict'}, has_messages={'messages' in payload if isinstance(payload, dict) else False}")
            
            # КРИТИЧЕСКИ ВАЖНО: Создаем глубокую копию payload, чтобы изменения не потерялись
            # LangChain может модифицировать payload после нашего патча
            import copy
            if isinstance(payload, dict) and 'messages' in payload:
                # Сохраняем обработанные сообщения отдельно для финальной проверки
                processed_messages = copy.deepcopy(payload['messages'])
            
            if is_deepseek and 'messages' in payload:
                # Обрабатываем сообщения для DeepSeek API 3.2
                # reasoning_content должен быть на верхнем уровне assistant сообщений
                messages = payload['messages']
                assistant_count = 0
                tool_count = 0
                fixed_count = 0
                
                logger.info(f"🔍 Обработка payload для DeepSeek: {len(messages)} сообщений")
                
                for idx, msg in enumerate(messages):
                    if not isinstance(msg, dict):
                        logger.warning(f"⚠️  Сообщение {idx} не является словарем: {type(msg)}")
                        continue
                    
                    msg_role = msg.get('role')
                    
                    # Обработка assistant сообщений
                    if msg_role == 'assistant':
                        assistant_count += 1
                        # КРИТИЧЕСКИ ВАЖНО: DeepSeek API 3.2 требует reasoning_content на верхнем уровне
                        # Проверяем, есть ли reasoning_content в additional_kwargs
                        additional_kwargs = msg.get('additional_kwargs', {})
                        
                        # Извлекаем reasoning_content из additional_kwargs, если он там есть
                        reasoning_content = None
                        if isinstance(additional_kwargs, dict) and 'reasoning_content' in additional_kwargs:
                            reasoning_content = additional_kwargs.get('reasoning_content')
                        
                        # КРИТИЧЕСКИ ВАЖНО: DeepSeek API требует reasoning_content как строку или отсутствие поля
                        # НО согласно документации, если поле отсутствует, API выдает ошибку
                        # Поэтому устанавливаем пустую строку "", если reasoning_content отсутствует
                        if reasoning_content is None or reasoning_content == "":
                            reasoning_content = ""  # Пустая строка вместо None
                            logger.debug(f"🔧 Сообщение {idx}: reasoning_content отсутствовал, установлена пустая строка")
                        else:
                            logger.debug(f"🔧 Сообщение {idx}: reasoning_content найден: {str(reasoning_content)[:50] if len(str(reasoning_content)) > 50 else reasoning_content}")
                        
                        # КРИТИЧЕСКИ ВАЖНО: Устанавливаем reasoning_content на верхний уровень
                        # Всегда устанавливаем как строку (пустую или с содержимым)
                        msg['reasoning_content'] = str(reasoning_content) if reasoning_content is not None else ""
                        fixed_count += 1
                        
                        # ФИНАЛЬНАЯ ПРОВЕРКА: убеждаемся, что поле точно установлено как строка
                        if 'reasoning_content' not in msg:
                            msg['reasoning_content'] = ""
                            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Сообщение {idx} все еще не имеет reasoning_content после обработки!")
                        elif msg['reasoning_content'] is None:
                            msg['reasoning_content'] = ""
                            logger.warning(f"⚠️  Сообщение {idx}: reasoning_content был None, заменен на пустую строку")
                        elif not isinstance(msg['reasoning_content'], str):
                            msg['reasoning_content'] = str(msg['reasoning_content']) if msg['reasoning_content'] else ""
                            logger.warning(f"⚠️  Сообщение {idx}: reasoning_content был не строкой ({type(msg['reasoning_content'])}), преобразован в строку")
                    
                    # Обработка tool сообщений (ToolMessage)
                    elif msg_role == 'tool':
                        tool_count += 1
                        # КРИТИЧЕСКИ ВАЖНО: ToolMessage для DeepSeek API должен иметь ТОЛЬКО:
                        # role='tool', content (строка), tool_call_id
                        # Удаляем ВСЕ дополнительные поля, которые могут вызвать проблемы
                        
                        # Логируем исходное состояние для отладки
                        original_keys = list(msg.keys())
                        logger.info(f"🔍 ToolMessage {idx} до обработки: keys={original_keys}, role={msg.get('role')}")
                        logger.info(f"🔍 ToolMessage {idx} additional_kwargs до обработки: {msg.get('additional_kwargs', {})}")
                        
                        # Удаляем reasoning_content, если он есть
                        if 'reasoning_content' in msg:
                            logger.warning(f"⚠️  Сообщение {idx} (tool): обнаружен reasoning_content на верхнем уровне, удаляем")
                            del msg['reasoning_content']
                        
                        # КРИТИЧЕСКИ ВАЖНО: Удаляем additional_kwargs полностью для DeepSeek API
                        # DeepSeek API не поддерживает дополнительные поля в tool сообщениях
                        if 'additional_kwargs' in msg:
                            additional_kwargs = msg.get('additional_kwargs', {})
                            logger.debug(f"🔍 ToolMessage {idx}: удаляем additional_kwargs={list(additional_kwargs.keys()) if isinstance(additional_kwargs, dict) else 'not_dict'}")
                            del msg['additional_kwargs']
                        
                        # Убеждаемся, что tool сообщение имеет правильную структуру
                        # DeepSeek API ожидает: role='tool', content (строка), tool_call_id
                        if 'content' not in msg:
                            logger.error(f"❌ Сообщение {idx} (tool): отсутствует content!")
                        else:
                            content_len = len(str(msg.get('content', '')))
                            logger.debug(f"🔍 ToolMessage {idx}: content length={content_len}")
                        
                        if 'tool_call_id' not in msg:
                            logger.warning(f"⚠️  Сообщение {idx} (tool): отсутствует tool_call_id")
                        else:
                            tool_call_id = msg.get('tool_call_id', '')
                            logger.debug(f"🔍 ToolMessage {idx}: tool_call_id={tool_call_id[:30] if tool_call_id else 'N/A'}")
                        
                        # Удаляем все остальные поля, которые не нужны для DeepSeek API
                        allowed_keys = {'role', 'content', 'tool_call_id'}
                        keys_to_remove = [k for k in msg.keys() if k not in allowed_keys]
                        if keys_to_remove:
                            logger.warning(f"⚠️  Сообщение {idx} (tool): удаляем лишние поля: {keys_to_remove}")
                            for key in keys_to_remove:
                                del msg[key]
                        
                        # Финальная проверка структуры
                        final_keys = list(msg.keys())
                        logger.info(f"✅ ToolMessage {idx} после обработки: keys={final_keys}, role={msg.get('role')}, has_content={'content' in msg}, has_tool_call_id={'tool_call_id' in msg}")
                        logger.info(f"✅ ToolMessage {idx} финальный payload: {json.dumps({k: str(v)[:50] if len(str(v)) > 50 else v for k, v in msg.items()}, ensure_ascii=False)}")
                
                # ФИНАЛЬНАЯ ПРОВЕРКА: убеждаемся, что ВСЕ assistant сообщения имеют reasoning_content как строку
                final_fixed = 0
                for idx, msg in enumerate(messages):
                    if isinstance(msg, dict) and msg.get('role') == 'assistant':
                        if 'reasoning_content' not in msg:
                            msg['reasoning_content'] = ""
                            final_fixed += 1
                            logger.error(f"❌ ФИНАЛЬНАЯ ПРОВЕРКА: Сообщение {idx} не имеет reasoning_content, установлена пустая строка")
                        elif msg['reasoning_content'] is None:
                            msg['reasoning_content'] = ""
                            final_fixed += 1
                            logger.error(f"❌ ФИНАЛЬНАЯ ПРОВЕРКА: Сообщение {idx} имеет reasoning_content=None, заменен на пустую строку")
                        elif not isinstance(msg['reasoning_content'], str):
                            msg['reasoning_content'] = str(msg['reasoning_content']) if msg['reasoning_content'] else ""
                            final_fixed += 1
                            logger.error(f"❌ ФИНАЛЬНАЯ ПРОВЕРКА: Сообщение {idx} имеет reasoning_content не строкой ({type(msg['reasoning_content'])}), преобразован")
                        else:
                            # Проверяем, что это действительно строка (даже пустая)
                            logger.debug(f"✅ ФИНАЛЬНАЯ ПРОВЕРКА: Сообщение {idx} имеет reasoning_content как строку (длина={len(msg['reasoning_content'])})")
                
                if fixed_count > 0 or final_fixed > 0:
                    logger.warning(f"⚠️  Исправлено {fixed_count} из {assistant_count} assistant сообщений без reasoning_content, финальная проверка исправила {final_fixed}")
                logger.info(f"✅ Обработан payload для DeepSeek: {len(messages)} сообщений, {assistant_count} assistant, {tool_count} tool, исправлено {fixed_count + final_fixed}")
                
                # КРИТИЧЕСКИ ВАЖНО: Убеждаемся, что изменения сохранены в payload
                # Перезаписываем messages в payload, чтобы гарантировать, что изменения не потеряются
                payload['messages'] = messages
                logger.debug(f"🔧 ПАТЧ: payload['messages'] обновлен, всего сообщений: {len(payload['messages'])}")
            
            # ФИНАЛЬНАЯ ПРОВЕРКА payload перед возвратом
            if is_deepseek and isinstance(payload, dict) and 'messages' in payload:
                final_messages = payload.get('messages', [])
                assistant_without_reasoning = []
                for idx, msg in enumerate(final_messages):
                    if isinstance(msg, dict) and msg.get('role') == 'assistant':
                        if 'reasoning_content' not in msg or msg.get('reasoning_content') is None or not isinstance(msg.get('reasoning_content'), str):
                            assistant_without_reasoning.append(idx)
                            # Принудительно исправляем
                            msg['reasoning_content'] = ""
                            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПЕРЕД ОТПРАВКОЙ: Сообщение {idx} не имеет reasoning_content, принудительно установлена пустая строка")
                
                if assistant_without_reasoning:
                    logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {len(assistant_without_reasoning)} assistant сообщений без reasoning_content перед отправкой: {assistant_without_reasoning}")
                else:
                    logger.info(f"✅ ФИНАЛЬНАЯ ПРОВЕРКА: Все assistant сообщения имеют reasoning_content как строку")
            
            return payload
        
        # Применяем патч к целевому классу
        target_class._get_request_payload = patched_get_request_payload
        logger.info(f"✅ Патч для _get_request_payload применен к {target_name} для DeepSeek API 3.2")
        
        # Проверяем, что патч применен
        if target_class._get_request_payload == patched_get_request_payload:
            logger.info(f"✅ Патч успешно применен и проверен для {target_name}")
            logger.info(f"✅ Метод _get_request_payload теперь: {target_class._get_request_payload}")
        else:
            logger.error(f"❌ ОШИБКА: Патч не применен к {target_name}!")
            logger.error(f"❌ Ожидался: {patched_get_request_payload}")
            logger.error(f"❌ Получен: {target_class._get_request_payload}")
        
        _patch_applied = True
        logger.info(f"✅ Флаг _patch_applied установлен в True")
                
    except ImportError as e:
        logger.warning(f"⚠️  Не удалось импортировать langchain_openai: {e}")
    except Exception as e:
        logger.error(f"❌ Ошибка при применении патча: {e}", exc_info=True)


def unpatch_langchain_deepseek():
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
# (можно отключить, если нужно применять вручную)
try:
    logger.info("🔧 Попытка автоматически применить патч для DeepSeek при импорте модуля")
    patch_langchain_deepseek()
    logger.info("✅ Автоматическое применение патча завершено")
except Exception as e:
    logger.error(f"❌ Не удалось автоматически применить патч: {e}", exc_info=True)

