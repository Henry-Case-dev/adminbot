"""Product delta of the assembled release against the deployed base 6d97c02d8."""
import subprocess
from pathlib import Path

ROOT = Path(subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    check=True, cwd=Path(__file__).parent).stdout.strip())
OUT = Path(__file__).with_name("product-delta.txt")
BASE = "6d97c02d8"
BUMP = "3eafef83c"
PRODUCT = "344d6126b"

changed = subprocess.run(
    ["git", "diff", "--name-only", BASE, "HEAD"], cwd=ROOT,
    capture_output=True, text=True, check=True).stdout.split()
bump_files = set(subprocess.run(
    ["git", "show", "--name-only", "--format=", BUMP], cwd=ROOT,
    capture_output=True, text=True, check=True).stdout.split())
product_files = subprocess.run(
    ["git", "diff", "--name-only", BASE, PRODUCT], cwd=ROOT,
    capture_output=True, text=True, check=True).stdout.split()

evidence_prefix = "plans/features/p0-dream-loop-block-01/evidence/release-2.58.270/"
outside = [f for f in changed if f not in bump_files and f not in product_files
           and not f.startswith(evidence_prefix)]
evidence = [f for f in changed if f.startswith(evidence_prefix)]
services = [f for f in product_files if f.startswith("services/")]
tests = [f for f in product_files if f.startswith("tests/")]

numstat = subprocess.run(
    ["git", "diff", "--numstat", BASE, PRODUCT], cwd=ROOT,
    capture_output=True, text=True, check=True).stdout.strip()

ddl = subprocess.run(
    ["git", "diff", "--name-only", BASE, "HEAD", "--", "services/database.py",
     "services/param_catalog.py", "migrations"], cwd=ROOT, capture_output=True,
    text=True, check=True).stdout.split()

sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                     capture_output=True, text=True, check=True).stdout.strip()
dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                       capture_output=True, text=True, check=True).stdout.split()

lines = [
    f"head={sha}",
    f"base={BASE}",
    f"changed_files_total_vs_base={len(changed)}",
    f"product_files={product_files}",
    f"bump_touched_files={len(bump_files)}",
    f"evidence_files={len(evidence)}",
    f"outside_product_tests_bump_evidence={outside or '(none)'}",
    f"services_changed={services}",
    f"tests_changed={tests}",
    f"ddl_relevant_changed={ddl or '(none)'}",
    f"worktree_dirty_entries={len(dirty)}",
    "",
    "numstat(base..product):",
    numstat,
]
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
