"""ASAP-FC-VOICE-01 / B — характер как ДАННЫЕ для decision-планеров.

Контракт `plans/features/asap-fc-voice-01/arch/l1-decision-profile-contract.md`
§2/§6 (пп.17-23) и `plans/owner_inputs/2026-11-02-asap-fc-voice-01.md` §5:

* секция `[ПРОФИЛЬ РЕШЕНИЙ]` собирается ОДНОЙ точкой
  (`bot_persona.build_decision_profile_block`) из существующего BehaviorFrame
  (закрытый набор измерений) — не из головного среза прозы `<Persona>`
  (прежний `L1_PERSONA_FRAME_CHARS = 400` удалён);
* профиль — данные для решения: нет инструкций во 2-м лице, нет речевых
  примеров/уровней мата/стилевых директив, нет выдуманных чисел;
* профиль доезжает и до Direct L1, и до Initiative L1 одинаковыми байтами и
  НЕ вытесняется сжатием бюджета (protected в `_cap_context`);
* фоновые машинные стадии (Summary/Sleep/Memory/fact_extract) не получают ни
  Core/Expression, ни профиль и не делают новых веб/provider-вызовов;
* канон: ревизия EVR3 = прежние байты 2.58.148 (EVR2) + ОДНО правило статуса
  секции; откат ведёт ровно на deployed-байты, ступень миграции узнаёт только
  точное совпадение байт.

TEST-LIFECYCLE: CONTRACT owner=ASAP-FC-VOICE-01/B (§5 owner_inputs).
"""
from __future__ import annotations

import json

import pytest

from services import bot_persona
from services import direct_l1 as _l1
from services import mca_self_model as msm
from services import prompt_composer as pc
from services import prompt_migrations as pm
from services import prompt_registry as pr
from services.chat_prompts import DIRECT_L1_PLANNER_SYSTEM_PROMPT as CANON
from services import chat_prompts as cp

CHAT = 424242
CORE = "ЯДРО_ХАРАКТЕРА_ВЕСЁЛОЕ"

#: Прежняя секция планера (головной срез прозы) — быть её не должно.
LEGACY_SECTION = "ХАРАКТЕР (кадр)"
#: Маркеры речевых слоёв Writer'а (в планер не попадают).
SPEECH_MARKERS = ("<Persona>", "<Expression_Settings>", "<Speech_Base>",
                  "<Few_Shot>", "<Humor_Craft>")
#: Маркеры инструкций речи / уровней мата / примеров (профиль = данные).
DIRECTIVE_MARKERS = ("Ты ", "ты ", "отвечай", "пиши", "скажи",
                     "профан", "Нецензурн", "нецензурн",
                     "пример реплики", "Пример:", "стиль ответа")


# ═══ стенд: кадр поведения и L1-пейлоад ═════════════════════════════════════

def make_frame(*, scope_chat_id: int | None = 42, version_seed: str = "a",
               rules=(("инициативность", 0.7), ("краткость", 0.4))):
    """BehaviorFrame из закрытого набора измерений (без LLM/PG)."""
    applied = tuple(
        msm.CompiledRule(
            rule_id=index + 1, dimension=dimension, version=1,
            target_value=value,
            instruction="ИНСТРУКЦИЯ_ВО_ВТОРОМ_ЛИЦЕ_" + dimension,
            source="derived_traits")
        for index, (dimension, value) in enumerate(rules))
    return msm.BehaviorFrame(
        snapshot_version=(version_seed * 32)[:32], scope_chat_id=scope_chat_id,
        addressee=None, agent_id="bot", bot_user_id=999,
        self_presentation_mode="aware", is_aware_ai=True,
        applied_rules=applied, positions=(), mood=None,
        factual_constraints=(), scoped_request=(), rejected_rules=())


