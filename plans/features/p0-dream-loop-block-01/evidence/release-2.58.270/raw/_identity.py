"""Byte identity: release worktree files vs reviewed candidate commits.

Compares (a) working-tree raw bytes, (b) index blob, (c) blob in the product
commit e30ae12bf, (d) blob in the candidate branch tip 028dcf637, and prints the
base blob for reference.
"""
import subprocess
from pathlib import Path

ROOT = Path(subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    check=True, cwd=Path(__file__).parent).stdout.strip())
OUT = Path(__file__).with_name("identity.txt")

BASE = "6d97c02d8"
PRODUCT = "e30ae12bf0a6fff5f7eac7bfaea400175dd55c52"
TIP = "028dcf637f7927231352e9b876dc1aa1ebde3852"

FILES = [
    "services/summary_memory.py",
    "tests/p0_dream_loop/test_no_event_loop_block.py",
]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def blob_at(rev: str, rel: str) -> str | None:
    r = subprocess.run(["git", "rev-parse", f"{rev}:{rel}"], cwd=ROOT,
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


lines = [f"release_worktree={ROOT}", f"base={BASE}", f"product={PRODUCT}",
         f"tip={TIP}", ""]

for rel in FILES:
    raw = (ROOT / rel).read_bytes()
    idx = blob_at(":0", rel)
    prod = blob_at(PRODUCT, rel)
    tip = blob_at(TIP, rel)
    base = blob_at(BASE, rel)
    prod_raw = subprocess.run(["git", "show", f"{PRODUCT}:{rel}"], cwd=ROOT,
                              capture_output=True, check=True).stdout
    lines.append(
        f"{rel}\n"
        f"  index_blob={idx}\n"
        f"  product_blob={prod}\n"
        f"  tip_blob={tip}\n"
        f"  base_blob={base or '(absent)'}\n"
        f"  worktree_sha256={__import__('hashlib').sha256(raw).hexdigest()}\n"
        f"  product_sha256="
        f"{__import__('hashlib').sha256(prod_raw).hexdigest()}\n"
        f"  index_eq_product={idx == prod}\n"
        f"  index_eq_tip={idx == tip}\n"
        f"  bytes_equal_product={raw == prod_raw}\n"
        f"  size={len(raw)}")
    lines.append("")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
