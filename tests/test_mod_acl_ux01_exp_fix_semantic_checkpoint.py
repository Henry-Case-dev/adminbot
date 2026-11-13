"""MOD-ACL-UX-01 / M5A — owner EXP-FIX-01..07, 09, 10 (semantic checkpoint).

Регрессионный набор владельца (TZ §7.1) на РЕАЛЬНЫХ SQL-строках, прогрессе
и повторных прогонах (не «функция вызвана»):

  (a) два последовательных job'а берут РАЗНЫЕ следующие сообщения;
  (b) рестарт после checkpoint и между durable insert и checkpoint;
  (c) окно, где 10 из 10 строк отфильтрованы (pending честно убывает,
      drained обновляет last_ts);
  (d) 4 чата, один из них выключен/пустой — не блокируют остальных;
  (e) SQL-сбой записи на второй записи — позиция не двигается, повтор без
      дублей;
  (f) invalid JSON vs валидный `[]` (типизированный результат разбора);
  (g) OFF→ON→OFF без рестарта, при OFF — нуль работы;
  (h) LLM недоступен — позиция стоит, детерминированный контур работает;
  (i) бэклог больше одного прохода — порции, throughput/lag, план следующей
      порции при накопленном бэклоге;
  (j) дедуп не создаёт дубликат урока;
  плюс: (EXP-FIX-01) полный durable semantic checkpoint наследуется новым
  job'ом; (EXP-FIX-07) справедливая ротация окна resume; (EXP-FIX-10)
  backpressure discovery при переполнении индекса чатов без потери сообщений.

TEST-LIFECYCLE: CONTRACT owner=MOD-ACL-UX-01/EXP-FIX-01..07,09,10
"""
import json
import time

import pytest

from services import hot_config
from services import mca_events, mca_gates
from services import mca_experience as me
from services import mca_experience_jobs as mj
from services import memory_maintenance as mm
from services.database import DatabaseService


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


@pytest.fixture(autouse=True)
def _fast_validation(monkeypatch):
    monkeypatch.setattr(mca_gates, "lesson_min_independent_episodes",
                        lambda: 1)


class _FakeLLM:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = 0
        self.last_messages = None

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.last_messages = messages
        if self.responses:
            return self.responses.pop(0)
        return "[]"


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeChatParams:
    def __init__(self, by_chat):
        self._by_chat = dict(by_chat or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}


def _cand(**kw) -> dict:
    base = {"kind": "preference", "msg_ids": [1], "subject_user_id": 42,
            "confidence": "high", "epistemic": "fact",
            "pref_token": None, "topic": None}
    base.update(kw)
    return base


async def _db(tmp_path, name="exp.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _msg(db, *, chat_id=-100, user_id=42, text, ts=None,
               media_type="text", is_forward=False, reply_to_id=None) -> int:
    ts = int(time.time()) if ts is None else int(ts)
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, ?, ?, ?, 'u', ?, NULL)",
        (user_id, chat_id, text, reply_to_id, ts, media_type,
         int(is_forward)))
    await db.db.commit()
    return cursor.lastrowid


async def _payload_of(db) -> dict:
    cursor = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE kind = ? "
        "ORDER BY finished_at DESC, created_at DESC, rowid DESC LIMIT 1",
        ("experience.review",))
    row = await cursor.fetchone()
    return json.loads(row["payload"] or "{}")


async def _next_pass(db) -> None:
    """Сымитировать следующий плановый проход (предыдущий терминален)."""
    await db.db.execute(
        "UPDATE task_jobs SET status = 'completed', finished_at = 0 "
        "WHERE kind = ?", ("experience.review",))
    await db.db.commit()


async def _feedback_rows(db) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT feedback_id, source_kind, chat_id, signal_json, dedup_key "
        "FROM mca_experience_feedback ORDER BY rowid")
    return [dict(r) for r in await cursor.fetchall()]


async def _lessons(db) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT lesson_id, version, type, status, applicability "
        "FROM mca_lessons ORDER BY created_at, lesson_id")
    return [dict(r) for r in await cursor.fetchall()]


def _msg_ids_in_batch(llm: _FakeLLM) -> set[int]:
    """id сообщений, реально отправленных в user-контент батча."""
    content = llm.last_messages[1]["content"]
    out = set()
    for chunk in content.split("[msg:")[1:]:
        out.add(int(chunk.split(" ")[0]))
    return out


# ═══ (a) два последовательных job'а — РАЗНЫЕ следующие сообщения ═════════════

