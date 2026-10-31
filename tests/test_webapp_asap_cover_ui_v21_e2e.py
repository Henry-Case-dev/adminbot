# -*- coding: utf-8 -*-
"""Живой Playwright-прогон P1/P2 UI-волны v2.1 (desktop 1280 + mobile 390 + 667).

Запускает `tools/ui_asap_cover_ui_v21_e2e.py` — настоящая разметка/JS/CSS на
детерминированных стабах API (секретов нет, в Telegram ничего не уходит).
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "ui_asap_cover_ui_v21_e2e.py"


def test_live_ui_v21_e2e():
    try:
        import playwright  # noqa: F401
    except Exception:  # noqa: BLE001
        pytest.skip("playwright не установлен в этом окружении")
    res = subprocess.run([sys.executable, str(TOOL)], cwd=str(ROOT),
                         capture_output=True, text=True, encoding="utf-8",
                         timeout=1800)
    assert res.returncode == 0, (res.stdout or "") + (res.stderr or "")
    assert "ASAP-UI-V21-OK" in res.stdout
