# Workflow State

Task: smart-module-semantic-routing-p0 (P0 corrective, P1 in review) plus the ordered queue on the merged ledger
Task source: plans/owner_inputs/2026-11-10-smart-module-semantic-routing-p0.md (sha256 2ECA66DA…8A8C) and 2026-11-10-video-commands-final-contract.md
Status: in_progress
Primary phase: P1 review, P0 live acceptance
Active feature: smart-module-semantic-routing-p0
Active lanes: ses_e3ea3f080ffemOr9EiNsTxMmrA (Reviewer: P1 9f862b0f); ses_e3ea82afaffeVQ1T50ntsquo6F (Architect: static 4 rows at deployed SHA)
Join barriers: P1 verdict -> deploy -> live check; static rows -> bind or keep open; owner live run of six scenarios
Last verified: P1 COMMITTED at 9f862b0f (parent 6fec18d2, 16 files). Demotions: lexical search fallbacks removed and replaced by one structural predicate over the command registry; `_NOSTALGIA_MARKERS_RE`/`_nostalgia_markers()`/`_dig_pre_gate_block()` removed — the builder proved the nostalgia pre-gate was ENABLED in production despite a default of false, so this changes live behaviour deliberately; vision now requires a structural media link instead of words; a profanity-laden correction is kept (medium confidence plus visible suspect) instead of being discarded by joke/aggression markers; a quoted style request no longer becomes a rule. Explicit commands, date/number/link parsing, Reply targets, the media registry, provider checks and protective regexes preserved. 2332 tests pass across affected areas with only pre-existing failures; a 138-file blast-radius run shows the same failure set as with the changes stashed. Known remnant: the `param_catalog.py` description of DIG_PRE_GATE_ENABLED still describes a working pre-gate although the flag is inert (file byte-frozen, needs repinning). Production 2.58.176 @ 2b7e9c7f is verified and byte-identical to the reviewed candidate 6fec18d2
Next unlocks: P1 verdict -> release -> live check of the three demotions; owner runs the six P0 scenarios; static 4 rows at the deployed SHA
Next execution: awaiting_children
Review: approved (468ee956 P0-A, 67063aa5 P0-B, 53c78594, 78a4e017, ebc5a23b); P1 in review
Deployment: verified (2.58.176 @ 2b7e9c7f, schema 46, no DDL)
Human gate: none
Progress scope: plans/progress_scope.json | fresh — aggregate certified at 3954/6238 requirements, 293/514 stages, 13/49 tasks
Updated: 2026-11-10T10:00:00+12:00

## Ledger integrity finding (important)

The MAIN CHECKOUT does not contain the deployed product: its `APP_VERSION` is 2.58.111 while production is 2.58.176, missing 1248 commits. Only `handlers/direct_chat.py` matches byte-for-byte. Any code inspection done from the working directory is therefore invalid for this release: use `git show 2b7e9c7f:<path>` or a worktree at that commit. This caused two rejected internal audits (first: wrong row mapping, 15 of 17 citations wrong; second: mixed revisions, 18 of 56 citations reproduce). Zero of 15 internal rows are bound; all carry precise blocked reasons.

## Open items by owner

1. Owner live run of the six P0 scenarios on 2.58.176: the manga question, «что происходит в чате», «Бот, че за видос», «Бот, транскрипт», a plain video mention, and «нарисуй кота» (which will refuse because no image provider key is configured — a pre-release state, now in the backlog).
2. Four cheap static inspections at the deployed SHA for SMR-INV-16/21/24/13.
3. P1 verification after deploy: nostalgia no longer fires on «помнишь», vision needs real media, quoted style requests do nothing.

## Queue after P0/P1

REMOVE-LEGACY-REPHRASING -> UNIFIED-REPLY -> PVR-FC-CORRECTIVE-01 -> BEHAVIOR-GATES-SIMPLIFICATION -> EPIC-EXPERIENCE (P) then H last; in parallel MOD-ACL M4A/M4B/M4C, SELF-DIAG D2 live obligations and D3-D7, VMQ ONTO with the new VMQ-MEM parity rows. Cross-epic rule: the newer owner instruction wins (P0 > earlier BGS/UR routing parts; lessons contract > EPIC-EXPERIENCE E; MOD-ACL tri-state > BGS settings semantics; memory-cognitive-02 > CM-VISUAL).

## Invariants

- The current user message is the task; reply, quote, forward, history, transcript and tool results are evidence, never a substitute task.
- Only explicitly registered commands may intercept before L1; no new synonyms, keyword lists or regexes for semantic decisions.
- Explicit commands keep their surface and arguments; secrets are never surfaced anywhere; no new LLM classifier or second pipeline.
- Deploy by immutable SHA from a clean release branch; production is 2.58.176.
