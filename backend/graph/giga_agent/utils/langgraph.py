import copy
import inspect
import logging
from typing import Any, Annotated, get_origin, get_args

try:
    from langgraph.prebuilt import InjectedState
except ImportError:
    InjectedState = None

logger = logging.getLogger(__name__)


def inject_tool_args_compat(
    tool_node: Any,
    tool_call: dict,
    state: Any,
    store: Any,
) -> dict:
    """Inject tool args the same way as newer langgraph versions do.

    NOTE: помогаем сохранить совместимость с версиями langgraph,
    где у ToolNode ещё нет метода `inject_tool_args`.
    """
    base_method = getattr(tool_node, "inject_tool_args", None)
    if callable(base_method):
        try:
            result = base_method(tool_call, state, store)
            # Проверяем, что результат валиден (имеет структуру tool_call)
            if isinstance(result, dict) and "args" in result:
                return result
        except (AttributeError, TypeError, Exception):
            # Если метод существует, но не работает, продолжаем с нашей логикой
            pass

    tools_by_name = getattr(tool_node, "tools_by_name", {})
    tool_name = tool_call.get("name")
    if tool_name not in tools_by_name:
        return tool_call

    tool_call_copy = copy.deepcopy(tool_call)
    tool_call_copy.setdefault("args", {})
    messages_key = getattr(tool_node, "messages_key", "messages")
    state_args_map = getattr(tool_node, "tool_to_state_args", {}).get(tool_name, {})

    # ВАЖНО (args compat):
    # MCP инструмент `process_financial_question` в некоторых подсказках/планах может вызываться
    # с аргументом `query`, но реализация сервера ожидает `question`.
    # Чтобы не ломать старые цепочки и "планы", поддерживаем алиас query->question.
    try:
        if tool_name == "process_financial_question":
            args = tool_call_copy.get("args")
            if isinstance(args, dict) and "query" in args and "question" not in args:
                args["question"] = args.pop("query")
            # Также иногда в планах ошибочно передают user_request (как у tinkoff_agent).
            if isinstance(args, dict) and "user_request" in args and "question" not in args:
                args["question"] = args.pop("user_request")
        # Tinkoff agent ожидает user_request, но LLM часто передаёт query.
        if tool_name == "tinkoff_agent":
            args = tool_call_copy.get("args")
            if isinstance(args, dict) and "query" in args and "user_request" not in args:
                args["user_request"] = args.pop("query")
    except Exception:
        # Не даём совместимости по аргументам ломать выполнение tools
        pass
    
    # Если tool_to_state_args пуст, пытаемся определить InjectedState через сигнатуру
    if not state_args_map and InjectedState is not None:
        try:
            tool_obj = tools_by_name.get(tool_name)
            if tool_obj:
                # Получаем исходную функцию
                func = getattr(tool_obj, 'func', None) or getattr(tool_obj, 'coroutine', None)
                if not func:
                    # Пытаемся получить через другие атрибуты
                    if hasattr(tool_obj, '__wrapped__'):
                        func = tool_obj.__wrapped__
                    elif callable(tool_obj):
                        func = tool_obj
                
                if func:
                    sig = inspect.signature(func)
                    logger.debug(f"🔍 Проверка сигнатуры для {tool_name}: {sig.parameters.keys()}")
                    for param_name, param in sig.parameters.items():
                        # Проверяем, есть ли InjectedState в аннотации
                        annotation = param.annotation
                        if annotation is inspect.Parameter.empty:
                            continue
                        
                        logger.debug(f"🔍 Параметр {param_name}: annotation={annotation}, type={type(annotation)}")
                        
                        # Проверяем Annotated[..., InjectedState]
                        try:
                            origin = get_origin(annotation)
                            if origin is Annotated:
                                args = get_args(annotation)
                                logger.debug(f"🔍 Annotated параметр {param_name}: args={args}")
                                # args[0] - это тип, args[1:] - это метаданные (включая InjectedState)
                                if len(args) > 1 and InjectedState in args[1:]:
                                    # Добавляем в state_args_map
                                    state_args_map[param_name] = None  # None означает весь state
                                    logger.info(f"✅ Найден InjectedState для параметра {param_name} в {tool_name}")
                        except (TypeError, AttributeError) as e:
                            logger.debug(f"🔍 Ошибка при проверке Annotated для {param_name}: {e}")
                            # Если не Annotated, проверяем прямой InjectedState
                            if annotation is InjectedState:
                                state_args_map[param_name] = None
                                logger.info(f"✅ Найден прямой InjectedState для параметра {param_name} в {tool_name}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при определении InjectedState для {tool_name}: {e}", exc_info=True)
    
    if state_args_map:
        logger.debug(f"🔍 Найдены state_args_map для {tool_name}: {state_args_map}")
        normalized_state = state
        required_fields = list(state_args_map.values())
        
        # Логируем информацию о state
        if isinstance(normalized_state, dict):
            logger.debug(f"🔍 State для {tool_name}: keys={list(normalized_state.keys())}, has_secrets={'secrets' in normalized_state}")
            if "secrets" in normalized_state:
                secrets_count = len(normalized_state.get("secrets", [])) if isinstance(normalized_state.get("secrets"), list) else 0
                logger.debug(f"🔍 State содержит {secrets_count} секретов")
        elif normalized_state is not None:
            logger.debug(f"🔍 State для {tool_name}: type={type(normalized_state)}")
        
        if isinstance(normalized_state, list):
            if len(required_fields) == 1 and (
                required_fields[0] == messages_key or required_fields[0] is None
            ):
                normalized_state = {messages_key: normalized_state}
            else:
                required_fields_str = ", ".join(
                    field for field in required_fields if field
                )
                raise ValueError(
                    "Invalid input to ToolNode. Tool "
                    f"{tool_name} requires graph state dict as input. "
                    f"State should contain fields {required_fields_str}."
                )

        if isinstance(normalized_state, dict):
            tool_state_args = {
                tool_arg: normalized_state[state_field] if state_field else normalized_state
                for tool_arg, state_field in state_args_map.items()
            }
            logger.info(f"✅ Инжектируем state для {tool_name}: параметры={list(tool_state_args.keys())}")
        else:
            tool_state_args = {
                tool_arg: getattr(normalized_state, state_field)
                if state_field
                else normalized_state
                for tool_arg, state_field in state_args_map.items()
            }
            logger.info(f"✅ Инжектируем state для {tool_name} (объект): параметры={list(tool_state_args.keys())}")

        tool_call_copy["args"] = {**tool_call_copy["args"], **tool_state_args}
    else:
        logger.debug(f"ℹ️ State не требуется для {tool_name} (state_args_map пуст)")

    store_arg = getattr(tool_node, "tool_to_store_arg", {}).get(tool_name)
    if store_arg:
        if store is None:
            raise ValueError(
                "Cannot inject store into tools with InjectedStore annotations - "
                "please compile your graph with a store."
            )
        tool_call_copy["args"] = {**tool_call_copy["args"], store_arg: store}

    return tool_call_copy

