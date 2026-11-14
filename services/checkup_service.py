"""Epic 42 — CheckupService (Section 51.6): логи → LLM-отчёт → cleanup.
Epic 60 (64.5, T-466): db+memory → data-секция <memory_health> в user-контенте.
Epic 61 (64.5 хотфикс, D250/T-501): секция метрик НЕ теряется при переполнении
логов; escape РОВНО ОДИН раз на финальной обёртке <system_logs>.

SMART-CORRECTIVE-01 §7 (S3B-INPUT): семь видов ограничений входа больше не
смешиваются (см. блок `_InputBudget` ниже): окно журнала (свежий срез, не
запрет истории), полнота diagnostics (facts/not_checked), ФИЗИЧЕСКАЯ ёмкость
модели (`services.model_capacity`), операторские бюджеты
(`flags.budgets_enabled` → `limits.checkup_max_input_symbols`), размер порции
данных (потолки fetcher/probe), желаемый объём отчёта
(`limits.checkup_max_symbols` — только `{max_symbols}` промпта, никогда не
размер payload/исследования) и лимиты канала доставки (outbound chunking).
Сборка payload идёт по значимости фактов, сохраняет структуру строк и при
нехватке места честно сообщает, что именно опущено, и называет маршрут
дальнейшей диагностики (существующий инструмент) либо его отсутствие.
При budgets OFF искусственная
обрезка по старым лимитам символов не применяется — остаются физические,
security- и no-progress-гварды.

SELF-DIAG-01 D6 (`SD1-D6-05`, B1): сервис не меняет промпт и не пишет его
содержимое — наружу отдаётся только машинная телеметрия ФИНАЛЬНОГО system
(source/version/hash) в per-run словарь ``telemetry`` вызывающего; хендлер
кладёт её в существующий mca-событийный контур. Общего mutable-атрибута
телеметрии нет: конкурентные чекапы разных чатов не смешиваются.

SMART-CORRECTIVE-01 §8.2/§8.4 (S6-PROMPT, 14.11.2026): база чекапа
резолвится существующим реестром по порядку chat override → global →
factory (``prompt_registry.resolve_chat_speech_ex``) для пользовательской
команды; без ``chat_id`` — прежний global-резолв. Сохранённая владельцем
per-chat редакция теперь реально доходит до маршрута своего чата, а
сохранённые значения НЕ перезаписываются. Телеметрия получила additive-ключи
``prompt_layer``/``prompt_base_hash``/``prompt_base_chars``/``prompt_withheld``/
``prompt_provenance_reason`` (без текста): по ним проверяется фактическая
доставка и возможное изменение текста реестром. Смысловое различение
«чистое свежее окно журналов + активный ERROR-инцидент» и операционные
маршруты продолжения/частичного отчёта живут в wording промпта/addendum,
второго движка/регулятора мата/квот инструкций здесь нет.
"""
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass

from config.settings import settings
from services import hot_config as hot
from services.checkup_prompts import (
    CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM,
    CHECKUP_FALLBACK_NOTICE,
    CHECKUP_SYSTEM_PROMPT,
)
from services.llm_client import LLMBadResponseError, LLMClient
from services.memory_health import collect_metrics
from services.prompt_composer import speech_owner_block
from services.prompt_style_blocks import resolve_prompt_with_source
from services.summary_cleanup import cleanup_llm_text
from services.summary_xml import escape_xml_text
from services.token_counter import count_tokens

logger = logging.getLogger(__name__)

# Epic 49 (Section 57.5, D196): C0-управляющие, кроме \n (переносы логов) и
# \t; плюс DEL (0x7f). Каждый такой символ → ровно ОДИН пробел.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# ── SMART-CORRECTIVE-01 §7 (S3B-INPUT): сборка входа по значимости ─────────
# Потолки фетчера/probe (окно, порция) остаются у своих владельцев; здесь —
# только раскладка уже собранного payload по реальной ёмкости. Фиксированной
# обрезки метрик (прежние 2000) больше нет: секция метрик — такой же
# диагностический факт и участвует в общей раскладке, а не отнимает бюджет
# логов скрытой константой.

#: Признаки СУЩЕСТВЕННЫХ диагностических строк: текущие сбои, причины отказа,
#: traceback/исключения. Такие строки сохраняются первыми.
_SIGNIFICANT_LINE_MARKERS = (
    "error", "critical", "traceback", "exception", "fatal", "panic",
    "failed", "failure", "refused", "unavailable", "timeout", "denied",
)

#: Структурные строки провенанса/фактов (источник логов, состояния источников,
#: reason_code, not_checked, честные маркеры бюджета). Сохраняются первыми.
_STRUCTURED_LINE_PREFIXES = (
    "[log-source", "[checkup-input", "diagnostic_evidence",
    "[facts_budget_exceeded]", "[facts_unknown]", "not_checked=",
)

#: Строки фактов коллектора: `- logs.checkup [ok] ...` и `    key=value`.
_STRUCTURED_FACT_RE = re.compile(
    r"^\s*(?:-\s+)?[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*(?:\s+\[|[:\s=])"
    r"|^\s{2,}[a-z][a-z0-9_]*=")

