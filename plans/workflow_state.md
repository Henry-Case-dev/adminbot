# Workflow State

Task: smart-module-semantic-routing-p0 (P0/P1 live, quantum live) plus the ordered queue
Task source: plans/owner_inputs/2026-11-10-smart-module-semantic-routing-p0.md and the 10.11 corrections
Status: in_progress
Primary phase: retrieval fixes committed, review and real-archive re-measurement in flight
Active feature: vmq-onto-01 VMQ-MEM (measurement done, mechanical fixes in flight)
Active lanes: ses_e3c3677f4ffe51yOk8PH8922xN (Reviewer: retrieval fixes 7bc8545a); ses_e3c3677f3ffefFdap7hWH3Y6jr (DevOps: re-measure 7bc8545a + year-less probes); ses_e3c2e17f0ffeGxag3wkaVrva8x (Architect: year-bias root cause); ses_e3c2de8b9ffeDjQYcXty0Em277 (PM: register VMQ-TIME defect)
review + re-measurement -> deploy -> confirm the old-episode block and the year-window timing in production
Last verified: RETRIEVAL FIXES COMMITTED as 7bc8545a (parent c99d64c7) — canonical SHA; my earlier 846a00c0 had the identical tree 89c5ffbcdd82b812f62f794ae6569842fbfec4ac, was replaced on the branch by the builder's commit and is now unreachable, with an empty diff between the two, so no work was lost. Content: episodes capped at half the history slice so real messages reach the Old_Episode block; msg:<row> accepted as an anchor through target_row_id with the tg path untouched; time-ordered FTS plan for year windows with honest coverage.sampling and truncated. Builder measurements on a real copy of the archive (1 928 453 messages): the old rank plan in a 2023 window did not finish within a 90 s watchdog (4.03 M VM steps) and reproduces the observed 300 s / 1223 s, while order=time returns 40 rows in 0.22 s (3.36 M VM steps, years [2023]); the same query without a window takes 1.12 s. Integration test on real SQLite: with 12 episode rows and 6 old messages the slice is 4 episodes + 4 messages and the block is non-empty with real text, while an irrelevant query yields an empty block and does not increment direct_old_episode_empty_total. Suite: 1947 passed / 16 failed on the branch versus 1934 / 17 on c99d64c7, every failing ID a subset of the base set (llm_client `sent=` doubles, REASON_CODES 341 vs 330, soul1 observer gates), so no regression. Honest limits: the multi-year asymmetry of ordinary questions is NOT fixed (RAG_Memory still 2026 in classes A-D, subject channel unchanged); that remains an architect decision, not part of these three defects.
Next unlocks: deploy 7bc8545a (three measured defects) -> year-bias fix scoped by the root cause -> parity rows; then the queue with UNIFIED-REPLY, PVR-FC, BEHAVIOR-GATES, EPIC-EXPERIENCE and MOD-ACL M4
Next execution: awaiting_children
Review: approved (P0-A 468ee956, P0-B 67063aa5, P1 9f862b0f, nostalgia 6674811f, quantum 629743f9); retrieval fixes pending review
Deployment: verified (2.58.179 @ 32e018b9, schema 47)
Human gate: none
Progress scope: plans/progress_scope.json | fresh — 71/71 owner inputs reconciled; aggregate 3993/6283 requirements (63%), 13/49 tasks
Updated: 2026-11-10T20:30:00+12:00

## Retrieval-fix commit (factual)

Commit 846a00c0 on integ/unify-release (parent c99d64c7), 7 files, +655/-39: services/database.py, direct_chat_service.py, direct_context_composer.py, mca_retrieval_context.py, summary_memory.py, tool_router.py and a new tests/test_vmq_mem_retrieval_fixes.py. Verified locally by me: the new suite is 12 passed in 5.7 s and the combined retrieval/direct/schema set is 185 passed in 20 s, so no test hang exists — the earlier stall was the full 19k suite, not the fix. The work had been sitting uncommitted in the worktree while the builder waited on background runs; it is now preserved as a commit.

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
