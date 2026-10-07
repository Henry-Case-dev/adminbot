# -*- coding: utf-8 -*-
"""T-5270: финальный SHA256-манифест интегрированного кандидата ASAP 5."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

out = subprocess.run(
    ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
    text=True, encoding="utf-8").stdout
files = []
for line in out.splitlines():
    m = re.match(r"^\s*(?:M|\?\?)\s+(\S+)$", line)
    if m:
        files.append(m.group(1))

manifest = {}
for rel in sorted(files):
    p = ROOT / rel
    if not p.is_file():
        continue
    if "node_modules" in rel or rel.startswith("tools/_ui_") \
            or rel.endswith(".png") or rel.endswith(".log"):
        continue
    try:
        manifest[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        pass

dest = ROOT / "plans/features/asap5-final-fixes/t5270_candidate_hashes.json"
dest.write_text(
    json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
    encoding="utf-8")
print(f"manifest: {len(manifest)} files -> {dest.relative_to(ROOT)}")
