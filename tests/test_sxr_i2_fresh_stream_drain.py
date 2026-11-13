"""SXR-I2 — fresh stream lag: реальный дренаж семантического бэклога опыта.

Владельческий дефект I2 (production recon 14.11.2026):
`experience.fresh_stream_lag` показывал lag_rows=14 399 при фактически
2 059 418 строках после курсора; курсор двигался ровно +50 за прогон
(≈4.8k/сутки) при поступлении ~7.2k/сутки — backlog не сходился никогда.

Покрытие контракта:
  * дренаж: один прогон исполняет НЕСКОЛЬКО батчей и уходит дальше 50 строк
    до пустого бэклога или реального бюджета (не «один батч за проход»);
  * durable-прогресс курсора: рестарт не откатывает позицию;
  * нет потери/дублей/систематического пропуска на многобатчевом дренаже;
  * одиночная невалидная/непригодная строка не останавливает дренаж;
  * изоляция чатов: битый ответ одного чата не блокирует остальные;
  * crash/restart между батчами: checkpoint каждого батча, interrupted-job
    наследуется, повтор идемпотентен по dedup_key;
  * прогон ограничен реальным бюджетом (батчи + wall-clock);
  * lag_rows — расстояние курсора до данных, а не счётчик pending; порог
    warning НЕ поднят (запрещённый способ «исправления»).

TEST-LIFECYCLE: CONTRACT owner=SXR-I2
"""
import json
import time

import pytest

from services import hot_config
from services import mca_events, mca_gates
from services import mca_experience_jobs as mj
from services.database import DatabaseService
from services.task_supervisor import TaskJobStore


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


@pytest.fixture(autouse=True)
def _fast_validation(monkeypatch):
    monkeypatch.setattr(mca_gates, "lesson_min_independent_episodes",
                        lambda: 1)


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


def _hot(values: dict | None = None):
    return _FakeHot(values or {})


class _FakeLLM:
    """Пустой валидный ответ; считает вызовы и отправленные строки."""

    def __init__(self):
        self.calls = 0
        self.batches: list[set[int]] = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.batches.append(_msg_ids_in_prompt(messages))
        return "[]"


class _EchoLLM(_FakeLLM):
    """Возвращает один durable-кандидат на первый msg_id батча."""

    async def generate(self, messages, **kwargs):
        self.calls += 1
        ids = sorted(_msg_ids_in_prompt(messages))
        self.batches.append(set(ids))
        if not ids:
            return "[]"
        first = ids[0]
        cand = {"kind": "topic_pattern", "msg_ids": [first],
                "subject_user_id": 42, "confidence": "high",
                "epistemic": "fact", "topic": f"t{first}",
                "pref_token": None}
        return json.dumps([cand], ensure_ascii=False)


class _Crash(BaseException):
    """Жёсткое падение процесса (не ловится `except Exception` в job)."""


class _CrashLLM(_EchoLLM):
    def __init__(self, crash_on_call: int):
        super().__init__()
        self._crash_on = int(crash_on_call)

    async def generate(self, messages, **kwargs):
        self.calls += 1
        if self.calls == self._crash_on:
            raise _Crash("simulated process crash")
        ids = sorted(_msg_ids_in_prompt(messages))
        self.batches.append(set(ids))
        if not ids:
            return "[]"
        first = ids[0]
        return json.dumps([{"kind": "topic_pattern", "msg_ids": [first],
                            "subject_user_id": 42, "confidence": "high",
                            "epistemic": "fact", "topic": f"t{first}",
                            "pref_token": None}], ensure_ascii=False)


class _ChatAwareLLM:
    """Чат -100 → невалидный ответ; остальные → валидный пустой."""

    def __init__(self):
        self.calls = 0
        self.batches: list[set[int]] = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        ids = _msg_ids_in_prompt(messages)
        self.batches.append(set(ids))
        content = str(messages[1]["content"])
        if "chat:-100" in content:
            return "извините, не могу вернуть json"
        return "[]"


def _msg_ids_in_prompt(messages) -> set[int]:
    try:
        content = str(messages[1]["content"])
    except (KeyError, IndexError, TypeError):
        return set()
    out = set()
    for chunk in content.split("[msg:")[1:]:
        try:
            out.add(int(chunk.split(" ")[0]))
        except (TypeError, ValueError):
            continue
    return out


