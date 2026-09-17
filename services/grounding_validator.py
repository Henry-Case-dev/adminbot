"""F2 (T-1954/T-1957; ADR-1021-2) — детерминированный grounding-валидатор.

Без LLM: из входного user-контекста собирается множество допустимых якорей
(``fact:ID``, месяцы ``ММ.ГГГГ``, ISO-даты), а из вердикта модели жёстко
вырезаются «фантомные» ссылки, которых в контексте нет.

Принципы:
* идём от **точного формата** тега ``[ММ.ГГГГ | ... | fact:ID]`` — чтобы не
  задеть полезные даты, авторов и обычный текст;
* тег удаляется целиком, если id ЛИБО дата не входят в допустимое множество
  (Д6 = вырезать, без нейтральной замены). Так же режется и «дата-только»
  метка без ``fact:ID`` (``[04.2023 | Иван]``), если её месяц/ISO-даты нет во
  входном контексте (S10.21-4); сопоставление месяца ``ММ.ГГГГ`` и ISO-даты
  идёт и по нормализованному ключу ``YYYY-MM`` (месяц ↔ ISO-месяц, чтобы
  валидные теги не резались из-за формата);
* «голые» ``fact:ID`` вне допустимого множества вырезаются по токену;
* валидатор **никогда не бросает** и логирует только counts (R17: без
  содержимого вердикта и без значений секретов);
* аддитивен: пустые множества не ломают вызов, валидные теги сохраняются.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ``fact:123`` — ID факта в графе.
_FACT_ID_RE = re.compile(r"fact:\s*(\d+)")
# Месяц-год канона 4D-памяти: ``ММ.ГГГГ`` (ровно две цифры месяца).
_MONTH_RE = re.compile(r"(?<!\d)(\d{2})\.(\d{4})(?!\d)")
# ISO-дата в метке.
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
# Квадратная метка (не вложенная) — кандидат на тег.
_BRACKET_RE = re.compile(r"\[[^\[\]]{0,300}?\]")


@dataclass(frozen=True)
class GroundingAnchors:
    """Допустимые якоря, собранные из входного контекста."""

    ids: frozenset[str]
    months: frozenset[str]
    dates: frozenset[str]


@dataclass(frozen=True)
class StripStats:
    """Счётчики пост-обработки (для логов, без содержимого — R17)."""

    kept: int
    stripped_phantom: int
    stripped_bare: int


def collect_allowed_anchors(source: str) -> GroundingAnchors:
    """Собрать допустимые ``fact:ID`` / месяцы ``ММ.ГГГГ`` / ISO-даты.

    Никогда не бросает: не-str ``source`` приводится к строке.
    """
    try:
        text = str(source or "")
    except Exception:  # pragma: no cover - defensive
        return GroundingAnchors(frozenset(), frozenset(), frozenset())
    ids = frozenset(_FACT_ID_RE.findall(text))
    months = frozenset(f"{mm}.{yyyy}" for mm, yyyy in _MONTH_RE.findall(text))
    dates = frozenset(_ISO_DATE_RE.findall(text))
    return GroundingAnchors(ids=ids, months=months, dates=dates)


def _allowed_month_keys(anchors: GroundingAnchors) -> frozenset[str]:
    """Множество допустимых YYYY-MM, нормализованное из обоих источников:
    месяцев ``MM.YYYY`` и ISO-дат ``YYYY-MM-DD``. Нужно для сопоставления
    тега-месяца с ISO-датой контекста (и наоборот) — иначе легитимный
    ``[01.2024 | fact:N]`` при наличии только ``2024-01-01`` вырезался бы
    как фантом."""
    keys: set[str] = set()
    for value in anchors.months:
        mm, _, yyyy = str(value).partition(".")
        if mm and yyyy:
            keys.add(f"{yyyy}-{mm}")
    for iso in anchors.dates:
        keys.add(str(iso)[:7])                 # "YYYY-MM-DD" → "YYYY-MM"
    return frozenset(keys)


def _segment_ok(inner: str, anchors: GroundingAnchors) -> bool:
    """Допустим ли тег-сегмент: все id и даты должны быть в контексте.

    Работает и для меток без ``fact:ID`` (тогда проверяются только даты).
    F2 fix-round 2: месяц ``MM.YYYY`` и ISO-дата сопоставляются также по
    нормализованному ключу ``YYYY-MM`` (месяц ↔ ISO-месяц)."""
    fact_ids = _FACT_ID_RE.findall(inner)
    months = _MONTH_RE.findall(inner)
    dates = _ISO_DATE_RE.findall(inner)
    if not all(fid in anchors.ids for fid in fact_ids):
        return False
    if months or dates:
        month_keys = _allowed_month_keys(anchors)
        for mm, yyyy in months:
            if f"{mm}.{yyyy}" in anchors.months:
                continue
            if f"{yyyy}-{mm}" in month_keys:
                continue
            return False
        for d in dates:
            if d in anchors.dates:
                continue
            if d[:7] in month_keys:
                continue
            return False
    return True


def _strip_impl(text: str, anchors: GroundingAnchors) -> tuple[str, StripStats]:
    kept = 0
    stripped = 0
    out: list[str] = []
    pos = 0
    for match in _BRACKET_RE.finditer(text):
        out.append(text[pos:match.start()])
        seg = match.group(0)
        inner = seg[1:-1]
        has_fact = _FACT_ID_RE.search(inner) is not None
        has_date = (_MONTH_RE.search(inner) is not None
                    or _ISO_DATE_RE.search(inner) is not None)
        # S10.21-4: дата-только метка без `fact:ID` тоже проверяется по
        # контексту (иначе фантомные даты вида `[04.2023 | Иван]` проходят).
        if has_fact or has_date:
            if _segment_ok(inner, anchors):
                out.append(seg)
                kept += 1
            else:
                stripped += 1
        else:
            out.append(seg)
        pos = match.end()
    out.append(text[pos:])
    result = "".join(out)

    bare = 0

    def _replace_bare(match: re.Match[str]) -> str:
        nonlocal bare
        if match.group(1) in anchors.ids:
            return match.group(0)
        bare += 1
        return ""

    result = _FACT_ID_RE.sub(_replace_bare, result)
    return result, StripStats(kept=kept, stripped_phantom=stripped,
                              stripped_bare=bare)


def strip_phantom_tags(
    text: str, anchors: GroundingAnchors
) -> tuple[str, StripStats]:
    """Вырезать фантомные ``fact:``-теги. Никогда не бросает.

    Пустая строка → ``("", stats(0,0,0))``. Ошибка внутри → исходный текст
    без изменений (fail-open: validator аддитивен и не должен ломать ответ).
    """
    source = str(text or "")
    if not source:
        return source, StripStats(0, 0, 0)
    try:
        return _strip_impl(source, anchors)
    except Exception:  # pragma: no cover - defensive
        logger.warning("[grounding] validator error — text passed through")
        return source, StripStats(0, 0, 0)
