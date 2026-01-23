"""
Инструмент для быстрого синтеза речи через Sber SmartSpeech.

План действий:
1. Проверить наличие обязательных env и корректность параметров.
2. Получить access token через salute (SmartSpeech) API.
3. Выполнить синтез и вернуть результат с вложением audio.
"""

import base64
import io
import os
import uuid
from typing import Annotated, Literal

from langchain_core.tools import tool
from pydantic import Field
from pydub import AudioSegment

from giga_agent.agents.podcast.tts_sber import (
    SBER_VOICES,
    get_sber_tts_token,
    synthesize_sber_speech,
)

# Шаг 0: задаем поддерживаемые форматы и соответствие mime-типов.
# SmartSpeech стабильно отдает WAV16, поэтому внутренняя генерация всегда в нем,
# а запрошенный пользователем формат получаем конвертацией.
SOURCE_TTS_FORMAT = "wav16"

SUPPORTED_FORMATS: dict[str, str] = {
    "wav16": "audio/wav",
    "ogg": "audio/ogg",
    "mp3": "audio/mp3",
}


def _resolve_voice(voice: str | None) -> str:
    """Подбирает корректный голос, опираясь на карту SBER_VOICES."""
    available = {voice for voices in SBER_VOICES.values() for voice in voices}
    if voice and voice in available:
        return voice
    # По умолчанию используем женский голос, т.к. он звучит нейтрально.
    return SBER_VOICES["host"][0]


def _resolve_format(format_name: str) -> tuple[str, str]:
    """Проверяет формат и возвращает (format_name, mime)."""
    fmt = (format_name or "wav16").lower()
    if fmt not in SUPPORTED_FORMATS:
        fmt = "wav16"
    return fmt, SUPPORTED_FORMATS[fmt]


def _convert_audio_bytes(source_bytes: bytes, target_format: str) -> tuple[bytes, str]:
    """Преобразует исходный WAV16 в запрошенный формат."""
    if target_format == "wav16":
        return source_bytes, SUPPORTED_FORMATS["wav16"]

    audio_segment = AudioSegment.from_file(io.BytesIO(source_bytes), format="wav")
    buffer = io.BytesIO()
    export_format = "mp3" if target_format == "mp3" else "ogg"
    audio_segment.export(buffer, format=export_format)
    return buffer.getvalue(), SUPPORTED_FORMATS[target_format]


@tool(parse_docstring=True)
async def salute_say(
    text: Annotated[str, Field(description="Текст, который нужно озвучить")],
    voice: Annotated[
        str,
        Field(
            description=(
                "Голос из доступных в Sber SmartSpeech (например, May_24000, Ost_24000)"
            )
        ),
    ] = "May_24000",
    audio_format: Annotated[
        Literal["wav16", "ogg", "mp3"],
        Field(description="Формат аудио, который нужно получить"),
    ] = "mp3",
):
    """
    Синтезирует речь через Sber SmartSpeech и возвращает аудио-файл.

    Args:
        text: Текст для синтеза (до ~1000 символов за один вызов).
        voice: Конкретный голос. Можно посмотреть карту голосов в документации SmartSpeech.
        audio_format: Формат аудио (wav16, ogg, mp3).
    """
    # Шаг 1: проверяем наличие обязательной переменной окружения.
    sber_basic_token = os.getenv("SALUTE_SPEECH")
    if not sber_basic_token:
        return (
            "Переменная окружения SALUTE_SPEECH не задана. Укажи ключ, чтобы "
            "можно было получить access token для SmartSpeech."
        )

    # Шаг 2: получаем временный access token.
    salute_scope = os.getenv("SALUTE_SPEECH_SCOPE", "SALUTE_SPEECH_PERS")
    access_token = await get_sber_tts_token(sber_basic_token, scope=salute_scope)
    if not access_token:
        return "Не удалось получить access token от Sber SmartSpeech."

    # Шаг 3: синтезируем речь выбранным голосом и форматом.
    selected_voice = _resolve_voice(voice)
    audio_bytes = await synthesize_sber_speech(
        text=text,
        token=access_token,
        format=SOURCE_TTS_FORMAT,
        voice=selected_voice,
    )
    if not audio_bytes:
        return "Сервис SmartSpeech вернул пустой ответ. Попробуй еще раз."

    # Шаг 4: конвертируем в запрошенный формат (или оставляем WAV16).
    try:
        target_format, mime_type = _resolve_format(audio_format)
        converted_bytes, mime_type = _convert_audio_bytes(audio_bytes, target_format)
    except Exception:
        return "Не удалось сконвертировать аудио-файл. Попробуй выбрать другой формат."

    # Шаг 4: упаковываем результат в стандартный формат для giga_agent.
    encoded_audio = base64.b64encode(converted_bytes).decode("ascii")
    file_id = str(uuid.uuid4())
    return {
        "transcript": text,
        "voice": selected_voice,
        "message": (
            f"Сгенерирован аудио-файл {file_id}. "
            f"Покажи его пользователю через ![Аудио](audio:{file_id})"
        ),
        "giga_attachments": [
            {"type": mime_type, "file_id": file_id, "data": encoded_audio}
        ],
    }

