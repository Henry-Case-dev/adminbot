"""F3/F4/F5 (10.22) — общий контракт двухвызовного пайплайна System 2.

Цепочка handoff: Слой-1 обязан вернуть **строгий JSON** (Аналитик/Синтезатор)
или чистую выжимку; между стадиями — schema-validation. Слой-2 физически не
видит сырьё/теги/тулы (получает только валидированный объект). Невалидный или
усечённый JSON → ``None`` → вызывающий уходит на одиночный путь 10.21.

Здесь же — детерминированные проверки «нет ли в тексте системных тегов/ID»
(для перехвата утечек) и R17-маскирование секретов перед подачей в промпт.
Никаких LLM-вызовов: только разбор/валидация.
"""
from __future__ import annotations

import json
import logging
import re

from services.reply_postprocess import strip_reasoning_tags

logger = logging.getLogger(__name__)

_FACT_ID_RE = re.compile(r"\bfact\s*:\s*\d+\b", re.IGNORECASE)
_MSG_ID_RE = re.compile(r"\bmsg\s*:\s*\d+\b", re.IGNORECASE)
# Метка-кандидат канона 4D-памяти: ``[ММ.ГГГГ | Автор …]``.
_PHANTOM_BRACKET_RE = re.compile(r"\[\s*\d{2}\.\d{4}\s*\|")
_FENCE_OPEN_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*")
_FENCE_CLOSE_RE = re.compile(r"\s*```$")

# R17: типовые секреты/токены (не логируются, вырезаются из входа Синтезатора).
_SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_\-]{10,}|Bearer\s+\S+|[A-Za-z0-9_\-]{32,})"
)

_FACT_STATUSES = frozenset({"true", "false", "misleading", "unverifiable"})
_CONFIDENCE = frozenset({"high", "medium", "low"})
_SOURCES = frozenset({"exa", "rag", "lore", "api", "unknown"})

# Раунд 10.23 (F3, ADR-1023-3): режим общения определяется Синтезатором
# (Stage-1) и передаётся Вербализатору служебным полем `response_mode`.
# Роутер НЕ добавляет третий LLM-вызов — поле едет в том же JSON Stage-1.
RESPONSE_MODES = ("casual", "serious", "deep_research")
_DEFAULT_RESPONSE_MODE = "serious"


def normalize_response_mode(value) -> str:
    """Fail-safe нормализация ``response_mode``: любое неизвестное/пустое/
    ``None`` → ``"serious"``. Никогда не бросает (R3)."""
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in RESPONSE_MODES:
            return candidate
    return _DEFAULT_RESPONSE_MODE


# Раунд 10.23 (F6, ADR-1023-6 §Decision 1): визуальный промпт обложки — короткий
# (EN, ≤300) и едет служебным полем того же Stage-1 JSON. Обрезка — по границе
# слова, никогда не бросает (R3/back-compat).
COVER_PROMPT_MAX = 300
_WS_RUN_RE = re.compile(r"\s+")


def normalize_cover_prompt(value) -> str:
    """Нормализовать ``cover_prompt`` из Stage-1 JSON.

    Не строка / пусто / ``None`` → ``""``; схлопывание всех пробельных
    пробегов (включая ``\\n``) в один пробел; обрезка до 300 символов по
    границе слова. Никогда не бросает (fail-open → ``""``)."""
    try:
        if not isinstance(value, str):
            return ""
        collapsed = _WS_RUN_RE.sub(" ", value).strip()
        if not collapsed:
            return ""
        if len(collapsed) <= COVER_PROMPT_MAX:
            return collapsed
        truncated = collapsed[:COVER_PROMPT_MAX]
        cut = truncated.rfind(" ")
        if cut > 0:
            truncated = truncated[:cut]
        return truncated.rstrip()
    except Exception:  # pragma: no cover - defensive
        return ""


def parse_json_object(raw: str) -> dict | None:
    """Строгий разбор JSON-объекта. Никогда не бросает; ошибка → ``None``.

    Срезает reasoning-теги и markdown-фенсы; берёт первый ``{…}`` через
    ``raw_decode`` (устойчиво к хвостовому тексту и усечению).
    """
    try:
        source = strip_reasoning_tags(str(raw or "")).strip()
        if not source:
            return None
        source = _FENCE_OPEN_RE.sub("", source)
        source = _FENCE_CLOSE_RE.sub("", source)
        start = source.find("{")
        if start < 0:
            return None
        data, _end = json.JSONDecoder().raw_decode(source[start:])
        return data if isinstance(data, dict) else None
    except Exception:  # pragma: no cover - defensive
        return None


def contains_system_ids(text: str) -> bool:
    """Есть ли в тексте технические маркеры (``fact:ID``/``msg:ID``/метка-дата)."""
    value = str(text or "")
    return bool(
        _FACT_ID_RE.search(value)
        or _MSG_ID_RE.search(value)
        or _PHANTOM_BRACKET_RE.search(value)
    )


def redact_secrets(text: str) -> str:
    """R17: замаскировать токен-подобные фрагменты перед подачей в LLM."""
    return _SECRET_RE.sub("[redacted]", str(text or ""))


