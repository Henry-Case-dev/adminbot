"""SOUL-1 W5 (SOUL-18.2/18.4/18.5) — жизнеспособность инициативы без вранья.

Задача слайса: показать ЧЕСТНУЮ воронку наблюдателя за окно, отделить
`health` (тики/задачи живы) от `outcome` (инициативное сообщение реально
доставлено), объяснить причины молчания и дать владельцу безопасную
проверку «Проверить инициативу» с полным trace до mock send.

Принципы модуля:
* **нули видны как нули** — ни одно плечо не подменяется «здоровьем»;
* **никаких выдуманных чисел** — если durable-данных нет, поле получает
  ``None``/``null`` и честную пометку о покрытии окна (``coverage``);
* **R17-safe** — наружу уходят только коды/числа/ID; сырой текст чата
  остаётся в БД и никогда не попадает в payload (исключение — ``preview``
  диагностики, и он предназначен владельцу, а не в логи/события);
* **диагностика не подменяет отправку** — mock-прогон не пишет воронку и
  не создаёт ни одного сообщения в чате.

Источники (все существующие):
* ``task_jobs`` kind='initiative.observe' — durable checkpoint-payload
  наблюдателя (накопительные счётчики + per-chat состояние);
* ``mca_events`` — оконные события воронки (ts-фильтр); читаются как есть
  (`SELECT *`), поэтому модуль не зависит от наличия необязательных колонок
  в старой БД; machine-токены берутся из существующей колонки `entity_ids`;
* ``mca_bot_outputs`` — source of truth доставленных инициативных сообщений
  (``tg_message_id``, ``correlation_id``, ``content_hash``);
* ``smart_messages`` — живой трафик чата (для отделения «задушено» от
  «в чате тихо»).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from services import initiative_observer as obs

logger = logging.getLogger(__name__)

#: События воронки инициативы (оконные COUNT).
SCAN_EVENT = "initiative_observer_scan"
OPPORTUNITY_EVENT = "initiative_opportunity"
DECIDED_EVENT = "initiative_decided"
WRITER_GENERATED_EVENT = "initiative_writer_generated"
WRITER_UNAVAILABLE_EVENT = "initiative_writer_unavailable"
RECHECK_PASSED_EVENT = "initiative_recheck_passed"
SENT_EVENT = "initiative_sent"
DIAGNOSTIC_EVENT = "initiative_observer_diagnostic"
MANIFEST_EVENT = "initiative_delivery_manifest"
CHECK_EVENT = "initiative_diagnostics_check"

INITIATIVE_EVENTS = (
    SCAN_EVENT, OPPORTUNITY_EVENT, DECIDED_EVENT, WRITER_GENERATED_EVENT,
    WRITER_UNAVAILABLE_EVENT, RECHECK_PASSED_EVENT, SENT_EVENT,
    DIAGNOSTIC_EVENT,
)

#: Плечо доставки в ledger (source of truth факта отправки).
OUTPUT_KIND_INITIATIVE = "initiative_reply"

#: Границы вердикта «живой чат» (SOUL-18.5: 2000+ сообщений за сутки).
BUSY_MESSAGES_PER_DAY = 2000
#: Сколько подряд идущих решений-молчаний считаем «затяжным молчанием».
SILENT_STREAK_MIN = 3
#: Максимум строк в компактных списках ответа (не аналитическая стена).
LIST_LIMIT = 5
#: Ограничение выборки событий окна (bounded чтение).
EVENT_ROWS_MAX = 4000
#: Сколько секунд без тика наблюдателя считаем «heartbeat не живой».
HEARTBEAT_STALE_SECONDS = 3 * 300


def _now(ts=None) -> int:
    return int(time.time() if ts is None else int(ts))


def _int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _tokens_of(row: dict) -> list[str]:
    """Machine-токены события из колонки `entity_ids` (JSON-список)."""
    raw = row.get("entity_ids")
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if isinstance(data, dict):
        return [str(k) for k in data.keys()] + [str(v) for v in data.values()]
    if isinstance(data, (list, tuple)):
        return [str(item) for item in data]
    return [str(data)]


def _token_value(tokens: list[str], prefix: str) -> str:
    marker = prefix + ":"
    for token in tokens:
        text = str(token)
        if text.startswith(marker):
            value = text[len(marker):]
            return "" if value == "-" else value
    return ""


def _split_decision_status(raw) -> tuple[str, str]:
    """G2: `status` = `action.delivery_kind` (`reply.text`, `react.react`).

    Старые события (до 24.10.2026) писали только action без `.` — читаются
    ровно как раньше: `("reply", "")`. Незнакомый формат не теряется:
    первая часть остаётся действием."""
    text = str(raw or "")
    action, _, kind = text.partition(".")
    return action, kind


async def _event_rows(db, since_ts: int, chat_id: int | None,
                      names: tuple | None = None) -> list[dict]:
    """События окна как словари (`SELECT *`; схема-терпимо)."""
    try:
        sql = "SELECT * FROM mca_events WHERE ts >= ?"
        params: list = [int(since_ts)]
        if names:
            sql += " AND event_name IN (" + ",".join("?" * len(names)) + ")"
            params.extend(names)
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(EVENT_ROWS_MAX)
        cursor = await db.db.execute(sql, tuple(params))
        return [dict(r) for r in await cursor.fetchall() or ()]
    except Exception:
        logger.warning("[w5] events read failed — zeros", exc_info=True)
        return []


# ── оконные COUNT событий ──────────────────────────────────────────────────

async def _events_window(db, since_ts: int, chat_id: int | None) -> dict:
    rows = await _event_rows(db, since_ts, chat_id, INITIATIVE_EVENTS)
    out = {name: 0 for name in INITIATIVE_EVENTS}
    for row in rows:
        name = str(row.get("event_name") or "")
        if name in out:
            out[name] += 1
    return out


async def _opportunities_by_kind(db, since_ts: int,
                                 chat_id: int | None) -> dict:
    """Возможности по видам (stage='opportunity:<kind>:<action>')."""
    rows = await _event_rows(db, since_ts, chat_id, (OPPORTUNITY_EVENT,))
    out: dict[str, int] = {}
    for row in rows:
        stage = str(row.get("stage") or "")
        parts = stage.split(":")
        if len(parts) < 3 or parts[0] != "opportunity" or parts[1] == "none":
            continue
        kind = parts[1] or "unknown"
        out[kind] = out.get(kind, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


async def _decision_rows(db, since_ts: int, chat_id: int | None,
                         limit: int = LIST_LIMIT) -> list[dict]:
    """Последние решения (action/outcome/reason) — без сырого текста."""
    rows = await _event_rows(db, since_ts, chat_id, (DECIDED_EVENT,))
    out: list[dict] = []
    for row in rows[:max(1, int(limit))]:
        code = str(row.get("reason_code") or "")
        tokens = _tokens_of(row)
        action, delivery_kind = _split_decision_status(row.get("status"))
        out.append({
            "ts": _int(row.get("ts")),
            "action": action,
            "delivery_kind": delivery_kind,
            "delivery": _token_value(tokens, "delivery"),
            "target_message_id": _token_value(tokens, "tgt"),
            "target_user_id": _token_value(tokens, "tgt_user"),
            "addressee_user_id": _token_value(tokens, "addr"),
            "correlation_id": (str(row.get("trace_id") or "")
                               or _token_value(tokens, "corr")),
            "outcome": str(row.get("outcome") or ""),
            "reason_code": code,
            "reason_label": obs.reason_label(code),
            "intent_id": _token_value(tokens, "intent"),
            "stage": str(row.get("stage") or ""),
        })
    return out


async def _silence_reasons(db, since_ts: int, chat_id: int | None,
                           limit: int = LIST_LIMIT) -> list[dict]:
    """Распределение причин молчания (решения + отказы до отправки)."""
    rows = await _event_rows(db, since_ts, chat_id, (DECIDED_EVENT,))
    counts: dict[str, int] = {}
    for row in rows:
        outcome = str(row.get("outcome") or "")
        if outcome not in ("silent", "cancelled", "skipped"):
            continue
        code = str(row.get("reason_code") or "") or "reason_not_recorded"
        counts[code] = counts.get(code, 0) + 1
    out = [{"reason_code": code, "label": obs.reason_label(code),
            "count": count}
           for code, count in counts.items()]
    out.sort(key=lambda item: -item["count"])
    return out[:max(1, int(limit))]


async def _action_counts(db, since_ts: int, chat_id: int | None) -> dict:
    rows = await _event_rows(db, since_ts, chat_id, (DECIDED_EVENT,))
    out = {"say": 0, "react": 0, "silent": 0, "cancelled": 0, "other": 0}
    for row in rows:
        # G2: `action.delivery_kind`; старая запись без `.` — только action.
        action, _kind = _split_decision_status(row.get("status"))
        if str(row.get("outcome") or "") == "cancelled":
            out["cancelled"] += 1
            continue
        if action in ("say", "react", "silent"):
            out[action] += 1
        else:
            out["other"] += 1
    return out


async def _last_ts(db, since_ts: int, chat_id: int | None,
                   names: tuple) -> dict:
    rows = await _event_rows(db, since_ts, chat_id, names)
    out = {name: 0 for name in names}
    for row in rows:
        name = str(row.get("event_name") or "")
        if name in out:
            out[name] = max(out[name], _int(row.get("ts")))
    return out


# ── durable-счётчики: оконная дельта по checkpoint-payload ─────────────────

def _payload_counters(row: dict) -> dict:
    try:
        data = json.loads((row.get("payload") or "") or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    counters = data.get("counters")
    return counters if isinstance(counters, dict) else {}


def _job_stamp(row: dict) -> int:
    return _int(row.get("finished_at") or row.get("updated_at")
                or row.get("created_at"), 0)


async def _job_history(db, limit: int = 400) -> list[dict]:
    try:
        cursor = await db.db.execute(
            "SELECT payload, status, finished_at, updated_at, created_at "
            "FROM task_jobs WHERE kind = ? ORDER BY COALESCE(finished_at, "
            "updated_at, created_at) DESC LIMIT ?",
            (obs.OBSERVE_JOB_KIND, max(2, int(limit))))
        return [dict(r) for r in await cursor.fetchall()]
    except Exception:
        logger.warning("[w5] job history read failed", exc_info=True)
        return []


def _window_baseline(rows: list[dict], since_ts: int) -> tuple[dict, str, int]:
    """Базовая точка окна: САМЫЙ СТАРЫЙ прогон внутри окна.

    Так дельта (latest − baseline) описывает ровно окно с точностью до
    шага планировщика, а не «окно + произвольный хвост до предыдущего
    прогона». Покрытие честное: если история наблюдателя не дотягивается
    до начала окна, это видно как ``partial``/``insufficient``.
    """
    if not rows:
        return {}, "insufficient", 0
    inside = [row for row in rows if _job_stamp(row) > int(since_ts)]
    if not inside:
        return {}, "insufficient", 0
    baseline_row = inside[-1]
    delta_span = _job_stamp(rows[0]) - _job_stamp(baseline_row)
    oldest_reaches_back = _job_stamp(rows[-1]) <= int(since_ts)
    coverage = "full" if oldest_reaches_back else "partial"
    return _payload_counters(baseline_row), coverage, delta_span


async def _counter_deltas(db, since_ts: int) -> tuple[dict, str, dict]:
    rows = await _job_history(db)
    if not rows:
        return {}, "insufficient", {}
    newest = _payload_counters(rows[0])
    if len(rows) == 1:
        # единственный прогон: раскладывать накопленное по окну нельзя
        return dict(newest), "insufficient", newest
    baseline, coverage, _span = _window_baseline(rows, since_ts)
    if not baseline:
        return {}, "insufficient", newest
    delta: dict[str, int] = {}
    keys = ("passes", "observed", "eligible", "evals", "opportunities",
            "silent_decisions", "react_decisions", "sent", "intents_created",
            "writer_unavailable", "eval_unavailable", "errors",
            "scan_skipped")
    for key in keys:
        diff = _int(newest.get(key)) - _int(baseline.get(key))
        delta[key] = diff if diff > 0 else 0
    return delta, coverage, newest


async def _eval_skip_delta(db, since_ts: int) -> tuple[dict, str]:
    rows = await _job_history(db)
    if not rows:
        return {}, "insufficient"
    newest = dict(_payload_counters(rows[0]).get("eval_skips") or {})
    if len(rows) == 1:
        return {str(k): _int(v) for k, v in newest.items() if _int(v) > 0}, \
            "insufficient"
    baseline_row_counters, coverage, _span = _window_baseline(rows, since_ts)
    if not baseline_row_counters:
        return {}, "insufficient"
    baseline = dict(baseline_row_counters.get("eval_skips") or {})
    delta: dict[str, int] = {}
    for code, value in newest.items():
        diff = _int(value) - _int(baseline.get(code))
        if diff > 0:
            delta[str(code)] = diff
    return delta, coverage


# ── доставка и манифест ────────────────────────────────────────────────────

async def _delivered_rows(db, since_ts: int, chat_id: int | None) -> list[dict]:
    """Доставленные инициативные сообщения из ledger (R17-safe поля)."""
    out: list[dict] = []
    try:
        sql = ("SELECT output_id, chat_id, tg_message_id, sent_at, "
               "correlation_id, content_hash, delivery_status, "
               "LENGTH(COALESCE(content_text, '')) AS chars "
               "FROM mca_bot_outputs WHERE sent_at >= ? AND output_kind = ?")
        params: list = [int(since_ts), OUTPUT_KIND_INITIATIVE]
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        sql += " ORDER BY sent_at DESC LIMIT 200"
        cursor = await db.db.execute(sql, tuple(params))
        for row in await cursor.fetchall() or ():
            row = dict(row)
            out.append({
                "output_id": _int(row.get("output_id")),
                "chat_id": _int(row.get("chat_id")),
                "message_id": (None if row.get("tg_message_id") is None
                               else _int(row.get("tg_message_id"))),
                "ts": _int(row.get("sent_at")),
                "correlation_id": str(row.get("correlation_id") or ""),
                "content_hash": str(row.get("content_hash") or ""),
                "chars": _int(row.get("chars")),
                "delivery_status": str(row.get("delivery_status") or ""),
            })
    except Exception:
        logger.warning("[w5] ledger read failed — sends empty", exc_info=True)
    return out


async def _manifest_refs(db, since_ts: int, chat_id: int | None) -> dict:
    """Core/Style/identity ревизии доставленных инициатив (по correlation_id).

    Источник — событие ``initiative_delivery_manifest``, которое пишет путь
    отправки инициативы (ревизии из единого Compose/Composer-манифеста).
    Нет события → пустая карта: панель обязана честно сказать «нет данных»,
    а не подставлять текущие значения задним числом."""
    rows = await _event_rows(db, since_ts, chat_id, (MANIFEST_EVENT,))
    refs: dict[str, dict] = {}
    for row in rows:
        tokens = _tokens_of(row)
        parsed = {
            "core_revision": _token_value(tokens, "core"),
            "style_policy_revision": _token_value(tokens, "style"),
            "identity_revision": _token_value(tokens, "identity"),
            "manifest_id": _token_value(tokens, "manifest"),
            "composer": _token_value(tokens, "composer"),
            "delivery": _token_value(tokens, "delivery"),
            "delivery_form": _token_value(tokens, "form"),
            "reply_to": _token_value(tokens, "reply"),
            "delivery_mismatch": _token_value(tokens, "mismatch"),
            "manifest_ts": _int(row.get("ts")),
            "manifest_message_id": None,
        }
        msg_token = _token_value(tokens, "msg")
        if msg_token:
            parsed["manifest_message_id"] = _int(msg_token)
        if not parsed["core_revision"]:
            # fallback: сводка в config_version (старые/усечённые события)
            parsed.update(_parse_manifest_version(
                str(row.get("config_version") or "")))
        correlation = _token_value(tokens, "corr")
        if correlation and correlation not in refs:
            refs[correlation] = parsed
        mid = parsed.get("manifest_message_id")
        if mid:
            refs["msg:%d" % int(mid)] = parsed
    return refs


def _parse_manifest_version(raw: str) -> dict:
    """Сводка `config_version` → словарь (три формата).

    Новый (24.10.2026): `core.<rev>_style.<rev>_ident.<rev>_man.<id>_c.<on>`
    — единственный формат, переживающий R17 code-валидатор (≤64 символа,
    только `[A-Za-z0-9_.:-]`); полные ревизии — в токенах события.
    Старый `core=<rev>;style=...` читается как раньше (обратная
    совместимость уже записанных событий)."""
    out = {"core_revision": "", "style_policy_revision": "",
           "identity_revision": "", "manifest_id": "", "composer": ""}
    text = str(raw or "")
    if not text:
        return out
    keys = {"core": "core_revision", "style": "style_policy_revision",
            "ident": "identity_revision", "identity": "identity_revision",
            "man": "manifest_id", "manifest": "manifest_id",
            "c": "composer", "composer": "composer"}
    if "=" not in text and "_" in text:
        for part in text.split("_"):
            key, _, value = part.partition(".")
            target = keys.get(key.strip())
            value = value.strip()
            if target and value and value != "-":
                out[target] = value
        return out
    if "=" not in text:
        return out
    for part in text.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        target = keys.get(key.strip())
        value = value.strip()
        if target and value and value != "-":
            out[target] = value
    return out


def _manifest_ref_for_row(row: dict, refs: dict) -> dict:
    ref = refs.get(str(row.get("correlation_id") or "")) or {}
    if not ref and row.get("message_id") is not None:
        ref = refs.get("msg:%d" % int(row["message_id"])) or {}
    return ref or {}


def _duplicates(rows: list[dict]) -> int:
    """Сколько доставок продублировали уже отправленный текст (окно)."""
    counts: dict[str, int] = {}
    for row in rows:
        h = str(row.get("content_hash") or "")
        if not h:
            continue
        counts[h] = counts.get(h, 0) + 1
    return sum(max(0, value - 1) for value in counts.values())


async def _latency(db, since_ts: int, chat_id: int | None) -> dict:
    """Задержка «текст сгенерирован → доставлено» по связке намерения."""
    samples: list[int] = []
    generated_rows = await _event_rows(db, since_ts, chat_id,
                                      (WRITER_GENERATED_EVENT,))
    sent_rows = await _event_rows(db, since_ts, chat_id, (SENT_EVENT,))
    generated = {}
    for row in generated_rows:
        intent = _token_value(_tokens_of(row), "intent")
        if intent:
            generated[intent] = _int(row.get("ts"))
    for row in sent_rows:
        intent = _token_value(_tokens_of(row), "intent")
        if not intent:
            continue
        start = generated.get(intent)
        if start is None:
            continue
        delta = _int(row.get("ts")) - int(start)
        if delta >= 0:
            samples.append(delta)
    samples.sort()
    if not samples:
        return {"p50": None, "max": None, "samples": 0}
    return {"p50": samples[(len(samples) - 1) // 2], "max": samples[-1],
            "samples": len(samples)}


# ── сборка окна ────────────────────────────────────────────────────────────

async def collect_window(db, *, hours: int = 24, chat_id: int | None = None,
                         now: int | None = None) -> dict:
    """Честная воронка за окно (нули — как нули). Никогда не бросает."""
    now_ts = _now(now)
    hours = 48 if int(hours or 24) >= 48 else 24
    since = now_ts - hours * 3600
    events = await _events_window(db, since, chat_id)
    counters, coverage, _latest = await _counter_deltas(db, since)
    eval_skips, _skip_cov = await _eval_skip_delta(db, since)
    by_kind = await _opportunities_by_kind(db, since, chat_id)
    decisions = await _decision_rows(db, since, chat_id)
    silence = await _silence_reasons(db, since, chat_id)
    delivered_rows = await _delivered_rows(db, since, chat_id)
    manifest_refs = await _manifest_refs(db, since, chat_id)
    sends: list[dict] = []
    for row in delivered_rows[:LIST_LIMIT]:
        ref = _manifest_ref_for_row(row, manifest_refs)
        sends.append({
            "ts": row["ts"],
            "message_id": row["message_id"],
            "correlation_id": row["correlation_id"],
            "chars": _int(row.get("chars")),
            "output_kind": OUTPUT_KIND_INITIATIVE,
            "delivery_status": row["delivery_status"],
            "core_revision": str(ref.get("core_revision") or ""),
            "style_policy_revision": str(ref.get("style_policy_revision") or ""),
            "identity_revision": str(ref.get("identity_revision") or ""),
            "manifest_id": str(ref.get("manifest_id") or ""),
            "composer": str(ref.get("composer") or ""),
            # G1/G7 (аудит 24.10.2026): фактическая форма доставки и цель
            # reply из существующего события манифеста (без сырого текста).
            "delivery": str(ref.get("delivery") or ""),
            "delivery_form": str(ref.get("delivery_form") or ""),
            "reply_to": str(ref.get("reply_to") or ""),
            "delivery_mismatch": str(ref.get("delivery_mismatch") or ""),
            "ledger_output_id": row["output_id"],
        })
    latency = await _latency(db, since, chat_id)
    last = await _last_ts(db, since, chat_id, (
        SCAN_EVENT, OPPORTUNITY_EVENT, DECIDED_EVENT, SENT_EVENT))
    all_actions = await _action_counts(db, since, chat_id)
    refusals = [row for row in decisions
                if str(row.get("outcome") or "") == "cancelled"]
    delivered_events = int(events.get(SENT_EVENT) or 0)
    delivered_ledger = len(delivered_rows)
    delivered_counters = int(counters.get("sent") or 0)
    # Источник истины доставки — ledger; события и durable-счётчики идут
    # рядом и служат honest-фолбэком, когда ledger выключен/пуст.
    delivered = (delivered_ledger or delivered_events
                 or delivered_counters)
    return {
        "hours": hours,
        "coverage": coverage,
        "coverage_note": (
            "история прогонов наблюдателя дотягивается до начала окна"
            if coverage == "full" else
            "история прогонов наблюдателя короче окна — числа покрывают "
            "меньшее время"),
        "scans": int(counters.get("passes") or 0),
        "scan_events": int(events.get(SCAN_EVENT) or 0),
        "observed": int(counters.get("observed") or 0),
        "eligible": int(counters.get("eligible") or 0),
        "evals": int(counters.get("evals") or 0),
        "opportunities": int(counters.get("opportunities") or 0),
        "opportunities_by_kind": by_kind,
        "decisions": all_actions,
        "silence_by_reason": silence,
        "intents_created": int(counters.get("intents_created") or 0),
        "writer_generated": int(events.get(WRITER_GENERATED_EVENT) or 0),
        "writer_unavailable": int(counters.get("writer_unavailable") or 0),
        "send_attempts": int(events.get(RECHECK_PASSED_EVENT) or 0),
        "delivered": delivered,
        "delivered_ledger": delivered_ledger,
        "delivered_events": delivered_events,
        "delivered_counters": delivered_counters,
        "refusals": len(refusals) or int(all_actions.get("cancelled") or 0),
        "duplicates": _duplicates(delivered_rows),
        "eval_skips": eval_skips,
        "errors": int(counters.get("errors") or 0),
        "diagnostics": int(events.get(DIAGNOSTIC_EVENT) or 0),
        "latency_seconds": latency,
        "last": {
            "scan_ts": _int(last.get(SCAN_EVENT), 0),
            "opportunity_ts": _int(last.get(OPPORTUNITY_EVENT), 0),
            "decision_ts": _int(last.get(DECIDED_EVENT), 0),
            "delivered_ts": (sends[0]["ts"] if sends else 0),
            "send_attempt_ts": 0,
        },
        "decisions_recent": decisions,
        "refusals_recent": refusals[:LIST_LIMIT],
        "sends": sends,
        # EVOL-014: отдельный объект. Цифры мемов не входят в delivered/
        # opportunities текстовой инициативы.
        "meme": _meme_snapshot(db, chat_id),
    }


def _meme_snapshot(db, chat_id: int | None) -> dict:
    """Снимок мемов. Ошибка чтения не роняет воронку инициативы."""
    try:
        from services import meme_initiative as meme
        return meme.analytics_snapshot(meme.open_ledger(db), chat_id=chat_id)
    except Exception:
        logger.warning("[w5] meme snapshot failed — empty", exc_info=True)
        return {
            "output_kind": "meme_initiative",
            "separate_from_initiative": True,
            "coverage": "unavailable",
            "counters": {},
            "skip_reasons": {},
            "attempts": [],
            "quota": None,
        }


# ── вердикт: health ≠ outcome ──────────────────────────────────────────────

def activity_verdict(window: dict, *, live_messages: int | None,
                     master_on: bool, chat_on: bool | None,
                     liveness: dict | None = None) -> dict:
    """Отделить «воронка жива» от «инициатива реально доставлена» (SOUL-18.5).

    Возвращает честный вердикт с предупреждением и рекомендацией; нули
    никогда не превращаются в «здорово»."""
    opp = _int(window.get("opportunities"))
    scans = _int(window.get("scans"))
    observed = _int(window.get("observed"))
    delivered = _int(window.get("delivered"))
    silent = _int((window.get("decisions") or {}).get("silent"))
    busy = live_messages is not None and \
        _int(live_messages) >= BUSY_MESSAGES_PER_DAY
    base = {
        "state": "no_data", "level": "info", "title": "", "warning": "",
        "recommendation": "", "reasons": [],
        "live_messages": live_messages,
        "thresholds": {"live_messages_busy": BUSY_MESSAGES_PER_DAY,
                       "silent_streak": SILENT_STREAK_MIN},
        "health": _health(liveness or {}, window),
        "counters": {"scans": scans, "observed": observed,
                     "opportunities": opp, "delivered": delivered,
                     "silent": silent},
        "silent_streak": _silent_streak(window.get("decisions_recent") or []),
    }
    base["reasons"] = _top_reasons(window)
    if not master_on or chat_on is False:
        base.update({
            "state": "disabled", "level": "warn",
            "title": "Наблюдение выключено",
            "warning": ("Инициатива не работает: мастер-гейт или разрешение "
                        "чата выключены — отсутствие сообщений ожидаемо, "
                        "воронка пуста по этой причине."),
            "recommendation": ("Включить наблюдателя инициативы (модуль "
                               "«Инициатива») и разрешение для этого чата."),
        })
        return base
    if not scans and not observed and not live_messages:
        base.update({
            "state": "no_data", "level": "info",
            "title": "Данных наблюдения нет",
            "warning": "",
            "recommendation": ("Проверить, что планировщик обслуживания "
                               "выполняется: тик наблюдателя идёт каждые "
                               "5 минут, но до первого прохода данных нет."),
        })
        return base
    if opp == 0 and busy:
        base.update({
            "state": "observer_silent_live_chat", "level": "warn",
            "title": "Возможности не находятся при живом чате",
            "warning": ("Чат активен (%d сообщений за сутки), но возможности "
                        "не находятся: это признак задушенных ворот "
                        "(scope, порог оценки, пауза), а не «всё хорошо»."
                        % _int(live_messages)),
            "recommendation": ("Сверить распределение пропусков ниже: если "
                               "доминирует «в чате пока мало новых "
                               "сообщений» или «интервал между проверками "
                               "ещё не прошёл» — задать мягкую цель проверки "
                               "или снизить порог; если «в окне было "
                               "обращение к боту» — чат разговаривает с "
                               "ботом напрямую, инициатива там не нужна."),
        })
        return base
    if opp == 0:
        base.update({
            "state": "low_activity", "level": "info",
            "title": "Низкая активность — молчание ожидаемо",
            "warning": "",
            "recommendation": ("Поводов не было, и живого трафика мало: "
                               "наблюдение не обязано писать. Пороги можно "
                               "не менять."),
        })
        return base
    if delivered == 0:
        base.update({
            "state": "opportunities_no_messages", "level": "warn",
            "title": "Возможности есть, сообщений нет",
            "warning": ("За окно найдено возможностей: %d, решений молчанием: "
                        "%d, доставлено: 0. Воронка жива, но инициативных "
                        "сообщений не было." % (opp, silent)),
            "recommendation": _no_message_recommendation(window),
        })
        return base
    base.update({
        "state": "ok", "level": "ok",
        "title": "Инициатива доставляется",
        "warning": "",
        "recommendation": "",
    })
    return base


def health_only(window: dict, liveness: dict | None = None) -> dict:
    """Только техническое здоровье (тик/прогоны) — БЕЗ вывода об отправках."""
    return _health(liveness or {}, window)


def _health(liveness: dict, window: dict) -> dict:
    ts = liveness.get("ts")
    ts_int = _int(ts, 0) if ts is not None else None
    fresh = (ts_int is not None and (_now() - ts_int) < HEARTBEAT_STALE_SECONDS)
    return {
        "heartbeat_ok": bool(fresh),
        "last_tick_ts": ts_int,
        "last_tick_status": str(liveness.get("status") or ""),
        "jobs_processed": _int(window.get("scans")),
        "note": "heartbeat≠outcome: тики и прогоны не являются отправкой",
    }


def _silent_streak(rows: list[dict]) -> int:
    streak = 0
    for row in rows:
        if str(row.get("outcome") or "") == "silent" or \
                str(row.get("action") or "") == "silent":
            streak += 1
        else:
            break
    return streak


def _top_reasons(window: dict, limit: int = LIST_LIMIT) -> list[dict]:
    counts: dict[str, int] = {}
    for item in window.get("silence_by_reason") or []:
        code = str(item.get("reason_code") or "")
        counts[code] = counts.get(code, 0) + _int(item.get("count"))
    for code, value in (window.get("eval_skips") or {}).items():
        counts[str(code)] = counts.get(str(code), 0) + _int(value)
    out = [{"reason_code": code, "label": obs.reason_label(code),
            "count": count}
           for code, count in counts.items() if count > 0]
    out.sort(key=lambda item: -item["count"])
    return out[:max(1, int(limit))]


def _no_message_recommendation(window: dict) -> str:
    reasons = _top_reasons(window, limit=3)
    if not reasons:
        return ("Посмотреть решения по чату: причин не записано — проверить "
                "путь decision → writer → recheck.")
    top = reasons[0]
    return ("Главная причина: %s (%d). Проверить плечи writer/recheck и "
            "причины решений ниже; при недоступном писателе повод "
            "откладывается в намерение, а не теряется." % (
                top["label"], top["count"]))


# ── полный payload для MiniApp ─────────────────────────────────────────────

async def collect_vitality(db, *, chat_id: int | None = None, hours: int = 24,
                           now: int | None = None,
                           liveness: dict | None = None,
                           llm_available: bool | None = None,
                           writer_available: bool | None = None) -> dict:
    """Одно место чтения диагностики инициативы (MiniApp: Статус).

    Возвращает воронку окна, отдельный вердикт ``health≠outcome``, реальное
    состояние ворот чата и компактные списки последних решений/отказов/
    доставок с ревизиями Core/Style. Никогда не бросает."""
    now_ts = _now(now)
    hours = 48 if int(hours or 24) >= 48 else 24
    master_on = bool(obs.observer_enabled())
    chat_on: bool | None = None
    if chat_id is not None:
        try:
            chat_on = bool(await obs.chat_observer_enabled(chat_id))
        except Exception:
            chat_on = None
    live: int | None = None
    if chat_id is not None:
        live = await obs.live_messages(db, chat_id, window_seconds=hours * 3600,
                                       now=now_ts)
    window = await collect_window(db, hours=hours, chat_id=chat_id, now=now_ts)
    verdict = activity_verdict(window, live_messages=live, master_on=master_on,
                               chat_on=chat_on, liveness=liveness or {})
    gates: dict = {}
    if chat_id is not None:
        try:
            gates = await obs.chat_block_state(
                db, chat_id, now=now_ts, llm_available=llm_available,
                writer_available=writer_available)
        except Exception:
            logger.warning("[w5] block state failed", exc_info=True)
            gates = {}
    return {
        "available": True,
        "now_ts": now_ts,
        "hours": hours,
        "chat_id": chat_id,
        "chat_scoped": chat_id is not None,
        "scope": {"master": master_on, "chat_enabled": chat_on},
        "windows": {("%dh" % hours): window},
        "window": window,
        "activity": verdict,
        "gates": gates,
        "decisions": list(window.get("decisions_recent") or []),
        "refusals": list(window.get("refusals_recent") or []),
        "sends": list(window.get("sends") or []),
    }


# ═════════════════════════════════════════════════════════════════════════════
# SOUL-18.4: «Проверить инициативу» — безопасный прогон до mock send
# ═════════════════════════════════════════════════════════════════════════════

#: Текст превью для владельца (не в логи и не в события).
PREVIEW_CHARS = 300
#: Защита от параллельных проверок (одна за раз).
_check_lock = None


class MockSendBot:
    """Бот-двойник: НИ ОДНОГО сетевого вызова.

    Используется безопасной проверкой инициативы: цепочка проходит целиком
    (оценка → решение → Writer → форма → recheck → чанки), а «отправка»
    фиксируется здесь. Ни одного сообщения в рабочую группу."""

    def __init__(self) -> None:
        self.id = None
        self.sent: list[dict] = []
        self.texts: list[str] = []

    async def send_message(self, chat_id, text, **kwargs):
        payload = str(text or "")
        self.texts.append(payload)
        self.sent.append({"chat_id": _int(chat_id), "chars": len(payload)})
        return _MockMessage()


class _MockMessage:
    """Сообщение-двойник: у него нет реального message_id (честно)."""

    message_id = None


def _get_check_lock():
    global _check_lock
    if _check_lock is None:
        import asyncio
        _check_lock = asyncio.Lock()
    return _check_lock


def _suppressed_emitters() -> tuple:
    """Эмиттеры воронки, которые mock-прогон обязан не вызывать.

    Диагностика не имеет права подменять реальные счётчики (SOUL-18.5:
    «инициативная воронка не подменяет отправки»)."""
    return ("note_decision", "note_writer_generated", "note_recheck_passed",
            "note_initiative_sent", "note_delivery_manifest")


def _noop_emitter(*args, **kwargs) -> None:
    """Заглушка эмиттеров на время mock-прогона (вызовы синхронные)."""
    return None


async def run_check(db, *, chat_id: int, hours: int = 24,
                    publish: bool = False, confirm_publish: bool = False,
                    writer_service=None, llm=None, bot=None,
                    now: int | None = None) -> dict:
    """Полный trace проверки инициативы без публикации по умолчанию.

    Один прогон: состояние ворот → окно → семантическая оценка (1 LLM-вызов)
    → решение → Writer (1 LLM-вызов) → проход формы → recheck → mock send.
    Ни одна отправка не выполняется, воронка не пишется. Реальная отправка —
    только при ``publish`` И включённой оси ``initiative_diagnostics_publish_
    enabled`` И ``confirm_publish=True`` (явное разрешение владельца).
    Никогда не бросает."""
    started = _now(now)
    trace: list[dict] = []
    out: dict[str, Any] = {
        "available": True, "chat_id": _int(chat_id), "hours": hours,
        "published": False, "publish_mode": "mock",
        "publish_disabled_reason": "", "trace": trace,
        "verdict": None, "decision": None,
        "writer": {"available": False},
        "mock_send": {"attempted": False, "would_send_chars": 0,
                      "preview": "", "preview_truncated": False, "chunks": 0,
                      "published": False},
        "llm_calls": 0, "duration_ms": 0,
    }
    if chat_id is None or int(chat_id) >= 0:
        trace.append(_step("chat", "blocked", "not_group",
                           "Инициатива работает только в групповых чатах"))
        out["duration_ms"] = max(0, _now() - started) * 1000
        return out
    from services import mca_gates
    from services import mca_intents as mi
    from services import direct_chat_service as dcs

    async with _get_check_lock():
        publish_axis = False
        try:
            publish_axis = bool(
                mca_gates.initiative_diagnostics_publish_enabled())
        except Exception:
            publish_axis = False

        # ── 1) ворота чата (read-only, без LLM) ──────────────────────────
        try:
            gates = await obs.chat_block_state(
                db, int(chat_id), now=started,
                llm_available=llm is not None,
                writer_available=writer_service is not None)
        except Exception:
            gates = {}
        blocked = [i for i in (gates.get("items") or [])
                   if i.get("status") == "block"]
        trace.append(_step(
            "gates", "blocked" if blocked else "ok",
            (blocked[0].get("reason_code") if blocked else ""),
            ("Сейчас мешает: " + str(blocked[0].get("label") or ""))
            if blocked else "Явных блокировок нет",
            value=(gates.get("state") or {}).get("pending")))
        out["gates"] = {"blocked_now": bool(gates.get("blocked_now")),
                        "items": gates.get("items") or [],
                        "effective": gates.get("effective") or {},
                        "soft_targets": gates.get("soft_targets") or {},
                        "state": gates.get("state") or {}}

        # ── 2) окно наблюдения (durable, без LLM) ────────────────────────
        runner = obs.InitiativeObserverRunner(db, bot=bot, llm=llm,
                                             writer_service=writer_service,
                                             alias_resolver=getattr(
                                                 writer_service, "aliases",
                                                 None))
        # INIT-ARCH-FIX (ТЗ §1.3): dry-run показывает окно ТОГО ЖЕ резолвера,
        # что боевой путь (база 10 → рост по накоплению → кап 200).
        try:
            window_limit = await runner._window_messages(  # noqa: SLF001
                int(chat_id), 0)
        except Exception:
            window_limit = obs.EVAL_WINDOW_BASE_MESSAGES
        try:
            rows = await runner._window_rows(int(chat_id), 0)  # noqa: SLF001
        except Exception:
            rows = []
        trace.append(_step(
            "window", "ok" if rows else "skipped",
            "" if rows else "not_enough_messages",
            "Свежих реплик в окне: %d" % len(rows), value=len(rows),
            limit=int(window_limit)))
        if not rows:
            out["duration_ms"] = max(0, _now() - started) * 1000
            return out

        # ── 3) семантическая оценка (ровно 1 LLM-вызов) ──────────────────
        if llm is None:
            trace.append(_step("evaluate", "skipped", "llm_unavailable",
                               "Оценщик недоступен — проверка невозможна"))
            out["duration_ms"] = max(0, _now() - started) * 1000
            return out
        try:
            verdict = await runner._evaluate_window(int(chat_id), rows)
        except Exception:
            verdict = None
        out["llm_calls"] = 1
        if verdict is None:
            trace.append(_step("evaluate", "error",
                               "semantic_eval_unavailable",
                               "Оценка не вернула разборчивый вердикт"))
            out["duration_ms"] = max(0, _now() - started) * 1000
            return out
        out["verdict"] = {
            "opportunity": bool(verdict.get("opportunity")),
            "kind": str(verdict.get("kind") or ""),
            "action": str(verdict.get("action") or ""),
            "horizon": str(verdict.get("horizon") or ""),
            "rationale": str(verdict.get("rationale") or ""),
        }
        trace.append(_step(
            "evaluate", "ok" if verdict.get("opportunity") else "skipped",
            "" if verdict.get("opportunity") else "no_opportunity",
            "Вердикт: %s / %s" % (verdict.get("kind") or "-",
                                  verdict.get("action") or "-")))
        if not verdict.get("opportunity"):
            out["duration_ms"] = max(0, _now() - started) * 1000
            return out

        # ── 4) решение → Writer → форма → recheck → mock send ────────────
        mock_bot = MockSendBot()
        style_seen: dict = {}
        original_style = getattr(dcs, "_style_initiative_text", None)

        async def _style_probe(text, cid, plan=None):
            styled, outcome = await original_style(text, cid, plan)
            style_seen["outcome"] = str(getattr(outcome, "applied", ""))
            style_seen["chars_in"] = len(str(text or ""))
            style_seen["chars_out"] = len(str(styled or ""))
            return styled, outcome

        suppressed: dict = {}
        use_mock = not (publish and publish_axis and confirm_publish)
        if use_mock:
            for name in _suppressed_emitters():
                if hasattr(mi, name):
                    suppressed[name] = getattr(mi, name)
                    setattr(mi, name, _noop_emitter)
            if original_style is not None:
                dcs._style_initiative_text = _style_probe
        from services import publication_coordination as _pubmod
        publication = None
        result: dict = {}
        try:
            intent_kind = ("open_dispute"
                           if str(verdict.get("kind")) == "dispute"
                           else "topic_interest")
            candidate = mi.candidate_from_trigger(
                trigger_kind="new_message", chat_id=int(chat_id),
                kind=intent_kind,
                source="memory", goal=str(verdict.get("goal") or ""),
                priority=1,
                reason_code="observer_%s" % (verdict.get("kind") or "unknown"))
            situation = mi.InitiativeSituation(
                trigger_kind="new_message", chat_id=int(chat_id),
                direct_pending=False, same_event_pending=False,
                sensitive_moment=False, relations_ok=True,
                bot_replied_recently=False, reply_needed=False,
                topic_open=True, open_intent_ids=None,
                requested_source="diagnostics")
            # P0A-INIT (REV-INIT-FIX): dry-run обязан идти ТОЙ ЖЕ цепочкой,
            # что боевой путь наблюдателя, — контекст эфемерного повода
            # собирает тот же производитель. Без него Writer/L1 видели
            # пустую цель («цель не указана») и проверка показывала неправду.
            opportunity_row = obs.build_opportunity_row(
                int(chat_id), kind=intent_kind,
                goal=str(verdict.get("goal") or ""),
                fallback=str(verdict.get("kind") or "development"),
                rows=rows, now=started,
                addressee_user_id=verdict.get("addressee_user_id"),
                rationale=verdict.get("rationale"))
            # ── INIT-COORD (03.11.2026) §3.5: координация публикации ТЕМ ЖЕ
            # швом, что у боевого пути (precheck → бронь → publish_guard →
            # release). Реальный прогон занимает бронь — иначе он невидим для
            # мема; dry-run бронь НЕ занимает (`claim=False`): он ничего не
            # публикует и состояние чата не трогает.
            publication = await _pubmod.open_text_publication(
                db, int(chat_id), holder_ref="diag%s" % _int(started),
                claim=not use_mock)
            out["publication"] = publication.as_dict()
            result = await dcs.handle_initiative(
                bot=(mock_bot if use_mock else bot), chat_id=int(chat_id),
                situation=situation, candidates=[candidate], db=db,
                writer_service=writer_service,
                correlation_id="diag%s" % _int(started),
                opportunity_row=opportunity_row,
                publish_guard=publication.guard) or {}
        except Exception:
            logger.warning("[w5] initiative check failed", exc_info=True)
            result = {"status": "error"}
        finally:
            if publication is not None:
                await publication.close(
                    published=(str((result or {}).get("status") or "") == "sent")
                    and not use_mock)
            for name, func in suppressed.items():
                setattr(mi, name, func)
            if original_style is not None:
                dcs._style_initiative_text = original_style

        status = str(result.get("status") or "error")
        decision = result.get("decision")
        reason_code = str(result.get("reason_code")
                          or getattr(decision, "reason_code", "") or "")
        out["decision"] = {
            "action": str(getattr(decision, "action", "") or ""),
            "reason_code": reason_code,
            "reason_label": obs.reason_label(reason_code),
            "status": status,
            "delivery_kind": str(result.get("delivery_kind") or ""),
        }
        if out["llm_calls"] == 1 and status in ("sent", "silent", "cancelled",
                                                "writer_failed"):
            out["llm_calls"] = 2
        trace.append(_step(
            "decision", "ok" if status == "sent" else "skipped",
            reason_code,
            "Решение: %s (%s)" % (out["decision"]["action"] or "-", status)))
        trace.append(_step(
            "writer", "ok" if result.get("generated") else "skipped",
            "" if result.get("generated") else "writer_failed",
            "Текст сгенерирован" if result.get("generated")
            else "Текст не сгенерирован"))
        if style_seen:
            trace.append(_step(
                "style", "ok", "", "Проход формы выполнен",
                value=style_seen.get("chars_out")))
        chunks = int(result.get("chunks") or len(mock_bot.sent) or 0)
        out["writer"] = {
            "available": bool(writer_service is not None),
            "generated": bool(result.get("generated")),
            "style": dict(style_seen),
        }
        if use_mock:
            text = str(mock_bot.texts[-1]) if mock_bot.texts else ""
            out["mock_send"] = {
                "attempted": bool(mock_bot.sent),
                "would_send_chars": (mock_bot.sent[0]["chars"]
                                     if mock_bot.sent else 0),
                "preview": text[:PREVIEW_CHARS],
                "preview_truncated": len(text) > PREVIEW_CHARS,
                "chunks": chunks,
                "published": False,
            }
            trace.append(_step(
                "mock_send", "ok" if mock_bot.sent else "skipped",
                "" if mock_bot.sent else (reason_code or "no_send"),
                ("Готово к отправке: %d символов в %d чанк(ах), НЕ отправлено"
                 % (out["mock_send"]["would_send_chars"], chunks))
                if mock_bot.sent else "Отправка не состоялась бы"))
        else:
            out["published"] = status == "sent"
            out["publish_mode"] = "real"
            trace.append(_step(
                "real_send", "ok" if status == "sent" else "skipped",
                reason_code,
                "РЕАЛЬНАЯ отправка с разрешения владельца: %s" % status))
        if publish and not (publish_axis and confirm_publish):
            out["publish_disabled_reason"] = (
                "publish_axis_off" if not publish_axis else "confirm_required")
        _emit_check_marker(chat_id=int(chat_id), published=out["published"],
                           decision=out["decision"])
        out["duration_ms"] = max(0, _now() - started) * 1000
        return out


def _emit_check_marker(*, chat_id: int, published: bool,
                       decision: dict) -> None:
    """Единственное событие проверки (явно не подменяет воронку)."""
    try:
        from services import mca_events
        mca_events.emit_mca_event(
            CHECK_EVENT,
            outcome="success" if published else "skipped",
            component="initiative", chat_id=int(chat_id),
            stage="diagnostics:%s" % ("published" if published else "mock"),
            reason_code=("initiative_check_published" if published
                         else "initiative_check_dry_run"),
            status=str(decision.get("action") or "") or None)
    except Exception:
        pass


def _step(stage: str, status: str, reason_code: str, label: str,
          *, value=None, limit=None) -> dict:
    return {"stage": str(stage), "status": str(status),
            "reason_code": str(reason_code or ""),
            "label": str(label or ""), "value": value, "limit": limit}


# ═════════════════════════════════════════════════════════════════════════════
# MEME-INIT-DIAG (P9): диагностика ПО КАЖДОМУ МЕХАНИЗМУ — одна точка для UI
# ═════════════════════════════════════════════════════════════════════════════
#: Версия формы ответа: потребитель (P4) читает её, чтобы не угадывать.
DIAG_SCHEMA_VERSION = 1
MECHANISM_TEXT = "text_initiative"
MECHANISM_MEME = "meme"

DATA_OK = "ok"
DATA_NO_DATA = "no_data"

#: Машинные коды «чего не хватает» в ЭТОМ ответе. Это НЕ `reason_code`
#: пайплайна: они не пишутся в события/`mca_events`/payload и не входят в
#: общий словарь `initiative_observer.REASON_LABELS`. Назначение — объяснить
#: пустое поле, а не изобрести новую причину поведения механизма.
NO_DATA_READ_FAILED = "read_failed"
NO_DATA_NO_OBSERVER_PAYLOAD = "no_observer_payload"
NO_DATA_NEVER_CHECKED = "never_checked"
NO_DATA_NO_DECISION = "no_decision_recorded"
NO_DATA_NO_RANDOM = "no_random_trace"
NO_DATA_NO_MEME_STATE = "no_meme_state"
NO_DATA_NO_ATTEMPTS = "no_attempts_journal"
NO_DATA_CHAT_REQUIRED = "chat_not_selected"

#: Остаток кулдауна считается ТОЛЬКО по собственному кулдауну механизма.
#: TTL брони (90/120/600 с) — аренда отправки, а не пауза механизма.
COOLDOWN_SCOPE = "mechanism_own"

#: Рассуждение о конфликте публикаций — единственный источник `publication`.
CONFLICT_CLEAR = "clear"
CONFLICT_ACTIVE = "conflict"
CONFLICT_UNKNOWN = "unknown"

#: КОНТРАКТ ДЛЯ P4 (админка): набор ключей блока механизма.
#: Все ключи присутствуют ВСЕГДА; «нет данных» — это ``null``/``None``,
#: ``available=false`` и код в ``no_data_reasons``, а не 0.
MECHANISM_BLOCK_FIELDS = (
    "mechanism", "output_kind", "source", "available", "data_state",
    "no_data_reasons", "ready", "ready_reason", "last_check_ts",
    "next_check_ts", "next_check_basis", "random", "conditions", "stages",
    "skip", "skip_recorded", "cooldown", "quota", "publication", "blocking",
)
#: Поля вложенных объектов (их нет, если объект ``null``).
DRAW_FIELDS = (
    "performed", "outcome", "value", "hit", "probability", "purpose",
    "draw_id", "source", "source_impl", "provider", "selected_source",
    "fallback", "fallback_reason", "policy_version", "attempts", "reason",
    "reason_label", "no_draw_reason", "ts",
)
PUBLICATION_FIELDS = (
    "available", "coordination", "degraded", "degraded_reason", "conflict",
    "conflict_state", "ok", "reason", "reason_label", "detail", "state",
    "holder_kind", "claimed_by", "other_kind", "other_age_seconds",
    "interval_seconds", "manual_priority_until", "checked_at",
)
COOLDOWN_FIELDS = ("scope", "own_seconds", "remaining_seconds", "basis",
                   "basis_ts")
QUOTA_FIELDS = ("scope", "limit", "used", "remaining", "unlimited",
                "limit_reached", "available", "next_reset")
SKIP_FIELDS = ("code", "label", "origin")


def _int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stamp_or_none(value) -> int | None:
    """Метка времени: ``0``/пусто → ``None`` («никогда»), а не 1970-01-01."""
    stamp = _int_or_none(value)
    return stamp if stamp is not None and stamp > 0 else None


def _scalar_dict(value) -> dict | None:
    """Только плоские скаляры: тексты/промпты/вложенные блобы не проходят.

    Условия механизма — это флаги/счётчики/коды; всё остальное в диагностику
    не попадает даже если механизм записал это в свой payload.
    """
    if not isinstance(value, dict) or not value:
        return None
    out: dict = {}
    for key, item in value.items():
        if item is None or isinstance(item, (bool, int, float, str)):
            out[str(key)] = item
    return out or None


def _unique(codes: list[str]) -> list[str]:
    seen: list[str] = []
    for code in codes:
        text = str(code or "")
        if text and text not in seen:
            seen.append(text)
    return seen


def draw_block(trace) -> dict | None:
    """Разложить трассировку случайного решения. Пусто → ``None``.

    Честные правила (§8 P8, п.4): `reason="probability_one"` значит, что draw
    НЕ выполнялся — это не «выигранный случай», поэтому `hit` не выдаётся.
    В ответ идут только поля ``DRAW_TRACE_FIELDS`` (R17-safe: коды/числа/ID).
    """
    if not isinstance(trace, dict) or not trace:
        return None
    data = {key: trace.get(key) for key in obs.DRAW_TRACE_FIELDS}
    reason = str(data.get("reason") or "")
    value = _float_or_none(data.get("value"))
    no_draw_reason = ""
    if reason == obs.DRAW_PROBABILITY_ONE:
        no_draw_reason = obs.DRAW_PROBABILITY_ONE
    elif data.get("deferred"):
        no_draw_reason = reason
    elif value is None:
        no_draw_reason = reason
    performed = not no_draw_reason
    return {
        "performed": performed,
        "outcome": "draw" if performed else "no_draw",
        "value": (value if performed else None),
        "hit": (bool(data.get("hit")) if performed else None),
        "probability": _float_or_none(data.get("probability")),
        "purpose": str(data.get("purpose") or ""),
        "draw_id": (str(data.get("draw_id") or "") or None),
        # Фактически использованный источник (выбранный — отдельным полем).
        "source": (str(data.get("source") or "") or None),
        "source_impl": (str(data.get("source_impl") or "") or None),
        "provider": (str(data["provider"]) if data.get("provider") else None),
        "selected_source": (str(data.get("selected_source") or "") or None),
        "fallback": bool(data.get("fallback_reason")),
        "fallback_reason": (str(data["fallback_reason"])
                            if data.get("fallback_reason") else None),
        "policy_version": (str(data.get("policy_version") or "") or None),
        "attempts": _int_or_none(data.get("attempts")) or 0,
        "reason": reason,
        "reason_label": (obs.reason_label(reason) if reason else ""),
        "no_draw_reason": no_draw_reason,
        "ts": _stamp_or_none(data.get("ts")),
    }


def publication_block(view, *, checked_at=None) -> dict | None:
    """Единственная правда о конфликте публикаций.

    Источник — снимок `PublicationCoordinator.precheck` (та же бронь, что у
    боевого пути). ``coordination="degraded"`` — это ДЕГРАДАЦИЯ, а не «всё
    хорошо»: брони нет, конфликт НЕИЗВЕСТЕН (``conflict: null``), а не «нет».
    """
    if not isinstance(view, dict) or not view:
        return None
    coordination = str(view.get("coordination") or "ok")
    degraded = coordination == "degraded"
    ok = view.get("ok")
    ok_bool = None if ok is None else bool(ok)
    if degraded:
        conflict = None
    elif ok_bool is None:
        conflict = None
    else:
        conflict = not ok_bool
    if conflict is None:
        conflict_state = CONFLICT_UNKNOWN
    else:
        conflict_state = CONFLICT_ACTIVE if conflict else CONFLICT_CLEAR
    reason = str(view.get("reason") or "")
    return {
        "available": not degraded,
        "coordination": coordination,
        "degraded": degraded,
        # precheck помечает degraded ровно одним случаем — отсутствием таблицы.
        "degraded_reason": (str(view.get("degraded_reason") or "")
                            or ("claim_table_absent" if degraded else "")),
        "conflict": conflict,
        "conflict_state": conflict_state,
        "ok": (None if degraded else ok_bool),
        "reason": reason,
        "reason_label": (obs.reason_label(reason) if reason else ""),
        "detail": str(view.get("detail") or ""),
        "state": str(view.get("state") or ""),
        "holder_kind": str(view.get("holder_kind")
                           or view.get("holder") or ""),
        "claimed_by": str(view.get("holder") or ""),
        "other_kind": str(view.get("other_kind") or ""),
        "other_age_seconds": _int_or_none(view.get("other_age_seconds")),
        "interval_seconds": _int_or_none(view.get("interval_seconds")),
        "manual_priority_until": _stamp_or_none(
            view.get("manual_priority_until")),
        "checked_at": _stamp_or_none(view.get("checked_at") or checked_at),
    }


def cooldown_block(own_seconds, *, now: int, basis_ts=None,
                   basis: str = "") -> dict:
    """Собственный остаток кулдауна механизма (НЕ TTL брони).

    ``remaining_seconds == 0`` — законный ноль (пауза истекла либо публикаций
    ещё не было, см. `basis`), а не «нет данных»: «никогда не проверяли»
    видно по ``last_check_ts is None``, это разные поля.
    """
    own = _int_or_none(own_seconds)
    stamp = _stamp_or_none(basis_ts)
    remaining: int | None = None
    if own is None:
        remaining = None
    elif own <= 0:
        remaining = 0
    elif stamp is None:
        remaining = 0
        basis = basis or "no_prior_publication"
    else:
        remaining = max(0, int(own) - max(0, int(now) - int(stamp)))
    return {
        "scope": COOLDOWN_SCOPE,
        "own_seconds": own,
        "remaining_seconds": remaining,
        "basis": basis,
        "basis_ts": stamp,
    }


def quota_block(*, limit, used, available: bool | None = None,
                next_reset=None, zero_means_unlimited: bool = True) -> dict:
    """Собственная квота механизма (сутки): лимит/использовано/остаток.

    ``zero_means_unlimited=True`` (текстовая инициатива: ``day_cap <= 0`` —
    «без дневного капа»), ``False`` (мемы: ``daily_limit <= 0`` — механизм
    фактически остановлен, боевой гейт отдаёт ``daily_quota_reached``).
    Нет данных → соответствующие поля ``null``, а не нули.
    """
    cap = _int_or_none(limit)
    spent = _int_or_none(used)
    unlimited = bool(cap is not None and cap <= 0 and zero_means_unlimited)
    limit_reached = bool(
        cap is not None and spent is not None and (
            spent >= cap if cap > 0 else not zero_means_unlimited))
    remaining: int | None = None
    if cap is not None and spent is not None:
        remaining = max(0, cap - spent) if cap > 0 else 0
    return {
        "scope": COOLDOWN_SCOPE,
        "limit": cap,
        "used": spent,
        "remaining": remaining,
        "unlimited": unlimited,
        "limit_reached": limit_reached,
        "available": available,
        "next_reset": next_reset,
    }


def skip_block(code, origin: str, label=None) -> dict | None:
    """Причина пропуска — ТОЛЬКО существующий код механизма (не выдуманный).

    ``origin`` говорит, откуда взята причина: ``gate``/``availability``/
    ``quota``/``cooldown``/``quiet_hours``/``publication`` — «почему не
    сработает сейчас», ``payload_state``/``journal`` — что записал последний
    проход. Пустой код → ``None`` («причины нет», а не «причина неизвестна»).
    """
    text = str(code or "")
    if not text:
        return None
    return {"code": text, "label": str(label or obs.reason_label(text)),
            "origin": str(origin or "")}


def _blocking_block(items) -> dict | None:
    """Что мешает механизму СЕЙЧАС (коды ворот, без смешивания механизмов)."""
    if not isinstance(items, list) or not items:
        return None
    blocked: list[dict] = []
    warned: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        if status not in ("block", "warn"):
            continue
        row = {"gate": str(item.get("gate") or ""), "status": status,
               "reason_code": str(item.get("reason_code") or ""),
               "label": str(item.get("label") or "")}
        (blocked if status == "block" else warned).append(row)
    return {"blocked": blocked, "warned": warned}


async def text_mechanism_diagnostics(db, chat_id, *,
                                     now: int | None = None) -> dict:
    """Диагностика ТЕКСТОВОЙ инициативы (существующие payload/бронь).

    Числа берутся у того же read-model, что показывает ворота чата
    (`initiative_observer.chat_block_state`), поэтому диагностика не выводит
    своё мнение о состоянии механизма. Порядок причин «сейчас мешает» — тот
    же порядок ворот, что у боевого пути. Никогда не бросает.
    """
    now_ts = _now(now)
    cid = _int_or_none(chat_id)
    if cid is None:
        return _no_chat_block(MECHANISM_TEXT, obs.INITIATIVE_OUTPUT_KINDS[0])
    reasons: list[str] = []
    try:
        view = await obs.chat_block_state(db, cid, now=now_ts)
    except Exception:
        logger.warning("[diag] text mechanism state failed", exc_info=True)
        view = {}
    if not isinstance(view, dict):
        view = {}
    state = view.get("state") if isinstance(view.get("state"), dict) else {}
    effective = (view.get("effective")
                 if isinstance(view.get("effective"), dict) else {})
    if not state:
        reasons.append(NO_DATA_READ_FAILED)
    decision = (state.get("last_decision")
                if isinstance(state.get("last_decision"), dict) else {})
    age_eval = _int_or_none(state.get("last_eval_age_seconds"))

    last_check = _stamp_or_none(decision.get("ts"))
    if last_check is None and age_eval is not None:
        last_check = now_ts - max(0, age_eval)
    if last_check is None:
        # «Никогда»: проверок и решений не было — это не 01.01.1970 и не 0.
        reasons.append(NO_DATA_NEVER_CHECKED)
    if not decision:
        reasons.append(NO_DATA_NO_DECISION)
    available = last_check is not None

    interval = _int(effective.get("eval_min_interval_seconds"), 0)
    if last_check is None:
        # Проверки ещё не было → и «следующей» даты нет (None, не now).
        next_check, next_basis = None, NO_DATA_NEVER_CHECKED
    else:
        next_check = _stamp_or_none(state.get("next_eval_ts"))
        next_basis = "eval_interval" if interval > 0 else "every_pass"
        if next_check is None:
            next_basis = "unknown"

    draw = draw_block(decision.get("random"))
    if draw is None:
        reasons.append(NO_DATA_NO_RANDOM)

    age_out = _int_or_none(state.get("last_initiative_output_age_seconds"))
    cooldown = cooldown_block(
        effective.get("min_gap_seconds"), now=now_ts,
        basis_ts=((now_ts - max(0, age_out)) if age_out is not None else None),
        basis=("last_initiative_publication" if age_out is not None
               else "no_prior_publication"))
    quota = quota_block(limit=effective.get("max_replies_per_day"),
                        used=state.get("sent_in_window"),
                        zero_means_unlimited=True)

    blocking = _blocking_block(view.get("items"))
    skip_recorded = skip_block(decision.get("skip_reason"), "payload_state",
                               label=decision.get("skip_label"))
    # «Сейчас мешает» — первый заблокированный гейт боевого порядка; иначе
    # остаётся записанная причина последнего прохода (она может быть старой и
    # потому лежит отдельным полем `skip_recorded`).
    skip = None
    for item in (blocking or {}).get("blocked") or ():
        if item.get("reason_code"):
            skip = skip_block(item["reason_code"], "gate",
                              label=item.get("label"))
            break
    ready = None if blocking is None else not blocking.get("blocked")

    return {
        "mechanism": MECHANISM_TEXT,
        "output_kind": obs.INITIATIVE_OUTPUT_KINDS[0],
        "source": "initiative_observer.chat_block_state",
        "available": available,
        "data_state": DATA_OK if available else DATA_NO_DATA,
        "no_data_reasons": _unique(reasons),
        "ready": ready,
        "ready_reason": str((skip or {}).get("code") or ""),
        "last_check_ts": last_check,
        "next_check_ts": next_check,
        "next_check_basis": next_basis,
        "random": draw,
        "conditions": _scalar_dict(decision.get("conditions")),
        "stages": None,
        "skip": skip,
        "skip_recorded": skip_recorded,
        "cooldown": cooldown,
        "quota": quota,
        "publication": publication_block(state.get("publication"),
                                         checked_at=now_ts),
        "blocking": blocking,
    }


def _no_chat_block(mechanism: str, output_kind: str) -> dict:
    """Блок-заглушка «чат не выбран»: полная форма, ни одного выдуманного 0."""
    return {
        "mechanism": mechanism,
        "output_kind": output_kind,
        "source": "",
        "available": False,
        "data_state": DATA_NO_DATA,
        "no_data_reasons": [NO_DATA_CHAT_REQUIRED],
        "ready": None,
        "ready_reason": "",
        "last_check_ts": None,
        "next_check_ts": None,
        "next_check_basis": NO_DATA_CHAT_REQUIRED,
        "random": None,
        "conditions": None,
        "stages": None,
        "skip": None,
        "skip_recorded": None,
        "cooldown": cooldown_block(None, now=0),
        "quota": quota_block(limit=None, used=None),
        "publication": None,
        "blocking": None,
    }


async def _meme_precheck(db, chat_id: int, ledger, now_ts: int) -> dict:
    """Снимок брони публикации глазами МЕМ-механизма (та же координация)."""
    from services import publication_coordination as pubmod
    coordinator = pubmod.PublicationCoordinator(
        db, store=pubmod.open_store(db, path=getattr(ledger, "path", None)))
    return await coordinator.precheck(
        int(chat_id), pubmod.KIND_MEME_INITIATIVE, now=now_ts,
        interval_seconds=await pubmod.resolve_cross_type_interval(chat_id))


async def meme_mechanism_diagnostics(db, chat_id, *, now: int | None = None,
                                     settings=None, ledger=None,
                                     image_health=None,
                                     publication=None) -> dict:
    """Диагностика МЕМ-механизма (журнал попыток + payload прохода + бронь).

    Отдельный блок: ничего не берётся из блока текстовой инициативы и ничего
    в него не подмешивается. Порядок причин «сейчас мешает» — тот же порядок
    гейтов, что у боевого `consider_chat`. Никогда не бросает.
    """
    from services import meme_initiative as meme
    now_ts = _now(now)
    cid = _int_or_none(chat_id)
    if cid is None:
        return _no_chat_block(MECHANISM_MEME, meme.OUTPUT_KIND)
    reasons: list[str] = []
    ledger = ledger if ledger is not None else meme.open_ledger(db)
    if ledger is None:
        reasons.append(NO_DATA_NO_ATTEMPTS)

    payload = await obs.latest_observe_payload(db)
    if not payload:
        reasons.append(NO_DATA_NO_OBSERVER_PAYLOAD)
    meme_state = (payload.get("meme")
                  if isinstance(payload.get("meme"), dict) else {})
    if not meme_state:
        reasons.append(NO_DATA_NO_MEME_STATE)
    chats = (meme_state.get("chats")
             if isinstance(meme_state.get("chats"), dict) else {})
    entry = chats.get(str(cid)) if isinstance(chats, dict) else None
    entry = dict(entry) if isinstance(entry, dict) else {}

    if isinstance(publication, dict) and publication:
        pub_view: dict = dict(publication)
    else:
        try:
            pub_view = await _meme_precheck(db, cid, ledger, now_ts)
        except Exception:
            logger.warning("[diag] meme publication precheck failed",
                           exc_info=True)
            pub_view = {"ok": True, "coordination": "degraded"}

    try:
        cfg = (settings if settings is not None
               else await meme.load_settings(chat_id))
    except Exception:
        cfg = None
    try:
        avail = await meme.availability(
            cid, settings=cfg, ledger=ledger, image_health=image_health,
            publication=pub_view, now=now_ts)
    except Exception:
        logger.warning("[diag] meme availability failed", exc_info=True)
        avail = {}
    diag = (avail.get("diagnostics")
            if isinstance(avail.get("diagnostics"), dict) else {})

    last_attempt: dict = {}
    eligible_facts: dict = {}
    if ledger is not None:
        try:
            rows = ledger.attempts(cid, limit=len(meme.STAGES))
        except Exception:
            rows = []
        rows = [row for row in rows or () if isinstance(row, dict)]
        if rows:
            last_attempt = dict(rows[0])
        else:
            reasons.append(NO_DATA_NO_ATTEMPTS)
        for row in rows:
            if str(row.get("stage") or "") == meme.STAGE_ELIGIBLE:
                eligible_facts = meme.parse_attempt_facts(row)
                break
    last_attempt_ts = _stamp_or_none(last_attempt.get("ts"))
    last_attempt_reason = str(last_attempt.get("reason_code") or "")
    last_facts = meme.parse_attempt_facts(last_attempt) if last_attempt else {}

    last_check = _stamp_or_none(entry.get("last_check_ts")) or last_attempt_ts
    if last_check is None:
        reasons.append(NO_DATA_NEVER_CHECKED)
    available = last_check is not None

    own_cooldown = _int_or_none(getattr(cfg, "cooldown_seconds", None))
    basis_ts = None
    if ledger is not None:
        try:
            basis_ts = _stamp_or_none(ledger.last_provider_ts(cid))
        except Exception:
            basis_ts = None
    cooldown = cooldown_block(
        own_cooldown, now=now_ts, basis_ts=basis_ts,
        basis=("last_provider_call" if basis_ts
               else "no_prior_provider_call"))
    cooldown_active = bool(
        own_cooldown is not None and own_cooldown > 0 and basis_ts is not None
        and (now_ts - int(basis_ts)) < int(own_cooldown))

    next_check = _stamp_or_none(entry.get("next_check_ts"))
    if next_check is not None:
        next_basis = "payload_state"
    elif own_cooldown is not None and basis_ts:
        # Пауза истекла или ещё идёт — дата считается от последнего вызова
        # провайдера (тот же базис, что у боевого гейта), а не от брони.
        next_check = int(basis_ts) + int(own_cooldown)
        next_basis = "cooldown"
    else:
        next_check, next_basis = None, "unknown"

    trace = (entry.get("random") or diag.get("random")
             or eligible_facts.get("random") or last_facts.get("random"))
    draw = draw_block(trace)
    if draw is None:
        reasons.append(NO_DATA_NO_RANDOM)

    # ── собственная квота (сутки чата; тот же расчёт, что у боевого гейта) ──
    quota = quota_block(limit=None, used=None)
    quiet_active = False
    try:
        stamp = datetime.fromtimestamp(int(now_ts), timezone.utc)
        day = meme.day_window(cid, stamp)
        limit = (_int_or_none(getattr(cfg, "daily_limit", None))
                 if cfg is not None else None)
        if limit is not None:
            view = meme.quota_view(ledger, chat_id=cid, day=day, limit=limit)
            quota = quota_block(
                limit=view.get("limit"), used=view.get("spent"),
                available=bool(view.get("available")),
                next_reset=view.get("next_reset"), zero_means_unlimited=False)
        quiet_active = bool(cfg is not None and meme.quiet_hours_block(
            getattr(cfg, "quiet_hours", ""), stamp,
            str(getattr(day, "timezone_name", "UTC"))))
    except Exception:
        logger.warning("[diag] meme quota/quiet read failed", exc_info=True)

    # ── причина пропуска: ТЕКУЩЕЕ состояние в порядке боевых гейтов ─────────
    avail_reason = str(avail.get("reason") or "")
    skip = None
    if avail_reason and avail_reason != "ok":
        skip = skip_block(avail_reason, "availability")
    elif quota.get("limit_reached"):
        skip = skip_block(meme.SKIP_QUOTA, "quota")
    elif cooldown_active:
        skip = skip_block(meme.SKIP_COOLDOWN, "cooldown")
    elif quiet_active:
        skip = skip_block(meme.SKIP_QUIET, "quiet_hours")
    elif pub_view.get("ok") is False:
        # Код берётся из причины брони (боевая карта), не из нового словаря.
        pub_reason = str(pub_view.get("reason") or "")
        skip = skip_block(
            meme.SKIP_PUBLICATION_IN_FLIGHT
            if pub_reason == "publication_in_flight"
            else meme.SKIP_PUBLICATION_CONFLICT, "publication")
    skip_recorded = None
    if str(entry.get("reason") or "") in meme.SKIP_REASONS:
        skip_recorded = skip_block(entry.get("reason"), "payload_state")
    elif last_attempt_reason in meme.SKIP_REASONS:
        skip_recorded = skip_block(last_attempt_reason, "journal")

    return {
        "mechanism": MECHANISM_MEME,
        "output_kind": meme.OUTPUT_KIND,
        "source": "meme_initiative attempt journal + meme.chats + claim",
        "available": available,
        "data_state": DATA_OK if available else DATA_NO_DATA,
        "no_data_reasons": _unique(reasons),
        "ready": (bool(avail.get("available")) if avail else None),
        "ready_reason": avail_reason,
        "last_check_ts": last_check,
        "next_check_ts": next_check,
        "next_check_basis": next_basis,
        "random": draw,
        "conditions": _scalar_dict(diag.get("conditions")),
        "stages": _scalar_dict(entry.get("conditions")),
        "skip": skip,
        "skip_recorded": skip_recorded,
        "cooldown": cooldown,
        "quota": quota,
        "publication": publication_block(pub_view, checked_at=now_ts),
        "blocking": None,
    }


async def collect_mechanism_diagnostics(db, chat_id, *,
                                        now: int | None = None,
                                        meme_settings=None, ledger=None,
                                        image_health=None,
                                        publication=None) -> dict:
    """P9: ДВА отдельных блока диагностики для админки (P4) — одна точка.

    Форма ответа (``schema_version = 1``)::

        {
          "schema_version": 1,
          "generated_at": <int>,
          "chat_id": <int>,
          "text_initiative": {...},   # блок текстовой инициативы
          "meme": {...},              # блок мемов (независимый)
          "degraded": ["meme", ...],  # у кого coordination="degraded"
        }

    Честные правила (их нельзя нарушать потребителю):
    * ``available = false`` / ``data_state = "no_data"`` и ``null`` в полях —
      это «НЕТ ДАННЫХ», а не нули и не «всё хорошо»;
    * ``last_check_ts = null`` значит «проверок не было НИКОГДА»
      (в журнале это ``0``); ``cooldown.remaining_seconds = 0`` — законный
      ноль, см. ``cooldown.basis``;
    * ``publication`` — единственная правда о конфликте публикаций;
      ``conflict = null`` при ``coordination = "degraded"`` = неизвестно;
    * ``random.performed = false`` + ``no_draw_reason = "probability_one"``
      значит, что draw НЕ выполнялся (а не «случай сработал»);
    * ``cooldown`` считается только по собственному кулдауну механизма
      (``scope = "mechanism_own"``), TTL брони 90/120/600 с — не кулдаун.

    Карта полей блока механизма (``MECHANISM_BLOCK_FIELDS``; все ключи есть
    всегда, «нет данных» = ``null``)::

        mechanism            "text_initiative" | "meme" — блоки не смешиваются
        output_kind          "initiative_reply" | "meme_initiative"
        source               откуда прочитано (строка-источник)
        available            есть ли данные о механизме (не «работает ли»)
        data_state           "ok" | "no_data"
        no_data_reasons      коды отсутствующих данных (см. NO_DATA_*)
        ready                может ли механизм сработать сейчас; null=N/A
        ready_reason         код причины, почему нет ("" если нечего сказать)
        last_check_ts        int | null  — null = НИКОГДА (не 0 и не 1970)
        next_check_ts        int | null  — null = нет рассчитанной даты
        next_check_basis     "payload_state"|"cooldown"|"eval_interval"|
                             "every_pass"|"unknown"|"never_checked"|
                             "chat_not_selected"
        random               объект DRAW_FIELDS | null (draw не записан)
        conditions           плоские скаляры выполненных условий | null
        stages               счётчики стадий мема | null (у текста стадий нет)
        skip                 причина «сейчас не сработает» (SKIP_FIELDS)|null
        skip_recorded        что записал последний проход | null
        cooldown             COOLDOWN_FIELDS (always) — свой остаток
        quota                QUOTA_FIELDS (always) — своя квота суток
        publication          PUBLICATION_FIELDS | null (не проверялась)
        blocking             {"blocked":[...], "warned":[...]} | null

    ``skip.origin``: ``gate``/``availability``/``quota``/``cooldown``/
    ``quiet_hours``/``publication`` — текущее состояние; ``payload_state``/
    ``journal`` — запись прошлого прохода (может быть устаревшей, поэтому
    текущая причина и запись разведены в разные поля).

    ``publication`` (``PUBLICATION_FIELDS``): ``coordination`` = "ok"|
    "degraded" (деградация ⇒ ``available=false``, ``conflict=null``,
    ``conflict_state="unknown"``); ``conflict`` — единственный признак
    конфликта; ``holder_kind`` — механизм, ДЛЯ которого спросили бронь,
    ``claimed_by`` — кто реально держит бронь сейчас; ``other_kind``/
    ``other_age_seconds``/``interval_seconds`` — кто публиковал и сколько
    ещё действует межтиповой интервал; ``manual_priority_until`` — до какого
    момента действует приоритет ручного `/meme` (это НЕ кулдаун механизма).

    ``quota`` (``QUOTA_FIELDS``): ``limit_reached`` — упёрлись в предел
    (у мемов ``limit<=0`` тоже предел: механизм выключен лимитом; у текста
    ``cap<=0`` — «без капа», поэтому ``unlimited=true``).

    Никогда не бросает: сбой чтения даёт честный ``no_data``-блок.
    Ничего не пишет, ничего не отправляет, LLM не вызывает.
    """
    now_ts = _now(now)
    text_block = await text_mechanism_diagnostics(db, chat_id, now=now_ts)
    meme_block = await meme_mechanism_diagnostics(
        db, chat_id, now=now_ts, settings=meme_settings, ledger=ledger,
        image_health=image_health, publication=publication)
    degraded = []
    for block in (text_block, meme_block):
        pub = block.get("publication") or {}
        if pub.get("degraded"):
            degraded.append(str(block.get("mechanism") or ""))
    return {
        "schema_version": DIAG_SCHEMA_VERSION,
        "generated_at": now_ts,
        "chat_id": _int_or_none(chat_id),
        "text_initiative": text_block,
        "meme": meme_block,
        "degraded": _unique(degraded),
    }
