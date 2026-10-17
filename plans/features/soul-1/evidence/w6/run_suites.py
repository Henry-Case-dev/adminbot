#!/usr/bin/env python
"""SOUL-1 / W6 — сводка прогонов (фиксируется как evidence).

Запускается вручную после прогона харнесса и сьютов: собирает в один файл
команды и их результаты (без пересказа — только факты запуска).
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent / "glass-and-ui-suites.txt"
PY = str(REPO / ".venv" / "Scripts" / "python.exe")

COMMANDS = [
    ("node tests/js/glass_probe_test.js", ["node", "tests/js/glass_probe_test.js"]),
    ("node tests/js/round1025_design_tokens_test.js",
     ["node", "tests/js/round1025_design_tokens_test.js"]),
    ("node tests/js/routing_test.js", ["node", "tests/js/routing_test.js"]),
    ("node tests/js/round1025_ia_routing_test.js",
     ["node", "tests/js/round1025_ia_routing_test.js"]),
    ("node tests/js/vue_mount_test.js", ["node", "tests/js/vue_mount_test.js"]),
    ("node tests/js/asap8_w2_shell_mobile_nav_test.js",
     ["node", "tests/js/asap8_w2_shell_mobile_nav_test.js"]),
    ("py tools/gen_param_registry_round1025.py --check",
     [PY, "tools/gen_param_registry_round1025.py", "--check"]),
    ("pytest tests/test_soul1_w6_speech_ui.py",
     [PY, "-m", "pytest", "tests/test_soul1_w6_speech_ui.py", "-q"]),
    ("pytest IA/веб-маркеры",
     [PY, "-m", "pytest", "tests/test_ia_inventory_round1025.py",
      "tests/test_webapp_f5_round1025.py", "tests/test_webapp_round1014_ui.py",
      "tests/test_webapp_f11_round1025.py", "tests/test_webapp_teststand_guard.py",
      "tests/test_round1025_f8_registry.py", "-q"]),
    ("UI e2e shell (asap8-v6.3)",
     [PY, "tools/ui_asap8_w2_shell_e2e.py"]),
    ("UI e2e fullscreen (asap8-v6.3)",
     [PY, "tools/ui_asap8_w2_fullscreen_e2e.py"]),
]


def main() -> int:
    lines = ["SOUL-1 W6 — прогоны (кандидат: рабочее дерево без коммита)", ""]
    with OUT.open("w", encoding="utf-8") as fh:
        for label, cmd in COMMANDS:
            proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True,
                                  text=True, encoding="utf-8", errors="replace")
            tail = [row for row in (proc.stdout or "").strip().splitlines()[-6:]
                    if row.strip()]
            errtail = [row for row in (proc.stderr or "").strip().splitlines()[-4:]
                       if row.strip()]
            fh.write("$ %s\n" % label)
            fh.write("exit=%d\n" % proc.returncode)
            for row in tail:
                fh.write("    %s\n" % row)
            if proc.returncode != 0:
                for row in errtail:
                    fh.write("    stderr: %s\n" % row)
            fh.write("\n")
            fh.flush()
            print(label, "exit=", proc.returncode, "|", tail[-1] if tail else
                  (errtail[-1] if errtail else ""))
            if proc.returncode != 0:
                lines.append("FAIL: %s" % label)
    print("\n".join(lines))
    return 1 if len(lines) > 2 else 0


if __name__ == "__main__":
    raise SystemExit(main())
