"""Epic 60 Фаза A (Section 63.1, D245, T-460) — персистентный троттлинг в БД.

Таблица `throttle_state` (миграция user_version 2→3, 63.3): все слоты
смарт-модуля в одной таблице (scope: 'search'|'factcheck'|'youtube'|'web'|
'checkup'|'info'|'direct_chat'|'direct_silence').

- PersistentCooldownTracker — те же семантики, что у in-memory
  CooldownTracker (dict-TTL per (chat, user)), но async и в БД:
  `await tracker.remaining(chat_id, user_id)`, `await tracker.touch(...)`.
- PersistentThrottle — те же семантики, что у DirectChatThrottle
  (token bucket, R50-7): `await throttle.allow(chat_id, user_id)` →
  0.0 = допустимо (заряд списан); >0 = остаток кулдауна, сек.

Атомарность (ФИНАЛ T-459 тема 9, эталон sl-map-web): refill+consume — ОДИН
UPSERT `INSERT ... ON CONFLICT DO UPDATE ... WHERE ... RETURNING burst_left`;
нет строки в RETURNING → отказ. SELECT-then-UPDATE ЗАПРЕЩЁН.

Стена: `time.time()` (НЕ monotonic — состояние переживает рестарт; сдвиг
системных часов — принятый риск 63.7 #1, прод на NTP).

Fail-open (63.1, прецедент SmartCache): ошибки БД → WARNING + пропуск
кулдауна (remaining/allow → 0.0, touch — no-op) — троттлинг НЕ роняет хендлер.

Выключатель `THROTTLE_PERSISTENT_ENABLED` (settings, default true): false →
ровно старые in-memory инстансы (`make_cooldown`); helper'ы
`cooldown_remaining`/`cooldown_touch` принимают и sync-, и async-трекеры
(обратная совместимость in-memory fallback-режима в хендлерах).
"""
import asyncio
import logging
import time

from config.settings import settings
from services import hot_config as hot
from services.smartmodule_throttling import CooldownTracker

logger = logging.getLogger(__name__)

# UPSERT-стейтмент token bucket (тема 9): refill+consume атомарно.
# INSERT-ветка (новый слот) — burst_left = capacity-1, last_ts = now.
# UPDATE-ветка — полный refill при истёкшем кулдауне (после ПОСЛЕДНЕГО
# допущенного обращения), иначе списать 1 заряд; WHERE отсекает отказ
# (нет строки в RETURNING). last_ts = now на КАЖДОМ допуске (R50-7:
# «полное восстановление после последнего допущенного обращения»).
_UPSERT_CONSUME_SQL = (
    "INSERT INTO throttle_state (scope, chat_id, user_id, burst_left, last_ts) "
    "VALUES (?, ?, ?, ?, ?) "
    "ON CONFLICT(scope, chat_id, user_id) DO UPDATE SET "
    "burst_left = CASE WHEN throttle_state.last_ts + ? <= ? THEN ? - 1 "
    "ELSE throttle_state.burst_left - 1 END, "
    "last_ts = excluded.last_ts "
    "WHERE throttle_state.last_ts + ? <= ? OR throttle_state.burst_left > 0 "
    "RETURNING burst_left"
)

_UPSERT_TOUCH_SQL = (
    "INSERT INTO throttle_state (scope, chat_id, user_id, burst_left, last_ts) "
    "VALUES (?, ?, ?, NULL, ?) "
    "ON CONFLICT(scope, chat_id, user_id) DO UPDATE SET last_ts = excluded.last_ts"
)


