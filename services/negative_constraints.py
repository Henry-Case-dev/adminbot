"""F6 (T-2092, ADR-1022-6 §2.3) — детектор ИИ-клише + наблюдения по тексту.

REMOVE-LEGACY-REPHRASING v2.0 (R-04.1, R-03.1/R-03.2, §3.4): внутри модуля
жёстко разделены две работы.

* **Машинный протокол** (структура JSON/схема/function-call) —
  ``repair_machine_payload``: единственное место, где повторная генерация
  допустима — bounded и с видимой причиной (``stats['machine_reasons']``).
* **Готовая разговорная речь** — ``verbalize_validated``: ровно один вызов
  Writer'а. Пост-L2 reroll снят полностью (было: form / numeric / metatext /
  format / cliché).

Что осталось наблюдением в свободной речи:

* стиль (жёсткое правило, динамическое PG-правило, pinned, множественное)
  НЕ вызывает повтор, reject, best-of, fallback, scrub или задержку:
  находка пишется в ``stats['cliche_observed']``
  (``stats['anti_cliche_retries']`` всегда 0);
* метатекст (``metatext_reason``) — наблюдение
  (``stats['metatext_observed']``), без reroll и без вырезания фразы;
* формат доставки (``plain_no_tables``/``bullet_list``) — вкусовая форма,
  а не невозможность доставки: Telegram принимает обычный текст, поэтому
  это тоже наблюдение (``stats['format_observed']``), без повтора;
* числа в стат-контексте (``numeric_contract``) — наблюдение
  (``stats['numeric_claim_mismatch']``/``numeric_claim_reason``): вставки
  ``verified_phrase`` и снятия предложения из свободной речи больше нет
  (R-04.2). Точные числа обязан дать data-stage ДО генерации.
  ``apply_numeric_guard`` — оставленный хелпер для БУДУЩЕЙ сборки строки
  кодом: продуктовых вызывающих у него НЕТ (RLR-04 убрал и свободный финал,
  и доставку «Летописца» — её текст пишет модель). Любой потребитель обязан
  вызывать его только на строке, собранной кодом, а не на авторском тексте.

Узкая детерминированная проверка защищённых данных (G1–G3: числа, отрицания,
имена ростера) остаётся ТОЛЬКО у явной трансформации с исходным текстом
(``form_contract``: пользовательские «перепиши/переведи/отредактируй»).
Нарушение не перегенерируется и не правится литературно: возвращаются
исходные данные (``form_fallback``) либо авторский текст с
``needs_clarification``. Второй LLM-стадии литературной правки нет нигде.

Список клише живёт ТОЛЬКО здесь (в коде), а не в промпт-константах — иначе
grep-тест отсутствия тропов поймал бы сам список.

R17: ``find_forbidden_cliches`` возвращает только коды правил, не matched-
подстроки; ``verbalize_validated`` возвращает stats из кодов/чисел.

Fail-open: ошибка детектора → текст считается чистым (ответ не блокируется).
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

from config.settings import settings
from services import mca_gates
from services.outgoing_guard import sanitize_outgoing

logger = logging.getLogger(__name__)

_MAX_RETRIES_HARD_CAP = 2

# ── MCA-08 (D8, T-4907/T-4908): узкая проверка защищённых данных ────────────
# Только для ЯВНОЙ трансформации с исходным текстом (R-03.2/R-03.3): гарды
# детерминированные, повторной генерации не запускают, литературно не правят.

FORM_GUARD_REJECTED = "form_guard_rejected"
FORM_GUARD_LEAK_BLOCKED = "form_guard_leak_blocked"

# G1: техметки/JSON-маркеры/<thought>/target-маркер — через diff
# `sanitize_outgoing` (неизменный egress-канон).
# G2: числа (пробелы/NBSP/разделители тысяч/десятичная запятая) и отрицание
# в окне ±40 символов (закрытый список).
# G2b (BGS-04.10): отрицание ЦЕЛИКОМ — множества куэ-токенов источника и
# результата трансформации обязаны совпасть.
# G3: новые имена ростера (регистронезависимо, границы слов).
_NEGATION_WINDOW = 40
_NUMBER_TOKEN_RE = re.compile(r"\d+(?:[ \u00a0\u202f'.,]\d+)*")
_NEGATION_RE = re.compile(
    r"(?<![0-9a-zа-яё_])(?:не|ни|никогда|без|нет)(?![0-9a-zа-яё_])")
_NAME_BOUNDARY_CHARS = r"0-9a-zа-яё_"

# ── G2b (BGS-04.10): отрицание вне числового окна ──────────────────────────
# Закрытый СПИСОК куэ-токенов, а не префикс: слова на «не-/ни-», которые не
# являются отрицанием («неделя», «низкий», «небо», «немного», «нибудь»),
# в перечислении отсутствуют и по определению не считаются. Куэ-токен
# обязан быть отдельным словом (границы `_NAME_BOUNDARY_CHARS`).
_NEGATION_CUES: tuple[str, ...] = tuple(sorted((
    "не",                    # частица
    "ни",                    # усилительная частица отрицания
    "нет", "нету",           # предикативное отрицание (в т.ч. стяжённое)
    "нельзя",                # модальное отрицание
    "никогда", "никуда", "нигде", "ничуть", "нисколько",   # ни- наречия
    "некуда", "негде", "некому", "нечего", "нечем",        # не- наречия/мест.
    "без",                   # отрицание-предлог («без ответа»)
), key=len, reverse=True))
_NEGATION_CUE_RE = re.compile(
    r"(?<![0-9a-zа-яё_])(?:" + "|".join(_NEGATION_CUES)
    + r")(?![0-9a-zа-яё_])")

# Эквивалентное двойное отрицание: пара куэ взаимно гасится, иначе
# «не мог не сказать» → «сказал» давал бы ложный отказ. Список закрытый:
# только устойчивые конструкции, где два отрицания дают утверждение.
_DOUBLE_NEGATION_RE = re.compile(
    r"(?<![0-9a-zа-яё_])не\s+"
    r"(?:мог|могла|могли|могут|может|могу|можешь|можем"
    r"|хотел|хотела|хотели|хотелось|умел|умела|умели)\s+не(?![0-9a-zа-яё_])"
    r"|(?<![0-9a-zа-яё_])нельзя\s+не(?![0-9a-zа-яё_])"
    r"|(?<![0-9a-zа-яё_])не\s+без(?![0-9a-zа-яё_])")


@dataclass(frozen=True)
class FormContract:
    """Исходный текст ЯВНОЙ трансформации для узкой проверки данных.

    Заполняется только там, где пользователь попросил переписать/перевести/
    отредактировать конкретный исходник и смысл обязан сохраниться
    (``source_text``). Для свободного Direct/Initiative L2 контракт не
    создаётся: финальная формулировка не обязана повторять числа/отрицания/
    имена черновика инструмента (R-03.1).

    ``addressee`` — адресат (справочно, не влияет на гарды); ``roster_names`` —
    участники, новых имён которых кандидат вводить не должен.
    """

    source_text: str
    addressee: str | None = None
    roster_names: tuple[str, ...] = ()


def _canon_number(token: str) -> str:
    """Канонизация числа: пробелы/NBSP/' — разделители тысяч, ',' → '.'."""
    text = (token.replace(" ", "").replace("\u00a0", "")
            .replace("\u202f", "").replace("'", ""))
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    return text


