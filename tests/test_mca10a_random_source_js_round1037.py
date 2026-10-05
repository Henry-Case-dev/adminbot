"""MCA-10a (round 10.37, ADR-1028-14 D8/D9) — JS-проверки UI (T-4977/T-4979).

Реальный node-прогон (не grep): computed `randomSource` (PRNG → без
quantum-статуса), «Проверить подключение» (draft только в POST-body, маска не
уходит, busy-гейт), клиентское раскрытие последних решений, wiring index.html
и зеркало TABS. Пропускается, если node недоступен.
"""
import os
import shutil
import subprocess

import pytest

SCRIPT = os.path.join("tests", "js", "round1037_random_source_test.js")


def test_js_unit_mca10a_random_source():
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    res = subprocess.run([node, SCRIPT], capture_output=True, text=True,
                         timeout=60, cwd=root)
    assert res.returncode == 0, (
        "MCA10a JS-UNIT провалился:\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (res.stdout, res.stderr))
    assert "MCA10A-RANDOM-OK" in res.stdout
