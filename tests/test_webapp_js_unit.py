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
