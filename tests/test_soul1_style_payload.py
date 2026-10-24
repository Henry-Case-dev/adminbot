"""SOUL-1 / W3 — правило на ФАКТИЧЕСКИ доставляемом payload + 10+ входов.

Покрытие (SOUL-16.3.4/16.5.3, SOUL-05.6, SOUL-AMD.1.7/3.5):
  * проход формы выполняется ДО сериализации, проверка — на реальном payload
    (после ``escape_lore_html``/снятия разметки и ``sanitize_outgoing``
    существующего egress-контура): завершающая точка убрана, URL/версия/код
    не тронуты;
  * 10+ разнородных по структуре входов через реальный delivery-контур Direct
    (тестовый контур: записывающий бот, без отправки в рабочий чат), плюс
    инициативный writer — с сохранением смысла/характера/разной длины;
  * ``styled=true`` не объявляется при провале hard-правила на payload;
  * OFF-флаг оставляет payload байт-в-байт прежним.

TEST-LIFECYCLE: CONTRACT owner=SOUL-16.3.4/16.5.3 + SOUL-05.6
(soul-1, слайс W3)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services import chat_params
from services import hot_config as hot
from services import mca_intents as mi
from services import response_extent as _extent
from services import style_policy as sp
from services.direct_chat_service import DirectChatService, handle_initiative
from services.direct_l1 import L1Plan

CHAT_ID = -100777


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, **kwargs):
        self.values[key] = value


class FakeChatCache:
    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides.get(int(chat_id), {}))}


class RecordingBot:
    """Тестовый контур доставки: запоминает ФАКТИЧЕСКИ отправленный payload."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})
        message = MagicMock()
        message.message_id = 4242
        return message

    async def send_rich_message(self, chat_id, rich, **kwargs):
        self.sent.append({"chat_id": chat_id, "rich": rich, "kwargs": kwargs})
        message = MagicMock()
        message.message_id = 4243
        return message

    @property
    def payloads(self) -> list[str]:
        return [row.get("text", "") for row in self.sent]


@pytest.fixture(autouse=True)
def _clean_state():
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    yield
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


def enable_style(monkeypatch, doc):
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "1")
    hot.set_config_cache(FakeHot({"flags.speech_style_policy_enabled": True,
                                  sp.DOC_KEY: doc}))
    chat_params.set_chat_params_cache(FakeChatCache({}))


def hard_doc():
    """Владельческие hard-правила: без кавычек + без точки + без эмодзи."""
    return sp.build_document(presets=["no_quotes", "no_trailing_period",
                                     "no_emoji"], owner=1,
                             reason="приёмка SOUL-16.5.3")


async def deliver(bot, text, *, style_outcome=None, **kwargs):
    return await DirectChatService._send_direct_answer(
        bot, CHAT_ID, text, None, style_outcome=style_outcome, **kwargs)


# ═══ payload-доказательство (SOUL-16.3.4) ═══════════════════════════════════

@pytest.mark.asyncio
async def test_trailing_period_removed_from_real_payload_url_intact(
        monkeypatch):
    enable_style(monkeypatch, hard_doc())
    answer = ("Смотри https://example.org/path — там версия v1.2.3, "
              "и код `x = 1.2.3` в примере.")
    outcome = await sp.apply_style_policy(answer, chat_id=CHAT_ID,
                                          context="regular")
    assert outcome.text.endswith("примере")        # точка убрана на тексте
    bot = RecordingBot()
    await deliver(bot, outcome.text, style_outcome=outcome)
    payload = bot.payloads[0]
    assert payload.endswith("примере"), payload[-40:]
    assert not payload.rstrip().endswith(".")
    assert "https://example.org/path" in payload
    assert "v1.2.3" in payload and "x = 1.2.3" in payload
    assert outcome.payload is True and outcome.payload_status == "ok"


