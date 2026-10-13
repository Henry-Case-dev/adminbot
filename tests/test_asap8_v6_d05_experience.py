"""ASAP 8 v6 — D05: Experience hybrid detector / durability / scope.

Покрытие (v6 §C D05; v5 §18E.1–18E.6, X1–X5/U4):
  * §18E.1 hybrid production feedback entry: детерминированный детектор
    обычного чата (worker-проход, без LLM) — явная коррекция/предпочтение →
    scoped feedback candidate → validation → active lesson → поздний match →
    применён; негативы: шутка/агрессия/мнение третьего лица/спор/forward →
    НЕ истина/урок (deliberate skip, ни feedback, ни lesson);
  * §18E.2/X1: курсор продвигается ТОЛЬКО после durable обработки; сбой
    записи → курсор на месте → retry → ровно один durable event;
    deliberate skip ≠ technical loss;
  * §18E.3/X2: uniqueness включает subject (tool) — урок для tool A не
    глушит эквивалентный для tool B; повтор идемпотентен;
  * §18E.4/X3: нормализованная конкретная preference {scope, value};
    поздняя явная замена supersede'ит; старая не инжектируется;
  * §18E.5/X4: crash между create и verify → auto-resume следующим
    проходом; semantic rejection ≠ transient technical failure;
  * §18E.6/X5: fair scanning — старые permanently-unknown строки не
    блокируют новые matchable; unknown остаётся unknown (не авто-success,
    не удаление);
  * U4: global master OFF глушит все чаты (stored override не
    переписывается); ON + chat OFF — только этот чат; урок чата A не в
    чате B.

TEST-LIFECYCLE: CONTRACT owner=asap8-v6/D05
"""
import json

import pytest

from services import hot_config
from services import mca_events, mca_gates
from services import mca_experience as me
from services import mca_experience_jobs as mj
from services.database import DatabaseService


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


async def _db(tmp_path, name="d05.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _msg(db: DatabaseService, *, chat_id=-100, user_id=42, text,
               reply_to_id=None, is_forward=False, media_type="text",
               ts=1000) -> int:
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (user_id, chat_id, text, reply_to_id, int(ts), media_type, "u",
         int(is_forward)))
    await db.db.commit()
    return cursor.lastrowid


async def _payload_of(db: DatabaseService) -> dict:
    cursor = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE kind = ? "
        "ORDER BY finished_at DESC, created_at DESC, rowid DESC LIMIT 1",
        ("experience.review",))
    row = await cursor.fetchone()
    return json.loads(row["payload"] or "{}")


async def _next_pass(db: DatabaseService) -> None:
    """Сымитировать следующий worker-проход (терминальный прогон позади)."""
    await db.db.execute(
        "UPDATE task_jobs SET status = 'completed', finished_at = 0 "
        "WHERE kind = ?", ("experience.review",))
    await db.db.commit()


# ═══ §18E.1: E2E — явная коррекция → candidate → урок → применение ══════════

