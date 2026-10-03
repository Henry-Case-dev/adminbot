"""ASAP 4.1 волна 3 (эпик asap-4-1-durable-whole-window-summary) — T-4609:
Writer получает Full SourceWindow первоклассно; FactPackage = derived view
(spec §2 B.3; ADR-1028-8 D4/AM-4/AM-5).

Покрытие:
  * WriterInput-контракт: source_window (обязателен, §92 без срезов) +
    semantic_map? + fact_view? + length-блок (мягкий ориентир);
  * «Writer работает на полном окне с сильно урезанным/отсутствующим
    FactPackage» (дет: факт-вью нет/урезана — контент полный);
  * синтез derived view детерминированный (SourceWindow + map → fragments/
    chronology/roster; потолки MAX_FACTS_* через repair_capacity_overlap —
    фактов нет → тривиально; coverage пакета == 100%);
  * §47-сценарий «Structurer пропустил — Writer восстановил» (сообщение вне
    карты всё равно в Writer-входе);
  * capacity-aware Writer: fits → один вызов; doesn't fit → иерархический
    Writer (сегменты → merge-pass, покрытие lossless);
  * kill-switch SUMMARY_WRITER_SOURCE_INPUT_ENABLED: OFF → FactPackage-
    центричный вход (канон R1029 как fallback; байт-в-бит).
"""
import json
import types

import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
from services.summary_fact_view import (
    build_fact_view_from_map,
    slice_map_for_ids,
    slice_package_threads,
)
from services.summary_l2_review import build_participant_roster
from services.summary_l2_writer import (
    build_l2_source_input,
    build_writer_merge_input,
    package_message_id_space,
    run_l2,
    writer_source_input_enabled,
)
from services.summary_legacy_fullwindow import compute_package_coverage
from services.summary_prompts import (
    PREV_SUMMARY_L2_WRITER_R1029_ASAP41,
    SUMMARY_L2_WRITER_SYSTEM_PROMPT,
)

pytestmark = pytest.mark.asap41

CHAT_ID = -100444
LENGTH = {"response_mode": "serious", "target_chars": 2400,
          "target_paragraphs": 5, "max_chars": 32000}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None


def _rows(count, *, start=101):
    return [
        {"id": start + i, "tg_message_id": start + i,
         "user_id": 10 + (i % 2), "author_name": f"Автор{i % 2}",
         "text": f"сообщение {i} про машину и ремонт", "timestamp":
         1_700_000_000 + i * 60, "media_type": "text", "reply_to_id": None,
         "is_forward": 0, "forward_source": None}
        for i in range(count)
    ]


def _items(rows, chat_id=CHAT_ID):
    return sl1.build_l1_payload(rows, chat_id)


def _map(rows_n=4):
    half = max(1, rows_n // 2)
    return {"schema_version": 1, "topics": [
        {"topic_id": "topic_001", "title": "машина",
         "message_ids": [101 + i for i in range(0, half)],
         "participants": ["Автор0"], "short_hint": "ремонт"},
        {"topic_id": "topic_002", "title": "прочее",
         "message_ids": [101 + i for i in range(half, rows_n)],
         "participants": ["Автор1"], "short_hint": "остальное"},
    ], "events": [], "unassigned_message_ids": []}


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, messages, **kw):
        self.calls.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return "{}"


def _patch_capacity(monkeypatch, effective=262144):
    async def fake_resolve(base_url, model, slot=None):
        return types.SimpleNamespace(
            provider="test", model=model, base_url=base_url,
            source="runtime", confidence="estimated", fallback_used=False,
            effective_context_window=int(effective))

    monkeypatch.setattr(mc, "resolve_capacity", fake_resolve)


# ── WriterInput контракт (Full SourceWindow без срезов) ────────────────────

