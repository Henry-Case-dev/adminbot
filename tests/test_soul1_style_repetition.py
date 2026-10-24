"""SOUL-1 / W3 — антизалипание (SOUL-09.0-09.3): наблюдаемо и пропорционально.

Покрытие:
  * повторяемость оценивается по СКОЛЬЗЯЩЕМУ окну собственных фраз (лексические
    n-граммы), а не по одному ban-list (SOUL-09.1);
  * некритичный повтор не запускает дорогую генерацию: сначала локальная
    замена, и она не переписывает суть ответа (SOUL-09.2);
  * динамический ban-list capped, с TTL и архивом, без персональных имён и
    секретов (SOUL-09.2);
  * удачный повтор цитаты/устойчивая привычка персонажа без повода не
    наказываются; защищённые сегменты не трогаются (SOUL-09.1);
  * наблюдаемость R17-safe (только числа/хеши, без текста ответа).

TEST-LIFECYCLE: CONTRACT owner=SOUL-09.0-09.3 (soul-1, слайс W3)
"""
from __future__ import annotations

import json

import pytest

from services import chat_params
from services import hot_config as hot
from services import style_policy as sp

CHAT_A = 9001
CHAT_B = 9002


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, **kwargs):
        self.values[key] = value


class FakeChatCache:
    async def get_chat_params(self, chat_id):
        return {"overrides": {}}


@pytest.fixture(autouse=True)
def _clean_state():
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    yield
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


def enable_style(monkeypatch, doc=None):
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "1")
    values = {"flags.speech_style_policy_enabled": True}
    if doc is not None:
        values[sp.DOC_KEY] = doc
    hot.set_config_cache(FakeHot(values))
    chat_params.set_chat_params_cache(FakeChatCache())


# ═══ скользящее окно и классификация повторов (SOUL-09.1) ══════════════════

def test_sliding_window_sees_own_recent_phrases():
    sp.record_bot_output(CHAT_A, "кот сегодня вел себя как чиновник на приеме")
    findings = sp.detect_repetition(
        "кот сегодня вел себя как чиновник на приеме", CHAT_A)
    assert findings
    assert findings[0]["severity"] == "critical"
    assert findings[0]["kind"] == "whole_message"


def test_partial_ngram_repeat_is_observable():
    sp.record_bot_output(CHAT_A, "он опять пришел с этой идеей про налог")
    findings = sp.detect_repetition("с этой идеей про налог и ничего больше",
                                    CHAT_A)
    assert findings, "повтор n-грамма не замечен"
    assert all(row["kind"] in ("ngram", "whole_message") for row in findings)
    assert findings[0]["phrase_sha12"], "нет R17-safe идентификатора"


def test_window_is_per_chat_and_capped():
    for index in range(sp.REPEAT_WINDOW_MAX + 5):
        sp.record_bot_output(CHAT_A, f"ответ номер {index} про кота")
    view = sp.repetition_view(CHAT_A)
    assert view["window"] == sp.REPEAT_WINDOW_MAX
    assert sp.repetition_view(CHAT_B)["window"] == 0
    assert sp.detect_repetition("ответ номер 0 про кота", CHAT_A) == ()


def test_ttl_expiry_ignores_old_phrases():
    sp.record_bot_output(CHAT_A, "старая фраза про кота и налоги", now=1000.0)
    findings = sp.detect_repetition(
        "старая фраза про кота и налоги", CHAT_A,
        now=1000.0 + sp.REPEAT_TTL_SECONDS + 1)
    assert findings == (), "протухшая запись окна не наказывается"
    fresh = sp.detect_repetition("старая фраза про кота и налоги", CHAT_A,
                                 now=1000.0 + 60)
    assert fresh


def test_short_habitual_phrase_is_not_punished():
    sp.record_bot_output(CHAT_A, "ну да")
    findings = sp.detect_repetition("ну да", CHAT_A)
    # Короткая привычка характера не становится sticky-повтором для правки.
    assert all(row["severity"] != "sticky" for row in findings)


# ═══ capped/TTL ban-list без имён и секретов (SOUL-09.2) ════════════════════

def test_dynamic_ban_list_is_capped_with_archive_and_ttl():
    for index in range(sp.BAN_MAX + 10):
        assert sp.register_dynamic_ban(CHAT_A, f"шаблонная фраза номер {index}")
    view = sp.dynamic_bans_view(CHAT_A)
    assert view["active"] == sp.BAN_MAX
    assert view["cap"] == sp.BAN_MAX
    assert view["ttl_seconds"] == sp.BAN_TTL_SECONDS
    assert view["hashes"] and len(view["hashes"]) <= 10
    # TTL-вытеснение уводит запись в bounded архив.
    sp.register_dynamic_ban(CHAT_A, "ещё одна фраза",
                            now=sp.BAN_TTL_SECONDS * 3)
    assert sp.dynamic_bans_view(CHAT_A)["archived"] >= 1


