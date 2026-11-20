# HC-COV slice A — review r1 fixes (F1–F5, F9)

- Reviewer: `evidence/cov/review-a-r1.md` (sha256 `5239e030…`), verdict `NEEDS_FIXES`.
- Reviewed product: `596f5e38d2de345df96f56509980527886e69ec0`.
- Branch/worktree: `p0/hc-a`, same worktree `c742e4de9e92c489/...`.
- Base: `1b7d43333b5be8fcbceff2fc82ff8436e5947e9d`.
- Scope: product/test fixes A only; no bump/deploy; no B/C files.
- New product candidate: 5eed27762456e34e5748d1fd3e3ba6b01c386f75 (see `tests.json`).

## RED before fixes

Added six focused regressions; on reviewed product `596f5e38` the five
blocking findings reproduce as **5 failed, 55 passed**:

- `pytest-review-fixes-596f5e38.txt` under `red-base/`.

## F1 — false complete on anchor_missing

- Cause: `_short_range` treated any `status=empty_window` as an empty range,
  overriding `available>0`, `incomplete=1`, `reason=anchor_missing`.
- Fix: short-path completeness now requires `incomplete=0` and
  `delivered(lines+skipped) >= available` (or available=0 for a truly empty
  range); `processed` is delivered rows, not `available`; reason keeps
  `anchor_missing`; `range_complete=0`.
- Regression: `test_retention_after_capture_is_not_complete_coverage`
  (delete rows after capture → page `empty_window available=20 incomplete=1
  reason=anchor_missing` → coverage `range_complete=0 processed=0 lines=0
  skipped=0 reason=anchor_missing`).
- Mutation `review-m3-f1-false-complete` (re-introduce empty_window override):
  test failed as expected; restored.

## F2 — skipped rows in tail pages

- Cause: `_iter_history_sample_entries` updated `fetched`/`lines` for tail
  pages but not `skipped`; `collect_history_segments` used only delivered-page
  header skipped.
- Fix: each tail page adds `max(0, len(rows)-len(lines))` to
  `stats["skipped"]`; segmented range `processed = ok segment rows + skipped`,
  so a read-but-unpresentable row is not mistaken for a missing tail.
- Regression: `test_skipped_tail_page_rows_are_counted` (120 rows, empty row
  on page 2 → `skipped=1 processed=120 lines=119 range_complete=1 reason=""`).
- Mutation `review-m4-f2-tail-skipped` (drop skipped increment): test failed as
  expected; restored.

## F3 — current-state «сегодня» became a forced history range

- Cause: `extract_history_window("как дела сегодня?")` → local_day and turn
  capture/force had no history-intent gate.
- Fix: new pure `tool_router.is_history_period_request(text, spec)`:
  - duration/unresolved needs a strong history marker OR `последн` OR explicit
    `за N` period;
  - local_day needs a strong history marker OR `за сегодня/вчера/позавчера`;
  - local_day_range is itself an explicit requested interval.
  `_capture_turn_history_sample` drops the spec when the gate is false, so no
  range bound/`chat_history` force. The tool's explicit model call path still
  uses the grammar directly.
- Regressions: `test_current_state_today_is_not_a_history_request`
  («как дела сегодня?» and «он пришёл 10 минут назад» → None);
  `test_explicit_today_history_questions_still_capture`
  («что было сегодня?», «за сегодня», «что было 10 минут назад» → range).
- No mutation required beyond the RED-on-candidate run.

## F4 — explicit time_window chronology without coverage

- Cause: `_history_chronology_in_window` marked the bound as range in the
  header but did not put it on `ctx.history_sample`; the short path/segments
  therefore had no range coverage. `requested` stayed 0.
- Fix:
  - explicit chronology bound is assigned to `ctx.history_sample` (both
    non-empty and empty/error paths);
  - live turn (`turn_as_of>0`) sets `requested=available`; legacy tool-only
    calls without a turn keep the accepted TIME-03 `requested=0/depth` unit
    contract (focused `test_vmq_recent_window` re-run green);
  - `collect_history_segments` now emits `@@HISTORY_COVERAGE` with
    `range_read/range_complete/lines/skipped`.
- Regression: `test_explicit_time_window_gets_coverage`
  (since/until with rows → header `requested==available==2`,
  `ctx.history_sample` range, coverage `range_read=1 range_complete=1
  processed=2 lines=2`).

## F5 — «за 3 дня до этого» resolved as last 3 days

- Cause: `_HISTORY_ZA_RE` unit `\w*` backtracked to a partial word and the
  negative lookahead saw «я до», not « до».
- Fix: added `\b` after the unit group so the full unit word is required before
  the `(?!\s+до\b)` check.
- Result: `extract_history_window("за 3 дня до этого") is None`;
  `extract_history_window("за 3 дня")` remains `duration/3 days`.
- Tests: wrong positive expectation replaced; new
  `test_za_days_before_event_is_not_now_anchored_duration`.

## F9 — evidence typo

- `implementation.md` now says **60 passed** (not 53/54); `tests.json` and
  `tests/new.txt` agree (60).
- `tests.json` focused result: **186 passed**.

## Results after fixes

| Check | Result |
|---|---|
| `pytest tests/test_p0_hc_coverage.py -q` | **60 passed** |
| Focused 6-file history suite | **186 passed** |
| Mandatory 24-file pytest | **386 passed, 1 warning** |
| Mutation F1 | expected RED, restored |
| Mutation F2 | expected RED, restored |

## Remaining non-blocking (unchanged)

F6 (probe None treated as empty), F7 (one-word durations parked for B/ACCEPT),
F8 (TIME-03 explicit time_window+query FTS exception), F10 (dead duck-typed
fallback cap) remain non-blocking/backlog. No B/C files, prompts canon, DDL,
flags, bump or deploy were touched.
