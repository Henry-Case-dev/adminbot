# REL226-F1 — speech history lines use the projected reply label

**Status:** FIXED in candidate; re-review pending
**Finding:** delta review of release 2.58.226, blocker `REL226-F1`
**Product commit:** `a7200eba70d32f05c5fd019312dd2165d3ced681` (`fix/p0-hc-accept`)
**Release commit:** `5dd588201c27419d93f9414c66b9aac5557e34b9` (cherry-pick on `e7c9a2e66`)
**Base / rollback unchanged:** `1b7d43333b5be8fcbceff2fc82ff8436e5947e9d` (2.58.225, schema 48, DDL 0)

## 1. Defect

`ToolRouter._history_lines` (`services/tool_router.py`) speech branch
(`projection is not None` and `speech_projection_enabled()`) passed the RAW
reply reference into the speech line:

```python
reply_ref = resolve_item_id(tg_message_id=parent_tg)
if reply_ref and reply_uid not in (None, "", 0):
    reply_ref = f"{reply_ref} (uid {reply_uid})"
...
format_speech_item(..., reply_to=reply_ref or None)
```

`format_speech_item` prints `reply_to` verbatim as the header segment
`| ответ на <ref> |`, so a reply row produced the raw service address:

```
[30.04.2024 16:01 UTC | Марина (U2) | M2 | ответ на tg:500 (uid 9)]: ответ
```

That violates the function's own docstring (run labels instead of ids/uid) and
the consumer contract asserted by `tests/test_evol_reply_context_consumers.py`
(`_assert_no_service_ids`: no `tg:`/`msg:`/`fact:` refs, no bare uid). The
existing test stayed green only because its fixture had no reply metadata. The
reply segment itself is introduced by this delta (no `reply_ref` /
`reply_to_id` in `services/tool_router.py` at base `1b7d43333`), so this is a
delta-introduced defect, not old behavior.

## 2. Fix

The speech branch resolves the parent's run label from the SAME projection,
under `try/except` — the pattern already used by
`direct_chat_service._context_row_line`:

```python
reply_label = None
if reply_ref:
    try:
        reply_label = projection.label_of_item(
            resolve_item_id(tg_message_id=parent_tg)) or None
    except Exception:
        reply_label = None
format_speech_item(..., reply_to=reply_label, edited_at=edited_at)
```

- Parent already labeled (inside the shown rows) → header edge `ответ на M…`;
  `projection.raw_of("M…")` resolves back to `tg:<id>`.
- No label (parent outside the shown rows) → edge omitted honestly: no invented
  relation and no raw id.
- Raw branch (`format_context_item`, `with_user_id=True`, `projection=None` /
  flag OFF) is byte-identical: `| ответ на tg:<id> (uid N) |` stays.
- No SQL/DDL/field/flag/second renderer; `edited_at`, media marker, forward and
  absolute time are untouched.

Diff: `services/tool_router.py` +18/−2 (docstring + speech branch only),
`tests/test_evol_reply_context_consumers.py` +45 (two tests).
`git diff --name-only e7c9a2e66..5dd588201 -- services` = `services/tool_router.py`.

## 3. RED (release tip before the fix, `e26ebc163`)

Tests added, product not yet fixed, product worktree at `e26ebc163`:

```
py -3 -m pytest tests/test_evol_reply_context_consumers.py -k recent_history_reply -q
2 failed, 51 deselected
```

Both tests fail on the same leak:

```
payload = '[30.04.2024 16:00 UTC | Вася (U1) | M1]: родитель\n[30.04.2024 16:01 UTC | Марина (U2) | M2 | ответ на tg:500 (uid 9)]: ответ'
_assert_no_service_ids -> assert not _REF_RE.search(payload)
assert not <re.Match object; span=(102, 108), match='tg:500'>
FAILED ...::TestToolResults::test_recent_history_reply_uses_projected_label
FAILED ...::TestToolResults::test_recent_history_reply_outside_projection_not_invented
```

## 4. GREEN (release tip `5dd588201`)

```
[tests/test_evol_reply_context_consumers.py]
py -3 -m pytest tests/test_evol_reply_context_consumers.py -q
53 passed

[mandatory set: p0_hc coverage/temporal, history pages/segments/isolation, direct_chat]
py -3 -m pytest tests/test_p0_hc_coverage.py tests/test_p0_hc_temporal.py \
    tests/test_history_pages.py tests/test_history_segments.py \
    tests/test_history_isolation.py tests/test_direct_chat.py -q
358 passed
rc=0
```

No new failures in the mandatory set. Raw result lines: `tests-rel226-f1.txt`.

Exact observable payloads after the fix (same inputs as the RED case):

```
SPEECH:        [30.04.2024 16:00 UTC | Вася (U1) | M1]: родитель
SPEECH:        [30.04.2024 16:01 UTC | Марина (U2) | M2 | ответ на M1]: ответ
RAW:           [30.04.2024 16:01 UTC | Марина [20] | tg:501 | ответ на tg:500 (uid 9)]: ответ
SPEECH, parent outside the shown rows:
               [30.04.2024 16:01 UTC | Марина (U1) | M1]: ответ   (no invented edge)
```

## 5. Tests added (`tests/test_evol_reply_context_consumers.py::TestToolResults`)

- `test_recent_history_reply_uses_projected_label` — parent row + reply row
  under `SpeechProjection`: `_assert_no_service_ids` passes, no `tg:500`, no
  `(uid 9)`, the header carries the parent's label (`ответ на M1`), the label
  resolves through `raw_of`; the same rows without a projection still carry
  `ответ на tg:500 (uid 9)`.
- `test_recent_history_reply_outside_projection_not_invented` — reply row alone
  under a projection: no service ids, no `ответ на` segment invented, no `uid`.

## 6. Invariants re-checked

- `config/settings.py` is not touched by the fix; `APP_VERSION = "2.58.226"`.
- `git diff --name-only e7c9a2e66..5dd588201 -- services` = `services/tool_router.py` only.
- `manifest-dry-run.json` rerun at the content tip: version `2.58.226`,
  `dirty_tracked=false`, `deployed_sha=5dd588201…`; `previous_sha` /
  `previous_version` are `null` locally because a fresh worktree has no
  `.deploy/` manifest — the production checkout keeps its own previous manifest
  and reports the real value.
- The evidence commit on top of the content tip is docs-only; the deployed
  checkout SHA must equal the manifest `deployed_sha` exactly (runbook §3/§3.1).

## 7. Non-blocking, parked (no code change here)

- `REL226-N1` — `_context_row_line` speech can state the same reply twice
  (header edge `ответ на M…` plus relation `↳ Reply M…` when the parent is in
  `window_items`). Redundant but correct; separate scoped change, not this
  release.
- `REL226-N2` — one bare LF among CRLF lines in `config/settings.py`
  (pre-existing encoding shape, preserved byte-for-byte by the bump).
- `REL226-N3` — runbook §3.1 wording closed in this evidence commit: no
  “authorized test chat”, postdeploy stays read-only, plus identity
  `verified_deployed`, separate local/public `/healthz`, prompt/profile digests
  pre==post and exact `deployed_sha` == checkout SHA equality.
