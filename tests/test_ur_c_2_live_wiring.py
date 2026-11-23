"""UR-C-2b: live ContextSelection wiring for direct L2.

Проверяет фактический live-путь `_build_user_content`:
  * один `build_context_selection` + один `allocate_selection`;
  * `allocate_budget` на success = 0 (только fail-open);
  * canonical memory leg с адресатом/reply-parent — один bounded read;
  * fact-row tuple и снятие семантического char-cap на active path;
  * fail-open только на исключении, с явным `degraded`;
  * part-aware current/reply-parent overflow.

Строки `UR-09.1/09.2/09.6/09.7/11.6/BAN-04` остаются PARTIAL до независимого
ревью; этот файл не заявляет VERIFIED.
"""
from types import SimpleNamespace

import pytest

import services.direct_chat_service as dcs
from services import direct_context_composer as comp
from services.token_counter import count_tokens
from tests.test_direct_chat import (
    FakeDB,
    FakeMemory,
    _make_service,
    _message,
)

pytestmark = [pytest.mark.asap3, pytest.mark.asap31, pytest.mark.asap32]

CHAT = -100777
BOT_UID = 999000


def _row(i: int, *, text: str = "") -> dict:
    return {
        "id": i, "tg_message_id": 500 + i, "user_id": 10,
        "author_name": "Вася", "text": text or f"строка {i}",
        "timestamp": 1_700_000_000 + i, "reply_to_id": None,
        "media_type": "text",
    }


def _service(*, window=None, rag_facts=None):
    return _make_service(
        memory=FakeMemory(window=list(window or ()),
                          rag_facts=rag_facts),
        db=FakeDB({}),
        bot_id=BOT_UID,
    )


@pytest.mark.asyncio
async def test_live_one_build_one_allocate_and_zero_block_allocator(
        monkeypatch):
    """UR-09.2: один selection и один allocator на payload."""
    window = [_row(i) for i in range(1, 5)]
    svc = _service(window=window)
    counts = {"build": 0, "select": 0, "budget": 0}
    real_build = comp.build_context_selection
    real_select = comp.allocate_selection
    real_budget = comp.allocate_budget

    def _build(*args, **kwargs):
        counts["build"] += 1
        return real_build(*args, **kwargs)

    def _select(*args, **kwargs):
        counts["select"] += 1
        return real_select(*args, **kwargs)

    def _budget(*args, **kwargs):
        counts["budget"] += 1
        return real_budget(*args, **kwargs)

    monkeypatch.setattr(comp, "build_context_selection", _build)
    monkeypatch.setattr(comp, "allocate_selection", _select)
    monkeypatch.setattr(comp, "allocate_budget", _budget)

    out: dict = {}
    blocks = await svc._build_user_content(
        CHAT, _message(text="вопрос"), "Вася", out_prepared=out)
    assert blocks
    assert counts == {"build": 1, "select": 1, "budget": 0}
    prepared = out["primary"]
    assert prepared.budget["selection_budget"] == max(
        0, prepared.budget["budget"] - prepared.budget["fixed_p0_tokens"])
    assert prepared.budget["fixed_p0_tokens"] > 0
    kinds = [b.get("kind") for b in prepared.event_blocks]
    assert "global_tail" in kinds and "current" in kinds
    assert prepared.event_blocks[-1].get("kind") == "current"


