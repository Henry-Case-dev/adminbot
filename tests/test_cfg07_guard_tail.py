"""CFG-07CG-TAIL — runtime egress-guard на outbound-швах фактчека v2.

Закрывает хвост 07C.1–.6 (reuse-аудит 07cg-reuse-audit.md §3) и
NONBLOCKING-наблюдения 1/3/4 review-07cg.md:

* delivery-шов: outbound-payload (после Writer/кеш-хита, ДО сериализации
  renderer'ом) проходит `public_speech_guard` — FORBIDDEN-маркеры и
  overclaim срезаются детерминированно (факты/числа целы), honesty-
  классы и чистые тексты проходят байт-в-байт;
* вырожденный остаток → честный статус: enum-вердикт из реального
  CheckedVerdict либо молчание с 🗿 — fail-soft не выдаёт фиктивно
  уверенный вердикт (07C.4);
* short_reply/no_claim/attribution_miss/busy/error-швы: пулы проходят
  байт-в-байт, LLM-реплика чистится, сбой guard'а не рвёт доставку;
* tool_route v2 (`fact_check`): NL-верdict tool-ответа чистится,
  машинный JSON-конверт не трогается; OFF → guard не вызывается,
  payload байт-в-байт прежний;
* админ-контекст (наблюдение 4): легитимная техсправка не режется;
* honest_limitation в allow-пути (наблюдение 3): «проверил — не нашёл
  подтверждений» (PC-01) не режется.

OFF-паритет: весь guard живёт в v2-ветке за FACTCHECK_PIPELINE_V2_ENABLED
(handler dispatch уже pinned тестами CFG-06; здесь — tool-route OFF).

Всё на моках: сеть, LLM и реальные чаты не используются.

TEST-LIFECYCLE: CONTRACT owner=CFG-07CG-TAIL
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from config.settings import settings
from services import public_speech_guard as psg
from services.factcheck_orchestrator import (
    CheckedVerdict,
    FactcheckPresentation,
    _apply_delivery_guard,
    _guard_outbound,
    pipeline_v2_enabled,
    run_factcheck,
)
from services.factcheck_renderer import _NO_LINKS_NOTICE
from services.llm_client import LLMBadResponseError
from services.smartmodule_phrases import (
    FACTCHECK_ATTRIBUTION_MISS_PHRASES,
    FACTCHECK_CLARIFY_PHRASES,
    FACTCHECK_ERROR_PHRASES,
    FACTCHECK_NO_CLAIM_PHRASES,
    LLM_ERROR_PHRASES,
    SMARTMODULE_BUSY_PHRASES,
)

CHAT_ID = -100777
TARGET_TG = 9200
TRIGGER_TG = 9201

CLAIM_PLAIN = "дрожжи — это грибы"

DIRTY_VERDICT = ("Тезис не подтверждается. По моим логам, "
                 "источники врут.")
DIRTY_TOOL_VERDICT = "Подтверждено. По моим логам всё сошлось."
OVERCLAIM_VERDICT = ("Я проверил всё в интернете: тезис "
                     "не подтверждается.")


# ── Харнес (моки, без сети/LLM/реальных чатов) ──────────────────────────────

class _Row(dict):
    pass


class FakeDB:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def get_messages_around(self, chat_id, tg, before, after):
        return list(self._rows)

    async def get_recent_messages(self, chat_id, limit):
        return list(self._rows[-limit:]) if limit else []

    async def get_smart_message_origin_block(self, chat_id, tg):
        raise RuntimeError("no origin row")


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value

    async def get_update_marker(self, key, *, ttl_seconds):
        return None

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.store[key] = payload

    def build_key(self, slug, raw):
        from services.smart_cache import build_key, normalize_text
        return build_key(slug, normalize_text(str(raw)))


class FakeBot:
    id = 862000000

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 555})()

    async def send_chat_action(self, chat_id, action, **kw):
        return True

    async def set_message_reaction(self, chat_id, message_id, **kw):
        return True


class SpyService:
    """Фиксирует проверки; опционально текст ответа/исключение/LLM."""

    def __init__(self, text: str | None = None, exc: Exception | None = None):
        self.text = text
        self.exc = exc
        self.llm = None
        self.check_calls = []

    async def check_claim(self, target_text, user_hint, forward_source, *,
                          chat_id=None, chat_context=None,
                          search_results=None):
        self.check_calls.append({"target_text": target_text})
        if self.exc is not None:
            raise self.exc
        return self.text if self.text is not None else \
            "Тезис подтверждается частично по найденным источникам."


class _FakeLLM:
    def __init__(self, text: str | None = None, exc: Exception | None = None):
        self.text = text
        self.exc = exc

    async def generate(self, messages, *, module=None, step=None):
        if self.exc is not None:
            raise self.exc
        return self.text


def _req(claim: str = CLAIM_PLAIN):
    from services.factcheck_orchestrator import FactcheckRequest
    return FactcheckRequest(
        chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
        target_tg_message_id=TARGET_TG, target_text=claim, kind="reply")


@pytest.fixture
def v2_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


@pytest.fixture
def v2_off():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


def _patch_gate(monkeypatch, decision_str: str = "needs_context"):
    """Детерминированный suitability-gate: тезис есть, нужен поиск."""
    from services import factcheck_suitability as fsg
    decision = fsg.SuitabilityDecision(
        decision=decision_str, claim_type="checkable_fact",
        claim_items=(), scope="web", reason_code=None, confidence=0.9,
        target_ref={"chat_id": CHAT_ID})

    async def fake_eval(db_, chat_id, **kwargs):
        return decision, None

    monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_eval)


async def _run_plain(svc, bot, monkeypatch, claim: str = CLAIM_PLAIN):
    _patch_gate(monkeypatch)
    await run_factcheck(_req(claim), service=svc, db=None, bot=bot,
                        cache=FakeCache())


# ════════════════════════════════════════════════════════════════════════════
# 1. Guard-семантика (public_speech_guard.guard_public_text)
# ════════════════════════════════════════════════════════════════════════════

class TestGuardSemantics:
    def test_clean_payload_byte_identical(self):
        """Чистый payload проходит байт-в-байт, без флагов."""
        text = "Тезис подтверждается по трём ссылкам, вот первоисточник."
        res = psg.guard_public_text(text)
        assert res.text == text
        assert res.changed is False
        assert res.findings == ()
        assert res.repaired is True

    def test_honesty_classes_pass_byte_identical(self):
        """Honesty-классы (отказ/недоступность/ограничение) не режутся."""
        for text in (FACTCHECK_NO_CLAIM_PHRASES[0],
                     FACTCHECK_ERROR_PHRASES[0],
                     "проверил — не нашёл подтверждений",      # PC-01
                     _NO_LINKS_NOTICE):
            res = psg.guard_public_text(text)
            assert res.text == text, text
            assert res.changed is False and res.findings == (), text

    def test_honest_limitation_in_allow_path(self):
        """Наблюдение 3 review-07cg: honest_limitation в allow-пути
        honest_failure_is_allowed; PC-01 не режется guard'ом."""
        pc01 = "проверил — не нашёл подтверждений"
        assert psg.is_honest_limitation(pc01)
        assert psg.honest_failure_is_allowed(pc01)
        assert psg.guard_public_text(pc01).text == pc01
        assert psg.honest_failure_is_allowed(_NO_LINKS_NOTICE)

    def test_marker_payload_cut_facts_kept(self):
        """FORBIDDEN-маркер → срез + findings; факты/структура целы."""
        res = psg.guard_public_text(DIRTY_VERDICT)
        assert "по моим логам" in res.findings
        assert res.changed is True and res.repaired is True
        assert "по моим логам" not in res.text.lower()
        assert "не подтверждается" in res.text
        assert "источники врут" in res.text

    def test_overclaim_payload_cut_facts_kept(self):
        """07D.2: «проверил всё в интернете» → срез + флаг, факт цел."""
        res = psg.guard_public_text(OVERCLAIM_VERDICT)
        assert res.findings == ("overclaim:total_verification",)
        assert "всё в интернете" not in res.text.lower()
        assert "не подтверждается" in res.text

    def test_unrepairable_payload_reports_empty(self):
        """Сплошная метаречь → вырожденный остаток: text="" (шов обязан
        подставить честный класс), repaired=False."""
        res = psg.guard_public_text("по моим логам")
        assert res.text == ""
        assert res.changed is True and res.repaired is False
        assert res.findings == ("по моим логам",)

    def test_admin_context_passthrough_dirty_text(self):
        """Наблюдение 4 review-07cg: в явном админ-контексте техсправка
        (даже с маркером MB-01) не режется."""
        dirty = "В логах видно, что фактура пустая — модуль такой."
        res = psg.guard_public_text(dirty, admin_context=True)
        assert res.text == dirty
        assert res.admin_context is True and res.findings == ()

    def test_guard_fail_soft_on_internal_error(self, monkeypatch):
        """Внутренний сбой guard'а → исходный текст, доставки не нет."""
        def boom(*a, **kw):
            raise RuntimeError("guard down")

        monkeypatch.setattr(psg, "find_backstage_metatext", boom)
        res = psg.guard_public_text(DIRTY_VERDICT)
        assert res.text == DIRTY_VERDICT
        assert res.changed is False and res.findings == ()

    @pytest.mark.parametrize("text", [None, "", 123, "   "])
    def test_guard_never_raises_on_degenerate_input(self, text):
        res = psg.guard_public_text(text)
        assert res.findings == () and res.changed is False


