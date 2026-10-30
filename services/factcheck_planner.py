"""CFG-06 W4 — планировщик проверки + структурный evidence (06C, бриф §W4).

Закрывает W0-находку 06A.4: поисковая формулировка была «дословный слайс
клейма + годы» (`temporal_factcheck.search_queries_for`). Здесь — осмысленные
запросы из claim_items (SuitabilityDecision, W2): сущности/числа/цитаты/годы,
2–4 запроса с различающей целью, privacy-фильтр (участники чата НЕ утекают в
веб, 06G.3), структурный evidence (тезис → выдержка → URL → тип) в
замороженные схемы `EvidenceRef`/`EvidenceMap` (W3, w3-schemas.md §1/§6).

Границы лейна W4:

* детерминированно — БЕЗ новых LLM-вызовов; поиск — существующий
  `SearchAggregator.search` (REUSE); первоисточники — существующий
  `SafeFetcher.fetch_text` (REUSE, «второй fetch-контур запрещён»), с
  инъекцией `fetch_text` для офлайн-тестов (прецедент
  `temporal_factcheck.enrich_evidence_dates`);
* план выполняется только за `FACTCHECK_PIPELINE_V2_ENABLED` (консолидация
  W3: планировщик — часть v2; OFF → модуль не вызывается);
* EvidenceMap наполняется только ДОКАЗАТЕЛЬСТВАМИ ТЕКУЩЕГО ПРОГОНА
  (allowlist = ID этого прогона, 06D/§18G3-совместимо);
* интеграция поиска в вычисление вердикта (поиск ДО вердикта строго по
  плану) — стадия W6; в W4 planner даёт структурированный evidence-слой
  presentation (аддитивно, ветки сервиса не меняются).
"""
from __future__ import annotations

import asyncio
import dataclasses
import datetime
import logging
import re

from services import temporal_factcheck as tf
from services.factcheck_orchestrator import EvidenceMap, EvidenceRef
from services.search_aggregator import (      # noqa: F401 — реэкспорт контракта
    DISPLAYABLE_EVIDENCE_ROLES,
    EVIDENCE_ROLE_BACKGROUND,
    EVIDENCE_ROLE_CONTRADICTS,
    EVIDENCE_ROLE_IRRELEVANT,
    EVIDENCE_ROLE_QUALIFIES,
    EVIDENCE_ROLE_SUPPORTS,
    EVIDENCE_ROLES,
    ClaimRelevance,
    claim_relevance,
    classify_source_kind,
)

logger = logging.getLogger(__name__)

# fp2 (FC-SEMQUERY/FC-EVIDQ, owner 21.10.2026 §3.3–3.4): запросы строятся
# от самостоятельных частей клейма (claim_items/предложения) + generic
# синонимы; выдача проверяется на содержательную релевантность.
# fp3 (P0-FACTCHECK, owner 24.10.2026 §3.3/§3.5): КАЖДАЯ проверяемая часть
# получает свой запрос (бюджет тот же ≤3) — составная публикация больше не
# сводится к одному запросу; свидетельство без URL не считается
# доказательством; бюджет запроса урезает per-engine таймауты.
# fp4 (ASAP-FC-EVIDENCE-STYLE-02 §3.1–3.3): per-claim retrieval — единица
# проверки (ClaimUnit) строится из тех же claim_items/предложений, каждая
# получает попытку поиска и свой статус; ссылка привязывается к claim только
# при подтверждении ЯКОРЯ тезиса (метрика/сущность/тикер); общий жёсткий
# 10-секундный потолок заменён адаптивным бюджетом по числу частей.
PLANNER_VERSION = "fp4"

# ── Статусы поиска по claim (§3.1/§4; эквивалент существующих метрик) ────────
CLAIM_SEARCH_NOT_ATTEMPTED = "not_attempted"
CLAIM_SEARCH_SEARCHED = "searched"
CLAIM_SEARCH_SOURCE_READ = "source_read"
CLAIM_SEARCH_SOURCE_FAILED = "source_failed"
CLAIM_SEARCH_DEADLINE = "deadline_exceeded"
CLAIM_SEARCH_PROVIDER_FAILED = "provider_failed"

#: §4: детализированный исход, который нельзя схлопывать в «данных
#: недостаточно». Публичные формулировки различают эти состояния; итоговый
#: verdict по-прежнему живёт в существующем enum ``FACTUAL_VERDICTS``.
CLAIM_STATUS_VERIFIED = "verified"
CLAIM_STATUS_REFUTED = "refuted"
CLAIM_STATUS_PARTIAL = "partial"
CLAIM_STATUS_NO_RELEVANT_SOURCES = "no_relevant_sources"
CLAIM_STATUS_EXACT_NUMBER = "evidence_insufficient_for_exact_number"
CLAIM_STATUS_CONFLICTING = "evidence_conflicting"
CLAIM_STATUS_SOURCE_EXTRACT = "source_extract_failed"
CLAIM_STATUS_PROVIDER_ERROR = "provider_error"
CLAIM_STATUS_DEADLINE = "deadline_exceeded"
CLAIM_STATUS_SEARCH_NOT_STARTED = "search_not_started"
CLAIM_STATUS_CLAIM_UNIDENTIFIED = "claim_unidentified"

# ── Итог проверки claim (§3.1; сопоставлен с FACTUAL_VERDICTS) ──────────────
CLAIM_OUTCOME_CONFIRMED = "confirmed"
CLAIM_OUTCOME_REFUTED = "refuted"
CLAIM_OUTCOME_PARTIAL = "partially_confirmed"
CLAIM_OUTCOME_CONFLICTING = "conflicting_evidence"
CLAIM_OUTCOME_INSUFFICIENT = "insufficient_evidence"
CLAIM_OUTCOME_TECHNICAL = "not_checked_technical"

CLAIM_OUTCOMES = (CLAIM_OUTCOME_CONFIRMED, CLAIM_OUTCOME_REFUTED,
                  CLAIM_OUTCOME_PARTIAL, CLAIM_OUTCOME_CONFLICTING,
                  CLAIM_OUTCOME_INSUFFICIENT, CLAIM_OUTCOME_TECHNICAL)

#: §4: сопоставление итога claim существующему verdict-enum (параллельной
#: системы вердиктов нет).
CLAIM_OUTCOME_TO_VERDICT = {
    CLAIM_OUTCOME_CONFIRMED: "supported",
    CLAIM_OUTCOME_REFUTED: "refuted",
    CLAIM_OUTCOME_PARTIAL: "mixed",
    CLAIM_OUTCOME_CONFLICTING: "mixed",
    CLAIM_OUTCOME_INSUFFICIENT: "insufficient_evidence",
    CLAIM_OUTCOME_TECHNICAL: "insufficient_evidence",
}

#: Итог claim → существующий reason-код реестра (mca_events.REASON_CODES).
CLAIM_OUTCOME_REASON = {
    CLAIM_STATUS_CONFLICTING: "contradictory_evidence",
    CLAIM_STATUS_DEADLINE: "deadline_exceeded",
    CLAIM_STATUS_PROVIDER_ERROR: "provider_unavailable",
    CLAIM_STATUS_SOURCE_EXTRACT: "source_missing",
    CLAIM_STATUS_NO_RELEVANT_SOURCES: "insufficient_evidence",
    CLAIM_STATUS_EXACT_NUMBER: "insufficient_evidence",
    CLAIM_STATUS_PARTIAL: "insufficient_evidence",
    CLAIM_STATUS_CLAIM_UNIDENTIFIED: "insufficient_evidence",
    CLAIM_STATUS_SEARCH_NOT_STARTED: "insufficient_evidence",
}

# ── Типы утверждений (§3.2: событие / величина / причинная интерпретация) ────
CLAIM_TYPE_FACT = "fact"
CLAIM_TYPE_NUMBER = "number"
CLAIM_TYPE_CHANGE = "change"
CLAIM_TYPE_CAUSE = "cause"
CLAIM_TYPE_QUOTE = "quote"
CLAIM_TYPE_FORECAST = "forecast"
CLAIM_TYPES = (CLAIM_TYPE_FACT, CLAIM_TYPE_NUMBER, CLAIM_TYPE_CHANGE,
               CLAIM_TYPE_CAUSE, CLAIM_TYPE_QUOTE, CLAIM_TYPE_FORECAST)

# Интенты запросов (06C: 2–4 запроса с различающей целью).
INTENT_ENTITY_CHECK = "entity_check"
INTENT_NUMERIC = "numeric_verification"
INTENT_TEMPORAL = "temporal_context"
INTENT_ORIGIN = "claim_origin"
INTENTS = (INTENT_ENTITY_CHECK, INTENT_NUMERIC, INTENT_TEMPORAL,
           INTENT_ORIGIN)

#: Назначение запроса в adaptive coverage-loop (§3.2): базовая попытка по
#: claim vs уточнение только для непокрытой части.
QUERY_PURPOSE_BASE = "base"
QUERY_PURPOSE_REFINE = "refine"

