"""CFG-06 W4 — планировщик проверки + структурный evidence (06C, бриф §W4).

Закрывает W0-находку 06A.4: поисковая формулировка была «дословный слайс
клейма + годы» (`temporal_factcheck.search_queries_for`). Здесь — осмысленные
запросы из claim_items (SuitabilityDecision, W2): сущности/числа/цитаты/годы,
2–4 запроса с различающей целью, структурный evidence (тезис → выдержка →
URL → тип) в
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

#: Стартовое число запросов для КОРОТКОГО клейма (одна-две части). Это НЕ
#: общий потолок исследования: составной клейм получает по запросу на часть,
#: а общий/уточняющий бюджеты задаются `FactcheckLimits` (S14).
_MAX_QUERIES = 3
#: S14 FACTCHECK-REQUEST-INTEGRITY §5.2: заводской общий бюджет поисковых
#: запросов (базовые + уточняющие ВМЕСТЕ), применяется только при
#: effective budgets ON.
_MAX_QUERIES_TOTAL_DEFAULT = 64
_QUERY_MAX_CHARS = 200            # технический предел формулировки запроса
_MAX_PRIMARY_FETCHES = 2          # политика нагрузки при budgets ON
_EXCERPT_MAX_CHARS = 600          # размер выдержки открытой страницы


_NUMERIC_PHRASE_RE = re.compile(
    # §F1: длинные единицы ИДУТ ПЕРЕД короткими (млрд/млн/тыс раньше «м»,
    # иначе «658 млрд» распознавалось как «658 м»), плюс валютный префикс.
    r"(?:[$€£₽]\s*)?\d+(?:[.,]\d+)?\s*(?:"
    r"млрд|млн|трлн|тыс\.?|"
    r"градус\w*|процент\w*|человек|чел|"
    r"руб\w*|доллар\w*|долл\.?|юан\w*|фунт\w*|евро|"
    r"мм|см|дм|км|кг|тонн|"
    r"%|п\.п\.?|"
    r"м|г"
    r")?", re.IGNORECASE)
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
    """§3.1: доказательство с РОЛЬЮ для конкретного claim.

    FC-03.2 (corrective 05.11.2026): кандидат хранит provenance-набор —
    claim_id, url, нормализованный title, extracted passage (``note``/роль
    в ClaimCoverage), дата/тип источника, relation (роль) и strength
    (direct/indirect), плюс факт открытия страницы. Нечитаемая страница не
    помечается прочитанной (``opened=False``), одна ссылка не доказывает
    все части (claim_id входящей части)."""
    claim_id: str
    evidence_id: str
    url: str | None = None
    role: str = EVIDENCE_ROLE_QUALIFIES
    published_at: int | None = None
    event_at: int | None = None
    note: str = ""
    #: FC-03.2: direct — источник прямо подтверждает/опровергает тезис;
    #: indirect — уточняет/косвенный (форум, корреляция без причинной связки)
    strength: str = ""
    #: нормализованный заголовок кандидата (первое предложение выдержки)
    title: str = ""
    #: страница кандидата была открыта и прочитана в этом прогоне
    opened: bool = False

    def as_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
            "url": self.url,
            "role": self.role,
            "published_at": self.published_at,
            "event_at": self.event_at,
            "note": self.note,
            "strength": self.strength,
            "title": self.title,
            "opened": self.opened,
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
    claim_text: str = ""
    plan_version: str = PLANNER_VERSION
    #: §3.1: проверяемые единицы составной новости (каждая получает попытку)
    claims: tuple[ClaimUnit, ...] = ()
    #: §3.1: ссылка на исходное сообщение/цитату (трассировка claim → пост)
    source_link: str = ""
    #: EVOL §1.5 (M6): claim_id → сообщение/автор, которому принадлежит
    #: проверяемая часть. Часть без установленной принадлежности остаётся с
    #: пустым анкором (приписывать «наверное этому» запрещено).
    claim_anchors: tuple[dict, ...] = ()
    #: S13 FACTCHECK-REQUEST-INTEGRITY: структурное происхождение предмета
    #: (material | request | mixed) и его кэш-идентичность. План строится
    #: ТОЛЬКО от уже установленного предмета; исходное сообщение повторно
    #: приоритетным текстом не выбирается.
    subject_origin: str = ""
    subject_fingerprint: str = ""
    #: S14: чат прогона — для per-chat effective-настроек бюджетов фактчека
    #: (chat override → global → default). Берётся из уже разрешённой цели,
    #: второго резолва чата планировщик не делает.
    chat_id: int | None = None

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
    Токены в lowercase (поисковый запрос), без стоп-слов, дедуп.

    FC-SHORT-TOKENS: единый токенизатор с search_aggregator.content_terms
    (порог 2 симв., обозначения RTX/4060 и отрицание «не» выживают),
    поверх — стоп-слова factcheck_context._STOPWORDS."""
    from services.factcheck_context import _STOPWORDS
    from services.search_aggregator import content_terms
    return content_terms(text, limit=limit, stopwords=_STOPWORDS)


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


#: FC-01.1/FC-02.2 (corrective 05.11.2026): собственные служебные обёртки
#: материала изображений (метки способа распознавания/инструментов) — не
#: тезис и не поисковые термы. Убираются ТОЛЬКО на поисковом пути; тексты
#: внутри обёрток остаются тезисом (для картинки это и есть утверждение).
#: Inline-совпадение: предложение-разбиение может отрезать метку от
#: закрывающей скобки, поэтому сбрасываются и строки-остатки меток.
_SEARCH_SERVICE_LABEL_RE = re.compile(
    r"Текст с изображения(?:\s+\d+)?[ \t]*"
    r"\(OCR, не слова автора\)[ \t]*:?"
    r"|Визуальное описание изображения(?:\s+\d+)?[ \t]*"
    r"\(результат модели;[^)]*\)[ \t]*:?")

_SEARCH_LABEL_PREFIXES = ("Текст с изображения",
                          "Визуальное описание изображения")


def search_thesis_text(text: str) -> str:
    """Тезис для ПОИСКОВОГО пути: без служебных обёрток OCR/vision-меток
    (FC-01.1: служебные данные хранятся отдельно от формулировки тезиса и
    никогда не считаются доказательством; FC-02.2: произвольный OCR-блок с
    техметками в публичный поисковик не уходит — запросы строятся от
    смысловых формулировок). Детерминированно, без LLM."""
    cleaned = _SEARCH_SERVICE_LABEL_RE.sub("", str(text or ""))
    lines = []
    for line in cleaned.splitlines():
        if line.strip().startswith(_SEARCH_LABEL_PREFIXES):
            continue          # строка-остаток метки (после разбиения на части)
        lines.append(line)
    return re.sub(r"\n{2,}", "\n", "\n".join(lines)).strip()


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