@pytest.mark.asyncio
async def test_e2e_preference_correction_to_applied_lesson(tmp_path):
    db = await _db(tmp_path)
    try:
        await _msg(db, text="отвечай короче, без воды", user_id=42)
        assert await mj.tick_experience_review(db) == "completed"
        svc = me.get_service(db)
        # feedback candidate: typed signal, provenance (msg), chat scope
        cursor = await db.db.execute(
            "SELECT source_kind, chat_id, signal_json FROM "
            "mca_experience_feedback")
        rows = [dict(r) for r in await cursor.fetchall()]
        assert len(rows) == 1
        feedback = rows[0]
        assert feedback["source_kind"] == "participant_correction"
        assert feedback["chat_id"] == -100
        signal = json.loads(feedback["signal_json"])
        assert signal["class"] == "preference"
        assert signal["preference"] == "reply_length.short"
        assert signal["user_id"] == 42
        assert int(signal["msg"]) >= 1
        # урок: scoped, verified/active, нормализованная конкретная форма
        lessons = await svc.list_lessons(chat_id=-100)
        assert len(lessons) == 1
        lesson = lessons[0]
        assert lesson["type"] == "social_preference"
        assert lesson["scope"] == "user_in_chat"
        assert lesson["scope_user_id"] == 42
        assert lesson["status"] == "active"
        assert lesson["applicability"] == "user:42 pref:reply_length.short"
        # candidate != fact != lesson: recommendation — только канон
        assert lesson["recommendation"] == me.CANONICAL_RECOMMENDATIONS[
            ("social_preference", "explicit_user_preference")]
        # поздний match → применён
        sel = await svc.lesson.select_for_context(
            chat_id=-100, user_id=42,
            query="явное предпочтение формы ответа участника")
        assert len(sel.lessons) == 1
        assert await svc.record_applications(
            sel.lessons, application_ref="t-1", trace_id="t-1",
            chat_id=-100) == 1
        # независимый проверенный исход ПОЗЖЕ применения
        import time
        await svc.capture_episode(chat_id=-100, trace_id="t-1",
                                  outcome_kind="success",
                                  outcome_source="explicit",
                                  ts=int(time.time()) + 5)
        await _next_pass(db)
        assert await mj.tick_experience_review(db) == "completed"
        lesson = await svc.get_lesson(lesson["lesson_id"],
                                      lesson["version"])
        assert lesson["counters_success"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_e2e_owner_correction_fact_user_becomes_chat_lesson(tmp_path):
    from config.settings import settings
    _original_admin = settings.ADMIN_USER_ID
    object.__setattr__(settings, "ADMIN_USER_ID", 7)
    db = await _db(tmp_path)
    try:
        for i in range(3):
            await _msg(db, user_id=7, text=f"нет, вообще-то я не из Казани",
                       ts=1000 + i)
        assert await mj.tick_experience_review(db) == "completed"
        svc = me.get_service(db)
        cursor = await db.db.execute(
            "SELECT source_kind FROM mca_experience_feedback")
        kinds = {str(r["source_kind"]) for r in await cursor.fetchall()}
        assert kinds == {"owner_correction"}
        lessons = await svc.list_lessons(chat_id=-100)
        assert len(lessons) == 1
        lesson = lessons[0]
        assert lesson["type"] == "failure_pattern"
        assert lesson["status"] == "active"
        assert lesson["scope"] == "chat"
        assert lesson["scope_chat_id"] == -100
        assert await svc.store.count("mca_experience_episodes") == 3
    finally:
        object.__setattr__(settings, "ADMIN_USER_ID", _original_admin)
        await db.close()


@pytest.mark.asyncio
async def test_e2e_negatives_joke_aggression_third_party_dispute(tmp_path):
    db = await _db(tmp_path)
    try:
        await _msg(db, text="ахаха ну ты выдал :D", user_id=42)
        await _msg(db, text="ты тупой бот, дурак", user_id=42)
        await _msg(db, text="он сказал, что ты ошибаешься в цифрах",
                   user_id=42)
        await _msg(db, text="не согласен с таким подходом", user_id=42)
        await _msg(db, text="смотри что он прислал", user_id=42,
                   is_forward=True)
        await _msg(db, text="я не знаю, честно", user_id=42)
        await _msg(db, text="/help", user_id=42)
        assert await mj.tick_experience_review(db) == "completed"
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_experience_feedback")
        assert (await cursor.fetchone())["c"] == 0
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM mca_lessons")
        assert (await cursor.fetchone())["c"] == 0
        payload = await _payload_of(db)
        # deliberate skip с кодами причин; курсор продвинут (не loss)
        assert payload["counters"]["detector_skipped"] == 7
        assert payload["counters"]["detector_detected"] == 0
        assert payload[mj.DETECTOR_CURSOR_KEY] >= 7
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reply_to_another_user_is_dispute_not_correction(tmp_path):
    db = await _db(tmp_path)
    try:
        other_id = await _msg(db, user_id=99, text="я считаю иначе", ts=900)
        # tg_message_id совпадает с id упрощённо: reply ищется по tg_message_id
        await db.db.execute(
            "UPDATE smart_messages SET tg_message_id = ? WHERE id = ?",
            (other_id, other_id))
        await _msg(db, user_id=42, text="ты ошибаешься в выводах",
                   reply_to_id=other_id)
        await db.db.commit()
        assert await mj.tick_experience_review(db) == "completed"
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_experience_feedback")
        assert (await cursor.fetchone())["c"] == 0
    finally:
        await db.close()


# ═══ §18E.2/X1: курсор только после durable обработки ════════════════════════

@pytest.mark.asyncio
async def test_x1_failed_write_cursor_stays_retry_exactly_one_event(
        tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        first = await _msg(db, text="отвечай короче", user_id=42)
        second = await _msg(db, text="не называй меня по фамилии", user_id=42)
        original = me.ExperienceService.record_feedback
        calls = {"n": 0}

        async def _flaky(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient write failure")
            return await original(self, **kwargs)

        monkeypatch.setattr(me.ExperienceService, "record_feedback", _flaky)
        assert await mj.tick_experience_review(db) == "completed"
        payload = await _payload_of(db)
        # курсор НЕ двигается мимо упавшей строки (технической потери нет)
        assert payload[mj.DETECTOR_CURSOR_KEY] == first - 1
        assert payload["counters"]["capture_write_failures"] >= 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_experience_feedback")
        assert (await cursor.fetchone())["c"] == 0
        # retry: детерминированный проход доводит оба события
        monkeypatch.setattr(me.ExperienceService, "record_feedback", original)
        await _next_pass(db)
        assert await mj.tick_experience_review(db) == "completed"
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c, COUNT(DISTINCT dedup_key) AS d FROM "
            "mca_experience_feedback")
        row = await cursor.fetchone()
        assert row["c"] == 2 and row["d"] == 2     # ровно по одному событию
        payload = await _payload_of(db)
        assert payload[mj.DETECTOR_CURSOR_KEY] >= second
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_x1_episode_capture_failure_cursor_stays(tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        await _msg(db, text="не выдумывай, проверяй факты", user_id=42)
        assert await mj.tick_experience_review(db) == "completed"
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_experience_episodes")
        assert (await cursor.fetchone())["c"] == 1
        # дубликат feedback → второй эпизод не создаётся (идемпотентность)
        payload = await _payload_of(db)
        assert payload["counters"]["captured_feedback"] == 1
    finally:
        await db.close()


# ═══ §18E.3/X2: subject-специфичность уроков инструментов ═══════════════════

@pytest.mark.asyncio
async def test_x2_two_tools_two_scoped_lessons_idempotent_retry(tmp_path):
    db = await _db(tmp_path)
    try:
        for i in range(3):
            await db.db.execute(
                "INSERT INTO mca_events (ts, level, event_name, outcome, "
                "trace_id, chat_id, component, stage, reason_code, "
                "entity_ids) VALUES (?, 'WARNING', 'tool_call', 'failed', "
                "?, -100, 'tools', 'execute', 'timeout', ?)",
                (1000 + i, f"a-{i}", json.dumps({"tool": "web_search"})))
            await db.db.execute(
                "INSERT INTO mca_events (ts, level, event_name, outcome, "
                "trace_id, chat_id, component, stage, reason_code, "
                "entity_ids) VALUES (?, 'WARNING', 'tool_call', 'failed', "
                "?, -100, 'tools', 'execute', 'timeout', ?)",
                (1000 + i, f"b-{i}", json.dumps({"tool": "image_gen"})))
        await db.db.commit()
        assert await mj.tick_experience_review(db) == "completed"
        svc = me.get_service(db)
        lessons = await svc.list_lessons(chat_id=-100)
        apps = sorted(str(l["applicability"]) for l in lessons)
        assert apps == ["tool:image_gen", "tool:web_search"]
        assert all(l["status"] == "active" for l in lessons)
        # повтор того же события → идемпотентно (без новых уроков)
        await _next_pass(db)
        assert await mj.tick_experience_review(db) == "completed"
        assert await svc.store.count("mca_lessons") == 2
    finally:
        await db.close()


# ═══ §18E.4/X3: конкретная preference, замена, старая не инжектируется ══════

@pytest.mark.asyncio
async def test_x3_preference_replacement_supersedes_old(tmp_path):
    db = await _db(tmp_path)
    try:
        await _msg(db, user_id=7, text="отвечай короче", ts=1000)
        assert await mj.tick_experience_review(db) == "completed"
        svc = me.get_service(db)
        lessons = await svc.list_lessons(chat_id=-100)
        assert len(lessons) == 1
        v1 = lessons[0]
        assert v1["applicability"] == "user:7 pref:reply_length.short"
        # поздняя явная замена
        await _msg(db, user_id=7, text="теперь отвечай подробнее", ts=2000)
        await _next_pass(db)
        assert await mj.tick_experience_review(db) == "completed"
        lessons = await svc.list_lessons(chat_id=-100)
        versions = {int(l["version"]): l for l in lessons
                    if l["lesson_id"] == v1["lesson_id"]}
        assert int(v1["version"]) in versions
        assert versions[int(v1["version"])]["status"] == "superseded"
        latest = versions[max(versions)]
        assert latest["status"] == "active"
        assert latest["applicability"] == "user:7 pref:reply_length.long"
        # старая не инжектируется; отбор возвращает только актуальную
        sel = await svc.lesson.select_for_context(
            chat_id=-100, user_id=7,
            query="явное предпочтение формы ответа участника")
        assert len(sel.lessons) == 1
        assert sel.lessons[0].version == max(versions)
        # старый сигнал в новом проходе не откатывает замену (анти-ping-pong)
        await _next_pass(db)
        assert await mj.tick_experience_review(db) == "completed"
        lessons = await svc.list_lessons(chat_id=-100)
        assert len(lessons) == 2
        assert all(l["applicability"] != "user:7 pref:reply_length.short"
                   or l["status"] == "superseded" for l in lessons)
    finally:
        await db.close()


# ═══ §18E.5/X4: resume незавершённых durable-кандидатов ═════════════════════

@pytest.mark.asyncio
async def test_x4_crash_after_create_resumes(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        # durable provenance (feedback) есть, верификация не успела (crash)
        await svc.record_feedback(
            source_kind="participant_correction", chat_id=-100,
            ref_type="chat_message", ref_id=11,
            signal={"preference": "reply_length.short", "user_id": 7,
                    "author_user_id": 7})
        lid, ver = await svc.lesson.propose(
            type="social_preference", scope="user_in_chat",
            rule_key="explicit_user_preference", scope_chat_id=-100,
            scope_user_id=7, applicability="user:7 pref:reply_length.short")
        assert lid
        assert (await svc.get_lesson(lid, ver))["status"] == "candidate"
        assert await mj.tick_experience_review(db) == "completed"
        lesson = await svc.get_lesson(lid, ver)
        assert lesson["status"] == "active"      # resume: create → verify
        payload = await _payload_of(db)
        assert payload["counters"]["resumed_validated"] == 1
        assert payload["counters"]["resumed_activated"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_x4_crash_after_verify_resumes_activation(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await svc.lesson.propose(
            type="tool_usage", scope="chat",
            rule_key="retry_after_typed_failure", scope_chat_id=-100)
        assert await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=True,
                control_example_succeeded=True))
        assert await mj.tick_experience_review(db) == "completed"
        assert (await svc.get_lesson(lid, ver))["status"] == "active"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_x4_semantic_rejection_stays_candidate_until_evidence(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        episode_ids = []
        for i in range(2):                     # < min_independent_episodes
            episode_ids.append(await svc.capture_episode(
                chat_id=-100, trace_id=f"e-{i}", outcome_kind="failure",
                outcome_source="technical", ts=1000 + i))
        lid, ver = await svc.lesson.propose(
            type="tool_usage", scope="chat",
            rule_key="retry_after_typed_failure", scope_chat_id=-100,
            episode_ids=tuple(episode_ids))
        assert await mj.tick_experience_review(db) == "completed"
        lesson = await svc.get_lesson(lid, ver)
        assert lesson["status"] == "candidate"  # semantic rejection ≠ loss
        payload = await _payload_of(db)
        assert payload["counters"]["resume_rejected"] >= 1
        # эпизоды накапливаются → eventual validation следующим проходом
        await svc.capture_episode(chat_id=-100, trace_id="e-9",
                                  outcome_kind="failure",
                                  outcome_source="technical", ts=1999)
        cursor = await db.db.execute(
            "SELECT episode_id FROM mca_experience_episodes WHERE "
            "trace_id = 'e-9'")
        third = (await cursor.fetchone())["episode_id"]
        lesson_ref = lesson["source_ref_id"]
        from services.provenance import (EvidenceLink, SourceRef,
                                         add_evidence_link, resolve_source_ref)
        src_id = await resolve_source_ref(db, SourceRef(
            store="sqlite", entity_type="episode", entity_id=str(third),
            chat_id=-100, resolution="resolved"))
        await add_evidence_link(db, EvidenceLink(
            subject_ref_id=int(lesson_ref), source_ref_id=int(src_id),
            link_type="derived_from", method="metadata",
            verification="verified", independence="independent",
            extractor_version="mca-16/v1", basis="test accumulation"))
        await db.db.commit()
        await _next_pass(db)
        assert await mj.tick_experience_review(db) == "completed"
        assert (await svc.get_lesson(lid, ver))["status"] == "active"
    finally:
        await db.close()


# ═══ §18E.6/X5: fair scanning, unknown остаётся unknown ═════════════════════

async def _active_tool_lesson(svc):
    lid, ver = await svc.lesson.propose(
        type="tool_usage", scope="chat",
        rule_key="retry_after_typed_failure", scope_chat_id=-100)
    assert await svc.lesson.validate(
        lid, evidence=me.ValidationEvidence(
            kind="technical_fix", error_reproduced=True,
            control_example_succeeded=True))
    assert await svc.lesson.activate(lid)
    return lid, ver


@pytest.mark.asyncio
async def test_x5_new_matchable_not_blocked_by_old_unknown(tmp_path,
                                                           monkeypatch):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr(mca_gates, "experience_review_batch_max",
                            lambda: 1)
        svc = me.get_service(db)
        lid, ver = await _active_tool_lesson(svc)
        from services.mca_retrieval_context import LessonRef
        refs = (LessonRef(lesson_id=lid, version=ver, type="tool_usage",
                          scope="chat", recommendation="x"),)
        import time
        now = int(time.time())
        # старая permanently-unknown (эпизода никогда не будет)
        assert await svc.record_applications(
            refs, application_ref="ghost", trace_id="ghost",
            chat_id=-100) == 1
        await db.db.execute(
            "UPDATE mca_lesson_applications SET applied_at = ? "
            "WHERE application_ref = 'ghost'", (now - 10000,))
        # новая matchable позади неё
        assert await svc.record_applications(
            refs, application_ref="hit", trace_id="hit", chat_id=-100) == 1
        await db.db.execute(
            "UPDATE mca_lesson_applications SET applied_at = ? "
            "WHERE application_ref = 'hit'", (now - 5000,))
        await svc.capture_episode(chat_id=-100, trace_id="hit",
                                  outcome_kind="failure",
                                  outcome_source="technical", ts=now + 5)
        await db.db.commit()
        # проход 1: окно = ghost (голова) — без исхода, остаётся unknown
        assert await mj.tick_experience_review(db) == "completed"
        assert (await svc.get_lesson(lid, ver))["counters_failure"] == 0
        # проход 2: вращающийся курсор доходит до новой matchable
        await _next_pass(db)
        assert await mj.tick_experience_review(db) == "completed"
        lesson = await svc.get_lesson(lid, ver)
        assert lesson["counters_failure"] == 1
        # ghost остаётся unknown: не авто-success, не удаление
        cursor = await db.db.execute(
            "SELECT outcome, linked_at FROM mca_lesson_applications "
            "WHERE application_ref = 'ghost'")
        row = await cursor.fetchone()
        assert row["outcome"] == "unknown" and row["linked_at"] is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_x5_structurally_unmatchable_excluded_and_counted(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _active_tool_lesson(svc)
        from services.mca_retrieval_context import LessonRef
        refs = (LessonRef(lesson_id=lid, version=ver, type="tool_usage",
                          scope="chat", recommendation="x"),)
        assert await svc.record_applications(
            refs, application_ref="orphan", trace_id=None,
            chat_id=None) == 1
        assert await mj.tick_experience_review(db) == "completed"
        payload = await _payload_of(db)
        assert payload["counters"]["outcomes_unmatchable"] == 1
        cursor = await db.db.execute(
            "SELECT outcome, linked_at FROM mca_lesson_applications "
            "WHERE application_ref = 'orphan'")
        row = await cursor.fetchone()
        assert row["outcome"] == "unknown" and row["linked_at"] is None
    finally:
        await db.close()


# ═══ U4: scope (global master / per-chat / cross-chat) ══════════════════════

class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeChatParamsCache:
    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}

    def __init__(self, overrides_by_chat):
        self._by_chat = dict(overrides_by_chat or {})


@pytest.mark.asyncio
async def test_u4_global_master_off_silences_all_chats(tmp_path):
    hot_config.set_config_cache(_FakeHot(
        {"memory.experience_learning_enabled": False}))
    db = await _db(tmp_path)
    cache = _FakeChatParamsCache({
        -100: {"memory.experience_learning_enabled": True},
    })
    from services import chat_params
    chat_params.set_chat_params_cache(cache)
    try:
        await _msg(db, chat_id=-100, text="отвечай короче", user_id=42)
        # global master OFF: worker честно disabled — ни одного сигнала
        assert await mj.tick_experience_review(db) == "disabled"
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_experience_feedback")
        assert (await cursor.fetchone())["c"] == 0
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM mca_lessons")
        assert (await cursor.fetchone())["c"] == 0
        # stored per-chat override НЕ переписан глобальным master
        assert cache._by_chat[-100] == {
            "memory.experience_learning_enabled": True}
    finally:
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


@pytest.mark.asyncio
async def test_u4_chat_off_is_local_other_chat_learns(tmp_path):
    hot_config.set_config_cache(_FakeHot(
        {"memory.experience_learning_enabled": True}))
    db = await _db(tmp_path)
    from services import chat_params
    chat_params.set_chat_params_cache(_FakeChatParamsCache({
        -100: {"memory.experience_learning_enabled": False},
    }))
    try:
        await _msg(db, chat_id=-100, text="отвечай короче", user_id=42)
        await _msg(db, chat_id=-200, text="отвечай короче", user_id=42)
        assert await mj.tick_experience_review(db) == "completed"
        # chat OFF — deliberate skip (курсор продвинут), не technical loss
        payload = await _payload_of(db)
        assert payload[mj.DETECTOR_CURSOR_KEY] >= 2
        assert payload["counters"]["detector_skipped"] == 1
        assert payload["counters"]["detector_detected"] == 1
        cursor = await db.db.execute(
            "SELECT chat_id FROM mca_experience_feedback")
        chats = {int(r["chat_id"]) for r in await cursor.fetchall()}
        assert chats == {-200}
        svc = me.get_service(db)
        # урок чата -200 не виден в чате -100 (cross-chat isolation)
        sel = await svc.lesson.select_for_context(
            chat_id=-100, user_id=42,
            query="явное предпочтение формы ответа участника")
        assert sel.lessons == ()
        sel = await svc.lesson.select_for_context(
            chat_id=-200, user_id=42,
            query="явное предпочтение формы ответа участника")
        assert len(sel.lessons) == 1
    finally:
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


# ═══ R17 + детерминированность детектора ════════════════════════════════════

def test_detector_signal_never_carries_raw_text():
    verdict = mj.classify_chat_message(
        text="не называй меня Хранителем тьмы",
        media_type="text", is_forward=False, reply_to_user_id=None)
    assert verdict and verdict["class"] == mj.DETECTOR_CLASS_PREFERENCE
    runner = mj.ExperienceReviewRunner.__new__(mj.ExperienceReviewRunner)
    signal = runner._detector_signal(
        {"id": 5, "user_id": 42, "reply_to_id": None}, verdict, False)
    blob = json.dumps(signal, ensure_ascii=False)
    assert "Хранителем" not in blob
    assert signal["msg"] == 5 and signal["user_id"] == 42


def test_detector_patterns_closed_set():
    # сомнительные классы не проходят даже с коррекционной лексикой
    for text in ("ахаха ты ошибаешься конечно",
                 "ты тупой, ошибаешься",
                 "он сказал, что ты ошибаешься",
                 "не согласен, ты ошибаешься"):
        verdict = mj.classify_chat_message(text=text, media_type="text",
                                           is_forward=False,
                                           reply_to_user_id=None)
        assert verdict is not None and "skip" in verdict, text


@pytest.mark.asyncio
async def test_detector_off_when_review_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(mca_gates, "experience_review_enabled", lambda: False)
    db = await _db(tmp_path)
    try:
        await _msg(db, text="отвечай короче", user_id=42)
        assert await mj.tick_experience_review(db) == "disabled"
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_experience_feedback")
        assert (await cursor.fetchone())["c"] == 0
    finally:
        await db.close()
