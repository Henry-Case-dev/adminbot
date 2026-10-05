"""MCA-18 `mca-18-self-model` — focused-тесты блока B (T-5077/T-5078).

Покрытие (ADR-1028-18 D4; §28.3 `:1529–1546`; A59 `:940`):
  * типированная запись в graph_facts (расширение контракта mca-03/04a,
    НЕ копия графа): roundtrip + CHECK-рубеж схемы;
  * атрибуция `:1533`: self — по agent_id; «я» в цитате — автор цитаты;
    «бот» без референта — ambiguous (характер не меняет); автор пересылки/
    поста/изображённый — разные роли;
  * запреты таблицы `:1535–1544` — негативный тест на каждый запрет;
  * adoption (D4): «в чате принято X» ≠ «я предпочитаю X» — позиции только
    через mca_adoption_links с основаниями; повтор фразы группой ≠ мнение;
  * K2 OFF: таблицы черт инертны (честный disabled), K1 OFF — resolve off.
"""
import pytest

from services import mca_events, mca_gates
from services import mca_self_model as sm
from services.database import DatabaseService

CHAT = -100500
AGENT = "agent-uuid-fixed"
OTHER = "user:vasya"


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
def db(tmp_path):
    import asyncio

    async def _make():
        d = DatabaseService(str(tmp_path / "mca18_b.db"))
        await d.initialize()
        # Фиксированный agent_id для атрибуции (сид перезаписываем явно).
        await d.rebind_self_identity(bot_user_id=4242, note="test")
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
    import asyncio as _aio
    loop2 = _aio.new_event_loop()
    try:
        loop2.run_until_complete(d.close())
    finally:
        loop2.close()


# ═══ T-5077: типированная память (roundtrip + CHECK) ════════════════════════

@pytest.mark.asyncio
async def test_typed_fact_roundtrip_and_check(db):
    fid = await db.save_typed_fact(
        chat_id=CHAT, fact="Вася стал грубее за период",
        subject_entity_id=OTHER, speaker_entity_id="user:petya",
        perspective="other", memory_kind="world_fact", scope="chat",
        valid_from=1_000, valid_to=2_000,
        confidence_basis='{"anchors": 2}')
    assert fid is not None
    fact = await db.get_typed_fact(fid)
    assert fact["fact"] == "Вася стал грубее за период"
    assert fact["perspective"] == "other"
    assert fact["memory_kind"] == "world_fact"
    assert fact["scope"] == "chat"
    assert fact["revision"] == 1                  # NOT NULL DEFAULT 1
    assert fact["status"] == "confirmed"          # REUSE (Epic 60)
    assert fact["weight"] == 0.5                  # REUSE
    # CHECK-рубеж: недопустимая перспектива → отказ записи (fail-open).
    bad = await db.save_typed_fact(chat_id=CHAT, fact="x",
                                   perspective="bogus")
    assert bad is None
    bad = await db.save_typed_fact(chat_id=CHAT, fact="x",
                                   memory_kind="gossip")
    assert bad is None
    bad = await db.save_typed_fact(chat_id=CHAT, fact="x", scope="room")
    assert bad is None


# ═══ T-5077: атрибуция (A59) ════════════════════════════════════════════════

def test_attribution_self_by_agent_id():
    attr = sm.attribute_memory(
        sm.AttributionInput(agent_id=AGENT, speaker_entity_id=AGENT),
        declared_kind="self_trait")
    assert attr.perspective == "self"
    assert attr.subject_entity_id == AGENT
    assert attr.subject_status == "self"
    assert attr.memory_kind == "self_trait"


def test_attribution_first_person_in_quote_belongs_to_quote_author():
    """«я увольняюсь» внутри цитаты — слова автора цитаты, не наши."""
    attr = sm.attribute_memory(
        sm.AttributionInput(agent_id=AGENT, speaker_entity_id="user:petya",
                            quote_author_entity_id=OTHER,
                            first_person_in_quote=True),
        declared_kind="self_trait")
    assert attr.perspective == "quoted"
    assert attr.subject_entity_id == OTHER        # не наш агент
    assert attr.subject_status == "other"
    # self_trait из чужой цитаты не создаётся.
    assert attr.memory_kind is None