def build_retrieval_plan(decision, *,
                         claim_text: str | None = None,
                         max_queries: int | None = None,
                         subject_origin: str = "",
                         subject_fingerprint: str = "",
                         subject_anchor_tg_message_id: int | None = None,
                         subject_author: str = "",
                         subject_request_text: str = "",
                         subject_material_text: str = "",
                         ) -> RetrievalPlan | None:
    """SuitabilityDecision/ClaimItem → план поисковых действий.

    Gate/планировщик OFF (default) или проверять нечего → None — вызывающий
    не выполняет НИКАКИХ платных запросов (OFF-паритет). ``max_queries=None``
    → адаптивный бюджет по числу частей (§3.2); явное число — потолок
    вызывающего. Никогда не бросает.

    S13 FACTCHECK-REQUEST-INTEGRITY: ``claim_text`` — УЖЕ установленный
    предмет проверки (CheckSubject), а не исходная публикация. Планировщик не
    выбирает исходное сообщение повторно: без предмета план не строится.
    ``subject_origin``/``subject_fingerprint`` — структурный провенанс и
    кэш-идентичность; ``subject_anchor_tg_message_id``/``subject_author`` —
    анкор частей, происходящих из запроса пользователя (не из материала).

    BGS-01: контекст чата (участники) планировщику больше НЕ передаётся —
    у него нет доступа к именам, поэтому обязательная деперсонализация
    запроса не может быть возвращена «по привычке»."""
    if not planner_enabled():
        return None
    try:
        return _build_plan_inner(decision, claim_text=claim_text,
                                 max_queries=max_queries,
                                 subject_origin=subject_origin,
                                 subject_fingerprint=subject_fingerprint,
                                 subject_anchor_tg_message_id=(
                                     subject_anchor_tg_message_id),
                                 subject_author=subject_author,
                                 subject_request_text=subject_request_text,
                                 subject_material_text=subject_material_text)
    except Exception:
        logger.warning("[factcheck_planner] plan build failed", exc_info=True)
        return None


def _claim_units(items, claim: str, *, cap: int | None = None) -> list[str]:
    """FC-SEMQUERY: самостоятельные проверяемые части для запросов —
    верифицируемые тексты claim_items; единый тезис-«всё сообщение»
    разбивается на предложения (как decompose_claim). Детерминированно.

    BGS-01: часть принимается только если она — фрагмент ПРОВЕРЯЕМОГО
    ПРЕДМЕТА (``claim``). S13 FACTCHECK-REQUEST-INTEGRITY: ``claim`` — это
    установленный предмет (может быть вопросом пользователя или условием,
    которых нет в исходной публикации); проверка принадлежности НЕ отключена,
    но привязана к предмету, а не к исходному тексту. Части материала, не
    вошедшие в предмет, не ищутся (не расширяют проверку); непокрытый остаток
    предмета (условие/вопрос пользователя) добавляется предложениями.

    FC-01.1/FC-02.2 (corrective 05.11.2026): служебные обёртки материала
    изображений (наши метки OCR/vision) вынесены из ПОИСКОВОГО пути ДО
    разбиения на предложения — тезис для запросов строится из содержательных
    формулировок, служебные метки не уходят в публичный поисковик. Сам клейм
    для аналитика остаётся с метками."""
    claim_thesis = search_thesis_text(claim).strip()
    claim_low = claim_thesis.lower()
    units: list[str] = []
    for item in items or ():
        text = search_thesis_text(
            str(getattr(item, "text", "") or "")).strip()
        if not text:
            continue
        if claim_thesis and text.lower() not in claim_low:
            continue
        if getattr(item, "verifiable", True) is not False \
                and text.lower() not in {u.lower() for u in units}:
            units.append(text)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?;])\s+", claim_thesis)
                 if s.strip()] or [claim_thesis]
    if not units or (len(units) == 1 and units[0].lower() == claim_low):
        # гейт не декомпозировал → предложения тезиса без служебных меток
        units = sentences
    else:
        # S13 §4.1: предмет может содержать условие/вопрос пользователя,
        # которых нет в claim_items. Они — часть УЖЕ установленного предмета и
        # не должны исчезать из плана только потому, что item-фильтр принял
        # лишь material-часть. Остаток предмета добавляется структурно
        # (предложения), без лексических правил и новых категорий.
        covered = [u.lower() for u in units]
        for sentence in sentences:
            low = sentence.lower()
            if low == claim_low:
                continue
            if any(low in c or c in low for c in covered):
                continue
            units.append(sentence)
            covered.append(low)
    result = [search_thesis_text(u) for u in units if u]
    # S14 §6.6: ``cap`` — размер ПОРЦИИ обработки (32), а не максимум
    # проверяемых утверждений на весь запрос. Без явного ``cap`` хвост
    # сохраняется; порционность обеспечивает ``build_claim_units``.
    return result[:cap] if cap is not None else result


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

#: S14 §5.2/§6.6: размер ПОРЦИИ декомпозиции (было жёсткое 16). Части сверх
#: порции не исчезают: материал обрабатывается последовательными порциями
#: (``build_claim_units``), поэтому 32 — не максимум на весь запрос.
_CLAIM_UNITS_PORTION = 32

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
    r"(млрд|млр|млн|мл|тыс\.?|трлн|%|процент\w*|п\.п\.?|пункт\w*|"
    r"руб\w*|доллар\w*|долл\.?|юан\w*|фунт\w*|евро|\$|€|£|₽|"
    r"billion|trillion|million|thousand|percent|pct|points?|usd|eur|gbp|"
    r"rub|bn|mn)", re.IGNORECASE)


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


def build_claim_units(items, claim: str, *,
                      source_link: str = "") -> tuple[ClaimUnit, ...]:
    """§3.1: исходная новость → проверяемые claim-единицы (без LLM).

    Переиспользует существующую декомпозицию (`_claim_units`, те же
    claim_items/предложения), добавляя контракт: сущности, метрики/единицы,
    временной интервал/часовой пояс, тип утверждения и связь с сообщением.

    BGS-01 (§0.1): текст части — это ЕЁ СОБСТВЕННЫЙ текст. Имена участников
    не вычищаются: упоминание человека в реплике не запрещает проверку, а
    удаление имени из тезиса ломало смысл запроса.

    Reviewer (nonblocking): части сверх бюджета запросов больше не исчезают
    молча — они остаются в плане, получают ``deadline_exceeded`` в покрытии
    и честно называются как непроверенные.

    S14 §6.6: 32 — размер ПОРЦИИ. Материал с большим числом существенных
    частей обрабатывается последовательными порциями по 32, хвост исходного
    текста не удаляется; ``claim_id`` сквозной по всему материалу.
    """
    claim_years = _years(claim)
    units: list[ClaimUnit] = []
    raw_units = _claim_units(items, claim)
    for start in range(0, len(raw_units), _CLAIM_UNITS_PORTION):
        for raw_unit in raw_units[start:start + _CLAIM_UNITS_PORTION]:
            unit = str(raw_unit or "").strip()
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
    return tuple(units)


