"""MCA-16 `mca-16-experience-lessons` — focused-тесты блока C (T-4999…T-5002).

Покрытие:
  * состояния candidate/validated/active/suspended/superseded; candidate не
    применяется; включение сразу (валидация — обычная операция, не Human Gate);
  * явное предпочтение → user_in_chat после разрешения автора/адресата и
    проверки конфликтов; техфикс → воспроизведение + контрольный пример +
    инварианты; обобщение → ≥3 независимых эпизода + новые контексты;
    global — только обезличенный техурок;
  * delta/lineage/supersede (не переписывание книги); merge дублей;
    противоречие → suspend; compat-инвалидация → recheck → не применяется;
    изменение источника распространяет статус;
  * исторический bootstrap: только candidate historical/unverified; без
    массового backfill-успеха; OFF K3 — статусы заморожены.
"""
import pytest

from services import mca_events, mca_gates
from services import mca_experience as me
from services.database import DatabaseService
from services.mca_retrieval_context import LessonRef


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


async def _db(tmp_path, name="mca16_c.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _propose(svc, *, type="tool_usage",
                   rule_key="retry_after_typed_failure", scope="chat",
                   chat_id=-100, user_id=None, episode_ids=(),
                   historical=False):
    return await svc.lesson.propose(
        type=type, scope=scope, rule_key=rule_key, scope_chat_id=chat_id,
        scope_user_id=user_id, episode_ids=episode_ids, historical=historical)


async def _active(svc, **kw):
    lid, ver = await _propose(svc, **kw)
    assert lid
    assert await svc.lesson.validate(
        lid, evidence=me.ValidationEvidence(
            kind="technical_fix", error_reproduced=True,
            control_example_succeeded=True))
    assert await svc.lesson.activate(lid)
    return lid, ver


def _refs(lid, ver):
    return (LessonRef(lesson_id=lid, version=ver, type="tool_usage",
                      scope="chat", recommendation="x"),)


# ═══ T-4999: состояния и активация ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_candidate_not_used_and_not_prescribed(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _propose(svc)
        sel = await svc.lesson.select_for_context(
            chat_id=-100, user_id=7,
            query="повторный вызов инструмента после ошибки")
        assert sel.lessons == ()                       # candidate не в bundle
        assert not await svc.lesson.activate(lid)      # без validated — отказ
        assert (await svc.get_lesson(lid))["status"] == "candidate"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_activation_is_immediate_no_human_gate(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, _ = await _propose(svc)
        assert await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=True,
                control_example_succeeded=True))
        assert (await svc.get_lesson(lid))["status"] == "validated"
        assert await svc.lesson.activate(lid)          # сразу, без gate
        row = await svc.get_lesson(lid)
        assert row["status"] == "active"
        assert row["compat_tool_schema_hash"] == me.current_tool_schema_hash()
        assert row["last_validated_at"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_explicit_preference_scope_permission_conflict(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        # не user_in_chat → отказ
        lid_chat, _ = await _propose(
            svc, type="social_preference", scope="chat",
            rule_key="explicit_user_preference")
        assert not await svc.lesson.validate(
            lid_chat, evidence=me.ValidationEvidence(
                kind="explicit_preference", permission_granted=True,
                conflict_free=True))
        # user_in_chat без разрешения → отказ
        lid_np, _ = await _propose(
            svc, type="social_preference", scope="user_in_chat",
            rule_key="explicit_user_preference", user_id=7)
        assert not await svc.lesson.validate(
            lid_np, evidence=me.ValidationEvidence(
                kind="explicit_preference", permission_granted=False,
                conflict_free=True))
        # конфликт с обязательными правилами → отказ
        assert not await svc.lesson.validate(
            lid_np, evidence=me.ValidationEvidence(
                kind="explicit_preference", permission_granted=True,
                conflict_free=False))
        # полный набор оснований → validated → active → виден только субъекту
        assert await svc.lesson.validate(
            lid_np, evidence=me.ValidationEvidence(
                kind="explicit_preference", permission_granted=True,
                conflict_free=True))
        assert await svc.lesson.activate(lid_np)
        sel = await svc.lesson.select_for_context(
            chat_id=-100, user_id=7,
            query="предпочтение участника формы ответа")
        assert lid_np in {r.lesson_id for r in sel.lessons}
        sel_other = await svc.lesson.select_for_context(
            chat_id=-100, user_id=8,
            query="предпочтение участника формы ответа")
        assert lid_np not in {r.lesson_id for r in sel_other.lessons}
    finally:
        await db.close()


def test_authorize_preference_fail_closed():
    assert me.authorize_preference(subject_user_id=7, author_user_id=7)
    assert not me.authorize_preference(subject_user_id=7, author_user_id=8)
    assert me.authorize_preference(subject_user_id=7, author_user_id=8,
                                   actor_is_owner=True)
    assert not me.authorize_preference(subject_user_id=None,
                                       author_user_id=8)


@pytest.mark.asyncio
async def test_technical_fix_requires_reproduction_control_invariants(
        tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, _ = await _propose(svc)
        # нет воспроизведения ошибки
        assert not await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=False,
                control_example_succeeded=True))
        # нет успешного контрольного примера
        assert not await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=True,
                control_example_succeeded=False))
        # нарушение инвариантов
        assert not await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=True,
                control_example_succeeded=True, invariant_violations=1))
        assert (await svc.get_lesson(lid))["status"] == "candidate"
        assert await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=True,
                control_example_succeeded=True))
        assert (await svc.get_lesson(lid))["status"] == "validated"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_generalization_requires_three_independent_episodes(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, _ = await _propose(svc)
        two = await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="generalization",
                independent_episode_ids=("e1", "e2")))
        assert not two
        # дубликаты одного первичного события — один эпизод
        dup = await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="generalization",
                independent_episode_ids=("e1", "e1", "e1", "e2")))
        assert not dup
        assert await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="generalization",
                independent_episode_ids=("e1", "e2", "e3")))
        assert (await svc.get_lesson(lid))["status"] == "validated"
        assert mca_gates.lesson_min_independent_episodes() == 3
    finally:
        await db.close()


