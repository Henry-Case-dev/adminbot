# HC-COV slice A — implementation and evidence

- Task: `p0-history-coverage-temporal-egress-01`, slice `HC-COV` (A).
- Base: `1b7d43333b5be8fcbceff2fc82ff8436e5947e9d` (2.58.225 content tip; actual deployed SHA was not contacted by this slice).
- Branch: `p0/hc-a`.
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\p0-history-coverage-temporal-e-cbf9b3fab6a8-6a3294ea`
  (created with installed `workflow_housekeeping.py worktree-path` + `git worktree add`; no sibling checkout).
- Product/tests candidate: `a58104f691ff3a7d2c2a543d6bb5646dfc5b3fd4`.
- Evidence commit adds only `plans/features/p0-history-coverage-temporal-egress/evidence/cov/**`.
- Deploy/bump: none. DDL/flags/prompts canon/`chat_prompts.py`: none.

## 1. What the ordinary Direct period question did at base

1. `DirectChatService._handle_turn` captured a turn sample only through
   `extract_history_depth(query)` (N messages). A period phrase such as
   «последние 10 часов» did not produce any sample, so `tool_ctx.history_sample`
   stayed empty.
2. L1 could answer/plan without `chat_history`; `derive_simple_steps` had no
   deterministic history step. If the model did call `get_recent_history` with
   only `query`, the route fell to `_recent_history_by_query` (FTS over recent
   hours) or to the default 50, not to the requested chronology.
3. `_history_partial` truthfully reported that rows older than the operational
   L1 window exist (always true for a multi-year chat). On the composer path
   `_build_global_context_parts` inserted `HISTORY_PARTIAL_INLINE` into
   `<Global_Context>`, and `HISTORY_COVERAGE_ASSEMBLY_BLOCK` reached the Writer
   only when a count sample existed. There was no independent
   `range_read`/`range_complete` ledger for a period.
4. `collect_history_segments` returned `None` on the short path, so a range that
   fit one slot had no coverage block at all.

Full production trace (release/config/prompt effective values, original
`chat_id/message_id/trace_id`, actual tool args, delivered evidence and Telegram
`parse_mode`) is **not available in this environment**. The failure was
reproduced on an isolated synthetic SQLite fixture through the same execution
path; see `root-cause-trace.md` and `tests/test_p0_hc_coverage.py`. Telegram
egress is slice C and is not claimed here.

## 2. Implemented behavior (A)

- `services/tool_router.py`
  - `HistoryWindowSpec` + pure `extract_history_window(text)` (closed grammar:
    duration with `последн/назад/за`, `полчаса`, `сутки`, local day
    `сегодня/вчера/позавчера [с HH:MM до HH:MM]`, date range `с DD.MM[.YYYY]
    по DD.MM[.YYYY]` / `с DD <месяц>`; bare «10 часов» → `None`; period-like
    but unparsed → `unresolved`).
  - `resolve_history_window_at(spec, as_of, timezone)` + async
    `ToolRouter.resolve_history_window(..., chat_id)`: one IANA zone from
    ChatClock, local midnight, DST spring shift to the first valid instant,
    fall-back `fold=0`, inclusive local end-of-day.
  - `capture_history_range(db, chat_id, from_ts, to_ts, as_of, clamped)`:
    real newest `<= to`, real oldest `>= from`, exact `available` COUNT,
    metadata-only SQL (`_HISTORY_COUNT_IN_WINDOW_SQL` / existing reader);
    empty range is a bound with `available=0`, `range_status="empty"`,
    `reason=range_empty`, no cursor.
  - `get_recent_history` route: `cursor → ctx.history_sample (range) →
    time_window → depth → extract_history_depth → extract_history_window →
    query(FTS) → 50`. A range bound always returns chronology; FTS is not
    called. `last_*` is resolved from `turn_as_of`, not a new `time.time()`.
  - Range-only header fields: `window_kind/window_from/window_to/as_of/
    clamped/requested/available/processed/remaining/has_next/lines/skipped`;
    count header remains byte-identical. Cursor remains the existing v3 format;
    continuation takes range metadata from `ctx.history_sample` by matching
    `sample_id`.
- `services/direct_chat_service.py`
  - One `turn_as_of = int(time.time())` per Direct turn; passed to capture and
    `ToolContext`.
  - `_capture_turn_history_sample`: range first (duration/local day/date range),
    then count; count-unit queries are not misread as unresolved periods;
    range resolve/capture failure → explicit marker (`capture_failed`/
    `unresolved`), never FTS/default.
  - `_l1_tool_phase`: on reply/empty action with active range, deterministically
    adds existing `chat_history` capability and recalculates
    `derive_execution_mode`; react/silent/clarify are not forced.
  - `collect_history_segments`: range short path now emits coverage while
    keeping the page; segmented path reports `range_read`,
    `range_complete`, `lines`, `skipped`; skipped rows are counted, not silently
    dropped; no history source → dedicated `history_coverage` EvidenceSource;
    no tool phase → coverage is prepended to `_evidence` with
    `range_read=0`/concrete reason.
  - `_build_global_context_parts(history_sample=...)`: no
    `HISTORY_PARTIAL_INLINE` on sampled turns; `_history_partial` and
    `HISTORY_PARTIAL_LINE` remain operational for L1.
- `services/direct_l1.py`: additive protected `ОХВАТ ПЕРИОДА` section
  (`history_range_note`), only for range turns; byte parity otherwise.
- `services/prompt_style_blocks.py`: one additive Writer sentence about
  `@@HISTORY_COVERAGE` (`range_read/range_complete`, `available` = stored rows,
  not continuous-chat proof).
- `services/tool_schemas.py`: description teaches that a period question reads
  the full stored chronology and FTS matches never replace it (schema fields
  unchanged).

## 3. Deliberate deviations from the plan text (with reasons)

1. **`time_window` already existed at base** (VMQ/MEM-TIME, `since/until/
   last_seconds`). A did not add a second window shape: it reuses the existing
   structured window and adds deterministic text extraction + range capture.
   Adding fields would break the existing accepted schema assertion
   `tests/test_vmq_recent_window.py::...test_schema_teaches_structural_period`
   (`set(fields) == {"since","until","last_seconds"}`), which is outside A's
   write scope and a mandatory unaffected invariant.
2. **Cursor is v3 at this base, not v2.** A leaves the format and payload
   unchanged; range continuation metadata comes from `ctx.history_sample` by
   `sample_id` as the contract requires, without a v4.
3. **`services/direct_execution.py` was not touched**: the existing
   `derive_simple_steps`/`chat_history` seam was sufficient; the packer is
   unchanged.
4. **`services/chat_prompts.py` was not touched** (per plan/contract).
5. **Review r1 (F1–F5) fixes:** short-path completeness no longer treats
   `empty_window` as complete when `available>0`/`incomplete=1`; tail-page
   skipped rows are counted; turn capture has a history-intent gate (current
   state «как дела сегодня?» stays current-state); explicit `time_window`
   chronology gets the range bound + coverage ledger (`requested=available`
   on a live turn; legacy tool-only TIME-03 calls keep `requested=0/depth`);
   `за N дней до …` is no longer a now-anchored duration. Details:
   `review-fixes.md`.
6. **Review r2 (HC-A-R2-F1):** a persisted explicit-window error bound keeps
   `range_status=unread`, its `reason` (`db_error`/`timeout`/`search_failed`)
   and `range_complete=0`; an empty page cannot mask it. A new valid explicit
   window replaces an old error bound as a retry; an empty valid window remains
   `range_empty`. Details: `review-fixes-r2.md`.
7. **FTS boundary:** the turn range-bound (`ctx.history_sample`,
   `window_kind=time_range`) always wins, ignores `query` and never calls
   `search_long_term`; the deterministic extraction path also forbids FTS.
   An explicit model-supplied `time_window` **with** `query` keeps the
   existing TIME-03 query-in-window behaviour (accepted tests
   `test_no_match_when_window_has_messages` / `test_ctx_query_ignored_when_window_present`),
   which the slice is required to preserve. This is not a silent chronology
   substitution: the turn range-bound is what the period question produces.

## 4. Tests and proofs

Machine-readable: `tests.json`. Raw outputs: `tests/`, `red-base/`,
`mutations/`.

| Batch | Result |
|---|---|
| New `tests/test_p0_hc_coverage.py` | **62 passed** |
| New + existing history pages/segments/depth/VMQ/isolation marker | **188 passed** |
| Mandatory 24-file pytest set | **386 passed, 0 failed** |
| RED on base `1b7d43333` (new contract symbols absent) | collection `ImportError` (saved) |
| Mutations (8) | each expected RED; restored tree **188 passed** on focused rerun |

Mutation coverage: range→FTS, wrong local midnight, page drop, partial inline,
missing `range_empty`; review-r1 F1 false-complete and F2 tail-skipped.
Review-fix matrix and RED/GREEN: `review-fixes.md`.

## 5. Limitations / not in scope

- Production trace and a read-only copy of the real chat archive were not
  available; reproduction is a synthetic SQLite fixture through the same
  execution path. No live chat, no production writes, no Telegram sends.
- `HC-COV-TRACE` therefore records this evidence limitation explicitly; it does
  not claim production facts.
- Telegram Markdown egress (`**...**` incident), temporal metadata matrix and
  full acceptance batteries belong to C1/C2/B/ACCEPT, not this slice.
- `tests/test_speech_p0_a2_memory.py::TestSelfEchoNotFactual::
  test_style_anchors_not_broken` fails outside the mandatory set because the
  `style_anchors` section was intentionally removed in UR-14; A does not touch
  that path and does not use it as evidence.
- No new flags, no DDL, no dependency/config/release changes; no deploy.

## 6. Cleanup

- RED-base worktree was removed cleanly (`git worktree remove`, no force);
  only the temporary copied test file was deleted before removal.
- Mutations used a temp backup and were restored; post-restore focused tests
  passed.
- No production artifacts, no live data, no worker left running.
