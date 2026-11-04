"""BGS-04.10 — контроль отрицания вне числового окна (G2b).

Приёмка строки BGS-04.10: «Операция „перефразируй без изменения фактов“ не
меняет „не“, числа и имена; при недостижимой точности исходные данные
сохраняются, а ошибка трассируется».

До этой полосы отрицание ловилось ТОЛЬКО в окне ±40 символов вокруг числа
(`_number_signature`), поэтому перефраз без чисел мог молча заменить
«Вася не писал» → «Вася писал» и пройти гард. Теперь у form-контракта есть
G2b: множества куэ-токенов отрицания источника и результата обязаны совпасть.

Что проверяется здесь:

* (a) потеря «не» в перефразе без чисел → отказ узкой проверки, второго
  LLM-вызова нет, доставляется исходный черновик (+ видимая трассировка);
* (b) отрицание сохранено (и эквивалентное двойное отрицание) → отказа нет,
  лишнего вызова нет;
* (c) обычные слова на «не-/ни-» («неделя», «низкий», «небо») — не куэ,
  ложных отказов нет;
* (d) «не» рядом с числом ловится прежним механизмом (регресс не сломан);
* (e) клише/метатекст в перефразе — ноль лишних генераций (BGS-04 §1);
* (f) свободная генерация (без `form_contract`) не получила нового гейта.

TEST-LIFECYCLE: CONTRACT owner=BGS-04.10
"""
import asyncio

import pytest

from services import negative_constraints as nc
from services import public_speech_guard as psg

#: Проверенный черновик Stage-1 — БЕЗ чисел: именно этот случай раньше
#: проходил гард при подмене отрицания.
DRAFT = "По проверке, Вася не писал в чат про это — это подтверждено."
#: Тот же смысл с ПОДМЕНЁННЫМ отрицанием (искажение факта).
INVERTED = "По проверке, Вася писал в чат про это — это подтверждено."


def _run(coro):
    return asyncio.run(coro)


class _Gen:
    """Генератор-счётчик: отдаёт заданные кандидаты и хранит messages."""

    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []

    async def __call__(self, messages):
        self.calls += 1
        self.messages.append(list(messages))
        return self.texts[min(self.calls - 1, len(self.texts) - 1)]


# ════════════════════════════════════════════════════════════════════════════
# (a) потеря «не» без чисел → видимая находка → исходные данные, без повтора
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.system2
def test_negation_lost_without_numbers_is_rejected_and_source_draft_wins():
    """«Вася не писал в чат» → «Вася писал в чат»: узкая проверка видит
    подмену, второго LLM-вызова нет, доставляется исходный черновик
    (REMOVE-LEGACY-REPHRASING v2.0: литературного повтора больше нет)."""
    gen = _Gen([INVERTED, DRAFT])             # второй кандидат не запросят
    out, stats = _run(nc.verbalize_validated(
        gen,
        [{"role": "user", "content": "перефразируй без изменения фактов"}],
        form_contract=nc.FormContract(source_text=DRAFT),
        fallback_text=DRAFT))

    assert gen.calls == 1                    # второго автора нет вовсе
    assert out == DRAFT                      # исходные данные сохранены
    assert "не писал" in out
    assert stats["form_retry"] is False
    assert stats["form_fallback"] is True
    assert stats["form_guard_reason"] == nc.FORM_GUARD_REJECTED
    assert stats["form_guard_rejects"] == 1  # искажение видно в телеметрии
    assert stats["fallback"] is True
    assert stats["semantic_rewrite_count"] == 0


@pytest.mark.system2
def test_negation_lost_is_rejected_directly_by_form_contract():
    """Тот же случай на уровне гарда: код отказа, а не None."""
    assert nc.check_form_contract(INVERTED, nc.FormContract(source_text=DRAFT)) \
        == nc.FORM_GUARD_REJECTED
    # Добавленное отрицание — тоже искажение факта.
    assert nc.check_form_contract(
        DRAFT, nc.FormContract(source_text=INVERTED)) == nc.FORM_GUARD_REJECTED


