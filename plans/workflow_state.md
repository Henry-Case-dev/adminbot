# Workflow State

Task: p0-init-meme-ux-diag (P0 corrective, queue position 2) plus the ordered queue
Task source: root prompt + plans/owner_inputs/2026-11-11-p0-init-meme-ux-diag-corrective-excerpt.md
Status: in_progress
Primary phase: review
Active feature: p0-init-meme-ux-diag
Active lanes: ses_e35acae71ffeL25nAbHGPwHb1B (Reviewer: 2d0dc10a six corrected axes blockers); ses_e35cb2fcbffdSK0NnPDg0Ksm9O (Reviewer: inspector d3e74eef consolidating verdict)
Join barriers: both verdicts. S3 overview UI must not start before the axes verdict; inspector release 2.58.189 waits on its verdict.
Last verified: R0-INV closed read-only on production 2.58.188 (evidence/r0/diagnosis-2.58.188.md, 9 rows VERIFIED); axes candidate 2d0dc10a implements the six review blockers; production healthy at c087253d.
Next unlocks: bind 2d0dc10a verdict -> S3 overview UI; inspector verdict -> 2.58.189; S5b paid-image loss after S5
Next execution: awaiting_children
Review: pending
Deployment: verified 2.58.188 @ c087253d (schema 47, no DDL); rollback 952b9ebd
Human gate: none
Progress scope: plans/progress_scope.json | fresh - source coverage 35/35, queue 39/39, owner inputs reconciled
Updated: 2026-11-11T23:18:00+12:00

## Current factual state

Production is 2.58.188 at c087253d (release/2.58.188), schema 47, no DDL. The Initiative/Meme module exists ONLY on the production line - the working branch (master 89be9d4f) does not contain services/meme_initiative.py, web/api/initiative_publications.py, handlers/meme_command.py or services/publication_coordination.py. Every implementation branches from c087253d; deploy only by cherry-picking onto release/2.58.x.

R0 investigation (read-only, no product change) established the real `/meme` failure: the 2026-11-11 09:20:56 UTC manual run in chat -1002661910336 reached the image stage (summary OK 09:20:59.753, joke OK 09:21:01.462) and was killed by the 2.58.188 restart at 09:21:08; `CancelledError` is a BaseException, so no terminal journal row and no user reply were written. The three suspected candidates (manual marker TTL, late jid, sqlite lock) are real defects but NOT the cause of that failure. Confirmed defects: ready=false rendered as "disabled" on both cards; expired manual_priority_until shown as a current block; empty job_id for early refusals; attempt journal losing rows on sqlite lock (77/24h, 228/7d); marker never cleared and its failed write only a WARNING; automatic memes discarding a paid image at publisher_not_bound 6 times in 7 days. Ordinary per-chat differences (last publication, cooldown remainder, quota use, 7-of-8 vs 0-of-8 messages, mirrored 1800 s cross-type conflicts) are NOT defects. The API echoes the selected chat; no cross-chat leak.

Map: 72 unique requirements across slices R0-INV, A0-ARCH, S1-AXES, S2-ID, S3-OV, S4-TRACE, S5-MEME, S5b, S6-FRESH, S7-ACCEPT. No duplicated rows - sixteen existing maps were checked and overlapping obligations stay required with covered_by + delta. HMF-UI-02/06/07 and the "last attempt" panel of HMF-UI-05 are superseded by the stricter P0 rows; the image-prompt budget and the admin /meme mark remain in force.

## Open items outside this epic

Inspector UR-20.4/20.5/20.8 VERIFIED; UR-20.6 and UR-20.7 await the consolidating verdict at d3e74eef, which also decides parent UR-20 and readiness for 2.58.189. VMQ-NEXT-01..05 stay PENDING for lack of a real direct turn (admission proven, per-turn behaviour unobserved). Scheduled live-share sample waits for real traffic (>=34 blocks, >=10 operative answers); no automatic wake-up, no owner action.

## Owner corrections that stay binding

Two earlier claims of mine are superseded and recorded as such: CHAT_RAG_RERANK_ENABLED has been effectively True in production since 2026-09-06 (stored key carries the `flags.` prefix), and the index "compat_not_proven" reading was a side-process artefact (quota_group apinet_paid vs primary); admission was valid all along with the vector digest unchanged.

Owner rules in force: agents verify, never the owner; no new human gates, agents or queues; no OFF/SHADOW modes and no per-example patching; ready is not enabled; do not invent an ETA; no new diagnostic systems or LLM checks for observability; user prompts, models and saved settings are untouched; every further fix must name the original requirement it violates.