def test_attribution_quote_by_our_agent_is_self():
    attr = sm.attribute_memory(
        sm.AttributionInput(agent_id=AGENT, speaker_entity_id=OTHER,
                            quote_author_entity_id=AGENT,
                            first_person_in_quote=True),
        declared_kind="self_event")
    assert attr.perspective == "quoted"
    assert attr.subject_entity_id == AGENT
    assert attr.subject_status == "self"
    assert attr.memory_kind == "self_event"


def test_attribution_bot_without_referent_is_ambiguous():
    """«бот» без доказанного референта — ambiguous; характер не меняет:
    self_trait не создаётся, наблюдение остаётся с причиной."""
    attr = sm.attribute_memory(
        sm.AttributionInput(agent_id=AGENT, speaker_entity_id="user:petya",
                            bot_referent_proven=False),
        declared_kind="self_trait")
    assert attr.perspective == "ambiguous"
    assert attr.subject_entity_id is None
    assert attr.ambiguous_reason == "bot_no_referent"
    assert attr.subject_status == "ambiguous"
    assert attr.memory_kind is None               # черта НЕ пишется


def test_attribution_other_bot_trait_does_not_change_character():
    """«Другой бот стал грубее» — other; self_trait не создаётся (A59)."""
    attr = sm.attribute_memory(
        sm.AttributionInput(agent_id=AGENT, speaker_entity_id="user:petya",
                            proven_subject_entity_id="bot:external:1"),
        declared_kind="self_trait")
    assert attr.perspective == "other"
    assert attr.subject_entity_id == "bot:external:1"
    assert attr.memory_kind is None


def test_attribution_roles_are_distinct():
    """Автор пересылки / автор исходного поста / изображённый — разные роли
    (mca-03/22 CanonicalMessage.roles + изображённый mca-19)."""
    inp = sm.AttributionInput(
        agent_id=AGENT, speaker_entity_id="user:petya",
        quote_author_entity_id="user:vasya",
        forward_author_entity_id="user:olga",
        post_author_entity_id="channel:news",
        depicted_author_entity_id="person:photo:1")
    roles = inp.role_entity_ids()
    assert roles == {
        "author": "user:petya",
        "quoted_author": "user:vasya",
        "forward_author": "user:olga",
        "post_author": "channel:news",
        "depicted_author": "person:photo:1",
    }
    assert len(set(roles.values())) == 5          # роли не сливаются


# ═══ T-5078: запреты таблицы :1535–1544 — по одному негатив-тесту ═══════════

def test_prohibition_fact_is_not_self_trait():
    verdict = sm.guard_fact_not_self_trait("world_fact", "self_trait")
    assert verdict.allowed is False
    assert verdict.reason == "fact_is_not_self_trait"
    assert sm.guard_fact_not_self_trait("world_fact", "world_fact").allowed


def test_prohibition_own_output_is_not_proof():
    verdict = sm.guard_own_output_not_proof(["self_event"], "world_fact")
    assert verdict.allowed is False
    assert verdict.reason == "own_output_is_not_proof"
    # Не-self источники и не-факты — допустимо.
    assert sm.guard_own_output_not_proof(["search"], "world_fact").allowed
    assert sm.guard_own_output_not_proof(["self_event"], "self_event").allowed


def test_prohibition_trait_not_all_topics():
    verdict = sm.guard_trait_applicability((), ())
    assert verdict.allowed is False
    assert verdict.reason == "trait_applicability_unbounded"
    assert sm.guard_trait_applicability(("banter",), ()).allowed
    assert sm.guard_trait_applicability((), ("formal",)).allowed


def test_prohibition_opinion_is_not_fact():
    verdict = sm.guard_opinion_not_fact("opinion", "factual_constraint")
    assert verdict.allowed is False
    assert verdict.reason == "opinion_is_not_fact"
    # Как позиция/голос — допустимо.
    assert sm.guard_opinion_not_fact("opinion", "position").allowed
    assert sm.guard_opinion_not_fact("world_fact",
                                     "factual_constraint").allowed


