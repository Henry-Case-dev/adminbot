"""Committed-blob identity at the deploy HEAD: proves the evidence commits did not
change any product blob (assembly.md §1 sha256 must still match)."""
import subprocess
from pathlib import Path

RAW = Path(__file__).parent
ROOT = Path(subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    check=True, cwd=RAW).stdout.strip())


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


head = git("rev-parse", "HEAD")
files = [
    "web/api/routes.py", "web/app.js", "web/index.html",
    "config/settings.py", "services/factcheck_orchestrator.py",
    "services/factcheck_prompts.py", "tests/test_fc_trust_s6_aggregate_api.py",
    "tests/test_mca23_planned_vs_actual.py",
    "tests/test_round1025_f8_registry.py",
    "tests/fixtures/round1025/f8_baseline.json",
]
out = [f"head={head}", f"dirty_tracked={bool(git('status', '--porcelain', '--untracked-files=no'))}",
       f"branch={git('branch', '--show-current')}", ""]
for f in files:
    out.append(f"{git('rev-parse', f'HEAD:{f}')}  {f}")
out.append("")
out.append("evidence-only delta since assembly commit:")
out.append(git("diff", "--stat", "cb47e6cbd", "HEAD"))
text = "\n".join(out) + "\n"
(RAW / "identity-committed.txt").write_text(text, encoding="utf-8")
print(text)