# ═══ T-5000: delta/lineage/supersede/совместимость ══════════════════════════

@pytest.mark.asyncio
async def test_revision_delta_and_supersede(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _active(svc)
        created = await svc.lesson.revise(
            lid, rule_key="check_tool_result_stage")
        assert created == (lid, 2)
        old = await svc.get_lesson(lid, 1)
        new = await svc.get_lesson(lid, 2)
        assert old["status"] == "superseded"
        assert new["status"] == "candidate"
        assert new["supersedes_lesson_id"] == lid
        assert new["supersedes_version"] == 1
        # старая версия не выбирается; новая — только после проверки
        sel = await svc.lesson.select_for_context(
            chat_id=-100, user_id=7,
            query="типизированный исход инструмента вызова")
        assert sel.lessons == ()
        # delta: книга не переписывалась — обе версии сохранены
        rows = await svc.list_lessons(chat_id=-100)
        assert len([r for r in rows if r["lesson_id"] == lid]) == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_merge_duplicates_with_lineage(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        a, a_v = await _active(svc)
        b, b_v = await _active(svc, rule_key="check_tool_result_stage")
        created = await svc.lesson.merge(
            primary_lesson_id=a, merged_lesson_ids=[b])
        assert created == (a, 2)
        merged = await svc.get_lesson(a, 2)
        assert f"{b}:{b_v}" in (merged["merged_from_json"] or "")
        assert (await svc.get_lesson(b))["status"] == "superseded"
        assert (await svc.get_lesson(a, 1))["status"] == "superseded"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_strong_contradiction_blocks_activation_and_suspends(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _propose(svc)
        row = await svc.get_lesson(lid)
        # подтверждённое противоречие → активация отклонена (не спор)
        await db.db.execute(
            "INSERT INTO mca_evidence_links (subject_ref_id, source_ref_id, "
            "link_type, method, verification, independence, established_at, "
            "created_at) VALUES (?, 1, 'contradicts', 'manual', 'verified', "
            "'independent', 1, 1)", (row["source_ref_id"],))
        await db.db.commit()
        assert await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=True,
                control_example_succeeded=True))
        assert not await svc.lesson.activate(lid)
        assert (await svc.get_lesson(lid))["status"] == "validated"
        # действие владельца → suspend, suspended не применяется
        assert await svc.lesson.suspend(lid,
                                        reason_code="owner_disabled")
        assert (await svc.get_lesson(lid))["status"] == "suspended"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_compat_invalidation_recheck_and_recovery(tmp_path,
                                                        monkeypatch):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _active(svc)
        query = "повторный вызов инструмента после ошибки"
        assert len((await svc.lesson.select_for_context(
            chat_id=-100, user_id=7, query=query)).lessons) == 1
        # смена tool schema → временная несовместимость → не применяется
        monkeypatch.setattr(me, "current_tool_schema_hash",
                            lambda: "changed-schema")
        sel = await svc.lesson.select_for_context(
            chat_id=-100, user_id=7, query=query)
        assert sel.lessons == ()
        assert any(e["reason_code"] == "stale_context"
                   for e in sel.excluded)
        assert await svc.lesson.recheck_stale() == 1
        assert (await svc.get_lesson(lid))["recheck_required"] == 1
        # успешная повторная проверка → снова active с новым compat
        assert await svc.lesson.recheck(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=True,
                control_example_succeeded=True))
        row = await svc.get_lesson(lid)
        assert row["recheck_required"] == 0 and row["status"] == "active"
        assert row["compat_tool_schema_hash"] == "changed-schema"
        assert len((await svc.lesson.select_for_context(
            chat_id=-100, user_id=7, query=query)).lessons) == 1
        # провал повторной проверки → suspended с причиной
        monkeypatch.setattr(me, "current_tool_schema_hash",
                            lambda: "changed-again")
        assert await svc.lesson.recheck_stale() == 1
        assert not await svc.lesson.recheck(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=True,
                control_example_succeeded=False))
        assert (await svc.get_lesson(lid))["status"] == "suspended"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_source_change_propagates_status(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        eid = await svc.capture_episode(chat_id=-100, trace_id="src-1",
                                        outcome_kind="failure",
                                        outcome_source="technical")
        lid, ver = await _propose(svc, episode_ids=[eid])
        assert await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=True,
                control_example_succeeded=True))
        assert await svc.lesson.activate(lid)
        cur = await db.db.execute(
            "SELECT source_ref_id FROM mca_source_refs WHERE entity_type = "
            "'episode' AND entity_id = ?", (eid,))
        src_id = (await cur.fetchone())["source_ref_id"]
        assert await svc.lesson.propagate_source_change(src_id) == 1
        row = await svc.get_lesson(lid)
        assert row["recheck_required"] == 1
        sel = await svc.lesson.select_for_context(
            chat_id=-100, user_id=7,
            query="повторный вызов инструмента после ошибки")
        assert sel.lessons == ()                  # не применяется до recheck
    finally:
        await db.close()