def _number_signature(text: str) -> tuple[dict[str, int], dict[str, int]]:
    """(мультимножество чисел, счётчики чисел с отрицанием в окне ±40)."""
    counts: dict[str, int] = {}
    negated: dict[str, int] = {}
    source = str(text or "")
    for match in _NUMBER_TOKEN_RE.finditer(source):
        canon = _canon_number(match.group())
        counts[canon] = counts.get(canon, 0) + 1
        window = source[max(0, match.start() - _NEGATION_WINDOW):
                        match.end() + _NEGATION_WINDOW].casefold()
        if _NEGATION_RE.search(window):
            negated[canon] = negated.get(canon, 0) + 1
    return counts, negated


def _negation_signature(text: str) -> frozenset[str]:
    """Множество куэ-токенов отрицания текста (G2b, BGS-04.10).

    Сравниваются НАБОРЫ, а не количество: перефраз вправе повторить «не» в
    другом месте, но не вправе потерять или добавить отрицание. Перед
    подсчётом снимаются locked-конструкции двойного отрицания (их два куэ
    взаимно гасятся), поэтому эквивалентная замена «не мог не сказать» →
    «сказал» отказа не даёт. Обычные слова на «не-/ни-» («неделя», «низкий»,
    «небо») в закрытый список не входят.
    """
    source = _DOUBLE_NEGATION_RE.sub(" ", str(text or "").casefold())
    return frozenset(
        match.group() for match in _NEGATION_CUE_RE.finditer(source))


def check_form_contract(candidate: str, contract: FormContract, *,
                        scrubber: Scrubber = sanitize_outgoing
                        ) -> str | None:
    """Узкая проверка защищённых данных явной трансформации (G1–G3).

    → код отказа либо None (данные сохранены). Проверка ЧИСТО
    детерминированная: она ничего не перегенерирует и не переписывает
    (R-03.2/R-03.3). Применяется только там, где есть исходный текст и
    требование сохранить смысл; для свободной речи L2 контракт не создаётся.
    """
    try:
        text = str(candidate or "")
        if scrubber(text) != text:
            return FORM_GUARD_LEAK_BLOCKED          # G1
        counts_src, neg_src = _number_signature(contract.source_text)
        counts_cand, neg_cand = _number_signature(text)
        if counts_src != counts_cand or neg_src != neg_cand:
            return FORM_GUARD_REJECTED              # G2
        if _negation_signature(contract.source_text) \
                != _negation_signature(text):
            return FORM_GUARD_REJECTED              # G2b (BGS-04.10)
        if contract.roster_names:                   # G3
            low_src = str(contract.source_text or "").casefold()
            low_cand = text.casefold()
            for name in contract.roster_names:
                norm = str(name or "").strip().casefold()
                if len(norm) < 2:
                    continue
                pattern = re.compile(
                    rf"(?<![{_NAME_BOUNDARY_CHARS}]){re.escape(norm)}"
                    rf"(?![{_NAME_BOUNDARY_CHARS}])")
                if pattern.search(low_cand) and not pattern.search(low_src):
                    return FORM_GUARD_REJECTED
        return None
    except Exception:      # fail-open: гард не рвёт поток
        logger.warning("[validator] form guard error — text treated as clean")
        return None


# ── MCA-15 (D5, T-4930/T-4931): numeric-гард в существующем контуре ─────────
# Один детерминированный гард (не второй LLM-судья и не paraphrase-модуль):
# числа в статистическом контексте обязаны соответствовать NumericClaim ЭТОГО
# хода; число из tool output/другого запроса — не подтверждение (A41).
# Числа вне стат-контекста (даты, возраст, цитаты, обычная речь) свободны.

NUMERIC_CLAIM_MISMATCH = "numeric_claim_mismatch"
NUMERIC_CLAIM_CORRECTED = "numeric_claim_corrected"
NUMERIC_CLAIM_FALLBACK = "numeric_claim_fallback"

# Закрытый список маркеров единиц статистического контекста (§7.1).
_STAT_UNIT_MARKERS: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (re.compile(r"сообщени"), frozenset({"messages"})),
    (re.compile(r"упомина"), frozenset({"messages", "occurrences"})),
    (re.compile(r"вхожден"), frozenset({"occurrences"})),
    (re.compile(r"автор"), frozenset({"authors", "messages"})),
    (re.compile(r"участник"), frozenset({"authors", "messages"})),
    (re.compile(r"(?<![0-9a-zа-яё_])раз(?:а|ы|ов)?(?![0-9a-zа-яё_])"),
     frozenset({"messages", "occurrences"})),
)
_STAT_CONTEXT_WINDOW = 20
# Даты/возраст: 4-значный год и «N лет/год(а)/месяцев/...» не блокируются.
_YEAR_MIN = 1900
_YEAR_MAX = 2100
_DATE_UNIT_RE = re.compile(
    r"\s*(?:год|года|году|годов|лет|месяц|месяца|месяцев|"
    r"дн(?:я|ей|ём)|недел(?:я|и|ь)|час(?:а|ов)?)"
    r"(?![0-9a-zа-яё_])")