class PersistentCooldownTracker:
    """Dict-TTL-кулдаун per (chat_id, user_id) в таблице throttle_state
    (cooldown-стиль: burst_left NULL). Семантики CooldownTracker
    (smartmodule_throttling.py) сохранены; состояние переживает рестарт
    (стена time.time). Fail-open при ошибке БД."""

    def __init__(self, cooldown_seconds: float, scope: str, db) -> None:
        self._cooldown = cooldown_seconds
        self._scope = scope
        self._db = db

    async def remaining(self, chat_id: int, user_id: int) -> float:
        """Остаток кулдауна, сек (0.0 = можно выполнять). Fail-open → 0.0."""
        try:
            cursor = await self._db.db.execute(
                "SELECT last_ts FROM throttle_state "
                "WHERE scope = ? AND chat_id = ? AND user_id = ?",
                (self._scope, chat_id, user_id),
            )
            row = await cursor.fetchone()
        except Exception:
            logger.warning(
                "persistent throttle: remaining failed — fail-open | scope=%s",
                self._scope, exc_info=True)
            return 0.0
        if row is None:
            return 0.0
        return max(0.0, self._cooldown - (time.time() - row["last_ts"]))

    async def touch(self, chat_id: int, user_id: int) -> None:
        """Поставить/обновить слот (валидный триггер). Fail-open → no-op."""
        try:
            await self._db.db.execute(
                _UPSERT_TOUCH_SQL, (self._scope, chat_id, user_id, time.time()))
            await self._db.db.commit()
        except Exception:
            logger.warning(
                "persistent throttle: touch failed — fail-open | scope=%s",
                self._scope, exc_info=True)


class PersistentThrottle:
    """Token Bucket (R50-7) в throttle_state: per (chat_id, user_id),
    полное восстановление зарядов через cooldown_seconds после ПОСЛЕДНЕГО
    допущенного обращения. Семантики DirectChatThrottle.allow сохранены.
    refill+consume — один атомарный UPSERT (RETURNING). Fail-open → 0.0."""

    def __init__(self, burst_limit: int, cooldown_seconds: float,
                 scope: str, db) -> None:
        self._limit = burst_limit
        self._cooldown = cooldown_seconds
        self._scope = scope
        self._db = db

    async def allow(self, chat_id: int, user_id: int) -> float:
        """0.0 = допустимо (заряд списан); >0 = остаток кулдауна, сек."""
        now = time.time()
        try:
            cursor = await self._db.db.execute(
                _UPSERT_CONSUME_SQL,
                (self._scope, chat_id, user_id, self._limit - 1, now,
                 self._cooldown, now, self._limit,
                 self._cooldown, now),
            )
            row = await cursor.fetchone()
            await self._db.db.commit()
        except Exception:
            logger.warning(
                "persistent throttle: allow failed — fail-open | scope=%s",
                self._scope, exc_info=True)
            return 0.0
        if row is not None:
            return 0.0                            # заряд списан — допуск
        # Нет строки в RETURNING → отказ (WHERE не выполнился). Остаток —
        # read-only SELECT для фразы (никакого UPDATE по нему — SELECT-then-
        # UPDATE запрещён, а display-чтение после решения гонки не создаёт).
        try:
            cursor = await self._db.db.execute(
                "SELECT last_ts FROM throttle_state "
                "WHERE scope = ? AND chat_id = ? AND user_id = ?",
                (self._scope, chat_id, user_id),
            )
            row = await cursor.fetchone()
        except Exception:
            logger.warning(
                "persistent throttle: remaining read failed — fail-open | scope=%s",
                self._scope, exc_info=True)
            return 0.0
        if row is None:
            return 0.0
        return max(1.0, self._cooldown - (now - row["last_ts"]))