#: Промежуточная значимость: предупреждения/деградации (после существенного,
#: но раньше обычного INFO-потока).
_WARNING_LINE_MARKERS = ("warning", "warn", "degraded")

#: Честная приписка о том, что свежее окно журнала не является запретом на
#: исторический запрос (п.7.1 №1 owner-источника). Добавляется только когда
#: payload реально содержит провенанс log-source И tool-loop доступен.
_HISTORY_NOTE = (
    "[checkup-input] journal_window=fresh_slice_only; окно наблюдения "
    "ограничивает только доставленный срез и не запрещает исторический "
    "запрос: существующие инструменты дают time_window (события/пробы) и "
    "cursor (продолжение выдачи); сырой текст старше окна в этом запуске "
    "повторно не читается")

#: SMART-CORRECTIVE-01 §8.2 (S6-PROMPT): ключ существующего реестра промптов.
_CHECKUP_PROMPT_KEY = "prompts.checkup_system_prompt"


async def _resolve_checkup_base_prompt(chat_id: int | None) -> tuple:
    """Базовый жанровый промпт чекапа: chat override → global → factory.

    До S6 резолвился ТОЛЬКО global-слой (`prompt_style_blocks.resolve_prompt*`),
    поэтому сохранённая владельцем per-chat редакция `prompts.checkup_system_prompt`
    не применялась на маршруте чекапа (production run A: prompt_source=global).
    Теперь при наличии ``chat_id`` (пользовательская команда) используется
    СУЩЕСТВУЮЩИЙ резолвер реестра ``prompt_registry.resolve_chat_speech_ex`` —
    тот же порядок chat → global → default, что у Direct-канала, включая
    провенанс/удержание реестра. Без ``chat_id`` (внутренний tool-loop
    ``get_bot_health``) сохраняется прежний global-резолв: per-chat слой там
    не читается и поведение не меняется.

    Возвращает ``(effective_text, source, meta)``; ``meta`` — только машинные
    коды/флаги (без текста промпта): ``prompt_layer`` — фактический слой
    (``chat|global|default``), ``prompt_withheld`` — значение из PG не стало
    эффективным слоем (действует заводская редакция), ``prompt_provenance_reason``
    — код причины. Сам сохранённый текст НЕ пишется и НЕ нормализуется сервисом.
    """
    if chat_id is None:
        effective, source = resolve_prompt_with_source(
            _CHECKUP_PROMPT_KEY, CHECKUP_SYSTEM_PROMPT)
        return effective, source, {
            "prompt_layer": source,
            "prompt_withheld": False,
            "prompt_provenance_reason": "",
        }
    try:
        from services import prompt_registry as registry
        resolved = await registry.resolve_chat_speech_ex(
            _CHECKUP_PROMPT_KEY, CHECKUP_SYSTEM_PROMPT, chat_id=int(chat_id))
    except Exception:      # pragma: no cover - резолвер не бросает
        logger.warning("[checkup] chat prompt resolver failed — global layer "
                       "| chat=%s", chat_id, exc_info=True)
        effective, source = resolve_prompt_with_source(
            _CHECKUP_PROMPT_KEY, CHECKUP_SYSTEM_PROMPT)
        return effective, source, {
            "prompt_layer": source,
            "prompt_withheld": False,
            "prompt_provenance_reason": "",
        }
    return resolved.text, resolved.source, {
        "prompt_layer": resolved.source,
        "prompt_withheld": bool(resolved.withheld),
        "prompt_provenance_reason": str(resolved.provenance_reason or ""),
    }


@dataclass(frozen=True)
class _InputBudget:
    """Физическая/операторская ёмкость входа (разделение лимитов §7.1).

    ``tokens is None`` — физический потолок не разрешён (резолвер ёмкости
    недоступен): НЕ подставляем произвольное маленькое окно. ``chars`` — это
    ОПЕРАТОРСКИЙ предел (`limits.checkup_max_input_symbols`) и только при
    effective budgets ON; при OFF он не ограничивает доказательства.
    """

    tokens: int | None = None
    chars: int | None = None
    basis: str = "none"
    budgets_enabled: bool = True
    window: int = 0
    window_source: str = ""
    external_tokens: int = 0
    answer_reserve: int = 0
    tool_reserve: int = 0
    operator_chars: int | None = None


@dataclass(frozen=True)
class _LineCost:
    """Одна строка payload: индекс порядка, значимость, цена в токенах/символах."""

    index: int
    line: str
    priority: int
    tokens: int
    chars: int


def _line_priority(line: str) -> int:
    """0 — существенный факт/структура, 1 — предупреждение, 2 — обычный поток."""
    low = line.lower()
    if any(marker in low for marker in _SIGNIFICANT_LINE_MARKERS):
        return 0
    if low.strip().startswith(_STRUCTURED_LINE_PREFIXES):
        return 0
    if _STRUCTURED_FACT_RE.match(line):
        return 0
    if any(marker in low for marker in _WARNING_LINE_MARKERS):
        return 1
    return 2


