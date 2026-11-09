"""QND-NONDET §1 (owner corrective 2026-11-10, frozen contract
`plans/features/smart-module-semantic-routing/quantum-nondeterminism-contract.md`).

Пер-чатовое стохастическое расписание СМЫСЛОВОЙ проверки для двух механизмов
(`nostalgia`, `initiative`) на ЕДИНОМ `RandomSourceService`.

Что здесь есть и чего здесь нет:
  * durable-строка на `(chat_id, mechanism)` — момент следующей проверки,
    параметры/значение последнего draw, lease для конкурентных прогонов
    (`semantic_schedule`, аддитивная миграция v47);
  * ограниченное адаптивное распределение: границы и коэффициенты — только
    `limits.qnd_*` (`ParamSpec`, редактируются в существующей админке);
  * один draw на выбор следующего момента (`draw_probability`, значение
    `[0,1)` → `delay = lo + (hi-lo) * u**shape`), без псевдослучайных
    подмешиваний и без второго генератора;
  * «пропущенный срок» = ровно ОДНО исполнение на claim, после которого ВСЕГДА
    новый draw; устаревший срок — только новый draw (никакой очереди
    задолженностей и массовой отправки);
  * `request_event` — событийный сигнал (durable `scan_requested_at` +
    немедленная диспетчеризация в существующий Observer), не сканер текста.

Здесь НЕТ: второго Observer/пайплайна, лексических триггеров, собственного
генератора случайности, записи в обход `DatabaseService.write_transaction`.
"""
from __future__ import annotations

import hashlib
import logging
import time
import json

logger = logging.getLogger(__name__)

# ── механизмы (ровно два; новых не появляется) ─────────────────────────────
MECH_NOSTALGIA = "nostalgia"
MECH_INITIATIVE = "initiative"
MECHANISMS: tuple[str, ...] = (MECH_NOSTALGIA, MECH_INITIATIVE)

# ── провенанс запуска (контракт §2: trigger="schedule|event") ──────────────
TRIGGER_SCHEDULE = "schedule"
TRIGGER_EVENT = "event"
TRIGGERS: tuple[str, ...] = (TRIGGER_SCHEDULE, TRIGGER_EVENT)

# ── фактический источник значения (R17: только код) ────────────────────────
SOURCE_QUANTUM = "quantum"
SOURCE_PSEUDORANDOM = "pseudorandom"
SOURCE_UNAVAILABLE = "unavailable"

# ── машиночитаемые причины (не строки для человека) ────────────────────────
REASON_NO_STATE = "no_state"
REASON_STALE = "stale_deadline"
REASON_LEASE_HELD = "lease_held"
REASON_SETTINGS_RESCALED = "settings_rescaled"
REASON_RANDOM_UNAVAILABLE = "random_unavailable"

TABLE = "semantic_schedule"
COMPONENT = "qnd"

#: §5 контракта: durable-события механизма (одно имя = одно событие).
EVENT_DRAW = "quantum_schedule_draw"
EVENT_DUE = "quantum_schedule_due"
EVENT_EVALUATION = "quantum_evaluation"
EVENT_PUBLICATION = "quantum_publication_decision"
EVENT_RESULT = "quantum_publication_result"

#: v47 (§1): аддитивная таблица. DDL живёт в модуле-владельце механизма,
#: шаг миграции только применяет его (IF NOT EXISTS) — второй копии нет.
SEMANTIC_SCHEDULE_DDL_SQLITE = (
    "CREATE TABLE IF NOT EXISTS semantic_schedule ("
    "chat_id INTEGER NOT NULL, "
    "mechanism TEXT NOT NULL, "
    "next_due_ts INTEGER NOT NULL DEFAULT 0, "
    "last_check_ts INTEGER, "
    "last_draw_ts INTEGER, "
    "lo_seconds REAL, "
    "hi_seconds REAL, "
    "shape REAL, "
    "u REAL, "
    "delay_seconds INTEGER, "
    "source TEXT NOT NULL DEFAULT '', "
    "provider TEXT, "
    "draw_id TEXT, "
    "fallback_reason TEXT, "
    "settings_hash TEXT NOT NULL DEFAULT '', "
    "missed_count INTEGER NOT NULL DEFAULT 0, "
    "scan_requested_at INTEGER, "
    "lease_until INTEGER NOT NULL DEFAULT 0, "
    "lease_owner TEXT, "
    "PRIMARY KEY (chat_id, mechanism))"
)
SEMANTIC_SCHEDULE_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_semantic_schedule_due "
    "ON semantic_schedule(mechanism, next_due_ts)",
)

