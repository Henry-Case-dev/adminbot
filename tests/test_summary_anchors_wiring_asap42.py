"""ASAP 4.2 Step 2b — targeted + local integration: anchor-space wiring.

Покрытие (задачи T-4804..T-4807, T-4829 §50):
  * L1 `run_l1` в AnchorSpace: SourceAnchorMap из immutable SummarySourceWindow;
    bad anchor → local repair (НЕ invalid); unassigned считает код; raw id не
    уходит в LLM-вход; OFF-kill-switch → v1/message_ids;
  * correction-retry policy: broken-anchor-only → НЕ retry; invalid_json/
    structural → retry с reason валидатора;
  * L2 Writer: evidence = source_anchors; invalid ref удаляется, абзац живёт;
  * L2 Reviewer: anchor-вердикт (validate_review_result) + targeted revision
    одного абзаца (bounded);
  * §50 integration: synthetic SourceWindow 1000+ WHOLE_WINDOW c 1 bad L1
    anchor + 1 bad L2 evidence → Hybrid выживает, Legacy НЕ используется.
"""
from __future__ import annotations

import json
import types

import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
from services.summary_l2_writer import L2Slot
from services.summary_source_anchors import build_anchor_map
from services.summary_source_window import build_source_window

pytestmark = pytest.mark.asap41

CHAT_ID = -100777

_ANCHOR_FLAGS = (
    "SUMMARY_SOURCE_ANCHORS_ENABLED",
    "SUMMARY_L1_ANCHOR_REPAIR_ENABLED",
    "SUMMARY_L2_EVIDENCE_REPAIR_ENABLED",
    "SUMMARY_L2_TARGETED_REVISION_ENABLED",
)
_ZONE_A_FLAGS = (
    "SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED",
    "SUMMARY_WHOLE_WINDOW_FIRST_ENABLED",
    "SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED",
    "SUMMARY_L1_SEMANTIC_MAP_ENABLED",
    "SUMMARY_WRITER_SOURCE_INPUT_ENABLED",
    "SUMMARY_COVERAGE_CHUNKING_ENABLED",
    "SUMMARY_L1_CAPACITY_GUARD_ENABLED",
    "AUTO_BUDGET_RESOLVER_ENABLED",
    "MODEL_CAPACITY_RESOLVER_ENABLED",
    "SUMMARY_L2_REVIEW_ENABLED",
    "SUMMARY_REVISION_PATCH_ENABLED",
)


def _flag(monkeypatch, name, value):
    """Патч флага на всех Settings-классах (прецедент wave D)."""
    import config.settings as _cs
    import services.summary_generator as _gen
    import services.summary_l1_clusterizer as _sl1
    import services.summary_l2_review as _rev
    import services.summary_l2_writer as _wr
    from config.settings import Settings
    classes = {Settings, type(_cs.settings), type(_sl1.settings),
               type(_rev.settings), type(_wr.settings), type(_gen.settings)}
    for _cls in classes:
        monkeypatch.setattr(_cls, name, value, raising=False)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    for name in _ZONE_A_FLAGS:
        _flag(monkeypatch, name, True)
    for name in _ANCHOR_FLAGS:
        _flag(monkeypatch, name, True)
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()


def _slot(monkeypatch):
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_BASE_URL", "",
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_MODEL_NAME", "",
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "LLM_BASE_URL",
                        "http://127.0.0.1:8080/v1", raising=False)
    monkeypatch.setattr(type(sl1.settings), "LLM_MODEL_NAME", "large-model",
                        raising=False)


def _patch_capacity(monkeypatch, effective=262144):
    async def fake_resolve(base_url, model, slot=None):
        return types.SimpleNamespace(
            provider="test", model=model, base_url=base_url,
            source="runtime", confidence="estimated", fallback_used=False,
            effective_context_window=int(effective))
    monkeypatch.setattr(mc, "resolve_capacity", fake_resolve)


