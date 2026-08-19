"""Epic 42 — CheckupLogsFetcher (R42-2, D160/D161, Section 51.3).

Каскад: GET {base_url} (Betterstack, Bearer, 24ч) → при падении журнал
journalctl (create_subprocess_shell, БЕЗ sudo). fetch() -> (logs_text, used_fallback).
Обе ступени мертвы → CheckupLogsUnavailableException (хендлер шлёт CHECKUP_DEAD_PHRASES).
Пустой токен → шаг 1 пропускается (WARNING, D104-стиль), сразу journalctl.
Токен НЕ логируется (R17); платные MCP не используются (R42-2).
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_BETTERSTACK_TIMEOUT = 10.0
_LOOKBACK_HOURS = 24.0
_MAX_PAGES = 5                      # pagination.next — максимум доп. страниц
_MAX_LOG_EVENTS = 200               # стоп-потолок событий (обе ступени)
_MAX_LOG_SYMBOLS = 20000            # потолок контекста логов для LLM
_MAX_EVENT_MESSAGE_CHARS = 400      # обрезка одного сообщения события
_JOURNALCTL_MAX_LINES = 300         # совпадает с -n 300
_JOURNALCTL_TIMEOUT = 15.0
_LEVEL_KEYWORDS = (
    "error", "warning", "warn", "critical", "alert", "fatal",
    "exception", "traceback",
)                                    # фильтр ступени Betterstack (ТЗ)
_LOCAL_LINE_MARKERS = ("error", "warning", "traceback")   # фильтр journalctl (ТЗ)
_TS_NUMERIC_RE = re.compile(r"^\d{9,13}(?:\.\d+)?$")


class CheckupLogsUnavailableException(Exception):
    """Обе ступени каскада мертвы (Betterstack + journalctl)."""


class CheckupLogsFetcher:
    def __init__(
        self,
        token: str,
        base_url: str = settings.CHECKUP_BETTERSTACK_URL,
        journalctl_cmd: str = settings.CHECKUP_JOURNALCTL_CMD,
        transport: httpx.AsyncBaseTransport | None = None,   # тесты: MockTransport
    ) -> None:
        self._token = token
        self._base_url = base_url
        self._journalctl_cmd = journalctl_cmd
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(_BETTERSTACK_TIMEOUT, connect=10.0),
                headers={"Authorization": f"Bearer {self._token}"},
                transport=self._transport,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self) -> tuple[str, bool]:
        """(logs_text, used_fallback). Betterstack ок → (text, False).
        Betterstack упал → journalctl → (text, True). Оба мертвы → raise."""
        if not self._token.strip():
            logger.warning("[checkup fetcher] betterstack skipped (no token) → journalctl")
            return await self._fetch_journalctl(), True
        try:
            return await self._fetch_betterstack(), False
        except (httpx.HTTPError, ValueError) as exc:
            # httpx.TimeoutException — подкласс httpx.RequestError (входит в HTTPError)
            logger.warning(
                "[checkup fetcher] betterstack failed → journalctl fallback | error=%s", exc
            )
            return await self._fetch_journalctl(), True

    # ── Ступень 1: Betterstack ────────────────────────────────

    async def _fetch_betterstack(self) -> str:
        now = datetime.now(timezone.utc)
        params = {
            "from": (now - timedelta(hours=_LOOKBACK_HOURS)).strftime("%Y-%m-%dT%H:%M:%S%z"),
            "to": now.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        lines: list[str] = []
        url: str | None = self._base_url
        page = 0
        while url and page < _MAX_PAGES and len(lines) < _MAX_LOG_EVENTS:
            page += 1
            resp = await self._get_client().get(url, params=params if page == 1 else None)
            resp.raise_for_status()                    # 4xx/5xx → HTTPStatusError → фолбек
            payload = resp.json()                      # битый JSON → ValueError → фолбек
            lines.extend(self._extract_lines(payload))
            nxt = (payload.get("pagination") or {}).get("next")
            url = nxt if isinstance(nxt, str) and nxt else None
        text = "\n".join(lines[:_MAX_LOG_EVENTS])
        logger.info(
            "[checkup fetcher] betterstack ok | events=%d | chars=%d | pages=%d",
            len(lines), len(text), page,
        )
        return text[:_MAX_LOG_SYMBOLS]

    @staticmethod
    def _extract_lines(payload: dict) -> list[str]:
        """ТОЛЕРАНТНЫЙ контракт (допуск на разницу реальной схемы):
        items = data[] (JSON:API attributes ИЛИ плоские поля); поля события:
        message = message|msg|json; level = level|severity|log_level;
        timestamp = dt (ISO8601) | timestamp | _dt (unix). Фильтр уровней —
        ЛОКАЛЬНО по level+message (API-фильтра не гарантировано)."""
        data = payload.get("data")
        items = data if isinstance(data, list) else payload.get("events", [])
        out: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            attrs = item.get("attributes")
            attrs = attrs if isinstance(attrs, dict) else item
            message = (attrs.get("message") or attrs.get("msg")
                       or attrs.get("json") or "")
            level = (attrs.get("level") or attrs.get("severity")
                     or attrs.get("log_level") or "")
            if not any(k in f"{level} {message}".lower() for k in _LEVEL_KEYWORDS):
                continue                            # нерелевантный уровень — мимо
            ts = (attrs.get("dt") or attrs.get("timestamp")
                  or attrs.get("_dt") or "-")
            if isinstance(ts, (int, float)) or _TS_NUMERIC_RE.match(str(ts)):
                try:
                    ts = datetime.fromtimestamp(float(ts), tz=timezone.utc) \
                        .strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, OSError):
                    ts = str(ts)
            msg = " ".join(str(message).split())[:_MAX_EVENT_MESSAGE_CHARS]
            out.append(f"{ts} - {level.upper() or '-'} - {msg}")
            if len(out) >= _MAX_LOG_EVENTS:
                break
        return out

    # ── Ступень 2: journalctl (локальный фолбек) ──────────────

    async def _fetch_journalctl(self) -> str:
        """rc != 0 (127 command not found / 1 нет прав — hint в stderr) →
        CheckupLogsUnavailableException (DEAD). rc == 0 + пустой stdout →
        ВАЛИДНЫЙ «логов нет» → "". rc == 0 + вывод → фильтр
        ERROR/WARNING/Traceback, последние _JOURNALCTL_MAX_LINES строк."""
        try:
            proc = await asyncio.create_subprocess_shell(
                self._journalctl_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_JOURNALCTL_TIMEOUT
            )
        except Exception as exc:
            logger.error(
                "[checkup fetcher] journalctl spawn/run failed | error=%s", exc
            )
            raise CheckupLogsUnavailableException(
                f"journalctl unavailable: {exc}"
            ) from exc
        if proc.returncode != 0:
            tail = (stderr or b"").decode("utf-8", errors="replace").strip()[-200:]
            logger.error(
                "[checkup fetcher] journalctl unavailable | rc=%s | stderr_tail=%r",
                proc.returncode, tail,
            )
            raise CheckupLogsUnavailableException(
                f"journalctl rc={proc.returncode}: {tail}"
            )
        text = stdout.decode("utf-8", errors="replace")
        if not text.strip():
            logger.info("[checkup fetcher] journalctl ok | lines=0 (valid: логов нет)")
            return ""
        lines = [
            ln for ln in text.splitlines()
            if any(m in ln.lower() for m in _LOCAL_LINE_MARKERS)
        ][-_JOURNALCTL_MAX_LINES:]
        joined = "\n".join(lines)
        logger.info("[checkup fetcher] journalctl ok | lines=%d", len(lines))
        return joined[:_MAX_LOG_SYMBOLS]
