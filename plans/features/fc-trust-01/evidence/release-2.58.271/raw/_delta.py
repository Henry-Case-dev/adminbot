"""Release 2.58.271 assembly: byte identity + product delta proof.

Base 438ad790e (2.58.270), candidate 936bc31a7 (FC-TRUST S6-U2 aggregates).
Writes product-delta.txt / product-diff-stat.txt / product-diff-full.txt /
identity.txt into the raw/ directory next to this script.
"""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    check=True, cwd=Path(__file__).parent).stdout.strip())
RAW = Path(__file__).parent
BASE = "438ad790e"
CANDIDATE = "936bc31a76971e47e7f101bcddc1e7656d7c7270"
PRODUCT_PATHS = ["services/temporal_factcheck.py", "tests/test_fc_trust_s6_aggregates.py"]
GUARD_PATHS = ["web/api/routes.py", "web/app.js", "services/factcheck_prompts.py"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout


def sha256(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def blob(rev, path):
    proc = subprocess.run(["git", "rev-parse", f"{rev}:{path}"], cwd=ROOT,
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else "absent"


def disk_blob(path):
    return git("hash-object", path).strip()


lines = []
lines.append(f"head_branch={git('rev-parse', '--abbrev-ref', 'HEAD').strip()}")
lines.append(f"head={git('rev-parse', 'HEAD').strip()}")
lines.append(f"base={git('rev-parse', BASE + '^{commit}').strip()} ({BASE})")
lines.append(f"candidate={CANDIDATE}")
lines.append(f"base_ancestor_of_head={subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], cwd=ROOT).returncode == 0}")
lines.append("")

lines.append("## product files: worktree blob == candidate blob (byte identity)")
identity_ok = True
for path in PRODUCT_PATHS:
    wt = disk_blob(path)
    cand = blob(CANDIDATE, path)
    base = blob(BASE, path)
    ok = wt == cand
    identity_ok = identity_ok and ok
    lines.append(f"{path}: worktree_blob={wt} candidate_blob={cand} "
                 f"base_blob={base} identical_to_candidate={ok} sha256={sha256(path)}")
lines.append(f"all_product_files_byte_identical_to_candidate={identity_ok}")
lines.append("")

lines.append("## guard files: unchanged vs base 438ad790e")
guards_ok = True
for path in GUARD_PATHS:
    wt = disk_blob(path)
    base = blob(BASE, path)
    ok = wt == base
    guards_ok = guards_ok and ok
    lines.append(f"{path}: worktree_blob={wt} base_blob={base} unchanged={ok} "
                 f"sha256={sha256(path)}")
lines.append(f"all_guards_unchanged={guards_ok}")
lines.append("")

changed = git("diff", "--name-status", BASE, "--", ".").strip().splitlines()
product_changed = [ln for ln in changed if not ln.endswith("evidence/release-2.58.271")]
lines.append(f"changed_paths_total={len(changed)}")
for ln in changed:
    lines.append(f"  {ln}")
lines.append(f"changed_paths_excluding_this_evidence={len(product_changed)}")
lines.append("")

ddl_touched = [ln for ln in changed if any(k in ln for k in ("migrat", "schema", ".sql"))]
lines.append(f"ddl_or_migration_paths={ddl_touched or 'none'}")

(RAW / "identity.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

stat = git("diff", "--stat", BASE, "--", ".").strip()
(RAW / "product-diff-stat.txt").write_text(stat + "\n", encoding="utf-8")

full = git("diff", BASE, "--", *PRODUCT_PATHS)
(RAW / "product-diff-full.txt").write_text(full, encoding="utf-8")

prod_delta = []
prod_delta.append(f"base={BASE} candidate={CANDIDATE}")
prod_delta.append(f"product_paths_changed={len(product_changed)}")
for ln in product_changed:
    prod_delta.append(f"  {ln}")
prod_delta.append("protection_guards: "
                  + ", ".join(f"{p} sha256={sha256(p)}" for p in GUARD_PATHS))
(RAW / "product-delta.txt").write_text("\n".join(prod_delta) + "\n", encoding="utf-8")

print("\n".join(lines))
print("---")
print(stat)