@pytest.mark.asyncio
async def test_a_two_consecutive_jobs_take_different_next_messages(tmp_path):
    hot_config.set_config_cache(_FakeHot({
        "memory.experience_drain_chats_per_pass": 4,
        "memory.experience_drain_per_chat_max": 10,
        # SXR-I2: тест проверяет границу ОДНОГО окна/прохода, не дренаж.
        "memory.experience_semantic_batches_per_run": 1,
    }))
    db = await _db(tmp_path, "a.db")
    try:
        ids = [await _msg(db, user_id=42, ts=1000 + i,
                          text=f"реплика номер {i}")
               for i in range(25)]
        llm1 = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm1) == "completed"
        first = _msg_ids_in_batch(llm1)
        payload1 = await _payload_of(db)
        cursor1 = payload1[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"]
        # проход ограничен пределом дренажа (≤10 строк одного чата в тесте)
        assert len(first) == 10
        assert first == set(ids[:10])
        await _next_pass(db)
        llm2 = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm2) == "completed"
        second = _msg_ids_in_batch(llm2)
        payload2 = await _payload_of(db)
        cursor2 = payload2[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"]
        # второй job НЕ повторяет окно первого и двигает позицию дальше
        assert second and not (first & second)
        assert second == set(ids[10:20])
        assert cursor2 > cursor1
        assert llm2.last_messages[1]["content"] != llm1.last_messages[1][
            "content"]
        # воронка честная по строкам: каждый проход выбрал свои 10 строк
        assert payload1["counters"]["semantic_selected"] == 10
        assert payload2["counters"]["semantic_selected"] == 10
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ (b) рестарт: после checkpoint и между insert и checkpoint ═══════════════

@pytest.mark.asyncio
async def test_b_restart_after_checkpoint_and_between_insert_and_checkpoint(
        tmp_path):
    path = tmp_path / "b.db"
    db = await _db(tmp_path, "b.db")
    m1 = await _msg(db, user_id=42, ts=1000, text="реплика для кандидата")
    llm = _FakeLLM([json.dumps([
        _cand(kind="preference", msg_ids=[m1], subject_user_id=42,
              pref_token="reply_length.short")], ensure_ascii=False)])
    assert await mj.tick_experience_review(db, llm=llm) == "completed"
    cursor_before = (await _payload_of(db))[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"]
    assert await _feedback_rows(db)
    # РЕСТАРТ процесса: новый сервис на том же durable-файле
    await db.close()
    db = DatabaseService(str(path))
    await db.initialize()
    try:
        payload = await _payload_of(db)
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == cursor_before
        # новый job наследует позицию и НЕ пересканирует уже пройденное
        m2 = await _msg(db, user_id=42, ts=2000, text="реплика после рестарта")
        llm2 = _FakeLLM()
        await _next_pass(db)
        assert await mj.tick_experience_review(db, llm=llm2) == "completed"
        # (b2) сбой между durable insert и checkpoint: checkpoint не сохранён
        m3 = await _msg(db, user_id=42, ts=3000, text="третья реплика")
        cand = _cand(kind="correction", msg_ids=[m3], subject_user_id=42,
                     epistemic="fact")
        original = mj.ExperienceReviewRunner._checkpoint

        async def _lost(self, job_id, payload):
            return None

        mj.ExperienceReviewRunner._checkpoint = _lost
        try:
            llm3 = _FakeLLM([json.dumps([cand], ensure_ascii=False)])
            await _next_pass(db)
            assert await mj.tick_experience_review(db, llm=llm3) == "completed"
        finally:
            mj.ExperienceReviewRunner._checkpoint = original
        rows_after_insert = await _feedback_rows(db)
        assert len(rows_after_insert) == 2       # durable insert состоялся
        # повторный проход с потерянным checkpoint → тот же кандидат отсечён
        await _next_pass(db)
        llm4 = _FakeLLM([json.dumps([cand], ensure_ascii=False)])
        assert await mj.tick_experience_review(db, llm=llm4) == "completed"
        payload = await _payload_of(db)
        assert payload["counters"]["semantic_duplicates"] >= 1
        assert len(await _feedback_rows(db)) == 2     # дубль не создан
        # позиция восстановлена и указывает за последнее сообщение
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] >= m3
        assert llm2.calls == 1
    finally:
        await db.close()


# ═══ (c) окно, где 10 из 10 строк отфильтрованы ══════════════════════════════

@pytest.mark.asyncio
async def test_c_fully_filtered_window_advances_pending_and_last_ts(tmp_path):
    db = await _db(tmp_path, "c.db")
    try:
        last_id = 0
        for i in range(4):
            last_id = await _msg(db, user_id=42, ts=1000 + i,
                                 text=f"фото {i}", media_type="photo")
        for i in range(3):
            last_id = await _msg(db, user_id=42, ts=1010 + i,
                                 text=f"переслано {i}", is_forward=True)
        for i in range(2):
            last_id = await _msg(db, user_id=42, ts=1020 + i,
                                 text=f"/command{i}")
        last_id = await _msg(db, user_id=42, ts=1030, text="   ")
        llm = _FakeLLM()
        before = int(time.time())
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        assert llm.calls == 0                    # в LLM ничего не ушло
        payload = await _payload_of(db)
        counters = payload["counters"]
        # строки учтены как ПРОЧИТАННЫЕ и отфильтрованные (не потеряны)
        assert counters["semantic_rows_read"] == 10
        assert counters["semantic_rows_ineligible"] == 10
        assert counters["semantic_selected"] == 0
        # позиция продвинута, phantom pending снят, drained обновил last_ts
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == last_id
        assert payload["semantic_pending"].get("-100") in (None, 0)
        assert int(payload["semantic_last_ts"]["-100"]) >= before
        assert payload["semantic_progress"]["backlog_rows"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_c2_empty_window_reconciles_phantom_pending(tmp_path):
    db = await _db(tmp_path, "c2.db")
    try:
        await _msg(db, user_id=42, ts=1000, text="одна реплика")
        assert await mj.tick_experience_review(db, llm=_FakeLLM()) == "completed"
        payload = await _payload_of(db)
        # искусственно оставляем фантомный pending за пределами последней
        # строки — как было при старом поведении «drained без пересчёта»
        payload["semantic_pending"] = {"-100": 5}
        payload["semantic_pending_since"] = {"-100": 1000}
        await db.db.execute(
            "UPDATE task_jobs SET payload = ? WHERE kind = ?",
            (json.dumps(payload), "experience.review"))
        await db.db.commit()
        await _next_pass(db)
        assert await mj.tick_experience_review(db, llm=_FakeLLM()) == "completed"
        payload = await _payload_of(db)
        assert payload["semantic_pending"].get("-100") in (None, 0)
        assert payload["counters"]["semantic_pending_reconciled"] >= 1
        assert payload["semantic_progress"]["backlog_rows"] == 0
    finally:
        await db.close()


# ═══ (d) 4 чата: один выключен, один пустой — не блокируют остальных ════════

@pytest.mark.asyncio
async def test_d_disabled_and_empty_chats_do_not_block_others(tmp_path):
    db = await _db(tmp_path, "d.db")
    hot_config.set_config_cache(_FakeHot(
        {"memory.experience_learning_enabled": True}))
    from services import chat_params
    chat_params.set_chat_params_cache(_FakeChatParams({
        -100: {"memory.experience_learning_enabled": False},
    }))
    try:
        a1 = await _msg(db, chat_id=-100, user_id=42, ts=1000,
                        text="выключенный чат реплика")
        b1 = await _msg(db, chat_id=-200, user_id=52, ts=1001,
                        text="включённый чат B реплика")
        # -300: «пустой» чат (нет сообщений вовсе) — инертен
        d1 = await _msg(db, chat_id=-400, user_id=62, ts=1002,
                        text="включённый чат D реплика")
        llm = _FakeLLM([json.dumps([
            _cand(kind="preference", msg_ids=[b1], subject_user_id=52,
                  pref_token="reply.slow_pace")], ensure_ascii=False)])
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        user_content = llm.last_messages[1]["content"]
        assert "chat:-200" in user_content and "chat:-400" in user_content
        assert "chat:-100" not in user_content
        payload = await _payload_of(db)
        # выключенный чат дренирован (deliberate skip), pending снят
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] >= a1
        assert payload["semantic_pending"].get("-100") in (None, 0)
        assert payload["counters"]["semantic_chats_disabled"] >= 1
        # включённые чаты обработаны и продвинуты
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-200"] >= b1
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-400"] >= d1
        assert payload["semantic_pending"] == {}
    finally:
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


# ═══ (e) SQL-сбой записи на второй записи ════════════════════════════════════

@pytest.mark.asyncio
async def test_e_write_failure_does_not_advance_and_retries_without_dupes(
        tmp_path, monkeypatch):
    db = await _db(tmp_path, "e.db")
    try:
        m1 = await _msg(db, user_id=42, ts=1000, text="первый кандидат")
        m2 = await _msg(db, user_id=42, ts=1001, text="второй кандидат")
        batch = json.dumps([
            _cand(kind="preference", msg_ids=[m1], subject_user_id=42,
                  pref_token="reply_length.short"),
            _cand(kind="preference", msg_ids=[m2], subject_user_id=42,
                  pref_token="reply.slow_pace"),
        ], ensure_ascii=False)
        original = me.ExperienceService.record_feedback
        calls = {"n": 0}

        async def flaky(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("sqlite: disk I/O error")
            return await original(self, **kwargs)

        monkeypatch.setattr(me.ExperienceService, "record_feedback", flaky)
        llm = _FakeLLM([batch])
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        rows = await _feedback_rows(db)
        assert len(rows) == 1                    # первая запись durable
        payload = await _payload_of(db)
        # позиция НЕ продвинута: батч не считается обработанным
        assert payload.get(f"{mj.SEMANTIC_CURSOR_PREFIX}-100", 0) == 0
        assert payload["semantic_pending"].get("-100") == 2
        assert payload["counters"]["semantic_write_failures"] >= 1
        # повтор без дублей: первый кандидат → duplicate, второй → accepted
        monkeypatch.setattr(me.ExperienceService, "record_feedback", original)
        await _next_pass(db)
        llm2 = _FakeLLM([batch])
        assert await mj.tick_experience_review(db, llm=llm2) == "completed"
        rows = await _feedback_rows(db)
        assert len(rows) == 2
        dedups = {r["dedup_key"] for r in rows}
        assert len(dedups) == 2                  # два разных кандидата
        payload = await _payload_of(db)
        assert payload["counters"]["semantic_duplicates"] == 1
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] >= m2
        assert payload["semantic_pending"].get("-100") in (None, 0)
    finally:
        await db.close()


# ═══ (f) invalid JSON vs валидный `[]` ═══════════════════════════════════════

def test_f_parse_typed_outcomes_unit():
    valid_empty = mj.parse_semantic_candidates_typed("[]")
    assert valid_empty["outcome"] == mj.SEMANTIC_PARSE_VALID_EMPTY
    assert valid_empty["candidates"] == []
    invalid = mj.parse_semantic_candidates_typed("извините, не могу")
    assert invalid["outcome"] == mj.SEMANTIC_PARSE_INVALID
    assert invalid["reason"] == mj.SEMANTIC_PARSE_REASON_NO_ARRAY
    broken = mj.parse_semantic_candidates_typed('[{"kind": "preference",}]')
    assert broken["outcome"] == mj.SEMANTIC_PARSE_INVALID
    assert broken["reason"] == mj.SEMANTIC_PARSE_REASON_JSON_ERROR
    not_list = mj.parse_semantic_candidates_typed('{"kind": "preference"}')
    assert not_list["outcome"] == mj.SEMANTIC_PARSE_INVALID
    garbage = mj.parse_semantic_candidates_typed('[{"kind": "personality"}]')
    assert garbage["outcome"] == mj.SEMANTIC_PARSE_INVALID
    assert garbage["reason"] == mj.SEMANTIC_PARSE_REASON_NO_USABLE
    good = mj.parse_semantic_candidates_typed(json.dumps([_cand(msg_ids=[7])]))
    assert good["outcome"] == mj.SEMANTIC_PARSE_VALID_CANDIDATES
    assert good["candidates"][0]["msg_ids"] == [7]
    # совместимый список остаётся прежним
    assert mj.parse_semantic_candidates("[]") == []
    assert len(mj.parse_semantic_candidates(json.dumps([_cand(msg_ids=[7])]))) == 1


@pytest.mark.asyncio
async def test_f_invalid_output_does_not_advance_but_valid_empty_does(tmp_path):
    db = await _db(tmp_path, "f.db")
    try:
        m1 = await _msg(db, user_id=42, ts=1000, text="реплика для разбора")
        llm = _FakeLLM(["я не могу вернуть json"])
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        # позиция стоит, pending сохранён, включён отложенный повтор
        assert payload.get(f"{mj.SEMANTIC_CURSOR_PREFIX}-100", 0) == 0
        assert payload["semantic_pending"].get("-100") == 1
        assert payload["counters"]["semantic_parse_invalid"] == 1
        assert payload["counters"]["semantic_parse_reasons"][
            mj.SEMANTIC_PARSE_REASON_NO_ARRAY] == 1
        retry = payload["semantic_retry"]["-100"]
        assert retry["attempts"] == 1 and retry["retry_at"] > int(time.time())
        assert await _feedback_rows(db) == []
        # отложенный чат не порождает пустых проходов: каденция не истекла,
        # планируемого бэклога нет → следующий тик честный `not_due`
        assert payload["semantic_progress"]["actionable_rows"] == 0
        assert await mj.tick_experience_review(db, llm=_FakeLLM()) == "not_due"
        # данные не потеряны: следующий проход (после окна отсрочки) разбирает
        payload["semantic_retry"] = {}
        await db.db.execute(
            "UPDATE task_jobs SET payload = ? WHERE kind = ?",
            (json.dumps(payload), "experience.review"))
        await db.db.commit()
        await _next_pass(db)
        llm2 = _FakeLLM(["[]"])                  # валидный пустой ответ
        assert await mj.tick_experience_review(db, llm=llm2) == "completed"
        payload = await _payload_of(db)
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] >= m1
        assert payload["counters"]["semantic_parse_valid_empty"] == 1
        assert payload["semantic_pending"].get("-100") in (None, 0)
    finally:
        await db.close()


