"""E-TRUNC / E-LAG amendment (owner input 2026-11-22, §B).

Покрытие контракта (`requirements-map-exp-amendment.json`):
  EXP-E-TRUNC-01: reasoning-only/finish_reason=length воспроизводится;
    универсальный потолок 1500 больше не применяется; бюджет считается по
    контракту + размеру окна + capability модели; контролируемый retry с
    большим бюджетом и durable уменьшение окна; принимается только валидный
    контент (reasoning не становится ответом); типизированный parse/SourceRef/
    идемпотентность сохранены; отказавшееся окно не крутится вечно.
  EXP-E-LAG-01: head-of-line старого хвоста больше не блокирует новые события
    (fresh-полоса того же job/экстрактора); batch bounded по строкам; лаг
    остаётся измеренным COUNT, не подменяется нулём; курсор не двигается
    фиктивно; discovery catch-up при разрыве watermark↔MAX(id).

TEST-LIFECYCLE: CONTRACT owner=EXP-E-TRUNC-01/EXP-E-LAG-01
"""
import json
import time
from types import SimpleNamespace

import pytest

from services import hot_config
from services import mca_events
from services import mca_experience_jobs as mj
from services import model_capacity
from services.database import DatabaseService
from services.llm_client import LLMBadResponseError


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


def _hot(values: dict | None = None):
    return _FakeHot(values or {})


def _truncation_error() -> LLMBadResponseError:
    exc = LLMBadResponseError(
        "chat/completions: no final text | "
        "kind=truncated_reasoning | finish_reason=length")
    exc.response_kind = "truncated_reasoning"
    exc.llm_finish_reason = "length"
    exc.reasoning_chars = 4096
    return exc


def _msg_ids(messages) -> list[int]:
    try:
        content = str(messages[1]["content"])
    except (KeyError, IndexError, TypeError):
        return []
    out = []
    for chunk in content.split("[msg:")[1:]:
        try:
            out.append(int(chunk.split(" ")[0]))
        except (TypeError, ValueError):
            continue
    return out


class _BudgetLLM:
    """Обрезает ответ ниже min_budget (reasoning-only), иначе — валидный []."""

    def __init__(self, min_budget: int = 0):
        self.min_budget = int(min_budget)
        self.calls = 0
        self.budgets: list[int] = []
        self.fields: list[str] = []
        self.batches: list[list[int]] = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        budget = int(kwargs.get("max_output_tokens") or 0)
        self.budgets.append(budget)
        self.fields.append(str(kwargs.get("output_field") or ""))
        self.batches.append(_msg_ids(messages))
        if budget < self.min_budget:
            raise _truncation_error()
        return "[]"


class _AlwaysTruncatedLLM:
    def __init__(self):
        self.calls = 0
        self.budgets: list[int] = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.budgets.append(int(kwargs.get("max_output_tokens") or 0))
        raise _truncation_error()


class _RecordingLLM:
    def __init__(self):
        self.calls = 0
        self.batches: list[list[int]] = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.batches.append(_msg_ids(messages))
        return "[]"


class _SizeAwareLLM(_RecordingLLM):
    """Обрезает большие окна (reasoning-only), малые — валидный []."""

    def __init__(self, truncate_at: int = 10):
        super().__init__()
        self.truncate_at = int(truncate_at)

    async def generate(self, messages, **kwargs):
        self.calls += 1
        ids = _msg_ids(messages)
        self.batches.append(ids)
        if len(ids) >= self.truncate_at:
            raise _truncation_error()
        return "[]"


async def _latest_terminal_job(db) -> tuple[str, dict]:
    """Тот же выбор, что `_inherit_cursor`: последний терминальный job."""
    cursor = await db.db.execute(
        "SELECT job_id, payload FROM task_jobs WHERE kind = ? AND status IN "
        "('completed','failed','interrupted') "
        "ORDER BY COALESCE(finished_at, updated_at, created_at) DESC, "
        "rowid DESC LIMIT 1", (mj.REVIEW_JOB_KIND,))
    row = await cursor.fetchone()
    return str(row["job_id"]), json.loads(row["payload"] or "{}")


