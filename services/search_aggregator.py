"""Epic 33 — SearchAggregator: каскад Tavily → Exa → DuckDuckGo (R33-2, D105).

Один ленивый httpx.AsyncClient (прецедент LLMClient), per-request таймауты,
close() в on_shutdown. Уровень пропускается, если API-ключ пуст (D104).
Любая ошибка уровня (timeout/HTTP/пустой результат) → следующий уровень.
Все уровни упали → AllSearchEnginesFailedException.
Результат — единый текстовый формат, обрезка до max_symbols.

DDG (уровень 3): duckduckgo-search 8.x — sync-only (AsyncDDGS удалён в PR#268),
официальная рекомендация мейнтейнера — обёртка sync-вызова в executor
(здесь asyncio.to_thread). Контракт search() остаётся async.

ASAP-VISION-SYNC-01 §4 (другие потребители): агрегатор работает ТОЛЬКО с
текстовым запросом и текстовой выдачей — визуальное содержимое сюда не
попадает, поэтому собственная логика ожидания готовности ему не нужна
(единый контракт — `services.media_readiness`; запрос, зависящий от
изображения, собирается потребителем ДО вызова агрегатора).
"""
import asyncio
import dataclasses
import inspect
import logging
import re
import time
from typing import Awaitable, Callable

import httpx

from config.settings import settings
from services import hot_config as hot

try:
    from duckduckgo_search import DDGS
except ImportError:  # pragma: no cover — зависимость в requirements.txt
    DDGS = None

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
EXA_URL = "https://api.exa.ai/search"


class AllSearchEnginesFailedException(Exception):
    """Все уровни каскада (Tavily → Exa → DDG) упали.

    P0-FACTCHECK-CORRECTIVE (§5.1): ``reason`` — машинная причина ПОСЛЕДНЕГО
    неудачного уровня: ``provider_error`` (недоступность/ошибка API) |
    ``timeout`` | ``empty_results`` (провайдер ответил пустой выдачей) |
    ``irrelevant_results`` (выдача не прошла relevance-фильтр) | ``budget``.
    Пустая/нерелевантная выдача — НЕ «провайдеры недоступны»."""

    def __init__(self, msg: str = "all search engines failed",
                 *, reason: str = "provider_error") -> None:
        super().__init__(msg)
        self.reason = reason


def level_failure_reason(exc: BaseException) -> str:
    """Классификация неудачи уровня каскада (§5.1): timeout / API-ошибка /
    пустая выдача / нерелевантная выдача / прочая ошибка провайдера.
    Детерминированно, без новых вызовов."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    text = str(exc or "").lower()
    if "irrelevant" in text:
        return "irrelevant_results"
    if "empty" in text:
        return "empty_results"
    return "provider_error"


#: Порядок информативности причин каскада: «ответили, но пусто/нерелевантно»
#: честнее «не ответили», timeout конкретнее общей ошибки провайдера.
_REASON_PRECEDENCE = ("irrelevant_results", "empty_results", "timeout",
                      "provider_error")


def _most_informative_reason(reasons) -> str:
    """Итоговая причина каскада: самая информативная из уровней (§5.1).
    Пусто → provider_error."""
    for reason in _REASON_PRECEDENCE:
        if reason in reasons:
            return reason
    return "provider_error"


# ── FC-EVIDQ (owner 21.10.2026 §3.4): лёгкая релевантность + тип источника ──
# Дешёвые детерминированные эвристики БЕЗ тяжёлого ранжировщика и БЕЗ
# дополнительных LLM-вызовов. Никаких доменных словарей темы клейма.

_RELEVANCE_WORD_RE = re.compile(r"[0-9a-zа-яё]{4,}", re.IGNORECASE)
_RELEVANCE_STOPWORDS = frozenset({
    "это", "этого", "этому", "того", "том", "тем", "чтобы", "как", "так",
    "вот", "или", "если", "когда", "тогда", "для", "над", "под", "про",
    "что", "чего", "чем", "все", "всё", "весь", "вся", "свои", "свой",
    "одно", "один", "два", "три", "будет", "были", "было", "есть", "нет",
    "они", "них", "него", "нее", "ней", "ним", "ими", "мне", "тебе",
    "себе", "даже", "уже", "ещё", "очень", "более", "менее", "самый",
    "который", "которые", "также", "этот", "эта", "эти", "сейчас", "год",
    "года", "году", "very", "this", "that", "with", "from", "have",
    "about", "the", "and", "for", "are", "was",
})


def content_terms(text: str, *, limit: int = 10) -> list[str]:
    """Содержательные термины запроса/текста (детерминированно, lowercase,
    без стоп-слов, в исходном порядке). Для overlap-эвристики релевантности
    и смысловых запросов fallback-поиска."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for match in _RELEVANCE_WORD_RE.finditer(str(text or "").lower()):
        word = match.group(0)
        if word in _RELEVANCE_STOPWORDS or word in seen_set:
            continue
        seen_set.add(word)
        seen.append(word)
        if len(seen) >= max(1, int(limit)):
            break
    return seen


