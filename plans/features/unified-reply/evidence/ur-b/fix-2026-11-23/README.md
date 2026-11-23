# UR-B tool/evidence minimal fix — 2026-11-23

**Task:** `unified-reply` UR-B, depends UR-A; after UR-A F3/F4.
**Base:** `1e9168ea8` (UR-A F3/F4 branch HEAD; code `b9b9317c7`).
**Branch:** `fix/ur-b-tool-evidence`.
**Code candidate:** `462cf1b22d492c771785a0c0f3d4422ff20f3eef` (final; initial `85cc4e7c1`, follow-up tightens no-growth status).
**Scope:** one live tool stage and one `ToolEvidence` for REPLY in both modes; no unrelated product/DDL/ACL/UI/embedding, no map/status/deploy/SSH/LLM.

## 1. The exact 7 UR-B PENDING rows

Source: `plans/features/unified-reply/requirements-map.json`, slice `UR-B` (items + additional requirements), state at master `79bd2f0ef`.

| Row | Acceptance focus | This increment | Status |
|---|---|---|---|
| `UR-03.1` | rights/provider state before planning; one `ToolEvidence` with dedup/errors/source/time/tool trace for both modes | `tool_events` (R17-safe per-call projection) added to `ToolEvidence`; sources/tool_trace preserved; pre-planning `ToolStateSnapshot` remains the resolver | **PARTIAL** |
| `UR-07.3` | L2 structured results + source/limits; adaptive stops when evidence does not grow | `_has_evidence_growth` stops `run_adaptive_chain` with `step_skipped`; test covers empty result and one dispatch | **PARTIAL** |
| `UR-17.7` | live dialogue: honest tools description + real Web Search on current external request | not implementable as unit/product change; needs an agent-run live turn | **PARTIAL / RFL** |
| `UR-17.8` | live dialogue: substantive answer + search for scientific claims | not implementable as unit/product change; needs an agent-run live turn | **PARTIAL / RFL** |
| `UR-BAN-02` | no infinite tool-loop/retry; no giant prompt without useful material; physical bounds remain safety | no-growth stop; bounded loop/cycle tests existing; bounded orchestrator prompt test added | **PARTIAL** |
| `UR-06.5` | SILENT/REACT no search; Observer no per-window search before participation | Observer source test proves no search/tool path; SILENT/REACT tests already exist | **PARTIAL** |
| `UR-08.2` | 100%/95% search coverage on labeled open tasks; payload privacy; no false search claims | needs live/preprod labeled set and real provider calls; not a unit test | **PARTIAL / RFL** |

Rows remain PARTIAL; no VERIFIED. UR-A rows also remain PARTIAL.

## 2. Code change (`services/direct_execution.py`)

### 2.1 `ToolEvidence.tool_events`

Added a field to the existing single `ToolEvidence`:

```python
tool_events: tuple[dict, ...] = ()
```

Projection `_tool_events_from(raw)` keeps only machine fields from the existing envelope:
`round`, `tool`, `status`, `error_code`, `error_type`, `duplicate`, `attempt`,
`duration_ms`, `out_chars`, `truncated`, `metered`.
It deliberately drops `data`, args, URLs and snippets. `sources`,
`source_ids`, `tool_trace`, `search_*`, `published_at`/`source_links` remain as
before. This is one structure for both direct and initiative because both use
`_tool_evidence_from` through the one `run_tool_phase`.

### 2.2 Adaptive no-growth stop

Added `_has_evidence_growth(results)`: true only for a non-duplicate envelope
with `out_chars > 0` and `status == ok`. In `run_adaptive_chain`, after
each step and after the existing denied check:

```python
new_results = tool_results[results_before:]
if not _has_evidence_growth(new_results):
    stop_reason = "step_skipped"
    break
```

This makes the existing `step_skipped` branch reachable: a tool that returns
nothing (or a duplicate/error) no longer causes another orchestrator prompt.
Cycle detection, max steps/token/metered policy and the fuse are unchanged.

## 3. Verification

Commands from the worktree with the project venv, `PYTHONDONTWRITEBYTECODE=1`,
`-p no:cacheprovider`:

