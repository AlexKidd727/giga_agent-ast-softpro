import asyncio
import base64
import re

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import (
    RunnableConfig,
    RunnableParallel,
    RunnablePassthrough,
)
from giga_agent.agents.presentation_agent.config import PresentationState, llm
from giga_agent.agents.presentation_agent.prompts.ru import IMAGE_PROMPT
from giga_agent.generators.image import load_image_gen
from giga_agent.utils.jupyter import REPLUploader, RunUploadFile


async def image_node(state: PresentationState, config: RunnableConfig):
    # Проверяем, что state содержит slides
    if "slides" not in state or not state["slides"]:
        return {"slide_map": {}, "images_uploaded": state.get("images_uploaded", {})}
    
    slides_for_images = []
    uuid_pattern = (
        "^[0-9a-f]{8}-[0-9a-f]{4}-[0-5][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    for idx, slide in enumerate(state["slides"]):
        if not slide.get("attachments"):
            slides_for_images.append(f"{idx + 1}. {slide.get('name')}")
        else:
            graph_not_valid = True
            for graph in slide["attachments"]:
                if graph.startswith("attachment:") and graph_not_valid:
                    graph_not_valid = False
                    break
                elif re.match(uuid_pattern, graph):
                    graph_not_valid = False
                    break
            if graph_not_valid:
                slides_for_images.append(f"{idx + 1}. {slide.get('name')}")
    slides_text = "\n".join(slides_for_images)
    img_chain = (
        IMAGE_PROMPT
        | llm
        | RunnableParallel(
            {"message": RunnablePassthrough(), "json": JsonOutputParser()}
        )
    ).with_retry()
    img_resp = await img_chain.ainvoke(
        {
            "messages": state["messages"][-2:]
            + [
                (
                    "user",
                    f"Придумай список изображений для следующих слайдов: {slides_text}. Ты можешь придумывать не для каждого слайда изображения, а только там где считаешь нужным. Помни, что графики мы будем брать исходя из переписки с пользователем выше! Тебе нужно сгенерировать описание изображения для: предметов, интерьеров, ландшафтов, людей и т.д. все, что может относится к презентации! Инфографика не нужна! Изображения нужны только в тех слайдах где нет инфографики!",
                ),
            ]
        }
    )
    # Проверяем, что img_resp содержит json и images
    if "json" not in img_resp or img_resp["json"] is None:
        raise ValueError("Ошибка: img_resp не содержит json или json равен None.")
    if "images" not in img_resp["json"]:
        raise ValueError("Ошибка: img_resp['json'] не содержит ключ 'images'.")
    images = img_resp["json"]["images"]
    if config["configurable"].get("print_messages", False):
        img_resp["message"].pretty_print()
    generator = load_image_gen()
    await generator.init()
    tasks = [
        generator.generate_image(i["description"], i["width"], i["height"])
        for i in images
    ]
    images_data = await asyncio.gather(*tasks, return_exceptions=True)
    images_data_filtered = [
        (i, d) for i, d in zip(images, images_data) if isinstance(d, str)
    ]
    uploader = REPLUploader()
    upload_files = []
    for img_tuple in images_data_filtered:
        # Проверяем, что кортеж не пустой и содержит необходимые данные
        if not img_tuple or len(img_tuple) != 2:
            continue
        img_dict, img_data = img_tuple
        if img_dict is None or not isinstance(img_dict, dict):
            continue
        if "name" not in img_dict:
            continue
        if not isinstance(img_data, str):
            continue
        upload_files.append(
            RunUploadFile(
                path=img_dict["name"],
                file_type="image",
                content=base64.b64decode(img_data),
            )
        )
    upload_resp = await uploader.upload_run_files(
        upload_files, config["configurable"]["thread_id"]
    )
    # Проверяем, что upload_resp не None
    if upload_resp is None:
        upload_resp = []
    slide_map = {}
    images_uploaded = state.get("images_uploaded", {})
    for img_tuple, b in zip(images_data_filtered, upload_resp):
        if isinstance(b, Exception):
            continue
        # Проверяем, что img_tuple не пустой и содержит необходимые данные
        if not img_tuple or len(img_tuple) != 2:
            continue
        img_dict, _ = img_tuple
        if img_dict is None or not isinstance(img_dict, dict):
            continue
        if "slide_index" not in img_dict or "name" not in img_dict:
            continue
        slide_map.setdefault(img_dict["slide_index"], []).append(img_dict)
        images_uploaded[img_dict["name"]] = b
        if config["configurable"].get("save_files", False):
            raise Exception("TODO: переделать")
            # with open(i["name"], "wb") as f:
            #     await asyncio.to_thread(f.write, base64.b64decode(b))
    return {"slide_map": slide_map, "images_uploaded": images_uploaded}
