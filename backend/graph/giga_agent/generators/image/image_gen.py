import abc
import asyncio
import os
from typing import Optional


class ImageGen(abc.ABC):
    """Базовый генератор изображений.

    - Принимает `semaphore` ограничивающий вызовы `generate_image`.
    """

    def __init__(
        self, model: str, semaphore: Optional[asyncio.Semaphore] = None
    ) -> None:
        self.model = model
        self.semaphore: asyncio.Semaphore = semaphore or asyncio.Semaphore(
            int(os.getenv("IMAGE_GEN_PARALLEL", 1))
        )
        self._initialized: bool = False

    @abc.abstractmethod
    async def init(self) -> None:
        """Подготовка ресурсов перед генерацией изображений."""
        self._initialized = True

    async def generate_image(self, prompt: str, width: int, height: int) -> str:
        """Обёртка, обеспечивающая ограничение семафором.

        Реализацию генерации предоставляет `_generate_image` в наследниках.
        Возвращает base64-строку изображения.
        """
        if not self._initialized:
            raise RuntimeError(
                "ImageGen.init() must be called before generate_image()."
            )
        async with self.semaphore:
            return await self._generate_image(prompt, width, height)

    @abc.abstractmethod
    async def _generate_image(
        self, prompt: str, width: int, height: int
    ) -> str:  # pragma: no cover - интерфейс
        raise NotImplementedError