@pytest.fixture()
def pinned_frame():
    """Кадр хода (holder mca-18) на время теста: прямой аналог того, что
    ставит `resolve_character_context`, без PG. Пин принадлежит чату кадра."""
    frame = make_frame(scope_chat_id=CHAT)
    _RUN_RESET = getattr(msm, "_RUN_FRAME", None)
    previous = _RUN_RESET.get() if _RUN_RESET is not None else None
    msm.set_run_frame(frame, CHAT)
    try:
        yield frame
    finally:
        if _RUN_RESET is not None:
            _RUN_RESET.set(previous)


def turn_ctx(frame, *, traits=()):
    """`CharacterReadContext` хода: с версией кадра — как после успешного
    `resolve_character_context` (именно она подтверждает «кадр ЭТОГО хода»)."""
    return bot_persona.CharacterReadContext(
        persona=bot_persona.BotPersona.empty(), traits=tuple(traits),
        frame_version=getattr(frame, "version", None))


def clear_pin():
    msm.clear_run_frame() if hasattr(msm, "clear_run_frame") else \
        msm._RUN_FRAME.set(None)


def profile_section(payload: str) -> str:
    marker = f"[{_l1.L1_PROFILE_SECTION}]\n"
    assert marker in payload, payload
    return payload.split(marker, 1)[1].split("\n\n[", 1)[0]


# ═══ 1. профиль: детерминизм, состав, отсутствие инструкций ═════════════════

def test_profile_is_byte_deterministic_for_the_same_frame():
    frame = make_frame()
    first = bot_persona.build_decision_profile_block(None, frame=frame)
    second = bot_persona.build_decision_profile_block(None, frame=frame)
    rebuilt = bot_persona.build_decision_profile_block(
        None, frame=make_frame())          # тот же вход, новый объект кадра
    assert first == second == rebuilt
    assert first.strip()
    # повторный вызов не накапливает состояние (нет кеша/счётчиков)
    assert bot_persona.build_decision_profile_block(None, frame=frame) == first


def test_profile_contains_only_closed_dimension_set():
    frame = make_frame(rules=(
        ("инициативность", 0.7), ("краткость", 0.4), ("сарказм", None),
        ("quality_regression", 0.9),          # чужое измерение (FOREIGN)
        ("выдуманное_измерение", 0.5),        # вне закрытого набора
    ))
    block = bot_persona.build_decision_profile_block(None, frame=frame)
    lines = [line for line in block.splitlines()
             if line.split(":", 1)[0] in msm.INITIAL_DIMENSIONS]
    assert [line.split(":", 1)[0] for line in lines] == \
        ["сарказм", "краткость", "инициативность"]      # фиксированный порядок
    assert "quality_regression" not in block
    assert "выдуманное_измерение" not in block
    # значение не выдумывается: правило без числа честно помечено
    assert "сарказм: без числа" in block
    assert "краткость: 0.40" in block and "инициативность: 0.70" in block
    # инструкции правил во 2-м лице в профиль НЕ переносятся
    assert "ИНСТРУКЦИЯ_ВО_ВТОРОМ_ЛИЦЕ" not in block


def test_profile_has_no_speech_directives_or_examples():
    block = bot_persona.build_decision_profile_block(None, frame=make_frame())
    lowered = block.casefold()
    for marker in DIRECTIVE_MARKERS:
        assert marker.casefold() not in lowered, marker
    for marker in SPEECH_MARKERS:
        assert marker not in block, marker
    # это данные о характере + статус, а не второй промпт
    assert block.startswith("роль: участник чата, не сервис")
    assert "источник: кадр поведения" in block
    assert "не делают ответ обязательным" in block
    assert "Молчание - полноценный исход." in block


def test_profile_absent_is_honest_and_not_invented():
    block = bot_persona.build_decision_profile_block(None)
    assert "источник: кадр поведения недоступен" in block
    assert "привычки (без значений)" not in block
    assert not any(f"{dimension}:" in block for dimension in
                   msm.INITIAL_DIMENSIONS)
    assert bot_persona.decision_profile_source(block) == "legacy"
    # legacy-фолбэк: только ИМЕНА измерений по существующему стем-матчеру
    legacy = bot_persona.build_decision_profile_block(
        bot_persona.CharacterReadContext(
            persona=bot_persona.BotPersona.empty(),
            traits=("сарказм в дружеской перепалке", "спорит по любому поводу")))
    assert "привычки (без значений): сарказм, склонность спорить" in legacy
    assert "0." not in legacy                       # чисел без правил нет


