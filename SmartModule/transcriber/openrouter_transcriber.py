"""Epic 67 (D266, Section 71.2) — OpenRouter фолбэк (chat.completions).

Формат input_audio сверён с актуальной документацией OpenRouter:
https://openrouter.ai/docs/guides/overview/multimodal/audio — контент-часть
{"type": "input_audio", "input_audio": {"data": <base64>, "format": <fmt>}},
где data — СЫРОЙ base64 БЕЗ префикса data URI (схема STTInputAudio:
«Base64-encoded audio data (raw bytes, not a data URI)»).

Epic 79.6 (D296): fallback стратегия использует openrouter/free роутер.
Роутер автоматически выбирает free-модель с поддержкой input_audio.
НО free модели могут быть agentic-harness-only (inkling:free → 403) или
не поддерживать input_audio (Nemotron → 400). Добавлен retry на эти статусы:
повторный запрос заставит роутер выбрать другую модель из пула.

R17: API ключ и URL никогда не логируются. Ошибки логируются как тип
исключения + HTTP status, без тела ответа (может содержать модельные slug).
"""
import asyncio
import base64
import logging
import time
from pathlib import Path

from openai import AsyncOpenAI

from config.settings import settings
from services import hot_config as hot
from services.status_service import status as status_service
from SmartModule.transcriber.base import BaseTranscriber

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Epic 79.6 (D296): роутер openrouter/free автоматически выбирает free-модель
# с поддержкой input_audio. Retry на 403/400 заставит роутер повторить выбор.
OPENROUTER_TRANSCRIBE_MODEL = "openrouter/free"
# Количество retry на 403/400 (роутер выбирает другую free-модель).
OPENROUTER_MAX_RETRIES = 3

# Канон Section 71.2, VERBATIM.
_SYSTEM_PROMPT = (
    "СТРОГИЙ ФОРМАТ: Выведи только транскрипцию этого аудио без лишних слов. "
    "Никаких вступлений."
)
_USER_TEXT = "Расшифруй это аудио."


class OpenRouterTranscriber(BaseTranscriber):
    """Fallback-стратегия: мультимодальный chat.completions с input_audio.

    Epic 79.6 (D296): использует openrouter/free роутер + retry на 403/400,
    чтобы обойти agentic-only и несовместимые free модели.
    """

    name = "openrouter"

    def __init__(self, api_key: str | None = None) -> None:
        # T-619 (84.4): ключ — горячая точка на КАЖДЫЙ вызов (фолбек settings)
        self._default_key = settings.OPENROUTER_API_KEY if api_key is None else api_key
        self.timeout = settings.OPENROUTER_TIMEOUT
        self._max_retries = OPENROUTER_MAX_RETRIES
        self._client: AsyncOpenAI | None = self._build_client()

    def _current_api_key(self) -> str:
        return hot.get("keys.openrouter_api_key", self._default_key) or ""

    def _build_client(self) -> AsyncOpenAI | None:
        key = self._current_api_key()
        if not key:
            return None
        return AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=key,
            timeout=self.timeout,
        )

    def _refresh_client(self) -> None:
        """T-619: ключ изменился → пересоздать клиент (hot-reload)."""
        if self._client is None or self._current_api_key() != self._default_key:
            self._client = self._build_client()

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

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        """Epic 79.6 (D296): 403 (agentic-only модель) и 400 (модель не
        поддерживает input_audio) — retryable через openrouter/free роутер.
        R17: не логируем тело ошибки (может содержать slug модели)."""
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
        if status in (403, 400):
            # OpenAI SDK: тело ошибки в exc.body (dict) или exc.message
            if hasattr(exc, "body") and isinstance(exc.body, dict):
                err = exc.body.get("error", {})
                meta = err.get("metadata", {})
                raw = meta.get("raw", "")
                if raw and "input_audio" in str(raw):
                    return True  # 400: модель не поддерживает input_audio
                # 403 из-за agentic-harness-only
                if err.get("code") == 403:
                    return True
            return True  # безопасно: retry на любые 403/400 от роутера
        return False

    async def transcribe(self, file_path: str) -> str:
        # T-619: клиент перечитывается при смене ключа (hot-reload)
        self._refresh_client()
        if self._client is None:
            raise RuntimeError(
                "OpenRouterTranscriber: OPENROUTER_API_KEY is not configured")

        raw = Path(file_path).read_bytes()
        audio_b64 = base64.b64encode(raw).decode("ascii")
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": _USER_TEXT},
                {"type": "input_audio", "input_audio": {
                    "data": audio_b64,
                    "format": self._audio_format(file_path),
                }},
            ]},
        ]

        # Epic 79.6 (D296): retry на 403/400 — openrouter/free роутер выберет
        # другую модель из free пула при повторном запросе.
        for attempt in range(1, self._max_retries + 1):
            started = time.monotonic()
            try:
                response = await self._client.chat.completions.create(
                    model=OPENROUTER_TRANSCRIBE_MODEL,
                    messages=messages,
                )
                content = response.choices[0].message.content if response.choices else None
                # Epic 85 (84.11.2): замер латентности для /api/status
                status_service.record_llm(
                    "openrouter", (time.monotonic() - started) * 1000.0)
                return content or ""
            except Exception as exc:
                if self._is_retryable_error(exc) and attempt < self._max_retries:
                    logger.warning(
                        "[transcribe] openrouter retry %d/%d | %s",
                        attempt, self._max_retries, type(exc).__name__)
                    await asyncio.sleep(0.5)
                    continue
                raise
