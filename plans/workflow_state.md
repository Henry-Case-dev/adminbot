# Workflow State

Task: smart-module-semantic-routing-p0 (P0/P1 live, quantum live) plus the ordered queue
Task source: plans/owner_inputs/2026-11-10-smart-module-semantic-routing-p0.md and the 10.11 corrections
Status: in_progress
Primary phase: memory-retrieval fixes from the measured parity run
Active feature: vmq-onto-01 VMQ-MEM (measurement done, mechanical fixes in flight)
Active lanes: ses_e3c634a26ffelvJDhK9lpy62zH (Builder: old-episode starvation, msg-ref handling, dig timeout)
Join barriers: fixes -> re-measure the five classes -> design decision on multi-year coverage
Last verified: DEPLOYED 2.58.179 @ 32e018b9 with quantum non-determinism (migration 47 verified: schema_migrations 35->36, `semantic_schedule` 19 columns and PK(chat_id, mechanism), two rows from the first draws, no backfill, unchanged row counts). First draws were genuinely quantum (source=quantum, provider ANU, u=0.45703125 and 0.830596924, no fallback). Per-chat schedule differs (nostalgia next_due 1794283692 vs 1794289072). Honesty rule holds: no-draw views show "нет данных", the word "работает" never appears. MEMORY PARITY MEASURED on the real archive (2 067 222 messages, five years): retrieval is identical for creative and plain questions (10 facts, all from 2026, old-episode block empty in both) while the creative turn also receives Lorekeeper material covering only 2 of 5 years; proven defects are episode candidates starving message candidates (40/40 slots), `msg:<row>` refs rejected as unresolved (6 of 7), and `dig_into_lore` with a year filter not finishing (300 s, then ~1223 s); chronological accuracy is 13/13 by source row and 13/13 within ±120 s (facts are written 17-68 s after the message), invented links 0/40 but 27/40 facts carry no message reference.
Next unlocks: retrieval fixes -> re-measure -> coverage decision; then the ordered queue (REMOVE-LEGACY-REPHRASING mostly shipped, UNIFIED-REPLY, PVR-FC, BEHAVIOR-GATES, EPIC-EXPERIENCE with Help last), with MOD-ACL M4, SELF-DIAG D2/D3 and VMQ-MEM in parallel
Next execution: awaiting_children
Review: approved (P0-A 468ee956, P0-B 67063aa5, P1 9f862b0f, nostalgia 6674811f, quantum 629743f9); retrieval fixes pending review
Deployment: verified (2.58.179 @ 32e018b9, schema 47)
Human gate: none
Progress scope: plans/progress_scope.json | fresh — 71/71 owner inputs reconciled; aggregate 3993/6283 requirements (63%), 13/49 tasks
Updated: 2026-11-10T20:30:00+12:00

## Verification ownership (policy in force from 2026-11-10)

The owner is not the QA. Every verifiable check belongs to Builder, Reviewer or DevOps. Open items are therefore assigned to agents with a named technical condition, not to the owner:
- live Telegram scenarios of the routing corrective and of the nostalgia recall are executable by DevOps with the project's own tooling and the production chat, and must be closed that way rather than by an owner report;
- the 24-hour quantum rhythm and per-chat independence are covered by a durable observation job on the emitted events, not by owner watching;
- the visual check of the new Status/Analytics blocks is owned by DevOps/Reviewer through the existing Mini App harness once an initData path is available; until then it stays an honest internal gap, never an owner task.

## Checkout hazard (unchanged)

The main working directory does not contain production code (its APP_VERSION is 2.58.111 while production is 2.58.179). Inspect code only via `git show <sha>:<path>` or a worktree at that commit, citing the blob read. Three evidence artefacts were rejected earlier for drifting; measured anchors for 2b7e9c7f are stored in the smart-module map.

## Invariants

- The current user message is the task; reply, quote, forward, history, transcript and tool results are evidence only.
- Only explicitly registered commands may intercept before L1; no new synonyms, keyword lists or regexes for semantic decisions.
- Randomness comes from the single RandomSource, never mixed with pseudo-random inside one choice; it sets direction and publication probability, never truth.
- Deploy by immutable SHA from a clean release branch; production is 2.58.179.