def test_decision_profile_source_is_structural_not_substring():
    """RED на 1aa818c5: legacy-блок («источник: кадр поведения недоступен»)
    содержит текст frame-строки, и трасса врала `frame` ровно в деградированном
    случае (ревью W2/P1, F2)."""
    frame_block = bot_persona.build_decision_profile_block(
        None, frame=make_frame())
    legacy_block = bot_persona.build_decision_profile_block(None)
    # ловушка подстроки: frame-строка целиком входит в legacy-строку
    assert "источник: кадр поведения" in legacy_block
    assert bot_persona.decision_profile_source(frame_block) == "frame"
    assert bot_persona.decision_profile_source(legacy_block) == "legacy"
    # неизвестный/пустой блок не имеет права называться frame
    assert bot_persona.decision_profile_source("") == "legacy"
    assert bot_persona.decision_profile_source("роль: участник чата") == "legacy"


# ═══ 2. пейлоад Direct L1: секция есть, прозы/речи нет, сжатие не съедает ═══

def test_l1_payload_carries_profile_instead_of_persona_prose(pinned_frame):
    profile = bot_persona.build_decision_profile_block(
        turn_ctx(pinned_frame), chat_id=pinned_frame.scope_chat_id)
    payload = _l1.build_l1_context(
        query="почему упал сервис", window=[], speaker="Аня",
        addressee="чат", capabilities=("web_search",), decision_profile=profile)
    section = profile_section(payload)
    assert _l1.L1_PROFILE_SECTION in payload
    assert "инициативность: 0.70" in section and "краткость: 0.40" in section
    assert pinned_frame.version in section          # provenance секции
    assert f"[{LEGACY_SECTION}]" not in payload      # прежнего среза нет
    assert "ИНСТРУКЦИЯ_ВО_ВТОРОМ_ЛИЦЕ" not in payload
    for marker in SPEECH_MARKERS:
        assert marker not in payload, marker


def test_profile_survives_budget_compression_at_live_budget():
    """RED на 2.58.148: секция «ХАРАКТЕР (кадр)» стояла последней и
    сжималась/удалялась первой — характер исчезал именно при переполнении."""
    frame = make_frame(rules=tuple(
        (dimension, 0.5) for dimension in msm.INITIAL_DIMENSIONS))
    profile = bot_persona.build_decision_profile_block(None, frame=frame)
    window = [{"id": index, "user_id": 1, "author_name": "Гоша",
               "text": "длинная реплика про сервис " * 30}
              for index in range(20)]
    for budget in (_l1.l1_context_tokens(), 400, 150):
        payload = _l1.build_l1_context(
            query="почему упал сервис " * 40, window=window, speaker="Гоша",
            addressee="чат", capabilities=("web_search",),
            decision_profile=profile, budget_tokens=budget)
        section = profile_section(payload)
        for dimension in msm.INITIAL_DIMENSIONS:
            assert f"{dimension}: 0.50" in section, (budget, dimension)


