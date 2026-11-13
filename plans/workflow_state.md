# Workflow State

Task: smart-execution-reliability-01 (queue 1, P0, owner 2026-11-14) — execution reliability + SELF-DIAG stage H
Task source: plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md
Status: in_progress
Primary phase: build
Active feature: smart-execution-reliability-01
Active lanes: Builder ses_e2b148a99ffeXdFEYwNdISc2RQ (A+B budgets OFF + tool-loop); Builder ses_e2b14454cffep2Jszi7h96sqoM (D capacity); Builder ses_e2b140a5dffeO1TPJIkdmf9e52 (C1 SourceReader); PM ses_e2b280b15ffeehWbOFmhnZUT7r (map committed, report pending)
Join barriers: wave-1 candidates -> independent review -> wave 2 (C evidence, G finalization, E local-first, F SafeFetch, I1-I6) -> SELF-DIAG H -> acceptance L1-L8 -> one release + smoke.
Last verified: production 2.58.199 at d20a7f73 (schema 47, no DDL, rollback 25876167); identity verified_deployed; journal rc=0 as service user. Recon (commit 002c1726): budgets_enabled=false global/both chats/DM; TOOL_CHAIN_LIMITS_ENABLED absent -> true (4/2/6/360 active); model z-ai/glm-5.3-flash-uncensored @ nano-gpt; CHAT_UNKNOWN_MODEL_WINDOW factory 16384 but async catalog resolves 1,048,576 verified (max_output 32768); SELF_DIAG_LOCAL_REPO_ROOT empty -> local provider off; checkup trace 3f9bd22a fully reconstructed (2 destination_blocked, chain_call_limit 6/4, tool_step_limit, degraded 87 chars, stub text); SafeFetch cause proven = single DNS snapshot 140.82.114.5 vs real peer 140.82.112.6 (GitHub A-record rotation), TLS valid, no proxy/IPv6; I1 spool OperationalError (spool now absent, table alive 28,678 rows, exact SQLite error not logged); I2 real backlog (cursor +50/run vs ~7,200 rows/day; pending 14,399 since 2026-08-15); I4 codes are sha256 prefixes not in REASON_CODES (more unmapped codes exist).
Next unlocks: wave-1 review -> wave 2 builders (F with proven cause; E local-first; G finalization; C evidence transport; I1/I2/I4) -> H -> release.
Next execution: awaiting_children
Review: pending per slice
Deployment: verified 2.58.199 @ d20a7f73 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | map committed (99 reqs, 13 slices); new epic intake pending PM report; self-diag 147/41/16/2; vmq 1/6/0/63
Updated: 2026-11-14T01:02:00+12:00

## Facts

- Lineage: `master` is not an ancestor of `release/2.58.199` (377/1446 divergence). All new work must branch from the release line `d20a7f73` (builders instructed so). Do not merge master into the release branch.
- Owner decisions frozen in contract parts 1–2: budgets OFF disables artificial limits; remove 4/2/6/4 and 360 s product deadline; one tool-loop; structured result per requested call; SourceReader caps removed with real file safety and per-request counters; evidence must reach the LLM payload; unknown window 1M with single resolver and NanoGPT exact-ID; local-first own code; GitHub via SafeFetch without weakening SSRF/TLS; mandatory finalization preserving evidence; anti-hardcode; security/settings preserved; fixes active after release.
- SafeFetch fix direction (proven cause): the connection must pin/validate against the pre-resolved addresses of the same resolution (peer 140.82.112.6 vs snapshot .114.5 is legitimate GitHub rotation), not a single stored IP; keep anti-rebinding by connecting to a validated address rather than re-resolving and rejecting. No trusted-by-name bypass, no TLS/redirect changes.
- I2 fix direction: increase real throughput/processing per run to drain pending (not the threshold, not a cursor rewind); cursor +50/run cannot catch ~7,200 rows/day.
- I1 requires logging the actual SQLite exception class/message safely and reproducing the write path; do not drop the spool or old rows.
- I4 requires decoding the sha256-prefix producer codes and aligning the `mca_events` registry; do not collapse unknown codes into one.
- Wave 1 write scopes are disjoint; shared serializer/composer/settings-budget keys are serialized for wave 2.