def _rows(count, *, start=101, text_size=16):
    return [
        {"id": start + i, "tg_message_id": start + i,
         "user_id": 10 + (i % 3), "author_name": f"Автор{i % 3}",
         "text": f"сообщение {i} " * (text_size // 4),
         "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
         "reply_to_id": None, "is_forward": 0, "forward_source": None}
        for i in range(count)
    ]


class ScriptedLLM:
    def __init__(self, responses, *, fallback="не json"):
        self.responses = list(responses)
        self.fallback = fallback
        self.calls: list = []

    async def generate(self, messages, **kw):
        self.calls.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return self.fallback

    @property
    def consumed(self) -> int:
        return len(self.calls)


def _window(run_id, rows):
    return build_source_window(run_id, CHAT_ID, rows)


def _anchors(window):
    am = build_anchor_map(window)
    return am, [e.anchor for e in am.entries]


def _v2_map(anchors_used, *, bad=None, events=None):
    used = list(anchors_used)
    if bad:
        used = used + [bad]
    return json.dumps({
        "schema_version": 2,
        "topics": [{"topic_id": "topic_001", "title": "тема",
                    "source_anchors": used, "participants": ["Автор0"],
                    "short_hint": "h"}],
        "events": events or [],
    }, ensure_ascii=False)


def _v1_map(ids):
    return json.dumps({
        "schema_version": 1,
        "topics": [{"topic_id": "topic_001", "title": "тема",
                    "message_ids": list(ids), "participants": ["Автор0"],
                    "short_hint": "h"}],
        "events": [], "unassigned_message_ids": [],
    }, ensure_ascii=False)


async def _run_l1(monkeypatch, llm, rows, window):
    _slot(monkeypatch)
    _patch_capacity(monkeypatch)
    return await sl1.run_l1(llm=llm, rows=rows, chat_id=CHAT_ID,
                            correlation_id="wire-run", source_window=window)


# ══ L1: anchor-space wiring ════════════════════════════════════════════════

class TestL1AnchorWiring:
    @pytest.mark.asyncio
    async def test_bad_anchor_repaired_not_invalid(self, monkeypatch):
        rows = _rows(5)
        window = _window("wire-l1-1", rows)
        am, anchors = _anchors(window)
        llm = ScriptedLLM([_v2_map([anchors[0], anchors[1]],
                                   bad="mZZZZ-99")])
        result = await _run_l1(monkeypatch, llm, rows, window)
        assert result.usable and result.status == "ok"
        assert result.payload["schema_version"] == 2
        serialized = json.dumps(result.payload)
        assert "mZZZZ-99" not in serialized
        assert result.payload["topics"][0]["source_anchors"] == anchors[:2]
        # unassigned посчитан КОДОМ (5 - 2 упомянутых).
        assert len(result.payload["unassigned_anchors"]) == 3
        assert result.map_stats["anchors_repaired"] == 1
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_raw_ids_absent_from_llm_input(self, monkeypatch):
        rows = _rows(3)
        window = _window("wire-l1-2", rows)
        am, anchors = _anchors(window)
        llm = ScriptedLLM([_v2_map([anchors[0]])])
        await _run_l1(monkeypatch, llm, rows, window)
        user = llm.calls[0][-1]["content"]
        assert anchors[0] in user
        # реальные TG id не подаются модели как reference-контракт.
        assert '"message_id"' not in user

    @pytest.mark.asyncio
    async def test_broken_anchor_only_no_retry(self, monkeypatch):
        rows = _rows(4)
        window = _window("wire-l1-3", rows)
        am, anchors = _anchors(window)
        # bad anchor + structural-invalid topic отсутствует → usable, retry нет.
        llm = ScriptedLLM([_v2_map([anchors[0]], bad="mABCD-99")])
        result = await _run_l1(monkeypatch, llm, rows, window)
        assert result.usable
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_invalid_json_triggers_correction_with_reason(
            self, monkeypatch):
        rows = _rows(4)
        window = _window("wire-l1-4", rows)
        am, anchors = _anchors(window)
        llm = ScriptedLLM(["не json", _v2_map([anchors[0]])])
        result = await _run_l1(monkeypatch, llm, rows, window)
        assert result.usable and len(llm.calls) == 2
        correction = llm.calls[1][-1]["content"]
        assert "semantic map v2" in correction
        assert "invalid_json" in correction

    @pytest.mark.asyncio
    async def test_fabricated_anchor_not_silently_accepted(self,
                                                           monkeypatch):
        rows = _rows(4)
        window = _window("wire-l1-5", rows)
        am, anchors = _anchors(window)
        # fabricate anchor for ordinal 1 с заведомо неверным checksum →
        # не становится валидным (не alias на другое сообщение).
        wrong = "m0001-ZZ" if anchors[1] != "m0001-ZZ" else "m0001-YY"
        llm = ScriptedLLM([_v2_map([anchors[0], wrong])])
        result = await _run_l1(monkeypatch, llm, rows, window)
        assert result.usable
        serialized = json.dumps(result.payload)
        assert wrong not in serialized
        assert result.payload["topics"][0]["source_anchors"] == [anchors[0]]
        assert result.map_stats["anchors_repaired"] == 1

    @pytest.mark.asyncio
    async def test_kill_switch_off_keeps_v1(self, monkeypatch):
        _flag(monkeypatch, "SUMMARY_SOURCE_ANCHORS_ENABLED", False)
        rows = _rows(4)
        window = _window("wire-l1-6", rows)
        llm = ScriptedLLM([_v1_map([101, 102, 103, 104])])
        result = await _run_l1(monkeypatch, llm, rows, window)
        assert result.usable
        assert result.payload["schema_version"] == 1
        assert result.payload["topics"][0]["message_ids"] == [101, 102, 103, 104]

    @pytest.mark.asyncio
    async def test_no_source_window_keeps_v1(self, monkeypatch):
        rows = _rows(4)
        _slot(monkeypatch)
        _patch_capacity(monkeypatch)
        llm = ScriptedLLM([_v1_map([101, 102, 103, 104])])
        result = await sl1.run_l1(llm=llm, rows=rows, chat_id=CHAT_ID,
                                  correlation_id="wire-l1-7")
        assert result.usable
        assert result.payload["schema_version"] == 1
        assert result.payload["topics"][0]["message_ids"] == [101, 102, 103, 104]


# ══ L2: Writer evidence + Reviewer targeted revision ═══════════════════════
def _package():
    return {
        "schema_version": 2, "status": "ok",
        "threads": [{"thread_id": "t", "name": "T", "description": "",
                     "chronology": [], "facts": [], "fragments": []}],
        "service": {"response_mode": "serious", "cover_prompt": ""},
        "unassigned_message_ids": [],
    }


class _Writer:
    def __init__(self, document):
        self.document = document

    async def __call__(self, messages):
        return json.dumps(self.document, ensure_ascii=False)


class _Seq:
    def __init__(self, seq):
        self.seq = list(seq)

    async def __call__(self, messages):
        return self.seq.pop(0) if len(self.seq) > 1 else self.seq[0]


@pytest.mark.asyncio
async def test_l2_writer_anchor_repair_keeps_paragraph():
    from services.summary_l2_writer import run_l2
    rows = _rows(4)
    window = _window("wire-l2-1", rows)
    am, anchors = _anchors(window)
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": [anchors[0], "mZZZZ-99"]},
        {"text": "P1.", "source_anchors": [anchors[1]]}]}
    slot = L2Slot("http://x", "m", "k", False)
    res = await run_l2(None, _package(), slot=slot, llm_call=_Writer(doc),
                       anchor_map=am)
    assert res.usable
    assert res.document["paragraphs"][0]["source_anchors"] == [anchors[0]]
    assert res.document["paragraphs"][0]["text"] == "P0."
    assert res.metrics["invalid_refs_repaired"] == 1
    assert res.metrics["evidence_anchor_space"] == 1