_MAX_QUERIES = 3                 # прежний потолок малых клеймов (совместимость)
_MAX_QUERIES_TOTAL_DEFAULT = 12  # потолок составной новости (настраивается)
_QUERY_MAX_CHARS = 200
_MAX_EVIDENCE_REFS = 12
_MAX_PRIMARY_FETCHES = 2
_EXCERPT_MAX_CHARS = 600


_NUMERIC_PHRASE_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:мм|см|дм|км|м|кг|г|тонн|тыс\.?|млн|млрд|%|"
    r"градус\w*|человек|чел)?", re.IGNORECASE)
_CAPITALIZED_RE = re.compile(
    r"(?<![.!?…]\s)(?<!^)\b[А-ЯЁA-Z][а-яёa-z]{3,}\b", re.UNICODE)
_QUOTED_RE = re.compile(r"[«\"]([^«»\"]{12,160})[»\"]")
_TAG_RE = re.compile(r"<[^>]+>")


def planner_enabled() -> bool:
    """Планировщик — часть pipeline v2 (консолидация W3): тот же рубильник.
    Default OFF → модуль не вызывается. Никогда не бросает."""
    try:
        from config.settings import settings
        default = bool(getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED",
                               False))
        from services import hot_config as hot
        return bool(hot.get("flags.factcheck_pipeline_v2", default))
    except Exception:      # pragma: no cover
        return False


# ── Схемы плана (локальные; замороженные Evidence* не меняются) ─────────────

@dataclasses.dataclass(frozen=True)
class SearchQuery:
    """Один осмысленный поисковый запрос с целью."""
    text: str
    intent: str
    max_symbols: int = 2500
    #: §3.2: запрос принадлежит конкретному проверяемому claim
    claim_id: str = ""
    #: §3.2: базовая попытка по claim vs уточнение непокрытой части
    purpose: str = QUERY_PURPOSE_BASE


@dataclasses.dataclass(frozen=True)
class ClaimUnit:
    """§3.1: единица проверки составной новости (минимальный контракт).

    ``claim_id`` + короткий текст + связь с исходным сообщением; сущности,
    метрики и единицы, временной интервал/часовой пояс; тип утверждения —
    событие / величина / изменение / причина / цитата / прогноз.
    """
    claim_id: str
    text: str
    source_link: str = ""
    entities: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    units: tuple[str, ...] = ()
    timeframe: str = ""
    timezone: str = ""
    claim_type: str = CLAIM_TYPE_FACT
    #: латинские имена/тикеры/варианты термина тезиса (международные новости)
    foreign_terms: tuple[str, ...] = ()
    #: временная точка события (unix ts), когда она однозначна
    event_at: int | None = None

    def vocabulary(self) -> str:
        """Словарь привязки источника к ЭТОМУ claim (текст + латинские
        имена/тикеры + метрики): по нему считается релевантность."""
        pieces = [self.text, *self.foreign_terms, *self.metrics]
        return " ".join(p for p in pieces if p)

    def as_dict(self) -> dict:
        """Служебная сериализация (payload аналитика/диагностика)."""
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "claim_type": self.claim_type,
            "entities": list(self.entities),
            "metrics": list(self.metrics),
            "units": list(self.units),
            "timeframe": self.timeframe,
            "timezone": self.timezone,
        }


@dataclasses.dataclass(frozen=True)
class ClaimEvidence:
    """§3.1: доказательство с РОЛЬЮ для конкретного claim."""
    claim_id: str
    evidence_id: str
    url: str | None = None
    role: str = EVIDENCE_ROLE_QUALIFIES
    published_at: int | None = None
    event_at: int | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
            "url": self.url,
            "role": self.role,
            "published_at": self.published_at,
            "event_at": self.event_at,
            "note": self.note,
        }


@dataclasses.dataclass(frozen=True)
class ClaimCoverage:
    """§3.1/§4: полный исход проверки одного claim."""
    claim: ClaimUnit
    search_status: str = CLAIM_SEARCH_NOT_ATTEMPTED
    status_detail: str = CLAIM_STATUS_SEARCH_NOT_STARTED
    outcome: str = CLAIM_OUTCOME_INSUFFICIENT
    reason_code: str | None = None
    gap_note: str = ""
    queries_count: int = 0
    candidates: int = 0
    opened: int = 0
    provider_status: tuple[str, ...] = ()
    evidence: tuple[ClaimEvidence, ...] = ()
    citation_ids: tuple[str, ...] = ()

    @property
    def displayable_evidence(self) -> tuple[ClaimEvidence, ...]:
        """Только роли, которые можно показывать рядом с тезисом (§3.3)."""
        return tuple(e for e in self.evidence if e.role in
                     DISPLAYABLE_EVIDENCE_ROLES)

    def as_dict(self) -> dict:
        return {
            "claim": self.claim.as_dict(),
            "search_status": self.search_status,
            "status_detail": self.status_detail,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "gap_note": self.gap_note,
            "queries_count": self.queries_count,
            "candidates": self.candidates,
            "opened": self.opened,
            "provider_status": list(self.provider_status),
            "evidence": [e.as_dict() for e in self.evidence],
            "citation_ids": list(self.citation_ids),
        }


@dataclasses.dataclass(frozen=True)
class RetrievalPlan:
    """План поисковых действий (06C.1): запросы, порядок, типы источников."""
    queries: tuple[SearchQuery, ...] = ()
    needs_web: bool = False
    needs_chat_history: bool = False
    needs_primary_fetch: bool = False
    dropped_privacy: tuple[str, ...] = ()   # удалённые имена участников
    claim_text: str = ""
    plan_version: str = PLANNER_VERSION
    #: §3.1: проверяемые единицы составной новости (каждая получает попытку)
    claims: tuple[ClaimUnit, ...] = ()
    #: §3.1: ссылка на исходное сообщение/цитату (трассировка claim → пост)
    source_link: str = ""

    def queries_for(self, claim_id: str) -> tuple[SearchQuery, ...]:
        """Запросы КОНКРЕТНОЙ части; непомеченные — только когда часть одна
        (ручной/legacy план), иначе один запрос пошёл бы всем частям."""
        labeled = tuple(q for q in self.queries if q.claim_id == claim_id)
        if labeled:
            return labeled
        if len(self.claims) <= 1:
            return tuple(q for q in self.queries if not q.claim_id)
        return ()



def _claim_terms(text: str, *, limit: int = 8) -> list[str]:
    """Ключевые термины клейма — ДЕТЕРМИНИРОВАННО по исходному порядку
    (W6: set-итерация давала плавающий порядок запросов между процессам).
    Токены в lowercase (поисковый запрос), без стоп-слов, дедуп."""
    from services.factcheck_context import _STOPWORDS
    seen: set[str] = set()
    terms: list[str] = []
    for match in re.finditer(r"[0-9a-zа-яё]+", str(text or "").lower()):
        raw = match.group(0)
        if len(raw) < 4 or raw in _STOPWORDS or raw in seen:
            continue
        seen.add(raw)
        terms.append(raw)
        if len(terms) >= limit:
            break
    return terms


# ── FC-SEMQUERY (owner §3.3): generic синонимы/терминология ─────────────────
# Общие разговорные→книжные пары БЕЗ предметных терминов (работают на
# произвольной теме: медицина, история, экономика, технологии). Дают
# поисковику вторую формулировку того же смысла: в публикациях для широкой
# аудитории почти всегда разговорное слово, в проверяемых источниках —
# книжное. Никаких медицинских/тематических словарей.
_SYNONYM_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("всплеск", ("рост", "увеличение")),
    ("скачок", ("рост", "повышение")),
    ("рекорд", ("максимум", "рекордный")),
    ("болезнь", ("заболевание",)),
    ("заболели", ("заболеваемость",)),
    ("врачи", ("медики", "специалисты")),
    ("учёные", ("исследователи", "специалисты")),
    ("молодёжь", ("молодые",)),
    ("подорожал", ("рост", "цен")),
    ("подешевел", ("снижение", "цен")),
    ("вырос", ("рост",)),
    ("упал", ("снижение",)),
    ("запретили", ("запрет", "ограничение")),
    ("разрешили", ("разрешение",)),
    ("отменили", ("отмена",)),
    ("закрыли", ("закрытие",)),
    ("открыли", ("открытие",)),
    ("выпустил", ("выпуск", "запуск")),
)


def _expand_terms(terms: list[str], *, limit: int = 12) -> list[str]:
    """Дописать 1–2 generic-синонима для встретившихся слов (порядок
    детерминированный, дедуп, потолок ``limit``)."""
    out = list(terms)
    low = {t.lower() for t in out}
    for word, synonyms in _SYNONYM_GROUPS:
        if word in low:
            for syn in synonyms:
                if syn not in low and len(out) < limit:
                    out.append(syn)
                    low.add(syn)
    return out


