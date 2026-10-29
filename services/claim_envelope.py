"""MCA-22 (round 10.27, ADR-1028-6 D4/D5) — Claim/Assertion Envelope,
speaker ≠ subject, coreference, единый producer-validator.

C4 (§6/§7/§8 ТЗ):
* Runtime frozen-DTO `ClaimEnvelope`; persistence — СУЩЕСТВУЮЩАЯ схема
  (graph_facts v17-колонки + `mca_evidence_links` `claim_key`/`checks_json`
  + `mca_provenance_status`). Новая SQL-таблица запрещена (Q6).
* Speech acts: `assert/deny/correct/quote/retell/question/hypothesis/
  joke_candidate/command`. Question/hypothesis/command/joke-candidate —
  write-gating: personal fact НЕ создаётся. Negation guard: «Я не говорил,
  что X» не создаёт positive X (truth-set D).
* Speaker ≠ subject (§7): `speaker=A, subject=Лёха`; fallback
  «subject не найден → subject=sender» ЗАПРЕЩЁН; недоказанный subject →
  unresolved-candidate / world-chat fact / skip personal write +
  диагностический reason.
* Attribution certainty ≠ truth/evidence status.
* Coreference (§8): местоимения без достаточного локального контекста →
  unresolved; `ALIAS > real_name > username` — display preference, НЕ
  слияние identities.
* Producer-validator (§13): один normalizer для всех personal-fact
  producers с исходами `accepted+source / tentative+source candidate /
  unresolved / rejected`.

Kill-switch: `MCA_CANONICAL_ATTRIBUTION_ENABLED` (+ уважение
`MCA_FACT_ATTRIBUTION_ENABLED`/`MCA_PROVENANCE_ENABLED`).
"""
from __future__ import annotations

import dataclasses
import datetime
import logging
import re

from services import mca_gates
from services.provenance import (
    ASSERTION_KINDS,
    ATTRIBUTION_METHODS,
    CHECK_KEYS,
    make_checks,
)

logger = logging.getLogger(__name__)

# ── speech acts (§6; закрытый набор) ────────────────────────────────────────
SPEECH_ACT_ASSERT = "assert"
SPEECH_ACT_DENY = "deny"
SPEECH_ACT_CORRECT = "correct"
SPEECH_ACT_QUOTE = "quote"
SPEECH_ACT_RETELL = "retell"
SPEECH_ACT_QUESTION = "question"
SPEECH_ACT_HYPOTHESIS = "hypothesis"
SPEECH_ACT_JOKE_CANDIDATE = "joke_candidate"
SPEECH_ACT_COMMAND = "command"
SPEECH_ACTS = frozenset({
    SPEECH_ACT_ASSERT, SPEECH_ACT_DENY, SPEECH_ACT_CORRECT, SPEECH_ACT_QUOTE,
    SPEECH_ACT_RETELL, SPEECH_ACT_QUESTION, SPEECH_ACT_HYPOTHESIS,
    SPEECH_ACT_JOKE_CANDIDATE, SPEECH_ACT_COMMAND,
})

# speech acts, запрещённые к записи как personal fact (write-gating, Q6).
GATED_SPEECH_ACTS = frozenset({
    SPEECH_ACT_QUESTION, SPEECH_ACT_HYPOTHESIS, SPEECH_ACT_JOKE_CANDIDATE,
    SPEECH_ACT_COMMAND,
})

# Исходы producer-validator (§13; закрытый набор).
OUTCOME_ACCEPTED = "accepted"
OUTCOME_TENTATIVE = "tentative"
OUTCOME_UNRESOLVED = "unresolved"
OUTCOME_REJECTED = "rejected"
VALIDATOR_OUTCOMES = frozenset({
    OUTCOME_ACCEPTED, OUTCOME_TENTATIVE, OUTCOME_UNRESOLVED, OUTCOME_REJECTED,
})

# Персональные местоимения без локального контекста → unresolved (§8).
_PERSONAL_PRONOUNS = frozenset({"я", "ты", "он", "она", "они", "мы", "вы"})

# Deny/коррекция-триггеры (нормализованные, deterministic; §6/§12).
_DENY_PATTERNS = (
    r"\bя\s+не\s+говорил\b", r"\bне\s+говорил\s+(это|такого|так)\b",
    r"\bя\s+этого\s+не\s+говорил\b", r"\bне\s+писал\b",
)
_CORRECTION_PATTERNS = (
    r"\bэто\s+говорил\b", r"\bговорил\s+не\s+я\b", r"\bты\s+сам\s+(это\s+)?"
    r"(написал|говорил)\b", r"\bты\s+меня\s+(с\s+ним\s+)?перепутал\b",
    r"\bэто\s+старая\s+информация\b", r"\bуже\s+не\s+актуально\b",
)
_QUOTE_MARKERS = ("сказал, что", "сказал что", "цитирую", "по словам",
                  "мол, дескать")


