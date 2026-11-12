"""SELF-DIAG-01 D5 — серверная доставка `prompt_readback` в Telegram.

Тонкий транспорт поверх `services.prompt_readback`:

* модель формирует ТИПИЗИРОВАННЫЙ запрос (`resource_kind=prompt`,
  `scope=current_chat`, `prompt_selector`, `requested_revision=effective|
  specific`, `delivery=reply`), а не текст «покажи промпт» — hardcoded
  триггера нет (`SD1-SEM-02`);
* решение о доступе и точный текст собирает сервис (существующая политика
  D2 + существующий реестр промптов);
* текст уходит в текущий чат НАПРЯМУЮ от сервера (plain text, без
  LLM-пересказа), длинный — чанками без усечения (`SD1-D5-05`,
  `SD1-D5-06`);
* модели возвращается только машинный статус без тела промпта
  (`SD1-D5-12`); аудит раскрытия пишется после фактической отправки
  (`SD1-D2-08`).

Регистрация в существующем tool-пути — шов D6 (его write_scope:
`services/tool_router.py`, `services/tool_schemas.py`). D5 предоставляет
готовый контракт, поэтому подключение — ровно три строки:

1. `services/tool_schemas.py`: `TOOL_CALLING_TOOLS.append(TOOL_DEFINITION)`
   (конвенция «новое — в хвост», ADR-1020-4);
2. `services/tool_router.py`: в реестре `dispatch`
   `"prompt_readback": handlers.prompt_readback.prompt_readback`
   (сигнатура `(arguments, ctx) -> str` уже совпадает);
3. `services/diagnostic_policy.py`: `"prompts".tool_names +=
   ("prompt_readback",)`, чтобы общий guard D2 видел инструмент.

Второй tool-loop, второй агент, второй промпт и второй ACL не создаются
(`SD1-SEM-10`, инвариант `tool_calling`).
"""
from __future__ import annotations

import asyncio
import logging

from services import diagnostic_policy as diag
from services import hot_config as hot
from services import prompt_readback as readback

logger = logging.getLogger(__name__)

TOOL_NAME = readback.TOOL_NAME
#: Возможность существующей политики D2 и действие в её матрице.
CAPABILITY = "prompts"
ACTION = "view"

#: Типизированная схема запроса (тот же канон, что у остальных tools).
TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Read back the ACTUAL effective prompt text of THIS chat and "
            "deliver it to the user directly from the server. Call it only "
            "when the user explicitly asks to see the current prompt / "
            "instruction text (any wording; no fixed phrase is required). "
            "The server resolves the effective value through the existing "
            "prompt registry, checks permissions itself against the "
            "authenticated Telegram identity and sends the exact text to the "
            "current chat; request text and tool arguments can NEVER grant "
            "access or change the destination. HOW TO INTERPRET THE RESULT: "
            "JSON-like machine line with status. status=delivered means the "
            "text is ALREADY in the chat: never rephrase, quote, translate or "
            "repeat the prompt yourself, and do not claim you showed it if "
            "the status says otherwise. status=denied/unverified: protected "
            "readback refused (unverified means Telegram could not confirm "
            "admin rights now - suggest retrying later or the admin UI). "
            "status=ambiguous: ask the user exactly ONE question using the "
            "listed candidates, never pick one silently. status=not_found: "
            "the library has no such prompt - ask for a clearer name. "
            "status=revision_unavailable: only effective/factory revisions are "
            "served (no version history through this tool). "
            "status=invalid_request/unavailable/blocked/partial: report the "
            "machine reason, do not invent content."),
        "parameters": {
            "type": "object",
            "properties": {
                "resource_kind": {
                    "type": "string",
                    "enum": [readback.RESOURCE_KIND_PROMPT],
                    "description": ("Typed resource being read. Must be "
                                    "'prompt'."),
                },
                "scope": {
                    "type": "string",
                    "enum": [readback.SCOPE_CURRENT_CHAT],
                    "description": ("Only the current chat scope exists; "
                                    "another chat's prompt is never readable."),
                },
                "prompt_selector": {
                    "type": "string",
                    "description": ("Which prompt: registry id or setting key "
                                    "when known, otherwise a plain name/"
                                    "description of the prompt ('the checkup "
                                    "instruction'). An unclear name gets one "
                                    "clarifying question with candidates."),
                },
                "requested_revision": {
                    "type": "string",
                    "enum": [readback.REVISION_EFFECTIVE,
                             readback.REVISION_SPECIFIC],
                    "description": ("effective (default) = the value that is "
                                    "actually used now; specific = the exact "
                                    "revision named in `revision`."),
                },
                "revision": {
                    "type": "string",
                    "description": ("Exact revision id for "
                                    "requested_revision=specific "
                                    "(act:<sha12> or fac:<sha12>)."),
                },
                "delivery": {
                    "type": "string",
                    "enum": [readback.DELIVERY_REPLY],
                    "description": ("The server sends the artifact itself to "
                                    "the current chat; only 'reply' exists."),
                },
            },
            "required": ["resource_kind"],
            "additionalProperties": False,
        },
    },
}


