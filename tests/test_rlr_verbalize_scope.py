"""REMOVE-LEGACY-REPHASING v2.0 — границы переписывания готовой речи.

Owner corrective `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`
(R-04.1/R-04.2, R-03.1/R-03.2/R-03.3, §3.4):

* свободная речь L2 доставляется **как написана**: ни форма, ни числа, ни
  отрицания, ни метатекст, ни формат, ни клише не вызывают ни повторной
  генерации, ни вставки готовой фразы, ни снятия предложения — всё это
  только наблюдения в ``stats``;
* машинный протокол (структура JSON/схема) чинится ОТДЕЛЬНО и только в
  машинном слое — ``repair_machine_payload``, bounded и с видимой причиной;
* явная трансформация («перепиши/переведи/отредактируй») получает узкую
  детерминированную проверку защищённых данных и прозрачный исход, но не
  второго литературного автора.

TEST-LIFECYCLE: CONTRACT owner=REMOVE-LEGACY-REPHRASING (R-04, R-03)
"""
import ast
import inspect
import json

import pytest
from unittest.mock import AsyncMock

from services import negative_constraints as nc
from services import public_speech_guard as psg
from services.prompt_style_blocks import (
    FORM_GUARD_RETRY_SYSTEM_PROMPT,
    NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT,
)

pytestmark = pytest.mark.system2

_BASE = [{"role": "user", "content": "расскажи, что было в чате"}]

#: Текст, нарушающий ВСЕ диагностики сразу: отрицание с числом, клише, метатекст
#: и формат plain-канала. Он обязан уйти пользователю байт-в-байт.
_NOISY = ("Как ИИ, подводя итог: Вася не писал 12 сообщений в чат. "
          "Весь интернет я проверил.\n| a | b |\n|---|---|")


class _Claim:
    """Минимальный NumericClaim-совместимый объект (value/unit)."""

    value = 9
    unit = "messages"


def _run(coro):
    import asyncio
    return asyncio.run(coro)


# ════════════════════════════════════════════════════════════════════════════
# 1. Свободная речь: одно Writer-обращение, текст как написан, наблюдения
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_free_form_text_with_all_diagnostics_is_delivered_as_written():
    """Клише + метатекст + число + формат: ровно один LLM-вызов, текст
    байт-в-байт, все находки — только наблюдения."""
    calls: list = []

    async def gen(messages):
        calls.append([dict(m) for m in messages])
        return _NOISY

    text, stats = await nc.verbalize_validated(
        gen, list(_BASE),
        enabled_rules=nc.channel_enabled_rules("plain", "serious"),
        numeric_contract=nc.NumericContract(claims=(_Claim(),),
                                            verified_phrase="9 сообщений"),
        metatext_reason=psg.metatext_retry_reason)

    assert len(calls) == 1                      # второго вызова LLM нет
    assert text == _NOISY                       # авторский текст не изменён
    assert "9 сообщений" not in text            # verified_phrase не вставлен
    assert stats["attempts"] == 1 and stats["retries"] == 0
    assert stats["cliche_observed"] == ["as_ai", "summing_up"]
    assert stats["format_observed"] == ["plain_no_tables"]
    assert stats["metatext_observed"]
    assert stats["numeric_claim_mismatch"] == 1
    assert stats["numeric_claim_fallback"] is False
    assert stats["numeric_claim_retry"] is False
    assert stats["anti_cliche_retries"] == 0
    assert stats["semantic_rewrite_count"] == 0
    # Свободный путь не создаёт form-контракта и не считает «отказы».
    assert "form_guard_rejects" not in stats


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", [
    "Вася писал в чат про это.",                       # отрицание отсутствует
    "Вася не писал 12 сообщений.",                     # число
    "Как ИИ, отвечаю: всё хорошо.",                    # клише
    "Весь интернет я проверил, это точно.",            # метатекст
    "| a | b |\n|---|---|",                            # формат plain
])
async def test_single_signal_free_form_is_never_corrected(candidate):
    """Каждый отдельный сигнал: один вызов и текст без изменений."""
    calls = 0

    async def gen(messages):
        nonlocal calls
        calls += 1
        return candidate

    text, stats = await nc.verbalize_validated(
        gen, list(_BASE),
        enabled_rules=nc.channel_enabled_rules("plain", "serious"),
        numeric_contract=nc.NumericContract(claims=(_Claim(),)),
        metatext_reason=psg.metatext_retry_reason)

    assert calls == 1
    assert text == candidate
    assert stats["retries"] == 0
    assert stats["semantic_rewrite_count"] == 0


