"""UNIFIED-REPLY UR-26.3/UR-26.4 — payload-наблюдаемость стадий Initiative
и Factcheck (те же конвенции, что test_ur26_summary_payloads).

Матрица (строки UR-26.3/UR-26.4, reviewer-note 7632fdb6):

  * Initiative: L1-решение (silent/react/reply — код решения), tool/WebSearch
    фаза (route direct|initiative, режим/статус поиска), recheck перед
    отправкой (recheck_passed/again/demoted), nostalgia-Writer
    (prepared_text без вымышленного времени — честный код отсутствия
    ChatClock BY DESIGN);
  * Factcheck: Stage-1 аналитик (tool_loop/plain, parse-fallback chain),
    Stage-2 вербализатор (response_mode/short, server_time из снапшота),
    короткий персона-ответ (ChatClock-блок в payload — фикс UR-26.4),
    temporal_verdict (код вердикта + РАЗДЕЛЬНЫЕ маркеры времени оценки и
    даты публикации источника), temporal_validator (validated/corrected/
    failed), temporal_verbalize;
  * в payload событий нет текстов чата/ответа (R17) — только числа/коды/
    id/blake2s-16hex digest;
  * durable-канал — существующий mca_events (event_name=стадия,
    component=turn_payload, usage_json): событие проходит контракт mca-13
    (built is not None), ΔDDL=0.

Все LLM-каналы инжектируются — 0 сетевых/платных вызовов.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-G (payload matrix UR-26.3/26.4)
"""
from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import chat_clock as cc
from services import direct_chat_service as dcs
from services import mca_events
from services import mca_intents as mi
from services import turn_payload_events as tpe
from services.database import DatabaseService
from services.factcheck_service import FactCheckService
from services.tool_router import ToolContext, ToolDeps, ToolRouter

pytestmark = [pytest.mark.system2]

CHAT_A = 1001
CHAT = -100777

_DIGEST_RE = re.compile(r"^[0-9a-f]{16}$")

_STAGE_NAMES = (
    tpe.STAGE_INITIATIVE_L1, tpe.STAGE_TOOL_PHASE,
    tpe.STAGE_INITIATIVE_RECHECK, tpe.STAGE_NOSTALGIA_TEXT,
    tpe.STAGE_FC_STAGE1, tpe.STAGE_FC_STAGE2, tpe.STAGE_FC_SHORT_REPLY,
    tpe.STAGE_FC_TEMPORAL_VERDICT, tpe.STAGE_FC_TEMPORAL_VALIDATOR,
    tpe.STAGE_FC_TEMPORAL_VERBALIZE,
)


# ── Фикстуры ────────────────────────────────────────────────────────────────


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
             CHAT: {"overrides": {"limits.chat_timezone":
                                  "Europe/Moscow"}}}
    chat_params._chat_params_cache = FakeCache(roots)
    yield
    chat_params._chat_params_cache = None


@pytest.fixture()
def captured_events(monkeypatch):
    """Перехват mca-эмиссий payload-событий; реальный контракт mca-13
    выполняется (built is not None = событие принято allowlist'ами)."""
    real = mca_events.emit_mca_event
    rec: list = []

    def _rec(event_name, **kwargs):
        built = real(event_name, **kwargs)
        rec.append({"event_name": event_name, "built": built, **kwargs})
        return built

    monkeypatch.setattr(mca_events, "emit_mca_event", _rec)
    mca_events.reset_pending()
    yield rec
    mca_events.reset_pending()


def _events(rec, name):
    return [e for e in rec if e["event_name"] == name]


def _payload(event):
    """Payload-блок стадии (usage_json зеркала)."""
    return event.get("usage_json") or {}


def _assert_r17(rec, *forbidden):
    """В captured-событиях нет сырых текстов (R17)."""
    blob = json.dumps(rec, ensure_ascii=False, default=str)
    for fragment in forbidden:
        assert fragment not in blob, (
            f"сырой текст попал в payload события: {fragment!r}")


# ── Initiative: L1-решение + reply-прогон (tool-фаза + recheck) ─────────────


class _Bot:
    def __init__(self):
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))

        class _Msg:
            message_id = 5000 + len(self.sent)

        return _Msg()


