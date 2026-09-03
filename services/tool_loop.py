"""Эпик 04.09.2026 (3.3, Часть 2) — цикл обработки tool_calls (Tool Calling).

Формат ролей OpenAI: assistant с tool_calls → роль "tool" по каждому
tool_call_id → повторный вызов generate_chat. Жёсткий лимит раундов
TOOL_MAX_ROUNDS (≤4 вызова LLM суммарно) — защита от бесконечного цикла
(FR-13/AC-2.3). При невозможности tool-режима провайдера (детерминированный
не-2xx на 1-м вызове) — один повтор БЕЗ tools и обычный ответ (FR-15).

Все логи — с префиксом [tools]; WARNING на деградацию/лимит; INFO на раунд.
"""
import copy
import json
import logging

from services.llm_client import (
    LLMBadResponseError,
    LLMError,
    LLMToolCall,
)

logger = logging.getLogger(__name__)

TOOL_MAX_ROUNDS = 4      # 1 стартовый вызов + до 3 раундов инструментов
_TOOL_CALLS_PER_ROUND_MAX = 2   # защита от спама вызовов одним ходом (3.3)


async def chat_with_tools(llm, messages: list[dict], *,
                          tools: list[dict], router, ctx,
                          temperature: float | None = None) -> str:
    """→ финальный текст. При невозможности tool-режима — обычный ответ без tools.

    Исключения наружу: LLMError (провайдер/раунд > 0), LLMBadResponseError
    (пустой финал / лимит раундов без текста) — обрабатываются существующими
    except-ветками direct_chat (пустой ответ → молчание + 🗿, FR-14).
    """
    payload_messages = copy.deepcopy(messages)
    for round_index in range(TOOL_MAX_ROUNDS):
        try:
            result = await llm.generate_chat(payload_messages,
                                             temperature=temperature,
                                             tools=tools, tool_choice="auto")
        except LLMError as exc:                 # провайдер не умеет tools
            if round_index == 0:
                logger.warning(
                    "[tools] provider rejected tools — plain answer | error=%s",
                    exc)
                # degrade: 1 обычный вызов БЕЗ tools (FR-15, AC-2.5)
                return await llm.generate(messages, temperature=temperature)
            raise
        if not result.tool_calls:
            text = (result.content or "").strip()
            if text:
                logger.info(
                    "[tools] final round | round=%d | out_chars=%d",
                    round_index + 1, len(text))
                return text
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
            try:
                arguments = json.loads(tc.arguments) if (tc.arguments or "").strip() else {}
                if not isinstance(arguments, dict):
                    raise ValueError("arguments not object")
                output = await router.dispatch(tc.name, arguments, ctx)
            except Exception as exc:              # инструмент упал — модель видит текст
                logger.warning("[tools] exec failed | tool=%s | error=%s",
                               tc.name, f"{type(exc).__name__}: {exc}")
                output = f"ОШИБКА {tc.name}: {type(exc).__name__}"
            payload_messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": output})
            logger.info("[tools] round=%d | tool=%s | out_chars=%d",
                        round_index + 1, tc.name, len(output))
    # лимит раундов исчерпан
    logger.warning("[tools] round limit reached | rounds=%d", TOOL_MAX_ROUNDS)
    raise LLMBadResponseError("tool loop: no final answer within round limit")
