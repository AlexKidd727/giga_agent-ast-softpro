from __future__ import annotations

import os
from typing import Tuple

from giga_agent.generators.image.image_gen import ImageGen
from giga_agent.generators.image.openai import OpenAIImageGen
# Опциональный импорт GigaChatImageGen (может быть не установлен langchain-gigachat)
try:
    from giga_agent.generators.image.gigachat import GigaChatImageGen
    GIGACHAT_IMAGE_GEN_AVAILABLE = True
except ImportError:
    GigaChatImageGen = None
    GIGACHAT_IMAGE_GEN_AVAILABLE = False
from giga_agent.generators.image.fusion_brain import FusionBrainImageGen
from giga_agent.generators.image.openrouter import OpenRouterImageGen


def load_image_gen(name: str = None) -> ImageGen:
    """Загружает и инициализирует генератор изображений по строке формата
    "provider:model".

    Примеры:
    - "openai:dall-e-3" → OpenAIImageGen(model="dall-e-3")
    - "gigachat:kandinsky-4.1:image" → GigaChatImageGen(model="kandinsky-4.1:image")
    - "fusion_brain:kandinsky" → FusionBrainImageGen(model="kandinsky")
    - "openrouter:openai/dall-e-3" → OpenRouterImageGen(model="openai/dall-e-3")
    """

    if name is None:
        name = os.getenv("IMAGE_GEN_NAME")
    if name is None:
        raise ValueError(
            "Specify the image provider in the IMAGE_GEN_NAME environment variable"
        )
    provider, model = _parse_name(name)

    if provider == "openai":
        gen = OpenAIImageGen(model=model)
    elif provider == "gigachat":
        if not GIGACHAT_IMAGE_GEN_AVAILABLE:
            raise ImportError(
                "langchain-gigachat не установлен. "
                "Установите его для использования GigaChat генерации изображений: pip install langchain-gigachat"
            )
        gen = GigaChatImageGen(model=model)
    elif provider == "fusion_brain":
        gen = FusionBrainImageGen(model=model)
    elif provider == "openrouter":
        gen = OpenRouterImageGen(model=model)
    else:
        raise ValueError(
            f"Unknown image provider: {provider}. "
            f"Expected: openai, gigachat, fusion_brain, openrouter"
        )

    return gen


def _parse_name(name: str) -> Tuple[str, str]:
    if ":" not in name:
        raise ValueError(
            "Invalid generator name format. Use 'provider:model'"
        )
    provider, model = name.split(":", 1)
    provider = provider.strip().lower()
    model = model.strip()
    if not provider or not model:
        raise ValueError(
            "Invalid generator name format. Provider and model are required"
        )
    return provider, model