#: P0-FACTCHECK (owner 24.10.2026 §3.3/§3.4): лёгкая морфология без
#: зависимостей — русские словоизменения и английские окончания. Сравнение
#: идёт по «ключу» слова (основа), поэтому «заболеваемости» и «заболевших»
#: считаются одним термином, а «Claude» не становится доказательством
#: темы «агенты Telegram».
_RU_SUFFIXES = (
    "иями", "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими",
    "ать", "ять", "ить", "еть", "ешь", "ете", "иях", "ией", "ов", "ев",
    "ий", "ый", "ой", "ая", "яя", "ое", "ее", "ые", "ие", "ам", "ям",
    "ах", "ях", "ом", "ем", "ую", "юю", "ут", "ют", "ал", "ял", "ил",
    "ел", "ла", "ло", "ли", "их", "ых", "а", "я", "о", "е", "ы", "и",
    "у", "ю", "ь",
)
_EN_SUFFIXES = ("ations", "ation", "ings", "ing", "ers", "er", "ed", "es",
                "s")


def term_key(word: str) -> str:
    """Ключ сравнения термина: срезать словоизменение и взять основу.

    Детерминированно, без внешних зависимостей. Числа и короткие токены
    (≤5 символов) не усекаются — иначе «2019» и «2024» стали бы одним
    термином."""
    low = str(word or "").lower()
    if not low:
        return ""
    suffix = ""
    for cand in _RU_SUFFIXES:
        if len(low) - len(cand) >= 4 and low.endswith(cand):
            suffix = cand
            break
    if not suffix:
        for cand in _EN_SUFFIXES:
            if len(low) - len(cand) >= 4 and low.endswith(cand):
                suffix = cand
                break
    stem = low[: len(low) - len(suffix)] if suffix else low
    if len(stem) <= 5:
        return stem
    return stem[:6]


def _term_keys(text: str) -> set[str]:
    low = str(text or "").lower()
    keys = {term_key(w) for w in _RELEVANCE_WORD_RE.findall(low) if w}
    # числа любой длины (цены/версии/сборки) — значимые термины, но их
    # нельзя усекать основой (иначе 2019 == 2024)
    keys.update(n for n in re.findall(r"\d+(?:[.,]\d+)?", low) if n)
    return keys


def is_relevant_result(text: str, relevance_terms,
                       *, min_distinct: int | None = None) -> bool:
    """Overlap-эвристика «запрос ↔ выдача» с морфологией (P0-FACTCHECK).

    Нет терминов → True (поведение прежнее). Совпадение ОДНОГО слова не
    считается релевантностью при многотомном запросе: нужно ≥2 разных
    терминов (по основе) И ≥20% терминов. Это отсекает чужую тему, где
    случайно совпало одно имя («Claude Code» вместо «агентов Telegram»), и
    при этом пропускает пересказ другими словами («заболеваемости» ↔
    «заболевших»)."""
    terms = [str(t) for t in (relevance_terms or ()) if str(t or "").strip()]
    if not terms:
        return True
    haystack_keys = _term_keys(text)
    matched = 0
    seen: set[str] = set()
    for term in terms:
        for word in _RELEVANCE_WORD_RE.findall(term.lower()) or [term.lower()]:
            key = term_key(word)
            if not key or key in seen:
                continue
            seen.add(key)
            if key in haystack_keys:
                matched += 1
    floor = 2 if min_distinct is None else max(1, int(min_distinct))
    if min_distinct is None and len(seen) == 2:
        # P0-FACTCHECK-CORRECTIVE (§5.2): требовать ОБА стема у
        # двухтерминного запроса — генератор ложных отрицаний: документ,
        # пересказавший один термин другими словами, отбрасывался целиком.
        # Одно совпадение из двух при морфологии оставляет документ
        # аналитику (окончательное решение о пригодности — не за фильтром).
        floor = 1
    return matched >= min(floor, len(seen)) and matched >= 0.2 * len(seen)


