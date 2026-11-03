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

ASAP-FC-ADMISSION-01 (31.10.2026) — допуск при ЯВНОЙ команде фактчека:

* явный ``фактчек`` — сильный сигнал намерения: грубость/ирония/мнение/
  технический термин/пересылка/ссылка/отсутствие глагольных маркеров НЕ
  превращают запрос в ``no_claim`` (политика §2.1);
* проверяемое ядро определяется отдельно и recall-ориентированно
  (``has_checkable_core``): числа/даты, структурный предикат, глагольная
  форма + содержательные токены, ссылка/материал. Это НЕ словарь терминов и
  НЕ отдельный LLM-фильтр (политика §2.7);
* при явном запросе и хотя бы одном правдоподобно проверяемом утверждении
  решение допуска — ``checkable`` (``_REASON_EXPLICIT_CORE``): сомнение
  классификатора не становится отказом, а обычный конвейер может закончить
  ``insufficient_evidence`` — это НЕ ``no_claim`` (политика §2.3);
* три исхода разделены: ``no_identifiable_claim`` (после корректного
  разрешения цели утверждения нет), ``insufficient_context`` /
  ``ambiguous_target`` (неизвестно, что проверять), а
  ``checkable_but_insufficient_evidence`` — вердикт-слой пайплайна, не гейт
  (политика §2.4, ``admission_label``).
