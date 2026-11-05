"""UNIFIED-REPLY UR-C-SCHED (arch contract §4): claim слотов расписания.

ОДИН механизм на оба вида расписания (``summary`` и ``goodmorning``),
никаких вторых планировщиков/агентов (UR-28, UR-BAN-06): существующий
глобальный тикер остаётся драйвером, а «per-chat» — это вычисление
локального слота каждого чата через ChatClock (services/chat_clock.py)
+ атомарная бронь слота перед запуском.

Математика слота (§4.3, UR-28.2):

* локальный слот ``HH:MM`` в IANA-поясе чата → детерминированный
  UTC-instant через ``zoneinfo`` (fold=0 — раннее появление);
* несуществующее локальное время (spring gap) → первый валидный instant
  ТОГО ЖЕ календарного дня (явный минуточный скан с roundtrip-проверкой,
  не ``replace(tzinfo=...)``);
* повторяющийся локальный час (fall fold) → один запуск на слот на
  раннем появлении.

Claim (§4.2): аддитивная таблица ``slot_claims`` (миграция v42; DDL —
здесь, владелец механизма), PK ``(kind, chat_id, local_date,
local_slot)``. ``INSERT OR IGNORE`` — атомарная бронь: ``rowcount == 1``
→ слот наш. Повторный тик, рестарт и конкурентный воркер дубль не
создают (SQLite WAL, каждый вызов — своё соединение; прецедент
``publication_coordination.SqliteClaimStore`` v41). ``slot_utc_instant``
и ``config_version`` — поля строки (диагностика/смена пояса), они НЕ
участвуют в уникальности: иначе fold-час и смена пояса давали бы
повторный запуск (§4.3: claim по local_date+slot).

Coalescing (§4.4, UR-28.3): слот запускается только в своём ограниченном
due-окне ``[slot_utc, slot_utc + due_window)``; просроченный — честный
skip (``fired=0``, ``reason_code='missed_slot_expired'``) ровно один раз;
слоты старше текущего не оцениваются — «пачка просроченных саммари»
невозможна, а уже покрытый период не пересказывается (окно саммари
считает генератор, как и прежде). Смена пояса (§4.5) пересчитывает
только будущие слоты: уже занятый слот остаётся занятым.

Хранение мгновений — epoch-секунды UTC (UR-24.4, история не меняется).
Наблюдаемость — только chat_id/коды/числа, без текстов чата (R17).
"""
from __future__ import annotations

import dataclasses
import datetime
import logging
import os
import sqlite3
import zoneinfo

logger = logging.getLogger(__name__)

#: Имя аддитивной таблицы (v42).
SLOT_CLAIMS_TABLE = "slot_claims"
#: Стабильное имя шага миграции (книга schema_migrations).
SLOT_CLAIMS_MIGRATION_STEP_NAME = "slot_claims_v42"

#: DDL владельца механизма — применяет миграция v42 (database.py) и тесты.
SLOT_CLAIMS_DDL_SQLITE = (
    f"CREATE TABLE IF NOT EXISTS {SLOT_CLAIMS_TABLE} ("
    "kind TEXT NOT NULL, "                 # 'summary' | 'goodmorning'
    "chat_id INTEGER NOT NULL, "
    "local_date TEXT NOT NULL, "           # ISO-дата в поясе чата
    "local_slot TEXT NOT NULL, "           # '00','06','12','18' | 'HH:MM'
    "slot_utc_instant INTEGER NOT NULL, "  # детерминированный UTC instant (epoch s)
    "config_version TEXT NOT NULL DEFAULT '', "
    "claimed_at INTEGER NOT NULL, "
    "fired INTEGER NOT NULL DEFAULT 1, "   # 1 = запуск; 0 = честный skip
    "reason_code TEXT NOT NULL DEFAULT '', "
    "PRIMARY KEY (kind, chat_id, local_date, local_slot)",
)
_SLOT_CLAIMS_INDEX_DDL = (
    f"CREATE INDEX IF NOT EXISTS idx_slot_claims_chat "
    f"ON {SLOT_CLAIMS_TABLE} (kind, chat_id, local_date)",
)