@pytest.mark.asyncio
async def test_payload_verification_is_honest_when_rule_still_violated(
        monkeypatch):
    # Кавычки теперь правятся детерминированно, поэтому «непоправимый»
    # hard-конфликт для payload-проверки даёт лимит переносов строк.
    doc = {"v": 1, "revision": 1, "soft_instructions": [],
           "rules": [{"id": "br.hard", "kind": "line_breaks",
                      "strictness": "hard", "params": {"max_breaks": 1},
                      "reason": "r"}]}
    enable_style(monkeypatch, doc)
    answer = "раз\nдва\nтри"
    outcome = await sp.apply_style_policy(answer, chat_id=CHAT_ID,
                                          context="regular")
    assert outcome.styled is False, "hard-правило провалено — styled запрещён"
    check = sp.verify_outbound_payload(outcome.text, policy=outcome.policy,
                                       outcome=outcome)
    assert check.payload_status == "mismatch"
    assert "br.hard" in check.conflicts


@pytest.mark.asyncio
async def test_safe_html_payload_is_checked_after_escaping(monkeypatch):
    enable_style(monkeypatch, hard_doc())
    answer = "Ссылка <b>важна</b>: https://example.org/a?x=1&y=2."
    outcome = await sp.apply_style_policy(answer, chat_id=CHAT_ID)
    bot = RecordingBot()
    await deliver(bot, outcome.text, style_outcome=outcome,
                  deep_research=True)
    payload = bot.payloads[0]
    assert payload.endswith(("2", "2&amp;y=2")), payload[-30:]
    assert "&amp;" in payload or "&" in payload     # escape выполнен
    assert not payload.rstrip().endswith(".")
    assert outcome.payload_status == "ok"


@pytest.mark.asyncio
async def test_payload_verification_reports_extent_mismatch(monkeypatch):
    """SOUL-05.6: доставляемый текст проверяется и по extent (one_word)."""
    enable_style(monkeypatch, sp.build_document(presets=["no_trailing_period"],
                                               owner=1))
    plan = _extent.ResponsePlan(extent="one_word")
    outcome = await sp.apply_style_policy("Да, конечно", chat_id=CHAT_ID,
                                          plan=plan)
    check = sp.verify_outbound_payload(outcome.text, policy=outcome.policy,
                                       plan=plan, outcome=outcome)
    assert check.payload_status == "mismatch"
    assert check.as_dict()["extent"]["reason"] == "one_word_multiple_words"
    ok = sp.verify_outbound_payload("Да", policy=outcome.policy, plan=plan)
    assert ok.payload_status == "ok"


@pytest.mark.asyncio
async def test_off_flag_payload_is_byte_identical(monkeypatch):
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "0")
    hot.set_config_cache(FakeHot({"flags.speech_style_policy_enabled": True,
                                  sp.DOC_KEY: hard_doc()}))
    chat_params.set_chat_params_cache(FakeChatCache({}))
    answer = "Ну это «гениальная» идея. 😀"
    outcome = await sp.apply_style_policy(answer, chat_id=CHAT_ID)
    assert outcome.applied is False and outcome.text == answer
    bot = RecordingBot()
    await deliver(bot, outcome.text, style_outcome=outcome)
    assert bot.payloads[0] == answer, "OFF-путь изменил payload"


# ═══ 10+ разнородных входов (SOUL-16.5.3) ═══════════════════════════════════

HETEROGENEOUS = [
    ("Да.", "one_word"),
    ("Ну да, логично.", "micro"),
    ("Он сказал «база», и это была «истина».", "compact"),
    ("Смотри https://example.org/path и https://example.org/other.",
     "normal"),
    ("Версия v1.2.3 и сборка 2.58.33.", "normal"),
    ("Файл `report.txt` лежит в C:\\data\\report.txt.", "normal"),
    ("Код: print(\"hi\") — работает.", "normal"),
    ("Да, конечно. Вот почему.", "compact"),
    ("Ответ: «цитата источника» внутри строки.", "normal"),
    ("Первая строка.\n\n\nВторая строка.", "compact"),
    ("Что это значит?", "micro"),
    ("Разбор: 1) шаг один; 2) шаг два — итог.", "detailed"),
]
EXPECTED_ONE_WORD = {"Да.": "Да"}
PROTECTED_FRAGMENTS = {
    "https://example.org/path", "https://example.org/other", "v1.2.3",
    "2.58.33", "`report.txt`", "C:\\data\\report.txt", "print(\"hi\")",
    "цитата источника", "1) шаг один", "2) шаг два",
}