# ════════════════════════════════════════════════════════════════════════════
# 2. Машинный протокол: повтор остаётся только в машинном слое
# ════════════════════════════════════════════════════════════════════════════

def _json_validator(value: str) -> str | None:
    try:
        parsed = json.loads(value)
    except ValueError:
        return nc.MACHINE_CONTRACT_REJECTED
    if not isinstance(parsed, dict) or "answer" not in parsed:
        return nc.MACHINE_CONTRACT_REJECTED
    return None


def test_invalid_machine_json_is_repaired_in_machine_stage_only():
    """§3.4: схема чинится в подготовительном слое, ≤1 повтор, причина видна."""
    replies = ["{oops", json.dumps({"answer": "ок"})]
    calls: list[list[dict]] = []

    async def gen(messages):
        calls.append([dict(m) for m in messages])
        return replies[len(calls) - 1]

    text, stats = _run(nc.repair_machine_payload(
        gen, list(_BASE), validator=_json_validator, max_retries=1))

    assert len(calls) == 2                              # 1 кандидат + 1 починка
    assert json.loads(text) == {"answer": "ок"}
    assert stats["machine_reasons"] == [nc.MACHINE_CONTRACT_REJECTED]
    assert stats["machine_unrepaired"] is False
    assert stats["fallback"] is False
    # Повтор — машинный, со служебной причиной, а не литературный канон.
    retry_system = [m["content"] for m in calls[1] if m["role"] == "system"]
    assert retry_system and retry_system[-1].startswith(
        nc.MACHINE_CONTRACT_PREFIX)
    assert retry_system[-1].endswith(nc.MACHINE_CONTRACT_REJECTED)
    assert FORM_GUARD_RETRY_SYSTEM_PROMPT not in str(calls)
    assert NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT not in str(calls)


def test_machine_repair_is_bounded_and_reports_unrepaired():
    """Граница машинного слоя: не более cap повторов, честный флаг."""
    calls = 0

    async def gen(messages):
        nonlocal calls
        calls += 1
        return "{oops"

    text, stats = _run(nc.repair_machine_payload(
        gen, list(_BASE), validator=_json_validator, max_retries=99))

    assert calls == nc._MAX_RETRIES_HARD_CAP + 1        # потолок, не 99
    assert text == "{oops"                              # ничего не выдумано
    assert stats["machine_unrepaired"] is True
    assert stats["fallback"] is True
    assert stats["machine_reasons"] == [nc.MACHINE_CONTRACT_REJECTED] * (
        nc._MAX_RETRIES_HARD_CAP + 1)


# ════════════════════════════════════════════════════════════════════════════
# 3. Явная трансформация: узкая проверка данных, без второго автора
# ════════════════════════════════════════════════════════════════════════════

_SOURCE = "По проверке, Вася не писал 12 сообщений в чат."


@pytest.mark.parametrize("candidate", [
    "По проверке, Вася писал 12 сообщений в чат.",      # потеряно «не»
    "По проверке, Вася не писал 13 сообщений в чат.",   # подменено число
    "По проверке, Петя не писал 12 сообщений в чат.",   # новое имя ростера
])
def test_explicit_rewrite_validates_protected_facts_without_second_author(
        candidate):
    """Явная трансформация: узкая проверка срабатывает, но нового автора нет —
    возвращаются исходные данные и видимая причина."""
    calls = 0

    async def gen(messages):
        nonlocal calls
        calls += 1
        return candidate

    text, stats = _run(nc.verbalize_validated(
        gen, [{"role": "user", "content": "перепиши без изменения фактов"}],
        form_contract=nc.FormContract(source_text=_SOURCE,
                                      roster_names=("Вася", "Петя")),
        fallback_text=_SOURCE))

    assert calls == 1
    assert text == _SOURCE
    assert stats["form_guard_reason"] == nc.FORM_GUARD_REJECTED
    assert stats["form_guard_rejects"] == 1
    assert stats["protected_facts_mismatch"] is True
    assert stats["form_retry"] is False
    assert stats["form_fallback"] is True
    assert stats["semantic_rewrite_count"] == 0


