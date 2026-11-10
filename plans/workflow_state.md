# Workflow State

Task: smart-module-semantic-routing-p0 (P0/P1 live, quantum live) plus the ordered queue
Task source: plans/owner_inputs/2026-11-10-smart-module-semantic-routing-p0.md and the 10.11 corrections
Status: in_progress
Primary phase: retrieval fixes committed, review and real-archive re-measurement in flight
Active feature: vmq-onto-01 VMQ-MEM (measurement done, mechanical fixes in flight)
Active lanes: ses_e3b4ca1aaffeipMKhSh8CkNOQS (Builder: finish VMQ-TIME); ses_e3b44c3b1ffe4JWOMS05Qswhpn (Builder: avatar access verification); ses_e3b3e52a6ffeBPkuZi8fXG7kai (Builder: permission-front role_type fix MAC-DEF-01)
review + re-measurement -> deploy -> confirm the old-episode block and the year-window timing in production
Last verified: RETRIEVAL FIXES MEASURED ON A REAL COPY OF THE ARCHIVE at candidate 7bc8545a (tree 89c5ffbc, identical to 846a00c0). Before/after, same chat: the `<Old_Episode>` block was 0 characters in all five classes and is now 15 923 characters across 4 of 5 (3 912 / 2 483 / 0 / 5 241 / 4 287), with 2023, 2024 and 2025 material appearing for the first time; accepted message candidates went from 1 of 7 to 7 of 7 (56 candidates at top_k=40, none unresolvable); the `dig` query with year=2023 went from not finishing (300 s, then ~1 223 s) to 1.76 s with honest coverage.sampling=window_scan_by_time and truncated=true over a 129 482-message window. Class C (participant profile) is still empty at the default top_k because its eight slots hold 4 episodes and 4 graph facts and no messages; at top_k=40 the block appears (2025). The two year-less probes confirm the separate time-bias defect: a person question reaches only 2026 in RAG and episodes while the profile reaches 2023/2025 for one participant whose stored facts number only 35, all 2026; an event question about 2023 returns only 2026 although the anchor has 1 275 messages in that year. Negative control: the tokenizer, history markers and FTS builder are byte-identical between 32e018b9 and 7bc8545a; the only new functions are the episode anchor resolver, the row-id mapper and the dig coverage helper; the single retrieve() remains the only path.
Next unlocks: VMQ-TIME review and release with real-archive proof; M1 rows bound; avatar decision; then UNIFIED-REPLY, PVR-FC, BEHAVIOR-GATES, EPIC-EXPERIENCE and MOD-ACL M4
Next execution: awaiting_children
Review: approved (retrieval 7bc8545a with independent numbers; P0-A, P0-B, P1, nostalgia, quantum approved earlier)
Deployment: verified (2.58.180 @ 721bab10, schema 47)
Human gate: none
Progress scope: plans/progress_scope.json | fresh — 71/71 owner inputs reconciled; aggregate 3993/6283 requirements (63%), 13/49 tasks
Open detail: the preserved WIP commit f41c2c31 covers 22 files (9 service modules, settings, catalogue, four new suites, the reissue tool). Another 71 files under tests/fixtures and test pins are dirty in that worktree because the catalogue grew and the pins still need regeneration; they are derived artefacts and the finish lane regenerates them rather than keeping the dirty copies.

M1 audit result: 16 admin predicates inventoried with blob hashes, parity verified across 17 routers by AST analysis, secrets controlled by masking plus a log filter plus request-status redaction, 503 and 403 distinguishable in the UI, and a real 401 recorded on production. Two findings were registered: `requires_permission('access')` (~33 endpoints) does not evaluate role_type, so a global_admin role without wildcard gets 403 there (the owner is unaffected because the seeded role has wildcard); and `GET /api/avatar/{kind}/{tid}` has no scope predicate, which is being verified before any fix because the correct rule may be shared-chat visibility rather than an admin check.

M1 ledger after the audit: 2 rows bound to VERIFIED (predicate inventory and router parity), 5 rows kept PENDING with partial evidence and an exact remaining condition (live 503 screen, DOM/Telegram secret channels, SELF-DIAG prompt dependency, HTTP-only part of the bot-side check), and the rest pending on live sessions or a custom-role migration. MAC-DEF-01 is registered as a mandatory defect: `requires_permission` ignores role_type, so a global_admin role without wildcard gets 403 on ~33 endpoints; the fix is in flight on its own branch.

Updated: 2026-11-10T20:30:00+12:00

## Stalled builder recovered (2026-11-11)

The VMQ-TIME builder produced substantial work and then stalled: 22 files with the three separated properties, L1 memory_scope, per-year profile, as-of marking, durable year-coverage events and four new test suites, uncommitted, with no file change for about five hours. I preserved it as commit f41c2c31 on branch vmq/time-bias (base e63eb64c = production 2.58.180) and measured it: 52 passed, 1 failed — a structural assertion expecting an exact expression that the code does not contain. A fresh builder now resolves that one point (aligning code or strengthening the assertion, never deleting it) and finishes the suites.

## Retrieval release verified in production (2.58.180)

Deployed 721bab10 from 32e018b9 with a single cherry-pick (1f792d85) of the approved 7bc8545a; no conflicts, 6 product files, no DDL, schema 47. Live read-only checks: `<Old_Episode>` is non-empty on a real chat (3 144 chars, 2 episodes, 31 messages) with a `msg:<row>` anchor accepted alongside the intact tg path; `dig_into_lore(year=2023)` completes in 0.385 s with `coverage.sampling=window_scan_by_time`, `truncated=true` and 31 213 messages in the window; `msg:528` reaches the payload with its real date and resolved author. The empty-block counter stayed at 0 because the tg path handled live traffic, so that defect rests on the controlled measurement rather than live observation — stated honestly. Open non-blocking items: no internal timeout in `dig_into_lore`; the chosen plan depends on statistics (no ANALYZE in code); the plan-shape test only covers a tiny database.

## Release-line finding (must not be ignored)

The integration branch is NOT on the production line: merge-base with production is adfd0d0c and 34 commits exist only in production (releases 2.58.173 through 2.58.179). Deploying integ/unify-release as-is would roll production back. Every release must therefore be rebuilt by cherry-picking the reviewed commits onto release/2.58.179, and that is the only path for the retrieval fix.

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
