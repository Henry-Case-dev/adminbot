# VMQ Slice D — independent re-review r2 (2026-11-15)

Reviewer: DeepSeek V4.1 Flash (`opencode-go/deepseek-v4.1-flash`), session `ses_e2221abb6ffeSaFVCOq0pGps8K`.
Candidate: `vmq/slice-d` HEAD `c4b2c1c2` (code `743a3d1a`), previous `dbaf1a6d`, base `2b419aa2`, clean.
Scope: only `git diff dbaf1a6d..c4b2c1c2` (D1–D8 fixes) and changed seams. Verdict preserved unchanged.

## Verdict: Needs Fixes — D1 still open (BLOCKER). Not Approved, not VERIFIED, do not deploy.

| ID | Verdict | Evidence |
|---|---|---|
| D1 | **NOT CLOSED (BLOCKER)** | Guard suppresses only the period path when a present-marker is present and `policy=auto`. Bypasses reproduced on the DB copy: (1) unmarked — `«как дела с мулянкой?»` -> `2022:1, 2024:1, 2026:8`; `«что нового у Алины?»` -> `2023:1, 2024:1, 2025:4, 2026:4`; `«как обстановка с мулянкой?»` -> `2022:1, 2023:1, 2026:8`; (2) historical marker with present meaning — `«расскажи, что сейчас с мулянкой?»` -> `2023:1, 2026:8` (`intent=historical`); `«что сейчас с Алиной, расскажи»` -> `2023:1, 2024:1, 2026:8`; (3) profile path with real `subject_name`/`subject_uid` — `_build_rag_block(..., memory_scope="auto", subject_name="Alina", subject_uid=485008070)` for `«что сейчас с Алиной?»` -> `2023:1, 2024:1, 2026:7`, `period.kept=0`, `current_state_guard=0`; old rows added by `_rag_append_profile_rows`, current rows displaced. This is the real caller (`direct_chat_service.py:10095-10099`). Tests `test_full_path_current_state_keeps_current_ids` and `probe_current_state.py` call `_rag_unified_rows` without `subject_name`, so they miss the real path. |
| D2 | Closed for the stated negative; residual | `«шизы обсуждали» 2023 + «на конфе шумели» 2024` correctly rejected (`topic_common_stems=0`); A1P still `2023:1, 2024:1, 2026:8`. Residual: generic stems (`были`, `есть`) count as common (`«шизы были»` + `«на конфе были»` accepted); hard precision 0.5 reflects this. |
| D3 | Closed for P2/P3; new underfill | P2 -> `2026:8, 2024:1, 2025:1`; P3 -> `2026:8, 2023:1, 2024:1`; other facts kept. Underfill: 1 subject fact + 6 own messages -> only 3 facts returned; `reserve=max_items//5` is applied even with 9 free slots (`tool_router.py:4727-4737`). |
| D4 | Closed | Three participants (P1, top author, P3 with 2023–2024 history) in corpus evidence. |
| D5 | Mostly closed; residual trace | `logger.info`, durable `emit_stage_event`, `memory_period` selection payload and per-block years exist; allowlist carries only codes/numbers, no query. Residual: `current_state_guard=0` when the guard is active but no strict row was dropped; the reader cannot distinguish "guard active" from "not applied"; profile old rows are not attributed in `memory_period`. |
| D6 | Partial | Hard distractors now compete (hard 2/4); core 1.0 remains structural (core distractors share no stems and never enter `soft_pool`); T3 only marked/no-subject; labeled set still synthetic, not an independent TIME-07 reference. |
| D7 | Closed | RED on base: 19 failed / 5 passed; passed list matches evidence; non-existent test removed. |
| D8 | Closed for the six stated negatives; does not cover the real D1 path | No negative calls `_build_rag_block`/`_rag_unified_rows` with `subject_name`, checks an unmarked present question, or `«расскажи, что сейчас…»`. |

## New defects

- **N1 — BLOCKER (MEM-04/TIME-01/TIME-06/TIME-07):** the current-state guard is bypassed by the profile path, by unmarked present questions and by a historical marker attached to a present question. The guard is keyword-based and covers only one of several old-material injection paths.
- **N2 — MEDIUM (TIME-02):** tool biography underfills when subject facts are few: reserve is applied even with free envelope slots (3 facts instead of 7).
- **N3 — MEDIUM (MEM-04/TIME-01):** generic stems (`были`, `есть`) pass `topic_common_stems`.
- **N4 — LOW/MEDIUM (TIME-04):** trace does not distinguish an active guard from an unapplied one.
- **N5 — MEDIUM (test/evidence):** D1 tests do not reproduce the real caller (`subject_name`/`subject_uid`).
- **N6 — LOW:** `test_memory_period_vector_leg.py` was not weakened for the two-stem positive, but its neighbouring current-state test runs with default `policy="historical"` and does not prove absence of a "now dictionary" under `auto`.

## Independent numbers

Candidate tests 24 passed; focused 274 passed; Direct Chat/ToolRouter/trace 496 passed; RED on base 19/5; mutations: guard->False 5 failed, D2 filter off 1 failed, `memory_period` removed 1 failed. Real copy: A1P `2023:1, 2024:1, 2026:8`; P2 tool `2026:8, 2024:1, 2025:1`; P3 `2026:8, 2023:1, 2024:1`; T3 marked without subject `2026:10`; T3 with subject `2023:1, 2024:1, 2026:7`; unmarked present `2022:1, 2024:1, 2026:8`.

## Limitations

No live process (L1, Writer, rerank, generation); vector leg `compat_not_proven`; one chat, one copy (2,043,181 messages), one run per query; 3 mutations checked; full suite not run; N2/N3 reproduced synthetically; no UI.

## Conclusion

Only TIME-06 (inventory/invariants, with the semantic-leg limitation) and the D4 part of TIME-02 can be treated as confirmed; TIME-04 mostly; MEM-04/TIME-01 are not confirmed; TIME-02 partially; TIME-07 is not an independent reference. No row may be marked VERIFIED. The repeated D1 failure means the next step is a root-cause contract decision, not another keyword patch.
