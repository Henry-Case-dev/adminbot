"""CFG-06 06G.3 — локальный tool «кто это сказал» (атрибуционный спор).

Спор «кто конкретно это сказал в чате» (клейм вида «X сказал Y») решается
ЛОКАЛЬНО по широкому контексту чата (ConversationContext из v2, W1) ДО
любого платного внешнего поиска:

* ``detect_attribution_claim`` — детерминированное (БЕЗ LLM) распознавание
  атрибуционного клейма: автор (участник) + речевой глагол + тезис;
* ``mention_is_participant`` — спор про «кто в чате» имеет смысл только для
  имён участников среза; публичные фигуры («Путин сказал …») идут обычным
  веб-контуром без изменений (байт-паритет);
* ``resolve_attribution`` — поиск реплики-источника: автор совпадает с
  участником И текст сообщения содержит ДОСЛОВНЫЙ фрагмент тезиса →
  ``AttributionMatch`` (автор, цитата, дата/время, якоря message_id);
* ``attribution_evidence_ref``/``attach_attribution_evidence`` — привязка
  evidence к автору/цитате/контексту (ср. VERIFIED 06D.4: тезис → выдержка
  → источник; source_kind="chat", url=None — внешней ссылки нет);
* ``external_safe_claim``/``with_external_claim`` — privacy (06G.3): в
  веб-запросы уходит только тезис, имена участников (включая упомянутого
  автора) вычищены существующим planner-фильтром `_strip_privacy` (W4);

Честный отказ: совпадения нет → вызывающий отвечает готовой репликой
(``FACTCHECK_ATTRIBUTION_MISS_PHRASES``) БЕЗ домыслов и БЕЗ внешнего поиска
(reason_code ``attribution_not_found``); реплика найдена → тезис
проверяется по существу стандартным контуром (план/поиск v2 уже есть).

Интеграция — только за ``FACTCHECK_PIPELINE_V2_ENABLED`` (оркестратор
``_run_inner`` и tool-маршрут ``fact_check`` v2-ветка); OFF → модуль не
вызывается (байт-паритет 2.58.98). Второго пайплайна нет: стадии —
детерминированные функции над замороженными схемами W1/W3.

Границы: рендер/доставка не меняются (EvidenceMap — по W3-фризу;
chat-ref без URL не даёт ссылки и не ломает renderer).

TEST-LIFECYCLE: CONTRACT owner=CFG-06
  (tests/test_factcheck_attribution_cfg06.py: found/miss/privacy/OFF).
"""
from __future__ import annotations

import dataclasses
import datetime
import logging
import re

from services.factcheck_orchestrator import EvidenceRef

logger = logging.getLogger(__name__)

ATTRIBUTION_VERSION = "fat1"

# ── DTO ──────────────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class AttributionClaim:
    """Распознанный атрибуционный клейм («X сказал Y»)."""
    author_mention: str     # упоминание автора в клейме (как сказано)
    thesis_text: str        # содержательная часть — что именно сказал
    verb: str               # речевой глагол (сказал/написал/…)
    raw_claim: str


@dataclasses.dataclass(frozen=True)
class AttributionMatch:
    """Найденная ЛОКАЛЬНО реплика-источник (06G.3: автор/цитата/дата)."""
    author: str
    quote: str              # дословный фрагмент реплики (свёрнутый пробел)
    message_text: str
    timestamp: int | None
    tg_message_id: int | None
    message_id: int | None
    chat_id: int | None


# ── Детерминированное распознавание (БЕЗ LLM) ────────────────────────────────

# Стемы речевых глаголов (морфология: род/число/время покрываются \w*).
_SPEECH_VERB_STEMS = (
    "сказа", "говор", "спрашива", "написа", "писа", "утвержда", "заяви",
    "сообщи", "спроси", "ответи", "отвеча", "отмет", "добави", "объясни",
    "рассказа", "поведа", "призна", "подтверди", "озвуч", "упомяну",
    "предупреди", "пообеща", "обеща", "крича",
)
_VERB_ALT = "|".join(re.escape(s) for s in _SPEECH_VERB_STEMS)

# Автор: один токен (любой регистр; ник/имя/фамилия) + до двух
# капитализированных доп. токенов («Вася Пупкин»). Местоимения («он», «ты»)
# короче 3 символов не матчатся — консервативно.
_AUTHOR_TOK = r"[A-Za-zА-ЯЁа-яё0-9_@]{3,30}"
_ATTR_CLAIM_RE = re.compile(
    r"^\s*(?:ну\s+|да\s+|и\s+|это\s+)?"
    r"(?P<author>" + _AUTHOR_TOK +
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-ЯЁа-яё0-9_]{2,29}){0,2})"
    r"\s+(?:не\s+)?(?P<verb>(?:" + _VERB_ALT + r")\w*)"
    r"(?P<tail>[\s\S]+)$",
    re.IGNORECASE)
