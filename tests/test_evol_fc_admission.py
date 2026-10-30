"""ASAP-FC-ADMISSION-01 — допуск явного фактчека: 8 контрактных сценариев §5.

TEST-LIFECYCLE: CONTRACT owner=ASAP-FC-ADMISSION-01

Дефект 31.10.2026: явный ``фактчек`` в reply к пересланному утверждению про
вредоносный стикер со ссылкой получал «тут нечего проверять, просто базар»
(``FACTCHECK_NO_CLAIM_PHRASES``); быстрый повтор упирался в cooldown, а позже
проверка всё-таки выполнялась.

Контракты этой приёмки:

(1) явный фактчек + правдоподобно проверяемое ядро → ``checkable``, обычный
    пайплайн запускается, ответ НЕ из пула ``no_claim``;
(2) разговорная/матная/саркастичная формулировка без дат и цифр → ядро
    выделяется, конкретное ключевое слово из словаря НЕ требуется;
(3) факт + эмоция → проверяется фактическая часть, оценка отделяется;
(4) два тезиса в одном посте → оба распознаны per-claim policy (fp3);
(5) явный фактчек на пустое сообщение → честный ответ о недоступной цели,
    без выдуманного вердикта и без платного поиска;
(6) несколько неоднозначных соседних сообщений → уточнение, НЕ ``no_claim`` и
    не приписывание чужого тезиса;
(7) тезис определён, поиск ничего надёжного не подтвердил →
    ``insufficient_evidence``, НЕ ``no_claim``;
(8) повтор после раннего отказа + одновременные вызовы → нет необоснованного
    полного cooldown, при этом антиспам и single-flight сохранены.

Все сценарии детерминированные и офлайновые: LLM/сеть/Telegram не вызываются.
"""
import asyncio
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from handlers import factcheck as hfc
from services import factcheck_context as fcx
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import factcheck_suitability as fsg
from services import mca_gates
from services import temporal_factcheck as tf
from services.smartmodule_phrases import (
    FACTCHECK_CLARIFY_PHRASES,
    FACTCHECK_EMPTY_CONTEXT_PHRASES,
    FACTCHECK_NO_CLAIM_PHRASES,
    FACTCHECK_TARGET_UNAVAILABLE_PHRASES,
)

CHAT_ID = -100777
TARGET_TG = 5000
TRIGGER_TG = 5001
USER_ID = 7

# (1) Пересланный тезис 31.10: стикер/вирус/кошелёк + ссылка на разбор.
# Ни узкого предиката (глагольный список), ни чисел — только ядро и ссылка.
FORWARD_CLAIM = (
    "ОСТОРОЖНО! Со стикера можно поймать вирус: он залезает в телефон, "
    "сливает переписку и уводит деньги с кошелька. Разбор тут "
    "t.me/virusstickers/razbor")
# (2) Разговорно, с матом и сарказмом, без дат/цифр и без «словарных» слов.
COLLOQUIAL_CLAIM = (
    "эта хуйня со стикером пиздец опасная, реально тырит бабки с кошелька, "
    "ну серьёзно, какие ещё вирусы в картинках")
# (3) Смесь фактического тезиса и эмоциональной оценки.
MIXED_CLAIM = "стикер с вирусом заражает телефон, но это отвратительно и мерзко"
# (4) Два самостоятельных тезиса в одном посте.
TWO_CLAIMS = (
    "стикер с вирусом крадёт данные и слить кошелёк может. ещё пишут, что "
    "через такие ссылки угоняют аккаунты")
REFERENTIAL_TARGET = "ну и что там?"


# ── Двойники (офлайн) ───────────────────────────────────────────────────────

def _row(i, text, *, tg=None, reply_to=None, author="Вася"):
    return {"id": 100 + i, "user_id": 1, "chat_id": CHAT_ID, "text": text,
            "reply_to_id": reply_to, "timestamp": 1000 + i,
            "media_type": "text", "author_name": author, "is_forward": False,
            "forward_source": None, "tg_message_id": tg}


