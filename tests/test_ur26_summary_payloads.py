"""UNIFIED-REPLY UR-26.5/UR-30.4 — payload-наблюдаемость стадий Summary.

Матрица payload'ов (UR-G blocked-note; строка UR-30.4/ACC-E4):

  * stage1 ``l1_plan`` (L1 clusterizer) и stage2 ``l2_writer`` — события
    в ``RunContext.stage_events`` с model/provider, finish-кодом, usage,
    chars, digest'ом сырого ответа и наличием ChatClock-блока;
  * reviewer/revision — вердикт и решение ревизии видимы кодами;
  * repair — детерминированный ремонт видим явным кодом решения
    (``repair_applied:N``), не молчаливым fallback'ом;
  * supervisor — остановка (stall/бюджет попыток) видна кодом события;
  * digest стадии соответствует ПОЛНОМУ доставленному тексту (связка с
    фиксом full-text ledger UR-23.4 — никаких молчаливых [:20000]);
  * в payload событий нет текстов чата (R17);
  * подсаб-итем (a): отложенный генератор (retry-once после дефер-паузы)
    несёт свежее answer_as_of_utc по правилу минуты ChatClock, окно
    источников (summary_window_end_utc) не пересобирается;
  * подсаб-итем (b): chunked-L1 overflow-путь эмитит l1_plan с теми же
    полями и честной пометкой сборки из чанков.

Все LLM-каналы инжектируются — 0 сетевых/платных вызовов.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-G (payload matrix UR-30.4)
"""
from __future__ import annotations

import json
import re

import pytest

from services.summary_l2_review import run_l2_with_review
from services.summary_l2_writer import L2Slot, run_l2
from services.summary_l1_clusterizer import run_l1
from services.summary_stage_events import document_plain_digest, text_digest

pytestmark = [pytest.mark.system2]

CHAT_A = 1001
CHAT_ID = -100777

_DIGEST_RE = re.compile(r"^[0-9a-f]{16}$")


class RunContextStub:
    """Минимальный носитель append-only stage_events (§50.54)."""

    def __init__(self):
        self.stage_events = []


# ── Фикстуры/фейки ──────────────────────────────────────────────────────────


class FakeCache:
    """chat_params-кэш с per-chat override пояса (как в test_ur_c_clock)."""

    def __init__(self, roots):
        self._roots = roots

    async def get_chat_params(self, chat_id):
        return self._roots.get(int(chat_id), {})

    async def get_chat_params_full(self, chat_id):
        return self._roots.get(int(chat_id), {}), "2026-11-05T10:00:00Z"


@pytest.fixture()
def tz_chat(monkeypatch):
    """Europe/Moscow для тестовых чатов; изоляция кэша chat_params."""
    import services.chat_params as chat_params
    roots = {CHAT_A: {"overrides": {"limits.chat_timezone":
                                    "Europe/Moscow"}},
             CHAT_ID: {"overrides": {"limits.chat_timezone":
                                     "Europe/Moscow"}}}
    chat_params._chat_params_cache = FakeCache(roots)
    yield
    chat_params._chat_params_cache = None


_L1_FLAGS = (
    "SUMMARY_SOURCE_ANCHORS_ENABLED",
    "SUMMARY_L1_ANCHOR_REPAIR_ENABLED",
    "SUMMARY_L1_SEMANTIC_MAP_ENABLED",
    "SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED",
    "SUMMARY_WHOLE_WINDOW_FIRST_ENABLED",
    "SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED",
    "SUMMARY_L1_CAPACITY_GUARD_ENABLED",
    "AUTO_BUDGET_RESOLVER_ENABLED",
    "MODEL_CAPACITY_RESOLVER_ENABLED",
)


