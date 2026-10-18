"""Epic 60 Фаза A (Section 63.1, D245, T-460) — персистентный троттлинг в БД.

Таблица `throttle_state` (миграция user_version 2→3, 63.3): все слоты
смарт-модуля в одной таблице (scope: 'search'|'factcheck'|'youtube'|'web'|
'checkup'|'info'|'direct_chat'|'direct_silence'|'image_freq').

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

CFG-01 (§01.2/§01.4/§01.5) — effective-лимиты Direct Chat и судьба состояния:

* `resolve_direct_chat_limits(chat_id)` — per-chat override → глобальное
  значение ConfigCache → settings-дефолт (+ источник `chat|global|factory`),
  переиспользуется существующий резолвер `chat_params` (spec §4.5);
* `throttle_refresh(...)` — применить их перед проверкой (hot-reload без
  рестарта в пределах гарантированного времени: global — немедленно,
  override — NOTIFY-инвалидация, не позднее TTL 120 с);
* перезапуск: persistent-режим (прод-дефолт) СОХРАНЯЕТ состояние слота
  (`throttle_state`, стена `time.time`), in-memory fallback-режим
  (`THROTTLE_PERSISTENT_ENABLED=false` — аварийный) сбрасывает его вместе с
  процессом и виден только своему инстансу; несколько процессов в
  persistent-режиме делят один слот (проверено тестами).
"""
import asyncio
import dataclasses
import logging
import math
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
# CFG-01 (§01.2): ёмкость берётся из EFFECTIVE-лимита текущего запроса и
# накопленный остаток обрезается до неё (`MIN` — скалярная функция SQLite,
# `COALESCE` — слот после cooldown-стиля с burst_left IS NULL трактуется как
# исчерпанный): уменьшение лимита не даёт «бонусных» обращений из старого
# запаса, увеличение не выдаёт заряды до штатного полного восстановления;
# состояние (last_ts) не сбрасывается. Всё — в ОДНОМ UPSERT, поэтому кламп
# работает и для нескольких процессов/воркеров сразу (состояние в БД, не в
# инстансе).
_UPSERT_CONSUME_SQL = (
    "INSERT INTO throttle_state (scope, chat_id, user_id, burst_left, last_ts) "
    "VALUES (?, ?, ?, ?, ?) "
    "ON CONFLICT(scope, chat_id, user_id) DO UPDATE SET "
    "burst_left = CASE WHEN throttle_state.last_ts + ? <= ? THEN ? - 1 "
    "ELSE MIN(COALESCE(throttle_state.burst_left, 0), ?) - 1 END, "
    "last_ts = excluded.last_ts "
    "WHERE throttle_state.last_ts + ? <= ? "
    "OR MIN(COALESCE(throttle_state.burst_left, 0), ?) > 0 "
    "RETURNING burst_left"
)

_UPSERT_TOUCH_SQL = (
    "INSERT INTO throttle_state (scope, chat_id, user_id, burst_left, last_ts) "
    "VALUES (?, ?, ?, NULL, ?) "
    "ON CONFLICT(scope, chat_id, user_id) DO UPDATE SET last_ts = excluded.last_ts"
)


async def _db_write(db, op, *, op_name: str, chat_id):
    """F0.5 (ADR-1025-5): запись через публичный `Database.write_transaction`
    (single-writer + bounded retry на `database is locked`). Сырой
    `db.db.execute`/`commit` устранён (T-2449). Фолбэк на прежний путь — для
    тестовых двойников без публичного API."""
    tx = getattr(db, "write_transaction", None)
    if tx is not None:
        return await tx(op, op_name=op_name, chat_id=chat_id)
    # Фолбэк на сырой путь — ТОЛЬКО для тестовых двойников без публичного API
    # (в проде `Database.write_transaction` всегда есть). Не молчаливо.
    logger.warning(
        "persistent throttle: write_transaction отсутствует — сырой путь "
        "(тестовый двойник?) | op=%s", op_name)
    try:
        result = await op(db.db)
        await db.db.commit()  # mca01-write-fallback: db double без write_transaction
        return result
    except Exception:
        try:
            await db.db.rollback()
        except Exception:
            pass
        raise


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
        """Поставить/обновить слот (валидный триггер). Fail-open → no-op.

        F0.5: через публичный write_transaction (single-writer + retry)."""
        async def _body(conn):
            await conn.execute(
                _UPSERT_TOUCH_SQL,
                (self._scope, chat_id, user_id, time.time()))
        try:
            await _db_write(self._db, _body, op_name="throttle_touch",
                            chat_id=chat_id)
        except Exception:
            logger.warning(
                "persistent throttle: touch failed — fail-open | scope=%s",
                self._scope, exc_info=True)