class FakeDB:
    """Минимальный двойник БД для широкого контекста (W1)."""

    def __init__(self, rows):
        self._rows = list(rows)

    async def get_messages_around(self, chat_id, target_tg_message_id,
                                  before, after):
        return list(self._rows)

    async def get_recent_messages(self, chat_id, limit):
        return list(self._rows[-limit:]) if limit else []


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get_update_marker(self, key, *, ttl_seconds):
        return self.store.get(key)

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.store[key] = payload


def _make_msg(text=None, caption=None, message_id=1, user_id=USER_ID,
              reply_to_message=None, forward_origin=None, media_group_id=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.reply_to_message = reply_to_message
    msg.forward_origin = forward_origin
    msg.media_group_id = media_group_id
    msg.quote = None
    return msg


def _background(count=8):
    return [_row(i, f"болтовня номер {i}", tg=6000 + i) for i in range(count)]


async def _ctx(rows, claim=""):
    return await fcx.build_wide_context(
        FakeDB(rows), CHAT_ID, target_tg_message_id=TARGET_TG,
        trigger_tg_message_id=TRIGGER_TG, claim_text=claim,
        cache=FakeCache())


def _clusters():
    """Два сопоставимых спора в окне — цель не приписывается ни одному."""
    return [
        _row(0, "килякетские дожди были кислотными и убили весь урожай",
             tg=7000, author="Вася"),
        _row(1, "это бред", tg=7001, reply_to=7000, author="Петя"),
        _row(2, "источник где?", tg=7002, reply_to=7000, author="Оля"),
        _row(3, "вакцина от гриппа содержит живой вирус штамм",
             tg=7100, author="Петя"),
        _row(4, "да ну, это правда что ли", tg=7101, reply_to=7100,
             author="Оля"),
        _row(5, "пруфов не будет, знаю я это", tg=7102, reply_to=7100,
             author="Вася"),
    ]


@pytest.fixture
def gate_on():
    """Действующий маршрут гейта: широкий контекст + suitability ON."""
    olds = (getattr(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", False),
            getattr(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", False))
    object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", True)
    object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", olds[0])
    object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", olds[1])


@pytest.fixture
def handler_env(monkeypatch):
    """Handler на действующем (не-v2/не-temporal) маршруте + чистый кулдаун."""
    monkeypatch.setattr(hfc, "_temporal_on", lambda: False)
    monkeypatch.setattr(hfc, "_pipeline_v2_enabled", lambda: False)
    monkeypatch.setattr(hfc, "get_smart_cache", lambda: FakeCache())
    old_db, old_service = hfc._db, hfc._service
    hfc._cooldown._last.clear()
    yield
    hfc._db, hfc._service = old_db, old_service
    hfc._cooldown._last.clear()


def _verdict_service(text="проверил: заражение через стикер не подтверждается"):
    service = MagicMock()
    service.check_claim = AsyncMock(return_value=text)
    service.check_claim_envelope = AsyncMock(
        side_effect=AssertionError("envelope-ветка не ожидалась"))
    service.llm = MagicMock()
    service.llm.generate = AsyncMock(side_effect=AssertionError("LLM offline"))
    return service


# ── (1) Явный фактчек на пересланный тезис со ссылкой ───────────────────────

class TestScenario1ForwardedClaimWithLink:
    """«фактчек» в reply к пересланному тезису про стикер/вирус/кошелёк."""

    @pytest.mark.asyncio
    async def test_red_reproduction_without_explicit_request(self):
        """RED: именно этот текст раньше уходил в no_claim_after_context."""
        ctx = await _ctx(_background(), claim=FORWARD_CLAIM)
        decision = fsg.evaluate_suitability(
            FORWARD_CLAIM, None, ctx, target_ref={"chat_id": CHAT_ID},
            explicit_request=False)
        assert decision.decision == fsg.DECISION_NO_CLAIM
        assert decision.claim_type == fsg.NONSENSE
        assert fsg.admission_label(decision) == \
            fsg.ADMISSION_NO_IDENTIFIABLE_CLAIM

    @pytest.mark.asyncio
    async def test_explicit_request_admits_checkable_core(self):
        ctx = await _ctx(_background(), claim=FORWARD_CLAIM)
        decision = fsg.evaluate_suitability(
            FORWARD_CLAIM, None, ctx, target_ref={"chat_id": CHAT_ID},
            explicit_request=True)
        assert decision.decision == fsg.DECISION_CHECKABLE
        assert decision.reason_code == fsg._REASON_EXPLICIT_CORE
        assert decision.scope in (fsg.SCOPE_WEB, fsg.SCOPE_WEB_AND_CHAT)
        assert decision.claim_items
        item = decision.claim_items[0]
        assert "вирус" in item.text.lower()
        assert item.source == "literal" and item.verifiable is True
        # ссылка — материал, а не тезис
        assert all("t.me" not in i.text for i in decision.claim_items)

    @pytest.mark.asyncio
    async def test_pipeline_runs_and_no_claim_pool_not_used(
            self, gate_on, handler_env, monkeypatch, caplog):
        target = _make_msg(text=FORWARD_CLAIM, message_id=TARGET_TG)
        msg = _make_msg(text="фактчек", message_id=TRIGGER_TG,
                        reply_to_message=target)
        service = _verdict_service()
        hfc._db = FakeDB(_background())
        hfc.setup_factcheck(service)
        bot = AsyncMock()
        with caplog.at_level("INFO"):
            await hfc.factcheck_handler(msg, bot=bot)
        assert service.check_claim.await_count == 1
        sent = bot.send_message.await_args.args[1]
        assert sent not in FACTCHECK_NO_CLAIM_PHRASES
        assert "проверил" in sent
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == \
            TARGET_TG
        assert any("admission=checkable" in r.getMessage()
                   and "explicit=True" in r.getMessage()
                   and "reason=explicit_request_checkable_core"
                   in r.getMessage()
                   for r in caplog.records)


# ── (2) Разговорно/мат/сарказм, без дат и цифр ──────────────────────────────

class TestScenario2ColloquialClaim:
    """Проверяемое ядро выделяется без требования ключевого слова."""

    def test_no_keyword_predicate_but_core_present(self):
        # Ключевое доказательство механизма: узкий предикат молчит,
        # ядро всё равно найдено (иначе это был бы словарный фикс).
        assert fsg._has_predicate(COLLOQUIAL_CLAIM) is False
        assert fsg.has_checkable_core(COLLOQUIAL_CLAIM) is True

    @pytest.mark.asyncio
    async def test_explicit_request_checks_colloquial_claim(self):
        ctx = await _ctx(_background(), claim=COLLOQUIAL_CLAIM)
        decision = fsg.evaluate_suitability(
            COLLOQUIAL_CLAIM, None, ctx, target_ref={"chat_id": CHAT_ID},
            explicit_request=True)
        assert decision.decision == fsg.DECISION_CHECKABLE
        assert decision.claim_items
        # грубость/сарказм не становятся «бессмыслицей»
        assert decision.claim_type in (fsg.CHECKABLE_FACTUAL_CLAIM,
                                       fsg.MIXED_CLAIM)

    @pytest.mark.asyncio
    async def test_hint_with_core_is_enough_for_explicit_request(self):
        """Явный запрос с тезисом в самом вызове: «фактчек <утверждение>»."""
        decision = fsg.evaluate_suitability(
            "вообще без текста", "стикер со ссылкой сливает кошелёк", None,
            target_ref={"chat_id": CHAT_ID}, allow_needs_context=False,
            explicit_request=True)
        assert decision.decision == fsg.DECISION_CHECKABLE
        assert decision.reason_code == fsg._REASON_HINT


# ── (3) Факт + эмоция ──────────────────────────────────────────────────────

class TestScenario3MixedClaim:
    @pytest.mark.asyncio
    async def test_factual_part_checked_opinion_separated(self):
        ctx = await _ctx(_background(), claim=MIXED_CLAIM)
        decision = fsg.evaluate_suitability(
            MIXED_CLAIM, None, ctx, target_ref={"chat_id": CHAT_ID},
            explicit_request=True)
        assert decision.decision == fsg.DECISION_CHECKABLE
        assert decision.claim_type == fsg.MIXED_CLAIM
        texts = [i.text for i in decision.claim_items]
        assert any("заражает" in t for t in texts)
        # оценка остаётся оценкой, а не проверяемым пунктом
        assert all("отвратительно" not in t for t in texts)


# ── (4) Два тезиса в одном посте ───────────────────────────────────────────

class TestScenario4TwoClaims:
    @pytest.mark.asyncio
    async def test_both_claims_recognised_per_claim_policy(self):
        ctx = await _ctx(_background(), claim=TWO_CLAIMS)
        decision = fsg.evaluate_suitability(
            TWO_CLAIMS, None, ctx, target_ref={"chat_id": CHAT_ID},
            explicit_request=True)
        assert decision.decision == fsg.DECISION_CHECKABLE
        assert len(decision.claim_items) == 2
        # действующая per-claim policy планировщика: своя единица на тезис
        units = fsp._claim_units(decision.claim_items, TWO_CLAIMS)
        assert len(units) == 2
        assert "крадёт" in units[0] and "угоняют" in units[1]


# ── (5) Явный фактчек на пустое сообщение ──────────────────────────────────

class TestScenario5EmptyTarget:
    @pytest.mark.asyncio
    async def test_handler_honest_unavailable_without_invented_verdict(
            self, gate_on, handler_env):
        target = _make_msg(text=None, caption=None, message_id=TARGET_TG)
        msg = _make_msg(text="фактчек", message_id=TRIGGER_TG,
                        reply_to_message=target)
        service = _verdict_service()
        hfc._db = None                       # окружение недоступно (DI-off)
        hfc.setup_factcheck(service)
        bot = AsyncMock()
        await hfc.factcheck_handler(msg, bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in FACTCHECK_EMPTY_CONTEXT_PHRASES
        service.check_claim.assert_not_called()
        # выдуманного вердикта нет, ссылка — на целевое
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == \
            TARGET_TG

    @pytest.mark.asyncio
    async def test_v2_stops_before_paid_search(self):
        service = _verdict_service()
        req = orch.FactcheckRequest(
            chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
            target_tg_message_id=TARGET_TG, target_text="", kind="reply")
        bot = AsyncMock()
        outcome = await orch.run_factcheck(req, service=service, db=None,
                                           bot=bot, cache=FakeCache())
        assert outcome == orch.OUTCOME_UNAVAILABLE
        sent = bot.send_message.await_args.args[1]
        assert sent in FACTCHECK_TARGET_UNAVAILABLE_PHRASES
        assert sent not in FACTCHECK_NO_CLAIM_PHRASES
        service.check_claim.assert_not_called()
        service.check_claim_envelope.assert_not_called()

    @pytest.mark.asyncio
    async def test_claim_found_in_related_material_is_checked(
            self, caplog):
        """§2.2: тезис живёт в связанном материале (соседнее сообщение) —
        это НЕ «нечего проверять»: тезис разрешается и проверяется."""
        rows = _background()
        rows.append(_row(8, "стикер со ссылкой заражает телефон и уводит "
                            "деньги с кошелька", tg=TARGET_TG - 1))
        rows.append(_row(9, "", tg=TARGET_TG))
        service = _verdict_service()
        req = orch.FactcheckRequest(
            chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
            target_tg_message_id=TARGET_TG, target_text="", kind="reply")
        bot = AsyncMock()
        with caplog.at_level("INFO"):
            outcome = await orch.run_factcheck(
                req, service=service, db=FakeDB(rows), bot=bot,
                cache=FakeCache())
        assert outcome == orch.OUTCOME_VERDICT
        assert service.check_claim.await_count == 1
        sent_service_arg = service.check_claim.await_args.args[0]
        assert "заражает" in sent_service_arg
        assert any("target_resolved=True" in r.getMessage()
                   and "admission=checkable" in r.getMessage()
                   for r in caplog.records)


# ── (6) Неоднозначные соседние сообщения ───────────────────────────────────

class TestScenario6AmbiguousTarget:
    @pytest.mark.asyncio
    async def test_clarification_not_no_claim_and_no_foreign_claim(self):
        rows = _clusters() + [_row(9, REFERENTIAL_TARGET, tg=TARGET_TG)]
        ctx = await _ctx(rows, claim=REFERENTIAL_TARGET)
        decision = fsg.evaluate_suitability(
            REFERENTIAL_TARGET, None, ctx, target_ref={"chat_id": CHAT_ID},
            explicit_request=True)
        assert decision.decision == fsg.DECISION_AMBIGUOUS
        assert decision.reason_code == fsg._REASON_AMBIGUOUS
        assert fsg.admission_label(decision) == fsg.ADMISSION_AMBIGUOUS_TARGET
        # чужой тезис не приписан цели: сама цель не становится claim_item
        assert not any(i.text == REFERENTIAL_TARGET
                       for i in decision.claim_items)

    @pytest.mark.asyncio
    async def test_v2_asks_for_clarification(self, monkeypatch):
        rows = _clusters() + [_row(9, REFERENTIAL_TARGET, tg=TARGET_TG)]
        service = _verdict_service()
        req = orch.FactcheckRequest(
            chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
            target_tg_message_id=TARGET_TG, target_text=REFERENTIAL_TARGET,
            kind="reply")
        bot = AsyncMock()
        outcome = await orch.run_factcheck(
            req, service=service, db=FakeDB(rows), bot=bot, cache=FakeCache())
        assert outcome == orch.OUTCOME_AMBIGUOUS
        sent = bot.send_message.await_args.args[1]
        assert sent in FACTCHECK_CLARIFY_PHRASES
        assert sent not in FACTCHECK_NO_CLAIM_PHRASES
        service.check_claim.assert_not_called()
        service.check_claim_envelope.assert_not_called()


# ── (7) Тезис есть, доказательств не хватило ───────────────────────────────

class TestScenario7InsufficientEvidence:
    @pytest.mark.asyncio
    async def test_insufficient_evidence_is_not_no_claim(
            self, monkeypatch, caplog):
        verdict_ns = types.SimpleNamespace(
            verdict_text=("Проверил доступные материалы: проверяемых ссылок, "
                          "подтверждающих заражение через стикер, не нашёл."),
            factual_verdict="insufficient_evidence",
            temporal_status="contextual", evaluated_period=None,
            uncertainty=None, reason="temporal_insufficient_evidence",
            as_of=None, evidence_refs=(), parts=())
        run_ns = types.SimpleNamespace(
            verdict_text=verdict_ns.verdict_text, verdict=verdict_ns,
            evidence_rows=(), fallback_used=False)

        async def _fake_envelope(db, ref, **kwargs):
            return object(), None

        async def _fake_record(db, run, **kwargs):
            return "run-1"

        monkeypatch.setattr(tf, "build_envelope", _fake_envelope)
        monkeypatch.setattr(tf, "record_temporal_run", _fake_record)
        monkeypatch.setattr(mca_gates, "temporal_factcheck_enabled",
                            lambda: True)

        service = _verdict_service()
        service.check_claim_envelope = AsyncMock(return_value=run_ns)
        req = orch.FactcheckRequest(
            chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
            target_tg_message_id=TARGET_TG, target_text=FORWARD_CLAIM,
            kind="reply")
        bot = AsyncMock()
        with caplog.at_level("INFO"):
            outcome = await orch.run_factcheck(
                req, service=service, db=FakeDB(_background()), bot=bot,
                cache=FakeCache())
        assert outcome == orch.OUTCOME_VERDICT
        assert service.check_claim_envelope.await_count == 1
        sent = bot.send_message.await_args.args[1]
        assert sent not in FACTCHECK_NO_CLAIM_PHRASES
        assert "недостаточно данных" in sent.lower()
        assert any("verdict_stage=insufficient_evidence" in r.getMessage()
                   for r in caplog.records)
        assert any("admission=checkable" in r.getMessage()
                   for r in caplog.records)


# ── (8) Повтор после раннего отказа + параллельные вызовы ──────────────────

class TestScenario8CooldownAndSingleFlight:
    def test_outcome_sets_match_orchestrator(self):
        assert hfc._EARLY_OUTCOMES == set(orch.REFUNDABLE_OUTCOMES)
        assert hfc._VERDICT_OUTCOME == orch.OUTCOME_VERDICT
        # вердикт НЕ возвращает слот, ранние исходы — возвращают
        assert orch.OUTCOME_VERDICT not in orch.REFUNDABLE_OUTCOMES
        for outcome in (orch.OUTCOME_NO_CLAIM, orch.OUTCOME_UNAVAILABLE,
                        orch.OUTCOME_AMBIGUOUS, orch.OUTCOME_ERROR,
                        orch.OUTCOME_BUSY):
            assert outcome in orch.REFUNDABLE_OUTCOMES

    @pytest.mark.asyncio
    async def test_persistent_tracker_refund_deletes_slot(
            self, monkeypatch):
        """Прод-режим (PersistentCooldownTracker): снятие слота — DELETE той
        же строки throttle_state scope='factcheck' (без новой схемы)."""
        calls = []

        class _Conn:
            async def execute(self, sql, params):
                calls.append((sql, params))

        class _DB:
            async def write_transaction(self, op, *, op_name, chat_id):
                await op(_Conn())

        tracker = types.SimpleNamespace(_scope="factcheck", _db=_DB())
        monkeypatch.setattr(hfc, "_cooldown", tracker)
        assert await hfc._refund_cooldown(CHAT_ID, USER_ID) is True
        sql, params = calls[0]
        assert "DELETE FROM throttle_state" in sql
        assert params == ("factcheck", CHAT_ID, USER_ID)
        # вердикт слот не снимает (антиспам/лимит сохраняются)
        calls.clear()
        await hfc._settle_cooldown(CHAT_ID, USER_ID, orch.OUTCOME_VERDICT)
        assert calls == []

    @pytest.mark.asyncio
    async def test_retry_after_early_refusal_not_blocked(
            self, gate_on, handler_env):
        service = _verdict_service()
        hfc._db = None
        hfc.setup_factcheck(service)
        bot = AsyncMock()
        empty = _make_msg(text=None, message_id=TARGET_TG)
        first = _make_msg(text="фактчек", message_id=TRIGGER_TG,
                          reply_to_message=empty)
        await hfc.factcheck_handler(first, bot=bot)
        assert hfc._cooldown.remaining(CHAT_ID, USER_ID) == 0

        claim = _make_msg(text="стикер со ссылкой заражает телефон",
                          message_id=TARGET_TG + 10)
        second = _make_msg(text="фактчек", message_id=TRIGGER_TG + 10,
                           reply_to_message=claim)
        await hfc.factcheck_handler(second, bot=bot)
        assert service.check_claim.await_count == 1
        # повтор прошёл в реальную проверку, а не в фразу троттлинга
        assert bot.send_message.await_args.args[1] == \
            "проверил: заражение через стикер не подтверждается"

    @pytest.mark.asyncio
    async def test_single_flight_and_antispam_preserved(
            self, gate_on, handler_env):
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_check(*args, **kwargs):
            started.set()
            await release.wait()
            return "проверил: тезис не подтверждается"

        service = _verdict_service()
        service.check_claim = AsyncMock(side_effect=_slow_check)
        hfc._db = None
        hfc.setup_factcheck(service)
        bot = AsyncMock()

        def _trigger(mid):
            claim = _make_msg(text="стикер со ссылкой заражает телефон",
                              message_id=mid)
            return _make_msg(text="фактчек", message_id=mid + 1,
                             reply_to_message=claim)

        task = asyncio.create_task(
            hfc.factcheck_handler(_trigger(TARGET_TG), bot=bot))
        await started.wait()
        # Параллельный дубль, пока первый прогон в работе → троттлинг.
        await hfc.factcheck_handler(_trigger(TARGET_TG + 100), bot=bot)
        assert service.check_claim.await_count == 1
        throttle_sent = bot.send_message.await_args.args[1]
        assert "мин" in throttle_sent or "сек" in throttle_sent
        release.set()
        await task
        # Реальный вердикт слот НЕ возвращает — антиспам сохранён.
        assert hfc._cooldown.remaining(CHAT_ID, USER_ID) > 0
        await hfc.factcheck_handler(_trigger(TARGET_TG + 200), bot=bot)
        assert service.check_claim.await_count == 1
