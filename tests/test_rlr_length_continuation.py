"""REMOVE-LEGACY-REPHRASING v2.0 — R-08.14 / R-FAIL.2 / §3.2: продолжение
финального ответа при `finish_reason=length`.

Owner corrective `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`:
§3.2 («`finish_reason=length`: продолжать ТОТ ЖЕ логический ответ с явной
границей накопленных токенов; не выдавать обрезок и не запускать независимого
"переписчика"; при невозможности — честное техническое состояние»), §1
(«продолжение ответа ... не считать повторным Writer»), §7 (в трассе видно
`finish_reason` и классификацию LLM-вызовов, включая continuation),
R-08 строка «`finish_reason=length`», DoD §10 («continuation по length
сохранён, не маскирует unfinished outputs»).

ГЛАВНЫЙ ДЕФЕКТ ДО ПРАВКИ: сигнал `is_truncated`/`finish_reason` существовал на
объекте завершения (`LLMCompletion`), но финальный Writer читал только
`str`-фасад `generate()` — обрезанный ответ уходил в чат как готовый.

Что проверяет файл (на продовом шве `DirectChatService.handle →
_l2_write_answer`, а не только на хелперах):

* (a) обрезанный первый ответ → РОВНО одно продолжение с уже написанным
  текстом как префиксом; итог = часть1+часть2 без дублей и без обрыва слова;
* (b) провайдер повторил хвост → точное эхо снимается один раз;
* (c) продолжение невозможно (лимит / ошибка провайдера) → честный исход:
  обрезок НЕ публикуется как готовый ответ, второго варианта нет;
* (d) ответ не обрезан → ровно один вызов, текст байт-в-байт;
* (e) продолжение не считается `semantic_rewrite_count` (это тот же ответ,
  тот же автор: один литературный вызов, два вызова провайдера).

MUTATION: перестать читать сигнал обрезки (вернуть `self.llm.generate(...)` с
`str`, т.е. считать любой ответ завершённым) → (a) красный: в чат уходит
обрезанный текст `…в цело`, продолжения нет.

TEST-LIFECYCLE: CONTRACT owner=REMOVE-LEGACY-REPHRASING (R-08.14, R-FAIL.2)
"""
import pytest

from services.llm_client import LLMCompletion
from services import l2_continuation as cont

pytestmark = pytest.mark.system2


def _completion(text, finish_reason="stop"):
    """Настоящий объект завершения клиента (is_truncated — реальная логика)."""
    return LLMCompletion(
        text=text, finish_reason=finish_reason, provider="test-provider",
        model="test-model", usage=None, max_output_tokens_sent=1000,
        attempt=1, correlation_id="cid-test")


class _MetaLLM:
    """Двойник клиента, который отдаёт МЕТАДАННЫЕ завершения.

    `generate_with_metadata` определён на КЛАССЕ — как у настоящего
    `LLMClient`, поэтому продовый шов вызывает именно его (проверка
    возможности идёт по классу, авто-атрибуты моков её не включают).
    Текстовый фасад `generate` фиксируется отдельно: если через него пойдёт
    финальный Writer, тест это увидит.
    """

    def __init__(self, *, l1, writer):
        self.l1_reply = l1
        self.writer = list(writer)          # очередь (текст | Exception, finish)
        self.calls = []
        self.single_text = "обычный ответ"

    def _record(self, step, messages, correlation_id, text_facade):
        self.calls.append({"step": step, "messages": list(messages or []),
                           "correlation_id": correlation_id,
                           "text_facade": bool(text_facade)})

    def _next_writer(self, step):
        assert self.writer, f"неожиданный вызов {step!r}: очередь пуста"
        text, finish = self.writer.pop(0)
        if isinstance(text, Exception):
            raise text
        return _completion(text, finish)

    async def generate(self, messages, temperature=None, chat_id=None, *,
                       module=None, step=None, correlation_id=None, **kwargs):
        self._record(step, messages, correlation_id, True)
        if step == "l1_planner":
            return self.l1_reply
        return self.single_text

    async def generate_with_metadata(self, messages, temperature=None,
                                     chat_id=None, *, module=None, step=None,
                                     correlation_id=None, **kwargs):
        self._record(step, messages, correlation_id, False)
        if step == "l1_planner":
            return _completion(self.l1_reply, "stop")
        if step in ("l2_writer", "l2_continuation"):
            return self._next_writer(step)
        return _completion(self.single_text, "stop")

    def calls_of(self, step):
        return [c for c in self.calls if c["step"] == step]

    def text_facade_of(self, step):
        return [c for c in self.calls_of(step) if c["text_facade"]]


