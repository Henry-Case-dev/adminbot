"""MEME-PIPELINE-REFactor-01 / INIT-COORD — координация публикаций двух
независимых механизмов одного модуля (инициативы).

Задача (дополнение владельца 03.11.2026, `arch/initiative-coordination.md` §3):
планирование текстовой инициативы и мемов НЕЗАВИСИМО, но публикации в один
чат не должны сталкиваться. Оба механизма обязаны перед фактической отправкой
учитывать недавние публикации бота в ЭТОМ чате.

Два уровня, их нельзя путать:

* **pre-check** (`precheck`) — дешёвая ПРОВЕРКА, которая ОБЪЯСНЯЕТ: читает
  существующий журнал выводов (`mca_bot_outputs`, kind ∈
  :data:`PUBLICATION_KINDS`) и строку брони, ничего не пишет. Вызывается до
  дорогой генерации.
* **claim** (`acquire` / `begin_sending` / `release`) — атомарное РЕШЕНИЕ перед
  отправкой. Один `UPSERT` по PK `chat_id` в аддитивной таблице
  :data:`CLAIM_TABLE` (v41): compare-and-set отдаёт бронь ровно одному
  участнику, включая N воркеров и N процессов на одной SQLite-базе.

Инварианты (не менять без решения Архитектора):

* никакого глобального `asyncio.Lock` на все чаты — атомарность даёт сам
  стейтмент SQLite (WAL); блокировка процесса не работает между воркерами и
  рестартами;
* никакого нового планировщика/воркера/очереди: бронь живёт только как
  предусловие существующей отправки;
* «ok» — это не «разрешено вообще», а «разрешено до следующей проверки»:
  отправлять можно ТОЛЬКО после успешного `claimed → sending`;
* межтиповой интервал ограничивает ТОЛЬКО пару разных типов публикаций и не
  заменяет собственные кулдауны/расписания/квоты механизмов: действующий
  зазор = ``max(свой кулдаун, интервал)`` (:func:`resolve_gap_seconds`);
* деградация без таблицы не выключает молча основной механизм текстовой
  инициативы (``coordination="degraded"`` + один WARN), но мем остаётся на
  своём честном ``schema_absent``;
* порядок ``precheck → acquire → publish_guard → release`` ОДИН у всех
  sender'ов текста инициативы: наблюдатель-повод, heartbeat-намерение,
  делегированный кандидат nostalgia, legacy-отправка nostalgia и реальный
  прогон админской диагностики. Новая точка отправки без ``publish_guard``
  запрещена структурной проверкой `tests/test_initiative_coordination.py`
  (:class:`TextPublication` — общий шов).

Состояние отправки живёт в операционной SQLite рядом с `mca_bot_outputs`;
PG-копии нет (бронь — не долговременное знание, а 90–120-секундная аренда).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── kinds публикаций ────────────────────────────────────────────────────────
#: Текстовая инициатива (`direct_chat_service.handle_initiative`).
KIND_TEXT_INITIATIVE = "initiative_reply"
#: Инициативный мем (`meme_initiative.OUTPUT_KIND`).
KIND_MEME_INITIATIVE = "meme_initiative"
#: Пары, между которыми действует межтиповой интервал. Оба kind пишутся в
#: СУЩЕСТВУЮЩИЙ журнал выводов (`mca_bot_outputs`): отдельного реестра нет.
PUBLICATION_KINDS: tuple[str, ...] = (KIND_TEXT_INITIATIVE, KIND_MEME_INITIATIVE)

# ── схема v41 (аддитивная таблица, одна строка на чат) ──────────────────────
CLAIM_TABLE = "chat_publish_claim"
CLAIM_SCHEMA_VERSION = 41
CLAIM_MIGRATION_STEP_NAME = "chat_publish_claim_v41"

#: TTL брони до перехода в отправку (аренда «я печатаю/генерирую»).
CLAIM_TTL_SECONDS = 90
#: TTL после перехода в `sending` (отправка в процессе/упала в полёте).
SENDING_TTL_SECONDS = 120
#: Сколько живёт приоритет ручного `/meme` (срок жизни брони, не пауза).
MANUAL_PRIORITY_SECONDS = 600

#: Ключ межтипового интервала. Дефолт — СУЩЕСТВУЮЩАЯ константа инициативы
#: (`initiative_observer.MIN_GAP_FLOOR_SECONDS`), нового числа не вводим.
KEY_CROSS_TYPE_INTERVAL = "initiative.cross_type_publication_interval_seconds"

STATES = ("claimed", "sending", "released", "cancelled")

# ── коды причины («объяснил») и detail («где именно») ───────────────────────
REASON_CONFLICT = "publication_conflict"
REASON_IN_FLIGHT = "publication_in_flight"
REASON_EXPIRED = "publication_expired"
REASON_SENT = "sent"
REASON_NONE = ""
#: detail для pre-check/claim: что именно не совпало.
DETAIL_CROSS_TYPE = "cross_type_interval"
DETAIL_CLAIM_HELD = "claim_held"
DETAIL_MANUAL_PRIORITY = "manual_priority"
#: detail для восстановленной после рестарта отправки (могла уехать или нет).
DETAIL_DELIVERY_UNKNOWN = "delivery_unknown"

#: Состояние координации (честная метка, а не «тишина»).
COORDINATION_OK = "ok"
COORDINATION_DEGRADED = "degraded"

CLAIM_DDL_SQLITE = (
    f"CREATE TABLE IF NOT EXISTS {CLAIM_TABLE} ("
    "chat_id INTEGER PRIMARY KEY,"
    "claim_id TEXT NOT NULL,"
    "holder_kind TEXT NOT NULL,"
    "holder_ref TEXT NOT NULL DEFAULT '',"
    "state TEXT NOT NULL,"
    "claimed_at INTEGER NOT NULL,"
    "expires_at INTEGER,"
    "last_publish_ts INTEGER,"
    "last_publish_kind TEXT NOT NULL DEFAULT '',"
    "last_publish_ref TEXT NOT NULL DEFAULT '',"
    "manual_priority_until INTEGER,"
    "updated_at INTEGER NOT NULL)",
)

#: Справочный DDL для PostgreSQL — НЕ зарегистрирован и НЕ применяется:
#: состояние отправки живёт в операционной SQLite (PG-копия не читается никем
#: и выдавала бы несуществующую поддержку). Форма оставлена как контракт.
CLAIM_DDL_POSTGRES = (
    f"CREATE TABLE IF NOT EXISTS {CLAIM_TABLE} ("
    "chat_id BIGINT PRIMARY KEY,"
    "claim_id TEXT NOT NULL,"
    "holder_kind TEXT NOT NULL,"
    "holder_ref TEXT NOT NULL DEFAULT '',"
    "state TEXT NOT NULL,"
    "claimed_at BIGINT NOT NULL,"
    "expires_at BIGINT,"
    "last_publish_ts BIGINT,"
    "last_publish_kind TEXT NOT NULL DEFAULT '',"
    "last_publish_ref TEXT NOT NULL DEFAULT '',"
    "manual_priority_until BIGINT,"
    "updated_at BIGINT NOT NULL)",
)

#: Один стейтмент = атомарное решение (§3.3). `rowcount == 1` → бронь выдана,
#: `0` → проигравший. Семантика (дословно из решения Архитектора):
#:   * строка свободна (`released`/`cancelled`) ИЛИ аренда истекла
#:     (`expires_at <= now`) ИЛИ ручной запрос забирает чужой `claimed`;
#:   * чужой приоритет ручного `/meme` блокирует автоматический путь;
#:   * межтиповой интервал считается от последней публикации ДРУГОГО типа —
#:     и по журналу выводов (`:other_ts`, читается до стейтмента), и по
#:     собственному watermark строки (`last_publish_kind/last_publish_ts`,
#:     читается ВНУТРИ стейтмента, поэтому гонка send→claim не проходит);
#:   * бронь, оставленная в `sending` с истёкшим TTL (рестарт/обрыв),
#:     переоценивается как состоявшаяся публикация (`delivery_unknown`):
#:     повторной автоматической отправки того же окна не будет.
_ACQUIRE_SQL = f"""
INSERT INTO {CLAIM_TABLE} (
    chat_id, claim_id, holder_kind, holder_ref, state, claimed_at,
    expires_at, last_publish_ts, last_publish_kind, last_publish_ref,
    manual_priority_until, updated_at)
