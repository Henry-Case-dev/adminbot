"""UR-11b r2: Writer fallback, provenance identity, anchored extras.

Строки UR-11.4/UR-11 остаются PENDING до независимого re-review.
"""
from types import SimpleNamespace

import pytest

from services import direct_chat_service as dcs
from services import direct_context_composer as comp
from services.token_counter import count_tokens
from services.llm_client import LLMClient, LLMError
from tests.test_direct_chat import (
    FakeDB, FakeLLM, FakeMemory, _make_service, _message,
)

pytestmark = [pytest.mark.asap3, pytest.mark.asap31, pytest.mark.asap32]

CHAT = -100777
BOT_UID = 999000


# ── llm_client: adapter failure => no fallback transport, primary error ─────

def _bare_llm(monkeypatch):
    client = LLMClient.__new__(LLMClient)
    client._base_url = "https://primary"
    client._api_key = "k"
    client._chat_model = "primary"
    client._fallback_base_url = "https://fallback"
    client._fallback_model = "fb"
    client._fallback_api_key = "fk"
    client._fallback_active = True
    client._refresh_chat_model = lambda: None
    client._refresh_transport_policy = lambda: None

    async def _resolve(chat_id=None):
        return "k", "test"

    async def _post(*args, **kwargs):
        raise LLMError("primary down")

    client._resolve_api_key_and_source = _resolve
    client._post_with_key = _post
    client._record_sent_attempts = lambda *a, **k: None
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["generate", "generate_with_metadata"])
@pytest.mark.parametrize("adapter", [
    lambda payload: (_ for _ in ()).throw(RuntimeError("recompose")),
    lambda payload: {"not_messages": True},
])
async def test_adapter_failure_skips_fallback_and_raises_primary(
        monkeypatch, method, adapter):
    client = _bare_llm(monkeypatch)
    fallback_calls: list = []

    async def _fallback(payload, sent=None):
        fallback_calls.append(payload)
        return None

    client._fallback_with_retries = _fallback
    with pytest.raises(LLMError):
        await getattr(client, method)(
            [{"role": "user", "content": "q"}], chat_id=CHAT,
            fallback_payload_adapter=adapter)
    assert fallback_calls == []


@pytest.mark.asyncio
async def test_no_adapter_keeps_legacy_fallback_attempt(monkeypatch):
    client = _bare_llm(monkeypatch)
    fallback_calls: list = []

    async def _fallback(payload, sent=None):
        fallback_calls.append(payload)
        return None

    client._fallback_with_retries = _fallback
    with pytest.raises(LLMError):
        await client.generate([{"role": "user", "content": "q"}],
                              chat_id=CHAT)
    assert len(fallback_calls) == 1


# ── live-direct helpers ─────────────────────────────────────────────────────

class _AdapterLLM:
    """Метаданные-путь, который реально вызывает fallback-адаптер."""

    _chat_model = "primary"
    _base_url = ""
    _fallback_model = "fb"
    _fallback_base_url = ""

    def __init__(self, text="ok"):
        self.text = text
        self.invoke_fallback = True
        self.fallback_calls = 0
        self.fallback_payload = None
        self.fallback_prepared = None
        self.messages = None

    async def generate_with_metadata(self, messages, *, step=None,
                                     fallback_payload_adapter=None,
                                     **kwargs):
        self.messages = messages
        if (self.invoke_fallback and step == "l2_writer"
                and fallback_payload_adapter is not None):
            self.fallback_calls += 1
            adapted, prepared = fallback_payload_adapter(
                {"messages": list(messages)})
            self.fallback_payload = adapted
            self.fallback_prepared = prepared
        return dcs._l2_cont.TextCompletion(self.text)


def _row(i: int, text: str = "") -> dict:
    return {
        "id": i, "tg_message_id": 500 + i, "user_id": 10,
        "author_name": "Вася", "text": text or f"строка-{i}",
        "timestamp": 1_700_000_000 + i, "media_type": "text",
        "reply_to_id": None,
    }


