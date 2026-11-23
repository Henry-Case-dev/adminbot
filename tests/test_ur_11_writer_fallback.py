"""UR-11b: Writer fallback, no primary-as-is, exact accounting, initiative L2.

Строки UR-11.4/UR-11 остаются PENDING до независимого ревью.
"""
import dataclasses
from types import SimpleNamespace

import pytest

from services import direct_chat_service as dcs
from services.llm_client import LLMClient, LLMError
from tests.test_direct_chat import (
    FakeLLM, FakeMemory, _make_service,
)

pytestmark = [pytest.mark.asap3, pytest.mark.asap31, pytest.mark.asap32]

CHAT = -100777


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


# ── Direct: same selection + writer extras in original order ────────────────

def _row(i: int, text: str) -> dict:
    return {
        "id": i, "tg_message_id": i, "user_id": 10,
        "author_name": "Вася", "text": text, "timestamp": 100 + i,
        "media_type": "text", "reply_to_id": None,
    }


def _force_capacity(monkeypatch, svc):
    monkeypatch.setattr(dcs._model_capacity,
                        "capacity_resolver_enabled", lambda: True)
    monkeypatch.setattr(dcs._auto_budget,
                        "auto_budget_enabled", lambda: True)

    async def _window(base_url, model, slot=None):
        return 20000, "runtime"

    async def _budget(slot, **kwargs):
        return SimpleNamespace(
            context_window=20000, source="runtime",
            auto_input_budget=15000, output_reserve=1000,
            effective_input_budget=(12000 if slot == "direct.primary"
                                    else 6000),
            policy_mode="dynamic")

    monkeypatch.setattr(dcs._model_capacity, "resolve_stage_window", _window)
    monkeypatch.setattr(dcs._auto_budget, "resolve_stage_budget", _budget)


@pytest.mark.asyncio
async def test_selection_fallback_keeps_writer_extras_order(monkeypatch):
    window = [_row(i, f"строка-{i}") for i in range(1, 5)]
    svc = _make_service(memory=FakeMemory(window=window), llm=FakeLLM(text="ok"))
    svc.llm._chat_model = "primary"
    svc.llm._fallback_model = "fb"
    svc.llm._base_url = ""
    svc.llm._fallback_base_url = ""
    _force_capacity(monkeypatch, svc)
    out: dict = {}
    fallback: dict = {}
    await svc._build_user_content(
        CHAT, _make_message("вопрос"), "Вася", out_prepared=out,
        out_fallback=fallback)
    factory = fallback.get("adapter_factory")
    assert callable(factory)
    assert fallback.get("selection_recompose") is True
    adapter = factory(
        "TIME", extra_prefix=("PLAN",), extra_suffix=("EVIDENCE",))
    adapted, prepared = adapter({
        "messages": [{"role": "system", "content": "SYS"},
                     {"role": "user", "content": "OLD"}]})
    user = adapted["messages"][-1]["content"]
    assert "OLD" not in user
    assert "TIME" in user and "PLAN" in user
    assert user.index("PLAN") < user.index("EVIDENCE")
    assert prepared.budget["policy_mode"] == "fallback_recompose"
    assert fallback.get("fallback_used") is not True


def _make_message(text: str, *, message_id: int = 100):
    from tests.test_direct_chat import _message
    return _message(text=text, message_id=message_id)


# ── Final fit: actual extras > estimate → one allocation, prepared updated ─

@pytest.mark.asyncio
async def test_final_fit_recomposes_once_and_updates_prepared():
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
                        "policy_mode": "fallback_recompose"},
                dropped=(), self_outputs=(), policy_version="p")
            adapted = {
                "messages": [
                    {"role": "system", "content": "SYS"},
                    {"role": "user", "content": "FIT"},
                ]}
            return adapted, prepared
        return _adapt

    primary = SimpleNamespace(
        budget={"budget": 100, "payload_tokens": 95},
        blocks=(dcs.PreparedBlock(kind="current", text="SEL"),))
    out: dict = {}
    result = await svc._l2_write_answer(
        CHAT, "q", temperature=0.1, primary_prepared=primary,
        selection_budget_tokens=90,
        fallback_budget_tokens=80,
        fallback_selection_factory=_factory,
        plan_block="ПЛАН " * 40, evidence="EVID " * 40,
        user_blocks=["SEL"],
        time_line="TIME", out_prepared=out)
    assert result is not None
    assert len(calls) == 1
    assert calls[0]["selection_budget"] == 90
    assert calls[0]["extra_reserve"] > 0
    assert calls[0]["mark_fallback"] is False
    assert "FIT" in svc.llm.messages[-1]["content"]
    assert out["primary"].budget["policy_mode"] == "final_fit"
    assert result.prepared.budget["policy_mode"] == "final_fit"