def _line_costs(lines: list[str], *, offset: int = 0) -> list[_LineCost]:
    """Стоимость строк тем же счётчиком, что и живой контекст (token_counter)."""
    return [
        _LineCost(index=offset + index, line=line,
                  priority=_line_priority(line),
                  tokens=count_tokens(line), chars=len(line))
        for index, line in enumerate(lines)
    ]


def _truncation_note(*, section: str, omitted_lines: int, omitted_chars: int,
                     basis: str, continuation: str,
                     partial_lines: int = 0) -> str:
    """Честная метка об опущенных строках + путь к остатку (не потеря доступа)."""
    return (
        f"[checkup-input-truncated] section={section} "
        f"omitted_lines={int(omitted_lines)} "
        f"omitted_chars={int(omitted_chars)} "
        f"partial_lines={int(partial_lines)} basis={basis} "
        f"remainder=not_pushed continuation={continuation}")


_METRICS_SECTION_PREFIX = "\n\n<memory_health>\n"
_METRICS_SECTION_SUFFIX = "\n</memory_health>"


def _metrics_section(metrics_text: str) -> str:
    """Обёртка секции метрик (та же единственная форма для измерения и body)."""
    if not metrics_text:
        return ""
    return f"{_METRICS_SECTION_PREFIX}{metrics_text}{_METRICS_SECTION_SUFFIX}"


def _continuation_hint(loop_ready: bool) -> str:
    """Маршрут дальнейшей диагностики (существующий инструмент) или честный none."""
    if loop_ready:
        return "inspect_runtime:time_window,cursor"
    return "not_available_in_this_run"


def _has_runtime_tool(tool_schemas) -> bool:
    """Есть ли в объявленных схемах существующий инструмент runtime-проб."""
    for schema in tool_schemas or ():
        if not isinstance(schema, dict):
            continue
        function = schema.get("function")
        name = (function.get("name") if isinstance(function, dict)
                else schema.get("name"))
        if str(name or "") == "inspect_runtime":
            return True
    return False


async def _resolve_input_budget(*, llm, system: str, tool_schemas,
                                operator_chars: int,
                                chat_id: int | None) -> _InputBudget:
    """ФИЗИЧЕСКАЯ ёмкость входа + операторский предел (раздельно, §7.1).

    - физика: реальное окно модели (`services.model_capacity`, live-adapters/
      каталог/реестр с честным source) минус system-инструкции, tool schemas,
      один раунд tool-результатов (`output_reserve_tokens`) и место под ответ
      (`compute_available_budget`) — те же существующие формулы, без новых
      констант;
    - оператор: `limits.checkup_max_input_symbols` действует ТОЛЬКО при
      effective `flags.budgets_enabled=true` (`services.budget_gate`); при OFF
      символьно-искусственная обрезка доказательств не применяется;
    - резолвер ёмкости недоступен → физический потолок НЕ выдумывается
      (`tokens=None`): ни один произвольный размер не подставляется.
    """
    budgets_enabled = True
    try:
        from services import budget_gate
        budgets_enabled = bool(await budget_gate.budgets_enabled(chat_id))
    except Exception:      # pragma: no cover - резолвер не бросает
        logger.warning("[checkup] budget gate failed — operator cap kept",
                       exc_info=True)
        budgets_enabled = True
    chars: int | None = None
    if budgets_enabled:
        try:
            chars = max(1, int(operator_chars))
        except (TypeError, ValueError):
            chars = None
    tokens: int | None = None
    window, window_source = 0, "unavailable"
    external_tokens = answer_reserve = tool_reserve = 0
    try:
        from services import model_capacity as _capacity

        model = str(getattr(llm, "_chat_model", "") or "")
        base_url = str(getattr(llm, "_base_url", "") or "")
        try:
            resolved = await _capacity.resolve_capacity(
                base_url, model, slot="checkup")
            window = int(getattr(resolved, "effective_context_window", 0) or 0)
            window_source = str(getattr(resolved, "source", "") or "")
        except Exception:
            logger.warning("[checkup] capacity resolver failed | model=%s",
                           model[:64], exc_info=True)
            window = 0
        if window <= 0:
            window, window_source = _capacity.resolve_model_context_window(
                model)
        external_tokens = count_tokens(system)
        if tool_schemas:
            external_tokens += count_tokens(json.dumps(
                list(tool_schemas), ensure_ascii=False, default=str))
        available, answer_reserve = _capacity.compute_available_budget(
            window, external_tokens)
        tool_reserve = (_capacity.output_reserve_tokens(window)
                        if tool_schemas else 0)
        tokens = max(1, int(available) - int(tool_reserve))
    except Exception:      # pragma: no cover - защитная ветка
        logger.warning("[checkup] input capacity unavailable — no physical cap",
                       exc_info=True)
        tokens = None
    if chars is not None and tokens is not None:
        basis = "operator+physical"
    elif chars is not None:
        basis = "operator"
    elif tokens is not None:
        basis = "physical"
    else:
        basis = "none"
    return _InputBudget(
        tokens=tokens, chars=chars, basis=basis,
        budgets_enabled=budgets_enabled, window=window,
        window_source=window_source, external_tokens=external_tokens,
        answer_reserve=answer_reserve, tool_reserve=tool_reserve,
        operator_chars=chars)


