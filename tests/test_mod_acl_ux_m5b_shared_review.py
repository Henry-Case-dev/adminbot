"""M5B / MAC-EXP-08 — shared review при GLOBAL OFF + CHAT ON.

Контракт (MOD-ACL-UX-01 §2.1/§2.3.1, EXP-FIX-08):
* GLOBAL — наследуемый default, не запрет: GLOBAL OFF + явный CHAT ON
  обрабатывается shared worker'ом;
* GLOBAL ON + CHAT OFF — только этот чат выключен, worker/индекс живы;
* review_enabled() не блокирует job до выбора чата; аварийные env-оси
  остаются отдельными;
* capture, detector и semantic используют единый
  `learning_enabled_for_chat`; stored overrides не переписываются.

TEST-LIFECYCLE: CONTRACT owner=MOD-ACL-UX-01/MAC-EXP-08
"""
import copy
import json

import pytest

from services import chat_params, hot_config, mca_gates
from services import mca_experience as me
from services import mca_experience_jobs as jobs
from services.database import DatabaseService

KEY = "memory.experience_learning_enabled"


class _Cache:
    def __init__(self, by_chat=None):
        self.by_chat = copy.deepcopy(by_chat or {})

    async def get_chat_params(self, chat_id):
        data = self.by_chat.get(int(chat_id), {})
        return {"overrides": dict(data.get("overrides") or {}),
                "gates": dict(data.get("gates") or {})}

    async def get_chat_params_checked(self, chat_id):
        return await self.get_chat_params(chat_id), True

    async def invalidate_chat(self, chat_id):
        return None


@pytest.fixture
def world(monkeypatch):
    class World:
        globals: dict = {}
        env: dict = {}

    w = World()
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: w.globals.get(key, default))
    monkeypatch.setattr(mca_gates, "experience_lessons_enabled",
                        lambda: w.env.get("MCA_EXPERIENCE_LESSONS_ENABLED",
                                          True))
    monkeypatch.setattr(mca_gates, "experience_review_enabled",
                        lambda: w.env.get("MCA_EXPERIENCE_REVIEW_ENABLED",
                                          True))
    yield w
    chat_params.set_chat_params_cache(None)


def _root(overrides=None):
    return {"overrides": dict(overrides or {}), "gates": {}}


def _set_chat(by_chat):
    chat_params.set_chat_params_cache(_Cache(by_chat))


async def _db(tmp_path, name="m5b.db"):
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _msg(db, chat_id, text, ts=1000):
    cur = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (42, ?, ?, NULL, ?, 'text', 'u', 0, NULL)",
        (chat_id, text, int(ts)))
    await db.db.commit()
    return cur.lastrowid


async def _payload(db):
    cur = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE kind = ? "
        "ORDER BY COALESCE(finished_at, updated_at, created_at) DESC, "
        "rowid DESC LIMIT 1", (jobs.REVIEW_JOB_KIND,))
    return json.loads((await cur.fetchone())["payload"] or "{}")


async def _feedback_chats(db):
    cur = await db.db.execute(
        "SELECT chat_id, COUNT(*) AS c FROM mca_experience_feedback "
        "GROUP BY chat_id")
    return {int(r["chat_id"]): int(r["c"]) for r in await cur.fetchall()}


class _FakeLLM:
    def __init__(self, response="[]"):
        self.response = response
        self.calls = 0
        self.prompts = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.prompts.append(str(messages[1]["content"]))
        return self.response