def _claim_anchor_map(items, units, *, subject_origin: str = "",
                      subject_anchor_tg_message_id: int | None = None,
                      subject_author: str = "",
                      subject_request_text: str = "",
                      subject_material_text: str = "") -> tuple[dict, ...]:
    """M6: claim_id → анкор/автор исходного фрагмента (без догадок).

    Часть плана сопоставляется с claim-item по совпадению текста (пункт может
    быть целым предложением части). Нет однозначного совпадения → анкор
    пустой: приписывать часть «ближайшему» сообщению запрещено §4.3.

    S13: часть самостоятельного вопроса пользователя (``subject_origin ==
    "request"``) без item-совпадения принадлежит СООБЩЕНИЮ ЗАПРОСА, а не
    материалу: пользовательский вопрос не становится цитатой исходного автора.
    Для mixed-предмета так же структурно определяется часть, дословно взятая
    из request_part. Для material/mixed без такого совпадения анкор не
    угадывается."""
    rows: list[dict] = []
    request_low = str(subject_request_text or "").strip().lower()
    material_low = str(subject_material_text or "").strip().lower()
    by_text = {}
    for item in items or ():
        text = str(getattr(item, "text", "") or "").strip().lower()
        if text:
            by_text[text] = item
    for unit in units or ():
        unit_text = str(getattr(unit, "text", "") or "").strip().lower()
        item = by_text.get(unit_text)
        if item is None:
            for text, candidate in by_text.items():
                if unit_text and (unit_text in text or text in unit_text):
                    item = candidate
                    break
        row = {
            "claim_id": str(getattr(unit, "claim_id", "") or ""),
            "anchor_tg_message_id": (getattr(item, "anchor_tg_message_id", None)
                                     if item is not None else None),
            "author": (str(getattr(item, "author", "") or "")
                       if item is not None else ""),
            "source": (str(getattr(item, "source", "") or "")
                       if item is not None else ""),
        }
        if item is not None and row["source"] == "user_request":
            row["origin"] = "user_request"
        elif item is None and subject_anchor_tg_message_id not in (None, "", 0):
            unit_low = str(getattr(unit, "text", "") or "").strip().lower()
            in_material = bool(
                material_low and unit_low
                and (unit_low in material_low or material_low in unit_low))
            from_request = bool(
                request_low and unit_low
                and (unit_low in request_low or request_low in unit_low))
            if (subject_origin == "request" and not in_material) or \
                    (from_request and not in_material):
                row["anchor_tg_message_id"] = int(subject_anchor_tg_message_id)
                row["author"] = str(subject_author or "")
                row["source"] = "user_request"
                row["origin"] = "user_request"
            else:
                row["origin"] = ""
        else:
            row["origin"] = "material" if row["anchor_tg_message_id"] else ""
        rows.append(row)
    return tuple(rows)


#: S14: прежние `adaptive_query_budget`/`_max_queries_total` удалены как
#: второй, скрытый источник потолка запросов. Единственный источник —
#: `FactcheckLimits` (plan строит запросы по числу частей; исполнение
#: применяет общий бюджет ON и не применяет его при OFF).


#: Варианты единиц измерения для уточняющего запроса (§3.2: «варианты
#: термина»). Это общеязыковые единицы, а не предметный словарь.
_UNIT_VARIANTS = {
    "млрд": "billion", "млр": "billion", "млн": "million", "мл": "million",
    "тыс": "thousand", "трлн": "trillion",
    "$": "dollars", "usd": "dollars", "€": "euros", "eur": "euros",
    "%": "percent",
}


def refinement_query_for(claim: ClaimUnit) -> SearchQuery | None:
    """§3.2: уточняющий запрос ТОЛЬКО для непокрытой части.

    Сохраняет метрику с единицей и временной интервал (или латинское имя/
    тикер для международной новости) — то, чего не хватило базовой попытке.
    Reviewer F5: для спорного ЧИСЛА добавляется вариант единицы
    (млрд→billion, $→dollars, %→percent), поэтому уточнение не повторяет
    базовую формулировку и реально может найти первоисточник с суммой.
    """
    try:
        if claim.foreign_terms:
            terms = list(claim.foreign_terms[:4])
        else:
            terms = _expand_terms(
                (list(claim.entities[:2])
                 + _claim_terms(claim.text, limit=6))[:8])
        tail_bits: list[str] = []
        if claim.metrics:
            numbers = [re.sub(r"[^\d.,]", "", str(m)) for m in claim.metrics]
            tail_bits.extend(n for n in numbers if n)
            for unit in claim.units:
                variant = _UNIT_VARIANTS.get(str(unit).lower())
                if variant:
                    tail_bits.append(variant)
        if claim.timeframe:
            tail_bits.append(claim.timeframe)
        tail = " ".join(dict.fromkeys(tail_bits)).strip()
        intent = INTENT_NUMERIC if claim.metrics else INTENT_ENTITY_CHECK
        return _make_query(terms, intent, tail=tail,
                           claim_id=claim.claim_id,
                           purpose=QUERY_PURPOSE_REFINE)
    except Exception:      # pragma: no cover — уточнение не рвёт контур
        return None


def _build_plan_inner(decision, *, claim_text, max_queries,
                      subject_origin: str = "",
                      subject_fingerprint: str = "",
                      subject_anchor_tg_message_id: int | None = None,
                      subject_author: str = "",
                      subject_request_text: str = "",
                      subject_material_text: str = "") -> RetrievalPlan | None:
    if decision is None:
        return None
    scope = str(getattr(decision, "scope", "") or "")
    needs_web = scope in ("web", "web_and_chat")
    needs_chat = scope in ("chat_history", "web_and_chat")
    items = list(getattr(decision, "claim_items", ()) or ())
    claim = (str(claim_text) if claim_text else "").strip()
    if not claim and subject_origin:
        # S13: предмет уже установлен — planner НЕ выбирает исходное
        # сообщение повторно в качестве более приоритетного текста.
        return None
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

    terms = _claim_terms(claim)
    entities = [e for e in _entities(claim)
                if e.lower() not in {t.lower() for t in terms}][:3]

    queries: list[SearchQuery] = []
    seen: set[str] = set()

    # §3.1/§3.2 (ASAP-FC-EVIDENCE-STYLE-02): единица проверки — claim unit.
    # Каждая существенная часть получает СВОЙ запрос (проход 1), уточнения
    # (числа/интервал) идут на остаток бюджета (проход 2). Бюджет зависит от
    # числа частей (§3.2), а не «≤3 на всю новость».
    units = build_claim_units(items, claim)
    if not units:
        units = (ClaimUnit(claim_id="c1",
                           text=search_thesis_text(claim)),)
    explicit_cap = max_queries is not None and int(max_queries) > 0
    # S14 §5.2/§6.3: план строится по числу существенных частей; 64 — это
    # бюджет ИСПОЛНЕНИЯ (run_retrieval), а не причина терять части плана.
    # Поэтому верхняя граница плана не фиксируется старым 12/64: каждая
    # часть получает запрос, а при effective budgets ON исполнение честно
    # остановится на общем бюджете и отметит непроверенное.
    max_queries_value = (int(max_queries) if explicit_cap
                         else max(len(units), _MAX_QUERIES))

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
    chat_id = None
    if isinstance(target_ref, dict):
        if target_ref.get("target_tg_message_id"):
            source_link = f"tg:{target_ref.get('target_tg_message_id')}"
        raw_chat_id = target_ref.get("chat_id")
        try:
            chat_id = int(raw_chat_id) if raw_chat_id is not None else None
        except (TypeError, ValueError):
            chat_id = None
    return RetrievalPlan(
        queries=tuple(queries), needs_web=True,
        needs_chat_history=needs_chat,
        needs_primary_fetch=True,
        claim_text=claim, claims=tuple(units), source_link=source_link,
        claim_anchors=_claim_anchor_map(
            items, units, subject_origin=subject_origin,
            subject_anchor_tg_message_id=subject_anchor_tg_message_id,
            subject_author=subject_author,
            subject_request_text=subject_request_text,
            subject_material_text=subject_material_text),
        subject_origin=subject_origin,
        subject_fingerprint=subject_fingerprint,
        chat_id=chat_id)



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


def _excerpt_from_html(html_text: str, *, limit: int | None = _EXCERPT_MAX_CHARS
                       ) -> str:
    """Первый содержательный абзац страницы (теги срезаны); предел порции.

    ``limit=None`` — бюджеты OFF: выдержка не обрезается искусственно.
    """
    text = _TAG_RE.sub(" ", str(html_text or ""))
    text = re.sub(r"\s{2,}", " ", text)
    for chunk in re.split(r"(?<=[.!?])\s+", text.strip()):
        chunk = chunk.strip()
        if len(chunk) >= 80:
            return chunk if limit is None else chunk[:limit].rstrip()
    if not text.strip():
        return ""
    return text.strip() if limit is None else text.strip()[:limit]