def _force_live(monkeypatch, *, primary=12000, fallback=6000):
    monkeypatch.setattr(dcs._model_capacity,
                        "capacity_resolver_enabled", lambda: True)
    monkeypatch.setattr(dcs._auto_budget,
                        "auto_budget_enabled", lambda: True)

    async def _window(base_url, model, slot=None):
        return 20000, "runtime"

    async def _budget(slot, **kwargs):
        effective = fallback if slot == "direct.fallback" else primary
        return SimpleNamespace(
            context_window=20000, source="runtime",
            auto_input_budget=effective, output_reserve=100,
            effective_input_budget=effective, policy_mode="dynamic")

    monkeypatch.setattr(dcs._model_capacity, "resolve_stage_window", _window)
    monkeypatch.setattr(dcs._auto_budget, "resolve_stage_budget", _budget)


def _live_service(monkeypatch, *, llm=None, primary=12000, fallback=6000,
                  rows=None):
    svc = _make_service(
        memory=FakeMemory(window=list(rows or [
            _row(1), _row(2), _row(3), _row(4)])),
        db=FakeDB({}), bot_id=BOT_UID, llm=llm or FakeLLM("ok"))
    svc.llm._chat_model = "primary"
    svc.llm._fallback_model = "fb"
    svc.llm._base_url = ""
    svc.llm._fallback_base_url = ""
    _force_live(monkeypatch, primary=primary, fallback=fallback)
    return svc


async def _build_live(svc):
    out: dict = {}
    fallback: dict = {}
    blocks = await svc._build_user_content(
        CHAT, _message(text="вопрос"), "Вася",
        out_prepared=out, out_fallback=fallback)
    return list(blocks), out, fallback


def _insert_extra(blocks, *, tag, text, tail=False):
    out = list(blocks)
    if not text:
        return out
    if tail:
        out.append(text)
        return out
    index = next((i for i, b in enumerate(out)
                  if str(b).lstrip().startswith(tag)), None)
    out.insert(len(out) if index is None else index, text)
    return out


def _with_anchored_extras(blocks, *, media="", voice="", dig="", note=""):
    out = _insert_extra(blocks, tag="<Target_User", text=dig)
    out = _insert_extra(out, tag="<Current_Question", text=media)
    out = _insert_extra(out, tag="<Current_Question", text=voice)
    return _insert_extra(out, tag="", text=note, tail=True)


def _body(llm) -> str:
    return str(llm.fallback_payload["messages"][-1]["content"])


# ── T1: live recompose through provenance, legacy not built ─────────────────

@pytest.mark.asyncio
async def test_live_recompose_uses_selection_texts_not_legacy(monkeypatch):
    llm = _AdapterLLM()
    svc = _live_service(monkeypatch, llm=llm)
    blocks, out, fb = await _build_live(svc)

    assert fb.get("selection_texts") == tuple(blocks)
    assert fb.get("selection_payload_tokens") == sum(
        count_tokens(b) for b in blocks)
    assert fb.get("selection_recompose") is True

    legacy: list = []
    real_legacy = dcs._dx.build_l2_fallback_adapter

    def _legacy(*args, **kwargs):
        legacy.append(1)
        return real_legacy(*args, **kwargs)

    monkeypatch.setattr(dcs._dx, "build_l2_fallback_adapter", _legacy)
    out2: dict = {}
    result = await svc._l2_write_answer(
        CHAT, "q", temperature=0.1,
        selection_texts=fb["selection_texts"],
        user_blocks=blocks,
        primary_budget_tokens=fb["l2_input_budget"],
        selection_budget_tokens=fb["selection_budget"],
        fallback_budget_tokens=fb.get("l2_fallback_budget"),
        fallback_selection_factory=fb["adapter_factory"],
        out_prepared=out2)

    assert result is not None
    assert llm.fallback_calls == 1
    assert legacy == []
    body = _body(llm)
    assert "<Global_Context" in body
    assert "<Target_User" in body
    assert "<Current_Question" in body
    assert llm.fallback_prepared.budget["policy_mode"] == "fallback_recompose"
    assert llm.fallback_prepared.budget["payload_tokens"] > 0


# ── T2: allocation failure => capacity with ALL anchored extras ─────────────

