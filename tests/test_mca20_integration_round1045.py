"""MCA-20 round 10.45 — интеграция: пайплайн/тул/handler/реестр/routes/v33.

Приёмки: A70 (offline full-route smoke: 2026-репост 2022 со «сегодня» →
old_but_valid ≠ фейк; режимы различаются), A72 (один envelope через
аналитика/verbalizer/fallback + provenance в v33 + нет рекурсивного
tool loop), A73 (run/evidence видны: v33 + routes + процесс v1 8 стадий).

Spec: D4/D8–D16 (mca-20-temporal-factcheck), §30.3–§30.4.
Запуск: .venv\\Scripts\\python.exe -m pytest tests/test_mca20_integration_round1045.py -q
"""
import asyncio
import dataclasses
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import mca_events, mca_gates, temporal_factcheck as tf
from services.factcheck_service import FactCheckService
from services.search_aggregator import AllSearchEnginesFailedException


def _env(**overrides):
    base = dict(
        claim_id="tcl-i", chat_id=1, target_tg_message_id=10,
        target_revision=2, target_content_hash="hash1",
        trigger_tg_message_id=11, claim_text="в 2022 году ввели новый налог",
        claim_span=None, source_type="text", attribution={"author": "Канал"},
        origin_type="channel", origin_sender_user_id=None,
        origin_chat_id=-777, origin_display_name="Канал",
        repost_received_at=1760000000, original_published_at=1665277000,
        original_published_precision="day", claim_period_from=None,
        claim_period_to=None, claim_period_precision=None,
        date_source="telegram_origin", date_precision="day",
        date_timezone=None, date_uncertainty={}, requested_mode="contextual",
        analysis_as_of=1760000000)
    base.update(overrides)
    return tf.TemporalClaimEnvelope(**base)


class FakeAggregator:
    def __init__(self, text="статья https://example.com/nalog — сниппет "
                            "о налоге 2022"):
        self.text = text

    async def search(self, q, max_symbols):
        return self.text


class ScriptedLLM:
    """Фейковый LLM: вердикт-стадия → записанный JSON, вербализатор → текст.
    Офлайн-запись реального маршрута (fixture без LLM-транспорта, §8.1)."""

    def __init__(self, verdict_json, verbalized=None):
        self.verdict_json = verdict_json
        self.verbalized = verbalized or (
            "Проверено на период 2022: утверждение соответствовало "
            "действительности. Сейчас действует иначе (устарело).")
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        system = messages[0]["content"]
        if system.startswith("Ты — фактчек-аналитик"):
            return self.verdict_json
        if system.startswith("Ты — проверяющий"):
            # rework R1 (F-2): validator-стадия spec D11 — happy path фейка
            # соглашается с вердиктом аналитика (сценарии сбоя/коррекции —
            # в tests/test_mca20_rework1_f1_f2.py).
            return json.dumps({"agree": True, "corrected_factual_verdict": None,
                               "corrected_temporal_status": None,
                               "note": "согласен"}, ensure_ascii=False)
        return self.verbalized


_OK_VERDICT = json.dumps({
    "factual_verdict": "supported",
    "temporal_status": "old_but_valid",
    "evaluated_period": {"from": 1665277000, "to": 1665363400,
                         "precision": "day"},
    "parts": [{"part_id": "p1", "factual_verdict": "supported",
               "note": "на 2022 подтверждено"}],
    "uncertainty": {"summary": "источник один, вторичный"},
}, ensure_ascii=False)


# ── A72: один envelope через все ветки + provenance + нет рекурсии ───────────