# ════════════════════════════════════════════════════════════════════════════
# 2. Delivery-шов: presentation/рендер (07C.1/.4)
# ════════════════════════════════════════════════════════════════════════════

class TestDeliverySeam:
    @pytest.mark.asyncio
    async def test_dirty_verdict_cleaned_facts_kept(self, v2_on,
                                                    monkeypatch):
        """Грязный вердикт Writer'а: маркер срезан, факты доставлены,
        delivery не сорвался."""
        svc = SpyService(text=DIRTY_VERDICT)
        bot = FakeBot()
        await _run_plain(svc, bot, monkeypatch)
        assert len(bot.sent) == 1
        text = bot.sent[0]["text"]
        assert "по моим логам" not in text.lower()
        assert "не подтверждается" in text
        assert "источники врут" in text

    @pytest.mark.asyncio
    async def test_honesty_class_verdict_byte_identical(self, v2_on,
                                                        monkeypatch):
        """Honesty-класс (PC-01) как вердикт: доставляется байт-в-байт."""
        pc01 = "проверил — не нашёл подтверждений"
        svc = SpyService(text=pc01)
        bot = FakeBot()
        await _run_plain(svc, bot, monkeypatch)
        assert bot.sent[0]["text"] == pc01

    @pytest.mark.asyncio
    async def test_guard_crash_fail_soft_delivery_intact(self, v2_on,
                                                         monkeypatch):
        """Fail-soft шва: сбой guard'а → исходный payload доставлен."""

        def boom(*a, **kw):
            raise RuntimeError("guard down")

        monkeypatch.setattr(psg, "guard_public_text", boom)
        svc = SpyService(text=DIRTY_VERDICT)
        bot = FakeBot()
        await _run_plain(svc, bot, monkeypatch)
        assert len(bot.sent) == 1
        assert "по моим логам" in bot.sent[0]["text"].lower()

    def test_apply_guard_repaired_keeps_enum(self):
        """Урезанный payload сохраняет enum-вердикт (реальный статус)."""
        presentation = FactcheckPresentation(text=DIRTY_VERDICT)
        verdict = CheckedVerdict(verdict_text=DIRTY_VERDICT,
                                 route="legacy_single",
                                 factual_verdict="refuted")
        pres2, verdict2 = _apply_delivery_guard(presentation, verdict)
        assert "по моим логам" not in pres2.text.lower()
        assert "не подтверждается" in pres2.text
        assert verdict2.factual_verdict == "refuted"

    def test_apply_guard_unrepairable_enum_status_only(self):
        """Вырожденный остаток + enum → честный статус без фиктивного
        тела: доставляется только заголовок реального enum."""
        presentation = FactcheckPresentation(text="по моим логам")
        verdict = CheckedVerdict(verdict_text="по моим логам",
                                 route="envelope_temporal",
                                 factual_verdict="refuted")
        pres2, verdict2 = _apply_delivery_guard(presentation, verdict)
        assert pres2.text == "Не подтверждается"
        assert verdict2.factual_verdict is None   # renderer не задублирует

    def test_apply_guard_unrepairable_no_enum_raises(self):
        """Вырожденный остаток без enum → LLMBadResponseError (шов 🗿),
        НЕ фиктивно уверенный вердикт."""
        presentation = FactcheckPresentation(text="по моим логам")
        verdict = CheckedVerdict(verdict_text="по моим логам",
                                 route="legacy_single")
        with pytest.raises(LLMBadResponseError):
            _apply_delivery_guard(presentation, verdict)