@pytest.mark.asyncio
async def test_review_enabled_not_blocked_by_global_off(world, tmp_path):
    world.globals = {KEY: False}
    _set_chat({-100: _root({KEY: True})})
    assert jobs.review_enabled() is True
    db = await _db(tmp_path, "gate.db")
    try:
        await _msg(db, -100, "нет, отвечай короче")
        job_id = await jobs.enqueue_experience_review(db)
        assert job_id, "job должен ставиться при GLOBAL OFF"
        assert await jobs.tick_experience_review(
            db, llm=_FakeLLM()) == "completed"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_global_off_chat_on_processes_only_enabled_chat(
        world, tmp_path):
    world.globals = {KEY: False}
    _set_chat({
        -100: _root({KEY: True}),      # явный ON при GLOBAL OFF
        -200: _root({}),               # INHERIT → OFF
    })
    db = await _db(tmp_path, "on.db")
    try:
        id_on = await _msg(db, -100, "нет, отвечай короче")
        id_off = await _msg(db, -200, "нет, отвечай короче")
        llm = _FakeLLM()
        assert await jobs.tick_experience_review(db, llm=llm) == "completed"
        feedback = await _feedback_chats(db)
        assert feedback.get(-100, 0) >= 1
        assert feedback.get(-200, 0) == 0
        payload = await _payload(db)
        assert payload["counters"]["detector_detected"] >= 1
        assert payload[f"{jobs.SEMANTIC_CURSOR_PREFIX}-100"] >= id_on
        assert payload[f"{jobs.SEMANTIC_CURSOR_PREFIX}-200"] >= id_off
        assert llm.calls >= 1
        assert any("chat:-100" in prompt for prompt in llm.prompts)
        assert not any("chat:-200" in prompt for prompt in llm.prompts)
        # GLOBAL OFF не переписан в stored override.
        stored = await chat_params.get_chat_params_cache().get_chat_params(-200)
        assert KEY not in (stored.get("overrides") or {})
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_global_on_chat_off_does_not_process_but_worker_alive(
        world, tmp_path):
    world.globals = {KEY: True}
    _set_chat({
        -100: _root({KEY: False}),     # только этот чат OFF
        -200: _root({}),               # INHERIT → ON
    })
    db = await _db(tmp_path, "off.db")
    try:
        await _msg(db, -100, "нет, отвечай короче")
        id_on = await _msg(db, -200, "нет, отвечай короче")
        llm = _FakeLLM()
        assert await jobs.tick_experience_review(db, llm=llm) == "completed"
        feedback = await _feedback_chats(db)
        assert feedback.get(-100, 0) == 0
        assert feedback.get(-200, 0) >= 1
        payload = await _payload(db)
        assert payload[f"{jobs.SEMANTIC_CURSOR_PREFIX}-200"] >= id_on
        assert not any("chat:-100" in prompt for prompt in llm.prompts)
        assert any("chat:-200" in prompt for prompt in llm.prompts)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_global_off_no_enabled_chat_is_inert_but_not_disabled(
        world, tmp_path):
    world.globals = {KEY: False}
    _set_chat({-100: _root({}), -200: _root({})})
    db = await _db(tmp_path, "inert.db")
    try:
        await _msg(db, -100, "нет, отвечай короче")
        llm = _FakeLLM()
        status = await jobs.tick_experience_review(db, llm=llm)
        assert status == "completed"
        assert llm.calls == 0
        assert await _feedback_chats(db) == {}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_global_on_chat_off_no_lessons_from_existing_episodes(
        world, tmp_path):
    world.globals = {KEY: True}
    _set_chat({-100: _root({KEY: False}), -200: _root({})})
    db = await _db(tmp_path, "proposal.db")
    try:
        svc = me.get_service(db)
        for chat_id in (-100, -200):
            await svc.capture_episode(
                chat_id=chat_id, task_type="feedback",
                trace_id=f"m5b:{chat_id}",
                outcome_kind="failure", outcome_source="explicit",
                decision={"reason_code": "correction"})
        assert await jobs.tick_experience_review(
            db, llm=_FakeLLM()) == "completed"
        cur = await db.db.execute(
            "SELECT scope_chat_id, COUNT(*) AS c FROM mca_lessons "
            "GROUP BY scope_chat_id")
        lessons = {int(r["scope_chat_id"]): int(r["c"])
                   for r in await cur.fetchall()
                   if r["scope_chat_id"] is not None}
        assert lessons.get(-100, 0) == 0
        assert lessons.get(-200, 0) >= 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_global_off_chat_on_lesson_retrievable_for_enabled_chat(
        world, tmp_path):
    world.globals = {KEY: False}
    _set_chat({-100: _root({KEY: True}), -200: _root({})})
    db = await _db(tmp_path, "retrieval.db")
    try:
        await _msg(db, -100, "нет, отвечай короче")
        await _msg(db, -200, "нет, отвечай короче")
        assert await jobs.tick_experience_review(
            db, llm=_FakeLLM()) == "completed"
        svc = me.get_service(db)
        sel = await svc.lesson.select_for_context(
            chat_id=-100, user_id=42,
            query="учитывать предпочтение участника")
        assert len(sel.lessons) == 1
        sel_off = await svc.lesson.select_for_context(
            chat_id=-200, user_id=42,
            query="учитывать предпочтение участника")
        assert sel_off.lessons == ()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_global_off_chat_on_semantic_candidate_accepted(
        world, tmp_path):
    world.globals = {KEY: False}
    _set_chat({-100: _root({KEY: True}), -200: _root({})})
    db = await _db(tmp_path, "sem.db")
    try:
        mid = await _msg(db, -100, "предпочитаю краткие ответы")
        await _msg(db, -200, "предпочитаю краткие ответы")
        cand = {"kind": "preference", "msg_ids": [mid],
                "subject_user_id": 42, "confidence": "high",
                "epistemic": "fact", "pref_token": "style.short",
                "topic": None}
        llm = _FakeLLM(json.dumps([cand]))
        assert await jobs.tick_experience_review(db, llm=llm) == "completed"
        payload = await _payload(db)
        assert payload["counters"]["semantic_candidates"] >= 1
        feedback = await _feedback_chats(db)
        assert feedback.get(-100, 0) >= 1
        assert feedback.get(-200, 0) == 0
    finally:
        await db.close()