_DATE_NUM_RE = re.compile(
    r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2}")
_QUOTE_PAIRS = (("«", "»"), ("“", "”"), ("„", "“"), ('"', '"'))
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")
# Детерминированная оговорка, когда статистику запрашивали, но проверить
# нечего (без выдуманного числа). R17-safe: без текста запроса.
NUMERIC_CLAIM_CAVEAT = (
    "Число не проверено по доступной истории — называть его не буду.")


@dataclass(frozen=True)
class NumericContract:
    """Контракт numeric-гарда одного хода (D5/§7.1).

    ``claims`` — проверенные NumericClaim ЭТОГО хода (per-turn; числа прошлых
    ходов/другого запроса не подтверждение); ``verified_phrase`` — готовая
    детерминированная формулировка измерения (слот финального сборщика);
    ``stats_expected`` — запрашивали ли статистику (для честной оговорки).
    """
    claims: tuple = ()
    verified_phrase: str = ""
    stats_expected: bool = False


def _quote_spans(text: str) -> list[tuple[int, int]]:
    """Диапазоны цитат (числа внутри кавычек не блокируются)."""
    spans: list[tuple[int, int]] = []
    for opener, closer in _QUOTE_PAIRS:
        start = 0
        while True:
            left = text.find(opener, start)
            if left < 0:
                break
            right = text.find(closer, left + 1)
            if right < 0:
                break
            spans.append((left, right + 1))
            start = right + 1
    return spans


def _stat_context_numbers(text: str) -> list[tuple[str, int, frozenset]]:
    """Числа в статистическом контексте: (канон, позиция, единицы-маркеры).

    Вне стат-контекста (нет маркера единицы в окне), внутри цитат, даты,
    годы и возраст/длительность — не возвращаются (свободны)."""
    source = str(text or "")
    if not source:
        return []
    spans = _quote_spans(source)
    found: list[tuple[str, int, frozenset]] = []
    for match in _NUMBER_TOKEN_RE.finditer(source):
        if any(start <= match.start() < end for start, end in spans):
            continue
        if _DATE_NUM_RE.match(source, match.start()):
            continue
        if match.start() > 0 and source[match.start() - 1] in "./-":
            continue
        if match.end() < len(source) and source[match.end()] in "./-":
            continue
        window = source[max(0, match.start() - _STAT_CONTEXT_WINDOW):
                        match.end() + _STAT_CONTEXT_WINDOW].casefold()
        units: frozenset = frozenset()
        for pattern, marker_units in _STAT_UNIT_MARKERS:
            if pattern.search(window):
                units = units | marker_units
        if not units:
            continue
        canon = _canon_number(match.group())
        try:
            integer = int(canon)
        except ValueError:
            integer = None
        if integer is not None and len(canon) == 4 \
                and _YEAR_MIN <= integer <= _YEAR_MAX:
            continue                                    # год — дата
        if _DATE_UNIT_RE.match(source, match.end()):
            continue                                    # «30 лет», «3 дня»
        found.append((canon, match.start(), units))
    return found


def check_numeric_claims(candidate: str, contract: NumericContract | None, *,
                         source_text: str | None = None) -> str | None:
    """Детерминированная проверка чисел в стат-контексте (D5).

    → ``numeric_claim_mismatch`` либо None. Число в стат-контексте обязано
    совпасть по значению и совместимой единице с claim ЭТОГО хода;
    ``source_text`` (черновик/tool output) намеренно НЕ является
    подтверждением — иначе число другого запроса проходило бы (A41).
    Fail-open: ошибка гарда → текст считается чистым."""
    try:
        if contract is None:
            return None
        numbers = _stat_context_numbers(str(candidate or ""))
        if not numbers:
            return None
        claims = tuple(contract.claims or ())
        for canon, _pos, units in numbers:
            matched = False
            for claim in claims:
                try:
                    claim_value = int(claim.value)
                except (AttributeError, TypeError, ValueError):
                    continue
                if _canon_number(str(claim_value)) != canon:
                    continue
                claim_unit = str(getattr(claim, "unit", "") or "")
                if claim_unit and units and claim_unit not in units:
                    continue
                matched = True
                break
            if not matched:
                return NUMERIC_CLAIM_MISMATCH
        return None
    except Exception:      # fail-open: гард не рвёт поток
        logger.warning("[validator] numeric guard error — text treated as clean")
        return None


def _correct_numeric_claims(candidate: str,
                            contract: NumericContract | None) -> str:
    """Детерминированная ≤1 коррекция: нарушающая фраза заменяется
    ``verified_phrase`` (если есть) либо снимается; последующие нарушения —
    снимаются. Без второго LLM-вызова."""
    text = str(candidate or "")
    if contract is None or check_numeric_claims(text, contract) is None:
        return text
    phrase = str(getattr(contract, "verified_phrase", "") or "").strip()
    segments = _SENTENCE_SPLIT_RE.split(text)
    out: list[str] = []
    replaced = False
    for segment in segments:
        if check_numeric_claims(segment, contract) is not None:
            if phrase and not replaced:
                out.append(phrase)
                replaced = True
            continue
        out.append(segment)
    corrected = " ".join(seg for seg in out if seg).strip()
    if not corrected and phrase:
        return phrase
    return corrected


