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
import logging
import re

from services import temporal_factcheck as tf
from services.factcheck_orchestrator import EvidenceMap, EvidenceRef
from services.search_aggregator import classify_source_kind

logger = logging.getLogger(__name__)

# fp2 (FC-SEMQUERY/FC-EVIDQ, owner 21.10.2026 §3.3–3.4): запросы строятся
# от самостоятельных частей клейма (claim_items/предложения) + generic
# синонимы; выдача проверяется на содержательную релевантность.
# fp3 (P0-FACTCHECK, owner 24.10.2026 §3.3/§3.5): КАЖДАЯ проверяемая часть
# получает свой запрос (бюджет тот же ≤3) — составная публикация больше не
# сводится к одному запросу; свидетельство без URL не считается
# доказательством; бюджет запроса урезает per-engine таймауты.
PLANNER_VERSION = "fp3"

# Интенты запросов (06C: 2–4 запроса с различающей целью).
INTENT_ENTITY_CHECK = "entity_check"
INTENT_NUMERIC = "numeric_verification"
INTENT_TEMPORAL = "temporal_context"
INTENT_ORIGIN = "claim_origin"
INTENTS = (INTENT_ENTITY_CHECK, INTENT_NUMERIC, INTENT_TEMPORAL,
           INTENT_ORIGIN)

_MAX_QUERIES = 3
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
                quoted: str = "") -> SearchQuery | None:
    parts = list(terms)
    if quoted:
        parts.insert(0, f"«{quoted}»")
    if tail:
        parts.append(tail)
    text = " ".join(p for p in parts if p)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) < 6:
        return None
    return SearchQuery(text=text[:_QUERY_MAX_CHARS], intent=intent)


