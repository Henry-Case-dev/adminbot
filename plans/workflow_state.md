# Workflow State

Task: self-diag-01 corrective (P0, owner 2026-11-13) + vmq-onto-01 in parallel
Task source: plans/owner_inputs/2026-11-13-selfdiag-corrective-journal-code-identity.md + 2026-11-13-vmq-next02-natural-retrieval-metric.md + 2026-11-12-queue-order-selfdiag-quantum.md
Status: in_progress
Primary phase: build
Active feature: self-diag-01 (corrective) + vmq-onto-01
Active lanes: Builder ses_e2cdd5c5effe0BLaveCRaYIJB1 (self-diag core: checkup research loop, continuation, repo resolution, L1 degradation); Builder ses_e2cdd1dffffedGF8QTJpYSLVKZ (deploy identity/manifest + honest counters); Builder ses_e2d36bf94ffe557G6z1G6zaqXI (vmq NEXT-02 final §A+NEXT-05); Builder ses_e2d15dd9fffeC9TZGu3ulBs4ir (M1 story-assembly fix)
Join barriers: self-diag core+identity -> Reviewer E2E + anti-hardcode audit -> one release + smoke; vmq NEXT-02 -> quality review -> release slice; M1 -> re-review M-03.
Last verified: production 2.58.198 at 23477658 (schema 47, no DDL, rollback 25876167). Journal access RESTORED and verified as the service user: cause = adminbot missing from systemd-journal group (files 0640 root:systemd-journal), fix `usermod -aG systemd-journal adminbot` + restart; `runuser -u adminbot -- journalctl -u admin_bot -n 300` rc=0 with current invocation entries; /healthz 200; evidence commit 1f2156ea. Self-diag prior 150 VERIFIED rows kept but the end-user scenario was not proven; corrective reopens limited scope. vmq: 1/70, 54 owner-mandated REAL_GAP rows source-anchored; M1 candidate 80726249 review M-03 FAILED (story-assembly error swallowed); NEXT-02 final building.
Next unlocks: corrective candidates -> Reviewer E2E (A-G) + anti-hardcode -> one release + smoke -> corrective DONE -> vmq slices continue.
Next execution: awaiting_children
Review: pending
Deployment: verified 2.58.198 @ 23477658 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | initiative DONE 114/114; self-diag corrective P0 (prior 150/39 kept); vmq 1/70; source 36/36, queue 40/40
Updated: 2026-11-13T16:25:00+12:00

## Facts

- Owner corrective (binding): no lexical routing/hardcoded intents anywhere (code/config/prompt/fallback). LLM decides intent; code validates/executes structured decisions. Checkup must research the bot's own code via existing SourceReader/read_source_code/inspect_runtime inside the standard checkup; continuation must not require a repo URL (repo_origin from flags.self_diag_repo_origin); L1 empty-content fallback must preserve established intent/context; deploy identity must prove the running version; counters must be honest unknown instead of zero. One release + smoke; Reviewer independently verifies E2E A-G and the anti-hardcode invariant.
- Journal: fixed at environment level (group membership), no code change, persists across restarts/deploys; no root bot, no sudo, no sandbox weakening, no Better Stack.
- Architect contract: `plans/features/self-diag-01/corrective-2026-11-13/architecture-corrective.md` (SELFDIG_CORRECTIVE_READY). Builders split: core (checkup loop/continuation/repo/L1) + identity/counters; disjoint files.
- M1 review: M-01/M-02 VERIFIED on fixtures, M-03 FAILED (process_rechecks swallows assemble_stories; complete=True unreliable). Builder fixing with regression; re-review M-03 only.
- NEXT-02 final: §A period-only FTS tokenization repair + NEXT-05 additive timings; §B excluded; paired quality measurement per owner decision (year share diagnostic only).
- Natural/future observations remain nonblocking; no owner QA.
- Backlog: .gitignore:7, git log timeout, mca10b 643/644, cfg03 dead knob, two pre-existing RED, 5 direct_fallback_recompose RED, write-points scan parity, send_chunked_reply >4096, speech _chat_overrides fail-open, rejected_subject mixes lexical+KNN.
