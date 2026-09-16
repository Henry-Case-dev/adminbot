"""Эпик 04.09.2026 (3.3, Часть 2) — цикл обработки tool_calls (Tool Calling).

Формат ролей OpenAI: assistant с tool_calls → роль "tool" по каждому
tool_call_id → повторный вызов generate_chat. Жёсткий лимит раундов
TOOL_MAX_ROUNDS (≤4 вызова LLM суммарно) — защита от бесконечного цикла
(FR-13/AC-2.3). При невозможности tool-режима провайдера (детерминированный
не-2xx на 1-м вызове) — один повтор БЕЗ tools и обычный ответ (FR-15).

Все логи — с префиксом [tools]; WARNING на деградацию/лимит; INFO на раунд.

Раунд 10.20 (БЛОК 1, ADR-1020-6 п.2, T-1887): цикл НЕ меняется — сигнал
режима доставки «Летописца» несёт сам `ctx` (поле ``ToolContext.lore_compiled``,
ставится инструментом compile_lore_story и читается DirectChat после возврата).
`chat_with_tools` лишь проносит ctx в `router.dispatch(..., ctx)`.

Раунд 10.20 (БЛОК 7.1, ADR-1020-7 §1, T-1919): graceful degradation —
исчерпание раундов и `LLMError` на `round_index > 0` больше НЕ роняют ответ
в тишину+🗿. Возвращается частичный текст, накопленный в раундах, либо
саркастичная заглушка `TOOL_LOOP_FALLBACK_PHRASE`. Провайдер-reject на
`round_index == 0` (plain-фолбэк, FR-15) и `NoApiKeyForChat` — без изменений;
пустой финал (нет tool_calls и нет текста) — прежний `LLMBadResponseError`
(FR-14/65.1, сохраняем контракт 🗿).
"""
import copy
import json
import logging

from services.llm_client import (
    LLMBadResponseError,
    LLMError,
    LLMToolCall,
    NoApiKeyForChat,
)
from services.reply_postprocess import strip_reasoning_tags

logger = logging.getLogger(__name__)

TOOL_MAX_ROUNDS = 4      # 1 стартовый вызов + до 3 раундов инструментов
_TOOL_CALLS_PER_ROUND_MAX = 2   # защита от спама вызовов одним ходом (3.3)

# Саркастичная заглушка деградации (код-константа; каталог-Δ = 0). Показывается
# только когда все раунды/поздние ошибки «съели» ответ, а частичного текста нет.
TOOL_LOOP_FALLBACK_PHRASE = (
    "Чет долго думал, аж перегрелся — и всё равно ни к чему не пришёл. "
    "Спроси проще, что ли.")


class ToolLoopResult(str):
    """Финальный текст tool-цикла + телеметрия (ADR-1020-7 §1).

    ЯВЛЯЕТСЯ ``str`` → downstream `str(raw).strip()`,
    `send_chunked_reply`/`remember_bot_reply` работают БЕЗ правок.

    * ``rounds_used`` — сколько LLM-раундов реально израсходовано;
    * ``degraded`` — ответ получен деградацией (не штатный финал);
    * ``reason`` — ``"ok" | "round_limit" | "llm_error"``;
    * ``tool_trace`` — ``[{"round", "tool", "ok", "out_chars"}, …]``.

    Атрибуты не сериализуются и не влияют на строковое равенство.
    """

    def __new__(cls, text, *, rounds_used=1, degraded=False, reason="ok",
                tool_trace=None):
        obj = super().__new__(cls, str(text or ""))
        obj.rounds_used = int(rounds_used)
        obj.degraded = bool(degraded)
        obj.reason = str(reason or "ok")
        obj.tool_trace = list(tool_trace) if tool_trace else []
        return obj


def _log_degraded(reason: str, rounds_used: int, tool_trace: list,
                  text: str) -> None:
    """R17: только причина/числа/длины/имена тулов — без текстов и аргументов."""
    lost_rounds = max(0, TOOL_MAX_ROUNDS - int(rounds_used))
    tools = ",".join(
        sorted({str(entry.get("tool") or "") for entry in tool_trace
                if entry.get("tool")})) or "-"
    logger.warning(
        "[tools] degraded | reason=%s | rounds_used=%d | lost_rounds=%d | "
        "tools=%s | partial_chars=%d",
        reason, int(rounds_used), lost_rounds, tools, len(text or ""))


