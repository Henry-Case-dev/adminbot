"""Byte-identity of reviewed product/test files (release 2.58.269 assembly, S6-U1)."""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
CAND = "fa3cb0391f53728d1b64961b34d49cf8eee9174e"
TIP = "589269b04"
BASE = "e46aa0696"
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
FILES = PRODUCT + TESTS
OUT = Path(__file__).with_name("identity.txt")


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=check).stdout


lines = []
for rel in FILES:
    data = (ROOT / rel).read_bytes()
    idx = git("hash-object", "--", rel).strip()
    cand = git("rev-parse", f"{CAND}:{rel}").strip()
    tip_blob = git("rev-parse", f"{TIP}:{rel}").strip()
    base_res = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{BASE}:{rel}"],
                              cwd=ROOT, capture_output=True, text=True)
    base = base_res.stdout.strip() if base_res.returncode == 0 else "(absent)"
    plain = hashlib.sha256(data).hexdigest()
    cand_bytes = subprocess.run(["git", "show", f"{CAND}:{rel}"], cwd=ROOT,
                                capture_output=True, check=True).stdout
    crlf = data.count(b"\r\n")
    lines.append(
        f"{rel}\n  idx={idx}\n  candidate={cand}\n  tip={tip_blob}\n"
        f"  base={base or '(absent)'}\n  match_candidate={idx == cand}\n"
        f"  match_tip={idx == tip_blob}\n  bytes_equal_candidate={data == cand_bytes}\n"
        f"  sha256={plain}\n  crlf={crlf} total_lf={data.count(bytes([10]))}")

# prompts canon unchanged
prompts = (ROOT / "services/factcheck_prompts.py").read_bytes()
prompts_sha = hashlib.sha256(prompts).hexdigest()
cand_prompts = git("rev-parse", "fa3cb0391:services/factcheck_prompts.py").strip()
head_prompts = git("rev-parse", f"{BASE}:services/factcheck_prompts.py").strip()
lines.append(
    f"services/factcheck_prompts.py\n  sha256={prompts_sha}\n"
    f"  canon_4cd1e893={prompts_sha.startswith('4cd1e893d8c5fed8566ed242af1b1c54d90da91d71bd6dd7b782f1415dde1bb4')}\n"
    f"  candidate_blob={cand_prompts}\n  base_blob={head_prompts}\n"
    f"  unchanged={cand_prompts == head_prompts}")

# DDL scope: exactly services/database.py touched, one constant bumped
ddl = git("diff", "--name-only", BASE, "--", "services/database.py", "migrations",
          "services/param_catalog.py").strip()
lines.append(f"ddl_files_changed={ddl.split() if ddl else '(none)'}")
db_text = (ROOT / "services/database.py").read_text(encoding="utf-8")
vers = sorted({int(tok) for tok in __import__("re").findall(
    r"_SCHEMA_VERSION_[A-Z0-9_]+ = (\d+)", db_text)})
lines.append(f"schema_version_constants={vers} max={max(vers)}")

stat = git("diff", "--stat", BASE).strip()
lines.append("git diff --stat vs base:\n" + stat)

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