class PersistentThrottle:
    """Token Bucket (R50-7) в throttle_state: per (chat_id, user_id),
    полное восстановление зарядов через cooldown_seconds после ПОСЛЕДНЕГО
    допущенного обращения. Семантики DirectChatThrottle.allow сохранены.
    refill+consume — один атомарный UPSERT (RETURNING). Fail-open → 0.0.

    CFG-01: лимиты (`burst_limit`/`cooldown_seconds`) — не константа
    инстанса, а EFFECTIVE-значение вызывающего хода: `refresh()` применяет
    per-chat override → global → factory ДО проверки (hot-reload без
    рестарта). Состояние живёт в БД, поэтому перезапуск процесса его
    сохраняет, а несколько процессов видят один и тот же слот."""

    def __init__(self, burst_limit: int, cooldown_seconds: float,
                 scope: str, db) -> None:
        self._limit, self._cooldown = normalize_direct_chat_limits(
            burst_limit, cooldown_seconds)
        self._scope = scope
        self._db = db

    def refresh(self, burst_limit: int, cooldown_seconds: float) -> None:
        """CFG-01 (§01.2): новые лимиты на СЛЕДУЮЩУЮ проверку (состояние не
        сбрасывается, остаток зарядов обрезается в SQL до нового лимита)."""
        self._limit, self._cooldown = normalize_direct_chat_limits(
            burst_limit, cooldown_seconds)

    async def allow(self, chat_id: int, user_id: int) -> float:
        """0.0 = допустимо (заряд списан); >0 = остаток кулдауна, сек.

        F0.5: атомарный UPSERT через публичный write_transaction."""
        now = time.time()

        async def _body(conn):
            cursor = await conn.execute(
                _UPSERT_CONSUME_SQL,
                (
                    self._scope, chat_id, user_id, self._limit - 1, now,
                    # refill: полное восстановление → limit минус списанный заряд
                    self._cooldown, now, self._limit,
                    # кламп накопленного остатка до текущего лимита
                    self._limit,
                    self._cooldown, now, self._limit,
                ),
            )
            return await cursor.fetchone()

        try:
            row = await _db_write(self._db, _body, op_name="throttle_allow",
                                  chat_id=chat_id)
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
            async def _body(conn):
                cursor = await conn.execute(
                    self._BUMP_SQL,
                    (self._SCOPE, chat_id, user_id, time.time(),
                     self._cooldown, time.time()),
                )
                return await cursor.fetchone()

            try:
                row = await _db_write(self._db, _body, op_name="silence_bump",
                                      chat_id=chat_id)
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
            async def _body(conn):
                await conn.execute(
                    "DELETE FROM throttle_state "
                    "WHERE scope = ? AND chat_id = ? AND user_id = ?",
                    (self._SCOPE, chat_id, user_id))

            try:
                await _db_write(self._db, _body, op_name="silence_reset",
                                chat_id=chat_id)
                return
            except Exception:
                logger.warning(
                    "persistent throttle: silence streak reset failed — "
                    "in-memory fallback | scope=%s", self._SCOPE, exc_info=True)
        self._mem.pop((chat_id, user_id), None)


# ── CFG-01: effective-лимиты Direct Chat (hot-reload + per-chat + источник) ──
# Ключи каталога (param_catalog, категория limits_chat → per_chat=True).
CHAT_BURST_LIMIT_KEY = "limits.chat_burst_limit"
CHAT_COOLDOWN_SECONDS_KEY = "limits.chat_cooldown_seconds"


def normalize_direct_chat_limits(burst_limit, cooldown_seconds):
    """CFG-01 (§01.4): единицы/границы лимитов Direct Chat.

    * `burst_limit` — ЦЕЛОЕ число обращений подряд до паузы, ≥ 1. Значения
      ≤ 0 (0/-1/мусор, если такое попало в слой настроек) нормализуются в 1
      («одно обращение до паузы») — вечного лока из-за нуля не возникает;
    * `cooldown_seconds` — пауза в СЕКУНДАХ, ≥ 0. `0` = окно не ограничивает
      (каждый запрос получает полное восстановление зарядов), отрицательные/
      нечисловые/NaN → 0.

    Возвращает `(burst_limit: int, cooldown_seconds: float)`."""
    try:
        limit = int(burst_limit)
    except (TypeError, ValueError):
        limit = 1
    try:
        cooldown = float(cooldown_seconds)
    except (TypeError, ValueError):
        cooldown = 0.0
    if not math.isfinite(cooldown):
        cooldown = 0.0
    return max(1, limit), max(0.0, cooldown)


