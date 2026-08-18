# services/web_content_extractor.py (НОВЫЙ)
"""Epic 38 — WebContentExtractor (R38-3, D134/D136, Section 47.4).

Каскад: trafilatura → Tavily /extract → Exa /contents (прецедент
SearchAggregator: ленивый httpx.AsyncClient, skip уровня при пустом ключе,
ретраев внутри уровней НЕТ). Все уровни упали → WebContentExtractionFailedException
→ пул 5.7 (WEB_ERROR_PHRASES) в handlers/web.py."""
import asyncio
import logging
import time

import httpx

from config.settings import settings

try:
    import trafilatura
except ImportError:  # pragma: no cover — зависимость в requirements.txt
    trafilatura = None

logger = logging.getLogger(__name__)

TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
EXA_CONTENTS_URL = "https://api.exa.ai/contents"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_FETCH_TIMEOUT = 10.0   # trafilatura: скачивание HTML (ТЗ)
_API_TIMEOUT = 15.0     # Tavily / Exa (ТЗ)
_MIN_CONTENT_CHARS = 150


class WebContentExtractionFailedException(Exception):
    """Все уровни каскада провалились/пусто. → пул 5.7 (WEB_ERROR_PHRASES)."""


class WebContentExtractor:
    def __init__(
        self,
        tavily_api_key: str = settings.TAVILY_API_KEY,
        exa_api_key: str = settings.EXA_API_KEY,
    ) -> None:
        self._tavily_api_key = tavily_api_key
        self._exa_api_key = exa_api_key
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Ленивый общий httpx-клиент (прецедент SearchAggregator._get_client)."""
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def extract(self, target_url: str, max_symbols: int) -> str:
        """Каскад: trafilatura → tavily → exa. Успех уровня: text.strip() ДОЛЖЕН
        быть СТРОГО >150 символов (ровно 150 → фейл, ТЗ «длина >150»), затем
        text[:max_symbols] (жёсткий срез). Все уровни упали →
        WebContentExtractionFailedException."""
        levels = [
            ("trafilatura", self._extract_trafilatura, None),
            ("tavily", self._extract_tavily, self._tavily_api_key),
            ("exa", self._extract_exa, self._exa_api_key),
        ]
        for name, fn, key in levels:
            if key is not None and not key.strip():
                # пустой ключ — уровень отключён (D104-прецедент)
                logger.warning(
                    "[web_extractor] level skipped (no api key) | provider=%s", name
                )
                continue
            started = time.monotonic()
            try:
                text = await fn(target_url)
                if len(text.strip()) <= _MIN_CONTENT_CHARS:
                    raise ValueError("short content")
                latency_ms = (time.monotonic() - started) * 1000.0
                logger.info(
                    "[web_extractor] level ok | provider=%s | latency_ms=%.0f | chars=%d",
                    name, latency_ms, len(text),
                )
                return self._truncate(text, max_symbols)
            except Exception as exc:
                logger.warning(
                    "[web_extractor] level failed → fallback | provider=%s | error=%s",
                    name, exc,
                )
        logger.error("[web_extractor] all levels failed | url=%s", target_url)
        raise WebContentExtractionFailedException(
            f"all extraction levels failed | url={target_url!r}"
        )

    async def _extract_trafilatura(self, target_url: str) -> str:
        """Шаг 1 (основной): GET target_url (UA, follow_redirects=True,
        timeout 10.0) → trafilatura.extract(...) в asyncio.to_thread
        (прецедент youtube_transcript_engine). None/raise → фолбек."""
        if trafilatura is None:  # pragma: no cover
            raise RuntimeError("trafilatura is not installed")
        client = self._get_client()
        response = await client.get(
            target_url,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=httpx.Timeout(_FETCH_TIMEOUT),
        )
        response.raise_for_status()
        text = await asyncio.to_thread(
            trafilatura.extract,
            response.text,
            output_format="markdown",
            include_links=False,
            include_images=False,
            include_tables=True,
            favor_precision=True,
        )
        if text is None:
            raise ValueError("trafilatura: no extractable content")
        return text

    async def _extract_tavily(self, target_url: str) -> str:
        """Шаг 2 (фолбек №1): POST api.tavily.com/extract,
        json={"urls":[target_url],"api_key":…}, timeout 15.0 (ТЗ).
        Возвращает results[0]["raw_content"]; пусто → raise."""
        client = self._get_client()
        response = await client.post(
            TAVILY_EXTRACT_URL,
            json={"urls": [target_url], "api_key": self._tavily_api_key},
            timeout=httpx.Timeout(_API_TIMEOUT),
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        if not results or not str(results[0].get("raw_content") or "").strip():
            raise ValueError("tavily: empty raw_content")
        return str(results[0]["raw_content"])

    async def _extract_exa(self, target_url: str) -> str:
        """Шаг 3 (фолбек №2): POST api.exa.ai/contents,
        headers={"x-api-key":…}, json={"urls":[target_url],"text":True},
        timeout 15.0 (ТЗ). Возвращает results[0]["text"]; пусто → raise."""
        client = self._get_client()
        response = await client.post(
            EXA_CONTENTS_URL,
            headers={"x-api-key": self._exa_api_key},
            json={"urls": [target_url], "text": True},
            timeout=httpx.Timeout(_API_TIMEOUT),
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        if not results or not str(results[0].get("text") or "").strip():
            raise ValueError("exa: empty text")
        return str(results[0]["text"])

    async def close(self) -> None:
        """Закрыть ленивый клиент (on_shutdown, прецедент Epic 33/37)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def log_config(self) -> None:
        """WARNING пустых ключей при старте (bot.py on_startup, прецедент D104)."""
        if not (self._tavily_api_key or "").strip():
            logger.warning("Tavily extract level disabled: TAVILY_API_KEY is empty")
        if not (self._exa_api_key or "").strip():
            logger.warning("Exa contents level disabled: EXA_API_KEY is empty")

    @staticmethod
    def _truncate(text: str, max_symbols: int) -> str:
        """Жёсткий срез (прецедент SearchAggregator._truncate)."""
        return text[:max_symbols]
