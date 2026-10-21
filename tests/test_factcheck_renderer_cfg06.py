"""CFG-06 W5 — детерминированный renderer + filtered verbalize (06E/06A.5).

TEST-LIFECYCLE: CONTRACT owner=CFG-06

Контракты:
  * renderer: FactcheckPresentation (+enum CheckedVerdict) → безопасный
    Telegram-HTML; структура вместо полотна (bold-вердикт, 2–4 пункта,
    источники); HTML-инъекция из текста/URL невозможна; ссылки — ТОЛЬКО
    из presentation.links (EvidenceMap текущего прогона), scheme-whitelist;
    служебные поля в публичном тексте отсутствуют (негативный тест);
  * снапшоты разметки: fixture-презентации → точный ожидаемый текст;
  * entity-safe чанки: теги не рвутся, каждая часть ≤ лимита;
  * доставка через СУЩЕСТВУЮЩИЙ send_chunked_reply(parse_mode=...),
    reply только у первой части, plain-деградация сломанного чанка;
  * утечка style_note («период проверки (unknown)») устранена: байты
    w0-trace (probe 06A.5) в исходнике отсутствуют, payload вербализатора
    — человекочитаемый дайджест без служебных полей, раскладка остального
    текста байт-защищена, шов speech_owner_block — ПОСЛЕДНИЙ блок system;
  * OFF-паритет: renderer живёт только в v2-оркестраторе, прод-путь
    2.58.98 (handlers/factcheck.py) его не импортирует.
"""
import json

import pytest

from aiogram.exceptions import TelegramBadRequest
from config.settings import settings
from services import factcheck_orchestrator as orch
from services import factcheck_renderer as fr
from services import factcheck_service as fs
from services.temporal_factcheck import (
    TemporalClaimEnvelope,
    TemporalRunResult,
    TemporalVerdict,
)

CHAT_ID = -100555
TARGET_TG = 9200
TRIGGER_TG = 9201


def _presentation(text="Тезис не подтверждается. Данные расходятся. "
                       "Источник один.", links=("https://example.org/a",),
                  notice="", reply=TARGET_TG):
    return orch.FactcheckPresentation(text=text, links=tuple(links),
                                      reply_to_message_id=reply,
                                      parse_mode=None, notice=notice)


def _verdict(text="Тезис не подтверждается. Данные расходятся. "
                  "Источник один.",
             factual="refuted", with_evidence=True):
    refs = ()
    if with_evidence:
        refs = (orch.EvidenceRef("ev-1", "https://example.org/a",
                                 "подтверждение"),)
    return orch.CheckedVerdict(
        verdict_text=text, route="envelope_temporal",
        factual_verdict=factual, temporal_status="current",
        evaluated_period={"from": 100, "to": 200, "precision": "day"},
        evidence=orch.EvidenceMap(refs=refs, allowlist=("ev-1",)),
        reason_code="temporal_fallback_mode", as_of=1760900000,
        gate_version="fsg1")


# ── Структура рендера (06E) ──────────────────────────────────────────────────