# ═══ (g) OFF→ON→OFF без рестарта ════════════════════════════════════════════

@pytest.mark.asyncio
async def test_g_tick_registered_always_and_hot_toggle_without_restart(
        tmp_path, monkeypatch):
    db = await _db(tmp_path, "g.db")
    monkeypatch.setattr(mca_gates, "experience_review_enabled",
                        lambda: False)
    svc = mm.MemoryMaintenanceService(db, memory=None, llm=None, bot=None)
    try:
        svc.start()
        job = svc._scheduler.get_job(
            mm.MemoryMaintenanceService.JOB_EXPERIENCE_REVIEW_ID)
        assert job is not None, ("EXP-FIX-06: тик review обязан быть "
                                 "зарегистрирован независимо от гейта")
        assert job.max_instances == 1 and job.coalesce is True
        await _msg(db, user_id=42, ts=1000, text="отвечай короче, пожалуйста")
        # OFF: нуль работы — ни одной durable-задачи
        await svc._tick_experience_review()
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM task_jobs")
        assert int((await cursor.fetchone())["c"]) == 0
        assert await mj.tick_experience_review(db) == "disabled"
        # ON-hot без рестарта: тот же сервис/планировщик
        monkeypatch.setattr(mca_gates, "experience_review_enabled",
                            lambda: True)
        await svc._tick_experience_review()
        cursor = await db.db.execute(
            "SELECT status FROM task_jobs WHERE kind = ?", ("experience.review",))
        rows = [dict(r) for r in await cursor.fetchall()]
        assert len(rows) == 1 and rows[0]["status"] == "completed"
        # OFF-hot снова: новых задач нет, планировщик не падает
        monkeypatch.setattr(mca_gates, "experience_review_enabled",
                            lambda: False)
        await svc._tick_experience_review()
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM task_jobs WHERE kind = ?",
            ("experience.review",))
        assert int((await cursor.fetchone())["c"]) == 1
    finally:
        await svc.shutdown()
        await db.close()