@pytest.mark.asyncio
async def test_memory_leg_uses_addressee_and_reply_parent_once(monkeypatch):
    """UR-09.1: memory request несёт адресата и reply-parent; один вызов."""
    msg = _message(text="что я говорил про кредит?", message_id=4242)
    msg.reply_to_message = SimpleNamespace(
        message_id=99, text="старый вопрос про кредит",
        from_user=SimpleNamespace(id=77))
    svc = _service()
    seen: dict = {}
    real = dcs._mca_rc.build_memory_request

    def _request(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    collect_calls = {"n": 0}
    real_collect = comp.collect_memory_fragments

    async def _collect(*args, **kwargs):
        collect_calls["n"] += 1
        return await real_collect(*args, **kwargs)

    monkeypatch.setattr(dcs._mca_rc, "build_memory_request", _request)
    monkeypatch.setattr(comp, "collect_memory_fragments", _collect)

    await svc._build_user_content(
        CHAT, msg, "Вася", target_user_id=10, out_prepared={})
    assert seen.get("addressee_uid") == 10
    assert seen.get("reply_parent_uid") == 77
    assert "кредит" in str(seen.get("reply_parent_text") or "")
    assert seen.get("trigger_ref") == 4242
    assert collect_calls["n"] == 1


@pytest.mark.asyncio
async def test_selection_mode_removes_rag_semantic_char_cap(
        monkeypatch, caplog):
    """UR-C-2b: graph_rag_context_max_chars — не владелец отсечки live-пути."""
    facts = [{
        "id": 1, "item_id": "fact:1", "origin": "chat_history",
        "fact": "длинный факт про кредит " * 80,
        "rag_ts": 1_700_000_000, "status": "confirmed",
        "subject_ref_id": 1, "speaker_author_id": 1,
    }]
    svc = _service(rag_facts=facts)

    async def _cpg(chat_id, key, default=None):
        if key == "limits.graph_rag_context_max_chars":
            return 80
        return default

    monkeypatch.setattr(dcs, "_cp_g", _cpg)
    legacy_out: dict = {}
    legacy, _ = await svc._build_rag_block(
        1, _message(text="кредит"), "", out_memory=legacy_out)
    caplog.clear()
    selected_out: dict = {}
    selected, _ = await svc._build_rag_block(
        1, _message(text="кредит"), "", out_memory=selected_out,
        selection_mode=True)
    assert legacy and selected
    assert len(selected) > len(legacy)
    assert "truncated to 80 chars" not in caplog.text
    rows = selected_out.get("rows") or []
    assert rows
    frag = comp.fragment_from_fact_row(rows[0])
    assert frag is not None and frag.memory_tier == 3


@pytest.mark.asyncio
async def test_selection_exception_falls_open_to_block_allocator(monkeypatch):
    """UR-C-2b: legacy allocator достижим ТОЛЬКО при исключении selection."""
    svc = _service(window=[_row(1), _row(2)])

    def _boom(*args, **kwargs):
        raise RuntimeError("selection down")

    calls = {"budget": 0}
    real_budget = comp.allocate_budget

    def _budget(*args, **kwargs):
        calls["budget"] += 1
        return real_budget(*args, **kwargs)

    monkeypatch.setattr(comp, "allocate_selection", _boom)
    monkeypatch.setattr(comp, "allocate_budget", _budget)
    out: dict = {}
    blocks = await svc._build_user_content(
        CHAT, _message(text="вопрос"), "Вася", out_prepared=out)
    assert blocks
    assert calls["budget"] >= 1
    prepared = out["primary"]
    assert prepared.budget["degraded"] is True
    assert prepared.budget["policy_mode"] == "legacy_fail_open"


@pytest.mark.asyncio
async def test_fallback_recompose_reuses_full_selection(monkeypatch):
    """UR-C-2b: fallback budget → тот же full selection, без retrieval."""
    svc = _service(window=[_row(1), _row(2)])
    svc.llm._chat_model = "primary"
    svc.llm._fallback_model = "fb"
    svc.llm._base_url = ""
    svc.llm._fallback_base_url = ""
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

    counts = {"build": 0, "select": 0, "budget": 0, "memory": 0}
    real_build = comp.build_context_selection
    real_select = comp.allocate_selection
    real_budget = comp.allocate_budget
    real_memory = dcs._mca_rc.build_memory_request

    def _build(*args, **kwargs):
        counts["build"] += 1
        return real_build(*args, **kwargs)

    def _select(*args, **kwargs):
        counts["select"] += 1
        return real_select(*args, **kwargs)

    def _legacy(*args, **kwargs):
        counts["budget"] += 1
        return real_budget(*args, **kwargs)

    def _memory(*args, **kwargs):
        counts["memory"] += 1
        return real_memory(*args, **kwargs)

    monkeypatch.setattr(dcs._model_capacity, "resolve_stage_window", _window)
    monkeypatch.setattr(dcs._auto_budget, "resolve_stage_budget", _budget)
    monkeypatch.setattr(comp, "build_context_selection", _build)
    monkeypatch.setattr(comp, "allocate_selection", _select)
    monkeypatch.setattr(comp, "allocate_budget", _legacy)
    monkeypatch.setattr(dcs._mca_rc, "build_memory_request", _memory)
    out: dict = {}
    fallback: dict = {}
    await svc._build_user_content(
        CHAT, _message(text="вопрос"), "Вася",
        out_prepared=out, out_fallback=fallback)
    assert counts["build"] == 1
    # primary allocation + fallback allocation на ТОЙ ЖЕ selection.
    assert counts["select"] == 1
    factory = fallback.get("adapter_factory")
    assert callable(factory)
    adapter = factory(None)
    adapted, prepared = adapter({
        "messages": [{"role": "system", "content": "sys"},
                     {"role": "user", "content": "old"}]})
    assert counts["select"] == 2
    assert counts["build"] == 1
    assert counts["memory"] == 1
    assert counts["budget"] == 0
    assert adapted["messages"][-1]["content"]
    assert prepared.budget["policy_mode"] == "fallback_recompose"
    assert prepared.budget["selection_budget"] < \
        out["primary"].budget["selection_budget"]


@pytest.mark.asyncio
async def test_history_supplement_is_allocated_and_traced(monkeypatch):
    """P0-HA supplement входит в selection и слот history_supplement."""
    svc = _service(window=[_row(1)])

    async def _episodes(*args, **kwargs):
        return "", {
            "count": 0, "messages": 0, "tokens": 0, "hits": 0,
            "spans": [], "rows": [],
            "supplement_lines": ["[вне выборки] старый факт"],
        }

    monkeypatch.setattr(svc, "_build_old_episodes", _episodes)
    out: dict = {}
    blocks = await svc._build_user_content(
        CHAT, _message(text="вопрос"), "Вася",
        history_sample={"sample_id": "hs_ab12cd34ef56"},
        out_prepared=out)
    supplement = [b for b in blocks if "ДОПОЛНЕНИЕ ВНЕ ВЫБОРКИ" in b]
    assert supplement and "старый факт" in supplement[0]
    kinds = [e.get("kind") for e in out["primary"].event_blocks]
    assert "history_supplement" in kinds


@pytest.mark.asyncio
async def test_fallback_failure_returns_capacity_not_primary(monkeypatch):
    """A2 §3.6: сбой fallback-рекомпоза → capacity-only, не primary as-is."""
    svc = _service(window=[_row(1), _row(2)])
    svc.llm._chat_model = "primary"
    svc.llm._fallback_model = "fb"
    svc.llm._base_url = ""
    svc.llm._fallback_base_url = ""
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

    calls = {"select": 0}
    real_select = comp.allocate_selection

    def _select(*args, **kwargs):
        calls["select"] += 1
        if calls["select"] > 1:
            raise RuntimeError("fallback allocation failed")
        return real_select(*args, **kwargs)

    monkeypatch.setattr(dcs._model_capacity, "resolve_stage_window", _window)
    monkeypatch.setattr(dcs._auto_budget, "resolve_stage_budget", _budget)
    monkeypatch.setattr(comp, "allocate_selection", _select)
    out: dict = {}
    fallback: dict = {}
    await svc._build_user_content(
        CHAT, _message(text="вопрос"), "Вася",
        out_prepared=out, out_fallback=fallback)
    adapter = fallback["adapter_factory"](None)
    adapted, prepared = adapter({
        "messages": [{"role": "system", "content": "SYS"},
                     {"role": "user", "content": "СТАРЫЙ КОНТЕКСТ"}]})
    user_text = adapted["messages"][-1]["content"]
    assert "СТАРЫЙ КОНТЕКСТ" not in user_text
    assert "<Current_Question>" in user_text
    assert prepared.budget["policy_mode"] == "fallback_capacity"
    assert prepared.budget["degraded"] is True
    assert prepared.budget["physical_overflow"] is True
    assert out.get("fallback_prepared") is prepared
    assert calls["select"] == 2


@pytest.mark.asyncio
async def test_fallback_double_failure_keeps_fixed_p0(monkeypatch):
    """R2-01: raw double-failure сохраняет fixed P0 и честный fixed-tokens."""
    svc = _service(window=[_row(1), _row(2)])
    svc.llm._chat_model = "primary"
    svc.llm._fallback_model = "fb"
    svc.llm._base_url = ""
    svc.llm._fallback_base_url = ""
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

    calls = {"select": 0, "materialize": 0}
    real_select = comp.allocate_selection
    real_mat = dcs._materialize_selection

    def _select(*args, **kwargs):
        calls["select"] += 1
        if calls["select"] > 1:
            raise RuntimeError("fallback allocation failed")
        return real_select(*args, **kwargs)

    def _mat(*args, **kwargs):
        calls["materialize"] += 1
        if calls["materialize"] > 1:
            raise RuntimeError("fallback materialize failed")
        return real_mat(*args, **kwargs)

    monkeypatch.setattr(dcs._model_capacity, "resolve_stage_window", _window)
    monkeypatch.setattr(dcs._auto_budget, "resolve_stage_budget", _budget)
    monkeypatch.setattr(comp, "allocate_selection", _select)
    monkeypatch.setattr(dcs, "_materialize_selection", _mat)
    out: dict = {}
    fallback: dict = {}
    await svc._build_user_content(
        CHAT, _message(text="вопрос"), "Вася",
        out_prepared=out, out_fallback=fallback)
    adapter = fallback["adapter_factory"](None)
    adapted, prepared = adapter({
        "messages": [{"role": "system", "content": "SYS"},
                     {"role": "user", "content": "СТАРЫЙ КОНТЕКСТ"}]})
    user_text = adapted["messages"][-1]["content"]
    assert "СТАРЫЙ КОНТЕКСТ" not in user_text
    assert "<Current_Question>" in user_text
    # fixed P0 не потерян в raw-пути
    assert "<UserResolutionMap>" in user_text
    assert "<Target_User>" in user_text
    assert "отвечай на последний вопрос" in user_text
    assert prepared.budget["policy_mode"] == "fallback_capacity"
    assert prepared.budget["degraded"] is True
    fixed_kinds = {"map", "target", "relations", "protected", "lore",
                   "correction", "nostalgia", "sandwich"}
    sent_fixed = sum(
        count_tokens(block.text) for block in prepared.blocks
        if block.kind in fixed_kinds)
    assert sent_fixed > 0
    assert prepared.budget["fixed_p0_tokens"] == sent_fixed
    assert calls["select"] == 2 and calls["materialize"] == 2


def test_trace_dropped_classifies_episode_and_rag():
    """R2-02: dropped trace не путает episode:* и fact/rag."""
    current = comp.ContextFragment(
        kind=comp.KIND_USER_STATEMENT, source_id="msg:current",
        text="вопрос", role=comp.ROLE_CURRENT_QUESTION)
    episode = comp.ContextFragment(
        kind=comp.KIND_SUMMARY_INFERENCE, source_id="episode:7",
        text="эпизод " * 20, role=comp.ROLE_MEMORY,
        authority=comp.AUTHORITY_BACKGROUND, memory_tier=4,
        timestamp_utc=100, time_known=True)
    rag = comp.ContextFragment(
        kind=comp.KIND_SUMMARY_INFERENCE, source_id="fact:9",
        text="факт " * 20, role=comp.ROLE_MEMORY,
        authority=comp.AUTHORITY_BACKGROUND, memory_tier=3,
        timestamp_utc=200, time_known=True)
    selection = comp.build_context_selection(
        current_text=current.text, timestamp_utc=1000,
        memory=[episode, rag],
        budget_tokens=current.tokens() + 1)
    dropped = {row["kind"]: row
               for row in dcs._trace_selection_dropped(selection)}
    assert {"episode", "rag"} <= set(dropped)
    assert dropped["episode"]["source_ids"] == ["episode:7"]
    assert dropped["episode"]["count"] == 1
    assert dropped["episode"]["tokens"] == episode.tokens()
    assert dropped["rag"]["source_ids"] == ["fact:9"]
    assert dropped["rag"]["count"] == 1
    assert dropped["rag"]["tokens"] == rag.tokens()


def test_materializer_keeps_current_and_reply_parent_overflow_parts():
    """UR-11.6: P0 overflow не теряет части current/reply-parent."""
    part1 = comp.ContextFragment(
        kind=comp.KIND_USER_STATEMENT, source_id="msg:current",
        text="НАЧАЛО вопроса", role=comp.ROLE_CURRENT_QUESTION)
    part2 = comp.ContextFragment(
        kind=comp.KIND_USER_STATEMENT, source_id="msg:current",
        text="КОНЕЦ вопроса", role=comp.ROLE_CURRENT_QUESTION,
        part_index=2, part_total=2)
    parent1 = comp.ContextFragment(
        kind=comp.KIND_USER_STATEMENT, source_id="msg:700",
        text="начало родителя", role=comp.ROLE_REPLY_PARENT)
    parent2 = comp.ContextFragment(
        kind=comp.KIND_USER_STATEMENT, source_id="msg:700",
        text=" конец родителя", role=comp.ROLE_REPLY_PARENT,
        part_index=2, part_total=2)
    selection = comp.ContextSelection(
        current_question=part1, current_parts=(part2,),
        reply_parent=parent1, reply_parent_parts=(parent2,))
    chain_item = SimpleNamespace(
        item_id="tg:700", text="начало родителя конец родителя",
        uid=10, name="Вася", is_bot=False, ts=1_700_000_000)
    blocks = dict(dcs._materialize_selection(
        selection,
        render_chain_line=lambda frag, item: item.text,
        render_row_line=lambda frag, source: "",
        source_index={"msg:700": chain_item}))
    assert "НАЧАЛО вопроса" in blocks["current"]
    assert "КОНЕЦ вопроса" in blocks["current"]
    assert "начало родителя конец родителя" in blocks["branch"]
    assert "начало родителя конец родителя" in blocks["thread"]
