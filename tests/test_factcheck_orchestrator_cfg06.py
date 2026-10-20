"""CFG-06 W3 — единый оркестратор + фриз схем (06H, join-barrier).

TEST-LIFECYCLE: CONTRACT owner=CFG-06

Контракты:
  * фриз схем: наборы полей FactcheckRequest/FactcheckPlan/EvidenceRef/
    EvidenceMap/CheckedVerdict/FactcheckPresentation зафиксированы тестами —
    W4∥W5 строят от одних схем; изменение = осознанный bump;
  * миграционный флаг default OFF → байт-паритет прод-пути 2.58.98;
  * один контракт маршрутов: envelope-ветка и legacy-ветка вызывают сервис
    одними и теми же аргументами, что прод-путь (байт-паритет legacy-ветки);
  * egress-whitelist: служебные поля CheckedVerdict физически отсутствуют
    в FactcheckPresentation; латиница-маркеры срезаются (негативный тест);
  * шов UNIFIED-CORE: персона-реплика несёт speech_owner_block ПОСЛЕДНИМ
    блоком system-сообщения;
  * gate-маршруты (no_claim/ambiguous) отвечают ДО платного поиска —
    сервис проверки не вызывается.
"""
import asyncio
import json

import pytest

from config.settings import settings
from handlers import factcheck as hfc
from services import factcheck_orchestrator as orch
from services import smart_cache as sc

CHAT_ID = -100444
TARGET_TG = 9100
TRIGGER_TG = 9101


class FakeDB:
    def __init__(self, rows=None, origin_row=None):
        self._rows = rows or []
        self._origin = origin_row
        self.queries = []

    async def get_messages_around(self, chat_id, tg, before, after):
        self.queries.append(("around", chat_id, before, after))
        return list(self._rows)

    async def get_recent_messages(self, chat_id, limit):
        self.queries.append(("recent", chat_id, limit))
        return list(self._rows[-limit:]) if limit else []

    async def get_smart_message_origin_block(self, chat_id, tg):
        self.queries.append(("origin", chat_id, tg))
        if self._origin is None:
            raise RuntimeError("no origin row")
        return dict(self._origin)


class FakeCache:
    def __init__(self):
        self.store = {}
        self.markers = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value

    async def get_update_marker(self, key, *, ttl_seconds):
        return self.markers.get(key)

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.markers[key] = payload

    def build_key(self, slug, raw):
        from services.smart_cache import build_key, normalize_text
        return build_key(slug, normalize_text(str(raw)))


class FakeLLM:
    def __init__(self, reply="уточни, какой тезис проверить"):
        self.reply = reply
        self.calls = []

    async def generate(self, messages, **kw):
        self.calls.append({"messages": messages, **kw})
        return self.reply


class FakeService:
    """Фейковый FactCheckService: проверяет, ЧТО вызвано и с чем."""

    def __init__(self, llm=None, verdict="Вердикт легаси-ветки",
                 envelope_text="Вердикт envelope-ветки"):
        self.llm = llm or FakeLLM()
        self.verdict = verdict
        self.envelope_text = envelope_text
        self.check_claim_calls = []
        self.envelope_calls = []

    async def check_claim(self, target_text, user_hint, forward_source, *,
                          chat_id=None, chat_context=None,
                          search_results=None):
        self.check_claim_calls.append({
            "target_text": target_text, "user_hint": user_hint,
            "forward_source": forward_source, "chat_id": chat_id,
            "chat_context": chat_context, "search_results": search_results})
        return self.verdict

    async def check_claim_envelope(self, envelope, *, chat_context=None):
        self.envelope_calls.append({"envelope": envelope,
                                    "chat_context": chat_context})
        from services.temporal_factcheck import (
            TemporalClaimEnvelope, TemporalRunResult, TemporalVerdict)
        verdict = TemporalVerdict(
            factual_verdict="refuted", temporal_status="current",
            evaluated_period={"from": 100, "to": 200, "precision": "day"},
            assessment_mode="contextual", as_of=1760900000,
            evidence_refs=("ev-1",), reason=None)
        return TemporalRunResult(
            envelope=envelope, verdict=verdict,
            verdict_text=self.envelope_text,
            evidence_rows=({"evidence_id": "ev-1",
                            "url": "https://example.org/src",
                            "support": "подтверждение", "source_kind":
                            "secondary", "published_at": None},),
            fallback_used=False)


class FakeBot:
    id = 862000000                      # aiogram ChatActionSender логирует bot.id

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 555})()

    async def send_chat_action(self, chat_id, action, **kw):
        # aiogram ChatActionSender (typing_active) — мгновенный no-op
        return True