_INSERT_CLAIM_SQL = (
    f"INSERT OR IGNORE INTO {SLOT_CLAIMS_TABLE} "
    "(kind, chat_id, local_date, local_slot, slot_utc_instant, "
    " config_version, claimed_at, fired, reason_code) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

#: Due-окно summary (с): слот запускается, пока now внутри окна от его
#: instant. Семантика прежнего cron (coalesce/misfire → просроченный слот
#: не запускается) + bounded catch-up короткого простоя.
SUMMARY_DUE_WINDOW_SECONDS = 120
#: Due-окно goodmorning (с): то же для утренней рассылки (GOODMORNING_TIME
#: — час рассылки; дедуп «одно утро в день на чат» сохраняется).
GOODMORNING_DUE_WINDOW_SECONDS = 120

_EXPIRED_REASON = "missed_slot_expired"

# ── чистая математика локальных слотов (DST/fold) ──────────────────────────


@dataclasses.dataclass(frozen=True)
class SlotRef:
    """Слот локальной шкалы чата (диагностика + решение тика).

    ``local_date``/``label`` — ключ claim; ``slot_utc`` — детерминированный
    UTC-instant (gap → первый валидный день, fold → раннее появление);
    ``next_utc`` — конец периода (инстант следующего слота шкалы);
    ``mode`` — normal | gap_shifted | fold_earlier."""

    local_date: datetime.date
    label: str
    slot_utc: datetime.datetime
    next_utc: datetime.datetime
    mode: str


def slot_instant_for(local_date: datetime.date, hour: int, minute: int,
                     tz) -> tuple[datetime.datetime, str]:
    """UTC-instant локального ``HH:MM`` на дату в поясе + режим.

    Возвращает ``(aware_utc_datetime, mode)``. Несуществующее локальное
    время (gap) → первый валидный instant того же календарного дня
    (``mode='gap_shifted'``); повторяющееся (fold) → раннее появление
    (``mode='fold_earlier'``). ``tz`` может быть фиксированным offset
    (UTC-деградация ChatClock) — тогда gap/fold невозможны."""

    def _instant(naive: datetime.datetime, fold: int) -> datetime.datetime:
        return naive.replace(tzinfo=tz, fold=fold).astimezone(
            datetime.timezone.utc)

    naive = datetime.datetime.combine(local_date, datetime.time(hour, minute))
    direct = _instant(naive, 0)
    if direct.astimezone(tz).replace(tzinfo=None) == naive:
        # Валидное время; fold=0 уже даёт раннее появление.
        if _instant(naive, 1) != direct:
            return direct, "fold_earlier"
        return direct, "normal"
    # Spring gap: первый валидный instant ТОГО ЖЕ календарного дня.
    probe = naive + datetime.timedelta(minutes=1)
    day_end = datetime.datetime.combine(
        local_date + datetime.timedelta(days=1), datetime.time(0, 0))
    while probe < day_end:
        cand = _instant(probe, 0)
        if cand.astimezone(tz).replace(tzinfo=None) == probe:
            return cand, "gap_shifted"
        probe += datetime.timedelta(minutes=1)
    # Патология пояса (нет валидного времени до конца дня) — честный
    # fallback: первый валидный instant следующего дня (логирует вызывающий
    # resolve; здесь без логгера — чистая функция).
    probe = day_end
    for _ in range(24 * 60):
        cand = _instant(probe, 0)
        if cand.astimezone(tz).replace(tzinfo=None) == probe:
            return cand, "gap_shifted"
        probe += datetime.timedelta(minutes=1)
    # Дошли сюда только при полностью сломанном tz — фиксированный UTC.
    return naive.replace(
        tzinfo=datetime.timezone.utc), "gap_shifted"


def _slots_for_date(day: datetime.date, slot_seq, tz) -> list[SlotRef]:
    refs: list[SlotRef] = []
    for index, (hour, minute) in enumerate(slot_seq):
        instant, mode = slot_instant_for(day, hour, minute, tz)
        nxt_hour, nxt_minute = slot_seq[(index + 1) % len(slot_seq)]
        nxt_day = day if index + 1 < len(slot_seq) else \
            day + datetime.timedelta(days=1)
        next_instant, _ = slot_instant_for(nxt_day, nxt_hour, nxt_minute, tz)
        refs.append(SlotRef(
            local_date=day,
            label="%02d:%02d" % (hour, minute),
            slot_utc=instant,
            next_utc=next_instant,
            mode=mode,
        ))
    return refs


def latest_slot(now_utc: datetime.datetime, tz, slot_seq) -> SlotRef | None:
    """Самый свежий слот локальной шкалы с ``slot_utc <= now``.

    Периоды непрерывны: до первого слота даты это последний слот
    предыдущего дня. ``slot_seq`` — возрастающая последовательность
    ``(hour, minute)`` одного дня. ``None`` — только для вырожденной
    пустой шкалы."""

    def _ordered(refs: list[SlotRef]) -> list[SlotRef]:
        return sorted(refs, key=lambda r: r.slot_utc)

    local_now = now_utc.astimezone(tz)
    day = local_now.date()
    today = _ordered(_slots_for_date(day, slot_seq, tz))
    prev_day_last = _slots_for_date(
        day - datetime.timedelta(days=1), slot_seq[-1:], tz)[0]
    if local_now < today[0].slot_utc.astimezone(tz):
        return prev_day_last
    chosen: SlotRef | None = None
    for ref in today:
        if ref.slot_utc <= now_utc:
            chosen = ref
    if chosen is not None:
        return chosen
    return prev_day_last


def in_due_window(now_utc: datetime.datetime, slot: SlotRef,
                  due_window_s: float) -> bool:
    """Слот ещё «актуален»: now внутри ``[slot_utc, slot_utc + window)``."""
    window = datetime.timedelta(seconds=max(0, float(due_window_s)))
    return slot.slot_utc <= now_utc < slot.slot_utc + window


# ── атомарный claim (SQLite, файл БД; каждый вызов — своё соединение) ──────


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5, isolation_level=None,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


class SqliteSlotClaimStore:
    """Файловая бронь слотов (v42). Один стейтмент на решение.

    Прецедент ``publication_coordination.SqliteClaimStore`` (v41):
    ``INSERT OR IGNORE`` по PK отдаёт слот ровно одному участнику —
    N воркеров/N процессов видят ровно один результат, без in-process
    блокировок и без ``BEGIN IMMEDIATE`` вокруг операции."""

    def __init__(self, path: str) -> None:
        self.path = str(path)

    def apply_schema(self) -> None:
        """Применить DDL (миграция v42 и тесты; горячий путь не зовёт)."""
        conn = _connect(self.path)
        try:
            for statement in SLOT_CLAIMS_DDL_SQLITE:
                conn.execute(statement)
            for statement in _SLOT_CLAIMS_INDEX_DDL:
                conn.execute(statement)
        finally:
            conn.close()

    def table_present(self) -> bool:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (SLOT_CLAIMS_TABLE,)).fetchone()
            return row is not None
        except Exception:
            return False
        finally:
            conn.close()

    def lookup(self, *, kind: str, chat_id: int, local_date: str,
               local_slot: str) -> dict | None:
        """Строка брони слота (read-only; нет строки → None)."""
        conn = _connect(self.path)
        try:
            row = conn.execute(
                f"SELECT * FROM {SLOT_CLAIMS_TABLE} "
                "WHERE kind=? AND chat_id=? AND local_date=? AND "
                "local_slot=?",
                (str(kind), int(chat_id), str(local_date), str(local_slot)),
            ).fetchone()
            return dict(row) if row is not None else None
        except Exception:
            return None
        finally:
            conn.close()

    def try_claim(self, *, kind: str, chat_id: int, local_date: str,
                  local_slot: str, slot_utc_instant: int,
                  config_version: str, claimed_at: int, fired: bool = True,
                  reason_code: str = "") -> bool:
        """Атомарная бронь слота. ``True`` — слот наш (rowcount == 1)."""
        conn = _connect(self.path)
        try:
            cursor = conn.execute(_INSERT_CLAIM_SQL, (
                str(kind), int(chat_id), str(local_date), str(local_slot),
                int(slot_utc_instant), str(config_version or ""),
                int(claimed_at), 1 if fired else 0, str(reason_code or ""),
            ))
            return int(cursor.rowcount or 0) == 1
        finally:
            conn.close()


