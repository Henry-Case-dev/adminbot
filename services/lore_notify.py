"""Раунд 7 (chat-lore-management-v2, T-773, B3) — LISTEN-подписка lore_updated.

Отдельное asyncpg-соединение (НЕ из пула; §3.4/Q4): `add_listener` на канал
`lore_updated`; колбэк `(conn, pid, channel, payload)` → task
`cache.invalidate(int(payload))` — никогда не роняет задачу слушателя
(try/except WARNING).

Lifecycle:
  * `start()` — главный цикл (фоновый, запускается `asyncio.create_task`):
    попытка connect (с init-колбэком json-кодеков, как пул pg_db) + listen;
    недоступность PG/обрыв соединения → WARNING + ретрай каждые 60 с
    (fail-open: бот жив, TTL-фолбэк кэша 120 с лечит потерянные NOTIFY);
  * `stop()` — закрытие соединения и завершение цикла.

Не блокирует main: сам `start()` не завершается до `stop()`.
"""
import asyncio
import logging

import asyncpg

from services import pg_db as pg_db_module

logger = logging.getLogger(__name__)

_CHANNEL = "lore_updated"
_RETRY_INTERVAL = 60.0
_POLL_INTERVAL = 0.2


class LoreNotify:
    """LISTEN-подписка `lore_updated` → инвалидация ChatLoreCache."""

    def __init__(self, cache, dsn: str | None = None, init_fn=None, *,
                 retry_interval: float = _RETRY_INTERVAL,
                 connector=None):
        self._cache = cache
        self._dsn = dsn
        self._init_fn = init_fn if init_fn is not None else \
            pg_db_module._init_connection
        self._retry_interval = max(0.5, retry_interval)
        self._connector = connector or self._connect_default
        self._conn = None
        self._task: asyncio.Task | None = None
        self._stop = False

    async def _connect_default(self) -> asyncpg.Connection:
        """Прямое соединение по DSN (кодеки json/jsonb — как у пула)."""
        return await asyncpg.connect(self._dsn, init=self._init_fn)

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Фоновый цикл слушателя: connect+listen, ретрай каждые N сек.
        Обычно вызывается через `asyncio.create_task(notify.start())`."""
        self._stop = False
        self._task = asyncio.current_task()
        warned_retry = False
        while not self._stop:
            try:
                conn = await self._connector()
            except Exception:
                if not warned_retry:
                    logger.warning(
                        "[lore_notify] PG недоступен — LISTEN-подписка "
                        "не активна, ретрай каждые %.0f с (fail-open; "
                        "TTL-фолбэк кэша 120 с)", self._retry_interval,
                        exc_info=True)
                    warned_retry = True
                await self._sleep_between()
                continue
            warned_retry = False
            try:
                await conn.add_listener(_CHANNEL, self._on_notify)
                self._conn = conn
                logger.info("[lore_notify] listening on '%s'", _CHANNEL)
                while not self._stop and not conn.is_closed():
                    await asyncio.sleep(_POLL_INTERVAL)
            except Exception:
                logger.warning("[lore_notify] соединение оборвано — "
                               "переподключение", exc_info=True)
            finally:
                if self._conn is conn:
                    self._conn = None
                try:
                    await conn.close()
                except Exception:
                    pass
            if not self._stop:
                await self._sleep_between()

    async def _sleep_between(self) -> None:
        """Пауза до следующей попытки (прерывается stop-ом)."""
        try:
            await asyncio.sleep(self._retry_interval)
        except asyncio.CancelledError:
            raise

    async def stop(self) -> None:
        """Закрыть соединение и завершить цикл start()."""
        self._stop = True
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                logger.debug("[lore_notify] close: уже закрыто")
        task = self._task
        if task is not None and task is not asyncio.current_task():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        logger.info("[lore_notify] stopped")

    # ── колбэк слушателя ───────────────────────────────────────────────────

    def _on_notify(self, conn, pid: int, channel: str, payload: str) -> None:
        """NOTIFY `lore_updated` payload=str(chat_id) → invalidate кэша.
        Исключения никогда не роняют задачу слушателя (WARNING)."""
        try:
            chat_id = int(payload)
        except (TypeError, ValueError):
            logger.warning("[lore_notify] кривой payload: %r", payload)
            return
        try:
            asyncio.create_task(self._safe_invalidate(chat_id))
        except RuntimeError:
            logger.warning("[lore_notify] no running loop — invalidate "
                           "пропущен | chat_id=%s", chat_id)

    async def _safe_invalidate(self, chat_id: int) -> None:
        try:
            await self._cache.invalidate(chat_id)
        except Exception:
            logger.warning("[lore_notify] invalidate failed | chat_id=%s",
                           chat_id, exc_info=True)