async def _force_tail_retry_due(db, chat_id=-100) -> None:
    """Сделать tail-backoff истёкшим, не трогая fresh-полосу."""
    job_id, payload = await _latest_terminal_job(db)
    entry = (payload.get(mj.SEMANTIC_RETRY_KEY) or {}).get(str(chat_id))
    assert entry, "tail retry должен существовать"
    entry["retry_at"] = 0
    await db.db.execute(
        "UPDATE task_jobs SET payload = ? WHERE job_id = ?",
        (json.dumps(payload), job_id))
    await db.db.commit()


async def _db(tmp_path, name="exp_e.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _msgs(db, count, *, chat_id=-100, start=0, prefix="m") -> list[int]:
    ids = []
    now = int(time.time())
    for i in range(int(count)):
        cursor = await db.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
            "timestamp, media_type, author_name, is_forward, tg_message_id) "
            "VALUES (42, ?, ?, NULL, ?, 'text', 'u', 0, NULL)",
            (chat_id, f"{prefix}{start + i}", now))
        ids.append(cursor.lastrowid)
    await db.db.commit()
    return ids


async def _payload_of(db) -> dict:
    cursor = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE kind = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (mj.REVIEW_JOB_KIND,))
    row = await cursor.fetchone()
    return json.loads(row["payload"] or "{}")


async def _next_pass(db) -> None:
    """Сделать проход due, не дожидаясь суточной каденции."""
    await db.db.execute(
        "UPDATE task_jobs SET status = 'completed', finished_at = 0 "
        "WHERE kind = ?", (mj.REVIEW_JOB_KIND,))
    await db.db.commit()


def _cursor(payload, chat_id=-100) -> int:
    return int(payload.get(f"{mj.SEMANTIC_CURSOR_PREFIX}{chat_id}") or 0)


# ═══ 1. E-TRUNC: budget растёт, окно восстанавливается, только валидный [] ══

@pytest.mark.asyncio
async def test_reasoning_truncation_recovers_with_contract_budget(
        tmp_path, monkeypatch):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 4,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    db = await _db(tmp_path, "trunc_recover.db")
    try:
        ids = await _msgs(db, 40)
        llm = _BudgetLLM(min_budget=5000)
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        assert llm.calls == 2, "первый бюджет обрезан, второй — восстановил"
        assert llm.budgets[0] != 1500, "универсальных 1500 больше нет"
        assert llm.budgets[0] >= mj.SEMANTIC_OUTPUT_FLOOR_TOKENS
        assert llm.budgets[1] > llm.budgets[0], "повтор не идентичен"
        assert llm.budgets[1] <= mj.SEMANTIC_OUTPUT_CEILING_TOKENS
        assert _cursor(payload) == ids[-1], "валидный ответ двигает курсор"
        counters = payload["counters"]
        assert counters["semantic_throughput_rows"] == 40
        assert counters["semantic_truncated"] == 1
        assert counters["semantic_truncated_recovered"] == 1
        assert counters["semantic_truncation_reasons"][
            "truncated_reasoning"] == 1
        assert counters["semantic_llm_unavailable"] == 0
        assert payload["semantic_retry"] == {}
        assert payload[mj.SEMANTIC_TRUNCATED_KEY] == {}
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 2. E-TRUNC: capability модели ограничивает бюджет и выбирает поле ═════