@pytest.fixture
def v2_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


@pytest.fixture
def w1w2_off():
    olds = (getattr(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", False),
            getattr(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", False))
    object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", False)
    yield
    object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", olds[0])
    object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", olds[1])


def _req(claim="в килякете выпало 120 мм осадков за сутки"):
    return orch.FactcheckRequest(
        chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
        target_tg_message_id=TARGET_TG, target_text=claim,
        kind="reply")


# ── Фриз схем (join-barrier) ─────────────────────────────────────────────────

class TestSchemaFreeze:
    def test_request_fields_frozen(self):
        assert tuple(f.name for f in __import__("dataclasses").fields(
            orch.FactcheckRequest)) == (
            "chat_id", "trigger_tg_message_id", "target_tg_message_id",
            "target_text", "user_hint", "forward_source", "kind",
            "source_type", "default_mode")

    def test_plan_fields_frozen(self):
        import dataclasses
        assert tuple(f.name for f in dataclasses.fields(
            orch.FactcheckPlan)) == (
            "route", "context_mode", "scope", "temporal_hint", "cache_slug",
            "fallback_allowed", "plan_version")

    def test_evidence_fields_frozen(self):
        import dataclasses
        assert tuple(f.name for f in dataclasses.fields(
            orch.EvidenceRef)) == (
            "evidence_id", "url", "support", "source_kind", "published_at")
        assert tuple(f.name for f in dataclasses.fields(
            orch.EvidenceMap)) == ("refs", "allowlist")

    def test_checked_verdict_fields_frozen(self):
        import dataclasses
        assert tuple(f.name for f in dataclasses.fields(
            orch.CheckedVerdict)) == (
            "verdict_text", "route", "factual_verdict", "temporal_status",
            "evaluated_period", "uncertainty", "evidence", "reason_code",
            "as_of", "gate_version", "fallback_used", "cache_hit",
            "already_delivered")

    def test_presentation_fields_frozen_and_service_free(self):
        import dataclasses
        names = tuple(f.name for f in dataclasses.fields(
            orch.FactcheckPresentation))
        assert names == ("text", "links", "reply_to_message_id", "parse_mode",
                         "notice")
        # 06B: служебные поля в egress-контракте ОТСУТСТВУЮТ по построению
        for forbidden in ("as_of", "gate_version", "reason_code",
                          "temporal_status", "evaluated_period",
                          "factual_verdict", "target_ref", "scope"):
            assert forbidden not in names

    def test_w1w2_schemas_unchanged(self):
        # фриз W1/W2-схем (перекрёстная проверка без импорта тестов W1/W2)
        import dataclasses
        from services.factcheck_context import ContextMessage, \
            ConversationContext
        from services.factcheck_suitability import ClaimItem, \
            SuitabilityDecision
        assert tuple(f.name for f in dataclasses.fields(ContextMessage)) == (
            "message_id", "tg_message_id", "chat_id", "author", "timestamp",
            "reply_to_tg_id", "is_forward", "forward_source", "text",
            "verbatim")
        assert tuple(f.name for f in dataclasses.fields(
            ConversationContext)) == ("chat_id", "target_tg_message_id",
                                      "trigger_tg_message_id", "messages",
                                      "window", "newest_message_id",
                                      "version")
        assert tuple(f.name for f in dataclasses.fields(ClaimItem)) == (
            "text", "claim_type", "verifiable", "source", "author",
            "anchor_tg_message_id", "anchor_chat_id")
        assert tuple(f.name for f in dataclasses.fields(
            SuitabilityDecision)) == ("decision", "claim_type", "claim_items",
                                      "scope", "reason_code", "confidence",
                                      "target_ref", "temporal_hint",
                                      "gate_version")


# ── Флаг и OFF-паритет ───────────────────────────────────────────────────────

class TestFlagAndParity:
    def test_pipeline_v2_default_off_and_hot_prio(self, monkeypatch):
        old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
        object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
        try:
            assert orch.pipeline_v2_enabled() is False
            assert hfc._pipeline_v2_enabled() is False
            from services import hot_config as hot
            monkeypatch.setattr(
                hot, "get",
                lambda key, default=None: True
                if key == "flags.factcheck_pipeline_v2" else default)
            assert orch.pipeline_v2_enabled() is True
        finally:
            object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)

    @pytest.mark.asyncio
    async def test_v2_implies_wide_context_and_gate(
            self, v2_on, w1w2_off, monkeypatch):
        # Консолидация: внутри v2 W1/W2 подразумеваются независимо от их
        # индивидуальных флагов (широкое окно > кап-40).
        rows = [{"id": 100 + i, "user_id": 1, "chat_id": CHAT_ID,
                 "text": f"болтовня номер {i}", "reply_to_id": None,
                 "timestamp": 1000 + i, "media_type": "text",
                 "author_name": "Вася", "is_forward": False,
                 "forward_source": None, "tg_message_id": 100 + i}
                for i in range(60)]
        rows.append({"id": 999, "user_id": 1, "chat_id": CHAT_ID,
                     "text": "целевое", "reply_to_id": None,
                     "timestamp": 9999, "media_type": "text",
                     "author_name": "Вася", "is_forward": False,
                     "forward_source": None, "tg_message_id": TARGET_TG})
        db = FakeDB(rows=rows)
        svc = FakeService()
        bot = FakeBot()
        await orch.run_factcheck(_req(), service=svc, db=db, bot=bot,
                                 cache=FakeCache())
        around = [q for q in db.queries if q[0] == "around"]
        assert around and (around[0][2] > 40 or around[0][3] > 0)
        assert svc.check_claim_calls           # legacy-ветка выполнилась


# ── Маршруты: один контракт ──────────────────────────────────────────────────

class TestRoutes:
    @pytest.mark.asyncio
    async def test_legacy_branch_same_call_args_as_prod(self, v2_on):
        db = FakeDB()
        svc = FakeService()
        await orch.run_factcheck(
            orch.FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                target_tg_message_id=TARGET_TG,
                target_text="дрожжи это грибы", user_hint="проверь",
                forward_source="Channel X", kind="reply"),
            service=svc, db=db, bot=FakeBot(), cache=FakeCache())
        call = svc.check_claim_calls[0]
        # байт-паритет аргументов прод-legacy-пути
        assert call["target_text"] == "дрожжи это грибы"
        assert call["user_hint"] == "проверь"
        assert call["forward_source"] == "Channel X"
        assert call["chat_id"] == CHAT_ID

    @pytest.mark.asyncio
    async def test_legacy_cache_write_after_delivery(self, v2_on):
        db = FakeDB()
        svc = FakeService()
        cache = FakeCache()
        bot = FakeBot()
        await orch.run_factcheck(_req(), service=svc, db=db, bot=bot,
                                 cache=cache)
        assert len(bot.sent) == 1
        assert cache.store                     # 59.2: запись после доставки

    @pytest.mark.asyncio
    async def test_envelope_branch_cache_and_links(self, v2_on, monkeypatch):
        origin = {"text": "в килякете выпало 120 мм", "caption": None,
                  "origin_type": None, "origin_sent_at": None,
                  "sent_at": 1700000000, "current_revision": None,
                  "content_hash": None, "origin_sender_user_id": None,
                  "origin_chat_id": None, "origin_display_name": None,
                  "author_name": "Вася", "forward_source": None}
        db = FakeDB(rows=[], origin_row=origin)
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_enabled", lambda: True)
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_cache_enabled",
            lambda: True)
        svc = FakeService()
        cache = FakeCache()
        bot = FakeBot()
        await orch.run_factcheck(_req(), service=svc, db=db, bot=bot,
                                 cache=cache)
        assert svc.envelope_calls              # envelope-ветка
        assert not svc.check_claim_calls
        assert cache.markers                   # составной кеш записан
        assert len(bot.sent) == 1
        # W5 renderer: URL из EvidenceMap текущего прогона идёт ТОЛЬКО как
        # href (кликабельная ссылка); в видимом тексте полного URL нет.
        rendered = bot.sent[0]["text"]
        assert rendered.count("https://example.org/src") == 1
        assert 'href="https://example.org/src"' in rendered
        from services.factcheck_renderer import visible_text
        assert "https://example.org/src" not in visible_text(rendered)

    @pytest.mark.asyncio
    async def test_no_claim_short_circuit_no_service_call(self, v2_on):
        rows = [{"id": 100 + i, "user_id": 1, "chat_id": CHAT_ID,
                 "text": "целевое" if i == 10 else "абв гдё жзик лсн прст",
                 "reply_to_id": None, "timestamp": 1000 + i,
                 "media_type": "text", "author_name": "Вася",
                 "is_forward": False, "forward_source": None,
                 "tg_message_id": TARGET_TG if i == 10 else 100 + i}
                for i in range(12)]
        db = FakeDB(rows=rows)

        class _NoService:
            def __getattr__(self, name):
                raise AssertionError("проверка не должна вызываться")

        bot = FakeBot()
        await orch.run_factcheck(
            orch.FactcheckRequest(chat_id=CHAT_ID,
                                  trigger_tg_message_id=TRIGGER_TG,
                                  target_tg_message_id=TARGET_TG,
                                  target_text="абв гдё жзик лсн прст"),
            service=_NoService(), db=db, bot=bot, cache=FakeCache())
        assert len(bot.sent) == 1
        from services.smartmodule_phrases import FACTCHECK_NO_CLAIM_PHRASES
        assert bot.sent[0]["text"] in FACTCHECK_NO_CLAIM_PHRASES

    @pytest.mark.asyncio
    async def test_ambiguous_persona_reply_with_owner_block_last(
            self, v2_on, monkeypatch):
        rows = [*_two_disputes()]
        db = FakeDB(rows=rows)
        llm = FakeLLM(reply="какой именно тезис проверяем?")
        svc = FakeService(llm=llm)
        import services.prompt_composer as pc
        monkeypatch.setattr(pc, "speech_owner_block",
                            _fake_owner_block)
        bot = FakeBot()
        await orch.run_factcheck(
            orch.FactcheckRequest(chat_id=CHAT_ID,
                                  trigger_tg_message_id=TRIGGER_TG,
                                  target_tg_message_id=TARGET_TG,
                                  target_text="ну и что там?"),
            service=svc, db=db, bot=bot, cache=FakeCache())
        assert llm.calls and llm.calls[0]["step"] == "short_reply"
        system = llm.calls[0]["messages"][0]["content"]
        # шов MCA-08: character_block (persona) — ПОСЛЕДНИЙ блок system
        assert system.strip().endswith("[PERSONA]")
        assert "какой именно тезис" in bot.sent[0]["text"]