_QUOTED_TAIL_RE = re.compile(r"[«\"]([^«»\"]{8,400})[»\"]")
_LEADING_FILL_RE = re.compile(r"^[\s,:;—–-]+")
_LEADING_CONN_RE = re.compile(r"^(?:что|будто|типа|мол)\s+", re.IGNORECASE)
_WORD_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)

# Слишком короткий/бессодержательный тезис — атрибуция не ищется
# (защита от ложных «подтверждений» на слове из трёх букв).
_MIN_THESIS_CHARS = 8
_MIN_THESIS_TOKENS = 2
_MIN_QUOTE_CHARS = 8

# Нормализация матча: ё→е, тире→«-», регистр/пробелы. Длина строки НЕ
# меняется → индексы совпадают со «свёрнутым» оригиналом (дословный фрагмент).
_DASH_TABLE = str.maketrans({"—": "-", "–": "-", "−": "-", "ё": "е",
                             "Ё": "Е"})
_EDGE_TRIM = " \t\r\n«»\"'.,!?;:()…-"


def _norm_for_match(text: str) -> str:
    collapsed = " ".join(str(text or "").split())
    return collapsed.translate(_DASH_TABLE).lower()


def _norm_name(name: str) -> str:
    n = " ".join(str(name or "").split()).translate(_DASH_TABLE).lower()
    return n.lstrip("@").strip(_EDGE_TRIM)


def _strip_edges(text: str) -> str:
    return str(text or "").strip(_EDGE_TRIM)


def _extract_thesis(tail: str) -> str:
    """Тезис из хвоста клейма: кавычки приоритетны, связки «что/мол» срезаны."""
    t = _LEADING_FILL_RE.sub("", str(tail or ""))
    t = _LEADING_CONN_RE.sub("", t, count=1).strip()
    if not t:
        return ""
    quoted = _QUOTED_TAIL_RE.search(t)
    if quoted:
        return quoted.group(1).strip()
    return t


def detect_attribution_claim(claim_text: str | None
                             ) -> AttributionClaim | None:
    """Клейм → ``AttributionClaim`` (автор+тезис) или None.

    Детерминированно, без LLM, никогда не бросает; не матчатся местоимения
    (<3 симв.), реплики без тезиса и слишком короткие тезисы."""
    claim = str(claim_text or "").strip()
    if not claim:
        return None
    try:
        match = _ATTR_CLAIM_RE.match(claim)
        if match is None:
            return None
        thesis = _extract_thesis(match.group("tail"))
        if len(thesis) < _MIN_THESIS_CHARS:
            return None
        if len(_WORD_RE.findall(thesis)) < _MIN_THESIS_TOKENS:
            return None
        return AttributionClaim(
            author_mention=match.group("author").strip(),
            thesis_text=thesis,
            verb=match.group("verb").strip(),
            raw_claim=claim)
    except Exception:      # pragma: no cover — детерминированный парсер
        logger.warning("[factcheck_attribution] detect failed",
                       exc_info=True)
        return None


# ── Локальная резолюция по ConversationContext ───────────────────────────────

def _author_matches(author: str | None, mention_norm: str) -> bool:
    """Участник совпадает с упоминанием: точное имя или токен-префикс
    («Вася» ↔ «Василий Пупкин», «Вася Пупкин» ↔ «вася»). Никогда не бросает."""
    if not author or not mention_norm:
        return False
    name = _norm_name(author)
    if not name:
        return False
    if name == mention_norm:
        return True
    tokens = name.split()
    for mt in mention_norm.split():
        for token in tokens:
            if token == mt:
                return True
            if (len(token) >= 3 and len(mt) >= 3
                    and (token.startswith(mt) or mt.startswith(token))):
                return True
    return False


def mention_is_participant(ctx, author_mention: str | None) -> bool:
    """Упоминание — имя участника среза? Спор «кто в чате» иначе не имеет
    смысла: публичные фигуры идут обычным веб-контуром. Fail-open → False."""
    if ctx is None:
        return False
    mention = _norm_name(author_mention)
    if not mention:
        return False
    try:
        return any(_author_matches(m.author, mention)
                   for m in ctx.messages if m.author)
    except Exception:      # pragma: no cover
        return False


def _find_quote(message_text: str, thesis_norm: str) -> str | None:
    """Дословный фрагмент реплики, содержащий тезис (нормализованный
    substring; длины совпадают → индексы валидны для оригинала)."""
    hay = _norm_for_match(message_text)
    pos = hay.find(thesis_norm)
    if pos < 0:
        return None
    collapsed = " ".join(str(message_text or "").split())
    return collapsed[pos:pos + len(thesis_norm)].strip(_EDGE_TRIM) \
        or collapsed[pos:pos + len(thesis_norm)]