class TestRenderStructure:
    def test_snapshot_refuted_with_links(self):
        p = fr.render_factcheck(_presentation(), _verdict())
        assert p.parse_mode == "HTML"
        assert p.text == (
            "<b>Не подтверждается</b>\n\n"
            "• Тезис не подтверждается.\n"
            "• Данные расходятся.\n"
            "• Источник один.\n\n"
            "Источники:\n"
            "1. <a href=\"https://example.org/a\">example.org</a> — пересказ")
        # снапшот фиксирован: egress-поля в разметке не появляются
        assert "fsg1" not in p.text and "1760900000" not in p.text

    def test_no_verdict_no_headline(self):
        p = fr.render_factcheck(_presentation(), None)
        assert "<b>" not in p.text
        assert p.text.startswith("• Тезис не подтверждается.")

    def test_unknown_enum_no_fabricated_headline(self):
        v = _verdict(factual="загадочный-статус")
        p = fr.render_factcheck(_presentation(), v)
        assert "<b>" not in p.text          # renderer не выдумывает вердикт

    def test_single_sentence_no_bullets(self):
        p = fr.render_factcheck(_presentation(text="Один тезис.", links=()),
                                None)
        assert p.text == "Один тезис."

    def test_two_points(self):
        p = fr.render_factcheck(
            _presentation(text="Первое предложение. Второе предложение.",
                          links=()), None)
        assert p.text == ("• Первое предложение.\n"
                          "• Второе предложение.")

    def test_seven_sentences_four_points_order_kept(self):
        body = " ".join(f"Предложение номер {i}." for i in range(1, 8))
        p = fr.render_factcheck(_presentation(text=body, links=()), None)
        bullets = [ln for ln in p.text.split("\n") if ln.startswith("• ")]
        assert len(bullets) == 4
        joined = " ".join(bullets)
        for i in range(1, 8):
            assert f"Предложение номер {i}." in joined   # ничего не выброшено
        # порядок сохранён (группы подряд)
        assert joined.index("номер 1") < joined.index("номер 4") \
            < joined.index("номер 7")

    def test_insufficient_evidence_headline(self):
        v = _verdict(factual="insufficient_evidence", with_evidence=False)
        p = fr.render_factcheck(_presentation(text="Данных мало.", links=()),
                                v)
        assert p.text.startswith("<b>Недостаточно данных для проверки</b>")

    def test_notice_rendered_italic(self):
        p = fr.render_factcheck(_presentation(text="Один тезис.", links=(),
                                              notice="Проверка ограничена."),
                                None)
        assert p.text.endswith("<i>Проверка ограничена.</i>")

    def test_no_links_with_evidence_honest_limitation(self):
        v = _verdict(with_evidence=False)   # refs нет → ожидание не заявлено
        refs = (orch.EvidenceRef("ev-2", None, "выдержка без URL"),)
        v = orch.CheckedVerdict(
            verdict_text=v.verdict_text, route="envelope_temporal",
            factual_verdict="refuted",
            evidence=orch.EvidenceMap(refs=refs, allowlist=("ev-2",)))
        p = fr.render_factcheck(
            _presentation(text="Один тезис.", links=()), v)
        assert "Первоисточники в этот раз открыть не удалось" in p.text

    def test_no_links_without_evidence_no_limitation(self):
        p = fr.render_factcheck(_presentation(text="Один тезис.", links=()),
                                None)
        assert "Первоисточники" not in p.text

    def test_visible_text_strips_tags(self):
        assert fr.visible_text("<b>А</b> и <a href=\"https://x.y\">Б</a>") \
            == "А и Б"


# ── Экранирование и whitelist ссылок (06E) ───────────────────────────────────

class TestEscapeAndLinks:
    def test_html_injection_escaped(self):
        evil = ("Тезис <script>alert(1)</script> и <b onmouseover=\"x()\">"
                "жирный</b> ещё.")
        p = fr.render_factcheck(_presentation(text=evil, links=()), None)
        # ни один сырой тег из входа не выжил (экранирование < > &)
        assert "<script>" not in p.text and "<b " not in p.text
        assert "&lt;script&gt;" in p.text
        assert "&lt;b onmouseover=" in p.text
        # из тегов разметки допустимы только b/i/a
        allowed = set(fr._TAG_RE.findall(p.text))
        assert all(t in ("<b>", "</b>", "<i>", "</i>") or
                   t.startswith("<a ") or t == "</a>" for t in allowed)

    def test_url_escaped_in_href(self):
        url = "https://example.org/a?x=1&y=2"
        p = fr.render_factcheck(_presentation(text="Тезис.", links=(url,)),
                                None)
        assert 'href="https://example.org/a?x=1&amp;y=2"' in p.text

    def test_scheme_whitelist(self):
        p = fr.render_factcheck(_presentation(
            text="Тезис.", links=("javascript:alert(1)",
                                  "ftp://example.org/f",
                                  "https://ok.example/x")), None)
        assert "javascript:" not in p.text and "ftp://" not in p.text
        assert "https://ok.example/x" in p.text

    def test_links_dedup_and_order(self):
        p = fr.render_factcheck(_presentation(
            text="Тезис.", links=("https://b.example/",
                                  "https://a.example/",
                                  "https://b.example/")), None)
        assert p.text.index("b.example") < p.text.index("a.example")
        assert p.text.count("https://b.example/") == 1

    def test_www_stripped_in_label(self):
        p = fr.render_factcheck(_presentation(
            text="Тезис.", links=("https://www.example.org/x",)), None)
        assert ">example.org</a>" in p.text