@pytest.mark.asyncio
async def test_model_capability_caps_budget_and_uses_output_field(
        tmp_path, monkeypatch):
    hot_config.set_config_cache(_hot())
    db = await _db(tmp_path, "cap.db")

    async def _capability(base_url, model, **kwargs):
        return SimpleNamespace(
            max_output=2048, context_window=8192, supports_reasoning=True,
            output_token_field="max_completion_tokens")

    monkeypatch.setattr(model_capacity, "resolve_model_capability", _capability)
    try:
        await _msgs(db, 40)

        class _AttrsLLM(_BudgetLLM):
            _chat_model = "vendor/reasoning-model"
            _base_url = "https://llm.invalid/v1"

        llm = _AttrsLLM(min_budget=0)
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        assert llm.calls == 1
        assert llm.budgets[0] <= 2048, "max_output модели — жёсткий потолок"
        assert llm.fields[0] == "max_completion_tokens"
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 3. E-TRUNC: невосстановимая обрезка — курсор стоит, durable причина ═══

@pytest.mark.asyncio
async def test_unrecoverable_truncation_keeps_cursor_and_backs_off(
        tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 1,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    path = tmp_path / "trunc_stuck.db"
    db = await _db(tmp_path, "trunc_stuck.db")
    try:
        await _msgs(db, 30)
        stuck = _AlwaysTruncatedLLM()
        assert await mj.tick_experience_review(db, llm=stuck) == "completed"
        payload = await _payload_of(db)
        # initial + ровно SEMANTIC_OUTPUT_RETRY_ATTEMPTS повторов, затем стоп.
        assert stuck.calls == 1 + mj.SEMANTIC_OUTPUT_RETRY_ATTEMPTS
        assert stuck.budgets[-1] <= mj.SEMANTIC_OUTPUT_CEILING_TOKENS
        assert _cursor(payload) == 0, "обрезанный ответ не двигает курсор"
        counters = payload["counters"]
        assert counters["semantic_throughput_rows"] == 0
        assert counters["semantic_truncated"] == stuck.calls
        assert counters["semantic_truncated_chats"] == 1
        assert counters["semantic_llm_unavailable"] == 0
        trunc = payload[mj.SEMANTIC_TRUNCATED_KEY]["-100"]
        assert trunc["count"] == 1
        assert trunc["reason"] == "truncated_reasoning"
        retry = payload["semantic_retry"]["-100"]
        assert retry["reason"] == "truncated_reasoning"
        assert retry["retry_at"] > int(time.time())
        assert retry["row_limit"] < 30, "окно уменьшено для следующего прохода"
        # Планировщик: пока retry_at в будущем — прохода нет; когда наступил —
        # backlog снова ненулевой, даже если actionable/pending уже 0.
        assert (await mj.semantic_backlog(db))["rows"] == 0
        payload["semantic_retry"]["-100"]["retry_at"] = 0
        await db.db.execute(
            "UPDATE task_jobs SET payload = ? WHERE kind = ?",
            (json.dumps(payload), mj.REVIEW_JOB_KIND))
        await db.db.commit()
        assert (await mj.semantic_backlog(db))["rows"] > 0
        payload["semantic_retry"]["-100"]["retry_at"] = int(time.time()) + 900
        await db.db.execute(
            "UPDATE task_jobs SET payload = ? WHERE kind = ?",
            (json.dumps(payload), mj.REVIEW_JOB_KIND))
        await db.db.commit()
        # Durable: рестарт процесса не сбрасывает причину/backoff.
        await db.close()
        db = DatabaseService(str(path))
        await db.initialize()
        await _next_pass(db)
        deferred = _AlwaysTruncatedLLM()
        assert await mj.tick_experience_review(db, llm=deferred) == "completed"
        assert deferred.calls == 0, "до retry_at окно не долбится повторно"
        # По истечении backoff — меньшее окно и успешное восстановление.
        payload = await _payload_of(db)
        payload["semantic_retry"]["-100"]["retry_at"] = 0
        await db.db.execute(
            "UPDATE task_jobs SET payload = ? WHERE kind = ?",
            (json.dumps(payload), mj.REVIEW_JOB_KIND))
        await db.db.commit()
        await _next_pass(db)
        recovered = _BudgetLLM(min_budget=0)
        assert await mj.tick_experience_review(db, llm=recovered) == "completed"
        assert recovered.calls >= 1
        assert all(len(batch) <= 15 for batch in recovered.batches)
        payload = await _payload_of(db)
        assert _cursor(payload) == 15
        assert payload["semantic_retry"] == {}
        # История отказа не стирается — это диагностика, а не блокировка.
        assert payload[mj.SEMANTIC_TRUNCATED_KEY]["-100"]["count"] == 1
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 4. E-LAG: один вызов ≤ bounded строк, все строки доходят без дублей ══

@pytest.mark.asyncio
async def test_one_call_is_row_bounded_across_chats(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 8,
        "memory.experience_semantic_run_budget_seconds": 3600,
    }))
    db = await _db(tmp_path, "rowcap.db")
    try:
        ids: list[int] = []
        for chat in range(6):
            ids.extend(await _msgs(db, 50, chat_id=-100 - chat,
                                   prefix=f"c{chat}m"))
        llm = _RecordingLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        sizes = [len(batch) for batch in llm.batches]
        assert sizes and max(sizes) <= mj.SEMANTIC_BATCH_ROWS_MAX
        seen: set[int] = set()
        for batch in llm.batches:
            assert not (seen & set(batch)), "строка отправлена повторно"
            seen |= set(batch)
        assert seen == set(ids), "ни одна строка не потеряна"
        payload = await _payload_of(db)
        assert payload["counters"]["semantic_throughput_rows"] == 300
        assert payload["counters"]["semantic_batches_run"] == len(llm.batches)
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 5. E-LAG: новые события обрабатываются при отстающем старом хвосте ═══