@pytest.mark.asyncio
async def test_l2_review_invalid_anchor_does_not_kill_document():
    from services.summary_l2_review import run_l2_with_review
    rows = _rows(3)
    window = _window("wire-l2-2", rows)
    am, anchors = _anchors(window)
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": [anchors[0]]}]}
    slot = L2Slot("http://x", "m", "k", False)
    reviewer = _Seq([json.dumps({"status": "approved", "issues": []},
                                ensure_ascii=False)])
    res = await run_l2_with_review(
        None, _package(), slot=slot, reviewer_slot=slot,
        correlation_id="wire-l2-2", chat_id=CHAT_ID, llm_call=_Writer(doc),
        reviewer_call=reviewer, revision_call=_Seq([]), anchor_map=am)
    assert res.usable
    assert res.metrics["l2_legacy_after_review"] == 0
    assert res.metrics["l2_review_calls"] == 1


@pytest.mark.asyncio
async def test_l2_targeted_revision_single_paragraph():
    from services.summary_l2_review import run_l2_with_review
    rows = _rows(4)
    window = _window("wire-l2-3", rows)
    am, anchors = _anchors(window)
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": [anchors[0]]},
        {"text": "P1.", "source_anchors": [anchors[1]]}]}
    slot = L2Slot("http://x", "m", "k", False)
    reviewer = _Seq([
        json.dumps({"status": "needs_fixes", "issues": [
            {"paragraph_id": 0, "reason": "bad_quote",
             "source_anchors": [anchors[0]],
             "repair_instruction": "fix quote"}]}, ensure_ascii=False),
        json.dumps({"status": "approved", "issues": []},
                   ensure_ascii=False)])
    revision = _Writer({"text": "P0 fixed.", "source_anchors": [anchors[2]]})
    res = await run_l2_with_review(
        None, _package(), slot=slot, reviewer_slot=slot,
        correlation_id="wire-l2-3", chat_id=CHAT_ID, llm_call=_Writer(doc),
        reviewer_call=reviewer, revision_call=revision, anchor_map=am)
    assert res.usable
    assert res.metrics["l2_revision_count"] == 1
    assert res.metrics["l2_final_approved"] == 1
    assert res.metrics["l2_legacy_after_review"] == 0
    # правка коснулась ТОЛЬКО проблемного абзаца.
    assert res.document["paragraphs"][0]["text"] == "P0 fixed."
    assert res.document["paragraphs"][1]["text"] == "P1."