# ── Негативный: служебные поля не проходят (06B/06G.5) ──────────────────────

class TestNoServiceFields:
    def test_service_fields_absent_from_markup(self):
        p = fr.render_factcheck(_presentation(), _verdict())
        for forbidden in ("1760900000", "fsg1", "temporal_fallback_mode",
                          "refuted", "evaluated_period", "as_of",
                          "gate_version", "reason_code", "current"):
            assert forbidden not in p.text, forbidden
        assert "Не подтверждается" in p.text   # человеческая фраза по enum

    def test_presentation_fields_unchanged(self):
        import dataclasses
        assert tuple(f.name for f in dataclasses.fields(
            orch.FactcheckPresentation)) == (
            "text", "links", "reply_to_message_id", "parse_mode", "notice")


# ── Entity-safe чанки (06E) ──────────────────────────────────────────────────

class TestEntitySafeChunks:
    def test_short_single_chunk(self):
        assert fr.split_entity_safe("короткий текст") == ["короткий текст"]

    def test_long_markup_chunks_valid(self):
        body = "\n\n".join(
            ["<b>Вердикт</b>"] +
            ["• " + " ".join(f"слово{i}" for i in range(60))
             for _ in range(80)] +
            ["Источники:\n" + "\n".join(
                f"{i}. <a href=\"https://src{i}.example/page\">src{i}"
                f"</a>" for i in range(20))])
        assert len(body) > 2 * fr._CHUNK_LIMIT
        chunks = fr.split_entity_safe(body)
        assert len(chunks) >= 3
        seen_lines: list[str] = []
        for chunk in chunks:
            assert len(chunk) <= fr._CHUNK_LIMIT
            # теги не разорваны границей части (баланс в каждой части)
            assert chunk.count("<b>") == chunk.count("</b>")
            assert chunk.count("<a ") == chunk.count("</a>")
            for line in chunk.split("\n"):
                if line:
                    seen_lines.append(line)
        # все непустые строки сохранены по порядку
        assert seen_lines == [ln for ln in body.split("\n") if ln]

    def test_long_single_paragraph_split_by_words(self):
        para = " ".join(f"слово{i}" for i in range(3000))
        chunks = fr.split_entity_safe(para, limit=1000)
        assert all(len(c) <= 1000 for c in chunks)
        assert " ".join(chunks).split() == para.split()


# ── Доставка через СУЩЕСТВУЮЩИЙ send_chunked_reply ──────────────────────────

class _RecBot:
    def __init__(self, fail_html=False):
        self.sent = []
        self.fail_html = fail_html

    async def send_message(self, chat_id, text, **kw):
        if self.fail_html and kw.get("parse_mode"):
            raise TelegramBadRequest(method="sendMessage",
                                     message="Bad Request: can't parse "
                                             "entities")
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 700})()


class _FakeTyping:
    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


class TestDelivery:
    @pytest.mark.asyncio
    async def test_plain_passthrough(self):
        bot = _RecBot()
        await fr.deliver_factcheck(bot, CHAT_ID,
                                   _presentation(text="привет"),
                                   reply_to_message_id=TARGET_TG)
        assert len(bot.sent) == 1
        assert "parse_mode" not in bot.sent[0]

    @pytest.mark.asyncio
    async def test_html_single_send(self):
        bot = _RecBot()
        p = fr.render_factcheck(_presentation(), _verdict())
        await fr.deliver_factcheck(bot, CHAT_ID, p,
                                   reply_to_message_id=TARGET_TG)
        assert len(bot.sent) == 1
        assert bot.sent[0]["parse_mode"] == "HTML"
        assert bot.sent[0]["reply_to_message_id"] == TARGET_TG

    @pytest.mark.asyncio
    async def test_html_long_reply_first_chunk_only(self):
        bot = _RecBot()
        body = "\n\n".join("• " + "x" * 200 for _ in range(60))
        p = orch.FactcheckPresentation(text=body, links=(), parse_mode="HTML")
        await fr.deliver_factcheck(bot, CHAT_ID, p,
                                   reply_to_message_id=TARGET_TG)
        assert len(bot.sent) >= 2
        assert bot.sent[0]["reply_to_message_id"] == TARGET_TG
        for extra in bot.sent[1:]:
            assert "reply_to_message_id" not in extra
            assert extra["parse_mode"] == "HTML"
            assert len(extra["text"]) <= fr._CHUNK_LIMIT

    @pytest.mark.asyncio
    async def test_bad_html_chunk_plain_degradation(self):
        bot = _RecBot(fail_html=True)
        p = fr.render_factcheck(_presentation(), _verdict())
        await fr.deliver_factcheck(bot, CHAT_ID, p,
                                   reply_to_message_id=TARGET_TG)
        assert bot.sent                                  # деградация состоялась
        assert all(not s.get("parse_mode") for s in bot.sent)
        assert "Не подтверждается" in bot.sent[0]["text"]
        assert "<b>" not in bot.sent[0]["text"]
        # контент сохранён без разметки
        assert "Тезис не подтверждается." in bot.sent[0]["text"]