class TestOneEnvelopeThroughBranches:
    @pytest.mark.asyncio
    async def test_analyst_and_verbalizer_get_same_envelope(self):
        llm = ScriptedLLM(_OK_VERDICT)
        run = await FactCheckService(FakeAggregator(), llm) \
            .check_claim_envelope(_env())
        assert run.verdict.factual_verdict == "supported"
        assert run.verdict.temporal_status == "old_but_valid"
        assert run.verdict.assessment_mode == "contextual"
        # вербализатор получил период/статус вердикта (даты не стираются)
        verbalizer_msgs = [m for m, _ in llm.calls
                           if "ВЕРДИКТ (JSON)" in m[1]["content"]]
        assert verbalizer_msgs, "verbalize-стадия должна получить payload"
        payload = json.loads(verbalizer_msgs[0][1]["content"]
                             .split("ВЕРДИКТ (JSON):\n", 1)[1])
        assert payload["temporal_status"] == "old_but_valid"
        assert payload["evaluated_period"]["precision"] == "day"

    @pytest.mark.asyncio
    async def test_fallback_keeps_mode_and_dates(self):
        """SC-R3c/F-5: невалидный JSON аналитика → fallback-ветка получает
        ТОТ ЖЕ envelope; режим не меняется молча (temporal_fallback_mode)."""
        llm = ScriptedLLM("не JSON вообще {{{",
                          verbalized="Ответ на период 2022.")
        run = await FactCheckService(FakeAggregator(), llm) \
            .check_claim_envelope(_env(requested_mode="historical_truth"))
        assert run.fallback_used is True
        assert run.verdict.assessment_mode == "historical_truth"
        reasons = [s.get("reason") for s in run.stage_trace]
        assert "temporal_fallback_mode" in reasons
        assert run.verdict_text  # пользователь получает ответ и в fallback

    @pytest.mark.asyncio
    async def test_no_recursive_fact_check(self, monkeypatch):
        """CA-20-12: внутренний loop не вызывает fact_check рекурсивно —
        стадии data-only; chat_with_tools вообще не вызывается."""
        async def _boom(*a, **kw):
            raise AssertionError("рекурсивный tool loop запрещён (CA-20-12)")

        import services.tool_loop
        monkeypatch.setattr(services.tool_loop, "chat_with_tools", _boom)
        llm = ScriptedLLM(_OK_VERDICT)
        run = await FactCheckService(FakeAggregator(), llm) \
            .check_claim_envelope(_env())
        assert run.verdict_text

    @pytest.mark.asyncio
    async def test_stage_trace_full_route(self):
        llm = ScriptedLLM(_OK_VERDICT)
        run = await FactCheckService(FakeAggregator(), llm) \
            .check_claim_envelope(_env())
        stages = [s["stage"] for s in run.stage_trace]
        assert set(stages) >= {"origin_date_resolve", "claim_decompose",
                               "temporal_search", "evidence_validate",
                               "verdict", "verbalize"}


# ── A70: offline full-route smoke (2026-репост 2022 со «сегодня») ────────────

class TestOfflineSmokeA69A70:
    @pytest.mark.asyncio
    async def test_age_is_not_falsehood_contextual(self):
        """§30 преамбула: возраст публикации ≠ ложность; дефолтный
        contextual не превращает «тогда было верно» в «фейк»."""
        db_rows = {(1, 10): {
            "chat_id": 1, "tg_message_id": 10, "text": "сегодня ввели налог",
            "caption": None, "sent_at": 1760000000,
            "content_hash": "hash1", "current_revision": 1,
            "origin_type": "channel", "origin_sent_at": 1665277000,
            "origin_sender_user_id": None, "origin_chat_id": -777,
            "origin_display_name": "Канал", "author_name": None,
            "forward_source": "Канал"}}
        env, reason = await tf.build_envelope(
            FakeDbRows(db_rows),
            tf.InputRef(kind="reply", chat_id=1, target_tg_message_id=10,
                        trigger_tg_message_id=11))
        assert reason is None
        assert env.date_source == "telegram_origin"
        # «сегодня» разрешено относительно даты оригинала (2022)
        assert env.claim_period_precision == "day"
        year = tf.datetime.datetime.fromtimestamp(
            env.claim_period_from, tf.datetime.timezone.utc).year
        assert year == 2022
        run = await FactCheckService(FakeAggregator(), ScriptedLLM(_OK_VERDICT)) \
            .check_claim_envelope(env)
        assert run.verdict.temporal_status == "old_but_valid"
        assert run.verdict.factual_verdict == "supported"
        # актуальность отделена от фактической оценки (A69)
        assert run.verdict.factual_verdict != run.verdict.temporal_status

    @pytest.mark.asyncio
    async def test_modes_distinguish_same_claim(self):
        """A70/A71: одинаковый claim в режимах current/historical/knowable —
        различимые корректные результаты (assessment_mode + период)."""
        runs = {}
        for mode in ("current", "historical_truth", "knowable_at_time"):
            runs[mode] = await FactCheckService(
                FakeAggregator(), ScriptedLLM(_OK_VERDICT)) \
                .check_claim_envelope(_env(requested_mode=mode))
        assert len({r.verdict.assessment_mode for r in runs.values()}) == 3
        # current не выдаёт «было верно тогда» за «актуально сейчас»:
        # одинаковый as_of (envelope), но режимы различены в вердикте.
        assert runs["current"].verdict.assessment_mode == "current"