# ════════════════════════════════════════════════════════════════════════════
# 3. Short-reply / no_claim / attribution-швы и байт-паритет пулов
# ════════════════════════════════════════════════════════════════════════════

class TestShortReplyAndPools:
    @pytest.mark.asyncio
    async def test_ambiguous_llm_reply_guarded(self, v2_on, monkeypatch):
        """ambiguous → persona-реплика: LLM-метаречь срезается, смысл цел."""
        from services import factcheck_suitability as fsg
        decision = fsg.SuitabilityDecision(
            decision=fsg.DECISION_AMBIGUOUS, claim_type="ambiguous",
            claim_items=(), scope="none", reason_code="ambiguous",
            confidence=0.9, target_ref={"chat_id": CHAT_ID})

        async def fake_eval(db_, chat_id, **kwargs):
            return decision, None

        monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_eval)
        svc = SpyService()
        svc.llm = _FakeLLM("По моим логам тут несколько тем, "
                           "уточни тезис.")
        bot = FakeBot()
        await run_factcheck(_req(), service=svc, db=None, bot=bot,
                            cache=FakeCache())
        assert len(bot.sent) == 1
        text = bot.sent[0]["text"]
        assert "по моим логам" not in text.lower()
        assert "уточни тезис" in text

    @pytest.mark.asyncio
    async def test_short_reply_llm_down_falls_back_to_pool(self, v2_on,
                                                           monkeypatch):
        """LLM недоступна → прежний честный пул (поведение не изменено)."""
        from services import factcheck_suitability as fsg
        decision = fsg.SuitabilityDecision(
            decision=fsg.DECISION_AMBIGUOUS, claim_type="ambiguous",
            claim_items=(), scope="none", reason_code="ambiguous",
            confidence=0.9, target_ref={"chat_id": CHAT_ID})

        async def fake_eval(db_, chat_id, **kwargs):
            return decision, None

        monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_eval)
        svc = SpyService()
        svc.llm = _FakeLLM(exc=RuntimeError("llm down"))
        bot = FakeBot()
        await run_factcheck(_req(), service=svc, db=None, bot=bot,
                            cache=FakeCache())
        assert bot.sent[0]["text"] in FACTCHECK_CLARIFY_PHRASES

    def test_canned_pools_pass_guard_byte_identical(self):
        """Каждый зарегистрированный честный пул проходит шов-обёртку
        байт-в-байт (OFF-паритет пулов через guard)."""
        pools = (FACTCHECK_NO_CLAIM_PHRASES,
                 FACTCHECK_ATTRIBUTION_MISS_PHRASES,
                 FACTCHECK_ERROR_PHRASES, LLM_ERROR_PHRASES,
                 SMARTMODULE_BUSY_PHRASES, FACTCHECK_CLARIFY_PHRASES)
        for pool in pools:
            for phrase in pool:
                assert _guard_outbound(phrase, where="unit") == phrase, \
                    phrase


