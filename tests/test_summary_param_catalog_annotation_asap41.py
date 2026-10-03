"""ASAP 4.1 / фикс [M-ASAP41-1] (финальный gate T-4629): spec §8.1 аннотация.

Судьба spec §8.1 (зона H, T-4602 — ключи «обычная админка, остаётся»):
описания `LLM_TIMEOUT` (param_catalog.py:735) и `LLM_TOTAL_BUDGET`
(param_catalog.py:745) дополняются пометкой «не управляет Summary».
Смысл — закрыть прод-антипаттерн «повысить таймаут» (§50/§G.3): админ
должен видеть прямо в витрине, что ключ больше не управляет Summary —
длительность Саммари определяет супервизор исполнения (Supervisor, AM-3).

Правка doc-only: строки описаний в REGISTRY; значения/типы/группы/
поведение не тронуты. Тест — R6-H-сосед, проверяет витрину каталога.
"""

from __future__ import annotations

import services.param_catalog as pc

# Маркеры spec §8.1 («пометкой „не управляет Summary"») + человеческое
# объяснение причины (супервизор). Case-insensitive для русской фразы,
# exact-case для обязательного сокращения Summary.
_MARKER_NOT_MANAGES = "не управляет"
_MARKER_SUMMARY = "Summary"
_MARKER_SUPERVISOR = "супервизор"

# Ключи с обещанной строкой судьбы §8.1.
ANNOTATED_KEYS = ("LLM_TIMEOUT", "LLM_TOTAL_BUDGET")


def _has_annotation(spec: pc.ParamSpec) -> bool:
    lowered = spec.description.lower()
    return (
        _MARKER_NOT_MANAGES in lowered
        and _MARKER_SUMMARY in spec.description
        and _MARKER_SUPERVISOR in lowered
    )


class TestSpec81SummaryAnnotation:
    def test_llm_timeout_description_carries_marker(self):
        spec = pc.REGISTRY["LLM_TIMEOUT"]
        assert _has_annotation(spec), (
            "spec §8.1: описание LLM_TIMEOUT должно содержать пометку "
            "«не управляет Summary»")

    def test_llm_total_budget_description_carries_marker(self):
        spec = pc.REGISTRY["LLM_TOTAL_BUDGET"]
        assert _has_annotation(spec), (
            "spec §8.1: описание LLM_TOTAL_BUDGET должно содержать пометку "
            "«не управляет Summary»")

    def test_marker_explain_supervisor_not_generic(self):
        # Пометка честно объясняет замену, а не обрывается: «…— длительность
        # Саммари определяет супервизор…» — поясняющих хвостов достаточно.
        for key in ANNOTATED_KEYS:
            desc = pc.REGISTRY[key].description
            assert "длительность" in desc.lower() and _MARKER_SUPERVISOR in desc, (
                f"{key}: пометка должна объяснять, что длительность Саммари "
                "определяет супервизор исполнения")

    def test_sibling_keys_do_not_carry_exclusive_marker(self):
        # Точный охват пометки = ровно два ключа §8.1 (ловля случайного
        # массового sweep по остальным описаниям каталога).
        flagged = [
            env for env, spec in pc.REGISTRY.items()
            if env not in ANNOTATED_KEYS and _has_annotation(spec)
        ]
        assert flagged == [], (
            "строка судьбы §8.1 обещана только LLM_TIMEOUT/LLM_TOTAL_BUDGET; "
            f"пометка обнаружена у: {flagged}")

    def test_annotated_keys_values_and_groups_untouched(self):
        # Doc-only инвариант: значения/типы/группы/поля не тронуты.
        assert pc.REGISTRY["LLM_TIMEOUT"].type == "float"
        assert pc.REGISTRY["LLM_TIMEOUT"].group == "models_llm_timeouts"
        assert pc.REGISTRY["LLM_TIMEOUT"].settings_field == "LLM_TIMEOUT"
        assert pc.REGISTRY["LLM_TOTAL_BUDGET"].type == "float"
        assert pc.REGISTRY["LLM_TOTAL_BUDGET"].group == "models_llm_guard"
        assert pc.REGISTRY["LLM_TOTAL_BUDGET"].settings_field == "LLM_TOTAL_BUDGET"