# ── ASAP-FC-EVIDENCE-STYLE-02 §3.3: релевантность КОНКРЕТНОМУ claim ────────
# Роли доказательства для claim (закрытый набор §3.1). Оценка — лёгкая
# детерминированная (без LLM/ранжировщика): привязка якоря тезиса (число/
# метрика/латинское имя/тикер) + overlap содержательных терминов. Совпадение
# 1–2 слов/домена/общей темы доказательством НЕ является — поэтому роль
# background_only/irrelevant не попадает в «Источники».
EVIDENCE_ROLE_SUPPORTS = "supports"
EVIDENCE_ROLE_CONTRADICTS = "contradicts"
EVIDENCE_ROLE_QUALIFIES = "qualifies"
EVIDENCE_ROLE_BACKGROUND = "background_only"
EVIDENCE_ROLE_IRRELEVANT = "irrelevant"

EVIDENCE_ROLES = (EVIDENCE_ROLE_SUPPORTS, EVIDENCE_ROLE_CONTRADICTS,
                  EVIDENCE_ROLE_QUALIFIES, EVIDENCE_ROLE_BACKGROUND,
                  EVIDENCE_ROLE_IRRELEVANT)

#: Роли, которые можно показывать рядом с тезисом (background/irrelevant —
#: контекст, а не доказательство).
DISPLAYABLE_EVIDENCE_ROLES = (EVIDENCE_ROLE_SUPPORTS, EVIDENCE_ROLE_CONTRADICTS,
                              EVIDENCE_ROLE_QUALIFIES)

#: Общеязыковые признаки НАПРАВЛЕНИЯ (не предметный словарь): морфология
#: падения/снижения/удешевления против роста/повышения/подорожания. Закрытый
#: список конкретных словоформ заменён на основы — иначе «вырос» против
#: «подешевел/снизился» не распознавался (Reviewer F1).
_DOWN_RE = re.compile(
    r"\b(?:упал\w*|пада\w*|паден\w*|сниз\w*|сниж\w*|дешев\w*|подешев\w*|"
    r"обвал\w*|рухн\w*|потеря\w*|потерь|fell|fallen|fall|falls|drop\w*|"
    r"declin\w*|sank|slump\w*|plunge\w*|lost|loss\w*|down|lower)\b",
    re.IGNORECASE)
_UP_RE = re.compile(
    r"\b(?:вырос\w*|раст\w*|рост\w*|повыс\w*|повыш\w*|подорож\w*|дорож\w*|"
    r"grow\w*|grew|rose|rise|rises|risen|gain\w*|jump\w*|surge\w*|"
    r"higher|up)\b", re.IGNORECASE)

#: Причинная связка тезиса («из-за …») — отдельное требование к привязке:
#: статья о падении рынка не доказывает приписанную причину (Reviewer F1).
_CAUSAL_RE = re.compile(
    r"\b(?:из-за|потому что|в результате|вследствие|на фоне|причин\w*|"
    r"связан\w*|because|due to|caused|driven by|as a result)\b",
    re.IGNORECASE)

#: Классы единиц измерения: масштаб/валюта/проценты. Число без совместимого
#: класса НЕ подтверждает метрику (658 «млрд» ≠ 658 «million»).
_SCALE_CLASSES = (
    ("млрд", "billion"), ("млр", "billion"), ("billion", "billion"),
    ("bn", "billion"),
    ("трлн", "trillion"), ("trillion", "trillion"), ("tn", "trillion"),
    ("млн", "million"), ("million", "million"), ("mn", "million"),
    ("тыс", "thousand"), ("thousand", "thousand"),
)
_PERCENT_CLASSES = (
    ("%", "percent"), ("процент", "percent"), ("percent", "percent"),
    ("pct", "percent"), ("п.п", "pp"), ("пп", "pp"),
    ("пункт", "points"), ("point", "points"),
)
_CURRENCY_CLASSES = (
    ("$", "usd"), ("usd", "usd"), ("доллар", "usd"), ("долл", "usd"),
    ("dollar", "usd"), ("евро", "eur"), ("eur", "eur"), ("€", "eur"),
    ("фунт", "gbp"), ("gbp", "gbp"), ("£", "gbp"),
    ("руб", "rub"), ("rub", "rub"), ("₽", "rub"),
)