@pytest.mark.parametrize("phrase", [
    "Иван Петров снова пришёл",             # персональное имя
    "смотри https://example.org/secret",    # ссылка
    "напиши @vasya прямо сейчас",           # упоминание
    "код 4829137465012345 не подходит",     # длинный числовой ряд
    "ключ sk-abcdefghijklmnopqrstuvwxyz12", # секретоподобный токен
])
def test_ban_list_rejects_personal_names_and_secrets(phrase):
    assert sp.register_dynamic_ban(CHAT_A, phrase) is False
    assert sp.dynamic_bans_view(CHAT_A)["active"] == 0


def test_ban_list_accepts_neutral_cliche():
    assert sp.register_dynamic_ban(CHAT_A, "классика жанра как всегда") is True


# ═══ пропорциональная реакция в проходе (SOUL-09.2) ════════════════════════

@pytest.mark.asyncio
async def test_sticky_tail_repeat_is_repaired_locally(monkeypatch):
    enable_style(monkeypatch, sp.build_document(
        presets=["no_trailing_period"], owner=1))
    sp.record_bot_output(CHAT_A, "Ну и классика жанра как всегда")
    outcome = await sp.apply_style_policy(
        "Разбор простой. Ну и классика жанра как всегда",
        chat_id=CHAT_A)
    assert outcome.repetition, "повтор не наблюдаем"
    assert "Ну и классика жанра как всегда" not in outcome.text
    assert outcome.text.startswith("Разбор простой"), "суть ответа сохранена"


@pytest.mark.asyncio
async def test_repeat_does_not_trigger_extra_generation(monkeypatch):
    enable_style(monkeypatch, sp.build_document(
        presets=["no_trailing_period"], owner=1))
    calls = {"n": 0}

    async def repair(text, instruction):        # смысловой ремонт не нужен
        calls["n"] += 1
        return "переписано"

    sp.record_bot_output(CHAT_A, "Ну и классика жанра как всегда")
    outcome = await sp.apply_style_policy(
        "Разбор простой. Ну и классика жанра как всегда",
        chat_id=CHAT_A, repair=repair, repair_allowed=True)
    assert calls["n"] == 0, "некритичный повтор вызвал дорогую генерацию"
    assert outcome.repair_used == 0
    assert outcome.repetition


@pytest.mark.asyncio
async def test_observation_only_without_owner_policy(monkeypatch):
    """Без владельческой политики повтор ТОЛЬКО наблюдается (текст не теряем)."""
    enable_style(monkeypatch, None)
    sp.record_bot_output(CHAT_A, "Ну и классика жанра как всегда")
    text = "Разбор простой. Ну и классика жанра как всегда"
    outcome = await sp.apply_style_policy(text, chat_id=CHAT_A)
    assert outcome.repetition
    assert outcome.text == text, "тихая потеря текста без политики владельца"


@pytest.mark.asyncio
async def test_protected_repeat_is_not_touched(monkeypatch):
    enable_style(monkeypatch, sp.build_document(
        presets=["no_trailing_period"], owner=1))
    quote = "«дословная цитата источника целиком»"
    sp.record_bot_output(CHAT_A, quote)
    outcome = await sp.apply_style_policy(
        "Ответ такой. " + quote, chat_id=CHAT_A)
    # Повтор не срезан: слова цитаты на месте. Типографика кавычек — отдельное
    # заводское правило A (« » → "), поэтому сравниваем текст без кавычек.
    words = "дословная цитата источника целиком"
    assert words in outcome.text, "защищённый повтор срезан"
    assert outcome.text.strip().endswith(words + '"'), outcome.text


@pytest.mark.asyncio
async def test_repetition_event_is_emitted_without_leaking_text(monkeypatch):
    """Notable-событие о повторе эмитится и не содержит текста (R17)."""
    enable_style(monkeypatch, sp.build_document(
        presets=["no_trailing_period"], owner=1))
    events: list = []
    from services import mca_events as _events
    real = _events.emit_mca_event

    def capture(name, **fields):
        events.append((name, fields))
        return real(name, **fields)

    monkeypatch.setattr(_events, "emit_mca_event", capture)
    sp.record_bot_output(CHAT_A, "Ну и классика жанра как всегда")
    outcome = await sp.apply_style_policy(
        "Разбор простой. Ну и классика жанра как всегда", chat_id=CHAT_A,
        emit_events=True, stage="test_stage")
    assert events, "событие о повторе не эмитировано"
    name, fields = events[0]
    assert name == "style_policy" and fields["stage"] == "test_stage"
    blob = json.dumps(fields, ensure_ascii=False, default=str)
    assert "классика" not in blob and "Разбор простой" not in blob
    assert outcome.repetition