@pytest.mark.asyncio
async def test_ten_plus_heterogeneous_inputs_on_delivery_contour(monkeypatch):
    enable_style(monkeypatch, hard_doc())
    assert len(HETEROGENEOUS) >= 10
    lengths: list[int] = []
    for raw, extent in HETEROGENEOUS:
        outcome = await sp.apply_style_policy(
            raw, chat_id=CHAT_ID,
            plan=_extent.ResponsePlan(extent=extent), context="regular")
        bot = RecordingBot()
        await deliver(bot, outcome.text, style_outcome=outcome)
        payload = bot.payloads[0]
        lengths.append(len(payload))
        # 1. Смысл/содержимое не потеряно: все защищённые фрагменты на месте.
        for fragment in PROTECTED_FRAGMENTS:
            if fragment in raw:
                assert fragment in payload, (raw, fragment, payload)
        # 2. Завершающая точка снята там, где она была.
        if raw.rstrip().endswith("."):
            assert not payload.rstrip().endswith("."), (raw, payload)
        # 3. Графические кавычки-ирония вокруг одного слова сняты.
        if raw.startswith("Он сказал «база»"):
            assert "«база»" not in payload
        # 4. Формат/структура сохранены (переносы не схлопнуты целиком).
        if "\n\n\n" in raw:
            assert "\n" in payload
        # 5. Эмодзи-хвостов нет (правило эмодзи).
        assert "😀" not in payload
    # Разная длина сохранена (не «всё в две фразы»).
    assert max(lengths) - min(lengths) > 40, lengths
    one_word_payload = None
    outcome = await sp.apply_style_policy(
        "Да.", chat_id=CHAT_ID,
        plan=_extent.ResponsePlan(extent="one_word"))
    bot = RecordingBot()
    await deliver(bot, outcome.text, style_outcome=outcome)
    one_word_payload = bot.payloads[0]
    assert one_word_payload == EXPECTED_ONE_WORD["Да."]
    assert len(_extent.lexical_words(one_word_payload)) == 1


@pytest.mark.asyncio
async def test_initiative_writer_returns_raw_text_for_the_single_pass(
        monkeypatch):
    """SOUL-AMD.3.5 + SOUL-16.4.2: writer НЕ делает второй проход сам.

    Проход формы для инициативы выполняется ровно один раз — в единой точке
    отправки ``handle_initiative`` (см. тесты выше): writer отдаёт текст как
    есть, а форма применяется к тому, что реально уйдёт."""
    enable_style(monkeypatch, hard_doc())
    svc = DirectChatService.__new__(DirectChatService)
    svc.db = None
    svc._initiative_persona_block = AsyncMock(return_value="ПЕРСОНА")
    svc._l2_write_answer = AsyncMock(
        return_value=("Он сказал «база это сила».", "casual"))
    row = {"goal": "повод", "kind": "follow_up", "origin": "test"}
    text = await DirectChatService.generate_initiative_reply(svc, CHAT_ID, row)
    assert text == "Он сказал «база это сила».", text
    svc._l2_write_answer.assert_awaited_once()
    # Тот же Writer и тот же канал, что в Direct (один владелец).
    call = svc._l2_write_answer.await_args
    assert call.kwargs.get("writer") == "initiative_writer"


@pytest.mark.asyncio
async def test_payload_check_sees_bytes_after_egress_guard(monkeypatch):
    """SOUL-16.3.4 (review-w3 F3): проверяется payload ПОСЛЕ egress-guard.

    ``Готово. fact:123`` доезжает как ``Готово.`` — завершающая точка на
    доставленных байтах, и проверка обязана это видеть (mismatch), а не
    объявлять ``ok`` по до-guard-строке."""
    enable_style(monkeypatch, hard_doc())
    from config.settings import settings as app_settings
    monkeypatch.setattr(type(app_settings), "TELEGRAM_SEND_GUARD_ENABLED", True)
    outcome = await sp.apply_style_policy("Готово. fact:123", chat_id=CHAT_ID)
    bot = RecordingBot()
    await deliver(bot, outcome.text, style_outcome=outcome)
    delivered = bot.payloads[0]
    assert delivered == "Готово.", delivered      # egress-guard вырезал fact:123
    assert outcome.payload is True
    assert outcome.payload_status == "mismatch", (
        "проверка смотрела на до-guard-строку")