async def chat_with_tools(llm, messages: list[dict], *,
                          tools: list[dict], router, ctx,
                          temperature: float | None = None,
                          chat_id: int | None = None) -> "ToolLoopResult":
    """→ ``ToolLoopResult`` (str) — финальный текст + телеметрия.

    При исчерпании ``TOOL_MAX_ROUNDS`` или ``LLMError`` на ``round_index > 0``
    возвращается частичный ответ либо ``TOOL_LOOP_FALLBACK_PHRASE``
    (``degraded=True``) — НЕ тишина и НЕ исключение (ADR-1020-7 §1).
    Провайдер-reject на 1-м раунде — plain-фолбэк без tools (FR-15);
    ``NoApiKeyForChat`` — проброс; пустой финал — прежний
    ``LLMBadResponseError`` (FR-14/65.1).
    """
    payload_messages = copy.deepcopy(messages)
    tool_trace: list[dict] = []
    partial_text = ""
    for round_index in range(TOOL_MAX_ROUNDS):
        try:
            result = await llm.generate_chat(payload_messages,
                                             temperature=temperature,
                                             tools=tools, tool_choice="auto",
                                             chat_id=chat_id)
        except NoApiKeyForChat:
            raise
        except LLMError as exc:                 # провайдер не умеет tools
            if round_index == 0:
                logger.warning(
                    "[tools] provider rejected tools — plain answer | error=%s",
                    exc)
                # degrade: 1 обычный вызов БЕЗ tools (FR-15, AC-2.5)
                plain = await llm.generate(messages, temperature=temperature,
                                           chat_id=chat_id)
                return ToolLoopResult(plain, rounds_used=1)
            # БЛОК 7.1: поздний раунд — не пробрасываем (не теряем ответ).
            text = strip_reasoning_tags(partial_text) or TOOL_LOOP_FALLBACK_PHRASE
            _log_degraded("llm_error", round_index, tool_trace, text)
            return ToolLoopResult(text, rounds_used=round_index,
                                  degraded=True, reason="llm_error",
                                  tool_trace=tool_trace)
        if result.content and str(result.content).strip():
            partial_text = str(result.content).strip()
        if not result.tool_calls:
            text = (result.content or "").strip()
            if text:
                logger.info(
                    "[tools] final round | round=%d | out_chars=%d",
                    round_index + 1, len(text))
                # БЛОК 7.2b (T-1921): страховка tool-пути (idempotent).
                return ToolLoopResult(strip_reasoning_tags(text),
                                      rounds_used=round_index + 1,
                                      tool_trace=tool_trace)
            raise LLMBadResponseError("tool loop: empty final answer")
        tool_calls: list[LLMToolCall] = result.tool_calls
        if len(tool_calls) > _TOOL_CALLS_PER_ROUND_MAX:   # защита от спама
            logger.warning("[tools] tool_calls truncated | %d -> %d | round=%d",
                           len(tool_calls), _TOOL_CALLS_PER_ROUND_MAX,
                           round_index + 1)
            tool_calls = tool_calls[:_TOOL_CALLS_PER_ROUND_MAX]
        assistant_message = {"role": "assistant",
                             "content": result.content or None,
                             "tool_calls": [tc.as_openai_dict()
                                            for tc in tool_calls]}
        payload_messages.append(assistant_message)
        for tc in tool_calls:
            ok = True
            try:
                arguments = json.loads(tc.arguments) if (tc.arguments or "").strip() else {}
                if not isinstance(arguments, dict):
                    raise ValueError("arguments not object")
                output = await router.dispatch(tc.name, arguments, ctx)
            except Exception as exc:              # инструмент упал — модель видит текст
                ok = False
                logger.warning("[tools] exec failed | tool=%s | error=%s",
                               tc.name, f"{type(exc).__name__}: {exc}")
                output = f"ОШИБКА {tc.name}: {type(exc).__name__}"
            payload_messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": output})
            tool_trace.append({"round": round_index + 1, "tool": tc.name,
                               "ok": ok, "out_chars": len(output or "")})
            logger.info("[tools] round=%d | tool=%s | out_chars=%d",
                        round_index + 1, tc.name, len(output))
    # лимит раундов исчерпан — graceful degradation (НЕ исключение).
    text = strip_reasoning_tags(partial_text) or TOOL_LOOP_FALLBACK_PHRASE
    _log_degraded("round_limit", TOOL_MAX_ROUNDS, tool_trace, text)
    return ToolLoopResult(text, rounds_used=TOOL_MAX_ROUNDS, degraded=True,
                          reason="round_limit", tool_trace=tool_trace)
