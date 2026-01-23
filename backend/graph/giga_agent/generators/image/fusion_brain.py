from typing import Optional

import os
import json
import asyncio
import httpx

from giga_agent.generators.image.image_gen import ImageGen


class AsyncKandinskyAPI:
    def __init__(self):
        self.base_url = "https://api-key.fusionbrain.ai/"
        self.api_key = os.getenv("KANDINSKY_API_KEY")
        self.secret_key = os.getenv("KANDINSKY_SECRET_KEY")
        if not self.api_key or not self.secret_key:
            raise ValueError(
                "KANDINSKY_API_KEY and/or KANDINSKY_SECRET_KEY are not set in the environment"
            )
        self.auth_headers = {
            "X-Key": f"Key {self.api_key}",
            "X-Secret": f"Secret {self.secret_key}",
        }
        self._pipeline_id = None
        # Увеличиваем таймауты для HTTP клиента: connect=10s, read=30s, write=30s, pool=5s
        # Это необходимо, так как генерация изображений может занимать много времени
        timeout = httpx.Timeout(10.0, connect=10.0, read=30.0, write=30.0, pool=5.0)
        self.client = httpx.AsyncClient(
            base_url=self.base_url, headers=self.auth_headers, timeout=timeout
        )

    async def get_pipeline(self) -> str:
        if self._pipeline_id:
            return self._pipeline_id

        try:
            resp = await self.client.get("key/api/v1/pipelines")
            resp.raise_for_status()
            data = resp.json()
            self._pipeline_id = data[0]["id"]
            return self._pipeline_id
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 502:
                raise RuntimeError(
                    "FusionBrain API недоступен (502 Bad Gateway). "
                    "Сервер временно недоступен. Попробуйте позже или используйте другой провайдер генерации изображений."
                ) from e
            raise

    async def generate(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        style: str = "DEFAULT",
        negative_prompt: str = "",
    ) -> str:
        pipeline_id = await self.get_pipeline()
        params = {
            "type": "GENERATE",
            "style": style,
            "width": width,
            "height": height,
            "numImages": 1,
            "generateParams": {"query": prompt},
        }
        if negative_prompt:
            params["negativePromptDecoder"] = negative_prompt

        files = {
            "pipeline_id": (None, pipeline_id),
            "params": (None, json.dumps(params), "application/json"),
        }
        resp = await self.client.post("key/api/v1/pipeline/run", files=files)
        resp.raise_for_status()
        return resp.json()["uuid"]

    async def check_generation(
        self, request_id: str, attempts: int = 200, delay: float = 2.0
    ) -> list[str]:
        for _ in range(attempts):
            resp = await self.client.get(f"key/api/v1/pipeline/status/{request_id}")
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status")
            if status == "DONE":
                return data["result"]["files"]
            elif status == "FAIL":
                raise RuntimeError(
                    f"Kandinsky generation failed: "
                    f"{data.get('errorDescription', 'Unknown error')}"
                )

            await asyncio.sleep(delay)

        raise TimeoutError("Kandinsky generation timed out")

    async def generate_and_get_image(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        style: str = "DEFAULT",
        negative_prompt: str = "",
    ) -> list[str]:
        request_id = await self.generate(prompt, width, height, style, negative_prompt)
        return await self.check_generation(request_id)


class FusionBrainImageGen(ImageGen):
    """Генерация через FusionBrain (Kandinsky API)."""

    def __init__(
        self, model: str, semaphore: Optional[asyncio.Semaphore] = None
    ) -> None:
        super().__init__(model=model, semaphore=semaphore)
        self._api = AsyncKandinskyAPI()

    async def init(self) -> None:
        await super().init()

    async def _generate_image(self, prompt: str, width: int, height: int) -> str:
        files = await self._api.generate_and_get_image(
            prompt,
            width=width,
            height=height,
        )
        return files[0]