# ── границы/коэффициенты: КОД-дефолты ParamSpec `limits.qnd_*` ─────────────
# Значения редактируются в существующей админке (category=limits,
# group=limits_qnd); здесь только заводские значения для отсутствующей строки.
DEFAULT_MIN_SECONDS: dict[str, float] = {
    MECH_NOSTALGIA: 1800.0,      # 30 минут
    MECH_INITIATIVE: 600.0,      # 10 минут
}
DEFAULT_MAX_SECONDS: dict[str, float] = {
    MECH_NOSTALGIA: 21600.0,     # 6 часов
    MECH_INITIATIVE: 7200.0,     # 2 часа
}
#: Явные ключи границ по механизмам (литералы, а не сборка строки): это и
#: читаемо, и проверяемо аудитом каталога (каждая ручка каталога видна в коде).
CADENCE_PARAMS: dict[str, tuple[str, str]] = {
    MECH_NOSTALGIA: ("limits.qnd_nostalgia_min_seconds",
                     "limits.qnd_nostalgia_max_seconds"),
    MECH_INITIATIVE: ("limits.qnd_initiative_min_seconds",
                      "limits.qnd_initiative_max_seconds"),
}
PARAM_DEFAULTS: dict[str, float] = {
    "limits.qnd_cadence_floor_seconds": 300.0,
    "limits.qnd_cadence_shape": 1.0,          # 1.0 = равномерное
    "limits.qnd_activity_min_factor": 0.35,
    "limits.qnd_activity_max_factor": 3.0,
    "limits.qnd_activity_target_mps": 0.02,   # сообщений/сек (≈72 в час)
    "limits.qnd_silence_hours": 24.0,
    "limits.qnd_silence_factor": 1.5,
    "limits.qnd_budget_factor": 2.0,
    "limits.qnd_stale_seconds": 21600.0,      # 6 часов «опоздания»
    "limits.qnd_lease_seconds": 300.0,
    "limits.qnd_heartbeat_seconds": 60.0,
    "limits.qnd_event_debounce_seconds": 90.0,
    "limits.qnd_event_min_interval_seconds": 1800.0,
    "limits.qnd_freshness_horizon_seconds": 86400.0,
}

#: Доли бюджета ниже этого порога включают `limits.qnd_budget_factor`.
BUDGET_TIGHT_RATIO = 0.20

_FIELDS = (
    "next_due_ts", "last_check_ts", "last_draw_ts", "lo_seconds",
    "hi_seconds", "shape", "u", "delay_seconds", "source", "provider",
    "draw_id", "fallback_reason", "settings_hash", "missed_count",
    "scan_requested_at", "lease_until", "lease_owner",
)


# ── инфраструктура ─────────────────────────────────────────────────────────

def _now(ts: int | float | None = None) -> int:
    return int(ts if ts is not None else time.time())


async def _param(chat_id, key: str, default):
    """Generic-резолв параметра: overrides чата → hot → код-дефолт.

    Тот же порядок, что у остальных потребителей (`initiative_observer.
    _param`): пер-чатовый override сильнее, заводское значение — последний
    рубеж. Ошибка резолва не роняет расписание.
    """
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