def apply_numeric_guard(candidate: str,
                        contract: NumericContract | None, *,
                        fallback_text: str | None = None
                        ) -> tuple[str, dict]:
    """Детерминированная коррекция числа по контракту хода → (текст, stats).

    RLR-04 (R-04.2; owner corrective 2026-11-05): **продуктовых вызывающих
    НЕТ**. Оба прежних потребителя сняты: свободный финал Direct и доставка
    текста «Летописца» (его пишет модель — ``LoreCompilerService.llm.
    generate``, writer ``lore_writer``), а не код. Никакой доставляемый
    авторский текст этой функцией не правится: расхождение числа — только
    наблюдение (``check_numeric_claims``), точные числа приходят в Writer ДО
    генерации.

    Хелпер оставлен для случая, когда строку реально собирает КОД из
    проверенных агрегатов (тогда сверка с NumericClaim законна); такой
    потребитель появится только с явной детерминированной сборкой и должен
    вызывать её именно на своём тексте, не на речи модели.

    ``contract is None``/K2 OFF → байт-паритет (текст как есть, stats пуст).
    Нарушение → одна детерминированная коррекция; не удалось → проверенный
    черновик/``verified_phrase``/снятие неподтверждённой части. Событий не
    эмитит (решает вызывающий; notable-only)."""
    text = str(candidate or "")
    if contract is None or not mca_gates.numeric_claim_guard_enabled():
        return text, {}
    reason = check_numeric_claims(text, contract)
    if reason is None:
        return text, {}
    stats: dict = {"mismatch": True, "reason": NUMERIC_CLAIM_MISMATCH,
                   "corrected": False, "fallback": False}
    corrected = _correct_numeric_claims(text, contract)
    if corrected.strip() and check_numeric_claims(corrected, contract) is None:
        stats["corrected"] = True
        stats["reason"] = NUMERIC_CLAIM_CORRECTED
        return corrected, stats
    candidates: list[str] = []
    if fallback_text is not None and str(fallback_text).strip():
        candidates.append(str(fallback_text))
    phrase = str(getattr(contract, "verified_phrase", "") or "").strip()
    if phrase:
        candidates.append(phrase)
    if getattr(contract, "stats_expected", False):
        candidates.append(NUMERIC_CLAIM_CAVEAT)
    for candidate_text in candidates:
        fixed = _correct_numeric_claims(candidate_text, contract)
        if fixed.strip() and check_numeric_claims(fixed, contract) is None:
            stats["fallback"] = True
            stats["reason"] = NUMERIC_CLAIM_FALLBACK
            return fixed, stats
    stats["fallback"] = True
    stats["reason"] = NUMERIC_CLAIM_FALLBACK
    return corrected, stats


@dataclass(frozen=True)
class ClicheRule:
    """Одно правило детектора: код + компилированные шаблоны."""

    code: str
    patterns: tuple[re.Pattern[str], ...]
    # Вторичные правила (bullet_list) по умолчанию выключены.
    secondary: bool = False
    # Многострочные правила ищутся по СЫРОМУ тексту (нормализация схлопывает \n).
    use_raw: bool = False


@dataclass(frozen=True)
class DynamicClicheRule:
    """F4 (ADR-1023-4 D2): динамическое правило — литеральная фраза + код.

    Фраза хранится уже нормализованной (`_normalize`: lower/ё→е/пробелы);
    на детекторе компилируется через ``re.escape`` (произвольные regex НЕ
    принимаются — защита от ReDoS/инъекций). Код стабилен: ``dyn_<sha1[:8]>``.
    R17: наружу отдаются только коды, не фразы.
    """

    code: str
    phrase: str


def _c(*patterns: str, flags: int = 0) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, flags) for p in patterns)


# Финальный список клише (объединение 10.21 + UPD2). Регистронезависимость
# обеспечивается нормализацией в lower-case перед поиском.
FORBIDDEN_CLICHE_PATTERNS: tuple[ClicheRule, ...] = (
    ClicheRule("as_ai", _c(
        # Первое лицо: «я (как) ИИ / искусственный интеллект».
        r"\bя\s*,?\s+(?:как\s+)?(?:ии|искусственный\s+интеллект)\b",
        # «как ИИ / языковая модель» — но НЕ третьеличные сравнения
        # (S10.22-4: «он/она/оно/это/люди … как …», «ведёт себя как …»).
        # S10.22-4b (F4, ADR-1023-4 D5): добавлены comma-варианты lookbehind
        # фиксированной ширины — «Он, как …», «Люди, как …» (Python re не
        # поддерживает lookbehind переменной длины). Review iter1 (M3):
        # добавлены и варианты с пробелом ПЕРЕД запятой («Он , как …») —
        # типичный дефект набора; `_normalize` пробел перед запятой не убирает.
        r"(?<!\bсебя\s)(?<!\bсебя,\s)(?<!\bсебя\s,\s)"
        r"(?<!\bон\s)(?<!\bон,\s)(?<!\bон\s,\s)"
        r"(?<!\bона\s)(?<!\bона,\s)(?<!\bона\s,\s)"
        r"(?<!\bоно\s)(?<!\bоно,\s)(?<!\bоно\s,\s)"
        r"(?<!\bэто\s)(?<!\bэто,\s)(?<!\bэто\s,\s)"
        r"(?<!\bлюди\s)(?<!\bлюди,\s)(?<!\bлюди\s,\s)"
        r"(?<!\bчеловек\s)(?<!\bчеловек,\s)(?<!\bчеловек\s,\s)"
        r"\bкак\s+"
        r"(?:ии|искусственный\s+интеллект|языковая\s+модель)\b",
        # S10.22-4b: голое «языковая модель» — самоидентификация; в
        # третьеличном сравнении «она, как языковая модель» роль играет
        # предыдущее правило (его comma-lookbehind), поэтому bare-правило
        # не должно срабатывать сразу после «как ».
        r"(?<!\bкак\s)\bязыковая\s+модель\b",
    )),
    ClicheRule("classic_genre", _c(r"\bклассика\s+жанра\b")),
    ClicheRule("summing_up", _c(r"\bподводя\s+итог(?:и)?\b")),
    ClicheRule("in_conclusion", _c(r"\bв\s+(?:заключение|завершение)\b")),
    ClicheRule("hope_helped", _c(
        r"\bнадеюсь[,\s]+(?:что\s+)?(?:это\s+)?(?:я\s+)?помог(?:ла|ло)?\b",
        r"\bнадеюсь[,\s]+(?:что\s+)?(?:это\s+)?было\s+полезно\b",
    )),
    ClicheRule("you_asked_before", _c(
        r"\b(?:ты|вы)\s+уже\s+спрашивал(?:а|и)?\b",
        r"\b(?:ты|вы)\s+спрашивал(?:а|и)?\s+это\b",
        r"\bуже\s+спрашивал(?:а|и)?\s+это\b",
    )),
    # «нет, это ты …» — перепалка/перевод стрелок. Уступка («нет, ты прав»,
    # «нет, ты верно заметил») — НЕ клише (negative lookahead).
    ClicheRule("mirror_no_you", _c(
        r"\bнет[,\s]+(?:это\s+)?ты\b(?!\s*,?\s*"
        r"(?:прав|права|право|верн|точно|молодец))")),
    ClicheRule(
        "bullet_list",
        _c(r"^\s*[-*•]\s+\S", r"^\s*\d+[.)]\s+\S", flags=re.MULTILINE),
        secondary=True,
        use_raw=True,
    ),
    # Раунд 10.23 (F3, ADR-1023-3 §3.6.3): таблицы запрещены на plain-канале
    # (Telegram ParseError). Включается только для plain-канала; на rich
    # (статья) правило НЕ активно. Сам детектор — `detect_plain_tables` ниже;
    # в правиле оставлены только однозначные жёсткие маркеры таблиц.
    # Review iter2 (M5): одиночная строка с `|` сама по себе таблицей НЕ
    # считается (см. контекстную эвристику в детекторе).
    ClicheRule(
        "plain_no_tables",
        _c(
            r"<table\b",
            r"^\s*\+[-=+]+\+\s*$",
            flags=re.IGNORECASE | re.MULTILINE,
        ),
        secondary=True,
        use_raw=True,
    ),
)

