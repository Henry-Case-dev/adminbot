"""Раунд 7 (chat-lore-management-v2, T-774, B4) — RAM-кэш профилей лора.

Решение Q2 (spec §3.4): ОТДЕЛЬНЫЙ модуль `services/lore_cache.py`.
Инстанс один на процесс (создаётся в bot.py on_startup), шарится между
инжектом direct_chat, API-роутами и воркером.

Контракт:
  * `LoreProfile` — frozen-dataclass профиля чата (тип данных §3.3: поля
    §3.2, метки времени ISO-8601 UTC-строками).
  * `ChatLoreCache(store)`:
    - `get(chat_id) -> LoreProfile | None` — load-on-demand: miss →
      `store.get_profile(chat_id)` (резолв chat_id внутри store);
    - инвалидация: NOTIFY `lore_updated` → `invalidate(chat_id)` (B3);
      TTL-фолбэк 120 с (NOTIFY может потеряться; Q2/D6);
    - исключение/None → наружу None, в кэш НЕ кладётся (следующий вызов
      попробует снова) — fail-open: PG down — пусто, SQLite-fallback жив
      (легаси-путь инжекта); WARNING с дедупом (раз в 60 с);
    - гонки: asyncio.Lock на мутации + coalescing параллельных miss'ов
      (второй `get` того же chat_id не делает второй SELECT).

`resolve_chat_id` отдельно НЕ кэшируется (база: запрос в store; §3.4).
"""
import asyncio
import dataclasses
import logging
import time

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 120.0      # Q2/D6: TTL-фолбэк (NOTIFY может потеряться)
_WARN_EVERY_SECONDS = 60.0      # дедуп WARNING при недоступности PG


@dataclasses.dataclass(frozen=True)
class LoreProfile:
    """Профиль лора чата (spec §3.3): frozen; строки ISO-8601 UTC."""

    chat_id: int
    manual_lore: str
    auto_lore: str
    auto_enabled: bool
    auto_period_hours: int
    auto_window_hours: int
    is_active: bool
    last_auto_at: str | None
    updated_at: str

    def to_dict(self) -> dict:
        """Полный объект профиля (поля §3.2) — для API/сериализации."""
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class _Entry:
    profile: LoreProfile
    loaded_mono: float


class ChatLoreCache:
    """RAM-кэш `chat_id → LoreProfile` поверх ChatLoreStore (fail-open)."""

    def __init__(self, store, ttl_seconds: float = _CACHE_TTL_SECONDS):
        self._store = store
        self._ttl = ttl_seconds
        self._entries: dict[int, _Entry] = {}
        self._inflight: dict[int, asyncio.Future] = {}
        self._lock = asyncio.Lock()   # мутации dict'ов (asyncio-защита)
        self._last_warn_mono = 0.0

    @property
    def store(self):
        return self._store

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    # ── чтение ─────────────────────────────────────────────────────────────

    async def get(self, chat_id: int) -> LoreProfile | None:
        """Профиль чата: из кэша (TTL-фолбэк) или load-on-demand из store.

        PG недоступен/ошибка/профиля нет → None (fail-open, в кэш НЕ кладётся).
        Параллельные get одного chat_id коалесцируются в один SELECT
        (второй и последующие ждут inflight-future владельца).
        """
        now = time.monotonic()
        async with self._lock:
            entry = self._entries.get(chat_id)
            if entry is not None and now - entry.loaded_mono < self._ttl:
                return entry.profile
            inflight = self._inflight.get(chat_id)
            if inflight is None:
                inflight = asyncio.get_running_loop().create_future()
                self._inflight[chat_id] = inflight
                owner = True
            else:
                owner = False
        if not owner:
            # коалесинг: тот же chat_id уже грузится — ждём владельца
            try:
                return await asyncio.shield(inflight)
            finally:
                async with self._lock:
                    if self._inflight.get(chat_id) is inflight:
                        self._inflight.pop(chat_id, None)
        profile = None
        try:
            profile = await self._store.get_profile(chat_id)
        except asyncio.CancelledError:
            # отмена владельца: ждущие НЕ должны зависнуть навсегда — в
            # finally фьюча резолвится (None, fail-open); исключение уходит
            # дальше (задача владельца действительно отменена)
            raise
        except Exception:
            self._warn_once(chat_id)
        finally:
            async with self._lock:
                if self._inflight.get(chat_id) is inflight:
                    self._inflight.pop(chat_id, None)
            if not inflight.done():
                inflight.set_result(profile)
        if profile is None:
            return None
        async with self._lock:
            self._entries[chat_id] = _Entry(profile, time.monotonic())
        return profile

    def _warn_once(self, chat_id: int) -> None:
        """Fail-open WARNING с дедупом: не чаще раза в 60 секунд."""
        now = time.monotonic()
        if now - self._last_warn_mono >= _WARN_EVERY_SECONDS:
            self._last_warn_mono = now
            logger.warning(
                "[lore_cache] get failed — fail-open (None) | chat_id=%s",
                chat_id, exc_info=True)

    # ── инвалидация ────────────────────────────────────────────────────────

    async def invalidate(self, chat_id: int) -> None:
        """Удалить ключ кэша (NOTIFY `lore_updated` из B3 / служебно)."""
        async with self._lock:
            self._entries.pop(chat_id, None)
            self._inflight.pop(chat_id, None)

    async def invalidate_all(self) -> None:
        """Полная очистка (reload/служебные нужды; опционально, §3.4)."""
        async with self._lock:
            self._entries.clear()
            self._inflight.clear()

    def size(self) -> int:
        """Число закэшированных профилей (диагностика/тесты)."""
        return len(self._entries)