@pytest.mark.asyncio
async def test_new_events_processed_while_old_tail_lags(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 1,
        "memory.experience_semantic_run_budget_seconds": 3600,
        "memory.experience_semantic_batch_rows_max": 50,
        "memory.experience_semantic_fresh_lane_lag_rows": 4000,
    }))
    db = await _db(tmp_path, "fresh_lane.db")
    try:
        old = await _msgs(db, 6000, prefix="old")
        llm = _RecordingLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        # `_init_chat_stream` стартует свежий хвост с max_id - FRESH_TAIL_ROWS
        # (5000): cursor=1000, а хвост 5000 строк превышает порог 4000 →
        # свежая полоса включается сразу и обрабатывает самый новый id.
        payload = await _payload_of(db)
        first_cursor = _cursor(payload)
        assert first_cursor == old[999]
        assert set(llm.batches[0]) == {old[-1]}
        lane = payload[mj.SEMANTIC_FRESH_KEY]["-100"]
        assert lane["boundary"] == old[-1]
        assert lane["cursor"] == old[-1]
        new = await _msgs(db, 3, start=6000, prefix="new")
        await _next_pass(db)
        before = len(llm.batches)
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        fresh_batches = llm.batches[before:]
        assert fresh_batches, "fresh-батч должен исполниться"
        assert set(fresh_batches[0]) == set(new), (
            "новые события не ждут, пока дренируется архив")
        payload = await _payload_of(db)
        lane = payload[mj.SEMANTIC_FRESH_KEY]["-100"]
        assert lane["boundary"] == old[-1]
        assert lane["cursor"] == new[-1]
        assert _cursor(payload) == first_cursor, (
            "старый курсор не двигается фиктивно")
        # lag остаётся ИЗМЕРЕННЫМ COUNT: старый хвост честно виден.
        lag = payload["semantic_lag"]
        assert lag["available"] is True
        assert lag["rows"] == 6000 - first_cursor - 1
        assert payload["counters"]["semantic_fresh_rows"] == 3
        # Следующий проход дренирует старый хвост, новые не дублируются.
        await _next_pass(db)
        before = len(llm.batches)
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        tail_batches = llm.batches[before:]
        tail_ids = [mid for mid in tail_batches[0] if mid not in set(new)]
        assert tail_ids and min(tail_ids) == first_cursor + 1
        assert not (set(tail_batches[0]) & set(new))
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 6. E-LAG: discovery catch-up не отстаёт от MAX(id) на месяцы ═════════

