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
from services import tool_result
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
# MCA-19 (ADR-1028-19 §8.6): recognize_image — метричный (vision-вызов);
# cache_hit НЕ тратит vision-токены (D20).
# MCA-20 (ADR-1028-20 §7.5, round 10.44): fact_check — метричный (8→9);
# cache_hit вердикта — 0 LLM-токенов (D12).
METERED_TOOLS = frozenset({
    "execute_web_search", "fetch_article", "summarize_video", "download_media",
    "compile_lore_story", "generate_image", "transcribe_video",
    "recognize_image", "fact_check",
})

# §17-причины деградации, аддитивные к существующим ok/round_limit/llm_error
# (ADR-1020-7 §1 effective AMEND; существующие ветки не меняются).
CHAIN_TIMEOUT_REASON = "chain_timeout"
CHAIN_CALL_LIMIT_REASON = "chain_call_limit"
CHAIN_COST_LIMIT_REASON = "chain_cost_limit"

# ── MCA-23 фаза 2 (§17/§39): bounded multi-tool DAG ─────────────────────────
# План строит ResponsePlanner (services/response_extent, 0 LLM); здесь —
# исполнение ПОВЕРХ существующего цикла (НЕ второй агент): шаги в
# топологическом порядке через существующий router.dispatch + ToolResult
# envelope; затем ОДИН модельный контур (Stage-1 видит результаты блоком
# <tool_plan_results> и синтезирует; может вызвать дополнительные tools —
# общие §17-бюджеты). Обычные сценарии (micro/chat/один tool) идут прежним
# путём байт-в-байт: tool_plan=None → планирование не активируется.
PLAN_MAX_STEPS = 6        # шагов не больше суммарного cap вызовов (§39)
PLAN_MAX_REPLANS = 2      # §39 ceiling re-plan; фаза 2: re-plan = 0 (bounded)

# §18-I: tools, доставляющие медиа сами (файл уходит пользователю из тулa,
# Writer-регенерация результата бесполезна). Статусы — только канонические.
MEDIA_DELIVERY_TOOLS = frozenset({"download_media", "generate_image"})

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
      MCA-11 (ADR-1028-13 D1, K1 ON): статусы канонические
      (``ok/empty/error/timeout/cancelled/denied/delivery_unknown``) +
      аддитивные поля ``category/retryable/duration_ms/usage/
      external_operation_id/evidence_refs/partial``; K1 OFF — прежние
      ключи/статусы байт-в-байт (legacy ``ok/error/skipped``).

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


# ── MCA-23 фаза 2 (§17/§38): нормализация и исполнение плана ────────────────

def _plan_announced_tools(tools) -> set:
    """Имена инструментов, АНОНСИРОВАННЫХ LLM (runtime candidate set).

    Из схем active_tools (``{"function": {"name": ...}}``); мусор молча
    пропускается. Никогда не бросает."""
    names: set = set()
    for schema in tools or []:
        try:
            name = str(((schema or {}).get("function") or {}).get("name") or "")
        except Exception:
            continue
        if name:
            names.add(name)
    return names


def normalize_tool_plan(raw_plan, *, announced=None) -> list:
    """Валидация плана (§38; никог는 не бросает).

    * шаг = dict с непустым ``tool``; неизвестный/неанонсированный tool →
      шаг ВЫБРАСЫВАЕТСЯ (не исполняется);
    * ``arguments`` — dict (иначе {});
    * ``depends_on`` — только id валидных шагов (неизвестные отбрасываются);
    * ``failure_policy`` — ``required`` | ``optional`` (иное → ``optional``);
    * больше PLAN_MAX_STEPS шагов → первые PLAN_MAX_STEPS (§39)."""
    if not isinstance(raw_plan, (list, tuple)):
        return []
    seen: set = set()
    steps: list = []
    for item in list(raw_plan)[:PLAN_MAX_STEPS]:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip()
        if not tool:
            continue
        if announced is not None and tool not in announced:
            continue
        step_id = str(item.get("step_id") or "").strip() or f"step_{len(steps) + 1}"
        if step_id in seen:
            continue
        seen.add(step_id)
        arguments = item.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        policy = str(item.get("failure_policy") or "").strip().lower()
        if policy not in ("required", "optional"):
            policy = "optional"
        raw_deps = item.get("depends_on")
        deps = ([str(d).strip() for d in raw_deps]
                if isinstance(raw_deps, (list, tuple)) else [])
        steps.append({"step_id": step_id, "tool": tool,
                      "arguments": dict(arguments),
                      "depends_on": deps, "failure_policy": policy})
    valid_ids = {s["step_id"] for s in steps}
    for step in steps:
        step["depends_on"] = [d for d in step["depends_on"]
                              if d and d in valid_ids]
    return steps