async def _init_db(tmp_path, name="ur26_init.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _make_intent(db, *, goal="что там с релизом?"):
    import time as _time
    now = int(_time.time())
    result = await mi.get_service(db).create_intent(
        CHAT, kind="follow_up", origin="unanswered_question",
        subject_ids=("q:test",), goal=goal, source_refs=("msg:11",),
        not_before=now - 7200, expires_at=now + 3 * 86400,
        activation_condition="time_due", created_at=now - 7200)
    intent_id = result[0] if isinstance(result, tuple) else result
    row = await mi.get_service(db).store.get_intent(intent_id)
    return intent_id, row


def _candidate(intent_id):
    return mi.candidate_from_trigger(
        trigger_kind="intent_due", chat_id=CHAT, intent_id=intent_id,
        reason_code="default")


def _situation():
    return mi.InitiativeSituation(trigger_kind="intent_due", chat_id=CHAT)


@pytest.fixture(autouse=True)
def _exploration_off(monkeypatch):
    import services.mca_exploration as expl

    async def _off(db, purpose, chat_id):
        return False, "test_disabled"

    monkeypatch.setattr(expl, "exploration_allowed", _off)


def _plan_json(**over):
    from tests.test_asap7_direct_l1 import _plan_json as _base
    return _base(**over)


class TestInitiativePayloadEvents:
    @pytest.mark.asyncio
    async def test_reply_run_l1_tool_phase_recheck_events(
            self, tz_chat, captured_events, monkeypatch, tmp_path):
        """(a) Реальный инициативный reply-прогон: события L1-решения
        (decision=reply, часы в payload L1), tool-фазы (route=initiative,
        режим/статус поиска, digest evidence) и recheck_passed — кодами,
        без сырых текстов (R17)."""
        from services.direct_l1 import normalize_l1_plan
        from tests.test_asap7_direct_l1 import _FakeLLM, _FakeRouter
        from tests.test_direct_chat import FakeMemory, _make_service

        plan = json.loads(_plan_json(
            capabilities_needed=["web_search"],
            knowledge_origin="open_world"))
        llm = _FakeLLM(l1=json.dumps(plan, ensure_ascii=False),
                       l2="ответ Initiative")
        router = _FakeRouter(default="результаты поиска по релизу")
        writer = _make_service(llm=llm, memory=FakeMemory(window=[]),
                               tool_router=router)
        # Гейты evidence-политики — вне среза этого теста (свой CONTRACT-
        # охват в test_evol_evidence_routing); tool-фаза ниже идёт РЕАЛЬНЫМ
        # исполнителем run_tool_phase с реальным роутером и поисковым
        # запросом из claim'ов плана. Сеам reuse — синхронный вызов.
        _claim = SimpleNamespace(entity="релиз", version="2.58",
                                 metric="", date="", complete=True,
                                 key=lambda: "релиз:2.58")
        _decision = SimpleNamespace(required=True,
                                    required_caps=("web_search",),
                                    claims=(_claim,))
        monkeypatch.setattr(writer, "_evidence_preflight",
                            AsyncMock(return_value=_decision))
        monkeypatch.setattr(writer, "_evidence_reuse_pack",
                            lambda *a, **kw: None)
        monkeypatch.setattr(writer, "_emit_evidence_delivery_event",
                            lambda *a, **kw: None)
        monkeypatch.setattr(writer, "_record_evidence_delivery",
                            lambda *a, **kw: None)
        monkeypatch.setattr(writer, "_evidence_writer_note",
                            lambda *a, **kw: "")
        monkeypatch.setattr(writer, "_emit_evidence_egress_event",
                            lambda *a, **kw: None)
        monkeypatch.setattr(dcs, "_run_evidence_egress_guard",
                            AsyncMock(return_value=("ответ Initiative",
                                                    SimpleNamespace())))
        monkeypatch.setattr(
            writer, "_l1_tool_subset",
            AsyncMock(return_value=(
                [{"function": {"name": "execute_web_search",
                               "description": "web"}}], [])))

        db = await _init_db(tmp_path)
        try:
            intent_id, intent_row = await _make_intent(db)
            result = await dcs.handle_initiative(
                bot=_Bot(), chat_id=CHAT, situation=_situation(),
                candidates=[_candidate(intent_id)], db=db,
                correlation_id="corr-ur26-init", writer_service=writer,
                opportunity_row={"goal": "рассказать про релиз",
                                 "kind": "follow_up",
                                 "origin": "unanswered_question",
                                 "created_at": 1})
            assert result["status"] == "sent", result
        finally:
            await db.close()

        l1_events = _events(captured_events, tpe.STAGE_INITIATIVE_L1)
        assert len(l1_events) == 1
        ev = l1_events[0]
        assert ev["built"] is not None          # контракт mca-13 принят
        assert ev["outcome"] == "success"
        assert ev["chat_id"] == CHAT
        payload = _payload(ev)
        assert payload["decision"] == "reply"
        assert payload["finish_reason"] == "parsed"
        assert payload["clock"]["clock_included"] is True
        assert payload["clock"]["timezone"] == "Europe/Moscow"
        assert _DIGEST_RE.match(payload["text_digest"])
        assert isinstance(payload["chars"], int) and payload["chars"] > 0

        tool_events = _events(captured_events, tpe.STAGE_TOOL_PHASE)
        assert tool_events, "tool-фаза ответа не дала payload-события"
        ev = tool_events[0]
        assert ev["outcome"] == "success"
        payload = _payload(ev)
        assert "route=initiative" in payload["decision"]
        assert "action=reply" in payload["decision"]
        assert "search=ok" in payload["decision"]
        assert ev["built"] is not None
        assert _DIGEST_RE.match(payload["text_digest"])

        recheck_events = _events(captured_events,
                                 tpe.STAGE_INITIATIVE_RECHECK)
        assert recheck_events, "recheck verdict не виден событием"
        ev = recheck_events[-1]
        assert ev["outcome"] == "success"
        assert _payload(ev)["decision"] == "recheck_passed"
        assert _payload(ev)["finish_reason"] == "recheck_passed"

        _assert_r17(captured_events, "ответ Initiative",
                    "результаты поиска по релизу",
                    "рассказать про релиз", "что там с релизом?")

    @pytest.mark.asyncio
    async def test_l1_silent_decision_code_no_writer(
            self, tz_chat, captured_events):
        """(b) SILENT-решение L1: код решения виден в событии, Writer не
        вызывается (0 L2-вызовов, 0 сети)."""
        from tests.test_asap7_direct_l1 import _FakeLLM
        from tests.test_direct_chat import FakeMemory, _make_service

        llm = _FakeLLM(l1=_plan_json(action="silent"), l2="НЕ ДОЛЖЕН")
        service = _make_service(llm=llm, memory=FakeMemory(window=[]))
        plan = await service.plan_initiative_decision(
            CHAT, {"goal": "цель"}, correlation_id="corr-silent")
        assert plan is not None
        assert getattr(plan, "action", "") == "silent"

        evs = _events(captured_events, tpe.STAGE_INITIATIVE_L1)
        assert len(evs) == 1
        payload = _payload(evs[0])
        assert payload["decision"] == "silent"
        assert payload["clock"]["clock_included"] is True
        assert evs[0]["built"] is not None
        # Writer не вызван: ни одного шага l2_writer.
        assert not [c for c in llm.calls if c.get("step") == "l2_writer"]
        _assert_r17(captured_events, "НЕ ДОЛЖЕН", "цель")

    @pytest.mark.asyncio
    async def test_recheck_demoted_visible(self, tz_chat, captured_events,
                                           monkeypatch, tmp_path):
        """Recheck понизил участие (L1 переоценка на свежем контексте дала
        silent) — код recheck_demoted виден в payload-событии, не
        молчаливый demote; переоценка ровно одна (bounded §18D-3)."""
        from dataclasses import replace as _dc_replace
        from tests.test_asap7_direct_l1 import _FakeLLM
        from tests.test_direct_chat import FakeMemory, _make_service

        db = await _init_db(tmp_path, "ur26_demote.db")
        try:
            intent_id, _row = await _make_intent(db)
            llm = _FakeLLM(
                l1=[_plan_json(capabilities_needed=["web_search"],
                               knowledge_origin="open_world"),
                    _plan_json(action="silent")],
                l2="черновик инициативы")
            writer = _make_service(llm=llm, memory=FakeMemory(window=[]))
            # Детерминированная смена контекста между решением и отправкой:
            # второй свежий расчёт возвращает ДРУГУЮ версию контекста.
            real_recheck = dcs.build_fresh_recheck_context
            calls = {"n": 0}

            async def _changing(db_, chat_id, intent_row, **kw):
                ctx = await real_recheck(db_, chat_id, intent_row, **kw)
                calls["n"] += 1
                if calls["n"] >= 2:
                    return _dc_replace(
                        ctx, context_version=(
                            str(getattr(ctx, "context_version", "") or "v0")
                            + "-changed"))
                return ctx

            monkeypatch.setattr(dcs, "build_fresh_recheck_context",
                                _changing)
            result = await dcs.handle_initiative(
                bot=_Bot(), chat_id=CHAT, situation=_situation(),
                candidates=[_candidate(intent_id)], db=db,
                correlation_id="corr-demote", writer_service=writer,
                opportunity_row={"goal": "повод", "kind": "follow_up",
                                 "origin": "unanswered_question",
                                 "created_at": 1})
            assert result["status"] == "silent", result
            assert result.get("reason_code") == "recheck_demoted"
            evs = _events(captured_events, tpe.STAGE_INITIATIVE_RECHECK)
            assert evs, "recheck_demoted не дал события"
            again = [e for e in evs
                     if _payload(e)["decision"] == "recheck_again"]
            assert again, "recheck_again не виден кодом"
            assert again[0]["outcome"] == "skipped"
            last = evs[-1]
            assert _payload(last)["decision"].startswith("recheck_demoted")
            assert last["outcome"] == "skipped"
            # Ровно одна переоценка: второй вызов L1 был (bounded §18D-3).
            l1_events = _events(captured_events, tpe.STAGE_INITIATIVE_L1)
            assert len(l1_events) == 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_nostalgia_writer_event_no_fabricated_clock(
            self, tz_chat, captured_events):
        """Nostalgia-Writer: prepared_text не получает вымышленного
        времени — ChatClock-блока в payload НЕТ BY DESIGN, событие честно
        фиксирует отсутствие + digest произведённого текста."""
        from services.nostalgia_worker import NostalgiaWorker

        class _NLLM:
            _chat_model = "unit-model"
            _base_url = "https://unit.example/v1"

            def __init__(self):
                self.messages = None

            async def generate(self, messages, temperature=None, **kw):
                self.messages = messages
                return "UNCHANGED"

        llm = _NLLM()
        worker = NostalgiaWorker.__new__(NostalgiaWorker)
        worker.llm = llm
        worker.store = None
        worker.db = SimpleNamespace(
            list_chat_memes=AsyncMock(return_value=[]))
        raw = await worker._llm_once(
            {"kind": "year_back", "weight": 1.0, "text": "событие",
             "year_lines": ["[Аня 2025-11-05]: то самое событие"]},
            CHAT_A)
        assert raw == "UNCHANGED"
        # Часов в payload нет — время не выдумывается.
        user_content = llm.messages[-1]["content"]
        assert "<Chat_Time_Context" not in user_content
        evs = _events(captured_events, tpe.STAGE_NOSTALGIA_TEXT)
        assert len(evs) == 1
        payload = _payload(evs[0])
        assert payload["finish_reason"] == "generated"
        assert payload["decision"] == "nostalgia_generated"
        assert payload["clock"] == {
            "clock_included": False,
            "skip_reason": "nostalgia_by_design_no_clock"}
        assert _DIGEST_RE.match(payload["text_digest"])
        assert _payload(evs[0])["chars"] == len("UNCHANGED")
        _assert_r17(captured_events, "то самое событие")


# ── Factcheck: Stage-1/Stage-2, temporal, короткий ответ ────────────────────


class _FakeSearch:
    async def search(self, query, max_symbols=4000, **kw):
        return "источник с датой публикации https://example.com/x"


class _RoutedFC:
    """LLM-двойник по step: stage1 → аналитик JSON, stage2 → текст."""

    def __init__(self, stage1, stage2="Проверено: подтверждено."):
        self.stage1 = stage1
        self.stage2 = stage2
        self.calls = []
        self._chat_model = "unit-model"
        self._base_url = "https://unit.example/v1"

    async def generate(self, messages, **kwargs):
        step = str(kwargs.get("step") or "")
        self.calls.append((step, messages))
        if step in ("stage1", "single"):
            return self.stage1
        return self.stage2


_ANALYST = json.dumps({
    "claim": "утверждение про налог 2022 года",
    "verdict": "подтверждено частично",
    "response_mode": "serious",
    "findings": [{"assertion": "налог введён в 2022",
                  "status": "true",
                  "evidence": "источник с датой публикации",
                  "human_time": "2022"}],
    "uncertainty": {},
}, ensure_ascii=False)


class TestFactcheckPayloadEvents:
    @pytest.mark.asyncio
    async def test_two_call_stage_events(self, tz_chat, captured_events,
                                         monkeypatch):
        """(c) Структурный прогон (System 2): события Stage-1 (аналитик
        JSON, plain-маршрут, часы в payload) и Stage-2 (режим ответа,
        server_time из снапшота) с digest/chars; usage честно None
        (слой str-фасада токенов не имеет)."""
        from config.settings import settings
        monkeypatch.setattr(type(settings), "SYSTEM2_FACTCHECK_ENABLED",
                            True, raising=False)
        llm = _RoutedFC(_ANALYST, stage2="Короткий подтверждённый ответ.")
        svc = FactCheckService(llm=llm, aggregator=_FakeSearch(),
                               memory=None, tool_router=None)
        out = await svc.check_claim(
            "утверждение про налог 2022 года", search_results="выдача",
            chat_id=CHAT_A)
        assert out

        s1 = _events(captured_events, tpe.STAGE_FC_STAGE1)
        assert len(s1) == 1
        ev = s1[0]
        assert ev["built"] is not None
        assert ev["outcome"] == "success"
        payload = _payload(ev)
        assert payload["finish_reason"] == "parsed_json"
        assert payload["decision"] == "plain"
        assert payload["clock"]["clock_included"] is True
        assert payload["clock"]["timezone"] == "Europe/Moscow"
        assert _DIGEST_RE.match(payload["text_digest"])
        assert payload["chars"] == len(strip_tags_analyst(_ANALYST))
        assert payload.get("usage") is None      # честная пустота

        s2 = _events(captured_events, tpe.STAGE_FC_STAGE2)
        assert len(s2) == 1
        payload = _payload(s2[0])
        assert payload["finish_reason"] == "generated"
        assert "mode=serious" in payload["decision"]
        assert "server_time=snapshot" in payload["decision"]
        assert _DIGEST_RE.match(payload["text_digest"])
        assert s2[0]["model"] == "unit-model"
        assert s2[0]["provider"] == "unit.example"

        _assert_r17(captured_events, "утверждение про налог",
                    "Короткий подтверждённый ответ", "тезис")

    @pytest.mark.asyncio
    async def test_stage1_parse_invalid_fallback_chain_visible(
            self, tz_chat, captured_events, monkeypatch):
        """Fallback-цепочка видна событиями: Stage-1 parse-invalid →
        одиночный путь 10.21 (decision single_path:plain), не молчаливый
        fallback."""
        from config.settings import settings
        monkeypatch.setattr(type(settings), "SYSTEM2_FACTCHECK_ENABLED",
                            True, raising=False)
        llm = _RoutedFC("совсем не JSON {{{", stage2="вербализация")
        svc = FactCheckService(llm=llm, aggregator=_FakeSearch(),
                               memory=None, tool_router=None)
        out = await svc.check_claim("утверждение", search_results="выдача",
                                    chat_id=CHAT_A)
        assert out
        s1 = _events(captured_events, tpe.STAGE_FC_STAGE1)
        assert len(s1) == 2
        first, second = s1
        assert _payload(first)["finish_reason"] == "parse_invalid"
        assert _payload(first)["decision"].endswith("parse_invalid_fallback")
        assert first["outcome"] == "failed"
        assert _payload(second)["decision"] == "single_path:plain"
        assert second["outcome"] == "success"
        assert _payload(second)["clock"]["clock_included"] is True

    @pytest.mark.asyncio
    async def test_temporal_verdict_event_separation_markers(
            self, tz_chat, captured_events):
        """(d) temporal_verdict: код вердикта + РАЗДЕЛЬНЫЕ маркеры — время
        оценки (ChatClock as_of_utc в clock) и дата публикации источника
        (date_source/pub_date); downgrade и валидатор — явные коды."""
        from services import temporal_factcheck as tf

        analyst = json.dumps({
            "factual_verdict": "supported",
            "temporal_status": "old_but_valid",
            "evaluated_period": {"from": 1665277000, "to": 1665363400,
                                 "precision": "day"},
            "uncertainty": {},
        }, ensure_ascii=False)
        validator = json.dumps(
            {"agree": True, "corrected_factual_verdict": None,
             "corrected_temporal_status": None, "note": "ок"},
            ensure_ascii=False)

        class _TempLLM:
            _chat_model = "unit-model"
            _base_url = "https://unit.example/v1"

            def __init__(self):
                self.calls = []

            async def generate(self, messages, **kwargs):
                step = str(kwargs.get("step") or "")
                self.calls.append(step)
                if step in ("temporal_verdict", "temporal_fallback"):
                    return analyst
                if step == "temporal_validator":
                    return validator
                return "Было верно, сейчас устарело."

        llm = _TempLLM()
        env = tf.TemporalClaimEnvelope(
            claim_id="tcl-ur26", chat_id=CHAT_A, target_tg_message_id=10,
            target_revision=2, target_content_hash="h",
            trigger_tg_message_id=11,
            claim_text="в 2022 ввели налог",
            claim_span=None, source_type="text",
            attribution={"author": "Канал"},
            related_asset_id=None, related_analysis_revision=None,
            claim_anchor_tg_message_id=None,
            origin_type="channel", origin_sender_user_id=None,
            origin_chat_id=-777, origin_display_name="Канал",
            repost_received_at=1760000000, original_published_at=1665277000,
            original_published_precision="day",
            claim_period_from=None, claim_period_to=None,
            claim_period_precision=None,
            date_source="telegram_origin", date_precision="day",
            date_timezone=None, date_uncertainty={},
            requested_mode="contextual", analysis_as_of=1760000000)
        run = await FactCheckService(_FakeSearch(), llm) \
            .check_claim_envelope(env)
        assert run.verdict.factual_verdict == "supported"

        verdict_events = _events(captured_events,
                                 tpe.STAGE_FC_TEMPORAL_VERDICT)
        assert len(verdict_events) == 1
        payload = _payload(verdict_events[0])
        assert payload["finish_reason"] == "parsed_json"
        assert payload["decision"].startswith("v=supported")
        assert "dg=none" in payload["decision"]
        # Разделение времён: оценка — ChatClock-блок, публикация — свои
        # поля (reason_code), не подменяются временем чата.
        assert payload["clock"]["clock_included"] is True
        assert "as_of_utc" in payload["clock"]
        reason = payload.get("reason_code") or ""
        assert "temporal=old_but_valid" in reason
        assert "date_source=telegram_origin" in reason
        assert "pub_date=present" in reason

        val = _events(captured_events, tpe.STAGE_FC_TEMPORAL_VALIDATOR)
        assert len(val) == 1
        assert _payload(val[0])["decision"] == "validator=validated;corrected=False"
        assert _payload(val[0])["clock"]["clock_included"] is True

        verb = _events(captured_events, tpe.STAGE_FC_TEMPORAL_VERBALIZE)
        assert len(verb) == 1
        assert _payload(verb[0])["finish_reason"] == "generated"
        assert "server_time=snapshot" in _payload(verb[0])["decision"]
        assert _DIGEST_RE.match(_payload(verb[0])["text_digest"])

        _assert_r17(captured_events, "в 2022 ввели налог",
                    "Было верно, сейчас устарело")

    @pytest.mark.asyncio
    async def test_short_reply_carries_clock_and_event(
            self, tz_chat, captured_events):
        """Короткий персона-ответ получает TimeContext (UR-26.4 фикс:
        блок в фактическом payload) + payload-событие."""
        from services.factcheck_orchestrator import persona_short_reply

        class _LLM:
            _chat_model = "unit-model"
            _base_url = "https://unit.example/v1"

            def __init__(self):
                self.messages = None

            async def generate(self, messages, **kwargs):
                self.messages = messages
                return "Уточните, какой именно тезис проверить?"

        llm = _LLM()
        svc = SimpleNamespace(llm=llm)
        out = await persona_short_reply(
            svc, CHAT_A, instruction="короткая реплика",
            situation="предложение проверить факт",
            fallback_phrases=())
        assert out
        user_content = llm.messages[-1]["content"]
        assert user_content.count("<Chat_Time_Context") == 1
        assert "Europe/Moscow" in user_content
        evs = _events(captured_events, tpe.STAGE_FC_SHORT_REPLY)
        assert len(evs) == 1
        payload = _payload(evs[0])
        assert payload["decision"] == "short_reply:generated"
        assert payload["clock"]["clock_included"] is True
        assert evs[0]["model"] == "unit-model"
        _assert_r17(captured_events, "Уточните, какой именно")


class TestToolPhasePayloadEvent:
    """Общий шов tool/WebSearch-фазы (run_tool_phase): route-коды и
    честные пропуски (silent/react — 0 сети)."""

    def _schemas(self, *names):
        return [{"function": {"name": name, "description": name}}
                for name in names]

    class _SearchProvider:
        def __init__(self, text):
            self.text = text
            self.queries: list = []

        async def search(self, query, max_symbols=4000, **kw):
            self.queries.append(str(query))
            return self.text

    @pytest.mark.asyncio
    async def test_direct_route_search_event(self, tz_chat, captured_events):
        """route=direct + реальный поиск: событие с режимом, статусом
        поиска, digest'ом evidence и ChatClock-блоком orchestrator-payload."""
        from services import direct_execution as _dx
        from services.direct_l1 import normalize_l1_plan
        snap = await cc.snapshot(CHAT_A)
        time_line = cc.render_chat_time_context(snap, phase=cc.PHASE_PLAN)
        search = self._SearchProvider("выдача поиска: релиз прошёл")
        router = ToolRouter(ToolDeps(search=search, memory=object()))
        plan = normalize_l1_plan({"action": "reply", "confidence": 0.9,
                                  "knowledge_origin": "open_world"})
        result = await _dx.run_tool_phase(
            plan=plan, router=router, ctx=ToolContext(CHAT, "релиз?"),
            query="релиз?", chat_id=CHAT, correlation_id="corr-tool",
            tool_schemas=self._schemas("execute_web_search"),
            required_caps=("web_search",), emit_trace=False,
            time_context=time_line, route="direct")
        assert result.raw is not None
        assert search.queries, "поиск не выполнялся"
        evs = _events(captured_events, tpe.STAGE_TOOL_PHASE)
        assert len(evs) == 1
        payload = _payload(evs[0])
        assert evs[0]["outcome"] == "success"
        assert "route=direct" in payload["decision"]
        assert "action=reply" in payload["decision"]
        assert "search=ok" in payload["decision"]
        assert payload["clock"]["clock_included"] is True
        assert payload["clock"]["timezone"] == snap.timezone
        assert payload["clock"]["phase"] == "plan"
        assert "as_of_utc" in payload["clock"]
        assert _DIGEST_RE.match(payload["text_digest"])
        _assert_r17(captured_events, "выдача поиска: релиз прошёл",
                    "релиз?")

    @pytest.mark.asyncio
    async def test_silent_skip_no_network(self, tz_chat, captured_events):
        """SILENT/REACT → 0 tool-вызовов: событие-пропуск с кодом участия,
        поисковый провайдер не тронут."""
        from services import direct_execution as _dx
        from services.direct_l1 import normalize_l1_plan
        search = self._SearchProvider("НЕ ДОЛЖЕН")
        router = ToolRouter(ToolDeps(search=search, memory=object()))
        plan = normalize_l1_plan({"action": "silent", "confidence": 0.9})
        result = await _dx.run_tool_phase(
            plan=plan, router=router, ctx=ToolContext(CHAT, "вопрос?"),
            query="вопрос?", chat_id=CHAT, correlation_id="corr-skip",
            tool_schemas=self._schemas("execute_web_search"),
            emit_trace=False, route="initiative")
        assert result.raw is None
        assert not search.queries, "silent не должен ходить в сеть"
        evs = _events(captured_events, tpe.STAGE_TOOL_PHASE)
        assert len(evs) == 1
        assert evs[0]["outcome"] == "skipped"
        payload = _payload(evs[0])
        assert payload["finish_reason"] == "skipped_participation"
        assert "route=initiative" in payload["decision"]
        assert "action=silent" in payload["decision"]
        _assert_r17(captured_events, "НЕ ДОЛЖЕН")


def strip_tags_analyst(text: str) -> str:
    """Размер ответа аналитика после strip (паритет с событием stage1)."""
    from services.reply_postprocess import strip_reasoning_tags
    return str(strip_reasoning_tags(text))