def _entities(text: str) -> list[str]:
    """Потенциальные именованные сущности: капитализированные токены НЕ в
    начале предложения (детерминированно, без LLM)."""
    out: list[str] = []
    for match in _CAPITALIZED_RE.finditer(str(text or "")):
        token = match.group(0)
        if token.lower() not in {t.lower() for t in out}:
            out.append(token)
    return out[:4]


def _numeric_phrases(text: str) -> list[str]:
    """Числовые фразы с единицами (для numeric_verification)."""
    phrases: list[str] = []
    for match in _NUMERIC_PHRASE_RE.finditer(str(text or "")):
        phrase = match.group(0).strip()
        if phrase and any(ch.isdigit() for ch in phrase):
            phrases.append(phrase)
    return phrases[:3]


def _years(text: str) -> list[str]:
    years: list[str] = []
    for match in tf._YEAR_RE.finditer(str(text or "")):
        year = match.group(1)
        if year not in years:
            years.append(year)
    return years[:3]


def _strip_privacy(text: str, authors: tuple[str, ...]
                   ) -> tuple[str, tuple[str, ...]]:
    """Privacy-фильтр (06G.3): имена участников чата не уходят в веб-запрос."""
    dropped: list[str] = []
    clean = str(text or "")
    for author in authors:
        name = str(author or "").strip()
        if len(name) < 4:
            continue
        pattern = re.compile(r"\b" + re.escape(name) + r"\w*\b", re.IGNORECASE)
        if pattern.search(clean):
            dropped.append(name)
            clean = pattern.sub(" ", clean)
    clean = re.sub(r"\s{2,}", " ", clean).strip(" -,")
    return clean, tuple(dropped)


def _make_query(terms: list[str], intent: str, *, tail: str = "",
                quoted: str = "", claim_id: str = "",
                purpose: str = QUERY_PURPOSE_BASE) -> SearchQuery | None:
    parts = list(terms)
    if quoted:
        parts.insert(0, f"«{quoted}»")
    if tail:
        parts.append(tail)
    text = " ".join(p for p in parts if p)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) < 6:
        return None
    return SearchQuery(text=text[:_QUERY_MAX_CHARS], intent=intent,
                       claim_id=claim_id, purpose=purpose)


def build_retrieval_plan(decision, ctx=None, *,
                         claim_text: str | None = None,
                         max_queries: int | None = None,
                         ) -> RetrievalPlan | None:
    """SuitabilityDecision/ClaimItem → план поисковых действий.

    Gate/планировщик OFF (default) или проверять нечего → None — вызывающий
    не выполняет НИКАКИХ платных запросов (OFF-паритет). ``max_queries=None``
    → адаптивный бюджет по числу частей (§3.2); явное число — потолок
    вызывающего. Никогда не бросает."""
    if not planner_enabled():
        return None
    try:
        return _build_plan_inner(decision, ctx, claim_text=claim_text,
                                 max_queries=max_queries)
    except Exception:
        logger.warning("[factcheck_planner] plan build failed", exc_info=True)
        return None


def _claim_units(items, claim: str, *, cap: int = 8) -> list[str]:
    """FC-SEMQUERY: самостоятельные проверяемые части для запросов —
    верифицируемые тексты claim_items; единый тезис-«всё сообщение»
    разбивается на предложения (как decompose_claim). Детерминированно."""
    units: list[str] = []
    for item in items or ():
        text = str(getattr(item, "text", "") or "").strip()
        if text and getattr(item, "verifiable", True) is not False \
                and text.lower() not in {u.lower() for u in units}:
            units.append(text)
    if not units or (len(units) == 1 and units[0].lower() == claim.lower()):
        # гейт не декомпозировал → предложения самого клейма
        units = [s.strip() for s in re.split(r"(?<=[.!?;])\s+", claim)
                 if s.strip()] or [claim]
    return [u for u in units if u][:cap]


_YEAR_ONLY_RE = re.compile(
    r"^\s*\d{4}\s*(?:г\.?|год[а-я]*|года|году)?\s*$", re.IGNORECASE)


def _numeric_refinements(unit: str, years: list[str]) -> list[str]:
    """Числовые уточнения БЕЗ годов: «2019 г» — временной контекст, а не
    измеряемая метрика («120 мм»)."""
    out: list[str] = []
    for phrase in _numeric_phrases(unit):
        if _YEAR_ONLY_RE.match(phrase):
            continue
        if phrase in years:
            continue
        out.append(phrase)
    return out


# ── §3.1/§3.2: разбор claim-единицы (сущности/метрики/интервал/тип) ──────────

_MAX_CLAIM_UNITS = 8

#: Латинские имена/тикеры/варианты термина (международные новости: «Alphabet
#: (GOOGL)», «S&P 500», «Nasdaq»). Именно они уходят в англоязычный запрос —
#: русская формулировка поста больше не запирает поиск в русских пересказах.
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9&.\-]{1,}")
_LATIN_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
    "has", "have", "had", "but", "not", "you", "all", "any", "can", "its",
    "his", "her", "our", "their", "they", "will", "would", "could", "should",
    "after", "before", "over", "under", "than", "into", "out", "off", "per",
    "on", "in", "of", "to", "as", "at", "by", "is", "it", "be", "or", "an",
    "a", "vs", "via", "amp", "http", "https", "www", "com", "ru",
})

#: Относительные временные формулировки (сохраняются как интервал тезиса).
_RELATIVE_TIMEFRAME_RE = re.compile(
    r"\b(сегодня|вчера|позавчера|на этой неделе|на прошлой неделе|"
    r"в этом месяце|в прошлом месяце|today|yesterday|last week|this week)\b",
    re.IGNORECASE)
_DATE_DOTTED_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4}|\d{2})\b")
_DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTHS_RU = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11,
    "декабр": 12,
}
_MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_TZ_RE = re.compile(
    r"\b(UTC|GMT|MSK|EST|EDT|PST|CET|CEST|по Москве|по Нью-Йорку)\b",
    re.IGNORECASE)
_CAUSE_RE = re.compile(
    r"\b(из-за|потому что|в результате|на фоне|вследствие|причин\w*|"
    r"because|due to|caused by|after)\b", re.IGNORECASE)
_FORECAST_RE = re.compile(
    r"\b(прогноз\w*|ожида\w*|предсказ\w*|может|могут|будет|будут|"
    r"forecast\w*|expected|may|might|will)\b", re.IGNORECASE)
_CHANGE_RE = re.compile(
    r"\b(упал\w*|падени\w*|снизил\w*|снижени\w*|вырос\w*|рост\w*|"
    r"подорожал\w*|подешевел\w*|потерял\w*|потери|обвал\w*|рухнул\w*|"
    r"fell|dropped|declined|slumped|rose|gained|lost|plunge\w*)\b",
    re.IGNORECASE)
_UNIT_RE = re.compile(
    r"(млрд|млн|тыс|трлн|%|процент\w*|п\.п\.|руб\w*|доллар\w*|\$|€|"
    r"billion|trillion|million|percent|points?|пункт\w*)", re.IGNORECASE)


def _latin_terms(text: str) -> list[str]:
    """Латинские имена/тикеры/варианты термина тезиса (детерминированно)."""
    out: list[str] = []
    low_seen: set[str] = set()
    for match in _LATIN_TOKEN_RE.finditer(str(text or "")):
        token = match.group(0).strip(".-")
        low = token.lower()
        if len(low) < 2 or low in _LATIN_STOPWORDS or low in low_seen:
            continue
        low_seen.add(low)
        out.append(token)
    return out


def _claim_metrics(unit: str, years: list[str]) -> list[str]:
    """Метрики тезиса: числа с единицами/валютой (§3.2 «величина»)."""
    return _numeric_refinements(unit, years)


def _metric_units(metrics: list[str]) -> list[str]:
    """Единицы измерения из метрик (млрд/млн/%/$/billion …) — различают
    абсолютное значение, проценты и пункты при сверке с источником."""
    out: list[str] = []
    for metric in metrics:
        for match in _UNIT_RE.finditer(str(metric)):
            unit = match.group(1).lower()
            if unit not in out:
                out.append(unit)
    return out


def _date_point_ts(day: int, month: int, year: int | None) -> int | None:
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    year_value = year if year and year >= 1990 else None
    if year_value is None:
        return None
    try:
        return int(datetime.datetime(
            year_value, month, day, tzinfo=datetime.timezone.utc).timestamp())
    except ValueError:
        return None