@pytest.mark.system2
def test_no_second_generation_even_when_model_could_fix():
    """Даже «исправленный» вариант не запрашивается: второй литературной
    стадии нет — доставляются исходные данные, причина видима."""
    good = "Как и сказано в проверке, Вася в чат про это не писал."
    gen = _Gen([INVERTED, good])
    out, stats = _run(nc.verbalize_validated(
        gen,
        [{"role": "user", "content": "перефразируй без изменения фактов"}],
        form_contract=nc.FormContract(source_text=DRAFT),
        fallback_text=DRAFT))

    assert gen.calls == 1
    assert out == DRAFT
    assert stats["form_retry"] is False
    assert stats["form_fallback"] is True
    assert stats["semantic_rewrite_count"] == 0


# ════════════════════════════════════════════════════════════════════════════
# (b) отрицание сохранено → отказа нет, лишнего вызова нет
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.system2
@pytest.mark.parametrize("candidate", [
    "Как показала проверка, в чат про это Вася не писал — подтверждено.",
    "Вася не писал в чат про это — так показала проверка.",
    "Проверка подтверждает: в чат про это Вася не отправлял сообщений.",
])
def test_negation_preserved_costs_no_extra_generation(candidate):
    """Отрицание на месте → один вызов, текст доставлен как есть."""
    gen = _Gen([candidate])
    out, stats = _run(nc.verbalize_validated(
        gen,
        [{"role": "user", "content": "перефразируй без изменения фактов"}],
        form_contract=nc.FormContract(source_text=DRAFT),
        fallback_text=DRAFT))

    assert gen.calls == 1
    assert out == candidate
    assert stats["form_retry"] is False
    assert stats["fallback"] is False


def test_added_negation_cue_is_a_violation():
    """Добавленный куэ — тоже изменение факта («не писал» → «никогда не
    писал» добавляет утверждение о всей истории)."""
    assert nc.check_form_contract(
        "Вася никогда не писал в чат про это.",
        nc.FormContract(source_text=DRAFT)) == nc.FORM_GUARD_REJECTED


@pytest.mark.system2
@pytest.mark.parametrize("source, candidate", [
    # Эквивалентное двойное отрицание: два куэ дают утверждение.
    ("Он не мог не сказать об этом.", "Он сказал об этом."),
    ("Нельзя не заметить эту разницу.", "Эту разницу стоит заметить."),
    ("Он не без таланта.", "Он талантлив."),
])
def test_equivalent_double_negation_is_not_a_violation(source, candidate):
    """Двойное отрицание источника ≡ утверждение результата — не отказ."""
    assert nc.check_form_contract(candidate,
                                  nc.FormContract(source_text=source)) is None
    # И обратное направление тоже эквивалентно.
    assert nc.check_form_contract(source,
                                  nc.FormContract(source_text=candidate)) is None


def test_double_negation_really_inverted_is_still_rejected():
    """«не мог не сказать» → «не сказал» — уже не эквивалент: отказ."""
    assert nc.check_form_contract(
        "Он не сказал об этом.",
        nc.FormContract(source_text="Он не мог не сказать об этом.")) \
        == nc.FORM_GUARD_REJECTED


# ════════════════════════════════════════════════════════════════════════════
# (c) обычные слова на «не-/ни-» — не куэ (закрытый список, не префикс)
# ════════════════════════════════════════════════════════════════════════════

def test_ordinary_ne_ni_words_are_not_negation_cues():
    """«неделя», «низкий», «небо» и подобные не считаются отрицанием."""
    text = "На следующей неделе низкий небосклон закрыл небо над городом."
    assert nc._negation_signature(text) == frozenset()
    assert nc.check_form_contract(
        "На следующей неделе небо над городом заслонил низкий небосклон.",
        nc.FormContract(source_text=text)) is None