@pytest.mark.asyncio
async def test_fallback_capacity_keeps_all_anchored_extras(monkeypatch):
    llm = _AdapterLLM()
    svc = _live_service(monkeypatch, llm=llm)
    blocks, out, fb = await _build_live(svc)
    media = "<media_analysis>MEDIA_MARK</media_analysis>"
    voice = "<voice_transcripts>VOICE_MARK</voice_transcripts>"
    dig = "<dig_result>DIG_MARK</dig_result>"
    note = "[EVIDENCE] NOTE_MARK"
    user_blocks = _with_anchored_extras(
        blocks, media=media, voice=voice, dig=dig, note=note)

    monkeypatch.setattr(comp, "allocate_selection",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("allocation down")))
    out2: dict = {}
    result = await svc._l2_write_answer(
        CHAT, "q", temperature=0.1,
        selection_texts=fb["selection_texts"],
        user_blocks=user_blocks,
        primary_budget_tokens=10000,
        selection_budget_tokens=fb["selection_budget"],
        fallback_budget_tokens=fb.get("l2_fallback_budget"),
        fallback_selection_factory=fb["adapter_factory"],
        out_prepared=out2)

    assert result is not None
    assert llm.fallback_calls == 1
    body = _body(llm)
    for marker in (media, voice, dig, note):
        assert marker in body, marker
    assert "<Target_User" in body and "<Current_Question" in body
    prepared = llm.fallback_prepared
    assert prepared.budget["policy_mode"] == "fallback_capacity"
    assert prepared.budget["degraded"] is True
    assert prepared.budget["physical_overflow"] is True
    assert prepared.budget["payload_tokens"] > 0
    assert body.index(dig) < body.index("<Target_User")
    assert body.index(media) < body.index(voice) < body.index("<Current_Question")


# ── T5: initiative receives provenance; factory is reachable ───────────────

@pytest.mark.asyncio
async def test_initiative_l2_receives_provenance_and_recomposes(monkeypatch):
    from tests.test_ur_turn_engine import (
        _patch_fixed_tool_flags, _plan as _ur_plan, _svc)

    _patch_fixed_tool_flags(monkeypatch)
    rows = [_row(1, "A" * 400), _row(2, "B" * 400)]
    svc = _svc(_ur_plan(), window=rows)
    llm = _AdapterLLM()
    svc.llm = llm
    svc.llm._chat_model = "primary"
    # F6: default production config — fallback-модели нет.
    svc.llm._fallback_model = ""
    svc.llm._base_url = ""
    svc.llm._fallback_base_url = ""
    llm.invoke_fallback = False

    async def _budget(slot, **kwargs):
        return SimpleNamespace(
            effective_input_budget=(
                4000 if kwargs.get("model") == "primary" else 2000),
            context_window=20000, source="runtime",
            auto_input_budget=4000, output_reserve=100,
            policy_mode="dynamic")

    monkeypatch.setattr(dcs._auto_budget, "resolve_stage_budget", _budget)

    async def _persona(chat_id):
        return "PERSONA"

    async def _character(chat_id):
        return "", None

    async def _preflight(*args, **kwargs):
        return None

    monkeypatch.setattr(svc, "_initiative_persona_block", _persona)
    monkeypatch.setattr(svc, "_initiative_character", _character)
    monkeypatch.setattr(svc, "_evidence_preflight", _preflight)

    real_l2 = svc._l2_write_answer
    captured: dict = {}

    async def _capture(*args, **kwargs):
        captured.update(kwargs)
        return await real_l2(*args, **kwargs)

    monkeypatch.setattr(svc, "_l2_write_answer", _capture)
    await svc.generate_initiative_reply(
        CHAT, {"goal": "напомнить про релиз", "kind": "follow_up",
               "origin": "observer"}, correlation_id="c")

    factory = captured.get("fallback_selection_factory")
    assert callable(factory)
    assert captured.get("fallback_budget_tokens") is None, captured
    selection_texts = captured.get("selection_texts") or ()
    assert len(selection_texts) == 2
    assert selection_texts[0].startswith("<Initiative_Context")
    assert selection_texts[1].startswith("<Fresh_Chat_Window")
    context_tokens = count_tokens(selection_texts[0])
    assert captured.get("primary_budget_tokens") == 4000
    assert captured.get("selection_budget_tokens") == max(
        1, 4000 - context_tokens)
    assert captured.get("primary_payload_tokens") == sum(
        count_tokens(t) for t in selection_texts)
    # Без fallback-модели реальный клиент fallback-адаптер не вызывает.
    assert llm.fallback_calls == 0

    # F6: final fit primary обязан работать на default-конфиге. Форсируем
    # фактическое превышение primary бюджета (payload == budget) и проверяем
    # factory 1×, legacy 0×, primary budget в prepared.
    calls: list = []

    def _record_factory(*args, **kwargs):
        calls.append((args, dict(kwargs)))
        return factory(*args, **kwargs)

    def _legacy(*args, **kwargs):
        raise AssertionError("legacy adapter must not be built")

    monkeypatch.setattr(dcs._dx, "build_l2_fallback_adapter", _legacy)
    out2: dict = {}
    result = await svc._l2_write_answer(
        CHAT, "q", temperature=0.1,
        selection_texts=selection_texts,
        user_blocks=list(selection_texts),
        primary_budget_tokens=4000,
        primary_payload_tokens=4000,
        selection_budget_tokens=captured["selection_budget_tokens"],
        fallback_budget_tokens=None,
        fallback_selection_factory=_record_factory,
        time_line="TIME",
        out_prepared=out2)
    assert result is not None
    assert len(calls) == 1
    assert calls[0][1].get("mark_fallback") is False
    prepared = out2["primary"]
    assert prepared.budget["budget"] == 4000
    assert prepared.budget["payload_tokens"] > 0
    assert prepared.budget["policy_mode"] == "final_fit"
    sent = svc.llm.messages[-1]["content"]
    assert "<Initiative_Context" in sent
    assert "A" * 400 in sent
    assert "напомнить про релиз" in sent

    # F9: final-fit capacity prepared описывает PRIMARY бюджет и факт тела,
    # а не fallback/allocator-бюджет.
    out3: dict = {}
    result = await svc._l2_write_answer(
        CHAT, "q", temperature=0.1,
        selection_texts=selection_texts,
        user_blocks=list(selection_texts),
        primary_budget_tokens=100,
        primary_payload_tokens=100,
        selection_budget_tokens=1,
        fallback_budget_tokens=None,
        fallback_selection_factory=factory,
        time_line="TIME",
        out_prepared=out3)
    assert result is not None
    prepared = out3["primary"]
    assert prepared.budget["budget"] == 100
    assert prepared.budget["policy_mode"] == "fallback_capacity"
    assert prepared.budget["degraded"] is True
    assert prepared.budget["physical_overflow"] is True
    assert prepared.budget["capacity_limited"] is True
    assert prepared.budget["payload_tokens"] == count_tokens(
        svc.llm.messages[-1]["content"])
    assert "<Initiative_Context" in svc.llm.messages[-1]["content"]