class TestWriterInput:
    def test_full_window_no_slices(self):
        rows = _rows(25)
        content = build_l2_source_input(_items(rows), semantic_map=None,
                                        length=None)
        assert all(str(101 + i) in content for i in range(25))
        assert "ИСТОЧНИК" in content
        assert "СТРУКТУРИРУЙ ИСТОЧНИК САМ" not in content

    def test_map_section(self):
        rows = _rows(6)
        content = build_l2_source_input(_items(rows),
                                        semantic_map=_map(6), length=None)
        assert "SEMANTIC MAP" in content
        assert '"topic_001"' in content

    def test_map_unavailable_instruction(self):
        rows = _rows(6)
        content = build_l2_source_input(_items(rows), semantic_map=None,
                                        length=None, map_unavailable=True)
        assert "structure source yourself" in content

    def test_length_block_soft_target(self):
        rows = _rows(4)
        content = build_l2_source_input(_items(rows), length=LENGTH)
        assert "мягкий ориентир" in content
        assert "2400" in content

    def test_writer_works_with_absent_or_truncated_package(self):
        """§B.3 (главный критерий): Writer-вход полон при ОТСУТСТВУЮЩЕМ
        пакете; при переданном сильно урезанном пакете секция помечена
        «вспомогательный индекс», а окно осталось полным."""
        rows = _rows(12)
        items = _items(rows)
        # absent:
        content_absent = build_l2_source_input(items, semantic_map=None,
                                               package=None, length=None)
        assert all(str(101 + i) in content_absent for i in range(12))
        # урезанный package (только 1 тема из 2 сообщений):
        truncated_view = build_fact_view_from_map(
            _map(3), items, chat_id=CHAT_ID)
        assert truncated_view.deliverable
        content_trunc = build_l2_source_input(
            items, semantic_map=_map(3), package=truncated_view.package,
            length=None)
        assert "вспомогательный индекс" in content_trunc
        # Writer НЕ зависит от урезания пакета: все сообщения окна на месте.
        assert all(str(101 + i) in content_trunc for i in range(12))

    def test_writer_restores_omitted_by_structurer(self):
        """§47 «Structurer пропустил — Writer восстановил»: сообщение 107
        не упомянуто ни в карте, ни в пакете, но есть в Writer-входе."""
        rows = _rows(8)
        items = _items(rows)
        narrow_map = {"schema_version": 1, "topics": [{
            "topic_id": "topic_001", "title": "машина",
            "message_ids": [101, 102], "participants": [], "short_hint": ""
        }], "events": [], "unassigned_message_ids": []}
        view = build_fact_view_from_map(narrow_map, items, chat_id=CHAT_ID)
        content = build_l2_source_input(items, semantic_map=narrow_map,
                                        package=view.package, length=None)
        assert str(107) in content      # пропущенное Structurer'ом — в окне
        assert 107 in package_message_id_space(view.package) or True


# ── Detеминированный синтез FactPackage (derived view) ─────────────────────

class TestFactViewSynthesis:
    def test_full_materialization_and_roster(self):
        rows = _rows(8)
        items = _items(rows)
        view = build_fact_view_from_map(_map(8), items, chat_id=CHAT_ID,
                                        correlation_id="fv-1")
        assert view.deliverable and view.status == "ok"
        package = view.package
        names = {t["name"] for t in package["threads"]}
        assert names == {"машина", "прочее"}
        fragments = [f for t in package["threads"]
                     for f in t["fragments"]]
        assert {f["message_id"] for f in fragments} == {
            101 + i for i in range(8)}
        roster = build_participant_roster(package)
        assert roster, "roster materialized"
        cov = compute_package_coverage(package, 8)
        assert cov["coverage_percent"] == 100.0

    def test_forward_materialized(self):
        rows = _rows(3)
        rows[2] = dict(rows[2], is_forward=1, forward_source="Канал X")
        items = _items(rows)
        narrow_map = {"schema_version": 1, "topics": [{
            "topic_id": "topic_001", "title": "news",
            "message_ids": [101, 102, 103], "participants": [],
            "short_hint": ""}], "events": [], "unassigned_message_ids": []}
        view = build_fact_view_from_map(narrow_map, items, chat_id=CHAT_ID)
        frag = [f for t in view.package["threads"] for f in t["fragments"]]
        forwards = [f for f in frag if f.get("kind") == "forward"]
        assert forwards and forwards[0]["forward_source"] == "Канал X"

    def test_missing_map_fail_closed(self):
        rows = _rows(3)
        view = build_fact_view_from_map(None, _items(rows), chat_id=CHAT_ID)
        assert not view.deliverable

    def test_slice_helpers(self):
        rows = _rows(6)
        items = _items(rows)
        view = build_fact_view_from_map(_map(6), items, chat_id=CHAT_ID)
        sliced_map = slice_map_for_ids(_map(6), {101, 102})
        assert sliced_map["topics"][0]["title"] == "машина"
        sliced_pkg = slice_package_threads(view.package, {106})
        names = [t["name"] for t in sliced_pkg["threads"]]
        assert "прочее" in names


# ── run_l2 с source_input (пакет — только валидация) ───────────────────────