@pytest.fixture()
def l1_anchor_env(monkeypatch):
    """Anchor-mode L1: флаги ON, capacity-резолв фейковый, слот из settings."""
    import types

    import config.settings as _cs
    import services.model_capacity as mc
    import services.summary_l1_clusterizer as sl1
    from config.settings import Settings

    def _flag(name, value):
        for cls in (Settings, type(_cs.settings), type(sl1.settings)):
            monkeypatch.setattr(cls, name, value, raising=False)

    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    for name in _L1_FLAGS:
        _flag(name, True)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_BASE_URL", "",
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_MODEL_NAME", "",
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "LLM_BASE_URL",
                        "http://127.0.0.1:8080/v1", raising=False)
    monkeypatch.setattr(type(sl1.settings), "LLM_MODEL_NAME", "large-model",
                        raising=False)

    async def fake_resolve(base_url, model, slot=None):
        return types.SimpleNamespace(
            provider="test", model=model, base_url=base_url,
            source="runtime", confidence="estimated", fallback_used=False,
            effective_context_window=262144)

    monkeypatch.setattr(mc, "resolve_capacity", fake_resolve)
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()


_REVIEW_FLAGS = (
    "SUMMARY_SOURCE_ANCHORS_ENABLED",
    "SUMMARY_L1_ANCHOR_REPAIR_ENABLED",
    "SUMMARY_L2_EVIDENCE_REPAIR_ENABLED",
    "SUMMARY_L2_TARGETED_REVISION_ENABLED",
    "SUMMARY_L2_REVIEW_ENABLED",
    "SUMMARY_REVISION_PATCH_ENABLED",
)


@pytest.fixture()
def review_env(monkeypatch):
    """Bounded-review ON (как в test_asap44): review/revision-каналы живут."""
    import config.settings as _cs
    import services.summary_l2_review as _rev
    import services.summary_l2_writer as _wr
    from config.settings import Settings
    for name in _REVIEW_FLAGS:
        for cls in (Settings, type(_cs.settings), type(_rev.settings),
                    type(_wr.settings)):
            monkeypatch.setattr(cls, name, True, raising=False)
    yield


class _Writer:
    """Writer-канал: всегда возвращает один и тот же документ-JSON."""

    def __init__(self, document):
        self.document = document
        self.calls = 0

    async def __call__(self, messages):
        self.calls += 1
        return json.dumps(self.document, ensure_ascii=False)


class _Seq:
    """Последовательные ответы канала; последний повторяется."""

    def __init__(self, seq):
        self.seq = list(seq)
        self.calls: list = []

    async def __call__(self, messages):
        self.calls.append(messages)
        if len(self.seq) > 1:
            return self.seq.pop(0)
        return self.seq[0]


def _package():
    """id-space пакета: {101, 102, 103} (как в test_asap8_f1)."""
    return {
        "schema_version": 2,
        "status": "ok",
        "threads": [{
            "thread_id": "thread_001",
            "name": "Погода и планы",
            "description": "Обсуждали дождь и поездку.",
            "chronology": [
                {"message_id": 101, "timestamp": 1000,
                 "topic_ids": ["thread_001"]},
                {"message_id": 102, "timestamp": 1001,
                 "topic_ids": ["thread_001"]},
            ],
            "facts": [
                {"text": "На улице шёл сильный дождь",
                 "evidence_message_ids": [101]},
            ],
            "evidence_ids": [101, 102],
            "fragments": [
                {"message_id": 101, "author_id": 7001,
                 "display_name": "Вася", "timestamp": 1000,
                 "reply_to_id": None, "text": "На улице шёл сильный дождь"},
                {"message_id": 102, "author_id": 7002,
                 "display_name": "Петя", "timestamp": 1001,
                 "reply_to_id": 101, "text": "Поездку решили перенести"},
            ],
        }],
        "unassigned_message_ids": [103],
        "service": {"response_mode": "serious", "cover_prompt": "rain"},
        "budget": {"kind": "tokens", "limit": 30000, "estimated": 42,
                   "fits": True},
    }


def _doc(paragraphs, title: str = "Дождливый день") -> dict:
    return {"schema_version": 1, "title": title, "paragraphs": paragraphs}


def _l1_rows():
    return [{"id": 1, "user_id": 10, "author_name": "вася",
             "text": "реплика один", "timestamp": 1000,
             "media_type": "text", "reply_to_id": None,
             "tg_message_id": 11},
            {"id": 2, "user_id": 11, "author_name": "петя",
             "text": "реплика два", "timestamp": 2000,
             "media_type": "text", "reply_to_id": 1,
             "tg_message_id": 12}]


def _event(stub, stage):
    return [e for e in stub.stage_events if e.get("stage") == stage]