# ── Утечка style_note устранена (06A.5, байт-защита по w0-trace) ────────────

def _env(claim="в Килякете выпало 120 мм осадков за сутки"):
    return TemporalClaimEnvelope(
        claim_id="c-1", chat_id=777, target_tg_message_id=TARGET_TG,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=TRIGGER_TG, claim_text=claim, claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=None, original_published_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source="unknown",
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="contextual", analysis_as_of=1760900000)


def _temporal_verdict(period=None, uncertainty=None):
    return TemporalVerdict(
        factual_verdict="refuted", temporal_status="unknown",
        evaluated_period=period if period is not None else
        {"from": None, "to": None, "precision": "unknown"},
        assessment_mode="contextual", as_of=1760900000,
        evidence_refs=("ev-1",),
        uncertainty=uncertainty if uncertainty is not None else
        {"dates_unresolved": "дата публикации оригинала не определена — "
                             "временная оценка ограничена"},
        parts=(), reason=None)


class _CaptureVerbalize:
    def __init__(self):
        self.messages = None

    async def __call__(self, _generate, messages, **kwargs):
        self.messages = messages
        return "ок, вердикт", {"attempts": 1, "retries": 0, "hits": [],
                               "fallback": False}


def _capture_verbalize(monkeypatch) -> _CaptureVerbalize:
    cap = _CaptureVerbalize()
    monkeypatch.setattr(fs, "verbalize_validated", cap)
    return cap


def _make_service():
    return fs.FactCheckService(aggregator=None, llm=None, memory=None)