def _topo_order(steps: list) -> list:
    """Топологический порядок (Kahn): родители раньше детей; участники
    цикла отбрасываются (bounded, детерминированно по порядку плана)."""
    remaining = list(steps)
    ordered: list = []
    done: set = set()
    while remaining:
        progressed = False
        for step in list(remaining):
            if all(dep in done for dep in step["depends_on"]):
                ordered.append(step)
                done.add(step["step_id"])
                remaining.remove(step)
                progressed = True
        if not progressed:      # цикл → зависшие шаги не исполняются
            break
    return ordered


def media_delivered(result) -> bool:
    """§18-I: в envelopes прогона есть УСПЕШНЫЙ media-инструмент.

    Статус — только канонический ``ok`` (тул сам доставил файл пользовате-
    лю). Никогда не бросает; без envelopes/атрибута → False."""
    try:
        envelopes = getattr(result, "tool_results", None) or []
    except Exception:
        return False
    for env in envelopes:
        try:
            if (str(env.get("tool") or "") in MEDIA_DELIVERY_TOOLS
                    and str(env.get("status") or "") == "ok"):
                return True
        except Exception:
            continue
    return False


def _render_plan_block(parts: list, limitations: list) -> str:
    """Модельно-видимый блок результатов плана (§17 synthesis; в логи не
    пишется). limitations — честные пометки о несостоявшихся шагах (§19)."""
    lines = ["<tool_plan_results>"]
    lines.extend(parts)
    if limitations:
        lines.append("ОГРАНИЧЕНИЯ: " + "; ".join(limitations)
                     + ". Недостающие данные НЕ выдумывай — ответь честно, "
                       "что эта часть недоступна.")
    lines.append("</tool_plan_results>")
    return "\n\n".join(lines)


def _append_plan_block(payload_messages: list, block: str) -> None:
    """Аддитивный user-блок (прецедент <dig_result>/<image_result>) — в
    ПОСЛЕДНЕЕ user-сообщение; если его нет/контент не str — отдельным
    user-сообщением. Мутирует только локальную копию payload (вход не
    меняется)."""
    for index in range(len(payload_messages) - 1, -1, -1):
        message = payload_messages[index]
        try:
            if message.get("role") == "user" \
                    and isinstance(message.get("content"), str):
                message["content"] = message["content"].rstrip() \
                    + "\n\n" + block
                return
        except Exception:
            break
    payload_messages.append({"role": "user", "content": block})


# ── MCA-11 (ADR-1028-13 D2): env-only числа лимитов поверх существующих cap'ов.
# Дефолты = текущие код-константы (байт-паритет); enforcement остаётся здесь.
def _max_total_calls() -> int:
    return _int_setting("MCA_TOOL_MAX_TOTAL_CALLS", TOOL_MAX_TOTAL_CALLS)


def _max_metered_calls() -> int:
    return _int_setting("MCA_TOOL_MAX_METERED_CALLS",
                        TOOL_CHAIN_MAX_METERED_CALLS)


def _max_same_call() -> int:
    return _int_setting("MCA_TOOL_MAX_SAME_CALL", _TOOL_MAX_SAME_CALL)