# ═══ (h) LLM недоступен ═════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_h_llm_unavailable_stalls_position_honestly(tmp_path):
    db = await _db(tmp_path, "h.db")
    try:
        await _msg(db, user_id=42, ts=1000, text="отвечай короче")
        await _msg(db, user_id=42, ts=1001, text="невзрачная фраза")
        assert await mj.tick_experience_review(db, llm=None) == "completed"
        payload = await _payload_of(db)
        counters = payload["counters"]
        assert counters["semantic_llm_unavailable"] == 1
        assert counters["semantic_selected"] == 0
        # позиция/индекс семантики не двинуты, детерминированный контур жив
        assert payload.get(f"{mj.SEMANTIC_CURSOR_PREFIX}-100", 0) == 0
        assert counters["detector_detected"] == 1
        assert payload["semantic_progress"]["backlog_rows"] == 0
        # LLM появился → семантика догоняет с durable-позиции
        await _next_pass(db)
        llm = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload_of(db)
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] >= 1
        assert payload["counters"]["semantic_selected"] == 2
    finally:
        await db.close()


# ═══ (i) бэклог больше одного прохода ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_i_backlog_larger_than_one_pass_drains_by_portions(tmp_path):
    hot_config.set_config_cache(_FakeHot({
        "memory.experience_drain_chats_per_pass": 4,
        "memory.experience_drain_per_chat_max": 10,
        # SXR-I2: тест проверяет границу ОДНОГО окна/прохода, не дренаж.
        "memory.experience_semantic_batches_per_run": 1,
    }))
    db = await _db(tmp_path, "i.db")
    try:
        all_ids: set[int] = set()
        for chat_id in (-100, -200, -300):
            for i in range(15):
                all_ids.add(await _msg(db, chat_id=chat_id, user_id=42,
                                       ts=1000 + i,
                                       text=f"бэклог {chat_id} {i}"))
        seen: set[int] = set()
        llm1 = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm1) == "completed"
        first = _msg_ids_in_batch(llm1)
        seen |= first
        payload = await _payload_of(db)
        # один проход ограничен (тестовый предел 4 чата × 10 строк)
        assert len(first) == 3 * 10
        assert payload["semantic_progress"]["backlog_rows"] == 3 * 5
        assert payload["semantic_progress"]["backlog_chats"] == 3
        assert payload["semantic_progress"]["lag_seconds"] > 0
        assert payload["counters"]["semantic_throughput_rows"] == 30
        # EXP-FIX-02: накопленный бэклог планирует СЛЕДУЮЩУЮ порцию сразу,
        # не дожидаясь суточной каденции (job только что завершён)
        llm2 = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm2) == "completed"
        second = _msg_ids_in_batch(llm2)
        assert second and not (first & second)
        seen |= second
        payload = await _payload_of(db)
        assert payload["semantic_progress"]["backlog_rows"] == 0
        assert payload["semantic_progress"]["backlog_chats"] == 0
        # бэклог разобран → следующий тик снова подчиняется каденции
        assert await mj.tick_experience_review(db, llm=_FakeLLM()) == "not_due"
        # ни одно сообщение не потеряно и не обработано дважды
        assert seen == all_ids
        assert payload["counters"]["semantic_duplicates"] == 0
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ (j) дедуп не создаёт дубликат урока ════════════════════════════════════