@dataclasses.dataclass(frozen=True)
class ClaimEnvelope:
    """C4 (§6 ТЗ): runtime-контракт утверждения (frozen).

    Persistence — существующая схема: graph_facts v17-колонки
    (subject_ref_id/attribution_method/assertion_kind/speaker_author_id) +
    EvidenceLink (`claim_key`, `checks_json`) + `mca_provenance_status`.
    Attribution certainty (`attribution_method`, `verification`) — это НЕ
    truth status: «уверенно знаем, что Вася сказал X» ≠ «X правда»."""

    speaker_entity_id: int | None
    subject_entity_id: int | None          # None = unresolved (НЕ sender!)
    mentioned_entity_ids: tuple[int, ...] = ()
    claim_text: str | None = None
    normalized_proposition: str | None = None
    speech_act: str = SPEECH_ACT_ASSERT
    stance: str | None = None              # positive|negative|neutral
    negated: bool = False
    quoted_source_ref: str | None = None
    reply_target_ref: str | None = None
    event_time: int | None = None
    valid_from: int | None = None
    valid_to: int | None = None
    source_refs: tuple[int, ...] = ()
    attribution_method: str = "unknown"    # ATTRIBUTION_METHODS
    assertion_kind: str = "unknown"        # ASSERTION_KINDS
    verification: str = "unknown"          # VERIFICATIONS
    revision: int = 1
    subject_resolution: str = "unknown"    # resolved|unresolved|unknown

    def validate(self) -> "ClaimEnvelope":
        if self.speech_act not in SPEECH_ACTS:
            raise ValueError(f"speech_act invalid: {self.speech_act!r}")
        if self.attribution_method not in ATTRIBUTION_METHODS:
            raise ValueError(
                f"attribution_method invalid: {self.attribution_method!r}")
        if self.assertion_kind not in ASSERTION_KINDS:
            raise ValueError(
                f"assertion_kind invalid: {self.assertion_kind!r}")
        return self


def canonical_attribution_enabled() -> bool:
    try:
        return mca_gates.canonical_attribution_enabled()
    except Exception:                                     # pragma: no cover
        return True


def _has_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    low = str(text or "").casefold()
    return any(re.search(p, low) for p in patterns)


def classify_speech_act(text: str | None) -> str:
    """Детерминированная классификация speech act (не NLP-комбайн, §6:
    цель — запретить опасные semantic inversions)."""
    value = str(text or "")
    low = value.casefold().strip()
    if not low:
        return SPEECH_ACT_ASSERT
    if low.endswith("?"):
        return SPEECH_ACT_QUESTION
    if low.startswith(("/", "!")) or low.startswith(("бот,", "bot,")) and \
            any(w in low for w in ("напиши", "сделай", "расскажи", "покажи")):
        return SPEECH_ACT_COMMAND
    if _has_pattern(low, _DENY_PATTERNS):
        return SPEECH_ACT_DENY
    if _has_pattern(low, _CORRECTION_PATTERNS):
        return SPEECH_ACT_CORRECT
    if any(m in low for m in _QUOTE_MARKERS) or low.startswith(("цитата",
                                                                '"', "«")):
        return SPEECH_ACT_QUOTE
    if low.startswith(("может быть", "возможно", "наверное", "кажется",
                       "вроде бы")):
        return SPEECH_ACT_HYPOTHESIS
    if low.endswith(("))", " :)")) or any(w in low for w in ("шучу", "лол",
                                                             "кек")):
        return SPEECH_ACT_JOKE_CANDIDATE
    if low.startswith(("говорят,", "говорят ", "передавали,", "слышал,")):
        return SPEECH_ACT_RETELL
    return SPEECH_ACT_ASSERT


def normalize_proposition(text: str | None) -> str | None:
    """Normalized proposition: whitespace/пунктуация-канон для claim_key."""
    value = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    value = re.sub(r"[\"«»“”]", "", value)
    return value or None


def checks_for_envelope(env: ClaimEnvelope) -> dict:
    """`checks_json` для EvidenceLink (REUSE `provenance.CHECK_KEYS`)."""
    return make_checks(
        negation=("failed" if env.negated else "ok"),
        quote=("ok" if env.quoted_source_ref else "unknown"),
        retelling=("ok" if env.speech_act == SPEECH_ACT_RETELL else "unknown"),
        joke=("ok" if env.speech_act == SPEECH_ACT_JOKE_CANDIDATE
              else "unknown"),
    )


def validate_personal_write(env: ClaimEnvelope) -> tuple[str, str | None]:
    """Write-gating personal fact по envelope.

    Возвращает (outcome, reason): outcome ∈ VALIDATOR_OUTCOMES.
    * `rejected` — negation/deny (positive fact НЕ создаётся — truth-set D);
    * `rejected` — gated speech acts (question/hypothesis/joke/command);
    * `unresolved` — subject не доказан (запрет subject=sender — truth-set
      C/L); квалифицированный reason `subject_unresolved_skipped`.
    * `tentative` — третье лицо без постоянного SourceRef (attributed
      assertion, не биография);
    * `accepted` — self-report / есть source_refs.
    Никогда не бросает."""
    if not canonical_attribution_enabled():
        return OUTCOME_TENTATIVE, None       # OFF: поведение вызывающего
    if env.speech_act in GATED_SPEECH_ACTS:
        return OUTCOME_REJECTED, f"gated_speech_act:{env.speech_act}"
    if env.negated or env.speech_act == SPEECH_ACT_DENY:
        return OUTCOME_REJECTED, "negation_guard"
    if env.subject_entity_id is None:
        return OUTCOME_UNRESOLVED, "subject_unresolved_skipped"
    if env.source_refs:
        return OUTCOME_ACCEPTED, None
    if env.attribution_method == "third_party":
        return OUTCOME_TENTATIVE, None
    if env.attribution_method == "self_report":
        return OUTCOME_ACCEPTED, None
    return OUTCOME_TENTATIVE, None


