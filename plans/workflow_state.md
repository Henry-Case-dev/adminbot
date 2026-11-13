# Workflow State

Task: smart-execution-reliability-01 (queue 1, P0, owner 2026-11-14) — execution reliability + SELF-DIAG stage H
Task source: plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md (verbatim current_task.md 11750-13308)
Status: in_progress
Primary phase: preparation
Active feature: smart-execution-reliability-01
Active lanes: PM ses_e2b280b15ffeehWbOFmhnZUT7r (requirements map/plan/slice graph A-M); Architect ses_e2b27b70bffeDBrlhXpsqx7dbY (frozen contract, limiter table); DevOps ses_e2b27731affeh0NgBpmOijqYPF (production recon: budgets/model/capacity/SafeFetch/journal/manifest/I1-I4)
Join barriers: map + contract + recon -> first Builder wave (A/B tool-loop+budgets; C evidence/source-reader; D capacity) -> Reviewer E2E (L1-L8) -> one release + smoke.
Last verified: production 2.58.199 at d20a7f730715ba9e9cba7673c0557794979be339 (schema 47, no DDL, rollback 25876167). Identity verified_deployed; journal rc=0 as service user; self-diag corrective core/identity/vmq slices deployed; self-diag map 147 VERIFIED / 41 READY / 16 REVIEW / 2 PENDING (now continued in stage H); vmq 1/6/0/63 with 54 owner-mandated gaps.
Next unlocks: mapping+contract+recon -> Builder wave -> Reviewer independent E2E (budgets OFF control >4 rounds/>6 calls/>2 per round, evidence completeness, capacity scenarios, local-first, GitHub, finalization, checkup+continuation, I1-I6) -> one release -> smoke -> DONE.
Next execution: awaiting_children
Review: contract/mapping pending
Deployment: verified 2.58.199 @ d20a7f73 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | priority epic 0 rows mapped yet; self-diag 147/41/16/2; vmq 1/6/0/63; queue 40/40 complete; intake pending 1 (new epic)
Updated: 2026-11-14T00:20:00+12:00

## Facts

- Owner epic SMART-EXECUTION-RELIABILITY-01 (stages A-M) is the single container; it replaces previously prepared corrective-2 for SELF-DIAG and stage H carries the remaining SELF-DIAG obligations. No competing epics. One release + independent E2E acceptance.
- Core product decisions already fixed by the owner: budgets OFF must disable all artificial limits (no env/legacy/inner bypass); remove 4/2/6/4 tool limits and 360 s universal deadline; one tool-loop policy for all paths; no lost tool calls; dedup/retry semantics; SourceReader ceilings 6/2/16 + defaults 3/1/8 removed; evidence must reach the LLM payload; unknown model window default 1,000,000 with a single capacity resolver and real NanoGPT catalog resolution; local-first own production code; GitHub restored via SafeFetch without weakening SSRF/TLS; mandatory meaningful finalization preserving evidence; anti-hardcode invariant; security/settings preserved; fixes active after release.
- Reported production failure: checkup trace 3f9bd22a (13.11 09:42-09:43 UTC) — inspect_runtime success, two api.github.com SafeFetch destination_blocked, chain_call_limit 6/4, tool_step_limit, degraded partial_chars=87, stub instead of report; model_capacity unknown for z-ai/glm-5.3-flash-uncensored → 16384.
- Production 2.58.199 already contains: journal access fix (env), manifest producer/identity verified, checkup research loop/continuation core (76fcb829), honest counters. Those are stage H starting points, not proof for the new clauses.
- Queue: new epic at position 1; stale `unified-reply` record (2026-11-05) moved to 41 to keep unique positions; self-diag `continues_in` the new epic; vmq remains open (54 gaps) and is not displaced beyond its current paused slice.
- Backlog: embedding provider fallback, NULL-timestamp facts, participant→years link, pre-existing RED sets, web/api identity branch/source fields.