@pytest.mark.asyncio
async def test_direct_service_l1_payload_gets_profile_from_turn_frame(
        pinned_frame):
    """Реальный путь Direct L1: секция уходит в user-payload вместе с
    источником в трассе; системный промпт — канон без Core/прозы."""
    from services import prompt_style_blocks as psb
    from services.summary_aliases import AliasResolver
    from services.direct_chat_service import DirectChatService as D
    from services import hot_config as hot
    from services import chat_params

    class StubLLM:
        def __init__(self):
            self.captured = []

        async def generate(self, messages, **kwargs):
            self.captured.append({"step": kwargs.get("step"),
                                  "messages": [dict(m) for m in messages]})
            if kwargs.get("step") == "l1_planner":
                return json.dumps({
                    "action": "reply", "response_act": "explanation",
                    "tone": "inherit", "extent": "detailed",
                    "structure": "answer", "delivery_hint": "plain",
                    "tool_policy": "none", "confidence": 0.8,
                    "capabilities_needed": [],
                }, ensure_ascii=False)
            return "ТЕКСТ"

        def _pg(self):
            return None

    class Stub:
        _render_current_question = D._render_current_question
        _l1_speech_hints = D._l1_speech_hints
        _build_speech_understanding = D._build_speech_understanding
        _attach_l1_plan_meta = D._attach_l1_plan_meta
        _compose_speech_system = D._compose_speech_system

        def _l1_reply_block(self, message, budget_tokens=None):
            return D._l1_reply_block(self, message, budget_tokens=budget_tokens)

        async def _history_partial(self, chat_id, window):
            return False

        def __init__(self, llm):
            self.llm = llm
            self.memory = type("M", (), {
                "get_window_messages": staticmethod(
                    lambda chat_id: _empty())})()
            self.db = None
            self.bot_id = 999
            self.aliases = AliasResolver({})

    async def _empty():
        return []

    message = type("M", (), {
        "text": "бот: почему упал сервис", "caption": None, "message_id": 1,
        "chat": type("C", (), {"type": "supergroup"})(),
        "reply_to_message": None, "from_user": None})()

    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    try:
        llm = StubLLM()
        # ctx хода — как из `resolve_character_context`: с версией кадра
        # (ревью W2/P1 §6в: проба обязана покрывать именно этот путь).
        _plan, meta = await D._plan_direct_l1(
            Stub(llm), CHAT, message, "почему упал сервис", None,
            bundle=None, target_name="Аня", user_id=None,
            character_block=CORE,
            character_ctx=turn_ctx(pinned_frame), lore_enabled=False,
            image_enabled=False, force_required=False, reply_bot=False)
        captured = [c for c in llm.captured if c["step"] == "l1_planner"]
        assert captured, "L1-вызов не состоялся"
        system = captured[0]["messages"][0]["content"]
        user_payload = captured[0]["messages"][1]["content"]
        section = profile_section(user_payload)
        assert pinned_frame.version in section
        assert "инициативность: 0.70" in section
        assert CORE not in user_payload and CORE not in system
        for marker in SPEECH_MARKERS:
            assert marker not in user_payload, marker
        assert f"[{LEGACY_SECTION}]" not in user_payload
        assert system == psb.resolve_prompt(
            "prompts.direct_l1_planner_system_prompt", CANON)
        # провенанс секции в существующей трассе, без текста профиля
        assert meta["l1_profile_source"] == "frame"
        assert int(meta["l1_profile_chars"]) == len(section)
        diag = _l1.get_l1_diagnostics(CHAT) or {}
        assert diag.get("l1_profile_source") == "frame"
    finally:
        pc.reset_state()


# ═══ 2b. изоляция ходов/чатов: чужой кадр не переезжает (ревью F1) ═════════

CHAT_A = 111
CHAT_B = 222


def _frame_a():
    """Кадр чата A с ЗАМЕТНЫМИ значениями (то, что ревьюер увидел в чате B)."""
    return make_frame(scope_chat_id=CHAT_A, version_seed="a",
                      rules=(("инициативность", 0.90), ("сарказм", 0.80)))


def test_profile_does_not_reuse_a_pinned_frame_of_another_chat():
    """RED на 1aa818c5: кадр читался из ambient ContextVar, не сбрасывался, и
    чат B получал «инициативность: 0.90 (в этом чате)» от чата A."""
    frame_a = _frame_a()
    msm.set_run_frame(frame_a, CHAT_A)
    try:
        # B без своего ctx (persona OFF / сбой PG) — кадра ЭТОГО хода нет
        block_b = bot_persona.build_decision_profile_block(None, chat_id=CHAT_B)
        assert "0.90" not in block_b and "0.80" not in block_b
        assert frame_a.version not in block_b
        assert "(в этом чате)" not in block_b
        assert "источник: кадр поведения недоступен" in block_b
        assert bot_persona.decision_profile_source(block_b) == "legacy"
        # ctx с версией, но ЧУЖОГО чата — тоже не источник профиля
        ctx_foreign = bot_persona.CharacterReadContext(
            persona=bot_persona.BotPersona.empty(),
            frame_version=frame_a.version)
        block_foreign = bot_persona.build_decision_profile_block(
            ctx_foreign, chat_id=CHAT_B)
        assert "0.90" not in block_foreign and frame_a.version not in block_foreign
        # ctx своей версии, но chat_id не совпал с владельцем пина — отказ
        assert "0.90" not in bot_persona.build_decision_profile_block(
            turn_ctx(frame_a), chat_id=CHAT_B)
        # а свой чат получает кадр как прежде
        own = bot_persona.build_decision_profile_block(
            turn_ctx(frame_a), chat_id=CHAT_A)
        assert "инициативность: 0.90 (в этом чате)" in own
        assert bot_persona.decision_profile_source(own) == "frame"
    finally:
        clear_pin()


