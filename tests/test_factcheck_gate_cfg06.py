"""CFG-06 W2 — suitability gate + ContextualClaimResolution (06B/06J/06I.6).

TEST-LIFECYCLE: CONTRACT owner=CFG-06

Контракты:
  * флаги default OFF → `_fetch_context_with_gate` байт-в-байт прежнего
    контекста, решение None (откат);
  * гейт многоступенчатый (06J.1): одна строка НИКОГДА не отказывает —
    needs_context → одно ограниченное расширение → решение;
  * no_claim возможен ТОЛЬКО после изучения контекста (06J.3) и без
    веб-скоупа (06J.5 unnecessary_search_rate = 0 на корпусе);
  * мат/ирония НЕ блокиратор: мат+тезис → checkable (06J.4);
  * атрибуция: contextual-тезис сохраняет автора анцедента, чужой тезис не
    приписывается цели (06I.6); два сопоставимых спора → ambiguous;
  * корпус-метрики (06J.5): false_refusal_rate = 0, false_contextual_claim_
    rate = 0 на фиксированном наборе а–з.
"""
import asyncio

import pytest

from config.settings import settings
from handlers import factcheck as hfc
from services import factcheck_context as fcx
from services import factcheck_suitability as fsg
from services import smart_cache as sc

CHAT_ID = -100555
TARGET_TG = 9000
TRIGGER_TG = 9001
THESIS_TG = 8900          # тезис ~50 сообщений раньше цели


def _row(i, text, *, tg=None, reply_to=None, author="Вася"):
    return {"id": 100 + i, "user_id": 1, "chat_id": CHAT_ID, "text": text,
            "reply_to_id": reply_to, "timestamp": 1000 + i,
            "media_type": "text", "author_name": author, "is_forward": False,
            "forward_source": None, "tg_message_id": tg}


def _dispute(name="килякетские дожди были кислотными и убили весь урожай",
             author="Вася", thesis_tg=THESIS_TG, base=0):
    """Кластер спора: тезис + реакции соседей (маркеры спора, replies)."""
    return [
        _row(base, name, tg=thesis_tg, author=author),
        _row(base + 1, "это бред", tg=thesis_tg + 1,
             reply_to=thesis_tg, author="Петя"),
        _row(base + 2, "источник где?", tg=thesis_tg + 2,
             reply_to=thesis_tg, author="Оля"),
        _row(base + 3, "пруфов не будет, знаю я это", tg=thesis_tg + 3,
             reply_to=thesis_tg + 1, author="Петя"),
    ]


def _fixture_case_b(count=120):
    """(б) тезис 50 сообщений раньше + референциальная цель «правда?»."""
    rows = []
    for i in range(count - 2):
        if i == 50:
            rows.extend(_dispute(base=i))
        else:
            rows.append(_row(i, f"болтовня номер {i}", tg=100 + i))
    rows.append(_row(count - 2, "правда?", tg=TARGET_TG))
    rows.append(_row(count - 1, "фактчек", tg=TRIGGER_TG))
    return rows


class FakeDB:
    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    async def get_messages_around(self, chat_id, target_tg_message_id,
                                  before, after):
        self.queries.append(("around", chat_id, before, after))
        return list(self._rows)

    async def get_recent_messages(self, chat_id, limit):
        self.queries.append(("recent", chat_id, limit))
        return list(self._rows[-limit:]) if limit else []


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get_update_marker(self, key, *, ttl_seconds):
        return self.store.get(key)

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.store[key] = payload


async def _ctx(rows, *, claim=""):
    return await fcx.build_wide_context(
        FakeDB(rows), CHAT_ID, target_tg_message_id=TARGET_TG,
        trigger_tg_message_id=TRIGGER_TG, claim_text=claim,
        cache=FakeCache())