# ════════════════════════════════════════════════════════════════════════════
# 4. tool_route v2 (`fact_check`): NL-верdict чистится, JSON цел; OFF-паритет
# ════════════════════════════════════════════════════════════════════════════

_READY_KEYS = {"status", "reason", "claim", "factual_verdict",
               "temporal_status", "evaluated_period", "assessment_mode",
               "as_of", "date_source", "original_published_at",
               "repost_received_at", "uncertainty", "run_id", "cache_hit",
               "verdict"}

TOOL_CLAIM = "Байкал — самое глубокое озеро в мире"


class _FakeToolService:
    verdict_text = "Подтверждено."
    calls: list = []

    def __init__(self, search, llm):
        pass

    async def check_claim_envelope(self, envelope, **kwargs):
        type(self).calls.append((envelope, kwargs))
        from services import temporal_factcheck as tf
        verdict = tf.verdict_from_payload(
            {"factual_verdict": "supported", "temporal_status": "unknown"},
            envelope)
        return tf.TemporalRunResult(envelope=envelope, verdict=verdict,
                                    verdict_text=type(self).verdict_text)


class _FeedCtx:
    def __init__(self, feed):
        self._feed = feed

    def render_feed(self, **kwargs):
        return self._feed


@pytest_asyncio.fixture
async def tool_db(tmp_path):
    from services.database import DatabaseService
    db = DatabaseService(str(tmp_path / "cfg07_guard_tail.db"))
    await db.initialize()
    yield db
    await db.close()


@pytest.fixture(autouse=True)
def _fake_tool_service(monkeypatch):
    _FakeToolService.calls = []
    monkeypatch.setattr("services.factcheck_service.FactCheckService",
                        _FakeToolService)
    yield