def _claim_timeframe(unit: str, claim_years: list[str]) -> tuple[str, int | None]:
    """Временной интервал тезиса: фраза + точная точка события (§3.3).

    «30 октября» (без года) остаётся фразой без unix-точки — нельзя
    сравнивать с датой публикации, но и терять интервал нельзя."""
    text = str(unit or "")
    iso = _DATE_ISO_RE.search(text)
    if iso:
        ts = _date_point_ts(int(iso.group(3)), int(iso.group(2)),
                            int(iso.group(1)))
        return iso.group(0), ts
    dotted = _DATE_DOTTED_RE.search(text)
    if dotted:
        year = int(dotted.group(3))
        if year < 100:
            year += 2000
        ts = _date_point_ts(int(dotted.group(1)), int(dotted.group(2)), year)
        return dotted.group(0), ts
    low = text.lower()
    for prefix, month in _MONTHS_RU.items():
        idx = low.find(prefix)
        if idx < 0:
            continue
        around = low[max(0, idx - 4): idx + len(prefix) + 12]
        day_match = re.search(r"\b(\d{1,2})\b", around)
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", around)
        year = int(year_match.group(1)) if year_match else (
            int(claim_years[0]) if claim_years else None)
        day = int(day_match.group(1)) if day_match else 1
        ts = _date_point_ts(day, month, year) if day_match else None
        phrase = around.strip()
        return phrase[:60], ts
    for name, month in _MONTHS_EN.items():
        idx = low.find(name)
        if idx < 0:
            continue
        around = low[max(0, idx - 6): idx + len(name) + 12]
        day_match = re.search(r"\b(\d{1,2})\b", around)
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", around)
        year = int(year_match.group(1)) if year_match else (
            int(claim_years[0]) if claim_years else None)
        day = int(day_match.group(1)) if day_match else 1
        ts = _date_point_ts(day, month, year) if day_match else None
        return around.strip()[:60], ts
    relative = _RELATIVE_TIMEFRAME_RE.search(text)
    if relative:
        return relative.group(0), None
    if claim_years:
        return claim_years[0], None
    return "", None


def _claim_timezone(unit: str) -> str:
    match = _TZ_RE.search(str(unit or ""))
    return match.group(0) if match else ""


def _claim_type(unit: str, metrics: list[str]) -> str:
    """Тип утверждения (§3.2): цитата / причина / прогноз / изменение /
    величина / факт. Одна статья о падении рынка не доказывает ни сумму,
    ни причину — тип задаёт требования к привязке."""
    text = str(unit or "")
    if _QUOTED_RE.search(text):
        return CLAIM_TYPE_QUOTE
    if _CAUSE_RE.search(text):
        return CLAIM_TYPE_CAUSE
    if _FORECAST_RE.search(text):
        return CLAIM_TYPE_FORECAST
    if metrics and _CHANGE_RE.search(text):
        return CLAIM_TYPE_CHANGE
    if metrics:
        return CLAIM_TYPE_NUMBER
    if _CHANGE_RE.search(text):
        return CLAIM_TYPE_CHANGE
    return CLAIM_TYPE_FACT


def build_claim_units(items, claim: str, *, authors: tuple[str, ...] = (),
                      source_link: str = "") -> tuple[ClaimUnit, ...]:
    """§3.1: исходная новость → проверяемые claim-единицы (без LLM).

    Переиспользует существующую декомпозицию (`_claim_units`, те же
    claim_items/предложения), добавляя контракт: сущности, метрики/единицы,
    временной интервал/часовой пояс, тип утверждения и связь с сообщением.
    """
    claim_years = _years(claim)
    units: list[ClaimUnit] = []
    for index, raw_unit in enumerate(_claim_units(items, claim)):
        unit, _dropped = _strip_privacy(raw_unit, authors)
        if not unit:
            continue
        uterms = _claim_terms(unit, limit=8)
        entities = [e for e in _entities(unit)
                    if e.lower() not in {t.lower() for t in uterms}][:3]
        uyears = _years(unit) or claim_years
        metrics = _claim_metrics(unit, uyears)
        timeframe, event_at = _claim_timeframe(unit, uyears)
        if timeframe:
            # Числа самого временного интервала («30», «2026») — это КОГДА
            # событие, а не ЧТО измерено: иначе «30 октября» подтверждало бы
            # заявленную сумму совпадением дня месяца (§3.3).
            frame_numbers = set(re.findall(r"\d+", timeframe))
            metrics = [m for m in metrics
                       if set(re.findall(r"\d+", m)) - frame_numbers
                       or not set(re.findall(r"\d+", m))]
        units.append(ClaimUnit(
            claim_id=f"c{len(units) + 1}",
            text=unit,
            source_link=source_link,
            entities=tuple(entities),
            metrics=tuple(metrics),
            units=tuple(_metric_units(metrics)),
            timeframe=timeframe,
            timezone=_claim_timezone(unit),
            claim_type=_claim_type(unit, metrics),
            foreign_terms=tuple(_latin_terms(unit)),
            event_at=event_at))
        if len(units) >= _MAX_CLAIM_UNITS:
            break
    return tuple(units)


def adaptive_query_budget(claims_count: int, *, base: int = _MAX_QUERIES,
                          total: int | None = None) -> int:
    """§3.2: бюджет запросов зависит от числа существенных частей.

    Малый клейм сохраняет прежний потолок (``base``), составная новость
    получает по запросу на каждую часть (не больше ``total``): прежний
    «≤3 запроса на всю новость» оставлял большинство частей без попытки.
    """
    count = max(1, int(claims_count))
    limit_total = _max_queries_total() if total is None else int(total)
    return max(1, min(max(count, int(base)), max(1, int(limit_total))))


def _max_queries_total() -> int:
    """Потолок запросов на один прогон (настраиваемый, не «магические 3»)."""
    try:
        from services import hot_config as hot
        value = hot.get("limits.factcheck_max_queries_total",
                        _MAX_QUERIES_TOTAL_DEFAULT)
        return max(1, int(value))
    except Exception:      # pragma: no cover — конфиг не рвёт план
        return _MAX_QUERIES_TOTAL_DEFAULT


def refinement_query_for(claim: ClaimUnit) -> SearchQuery | None:
    """§3.2: уточняющий запрос ТОЛЬКО для непокрытой части.

    Сохраняет метрику с единицей и временной интервал (или латинское имя/
    тикер для международной новости) — то, чего не хватило базовой попытке.
    """
    try:
        if claim.foreign_terms:
            terms = list(claim.foreign_terms[:4])
        else:
            terms = _expand_terms(
                (list(claim.entities[:2])
                 + _claim_terms(claim.text, limit=6))[:8])
        tail_bits = list(claim.metrics[:2])
        if claim.timeframe:
            tail_bits.append(claim.timeframe)
        tail = " ".join(tail_bits).strip()
        intent = INTENT_NUMERIC if claim.metrics else INTENT_ENTITY_CHECK
        return _make_query(terms, intent, tail=tail,
                           claim_id=claim.claim_id,
                           purpose=QUERY_PURPOSE_REFINE)
    except Exception:      # pragma: no cover — уточнение не рвёт контур
        return None