@pytest.fixture
def both_on():
    olds = (getattr(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", False),
            getattr(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", False))
    object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", True)
    object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", olds[0])
    object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", olds[1])


@pytest.fixture
def restore_handler_db():
    old_db, old_service = hfc._db, hfc._service
    yield
    hfc._db, hfc._service = old_db, old_service


# ── OFF-паритет (откат) ──────────────────────────────────────────────────────

class TestGateOffParity:
    @pytest.fixture(autouse=True)
    def _wide_off(self, monkeypatch):
        # Решение владельца 25.10.2026: wide default ON. Этот класс
        # проверяет ОТКАТ (гейт выключен) — фиксируем откат явно.
        from services import factcheck_context as fcx
        monkeypatch.setattr(fcx, "wide_context_enabled", lambda: False)
    @pytest.mark.asyncio
    async def test_flags_default_off_and_hot_prio(self, monkeypatch):
        old = getattr(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", False)
        object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED",
                           False)
        try:
            assert fsg.suitability_gate_enabled() is False
            from services import hot_config as hot
            monkeypatch.setattr(
                hot, "get",
                lambda key, default=None: True
                if key == "flags.factcheck_suitability_gate" else default)
            assert fsg.suitability_gate_enabled() is True
        finally:
            object.__setattr__(settings,
                               "FACTCHECK_SUITABILITY_GATE_ENABLED", old)

    @pytest.mark.asyncio
    async def test_gate_off_byte_parity(self, restore_handler_db):
        rows = _fixture_case_b()
        db = FakeDB(rows)
        hfc._db = db
        actual, decision = await hfc._fetch_context_with_gate(
            CHAT_ID, 6, 6, target_tg_message_id=TARGET_TG,
            trigger_message_id=TRIGGER_TG, claim_text="правда?",
            user_hint=None)
        expected = await hfc._fetch_chat_context(
            CHAT_ID, 6, 6, target_tg_message_id=TARGET_TG,
            trigger_message_id=TRIGGER_TG, claim_text="правда?")
        assert actual == expected
        assert decision is None
        assert "фон: сжатая хронология" not in actual

    @pytest.mark.asyncio
    async def test_gate_on_requires_wide_context(
            self, restore_handler_db, monkeypatch):
        # W1 OFF + gate ON → прежний путь (гейт без структурированного
        # контекста не создаёт решений). Wide-откат уже зафиксирован
        # autouse-фикстурой класса.
        old = getattr(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", False)
        object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED",
                           True)
        try:
            db = FakeDB(_fixture_case_b())
            hfc._db = db
            feed, decision = await hfc._fetch_context_with_gate(
                CHAT_ID, 6, 6, target_tg_message_id=TARGET_TG,
                trigger_message_id=TRIGGER_TG, claim_text="правда?")
            assert decision is None
            assert feed == await hfc._fetch_chat_context(
                CHAT_ID, 6, 6, target_tg_message_id=TARGET_TG,
                trigger_message_id=TRIGGER_TG, claim_text="правда?")
        finally:
            object.__setattr__(settings,
                               "FACTCHECK_SUITABILITY_GATE_ENABLED", old)


# ── Многоступенчатость и классы (06B.2/06J.1/06J.3/06J.4) ───────────────────

class TestGateDecisions:
    @pytest.mark.asyncio
    async def test_case_a_direct_claim(self):
        rows = [*_dispute(), _row(10, "целевое", tg=TARGET_TG)]
        ctx = await _ctx(rows, claim="в Килякете выпало 120 мм осадков за сутки")
        d = fsg.evaluate_suitability(
            "в Килякете выпало 120 мм осадков за сутки", None, ctx,
            target_ref={"chat_id": CHAT_ID})
        assert d.decision == fsg.DECISION_CHECKABLE
        assert d.claim_type == fsg.CHECKABLE_FACTUAL_CLAIM
        assert d.scope == fsg.SCOPE_WEB
        assert d.claim_items and d.claim_items[0].source == "literal"
        assert d.gate_version == fsg.GATE_VERSION

    @pytest.mark.asyncio
    async def test_case_b_thesis_50_earlier_found(self):
        ctx = await _ctx(_fixture_case_b(), claim="правда?")
        d = fsg.evaluate_suitability("правда?", None, ctx,
                                     target_ref={"chat_id": CHAT_ID})
        assert d.decision == fsg.DECISION_CHECKABLE
        item = d.claim_items[0]
        assert item.source in ("topic", "reply_to")
        assert item.author == "Вася"            # автор АНЦЕДЕНТА
        assert item.anchor_tg_message_id == THESIS_TG

    @pytest.mark.asyncio
    async def test_case_c_other_author_topic_attribution(self):
        rows = [_row(i, f"болтовня номер {i}", tg=7000 + i) for i in range(6)]
        rows += [
            _row(10, "вакцина от гриппа содержит живой вирус штамм",
                 tg=8000, author="Петя"),
            _row(11, "да ну, это правда что ли", tg=8001, reply_to=8000,
                 author="Оля"),
            _row(12, "целевое", tg=TARGET_TG, author="Вася"),
        ]
        ctx = await _ctx(rows, claim="а прививки эти с живым вирусом — правда?")
        d = fsg.evaluate_suitability(
            "а прививки эти с живым вирусом — правда?", None, ctx,
            target_ref={"chat_id": CHAT_ID})
        assert d.decision == fsg.DECISION_CHECKABLE
        item = d.claim_items[0]
        assert item.author == "Петя"            # НЕ автор цели (06I.6)
        assert item.anchor_tg_message_id == 8000

    @pytest.mark.asyncio
    async def test_case_g_two_parallel_disputes_ambiguous(self):
        rows = [*_dispute(base=0, thesis_tg=8000),
                *_dispute(name="вакцина от гриппа содержит живой вирус",
                          author="Оля", thesis_tg=8100, base=10),
                _row(20, "целевое", tg=TARGET_TG)]
        ctx = await _ctx(rows, claim="ну и что там?")
        d = fsg.evaluate_suitability("ну и что там?", None, ctx,
                                     target_ref={"chat_id": CHAT_ID})
        assert d.decision == fsg.DECISION_AMBIGUOUS
        assert all(i.author != "Вася" for i in d.claim_items)

    @pytest.mark.asyncio
    async def test_case_d_long_dispute_referential_no_refusal(self):
        ctx = await _ctx(_fixture_case_b(count=320), claim="ну и что там?")
        d = fsg.evaluate_suitability("ну и что там?", None, ctx,
                                     target_ref={"chat_id": CHAT_ID})
        assert d.decision == fsg.DECISION_CHECKABLE
        assert d.claim_items

    @pytest.mark.asyncio
    async def test_case_e_nonsense_after_context_no_claim_no_search(self):
        rows = [*_dispute(), _row(10, "целевое", tg=TARGET_TG)]
        ctx = await _ctx(rows, claim="абв гдё жзик лсн прст")
        d = fsg.evaluate_suitability("абв гдё жзик лсн прст", None, ctx,
                                     target_ref={"chat_id": CHAT_ID})
        assert d.decision == fsg.DECISION_NO_CLAIM
        assert d.scope == fsg.SCOPE_NONE        # поиск не тратится (06J.5)

    @pytest.mark.asyncio
    async def test_profanity_with_claim_not_blocked(self):
        # 06J.4: мат НЕ regex-блокиратор — тезис с копулой проверяем.
        d = fsg.evaluate_suitability(
            "дрожжи это грибы, так что вся затея — херня", None, None,
            target_ref={"chat_id": CHAT_ID}, allow_needs_context=False)
        assert d.decision in (fsg.DECISION_CHECKABLE,
                              fsg.DECISION_NEEDS_CONTEXT)
        assert d.claim_type != fsg.NONSENSE

    @pytest.mark.asyncio
    async def test_sarcasm_with_checkable_core_not_refused(self):
        # 06B.4: ирония с конкретным утверждением — не отклоняется.
        d = fsg.evaluate_suitability(
            "ну конечно, дрожжи это грибы, гений", None, None,
            target_ref={"chat_id": CHAT_ID}, allow_needs_context=False)
        assert d.claim_type in (fsg.CHECKABLE_FACTUAL_CLAIM,
                                fsg.JOKE_IRONY)
        assert d.decision != fsg.DECISION_NO_CLAIM

    @pytest.mark.asyncio
    async def test_prediction_no_claim_scope_none(self):
        d = fsg.evaluate_suitability(
            "спартак станет чемпионом в следующем году", None, None,
            target_ref={"chat_id": CHAT_ID}, allow_needs_context=False)
        assert d.claim_type == fsg.PERSONAL_PREDICTION
        assert d.decision == fsg.DECISION_NO_CLAIM
        assert d.scope == fsg.SCOPE_NONE

    @pytest.mark.asyncio
    async def test_hint_explicit_check_request(self):
        d = fsg.evaluate_suitability(
            "проверь", "что дрожжи это грибы и их нельзя есть", None,
            target_ref={"chat_id": CHAT_ID}, allow_needs_context=False)
        assert d.decision == fsg.DECISION_CHECKABLE
        assert d.reason_code == fsg._REASON_HINT

    @pytest.mark.asyncio
    async def test_empty_target_context_unavailable_no_refusal(self):
        d = fsg.evaluate_suitability(None, None, None,
                                     target_ref={"chat_id": CHAT_ID})
        assert d.decision == fsg.DECISION_CONTEXT_UNAVAILABLE
        assert d.claim_type == fsg.UNSAFE_OR_UNAVAILABLE_TARGET

    @pytest.mark.asyncio
    async def test_temporal_hint_on_dated_claim(self):
        d = fsg.evaluate_suitability(
            "в 2019 году в килякете выпало 120 мм осадков", None, None,
            target_ref={"chat_id": CHAT_ID}, allow_needs_context=False)
        assert d.decision == fsg.DECISION_CHECKABLE
        assert d.temporal_hint is True


# ── needs_context-протокол (06J.1) ───────────────────────────────────────────

class TestNeedsContextProtocol:
    @pytest.mark.asyncio
    async def test_small_context_needs_then_expand_resolves(self):
        small = [*_dispute(base=0), _row(10, "целевое", tg=TARGET_TG)]
        ctx_small = await _ctx(small, claim="правда?")
        assert ctx_small is not None
        d1 = fsg.evaluate_suitability("правда?", None, ctx_small,
                                      target_ref={"chat_id": CHAT_ID})
        # <5 сообщений в срезе? нет — 6; сузим до критерия:
        rows_few = [*_dispute(base=0)[:3], _row(10, "целевое",
                                                tg=TARGET_TG)]
        ctx_few = await _ctx(rows_few, claim="правда?")
        d_few = fsg.evaluate_suitability("правда?", None, ctx_few,
                                         target_ref={"chat_id": CHAT_ID})
        assert d_few.decision == fsg.DECISION_NEEDS_CONTEXT
        del d1, ctx_small, small
        # расширение (один ограниченный дозапрос) → тезис найден
        big_db = FakeDB(_fixture_case_b(count=80))
        d2, ctx2 = await fsg.evaluate_with_expansion(
            big_db, CHAT_ID, claim_text="правда?", user_hint=None,
            target_tg_message_id=TARGET_TG,
            trigger_tg_message_id=TRIGGER_TG, cache=FakeCache())
        assert d2.decision == fsg.DECISION_CHECKABLE
        assert ctx2 is not None and d2.claim_items

    @pytest.mark.asyncio
    async def test_second_needs_context_degrades_honestly(self):
        # Контекст остаётся недостаточным и после расширения →
        # context_unavailable, НЕ отказ и НЕ выдуманный тезис (06I.8/06J.1).
        db = FakeDB([_row(0, "целевое", tg=TARGET_TG)])
        d, ctx = await fsg.evaluate_with_expansion(
            db, CHAT_ID, claim_text="правда?", user_hint=None,
            target_tg_message_id=TARGET_TG,
            trigger_tg_message_id=TRIGGER_TG, cache=FakeCache())
        assert d.decision == fsg.DECISION_CONTEXT_UNAVAILABLE
        assert d.claim_items == ()
        assert ctx is None or len(ctx.messages) < fsg._MIN_CONTEXT_MESSAGES


# ── Live-маршрутизация (06B.3): no_claim → короткая реплика без поиска ──────

class TestHandlerRouting:
    @pytest.mark.asyncio
    async def test_no_claim_route_skips_search(self, both_on,
                                                restore_handler_db,
                                                monkeypatch):
        rows = [*_dispute(), _row(10, "абв гдё жзик", tg=TARGET_TG)]
        db = FakeDB(rows)
        hfc._db = db

        class _NoService:
            def __getattr__(self, name):
                raise AssertionError("service не должен вызываться")

        hfc._service = _NoService()
        monkeypatch.setattr(sc, "get_smart_cache", lambda: FakeCache())
        feed, decision = await hfc._fetch_context_with_gate(
            CHAT_ID, 6, 6, target_tg_message_id=TARGET_TG,
            trigger_message_id=TRIGGER_TG, claim_text="абв гдё жзик",
            user_hint=None)
        assert decision is not None
        assert decision.decision == fsg.DECISION_NO_CLAIM
        assert decision.scope == fsg.SCOPE_NONE
        from services.smartmodule_phrases import FACTCHECK_NO_CLAIM_PHRASES
        assert FACTCHECK_NO_CLAIM_PHRASES       # пул реплик непуст