def build_envelope(
        *, speaker_entity_id: int | None, subject_entity_id: int | None,
        claim_text: str | None, mentioned_entity_ids: tuple[int, ...] = (),
        quoted_source_ref: str | None = None,
        reply_target_ref: str | None = None,
        attribution_method: str = "unknown",
        assertion_kind: str = "unknown", verification: str = "unknown",
        source_refs: tuple[int, ...] = (), revision: int = 1,
        event_time: int | None = None) -> ClaimEnvelope:
    """Собрать envelope c детерминированной классификацией speech act и
    negation-флагом (semantics inversion guard)."""
    act = classify_speech_act(claim_text)
    negated = act == SPEECH_ACT_DENY
    if act == SPEECH_ACT_QUOTE and quoted_source_ref is None:
        # цитата без резолвнутого источника — источник остаётся unknown
        pass
    stance = "negative" if negated else "positive"
    subject_resolution = ("resolved" if subject_entity_id is not None
                          else "unresolved")
    return ClaimEnvelope(
        speaker_entity_id=speaker_entity_id,
        subject_entity_id=subject_entity_id,
        mentioned_entity_ids=tuple(dict.fromkeys(mentioned_entity_ids)),
        claim_text=claim_text,
        normalized_proposition=normalize_proposition(claim_text),
        speech_act=act, stance=stance, negated=negated,
        quoted_source_ref=quoted_source_ref,
        reply_target_ref=reply_target_ref,
        event_time=event_time, source_refs=source_refs,
        attribution_method=(attribution_method
                            if attribution_method in ATTRIBUTION_METHODS
                            else "unknown"),
        assertion_kind=(assertion_kind if assertion_kind in ASSERTION_KINDS
                        else "unknown"),
        verification=(verification if verification in
                      {"verified", "rejected", "tentative", "unknown"}
                      else "unknown"),
        revision=max(1, int(revision or 1)),
        subject_resolution=subject_resolution)


def resolve_coreference(text: str | None, *, speaker_entity_id: int | None,
                        speaker_display_name: str | None = None,
                        reply_target_entity_id: int | None = None,
                        quoted_speaker_entity_id: int | None = None,
                        candidate_names: list[tuple[str, int]] | None = None,
                        ) -> tuple[str, int | None]:
    """Минимальный coreference resolver (§8): возвращает (resolution, id).

    * «я» → speaker (self-report — только если speaker известен);
    * «ты» → reply-адресат (только при известном native reply target);
    * «он/она/они» → только явный candidate по имени ИЛИ quoted speaker;
      без достаточного локального контекста → unresolved;
    * имя → точное совпадение по `candidate_names` (ALIAS > real_name >
      username — display preference, НЕ слияние identities; двух разных
      ID с одним именем не сливаем — ambiguous → unresolved).
    Никогда не возвращает sender'а для третьего лица (§7)."""
    value = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    if not value:
        return "unresolved", None
    first_token = re.findall(r"[а-яёa-z]+", value)[:1]
    head = first_token[0] if first_token else ""
    if head == "я" and speaker_entity_id is not None:
        return "resolved", speaker_entity_id
    if head == "ты" and reply_target_entity_id is not None:
        return "resolved", reply_target_entity_id
    if head in ("он", "она", "они"):
        if quoted_speaker_entity_id is not None:
            return "resolved", quoted_speaker_entity_id
        matches: set[int] = set()
        if candidate_names:
            for name, eid in candidate_names:
                if name and name.strip().casefold() == value:
                    matches.add(eid)
        if len(matches) == 1:
            return "resolved", next(iter(matches))
        return "unresolved", None
    if candidate_names:
        matches = {eid for name, eid in candidate_names
                   if name and name.strip().casefold() == value}
        if len(matches) == 1:
            return "resolved", next(iter(matches))
        if len(matches) > 1:
            return "unresolved", None        # same display name — не слияние
    return "unresolved", None


def gate_personal_text_write(text: str | None) -> tuple[str, str | None]:
    """Write-gating personal fact по ТЕКСТУ (subject-атрибуцию выполняет
    store: personal-скоуп «запомни» = self-report канон-автора).

    Возвращает (outcome, reason): `rejected` для negation/deny и gated
    speech acts; `accepted` иначе (subject-scope решает вызывающий).
    Используется producer'ами без entity-графа (memory-команды)."""
    if not canonical_attribution_enabled():
        return OUTCOME_ACCEPTED, None       # OFF: паритет baseline
    act = classify_speech_act(text)
    if act in GATED_SPEECH_ACTS:
        return OUTCOME_REJECTED, f"gated_speech_act:{act}"
    if act == SPEECH_ACT_DENY:
        return OUTCOME_REJECTED, "negation_guard"
    return OUTCOME_ACCEPTED, None


def is_correction_phrase(text: str | None) -> bool:
    """Фразы-триггеры correction path (§12; deterministic, без LLM)."""
    return _has_pattern(str(text or ""), _CORRECTION_PATTERNS)


def is_deny_phrase(text: str | None) -> bool:
    return _has_pattern(str(text or ""), _DENY_PATTERNS)


def checks_json_for(env: ClaimEnvelope) -> str | None:
    """JSON checks (R17-safe) — REUSE `provenance.normalize_checks`."""
    try:
        from services.provenance import normalize_checks
        return normalize_checks(checks_for_envelope(env))
    except Exception:                                     # pragma: no cover
        return None