@pytest.mark.asyncio
async def test_discovery_catchup_scans_beyond_normal_limit(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 1,
        "memory.experience_semantic_run_budget_seconds": 3600,
        "memory.experience_semantic_fresh_lane_lag_rows": 1_000_000,
    }))
    db = await _db(tmp_path, "disc.db")
    try:
        await _msgs(db, 6000)
        llm = _RecordingLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        assert payload["counters"]["semantic_discovery_catchup"] == 1
        assert payload["counters"]["semantic_scanned"] >= 5000
        assert payload["semantic_watermark"] >= 5000
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 8. E-LAG: измеренный lag монотонно падает, throughput > поступления ═══

@pytest.mark.asyncio
async def test_measured_lag_converges_with_bounded_catch_up(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 12,
        "memory.experience_semantic_run_budget_seconds": 3600,
        "memory.experience_semantic_catchup_batches_per_run": 36,
        "memory.experience_semantic_catchup_run_budget_seconds": 3600,
        "memory.experience_semantic_fresh_lane_lag_rows": 5000,
    }))
    db = await _db(tmp_path, "lag_math.db")
    try:
        ids = await _msgs(db, 8000)
        job_id = await mj.enqueue_experience_review(db)
        assert job_id
        # Прод-подобный checkpoint: курсор далеко от MAX, измеренный lag уже
        # есть (2 048 762 в проде — здесь 8000, та же арифметика COUNT).
        payload = await _payload_of(db)
        payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] = 0
        payload["semantic_pending"] = {"-100": 8000}
        payload["semantic_pending_since"] = {"-100": int(time.time()) - 3600}
        payload["semantic_lag"] = {
            "available": True, "ts": int(time.time()), "rows": 8000,
            "chats": 1, "actionable_rows": 8000, "actionable_chats": 1,
            "measured_chats": 1, "failed_chats": 0, "partial": False,
            "worst_chat": -100, "worst_rows": 8000, "worst_cursor": 0,
            "worst_max_id": ids[-1], "oldest_ts": 0, "age_seconds": None,
        }
        await db.db.execute(
            "UPDATE task_jobs SET payload = ? WHERE job_id = ?",
            (json.dumps(payload), job_id))
        await db.db.commit()
        lags: list[int] = []
        processed = 0
        llm = _RecordingLLM()
        seen: set[int] = set()
        for pass_no in range(10):
            if pass_no == 1:
                # Новые события приходят во время разгребания старого хвоста.
                await _msgs(db, 20, start=8000, prefix="inflow")
            await _next_pass(db)
            before = len(llm.batches)
            assert await mj.tick_experience_review(
                db, llm=llm) == "completed"
            for batch in llm.batches[before:]:
                assert not (seen & set(batch)), "повторная обработка строки"
                seen |= set(batch)
            payload = await _payload_of(db)
            lag = int(payload["semantic_lag"]["rows"])
            lags.append(lag)
            processed = int(payload["counters"]["semantic_throughput_rows"])
            if lag == 0:
                break
        assert lags and lags[0] < 8000, "catch-up реально двигает хвост"
        assert all(b < a for a, b in zip(lags, lags[1:]) if a != b or b > 0), (
            f"lag обязан монотонно падать: {lags}")
        assert lags[-1] == 0, f"лаг не сошёлся: {lags}"
        assert processed > 0
        assert len(seen) == 8000 + 20, "обработаны старый хвост и inflow"
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 9. E-LAG: слияние fresh-полосы без потерь и дублей ═══════════════════

