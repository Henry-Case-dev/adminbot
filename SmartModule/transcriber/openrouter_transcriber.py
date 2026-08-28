"""Epic 67 (D266, Section 71.2) — OpenRouter фолбэк (chat.completions).

Формат input_audio сверён с актуальной документацией OpenRouter:
https://openrouter.ai/docs/guides/overview/multimodal/audio — контент-часть
{"type": "input_audio", "input_audio": {"data": <base64>, "format": <fmt>}},
где data — СЫРОЙ base64 БЕЗ префикса data URI (схема STTInputAudio:
«Base64-encoded audio data (raw bytes, not a data URI)»).

Epic 79.6 (D296): fallback модель сменена с thinkingmachines/inkling:free
(agentic-harness-only → постоянный 403) на nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
(free, поддерживает audio input, НЕ agentic-restricted, принимает wav/mp3 аудио).
"""
import base64
import logging
from pathlib import Path

from openai import AsyncOpenAI

from config.settings import settings
from SmartModule.transcriber.base import BaseTranscriber

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_TRANSCRIBE_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"

# Канон Section 71.2, VERBATIM.
_SYSTEM_PROMPT = (
    "СТРОГИЙ ФОРМАТ: Выведи только транскрипцию этого аудио без лишних слов. "
    "Никаких вступлений."
)
_USER_TEXT = "Расшифруй это аудио."


class OpenRouterTranscriber(BaseTranscriber):
    """Fallback-стратегия: мультимодальный chat.completions с input_audio."""

    name = "openrouter"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = settings.OPENROUTER_API_KEY if api_key is None else api_key
        self.timeout = settings.OPENROUTER_TIMEOUT
        self._client: AsyncOpenAI | None = (
            AsyncOpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=self._api_key,
                timeout=self.timeout,
            )
            if self._api_key
            else None
        )

    @property
    def available(self) -> bool:
        return bool(self._client)

    @staticmethod
    def _audio_format(file_path: str) -> str:
        """format по расширению файла: voice → ogg, video_note → m4a.

        Решение @Reviewer v2.46.0 (сверено с доками OpenRouter
        https://openrouter.ai/docs/guides/overview/multimodal/audio):
        поддерживаемые форматы input_audio = wav/mp3/flac/m4a/ogg/webm/aac —
        'mp4' в списке НЕТ. Telegram video_note — это MP4-контейнер с
        AAC-аудиодорожкой; без ffmpeg перекодировать нельзя, поэтому контейнер
        объявляем как 'm4a' (MIME audio/mp4 — тот же MPEG-4 аудио-контейнер).
        """
        suffix = Path(file_path).suffix.lstrip(".").lower()
        if suffix == "mp4":
            return "m4a"                        # video_note: MP4-контейнер ≡ MPEG-4 audio
        return suffix or "ogg"

    async def transcribe(self, file_path: str) -> str:
        if self._client is None:
            raise RuntimeError(
                "OpenRouterTranscriber: OPENROUTER_API_KEY is not configured")
        raw = Path(file_path).read_bytes()
        audio_b64 = base64.b64encode(raw).decode("ascii")
        response = await self._client.chat.completions.create(
            model=OPENROUTER_TRANSCRIBE_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": _USER_TEXT},
                    {"type": "input_audio", "input_audio": {
                        "data": audio_b64,
                        "format": self._audio_format(file_path),
                    }},
                ]},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        return content or ""