class TestStyleNoteLeakGone:
    def test_old_bytes_absent_from_source(self):
        # байты w0-trace probe 06A.5 (deployed L753–758) удалены
        src = open("services/factcheck_service.py", encoding="utf-8").read()
        assert "Обязательно сохрани в ответе: период проверки" not in src
        assert '"style_note"' not in src
        assert "temporal_note" not in src

    @pytest.mark.asyncio
    async def test_payload_humanized_no_service_fields(self, monkeypatch):
        cap = _capture_verbalize(monkeypatch)
        svc = _make_service()
        out = await svc._temporal_verbalize(
            _env(), _temporal_verdict(), False, None)
        assert out == "ок, вердикт"
        system, user = (m["content"] for m in cap.messages)
        assert user.startswith("ВЕРДИКТ (JSON):\n")
        payload = json.loads(user[len("ВЕРДИКТ (JSON):\n"):])
        # служебные поля — мимо payload; unknown → человеческие слова
        for forbidden in ("unknown", "refuted", "1760900000", "precision",
                          "as_of", "style_note", "temporal_status",
                          "evaluated_period", "assessment_mode",
                          "uncertainty", "период проверки"):
            assert forbidden not in user, forbidden
        assert payload["verdict"] == \
            "доступные данные утверждение не подтверждают"
        assert payload["freshness"] == "свежесть данных определить не удалось"
        assert payload["caveats"] == [
            "дата публикации оригинала не определена — временная оценка "
            "ограничена"]
        assert payload["claim"] == "в Килякете выпало 120 мм осадков за сутки"
        assert payload["parts"] == []

    @pytest.mark.asyncio
    async def test_payload_layout_bytes_snapshot(self, monkeypatch):
        """Байт-защита раскладки: обёртка/порядок человекочитаемых ключей
        сохранены (period — даты по-человечески, никаких «unknown»)."""
        cap = _capture_verbalize(monkeypatch)
        svc = _make_service()
        period = {"from": 1750000000, "to": 1750086400, "precision": "day"}
        await svc._temporal_verbalize(
            _env(), _temporal_verdict(period=period, uncertainty={}),
            False, None)
        user = cap.messages[1]["content"]
        expected_payload = {
            "verdict": "доступные данные утверждение не подтверждают",
            "freshness": "свежесть данных определить не удалось",
            "period": "с 15.06.2025 по 16.06.2025",
            "parts": [],
            "claim": "в Килякете выпало 120 мм осадков за сутки",
        }
        assert user == "ВЕРДИКТ (JSON):\n" + json.dumps(
            expected_payload, ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_period_omitted_when_unknown(self, monkeypatch):
        cap = _capture_verbalize(monkeypatch)
        svc = _make_service()
        await svc._temporal_verbalize(_env(), _temporal_verdict(), False,
                                      None)
        payload = json.loads(cap.messages[1]["content"][
            len("ВЕРДИКТ (JSON):\n"):])
        assert "period" not in payload     # нет дат — нет и «unknown»

    @pytest.mark.asyncio
    async def test_fallback_note_bytes_preserved(self, monkeypatch):
        cap = _capture_verbalize(monkeypatch)
        svc = _make_service()
        await svc._temporal_verbalize(_env(), _temporal_verdict(), True,
                                      None)
        payload = json.loads(cap.messages[1]["content"][
            len("ВЕРДИКТ (JSON):\n"):])
        assert list(payload)[-1] == "fallback_note"
        assert payload["fallback_note"] == (
            "структурированный анализ не удался — не утверждай больше, "
            "чем следует из данных")

    @pytest.mark.asyncio
    async def test_owner_block_last_system_seam(self, monkeypatch):
        cap = _capture_verbalize(monkeypatch)
        seen = {}

        async def fake_owner(chat_id):
            seen["chat_id"] = chat_id
            return "[PERSONA]"

        monkeypatch.setattr(fs, "speech_owner_block", fake_owner)
        svc = _make_service()
        await svc._temporal_verbalize(_env(), _temporal_verdict(), False,
                                      None)
        assert seen["chat_id"] == 777      # характер по настройкам владельца
        system = cap.messages[0]["content"]
        assert system.endswith("[PERSONA]")   # character_block — последний

    @pytest.mark.asyncio
    async def test_owner_block_empty_is_byte_parity(self, monkeypatch):
        cap = _capture_verbalize(monkeypatch)
        monkeypatch.setattr(fs, "speech_owner_block",
                            _empty_owner)
        svc = _make_service()
        await svc._temporal_verbalize(_env(), _temporal_verdict(), False,
                                      None)
        system_without = cap.messages[0]["content"]
        assert system_without.strip()
        # тот же прогон с непустым блоком → канон + "\n\n" + блок
        cap2 = _capture_verbalize(monkeypatch)
        monkeypatch.setattr(fs, "speech_owner_block", _persona_owner)
        await svc._temporal_verbalize(_env(), _temporal_verdict(), False,
                                      None)
        assert cap2.messages[0]["content"] == system_without + "\n\n[PERSONA]"


async def _empty_owner(chat_id):
    return ""


async def _persona_owner(chat_id):
    return "[PERSONA]"


# ── Интеграция: v2-оркестратор доставляет через renderer ────────────────────

class FakeDB:
    async def get_messages_around(self, chat_id, tg, before, after):
        return []

    async def get_recent_messages(self, chat_id, limit):
        return []

    async def get_smart_message_origin_block(self, chat_id, tg):
        raise RuntimeError("no origin row")


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


class FakeBot(_RecBot):
    async def send_chat_action(self, chat_id, action, **kw):
        return True


class FakeService:
    def __init__(self):
        self.envelope_calls = []

    async def check_claim_envelope(self, envelope, *, chat_context=None):
        self.envelope_calls.append(envelope)
        return TemporalRunResult(
            envelope=envelope,
            verdict=TemporalVerdict(
                factual_verdict="refuted", temporal_status="current",
                evaluated_period={"from": 100, "to": 200, "precision": "day"},
                assessment_mode="contextual", as_of=1760900000,
                evidence_refs=("ev-1",), reason=None),
            verdict_text="Тезис не подтверждается. Данные расходятся. "
                         "Источник один.",
            evidence_rows=({"evidence_id": "ev-1",
                            "url": "https://example.org/src",
                            "support": "подтверждение",
                            "source_kind": "secondary",
                            "published_at": None},),
            fallback_used=False)


def _decision_checkable():
    from services import factcheck_suitability as fsg
    item = fsg.ClaimItem(text="тезис",
                         claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
                         verifiable=True, source="literal")
    return fsg.SuitabilityDecision(
        decision=fsg.DECISION_CHECKABLE,
        claim_type=fsg.CHECKABLE_FACTUAL_CLAIM, claim_items=(item,),
        scope="web", reason_code="obvious_checkable_predicate",
        confidence=0.8, target_ref={}, temporal_hint=True)


class TestOrchestratorW5Delivery:
    @pytest.mark.asyncio
    async def test_v2_envelope_delivered_rendered(self, monkeypatch):
        object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
        try:
            from services import factcheck_suitability as fsg
            from services import temporal_factcheck as tf
            monkeypatch.setattr(fsg, "evaluate_with_expansion",
                                _fake_evaluate)
            monkeypatch.setattr(tf, "build_envelope", _fake_build_envelope)
            monkeypatch.setattr(
                "services.mca_gates.temporal_factcheck_enabled",
                lambda: True)
            monkeypatch.setattr(
                "services.mca_gates.temporal_factcheck_cache_enabled",
                lambda: True)
            monkeypatch.setattr(orch, "get_smartmodule_concurrency_pool",
                                lambda: _FakePool())
            monkeypatch.setattr(orch, "typing_active", _FakeTyping)
            svc = FakeService()
            bot = FakeBot()
            await orch.run_factcheck(
                orch.FactcheckRequest(
                    chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                    target_tg_message_id=TARGET_TG, target_text="тезис",
                    kind="reply"),
                service=svc, db=FakeDB(), bot=bot, cache=FakeCache())
            assert svc.envelope_calls and len(bot.sent) == 1
            sent = bot.sent[0]
            assert sent["parse_mode"] == "HTML"
            assert "<b>Не подтверждается</b>" in sent["text"]
            assert 'href="https://example.org/src"' in sent["text"]
            from services.factcheck_renderer import visible_text
            assert "https://example.org/src" not in visible_text(
                sent["text"])
            assert sent["reply_to_message_id"] == TARGET_TG
        finally:
            object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED",
                               False)