def _unit_class(token: str) -> str:
    """Канонический класс единицы/валюты токена (пустой → не класс)."""
    low = str(token or "").strip().lower()
    if not low:
        return ""
    for prefix, cls in (_SCALE_CLASSES + _PERCENT_CLASSES
                        + _CURRENCY_CLASSES):
        if low.startswith(prefix) or low == prefix:
            return cls
    return ""


def _unit_classes(text: str) -> set[str]:
    """Классы единиц/валют текста (масштаб/проценты/валюта)."""
    return {cls for token in _UNIT_TOKEN_RE.findall(str(text or "").lower())
            for cls in (_unit_class(token),) if cls}

_NUMBER_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)?")
_UNIT_TOKEN_RE = re.compile(
    r"(млрд|млр|млн|мл|трлн|тыс|%|процент\w*|п\.п\.?|пункт\w*|руб\w*|"
    r"доллар\w*|долл\.?|юан\w*|фунт\w*|евро|\$|€|£|₽|"
    # валюты/проценты словами в источниках: «658 billion dollars» — это млрд
    # долларов, а не «billion» без валюты (иначе верный источник = расхождение)
    r"dollars?|euros?|pounds?|cents?|rubles?|percentage|"
    r"billion|trillion|million|thousand|percent|pct|points?|usd|eur|gbp|"
    r"rub|bn|mn)", re.IGNORECASE)


def _numbers_in(text: str) -> set[str]:
    """Нормализованные числа текста (658 / 0,8 → 658 / 0.8)."""
    out: set[str] = set()
    for raw in _NUMBER_TOKEN_RE.findall(str(text or "").lower()):
        out.add(raw.replace(",", ".").lstrip("0") or "0")
    return out


def _directions(text: str) -> tuple[bool, bool]:
    """(есть_падение, есть_рост) по морфологии направления."""
    low = str(text or "").lower()
    return bool(_DOWN_RE.search(low)), bool(_UP_RE.search(low))


def _opposite_direction(claim_low: str, text_low: str) -> bool:
    """Источник утверждает ПРОТИВОПОЛОЖНОЕ направление тезиса.

    Общая морфология, а не закрытый список пар: «вырос» против
    «подешевел/снизился» распознаётся так же, как «упал» против «rose».
    Двунаправленный текст (в источнике есть и рост, и падение) опровержением
    не считается — консервативно.
    """
    c_down, c_up = _directions(claim_low)
    t_down, t_up = _directions(text_low)
    if c_down and not c_up and t_up and not t_down:
        return True
    if c_up and not c_down and t_down and not t_up:
        return True
    return False


@dataclasses.dataclass(frozen=True)
class ClaimRelevance:
    """Оценка одного источника относительно одного claim (§3.3)."""
    role: str
    score: int = 0
    word_hits: int = 0
    number_hits: int = 0
    entity_hit: bool = False
    opposite: bool = False
    #: тема/сущность совпали, но число тезиса в источнике ДРУГОЕ
    #: (расхождение оценок: «2,8%» против заявленных «3,4%»)
    number_mismatch: bool = False

    @property
    def displayable(self) -> bool:
        return self.role in DISPLAYABLE_EVIDENCE_ROLES

    @property
    def strong(self) -> bool:
        """Источник покрывает ИМЕННО тезис: якорь + совместимые единицы."""
        return self.role == EVIDENCE_ROLE_SUPPORTS and not self.opposite \
            and not self.number_mismatch \
            and (self.entity_hit or self.word_hits >= 2)


