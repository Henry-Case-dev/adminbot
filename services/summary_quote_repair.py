"""ASAP-4 волна C (epic `asap-4-embedding-graphrag-cover-runtime`) — quote
reason codes + deterministic repair pipeline (spec §3 C.2, ADR-1028-7 D7.2;
T-4423; ТЗ §53/§53.1/§53.2/§54, §50.20).

Прод-болезнь (Q18): валидатор L2 путал ТИПОГРАФСКУЮ кавычку с семантической
атрибуцией — именная цитата reject'илась `quote_attribution` даже когда
текст цитаты ЕСТЬ в пакете (`quote_unverified=0` при reject), и одна
repairable цитата уносила всю 688-message статью в Legacy.

Контракт (§50.20 после ASAP-4):

    quote found + speaker доказан   → valid
    quote found + speaker не доказан → needs_fix (repair)
    quote not found                  → paraphrase / de-quote

**Это НЕ нормализация кавычек** (§53.1): типографика — formatting concern;
здесь — семантическая атрибуция прямой цитаты: (1) текст цитаты в
source/evidence; (2) source принадлежит именно этому спикеру; (3) цитата не
вырвана из чужого reply/forward; (4) имя рядом ≠ proof.

Reason codes (§53.1): ``quote_text_not_found`` / ``quote_speaker_unresolved``
/ ``quote_speaker_mismatch`` / ``quote_source_ambiguous`` /
``quote_attribution_repaired`` (umbrella ``quote_attribution`` остаётся для
совместимости логов/OFF-пути; Analytics видит подпричину).

**Один контракт с MCA-22 D3 Quote Resolver — EXTENSION, не fork**
(conflict-audit §6): наследуются семантика лестницы (text → speaker →
source), статусы ``resolved|ambiguous|unresolved`` из
``services/quote_resolver`` и его инварианты («ближайшее имя ≠ proof
speaker», «unknown > hallucinated», «≥2 уверенных автора → ambiguous»).
L2-случай, который лестница не покрывает, — резолв против **FactPackage**
(внутрипайплайновый, синхронный, без БД/ledger/FTS-ступеней 1–2/5–6) —
реализован здесь как extension той же лестницы, БЕЗ второго resolver'а
живого контура (Wave D T-4430/T-4431 переиспользуют этот слой).

Repair pipeline (§53.2): extract quotes → resolve против
FactPackage/SourceRefs → validate speaker → deterministic safe repair →
revalidate. Допустимые repairs: de-quote в пересказ; снять имя спикера при
известном факте; удалить только недоказуемую формулировку; direct →
indirect speech. Запрещены (здесь кодом недостижимы): invent text/speaker,
смена смысла, скрытие contradiction, тихий drop куска статьи.

Attribution НЕ ослабляется (§54): неподтверждённая прямая речь не
публикуется никогда — если repair невозможен, документ fail-closed.

Метрики (safe, без текстов цитат): ``quotes_total / verified / repaired /
removed / failure_reason``.

Kill-switch ``SUMMARY_QUOTE_REPAIR_ENABLED`` (env, default ON): OFF →
прежняя validator-матрица §50.20 бит-в-бит (баг живёт — осознанный
rollback-контур).

Чистый модуль (0 LLM, без БД/сети/часов); детерминированно.
"""
from __future__ import annotations

import dataclasses
import logging
import re

from config.settings import settings
# EXTENSION, не fork: статусы/семантика лестницы MCA-22 D3 (ADR-1028-6).
from services.quote_resolver import (
    QUOTE_AMBIGUOUS,
    QUOTE_RESOLVED,
    QUOTE_UNRESOLVED,
)
from services.summary_l2_writer import (
    _QUOTE_RE,
    _has_named_attribution,
    _normalize_quote,
    _quote_matches_pool,
    _strip_quotes,
)

logger = logging.getLogger(__name__)

# ── Kill-switch (spec §8.2) ────────────────────────────────────────────────