def _drive(monkeypatch, query, llm):
    """Продовый Direct-путь (`handle`) с двойником, отдающим метаданные."""
    from tests.test_asap7_direct_l1 import _drive as drive_handle
    from tests.test_asap7_direct_l1 import _plan_json

    assert not isinstance(llm.l1_reply, list)
    svc, react, bot, msg, user = drive_handle(monkeypatch, query, llm=llm)
    return svc, react, bot, msg, user


def _plan(**over):
    from tests.test_asap7_direct_l1 import _plan_json
    return _plan_json(**over)


def _stats_spy(monkeypatch):
    """Перехват `stats` РЕАЛЬНОГО `verbalize_validated` на продовом шве."""
    from services import direct_chat_service as dcs
    from services import negative_constraints as nc

    seen: dict = {}
    real = nc.verbalize_validated

    async def spy(generate_call, base_messages, **kwargs):
        text, stats = await real(generate_call, base_messages, **kwargs)
        seen["stats"] = stats
        return text, stats

    monkeypatch.setattr(dcs, "verbalize_validated", spy)
    return seen


def _delivered(svc):
    assert svc._send_direct_answer.await_count == 1
    return svc._send_direct_answer.await_args.args[2]


PART1 = "Сервер подняли ночью, но у базы потерялась цело"
PART2 = "стность: часть таблиц не отвечала."


# ════════════════════════════════════════════════════════════════════════════
# (a) Обрезка → ОДНО продолжение с префиксом; итог = часть1+часть2
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_truncated_answer_is_continued_once_with_prefix(monkeypatch):
    llm = _MetaLLM(l1=_plan(), writer=[(PART1, "length"), (PART2, "stop")])
    svc, react, bot, msg, user = _drive(monkeypatch, "что с сервером?", llm)

    await svc.handle(bot, msg, user)

    # Первое и главное: обрезок НЕ уходит как готовый ответ — склеенный текст.
    delivered = _delivered(svc)
    assert delivered == PART1 + PART2
    # Ровно один авторский вызов + ровно одно продолжение того же ответа.
    assert len(llm.calls_of("l2_writer")) == 1
    assert len(llm.calls_of("l2_continuation")) == 1
    # Оба — через метаданные, а не через текст-фасад (иначе сигнал не читается).
    assert llm.text_facade_of("l2_writer") == []
    assert llm.text_facade_of("l2_continuation") == []
    # Продолжение несёт уже написанный текст как префикс (явная граница).
    cont_calls = llm.calls_of("l2_continuation")
    messages = cont_calls[0]["messages"]
    assert messages[-2] == {"role": "assistant", "content": PART1}
    boundary = messages[-1]
    assert boundary["role"] == "user"
    assert str(len(PART1)) in boundary["content"]
    assert "токен" in boundary["content"]
    # Исходный контекст хода сохранён: тот же system/user, что у первого вызова.
    assert messages[:-2] == llm.calls_of("l2_writer")[0]["messages"]

    # Ни обрыва слова на стыке, ни дубля.
    assert "целостность" in delivered
    assert delivered.count("целостность") == 1


# ════════════════════════════════════════════════════════════════════════════
# (b) Провайдер повторил хвост → точное эхо снимается один раз
# ════════════════════════════════════════════════════════════════════════════

