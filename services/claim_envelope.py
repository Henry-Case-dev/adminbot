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
    """D7: политика уточнения — детерминированная, ≤1 вопрос на ответ.

    `ask` — материалная неоднозначность: короткая зависимая реплика ∧ нет
    reply-родителя ∧ групповой чат. Anti-loop: родитель — вопрос бота →
    `assume` (явное допущение, без повторного вопроса); повторных переспросов
    нет структурно (блок строится один раз на ответ). Всё остальное — `none`.
    """
    if not short_dependency:
        return CLARIFY_NONE
    if has_reply_parent:
        if reply_parent_from_bot and reply_parent_ends_with_question:
            return CLARIFY_ASSUME
        return CLARIFY_NONE
    if not is_group:
        return CLARIFY_NONE
    return CLARIFY_ASK


def build_speech_understanding(
        text: str | None, *,
        has_reply_parent: bool = False,
        is_group: bool = False,
        reply_parent_from_bot: bool = False,
        reply_parent_ends_with_question: bool = False,
        quote_attribution_known: bool = False,
        quote_text_present: bool = False) -> SpeechUnderstanding:
    """D6/D7: собрать сигнал ответа (REUSE `classify_speech_act`).

    `quote_text_present` — структурный tg/quote-маркер сообщения;
    `quote_attribution_known` — фактический автор из уже построенного
    mca-22-контура (`bundle.quoted_speaker`); повторный вызов резолвера
    цитат здесь запрещён — автор сюда только передаётся.
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
        flags=tuple(flags))


def render_speech_block(u: SpeechUnderstanding | None) -> str:
    """D6: `<Speech_Understanding>` — канон-ветки, только при активном
    сигнале; cap ≤500 символов; пусто → "" (паритет)."""
    if u is None or not u.active:
        return ""
    lines: list[str] = []
    if u.quote:
        lines.append("Цитата принадлежит её автору: не приписывай чужие слова "
                     "себе; если автор не установлен — не додумывай его.")
    if u.humor_risk:
        lines.append("Сообщение похоже на шутку/сарказм/гиперболу: не "
                     "превращай его в биографический факт.")
    if u.negation:
        lines.append("Учти отрицание буквально: не переворачивай «не» в "
                     "утверждение.")
    if u.clarify == CLARIFY_ASK:
        lines.append("Если без уточнения ответ может быть не о том — задай "
                     "ровно ОДИН короткий уточняющий вопрос, не переспрашивай "
                     "дальше.")
    elif u.clarify == CLARIFY_ASSUME:
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