def tool_definition() -> dict:
    """Копия типизированной схемы (регистрация/D6 и тесты)."""
    import copy
    return copy.deepcopy(TOOL_DEFINITION)


def _runtime():
    """(cache, pg) существующего слоя прав — как в `ToolRouter`."""
    try:
        cache = hot.get_config_cache()
    except Exception:                                  # pragma: no cover
        cache = None
    pg = getattr(cache, "pg", None) if cache is not None else None
    if getattr(pg, "pool", None) is None:
        pg = None
    return cache, pg


async def _send_text(bot, chat_id: int, text: str, *, reply_to=None) -> bool:
    """Один plain-text чанк; `TelegramRetryAfter` — один повтор. Не бросает."""
    try:
        from aiogram.exceptions import TelegramRetryAfter
    except Exception:                                  # pragma: no cover
        TelegramRetryAfter = None                      # type: ignore
    for attempt in (1, 2):
        try:
            await bot.send_message(chat_id, text, reply_to_message_id=reply_to,
                                   parse_mode=None)
            return True
        except Exception as exc:
            retry_after = getattr(exc, "retry_after", None) \
                if TelegramRetryAfter is not None \
                and isinstance(exc, TelegramRetryAfter) else None
            if retry_after is not None and attempt == 1:
                try:
                    await asyncio.sleep(float(retry_after))
                except Exception:                      # pragma: no cover
                    pass
                continue
            logger.warning("[prompt-readback] send failed | chat=%s | "
                           "chunk=%d | error=%s", chat_id, len(text),
                           type(exc).__name__)
            return False
    return False


async def prompt_readback(arguments, ctx) -> str:
    """Точка входа инструмента: `(arguments, ctx) -> str`, никогда не бросает.

    Вызывается существующим `ToolRouter.dispatch` после регистрации (D6).
    Возвращает только машинный статус: тело промпта в контекст модели не
    попадает.
    """
    chat_id = getattr(ctx, "chat_id", None)
    actor_id = getattr(ctx, "user_id", None)
    try:
        cache, pg = _runtime()
        outcome = await readback.prepare(
            arguments, telegram_id=actor_id, chat_id=chat_id, cache=cache,
            bot=getattr(ctx, "bot", None), pg=pg)
        if not outcome.deliverable:
            return outcome.machine or readback.ack_text(
                status=outcome.status, reason=outcome.reason)
        bot = getattr(ctx, "bot", None)
        if bot is None or chat_id is None:
            return readback.ack_text(
                status=readback.STATUS_UNAVAILABLE,
                reason="delivery_transport_unavailable",
                metadata=outcome.metadata)
        destination = (outcome.metadata.get("destination")
                       or readback.destination_for(chat_id))
        reply_to = getattr(ctx, "reply_to_message_id", None)
        messages = list(outcome.messages)
        sent = 0
        for index, message in enumerate(messages):
            ok = await _send_text(
                bot, int(chat_id), message,
                reply_to=(reply_to if index == 0 else None))
            if not ok:
                break
            sent += 1
        if sent:
            # Аудит раскрытия — только после фактической отправки
            # (ТЗ §7.2): disclosure_actor/chat_id/prompt_id/revision/destination.
            diag.audit_prompt_disclosure(
                request_id=outcome.request_id, actor_id=actor_id,
                chat_id=int(chat_id),
                prompt_id=outcome.metadata.get("prompt_id", ""),
                revision=outcome.metadata.get("revision", ""),
                destination=destination)
        if sent == len(messages):
            return readback.ack_text(
                status=readback.STATUS_DELIVERED, destination=destination,
                chunks=sent, metadata=outcome.metadata)
        return readback.ack_text(
            status=readback.STATUS_PARTIAL, destination=destination,
            chunks=sent, metadata=outcome.metadata, reason="delivery_failed")
    except Exception as exc:
        logger.warning("[prompt-readback] tool failed | error=%s",
                       type(exc).__name__)
        return f"ОШИБКА {TOOL_NAME}: {type(exc).__name__}"