TAIL = "Тут важно, что сервер не отвечал."
PREFIX_B = "Первое: логи чистые. " + TAIL
ECHO = TAIL + " Поэтому базу перезапустили."


@pytest.mark.asyncio
async def test_repeated_tail_is_removed_exactly_once(monkeypatch):
    llm = _MetaLLM(l1=_plan(), writer=[(PREFIX_B, "length"), (ECHO, "stop")])
    svc, react, bot, msg, user = _drive(monkeypatch, "что было?", llm)

    await svc.handle(bot, msg, user)

    delivered = _delivered(svc)
    assert delivered == PREFIX_B + " Поэтому базу перезапустили."
    # Повторённое предложение осталось ровно один раз, продолжение сохранено.
    assert delivered.count("сервер не отвечал") == 1
    assert delivered.endswith("Поэтому базу перезапустили.")


# ════════════════════════════════════════════════════════════════════════════
# (c) Продолжение невозможно → честный исход, обрезок не публикуется
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cap_exhausted_does_not_publish_truncated_text(monkeypatch):
    """Провайдер обрывает каждый фрагмент: лимит продолжений исчерпан.

    Обрезок НЕ уходит как готовый ответ, второго варианта/второго автора нет.
    """
    writer = [(PART1, "length")] + [(" ещё", "length")
                                    for _ in range(cont.MAX_CONTINUATION_CALLS)]
    llm = _MetaLLM(l1=_plan(), writer=writer)
    svc, react, bot, msg, user = _drive(monkeypatch, "что с сервером?", llm)

    await svc.handle(bot, msg, user)

    assert svc._send_direct_answer.await_count == 0
    assert len(llm.calls_of("l2_writer")) == 1
    assert len(llm.calls_of("l2_continuation")) == cont.MAX_CONTINUATION_CALLS


@pytest.mark.asyncio
async def test_provider_error_during_continuation_is_honest(monkeypatch):
    """Ошибка провайдера на продолжении не маскируется и не даёт обрезок."""
    llm = _MetaLLM(l1=_plan(),
                   writer=[(PART1, "length"), (RuntimeError("upstream down"),
                                               "stop")])
    svc, react, bot, msg, user = _drive(monkeypatch, "что с сервером?", llm)

    await svc.handle(bot, msg, user)

    assert svc._send_direct_answer.await_count == 0
    assert len(llm.calls_of("l2_continuation")) == 1


# ════════════════════════════════════════════════════════════════════════════
# (d) Ответ не обрезан → один вызов, текст байт-в-байт
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_complete_answer_makes_no_continuation_call(monkeypatch):
    answer = "Всё в порядке, база отвечает, таблицы целы."
    llm = _MetaLLM(l1=_plan(), writer=[(answer, "stop")])
    svc, react, bot, msg, user = _drive(monkeypatch, "как дела?", llm)

    await svc.handle(bot, msg, user)

    assert len(llm.calls_of("l2_writer")) == 1
    assert llm.calls_of("l2_continuation") == []
    assert _delivered(svc) == answer


# ════════════════════════════════════════════════════════════════════════════
# (e) Продолжение — НЕ второй автор: semantic_rewrite_count остаётся 0
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_continuation_is_not_a_semantic_rewrite(monkeypatch):
    """Один литературный вызов (attempts=1) при двух вызовах провайдера.

    `semantic_rewrite_count` считается как «литературные вызовы сверх одного
    авторского» (`max(0, literary_calls - 1)`), поэтому равен 0: продолжение
    живёт ВНУТРИ единственного авторского вызова — это тот же текст, тот же
    план и тот же evidence, а не новый автор/reroll.
    """
    seen = _stats_spy(monkeypatch)
    llm = _MetaLLM(l1=_plan(), writer=[(PART1, "length"), (PART2, "stop")])
    svc, react, bot, msg, user = _drive(monkeypatch, "что с сервером?", llm)

    await svc.handle(bot, msg, user)

    stats = seen["stats"]
    assert stats["attempts"] == 1                    # ровно один автор
    assert stats["semantic_rewrite_count"] == 0      # продолжение — не rewrite
    # Провайдер при этом вызван дважды (первый фрагмент + продолжение).
    assert (len(llm.calls_of("l2_writer"))
            + len(llm.calls_of("l2_continuation"))) == 2
    assert _delivered(svc) == PART1 + PART2


