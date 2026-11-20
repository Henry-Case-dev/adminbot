# HC-TIME (B) — review r1 fixes

- Finding: **HC-B-F1** (P1 IN_SCOPE), Reviewer evidence `review-b-r1.md`
  (sha `6287eb5a…`), candidate `24f0f76672c4f5187700c19cdbf9492481e016f3`;
  fixed candidate **`1fe684d369d753449cf1bdc974de6fdefdd1c8ca`**.
- Branch: `p0/hc-b`, same worktree
  `...\WorkspaceData\worktrees\c742e4de9e92c489\p0-history-coverage-temporal-e-cbf9b3fab6a8-912d3c5b`.
- Scope addendum: `services/thread_chain.py` and the test-only addendum in
  `tests/test_history_segments.py` (Reviewer-directed; PM amends the graph).
- No C2/DDL/flags/bump/deploy.

## HC-B-F1 — repaired

**Before:** `_render_thread`/`_render_branch` → `thread_chain.format_chain_line` /
`render_speech_line` rendered chain rows without reply/edit. `ChainItem` had
`reply_to_item_id` but no `edited_at`/`reply_to_author_id`; the already-selected
`get_smart_message_by_tg_id` fields were not propagated.

**Fix:**

- `ChainItem` additively gains `edited_at` and `reply_to_author_id` at the end
  (old positional constructions remain valid).
- `collect_thread_chain` fills both from the row it already reads via
  `get_smart_message_by_tg_id` (that SELECT already includes
  `edited_at`/`reply_to_author_id`; **no new SQL/DDL**).
- `format_chain_line` (raw Thread/Branch/factcheck) passes
  `reply_to="tg:<parent> [(uid N)]"` and `edited_at` to `format_context_item`.
  Absent fields keep the previous bytes.
- `render_speech_line` keeps the visual contract: raw `tg:`/uid are never
  printed in speech projection; reply remains the existing `↳ Reply M…`
  relation and edit is an additive `(ред. … UTC)` clause after the text.
- `_context_row_line` speech branch was corrected the same way: mapped reply
  label only, edit as a text clause — no raw `tg:`/uid leak. (Found by the
  independent `test_evol_rc_accept_fixes` reply-edge check during this fix.)

**RED on candidate `24f0f766`:** `3 failed, 1 passed` —
`red-base/hc-b-f1-red-at-24f0f766.txt`.

**GREEN:** `tests/test_p0_hc_temporal.py::TestThreadBranchTemporalDelivery`
`5 passed`; full new file `35 passed`; Thread/Branch final Writer payload
contains both `ответ на tg:11 (uid 7)` and `ред. 01.01.2024 00:05 UTC`
(`payloads/writer-payload.json`, sha `025a063c…`).

## Test-only addendum (HC-B-F1 item 4)

`tests/test_history_segments.py::TestBoundaryContinuity::test_intra_page_cut_reply_keeps_connection`
now uses the actual post-B cut 120|121 and moves the second cross-cut reply to
121→120 (first row of segment 3 answers the last row of segment 2). It still
asserts `complete=1` and `continues_from=1/2` through a real cross-cut reply;
nothing deleted, deselected or weakened. `1 passed`.

## Mutations (killed)

| ID | Mutation | Targeted test | Result |
|---|---|---|---|
| f1-m1 | `format_chain_line` drops `reply_to` | `test_thread_and_branch_lines_carry_reply_edit` | 1 failed |
| f1-m2 | `format_chain_line` drops `edited_at` | same | 1 failed |
| f1-m3 | `_render_thread` emits empty body (payload Thread content missing) | `test_thread_branch_reach_final_writer_payload` | 1 failed |

Artifacts: `mutations/f1-m1-drop-thread-reply.txt`,
`mutations/f1-m2-drop-thread-edited-at.txt`,
`mutations/f1-m3-payload-thread-missing.txt`.

## Verification totals

- New temporal: **35 passed**.
- History isolation: **21 passed**.
- Focused: **745 passed, 1 deselected** (666 core + 79 summary-memory; only the
  pre-existing ur_c_clock capacity test deselected).
- Thread/reply consumers (HC-B-F1): **367 passed, 1 deselected**.
- Mandatory 24-file set: **386 passed**.
- TIME-03/NEXT-02/turn-clock 6-file set: **157 passed** (the earlier 5-file set
  was 108; Reviewer's 110 used a different file set).

## Remaining non-blocking

- `tests/test_evol015_quote_pipeline.py::test_d_plain_reply_byte_parity` still
  compares raw Thread output with the pre-B oracle and now fails by design
  because HC-B-F1 requires the reply edge. It is outside the authorized test
  addendum scope; artifact `known-test-shape-evol015-byte-parity.txt`.
  The semantic substitute is the new Thread/Branch payload test.
- `test_ur_c_clock::TestFallbackAdapterClock::test_generous_budget_keeps_block_intact_same_asof`
  fails identically on A tip — pre-existing, not caused by B.
- NB4 (`sent_at` selected but the message line uses `timestamp`) remains a
  documented matrix limitation; live rows have equal values.
- Episode facade event columns and `valid_from/valid_to` SELECT remain outside
  the frozen B database scope, as documented in `implementation.md`/matrix.
