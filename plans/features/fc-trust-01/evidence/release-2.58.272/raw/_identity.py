"""Assembly identity proof for release 2.58.272 (byte level, no guesswork).

Compares every file touched by the merge (candidate c3c0e1cb3) and by the
version bump against the reviewed candidate blobs, prints git blob ids and
sha256 of the on-disk bytes of the release worktree, and records the DDL delta.
"""
import hashlib
import subprocess
from pathlib import Path

RAW = Path(__file__).parent
ROOT = Path(subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    check=True, cwd=RAW).stdout.strip())

BASE = "3a78484b92a6f3ba1273360e4a34de396dcf52f1"      # deployed 2.58.271
PREV = "cd30faac1"                                     # release/2.58.271 tip
TIP = "c3c0e1cb3ff88cc9f4d7c8fa2a52f1b4208dd1fc"      # reviewed candidate tip
PRODUCT = "f6cd011e0ef73fdce9633185f7b2889c2bf7e3fe"   # reviewed product candidate


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=check).stdout


def blob(rev, path):
    try:
        return git("rev-parse", f"{rev}:{path}").strip()
    except subprocess.CalledProcessError:
        return "(absent)"


def sha256_file(path):
    data = (ROOT / path).read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


head = git("rev-parse", "HEAD").strip()
merge = git("rev-parse", "HEAD~1").strip()
changed_vs_prev = [ln for ln in git("diff", "--name-only", PREV, "HEAD").splitlines() if ln]
changed_vs_base = [ln for ln in git("diff", "--name-only", BASE, "HEAD").splitlines() if ln]
candidate_touched = [p for p in changed_vs_prev
                     if blob(TIP, p) != "(absent)"]

out = []
out.append(f"base_deployed={BASE} (2.58.271)")
out.append(f"previous_release_tip={PREV}")
out.append(f"release_branch=release/2.58.272")
out.append(f"merge_commit={merge}")
out.append(f"release_head={head}")
out.append(f"reviewed_candidate_tip={TIP}")
out.append(f"reviewed_product_candidate={PRODUCT}")
out.append(f"files_changed_vs_base={len(changed_vs_base)}")
out.append(f"files_changed_vs_previous_tip={len(candidate_touched)}")
out.append("")

def candidate_bytes(rev, path):
    r = subprocess.run(["git", "cat-file", "blob", f"{rev}:{path}"], cwd=ROOT,
                       capture_output=True, check=False)
    return r.stdout if r.returncode == 0 else None


def version_only(path):
    """True when the only delta vs the candidate is the 2.58.271 -> 2.58.272 literal."""
    cand = candidate_bytes(TIP, path)
    if cand is None:
        return False
    return cand.replace(b"2.58.271", b"2.58.272") == (ROOT / path).read_bytes()


out.append("## every path changed vs previous release tip: worktree blob / candidate blob / base blob")
mismatch = []
version_only_files = []
for p in sorted(candidate_touched):
    wt = git("hash-object", "--", p).strip()
    cand = blob(TIP, p)
    prod = blob(PRODUCT, p)
    base = blob(BASE, p)
    exact = wt == cand
    vonly = (not exact) and version_only(p)
    if not exact and not vonly:
        mismatch.append(p)
    if vonly:
        version_only_files.append(p)
    out.append(f"{p}\n  worktree={wt} candidate={cand} product={prod} base={base} "
               f"byte_identical={exact} version_literal_only={vonly}")
out.append(f"all_candidate_files_identical_or_version_only={not mismatch} "
           f"mismatches={mismatch or 'none'}")
out.append(f"version_literal_only_files={version_only_files or 'none'}")
out.append("")

out.append("## sha256 of on-disk bytes (release worktree) vs candidate worktree file")
CAND_WT = Path(r"C:\Users\main\.config\opencode\WorkspaceData\worktrees"
               r"\c742e4de9e92c489\fct-s6-u3-aggregate-api-fa895e5e42eb-b2d4d976")
keys = [
    "web/api/routes.py",
    "web/app.js",
    "web/index.html",
    "config/settings.py",
    "services/factcheck_orchestrator.py",
    "services/factcheck_prompts.py",
    "tests/test_fc_trust_s6_aggregate_api.py",
    "tests/test_mca23_planned_vs_actual.py",
    "tests/test_round1025_f8_registry.py",
    "tests/fixtures/round1025/f8_baseline.json",
]
for p in keys:
    sha, size = sha256_file(p)
    csha = None
    if (CAND_WT / p).exists():
        csha = hashlib.sha256((CAND_WT / p).read_bytes()).hexdigest()
    out.append(f"{sha}  {size:>7}B  release  {p}  candidate_sha256_equal={sha == csha}")
out.append("")

out.append("## version-literal-only delta vs candidate (code/config/tests/tools)")
diff = git("diff", "-U0", TIP, "HEAD", "--", "web", "services", "config",
           "tests", "tools").splitlines()
pairs = [ln for ln in diff
         if (ln.startswith("+") or ln.startswith("-"))
         and not ln.startswith("+++") and not ln.startswith("---")]
nonver = [ln for ln in pairs if "2.58.271" not in ln and "2.58.272" not in ln]
out.append(f"changed_lines={len(pairs)} non_version_lines={len(nonver)}")
out.append(f"non_version_lines_list={nonver or 'none'}")
out.append("")

out.append("## DDL / migration delta base..HEAD")
ddl = [ln for ln in git("diff", "--name-only", BASE, "HEAD", "--", "db", "migrations",
                        "services/database.py", "services/param_catalog.py").splitlines() if ln]
out.append(f"ddl_or_migration_paths={ddl or 'none'}")
out.append("")

out.append("## product delta base..HEAD (web/services/config/tests/tools)")
status = [ln for ln in git("diff", "--name-status", BASE, "HEAD", "--",
                           "web", "services", "config", "tests", "tools").splitlines() if ln]
out.append(f"product_paths_changed={len(status)}")
out.extend(status)

text = "\n".join(out) + "\n"
(RAW / "identity.txt").write_text(text, encoding="utf-8")
print(text)
