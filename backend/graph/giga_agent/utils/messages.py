from langchain_core.messages import ToolMessage


def filter_tool_messages(messages):
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
    last_mes = message.model_copy()
    last_mes.tool_calls = None
    last_mes.additional_kwargs["function_call"] = None
    last_mes.additional_kwargs["functions_state_id"] = None
    if "tool_calls" in last_mes.additional_kwargs:
        if not last_mes.content:
            last_mes.content = "."
        del last_mes.additional_kwargs["tool_calls"]
    return last_mes
