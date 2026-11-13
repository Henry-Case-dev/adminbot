"""Эпик 04.09.2026 (3.3, Часть 2) — цикл обработки tool_calls (Tool Calling).

Формат ролей OpenAI: assistant с tool_calls → роль "tool" по каждому
tool_call_id → повторный вызов generate_chat. При невозможности tool-режима
провайдера (детерминированный не-2xx на 1-м вызове) — один повтор БЕЗ tools
и обычный ответ (FR-15).

SMART-EXECUTION-RELIABILITY-01 (owner input 2026-11-14, этап B) — единая
политика исполнения для всех потребителей (Direct, L1-план, checkup,
inspect_runtime, SourceReader, поиск/fetch, фактчек, retrieval/memory):

* НЕТ фиксированных пределов исследования (4 раунда / 2 вызова за раунд /
  6 суммарных / 2 одинаковых / 4 «платных»): числа 4/2/6/4 больше не
  продуктовые потолки. Все корректно запрошенные вызовы исполняются и
  получают структурный результат; обрезки `tool_calls[:2]` нет.
* Завершение — по прогрессу/модели/реальному лимиту/отмене/безопасности:
  модель не просит инструментов (финальный ответ); два раунда подряд без
  ни одного нового исполнения (`no_progress`); подтверждённый технический
  отказ; явная операторская политика при `flags.budgets_enabled=true`;
  аварийный операторский fuse (`MCA_TOOL_CHAIN_TIMEOUT_SECONDS>0`).
* Дедуп — по нормализованным аргументам/идентичности операции: терминальный
  (`retryable=false`) повтор без изменения условий не исполняется, retryable
  повторяется в пределах `MCA_TOOL_TRANSIENT_RETRIES_MAX`, неидемпотентная
  операция после успеха/`delivery_unknown` не повторяется (safety).
* Каждый вызов даёт envelope с исходным `tool_call_id` и валидной
  последовательностью провайдера: `assistant(tool_calls)` → `tool` на
  КАЖДЫЙ id → `assistant`. Metered/usage — наблюдательные оси.

Все логи — с префиксом [tools]; WARNING на деградацию/лимит; INFO на раунд.

SMART-EXECUTION-RELIABILITY-01 §G (owner 2026-11-14, этап G) — обязательная
финализация исследования в ЭТОМ ЖЕ цикле (не новый агент/клиент/пайплайн):

* два логических состояния: сбор evidence (tool-раунды) и финальный ответ;
* штатный финальный ответ модели — без лишнего повторного LLM-вызова
  (`finalize_mode=""`);
* если исследование остановлено до ответа, но evidence накоплено, ответ
  формирует существующий LLM (`llm.generate`, без tools) по уже собранным
  результатам; остановка по лимитам исследования этому НЕ мешает;
* недоступен финальный LLM-вызов/пустой ответ → детерминированный
  структурный partial из tool-результатов (подтверждённое/отказы/
  непроверенное/provenance/причина остановки); саркастичная заглушка при
  наличии данных не публикуется;
* `retryable=false` терминален для маршрута: идентичный вызов не повторяется
  (дедуп), а разные вызовы к тому же структурно недоступному маршруту
  (host/provider из результата) получают честный `denied` без диспетча.

Раунд 10.20 (БЛОК 1, ADR-1020-6 п.2, T-1887): цикл НЕ меняется — сигнал
режима доставки «Летописца» несёт сам `ctx` (поле ``ToolContext.lore_compiled``,
ставится инструментом compile_lore_story и читается DirectChat после возврата).
`chat_with_tools` лишь проносит ctx в `router.dispatch(..., ctx)`.

Раунд 10.20 (БЛОК 7.1, ADR-1020-7 §1, T-1919): graceful degradation —
исчерпание раундов и `LLMError` на `round_index > 0` больше НЕ роняют ответ
в тишину+🗿. При накопленном evidence ответ формирует финальная фаза §G
(существующий LLM/Writer либо детерминированный partial); прежний частичный
текст/саркастичная заглушка `TOOL_LOOP_FALLBACK_PHRASE` остаются только
когда данных нет вовсе. Провайдер-reject на `round_index == 0` (plain-фолбэк,
FR-15) и `NoApiKeyForChat` — без изменений; пустой финал (нет tool_calls и
нет текста) — прежний `LLMBadResponseError` (FR-14/65.1, сохраняем контракт 🗿).
"""
import copy
import hashlib
import json
import logging
import re
import time

from dataclasses import dataclass
from urllib.parse import urlsplit

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

# ── SMART-EXECUTION-RELIABILITY-01 (owner 2026-11-14 §B1) ───────────────────
# Фиксированных пределов исследования больше нет: 4 раунда / 2 вызова за
# раунд / 6 суммарных / 2 одинаковых / 4 «платных» были продуктовыми
# потолками и обрывали полезное исследование. Завершение — по прогрессу:
# финальный ответ модели, отсутствие новых исполнений (`no_progress`),
# подтверждённый технический предел, отмена, safety-гвард. Явная
# операторская политика (`MCA_TOOL_MAX_*`) действует ТОЛЬКО при effective
# `flags.budgets_enabled=true`; `0` = политика не задана. Аварийный fuse —
# `MCA_TOOL_CHAIN_TIMEOUT_SECONDS>0` (тоже operator-declared; 0 = нет).

#: Сколько раундов подряд без единого нового исполнения считаются
#: отсутствием прогресса (§B4 п.2: «дальнейшие вызовы не дают новых данных»).
#: Это НЕ квота объёма: раунд с новыми вызовами всегда прогресс.
_NO_PROGRESS_ROUNDS = 2

# Метка «платного»/внешнего вызова (ADR-1026-15 D3). `worker_budget.image_calls`
# внутри `generate_image` НЕ дублируется. Free/local: memory/dig/history/health.
# MCA-19 (ADR-1028-19 §8.6): recognize_image — метричный (vision-вызов);
# cache_hit НЕ тратит vision-токены (D20).
# MCA-20 (ADR-1028-20 §7.5, round 10.44): fact_check — метричный (8→9);
# cache_hit вердикта — 0 LLM-токенов (D12).
METERED_TOOLS = frozenset({
    "execute_web_search", "fetch_article", "summarize_video", "download_media",
    "compile_lore_story", "generate_image", "edit_image", "transcribe_video",
    "recognize_image", "fact_check",
    # EVOL-SRC-READER (W6): инструмент делает сетевую работу (внешние
    # source-эндпоинты), поэтому «метрированный» по факту характера вызова.
    "read_source_code",
})

#: ER-08 (решение владельца 02.11.2026): read-only проверка фактов — счётчик
#: `metered_calls` есть счётчик ИНСТРУМЕНТОВ, а не долларов. Поиск, чтение
#: статьи и фактчек обязаны доезжать до ответа; ограничивать их «финансовой
#: экономией» в счётчике платных операций запрещено. Исследование держат
#: структурированный дедуп/retry-политика, реальные квоты и перегрузка
#: провайдера (tool_router/quota). Счётчики metered/cost — наблюдательные
#: оси (SMART-EXECUTION-RELIABILITY-01 §B1 «Metered calls»).
METERED_EVIDENCE_READ_ONLY = frozenset({
    "execute_web_search", "fetch_article", "fact_check",
    # EVOL-SRC-READER (W6): чтение исходника — такая же read-only проверка
    # (HTTP к source-эндпоинту, 0 LLM-токенов на само чтение): «денежный»
    # счётчик её не режет, anti-loop гварды и SOURCE_READ_MAX_REQUESTS
    # остаются (ER-08).
    "read_source_code",
})


