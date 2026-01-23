import asyncio
from typing import Optional

import os
import httpx

from giga_agent.generators.image.image_gen import ImageGen

# Поддерживаемые размеры для моделей OpenRouter
# OpenRouter использует aspect_ratio вместо size
# Форматы согласно документации OpenRouter
OPENROUTER_ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),      # квадрат (default)
    "2:3": (832, 1248),        # portrait
    "3:2": (1248, 832),        # landscape
    "3:4": (864, 1184),        # portrait
    "4:3": (1184, 864),        # landscape
    "4:5": (896, 1152),        # portrait
    "5:4": (1152, 896),        # landscape
    "9:16": (768, 1344),       # очень высокий portrait
    "16:9": (1344, 768),       # широкий landscape
    "21:9": (1536, 672),       # очень широкий landscape
}

# Поддерживаемые уровни качества для OpenRouter
# Согласно документации OpenRouter
OPENROUTER_QUALITIES = {
    "1K": "1K",      # Standard resolution (default)
    "2K": "2K",      # Higher resolution
    "4K": "4K",      # Highest resolution
}

# Список всех доступных размеров для совместимости
SUPPORTED_IMAGE_SIZES: dict[str, list[tuple[int, int]]] = {
    # OpenRouter поддерживает все форматы для всех моделей
    "openrouter": list(OPENROUTER_ASPECT_RATIOS.values()),
    # Для обратной совместимости с моделями OpenAI через OpenRouter
    "dall-e-3": [
        (1024, 1024),   # 1:1
        (1344, 768),    # 16:9 (широкий)
        (768, 1344),    # 9:16 (высокий)
    ],
    "gpt-image-1": [
        (1024, 1024),   # 1:1
        (1344, 768),    # 16:9
        (768, 1344),    # 9:16
    ],
    "dall-e-2": [
        (1024, 1024),   # 1:1
    ],
}