def slot_claim_store_of(db) -> SqliteSlotClaimStore | None:
    """Store по файлу БД владельца; пути нет → None (деградация).

    Строгая типизация пути (str/os.PathLike): тест-двойники с MagicMock
    атрибутами честно дают «пути нет», а не файл-мусор рядом с репо."""
    path = getattr(db, "db_path", None) or getattr(db, "path", None)
    if not path:
        raw = getattr(db, "db", None)
        path = getattr(raw, "path", None) if raw is not None else None
    if not isinstance(path, (str, os.PathLike)):
        return None
    text = os.fspath(path)
    if not text or text == ":memory:":
        return None
    return SqliteSlotClaimStore(text)


# ── деградация без таблицы: fail-open с in-process дедупом (R17-лог) ───────

_MEM_CLAIMS: set[tuple] = set()
_DEGRADED_WARNED: set[str] = set()


def reset_in_memory_claims() -> None:
    """Сброс process-local дедупа деградации (тесты/диагностика)."""
    _MEM_CLAIMS.clear()


def _mem_claim(kind: str, chat_id: int, local_date: str,
               local_slot: str) -> bool:
    key = (str(kind), int(chat_id), str(local_date), str(local_slot))
    if key in _MEM_CLAIMS:
        return False
    if len(_MEM_CLAIMS) > 100_000:      # bounded: чистим целиком (без порядка)
        _MEM_CLAIMS.clear()
    _MEM_CLAIMS.add(key)
    return True


