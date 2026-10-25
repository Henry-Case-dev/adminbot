"""CFG-06 W2 — suitability gate + ContextualClaimResolution (06B, 06J, 06I.6).

Бриф: plans/features/cfg/cfg-06-build-plan.md §W2. Детерминированный
(БЕЗ LLM-вызовов и БЕЗ правок промпт-канонов — граница лейна), многоступенчатый
по 06J.1: ``obvious_checkable → contextual_resolution/expand →
contextual_checkable | genuinely_uncheckable | insufficient_context``.

Ключевые инварианты исходника:

* 06J.1/ADD-1.C2 — изолированно бессмысленное сообщение — ПОВОД проверить
  контекст, не автоматический отказ; ``not_checkable`` — вывод ПОСЛЕ
  исследования доступного контекста.
* 06J.2 — приоритет ошибки: ложный отказ при существующем контекстном тезисе.
  При неуверенности между checkable/no_claim выбирается **checkable**.
* 06J.3/06B.3 — действительно непроверяемое (после контекста) → короткая
  реплика БЕЗ псевдопроверки/поиска; ``insufficient_evidence`` и
  ``not_checkable`` не смешиваются (вердикт-слой не трогается).
* 06J.4/06B.4 — «бессмыслица»/мат НЕ являются regex-блокиратором: структурный
  предикат (числа/даты/фактические сказуемые) делает клейм проверяемым
  независимо от лексики; различаются ``no_claim_after_context`` /
  ``context_unavailable`` / ``checkable_in_context`` /
  ``ambiguous_needs_clarification``.
* 06B.6 — типизированный результат (decision/claim_items/scope/reason_code/
  confidence/target_ref), версия гейта, измеримая точность (корпус W2).
* 06I.6 — target_claim и contextual_claims хранятся РАЗДЕЛЬНО с
  provenance-якорями; чужой тезис не приписывается цели (автор анцедента
  сохраняется).
* 06B.1 — гейт стоит ПОСЛЕ реконструкции контекста и ДО платного поиска;
  выполняется только за флагом (default OFF → прод-путь байт-паритетен).

Границы W2-лейна: маршруты ``no_claim_after_context`` отвечают короткой
готовой репликой (пул smartmodule_phrases, БЕЗ LLM); персона-озвученная
короткая реплика через speech_owner_block — W3 (единый Writer).
"""
from __future__ import annotations

import dataclasses
import logging
import re

from services import temporal_factcheck as tf
from services.factcheck_context import (
    _WIDE_WINDOW_MAX,
    ConversationContext,
    ContextMessage,
    build_wide_context,
    tokenize_for_relevance,
)

logger = logging.getLogger(__name__)

GATE_VERSION = "fsg1"

# ── Типы (06B.2) ─────────────────────────────────────────────────────────────
CHECKABLE_FACTUAL_CLAIM = "checkable_factual_claim"
MIXED_CLAIM = "mixed_claim"
SUBJECTIVE_OPINION = "subjective_opinion"
PERSONAL_PREDICTION = "personal_prediction"
QUESTION_WITHOUT_ASSERTION = "question_without_assertion"
JOKE_IRONY = "joke_irony"
NONSENSE = "nonsense_semantically_incoherent"
INSUFFICIENT_CONTEXT = "insufficient_context"
QUOTE_WITHOUT_CLAIM = "quote_without_claim"
UNSAFE_OR_UNAVAILABLE_TARGET = "unsafe_or_unavailable_target"
CLAIM_TYPES = (CHECKABLE_FACTUAL_CLAIM, MIXED_CLAIM, SUBJECTIVE_OPINION,
               PERSONAL_PREDICTION, QUESTION_WITHOUT_ASSERTION, JOKE_IRONY,
               NONSENSE, INSUFFICIENT_CONTEXT, QUOTE_WITHOUT_CLAIM,
               UNSAFE_OR_UNAVAILABLE_TARGET)

# ── Решения (06J.4 + 06J.1) ─────────────────────────────────────────────────
DECISION_CHECKABLE = "checkable_in_context"
DECISION_NEEDS_CONTEXT = "needs_context"
DECISION_AMBIGUOUS = "ambiguous_needs_clarification"
DECISION_NO_CLAIM = "no_claim_after_context"
DECISION_CONTEXT_UNAVAILABLE = "context_unavailable"
DECISIONS = (DECISION_CHECKABLE, DECISION_NEEDS_CONTEXT, DECISION_AMBIGUOUS,
             DECISION_NO_CLAIM, DECISION_CONTEXT_UNAVAILABLE)