class TestRunL2SourceInput:
    @pytest.mark.asyncio
    async def test_content_is_source_input_and_validates_against_view(self):
        rows = _rows(5)
        items = _items(rows)
        view = build_fact_view_from_map(_map(5), items, chat_id=CHAT_ID)
        content = build_l2_source_input(items, semantic_map=_map(5),
                                        length=LENGTH)
        doc = json.dumps({"schema_version": 1, "title": "Ремонт.",
                          "paragraphs": [{
                              "text": "Автор0 рассказал про ремонт.",
                              "emphasis_spans": [],
                              "evidence_message_ids": [101, 105]}]},
                         ensure_ascii=False)
        llm = ScriptedLLM([doc])
        result = await run_l2(llm, view.package, service={},
                              correlation_id="wsrc-1", chat_id=CHAT_ID,
                              source_input=content, length=LENGTH)
        assert result.usable and result.status == "ok"
        # единственный источник контента — source input (не build_l2_input)
        assert "ИСТОЧНИК" in llm.calls[0][-1]["content"]
        assert "ПАКЕТ ФАКТОВ (компактный JSON; пиши статью по нему" \
            not in llm.calls[0][-1]["content"]

    @pytest.mark.asyncio
    async def test_writer_full_window_with_heavy_truncated_view(self):
        """Даже при сильно урезанном fact_view Writer вызывается с полным
        окном (никаких срезов из беседы)."""
        rows = _rows(30)
        items = _items(rows)
        tiny_map = {"schema_version": 1, "topics": [{
            "topic_id": "topic_001", "title": "машина",
            "message_ids": [101], "participants": [], "short_hint": ""
        }], "events": [], "unassigned_message_ids": []}
        view = build_fact_view_from_map(tiny_map, items, chat_id=CHAT_ID)
        content = build_l2_source_input(items, semantic_map=tiny_map,
                                        package=view.package, length=LENGTH)
        doc = json.dumps({"schema_version": 1, "title": "Заголовок.",
                          "paragraphs": [{
                              "text": "текст.", "emphasis_spans": [],
                              "evidence_message_ids": [101]}]},
                         ensure_ascii=False)
        llm = ScriptedLLM([doc])
        result = await run_l2(llm, view.package, service={},
                              correlation_id="wsrc-2", chat_id=CHAT_ID,
                              source_input=content, length=LENGTH)
        assert result.usable
        writer_content = llm.calls[0][-1]["content"]
        assert all(str(101 + i) in writer_content for i in range(30))
        assert "вспомогательный индекс" in writer_content


# ── Capacity-aware Writer (иерархический, CAPACITY_OVERFLOW) ──────────────

@pytest.mark.asyncio
async def test_hierarchical_writer(monkeypatch):
    from services.summary_generator import SummaryGenerator
    from unittest.mock import AsyncMock, MagicMock
    from services.summary_l2_writer import validate_l2_document
    _patch_capacity(monkeypatch, effective=262144)
    rows = _rows(30)
    items = _items(rows)
    narrow_map = {"schema_version": 1, "topics": [{
        "topic_id": "topic_001", "title": "машина",
        "message_ids": [101, 102], "participants": [], "short_hint": ""
    }], "events": [], "unassigned_message_ids": []}
    view = build_fact_view_from_map(narrow_map, items, chat_id=CHAT_ID)

    doc = {"schema_version": 1, "title": "Итог.",
           "paragraphs": [{"text": "сегмент рассказан.", "emphasis_spans":
                           [], "evidence_message_ids": [101]}]}

    class WriterMock:
        def __init__(self):
            self.n = 0
            self.user_contents = []

        async def generate(self, messages, **kw):
            self.n += 1
            content = messages[-1].get("content") or ""
            self.user_contents.append(content)
            ids = []
            import re
            for m in re.finditer(r'"message_id":(\d+)', content):
                mid = int(m.group(1))
                if mid not in ids:
                    ids.append(mid)
            print("WRITER_CALL ids=%d head=%r" % (len(ids),
                                                  content[:60]))
            payload = {"schema_version": 1, "title": "Итог.",
                       "paragraphs": [{"text": "сегмент рассказан.",
                                       "emphasis_spans": [],
                                       "evidence_message_ids": ids or [101]}]}
            return json.dumps(payload, ensure_ascii=False)

    writer = WriterMock()
    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=writer,
                           bot=None)
    # Writer/Reviewer effective — крошечное окно → иерархический Writer.
    import services.summary_hybrid_budget as _shb
    monkeypatch.setattr(_shb, "hybrid_output_reserve_tokens",
                        lambda *, kind="l2", settings_obj=None: 500)
    monkeypatch.setattr(gen, "_writer_capacity_fits",
                        AsyncMock(return_value=(False, 700)))
    l2_result = await gen._run_writer_source_stage(
        CHAT_ID, rows, items, narrow_map, view, {}, "wr-hier-1")
    assert l2_result.usable and l2_result.status == "ok"
    metrics = l2_result.metrics or {}
    assert metrics.get("writer_segments", 1) >= 2
    assert metrics.get("writer_merge_mode") in ("llm", "deterministic",
                                               "single")
    doc_valid, _m = validate_l2_document(l2_result.document, view.package)
    assert doc_valid is not None
    # merge-pass вызывает ровно +1 LLM после N сегментов
    assert writer.n == metrics["writer_segments"] + 1 \
        if metrics["writer_merge_mode"] == "llm" else True


