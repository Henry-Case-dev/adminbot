"""MCA-22 (round 10.27, ADR-1028-6 D8) — Response freshness closure.

C7 (§16–§20 ТЗ):
* **Update dedup**: identity `(chat_id, tg_message_id, revision)` — маркер
  в существующей `smart_cache` (slug `direct_update`, TTL ≈ 24 h), БЕЗ DDL.
  Инвариант: same Telegram update → idempotent (0 LLM, 0 reply, 0 memory);
  different update, same text → fresh processing (truth-set M/N/O).
* **No-replay**: conversational финальный ответ не кешируется между разными
  messages; разрешён только intermediate-кеш. Legacy text-dedup остаётся
  OFF-политикой `MCA_CONTEXT_ANSWER_CACHE_ENABLED` (уже так).
* **Exact duplicate guard** (§18): new tg_message_id AND
  normalized(final) == normalized(recent bot answer) → максимум ОДНА
  regeneration с фиксированным коротким hint; второй совпавший ответ
  отправляется + metric. Exemptions: точная цитата, deterministic command
  result, обязательный status/error phrase, structured output, code/hash/
  ID, tool-result-данные, system/safety text. Paraphrase-postprocessor
  ЗАПРЕЩЁН (не создан — invariant тестом).
* **Lineage** (§20): safe snapshot (refs/context_version/model/provider/
  attempt/retry flag/source refs) — БЕЗ hidden CoT и raw private content.

Kill-switch `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED`; существующие рубильники
(`MCA_CONTEXT_ANSWER_CACHE_ENABLED`, `CHAT_DEDUP_ENABLED`) уважаются и не
дублируются.
"""
from __future__ import annotations

import dataclasses
import hashlib
import logging
import re
import time

from services import mca_gates

logger = logging.getLogger(__name__)

# Slug update-dedup маркера (smart_cache.build_key; без DDL).
UPDATE_DEDUP_SLUG = "direct_update"
UPDATE_DEDUP_TTL_SECONDS = 24 * 3600

# Фиксированный короткий hint regeneration (§18; exact wording НЕ
# фиксируется в ответах — это подсказка МОДЕЛИ, не ответ пользователю).
DUPLICATE_GUARD_HINT = ("Не повторяй предыдущую реплику дословно; "
                        "сохрани факты и ответь естественно в текущем "
                        "контексте.")
DUPLICATE_GUARD_MAX_ATTEMPTS = 1

# Exemptions duplicate guard (§18): детерминированные/служебные тексты.
EXEMPTION_STRUCTURED_PREFIXES = ("/", "!", "{", "[", "```")
EXEMPTION_MAX_LENGTH = 600            # длинные structured-ответы не бьём
_MIN_CONVERSATIONAL_TOKENS = 3


def freshness_guard_enabled() -> bool:
    try:
        return mca_gates.response_freshness_guard_enabled()
    except Exception:                                     # pragma: no cover
        return True


def normalized_answer(text: str | None) -> str:
    """Нормализация для сравнения ответов (§18: normalized equality)."""
    value = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    value = re.sub(r"[\"«»“”'’]", "", value)
    return value


def update_dedup_key(chat_id: int, tg_message_id: int | None,
                     revision: int = 1,
                     user_id: int | None = None) -> str | None:
    """Строгий identity-ключ update-dedup (не по тексту!).

    `None` — update без tg_message_id (нечего дедупить по identity).
    `user_id` включается в материал ключа: в реальном Telegram message_id
    уникален в чате (включение user_id не меняет семантику «тот же
    update» — повторная доставка несёт того же автора), а тестовые/симуляционные
    сценарии с переиспользованием message_id разными участниками не
    склеиваются ложной идемпотентностью."""
    if tg_message_id is None:
        return None
    material = (f"{int(chat_id)}\x00{int(tg_message_id)}"
                f"\x00{max(1, int(revision or 1))}"
                f"\x00{int(user_id) if user_id is not None else '-'}")
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


async def check_update_seen(cache, chat_id: int, tg_message_id: int | None,
                            revision: int = 1,
                            user_id: int | None = None) -> bool:
    """Виден ли уже этот Telegram update (24 h TTL-маркер в smart_cache).

    Same update → True (idempotent: 0 LLM/0 reply/0 memory);
    different update, same text → False (fresh processing).

    Fix round-1 (M-1): чтение идёт через СОБСТВЕННЫЙ маркер-метод
    `get_update_marker` с явным TTL `UPDATE_DEDUP_TTL_SECONDS` (24 h) —
    НЕ через `get_dedup` (TTL 300 с `CHAT_DEDUP_TTL_SECONDS`) и БЕЗ
    зависимости от UI-флага `CHAT_DEDUP_ENABLED` (legacy text-дедуп).
    Хранилище недоступно/старый fake без маркер-метода → fail-open False."""
    if not freshness_guard_enabled():
        return False
    if cache is None or tg_message_id is None:
        return False
    key = update_dedup_key(chat_id, tg_message_id, revision, user_id)
    if key is None:
        return False
    try:
        # identity-ключ уже хеширован (chat\x00tg\x00revision\x00user) —
        # build_key (нормализация текста) не применим: словарь slug'ов
        # закрыт, а identity-дедуп по тексту ЗАПРЕЩЁН (§16/§19).
        marker = getattr(cache, "get_update_marker", None)
        if marker is None:
            return False
        seen = await marker(f"{UPDATE_DEDUP_SLUG}\x00{key}",
                            ttl_seconds=UPDATE_DEDUP_TTL_SECONDS)
        return seen is not None
    except Exception:                                     # pragma: no cover
        return False