VALUES (:chat, :cid, :kind, :ref, 'claimed', :now, :exp, NULL, '', '', NULL, :now)
ON CONFLICT(chat_id) DO UPDATE SET
    claim_id = excluded.claim_id,
    holder_kind = excluded.holder_kind,
    holder_ref = excluded.holder_ref,
    state = 'claimed',
    claimed_at = excluded.claimed_at,
    expires_at = excluded.expires_at,
    updated_at = excluded.updated_at,
    last_publish_ts = CASE
        WHEN {CLAIM_TABLE}.state = 'sending'
         AND {CLAIM_TABLE}.expires_at IS NOT NULL
         AND {CLAIM_TABLE}.expires_at <= :now
        THEN COALESCE({CLAIM_TABLE}.last_publish_ts,
                      {CLAIM_TABLE}.claimed_at)
        ELSE {CLAIM_TABLE}.last_publish_ts END,
    last_publish_kind = CASE
        WHEN {CLAIM_TABLE}.state = 'sending'
         AND {CLAIM_TABLE}.expires_at IS NOT NULL
         AND {CLAIM_TABLE}.expires_at <= :now
         AND COALESCE({CLAIM_TABLE}.last_publish_ts, 0) = 0
        THEN {CLAIM_TABLE}.holder_kind
        ELSE {CLAIM_TABLE}.last_publish_kind END
WHERE ({CLAIM_TABLE}.state IN ('released', 'cancelled')
       OR ({CLAIM_TABLE}.expires_at IS NOT NULL
           AND {CLAIM_TABLE}.expires_at <= :now)
       OR (:manual = 1 AND {CLAIM_TABLE}.state = 'claimed'))
  AND (:manual = 1 OR {CLAIM_TABLE}.manual_priority_until IS NULL
       OR {CLAIM_TABLE}.manual_priority_until <= :now)
  AND (:manual = 1 OR :interval <= 0
       OR ((:other_ts IS NULL OR :now - :other_ts >= :interval)
           AND ({CLAIM_TABLE}.last_publish_kind = :kind
                OR {CLAIM_TABLE}.last_publish_kind = ''
                OR {CLAIM_TABLE}.last_publish_ts IS NULL
                OR :now - {CLAIM_TABLE}.last_publish_ts >= :interval)))
"""

#: `claimed → sending`: единственное разрешение звать sender.
_BEGIN_SENDING_SQL = f"""
UPDATE {CLAIM_TABLE}
   SET state = 'sending', expires_at = :exp, updated_at = :now
 WHERE chat_id = :chat AND claim_id = :cid AND state = 'claimed'
   AND expires_at IS NOT NULL AND expires_at > :now
   AND (:manual = 1 OR manual_priority_until IS NULL
        OR manual_priority_until <= :now)
"""

_RELEASE_SQL = f"""
UPDATE {CLAIM_TABLE}
   SET state = 'released',
       expires_at = NULL,
       last_publish_ts = CASE WHEN :published = 1 THEN :now
                              ELSE last_publish_ts END,
       last_publish_kind = CASE WHEN :published = 1 THEN :kind
                                ELSE last_publish_kind END,
       last_publish_ref = CASE WHEN :published = 1 THEN :ref
                               ELSE last_publish_ref END,
       updated_at = :now
 WHERE chat_id = :chat AND claim_id = :cid