async def _db(tmp_path, name="sxr_i2.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _msg(db, *, chat_id=-100, user_id=42, text, ts=None,
               media_type="text") -> int:
    ts = int(time.time()) if ts is None else int(ts)
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, NULL, ?, ?, 'u', 0, NULL)",
        (user_id, chat_id, text, ts, media_type))
    await db.db.commit()
    return cursor.lastrowid


async def _payload_of(db) -> dict:
    cursor = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE kind = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (mj.REVIEW_JOB_KIND,))
    row = await cursor.fetchone()
    return json.loads(row["payload"] or "{}")


async def _next_pass(db) -> None:
    await db.db.execute(
        "UPDATE task_jobs SET status = 'completed', finished_at = 0 "
        "WHERE kind = ?", (mj.REVIEW_JOB_KIND,))
    await db.db.commit()


# ═══ 1. Дренаж: один прогон уходит дальше одного окна ═══════════════════════

@pytest.mark.asyncio
async def test_drain_advances_beyond_one_window_per_run(tmp_path, monkeypatch):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 8,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    heartbeats = {"n": 0}
    original_heartbeat = TaskJobStore.heartbeat

    async def _counting_heartbeat(self, job_id, **kwargs):
        heartbeats["n"] += 1
        return await original_heartbeat(self, job_id, **kwargs)

    monkeypatch.setattr(TaskJobStore, "heartbeat", _counting_heartbeat)
    db = await _db(tmp_path, "drain.db")
    try:
        ids = [await _msg(db, text=f"реплика {i}") for i in range(125)]
        llm = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        # 125 строк за ОДИН прогон: 3 батча по ≤50 (а не 50/прогон).
        assert payload["counters"]["semantic_throughput_rows"] == 125
        assert llm.calls == 3
        assert payload["counters"]["semantic_batches_run"] == 3
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[-1]
        # Живой heartbeat на каждом батче: watchdog (60с) не сочтёт задачу
        # потерянной на длинном дренаже.
        assert heartbeats["n"] >= 1 + 3
        # реальный backlog исчерпан, честный lag = 0
        assert payload["semantic_progress"]["lag_rows"] == 0
        assert payload["semantic_progress"]["lag_source"] == "cursor_distance"
        assert payload["semantic_pending"] == {}
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 2. lag_rows = расстояние до данных, не счётчик pending ════════════════

@pytest.mark.asyncio
async def test_lag_rows_measures_cursor_distance_not_pending(tmp_path):
    hot_config.set_config_cache(_hot({
        # Порог в этом тесте — 100 строк (дефолт 500 проверяется отдельно);
        # эмиссия события включается фактом 120 > 100, а НЕ поднятием порога.
        "memory.experience_fresh_stream_lag_warn_threshold": 100,
    }))
    db = await _db(tmp_path, "lag.db")
    try:
        ids = [await _msg(db, text=f"строка {i}") for i in range(120)]
        runner = mj.ExperienceReviewRunner(db)
        payload = {
            "counters": mj.default_counters(),
            # Прод-картина: счётчик сильно занижен, реальное отставание — 120.
            "semantic_pending": {"-100": 3},
            "semantic_pending_since": {"-100": int(time.time()) - 1000},
            f"{mj.SEMANTIC_CURSOR_PREFIX}-100": 0,
        }
        lag = await runner._measure_semantic_lag(
            payload, now=int(time.time()))
        assert lag["available"] is True
        assert lag["rows"] == 120 and lag["chats"] == 1
        assert lag["worst_chat"] == -100
        assert lag["worst_rows"] == 120
        assert lag["worst_max_id"] == ids[-1]
        payload[mj.SEMANTIC_LAG_KEY] = lag
        snapshot = mj.semantic_progress_snapshot(
            payload, now=lag["ts"])
        # Обе величины видимы и НЕ подменяют друг друга.
        assert snapshot["pending_rows"] == 3
        assert snapshot["backlog_rows"] == 3            # legacy-счётчик
        assert snapshot["lag_rows"] == 120              # фактическое отставание
        assert snapshot["lag_source"] == "cursor_distance"

        runner._note_fresh_lag(payload)
        assert payload["counters"]["fresh_stream_lag_rows"] == 120
        assert payload["counters"]["fresh_stream_pending_rows"] == 3
        await mca_events.flush_events(db)
        cursor = await db.db.execute(
            "SELECT usage_json FROM mca_events WHERE event_name = ?",
            ("experience.fresh_stream_lag",))
        rows = [dict(r) for r in await cursor.fetchall()]
        assert rows, "событие лага должно быть эмитировано"
        usage = json.loads(rows[-1]["usage_json"])
        assert usage["lag_rows"] == 120
        assert usage["pending_rows"] == 3
        assert usage["lag_source"] == "cursor_distance"
        assert usage["cursor_rowid"] == 0
        assert usage["max_id"] == ids[-1]
        # Запрещённый способ «исправления»: дефолтный порог НЕ поднят.
        assert mj.FRESH_STREAM_LAG_WARN_ROWS == 500
    finally:
        hot_config.set_config_cache(None)
        await db.close()


