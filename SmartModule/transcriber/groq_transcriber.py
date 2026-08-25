"""Epic 67 (D266, Section 71.2) — Groq whisper-large-v3 через OpenAI-SDK."""
import logging

from openai import AsyncOpenAI

from config.settings import settings
from SmartModule.transcriber.base import BaseTranscriber

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_TRANSCRIBE_MODEL = "whisper-large-v3"


class GroqTranscriber(BaseTranscriber):
    """Primary-стратегия: audio.transcriptions.create (OpenAI-compatible)."""

    name = "groq"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = settings.GROQ_API_KEY if api_key is None else api_key
        self.timeout = settings.GROQ_TIMEOUT
        # AsyncOpenAI(api_key="") кидает OpenAIError — клиент строим только
        # при наличии ключа; пустой ключ = стратегия недоступна.
        self._client: AsyncOpenAI | None = (
            AsyncOpenAI(
                base_url=GROQ_BASE_URL,
                api_key=self._api_key,
                timeout=self.timeout,
            )
            if self._api_key
            else None
        )

    @property
    def available(self) -> bool:
        return bool(self._client)

    async def transcribe(self, file_path: str) -> str:
        if self._client is None:
            raise RuntimeError("GroqTranscriber: GROQ_API_KEY is not configured")
        with open(file_path, "rb") as fh:
            response = await self._client.audio.transcriptions.create(
                model=GROQ_TRANSCRIBE_MODEL, file=fh)
        return getattr(response, "text", "") or ""