# Scope расхода инструментов (06B.6/06G.7-совместимо).
SCOPE_NONE = "none"
SCOPE_WEB = "web"
SCOPE_CHAT = "chat_history"
SCOPE_WEB_AND_CHAT = "web_and_chat"

_REASON_UNAVAILABLE = "unsafe_or_unavailable_target"
_REASON_NO_CLAIM = "no_claim_after_context"
_REASON_AMBIGUOUS = "multiple_dispute_candidates"
_REASON_NEEDS_CONTEXT = "needs_context_window"
_REASON_CONTEXT_UNAVAILABLE = "context_unavailable"
_REASON_PREDICATE = "obvious_checkable_predicate"
_REASON_HINT = "explicit_check_request"
_REASON_REFERENTIAL = "referential_claim_resolved"
_REASON_FALLBACK = "fallback_checkable"


def suitability_gate_enabled() -> bool:
    """Гейт отката W2 (default OFF → прод-путь байт-паритетен).

    Приоритет: hot ``flags.factcheck_suitability_gate`` → env
    ``FACTCHECK_SUITABILITY_GATE_ENABLED`` → False. Никогда не бросает."""
    try:
        from config.settings import settings
        default = bool(getattr(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED",
                               False))
        from services import hot_config as hot
        return bool(hot.get("flags.factcheck_suitability_gate", default))
    except Exception:      # pragma: no cover — конфиг не должен ронять
        return False


# ── DTO (06B.6) ──────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class ClaimItem:
    """Атомарный тезис с provenance (06B.5/06I.6). Для contextual-источников
    author/anchor — от АНЦЕДЕНТА, не от цели (защита атрибуции)."""
    text: str
    claim_type: str
    verifiable: bool
    source: str                      # literal | reply_to | quote | topic
    author: str | None = None        # автор анцедента (None → цель/неизвестно)
    anchor_tg_message_id: int | None = None
    anchor_chat_id: int | None = None


@dataclasses.dataclass(frozen=True)
class SuitabilityDecision:
    decision: str
    claim_type: str
    claim_items: tuple[ClaimItem, ...]
    scope: str                       # none | web | chat_history | web_and_chat
    reason_code: str | None
    confidence: float
    target_ref: dict
    temporal_hint: bool = False      # (ж) датный клейм → temporal-путь
    gate_version: str = GATE_VERSION


# ── Профилирование цели (stage 1, дешёвое; НИКОГДА не отказ) ────────────────

# Числа/даты/единицы — структурные маркеры проверяемости.
_PREDICATE_NUMERIC_RE = re.compile(
    r"\d|\b(тыс|млн|млрд|процент|руб|доллар|евро|килограмм|км|метр)\w*\b",
    re.IGNORECASE)
# Фактические сказуемые (лексикон утверждений о положении дел, НЕ блок-лист:
# мат/грубость/ирония на результат предиката не влияют).
_PREDICATE_LEXICON = (
    "называ", "явля", "работа", "выпусти", "запрет", "разреши",
    "умер", "побед", "проигр", "родил", "стоил", "стоит", "составл",
    "занял", "выпал", "открыл", "изобрет", "придума", "запуск",
    "построил", "уничтож", "заболел", "вылечил", "повысил", "понизил",
    "вырос", "упал", "подписал", "принял", "отменил", "ввёл", "ввел",
    "убил", "украл", "обманул", "существу", "бывает", "заража", "лечит",
    "помогает", "вредит", "убива", "опроверг", "подтверд", "доказал",
    "содержит", "содерж",
    "превыш", "ниже", "выше", "больше", "меньше", "самый", "первый",
    "последний", "единственный", "никогда", "всегда", "ни один", "каждый",
    "официально", "по данным", "по статистике", "рекорд", "чемпион",
)
# Субъективные маркеры (мнение/оценка).
_SUBJECTIVE_RE = re.compile(
    r"(по-моему|мне (кажется|нравится|не нравится)|считаю, что|думаю, что|"
    r"(самый |самая )?(лучш|хуж|отвратительн|прекрасн|ужасн|мерзк)\w*|"
    r"(красив|уродлив|вкусн|глуп|умн)\w*)", re.IGNORECASE)
# Будущее/предсказание.
_PREDICTION_RE = re.compile(
    r"\b(будет|будут|станет|станут|выиграет|победит|предскаж|"
    r"через \d+ ?(лет|года|год|месяц|дней))\b", re.IGNORECASE)
