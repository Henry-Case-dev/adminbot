"""2.58.198 release-candidate mandatory train (exact release SHA).

Same focused sets as the approved final integration binding, re-run on the
bumped release commit; plus the wide web/api set, JS-unit set and e2e scripts.
Zero project writes; cache/basetemp live in the run dir.
"""
from __future__ import annotations

import glob
import re
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(sys.argv[1])
RUNDIR = Path(sys.argv[2])
PY = r"C:\Code\Python\adminbot\.venv\Scripts\python.exe"

SETS: dict[str, list[str]] = {
    "d6_checkup_contract": ["tests/test_checkup_contract.py"],
    "d6_broad22": [
        "tests/test_checkup_contract.py",
        "tests/test_checkup_handlers.py",
        "tests/test_checkup_service.py",
        "tests/test_checkup_prompts.py",
        "tests/test_checkup_logs_fetcher.py",
        "tests/test_p0_checkup_core_contract.py",
        "tests/test_prompt_readback.py",
        "tests/test_diagnostic_probes.py",
        "tests/test_evidence_bundle.py",
        "tests/test_diagnostic_policy.py",
        "tests/test_tool_schemas.py",
        "tests/test_tool_router.py",
        "tests/test_tool_loop.py",
        "tests/test_tool_calling_round1015.py",
        "tests/test_tool_chains_round1026.py",
        "tests/test_evol_source_reader.py",
        "tests/test_round1025_f8_registry.py",
        "tests/test_frontend_tab_mapping.py",
        "tests/test_webapp_parity_smoke.py",
        "tests/test_addtr_entry_caption.py",
        "tests/test_direct_chat_handlers.py",
        "tests/test_p0b_current_question_priority.py",
    ],
    "d6_q16": [
        "tests/test_deploy_identity_d4b.py",
        "tests/test_deploy_identity.py",
        "tests/test_evol_source_reader.py",
        "tests/test_param_catalog.py",
        "tests/test_round1025_f8_registry.py",
        "tests/test_frontend_tab_mapping.py",
        "tests/test_webapp_parity_smoke.py",
        "tests/test_asap8_v6_d07_overrides.py",
        "tests/test_addtr_entry_caption.py",
        "tests/test_direct_chat_handlers.py",
        "tests/test_p0b_current_question_priority.py",
        "tests/test_asap7_cover_preview.py",
        "tests/test_mca10b_random_applications_block_d_round1041.py",
        "tests/test_prompts_round1024.py",
        "tests/test_prompt_baseline.py",
        "tests/test_prompt_versioning_enforcement.py",
    ],
    "d2_145": [
        "tests/test_param_sensitivity_registration.py",
        "tests/test_param_catalog.py",
        "tests/test_diagnostic_settings_adapter.py",
        "tests/test_evidence_bundle.py",
        "tests/test_diagnostic_probes.py",
    ],
    "d2_216": [
        "tests/test_param_catalog.py",
        "tests/test_param_sensitivity_registration.py",
        "tests/test_diagnostic_policy.py",
        "tests/test_diagnostic_probes.py",
        "tests/test_evidence_bundle.py",
        "tests/test_diagnostic_settings_adapter.py",
    ],
    "d2_42": ["tests/test_debug_config.py", "tests/test_log_ring.py"],
    "d2_232": [
        "tests/test_checkup_contract.py",
        "tests/test_prompt_readback.py",
        "tests/test_cfg03_param_audit.py",
        "tests/test_chat_params.py",
        "tests/test_settings_helpers.py",
        "tests/test_asap7_direct_settings.py",
        "tests/test_rlr_admin_manifest.py",
        "tests/test_summary_param_catalog_annotation_asap41.py",
        "tests/test_mod_acl_ux_01_m4_module_params.py",
    ],
    "d4_22": ["tests/test_deploy_identity_d4c.py"],
    "d4_366": [
        "tests/test_deploy_identity.py",
        "tests/test_deploy_identity_d4b.py",
        "tests/test_evidence_bundle.py",
        "tests/test_diagnostic_probes.py",
        "tests/test_checkup_contract.py",
        "tests/test_checkup_service.py",
        "tests/test_checkup_handlers.py",
        "tests/test_p0_checkup_core_contract.py",
        "tests/test_diagnostic_policy.py",
    ],
    "d5_62": ["tests/test_prompt_readback.py"],
    "d5_38": ["tests/test_self_diag_golden.py"],
    "d5_355": [
        "tests/test_prompt_readback.py",
        "tests/test_diagnostic_policy.py",
        "tests/test_tool_router.py",
        "tests/test_tool_schemas.py",
        "tests/test_diagnostic_probes.py",
        "tests/test_checkup_contract.py",
        "tests/test_checkup_service.py",
        "tests/test_self_diag_golden.py",
    ],
    "d5_prompt_contracts": [
        "tests/test_prompt_baseline.py",
        "tests/test_evol016_prompt_activation.py",
        "tests/test_soul1_direct_prompt_reads.py",
    ],
    "d3_80": ["tests/test_evidence_bundle.py", "tests/test_diagnostic_probes.py"],
    "d3_1325": [
        "tests/test_diagnostic_probes.py",
        "tests/test_evidence_bundle.py",
        "tests/test_tool_schemas.py",
        "tests/test_tool_router.py",
        "tests/test_diagnostic_policy.py",
        "tests/test_checkup_service.py",
        "tests/test_checkup_handlers.py",
        "tests/test_checkup_logs_fetcher.py",
        "tests/test_p0_checkup_core_contract.py",
        "tests/test_memory_health.py",
        "tests/test_memory_health_round1019.py",
        "tests/test_evol009_memory_diagnostics.py",
        "tests/test_deploy_identity.py",
        "tests/test_deploy_identity_d4b.py",
        "tests/test_evol_source_reader.py",
        "tests/test_tool_calling_round1015.py",
        "tests/test_tool_loop.py",
        "tests/test_smoke_round1016_tool_loop.py",
        "tests/test_agentic_ai_round1020.py",
        "tests/test_asap5_image_admin.py",
        "tests/test_asap5_integration_w3.py",
        "tests/test_decision_making_round1026.py",
        "tests/test_image_context_memory_round1026.py",
        "tests/test_mca11_tool_result_round1028.py",
        "tests/test_mca15_chat_statistics_round1028.py",
        "tests/test_mca17c_invariants_round1047.py",
        "tests/test_mca19_block_g_round1043.py",
        "tests/test_mca20_integration_round1045.py",
        "tests/test_media_transcribe_tool_round1024.py",
        "tests/test_memory_lookup_round1026.py",
        "tests/test_native_media_tools_round1024.py",
        "tests/test_recent_history_tool_round1015.py",
        "tests/test_telegram_reactions_round1026.py",
        "tests/test_tool_chains_round1026.py",
        "tests/test_tool_download_quality_round1017.py",
    ],
    "web_api": ["tests/test_webapp_api.py", "tests/test_webapp_hotfix10_round1025.py"],
    "js_unit": ["tests/test_webapp_js_unit.py"],
    "web_wide": sorted(glob.glob("tests/test_web*.py")),
}

