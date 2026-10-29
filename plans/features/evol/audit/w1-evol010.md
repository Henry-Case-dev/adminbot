# W1 — EVOL-010 implementation report (embedding NameError → fake budget → backfill stalls)

Lane: EVOL-010, worktree `evol/impl` (base `f382bd87` = production 2.58.141 + docs).
Author: Builder (W1). Date: 30.10.2026. Inputs: `plans/current_task.md` §3 EVOL-010,
`backend-defects-audit.md` F1–F7, **authoritative** `base-revalidation.md` (root cause is
committed code, not a deployment defect).

## 1. Root-cause decision — REMOVE the vestigial CANARY-03 `.set()` (not restore)

Evidence chain (all on this worktree's Git history):

1. `git grep -n _LAST_EMBED_META HEAD -- services/` → **exactly one hit**: the `.set()` call at
   `services/embedding_control_plane.py:1373`. No definition, no `MODEL_SOURCE_*` constants.
2. Pickaxe: `git log --oneline -S _LAST_EMBED_META -- services/embedding_control_plane.py` →
   single commit `60789cff` (EMBED-IDENTITY-GAPS, master line), which introduced the ContextVar
   definition + constants + consumer + the `.set()` **together**. The production-line version of
   the file dropped the post-`:2465` tail machinery (definition/constants/consumer) but the
   `.set()` at `:1373` survived ⇒ deterministic `NameError` after every successful embed
   HTTP call (matches prod telemetry `embed transport error | error=NameError`, 4 burned
   attempts, fake `EmbeddingBudgetExhausted`).
3. Consumer check on the production base: `_compat_probe_once` **exists** here (`:3148`) but reads
   actual model/params from the embed **API response** via `_split_probe_response(...)` (`:3192`) —
   it never reads the `_LAST_EMBED_META` ContextVar. ⇒ the ContextVar channel has **no consumer**.

**Decision:** remove the dead 4-line `.set()` block (done, with an evidence comment at the site).
Restoring definition+constants+consumer would rebuild a telemetry channel nobody reads on this
line — a feature, not a hotfix. Half-state (definition without consumer) is forbidden by the test
`test_successful_embed_no_nameerror_after_http_200` (`assert not hasattr(ecp, "_LAST_EMBED_META")`).

**RED evidence (pre-fix code, reproduced in this worktree via `git stash` of ecp only):**

```
pool size: 1
HTTP embed_once OK (provider 200)      ← ×4 successful HTTP calls
embed transport error | error=NameError ← ×4 (fake classification)
RED: EmbeddingBudgetExhausted: embedding attempt budget exhausted (budget=4)
```

Exact production signature 2.58.141. PASS post-fix: same script shape in
`test_successful_embed_no_nameerror_after_http_200` (12/12 file suite green).

## 2. Changes (file → function)

`services/embedding_control_plane.py`
- `EmbeddingExecutor.embed` — removed the dead `_LAST_EMBED_META.set(...)` block (root cause);
  no-credential terminal now raises `EmbeddingNoUsableCredential`; retry-loop handles
  `handled == "code_defect"` → raises `EmbeddingCodeDefect(...) from exc` (no retry, no budget
  burn); final terminal after transport-retry exhaustion now raises honest
  `EmbeddingRetriesExhausted(...) from last_error`; docstring contract updated.
- new exceptions: `EmbeddingCodeDefect(EmbeddingControlPlaneError)` (non-retryable code defect),
  `EmbeddingRetriesExhausted(EmbeddingBudgetExhausted)`,
  `EmbeddingNoUsableCredential(EmbeddingBudgetExhausted)` (compat subclasses keep all existing
  consumers working — see §4); `EmbeddingBudgetExhausted` is no longer synthesized directly.
- new `_PROGRAMMING_ERRORS` tuple + `_is_programming_error()` (NameError, AttributeError,
  TypeError, KeyError, IndexError, ImportError [incl. ModuleNotFoundError], SyntaxError
  [incl. IndentationError], UnboundLocalError, RecursionError). TimeoutError/ConnectionError/
  OSError family deliberately NOT classified (stays transport-retryable); arithmetic errors left
  unclassified (potentially data-dependent — documented boundary).
- `_SERVICEABILITY_ERRORS` += `EmbeddingCodeDefect` (batch-policy T-4878: text-only without
  retry storm is correct for a deterministic defect).
- `_on_error` — first branch: programming error → `logger.error("embed code defect | ...",
  exc_info=True)` (full traceback to internal logs, no key material — R17) → return
  `"code_defect"`; no credential-health marking, no AIMD, no quota state synthesis.
- `__all__` += the three new names.

`services/summary_memory.py`
- `_embed_fail_reason` — honest reason codes **before** the parent-class mapping:
  `EmbeddingRetriesExhausted → provider_unavailable`, `EmbeddingNoUsableCredential →
  provider_unconfigured` (both in `mca_events.REASON_CODES` whitelist);
  `EmbeddingCodeDefect → None` (honest unknown: no `code_defect` code exists in the whitelist and
  mca_events is not this lane's file — the state name remains visible via error_json/state).
- `backfill_archive_vectors` / `backfill_graph_fact_vectors` — honest failure classification:
  `EmbeddingCodeDefect` → ERROR log with `exc_info=True` + "code defect … backfill stopped";
  everything else → WARNING "deferred (<exception class>)". `break` kept (bounded); next
  maintenance tick (600 s) re-runs the idempotent backlog query — backfill survives restart by
  design (stateless SELECT of missing vectors), no durable registration needed for it.
- `_generation_hint` (+ new `_index_source_empty`, `_reconcile_source_empty_building`) — F6 fix,
  see §3.

`tests/test_evol010_embedding_defects.py` — new (12 tests, CONTRACT owner=EVOL-010).

Not touched (verified): `services/mca_vision.py`, `handlers/`, `database.py`,
`services/smart_cache.py`, `web/**`, `services/prompt_migrations.py`, `services/prompt_registry.py`,
`services/mca_events.py`, `services/graphrag_rebuild.py` (only imported).

## 3. F6 investigation — "build pending — durable job missing" (since 2.58.114)

Root cause found (within scope evidence):

- The rebuild **source** for smart_archive is `smart_archive_facts` — legitimately **empty** on
  production (`plans/features/_audit-2026-10-23/release-258114/deploy.md` observation
  «smart_archive gen1/gen2 — building, smart_archive_facts=0»): archive facts are written only by
  the L3-compress path (`summary_memory` `save_archive_fact` at the compress loop), which does not
  run under infinite retention.
- The scheduler honestly refuses to build an empty source: `maybe_schedule_rebuilds` →
  `resolve_index_compat` → `STATE_SOURCE_EMPTY → continue`; `ensure_current_generation` →
  `_source_empty` → no registration. So **no durable job can ever appear** for that row — by
  design, nothing to vectorize.
- But the vec registry holds **zombie `building` generations** (registered before the
  D10/T-5255 source-empty guard existed). Nothing reconciles them: `run_job` never runs (no job),
  so the honest `knn_source_empty` terminal can never be written by the job itself. The panel then
  reports `building / FTS-only (A06) / build pending — durable job missing` forever — a false
  alarm implying a lost job.

Fix (honest, no history re-import, no vector rebuild, no DDL):
1. `_generation_hint`: `job is None` → query source emptiness (reuse `graphrag_rebuild._source_empty`,
   fail-open to "not empty") → honest suffix `build pending — source empty (nothing to vectorize)`;
   a non-empty source without a job keeps the real `durable job missing` alarm.
2. `_reconcile_source_empty_building`: zombie in-progress row (`building/building_target/
   catching_up/ready`) + empty source + no job → `superseded` via the existing §8.5 API
   `supersede_building_generations` (registry status only; vectors/source rows untouched;
   `_GEN_LOG_STATE` invalidated so the next WARN shows the new state). Safe for the future:
   `register_embedding_target_generation` ignores only live statuses, so when facts appear a NEW
   building generation is registered and built normally (proven by test (e)).

Backfill restart-survival: the fill-missing backfill is idempotent (SELECT rows missing from the
vec table) and re-driven by `embed_recovery_tick` every 600 s — it survives restart
structurally; the durable `task_jobs` machinery (full rebuilds) already persists across restart
and needed no change. The "missing durable job" was the zombie-registry artifact above.

## 4. Honest classification semantics (after fix)

| Signal | Old (2.58.141) | New | Retry? | Budget burn? | Fake quota state? |
|---|---|---|---|---|---|
| Programming error (NameError, AttributeError, TypeError, KeyError, IndexError, ImportError, SyntaxError, UnboundLocalError, RecursionError) | `transport` WARNING (name only) → retries → `EmbeddingBudgetExhausted` (`quota_group=unknown`, `next_allowed_at=-`, reason `budget_exceeded`) | `EmbeddingCodeDefect` (serviceability terminal), ERROR log with full traceback (`raise … from exc`), reason_code=None (honest unknown) | no | no | no |
| Transport 5xx/timeout | retries ≤4 → `EmbeddingBudgetExhausted` | retries ≤4 (unchanged) → `EmbeddingRetriesExhausted` (compat subclass of `EmbeddingBudgetExhausted`) | yes (≤4, backoff) | by design | no (honest name; `_embed_fail_reason → provider_unavailable`) |
| 429 / rate limit | defer → group cooldown → `EmbeddingGroupCoolingDown(group_id, next_allowed_at)` | unchanged (the only genuine provider quota path) | defer by `next_allowed_at` | no | n/a (genuine) |
| No usable credential (auth_failed/disabled) | `EmbeddingBudgetExhausted` | `EmbeddingNoUsableCredential` (compat subclass) | no | no | no (`provider_unconfigured`) |

Consumer compatibility (verified by tests, no consumer edits): `graphrag_rebuild.run_job`
is_busy check `isinstance(exc, (EmbeddingBudgetExhausted, EmbeddingConcurrencyBusy))` still
catches both new subclasses → same bounded paused_provider flow; `EmbeddingCodeDefect` matches
neither cooling/busy nor the name heuristics (`Server/Timeout/Transport/Connection`) → honest
terminal FAILED with reason = class name; `_SERVICEABILITY_ERRORS` covers all three terminals for
the batch text-only policy.

## 5. Test results (focused only, as mandated)

Command: `C:\Code\Python\adminbot\.venv\Scripts\python.exe -m pytest … -q` (cwd = worktree).

| Suite | Result |
|---|---|
| `tests/test_evol010_embedding_defects.py` (new) | **12 passed** |
| `tests/test_embedding_control_plane_asap4.py` + `tests/test_asap8_f8_embeddings.py` | 79 passed |
| `tests/test_asap44_graphrag_batch_breaker.py` + `tests/test_summary_memory.py` | 90 passed (1 pre-existing unrelated warning) |
| `tests/test_graphrag_identity_reindex.py` + `tests/test_asap6_embedding_generations.py` + `tests/test_embed_identity_compat.py` | 56 passed |
| `tests/test_asap5_embedding_identity.py` + `tests/test_memory_health.py` | 19 passed |
| `python -m compileall services -q` | **EXIT=0** |

Acceptance mapping (ТЗ EVOL-010 / brief tests):
- (a) NameError-class → `code_defect`, no retries burned (`stats.http_calls==1` vs prod 4), no
  `EmbeddingBudgetExhausted` — `test_programming_error_is_code_defect_no_retries_no_budget`,
  `test_code_defect_is_serviceability_terminal`, `test_programming_error_classification_boundary`.
- (b) transport error → retries preserved (`llm.calls==4`) —
  `test_transport_error_retries_preserved_honest_terminal`; credential/429 semantics unchanged —
  `test_no_usable_credential_honest_class`, `test_rate_limit_defer_semantics_unchanged`.
- (c) backfill end-to-end with stubbed embedder, `processed>0` (full executor path: adapter →
  embed_once → success → vec rows written) — `test_backfill_processes_batch_after_fix`.
- (d) deterministic embedder failure → honest stop, no infinite loop, "code defect" log —
  `test_backfill_deterministic_failure_honest_stop`.
- (e) F6 zombie reconciliation + future build unblocked —
  `test_source_empty_zombie_reconciled_and_hint_honest`; non-empty source keeps the real alarm —
  `test_nonempty_source_keeps_durable_job_missing_alarm`.
- REGRESSION (root cause): successful embed returns vectors, no NameError, no half-state channel —
  `test_successful_embed_no_nameerror_after_http_200`.
- Full suite NOT run (per brief). No live/provider check required: the defect was deterministic
  committed code; RED reproduction above stands in for the live observation.

## 6. Requirement guardrails

- Text-only facts: preserved everywhere (`_save_graph_fact_embedding` fail-soft unchanged;
  batch-policy text-only semantics unchanged); no dedup/quota resets; no protective mechanism
  disabled; no embedding model/identity changes; FTS degradation stays honest (suffix now names
  the true reason).
- `plans/current_task.md`, `plans/workflow_state.md`: not touched. No commits made (orchestrator
  owns commits). Write scope respected: only `services/embedding_control_plane.py`,
  `services/summary_memory.py`, `tests/test_evol010_embedding_defects.py`, this report.

## 7. Incidental findings

- `related-nonblocking`: `_call_with_segmentation` raises bare `EmbeddingControlPlaneError` on a
  vectors!=inputs provider contract violation (`:~1520`) — propagates raw to callers (honest but
  unnamed); candidate for a dedicated class in a later wave.
- `related-nonblocking`: `mca_events.REASON_CODES` has no `code_defect` code; `EmbeddingCodeDefect`
  therefore carries no reason_code (honest unknown). One-line whitelist addition in mca_events
  (other lane's file) would make it explicit.
- `unrelated/pre-existing`: `smart_archive_facts` stays empty under infinite retention by design;
  if the owner ever wants the L3 archive indexed, that is a product decision, not a defect.

## 8. Follow-up (same lane, 30.10.2026): `code_defect` added to mca_events whitelist
`REASON_CODES` += `"code_defect"` (pattern-conform comment, §17.2 расширяемый; соседняя правка
`empty_content` не тронута); `_embed_fail_reason(EmbeddingCodeDefect) → "code_defect"` — телеметрия
`EMBED_API_FAILED` теперь несёт честный `reason_code=code_defect` (runtime-проверка `build_event`:
код проходит whitelist, bogus-коды по-прежнему честно отбрасываются). Tests re-run: 12/12 +
79/79 executor/backfill seams green.
