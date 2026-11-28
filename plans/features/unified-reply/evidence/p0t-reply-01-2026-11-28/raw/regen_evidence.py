"""Regenerate compact pytest evidence for P0T-REPLY-01 (evidence only).

Keeps only FAILED/ERROR lines + the final summary (no tracebacks: compact and
privacy-safe). Runs candidate batches, then stashes tracked changes to record
the same sets on base 74ef57ef4, and restores the stash in `finally`.

Usage: python plans/features/unified-reply/evidence/p0t-reply-01-2026-11-28/raw/regen_evidence.py
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[6]
E = pathlib.Path(__file__).resolve().parent
PY = sys.executable

NEW_SUITE = ["tests/test_p0t_reply_target.py"]
PINS = [
    "tests/test_direct_l1_l1d_contract.py",
    "tests/test_asap_w1_semantics.py",
    "tests/test_asap_speech_r3b_canon.py",
    "tests/test_p0_prompts_core.py",
    "tests/test_asap2_clar_contract.py",
    "tests/test_prompt_migrations.py",
    "tests/test_rlr_acceptance_rows.py",
    "tests/test_evol_evidence_routing.py",
    "tests/test_p0_goal_media_2026_11_25.py",
    "tests/test_post_asap5_w1_writer_core.py",
    "tests/test_post_asap5_w2_tech_reasoning.py",
    "tests/test_speech_p0_corrective_l1_route.py",
    "tests/test_asap_fc_voice_l1_decision_profile.py",
    "tests/test_evol_w17_small_canon_reqs.py",
    "tests/test_expression_isolation_followup.py",
    "tests/test_soul1_composer_parity_off.py",
]
DIRECT_BATCH = [
    "tests/test_asap7_direct_l1.py", "tests/test_asap8_v6_wc_direct_d03.py",
    "tests/test_asap8_v6_wc_direct_matrix.py",
    "tests/test_decision_making_round1026.py",
    "tests/test_p0b_current_question_priority.py",
    "tests/test_epic33_router_isolation.py",
    "tests/test_epic37_router_isolation.py", "tests/test_direct_chat.py",
    "tests/test_direct_chat_concurrency.py",
    "tests/test_direct_chat_handlers.py",
    "tests/test_evol_reply_context_consumers.py",
    "tests/test_evol_social_frame.py",
    "tests/test_p0_answer_finalization.py",
    "tests/test_bgs02_egress_observation.py", "tests/test_mca23_phase2.py",
    "tests/test_mca23_response_plan.py", "tests/test_rc_target_media_evidence.py",
    "tests/test_lore_compiler_round1020.py", "tests/test_p0_hc_egress_c2.py",
    "tests/test_p0_hc_telegram_egress.py", "tests/test_smartmodule_utils.py",
    "tests/test_asap8_initreply_binding.py",
]
REPLY_BATCH = [
    "tests/test_addtr_entry_caption.py", "tests/test_image_generation_round1023.py",
    "tests/test_tool_calling_round1015.py", "tests/test_ur_f_inspector_step1.py",
    "tests/test_asap5_integration_w3.py", "tests/test_mca23_planned_vs_actual.py",
    "tests/test_p0_media_phantom_intent.py",
    "tests/test_p0_row_media_marker_live_selection.py",
    "tests/test_p0_trigger_force_l1.py", "tests/test_smart_corrective_s7_reply.py",
    "tests/test_native_reply_media_context_round1024.py",
    "tests/test_tr_fix2_reply_ref.py", "tests/test_rc_direct_self_correction.py",
    "tests/test_speech_p0_l1_canonical.py", "tests/test_speech_p0_core_serious.py",
    "tests/test_p0_delta_routing.py", "tests/test_p0_followup_nostalgia_ab.py",
    "tests/test_unified_reply_ur_b_no_topic_veto.py",
    "tests/test_unified_reply_ur_b_review_fixes.py",
    "tests/test_ur_11_single_owner.py", "tests/test_ur_11_writer_fallback.py",
    "tests/test_ur_c_final_a.py", "tests/test_ur_d_writer.py",
    "tests/test_ur_e_speech.py",
]
CONTEXT_BATCH = [
    "tests/test_er08_limits_context.py", "tests/test_ur_context_selection.py",
    "tests/test_ur_10_no_pre_truncation.py", "tests/test_ur_21_18_reserve.py",
    "tests/test_direct_context_composer_asap3.py",
    "tests/test_direct_context_scenarios_asap3.py",
    "tests/test_asap2_boundary_marker.py", "tests/test_context_limits_round1019.py",
    "tests/test_caps_context.py", "tests/test_token_analytics_round1023.py",
    "tests/test_ur_c_clock.py",
]
BASE_PAIRS = [
    ("baseline-batch-direct-pair", ["tests/test_asap8_initreply_binding.py",
                                    "tests/test_epic33_router_isolation.py"]),
    ("baseline-batch-reply-pair", ["tests/test_asap5_integration_w3.py",
                                   "tests/test_native_reply_media_context_round1024.py"]),
    ("baseline-batch-reply-others", [
        "tests/test_image_generation_round1023.py::TestToolSchema",
        "tests/test_image_generation_round1023.py::TestPreGateIntegration",
        "tests/test_ur_f_inspector_step1.py"
        "::test_identical_quotes_credit_only_the_surviving_item",
    ]),
    ("baseline-batch-context", [
        "tests/test_direct_context_scenarios_asap3.py"
        "::TestStaleSummary::test_lag400_middle_topk_under_pressure",
    ]),
]

_KEEP = re.compile(r"^(FAILED|ERROR) \S")
_SUMMARY = re.compile(r"^[0-9]+ (passed|failed)")


def run(tests) -> tuple[int, list[str]]:
    proc = subprocess.run(
        [PY, "-m", "pytest", *tests, "-q", "--no-header", "--timeout=180"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = []
    for line in out.splitlines():
        if _KEEP.match(line) or _SUMMARY.search(line):
            lines.append(line)
    return proc.returncode, lines


def write(name: str, code: int, lines: list[str]) -> None:
    body = "\n".join(lines) + f"\n[exit={code}]\n"
    (E / f"{name}.txt").write_text(body, encoding="utf-8")
    print(f"{name}: exit={code} lines={len(lines)}")


def candidate() -> None:
    for name, tests in (
        ("candidate-new-suite", NEW_SUITE),
        ("candidate-pins", PINS),
        ("candidate-batch-direct", DIRECT_BATCH),
        ("candidate-batch-reply", REPLY_BATCH),
        ("candidate-batch-context", CONTEXT_BATCH),
    ):
        write(name, *run(tests))


def baseline() -> None:
    stash = subprocess.run(["git", "stash", "push", "--", "services", "tests"],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    if stash.returncode != 0:
        print("STASH FAILED:", stash.stdout, stash.stderr)
        return
    print("STASHED:", stash.stdout.strip().splitlines()[0])
    try:
        write("baseline-new-suite-red", *run(NEW_SUITE))
        write("baseline-pytest", *run(PINS))
        for name, tests in BASE_PAIRS:
            write(name, *run(tests))
    finally:
        pop = subprocess.run(["git", "stash", "pop"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace")
        print("RESTORED:", "ok" if pop.returncode == 0 else "FAILED")
        if pop.returncode != 0:
            print(pop.stdout, pop.stderr)


if __name__ == "__main__":
    candidate()
    baseline()