def test_prohibition_belief_is_not_personal_value():
    verdict = sm.guard_belief_not_value("belief", has_adoption_link=False)
    assert verdict.allowed is False
    assert verdict.reason == "belief_is_not_personal_value"
    # С adoption-связью — допустимо (осознанное принятие из опыта).
    assert sm.guard_belief_not_value("belief",
                                     has_adoption_link=True).allowed


def test_prohibition_paradigm_outside_period():
    now = 5_000
    assert sm.guard_paradigm_period(
        "paradigm", 1_000, 9_000, now).allowed
    before = sm.guard_paradigm_period("paradigm", 6_000, 9_000, now)
    assert (before.allowed, before.reason) == (False,
                                               "paradigm_before_period")
    after = sm.guard_paradigm_period("paradigm", 1_000, 4_000, now)
    assert (after.allowed, after.reason) == (False, "paradigm_after_period")
    unbounded = sm.guard_paradigm_period("paradigm", None, None, now)
    assert (unbounded.allowed, unbounded.reason) == (
        False, "paradigm_period_unbounded")
    assert sm.guard_paradigm_period("world_fact", None, None, now).allowed


def test_prohibition_mood_reversible():
    """Настроение — обратимая поправка: TTL обязателен, истёкшее неактивно;
    необратимого изменения личности нет."""
    missing = sm.guard_mood_reversible("mood", None)
    assert (missing.allowed, missing.reason) == (False, "mood_ttl_required")
    expired = sm.guard_mood_reversible("mood", 1_000, now=2_000)
    assert (expired.allowed, expired.reason) == (False, "mood_expired")
    assert sm.guard_mood_reversible("mood", 3_000, now=2_000).allowed


def test_prohibition_lesson_is_not_identity():
    verdict = sm.guard_lesson_not_identity("lesson", "self_trait")
    assert verdict.allowed is False
    assert verdict.reason == "lesson_is_not_identity"
    assert sm.guard_lesson_not_identity("lesson", "lesson").allowed


# ═══ Сводный write-гард + e2e store_typed_memory ════════════════════════════

@pytest.mark.asyncio
async def test_write_guard_self_trait_requires_proven_self(db):
    verdict = sm.check_typed_write(
        memory_kind="self_trait", perspective="ambiguous",
        subject_entity_id=None, agent_id=AGENT)
    assert (verdict.allowed, verdict.reason) == (
        False, "self_trait_requires_proven_self")
    verdict = sm.check_typed_write(
        memory_kind="self_trait", perspective="self",
        subject_entity_id=AGENT, agent_id=AGENT,
        applicability=("banter",))
    assert verdict.allowed is True


@pytest.mark.asyncio
async def test_store_typed_memory_rejects_and_stores(db, events):
    # Self-trait без условий применимости → отказ с причиной, не запись.
    attr_self = sm.attribute_memory(
        sm.AttributionInput(agent_id=AGENT, speaker_entity_id=AGENT),
        declared_kind="self_trait")
    fact_id, verdict = await sm.store_typed_memory(
        db, chat_id=CHAT, fact="отвечаю резко", attribution=attr_self,
        agent_id=AGENT, memory_kind="self_trait")
    assert fact_id is None
    assert verdict.reason == "trait_applicability_unbounded"
    # С applicability — пишется.
    fact_id, verdict = await sm.store_typed_memory(
        db, chat_id=CHAT, fact="отвечаю резко в перепалках",
        attribution=attr_self, agent_id=AGENT, memory_kind="self_trait",
        scope="chat", applicability=("banter", "dispute"))
    assert fact_id is not None and verdict.allowed
    # Настроение без TTL → отказ; с TTL → пишется.
    attr_self_event = sm.Attribution(
        perspective="self", subject_entity_id=AGENT,
        speaker_entity_id=AGENT, memory_kind="mood", subject_status="self")
    fact_id, verdict = await sm.store_typed_memory(
        db, chat_id=CHAT, fact="раздражён", attribution=attr_self_event,
        agent_id=AGENT, memory_kind="mood")
    assert fact_id is None and verdict.reason == "mood_ttl_required"
    fact_id, verdict = await sm.store_typed_memory(
        db, chat_id=CHAT, fact="раздражён", attribution=attr_self_event,
        agent_id=AGENT, memory_kind="mood", scope="chat",
        valid_from=1_000, valid_to=1_000 + 6 * 3600, now=1_100)
    assert fact_id is not None
    # Свой ответ ≠ доказательство: self_event-основание не проводит world_fact.
    attr_other = sm.Attribution(
        perspective="other", subject_entity_id=OTHER,
        speaker_entity_id="user:petya", memory_kind="world_fact",
        subject_status="other")
    fact_id, verdict = await sm.store_typed_memory(
        db, chat_id=CHAT, fact="X — проверенный факт",
        attribution=attr_other, agent_id=AGENT, memory_kind="world_fact",
        evidence_kinds=("self_event",))
    assert fact_id is None
    assert verdict.reason == "own_output_is_not_proof"


