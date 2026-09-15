"""Раунд 4 (T-706, spec 3.1, FR-B1/FR-B2/FR-B3) — собственный BetterStackHandler.

Замена logtail-python 0.4.0 (чёрный ящик: тихие дропы при Queue-Full, ошибки
только print в flusher): свой logging.Handler с logtail-СОВМЕСТИМЫМ JSON-фреймом
(make_betterstack_frame — эталон .venv/.../logtail/frame.py) и полной
наблюдаемостью вместо тихих потерь:

* буфер deque(maxlen=2000) + daemon-thread-флашер (раз в 1 с батчами до 500);
* POST https://{host} + `Authorization: Bearer {source_token}` (ADR-1019-1:
  токен — ТОЛЬКО заголовком, НЕ в path), stdlib urllib,
  Content-Type: application/json, тело — JSON-массив фреймов;
* счётчики sent/failed/dropped (+ get_stats()); журнал сбоев НЕ чаще 1/60 с;
  дроп при полном буфере — WARNING ≤1/60 с (не тихо); восстановление после
  серии сбоев — INFO «send ok | recovered | streak=N»;
* сообщение проходит log_ring.sanitize (R17) ДО отправки;
* анти-рекурсия: записи собственного модульного логгера
  (services.betterstack_handler) в сеть НЕ эхосируются (console/ring их видят).

FR-B3 (завершение): close() — stop → join → flush() остатка в вызывающем
потоке; вызывается logging.shutdown() из bot.py finally. NFR-1: emit никогда
не бросает (короткий lock; ошибки отправки живут в модульном логгере).

Токен — строго os.getenv("LOGTAIL_SOURCE_TOKEN") (bot.py), один на Errors и
Logs. ADR-1019-1: на **унифицированных US-кластерах** Source Token
(Telemetry) побайтово совпадает с public key из SENTRY_DSN — это НОРМА, а не
ошибка (владелец подтвердил скриншотами, раунд 10.19).

Раунд 10.18 (F1, ADR-1018-1): хост обязателен и берётся из env
`BETTERSTACK_HOST` (US-кластер проекта). Неявный EU-дефолт удалён
(`DEFAULT_HOST = ""`): конструктор без хоста бросает ValueError, а bot.py
при пустом хосте хендлер вообще не создаёт (fail-safe).

Раунд 10.19 (F1, **ADR-1019-1, AMEND ADR-1018-1 D2/D4/D6**): ingest-контракт
исправлен на официальный — `POST https://{host}` (без токена в path) +
`Authorization: Bearer {source_token}`. Прежний `POST https://{host}/{token}`
на unified US давал 401. `token_equals_sentry_public_key` остаётся дешёвой
диагностикой (DEBUG в bot.py), а не тревогой; подсказки по статусам — словарь
`_STATUS_HINTS` (R17: только коды и слова, без значений токена/URL).

D-01 (ревью 10.19): запросы идут через собственный opener с
`_NoRedirectHandler` — 3xx НЕ фоллоуится (токен не форвардится на чужой
`Location`, POST-тело не теряется, ложного `sent` нет): 3xx → `_mark_failed`
(`status=3xx`), без ретрая.
"""
import datetime
import hmac
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque

from services.log_ring import sanitize

logger = logging.getLogger(__name__)

# Пустой невозможный дефолт (ADR-1018-1 D2): любой явный вызов ОБЯЗАН
# передать host — EU in.logs.betterstack.com больше не подставляется молча.
DEFAULT_HOST = ""

_RATE_LIMIT_SECONDS = 60.0     # анти-спам журнала ошибок/дропов (spec 3.1.3)
_RETRY_PAUSE_SECONDS = 1.0     # пауза перед единственным повтором батча
_USER_AGENT = "adminbot/own-v1"

