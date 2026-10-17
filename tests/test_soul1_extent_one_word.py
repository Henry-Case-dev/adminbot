"""SOUL-1 / W3 — one_word против micro: два действующих extent end-to-end.

Покрытие (SOUL-05.2/05.3/05.4/05.5/05.6 + SOUL-AMD.1.6/1.7):
  * ``one_word`` и ``micro`` — два разных extent со своими блоками/схемами
    (никакого alias/legacy-склейки в ``direct_l1.to_response_plan``);
  * ``one_word`` = ровно одно лексическое слово (кириллица/латиница/составные/
    восклицания), одна минимальная локальная правка, не полная регенерация;
  * ``micro`` НЕ ограничение в одно слово (мягкий диапазон 2-8 слов, дальний
    выход — наблюдаемый conflict без обрезки текста);
  * защищённый контент (код/URL/дословная цитата/структурированный вывод) не
    портится; конфликт формы разрешается явной иерархией;
  * явное ограничение длины пользователя старше комической экспансии; длинный
    технический/творческий запрос не срезается старым cap;
  * цепочка проверена до доставляемого payload (SOUL-05.6).

TEST-LIFECYCLE: CONTRACT + REGRESSION(one_word→micro) owner=SOUL-05/AMD.1.6
(soul-1, слайс W3)
"""
from __future__ import annotations

import pytest

from services import chat_params
from services import direct_l1 as _l1
from services import hot_config as hot
from services import response_extent as _extent
from services import style_policy as sp

CHAT_ID = 555

#: Зафиксированный текст micro-блока: его правка ломает байт-паритет OFF
#: (dumps P2/P4 в evidence/direct-runtime-assembly.txt).
FROZEN_MICRO_BLOCK = (
    "ОЖИДАЕМАЯ ПОЛНОТА: МИКРО. Ответ - одна короткая фраза или да/нет. "
    "Без разворотов и списков: ровно то, о чём спросили.")


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


@pytest.fixture(autouse=True)
def _clean_state():
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    yield
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


# ═══ два разных extent (SOUL-05.3/05.4) ═════════════════════════════════════

def test_extents_are_distinct_and_no_silent_collapse():
    assert "one_word" in _extent.EXTENTS and "micro" in _extent.EXTENTS
    plan = _l1.L1Plan(extent="one_word")
    assert plan.to_response_plan().extent == "one_word"
    micro = _l1.L1Plan(extent="micro")
    assert micro.to_response_plan().extent == "micro"
    auto = _l1.L1Plan(extent="auto")
    assert auto.to_response_plan().extent == ""      # auto → без блока
    # Явная форма пользователя — тот же строгий extent, не micro.
    plan.apply_form_override(_extent.explicit_form_override("ответь одним словом"))
    assert plan.effective_extent() == "one_word"
    assert plan.to_response_plan().extent == "one_word"


def test_one_word_and_micro_have_their_own_blocks():
    one = _extent.render_extent_block(_extent.ResponsePlan(extent="one_word"))
    micro = _extent.render_extent_block(_extent.ResponsePlan(extent="micro"))
    assert one != micro
    assert "РОВНО ОДНО СЛОВО" in one
    assert "МИКРО" in micro
    assert _extent._EXTENT_BLOCKS["micro"] == FROZEN_MICRO_BLOCK, (
        "текст micro-блока изменён — сломан байт-паритет OFF")
    assert "МИКРО" not in one


def test_micro_range_is_declared_and_not_one_word():
    assert _extent.MICRO_WORD_RANGE == (2, 8)
    assert _extent.ONE_WORD_MAX == 1
    assert _extent.MICRO_REPORT_MAX_WORDS >= _extent.MICRO_WORD_RANGE[1]


# ═══ валидатор one_word (SOUL-05.5) ═════════════════════════════════════════