@pytest.mark.asyncio
async def test_ambiguous_write_emits_event_and_stores_observation(
        db, events):
    """ambiguous: наблюдение хранится с перспективой ambiguous и событием
    `trait_attribution_ambiguous`, характер не меняет (черты нет)."""
    attr = sm.attribute_memory(
        sm.AttributionInput(agent_id=AGENT, speaker_entity_id="user:petya",
                            bot_referent_proven=False))
    fact_id, verdict = await sm.store_typed_memory(
        db, chat_id=CHAT, fact="бот стал грубее", attribution=attr,
        agent_id=AGENT, memory_kind=None)
    assert fact_id is not None and verdict.allowed
    fact = await db.get_typed_fact(fact_id)
    assert fact["perspective"] == "ambiguous"
    assert fact["memory_kind"] is None
    assert any(kw.get("reason_code") == "trait_attribution_ambiguous"
               for _, kw in events)


# ═══ T-5078: adoption — «в чате принято X» ≠ «я предпочитаю X» ══════════════

@pytest.mark.asyncio
async def test_adoption_requires_basis(db):
    with pytest.raises(ValueError):
        await db.record_adoption_link(opinion_ref="fact:1", basis_refs=())
    with pytest.raises(ValueError):
        await db.record_adoption_link(opinion_ref="", basis_refs=("s:1",))
    link_id = await db.record_adoption_link(
        opinion_ref="fact:42", basis_refs=("src:1", "src:2"),
        adopted_at=1_234, subject_entity_id=AGENT)
    assert link_id is not None
    # Повтор — тот же id (UNIQUE subject+opinion), дублей нет.
    again = await db.record_adoption_link(
        opinion_ref="fact:42", basis_refs=("src:1",), adopted_at=9_999,
        subject_entity_id=AGENT)
    assert again == link_id
    links = await db.list_adoption_links(AGENT)
    assert len(links) == 1
    assert links[0]["basis_refs"] == ("src:1", "src:2")
    assert links[0]["adopted_at"] == 1_234        # первая запись


@pytest.mark.asyncio
async def test_group_repetition_is_not_position(db):
    """«В чате принято X» (world_fact, повтор группой) + попытка adoption →
    позицией НЕ становится: позиции — только memory_kind='opinion'."""
    # Повтор фразы группой — факт о чате (не мнение).
    fact_id = await db.save_typed_fact(
        chat_id=CHAT, fact="в чате принято кидать мемы",
        memory_kind="world_fact", scope="chat")
    # Adoption-связь на этот fact — но позиция собирается только из opinion.
    await db.record_adoption_link(opinion_ref=f"fact:{fact_id}",
                                  basis_refs=("src:9",), adopted_at=1_500,
                                  subject_entity_id=AGENT)
    positions = tuple(await sm._build_positions(
        db, await db.list_adoption_links(AGENT)))
    assert positions == ()
    # Мнение с adoption-связью → позиция с provenance/временем.
    op_id = await db.save_typed_fact(
        chat_id=CHAT, fact="предпочитаю прямые ответы",
        subject_entity_id=AGENT, perspective="self",
        memory_kind="opinion", scope="global")
    await db.record_adoption_link(opinion_ref=f"fact:{op_id}",
                                  basis_refs=("src:1", "src:2"),
                                  adopted_at=2_000,
                                  subject_entity_id=AGENT)
    positions = tuple(await sm._build_positions(
        db, await db.list_adoption_links(AGENT)))
    assert len(positions) == 1
    assert positions[0].text == "предпочитаю прямые ответы"
    assert positions[0].basis_refs == ("src:1", "src:2")
    assert positions[0].adopted_at == 2_000
    # Убеждение сна без adoption → позицией не становится (guard).
    assert sm.guard_belief_not_value("belief",
                                     has_adoption_link=False).allowed is False


