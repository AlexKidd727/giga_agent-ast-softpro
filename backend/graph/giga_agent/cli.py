import asyncio
import json
from io import BytesIO
from uuid import uuid4

import plotly
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tool_graph import workflow

import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from base64 import b64decode


def show_attachments(attachments):
    for attachment in attachments:
        if "application/vnd.plotly.v1+json" in attachment:
            data = json.dumps(attachment["application/vnd.plotly.v1+json"])
            plot = plotly.io.from_json(data)
            img = mpimg.imread(
                BytesIO(plotly.io.to_image(plot, format="png")), format="png"
            )
            plt.imshow(img)
            plt.show()
        if "image/png" in attachment:
            img = mpimg.imread(
                BytesIO(b64decode(attachment["image/png"])), format="png"
            )
            plt.imshow(img)
            plt.show()


async def main():
    checkpointer = InMemorySaver()
    graph = workflow.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": str(uuid4())}}
    is_interrupted = False
    while prompt := input("Human (q to quit): "):
        prompt = prompt.strip()
        if prompt == "q":
            break
        if is_interrupted:
            send = Command(
                resume={
                    "type": "approve" if prompt == "a" else "comment",
                    "message": prompt,
                },
            )
            is_interrupted = False
        else:
            send = {
                "messages": [
                    HumanMessage(additional_kwargs={"user_input": prompt}, content="")
                ],
                "file_ids": ["6790848b-15f2-4bf0-b82f-5a65b37d2e79"],
            }
        events = graph.astream(
            send,
            config,
            stream_mode=["values", "updates"],
        )
        async for event in events:
            if event[0] == "values":
                if "messages" in event[1]:
                    messages = [event[1]["messages"][-1]]
                    for message in messages:
                        message.pretty_print()
                        if message.additional_kwargs.get("tool_attachments"):
                            show_attachments(
                                message.additional_kwargs.get("tool_attachments")
                            )
            if event[0] == "updates":
                is_interrupted = "__interrupt__" in event[1]
            if is_interrupted:
                print(
                    "Interrupted! a — to approve tool_call, other — to decline and comment"
                )


asyncio.run(main())
