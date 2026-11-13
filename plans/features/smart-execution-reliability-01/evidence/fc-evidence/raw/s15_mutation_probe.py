"""S15 mutation-проверки: тесты обязаны краснеть при возврате старого cap.

Каждая мутация — точечная правка services/factcheck_service.py, прогон
`tests/test_factcheck_evidence_delivery.py`, откат. Пишет diff+вывод в
raw/mutation-<name>.{diff,txt} и сводку в JSON.

    python plans/features/smart-execution-reliability-01/evidence/\
fc-evidence/raw/s15_mutation_probe.py <raw-dir>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.getcwd()
SERVICE = os.path.join(ROOT, "services", "factcheck_service.py")
TEST = "tests/test_factcheck_evidence_delivery.py"

MUTATIONS = [
    {
        "name": "row-cap-20",
        "why": "прежний скрытый потолок 20 строк",
        "old": "    max_rows = len(refs) if refs else _temporal_max_evidence()",
        "new": "    max_rows = min(len(refs), 20) if refs else "
               "_temporal_max_evidence()",
    },
    {
        "name": "support-cut-1200",
        "why": "прежняя обрезка support до 1200 символов",
        "old": '            "support": support,',
        "new": '            "support": support[:1200],',
    },
    {
        "name": "fallback-ignores-route",
        "why": "fallback без recompose под фактическую ёмкость",
        "old": "            if fallback_route is None or not delivery.all_rows:",
        "new": "            if True:",
    },
    {
        "name": "silent-budget-no-note",
        "why": "остановка поиска бюджетом без запрета «доказательств нет»",
        "old": "    if not exhausted and skipped <= 0:",
        "new": "    if True:",
    },
    {
        "name": "capacity-16384",
        "why": "прежнее «универсальное окно» 16384 вместо резолвера",
        "old": "        budget = int(mc.evidence_window_for_tokens(window))",
        "new": "        budget = int(mc.evidence_window_for_tokens(16384))",
    },
]


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else "."
    original = open(SERVICE, encoding="utf-8", newline="").read()
    summary = []
    try:
        for mut in MUTATIONS:
            assert mut["old"] in original, mut["name"]
            open(SERVICE, "w", encoding="utf-8", newline="").write(
                original.replace(mut["old"], mut["new"], 1))
            diff = run(["git", "diff", "-U3", "--", "services/factcheck_service.py"])
            with open(os.path.join(raw, f"mutation-{mut['name']}.diff"),
                      "w", encoding="utf-8", newline="\n") as fh:
                fh.write(diff.stdout)
            proc = run([sys.executable, "-m", "pytest", "-q",
                        "-p", "no:cacheprovider", TEST])
            out = proc.stdout + proc.stderr
            with open(os.path.join(raw, f"mutation-{mut['name']}.txt"),
                      "w", encoding="utf-8", newline="\n") as fh:
                fh.write(out)
            failed = [ln.split("::")[-1].split(" ")[0]
                      for ln in out.splitlines()
                      if ln.startswith("FAILED ")]
            summary.append({"name": mut["name"], "why": mut["why"],
                            "exit": proc.returncode, "failed": failed,
                            "failed_count": len(failed)})
            open(SERVICE, "w", encoding="utf-8", newline="").write(original)
    finally:
        open(SERVICE, "w", encoding="utf-8", newline="").write(original)
    with open(os.path.join(raw, "mutations-s15.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
