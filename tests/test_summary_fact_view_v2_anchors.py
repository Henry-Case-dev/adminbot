"""FIND-2 fix (diag plans/features/asap-speech-arch/evidence/
summary-degraded-diag.md) — REGRESSION: v2 anchor-map FactView.

Дефект (прод-сигнатура 2.58.110/111, coverage=0.0 в 4/5 прогонов):
``build_fact_view_from_map`` читал только v1-поля карты (message_ids/
unassigned_message_ids), а anchor-mode валидатор канонизирует карту в v2
(source_anchors/unassigned_anchors) → пустой FactView помечался
ok/semantic/deliverable → EMPTY-GUARD пропускал → coverage-блок
перезаписывал честные writer_source-100% нулём. Связанное: прерванный
рестартом прогон логировал SUMMARY_COMPLETE status=ok при публикации «-».

Тесты (TEST-LIFECYCLE: REGRESSION owner=FIND-2/summary-factview):
  1. v2-карта + anchor_map → непустой FactView (fragments materialized,
     coverage 100%);
  2. v2-карта без anchor_map → fail-closed not_built (никогда ok+пусто);
  3. непустая карта без материализованных id → fail-closed not_built;
  4. coverage-гвард: пустой пакет НЕ перезаписывает writer_source-100%;
  5. offline-replay сигнатуры прогона 718e9ea6 (anchor_mode=true,
     WHOLE_WINDOW, writer_source) → coverage больше НЕ 0.0;
  6. прерванный отменой прогон → честный failed-терминал (interrupted),
     не SUMMARY_COMPLETE ok.
"""
import asyncio
import json
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
from services.summary_fact_view import build_fact_view_from_map
from services.summary_generator import SummaryGenerator
from services.summary_legacy_fullwindow import compute_package_coverage
from services.summary_l1_clusterizer import build_l1_payload
from services.summary_run_log import RunContext
from services.summary_source_anchors import build_anchor_map
from services.summary_source_window import SummarySourceWindow

pytestmark = pytest.mark.asap41

CHAT = -100718
RUN_ID = "run-718e9ea6"