def _build_plan_inner(decision, ctx, *, claim_text, max_queries
                      ) -> RetrievalPlan | None:
    if decision is None:
        return None
    scope = str(getattr(decision, "scope", "") or "")
    needs_web = scope in ("web", "web_and_chat")
    needs_chat = scope in ("chat_history", "web_and_chat")
    items = list(getattr(decision, "claim_items", ()) or ())
    claim = (str(claim_text) if claim_text else "").strip()
    if not claim:
        for item in items:
            if getattr(item, "source", "") == "literal":
                claim = str(getattr(item, "text", "") or "").strip()
                break
    if not claim:
        for item in items:
            text = str(getattr(item, "text", "") or "").strip()
            if text:
                claim = text
                break
    if not claim or not needs_web:
        return None

    authors: tuple[str, ...] = ()
    if ctx is not None:
        authors = tuple({str(m.author or "").strip()
                         for m in ctx.messages if m.author})
    claim, dropped = _strip_privacy(claim, authors)

    terms = _claim_terms(claim)
    entities = [e for e in _entities(claim)
                if e.lower() not in {t.lower() for t in terms}][:3]

    queries: list[SearchQuery] = []
    seen: set[str] = set()

    # §3.1/§3.2 (ASAP-FC-EVIDENCE-STYLE-02): единица проверки — claim unit.
    # Каждая существенная часть получает СВОЙ запрос (проход 1), уточнения
    # (числа/интервал) идут на остаток бюджета (проход 2). Бюджет зависит от
    # числа частей (§3.2), а не «≤3 на всю новость».
    units = build_claim_units(items, claim, authors=authors)
    if not units:
        units = (ClaimUnit(claim_id="c1", text=claim),)
    explicit_cap = max_queries is not None and int(max_queries) > 0
    max_queries_value = (int(max_queries) if explicit_cap
                         else adaptive_query_budget(len(units)))

    def _budget_reached() -> bool:
        return len(queries) >= max_queries_value

    def _add(query: SearchQuery | None) -> bool:
        if query is None or _budget_reached():
            return False
        key = query.text.lower()
        if key in seen:
            return False
        # 06A.4-фикс: запрос НЕ весь клейм дословно (реформулировка)
        if key == str(claim).lower().strip()[:_QUERY_MAX_CHARS]:
            return False
        seen.add(key)
        queries.append(query)
        return True

    base_units = units[:max_queries_value]
    refine_room = max(0, max_queries_value - len(base_units))

    for unit in base_units:
        uyears = _years(unit.text) or _years(claim)
        if unit.foreign_terms:
            # §3.2: международная новость — запрос по английскому имени/
            # тикеру/метрике, а не по русскому пересказу. Временной интервал
            # сохраняется, чтобы не искать «вообще когда-то» (§3.3).
            latin = list(unit.foreign_terms[:6])
            tail_bits = list(unit.metrics[:2])
            if refine_room <= 0 and uyears:
                tail_bits.extend(uyears[:1])
            if unit.timeframe and unit.timeframe not in tail_bits:
                tail_bits.append(unit.timeframe)
            _add(_make_query(latin, INTENT_ENTITY_CHECK,
                             tail=" ".join(tail_bits),
                             claim_id=unit.claim_id))
            continue
        uterms = _claim_terms(unit.text, limit=8)
        uents = [e for e in _entities(unit.text)
                 if e.lower() not in {t.lower() for t in uterms}][:3]
        base = _expand_terms((uents + uterms)[:10])
        if refine_room <= 0:
            # Слотов на отдельные уточнения нет — числа/годы/интервал части
            # идут в ЕЁ ЖЕ запрос, чтобы не потеряться (F4), а заявленный
            # временной интервал не размывается (§3.3).
            tail_bits = list(unit.metrics)
            if unit.metrics:
                tail_bits.extend(uyears)
            if unit.timeframe and unit.timeframe not in tail_bits:
                tail_bits.append(unit.timeframe)
            tail = " ".join(tail_bits).strip()
            _add(_make_query(base, INTENT_ENTITY_CHECK, tail=tail,
                             claim_id=unit.claim_id))
        else:
            _add(_make_query(base, INTENT_ENTITY_CHECK,
                             claim_id=unit.claim_id))
    # Проход 2: отдельные уточняющие интенты — только остаток бюджета.
    for unit in units:
        if _budget_reached():
            break
        if unit.foreign_terms:
            continue
        uterms = _claim_terms(unit.text, limit=8)
        years = _years(unit.text) or _years(claim)
        if unit.metrics:
            _add(_make_query(_expand_terms(uterms), INTENT_NUMERIC,
                             tail=" ".join(unit.metrics), claim_id=unit.claim_id,
                             purpose=QUERY_PURPOSE_REFINE))
        if _budget_reached():
            break
        if years:
            _add(_make_query(_expand_terms(uterms), INTENT_TEMPORAL,
                             tail=" ".join(years), claim_id=unit.claim_id,
                             purpose=QUERY_PURPOSE_REFINE))
    # Цитата → проверка происхождения (цитата может быть в любой части)
    quoted = _QUOTED_RE.search(claim)
    if quoted:
        _add(_make_query(entities or terms[:4], INTENT_ORIGIN,
                         quoted=quoted.group(1),
                         claim_id=units[0].claim_id if units else ""))
    # Деградация: ни одна часть не дала запроса (например, короткий клейм)
    if not queries:
        base = _expand_terms((entities + terms)[:8])
        _add(_make_query(base, INTENT_ENTITY_CHECK,
                         claim_id=units[0].claim_id if units else ""))
        years = _years(claim)
        if years:
            _add(_make_query(base, INTENT_TEMPORAL, tail=" ".join(years),
                             claim_id=units[0].claim_id if units else ""))
    if not queries:
        return None
    target_ref = getattr(decision, "target_ref", None)
    source_link = ""
    if isinstance(target_ref, dict) and target_ref.get("target_tg_message_id"):
        source_link = f"tg:{target_ref.get('target_tg_message_id')}"
    return RetrievalPlan(
        queries=tuple(queries), needs_web=True,
        needs_chat_history=needs_chat,
        needs_primary_fetch=True, dropped_privacy=dropped,
        claim_text=claim, claims=tuple(units), source_link=source_link)



# ── Структурный evidence (06C.5/06D.4) ───────────────────────────────────────

def evidence_refs_from_search(results_text: str, *,
                              intent: str | None = None,
                              max_rows: int = 6) -> tuple[EvidenceRef, ...]:
    """Структурированные EvidenceRef из выдачи агрегатора: URL отдельно от
    текста (06D.4), support = заголовок+сниппет (без URL-дублирования).
    FC-EVIDQ (§3.4): тип источника — classify_source_kind (первоисточник/
    исследование/энциклопедия/пересказ); дубли-блоки (url=None дубль) со
    срезаны."""
    if not results_text or not str(results_text).strip():
        return ()
    blocks = [b.strip() for b in re.split(r"\n\s*\n", str(results_text))
              if b.strip()]
    refs: list[EvidenceRef] = []
    seen: set[str] = set()
    for block in blocks:
        if len(refs) >= max(1, int(max_rows)):
            break
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        url = None
        text_lines: list[str] = []
        for line in lines:
            if url is None and line.lower().startswith(("http://", "https://")):
                url = line
                continue
            text_lines.append(line)
        if not text_lines:
            continue
        title = text_lines[0][:200]
        snippet = " ".join(text_lines[1:]).strip()
        support = f"{title}. {snippet}".strip(". ")[:400]
        if not support:
            continue
        key = re.sub(r"\W+", "", support.lower())[:100]
        if key in seen:                 # url=None дубли (FC-EVIDQ §3.4)
            continue
        seen.add(key)
        refs.append(EvidenceRef(
            evidence_id="",            # проставляется в EvidenceMap-сборке
            url=url, support=support,
            source_kind=classify_source_kind(url), published_at=None))
    return tuple(refs)


def _excerpt_from_html(html_text: str, *, limit: int = _EXCERPT_MAX_CHARS
                       ) -> str:
    """Первый содержательный абзац страницы (теги срезаны), cap 600."""
    text = _TAG_RE.sub(" ", str(html_text or ""))
    text = re.sub(r"\s{2,}", " ", text)
    for chunk in re.split(r"(?<=[.!?])\s+", text.strip()):
        chunk = chunk.strip()
        if len(chunk) >= 80:
            return chunk[:limit].rstrip()
    return text.strip()[:limit] if text.strip() else ""


async def fetch_primary_evidence(url: str, *, fetch_text=None,
                                 max_bytes: int = 65536,
                                 timeout: float = 4.0) -> EvidenceRef | None:
    """Первоисточник через СУЩЕСТВУЮЩИЙ SafeFetcher (REUSE; инъекция
    `fetch_text` — прецедент enrich_evidence_dates). Fail-open → None."""
    if not url or not str(url).lower().startswith(("http://", "https://")):
        return None
    try:
        if fetch_text is None:
            from services.safe_fetch import SafeFetcher
            fetch_text = SafeFetcher().fetch_text
        html_text = await fetch_text(str(url), max_bytes=max_bytes,
                                     timeout=timeout)
    except Exception:
        logger.info("[factcheck_planner] primary fetch failed | url=%s",
                    url, exc_info=True)
        return None
    excerpt = _excerpt_from_html(html_text)
    if not excerpt or len(excerpt) < 40:
        return None
    published_at, _source = tf.parse_publication_date(html_text, url)
    return EvidenceRef(evidence_id="", url=str(url), support=excerpt,
                       source_kind="primary", published_at=published_at)


def _assemble(refs: list[EvidenceRef]) -> EvidenceMap | None:
    """Проставить стабильные ID ev-N текущего прогона + allowlist."""
    assembled: list[EvidenceRef] = []
    for ref in refs[:_MAX_EVIDENCE_REFS]:
        assembled.append(dataclasses.replace(
            ref, evidence_id=f"ev-{len(assembled) + 1}"))
    if not assembled:
        return None
    return EvidenceMap(refs=tuple(assembled),
                       allowlist=tuple(r.evidence_id for r in assembled))


async def execute_retrieval(plan: RetrievalPlan, *, aggregator,
                            fetch_text=None, max_rows_per_query: int = 4
                            ) -> EvidenceMap | None:
    """Выполнить план: bounded 06C-запросы через существующий агрегатор +
    до 2 первоисточников через SafeFetcher → EvidenceMap текущего прогона.

    Ошибки запросов/фетчей не прерывают сбор (честная деградация); пусто →
    None. Никогда не бросает."""
    outcome = await run_retrieval(plan, aggregator=aggregator,
                                  fetch_text=fetch_text,
                                  max_rows_per_query=max_rows_per_query)
    return outcome.evidence_map


# ── W6: единый retrieval-контур v2 (06C.8: бюджеты/дедлайны + метрики) ──────

# Суммарный бюджет строк поиска, уходящих в user-content ветки (06C.8).
_SEARCH_TEXT_BUDGET_CHARS = 8000
# Базовый бюджет retrieval-контура (§3.2): больше НЕ безусловный потолок —
# на каждую дополнительную существенную часть добавляется доля базового
# бюджета, сверху действует технический предел прогона.
_BUDGET_SECONDS_DEFAULT = 10.0
_BUDGET_SECONDS_PER_EXTRA_CLAIM = 0.5
_BUDGET_SECONDS_MAX = 45.0
#: §3.2: сколько уточняющих запросов допускается на прогон (coverage-loop).
_REFINE_CALLS_DEFAULT = 3


