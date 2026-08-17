"""Epic 33 — SearchAggregator: каскад Tavily → Exa → DuckDuckGo (R33-2, D105).

Один ленивый httpx.AsyncClient (прецедент LLMClient), per-request таймауты,
close() в on_shutdown. Уровень пропускается, если API-ключ пуст (D104).
Любая ошибка уровня (timeout/HTTP/пустой результат) → следующий уровень.
Все уровни упали → AllSearchEnginesFailedException.
Результат — единый текстовый формат, обрезка до max_symbols.

DDG (уровень 3): duckduckgo-search 8.x — sync-only (AsyncDDGS удалён в PR#268),
официальная рекомендация мейнтейнера — обёртка sync-вызова в executor
(здесь asyncio.to_thread). Контракт search() остаётся async.
"""
import asyncio
import logging
import time
from typing import Awaitable, Callable

import httpx

from config.settings import settings

try:
    from duckduckgo_search import DDGS
except ImportError:  # pragma: no cover — зависимость в requirements.txt
    DDGS = None

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
EXA_URL = "https://api.exa.ai/search"


class AllSearchEnginesFailedException(Exception):
    """Все уровни каскада (Tavily → Exa → DDG) упали."""


class SearchAggregator:
    def __init__(
        self,
        tavily_api_key: str = settings.TAVILY_API_KEY,
        exa_api_key: str = settings.EXA_API_KEY,
        tavily_timeout: float = 5.0,      # ТЗ: таймаут >5с → фолбек (D105)
        exa_timeout: float = 10.0,        # Exa медленнее (живой краулинг)
        ddg_timeout: float = 15.0,
        max_results: int = 5,
    ) -> None:
        self._tavily_api_key = tavily_api_key
        self._exa_api_key = exa_api_key
        self._tavily_timeout = tavily_timeout
        self._exa_timeout = exa_timeout
        self._ddg_timeout = ddg_timeout
        self._max_results = max_results
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Ленивый общий httpx-клиент (прецедент LLMClient._get_client)."""
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def search(self, query: str, max_symbols: int) -> str:
        """Каскад: Tavily → Exa → DDG. Возвращает агрегированный текст
        (обрезка до max_symbols). Raises AllSearchEnginesFailedException."""
        levels: list[tuple[str, Callable[[str], Awaitable[str]], str | None]] = [
            ("tavily", self._search_tavily, self._tavily_api_key),
            ("exa", self._search_exa, self._exa_api_key),
            ("ddg", self._search_ddg, None),
        ]
        for name, fn, key in levels:
            if key is not None and not key.strip():
                # D104: пустой ключ — уровень каскада отключён
                logger.info("SearchAggregator: level skipped (no api key) | provider=%s", name)
                continue
            started = time.monotonic()
            try:
                text = await fn(query)
                if not text.strip():
                    raise ValueError("empty result")
                latency_ms = (time.monotonic() - started) * 1000.0
                logger.info(
                    "SearchAggregator: level ok | provider=%s | latency_ms=%.0f | chars=%d",
                    name, latency_ms, len(text),
                )
                return self._truncate(text, max_symbols)
            except Exception as exc:
                logger.warning(
                    "SearchAggregator: level failed → fallback | provider=%s | error=%s",
                    name, exc,
                )
        raise AllSearchEnginesFailedException(
            f"all search engines failed (tavily → exa → ddg) | query={query!r}"
        )

    async def close(self) -> None:
        """Закрыть ленивый httpx-клиент (on_shutdown). DDG — только внутри вызова."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def log_config(self) -> None:
        """D104: WARNING-и пустых ключей при старте (вызов из bot.py on_startup)."""
        if not (self._tavily_api_key or "").strip():
            logger.warning("Tavily level disabled: TAVILY_API_KEY is empty")
        if not (self._exa_api_key or "").strip():
            logger.warning("Exa level disabled: EXA_API_KEY is empty")

    # ── Уровни каскада ────────────────────────────────────────

    async def _search_tavily(self, query: str) -> str:
        """POST api.tavily.com/search (Bearer); raises on failure."""
        client = self._get_client()
        response = await client.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {self._tavily_api_key}"},
            json={
                "query": query,
                "max_results": self._max_results,
                "search_depth": "basic",
            },
            timeout=httpx.Timeout(self._tavily_timeout),
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results") or []
        if not results:
            raise ValueError("tavily: empty results")
        pairs = [
            (
                str(item.get("title") or ""),
                str(item.get("content") or ""),
                str(item.get("url") or ""),
            )
            for item in results
        ]
        return self._format_hits(pairs)

    async def _search_exa(self, query: str) -> str:
        """POST api.exa.ai/search (x-api-key); raises on failure."""
        client = self._get_client()
        response = await client.post(
            EXA_URL,
            headers={"x-api-key": self._exa_api_key},
            json={
                "query": query,
                "numResults": self._max_results,
                "type": "auto",
                "contents": {"text": {"maxCharacters": 2000}},
            },
            timeout=httpx.Timeout(self._exa_timeout),
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results") or []
        if not results:
            raise ValueError("exa: empty results")
        pairs = []
        for item in results:
            title = str(item.get("title") or "")
            url = str(item.get("url") or "")
            text = item.get("text")
            highlights = item.get("highlights")
            summary = item.get("summary")
            snippet = text or (highlights[0] if highlights else None) or summary or ""
            pairs.append((title, str(snippet), url))
        return self._format_hits(pairs)

    def _run_ddg_text(self, query: str) -> list[dict]:
        """Sync-блок DDG (библиотека 8.x sync-only) — исполняется в executor."""
        if DDGS is None:  # pragma: no cover
            raise RuntimeError("duckduckgo_search is not installed")
        with DDGS(timeout=int(self._ddg_timeout)) as ddgs:
            return ddgs.text(query, max_results=self._max_results)

    async def _search_ddg(self, query: str) -> str:
        """Уровень 3 — DuckDuckGo (без ключа). AsyncDDGS удалён из 8.x (PR#268):
        sync DDGS через asyncio.to_thread (официальная рекомендация)."""
        results = await asyncio.to_thread(self._run_ddg_text, query)
        if not results:
            raise ValueError("ddg: empty results")
        pairs = [
            (
                str(item.get("title") or ""),
                str(item.get("body") or ""),
                str(item.get("href") or ""),
            )
            for item in results
        ]
        return self._format_hits(pairs)

    # ── Общий формат ──────────────────────────────────────────

    @staticmethod
    def _format_hits(title_snippet_pairs: list[tuple[str, str, str]]) -> str:
        """Блок f"{title}\n{snippet}\n{url}" на результат; блоки через \n\n."""
        return "\n\n".join(
            f"{title}\n{snippet}\n{url}" for title, snippet, url in title_snippet_pairs
        )

    @staticmethod
    def _truncate(text: str, max_symbols: int) -> str:
        """Жёсткое ограничение без разрыва юникода (срез по символам)."""
        return text[:max_symbols]