def test_profile_rejects_a_stale_pin_of_the_same_chat():
    """Версия из ctx — подтверждение «кадр ЭТОГО хода»: пин со старой версией
    (например, предыдущий ход после сбоя резолва) не принимается."""
    old = _frame_a()
    new = make_frame(scope_chat_id=CHAT_A, version_seed="c",
                     rules=(("инициативность", 0.10),))
    msm.set_run_frame(old, CHAT_A)          # пин остался от прежнего хода
    try:
        ctx_new = turn_ctx(new)             # ctx нового хода
        block = bot_persona.build_decision_profile_block(ctx_new, chat_id=CHAT_A)
        assert "0.10" not in block and "0.90" not in block
        assert "источник: кадр поведения недоступен" in block
    finally:
        clear_pin()


def test_turn_reset_drops_the_previous_chat_frame():
    frame_a = _frame_a()
    msm.set_run_frame(frame_a, CHAT_A)
    bot_persona.reset_turn_frame()
    assert msm.current_run_frame_pin() is None
    assert "0.90" not in bot_persona.build_decision_profile_block(
        turn_ctx(frame_a), chat_id=CHAT_A)


@pytest.mark.asyncio
async def test_initiative_of_chat_b_never_receives_chat_a_values(monkeypatch):
    """Сценарий ревьюера: в одном процессе сначала ход чата A (кадр есть),
    затем инициатива чата B, где персона OFF / резолв упал. В payload B не
    должно быть ни версии, ни значений, ни пометки «(в этом чате)» чата A."""
    from services import direct_chat_service as dcs
    from services.direct_chat_service import DirectChatService as D

    frame_a = _frame_a()
    msm.set_run_frame(frame_a, CHAT_A)      # «предыдущий» ход чата A
    payloads: list[str] = []

    class StubLLM:
        async def generate(self, messages, **kwargs):
            payloads.append(messages[-1]["content"])
            raise RuntimeError("stop-after-context")

    class Mem:
        async def get_window_messages(self, chat_id):
            return [{"id": 5, "user_id": 7, "author_name": "Гоша",
                     "text": "бот читает?"}]

    def _service(character):
        service = D.__new__(D)
        service.llm = StubLLM()
        service.memory = Mem()
        service.db = None
        service.aliases = type("A", (), {
            "resolve": staticmethod(lambda *a, **k: None)})()

        async def _no_aliases(_chat_id):
            return None

        async def _no_replies(_chat_id, **kwargs):
            return ()

        service._initiative_character = character
        service._refresh_turn_aliases = _no_aliases
        service._recent_bot_replies = _no_replies
        return service

    async def _persona_off(_chat_id):
        return "", None                     # persona_enabled=False

    async def _pg_failure(_chat_id):
        raise RuntimeError("PG down")       # сбой резолва

    monkeypatch.setattr(dcs, "reaction_mechanics_enabled", lambda: False)
    try:
        for character in (_persona_off, _pg_failure):
            payloads.clear()
            await D.plan_initiative_decision(
                _service(character), CHAT_B,
                {"goal": "уточнить статус", "kind": "follow_up"})
            assert payloads, "инициативный L1-вызов не состоялся"
            payload = payloads[-1]
            assert frame_a.version not in payload
            assert "инициативность: 0.90" not in payload
            assert "сарказм: 0.80" not in payload
            assert "0.90 (в этом чате)" not in payload
            section = profile_section(payload)
            assert "источник: кадр поведения недоступен" in section
    finally:
        clear_pin()


