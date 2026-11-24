"""UR-11a: L1 single budget, P0 guard, initiative line cap, legacy metadata.

Live L1 больше не вызывает `select_l1_window`/`allocate_budget`: fixed-секции
считаются один раз, окно получает `stage_budget - fixed`, выбирается
`allocate_selection` через composer-helper, `_cap_context` — guard без cut.
Строки UR-11.1/11.7/11.8 остаются PENDING до независимого ревью.
"""
import inspect
import sqlite3

import pytest

import services.direct_chat_service as dcs
from services import direct_context_composer as comp
from services import direct_l1 as l1
from services import param_catalog


def _row(index: int, text: str, *, reply_to=None) -> dict:
    return {
        "id": index, "tg_message_id": index, "user_id": 10,
        "author_name": "Вася", "text": text, "timestamp": 100 + index,
        "media_type": "text", "reply_to_id": reply_to,
    }


def _sqlite_window(count: int = 4):
    """Настоящие sqlite3.Row (не dict-фейк) — форма live MemoryManager."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE w (id INTEGER, tg_message_id INTEGER, user_id INTEGER,"
        " author_name TEXT, text TEXT, timestamp INTEGER, media_type TEXT,"
        " reply_to_id INTEGER)")
    for i in range(1, count + 1):
        conn.execute(
            "INSERT INTO w VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (i, 100 + i, 10, "Вася", f"row-{i}", 100 + i, "text", None))
    conn.commit()
    rows = conn.execute("SELECT * FROM w ORDER BY id").fetchall()
    return conn, rows



def _build(**kwargs):
    status: dict = {}
    kwargs.setdefault("preallocated", True)
    kwargs.setdefault("with_ids", True)
    kwargs.setdefault("out_status", status)
    kwargs.setdefault("line_chars", 0)
    text = l1.build_l1_context(**kwargs)
    return text, status


def _settings_caps(monkeypatch):
    pairs = {
        "CHAT_BUDGET_MAP_RATIO": 0.9, "CHAT_BUDGET_GLOBAL_RATIO": 0.9,
        "CHAT_BUDGET_THREAD_RATIO": 0.9, "CHAT_BUDGET_RAG_RATIO": 0.9,
        "CHAT_BUDGET_TARGET_RATIO": 0.9, "CHAT_BUDGET_BRANCH_RATIO": 0.9,
        "CHAT_GLOBAL_CONTEXT_MAX_CHARS": 500,
        "CHAT_GLOBAL_CONTEXT_MAX_TOKENS": 500,
        "CHAT_THREAD_MAX_CHARS": 500, "CHAT_THREAD_MAX_TOKENS": 500,
        "GRAPH_RAG_CONTEXT_MAX_CHARS": 500, "CHAT_LEVEL2_MAX_CHARS": 500,
    }
    real = l1.settings

    class _Proxy:
        def __getattr__(self, name):
            if name in pairs:
                return pairs[name]
            return getattr(real, name)

    monkeypatch.setattr(l1, "settings", _Proxy())
    return pairs


# ── UR-11.1 / T1: P0 full, window gets nothing, overflow explicit ───────────

def test_tight_budget_keeps_full_p0_and_reports_overflow(monkeypatch):
    current = "ТЕКУЩИЙ " + ("Q" * 5000)
    reply = "ОТВЕТ " + ("R" * 3000)
    rows = [_row(i, f"фон {i} " + ("B" * 300)) for i in range(1, 19)]
    rows.append(_row(19, reply))
    rows.append(_row(20, current, reply_to=19))
    clip_calls: list = []
    real_clip = l1.clip_body

    def _clip(text, cap):
        clip_calls.append((len(text), cap))
        return real_clip(text, cap)

    monkeypatch.setattr(l1, "clip_body", _clip)
    text, status = _build(
        query="q", current_question=current, reply_block=reply,
        window=rows, budget_tokens=1600,
        trigger_message_id=20, reply_to_message_id=19)
    assert current in text and reply in text
    assert clip_calls == []                  # guard_only не режет P0
    assert status["overflow"] is True
    assert status["used_tokens"] > status["budget_tokens"]
    assert status["fixed_tokens"] >= status["budget_tokens"]
    assert status["window_budget"] == 1
    assert status["window_rows_selected"] == 0
    assert status["window_rows_excluded_p0"] == 2
    assert status["overflow_sections"]
    assert any(item["section"] == "СООБЩЕНИЕ"
               for item in status["overflow_sections"])
    assert "[ПОСЛЕДНИЕ СООБЩЕНИЯ]" not in text


def test_p0_exclusion_uses_tg_message_id_not_db_pk():
    """UR11A-R1-B1: DB PK не является Telegram-id для trigger/reply."""
    foreign = _row(7, "чужая строка")
    foreign["tg_message_id"] = 999
    trigger = _row(1, "trigger строка")
    trigger["tg_message_id"] = 7
    assert l1._row_matches_message_id(foreign, 7) is False
    assert l1._row_matches_message_id(trigger, 7) is True
    text, status = _build(
        query="q", current_question="cur", window=[foreign, trigger],
        trigger_message_id=7, budget_tokens=10_000)
    assert status["window_rows_excluded_p0"] == 1
    assert status["window_rows_selected"] >= 1
    assert "чужая строка" in text


@pytest.mark.asyncio
async def test_live_window_rows_are_normalized_from_sqlite_row_direct(
        monkeypatch):
    """UR11A-R1-B2: Direct-L1 принимает реальные sqlite3.Row."""
    from tests.test_ur_turn_engine import (
        _patch_fixed_tool_flags, _plan as _ur_plan, _run_direct, _svc)

    _patch_fixed_tool_flags(monkeypatch)
    conn, rows = _sqlite_window(4)
    try:
        assert rows and not isinstance(rows[0], dict)
        service = _svc(_ur_plan(), window=rows)
        _plan_out, meta = await _run_direct(service)
        assert meta["l1_window_rows_raw"] == 4
        assert meta["l1_window_rows_selected"] >= 1
        lines = l1.render_window_lines(rows, 4, line_chars=0)
        assert len(lines) == 4
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_live_window_rows_are_normalized_from_sqlite_row_initiative(
        monkeypatch):
    """UR11A-R1-B2: Initiative-L1 принимает реальные sqlite3.Row."""
    from tests.test_ur_turn_engine import (
        _patch_fixed_tool_flags, _plan as _ur_plan, _run_initiative, _svc)

    _patch_fixed_tool_flags(monkeypatch)
    conn, rows = _sqlite_window(4)
    try:
        service = _svc(_ur_plan(), window=rows)
        captured: list = []
        real_build = l1.build_l1_context

        def _build_spy(**kwargs):
            status = kwargs.get("out_status")
            result = real_build(**kwargs)
            captured.append(status)
            return result

        monkeypatch.setattr(l1, "build_l1_context", _build_spy)
        await _run_initiative(service)
        assert captured
        status = captured[-1]
        assert status is not None
        assert status["window_rows_raw"] == 4
        assert status["window_rows_selected"] >= 1
    finally:
        conn.close()


# ── UR-11.1 / T2: window budget is net of fixed; P3 leaves before P1 ───────

def test_window_budget_is_stage_minus_fixed_and_p3_dropped_first(monkeypatch):
    rows = ([_row(i, "OLD " + ("O" * 300)) for i in range(1, 6)]
            + [_row(i, f"NEW-{i}") for i in range(6, 26)])
    base, base_status = _build(
        query="q", current_question="короткий вопрос", window=rows,
        budget_tokens=1_000_000)
    fixed = int(base_status["fixed_tokens"])
    from services.token_counter import count_tokens
    note_tokens = int(count_tokens(l1._render_l1_sections(
        [(l1.HISTORY_SCOPE_SECTION, l1.HISTORY_PARTIAL_LINE)])))
    budget = fixed + note_tokens + 400
    text, status = _build(
        query="q", current_question="короткий вопрос", window=rows,
        budget_tokens=budget)
    assert status["fixed_tokens"] == fixed + note_tokens
    assert status["window_budget"] <= budget - status["fixed_tokens"]
    assert status["fixed_tokens"] + status["window_render_overhead"] \
        + status["window_budget"] == budget
    assert status["window_rows_selected"] == 20
    assert status["overflow"] is False
    assert status["used_tokens"] <= budget
    assert "OLD" not in text
    assert "NEW-25" in text


def test_window_projection_drops_background_before_compressing_p1():
    rows = ([_row(i, "OLD " + ("O" * 500)) for i in range(1, 6)]
            + [_row(i, "NEW " + ("N" * 500)) for i in range(6, 11)])
    selected, allocation = comp.allocate_window_projection(
        rows, budget_tokens=500, fresh_count=5)
    texts = "\n".join(str(row.get("text") or "") for row in selected)
    assert "OLD" not in texts
    assert texts.count("NEW") == 5
    reasons = [item.get("reason_code")
               for item in allocation.provenance.dropped]
    assert reasons and reasons[0] == "irrelevant_background"
    assert "compressed" in reasons
    assert "budget_exceeded" not in reasons


def test_window_projection_excludes_fixed_p0_rows():
    rows = [_row(i, f"строка {i}") for i in range(1, 4)]
    selected, _ = comp.allocate_window_projection(
        rows, budget_tokens=10_000, p0_ids=(2,))
    ids = {row["id"] for row in selected}
    assert ids == {1, 3}


def test_live_l1_uses_selection_not_legacy_allocators(monkeypatch):
    calls = {"select": 0, "budget": 0, "selection": 0}
    real_select = l1.select_l1_window
    real_budget = comp.allocate_budget
    real_selection = comp.allocate_selection

    def _select(*args, **kwargs):
        calls["select"] += 1
        return real_select(*args, **kwargs)

    def _budget(*args, **kwargs):
        calls["budget"] += 1
        return real_budget(*args, **kwargs)

    def _selection(*args, **kwargs):
        calls["selection"] += 1
        return real_selection(*args, **kwargs)

    monkeypatch.setattr(l1, "select_l1_window", _select)
    monkeypatch.setattr(comp, "allocate_budget", _budget)
    monkeypatch.setattr(comp, "allocate_selection", _selection)
    _build(query="q", current_question="вопрос",
           window=[_row(i, f"строка {i}") for i in range(1, 6)],
           budget_tokens=10_000)
    assert calls["select"] == 0
    assert calls["budget"] == 0
    assert calls["selection"] >= 1


# ── T-guard: _cap_context(guard_only=True) не режет текст ──────────────────

def test_cap_context_guard_only_returns_text_unchanged(monkeypatch):
    payload = "СООБЩЕНИЕ " + ("X" * 5000)
    clip_calls = {"n": 0}
    real_clip = l1.clip_body

    def _clip(*args, **kwargs):
        clip_calls["n"] += 1
        return real_clip(*args, **kwargs)

    monkeypatch.setattr(l1, "clip_body", _clip)
    result = l1._cap_context(
        payload, sections_budget=[("СООБЩЕНИЕ", payload)], budget=10,
        guard_only=True)
    assert result == payload
    assert clip_calls["n"] == 0


# ── UR-11.8 / T4: initiative selected line is rendered without re-cap ──────

def test_initiative_writer_renders_full_line_with_zero_cap():
    row = _row(1, "A" * 400)
    lines = l1.render_window_lines(
        [row], 1, with_ids=True, line_chars=0)
    assert lines and "A" * 400 in lines[0]
    src = inspect.getsource(dcs.DirectChatService.generate_initiative_reply)
    assert "line_chars=0" in src


# ── UR-11.7/T5: legacy caps не меняют active L1 payload ────────────────────

def test_legacy_caps_do_not_change_active_l1_payload(monkeypatch):
    rows = [_row(i, f"реплика-{i} " + ("Y" * 100))
            for i in range(1, 11)]
    baseline, _ = _build(
        query="q", current_question="вопрос", window=rows,
        budget_tokens=50_000)
    _settings_caps(monkeypatch)
    changed, _ = _build(
        query="q", current_question="вопрос", window=rows,
        budget_tokens=50_000)
    assert changed == baseline
    # Значения не удалены и параметры по-прежнему существуют.
    assert l1.settings.CHAT_BUDGET_GLOBAL_RATIO == 0.9
    assert l1.settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS == 500


def test_effective_meta_marks_legacy_and_no_op():
    expectations = {
        "limits.chat_current_question_max_chars": "no_op",
        "limits.chat_budget_map_ratio": "legacy",
        "limits.chat_budget_global_ratio": "legacy",
        "limits.chat_budget_thread_ratio": "legacy",
        "limits.chat_budget_rag_ratio": "legacy",
        "limits.chat_budget_target_ratio": "legacy",
        "limits.chat_budget_branch_ratio": "legacy",
        "limits.chat_global_context_max_tokens": "legacy",
        "limits.chat_global_context_max_chars": "legacy",
        "limits.chat_thread_max_tokens": "legacy",
        "limits.chat_thread_max_chars": "legacy",
        "limits.graph_rag_context_max_chars": "legacy",
        "limits.chat_level2_max_chars": "legacy",
        # UR-21.18: доля — только fallback, когда предел вывода модели
        # неизвестен/resolver выключен; активная формула model-aware.
        "limits.chat_budget_reserve_ratio": "legacy",
    }
    for key, status in expectations.items():
        meta = param_catalog.effective_meta(key)
        assert meta["status"] == status, key
        if status in ("legacy", "no_op"):
            assert meta["reason_inactive"], key
    assert param_catalog.effective_meta(
        "limits.chat_context_budget_tokens")["status"] == "active"
    ratio_meta = param_catalog.effective_meta(
        "limits.chat_budget_reserve_ratio")
    assert ratio_meta["active_consumer"].startswith("services.auto_budget")