async def resolve_direct_chat_limits(chat_id: int):
    """CFG-01 (§01.1/§01.2/§01.3): эффективные лимиты Direct Chat для чата.

    Порядок — существующий резолвер per-chat слоя (`chat_params`,
    spec §4.5): override своего скоупа → глобальное значение ConfigCache
    (hot-reload без рестарта, 84.4) → settings-дефолт. Гарантированное время
    обновления: глобальное значение — немедленно (POST /api/config обновляет
    кэш), per-chat override — немедленно (NOTIFY `chat_params_updated`
    инвалидирует кэш) и не позднее TTL кэша chat_params (120 с) при потере
    NOTIFY.

    Возвращает `(burst_limit, cooldown_seconds, source)`, где `source` —
    `'chat'` | `'global'` | `'factory'` (при разных источниках двух ключей —
    `'<limit>/<cooldown>'`). Fail-open: ошибка резолва → settings-дефолты
    (`'factory'`) — троттлинг не роняет ход."""
    try:
        from services import chat_params as _chat_params
        limit, lsrc = await _chat_params.get_chat_param_sourced(
            chat_id, CHAT_BURST_LIMIT_KEY, settings.CHAT_BURST_LIMIT)
        cooldown, csrc = await _chat_params.get_chat_param_sourced(
            chat_id, CHAT_COOLDOWN_SECONDS_KEY, settings.CHAT_COOLDOWN_SECONDS)
    except Exception:
        logger.warning(
            "direct chat limits: resolve failed — settings defaults | chat=%s",
            chat_id, exc_info=True)
        limit, lsrc = settings.CHAT_BURST_LIMIT, "factory"
        cooldown, csrc = settings.CHAT_COOLDOWN_SECONDS, "factory"
    limit, cooldown = normalize_direct_chat_limits(limit, cooldown)
    source = lsrc if lsrc == csrc else f"{lsrc}/{csrc}"
    return limit, cooldown, source


def throttle_refresh(throttle, burst_limit: int,
                     cooldown_seconds: float) -> None:
    """CFG-01 (§01.2): применить effective-лимиты ПЕРЕД проверкой — прецедент
    `cooldown_refresh` (T-619/84.4), но и для ёмкости bucket'а.

    Политика состояния (документирована и покрыта тестами): смена лимита НЕ
    сбрасывает состояние слота — `last_ts` продолжает течь, накопленные заряды
    обрезаются до нового `burst_limit` (`min`/`LEAST`), поэтому уменьшение
    лимита не даёт «бонусных» обращений из старого запаса, а увеличение не
    выдаёт заряды до обычного полного восстановления. Инъектированные
    троттлеры без `refresh` (DI-двойники в тестах/внешние реализации) не
    ломаются."""
    refresh = getattr(throttle, "refresh", None)
    if refresh is None:
        return
    refresh(burst_limit, cooldown_seconds)


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


# ── CFG-02B (§02B.1–§02B.4, ADR-1031-1): частотный лимит генераций ─────────
# Тот же token bucket (`throttle_state`, scope='image_freq'), но лимиты —
# per (chat_id, user_id|0): режим `per_user` считает на участника, `per_chat` —
# один запас на чат (user_id=0). Семантика «подряд»:
#   * заряд списывается ПЕРЕД платной попыткой (перед вызовом генератора);
#   * полное восстановление — через `cooldown` секунд после ПОСЛЕДНЕГО
#     допущенного обращения (R50-7, общий ровно с Direct Chat-лимитом);
#   * состояние живёт в БД → переживает рестарт и делится между воркерами;
#   * смена лимитов не сбрасывает состояние (кламп зарядов в SQL, CFG-01);
#   * ошибка БД/нет runtime-db → fail-open (лимитер не роняет генерацию).
IMAGE_FREQ_SCOPE = "image_freq"
IMAGE_FREQ_ENABLED_KEY = "limits.image_freq_limit_enabled"
IMAGE_FREQ_BURST_KEY = "limits.image_freq_limit_burst"
IMAGE_FREQ_COOLDOWN_KEY = "limits.image_freq_limit_cooldown_seconds"
IMAGE_FREQ_MODE_KEY = "limits.image_freq_limit_mode"
IMAGE_FREQ_MODE_PER_USER = "per_user"
IMAGE_FREQ_MODE_PER_CHAT = "per_chat"

