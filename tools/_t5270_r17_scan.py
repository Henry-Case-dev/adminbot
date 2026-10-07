# -*- coding: utf-8 -*-
"""T-5270: R17-скан секретов по дельте worktree (services/web/tests/tools)."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),                     # OpenAI-style
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),              # Slack
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),                       # GitHub PAT
    re.compile(r"AIza[A-Za-z0-9_\-]{30,}"),                    # Google
    re.compile(r"bot\d{6,}:[A-Za-z0-9_\-]{30,}"),              # TG bot token
    re.compile(
        r"(?:password|passwd|secret|api_key|apikey|token)\s*=\s*"
        r"[\"'][^\"']{8,}[\"']", re.IGNORECASE),               # literal assign
    re.compile(
        r"postgres(?:ql)?://[^\s\"']*:[^\s\"'*@]+@"),          # DB URL creds
]

out = subprocess.run(
    ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
    text=True, encoding="utf-8").stdout
files = []
for line in out.splitlines():
    m = re.match(r"^\s*(?:M|\?\?)\s+((?:services|web|tests|tools)/\S+)$", line)
    if m:
        files.append(m.group(1))

hits = []
checked = 0
for rel in files:
    p = ROOT / rel
    if not p.is_file():
        continue
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    checked += 1
    for i, line in enumerate(text.splitlines(), 1):
        for pat in PATTERNS:
            if pat.search(line):
                hits.append(f"{rel}:{i}")

print(f"delta files checked: {checked}")
print(f"SECRET_HITS={len(hits)}")
for h in hits:
    print("HIT", h)
sys.exit(1 if hits else 0)