def warn_degraded_once(kind: str) -> None:
    """Один WARN на процесс на kind: бронь недоступна → дедуп не
    гарантируется (честная деградация, не тихий пропуск)."""
    if kind in _DEGRADED_WARNED:
        return
    _DEGRADED_WARNED.add(kind)
    logger.warning(
        "[slot_claims] claim-store недоступен (kind=%s) — degraded "
        "fail-open: in-process дедуп слотов, кросс-рестарт дедуп не "
        "гарантируется", kind)


# ── решение тика: один вход для обоих планировщиков ────────────────────────

#: Действие вердикта: 'fire' — claim выигран, запускай; 'skip_busy' — слот
#: уже занят (тиком ранее/рестартом/конкурентом); 'skip_expired' — окно
#: прошло, честный skip зафиксирован; 'skip_quiet' — уже зафиксирован
#: ранее; 'skip_degraded' — окно прошло, брони нет; 'future' — до слота.
ACTION_FIRE = "fire"
ACTION_SKIP_BUSY = "skip_busy"
ACTION_SKIP_EXPIRED = "skip_expired"
ACTION_SKIP_QUIET = "skip_quiet"
ACTION_SKIP_DEGRADED = "skip_degraded"
ACTION_FUTURE = "future"


@dataclasses.dataclass(frozen=True)
class SlotVerdict:
    """Решение тика по одному чату (наблюдаемость без текстов чата)."""

    action: str
    slot: SlotRef | None
    iana: str = ""
    tz_source: str = ""
    config_version: str = ""
    claim_granted: bool = False