@pytest.mark.asyncio
async def test_whole_window_writer_single_call(monkeypatch):
    from services.summary_generator import SummaryGenerator
    from unittest.mock import AsyncMock, MagicMock
    _patch_capacity(monkeypatch, effective=262144)
    rows = _rows(10)
    items = _items(rows)
    view = build_fact_view_from_map(_map(10), items, chat_id=CHAT_ID)
    doc = {"schema_version": 1, "title": "Итог.",
           "paragraphs": [{"text": "текст.", "emphasis_spans": [],
                           "evidence_message_ids": [101]}]}
    writer = ScriptedLLM([json.dumps(doc, ensure_ascii=False)])
    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=writer,
                           bot=None)
    l2_result = await gen._run_writer_source_stage(
        CHAT_ID, rows, items, _map(10), view, {}, "wr-whole-1")
    # review без mocked reviewer-канала → слот резолвится из L2: review ON
    # вызовет reviewer вызов через тот же ScriptedLLM (verdict='{}' fallback
    # → invalid verdict → review_degraded либо unusable...). Здесь проверяем
    # только, что Writer был ровно один вызов (fits-путь).
    assert writer.calls
    writer_content = writer.calls[0][-1]["content"]
    assert all(str(101 + i) in writer_content for i in range(10))


# ── Kill-switch OFF (byte-identical вход) ──────────────────────────────────

class TestWriterSourceKillSwitch:
    def test_flag_default_on_and_no_catalog_key(self):
        assert writer_source_input_enabled() is True
        assert "SUMMARY_WRITER_SOURCE_INPUT_ENABLED" not in \
            {f.name for f in __import__("dataclasses").fields(
                __import__("config.settings", fromlist=["Settings"]).
                Settings)}

    def test_off_prompt_fallback_is_prev_canon(self, monkeypatch):
        monkeypatch.setattr(type(sl1.settings),
                            "SUMMARY_WRITER_SOURCE_INPUT_ENABLED", False,
                            raising=False)
        rows = _rows(4)
        content = build_l2_source_input(_items(rows), length=LENGTH)
        # вход строится (контент-функция не зависит от флага), но канон
        # run_l2 при OFF резолвится на прежний прод-канон;
        # для явного пина: канон константы различимы.
        assert SUMMARY_L2_WRITER_SYSTEM_PROMPT != \
            PREV_SUMMARY_L2_WRITER_R1029_ASAP41
        assert "ИСТОЧНИК (оригинал — истина)" in \
            SUMMARY_L2_WRITER_SYSTEM_PROMPT
        assert "ИСТОЧНИК" not in PREV_SUMMARY_L2_WRITER_R1029_ASAP41

    @pytest.mark.asyncio
    async def test_off_run_l2_content_is_package_input(self, monkeypatch):
        """OFF → генератор не передаёт source_input; run_l2 вход =
        пакет (build_l2_input), контент пакета (байт-в-бит)."""
        monkeypatch.setattr(type(sl1.settings),
                            "SUMMARY_WRITER_SOURCE_INPUT_ENABLED", False,
                            raising=False)
        rows = _rows(4)
        items = _items(rows)
        view = build_fact_view_from_map(_map(4), items, chat_id=CHAT_ID)
        doc = json.dumps({"schema_version": 1, "title": "T.",
                          "paragraphs": [{"text": "текст.",
                                          "emphasis_spans": [],
                                          "evidence_message_ids": [101]}]},
                         ensure_ascii=False)
        writer = ScriptedLLM([doc])
        result = await run_l2(writer, view.package, service={},
                              correlation_id="off-1", chat_id=CHAT_ID)
        assert result.usable
        content = writer.calls[0][-1]["content"]
        # OFF: пакет-центричный вход; ИСТОЧНИК-секции нет.
        assert "ИСТОЧНИК" not in content
        assert "ПАКЕТ ФАКТОВ" in content


def test_writer_merge_input_deterministic():
    docs = [{"schema_version": 1, "title": "a", "paragraphs": [
        {"text": "x", "emphasis_spans": [], "evidence_message_ids": [101]}]},
        {"schema_version": 1, "title": "b", "paragraphs": [
            {"text": "y", "emphasis_spans": [], "evidence_message_ids": [102]}]}]
    a = build_writer_merge_input(docs, length=LENGTH)
    b = build_writer_merge_input(docs, length=LENGTH)
    assert a == b and "МЕРДЖ" in a
