# -*- coding: utf-8 -*-
"""ASAP-3.1 rework round 1: пересчёт Working-Tree-Hash по рецепту ревью
(§binding): SHA-256 UTF-8 манифеста `"<path> <sha256(content)>"` по всем
release-scope путям (tracked-modified + untracked), отсортированным, + "\\n".
Исключения: review-артефакты, чужой WIP (mca-04b/окружение), сам манифест.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE = {
    "node_modules", "package.json", "package-lock.json", ".playwright-mcp",
    "plans/features/mca-04b-dossier-rebuild",
    "plans/metrics.md", "plans/workflow_state.md",
    "plans/features/mca-asap31-auto-budgets-capacity-react/review.md",
    "plans/reports/asap31_wth_manifest_944f3e4e.txt",
}


def excluded(path: str) -> bool:
    for rule in EXCLUDE:
        if path == rule or path.startswith(rule + "/"):
            return True
    return False


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


tracked = subprocess.run(
    ["git", "diff", "--name-only"], cwd=str(ROOT), capture_output=True,
    text=True, encoding="utf-8", errors="replace").stdout.splitlines()
untracked = subprocess.run(
    ["git", "ls-files", "--others", "--exclude-standard"], cwd=str(ROOT),
    capture_output=True, text=True, encoding="utf-8",
    errors="replace").stdout.splitlines()

rows = []
skipped = []
for rel in sorted(set(tracked) | set(untracked)):
    rel_norm = rel.replace("\\", "/")
    if excluded(rel_norm):
        skipped.append(rel_norm)
        continue
    p = ROOT / rel_norm
    if not p.is_file():
        skipped.append(rel_norm + " [missing]")
        continue
    rows.append((rel_norm, sha(p.read_bytes())))

manifest = "".join(f"{path} {digest}\n" for path, digest in rows)
wth = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
out = ROOT / "plans" / "reports" / "asap31_wth_manifest_rework1.txt"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(manifest, encoding="utf-8")
print("files:", len(rows), "skipped:", len(skipped))
print("WTH-rework1:", wth)
print("manifest:", out.relative_to(ROOT))