def claim_relevance(text: str, *, claim_text: str = "",
                    anchor_terms=(), metrics=(), entities=(),
                    claim_type: str = "") -> ClaimRelevance:
    """Релевантность источника КОНКРЕТНОМУ claim (§3.3), затем пригодность.

    Порядок: сначала связь с тезисом (якоря: числа/метрики тезиса, латинские
    имена и тикеры, содержательные термины), и только потом роль источника.
    Смысл: «золото» в статье о золоте не подтверждает потерю капитализации
    Alphabet; заголовок о падении индекса не подтверждает конкретную сумму.

    Reviewer F1: совпадение числа без совместимой ЕДИНИЦЫ/ВАЛЮТЫ не является
    подтверждением («$658 млрд» ≠ «$658 million»), а тезис-причина
    (`claim_type="cause"`) подтверждается только при наличии причинной связки
    в источнике.

    Детерминированно, без LLM. Никогда не бросает.
    """
    try:
        body = str(text or "")
        body_low = body.lower()
        claim_low = str(claim_text or "").lower()
        if not body_low.strip():
            return ClaimRelevance(role=EVIDENCE_ROLE_IRRELEVANT)
        vocab = _term_keys(claim_text)
        body_keys = _term_keys(body)
        matched = vocab & body_keys
        word_hits = sum(1 for k in matched if not k.isdigit())
        body_numbers = _numbers_in(body)
        claim_numbers = {n for m in (metrics or ())
                         for n in _numbers_in(str(m))}
        number_hits = len(claim_numbers & body_numbers)
        anchors = [str(a).lower() for a in (anchor_terms or ()) if str(a)]
        entity_hit = any(a and a in body_low for a in anchors)
        entity_hit = entity_hit or any(
            str(e).lower() in body_low for e in (entities or ())
            if len(str(e)) >= 3)
        opposite = _opposite_direction(claim_low, body_low) if claim_low else False
        # §F1: единицы/валюта тезиса против источника
        claim_classes = _unit_classes(" ".join(str(m) for m in
                                               (metrics or ())))
        body_classes = _unit_classes(body)
        units_ok = (not claim_classes) or claim_classes <= body_classes
        units_conflict = bool(claim_classes and not units_ok)
        causal_missing = (str(claim_type or "") == "cause"
                          and not _CAUSAL_RE.search(body))

        def _result(role: str, *, mismatch: bool = False) -> ClaimRelevance:
            return ClaimRelevance(role=role, score=len(matched) + number_hits,
                                  word_hits=word_hits, number_hits=number_hits,
                                  entity_hit=entity_hit, opposite=opposite,
                                  number_mismatch=mismatch)

        if claim_numbers:
            if number_hits and units_ok:
                if word_hits >= 1 or entity_hit:
                    if causal_missing and not opposite:
                        return _result(EVIDENCE_ROLE_QUALIFIES)
                    return _result(EVIDENCE_ROLE_CONTRADICTS if opposite
                                   else EVIDENCE_ROLE_SUPPORTS)
                # совпало только число — совпадение, а не доказательство
                return _result(EVIDENCE_ROLE_BACKGROUND)
            if number_hits and units_conflict:
                # то же число, но другая единица/масштаб/валюта — расхождение
                return _result(EVIDENCE_ROLE_QUALIFIES, mismatch=True)
            if entity_hit or word_hits >= 2:
                # событие/тема те же, но заявленного числа в источнике нет:
                # либо другой период/методология (не подтверждение), либо
                # другое число С ТОЙ ЖЕ единицей — расхождение оценок.
                numbers_differ = bool(body_numbers) and bool(
                    claim_classes & body_classes)
                return _result(EVIDENCE_ROLE_QUALIFIES,
                               mismatch=numbers_differ and not opposite)
            if word_hits == 1 or entity_hit:
                return _result(EVIDENCE_ROLE_BACKGROUND)
            return _result(EVIDENCE_ROLE_IRRELEVANT)
        if entity_hit and (word_hits >= 1 or opposite):
            if causal_missing and not opposite:
                return _result(EVIDENCE_ROLE_QUALIFIES)
            return _result(EVIDENCE_ROLE_CONTRADICTS if opposite
                           else EVIDENCE_ROLE_SUPPORTS)
        if word_hits >= 2:
            if causal_missing and not opposite:
                return _result(EVIDENCE_ROLE_QUALIFIES)
            return _result(EVIDENCE_ROLE_CONTRADICTS if opposite
                           else EVIDENCE_ROLE_SUPPORTS)
        if word_hits == 1 or entity_hit:
            return _result(EVIDENCE_ROLE_BACKGROUND)
        return _result(EVIDENCE_ROLE_IRRELEVANT)
    except Exception:      # pragma: no cover — оценка не рвёт контур
        logger.debug("[search_aggregator] claim relevance failed", exc_info=True)
        return ClaimRelevance(role=EVIDENCE_ROLE_IRRELEVANT)


