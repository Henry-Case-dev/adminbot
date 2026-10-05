"""MCA-18 `mca-18-self-model` — focused-тесты блоков C+D (T-5079…T-5083).

Покрытие (ADR-1028-18 D5/D6/D7; §28.4 `:1548–1562`; A60 `:941`, A61 `:942`):
  * lifecycle: observed→candidate→active/rejected/suspended/superseded;
    авто-валидация (субъект/источник/конфликт с ядром); 8 dimensions;
    новое имя → candidate с причиной; терминальное НЕ реактивируется;
  * quality_regression → НЕ правило (mca-16-наблюдение);
  * select_behavior → BehaviorFrame: детерминизм, precedence (разовая
    просьба не удаляет черту), rejected_rules с причинами, мнение ≠ факт,
    сырые тексты ≠ системные инструкции;
  * анти-самоусиление (A61): дедуп по исходным событиям; собственные ответы
    под чертой — не независимое подтверждение; гарды 0.1/0.2; ослабление
    допустимо; маркировка ledger (rule_tag);
  * границы: lesson ≠ trait ≠ paradigm ≠ style request; mca-22 — свои
    ответы не подтверждение.
"""
import dataclasses
import json

import pytest

from services import mca_events, mca_gates
from services import mca_self_model as sm
from services.database import DatabaseService

CHAT = -100500
AGENT = "agent-uuid-fixed"


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


@pytest.fixture
def events(monkeypatch):
    recorded: list = []

    def _fake(name, **kw):
        recorded.append((name, kw))
        return {"event_name": name}

    monkeypatch.setattr(mca_events, "emit_mca_event", _fake)
    return recorded


@pytest.fixture
def db(tmp_path, monkeypatch):
    """SQLite v31 + фиксированный agent_id + ядро владельца без конфликтов."""
    monkeypatch.setattr(sm, "_owner_core_conflict",
                        async_returns(None))
    d = DatabaseService(str(tmp_path / "mca18_cd.db"))
    d_sync_ready = None

    async def _make():
        await d.initialize()
        await d.rebind_self_identity(bot_user_id=4242, note="test")
        await d.db.execute("UPDATE mca_self_identity SET agent_id = ? "
                           "WHERE id = true", (AGENT,))
        await d.db.commit()
        return d

    import asyncio
    loop = asyncio.new_event_loop()
    try:
        d_sync_ready = loop.run_until_complete(_make())
    finally:
        loop.close()
    yield d_sync_ready
    import asyncio as _aio
    loop2 = _aio.new_event_loop()
    try:
        loop2.run_until_complete(d_sync_ready.close())
    finally:
        loop2.close()


