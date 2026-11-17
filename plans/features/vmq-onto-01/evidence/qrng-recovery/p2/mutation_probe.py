"""QRNG P2 — mutation-проба адаптера LfDR (red-proof каждого инварианта).

Запуск из корня worktree:
`python plans/features/vmq-onto-01/evidence/qrng-recovery/p2/mutation_probe.py`

Каждая мутация применяется к `services/mca_random_source.py` точной байтовой
заменой (ровно одно вхождение), затем запускается целевой pytest-набор.
Файл восстанавливается в `finally`; итоговый sha256 сверяется с исходным.
JSON — одним объектом в stdout. Сети не касается.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
MODULE = ROOT / "services" / "mca_random_source.py"
TESTS = "tests/test_qrng_p2_lfdr.py"
P1_TESTS = "tests/test_qrng_p1_isolation.py"

MUTATIONS = [
    {
        "id": "M1",
        "mutation": "scheme guard accepts http (origin-guard ослаблен)",
        "anchor": b'    if parts.scheme.lower() != "https":\n'
                  b'        raise LfdrError("scheme_not_allowed",',
        "replacement": b'    if parts.scheme.lower() not in ("https", "http"):\n'
                       b'        raise LfdrError("scheme_not_allowed",',
        "targets": [f"{TESTS}::TestOriginGuard::test_rejects_arbitrary_endpoint"],
    },
    {
        "id": "M2",
        "mutation": "путь endpoint не проверяется (любой path)",
        "anchor": b'if (parts.path or "") != LFDR_PATH:',
        "replacement": b"if False:",
        "targets": [f"{TESTS}::TestOriginGuard::test_rejects_arbitrary_endpoint"],
    },
    {
        "id": "M3",
        "mutation": "hex-символы ответа не проверяются",
        "anchor": b"if any(c not in _LFDR_HEX_CHARS for c in qrn):",
        "replacement": b"if False:",
        "targets": [
            f"{TESTS}::TestFetchContract::test_invalid_payload_is_validation_failed"],
    },
    {
        "id": "M4",
        "mutation": "заявленная length ответа не сверяется с запросом",
        "anchor": b"if int(text) != length:",
        "replacement": b"if False:",
        "targets": [
            f"{TESTS}::TestFetchContract::test_invalid_payload_is_validation_failed"],
    },
    {
        "id": "M5",
        "mutation": "границы запроса length удалены",
        "anchor": b"if not (LFDR_MIN_LENGTH <= length <= LFDR_MAX_LENGTH):",
        "replacement": b"if False:",
        "targets": [
            f"{TESTS}::TestFetchContract::test_bounds_rejected_before_request"],
    },
    {
        "id": "M6",
        "mutation": "LfDR объявлен требующим ключ (requires_key=True)",
        "anchor": b'requires_key=False, docs_url="https://lfdr.de/QRNG/"),',
        "replacement": b'requires_key=True, docs_url="https://lfdr.de/QRNG/"),',
        "targets": [
            f"{TESTS}::TestRegistry::test_lfdr_registered_hardware_keyless_with_hooks",
            f"{P1_TESTS}::TestProvenanceDto::"
            "test_registry_three_hardware_providers_no_lizaonair",
        ],
    },
    {
        "id": "M7",
        "mutation": "в запрос добавлен ключевой заголовок (LfDR стал key-based)",
        "anchor": b"headers: dict[str, str] = {}",
        "replacement": b'headers: dict[str, str] = {"x-api-key": "k"}  # MUT',
        "targets": [
            f"{TESTS}::TestFetchContract::"
            "test_valid_hex_to_uint8_and_request_shape"],
    },
]


def _run(targets: list[str]) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-q", "--tb=no",
         "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    failed = [line.split(" ", 1)[1] for line in lines
              if line.startswith("FAILED ")]
    summary = lines[-1] if lines else ""
    return {"returncode": proc.returncode, "summary": summary,
            "failed": failed}


def main() -> dict:
    original = MODULE.read_bytes()
    original_sha = hashlib.sha256(original).hexdigest()
    out = {"module": str(MODULE), "original_sha256": original_sha,
           "mutations": []}
    try:
        for item in MUTATIONS:
            anchor = item["anchor"]
            count = original.count(anchor)
            if count != 1:
                raise RuntimeError(
                    f"{item['id']}: anchor occurrences={count}, expected 1")
            MODULE.write_bytes(original.replace(anchor, item["replacement"]))
            result = _run(item["targets"])
            # killed ⇔ мутация падает на целевых тестах (не «зелёный» прогон)
            killed = result["returncode"] != 0 and bool(result["failed"])
            out["mutations"].append({
                "id": item["id"], "mutation": item["mutation"],
                "targets": item["targets"],
                "returncode": result["returncode"],
                "summary": result["summary"],
                "failed": result["failed"], "killed": killed,
            })
    finally:
        MODULE.write_bytes(original)
    restored_sha = hashlib.sha256(MODULE.read_bytes()).hexdigest()
    out["restored_sha256"] = restored_sha
    out["restored_ok"] = restored_sha == original_sha
    out["all_killed"] = all(m["killed"] for m in out["mutations"])
    return out


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not (result["restored_ok"] and result["all_killed"]):
        raise SystemExit(1)