def cost_limited_tool(name: str) -> bool:
    """Попадает ли вызов под «денежный» счётчик платных операций.

    ``metered`` (поле envelope/MCA-20) остаётся фактом о характере вызова;
    лимит применяется только к операциям, которые тратят деньги на
    производство результата (медиа/генерация/длинные media-конвейеры).
    Read-only проверка фактов НЕ режется этим счётчиком (ER-08)."""
    key = str(name or "")
    return key in METERED_TOOLS and key not in METERED_EVIDENCE_READ_ONLY

# Причины мягкой деградации. ``chain_*`` — срабатывание ЯВНОЙ операторской
# политики (или аварийного fuse) при budgets ON; ``no_progress`` — раунды без
# новых исполнений (§B4 п.2); ``round_limit``/``llm_error`` — прежние ветки
# (``round_limit`` больше НЕ производится: лимита раундов нет).
CHAIN_TIMEOUT_REASON = "chain_timeout"
CHAIN_CALL_LIMIT_REASON = "chain_call_limit"
CHAIN_COST_LIMIT_REASON = "chain_cost_limit"
NO_PROGRESS_REASON = "no_progress"

# ── MCA-23 фаза 2 (§17/§39): multi-tool DAG плана ───────────────────────────
# План строит ResponsePlanner (services/response_extent, 0 LLM); здесь —
# исполнение ПОВЕРХ существующего цикла (НЕ второй агент): все валидные шаги
# в топологическом порядке через существующий router.dispatch + ToolResult
# envelope; затем ОДИН модельный контур (Stage-1 видит результаты блоком
# <tool_plan_results> и синтезирует; может вызвать дополнительные tools).
# Обычные сценарии (micro/chat/один tool) идут прежним путём: tool_plan=None
# → планирование не активируется.
# SMART-EXECUTION-RELIABILITY-01 §B1: нормализованный план больше НЕ
# обрезается (было `PLAN_MAX_STEPS=6`); количество шагов ограничивает только
# сам план и явная операторская политика при budgets ON. Re-plan в этой фазе
# не выполняется — второго планировочного цикла нет.

# §18-I: tools, доставляющие медиа сами (файл уходит пользователю из тулa,
# Writer-регенерация результата бесполезна). Статусы — только канонические.
# ASAP5 §20: edit_image доставляет отредактированный исходник сам.
MEDIA_DELIVERY_TOOLS = frozenset(
    {"download_media", "generate_image", "edit_image"})

# ── ASAP5 §19 (CONTRADICTION, root-cause fix): синхронизация заявления ──────
# возможностей с фактическим результатом. `<capability_notice>` инжектится в
# контекст Writer'а ДО исполнения инструментов (состояние реестра на момент
# планирования), при этом сами инструменты остаются анонсированы и могут
# успешно выполниться позже в этом же ходе. Устаревшая инструкция «объясни
# отказ» рядом с подтверждённой отправкой — наблюдаемый источник
# production-противоречия «не умею рисовать» → изображение отправлено. После
# фактического успеха media-инструмента устаревшие notice этой capability
# ВЫВЕТРИВАЮТСЯ из модельного контекста (deepcopy — оригинал не тронут):
# ToolResult и заявление возможностей больше не противоречат друг другу.
_CLAIM_TOOL_CAPABILITY: dict[str, str] = {
    "generate_image": "image_generation",
    "edit_image": "image_edit",
}


def _strip_stale_capability_notices(payload_messages: list, capability_id: str
                                    ) -> int:
    """Убрать `<capability_notice … capability="X">` из user-сообщений
    payload'а (in-place, копия цикла). Возвращает число удалённых блоков.
    Никогда не бросает."""
    if not capability_id:
        return 0
    import re as _re
    pattern = _re.compile(
        r"<capability_notice\b[^>]*capability=\"%s\"[^>]*>.*?"
        r"</capability_notice>" % _re.escape(capability_id),
        _re.DOTALL)
    removed = 0
    try:
        for msg in payload_messages or ():
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, str) or "<capability_notice" not in \
                    content:
                continue
            new_content, n = pattern.subn("", content)
            if n:
                msg["content"] = new_content
                removed += n
    except Exception:      # pragma: no cover - защитная ветка
        return removed
    return removed


def _sync_claim_with_outcome(payload_messages: list, tool_name: str,
                             info) -> int:
    """После УСПЕШНОГО media-инструмента выветрить устаревшие
    capability-notice его capability из контекста (§19). Не-успех → 0.

    COR-03: успех определяется СТРУКТУРНЫМ контрактом результата — статусом
    классификации/envelope (``tool_result.classify_output``/legacy-derivat),
    тем же полем, что идёт в ``tool_results``, а НЕ поиском текстовых
    фрагментов: случайное совпадение подстроки в тексте ошибки/сообщения не
    трактуется как успех; ``delivery_unknown``/empty/error и битый info —
    консервативно (notice остаётся — уведомление не удаляется без
    подтверждённого результата)."""
    capability_id = _CLAIM_TOOL_CAPABILITY.get(str(tool_name or ""))
    if not capability_id or not isinstance(info, dict):
        return 0
    status = str(info.get("status") or "").strip().lower()
    if status != tool_result.STATUS_OK:
        return 0
    return _strip_stale_capability_notices(payload_messages, capability_id)

# Саркастичная заглушка деградации (код-константа; каталог-Δ = 0). Показывается
# только когда все раунды/поздние ошибки «съели» ответ, а частичного текста нет.
TOOL_LOOP_FALLBACK_PHRASE = (
    "Чет долго думал, аж перегрелся — и всё равно ни к чему не пришёл. "
    "Спроси проще, что ли.")


# ── SMART-EXECUTION-RELIABILITY-01 §G: финальная фаза исследования ──────────
#: Шаг существующего LLM-клиента для финального вызова (наблюдаемость; tools
#: не передаются).
FINALIZE_STEP = "finalize"

#: Причина структурного отказа «маршрут уже терминально недоступен».
ROUTE_TERMINAL_REASON = "route_terminal"

#: Закрытый набор структурных кодов, означающих недоступность МАРШРУТА
#: (провайдер/хост), а не конкретного ресурса: повтор с другими аргументами к
#: тому же маршруту без изменения условий бессмыслен и не диспетчится
#: (owner §G5). Ошибки конкретного ресурса (`source_missing`, `not_found`,
#: `invalid_url`, `unsupported`, `path_denied`, `parse_error`) сюда НЕ входят:
#: другой путь/файл на том же хосте может быть доступен.
ROUTE_TERMINAL_CODES = frozenset({
    "destination_blocked", "metadata_endpoint_blocked", "resolve_failed",
    "egress_guard_unavailable", "auth_failed", "provider_unavailable",
    "provider_unconfigured", "provider_stalled", "source_unavailable",
    "extract_failed", "disabled", "unknown_tool",
})

#: Инструменты с единственным провайдером: маршрут = сам инструмент (payload
#: не несёт host/provider).
ROUTE_SINGLE_PROVIDER_TOOLS = frozenset({"execute_web_search", "fact_check"})

