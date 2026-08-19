"""Epic 42/44/45 — CheckupLogsFetcher (Section 54.3, R45-1/R45-2, D173).

Epic 45: ступень 1 — Betterstack SQL API (ClickHouse HTTP, Basic auth, POST
SQL-тела, JSONEachRow). Каскад: SQL API → journalctl (фолбек НЕПРИКОСНОВЕНЕН,
канон Epic 42/51.3). Обе ступени мертвы → CheckupLogsUnavailableException
(хендлер шлёт CHECKUP_DEAD_PHRASES). Пустые host/user/password ИЛИ пустой SQL
(нет ни QUERY, ни TABLE) → ступень 1 пропускается (WARNING) → journalctl.
Легаси live-tail (Epic 44: BETTERSTACK_TOKEN/SOURCE_IDS/QUERY) УДАЛЁН (54.4).
Значения кредов НЕ логируются (R17): только факт configured/not configured.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

# КАНОН SQL-тела R45-1 (54.3): {table} — префикс сорса, {limit} — потолок.
_SQL_QUERY_TEMPLATE = (
    "SELECT dt, raw FROM remote({table}_logs) UNION ALL "
    "SELECT dt, raw FROM s3Cluster(primary, {table}_s3) WHERE _row_type = 1 "
    "ORDER BY dt DESC LIMIT {limit} FORMAT JSONEachRow"
)
_SQL_LIMIT = 200                        # LIMIT N == потолку событий (обе ступени)
_SQL_ROW_NUMBERS_PARAM = "output_format_pretty_row_numbers=0"   # канон доков (54.1)
_SQL_TIMEOUT = 15.0
_MAX_LOG_EVENTS = 200
_MAX_LOG_SYMBOLS = 20000
_MAX_EVENT_MESSAGE_CHARS = 400
_JOURNALCTL_MAX_LINES = 300
_JOURNALCTL_TIMEOUT = 15.0
_LEVEL_KEYWORDS = (
    "error", "warning", "warn", "critical", "alert", "fatal",
    "exception", "traceback",
)                                    # фильтр уровней локально по raw (как раньше)
_LOCAL_LINE_MARKERS = ("error", "warning", "traceback")   # фильтр journalctl (ТЗ)
_TS_NUMERIC_RE = re.compile(r"^\d{9,13}(?:\.\d+)?$")


class CheckupLogsUnavailableException(Exception):
    """Обе ступени каскада мертвы (SQL API + journalctl)."""


class CheckupLogsFetcher:
    def __init__(
        self,
        sql_host: str = settings.CHECKUP_BETTERSTACK_SQL_HOST,
        sql_user: str = settings.CHECKUP_BETTERSTACK_SQL_USER,
        sql_password: str = settings.CHECKUP_BETTERSTACK_SQL_PASSWORD,
        sql_table: str = settings.CHECKUP_BETTERSTACK_SQL_TABLE,
        sql_query: str = settings.CHECKUP_BETTERSTACK_SQL_QUERY,
        journalctl_cmd: str = settings.CHECKUP_JOURNALCTL_CMD,
        transport: httpx.AsyncBaseTransport | None = None,   # тесты: MockTransport
    ) -> None:
        self._sql_host = sql_host
        self._sql_user = sql_user
        self._sql_password = sql_password
        self._sql_table = sql_table
        self._sql_query = sql_query
        self._journalctl_cmd = journalctl_cmd
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(_SQL_TIMEOUT, connect=10.0),
                auth=(self._sql_user, self._sql_password) if self._sql_user else None,
                headers={"Content-type": "plain/text"},    # КАНОН R45-1 (не text/plain)
                transport=self._transport,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self) -> tuple[str, bool]:
        """(logs_text, used_fallback). SQL API ок → (text, False).
        SQL упал/пропущен → journalctl → (text, True). Оба мертвы → raise."""
        if not (self._sql_host.strip() and self._sql_user.strip()
                and self._sql_password.strip()):
            logger.warning("[checkup fetcher] sql api skipped (no host/user/password) → journalctl")
            return await self._fetch_journalctl(), True
        if not (self._sql_query.strip() or self._sql_table.strip()):
            logger.warning("[checkup fetcher] sql api skipped (no query/table) → journalctl")
            return await self._fetch_journalctl(), True
        try:
            return await self._fetch_sql(), False
        except (httpx.HTTPError, ValueError) as exc:
            # httpx.TimeoutException — подкласс httpx.RequestError (входит в HTTPError)
            logger.warning(
                "[checkup fetcher] sql api failed → journalctl fallback | error=%s", exc
            )
            return await self._fetch_journalctl(), True

    # ── Ступень 1: Betterstack SQL API (ClickHouse HTTP, 54.3) ───────

    async def _fetch_sql(self) -> str:
        body = self._sql_query.strip() or _SQL_QUERY_TEMPLATE.format(
            table=self._sql_table.strip(), limit=_SQL_LIMIT
        )
        resp = await self._get_client().post(
            self._sql_host,
            params={"output_format_pretty_row_numbers": "0"},   # канон (54.1)
            content=body,                                        # сырое SQL-тело
        )
        resp.raise_for_status()               # 401/404/5xx → фолбек (54.3-каскад)
        lines = self._parse_jsoneachrow(resp.text)
        text = "\n".join(lines[:_MAX_LOG_EVENTS])
        logger.info(
            "[checkup fetcher] sql api ok | events=%d | chars=%d",
            len(lines), len(text),
        )
        return text[:_MAX_LOG_SYMBOLS]

    @staticmethod
    def _parse_jsoneachrow(text: str) -> list[str]:
        """JSONEachRow (54.1/54.3): одна строка == один JSON-объект {dt, raw}.
        dt — DateTime (строка «YYYY-MM-DD HH:MM:SS…» | unix-число) →
        «YYYY-MM-DD HH:MM:SS» (число — через fromtimestamp UTC); raw — полная
        строка лога. Уровень извлекается ИЗ raw (первое вхождение keyword
        _LEVEL_KEYWORDS, регистронезависимо; warn → WARNING), нет keyword →
        строка фильтруется локально (как раньше, 51.3). Кривая JSON-строка —
        пропускается (WARNING-счётчик). Толерантность: алиасы raw|message|msg,
        dt|timestamp|_dt; не-dict объект — пропуск."""
        out: list[str] = []
        skipped = 0
        for line in str(text).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(obj, dict):
                skipped += 1
                continue
            raw = obj.get("raw") or obj.get("message") or obj.get("msg") or ""
            if not isinstance(raw, str):
                raw = str(raw)
            if not any(k in raw.lower() for k in _LEVEL_KEYWORDS):
                continue                      # нерелевантный уровень — мимо
            level = CheckupLogsFetcher._extract_level(raw)
            ts = obj.get("dt") or obj.get("timestamp") or obj.get("_dt") or "-"
            if isinstance(ts, (int, float)) or _TS_NUMERIC_RE.match(str(ts)):
                try:
                    ts = datetime.fromtimestamp(float(ts), tz=timezone.utc) \
                        .strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, OSError):
                    ts = str(ts)
            # Тест-план 54.6 #1: «ERROR disk exploded» → message «disk exploded»
            # (лидирующий level-токен выносится в поле LEVEL, не дублируется).
            msg_raw = re.sub(
                r"^(?:error|warning|warn|critical|alert|fatal|exception|traceback)"
                r"\b[:\s]*",
                "", raw, flags=re.IGNORECASE,
            ).strip()
            msg = " ".join(msg_raw.split())[:_MAX_EVENT_MESSAGE_CHARS]
            out.append(f"{ts} - {level} - {msg}")
            if len(out) >= _MAX_LOG_EVENTS:
                break
        if skipped:
            logger.warning(
                "[checkup fetcher] sql api: skipped %d broken JSONEachRow line(s)", skipped
            )
        return out

    @staticmethod
    def _extract_level(raw: str) -> str:
        """Первое вхождение keyword уровней в raw; warn → WARNING (54.1)."""
        lowered = raw.lower()
        for keyword in _LEVEL_KEYWORDS:
            if keyword in lowered:
                return "WARNING" if keyword == "warn" else keyword.upper()
        return "-"

    # ── Ступень 2: journalctl (локальный фолбек) — БЕЗ изменений (51.3) ──

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
