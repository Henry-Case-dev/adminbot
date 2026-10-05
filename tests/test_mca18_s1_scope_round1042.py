"""MCA-18 — S-1 rework (Scanner-аудит T-5093): read-side enforcement
chat-binding applicability.

Контракт (spec §6/D8; §28.4 `:1584` — «отношения к участнику и особенности
одного чата локальны; chat→global требует явного правила и
обезличивания»):
  * правило с `applicability=["chat:X"]` (создаёт `promote_observation`,
    scope='chat') применяется ТОЛЬКО при запуске в чате X; в другом чате
    и в глобальном запуске — исключено с видимой причиной
    `out_of_scope_chat` (rejected_rules, не молча);
  * global-правило без chat-биндинга действует в любом чате — не задето;
  * репро Scanner'а: chat:111-правило не попадает в BehaviorFrame и в
    `<Persona>`-блок запуска чата 222; его собственный чат не задет.

R17: синтетические строки; без секретов.
"""
import asyncio
import dataclasses

import pytest

from services import bot_persona, mca_events
from services import mca_self_model as sm
from services.database import DatabaseService

CHAT_A = 111
CHAT_B = 222
AGENT = "agent-uuid-fixed"


def async_returns(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


@pytest.fixture
def db(tmp_path):
    async def _make():
        d = DatabaseService(str(tmp_path / "mca18_s1_scope.db"))
        await d.initialize()
        # Seed agent_id — случайный uuid4: фиксируем под AGENT (прецедент
        # db-фикстуры block_ef), иначе resolve не найдёт правила.
        await d.db.execute("UPDATE mca_self_identity SET agent_id = ? "
                           "WHERE id = true", (AGENT,))
        await d.db.commit()
        return d

    loop = asyncio.new_event_loop()
    try:
        d = loop.run_until_complete(_make())
    finally:
        loop.close()
    yield d
    loop2 = asyncio.new_event_loop()
    try:
        loop2.run_until_complete(d.close())
    finally:
        loop2.close()


def _trait(**kw):
    base = dict(rule_id=11, dimension="резкость", target_value=0.7,
                strength=0.5, scope="chat", applicability=("chat:111",),
                exclusions=(), version=3)
    base.update(kw)
    return sm.TraitView(**base)


def _snap(scope_chat_id, *traits):
    return sm.SelfModelSnapshot(
        agent_id=AGENT, bot_user_id=4242, identity_binding="bound",
        persona_id=None, persona_version="p", scope_chat_id=scope_chat_id,
        name="", aliases=(), biography="", style_version=None,
        traits=tuple(traits), interests=(), relations=(), state=None,
        positions=(),
        persona_enabled=sm.SettingState(key="flags.persona_enabled",
                                        value=True, source="default"),
        is_aware_ai=sm.SettingState(key="personas.is_aware_ai", value=True,
                                    source="default"),
        bot_self_awareness=sm.SettingState(
            key="flags.bot_self_awareness_enabled", value=True,
            source="default"),
        self_presentation_mode=sm.MODE_AWARE,
        capabilities=sm.build_capabilities(), rules_status="on",
        version="snapv1", created_at=1_000)


# ═══ S-1: chat-binding сверяется с чатом запуска (select_behavior) ══════════

def test_chat_bound_rule_not_applied_in_other_chat_or_global_run():
    chat_rule = _trait()
    # Чужой чат: НЕ в applied, причина видима в rejected_rules.
    frame_b = sm.select_behavior(_snap(CHAT_B, chat_rule))
    assert frame_b.applied_rules == ()
    assert [(r.rule_id, r.reason) for r in frame_b.rejected_rules] == \
        [(11, "out_of_scope_chat")]
    # Глобальный запуск (scope_chat_id=None) — тоже не применяется.
    frame_g = sm.select_behavior(
        dataclasses.replace(_snap(CHAT_B, chat_rule), scope_chat_id=None))
    assert frame_g.applied_rules == ()
    assert [r.reason for r in frame_g.rejected_rules
            if r.rule_id == 11] == ["out_of_scope_chat"]
    # Свой чат — применяется (негативный контроль).
    frame_a = sm.select_behavior(_snap(CHAT_A, chat_rule))
    assert [r.rule_id for r in frame_a.applied_rules] == [11]
    # Смешанный кадр: чужое chat-правило исключено, global-сосед не задет.
    global_rule = _trait(rule_id=21, dimension="краткость", scope="global",
                         applicability=("banter",), version=1)
    mixed = sm.select_behavior(_snap(CHAT_B, chat_rule, global_rule))
    assert [r.rule_id for r in mixed.applied_rules] == [21]
    assert [(r.rule_id, r.reason) for r in mixed.rejected_rules] == \
        [(11, "out_of_scope_chat")]
    # Нечитаемый chat-биндинг — fail-closed (не применяется нигде).
    bad = _trait(rule_id=12, applicability=("chat:abc",))
    frame_bad = sm.select_behavior(_snap(CHAT_A, bad))
    assert frame_bad.applied_rules == ()
    assert [r.reason for r in frame_bad.rejected_rules
            if r.rule_id == 12] == ["out_of_scope_chat"]


def test_global_rule_applies_in_every_chat():
    """Не-регрессия: правила без chat-биндинга (global/темы) не задеты."""
    global_rule = _trait(rule_id=21, dimension="краткость", scope="global",
                         applicability=("banter",), version=1)
    for chat in (CHAT_A, CHAT_B, None):
        frame = sm.select_behavior(_snap(chat, global_rule))
        assert [r.dimension for r in frame.applied_rules] == ["краткость"]
        assert frame.rejected_rules == ()


# ═══ Репро Scanner'а (offline SQLite): promote → resolve → frame → <Persona>═

@pytest.mark.asyncio
async def test_scanner_repro_chat111_rule_not_in_chat222_persona(
        db, monkeypatch):
    monkeypatch.setattr(bot_persona, "resolve_bot_persona",
                        async_returns(bot_persona.BotPersona.empty()))
    monkeypatch.setattr(sm, "resolve_is_aware_ai", async_returns(
        sm.SettingState(key="personas.is_aware_ai", value=True,
                        source="default")))
    # Правило из чата 111 (путь promote_observation: scope='chat' +
    # applicability=["chat:111"]).
    oid = await sm.record_trait_observation(
        db, agent_id=AGENT, text="резче в спорах", source_refs=("fact:1",),
        subject_status="self", chat_id=CHAT_A, dimension="резкость")
    rule_id, verdict = await sm.promote_observation(db, oid,
                                                    scope_chat_id=CHAT_A)
    assert verdict.allowed and rule_id is not None
    # Global-правило (без chat-биндинга) — контроль «не пострадало».
    cursor = await db.db.execute(
        "INSERT INTO mca_behavior_rules (agent_id, dimension, target_value, "
        "strength, confidence_basis, scope, applicability, exclusions, "
        "status, status_reason, source_observation_ids, version, updated_at) "
        "VALUES (?, 'краткость', 0.5, NULL, NULL, 'global', '[\"banter\"]', "
        "NULL, 'active', NULL, '[999]', 1, 1000)", (AGENT,))
    global_rule_id = int(cursor.lastrowid)
    await db.db.commit()
    rules = await db.list_behavior_rules(AGENT, "active")
    assert len(rules) == 2

    # Запуск в чате 222: chat:111-правило НЕ в кадре и НЕ в <Persona>.
    snap_b = await sm.resolve_self_model(db, CHAT_B)
    frame_b = sm.select_behavior(snap_b)
    assert all(r.rule_id != rule_id for r in frame_b.applied_rules)
    assert any(r.rule_id == rule_id and r.reason == "out_of_scope_chat"
               for r in frame_b.rejected_rules)
    assert any(r.rule_id == global_rule_id for r in frame_b.applied_rules)
    block_b = sm.render_frame_block(frame_b, is_aware_ai=True)
    assert "Ты отвечаешь резче" not in block_b
    assert "Ты отвечаешь короче обычного" in block_b

    # Свой чат 111: правило применяется (global тоже не задет).
    snap_a = await sm.resolve_self_model(db, CHAT_A)
    frame_a = sm.select_behavior(snap_a)
    assert {r.rule_id for r in frame_a.applied_rules} == \
        {rule_id, global_rule_id}
    block_a = sm.render_frame_block(frame_a, is_aware_ai=True)
    assert "Ты отвечаешь резче" in block_a