def _chain_timeout_seconds() -> float:
    try:
        return float(getattr(settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS",
                             TOOL_CHAIN_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return TOOL_CHAIN_TIMEOUT_SECONDS


def _int_setting(name: str, default: int) -> int:
    try:
        return max(1, int(getattr(settings, name, default)))
    except (TypeError, ValueError):
        return default


def _contract_on() -> bool:
    """K1 ``MCA_TOOL_RESULT_ENABLED``: канонический envelope либо legacy."""
    return tool_result.enabled()


def _guard_on() -> bool:
    """K2 ``MCA_TOOL_DELIVERY_GUARD_ENABLED`` (вместе с K1 — контракт)."""
    return _contract_on() and tool_result.delivery_guard_enabled()


def _classify(name: str, output, signal: dict | None = None) -> dict:
    """Деривация ToolResult: K1 ON → каноническая; OFF → legacy байт-в-байт."""
    if _contract_on():
        return tool_result.classify_output(name, output, signal=signal)
    return _classify_output(name, output)


def _envelope(round_index: int, name: str, fingerprint: str, info: dict, *,
              metered: bool, duplicate: bool, attempt: int, out_chars: int,
              duration_ms: int = 0) -> dict:
    """Envelope-запись: K1 ON → канонические ключи; OFF → legacy байт-в-байт."""
    if _contract_on():
        return tool_result.make_envelope(
            round_index, name, fingerprint, info, metered=metered,
            duplicate=duplicate, attempt=attempt, out_chars=out_chars,
            duration_ms=duration_ms)
    return _make_envelope(round_index, name, fingerprint, info,
                          metered=metered, duplicate=duplicate,
                          attempt=attempt, out_chars=out_chars)


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
                          correlation_id: str | None = None,
                          fallback_payload_adapter=None,
                          max_output_tokens: int | None = None,
                          tool_plan: list[dict] | None = None
                          ) -> "ToolLoopResult":
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

    ASAP-3.2 (ADR-1028-5 D10, §44): ``fallback_payload_adapter`` — тот же
    контракт, что у ``generate()``/``generate_chat()``; прокидывается в
    КАЖДЫЙ вызов цикла (Stage-1 и tool-раунды) и в FR-15 plain-фолбэк —
    фоллбэк на меньшую модель НЕ получает payload, собранный под большее
    primary-окно (tool schemas учитываются адаптером, §45).

    MCA-23 фаза 2 (§Model slots): ``max_output_tokens`` — модельный слот
    длины (longform-планы); None → ключ ``max_tokens`` в payload НЕ
    добавляется (байт-паритет прежних tool-вызовов). Прокидывается в каждый
    вызов цикла и в FR-15 plain-фолбэк; ключ переживает recompose.

    MCA-23 фаза 2 (§17): ``tool_plan`` — ЯВНЫЙ мульти-шаговый план
    (ResponsePlanner, services/response_extent). None/пустой → обычный
    model-driven путь байт-в-байт. Непустой план: шаги исполняются ДО
    модельных раундов в топологическом порядке через существующий
    ``router.dispatch`` (ToolResult envelope, §17-бюджеты ОБЩИЕ с циклом:
    cap/тайм-аут/дедуп/side-effect-гард), результаты — одним аддитивным
    user-блоком ``<tool_plan_results>`` в Stage-1 (синтез + limitations);
    failure_policy=optional → limitation, required → честная деградация
    (§19); ``round=0`` в trace/envelope отличает плановые шаги от
    модельных раундов. Re-plan в фазе 2 не выполняется (≤2, §39).
    """
    limits_on = _chain_limits_enabled()
    payload_messages = copy.deepcopy(messages)
    tool_trace: list[dict] = []
    tool_results: list[dict] = []
    tool_context_parts: list[str] = []
    partial_text = ""
    # §17-состояние прогона (in-memory; OFF → не используется).
    # MCA-11 D2: числа — env-only (дефолты = прежние код-константы).
    deadline = (time.monotonic() + _chain_timeout_seconds()
                if limits_on else None)
    total_calls = 0
    metered_calls = 0
    same_calls: dict[str, int] = {}
    last_by_fp: dict[str, str] = {}
    # MCA-11 D3: последний канонический/legacy-результат по отпечатку —
    # запрет слепого повтора side effect после успеха/delivery_unknown.
    last_info_by_fp: dict[str, dict] = {}
    degrade_reason = ""
    # F7 (ADR-1023-7 D4): имена инструментов, исполненных ПЕРЕД текущим
    # LLM-вызовом — для телеметрии `step='tool'` (`tool_name`). На первом
    # (Stage-1) раунде пусто; далее — из tool_calls предыдущего раунда.
    pending_tool_name = ""
    # ── MCA-23 фаза 2 (§17): bounded multi-tool DAG ────────────────────────
    # Активируется ТОЛЬКО непустым tool_plan; обычные сценарии идут прежним
    # путём байт-в-байт. Шаги исполняются через СУЩЕСТВУЮЩИЙ dispatch/
    # envelope; §17-бюджеты (total/metered/deadline/dedup/side-effect) общие
    # с модельными раундами ниже. Граф не активируется без явного плана.
    plan_steps = normalize_tool_plan(
        tool_plan, announced=_plan_announced_tools(tools)) \
        if tool_plan else []
    plan_parts: list[str] = []
    plan_limitations: list[str] = []
    if plan_steps:
        # A9: план ДО исполнения (постфактум-сигнал модельных tool_calls
        # не дублируется: плановые шаги помечены round=0).
        emit_agentic_event(
            "TOOL_PLAN_CREATED", run_id=correlation_id, chat_id=chat_id,
            tools=[s["tool"] for s in plan_steps], round=0)
        for step in _topo_order(plan_steps):
            name = step["tool"]
            arguments = step["arguments"]
            metered = name in METERED_TOOLS
            fp = _args_fingerprint(name, arguments)
            # (а) §17-дедуп + MCA-11 D3-гард side effects — тот же контракт,
            # что в модельных раундах (слепой повтор запрещён).
            cached_reason = ""
            if limits_on and fp in last_by_fp:
                if same_calls.get(fp, 0) >= _max_same_call():
                    cached_reason = "dedup"
                elif (_guard_on() and not tool_result.is_idempotent(name)
                      and str((last_info_by_fp.get(fp) or {}).get("status"))
                      in (tool_result.STATUS_OK,
                          tool_result.STATUS_DELIVERY_UNKNOWN)):
                    cached_reason = "side_effect"
            if not cached_reason:
                # (б) §17-лимиты ПЕРЕД диспетчем (мягкие: как в раундах).
                if limits_on:
                    skip_code = ""
                    limit_kind = ""
                    limit_value = None
                    now_mono = time.monotonic()
                    if deadline is not None and now_mono > deadline:
                        skip_code = CHAIN_TIMEOUT_REASON
                        limit_kind = "tool_chain_deadline"
                        limit_value = round(
                            max(0.0, now_mono - deadline), 1)
                    elif total_calls >= _max_total_calls():
                        skip_code = CHAIN_CALL_LIMIT_REASON
                        limit_kind = "tool_calls"
                        limit_value = total_calls
                    elif metered and metered_calls >= _max_metered_calls():
                        skip_code = CHAIN_COST_LIMIT_REASON
                        limit_kind = "tool_metered_calls"
                        limit_value = metered_calls
                    if skip_code:
                        # §19: partial failure не роняет run — шаг в honest
                        # limitation, исполнение плана/цикла продолжается.
                        limit = tool_result.limit_record(
                            limit_kind, limit_value, skip_code)
                        info = {"status": ("denied" if _contract_on()
                                           else "skipped"),
                                "error_code": skip_code, "error_type": "",
                                "data": (limit if _contract_on() else None),
                                "truncated": False, "retryable": False,
                                "partial": False, "usage": {},
                                "evidence_refs": [],
                                "external_operation_id": None}
                        _record(ctx, tool_results, _envelope(
                            -1, name, fp, info, metered=metered,
                            duplicate=False, attempt=same_calls.get(fp, 0),
                            out_chars=0))
                        tool_result.emit_tool_chain_events(
                            tool=name, status="denied", chat_id=chat_id,
                            correlation_id=correlation_id,
                            args_fingerprint=fp,
                            attempt=same_calls.get(fp, 0),
                            chain_limit_code=skip_code)
                        emit_agentic_event(
                            "TOOL_CALL_FAILED", run_id=correlation_id,
                            chat_id=chat_id, tool=name, round=0,
                            status="denied", error_code=skip_code)
                        plan_limitations.append(
                            f"шаг {step['step_id']} не выполнен "
                            f"({skip_code})")
                        continue
                # (в) исполнение (существующий механизм; ошибка — структурный
                # текст; R17: только класс исключения).
                emit_agentic_event(
                    "TOOL_CALL_START", run_id=correlation_id,
                    chat_id=chat_id, tool=name, round=0)
                started = time.monotonic()
                try:
                    output = await router.dispatch(name, arguments, ctx)
                except Exception as exc:
                    logger.warning(
                        "[tools] plan step failed | tool=%s | error=%s",
                        name, f"{type(exc).__name__}: {exc}")
                    output = f"ОШИБКА {name}: {type(exc).__name__}"
                duration_ms = int((time.monotonic() - started) * 1000)
                signal = tool_result.take_signal(ctx)
                total_calls += 1
                if metered:
                    metered_calls += 1
                attempt = same_calls.get(fp, 0) + 1
                same_calls[fp] = attempt
                last_by_fp[fp] = output
                info = _classify(name, output, signal)
                last_info_by_fp[fp] = info
                _record(ctx, tool_results, _envelope(
                    -1, name, fp, info, metered=metered, duplicate=False,
                    attempt=attempt, out_chars=len(output),
                    duration_ms=duration_ms))
                tool_result.emit_tool_chain_events(
                    tool=name, status=str(info.get("status") or ""),
                    chat_id=chat_id, correlation_id=correlation_id,
                    args_fingerprint=fp, duration_ms=duration_ms,
                    attempt=attempt, usage=info.get("usage"),
                    error_code=str(info.get("error_code") or ""))
                status = str(info.get("status") or "")
                if status in (tool_result.STATUS_OK, tool_result.STATUS_EMPTY):
                    emit_agentic_event(
                        "TOOL_CALL_COMPLETE", run_id=correlation_id,
                        chat_id=chat_id, tool=name, round=0, status=status,
                        out_chars=len(output or ""))
                else:
                    emit_agentic_event(
                        "TOOL_CALL_FAILED", run_id=correlation_id,
                        chat_id=chat_id, tool=name, round=0,
                        status=("failed" if not _contract_on() else status),
                        error_code=str(info.get("error_code") or "tool_error"))
                # (г) failure_policy (§19): optional → limitation,
                # required → честная деградация (пометка модели).
                if status not in (tool_result.STATUS_OK,
                                  tool_result.STATUS_EMPTY):
                    err = str(info.get("error_code")
                              or info.get("error_type") or "error")[:64]
                    if step["failure_policy"] == "required":
                        plan_limitations.append(
                            f"обязательный шаг {step['step_id']} "
                            f"не выполнился ({err})")
                    else:
                        plan_limitations.append(
                            f"шаг {step['step_id']} не выполнился ({err})")
            else:
                output = last_by_fp[fp]
                status = str((last_info_by_fp.get(fp) or {}).get("status")
                             or "ok")
                info = dict(last_info_by_fp.get(fp)
                            or _classify(name, output))
                # envelope дедуп-выдачи — тот же контракт, что в раундах.
                _record(ctx, tool_results, _envelope(
                    -1, name, fp, info, metered=metered, duplicate=True,
                    attempt=same_calls.get(fp, 0) + 1, out_chars=len(output)))
                same_calls[fp] = same_calls.get(fp, 0) + 1
                emit_agentic_event(
                    "TOOL_CALL_COMPLETE", run_id=correlation_id,
                    chat_id=chat_id, tool=name, round=0,
                    status=(str(info.get("status") or "ok")
                            if _contract_on() else "ok"),
                    out_chars=len(output or ""))
                logger.info(
                    "[tools] plan duplicate skipped | tool=%s | step=%s | "
                    "reason=%s", name, step["step_id"], cached_reason)
            tool_trace.append({"round": 0, "tool": name,
                               "ok": (True if cached_reason == "dedup"
                                      else status in (tool_result.STATUS_OK,
                                                      tool_result.STATUS_EMPTY)),
                               "out_chars": len(output or "")})
            tool_context_parts.append(output)
            plan_parts.append(f"[{step['step_id']} | {name}]\n{output}")
        if plan_parts:
            _append_plan_block(
                payload_messages,
                _render_plan_block(plan_parts, plan_limitations))
            logger.info(
                "[tools] plan executed | steps=%d | ok=%d | limitations=%d "
                "| total_calls=%d",
                len(plan_steps),
                sum(1 for entry in tool_trace if entry.get("round") == 0
                    and entry.get("ok")),
                len(plan_limitations), total_calls)
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
                tool_name=(pending_tool_name if round_index > 0 else ""),
                fallback_payload_adapter=fallback_payload_adapter,
                max_output_tokens=max_output_tokens)
        except NoApiKeyForChat:
            raise
        except LLMError as exc:                 # провайдер не умеет tools
            if round_index == 0:
                logger.warning(
                    "[tools] provider rejected tools — plain answer | error=%s",
                    exc)
                # degrade: 1 обычный вызов БЕЗ tools (FR-15, AC-2.5);
                # ADR-1028-5 D10: recompose-адаптер прокидывается и сюда —
                # plain-фолбэк тоже под бюджетом fallback-окна.
                # MCA-23 фаза 2: payload_messages (а не messages) — без
                # плана контент идентичен (deepcopy), с планом сохраняет
                # уже исполненные шаги <tool_plan_results> (результаты
                # честно попадают в plain-ответ).
                plain = await llm.generate(
                    payload_messages, temperature=temperature,
                    chat_id=chat_id, module=module, step="single",
                    correlation_id=correlation_id,
                    fallback_payload_adapter=fallback_payload_adapter,
                    max_output_tokens=max_output_tokens)
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
                info = _classify(tc.name, output)
                last_info_by_fp[fp] = info
                _record(ctx, tool_results, _envelope(
                    round_index, tc.name, fp, info, metered=metered,
                    duplicate=False, attempt=attempt, out_chars=len(output)))
                # D6: notable-терминал стадии execute (invalid-args → error).
                tool_result.emit_tool_chain_events(
                    tool=tc.name, status=str(info.get("status") or ""),
                    chat_id=chat_id, correlation_id=correlation_id,
                    args_fingerprint=fp, attempt=attempt,
                    error_code=str(info.get("error_code") or ""))
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

            # (б) §17-дедуп одинакового вызова + MCA-11 D3-гард side effects:
            # сверх лимита ЛИБО повтор неидемпотентной операции после
            # успеха/`delivery_unknown` — НЕ диспетчим, возвращаем прежний
            # результат (слепой повтор запрещён; exactly-once не обещается).
            cached_reason = ""
            if limits_on and fp in last_by_fp:
                if same_calls.get(fp, 0) >= _max_same_call():
                    cached_reason = "dedup"
                elif (_guard_on() and not tool_result.is_idempotent(tc.name)
                      and str((last_info_by_fp.get(fp) or {}).get("status"))
                      in (tool_result.STATUS_OK,
                          tool_result.STATUS_DELIVERY_UNKNOWN)):
                    cached_reason = "side_effect"
            if cached_reason:
                output = last_by_fp[fp]
                attempt = same_calls[fp] + 1
                same_calls[fp] = attempt
                info = dict(last_info_by_fp.get(fp)
                            or _classify(tc.name, output))
                _record(ctx, tool_results, _envelope(
                    round_index, tc.name, fp, info, metered=metered,
                    duplicate=True, attempt=attempt, out_chars=len(output)))
                payload_messages.append({"role": "tool",
                                         "tool_call_id": tc.id,
                                         "content": output})
                tool_context_parts.append(output)
                cached_ok = (True if cached_reason == "dedup"
                             else str(info.get("status")) == "ok")
                tool_trace.append({"round": round_index + 1, "tool": tc.name,
                                   "ok": cached_ok, "out_chars": len(output or "")})
                logger.info(
                    "[tools] duplicate call skipped | tool=%s | round=%d | "
                    "attempt=%d | reason=%s", tc.name, round_index + 1,
                    attempt, cached_reason)
                # A9 (D5): результат отдан из кэша (K1 OFF — прежний status ok).
                emit_agentic_event(
                    "TOOL_CALL_COMPLETE", run_id=correlation_id, chat_id=chat_id,
                    tool=tc.name, round=round_index + 1,
                    status=(str(info.get("status") or "ok")
                            if _contract_on() else "ok"),
                    out_chars=len(output or ""))
                continue

            # (в) §17-лимиты ПЕРЕД диспетчем (мягкие: in-flight не отменяем).
            if limits_on:
                skip_code = ""
                limit_kind = ""
                limit_value = None
                now_mono = time.monotonic()
                if deadline is not None and now_mono > deadline:
                    skip_code = CHAIN_TIMEOUT_REASON
                    limit_kind = "tool_chain_deadline"
                    limit_value = round(max(0.0, now_mono - deadline), 1)
                elif total_calls >= _max_total_calls():
                    skip_code = CHAIN_CALL_LIMIT_REASON
                    limit_kind = "tool_calls"
                    limit_value = total_calls
                elif metered and metered_calls >= _max_metered_calls():
                    skip_code = CHAIN_COST_LIMIT_REASON
                    limit_kind = "tool_metered_calls"
                    limit_value = metered_calls
                if skip_code:
                    # MCA-11 D1/D4: legacy `skipped` → канонический `denied`;
                    # единицы/область/значение/причина — в data (K1 ON).
                    limit = tool_result.limit_record(limit_kind, limit_value,
                                                     skip_code)
                    info = {"status": ("denied" if _contract_on()
                                       else "skipped"),
                            "error_code": skip_code, "error_type": "",
                            "data": (limit if _contract_on() else None),
                            "truncated": False, "retryable": False,
                            "partial": False, "usage": {},
                            "evidence_refs": [],
                            "external_operation_id": None}
                    _record(ctx, tool_results, _envelope(
                        round_index, tc.name, fp, info, metered=metered,
                        duplicate=False, attempt=same_calls.get(fp, 0),
                        out_chars=0))
                    # D6: notable-отказ стадии execute (chain-лимит) — код из
                    # единого словаря (chain_* → существующий mapped-код);
                    # событие — канонический статус `denied` независимо от K1.
                    tool_result.emit_tool_chain_events(
                        tool=tc.name, status="denied",
                        chat_id=chat_id, correlation_id=correlation_id,
                        args_fingerprint=fp,
                        attempt=same_calls.get(fp, 0),
                        chain_limit_code=skip_code)
                    if _contract_on():
                        logger.warning(
                            "[tools] chain limit | reason=%s | unit=%s | "
                            "scope=%s | value=%s | tool=%s | round=%d | "
                            "total_calls=%d | metered_calls=%d",
                            skip_code, limit["unit"], limit["scope"],
                            limit.get("value"), tc.name, round_index + 1,
                            total_calls, metered_calls)
                    else:
                        logger.warning(
                            "[tools] chain limit | reason=%s | tool=%s | round=%d "
                            "| total_calls=%d | metered_calls=%d",
                            skip_code, tc.name, round_index + 1, total_calls,
                            metered_calls)
                    # A9 (D5): chain-skip (timeout/call-limit/cost-limit).
                    emit_agentic_event(
                        "TOOL_CALL_FAILED", run_id=correlation_id,
                        chat_id=chat_id, tool=tc.name,
                        round=round_index + 1,
                        status=("denied" if _contract_on() else "skipped"),
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
            started = time.monotonic()
            try:
                output = await router.dispatch(tc.name, arguments, ctx)
            except Exception as exc:              # инструмент упал — модель видит текст
                ok = False
                logger.warning("[tools] exec failed | tool=%s | error=%s",
                               tc.name, f"{type(exc).__name__}: {exc}")
                output = f"ОШИБКА {tc.name}: {type(exc).__name__}"
            duration_ms = int((time.monotonic() - started) * 1000)
            # MCA-11 D1/D3: out-of-band сигнал обвязки (SafeFetcher stage/
            # delivery_unknown) — одноразово, в модельный ввод не попадает.
            signal = tool_result.take_signal(ctx)
            total_calls += 1
            if metered:
                metered_calls += 1
            attempt = same_calls.get(fp, 0) + 1
            same_calls[fp] = attempt
            last_by_fp[fp] = output
            info = _classify(tc.name, output, signal)
            last_info_by_fp[fp] = info
            _record(ctx, tool_results, _envelope(
                round_index, tc.name, fp, info, metered=metered,
                duplicate=False, attempt=attempt, out_chars=len(output),
                duration_ms=duration_ms))
            # D6: стадии tools.chain v2 — execute (notable-терминал),
            # deliver (`delivery_unknown`), account (usage/unknown ≠ 0).
            tool_result.emit_tool_chain_events(
                tool=tc.name, status=str(info.get("status") or ""),
                chat_id=chat_id, correlation_id=correlation_id,
                args_fingerprint=fp, duration_ms=duration_ms,
                attempt=attempt, usage=info.get("usage"),
                error_code=str(info.get("error_code") or ""))
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