@pytest.mark.asyncio
async def test_j_dedup_prevents_duplicate_lesson_creation(tmp_path):
    db = await _db(tmp_path, "j.db")
    try:
        m1 = await _msg(db, user_id=42, ts=1000,
                        text="давай короче, без простыней")
        batch = json.dumps([
            _cand(kind="preference", msg_ids=[m1], subject_user_id=42,
                  pref_token="reply_length.short")], ensure_ascii=False)
        assert await mj.tick_experience_review(
            db, llm=_FakeLLM([batch])) == "completed"
        pref_lessons = [x for x in await _lessons(db)
                        if x["type"] == "social_preference"]
        assert len(pref_lessons) == 1
        # тот же кандидат приходит снова (потерянный checkpoint) → урока нет
        original = mj.ExperienceReviewRunner._checkpoint

        async def _lost(self, job_id, payload):
            return None

        mj.ExperienceReviewRunner._checkpoint = _lost
        try:
            await _next_pass(db)
            assert await mj.tick_experience_review(
                db, llm=_FakeLLM([batch])) == "completed"
        finally:
            mj.ExperienceReviewRunner._checkpoint = original
        await _next_pass(db)
        assert await mj.tick_experience_review(
            db, llm=_FakeLLM([batch])) == "completed"
        payload = await _payload_of(db)
        assert payload["counters"]["semantic_duplicates"] >= 1
        assert len(await _feedback_rows(db)) == 1
        pref_lessons = [x for x in await _lessons(db)
                        if x["type"] == "social_preference"]
        assert len(pref_lessons) == 1
        assert pref_lessons[0]["status"] == "active"
        assert pref_lessons[0]["applicability"] == \
            "user:42 pref:reply_length.short"
    finally:
        await db.close()