class _FakePool:
    def __init__(self):
        self._permit = type("P", (), {"release": lambda self: None})()

    async def try_acquire(self, chat_id, timeout=None):
        return self._permit


async def _fake_evaluate(db, chat_id, **kwargs):
    from services import factcheck_suitability as fsg
    return _decision_checkable(), None


async def _fake_build_envelope(db, ref, default_mode="contextual"):
    return _env(claim="тезис"), None


# ── OFF-паритет: renderer живёт только в v2 ─────────────────────────────────

class TestOffParity:
    def test_prod_handler_does_not_import_renderer(self):
        src = open("handlers/factcheck.py", encoding="utf-8").read()
        assert "factcheck_renderer" not in src
        assert "render_factcheck" not in src

    def test_renderer_import_side_effect_free(self):
        import importlib
        import sys
        mod = importlib.import_module("services.factcheck_renderer")
        assert "services.factcheck_renderer" in sys.modules
        assert mod.FACTCHECK_PARSE_MODE == "HTML"

    def test_legacy_route_single_sentence_stays_plain_readable(self):
        # legacy-ветка: enum нет → нет выдуманного вердикта, текст читаем
        p = fr.render_factcheck(
            _presentation(text="Вердикт легаси-ветки", links=()), None)
        assert "<b>" not in p.text and "• " not in p.text
        assert p.text == "Вердикт легаси-ветки"
