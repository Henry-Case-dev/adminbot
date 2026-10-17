# -*- coding: utf-8 -*-
"""W5 evidence collector: прогоны → plans/features/soul-1/evidence/w5/**.

Запуск: py -3 tools/_soul1_w5_evidence.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "plans" / "features" / "soul-1" / "evidence" / "w5"
OUT.mkdir(parents=True, exist_ok=True)

PY = sys.executable
FOCUSED = [
    "tests/test_soul1_w5_observer_gates.py",
    "tests/test_soul1_w5_initiative_vitality.py",
]
PERIMETER = ("-k", "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or "
                   "glass or persona or prompt or registry or catalog")
NODE_GUARDS = [
    "tests/js/soul1_w5_initiative_panel_test.js",
    "tests/js/asap8_v63_w3_status_logs_test.js",
    "tests/js/asap8_v63_w3_modules_ui_test.js",
    "tests/js/app_methods_dup_keys_guard_test.js",
]


def run(cmd, timeout=3600):
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def write(name, text):
    (OUT / name).write_text(text, encoding="utf-8", newline="\n")
    print("wrote", name, len(text), "bytes")


def main() -> int:
    # 1) focused
    code, out = run([PY, "-m", "pytest", *FOCUSED, "-q", "-p", "no:randomly"])
    write("focused-tests.txt",
          "$ py -3 -m pytest %s -q -p no:randomly\n%s\nrc=%d\n"
          % (" ".join(FOCUSED), out.strip()[-2000:], code))
    focused_ok = code == 0

    # 2) node-сторожа
    lines = []
    js_ok = True
    for script in NODE_GUARDS:
        rc, out = run(["node", script], timeout=600)
        lines.append("$ node %s\nrc=%d\n%s" % (script, rc,
                                               out.strip()[-400:]))
        js_ok = js_ok and rc == 0
        rc2, out2 = run([PY, "-c", "import subprocess,sys; "
                         "sys.exit(0)"], timeout=60)
        del rc2, out2
    write("js-guards.txt", "\n\n".join(lines) + "\n")

    # 3) каталог: F8 --check + reissue-скрипт (идемпотентность)
    rc_gen, out_gen = run([PY, "tools/gen_param_registry_round1025.py",
                           "--check"], timeout=600)
    rc_re, out_re = run([PY, "tools/_soul1_w5_reissue_f8.py"], timeout=600)
    write("catalog-reissue.txt",
          "$ py -3 tools/gen_param_registry_round1025.py --check\n%s\nrc=%d\n\n"
          "$ py -3 tools/_soul1_w5_reissue_f8.py   (идемпотентный повтор)\n"
          "%s\nrc=%d\n" % (out_gen.strip(), rc_gen, out_re.strip()[-1200:],
                           rc_re))
    catalog_ok = rc_gen == 0 and rc_re == 0

    # 4) периметр
    rc_per, out_per = run([PY, "-m", "pytest", *PERIMETER, "-q"], timeout=3600)
    write("perimeter.txt",
          "$ py -3 -m pytest %s -q\n%s\nrc=%d\n"
          % (" ".join(PERIMETER), out_per.strip()[-1500:], rc_per))
    perimeter_ok = rc_per == 0

    print(json.dumps({"focused": focused_ok, "js": js_ok,
                      "catalog": catalog_ok, "perimeter": perimeter_ok},
                     ensure_ascii=False))
    return 0 if all((focused_ok, js_ok, catalog_ok, perimeter_ok)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