_PRIMARY_HOST_RE = re.compile(r"\.(?:gov(?:\.[a-z]{2})?|edu|mil)(?:/|:|$)",
                              re.IGNORECASE)
_RESEARCH_HOST_RE = re.compile(
    r"(pubmed|ncbi\.nlm|doi\.org|arxiv\.org|medrxiv|biorxiv|jstor\.org|"
    r"nature\.com|science\.org|sciencedirect|springer\.com|wiley\.com|"
    r"oup\.com|thelancet|bmj\.com|nejm\.org|jamanetwork|cell\.com|"
    r"plos\.org|frontiersin|mdpi\.com|tandfonline|scielo|elibrary\.ru|"
    r"cyberleninka|e-library)", re.IGNORECASE)
_RESEARCH_PATH_RE = re.compile(
    r"/(?:doi|pmc|pubmed|abstract|articles?/|paper|records?)/", re.IGNORECASE)
_REFERENCE_HOST_RE = re.compile(
    r"(wikipedia\.org|britannica\.com|academic\.ru|encyclopedia)", re.IGNORECASE)


def classify_source_kind(url: str) -> str:
    """Тип источника по лёгким признакам домена/структуры (§3.4, без LLM):
    primary (официальные gov/edu/mil) | research (журналы/препринты/DOI) |
    reference (энциклопедии/справочники) | secondary (пересказ, дефолт).
    Классифицируется ДОСТУПНОСТЬ источника, не истинность утверждений."""
    low = str(url or "").lower()
    if not low.startswith(("http://", "https://")):
        return "secondary"
    # research раньше primary: pubmed.ncbi.nlm.nih.gov — индекс
    # исследований, хотя домен формально gov
    if _RESEARCH_HOST_RE.search(low) or _RESEARCH_PATH_RE.search(low):
        return "research"
    if _PRIMARY_HOST_RE.search(low):
        return "primary"
    if _REFERENCE_HOST_RE.search(low):
        return "reference"
    return "secondary"