def _select_kept(costs: list[_LineCost], *, token_limit: int | None,
                 char_limit: int | None, reserve_tokens: int,
                 reserve_chars: int) -> set[int]:
    """Выбрать строки по значимости в пределах ОБОИХ ограничений.

    Строка никогда не режется посередине: сохраняется либо целиком, либо
    опускается (структура фактов/логов не ломается). При равной значимости
    сохраняется исходный хронологический порядок.
    """
    kept: set[int] = set()
    used_tokens = 0
    used_chars = 0
    token_cap = (None if token_limit is None
                 else max(0, int(token_limit) - int(reserve_tokens)))
    char_cap = (None if char_limit is None
                else max(0, int(char_limit) - int(reserve_chars)))
    for cost in sorted(costs, key=lambda item: (item.priority, item.index)):
        if token_cap is not None and used_tokens + cost.tokens > token_cap:
            continue
        if char_cap is not None and used_chars + cost.chars > char_cap:
            continue
        kept.add(cost.index)
        used_tokens += cost.tokens
        used_chars += cost.chars
    return kept


def _head_prefix(line: str, *, token_left: int | None,
                 char_left: int | None) -> str:
    """Голова одной слишком длинной строки (последний честный вариант).

    Применяется ТОЛЬКО когда ни одна строка секции не влезает целиком: иначе
    структура строк не ломается. Точный срез — тем же токенным счётчиком;
    дальнейшая диагностика остатка идёт announced continuation-маршрутом.
    """
    text = str(line or "")
    if char_left is not None:
        text = text[:max(0, int(char_left))]
    if token_left is not None and count_tokens(text) > int(token_left):
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if count_tokens(text[:middle]) <= int(token_left):
                low = middle
            else:
                high = middle - 1
        text = text[:low]
    return text


def _section_output(costs: list[_LineCost], kept: set[int], *,
                    section: str, basis: str, continuation: str,
                    head_tokens: int | None = None,
                    head_chars: int | None = None
                    ) -> tuple[str, int, int]:
    """(текст секции, опущено строк, опущено символов) с меткой об остатке."""
    text = "\n".join(cost.line for cost in costs if cost.index in kept)
    dropped = [cost for cost in costs if cost.index not in kept]
    if not dropped:
        return text, 0, 0
    partial = 0
    omitted_chars = sum(cost.chars for cost in dropped)
    if not text and dropped and (head_tokens is not None
                                 or head_chars is not None):
        # Ни одна строка не влезла целиком: сохраняем голову самой
        # значительной строки, а не теряем содержимое полностью.
        first = min(dropped, key=lambda cost: (cost.priority, cost.index))
        head = _head_prefix(first.line, token_left=head_tokens,
                            char_left=head_chars)
        if head:
            text = head
            partial = 1
            omitted_chars -= len(head)
    note = _truncation_note(
        section=section, omitted_lines=len(dropped),
        omitted_chars=max(0, omitted_chars), basis=basis,
        continuation=continuation, partial_lines=partial)
    return (f"{text}\n{note}" if text else note,
            len(dropped), max(0, omitted_chars))


