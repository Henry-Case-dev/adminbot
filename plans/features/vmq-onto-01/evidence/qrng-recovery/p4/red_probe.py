# -*- coding: utf-8 -*-
"""QRNG P4 — RED-доказательство на базе `6cf4c32c` (до реализации UI).

Копирует ТОЛЬКО web/app.js + web/index.html из базового коммита и прогоняет
новый JS-тест P4 (`tests/js/qrng_p4_random_ui_test.js`) в изолированном temp-
дереве. Ничего в рабочем дереве не меняется.

Дополнительно фиксирует три факта базы:
  * config-вкладки mod_random нет;
  * keys_random всё ещё на llm_providers;
  * старая подсказка «зачисляет полученную партию в запас» присутствует.

Запуск: .venv\\Scripts\\python.exe
        plans/features/vmq-onto-01/evidence/qrng-recovery/p4/red_probe.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[6]
BASE = os.environ.get("QRNG_P4_RED_BASE", "6cf4c32c")
TEST = ROOT / "tests" / "js" / "qrng_p4_random_ui_test.js"

tmp = Path(tempfile.mkdtemp(prefix="qrng_p4_red_"))
try:
    (tmp / "web").mkdir(parents=True)
    (tmp / "tests" / "js").mkdir(parents=True)
    for rel in ("web/app.js", "web/index.html"):
        data = subprocess.check_output(
            ["git", "show", "%s:%s" % (BASE, rel)], cwd=str(ROOT))
        (tmp / rel).write_bytes(data)
    shutil.copy2(TEST, tmp / "tests" / "js" / TEST.name)

    app = (tmp / "web" / "app.js").read_text(encoding="utf-8")
    index = (tmp / "web" / "index.html").read_text(encoding="utf-8")
    tabs_start = app.index("var TABS = [")
    tabs_block = app[tabs_start:app.index("\n  ];", tabs_start)]
    llm_start = tabs_block.index("{ id: 'llm_providers'")
    next_tab = tabs_block.index("{ id: '", llm_start + 1)
    llm_block = tabs_block[llm_start:next_tab]
    facts = {
        "mod_random_config_tab_absent": (
            "{ id: 'mod_random', icon:" not in tabs_block),
        "keys_random_on_llm": "keys_random" in llm_block,
        "old_accrual_hint_present": (
            "зачисляет полученную партию в запас" in index),
    }

    res = subprocess.run(["node", str(tmp / "tests" / "js" / TEST.name)],
                         cwd=str(tmp), capture_output=True, text=True,
                         timeout=120)
    first = (res.stderr or res.stdout or "").strip().splitlines()
    assertion = next(
        (ln for ln in first if ln.strip().startswith("AssertionError")), "")
    report = {
        "base": BASE,
        "node_test_exit": res.returncode,
        "node_test_failed_as_expected": res.returncode != 0,
        "node_first_assertion": assertion.strip(),
        "base_facts": facts,
        "ok": (res.returncode != 0) and all(facts.values()),
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    out = os.environ.get("QRNG_P4_RED_OUT")
    if out:
        Path(out).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    sys.exit(0 if report["ok"] else 1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
