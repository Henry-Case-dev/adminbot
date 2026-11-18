"""F-01 mutation probe (self-contained; run from repo root).

Applies one mutation at a time to services/mca_random_source.py, runs the
focused F-01 suite, restores the exact original bytes and verifies sha256.
No production access; no network; writes only its JSON result file.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
PRODUCT = ROOT / "services" / "mca_random_source.py"
TEST = "tests/test_qrng_f01_activation_batch_scope.py"
OUT = Path(__file__).with_name("mutations.json")

SCOPE_LINE = "        batch_sql, batch_params = self._batch_clause(batch_id)"
SCOPE_MUT = '        batch_sql, batch_params = "", ()  # MUT: scope removed'

CONFIRM_OLD = """        chunk = await self._store.reserve_chunk(
            1, config_fingerprint=self._current_fingerprint(),
            batch_id=str(batch_id))
        if not chunk:
            return False
        item = chunk[0]
"""
CONFIRM_FALLBACK = """        chunk = await self._store.reserve_chunk(
            1, config_fingerprint=self._current_fingerprint(),
            batch_id=str(batch_id))
        if not chunk:
            chunk = await self._store.reserve_chunk(
                1, config_fingerprint=self._current_fingerprint())
        if not chunk:
            return False
        item = chunk[0]
"""

GUARD_OLD = """        if str(item.batch_id) != str(batch_id):
            # Защита контракта: store обязан вернуть только запрошенную
            # партию; чужое значение не должно подтверждать активацию.
            return False
"""
GUARD_MUT = "        # MUT: contract guard removed\n"

ADAPTER_OLD = "            provider=item.provider, batch_id=item.batch_id,"
ADAPTER_MUT = "            provider=item.provider, batch_id=str(batch_id),"

MUTATIONS = [
    {
        "id": "F01-M1",
        "seam": "exact batch scope removed in RandomStore.reserve_chunk",
        "edits": [(SCOPE_LINE, SCOPE_MUT)],
    },
    {
        "id": "F01-M2",
        "seam": "silent fallback to unscoped reserve when target batch is empty",
        "edits": [(CONFIRM_OLD, CONFIRM_FALLBACK)],
    },
    {
        "id": "F01-M3",
        "seam": "original defect + forced journal attribution (scope removed, "
                 "guard removed, journal names requested batch)",
        "edits": [(SCOPE_LINE, SCOPE_MUT), (GUARD_OLD, GUARD_MUT),
                  (ADAPTER_OLD, ADAPTER_MUT)],
    },
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TEST, "-q", "--tb=no"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900)
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    summary = lines[-1] if lines else ""
    failed = [ln.split("::", 1)[-1].strip()
              for ln in lines if ln.startswith("FAILED ")]
    return {"returncode": proc.returncode, "summary": summary,
            "failed_node_ids": failed}


def main() -> int:
    original = PRODUCT.read_bytes()
    before = _sha256(original)
    results = []
    try:
        for mutation in MUTATIONS:
            text = original.decode("utf-8")
            for old, new in mutation["edits"]:
                count = text.count(old)
                if count != 1:
                    raise SystemExit(
                        f"{mutation['id']}: expected 1 match, got {count} "
                        f"for {old[:60]!r}")
                text = text.replace(old, new, 1)
            PRODUCT.write_bytes(text.encode("utf-8"))
            try:
                outcome = _run_tests()
            finally:
                PRODUCT.write_bytes(original)
            restored = _sha256(PRODUCT.read_bytes())
            outcome.update({
                "id": mutation["id"], "seam": mutation["seam"],
                "killed": outcome["returncode"] != 0
                          and bool(outcome["failed_node_ids"]),
                "restored": restored == before,
                "sha256_before": before, "sha256_after": restored,
            })
            results.append(outcome)
            print(json.dumps(outcome, ensure_ascii=False))
    finally:
        PRODUCT.write_bytes(original)

    payload = {
        "feature": "F-01 activation self-check batch scope",
        "product_file": "services/mca_random_source.py",
        "base_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True,
            text=True, check=True).stdout.strip(),
        "test": TEST,
        "sha256_original": before,
        "sha256_final": _sha256(PRODUCT.read_bytes()),
        "all_restored": all(item["restored"] for item in results),
        "killed": sum(1 for item in results if item["killed"]),
        "total": len(results),
        "mutations": results,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT}")
    return 0 if payload["killed"] == payload["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