async def resolve_chat_zone(chat_id) -> tuple[object, str, str, str]:
    """(tz, iana, source, config_version) — ЕДИНСТВЕННЫЙ резолвер проекта.

    Переиспользует ``chat_clock.resolve_chat_timezone`` (UR-24.3); второй
    цепочки не создаёт. Невалидная зона/сбой → честный UTC-fallback
    (UR-24.4). Никогда не бросает."""
    try:
        from services.chat_clock import resolve_chat_timezone
        iana, source, cv = await resolve_chat_timezone(chat_id)
        try:
            return zoneinfo.ZoneInfo(iana), iana, source, cv
        except (zoneinfo.ZoneInfoNotFoundError, ValueError, FileNotFoundError,
                KeyError, OSError):
            logger.error(
                "[slot_claims] tzdata unavailable for %r — UTC fallback | "
                "chat=%s", iana, chat_id)
            return datetime.timezone.utc, "UTC", "utc_fallback", cv
    except Exception:      # pragma: no cover - fail-open
        return datetime.timezone.utc, "UTC", "utc_fallback", ""


def _ensure_utc(moment: datetime.datetime) -> datetime.datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=datetime.timezone.utc)
    return moment.astimezone(datetime.timezone.utc)


async def claim_slot_if_due(*, kind: str, db, chat_id, now_utc,
                            slot_seq, due_window_s: float) -> SlotVerdict:
    """ОДНА точка решения слота (arch contract §4.2–4.5).

    Порядок тика на чат: резолв пояса через ChatClock → слот шкалы →
    due-окно → атомарный claim (файл БД) → вердикт. Просроченный слот
    фиксируется честным skip (``fired=0``, ``reason_code=
    'missed_slot_expired'``) ровно один раз. Наблюдаемость решения —
    здесь (chat_id/пояс/источник/слот/instant/config, без текстов).
    Никогда не бросает: сбой claim → degraded fail-open c in-process
    дедупом."""
    try:
        tz, iana, tz_source, cv = await resolve_chat_zone(chat_id)
        now = _ensure_utc(now_utc)
        slot = latest_slot(now, tz, tuple(slot_seq))
        if slot is None:
            return SlotVerdict(ACTION_FUTURE, None, iana, tz_source, cv)
        store = slot_claim_store_of(db)
        if store is None:
            warn_degraded_once(str(kind))
            if in_due_window(now, slot, due_window_s):
                granted = _mem_claim(kind, chat_id, slot.local_date.isoformat(),
                                     slot.label)
                if granted:
                    _log_decision(kind, chat_id, slot, iana, tz_source, cv,
                                  "fire", degraded=True)
                    return SlotVerdict(ACTION_FIRE, slot, iana, tz_source,
                                       cv, granted=True)
                return SlotVerdict(ACTION_SKIP_BUSY, slot, iana, tz_source, cv)
            return SlotVerdict(ACTION_SKIP_DEGRADED, slot, iana, tz_source, cv)
        now_ts = int(now.timestamp())
        if in_due_window(now, slot, due_window_s):
            try:
                granted = store.try_claim(
                    kind=kind, chat_id=chat_id,
                    local_date=slot.local_date.isoformat(),
                    local_slot=slot.label,
                    slot_utc_instant=int(slot.slot_utc.timestamp()),
                    config_version=cv, claimed_at=now_ts, fired=True)
            except Exception as exc:
                logger.warning(
                    "[slot_claims] claim failed (kind=%s chat=%s) — "
                    "degraded fail-open", kind, chat_id, exc_info=exc)
                granted = _mem_claim(kind, chat_id,
                                     slot.local_date.isoformat(), slot.label)
                if granted:
                    _log_decision(kind, chat_id, slot, iana, tz_source, cv,
                                  "fire", degraded=True)
                    return SlotVerdict(ACTION_FIRE, slot, iana, tz_source,
                                       cv, granted=True)
                return SlotVerdict(ACTION_SKIP_BUSY, slot, iana, tz_source, cv)
            if granted:
                _log_decision(kind, chat_id, slot, iana, tz_source, cv, "fire")
                return SlotVerdict(ACTION_FIRE, slot, iana, tz_source, cv,
                                   granted=True)
            return SlotVerdict(ACTION_SKIP_BUSY, slot, iana, tz_source, cv)
        # Окно прошло: честный skip ровно один раз (fired=0).
        try:
            marked = store.try_claim(
                kind=kind, chat_id=chat_id,
                local_date=slot.local_date.isoformat(),
                local_slot=slot.label,
                slot_utc_instant=int(slot.slot_utc.timestamp()),
                config_version=cv, claimed_at=now_ts, fired=False,
                reason_code=_EXPIRED_REASON)
        except Exception:
            return SlotVerdict(ACTION_SKIP_DEGRADED, slot, iana, tz_source, cv)
        if marked:
            _log_decision(kind, chat_id, slot, iana, tz_source, cv,
                          "skip_expired")
            return SlotVerdict(ACTION_SKIP_EXPIRED, slot, iana, tz_source, cv)
        return SlotVerdict(ACTION_SKIP_QUIET, slot, iana, tz_source, cv)
    except Exception:      # pragma: no cover - защитная ветка тика
        logger.exception("[slot_claims] slot evaluation failed | kind=%s "
                         "| chat=%s", kind, chat_id)
        return SlotVerdict(ACTION_SKIP_DEGRADED, None)