# Референциальность/эллиптичность (повод для контекста, не отказ).
_REFERENTIAL_PRONOUN_RE = re.compile(
    r"^(ну и )?(что|как) (там|тут|с этим)|"
    r"^(да ладно|ну да|конечно|ага)[.!?]*$|"
    r"\b(это|этот|эта|эти|тот|она|он|они|там)\b", re.IGNORECASE)
_QUESTION_RE = re.compile(r"\?")
# Дискуссионные маркеры (вокруг спорного тезиса; для «ну и что там?»).
_DISPUTE_MARKER_RE = re.compile(
    r"\b(бред|фейк|неправда|неправ|врань[её]|ложь|правда|точно|не верю|"
    r"неверю|пруф|источник|чушь|да ну|серьёзно|серьезно|вброс|ботва|"
    r"конспиролог|глубоко)\b", re.IGNORECASE)
_QUOTE_RE = re.compile(r"[«\"]([^«»\"]{12,})[»\"]|^>\s?(.{12,})", re.M)
# Копула/категоризация («X — это Y», «дрожжи это грибы») — структурный
# предикат: сарказм/ирония с проверяемым ядром не становится «бессмыслицей»
# (06B.4/06J.2).
_COPULA_RE = re.compile(r"\bэто\b|\s[—–]\s|\s-\s", re.IGNORECASE)


def _has_predicate(text: str) -> bool:
    """Структурный признак проверяемости: числа/даты/сказуемое/копула/цитата.
    Копула («X — это Y») засчитывается только при ≥2 содержательных токенах:
    реакции «это бред» предикатами не становятся."""
    clean = str(text or "").strip()
    if not clean:
        return False
    if _PREDICATE_NUMERIC_RE.search(clean):
        return True
    low = clean.lower()
    for marker in _PREDICATE_LEXICON:
        if marker in low:
            return True
    if _COPULA_RE.search(clean):
        content = [t for t in tokenize_for_relevance(clean) if t != "это"]
        if len(content) >= 2:
            return True
    if _QUOTE_RE.search(clean):
        return True
    return False


def _is_subjective(text: str) -> bool:
    return bool(_SUBJECTIVE_RE.search(str(text or "")))


def _is_prediction(text: str) -> bool:
    return bool(_PREDICTION_RE.search(str(text or "")))


def _is_referential(text: str) -> bool:
    """Референциальная/эллиптичная цель: содержание — в контексте."""
    clean = str(text or "").strip()
    if not clean:
        return False
    if tf.is_referential_claim(clean):
        return True
    tokens = tokenize_for_relevance(clean)
    if len(tokens) <= 2 and _REFERENTIAL_PRONOUN_RE.search(clean):
        return True
    return False


def _classify_literal(text: str) -> str:
    """06B.2-тип по структуре (контекст затем уточняет решение)."""
    clean = str(text or "").strip()
    if not clean:
        return UNSAFE_OR_UNAVAILABLE_TARGET
    predicate = _has_predicate(clean)
    subjective = _is_subjective(clean)
    if predicate and subjective:
        return MIXED_CLAIM
    if predicate:
        return CHECKABLE_FACTUAL_CLAIM
    if _is_prediction(clean):
        return PERSONAL_PREDICTION
    if subjective:
        return SUBJECTIVE_OPINION
    if _QUESTION_RE.search(clean):
        return QUESTION_WITHOUT_ASSERTION
    if _is_referential(clean):
        # Референциальная эллиптика без маркеров — повод для контекста;
        # тип остаётся «вопрос без утверждения» до резолюции (06J.1).
        return QUESTION_WITHOUT_ASSERTION
    return NONSENSE


def _split_atomic(claim_text: str) -> list[str]:
    """Атомизация (06B.5): предложения + противопоставления «, но/однако/хотя».
    Детерминированно; ругань частью тезиса НЕ становится."""
    raw = re.split(r"(?<=[.!?;])\s+|,\s(?:но|однако|хотя)\s+",
                   str(claim_text or ""), flags=re.IGNORECASE)
    parts = []
    for chunk in raw:
        chunk = str(chunk or "").strip()
        if len(chunk) >= 4:
            parts.append(chunk)
    return parts or ([claim_text.strip()] if claim_text.strip() else [])


# ── Stage 2: контекстная резолюция (06I.6) ──────────────────────────────────