def parse_factcheck_analysis(raw: str) -> dict | None:
    """Валидировать JSON Аналитика фактчека. Невалидно → ``None``."""
    data = parse_json_object(raw)
    if not data:
        return None
    claim = data.get("claim")
    verdict = data.get("verdict")
    findings = data.get("findings")
    if not isinstance(claim, str) or not claim.strip():
        return None
    if not isinstance(verdict, str) or not verdict.strip():
        return None
    if not isinstance(findings, list) or not findings:
        return None
    clean: list[dict] = []
    for item in findings:
        if not isinstance(item, dict):
            return None
        assertion = item.get("assertion")
        status = str(item.get("status") or "").strip().lower()
        evidence = item.get("evidence")
        human_time = item.get("human_time")
        author = item.get("author")
        if not isinstance(assertion, str) or not assertion.strip():
            return None
        if status not in _FACT_STATUSES:
            return None
        if not isinstance(evidence, str) or not evidence.strip():
            return None
        if not isinstance(human_time, str) or not human_time.strip():
            human_time = "без даты"
        # Правило изоляции: системные теги/ID запрещены вне human_time.
        for value in (claim, assertion, evidence, verdict):
            if contains_system_ids(value):
                return None
        clean.append({
            "assertion": assertion.strip(),
            "status": status,
            "human_time": human_time.strip(),
            "author": author.strip() if isinstance(author, str) and author.strip() else None,
            "evidence": evidence.strip(),
        })
    tone_hint = data.get("tone_hint")
    result = {
        "claim": claim.strip(),
        "findings": clean,
        "verdict": verdict.strip(),
    }
    if isinstance(tone_hint, str) and tone_hint.strip():
        result["tone_hint"] = tone_hint.strip()
    # Поле добавляется последним (порядок F7 — корреляция — пойдёт ПОСЛЕ F3).
    result["response_mode"] = normalize_response_mode(data.get("response_mode"))
    return result


def _validate_digest_text(text) -> str | None:
    """Детерминированная проверка Markdown-выжимки (общие правила Stage-1)."""
    value = strip_reasoning_tags(str(text or "")).strip()
    if not value:
        return None
    if contains_system_ids(value):
        return None
    if "Архивная справка" in value:
        return None
    return value


def parse_summary_handoff(raw: str) -> dict | None:
    """Строгий JSON Редактора: ``{"response_mode": …, "digest": …}``.

    ``digest`` валидируется существующими правилами (reasoning-теги,
    ``contains_system_ids``, запрет «Архивная справка»). Обратная совместимость
    (ADR-1023-3 §3): если raw — не JSON, но валидная Markdown-выжимка, то
    возвращаем ``digest=raw``, ``response_mode="serious"``. Невалидно → ``None``.
    """
    source = str(raw or "")
    data = parse_json_object(source)
    if isinstance(data, dict) and "digest" in data:
        digest = _validate_digest_text(data.get("digest"))
        if digest is None:
            return None
        return {
            "response_mode": normalize_response_mode(data.get("response_mode")),
            "digest": digest,
            # F6 (additive): служебное поле визуального промпта обложки.
            "cover_prompt": normalize_cover_prompt(data.get("cover_prompt")),
        }
    digest = _validate_digest_text(source)
    if digest is None:
        return None
    # Legacy-выжимка (не JSON) режима/обложки не несёт.
    return {"response_mode": _DEFAULT_RESPONSE_MODE, "digest": digest,
            "cover_prompt": ""}


def validate_summary_digest(raw: str) -> str | None:
    """Backward-compatible обёртка (10.22): вернуть только ``digest``.

    Старый контракт «чистая Markdown-выжимка» жив: не-JSON raw проходит как
    выжимка с режимом ``serious``. Невалидно → ``None``."""
    parsed = parse_summary_handoff(raw)
    return parsed["digest"] if parsed else None


def parse_direct_synthesis(raw: str) -> dict | None:
    """Валидировать JSON-справку Синтезатора тулов. Невалидно → ``None``."""
    data = parse_json_object(raw)
    if not data:
        return None
    question = data.get("user_question")
    outline = data.get("answer_outline")
    facts = data.get("facts")
    if not isinstance(question, str) or not question.strip():
        return None
    if not isinstance(outline, str) or not outline.strip():
        return None
    if not isinstance(facts, list):
        return None
    # Изоляция/R17: системные теги/ID запрещены и в справке целиком; секреты
    # маскируем на всех строковых полях (иначе утекли бы в Вербализатор).
    if contains_system_ids(question) or contains_system_ids(outline):
        return None
    clean: list[dict] = []
    for item in facts:
        if not isinstance(item, dict):
            return None
        topic = str(item.get("topic") or "").strip()
        finding = str(item.get("finding") or "").strip()
        source = str(item.get("source") or "unknown").strip().lower()
        confidence = str(item.get("confidence") or "low").strip().lower()
        if not finding:
            continue
        if contains_system_ids(finding) or contains_system_ids(topic):
            return None
        finding = redact_secrets(finding)
        topic = redact_secrets(topic)
        if source not in _SOURCES:
            source = "unknown"
        if confidence not in _CONFIDENCE:
            confidence = "low"
        clean.append({"topic": topic, "finding": finding,
                      "source": source, "confidence": confidence})
    limitations = data.get("limitations")
    clean_limitations = [
        redact_secrets(str(x)) for x in limitations
        if isinstance(x, str) and str(x).strip()
    ] if isinstance(limitations, list) else []
    return {
        "user_question": redact_secrets(question.strip()),
        "facts": clean,
        "answer_outline": redact_secrets(outline.strip()),
        "limitations": clean_limitations,
        "response_mode": normalize_response_mode(data.get("response_mode")),
    }
