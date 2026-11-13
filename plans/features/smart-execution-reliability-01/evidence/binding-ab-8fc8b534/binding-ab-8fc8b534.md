# SMART-EXECUTION-RELIABILITY-01 — binding evidence, stages A+B

- **Candidate (code + tests):** `8fc8b534ebb993fca29fc2f86b7aef2d95796660`
  - `95ed5e1a` — implementation A+B
  - `027282a7` — contract tests + explicit-policy chain honesty
  - `8fc8b534` — OFF-beats-explicit-ceilings tests (simple/adaptive)
- **Base:** `d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199)
- **Branch / worktree:** `smart/ab`, Epic `smart-execution-reliability-01`, unit `binding-ab`
- **Contract:** `plans/features/smart-execution-reliability-01/architecture-contract-part1.md` §1–§3, §6 (stages A, B)
- **Slice scope:** A = budgets OFF predicate/resolution; B = single tool-loop policy.
  Stage C (SourceReader/context/evidence caps) and G (finalization branch) are **not** touched here.
- **No** deployment, DDL, production settings or chat-override changes in this candidate.

Diff vs base (23 files, +1740/−669):

```
config/settings.py                            |  20 +-
services/budget_gate.py                       | 192 +++-
services/diagnostic_collector.py              |  16 +-
services/direct_chat_service.py               |   9 +-
services/direct_execution.py                  | 342 +++---
services/response_extent.py                   |   9 +-
services/tool_loop.py                         | 711 ++++++----
services/tool_router.py                       |  18 +-
tests/ (15 files incl. new test_smart_exec_ab_round1114.py) 
```

## A — budgets OFF

Canonical predicate remains `budget_gate.budgets_enabled(chat_id)`;
resolution stays chat → global → factory `settings.BUDGETS_ENABLED`.

- `services/budget_gate.py`: new `BudgetState{enabled, source, chat_id,
  stale, known}` + `resolve_budgets()`; per-scope last-known-valid cache
  (bounded, LRU-ish, `reset_cache()`/`last_known_state()` for tests/diagnostics).
  Read error → last-known-valid (`source=last_known`, `stale=True`); if none →
  global layer with explicit `known=False`; if that also fails → factory default
  with `source=unknown`, `known=False`, WARNING. A known OFF can never become ON
  because of a transport/DB error; the previous "fail-open True" is gone.
- `services/tool_loop.py`: single `ChainLimits`/`resolve_chain_limits()` used by
  the model loop; `enforce = budgets_enabled AND TOOL_CHAIN_LIMITS_ENABLED`.
  `MCA_TOOL_MAX_*` factory values are `0` = policy not set. Nothing in the loop
  re-enables volume enforcement behind the predicate: legacy kill-switch only
  narrows, never widens; cannot override OFF.
- `services/direct_execution.py`: `ChainBudget` takes the effective predicate;
  `DIRECT_ORCHESTRATOR_MAX_STEPS/_TOTAL_TOKENS/_METERED_CALLS` bind only with
  budgets ON; `0` means not declared. `resolve_orchestrator_budget` keeps window
  derivation as payload sizing/observability only.
- Stats continue with OFF: `metered`, `cost_calls`, `usage`, duration, chain
  events, `chain_meta.limits` are always produced (test
  `test_stats_continue_when_off`; `metered`/`usage` asserted on the envelope).

## B — one tool-loop policy

Removed (contract §1 rows): `TOOL_MAX_ROUNDS`, `_TOOL_CALLS_PER_ROUND_MAX`,
`TOOL_MAX_TOTAL_CALLS`, `_TOOL_MAX_SAME_CALL`, `TOOL_CHAIN_MAX_METERED_CALLS`,
`PLAN_MAX_STEPS`, `PLAN_MAX_REPLANS`; per-round `tool_calls[:2]`; plan slice
`raw_plan[:PLAN_MAX_STEPS]`; universal 360 s chain deadline default;
window-derived step cap in the adaptive chain.

Kept / strengthened:
- One progress-driven `while` loop for Direct/L1/plan/checkup/inspect/
  SourceReader/web/factcheck through the existing `chat_with_tools` +
  `run_tool_phase`; no second loop, no progress-evaluator LLM, no lexical routing.
- Every requested call gets an envelope with its original `tool_call_id`
  (additive when `MCA_TOOL_RESULT_ENABLED=true`) and a `role:"tool"` message, so
  `assistant(tool_calls) → tool(each id) → assistant` stays valid; denied calls
  now receive a structured `{"status":"denied","reason":…,"limit":…}` instead of
  a dropped id.
- Dedup identity by normalized args: terminal (`retryable=false`) repeat and
  non-idempotent success/`delivery_unknown` repeat are not re-dispatched;
  retryable failures retry up to `MCA_TOOL_TRANSIENT_RETRIES_MAX + 1` attempts;
  changed args/cursor is a new identity.
- Completion: model final answer; `no_progress` (2 rounds without any new
  dispatch); confirmed technical limit (explicit policy/fuse); cancellation;
  safety stop.
- Fuse (`MCA_TOOL_CHAIN_TIMEOUT_SECONDS > 0`, factory `0` = none) is operator
  declared, checked only at round/call boundaries, never cancels in-flight work,
  keeps accumulated evidence and reports `chain_timeout`.
- Simple chain keeps full cardinality: `_SIMPLE_WAVE_CONCURRENCY = 4` throttles
  only simultaneous dispatch; every ready step is executed (previously the tail
  was silently dropped when the slot budget ran out).
- Cursor TTLs (`diagnostic_collector`, `tool_router`) decoupled from the removed
  chain constant; same 360 s behaviour, imports fixed (no ImportError).

## RED → GREEN (same probe, base vs candidate)

Probe: `evidence/binding-ab-8fc8b534/probe-base.json` /
`probe-candidate.json` (scenario source in the run dir; copied here).

| Scenario | Base `d20a7f73` | Candidate `8fc8b534` |
|---|---|---|
| 5 rounds × 3 distinct calls | 4 LLM rounds, 6 dispatched, `chain_call_limit`, tool msgs/request `2,4,6` | 6 LLM rounds, **15 dispatched**, `ok`, tool msgs `3,6,9,12,15` |
| 6 identical rounds | 2 dispatched, `round_limit` | 1 dispatched (dedup), `no_progress` |
| Legacy constants present | `TOOL_MAX_ROUNDS, _TOOL_CALLS_PER_ROUND_MAX, TOOL_MAX_TOTAL_CALLS, _TOOL_MAX_SAME_CALL, TOOL_CHAIN_MAX_METERED_CALLS, PLAN_MAX_STEPS` | none |
| Factory `MCA_TOOL_*` defaults | `6 / 4 / 2 / 360.0` | `0 / 0 / 0 / 0.0` |
| Chain fuse default | `360.0` | `0.0` |
| 9-step plan normalized | 6 steps | 9 steps |
| Read error with no cached value | `budgets_enabled=True` (fail-open, no metadata) | `known=False`, `source=unknown`, `stale=True` (explicit) |
| budgets OFF + `MCA_TOOL_MAX_TOTAL_CALLS=2` | 2 of 3 dispatched (policy leaked) | 3 of 3 dispatched, `ok` |

Additional RED→GREEN already asserted by the updated suites (each fails on the
old expectation, passes now): per-round truncation `2 → all`,
`round_limit → no_progress`, total cap `6 → no cap`, same-call `≤2` identity
dedup, metered default `4 → 0` with explicit-policy test, plan `6 → 9`,
`-1.0`/`360` deadline semantics → operator fuse `>0` only.

## Focused verification (candidate 8fc8b534, venv Python)

- **A/B + adjacent suites (21 files, incl. new contract file):**
  `638 passed, 2 failed` — both failures are the pre-existing stale-tag bounds
  guards, proven on base in `pre-existing.txt`.
- **New durable contract file** `tests/test_smart_exec_ab_round1114.py`:
  `15 passed` (budgets OFF/ON, last-known-valid, unknown state, OFF beats
  legacy/env/explicit ceilings in model and both chain paths, stats, L1 control
  >4 rounds / >6 calls / >2 per round, no_progress, retryable retry, no default
  deadline, plan not truncated).
- **Broad batch (25 files):** base `8 failed / 1092 passed`; candidate
  `8 failed` (same set) plus the 2 tag-baseline guards that cannot run in the
  archive; see `pre-existing.txt`.
- Suites that asserted the revoked limits were updated to the owner contract
  (`test_tool_loop`, `test_smoke_round1016_tool_loop`, `test_tool_calling_round1015`,
  `test_tool_chains_round1026`, `test_tool_coordinator_round1026`,
  `test_agentic_ai_round1020`, `test_factcheck_tools_round1020`,
  `test_er08_limits_context`, `test_mca11_tool_result_round1028`,
  `test_mca11_chain_stages_round1028`, `test_mca23_phase2`, `test_bgs05_budgets`,
  `test_tool_download_quality_round1017`, `test_asap8_v6_wc_direct_d04`).

## Effective configuration (acceptance-critical)

| Setting | Source / default | Test env (observed) | Production (recon 2026-11-14) | With this candidate |
|---|---|---|---|---|
| `flags.budgets_enabled` | chat → global → `settings.BUDGETS_ENABLED=true` | chats resolve via DB-less fallback → factory `true` (NEW: explicit `known=False` only when unreadable) | global row `false`; both chats override `false` → **OFF** | OFF predicate is authoritative; enforcement cannot be re-enabled by env/inner flags |
| `MCA_TOOL_MAX_TOTAL_CALLS` | env-only, factory `0` | `0`, tests set explicit values | not set | `0` = no cap; explicit `>0` only with budgets ON |
| `MCA_TOOL_MAX_METERED_CALLS` | env-only, factory `0` | `0` | not set | observational counter; explicit policy only |
| `MCA_TOOL_MAX_SAME_CALL` | env-only, factory `0` | `0` | not set | identity dedup; explicit policy only |
| `MCA_TOOL_CHAIN_TIMEOUT_SECONDS` | env-only, factory `0.0` | `0.0` | not set | no universal deadline; `>0` = operator fuse > |
| `TOOL_CHAIN_LIMITS_ENABLED` | env-only, factory `true` | `true` | `true` | can only narrow policy; cannot widen against budgets OFF |
| `DIRECT_ORCHESTRATOR_MAX_*` | env/settings, unset = `0` | unset (`0`) | unset | bind only with budgets ON |

Stored chat overrides and production values were **not** modified by this
candidate (no settings/DDL writes). Production is OFF today, so the new
factory `0` values cannot change production behaviour before an operator
explicitly sets a policy; with OFF they are ignored regardless.

## Requirement coverage (map IDs)

| ID | Evidence |
|---|---|
| SXR-A1-01 | `budget_gate` last-known-valid + explicit unknown; `ChainLimits.enforce`; OFF beats legacy/env/explicit ceilings (3 tests + probe row 8); stats tests |
| SXR-A2-01 | removed constants/dead config; `_volume_skip` gated by `enforce`; plan/calls not truncated; adaptive step/token ceilings only when ON (tests) |
| SXR-A2-02 | untouched provider/transport timeouts, model window, HTTP/file safety (stage C files untouched); cursor TTL preserved; fuse opt-in and evidence-preserving |
| SXR-A2-03 | dedup identity + side-effect guard + retry policy; `test_cancellation_propagates_clean`; RBAC/SSRF/secrets code untouched |
| SXR-A2-04 | `worker_budget`, image quotas, YooMoney untouched; metered/cost observational only |
| SXR-A3-01 / A3-02 | enforcement path walked: budget_gate → ChainLimits → model loop/ChainBudget → envelopes/events; limits map in contract part1 §1 with the rows implemented here (A/B) and rows deferred to C (`source_reader`, composer, evidence serializer) |
| SXR-B1-01 | no round cap; probe 6 LLM rounds; `no_progress` instead of `round_limit` |
| SXR-B1-02 | all calls dispatched (L1 control 15/15), per-call tool result/denied with `tool_call_id`, valid sequence on every request |
| SXR-B1-03 | total cap removed; probe 15 calls, no cap by default |
| SXR-B1-04 | metered/cost/usage separated from enforcement; read-only tools never cost-limited; stats with OFF |
| SXR-B1-05 | `_reuse_reason`: terminal/side-effect repeats not re-dispatched, retryable retried, changed args = new identity |
| SXR-B1-06 | 360 s default removed; per-tool/provider timeouts untouched; fuse only `>0`, boundary-checked, evidence kept |
| SXR-B2-01 | one `chat_with_tools`/`run_tool_phase` policy; no second loop; plan + model rounds share `ChainBudget`/`ChainLimits` |
| SXR-B3-01 | budgets ON without legacy 4/2/6/4; explicit policy tests; no new catalog/settings keys |
| SXR-B4-01 | six completion conditions implemented and covered |

## Remaining risk / not proven here

- Stage C (`source_reader.py`, composer/evidence caps) and G (finalization
  branch) are separate slices; their historical caps are **not** changed by this
  candidate and remain in force (owner-mapped to C/G).
- `usage`/`cost` for externally metered tools still depends on provider usage
  data; unchanged by this candidate.
- No production/live verification was performed or claimed; the slice requires
  independent review before any deploy, and stage E2E with real provider is a
  later slice.
- Pre-existing failures listed in `pre-existing.txt` are outside this candidate
  and reproduced on base.
