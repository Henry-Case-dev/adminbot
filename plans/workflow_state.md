# Workflow State

Task: self-diag-01 corrective (P0, owner 2026-11-13) + vmq-onto-01 approved slices awaiting release
Task source: plans/owner_inputs/2026-11-13-selfdiag-corrective-journal-code-identity.md + 2026-11-13-vmq-next02-natural-retrieval-metric.md + 2026-11-12-queue-order-selfdiag-quantum.md
Status: in_progress
Primary phase: build
Active feature: self-diag-01 (corrective) + vmq-onto-01
Active lanes: Builder ses_e2cdd5c5effe0BLaveCRaYIJB1 (self-diag core: checkup research loop, continuation, repo resolution, L1 degradation); Reviewer ses_e2cb0b029ffeUnwBVc8ohmUYyF (identity ea9e9f2a)
Join barriers: core candidate -> Reviewer E2E + anti-hardcode -> combined release train (self-diag core+identity + vmq M1 cfec9a1a + NEXT-02/05 96c8bc72) -> DevOps 2.58.199 + smoke -> PM postdeploy binding.
Last verified: production 2.58.198 at 23477658 (schema 47, no DDL, rollback 25876167). Journal access restored+verified as service user (group systemd-journal; rc=0, current invocation; evidence 1f2156ea). vmq map: 1 VERIFIED / 6 REVIEW / 0 FAILED / 63 PENDING; 54 owner-mandated gaps remain. Approved candidates: vmq M1 cfec9a1a (deploy gate errors=0) and NEXT-02/05 96c8bc72 (quality review Approved, §B excluded, no cap/threshold weakening). Self-diag identity/counters ea9e9f2a under review; production manifest proof deferred to the next release.
Next unlocks: core candidate -> independent review -> combined release train -> DevOps deploy + smoke -> postdeploy binding -> continue vmq gaps (ONTO-A/B first).
Next execution: awaiting_children
Review: pending
Deployment: verified 2.58.198 @ 23477658 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | initiative DONE 114/114; self-diag corrective P0; vmq 1/6/0/63 (54 owner-mandated gaps); source 36/36, queue 40/40
Updated: 2026-11-13T17:10:00+12:00

## Facts

- Owner corrective (binding): no lexical routing/hardcoded intents; LLM decides, code executes structured decisions. Checkup must research own code via existing SourceReader/read_source_code/inspect_runtime inside the standard checkup; continuation must not require a repo URL; L1 empty-content fallback preserves intent; deploy identity proves the running version; counters return honest unknown instead of zero. One release + smoke; Reviewer E2E A-G + anti-hardcode audit.
- Journal: environment fixed (usermod -aG systemd-journal adminbot + restart); verified from the service user; persists across restarts/deploys; no root bot, no sudo, no sandbox weakening.
- Identity/counters: proven cause = no manifest producer existed; new tools/release_manifest.py writes schema-1 manifest before restart, refuses dirty tree, supports rollback/dry-run; identity distinguishes manifest/process/checkout; counters honest null/not_checked. Production manifest appears only on the next release.
- vmq: M1 (episodes: boundaries, provenance, rebuild idempotency; M-03 fixed) and NEXT-02/05 (§A period-only FTS tokenization repair + additive timings; §B excluded) independently approved. Quality: 0 mandatory-fact losses, 115/120 identical rows, year share diagnostic only. NEXT-03 lacks candidate-bound approval on the new candidate; NEXT-04 PENDING; NEXT-01 postrelease.
- Epic vmq remains open: 54 owner-mandated REAL_GAP rows (ONTO, M2, Q0, Q0-IBM, Q1, O, U, R, memory/time evidence) — release of the two slices does not close it.
- Backlog: embedding fallback swaps provider silently (B1, Architect decision), 9550 NULL-timestamp facts (B2), no participant→years link (B3), 5 pre-existing asap32 RED, empty blocks under rerank (B5), web/api identity branch/source fields empty (byte-freeze), plus the standing backlog items.