_MIN_CONTEXT_MESSAGES = 5
_AMBIGUITY_RATIO = 1.6
_AMBIGUITY_MARGIN = 2.0
_MIN_TOPIC_SCORE = 2.0

# Лёгкий стемминг для сопоставления темы (русская морфология: живой/живым,
# вирус/вирусом). Только для резолюции гейта; W1-токенайзер не меняется.
_STEM_SUFFIX2 = ("ом", "ем", "ых", "их", "ую", "юю", "ая", "яя", "ой", "ый",
                 "ий", "ам", "ми", "ах", "ов", "ет", "ут", "ют", "ся", "сь")
_STEM_VOWELS = "аеёиоуыяюийъь"


def _stems(text: str) -> set[str]:
    stems = set()
    for token in tokenize_for_relevance(text):
        t = token
        while len(t) > 5 and t[-2:] in _STEM_SUFFIX2:
            t = t[:-2]
        if len(t) > 4 and t[-1] in _STEM_VOWELS:
            t = t[:-1]
        stems.add(t)
    return stems


def _dispute_scores(ctx: ConversationContext,
                    probe_tokens: set[str]
                    ) -> list[tuple[ContextMessage, float]]:
    """Кандидаты-анцеденты по СТЕММАМ (морфология: живой/живым): пересечение
    стеммов зонда цели/хинта со стеммами сообщения. Реакции-односложки
    («это бред») не становятся тезисом: кандидат обязан иметь структурный
    предикат или ≥6 содержательных токенов."""
    scored: list[tuple[ContextMessage, float]] = []
    messages = list(ctx.messages)
    df: dict[str, int] = {}
    stemmed = [(m, _stems(m.text)) for m in messages]
    for _m, stems in stemmed:
        for stem in stems:
            df[stem] = df.get(stem, 0) + 1
    for m, stems in stemmed:
        if m.tg_message_id == ctx.target_tg_message_id:
            continue
        overlap = stems & probe_tokens
        if not overlap:
            continue
        if not (_has_predicate(m.text) or len(stems) >= 6):
            continue
        score = 0.0
        for _stem in overlap:
            score += 1.0 + 1.0 / max(1, df.get(_stem, 1))
        if score > 0:
            scored.append((m, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def _dominant_dispute(ctx: ConversationContext
                      ) -> tuple[ContextMessage | None, float, float]:
    """Доминирующий спор по ДИСКУССИОННЫМ маркерам (для референциальных
    целей с пустым зондом — «ну и что там?»). Кандидат-тезис обязан иметь
    структурный предикат (реакции «это бред» тезисами не становятся);
    вес = маркеры в нём + маркеры/число прямых ответов.
    → (сообщение|None, top_score, second_score)."""
    messages = [m for m in ctx.messages
                if m.tg_message_id != ctx.target_tg_message_id
                and str(m.text or "").strip()]
    if not messages:
        return None, 0.0, 0.0
    replies_to: dict[int, int] = {}
    for m in messages:
        if m.reply_to_tg_id:
            replies_to[m.reply_to_tg_id] = replies_to.get(
                m.reply_to_tg_id, 0) + 1
    candidates = [m for m in messages
                  if _has_predicate(m.text)
                  or len(tokenize_for_relevance(m.text)) >= 6]
    if not candidates:
        return None, 0.0, 0.0
    scored: list[tuple[ContextMessage, float]] = []
    for m in candidates:
        score = len(_DISPUTE_MARKER_RE.findall(str(m.text or ""))) * 2.0
        score += replies_to.get(m.tg_message_id, 0) * 1.5
        score += len(tokenize_for_relevance(m.text)) / 20.0
        if _has_predicate(m.text):
            score += 1.0
        scored.append((m, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    top_msg, top_score = scored[0]
    second = scored[1][1] if len(scored) > 1 else 0.0
    if top_score < 2.0:
        return None, top_score, second
    return top_msg, top_score, second


def _replied_tg(ctx: ConversationContext) -> int | None:
    """tg-цель, на которую отвечает ЦЕЛЕВОЕ сообщение (reply_to таргета)."""
    for m in ctx.messages:
        if m.tg_message_id == ctx.target_tg_message_id:
            return m.reply_to_tg_id
    return None


# ── Уточнение владельца №2 (25.10.2026): пустая цель → обязательный контекст ─
# «В цели ничего» — не отказ: проверяются reply-цепочка и окно 200–300
# сообщений (W1), и только потом возможен честный отказ с указанием, что
# именно проверено. Новых механизмов нет: reuse W1 ContextMessage + предикат.

_CONTEXT_CLAIM_MIN_CHARS = 8
_CONTEXT_CLAIM_MIN_TOKENS = 6


@dataclasses.dataclass(frozen=True)
class ContextClaim:
    """Найденный в окружении тезис-кандидат (цель — только точка входа)."""
    text: str
    source: str                      # reply_to | window
    author: str | None = None
    tg_message_id: int | None = None


@dataclasses.dataclass(frozen=True)
class ContextProbe:
    """Результат обязательной проверки окружения для пустой цели."""
    feed: str                        # готовый <chat_context> (+ цепочка)
    claim: ContextClaim | None
    window_messages: int
    window_before: int
    window_after: int
    chain_len: int = 0


def _claim_like_text(text: str) -> bool:
    """Структурный признак проверяемого утверждения (тот же предикат W2)."""
    clean = str(text or "").strip()
    if len(clean) < _CONTEXT_CLAIM_MIN_CHARS:
        return False
    return (_has_predicate(clean)
            or len(tokenize_for_relevance(clean)) >= _CONTEXT_CLAIM_MIN_TOKENS)


def find_context_claim(ctx: ConversationContext | None, *,
                       trigger_tg_message_id=None) -> ContextClaim | None:
    """Ближайший к цели тезис в окне (детерминированно, без LLM).

    Цель и сообщение-триггер («фактчек …») исключаются: команда — не
    публикация. Расстояние — по ``tg_message_id``; при равенстве выбирается
    более раннее сообщение. Текст подписи доступен в окне (W1 caption-фикс)."""
    if ctx is None or not ctx.messages:
        return None
    target = ctx.target_tg_message_id
    candidates = [m for m in ctx.messages
                  if str(m.text or "").strip()
                  and m.tg_message_id != target
                  and m.tg_message_id != trigger_tg_message_id
                  and _claim_like_text(m.text)]
    if not candidates:
        return None

    def _distance(m: ContextMessage):
        try:
            return abs(int(m.tg_message_id) - int(target))
        except (TypeError, ValueError):
            return 10 ** 9

    best = min(candidates, key=lambda m: (_distance(m),
                                          m.tg_message_id or 0))
    return ContextClaim(text=str(best.text).strip(), source="window",
                        author=best.author,
                        tg_message_id=best.tg_message_id)


async def resolve_context_claim(
        db, chat_id: int | None, *,
        target_tg_message_id=None,
        trigger_tg_message_id=None,
        reply_to_tg_id: int | None = None,
        cache=None) -> ContextProbe | None:
    """Обязательная проверка окружения пустой цели (уточнение №2).

    Порядок: reply-цепочка (существующий ``collect_thread_chain``) → окно
    W1 (``build_wide_context``: 200–300 сообщений, кап 500, кеш). Гейт
    ``wide_context_enabled`` здесь НАМЕРЕННО не читается: для пустой цели
    широкий контекст обязателен, флаг остаётся откатом для непустых целей.

    Возврат ``None`` — окружение собрать не удалось (пусто/сбой): это
    техническая причина, вызывающий обязан не выдавать её за «фактов нет»."""
    if db is None or chat_id in (None, 0):
        return None
    try:
        ctx = await build_wide_context(
            db, int(chat_id), target_tg_message_id=target_tg_message_id,
            trigger_tg_message_id=trigger_tg_message_id, claim_text="",
            cache=cache)
    except Exception:
        logger.warning("[factcheck_suitability] wide context failed | chat=%s",
                       chat_id, exc_info=True)
        return None
    feed = ctx.render_feed() if ctx is not None else ""
    chain_claim = None
    chain_len = 0
    if reply_to_tg_id not in (None, "", 0):
        chain = []
        try:
            from config.settings import settings
            from services import hot_config as hot
            from services.thread_chain import (collect_thread_chain,
                                               render_reply_chains)
            depth = hot.get("limits.chat_thread_max_depth",
                            settings.CHAT_THREAD_MAX_DEPTH)
            chain = await collect_thread_chain(
                db, int(chat_id), int(reply_to_tg_id), int(depth or 0))
            chain_len = len(chain)
            for item in chain:               # от текущего (родителя) к корню
                if item.is_bot:
                    continue                 # ответы бота — не тезис
                if _claim_like_text(item.text):
                    chain_claim = ContextClaim(
                        text=str(item.text).strip(), source="reply_to",
                        author=item.name)
                    break
            if chain_claim is not None and chain:
                block = render_reply_chains(chain, trigger_tg_message_id)
                if block:
                    feed = f"{feed}\n\n{block}".strip()
        except Exception:
            logger.warning("[factcheck_suitability] reply chain failed | "
                           "chat=%s", chat_id, exc_info=True)
    if ctx is None and chain_claim is None:
        return None
    claim = chain_claim or find_context_claim(
        ctx, trigger_tg_message_id=trigger_tg_message_id)
    return ContextProbe(
        feed=feed, claim=claim,
        window_messages=len(ctx.messages) if ctx is not None else 0,
        window_before=int(ctx.window.get("before") or 0)
        if ctx is not None else 0,
        window_after=int(ctx.window.get("after") or 0)
        if ctx is not None else 0,
        chain_len=chain_len)


def _contextual_item(ctx: ConversationContext, m: ContextMessage,
                     source: str, confidence: float) -> ClaimItem:
    del confidence
    return ClaimItem(
        text=m.text.strip(),
        claim_type=_classify_literal(m.text),
        verifiable=_has_predicate(m.text),
        source=source,
        author=m.author,
        anchor_tg_message_id=m.tg_message_id,
        anchor_chat_id=ctx.chat_id)


def _resolve_contextual(ctx: ConversationContext, claim_text: str,
                        hint: str | None
                        ) -> tuple[list[ClaimItem], float, str | None]:
    """→ (items, confidence, reason|None). Порядок: reply_to → тема спора →
    доминирующий спор. Автор анцедента сохраняется (06I.6); два
    сопоставимых кандидата → ambiguous (чужой тезис не приписывается)."""
    items: list[ClaimItem] = []
    confidence = 0.0
    reason: str | None = None

    # 1. Прямой reply-анцедент (явная связь — самая сильная, 06I.4).
    replied_tg = _replied_tg(ctx)
    if replied_tg:
        for m in ctx.messages:
            if m.tg_message_id == replied_tg and str(m.text or "").strip():
                if _has_predicate(m.text) or len(
                        tokenize_for_relevance(m.text)) >= 3:
                    item = _contextual_item(ctx, m, "reply_to", 0.8)
                    items.append(item)
                    confidence = max(confidence, 0.8)
                    reason = _REASON_REFERENTIAL
                break

    # 2. Тема спора по редкотермам цели/хинта (стеммы — морфология).
    probe = _stems(claim_text) | _stems(hint)
    scored = _dispute_scores(ctx, probe) if probe else []
    if scored:
        top_msg, top_score = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else 0.0
        unambiguous = (top_score >= second_score * _AMBIGUITY_RATIO
                       or top_score - second_score >= _AMBIGUITY_MARGIN)
        if top_score >= _MIN_TOPIC_SCORE and unambiguous:
            conf = min(0.9, 0.5 + top_score / 20.0)
            items.append(_contextual_item(ctx, top_msg, "topic", conf))
            confidence = max(confidence, conf)
            reason = reason or _REASON_REFERENTIAL
        elif top_score >= _MIN_TOPIC_SCORE:
            # Сопоставимые кандидаты — не приписываем чужой тезис (06I.6).
            return items, 0.35, _REASON_AMBIGUOUS

    # 3. Референциальная цель с пустым зондом («ну и что там?») —
    #    доминирующий спор по дискуссионным маркерам (06J.6 E2E-кейс).
    if not items and _is_referential(claim_text):
        top_msg, top_score, second = _dominant_dispute(ctx)
        if top_msg is not None:
            unambiguous = (top_score >= second * _AMBIGUITY_RATIO
                           or top_score - second >= _AMBIGUITY_MARGIN)
            if unambiguous:
                conf = min(0.75, 0.4 + top_score / 20.0)
                items.append(_contextual_item(ctx, top_msg, "topic", conf))
                confidence = max(confidence, conf)
                reason = reason or _REASON_REFERENTIAL
            else:
                return items, 0.35, _REASON_AMBIGUOUS
    return items, confidence, reason


# ── Stage 3: решение ─────────────────────────────────────────────────────────

def evaluate_suitability(claim_text: str | None, user_hint: str | None,
                         ctx: ConversationContext | None, *,
                         target_ref: dict | None = None,
                         allow_needs_context: bool = True,
                         ) -> SuitabilityDecision:
    """Типизированное решение гейта (06B.6). Никогда не бросает; no_claim
    возможен ТОЛЬКО после изучения контекста (06J.1)."""
    target_ref = dict(target_ref or {})
    claim = str(claim_text or "").strip()

    def _decide(decision: str, claim_type: str, items: tuple, scope: str,
                reason: str | None, confidence: float,
                temporal_hint: bool = False) -> SuitabilityDecision:
        if decision not in DECISIONS:
            decision = DECISION_CHECKABLE
        if claim_type not in CLAIM_TYPES:
            claim_type = INSUFFICIENT_CONTEXT
        return SuitabilityDecision(
            decision=decision, claim_type=claim_type,
            claim_items=tuple(items), scope=scope, reason_code=reason,
            confidence=round(min(1.0, max(0.0, confidence)), 2),
            target_ref=target_ref, temporal_hint=temporal_hint)

    # 0. Пустая/недоступная цель — не отказ: тип 06B.2, деградация наверх.
    if not claim:
        return _decide(DECISION_CONTEXT_UNAVAILABLE,
                       UNSAFE_OR_UNAVAILABLE_TARGET, (), SCOPE_NONE,
                       _REASON_UNAVAILABLE, 0.9)
    # Заявленный год/дата в тексте — temporal-пометка (ж): тот же pipeline.
    temporal_hint = (tf._YEAR_RE.search(claim) is not None
                     or tf._DATE_POINT_RE.search(claim) is not None)

    # 1. Явная просьба «проверь, что X» — проверяемое X важнее формы (06B.2).
    if user_hint and _has_predicate(user_hint):
        item = ClaimItem(text=user_hint.strip(),
                         claim_type=CHECKABLE_FACTUAL_CLAIM, verifiable=True,
                         source="literal",
                         anchor_tg_message_id=target_ref.get(
                             "target_tg_message_id"),
                         anchor_chat_id=target_ref.get("chat_id"))
        return _decide(DECISION_CHECKABLE, CHECKABLE_FACTUAL_CLAIM, (item,),
                       SCOPE_WEB, _REASON_HINT, 0.85,
                       temporal_hint=temporal_hint)

    claim_type = _classify_literal(claim)
    # Вопрос-форма о цели («X — правда?», без собственного «что»-клейма) —
    # содержание в контексте (06I.6): литеральный fast-path не срабатывает,
    # работает контекстная резолюция. «Правда ли, ЧТО X» остаётся клеймом.
    if (claim_type in (CHECKABLE_FACTUAL_CLAIM, MIXED_CLAIM)
            and _QUESTION_RE.search(claim)
            and tf.is_referential_claim(claim)):
        claim_type = QUESTION_WITHOUT_ASSERTION

    # 2. Очевидно проверяемая цель — fast-path (06J.1 obvious_checkable);
    #    атомизация 06B.5: ругань/сарказм частями тезиса НЕ становятся.
    if claim_type in (CHECKABLE_FACTUAL_CLAIM, MIXED_CLAIM):
        items: list[ClaimItem] = []
        for part in _split_atomic(claim):
            if _has_predicate(part) and not _is_prediction(part):
                items.append(ClaimItem(
                    text=part, claim_type=CHECKABLE_FACTUAL_CLAIM,
                    verifiable=True, source="literal",
                    anchor_tg_message_id=target_ref.get(
                        "target_tg_message_id"),
                    anchor_chat_id=target_ref.get("chat_id")))
        if items:
            return _decide(DECISION_CHECKABLE, claim_type, tuple(items),
                           SCOPE_WEB, _REASON_PREDICATE, 0.8,
                           temporal_hint=temporal_hint)
        # Все «проверяемые» части оказались предсказаниями будущего:
        # структурно непроверяемо в настоящем, контекст этого не меняет.
        if _is_prediction(claim):
            return _decide(DECISION_NO_CLAIM, PERSONAL_PREDICTION, (),
                           SCOPE_NONE, _REASON_NO_CLAIM, 0.75,
                           temporal_hint=temporal_hint)

    # 3. Дальше нужен контекст (06J.1: одна строка не отказывает).
    if ctx is None or len(ctx.messages) < _MIN_CONTEXT_MESSAGES:
        if allow_needs_context:
            return _decide(DECISION_NEEDS_CONTEXT, INSUFFICIENT_CONTEXT, (),
                           SCOPE_CHAT, _REASON_NEEDS_CONTEXT, 0.3)
        return _decide(DECISION_CONTEXT_UNAVAILABLE, INSUFFICIENT_CONTEXT, (),
                       SCOPE_NONE, _REASON_CONTEXT_UNAVAILABLE, 0.4)

    items2, conf2, reason2 = _resolve_contextual(ctx, claim, user_hint)
    if reason2 == _REASON_AMBIGUOUS:
        return _decide(DECISION_AMBIGUOUS,
                       QUESTION_WITHOUT_ASSERTION
                       if claim_type == QUESTION_WITHOUT_ASSERTION
                       else INSUFFICIENT_CONTEXT,
                       tuple(items2), SCOPE_CHAT, reason2, conf2,
                       temporal_hint=temporal_hint)
    if items2:
        scope = (SCOPE_WEB_AND_CHAT
                 if any(i.verifiable and i.source in ("topic", "reply_to")
                        for i in items2) else SCOPE_CHAT)
        return _decide(DECISION_CHECKABLE,
                       MIXED_CLAIM if claim_type == MIXED_CLAIM
                       else CHECKABLE_FACTUAL_CLAIM,
                       tuple(items2), scope,
                       reason2 or _REASON_REFERENTIAL, conf2,
                       temporal_hint=temporal_hint)

    # 4. Контекст изучен, анцедентов нет (06J.3): вопрос без утверждения —
    #    уточнение (НЕ отказ); предсказание/мнение/абсурд — no_claim.
    if claim_type == QUESTION_WITHOUT_ASSERTION:
        return _decide(DECISION_AMBIGUOUS, QUESTION_WITHOUT_ASSERTION, (),
                       SCOPE_CHAT, _REASON_AMBIGUOUS, 0.5,
                       temporal_hint=temporal_hint)
    if claim_type in (SUBJECTIVE_OPINION, PERSONAL_PREDICTION, NONSENSE,
                      JOKE_IRONY):
        return _decide(DECISION_NO_CLAIM, claim_type, (), SCOPE_NONE,
                       _REASON_NO_CLAIM, 0.7, temporal_hint=temporal_hint)
    # 5. Неклассифицированный остаток — осторожный checkable-фолбэк
    #    (06J.2: ложный отказ дороже лишнего прохода пайплайна).
    return _decide(DECISION_CHECKABLE, claim_type, (), SCOPE_WEB,
                   _REASON_FALLBACK, 0.4, temporal_hint=temporal_hint)


async def expand_context_once(db, ctx: ConversationContext | None, *,
                              cache=None) -> ConversationContext | None:
    """Одно ограниченное расширение окна (06J.1 expand-ступень): максимум
    разрешённого окна (потолок W1 не превышается). Fail-open → прежний ctx."""
    if db is None or ctx is None:
        return ctx
    total = (max(0, int(ctx.window.get("before") or 0))
             + max(0, int(ctx.window.get("after") or 0)))
    target_total = max(total * 2, _WIDE_WINDOW_MAX)
    expanded = await build_wide_context(
        db, ctx.chat_id, target_tg_message_id=ctx.target_tg_message_id,
        trigger_tg_message_id=ctx.trigger_tg_message_id, cache=cache,
        window_override=(target_total, target_total), skip_cache_read=True)
    return expanded or ctx


async def evaluate_with_expansion(db, chat_id: int, *, claim_text: str,
                                  user_hint: str | None,
                                  target_tg_message_id=None,
                                  trigger_tg_message_id=None,
                                  cache=None,
                                  ) -> tuple[SuitabilityDecision,
                                             ConversationContext | None]:
    """Протокол двух проходов (06J.1): сбор → решение; needs_context →
    ОДНО ограниченное расширение → повторное решение. Второй needs_context
    честно деградирует в context_unavailable (без выдуманных тезисов).
    Возврат: (финальное решение, финальный контекст для рендера)."""
    target_ref = {"chat_id": chat_id,
                  "target_tg_message_id": target_tg_message_id,
                  "trigger_tg_message_id": trigger_tg_message_id}
    ctx = await build_wide_context(
        db, chat_id, target_tg_message_id=target_tg_message_id,
        trigger_tg_message_id=trigger_tg_message_id, claim_text=claim_text,
        cache=cache)
    decision = evaluate_suitability(claim_text, user_hint, ctx,
                                    target_ref=target_ref)
    if decision.decision == DECISION_NEEDS_CONTEXT:
        ctx = await expand_context_once(db, ctx, cache=cache)
        decision = evaluate_suitability(claim_text, user_hint, ctx,
                                        target_ref=target_ref,
                                        allow_needs_context=False)
    return decision, ctx
