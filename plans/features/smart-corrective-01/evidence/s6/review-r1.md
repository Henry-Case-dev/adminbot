# S6-PROMPT independent review R1

## Candidate binding

- Epic: `SMART-CORRECTIVE-01`
- Slice: `S6-PROMPT`
- Candidate code: `5d2eb427` (`5d2eb427` was reviewed from the candidate worktree)
- Evidence baseline: `717bcc61`
- Base: `sc/corrective-s3b` @ `b04dd8f7` (S3B previously approved)
- Candidate worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-e7b064d8`
- Review artifact is candidate-worktree-only; application code, master map and backlog were not modified.

## Implementation / contract

Inspected the exact diff from `b04dd8f7` to `5d2eb427` in:

- `services/checkup_service.py`: `_resolve_checkup_base_prompt`, the user checkup path, the no-`chat_id` internal path, prompt composition and `_prompt_telemetry`.
- `services/prompt_registry.py`: `resolve_chat_speech_ex` usage boundary, `FACTORY_REVISION_SEALS`, `FACTORY_SET_SHA256_12` and `activation_plan` inputs.
- `services/checkup_prompts.py`: active factory edition, `PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT`, addendum and fallback notice.
- `handlers/checkup.py` source path and the architecture contract `architecture-plan.md` §6/§8 from master.

Observed contract:

- User route with `chat_id` uses the existing registry precedence chat override → global → factory.
- Internal no-chat route retains the previous global/default resolution.
- The service has no prompt persistence call; saved owner bytes remain in PG/chat parameters.
- Telemetry preserves the existing source/hash/version/chars fields and adds layer/base hash/base chars/withheld/reason fields without prompt text.
- The active contour removes Betterstack and the 401 example; the historical `PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT` retains the old bytes.
- Composition is one base speech layer plus owner block, diagnostic addendum and fallback notice; no second speech engine or instruction quota was found.
- The unchanged revision label is deliberate and `activation_plan` remains `PLAN_NOOP`, preventing a factory activation over the saved chat edition.

## Test validity

Read all 16 tests in `tests/test_smart_corrective_prompt_delivery.py` and the five updated tests in `tests/test_checkup_prompts.py`, `tests/test_checkup_contract.py`, `tests/test_checkup_logs_fetcher.py`, `tests/test_p0_prompts_core.py` and `tests/test_expression_isolation_followup.py`.

Assertions are contract-bearing: resolver source/layer and per-chat isolation, saved bytes unchanged, registry substitution observability, telemetry field presence and text exclusion, active-vs-historical contour, addendum clauses, exact full system composition with a >12,000-character owner edition, one speech layer, seal integrity and `PLAN_NOOP`. No `assert True`, empty body or mock of the production registry boundary was used for the core delivery tests. The registry-change test patches the resolver to inject a changed effective text but still exercises `CheckupService` composition and persistence invariants.

## Executed checks

- Focused delivery: `16 passed`.
- S6/checkup/prompt contract suite: `344 passed, 2 skipped`.
- Broader prompt suite: `451 passed`.
- Regression/adjacent prompt suite: `264 passed, 1 failed`.
- The observed failure was `tests/test_prompt_field_audit.py::test_every_editable_prompt_has_reachable_surface`; it reproduced unchanged on base `b04dd8f7`.
- The separately requested registry pointer failure `tests/test_soul1_registry_completeness.py::test_registry_consumer_pointers_point_at_real_lines` also reproduced on base `b04dd8f7` (`internal.lore.init`, stale pointer `lore_worker.py:709`). Both are pre-existing and unrelated to S6.
- `py_compile` and `git diff --check` were reported clean in the implementation evidence; no contrary source issue was found during review.

## Independent falsification

A disposable Git archive of candidate `5d2eb427` was created under the allocated probe run. Each mutation was made only in its disposable copy and then the smallest relevant test was run:

| Mutation | Expected contract failure | Observed |
|---|---|---|
| Remove chat-specific resolver precedence | Chat override must no longer be delivered | `test_chat_override_applies_on_checkup_route`: **1 failed** |
| Re-add `Betterstack` to active contour | Active contour must reject stale provider text | `test_active_contour_has_no_stale_betterstack`: **1 failed** |
| Truncate the owner edition before composition | Exact full-system assertion must reject truncation | `test_full_instructions_reach_the_model`: **1 failed** |
| Change revision label to a new label | Activation/owner-preservation assertion must reject the overwrite-risking label | `test_factory_content_fix_does_not_activate_over_owner_edition`: **1 failed** |
| Add a saved-value write in the resolver path | Saved owner bytes must remain unchanged | `test_owner_saved_value_is_not_rewritten`: **1 failed** |

All five mutations produced real failing assertions; no mutation result was inferred from source text alone.

## Acceptance ledger

All mandatory S6-PROMPT rows, including `AC-15`/`AC-19`-mapped prompt delivery and preservation obligations, are accepted at **REVIEW** level for this candidate only. None is marked `VERIFIED`; production delivery requires the separately specified postdeploy checkup in a chat with the saved edition and effective telemetry/provenance observation.

The master map was not edited. When checked from master with `requirements_gate.py --stage review --slice S6-PROMPT --candidate 5d2eb427`, the result was `inventory=224 manual=232 scoped=55 errors=56`: the map candidate binding and S6 rows are still pending/unbound, including candidate mismatch. This is a PM evidence-binding synchronization gap, not a discovered implementation failure.

## Findings

### IN_SCOPE blockers

None found in implementation or behavior.

### Evidence synchronization required before gate closure

- **Owner: PM/Orchestrator.** Bind S6-PROMPT rows to candidate `5d2eb427`, attach this candidate-bound review artifact and set the applicable rows to `REVIEW`; then rerun the exact master review gate. Do not mark them `VERIFIED` before production evidence.

### BACKLOG_ONLY / pre-existing

- `tests/test_soul1_registry_completeness.py::test_registry_consumer_pointers_point_at_real_lines`: stale `internal.lore.init` consumer pointer, reproduced on base and candidate; unrelated to S6.
- `tests/test_prompt_field_audit.py::test_every_editable_prompt_has_reachable_surface`: missing reachable surface for `direct.base.synthesizer`, reproduced on base and candidate; unrelated to S6.

These were not added to `plans/backlog.md` because this review is read-only except for the requested review artifact; the findings are recorded here for PM's existing backlog reconciliation.

## Verdict

**Approved** for predeploy review of exact candidate `5d2eb427`, with S6 rows and AC-15/AC-19 represented at `REVIEW` level only. This is not production acceptance and does not claim final release verification. The required postdeploy checkup in a chat with the saved edition remains unverified by design.

### Three-pillar summary

- **Implementation:** exact changed paths, callers, registry contract and architecture §6/§8 inspected; precedence, no-write behavior, telemetry, active/history split, addendum, single layer and PLAN_NOOP were verified.
- **Test validity:** 16 new and five updated test bodies/assertions read; they assert user-visible payload/state and meaningful negative boundaries, and the two unrelated failures were reproduced on base.
- **Independent challenge:** five distinct disposable mutations all caused their targeted tests to fail with observed `1 failed` results.

## Housekeeping

Probe allocation: `C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a\probe-2d66f1c424`.

The candidate worktree is retained. Disposable mutation copies and logs remain until this review handoff cleanup completes; no application files were changed.