class SilenceStreak:
    """Epic 60 (65.3, T-471): счётчик «кулдаунов подряд» на человека —
    слот throttle_state scope='direct_silence' (burst_left = счётчик стачки,
    last_ts = время последнего кулдауна). bump() → новое значение стачки;
    ленивый сброс: если с последнего кулдауна прошёл cooldown_seconds —
    «кулдауны уже не подряд», стачка начинается с 1. reset() — полный сброс
    (успешный допуск). Fail-open: ошибка БД → WARNING + in-memory счётчик
    (стачка не роняет хендлер). db=None (THROTTLE_PERSISTENT_ENABLED=false) →
    ровно in-memory."""

    _SCOPE = "direct_silence"

    _BUMP_SQL = (
        "INSERT INTO throttle_state (scope, chat_id, user_id, burst_left, last_ts) "
        "VALUES (?, ?, ?, 1, ?) "
        "ON CONFLICT(scope, chat_id, user_id) DO UPDATE SET "
        "burst_left = CASE WHEN throttle_state.last_ts + ? <= ? THEN 1 "
        "ELSE throttle_state.burst_left + 1 END, "
        "last_ts = excluded.last_ts "
        "RETURNING burst_left"
    )

    def __init__(self, cooldown_seconds: float, db=None) -> None:
        self._cooldown = cooldown_seconds
        self._db = db
        self._mem: dict[tuple[int, int], tuple[int, float]] = {}

    async def bump(self, chat_id: int, user_id: int) -> int:
        """+1 к стачке (с ленивым сбросом по времени), возврат нового значения."""
        if self._db is not None:
            try:
                cursor = await self._db.db.execute(
                    self._BUMP_SQL,
                    (self._SCOPE, chat_id, user_id, time.time(),
                     self._cooldown, time.time()),
                )
                row = await cursor.fetchone()
                await self._db.db.commit()
                if row is not None:
                    return int(row["burst_left"])
            except Exception:
                logger.warning(
                    "persistent throttle: silence streak bump failed — "
                    "in-memory fallback | scope=%s", self._SCOPE, exc_info=True)
        return self._bump_mem(chat_id, user_id)

    def _bump_mem(self, chat_id: int, user_id: int) -> int:
        now = time.time()
        key = (chat_id, user_id)
        state = self._mem.get(key)
        if state is None or now - state[1] >= self._cooldown:
            streak = 1                              # кулдауны уже не подряд
        else:
            streak = state[0] + 1
        self._mem[key] = (streak, now)
        return streak

    async def reset(self, chat_id: int, user_id: int) -> None:
        """Полный сброс стачки (успешный допуск — 65.3). Fail-open → no-op."""
        if self._db is not None:
            try:
                await self._db.db.execute(
                    "DELETE FROM throttle_state "
                    "WHERE scope = ? AND chat_id = ? AND user_id = ?",
                    (self._SCOPE, chat_id, user_id))
                await self._db.db.commit()
                return
            except Exception:
                logger.warning(
                    "persistent throttle: silence streak reset failed — "
                    "in-memory fallback | scope=%s", self._SCOPE, exc_info=True)
        self._mem.pop((chat_id, user_id), None)


def make_cooldown(scope: str, cooldown_seconds: float, db):
    """63.1: рубильник THROTTLE_PERSISTENT_ENABLED. true + db → persistent;
    false/нет db → ровно старый in-memory CooldownTracker (аварийный режим,
    прецедент SMART_CACHE_ENABLED)."""
    if hot.get("flags.throttle_persistent_enabled", settings.THROTTLE_PERSISTENT_ENABLED) and db is not None:
        return PersistentCooldownTracker(cooldown_seconds, scope, db)
    return CooldownTracker(cooldown_seconds)


def cooldown_refresh(tracker, cooldown_seconds: float) -> None:
    """T-619 (84.4): актуализировать интервал кулдауна ПЕРЕД проверкой —
    значение из ConfigCache (hot.get) с фолбеком на settings; после
    POST /api/config следующий запрос уже с новым интервалом.
    Совместим с CooldownTracker и PersistentCooldownTracker."""
    if hasattr(tracker, "_cooldown"):
        tracker._cooldown = cooldown_seconds


async def cooldown_remaining(tracker, chat_id: int, user_id: int) -> float:
    """Хендлер-helper: принимает и sync- (in-memory fallback), и async-
    (persistent) трекер. `await` только если результат — корутина."""
    result = tracker.remaining(chat_id, user_id)
    if asyncio.iscoroutine(result):
        result = await result
    return result


async def cooldown_touch(tracker, chat_id: int, user_id: int) -> None:
    """Хендлер-helper: sync/async-touch без дублирования веток."""
    result = tracker.touch(chat_id, user_id)
    if asyncio.iscoroutine(result):
        await result