def _assemble_input(*, logs_text: str, metrics: str, budget: _InputBudget,
                    continuation_ready: bool) -> tuple[str, str, dict]:
    """Собрать user-payload по значимости в пределах ёмкости (SMART §7.2).

    Возвращает ``(logs_out, metrics_out, info)``. Если всё помещается —
    текст байт-в-байт прежний (никаких маркеров). При нехватке места сначала
    сохраняются существенные факты/состояния источников/причины отказа,
    затем метрики и предупреждения, затем обычный поток; опущенное честно
    посчитано, а путь к остатку назван.
    """
    lines = str(logs_text or "").split("\n")
    if continuation_ready and any(line.startswith("[log-source")
                          for line in lines):
        lines = lines + [_HISTORY_NOTE]
    log_costs = _line_costs(lines)
    metric_lines = str(metrics or "").split("\n") if metrics else []
    metric_costs = _line_costs(metric_lines, offset=len(log_costs))
    combined = log_costs + metric_costs
    wrapper = ((_METRICS_SECTION_PREFIX + _METRICS_SECTION_SUFFIX)
               if metric_costs else "")
    total_tokens = (sum(cost.tokens for cost in combined)
                    + count_tokens(wrapper))
    total_chars = (sum(cost.chars for cost in combined) + len(wrapper))
    continuation = _continuation_hint(continuation_ready)
    info = {
        "truncated": False,
        "logs_omitted_lines": 0,
        "logs_omitted_chars": 0,
        "metrics_omitted_lines": 0,
        "metrics_omitted_chars": 0,
        "input_tokens": total_tokens,
        "input_chars": total_chars,
        "logs_chars": sum(cost.chars for cost in log_costs),
        "metrics_chars": sum(cost.chars for cost in metric_costs),
        "budget_basis": budget.basis,
        "budget_tokens": budget.tokens,
        "budget_chars": budget.chars,
        "budget_window": budget.window,
        "budget_window_source": budget.window_source,
        "budgets_enabled": budget.budgets_enabled,
    }
    fits = ((budget.tokens is None or total_tokens <= budget.tokens)
            and (budget.chars is None or total_chars <= budget.chars))
    if fits:
        return "\n".join(lines), "\n".join(metric_lines), info
    # Резерв под честные метки об остатке (счёт по максимально длинным числам,
    # затем точная дожимка ниже — фиксированных констант размера нет).
    reserve_text = (
        _truncation_note(section="logs", omitted_lines=10 ** 6,
                         omitted_chars=10 ** 7, basis=budget.basis,
                         continuation=continuation)
        + (_truncation_note(section="metrics", omitted_lines=10 ** 6,
                            omitted_chars=10 ** 7, basis=budget.basis,
                            continuation=continuation) if metric_costs else ""))
    reserve_costs = _line_costs([reserve_text])
    reserve_tokens = sum(cost.tokens for cost in reserve_costs)
    reserve_chars = sum(cost.chars for cost in reserve_costs)
    if metric_costs:
        # Обёртка секции метрик тоже занимает место в ёмкости.
        reserve_tokens += count_tokens(_METRICS_SECTION_PREFIX
                                       + _METRICS_SECTION_SUFFIX)
        reserve_chars += len(_METRICS_SECTION_PREFIX
                             + _METRICS_SECTION_SUFFIX)
    kept = _select_kept(combined,
                        token_limit=budget.tokens, char_limit=budget.chars,
                        reserve_tokens=reserve_tokens,
                        reserve_chars=reserve_chars)

    def _render(selection: set[int]):
        used_tokens = sum(cost.tokens for cost in combined
                          if cost.index in selection)
        used_chars = sum(cost.chars for cost in combined
                         if cost.index in selection)
        # Свободное место под голову слишком длинной строки: остаток бюджета
        # после сохранённых строк и честной метки (счёт по худшим цифрам).
        head_tokens = head_chars = None
        if budget.tokens is not None:
            head_tokens = max(0, int(budget.tokens) - reserve_tokens
                              - used_tokens)
        if budget.chars is not None:
            head_chars = max(0, int(budget.chars) - reserve_chars - used_chars)
        logs_part = {index for index in selection if index < len(log_costs)}
        metric_part = {index - len(log_costs) for index in selection
                       if index >= len(log_costs)}
        logs_text_out, logs_dropped, logs_dropped_chars = _section_output(
            log_costs, logs_part, section="logs", basis=budget.basis,
            continuation=continuation, head_tokens=head_tokens,
            head_chars=head_chars)
        metrics_text_out, metric_dropped, metric_dropped_chars = \
            _section_output(metric_costs, metric_part, section="metrics",
                            basis=budget.basis,
                            continuation=continuation, head_tokens=head_tokens,
                            head_chars=head_chars)
        return (logs_text_out, metrics_text_out, logs_dropped,
                logs_dropped_chars, metric_dropped, metric_dropped_chars)

    logs_out, metrics_out, logs_omitted, logs_omitted_chars, \
        metric_omitted, metric_omitted_chars = _render(kept)
    # Дожимка по фактическому тексту: метка об остатке могла оказаться
    # длиннее резерва, а переводы строк считаются не как сумма строк. Снимаем
    # наименее значимые сохранённые строки, пока payload не уложится.
    while kept:
        effective_text = logs_out + _metrics_section(metrics_out)
        effective_tokens = count_tokens(effective_text)
        effective_chars = len(effective_text)
        if ((budget.tokens is None or effective_tokens <= budget.tokens)
                and (budget.chars is None
                     or effective_chars <= budget.chars)):
            break
        victim = max((cost for cost in combined if cost.index in kept),
                     key=lambda item: (item.priority, item.index),
                     default=None)
        if victim is None:
            break
        kept.discard(victim.index)
        logs_out, metrics_out, logs_omitted, logs_omitted_chars, \
            metric_omitted, metric_omitted_chars = _render(kept)
    info.update({
        "truncated": bool(logs_omitted or metric_omitted),
        "logs_omitted_lines": logs_omitted,
        "logs_omitted_chars": logs_omitted_chars,
        "metrics_omitted_lines": metric_omitted,
        "metrics_omitted_chars": metric_omitted_chars,
    })
    return logs_out, metrics_out, info