def _hot_number(key: str, default: float) -> float:
    """Числовая настройка из существующего конфиг-слоя (fail-open)."""
    try:
        from services import hot_config as hot
        return float(hot.get(key, default))
    except Exception:      # pragma: no cover — конфиг не рвёт контур
        return float(default)


def resolve_retrieval_budget(claims_count: int,
                            *, base: float | None = None) -> float:
    """§3.2: адаптивный бюджет по числу существенных частей.

    Прежний скрытый жёсткий ``10s`` на любой составной фактчек оставлял
    части без проверки. Теперь база — на прогон, плюс доля базы за каждую
    дополнительную часть, с техническим пределом: не бесконечный поиск и
    не необоснованный расход API. Дедлайн честно фиксируется по claim.
    """
    base_value = float(_BUDGET_SECONDS_DEFAULT if base is None
                       else base)
    base_value = _hot_number("limits.factcheck_retrieval_seconds", base_value)
    cap = _hot_number("limits.factcheck_retrieval_seconds_max",
                      _BUDGET_SECONDS_MAX)
    extra = max(0, int(claims_count) - 1)
    return max(base_value, min(cap, base_value *
                               (1.0 + _BUDGET_SECONDS_PER_EXTRA_CLAIM * extra)))


def _refine_calls_limit() -> int:
    try:
        return max(0, int(_hot_number("limits.factcheck_refine_calls",
                                      _REFINE_CALLS_DEFAULT)))
    except Exception:      # pragma: no cover
        return _REFINE_CALLS_DEFAULT


@dataclasses.dataclass(frozen=True)
class RetrievalOutcome:
    """Результат единого retrieval-контура v2 + метрики 06G.7.

    P0-FACTCHECK (§3.6): ``provider_failures`` — сколько запросов упало на
    провайдерах/транспорте; вместе с ``budget_exhausted`` это позволяет
    factcheck_service отличить технический сбой от реального отсутствия
    доказательств (сегодня оба превращались в insufficient_evidence).

    P0-FACTCHECK-CORRECTIVE (§5.1): ``empty_results`` — провайдер ОТВЕТИЛ,
    но выдача пустая; ``irrelevant_results`` — выдача была, но не прошла
    relevance-фильтр. Оба — НЕ «провайдеры недоступны» и не входят в
    ``provider_failures``.

    ASAP-FC-EVIDENCE-STYLE-02 §3.1–§3.3: ``claims`` — покрытие ПО КАЖДОЙ
    проверяемой части (запросы/провайдеры/кандидаты/открытые/роль/итог/
    причина пробела); ``off_topic_sources_dropped`` — ссылки, снятые как
    нерелевантные конкретному тезису (в «Источники» не попадают)."""
    evidence_map: EvidenceMap | None
    search_text: str                 # объединённая выдача для user-content
    queries_attempted: int
    queries_used: int
    refs_collected: int
    fetch_errors: int
    budget_exhausted: bool
    planner_version: str = PLANNER_VERSION
    provider_failures: int = 0
    empty_results: int = 0
    irrelevant_results: int = 0
    claims: tuple[ClaimCoverage, ...] = ()
    off_topic_sources_dropped: int = 0
    stale_sources_dropped: int = 0
    refine_calls: int = 0
    budget_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return bool(self.search_text) or self.evidence_map is not None

    def coverage_summary(self) -> dict:
        """§6: компактный итог охвата одного хода (без текстов и секретов)."""
        def _n(pred) -> int:
            return sum(1 for c in self.claims if pred(c))
        return {
            "total_claims": len(self.claims),
            "claims_searched": _n(lambda c: c.search_status in (
                CLAIM_SEARCH_SEARCHED, CLAIM_SEARCH_SOURCE_READ)),
            "claims_with_direct_evidence": _n(
                lambda c: bool(c.displayable_evidence)),
            "claims_partial": _n(
                lambda c: c.outcome in (CLAIM_OUTCOME_PARTIAL,
                                       CLAIM_OUTCOME_CONFLICTING)),
            "claims_unchecked_due_to_deadline": _n(
                lambda c: c.search_status == CLAIM_SEARCH_DEADLINE
                or c.status_detail == CLAIM_STATUS_DEADLINE),
            "off_topic_sources_dropped": self.off_topic_sources_dropped,
            "stale_sources_dropped": self.stale_sources_dropped,
            "refine_calls": self.refine_calls,
            "queries_attempted": self.queries_attempted,
            "queries_used": self.queries_used,
            "budget_exhausted": bool(self.budget_exhausted),
            "planner_version": self.planner_version,
        }


def _pseudo_claim(claim_text: str) -> ClaimUnit:
    """План без claim-единиц (ручные/legacy планы) → одна единица проверки."""
    text = str(claim_text or "").strip() or "утверждение"
    years = _years(text)
    metrics = _claim_metrics(text, years)
    timeframe, event_at = _claim_timeframe(text, years)
    return ClaimUnit(claim_id="c1", text=text,
                     entities=tuple(_entities(text)),
                     metrics=tuple(metrics),
                     units=tuple(_metric_units(metrics)),
                     timeframe=timeframe,
                     timezone=_claim_timezone(text),
                     claim_type=_claim_type(text, metrics),
                     foreign_terms=tuple(_latin_terms(text)),
                     event_at=event_at)


class _ClaimRun:
    """Изменяемый аккумулятор покрытия ОДНОЙ части (внутренний)."""

    def __init__(self, claim: ClaimUnit) -> None:
        self.claim = claim
        self.attempts = 0
        self.candidates = 0
        self.opened = 0
        self.providers: list[str] = []
        self.bound: dict[str, tuple[EvidenceRef, str, str]] = {}
        self.fetch_failed = 0
        self.provider_failed = 0
        self.deadline_hit = False
        self.empty = 0
        self.irrelevant = 0
        #: тексты уже выполненных запросов этой части (без повторов «того же»)
        self.attempted_texts: set[str] = set()
        #: найденая публикация оказалась старше заявленного события (§3.3)
        self.stale_hit = False

    def key(self, ref: EvidenceRef) -> str:
        return (str(ref.url) if ref.url
                else re.sub(r"\W+", "", str(ref.support or "").lower())[:100])


def _is_stale(ref: EvidenceRef, claim: ClaimUnit) -> bool:
    """§3.3: дата ПУБЛИКАЦИИ против даты СОБЫТИЯ — старую статью нельзя
    выдавать за свежее подтверждение (таймзоны учитываются только при
    известной точке события; неизвестная точка → честно не проверяем)."""
    published = getattr(ref, "published_at", None)
    event_at = claim.event_at
    if not published or not event_at:
        return False
    return int(published) < int(event_at) - 86400


def _relevance_for(ref: EvidenceRef, claim: ClaimUnit) -> ClaimRelevance:
    """Роль доказательства для КОНКРЕТНОЙ части (словарь: текст части +
    латинские имена/тикеры + метрики)."""
    return claim_relevance(
        str(getattr(ref, "support", "") or ""),
        claim_text=claim.vocabulary(),
        anchor_terms=claim.foreign_terms,
        metrics=claim.metrics,
        entities=claim.entities)


def _strong_binding(ref: EvidenceRef, claim: ClaimUnit) -> bool:
    return _relevance_for(ref, claim).strong


def _gap_note(status_detail: str, *, stale: bool = False) -> str:
    """§3.1/§4: КОНКРЕТНАЯ причина пробела (не «данных недостаточно»)."""
    notes = {
        CLAIM_STATUS_CONFLICTING: ("источники расходятся: есть данные и за "
                                   "тезис, и против него"),
        CLAIM_STATUS_PARTIAL: ("найдено только косвенное подтверждение — "
                               "прямого источника по этому пункту нет"),
        CLAIM_STATUS_EXACT_NUMBER: ("источник по событию есть, но конкретная "
                                    "сумма/число из поста не подтверждены"),
        CLAIM_STATUS_NO_RELEVANT_SOURCES: ("подходящих источников именно по "
                                           "этому пункту не нашлось"),
        CLAIM_STATUS_SOURCE_EXTRACT: ("источник найден, но содержимое открыть "
                                      "или извлечь не удалось — технический "
                                      "исход, а не отсутствие данных"),
        CLAIM_STATUS_PROVIDER_ERROR: ("поиск не ответил (технический сбой) — "
                                      "это не отсутствие данных"),
        CLAIM_STATUS_DEADLINE: ("поиск прерван по лимиту времени — пункт не "
                                "проверен"),
        CLAIM_STATUS_SEARCH_NOT_STARTED: "пункт не проверялся",
        CLAIM_STATUS_CLAIM_UNIDENTIFIED: "проверяемая часть не опознана",
    }
    note = notes.get(str(status_detail or ""), "")
    if stale:
        note = (note + "; " if note else "") + (
            "найденная публикация старше заявленного события")
    return note