#: Финальная LLM-инструкция (EVOL-018: объявлена в `prompt_registry`).
TOOL_FINALIZE_PROMPT = (
    "Заверши инструментальное исследование по уже собранным данным.\n"
    "Правила финального ответа:\n"
    "- опирайся на исходный запрос и результаты инструментов в этом диалоге; "
    "не выдумывай факты, которых в них нет;\n"
    "- подтверждённое (есть результат инструмента) отделяй от предположений и "
    "выводов;\n"
    "- назови источники или инструменты, которые отказали или не дали данных, "
    "и какие области остались непроверенными;\n"
    "- дай максимально содержательный ответ по доступным данным; если данных "
    "для ответа недостаточно, назови конкретную техническую причину;\n"
    "- не заявляй, что что-то прочитано или проверено, без подтверждения в "
    "результатах инструментов;\n"
    "- не вызывай инструменты и не предлагай пользователю самому искать "
    "данные, если они уже собраны;\n"
    "- ответь на языке исходного запроса."
)

#: Человекочитаемая причина остановки для финальной фазы (машинные коды
#: остаются в `reason`/телеметрии; это не анализ пользовательского текста).
_STOP_REASON_TEXT = {
    CHAIN_TIMEOUT_REASON: "остановлено по техническому предохранителю времени",
    CHAIN_CALL_LIMIT_REASON: "достигнут явный лимит вызовов, заданный оператором",
    CHAIN_COST_LIMIT_REASON: "достигнут явный лимит платных вызовов оператора",
    NO_PROGRESS_REASON: "новые данные перестали поступать",
    "llm_error": "провайдер модели прервал исследование технической ошибкой",
    ROUTE_TERMINAL_REASON: "маршрут источника терминально недоступен",
    "loop_exhausted": "исследование остановлено без новых данных",
}

#: Поля структурного payload'а, которые безопасно показывать как provenance
#: в детерминированном partial (R17-safe: без URL с секретами/текстов ответа).
_PARTIAL_PROVENANCE_KEYS = ("provider", "host", "commit", "path",
                            "line_range", "verified_url", "source_id")


def _stop_reason_text(reason: str) -> str:
    """Человекочитаемая причина остановки (неизвестный код → сам код)."""
    key = str(reason or "")
    return _STOP_REASON_TEXT.get(key) or key or "причина не зафиксирована"



