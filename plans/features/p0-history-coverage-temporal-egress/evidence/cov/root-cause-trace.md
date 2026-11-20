# HC-COV root-cause trace — ordinary Direct period question

- Base inspected: `1b7d43333b5be8fcbceff2fc82ff8436e5947e9d`.
- Incident source: owner input `plans/owner_inputs/2026-11-21-p0-history-coverage-temporal-egress.md`
  (§0/§1/§2), ordinary group-chat Direct summary of «последние 10 часов».
- Production trace availability: **unavailable in this environment**. The
  original effective release/config/prompt, `chat_id/message_id/trace_id`,
  actual tool args/as-of and delivered evidence are not claimed as facts here.
  Reproduction below uses an isolated synthetic SQLite fixture with the same
  execution paths; no live chat and no production data were touched.

## 1. Facts distinguished

| Fact | Where in this line | A slice status |
|---|---|---|
| N rows stored in `smart_messages` | `available` from range COUNT | proven on fixture and SQL path |
| N rows read by retrieval | `processed`, `range_read`, page `fetched/lines/skipped` | proven on fixture |
| N rows delivered to Writer evidence | `@@HISTORY_COVERAGE` in `_evidence` / first history `EvidenceSource` | proven on fixture; source packing is existing `build_evidence_pack` |
| N messages reached Telegram | `_send_direct_answer` egress | **not in A** (slice C), not claimed |

## 2. Base path and gaps

1. `DirectChatService._handle_turn` → `_capture_turn_history_sample`
   (base): only `extract_history_depth(query)`; no period grammar. A phrase
   «последние 10 часов» yields no turn sample.
2. `ToolRouter._get_recent_history` (base): `cursor → ctx.history_sample →
   time_window → depth → extract_history_depth → query(FTS) → 50`. There is no
   `extract_history_window`; a model call with only `query` takes
   `_recent_history_by_query` (FTS over `_HISTORY_QUERY_WINDOW_SECONDS`) or the
   default 50.
3. `_history_partial` (`direct_chat_service.py`) is true whenever any row is
   older than the visible L1 window — for a multi-year chat, almost always.
   `direct_l1.build_l1_context` turns it into `HISTORY_PARTIAL_LINE` (planner
   context). The composer path `_build_global_context_parts` additionally
   inserts `HISTORY_PARTIAL_INLINE` into `<Global_Context>`.
4. `HISTORY_COVERAGE_ASSEMBLY_BLOCK` reaches the Writer only when
   `history_sample is not None` (count path). There is no
   `range_read`/`range_complete`/`skipped` ledger for a period.
5. `collect_history_segments` short path returns `None`; a range that fits one
   slot would have had no coverage block.

These are independent causes: the caveat can be true about the operational
window while the requested period was never read; conversely, a fully read
stored period should not be described as «only part of history» because older
rows exist outside it.

## 3. Fix mapping

| Gap | Fix | Evidence |
|---|---|---|
| no period capture | pure `extract_history_window` + `resolve_history_window` + `capture_history_range` | tests `TestExtractWindow`, `TestResolveWindow`, `TestCaptureAndRoute` |
| range lost to FTS | range bound branch before query; `extract_history_window` before FTS | `test_range_bound_wins_over_query_fts_forbidden`, `test_empty_range_is_range_empty_not_error` |
| no coverage for short range | range short path renders `@@HISTORY_COVERAGE` and keeps page | `test_short_range_still_gets_coverage_and_keeps_page` |
| skipped rows invisible | header `lines/skipped`; coverage `lines/skipped`; skipped counted as processed | `test_skipped_rows_are_counted_not_silently_dropped` |
| operational caveat conflated with period | inline suppressed on sampled turns; L1 `ОХВАТ ПЕРИОДА`; Writer sentence names `range_read/range_complete` | `test_inline_partial_suppressed_on_sampled_turn`, `test_l1_range_note_is_separate_from_partial_line`, Writer instruction test |
| no deterministic tool call | existing `chat_history` capability forced on reply/range, execution mode recalculated | `TestForceAndWriterInstruction` |
| empty range treated as error | `empty_window`/`range_empty`, no cursor, coverage `range_complete=1` | `test_empty_range_is_range_empty_not_error`, `test_empty_range_coverage_is_complete_empty` |

## 4. Reproduction command

```powershell
cd <worktree>
C:\Code\Python\adminbot\.venv\Scripts\python.exe -m pytest tests/test_p0_hc_coverage.py -q
```

The fixture seeds a multi-row `smart_messages` SQLite table, fixes
`turn_as_of`, captures a range, dispatches `get_recent_history` and runs
`collect_history_segments`. The assertion set checks header fields, page
coverage, absence of `search_long_term` calls on range turns, coverage
`range_read/range_complete/lines/skipped`, and the Writer instruction.

## 5. Not verified here

- Real production trace and real archive ingestion gaps (owner §1/§3).
- Telegram delivery/`parse_mode` (slice C).
- Full temporal metadata matrix across RAG/graph/episodes (slice B).
- Real-model Writer wording (acceptance will run paired baseline/candidate on
  a read-only archive when available).
