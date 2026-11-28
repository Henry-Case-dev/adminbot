"""Bind committed HEAD blob identity of the release product files to the reviewed candidate."""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
CAND = "a0a34dcd32a3c55004c0f4c1f88cc9b2283391ae"
FILES = ["services/factcheck_service.py", "tests/test_fc_trust_s5_writer.py",
         "services/factcheck_prompts.py"]
OUT = Path(__file__).with_name("identity-committed.txt")


def g(*a, check=True):
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, check=check)
    return r.stdout.decode("utf-8", "replace").strip() if check else r


head = g("rev-parse", "HEAD")
lines = [f"head={head}", f"candidate={CAND}"]
for rel in FILES:
    blob = g("rev-parse", f"HEAD:{rel}")
    cand_blob = g("rev-parse", f"{CAND}:{rel}")
    work = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
    committed_bytes = subprocess.run(["git", "cat-file", "blob", blob], cwd=ROOT,
                                     capture_output=True, check=True).stdout
    lines.append(
        f"{rel}: head_blob={blob} candidate_blob={cand_blob} "
        f"match={blob == cand_blob} worktree_sha256={work} "
        f"committed_bytes_equal_worktree={committed_bytes == (ROOT / rel).read_bytes()}"
    )
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
