"""EVOL-032 / CONTRACT 2 — тонирование стекла по здоровью.

CONTRACT: соответствие state→заливка и текст статуса.
REGRESSION: соседняя карточка не наследует красный; стекло/полигоны не изменены.
"""
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _root() -> Path:
    return ROOT


PROTECTED = (
    "web/static/glass.js",
    "web/static/polygon-background.js",
    "web/static/aurora-flow.js",
    "web/static/vendor/liquidglass.core.0.5.3.min.js",
    "web/static/vendor/liquidglass.core.0.5.3.css",
)


def _git_blob(rel: str) -> bytes:
    res = subprocess.run(
        ["git", "show", "HEAD:" + rel],
        cwd=ROOT, capture_output=True, timeout=30,
    )
    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
    return res.stdout


def test_protected_optics_zero_diff_and_same_hash():
    """Защищённая оптика обязана остаться байт-в-байт HEAD (не «похоже»)."""
    for rel in PROTECTED:
        head = _git_blob(rel)
        disk = (ROOT / rel).read_bytes()
        assert hashlib.sha256(disk).hexdigest() == hashlib.sha256(head).hexdigest(), \
            "%s differs from HEAD: %s" % (rel, hashlib.sha256(disk).hexdigest())
        diff = subprocess.run(
            ["git", "diff", "HEAD", "--", rel],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        assert diff.returncode == 0, diff.stderr
        assert diff.stdout == "", "%s changed:\n%s" % (rel, diff.stdout)


def test_health_css_contract_and_tokens():
    css = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
    assert "--glass-bg: rgba(21, 27, 42, 0.5)" in css
    assert "rgba(91, 55, 67, 0.5)" in css
    assert "rgba(141, 74, 85, 0.5)" in css
    assert "--space-1: 4px" in css and "--space-3: 12px" in css
    assert "--space-4: 16px" in css and "--space-6: 24px" in css
    assert "--space-8: 32px" in css
    assert "--border-hairline: 1px" in css
    assert "--btn-h:" in css and "--toggle-hit:" in css
    block = css.split("EVOL-032 / CONTRACT 2 — тонирование", 1)[1]
    assert "transition: none" in block
    assert "prefers-reduced-motion: reduce" in block
    rules = block.split("*/", 1)[-1]
    assert "box-shadow" not in rules
    assert "backdrop-filter" not in rules


def test_status_markup_isolates_aggregate_card():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'class="card p-4 status-block"' in html
    assert 'data-health-material' not in html.split(
        'class="card p-4 status-block"', 1)[1].split("</div>", 1)[0]
    assert 'subsystem="bot"' in html
    assert 'subsystem="experience"' in html
    assert 'data-health-inline="heartbeat"' in html
    assert 'data-health-inline="memory"' in html
    assert 'data-health-inline="vision"' in html
    assert "aria-live=\"polite\"" in html


def test_evol032_js_unit():
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = ROOT / "tests" / "js" / "evol032_health_glass_test.js"
    res = subprocess.run(
        [node, str(script)],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stdout + "\n" + res.stderr
    assert "EVOL032-OK" in res.stdout