# ── (a) нормальный прогон: stage1+stage2 с digest/usage, без текстов чата ──


class TestNormalRunStagePayloads:
    @pytest.mark.asyncio
    async def test_stage1_plan_event_payload_fields(self, tz_chat):
        rows = [
            {"id": 101 + i, "tg_message_id": 101 + i, "user_id": 10 + i,
             "author_name": f"Автор{i}", "text": f"сообщение {i} о погоде",
             "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
             "reply_to_id": None, "is_forward": 0, "forward_source": None}
            for i in range(5)
        ]
        plan_json = json.dumps({
            "schema_version": 2,
            "threads": [{"thread_id": "thread_001", "topic": "тема",
                         "message_ids": [101, 102],
                         "facts": [{"text": "факт",
                                    "evidence_message_ids": [101]}]}],
            "unassigned_message_ids": [103],
        }, ensure_ascii=False)

        async def _llm_call(messages):
            return plan_json, {"prompt_tokens": 321, "completion_tokens": 55}

        ctx = RunContextStub()
        result = await run_l1(rows=rows, chat_id=CHAT_ID,
                              llm_call=_llm_call,
                              budget=("chars", 20000),
                              correlation_id="ur26-s1", ctx=ctx)
        events = _event(ctx, "l1_plan")
        assert events, "l1_plan stage event обязан быть (mutation-красная зона)"
        ev = events[-1]
        assert result.status == "ok", result.invalid_reason
        assert ev["status"] == "ok"
        assert ev["finish_reason"] == "parsed"
        assert ev["usage"] == {"input_tokens": 321, "output_tokens": 55}
        assert ev["chars"] == len(plan_json)
        assert ev["text_digest"] == text_digest(plan_json)
        # ChatClock-блок был в исходящем payload'е L1-плана (phase=plan).
        assert ev["clock"]["clock_included"] is True
        assert ev["clock"]["phase"] == "plan"
        assert ev["clock"]["timezone"] == "Europe/Moscow"
        assert ev["model"]
        assert ev["provider"]
        assert ev["decision"] == "l1_ok"

    @pytest.mark.asyncio
    async def test_stage2_writer_event_payload_fields(self, tz_chat):
        ctx = RunContextStub()
        llm_call = _Writer(_doc([
            {"text": "Первый абзац про дождь.", "emphasis": None},
            {"text": "Второй абзац про поездку.", "emphasis": None},
        ]))
        result = await run_l2(None, _package(),
                              slot=L2Slot("http://x", "l2-model", "k", False),
                              correlation_id="ur26-s2", chat_id=CHAT_A,
                              llm_call=llm_call, ctx=ctx)
        assert result.usable, result.invalid_reason
        events = _event(ctx, "l2_writer")
        assert events, "l2_writer stage event обязан быть"
        ev = events[-1]
        assert ev["status"] == "ok"
        assert ev["finish_reason"] == "validated"
        assert isinstance(ev["usage"], dict)
        assert ev["usage"]["output_tokens"] is not None
        assert ev["chars"] > 0
        assert _DIGEST_RE.match(ev["text_digest"] or "")
        assert ev["clock"]["clock_included"] is True
        assert ev["clock"]["phase"] == "answer"
        assert ev["model"] == "l2-model"
        assert ev["provider"] == "x"
        assert ev["decision"] == "writer_ok"
        assert _DIGEST_RE.match(ev["document_digest"] or "")

    @pytest.mark.asyncio
    async def test_review_run_emits_writer_and_reviewer_events(
            self, tz_chat, review_env):
        """Полный bounded-review прогон: writer/reviewer события в одном ctx."""
        from services.summary_source_anchors import build_anchor_map
        from services.summary_source_window import build_source_window
        rows = [
            {"id": 101 + i, "tg_message_id": 101 + i, "user_id": 10 + i,
             "author_name": f"Автор{i}", "text": f"сообщение {i} о погоде",
             "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
             "reply_to_id": None, "is_forward": 0, "forward_source": None}
            for i in range(4)
        ]
        window = build_source_window("ur26-review", CHAT_ID, rows)
        am = build_anchor_map(window)
        anchors = [e.anchor for e in am.entries]
        doc = _doc([
            {"text": "P0.", "source_anchors": [anchors[0]]},
            {"text": "P1.", "source_anchors": [anchors[1]]},
        ])
        ctx = RunContextStub()
        res = await run_l2_with_review(
            None, _package(), slot=L2Slot("http://x", "m", "k", False),
            reviewer_slot=L2Slot("http://x", "m", "k", False),
            correlation_id="ur26-review", chat_id=CHAT_ID,
            llm_call=_Writer(doc), reviewer_call=_Seq([json.dumps(
                {"status": "approved", "issues": []}, ensure_ascii=False)]),
            anchor_map=am, ctx=ctx)
        assert res.usable
        writer_events = _event(ctx, "l2_writer")
        reviewer_events = _event(ctx, "l2_reviewer")
        assert writer_events and reviewer_events
        assert reviewer_events[-1]["decision"] == "verdict=approved"
        assert reviewer_events[-1]["clock"]["clock_included"] is True

    @pytest.mark.asyncio
    async def test_stage_events_carry_no_chat_text(self, tz_chat):
        """R17: в payload событий нет ни текстов чата, ни текстов статьи."""
        ctx = RunContextStub()
        article_text = "УникальныйТекстСтатьиКоторыйНеДолженУтечь"
        llm_call = _Writer(_doc([
            {"text": article_text, "emphasis": None},
            {"text": "Второй абзац про поездку.", "emphasis": None},
        ]))
        await run_l2(None, _package(),
                     slot=L2Slot("http://x", "l2-model", "k", False),
                     correlation_id="ur26-r17", chat_id=CHAT_A,
                     llm_call=llm_call, ctx=ctx)
        blob = json.dumps(ctx.stage_events, ensure_ascii=False)
        assert article_text not in blob
        assert "реплика один" not in blob
        assert "На улице шёл сильный дождь" not in blob