@pytest.mark.asyncio
async def test_fresh_lane_merges_without_loss_or_duplicates(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 120,
        "memory.experience_semantic_run_budget_seconds": 3600,
        "memory.experience_semantic_fresh_lane_lag_rows": 4000,
    }))
    db = await _db(tmp_path, "lane_merge.db")
    try:
        ids = await _msgs(db, 6000)
        llm = _RecordingLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        assert payload[mj.SEMANTIC_FRESH_KEY] == {}, (
            "старый хвост дошёл до границы — полоса слита в одну позицию")
        assert _cursor(payload) == ids[-1]
        assert payload["semantic_lag"]["rows"] == 0
        seen: set[int] = set()
        for batch in llm.batches:
            assert not (seen & set(batch)), "дубль после слияния полос"
            seen |= set(batch)
        # Свежий хвост (после _init_chat_stream) обработан целиком; старый
        # архив 1..1000 не потерян и обслуживается archive-механизмом.
        assert set(ids[1000:]).issubset(seen)
        assert payload["counters"]["semantic_fresh_lanes_merged"] >= 1
    finally:
        hot_config.set_config_cache(None)
        await db.close()


def _tail_batch_sizes(llm, since: int, lo: int = 1001,
                      hi: int = 5999) -> list[int]:
    """Размеры ТОЛЬКО tail-батчей (archive ids ≤1000, fresh ids ≥6001)."""
    return [len(batch) for batch in llm.batches[since:]
            if any(lo <= mid <= hi for mid in batch)]


async def _prepare_tail_truncation_state(db, llm):
    """6000 строк → fresh-полоса + обрезанный tail (row_limit=25, attempts=1).

    Pass1: fresh читает 1 новый id (успех), tail читает 50 (обрезка, 3 вызова),
    после чего durable `semantic_retry[row_limit=25, attempts=1]`."""
    ids = await _msgs(db, 6000)
    assert await mj.tick_experience_review(db, llm=llm) == "completed"
    payload = await _payload_of(db)
    lane = payload[mj.SEMANTIC_FRESH_KEY]["-100"]
    assert lane["boundary"] == ids[-1]
    assert lane["cursor"] == ids[-1]
    retry = payload["semantic_retry"]["-100"]
    assert retry["reason"] == "truncated_reasoning"
    assert retry["row_limit"] == 25
    assert retry["attempts"] == 1
    assert retry["retry_at"] > int(time.time())
    assert _cursor(payload) == 1000
    return ids


# ═══ 6b. B01: fresh-успех не стирает tail row_limit/attempts/backoff ══════

@pytest.mark.asyncio
async def test_fresh_success_does_not_reset_tail_truncation_state(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 2,
        "memory.experience_semantic_run_budget_seconds": 3600,
        "memory.experience_semantic_batch_rows_max": 50,
        "memory.experience_semantic_fresh_lane_lag_rows": 4000,
    }))
    db = await _db(tmp_path, "b01.db")
    try:
        llm = _SizeAwareLLM(truncate_at=10)
        ids = await _prepare_tail_truncation_state(db, llm)
        tail_sizes = _tail_batch_sizes(llm, 0)
        assert set(tail_sizes) == {50}, tail_sizes
        expected_limits = [13, 7]
        for step in range(3):
            new = await _msgs(db, 2, start=6000 + 2 * step,
                              prefix=f"in{step}")
            await _force_tail_retry_due(db)
            await _next_pass(db)
            before = len(llm.batches)
            assert await mj.tick_experience_review(
                db, llm=llm) == "completed"
            payload = await _payload_of(db)
            # Fresh-полоса успешна каждый проход (свежие события не ждут).
            assert any(set(new).issubset(set(batch))
                       for batch in llm.batches[before:]), (
                f"fresh inflow не обработан на шаге {step}")
            tail_sizes = _tail_batch_sizes(llm, before)
            if step < 2:
                # B01: уменьшенное окно хвоста сохранено и применено.
                assert set(tail_sizes) == {25 if step == 0 else 13}, tail_sizes
                retry = payload["semantic_retry"]["-100"]
                assert retry["attempts"] == step + 2
                assert retry["row_limit"] == expected_limits[step]
                assert _cursor(payload) == 1000, "обрезанный tail не двигается"
            else:
                # 7 строк < порога: durable успех снимает только tail retry.
                assert tail_sizes == [7]
                assert payload["semantic_retry"] == {}
                assert _cursor(payload) == 1007
        # Ни одно fresh-событие не потеряно/не обработано дважды.
        seen_new: set[int] = set()
        for batch in llm.batches:
            fresh = set(batch) & set(range(6001, 6007))
            assert not (seen_new & fresh), "fresh-событие обработано дважды"
            seen_new |= fresh
        assert seen_new == set(range(6001, 6007))
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 6c. N01: fresh не ждёт tail backoff (включая restart) ═════════════════