# ── MCA-08 (T-4898/T-4900; ADR-1028-11 D6/D7): речевые сигналы ответа ───────
# Фасад над существующим `classify_speech_act` (второй классификатор
# запрещён). R17-safe: в DTO/блок — только коды/флаги, без сырого текста.
# Поля M-MCA07-2 (EvidenceBundle) не занимаются; CoordinatorDecision/
# action-schema не трогаются — сигнал читается только сборкой промпта.

CLARIFY_NONE = "none"
CLARIFY_ASK = "ask"
CLARIFY_ASSUME = "assume"
CLARIFY_ACTIONS = frozenset({CLARIFY_NONE, CLARIFY_ASK, CLARIFY_ASSUME})

QUOTE_ATTRIBUTION_KNOWN = "known"
QUOTE_ATTRIBUTION_UNKNOWN = "unknown"
QUOTE_ATTRIBUTIONS = frozenset({QUOTE_ATTRIBUTION_KNOWN,
                                QUOTE_ATTRIBUTION_UNKNOWN})

# Короткие зависимые реплики (§7): закрытый маркер-набор; «в любом падеже» —
# подстрочное сравнение casefold-текста. >3 слов → не короткая реплика.
_SHORT_DEPENDENCY_MARKERS: tuple[str, ...] = (
    "почему", "зачем", "а как", "как так", "и что", "ну и",
    "что?", "он?", "она?", "это?", "правда?", "серьёзно?")
_MAX_SHORT_DEPENDENCY_WORDS = 3

# Отрицание (§6): закрытый канон слов (тот же, что G2 §8) — «учти отрицание
# буквально», без переворота «не» в утверждение.
_NEGATION_RE = re.compile(
    r"(?<![а-яёa-z])(?:не|ни|никогда|без|нет)(?![а-яёa-z])",
    re.IGNORECASE)

# Canon carrier cap (spec §6): ≤500 символов.
_SPEECH_BLOCK_CAP = 500


@dataclasses.dataclass(frozen=True)
class SpeechUnderstanding:
    """MCA-08 (D6): речевой сигнал ответного пути (frozen, R17-safe)."""

    speech_act: str = SPEECH_ACT_ASSERT
    quote: bool = False
    quote_attribution: str = QUOTE_ATTRIBUTION_UNKNOWN
    reply_parent: bool = False
    short_dependency: bool = False
    humor_risk: bool = False
    negation: bool = False
    clarify: str = CLARIFY_NONE
    flags: tuple[str, ...] = ()
    # EVOL-015: дословный выделенный фрагмент (Telegram quote text), когда
    # он реально доставлен метаданными; "" = цитаты нет/текст неизвестен
    # (никогда не выдумывается — рендер предмета только при непустом).
    quote_text: str = ""

    @property
    def active(self) -> bool:
        """Активный сигнал → блок рендерится (spec §6)."""
        return bool(self.quote or self.humor_risk or self.negation
                    or self.clarify != CLARIFY_NONE)


def is_short_dependency(text: str | None) -> bool:
    """Закрытый маркер-набор §7: короткая зависимая реплика (≤3 слов)."""
    value = " ".join(str(text or "").split()).casefold()
    if not value:
        return False
    words = re.findall(r"[а-яёa-z0-9]+", value)
    if len(words) > _MAX_SHORT_DEPENDENCY_WORDS:
        return False
    return any(marker in value for marker in _SHORT_DEPENDENCY_MARKERS)


def clarify_action(*, short_dependency: bool, has_reply_parent: bool,
                   is_group: bool, reply_parent_from_bot: bool = False,
                   reply_parent_ends_with_question: bool = False) -> str:
    """D7 → ASAP 2 Direct Chat (§3.3/§4.4 source-2026-10-22.md,
    23.10.2026): автономное право Speech Understanding требовать вопрос
    СНЯТО — сигнал ``clarify=ask`` (короткая реплика ∧ нет reply-родителя
    ∧ групповой чат) больше не выдаётся; решение об уточнении принимает
    только L1 по контракту канона. Описательный признак
    ``short_dependency`` остаётся обычным флагом (не приказ). Anti-loop
    сохранён: родитель — вопрос бота → ``assume`` (явное допущение, без
    повторного вопроса). Всё остальное — ``none``.
    """
    if not short_dependency:
        return CLARIFY_NONE
    if has_reply_parent:
        if reply_parent_from_bot and reply_parent_ends_with_question:
            return CLARIFY_ASSUME
        return CLARIFY_NONE
    # Прежняя ветка CLARIFY_ASK (group ∧ short ∧ без родителя) удалена:
    # второй диктующий путь «уточни» в L1/L2 не подаётся (§3.3). Новых
    # маркеров/списков взамен не вводится — нужную модельную логику содержит
    # канон L1.
    return CLARIFY_NONE