class OpenRouterImageGen(ImageGen):
    """Генерация изображений через OpenRouter.ai API.

    OpenRouter.ai предоставляет доступ к различным моделям генерации изображений,
    включая DALL-E и другие модели через единый API интерфейс.
    Возвращает base64-строку изображения (b64_json), совместимую с интерфейсом
    базового класса `ImageGen`.
    """

    def __init__(
        self,
        model: str = "openai/dall-e-3",
        semaphore: Optional[asyncio.Semaphore] = None,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float | None = 60.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(model=model, semaphore=semaphore)
        self._api_key: Optional[str] = api_key or os.getenv("OPENROUTER_API_KEY")
        self._base_url = (
            base_url
            if base_url
            else os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        )
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    async def init(self) -> None:
        if not self._api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is not set in the environment and was not provided to the constructor"
            )
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        )
        await super().init()
    
    async def generate_image(
        self, prompt: str, width: int, height: int, quality: Optional[str] = None
    ) -> str:
        """Обёртка, обеспечивающая ограничение семафором.

        Реализацию генерации предоставляет `_generate_image` в наследниках.
        Возвращает base64-строку изображения.
        
        Args:
            prompt: Текст промпта для генерации изображения
            width: Ширина изображения
            height: Высота изображения
            quality: Качество изображения ("1K", "2K", "4K") - только для OpenRouter
        """
        if not self._initialized:
            raise RuntimeError(
                "ImageGen.init() must be called before generate_image()."
            )
        async with self.semaphore:
            return await self._generate_image(prompt, width, height, quality)

    async def _generate_image(
        self, prompt: str, width: int, height: int, quality: Optional[str] = None
    ) -> str:
        if self._client is None or not self._api_key:
            raise RuntimeError("OpenRouterImageGen is not initialized. Call init().")

        import base64
        import re

        # Определяем aspect_ratio на основе размеров
        aspect_ratio = self._get_aspect_ratio_for_size(width, height)
        
        # Определяем качество (по умолчанию 1K)
        image_quality = quality if quality in OPENROUTER_QUALITIES else "1K"
        
        # OpenRouter использует /chat/completions endpoint с modalities: ["image", "text"]
        # Изображение возвращается в message["images"] с image_url["url"] (base64 data URL)
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "modalities": ["image", "text"],
            "image_config": {
                "aspect_ratio": aspect_ratio,
                "quality": image_quality
            }
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", ""),
            "X-Title": os.getenv("OPENROUTER_X_TITLE", "Giga Agent"),
        }

        attempt = 0
        while True:
            attempt += 1
            resp = await self._client.post(
                "/chat/completions",
                json=payload,
                headers=headers,
            )

            if resp.is_success:
                data = resp.json()
                
                # Проверяем наличие ошибки в ответе
                if "error" in data:
                    error_info = data.get("error", {})
                    error_msg = error_info.get("message", "Unknown error")
                    error_type = error_info.get("type", "unknown")
                    raise RuntimeError(f"OpenRouter API error ({error_type}): {error_msg}")
                
                # Проверяем формат ответа OpenRouter
                choices = data.get("choices", [])
                if not choices:
                    # Логируем полный ответ для отладки (первые 500 символов)
                    response_str = str(data)[:500]
                    raise RuntimeError(f"OpenRouter did not return choices in response. Response preview: {response_str}")
                
                message = choices[0].get("message", {})
                
                # Проверяем наличие изображений в ответе
                if message.get("images"):
                    images = message["images"]
                    if not images:
                        raise RuntimeError("OpenRouter returned empty images array")
                    
                    # Извлекаем base64 из data URL
                    image_url = images[0].get("image_url", {}).get("url", "")
                    if not image_url:
                        raise RuntimeError("OpenRouter response does not contain image_url")
                    
                    # Извлекаем base64 строку из data URL (формат: data:image/...;base64,<base64_string>)
                    if image_url.startswith("data:image"):
                        # Ищем base64 данные после запятой
                        match = re.search(r'base64,([A-Za-z0-9+/=]+)', image_url)
                        if match:
                            return match.group(1)
                        # Если формат другой, пробуем извлечь после запятой
                        if "," in image_url:
                            return image_url.split(",", 1)[1]
                    
                    # Если это уже base64 строка без префикса
                    return image_url
                
                # Если изображения нет в images, проверяем content (для некоторых моделей)
                content = message.get("content", "")
                if content:
                    # Пытаемся найти base64 в content
                    if "base64" in content.lower() or content.startswith("data:image"):
                        match = re.search(r'base64,([A-Za-z0-9+/=]+)', content)
                        if match:
                            return match.group(1)
                        if "," in content:
                            return content.split(",", 1)[1]
                
                raise RuntimeError(f"OpenRouter did not return image data. Response: {data}")

            # На последней попытке — пробрасываем исключение
            if attempt >= self._max_retries:
                resp.raise_for_status()

            # Простая экспоненциальная пауза на ретраях (в т.ч. для 429/5xx)
            await asyncio.sleep(2 ** (attempt - 1))

    @staticmethod
    def _get_aspect_ratio_for_size(width: int, height: int) -> str:
        """Определяет aspect_ratio для OpenRouter на основе размеров.
        
        Возвращает ближайший поддерживаемый aspect_ratio из OPENROUTER_ASPECT_RATIOS.
        """
        # Вычисляем соотношение сторон
        ratio = width / height if height > 0 else 1.0
        
        # Находим ближайший aspect_ratio
        best_ratio = "1:1"  # по умолчанию
        min_diff = float('inf')
        
        for aspect_str, (w, h) in OPENROUTER_ASPECT_RATIOS.items():
            aspect_value = w / h if h > 0 else 1.0
            diff = abs(ratio - aspect_value)
            if diff < min_diff:
                min_diff = diff
                best_ratio = aspect_str
        
        return best_ratio
    
    @staticmethod
    def _normalize_size_for_model(
        model: str, width: int, height: int
    ) -> tuple[int, int]:
        """Преобразует произвольные width×height к ближайшему поддерживаемому размеру.

        Для OpenRouter использует форматы из OPENROUTER_ASPECT_RATIOS.
        """
        # Определяем aspect_ratio
        aspect_ratio = OpenRouterImageGen._get_aspect_ratio_for_size(width, height)
        
        # Возвращаем размеры для этого aspect_ratio
        return OPENROUTER_ASPECT_RATIOS[aspect_ratio]