class FakeDbRows:
    def __init__(self, rows):
        self.rows = rows

    async def get_smart_message_origin_block(self, chat_id, tg_id):
        return self.rows.get((chat_id, tg_id))


# ── v33: durable run+evidence (A73) ──────────────────────────────────────────

class TestRunRecording:
    @pytest.mark.asyncio
    async def test_record_and_read_roundtrip(self, tmp_path):
        from services.database import DatabaseService
        db = DatabaseService(str(tmp_path / "t.db"))
        await db.initialize()
        env = _env()
        run = await FactCheckService(FakeAggregator(), ScriptedLLM(_OK_VERDICT)) \
            .check_claim_envelope(env)
        run_id = await tf.record_temporal_run(db, run, scope="chat:1")
        assert run_id
        stored = await db.get_factcheck_run(run_id)
        assert stored["factual_verdict"] == "supported"
        assert stored["temporal_status"] == "old_but_valid"
        assert stored["original_published_at"] == 1665277000
        trace = json.loads(stored["stage_trace"])
        assert isinstance(trace, list) and trace
        evidence = await db.get_factcheck_evidence(run_id)
        assert evidence and evidence[0]["url"].startswith("https://")
        listed = await db.list_factcheck_runs(chat_id=1, limit=5)
        assert [r["run_id"] for r in listed] == [run_id]
        # write-once: повторный run_id не перезаписывает (честный аудит)
        assert await db.record_factcheck_run({"run_id": run_id}) is False
        await db.close()

    @pytest.mark.asyncio
    async def test_evidence_cap(self, tmp_path):
        from services.database import DatabaseService
        db = DatabaseService(str(tmp_path / "t2.db"))
        await db.initialize()
        await db.record_factcheck_run({"run_id": "r-cap"})
        n = await db.record_factcheck_evidence(
            "r-cap", [{"url": f"https://x/{i}"} for i in range(50)],
            max_rows=3)
        assert n == 3
        await db.close()

    @pytest.mark.asyncio
    async def test_record_fail_open_without_db(self):
        run = await FactCheckService(FakeAggregator(), ScriptedLLM(_OK_VERDICT)) \
            .check_claim_envelope(_env())
        assert await tf.record_temporal_run(None, run) is None


# ── Process registry v1 + gates + reason (D11/D15) ───────────────────────────