async def _fake_owner_block(chat_id):
    return "[PERSONA]"


def _two_disputes():
    def _row(i, text, tg, reply_to=None, author="Вася"):
        return {"id": 100 + i, "user_id": 1, "chat_id": CHAT_ID,
                "text": text, "reply_to_id": reply_to,
                "timestamp": 1000 + i, "media_type": "text",
                "author_name": author, "is_forward": False,
                "forward_source": None, "tg_message_id": tg}
    rows = []
    base = 0
    rows += [_row(base, "килякетские дожди были кислотными и убили весь "
                       "урожай", 8000, author="Вася"),
             _row(base + 1, "это бред", 8001, reply_to=8000, author="Петя"),
             _row(base + 2, "источник где?", 8002, reply_to=8000,
                  author="Оля")]
    base = 10
    rows += [_row(base, "вакцина от гриппа содержит живой вирус штамм",
                  8100, author="Оля"),
             _row(base + 1, "да ну, не верю", 8101, reply_to=8100,
                  author="Петя"),
             _row(base + 2, "пруфы будут?", 8102, reply_to=8100,
                  author="Вася")]
    rows.append(_row(20, "целевое", TARGET_TG))
    return rows


# ── Egress-whitelist (06B) ───────────────────────────────────────────────────

class TestEgressWhitelist:
    def test_service_fields_do_not_reach_presentation(self):
        verdict = orch.CheckedVerdict(
            verdict_text="Тезис не подтвердился.", route="envelope_temporal",
            factual_verdict="refuted", temporal_status="current",
            evaluated_period={"from": 100, "to": 200, "precision": "day"},
            uncertainty={"dates_unresolved": "x"},
            evidence=orch.EvidenceMap(
                refs=(orch.EvidenceRef("ev-1", "https://example.org/a",
                                       "support"),),
                allowlist=("ev-1",)),
            reason_code="temporal_fallback_mode", as_of=1760900000,
            gate_version="fsg1")
        p = orch.build_presentation(verdict, reply_to_message_id=42)
        data = json.dumps(__import__("dataclasses").asdict(p),
                          ensure_ascii=False)
        for forbidden in ("1760900000", "fsg1", "temporal_fallback_mode",
                          "refuted", "evaluated_period"):
            assert forbidden not in data
        assert p.links == ("https://example.org/a",)   # только EvidenceMap
        assert p.reply_to_message_id == 42

    def test_egress_scan_strips_service_markers_from_text(self):
        verdict = orch.CheckedVerdict(
            verdict_text="Итог: verdict по данным, as_of не публикуем, "
                         "reason_code скрыт.",
            route="legacy_single")
        p = orch.build_presentation(verdict)
        assert "as_of" not in p.text and "reason_code" not in p.text

    def test_empty_presentation_raises_bad_response(self):
        with pytest.raises(Exception):
            orch.build_presentation(
                orch.CheckedVerdict(verdict_text="   ", route="legacy_single"))