# ── (b) revision: решение видно кодом ───────────────────────────────────────


class TestRevisionDecisionCode:
    @pytest.mark.asyncio
    async def test_revision_emits_decision_code(self, tz_chat, review_env):
        from services.summary_source_anchors import build_anchor_map
        from services.summary_source_window import build_source_window
        rows = [
            {"id": 101 + i, "tg_message_id": 101 + i, "user_id": 10 + i,
             "author_name": f"Автор{i}", "text": f"сообщение {i} о погоде",
             "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
             "reply_to_id": None, "is_forward": 0, "forward_source": None}
            for i in range(4)
        ]
        window = build_source_window("ur26-rev", CHAT_ID, rows)
        am = build_anchor_map(window)
        anchors = [e.anchor for e in am.entries]
        doc = _doc([
            {"text": "P0.", "source_anchors": []},
            {"text": "P1.", "source_anchors": [anchors[1]]},
        ])
        reviewer = _Seq([
            json.dumps({"status": "needs_fixes", "issues": [
                {"paragraph_id": 0, "reason": "no_evidence",
                 "source_anchors": [anchors[0]],
                 "repair_instruction": "fix"}]},
                ensure_ascii=False),
            json.dumps({"status": "approved", "issues": []},
                       ensure_ascii=False),
        ])
        revision = _Seq([json.dumps(
            {"text": "P0 fixed.", "source_anchors": [anchors[2]]},
            ensure_ascii=False)])
        ctx = RunContextStub()
        res = await run_l2_with_review(
            None, _package(), slot=L2Slot("http://x", "m", "k", False),
            reviewer_slot=L2Slot("http://x", "m", "k", False),
            correlation_id="ur26-rev", chat_id=CHAT_ID,
            llm_call=_Writer(doc), reviewer_call=reviewer,
            revision_call=revision, anchor_map=am, ctx=ctx)
        assert res.usable
        assert res.metrics["l2_revision_count"] == 1
        revisions = _event(ctx, "revision")
        assert revisions, "revision stage event обязан быть"
        ev = revisions[-1]
        assert ev["decision"] == "revision_applied"
        assert ev["status"] == "ok"
        assert ev["finish_reason"] == "revision_applied"
        assert _DIGEST_RE.match(ev["text_digest"] or "")
        assert ev["clock"]["clock_included"] is True
        # Вердикт reviewer тоже кодом.
        reviewer_events = _event(ctx, "l2_reviewer")
        assert reviewer_events[0]["decision"] == "verdict=needs_fixes"


