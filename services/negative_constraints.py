"""F6 (T-2092, ADR-1022-6 §2.3) — детектор ИИ-клише + Validator Loop.

Вето владельца (UPD3 Д-10): клише **не** вырезаются кодом (это ломает
грамматику). Вместо этого Python-детектор находит запрещённое клише и
**бракует весь ответ**, возвращая его LLM-Вербализатору на полную
перегенерацию (≤2 ретрая). Список клише живёт ТОЛЬКО здесь (в коде), а не
в промпт-константах — иначе grep-тест отсутствия тропов поймал бы сам список.

R17: ``find_forbidden_cliches`` возвращает только коды правил, не matched-
подстроки; ``verbalize_validated`` возвращает stats из кодов/чисел.

Fail-open: ошибка детектора → текст считается чистым (ответ не блокируется).
Fail-safe: ошибка generate на ретрае → возвращается последний успешный текст.
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
from services.prompt_style_blocks import (
    CLICHE_RETRY_SYSTEM_PROMPT,
    FORM_GUARD_RETRY_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES_HARD_CAP = 2

# ── MCA-08 (D8, T-4907/T-4908): контракт «только форма» + анти-утечки ───────
# Расширение существующего контура `verbalize_validated` (отдельный
# paraphrase-модуль запрещён; второй постпроцессор не создаётся).

FORM_GUARD_REJECTED = "form_guard_rejected"
FORM_GUARD_LEAK_BLOCKED = "form_guard_leak_blocked"

# G1: техметки/JSON-маркеры/<thought>/target-маркер — через diff
# `sanitize_outgoing` (неизменный egress-канон).
# G2: числа (пробелы/NBSP/разделители тысяч/десятичная запятая) и отрицание
# в окне ±40 символов (закрытый список).
# G3: новые имена ростера (регистронезависимо, границы слов).
_NEGATION_WINDOW = 40
_NUMBER_TOKEN_RE = re.compile(r"\d+(?:[ \u00a0\u202f'.,]\d+)*")
_NEGATION_RE = re.compile(
    r"(?<![0-9a-zа-яё_])(?:не|ни|никогда|без|нет)(?![0-9a-zа-яё_])")
_NAME_BOUNDARY_CHARS = r"0-9a-zа-яё_"


@dataclass(frozen=True)
class FormContract:
    """Исходный проверенный черновик для form-гардов (D8, T-4907).

    ``source_text`` — финал tool-loop (`str(raw)`) / проверенный исходник;
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