def build_speech_understanding(
        text: str | None, *,
        has_reply_parent: bool = False,
        is_group: bool = False,
        reply_parent_from_bot: bool = False,
        reply_parent_ends_with_question: bool = False,
        quote_attribution_known: bool = False,
        quote_text_present: bool = False,
        quote_text: str | None = None) -> SpeechUnderstanding:
    """D6/D7: собрать сигнал ответа (REUSE `classify_speech_act`).

    `quote_text_present` — структурный tg/quote-маркер сообщения;
    `quote_attribution_known` — фактический автор из уже построенного
    mca-22-контура (`bundle.quoted_speaker`); повторный вызов резолвера
    цитат здесь запрещён — автор сюда только передаётся.
    EVOL-015: `quote_text` — дословный выделенный фрагмент из Telegram
    quote-метаданных; None/"" → прежнее поведение (байт-паритет).
    """
    value = str(text or "")
    act = classify_speech_act(value)
    manual_quote = any(
        ln.strip().startswith(">") and len(ln.strip()) > 1
        for ln in value.splitlines())
    quote = bool(act == SPEECH_ACT_QUOTE or manual_quote
                 or quote_text_present)
    # D7: команда — не материалная короткая реплика (уточнение не задаётся).
    short_dep = bool(is_short_dependency(value)
                     and act != SPEECH_ACT_COMMAND)
    humor_risk = act == SPEECH_ACT_JOKE_CANDIDATE
    negation = bool(act == SPEECH_ACT_DENY or _NEGATION_RE.search(value))
    clarify = clarify_action(
        short_dependency=short_dep, has_reply_parent=has_reply_parent,
        is_group=is_group, reply_parent_from_bot=reply_parent_from_bot,
        reply_parent_ends_with_question=reply_parent_ends_with_question)
    attribution = (QUOTE_ATTRIBUTION_KNOWN if quote_attribution_known
                   else QUOTE_ATTRIBUTION_UNKNOWN)
    flags: list[str] = []
    if act != SPEECH_ACT_ASSERT:
        flags.append(f"act:{act}")
    if manual_quote or quote_text_present:
        flags.append("quote_marker")
    if quote:
        flags.append(f"quote_attribution:{attribution}")
    if short_dep:
        flags.append("short_dependency")
    if has_reply_parent:
        flags.append("reply_parent")
    if reply_parent_from_bot:
        flags.append("parent_bot")
    if clarify != CLARIFY_NONE:
        flags.append(f"clarify:{clarify}")
    return SpeechUnderstanding(
        speech_act=act, quote=quote, quote_attribution=attribution,
        reply_parent=bool(has_reply_parent), short_dependency=short_dep,
        humor_risk=humor_risk, negation=negation, clarify=clarify,
        flags=tuple(flags),
        quote_text=str(quote_text or "").strip())


# ── P0-HA QUALITY (волна 4b, §12–§13 ТЗ source-2026-10-29.md) ───────────────
# Детерминированные страховки качества анализа участников и событий. НЕ
# второй смысловой классификатор и НЕ новый движок: закрытые маркер-наборы
# (прецедент `classify_speech_act` §6) + структурные поля канонических строк
# (`format_context_item`: «[ts | Имя | tg:N | Переслано: X]: текст»).
# Инструкционная часть (различение типов/запрет обобщений/атрибуция
# пересылок/запрет придуманной статистики) — константы
# `HISTORY_EXTRACTION_QUALITY_BLOCK`/`HISTORY_COVERAGE_ASSEMBLY_BLOCK` в
# services/prompt_style_blocks.py; R17: только коды/флаги, без сырого
# пользовательского текста в логи/телеметрию.

FINDING_KIND_REPEAT_THEME = "repeat_theme"        # повторяющиеся темы
FINDING_KIND_DISPUTE = "dispute"                  # продолжительные споры
FINDING_KIND_BRIEF_EVENT = "brief_event"          # краткие события
FINDING_KIND_SINGLE_REMARK = "single_remark"      # единичные реплики
FINDING_KIND_JOKE = "joke"                        # шутки
FINDING_KIND_FORWARDED = "forwarded"              # пересланные публикации
FINDING_KIND_EXTERNAL_NEWS = "external_news"      # внешние новости
FINDING_KIND_PARTICIPANT_CLAIM = "participant_claim"  # прямые утверждения
FINDING_KIND_BOT_STATEMENT = "bot_statement"      # собственные высказывания
FINDING_KINDS = frozenset({
    FINDING_KIND_REPEAT_THEME, FINDING_KIND_DISPUTE, FINDING_KIND_BRIEF_EVENT,
    FINDING_KIND_SINGLE_REMARK, FINDING_KIND_JOKE, FINDING_KIND_FORWARDED,
    FINDING_KIND_EXTERNAL_NEWS, FINDING_KIND_PARTICIPANT_CLAIM,
    FINDING_KIND_BOT_STATEMENT,
})

# Устойчивая характеристика личности допустима только для типов, которые по
# определению повторяются (§12 строка 469: единичная шутка/реплика — не
# черта) и подтверждены минимум двумя разными сообщениями выборки.
TRAIT_CAPABLE_KINDS = frozenset({FINDING_KIND_REPEAT_THEME,
                                 FINDING_KIND_DISPUTE})
MIN_TRAIT_REFS = 2

# Закрытые маркер-наборы (casefold; ПО ЛЕВОЙ ГРАНИЦЕ СЛОВА — «сми» внутри
# «космический» маркером не считается; префикс-глаголы покрытия —
# «поспор»/«заспор»/«пошут»/«пообещ» — частью того же набора). Порядок
# проверки в `classify_finding_kind` значим.
_FORWARD_MARKERS = ("переслан", "переслал", "форвард", "forward")
_NEWS_MARKERS = ("новост", "статья", "статьи", "сми", "пресс",
                 "репортаж", "в сети", "в интернете")