# ── (c) repair: детерминированный ремонт — явный код, не молчаливый ────────


class TestRepairDecisionCode:
    @pytest.mark.asyncio
    async def test_deterministic_repair_visible_as_code(self, tz_chat):
        """S1-дефект (абзац 900+): repair_document делит абзац; решение
        repair_applied:N обязано быть в событии (silent-мутация красная)."""
        ctx = RunContextStub()
        sentence = "В чате обсудили погоду, планы на выходные и поездку. "
        long_text = (sentence * 18).strip()          # ~952 символа
        llm_call = _Writer(_doc([{"text": long_text, "emphasis": None}]))
        result = await run_l2(None, _package(),
                              slot=L2Slot("http://x", "l2-model", "k", False),
                              correlation_id="ur26-rep", chat_id=CHAT_A,
                              llm_call=llm_call, ctx=ctx)
        assert result.usable, result.invalid_reason
        assert int(result.metrics.get("repairs_applied") or 0) > 0
        repairs = _event(ctx, "repair")
        assert repairs, "repair stage event обязан быть"
        ev = repairs[-1]
        assert ev["status"] == "ok"
        assert ev["decision"].startswith("repair_applied:")
        assert ev["finish_reason"] == "deterministic"
        assert ev["output_count"] >= 2

    @pytest.mark.asyncio
    async def test_no_repair_needed_is_explicit_code(self, tz_chat):
        """Чистый документ: repair-стадия отчитывается repair_not_needed."""
        ctx = RunContextStub()
        llm_call = _Writer(_doc([
            {"text": "Первый абзац про дождь.", "emphasis": None},
            {"text": "Второй абзац про поездку.", "emphasis": None},
        ]))
        result = await run_l2(None, _package(),
                              slot=L2Slot("http://x", "l2-model", "k", False),
                              correlation_id="ur26-rep0", chat_id=CHAT_A,
                              llm_call=llm_call, ctx=ctx)
        assert result.usable
        repairs = _event(ctx, "repair")
        assert repairs
        assert repairs[-1]["decision"] == "repair_not_needed"


# ── (d) supervisor: остановка видна кодом ───────────────────────────────────


class TestSupervisorStopCode:
    @pytest.mark.asyncio
    async def test_stall_stop_visible_as_code(self, monkeypatch):
        """Watchdog-остановка stalled-вызова: llm_activity события несут
        коды provider_stalled и retry_time_budget_exhausted."""
        import asyncio

        import services.summary_llm_supervisor as sup

        events: list = []

        def _capture(run_id, **kwargs):
            events.append(kwargs)

        monkeypatch.setattr(sup, "resolve_attempt_deadline",
                            lambda *a, **k: (0.15, "test_deadline"))
        monkeypatch.setattr(sup, "hard_deadline_seconds", lambda: 30.0)
        monkeypatch.setattr(sup, "select_execution_mode",
                            lambda caps: sup.MODE_SYNC)
        import services.pipeline_events as pe
        monkeypatch.setattr(pe, "llm_activity", _capture)

        class _StalledLLM:
            _chat_model = "stall-model"
            _base_url = "http://stall"

            async def generate(self, messages, **kwargs):
                await asyncio.sleep(5.0)
                return "никогда"

        llm = _StalledLLM()
        with pytest.raises(Exception):
            await sup.execute_supervised(
                llm, messages=[{"role": "user", "content": "тест"}],
                operation="l1", correlation_id="ur26-stall", chat_id=CHAT_A,
                module="m", step="s")
        failed = [e for e in events if e.get("outcome") == "failed"]
        codes = {str(e.get("reason_code")) for e in failed}
        assert "provider_stalled" in codes, codes
        assert "retry_time_budget_exhausted" in codes, codes
        # Событие старта несёт наличие/отсутствие clock-блока в payload.
        starts = [e for e in events if e.get("outcome") == "start"]
        assert starts
        assert "clock_included" in (starts[-1].get("counts") or {})


# ── (e) digest = полный доставленный текст (связка с ledger full-text) ─────


