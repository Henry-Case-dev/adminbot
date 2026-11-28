"""Release 2.58.266 assembly artefacts: changed files, full product diff, manifest dry-run."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
RAW = Path(__file__).parent
BASE = "55178d5bd"


def git(*args):
    return subprocess.run(("git",) + args, cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout


head = git("rev-parse", "HEAD").strip()
version = [ln.split('"')[1] for ln in (ROOT / "config/settings.py").read_text(
    encoding="utf-8").splitlines() if ln.startswith("APP_VERSION")][0]
dirty = git("status", "--porcelain", "--untracked-files=no").strip()

(RAW / "changed-files-preassembly.txt").write_text(
    f"base={BASE}\nhead={head}\nversion={version}\ndirty_tracked={bool(dirty)}\n"
    "--- name-status base..head:\n" + git("diff", "--name-status", BASE, "HEAD")
    + "--- stat:\n" + git("diff", "--stat", BASE, "HEAD"),
    encoding="utf-8")

product = ["services/factcheck_planner.py", "services/search_aggregator.py",
           "services/temporal_factcheck.py", "services/factcheck_orchestrator.py",
           "services/factcheck_service.py", "tests/test_fc_trust_s4_evidence.py"]
(RAW / "product-diff-full.txt").write_text(
    git("diff", BASE, "282151269852c57c916e8fd26f2bffd00747fad8", "--", *product),
    encoding="utf-8")

manifest = {
    "deployed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "deployed_sha": head,
    "deployer": "devops",
    "dirty_tracked": False,
    "effect": "deploy",
    "previous_sha": git("rev-parse", BASE).strip(),
    "previous_version": "2.58.265",
    "release_branch": "release/2.58.266",
    "schema": 1,
    "version": version,
}
(RAW / "manifest-dryrun.txt").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(manifest, sort_keys=True))
print("head:", head, "version:", version, "dirty:", bool(dirty))