# ═══ T-5001: исторический bootstrap ═════════════════════════════════════════

@pytest.mark.asyncio
async def test_historical_bootstrap_candidates_only(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _propose(svc, historical=True)
        row = await svc.get_lesson(lid)
        assert row["status"] == "candidate"
        assert row["historical"] == 1 and row["unverified"] == 1
        # без свежей проверки на новых контекстах — не validated
        assert not await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="generalization",
                independent_episode_ids=("old-1", "old-2", "old-3")))
        assert not await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=True,
                control_example_succeeded=True))   # historical ≠ техфикс
        # свежая проверка на новых контекстах → validated (не active)
        assert await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="generalization",
                independent_episode_ids=("old-1", "old-2", "old-3"),
                fresh_context_verified=True))
        assert (await svc.get_lesson(lid))["status"] == "validated"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_legacy_replies_without_trace_no_success(tmp_path):
    """2 млн старых реплик без trace не восстанавливают успех/инструмент."""
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        assert await svc.capture_episode(
            chat_id=-100, outcome_kind="success",
            outcome_source="technical") is None
        assert await svc.capture_episode(
            chat_id=-100, operation_id=None, trace_id=None,
            feedback_id=None, outcome_kind="unknown",
            outcome_source="technical") is None
        assert await svc.store.count("mca_experience_episodes") == 0
        assert await svc.store.count("mca_lessons") == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_bootstrap_env_off_blocks_historical(tmp_path, monkeypatch):
    monkeypatch.setattr(mca_gates, "experience_bootstrap_enabled",
                        lambda: False)
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        assert await _propose(svc, historical=True) is None
    finally:
        await db.close()


# ═══ OFF K3: статусы заморожены ══════════════════════════════════════════════

@pytest.mark.asyncio
async def test_k3_off_statuses_frozen_selection_still_works(tmp_path,
                                                           monkeypatch):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _active(svc)
        monkeypatch.setattr(mca_gates, "experience_review_enabled",
                            lambda: False)
        assert await svc.lesson.propose(
            type="tool_usage", scope="chat",
            rule_key="retry_after_typed_failure",
            scope_chat_id=-100) is None
        assert not await svc.lesson.suspend(lid, reason_code="owner_disabled")
        assert (await svc.get_lesson(lid))["status"] == "active"
        # отбор уже active при K4 ON продолжает работать
        sel = await svc.lesson.select_for_context(
            chat_id=-100, user_id=7,
            query="повторный вызов инструмента после ошибки")
        assert lid in {r.lesson_id for r in sel.lessons}
    finally:
        await db.close()