# ═══ EXP-FIX-09: два разных вида сигнала одной реплики не сливаются ═════════

@pytest.mark.asyncio
async def test_exp09_two_signal_kinds_one_message_stay_separate(tmp_path):
    db = await _db(tmp_path, "e09.db")
    try:
        m1 = await _msg(db, user_id=42, ts=1000,
                        text="не так — я просил короче и без таблиц")
        batch = json.dumps([
            _cand(kind="preference", msg_ids=[m1], subject_user_id=42,
                  pref_token="reply_length.short"),
            _cand(kind="correction", msg_ids=[m1], subject_user_id=42,
                  epistemic="fact"),
        ], ensure_ascii=False)
        assert await mj.tick_experience_review(
            db, llm=_FakeLLM([batch])) == "completed"
        rows = await _feedback_rows(db)
        assert len(rows) == 2                     # оба сигнала durable
        assert len({r["dedup_key"] for r in rows}) == 2
        kinds = {json.loads(r["signal_json"])["kind"] for r in rows}
        assert kinds == {"preference", "correction"}
        payload = await _payload_of(db)
        assert payload["counters"]["semantic_duplicates"] == 0
        # повтор того же набора идемпотентен
        original = mj.ExperienceReviewRunner._checkpoint

        async def _lost(self, job_id, payload_):
            return None

        mj.ExperienceReviewRunner._checkpoint = _lost
        try:
            await _next_pass(db)
            assert await mj.tick_experience_review(
                db, llm=_FakeLLM([batch])) == "completed"
        finally:
            mj.ExperienceReviewRunner._checkpoint = original
        await _next_pass(db)
        assert await mj.tick_experience_review(
            db, llm=_FakeLLM([batch])) == "completed"
        assert len(await _feedback_rows(db)) == 2
        assert (await _payload_of(db))["counters"]["semantic_duplicates"] == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_exp09_two_preferences_one_message_distinct_carriers(tmp_path):
    """Две РАЗНЫЕ конкретные формы предпочтения в одной реплике — два
    кандидата; повтор той же формы остаётся дублем."""
    db = await _db(tmp_path, "e09b.db")
    try:
        m1 = await _msg(db, user_id=42, ts=1000,
                        text="короче и без таблиц, пожалуйста")
        batch = json.dumps([
            _cand(kind="preference", msg_ids=[m1], subject_user_id=42,
                  pref_token="reply_length.short"),
            _cand(kind="preference", msg_ids=[m1], subject_user_id=42,
                  pref_token="reply.no_tables"),
        ], ensure_ascii=False)
        assert await mj.tick_experience_review(
            db, llm=_FakeLLM([batch])) == "completed"
        rows = await _feedback_rows(db)
        assert len(rows) == 2
        tokens = {json.loads(r["signal_json"])["preference"] for r in rows}
        assert tokens == {"reply_length.short", "reply.no_tables"}
        assert len({r["dedup_key"] for r in rows}) == 2
        # повтор тех же форм → ни одной новой строки
        original = mj.ExperienceReviewRunner._checkpoint

        async def _lost(self, job_id, payload_):
            return None

        mj.ExperienceReviewRunner._checkpoint = _lost
        try:
            await _next_pass(db)
            assert await mj.tick_experience_review(
                db, llm=_FakeLLM([batch])) == "completed"
        finally:
            mj.ExperienceReviewRunner._checkpoint = original
        await _next_pass(db)
        assert await mj.tick_experience_review(
            db, llm=_FakeLLM([batch])) == "completed"
        assert len(await _feedback_rows(db)) == 2
        payload = await _payload_of(db)
        assert payload["counters"]["semantic_duplicates"] == 2
    finally:
        await db.close()