@pytest.mark.parametrize("text", [
    "Да", "Конечно", "Ok", "кто-то", "Да!", "Да!!!", "Ну?", "ё-моё",
])
def test_one_word_accepts_exactly_one_lexical_word(text):
    check = _extent.check_extent(text, _extent.ResponsePlan(extent="one_word"))
    assert check.status == sp.STATUS_PASS, (text, check.as_dict())
    assert len(check.words) == 1


@pytest.mark.parametrize("text", [
    "Ну да", "Да, вполне", "Ответ: да", "Да или нет",
])
def test_one_word_rejects_second_word_without_truncating(text):
    check = _extent.check_extent(text, _extent.ResponsePlan(extent="one_word"))
    assert check.status == sp.STATUS_FAILED
    assert check.reason == "one_word_multiple_words"
    assert check.text == text, "текст не обрезается «до первого слова»"


def test_one_word_minimal_local_repair_of_service_tail():
    check = _extent.check_extent("Да 😀",
                                 _extent.ResponsePlan(extent="one_word"))
    assert check.status == sp.STATUS_REPAIRED
    assert check.text.strip() == "Да"
    assert check.reason == "one_word_extra_tail_removed"
    head = _extent.check_extent("😀 Да",
                                _extent.ResponsePlan(extent="one_word"))
    assert head.status == sp.STATUS_REPAIRED and head.text.strip() == "Да"
    tail = _extent.check_extent("Да [reply]",
                                _extent.ResponsePlan(extent="one_word"))
    assert tail.status == sp.STATUS_REPAIRED and tail.text == "Да"
    # Восклицание — разрешённая форма, не хвост.
    exclaim = _extent.check_extent("Да!!!",
                                   _extent.ResponsePlan(extent="one_word"))
    assert exclaim.status == sp.STATUS_PASS and exclaim.text == "Да!!!"


def test_one_word_conflict_with_protected_content():
    text = "Смотри https://example.org/path"
    check = _extent.check_extent(
        text, _extent.ResponsePlan(extent="one_word"),
        ignore_ranges=_extent.protected_ranges(_extent.segment(text))
        if hasattr(_extent, "protected_ranges") else ())
    assert check.status in (sp.STATUS_CONFLICT, sp.STATUS_FAILED)
    assert check.text == text, "payload не повреждён"


# ═══ micro не ограничение в одно слово (SOUL-05.3) ═════════════════════════

def test_micro_has_no_one_word_cap():
    plan = _extent.ResponsePlan(extent="micro")
    ok = _extent.check_extent("Да, вполне нормально", plan)
    assert ok.status == sp.STATUS_PASS
    assert len(ok.words) > 1
    short = _extent.check_extent("Да", plan)
    assert short.status == sp.STATUS_PASS, "одно слово в micro допустимо"


def test_micro_far_overflow_is_observable_conflict_without_truncation():
    plan = _extent.ResponsePlan(extent="micro")
    long_text = " ".join(["слово"] * 25)
    check = _extent.check_extent(long_text, plan)
    assert check.status == sp.STATUS_CONFLICT
    assert check.reason == "micro_extent_exceeded"
    assert check.text == long_text
    soft = _extent.check_extent(" ".join(["слово"] * 10), plan)
    assert soft.status == sp.STATUS_PASS
    assert soft.reason == "micro_soft_exceeded"


# ═══ приоритет длины и старый cap (SOUL-05.4) ══════════════════════════════

def test_explicit_user_length_limit_beats_comic_expansion():
    assert _extent.resolve_extent_priority(
        explicit_form="one_word", l1_extent="longform",
        comic_strategy="absurd_escalation") == ("one_word", "explicit")
    assert _extent.resolve_extent_priority(
        explicit_form="longform", l1_extent="one_word",
        comic_strategy="literalism") == ("longform", "explicit")
    assert _extent.resolve_extent_priority(
        l1_extent="detailed", comic_strategy="deadpan") == ("detailed", "l1")
    assert _extent.resolve_extent_priority(
        l1_extent="auto", comic_strategy="literalism") == ("", "auto")