_JOKE_MARKERS = ("шутк", "шучу", "шутил", "пошут", "прикол", "сарказм",
                 "ирони", "лол", "кек")
_DISPUTE_MARKERS = ("спор", "поспор", "заспор", "разноглас", "конфликт",
                    "поссор", "перебран", "стычка")
_REPEAT_MARKERS = ("повторя", "снова", "опять", "регулярно", "постоянно",
                   "не в первый раз", "возвращается к теме")
_CLAIM_MARKERS = ("заявил", "заявила", "утвержда", "утвержд", "обещал",
                  "обещала", "пообещ", "по его словам", "по её словам",
                  "сказал, что")
_SINGLE_MARKERS = ("единичн", "одна реплика", "одна фраза", "одноразов",
                   "лишь одн")
# Обобщающий язык «устойчивой характеристики» в note (строка 469; закрытый
# набор для `note_claims_stable_trait` — страховка, не смысловой разбор).
_TRAIT_NOTE_MARKERS = (
    "любит", "обожает", "ненавидит", "терпеть не может",
    "склонен", "склонна", "склонны",
    "по характеру", "по натуре", "черта характера",
    "в его характере", "в её характере",
    "всегда", "постоянно", "регулярно", "каждый раз",
    "известен тем", "известна тем", "славится",
)


def _marker_hit(text: str, marker: str) -> bool:
    """Маркер по левой границе слова (блокер 1 review-w4: «сми» — подстрока
    «космический» — маркером не считается). Никогда не бросает."""
    try:
        return re.search(r"(?<!\w)" + re.escape(marker), text) is not None
    except re.error:                                      # pragma: no cover
        return marker in text


# Числовые утверждения в note: «N раз», «N сообщений», «N упоминаний» —
# проверяемы по числу уникальных refs события (§13 строка 487).
_COUNT_CLAIM_RE = re.compile(
    r"(\d+)\s*(?:раз|сообщени|упоминан|материал|случа)")
# Календарная дата в note: только полная «ДД.ММ.ГГГГ» (без ложных
# срабатываний на «2.10»/время «12:30»); проверяемость — по датам refs.
_DATE_CLAIM_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")


@dataclasses.dataclass(frozen=True)
class FindingIdentity:
    """Идентичность строки канонической стенограммы (P0-HA QUALITY).

    ``display_name`` — имя из заголовка строки (алиас-каскад R7 по user_id,
    повторно НЕ резолвится); ``ref`` — id сообщения («tg:123»), основной
    ключ трассировки утверждений; ``user_id`` — Telegram user_id автора из
    суффикса «Имя [uid]» (волна 4, блокер 2 review-w4: строки выборки несут
    uid тем же приёмом, что `_speaker_tag`; uid — первичная идентичность
    участника, ref сообщения — ключ трассировки, а не личность);
    ``forward_source`` — исходный автор из поля «Переслано: X» ("" — не
    пересылка). Похожие имена разных id НИКОГДА не сливаются (строка 473;
    проверка H25) — см. `identity_matches`."""

    display_name: str = ""
    ref: str = ""
    forward_source: str = ""
    is_forward: bool = False
    user_id: int | None = None


_HISTORY_LINE_HEAD_RE = re.compile(r"\]: ")
_HISTORY_REF_FORMAT_RE = re.compile(r"^(?:tg|msg|fact):\d+$")
_HISTORY_STAMP_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}(?:\s+\d{1,2}:\d{2})?$"
                               r"|^\d{2}\.\d{4}$")
_FORWARD_FIELD_PREFIX = "Переслано:"
_UID_SUFFIX_RE = re.compile(r"\[(\d{1,18})\]\s*$")


def parse_finding_identity(line: str | None) -> FindingIdentity:
    """Разобрать заголовок канонической строки выборки (§12 материал).

    Формат `format_context_item`: «[ДД.ММ.ГГГГ ЧЧ:ММ | Имя | tg:123 |
    Переслано: X]: текст» — поля-метаданные отсутствуют вместе с
    разделителем. Разметки нет → пустая identity (строка без заголовка не
    даёт ни ref, ни автора — refs на неё не дают трассировки). Никогда не
    бросает."""
    value = str(line or "")
    if not value.startswith("["):
        return FindingIdentity()
    match = _HISTORY_LINE_HEAD_RE.search(value)
    if match is None:
        return FindingIdentity()
    head = value[1:match.start()]
    ref = ""
    forward_source = ""
    name = ""
    for field in head.split("|"):
        field = field.strip()
        if not field:
            continue
        if not ref and _HISTORY_REF_FORMAT_RE.match(field):
            ref = field
            continue
        if field.startswith(_FORWARD_FIELD_PREFIX):
            forward_source = field[len(_FORWARD_FIELD_PREFIX):].strip()
            continue
        if not name and not _HISTORY_STAMP_RE.match(field):
            name = field
    user_id = None
    uid_match = _UID_SUFFIX_RE.search(name)
    if uid_match is not None:
        try:
            user_id = int(uid_match.group(1))
            name = name[:uid_match.start()].rstrip()
        except ValueError:                                # pragma: no cover
            user_id = None
    return FindingIdentity(display_name=name, ref=ref,
                           forward_source=forward_source,
                           is_forward=bool(forward_source),
                           user_id=user_id)