# Жёсткие маркеры табличной разметки (однозначны без контекста).
_TABLE_HTML_RE = re.compile(r"<table\b", re.IGNORECASE)
_TABLE_ASCII_GRID_RE = re.compile(r"^\s*\+[-=+]+\+\s*$", re.MULTILINE)
# Separator-строка Markdown: только `-`/`:`/`|`/пробелы, есть `|` и прогон
# дефисов ≥2 («---|», «|---|---|», «|:--|:--|»).
_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+(?:\s*:?-{2,}:?\s*)?\|?\s*$",
    re.MULTILINE,
)
# «Pipe-строка»: есть `|` с непробельными символами по обе стороны
# (кандидат в строку таблицы, но сам по себе — не таблица).
_TABLE_PIPE_LINE_RE = re.compile(r"\S\s*\|\s*\S")


def detect_plain_tables(text: str) -> bool:
    """True, если в тексте есть табличная разметка. Fail-open.

    Review iter2 (M5): детекция **контекстно-чувствительная** — одиночный `|`
    (в т.ч. легитимный шелл-пайп `cat file | grep error`) таблицей не считается.
    Таблица фиксируется по любому из признаков:

    1. HTML-маркер `<table`;
    2. ASCII-сетка `+---+`;
    3. separator-строка Markdown (`---|`, `|---|---|`);
    4. **две и более подряд** идущих pipe-строк (шапка + строки/разделитель).
    """
    try:
        source = str(text or "")
        if not source:
            return False
        if _TABLE_HTML_RE.search(source):
            return True
        if _TABLE_ASCII_GRID_RE.search(source):
            return True
        if _TABLE_SEPARATOR_RE.search(source):
            return True
        consecutive = 0
        for line in source.splitlines():
            if _TABLE_PIPE_LINE_RE.search(line):
                consecutive += 1
                if consecutive >= 2:
                    return True
            else:
                consecutive = 0
        return False
    except Exception:  # pragma: no cover - defensive (fail-open)
        logger.warning("[validator] table detector error — treated as clean")
        return False


DEFAULT_ENABLED_RULES: frozenset[str] = frozenset(
    rule.code for rule in FORBIDDEN_CLICHE_PATTERNS if not rule.secondary
)

# ── Стиль и формат доставки разделены В ОДНОМ месте (BGS-04) ───────────────
#: Стилевые сигналы анти-клише (hardcoded-правила; динамические ``dyn_*`` и
#: любые неизвестные коды попадают в ту же группу наблюдений — см.
#: ``split_rule_codes``). ТОЛЬКО наблюдение: пишутся в
#: ``stats['cliche_observed']``/``stats['hits']`` и НИКОГДА не увеличивают
#: число генераций.
STYLE_SIGNALS: frozenset[str] = frozenset({
    "as_ai",
    "classic_genre",
    "summing_up",
    "in_conclusion",
    "hope_helped",
    "mirror_no_you",
    "you_asked_before",
})

#: Формат доставки — вкусовая форма канала, а не невозможность доставки
#: (BGS-04 §5: Telegram принимает обычный текст; запрет списков/таблиц ради
#: «естественности» не повод переписывать готовый ответ). Коды остаются
#: видимыми в наблюдении (``stats['format_observed']``), но повтора не дают.
FORMAT_GUARDS: frozenset[str] = frozenset({"plain_no_tables", "bullet_list"})
#: Историческое имя причины (совместимость чтения старых записей телеметрии).
FORMAT_RETRY_REASON = "format_retry"


def is_format_guard(code: str) -> bool:
    """Код — guard формата доставки (``plain_no_tables``/``bullet_list``)."""
    return str(code or "") in FORMAT_GUARDS


def split_rule_codes(codes: Iterable[str]) -> tuple[list[str], list[str]]:
    """Коды детектора → (наблюдения стиля, коды формата доставки).

    Наблюдение — всё, что не является guard'ом формата доставки: жёсткие
    стилевые правила ``STYLE_SIGNALS``, динамические ``dyn_*`` и любой
    неизвестный код (fail-safe: сюрприз не вызывает лишний вызов LLM).
    BGS-04: обе группы — наблюдение; ни одна не запускает повтор.
    """
    observed: list[str] = []
    fmt: list[str] = []
    for code in codes or ():
        (fmt if is_format_guard(code) else observed).append(str(code))
    return observed, fmt


