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

import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from config.settings import settings
from services.outgoing_guard import sanitize_outgoing
from services.prompt_style_blocks import CLICHE_RETRY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_MAX_RETRIES_HARD_CAP = 2


@dataclass(frozen=True)
class ClicheRule:
    """Одно правило детектора: код + компилированные шаблоны."""

    code: str
    patterns: tuple[re.Pattern[str], ...]
    # Вторичные правила (bullet_list) по умолчанию выключены.
    secondary: bool = False
    # Многострочные правила ищутся по СЫРОМУ тексту (нормализация схлопывает \n).
    use_raw: bool = False


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
        r"(?<!\bсебя\s)(?<!\bон\s)(?<!\bона\s)(?<!\bоно\s)(?<!\bэто\s)"
        r"(?<!\bлюди\s)(?<!\bчеловек\s)\bкак\s+"
        r"(?:ии|искусственный\s+интеллект|языковая\s+модель)\b",
        r"\bязыковая\s+модель\b",
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
    # (статья) правило НЕ активно. Детектор ниже — тот же набор шаблонов.
    ClicheRule(
        "plain_no_tables",
        _c(
            r"<table\b",
            r"^\s*\|.*\|\s*$",
            r"^\s*\+[-=+]+\+\s*$",
            r"\|?\s*:?-{2,}:?\s*\|",
            flags=re.IGNORECASE | re.MULTILINE,
        ),
        secondary=True,
        use_raw=True,
    ),
)

# Отдельный публичный детектор табличной разметки (Markdown `| … |`, HTML
# `<table>`, ASCII-сетки `+---+`, разделители `---|`). R17: наружу — только bool.
_PLAIN_TABLE_PATTERNS = next(
    rule.patterns for rule in FORBIDDEN_CLICHE_PATTERNS
    if rule.code == "plain_no_tables"
)


def detect_plain_tables(text: str) -> bool:
    """True, если в тексте есть табличная разметка любого вида. Fail-open."""
    try:
        source = str(text or "")
        return any(pattern.search(source) for pattern in _PLAIN_TABLE_PATTERNS)
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


def find_forbidden_cliches(
    text: str, enabled_rules: frozenset[str] | set[str] | None = None
) -> list[str]:
    """→ список кодов найденных клише (R17: без matched-подстрок).

    ``enabled_rules=None`` → дефолтный набор (все, кроме вторичного
    ``bullet_list``). Fail-open: ошибка → ``[]`` (текст считается чистым).
    """
    try:
        codes = (DEFAULT_ENABLED_RULES if enabled_rules is None
                 else frozenset(enabled_rules))
        if not codes:
            return []
        source = str(text or "")
        norm = _normalize(source)
        hits: list[str] = []
        for rule in FORBIDDEN_CLICHE_PATTERNS:
            if rule.code not in codes:
                continue
            haystack = source if rule.use_raw else norm
            if any(pattern.search(haystack) for pattern in rule.patterns):
                hits.append(rule.code)
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
) -> tuple[str, dict]:
    """Вызвать Вербализатор с браковкой ответа по запрещённым клише.

    Логика:
      attempt 0: ``generate_call(base_messages)``; чист → вернуть.
      при находке: до ``min(max_retries, 2)`` повторов ТЕМ ЖЕ Вербализатором
      с ``CLICHE_RETRY_SYSTEM_PROMPT`` (полная перегенерация).
      исчерпание → лучший вариант (минимум кодов; тай-брейк — самый ранний),
      очищенный scrubber'ом; ``fallback=True``.

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
    if not getattr(settings, "SYSTEM2_VALIDATOR_LOOP_ENABLED", True):
        stats["enabled"] = False
        text = await generate_call(base_messages)
        stats["attempts"] = 1
        return scrubber(text), stats

    retry_message = {"role": "system", "content": CLICHE_RETRY_SYSTEM_PROMPT}
    text = await generate_call(base_messages)
    attempts = 1
    codes = find_forbidden_cliches(text, enabled_rules)
    if not codes:
        stats["attempts"] = attempts
        return scrubber(text), stats

    best_text, best_codes = text, codes
    cap = max(0, min(int(max_retries), _MAX_RETRIES_HARD_CAP))
    for index in range(1, cap + 1):
        retry_messages = list(base_messages) + [retry_message]
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
            return scrubber(best_text), stats
        attempts += 1
        retries = index
        codes = find_forbidden_cliches(text, enabled_rules)
        if not codes:
            stats.update({"attempts": attempts, "retries": retries})
            return scrubber(text), stats
        if len(codes) < len(best_codes):
            best_text, best_codes = text, codes

    stats.update({
        "attempts": attempts,
        "retries": retries,
        "hits": list(best_codes),
        "fallback": True,
    })
    logger.info(
        "[validator] cliche loop exhausted | attempts=%d | retries=%d | "
        "codes=%d", attempts, retries, len(best_codes))
    return scrubber(best_text), stats
