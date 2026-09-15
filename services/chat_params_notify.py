"""Раунд 10.18 (F7 settings-worker-sync, T-1764, ADR-1018-7 D6) — LISTEN
`chat_params_updated` → инвалидация `ChatParamsCache`.

Закрывает кросс-процессный рассинхрон: web-процесс пишет слой чата
(`chat_profiles.chat_params.overrides`) и шлёт `pg_notify`, а бот-процесс,
подписанный на канал, инвалидирует кэш чата НЕМЕДЛЕННО — вместо ожидания
TTL 120с (`services/chat_params.py::_CACHE_TTL`).

Ключевой факт (фикс R10.18-1): у `asyncpg.Pool` НЕТ метода `add_listener`
(проверено на 0.31.0) — слушать канал можно только на `asyncpg.Connection`.
Поэтому открываем ОТДЕЛЬНОЕ прямое соединение `asyncpg.connect(dsn)` и вешаем
`add_listener`; паттерн — `services/lore_notify.py`.

Lifecycle (fail-open, бот НИКОГДА не роняется):
  * `start()` — фоновый цикл: connect (`init`-кодеки как у пула) + listen;
    недоступность PG/обрыв → WARNING (rate-limited) + реконнект с backoff
    (1с → 60с, сброс после успеха);
  * `stop()` — закрыть соединение и завершить цикл.

Ошибка подключения/`add_listener` не фатальна: кэш живёт на TTL 120с
(документированная граница, spec §4.5).
"""
import asyncio
import logging
import time

import asyncpg

from services import pg_db as pg_db_module

logger = logging.getLogger(__name__)

CHANNEL = "chat_params_updated"
_BACKOFF_MIN = 1.0
_BACKOFF_MAX = 60.0
_POLL_INTERVAL = 0.2
# Анти-спам прода: повторные WARNING не чаще раза в минуту (далее — debug).
_WARN_COOLDOWN = 60.0


class ChatParamsNotify:
    """LISTEN-подписка `chat_params_updated` → `invalidate_chat` кэша."""

    def __init__(self, dsn: str | None = None, init_fn=None, *,
                 retry_interval: float = _BACKOFF_MAX,
                 connector=None, warn_cooldown: float = _WARN_COOLDOWN):
        self._dsn = dsn
        # `init` есть только у create_pool — у connect кодеки ставим вручную.
        self._init_fn = init_fn if init_fn is not None else \
            pg_db_module._init_connection
        # retry_interval — и потолок backoff, и пауза между реконнектами.
        self._retry_interval = max(0.01, retry_interval)
        self._warn_cooldown = max(0.0, warn_cooldown)
        self._connector = connector or self._connect_default
        self._conn = None
        self._task: asyncio.Task | None = None
        self._stop = False
        self._last_warn = 0.0
        # R10.18-11: сильные ссылки на фоновые invalidate-задачи — иначе GC
        # может уничтожить «висящую» таску до завершения, а shutdown — не
        # увидеть её. Убираем по завершении (done-callback).
        self._pending: set[asyncio.Task] = set()

    async def _connect_default(self) -> asyncpg.Connection:
        """Прямое соединение по DSN (кодеки json/jsonb — как у пула).

        ВАЖНО: `init` есть только у `asyncpg.create_pool` — у `connect`
        такого параметра нет, поэтому кодеки применяем вручную сразу после
        connect, до первого запроса (прецедент `lore_notify`)."""
        conn = await asyncpg.connect(self._dsn)
        if self._init_fn is not None:
            await self._init_fn(conn)
        return conn

    # ── rate-limited предупреждения (анти-спам прода) ───────────────────────

    def _warn(self, msg: str, *args, exc_info: bool = False) -> None:
        now = time.monotonic()
        if now - self._last_warn >= self._warn_cooldown:
            self._last_warn = now
            logger.warning(msg, *args, exc_info=exc_info)
        else:
            logger.debug(msg, *args)

    # ── lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Фоновый цикл слушателя: connect+listen, реконнект с backoff.
        Обычно вызывается через `asyncio.create_task(notify.start())`."""
        self._stop = False
        self._task = asyncio.current_task()
        delay = _BACKOFF_MIN
        while not self._stop:
            try:
                conn = await self._connector()
            except Exception:
                self._warn(
                    "[chat_params] LISTEN connect failed — retry in %.0fs "
                    "(fail-open; TTL fallback 120s)", delay, exc_info=True)
                await self._sleep(delay)
                delay = min(delay * 2.0, self._retry_interval)
                continue
            delay = _BACKOFF_MIN
            try:
                await conn.add_listener(CHANNEL, self._on_notify)
                self._conn = conn
                logger.info("[chat_params] LISTEN '%s' attached", CHANNEL)
                while not self._stop and not conn.is_closed():
                    await asyncio.sleep(_POLL_INTERVAL)
            except Exception:
                self._warn("[chat_params] LISTEN connection lost — "
                           "reconnecting", exc_info=True)
            finally:
                if self._conn is conn:
                    self._conn = None
                try:
                    await conn.close()
                except Exception:
                    pass
            if not self._stop:
                await self._sleep(self._retry_interval)

    async def _sleep(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise

    async def stop(self) -> None:
        """Остановить цикл, отменить фоновые invalidate-задачи и закрыть
        соединение (fail-open). Вызывается из `bot.py::on_shutdown()`
        (S10.18-7 — lifecycle-метод, а не «мёртвый» код)."""
        self._stop = True
        task = self._task
        if task is not None and task is not asyncio.current_task() \
                and not task.done():
            task.cancel()
        for pending in list(self._pending):
            pending.cancel()
        self._pending.clear()
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                logger.debug("[chat_params] close: уже закрыто")
        logger.info("[chat_params] notify stopped")

    # ── колбэк слушателя ───────────────────────────────────────────────────

    def _on_notify(self, conn, pid: int, channel: str, payload: str) -> None:
        """NOTIFY `chat_params_updated` payload=str(chat_id) → invalidate.

        Колбэк СИНХРОННЫЙ (прецедент `LoreNotify`): тяжёлый async-invalidate
        выполняется отдельной задачей, исключения наружу не летят и не роняют
        задачу слушателя. R10.18-11: держим сильную ссылку на задачу в
        `self._pending` и снимаем по завершении (done-callback)."""
        try:
            task = asyncio.create_task(self._safe_invalidate(payload))
        except RuntimeError:
            logger.warning(
                "[chat_params] no running loop — invalidate skipped | "
                "payload=%s", payload)
            return
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _safe_invalidate(self, payload) -> None:
        from services.chat_params import invalidate_chat_from_notify
        try:
            await invalidate_chat_from_notify(payload)
        except Exception:
            logger.warning(
                "[chat_params] notify invalidate failed — fail-open | "
                "payload=%s", payload, exc_info=True)
