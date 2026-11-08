"""STALE-DEADLOCK (прод 2.58.170): `recheck_required` у активного урока.

Дефект: три активных урока имели compat-маркеры старых версий
(2.58.79 / 2.58.161 против 2.58.170) → `recheck_required=1` →
`list_scope_candidates` их исключал (`retrieval_empty`, considered=0, ноль
применений), а `_lesson_exists` блокировал новое предложение по тому же
правилу. Флаг снимался только в `activate()` (только для `validated`), то
есть никогда — вечный дедлок.

Контракт фикса:
  (a) активный урок со «старыми» compat-маркерами перепроверяется по уже
      сохранённым свидетельствам (те же правила, что в `validate()`) и снова
      отбирается в контекст;
  (b) если сохранённые свидетельства проверку не проходят — урок уходит в
      `suspended` существующим переходом, и новое предложение по тому же
      правилу (та же identity) больше не блокируется;
  (c) действительно актуальный активный урок не трогается;
  (d) без свидетельств ничего не активируется, порог
      `MCA_LESSON_MIN_INDEPENDENT_EPISODES` не меняется, уроки не удаляются.
"""
import json

import pytest

from services import mca_events
from services import mca_experience as me
from services import mca_experience_jobs as mj
from services.database import DatabaseService

QUERY = "повторный вызов инструмента после ошибки"
CHAT = -100
RULE = ("tool_usage", "retry_after_typed_failure")


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


