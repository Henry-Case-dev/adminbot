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


def test_js_unit_routing_and_scope_guard():
    script = os.path.join("tests", "js", "routing_test.js")
    assert os.path.exists(script)
    res = subprocess.run(
        [_node(), script],
        capture_output=True, text=True, timeout=60,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert res.returncode == 0, (
        "JS-UNIT провалился:\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (res.stdout, res.stderr))
    assert "JS-UNIT-OK" in res.stdout
