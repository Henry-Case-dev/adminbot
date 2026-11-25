# P0 memory-relevance — lane B, review r1 corrections

Review artifact: `plans/features/vmq-onto-01/evidence/p0-memory-relevance-review-r1.md`
(sha256 `06118384a717732ee396b6299d3018072d5d1f568ea17fc7194e3012bc58d738`),
session `ses_dee15c5beffeH5tOZDjREkuVWU`. Reviewed tip `f9d3cc72b`; base
`e3467ccb7`. All work stayed on the same branch/worktree.

## 1. F1 — `author_window` over the real author-period read

**Cause (confirmed on the real archive).** The channel sampled
`get_chat_history_messages(..., limit=fetch_k*20)`, i.e. `ORDER BY timestamp
ASC LIMIT`, so it only ever saw the first hours of the period. Measured by the
reviewer: 240 rows of 2025 cover 2025‑01‑01 00:11–08:32, while author
`138811255` wrote **122 722** messages in 2025 — zero in that slice, so the
channel silently returned nothing while an existing bounded author read
(`get_author_message_periods`) returned 24 rows for the same year in 0.77 s.

**Fix (no new engine).**
- `services/database.py::get_author_message_periods` + additive `years`:
  the same query (index range `(chat_id, timestamp)`, `user_id = ?`,
  `ORDER BY timestamp DESC LIMIT limit//5` per year) now accepts the years of
  the request. Default (no `years`) keeps the profile semantics unchanged.
- `services/mca_retrieval_context.py::retrieve` → `author_window` calls that
  read per author, filters to the exact window (`_author_window_bounds`), keeps
  the newest `fetch_k`, dedups by channel ordering. Bounded: `limit =
  max(5, fetch_k*20)` rows *read*, `fetch_k` delivered, no corpus scan.

**Proof on the local read-only archive** (`local_database_2026-09-04_history.db`,
chat `-1002661910336`, 1 928 313 rows; probe
`plans/features/vmq-onto-01/evidence/p0-memory-relevance/real_author_probe.py`):

    chat rows: 1928313
    author rows 2025 (existing read, limit 60): 12
    retrieve candidates: 12
    author-original candidates: 12 years: [2025] channels: ['author_window']

Before the fix the same request produced 0 `author_window` rows (reviewer R1/RA).

## 2. F2 — author and period actually reach production

**Period.**
- Live selection memory leg (`direct_chat_service._compose_user_content`):
  the turn's explicit year is resolved by the existing
  `resolve_period_intent` and sets `period_fill=True` on the request passed to
  `retrieve` (before: no period at all, `time_from/to=None`).
- The direct-RAG period leg already passed `period_fill`; unchanged.

**Author.**
- `_plan_material_author(plan)` — the material author comes from existing plan
  fields only: `target_user_id` is treated as the author **only when**
  `capabilities_needed` contains a read-only existing-material capability
  (`chat_memory` / `historical_search`). With `web_search`/no capability the
  named person stays the recipient — the RC1 role rule is preserved.
- The plan-driven RAG rescope (`_apply_plan_memory_scope` →
  `_build_rag_block(author_uid=…)` → `_rag_unified_rows(author_uid=…)` →
  `_rag_retrieve(author_uids=…)`) passes the uid into the period leg
  (`author_entity_ids`), adding the `author_window` channel to that call only.
- Originals are no longer dropped by the fact-only consumer:
  `_collect_originals(result)` keeps the verbatim messages, `_build_rag_block`
  renders them as a labelled `<Memory_Originals>` layer (canonical
  `_context_row_line` lines: date/author/ID) before the facts `<context>`, and
  an originals-only package still renders. Telemetry
  `period_message_candidates_used` / `..._reason` now report the delivered
  originals instead of a constant `fact_only_consumer`.

**Honest limit (corrects the earlier residual 2 wording):** before L1 there is
no author in the turn, so the live *selection* leg carries the period but not an
author; the author reaches retrieval through the plan-driven rescope and the
model-supplied `author` of `query_chat_memory`. No new L1 field, no new planner
contract.

## 3. Mutation survival (review N3/N4) and N5

- **M3 (year window on messages removed): KILLED** by the new test
  `TestMessageYearWindow::test_target_year_rows_survive_full_out_of_year_slice`
  (60 short out-of-year matches fill the `top_k*2` FTS limit; the single target
  year match is a long document that loses on bm25 rank; without the window the
  explicit-year filter empties the package, with the window the target row is
  read). Verified by running the test with `_message_period_window` forced to
  `None` (mutation applied locally, reverted): it fails — so the block is not
  dead logic and is kept.
