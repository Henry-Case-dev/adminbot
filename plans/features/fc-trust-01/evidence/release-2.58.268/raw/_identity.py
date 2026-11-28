"""Byte-identity of reviewed product files (release 2.58.268 assembly)."""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
CAND = "a0a34dcd32a3c55004c0f4c1f88cc9b2283391ae"
BASE = "9709b14af"
FILES = ["services/factcheck_service.py", "tests/test_fc_trust_s5_writer.py"]
OUT = Path(__file__).with_name("identity.txt")

lines = []
for rel in FILES:
    data = (ROOT / rel).read_bytes()
    idx = subprocess.run(["git", "hash-object", "--", rel], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.strip()
    cand = subprocess.run(["git", "rev-parse", f"{CAND}:{rel}"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    base_res = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{BASE}:{rel}"],
                              cwd=ROOT, capture_output=True, text=True)
    base = base_res.stdout.strip() if base_res.returncode == 0 else "(absent)"
    plain = hashlib.sha256(data).hexdigest()
    cand_bytes = subprocess.run(["git", "show", f"{CAND}:{rel}"], cwd=ROOT,
                               capture_output=True, check=True).stdout
    lines.append(
        f"{rel}\n  idx={idx}\n  candidate={cand}\n  base={base or '(absent)'}\n"
        f"  match={idx == cand}\n  bytes_equal={data == cand_bytes}\n"
        f"  sha256={plain}\n  crlf={data.count(bytes([13, 10]))} lines={data.count(bytes([10]))}"
    )

prompts = (ROOT / "services/factcheck_prompts.py").read_bytes()
prompts_sha = hashlib.sha256(prompts).hexdigest()
cand_prompts = subprocess.run(["git", "rev-parse", f"{CAND}:services/factcheck_prompts.py"],
                              cwd=ROOT, capture_output=True, text=True).stdout.strip()
head_prompts = subprocess.run(["git", "rev-parse", f"HEAD:services/factcheck_prompts.py"],
                              cwd=ROOT, capture_output=True, text=True).stdout.strip()
lines.append(
    f"services/factcheck_prompts.py\n  sha256={prompts_sha}\n"
    f"  canon_4cd1e893={prompts_sha.startswith('4cd1e893d8c5fed8566ed242af1b1c54d90da91d71bd6dd7b782f1415dde1bb4')}\n"
    f"  candidate_blob={cand_prompts}\n  head_blob={head_prompts}\n  unchanged={cand_prompts == head_prompts}"
)

# DDL / migration check
ddl = subprocess.run(["git", "diff", "--name-only", BASE, "--", "services/database.py",
                      "migrations", "services/param_catalog.py"], cwd=ROOT,
                     capture_output=True, text=True, check=True).stdout.strip()
lines.append(f"migrations_or_db_py_changed={ddl.split() if ddl else '(none)'}")

# full diff vs base
stat = subprocess.run(["git", "diff", "--stat", BASE], cwd=ROOT,
                      capture_output=True, text=True, check=True).stdout.strip()
lines.append("git diff --stat vs base:\n" + stat)

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