# ADR-1019-1 D3/D5: семантика ответов ingest BetterStack. Подсказки привязаны
# к коду; категоричного утверждения «token == public key = ошибка» больше нет
# (на unified US это норма). R17: значения токена/URL в текст НЕ попадают —
# только код и слова; ВСЕ 4xx (включая 429) НЕ ретраятся, 5xx/транспорт — ≤1
# повтор (как раньше).
_STATUS_HINTS = {
    401: "невалидный source token или не тот хост региона",
    402: "квота ingest исчерпана (проверьте план/объём)",
    403: "невалидный source token (Logs → Sources)",
    406: "битое тело батча (внутренняя ошибка, повторите после рестарта)",
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """D-01 (ADR-1019-1 D1): редиректы ingest-запроса ЗАПРЕЩЕНЫ.

    Дефолтный `HTTPRedirectHandler` на 301/302/303 повторил бы запрос на
    произвольный `Location`, **форвардя `Authorization: Bearer`** (утечка
    токена) и теряя POST-тело (302/303 → GET); финальный 2xx дал бы ложный
    `sent` — тихая потеря логов. Возврат `None` из `redirect_request` → базовый
    обработчик поднимает `HTTPError` 3xx → `_mark_failed`, без ретрая.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Единственный opener хендлера: те же дефолтные обработчики, но без
# follow-редиректов (D-01). Собирается один раз, сети на импорте нет.
_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def _urlopen(request, timeout):
    """Точка сетевого вызова (`_OPENER.open`); существует как отдельная
    функция-обёртка ради подмены в тестах (D-01)."""
    return _OPENER.open(request, timeout=timeout)

# SENTRY_DSN вида https://<public_key>@<host>/<project_id>
_SENTRY_DSN_USERINFO_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^@/]+)@")


def extract_sentry_public_key(dsn: str | None) -> str | None:
    """Public key (userinfo) из SENTRY_DSN `https://<key>@<host>/<id>`.

    Возвращает None при пустом/кривом DSN без userinfo. Не эвристика: берём
    ровно userinfo-часть URL."""
    if not dsn or not isinstance(dsn, str):
        return None
    match = _SENTRY_DSN_USERINFO_RE.match(dsn.strip())
    if not match:
        return None
    key = match.group(1).strip()
    return key or None


def token_equals_sentry_public_key(token: str | None,
                                   dsn: str | None) -> bool:
    """True, если `token` ТОЧНО равен public key из `SENTRY_DSN`
    (constant-time сравнение). Диагностика (ADR-1019-1 D4): на unified US
    совпадение — НОРМА; функция ничего не логирует и старт не блокирует."""
    pub = extract_sentry_public_key(dsn)
    if not token or not pub:
        return False
    try:
        return hmac.compare_digest(str(token), str(pub))
    except Exception:
        return False


def _rel_file(pathname: str) -> str:
    """file — relative к CWD при возможности, иначе pathname (logtail/frame.py)."""
    if not pathname:
        return ""
    try:
        cwd = os.getcwd()
        rel = os.path.relpath(pathname, cwd)
        return rel if not rel.startswith("..") else pathname
    except Exception:  # pragma: no cover — фрейм не должен падать
        return pathname


def make_betterstack_frame(record: logging.LogRecord, message: str) -> dict:
    """logtail-совместимый фрейм (logtail/frame.py). dt — ISO-UTC из
    record.created; level — levelname.lower(); severity = levelno // 10.
    message — ПРОШЕДШИЙ sanitize (R17). file — relative к CWD при
    возможности, иначе pathname. Доп. атрибуты записи (extra) НЕ включаем."""
    return {
        "dt": datetime.datetime.fromtimestamp(
            record.created, datetime.timezone.utc).isoformat(),
        "level": (record.levelname or "info").lower(),
        "severity": int(record.levelno) // 10,
        "message": message,
        "context": {
            "runtime": {"function": record.funcName, "file": _rel_file(record.pathname),
                        "line": record.lineno, "thread_id": record.thread,
                        "thread_name": record.threadName, "logger_name": record.name},
            "system": {"pid": record.process, "process_name": record.processName},
        },
    }


class _BadStatusError(Exception):
    """Не-2xx от BetterStack (4xx/5xx) — для ветки повтора внутри флашера."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"HTTP {status}")


class BetterStackHandler(logging.Handler):
    """Буферизующий BetterStack-хендлер с фоновым флашером и счётчиками.

    Конструктор: (source_token, host=..., level=INFO, buffer_size=2000,
    flush_interval=1.0, batch_size=500, timeout=10.0) — spec 3.1.
    """

    def __init__(self, source_token: str, host: str = DEFAULT_HOST,
                 level: int = logging.INFO, buffer_size: int = 2000,
                 flush_interval: float = 1.0, batch_size: int = 500,
                 timeout: float = 10.0) -> None:
        host = (host or "").strip()
        if not host:
            # ADR-1018-1 D2: неявный регион запрещён — хост обязателен.
            raise ValueError("BetterStackHandler: host is required")
        super().__init__(level=level)
        self.source_token = str(source_token or "")
        self.host = host
        self.flush_interval = max(0.05, float(flush_interval))
        self.batch_size = max(1, int(batch_size))
        self.timeout = float(timeout)
        # ADR-1019-1 D1/D2: официальный ingest-контракт — POST на голый хост
        # (токен в path УБРАН) + Authorization: Bearer. `_auth_header` в логи
        # не попадает (R17).
        self._url = f"https://{host}"
        self._auth_header = f"Bearer {self.source_token}"
        self._buffer: deque[dict] = deque(maxlen=max(1, int(buffer_size)))
        self._lock = threading.Lock()
        # Наблюдаемость (FR-B2): счётчики + rate-gate журнала ошибок/дропов.
        self.sent = 0
        self.failed = 0
        self.dropped = 0
        self._fail_streak = 0
        self._last_warn_ts = 0.0
        self._last_drop_warn_ts = 0.0
        self._stop = threading.Event()
        self._closed = False
        self._thread = threading.Thread(
            target=self._flush_loop, name="betterstack-flusher", daemon=True)
        self._thread.start()

    # ── эмиссия ────────────────────────────────────────────────────────────

    def emit(self, record: logging.LogRecord) -> None:
        """FR-B2/3.1.5: НИКОГДА не бросает. Собственный модульный логгер
        (services.betterstack_handler) в сеть не эхосируется — иначе сбой сети
        порождал бы бесконечный цикл «warning → отправка → warning»."""
        if record.name == __name__ or record.name.startswith(__name__ + "."):
            return
        try:
            message = sanitize(self.format(record))
            frame = make_betterstack_frame(record, message)
            dropped = False
            with self._lock:
                if len(self._buffer) >= self._buffer.maxlen:
                    self.dropped += 1
                    dropped = True
                else:
                    self._buffer.append(frame)
            if dropped:
                self._warn_drop()
        except Exception:  # pragma: no cover — emit не роняет логирование
            self.handleError(record)

    def _warn_drop(self) -> None:
        """Дроп при полном буфере — rate-limited WARNING (spec 3.1.3)."""
        now = time.monotonic()
        with self._lock:
            if now - self._last_drop_warn_ts < _RATE_LIMIT_SECONDS:
                return
            self._last_drop_warn_ts = now
        logger.warning("[betterstack] buffer full — dropped=%d", self.dropped)

    # ── флашер ─────────────────────────────────────────────────────────────

    def _flush_loop(self) -> None:
        while not self._stop.wait(self.flush_interval):
            self._flush_once()

    def _flush_once(self) -> None:
        items = self._drain(self.batch_size)
        if items:
            self._post(items)

    def _drain(self, limit: int) -> list[dict]:
        with self._lock:
            n = min(limit, len(self._buffer))
            return [self._buffer.popleft() for _ in range(n)]

    def _rate_warn(self, reason: str) -> None:
        """Журнал сбоя отправки: первая ошибка — сразу, далее ≤1/60 с."""
        now = time.monotonic()
        with self._lock:
            if now - self._last_warn_ts < _RATE_LIMIT_SECONDS:
                return
            self._last_warn_ts = now
            failed = self.failed
        logger.warning("[betterstack] send failed | reason=%s | failed=%d",
                       reason, failed)

    def _post(self, items: list[dict]) -> None:
        """Один батч в BetterStack. ADR-1019-1 D1: POST на `https://{host}` с
        заголовком `Authorization: Bearer {source_token}` (токена в URL нет).
        Ретрай ≤1 на транзиентное (5xx/транспорт, пауза 1 с); **все 4xx
        (включая 429) не ретраятся** (битый токен/квота/лимит — WARNING).
        D-01: редиректы запрещены (`_NoRedirectHandler`) — 3xx это отказ без
        повтора (токен не уходит на чужой `Location`)."""
        if not items:
            return
        body = json.dumps(items, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._url, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": self._auth_header,
                     "User-Agent": _USER_AGENT})
        retried = False
        while True:
            try:
                with _urlopen(request, timeout=self.timeout) as resp:
                    status = getattr(resp, "status", None)
                if status is not None and 300 <= status < 400:
                    # D-01: 3xx (если opener всё же вернул ответ) — отказ ДО
                    # проверки 2xx, без ретрая и без ложного `sent`.
                    self._mark_failed(f"status={status}", len(items))
                    return
                if status is not None and not 200 <= status < 300:
                    raise _BadStatusError(status)
                break                       # 2xx — успех
            except _BadStatusError as exc:
                if not retried and 500 <= exc.status < 600:
                    retried = True
                    self._stop.wait(_RETRY_PAUSE_SECONDS)
                    continue
                self._mark_failed(f"status={exc.status}", len(items))
                return
            except Exception as exc:        # URLError/HTTPError/таймаут/сеть
                status = getattr(exc, "code", None)
                if not retried and (status is None or status >= 500):
                    retried = True
                    self._stop.wait(_RETRY_PAUSE_SECONDS)
                    continue
                self._mark_failed(_reason(exc), len(items))
                return
        with self._lock:
            self.sent += len(items)
            streak = self._fail_streak
            self._fail_streak = 0
        if streak:
            logger.info("[betterstack] send ok | recovered | streak=%d", streak)

    def _mark_failed(self, reason: str, n: int) -> None:
        """ADR-1019-1 D3/D5: для известного кода (`_STATUS_HINTS`) reason
        дополняется словарной подсказкой; rate-gate ≤1/60с сохраняется;
        5xx/транспорт — без изменений; значений токена/URL в тексте нет
        (R17)."""
        hint = _STATUS_HINTS.get(_status_from_reason(reason))
        if hint:
            reason = f"{reason} | {hint}"
        with self._lock:
            self.failed += n
            self._fail_streak += 1
        self._rate_warn(reason)

    # ── завершение (FR-B3) ─────────────────────────────────────────────────

    def flush(self) -> None:
        """Синхронный досыл ВСЕГО остатка в вызывающем потоке (shutdown)."""
        while True:
            items = self._drain(self.batch_size)
            if not items:
                break
            self._post(items)

    def close(self) -> None:
        """stop → join → flush остатка → super().close(). Повторный вызов
        безвреден (AC-B5)."""
        if self._closed:
            return
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=max(2.0, self.flush_interval * 2 + 2.0))
        try:
            self.flush()
        except Exception:  # pragma: no cover — close не должен падать
            logger.warning("[betterstack] final flush failed", exc_info=True)
        self._closed = True
        super().close()

    def get_stats(self) -> dict:
        """FR-B2: счётчики наблюдаемости (journald/статус-эндпоинты)."""
        with self._lock:
            return {"sent": self.sent, "failed": self.failed,
                    "dropped": self.dropped}


def _status_from_reason(reason: str) -> int | None:
    """HTTP-код из reason вида 'status=NNN' (иначе None). R17-safe."""
    if isinstance(reason, str) and reason.startswith("status="):
        try:
            return int(reason.split("=", 1)[1].split(" ", 1)[0])
        except (ValueError, IndexError):
            return None
    return None


def _reason(exc: Exception) -> str:
    """Краткая причина сбоя без тела ответа (R17)."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"status={exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"transport: {type(exc.reason).__name__}" if exc.reason \
            else "transport: URLError"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return f"transport: {type(exc).__name__}"
