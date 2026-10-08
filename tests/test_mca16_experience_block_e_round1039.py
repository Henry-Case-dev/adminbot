"""MCA-16 `mca-16-experience-lessons` — focused-тесты блока E (T-5005…T-5009).

Покрытие:
  * настройки: `memory.experience_learning_enabled` / `..._review_cadence` в
    существующем каталоге (группа memory_experience, вкладка memory_rag,
    select hourly/daily/weekly, default daily, enabled=true); применение
    через hot (без рестарта); выполняющиеся решения — со своей config_version;
  * «Статус»: лента «Опыт» — реальные записи, честный disabled/not_run,
    unknown-исход → без выдуманного улучшения (A57), изоляция чужого чата;
  * «Память»: таблица/карточка уроков + права (suspend/activate/correct),
    основания/версии/применения/исходы, trace только разрешённого чата;
  * наблюдаемость: процесс `self_learning.run` v1 (стадии/события/widget-ID/
    recovery/gate), OFF → disabled/not_run; `utility_updated` агрегирован;
    сквозной trace A49 (эпизод↔trace↔урок↔применение) не рвётся;
  * R17: в витринах/API — только канонические формулировки/ID/коды/числа.
"""
import dataclasses
import json

import pytest

from services import mca_events, mca_gates
from services import mca_experience as me
from services import mca_experience_jobs as mj
from services import mca_process_registry as reg
from services.database import DatabaseService
from services.mca_retrieval_context import LessonRef
from services.status_service import StatusService
from web.api import memory_agi as ma


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


async def _db(tmp_path, name="mca16_e.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _active(svc, *, chat_id=-100, type="tool_usage",
                  rule_key="retry_after_typed_failure", user_id=None):
    scope = "user_in_chat" if type == "social_preference" else "chat"
    lid, ver = await svc.lesson.propose(
        type=type, scope=scope, rule_key=rule_key, scope_chat_id=chat_id,
        scope_user_id=user_id)
    assert lid
    if type == "social_preference":
        evidence = me.ValidationEvidence(
            kind="explicit_preference", permission_granted=True,
            conflict_free=True)
    else:
        evidence = me.ValidationEvidence(
            kind="technical_fix", error_reproduced=True,
            control_example_succeeded=True)
    assert await svc.lesson.validate(lid, evidence=evidence)
    assert await svc.lesson.activate(lid)
    return lid, ver


# ═══ T-5005: настройки в существующем каталоге ══════════════════════════════

def test_settings_catalog_group_and_defaults():
    from services import param_catalog as pc
    from config.settings import Settings, settings
    learning = pc.REGISTRY["EXPERIENCE_LEARNING_ENABLED"]
    cadence = pc.REGISTRY["EXPERIENCE_REVIEW_CADENCE"]
    assert learning.pg_key == "memory.experience_learning_enabled"
    assert learning.group == "memory_experience" and learning.type == "bool"
    assert learning.secret is False and learning.per_chat is True
    assert pc.group_tab("memory_experience") == pc.TAB_MEMORY_RAG
    assert cadence.pg_key == "memory.experience_review_cadence"
    assert cadence.widget == "select"
    assert cadence.select_options == ("hourly", "daily", "weekly")
    assert len(cadence.select_options) == len(cadence.select_labels)
    # enabled=true при релизе; каденция daily (стартовые значения)
    assert Settings().EXPERIENCE_LEARNING_ENABLED is True
    assert Settings().EXPERIENCE_REVIEW_CADENCE == "daily"
    assert getattr(settings, "EXPERIENCE_LEARNING_ENABLED") is True
    # зеркало TABS (web/app.js) — без новых вкладок
    import pathlib
    app_js = pathlib.Path("web/app.js").read_text(encoding="utf-8")
    assert "groups: ['memory_experience']" in app_js
    assert "len(pc.TAB_RULES) == 23" not in app_js  # sanity: JS не пинит каталог


def test_settings_apply_without_restart(monkeypatch):
    from services import hot_config as hot
    monkeypatch.setattr(hot, "get", lambda key, default=None: (
        {"memory.experience_review_cadence": "weekly",
         "memory.experience_learning_enabled": False}.get(key, default)))
    assert mj.review_cadence() == "weekly"       # hot, без рестарта
    assert mj.review_enabled() is False          # UI-гейт нового обучения
    monkeypatch.setattr(hot, "get", lambda key, default=None: (
        {"memory.experience_review_cadence": "bogus",
         "memory.experience_learning_enabled": True}.get(key, default)))
    assert mj.review_cadence() == "daily"        # невалидное → default
    assert mj.review_enabled() is True