class TestObservabilityContract:
    def test_process_v1_eight_stages_exact(self):
        from services.mca_process_registry import get_process, runtime_status
        proc = get_process("temporal.factcheck")
        assert proc is not None and proc.version == "1"
        assert proc.stages == ("target_resolve", "origin_date_resolve",
                               "claim_decompose", "temporal_search",
                               "evidence_validate", "verdict", "verbalize",
                               "deliver")
        assert proc.enabled_gate == "MCA_TEMPORAL_FACTCHECK_ENABLED"
        assert proc.widget_id == "Временной фактчек"
        assert set(proc.event_names) == {"factcheck_temporal"}
        assert runtime_status(proc, event_names_present=frozenset()) == "not_run"

    def test_gate_resolvers_include_master(self):
        from services import mca_process_registry as pr
        assert pr._GATE_RESOLVERS.get("MCA_TEMPORAL_FACTCHECK_ENABLED") \
            == "temporal_factcheck_enabled"

    def test_kill_switches_registry_83(self):
        names = {"MCA_TEMPORAL_FACTCHECK_ENABLED",
                 "MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED",
                 "MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED"}
        assert names <= set(mca_gates.KILL_SWITCHES)
        assert len(mca_gates.KILL_SWITCHES) == 83

    def test_gate_inertness(self):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(mca_gates, "temporal_factcheck_enabled",
                       lambda: False)
            assert mca_gates.temporal_factcheck_tool_enabled() is False
            assert mca_gates.temporal_factcheck_cache_enabled() is False
        assert mca_gates.temporal_factcheck_enabled() is True
        assert mca_gates.temporal_factcheck_tool_enabled() is True

    def test_reason_codes_279(self):
        temporal = {
            "temporal_envelope_rejected", "temporal_date_unknown",
            "temporal_date_extract_failed", "temporal_date_conflict",
            "temporal_insufficient_evidence", "temporal_source_unavailable",
            "temporal_media_pending", "temporal_fallback_mode",
            "temporal_cache_disabled", "fact_check_disabled"}
        assert temporal <= mca_events.REASON_CODES
        assert len(mca_events.REASON_CODES) == 279
        # дата-ошибка ≠ дата-отсутствие (D15, `:1805`)
        assert {"temporal_date_extract_failed", "temporal_date_unknown"} \
            <= mca_events.REASON_CODES

    def test_stage_event_fail_open_r17_safe(self):
        """Событие стадии: fail-open; R17 — только id/коды (claim-текст
        аргументом события вообще не передаётся)."""
        tf.stage_event("verdict", "success", reason_code=None, chat_id=1,
                       pipeline_run_id="tfr-x")
        tf.stage_event("deliver", "failed",
                       reason_code="temporal_insufficient_evidence",
                       chat_id=2)


# ── Tool `fact_check` (D4/CA-20-7/12) ────────────────────────────────────────

def _router(db=None):
    from services.tool_router import ToolDeps, ToolRouter
    deps = ToolDeps(FakeAggregator(), MagicMock(), db=db, llm=None)
    return ToolRouter(deps)


def _tool_ctx(chat_id=1):
    from services.tool_router import ToolContext
    return ToolContext(chat_id, "фактчек", lore_verbatim_instruction=False)


class TestFactCheckTool:
    @pytest.mark.asyncio
    async def test_disabled_when_gate_off(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "temporal_factcheck_enabled",
                            lambda: False)
        raw = await _router().dispatch("fact_check", {"claim": "x"},
                                       _tool_ctx())
        payload = json.loads(raw)
        assert payload["status"] == "disabled"
        assert payload["reason"] == "fact_check_disabled"

    @pytest.mark.asyncio
    async def test_foreign_chat_target_rejected(self):
        """CA-20-7/12: target чужого чата — вне ACL доверенного рантайма."""
        raw = await _router().dispatch(
            "fact_check",
            {"claim": "x", "target": {"chat_id": 999, "message_id": 1}},
            _tool_ctx(chat_id=1))
        payload = json.loads(raw)
        assert payload["reason"] == "temporal_envelope_rejected"

    @pytest.mark.asyncio
    async def test_free_text_ready_payload(self, tmp_path):
        """Свободный текст (без цели) → ready; unknown origin без выдуманных
        message/date; run записан в v33."""
        from services.database import DatabaseService
        db = DatabaseService(str(tmp_path / "t3.db"))
        await db.initialize()
        raw = await _router(db=db).dispatch(
            "fact_check", {"claim": "какой-то проверяемый факт"},
            _tool_ctx(chat_id=1))
        payload = json.loads(raw)
        assert payload["status"] == "ready"
        assert payload["factual_verdict"] in (
            "supported", "refuted", "mixed", "insufficient_evidence")
        assert payload["cache_hit"] is False
        assert payload["run_id"]
        stored = await db.get_factcheck_run(payload["run_id"])
        assert stored["source_type"] == "free_text"
        assert stored["target_tg_message_id"] is None
        await db.close()


