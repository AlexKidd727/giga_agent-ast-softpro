from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import RunnableConfig

from giga_agent.agents.presentation_agent.config import PresentationState, llm
from giga_agent.agents.presentation_agent.prompts.ru import PLAN_PROMPT, FORMAT


async def plan_node(state: PresentationState, config: RunnableConfig):
    # Проверяем, что state содержит необходимые данные
    if "messages" not in state or not state["messages"]:
        raise ValueError("Ошибка: state не содержит messages или messages пустой.")
    if "task" not in state or state["task"] is None:
        task_info = ""
    else:
        task_info = f"\nДополнительная информация: {state['task']}"
    
    ch = PLAN_PROMPT | llm
    resp = await ch.ainvoke(
        {
            "messages": state["messages"]
            + [
                (
                    "user",
                    "Придумай план презентации исходя из переписки выше"
                    + FORMAT
                    + task_info,
                )
            ]
        }
    )

    if config["configurable"].get("print_messages", False):
        resp.pretty_print()

    json_response = await ch.ainvoke(
        {
            "messages": state["messages"]
            + [("user", "Придумай план презентации исходя из переписки выше"), resp]
            + [
                (
                    "user",
                    """Переведи план выше в формат JSON.
Объекты:
```python
class Slide:
    name: str = Field("Название слайда")
    attachments: Optional[list[str]] = Field("Список вложений из предыдущей переписки (добавляй только если подходит к слайду)")
```
Формат:
{
    "slides": [Объекты типа Slide]
}""",
                )
            ]
        }
    )
    if config["configurable"].get("print_messages", False):
        json_response.pretty_print()
    # Проверяем, что json_response содержит content
    if json_response is None or not hasattr(json_response, "content") or json_response.content is None:
        raise ValueError("Ошибка: json_response не содержит content или content равен None.")
    data = JsonOutputParser().parse(json_response.content)
    # Проверяем, что data содержит slides
    if data is None or not isinstance(data, dict):
        raise ValueError("Ошибка: data не является словарем или равен None.")
    slides = data.get("slides")
    if slides is None:
        slides = []
    
    if "task" not in state or state["task"] is None:
        task_info = ""
    else:
        task_info = f"\nДополнительная информация: {state['task']}"
    
    return {
        "slides": slides,
        "messages": [
            (
                "user",
                "Придумай план презентации исходя из переписки выше"
                + FORMAT
                + task_info,
            ),
            resp,
        ],
    }