def test_explicit_rewrite_without_source_keeps_author_text_and_flags_clarification():
    """Нет исходника для прозрачного исхода: авторский текст остаётся как
    написан (никакой подмены), вызывающий видит требование уточнения."""
    async def gen(messages):
        return "По проверке, Вася писал 12 сообщений в чат."

    text, stats = _run(nc.verbalize_validated(
        gen, [{"role": "user", "content": "перепиши своими словами"}],
        form_contract=nc.FormContract(source_text=_SOURCE),
        fallback_text=""))

    assert text == "По проверке, Вася писал 12 сообщений в чат."
    assert stats["form_fallback"] is False
    assert stats["needs_clarification"] is True
    assert stats["fallback"] is False
    assert stats["semantic_rewrite_count"] == 0


def test_explicit_rewrite_that_keeps_facts_is_delivered_as_written():
    """Защищённые данные целы → текст уходит как написан, без «коррекций»."""
    rewritten = "Как показала проверка, в чат про это Вася не писал 12 сообщений."

    async def gen(messages):
        return rewritten

    text, stats = _run(nc.verbalize_validated(
        gen, [{"role": "user", "content": "перепиши без изменения фактов"}],
        form_contract=nc.FormContract(source_text=_SOURCE,
                                      roster_names=("Вася",)),
        fallback_text=_SOURCE))

    assert text == rewritten
    assert stats["form_guard_rejects"] == 0
    assert stats["fallback"] is False
    assert stats["semantic_rewrite_count"] == 0


def test_machine_validation_is_not_used_for_free_speech():
    """Границы разделены: свободная речь не принимает машинный валидатор,
    машинный слой не правит речь (разные функции, разные контракты)."""
    free_params = set(inspect.signature(nc.verbalize_validated).parameters)
    machine_params = set(
        inspect.signature(nc.repair_machine_payload).parameters)
    assert "validator" not in free_params
    assert "validator" in machine_params
    assert "form_contract" not in machine_params
    assert "scrubber" not in machine_params      # машинный payload не чистится


# ════════════════════════════════════════════════════════════════════════════
# 4. Инвариант кода: в свободном пути не осталось reroll-механизма
#    MUTATION: если вернуть в verbalize_validated ветку повтора (второй
#    ``await generate_call`` или импорт form/numeric retry-канона), этот тест
#    и тесты §1 становятся красными.
# ════════════════════════════════════════════════════════════════════════════

def test_free_form_path_has_no_reroll_mechanism_in_source():
    """AST-проверка кода, а не документации: один Writer-вызов, никаких
    канонов повтора и никакой подстановки verified_phrase."""
    tree = ast.parse(inspect.getsource(nc))
    imported = {alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names}
    assert "FORM_GUARD_RETRY_SYSTEM_PROMPT" not in imported
    assert "NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT" not in imported

    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "verbalize_validated")
    # Ни одной петли/повторного вызова: два обращения к LLM — это
    # kill-switch-ветка и единственный основной путь, оба одноразовые.
    assert not [node for node in ast.walk(function)
                if isinstance(node, (ast.While, ast.For))], \
        "в свободном пути появилась петля повторов"
    generate_awaits = [
        node for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "generate_call"]
    assert len(generate_awaits) == 2             # ровно два одиночных вызова
    function_source = ast.get_source_segment(inspect.getsource(nc), function) or ""
    assert "retry_messages" not in function_source
    assert "stats[\"retries\"] += 1" not in function_source

    used = {node.id for node in ast.walk(function)
            if isinstance(node, ast.Name)}
    used |= {node.attr for node in ast.walk(function)
             if isinstance(node, ast.Attribute)}
    assert "NUMERIC_CLAIM_FALLBACK" not in used       # нет подстановки фразы
    assert "NUMERIC_CLAIM_CAVEAT" not in used         # нет подмены оговоркой
    assert "_correct_numeric_claims" not in used      # нет снятия предложений

    assert NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT not in function_source
    assert FORM_GUARD_RETRY_SYSTEM_PROMPT not in function_source