_IMAGE_FREQ_SNAPSHOT_SQL = (
    "SELECT burst_left, last_ts FROM throttle_state "
    "WHERE scope = ? AND chat_id = ? AND user_id = ?"
)


@dataclasses.dataclass(frozen=True)
class ImageFreqLimits:
    """Effective-конфиг частотного лимита (CFG-02B §02B.1/§02B.3)."""

    enabled: bool
    burst: int
    cooldown: float
    mode: str                 # per_user | per_chat
    source: str               # chat | global | default (источник тумблера)


@dataclasses.dataclass(frozen=True)
class ImageFreqSnapshot:
    """Read-only снимок серии: сколько зарядов осталось и сколько ждать."""

    charges_left: int
    remaining_seconds: float  # > 0 → пауза активна (генерация подождёт)


def normalize_image_freq_limits(burst, cooldown, mode
                                ) -> tuple[int, float, str]:
    """CFG-02B (§02B.2.1/§02B.2.2): единицы/границы новых ключей.

    * `burst` — ЦЕЛОЕ ≥ 1 («сколько генераций подряд»); мусор/≤0 → 1
      (вечного лока из-за нуля не возникает);
    * `cooldown` — СЕКУНДЫ ≥ 0; отрицательные/нечисловые/NaN → 0
      (0 = пауза не ограничивает);
    * `mode` — `per_user` | `per_chat`; любое иное значение → `per_user`
      (заводской выбор §02B.2.3, «Общий на весь чат» не подставляется молча).
    """
    burst_n, cooldown_n = normalize_direct_chat_limits(burst, cooldown)
    return burst_n, cooldown_n, _normalize_image_freq_mode(mode)


def _normalize_image_freq_mode(mode) -> str:
    value = str(mode or "").strip().lower()
    if value == IMAGE_FREQ_MODE_PER_CHAT:
        return IMAGE_FREQ_MODE_PER_CHAT
    return IMAGE_FREQ_MODE_PER_USER


def image_freq_bucket_user(mode: str, user_id: int | None) -> int:
    """Ключ счётчика `user_id` в throttle_state (CFG-02B §02B.3).

    `per_user` + известный участник → его id; `per_chat` → 0 (общий запас
    чата); `per_user` без участника (неизвестный requester) → 0 — общий
    запас чата, а НЕ новый «личный» счётчик (обхода нет §02B.4)."""
    if mode == IMAGE_FREQ_MODE_PER_USER and user_id is not None:
        try:
            return int(user_id)
        except (TypeError, ValueError):
            return 0
    return 0


async def resolve_image_freq_limits(chat_id: int | None) -> ImageFreqLimits:
    """CFG-02B (§02B.1/§02B.3): effective-конфиг частотного лимита.

    Порядок — существующий резолвер per-chat слоя (`worker_settings`):
    override чата → глобальный слой ConfigCache (hot-reload) → заводской
    дефолт. `source` — источник ТУМБЛЕРА (chat|global|default) для витрины
    «Лимиты генерации» (§02B.8). Fail-open: ошибка резолва → заводские
    значения (OFF) + WARNING — лимитер не роняет генерацию."""
    try:
        from services.worker_settings import resolve_setting_with_source
        enabled, enabled_src = await resolve_setting_with_source(
            IMAGE_FREQ_ENABLED_KEY, chat_id=chat_id,
            default=bool(getattr(settings, "IMAGE_FREQ_LIMIT_ENABLED", False)))
        burst, _ = await resolve_setting_with_source(
            IMAGE_FREQ_BURST_KEY, chat_id=chat_id,
            default=int(getattr(settings, "IMAGE_FREQ_LIMIT_BURST", 3)))
        cooldown, _ = await resolve_setting_with_source(
            IMAGE_FREQ_COOLDOWN_KEY, chat_id=chat_id,
            default=float(getattr(settings,
                                  "IMAGE_FREQ_LIMIT_COOLDOWN_SECONDS", 300.0)))
        mode, _ = await resolve_setting_with_source(
            IMAGE_FREQ_MODE_KEY, chat_id=chat_id,
            default=str(getattr(settings, "IMAGE_FREQ_LIMIT_MODE",
                                IMAGE_FREQ_MODE_PER_USER)))
    except Exception:
        logger.warning(
            "image freq: resolve failed — factory defaults (OFF) | chat=%s",
            chat_id, exc_info=True)
        enabled = bool(getattr(settings, "IMAGE_FREQ_LIMIT_ENABLED", False))
        burst = int(getattr(settings, "IMAGE_FREQ_LIMIT_BURST", 3))
        cooldown = float(getattr(settings,
                                 "IMAGE_FREQ_LIMIT_COOLDOWN_SECONDS", 300.0))
        mode = str(getattr(settings, "IMAGE_FREQ_LIMIT_MODE",
                           IMAGE_FREQ_MODE_PER_USER))
        enabled_src = "default"
    burst, cooldown, mode = normalize_image_freq_limits(burst, cooldown, mode)
    return ImageFreqLimits(enabled=bool(enabled), burst=burst,
                           cooldown=cooldown, mode=mode,
                           source=str(enabled_src or "default"))