@pytest.mark.asyncio
async def test_final_fit_skips_inserted_user_blocks_without_loss():
    """Media/voice/dig/ev-note не входят в full_selection: final fit их
    не пересобирает и не теряет — остаётся исходный primary payload."""
    svc = _make_service(memory=FakeMemory(), llm=FakeLLM(text="answer"))
    calls: list = []

    def _factory(time_line=None, **kwargs):
        calls.append(dict(kwargs, time_line=time_line))
        raise AssertionError("final fit must not run")

    primary = SimpleNamespace(
        budget={"budget": 100, "payload_tokens": 95},
        blocks=(dcs.PreparedBlock(kind="current", text="SEL"),))
    out: dict = {}
    result = await svc._l2_write_answer(
        CHAT, "q", temperature=0.1, primary_prepared=primary,
        selection_budget_tokens=90, fallback_budget_tokens=80,
        fallback_selection_factory=_factory,
        plan_block="ПЛАН " * 40, evidence="EVID " * 40,
        user_blocks=["SEL", "<Voice_Evidence>\nфраза\n</Voice_Evidence>"],
        time_line="TIME", out_prepared=out)
    assert result is not None
    assert calls == []
    sent = svc.llm.messages[-1]["content"]
    assert "SEL" in sent
    assert "<Voice_Evidence>" in sent
    assert "primary" not in out


# ── Initiative L2: fallback same window, full line, capacity on failure ────

@pytest.mark.asyncio
async def test_initiative_fallback_keeps_context_and_full_window(monkeypatch):
    from tests.test_ur_turn_engine import (
        _patch_fixed_tool_flags, _plan as _ur_plan, _svc)

    _patch_fixed_tool_flags(monkeypatch)
    rows = [_row(1, "A" * 400), _row(2, "B" * 400)]
    svc = _svc(_ur_plan(), window=rows)
    svc.llm._chat_model = "primary"
    svc.llm._fallback_model = "fb"
    svc.llm._base_url = ""
    svc.llm._fallback_base_url = ""

    async def _budget(slot, **kwargs):
        return SimpleNamespace(
            effective_input_budget=(4000 if kwargs.get("model") == "primary"
                                    else 2000),
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

    captured: dict = {}

    async def _writer(*args, **kwargs):
        captured.update(kwargs)
        return ("ok", "plain")

    monkeypatch.setattr(svc, "_initiative_persona_block", _persona)
    monkeypatch.setattr(svc, "_initiative_character", _character)
    monkeypatch.setattr(svc, "_evidence_preflight", _preflight)
    monkeypatch.setattr(svc, "_l2_write_answer", _writer)
    await svc.generate_initiative_reply(
        CHAT, {"goal": "напомнить про релиз", "kind": "follow_up",
               "origin": "observer"}, correlation_id="c")
    factory = captured.get("fallback_selection_factory")
    assert callable(factory)
    adapter = factory(
        "TIME", extra_prefix=("PLAN",), extra_suffix=("EVIDENCE",))
    adapted, prepared = adapter({
        "messages": [{"role": "system", "content": "SYS"},
                     {"role": "user", "content": "OLD"}]})
    user = adapted["messages"][-1]["content"]
    assert "OLD" not in user
    assert "TIME" in user and "PLAN" in user and "EVIDENCE" in user
    assert "напомнить про релиз" in user
    assert "A" * 400 in user
    assert user.index("PLAN") < user.index("A" * 400) < user.index("EVIDENCE")
    assert prepared.budget["policy_mode"] in (
        "fallback_recompose", "fallback_capacity")
    cap_adapter = factory("TIME", selection_budget=1)
    _cap_adapted, cap_prepared = cap_adapter({
        "messages": [{"role": "system", "content": "SYS"},
                     {"role": "user", "content": "OLD"}]})
    assert cap_prepared.budget["policy_mode"] == "fallback_capacity"
    assert cap_prepared.budget["degraded"] is True
    assert cap_prepared.budget["physical_overflow"] is True


# ── Legacy adapter uses explicit parameters, no primary as-is ──────────────

def test_legacy_adapter_raises_on_invalid_input():
    from services import direct_execution as dx
    adapter = dx.build_l2_fallback_adapter(
        system="S", parts=["P"], evidence="", query="q",
        fallback_budget_tokens=1000)
    with pytest.raises(Exception):
        adapter(None)