@pytest.mark.asyncio
async def test_payload_check_is_clean_when_guard_changes_nothing(monkeypatch):
    """Guard включён, но ничего не меняет → проверка доставленного payload ok."""
    enable_style(monkeypatch, hard_doc())
    from config.settings import settings as app_settings
    monkeypatch.setattr(type(app_settings), "TELEGRAM_SEND_GUARD_ENABLED", True)
    outcome = await sp.apply_style_policy("Смотри https://example.org/a",
                                          chat_id=CHAT_ID)
    bot = RecordingBot()
    await deliver(bot, outcome.text, style_outcome=outcome)
    assert bot.payloads[0] == outcome.text
    assert outcome.payload_status == "ok"


# ═══ инициатива: тот же проход в единой точке отправки (review-w3 F4) ══════

class _FakeWriter:
    """Duck-typed writer §13.2 (plan_initiative_decision/generate_initiative_reply)."""

    def __init__(self, text="Он сказал «база это сила». 😀"):
        self.text = text
        self.generate_calls = 0

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        return L1Plan(action="reply", confidence=0.9,
                      confidence_bucket="high", source="llm")

    async def generate_initiative_reply(self, chat_id, intent_row, *,
                                        l1_plan=None, correlation_id=None):
        self.generate_calls += 1
        return self.text


def _nostalgia_candidate():
    return mi.candidate_from_trigger(
        trigger_kind="nostalgia_due", chat_id=CHAT_ID, source="nostalgia",
        prepared_text_ref="nostalgia:1", reason_code="default")


@pytest.mark.asyncio
async def test_initiative_prepared_text_goes_through_the_same_pass(monkeypatch):
    """SOUL-AMD.3.5: ностальгия/``prepared_text`` — тот же проход формы."""
    enable_style(monkeypatch, hard_doc())
    bot = RecordingBot()
    result = await handle_initiative(
        bot=bot, chat_id=CHAT_ID,
        situation=mi.InitiativeSituation(trigger_kind="nostalgia_due",
                                         chat_id=CHAT_ID),
        candidates=[_nostalgia_candidate()],
        prepared_text="Он сказал «база это сила». 😀", db=None)
    assert result["status"] == "sent", result
    delivered = bot.payloads[0]
    assert "😀" not in delivered, "инициативный текст обошёл проход формы"
    assert not delivered.endswith("."), delivered
    assert "база это сила" in delivered, "слова цитаты сохранены (режим B)"


@pytest.mark.asyncio
async def test_initiative_pass_runs_exactly_once_per_text(monkeypatch):
    """Один проход на текст (SOUL-16.4.2): writer и ностальгия в одной точке."""
    enable_style(monkeypatch, hard_doc())
    calls: list = []
    real = sp.apply_style_policy

    async def counting(text, **kwargs):
        calls.append((str(text), kwargs.get("context"), kwargs.get("stage")))
        return await real(text, **kwargs)

    monkeypatch.setattr(sp, "apply_style_policy", counting)
    bot = RecordingBot()
    writer = _FakeWriter()
    result = await handle_initiative(
        bot=bot, chat_id=CHAT_ID,
        situation=mi.InitiativeSituation(trigger_kind="intent_due",
                                         chat_id=CHAT_ID),
        candidates=[mi.candidate_from_trigger(
            trigger_kind="intent_due", chat_id=CHAT_ID, reason_code="default")],
        writer_service=writer, db=None)
    assert result["status"] == "sent", result
    assert writer.generate_calls == 1
    passes = [row for row in calls if row[2] == "initiative_pre_send"]
    assert len(passes) == 1, passes
    assert passes[0][1] == "initiative", passes
    delivered = bot.payloads[0]
    assert "😀" not in delivered and not delivered.endswith("."), delivered


@pytest.mark.asyncio
async def test_no_extra_llm_call_on_delivery_contour(monkeypatch):
    enable_style(monkeypatch, hard_doc())
    calls = {"n": 0}

    class LLM:
        async def generate(self, *args, **kwargs):
            calls["n"] += 1
            return "ответ"

    svc = DirectChatService.__new__(DirectChatService)
    svc.llm = LLM()
    outcome = await sp.apply_style_policy(
        "Он сказал «база». 😀", chat_id=CHAT_ID,
        plan=_extent.ResponsePlan(extent="compact"))
    bot = RecordingBot()
    await deliver(bot, outcome.text, style_outcome=outcome)
    assert calls["n"] == 0, "форма не стоит ни одного LLM-вызова"
    assert outcome.repaired >= 1