@pytest.mark.asyncio
async def test_scheduler_keeps_draining_when_pending_counter_undercounts(
        tmp_path):
    """pending=0 при отстающем курсоре не должен выключать планировщик."""
    db = await _db(tmp_path, "sched.db")
    try:
        ids = [await _msg(db, text=f"строка {i}") for i in range(120)]
        llm = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        # Прод-подобное рассогласование: счётчик обнулён, курсор отстаёт.
        payload["semantic_pending"] = {}
        payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] = 0
        payload[mj.SEMANTIC_LAG_KEY] = {
            "available": True, "ts": int(time.time()), "rows": 120,
            "chats": 1, "actionable_rows": 120, "actionable_chats": 1,
            "measured_chats": 1, "partial": False,
            "worst_chat": -100, "worst_rows": 120, "worst_cursor": 0,
            "worst_max_id": ids[-1],
        }
        await db.db.execute(
            "UPDATE task_jobs SET payload = ? WHERE kind = ?",
            (json.dumps(payload), mj.REVIEW_JOB_KIND))
        await db.db.commit()
        backlog = await mj.semantic_backlog(db)
        assert backlog["rows"] == 120
        assert backlog["chats"] == 1
    finally:
        await db.close()


# ═══ 3. Durable-курсор переживает рестарт, повторной обработки нет ══════════

