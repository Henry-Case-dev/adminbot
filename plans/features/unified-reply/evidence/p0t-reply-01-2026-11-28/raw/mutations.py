"""Mutation harness for P0T-REPLY-01 (evidence only; not a test).

For each mutation: backup file -> apply exact replacement -> run pytest subset ->
restore file. Restoration runs in `finally` for every mutation, and the last line
re-runs the new suite on the restored candidate. Never leaves a mutated file.

Usage: python plans/features/unified-reply/evidence/p0t-reply-01-2026-11-28/raw/mutations.py
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[6]
PY = sys.executable
DCS = ROOT / "services" / "direct_chat_service.py"
DL1 = ROOT / "services" / "direct_l1.py"
CP = ROOT / "services" / "chat_prompts.py"

SUITE = "tests/test_p0t_reply_target.py"

SEAM_TESTS = [
    f"{SUITE}::test_plan_target_photo_in_audio_window",
    f"{SUITE}::test_plan_target_chunked_reply_only_first_chunk",
    f"{SUITE}::test_delivery_chat_means_no_reply",
    f"{SUITE}::test_delivery_absent_means_no_reply",
]
FAILSOFT_TESTS = [
    f"{SUITE}::test_missing_target_is_plain_send_not_trigger",
    f"{SUITE}::test_stale_target_is_plain_send",
    f"{SUITE}::test_addressee_mismatch_is_plain_send",
]
FOREIGN_TESTS = [f"{SUITE}::test_foreign_chat_target_is_plain_send"]
CTX_TESTS = [f"{SUITE}::test_direct_l1_context_marks_window_and_p0_ids"]
CANON_TESTS = [
    "tests/test_asap_w1_semantics.py::test_p0g_l1_participation_section_byte_exact",
    "tests/test_direct_l1_l1d_contract.py::test_canon_forms_no_priority_and_positive_criteria",
]

MUTATIONS = [
    (
        "M1_always_trigger",
        DCS,
        "_reply_target = getattr(message, \"message_id\", None)\n"
        "            if l1_plan is not None and _l1.plan_delivery_is_semantic(l1_plan):",
        "_reply_target = getattr(message, \"message_id\", None)\n"
        "            if False and l1_plan is not None and _l1.plan_delivery_is_semantic(l1_plan):",
        SEAM_TESTS,
    ),
    (
        "M2_last_window_row",
        DCS,
        "_reply_target, _binding_code = await _validate_plan_target(\n"
        "                        self.db, chat_id, l1_plan, mode=\"reply\")",
        "_mut_rows = _l1.normalize_window_rows(\n"
        "                        await self.memory.get_window_messages(chat_id))\n"
        "                    _mut_plan = _l1.L1Plan(\n"
        "                        action=\"reply\", delivery=\"reply\", source=\"llm\",\n"
        "                        target_message_id=(_mut_rows[-1].get(\"id\")\n"
        "                                           if _mut_rows else None))\n"
        "                    _reply_target, _binding_code = await _validate_plan_target(\n"
        "                        self.db, chat_id, _mut_plan, mode=\"reply\")",
        [SEAM_TESTS[0]],
    ),
    (
        "M3_drop_chat_filter",
        DCS,
        "\"WHERE id = ? AND chat_id = ?\", (int(target), int(chat_id)))",
        "\"WHERE id = ?\", (int(target),))",
        FOREIGN_TESTS,
    ),
    (
        "M4_no_p0_msg_ids",
        DL1,
        "        p0_row_ids: dict[str, int] = {}\n        if with_ids:",
        "        p0_row_ids: dict[str, int] = {}\n        if False:",
        CTX_TESTS,
    ),
    (
        "M5_no_fail_soft",
        DCS,
        "                    if _reply_target is None:\n"
        "                        logger.info(",
        "                    if _reply_target is None:\n"
        "                        _reply_target = getattr(message, \"message_id\", None)\n"
        "                        logger.info(",
        FAILSOFT_TESTS,
    ),
    (
        "M6_canon_scope_reverted",
        CP,
        "    PREV_DIRECT_L1_PLANNER_P0GM.replace(\n"
        "        _DIRECT_L1_PARTICIPATION_R3, _DIRECT_L1_PARTICIPATION_R4))",
        "    PREV_DIRECT_L1_PLANNER_P0GM)",
        CANON_TESTS,
    ),
]


def run(tests) -> tuple[int, str]:
    proc = subprocess.run(
        [PY, "-m", "pytest", *tests, "-q", "--no-header"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-4:])
    return proc.returncode, tail


def main() -> int:
    print(f"ROOT={ROOT}")
    base_code, base_tail = run(sorted({t for _n, _f, _o, _new, ts in MUTATIONS
                                       for t in ts}))
    print(f"\nBASE candidate: exit={base_code}\n{base_tail}\n")
    for name, path, old, new, tests in MUTATIONS:
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            print(f"{name}: SKIP (anchor count={text.count(old)})")
            continue
        backup = path.with_suffix(path.suffix + f".{name}.bak")
        shutil.copy2(path, backup)
        try:
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            code, tail = run(tests)
        finally:
            shutil.copy2(backup, path)
            backup.unlink()
        verdict = ("RED (good)" if code != 0
                   else "GREEN (BAD: test does not discriminate)")
        print(f"{name}: exit={code} -> {verdict}\n{tail}\n")
    restored_code, restored_tail = run([SUITE])
    print(f"RESTORED candidate: exit={restored_code}\n{restored_tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