def build_retrieval_plan(decision, ctx=None, *,
                         claim_text: str | None = None,
                         max_queries: int = _MAX_QUERIES,
                         ) -> RetrievalPlan | None:
    """SuitabilityDecision/ClaimItem → план поисковых действий.

    Gate/планировщик OFF (default) или проверять нечего → None — вызывающий
    не выполняет НИКАКИХ платных запросов (OFF-паритет). Никогда не бросает."""
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

    def _add(query: SearchQuery | None) -> bool:
        if query is None or len(queries) >= max(1, int(max_queries)):
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

    # FC-SEMQUERY (owner §3.3): запрос — от самостоятельной части клейма
    # (claim_items/предложения), с сущностями/числами/годами ЭТОЙ части;
    # НЕ первые 8 токенов всего сообщения. Бюджеты сохранены (≤3 запроса,
    # ≤200 символов). Privacy: каждый unit проходит тот же фильтр участников,
    # что и весь клейм.
    #
    # P0-FACTCHECK (§3.3/§3.5, 24.10.2026): КАЖДАЯ часть получает СВОЙ
    # запрос — прежняя схема «по одному запросу на интент» превращала
    # составную новость в единственный общий запрос (прод: queries=1) и
    # теряла остальные тезисы. Общий бюджет НЕ увеличен.
    #
    # F4 (review r1): бюджет расходуется ДВУМЯ проходами — сначала по
    # одному базовому запросу на часть (части не голодают), затем
    # уточнения (числа/годы) на остаток. Раньше первая часть с числом и
    # годом забирала все 3 запроса, и остальные тезисы не проверялись.
    units: list[tuple[str, list[str], list[str], list[str]]] = []
    for raw_unit in _claim_units(items, claim):
        unit, _unit_dropped = _strip_privacy(raw_unit, authors)
        if not unit:
            continue
        uterms = _claim_terms(unit, limit=8)
        uents = [e for e in _entities(unit)
                 if e.lower() not in {t.lower() for t in uterms}][:3]
        units.append((unit, uterms, uents,
                      _expand_terms((uents + uterms)[:10])))
    budget = max(1, int(max_queries))
    # Проход 1: базовая проверка каждой части (≤ бюджет). Сколько слотов
    # останется на уточнения — зависит от числа частей.
    base_units = units[:budget]
    refine_room = budget - len(base_units)
    for unit, uterms, uents, base in base_units:
        if refine_room <= 0:
            # Слотов на отдельные уточнения нет — числа/годы части идут в
            # ЕЁ ЖЕ запрос, чтобы не потеряться (F4).
            years = _years(unit)
            numbers = _numeric_refinements(unit, years)
            tail = " ".join(numbers + years).strip()
            _add(_make_query(base, INTENT_ENTITY_CHECK, tail=tail))
        else:
            _add(_make_query(base, INTENT_ENTITY_CHECK))
    # Проход 2: отдельные уточняющие интенты — только остаток бюджета.
    for unit, uterms, uents, base in units:
        if len(queries) >= budget:
            break
        years = _years(unit)
        # год — временной контекст, не «числовая метрика» (120 мм ≠ 2019)
        numeric = _numeric_refinements(unit, years)
        if numeric:
            _add(_make_query(_expand_terms(uterms), INTENT_NUMERIC,
                             tail=" ".join(numeric)))
        if len(queries) >= budget:
            break
        if years:
            _add(_make_query(_expand_terms(uterms), INTENT_TEMPORAL,
                             tail=" ".join(years)))
    # Цитата → проверка происхождения (цитата может быть в любой части)
    quoted = _QUOTED_RE.search(claim)
    if quoted:
        _add(_make_query(entities or terms[:4], INTENT_ORIGIN,
                         quoted=quoted.group(1)))
    # Деградация: ни одна часть не дала запроса (например, короткий клейм)
    if not queries:
        base = _expand_terms((entities + terms)[:8])
        _add(_make_query(base, INTENT_ENTITY_CHECK))
        years = _years(claim)
        if years:
            _add(_make_query(base, INTENT_TEMPORAL, tail=" ".join(years)))
    if not queries:
        return None
    return RetrievalPlan(
        queries=tuple(queries), needs_web=True,
        needs_chat_history=needs_chat,
        needs_primary_fetch=True, dropped_privacy=dropped,
        claim_text=claim)


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
# Дедлайн всего retrieval-контура на прогон (сек; движки имеют свои
# per-engine таймауты, это — общий потолок контура).
_BUDGET_SECONDS_DEFAULT = 10.0


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
    ``provider_failures``."""
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

    @property
    def ok(self) -> bool:
        return bool(self.search_text) or self.evidence_map is not None


async def run_retrieval(plan: RetrievalPlan, *, aggregator,
                        fetch_text=None, max_rows_per_query: int = 4,
                        budget_seconds: float | None = None,
                        ) -> RetrievalOutcome:
    """Единый контур: план → bounded запросы → структурный evidence +
    строка выдачи для user-content. Дедлайн бюджета/ошибки запросов —
    честная деградация (partial результат, пусто → ok=False). Никогда
    не бросает.

    FC-EVIDQ (§3.4): запрос идёт через relevance-вход агрегатора
    (``search_relevant`` — непустая, но нерелевантная выдача уровня не
    останавливает каскад; фейки без метода — прежний ``search``); строки
    evidence ранжируются overlap'ом с клеймом (стабильная сортировка), и
    primary-fetch идёт по самым релевантным. URL ≠ доказательство: 
    содержимое подходящих страниц достаётся существующим SafeFetcher."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + float(
        budget_seconds if budget_seconds is not None
        else _BUDGET_SECONDS_DEFAULT)
    outcome_empty = RetrievalOutcome(
        evidence_map=None, search_text="", queries_attempted=0,
        queries_used=0, refs_collected=0, fetch_errors=0,
        budget_exhausted=False, provider_failures=0)
    if plan is None or not plan.queries or aggregator is None:
        return outcome_empty
    relevance_search = getattr(aggregator, "search_relevant", None)
    refs: list[EvidenceRef] = []
    blocks: list[str] = []
    attempted = 0
    used = 0
    fetch_errors = 0
    provider_failures = 0
    empty_results = 0
    irrelevant_results = 0
    budget_exhausted = False
    total_queries = len(plan.queries)
    for index, query in enumerate(plan.queries):
        remaining = deadline - loop.time()
        if remaining <= 0:
            budget_exhausted = True
            break
        attempted += 1
        query_terms = _claim_terms(query.text, limit=10)
        # §3.3: бюджет ДЕЛИТСЯ между оставшимися запросами — один медленный
        # провайдер не съедает весь контур; дедлайн проверен ДО запроса.
        per_query_budget = max(1.0, remaining / max(1, total_queries - index))
        try:
            if relevance_search is not None:
                try:
                    chunk = await relevance_search(
                        query.text, query.max_symbols,
                        relevance_terms=query_terms,
                        timeout_budget=per_query_budget)
                except TypeError:
                    # фейк/старый агрегатор без timeout_budget (контракт
                    # остаётся совместимым)
                    chunk = await relevance_search(
                        query.text, query.max_symbols,
                        relevance_terms=query_terms)
            else:
                chunk = await aggregator.search(query.text, query.max_symbols)
        except Exception as exc:
            # §5.1: причина различается — недоступность/timeout/ошибка API
            # (provider_failures) ≠ пустая выдача ≠ нерелевантная выдача.
            cause = str(getattr(exc, "reason", "") or "")
            if cause == "empty_results":
                empty_results += 1
            elif cause == "irrelevant_results":
                irrelevant_results += 1
            else:
                provider_failures += 1
            logger.info("[factcheck_planner] query failed | intent=%s | "
                        "cause=%s", query.intent,
                        cause or "provider_error", exc_info=True)
            if loop.time() >= deadline:
                budget_exhausted = True
            continue
        if not chunk or not str(chunk).strip():
            # §5.1: провайдер ответил ПУСТОЙ выдачей — это не недоступность
            empty_results += 1
            continue
        used += 1
        blocks.append(str(chunk))
        # FC-EVIDQ: дубли срезаются и МЕЖДУ запросами (один и тот же
        # источник из двух запросов — не «второе доказательство»)
        seen_support = {re.sub(r"\W+", "", r.support.lower())[:100]
                        for r in refs}
        for ref in evidence_refs_from_search(
                str(chunk), intent=query.intent,
                max_rows=max_rows_per_query):
            if not ref.url:
                # P0-FACTCHECK (§3.6): строка без URL — не доказательство:
                # её нельзя открыть/проверить (прод-кейс: 4 off-topic строки
                # с url=null). В search_text она остаётся как контекст.
                continue
            key = re.sub(r"\W+", "", ref.support.lower())[:100]
            if key in seen_support:
                continue
            seen_support.add(key)
            refs.append(ref)
        if len(refs) >= _MAX_EVIDENCE_REFS:
            break
    if refs:
        # §3.4: строки с содержательным overlap'ом с клеймом — первыми
        # (стабильная сортировка: порядок провайдеров в группах сохранён).
        claim_terms_all = _claim_terms(plan.claim_text, limit=24)

        def _score(ref: EvidenceRef) -> int:
            haystack = str(ref.support or "").lower()
            return sum(1 for t in claim_terms_all if t in haystack)

        refs.sort(key=_score, reverse=True)
    if refs and plan.needs_primary_fetch and loop.time() < deadline:
        # §3.4: URL ≠ доказательство — содержимое страниц достаётся только
        # для строк с overlap'ом по клейму (когда такие есть среди строк).
        fetch_pool = [r for r in refs if _score(r) > 0] or refs
        fetched: list[EvidenceRef] = []
        seen_urls: set[str] = set()
        for ref in fetch_pool:
            if len(fetched) >= _MAX_PRIMARY_FETCHES:
                break
            if loop.time() >= deadline:
                budget_exhausted = True
                break
            if not ref.url or ref.url in seen_urls:
                continue
            seen_urls.add(ref.url)
            primary = await fetch_primary_evidence(ref.url,
                                                   fetch_text=fetch_text)
            if primary is None:
                fetch_errors += 1
                continue
            fetched.append(primary)
        refs.extend(fetched)
    search_text = "\n\n".join(blocks)[:_SEARCH_TEXT_BUDGET_CHARS]
    evidence_map = _assemble(refs)
    return RetrievalOutcome(
        evidence_map=evidence_map, search_text=search_text,
        queries_attempted=attempted, queries_used=used,
        refs_collected=len(evidence_map.refs) if evidence_map else 0,
        fetch_errors=fetch_errors, budget_exhausted=budget_exhausted,
        provider_failures=provider_failures,
        empty_results=empty_results,
        irrelevant_results=irrelevant_results)