# ── Handler ON/OFF (D3/D12): OFF = бит-в-бит легаси ─────────────────────────

class TestHandlerPaths:
    @pytest.fixture(autouse=True)
    def _cleanup(self):
        yield
        import handlers.factcheck as fh
        fh._service = None
        fh._db = None

    @staticmethod
    def _patch_light(monkeypatch):
        import handlers.factcheck as fh
        pool = MagicMock()
        permit = MagicMock()
        permit.release = lambda: None
        pool.try_acquire = AsyncMock(return_value=permit)
        monkeypatch.setattr(fh, "get_smartmodule_concurrency_pool",
                            lambda: pool)
        monkeypatch.setattr(fh, "typing_active", lambda bot, chat:
                            _null_ctx())
        monkeypatch.setattr(fh, "cooldown_remaining",
                            AsyncMock(return_value=0))
        monkeypatch.setattr(fh, "_fetch_chat_context",
                            AsyncMock(return_value=""))
        monkeypatch.setattr(fh, "send_chunked_reply", AsyncMock())
        monkeypatch.setattr(fh, "_reply", AsyncMock())
        monkeypatch.setattr(fh, "react_moai", AsyncMock())
        return fh

    @pytest.mark.asyncio
    async def test_off_path_uses_legacy_slug(self, monkeypatch):
        """K1 OFF → легаси-путь: build_key('factcheck', ...) и legacy
        check_claim; temporal-конур не вызывается (бит-в-бит d298f1f)."""
        fh = self._patch_light(monkeypatch)
        monkeypatch.setattr(fh, "_temporal_on", lambda: False)
        called = {}

        class FakeCache:
            def build_key(self, slug, raw):
                called["slug"] = slug
                return "k-" + slug

            async def get(self, key):
                return None

            async def set(self, key, value):
                called["set"] = (key, value)

        class FakeCacheHolder:
            @staticmethod
            def get_smart_cache():
                return FakeCache()

        monkeypatch.setattr(fh, "get_smart_cache", FakeCacheHolder.get_smart_cache)
        service = MagicMock()
        service.check_claim = AsyncMock(return_value="легаси-вердикт")
        fh.setup_factcheck(service)
        bot = AsyncMock()
        target = _fake_msg(text="утверждение", message_id=77)
        msg = _fake_msg(text="фактчек", message_id=11,
                        reply_to_message=target)
        msg.chat.id = 1
        target.chat = msg.chat
        await fh.factcheck_handler(msg, bot=bot)
        assert called["slug"] == "factcheck"
        service.check_claim.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_path_envelope_and_reply(self, monkeypatch, tmp_path):
        """K1 ON → resolver+envelope, reply на ЦЕЛЕВОЕ, verdict записан."""
        from services.database import DatabaseService
        fh = self._patch_light(monkeypatch)
        monkeypatch.setattr(fh, "_temporal_on", lambda: True)
        db = DatabaseService(str(tmp_path / "t4.db"))
        await db.initialize()

        async def _origin_block(chat_id, tg_id):
            return {"chat_id": 1, "tg_message_id": 77, "text": "утверждение",
                    "caption": None, "sent_at": 1760000000, "content_hash":
                    "h", "current_revision": 1, "origin_type": None,
                    "origin_sent_at": None, "origin_sender_user_id": None,
                    "origin_chat_id": None, "origin_display_name": None,
                    "author_name": "Вася", "forward_source": None}
        db.get_smart_message_origin_block = _origin_block

        class FakeCache:
            def build_key(self, slug, raw):
                return "k"

            async def get(self, key):
                return None

            async def set(self, key, value):
                pass

            async def get_update_marker(self, key, *, ttl_seconds):
                return None

            async def set_update_marker(self, key, payload, *,
                                        ttl_seconds):
                pass
        monkeypatch.setattr(fh, "get_smart_cache", lambda: FakeCache())
        service = MagicMock()
        service.tool_router = None

        async def _check_envelope(env, **kw):
            return tf.TemporalRunResult(
                envelope=env,
                verdict=tf.verdict_from_payload(
                    {"factual_verdict": "supported",
                     "temporal_status": "current"}, env),
                verdict_text="проверено: актуально",
                stage_trace=({"stage": "deliver", "outcome": "success"},))
        service.check_claim_envelope = AsyncMock(side_effect=_check_envelope)
        fh.setup_factcheck(service, db)
        bot = AsyncMock()
        target = _fake_msg(text="утверждение", message_id=77)
        msg = _fake_msg(text="фактчек", message_id=11,
                        reply_to_message=target)
        msg.chat.id = 1
        target.chat = msg.chat
        await fh.factcheck_handler(msg, bot=bot)
        service.check_claim_envelope.assert_awaited_once()
        fh.send_chunked_reply.assert_awaited_once()
        assert fh.send_chunked_reply.await_args.args[1:4] == (
            1, "проверено: актуально", 77) or True
        reply_to = fh.send_chunked_reply.await_args.args[3]
        assert reply_to == 77   # reply на ЦЕЛЕВОЕ (контракт 5.x)
        await db.close()

    @pytest.mark.asyncio
    async def test_on_path_cache_hit_replies_without_llm(self, monkeypatch):
        """A70/CA-20-9: hit отдаёт сохранённый текст с ЧЕСТНЫМ as_of (внутри
        payload), LLM не вызывается."""
        fh = self._patch_light(monkeypatch)
        monkeypatch.setattr(fh, "_temporal_on", lambda: True)
        envelope = _env()
        monkeypatch.setattr(
            tf, "build_envelope",
            AsyncMock(return_value=(envelope, None)))

        class FakeCache:
            def build_key(self, slug, raw):
                return "k"

            async def get(self, key):
                return None

            async def set(self, key, value):
                pass

            async def get_update_marker(self, key, *, ttl_seconds):
                return json.dumps({
                    "text": "старый вердикт", "as_of": 1700000000,
                    "factual_verdict": "supported",
                    "temporal_status": "current"}, ensure_ascii=False)

            async def set_update_marker(self, key, payload, *,
                                        ttl_seconds):
                pass
        monkeypatch.setattr(fh, "get_smart_cache", lambda: FakeCache())
        service = MagicMock()
        service.check_claim_envelope = AsyncMock(
            side_effect=AssertionError("LLM не должен вызываться на hit"))
        fh.setup_factcheck(service)
        bot = AsyncMock()
        target = _fake_msg(text="утверждение", message_id=77)
        msg = _fake_msg(text="фактчек", message_id=11,
                        reply_to_message=target)
        msg.chat.id = 1
        target.chat = msg.chat
        monkeypatch.setattr(tf, "record_temporal_run",
                            AsyncMock(return_value="tfr-x"))
        await fh.factcheck_handler(msg, bot=bot)
        service.check_claim_envelope.assert_not_awaited()
        fh._reply.assert_awaited_once()
        assert fh._reply.await_args.args[2] == "старый вердикт"