# ── T6: final fit without fallback model, primary budget, extras kept ──────

@pytest.mark.asyncio
async def test_final_fit_without_fallback_model_uses_primary_budget():
    svc = _make_service(memory=FakeMemory(), llm=FakeLLM(text="answer"))
    calls: list = []

    def _factory(time_line=None, **kwargs):
        calls.append(dict(kwargs, time_line=time_line))

        def _adapt(incoming):
            prepared = dcs.PreparedTurnPayload(
                chat_id=CHAT, correlation_id="c", blocks=(),
                event_blocks=(), available_item_ids=frozenset(),
                window_messages=0,
                budget={"slot": "direct.primary", "budget": 90,
                        "policy_mode": "fallback_recompose",
                        "degraded": False},
                dropped=(), self_outputs=(), policy_version="p")
            return {
                "messages": [
                    {"role": "system", "content": "SYS"},
                    {"role": "user", "content": "FIT"},
                ]}, prepared
        return _adapt

    target = "<Target_User>\nT\n</Target_User>"
    current = "<Current_Question>\nC\n</Current_Question>"
    dig = "<dig_result>DIG</dig_result>"
    media = "<media_analysis>MEDIA</media_analysis>"
    voice = "<voice_transcripts>VOICE</voice_transcripts>"
    note = "[EVIDENCE] NOTE"
    user_blocks = [dig, target, media, voice, current, note]
    out: dict = {}
    result = await svc._l2_write_answer(
        CHAT, "q", temperature=0.1,
        selection_texts=(target, current),
        user_blocks=user_blocks,
        primary_budget_tokens=100,
        primary_payload_tokens=95,
        selection_budget_tokens=90,
        fallback_budget_tokens=None,
        fallback_selection_factory=_factory,
        history_assembly_block="HISTORY_BLOCK",
        out_prepared=out)

    assert result is not None
    assert len(calls) == 1
    assert calls[0]["mark_fallback"] is False
    assert calls[0]["selection_budget"] == 90
    assert calls[0]["extra_reserve"] > 0
    assert calls[0]["anchored"] == (
        ("<Target_User>", dig),
        ("<Current_Question>", media),
        ("<Current_Question>", voice),
        ("", note),
    )
    prepared = out["primary"]
    assert prepared.budget["budget"] == 100
    assert prepared.budget["selection_budget"] == max(
        1, 90 - calls[0]["extra_reserve"])
    assert prepared.budget["payload_tokens"] == count_tokens("FIT")
    assert prepared.budget["policy_mode"] == "final_fit"
    assert prepared.budget["final_fit"] is True
    assert svc.llm.messages[-1]["content"] == "FIT"


