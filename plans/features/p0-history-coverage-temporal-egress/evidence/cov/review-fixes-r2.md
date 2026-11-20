# HC-COV slice A — review r2 fix (HC-A-R2-F1)

- Reviewer: `evidence/cov/review-a-r2.md` (`31f89692…`), verdict `NEEDS_FIXES`, single blocker `HC-A-R2-F1`.
- Reviewed candidate: `5eed27762456e34e5748d1fd3e3ba6b01c386f75`.
- Branch/worktree: `p0/hc-a`, same worktree `c742e4de9e92c489/...`.
- Base: `1b7d43333b5be8fcbceff2fc82ff8436e5947e9d`.
- Scope: only the explicit-window error/retry seam; F1/F2/F3/F5 and core F4 untouched.
- New product candidate: `a58104f691ff3a7d2c2a543d6bb5646dfc5b3fd4` (see `tests.json`).

## Fault

`_history_window_error_page` persisted an error bound with
`range_status="unread"`, `available=0` but no `reason`. A later
`get_recent_history({})` treated it as an empty range
(`empty_window/range_empty`), and coverage said
`range_complete=1 range_read=1 processed=0 reason=range_empty`, losing
`db_error`. `_history_range_bound_page`/`_ensure_history_range_coverage` only
recognized `capture_failed`/`unresolved`; `collect_history_segments` keyed on
the last header, so an error source could be masked by an empty page.

## Fix

1. `_history_window_error_page` stores `reason` in the persisted bound.
2. `_HISTORY_RANGE_ERROR_STATUSES` recognizes `capture_failed`, `unresolved`,
   `unread`, `error`. `_history_range_bound_page` returns
   `status=error`, the bound reason (`db_error`/`timeout`/`search_failed`),
   `next_cursor_enabled=False` — never `empty_window/range_empty`.
3. `_ensure_history_range_coverage` treats `unread`/`error` as unread coverage
   (`range_read=0`, `range_complete=0`, concrete reason).
4. `collect_history_segments` checks the bound status first: an error/unread
   bound always yields unread coverage, regardless of the last header. When a
   later successful retry source exists, earlier error sources are dropped
   from `hist`; coverage is recomputed for the new range.
5. Retry: if `ctx.history_sample` is an error-bound and the call carries a new
   valid `time_window`, the old bound is cleared and the new window is captured
   as a fresh range. Successful/empty range bounds are not cleared (H8).
6. Empty valid window remains `range_status=empty` / `range_empty`, not error.

## RED / GREEN

- RED on reviewed product `5eed2776`: new
  `test_error_not_masked_and_retry_valid_window` failed at the persisted bound
  reason (`KeyError: 'reason'`, then empty mapping); artifact
  `red-base/pytest-review-r2-5eed2776.txt` (**1 failed, 61 passed**).
- GREEN after fix:
  - `pytest tests/test_p0_hc_coverage.py -q` → **62 passed**
  - focused 6-file suite → **188 passed**
  - mandatory 24-file set → **386 passed, 1 warning**
- The second new test, `test_empty_valid_window_stays_range_empty`, is a
  compatibility guard (empty valid window must remain `range_empty`); it was
  green on `5eed2776` and remains green.

## Mutation

- `review-r2-unread-to-range-empty`: remove `unread`/`error` from
  `_history_range_bound_page` error statuses → the new regression fails
  (`error` becomes `empty_window`), then restore. Artifact:
  `mutations/review-r2-unread-to-range-empty.txt`.

## Remaining non-blocking (unchanged)

F6 (probe None as empty), F7 (one-word durations — B/ACCEPT), F8 (TIME-03
explicit `time_window`+`query` FTS exception), F10 (dead fallback cap).
No bump/deploy/B/C changes; no DDL/flags/prompt canon.