def quote_repair_enabled() -> bool:
    """``SUMMARY_QUOTE_REPAIR_ENABLED`` (env-only, default ON; резолв
    per-call, никогда не бросает). OFF → прежняя validator-матрица."""
    try:
        return bool(getattr(settings, "SUMMARY_QUOTE_REPAIR_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


# ── Reason codes §53.1 (mca_events.REASON_CODES — тот же словарь) ──────────

REASON_QUOTE_TEXT_NOT_FOUND = "quote_text_not_found"
REASON_QUOTE_SPEAKER_UNRESOLVED = "quote_speaker_unresolved"
REASON_QUOTE_SPEAKER_MISMATCH = "quote_speaker_mismatch"
REASON_QUOTE_SOURCE_AMBIGUOUS = "quote_source_ambiguous"
REASON_QUOTE_ATTRIBUTION_REPAIRED = "quote_attribution_repaired"
# Umbrella (совместимость логов/OFF-пути).
REASON_QUOTE_ATTRIBUTION = "quote_attribution"

# Глагольные маркеры атрибуции — «сказал/написал/…», НЕ имена: префиксный
# парсер не должен принять `сказал:` за speaker name.
_SPEECH_VERBS = frozenset({
    "сказал", "сказала", "сказали", "говорит", "говорил", "говорила",
    "написал", "написала", "заявил", "заявила", "ответил", "ответила",
    "добавил", "добавила", "произнёс", "произнес", "воскликнул",
    "воскликнула", "спросил", "спросила", "подытожил", "подытожила",
    "заметил", "заметила", "заключил", "заключила",
})

# Префиксная атрибуция непосредственно перед цитатой: `Имя: «…»`.
_PREFIX_NAME_RE = re.compile(
    r"([A-Za-zА-Яа-яЁё0-9_@\-]{2,30})\s*:\s*$")
# Хвостовая атрибуция сразу после цитаты: `«…», — сказал Имя` / `«…», —
# сказал`. Начало строго на границе цитаты (after начинается с quote-end).
_TAIL_RE = re.compile(
    r"^\s*,?\s*[—\-–]?\s*"
    r"(?:сказал|сказала|написал|написала|заявил|заявила|ответил|ответила|"
    r"добавил|добавила|произнёс|произнес|воскликнул|воскликнула)\b"
    r"(?:\s+([A-Za-zА-Яа-яЁё0-9_@\-]{2,30}))?",
    re.IGNORECASE)


@dataclasses.dataclass
class QuoteStats:
    """Метрики §53.2 (R17-safe: только числа/коды; тексты цитат не логируются
    и в stats не попадают)."""

    quotes_total: int = 0
    verified: int = 0
    repaired: int = 0
    removed: int = 0
    reason_codes: list = dataclasses.field(default_factory=list)
    failure_reason: str | None = None

    def as_metrics(self) -> dict:
        return {
            "quotes_total": self.quotes_total,
            "quotes_verified": self.verified,
            "quotes_repaired": self.repaired,
            "quotes_removed": self.removed,
            "quote_reason_codes": sorted(set(self.reason_codes)),
            "quote_failure_reason": self.failure_reason,
        }


# ── Резолв против FactPackage (extension лестницы: text → speaker) ─────────

def _fragment_speaker_index(package) -> list[tuple[str, str, int | None]]:
    """``[(normalized_text, display_name, author_id), …]`` из фрагментов
    пакета (§12 v2-фрагменты несут полный авторский контекст)."""
    index: list[tuple[str, str, int | None]] = []
    threads = package.get("threads") if isinstance(package, dict) else None
    for thread in threads or []:
        if not isinstance(thread, dict):
            continue
        for fragment in thread.get("fragments") or []:
            if not isinstance(fragment, dict):
                continue
            text = fragment.get("text")
            if not isinstance(text, str) or not text:
                continue
            name = str(fragment.get("display_name") or "").strip()
            author = fragment.get("author_id")
            index.append((_normalize_quote(text) or text.casefold(), name,
                          author if isinstance(author, int)
                          and not isinstance(author, bool) else None))
    return index


def _resolve_speaker(quote: str, speaker_index) -> tuple[str, str | None]:
    """Ступень text→speaker лестницы против пакета (§53.1 п.1–2/4).

    Возвращает ``(status, display_name)``: ``resolved`` — ровно один
    уверенный автор; ``ambiguous`` — ≥2 разных авторов; ``unresolved`` —
    цитата в пакете есть только среди facts (без авторского контекста) либо
    вовсе без фрагментного вхождения. Ближайшее имя НЕ подставляется.
    """
    core = _normalize_quote(quote)
    if not core:
        return QUOTE_UNRESOLVED, None
    authors: dict[str, int | None] = {}
    for text, name, author in speaker_index:
        if core in text and name:
            authors[name] = author
    if len(authors) > 1:
        return QUOTE_AMBIGUOUS, None
    if len(authors) == 1:
        name = next(iter(authors))
        return QUOTE_RESOLVED, name
    return QUOTE_UNRESOLVED, None


def _names_equivalent(attributed: str, resolved: str | None) -> bool:
    """Имя из атрибуции совпадает с автором фрагмента (нормализованное
    равенство либо вхождение — «Вася» vs «Вася Пупкин»); смена имени в окне
    и дубли имён — ответственность roster/D.2, здесь только честный матч."""
    if not attributed or not resolved:
        return False
    a = attributed.strip().casefold()
    r = resolved.strip().casefold()
    if not a or not r:
        return False
    return a == r or a in r or r in a


def _extract_speaker_name(text: str, quote: str) -> str | None:
    """Имя атрибуции вокруг цитаты (префикс `Имя:` / хвост `— сказал Имя`).

    Глагол речи именем не считается (§53.1: типографика/глагол ≠ speaker).
    """
    index = text.find(quote)
    if index < 0:
        return None
    before = text[max(0, index - 40):index]
    match = _PREFIX_NAME_RE.search(before)
    if match:
        candidate = match.group(1)
        if candidate.strip().casefold() not in _SPEECH_VERBS:
            return candidate
    after = text[index + len(quote):index + len(quote) + 60]
    tail = _TAIL_RE.match(after)
    if tail and tail.group(1):
        return tail.group(1)
    return None


def _repair_quote_span(text: str, quote: str) -> tuple[str, bool]:
    """Deterministic safe repair одной цитаты (§53.2): снять атрибуцию
    (префикс `Имя:` / хвост `— сказал Имя`), затем прямую речь → косвенную
    (de-quote). Текст события вокруг сохраняется; нового текста не
    появляется; возвращает ``(new_text, repaired)``."""
    new_text = text
    index = new_text.find(quote)
    if index < 0:
        return new_text, False
    before = new_text[max(0, index - 40):index]
    match = _PREFIX_NAME_RE.search(before)
    if match and match.group(1).strip().casefold() not in _SPEECH_VERBS:
        start = index - (len(before) - match.start())
        new_text = new_text[:start] + new_text[index:]
        index = new_text.find(quote)
    if index >= 0:
        after = new_text[index + len(quote):index + len(quote) + 60]
        tail = _TAIL_RE.match(after)
        if tail:
            new_text = (new_text[:index + len(quote)]
                        + new_text[index + len(quote) + tail.end():])
    if quote not in new_text:
        return new_text, False
    new_text = new_text.replace(quote, _strip_quotes(quote), 1)
    # Хвост «: » после снятия атрибуции не должен оставаться висячим перед
    # пересказом; двойные пробелы схлопываются.
    new_text = re.sub(r":\s+(:\s*)+", ": ", new_text)
    new_text = re.sub(r"\s{2,}", " ", new_text).strip()
    return new_text, True


def _remove_quote_span(text: str, quote: str) -> tuple[str, bool]:
    """Последняя линия (§53.2 «удалить только недоказуемую формулировку,
    сохранив событие»): убрать атрибуцию и саму цитату ЦЕЛИКОМ; текст
    события вокруг сохраняется. Пустой абзац после удаления — не ok
    (вызывающий остаётся fail-closed)."""
    new_text, _repaired = _repair_quote_span(text, quote)
    core = _strip_quotes(quote)
    if core in new_text:
        new_text = new_text.replace(core, "", 1)
    new_text = re.sub(r"\s{2,}", " ", new_text).strip(" ,;:—-").strip()
    if not new_text:
        return text, False
    return new_text, True


def process_paragraph_quotes(text: str, package) -> tuple[str, QuoteStats]:
    """Quote pipeline §53.2 для ОДНОГО абзаца: extract → resolve → validate
    speaker → repair → revalidate. Возвращает ``(text, stats)``.

    Решения (матрица §50.20-после + §53.1):
      * quote в пуле + БЕЗ атрибуции → verified, без изменений;
      * quote в пуле + атрибуция + speaker доказан (имя = автору
        фрагмента) → **valid** (фикс бага §50.20 — именная цитата не
        reject'ится);
      * quote в пуле + атрибуция + speaker unresolved → repair (снять имя +
        de-quote) → ``quote_speaker_unresolved``;
      * quote в пуле + атрибуция + speaker ≠ автор фрагмента → repair →
        ``quote_speaker_mismatch``;
      * quote в пуле + атрибуция + ≥2 авторов-кандидатов → repair →
        ``quote_source_ambiguous``;
      * quote НЕ в пуле → repair (de-quote, атрибуция снимается при
        наличии) → ``quote_text_not_found``;
      * успешный любой repair → дополнительно
        ``quote_attribution_repaired``.
    Не бросает; при невозможности repair у неподтверждённой цитаты ставит
    ``failure_reason`` — вызывающий валидатор делает fail-closed.
    """
    stats = QuoteStats()
    quotes = _QUOTE_RE.findall(str(text or ""))
    stats.quotes_total = len(quotes)
    if not quotes:
        return text, stats
    speaker_index = _fragment_speaker_index(package)
    pool_normalized = [_normalize_quote(t) for t in _package_text_pool(package)]
    pool_normalized = [v for v in pool_normalized if v]
    working = str(text or "")
    # До двух проходов (revalidate §53.2); обработанные цитаты не считаются
    # повторно (дедуп по строке цитаты — детерминированно).
    processed: set[str] = set()
    for _pass in range(2):
        changed = False
        for quote in _QUOTE_RE.findall(working):
            if quote in processed:
                continue
            processed.add(quote)
            in_pool = _quote_matches_pool(quote, pool_normalized)
            has_attribution = _has_named_attribution(quote, working) \
                or _extract_speaker_name(working, quote) is not None
            if in_pool and not has_attribution:
                stats.verified += 1
                continue
            if in_pool and has_attribution:
                status, resolved_name = _resolve_speaker(quote, speaker_index)
                attributed = _extract_speaker_name(working, quote)
                if status == QUOTE_RESOLVED \
                        and _names_equivalent(attributed or "", resolved_name):
                    # Фикс §50.20: текст доказан + спикер доказан → valid.
                    stats.verified += 1
                    continue
                if status == QUOTE_AMBIGUOUS:
                    reason = REASON_QUOTE_SOURCE_AMBIGUOUS
                elif status == QUOTE_RESOLVED:
                    reason = REASON_QUOTE_SPEAKER_MISMATCH
                else:
                    reason = REASON_QUOTE_SPEAKER_UNRESOLVED
            else:
                reason = REASON_QUOTE_TEXT_NOT_FOUND
            # Repair (deterministic safe): снять атрибуцию + de-quote.
            removed = False
            repaired_text, ok = _repair_quote_span(working, quote)
            if not ok or quote in repaired_text:
                # De-quote не удался (цитата осталась) → удаление
                # недоказуемой формулировки с сохранением события.
                repaired_text, ok = _remove_quote_span(working, quote)
                removed = ok
            if not ok or not repaired_text.strip():
                # Repair невозможен → неподтверждённая прямая речь не
                # публикуется (§54): fail-closed с конкретной причиной.
                stats.failure_reason = reason
                return working, stats
            if removed:
                stats.removed += 1
            stats.reason_codes.append(reason)
            stats.reason_codes.append(REASON_QUOTE_ATTRIBUTION_REPAIRED)
            stats.repaired += 1
            working = repaired_text
            changed = True
        if not changed:
            break
    return working, stats


def _package_text_pool(package) -> list[str]:
    """Тексты пакета (facts ∪ fragments) — совместимо с
    ``summary_l2_writer._package_text_pool`` (тот же пул доказательств)."""
    pool: list[str] = []
    threads = package.get("threads") if isinstance(package, dict) else None
    for thread in threads or []:
        if not isinstance(thread, dict):
            continue
        for fact in thread.get("facts") or []:
            if isinstance(fact, dict) and isinstance(fact.get("text"), str):
                pool.append(fact["text"])
        for fragment in thread.get("fragments") or []:
            if isinstance(fragment, dict) and isinstance(
                    fragment.get("text"), str):
                pool.append(fragment["text"])
    return pool