def test_long_technical_request_is_not_truncated_by_old_cap():
    plan = _extent.ResponsePlan(extent="longform", structure="report")
    block = _extent.render_extent_block(plan)
    assert "Длина определяется задачей" in block
    assert "одно-два предложения" not in block.lower()
    capped = ("Ты должен отвечать ОЧЕНЬ коротко.\n"
              "Твой ответ должен состоять СТРОГО ИЗ ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ.\n"
              "Полезная часть канона.")
    scrubbed, removed = _extent.scrub_for_plan(capped, plan)
    assert removed >= 2 and "СТРОГО ИЗ ОДНОГО" not in scrubbed
    assert "Полезная часть канона" in scrubbed
    # Для one_word/micro старый cap не трогается (нет longform-плана).
    for extent in ("one_word", "micro"):
        same, count = _extent.scrub_for_plan(
            capped, _extent.ResponsePlan(extent=extent))
        assert same == capped and count == 0


# ═══ проход + payload (SOUL-05.2/05.6) ═════════════════════════════════════

def _enable_style(monkeypatch, doc=None):
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "1")
    values = {"flags.speech_style_policy_enabled": True}
    if doc is not None:
        values[sp.DOC_KEY] = doc
    hot.set_config_cache(FakeHot(values))
    chat_params.set_chat_params_cache(FakeChatCache({}))


@pytest.mark.asyncio
async def test_one_word_reaches_payload_as_exactly_one_word(monkeypatch):
    _enable_style(monkeypatch, sp.build_document(
        presets=["no_trailing_period"], owner=1))
    outcome = await sp.apply_style_policy(
        "Да.", chat_id=CHAT_ID, plan=_extent.ResponsePlan(extent="one_word"))
    assert outcome.text == "Да"
    assert outcome.extent_status == sp.STATUS_PASS
    payload = outcome.text  # то, что уходит в send после сериализации plain
    check = sp.verify_outbound_payload(payload, policy=outcome.policy,
                                       plan=_extent.ResponsePlan(
                                           extent="one_word"))
    assert check.payload_status == "ok"
    assert len(_extent.lexical_words(payload)) == 1


@pytest.mark.asyncio
async def test_one_word_violation_is_honest_not_silently_passed(monkeypatch):
    _enable_style(monkeypatch, sp.build_document(
        presets=["no_trailing_period"], owner=1))
    outcome = await sp.apply_style_policy(
        "Да, конечно", chat_id=CHAT_ID,
        plan=_extent.ResponsePlan(extent="one_word"))
    assert outcome.extent_status == sp.STATUS_FAILED
    assert outcome.styled is True       # правил формы нет — нарушен extent
    assert outcome.as_dict()["extent"]["reason"] == "one_word_multiple_words"
    assert outcome.text == "Да, конечно", "текст не срезан"


@pytest.mark.asyncio
async def test_micro_answer_is_not_collapsed_to_one_word(monkeypatch):
    _enable_style(monkeypatch, sp.build_document(
        presets=["no_trailing_period"], owner=1))
    outcome = await sp.apply_style_policy(
        "Да, вполне нормально.", chat_id=CHAT_ID,
        plan=_extent.ResponsePlan(extent="micro"))
    assert outcome.text == "Да, вполне нормально"
    assert len(_extent.lexical_words(outcome.text)) == 3
    assert outcome.extent_status == sp.STATUS_PASS


@pytest.mark.asyncio
async def test_off_flag_leaves_extent_text_untouched(monkeypatch):
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "0")
    hot.set_config_cache(FakeHot({"flags.speech_style_policy_enabled": True}))
    chat_params.set_chat_params_cache(FakeChatCache({}))
    outcome = await sp.apply_style_policy(
        "Да 😀", chat_id=CHAT_ID, plan=_extent.ResponsePlan(extent="one_word"))
    assert outcome.applied is False
    assert outcome.text == "Да 😀", "OFF-путь не меняет текст"
    assert outcome.skip_reason == "style_policy_disabled"