def channel_enabled_rules(channel: str = "plain", response_mode: str = "serious",
                          *, forbid_bullets: bool = False) -> frozenset[str]:
    """Набор правил под канал доставки (ADR-1023-3 §Decision 5/10).

    * rich-канал (статья) — таблицы легальны: ``plain_no_tables`` НЕ активен;
    * plain-канал — всегда ``plain_no_tables``; список-буллиты бракуются
      только там, где жанр их не предусматривает (``forbid_bullets=True``,
      напр. R11-саммари), и НЕ бракуются в режиме ``deep_research`` (там
      ``FORMAT_PLAIN_BLOCK`` их прямо требует).
    """
    rules = set(DEFAULT_ENABLED_RULES)
    if str(channel or "plain").strip().lower() != "rich":
        rules.add("plain_no_tables")
        mode = str(response_mode or "").strip().lower()
        if forbid_bullets and mode != "deep_research":
            rules.add("bullet_list")
    return frozenset(rules)

_DASH_RE = re.compile(r"[—–-]+")
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """lower-case, `ё→е`, схлопывание дефисов/пробелов (детерминированно)."""
    value = str(text or "").lower().replace("ё", "е")
    value = _DASH_RE.sub(" ", value)
    return _WS_RE.sub(" ", value).strip()


# ── F4 (ADR-1023-4 D2): динамические правила (литеральные фразы) ─────────────
DYNAMIC_PREFIX = "dyn_"
DYNAMIC_PHRASE_MIN = 2
DYNAMIC_PHRASE_MAX = 120
# Bounded-кэш скомпилированных шаблонов динамических фраз (module-level).
_DYNAMIC_PATTERN_CACHE: dict[str, re.Pattern[str] | None] = {}
_DYNAMIC_PATTERN_CACHE_MAX = 256


def normalize_dynamic_phrase(raw) -> str | None:
    """Нормализация фразы динамического правила → строка | None.

    Только литеральная строка: lower, `ё→е`, схлопывание дефисов/пробелов;
    длина 2…120 символов (иначе ``None``). Произвольные regex/служебные
    значения не принимаются на уровне вызывающего (``re.escape``).
    """
    try:
        value = _normalize(raw)
        if len(value) < DYNAMIC_PHRASE_MIN or len(value) > DYNAMIC_PHRASE_MAX:
            return None
        return value
    except Exception:  # pragma: no cover - defensive
        return None


def dynamic_rule_code(phrase: str) -> str:
    """Стабильный код правила: ``dyn_<sha1(normalized_phrase)[:8]>``."""
    digest = hashlib.sha1(
        str(phrase or "").encode("utf-8")).hexdigest()[:8]
    return DYNAMIC_PREFIX + digest


def build_dynamic_rule(phrase) -> DynamicClicheRule | None:
    """Нормализованная фраза → правило (или ``None``, если фраза невалидна)."""
    normalized = normalize_dynamic_phrase(phrase)
    if not normalized:
        return None
    return DynamicClicheRule(code=dynamic_rule_code(normalized),
                             phrase=normalized)


def _compile_dynamic_pattern(phrase: str) -> re.Pattern[str] | None:
    """Компиляция литеральной фразы через ``re.escape`` (+ ``\\b`` по краям).

    Произвольные regex не принимаются (фраза экранируется целиком). Кэш
    bounded (сброс при переполнении — динамических фраз мало)."""
    cached = _DYNAMIC_PATTERN_CACHE.get(phrase)
    if cached is not None or phrase in _DYNAMIC_PATTERN_CACHE:
        return cached
    try:
        escaped = re.escape(phrase)
        if re.match(r"\w", phrase):
            escaped = r"\b" + escaped
        if re.search(r"\w$", phrase):
            escaped = escaped + r"\b"
        pattern: re.Pattern[str] | None = re.compile(escaped)
    except Exception:  # pragma: no cover - defensive (не должно случаться)
        pattern = None
    if len(_DYNAMIC_PATTERN_CACHE) >= _DYNAMIC_PATTERN_CACHE_MAX:
        _DYNAMIC_PATTERN_CACHE.clear()
    _DYNAMIC_PATTERN_CACHE[phrase] = pattern
    return pattern


def _dynamic_hits(
    norm: str, dynamic_rules: Iterable[DynamicClicheRule] | None
) -> list[str]:
    """Коды сработавших динамических правил по нормализованному тексту."""
    hits: list[str] = []
    if not dynamic_rules:
        return hits
    for rule in dynamic_rules:
        code = getattr(rule, "code", None)
        phrase = getattr(rule, "phrase", None)
        if not code or not phrase or code in hits:
            continue
        pattern = _compile_dynamic_pattern(str(phrase))
        if pattern is not None and pattern.search(norm):
            hits.append(str(code))
    return hits


def find_forbidden_cliches(
    text: str,
    enabled_rules: frozenset[str] | set[str] | None = None,
    dynamic_rules: Iterable[DynamicClicheRule] | None = None,
) -> list[str]:
    """→ список кодов найденных клише (R17: без matched-подстрок).

    ``enabled_rules=None`` → дефолтный набор (все, кроме вторичного
    ``bullet_list``). ``dynamic_rules`` (F4, аддитивно) — литеральные
    правила из PG-кэша; ``None``/пусто → поведение **байт-в-байт** прежнее.
    Итератор материализуется один раз (review iter1 M2). Fail-open: ошибка →
    ``[]`` (текст считается чистым).
    """
    try:
        dyn = tuple(dynamic_rules) if dynamic_rules else ()
        codes = (DEFAULT_ENABLED_RULES if enabled_rules is None
                 else frozenset(enabled_rules))
        if not codes and not dyn:
            return []
        source = str(text or "")
        norm = _normalize(source)
        hits: list[str] = []
        for rule in FORBIDDEN_CLICHE_PATTERNS:
            if rule.code not in codes:
                continue
            # Review iter1 (M2): правило таблиц идёт через публичный детектор
            # `detect_plain_tables` — единый источник истины для прода и тестов.
            if rule.code == "plain_no_tables":
                if detect_plain_tables(source):
                    hits.append(rule.code)
                continue
            haystack = source if rule.use_raw else norm
            if any(pattern.search(haystack) for pattern in rule.patterns):
                hits.append(rule.code)
        hits.extend(_dynamic_hits(norm, dyn))
        return hits
    except Exception:  # pragma: no cover - defensive (fail-open)
        logger.warning("[validator] detector error — text treated as clean")
        return []