@pytest.mark.parametrize("word", [
    "неделя", "низкий", "небо", "немного", "нибудь", "нежный", "нитка",
    "недельный", "низина", "незнакомый",
])
def test_ne_ni_prefix_words_produce_no_cue(word):
    """Ни одно обычное слово на «не-/ни-» не даёт куэ."""
    assert nc._negation_signature(f"Тут {word} и всё.") == frozenset()


@pytest.mark.parametrize("text, cues", [
    ("Вася не писал.", {"не"}),
    ("Ни разу.", {"ни"}),
    ("Нет ответа.", {"нет"}),
    ("Нету ответа.", {"нету"}),
    ("Никогда не писал.", {"не", "никогда"}),
    ("Ответа нет и без него не будет.", {"нет", "без", "не"}),
    ("Нельзя так делать.", {"нельзя"}),
    ("Некуда идти.", {"некуда"}),
])
def test_closed_cue_list_is_stable(text, cues):
    """Закрытый список куэ (включая стяжённые формы) — как задокументирован."""
    assert nc._negation_signature(text) == frozenset(cues)


# ════════════════════════════════════════════════════════════════════════════
# (d) «не» рядом с числом — прежний механизм не сломан
# ════════════════════════════════════════════════════════════════════════════

def test_numeric_negation_path_still_fires():
    """Числовое окно ±40 продолжает помечать число как отрицаемое."""
    counts, negated = nc._number_signature("Вася не писал 12 сообщений")
    assert counts == {"12": 1}
    assert negated == {"12": 1}              # число попало в отрицание


@pytest.mark.system2
def test_numeric_claim_with_negation_still_rejected():
    """«не писал 12» → «писал 12»: отказ прежним G2-путём (регресс)."""
    source = "По проверке, Вася не писал 12 сообщений в чат."
    candidate = "По проверке, Вася писал 12 сообщений в чат."
    assert nc.check_form_contract(
        candidate, nc.FormContract(source_text=source)) == nc.FORM_GUARD_REJECTED

    gen = _Gen([candidate])
    out, stats = _run(nc.verbalize_validated(
        gen,
        [{"role": "user", "content": "перефразируй без изменения фактов"}],
        form_contract=nc.FormContract(source_text=source),
        fallback_text=source))

    assert gen.calls == 1
    assert out == source
    assert stats["form_fallback"] is True
    assert stats["form_retry"] is False


# ════════════════════════════════════════════════════════════════════════════
# (e) клише/метатекст в перефразе — ноль лишних генераций (BGS-04 §1)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.system2
def test_cosmetic_cliche_and_metatext_do_not_reroll_with_negation_guard():
    """Клише/метатекст не запускают повтор даже вместе с G2b: одна генерация."""
    candidate = ("Как ИИ, подводя итог: Вася не писал в чат про это. "
                 "Весь интернет я проверил.")
    gen = _Gen([candidate])
    out, stats = _run(nc.verbalize_validated(
        gen,
        [{"role": "user", "content": "перефразируй без изменения фактов"}],
        form_contract=nc.FormContract(source_text=DRAFT),
        fallback_text=DRAFT,
        metatext_reason=psg.metatext_retry_reason))

    assert gen.calls == 1
    assert out == candidate
    assert stats["anti_cliche_retries"] == 0
    assert stats["form_retry"] is False
    assert stats["metatext_observed"] == [
        "metatext_semantic:total_verification_variant"]


# ════════════════════════════════════════════════════════════════════════════
# (f) нового глобального гейта нет: свободная генерация не проверяется
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.system2
def test_free_generation_has_no_negation_gate():
    """Без `form_contract` (свободная генерация) гарда отрицания нет:
    один вызов, текст доставлен как сгенерирован."""
    gen = _Gen([INVERTED])
    out, stats = _run(nc.verbalize_validated(
        gen,
        [{"role": "user", "content": "расскажи, что было в чате"}]))

    assert gen.calls == 1
    assert out == INVERTED
    assert stats["fallback"] is False
    assert "form_guard_rejects" not in stats