async def mark_update_seen(cache, chat_id: int, tg_message_id: int | None,
                           revision: int = 1,
                           user_id: int | None = None) -> None:
    """Пометить update обработанным (24 h TTL-маркер).

    Трейд-офф (задокументирован по fix round-1 M-1/L-1): маркировка
    происходит ДО обработки (at-most-once) — повторная доставка того же
    update'а в течение 24 h идемпотентна, но если обработка упала (LLM-
    ошибка и т.п.), авто-ретрай того же update'а не выполняется до
    истечения TTL. Это сознательный выбор против двойного LLM-вызова/
    двойного ответа при webhook-retry (§16); единственный рубильник —
    `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED` (OFF → маркера нет вовсе)."""
    if not freshness_guard_enabled():
        return
    if cache is None or tg_message_id is None:
        return
    key = update_dedup_key(chat_id, tg_message_id, revision, user_id)
    if key is None:
        return
    try:
        marker = getattr(cache, "set_update_marker", None)
        if marker is None:
            return
        await marker(f"{UPDATE_DEDUP_SLUG}\x00{key}", "1",
                     ttl_seconds=UPDATE_DEDUP_TTL_SECONDS)
    except Exception:                                     # pragma: no cover
        pass


# ── Exact duplicate guard (§18) ─────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class DuplicateVerdict:
    """Решение guard'а: regenerate (bounded 1) / send-as-is."""

    duplicate: bool
    exempt: bool
    reason_code: str | None
    regeneration_allowed: bool


def duplicate_exemption_reason(text: str | None) -> str | None:
    """Exemptions §18: None = exemption нет (guard применим)."""
    value = str(text or "")
    stripped = value.strip()
    if not stripped:
        return "empty"
    if stripped.startswith(EXEMPTION_STRUCTURED_PREFIXES):
        return "structured_or_command"
    if len(stripped) > EXEMPTION_MAX_LENGTH:
        return "structured_or_command"
    if re.search(r"```", stripped):
        return "code_block"
    if re.fullmatch(r"[A-Fa-f0-9]{16,64}", stripped):
        return "hash_or_id"
    tokens = re.findall(r"[а-яёa-z0-9]+", stripped.casefold())
    if len(tokens) < _MIN_CONVERSATIONAL_TOKENS:
        return "status_or_short_phrase"
    return None


def evaluate_duplicate(final_answer: str | None, recent_answer: str | None,
                       *, new_tg_message_id: int | None,
                       regeneration_already_used: bool = False
                       ) -> DuplicateVerdict:
    """Exact duplicate guard (§18; D8).

    duplicate = new tg_message_id AND normalized(final)==normalized(recent).
    Regeneration — максимум ОДНА попытка (`regeneration_already_used`).
    Exemptions детерминированных текстов всегда отправляются как есть.
    Повторное совпадение → отправить + metric (без loop)."""
    if not freshness_guard_enabled():
        return DuplicateVerdict(duplicate=False, exempt=False,
                                reason_code=None, regeneration_allowed=False)
    if new_tg_message_id is None or not final_answer or not recent_answer:
        return DuplicateVerdict(duplicate=False, exempt=False,
                                reason_code=None, regeneration_allowed=False)
    if normalized_answer(final_answer) != normalized_answer(recent_answer):
        return DuplicateVerdict(duplicate=False, exempt=False,
                                reason_code=None, regeneration_allowed=False)
    exemption = duplicate_exemption_reason(final_answer)
    if exemption is not None:
        return DuplicateVerdict(duplicate=True, exempt=True,
                                reason_code=f"exempt:{exemption}",
                                regeneration_allowed=False)
    if regeneration_already_used:
        # bounded: второй совпавший ответ отправляется + metric (нет loop).
        return DuplicateVerdict(duplicate=True, exempt=False,
                                reason_code="duplicate_sent_after_retry",
                                regeneration_allowed=False)
    return DuplicateVerdict(duplicate=True, exempt=False,
                            reason_code="duplicate_detected",
                            regeneration_allowed=True)


# ── Lineage snapshot (§20; R17-safe) ────────────────────────────────────────

def build_lineage_snapshot(*, reply_message_id: int | None = None,
                           trigger_message_id: int | None = None,
                           parent_message_id: int | None = None,
                           context_version: str | None = None,
                           model: str | None = None,
                           provider: str | None = None,
                           generation_attempt: int = 1,
                           freshness_retry: bool = False,
                           source_refs_used: tuple = ()) -> dict:
    """Safe snapshot lineage: только ID/коды/версии — без raw content/CoT."""
    return {
        "reply_message_id": (int(reply_message_id)
                             if reply_message_id is not None else None),
        "trigger_message_id": (int(trigger_message_id)
                               if trigger_message_id is not None else None),
        "parent_message_id": (int(parent_message_id)
                              if parent_message_id is not None else None),
        "context_version": str(context_version or "") or None,
        "model": str(model or "") or None,
        "provider": str(provider or "") or None,
        "generation_attempt": max(1, int(generation_attempt or 1)),
        "freshness_retry": bool(freshness_retry),
        "source_refs_used": tuple(str(r) for r in source_refs_used or ()),
        "ts": int(time.time()),
    }


def emit_freshness_event(event_name: str, *, outcome: str = "success",
                         reason_code: str | None = None, **fields) -> None:
    """События `DIRECT_*` (§20) через `mca_events` (свободная ось
    event_name mca-13; reason_code — фичевый словарь). Fail-open."""
    try:
        from services import mca_events
        mca_events.emit_mca_event(event_name, outcome=outcome,
                                  component="response_freshness",
                                  reason_code=reason_code, **fields)
    except Exception:                                     # pragma: no cover
        pass