class ToolLoopResult(str):
    """Финальный текст tool-цикла + телеметрия (ADR-1020-7 §1).

    ЯВЛЯЕТСЯ ``str`` → downstream `str(raw).strip()`,
    `send_chunked_reply`/`remember_bot_reply` работают БЕЗ правок.

    * ``rounds_used`` — сколько LLM-раундов реально израсходовано;
    * ``degraded`` — ответ получен деградацией (не штатный финал);
    * ``reason`` — ``"ok" | "round_limit" | "llm_error"``;
    * ``finalize_mode`` — чем сформирован деградировавший ответ (§G):
      ``""`` (штатный финал), ``"llm"`` (финальный LLM по evidence),
      ``"structured_partial"`` (детерминированный partial),
      ``"partial_text"`` (последний текст модели без данных) или
      ``"fallback_phrase"`` (заглушка без данных);
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
                tool_trace=None, tool_context=None, tool_results=None,
                sent_body=None, finalize_mode=""):
        obj = super().__new__(cls, str(text or ""))
        obj.rounds_used = int(rounds_used)
        obj.degraded = bool(degraded)
        obj.reason = str(reason or "ok")
        obj.finalize_mode = str(finalize_mode or "")
        obj.tool_trace = list(tool_trace) if tool_trace else []
        obj.tool_context = str(tool_context or "")
        obj.tool_results = list(tool_results) if tool_results else []
        #: UR-F шаг 1 (delivery snapshot, Q1): фактически отправленный body
        #: ФИНАЛЬНОГО ответообразующего раунда (только in-process); None —
        #: доставка не доказана. Дополнительные раунды второй снимок не дают.
        obj.sent_body = sent_body if isinstance(sent_body, dict) else None
        return obj


def _log_degraded(reason: str, rounds_used: int, tool_trace: list,
                  text: str, *, limits=None, finalize_mode: str = "") -> None:
    """R17: только причина/числа/длины/имена тулов — без текстов и аргументов."""
    tools = ",".join(
        sorted({str(entry.get("tool") or "") for entry in tool_trace
                if entry.get("tool")})) or "-"
    logger.warning(
        "[tools] degraded | reason=%s | rounds_used=%d | calls=%d | "
        "budgets_on=%s | tools=%s | partial_chars=%d | finalize=%s",
        reason, int(rounds_used), len(tool_trace or ()),
        (getattr(limits, "budgets_enabled", True) if limits is not None
         else "unknown"), tools, len(text or ""),
        finalize_mode or "-")


def _chain_limits_enabled() -> bool:
    """env-only kill-switch ``TOOL_CHAIN_LIMITS_ENABLED`` (A2; default ON).

    OFF → явная операторская политика объёма (cap/расходы/same-call) НЕ
    применяется. Safety/дедуп/точные отказы от него не зависят, envelope
    остаётся out-of-band. При effective budgets OFF политика не действует
    независимо от этого флага (OFF нельзя вернуть внутренним переключателем)."""
    return bool(getattr(settings, "TOOL_CHAIN_LIMITS_ENABLED", True))


def _int_setting(name: str, default: int = 0) -> int:
    """Явная операторская политика: ``0``/отсутствие = политика не задана."""
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else 0


def _max_total_calls() -> int:
    """``MCA_TOOL_MAX_TOTAL_CALLS`` (0 = политика не задана, cap отсутствует)."""
    return _int_setting("MCA_TOOL_MAX_TOTAL_CALLS")


def _max_metered_calls() -> int:
    """``MCA_TOOL_MAX_METERED_CALLS`` (0 = политика не задана)."""
    return _int_setting("MCA_TOOL_MAX_METERED_CALLS")


def _max_same_call() -> int:
    """``MCA_TOOL_MAX_SAME_CALL`` (0 = политика не задана: дедуп по условиям)."""
    return _int_setting("MCA_TOOL_MAX_SAME_CALL")


def _chain_fuse_seconds() -> float:
    """Аварийный операторский fuse (``MCA_TOOL_CHAIN_TIMEOUT_SECONDS``).

    ``0`` (заводское значение) = fuse не задан: универсального продуктового
    дедлайна исследования нет. ``>0`` — явная техническая страховка
    оператора: проверяется на границах раундов (in-flight не отменяется),
    накопленные результаты сохраняются, причина остановки честная."""
    try:
        value = float(getattr(settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS", 0.0)
                      or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value if value > 0 else 0.0


def _chain_timeout_seconds() -> float:
    """Совместимое имя: секунды аварийного fuse (``0`` = fuse выключен).

    Используется историческими потребителями (история-сегменты, оркестратор);
    это НЕ продуктовый дедлайн исследования."""
    return _chain_fuse_seconds()


@dataclass(frozen=True)
class ChainLimits:
    """Эффективная политика исполнения цепочки (одна точка для всех путей).

    ``budgets_enabled`` — master `flags.budgets_enabled` (effective, chat→
    global→factory); ``kill_switch`` — env ``TOOL_CHAIN_LIMITS_ENABLED``.
    Объёмные потолки применяются только при ``enforce``; fuse — независимая
    техническая страховка оператора (``0`` = нет)."""

    budgets_enabled: bool = True
    kill_switch: bool = True
    max_total_calls: int = 0
    max_metered_calls: int = 0
    max_same_call: int = 0
    fuse_seconds: float = 0.0

    @property
    def enforce(self) -> bool:
        """Применяется ли явная операторская политика объёма."""
        return bool(self.budgets_enabled and self.kill_switch)

    def as_meta(self) -> dict:
        """R17-safe наблюдаемые оси политики (для chain_meta/логов)."""
        return {
            "budgets_enabled": bool(self.budgets_enabled),
            "limits_enforced": bool(self.enforce),
            "max_total_calls": int(self.max_total_calls),
            "max_metered_calls": int(self.max_metered_calls),
            "max_same_call": int(self.max_same_call),
            "fuse_seconds": float(self.fuse_seconds),
        }


def resolve_chain_limits(*, budgets_enabled: bool | None = None) -> ChainLimits:
    """Собрать политику. ``budgets_enabled=None`` — достоверного значения нет
    (вызывающий не резолвил): считаем бюджеты включёнными, но объёмных квот
    нет по заводским значениям ``MCA_TOOL_MAX_*=0``; fuse тоже 0."""
    budgets_on = True if budgets_enabled is None else bool(budgets_enabled)
    return ChainLimits(
        budgets_enabled=budgets_on,
        kill_switch=_chain_limits_enabled(),
        max_total_calls=_max_total_calls(),
        max_metered_calls=_max_metered_calls(),
        max_same_call=_max_same_call(),
        fuse_seconds=_chain_fuse_seconds())


async def _resolve_chain_limits(chat_id: int | None) -> ChainLimits:
    """Effective-политика для конкретного чата (никогда не бросает).

    Единственная точка чтения master-рубильника в tool-loop: ошибка резолва
    не превращается в enforcement — бюджеты считаются выключенными."""
    from services import budget_gate
    try:
        budgets_on = bool(await budget_gate.budgets_enabled(chat_id))
    except Exception:       # pragma: no cover - защитная ветка
        logger.warning("[tools] budget gate resolve failed — enforcement off | "
                       "chat=%s", chat_id, exc_info=True)
        budgets_on = False
    return resolve_chain_limits(budgets_enabled=budgets_on)


def _reuse_reason(name: str, fp: str, *, same_calls: dict,
                  last_by_fp: dict, last_info_by_fp: dict,
                  limits: ChainLimits, guard_on: bool = True) -> str:
    """Причина НЕ диспетчить повтор ('' = исполняем).

    * ``side_effect`` — неидемпотентная операция уже дала ok/delivery_unknown:
      слепой повтор запрещён (safety/idempotency, не бюджет; K2-gated);
    * ``same_call`` — явная операторская политика ``MCA_TOOL_MAX_SAME_CALL>0``
      при budgets ON;
    * ``terminal_repeat`` — та же операция уже вернула терминальный
      (``retryable=false``) отказ: повтор без изменения условий запрещён;
    * ``retry_exhausted`` — retryable-отказ повторился
      ``MCA_TOOL_TRANSIENT_RETRIES_MAX`` раз: дальше без изменения условий
      повтор бессмысленен (политика ретраев, а не квота объёма).
    """
    info = last_info_by_fp.get(fp)
    if not isinstance(info, dict):
        return ""
    attempts = int(same_calls.get(fp, 0) or 0)
    if limits.enforce and limits.max_same_call > 0 \
            and attempts >= limits.max_same_call:
        return "same_call"
    status = str(info.get("status") or "")
    if not info.get("retryable"):
        if (guard_on and not tool_result.is_idempotent(name)
                and status in (tool_result.STATUS_OK,
                               tool_result.STATUS_DELIVERY_UNKNOWN)):
            return "side_effect"
        return "terminal_repeat"
    if attempts >= tool_result.transient_retries_max() + 1:
        return "retry_exhausted"
    return ""


def _volume_skip(limits: ChainLimits, *, total_calls: int, cost_calls: int,
                 cost_limited: bool) -> tuple[str, str, int | None]:
    """Явная операторская политика объёма (только при ``limits.enforce``).

    → ``(reason, limit_kind, limit_value)``; пустая причина = не ограничено."""
    if not limits.enforce:
        return "", "", None
    if limits.max_total_calls and total_calls >= limits.max_total_calls:
        return (CHAIN_CALL_LIMIT_REASON, "tool_calls", total_calls)
    if (cost_limited and limits.max_metered_calls
            and cost_calls >= limits.max_metered_calls):
        return (CHAIN_COST_LIMIT_REASON, "tool_metered_calls", cost_calls)
    return "", "", None


def _denied_result_content(name: str, reason: str, limit: dict | None) -> str:
    """Модельно-видимый структурный отказ (валидная последовательность + смысл).

    JSON-конверт распознаётся существующим ``tool_result.classify_output``
    (``status:denied`` → канонический статус ``denied``); модель видит
    честную причину вместо потерянного ``tool_call_id``."""
    payload: dict = {
        "status": "denied",
        "tool": str(name or ""),
        "reason": str(reason or "denied"),
        "note": "вызов не исполнен: ограничение политики исполнения",
    }
    if isinstance(limit, dict) and limit:
        payload["limit"] = limit
    return json.dumps(payload, ensure_ascii=False)


# ── SMART-EXECUTION-RELIABILITY-01 §G: маршрут/финализация ──────────────────

def _url_host(value) -> str:
    """hostname из структурного URL-поля (никогда не бросает)."""
    try:
        return (urlsplit(str(value or "")).hostname or "").strip().lower()
    except Exception:       # pragma: no cover - защитная ветка
        return ""


def _route_host_from_info(info) -> str:
    """Маршрут из структурного payload результата (host → url.host → provider)."""
    data = info.get("data") if isinstance(info, dict) else None
    if not isinstance(data, dict):
        return ""
    host = str(data.get("host") or "").strip().lower()
    if host:
        return host
    host = _url_host(data.get("url"))
    if host:
        return host
    return str(data.get("provider") or "").strip().lower()


def _route_key(name: str, *, info=None, arguments=None) -> str:
    """Идентичность МАРШРУТА вызова: ``tool|host`` ('' — маршрут неизвестен).

    Host берётся из структурного результата, иначе из аргумента ``url``;
    для инструментов с единственным провайдером маршрут = сам инструмент.
    Неизвестный маршрут НЕ подавляется (иначе можно заблокировать
    альтернативный источник, например локальный snapshot после GitHub-сбоя)."""
    host = _route_host_from_info(info)
    if not host and isinstance(arguments, dict):
        host = _url_host(arguments.get("url"))
    if not host and str(name or "") in ROUTE_SINGLE_PROVIDER_TOOLS:
        host = "-"
    return f"{name}|{host}" if host else ""


def _terminal_route_of(name: str, info) -> str:
    """Маршрут терминально недоступен по СТРУКТУРНОМУ коду ('' = нет).

    Ошибка ресурса (`source_missing`/`not_found`/`invalid_url`) маршрут не
    закрывает: другой путь на том же хосте может быть доступен."""
    if not isinstance(info, dict):
        return ""
    status = str(info.get("status") or "")
    if status not in (tool_result.STATUS_ERROR, tool_result.STATUS_TIMEOUT,
                      tool_result.STATUS_DENIED):
        return ""
    code = str(info.get("error_code") or "").strip()
    if code not in ROUTE_TERMINAL_CODES:
        return ""
    return _route_key(name, info=info)


def _route_terminal_content(name: str, route: str, code: str) -> str:
    """Модельно-видимый отказ «маршрут уже недоступен» (id не теряется)."""
    return json.dumps({
        "status": "denied",
        "tool": str(name or ""),
        "reason": ROUTE_TERMINAL_REASON,
        "route": str(route or ""),
        "code": str(code or ""),
        "note": ("этот маршрут уже вернул терминальный инфраструктурный отказ; "
                 "повтор без изменения условий не выполняется. Используй "
                 "альтернативный источник, если он доступен, иначе опирайся "
                 "на уже собранные данные."),
    }, ensure_ascii=False)


def _route_suppression(name: str, arguments, terminal_routes) -> tuple[str, str]:
    """``(route, code)`` если маршрут уже терминально недоступен, иначе ``("", "")``.

    Идентичные аргументы обрабатываются дедупом ``_reuse_reason``; здесь —
    ДРУГИЕ аргументы к тому же структурно недоступному маршруту."""
    route = _route_key(name, arguments=arguments)
    if route and isinstance(terminal_routes, dict) and route in terminal_routes:
        return route, str(terminal_routes.get(route) or "")
    return "", ""



def _evidence_inventory(tool_results, outputs) -> list[dict]:
    """Структурный инвентарь evidence прогона для финальной фазы.

    Собирается ИЗ envelope-журнала (статусы/коды/provenance) и параллельного
    списка фактических выводов инструментов (тот же порядок записи)."""
    results = list(tool_results or ())
    texts = list(outputs or ())
    items: list[dict] = []
    for index in range(min(len(results), len(texts))):
        env = results[index]
        if not isinstance(env, dict):
            continue
        data = env.get("data") if isinstance(env.get("data"), dict) else {}
        provenance: dict = {}
        for key in _PARTIAL_PROVENANCE_KEYS:
            value = data.get(key)
            if value not in (None, "", [], {}):
                provenance[key] = value
        items.append({
            "tool": str(env.get("tool") or ""),
            "status": str(env.get("status") or ""),
            "error_code": str(env.get("error_code") or ""),
            "retryable": bool(env.get("retryable")),
            "partial": bool(env.get("partial")),
            "duplicate": bool(env.get("duplicate")),
            "attempt": int(env.get("attempt") or 0),
            "evidence_refs": [str(ref) for ref in
                              (env.get("evidence_refs") or ())],
            "provenance": provenance,
            "output": str(texts[index] or ""),
            "out_chars": int(env.get("out_chars") or 0),
        })
    return items


def _usable_evidence(items) -> list[dict]:
    """Результаты с данными: ok/empty либо явная частичность."""
    return [item for item in (items or ())
            if item.get("status") in (tool_result.STATUS_OK,
                                      tool_result.STATUS_EMPTY)
            or item.get("partial")]


def _failed_evidence(items) -> list[dict]:
    """Структурные отказы (ошибки/таймауты/отказы policy/пустые без partial)."""
    usable_ids = {id(item) for item in _usable_evidence(items)}
    return [item for item in (items or ()) if id(item) not in usable_ids]


def _failure_lines(items) -> list[str]:
    """Компактные строки отказов (tool + структурный код/статус)."""
    lines: list[str] = []
    seen: set = set()
    for item in items or ():
        key = (item.get("tool"), item.get("status"), item.get("error_code"))
        if key in seen:
            continue
        seen.add(key)
        code = str(item.get("error_code") or item.get("status") or "error")
        suffix = ", повторно" if item.get("duplicate") else ""
        lines.append(f"- {item.get('tool') or 'tool'}: {code}{suffix}")
    return lines


def _unchecked_text(items, stop_reason: str) -> str:
    """Непроверенные области по структурным отказам + причина остановки."""
    failed = _failed_evidence(items)
    if failed:
        names = sorted({str(item.get("tool") or "tool")
                        for item in failed})
        return ("не получены данные от: " + ", ".join(names)
                + f"; исследование остановлено: {_stop_reason_text(stop_reason)}")
    return ("явных отказов источников нет; полнота ограничена причиной "
            f"остановки: {_stop_reason_text(stop_reason)}")


def _excerpt(text, limit: int) -> str:
    """Короткая выдержка для детерминированного partial (не пустая)."""
    value = " ".join(str(text or "").split())
    if limit and len(value) > limit:
        return value[:max(1, int(limit))].rstrip() + "…"
    return value


def _last_user_text(messages) -> str:
    """Исходный запрос: последнее user-сообщение входа (без служебных блоков)."""
    for message in reversed(list(messages or ())):
        try:
            if message.get("role") == "user" \
                    and isinstance(message.get("content"), str):
                return str(message["content"])
        except Exception:
            continue
    return ""


def _finalize_directive(stop_reason: str, items) -> str:
    """User-сообщение финальной фазы: инструкция + структурный контекст."""
    usable = _usable_evidence(items)
    failed = _failed_evidence(items)
    lines = [TOOL_FINALIZE_PROMPT, "", "<finalize_context>",
             f"Причина остановки исследования: "
             f"{_stop_reason_text(stop_reason)} ({stop_reason}).",
             f"Результатов с данными: {len(usable)}; "
             f"отказов/пустых: {len(failed)}."]
    if failed:
        lines.append("Отказавшие источники/инструменты:")
        lines.extend(_failure_lines(failed))
    lines.append("Непроверенные области: " + _unchecked_text(items, stop_reason))
    lines.append("</finalize_context>")
    return "\n".join(lines)


def _structured_partial(stop_reason: str, items, messages,
                        finalize_error: str) -> str:
    """Детерминированный безопасный partial из структурированных фактов.

    Используется только когда финальный LLM-вызов недоступен/пуст: ответ
    строится по реальным tool-результатам, честно отделяет отказы и
    непроверенное, не подменяется саркастичной заглушкой."""
    try:
        from services.system2_handoff import redact_secrets
    except Exception:       # pragma: no cover - защитная ветка
        def redact_secrets(value):      # type: ignore
            return value

    request = _excerpt(_last_user_text(messages), 500)
    usable = _usable_evidence(items)
    failed = _failed_evidence(items)
    lines = ["Исследование остановлено: "
             f"{_stop_reason_text(stop_reason)} ({stop_reason}).",
             "Это частичный результат: финальный LLM-вызов недоступен "
             f"({finalize_error or 'error'}), ниже собраны только фактически "
             "полученные данные."]
    if request:
        lines.extend(["", f"Запрос: {redact_secrets(request)}"])
    if usable:
        lines.extend(["", "Подтверждённые данные (результаты инструментов):"])
        for item in usable:
            head = (f"- {item.get('tool')}: {item.get('status')}"
                    + (" (частично)" if item.get("partial") else "")
                    + f", {item.get('out_chars')} символов")
            lines.append(head)
            provenance = item.get("provenance") or {}
            if provenance:
                rendered = "; ".join(f"{key}={value}"
                                     for key, value in provenance.items())
                lines.append(f"  provenance: {redact_secrets(rendered)}")
            refs = item.get("evidence_refs") or []
            if refs:
                lines.append("  источники: " + ", ".join(refs))
            body = _excerpt(item.get("output"), 400)
            if body:
                lines.append("  " + redact_secrets(body))
    failed_lines = _failure_lines(failed)
    if failed_lines:
        lines.extend(["", "Отказы источников/инструментов:"])
        lines.extend(failed_lines)
    lines.extend(["", "Непроверено: " + _unchecked_text(items, stop_reason),
                  "", "Полные результаты вызовов сохранены в журнале прогона "
                  f"({len(items)} вызовов)."])
    return "\n".join(lines)


async def _finalize_from_evidence(llm, payload_messages, *, stop_reason,
                                  items, temperature, chat_id, module,
                                  correlation_id, fallback_payload_adapter,
                                  max_output_tokens) -> tuple[str, str]:
    """Финальный LLM-вызов по накопленным данным (существующий Writer-путь).

    → ``(text, error)``: пустой ``text`` = вызов недоступен/пуст, вызывающий
    строит детерминированный partial. Инструменты не передаются."""
    messages = copy.deepcopy(payload_messages)
    messages.append({"role": "user",
                     "content": _finalize_directive(stop_reason, items)})
    try:
        raw = await llm.generate(
            messages, temperature=temperature, chat_id=chat_id,
            module=module, step=FINALIZE_STEP, correlation_id=correlation_id,
            fallback_payload_adapter=fallback_payload_adapter,
            max_output_tokens=max_output_tokens)
    except NoApiKeyForChat as exc:
        logger.warning("[tools] finalize llm unavailable | reason=%s | "
                       "error=%s", stop_reason, type(exc).__name__)
        return "", type(exc).__name__
    except Exception as exc:        # LLMError/транспорт/двойник без Writer
        logger.warning("[tools] finalize llm failed | reason=%s | error=%s",
                       stop_reason, type(exc).__name__)
        return "", type(exc).__name__
    text = strip_reasoning_tags(str(raw or "")).strip()
    if not text:
        logger.warning("[tools] finalize llm empty | reason=%s", stop_reason)
        return "", "empty"
    return text, ""



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
    """Валидация плана (§38; никогда не бросает).

    * шаг = dict с непустым ``tool``; неизвестный/неанонсированный tool →
      шаг ВЫБРАСЫВАЕТСЯ (не исполняется);
    * ``arguments`` — dict (иначе {});
    * ``depends_on`` — только id валидных шагов (неизвестные отбрасываются);
    * ``failure_policy`` — ``required`` | ``optional`` (иное → ``optional``);
    * SMART-EXECUTION-RELIABILITY-01 §B1: нормализованный план НЕ обрезается
      по числу шагов (прежний ``PLAN_MAX_STEPS=6`` удалён); каждый валидный
      шаг исполняется, объём ограничивает явная политика при budgets ON."""
    if not isinstance(raw_plan, (list, tuple)):
        return []
    seen: set = set()
    steps: list = []
    for item in list(raw_plan):
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


# ── MCA-11 (ADR-1028-13 D2): env-only числа политики (см. resolve_chain_limits).
# Заводские значения `MCA_TOOL_MAX_*=0` = политика не задана; enforcement —
# только при effective budgets ON (SMART-EXECUTION-RELIABILITY-01 §A/B).
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


def _record(ctx, tool_results: list, envelope: dict,
            tool_call_id: str | None = None) -> None:
    """Записать envelope в журнал прогона (локальный + ``ctx.tool_results``).

    ``ctx`` может быть произвольным объектом (тесты передают MagicMock/object)
    → запись в контекст best-effort, сбой не роняет цикл.
    SMART-EXECUTION-RELIABILITY-01 §B1: в КАНОНИЧЕСКИЙ envelope добавляется
    исходный ``tool_call_id`` — структурный результат каждого запрошенного
    вызова однозначно сопоставим с провайдерским сообщением (K1 OFF —
    legacy-набор ключей байт-в-байт, без аддитивного поля)."""
    if (tool_call_id and isinstance(envelope, dict)
            and tool_result.enabled()):
        envelope["tool_call_id"] = str(tool_call_id)
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

    Единая политика исполнения (SMART-EXECUTION-RELIABILITY-01 §B): все
    корректно запрошенные вызовы исполняются и получают структурный
    результат; фиксированных пределов раундов/вызовов/«платных» нет.
    Завершение: финальный ответ модели; ``no_progress`` (два раунда подряд
    без единого нового исполнения); подтверждённый технический отказ;
    отмена; явная операторская политика при effective
    ``flags.budgets_enabled=true`` (``MCA_TOOL_MAX_*``); аварийный fuse
    (``MCA_TOOL_CHAIN_TIMEOUT_SECONDS>0``). Деградация возвращает частичный
    текст либо ``TOOL_LOOP_FALLBACK_PHRASE`` (``degraded=True``), НЕ
    исключение (ADR-1020-7 §1). Провайдер-reject на 1-м раунде —
    plain-фолбэк без tools (FR-15); ``NoApiKeyForChat`` — проброс; пустой
    финал — прежний ``LLMBadResponseError`` (FR-14/65.1).

    A2 (ADR-1026-15 D1/D3): на каждый вызов строится out-of-band envelope
    (``tool_results`` + ``ctx.tool_results``); модельно-видимый канал
    (``role:"tool"`` / ``tool_context``) не меняется (гибрид D1).
    ``metered``/``usage`` — наблюдательные оси, enforcement — отдельно.

    SMART-EXECUTION-RELIABILITY-01 §G: остановка исследования до финального
    ответа (no_progress/llm_error/fuse/явная политика) не возвращает
    последний промежуточный текст или саркастичную заглушку при наличии
    данных. Ответ формирует финальная фаза: существующий LLM-клиент
    (``generate``, без tools) по накопленным результатам; недоступен —
    детерминированный структурный partial. Штатный финальный ответ модели
    повторного вызова не делает. ``ToolLoopResult.finalize_mode`` сообщает,
    чем сформирован деградировавший ответ.

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
    model-driven путь. Непустой план: ВСЕ валидные шаги исполняются ДО
    модельных раундов в топологическом порядке через существующий
    ``router.dispatch`` (ToolResult envelope); результаты — одним аддитивным
    user-блоком ``<tool_plan_results>`` в Stage-1 (синтез + limitations);
    failure_policy=optional → limitation, required → честная деградация
    (§19); ``round=0`` в trace/envelope отличает плановые шаги от
    модельных раундов. Re-plan в этой фазе не выполняется.
    """
    limits = await _resolve_chain_limits(chat_id)
    payload_messages = copy.deepcopy(messages)
    tool_trace: list[dict] = []
    tool_results: list[dict] = []
    tool_context_parts: list[str] = []
    partial_text = ""
    # Аварийный операторский fuse (0 = не задан): проверка ТОЛЬКО на
    # границах раундов/перед диспетчем — in-flight вызов не отменяется,
    # накопленные результаты не уничтожаются.
    deadline = (time.monotonic() + limits.fuse_seconds
                if limits.fuse_seconds > 0 else None)
    total_calls = 0
    metered_calls = 0
    # ER-08: отдельный счётчик «денежных» операций (лимит применяется ТОЛЬКО
    # к нему). `metered_calls` остаётся наблюдаемой осью (сколько было
    # метричных вызовов вообще), а не тормозом проверки фактов.
    cost_calls = 0
    same_calls: dict[str, int] = {}
    last_by_fp: dict[str, str] = {}
    # MCA-11 D3: последний канонический/legacy-результат по отпечатку —
    # запрет слепого повтора side effect после успеха/delivery_unknown.
    last_info_by_fp: dict[str, dict] = {}
    # §G5: маршруты, уже вернувшие терминальный инфраструктурный отказ
    # (`tool|host` → структурный код). Повтор ДРУГИХ запросов к тому же
    # недоступному маршруту не диспетчится; успешный вызов маршрут снимает.
    terminal_routes: dict[str, str] = {}
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

    # ── SMART-EXECUTION-RELIABILITY-01 §G: общие помощники финализации ─────
    def _remember_terminal(name: str, info: dict) -> None:
        """Запомнить/снять терминальный маршрут по структурному результату."""
        route = _route_key(name, info=info)
        if not route:
            return
        status = str((info or {}).get("status") or "")
        if status in (tool_result.STATUS_OK, tool_result.STATUS_EMPTY):
            terminal_routes.pop(route, None)
            return
        code = str((info or {}).get("error_code") or "")
        if code in ROUTE_TERMINAL_CODES:
            terminal_routes[route] = code
            logger.warning(
                "[tools] route terminal | tool=%s | route=%s | code=%s",
                name, route, code)

    def _deny_route(name: str, fp: str, route: str, code: str, *,
                    round_index: int, tool_call_id: str | None = None,
                    metered: bool = False) -> str:
        """Структурный отказ «маршрут уже недоступен» + envelope/trace."""
        content = _route_terminal_content(name, route, code)
        info = {"status": (tool_result.STATUS_DENIED if _contract_on()
                           else "skipped"),
                "error_code": ROUTE_TERMINAL_REASON, "error_type": "",
                "data": ({"route": route, "code": code,
                          "reason": ROUTE_TERMINAL_REASON}
                         if _contract_on() else None),
                "truncated": False, "retryable": False, "partial": False,
                "usage": {}, "evidence_refs": [],
                "external_operation_id": None}
        _record(ctx, tool_results, _envelope(
            round_index, name, fp, info, metered=metered, duplicate=False,
            attempt=same_calls.get(fp, 0), out_chars=len(content)),
            tool_call_id)
        tool_result.emit_tool_chain_events(
            tool=name, status="denied", chat_id=chat_id,
            correlation_id=correlation_id, args_fingerprint=fp,
            attempt=same_calls.get(fp, 0),
            chain_limit_code=ROUTE_TERMINAL_REASON)
        emit_agentic_event(
            "TOOL_CALL_FAILED", run_id=correlation_id, chat_id=chat_id,
            tool=name, round=round_index + 1,
            status=("denied" if _contract_on() else "skipped"),
            error_code=ROUTE_TERMINAL_REASON)
        tool_context_parts.append(content)
        tool_trace.append({"round": round_index + 1, "tool": name,
                           "ok": False, "out_chars": len(content)})
        return content

    async def _finish_degraded(reason: str, *, allow_llm: bool = True
                               ) -> "ToolLoopResult":
        """Единый финал остановленного исследования (§G2–§G4).

        Наличие данных → финальный LLM по evidence (существующий Writer-путь);
        недоступен → детерминированный partial; данных нет вовсе → прежний
        частичный текст/заглушка. Лимиты исследования сюда не применяются.
        ``allow_llm=False`` — финальный LLM уже доказанно недоступен в этом
        ходе (не делаем третью попытку), сразу строится partial."""
        items = _evidence_inventory(tool_results, tool_context_parts)
        text = ""
        mode = ""
        if items:
            finalize_error = "llm_error"
            if allow_llm:
                text, finalize_error = await _finalize_from_evidence(
                    llm, payload_messages, stop_reason=reason, items=items,
                    temperature=temperature, chat_id=chat_id, module=module,
                    correlation_id=correlation_id,
                    fallback_payload_adapter=fallback_payload_adapter,
                    max_output_tokens=max_output_tokens)
            if text:
                mode = "llm"
            else:
                text = _structured_partial(reason, items, messages,
                                           finalize_error)
                mode = "structured_partial"
        if not text:
            text = strip_reasoning_tags(partial_text)
            mode = "partial_text" if text else "fallback_phrase"
        if not text:
            text = TOOL_LOOP_FALLBACK_PHRASE
        _log_degraded(reason, llm_rounds, tool_trace, text, limits=limits,
                      finalize_mode=mode)
        return ToolLoopResult(
            text, rounds_used=llm_rounds, degraded=True, reason=reason,
            tool_trace=tool_trace,
            tool_context="\n".join(tool_context_parts),
            tool_results=tool_results, finalize_mode=mode)

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
            # (а) дедуп по нормализованным аргументам + safety-гард side
            # effects — тот же контракт, что в модельных раундах.
            cached_reason = _reuse_reason(
                name, fp, same_calls=same_calls, last_by_fp=last_by_fp,
                last_info_by_fp=last_info_by_fp, limits=limits,
                guard_on=_guard_on())
            if not cached_reason:
                # (а2) §G5: другие запросы к уже терминально недоступному
                # маршруту не диспетчатся (альтернатива/накопленные данные).
                route, route_code = _route_suppression(
                    name, arguments, terminal_routes)
                if route:
                    _deny_route(name, fp, route, route_code, round_index=-1,
                                metered=metered)
                    plan_limitations.append(
                        f"шаг {step['step_id']} не выполнен "
                        f"({ROUTE_TERMINAL_REASON})")
                    continue
                # (б) явная операторская политика объёма / аварийный fuse.
                skip_code, limit_kind, limit_value = _volume_skip(
                    limits, total_calls=total_calls, cost_calls=cost_calls,
                    cost_limited=cost_limited_tool(name))
                if deadline is not None and time.monotonic() > deadline:
                    skip_code = CHAIN_TIMEOUT_REASON
                    limit_kind = "tool_chain_deadline"
                    limit_value = None
                if skip_code:
                    # §19: partial failure не роняет run — шаг в honest
                    # limitation, остальные шаги/цикл продолжаются.
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
                if cost_limited_tool(name):
                    cost_calls += 1
                attempt = same_calls.get(fp, 0) + 1
                same_calls[fp] = attempt
                last_by_fp[fp] = output
                info = _classify(name, output, signal)
                last_info_by_fp[fp] = info
                _remember_terminal(name, info)
                # §19: успешный media-инструмент выветривает устаревший
                # capability-notice из контекста (заявление = фактический
                # результат; «не умею» после реальной отправки исключено).
                # COR-03: решение — по структурному статусу классификации.
                _sync_claim_with_outcome(payload_messages, name, info)
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
                               "ok": (True if cached_reason
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
    round_index = 0
    llm_rounds = 0
    no_progress_rounds = 0
    while True:
        # Аварийный операторский fuse: только граница раунда (in-flight не
        # отменяем; уже полученный результат не рушим).
        if (deadline is not None and round_index > 0
                and time.monotonic() > deadline):
            return await _finish_degraded(CHAIN_TIMEOUT_REASON)
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
                # UR-F шаг 1 (Q1): plain-фолбэк обязан вернуть receipt —
                # у `generate()` его нет, поэтому идём metadata-вариантом.
                _plain_meta = getattr(llm, "generate_with_metadata", None)
                try:
                    if callable(_plain_meta):
                        _plain_completion = await _plain_meta(
                            payload_messages, temperature=temperature,
                            chat_id=chat_id, module=module, step="single",
                            correlation_id=correlation_id,
                            fallback_payload_adapter=fallback_payload_adapter,
                            max_output_tokens=max_output_tokens)
                        return ToolLoopResult(
                            str(getattr(_plain_completion, "text", "") or ""),
                            rounds_used=1, tool_results=tool_results,
                            sent_body=getattr(_plain_completion, "sent_body",
                                              None))
                    plain = await llm.generate(
                        payload_messages, temperature=temperature,
                        chat_id=chat_id, module=module, step="single",
                        correlation_id=correlation_id,
                        fallback_payload_adapter=fallback_payload_adapter,
                        max_output_tokens=max_output_tokens)
                    return ToolLoopResult(plain, rounds_used=1,
                                          tool_results=tool_results)
                except NoApiKeyForChat:
                    raise
                except LLMError as plain_exc:
                    # §G4: финальный LLM недоступен, но шаги плана уже дали
                    # данные → безопасный partial; без данных — прежний проброс
                    # (не подменяем контракт ошибки провайдера).
                    if not tool_results:
                        raise
                    logger.warning(
                        "[tools] plain fallback failed with evidence | "
                        "error=%s", type(plain_exc).__name__)
                    return await _finish_degraded("llm_error",
                                                  allow_llm=False)
            # БЛОК 7.1: поздний раунд — не пробрасываем (не теряем ответ).
            return await _finish_degraded("llm_error")
        llm_rounds += 1
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
                                      rounds_used=llm_rounds,
                                      tool_trace=tool_trace,
                                      tool_context="\n".join(tool_context_parts),
                                      tool_results=tool_results,
                                      sent_body=getattr(result, "sent_body",
                                                        None))
            raise LLMBadResponseError("tool loop: empty final answer")
        # SMART-EXECUTION-RELIABILITY-01 §B1: список вызовов НЕ обрезается —
        # все корректно запрошенные вызовы исполняются и получают результат.
        tool_calls: list[LLMToolCall] = list(result.tool_calls)
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
        dispatched_this_round = 0
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
                    duplicate=False, attempt=attempt, out_chars=len(output)),
                    tc.id)
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

            # (б) дедуп по нормализованным аргументам/идентичности операции +
            # safety-гард side effects. Повтор без изменения условий не
            # диспетчится и получает прежний структурный результат; retryable
            # отказ повторяется в пределах MCA_TOOL_TRANSIENT_RETRIES_MAX.
            cached_reason = _reuse_reason(
                tc.name, fp, same_calls=same_calls, last_by_fp=last_by_fp,
                last_info_by_fp=last_info_by_fp, limits=limits,
                guard_on=_guard_on())
            if cached_reason:
                output = last_by_fp[fp]
                attempt = same_calls[fp] + 1
                same_calls[fp] = attempt
                info = dict(last_info_by_fp.get(fp)
                            or _classify(tc.name, output))
                _record(ctx, tool_results, _envelope(
                    round_index, tc.name, fp, info, metered=metered,
                    duplicate=True, attempt=attempt, out_chars=len(output)),
                    tc.id)
                payload_messages.append({"role": "tool",
                                         "tool_call_id": tc.id,
                                         "content": output})
                tool_context_parts.append(output)
                cached_ok = str(info.get("status")) in (tool_result.STATUS_OK,
                                                        tool_result.STATUS_EMPTY)
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

            # (б2) §G5: та же операция/маршрут уже терминально недоступна —
            # другие аргументы к тому же маршруту не диспетчатся.
            route, route_code = _route_suppression(
                tc.name, arguments, terminal_routes)
            if route:
                denied = _deny_route(tc.name, fp, route, route_code,
                                     round_index=round_index,
                                     tool_call_id=tc.id, metered=metered)
                payload_messages.append({"role": "tool",
                                         "tool_call_id": tc.id,
                                         "content": denied})
                continue

            # (в) явная операторская политика объёма / аварийный fuse.
            skip_code, limit_kind, limit_value = _volume_skip(
                limits, total_calls=total_calls, cost_calls=cost_calls,
                cost_limited=cost_limited_tool(tc.name))
            if deadline is not None and time.monotonic() > deadline:
                skip_code = CHAIN_TIMEOUT_REASON
                limit_kind = "tool_chain_deadline"
                limit_value = None
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
                    out_chars=0), tc.id)
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
                # A9 (D5): chain-skip (fuse/call-limit/cost-limit).
                emit_agentic_event(
                    "TOOL_CALL_FAILED", run_id=correlation_id,
                    chat_id=chat_id, tool=tc.name,
                    round=round_index + 1,
                    status=("denied" if _contract_on() else "skipped"),
                    error_code=skip_code)
                # Отказ получает СВОБОДНЫЙ tool-результат с исходным id:
                # последовательность assistant(tool_calls) → tool(each id)
                # остаётся валидной, tool_call_id не теряется (§B1).
                denied = _denied_result_content(tc.name, skip_code, limit)
                payload_messages.append({"role": "tool",
                                         "tool_call_id": tc.id,
                                         "content": denied})
                tool_context_parts.append(denied)
                tool_trace.append({"round": round_index + 1, "tool": tc.name,
                                   "ok": False, "out_chars": len(denied)})
                degrade_reason = skip_code
                limit_hit = True
                continue

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
            dispatched_this_round += 1
            # MCA-11 D1/D3: out-of-band сигнал обвязки (SafeFetcher stage/
            # delivery_unknown) — одноразово, в модельный ввод не попадает.
            signal = tool_result.take_signal(ctx)
            total_calls += 1
            if metered:
                metered_calls += 1
            if cost_limited_tool(tc.name):
                cost_calls += 1
            attempt = same_calls.get(fp, 0) + 1
            same_calls[fp] = attempt
            last_by_fp[fp] = output
            info = _classify(tc.name, output, signal)
            last_info_by_fp[fp] = info
            _remember_terminal(tc.name, info)
            # §19: успешный media-инструмент выветривает устаревший
            # capability-notice из контекста (заявление = фактический
            # результат; «не умею» после реальной отправки исключено).
            # COR-03: решение — по структурному статусу классификации.
            _sync_claim_with_outcome(payload_messages, tc.name, info)
            _record(ctx, tool_results, _envelope(
                round_index, tc.name, fp, info, metered=metered,
                duplicate=False, attempt=attempt, out_chars=len(output),
                duration_ms=duration_ms), tc.id)
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
        round_index += 1
        # §B4 п.2: раунд без единого нового исполнения — данные не прибавились.
        if dispatched_this_round:
            no_progress_rounds = 0
        else:
            no_progress_rounds += 1
            if no_progress_rounds >= _NO_PROGRESS_ROUNDS:
                degrade_reason = NO_PROGRESS_REASON
                break
    # Мягкая деградация: ответ формирует финальная фаза §G по накопленным
    # данным (а не последний промежуточный текст модели/заглушка).
    if degrade_reason:
        return await _finish_degraded(degrade_reason)
    # Недостижимо: цикл завершается только возвратом/деградацией выше.
    return await _finish_degraded("loop_exhausted")
