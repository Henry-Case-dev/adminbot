"""EXP-E-LAG-SCHED: due-гейт review ставится по ИЗМЕРЕННОМУ лагу (P0 25.11.2026).

Живой замер (`plans/features/smart-execution-reliability-01/evidence/exp-e/
lag-live-check-2026-11-25.md`) доказал: механизм догоняющих проходов внутри
job'а работает, но сам проход не планировался 17.5 ч. `semantic_backlog()`
опирался на transient `semantic_pending`/устаревший `lag_actionable_rows`;
истёкший `retry_at` пересчитывался в 0 и давал молчаливый `not_due` при
измеренном lag 2 033 541 строка.

Тесты дискриминирующие: на базе 5621bda8d (до фикса) (a), (b), (d), (e)
падают, (c) — защитный (границы/нет busy-loop).

TEST-LIFECYCLE: CONTRACT owner=EXP-E-LAG-01 / amendment §B (owner input
2026-11-22-p0-embed-503-failover.md)
"""
import json
import logging
import time
import uuid

import pytest

from services import hot_config
from services import mca_experience_jobs as mj
from services.database import DatabaseService


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


def _hot(values: dict | None = None):
    return _FakeHot(values or {})


class _FakeLLM:
    """Валидный пустой ответ: курсор двигается по прочитанному окну."""

    def __init__(self):
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return "[]"


async def _db(tmp_path, name="exp_e_lag_sched.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _msg(db, *, chat_id=-100, user_id=42, ts=None) -> int:
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, NULL, ?, 'text', 'u', 0, NULL)",
        (int(user_id), int(chat_id), "реплика для разбора семантики",
         int(ts if ts is not None else time.time())))
    await db.db.commit()
    return int(cursor.lastrowid)


def _lag(*, rows, by_chat, actionable=0, max_id=0):
    lag = {
        "available": True, "ts": int(time.time()), "rows": int(rows),
        "chats": len(by_chat), "actionable_rows": int(actionable),
        "actionable_chats": 1 if actionable else 0,
        "measured_chats": len(by_chat), "failed_chats": 0,
        "partial": False, "oldest_ts": int(time.time()) - 86400 * 90,
        "age_seconds": 86400 * 90, "worst_chat": -100,
        "worst_rows": int(rows), "worst_cursor": 0,
        "worst_max_id": int(max_id),
    }
    if by_chat is not None:
        lag["rows_by_chat"] = {str(k): int(v) for k, v in by_chat.items()}
    return lag


def _seed_payload(*, cursor, max_id, lag, retry=None, pending=None,
                  watermark=None, fresh=None):
    payload = {
        "cursor_feedback_rowid": 0,
        "cursor_message_rowid": 0,
        "link_scan_application_id": 0,
        mj.SEMANTIC_WATERMARK_KEY: (int(max_id) if watermark is None
                                    else int(watermark)),
        mj.SEMANTIC_PENDING_KEY: dict(pending or {}),
        mj.SEMANTIC_PENDING_SINCE_KEY: {},
        mj.SEMANTIC_LAST_TS_KEY: {},
        mj.SEMANTIC_STATE_VERSION_KEY: mj.SEMANTIC_STATE_VERSION,
        mj.SEMANTIC_RETRY_KEY: dict(retry or {}),
        mj.SEMANTIC_LAG_KEY: lag,
        "counters": mj.default_counters(),
        f"{mj.SEMANTIC_CURSOR_PREFIX}-100": int(cursor),
    }
    if fresh is not None:
        payload[mj.SEMANTIC_FRESH_KEY] = fresh
    return payload


async def _seed_review_job(db, payload, *, finished_at=None) -> str:
    now = int(time.time()) if finished_at is None else int(finished_at)
    job_id = f"seed-{uuid.uuid4().hex[:10]}"
    await db.db.execute(
        "INSERT INTO task_jobs (job_id, owner, kind, payload, status, attempt, "
        "max_attempts, created_at, updated_at, finished_at) "
        "VALUES (?, ?, ?, ?, 'completed', 1, 3, ?, ?, ?)",
        (job_id, mj.REVIEW_OWNER, mj.REVIEW_JOB_KIND, json.dumps(payload),
         now, now, now))
    await db.db.commit()
    return job_id


