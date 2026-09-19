"""Редизайн 10.5 (Reviewer D1/D2) — РЕАЛЬНЫЕ JS-тесты (node), не grep.

Запускает tests/js/routing_test.js в stubbed-окружении: проверяет hub-aware
RBAC-гейт (D1) и отбрасывание устаревших in-flight ответов scope (D2).
Пропускается, если node недоступен.
"""
import os
import shutil
import subprocess

import pytest


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    return node


def _run_js(script: str, ok_marker: str = "JS-UNIT-OK"):
    node = _node()
    assert os.path.exists(script)
    res = subprocess.run(
        [node, script],
        capture_output=True, text=True, timeout=60,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert res.returncode == 0, (
        "JS-UNIT провалился (%s):\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (script, res.stdout, res.stderr))
    assert ok_marker in res.stdout


def test_js_unit_routing_and_scope_guard():
    _run_js(os.path.join("tests", "js", "routing_test.js"))


def test_js_unit_round1021_ui_audit():
    """F6 round 10.21 (T-1990…T-2000): регресс-зонды UI-аудита —
    glass/grid/mask/gradient/sticky + инвариант меню + регресс
    `_syntheticGroup` (метод, а не computed)."""
    _run_js(os.path.join("tests", "js", "round1021_ui_audit_test.js"))


def test_js_unit_round1022_aliases():
    """F2 round 10.22 (T-2032): KV-редактор `summary_aliases` рендерит пары из
    объекта И из строки-JSON (двойное кодирование) — регресс-гейт."""
    _run_js(os.path.join("tests", "js", "round1022_aliases_test.js"),
            ok_marker="ALIASES-UNIT-OK")


def test_js_unit_round1022_dossier_rebuild():
    """F8 round 10.22 (ADR-1022-8): фронт пересборки досье — статусы/job-view,
    POST period, 409-подхват, отмена+rollback-статус, polling, localStorage."""
    _run_js(os.path.join("tests", "js", "round1022_dossier_rebuild_test.js"),
            ok_marker="DOSSIER-REBUILD-UNIT-OK")


def test_js_unit_round1023_verbilizer_tabs():
    """F8 round 10.23 (ADR-1023-8): stage-секции «Промпты», Tabs режимов,
    блок анти-клише (force/PUT/fail-open)."""
    _run_js(os.path.join("tests", "js", "round1023_verbilizer_tabs_test.js"),
            ok_marker="VERBILIZER-UNIT-OK")


def test_js_unit_round1024_nodeflow():
    """F3 round 10.24 (ADR-1024-7): визуальное дерево вызова (Node Flow) —
    проекция steps[] (двухслойный/tool/single/image/пусто), нейминг,
    kill-switch uiFlag (OFF → бейджи), CSP/no-CDN."""
    _run_js(os.path.join("tests", "js", "round1024_nodeflow_test.js"),
            ok_marker="NODEFLOW-UNIT-OK")


def test_js_unit_round1024_image_module():
    """F5 round 10.24 (ADR-1024-9): карточка «Генерация изображений» в
    «Модулях» — toggleKey/tab/icon, вкладка mod_images с группой
    flags_module_images (один дом), menu-freeze +1, гейт uiFlag."""
    _run_js(os.path.join("tests", "js", "round1024_image_module_test.js"),
            ok_marker="IMAGE-MODULE-OK")


def test_js_unit_round1024_prompts_ui():
    """F6 round 10.24 (ADR-1024-10): плоский grid «Промптов» (без аккордеонов),
    fallback-режим → casual, табы режимов внутри карточек модулей."""
    _run_js(os.path.join("tests", "js", "round1024_prompts_ui_test.js"),
            ok_marker="PROMPTS-UI-UNIT-OK")