async def fetch_primary_evidence(url: str, *, fetch_text=None,
                                 max_bytes: int = 65536,
                                 timeout: float = 4.0,
                                 excerpt_chars: int | None = _EXCERPT_MAX_CHARS
                                 ) -> EvidenceRef | None:
    """Открыть страницу-кандидат через СУЩЕСТВУЮЩИЙ SafeFetcher (REUSE;
    инъекция `fetch_text` — прецедент enrich_evidence_dates). Fail-open →
    None.

    FC-03.3 (corrective 05.11.2026): успешный fetch больше НЕ повышает
    ``source_kind`` до primary. Тип источника — по происхождению
    (``classify_source_kind``: gov/edu/research/reference/secondary), поэтому
    форум, соцпост или SEO-пересказ после открытия страницы остаются
    secondary и «первоисточником» не становятся."""
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
    excerpt = _excerpt_from_html(
        html_text,
        limit=excerpt_chars if excerpt_chars is not None else None)
    if not excerpt or len(excerpt) < 40:
        return None
    published_at, _source = tf.parse_publication_date(html_text, url)
    return EvidenceRef(evidence_id="", url=str(url), support=excerpt,
                       source_kind=classify_source_kind(str(url)),
                       published_at=published_at)


def _assemble(refs: list[EvidenceRef]) -> EvidenceMap | None:
    """Проставить стабильные ID ev-N текущего прогона + allowlist.

    S14: прежний жёсткий потолок 12 ссылок снят — он молча отбрасывал уже
    полученные полезные доказательства и не входил ни в один бюджетный
    параметр. Дедупликация/allowlist сохранены; ограничение доставки —
    задача порций evidence (S15), а не скрытая потеря здесь.
    """
    assembled: list[EvidenceRef] = []
    for ref in refs:
        assembled.append(dataclasses.replace(
            ref, evidence_id=f"ev-{len(assembled) + 1}"))
    if not assembled:
        return None
    return EvidenceMap(refs=tuple(assembled),
                       allowlist=tuple(r.evidence_id for r in assembled))


async def execute_retrieval(plan: RetrievalPlan, *, aggregator,
                            fetch_text=None,
                            max_rows_per_query: int | None = None,
                            limits: "FactcheckLimits | None" = None
                            ) -> EvidenceMap | None:
    """Выполнить план: bounded запросы через существующий агрегатор +
    первоисточники через SafeFetcher → EvidenceMap текущего прогона.

    S14: размер страницы/политика открытий берутся из `FactcheckLimits`
    (заводской 20 при ON; OFF — без продуктовых caps). Ошибки запросов/
    фетчей не прерывают сбор (честная деградация); пусто → None.
    Никогда не бросает."""
    outcome = await run_retrieval(plan, aggregator=aggregator,
                                  fetch_text=fetch_text,
                                  max_rows_per_query=max_rows_per_query,
                                  limits=limits)
    return outcome.evidence_map


# ── S14: единый ресурсный контракт фактчека ─────────────────────────────────
# Заводские значения (owner §5.2, 14.11.2026). При effective budgets OFF ни
# одно из бюджетных значений не ограничивает исследование; при ON они —
# политика, а не обязательный минимум.
FACTCHECK_BUDGET_SECONDS = 120.0
FACTCHECK_BUDGET_SECONDS_MAX = 600.0
FACTCHECK_REFINE_CALLS = 24
FACTCHECK_QUERIES_TOTAL = 64
FACTCHECK_SEARCH_TEXT_CHARS = 100_000
FACTCHECK_PAGE_SIZE = 20
FACTCHECK_CLAIM_PORTION = 32
FACTCHECK_PRIMARY_FETCHES = 2
FACTCHECK_EXCERPT_CHARS = 600

#: Суммарный размер порции текстовой выдачи, уходящей в user-content ветки.
#: S14: 100 000 — размер ПОРЦИИ; остаток не уничтожается
#: (`RetrievalOutcome.search_text_portions`).
_SEARCH_TEXT_BUDGET_CHARS = FACTCHECK_SEARCH_TEXT_CHARS
#: Базовый бюджет retrieval-контура (owner §5.2): стартовый планировочный
#: бюджет, а не обязательная длительность. Имена сохранены для совместимости
#: существующих тестов/вызывающих.
_BUDGET_SECONDS_DEFAULT = FACTCHECK_BUDGET_SECONDS
_BUDGET_SECONDS_PER_EXTRA_CLAIM = 0.5
_BUDGET_SECONDS_MAX = FACTCHECK_BUDGET_SECONDS_MAX
#: §3.2/§6.4: сколько уточняющих запросов допускается на прогон при ON.
_REFINE_CALLS_DEFAULT = FACTCHECK_REFINE_CALLS

#: PG/hot-ключи ресурсного контракта (chat → global → default). Значения —
#: числа; каталог их не объявляет (аудит S14), поэтому резолвер сам приводит
#: типы и НЕ создаёт новую admin-панель.
_LIMIT_BASE = "limits.factcheck_retrieval_seconds"
_LIMIT_BASE_MAX = "limits.factcheck_retrieval_seconds_max"
_LIMIT_REFINE = "limits.factcheck_refine_calls"
_LIMIT_TOTAL_QUERIES = "limits.factcheck_max_queries_total"
_LIMIT_SEARCH_CHARS = "limits.factcheck_search_text_chars"
_LIMIT_PAGE_SIZE = "limits.factcheck_page_size"
_LIMIT_CLAIM_PORTION = "limits.factcheck_claim_portion"
_LIMIT_PRIMARY_FETCHES = "limits.factcheck_primary_fetches"
_LIMIT_EXCERPT_CHARS = "limits.factcheck_excerpt_chars"
#: PG-ключ master-рубильника (резолв принадлежит S1 `budget_gate`).
_BUDGETS_KEY = "flags.budgets_enabled"


@dataclasses.dataclass(frozen=True)
class FactcheckLimits:
    """Эффективные ресурсы фактчека + происхождение каждого значения.

    ``budgets_enabled=False`` (master `flags.budgets_enabled` OFF): бюджетные
    поля ``None`` — никакого продуктового deadline/cap не применяется.
    Размеры порций (``page_size``/``claim_portion``) — структурные, не бюджет.
    ``sources`` — пары (ключ, chat|global|default): сохранённое значение не
    перезаписывается, а материализованный default не выдаётся за выбор
    пользователя (SFC-5-09).
    """

    budgets_enabled: bool = True
    budget_source: str = "default"
    budget_known: bool = True
    base_seconds: float | None = FACTCHECK_BUDGET_SECONDS
    max_seconds: float | None = FACTCHECK_BUDGET_SECONDS_MAX
    refine_calls: int | None = FACTCHECK_REFINE_CALLS
    total_queries: int | None = FACTCHECK_QUERIES_TOTAL
    search_text_chars: int | None = FACTCHECK_SEARCH_TEXT_CHARS
    page_size: int = FACTCHECK_PAGE_SIZE
    claim_portion: int = FACTCHECK_CLAIM_PORTION
    primary_fetches: int | None = FACTCHECK_PRIMARY_FETCHES
    excerpt_chars: int | None = FACTCHECK_EXCERPT_CHARS
    sources: tuple[tuple[str, str], ...] = ()

    def as_meta(self) -> dict:
        """R17-safe снимок (без текстов/секретов)."""
        return {
            "budgets_enabled": bool(self.budgets_enabled),
            "budget_source": str(self.budget_source),
            "budget_known": bool(self.budget_known),
            "base_seconds": self.base_seconds,
            "max_seconds": self.max_seconds,
            "refine_calls": self.refine_calls,
            "total_queries": self.total_queries,
            "search_text_chars": self.search_text_chars,
            "page_size": self.page_size,
            "claim_portion": self.claim_portion,
            "primary_fetches": self.primary_fetches,
            "excerpt_chars": self.excerpt_chars,
            "sources": dict(self.sources),
        }