def finding_attribution_owner(identity: FindingIdentity | None) -> str:
    """Автор содержимого строки (строка 471; проверка H26): для пересланной
    строки — исходный автор из поля «Переслано», а НЕ тот, кто переслал;
    для обычной — автор строки. Пустая identity → ""."""
    if identity is None:
        return ""
    if identity.is_forward and identity.forward_source:
        return identity.forward_source
    return identity.display_name


def attribution_conflict(note: str | None,
                         identity: FindingIdentity | None) -> bool:
    """Пересылка приписана переславшему (H26): note упоминает автора
    пересылки, но не исходного автора. Только для is_forward; обычные
    строки конфликта не дают. Пограничная эвристика по границам слова —
    страховка, не смысловой разбор. Никогда не бросает."""
    if identity is None or not identity.is_forward:
        return False
    owner = identity.forward_source
    text = str(note or "")
    if owner:
        if re.search(r"(?<![\w])" + re.escape(owner) + r"(?![\w])",
                     text, re.IGNORECASE):
            return False
    forwarder = identity.display_name
    if not forwarder:
        return False
    return bool(re.search(r"(?<![\w])" + re.escape(forwarder) + r"(?![\w])",
                          text, re.IGNORECASE))


def _identity_key(value) -> tuple:
    """Ключ идентичности (волна 4, блокер 2 review-w4): у FindingIdentity —
    Telegram user_id («uid», …), без него — ref сообщения («ref», …);
    строка трактуется как ref (совместимость прежних вызовов)."""
    if isinstance(value, FindingIdentity):
        if value.user_id not in (None, 0):
            return ("uid", int(value.user_id))
        return ("ref", str(value.ref or "").strip())
    return ("ref", str(value or "").strip())


def identity_matches(a, b) -> bool:
    """Строгая идентичность участников (строка 475): Telegram user_id —
    ПЕРВИЧНЫЙ ключ (блокер 2 review-w4: два uid с одним именем — разные
    люди, два сообщения одного uid — один человек; ref/id сообщения —
    не личность). Без uid у сравниваемых — совместимый падение на
    совпадение ref/id сообщения. Пустой ключ идентичности не
    устанавливает. Никогда не бросает."""
    key_a, key_b = _identity_key(a), _identity_key(b)
    return key_a == key_b and bool(key_a[1])


def classify_finding_kind(note: str | None, *, distinct_refs: int = 0,
                          is_forward: bool = False,
                          is_bot_author: bool = False) -> str:
    """Детерминированный тип находки (§12 перечень строк 459-467).

    Приоритет: структурный флаг пересылки → автор-бот → маркеры note
    (новости → шутка → спор → повтор → утверждение → единичное) → fallback
    по числу refs: ≤1 — единичная реплика, иначе краткое событие. Это
    страховка поверх инструкций извлечения, не второй NLP: маркеры
    закрытые, неизвестный текст даёт консервативный fallback. Никогда не
    бросает."""
    text = " ".join(str(note or "").split()).casefold()
    if is_forward or any(_marker_hit(text, m) for m in _FORWARD_MARKERS):
        return FINDING_KIND_FORWARDED
    if is_bot_author:
        return FINDING_KIND_BOT_STATEMENT
    if any(_marker_hit(text, m) for m in _NEWS_MARKERS):
        return FINDING_KIND_EXTERNAL_NEWS
    if any(_marker_hit(text, m) for m in _JOKE_MARKERS):
        return FINDING_KIND_JOKE
    if any(_marker_hit(text, m) for m in _DISPUTE_MARKERS):
        return FINDING_KIND_DISPUTE
    if any(_marker_hit(text, m) for m in _REPEAT_MARKERS):
        return FINDING_KIND_REPEAT_THEME
    if any(_marker_hit(text, m) for m in _CLAIM_MARKERS):
        return FINDING_KIND_PARTICIPANT_CLAIM
    if any(_marker_hit(text, m) for m in _SINGLE_MARKERS):
        return FINDING_KIND_SINGLE_REMARK
    try:
        refs = max(0, int(distinct_refs))
    except (TypeError, ValueError):
        refs = 0
    return (FINDING_KIND_SINGLE_REMARK if refs <= 1
            else FINDING_KIND_BRIEF_EVENT)


def stable_trait_claim_allowed(kind: str, distinct_ref_count: int) -> bool:
    """Разрешена ли устойчивая характеристика личности (строка 469): тип
    должен быть повторяемым по определению И подтверждён минимум
    `MIN_TRAIT_REFS` разными сообщениями выборки. Неизвестный тип → False
    (консервативно). Никогда не бросает."""
    if kind not in TRAIT_CAPABLE_KINDS:
        return False
    try:
        refs = max(0, int(distinct_ref_count))
    except (TypeError, ValueError):
        return False
    return refs >= MIN_TRAIT_REFS


def note_claims_stable_trait(note: str | None) -> bool:
    """Note утверждает устойчивую характеристику/обобщение о человеке
    (строка 469): закрытый маркер-набор обобщающего языка по границе
    слова (страховка, не смысловой разбор). Неизвестный текст → False
    (консервативно — черта не заявлена). Никогда не бросает."""
    text = " ".join(str(note or "").split()).casefold()
    if not text:
        return False
    return any(_marker_hit(text, m) for m in _TRAIT_NOTE_MARKERS)


