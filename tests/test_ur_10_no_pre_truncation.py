"""UR-10 proof: no pre-truncation on live L1/L2 paths.

Строки UR-10/10.0/10.2/10.5 остаются PENDING до независимого ревью.
"""
from types import SimpleNamespace

import inspect

import pytest

import services.direct_chat_service as dcs
import services.auto_budget as ab_module
from services import direct_l1 as l1
from services.token_counter import count_tokens
from tests.test_direct_chat import FakeLLM, FakeMemory, _make_service, _message
from tests.test_ur_turn_engine import (
    CHAT, _patch_fixed_tool_flags, _plan, _run_direct, _svc,
)

pytestmark = [pytest.mark.asap3, pytest.mark.asap31, pytest.mark.asap32]


def _row(index: int, text: str, *, reply_to=None) -> dict:
    return {
        "id": index, "tg_message_id": 500 + index, "user_id": 10,
        "author_name": "Вася", "text": text, "timestamp": 100 + index,
        "media_type": "text", "reply_to_id": reply_to,
    }


def _large_l1(monkeypatch):
    async def _budget(**kwargs):
        return 100_000, {
            "effective_limit": 100_000, "source": "model_window",
            "capacity_source": "model_map", "context_window": 131_072,
            "model": "l1-test", "window_confidence": "verified",
            "window_estimated": False, "available_input_budget": 100_000,
        }

    monkeypatch.setattr(dcs._l1, "resolve_l1_context_budget", _budget)


def _l1_payload(llm) -> str:
    calls = [c for c in getattr(llm, "calls", [])
             if str((c.get("kwargs") or {}).get("step") or "")
             == "l1_planner"]
    assert calls, "L1 planner call not found"
    return "".join(str(m.get("content") or "")
                   for m in (calls[-1].get("messages") or ()))


def _window(count: int, *, long: bool = False):
    rows = []
    for i in range(1, count + 1):
        text = f"строка-{i}"
        if long:
            text += " " + ("ДЛИННЫЙ_ХВОСТ_" + str(i) + " " + "Z" * 450)
        rows.append(_row(i, text))
    return rows


def _long_question(size: int = 4200) -> str:
    return "ВОПРОС_НАЧАЛО " + ("Q" * (size - 40)) + " ВОПРОС_ХВОСТ"


# ── UR-10: live L1 >20 rows and long lines are not pre-cut by 20/200 ───────