| Check | Result |
|---|---|
| `tests/test_unified_reply_ur_b_search_first.py` | **60 passed** (including 7 new UR-B tests) |
| `tests/test_asap8_v6_wc_direct_d04.py` | **35 passed** |
| `tests/test_ur_b_live_wiring.py tests/test_evol_evidence_routing.py tests/test_unified_reply_ur_b_no_topic_veto.py tests/test_unified_reply_ur_b_review_fixes.py` | **200 passed** |
| `tests/test_ur_turn_engine.py tests/test_ur_d_writer.py tests/test_ur_e_speech.py` | **52 passed** |
| `tests/test_asap7_direct_l1.py` | **37 passed** |
| `tests/test_ur_f_inspector_step2.py` | **19 passed** |
| `py_compile services/direct_execution.py` | exit 0 |
| test file syntax | `compile(...)` + pytest import passed |
| `git diff --check` | exit 0 |

New tests:
- `TestToolEvidenceOneStructure::test_live_search_exposes_timed_events_in_the_same_evidence`
- `::test_provider_failure_event_carries_error_and_time`
- `::test_event_projection_keeps_dedup_error_and_time_without_payload`
- `TestAdaptiveNoGrowth::test_empty_tool_result_stops_adaptive_instead_of_looping`
- `::test_empty_or_error_status_is_not_evidence_growth`
- `::test_orchestrator_prompt_without_material_is_bounded`
- `TestObserverNoSearch::test_observer_source_has_no_tool_or_search_path`

Before the fix, a probe with a distinct-call orchestrator and a router returning
empty strings did not stop (it was terminated after >120 s). After the fix the
new no-growth test asserts one dispatch and one orchestrator call, with
`chain_meta.reason == "step_skipped"`.

## 4. ToolEvidence facts now covered

- One class/owner: `services/direct_execution.ToolEvidence`; both live call
  sites (`direct_chat_service._l1_tool_phase`, direct and initiative) use the
  same `run_tool_phase` / `_tool_evidence_from`.
- `tool_events` carries status/error/dedup/attempt/duration/out_chars per call;
  `sources` carries `SourceRecord` with source id/tool/url/title/date/status;
  `tool_trace` remains the existing round/tool/ok/out_chars trace.
- `trace_fields()` is unchanged and still R17-safe; `tool_events` is internal
  and contains no raw tool payload.
- Pre-planning `ToolStateSnapshot` (`capabilities`, `announced`,
  `search_available`, `fetch_available`) remains resolved by
  `DirectChatService._resolve_turn_tool_state` before `_build_turn_request`/L1.
  The existing `test_initiative_receives_real_capabilities` covers the two-mode
  capability set.

## 5. Remaining / RFL

- **UR-17.7 / UR-17.8:** need a real agent-run live/preprod turn with the two
  dialogue questions and a trace; no unit/product change can prove generated
  content. No owner QA.
- **UR-08.2:** need the owner-approved labeled set and real provider run
  (100% explicit / ≥95% mixed; payload privacy; no false search claims). This is
  preprod evidence, not code.
- **UR-03.1 provider health:** current pre-planning state is capability/tool
  availability (`ToolStateSnapshot`), while live provider rate-limit/down is
  checked at execution. If “состояние поисковых провайдеров” means a live
  pre-planning health probe, that needs an architecture/product decision and is
  not added by this minimal slice. No new health probe, no threshold.
- **UR-BAN-02:** physical API/timeout/resource/Telegram bounds are unchanged;
  no new gate.
- **UR-06.5:** the Observer source has no search path; a live observer tick with
  a real scheduler remains preprod observation, not product change.
- No production SSH/deploy/LLM; no `progress_scope.json`/`workflow_state.md`;
  no map/status/deploy change; no owner QA.

## 6. Reviewer readiness

- Branch `fix/ur-b-tool-evidence`; code candidate `462cf1b22` (initial `85cc4e7c1`); evidence commit is on top of the code.
- Product/test diff: `services/direct_execution.py` + `tests/test_unified_reply_ur_b_search_first.py` only.
- Rows remain PARTIAL; ready for independent review of the two code changes and
  the new tests. No VERIFIED claim.