SUMMARY = re.compile(r"^=+ .*(passed|failed|error|no tests ran).* =+$|^\d+ (passed|failed)", re.M)


def run(name: str) -> dict[str, object]:
    files = SETS[name]
    log = RUNDIR / f"run-{name}.log"
    (RUNDIR / "tmp" / name).mkdir(parents=True, exist_ok=True)
    cmd = [
        PY, "-m", "pytest", *files, "-q", "--timeout=60",
        "-p", "no:cacheprovider",
        f"--basetemp={RUNDIR / 'tmp' / name}",
    ]
    proc = subprocess.run(
        cmd, cwd=WORKTREE, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=5400,
    )
    out = (proc.stdout or "") + ("\n--- STDERR ---\n" + proc.stderr if proc.stderr else "")
    log.write_text(out, encoding="utf-8")
    tail = [ln.strip() for ln in out.splitlines() if ln.strip()]
    summary = tail[-1] if tail else "<no output>"
    failures = [ln.strip() for ln in tail if ln.startswith(("FAILED", "ERROR"))]
    print(f"{name}: exit={proc.returncode} | {summary}", flush=True)
    for f in failures:
        print(f"    {f}", flush=True)
    return {"name": name, "exit": proc.returncode, "summary": summary, "failures": failures}


def main() -> int:
    names = sys.argv[3:] or list(SETS)
    results = []
    for name in names:
        try:
            results.append(run(name))
        except subprocess.TimeoutExpired:
            print(f"{name}: TIMEOUT (bounded runner, 5400s)", flush=True)
            results.append({"name": name, "exit": "TIMEOUT", "summary": "timeout", "failures": []})
    print("\n== TOTALS ==", flush=True)
    bad = 0
    for r in results:
        print(f"  {r['name']:<22} exit={r['exit']}  {r['summary']}", flush=True)
        if r["exit"] != 0:
            bad += 1
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
