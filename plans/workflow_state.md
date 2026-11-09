# Workflow State

Task: smart-module-semantic-routing-p0 (P0 corrective, P1 in review) plus the ordered queue on the merged ledger
Task source: plans/owner_inputs/2026-11-10-smart-module-semantic-routing-p0.md (sha256 2ECA66DA…8A8C) and 2026-11-10-video-commands-final-contract.md
Status: waiting_external
Primary phase: P0 live acceptance by the owner; P1 held for lack of a valid independent review
Active lanes: none
Join barriers: the owner's six live scenarios on 2.58.176; a trustworthy independent review for P1 (three attempts produced no usable verdict)
Last verified: P0 corrective is LIVE and verified on production 2.58.176 @ 2b7e9c7f: product blobs byte-identical to the approved candidate 6fec18d2, no DDL, schema 46, zero tracebacks, and live probes show the manga sentence produces no image attempt or quota text, «что происходит в чате» is not consumed by the video handler, and the registry holds exactly «транскрипт» and «че за видос». P1 (9f862b0f) is COMMITTED BUT NOT DEPLOYED: I verified its three contested areas by direct measurement at that commit — no `_NOSTALGIA_MARKERS_RE`, no `_dig_pre_gate_block`, no `check_trigger(` anywhere in services/handlers; `is_media_dependent()` correctly covers own media (including a caption), reply-with-request, explicit tg ref, pending intent and a non-empty quote, and returns False for words alone; `is_search_command()` is built on command_prefix plus the canonical registry, and the remaining `_SEARCH_REQUEST_WORDS` list only cleans an already-decided query rather than deciding intent. Independent review of P1 could not be obtained: attempt 1 cited non-existent paths (`adminbot/core/...`), attempt 2 fabricated a nostalgia defect in lines that contain no such code, attempt 3 echoed the commands without running them. Three earlier evidence artifacts were also rejected (wrong row mapping, mixed revisions, hash mismatch), so the map now carries measured anchors for 2b7e9c7f and 15 internal rows stay PENDING
Next unlocks: owner's six live checks -> live rows and SMR-DONE-09; a reliable review of P1 -> its release; then REMOVE-LEGACY-REPHRASING -> UNIFIED-REPLY -> PVR-FC -> BEHAVIOR-GATES -> EPIC-EXPERIENCE (H last), with MOD-ACL M4, SELF-DIAG D2 live and VMQ-MEM parity in parallel
Next execution: none
Last verified: THE P1 REVIEW WAS VOID. Its verdict cited `adminbot/core/planner/executor.py` and `adminbot/features/vision/vision_feature.py`, which do not exist in this repository (the project uses services/, handlers/, web/, tests/, config/), so its findings are unreliable — including its "blocker". I verified the disputed point myself on the real file: `services/media_readiness.py::is_media_dependent()` at 9f862b0f returns True for `explicit_ref`, `pending_intent`, a non-empty `quote_text`, `own_media`, and for `reply_media` plus either empty text or a positive `mca_vision.vision_intent(text)`; an image with its own caption is therefore covered by `own_media`, and the alleged "caption-only returns False" blocker does not hold. A bounded re-review with an explicit "cite only real paths and blobs" rule is running. Earlier the same day I also reverted four falsely VERIFIED rows: the third inspection artifact had a recorded hash that did not match the file and mixed correct with wrong line numbers; I measured the real anchors myself and stored them in the map (`anchors_2b7e9c7f`): _render_current_question 9954, _build_user_content 8413, _l1_reply_block 5963, build_l1_context 1606, _cap_context 1706, composer_on 137, media_marker 106, run_simple_tools 887, run_adaptive_chain 1110
Next unlocks: P1 verdict -> release -> live verification of the three demotions; owner runs the six P0 scenarios on 2.58.176
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
