"""Committed-tree byte identity for release 2.58.269 (HEAD, not index)."""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
OUT = Path(__file__).with_name("identity-committed.txt")
CAND = "fa3cb0391f53728d1b64961b34d49cf8eee9174e"
BASE = "e46aa0696"
FILES = [
    "services/database.py",
    "services/temporal_factcheck.py",
    "services/factcheck_orchestrator.py",
    "services/factcheck_service.py",
    "handlers/factcheck.py",
    "tests/test_fc_trust_s6_run_link.py",
    "tests/test_t5150_startup_migrations_round1046.py",
]


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=check).stdout


head = git("rev-parse", "HEAD").strip()
lines = [f"head={head}"]
for rel in FILES:
    head_blob = git("rev-parse", f"HEAD:{rel}").strip()
    cand_blob = git("rev-parse", f"{CAND}:{rel}").strip()
    committed = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT,
                               capture_output=True, check=True).stdout
    worktree = (ROOT / rel).read_bytes()
    lines.append(
        f"{rel}\n  head_blob={head_blob}\n  candidate_blob={cand_blob}\n"
        f"  match_candidate={head_blob == cand_blob}\n"
        f"  committed_bytes_equal_worktree={committed == worktree}\n"
        f"  sha256={hashlib.sha256(committed).hexdigest()}")

prompts = subprocess.run(["git", "show", f"HEAD:services/factcheck_prompts.py"],
                         cwd=ROOT, capture_output=True, check=True).stdout
base_prompts = subprocess.run(["git", "show", f"{BASE}:services/factcheck_prompts.py"],
                              cwd=ROOT, capture_output=True, check=True).stdout
lines.append(
    "services/factcheck_prompts.py\n  head_blob="
    + git("rev-parse", "HEAD:services/factcheck_prompts.py").strip()
    + f"\n  sha256={hashlib.sha256(prompts).hexdigest()}\n"
    + f"  unchanged_vs_base={prompts == base_prompts}")

app_version = [ln for ln in git("show", "HEAD:config/settings.py").splitlines()
               if ln.startswith("APP_VERSION")]
lines.append(f"app_version_lines={app_version}")
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