"""

_MANUAL_PRIORITY_SQL = f"""
INSERT INTO {CLAIM_TABLE} (
    chat_id, claim_id, holder_kind, holder_ref, state, claimed_at,
    expires_at, last_publish_ts, last_publish_kind, last_publish_ref,
    manual_priority_until, updated_at)
VALUES (:chat, '', 'manual', '', 'cancelled', :now, NULL, NULL, '', '', :until,
        :now)
ON CONFLICT(chat_id) DO UPDATE SET
    manual_priority_until = :until, updated_at = :now
"""

#: Освобождение брони по in-process событию (ручной `/meme`): событие
#: взводится при release/cancel ЗАДЕРЖАВШЕЙ брони в этом процессе. Это не
#: глобальная блокировка: ожидание ограничено по времени и только для
#: ручного приоритетного запроса.
_RELEASE_EVENTS: dict[int, asyncio.Event] = {}

#: Предел ожидания чужой отправки ручным запросом (с).
MANUAL_IN_FLIGHT_WAIT_SECONDS = 20


def now_ts() -> int:
    """Текущее время (инъекция времени в тестах идёт через ``now=``)."""
    return int(time.time())


def sqlite_path_of(db) -> str | None:
    """Путь файла SQLite у DatabaseService или соединения. Нет пути → None.

    Та же конвенция, что у журнала квоты мемов: координация работает по файлу
    БД, а не по соединению процесса.
    """
    path = getattr(db, "db_path", None) or getattr(db, "path", None)
    if not path:
        raw = getattr(db, "db", None)
        path = getattr(raw, "path", None) if raw is not None else None
    if not path:
        return None
    text = str(path)
    if text in ("", ":memory:"):
        return None
    return text


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5, isolation_level=None,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _release_event(chat_id: int) -> asyncio.Event:
    event = _RELEASE_EVENTS.get(int(chat_id))
    if event is None:
        event = asyncio.Event()
        _RELEASE_EVENTS[int(chat_id)] = event
    return event


def reset_release_events() -> None:
    """Сброс in-process событий освобождения брони (тесты)."""
    _RELEASE_EVENTS.clear()


@dataclass(frozen=True)
class ClaimDecision:
    """Решение по брони. ``granted`` — можно идти к отправке (§3.3).

    ``reason`` — код для пользователя/журнала, ``detail`` — где именно
    столкнулись; ``coordination`` честно говорит, участвовала ли таблица.
    """

    granted: bool
    reason: str = REASON_NONE
    detail: str = ""
    claim_id: str = ""
    state: str = ""
    holder_kind: str = ""
    holder_ref: str = ""
    interval_seconds: int = 0
    other_kind: str = ""
    other_age_seconds: int | None = None
    manual_priority_until: int | None = None
    coordination: str = COORDINATION_OK
    expires_at: int | None = None
    recovered_delivery_unknown: bool = False

    def as_dict(self) -> dict:
        return {
            "granted": bool(self.granted),
            "reason": self.reason,
            "detail": self.detail,
            "claim_id": self.claim_id,
            "state": self.state,
            "holder_kind": self.holder_kind,
            "holder_ref": self.holder_ref,
            "interval_seconds": int(self.interval_seconds),
            "other_kind": self.other_kind,
            "other_age_seconds": self.other_age_seconds,
            "manual_priority_until": self.manual_priority_until,
            "coordination": self.coordination,
            "expires_at": self.expires_at,
            "recovered_delivery_unknown": bool(self.recovered_delivery_unknown),
        }


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _expired(expires_at, now: int) -> bool:
    """Истекла ли аренда брони (``None``/мусор = истекла: срока нет — нет и
    эксклюзивности)."""
    try:
        value = int(expires_at)
    except (TypeError, ValueError):
        return True
    return value <= int(now)


async def _param(chat_id: int | None, key: str, default):
    """Generic-резолв настройки (override чата → hot → дефолт)."""
    try:
        if chat_id is not None:
            from services import chat_params
            value = await chat_params.get_chat_param(int(chat_id), key, default)
            if value is not None:
                return value
        from services import hot_config as hot
        value = hot.get(key, default)
        return default if value is None else value
    except Exception:
        return default


def default_interval_seconds() -> int:
    """Дефолт межтипового интервала = существующая ``MIN_GAP_FLOOR_SECONDS``."""
    try:
        from services.initiative_observer import MIN_GAP_FLOOR_SECONDS
        return int(MIN_GAP_FLOOR_SECONDS)
    except Exception:
        return 1800


async def resolve_cross_type_interval(chat_id: int | None) -> int:
    """Межтиповой интервал чата (с). ``0`` — координация по интервалу выкл.

    Одна функция модуля: оба механизма читают ОДНО значение, иначе они
    разойдутся в оценке одного и того же зазора.
    """
    default = default_interval_seconds()
    value = await _param(chat_id, KEY_CROSS_TYPE_INTERVAL, default)
    number = _as_int(value, default)
    return max(0, number)


def resolve_gap_seconds(own_cooldown_seconds: int,
                        interval_seconds: int) -> int:
    """Действующий зазор между типами = ``max(свой кулдаун, интервал)``.

    Интервал НЕ заменяет собственный кулдаун и не может его укоротить:
    ``0 < interval < cooldown`` ничего не меняет, ``interval > cooldown``
    удлиняет паузу между типами (это и есть его назначение).
    """
    return max(0, _as_int(own_cooldown_seconds),
               _as_int(interval_seconds))


class SqliteClaimStore:
    """Файловая бронь публикации (v41). Каждый вызов — своё соединение.

    Один стейтмент на решение; так N воркеров и N процессов видят РОВНО один
    результат (SQLite WAL), без in-process блокировок и без ``BEGIN IMMEDIATE``
    вокруг всей операции.
    """

    def __init__(self, path: str) -> None:
        self.path = str(path)

    # ── схема ─────────────────────────────────────────────────────────────
    def apply_schema(self) -> None:
        """Применить DDL (миграция v41 и тесты). Горячий путь её не зовёт."""
        conn = _connect(self.path)
        try:
            for statement in CLAIM_DDL_SQLITE:
                conn.execute(statement)
        finally:
            conn.close()

    def table_present(self) -> bool:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (CLAIM_TABLE,)).fetchone()
            return row is not None
        finally:
            conn.close()

    # ── чтение ────────────────────────────────────────────────────────────
    def snapshot(self, chat_id: int) -> dict:
        """Текущая строка брони (read-only; нет строки → пустой словарь)."""
        conn = _connect(self.path)
        try:
            row = conn.execute(
                f"SELECT * FROM {CLAIM_TABLE} WHERE chat_id = ?",
                (int(chat_id),)).fetchone()
            return dict(row) if row is not None else {}
        except Exception:
            return {}
        finally:
            conn.close()

    # ── решение ───────────────────────────────────────────────────────────
    def acquire(self, *, chat_id: int, holder_kind: str, holder_ref: str = "",
                now: int, interval_seconds: int = 0,
                other_ts: int | None = None, manual: bool = False,
                ttl: int = CLAIM_TTL_SECONDS) -> ClaimDecision:
        """CAS-бронь. ``rowcount == 1`` → выдана, иначе проигравший."""
        claim_id = uuid.uuid4().hex
        params = {
            "chat": int(chat_id),
            "cid": claim_id,
            "kind": str(holder_kind),
            "ref": str(holder_ref or "")[:160],
            "now": int(now),
            "exp": int(now) + max(1, _as_int(ttl, CLAIM_TTL_SECONDS)),
            "manual": 1 if manual else 0,
            "interval": max(0, _as_int(interval_seconds)),
            "other_ts": int(other_ts) if other_ts else None,
        }
        before = self.snapshot(chat_id)
        conn = _connect(self.path)
        try:
            cursor = conn.execute(_ACQUIRE_SQL, params)
            granted = int(cursor.rowcount or 0) == 1
        except Exception:
            logger.warning("[publish] claim acquire failed | chat=%s",
                           chat_id, exc_info=True)
            return ClaimDecision(granted=False, reason=REASON_CONFLICT,
                                 detail=DETAIL_CLAIM_HELD,
                                 coordination=COORDINATION_DEGRADED)
        finally:
            conn.close()
        row = self.snapshot(chat_id)
        recovered = bool(
            before
            and str(before.get("state") or "") == "sending"
            and _expired(before.get("expires_at"), int(now))
        )
        if granted:
            return ClaimDecision(
                granted=True, claim_id=claim_id, state="claimed",
                holder_kind=str(holder_kind),
                holder_ref=str(holder_ref or ""),
                detail=(DETAIL_DELIVERY_UNKNOWN if recovered else ""),
                interval_seconds=params["interval"],
                other_kind=str(before.get("last_publish_kind") or ""),
                other_age_seconds=self._age(now, before.get("last_publish_ts")),
                manual_priority_until=before.get("manual_priority_until"),
                expires_at=params["exp"],
                recovered_delivery_unknown=recovered)
        return self._denied(row, now=now, holder_kind=str(holder_kind),
                            interval=params["interval"], manual=manual)

    def begin_sending(self, *, chat_id: int, claim_id: str, now: int,
                      manual: bool = False,
                      ttl: int = SENDING_TTL_SECONDS) -> ClaimDecision:
        """`claimed → sending`. Единственное разрешение звать sender."""
        conn = _connect(self.path)
        try:
            cursor = conn.execute(_BEGIN_SENDING_SQL, {
                "chat": int(chat_id), "cid": str(claim_id), "now": int(now),
                "exp": int(now) + max(1, _as_int(ttl, SENDING_TTL_SECONDS)),
                "manual": 1 if manual else 0})
            granted = int(cursor.rowcount or 0) == 1
        except Exception:
            logger.warning("[publish] begin_sending failed | chat=%s",
                           chat_id, exc_info=True)
            return ClaimDecision(granted=False, reason=REASON_EXPIRED,
                                 detail=DETAIL_CLAIM_HELD,
                                 coordination=COORDINATION_DEGRADED)
        finally:
            conn.close()
        if granted:
            return ClaimDecision(granted=True, claim_id=str(claim_id),
                                 state="sending",
                                 expires_at=int(now) + _as_int(
                                     ttl, SENDING_TTL_SECONDS))
        return self._denied(self.snapshot(chat_id), now=now,
                            holder_kind="", interval=0, manual=manual,
                            our_claim_id=str(claim_id))

    def release(self, *, chat_id: int, claim_id: str, now: int,
                published: bool, holder_kind: str, holder_ref: str = ""
                ) -> bool:
        """Освободить СВОЮ бронь; ``published`` пишет watermark публикации."""
        conn = _connect(self.path)
        try:
            cursor = conn.execute(_RELEASE_SQL, {
                "chat": int(chat_id), "cid": str(claim_id), "now": int(now),
                "published": 1 if published else 0,
                "kind": str(holder_kind), "ref": str(holder_ref or "")[:160]})
            changed = int(cursor.rowcount or 0) >= 1
        except Exception:
            logger.warning("[publish] claim release failed | chat=%s",
                           chat_id, exc_info=True)
            return False
        finally:
            conn.close()
        event = _RELEASE_EVENTS.get(int(chat_id))
        if event is not None:
            event.set()
        return changed

    def claim_manual_priority(self, *, chat_id: int, now: int,
                              ttl: int = MANUAL_PRIORITY_SECONDS) -> int:
        """Маркер приоритета ручного `/meme` ОДНИМ стейтментом (до генерации).

        С этого момента автоматический путь не может перейти в `sending`;
        строки нет — вставляется инертная (`state='cancelled'`), чтобы маркер
        существовал независимо от истории публикаций.
        """
        until = int(now) + max(1, _as_int(ttl, MANUAL_PRIORITY_SECONDS))
        conn = _connect(self.path)
        try:
            conn.execute(_MANUAL_PRIORITY_SQL,
                         {"chat": int(chat_id), "now": int(now),
                          "until": until})
        except Exception:
            logger.warning("[publish] manual priority failed | chat=%s",
                           chat_id, exc_info=True)
            return 0
        finally:
            conn.close()
        return until

    # ── helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _age(now: int, stamp) -> int | None:
        try:
            value = int(stamp)
        except (TypeError, ValueError):
            return None
        return max(0, int(now) - value) if value else None

    def _denied(self, row: dict, *, now: int, holder_kind: str,
                interval: int, manual: bool,
                our_claim_id: str = "") -> ClaimDecision:
        """Почему бронь не выдана: код + detail (объяснение, не «просто нет»)."""
        row = row or {}
        state = str(row.get("state") or "")
        holder = str(row.get("holder_kind") or "")
        manual_until = row.get("manual_priority_until")
        try:
            manual_active = bool(manual_until) and int(manual_until) > int(now)
        except (TypeError, ValueError):
            manual_active = False
        age = self._age(now, row.get("last_publish_ts"))
        other_kind = str(row.get("last_publish_kind") or "")
        if manual:
            # Ручной запрос не боится чужого `claimed` (он его забирает), но
            # чужую отправку он не прерывает: честный publication_in_flight.
            reason = REASON_IN_FLIGHT if state == "sending" else REASON_CONFLICT
            detail = DETAIL_CLAIM_HELD
        elif manual_active:
            reason, detail = REASON_CONFLICT, DETAIL_MANUAL_PRIORITY
        elif (interval > 0 and age is not None and other_kind
              and other_kind != str(holder_kind) and age < interval):
            reason, detail = REASON_CONFLICT, DETAIL_CROSS_TYPE
        else:
            reason, detail = REASON_CONFLICT, DETAIL_CLAIM_HELD
        if our_claim_id and str(row.get("claim_id") or "") != our_claim_id \
                and state != "sending":
            reason = REASON_EXPIRED
        return ClaimDecision(
            granted=False, reason=reason, detail=detail,
            claim_id=str(row.get("claim_id") or ""), state=state,
            holder_kind=holder, holder_ref=str(row.get("holder_ref") or ""),
            interval_seconds=int(interval or 0), other_kind=other_kind,
            other_age_seconds=age,
            manual_priority_until=(int(manual_until) if manual_until else None),
            coordination=COORDINATION_OK,
            expires_at=row.get("expires_at"))


def open_store(db=None, *, path: str | None = None) -> SqliteClaimStore | None:
    """Бронь по файлу БД или явному пути. Нет пути → None (честно)."""
    target = str(path) if path else sqlite_path_of(db)
    if not target or target == ":memory:":
        return None
    return SqliteClaimStore(target)


class PublicationCoordinator:
    """Координатор публикаций чата: pre-check, claim, отправка, освобождение.

    Один экземпляр на проход механизма. Хранит только ссылки на БД/файл —
    состояние живёт в таблице, поэтому рестарт процесса ничего не теряет.
    """

    def __init__(self, db=None, *, store: SqliteClaimStore | None = None,
                 path: str | None = None,
                 now_fn: Callable[[], int] | None = None) -> None:
        self._db = db
        self._store = store if store is not None else open_store(db, path=path)
        self._now_fn = now_fn or now_ts
        self._warned = False

    # ── инфраструктура ────────────────────────────────────────────────────
    @property
    def db(self):
        return self._db

    def bind_db(self, db) -> None:
        """Поздняя привязка БД (наблюдатель создаётся до сервисов)."""
        self._db = db
        if self._store is None:
            self._store = open_store(db)

    def store(self) -> SqliteClaimStore | None:
        return self._store

    def available(self) -> bool:
        """Таблица брони реально есть (иначе ``degraded``, см. §3.6)."""
        if self._store is None:
            return False
        try:
            return bool(self._store.table_present())
        except Exception:
            return False

    def _degraded(self, reason: str, *, chat_id: int) -> None:
        if self._warned:
            return
        self._warned = True
        logger.warning(
            "[publish] coordination degraded (%s) | chat=%s — текстовая "
            "инициатива публикует без брони, мем остаётся на schema_absent",
            reason, chat_id)

    async def _interval(self, chat_id: int, interval_seconds: int | None
                        ) -> int:
        if interval_seconds is not None:
            return max(0, _as_int(interval_seconds))
        return await resolve_cross_type_interval(chat_id)

    async def _other_publish_ts(self, chat_id: int,
                                holder_kind: str) -> tuple[int | None, str]:
        """`sent_at` последней публикации ДРУГОГО типа из журнала выводов."""
        if self._db is None:
            return None, ""
        try:
            outputs = await self._db.list_recent_bot_outputs(
                int(chat_id), limit=len(PUBLICATION_KINDS),
                kinds=PUBLICATION_KINDS)
        except Exception:
            return None, ""
        for row in outputs or ():
            kind = str(row.get("output_kind") or "")
            if kind and kind != holder_kind:
                try:
                    return int(row.get("sent_at") or 0), kind
                except (TypeError, ValueError):
                    return None, kind
        return None, ""

    # ── проверка (объясняет) ──────────────────────────────────────────────
    async def precheck(self, chat_id: int, holder_kind: str, *,
                       now: int | None = None,
                       interval_seconds: int | None = None,
                       manual: bool = False) -> dict:
        """Дешёвая проверка ДО дорогой генерации. Ничего не пишет.

        Возвращает словарь с ``ok``/``reason``/``detail`` и полным набором
        чисел для диагностики (кто держит бронь, чей watermark, интервал).
        """
        stamp = int(now if now is not None else self._now_fn())
        interval = await self._interval(chat_id, interval_seconds)
        out = {
            "ok": True, "reason": REASON_NONE, "detail": "",
            "holder_kind": str(holder_kind), "state": "",
            "claim_id": "", "holder": "",
            "last_publish_ts": None, "last_publish_kind": "",
            "other_kind": "", "other_age_seconds": None,
            "interval_seconds": int(interval),
            "manual_priority_until": None,
            "coordination": COORDINATION_OK, "checked_at": stamp,
        }
        if not self.available():
            self._degraded("claim_table_absent", chat_id=chat_id)
            out["coordination"] = COORDINATION_DEGRADED
            return out
        row = self._store.snapshot(int(chat_id)) or {}
        other_ts, other_kind = await self._other_publish_ts(
            chat_id, str(holder_kind))
        # Два источника «последней чужой публикации»: журнал выводов (доставки)
        # и watermark самой строки брони (последний release). Берём САМУЮ
        # свежую чужую публикацию — запоздавшая запись одного источника не
        # должна выглядеть новее реальной.
        candidates: list[tuple[int, str]] = []
        if other_ts:
            candidates.append((max(0, stamp - int(other_ts)), other_kind))
        row_kind = str(row.get("last_publish_kind") or "")
        row_age = SqliteClaimStore._age(stamp, row.get("last_publish_ts"))
        if row_age is not None and row_kind and row_kind != str(holder_kind):
            candidates.append((int(row_age), row_kind))
        if candidates:
            other_age, other_kind = min(candidates, key=lambda item: item[0])
        else:
            other_age = None
        state = str(row.get("state") or "")
        manual_until = row.get("manual_priority_until")
        try:
            manual_active = bool(manual_until) and int(manual_until) > stamp
        except (TypeError, ValueError):
            manual_active = False
        out.update({
            "state": state,
            "claim_id": str(row.get("claim_id") or ""),
            "holder": str(row.get("holder_kind") or ""),
            "last_publish_ts": row.get("last_publish_ts"),
            "last_publish_kind": str(row.get("last_publish_kind") or ""),
            "other_kind": other_kind,
            "other_age_seconds": other_age,
            "manual_priority_until": (int(manual_until)
                                      if manual_until else None),
        })
        if manual:
            # Ручной запрос приоритетен: интервал и маркер его не ограничивают.
            # Чужая АКТИВНАЯ отправка — НЕ повод отказывать ДО генерации: тот же
            # `acquire` дождётся освобождения брони через существующий
            # release-event (предел `MANUAL_IN_FLIGHT_WAIT_SECONDS`) и возьмёт
            # слот. Отказ на precheck терял бы готовый мем и требовал второго
            # `/meme`, что запрещено (§1.2.3/§3.4 ТЗ).
            in_flight = bool(state == "sending"
                             and not _expired(row.get("expires_at"), stamp))
            out["in_flight"] = in_flight
            if in_flight:
                # Диагностика честная: слот занят, но ручной путь его ЖДЁТ.
                out["detail"] = DETAIL_CLAIM_HELD
                out["waits_for_slot"] = True
            return out
        if manual_active:
            out.update({"ok": False, "reason": REASON_CONFLICT,
                        "detail": DETAIL_MANUAL_PRIORITY})
            return out
        if interval > 0 and other_age is not None and \
                other_kind != str(holder_kind) and other_age < interval:
            out.update({"ok": False, "reason": REASON_CONFLICT,
                        "detail": DETAIL_CROSS_TYPE})
            return out
        if state in ("claimed", "sending") and \
                not _expired(row.get("expires_at"), stamp):
            out.update({"ok": False, "reason": REASON_CONFLICT,
                        "detail": DETAIL_CLAIM_HELD})
        return out

    # ── решение (решает) ──────────────────────────────────────────────────
    async def acquire(self, chat_id: int, holder_kind: str, *,
                      holder_ref: str = "", now: int | None = None,
                      interval_seconds: int | None = None,
                      manual: bool = False, ttl: int = CLAIM_TTL_SECONDS,
                      wait_for_sending: float = 0.0) -> ClaimDecision:
        """Атомарная бронь перед отправкой.

        ``manual`` — приоритетный ручной запрос: он забирает чужой `claimed`,
        а при чужом `sending` ждёт in-process событие освобождения (не дольше
        ``wait_for_sending`` секунд) и делает ОДНУ повторную попытку; не
        дождались → честный ``publication_in_flight`` без второй публикации.
        """
        stamp = int(now if now is not None else self._now_fn())
        interval = await self._interval(chat_id, interval_seconds)
        if not self.available():
            self._degraded("claim_table_absent", chat_id=chat_id)
            return ClaimDecision(
                granted=True, interval_seconds=int(interval),
                coordination=COORDINATION_DEGRADED,
                holder_kind=str(holder_kind))
        other_ts, other_kind = await self._other_publish_ts(
            chat_id, str(holder_kind))
        decision = self._store.acquire(
            chat_id=int(chat_id), holder_kind=str(holder_kind),
            holder_ref=holder_ref, now=stamp, interval_seconds=interval,
            other_ts=other_ts, manual=manual, ttl=ttl)
        if (not decision.granted and manual and decision.state == "sending"
                and wait_for_sending > 0):
            # Ждём освобождения чужой брони ТОЛЬКО для приоритетного ручного
            # запроса и только ограниченное время; затем ровно одна попытка.
            event = _release_event(int(chat_id))
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=wait_for_sending)
            except asyncio.TimeoutError:
                pass
            decision = self._store.acquire(
                chat_id=int(chat_id), holder_kind=str(holder_kind),
                holder_ref=holder_ref, now=int(self._now_fn()),
                interval_seconds=interval, other_ts=None, manual=True,
                ttl=ttl)
        if not decision.other_kind and other_kind:
            decision = dataclasses.replace(decision, other_kind=other_kind)
        return decision

    async def begin_sending(self, chat_id: int, claim_id: str, *,
                            now: int | None = None, manual: bool = False,
                            ttl: int = SENDING_TTL_SECONDS) -> ClaimDecision:
        """`claimed → sending` ровно перед вызовом sender."""
        stamp = int(now if now is not None else self._now_fn())
        if not self.available() or not claim_id:
            return ClaimDecision(granted=True, claim_id=str(claim_id or ""),
                                 state="sending",
                                 coordination=COORDINATION_DEGRADED)
        return self._store.begin_sending(chat_id=int(chat_id),
                                         claim_id=str(claim_id), now=stamp,
                                         manual=manual, ttl=ttl)

    async def release(self, chat_id: int, claim_id: str, *,
                      published: bool, holder_kind: str,
                      holder_ref: str = "", now: int | None = None) -> bool:
        """Освобождение брони; ``published=True`` пишет watermark публикации."""
        stamp = int(now if now is not None else self._now_fn())
        if not self.available() or not claim_id:
            return False
        return self._store.release(chat_id=int(chat_id), claim_id=str(claim_id),
                                   now=stamp, published=published,
                                   holder_kind=str(holder_kind),
                                   holder_ref=holder_ref)

    async def claim_manual_priority(self, chat_id: int, *,
                                    now: int | None = None,
                                    ttl: int = MANUAL_PRIORITY_SECONDS) -> int:
        """Маркер приоритета `/meme` ДО генерации (атомарно, один стейтмент)."""
        stamp = int(now if now is not None else self._now_fn())
        if not self.available():
            self._degraded("claim_table_absent", chat_id=chat_id)
            return 0
        return self._store.claim_manual_priority(chat_id=int(chat_id),
                                                 now=stamp, ttl=ttl)

    async def snapshot(self, chat_id: int, *, now: int | None = None) -> dict:
        """Диагностика брони чата (read-only, для payload/аналитики)."""
        stamp = int(now if now is not None else self._now_fn())
        if not self.available():
            return {"available": False,
                    "coordination": COORDINATION_DEGRADED,
                    "state": "", "holder_kind": "", "last_publish_ts": None,
                    "last_publish_kind": "", "other_age_seconds": None,
                    "interval_seconds": await resolve_cross_type_interval(
                        chat_id),
                    "manual_priority_until": None, "checked_at": stamp}
        row = self._store.snapshot(int(chat_id)) or {}
        interval = await resolve_cross_type_interval(chat_id)
        age = SqliteClaimStore._age(stamp, row.get("last_publish_ts"))
        return {
            "available": True,
            "coordination": COORDINATION_OK,
            "state": str(row.get("state") or ""),
            "holder_kind": str(row.get("holder_kind") or ""),
            "holder_ref": str(row.get("holder_ref") or ""),
            "claim_id": str(row.get("claim_id") or ""),
            "last_publish_ts": row.get("last_publish_ts"),
            "last_publish_kind": str(row.get("last_publish_kind") or ""),
            "other_age_seconds": age,
            "interval_seconds": int(interval),
            "manual_priority_until": row.get("manual_priority_until"),
            "expires_at": row.get("expires_at"),
            "checked_at": stamp,
        }


class TextPublication:
    """Одна текстовая публикация инициативы в чате (§3.5) — общий шов.

    Порядок ровно один для ВСЕХ sender'ов текста инициативы (повод
    наблюдателя, отложенное намерение heartbeat, делегированный кандидат
    nostalgia, legacy-отправка nostalgia, реальный прогон админской
    диагностики):

        precheck  → ОБЪЯСНЯЕТ (журнал выводов + строка брони), ничего не пишет;
        acquire   → РЕШАЕТ (CAS-бронь), ``granted=False`` = реплики нет;
        guard     → `claimed → sending` ровно перед отправкой;
        release   → освобождение с watermark публикации.

    Интервал между типами берётся ОДИН на оба механизма
    (:func:`resolve_cross_type_interval`); последняя публикация другого типа —
    watermark строки брони, а для путей без брони/до первой брони — журнал
    выводов (`precheck`).

    Таблицы брони нет → ``coordination="degraded"`` и текст публикуется
    (§3.6): служебная таблица не выключает основной механизм молча.

    ``claim=False`` — путь БЕЗ брони (dry-run админской диагностики): он
    ничего не публикует, поэтому и состояние чата не трогает, но интервал
    объясняется тем же `precheck`-ом, а ``guard()`` возвращает ту же причину
    отказа, какую увидел бы боевой путь.
    """

    def __init__(self, coordinator: PublicationCoordinator, chat_id: int, *,
                 holder_kind: str = KIND_TEXT_INITIATIVE,
                 holder_ref: str = "", now: int | None = None,
                 interval_seconds: int | None = None, manual: bool = False,
                 claim: bool = True) -> None:
        self._coordinator = coordinator
        self.chat_id = int(chat_id)
        self.holder_kind = str(holder_kind)
        self.holder_ref = str(holder_ref or "")
        self._now = None if now is None else int(now)
        self._interval = interval_seconds
        self._manual = bool(manual)
        self._want_claim = bool(claim)
        self.precheck: dict = {}
        self.claim: ClaimDecision | None = None
        self._closed = False

    # ── открытие: precheck → acquire ──────────────────────────────────────
    async def open(self) -> "TextPublication":
        self.precheck = await self._coordinator.precheck(
            self.chat_id, self.holder_kind, now=self._now,
            interval_seconds=self._interval, manual=self._manual)
        if not self.precheck.get("ok") or not self._want_claim:
            return self
        self.claim = await self._coordinator.acquire(
            self.chat_id, self.holder_kind, holder_ref=self.holder_ref,
            now=self._now, interval_seconds=self._interval,
            manual=self._manual)
        return self

    # ── состояние ─────────────────────────────────────────────────────────
    @property
    def granted(self) -> bool:
        """Можно идти к отправке (в режиме без брони решает precheck)."""
        if self.claim is not None:
            return bool(self.claim.granted)
        return bool(self.precheck.get("ok", True))

    @property
    def reason(self) -> str:
        if self.claim is not None and not self.claim.granted:
            return str(self.claim.reason or REASON_CONFLICT)
        if self.claim is None and not self.granted:
            return str(self.precheck.get("reason") or REASON_CONFLICT)
        return REASON_NONE

    @property
    def detail(self) -> str:
        if self.claim is not None:
            return str(self.claim.detail or "")
        return str(self.precheck.get("detail") or "")

    @property
    def coordination(self) -> str:
        if self.claim is not None:
            return str(self.claim.coordination or COORDINATION_OK)
        return str(self.precheck.get("coordination") or COORDINATION_OK)

    @property
    def claim_id(self) -> str:
        return str((self.claim.claim_id if self.claim is not None else "")
                   or self.precheck.get("claim_id") or "")

    # ── отправка ──────────────────────────────────────────────────────────
    async def guard(self) -> str | None:
        """`claimed → sending` перед отправкой; ``None`` — публиковать можно."""
        if self.claim is not None:
            # Бронь не наша: `begin_sending` бросается только со СВОИМ
            # claim_id — иначе он перевёл бы чужую бронь в `sending`.
            if not self.claim.granted:
                return str(self.claim.reason or REASON_CONFLICT)
            decision = await self._coordinator.begin_sending(
                self.chat_id, self.claim.claim_id, now=self._now,
                manual=self._manual)
            if decision.granted:
                return None
            return str(decision.reason or REASON_EXPIRED)
        # Путь без брони (dry-run): решает precheck, состояние не пишется.
        return self.reason or None

    async def close(self, *, published: bool) -> bool:
        """Освобождение аренды; ``published=True`` пишет watermark публикации."""
        # Освобождается ТОЛЬКО своя бронь: у проигравшего `claim_id` — чужой
        # (из строки), и release по нему освободил бы чужую аренду.
        if self._closed or self.claim is None or not self.claim.granted:
            return False
        self._closed = True
        return await self._coordinator.release(
            self.chat_id, self.claim.claim_id, published=bool(published),
            holder_kind=self.holder_kind, holder_ref=self.holder_ref,
            now=self._now)

    def as_dict(self) -> dict:
        """Диагностика аренды (payload/лог); без «сырых» текстов."""
        return {
            "granted": bool(self.granted),
            "reason": self.reason,
            "detail": self.detail,
            "coordination": self.coordination,
            "claim_id": self.claim_id,
            "holder_kind": self.holder_kind,
            "holder_ref": self.holder_ref,
            "precheck": dict(self.precheck or {}),
            "claim": (self.claim.as_dict() if self.claim is not None
                      else None),
        }


async def open_text_publication(db, chat_id: int, *,
                                holder_kind: str = KIND_TEXT_INITIATIVE,
                                holder_ref: str = "",
                                now: int | None = None,
                                interval_seconds: int | None = None,
                                manual: bool = False, claim: bool = True,
                                coordinator: PublicationCoordinator | None = None
                                ) -> TextPublication:
    """Открыть аренду текстовой публикации чата (precheck → acquire)."""
    return await TextPublication(
        coordinator if coordinator is not None
        else PublicationCoordinator(db),
        int(chat_id), holder_kind=holder_kind, holder_ref=holder_ref,
        now=now, interval_seconds=interval_seconds, manual=manual,
        claim=claim).open()


def compact_json(payload: dict | None) -> str:
    """Компактный JSON для полей ``detail``/payload (без переводов строк)."""
    if not payload:
        return ""
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    except (TypeError, ValueError):
        return ""


async def publication_claim_store_present(db) -> bool:
    """Есть ли таблица брони на этой БД (дешёвая проверка для диагностики)."""
    store = open_store(db)
    if store is None:
        return False
    try:
        return bool(store.table_present())
    except Exception:
        return False


__all__ = [
    "CLAIM_DDL_SQLITE", "CLAIM_DDL_POSTGRES", "CLAIM_MIGRATION_STEP_NAME",
    "CLAIM_SCHEMA_VERSION", "CLAIM_TABLE", "CLAIM_TTL_SECONDS",
    "COORDINATION_DEGRADED", "COORDINATION_OK", "ClaimDecision",
    "DETAIL_CLAIM_HELD", "DETAIL_CROSS_TYPE", "DETAIL_DELIVERY_UNKNOWN",
    "DETAIL_MANUAL_PRIORITY", "KEY_CROSS_TYPE_INTERVAL",
    "KIND_MEME_INITIATIVE", "KIND_TEXT_INITIATIVE", "MANUAL_PRIORITY_SECONDS",
    "MANUAL_IN_FLIGHT_WAIT_SECONDS", "PUBLICATION_KINDS",
    "PublicationCoordinator", "REASON_CONFLICT", "REASON_EXPIRED",
    "REASON_IN_FLIGHT", "SENDING_TTL_SECONDS", "SqliteClaimStore",
    "TextPublication", "compact_json", "default_interval_seconds",
    "open_store", "open_text_publication",
    "publication_claim_store_present", "resolve_cross_type_interval",
    "resolve_gap_seconds", "reset_release_events",
]