# ═══ Read-side snapshot-грани (mood/TraitsView) ═════════════════════════════

@pytest.mark.asyncio
async def test_mood_read_side_reversible_and_chat_priority(db):
    now = 5_000
    await db.save_typed_fact(
        chat_id=CHAT, fact="спокойное настроение", perspective="self",
        subject_entity_id=AGENT, memory_kind="mood", scope="global",
        valid_from=1_000, valid_to=9_000)
    mood = await sm._latest_mood_row(db, AGENT, CHAT, now)
    assert mood is not None and mood["scope"] == "global"
    # Chat-настроение приоритетно.
    await db.save_typed_fact(
        chat_id=CHAT, fact="задорное настроение", perspective="self",
        subject_entity_id=AGENT, memory_kind="mood", scope="chat",
        valid_from=1_000, valid_to=9_000)
    mood = await sm._latest_mood_row(db, AGENT, CHAT, now)
    assert mood["scope"] == "chat" and mood["fact"] == "задорное настроение"
    # Истёкшее настроение не возвращается (обратимость), чат не маскирует.
    await db.db.execute("UPDATE graph_facts SET valid_to = 4000 "
                        "WHERE scope = 'chat' AND memory_kind = 'mood'")
    await db.db.commit()
    mood = await sm._latest_mood_row(db, AGENT, CHAT, now)
    assert mood is not None and mood["scope"] == "global"
    await db.db.execute("UPDATE graph_facts SET valid_to = 4000 "
                        "WHERE memory_kind = 'mood'")
    await db.db.commit()
    assert await sm._latest_mood_row(db, AGENT, CHAT, now) is None


def test_trait_view_unbounded_excluded_with_reason():
    view = sm._compile_trait_view({
        "id": 7, "dimension": "резкость", "target_value": 0.7,
        "strength": 0.5, "scope": "chat", "applicability": None,
        "exclusions": None, "version": 3})
    assert view.included is False
    assert view.excluded_reason == "applicability_unbounded"
    view_ok = sm._compile_trait_view({
        "id": 8, "dimension": "резкость", "target_value": 0.7,
        "strength": 0.5, "scope": "chat", "applicability": '["banter"]',
        "exclusions": None, "version": 3})
    assert view_ok.included is True
    assert view_ok.applicability == ("banter",)


# ═══ Snapshot read-side: K2 OFF — таблицы черт инертны ══════════════════════

@pytest.mark.asyncio
async def test_k2_off_rules_inert(tmp_path, monkeypatch):
    from services import bot_persona
    d = DatabaseService(str(tmp_path / "mca18_b_k2.db"))
    await d.initialize()
    try:
        monkeypatch.setattr(bot_persona, "resolve_bot_persona",
                            async_returns(bot_persona.BotPersona.empty()))
        monkeypatch.setattr(sm, "resolve_is_aware_ai", async_returns(
            sm.SettingState(key="personas.is_aware_ai", value=None,
                            source="default")))
        monkeypatch.setattr(mca_gates, "trait_rules_enabled", lambda: False)
        snap = await sm.resolve_self_model(d, CHAT)
        assert snap.rules_status == "disabled"
        assert snap.traits == ()
        assert snap.state is None
    finally:
        await d.close()


def async_returns(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner
