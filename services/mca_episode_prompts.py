"""Раунд 10.27 (MCA Wave 2, `mca-05-episodes-stories`, ADR-1027-12 D5/D7) —
канон промптов извлечения эпизодов и подтверждения продолжений.

Ключи канона: ``episodes_extract`` / ``continuation_confirm`` (Q7/D5);
canon-версии трекаются константами (прецедент ETL-промптов `dossier_prompts`:
внутренние пайплайн-промпты не входят в PG-реестр `prompt_migrations` —
«EXTRACT_PROMPT — ETL-экстрактор, не user-facing»; GEN-R2 — существующие
провайдеры/маршрутизация, интерфейс `llm.generate` как у `LoreCompilerService`).

Контракт LLM (D5): строгий JSON; участники — устойчивые ID (mca-03);
утверждения — с message-refs (→ SourceRef, контракт (k) spec §3);
неизвестные детали — **unknown** (не факт); офлайн-валидаторы работают без
LLM на фикстурах (SC-08). Unknown не превращается в факт: утверждение без
валидного ref-а переносится в ``unknown``, а не сохраняется как факт.

R17: промпты не содержат секретов; в логи — только коды/числа.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# ── canon-версии (участвуют в extraction_version записей) ───────────────────
EPISODES_EXTRACT_PROMPT_KEY = "episodes_extract"
EPISODES_EXTRACT_CANON_VERSION = "episodes_extract-1"
CONTINUATION_CONFIRM_PROMPT_KEY = "continuation_confirm"
CONTINUATION_CONFIRM_CANON_VERSION = "continuation_confirm-1"

# «Исход неизвестен» — честный маркер (§9.1; финал не выдумывается).
# Единый источник значения: database.py реэкспортирует как
# EPISODE_UNKNOWN_OUTCOME (v21-константы).
EPISODE_UNKNOWN_OUTCOME = "исход неизвестен"

# Лимиты полей контракта (R17-safe, детерминированные капы).
_TITLE_MAX = 200
_SUMMARY_MAX = 2000
_CLAIM_TEXT_MAX = 500
_CLAIMS_MAX = 40
_UNKNOWN_MAX = 20
_QUESTIONS_MAX = 10
_RATIONALE_MAX = 400
_ENTITY_TOKEN_MIN = 3

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_extract_system() -> str:
    """Системный канон извлечения эпизода (``episodes_extract``)."""
    return (
        "Ты — экстрактор эпизодов разговора. Тебе дают хронологическую "
        "подборку сообщений одного чата. Извлеки СВЯЗНЫЙ эпизод: о чём "
        "шло обсуждение, кто участвовал, что фактически установлено.\n"
        "Ответь СТРОГО одним JSON-объектом без пояснений:\n"
        '{"title": "краткое название (<=200 символов)", '
        '"summary": "краткое содержание (<=2000 символов)", '
        '"participants": ["ID-участника", ...], '
        '"claims": [{"text": "фактическое утверждение", '
        '"refs": ["ключ сообщения", ...]}, ...], '
        '"outcome_known": true|false, '
        '"outcome": "итог, если известен, иначе null", '
        '"open_questions": ["открытый вопрос", ...], '
        '"unknown": ["что осталось неизвестно", ...], '
        '"multi_topic": true|false}\n'
        "Правила:\n"
        "1. participants — только ID из списка участников подборки; "
        "имена запрещены.\n"
        "2. Каждое утверждение (claims) ОБЯЗАНО ссылаться на ключи "
        "сообщений-источников (refs). Утверждение без источника — "
        "не утверждай, вынеси в unknown.\n"
        "3. Неизвестные детали пиши в unknown. НЕ выдумывай факты, "
        "итоги и даты.\n"
        "4. Если итог события неизвестен — outcome_known=false, "
        "outcome=null. Финал не выдумывается.\n"
        "5. Не используй пересказы бота как независимое подтверждение.\n"
        "6. Если подборка содержит ДВА и более НЕЗАВИСИМЫХ разговора "
        "(разные темы без связи) — постави multi_topic=true."
    )


def build_extract_user(window_lines: list[str] | tuple[str, ...],
                       participant_ids: list[str] | tuple[str, ...]) -> str:
    """User-промпт извлечения: строки окна + список допустимых ID."""
    lines = "\n".join(str(line) for line in (window_lines or ()))
    ids = ", ".join(str(p) for p in (participant_ids or ())) or "(нет)"
    return (
        f"Участники подборки (допустимые ID): {ids}\n"
        f"Сообщения:\n{lines}\n\n"
        "Извлеки эпизод по контракту (строгий JSON)."
    )


def parse_extract_answer(raw: str | None) -> dict | None:
    """Разбор ответа LLM в сырой payload (или None — невалидный ответ).

    Только структурный разбор: JSON-объект, обязательные ключи-типы.
    Семантическую валидацию (refs/participants) делает
    :func:`validate_extract_payload` — офлайн, без LLM."""
    if raw is None:
        return None
    match = _JSON_OBJECT_RE.search(str(raw))
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    claims = data.get("claims")
    if claims is not None and not isinstance(claims, list):
        return None
    for claim in claims or ():
        if not isinstance(claim, dict) or not isinstance(
                claim.get("refs", []), list):
            return None
    for key in ("participants", "open_questions", "unknown"):
        value = data.get(key)
        if value is not None and not isinstance(value, list):
            return None
    return data


def validate_extract_payload(payload: dict | None, *,
                             member_keys: set[str] | frozenset[str],
                             participant_ids: set[str] | frozenset[str],
                             ) -> dict:
    """Офлайн-валидатор контракта извлечения (SC-08; fixture без LLM).

    Возвращает нормализованный payload:
      ``{title, summary, participants, claims, outcome_known, outcome,
      open_questions, unknown, dropped_claims}``.
    Правила (D5/§8.1):
      * участник не из подборки → отбрасывается (ID-дисциплина mca-03);
      * утверждение без валидного ref-а на сообщение эпизода → переносится
        в ``unknown`` (unknown не превращается в факт);
      * неизвестный исход → ``outcome_known=False`` и outcome =
        «исход неизвестен» (финал не выдумывается);
      * капы полей (R17-safe) — превышения усекаются.
    Payload невалиден структурно → ``{"valid": False}`` с честным unknown.
    """
    if not isinstance(payload, dict):
        return {"valid": False, "title": "", "summary": "",
                "participants": [], "claims": [], "outcome_known": False,
                "outcome": EPISODE_UNKNOWN_OUTCOME, "open_questions": [],
                "unknown": ["структура ответа модели невалидна"],
                "dropped_claims": 0}
    known_members = {str(k) for k in (member_keys or ())}
    known_ids = {str(p) for p in (participant_ids or ())}

    title = _clean_str(payload.get("title"), _TITLE_MAX)
    summary = _clean_str(payload.get("summary"), _SUMMARY_MAX)
    participants = [pid for pid in _clean_str_list(
        payload.get("participants"), 64) if pid in known_ids]

    claims: list[dict] = []
    unknown = _clean_str_list(payload.get("unknown"), _CLAIM_TEXT_MAX)
    dropped_claims = 0
    for claim in (payload.get("claims") or [])[:_CLAIMS_MAX * 2]:
        if not isinstance(claim, dict):
            continue
        text = _clean_str(claim.get("text"), _CLAIM_TEXT_MAX)
        refs = [str(ref) for ref in (claim.get("refs") or ())
                if str(ref) in known_members]
        if not text:
            continue
        if not refs:
            # §8.1: утверждение без источника — НЕ факт; честный unknown.
            dropped_claims += 1
            if len(unknown) < _UNKNOWN_MAX:
                unknown.append(text)
            continue
        if len(claims) < _CLAIMS_MAX:
            claims.append({"text": text, "refs": refs})

    outcome_known = bool(payload.get("outcome_known"))
    outcome = _clean_str(payload.get("outcome"), _CLAIM_TEXT_MAX)
    if not outcome_known:
        outcome = EPISODE_UNKNOWN_OUTCOME
    elif not outcome:
        outcome_known = False
        outcome = EPISODE_UNKNOWN_OUTCOME

    return {
        "valid": True,
        "title": title,
        "summary": summary,
        "participants": participants,
        "claims": claims,
        "outcome_known": outcome_known,
        "outcome": outcome,
        "open_questions": _clean_str_list(
            payload.get("open_questions"), _CLAIM_TEXT_MAX)[:_QUESTIONS_MAX],
        "unknown": unknown[:_UNKNOWN_MAX],
        # A12 (D4): маркер «в подборке независимые разговоры» — проксируется
        # для детерминированного сплита по кластерам участников.
        "multi_topic": bool(payload.get("multi_topic")),
        "dropped_claims": dropped_claims,
    }


def build_confirm_system() -> str:
    """Системный канон подтверждения продолжения (``continuation_confirm``)."""
    return (
        "Ты — верификатор связи событий. Тебе дают описание события A "
        "(эпизод-кандидат) и события B. Определи, является ли B "
        "ПРОДОЛЖЕНИЕМ ТОГО ЖЕ реального события/истории, что и A — "
        "по участникам, сущности события и времени, а НЕ по общей теме.\n"
        "Ответь СТРОГО одним JSON-объектом:\n"
        '{"related": true|false, "confidence": 0.0..1.0, '
        '"rationale": "краткое обоснование (<=400)", '
        '"shared": ["общая сущность/факт", ...]}\n'
        "Правила:\n"
        "1. Общая тема или общее слово — НЕ доказательство связи. "
        "Две разные истории о работе — related=false.\n"
        "2. Связь подтверждается только совпадением участников + сущности "
        "события + согласованностью времени.\n"
        "3. Не уверен → related=false (ложная склейка хуже пропуска)."
    )


def build_confirm_user(event_a: str, event_b: str, *,
                       time_a: str = "", time_b: str = "",
                       participants_a: str = "",
                       participants_b: str = "") -> str:
    """User-промпт подтверждения связи двух эпизодов-кандидатов."""
    return (
        f"Событие A:\n{event_a}\n"
        f"Время A: {time_a or 'неизвестно'}; участники A: "
        f"{participants_a or 'неизвестны'}\n\n"
        f"Событие B:\n{event_b}\n"
        f"Время B: {time_b or 'неизвестно'}; участники B: "
        f"{participants_b or 'неизвестны'}\n\n"
        "Является ли B продолжением того же события, что и A? "
        "Ответь строгим JSON по контракту."
    )


def parse_confirm_answer(raw: str | None) -> dict | None:
    """Структурный разбор ответа подтверждения (или None)."""
    if raw is None:
        return None
    match = _JSON_OBJECT_RE.search(str(raw))
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(
            data.get("related"), bool):
        return None
    return data


def validate_confirm_payload(payload: dict | None) -> dict:
    """Офлайн-валидатор подтверждения. Fail-closed: без явного
    ``related=true`` связь НЕ подтверждается (ложная склейка хуже — A12)."""
    if not isinstance(payload, dict):
        return {"related": False, "confidence": 0.0, "rationale": "",
                "shared": [], "fail_closed": True}
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    related = bool(payload.get("related")) and confidence > 0.0
    return {
        "related": related,
        "confidence": confidence,
        "rationale": _clean_str(payload.get("rationale"), _RATIONALE_MAX),
        "shared": _clean_str_list(payload.get("shared"),
                                  _CLAIM_TEXT_MAX)[:10],
        "fail_closed": False,
    }


# ── детерминированные кандидаты продолжений (Q7/D7: по событию) ─────────────

_ENTITY_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+")


def entity_tokens(text: str) -> set[str]:
    """Токены сущности (>=3 символа) — для детерминированного поиска
    кандидатов по событию (участники + сущность + время)."""
    return {token for token in _ENTITY_TOKEN_RE.findall(
        str(text or "").casefold()) if len(token) >= _ENTITY_TOKEN_MIN}


def is_continuation_candidate(*, participants_a: set[str],
                              participants_b: set[str], tokens_a: set[str],
                              tokens_b: set[str], time_a, time_b,
                              min_gap_seconds: int = 3600,
                              max_gap_seconds: int = 90 * 86400,
                              now: int | None = None) -> bool:
    """Детерминированный фильтр кандидата продолжения (D7): пересечение
    участников + пересечение сущности + расстояние во времени в окне
    ``[min_gap, max_gap]``. Тема/сходство — кандидат, НЕ доказательство:
    финальное решение — только LLM-подтверждение."""
    if not (participants_a & participants_b):
        return False
    if not (tokens_a & tokens_b):
        return False
    try:
        start_a = int(time_a) if time_a is not None else None
        start_b = int(time_b) if time_b is not None else None
    except (TypeError, ValueError):
        return False
    if start_a is None or start_b is None:
        return False
    gap = abs(start_b - start_a)
    if gap < min_gap_seconds or gap > max_gap_seconds:
        return False
    if now is not None and max(start_a, start_b) > int(now) + 86400:
        return False
    return True


def _clean_str(value, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit] if text else ""


def _clean_str_list(items, limit: int) -> list[str]:
    out: list[str] = []
    for item in items or ():
        text = str(item or "").strip()
        if text:
            out.append(text[:limit])
    return out