def _as_int(value, default: int) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _limits_from_values(*, enabled: bool, budget_source: str,
                        budget_known: bool, values: dict,
                        sources: dict) -> FactcheckLimits:
    """Собрать контракт: OFF снимает бюджеты, ON применяет значения."""
    page_size = max(1, _as_int(values["page"], FACTCHECK_PAGE_SIZE))
    portion = max(1, _as_int(values["portion"], _CLAIM_UNITS_PORTION))
    if not enabled:
        return FactcheckLimits(
            budgets_enabled=False, budget_source=budget_source,
            budget_known=budget_known,
            base_seconds=None, max_seconds=None, refine_calls=None,
            total_queries=None, search_text_chars=None,
            page_size=page_size, claim_portion=portion,
            primary_fetches=None, excerpt_chars=None,
            sources=tuple(sorted(sources.items())))
    base = max(0.0, _as_float(values["base"], _BUDGET_SECONDS_DEFAULT))
    cap = max(base, _as_float(values["max"], _BUDGET_SECONDS_MAX))
    refine = max(0, _as_int(values["refine"], _REFINE_CALLS_DEFAULT))
    total = max(1, _as_int(values["total"], _MAX_QUERIES_TOTAL_DEFAULT))
    chars = max(1, _as_int(values["chars"], _SEARCH_TEXT_BUDGET_CHARS))
    fetches = max(0, _as_int(values["fetches"], _MAX_PRIMARY_FETCHES))
    excerpt = max(1, _as_int(values["excerpt"], _EXCERPT_MAX_CHARS))
    return FactcheckLimits(
        budgets_enabled=True, budget_source=budget_source,
        budget_known=budget_known, base_seconds=base, max_seconds=cap,
        refine_calls=refine, total_queries=total, search_text_chars=chars,
        page_size=page_size, claim_portion=portion,
        primary_fetches=fetches, excerpt_chars=excerpt,
        sources=tuple(sorted(sources.items())))


async def _read_limit(key: str, default, *, chat_id):
    """(значение, source) из единого read-path; fail-open на default."""
    try:
        from services import worker_settings
        value, source = await worker_settings.resolve_setting_with_source(
            key, chat_id=chat_id, default=default)
        return value, source
    except Exception:      # pragma: no cover — конфиг не рвёт контур
        return default, "default"


async def resolve_factcheck_limits(
        chat_id=None, *,
        budgets_enabled: bool | None = None,
        budget_source: str | None = None,
        budget_known: bool | None = None,
) -> FactcheckLimits:
    """Единственная async-точка эффективных ресурсов фактчека (S14).

    Приоритет master-флага принадлежит S1 (`budget_gate.resolve_budgets`):
    chat override → global → default, с last-known-valid. Фактчек не вводит
    второй master и не угадывает происхождение сохранённых значений.
    """
    if budgets_enabled is None:
        try:
            from services import budget_gate
            state = await budget_gate.resolve_budgets(chat_id)
            enabled = bool(state.enabled)
            source = str(getattr(state, "source", "default") or "default")
            known = bool(getattr(state, "known", True))
        except Exception:      # pragma: no cover — fail-open как прежде
            from config.settings import settings
            enabled = bool(getattr(settings, "BUDGETS_ENABLED", True))
            source, known = "default", False
    else:
        enabled = bool(budgets_enabled)
        source = str(budget_source or "default")
        known = bool(True if budget_known is None else budget_known)

    values, sources = {}, {}
    for name, key, default in (
            ("base", _LIMIT_BASE, _BUDGET_SECONDS_DEFAULT),
            ("max", _LIMIT_BASE_MAX, _BUDGET_SECONDS_MAX),
            ("refine", _LIMIT_REFINE, _REFINE_CALLS_DEFAULT),
            ("total", _LIMIT_TOTAL_QUERIES, _MAX_QUERIES_TOTAL_DEFAULT),
            ("chars", _LIMIT_SEARCH_CHARS, _SEARCH_TEXT_BUDGET_CHARS),
            ("page", _LIMIT_PAGE_SIZE, FACTCHECK_PAGE_SIZE),
            ("portion", _LIMIT_CLAIM_PORTION, _CLAIM_UNITS_PORTION),
            ("fetches", _LIMIT_PRIMARY_FETCHES, _MAX_PRIMARY_FETCHES),
            ("excerpt", _LIMIT_EXCERPT_CHARS, _EXCERPT_MAX_CHARS)):
        value, src = await _read_limit(key, default, chat_id=chat_id)
        values[name], sources[key] = value, src
    sources[_BUDGETS_KEY] = source
    return _limits_from_values(
        enabled=enabled, budget_source=source, budget_known=known,
        values=values, sources=sources)


def resolve_factcheck_limits_sync(chat_id=None) -> FactcheckLimits:
    """Sync-проекция для планирования (без I/O): прогретый chat override →
    hot/global → settings default. Исполнение всё равно перечитывает async
    (`run_retrieval`), поэтому sync-значение не является решающим."""
    from config.settings import settings
    from services import hot_config as hot
    from services import chat_params as cp

    enabled = None
    source = "default"
    known = True
    try:
        from services import budget_gate
        state = budget_gate.last_known_state(chat_id)
        if state is not None:
            enabled = bool(state.enabled)
            source = str(state.source)
            known = bool(state.known)
    except Exception:      # pragma: no cover
        state = None
    if enabled is None and chat_id is not None:
        value, found = cp.read_override_sync(
            int(chat_id), _BUDGETS_KEY, None)
        if found:
            enabled, source = bool(value), "chat"
    if enabled is None:
        sentinel = object()
        value = hot.get(_BUDGETS_KEY, sentinel)
        if value is not sentinel and value is not None:
            enabled, source = bool(value), "global"
    if enabled is None:
        enabled = bool(getattr(settings, "BUDGETS_ENABLED", True))
        source = "default"
        # Для глобального скоупа заводской default — достоверная резолюция;
        # для чата отсутствие прогретого слоя не позволяет исключить chat
        # override, поэтому происхождение честно помечается unknown.
        known = chat_id is None

    def _sync_value(key: str, default):
        if chat_id is not None:
            value, found = cp.read_override_sync(int(chat_id), key, None)
            if found:
                return value, "chat"
        sentinel = object()
        value = hot.get(key, sentinel)
        if value is not sentinel and value is not None:
            return value, "global"
        return default, "default"

    values, sources = {}, {}
    for name, key, default in (
            ("base", _LIMIT_BASE, _BUDGET_SECONDS_DEFAULT),
            ("max", _LIMIT_BASE_MAX, _BUDGET_SECONDS_MAX),
            ("refine", _LIMIT_REFINE, _REFINE_CALLS_DEFAULT),
            ("total", _LIMIT_TOTAL_QUERIES, _MAX_QUERIES_TOTAL_DEFAULT),
            ("chars", _LIMIT_SEARCH_CHARS, _SEARCH_TEXT_BUDGET_CHARS),
            ("page", _LIMIT_PAGE_SIZE, FACTCHECK_PAGE_SIZE),
            ("portion", _LIMIT_CLAIM_PORTION, _CLAIM_UNITS_PORTION),
            ("fetches", _LIMIT_PRIMARY_FETCHES, _MAX_PRIMARY_FETCHES),
            ("excerpt", _LIMIT_EXCERPT_CHARS, _EXCERPT_MAX_CHARS)):
        value, src = _sync_value(key, default)
        values[name], sources[key] = value, src
    sources[_BUDGETS_KEY] = source
    return _limits_from_values(
        enabled=bool(enabled), budget_source=source, budget_known=known,
        values=values, sources=sources)