def resolve_attribution(ctx, attribution: AttributionClaim | None
                        ) -> AttributionMatch | None:
    """Найти реплику-источник в срезе: автор — участник с совпадающим именем
    И текст содержит дословный фрагмент тезиса. Совпадения нет → None
    (честный отказ вызывающего, БЕЗ домыслов: реплика другого автора
    атрибуцию НЕ подтверждает). Свежие реплики приоритетны. Не бросает."""
    if ctx is None or attribution is None:
        return None
    try:
        thesis = _strip_edges(_norm_for_match(attribution.thesis_text))
        if len(thesis) < _MIN_QUOTE_CHARS:
            return None
        mention = _norm_name(attribution.author_mention)
        if not mention:
            return None
        candidates = [m for m in ctx.messages
                      if str(m.text or "").strip()
                      and _author_matches(m.author, mention)]
        for m in reversed(candidates):      # свежие первыми
            quote = _find_quote(m.text, thesis)
            if quote:
                return AttributionMatch(
                    author=str(m.author or "").strip(),
                    quote=quote,
                    message_text=" ".join(
                        str(m.text or "").split())[:400],
                    timestamp=m.timestamp,
                    tg_message_id=m.tg_message_id,
                    message_id=m.message_id,
                    chat_id=m.chat_id)
        return None
    except Exception:      # pragma: no cover
        logger.warning("[factcheck_attribution] resolve failed",
                       exc_info=True)
        return None


# ── Структурный evidence (ср. 06D.4: тезис → выдержка → источник) ────────────

def format_match_stamp(timestamp: int | None) -> str:
    """Человекочитаемая дата/время реплики (UTC); нет даты → '' (не выдумываем)."""
    if not timestamp:
        return ""
    try:
        return datetime.datetime.fromtimestamp(
            int(timestamp), datetime.timezone.utc).strftime(
            "%d.%m.%Y %H:%M UTC")
    except (ValueError, OSError, OverflowError, TypeError):
        return ""


def attribution_evidence_ref(match: AttributionMatch) -> EvidenceRef:
    """EvidenceRef атрибуции: support = автор + цитата + дата, url=None
    (локальный источник, внешней ссылки нет → renderer ссылку не строит)."""
    stamp = format_match_stamp(match.timestamp)
    support = f"{match.author}: «{match.quote}»"
    if stamp:
        support = f"{support} [{stamp}]"
    return EvidenceRef(evidence_id="chat-1", url=None,
                       support=support[:400], source_kind="chat",
                       published_at=match.timestamp)


def attach_attribution_evidence(verdict, match: AttributionMatch):
    """Дописать chat-ref в EvidenceMap вердикта (id ``chat-1`` не
    пересекается с ``ev-N`` web-evidence — ссылки вердикта не сдвигаются).
    Любой сбой → вердикт без изменений (never бросает)."""
    try:
        ref = attribution_evidence_ref(match)
        refs = (ref,) + tuple(verdict.evidence.refs)
        from services.factcheck_orchestrator import EvidenceMap
        return dataclasses.replace(
            verdict,
            evidence=EvidenceMap(refs=refs,
                                 allowlist=tuple(r.evidence_id
                                                 for r in refs)))
    except Exception:      # pragma: no cover
        logger.warning("[factcheck_attribution] evidence attach failed",
                       exc_info=True)
        return verdict


# ── Privacy: веб-запросы без участников/цитат приватного чата (06G.3) ────────

def external_safe_claim(claim_text: str | None, ctx,
                        attribution: AttributionClaim | None) -> str:
    """Privacy-версия клейма для внешнего поиска: тезис без атрибуционной
    обвязки; имена участников (включая упомянутого автора) вычищены
    существующим planner-фильтром `_strip_privacy` (W4-инвариант).
    Fail-open → очищаемый тезис/вход. Никогда не бросает."""
    thesis = str(attribution.thesis_text if attribution is not None
                 else claim_text or "").strip()
    authors: list[str] = []
    try:
        if ctx is not None:
            authors.extend(str(m.author) for m in ctx.messages if m.author)
    except Exception:      # pragma: no cover
        pass
    if attribution is not None:
        authors.append(attribution.author_mention)
    try:
        from services.factcheck_planner import _strip_privacy
        clean, _dropped = _strip_privacy(
            thesis, tuple(a for a in authors if a))
    except Exception:      # pragma: no cover — фильтр недоступен
        clean = thesis
    return clean or thesis or str(claim_text or "")


def with_external_claim(envelope, claim_text: str):
    """Frozen-replace envelope: поисковые стадии временной ветки получают
    privacy-клейм (провенанс-поля не меняются). Никогда не бросает."""
    cleaned = str(claim_text or "").strip()
    if not cleaned or envelope is None:
        return envelope
    try:
        if cleaned == envelope.claim_text:
            return envelope
        return dataclasses.replace(envelope, claim_text=cleaned)
    except Exception:      # pragma: no cover
        logger.warning("[factcheck_attribution] envelope replace failed",
                       exc_info=True)
        return envelope