# ═══ 3. профиль инициативы: те же байты, молчание не отменяется ════════════
@pytest.mark.asyncio
async def test_initiative_payload_gets_same_profile_bytes(pinned_frame,
                                                          monkeypatch):
    from services import direct_chat_service as dcs
    from services.direct_chat_service import DirectChatService as D

    captured = []

    class StubLLM:
        async def generate(self, messages, **kwargs):
            captured.append([dict(m) for m in messages])
            raise RuntimeError("stop-after-context")

    class Mem:
        async def get_window_messages(self, chat_id):
            return [{"id": 5, "user_id": 7, "author_name": "Гоша",
                     "text": "бот читает?"}]

    service = D.__new__(D)
    service.llm = StubLLM()
    service.memory = Mem()
    service.db = None
    service.aliases = type("A", (), {
        "resolve": staticmethod(lambda *a, **k: None)})()

    async def _character(_chat_id):
        # ctx хода с версией кадра — как из `resolve_character_context`;
        # сам кадр берётся из пина ТОЛЬКО при совпадении чата и версии.
        # Стенд повторяет прод: резолв ставит пин (после reset_turn_frame).
        msm.set_run_frame(pinned_frame, _chat_id)
        return "", turn_ctx(pinned_frame)

    async def _no_aliases(_chat_id):
        return None

    async def _no_replies(_chat_id, **kwargs):
        return ()

    monkeypatch.setattr(dcs, "reaction_mechanics_enabled", lambda: False)
    # инстансные подмены: резолв характера и окно ответов не нужны, кадр
    # хода уже пиннут (pinned_frame) — проверяется сборка пейлоада
    service._initiative_character = _character
    service._refresh_turn_aliases = _no_aliases
    service._recent_bot_replies = _no_replies

    await D.plan_initiative_decision(
        service, CHAT, {"goal": "уточнить статус", "kind": "follow_up"})
    assert captured, "инициативный L1-вызов не состоялся"
    system = captured[0][0]["content"]
    payload = captured[0][1]["content"]
    section = profile_section(payload)
    # 17/19: тот же профиль, что получил бы Direct для этого кадра
    assert section == bot_persona.build_decision_profile_block(
        turn_ctx(pinned_frame), chat_id=CHAT)
    assert "инициативность: 0.70" in section
    assert pinned_frame.version in section
    # 18: профиль НЕ является разрешением отвечать — существующие критерии
    # молчания инициативы остались в пакете дословно
    assert "Умерший повод" in payload
    assert "нечего добавить - silent" in payload
    assert "промолчать" in _l1.INITIATIVE_LINE
    assert "никакая форма не имеет приоритета" in _l1.INITIATIVE_LINE
    # канон планера (общий для Direct и Initiative) содержит правило профиля
    assert system == cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert "ПРОФИЛЬ РЕШЕНИЙ" in system
    assert "молчание остается полноценным исходом" in system
    for marker in SPEECH_MARKERS:
        assert marker not in payload, marker


def test_profile_follows_the_next_turn_frame_without_stale_cache():
    first = bot_persona.build_decision_profile_block(
        None, frame=make_frame(version_seed="a",
                               rules=(("инициативность", 0.2),)))
    second = bot_persona.build_decision_profile_block(
        None, frame=make_frame(version_seed="b",
                               rules=(("инициативность", 0.9),)))
    assert first != second
    assert "инициативность: 0.20" in first and "0.20" not in second
    assert "инициативность: 0.90" in second
    assert ("a" * 32) in first and ("b" * 32) in second
    # GLOBAL-scope кадр отличается от chat-scope (precedence — у кадра)
    global_block = bot_persona.build_decision_profile_block(
        None, frame=make_frame(scope_chat_id=None))
    assert "(глобально)" in global_block
    assert "(в этом чате)" in first
    payload_a = _l1.build_l1_context(query="q", decision_profile=first)
    payload_b = _l1.build_l1_context(query="q", decision_profile=second)
    assert profile_section(payload_a) != profile_section(payload_b)