def _hot_number(key: str, default: float) -> float:
    """Числовая настройка из существующего конфиг-слоя (fail-open)."""
    try:
        from services import hot_config as hot
        return float(hot.get(key, default))
    except Exception:      # pragma: no cover — конфиг не рвёт контур
        return float(default)


def _budget_seconds(claims_count: int, limits: FactcheckLimits):
    """Адаптивный бюджет ON; ``None`` — бюджеты OFF (дедлайна нет)."""
    if not limits.budgets_enabled or limits.base_seconds is None:
        return None
    extra = max(0, int(claims_count) - 1)
    base = float(limits.base_seconds)
    cap = float(limits.max_seconds if limits.max_seconds is not None else base)
    return max(base, min(cap, base * (1.0 + _BUDGET_SECONDS_PER_EXTRA_CLAIM
                                      * extra)))


def resolve_retrieval_budget(claims_count: int,
                            *, base: float | None = None,
                            limits: FactcheckLimits | None = None):
    """§3.2: адаптивный бюджет по числу существенных частей.

    S14: при effective budgets OFF возвращает ``None`` — продуктового
    deadline нет. ``base``/hot-ключи сохранены для совместимости; при
    явном ``base`` (тест/вызывающий) значение используется как политика
    вызывающего.
    """
    if limits is not None:
        if base is not None:
            return float(base)
        return _budget_seconds(claims_count, limits)
    base_value = float(_BUDGET_SECONDS_DEFAULT if base is None
                       else base)
    base_value = _hot_number(_LIMIT_BASE, base_value)
    cap = _hot_number(_LIMIT_BASE_MAX, _BUDGET_SECONDS_MAX)
    extra = max(0, int(claims_count) - 1)
    return max(base_value, min(cap, base_value *
                               (1.0 + _BUDGET_SECONDS_PER_EXTRA_CLAIM * extra)))