def _finalize_claim(run: _ClaimRun) -> ClaimCoverage:
    """Итог части: статус поиска, детализированный исход, роль/ссылки, пробел."""
    claim = run.claim
    roles = [(ref, role, note) for ref, role, note in run.bound.values()]
    supports = [(r, n) for r, role, n in roles if role == EVIDENCE_ROLE_SUPPORTS]
    contradicts = [(r, n) for r, role, n in roles if role
                   == EVIDENCE_ROLE_CONTRADICTS]
    qualifies = [(r, n) for r, role, n in roles if role
                 == EVIDENCE_ROLE_QUALIFIES]
    strong_supports = [r for r, _n in supports if _strong_binding(r, claim)]
    mismatched = any(_relevance_for(r, claim).number_mismatch
                     for r, _n in qualifies)
    stale = run.stale_hit or any("старше" in (n or "")
                                 for _r, _role, n in roles)

    if strong_supports and not contradicts and not mismatched:
        outcome, detail = CLAIM_OUTCOME_CONFIRMED, CLAIM_STATUS_VERIFIED
    elif strong_supports and (contradicts or mismatched):
        outcome, detail = CLAIM_OUTCOME_CONFLICTING, CLAIM_STATUS_CONFLICTING
    elif contradicts and not supports:
        outcome, detail = CLAIM_OUTCOME_REFUTED, CLAIM_STATUS_REFUTED
    elif supports or qualifies:
        has_metric_hit = any(_relevance_for(r, claim).number_hits
                             for r, _n in supports)
        if claim.metrics and not has_metric_hit:
            outcome, detail = (CLAIM_OUTCOME_INSUFFICIENT,
                               CLAIM_STATUS_EXACT_NUMBER)
        else:
            outcome, detail = CLAIM_OUTCOME_PARTIAL, CLAIM_STATUS_PARTIAL
    elif run.deadline_hit:
        outcome, detail = CLAIM_OUTCOME_TECHNICAL, CLAIM_STATUS_DEADLINE
    elif run.provider_failed:
        outcome, detail = CLAIM_OUTCOME_TECHNICAL, CLAIM_STATUS_PROVIDER_ERROR
    elif run.fetch_failed:
        outcome, detail = (CLAIM_OUTCOME_TECHNICAL, CLAIM_STATUS_SOURCE_EXTRACT)
    elif run.attempts == 0:
        outcome, detail = (CLAIM_OUTCOME_INSUFFICIENT,
                           CLAIM_STATUS_SEARCH_NOT_STARTED)
    else:
        outcome, detail = (CLAIM_OUTCOME_INSUFFICIENT,
                           CLAIM_STATUS_NO_RELEVANT_SOURCES)

    if run.opened or any(str(r.source_kind) == "primary" for r in
                         (item[0] for item in roles)):
        search_status = CLAIM_SEARCH_SOURCE_READ
    elif run.bound:
        search_status = CLAIM_SEARCH_SEARCHED
    elif run.deadline_hit:
        search_status = CLAIM_SEARCH_DEADLINE
    elif run.provider_failed:
        search_status = CLAIM_SEARCH_PROVIDER_FAILED
    elif run.fetch_failed:
        search_status = CLAIM_SEARCH_SOURCE_FAILED
    elif run.attempts:
        search_status = CLAIM_SEARCH_SEARCHED
    else:
        search_status = CLAIM_SEARCH_NOT_ATTEMPTED

    detail_for_note = detail
    if outcome == CLAIM_OUTCOME_INSUFFICIENT and stale and detail in (
            CLAIM_STATUS_PARTIAL, CLAIM_STATUS_NO_RELEVANT_SOURCES):
        detail_for_note = CLAIM_STATUS_NO_RELEVANT_SOURCES
    note = "" if outcome in (CLAIM_OUTCOME_CONFIRMED,
                             CLAIM_OUTCOME_REFUTED) else _gap_note(
        detail_for_note, stale=stale)
    evidence_items = tuple(ClaimEvidence(
        claim_id=claim.claim_id, evidence_id=str(getattr(ref, "evidence_id", "")
                                                or ""),
        url=ref.url, role=role, published_at=getattr(ref, "published_at", None),
        event_at=claim.event_at, note=note_item)
        for ref, role, note_item in roles)
    return ClaimCoverage(
        claim=claim, search_status=search_status, status_detail=detail,
        outcome=outcome, reason_code=CLAIM_OUTCOME_REASON.get(detail_for_note),
        gap_note=note, queries_count=run.attempts,
        candidates=run.candidates, opened=run.opened,
        provider_status=tuple(run.providers),
        evidence=evidence_items,
        citation_ids=tuple(str(getattr(ref, "evidence_id", "") or "")
                           for ref, _role, _n in roles
                           if str(getattr(ref, "evidence_id", "") or "")))