async def _num(chat_id, key: str, default: float,
               *, minimum: float | None = None) -> float:
    raw = await _param(chat_id, key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float(default)
    if minimum is not None:
        value = max(float(minimum), value)
    return value


async def _int(chat_id, key: str, default: float,
               *, minimum: int = 0) -> int:
    return max(int(minimum), int(round(await _num(chat_id, key, default))))


async def _message_rate(db, chat_id, now: int) -> float:
    """Реальный темп чата (сообщений/сек) — существующий источник observer."""
    try:
        from services import initiative_observer as observer
        return float(await observer.recent_message_rate(
            db, int(chat_id), now=now) or 0.0)
    except Exception:
        return 0.0


async def _last_user_ts(db, chat_id) -> int | None:
    try:
        return await db.get_last_user_message_ts(int(chat_id), None)
    except Exception:
        return None


async def _budget_tight() -> bool:
    """< 20% остатка любого дневного бюджета фона → «тесно».

    Источник — существующий `worker_budget.get_usage` (PG). Нет данных/нет PG
    → НЕ тесно (расписание не выдумывает дефицит).
    """
    try:
        from services import worker_budget
        rows = await worker_budget.get_usage() or []
    except Exception:
        return False
    for row in rows:
        try:
            used = float(row.get("used") or 0.0)
            limit = float(row.get("limit") or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
        if limit <= 0:
            continue
        if max(0.0, limit - used) / limit < BUDGET_TIGHT_RATIO:
            return True
    return False


#: DI-крючок для тестов (`controlled RandomSource`, контракт §7). В продукте
#: всегда `None` — источник резолвится единственным `RandomSourceService`.
_INJECTED_SOURCE = None


def set_source(source) -> None:
    """Подставить управляемый источник (только тесты/DI)."""
    global _INJECTED_SOURCE
    _INJECTED_SOURCE = source


def reset_source() -> None:
    global _INJECTED_SOURCE
    _INJECTED_SOURCE = None


def _default_source(db):
    """Единственный контур случайности (`RandomSourceService`). Второго нет."""
    if _INJECTED_SOURCE is not None:
        return _INJECTED_SOURCE
    try:
        from services import mca_random_source
        return mca_random_source.get_service(db)
    except Exception:
        logger.warning("[qnd] random source unavailable", exc_info=True)
        return None


def settings_hash(mechanism: str, cadence: dict) -> str:
    """sha256 резолвнутых границ/весов (§1: смена настроек — видимая причина)."""
    material = {
        "mechanism": str(mechanism or ""),
        "lo": round(float(cadence.get("lo_seconds") or 0.0), 6),
        "hi": round(float(cadence.get("hi_seconds") or 0.0), 6),
        "lo_adj": round(float(cadence.get("lo_adj") or 0.0), 6),
        "hi_adj": round(float(cadence.get("hi_adj") or 0.0), 6),
        "shape": round(float(cadence.get("shape") or 1.0), 6),
        "floor": round(float(cadence.get("floor") or 0.0), 6),
        "act": round(float(cadence.get("act") or 1.0), 6),
        "sil": round(float(cadence.get("sil") or 1.0), 6),
        "bud": round(float(cadence.get("bud") or 1.0), 6),
        "anticipation": dict(cadence.get("weights") or {}),
    }
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def resolve_cadence(db, mechanism: str, chat_id, *,
                          now: int | None = None) -> dict:
    """Резолв границ/коэффициентов распределения (§1 контракта).

    Всё, что влияет на интервал, — редактируемый параметр `limits.qnd_*` и
    ФАКТИЧЕСКИЕ данные чата (темп сообщений, тишина, остаток бюджета).
    Ноль зашитых интервалов/вероятностей в потребителях.
    """
    stamp = _now(now)
    lo_key, hi_key = CADENCE_PARAMS[mechanism]
    lo = await _num(chat_id, lo_key,
                    DEFAULT_MIN_SECONDS[mechanism], minimum=1.0)
    hi = await _num(chat_id, hi_key,
                    DEFAULT_MAX_SECONDS[mechanism], minimum=1.0)
    hi = max(hi, lo)
    floor = await _num(chat_id, "limits.qnd_cadence_floor_seconds",
                       PARAM_DEFAULTS["limits.qnd_cadence_floor_seconds"],
                       minimum=1.0)
    shape = await _num(chat_id, "limits.qnd_cadence_shape",
                       PARAM_DEFAULTS["limits.qnd_cadence_shape"],
                       minimum=0.05)
    act_min = await _num(chat_id, "limits.qnd_activity_min_factor",
                         PARAM_DEFAULTS["limits.qnd_activity_min_factor"],
                         minimum=0.01)
    act_max = await _num(chat_id, "limits.qnd_activity_max_factor",
                         PARAM_DEFAULTS["limits.qnd_activity_max_factor"],
                         minimum=1.0)
    act_max = max(act_max, act_min)
    target_mps = await _num(chat_id, "limits.qnd_activity_target_mps",
                            PARAM_DEFAULTS["limits.qnd_activity_target_mps"],
                            minimum=1e-6)
    silence_hours = await _num(chat_id, "limits.qnd_silence_hours",
                               PARAM_DEFAULTS["limits.qnd_silence_hours"],
                               minimum=0.0)
    silence_factor = await _num(chat_id, "limits.qnd_silence_factor",
                                PARAM_DEFAULTS["limits.qnd_silence_factor"],
                                minimum=1.0)
    budget_factor = await _num(chat_id, "limits.qnd_budget_factor",
                               PARAM_DEFAULTS["limits.qnd_budget_factor"],
                               minimum=1.0)

    rate = await _message_rate(db, chat_id, stamp)
    act = max(act_min, min(act_max, (rate / target_mps) if target_mps else 1.0))
    last_user = await _last_user_ts(db, chat_id)
    silent = (last_user is None) or (stamp - int(last_user)
                                     >= silence_hours * 3600.0)
    sil = float(silence_factor) if silent else 1.0
    bud = float(budget_factor) if await _budget_tight() else 1.0

    lo_adj = max(float(floor), lo * sil * bud / max(1.0, act))
    hi_adj = max(lo_adj, hi * sil * bud)

    # Антифлуд/мин-пауза могут только ПОДНИМАТЬ нижнюю границу: после
    # опубликованной реплики проверка не может быть раньше разрешённого
    # интервала. Верхняя граница не уменьшается (§1).
    flood = await _anti_flood_floor(chat_id)
    lo_adj = max(lo_adj, float(flood))
    hi_adj = max(lo_adj, hi_adj)

    cadence = {
        "mechanism": mechanism,
        "lo_seconds": lo,
        "hi_seconds": hi,
        "lo_adj": lo_adj,
        "hi_adj": hi_adj,
        "shape": shape,
        "floor": floor,
        "act": act,
        "sil": sil,
        "bud": bud,
        "rate_mps": rate,
        "anti_flood": float(flood),
        "weights": {"activity_target": target_mps,
                    "silence_hours": silence_hours,
                    "silence_factor": silence_factor,
                    "budget_factor": budget_factor},
    }
    cadence["settings_hash"] = settings_hash(mechanism, cadence)
    return cadence


async def _anti_flood_floor(chat_id) -> int:
    """`min_gap_seconds`/`ANTI_FLOOD_AFTER_BOT_OUTPUT_SECONDS` как нижний порог."""
    floor = 0
    try:
        from services import initiative_observer as observer
        floor = int(getattr(observer, "ANTI_FLOOD_AFTER_BOT_OUTPUT_SECONDS", 0)
                    or 0)
    except Exception:
        floor = 0
    try:
        value = await _param(chat_id, "initiative.min_gap_seconds", 0)
        floor = max(floor, int(float(value or 0)))
    except (TypeError, ValueError):
        pass
    return max(0, floor)


# ── durable-строка ─────────────────────────────────────────────────────────

async def _row(db, mechanism: str, chat_id) -> dict | None:
    try:
        cursor = await db.db.execute(
            f"SELECT {', '.join(('chat_id', 'mechanism') + _FIELDS)} "
            f"FROM {TABLE} WHERE chat_id = ? AND mechanism = ?",
            (int(chat_id), str(mechanism)))
        row = await cursor.fetchone()
    except Exception:
        logger.warning("[qnd] schedule row read failed | chat=%s mech=%s",
                       chat_id, mechanism, exc_info=True)
        return None
    return dict(row) if row is not None else None


async def _write(db, mechanism: str, chat_id, fields: dict, *,
                 upsert: bool) -> dict | None:
    """Запись строки расписания через ЕДИНЫЙ write-канал (`write_transaction`)."""
    cols = [c for c in fields if c in _FIELDS]
    if not cols:
        return await _row(db, mechanism, chat_id)
    values = [fields[c] for c in cols]

    async def op(conn):
        if upsert:
            sql = (
                f"INSERT INTO {TABLE} (chat_id, mechanism, "
                + ", ".join(cols) + ") VALUES (?, ?, "
                + ", ".join("?" * len(cols)) + ") "
                + "ON CONFLICT(chat_id, mechanism) DO UPDATE SET "
                + ", ".join(f"{c}=excluded.{c}" for c in cols))
            params = [int(chat_id), str(mechanism)] + values
        else:
            sql = (f"UPDATE {TABLE} SET "
                   + ", ".join(f"{c}=?" for c in cols)
                   + " WHERE chat_id = ? AND mechanism = ?")
            params = values + [int(chat_id), str(mechanism)]
        cursor = await conn.execute(sql, params)
        return cursor.rowcount or 0

    try:
        await db.write_transaction(op, op_name="semantic_schedule")
    except Exception:
        logger.warning("[qnd] schedule write failed | chat=%s mech=%s",
                       chat_id, mechanism, exc_info=True)
        return None
    return await _row(db, mechanism, chat_id)


async def _insert_scan_request(db, mechanism: str, chat_id, *, now: int) -> None:
    """durable-сигнал события: строка без draw, срок ≤ сейчас."""
    async def op(conn):
        cursor = await conn.execute(
            f"INSERT INTO {TABLE} (chat_id, mechanism, next_due_ts, "
            "scan_requested_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id, mechanism) DO UPDATE SET "
            "scan_requested_at=excluded.scan_requested_at, "
            "next_due_ts=MIN(COALESCE(semantic_schedule.next_due_ts, "
            "excluded.next_due_ts), excluded.next_due_ts)",
            (int(chat_id), str(mechanism), int(now), int(now)))
        return cursor.rowcount or 0

    try:
        await db.write_transaction(op, op_name="semantic_schedule_event")
    except Exception:
        logger.warning("[qnd] schedule event mark failed | chat=%s mech=%s",
                       chat_id, mechanism, exc_info=True)


# ── публичный API §1 ───────────────────────────────────────────────────────

async def ensure(db, mechanism: str, chat_id, *,
                 now: int | None = None) -> dict | None:
    """Гарантировать durable-строку и актуальный `settings_hash`.

    * строки нет → ОДИН draw (`reason="no_state"`, первый heartbeat);
    * строка есть → она авторитетна (`next_due_ts` не перевыводится);
    * настройки изменились → `next_due_ts` зажимается в новые границы от
      `last_check_ts` (в прошлом → `now + lo_adj`), БЕЗ исполнения,
      `reason="settings_rescaled"`.
    """
    stamp = _now(now)
    row = await _row(db, mechanism, chat_id)
    if row is None:
        return await draw_next(db, mechanism, chat_id, now=stamp,
                               source=None, trigger=TRIGGER_SCHEDULE,
                               reason=REASON_NO_STATE)
    if row.get("last_draw_ts") is None:
        # Строка создана событийным сигналом: draw ещё не было, поэтому
        # пересчёт «смены настроек» здесь не применяется.
        return row
    cadence = await resolve_cadence(db, mechanism, chat_id, now=stamp)
    if str(row.get("settings_hash") or "") == cadence["settings_hash"]:
        return row
    base = int(row.get("last_check_ts") or stamp)
    lo_adj = float(cadence["lo_adj"])
    hi_adj = float(cadence["hi_adj"])
    planned = int(row.get("next_due_ts") or base)
    clamped = base + min(max(planned - base, lo_adj), hi_adj)
    if clamped <= stamp:
        clamped = stamp + lo_adj
    updated = await _write(
        db, mechanism, chat_id,
        {"next_due_ts": int(round(clamped)),
         "settings_hash": cadence["settings_hash"]}, upsert=False)
    emit_due(mechanism, chat_id, planned_at=planned, executed_at=stamp,
             lateness_seconds=0, missed_count=int(row.get("missed_count") or 0),
             executed=False, trigger=TRIGGER_SCHEDULE,
             reason_code=REASON_SETTINGS_RESCALED)
    return updated or row


async def due(db, mechanism: str, chat_id, *,
              now: int | None = None) -> bool:
    """Есть ли наступившее событие расписания для чата."""
    stamp = _now(now)
    row = await _row(db, mechanism, chat_id)
    if row is None:
        return False
    if row.get("scan_requested_at") is not None:
        return True
    return int(row.get("next_due_ts") or 0) <= stamp


async def due_chats(db, mechanism: str, *, now: int | None = None) -> list[int]:
    """Чаты с наступившим/запрошенным событием (heartbeat исполняет только их)."""
    stamp = _now(now)
    try:
        cursor = await db.db.execute(
            f"SELECT chat_id FROM {TABLE} WHERE mechanism = ? AND "
            "(scan_requested_at IS NOT NULL OR next_due_ts <= ?) "
            "ORDER BY next_due_ts ASC", (str(mechanism), stamp))
        rows = await cursor.fetchall()
    except Exception:
        logger.warning("[qnd] due_chats failed | mech=%s", mechanism,
                       exc_info=True)
        return []
    return [int(r["chat_id"]) for r in rows]


async def claim(db, mechanism: str, chat_id, *, now: int | None = None,
                owner: str = "") -> bool:
    """Атомарная аренда одной строки (§1 «Concurrency»).

    Условный `UPDATE` по `lease_until <= now`: rowcount 1 — владелец, 0 —
    проигравший (он ничего не делает и сообщает `lease_held`).
    """
    stamp = _now(now)
    ttl = await _int(None, "limits.qnd_lease_seconds",
                     PARAM_DEFAULTS["limits.qnd_lease_seconds"], minimum=1)

    async def op(conn):
        cursor = await conn.execute(
            f"UPDATE {TABLE} SET lease_until = ?, lease_owner = ? "
            "WHERE chat_id = ? AND mechanism = ? AND lease_until <= ?",
            (stamp + int(ttl), str(owner or "")[:80], int(chat_id),
             str(mechanism), stamp))
        return cursor.rowcount or 0

    try:
        won = await db.write_transaction(op, op_name="semantic_schedule_claim")
    except Exception:
        logger.warning("[qnd] claim failed | chat=%s mech=%s", chat_id,
                       mechanism, exc_info=True)
        return False
    if int(won or 0) != 1:
        emit_due(mechanism, chat_id, planned_at=stamp, executed_at=stamp,
                 lateness_seconds=0,
                 missed_count=0, executed=False,
                 trigger=TRIGGER_SCHEDULE, reason_code=REASON_LEASE_HELD)
        return False
    return True


async def release(db, mechanism: str, chat_id, *, owner: str = "") -> None:
    """Освободить аренду (успешное/провалившееся исполнение уже сняло её)."""
    await _write(db, mechanism, chat_id,
                 {"lease_until": 0, "lease_owner": str(owner or "")[:80]},
                 upsert=False)


def _draw_payload(mechanism: str, chat_id, *, cadence: dict, u,
                  delay_seconds, next_due_ts, source: str, provider,
                  draw_id, fallback_reason, trigger: str) -> dict:
    return {
        "mechanism": str(mechanism),
        "chat_id": int(chat_id),
        "lo": round(float(cadence["lo_adj"]), 3),
        "hi": round(float(cadence["hi_adj"]), 3),
        "shape": round(float(cadence["shape"]), 6),
        "u": (None if u is None else round(float(u), 9)),
        "delay_seconds": (None if delay_seconds is None
                          else int(delay_seconds)),
        "next_due_ts": (None if next_due_ts is None else int(next_due_ts)),
        "source": str(source or ""),
        "provider": provider,
        "draw_id": draw_id,
        "fallback_reason": fallback_reason,
        "settings_hash": str(cadence.get("settings_hash") or ""),
        "trigger": str(trigger or ""),
    }


def emit_draw(mechanism: str, chat_id, payload: dict) -> None:
    """Durable-событие `quantum_schedule_draw` (§5)."""
    _emit(EVENT_DRAW, mechanism=mechanism, chat_id=chat_id, payload=payload,
          outcome=("success" if payload.get("u") is not None else "skipped"))


def emit_due(mechanism: str, chat_id, *, planned_at, executed_at,
             lateness_seconds: int, missed_count: int, executed: bool,
             trigger: str, reason_code: str = "") -> None:
    """Durable-событие `quantum_schedule_due` (§5)."""
    payload = {
        "mechanism": str(mechanism),
        "chat_id": int(chat_id),
        "planned_at": int(planned_at or 0),
        "executed_at": int(executed_at or 0),
        "lateness_seconds": int(lateness_seconds or 0),
        "missed_count": int(missed_count or 0),
        "executed": bool(executed),
        "trigger": str(trigger or ""),
    }
    if reason_code:
        payload["reason_code"] = str(reason_code)
    _emit(EVENT_DUE, mechanism=mechanism, chat_id=chat_id, payload=payload,
          outcome=("success" if executed else "skipped"),
          reason_code=reason_code or None)


def _emit(event_name: str, *, mechanism: str, chat_id, payload: dict,
          outcome: str, reason_code: str | None = None,
          level: str = "INFO") -> None:
    """Единая точка эмиссии QND-событий (fail-open, R17: коды/числа).

    Полный набор полей §5 едет в `usage_json` (единственное JSON-поле
    контракта mca-13, читается существующими агрегаторами), а `chat_id/
    component/outcome/reason_code` — обычные durable-колонки.
    """
    try:
        from services import mca_events
        fields = {
            "component": COMPONENT,
            "chat_id": int(chat_id),
            "usage_json": dict(payload or {}),
            "stage": str(mechanism or ""),
        }
        if reason_code:
            fields["reason_code"] = str(reason_code)
        mca_events.emit_mca_event(event_name, outcome=outcome, level=level,
                                  **fields)
    except Exception:
        logger.debug("[qnd] emit failed | event=%s", event_name, exc_info=True)


async def draw_next(db, mechanism: str, chat_id, *, now: int | None = None,
                    source=None, trigger: str = TRIGGER_SCHEDULE,
                    reason: str = "") -> dict | None:
    """Один draw следующего момента проверки (ровно один на вызов).

    `deferred`/`disabled`/нет значения → НЕ выдумываем интервал: срок
    остаётся наступившим (`now`), причина сохраняется, следующий heartbeat
    повторит попытку. Фактический источник значения всегда записан.
    """
    stamp = _now(now)
    cadence = await resolve_cadence(db, mechanism, chat_id, now=stamp)
    src = source if source is not None else _default_source(db)
    result = None
    if src is not None:
        try:
            result = await src.draw_probability(
                chat_id=int(chat_id), purpose=f"{mechanism}_schedule")
        except Exception:
            logger.warning("[qnd] schedule draw failed | chat=%s mech=%s",
                           chat_id, mechanism, exc_info=True)
            result = None
    value = getattr(result, "value", None)
    deferred = (result is None
                or bool(getattr(result, "deferred", False))
                or value is None)
    if deferred:
        fallback_reason = str(
            getattr(result, "reason", "") or REASON_RANDOM_UNAVAILABLE)
        fields = {
            "next_due_ts": int(stamp),
            "last_draw_ts": int(stamp),
            "lo_seconds": float(cadence["lo_adj"]),
            "hi_seconds": float(cadence["hi_adj"]),
            "shape": float(cadence["shape"]),
            "u": None,
            "delay_seconds": None,
            "source": SOURCE_UNAVAILABLE,
            "provider": getattr(result, "provider", None),
            "draw_id": getattr(result, "draw_id", None),
            "fallback_reason": fallback_reason,
            "settings_hash": cadence["settings_hash"],
        }
        row = await _write(db, mechanism, chat_id, fields, upsert=True)
        emit_draw(mechanism, chat_id, _draw_payload(
            mechanism, chat_id, cadence=cadence, u=None, delay_seconds=None,
            next_due_ts=int(stamp), source=SOURCE_UNAVAILABLE,
            provider=fields["provider"], draw_id=fields["draw_id"],
            fallback_reason=fallback_reason, trigger=trigger))
        return row

    try:
        u = float(value)
    except (TypeError, ValueError):
        u = 0.0
    u = min(0.999999999, max(0.0, u))
    lo_adj = float(cadence["lo_adj"])
    hi_adj = float(cadence["hi_adj"])
    shape = float(cadence["shape"])
    delay = lo_adj + (hi_adj - lo_adj) * (u ** shape)
    next_due = stamp + int(round(delay))
    if mechanism == MECH_NOSTALGIA:
        next_due = _shift_out_of_quiet(next_due)
    fields = {
        "next_due_ts": int(next_due),
        "last_draw_ts": int(stamp),
        "lo_seconds": lo_adj,
        "hi_seconds": hi_adj,
        "shape": shape,
        "u": u,
        "delay_seconds": int(round(delay)),
        "source": str(getattr(result, "source", "") or SOURCE_QUANTUM),
        "provider": getattr(result, "provider", None),
        "draw_id": getattr(result, "draw_id", None),
        "fallback_reason": getattr(result, "fallback_reason", None),
        "settings_hash": cadence["settings_hash"],
        # срок исполняется — сигнал «проверить сейчас» снят
        "scan_requested_at": None,
    }
    if reason == REASON_NO_STATE:
        fields["last_check_ts"] = None
    row = await _write(db, mechanism, chat_id, fields, upsert=True)
    emit_draw(mechanism, chat_id, _draw_payload(
        mechanism, chat_id, cadence=cadence, u=u, delay_seconds=delay,
        next_due_ts=int(next_due), source=fields["source"],
        provider=fields["provider"], draw_id=fields["draw_id"],
        fallback_reason=fields["fallback_reason"], trigger=trigger))
    return row


def _shift_out_of_quiet(next_due: int) -> int:
    """Детерминированный сдвиг из тихих часов (второго draw нет).

    Тихие часы — существующие `memory.nostalgia_quiet_*`; сдвиг ровно в
    первый разрешённый локальный час, не более одного шага в сутки.
    """
    try:
        from config.settings import settings
        from services import hot_config as hot
        tz_name = str(hot.get("limits.summary_timezone",
                              settings.SUMMARY_TIMEZONE) or "UTC")
        start = int(hot.get("memory.nostalgia_quiet_start_hour",
                            settings.NOSTALGIA_QUIET_START_HOUR) or 0)
        end = int(hot.get("memory.nostalgia_quiet_end_hour",
                          settings.NOSTALGIA_QUIET_END_HOUR) or 0)
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
        import datetime as _dt
        local = _dt.datetime.fromtimestamp(int(next_due), tz)
        if not (local.hour >= start or local.hour < end):
            return int(next_due)
        allowed = local.replace(hour=(end % 24), minute=0, second=0,
                                microsecond=0)
        if allowed <= local:
            allowed = allowed + _dt.timedelta(days=1)
        return int(allowed.timestamp())
    except Exception:
        return int(next_due)


async def mark_executed(db, mechanism: str, chat_id, *,
                        now: int | None = None,
                        trigger: str = TRIGGER_SCHEDULE,
                        lateness_seconds: int = 0,
                        missed_count: int = 0) -> dict | None:
    """Зафиксировать ОДНО исполнение и снять сигнал «проверить сейчас»."""
    stamp = _now(now)
    return await _write(
        db, mechanism, chat_id,
        {"last_check_ts": int(stamp),
         "missed_count": int(missed_count or 0),
         "scan_requested_at": None,
         "lease_until": 0}, upsert=False)


async def mark_missed(db, mechanism: str, chat_id, *, now: int | None = None,
                      missed_count: int = 0) -> dict | None:
    """Зафиксировать ПРОПУЩЕННЫЙ срок БЕЗ исполнения (§1 «stale»).

    `last_check_ts` НЕ двигается: смысловой проверки не было, и выдавать
    пропуск за проверку нельзя. Меняются только `missed_count` и снятая
    метка события (срок всё равно будет перерисован).
    """
    return await _write(
        db, mechanism, chat_id,
        {"missed_count": int(missed_count or 0),
         "scan_requested_at": None,
         "lease_until": 0}, upsert=False)


async def request_event(db, chat_id, *, reason: str = "live_message",
                        now: int | None = None,
                        dispatch: bool = True) -> dict:
    """Событийный сигнал (§2): durable-метка + немедленная диспетчеризация.

    Метка ставится ОБОИМ механизмам: расписание обязано увидеть событие, а
    решение принимает существующий Observer. Немедленный запуск — через
    `TaskSupervisor` в существующий `observe_tick(trigger="event",
    only_chat=…)`; второго Observer/пайплайна нет.
    """
    stamp = _now(now)
    for mechanism in MECHANISMS:
        await _insert_scan_request(db, mechanism, chat_id, now=stamp)
    out = {"requested": True, "reason": str(reason or ""), "dispatch": None}
    if dispatch:
        try:
            from services import initiative_observer as observer
            out["dispatch"] = await observer.dispatch_event(
                db, chat_id=int(chat_id), reason=reason, now=stamp)
        except Exception:
            logger.warning("[qnd] event dispatch failed | chat=%s",
                           chat_id, exc_info=True)
            out["dispatch"] = "error"
    return out


async def next_due_ts(db, mechanism: str, chat_id) -> int | None:
    """Срок следующей проверки чата (`None` — строки нет)."""
    row = await _row(db, mechanism, chat_id)
    if row is None:
        return None
    return int(row.get("next_due_ts") or 0)


async def snapshot(db, *, now: int | None = None,
                   mechanism: str | None = None) -> dict:
    """Состояние расписания для Статуса/Аналитики (реальные строки)."""
    stamp = _now(now)
    mechanisms = ([mechanism] if mechanism else list(MECHANISMS))
    out: dict = {"now": stamp, "mechanisms": {}}
    for mech in mechanisms:
        try:
            cursor = await db.db.execute(
                f"SELECT {', '.join(('chat_id', 'mechanism') + _FIELDS)} "
                f"FROM {TABLE} WHERE mechanism = ? ORDER BY next_due_ts ASC",
                (str(mech),))
            rows = [dict(r) for r in await cursor.fetchall()]
        except Exception:
            rows = []
        out["mechanisms"][mech] = {
            "chats": len(rows),
            "rows": rows,
            "rows_due": len([r for r in rows
                             if r.get("scan_requested_at") is not None
                             or int(r.get("next_due_ts") or 0) <= stamp]),
        }
    return out