@pytest.mark.asyncio
async def test_cursor_progress_durable_across_restart(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 8,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    path = tmp_path / "restart.db"
    db = await _db(tmp_path, "restart.db")
    try:
        ids = [await _msg(db, text=f"реплика {i}") for i in range(125)]
        assert await mj.tick_experience_review(
            db, llm=_FakeLLM()) == "completed"
        before = await _payload_of(db)
        assert before[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[-1]
        await db.close()
        db = DatabaseService(str(path))
        await db.initialize()
        payload = await _payload_of(db)
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[-1]
        # бэклог исчерпан → новый тик не запускает работу и не пересканирует
        llm2 = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm2) == "not_due"
        assert llm2.calls == 0
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 4. Нет потери/дублей/пропусков на многобатчевом дренаже ════════════════

@pytest.mark.asyncio
async def test_no_loss_or_duplicates_across_batches(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 8,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    db = await _db(tmp_path, "nodup.db")
    try:
        ids = [await _msg(db, text=f"строка {i}") for i in range(130)]
        llm = _EchoLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        seen: set[int] = set()
        for batch in llm.batches:
            assert not (batch & seen), "строка отправлена в LLM повторно"
            seen |= batch
        assert seen == set(ids), "ни одна строка не потеряна и не пропущена"
        payload = await _payload_of(db)
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[-1]
        assert payload["counters"]["semantic_duplicates"] == 0
        assert payload["counters"]["semantic_throughput_rows"] == 130
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_experience_feedback")
        assert (await cursor.fetchone())["c"] == len(llm.batches)
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 5. Одиночная невалидная/непригодная строка не стопорит дренаж ═════════

@pytest.mark.asyncio
async def test_invalid_row_does_not_stall_drain(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 8,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    db = await _db(tmp_path, "badrow.db")
    try:
        ids = []
        bad_media = bad_cmd = None
        for i in range(60):
            if i == 17:
                bad_media = await _msg(
                    db, text="картинка без смысла", media_type="photo")
                ids.append(bad_media)
                continue
            if i == 33:
                bad_cmd = await _msg(db, text="/start")
                ids.append(bad_cmd)
                continue
            ids.append(await _msg(db, text=f"реплика {i}"))
        llm = _EchoLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[-1]
        assert payload["counters"]["semantic_throughput_rows"] == 60
        assert payload["counters"]["semantic_rows_ineligible"] >= 2
        sent = set().union(*llm.batches) if llm.batches else set()
        assert bad_media not in sent and bad_cmd not in sent
        assert len(sent) == 58
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 6. Изоляция чатов: битый ответ одного чата не блокирует другие ═════════

@pytest.mark.asyncio
async def test_broken_chat_does_not_block_other_chats(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_drain_chats_per_pass": 1,
        "memory.experience_drain_per_chat_max": 5,
        "memory.experience_semantic_batches_per_run": 10,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    db = await _db(tmp_path, "isolation.db")
    try:
        broken_ids = [await _msg(db, chat_id=-100, text=f"битый чат {i}")
                      for i in range(5)]
        ok_ids = [await _msg(db, chat_id=-200, text=f"рабочий чат {i}")
                  for i in range(5)]
        llm = _ChatAwareLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        # рабочий чат обработан полностью в ТОМ ЖЕ прогоне
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-200"] == ok_ids[-1]
        # битый чат: позиция НЕ сдвинута, отложенный повтор включён
        assert payload.get(f"{mj.SEMANTIC_CURSOR_PREFIX}-100", 0) == 0
        assert payload["counters"]["semantic_parse_invalid"] >= 1
        assert payload["semantic_retry"].get("-100", {}).get("retry_at", 0) > 0
        # Ровно два батча: рабочий чат и битый чат; третий раз битый чат
        # в этом прогоне не отправляется (изоляция без зацикливания).
        assert len(llm.batches) == 2
        assert llm.batches[0] == set(ok_ids)
        assert llm.batches[1] == set(broken_ids)
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 7. Crash между батчами: checkpoint, interrupted, безопасный resume ════

@pytest.mark.asyncio
async def test_crash_between_batches_resumes_without_duplicates(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_drain_chats_per_pass": 1,
        "memory.experience_drain_per_chat_max": 10,
        "memory.experience_semantic_batches_per_run": 6,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    db = await _db(tmp_path, "crash.db")
    try:
        ids = [await _msg(db, text=f"строка {i}") for i in range(55)]
        crash = _CrashLLM(crash_on_call=2)
        with pytest.raises(_Crash):
            await mj.tick_experience_review(db, llm=crash)
        payload = await _payload_of(db)
        # checkpoint после ПЕРВОГО батча durable, несмотря на падение
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[9]
        # Процесс «умер»: recover_stale помечает job interrupted (механизм
        # существующий, не новый).
        await db.db.execute(
            "UPDATE task_jobs SET heartbeat_at = 1 WHERE status = 'running'")
        await db.db.commit()
        store = TaskJobStore(db)
        assert await store.recover_stale(stale_after_seconds=1)
        # Новый job наследует checkpoint interrupted-job и продолжает с
        # позиции после первого батча: без потери и без повторной отправки.
        llm = _EchoLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        first_batch = llm.batches[0]
        assert ids[0] not in first_batch and ids[9] not in first_batch
        assert first_batch == set(ids[10:20])
        seen: set[int] = set()
        for batch in llm.batches:
            assert not (batch & seen)
            seen |= batch
        assert seen == set(ids[10:]), "хвост после checkpoint продолжен целиком"
        payload = await _payload_of(db)
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[-1]
        assert payload["counters"]["semantic_duplicates"] == 0
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 8. Прогон ограничен реальным бюджетом (батчи и wall-clock) ════════════

@pytest.mark.asyncio
async def test_run_bounded_by_batch_budget(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 2,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    db = await _db(tmp_path, "budget.db")
    try:
        ids = [await _msg(db, text=f"строка {i}") for i in range(300)]
        llm = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        assert llm.calls == 2
        assert payload["counters"]["semantic_batches_run"] == 2
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[99]
        assert payload["semantic_progress"]["lag_rows"] == 200
    finally:
        hot_config.set_config_cache(None)
        await db.close()


@pytest.mark.asyncio
async def test_run_bounded_by_wall_clock_budget(tmp_path, monkeypatch):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 8,
        "memory.experience_semantic_run_budget_seconds": 5,
    }))
    ticks = {"n": 0}

    def _fake_monotonic():
        ticks["n"] += 1
        return 0.0 if ticks["n"] == 1 else 1000.0

    monkeypatch.setattr(mj, "_monotonic", _fake_monotonic)
    db = await _db(tmp_path, "clock.db")
    try:
        ids = [await _msg(db, text=f"строка {i}") for i in range(120)]
        llm = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        assert llm.calls == 1, "бюджет исчерпан → второй батч не запускается"
        assert payload["counters"]["semantic_budget_exhausted"] == 1
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[49]
        # прогресс durable: следующий прогон продолжает с той же позиции
        await _next_pass(db)
        payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[49]
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 9. Не «исправление порогом»: дефолты дают реальный дренаж ═════════════

def test_defaults_are_drain_not_threshold(monkeypatch):
    monkeypatch.setattr(hot_config, "get", lambda key, default=None: default)
    # Порог warning остался 500 (поднимать его — запрещённый «фикс»).
    assert mj.fresh_lag_warn_rows() == 500
    # Дренаж по умолчанию — несколько батчей за прогон, с реальным бюджетом.
    assert mj.semantic_batches_per_run() >= 2
    assert mj.semantic_run_budget_seconds() >= 30
    assert mj.SEMANTIC_PER_CHAT_MAX == 50


# ═══ 10. F1: сбой всех COUNT — честная недоступность, не ложный 0 ═══════════

@pytest.mark.asyncio
async def test_all_lag_counts_failed_is_unavailable_not_zero(
        tmp_path, monkeypatch):
    """Ревью I2 F1: behind непуст, но ни один COUNT не удался → available=False.

    На прежнем коде замер отдавал `available=True, rows=0` и
    `lag_source="cursor_distance"`, то есть выдавал сбой чтения за «отставания
    нет». Ноль допустим только как измеренный ноль.
    """
    db = await _db(tmp_path, "lagfail.db")
    try:
        for i in range(5):
            await _msg(db, text=f"строка {i}")
        runner = mj.ExperienceReviewRunner(db)
        payload = {
            "counters": mj.default_counters(),
            f"{mj.SEMANTIC_CURSOR_PREFIX}-100": 0,
        }

        async def _boom(chat_id, cursor_pos):
            raise RuntimeError("read failed")

        monkeypatch.setattr(runner, "_chat_rows_after", _boom)
        now = int(time.time())
        lag = await runner._measure_semantic_lag(payload, now=now)
        assert lag["available"] is False, "сбой измерения не должен быть нулём"
        assert lag["chats"] == 1
        assert lag["measured_chats"] == 0
        assert lag["failed_chats"] == 1
        assert lag["partial"] is True
        payload[mj.SEMANTIC_LAG_KEY] = lag
        snapshot = mj.semantic_progress_snapshot(payload, now=now)
        # Источник явно pending-fallback; ложного cursor_distance нет.
        assert snapshot["lag_source"] == "pending"
        assert snapshot["lag_rows"] == 0
        assert snapshot["lag_seconds"] is None
        assert snapshot["lag_seconds_source"] == "unknown"
    finally:
        await db.close()


# ═══ 11. F2: lag_seconds из измеренной дистанции, не pending ════════════════

@pytest.mark.asyncio
async def test_lag_seconds_measured_from_cursor_distance(tmp_path):
    """Ревью I2 F2: при lag_rows>0 возраст не может оставаться нулём.

    pending-счётчик пуст (прод-рассогласование), но строки после курсора есть:
    `lag_seconds` обязан считаться по данным (timestamp самой старой из них).
    """
    db = await _db(tmp_path, "lagsec.db")
    try:
        now = int(time.time())
        await _msg(db, text="самая старая", ts=now - 3600)
        await _msg(db, text="следующая", ts=now - 60)
        runner = mj.ExperienceReviewRunner(db)
        payload = {
            "counters": mj.default_counters(),
            f"{mj.SEMANTIC_CURSOR_PREFIX}-100": 0,
        }
        lag = await runner._measure_semantic_lag(payload, now=now)
        assert lag["available"] is True
        assert lag["rows"] == 2
        assert lag["oldest_ts"] == now - 3600
        assert lag["age_seconds"] >= 3590
        payload[mj.SEMANTIC_LAG_KEY] = lag
        snapshot = mj.semantic_progress_snapshot(payload, now=now)
        assert snapshot["lag_rows"] == 2
        assert snapshot["pending_rows"] == 0          # счётчик пуст
        assert snapshot["lag_seconds"] >= 3590         # а возраст — не 0
        assert snapshot["lag_seconds_source"] == "cursor_distance"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_lag_seconds_unknown_is_none_not_zero(tmp_path, monkeypatch):
    """Ревью I2 F2: неизвестность не подставляется нулём."""
    db = await _db(tmp_path, "lagunknown.db")
    try:
        await _msg(db, text="строка")
        runner = mj.ExperienceReviewRunner(db)
        payload = {
            "counters": mj.default_counters(),
            f"{mj.SEMANTIC_CURSOR_PREFIX}-100": 0,
        }

        async def _boom(chat_id, cursor_pos):
            raise RuntimeError("read failed")

        monkeypatch.setattr(runner, "_chat_rows_after", _boom)
        now = int(time.time())
        lag = await runner._measure_semantic_lag(payload, now=now)
        assert lag["available"] is False
        payload[mj.SEMANTIC_LAG_KEY] = lag
        snapshot = mj.semantic_progress_snapshot(payload, now=now)
        assert snapshot["lag_seconds"] is None
        assert snapshot["lag_seconds_source"] == "unknown"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_lag_seconds_pending_fallback_marks_source(tmp_path, monkeypatch):
    """Если замер недоступен, возраст берётся из pending — с явным source."""
    db = await _db(tmp_path, "lagpending.db")
    try:
        await _msg(db, text="строка")
        runner = mj.ExperienceReviewRunner(db)
        now = int(time.time())
        payload = {
            "counters": mj.default_counters(),
            f"{mj.SEMANTIC_CURSOR_PREFIX}-100": 0,
            mj.SEMANTIC_PENDING_KEY: {"-100": 5},
            mj.SEMANTIC_PENDING_SINCE_KEY: {"-100": now - 120},
        }

        async def _boom(chat_id, cursor_pos):
            raise RuntimeError("read failed")

        monkeypatch.setattr(runner, "_chat_rows_after", _boom)
        lag = await runner._measure_semantic_lag(payload, now=now)
        assert lag["available"] is False
        payload[mj.SEMANTIC_LAG_KEY] = lag
        snapshot = mj.semantic_progress_snapshot(payload, now=now)
        assert snapshot["lag_source"] == "pending"
        assert snapshot["lag_seconds"] == 120
        assert snapshot["lag_seconds_source"] == "pending"
    finally:
        await db.close()


# ═══ 12. B1: потребители сохраняют None (неизвестно ≠ ноль) ═════════════════

async def _insert_review_progress(db, progress: dict) -> None:
    """Durable review-job с заданным semantic_progress (как в проде)."""
    payload = {"counters": {}, "semantic_progress": progress}
    await db.db.execute(
        "INSERT INTO task_jobs (job_id, owner, kind, payload, status, "
        "attempt, max_attempts, created_at, updated_at, finished_at) "
        "VALUES ('b1-review', 'mca16', ?, ?, 'completed', 1, 3, 100, 100, 100)",
        (mj.REVIEW_JOB_KIND, json.dumps(payload)))
    await db.db.commit()


@pytest.mark.asyncio
async def test_diagnostics_lag_seconds_unknown_stays_none(tmp_path):
    """`_learning_analytics` не подменяет неизвестность нулём (B1)."""
    from services import experience_diagnostics as ed
    db = await _db(tmp_path, "b1diag.db")
    try:
        await _insert_review_progress(db, {
            "lag_seconds": None, "lag_seconds_source": "unknown",
            "lag_rows": 5, "lag_source": "pending", "pending_rows": 5,
        })
        out = await ed._learning_analytics(db)
        assert out["fresh_lag"]["lag_seconds"] is None
        assert out["fresh_lag"]["lag_seconds_source"] == "unknown"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_diagnostics_measured_zero_stays_zero(tmp_path):
    """Измеренный ноль при cursor_distance остаётся нулём (B1)."""
    from services import experience_diagnostics as ed
    db = await _db(tmp_path, "b1diagz.db")
    try:
        await _insert_review_progress(db, {
            "lag_seconds": 0, "lag_seconds_source": "cursor_distance",
            "lag_rows": 0, "lag_source": "cursor_distance",
        })
        out = await ed._learning_analytics(db)
        assert out["fresh_lag"]["lag_seconds"] == 0
        assert out["fresh_lag"]["lag_seconds_source"] == "cursor_distance"
    finally:
        await db.close()
