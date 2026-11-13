# Workflow State

Task: self-diag-01 corrective (P0, owner 2026-11-13) + vmq-onto-01 approved slices — combined release train
Task source: plans/owner_inputs/2026-11-13-selfdiag-corrective-journal-code-identity.md + 2026-11-13-vmq-next02-natural-retrieval-metric.md + 2026-11-12-queue-order-selfdiag-quantum.md
Status: in_progress
Primary phase: build
Active feature: self-diag-01 (corrective) + vmq-onto-01
Active lanes: Builder ses_e2c420cf6ffeyVLy45EGjmMip1 (combined train release/2.58.199-train from 4 approved slices)
Join barriers: train candidate -> combined-diff Reviewer -> DevOps bump 2.58.199 + deploy + smoke -> postdeploy binding -> corrective closeout.
Last verified: production 2.58.198 at 23477658 (schema 47, no DDL, rollback 25876167). Journal access restored+verified as service user (systemd-journal; rc=0, current invocation; 1f2156ea). Approved slices: self-diag core 76fcb829 (checkup research loop, structured diagnostic_research, continuation to Writer, L1 degradation, adaptive_tool_chain fix; Reviewer Approved; 28/330/442 + p4), self-diag identity ea9e9f2a (manifest producer, identity semantics, honest counters; Approved; 58/555), vmq M1 cfec9a1a (episodes; M-03 fixed; deploy gate errors=0), vmq NEXT-02/05 96c8bc72 (§A FTS fix + timings; §B excluded; quality review Approved). Self-diag map: 147 VERIFIED / 41 READY / 16 REVIEW / 2 PENDING (206 unique); vmq: 1 VERIFIED / 6 REVIEW / 0 FAILED / 63 PENDING (54 gaps).
Next unlocks: train -> combined review -> deploy 2.58.199 -> smoke (journal, Telegram E2E, manifest) -> closeout rows -> vmq ONTO-A/B.
Next execution: awaiting_children
Review: approved for slices; combined-diff review pending
Deployment: verified 2.58.198 @ 23477658 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | initiative DONE 114/114; self-diag corrective bound; vmq 1/6/0/63; source 36/36, queue 40/40
Updated: 2026-11-13T19:12:00+12:00

## Facts

- Owner corrective binding: no lexical routing anywhere; LLM decides, code executes structured decisions. Checkup researches own code via existing SourceReader/read_source_code/inspect_runtime; continuation needs no repo URL; L1 empty-content preserves established intent only for reply-to-bot with zero auto-run; identity proves the running version; counters honest unknown instead of zero. One release + smoke; Reviewer E2E A–G + anti-hardcode audit. Epic not DONE.
- Core real defect found/fixed: `execution_mode="adaptive"` instead of canonical `adaptive_tool_chain` demoted the diagnostic decision to `simple_tools`, so L2 never received the code. C now runs to L2 Writer and the sent answer without asking for a repo link.
- Live-model evidence: local provider nano-gpt / deepseek-v4.1-flash (not production-equivalent), 2 series × 9 unseen formulations, 4 positives / 5 negatives, one honest `neg_external` target flip (needed=false both series), per-case sha256 present, strict UTF-8.
- Identity: proven cause = no `.deploy/release.json` producer existed; new `tools/release_manifest.py` writes schema-1 atomically before restart, refuses dirty trees, supports rollback/dry-run; identity distinguishes manifest/process/checkout; counters `null/not_checked` when unobserved. Production manifest appears only on the next release.
- vmq: M1 and NEXT-02/05 approved; quality 0 mandatory-fact losses, 115/120 identical rows, year share diagnostic only, no cap/threshold weakening. Epic remains open with 54 owner-mandated gaps (ONTO/M2/Q0/Q0-IBM/Q1/O/U/R + evidence rows).
- Release rule: scoped deploy is red only on deferred dependency closure → one epic-level train, then smoke. No fake VERIFIED.
- Backlog: web/api identity branch/source fields empty (byte-freeze), embedding fallback swaps provider (Architect decision), NULL-timestamp facts, participant→years link, pre-existing RED sets.
