"""UR-19 / R-08.14 / §3.2 — продолжение финального ответа при `finish_reason=length`.

REMOVE-LEGACY-REPHRASING v2.0 §3.2 (owner doc
`plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`):
«`finish_reason=length`: продолжать **тот же логический ответ** с явной
границей накопленных токенов; не выдавать обрезок и не запускать независимого
"переписчика для завершения". Защититься от дублирования и противоречивых
продолжений. При невозможности полного продолжения — честное техническое
состояние, не фиктивный успех.»

Что делает модуль:

* читает ФАКТ завершения, который уже отдаёт клиент
  (`LLMCompletion.is_truncated` / `finish_reason`). До этой правки сигнал
  никем из потребителей финального Writer'а не читался: обрезанный ответ
  уходил в чат как готовый;
* продолжает ТОТ ЖЕ текст: запрос содержит уже написанный фрагмент как
  assistant-реплику (это и есть явная граница накопленных токенов) плюс
  инструкцию продолжения; исходный system/user-контекст, план и evidence не
  меняются, поэтому продолжение — не новый автор, не новый план и не
  альтернативный вариант ответа;
* склеивает фрагменты без дублей: точное эхо «хвост написанного → голова
  продолжения» снимается один раз, а слово на стыке не обрывается;
* ограничивает число продолжений (`MAX_CONTINUATION_CALLS`) и возвращает
  причину остановки наружу (`stop_reason`), чтобы вызывающий не выдал
  незавершённый текст за готовый ответ.

Модуль ничего не генерирует сам, не «дописывает» текст от себя и не решает,
что доставлять: ошибка провайдера на продолжении не маскируется (исключение
уходит вызывающему), а незавершённый результат помечается `completed=False`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Sequence

from services.llm_client import is_truncation_finish_reason
from services.token_counter import count_tokens

logger = logging.getLogger(__name__)

#: Жёсткий верх ДОПОЛНИТЕЛЬНЫХ вызовов на один логический ответ. Значение —
#: защита от провайдера, который обрывает каждый фрагмент: это не бюджет
#: длины ответа и не пользовательская настройка (R-03.2/§3.2 требуют лишь
#: ограниченное число продолжений с видимой причиной).
MAX_CONTINUATION_CALLS = 2

#: Минимальная длина точного эха «хвост написанного → голова продолжения»,
#: при которой повтор признаётся дублем и снимается. Короче — совпадение
#: случайно, и удаление испортило бы авторский текст.
OVERLAP_MIN_CHARS = 8

#: Окно поиска хвостового эха. Полное «начал ответ заново» ловится отдельной
#: ветвью в `strip_exact_overlap`, окно ограничивает только поиск эха.
OVERLAP_WINDOW = 6000

#: Инструкция продолжения. Явно называет границу (длина накопленного текста)
#: и запрещает всё, что сделало бы продолжение вторым автором или дублем.
CONTINUATION_INSTRUCTION = (
    "Продолжение того же ответа. Выше — уже написанный текст, ровно "
    "{chars} символов ({tokens} токенов): его последний символ и есть граница "
    "продолжения. Продолжи с этого места — первое новое слово идёт сразу за "
    "границей. Не начинай ответ заново, не пересказывай и не повторяй "
    "написанное, не добавляй вступлений и пояснений о продолжении. Та же "
    "манера, тот же смысл; уже сказанное не отменяется и не противоречит "
    "продолжению."
)

#: Знаки, после которых новое слово не приклеивается к предыдущему.
_SENTENCE_TAIL = frozenset(".!?…:;,)»\"'")


@dataclass(frozen=True)
class TextCompletion:
    """Ответ клиента БЕЗ метаданных завершения (текстовый двойник `generate`).

    Такой ответ не несёт `finish_reason`, поэтому сигнала обрезки нет —
    `is_truncated=False` и поведение прежнее (байт-в-байт).
    """

    text: str
    finish_reason: str = ""

    @property
    def is_truncated(self) -> bool:      # сигнала нет → не обрезан
        return False


@dataclass(frozen=True)
class ContinuationResult:
    """Итог протокола продолжения одного логического ответа.

    ``text`` — собранный текст (частичный, если ``completed=False``);
    ``continuation_calls`` — сколько ДОПОЛНИТЕЛЬНЫХ вызовов реально сделано;
    ``stop_reason`` — видимая причина остановки:
    ``not_needed`` (обрезки не было), ``completed`` (продолжение довело
    ответ), ``cap`` (лимит продолжений исчерпан, текст всё ещё обрезан),
    ``no_progress`` (провайдер не дал нового текста);
    ``finish_reasons`` — фактические `finish_reason` всех вызовов цепочки.
    """

    text: str
    continuation_calls: int = 0
    completed: bool = True
    stop_reason: str = "not_needed"
    finish_reasons: tuple[str, ...] = ()

    @property
    def continued(self) -> bool:
        """Было ли продолжение (для трассы/диагностики)."""
        return self.continuation_calls > 0


class IncompleteContinuation(RuntimeError):
    """Ответ остался НЕЗАВЕРШЁННЫМ (лимит продолжений / нет прогресса).

    Бросается вместо пустого текста намеренно: пустая строка прошла бы
    form-guard явной трансформации как «потеря защищённых данных» и вернула бы
    пользователю исходник — незаконченный ответ был бы выдан за успешную
    трансформацию (§3.2: «не фиктивный успех»). Вызывающий обязан отдать
    честный отказ, а не текст.
    """

    def __init__(self, result: "ContinuationResult") -> None:
        self.result = result
        super().__init__(
            f"incomplete answer: {result.stop_reason} "
            f"(calls={result.continuation_calls}, chars={len(result.text)})")


def _finish_reason_of(completion) -> str:
    """Нормализованный `finish_reason` завершения (для трассы); нет — ''."""
    value = getattr(completion, "finish_reason", "")
    return str(value or "").strip().lower()


def is_truncated_output(completion) -> bool:
    """Обрезан ли output по пределу длины (провайдерский факт, не догадка).

    Приоритет — готовый флаг клиента (`LLMCompletion.is_truncated`); если его
    нет, решает нормализованный `finish_reason` (`length`/`max_tokens`).
    Строгая проверка `is True` не даёт посторонним объектам (mock-атрибутам)
    выглядеть как «обрезано».
    """
    flag = getattr(completion, "is_truncated", None)
    if isinstance(flag, bool):
        return flag
    return is_truncation_finish_reason(getattr(completion, "finish_reason", ""))


def build_continuation_messages(
        messages: Sequence[dict], accumulated: str) -> list[dict]:
    """Сообщения продолжения: исходный контекст + написанное + граница.

    Написанный фрагмент идёт assistant-репликой — модель видит ровно ту
    границу, на которой остановилась, а не пересказ и не другой черновик.
    Исходные system/user-сообщения не меняются: план, факты и роль те же.
    """
    boundary = CONTINUATION_INSTRUCTION.format(
        chars=len(accumulated), tokens=count_tokens(accumulated))
    out = [dict(m) for m in messages]
    out.append({"role": "assistant", "content": accumulated})
    out.append({"role": "user", "content": boundary})
    return out


def _trailing_word_run(text: str) -> str:
    """Хвостовой кусок слова, оборванный концом текста ('' если не оборван).

    «lost the wor» → «wor» (слово не дописано), «lost the word » → ''
    (последний символ — не буква/цифра, слова здесь не обрываются).
    """
    index = len(text)
    while index > 0 and text[index - 1].isalnum():
        index -= 1
    return text[index:]


def _leading_word_run(text: str) -> str:
    """Первый кусок слова в продолжении (пусто, если оно начинается не с буквы)."""
    index = 0
    while index < len(text) and text[index].isalnum():
        index += 1
    return text[:index]


def _incomplete_word_echo(prefix: str, fragment: str) -> str:
    """Голова продолжения без повтора, если она ДОПИСЫВАЕТ оборванное слово.

    Обрыв внутри слова невидим по длине: «wor» + «word is done.» — повтор в три
    символа, который правило ``OVERLAP_MIN_CHARS`` не ловит, и в чат уходило
    «worword». Здесь повтор снимается НЕЗАВИСИМО от длины, но только при
    строгом признаке продолжения слова: написанное кончается куском слова, а
    продолжение начинается С ЭТОГО ЖЕ куска и ДЛИННЕЕ его (то есть дописывает
    слово). Целые короткие повторы («и», «and», «word») под правило не
    попадают: продолжение не длиннее написанного куска → '' (не эхо).
    """
    tail = _trailing_word_run(prefix)
    if not tail or not fragment:
        return ""
    head = _leading_word_run(fragment)
    if len(head) <= len(tail) or not head.startswith(tail):
        return ""
    return fragment[len(tail):]


def strip_exact_overlap(prefix: str, fragment: str) -> str:
    """Снять точное эхо провайдера «хвост написанного = голова продолжения».

    Снимается РОВНО один раз и только точное совпадение:
    * провайдер повторил весь написанный текст (начал ответ заново) → снимаем
      весь повтор;
    * провайдер дописал оборванное слово, повторив его начало («wor»+«word…»)
      → снимаем повтор независимо от длины (иначе слово склеивается как
      «worword»);
    * провайдер повторил хвост (последние слова / предложение) → снимаем этот
      хвост из головы продолжения.

    Длинное совпадение (≥ ``OVERLAP_MIN_CHARS``) считается эхом всегда; более
    короткое — только как продолжение оборванного слова: законный короткий
    повтор автора («и», «and») не удаляется.
    """
    if not prefix or not fragment:
        return fragment
    if len(fragment) >= len(prefix) and fragment.startswith(prefix):
        return fragment[len(prefix):]
    word_echo = _incomplete_word_echo(prefix, fragment)
    if word_echo:
        return word_echo
    max_k = min(len(prefix), len(fragment), OVERLAP_WINDOW)
    last = prefix[-1]
    for size in range(max_k, OVERLAP_MIN_CHARS - 1, -1):
        # Дешёвый отсев: совпадение обязано кончаться последним символом
        # написанного (иначе `prefix.endswith` заведомо False).
        if fragment[size - 1] != last:
            continue
        if prefix.endswith(fragment[:size]):
            return fragment[size:]
    return fragment


def _is_decimal_point(prefix: str) -> bool:
    """Последняя «.» — десятичная точка («3.»), а не конец фразы."""
    return len(prefix) >= 2 and prefix[-2].isdigit()


def join_fragments(prefix: str, fragment: str) -> str:
    """Склеить части без обрыва слова и без потери пробела на стыке.

    * у продолжения есть свой ведущий пробел/перевод строки — склейка как есть;
    * написанное кончилось знаком конца фразы, а продолжение начинается словом
      — ставится один пробел (иначе слова слиплись бы);
    * НО если «.» стоит сразу после цифры, а продолжение начинается с цифры —
      это десятичная точка («3.» + «14» = «3.14»), пробел не ставится: иначе
      меняется смысл числа;
    * иначе продолжение — хвост ТОГО ЖЕ слова: склейка без вставок, ни одна
      буква не теряется и не появляется.
    """
    if not prefix:
        return fragment
    if not fragment:
        return prefix
    if fragment[0].isspace() or prefix[-1].isspace():
        return prefix + fragment
    if prefix[-1] in _SENTENCE_TAIL:
        decimal_split = fragment[0].isdigit() and _is_decimal_point(prefix)
        if not decimal_split and (fragment[0].isalnum()
                                  or fragment[0] in "\"'«("):
            return prefix + " " + fragment
    return prefix + fragment


async def complete_truncated_answer(
    completion,
    *,
    messages: Sequence[dict],
    call: Callable[[list[dict]], Awaitable[object]],
    max_continuations: int = MAX_CONTINUATION_CALLS,
) -> ContinuationResult:
    """Довести обрезанный ответ до завершения ТЕМ ЖЕ автором.

    ``completion`` — уже полученный ответ (первый авторский вызов);
    ``call`` — вызов провайдера тем же путём, что и первый (тот же клиент,
    та же стадия/провайдер, retry/fallback клиента), возвращает объект с
    ``text``/``is_truncated``; ``messages`` — исходные сообщения хода.

    Ошибка провайдера на продолжении НЕ ловится: вызывающий получает её так
    же, как ошибку первого вызова (честное техническое состояние), а не
    «готовый» обрезок. Незавершённый результат возвращается с
    ``completed=False``/``stop_reason`` — решение о доставке за вызывающим
    (пустой текст вместо него отдавать нельзя: см. `IncompleteContinuation`).
    """
    text = str(getattr(completion, "text", "") or "")
    reasons: list[str] = [_finish_reason_of(completion)]
    if not is_truncated_output(completion):
        return ContinuationResult(text=text, stop_reason="not_needed",
                                  finish_reasons=tuple(reasons))
    limit = max(0, int(max_continuations))
    calls = 0
    truncated = True
    while truncated and calls < limit:
        attempt = await call(build_continuation_messages(messages, text))
        calls += 1
        reasons.append(_finish_reason_of(attempt))
        fragment = str(getattr(attempt, "text", "") or "")
        joined = join_fragments(text, strip_exact_overlap(text, fragment))
        if joined == text:
            # Провайдер не дал нового текста (пусто/только повтор) — дальше
            # повторять бессмысленно, причина видна вызывающему.
            return ContinuationResult(
                text=text, continuation_calls=calls, completed=False,
                stop_reason="no_progress", finish_reasons=tuple(reasons))
        text = joined
        truncated = is_truncated_output(attempt)
    if truncated:
        return ContinuationResult(
            text=text, continuation_calls=calls, completed=False,
            stop_reason="cap", finish_reasons=tuple(reasons))
    return ContinuationResult(
        text=text, continuation_calls=calls, completed=True,
        stop_reason="completed", finish_reasons=tuple(reasons))