def image_freq_db():
    """Runtime SQLite (`DatabaseService`) для `throttle_state` — тот же
    инстанс, что у Direct Chat: проводка `bot.py on_startup`
    (`set_lore_components(db=db)`), чтение через существующий публичный
    геттер `lore_runtime.get_lore_db()` (прецедент web-api). None → caller
    обязан fail-open (WARNING), лимитер не роняет генерацию."""
    try:
        from services import lore_runtime
        return lore_runtime.get_lore_db()
    except Exception:      # pragma: no cover - защитная ветка
        return None


async def image_freq_snapshot(chat_id: int, user_id: int | None, *,
                              limits: ImageFreqLimits | None = None
                              ) -> ImageFreqSnapshot:
    """Read-only снимок серии для честного отказа/витрины (§02B.6/§02B.8):
    остаток зарядов и активная пауза. Состояние НЕ меняется; fail-open →
    «полный запас, паузы нет» (лимитер не блокирует при недоступной БД)."""
    limits = limits or await resolve_image_freq_limits(chat_id)
    db = image_freq_db()
    if db is None:
        return ImageFreqSnapshot(charges_left=limits.burst,
                                 remaining_seconds=0.0)
    bucket = image_freq_bucket_user(limits.mode, user_id)
    try:
        cursor = await db.db.execute(_IMAGE_FREQ_SNAPSHOT_SQL,
                                     (IMAGE_FREQ_SCOPE, int(chat_id), bucket))
        row = await cursor.fetchone()
    except Exception:
        logger.warning("image freq: snapshot failed — fail-open | chat=%s",
                       chat_id, exc_info=True)
        return ImageFreqSnapshot(charges_left=limits.burst,
                                 remaining_seconds=0.0)
    if row is None:
        return ImageFreqSnapshot(charges_left=limits.burst,
                                 remaining_seconds=0.0)
    left = int(row["burst_left"] or 0)
    if left > 0:
        return ImageFreqSnapshot(charges_left=left, remaining_seconds=0.0)
    remaining = max(0.0, limits.cooldown - (time.time() - float(row["last_ts"])))
    return ImageFreqSnapshot(charges_left=0, remaining_seconds=remaining)


async def image_freq_allow(chat_id: int, user_id: int | None, *,
                           limits: ImageFreqLimits | None = None
                           ) -> tuple[bool, float]:
    """Атомарное списание заряда серии ПЕРЕД платной попыткой (§02B.4).

    Возвращает `(allowed, remaining_seconds)`: True — заряд списан (0.0);
    False — отказ, `remaining_seconds` = остаток паузы. Дебаунс/параллель
    закрыты одним UPSERT (тот же механизм, что у Direct Chat). Fail-open:
    нет runtime-db / ошибка БД → (True, 0.0) + WARNING."""
    limits = limits or await resolve_image_freq_limits(chat_id)
    db = image_freq_db()
    if db is None:
        logger.warning("image freq: runtime db отсутствует — fail-open "
                       "(без ограничения) | chat=%s", chat_id)
        return True, 0.0
    bucket = image_freq_bucket_user(limits.mode, user_id)
    throttle = PersistentThrottle(limits.burst, limits.cooldown,
                                  IMAGE_FREQ_SCOPE, db)
    remaining = await throttle.allow(int(chat_id), bucket)
    return (remaining <= 0.0), max(0.0, float(remaining))