class CheckupService:
    """Канон SmartModule: system.replace({max_symbols}) → llm.generate →
    cleanup_llm_text (R33-7, ВСЕГДА) → outbound Style Policy (P0-CHECKUP,
    только пользовательская команда) → хендлер. LLMError пробрасывается.
    Epic 60 (64.5): метрики памяти подаются ДАННЫМИ в user-контент (без
    db/memory — ровно старое поведение; metrics_enabled=false — рубильник)."""

    def __init__(self, llm: LLMClient, db=None, memory=None,
                 metrics_enabled: bool = settings.CHECKUP_MEMORY_METRICS_ENABLED) -> None:
        self.llm = llm
        self.db = db
        self.memory = memory
        self.metrics_enabled = metrics_enabled

    async def checkup(self, logs_text: str, used_fallback: bool,
                      chat_id: int | None = None, *,
                      telemetry: dict | None = None,
                      tool_runtime: dict | None = None) -> str:
        """logs_text = результат fetcher.fetch(); used_fallback → скрытая
        приписка CHECKUP_FALLBACK_NOTICE в КОНЕЦ system-сообщения (51.4).

        UNIFIED-CORE (P0, 20.10.2026): ``chat_id`` (пользовательская команда
        в чате) → после канона идут Core + Expression владельца; без ``chat_id``
        (внутренний tool-loop ``get_bot_health`` — отчёт вербализует Direct
        Writer) блок не передаётся: внутренние данные остаются нейтральными.

        SELF-DIAG-01 D6 B1 (`SD1-D6-05`): ``telemetry`` — per-run словарь
        вызывающего. Сервис заполняет ЕГО, а не общий mutable-атрибут:
        одновременные чекапы разных чатов не видят чужую телеметрию. Hash
        считается по ФИНАЛЬНОМУ system (ровно те байты, что уходят в LLM).

        SELF-DIAG-01 corrective (§3 owner input): ``tool_runtime`` —
        СУЩЕСТВУЮЩИЙ tool-loop контур, подготовленный handler'ом
        (``{"router","ctx","schemas","correlation_id"}``). Передан → чекап
        идёт через ``tool_loop.chat_with_tools`` с объявленными read-only
        диагностическими инструментами; модель сама решает, читать ли код и
        runtime, а результаты возвращаются ей для синтеза. None/пустой набор
        → прежний одиночный ``generate`` (паритет и офлайн-тесты).

        SMART-CORRECTIVE-01 §4: для чекапа явно включается политика
        завершения исследования (``ensure_research_completion``) — при
        структурном пробеле модель получает продолжение в том же цикле, а
        если продолжение невозможно/исчерпано, ответ помечается как
        частичный с конкретной причиной. Здоровый чекап без инструментальных
        попыток остаётся одним вызовом модели."""
        # T-619: промпт/лимиты/флаг метрик — горячие точки (фолбек settings)
        # SMART-CORRECTIVE-01 §8.2 (S6-PROMPT): база — chat override → global
        # → factory существующим резолвером реестра; без chat_id — прежний
        # global-резолв (`prompt_source` = global/default).
        system_prompt, prompt_source, prompt_meta = \
            await _resolve_checkup_base_prompt(chat_id)
        prompt_base_text = str(system_prompt or "")
        max_symbols = hot.get("limits.checkup_max_symbols",
                              settings.CHECKUP_MAX_SYMBOLS)
        max_input = hot.get("limits.checkup_max_input_symbols",
                            settings.CHECKUP_MAX_INPUT_SYMBOLS)
        metrics_enabled = hot.get("flags.checkup_memory_metrics_enabled",
                                  self.metrics_enabled)
        system = system_prompt.replace("{max_symbols}", str(max_symbols))
        # UNIFIED-CORE: слои владельца речи — ДО служебной приписки
        # (CHECKUP_FALLBACK_NOTICE остаётся последним абзацем system).
        owner_block = await speech_owner_block(chat_id)
        if owner_block:
            system = f"{system}\n\n{owner_block}"
        # SELF-DIAG-01 corrective (§3): функциональная операционная директива
        # подключается только при реально переданном tool-loop; базовый
        # owner-канон/характер остаются байт-в-байт. Стоит ДО служебной
        # приписки — CHECKUP_FALLBACK_NOTICE остаётся последним абзацем.
        _tool_schemas = ()
        if isinstance(tool_runtime, dict):
            _tool_schemas = tuple(tool_runtime.get("schemas") or ())
        if _tool_schemas:
            system += "\n\n" + CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM
        if used_fallback:
            system += "\n\n" + CHECKUP_FALLBACK_NOTICE     # R42-2: ровно 1 раз
        _router = (tool_runtime or {}).get("router") \
            if isinstance(tool_runtime, dict) else None
        _tool_ctx = (tool_runtime or {}).get("ctx") \
            if isinstance(tool_runtime, dict) else None
        # Реальный tool-loop (не только объявленные схемы) — условие, при
        # котором обещание «остаток доступен инструментом» правдиво; для
        # маршрута продолжения нужен именно существующий runtime-инструмент.
        loop_ready = bool(_tool_schemas and _router is not None
                          and _tool_ctx is not None)
        continuation_ready = bool(loop_ready
                                  and _has_runtime_tool(_tool_schemas))
        # Epic 49 (57.5, D196): scrub C0 (гипотеза (б) — невалидные управляющие
        # символы raw-логов). Единая точка — здесь, ДО escape_xml_text.
        user_content = _CONTROL_CHARS_RE.sub(" ", logs_text)
        metrics = ""
        if metrics_enabled and self.db is not None:
            try:
                metrics = await collect_metrics(self.db, self.memory)
            except Exception:
                logger.warning("[checkup] memory metrics failed", exc_info=True)
                metrics = ""
        # SMART-CORRECTIVE-01 §7 (S3B-INPUT): ёмкость входа — ФИЗИЧЕСКОЕ окно
        # модели (минус system, tool schemas, раунд tool-результатов и ответ)
        # плюс операторский предел `limits.checkup_max_input_symbols` ТОЛЬКО
        # при effective budgets ON. Желаемый объём отчёта (`{max_symbols}`)
        # здесь не участвует: длина отчёта не ограничивает исследование.
        input_budget = await _resolve_input_budget(
            llm=self.llm, system=system, tool_schemas=_tool_schemas,
            operator_chars=max_input, chat_id=chat_id)
        user_content, metrics, input_info = _assemble_input(
            logs_text=user_content, metrics=metrics,
            budget=input_budget,
            continuation_ready=continuation_ready)
        input_truncated = bool(input_info["truncated"])
        if input_truncated:
            logger.warning(
                "[checkup] input truncated | chars=%d -> %d | omitted_lines=%d "
                "| basis=%s | window=%d/%s",
                input_info["logs_chars"],
                len(user_content),
                int(input_info["logs_omitted_lines"])
                + int(input_info["metrics_omitted_lines"]),
                input_info["budget_basis"], input_info["budget_window"],
                input_info["budget_window_source"] or "-")
        # БЕЗ предварительного escape (escape РОВНО ОДИН на обёртке ниже).
        metrics_section = _metrics_section(metrics)
        body = user_content + metrics_section
        user = f"<system_logs>{escape_xml_text(body)}</system_logs>"
        # SELF-DIAG-01 D6 B1: телеметрия ФИНАЛЬНОГО system — сразу перед
        # вызовом LLM (после {max_symbols}/owner-block/fallback-notice).
        # S6 (§8.2): additive-ключи базы (слой/hash/chars/удержание) — без
        # текста промпта, только машинные значения.
        prompt_telemetry = self._prompt_telemetry(
            system, prompt_source, base_text=prompt_base_text,
            meta=prompt_meta)
        if telemetry is not None:
            telemetry.update(prompt_telemetry)
        started = time.monotonic()
        # SMART-CORRECTIVE-01 §4: честная пометка частичного исследования
        # ('' — исследование завершено содержательно либо ответ уже
        # деградирован финальной фазой tool-loop с собственной причиной).
        research_note = ""
        if loop_ready:
            # SELF-DIAG-01 corrective (§3): ОДИН существующий tool-loop.
            # Рантайм-факты/логи уже в сообщениях; модель решает, какие
            # инструменты вызвать; результаты возвращаются ей же.
            # SMART-CORRECTIVE-01 §4: чекап — диагностическое исследование,
            # поэтому потребитель явно включает политику завершения: модель,
            # остановившаяся текстом при структурном пробеле, получает
            # продолжение в ТОМ ЖЕ цикле либо возвращает честный partial.
            from services.tool_loop import (
                chat_with_tools,
                research_partial_note,
            )
            loop_result = await chat_with_tools(
                self.llm,
                [{"role": "system", "content": system},
                 {"role": "user", "content": user}],
                tools=list(_tool_schemas), router=_router, ctx=_tool_ctx,
                chat_id=chat_id, module="checkup",
                correlation_id=str(
                    (tool_runtime or {}).get("correlation_id") or ""),
                ensure_research_completion=True)
            raw = str(loop_result)
            research_state = (getattr(loop_result, "research_state", None)
                              or {})
            if telemetry is not None:
                research_tools = [
                    str(entry.get("tool") or "")
                    for entry in (loop_result.tool_results or ())
                    if isinstance(entry, dict)]
                continuation = research_state.get("continuation") or {}
                telemetry.update({
                    "research_rounds": int(loop_result.rounds_used or 0),
                    "research_calls": len(loop_result.tool_results or ()),
                    "research_tools": ",".join(
                        sorted({name for name in research_tools if name})),
                    "research_degraded": bool(loop_result.degraded),
                    "research_reason": str(loop_result.reason or "ok"),
                    "research_status": str(research_state.get("status") or ""),
                    "research_cause": str(research_state.get("cause") or ""),
                    "research_continuations": int(
                        getattr(loop_result, "continuation_offers", 0) or 0),
                    "research_confirmed": int(
                        research_state.get("confirmed") or 0),
                    "research_unresolved": len(
                        research_state.get("gaps") or ()),
                    "research_evidence_ref_count": len(
                        research_state.get("evidence_refs") or ()),
                    "research_continuation_available": bool(
                        continuation.get("available")),
                })
            # Честный частичный результат: свободный ответ модели при
            # незакрытом структурном пробеле помечается причиной и
            # неподтверждёнными участками. Деградированные ответы уже
            # получают причину в финальной фазе tool-loop (не дублируем).
            if not loop_result.degraded:
                research_note = research_partial_note(research_state)
        else:
            raw = await self.llm.generate(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            )
        logger.info(
            "checkup LLM OK | out_chars=%d | latency_ms=%.0f | used_fallback=%s",
            len(raw), (time.monotonic() - started) * 1000.0, used_fallback,
        )
        if telemetry is not None:
            telemetry.update({
                "latency_ms": int((time.monotonic() - started) * 1000.0),
                "report_chars": len(raw),
                "metrics_included": bool(metrics),
                "input_truncated": bool(input_truncated),
                "input_chars": int(input_info["input_chars"]),
                "input_tokens": int(input_info["input_tokens"]),
                "input_omitted_lines": (
                    int(input_info["logs_omitted_lines"])
                    + int(input_info["metrics_omitted_lines"])),
                "input_budget_basis": str(input_info["budget_basis"]),
                "input_budget_chars": input_info["budget_chars"],
                "input_budget_tokens": input_info["budget_tokens"],
                "input_window": int(input_info["budget_window"]),
                "input_window_source": str(
                    input_info["budget_window_source"] or ""),
                "budgets_enabled": bool(input_info["budgets_enabled"]),
                "report_length_setting": int(max_symbols or 0),
                "used_fallback": bool(used_fallback),
                "chat_scoped": chat_id is not None,
            })
        raw = cleanup_llm_text(raw)
        if not raw.strip():
            # Epic 60 (65.1, T-469): пустой ответ → молчание + 🗿 (хендлер
            # ничего не шлёт). Ветка хендлера ДО except LLMError.
            raise LLMBadResponseError("checkup: empty answer")
        # SMART-CORRECTIVE-01 §4/§6.3: модель сама направляла исследование,
        # но структурный пробел остался — отчёт не выдаётся за полный.
        # Пометка добавляется ДО единственного outbound-прохода стиля, чтобы
        # действующие настройки чата применялись к финальному тексту целиком.
        if research_note:
            raw = raw.rstrip() + research_note
        # P0-CHECKUP (24.10.2026, addendum §5): исходящий Checkup-текст
        # проходит ДЕЙСТВУЮЩИЙ outbound Style Policy (dash.hard.factory,
        # настройки чата) — тот же единственный проход, что у Direct, без
        # второго движка/regex. Только пользовательская команда (chat_id);
        # внутренний tool-loop отдаёт данные Direct Writer, который применит
        # свой outbound-проход (без двойной обработки).
        if chat_id is not None:
            raw = await self._apply_outbound_style(raw, chat_id)
        return raw

    @staticmethod
    def _prompt_telemetry(system: str, source: str, *,
                          base_text: str = "", meta: dict | None = None) -> dict:
        """SELF-DIAG-01 D6 B1 (`SD1-D6-05`): source/version/hash ФИНАЛЬНОГО
        system-сообщения — БЕЗ текста. Hash считается по ровно тем байтам,
        которые уходят в LLM (включая `{max_symbols}`, owner-block и
        fallback-notice), поэтому сверка «до/после релиза» опирается на факт.

        SMART-CORRECTIVE-01 §8.2 (S6-PROMPT): прежние ключи сохранены
        (`prompt_source/prompt_hash/prompt_version_used/prompt_chars`), добавлены
        additive-ключи фактического слоя и базы ДО сборки:
        ``prompt_layer`` (``chat|global|default``), ``prompt_base_hash`` и
        ``prompt_base_chars`` (резолвнутая сохранённая редакция до подстановки
        `{max_symbols}`/owner-block/addendum — по ним проверяется, что ушла
        именно сохранённая редакция), ``prompt_withheld`` и
        ``prompt_provenance_reason`` (код причины, без текста).
        """
        text = str(system or "")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        source = str(source or "default")
        base = str(base_text or "")
        base_digest = hashlib.sha256(base.encode("utf-8")).hexdigest()
        meta = meta or {}
        return {
            "prompt_source": source,
            "prompt_hash": digest[:16],
            "prompt_version_used": f"{source}:{digest[:12]}",
            "prompt_chars": len(text),
            "prompt_layer": str(meta.get("prompt_layer") or source),
            "prompt_base_hash": base_digest[:16],
            "prompt_base_chars": len(base),
            "prompt_withheld": bool(meta.get("prompt_withheld")),
            "prompt_provenance_reason": str(
                meta.get("prompt_provenance_reason") or ""),
        }

    @staticmethod
    async def _apply_outbound_style(text: str, chat_id: int) -> str:
        """Один проход существующего Style Policy; fail-open (текст как есть)."""
        try:
            from services import style_policy as _style_policy
            outcome = await _style_policy.apply_style_policy(
                text, chat_id=int(chat_id), context="regular",
                emit_events=True, stage="checkup_pre_send")
        except Exception:      # pragma: no cover - проход не роняет отправку
            logger.warning("[checkup] style policy pass failed | chat=%s",
                           chat_id, exc_info=True)
            return text
        if outcome.applied and str(outcome.text or ""):
            return outcome.text
        return text
