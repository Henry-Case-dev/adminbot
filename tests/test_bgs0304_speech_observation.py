"""BGS-03/BGS-04 — контракт: речевые guard'ы только наблюдают.

BEHAVIOR-GATES-SIMPLIFICATION-01 (owner input 2026-11-05, §4 BGS-03 и
§5 BGS-04):

* живые фразы словаря («по моим наблюдениям», «я нейросеть», «мои
  промпты», «сейчас пошучу») и их цитаты проходят байт-в-байт;
* настоящие машинные маркеры (<thought>, ``fact:ID``, ``msg:ID``,
  target-маркер) по-прежнему вычищаются — узким техническим sanitizer'ом;
* ложное совпадение не превращает ответ в пустой Telegram message;
* стиль/метатекст/формат не вызывают повторной генерации (счётчик вызовов);
* числа/имена/отрицания сохраняются там, где трансформация реально идёт;
* правила владельца (no_emoji/no_quotes/trailing_period) применяются ровно
  один раз и не портят защищённые спаны.

TEST-LIFECYCLE: CONTRACT owner=BGS-03/BGS-04.
"""
import asyncio

import pytest

from services import negative_constraints as nc
from services import outgoing_guard as og
from services import public_speech_guard as psg
from services import style_policy as sp
from services.target_marking import TARGET_MARKER_CORE

OWNER_PHRASES = (
    "по моим наблюдениям",
    "я нейросеть",
    "мои промпты",
    "сейчас пошучу",
)


def _run(coro):
    return asyncio.run(coro)


# ════════════════════════════════════════════════════════════════════════════
# 1. BGS-03: живые фразы и цитаты — байт-в-байт
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("phrase", OWNER_PHRASES)
def test_natural_phrase_passthrough_byte_identical(phrase):
    """Фраза словаря в обычном ответе: находка есть, правок нет."""
    text = f"Слушай, {phrase} — и это нормальная живая речь."
    res = psg.guard_public_text(text, seam="unit")
    assert res.text == text
    assert res.changed is False and res.repaired is True
    assert res.findings                    # код для владельца виден


@pytest.mark.parametrize("phrase", OWNER_PHRASES)
def test_quoted_phrase_passthrough_byte_identical(phrase):
    """Цитата той же фразы в кавычках не вырезается."""
    text = f"Он буквально сказал «{phrase}», я процитировал."
    res = psg.guard_public_text(text)
    assert res.text == text
    assert f"«{phrase}»" in res.text


def test_observation_codes_are_not_private_text():
    """R17: в событии только коды/locations, без полного текста."""
    from services import mca_events
    seen: list = []
    orig = mca_events.emit_mca_event

    def spy(event_name, *, outcome, **fields):
        seen.append((event_name, outcome, fields))
        return orig(event_name, outcome=outcome, **fields)

    mca_events.emit_mca_event = spy
    try:
        text = "По моим наблюдениям, я нейросеть и мои промпты тут ни при чём."
        psg.guard_public_text(text, seam="direct_l2", chat_id=42)
    finally:
        mca_events.emit_mca_event = orig

    events = [e for e in seen if e[0] == "speech_observation"]
    assert len(events) == 1
    _name, outcome, fields = events[0]
    assert outcome == "success"
    assert fields["stage"] == "direct_l2"           # место срабатывания
    assert fields["component"] == "public_speech_guard"
    payload = str(fields["usage_json"])
    assert "по моим наблюдениям" in payload          # код находки
    assert "мои промпты" in payload
    assert text not in payload                       # полного текста нет
    assert fields.get("chat_id") == 42


def test_false_match_never_empties_message():
    """Полный ответ из одной фразы словаря доставляется, а не в пустоту."""
    for phrase in OWNER_PHRASES:
        res = psg.guard_public_text(phrase)
        assert res.text == phrase