- **N5 (quantitative ranges):** `_message_period_window` no longer reads
  `request.time_from/time_to`; the message FTS plan changes only for an
  explicit-year *period*. Range requests keep the accepted
  rank-then-post-filter basis. The author window uses
  `_author_window_bounds` (range allowed there only as bounds of its own
  bounded read).
- **M2:** the FTS author pushdown is now additionally covered by
  `TestOriginalsReachPayload::test_rescope_passes_author_and_period_to_retrieve`
  (author must appear in the request) and by the real-archive probe (12/12
  author rows in 2025).

## 4. Tests (RED → GREEN)

New file `tests/test_p0_memory_relevance_r1.py` (10 tests).

| Test | previous tip `f9d3cc72b` | this tip |
|---|---|---|
| `TestAuthorWindowOnDenseArchive::test_author_absent_from_first_rows_is_still_found` (3 authors × 300 rows, author only in December) | RED | GREEN |
| `…::test_author_window_does_not_return_other_years` | RED | GREEN |
| `…::test_author_read_is_bounded` (author read gets `years=(2025,)`, bounded limit) | RED | GREEN |
| `TestPlanMaterialAuthor::test_author_resolved_when_plan_requests_material` | RED | GREEN |
| `…::test_recipient_is_not_promoted_to_author` | RED | GREEN |
| `…::test_no_plan_no_author` | RED | GREEN |
| `TestOriginalsReachPayload::test_block_renders_author_originals` | RED | GREEN |
| `…::test_rescope_passes_author_and_period_to_retrieve` | RED | GREEN |
| `TestMessageYearWindow::test_target_year_rows_survive_full_out_of_year_slice` | GREEN on the tip (block present), **RED with M3** | GREEN |
| `TestLiveMemoryLegPeriod::test_explicit_year_reaches_live_memory_leg` | RED | GREEN |

Numbers: on `f9d3cc72b` the file gives **9 failed / 1 passed**; on this tip
**10 passed**. The pre-existing suite `tests/test_p0_memory_relevance.py`
remains **11 passed**.

Regression runs on this tip:
- `test_tool_router`, `test_mca15_chat_statistics_round1028`,
  `test_memory_unified_retrieval`, `…_06` — 210 passed.
- `test_memory_period_vector_leg`, `test_mem_time_policy`,
  `test_vmq_mem_retrieval_fixes`, `test_vmq_mem_rc2_message_rank`,
  `test_vmq_mem_slice_d`, `test_vmq_mem_period_intent`,
  `test_mca07_retrieval_context_round1027` — green after removing the always-on
  `author_uids` kwarg (additive-only-when-set, byte-parity for other callers).
- `test_vmq_mem_*` — **1 failed / 160 passed**; the failure
  (`test_vmq_mem_slice_b.py::TestHistoricalMeaningSelection::
  test_quota_is_bounded_by_slots_and_never_adds_current_year`) fails identically
  on base `e3467ccb7` (review N1). Previous claim "all green" was wrong and is
  corrected in the main evidence file.
- direct group (`test_direct_context_scenarios_asap3`,
  `test_direct_fallback_recompose_asap32`, `test_direct_l1_corrective_r1`) plus
  `test_ur_c_3_real_fts`, `test_ur_context_selection`, `test_history_isolation`
  — 7 failed / 106 passed, the same 7 pre-existing failures.
- `test_memory_quality_contract_07` (2), `test_speech_p0_a2_memory` (1) —
  pre-existing, identical on base.
- `py_compile` (changed modules + new tests): OK; `git diff --check`: clean.

## 5. Proof limits (unchanged, stated instead of implied)

- N6: the A/B/C/D replay and the block-render test are local fixtures; the
  Writer is not invoked (no network) and no live production turn was generated.
  The real-archive probe covers the retrieval/author-window claim only.
- N8: facts/vector legs cannot be exercised on the local archive (older schema,
  `no such column: f.importance`); fact attribution stays unit-level.
- The plan-driven author rule is a *structural* rule over existing fields; if
  L1 marks a style request without `chat_memory`/`historical_search`, no author
  is passed (honest "no material author known"), and the tool path stays the
  remaining channel for a model-declared author.