async def _db(tmp_path, name="mca16_stale.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _episodes(svc, count, *, tool="web_search", prefix="t") -> list[str]:
    ids = []
    for i in range(count):
        eid = await svc.capture_episode(
            chat_id=CHAT, trace_id=f"{prefix}-{tool}-{i}", outcome_kind="failure",
            outcome_source="technical", tool_ids=[tool])
        assert eid
        ids.append(eid)
    return ids


async def _active_lesson(svc, *, episodes=3, prefix="t"):
    """Активный generalization-урок с реальными независимыми эпизодами."""
    ids = await _episodes(svc, episodes, prefix=prefix)
    lid, ver = await svc.lesson.propose(
        type=RULE[0], scope="chat", rule_key=RULE[1], scope_chat_id=CHAT,
        applicability="tool:web_search", episode_ids=tuple(ids))
    assert lid
    assert await svc.lesson.validate(lid, evidence=me.ValidationEvidence(
        kind="generalization", independent_episode_ids=tuple(ids)))
    assert await svc.lesson.activate(lid)
    return lid, ver, ids


async def _seed_old_compat(db, lid, ver, *, config_version="2.58.79"):
    """Сид фикстуры: маркеры старой версии + флаг recheck (как на проде)."""
    await db.db.execute(
        "UPDATE mca_lessons SET recheck_required = 1, "
        "compat_tool_schema_hash = 'old-schema', "
        "compat_model_fingerprint = 'old-model', "
        "compat_config_version = ? WHERE lesson_id = ? AND version = ?",
        (config_version, lid, ver))
    await db.db.commit()


async def _downgrade_evidence(db, lesson):
    """Свидетельства перестали подтверждаться (не удаляем строки)."""
    await db.db.execute(
        "UPDATE mca_evidence_links SET verification = 'tentative' "
        "WHERE subject_ref_id = ?", (int(lesson["source_ref_id"]),))
    await db.db.commit()


# ═══ (a) stale compat → перепроверен → снова отбирается ═════════════════════

@pytest.mark.asyncio
async def test_stale_active_lesson_is_revalidated_and_selectable(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver, _ = await _active_lesson(svc)
        runner = mj.ExperienceReviewRunner(db)
        await _seed_old_compat(db, lid, ver)

        # До разрешения: не отбирается (дефект на проде).
        before = await svc.lesson.select_for_context(
            chat_id=CHAT, user_id=7, query=QUERY)
        assert before.lessons == ()
        assert before.reason_code == "retrieval_empty"

        result = await runner._resolve_recheck()
        assert result == {"resolved": 1, "suspended": 0}

        row = await svc.get_lesson(lid, ver)
        assert row["status"] == "active"          # активировано не «заново»
        assert row["recheck_required"] == 0
        assert row["compat_config_version"] == me.current_config_version()
        assert row["compat_tool_schema_hash"] == me.current_tool_schema_hash()
        assert row["last_validated_at"]

        # Повторный прогон идемпотентен: разрешать больше нечего.
        assert await runner._resolve_recheck() == {"resolved": 0,
                                                  "suspended": 0}

        after = await svc.lesson.select_for_context(
            chat_id=CHAT, user_id=7, query=QUERY)
        assert [r.lesson_id for r in after.lessons] == [lid]
        # Ноль применений больше не «вечный»: журнал пишется.
        assert await svc.record_applications(
            after.lessons, application_ref="trace-after-fix",
            trace_id="trace-after-fix", chat_id=CHAT) == 1
    finally:
        await db.close()


# ═══ (b) провал перепроверки → suspended + новое предложение разрешено ═════

@pytest.mark.asyncio
async def test_failed_revalidation_suspends_and_unblocks_new_proposal(
        tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver, _ = await _active_lesson(svc)
        lesson = await svc.get_lesson(lid, ver)
        await _downgrade_evidence(db, lesson)
        await _seed_old_compat(db, lid, ver)

        runner = mj.ExperienceReviewRunner(db)
        assert await runner._resolve_recheck() == {"resolved": 0,
                                                  "suspended": 1}
        row = await svc.get_lesson(lid, ver)
        assert row["status"] == "suspended"
        assert row["recheck_required"] == 1
        # История сохранена: строка и её версия на месте.
        assert row["version"] == ver

        # Identity больше не занята «мёртвым» уроком.
        assert not await runner._lesson_exists(
            type=RULE[0], scope="chat", scope_chat_id=CHAT,
            rule_key=RULE[1], applicability="tool:web_search")

        # Свежие независимые эпизоды → новое предложение проходит.
        await _episodes(svc, 3, tool="web_search", prefix="fresh")
        batch = await runner._propose_batch()
        assert batch["proposed"] == 1
        fresh = await svc.list_lessons(chat_id=CHAT, statuses=["candidate"])
        assert len(fresh) == 1 and fresh[0]["lesson_id"] != lid
        assert fresh[0]["status"] == "candidate"   # ничего не активировано
        # Старый урок по-прежнему в истории и не отбирается.
        assert (await svc.get_lesson(lid, ver))["status"] == "suspended"
        old_ids = [r.lesson_id for r in (await svc.lesson.select_for_context(
            chat_id=CHAT, user_id=7, query=QUERY)).lessons]
        assert lid not in old_ids
    finally:
        await db.close()


# ═══ (c) актуальный активный урок не трогается ═════════════════════════════

@pytest.mark.asyncio
async def test_current_active_lesson_is_untouched(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver, _ = await _active_lesson(svc)
        before = await svc.get_lesson(lid, ver)
        assert before["recheck_required"] == 0

        runner = mj.ExperienceReviewRunner(db)
        assert await runner._resolve_recheck() == {"resolved": 0,
                                                  "suspended": 0}
        after = await svc.get_lesson(lid, ver)
        assert after["status"] == "active"
        assert after["recheck_required"] == 0
        assert after["updated_at"] == before["updated_at"]
        assert after["compat_config_version"] == \
            before["compat_config_version"]
        assert [r.lesson_id for r in (await svc.lesson.select_for_context(
            chat_id=CHAT, user_id=7, query=QUERY)).lessons] == [lid]
    finally:
        await db.close()


# ═══ (d) без свидетельств не активируем; порог не меняем ═══════════════════

@pytest.mark.asyncio
async def test_no_activation_without_evidence_and_threshold_unchanged(
        tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        threshold = me.ExperiencePolicy.min_independent_episodes()
        assert threshold == 3            # MCA_LESSON_MIN_INDEPENDENT_EPISODES

        # validated-урок с провалившимися свидетельствами: не активируется.
        lid, ver, _ = await _active_lesson(svc)
        await db.db.execute(
            "UPDATE mca_lessons SET status = 'validated' "
            "WHERE lesson_id = ? AND version = ?", (lid, ver))
        await db.db.commit()
        lesson = await svc.get_lesson(lid, ver)
        await _downgrade_evidence(db, lesson)
        await _seed_old_compat(db, lid, ver, config_version="2.58.161")

        runner = mj.ExperienceReviewRunner(db)
        assert await runner._resolve_recheck() == {"resolved": 0,
                                                  "suspended": 1}
        assert (await svc.get_lesson(lid, ver))["status"] == "suspended"

        # validated-урок с проходящими свидетельствами: остаётся validated.
        lid2, ver2, _ = await _active_lesson(svc, prefix="v",
                                             episodes=threshold)
        await db.db.execute(
            "UPDATE mca_lessons SET status = 'validated' "
            "WHERE lesson_id = ? AND version = ?", (lid2, ver2))
        await db.db.commit()
        await _seed_old_compat(db, lid2, ver2, config_version="2.58.161")

        assert await runner._resolve_recheck() == {"resolved": 1,
                                                  "suspended": 0}
        row2 = await svc.get_lesson(lid2, ver2)
        assert row2["status"] == "validated"   # НЕ активирован автоматически
        assert row2["recheck_required"] == 0

        # Порог тот же; ни одна строка не удалена.
        assert me.ExperiencePolicy.min_independent_episodes() == threshold
        rows = await svc.list_lessons(chat_id=CHAT)
        assert {r["lesson_id"] for r in rows} == {lid, lid2}
    finally:
        await db.close()


# ═══ Preference-урок: перепроверка идёт по durable-сигналу ══════════════════

async def _pref_lesson(svc, *, user_id=7):
    await svc.record_feedback(
        source_kind="participant_correction", chat_id=CHAT,
        ref_type="chat_message", ref_id=11,
        signal={"preference": "reply_length.short", "user_id": user_id,
                "author_user_id": user_id})
    lid, ver = await svc.lesson.propose(
        type="social_preference", scope="user_in_chat",
        rule_key="explicit_user_preference", scope_chat_id=CHAT,
        scope_user_id=user_id,
        applicability=f"user:{user_id} pref:reply_length.short")
    assert lid
    assert await svc.lesson.validate(lid, evidence=me.ValidationEvidence(
        kind="explicit_preference", permission_granted=True,
        conflict_free=True))
    assert await svc.lesson.activate(lid)
    return lid, ver


@pytest.mark.asyncio
async def test_preference_recheck_uses_durable_signal(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _pref_lesson(svc)
        await _seed_old_compat(db, lid, ver, config_version="2.58.161")

        runner = mj.ExperienceReviewRunner(db)
        assert await runner._resolve_recheck() == {"resolved": 1,
                                                  "suspended": 0}
        row = await svc.get_lesson(lid, ver)
        assert row["status"] == "active" and row["recheck_required"] == 0

        # Отозванный сигнал (cancelled) — свидетельства нет → suspended.
        await _seed_old_compat(db, lid, ver, config_version="2.58.161")
        await db.db.execute(
            "UPDATE mca_experience_feedback SET status = 'cancelled'")
        await db.db.commit()
        assert await runner._resolve_recheck() == {"resolved": 0,
                                                  "suspended": 1}
        assert (await svc.get_lesson(lid, ver))["status"] == "suspended"
    finally:
        await db.close()


# ═══ Полный проход job: один проход разрывает дедлок ═══════════════════════

@pytest.mark.asyncio
async def test_review_pass_resolves_deadlock_end_to_end(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver, _ = await _active_lesson(svc)
        await _seed_old_compat(db, lid, ver)

        job_id = await mj.enqueue_experience_review(db)
        assert job_id
        status = await mj.ExperienceReviewRunner(db).run(job_id)
        assert status == "completed"

        row = await svc.get_lesson(lid, ver)
        assert row["status"] == "active" and row["recheck_required"] == 0
        selected = await svc.lesson.select_for_context(
            chat_id=CHAT, user_id=7, query=QUERY)
        assert [r.lesson_id for r in selected.lessons] == [lid]

        cursor = await db.db.execute(
            "SELECT payload FROM task_jobs WHERE job_id = ?", (job_id,))
        payload = json.loads((await cursor.fetchone())["payload"] or "{}")
        assert payload["counters"]["recheck_resolved"] >= 1
        assert payload["counters"]["recheck_suspended"] == 0
    finally:
        await db.close()
