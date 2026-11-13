# Independent review S3-EVIDENCE wave-2 C2/C3

**Решение: Needs Fixes**

Кандидат: fa37e48522ce3522943442a6e378cc2dc36eb139; base: 36dd6b232bf2705cc470764a7ab71451c5c49fdf; evidence head: f2359900.

## Acceptance ledger

- SXR-C1-01 VERIFIED (reused): caps 6/2/16, defaults 3/1/8.
- SXR-C1-02 VERIFIED (reused): initial/later line-range paging for local text >2 MB.
- SXR-C1-03 VERIFIED (reused): per-run counters/state reset.
- SXR-C2-01 UNVERIFIED: changed composer/evidence/response paths pass, but tool_router/search_aggregator, vision/OCR, transcripts, factcheck and direct_chat/message-memory are outside this diff and lack integrated system-wide proof.
- SXR-C2-02 VERIFIED for changed slice; system-wide continuation remains integration-required.
- SXR-C3-01 UNVERIFIED: SourceReader seven-step route is proven; remaining tool families need integrated proof.
- SXR-C3-02 UNVERIFIED: bundle/packing paths are proven, but global payload/fallback/provider paths and remaining caps are not.
- N/A: none. READY_FOR_LIVE: none.

## Implementation

Inspected actual diff and callers in services/direct_context_composer.py, services/evidence_bundle.py, services/response_extent.py and SourceReader/tool-loop. `0` is explicit no-artificial-cap; positive env policy, continuation (next_offset/frame:<offset>), provenance and real-window packing remain. No new paraphrasing stage or self-invented instruction quota found. Diff name list confirms tool_router, search_aggregator, vision/OCR, transcript, factcheck and direct_chat are absent: this proves write-scope claim, not behavior.

## Test validity

Read assertions in tests/test_smart_exec_evidence.py and updated tests/test_mca23_phase2.py/tests/test_mca23_response_plan.py. They assert values, env boundaries, continuation, no silent loss, byte-identical tool payload, provenance and final answer. Mutation re-add of middle cap was red and restored version green. Reused runs: focused 24 passed; combined impacted 957 passed, with 22 leaked aiosqlite connections warning. Tests do not prove untouched families or production effective-state.

## Independent challenge

Explicit caps were challenged: CHAT_MIDDLE_MAX_MESSAGES=5, CHAT_EPISODE_MAX_MESSAGES=10, DIRECT_TOOL_PLAN_MAX_FETCH_STEPS=3 remain enforced; malformed/zero policy is no-cap. Saved adversarial evidence shows oversized evidence continuation and mutation red. `git diff --check` independently FAILED: added services/direct_context_composer.py lines have trailing whitespace (CRLF in candidate diff, including import os and added block).

## Proven here vs integration-required

Proven here: changed-service factory-cap removal/env policy, bundle/source continuation/provenance, SourceReader -> ToolResult -> tool-loop -> composer -> payload -> final answer, C1 reuse, no migration/DDL/flag flip.

Integration-required: combined-candidate audit for tool_router/search_aggregator, vision/OCR, transcript, factcheck, direct_chat, L1/Writer/fallback/reserve paths, effective production config and live LLM payload. Do not mark C2-01/C3-01/C3-02 fully proven from this slice.

## Blocking findings / next action

1. BLOCKER Builder: normalize line endings/trailing whitespace in added direct_context_composer.py without behavior change; rerun diff --check and focused tests.
2. BLOCKER Builder/Reviewer integration owner: provide candidate-bound integrated audit for untouched families and direct_chat/payload seams; keep affected rows UNVERIFIED.

Next action for Orchestrator: route finding 1 to Builder, schedule combined-candidate audit, then independently re-review corrected exact candidate.