"""
from __future__ import annotations

import dataclasses
import logging
import re

from services import temporal_factcheck as tf
from services.canonical_context import (
    RELATION_SEMANTIC,
    SpeechProjection,
    SpeechRelation,
    resolve_item_id,
)
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
# ASAP-FC-ADMISSION-01: явный запрос + найденное проверяемое ядро / его нет.
_REASON_EXPLICIT_CORE = "explicit_request_checkable_core"
_REASON_EXPLICIT_NO_CORE = "explicit_request_no_checkable_core"

# Канонические метки допуска (политика §2.4, диагностика §E):
#   checkable / no_identifiable_claim / insufficient_context /
#   ambiguous_target / unavailable_target. Вердикт-слой
#   (``checkable_but_insufficient_evidence``) — НЕ гейт: его ставит пайплайн.
ADMISSION_CHECKABLE = "checkable"
ADMISSION_NO_IDENTIFIABLE_CLAIM = "no_identifiable_claim"
ADMISSION_INSUFFICIENT_CONTEXT = "insufficient_context"
ADMISSION_AMBIGUOUS_TARGET = "ambiguous_target"
ADMISSION_UNAVAILABLE_TARGET = "unavailable_target"
ADMISSION_NOT_APPLIED = "gate_not_applied"

_ADMISSION_BY_DECISION = {
    DECISION_CHECKABLE: ADMISSION_CHECKABLE,
    DECISION_NO_CLAIM: ADMISSION_NO_IDENTIFIABLE_CLAIM,
    DECISION_NEEDS_CONTEXT: ADMISSION_INSUFFICIENT_CONTEXT,
    DECISION_AMBIGUOUS: ADMISSION_AMBIGUOUS_TARGET,
    DECISION_CONTEXT_UNAVAILABLE: ADMISSION_UNAVAILABLE_TARGET,
}


def admission_label(decision: "SuitabilityDecision | None") -> str:
    """Метка допуска для телеметрии/админки (§2.4, §E).

    Отличает ложный отказ (``no_identifiable_claim`` при существующем тезисе)
    от честного «проверяемых фактов нет» и от «неизвестно, что проверять».
    ``None`` = гейт не применялся (откат) — не выдумываем решение."""
    if decision is None:
        return ADMISSION_NOT_APPLIED
    return _ADMISSION_BY_DECISION.get(str(getattr(decision, "decision", "")),
                                      ADMISSION_CHECKABLE)


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


def _has_factual_marker(text: str) -> bool:
    """Структурный фактический маркер части тезиса (числа/даты/сказуемое/
    цитата) — БЕЗ копулы. Нужен, чтобы отличить фактическую предпосылку от
    чистой оценки: «это отвратительно» копулой проверяемым не становится
    (ASAP-FC-ADMISSION-01 §2.5, оценка отделяется от факта)."""
    clean = str(text or "").strip()
    if not clean:
        return False
    if _PREDICATE_NUMERIC_RE.search(clean):
        return True
    low = clean.lower()
    for marker in _PREDICATE_LEXICON:
        if marker in low:
            return True
    return bool(_QUOTE_RE.search(clean))


# ASAP-FC-ADMISSION-01 (§2.2/§2.7): recall-ориентированный признак
# «правдоподобно проверяемого ядра». Механизм — структурный (числа/даты,
# предикат, глагольная форма, содержательные токены, ссылка/материал), а НЕ
# словарь предметных терминов и НЕ LLM-фильтр: разговорная, грубая или
# ироничная формулировка тезиса не мешает допуску.
_LINK_RE = re.compile(r"(https?://|www\.|\bt\.me/)", re.IGNORECASE)
_CORE_MIN_TOKENS = 3


def _is_link_only(text: str) -> bool:
    """Часть тезиса — только ссылка/адрес (материал, не утверждение).

    Такая часть не становится проверяемым пунктом: она остаётся материалом
    для контекста/источника, а не тезисом (иначе в claim_items попадал бы
    «Подробнее: https://…»)."""
    raw = str(text or "")
    if not _LINK_RE.search(raw):
        return False
    residue = re.sub(r"\S*?(?:https?://|www\.|t\.me/)\S*", " ", raw)
    return len(tokenize_for_relevance(residue)) < 2


def has_checkable_core(text: str) -> bool:
    """Есть ли в тексте правдоподобно проверяемое утверждение (§2.2).

    Порядок (дешёвый → дорогой, без внешних вызовов):
    * структурный claim-like предикат W1/W2 (``_claim_like_text``: числа/
      даты, фактические сказуемые, глагольная форма + содержательные токены);
    * ссылка/материал (пересылка, caption, «пруф» рядом) — тезис может жить
      в связанном материале, а не в первой строке цели;
    * ≥3 содержательных токена при непустом, не филлерном тексте.

    Возвращает False ТОЛЬКО для пустого/филлерного текста («лол», «ага»,
    эмодзи) — там проверять нечего. Решение «проверяемо/нет» принимает
    вызывающий (явный запрос → ``checkable``, §2.3)."""
    clean = str(text or "").strip()
    if not clean:
        return False
    if _claim_like_text(clean):
        return True
    if _LINK_RE.search(clean):
        return True
    if is_conservatively_irrelevant(clean):
        return False
    return len(tokenize_for_relevance(clean)) >= _CORE_MIN_TOKENS


def text_target_sufficient(text: str) -> bool:
    """Самостоятельный проверяемый текст цели (FC-MEDIA-OPTIONAL-01 §10.2).

    Один предикат на все маршруты фактчека: «у цели есть собственный тезис»
    решает, нужна ли вообще необязательная медиа-ассоциация. Переиспользует
    существующие предикаты (`_COMMAND_TEXT_RE`, `is_conservatively_irrelevant`,
    `has_checkable_core`) — нового классификатора нет.

    `False` только когда текста нет, это сама команда «фактчек …» или
    консервативный филлер: тогда цель действительно может нуждаться в медиа
    (§10.2 «Unbound фактчек after media»)."""
    clean = str(text or "").strip()
    if not clean:
        return False
    if _COMMAND_TEXT_RE.match(clean):
        return False
    if is_conservatively_irrelevant(clean):
        return False
    return has_checkable_core(clean)


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
        if not (_claim_like_text(m.text) or len(stems) >= 6):
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
    целей с пустым зондом — «ну и что там?»).

    EVOL-REPLY-CONTEXT-INTEGRITY-01 §4.3 (BD-5): вес больше НЕ включает
    «число прямых ответов» и «длину в словах» — эти критерии выбора
    антецедента прямо запрещены. Структурные признаки берутся как факты
    связи (тезис — не реакция; на него отвечают), а не как количество:

    * сообщение-реакция (само является ответом внутри окна) антецедентом
      быть не может — §13.13 «не создавать новый тезис из реакции»;
    * вес = маркеры спора ×2 + предикат + claim-like + «на него есть ответ».

    → (сообщение|None, top_score, second_score)."""
    target_tg = ctx.target_tg_message_id
    messages = [m for m in ctx.messages if str(m.text or "").strip()]
    if not messages:
        return None, 0.0, 0.0
    window_ids = {m.tg_message_id for m in messages}
    replied: set[int] = set()
    reaction_ids: set[int] = set()
    for m in messages:
        parent = m.reply_to_tg_id
        if parent in (None, "", 0):
            continue
        try:
            parent = int(parent)
        except (TypeError, ValueError):
            continue
        replied.add(parent)
        if parent in window_ids and m.tg_message_id != target_tg:
            # сообщение, которое отвечает внутри окна, — реакция, не тезис
            reaction_ids.add(m.tg_message_id)
    candidates = [m for m in messages
                  if m.tg_message_id != target_tg
                  and m.tg_message_id not in reaction_ids
                  and (_claim_like_text(m.text)
                       or len(tokenize_for_relevance(m.text)) >= 6)
                  # антецедент спора участвует в обсуждении: на него отвечают
                  # ИЛИ он сам несёт дискуссионный маркер (не «сколько раз»)
                  and (m.tg_message_id in replied
                       or bool(_DISPUTE_MARKER_RE.search(str(m.text or ""))))]
    if not candidates:
        return None, 0.0, 0.0
    scored: list[tuple[ContextMessage, float]] = []
    for m in candidates:
        score = len(_DISPUTE_MARKER_RE.findall(str(m.text or ""))) * 2.0
        if _has_predicate(m.text):
            score += 1.0
        if _claim_like_text(m.text):
            score += 1.0
        if m.tg_message_id in replied:
            # структурный факт: на это сообщение отвечают (не «сколько раз»)
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

_CONTEXT_CLAIM_MIN_CHARS = 4
_CONTEXT_CLAIM_MIN_TOKENS = 2
# Review fix (25.10.2026): recall-ориентированный структурный предикат для
# контекстного probe. Глагольные формы (в т.ч. возвратные) — достаточный
# признак утверждения: «Мост обрушился вчера» не должен теряться из-за
# длины/словаря. Числа/даты — значимы независимо от длины («Курс 95»).
_VERB_FORM_RE = re.compile(
    r"(?:л|ла|ло|ли|лся|лась|лось|лись|ет|ют|ит|ат|ят|"
    r"ется|ются|ует|ирует|ал|ял|ил|ел)\b", re.IGNORECASE)
_COMMAND_TEXT_RE = re.compile(r"^\s*фактчек\b", re.IGNORECASE)
# Реакции/филлеры — НЕ повод для фактчека (консервативный список).
_FILLER_WORDS = frozenset({
    "лол", "ага", "угу", "ок", "ok", "ну", "такое", "ясно", "понятно",
    "хм", "хз", "да", "нет", "конечно", "пф", "хех", "ахах", "кек",
    "норм", "бывает", "серьезно", "серьёзно", "ааа", "ооо",
})
_WORD_TOKEN_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class ContextClaim:
    """Найденный в окружении тезис-кандидат (цель — только точка входа)."""
    text: str
    source: str                      # reply_to | window
    author: str | None = None
    tg_message_id: int | None = None
    #: EVOL-REPLY-CONTEXT-INTEGRITY-01 §4.3: чем обоснован выбор антецедента
    #: (``structural`` | ``topic`` | ``tiebreak``) — видно в трассе.
    basis: str = ""


@dataclasses.dataclass(frozen=True)
class ContextProbe:
    """Результат обязательной проверки окружения для пустой цели."""
    feed: str                        # готовый <chat_context> (+ цепочка)
    claim: ContextClaim | None
    window_messages: int
    window_before: int
    window_after: int
    chain_len: int = 0
    #: Сопоставимые кандидаты без разрешения → вызывающий уточняет предмет,
    #: а не выдаёт вердикт по угаданному тезису (§4.3, сценарий 10).
    ambiguous: bool = False
    candidates: tuple[int, ...] = ()
    claim_basis: str = ""


def _item_tg_message_id(item) -> int | None:
    """Telegram ID хода цепочки из ``item_id`` (``tg:<id>``) либо ``None``.

    ADR-1020-1 п.4: ``item_id`` бывает ``tg:<tg_message_id>``, ``msg:<id>``
    (локальный id строки БД) или пустым. Анкором объявленного тезиса может
    быть только реальный Telegram ID: ``msg:``/пусто — id достоверно
    неизвестен, подставлять его нельзя (тезис получил бы чужую дату/автора)."""
    raw = str(getattr(item, "item_id", "") or "")
    if not raw.startswith("tg:"):
        return None
    try:
        value = int(raw.split(":", 1)[1])
    except (IndexError, TypeError, ValueError):
        return None
    return value or None


def _claim_like_text(text: str) -> bool:
    """Структурный признак проверяемого утверждения (recall-ориентированный).

    Review fix (25.10.2026): не терять короткие факты.
    * числа/даты — значимы независимо от длины («Курс 95», «12.10.2026»);
    * предикат W2 (лексика/копула/цитата) — как раньше;
    * глагольная форма + ≥2 содержательных токена («Мост обрушился вчера»).
    Без LLM-классификатора. Филлеры («ага», «ну такое») отсекаются отдельно
    в ``is_conservatively_irrelevant``.
    """
    clean = str(text or "").strip()
    if len(clean) < _CONTEXT_CLAIM_MIN_CHARS:
        return False
    if re.search(r"\d", clean):
        return True
    if _LINK_RE.search(clean):
        # ASAP-FC-ADMISSION-01 §2.2: материал-ссылка (пересылка/caption/«пруф»)
        # — тезис может жить в связанном материале, а не в первой строке.
        return True
    if _has_predicate(clean):
        return True
    if len(tokenize_for_relevance(clean)) < _CONTEXT_CLAIM_MIN_TOKENS:
        return False
    return bool(_VERB_FORM_RE.search(clean))


def is_conservatively_irrelevant(text: str) -> bool:
    """Консервативно нерелевантная непустая цель («лол», «ага», эмодзи).

    Только явные филлеры/реакции (≤24 симв., без цифр, не claim-like):
    такой текст — повод проверить окружение, а не тезис. Всё остальное
    (даже короткое) считается материалом и идёт обычным путём."""
    clean = str(text or "").strip()
    if not clean:
        return True
    if len(clean) > 24 or re.search(r"\d", clean):
        return False
    if _claim_like_text(clean):
        return False
    words = _WORD_TOKEN_RE.findall(clean.lower())
    if not words:
        return True                  # только эмодзи/пунктуация
    return all(word in _FILLER_WORDS for word in words)


#: Два тезиса в одном всплеске рядом с целью — выбор неоднозначен (§4.3,
#: сценарий 10): расстояния по tg-идентификатору различаются на 1 → уточнение.
_ADJACENT_TIE_GAP = 1
#: Неизвестный tg-идентификатор — «дальше любого известного» (детерминированно).
_CONTEXT_DISTANCE_UNKNOWN = 10 ** 9


def _infer_source_claim(ctx: ConversationContext | None, *,
                        trigger_tg_message_id=None,
                        hint: str | None = None,
                        reply_to_tg_id: int | None = None
                        ) -> tuple["ContextClaim | None", str, tuple[int, ...]]:
    """Антецедент тезиса в окне: (claim|None, статус, id кандидатов).

    EVOL-REPLY-CONTEXT-INTEGRITY-01 §4.2/§4.3 (BD-4). Порядок решения
    заморожен и НЕ содержит запрещённых критериев (минимум `abs(tg−target)`,
    максимум слов, число ответов, частота терминов как правило выбора):

    1. структурная цепочка — тезис связан с целью/триггером реальным
       reply-ребром (это не «соседство», а факт адресации);
    2. семантические кандидаты существующим `_dispute_scores` по стеммам
       текста цели и хинта; сопоставимые (неразличимые) → уточнение;
    3. разрешение ничьей по tg-близости — только среди РАВНЫХ по семантике
       (обычно нулевой зонд: у пустой/реактивной цели нет своего текста),
       и только если рядом нет второго сопоставимого тезиса;
    4. два сопоставимых кандидата в одном всплеске → `ambiguous`
       (вызывающий обязан уточнить, а не выдавать вердикт).

    Статусы: ``structural`` | ``topic`` | ``tiebreak`` | ``ambiguous`` |
    ``none``."""
    if ctx is None or not ctx.messages:
        return None, "none", ()
    target_tg = ctx.target_tg_message_id
    anchor_ids = {target_tg, trigger_tg_message_id}
    candidates: list[ContextMessage] = []
    for m in ctx.messages:
        text = str(m.text or "").strip()
        if not text or m.tg_message_id in anchor_ids:
            continue
        if _COMMAND_TEXT_RE.match(text):
            continue                     # команда «фактчек …» — не публикация
        if not _claim_like_text(text):
            continue
        candidates.append(m)
    if not candidates:
        return None, "none", ()

    def _ids(rows) -> tuple[int, ...]:
        return tuple(int(m.tg_message_id) for m in rows
                     if m.tg_message_id is not None)

    def _claim_of(m: ContextMessage, source: str) -> ContextClaim:
        return ContextClaim(text=str(m.text).strip(), source=source,
                            author=m.author, tg_message_id=m.tg_message_id)

    # 1. Структурная связь: цель/триггер отвечают именно на это сообщение.
    #    `reply_to_tg_id` приходит от публикации: строка самой пустой цели в
    #    окно не попадает (нет текста), поэтому реальное ребро берётся из
    #    фактических данных цели, а не угадывается по порядку.
    parents: set[int] = set()
    if reply_to_tg_id not in (None, "", 0):
        try:
            parents.add(int(reply_to_tg_id))
        except (TypeError, ValueError):
            pass
    for m in ctx.messages:
        if m.tg_message_id not in anchor_ids:
            continue
        try:
            parent = int(m.reply_to_tg_id)
        except (TypeError, ValueError):
            continue
        if parent not in anchor_ids:
            parents.add(parent)
    structural = [m for m in candidates if m.tg_message_id in parents]
    if len(structural) == 1:
        return _claim_of(structural[0], "reply_to"), "structural", _ids(
            structural)
    if len(structural) > 1:
        return None, "ambiguous", _ids(structural)

    # 2. Семантика: пересечение стеммов текста цели/хинта с сообщением.
    def _distance(m: ContextMessage) -> int:
        try:
            return abs(int(m.tg_message_id) - int(target_tg))
        except (TypeError, ValueError):
            return _CONTEXT_DISTANCE_UNKNOWN

    probe: set[str] = _stems(hint)
    for m in ctx.messages:
        if m.tg_message_id == target_tg:
            probe |= _stems(m.text)
            break
    by_id = {m.tg_message_id: m for m in candidates}
    scored = [(m, score) for m, score in (_dispute_scores(ctx, probe)
                                          if probe else [])
              if m.tg_message_id in by_id]
    if scored:
        top_msg, top_score = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else 0.0
        separated = (top_score >= second_score * _AMBIGUITY_RATIO
                     or top_score - second_score >= _AMBIGUITY_MARGIN)
        if second_score > 0 and not separated:
            return None, "ambiguous", _ids([m for m, _s in scored[:3]])
        if separated and top_score >= _MIN_TOPIC_SCORE:
            return (_claim_of(top_msg, "window"), "topic",
                    (int(top_msg.tg_message_id),))
        tied = [m for m, score in scored if score == top_score]
        if len(tied) > 1:
            return None, "ambiguous", _ids(tied[:3])

    # 3. Ничья по семантике (обычно нулевой зонд): близость — только
    #    детерминированное разрешение ничьей, не правило выбора темы.
    ordered = sorted(candidates, key=lambda m: (_distance(m),
                                                int(m.tg_message_id or 0)))
    best = ordered[0]
    if len(ordered) > 1:
        runner = ordered[1]
        if _distance(runner) - _distance(best) <= _ADJACENT_TIE_GAP:
            return None, "ambiguous", _ids(ordered[:3])
    return _claim_of(best, "window"), "tiebreak", (int(best.tg_message_id),)


def find_context_claim(ctx: ConversationContext | None, *,
                       trigger_tg_message_id=None,
                       hint: str | None = None,
                       reply_to_tg_id: int | None = None
                       ) -> ContextClaim | None:
    """Антецедент тезиса в окне (детерминированно, без LLM).

    Возврат ``None`` — либо кандидатов нет вовсе, либо они сопоставимы:
    вызывающий обязан уточнить предмет (угадывать запрещено, §4.3)."""
    claim, _status, _ids = _infer_source_claim(
        ctx, trigger_tg_message_id=trigger_tg_message_id, hint=hint,
        reply_to_tg_id=reply_to_tg_id)
    return claim


#: Основания `_infer_source_claim`, при которых связь установлена ПО ТЕМЕ,
#: а не транспортным Reply. ``tiebreak`` сюда НЕ входит: там семантика нулевая
#: и решает только близость по tg-id — называть это темой было бы выдумкой.
_SEMANTIC_BASES = ("topic",)


def _semantic_link(ctx, claim, basis):
    """Установленная смысловая связь антецедента → (проекция, relations).

    EVOL v5 §13 сц.7 / §9.5 п.2: «родитель отсутствует, но есть тематически
    связанный контекст → связь помечается семантической, не изображается
    настоящим Reply». Единственное место, где такая связь реально
    устанавливается (`_infer_source_claim`, основание ``topic``): антецедент
    выбран по пересечению стеммов, Reply у цели нет.

    Возврат ``(None, None)`` — связи по теме нет (структурный Reply, ничья по
    позиции, неоднозначность, пустое окружение): фид рендерится байт-в-байт
    прежним путём.

    Противоэлемент связи — сообщение, о котором спросили: цель проверки, если
    она видна в окне, иначе триггер запроса. Нет ни того, ни другого — метка
    не выдумывается, клауза честно говорит «реплика вне доступного окна».
    """
    if ctx is None or claim is None or basis not in _SEMANTIC_BASES:
        return None, None
    tg_id = claim.tg_message_id
    if tg_id in (None, "", 0):
        return None, None
    visible = {m.dedup_key for m in ctx.messages}
    link_ref = ""
    for candidate in (ctx.target_tg_message_id, ctx.trigger_tg_message_id):
        if candidate in (None, "", 0):
            continue
        ref = f"tg:{int(candidate)}"
        if ref in visible:
            link_ref = ref
            break
    projection = SpeechProjection(
        run_id=f"factcheck:{ctx.chat_id}:{ctx.target_tg_message_id}")
    # §4.3 п.3: метки выдаются в порядке ХРОНОЛОГИИ прогона — иначе ребро,
    # напечатанное раньше своего противоэлемента, получило бы «метку не
    # найдено» и связь выглядела бы неизвестной при известной.
    try:
        projection.reserve([
            resolve_item_id(tg_message_id=m.tg_message_id,
                            message_id=m.message_id)
            for m in ctx.messages])
    except Exception:                      # pragma: no cover — метки не рвут фид
        pass
    relation = SpeechRelation(kind=RELATION_SEMANTIC, target_item_id=link_ref,
                              basis=basis)
    return projection, {f"tg:{int(tg_id)}": (relation,)}


async def resolve_context_claim(
        db, chat_id: int | None, *,
        target_tg_message_id=None,
        trigger_tg_message_id=None,
        reply_to_tg_id: int | None = None,
        hint: str | None = None,
        cache=None) -> ContextProbe | None:
    """Обязательная проверка окружения пустой цели (уточнение №2).

    Порядок: reply-цепочка (существующий ``collect_thread_chain``) → окно
    W1 (``build_wide_context``: 200–300 сообщений, кап 500, кеш). Гейт
    ``wide_context_enabled`` здесь НАМЕРЕННО не читается: для пустой цели
    широкий контекст обязателен, флаг остаётся откатом для непустых целей.

    Выбор антецедента — ``_infer_source_claim`` (§4.3): структурная связь →
    семантика → детерминированная ничья; сопоставимые кандидаты дают
    ``ambiguous=True`` (уточнение вместо угадывания).

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
    chain_claim = None
    chain_len = 0
    chain_block = ""
    if reply_to_tg_id not in (None, "", 0):
        chain = []
        try:
            from config.settings import settings
            from services import hot_config as hot
            from services.thread_chain import (alias_quote_author_resolver,
                                               collect_thread_chain,
                                               render_reply_chains)
            depth = hot.get("limits.chat_thread_max_depth",
                            settings.CHAT_THREAD_MAX_DEPTH)
            chain = await collect_thread_chain(
                db, int(chat_id), int(reply_to_tg_id), int(depth or 0),
                # EVOL v5 §8 п.4: автор цитаты — имя через alias-каскад.
                quote_author_resolver=alias_quote_author_resolver())
            chain_len = len(chain)
            for item in chain:               # от текущего (родителя) к корню
                if item.is_bot:
                    continue                 # ответы бота — не тезис
                if _COMMAND_TEXT_RE.match(str(item.text or "")):
                    continue                 # «фактчек …» — команда, не тезис
                if _claim_like_text(item.text):
                    # B2 (§4.1/§4.2/§5.3): объявленный тезис обязан нести СВОЙ
                    # Telegram ID — иначе анкор пуст и envelope строится по
                    # сообщению-реакции, приписывая тезису чужую дату/автора.
                    tg_id = _item_tg_message_id(item)
                    if tg_id is None:
                        continue             # id достоверно неизвестен
                    chain_claim = ContextClaim(
                        text=str(item.text).strip(), source="reply_to",
                        author=item.name, tg_message_id=tg_id)
                    break
            if chain_claim is not None and chain:
                chain_block = render_reply_chains(
                    chain, trigger_tg_message_id, chat_id=int(chat_id))
        except Exception:
            logger.warning("[factcheck_suitability] reply chain failed | "
                           "chat=%s", chat_id, exc_info=True)
    if ctx is None and chain_claim is None:
        return None
    window_claim, basis, candidate_ids = _infer_source_claim(
        ctx, trigger_tg_message_id=trigger_tg_message_id, hint=hint,
        reply_to_tg_id=reply_to_tg_id)
    if chain_claim is not None:
        claim, basis, candidate_ids = chain_claim, "structural", (
            (int(chain_claim.tg_message_id),)
            if chain_claim.tg_message_id is not None else ())
    else:
        claim = window_claim
    if claim is not None and not claim.basis:
        claim = dataclasses.replace(claim, basis=basis)
    # §13 сц.7 / §9.5 п.2: связь установлена ПО ТЕМЕ (Reply у цели нет) —
    # окно печатает её явной клаузой «↳ по теме … (не Reply)», чтобы модель
    # не принимала смысловую связь за подтверждённый Telegram Reply.
    feed = ""
    if ctx is not None:
        projection, relations = _semantic_link(ctx, claim, basis)
        feed = ctx.render_feed(projection=projection,
                               relations_by_item=relations)
    if chain_block:
        feed = f"{feed}\n\n{chain_block}".strip()
    ambiguous = bool(claim is None and basis == "ambiguous")
    return ContextProbe(
        feed=feed, claim=claim,
        window_messages=len(ctx.messages) if ctx is not None else 0,
        window_before=int(ctx.window.get("before") or 0)
        if ctx is not None else 0,
        window_after=int(ctx.window.get("after") or 0)
        if ctx is not None else 0,
        chain_len=chain_len,
        ambiguous=ambiguous,
        candidates=tuple(candidate_ids),
        claim_basis=basis)