def test_guard_is_fail_soft(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("guard down")

    monkeypatch.setattr(psg, "find_backstage_metatext", boom)
    res = psg.guard_public_text("любой текст")
    assert res.text == "любой текст" and res.findings == ()


# ════════════════════════════════════════════════════════════════════════════
# 2. BGS-03 §3: настоящие машинные маркеры по-прежнему вычищаются
# ════════════════════════════════════════════════════════════════════════════

def test_real_machine_markers_are_still_stripped():
    """Технический sanitizer остаётся узким и рабочим."""
    raw = (f"Ответ: <thought>внутренний черновик</thought> fact:123 "
           f"msg:45 и {TARGET_MARKER_CORE} конец.")
    out = og.sanitize_outgoing(raw)
    assert "<thought>" not in out and "внутренний черновик" not in out
    assert "fact:123" not in out and "msg:45" not in out
    assert TARGET_MARKER_CORE not in out
    assert out.startswith("Ответ:") and out.endswith("конец.")
    assert og.sanitize_outgoing(out) == out          # идемпотентно


def test_conversation_with_colons_and_quotes_untouched():
    """Обычная речь с двоеточиями/кавычками/словом «аналитик» цела."""
    text = 'Аналитик сказал: «данные врут», и на этом всё.'
    assert og.sanitize_outgoing(text) == text
    assert psg.guard_public_text(text).text == text


def test_speech_guard_does_not_touch_live_words_in_technical_cleanup():
    """Техническая очистка не расширяется на живые слова словаря."""
    text = "По моим наблюдениям, я нейросеть — и это шутка."
    assert og.sanitize_outgoing(text) == text


# ════════════════════════════════════════════════════════════════════════════
# 3. BGS-04 §1/§4: стиль, клише, метатекст, формат не дают reroll
# ════════════════════════════════════════════════════════════════════════════

class _Gen:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0

    async def __call__(self, messages):
        self.calls += 1
        return self.texts[min(self.calls - 1, len(self.texts) - 1)]


@pytest.mark.system2
@pytest.mark.parametrize("text", [
    "как ИИ, подводя итог: надеюсь, помог",
    "| a | b |\n|---|---|",
    "- пункт один\n- пункт два",
])
def test_no_extra_generation_for_style_or_format(text):
    """Стиль/список/таблица: ровно один вызов генератора, текст цел."""
    gen = _Gen([text])
    out, stats = _run(run_verbalize(gen, text))
    assert gen.calls == 1
    assert out == text
    assert stats["attempts"] == 1 and stats["retries"] == 0
    assert stats["anti_cliche_retries"] == 0


async def run_verbalize(gen, text):
    rules = None
    if text.startswith("|") or text.startswith("- "):
        rules = nc.channel_enabled_rules("plain", "serious")
    return await nc.verbalize_validated(
        gen, [{"role": "user", "content": "x"}], enabled_rules=rules)


@pytest.mark.system2
def test_no_extra_generation_for_metatext():
    """Смысловая метаречь: код наблюдения, но второго вызова нет."""
    text = "Весь интернет я проверил."
    gen = _Gen([text])
    out, stats = _run(nc.verbalize_validated(
        gen, [{"role": "user", "content": "x"}],
        metatext_reason=psg.metatext_retry_reason))
    assert gen.calls == 1
    assert out == text
    assert stats["metatext_observed"] == [
        "metatext_semantic:total_verification_variant"]


# ════════════════════════════════════════════════════════════════════════════
# 4. BGS-04 §2/§3: числа/имена/отрицания там, где трансформация реальна
# ════════════════════════════════════════════════════════════════════════════

def test_form_contract_catches_changed_number_negation_and_name():
    contract = nc.FormContract(source_text="Вася не писал 12 сообщений",
                               roster_names=("Вася",))
    assert nc.check_form_contract("Вася не писал 12 сообщений", contract) is None
    assert nc.check_form_contract("Вася писал 12 сообщений", contract) == \
        nc.FORM_GUARD_REJECTED                       # отрицание потеряно
    assert nc.check_form_contract("Вася не писал 13 сообщений", contract) == \
        nc.FORM_GUARD_REJECTED                       # число подменено
    assert nc.check_form_contract("Петя не писал 12 сообщений", contract) == \
        nc.FORM_GUARD_REJECTED                       # чужое имя


@pytest.mark.system2
def test_transform_path_keeps_facts_and_stays_bounded():
    """Stage-1 → Stage-2: нарушение формы → один повтор, затем проверенный
    черновик; числа/имена/отрицания не теряются."""
    draft = "Вася не писал 12 сообщений, это точно."

    async def gen(messages):
        gen.calls += 1
        return "Вася писал 13 сообщений"            # всегда ломает форму

    gen.calls = 0
    out, stats = _run(nc.verbalize_validated(
        gen, [{"role": "user", "content": "x"}],
        form_contract=nc.FormContract(source_text=draft,
                                      roster_names=("Вася",)),
        fallback_text=draft))
    assert gen.calls == 2                            # ≤1 form-повтор
    assert stats["form_retry"] is True
    assert stats["form_fallback"] is True
    assert out == draft                              # исходные факты целы


@pytest.mark.system2
def test_free_path_never_empties_reply_for_number():
    """Свободная генерация: неподтверждённое число не съедает реплику."""
    class _Claim:
        value = 9
        unit = "messages"

    async def gen(messages):
        gen.calls += 1
        return "он писал 7 сообщений"

    gen.calls = 0
    out, stats = _run(nc.verbalize_validated(
        gen, [{"role": "user", "content": "x"}],
        numeric_contract=nc.NumericContract(claims=(_Claim(),))))
    assert gen.calls == 1
    assert out.strip()                                # не пусто
    assert stats["numeric_claim_retry"] is False
    assert stats["numeric_claim_mismatch"] == 1


# ════════════════════════════════════════════════════════════════════════════
# 5. BGS-04 §6: один проход правил владельца, защищённые спаны целы
# ════════════════════════════════════════════════════════════════════════════

def _owner_policy():
    doc = sp.build_document(rules=[
        {"id": "quotation_marks.hard.no_graphic", "kind": "quotation_marks",
         "strictness": "hard", "params": {"mode": "strip"},
         "conflict_strategy": "exempt_protected"},
        {"id": "emoji.hard.off", "kind": "emoji", "strictness": "hard",
         "params": {}, "conflict_strategy": "exempt_protected"},
        {"id": "trailing_period.hard.strip", "kind": "trailing_period",
         "strictness": "hard", "params": {"ellipsis": "keep"},
         "conflict_strategy": "exempt_protected"},
    ])
    return sp.effective_policy_sync(global_doc=doc, context="regular")


def test_owner_rules_apply_exactly_once():
    """Второй проход по уже нормализованному тексту — no-op."""
    policy = _owner_policy()
    text = "🤖 Он сказал «привет»."
    first = _run(sp.apply_style_policy(text, policy=policy, chat_id=0,
                                       record=False))
    second = _run(sp.apply_style_policy(first.text, policy=policy,
                                        chat_id=0, record=False))
    assert first.text == "Он сказал привет"
    assert second.text == first.text
    assert second.repaired == 0


def test_owner_rules_keep_protected_spans():
    """Код/URL не искажаются even при активных правилах владельца."""
    policy = _owner_policy()
    text = "Код `print(\"x\")` и ссылка https://example.org/a?b=1."
    out = _run(sp.apply_style_policy(text, policy=policy, chat_id=0,
                                     record=False))
    assert "`print(\"x\")`" in out.text
    assert "https://example.org/a?b=1" in out.text


def test_verbatim_quote_untouched_by_owner_rules():
    """Дословная цитата (фактчек) не переписывается правилами владельца."""
    policy = _owner_policy()
    quote = "Вердикт: «цитата источника» — полностью."
    out = _run(sp.apply_style_policy(quote, policy=policy, chat_id=0,
                                     verbatim=True, record=False))
    assert out.text == quote
    kept = _run(sp.apply_style_policy(
        quote, policy=policy, chat_id=0, record=False,
        extra_protected=["«цитата источника»"]))
    assert "«цитата источника»" in kept.text