async def run_retrieval(plan: RetrievalPlan, *, aggregator,
                        fetch_text=None, max_rows_per_query: int = 4,
                        budget_seconds: float | None = None,
                        refine_calls: int | None = None,
                        ) -> RetrievalOutcome:
    """Единый контур: план → запросы ПО КАЖДОЙ части → структурный evidence +
    строка выдачи для user-content. Дедлайн бюджета/ошибки запросов —
    честная деградация (partial результат, пусто → ok=False). Никогда
    не бросает.

    ASAP-FC-EVIDENCE-STYLE-02 §3: каждая claim-единица получает базовую
    попытку; далее coverage-loop добавляет уточнение ТОЛЬКО для непокрытых
    частей (в пределах настраиваемого числа вызовов и адаптивного бюджета).
    Ссылка попадает в evidence только если подтверждает ЯКОРЬ своей части
    (метрика/сущность/тикер); иначе она снимается как off-topic и в
    «Источники» не выводится. URL ≠ доказательство: содержимое достаётся
    существующим SafeFetcher.
    """
    loop = asyncio.get_running_loop()
    claims = tuple(plan.claims) if plan is not None and plan.claims else ()
    if not claims and plan is not None:
        base_text = str(plan.claim_text or "").strip()
        if not base_text and plan.queries:
            base_text = str(plan.queries[0].text or "")
        if base_text:
            claims = (_pseudo_claim(base_text),)
    budget = float(budget_seconds) if budget_seconds is not None else \
        resolve_retrieval_budget(len(claims) or 1)
    deadline = loop.time() + budget
    outcome_empty = RetrievalOutcome(
        evidence_map=None, search_text="", queries_attempted=0,
        queries_used=0, refs_collected=0, fetch_errors=0,
        budget_exhausted=False, provider_failures=0,
        claims=(), budget_seconds=budget)
    if plan is None or not plan.queries or aggregator is None:
        return outcome_empty

    relevance_search = getattr(aggregator, "search_relevant", None)
    runs: list[_ClaimRun] = [_ClaimRun(claim) for claim in claims]
    runs_by_id = {run.claim.claim_id: run for run in runs}
    blocks: list[str] = []
    counters = {"attempted": 0, "used": 0, "fetch_errors": 0,
                "provider_failures": 0, "empty": 0, "irrelevant": 0,
                "off_topic": 0, "stale": 0, "refine": 0}
    budget_exhausted = False
    total_calls = len(plan.queries) + max(0, _refine_calls_limit()
                                          if refine_calls is None
                                          else int(refine_calls))

    async def _attempt(query: SearchQuery, run: _ClaimRun) -> None:
        nonlocal budget_exhausted
        remaining = deadline - loop.time()
        if remaining <= 0:
            budget_exhausted = True
            run.deadline_hit = True
            return
        counters["attempted"] += 1
        run.attempts += 1
        run.attempted_texts.add(str(query.text).lower())
        query_terms = _claim_terms(query.text, limit=10)
        calls_left = max(1, total_calls - counters["attempted"] + 1)
        per_query_budget = max(1.0, remaining / calls_left)
        trace: dict = {}
        started_at = loop.time()
        try:
            if relevance_search is not None:
                try:
                    chunk = await relevance_search(
                        query.text, query.max_symbols,
                        relevance_terms=query_terms,
                        timeout_budget=per_query_budget, trace=trace)
                except TypeError:
                    try:
                        chunk = await relevance_search(
                            query.text, query.max_symbols,
                            relevance_terms=query_terms,
                            timeout_budget=per_query_budget)
                    except TypeError:
                        chunk = await relevance_search(
                            query.text, query.max_symbols,
                            relevance_terms=query_terms)
            else:
                try:
                    chunk = await aggregator.search(query.text,
                                                    query.max_symbols,
                                                    trace=trace)
                except TypeError:
                    chunk = await aggregator.search(query.text,
                                                    query.max_symbols)
        except Exception as exc:
            cause = str(getattr(exc, "reason", "") or "")
            provider = str(trace.get("provider") or "") or "search"
            if cause == "empty_results":
                counters["empty"] += 1
                run.empty += 1
            elif cause == "irrelevant_results":
                counters["irrelevant"] += 1
                run.irrelevant += 1
            elif cause == "budget":
                run.deadline_hit = True
                counters["provider_failures"] += 1
            else:
                counters["provider_failures"] += 1
                run.provider_failed += 1
            run.providers.append(
                f"{query.intent}:{provider}:{cause or 'provider_error'}")
            logger.info("[factcheck_planner] query failed | claim=%s | "
                        "intent=%s | provider=%s | cause=%s",
                        run.claim.claim_id, query.intent, provider,
                        cause or "provider_error")
            if loop.time() >= deadline:
                budget_exhausted = True
                run.deadline_hit = True
            return
        if not chunk or not str(chunk).strip():
            counters["empty"] += 1
            run.empty += 1
            run.providers.append(f"{query.intent}:empty")
            return
        counters["used"] += 1
        blocks.append(str(chunk))
        if loop.time() >= deadline:
            # §3.2: бюджет ИСЧЕРПАН этим вызовом — честно фиксируем, чтобы
            # оставшиеся части не выдавались за непроверенные «по факту».
            budget_exhausted = True
            run.deadline_hit = True
        refs = evidence_refs_from_search(str(chunk), intent=query.intent,
                                        max_rows=max_rows_per_query)
        run.candidates += len(refs)
        provider = str(trace.get("provider") or "") or "search"
        latency = int((loop.time() - started_at) * 1000)
        run.providers.append(f"{query.intent}:{provider}:ok:{latency}ms")
        for ref in refs:
            if not ref.url:
                # Строка без URL не может быть доказательством (её нельзя
                # открыть и проверить) — остаётся контекстом search_text.
                continue
            key = run.key(ref)
            if key in run.bound:
                continue
            relevance = _relevance_for(ref, run.claim)
            if relevance.role not in DISPLAYABLE_EVIDENCE_ROLES:
                counters["off_topic"] += 1
                continue
            if _is_stale(ref, run.claim):
                counters["stale"] += 1
                counters["off_topic"] += 1
                continue
            note = ""
            if relevance.role == EVIDENCE_ROLE_QUALIFIES and run.claim.metrics:
                note = "число/сумма тезиса в источнике не найдены"
            run.bound[key] = (dataclasses.replace(
                ref, claims=(run.claim.claim_id,),
                event_at=run.claim.event_at), relevance.role, note)

    # Проход 1 (§3.2): базовая попытка ПО КАЖДОЙ существенной части.
    for run in runs:
        queries = plan.queries_for(run.claim.claim_id)
        if not queries:
            # Части не досталось запроса из-за потолка вызовов: это честный
            # лимит (deadline), а не «данных не нашлось».
            run.deadline_hit = True
            budget_exhausted = True
            continue
        for query in queries:
            if query.purpose == QUERY_PURPOSE_REFINE:
                continue
            await _attempt(query, run)
    # Проход 2 (§3.2): уточнения — только непокрытым частям и только пока
    # есть полезная вероятность (бюджет вызовов/времени). Сначала берём
    # уточнение, уже заложенное в план для этой части, иначе строим его от
    # её метрики/интервала (одна лишняя «догадка» не нужна).
    refine_left = max(0, _refine_calls_limit() if refine_calls is None
                      else int(refine_calls))
    for run in runs:
        if refine_left <= 0 or loop.time() >= deadline:
            break
        if run.bound:
            continue
        if run.attempts == 0 and not run.provider_failed:
            continue
        planned = [q for q in plan.queries_for(run.claim.claim_id)
                   if q.purpose == QUERY_PURPOSE_REFINE]
        query = planned[0] if planned else refinement_query_for(run.claim)
        if query is None:
            continue
        if query.text.lower() in run.attempted_texts:
            # §3.2: не повторять уже сделанный запрос — это не уточнение.
            continue
        refine_left -= 1
        counters["refine"] += 1
        await _attempt(query, run)

    # §3.3: URL ≠ доказательство — содержимое достаётся только для строк,
    # привязанных к своей части; превышение бюджета больше не маскируется.
    if plan.needs_primary_fetch and loop.time() < deadline:
        seen_urls: set[str] = set()
        fetched_total = 0
        for run in runs:
            if fetched_total >= _MAX_PRIMARY_FETCHES or loop.time() >= deadline:
                break
            candidates = sorted(
                ((ref, role) for ref, role, _n in run.bound.values()
                 if role in (EVIDENCE_ROLE_SUPPORTS, EVIDENCE_ROLE_QUALIFIES)),
                key=lambda pair: 0 if pair[1] == EVIDENCE_ROLE_SUPPORTS else 1)
            for ref, _role in candidates:
                if fetched_total >= _MAX_PRIMARY_FETCHES:
                    break
                if not ref.url or ref.url in seen_urls:
                    continue
                seen_urls.add(ref.url)
                primary = await fetch_primary_evidence(
                    ref.url, fetch_text=fetch_text)
                if primary is None:
                    counters["fetch_errors"] += 1
                    run.fetch_failed += 1
                    continue
                relevance = _relevance_for(primary, run.claim)
                key = run.key(primary)
                if _is_stale(primary, run.claim):
                    # Открытый первоисточник ДОКАЗАЛ, что материал старее
                    # события: снять и уже связанную выдержку того же URL —
                    # старое нельзя выдавать за свежее подтверждение.
                    counters["stale"] += 1
                    run.stale_hit = True
                    if run.bound.pop(key, None) is not None:
                        counters["off_topic"] += 1
                    continue
                if relevance.role not in DISPLAYABLE_EVIDENCE_ROLES:
                    counters["off_topic"] += 1
                    continue
                fetched_total += 1
                run.opened += 1
                key = run.key(primary)
                previous = run.bound.get(key)
                kind = str(primary.source_kind or "primary")
                if previous is not None:
                    # Открытая страница даёт полную выдержку и дату, но не
                    # превращает энциклопедию/исследование в «первоисточник»:
                    # уточнённая классификация URL сохраняется.
                    prev_kind = str(previous[0].source_kind or "")
                    if prev_kind and prev_kind != "secondary":
                        kind = prev_kind
                primary = dataclasses.replace(primary, source_kind=kind)
                run.bound[key] = (dataclasses.replace(
                    primary, claims=(run.claim.claim_id,),
                    event_at=run.claim.event_at), relevance.role, "")

    # Сборка EvidenceMap: только привязанные к claim ссылки; ev-N назначаются
    # после сортировки (сильные подтверждения и покрытие нескольких частей
    # первыми), поэтому порядок ссылок детерминирован.
    grouped: dict[str, EvidenceRef] = {}
    for run in runs:
        for ref, _role, _note in run.bound.values():
            key = str(ref.url) if ref.url else \
                re.sub(r"\W+", "", str(ref.support or "").lower())[:100]
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = dataclasses.replace(
                    ref, claims=(run.claim.claim_id,))
            else:
                grouped[key] = dataclasses.replace(
                    existing,
                    claims=tuple(sorted(set(existing.claims)
                                        | {run.claim.claim_id})))
    ordered = sorted(
        grouped.values(),
        key=lambda r: (-_strong_binding_count(r, runs), -len(r.claims),
                       str(r.url or "")))
    evidence_map = _assemble(list(ordered))
    # ID назначаются в _assemble → переносим их в покрытие частей.
    ids_by_url = {}
    if evidence_map is not None:
        for ref in evidence_map.refs:
            ids_by_url[ref.url or re.sub(
                r"\W+", "", str(ref.support or "").lower())[:100]] = \
                ref.evidence_id
    coverage: list[ClaimCoverage] = []
    for run in runs:
        remapped = []
        for ref, role, note in run.bound.values():
            key = ref.url or re.sub(r"\W+", "", str(ref.support or "").lower())[:100]
            remapped.append((dataclasses.replace(
                ref, evidence_id=ids_by_url.get(key, "")), role, note))
        run.bound = {f"{i}": item for i, item in enumerate(remapped)}
        coverage.append(_finalize_claim(run))

    search_text = "\n\n".join(blocks)[:_SEARCH_TEXT_BUDGET_CHARS]
    return RetrievalOutcome(
        evidence_map=evidence_map, search_text=search_text,
        queries_attempted=counters["attempted"], queries_used=counters["used"],
        refs_collected=len(evidence_map.refs) if evidence_map else 0,
        fetch_errors=counters["fetch_errors"],
        budget_exhausted=budget_exhausted,
        provider_failures=counters["provider_failures"],
        empty_results=counters["empty"],
        irrelevant_results=counters["irrelevant"],
        claims=tuple(coverage),
        off_topic_sources_dropped=counters["off_topic"],
        stale_sources_dropped=counters["stale"],
        refine_calls=counters["refine"],
        budget_seconds=budget)


def _strong_binding_count(ref: EvidenceRef, runs: list[_ClaimRun]) -> int:
    """Сколько частей эта ссылка подтверждает сильно (порядок выдачи)."""
    count = 0
    for run in runs:
        if run.claim.claim_id not in (ref.claims or ()):
            continue
        if _strong_binding(ref, run.claim):
            count += 1
    return count