def async_returns(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


async def _mk_self_obs(db, *, text="ты стал отвечать резче в спорах",
                       dimension="резкость", refs=("fact:101",),
                       chat=CHAT):
    oid = await sm.record_trait_observation(
        db, agent_id=AGENT, text=text, source_refs=refs,
        subject_status="self", chat_id=chat, dimension=dimension)
    return oid


# ═══ T-5079: lifecycle ══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_lifecycle_observation_to_active(db, events):
    oid = await _mk_self_obs(db)
    assert oid is not None
    rule_id, verdict = await sm.promote_observation(db, oid,
                                                    scope_chat_id=CHAT)
    assert rule_id is not None and verdict.allowed
    rules = await db.list_behavior_rules(AGENT, "active")
    assert len(rules) == 1
    assert rules[0]["dimension"] == "резкость"
    assert rules[0]["scope"] == "chat"          # chat-наблюдение → chat-scope
    assert json.loads(rules[0]["source_observation_ids"]) == [oid]
    # Стадия активации видима в событии.
    assert any(kw.get("stage") == "activation"
               for _, kw in events)


@pytest.mark.asyncio
async def test_lifecycle_repeat_observation_no_version_bump(db):
    """Повторное извлечение НЕ двигает версию/значение (≠ подкрепление)."""
    oid = await _mk_self_obs(db)
    rule_id, _ = await sm.promote_observation(db, oid, scope_chat_id=CHAT)
    rules = await db.list_behavior_rules(AGENT, "active")
    version_before = rules[0]["version"]
    oid2 = await _mk_self_obs(db, refs=("fact:102",))   # другой эпизод
    await sm.promote_observation(db, oid2, scope_chat_id=CHAT)
    rules = await db.list_behavior_rules(AGENT, "active")
    assert len(rules) == 1                       # тот же dimension → тот же rule
    assert rules[0]["version"] == version_before  # версия не растёт


@pytest.mark.asyncio
async def test_lifecycle_subject_not_self_rejected(db, events):
    oid = await sm.record_trait_observation(
        db, agent_id=AGENT, text="бот стал грубее",
        source_refs=("fact:9",), subject_status="ambiguous",
        chat_id=CHAT, dimension="резкость")
    rule_id, verdict = await sm.promote_observation(db, oid,
                                                    scope_chat_id=CHAT)
    assert verdict.allowed is False
    assert verdict.reason == "subject_not_self"
    assert await db.list_behavior_rules(AGENT, "active") == []
    assert any(kw.get("reason_code") == "trait_rule_rejected"
               for _, kw in events)


@pytest.mark.asyncio
async def test_lifecycle_unmapped_dimension_is_candidate(db, events):
    """Новое имя dimension от LLM → НЕприведённый кандидат с причиной;
    исполняемое правило НЕ создаётся (`:1554`; rules.dimension NOT NULL —
    санкция §8.1)."""
    oid = await sm.record_trait_observation(
        db, agent_id=AGENT, text="любит мемы про котов",
        source_refs=("fact:5",), subject_status="self", chat_id=CHAT,
        dimension="котолюбивость")            # неизвестное имя → NULL
    rule_id, verdict = await sm.promote_observation(db, oid,
                                                    scope_chat_id=CHAT)
    assert verdict.reason == "candidate_unmapped_dimension"
    assert rule_id is None
    assert await db.list_behavior_rules(AGENT, "active") == []
    assert await db.list_behavior_rules(AGENT, "candidate") == []
    # Наблюдение-кандидат осталось (история/основания целы).
    cur = await db.db.execute(
        "SELECT COUNT(*) AS c FROM mca_trait_observations WHERE id = ? "
        "AND dimension IS NULL", (oid,))
    assert (await cur.fetchone())["c"] == 1


@pytest.mark.asyncio
async def test_lifecycle_core_conflict_rejects(db, monkeypatch, events):
    async def _conflict(db_, scope, dim):
        return "owner_core:без резкости"
    monkeypatch.setattr(sm, "_owner_core_conflict", _conflict)
    oid = await _mk_self_obs(db)
    rule_id, verdict = await sm.promote_observation(db, oid,
                                                    scope_chat_id=CHAT)
    assert verdict.allowed is False
    assert verdict.reason.startswith("conflict_core")
    active = await db.list_behavior_rules(AGENT, "active")
    assert active == []
    rejected = await db.list_behavior_rules(AGENT, "rejected")
    assert len(rejected) == 1
    assert rejected[0]["status_reason"].startswith("rejected:")
    assert any(kw.get("reason_code") == "trait_conflict_core"
               for _, kw in events)


@pytest.mark.asyncio
async def test_lifecycle_terminal_not_reactivated(db, monkeypatch):
    monkeypatch.setattr(sm, "_owner_core_conflict", async_returns(None))
    oid = await _mk_self_obs(db)
    rule_id, _ = await sm.promote_observation(db, oid, scope_chat_id=CHAT)
    assert await sm.supersede_rule(db, rule_id, reason="противоположное "
                                                 "наблюдение",
                                   scope_chat_id=CHAT) is True
    # Терминальное (superseded) НЕ реактивируется.
    assert await sm.reactivate_rule(db, rule_id, reason="owner",
                                    scope_chat_id=CHAT) is False
    assert await db.list_behavior_rules(AGENT, "superseded")
    assert await db.list_behavior_rules(AGENT, "active") == []


@pytest.mark.asyncio
async def test_quality_regression_never_a_rule(db, events):
    """CA-18-2 (`:1558`): quality_regression → наблюдение в mca-16, НЕ
    анти-полезное правило."""
    oid = await sm.record_trait_observation(
        db, agent_id=AGENT, text="стал реже давать полезную выжимку",
        source_refs=("fact:77",), subject_status="self", chat_id=CHAT,
        dimension="quality_regression")
    rule_id, verdict = await sm.promote_observation(db, oid,
                                                    scope_chat_id=CHAT)
    assert verdict.allowed is False
    assert "experience" in verdict.reason
    assert await db.list_behavior_rules(AGENT, "active") == []
    assert await db.list_behavior_rules(AGENT, "candidate") == []
    assert any(kw.get("reason_code") == "trait_rule_rejected"
               for _, kw in events)


@pytest.mark.asyncio
async def test_k2_off_lifecycle_inert(db, monkeypatch):
    monkeypatch.setattr(mca_gates, "trait_rules_enabled", lambda: False)
    oid = await _mk_self_obs(db)
    assert oid is None                         # записи нет (v31 инертна)
    rule_id, verdict = await sm.promote_observation(db, 1)
    assert verdict.reason == "trait_rules_disabled"


@pytest.mark.asyncio
async def test_eight_initial_dimensions_complete():
    assert len(sm.INITIAL_DIMENSIONS) == 8
    for dim in ("прямота", "резкость", "сарказм", "краткость",
                "инициативность", "любопытство", "склонность спорить",
                "теплота"):
        assert dim in sm.DIMENSION_INSTRUCTIONS


# ═══ T-5080: select_behavior → BehaviorFrame ════════════════════════════════

def _snapshot_with(active_rules, *, rules_status="on", stale=False):
    from dataclasses import replace
    base = sm.TraitView(rule_id=1, dimension="резкость", target_value=0.7,
                        strength=0.5, scope="chat",
                        applicability=("dispute",), exclusions=(),
                        version=3)
    traits = tuple(replace(base, rule_id=i + 1, **kw)
                   for i, kw in enumerate(active_rules))
    return sm.SelfModelSnapshot(
        agent_id=AGENT, bot_user_id=4242, identity_binding="bound",
        persona_id=None, persona_version="p", scope_chat_id=CHAT,
        name="", aliases=(), biography="", style_version=None,
        traits=traits, interests=(), relations=(), state=None,
        positions=(),
        persona_enabled=sm.SettingState(key="flags.persona_enabled",
                                        value=True, source="default"),
        is_aware_ai=sm.SettingState(key="personas.is_aware_ai", value=True,
                                    source="default"),
        bot_self_awareness=sm.SettingState(
            key="flags.bot_self_awareness_enabled", value=True,
            source="default"),
        self_presentation_mode=sm.MODE_AWARE,
        capabilities=sm.build_capabilities(), rules_status=rules_status,
        version="snapv1", created_at=1_000, stale=stale)


def test_select_behavior_deterministic_and_second_person():
    snap = _snapshot_with([{"dimension": "резкость"}])
    f1 = sm.select_behavior(snap, addressee="Вася")
    f2 = sm.select_behavior(snap, addressee="Вася")
    assert f1 == f2                            # детерминизм (без LLM)
    assert len(f1.applied_rules) == 1
    rule = f1.applied_rules[0]
    assert rule.rule_id == 1 and rule.version == 3
    # 2-е лицо + отличие от цитат/справок.
    assert rule.instruction.startswith("Ты ")
    assert "Ты отвечаешь резче" in rule.instruction
    # Кадр — структурированные данные, не «бот»→«я» replace: сырых текстов
    # памяти в кадре нет (GEN-R18).
    assert all("стал" not in r.instruction for r in f1.applied_rules)


def test_select_behavior_scoped_request_shadows_not_deletes():
    """Одноразовая просьба «без резкости» действует на ответ, черта
    остаётся (`:1560`; mca-08 scoped_request precedence)."""
    snap = _snapshot_with([{"dimension": "резкость"}])
    frame = sm.select_behavior(
        snap, scoped_request=("без резкости объясни",))
    assert frame.applied_rules == ()           # на ЭТОТ ответ не применена
    assert frame.rejected_rules[0].reason == "shadowed_by_scoped_request"
    assert snap.traits                         # черта в snapshot цела
    # Другой ответ без просьбы — черта снова применима.
    frame2 = sm.select_behavior(snap)
    assert len(frame2.applied_rules) == 1


def test_select_behavior_rejected_with_reasons_and_opinion_boundary():
    snap = _snapshot_with([
        {"dimension": "резкость", "excluded_reason":
         "applicability_unbounded"},
        {"dimension": "котолюбивость"}])
    frame = sm.select_behavior(snap)
    reasons = {r.reason for r in frame.rejected_rules}
    assert "applicability_unbounded" in reasons
    assert "unmapped_dimension" in reasons
    # Мнение ≠ факт: позиции (opinion) НЕ попадают в factual_constraints —
    # это разные слоты кадра (запрет `:1540`); constraints — только
    # проверенный слой mca-07.
    position = sm.Position(opinion_ref="fact:9", text="коты лучше собак",
                           basis_refs=("src:1",), adopted_at=1)
    snap_pos = _snapshot_with([{"dimension": "резкость"}])
    snap_pos = dataclasses.replace(snap_pos, positions=(position,))
    f = sm.select_behavior(
        snap_pos, type("B", (), {"constraints": ("Вася из Питера",)})())
    assert f.factual_constraints == ("Вася из Питера",)
    assert f.positions == (position,)          # позиция живёт своим слотом


def test_render_frame_block_a58_and_false_replacement():
    snap = _snapshot_with([], stale=False)
    snap_empty = snap
    frame = sm.select_behavior(snap_empty)
    # A58: пустая персона → различимое поведение (не пустая строка).
    out_true = sm.render_frame_block(frame, name="", biography="",
                                     overrides="", is_aware_ai=True)
    assert out_true.startswith("<Persona>")
    assert "цифровой собеседник" in out_true
    out_false = sm.render_frame_block(frame, name="", biography="",
                                      overrides="", is_aware_ai=False)
    # Новая формулировка False ЗАМЕНЯЕТ абсолютный запрет (D3).
    assert sm.SELF_MODEL_FALSE_BLOCK in out_false
    assert "Ты НЕ раскрываешь" not in out_false


def test_render_frame_stale_honest():
    snap = _snapshot_with([{"dimension": "резкость"}], stale=True)
    frame = sm.select_behavior(snap)
    assert frame.applied_rules == ()           # stale данные не ведут
    assert frame.version.endswith(":stale")
    out = sm.render_frame_block(frame, name="Костик", biography="кот",
                                overrides="", is_aware_ai=True)
    assert "Правила характера" not in out       # fallback честен


def test_frame_version_stable_and_distinct():
    snap = _snapshot_with([{"dimension": "резкость"}])
    f1 = sm.select_behavior(snap)
    snap2 = _snapshot_with([{"dimension": "теплота"}])
    f2 = sm.select_behavior(snap2)
    assert f1.version == f2.version            # версия = snapshot_version
    assert sm.frame_signature(f1) != sm.frame_signature(f2)


# ═══ T-5082: анти-самоусиление (A61) ════════════════════════════════════════

@pytest.mark.asyncio
async def test_reinforcement_dedup_by_source_events(db, events):
    oid = await _mk_self_obs(db)
    rule_id, _ = await sm.promote_observation(db, oid, scope_chat_id=CHAT)
    v1 = sm.GuardVerdict(True, "ok")
    first = await sm.reinforce_rule(
        db, rule_id, delta=0.05, refs=("fact:201",), scope_chat_id=CHAT)
    assert first.allowed
    # ТОТ ЖЕ эпизод → no-op (дедуп по исходным событиям, не по summary).
    again = await sm.reinforce_rule(
        db, rule_id, delta=0.05, refs=("fact:201",), scope_chat_id=CHAT)
    assert again.allowed is False
    assert again.reason == "reinforcement_dedup"
    assert any(kw.get("reason_code") == "trait_reinforcement_dedup"
               for _, kw in events)


@pytest.mark.asyncio
async def test_own_answer_under_trait_not_independent(db, monkeypatch,
                                                      events):
    """A61: сон повторно видит ответ, созданный ПОД чертой (ledger помечен
    rule_tag) → подкрепления нет."""
    oid = await _mk_self_obs(db)
    rule_id, _ = await sm.promote_observation(db, oid, scope_chat_id=CHAT)
    rules = await db.list_behavior_rules(AGENT, "active")
    tag = sm.rule_tag(rules[0]["id"], rules[0]["version"])
    # Ответ бота под чертой: self-факт от собственного ответа с маркером.
    fid = await db.save_typed_fact(
        chat_id=CHAT, fact="суть моего ответа", origin="bot_self_reply")
    await db.db.execute(
        "UPDATE graph_facts SET tg_message_id = 555 WHERE id = ?", (fid,))
    await db.db.execute(
        "INSERT INTO mca_bot_outputs (chat_id, tg_message_id, "
        "output_kind, source_feature, delivery_status, created_at) VALUES "
        "(?, 555, 'direct_reply', ?, 'delivered', 1)",
        (CHAT, f"direct_chat|{tag}"))
    await db.db.commit()
    verdict = await sm.reinforce_rule(
        db, rule_id, delta=0.05, refs=(f"fact:{fid}",),
        scope_chat_id=CHAT)
    assert verdict.allowed is False
    assert verdict.reason == "own_output_not_independent"
    assert any(kw.get("reason_code") == "trait_reinforcement_dedup"
               for _, kw in events)


@pytest.mark.asyncio
async def test_step_guards_and_weakening(db, events, monkeypatch):
    oid = await _mk_self_obs(db)
    rule_id, _ = await sm.promote_observation(db, oid, scope_chat_id=CHAT)
    # Шаг > капа (0.1/цикл; 0.2/24ч) → отказ trait_step_limit.
    verdict = await sm.reinforce_rule(
        db, rule_id, delta=0.3, refs=("fact:301",), scope_chat_id=CHAT)
    assert verdict.allowed is False
    assert verdict.reason == "trait_step_limit"
    assert any(kw.get("reason_code") == "trait_step_limit"
               for _, kw in events)
    # В капе — ок.
    ok = await sm.reinforce_rule(
        db, rule_id, delta=0.1, refs=("fact:302",), scope_chat_id=CHAT)
    assert ok.allowed
    # Ослабление — допустимо (кап не ограничивает delta<0).
    weaker = await sm.reinforce_rule(
        db, rule_id, delta=-0.15, refs=("fact:303",), scope_chat_id=CHAT)
    assert weaker.allowed
    rules = await db.list_behavior_rules(AGENT, "active")
    assert rules[0]["target_value"] == pytest.approx(0.0)   # 0.1-0.15 → 0
    # Env-границы читаются из настроек.
    monkeypatch.setattr(mca_gates, "trait_max_step_per_cycle",
                        lambda: 0.05)
    capped = await sm.reinforce_rule(
        db, rule_id, delta=0.1, refs=("fact:304",), scope_chat_id=CHAT)
    assert capped.reason == "trait_step_limit"


@pytest.mark.asyncio
async def test_mood_ttl_guards(db, monkeypatch):
    """TTL настроения 6 ч (env-only); настроение обратимо."""
    assert mca_gates.mood_ttl_seconds() == 6 * 3600
    # M-2 (rework): порог — ClassVar Settings (env `MCA_MOOD_TTL_HOURS`
    # больше не игнорируется), а не зашитое значение.
    from config.settings import settings
    assert hasattr(settings, "MCA_MOOD_TTL_HOURS")

    class _MoodSettings:          # ClassVar — не dataclass-поле
        MCA_MOOD_TTL_HOURS = 2
    monkeypatch.setattr(mca_gates, "settings", _MoodSettings)
    assert mca_gates.mood_ttl_seconds() == 2 * 3600
    # Истёкшее настроение не попадает в snapshot (read-side, блок B тесты
    # покрывают write-side; здесь — gate-контракт).
    assert sm.guard_mood_reversible("mood", 1_000, now=5_000).allowed is False


def test_mood_ttl_env_override_read(tmp_path):
    """M-2 (rework, pre-fix RED): env `MCA_MOOD_TTL_HOURS=2` реально читается
    процессом (ClassVar → 7200, а не зашитые 21600)."""
    import os
    import pathlib
    import subprocess
    import sys
    root = pathlib.Path(__file__).resolve().parent.parent
    env = dict(os.environ, ADMINBOT_SKIP_DOTENV="1",
               MCA_MOOD_TTL_HOURS="2")
    code = ("import sys; sys.path.insert(0, r'%s'); "
            "from services import mca_gates; "
            "print(mca_gates.mood_ttl_seconds())" % root)
    res = subprocess.run([sys.executable, "-c", code], cwd=str(root),
                         env=env, capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-500:]
    assert res.stdout.strip() == "7200"


@pytest.mark.asyncio
async def test_rule_tag_marking_format():
    assert sm.rule_tag(12, 3) == "trait:12:v3"


# ═══ T-5083: границы смежных механизмов ═════════════════════════════════════

@pytest.mark.asyncio
async def test_boundary_lesson_not_trait(db):
    verdict = sm.guard_lesson_not_identity("lesson", "self_trait")
    assert verdict.allowed is False
    # lesson-наблюдение не активирует правило черты.
    oid = await sm.record_trait_observation(
        db, agent_id=AGENT, text="урок: проверяй источники",
        source_refs=("lesson:1",), subject_status="self", chat_id=CHAT,
        dimension=None)
    rule_id, v = await sm.promote_observation(db, oid, scope_chat_id=CHAT)
    assert v.reason == "candidate_unmapped_dimension"   # не active
    assert await db.list_behavior_rules(AGENT, "active") == []


@pytest.mark.asyncio
async def test_boundary_paradigm_period_vs_trait():
    """Парадигма mca-06 — вне периода неприменима; чертой не становится."""
    assert sm.guard_paradigm_period(
        "paradigm", 1_000, 2_000, now=3_000).allowed is False
    verdict = sm.guard_fact_not_self_trait("paradigm", "self_trait")
    # Парадигма ≠ факт о мире → запрет «факт ≠ черта» не для неё, но
    # self_trait из парадигмы запрещён write-гардом субъекта.
    assert sm.check_typed_write(
        memory_kind="self_trait", perspective="other",
        subject_entity_id="paradigm:1", agent_id=AGENT).allowed is False


@pytest.mark.asyncio
async def test_boundary_style_request_not_trait(db):
    """Style request mca-08 — разовая директива; не удаляет и не создаёт
    черту (precedence в компиляторе)."""
    snap = _snapshot_with([{"dimension": "сарказм"}])
    frame = sm.select_behavior(snap, scoped_request=("без сарказма",))
    assert frame.applied_rules == ()
    assert frame.rejected_rules[0].reason == "shadowed_by_scoped_request"
    assert await db.list_behavior_rules(AGENT, "active") == []  # черт нет


@pytest.mark.asyncio
async def test_boundary_own_outputs_not_confirmation(db):
    """mca-22: свои ответы — не независимое подтверждение (вне trait-
    маркировки — self-ответы от bot_self_reply с ledger-маркером ДРУГОГО
    правила независимы для этого правила, но помеченное — нет)."""
    fid = await db.save_typed_fact(chat_id=CHAT, fact="ответ",
                                   origin="bot_self_reply")
    await db.db.execute(
        "UPDATE graph_facts SET tg_message_id = 777 WHERE id = ?", (fid,))
    await db.db.execute(
        "INSERT INTO mca_bot_outputs (chat_id, tg_message_id, "
        "output_kind, source_feature, delivery_status, created_at) VALUES "
        "(?, 777, 'direct_reply', 'direct_chat|trait:999:v1', "
        "'delivered', 1)", (CHAT,))
    await db.db.commit()
    # Для правила 999 собственный ответ — НЕ подтверждение.
    assert await sm._rule_sources_independent(db, 999, (f"fact:{fid}",)) \
        is False
    # Для другого правила этот же ответ — независимый источник.
    assert await sm._rule_sources_independent(db, 42, (f"fact:{fid}",)) \
        is True