# ═══ EXP-FIX-01: полный semantic checkpoint наследуется новым job'ом ══════

@pytest.mark.asyncio
async def test_exp01_new_job_inherits_full_semantic_checkpoint(tmp_path):
    hot_config.set_config_cache(_FakeHot({
        "memory.experience_drain_chats_per_pass": 4,
        "memory.experience_drain_per_chat_max": 10,
        # SXR-I2: тест проверяет границу ОДНОГО окна/прохода, не дренаж.
        "memory.experience_semantic_batches_per_run": 1,
    }))
    db = await _db(tmp_path, "e01.db")
    try:
        ids = [await _msg(db, chat_id=-100, user_id=42, ts=1000 + i,
                          text=f"строка {i}") for i in range(12)]
        await _msg(db, chat_id=-200, user_id=42, ts=2000, text="другой чат")
        assert await mj.tick_experience_review(db, llm=_FakeLLM()) == "completed"
        first = await _payload_of(db)
        assert first[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[9]
        assert first["semantic_watermark"] >= ids[-1]
        # новый job (свежий payload из enqueue) НЕ начинает pass с начала
        llm2 = _FakeLLM()
        await _next_pass(db)
        assert await mj.tick_experience_review(db, llm=llm2) == "completed"
        batch2 = _msg_ids_in_batch(llm2)
        assert batch2 == {ids[10], ids[11]}
        payload = await _payload_of(db)
        assert payload["semantic_state_version"] == mj.SEMANTIC_STATE_VERSION
        assert payload[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[-1]
        # наследование идемпотентно: повторное чтение payload не откатывает
        runner = mj.ExperienceReviewRunner(db)
        job_id = await mj.enqueue_experience_review(db)
        loaded1 = await runner._load_payload(job_id)
        loaded2 = await runner._load_payload(job_id)
        assert loaded1[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[-1]
        assert loaded2[f"{mj.SEMANTIC_CURSOR_PREFIX}-100"] == ids[-1]
        assert loaded1["semantic_watermark"] == loaded2["semantic_watermark"]
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ EXP-FIX-07: справедливая ротация окна resume ══════════════════════════

@pytest.mark.asyncio
async def test_exp07_resume_window_rotates_over_all_candidates(
        tmp_path, monkeypatch):
    db = await _db(tmp_path, "e07.db")
    try:
        monkeypatch.setattr(mca_gates, "experience_review_batch_max",
                            lambda: 1)
        svc = me.get_service(db)
        lesson_ids = []
        for i in range(3):
            lid, _ver = await svc.lesson.propose(
                type="tool_usage", scope="chat",
                rule_key="retry_after_typed_failure", scope_chat_id=-100,
                applicability=f"tool:t{i}")
            lesson_ids.append(lid)
        assert len(await _lessons(db)) == 3
        # порядок ротации — тот же, что в SQL (created_at, lesson_id)
        ordered = [row["lesson_id"] for row in await _lessons(db)]
        visited = []
        rejects = []
        for _ in range(4):
            await _next_pass(db)
            await mj.tick_experience_review(db, llm=_FakeLLM())
            payload = await _payload_of(db)
            cursor = payload.get(mj.RESUME_CURSOR_KEY)
            visited.append(cursor["lesson_id"] if cursor else None)
            rejects.append(int(payload["counters"]["resume_rejected"]))
        # за круг каждая строка попала в окно ровно один раз (ротация)
        assert visited[:3] == ordered
        assert visited[3] is None            # строк за курсором нет → wrap
        assert rejects[:3] == [1, 1, 1]      # каждая строка получила попытку
        assert rejects[3] == 0
        # ни одна строка не активирована и не удалена, чтобы «двигать прогресс»
        lessons = await _lessons(db)
        assert len(lessons) == 3
        assert {row["status"] for row in lessons} == {"candidate"}
    finally:
        await db.close()


# ═══ EXP-FIX-10: backpressure индекса >cap чатов без потери сообщений ══════

@pytest.mark.asyncio
async def test_exp10_many_chats_backpressure_no_message_lost(tmp_path,
                                                            monkeypatch):
    path = tmp_path / "e10.db"
    db = await _db(tmp_path, "e10.db")
    monkeypatch.setattr(mj, "semantic_pending_chat_cap", lambda: 2)
    try:
        all_ids: set[int] = set()
        for chat_id in (-100, -200, -300, -400):
            for i in range(2):
                all_ids.add(await _msg(db, chat_id=chat_id, user_id=42,
                                       ts=1000 + i,
                                       text=f"чат {chat_id} строка {i}"))
        seen: set[int] = set()
        llm = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        seen |= _msg_ids_in_batch(llm)
        payload = await _payload_of(db)
        # индекс ограничен, discovery остановлен ДО неиндексированной строки
        assert len(payload["semantic_pending"]) <= 2
        assert payload["counters"]["semantic_discovery_backpressure"] >= 1
        assert payload["semantic_watermark"] < max(all_ids)
        # РЕСТАРТ: durable-состояние переживает перезапуск, ничего не теряется
        await db.close()
        db = DatabaseService(str(path))
        await db.initialize()
        for _ in range(6):
            await _next_pass(db)
            llm = _FakeLLM()
            assert await mj.tick_experience_review(db, llm=llm) == "completed"
            seen |= _msg_ids_in_batch(llm)
            payload = await _payload_of(db)
            if payload["semantic_progress"]["backlog_rows"] == 0:
                break
        payload = await _payload_of(db)
        assert payload["semantic_watermark"] == max(all_ids)
        assert payload["semantic_progress"]["backlog_rows"] == 0
        assert seen == all_ids               # ни одно сообщение не потеряно
    finally:
        await db.close()


# ═══ EXP-FIX-10: >64 чатов — ни один ключ не теряется (старый баг) ════════

@pytest.mark.asyncio
async def test_exp10b_more_than_64_chats_no_pending_key_dropped(tmp_path):
    hot_config.set_config_cache(_FakeHot({
        "memory.experience_drain_chats_per_pass": 4,
        "memory.experience_drain_per_chat_max": 10,
        # SXR-I2: тест проверяет границу ОДНОГО окна/прохода, не дренаж.
        "memory.experience_semantic_batches_per_run": 1,
    }))
    db = await _db(tmp_path, "e10b.db")
    try:
        chats = [-(1000 + i) for i in range(80)]
        all_ids: set[int] = set()
        for chat_id in chats:
            all_ids.add(await _msg(db, chat_id=chat_id, user_id=42,
                                   ts=1000, text=f"реплика чата {chat_id}"))
        llm = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        seen = _msg_ids_in_batch(llm)
        payload = await _payload_of(db)
        # индекс хранит ВСЕ ожидающие чаты: старый код срезал его до 64 и
        # терял сообщения; здесь потерянных ключей нет
        assert payload["counters"]["semantic_scanned"] == 80
        assert payload["semantic_watermark"] == max(all_ids)
        # обработано 4 чата (предел прохода), остальные 76 остаются в индексе
        assert len(payload["semantic_pending"]) == 80 - 4
        assert len(seen) == 4
        # догоняем оставшиеся чаты: каждое сообщение обработано ровно один раз
        for _ in range(30):
            await _next_pass(db)
            llm = _FakeLLM()
            assert await mj.tick_experience_review(db, llm=llm) == "completed"
            batch = _msg_ids_in_batch(llm)
            assert not (batch & seen)          # без повторной обработки
            seen |= batch
            if (await _payload_of(db))["semantic_progress"][
                    "backlog_rows"] == 0:
                break
        assert seen == all_ids
        payload = await _payload_of(db)
        assert payload["semantic_pending"] == {}
        assert payload["counters"]["semantic_duplicates"] == 0
    finally:
        hot_config.set_config_cache(None)
        await db.close()


# ═══ горячие пределы дренажа (EXP-FIX-02) ══════════════════════════════════

@pytest.mark.asyncio
async def test_exp02_drain_limits_are_hot_configurable(tmp_path):
    db = await _db(tmp_path, "e02.db")
    hot_config.set_config_cache(_FakeHot({
        "memory.experience_drain_chats_per_pass": 1,
        "memory.experience_drain_per_chat_max": 3,
        "memory.experience_semantic_batches_per_run": 1,
    }))
    try:
        for i in range(5):
            await _msg(db, chat_id=-100, user_id=42, ts=1000 + i,
                       text=f"чат A {i}")
        for i in range(5):
            await _msg(db, chat_id=-200, user_id=42, ts=2000 + i,
                       text=f"чат B {i}")
        llm = _FakeLLM()
        assert await mj.tick_experience_review(db, llm=llm) == "completed"
        first = _msg_ids_in_batch(llm)
        assert len(first) == 3                     # per_chat_max из настройки
        assert len({x for x in first}) == 3
        payload = await _payload_of(db)
        # второй чат не тронут этим проходом (chats_per_pass=1)
        assert payload["semantic_progress"]["backlog_chats"] == 2
        assert mj.semantic_drain_limits() == (1, 3)
    finally:
        hot_config.set_config_cache(None)
        await db.close()