class TestDigestMatchesDeliveredText:
    @pytest.mark.asyncio
    async def test_document_digest_covers_full_text(self, tz_chat):
        """Документ >20000 символов: document_digest = digest ПОЛНОГО
        plain-рендера (как леджер пишет целиком), не [:20000]-превью."""
        ctx = RunContextStub()
        paragraph = ("В чате обсудили погоду на выходные и договорились "
                     "встретиться у парка в полдень. ") * 9  # ~740 симв.
        doc = _doc([{"text": paragraph, "emphasis": None}
                    for _ in range(30)])            # ~22k символов
        llm_call = _Writer(doc)
        result = await run_l2(None, _package(),
                              slot=L2Slot("http://x", "l2-model", "k", False),
                              correlation_id="ur26-digest", chat_id=CHAT_A,
                              llm_call=llm_call, ctx=ctx)
        assert result.usable, result.invalid_reason
        from services.summary_article_formatter import format_plain_text
        delivered = format_plain_text(result.document)
        assert len(delivered) > 20000
        events = _event(ctx, "l2_writer")
        ev = events[-1]
        assert ev["document_digest"] == text_digest(delivered)
        # Мутация старого бага: digest по [:20000]-превью НЕ совпадает.
        assert ev["document_digest"] != text_digest(delivered[:20000])
        repairs = _event(ctx, "repair")
        assert repairs
        assert repairs[-1]["document_digest"] == text_digest(delivered)

    @pytest.mark.asyncio
    async def test_text_digest_is_full_stage_output(self, tz_chat):
        """text_digest стадии = digest полного сырого ответа LLM."""
        ctx = RunContextStub()
        doc = _doc([{"text": "Первый абзац про дождь.", "emphasis": None},
                    {"text": "Второй абзац про поездку.", "emphasis": None}])
        raw = json.dumps(doc, ensure_ascii=False)
        llm_call = _Writer(doc)
        await run_l2(None, _package(),
                     slot=L2Slot("http://x", "l2-model", "k", False),
                     correlation_id="ur26-digest2", chat_id=CHAT_A,
                     llm_call=llm_call, ctx=ctx)
        events = _event(ctx, "l2_writer")
        assert events[-1]["text_digest"] == text_digest(raw)
        assert events[-1]["chars"] == len(raw)


# ── Честные коды отсутствия payload/clock ───────────────────────────────────


class TestHonestAbsenceCodes:
    @pytest.mark.asyncio
    async def test_empty_l1_reports_no_llm_call(self):
        """Пустой вход: l1_plan событие с честным skip-кодом, без clock."""
        ctx = RunContextStub()
        result = await run_l1(rows=[], chat_id=None,
                              llm_call=_Writer(_doc([])),
                              budget=("chars", 20000),
                              correlation_id="ur26-empty", ctx=ctx)
        events = _event(ctx, "l1_plan")
        assert events
        ev = events[-1]
        assert result.status == "empty"
        assert ev["status"] == "empty"
        assert ev["clock"] == {"clock_included": False,
                               "skip_reason": "no_llm_call"}
        assert ev["decision"] == "empty_payload"

    @pytest.mark.asyncio
    async def test_clock_meta_honest_no_block(self):
        from services.summary_stage_events import clock_meta
        # chat_id есть, блока нет → no_time_block.
        meta = clock_meta([{"role": "user", "content": "без блока"}],
                          chat_id=CHAT_A)
        assert meta == {"clock_included": False,
                        "skip_reason": "no_time_block"}
        # chat_id нет → no_chat_id.
        assert clock_meta(None, chat_id=None) == {
            "clock_included": False, "skip_reason": "no_chat_id"}


# ── (f) подсаб-итем (a): deferred generator → свежий answer_as_of_utc ───────


def _strip_clock_block(content: str) -> str:
    start = content.find("<Chat_Time_Context")
    end = content.find("</Chat_Time_Context>", start)
    return (content[:start]
            + content[end + len("</Chat_Time_Context>"):]).strip()


