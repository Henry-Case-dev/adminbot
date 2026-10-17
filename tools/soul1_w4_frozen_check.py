"""W4 — проверка неприкосновенности замороженных артефактов и LF-инварианта.

1) polygon-фон, карта линзы (#lg-lens), токены --lg-* и glass-классы не
   изменились (сравнение с HEAD по счётчикам вхождений и по хэшам фрагментов);
2) web/index.html и web/app.js — LF-only (0 CRLF).

Запуск: `py -3 tools/soul1_w4_frozen_check.py`
Выход: `plans/features/soul-1/evidence/w4/frozen-assets.txt`
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = (REPO / "plans" / "features" / "soul-1" / "evidence" / "w4"
       / "frozen-assets.txt")

NEEDLES = (
    'id="lg-lens"',
    "lg-lens-map",
    "feDisplacementMap",
    "polygon-background.js",
    "--lg-tint-hero",
    "--lg-blur",
    "glass-card",
    "lg-lens",
)


def head_text(rel: str) -> str:
    proc = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(REPO),
                          capture_output=True)
    return proc.stdout.decode("utf-8", errors="replace")


def main() -> int:
    lines: list[str] = []
    ok = True
    for rel in ("web/index.html", "web/app.js", "web/static/app.css"):
        head = head_text(rel)
        current = (REPO / rel).read_text(encoding="utf-8")
        lines.append(f"== {rel}")
        lines.append(f"   HEAD sha256_12 {hashlib.sha256(head.encode()).hexdigest()[:12]}"
                     f" | current {hashlib.sha256(current.encode()).hexdigest()[:12]}")
        for needle in NEEDLES:
            before, after = head.count(needle), current.count(needle)
            status = "same" if before == after else "CHANGED"
            if before != after:
                ok = False
            lines.append(f"   {needle!r}: {before} -> {after} [{status}]")
    for rel in ("web/index.html", "web/app.js"):
        raw = (REPO / rel).read_bytes()
        crlf = raw.count(b"\r\n")
        if crlf:
            ok = False
        lines.append(f"== {rel}: CRLF={crlf} bytes={len(raw)}")
    report = "\n".join(lines)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(report + "\n", encoding="utf-8", newline="\n")
    print(report)
    print("FROZEN-ASSETS-OK" if ok else "FROZEN-ASSETS-CHANGED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