@pytest.mark.asyncio
async def test_repetition_is_observable_and_r17_safe(monkeypatch):
    """R17-safe витрина повтора: только числа/хеши, без текста ответа."""
    enable_style(monkeypatch, sp.build_document(
        presets=["no_trailing_period"], owner=1))
    secret_phrase = "Ну и классика жанра как всегда"
    sp.record_bot_output(CHAT_A, secret_phrase)
    outcome = await sp.apply_style_policy(
        "Разбор простой. " + secret_phrase, chat_id=CHAT_A)
    blob = json.dumps(outcome.as_dict(), ensure_ascii=False)
    assert "классика" not in blob and "Разбор простой" not in blob
    assert outcome.as_dict()["repetition"], "повтор не попал в телеметрию"
    assert sp.repetition_view(CHAT_A)["window"] >= 1


# ═══ правка не трогает посторонний текст (review-w3 F2) ════════════════════
# Требования: SOUL-09.0/09.1/09.2 («не переписывать суть ответа», «не наказывать
# без повода»). Контракт: снимается ТОЛЬКО повторяющаяся финальная фраза.

PREV_PHRASE = "Ну да, это классика жанра, как обычно."


def _soft_only_doc():
    """Документ без правил формы: изолирует локальную правку повтора."""
    return sp.build_document(presets=["casual_concise"], owner=1)


@pytest.mark.asyncio
async def test_repeat_in_first_sentence_keeps_unrelated_tail(monkeypatch):
    """Повтор в ПЕРВОМ предложении: посторонний хвост не удаляется."""
    enable_style(monkeypatch, _soft_only_doc())
    sp.record_bot_output(CHAT_A, PREV_PHRASE)
    raw = "Ну да, это классика жанра. И это важный нюанс."
    outcome = await sp.apply_style_policy(raw, chat_id=CHAT_A)
    assert outcome.text == raw, "удалено предложение без повтора"
    assert outcome.repetition, "повтор должен остаться наблюдаемым"
    assert not any(row.get("repaired") for row in outcome.repetition)


@pytest.mark.asyncio
async def test_repeat_in_middle_keeps_unrelated_tail(monkeypatch):
    """Повтор в середине: хвост без повтора не срезается."""
    enable_style(monkeypatch, _soft_only_doc())
    sp.record_bot_output(CHAT_A, PREV_PHRASE)
    raw = ("Первое предложение. Ну да, это классика жанра. "
           "И это важный нюанс.")
    outcome = await sp.apply_style_policy(raw, chat_id=CHAT_A)
    assert outcome.text == raw, "удалён хвост без повтора"
    assert outcome.repetition


@pytest.mark.asyncio
async def test_repeat_as_tail_is_still_removed(monkeypatch):
    """Повтор ИМЕННО в финальной фразе — прежнее пропорциональное поведение."""
    enable_style(monkeypatch, _soft_only_doc())
    sp.record_bot_output(CHAT_A, PREV_PHRASE)
    outcome = await sp.apply_style_policy(
        "Разбор простой. Ну да, это классика жанра.", chat_id=CHAT_A)
    assert outcome.text == "Разбор простой.", outcome.text
    assert any(row.get("repaired") for row in outcome.repetition)


@pytest.mark.asyncio
async def test_no_repeat_is_a_noop(monkeypatch):
    """Нет повтора — текст не меняется и находок нет."""
    enable_style(monkeypatch, _soft_only_doc())
    sp.record_bot_output(CHAT_A, "совсем другая фраза про погоду и дела")
    raw = "Разбор простой. И это важный нюанс."
    outcome = await sp.apply_style_policy(raw, chat_id=CHAT_A)
    assert outcome.text == raw
    assert not outcome.repetition


@pytest.mark.asyncio
async def test_protected_repeat_is_exempted_not_trimmed(monkeypatch):
    """Повтор внутри защищённого сегмента (JSON) не режется: exempted."""
    enable_style(monkeypatch, sp.build_document(presets=["no_quotes"], owner=1))
    phrase = 'Данные {"note": "важный текст"} и всё'
    sp.record_bot_output(CHAT_A, phrase)
    raw = "Разбор простой. " + phrase
    outcome = await sp.apply_style_policy(raw, chat_id=CHAT_A)
    assert '{"note": "важный текст"}' in outcome.text, "защищённый повтор срезан"
    assert outcome.text == raw, "посторонний/защищённый текст изменён"
    assert outcome.repetition, "повтор должен быть наблюдаем"
    assert not any(row.get("repaired") for row in outcome.repetition)
    assert outcome.exempted >= 1