def check_form_contract(candidate: str, contract: FormContract, *,
                        scrubber: Scrubber = sanitize_outgoing
                        ) -> str | None:
    """Прогнать form-гарды G1–G3. → код отказа либо None (форма сохранена)."""
    try:
        text = str(candidate or "")
        if scrubber(text) != text:
            return FORM_GUARD_LEAK_BLOCKED          # G1
        counts_src, neg_src = _number_signature(contract.source_text)
        counts_cand, neg_cand = _number_signature(text)
        if counts_src != counts_cand or neg_src != neg_cand:
            return FORM_GUARD_REJECTED              # G2
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
) -> tuple[str, dict]:
    """Вызвать Вербализатор с браковкой ответа по запрещённым клише.

    Логика:
      attempt 0: ``generate_call(base_messages)``; чист → вернуть.
      при находке: до ``min(max_retries, 2)`` повторов ТЕМ ЖЕ Вербализатором
      с ``CLICHE_RETRY_SYSTEM_PROMPT`` (полная перегенерация).
      исчерпание → лучший вариант (минимум кодов; тай-брейк — самый ранний),
      очищенный scrubber'ом; ``fallback=True``.

    MCA-08 (D8, T-4907/T-4908): при переданном ``form_contract`` и K4 ON
    (``MCA_POSTPROCESS_FORM_GUARD_ENABLED``) кандидат дополнительно проходит
    form-гарды G1–G3; reject → **≤1** повтор с
    ``FORM_GUARD_RETRY_SYSTEM_PROMPT`` внутри ТОГО ЖЕ bounded-бюджета (≤2
    ретрая всего, бюджет не растёт); после reject'а в повторе (или при
    недоступном бюджете) — возврат ``fallback_text`` (санитизированный;
    деградация честно помечается ``form_fallback=True``). Значения по
    умолчанию (``None``) и K4 OFF → байт-паритет 2.58.54, stats без новых
    ключей.

    Ретраи строго bounded (≤2 → ≤3 вызова Stage-2). Ошибка generate на
    ретрае → вернуть последний успешный текст (``retry_error=True``).
    Kill-switch ``SYSTEM2_VALIDATOR_LOOP_ENABLED=false`` → один прямой вызов.
    """
    attempts = 0
    retries = 0
    stats: dict = {
        "attempts": 0,
        "retries": 0,
        "hits": [],
        "fallback": False,
        "retry_error": False,
        "enabled": True,
    }
    form_active = bool(form_contract is not None
                       and mca_gates.postprocess_form_guard_enabled())
    if form_active:
        stats.update({
            "form_guard_rejects": 0,
            "form_guard_reason": None,
            "form_retry": False,
            "form_fallback": False,
        })

    def _form_reason(candidate: str) -> str | None:
        if not form_active:
            return None
        return check_form_contract(candidate, form_contract, scrubber=scrubber)

    def _fallback_result(text_value: str):
        """Финальный возврат при исчерпании: проверенный черновик, иначе best."""
        if form_active and int(stats.get("form_guard_rejects") or 0) > 0:
            stats["form_fallback"] = True
            if fallback_text is not None and str(fallback_text).strip():
                return scrubber(str(fallback_text)), stats
        return scrubber(text_value), stats

    if not getattr(settings, "SYSTEM2_VALIDATOR_LOOP_ENABLED", True):
        stats["enabled"] = False
        text = await generate_call(base_messages)
        stats["attempts"] = 1
        return scrubber(text), stats

    # Review iter1 (M2): материализуем один раз — итератор/генератор нельзя
    # прокручивать повторно на ретраях.
    dyn = tuple(dynamic_rules) if dynamic_rules else ()
    text = await generate_call(base_messages)
    attempts = 1
    codes = find_forbidden_cliches(text, enabled_rules, dyn)
    form_reason = _form_reason(text)
    if form_reason is not None:
        stats["form_guard_rejects"] += 1
        stats["form_guard_reason"] = form_reason
    if not codes and form_reason is None:
        stats["attempts"] = attempts
        return scrubber(text), stats

    best_text, best_codes = text, codes
    best_form_ok = form_reason is None
    form_retry_used = False
    cap = max(0, min(int(max_retries), _MAX_RETRIES_HARD_CAP))
    for index in range(1, cap + 1):
        if form_reason is not None:
            # «Только форма»: ровно ≤1 повтор с каноном формы (T-4908);
            # повтор тратится из ТОГО ЖЕ bounded-бюджета (бюджет не растёт).
            if form_retry_used:
                break
            form_retry_used = True
            stats["form_retry"] = True
            retry_system = FORM_GUARD_RETRY_SYSTEM_PROMPT
        else:
            retry_system = CLICHE_RETRY_SYSTEM_PROMPT
        retry_messages = list(base_messages) + [
            {"role": "system", "content": retry_system}]
        try:
            text = await generate_call(retry_messages)
        except Exception:
            stats["retry_error"] = True
            attempts += 0
            stats["attempts"] = attempts
            stats["retries"] = index - 1
            stats["hits"] = list(best_codes)
            stats["fallback"] = True
            logger.warning(
                "[validator] retry generate failed — best kept | attempts=%d "
                "| codes=%d", attempts, len(best_codes))
            return _fallback_result(best_text)
        attempts += 1
        retries = index
        codes = find_forbidden_cliches(text, enabled_rules, dyn)
        form_reason = _form_reason(text)
        if form_reason is not None:
            stats["form_guard_rejects"] += 1
            stats["form_guard_reason"] = form_reason
        if not codes and form_reason is None:
            stats.update({"attempts": attempts, "retries": retries})
            return scrubber(text), stats
        form_ok = form_reason is None
        if form_active:
            better = (form_ok, -len(codes)) > (best_form_ok, -len(best_codes))
        else:
            better = len(codes) < len(best_codes)
        if better:
            best_text, best_codes, best_form_ok = text, codes, form_ok

    stats.update({
        "attempts": attempts,
        "retries": retries,
        "hits": list(best_codes),
        "fallback": True,
    })
    logger.info(
        "[validator] cliche loop exhausted | attempts=%d | retries=%d | "
        "codes=%d | form_rejects=%d", attempts, retries, len(best_codes),
        int(stats.get("form_guard_rejects") or 0))
    return _fallback_result(best_text)