class TestDeferredGeneratorFreshAnswerClock:
    @pytest.mark.asyncio
    async def test_retry_after_deferral_refreshes_answer_as_of(
            self, tz_chat, monkeypatch):
        """Отложенная генерация (retry-once после LLMError + дефер-пауза):
        новая попытка несёт ЯВНО свежее answer_as_of_utc (перевод минуты
        эмулируется честным ChatClock-правилом ensure_answer_snapshot),
        окно источников (summary_window_end_utc) в payload не меняется.
        Мутация «заморозить блок часов через дефер» — красная."""
        import datetime

        import config.settings as _cs
        from config.settings import Settings
        from services import chat_clock as cc
        from services.llm_client import LLMError
        from services.summary_generator import SummaryGenerator

        t0 = datetime.datetime(2026, 7, 15, 12, 0, 0,
                               tzinfo=datetime.timezone.utc)
        t1 = t0 + datetime.timedelta(seconds=61)

        def _snap(at):
            return cc.TimeSnapshot(
                as_of_utc=at,
                local_datetime=at + datetime.timedelta(hours=3),
                weekday="Среда", timezone="Europe/Moscow",
                utc_offset="+03:00", timezone_source="chat",
                config_version="cfg-ur26")

        produced = [_snap(t0), _snap(t1)]

        async def _fake_snapshot(chat_id, **kwargs):
            return produced.pop(0)

        monkeypatch.setattr(cc, "snapshot", _fake_snapshot)
        for cls in (Settings, type(_cs.settings)):
            monkeypatch.setattr(cls, "SUMMARY_RETRY_ONCE_PAUSE", 0.0,
                                raising=False)

        captured: list[list] = []

        class _DeferredLLM:
            _chat_model = "gen-model"
            _base_url = "http://gen"

            async def generate(self, messages, **kwargs):
                captured.append([dict(m) for m in messages])
                if len(captured) == 1:
                    raise LLMError("deferred: provider 503")
                return "саммари готово"

        sg = SummaryGenerator.__new__(SummaryGenerator)
        sg.llm = _DeferredLLM()
        sg.bot = __import__("unittest.mock",
                            fromlist=["AsyncMock"]).AsyncMock()
        window = ("Окно источников (период до 2026-11-05T10:00:00+00:00, "
                  "WINDOW_END_UTC_MARKER):\nсообщение про погоду и планы")
        out = await sg._llm_generate(
            [{"role": "system", "content": "S"},
             {"role": "user", "content": window}],
            CHAT_A, correlation_id="ur26-defer", step="single")
        assert out == "саммари готово"
        assert len(captured) == 2, "ровно одна повторная попытка (retry-once)"
        c1 = captured[0][-1]["content"]
        c2 = captured[1][-1]["content"]
        assert "as_of_utc: 2026-07-15T12:00:00+00:00" in c1
        assert "as_of_utc: 2026-07-15T12:01:01+00:00" in c2, (
            "отложенная повторная попытка обязана нести свежее "
            "answer_as_of_utc (мутация: блок заморожен через дефер → red)")
        assert _strip_clock_block(c1) == _strip_clock_block(c2) == window, (
            "окно источников (summary_window_end_utc) не пересобирается "
            "задним числом — payload вне блока часов байт-в-байт прежний")

    @pytest.mark.asyncio
    async def test_same_minute_deferral_keeps_plan_snapshot(self, tz_chat,
                                                            monkeypatch):
        """Дефер в пределах той же минуты: reuse снапшота по правилу минуты
        ChatClock (ас_of не «дрожит» между попытками без перевода минуты)."""
        import datetime

        import config.settings as _cs
        from config.settings import Settings
        from services import chat_clock as cc
        from services.llm_client import LLMError
        from services.summary_generator import SummaryGenerator

        t0 = datetime.datetime(2026, 7, 15, 12, 0, 0,
                               tzinfo=datetime.timezone.utc)
        produced = [cc.TimeSnapshot(
            as_of_utc=t0, local_datetime=t0 + datetime.timedelta(hours=3),
            weekday="Среда", timezone="Europe/Moscow", utc_offset="+03:00",
            timezone_source="chat", config_version="cfg-ur26")]

        async def _fake_snapshot(chat_id, **kwargs):
            return produced.pop(0)

        monkeypatch.setattr(cc, "snapshot", _fake_snapshot)
        for cls in (Settings, type(_cs.settings)):
            monkeypatch.setattr(cls, "SUMMARY_RETRY_ONCE_PAUSE", 0.0,
                                raising=False)

        captured: list[list] = []

        class _DeferredLLM:
            _chat_model = "gen-model"
            _base_url = "http://gen"

            async def generate(self, messages, **kwargs):
                captured.append([dict(m) for m in messages])
                if len(captured) == 1:
                    raise LLMError("deferred same-minute")
                return "саммари"

        sg = SummaryGenerator.__new__(SummaryGenerator)
        sg.llm = _DeferredLLM()
        sg.bot = __import__("unittest.mock",
                            fromlist=["AsyncMock"]).AsyncMock()
        await sg._llm_generate(
            [{"role": "system", "content": "S"},
             {"role": "user", "content": "окно источников"}],
            CHAT_A, correlation_id="ur26-defer0", step="single")
        assert len(captured) == 2
        assert captured[0][-1]["content"] == captured[1][-1]["content"], (
            "та же минута → один снапшот на ход (правило минуты ChatClock)")