async def _set_payload(db, job_id, payload) -> None:
    await db.db.execute(
        "UPDATE task_jobs SET payload = ? WHERE job_id = ?",
        (json.dumps(payload), job_id))
    await db.db.commit()


async def _latest_payload(db) -> dict:
    cursor = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE kind = ? "
        "ORDER BY COALESCE(finished_at, updated_at, created_at) DESC, "
        "rowid DESC LIMIT 1", (mj.REVIEW_JOB_KIND,))
    row = await cursor.fetchone()
    return json.loads(row["payload"] or "{}")


def _cursor(payload, chat_id=-100) -> int:
    return int(payload.get(f"{mj.SEMANTIC_CURSOR_PREFIX}{chat_id}") or 0)


# ═══ (a) Измеренный лаг с пустым pending сам планирует проход ═══════════════

@pytest.mark.asyncio
async def test_a_large_measured_lag_empty_pending_schedules_pass(tmp_path):
    """lag_rows>0 (per-chat) + `semantic_pending`={} должен дать проход.

    Старый код брал только `actionable_rows`/`lag_actionable_rows` из
    снимка: при нулевых счётчиках он возвращал `not_due` при реальном
    отставании. Гейт обязан опираться на ИЗМЕРЕННЫЙ лаг, а не на устаревший
    счётчик (прод-форма 25.11.2026: pending=0, actionable=0, lag=2 033 541).
    """
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 1,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    db = await _db(tmp_path, "lag_a.db")
    try:
        ids = [await _msg(db) for _ in range(120)]
        payload = _seed_payload(
            cursor=0, max_id=ids[-1],
            lag=_lag(rows=2033541, by_chat={-100: 2033459}, actionable=0,
                     max_id=ids[-1]))
        await _seed_review_job(db, payload)

        backlog = await mj.semantic_backlog(db)
        assert backlog["rows"] > 0, (
            "измеренный лаг при пустом pending обязан быть планируемым")
        assert backlog["lag_ready_rows"] > 0
        assert backlog["reason"] in ("measured_lag", "retry_due")

        llm = _FakeLLM()
        status = await mj.tick_experience_review(db, llm=llm)
        assert status == "completed", "проход должен быть поставлен и выполнен"
        assert llm.calls >= 1
        after = await _latest_payload(db)
        assert _cursor(after) > 0, "курсор реально продвинулся по данным"
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ (b) Истёкший retry_at даёт проход (прод-состояние 25.11.2026) ═════════

@pytest.mark.asyncio
async def test_b_expired_retry_at_produces_pass(tmp_path):
    """pending=0, actionable=0, lag>0, retry_at в прошлом → pass, не not_due.

    Это точная форма живого замера: единственный отстающий чат был в
    backoff на момент замера (`lag_actionable_rows=0`), а к моменту тика
    срок `retry_at` уже истёк. Старый код пересчитывал `next_retry_at`
    только для БУДУЩИХ retry_at → 0 → молчаливый `not_due` 17.5 ч.
    """
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 1,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    db = await _db(tmp_path, "lag_b.db")
    try:
        ids = [await _msg(db) for _ in range(60)]
        now = int(time.time())
        payload = _seed_payload(
            cursor=0, max_id=ids[-1],
            lag=_lag(rows=2033541, by_chat={-100: 2033459}, actionable=0,
                     max_id=ids[-1]),
            retry={"-100": {"attempts": 1,
                            "retry_at": now - 17 * 3600,
                            "reason": "parse:json_error"}})
        await _seed_review_job(db, payload)

        backlog = await mj.semantic_backlog(db)
        assert backlog["retry_due_chats"] == 1
        assert backlog["rows"] > 0, "истёкший retry не должен становиться not_due"
        assert backlog["reason"] == "retry_due"

        llm = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        assert llm.calls >= 1
        after = await _latest_payload(db)
        assert _cursor(after) > 0
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ (c) Нет лага / весь лаг на bounded backoff → not_due (нет busy-loop) ══