def _contextual_item(ctx: ConversationContext, m: ContextMessage,
                     source: str, confidence: float) -> ClaimItem:
    del confidence
    return ClaimItem(
        text=m.text.strip(),
        claim_type=_classify_literal(m.text),
        verifiable=_claim_like_text(m.text),
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
                if _claim_like_text(m.text) or len(
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

def _core_items(claim: str, claim_type: str, target_ref: dict) -> list[ClaimItem]:
    """Части тезиса, которые действительно несут проверяемое ядро (§2.2/§2.5).

    Атомизация существующая (``_split_atomic``); отбор — ``has_checkable_core``
    (структурный, без словарей). Оценочные/эмоциональные части в проверяемые
    пункты НЕ попадают: смешанное высказывание проверяется по фактической
    части, оценка остаётся оценкой (политика §2.5)."""
    items: list[ClaimItem] = []
    for part in _split_atomic(claim):
        if not has_checkable_core(part) or _is_link_only(part):
            continue
        if _is_subjective(part) and not _has_factual_marker(part):
            continue                     # чистая оценка — не тезис
        items.append(ClaimItem(
            text=part,
            claim_type=(MIXED_CLAIM if claim_type == MIXED_CLAIM
                        else CHECKABLE_FACTUAL_CLAIM),
            verifiable=True, source="literal",
            anchor_tg_message_id=target_ref.get("target_tg_message_id"),
            anchor_chat_id=target_ref.get("chat_id")))
    return items


def evaluate_suitability(claim_text: str | None, user_hint: str | None,
                         ctx: ConversationContext | None, *,
                         target_ref: dict | None = None,
                         allow_needs_context: bool = True,
                         explicit_request: bool = False,
                         ) -> SuitabilityDecision:
    """Типизированное решение гейта (06B.6). Никогда не бросает; no_claim
    возможен ТОЛЬКО после изучения контекста (06J.1).

    ``explicit_request`` (ASAP-FC-ADMISSION-01 §2.1/§2.3) — пользователь явно
    попросил фактчек (команда «фактчек»). Тогда сомнение классификатора НЕ
    превращается в отказ: при наличии правдоподобно проверяемого ядра
    (``has_checkable_core``) решение — ``checkable``, а честный «доказательств
    не хватило» остаётся вердикт-слою пайплайна."""
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
    #    ASAP-FC-ADMISSION-01: для явного запроса достаточно проверяемого
    #    ядра, а не глагольного маркера из узкого списка.
    if user_hint and (has_checkable_core(user_hint) if explicit_request
                      else _has_predicate(user_hint)):
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
            if not _has_predicate(part) or _is_prediction(part):
                continue
            if _is_link_only(part):
                continue                 # ссылка — материал, не тезис
            # ASAP-FC-ADMISSION-01 §2.5: в смешанном высказывании чисто
            # оценочные части не становятся проверяемыми пунктами — факт
            # проверяется, оценка остаётся оценкой.
            if _is_subjective(part) and not _has_factual_marker(part):
                continue
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
        if _is_prediction(claim) and not explicit_request:
            return _decide(DECISION_NO_CLAIM, PERSONAL_PREDICTION, (),
                           SCOPE_NONE, _REASON_NO_CLAIM, 0.75,
                           temporal_hint=temporal_hint)

    # 2b. ASAP-FC-ADMISSION-01 §2.1/§2.3: ЯВНЫЙ запрос + правдоподобно
    #     проверяемое ядро → допуск ``checkable``. Грубость, ирония, мнение,
    #     технический термин, пересылка, ссылка и отсутствие глагольных
    #     маркеров отказом не являются; «доказательств не хватило» — честный
    #     исход пайплайна (``insufficient_evidence``), не ``no_claim``.
    if explicit_request and has_checkable_core(claim):
        core = _core_items(claim, claim_type, target_ref)
        if core:
            admitted_type = (MIXED_CLAIM if claim_type == MIXED_CLAIM
                             else CHECKABLE_FACTUAL_CLAIM)
            return _decide(DECISION_CHECKABLE, admitted_type, tuple(core),
                           SCOPE_WEB, _REASON_EXPLICIT_CORE, 0.65,
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
        # ASAP-FC-ADMISSION-01 §2.6: no_claim — только после корректного
        # определения цели и контекста, когда проверяемого ядра нет.
        return _decide(DECISION_NO_CLAIM, claim_type, (), SCOPE_NONE,
                       (_REASON_EXPLICIT_NO_CORE if explicit_request
                        else _REASON_NO_CLAIM), 0.7,
                       temporal_hint=temporal_hint)
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
                                  explicit_request: bool = False,
                                  ) -> tuple[SuitabilityDecision,
                                             ConversationContext | None]:
    """Протокол двух проходов (06J.1): сбор → решение; needs_context →
    ОДНО ограниченное расширение → повторное решение. Второй needs_context
    честно деградирует в context_unavailable (без выдуманных тезисов).
    Возврат: (финальное решение, финальный контекст для рендера).

    ``explicit_request`` (ASAP-FC-ADMISSION-01) — явная команда «фактчек»:
    передаётся в оба прохода, чтобы сомнение классификатора не превращалось
    в отказ на действующем маршруте (в т.ч. в v2, где suitability
    вызывается напрямую, без отдельного флага путей)."""
    target_ref = {"chat_id": chat_id,
                  "target_tg_message_id": target_tg_message_id,
                  "trigger_tg_message_id": trigger_tg_message_id}
    ctx = await build_wide_context(
        db, chat_id, target_tg_message_id=target_tg_message_id,
        trigger_tg_message_id=trigger_tg_message_id, claim_text=claim_text,
        cache=cache)
    decision = evaluate_suitability(claim_text, user_hint, ctx,
                                    target_ref=target_ref,
                                    explicit_request=explicit_request)
    if decision.decision == DECISION_NEEDS_CONTEXT:
        ctx = await expand_context_once(db, ctx, cache=cache)
        decision = evaluate_suitability(claim_text, user_hint, ctx,
                                        target_ref=target_ref,
                                        allow_needs_context=False,
                                        explicit_request=explicit_request)
    return decision, ctx