@pytest.mark.asyncio
async def test_final_fit_capacity_prepared_uses_primary_budget():
    """F9: capacity-prepared final fit не несёт fallback/allocator budget."""
    svc = _make_service(memory=FakeMemory(), llm=FakeLLM(text="answer"))
    calls: list = []

    def _factory(time_line=None, **kwargs):
        calls.append(dict(kwargs, time_line=time_line))

        def _adapt(incoming):
            prepared = dcs.PreparedTurnPayload(
                chat_id=CHAT, correlation_id="c", blocks=(),
                event_blocks=(), available_item_ids=frozenset(),
                window_messages=0,
                budget={"slot": "direct.primary", "budget": 400,
                        "selection_budget": 1,
                        "policy_mode": "fallback_capacity",
                        "degraded": True,
                        "physical_overflow": True,
                        "capacity_limited": True,
                        "payload_tokens": 142},
                dropped=(), self_outputs=(), policy_version="p")
            return {
                "messages": [
                    {"role": "system", "content": "SYS"},
                    {"role": "user", "content": "CAP"},
                ]}, prepared
        return _adapt

    out: dict = {}
    result = await svc._l2_write_answer(
        CHAT, "q", temperature=0.1,
        selection_texts=("SEL",),
        user_blocks=["SEL"],
        primary_budget_tokens=100,
        primary_payload_tokens=100,
        selection_budget_tokens=1,
        fallback_budget_tokens=400,
        fallback_selection_factory=_factory,
        plan_block="PLAN",
        out_prepared=out)
    assert result is not None
    assert len(calls) == 1
    prepared = out["primary"]
    assert prepared.budget["budget"] == 100
    assert prepared.budget["payload_tokens"] == count_tokens("CAP")
    assert prepared.budget["selection_budget"] == 1
    assert prepared.budget["policy_mode"] == "fallback_capacity"
    assert prepared.budget["degraded"] is True
    assert prepared.budget["physical_overflow"] is True
    assert prepared.budget["capacity_limited"] is True
    assert "final_fit" not in prepared.budget
    assert svc.llm.messages[-1]["content"] == "CAP"


# ── T7: success path — no legacy builder, no fallback allocation ───────────

@pytest.mark.asyncio
async def test_success_path_does_not_build_legacy_adapter(monkeypatch):
    svc = _live_service(monkeypatch, llm=FakeLLM("ok"))
    blocks, out, fb = await _build_live(svc)
    calls = {"budget": 0, "factory": 0}
    real_budget = comp.allocate_budget

    def _budget(*args, **kwargs):
        calls["budget"] += 1
        return real_budget(*args, **kwargs)

    def _factory(*args, **kwargs):
        calls["factory"] += 1
        raise AssertionError("factory must not run on success")

    def _legacy(*args, **kwargs):
        raise AssertionError("legacy adapter must not be built")

    monkeypatch.setattr(comp, "allocate_budget", _budget)
    monkeypatch.setattr(dcs._dx, "build_l2_fallback_adapter", _legacy)
    result = await svc._l2_write_answer(
        CHAT, "q", temperature=0.1,
        primary_prepared=out.get("primary"),
        selection_texts=fb["selection_texts"],
        user_blocks=blocks,
        primary_budget_tokens=fb["l2_input_budget"],
        selection_budget_tokens=fb["selection_budget"],
        fallback_budget_tokens=fb.get("l2_fallback_budget"),
        fallback_selection_factory=_factory,
        out_prepared={})
    assert result is not None
    assert calls == {"budget": 0, "factory": 0}


# ── T8: pressure 800/400, media+voice+dig+note order preserved ─────────────