# ════════════════════════════════════════════════════════════════════════════
# Протокол модуля: граница, эхо, склейка, лимит
# ════════════════════════════════════════════════════════════════════════════

def test_continuation_messages_carry_explicit_accumulated_boundary():
    messages = [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}]
    out = cont.build_continuation_messages(messages, PART1)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "user"]
    assert out[0] == messages[0] and out[1] == messages[1]
    assert out[2]["content"] == PART1
    assert str(len(PART1)) in out[3]["content"]
    assert str(cont.count_tokens(PART1)) in out[3]["content"]


def test_exact_overlap_and_full_restart_are_stripped():
    assert cont.strip_exact_overlap("aaaaaaaa bbbbbbbb", "bbbbbbbb c") == " c"
    # Полный рестарт ответа: провайдер прислал всё написанное заново.
    assert cont.strip_exact_overlap("Первое. Второе.", "Первое. Второе. Третье.") \
        == " Третье."
    # Короткое случайное совпадение не съедается (авторский повтор легален).
    assert cont.strip_exact_overlap("конец и", "и вот так") == "и вот так"


def test_join_keeps_word_and_space_boundaries():
    # Обрыв посреди слова: склейка без вставок, ни одной буквы не теряем.
    assert cont.join_fragments("потерялась цело", "стность") == \
        "потерялась целостность"
    # Конец фразы + новое слово: один пробел, без слипания.
    assert cont.join_fragments("Готово.", "Дальше расскажу") == \
        "Готово. Дальше расскажу"
    # Провайдер сам дал ведущий пробел — второй не появляется.
    assert cont.join_fragments("Готово.", " Дальше") == "Готово. Дальше"


@pytest.mark.asyncio
async def test_cap_is_bounded_and_reported():
    calls = []

    async def call(messages):
        calls.append(messages)
        return _completion(" ещё", "length")

    result = await cont.complete_truncated_answer(
        _completion(PART1, "length"), messages=[{"role": "user", "content": "Q"}],
        call=call, max_continuations=3)

    assert result.continuation_calls == 3
    assert result.completed is False
    assert result.stop_reason == "cap"
    assert len(calls) == 3
    assert result.finish_reasons == ("length", "length", "length", "length")


@pytest.mark.asyncio
async def test_no_progress_stops_without_looping():
    async def call(messages):
        return _completion("", "length")   # провайдер не дал нового текста

    result = await cont.complete_truncated_answer(
        _completion(PART1, "length"), messages=[{"role": "user", "content": "Q"}],
        call=call)

    assert result.continuation_calls == 1
    assert result.completed is False
    assert result.stop_reason == "no_progress"
    assert result.text == PART1


@pytest.mark.asyncio
async def test_not_truncated_is_passed_through_untouched():
    async def call(messages):       # pragma: no cover — не должен вызываться
        raise AssertionError("продолжение не требуется")

    result = await cont.complete_truncated_answer(
        _completion(PART1, "stop"), messages=[], call=call)
    assert result.text == PART1
    assert result.continuation_calls == 0
    assert result.completed is True
    assert result.stop_reason == "not_needed"


def test_text_only_completion_has_no_truncation_signal():
    """Текст-двойник клиента не отдаёт `finish_reason` → поведение прежнее."""
    assert cont.is_truncated_output(cont.TextCompletion("текст")) is False
    assert cont.is_truncated_output(_completion("текст", "length")) is True
    assert cont.is_truncated_output(_completion("текст", "MAX_TOKENS")) is True
    assert cont.is_truncated_output(_completion("текст", "stop")) is False
    # Незнакомое поле не выдаётся за штатное завершение, но и не «обрезано».
    assert cont.is_truncated_output(_completion("текст", "unknown")) is False
