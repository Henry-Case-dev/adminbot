"""Assembly artefacts for release 2.58.268 (delta scope + review pin)."""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
OUTDIR = Path(__file__).parent
BASE = "9709b14af"
CAND = "a0a34dcd32a3c55004c0f4c1f88cc9b2283391ae"
PRODUCT = ["services/factcheck_service.py", "tests/test_fc_trust_s5_writer.py"]
BUMP_COMMIT = "7b835b838"


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=check).stdout


bump_files = set(git("show", "--name-only", "--format=", BUMP_COMMIT).split())
changed = [ln for ln in git("diff", "--name-only", BASE).split() if ln]
outside = [f for f in changed if f not in PRODUCT and f not in bump_files]
numstat = git("diff", "--numstat", BASE)
non_version = [f for f in changed
               if f in bump_files and f in PRODUCT]

lines = [
    f"base={BASE}",
    f"candidate={CAND}",
    f"product_files_changed={len(PRODUCT)}",
    "product_files=" + ",".join(PRODUCT),
    f"changed_files_total_vs_base={len(changed)}",
    f"bump_touched_files={len(bump_files)}",
    f"outside_product_and_bump_files={outside or '(none)'}",
    f"product_files_inside_bump_set={non_version or '(none)'}",
    "",
    "numstat_vs_base:",
    numstat.strip(),
]
(OUTDIR / "product-delta.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

# full product diff for the record
diff = git("diff", BASE, CAND, "--", *PRODUCT)
(OUTDIR / "product-diff-full.txt").write_text(diff, encoding="utf-8", newline="")

stat = git("diff", "--stat", BASE)
(OUTDIR / "changed-files-preassembly.txt").write_text(
    stat + "\n\nname-status:\n" + git("diff", "--name-status", BASE), encoding="utf-8")

# review pin (file lives on master line; verified from the canonical repo object store)
review = git("show", "62cce15ed:plans/features/fc-trust-01/evidence/fct-s5-u1-2026-11-28/review-r1/review-r1.md",
             check=False)
sha = hashlib.sha256(review.encode()).hexdigest()
(OUTDIR / "review-pin.txt").write_text(
    f"review_path=plans/features/fc-trust-01/evidence/fct-s5-u1-2026-11-28/review-r1/review-r1.md\n"
    f"review_commit=62cce15ed\nsha256={sha}\nprefix_fdfd805c={sha.startswith('fdfd805c')}\n"
    f"verdict={[l for l in review.splitlines() if l.startswith('## VERDICT')]}\n", encoding="utf-8")

print("\n".join(lines))
print("review_sha256=" + sha)