@pytest.mark.asyncio
async def test_live_l1_keeps_all_rows_and_long_lines(monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    _large_l1(monkeypatch)
    rows = _window(26, long=True)
    service = _svc(_plan(), window=rows)
    _plan_out, meta = await _run_direct(service, text="вопрос")

    assert meta["l1_window_rows_raw"] == 26
    assert meta["l1_window_rows_selected"] == 26, meta
    assert meta["l1_line_chars_cap"] == 0
    payload = _l1_payload(service.llm)
    for i in range(1, 27):
        assert f"строка-{i}" in payload, i
    # Полный длинный хвост каждой строки, а не 200-символьный срез.
    for i in range(1, 27):
        assert f"ДЛИННЫЙ_ХВОСТ_{i}" in payload, i
    assert "Z" * 450 in payload
    assert "обрезано" not in payload.lower()


@pytest.mark.asyncio
async def test_live_l1_question_has_no_800_cap(monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    _large_l1(monkeypatch)
    question = _long_question(4200)
    service = _svc(_plan(), window=[])
    await _run_direct(service, text=question)
    payload = _l1_payload(service.llm)
    assert "ВОПРОС_НАЧАЛО" in payload
    assert "ВОПРОС_ХВОСТ" in payload
    assert question in payload


@pytest.mark.asyncio
async def test_legacy_l1_still_applies_20_and_200(monkeypatch):
    short_rows = _window(25)
    text_legacy = l1.build_l1_context(
        query="q", window=short_rows, budget_tokens=5000,
        preallocated=False, with_ids=True)
    # legacy: только последние L1_WINDOW_MESSAGES строк.
    assert "[msg:5]" not in text_legacy
    assert "[msg:6]" in text_legacy
    assert "[msg:25]" in text_legacy

    long_rows = _window(20, long=True)
    assert l1.L1_WINDOW_LINE_CHARS == 200
    assert l1.window_line_chars(
        long_rows, budget_tokens=1600) == l1.L1_WINDOW_LINE_CHARS
    lines = l1.render_window_lines(long_rows, 20, line_chars=None)
    joined = "\n".join(lines)
    assert "строка-20" in joined
    assert "Z" * 450 not in joined
    long_line = next(line for line in lines if "строка-20" in line)
    assert len(long_line) < 700, long_line[:300]

    text_active = l1.build_l1_context(
        query="q", window=short_rows, budget_tokens=100_000,
        preallocated=True, with_ids=True, line_chars=0)
    assert "[msg:1]" in text_active
    assert "[msg:25]" in text_active


# ── UR-10: direct L2 payload is built from selection, not the raw window ──

@pytest.mark.asyncio
async def test_direct_l2_payload_uses_full_selection(monkeypatch):
    rows = _window(26, long=True)
    svc = _make_service(memory=FakeMemory(window=rows), llm=FakeLLM("ok"))
    monkeypatch.setattr(dcs._model_capacity,
                        "capacity_resolver_enabled", lambda: True)
    monkeypatch.setattr(dcs._auto_budget,
                        "auto_budget_enabled", lambda: True)

    async def _resolve_window(base_url, model, slot=None):
        return 131_072, "model_map"

    async def _stage(stage, **kwargs):
        return SimpleNamespace(
            stage=stage, model="primary", context_window=131_072,
            mandatory_tokens=0, output_reserve=1024, safety_reserve=0,
            auto_input_budget=100_000, policy_mode="dynamic",
            manual_cap=None, effective_input_budget=100_000,
            source="model_map")

    monkeypatch.setattr(dcs._model_capacity, "resolve_stage_window",
                        _resolve_window)
    monkeypatch.setattr(dcs._auto_budget, "resolve_stage_budget", _stage)
    out: dict = {}
    fallback: dict = {}
    blocks = await svc._build_user_content(
        CHAT, _message("вопрос"), "Вася",
        out_prepared=out, out_fallback=fallback)
    joined = "\n".join(blocks)
    for i in range(1, 27):
        assert f"строка-{i}" in joined, i
        assert f"ДЛИННЫЙ_ХВОСТ_{i}" in joined, i
    assert fallback["selection_texts"] == tuple(blocks)
    assert fallback["selection_payload_tokens"] == sum(
        count_tokens(t) for t in blocks)


# ── UR-10.0: initiative render has no 12/200 or fixed 700 ─────────────────

@pytest.mark.asyncio
async def test_initiative_render_keeps_all_rows_without_12_cap(monkeypatch):
    _patch_fixed_tool_flags(monkeypatch)
    _large_l1(monkeypatch)
    rows = _window(24, long=True)
    service = _svc(_plan(), window=rows)

    async def _large_stage(stage, **kwargs):
        return SimpleNamespace(
            stage=stage, model="initiative-test", context_window=131_072,
            mandatory_tokens=0, output_reserve=100, safety_reserve=0,
            auto_input_budget=100_000, policy_mode="dynamic",
            manual_cap=None, effective_input_budget=100_000,
            source="model_map")

    monkeypatch.setattr(dcs._auto_budget, "resolve_stage_budget",
                        _large_stage)

    async def _persona(chat_id):
        return "PERSONA"

    async def _character(chat_id):
        return "", None

    async def _preflight(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "_initiative_persona_block", _persona)
    monkeypatch.setattr(service, "_initiative_character", _character)
    monkeypatch.setattr(service, "_evidence_preflight", _preflight)
    captured: dict = {}

    async def _writer(*args, **kwargs):
        captured.update(kwargs)
        return ("ok", "plain")

    monkeypatch.setattr(service, "_l2_write_answer", _writer)
    await service.generate_initiative_reply(
        CHAT, {"goal": "проверить окно", "kind": "follow_up",
               "origin": "observer"}, correlation_id="ur10-init")
    selection = tuple(captured.get("selection_texts") or ())
    assert selection
    window_text = selection[-1]
    for i in range(1, 25):
        assert f"строка-{i}" in window_text, i
    assert "Z" * 450 in window_text
    assert "max_tokens" not in captured or captured["max_tokens"] is None
    assert "700" not in str(captured.get("max_tokens"))
    assert "max_tokens=700" not in inspect.getsource(
        dcs.DirectChatService._l2_write_answer)
    assert "line_chars=0" in inspect.getsource(
        dcs.DirectChatService.generate_initiative_reply)


# ── UR-10.2: preallocated L1 full P0, markers, no second cut ──────────────

def test_preallocated_l1_keeps_full_p0_and_reply_id(monkeypatch):
    current = "ТЕКУЩИЙ " + ("C" * 3000)
    reply = "ЦИТАТА " + ("R" * 3000)
    rows = _window(6)
    rows[-1]["reply_to_id"] = 5
    clip_calls: list = []
    real_clip = l1.clip_body

    def _clip(text, cap):
        clip_calls.append((len(text), cap))
        return real_clip(text, cap)

    monkeypatch.setattr(l1, "clip_body", _clip)
    status: dict = {}
    budget = 20_000
    service = _make_service(memory=FakeMemory(), llm=FakeLLM())
    msg = _message("q", message_id=105)
    msg.reply_to_message = SimpleNamespace(
        message_id=99, text=reply,
        from_user=SimpleNamespace(id=77, first_name="Вася"))
    reply_block = service._l1_reply_block(
        msg, budget_tokens=budget, preserve=True)
    assert "[user:77]" in reply_block
    clip_calls.clear()
    text = l1.build_l1_context(
        query="q", current_question=current,
        reply_block=reply_block,
        window=rows, budget_tokens=budget, preallocated=True,
        with_ids=True, line_chars=0, trigger_message_id=105,
        reply_to_message_id=99, out_status=status)
    assert current in text
    assert reply in text
    assert "[user:77]" in text
    assert "(ответ на msg:5)" in text
    assert clip_calls == []
    assert status["window_preserved"] is True
    assert status["window_rows_raw"] == 6
    assert status["window_rows_selected"] == 6, status
    assert status["used_tokens"] <= budget
    assert status["overflow"] is False


# ── UR-10.5: dedicated L1 slot budget; fallback min; <= available ──────────

@pytest.mark.asyncio
async def test_l1_budget_uses_model_window_and_fallback_min(monkeypatch):
    main_budget = 8000
    fallback_window = 4000

    async def _stage(stage, **kwargs):
        return SimpleNamespace(
            stage=stage, model="l1-main", context_window=20_000,
            mandatory_tokens=0, output_reserve=1024, safety_reserve=0,
            auto_input_budget=10_000, policy_mode="dynamic",
            manual_cap=None, effective_input_budget=main_budget,
            source="model_map")

    monkeypatch.setattr(ab_module, "resolve_stage_budget", _stage)
    monkeypatch.setattr(dcs._model_capacity,
                        "fallback_window_for_model",
                        lambda model: (fallback_window, "model_map"))
    monkeypatch.setattr(dcs._l1, "_explicit_l1_context_cap",
                        lambda: None)
    base_budget, base_meta = await l1.resolve_l1_context_budget(
        base_url="", model="l1-main")
    assert base_budget == main_budget
    assert base_meta["source"] == "model_window"
    budget, meta = await l1.resolve_l1_context_budget(
        base_url="", model="l1-main", fallback_model="fb-small")
    assert budget == meta["effective_limit"]
    assert budget <= int(meta["available_input_budget"])
    assert budget < main_budget
    assert meta["source"] == "model_window_fallback"
    assert meta["fallback_model"] == "fb-small"

    # dedicated slot виден в meta/call-site
    async def _authorize(llm, chat_id):
        return "global"

    monkeypatch.setattr(dcs._l1, "authorize_l1_call", _authorize)
    monkeypatch.setattr(dcs._l1, "resolve_l1_model",
                        lambda chat_id=None: SimpleNamespace(
                            model="l1-main", base_url="", dedicated=True))

    def _hot_get(key, default=None):
        if key == "models.llm_model_name":
            return "fb-small"
        return default

    monkeypatch.setattr(dcs.hot, "get", _hot_get)
    service = _make_service(memory=FakeMemory(), llm=FakeLLM())
    slot_meta, _slot = await service._resolve_turn_slot_meta(
        CHAT, prompt_text="system")
    assert slot_meta.slot == "l1_slot"
    assert slot_meta.budget_tokens <= budget
    assert slot_meta.budget_tokens > 0
    assert slot_meta.budget_source == "model_window_fallback"
    assert slot_meta.fallback_model == "fb-small"