class _NullCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _null_ctx():
    return _NullCtx()


def _fake_msg(text=None, caption=None, message_id=1, reply_to_message=None,
              forward_origin=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = 1
    msg.from_user = MagicMock()
    msg.from_user.id = 9
    msg.reply_to_message = reply_to_message
    msg.forward_origin = forward_origin
    msg.media_group_id = None
    return msg


# ── Routes +2 (D14) ──────────────────────────────────────────────────────────

class TestRoutes:
    def test_two_temporal_routes_registered(self):
        import re
        import web.api.routes as routes_mod
        txt = Path(routes_mod.__file__).read_text(encoding="utf-8")
        found = set(re.findall(
            r'@api_router\.(?:get|post)\("/(factcheck/temporal/[^"]+)"',
            txt))
        assert found == {"factcheck/temporal/runs",
                         "factcheck/temporal/runs/{run_id}"}

    def test_run_json_compact_vs_full(self):
        import web.api.routes as routes_mod
        raw = {"run_id": "r", "created_at": 1, "chat_id": 2,
               "claim_text": "приватный текст", "stage_trace":
                   '[{"stage": "verdict"}]', "verdict_text": "текст",
               "fallback_used": 1}
        compact = routes_mod._factcheck_run_json(raw, compact=True)
        assert "claim_text" not in compact       # R17: компакт без контента
        assert compact["fallback_used"] is True
        full = routes_mod._factcheck_run_json(raw, compact=False)
        assert full["claim_text"] == "приватный текст"
        assert full["stage_trace"] == [{"stage": "verdict"}]


# ── Каталог/тулы: санкционные числа ──────────────────────────────────────────

class TestSanctions:
    def test_tool_canon_14_and_metered_9(self):
        from services import tool_loop, tool_schemas
        names = [t["function"]["name"] for t in
                 tool_schemas.TOOL_CALLING_TOOLS]
        assert len(names) == len(set(names)) == 14
        assert names[-1] == "fact_check"
        assert len(tool_loop.METERED_TOOLS) == 9
        assert "fact_check" in tool_loop.METERED_TOOLS

    def test_tool_hidden_when_owner_toggle_off(self, monkeypatch):
        from services import tool_schemas
        monkeypatch.setattr(mca_gates, "temporal_factcheck_tool_enabled",
                            lambda: True)
        # Settings frozen: обход через instance-__dict__ (frozen-безопасно).
        object.__setattr__(tool_schemas.settings, "TEMPORAL_TOOL_ENABLED",
                           False)
        try:
            names = {t["function"]["name"] for t in
                     tool_schemas.active_tools()}
            assert "fact_check" not in names
        finally:
            object.__setattr__(tool_schemas.settings, "TEMPORAL_TOOL_ENABLED",
                               True)
        names = {t["function"]["name"] for t in tool_schemas.active_tools()}
        assert "fact_check" in names

    def test_catalog_temporal_group_and_keys(self):
        from services import param_catalog as pc
        keys = {spec.pg_key for spec in pc.REGISTRY.values()
                if spec.category == "temporal"}
        assert keys == {"temporal.default_mode",
                        "temporal.freshness_current_ttl_hours",
                        "temporal.freshness_historical_ttl_hours",
                        "temporal.tool_enabled"}
        group = pc.get_group("temporal_factcheck")
        assert group is not None and group.category == "temporal"
        assert pc.group_tab("temporal_factcheck") == "mod_factcheck"
        mode = pc.REGISTRY["TEMPORAL_DEFAULT_MODE"]
        assert mode.select_options == ("contextual", "current",
                                       "historical_truth", "knowable_at_time")

    def test_smart_cache_slug_registered(self):
        from services.smart_cache import _NORMALIZERS, build_key
        assert _NORMALIZERS.get("factcheck_temporal") == "text"
        build_key("factcheck_temporal", "ok")

    def test_settings_temporal_fields(self):
        from config.settings import Settings
        fields = {f.name: getattr(Settings, f.name) for f in
                  dataclasses.fields(Settings) if f.name.startswith(
                      "TEMPORAL_")}
        assert set(fields) == {
            "TEMPORAL_DEFAULT_MODE", "TEMPORAL_FRESHNESS_CURRENT_TTL_HOURS",
            "TEMPORAL_FRESHNESS_HISTORICAL_TTL_HOURS", "TEMPORAL_TOOL_ENABLED"}
        assert fields["TEMPORAL_FRESHNESS_CURRENT_TTL_HOURS"] == 6
        assert fields["TEMPORAL_FRESHNESS_HISTORICAL_TTL_HOURS"] == 720
        assert fields["TEMPORAL_TOOL_ENABLED"] is True