#: S14: прежний `_refine_calls_limit` удалён — единственный источник
#: уточняющего бюджета `FactcheckLimits.refine_calls` (OFF снимает его).


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
    budget_seconds: float | None = 0.0
    #: §11.2 п.2 (ES-3): сколько кандидатов на открытие первоисточника
    #: осталось без попытки именно из-за дедлайна стадии. Отдельный счётчик:
    #: это не `source_extract_failed` и не «материалы не удалось разобрать».
    fetch_skipped_deadline: int = 0
    #: S14: сколько кандидатов не открыто из-за политики нагрузки при ON
    #: (не смешивается с дедлайном; при OFF счётчик всегда 0).
    fetch_skipped_budget: int = 0
    #: FC-07.1 (corrective 05.11.2026): все attempted queries прогона —
    #: в приватную диагностику (корреляция с correlation_id); это уже
    #: деперсонализированные строки, ушедшие в поисковик, а не текст чата.
    attempted_queries: tuple[str, ...] = ()
    #: S14 §13: машинная причина завершения retrieval (различает ранний
    #: успех, достаточное evidence, отсутствие прогресса, отказ провайдера,
    #: технический и бюджетный предел; не маскирует скрытый enforcement).
    stop_reason: str = ""
    #: S14: effective-состояние бюджетов и источник значений (без секретов).
    budgets_enabled: bool = True
    budget_source: str = "default"
    budget_known: bool = True
    limit_sources: tuple[tuple[str, str], ...] = ()
    #: S14 §5.2/§7: 100 000 символов — размер ПОРЦИИ. Полный текст не теряется:
    #: `search_text` = первая порция (совместимый контракт), `search_text_
    #: portions` = все порции, `search_text_truncated` — есть ли остаток.
    search_text_portions: tuple[str, ...] = ()
    search_text_total_chars: int = 0
    search_text_truncated: bool = False

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
            "stop_reason": str(self.stop_reason),
            "budgets_enabled": bool(self.budgets_enabled),
            "budget_source": str(self.budget_source),
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
        #: FC-07.1: URL, открытые и прочитанные в этом прогоне (run-level
        #: ``opened`` остаётся счётчиком; здесь — факт открытия по кандидату)
        self.opened_urls: set[str] = set()
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
    латинские имена/тикеры + метрики; тип тезиса — причина требует причинной
    связки в источнике)."""
    return claim_relevance(
        str(getattr(ref, "support", "") or ""),
        claim_text=claim.vocabulary(),
        anchor_terms=claim.foreign_terms,
        metrics=claim.metrics,
        entities=claim.entities,
        claim_type=claim.claim_type)


def _strong_binding(ref: EvidenceRef, claim: ClaimUnit) -> bool:
    return _relevance_for(ref, claim).strong


def _claim_settled(run: "_ClaimRun") -> bool:
    """Тезис уже покрыт по существу: сильное подтверждение или опровержение.

    Reviewer F5: `qualifies` (событие без числа) — НЕ покрытие, иначе спорная
    сумма никогда не получает уточняющего запроса.
    """
    for ref, role, _note in run.bound.values():
        if role == EVIDENCE_ROLE_CONTRADICTS:
            return True
        if role == EVIDENCE_ROLE_SUPPORTS and _strong_binding(ref, run.claim):
            return True
    return False


def _gap_note(status_detail: str, *, stale: bool = False,
              number_mismatch: bool = False) -> str:
    """§3.1/§4: КОНКРЕТНАЯ причина пробела (не «данных недостаточно»)."""
    notes = {
        CLAIM_STATUS_CONFLICTING: (
            "источники расходятся в числе/единице: заявленное значение не "
            "совпадает с тем, что дают источники"
            if number_mismatch else
            "источники расходятся: есть данные и за тезис, и против него"),
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


def _normalized_title(support: str, *, limit: int = 200) -> str:
    """FC-03.2: нормализованный title кандидата — первое предложение
    выдержки (support = «title. snippet» у строк поиска). Детерминированно."""
    text = re.sub(r"\s{2,}", " ", str(support or "")).strip()
    if not text:
        return ""
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    return first[:limit].strip()


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
                     for r, _n in qualifies + supports)
    stale = run.stale_hit or any("старше" in (n or "")
                                 for _r, _role, n in roles)

    if strong_supports and not contradicts and not mismatched:
        outcome, detail = CLAIM_OUTCOME_CONFIRMED, CLAIM_STATUS_VERIFIED
    elif strong_supports and (contradicts or mismatched):
        outcome, detail = CLAIM_OUTCOME_CONFLICTING, CLAIM_STATUS_CONFLICTING
    elif contradicts and not supports:
        outcome, detail = CLAIM_OUTCOME_REFUTED, CLAIM_STATUS_REFUTED
    elif mismatched:
        # Reviewer F2: расходящиеся оценки (2,8 % и 3,1 % против заявленных
        # 3,4 %) — конфликт, а не «число не подтверждено» в вакууме.
        outcome, detail = CLAIM_OUTCOME_CONFLICTING, CLAIM_STATUS_CONFLICTING
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
        detail_for_note, stale=stale,
        number_mismatch=bool(mismatched and not strong_supports))
    evidence_items = tuple(ClaimEvidence(
        claim_id=claim.claim_id, evidence_id=str(getattr(ref, "evidence_id", "")
                                                or ""),
        url=ref.url, role=role, published_at=getattr(ref, "published_at", None),
        event_at=claim.event_at, note=note_item,
        strength=_relevance_for(ref, claim).strength,
        title=_normalized_title(ref.support),
        opened=(str(ref.url or "") in run.opened_urls))
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


#: S14 §6.3: содержательные причины завершения retrieval. Значения —
#: машинные (для логов/метрик); текст причины не является пользовательским
#: ответом. `unexplained_stop` — специальный маркер скрытого enforcement:
#: исполнение прекратилось без отслеженной причины.
STOP_SUFFICIENT_EVIDENCE = "sufficient_evidence"
STOP_NO_PROGRESS = "no_progress"
STOP_PROVIDERS_UNAVAILABLE = "providers_unavailable"
STOP_BUDGET_EXHAUSTED = "budget_exhausted"
STOP_TECHNICAL_LIMIT = "technical_limit"
STOP_PATHS_EXHAUSTED = "paths_exhausted"
STOP_CANCELLED = "cancelled"
STOP_UNEXPLAINED = "unexplained_stop"
STOP_NOT_STARTED = "not_started"


def _text_portions(text: str, size: int | None) -> tuple[str, ...]:
    """Разбить текст на порции БЕЗ потери: `"".join(portions) == text`."""
    value = str(text or "")
    if not value:
        return ()
    if size is None or int(size) <= 0 or len(value) <= int(size):
        return (value,)
    step = int(size)
    return tuple(value[start:start + step]
                 for start in range(0, len(value), step))


async def run_retrieval(plan: RetrievalPlan, *, aggregator,
                        fetch_text=None,
                        max_rows_per_query: int | None = None,
                        budget_seconds: float | None = None,
                        refine_calls: int | None = None,
                        limits: "FactcheckLimits | None" = None,
                        ) -> RetrievalOutcome:
    """Единый контур: план → запросы ПО КАЖДОЙ части → структурный evidence +
    строка выдачи для user-content. Дедлайн бюджета/ошибки запросов —
    честная деградация (partial результат, пусто → ok=False). Никогда
    не бросает.

    ASAP-FC-EVIDENCE-STYLE-02 §3: каждая claim-единица получает базовую
    попытку; далее coverage-loop добавляет уточнение ТОЛЬКО для непокрытых
    частей.

    S14 FACTCHECK-REQUEST-INTEGRITY §5–6: ресурсы берутся из
    `FactcheckLimits`. При effective budgets OFF (`budgets_enabled=False`)
    нет продуктового дедлайна, общего/уточняющего cap и char-бюджета —
    исполняются все запросы плана и уточнения по содержательной надобности;
    при ON действуют 120/600 с, 24 уточняющих и 64 общих (базовые+уточняющие
    ВМЕСТЕ), 100 000 символов — размер порции, 20 результатов на страницу,
    32 claim units — размер порции. Поиск завершается по содержательному
    состоянию (`stop_reason`), а не по счётчику.
    """
    loop = asyncio.get_running_loop()
    claims = tuple(plan.claims) if plan is not None and plan.claims else ()
    if not claims and plan is not None:
        base_text = str(plan.claim_text or "").strip()
        if not base_text and plan.queries:
            base_text = str(plan.queries[0].text or "")
        if base_text:
            claims = (_pseudo_claim(base_text),)
    if limits is None:
        limits = await resolve_factcheck_limits(
            getattr(plan, "chat_id", None) if plan is not None else None)
    if budget_seconds is not None:
        budget: float | None = float(budget_seconds)
    else:
        budget = _budget_seconds(len(claims) or 1, limits)
    deadline = loop.time() + budget if budget is not None else None
    page_limit = (max(1, int(max_rows_per_query))
                  if max_rows_per_query is not None
                  else max(1, int(limits.page_size)))
    refine_limit = (max(0, int(refine_calls)) if refine_calls is not None
                    else limits.refine_calls)
    total_limit = limits.total_queries
    fetch_limit = limits.primary_fetches
    excerpt_chars = limits.excerpt_chars
    outcome_empty = RetrievalOutcome(
        evidence_map=None, search_text="", queries_attempted=0,
        queries_used=0, refs_collected=0, fetch_errors=0,
        budget_exhausted=False, provider_failures=0,
        claims=(), budget_seconds=budget, stop_reason=STOP_NOT_STARTED,
        budgets_enabled=bool(limits.budgets_enabled),
        budget_source=str(limits.budget_source),
        budget_known=bool(limits.budget_known),
        limit_sources=tuple(limits.sources))
    if plan is None or not plan.queries or aggregator is None:
        return outcome_empty

    relevance_search = getattr(aggregator, "search_relevant", None)
    runs: list[_ClaimRun] = [_ClaimRun(claim) for claim in claims]
    blocks: list[str] = []
    counters = {"attempted": 0, "used": 0, "fetch_errors": 0,
                "provider_failures": 0, "empty": 0, "irrelevant": 0,
                "off_topic": 0, "stale": 0, "refine": 0}
    product_budget_hit = False
    technical_deadline = False
    stop_reason = ""
    total_calls = (len(plan.queries) + (refine_limit or 0))

    def _deadline_now() -> bool:
        return deadline is not None and loop.time() >= deadline

    async def _invoke(query: SearchQuery, query_terms, timeout_budget, trace):
        if relevance_search is not None:
            if timeout_budget is not None:
                try:
                    return await relevance_search(
                        query.text, query.max_symbols,
                        relevance_terms=query_terms,
                        timeout_budget=timeout_budget, trace=trace)
                except TypeError:
                    try:
                        return await relevance_search(
                            query.text, query.max_symbols,
                            relevance_terms=query_terms,
                            timeout_budget=timeout_budget)
                    except TypeError:
                        pass
            try:
                return await relevance_search(
                    query.text, query.max_symbols,
                    relevance_terms=query_terms, trace=trace)
            except TypeError:
                return await relevance_search(
                    query.text, query.max_symbols,
                    relevance_terms=query_terms)
        try:
            return await aggregator.search(query.text, query.max_symbols,
                                           trace=trace)
        except TypeError:
            return await aggregator.search(query.text, query.max_symbols)

    async def _attempt(query: SearchQuery, run: _ClaimRun) -> None:
        nonlocal product_budget_hit, technical_deadline
        if total_limit is not None and counters["attempted"] >= int(total_limit):
            product_budget_hit = True
            run.deadline_hit = True
            return
        remaining = None
        if deadline is not None:
            remaining = deadline - loop.time()
            if remaining <= 0:
                product_budget_hit = True
                run.deadline_hit = True
                return
        counters["attempted"] += 1
        run.attempts += 1
        run.attempted_texts.add(str(query.text).lower())
        query_terms = _claim_terms(query.text, limit=10)
        per_query_budget = None
        if remaining is not None:
            calls_left = max(1, total_calls - counters["attempted"] + 1)
            per_query_budget = max(1.0, remaining / calls_left)
        trace: dict = {}
        started_at = loop.time()
        try:
            chunk = await _invoke(query, query_terms, per_query_budget, trace)
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
                # Транспортный/провайдерский предел конкретного вызова —
                # НЕ продуктовый бюджет всего исследования (SFC-13-03).
                technical_deadline = True
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
            if _deadline_now():
                product_budget_hit = True
                run.deadline_hit = True
            return
        if not chunk or not str(chunk).strip():
            counters["empty"] += 1
            run.empty += 1
            run.providers.append(f"{query.intent}:empty")
            return
        counters["used"] += 1
        blocks.append(str(chunk))
        if _deadline_now():
            # §3.2/§5.2: продуктовый бюджет ИСЧЕРПАН этим вызовом — честно
            # фиксируем, чтобы оставшиеся части не выдавались за проверенные.
            product_budget_hit = True
            run.deadline_hit = True
        refs = evidence_refs_from_search(str(chunk), intent=query.intent,
                                        max_rows=page_limit)
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
            # Запроса нет: при ON это упёршийся общий бюджет, при OFF —
            # структурная аномалия вызывающего (честно отмечаем, не прячем).
            if total_limit is not None:
                run.deadline_hit = True
                product_budget_hit = True
            continue
        for query in queries:
            if query.purpose == QUERY_PURPOSE_REFINE:
                continue
            if _deadline_now():
                product_budget_hit = True
                run.deadline_hit = True
                break
            if total_limit is not None and \
                    counters["attempted"] >= int(total_limit):
                product_budget_hit = True
                run.deadline_hit = True
                break
            await _attempt(query, run)
    # Части, до которых общий бюджет не дошёл, честно помечаются лимитом
    # (а не «источников не нашлось»).
    if product_budget_hit:
        for run in runs:
            if run.attempts == 0 and not _claim_settled(run):
                run.deadline_hit = True

    # Проход 2 (§3.2/§6.4): уточнения — только непокрытым частям; при ON
    # 24 уточняющих и общий 64 включают и базовые, и уточняющие запросы.
    refine_left = refine_limit
    for run in runs:
        if _claim_settled(run):
            continue
        if total_limit is not None and \
                counters["attempted"] >= int(total_limit):
            product_budget_hit = True
            break
        if _deadline_now():
            product_budget_hit = True
            break
        if refine_left is not None and refine_left <= 0:
            product_budget_hit = True
            break
        # Reviewer F5: уточнение нужно, пока тезис НЕ подтверждён сильно и не
        # опровергнут. Любая показанная ссылка (в т.ч. `qualifies` — «событие
        # есть, числа нет») покрытием не считается.
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
        if refine_left is not None:
            refine_left -= 1
        counters["refine"] += 1
        await _attempt(query, run)

    # §3.3: URL ≠ доказательство — содержимое достаётся только для строк,
    # привязанных к своей части; превышение бюджета больше не маскируется.
    # ES-3: кандидаты, не открытые ИМЕННО из-за дедлайна, считаются отдельно.
    eligible_urls: list[str] = []
    seen_urls: set[str] = set()
    if plan.needs_primary_fetch:
        for run in runs:
            for ref, role, _n in run.bound.values():
                if role in (EVIDENCE_ROLE_SUPPORTS, EVIDENCE_ROLE_QUALIFIES) \
                        and ref.url and ref.url not in eligible_urls:
                    eligible_urls.append(ref.url)
    fetched_total = 0
    fetch_skipped_budget = 0
    fetch_limit_reached = False
    if plan.needs_primary_fetch and not _deadline_now():
        for run in runs:
            if fetch_limit is not None and fetched_total >= int(fetch_limit):
                fetch_limit_reached = True
                break
            if _deadline_now():
                break
            candidates = sorted(
                ((ref, role) for ref, role, _n in run.bound.values()
                 if role in (EVIDENCE_ROLE_SUPPORTS, EVIDENCE_ROLE_QUALIFIES)),
                key=lambda pair: 0 if pair[1] == EVIDENCE_ROLE_SUPPORTS else 1)
            for ref, _role in candidates:
                if fetch_limit is not None and \
                        fetched_total >= int(fetch_limit):
                    fetch_limit_reached = True
                    break
                if not ref.url or ref.url in seen_urls:
                    continue
                seen_urls.add(ref.url)
                primary = await fetch_primary_evidence(
                    ref.url, fetch_text=fetch_text,
                    excerpt_chars=excerpt_chars)
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
                run.opened_urls.add(str(primary.url or ""))
                key = run.key(primary)
                previous = run.bound.get(key)
                # FC-03.3: тип источника — по происхождению URL
                # (classify_source_kind при открытии), а не по факту fetch.
                kind = str(primary.source_kind or "secondary")
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
    if fetch_limit_reached:
        # Политика нагрузки ON: сколько релевантных кандидатов осталось
        # неоткрытыми именно из-за предела (не «источников не нашлось»).
        fetch_skipped_budget = len(
            [u for u in eligible_urls if u not in seen_urls])

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

    full_text = "\n\n".join(blocks)
    portions = _text_portions(full_text, limits.search_text_chars)
    search_text = portions[0] if portions else ""
    fetch_skipped = 0
    if eligible_urls and _deadline_now():
        # Дедлайн — фактическая причина, по которой открытие не состоялось.
        fetch_skipped = len([u for u in eligible_urls if u not in seen_urls])

    all_settled = bool(runs) and all(_claim_settled(run) for run in runs)
    planned_base = sum(
        1 for run in runs
        for query in plan.queries_for(run.claim.claim_id)
        if query.purpose != QUERY_PURPOSE_REFINE)
    if product_budget_hit:
        stop_reason = STOP_BUDGET_EXHAUSTED
    elif all_settled:
        stop_reason = STOP_SUFFICIENT_EVIDENCE
    elif counters["attempted"] == 0:
        stop_reason = STOP_PATHS_EXHAUSTED
    elif counters["used"] == 0 and technical_deadline \
            and counters["provider_failures"] > 0 \
            and not (counters["empty"] or counters["irrelevant"]):
        stop_reason = STOP_TECHNICAL_LIMIT
    elif counters["used"] == 0 and counters["provider_failures"] > 0 \
            and not (counters["empty"] or counters["irrelevant"]):
        stop_reason = STOP_PROVIDERS_UNAVAILABLE
    elif counters["used"] == 0:
        stop_reason = STOP_NO_PROGRESS
    elif planned_base and counters["attempted"] < planned_base \
            and not product_budget_hit:
        # Скрытый enforcement: запросы плана остались без попытки без
        # отслеженного бюджета/дедлайна/содержательной причины.
        stop_reason = STOP_UNEXPLAINED
    else:
        stop_reason = STOP_PATHS_EXHAUSTED
    budget_exhausted = bool(product_budget_hit)
    # FC-07.1: attempted queries прогона (порядок попыток, без повторов).
    attempted: list[str] = []
    for run in runs:
        for text in run.attempted_texts:
            if text not in {a.lower() for a in attempted}:
                attempted.append(text)
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
        budget_seconds=budget,
        fetch_skipped_deadline=fetch_skipped,
        fetch_skipped_budget=fetch_skipped_budget,
        attempted_queries=tuple(attempted),
        stop_reason=stop_reason,
        budgets_enabled=bool(limits.budgets_enabled),
        budget_source=str(limits.budget_source),
        budget_known=bool(limits.budget_known),
        limit_sources=tuple(limits.sources),
        search_text_portions=portions,
        search_text_total_chars=len(full_text),
        search_text_truncated=len(portions) > 1)


def _strong_binding_count(ref: EvidenceRef, runs: list[_ClaimRun]) -> int:
    """Сколько частей эта ссылка подтверждает сильно (порядок выдачи)."""
    count = 0
    for run in runs:
        if run.claim.claim_id not in (ref.claims or ()):
            continue
        if _strong_binding(ref, run.claim):
            count += 1
    return count