class SearchAggregator:
    def __init__(
        self,
        tavily_api_key: str = settings.TAVILY_API_KEY,
        exa_api_key: str = settings.EXA_API_KEY,
        tavily_timeout: float = 5.0,      # ТЗ: таймаут >5с → фолбек (D105)
        exa_timeout: float = 10.0,        # Exa медленнее (живой краулинг)
        ddg_timeout: float = 15.0,
        max_results: int = 5,
    ) -> None:
        # Миграция read-пути: ключи из админки (keys.tavily/exa) — в приоритете
        # над env; в дефолтах бейкдились бы при импорте.
        self._tavily_api_key = hot.get("keys.tavily_api_key",
                                       tavily_api_key) or ""
        self._exa_api_key = hot.get("keys.exa_api_key", exa_api_key) or ""
        self._tavily_timeout = tavily_timeout
        self._exa_timeout = exa_timeout
        self._ddg_timeout = ddg_timeout
        self._max_results = max_results
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Ленивый общий httpx-клиент (прецедент LLMClient._get_client)."""
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def search(self, query: str, max_symbols: int,
                     relevance_terms: list[str] | None = None,
                     timeout_budget: float | None = None,
                     trace: dict | None = None) -> str:
        """Каскад: Tavily → Exa → DDG. Возвращает агрегированный текст
        (обрезка до max_symbols). Raises AllSearchEnginesFailedException.

        ``relevance_terms`` (FC-EVIDQ, §3.4): опциональные термины запроса —
        непустая, но содержательно нерелевантная выдача уровня (overlap-
        эвристика без ранжировщика) не останавливает каскад, поиск
        продолжается следующими провайдерами. None → прежнее поведение.

        ``timeout_budget`` (P0-FACTCHECK §3.3): остаток общего бюджета
        запроса в секундах — per-engine таймауты урезаются до остатка,
        чтобы один медленный провайдер не съедал бюджет следующих запросов.
        None → прежние таймауты.

        ``trace`` (ASAP-FC-EVIDENCE-STYLE-02 §6): необязательный словарь для
        телеметрии хода — заполняется фактическим ``provider``/``latency_ms``/
        ``reason``/``levels``. None → прежнее поведение байт-в-байт."""
        levels: list[tuple[str, Callable[[str], Awaitable[str]], str | None]] = [
            ("tavily", self._search_tavily, self._tavily_api_key),
            ("exa", self._search_exa, self._exa_api_key),
            ("ddg", self._search_ddg, None),
        ]
        started_budget = time.monotonic()
        # §5.1: причины уровней собираются; итог — самая информативная
        # (ответившие провайдеры с пустой/нерелевантной выдачей честнее
        # «недоступно»: ddg-уровень без библиотеки не затирает причину
        # ответивших уровней)
        reasons: list[str] = []

        def _left() -> float | None:
            if timeout_budget is None:
                return None
            return float(timeout_budget) - (time.monotonic() - started_budget)

        def _accepts_budget(fn) -> bool:
            """F1: бюджет передаётся только тем движкам, что его принимают.

            Реальные уровни (`_search_tavily/_search_exa/_search_ddg`)
            объявляют параметр; сторонние/подменённые callable с одной
            `query` не должны ломать каскад (прод-инцидент: Tavily упал →
            Exa/DDG получали TypeError и «поиск недоступен»)."""
            try:
                params = inspect.signature(fn).parameters
            except (TypeError, ValueError):      # pragma: no cover
                return False
            return ("timeout_budget" in params
                    or any(p.kind is inspect.Parameter.VAR_KEYWORD
                           for p in params.values()))

        for name, fn, key in levels:
            if key is not None and not key.strip():
                # D104: пустой ключ — уровень каскада отключён
                logger.info("SearchAggregator: level skipped (no api key) | provider=%s", name)
                continue
            left = _left()
            if left is not None and left <= 0.2:
                raise AllSearchEnginesFailedException(
                    f"search budget exhausted (tavily → exa → ddg) | "
                    f"query={query!r}", reason="budget")
            started = time.monotonic()
            try:
                # бюджет есть → передаём остаток (реальный агрегатор
                # урезает per-engine таймаут); бюджета нет или движок его
                # не принимает → прежний одноаргументный вызов
                if left is not None and _accepts_budget(fn):
                    text = await fn(query, timeout_budget=left)
                else:
                    text = await fn(query)
                if not text.strip():
                    raise ValueError("empty result")
                if relevance_terms and not is_relevant_result(
                        text, relevance_terms):
                    # §3.4: URL/непустой текст ≠ доказательство — пробуем
                    # следующего провайдера
                    raise ValueError(
                        "irrelevant results (low query overlap)")
                latency_ms = (time.monotonic() - started) * 1000.0
                logger.info(
                    "SearchAggregator: level ok | provider=%s | latency_ms=%.0f | chars=%d",
                    name, latency_ms, len(text),
                )
                if trace is not None:
                    trace.update({
                        "provider": name, "reason": "ok",
                        "latency_ms": round(latency_ms, 1),
                        "levels": list(reasons) + [f"{name}:ok"]})
                return self._truncate(text, max_symbols)
            except Exception as exc:
                # §5.1/§5.3: реальная причина уровня — в техническом логе
                cause = level_failure_reason(exc)
                logger.warning(
                    "SearchAggregator: level failed → fallback | provider=%s | "
                    "cause=%s | error=%s",
                    name, cause, exc,
                )
                reasons.append(cause)
                if trace is not None:
                    trace.update({"provider": name, "reason": cause,
                                  "latency_ms": round(
                                      (time.monotonic() - started) * 1000.0, 1),
                                  "levels": list(reasons)})
        if trace is not None:
            trace.update({"provider": "", "reason": "provider_error",
                          "levels": list(reasons)})
        raise AllSearchEnginesFailedException(
            f"all search engines failed (tavily → exa → ddg) | query={query!r}",
            reason=_most_informative_reason(reasons),
        )

    async def search_relevant(self, query: str, max_symbols: int,
                              relevance_terms: list[str] | None = None,
                              timeout_budget: float | None = None,
                              trace: dict | None = None
                              ) -> str:
        """Явный relevance-вход контура фактчека (FC-EVIDQ): тот же каскад
        с проверкой содержательной релевантности выдачи. Существующие
        вызовы `search()` (сводки и пр.) не меняются."""
        return await self.search(query, max_symbols,
                                 relevance_terms=relevance_terms,
                                 timeout_budget=timeout_budget, trace=trace)


    async def close(self) -> None:
        """Закрыть ленивый httpx-клиент (on_shutdown). DDG — только внутри вызова."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def log_config(self) -> None:
        """D104: WARNING-и пустых ключей при старте (вызов из bot.py on_startup)."""
        if not (self._tavily_api_key or "").strip():
            logger.warning("Tavily level disabled: TAVILY_API_KEY is empty")
        if not (self._exa_api_key or "").strip():
            logger.warning("Exa level disabled: EXA_API_KEY is empty")

    # ── Уровни каскада ────────────────────────────────────────

    async def _search_tavily(self, query: str,
                             timeout_budget: float | None = None) -> str:
        """POST api.tavily.com/search (Bearer); raises on failure."""
        client = self._get_client()
        timeout = self._tavily_timeout
        if timeout_budget is not None:
            timeout = max(0.5, min(timeout, float(timeout_budget)))
        response = await client.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {self._tavily_api_key}"},
            json={
                "query": query,
                "max_results": self._max_results,
                "search_depth": "basic",
            },
            timeout=httpx.Timeout(timeout),
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results") or []
        if not results:
            raise ValueError("tavily: empty results")
        pairs = [
            (
                str(item.get("title") or ""),
                str(item.get("content") or ""),
                str(item.get("url") or ""),
            )
            for item in results
        ]
        return self._format_hits(pairs)

    async def _search_exa(self, query: str,
                          timeout_budget: float | None = None) -> str:
        """POST api.exa.ai/search (x-api-key); raises on failure."""
        client = self._get_client()
        timeout = self._exa_timeout
        if timeout_budget is not None:
            timeout = max(0.5, min(timeout, float(timeout_budget)))
        response = await client.post(
            EXA_URL,
            headers={"x-api-key": self._exa_api_key},
            json={
                "query": query,
                "numResults": self._max_results,
                "type": "auto",
                "contents": {"text": {"maxCharacters": 2000}},
            },
            timeout=httpx.Timeout(timeout),
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results") or []
        if not results:
            raise ValueError("exa: empty results")
        pairs = []
        for item in results:
            title = str(item.get("title") or "")
            url = str(item.get("url") or "")
            text = item.get("text")
            highlights = item.get("highlights")
            summary = item.get("summary")
            snippet = text or (highlights[0] if highlights else None) or summary or ""
            pairs.append((title, str(snippet), url))
        return self._format_hits(pairs)

    def _run_ddg_text(self, query: str,
                      timeout_budget: float | None = None) -> list[dict]:
        """Sync-блок DDG (библиотека 8.x sync-only) — исполняется в executor."""
        if DDGS is None:  # pragma: no cover
            raise RuntimeError("duckduckgo_search is not installed")
        timeout = self._ddg_timeout
        if timeout_budget is not None:
            timeout = max(1.0, min(timeout, float(timeout_budget)))
        with DDGS(timeout=int(max(1.0, timeout))) as ddgs:
            return ddgs.text(query, max_results=self._max_results)

    async def _search_ddg(self, query: str,
                          timeout_budget: float | None = None) -> str:
        """Уровень 3 — DuckDuckGo (без ключа). AsyncDDGS удалён из 8.x (PR#268):
        sync DDGS через asyncio.to_thread (официальная рекомендация)."""
        results = await asyncio.to_thread(self._run_ddg_text, query,
                                          timeout_budget)
        if not results:
            raise ValueError("ddg: empty results")
        pairs = [
            (
                str(item.get("title") or ""),
                str(item.get("body") or ""),
                str(item.get("href") or ""),
            )
            for item in results
        ]
        return self._format_hits(pairs)

    # ── Общий формат ──────────────────────────────────────────

    @staticmethod
    def _format_hits(title_snippet_pairs: list[tuple[str, str, str]]) -> str:
        """Блок f"{title}\n{snippet}\n{url}" на результат; блоки через \n\n."""
        return "\n\n".join(
            f"{title}\n{snippet}\n{url}" for title, snippet, url in title_snippet_pairs
        )

    @staticmethod
    def _truncate(text: str, max_symbols: int) -> str:
        """Жёсткое ограничение без разрыва юникода (срез по символам)."""
        return text[:max_symbols]
