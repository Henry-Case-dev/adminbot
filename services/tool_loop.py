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
import hashlib
import json
import logging
import re
import time

from config.settings import settings
from services.llm_client import (
    LLMBadResponseError,
    LLMError,
    LLMToolCall,
    NoApiKeyForChat,
)
from services.reply_postprocess import strip_reasoning_tags
from services.agentic_events import emit_agentic_event

logger = logging.getLogger(__name__)

TOOL_MAX_ROUNDS = 4      # 1 стартовый вызов + до 3 раундов инструментов
_TOOL_CALLS_PER_ROUND_MAX = 2   # защита от спама вызовов одним ходом (3.3)

# A2 (раунд 10.26, ADR-1026-15 D3/D5): §17-лимиты цепочки — аддитивные
# код-константы ПОВЕРХ существующих 4 раундов / ≤2 за раунд / per-tool
# тайм-аутов. Все гейтятся env-only `TOOL_CHAIN_LIMITS_ENABLED` (Δ каталога=0).
TOOL_MAX_TOTAL_CALLS = 6                 # суммарный cap вызовов (§17)
TOOL_CHAIN_TIMEOUT_SECONDS = 360.0       # мягкий wall-clock (max per-tool 300 + 60)
_TOOL_MAX_SAME_CALL = 2                  # одинаковый вызов (имя+арг.) ≤2 раз
TOOL_CHAIN_MAX_METERED_CALLS = 4         # лимит «платных»/внешних вызовов

# Метка «платного»/внешнего вызова (ADR-1026-15 D3). `worker_budget.image_calls`
# внутри `generate_image` НЕ дублируется. Free/local: memory/dig/history/health.
METERED_TOOLS = frozenset({
    "execute_web_search", "fetch_article", "summarize_video", "download_media",
    "compile_lore_story", "generate_image", "transcribe_video",
})