@pytest.mark.asyncio
async def test_c_no_lag_and_deferred_lag_stay_not_due(tmp_path):
    """Честный ноль и будущий retry не порождают пустые проходы."""
    db = await _db(tmp_path, "lag_c.db")
    try:
        ids = [await _msg(db) for _ in range(5)]
        now = int(time.time())
        job_id = await _seed_review_job(db, _seed_payload(
            cursor=ids[-1], max_id=ids[-1],
            lag=_lag(rows=0, by_chat={}, actionable=0, max_id=ids[-1])))

        backlog = await mj.semantic_backlog(db)
        assert backlog["rows"] == 0
        assert backlog["reason"] == "no_lag"

        llm = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "not_due"
        assert llm.calls == 0

        # Лаг есть, но единственный отстающий чат — на будущем backoff.
        await _set_payload(db, job_id, _seed_payload(
            cursor=0, max_id=ids[-1],
            lag=_lag(rows=5, by_chat={-100: 5}, actionable=0,
                     max_id=ids[-1]),
            retry={"-100": {"attempts": 1, "retry_at": now + 900,
                            "reason": "truncated_reasoning"}}))
        backlog = await mj.semantic_backlog(db)
        assert backlog["rows"] == 0
        assert backlog["reason"] == "deferred"
        assert backlog["next_retry_at"] == now + 900

        assert await mj.tick_experience_review(db, llm=llm) == "not_due"
        assert llm.calls == 0, "отложенный чат не должен долбить LLM каждый тик"
    finally:
        await db.close()


# ═══ (d) Причина тика наблюдаема в журнале (не молчаливый not_due) ═════════

@pytest.mark.asyncio
async def test_d_tick_logs_observable_reason(tmp_path, caplog):
    """Каждый тик пишет status+reason; not_due и due различимы строкой лога."""
    logger_name = "services.mca_experience_jobs"
    db = await _db(tmp_path, "lag_d.db")
    try:
        ids = [await _msg(db) for _ in range(40)]
        now = int(time.time())
        job_id = await _seed_review_job(db, _seed_payload(
            cursor=ids[-1], max_id=ids[-1],
            lag=_lag(rows=0, by_chat={}, actionable=0, max_id=ids[-1])))
        with caplog.at_level(logging.INFO, logger=logger_name):
            assert await mj.tick_experience_review(db) == "not_due"
        assert "status=not_due" in caplog.text
        assert "reason=no_lag" in caplog.text

        caplog.clear()
        await _set_payload(db, job_id, _seed_payload(
            cursor=0, max_id=ids[-1],
            lag=_lag(rows=40, by_chat={-100: 40}, actionable=0,
                     max_id=ids[-1]),
            retry={"-100": {"attempts": 1, "retry_at": now - 60,
                            "reason": "parse:json_error"}}))
        with caplog.at_level(logging.INFO, logger=logger_name):
            status = await mj.tick_experience_review(db, llm=_FakeLLM())
        assert status == "completed"
        assert "status=due" in caplog.text
        assert "reason=retry_due" in caplog.text
        assert "lag_ready_rows=40" in caplog.text
    finally:
        await db.close()


# ═══ (e) Устаревший retry без работы не крутит пустые проходы ══════════════

@pytest.mark.asyncio
async def test_e_stale_expired_retry_is_bounded(tmp_path):
    """Истёкший retry без оставшихся строк даёт ровно один пустой проход.

    Истёкший retry обязан разрешать проход (§2), но запись, за которой уже
    нет работы, убирается — иначе гейт планировал бы пустой проход каждый тик.
    """
    db = await _db(tmp_path, "lag_e.db")
    try:
        ids = [await _msg(db) for _ in range(3)]
        now = int(time.time())
        await _seed_review_job(db, _seed_payload(
            cursor=ids[-1], max_id=ids[-1],
            lag=_lag(rows=0, by_chat={}, actionable=0, max_id=ids[-1]),
            retry={"-100": {"attempts": 5, "retry_at": now - 60,
                            "reason": "read_error"}}))
        backlog = await mj.semantic_backlog(db)
        assert backlog["reason"] == "retry_due"

        llm = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _latest_payload(db)
        assert payload[mj.SEMANTIC_RETRY_KEY] == {}, "устаревший retry убран"

        assert await mj.tick_experience_review(db, llm=llm) == "not_due"
        assert llm.calls == 0
    finally:
        await db.close()