@pytest.mark.asyncio
async def test_l2_all_invalid_anchors_keep_paragraphs_signal():
    """Все evidence anchors битые → абзацы сохранены (reviewer signal), НЕ
    document=None/Legacy; paragraphs_without_evidence > 0."""
    from services.summary_l2_writer import run_l2
    rows = _rows(3)
    window = _window("wire-l2-4", rows)
    am, anchors = _anchors(window)
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": ["mZZZZ-99"]},
        {"text": "P1.", "source_anchors": ["not-an-anchor"]}]}
    slot = L2Slot("http://x", "m", "k", False)
    res = await run_l2(None, _package(), slot=slot, llm_call=_Writer(doc),
                       anchor_map=am)
    assert res.usable
    assert len(res.document["paragraphs"]) == 2
    assert res.metrics["invalid_refs_repaired"] == 2
    assert res.metrics["paragraphs_without_evidence"] == 2


@pytest.mark.asyncio
async def test_l1_anchor_system_canon_selected(monkeypatch):
    rows = _rows(3)
    window = _window("wire-l1-8", rows)
    am, anchors = _anchors(window)
    llm = ScriptedLLM([_v2_map([anchors[0]])])
    await _run_l1(monkeypatch, llm, rows, window)
    system = llm.calls[0][0]["content"]
    assert "source_anchor" in system
    assert "schema_version" in system and '"schema_version": 2' in system


# ══ §50 local integration ══════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_integration_1000_window_hybrid_survives(monkeypatch):
    """Synthetic SourceWindow 1000+ WHOLE_WINDOW: 1 bad L1 anchor + 1 bad L2
    evidence → L1 usable/repaired, Writer usable, Reviewer completed,
    Legacy NOT used."""
    from services.summary_l2_review import run_l2_with_review
    rows = _rows(1001)
    window = _window("integ-50", rows)
    assert window.source_message_count >= 1000
    am, anchors = _anchors(window)

    # L1: WHOLE_WINDOW, 1 битый anchor среди валидных.
    l1_llm = ScriptedLLM([_v2_map([anchors[0], anchors[1]], bad="mZZZZ-99",
                                  events=[{"kind": "k",
                                           "source_anchors": [anchors[2]]}])])
    l1 = await _run_l1(monkeypatch, l1_llm, rows, window)
    assert l1.usable, l1.invalid_reason
    assert l1.payload["schema_version"] == 2
    assert "mZZZZ-99" not in json.dumps(l1.payload)
    assert l1.map_stats["anchors_repaired"] == 1

    # L2: Writer с 1 битым evidence anchor, Reviewer — completed.
    doc = {"schema_version": 1, "title": "Большая статья", "paragraphs": [
        {"text": "Абзац 0.", "source_anchors": [anchors[0], "mZZZZ-99"]},
        {"text": "Абзац 1.", "source_anchors": [anchors[1]]}]}
    slot = L2Slot("http://x", "m", "k", False)
    reviewer = _Seq([json.dumps({"status": "approved", "issues": []},
                                ensure_ascii=False)])
    l2 = await run_l2_with_review(
        None, _package(), slot=slot, reviewer_slot=slot,
        correlation_id="integ-50", chat_id=CHAT_ID, llm_call=_Writer(doc),
        reviewer_call=reviewer, revision_call=_Seq([]), anchor_map=am)
    assert l2.usable
    assert l2.document["paragraphs"][0]["text"] == "Абзац 0."
    assert l2.document["paragraphs"][0]["source_anchors"] == [anchors[0]]
    assert l2.metrics["l2_review_calls"] >= 1
    assert l2.metrics["l2_legacy_after_review"] == 0


# ══ Generator wiring helpers ═══════════════════════════════════════════════

def test_map_is_anchor_space_detection():
    from services.summary_generator import _map_is_anchor_space
    assert _map_is_anchor_space(None) is True
    assert _map_is_anchor_space({"schema_version": 2, "topics": []}) is True
    assert _map_is_anchor_space({"topics": [
        {"source_anchors": ["m0000-A1"]}]}) is True
    assert _map_is_anchor_space({"schema_version": 1, "topics": [
        {"message_ids": [1]}]}) is False


def test_resolve_anchor_map_uses_window_identity():
    from services.summary_l1_clusterizer import resolve_anchor_map
    rows = _rows(3)
    window = _window("wire-identity", rows)
    first = resolve_anchor_map(window)
    second = resolve_anchor_map(window)
    assert first is not None
    assert first.entries == second.entries
    # anchors, выпущенные тем же кодом для того же окна, валидны.
    assert all(first.validate(a).ok for a in first.source_anchors)
    # другой run_id (другое окно) → другой fingerprint/anchors (не alias).
    other = _window("wire-other", rows)
    other_map = build_anchor_map(other)
    assert other_map.run_fingerprint != first.run_fingerprint