def _patch_tool_gate(monkeypatch):
    from services import factcheck_suitability as fsg
    decision = fsg.SuitabilityDecision(
        decision="checkable_in_context", claim_type="checkable_fact",
        claim_items=(), scope="web", reason_code=None, confidence=0.9,
        target_ref={"chat_id": 7})

    async def fake_eval(db_, chat_id, **kwargs):
        return decision, _FeedCtx("FEED")

    monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_eval)


async def _dispatch_tool(db, claim=TOOL_CLAIM):
    from services.tool_router import ToolContext, ToolDeps, ToolRouter
    deps = ToolDeps(MagicMock(), MagicMock(), db=db, llm=MagicMock())
    router = ToolRouter(deps)
    raw = await router.dispatch("fact_check", {"claim": claim},
                                ToolContext(7, "фактчек",
                                            lore_verbatim_instruction=False))
    return json.loads(raw)


class TestToolRouteSeam:
    @pytest.mark.asyncio
    async def test_v2_dirty_verdict_cleaned_json_intact(
            self, monkeypatch, tool_db, v2_on):
        """v2 ON: NL-верdict чистится; машинный JSON-конверт не тронут
        (claim/reason/статусы как были)."""
        _patch_tool_gate(monkeypatch)
        _FakeToolService.verdict_text = DIRTY_TOOL_VERDICT
        payload = await _dispatch_tool(tool_db)
        assert payload["status"] == "ready"
        assert set(payload) == _READY_KEYS
        assert "по моим логам" not in payload["verdict"].lower()
        assert "Подтверждено" in payload["verdict"]
        assert "всё сошлось" in payload["verdict"]
        assert payload["claim"] == TOOL_CLAIM   # машинные поля не тронуты

    @pytest.mark.asyncio
    async def test_v2_clean_verdict_byte_identical(
            self, monkeypatch, tool_db, v2_on):
        _patch_tool_gate(monkeypatch)
        _FakeToolService.verdict_text = "Подтверждено: источник согласен."
        payload = await _dispatch_tool(tool_db)
        assert payload["verdict"] == "Подтверждено: источник согласен."

    @pytest.mark.asyncio
    async def test_v2_unrepairable_honest_failed(
            self, monkeypatch, tool_db, v2_on):
        """Сплошная метаречь → структурный failed БЕЗ ретранслируемой
        метаречи и БЕЗ записи успешного прогона."""
        _patch_tool_gate(monkeypatch)
        _FakeToolService.verdict_text = "по моим логам"
        payload = await _dispatch_tool(tool_db)
        assert payload == {"status": "failed",
                           "reason": "temporal_insufficient_evidence"}

    @pytest.mark.asyncio
    async def test_off_parity_guard_not_applied(
            self, monkeypatch, tool_db, v2_off):
        """OFF: guard не вызывается вовсе, payload байт-в-байт прежний."""
        from services import factcheck_suitability as fsg

        async def must_not_run(*a, **kw):
            raise AssertionError("gate must not run with v2 OFF")

        monkeypatch.setattr(fsg, "evaluate_with_expansion", must_not_run)
        guard_calls: list = []
        real_guard = psg.guard_public_text

        def spy(text, **kw):
            guard_calls.append(text)
            return real_guard(text, **kw)

        monkeypatch.setattr(psg, "guard_public_text", spy)
        _FakeToolService.verdict_text = DIRTY_TOOL_VERDICT
        payload = await _dispatch_tool(tool_db)
        assert payload["status"] == "ready"
        assert guard_calls == []                 # guard в OFF-ветке живёт?
        assert payload["verdict"] == DIRTY_TOOL_VERDICT   # байт-в-байт


# ════════════════════════════════════════════════════════════════════════════
# 5. OFF-паритет: guard-швы достижимы только в v2-контуре
# ════════════════════════════════════════════════════════════════════════════

class TestOffParity:
    def test_pipeline_off_guard_seams_unreachable(self, v2_off):
        """OFF (default): рубильник выключен → v2-швы (весь guard живёт
        внутри run_factcheck/_fact_check v2-ветки) недостижимы; handler-
        dispatch за этим же гейтом pinned тестами CFG-06
        (test_pipeline_v2_default_off_and_hot_prio)."""
        assert pipeline_v2_enabled() is False
        import handlers.factcheck as hfc
        assert hfc._pipeline_v2_enabled() is False
