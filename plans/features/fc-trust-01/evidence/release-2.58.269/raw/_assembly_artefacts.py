"""Assembly artefacts for release 2.58.269 (S6-U1 delta scope + review pin)."""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
OUTDIR = Path(__file__).parent
BASE = "e46aa0696"
CAND = "fa3cb0391f53728d1b64961b34d49cf8eee9174e"
PRODUCT = [
    "services/database.py",
    "services/temporal_factcheck.py",
    "services/factcheck_orchestrator.py",
    "services/factcheck_service.py",
    "handlers/factcheck.py",
]
TESTS = [
    "tests/test_fc_trust_s6_run_link.py",
    "tests/test_t5150_startup_migrations_round1046.py",
]
BUMP_COMMIT = "9c45a454c"
REVIEW_COMMIT = "7074a1e43"
REVIEW_PATH = ("plans/features/fc-trust-01/evidence/fct-s6-u1-2026-11-28/"
               "review-r1/review-r1.md")


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=check).stdout


bump_files = set(git("show", "--name-only", "--format=", BUMP_COMMIT).split())
changed = [ln for ln in git("diff", "--name-only", BASE).split() if ln]
outside = [f for f in changed if f not in PRODUCT + TESTS and f not in bump_files]
numstat = git("diff", "--numstat", BASE)
in_both = [f for f in changed if f in bump_files and f in PRODUCT + TESTS]

lines = [
    f"base={BASE}",
    f"candidate={CAND}",
    f"product_files_changed={len(PRODUCT)}",
    "product_files=" + ",".join(PRODUCT),
    f"test_files_changed={len(TESTS)}",
    "test_files=" + ",".join(TESTS),
    f"changed_files_total_vs_base={len(changed)}",
    f"changed_files={changed}",
    f"bump_touched_files={len(bump_files)}",
    f"outside_product_tests_and_bump_files={outside or '(none)'}",
    f"product_or_test_files_inside_bump_set={in_both or '(none)'}",
    "",
    "numstat_vs_base:",
    numstat.strip(),
]
(OUTDIR / "product-delta.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

diff = git("diff", BASE, CAND, "--", *PRODUCT, *TESTS)
(OUTDIR / "product-diff-full.txt").write_text(diff, encoding="utf-8", newline="")

stat = git("diff", "--stat", BASE)
(OUTDIR / "changed-files-preassembly.txt").write_text(
    stat + "\n\nname-status:\n" + git("diff", "--name-status", BASE), encoding="utf-8")

review = git("show", f"{REVIEW_COMMIT}:{REVIEW_PATH}", check=False)
sha = hashlib.sha256(review.encode()).hexdigest()
verdict = [ln for ln in review.splitlines() if ln.startswith("## VERDICT")]
(OUTDIR / "review-pin.txt").write_text(
    f"review_path={REVIEW_PATH}\nreview_commit={REVIEW_COMMIT}\nsha256={sha}\n"
    f"prefix_e48b2abd={sha.startswith('e48b2abd')}\nverdict={verdict}\n",
    encoding="utf-8")

print("\n".join(lines))
print("review_sha256=" + sha)
print("verdict=" + str(verdict))