@pytest.fixture(autouse=True)
def _review_on(monkeypatch):
    """Review-контур прод-дефолт ON (прецедент wave8 golden)."""
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L2_REVIEW_ENABLED",
                        True, raising=False)
    yield


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Чистая capacity-механика + обложка OFF (прецедент wave8 golden)."""
    import config.settings as cs
    import services.summary_generator as sg

    def _patch_all(name, value):
        targets = [type(cs.settings), type(sl1.settings), type(sg.settings)]
        extra = getattr(cs, "Settings", None)
        if extra is not None:
            targets.append(extra)
        for cls in {c for c in targets if c is not None}:
            if hasattr(cls, name):
                monkeypatch.setattr(cls, name, value, raising=False)

    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None
    _patch_all("SUMMARY_COVER_ARTICLE_ENABLED", False)
    _patch_all("SUMMARY_COVER_FALLBACK_ENABLED", False)
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None


def _rows(count, *, start_id=7300):
    return [{
        "id": start_id + i, "tg_message_id": start_id + i,
        "timestamp": 1_700_000_000 + i * 60, "user_id": 10 + (i % 2),
        "author_name": f"Автор{i % 2}", "text": f"сообщение про релиз {i}",
        "media_type": "text", "reply_to_id": None,
        "is_forward": 0, "forward_source": None} for i in range(count)]


def _window(rows, *, run_id=RUN_ID):
    messages = tuple(
        {"message_id": r["tg_message_id"], "db_id": r["id"],
         "timestamp": r["timestamp"], "text": r["text"]} for r in rows)
    return SummarySourceWindow(
        run_id=run_id, chat_id=CHAT,
        window_from=rows[0]["tg_message_id"] if rows else None,
        window_to=rows[-1]["tg_message_id"] if rows else None,
        messages=messages, messages_json="[]", created_at=0)


def _v2_map(anchor_map, rows, *, per_topic=3):
    """v2-карта (форма канонизатора): темы несут source_anchors."""
    anchors = list(anchor_map.source_anchors)
    topics = []
    for n in range(0, len(anchors), per_topic):
        topics.append({
            "topic_id": f"topic_{len(topics) + 1:03d}",
            "title": f"Тема {len(topics) + 1}",
            "source_anchors": anchors[n:n + per_topic],
            "participants": ["Автор0"], "short_hint": "обсуждение"})
    return {"schema_version": 2, "topics": topics, "events": [],
            "unassigned_anchors": []}


# ── 1. v2-карта + anchor_map → непустой FactView ───────────────────────────

def test_v2_anchor_map_materializes_nonempty_view():
    rows = _rows(6)
    am = build_anchor_map(_window(rows))
    assert am is not None
    items = build_l1_payload(rows, CHAT)
    view = build_fact_view_from_map(_v2_map(am, rows), items, chat_id=CHAT,
                                    anchor_map=am)
    assert view.status == "ok"
    assert view.deliverable
    assert len(view.package["threads"]) == 2
    frag_ids = sorted(f["message_id"] for t in view.package["threads"]
                      for f in t["fragments"])
    assert frag_ids == [r["tg_message_id"] for r in rows]
    cov = compute_package_coverage(view.package, len(rows))
    assert cov["coverage_percent"] == 100.0
    assert cov["source_messages_considered"] == len(rows)


def test_v2_map_unassigned_anchors_materialize():
    rows = _rows(6)
    am = build_anchor_map(_window(rows))
    items = build_l1_payload(rows, CHAT)
    anchors = list(am.source_anchors)
    v2map = {"schema_version": 2,
             "topics": [{"topic_id": "topic_001", "title": "Тема",
                         "source_anchors": anchors[:3],
                         "participants": [], "short_hint": ""}],
             "events": [],
             "unassigned_anchors": anchors[3:]}
    view = build_fact_view_from_map(v2map, items, chat_id=CHAT, anchor_map=am)
    assert view.deliverable
    assert view.package["unassigned_message_ids"] == \
        [r["tg_message_id"] for r in rows[3:]]
    cov = compute_package_coverage(view.package, len(rows))
    assert cov["coverage_percent"] == 100.0


# ── 2/3. fail-closed: пустой view никогда не «ok» ──────────────────────────

def test_v2_map_without_anchor_map_fails_closed():
    rows = _rows(6)
    am = build_anchor_map(_window(rows))
    items = build_l1_payload(rows, CHAT)
    view = build_fact_view_from_map(_v2_map(am, rows), items, chat_id=CHAT,
                                    anchor_map=None)
    assert view.status == "not_built"
    assert view.reason == "anchor_map_unavailable"
    assert not view.deliverable
    assert view.package is None


def test_zero_material_map_fails_closed_not_ok():
    rows = _rows(6)
    items = build_l1_payload(rows, CHAT)
    # v1-карта с id вне окна: раньше → «ok» с пустым пакетом (дефект).
    v1map = {"schema_version": 1,
             "topics": [{"topic_id": "topic_001", "title": "Т",
                         "message_ids": [999001, 999002],
                         "participants": [], "short_hint": ""}],
             "events": [], "unassigned_message_ids": []}
    view = build_fact_view_from_map(v1map, items, chat_id=CHAT)
    assert view.status == "not_built"
    assert view.reason == "no_materialized_ids"
    assert not view.deliverable


# ── 4. coverage-гвард: пустой пакет не перезаписывает writer_source-100 ────

def test_coverage_guard_keeps_writer_source_100_on_empty_package():
    from services.summary_generator import _apply_package_coverage
    ctx = RunContext(run_id="r1", chat_id=CHAT, mode="hybrid_l2")
    ctx.source_total = 5
    ctx.source_considered = 5
    ctx.source_coverage = 100.0
    empty_package = {"threads": [], "unassigned_message_ids": []}
    _apply_package_coverage(ctx, empty_package, 5, writer_source=True)
    assert ctx.source_coverage == 100.0
    assert ctx.source_considered == 5
    assert ctx.source_total == 5


def test_coverage_guard_overwrites_with_material():
    from services.summary_generator import _apply_package_coverage
    ctx = RunContext(run_id="r2", chat_id=CHAT, mode="hybrid_l2")
    ctx.source_total = 5
    ctx.source_considered = 5
    ctx.source_coverage = 100.0
    package = {"threads": [{"chronology": [{"message_id": 1}],
                            "fragments": [{"message_id": 1}],
                            "evidence_ids": [1],
                            "facts": []}],
               "unassigned_message_ids": []}
    _apply_package_coverage(ctx, package, 5, writer_source=True)
    assert ctx.source_coverage == 20.0
    assert ctx.source_considered == 1
    assert ctx.source_total == 5


# ── 5. offline-replay сигнатуры прогона 718e9ea6 (моки, 0 платных) ────────

def _writer_doc(payload_items):
    ids = [item["message_id"] for item in payload_items
           if isinstance(item.get("message_id"), int)]
    return json.dumps({
        "schema_version": 1, "title": "Релиз и деплой.",
        "paragraphs": [{
            "text": "Участники обсудили релиз и деплой.",
            "emphasis_spans": [], "evidence_message_ids": ids[:3]}],
    }, ensure_ascii=False)


def _review_approved():
    return json.dumps({"status": "approved", "findings": []},
                      ensure_ascii=False)


class _AnchorModeLLM:
    """Head-routing мок: L1 отвечает v2-картой в AnchorSpace (anchor_mode),
    Writer/Review — детерминированные ответы."""

    def __init__(self, anchor_map, rows, writer_doc):
        self.anchor_map = anchor_map
        self.rows = rows
        self.writer_doc = writer_doc
        self.calls = []

    async def generate(self, messages, **kw):
        head = messages[-1].get("content") or ""
        self.calls.append(head)
        if head.startswith("СООБЩЕНИЯ ЧАТА"):
            return json.dumps(_v2_map(self.anchor_map, self.rows),
                              ensure_ascii=False)
        if head.startswith("ИСТОЧНИК"):
            return self.writer_doc
        return _review_approved()


def _memory_mock(rows):
    memory = MagicMock()
    memory.db = object()
    memory.get_window_messages = AsyncMock(return_value=rows)
    memory.compress_and_purge = AsyncMock()
    memory.search_long_term = AsyncMock(return_value=[])
    memory.vector_search = AsyncMock(return_value=[])
    memory.get_graph_facts = AsyncMock(return_value=[])
    memory.get_rag_context = AsyncMock(return_value="")
    memory.memorize_facts = AsyncMock()
    return memory


def _events(monkeypatch):
    from services import pipeline_events as pe
    captured = []

    def fake_emit(event_name, **kwargs):
        captured.append((event_name, dict(kwargs)))

    monkeypatch.setattr(pe, "_emit", fake_emit)
    return captured


@pytest.mark.asyncio
async def test_replay_718e9ea6_anchor_mode_coverage_not_zero(monkeypatch):
    """Сигнатура FIND-2 (run 718e9ea6): anchor_mode=true, WHOLE_WINDOW,
    writer_source, v2-карта → coverage больше НЕ 0.0 (== 100.0 честно),
    RUN_DONE публикует ненулевой coverage."""
    # capacity-механика: WHOLE_WINDOW, 0 внешних вызовов.
    async def fake_resolve(base_url, model, slot=None):
        return types.SimpleNamespace(
            provider="test", model=model, base_url=base_url,
            source="runtime", confidence="estimated", fallback_used=False,
            effective_context_window=262144)

    monkeypatch.setattr(mc, "resolve_capacity", fake_resolve)

    async def _forced(system, slot):
        return ("tokens", 60000, "manual_cap")

    monkeypatch.setattr(sl1, "resolve_l1_effective_budget", _forced)

    rows = _rows(6)
    window = _window(rows)
    am = build_anchor_map(window)
    assert am is not None
    writer_doc = _writer_doc(build_l1_payload(rows, CHAT))
    llm = _AnchorModeLLM(am, rows, writer_doc)

    from services.summary_xml import XmlGroundingBuilder
    gen = SummaryGenerator(memory=_memory_mock(rows),
                           xml=XmlGroundingBuilder(), llm=llm, bot=None)
    gen._deliver_l2_plain = AsyncMock(return_value=True)
    gen._deliver_l2_rich = AsyncMock(return_value=True)
    events = _events(monkeypatch)

    ctx = RunContext(run_id=RUN_ID, chat_id=CHAT, mode="hybrid_l2",
                     manual=False)
    await gen._run_hybrid_l2(CHAT, rows, None, RUN_ID, ctx=ctx,
                             source_window=window)

    # L1 ответила РОВНО один раз в anchor-mode (v2-карта принята).
    l1_calls = [c for c in llm.calls if c.startswith("СООБЩЕНИЯ ЧАТА")]
    assert len(l1_calls) == 1
    # ГЛАВНОЕ: coverage честный, а не сигнатурный 0.0.
    assert ctx.source_coverage == 100.0
    assert ctx.source_considered == len(rows)
    assert ctx.source_total == len(rows)
    # Прогон дошёл до публикации.
    gen._deliver_l2_plain.assert_awaited_once()
    assert ctx.status == "ok"
    # Сигнатура диаг-прогона: L1 в anchor_mode (v2 AnchorSpace)…
    l1_stage = [kw for name, kw in events if name == "SUMMARY_L1_STAGE"]
    assert l1_stage and l1_stage[-1].get("counts", {}).get(
        "anchor_mode") is True
    # …пакет — semantic fact view (не fallback).
    assert ctx.package_grade == "semantic"


# ── 6. прерванный прогон → честный failed-терминал ─────────────────────────

@pytest.mark.asyncio
async def test_interrupted_run_marks_failed_not_ok(monkeypatch):
    """CancelledError (рестарт/шатдаун) → ctx failed (SUMMARY_FAILED
    reason=interrupted), а не SUMMARY_COMPLETE status=ok при публикации
    «-» (diag §1: «плановый рестарт убил процесс»)."""
    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(),
                           llm=MagicMock(), bot=None)
    gen._hybrid_l2_enabled = AsyncMock(return_value=True)
    gen.memory.compress_and_purge = AsyncMock()
    gen.memory.get_window_messages = AsyncMock(return_value=_rows(2))
    gen._establish_source_window = AsyncMock(return_value=None)
    gen._durable_run_create = AsyncMock()
    gen._durable_stage_result = AsyncMock()
    gen._durable_mark = AsyncMock()
    gen._durable_run_finish = AsyncMock()
    captured = {}

    async def _cancel(*args, **kwargs):
        captured["ctx"] = kwargs.get("ctx")
        raise asyncio.CancelledError()

    monkeypatch.setattr(gen, "_run_hybrid_l2", _cancel)
    monkeypatch.setattr("services.summary_generator.mca_gates"
                        ".summary_pregen_bounds_enabled", lambda: False)

    with pytest.raises(asyncio.CancelledError):
        await gen._run(CHAT, manual=False)

    ctx = captured["ctx"]
    assert ctx is not None
    assert ctx.status == "failed"
    assert ctx.reason == "interrupted"
    assert ctx.error_type == "CancelledError"


@pytest.mark.asyncio
async def test_published_run_cancel_keeps_ok_terminal(monkeypatch):
    """REV B-1 (инвариант INC-SUMMARY-01): опубликованный ран
    (publish_status=ok), отменённый ПОСЛЕ публикации, НЕ переписывается
    в SUMMARY_FAILED — терминал остаётся ok (не failed)."""
    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(),
                           llm=MagicMock(), bot=None)
    gen._hybrid_l2_enabled = AsyncMock(return_value=True)
    gen.memory.compress_and_purge = AsyncMock()
    gen.memory.get_window_messages = AsyncMock(return_value=_rows(2))
    gen._establish_source_window = AsyncMock(return_value=None)
    gen._durable_run_create = AsyncMock()
    gen._durable_stage_result = AsyncMock()
    gen._durable_mark = AsyncMock()
    gen._durable_run_finish = AsyncMock()
    captured = {}

    async def _publish_then_cancel(*args, **kwargs):
        ctx = kwargs.get("ctx")
        captured["ctx"] = ctx
        ctx.publish_status = "ok"       # публикация уже состоялась
        ctx.publish_channel = "rich"
        raise asyncio.CancelledError()  # отмена в хвосте (cover/дренаж)

    monkeypatch.setattr(gen, "_run_hybrid_l2", _publish_then_cancel)
    monkeypatch.setattr("services.summary_generator.mca_gates"
                        ".summary_pregen_bounds_enabled", lambda: False)

    with pytest.raises(asyncio.CancelledError):
        await gen._run(CHAT, manual=False)

    ctx = captured["ctx"]
    assert ctx is not None
    # Терминал НЕ переписан в failed: публикация была — статус остаётся ok.
    assert ctx.publish_status == "ok"
    assert ctx.status != "failed"
    assert ctx.reason != "interrupted"