def _log_decision(kind: str, chat_id, slot: SlotRef, iana: str,
                  tz_source: str, cv: str, action: str, *,
                  degraded: bool = False) -> None:
    """Наблюдаемость решения слота: chat_id/пояс/источник/слот/instant —
    без текстов чата (R17). Level: fire → INFO, skip_expired → INFO."""
    try:
        offset = slot.slot_utc.astimezone(
            slot.slot_utc.tzinfo or datetime.timezone.utc)
        local = offset.astimezone(zoneinfo.ZoneInfo(iana)) if iana else offset
        logger.info(
            "[sched_slot] kind=%s | chat_id=%s | tz=%s | tz_source=%s | "
            "local_date=%s | slot=%s | local=%s | slot_utc=%s | mode=%s | "
            "config=%s | action=%s%s",
            kind, chat_id, iana, tz_source, slot.local_date.isoformat(),
            slot.label, local.strftime("%H:%M %d.%m.%Y"),
            slot.slot_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), slot.mode, cv,
            action, " | degraded=true" if degraded else "")
    except Exception:      # pragma: no cover - наблюдаемость не рвёт тик
        logger.info(
            "[sched_slot] kind=%s | chat_id=%s | slot=%s | action=%s",
            kind, chat_id,
            getattr(slot, "label", "?"), action)


async def next_due_utc(chat_id, slot_seq, *,
                       now_utc: datetime.datetime | None = None
                       ) -> datetime.datetime | None:
    """Ближайший БУДУЩИЙ instant слота чата (для UI «Следующий запуск»,
    UR-28.4/UR-29; сам планировщик его не требует). Никогда не бросает."""
    try:
        tz, _iana, _src, _cv = await resolve_chat_zone(chat_id)
        now = _ensure_utc(now_utc or datetime.datetime.now(
            datetime.timezone.utc))
        day = now.astimezone(tz).date()
        for offset_days in (0, 1, 2):
            for ref in sorted(_slots_for_date(
                    day + datetime.timedelta(days=offset_days), slot_seq, tz),
                    key=lambda r: r.slot_utc):
                if ref.slot_utc > now:
                    return ref.slot_utc
        return None
    except Exception:      # pragma: no cover - fail-open
        return None


__all__ = [
    "SLOT_CLAIMS_TABLE",
    "SLOT_CLAIMS_MIGRATION_STEP_NAME",
    "SLOT_CLAIMS_DDL_SQLITE",
    "SUMMARY_DUE_WINDOW_SECONDS",
    "GOODMORNING_DUE_WINDOW_SECONDS",
    "SlotRef",
    "SlotVerdict",
    "SqliteSlotClaimStore",
    "slot_claim_store_of",
    "slot_instant_for",
    "latest_slot",
    "in_due_window",
    "resolve_chat_zone",
    "claim_slot_if_due",
    "next_due_utc",
    "reset_in_memory_claims",
    "warn_degraded_once",
    "ACTION_FIRE", "ACTION_SKIP_BUSY", "ACTION_SKIP_EXPIRED",
    "ACTION_SKIP_QUIET", "ACTION_SKIP_DEGRADED", "ACTION_FUTURE",
]