@pytest.mark.asyncio
async def test_running_decisions_keep_their_config_version(tmp_path):
    from config.settings import APP_VERSION
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        eid = await svc.capture_episode(chat_id=-100, trace_id="ver-1",
                                        outcome_kind="unknown",
                                        outcome_source="technical")
        row = await svc.store.get_episode(eid)
        assert row["config_version"] == APP_VERSION
        assert row["tool_schema_hash"] == me.current_tool_schema_hash()
        lid, ver = await _active(svc)
        lesson = await svc.get_lesson(lid, ver)
        assert lesson["policy_version"] == me.EXPERIENCE_POLICY_VERSION
        assert lesson["proposal_version"] == me.PROPOSAL_VERSION
        assert lesson["validator_version"] == me.VALIDATOR_VERSION
        assert lesson["compat_config_version"] == APP_VERSION
    finally:
        await db.close()


# ═══ T-5006: «Статус» — лента «Опыт» ════════════════════════════════════════

@pytest.mark.asyncio
async def test_status_feed_real_records_and_honest_unknown(
        tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr("services.lore_runtime.get_lore_db", lambda: db)
        status = StatusService()
        # пусто → not_run (без выдуманных записей)
        empty = await status.experience_snapshot()
        assert empty["state"] == "not_run" and empty["items"] == []
        assert empty["improvement"]["measured"] is False
        svc = me.get_service(db)
        lid, ver = await _active(svc)
        refs = (LessonRef(lesson_id=lid, version=ver, type="tool_usage",
                          scope="chat", recommendation="x"),)
        assert await svc.record_applications(
            refs, application_ref="feed-1", trace_id="feed-1",
            chat_id=-100) == 1
        snap = await status.experience_snapshot(chat_id=-100,
                                                chat_scope_allowed=True)
        assert snap["enabled"] is True and snap["state"] == "implemented"
        labels = {item["label"] for item in snap["items"]}
        assert "исправлен способ действия" in labels
        assert "урок применён" in labels
        applied = [i for i in snap["items"] if i["kind"] == "applied"][0]
        assert applied["outcome"] == "unknown"    # молчание ≠ успех
        assert snap["counters"]["applications"] == 1
        assert snap["improvement"]["measured"] is False
        # приостановленный урок виден и не применяется
        assert await svc.lesson.suspend(lid, reason_code="owner_disabled")
        snap2 = await status.experience_snapshot(chat_id=-100,
                                                 chat_scope_allowed=True)
        assert "урок приостановлен" in {i["label"] for i in snap2["items"]}
        assert snap2["counters"]["suspended"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_status_feed_off_and_foreign_chat_isolation(tmp_path,
                                                         monkeypatch):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr("services.lore_runtime.get_lore_db", lambda: db)
        status = StatusService()
        monkeypatch.setattr(mca_gates, "experience_lessons_enabled",
                            lambda: False)
        off = await status.experience_snapshot()
        assert off["enabled"] is False and off["state"] == "disabled"
        assert off["items"] == []
        monkeypatch.setattr(mca_gates, "experience_lessons_enabled",
                            lambda: True)
        svc = me.get_service(db)
        await _active(svc, chat_id=-100)
        # без разрешённого чата чужой урок не раскрывается
        foreign = await status.experience_snapshot()
        assert foreign["items"] == []
        own = await status.experience_snapshot(chat_id=-100,
                                               chat_scope_allowed=True)
        assert len(own["items"]) == 1
        # chat_scope_allowed=False (RBAC не пропустил) → тоже пусто
        denied = await status.experience_snapshot(chat_id=-100,
                                                  chat_scope_allowed=False)
        assert denied["items"] == []
    finally:
        await db.close()


# ═══ T-5007: «Память» — таблица/карточка/права ══════════════════════════════

@pytest.fixture
def _api_db(monkeypatch, tmp_path):
    async def _run(db):
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        return db
    return _run


@pytest.mark.asyncio
async def test_memory_lessons_table_card_and_trace_scope(tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        svc = me.get_service(db)
        eid = await svc.capture_episode(chat_id=-100, trace_id="tr-scope",
                                        outcome_kind="failure",
                                        outcome_source="technical")
        lid, ver = await svc.lesson.propose(
            type="tool_usage", scope="chat", rule_key="retry_after_typed_failure",
            scope_chat_id=-100, episode_ids=(eid,))
        assert await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="technical_fix", error_reproduced=True,
                control_example_succeeded=True))
        assert await svc.lesson.activate(lid)
        out = await ma.memory_lessons(None, None, chat_id=-100, status=None,
                                      limit=100)
        assert out["enabled"] is True and out["count"] == 1
        lesson = out["lessons"][0]
        assert lesson["status"] == "active" and lesson["applied"] is True
        assert lesson["grounds_count"] >= 1
        assert lesson["versions"]["policy"] == me.EXPERIENCE_POLICY_VERSION
        assert lesson["trace_available"] is True
        assert lesson["trace_ids"] == ["tr-scope"]   # свой чат — след открыт
        # чужой чат: trace НЕ отдаётся (чужой trace не раскрывается)
        foreign = await ma.memory_lessons(None, None, chat_id=-200,
                                          status=None, limit=100)
        assert foreign["lessons"] == []              # фильтр по scope чата
        # без chat_id — только global (урок чата не раскрывается)
        no_chat = await ma.memory_lessons(None, None, chat_id=None,
                                          status=None, limit=100)
        assert no_chat["lessons"] == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_memory_lesson_actions_idempotent_and_correct(tmp_path,
                                                            monkeypatch):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        svc = me.get_service(db)
        lid, ver = await _active(svc, chat_id=-100)
        # suspend (owner_disabled) — идемпотентно
        res = await ma.memory_lesson_action(None, None, ma.LessonActionRequest(
            lesson_id=lid, version=ver, action="suspend"))
        assert res["ok"] is True and res["status"] == "suspended"
        again = await ma.memory_lesson_action(None, None,
                                              ma.LessonActionRequest(
                                                  lesson_id=lid, version=ver,
                                                  action="suspend"))
        assert again["ok"] is False
        assert again["reason"] == "not_active_or_validated"
        assert await svc.store.count("mca_lessons") == 1   # без дублей
        # activate только для validated — suspended отклонён
        act = await ma.memory_lesson_action(None, None, ma.LessonActionRequest(
            lesson_id=lid, version=ver, action="activate"))
        assert act["ok"] is False and act["status"] == "suspended"
        # correct = НОВАЯ версия (candidate); пустая правка → no-op
        noop = await ma.memory_lesson_action(None, None, ma.LessonActionRequest(
            lesson_id=lid, version=ver, action="correct"))
        assert noop["ok"] is False and noop["reason"] == "no_changes"
        fixed = await ma.memory_lesson_action(None, None,
                                              ma.LessonActionRequest(
                                                  lesson_id=lid, version=ver,
                                                  action="correct",
                                                  applicability="tool:web"))
        assert fixed["ok"] is True and fixed["status"] == "candidate"
        assert fixed["lesson_id"] == lid and fixed["version"] == ver + 1
        assert await svc.store.count("mca_lessons") == 2   # delta, не перезапись
        # unknown action / missing lesson
        with pytest.raises(Exception):
            await ma.memory_lesson_action(None, None,
                                          ma.LessonActionRequest(
                                              lesson_id=lid, action="explode"))
        with pytest.raises(Exception):
            await ma.memory_lesson_action(None, None,
                                          ma.LessonActionRequest(
                                              lesson_id="nope",
                                              action="suspend"))
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_memory_lessons_disabled_off(tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        monkeypatch.setattr(mca_gates, "experience_lessons_enabled",
                            lambda: False)
        out = await ma.memory_lessons(None, None, chat_id=None, status=None,
                                      limit=100)
        assert out == {"enabled": False, "state": "disabled", "count": 0,
                       "lessons": []}
        res = await ma.memory_lesson_action(None, None,
                                            ma.LessonActionRequest(
                                                lesson_id="x", action="suspend"))
        assert res == {"ok": False, "reason": "disabled"}
    finally:
        await db.close()


# ═══ T-5008: наблюдаемость — процесс v1, события, A49 ═══════════════════════

def test_process_self_learning_v1_registry():
    p = reg.get_process("self_learning.run")
    assert p is not None and p.version == "1"
    assert p.owner_feature == "mca-16"
    assert p.widget_id == "Опыт и уроки"          # контракт mca-17c
    assert p.enabled_gate == "MCA_EXPERIENCE_LESSONS_ENABLED"
    assert p.stages == ("capture", "review", "propose", "validate",
                        "activate", "select", "apply", "outcome", "utility",
                        "suspend")
    assert set(p.instrumentation) <= set(p.stages)
    assert p.recovery_ops == ("review_resume", "outcome_reconcile")
    assert "mca_experience_episodes" in p.state_source
    assert "task_jobs" in p.state_source
    assert p.declared_instrumented
    # каждый объявленный код события — из санкционного словаря
    for name in p.event_names:
        assert name in mca_events.REASON_CODES, name
    # OFF → честный disabled; без событий → not_run (не implemented)
    assert reg.runtime_status(
        p, event_names_present=frozenset({"unrelated"})) == reg.STATUS_NOT_RUN
    assert reg.runtime_status(
        p, event_names_present=frozenset({"utility_updated"})) \
        == reg.STATUS_IMPLEMENTED


def test_process_self_learning_disabled_by_gate(monkeypatch):
    p = reg.get_process("self_learning.run")
    monkeypatch.setattr(mca_gates, "experience_lessons_enabled",
                        lambda: False)
    assert reg.runtime_status(p) == reg.STATUS_DISABLED


@pytest.mark.asyncio
async def test_utility_updated_aggregated_with_versions(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(mca_events, "emit_mca_event",
                        lambda name, *, outcome, **fields: captured.append(
                            {"event_name": name, "outcome": outcome,
                             **fields}) or {})
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _active(svc)
        refs = (LessonRef(lesson_id=lid, version=ver, type="tool_usage",
                          scope="chat", recommendation="x"),)
        for i in range(2):
            ref = f"agg-{i}"
            await svc.record_applications(refs, application_ref=ref,
                                          trace_id=ref, chat_id=-100)
            await svc.capture_episode(chat_id=-100, trace_id=ref,
                                      outcome_kind="failure",
                                      outcome_source="technical")
        assert await mj.tick_experience_review(db) == "completed"
        util = [c for c in captured if c["event_name"] == "utility_updated"]
        assert len(util) == 1                     # агрегировано на запуск
        assert util[0]["config_version"] == me.EXPERIENCE_POLICY_VERSION
        assert util[0]["component"] == "experience"
        assert util[0]["reason_code"] == "utility_updated"
        lesson = await svc.get_lesson(lid, ver)
        assert lesson["counters_failure"] == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_a49_trace_chain_not_broken(tmp_path):
    """Сквозной trace A49: эпизод↔trace, урок↔эпизод, применение↔trace,
    job↔causation — связи сохраняются на границе очереди."""
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _active(svc)
        eid = await svc.capture_episode(chat_id=-100, trace_id="a49-1",
                                        operation_id="op-a49",
                                        outcome_kind="failure",
                                        outcome_source="technical",
                                        ts=10_000)
        # урок ← эпизод (evidence link, mca-04a)
        new_lid, new_ver = await svc.lesson.propose(
            type="tool_usage", scope="chat",
            rule_key="retry_after_typed_failure", scope_chat_id=-100,
            episode_ids=(eid,))
        assert new_lid
        lesson = await svc.get_lesson(new_lid, new_ver)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_evidence_links WHERE "
            "subject_ref_id = ?", (lesson["source_ref_id"],))
        assert (await cursor.fetchone())["c"] == 1
        # применение ↔ trace
        refs = (LessonRef(lesson_id=lid, version=ver, type="tool_usage",
                          scope="chat", recommendation="x"),)
        await svc.record_applications(refs, application_ref="a49-1",
                                      trace_id="a49-1", chat_id=-100)
        cursor = await db.db.execute(
            "SELECT trace_id FROM mca_lesson_applications WHERE "
            "lesson_id = ?", (lid,))
        assert (await cursor.fetchone())["trace_id"] == "a49-1"
        # job ↔ causation/coalesce (граница очереди)
        job_id = await mj.enqueue_experience_review(db)
        row = await mj.TaskJobStore(db).get(job_id)
        assert row["coalesce_key"] == "experience.review:global"
        assert row["kind"] == "experience.review"
        # R17: сырые тексты/секреты не появились ни в одной v28-таблице
        blob = json.dumps([lesson, await svc.store.get_episode(eid)],
                          ensure_ascii=False, default=str)
        assert "password" not in blob and "token=" not in blob
    finally:
        await db.close()


# ═══ T-5009: R17-скан витрин блока E ════════════════════════════════════════

@pytest.mark.asyncio
async def test_r17_windows_are_canonical_only(tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr("services.lore_runtime.get_lore_db", lambda: db)
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        svc = me.get_service(db)
        lid, ver = await _active(svc)
        status = await StatusService().experience_snapshot(
            chat_id=-100, chat_scope_allowed=True)
        lessons = await ma.memory_lessons(None, None, chat_id=-100,
                                          status=None, limit=100)
        blob = json.dumps([status, lessons], ensure_ascii=False, default=str)
        # только канонические формулировки сервера (не копии реплик)
        assert me.CANONICAL_RECOMMENDATIONS[
            ("tool_usage", "retry_after_typed_failure")] in blob
        for marker in ("password", "api_key", "secret", "token=",
                       "chain-of-thought"):
            assert marker not in blob.lower(), marker
        assert lid in blob and str(ver) in blob
    finally:
        await db.close()
