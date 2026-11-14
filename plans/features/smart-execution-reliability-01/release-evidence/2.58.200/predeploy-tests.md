# 2.58.200 pre-deploy verification (candidate 0e4a144d)

Environment: release worktree
`WorkspaceData/worktrees/.../smart-execution-reliability-01-45d7d5f19c3b-db50b61f`
at `0e4a144d`, project venv `C:\Code\Python\adminbot\.venv`.
Baseline parity reproduced in the 2.58.199 worktree at `d20a7f73` (production).

## 1. Feature / acceptance set — 17 files, 362 passed

`tests/test_smart_exec_ab_round1114.py test_smart_exec_evidence.py
test_smart_exec_learning_incidents.py test_smart_exec_memory_scope.py
test_smart_exec_selfdiag.py test_capacity_stage_d_smart.py test_caps_context.py
test_caps_tool_results.py test_smart_c1_source_reader_limits.py
test_smart_g_finalize_round1114.py test_smart_i4_reason_codes.py
test_sxr_i2_fresh_stream_drain.py test_sxr_i3_lesson_effects.py
test_smart_e_local_first_source.py test_selfdiag_corrective_research.py
test_checkup_contract.py test_release_manifest.py`

Result: `362 passed in 26.65s` (exit 0).

## 2. FACTCHECK set — 15 files, 276 passed

`tests/test_factcheck_subject_contract.py test_factcheck_resources.py
test_factcheck_evidence_delivery.py test_factcheck_finalization.py
test_factcheck_prompts.py test_factcheck_service.py test_factcheck_planner_cfg06.py
test_factcheck_orchestrator_cfg06.py test_factcheck_context_cfg06.py
test_factcheck_attribution_cfg06.py test_factcheck_renderer_cfg06.py
test_factcheck_gate_cfg06.py test_factcheck_tool_route_cfg06.py
test_factcheck_w6_cfg06.py test_factcheck_w7_acceptance_cfg06.py`

Result: `276 passed in 13.98s` (exit 0). The 4 acceptance files alone:
`88 passed in 4.46s` (exit 0).

## 3. Pin-guard set — 24 files touched by the version bump: 856 passed / 4 failed

Failures (identical on production baseline `d20a7f73`, reproduced in the
2.58.199 worktree — pre-existing, not introduced):

- `test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools`
  (canon is 18 tools, the legacy assertion still says 17)
- `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`
- `test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`
- `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`

## 4. Broad smoke set — 26 files, 1037 passed / 12 failed

`test_budget_global_toggle_round1024 test_budget_guardrails_round1024
test_budget_overrides_merge_round1024 test_budget_settings_round1019
test_budget_unlimited_round1019 test_bgs05_budgets test_auto_budget_asap31
test_tool_loop test_tool_router test_smoke_round1016_tool_loop
test_mca11_tool_result_round1028 test_evidence_bundle test_evol_source_reader
test_direct_chat test_direct_chat_handlers test_direct_chat_prompts
test_direct_chat_concurrency test_mca02_safe_fetch_round1027
test_asap8_v6_d05_experience test_asap8_v63_b02_semantic_experience
test_evol020_experience_pipeline test_param_catalog test_webapp_api
test_self_diag_golden test_checkup_service test_prompt_field_audit`

Result: `12 failed, 1037 passed, 1 warning in 51.74s`.

The failing list is **byte-identical** to the same four files run on the
production baseline `d20a7f73` (`12 failed, 65 passed`): `test_budget_global_toggle_round1024`
(3), `test_budget_guardrails_round1024` (2 menu-freeze), `test_budget_overrides_merge_round1024`
(6), `test_prompt_field_audit::test_every_editable_prompt_has_reachable_surface` (1).
`Compare-Object` over the two FAILED lists returned no differences → no new
failures. These are pre-existing environment/legacy-expectation failures
(backlog), not regressions of this train.

## 5. Hygiene

`git status --porcelain` = clean before and after the bump commit;
`git diff --check` = 0; obsolete `.deploy/release.json` from the local manifest
dry run removed (`.deploy/` is git-ignored).

## Not re-run by ritual

Reviewer already proved the unchanged candidate (`1d9cf251`) with S12 388 /
S17 127 on the merged tree; the only post-approval delta is version pins, so a
focused re-run plus the baseline parity above is the delivery-level check.