# §17-причины деградации, аддитивные к существующим ok/round_limit/llm_error
# (ADR-1020-7 §1 effective AMEND; существующие ветки не меняются).
CHAIN_TIMEOUT_REASON = "chain_timeout"
CHAIN_CALL_LIMIT_REASON = "chain_call_limit"
CHAIN_COST_LIMIT_REASON = "chain_cost_limit"

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
    * ``tool_trace`` — ``[{"round", "tool", "ok", "out_chars"}, …]``;
    * ``tool_context`` — склеенный текст выводов инструментов (нужен F2 для
      допустимых grounding-якорей: id/даты, полученные ИЗ ТУЛОВ; в логи не
      пишется, R17).
    * ``tool_results`` — A2/ADR-1026-15 D1: out-of-band envelope-журнал
      ``[{round, tool, args_fingerprint, status, data, error_code, error_type,
      truncated, metered, duplicate, attempt, out_chars}, …]`` — структурный
      спутник каждого вызова. НЕ сериализуется в модельный ввод; ключи
      ``tool_trace`` сохранены байт-в-байт (совместимость).

    Атрибуты не сериализуются и не влияют на строковое равенство.
    """

    def __new__(cls, text, *, rounds_used=1, degraded=False, reason="ok",
                tool_trace=None, tool_context=None, tool_results=None):
        obj = super().__new__(cls, str(text or ""))
        obj.rounds_used = int(rounds_used)
        obj.degraded = bool(degraded)
        obj.reason = str(reason or "ok")
        obj.tool_trace = list(tool_trace) if tool_trace else []
        obj.tool_context = str(tool_context or "")
        obj.tool_results = list(tool_results) if tool_results else []
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


def _chain_limits_enabled() -> bool:
    """env-only kill-switch ``TOOL_CHAIN_LIMITS_ENABLED`` (A2; default ON).

    OFF → §17-лимиты (cap/тайм-аут/дедуп/расходы) НЕ применяются; поведение
    цикла = baseline. Envelope остаётся out-of-band (модельно-видимый контур
    не затрагивается)."""
    return bool(getattr(settings, "TOOL_CHAIN_LIMITS_ENABLED", True))


def _args_fingerprint(name: str, arguments) -> str:
    """R17-safe отпечаток вызова = имя + канонические аргументы.

    ``json.dumps(sort_keys=True)`` — канон сравнения одинаковых вызовов
    (ADR-1026-15 D3). Возвращается короткий хэш: аргументы в открытом виде
    никогда не логируются/не хранятся в envelope."""
    try:
        canon = json.dumps(arguments, sort_keys=True, ensure_ascii=False,
                           default=str)
    except Exception:
        canon = repr(type(arguments).__name__)
    return hashlib.sha256(f"{name}\x00{canon}".encode("utf-8")).hexdigest()[:16]


def _classify_output(name: str, output) -> dict:
    """Структурная классификация модельно-видимого вывода (ADR-1026-15 D1/D2).

    Модельно-видимый ``output`` НЕ меняется; возвращаются производные поля
    envelope: ``status`` (ok/error), ``error_code``/``error_type``, ``data``
    (структурный JSON-payload, если вывод — JSON-объект), ``truncated``.
    Ничего не бросает."""
    text = str(output or "")
    info = {"status": "ok", "error_code": "", "error_type": "",
            "data": None, "truncated": False}
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            info["data"] = payload
            if payload.get("truncated"):
                info["truncated"] = True
            pstatus = str(payload.get("status") or "").strip().lower()
            if pstatus == "error":
                info["status"] = "error"
                reason = str(payload.get("error") or payload.get("reason")
                             or "tool_error")
                info["error_code"] = reason[:64]
                info["error_type"] = reason[:120]
            elif pstatus == "not_found":
                info["error_code"] = "not_found"
    if info["status"] == "ok" and text.startswith("ОШИБКА"):
        info["status"] = "error"
        if "неизвестный инструмент" in text:
            info["error_code"] = "unknown_tool"
        elif "timeout" in text.lower():
            info["error_code"] = "timeout"
        else:
            info["error_code"] = "tool_error"
        match = re.match(r"ОШИБКА[^:]*:\s*(.+)$", stripped)
        info["error_type"] = (match.group(1).strip() if match else "error")[:120]
    if not info["truncated"] and stripped.endswith("…"):
        info["truncated"] = True
    return info


def _record(ctx, tool_results: list, envelope: dict) -> None:
    """Записать envelope в журнал прогона (локальный + ``ctx.tool_results``).

    ``ctx`` может быть произвольным объектом (тесты передают MagicMock/object)
    → запись в контекст best-effort, сбой не роняет цикл."""
    tool_results.append(envelope)
    try:
        bucket = getattr(ctx, "tool_results", None)
        if isinstance(bucket, list):
            bucket.append(envelope)
    except Exception:
        pass


def _make_envelope(round_index: int, name: str, fingerprint: str, info: dict,
                   *, metered: bool, duplicate: bool, attempt: int,
                   out_chars: int) -> dict:
    """Envelope-запись вызова (ADR-1026-15 D1): out-of-band, R17-safe.

    ``data`` — структурный результат (JSON-payload), если применимо;
    ``args_fingerprint`` — короткий хэш, без сырых аргументов."""
    return {
        "round": int(round_index) + 1,
        "tool": str(name),
        "args_fingerprint": str(fingerprint),
        "status": str(info.get("status") or "ok"),
        "data": info.get("data"),
        "error_code": str(info.get("error_code") or ""),
        "error_type": str(info.get("error_type") or ""),
        "truncated": bool(info.get("truncated")),
        "metered": bool(metered),
        "duplicate": bool(duplicate),
        "attempt": int(attempt),
        "out_chars": int(out_chars),
    }


async def chat_with_tools(llm, messages: list[dict], *,
                          tools: list[dict], router, ctx,
                          temperature: float | None = None,
                          chat_id: int | None = None,
                          module: str | None = None,
                          correlation_id: str | None = None) -> "ToolLoopResult":
    """→ ``ToolLoopResult`` (str) — финальный текст + телеметрия.

    При исчерпании ``TOOL_MAX_ROUNDS`` или ``LLMError`` на ``round_index > 0``
    возвращается частичный ответ либо ``TOOL_LOOP_FALLBACK_PHRASE``
    (``degraded=True``) — НЕ тишина и НЕ исключение (ADR-1020-7 §1).
    Провайдер-reject на 1-м раунде — plain-фолбэк без tools (FR-15);
    ``NoApiKeyForChat`` — проброс; пустой финал — прежний
    ``LLMBadResponseError`` (FR-14/65.1).

    A2 (ADR-1026-15 D1/D3): на каждый вызов строится out-of-band envelope
    (``tool_results`` + ``ctx.tool_results``); модельно-видимый канал
    (``role:"tool"`` / ``tool_context``) не меняется (гибрид D1). При ON
    действуют §17-лимиты (cap 6 / мягкий тайм-аут 360 c / дедуп ≤2 / платные
    4) с аддитивными причинами деградации ``chain_*`` (in-flight не
    отменяется).
    """
    limits_on = _chain_limits_enabled()
    payload_messages = copy.deepcopy(messages)
    tool_trace: list[dict] = []
    tool_results: list[dict] = []
    tool_context_parts: list[str] = []
    partial_text = ""
    # §17-состояние прогона (in-memory; OFF → не используется).
    deadline = (time.monotonic() + TOOL_CHAIN_TIMEOUT_SECONDS
                if limits_on else None)
    total_calls = 0
    metered_calls = 0
    same_calls: dict[str, int] = {}
    last_by_fp: dict[str, str] = {}
    degrade_reason = ""
    # F7 (ADR-1023-7 D4): имена инструментов, исполненных ПЕРЕД текущим
    # LLM-вызовом — для телеметрии `step='tool'` (`tool_name`). На первом
    # (Stage-1) раунде пусто; далее — из tool_calls предыдущего раунда.
    pending_tool_name = ""
    for round_index in range(TOOL_MAX_ROUNDS):
        # §17: граница раунда — мягкий wall-clock (in-flight не отменяем;
        # уже полученный результат не рушим).
        if (limits_on and deadline is not None and round_index > 0
                and time.monotonic() > deadline):
            text = strip_reasoning_tags(partial_text) or TOOL_LOOP_FALLBACK_PHRASE
            _log_degraded(CHAIN_TIMEOUT_REASON, round_index, tool_trace, text)
            return ToolLoopResult(
                text, rounds_used=round_index, degraded=True,
                reason=CHAIN_TIMEOUT_REASON, tool_trace=tool_trace,
                tool_context="\n".join(tool_context_parts),
                tool_results=tool_results)
        try:
            result = await llm.generate_chat(
                payload_messages, temperature=temperature,
                tools=tools, tool_choice="auto", chat_id=chat_id,
                module=module,
                # Первый раунд — это Stage-1 (Синтезатор с тулами);
                # последующие — tool-раунды (ADR-1023-7 D4).
                step=("stage1" if round_index == 0 else "tool"),
                correlation_id=correlation_id,
                tool_name=(pending_tool_name if round_index > 0 else ""))
        except NoApiKeyForChat:
            raise
        except LLMError as exc:                 # провайдер не умеет tools
            if round_index == 0:
                logger.warning(
                    "[tools] provider rejected tools — plain answer | error=%s",
                    exc)
                # degrade: 1 обычный вызов БЕЗ tools (FR-15, AC-2.5)
                plain = await llm.generate(
                    messages, temperature=temperature, chat_id=chat_id,
                    module=module, step="single",
                    correlation_id=correlation_id)
                return ToolLoopResult(plain, rounds_used=1,
                                      tool_results=tool_results)
            # БЛОК 7.1: поздний раунд — не пробрасываем (не теряем ответ).
            text = strip_reasoning_tags(partial_text) or TOOL_LOOP_FALLBACK_PHRASE
            _log_degraded("llm_error", round_index, tool_trace, text)
            return ToolLoopResult(text, rounds_used=round_index,
                                  degraded=True, reason="llm_error",
                                  tool_trace=tool_trace,
                                  tool_context="\n".join(tool_context_parts),
                                  tool_results=tool_results)
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
                                      tool_trace=tool_trace,
                                      tool_context="\n".join(tool_context_parts),
                                      tool_results=tool_results)
            raise LLMBadResponseError("tool loop: empty final answer")
        tool_calls: list[LLMToolCall] = result.tool_calls
        if len(tool_calls) > _TOOL_CALLS_PER_ROUND_MAX:   # защита от спама
            logger.warning("[tools] tool_calls truncated | %d -> %d | round=%d",
                           len(tool_calls), _TOOL_CALLS_PER_ROUND_MAX,
                           round_index + 1)
            tool_calls = tool_calls[:_TOOL_CALLS_PER_ROUND_MAX]
        # Имена фактически запрошенных тулов — станут `tool_name` события
        # СЛЕДУЮЩЕГО (tool-)раунда.
        pending_tool_name = ",".join(
            tc.name for tc in tool_calls if tc.name)
        # A9 (ADR-1026-22 D5): TOOL_PLAN_CREATED — запрошенные инструменты.
        emit_agentic_event(
            "TOOL_PLAN_CREATED", run_id=correlation_id, chat_id=chat_id,
            tools=[tc.name for tc in tool_calls if tc.name],
            round=round_index + 1)
        assistant_message = {"role": "assistant",
                             "content": result.content or None,
                             "tool_calls": [tc.as_openai_dict()
                                            for tc in tool_calls]}
        payload_messages.append(assistant_message)
        limit_hit = False
        for tc in tool_calls:
            metered = tc.name in METERED_TOOLS
            # (а) аргументы: кривой JSON/тип → структурный tool-error (как было).
            try:
                arguments = json.loads(tc.arguments) \
                    if (tc.arguments or "").strip() else {}
                if not isinstance(arguments, dict):
                    raise ValueError("arguments not object")
            except Exception as exc:
                logger.warning("[tools] exec failed | tool=%s | error=%s",
                               tc.name, f"{type(exc).__name__}: {exc}")
                output = f"ОШИБКА {tc.name}: {type(exc).__name__}"
                # A9 (D5): кривые аргументы → TOOL_CALL_FAILED (invalid_args).
                emit_agentic_event(
                    "TOOL_CALL_FAILED", run_id=correlation_id, chat_id=chat_id,
                    tool=tc.name, round=round_index + 1, status="failed",
                    error_code="invalid_args")
                fp = _args_fingerprint(tc.name, tc.arguments or "")
                attempt = same_calls.get(fp, 0) + 1
                same_calls[fp] = attempt
                total_calls += 1
                if metered:
                    metered_calls += 1
                info = _classify_output(tc.name, output)
                _record(ctx, tool_results, _make_envelope(
                    round_index, tc.name, fp, info, metered=metered,
                    duplicate=False, attempt=attempt, out_chars=len(output)))
                payload_messages.append({"role": "tool",
                                         "tool_call_id": tc.id,
                                         "content": output})
                tool_context_parts.append(output)
                tool_trace.append({"round": round_index + 1, "tool": tc.name,
                                   "ok": False, "out_chars": len(output or "")})
                logger.info("[tools] round=%d | tool=%s | out_chars=%d",
                            round_index + 1, tc.name, len(output))
                continue
            fp = _args_fingerprint(tc.name, arguments)

            # (б) §17-дедуп одинакового вызова: сверх лимита — НЕ диспетчим,
            # возвращаем прежний результат (идемпотентно, как требует D3).
            if limits_on and same_calls.get(fp, 0) >= _TOOL_MAX_SAME_CALL \
                    and fp in last_by_fp:
                output = last_by_fp[fp]
                attempt = same_calls[fp] + 1
                same_calls[fp] = attempt
                info = _classify_output(tc.name, output)
                _record(ctx, tool_results, _make_envelope(
                    round_index, tc.name, fp, info, metered=metered,
                    duplicate=True, attempt=attempt, out_chars=len(output)))
                payload_messages.append({"role": "tool",
                                         "tool_call_id": tc.id,
                                         "content": output})
                tool_context_parts.append(output)
                tool_trace.append({"round": round_index + 1, "tool": tc.name,
                                   "ok": True, "out_chars": len(output or "")})
                logger.info(
                    "[tools] duplicate call skipped | tool=%s | round=%d | "
                    "attempt=%d", tc.name, round_index + 1, attempt)
                # A9 (D5): дедуп-скип — результат отдан из кэша (status ok).
                emit_agentic_event(
                    "TOOL_CALL_COMPLETE", run_id=correlation_id, chat_id=chat_id,
                    tool=tc.name, round=round_index + 1, status="ok",
                    out_chars=len(output or ""))
                continue

            # (в) §17-лимиты ПЕРЕД диспетчем (мягкие: in-flight не отменяем).
            if limits_on:
                skip_code = ""
                if deadline is not None and time.monotonic() > deadline:
                    skip_code = CHAIN_TIMEOUT_REASON
                elif total_calls >= TOOL_MAX_TOTAL_CALLS:
                    skip_code = CHAIN_CALL_LIMIT_REASON
                elif metered and metered_calls >= TOOL_CHAIN_MAX_METERED_CALLS:
                    skip_code = CHAIN_COST_LIMIT_REASON
                if skip_code:
                    _record(ctx, tool_results, _make_envelope(
                        round_index, tc.name, fp,
                        {"status": "skipped", "error_code": skip_code,
                         "error_type": "", "data": None, "truncated": False},
                        metered=metered, duplicate=False,
                        attempt=same_calls.get(fp, 0), out_chars=0))
                    logger.warning(
                        "[tools] chain limit | reason=%s | tool=%s | round=%d "
                        "| total_calls=%d | metered_calls=%d",
                        skip_code, tc.name, round_index + 1, total_calls,
                        metered_calls)
                    # A9 (D5): chain-skip (timeout/call-limit/cost-limit).
                    emit_agentic_event(
                        "TOOL_CALL_FAILED", run_id=correlation_id,
                        chat_id=chat_id, tool=tc.name,
                        round=round_index + 1, status="skipped",
                        error_code=skip_code)
                    degrade_reason = skip_code
                    limit_hit = True
                    break

            # (г) исполнение (существующий путь; ошибка — структурный текст).
            ok = True
            # A9 (D5): TOOL_CALL_START — перед фактическим dispatch.
            emit_agentic_event(
                "TOOL_CALL_START", run_id=correlation_id, chat_id=chat_id,
                tool=tc.name, round=round_index + 1)
            try:
                output = await router.dispatch(tc.name, arguments, ctx)
            except Exception as exc:              # инструмент упал — модель видит текст
                ok = False
                logger.warning("[tools] exec failed | tool=%s | error=%s",
                               tc.name, f"{type(exc).__name__}: {exc}")
                output = f"ОШИБКА {tc.name}: {type(exc).__name__}"
            total_calls += 1
            if metered:
                metered_calls += 1
            attempt = same_calls.get(fp, 0) + 1
            same_calls[fp] = attempt
            last_by_fp[fp] = output
            info = _classify_output(tc.name, output)
            _record(ctx, tool_results, _make_envelope(
                round_index, tc.name, fp, info, metered=metered,
                duplicate=False, attempt=attempt, out_chars=len(output)))
            payload_messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": output})
            tool_context_parts.append(output)
            tool_trace.append({"round": round_index + 1, "tool": tc.name,
                               "ok": ok, "out_chars": len(output or "")})
            logger.info("[tools] round=%d | tool=%s | out_chars=%d",
                        round_index + 1, tc.name, len(output))
            # A9 (D5): исход вызова — COMPLETE (ok) или FAILED (исключение).
            if ok:
                emit_agentic_event(
                    "TOOL_CALL_COMPLETE", run_id=correlation_id,
                    chat_id=chat_id, tool=tc.name, round=round_index + 1,
                    status=str(info.get("status") or "ok"),
                    out_chars=len(output or ""))
            else:
                emit_agentic_event(
                    "TOOL_CALL_FAILED", run_id=correlation_id, chat_id=chat_id,
                    tool=tc.name, round=round_index + 1, status="failed",
                    error_code=str(info.get("error_code") or "tool_error"))
        if limit_hit:
            break
    # §17-лимит цепочки — graceful degradation (частичный результат, при ON).
    if degrade_reason:
        text = strip_reasoning_tags(partial_text) or TOOL_LOOP_FALLBACK_PHRASE
        rounds_used = round_index + 1
        _log_degraded(degrade_reason, rounds_used, tool_trace, text)
        return ToolLoopResult(text, rounds_used=rounds_used, degraded=True,
                              reason=degrade_reason, tool_trace=tool_trace,
                              tool_context="\n".join(tool_context_parts),
                              tool_results=tool_results)
    # лимит раундов исчерпан — graceful degradation (НЕ исключение).
    text = strip_reasoning_tags(partial_text) or TOOL_LOOP_FALLBACK_PHRASE
    _log_degraded("round_limit", TOOL_MAX_ROUNDS, tool_trace, text)
    return ToolLoopResult(text, rounds_used=TOOL_MAX_ROUNDS, degraded=True,
                          reason="round_limit", tool_trace=tool_trace,
                          tool_context="\n".join(tool_context_parts),
                          tool_results=tool_results)