def validate_finding_refs(refs, known_refs) -> tuple[list, list]:
    """Трассировка утверждений (§13 строка 483): из refs события остаются
    только refs, реально входящие в выборку; остальные — dropped с
    сохранением порядка. Никогда не бросает."""
    known = {str(r).strip() for r in (known_refs or ()) if str(r).strip()}
    kept, dropped = [], []
    for raw in (refs or ()):
        ref = str(raw).strip()
        if not ref:
            continue
        (kept if ref in known else dropped).append(ref)
    return kept, dropped


def invented_count_violations(note: str | None,
                              distinct_ref_count: int) -> list[int]:
    """Придуманная статистика (строка 487): числовые утверждения «N раз /
    N сообщений / N упоминаний» в note, которым не хватает подтверждения
    refs выборки (N > число уникальных refs события). Никогда не бросает."""
    text = " ".join(str(note or "").split()).casefold()
    try:
        refs = max(0, int(distinct_ref_count))
    except (TypeError, ValueError):
        refs = 0
    out: list[int] = []
    for match in _COUNT_CLAIM_RE.finditer(text):
        try:
            claimed = int(match.group(1))
        except (TypeError, ValueError):          # pragma: no cover — \d+
            continue
        if claimed > refs:
            out.append(claimed)
    return out


def invented_date_violations(note: str | None, ts_by_ref) -> list[str]:
    """Придуманные даты (строка 487): полная дата «ДД.ММ.ГГГГ» в note без
    ни одного ref-сообщения выборки с этой датой (UTC ±1 сутки — допуск
    локального сдвига чата без чтения per-chat tz). Возвращает ТОЧНЫЕ
    подстроки note в найденном написании — включая день/месяц без ведущего
    нуля («5.10.2024», «15.3.2025»): строка флага совпадает с тем, что
    срезается из note (блокер B review-w4-fix). Никогда не бросает."""
    text = str(note or "")
    if not text:
        return []
    matched: list[tuple[str, int, int, int]] = []
    for match in _DATE_CLAIM_RE.finditer(text):
        try:
            day, month, year = (int(match.group(1)), int(match.group(2)),
                                int(match.group(3)))
            datetime.date(year, month, day)
        except (TypeError, ValueError):          # не календарная дата
            continue
        matched.append((match.group(0), day, month, year))
    if not matched:
        return []
    stamps: list[int] = []
    for value in (ts_by_ref or {}).values():
        try:
            stamps.append(int(value))
        except (TypeError, ValueError):
            continue
    out: list[str] = []
    for value, day, month, year in matched:
        supported = False
        for seconds in stamps:
            try:
                moment = datetime.datetime.fromtimestamp(
                    seconds, datetime.timezone.utc)
            except (ValueError, OSError, OverflowError):
                continue
            for offset in (-1, 0, 1):
                shifted = moment + datetime.timedelta(days=offset)
                if (shifted.day, shifted.month, shifted.year) == \
                        (day, month, year):
                    supported = True
                    break
            if supported:
                break
        if not supported and value not in out:
            out.append(value)
    return out


def render_speech_block(u: SpeechUnderstanding | None) -> str:
    """D6: `<Speech_Understanding>` — канон-ветки, только при активном
    сигнале; cap ≤500 символов; пусто → "" (паритет)."""
    if u is None or not u.active:
        return ""
    lines: list[str] = []
    # EVOL-015: доставленный дословный фрагмент — ПРЕДМЕТ текущего вопроса;
    # строка ПЕРВАЯ (приоритет), только при реально полученном тексте
    # (никогда не выдумывается). Схлопывание переносов — как в каноне.
    u_quote_text = " ".join(str(u.quote_text or "").split())
    if u_quote_text:
        lines.append("Предмет вопроса — выделенная цитата (её автор — не "
                     f"ты): «{u_quote_text}». Полное исходное сообщение — "
                     "контекст, отвечай по выделенному фрагменту.")
    if u.quote:
        lines.append("Цитата принадлежит её автору: не приписывай чужие слова "
                     "себе; если автор не установлен — не додумывай его.")
    if u.humor_risk:
        lines.append("Сообщение похоже на шутку/сарказм/гиперболу: не "
                     "превращай его в биографический факт.")
    if u.negation:
        lines.append("Учти отрицание буквально: не переворачивай «не» в "
                     "утверждение.")
    # ── ASAP 2 Direct Chat (§3.3/§4.4 source-2026-10-22.md): директива
    # CLARIFY_ASK («Если без уточнения ... задай ровно ОДИН ... вопрос»)
    # СНЯТА — второго модельного приказа «уточни» нет; решение об уточнении
    # — только L1. Assume-строка (анти-переспрос) сохранена.
    if u.clarify == CLARIFY_ASSUME:
        lines.append("Не переспрашивай: ответь с явным допущением, как ты "
                     "понял реплику.")
    if not lines:
        return ""
    head, tail = "<Speech_Understanding>\n", "\n</Speech_Understanding>"
    block = head + "\n".join(lines) + tail
    if len(block) > _SPEECH_BLOCK_CAP:      # дефенс; канон укладывается
        keep: list[str] = []
        used = len(head) + len(tail)
        for line in lines:
            if used + len(line) + 1 > _SPEECH_BLOCK_CAP:
                break
            keep.append(line)
            used += len(line) + 1
        block = head + "\n".join(keep) + tail
    return block