# ── (g) подсаб-итем (b): chunked-L1 overflow эмитит l1_plan ─────────────────


class TestChunkedL1OverflowPlanEvent:
    @pytest.mark.asap41
    @pytest.mark.asyncio
    async def test_chunked_overflow_emits_l1_plan_events(self, tz_chat):
        """L1 переполнение → lossless chunking: события l1_plan эмитятся и
        здесь (те же поля payload-матрицы), финальное событие честно
        помечает план, собранный из чанков. Мутация «не эмитить на
        chunked overflow» (и «не прокидывать ctx в chunked-путь») — красная."""
        rows = [
            {"id": 101 + i, "tg_message_id": 101 + i, "user_id": 10 + i,
             "author_name": f"Автор{i}",
             "text": f"сообщение {i} про погоду и планы на выходные " * 30,
             "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
             "reply_to_id": None, "is_forward": 0, "forward_source": None}
            for i in range(4)
        ]
        calls: list[int] = []

        async def _llm_call(messages):
            content = str(messages[-1]["content"])
            ids = sorted({int(m)
                          for m in re.findall(r'"message_id":(\d+)', content)})
            assert ids, "сегмент обязан содержать §92-элементы с message_id"
            calls.append(len(ids))
            plan = {
                "schema_version": 2,
                "threads": [{
                    "thread_id": "t1", "topic": "погода",
                    "message_ids": ids,
                    "facts": [{"text": "обсуждали погоду",
                               "evidence_message_ids": ids[:1]}],
                }],
                "unassigned_message_ids": [],
            }
            return json.dumps(plan, ensure_ascii=False), {
                "prompt_tokens": 10, "completion_tokens": 5}

        ctx = RunContextStub()
        result = await run_l1(rows=rows, chat_id=CHAT_ID, llm_call=_llm_call,
                              budget=("chars", 700),
                              correlation_id="ur26-chunk", ctx=ctx)
        assert result.usable, result.invalid_reason
        assert result.status == "ok"
        assert len(calls) >= 2, "chunked-прогон обязан дать ≥2 сегмента"
        events = _event(ctx, "l1_plan")
        assert len(events) >= 2, (
            "сегменты chunked-прогона обязаны эмитить l1_plan (мутация: "
            "ctx не прокинут в chunked-путь → 0 событий → red)")
        final = events[-1]
        assert final["finish_reason"] == "chunked_merge", (
            "итог chunked-стадии обязан честно помечать сборку из чанков "
            "(мутация: событие вообще не эмитится → red)")
        assert final["decision"] == "l1_ok_chunked"
        assert final["status"] == "ok"
        assert final["model"] and final["provider"]
        assert _DIGEST_RE.match(final["text_digest"] or "")
        assert final["usage"]["input_tokens"] > 0
        assert final["usage"]["output_tokens"] > 0
        assert final["clock"]["clock_included"] is True
        assert final["output_count"] >= 1
        assert final["input_count"] == len(rows)
        # Честные фрагменты: text_digest финала — digest merged-плана,
        # НЕ digest последнего сырого сегмента.
        merged_json = json.dumps(result.payload, ensure_ascii=False)
        assert final["text_digest"] == text_digest(merged_json)