# ═══ 4. негатив фона: машинные стадии без Core/Expression/профиля и без сети ═

BACKGROUND_BLOCKS = (
    "summary.base.single", "summary.base.editor", "summary.base.narrator",
    "summary.base.l1_clusterizer", "memory.extract", "memory.compress",
    "internal.dream.distill", "internal.dream.deep_sleep_bridge",
)


def test_background_stages_get_no_core_expression_or_profile(monkeypatch):
    from services import llm_client
    from services import tool_router

    calls: list[str] = []

    async def _no_provider_call(self, *args, **kwargs):
        calls.append("provider")
        raise AssertionError("фоновая стадия сделала provider-вызов")

    async def _no_web_search(self, *args, **kwargs):
        calls.append("web_search")
        raise AssertionError("фоновая стадия сделала веб-проверку")

    monkeypatch.setattr(llm_client.LLMClient, "_post", _no_provider_call)
    monkeypatch.setattr(tool_router.ToolRouter, "_execute_web_search",
                        _no_web_search)

    for block_id in BACKGROUND_BLOCKS:
        text = pr.factory_text(block_id)
        assert text, block_id
        manifest = pc.compose_machine_system(text, writer=block_id, chat_id=7)
        assert manifest.system == text
        assert manifest.profile == "machine_json"
        trace = {layer.layer: layer for layer in manifest.layers}
        for layer in ("core", "expression", "few_shot", "identity",
                      "humor_craft", "style_policy_hint"):
            assert trace[layer].rendered is False, (block_id, layer)
        for marker in SPEECH_MARKERS + ("[ПРОФИЛЬ РЕШЕНИЙ]",):
            assert marker not in manifest.system, (block_id, marker)
    assert calls == [], calls


# ═══ 5. ревизия канона: EVR3, откат на deployed-байты, ступень миграции ═════

def test_canon_revision_keeps_deployed_bytes_as_rollback_target():
    import hashlib

    assert "ПРОФИЛЬ РЕШЕНИЙ" in CANON
    assert "не меняют факты" in CANON
    # прежние байты = прод 2.58.148 (ревизия EVR2), ровно то, что откатывается
    deployed_sha12 = hashlib.sha256(
        cp.PREV_DIRECT_L1_PLANNER_EVR2.encode("utf-8")).hexdigest()[:12]
    assert deployed_sha12 == "09f3d533d173"
    assert CANON.startswith(cp.PREV_DIRECT_L1_PLANNER_EVR2)
    # правило добавлено ОДНОЙ секцией, а не переписыванием канона
    assert len(CANON) > len(cp.PREV_DIRECT_L1_PLANNER_EVR2)
    assert CANON.replace(
        CANON[len(cp.PREV_DIRECT_L1_PLANNER_EVR2):], "") == \
        cp.PREV_DIRECT_L1_PLANNER_EVR2


def test_migration_and_rollback_only_match_exact_deployed_bytes():
    forward = dict(
        (old, new) for old, new in
        pm.PROMPT_MIGRATIONS["prompts.direct_l1_planner_system_prompt"])
    assert forward[cp.PREV_DIRECT_L1_PLANNER_EVR2] == CANON
    rollback = dict(
        pm.ROLLBACK_MIGRATIONS["prompts.direct_l1_planner_system_prompt"])
    assert rollback[CANON] == cp.PREV_DIRECT_L1_PLANNER_EVR2
    # печать и метка заводской ревизии согласованы с активными байтами
    assert pr.seal_integrity() == {}
    label, sealed = pr.FACTORY_REVISION_SEALS["direct.base.l1_planner"]
    assert label == "l1-planner-decision-profile"
    assert sealed == pr.sha12(CANON)
    assert pr.sealed_factory_revision("direct.base.l1_planner").endswith(
        pr.sha12(label))
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12