@pytest.mark.asyncio
async def test_fresh_lane_ignores_tail_backoff_across_restart(tmp_path):
    hot_config.set_config_cache(_hot({
        "memory.experience_semantic_batches_per_run": 2,
        "memory.experience_semantic_run_budget_seconds": 3600,
        "memory.experience_semantic_batch_rows_max": 50,
        "memory.experience_semantic_fresh_lane_lag_rows": 4000,
    }))
    path = tmp_path / "n01.db"
    db = await _db(tmp_path, "n01.db")
    try:
        llm = _SizeAwareLLM(truncate_at=10)
        ids = await _prepare_tail_truncation_state(db, llm)
        new = await _msgs(db, 2, start=6000, prefix="n01")
        retry_before = (await _payload_of(db))["semantic_retry"]["-100"]
        await db.close()
        db = DatabaseService(str(path))
        await db.initialize()
        await _next_pass(db)
        before = len(llm.batches)
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        calls = llm.batches[before:]
        # N01: tail retry_at ещё в будущем, но fresh обрабатывает новые события.
        assert retry_before["retry_at"] > int(time.time())
        assert any(set(new).issubset(set(batch)) for batch in calls), (
            "fresh-полоса ошибочно ждёт tail backoff")
        assert _tail_batch_sizes(llm, before) == [], (
            "tail не должен обходить свой backoff")
        assert payload[mj.SEMANTIC_FRESH_KEY]["-100"]["cursor"] == new[-1]
        assert _cursor(payload) == 1000
        retry = payload["semantic_retry"]["-100"]
        assert retry["attempts"] == 1
        assert retry["row_limit"] == 25
        assert retry["retry_at"] == retry_before["retry_at"]
        # После истечения backoff tail повторяет уменьшенное окно (не 50).
        await _force_tail_retry_due(db)
        await _next_pass(db)
        before = len(llm.batches)
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        tail_sizes = _tail_batch_sizes(llm, before)
        assert set(tail_sizes) == {25}, tail_sizes
        assert payload["semantic_retry"]["-100"]["attempts"] == 2
        assert payload["semantic_retry"]["-100"]["row_limit"] == 13
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ 7. Формула бюджета: не 1500, растёт с окном/повтором, чтит потолки ═══

def test_output_budget_formula_is_contract_and_capability_based():
    one, src = mj.semantic_output_budget(1)
    many, _ = mj.semantic_output_budget(40)
    assert one != 1500 and one >= mj.SEMANTIC_OUTPUT_FLOOR_TOKENS
    assert many > one
    retry, _ = mj.semantic_output_budget(40, attempt=2)
    assert retry > many
    assert retry <= mj.SEMANTIC_OUTPUT_CEILING_TOKENS
    # Явно подтверждённое отсутствие reasoning снимает резерв.
    no_reasoning, _ = mj.semantic_output_budget(
        40, SimpleNamespace(supports_reasoning=False))
    assert no_reasoning < many
    # Известный max_output модели — жёсткий потолок.
    capped, _ = mj.semantic_output_budget(
        40, SimpleNamespace(max_output=2048, supports_reasoning=True))
    assert capped <= 2048
    # Контекст меньше запрошенного бюджета — не просим больше остатка.
    tight, _ = mj.semantic_output_budget(
        40, SimpleNamespace(context_window=4096, supports_reasoning=True),
        input_chars=8000)
    assert tight < many
    assert src