@pytest.mark.asyncio
async def test_fallback_pressure_keeps_anchored_order(monkeypatch):
    llm = _AdapterLLM()
    svc = _live_service(monkeypatch, llm=llm, primary=1200, fallback=400)
    blocks, out, fb = await _build_live(svc)
    media = "<media_analysis>MEDIA_800_400</media_analysis>"
    voice = "<voice_transcripts>VOICE_800_400</voice_transcripts>"
    dig = "<dig_result>DIG_800_400</dig_result>"
    note = "[EVIDENCE] NOTE_800_400"
    user_blocks = _with_anchored_extras(
        blocks, media=media, voice=voice, dig=dig, note=note)
    result = await svc._l2_write_answer(
        CHAT, "q", temperature=0.1,
        selection_texts=fb["selection_texts"],
        user_blocks=user_blocks,
        primary_budget_tokens=10000,
        selection_budget_tokens=fb["selection_budget"],
        fallback_budget_tokens=fb.get("l2_fallback_budget"),
        fallback_selection_factory=fb["adapter_factory"],
        out_prepared={})
    assert result is not None
    assert llm.fallback_calls == 1
    body = _body(llm)
    for marker in (media, voice, dig, note):
        assert marker in body, marker
    assert body.index(dig) < body.index("<Target_User")
    assert body.index(media) < body.index(voice) < body.index("<Current_Question")
    assert body.index(note) > body.index("<Current_Question")
    prepared = llm.fallback_prepared
    assert prepared.budget["policy_mode"] in (
        "fallback_recompose", "fallback_capacity")
    assert prepared.budget["payload_tokens"] > 0
    if prepared.budget["policy_mode"] == "fallback_capacity":
        assert prepared.budget["degraded"] is True
        assert prepared.budget["physical_overflow"] is True


# ── T9: unknown/ambiguous insertion => no live recompose, legacy full parts ─

@pytest.mark.asyncio
async def test_unknown_insertion_falls_back_to_legacy_full_parts(monkeypatch):
    llm = _AdapterLLM()
    svc = _make_service(memory=FakeMemory(), db=FakeDB({}),
                        bot_id=BOT_UID, llm=llm)
    svc.llm._chat_model = "primary"
    svc.llm._fallback_model = "fb"
    svc.llm._base_url = ""
    svc.llm._fallback_base_url = ""
    legacy: list = []
    factory_calls: list = []
    real_legacy = dcs._dx.build_l2_fallback_adapter

    def _legacy(*args, **kwargs):
        legacy.append(dict(kwargs))
        return real_legacy(*args, **kwargs)

    def _factory(*args, **kwargs):
        factory_calls.append((args, kwargs))
        raise AssertionError("live factory must not run on ambiguous split")

    monkeypatch.setattr(dcs._dx, "build_l2_fallback_adapter", _legacy)
    result = await svc._l2_write_answer(
        CHAT, "q", temperature=0.1,
        selection_texts=("A", "B"),
        user_blocks=["B", "A"],
        primary_budget_tokens=10000,
        selection_budget_tokens=700,
        fallback_budget_tokens=20000,
        fallback_selection_factory=_factory,
        plan_block="PLAN",
        out_prepared={})
    assert result is not None
    assert factory_calls == []
    assert len(legacy) == 1
    body = _body(llm)
    assert "A" in body and "B" in body and "PLAN" in body


# ── T10: legacy plain truncation is visibly capacity-marked ────────────────

def test_legacy_plain_truncation_marks_capacity():
    from services import direct_execution as dx

    reasons: list = []
    adapter = dx.build_l2_fallback_adapter(
        system="S", parts=["P" * 4000, "Q" * 4000], evidence="",
        query="q", fallback_budget_tokens=250,
        on_capacity_reason=reasons.append)
    out = adapter({"messages": [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "old"}]})
    body = out["messages"][-1]["content"]
    assert "[CAPACITY]" in body
    assert "fallback_window_exceeded" in reasons
    assert "fallback_repacked" not in reasons


# ── T3/T4 retained: legacy adapter failure semantics ──────────────────────

def test_legacy_adapter_raises_on_invalid_input():
    from services import direct_execution as dx

    adapter = dx.build_l2_fallback_adapter(
        system="S", parts=["P"], evidence="", query="q",
        fallback_budget_tokens=1000)
    with pytest.raises(Exception):
        adapter(None)