GenerateCall = Callable[[list[dict[str, str]]], Awaitable[str]]
Scrubber = Callable[[str], str]
#: Машинный протокол ответа (JSON/схема/function-call): кандидат → код отказа
#: либо None. Проверяется ПРОТОКОЛ, а не речь (R-04.1, §3.4).
MachineValidator = Callable[[str], str | None]

#: Код отказа машинного протокола (видимая причина повтора машинного слоя).
MACHINE_CONTRACT_REJECTED = "machine_contract_rejected"
MACHINE_VALIDATOR_ERROR = "machine_validator_error"
#: Служебный префикс инструкции повтора: исправляется структура, не смысл.
MACHINE_CONTRACT_PREFIX = "MACHINE_CONTRACT: "


async def repair_machine_payload(
    generate_call: GenerateCall,
    base_messages: list[dict[str, str]],
    *,
    validator: MachineValidator,
    max_retries: int = 1,
) -> tuple[str, dict]:
    """Машинный слой: исправить СТРУКТУРУ ответа (JSON/схема/function-call).

    R-04.1 / §3.4: повторная генерация допустима ровно здесь — в
    подготовительном машинном слое, где чинится протокол, а не готовая речь.
    ``validator`` — проверка протокола вызывающего слоя; её код отказа
    попадает в ``stats['machine_reasons']`` (код, не текст), поэтому причина
    каждого повтора видима.

    Границы: не более ``min(max_retries, _MAX_RETRIES_HARD_CAP)`` повторов;
    исчерпание → ``machine_unrepaired=True`` и последний кандидат — честное
    решение об ошибке принимает машинный слой (никакого литературного
    переписчика, никакого Verbalizer'а для невалидного JSON). Свободный текст
    здесь не правится вообще: за речь отвечает ``verbalize_validated``.
    """
    stats: dict = {
        "attempts": 0,
        "retries": 0,
        "machine_reasons": [],
        "machine_unrepaired": False,
        "fallback": False,
        "retry_error": False,
    }

    def _check(value: str) -> str | None:
        try:
            return validator(value)
        except Exception:      # fail-safe: сломанный валидатор виден, поток цел
            logger.warning("[validator] machine validator error — rejected")
            return MACHINE_VALIDATOR_ERROR

    cap = max(0, min(int(max_retries), _MAX_RETRIES_HARD_CAP))
    text = await generate_call(base_messages)
    stats["attempts"] = 1
    reason = _check(text)
    while reason is not None and int(stats["retries"]) < cap:
        stats["machine_reasons"].append(str(reason))
        retry_messages = list(base_messages) + [
            {"role": "system",
             "content": MACHINE_CONTRACT_PREFIX + str(reason)}]
        try:
            text = await generate_call(retry_messages)
        except Exception:
            stats["retry_error"] = True
            break
        stats["attempts"] += 1
        stats["retries"] += 1
        reason = _check(text)
    if reason is not None:
        stats["machine_reasons"].append(str(reason))
        stats["machine_unrepaired"] = True
        stats["fallback"] = True
        logger.info(
            "[validator] machine contract unrepaired | attempts=%d | "
            "retries=%d | reasons=%d", stats["attempts"], stats["retries"],
            len(stats["machine_reasons"]))
    return text, stats


