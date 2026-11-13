# Workflow State

Task: smart-execution-reliability-01 (queue 1, P0, owner 2026-11-14) — execution reliability + SELF-DIAG stage H
Task source: plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md
Status: in_progress
Primary phase: build
Active feature: smart-execution-reliability-01
Active lanes: Builder ses_e2b148a99ffeXdFEYwNdISc2RQ (A+B budgets OFF + tool-loop); Builder ses_e2b14454cffep2Jszi7h96sqoM (D capacity resolver, 1M default); Builder ses_e2b140a5dffeO1TPJIkdmf9e52 (C1 SourceReader caps); PM ses_e2b280b15ffeehWbOFmhnZUT7r (requirements map A-M); DevOps ses_e2b27731affeh0NgBpmOijqYPF (production recon/budgets/model/SafeFetch/I1-I4)
Join barriers: three builders -> independent review per slice; then C-evidence/G finalization, S5 local-first -> S6 GitHub, I1-I6, SELF-DIAG H, acceptance L1-L8 -> one release + smoke.
Last verified: production 2.58.199 at d20a7f730715ba9e9cba7673c0557794979be339 (schema 47, no DDL, rollback 25876167); identity verified_deployed; journal rc=0 as service user. Contracts part1/part2 committed; owner source captured verbatim.
Next unlocks: builder candidates -> Reviewer (reproduce 4/2/6/4 failure and GitHub error) -> merge wave 1 -> wave 2 (C evidence transport, G finalization, E local-first, F GitHub, I1-I6) -> H -> release.
Next execution: awaiting_children
Review: pending per slice
Deployment: verified 2.58.199 @ d20a7f73 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | new epic 0 rows mapped yet (PM mapping); self-diag 147/41/16/2; vmq 1/6/0/63; queue 40/40 complete
Updated: 2026-11-14T00:52:00+12:00

## Facts

- Owner decisions frozen: budgets OFF disables artificial limits (no env/legacy/inner bypass, last-known-valid OFF never flips ON); remove 4/2/6/4 tool limits and the universal 360 s deadline; one tool-loop policy for all consumers; every requested call gets a structured result with tool_call_id and a valid provider sequence; SourceReader 6/2/16 + 3/1/8 removed with real file safety and per-request counters; evidence must reach the LLM payload; unknown model window 1,000,000 with a single resolver and NanoGPT exact-ID resolution; local-first own production code; GitHub restored via SafeFetch without weakening SSRF/TLS; meaningful finalization preserving evidence; anti-hardcode invariant; security/settings preserved; fixes active after release.
- Production failure to reproduce: checkup trace 3f9bd22a — inspect_runtime success, two api.github.com `SafeFetchError destination_blocked stage=connect retryable=false`, chain_call_limit 6/4, tool_step_limit, degraded partial_chars=87, stub instead of report; `model_capacity: unknown z-ai/glm-5.3-flash-uncensored → 16384`.
- Wave 1 is deliberately limited to disjoint files: budget_gate/tool_loop/direct_execution (A+B), model_capacity/settings capacity keys (D), source_reader (C1). Shared files (serializer, composer, prompts, settings budget keys) are serialized.
- SELF-DIAG H starts from 2.58.199 proven pieces (journal env, manifest/identity, checkup research loop, honest counters); it must not re-implement them.
- No competing epics; self-diag `continues_in` this epic stage H; vmq remains open with 54 gaps.