async def verbalize_validated(
    generate_call: GenerateCall,
    base_messages: list[dict[str, str]],
    *,
    max_retries: int = _MAX_RETRIES_HARD_CAP,
    scrubber: Scrubber = sanitize_outgoing,
    enabled_rules: frozenset[str] | set[str] | None = None,
    dynamic_rules: Iterable[DynamicClicheRule] | None = None,
    form_contract: FormContract | None = None,
    fallback_text: str | None = None,
    numeric_contract: NumericContract | None = None,
    metatext_reason: Callable[[str], str | None] | None = None,
    author_state: dict | None = None,
) -> tuple[str, dict]:
    """Один Writer-вызов + НАБЛЮДЕНИЯ по готовому тексту (без повторов).

    REMOVE-LEGACY-REPHRASING v2.0 (R-04.1, R-03.1/R-03.2, §4): после Writer
    никакой новой смысловой генерации нет. Модуль разделён на две работы:

    * машинный протокол (структура JSON/схема/function-call) —
      ``repair_machine_payload`` (единственное место, где допустим повтор);
    * готовая разговорная речь — ЭТА функция: ровно один вызов автора;
      форма, числа, отрицания, метатекст, «клише» и формат доставки только
      наблюдаются (``stats['cliche_observed']``,
      ``stats['format_observed']``, ``stats['metatext_observed']``,
      ``stats['numeric_claim_mismatch']``), текст доставляется как написан
      автором.

    ``stats['semantic_rewrite_count']`` — ИЗМЕРЕНИЕ, не литерал: это число
    литературных вызовов ЭТОГО хода сверх первого авторского
    (``max(0, literary_calls - 1)``). Считается обёрткой над
    ``generate_call``, поэтому автоматически станет >0, если кто-то вернёт
    цикл повтора/второго автора. ``author_state`` (необязательный словарь)
    — учёт литературных вызовов на уровне хода: интеграция/тест видит
    фактическое число вызовов, а уже сделанный в ходе литературный вызов
    даёт честный ``semantic_rewrite_count``.

    Единственное меняющее текст действие свободного пути — технический
    ``scrubber`` (``sanitize_outgoing``: маркеры рассуждений/машинные метки,
    смысл не меняется).

    Явная трансформация (``form_contract`` = исходный текст + требование
    сохранить смысл: пользовательские «перепиши/переведи/отредактируй»)
    получает узкую детерминированную проверку защищённых данных G1–G3
    (числа, отрицания, имена ростера). Нарушение НЕ перегенерируется и НЕ
    «правится» литературно: либо возвращаются исходные данные
    (``fallback_text`` — прозрачный исход, ``form_fallback=True``), либо
    авторский текст остаётся как написан с ``needs_clarification=True``
    (решение об уточнении принимает вызывающий). Ошибка трассируется в
    ``stats['form_guard_reason']``/``protected_facts_mismatch``.

    Машинные метки (G1) на пути трансформации считаются технической чисткой:
    их снимает ``scrubber`` при доставке (``technical_cleanup=True``), исходник
    из-за них не подменяется.

    Числа в свободной речи (``numeric_contract``) — тоже наблюдение:
    ``stats['numeric_claim_mismatch']``/``numeric_claim_reason`` видимы, но
    ни повторной генерации, ни вставки ``verified_phrase``, ни снятия
    предложения нет (R-04.2: точные числа даёт data-stage до генерации).

    Параметр ``max_retries`` сохранён для совместимости вызовов и больше не
    влияет на число генераций: петель в свободном пути нет.

    Исторический kill-switch ``SYSTEM2_VALIDATOR_LOOP_ENABLED=false``
    (deprecated_compat) оставлен читаемым: петель нет, флаг только отключает
    публикацию наблюдений (``stats['enabled']=False``).

    Fail-safe: ошибка ``generate_call`` пробрасывается вызывающему (честная
    ошибка провайдера), ошибки детекторов — тихие (текст считается чистым).
    """
    stats: dict = {
        "attempts": 0,
        "retries": 0,
        "hits": [],
        "fallback": False,
        "retry_error": False,
        "enabled": True,
        # Анти-клише не перегенерирует никогда (исторический инвариант).
        "anti_cliche_retries": 0,
        # Наблюдение стилевых сигналов (код в stats, без повтора).
        "cliche_observed": [],
    }
    # Учёт ЛИТЕРАТУРНЫХ вызовов хода (R-07/R-04): словарь может прийти от
    # вызывающего/интеграции, иначе ведём свой. `semantic_rewrite_count`
    # считается из него, а не задаётся литералом.
    ledger = author_state if isinstance(author_state, dict) else {}

    async def _author_generate(messages):
        """Единственный путь литературного вызова: каждый вызов учитывается."""
        ledger["literary_calls"] = int(ledger.get("literary_calls") or 0) + 1
        return await generate_call(messages)

    def _result(value: str) -> tuple[str, dict]:
        """Итог пути: счётчик лишних авторов = литературные вызовы сверх 1."""
        literary_calls = int(ledger.get("literary_calls") or 0)
        stats["semantic_rewrite_count"] = max(0, literary_calls - 1)
        return scrubber(value), stats

    metatext_active = metatext_reason is not None
    if metatext_active:
        stats["metatext_observed"] = []
    transform_active = bool(form_contract is not None
                            and mca_gates.postprocess_form_guard_enabled())
    if transform_active:
        stats.update({
            "form_guard_rejects": 0,
            "form_guard_reason": None,
            # Исторические ключи: повтора больше нет (всегда False).
            "form_retry": False,
            "form_fallback": False,
        })
    numeric_active = bool(numeric_contract is not None
                          and mca_gates.numeric_claim_guard_enabled())
    if numeric_active:
        stats.update({
            "numeric_claim_mismatch": 0,
            # Исторические ключи: повтора за число больше нет (всегда False).
            "numeric_claim_retry": False,
            "numeric_claim_fallback": False,
            "numeric_claim_reason": None,
        })

    if not getattr(settings, "SYSTEM2_VALIDATOR_LOOP_ENABLED", True):
        stats["enabled"] = False
        text = await _author_generate(base_messages)
        stats["attempts"] = 1
        return _result(text)

    # Материализуем один раз — итератор/генератор нельзя прокручивать повторно.
    dyn = tuple(dynamic_rules) if dynamic_rules else ()
    text = await _author_generate(base_messages)
    stats["attempts"] = 1
    codes = find_forbidden_cliches(text, enabled_rules, dyn)
    style_codes, format_codes = split_rule_codes(codes)
    stats["cliche_observed"] = list(style_codes)
    if format_codes:
        stats["format_observed"] = list(format_codes)
    if metatext_active:
        try:
            metatext_code = metatext_reason(text)
        except Exception:      # наблюдение не роняет валидацию
            metatext_code = None
        stats["metatext_observed"] = (
            [str(metatext_code)] if metatext_code else [])
    stats["hits"] = list(codes)

    numeric_reason = (check_numeric_claims(text, numeric_contract)
                      if numeric_active else None)
    if numeric_reason is not None:
        stats["numeric_claim_mismatch"] = 1
        stats["numeric_claim_reason"] = numeric_reason

    if not transform_active:
        # Свободная речь L2: текст автора уходит как написан (R-04.1).
        return _result(text)

    # ── Явная трансформация: узкая проверка защищённых данных, без повтора ──
    form_reason = check_form_contract(text, form_contract, scrubber=scrubber)
    technical_leak = form_reason == FORM_GUARD_LEAK_BLOCKED
    if form_reason is not None:
        # Любая находка видима (в т.ч. техническая чистка машинных меток):
        # UI не должен считать такой ответ «прошедшим проверку».
        stats["form_guard_reason"] = form_reason
        stats["form_guard_rejects"] = 1
        if technical_leak:
            # Машинные метки снимает scrubber при доставке: смысл не меняется,
            # исходник из-за них не подменяется.
            stats["technical_cleanup"] = True
    if not (form_reason is not None and not technical_leak) \
            and numeric_reason is None:
        return _result(text)

    stats["protected_facts_mismatch"] = True
    source = str(fallback_text or "")
    if not source.strip() or source.strip() == text.strip():
        # Исходника нет: авторский текст остаётся как написан (никакой
        # подмены и никакой второй литературной правки), вызывающий видит
        # требование уточнить трансформацию.
        stats["needs_clarification"] = True
        logger.warning(
            "[validator] explicit transform: protected facts changed | "
            "reason=%s | source=none", stats.get("form_guard_reason"))
        return _result(text)
    stats["fallback"] = True
    stats["form_fallback"] = bool(form_reason is not None and not technical_leak)
    if numeric_reason is not None:
        stats["numeric_claim_fallback"] = True
    logger.warning(
        "[validator] explicit transform: source restored | reason=%s | "
        "numeric=%s", stats.get("form_guard_reason"), numeric_reason)
    return _result(source)
