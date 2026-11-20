# HC-TIME slice B - independent review r1

```json
{
  "schema": "p0-hc-time-review-v1",
  "task": "p0-history-coverage-temporal-egress-01",
  "slice": "HC-TIME",
  "candidate": "24f0f76672c4f5187700c19cdbf9492481e016f3",
  "branch": "p0/hc-b",
  "base": "658661710add58b88dfcb7a18a43bd7ad15d5f89",
  "evidence_tip": "a94b82576f7ec2bdfc5ee2d160b5d138dab85331",
  "verdict": "NEEDS_FIXES",
  "covered_ids": ["HC-TIME-SMART-CONTEXT", "HC-TIME-HISTORY-TOOL", "HC-TIME-RETRIEVAL", "HC-TIME-EVIDENCE-WRITER", "HC-TIME-FMT-PRECISION", "HC-TIME-CANDIDATE-FIELDS", "HC-TIME-CLOCK-TZ", "HC-TIME-EVENT-VS-RECORDED", "HC-TIME-MATRIX", "HC-TIME-PAYLOAD-PROOF", "HC-TIME-TAXONOMY", "HC-TIME-RANGE-SEMANTICS", "HC-ACC-TIME (supporting)", "HC-ACC-CHANNELS (supporting)"],
  "blockers": ["HC-B-F1"],
  "non_blocking": ["HC-B-NB1", "HC-B-NB2", "HC-B-NB3", "HC-B-NB4"],
  "commands": {
    "new": "python -m pytest tests/test_p0_hc_temporal.py -q => 30 passed",
    "isolation": "python -m pytest tests/test_history_isolation.py -q => 21 passed",
    "focused": "16-file history/time focus => 739 passed, 2 deselected",
    "mandatory": "24-file mandatory set => 386 passed, 1 warning",
    "time03_next02": "TIME-03/NEXT-02 relevant 5-file set => 110 passed (evidence claims 108; command not recorded)",
    "red_a_tip": "B tests on A tip 65866171 => 22 failed, 29 passed (artifact)",
    "mutation_drop_sent_at": "get_smart_window SELECT drops sent_at => test_smart_window_selects_reply_edit_sent_at failed; restored",
    "mutation_local_tz": "_ha_fmt_ts local fromtimestamp => test_message_timestamp_renderers_are_utc failed (12:00 vs 00:00); restored"
  },
  "payload_proof": {
    "file": "evidence/time/payloads/writer-payload.json",
    "sha256": "e88ed1d14a54b1e2feb4b26c47bca070c933120279dff43f26ba7d1c17d806ce",
    "observed": "reply edge, edit stamp, recorded fact label, one UTC legend in actual _l2_write_answer user content; no DDL/DTO substitute"
  },
  "proof_limitations": ["No production trace/read-only real archive or live Telegram/Writer run; payload proof is isolated synthetic SQLite through real L2/global/history/RAG boundaries.", "No deploy or product edits by reviewer."]
}
```

## Scope / no-regression check

- Product diff `65866171..24f0f7667`: `canonical_context.py`, `database.py` (only `get_smart_window`/`get_recent_messages` SELECT lists and `get_messages_around` `_fields`), `direct_chat_service.py`, `mca_retrieval_context.py`, `summary_memory.py`, `tool_router.py`, plus `tests/test_history_isolation.py` and new `tests/test_p0_hc_temporal.py`.
- No DDL, indexes, ORDER BY, ranking, `rag_ts`, `_apply_filters`, flags, prompts, Telegram, version bump or deploy. No B/C file leakage beyond the frozen B list.
- A window parser/header/coverage code is untouched; focused A tests pass except the known exact-cut fixture (below).

## Verified positive seams

- SQLite row -> `get_smart_window`/`get_recent_messages`/`get_messages_around` now exposes `sent_at/edited_at/reply_to_author_id`; raw canonical and history lines render `ответ на tg:... (uid ...)` and `ред. ... UTC`; legacy rows stay byte-identical.
- `_ha_fmt_ts`/`_format_timestamp`/`format_utc_timestamp` are UTC; `_fmt_ts` bytes unchanged; chat-zone/DST labels do not leak into UTC labels; A `turn_as_of` path is used.
- `RetrievalCandidate` additive defaults and message/fact/vector/reply/episode constructors distinguish source/recorded/event/unknown; `sent_at`, `score`, channel ranks, dedup and `_apply_filters` are unchanged. Episode event fields are row-aware and fall back to recorded/unknown when the facade lacks event columns; valid_* remain honest defaults 0 (not rendered as event time).
- Graph-fact `_fact_time_origin`, `_fact_prefix` recorded label, 8th Direct-RAG tuple element, `_format_origin_labeled_line`, and `build_rag_context` parity are covered; legacy 7-tuple contract remains.
- Actual `_l2_write_answer` payload proof contains reply edge, edit stamp, recorded fact label and exactly one UTC legend after the clock block; sha256 matches `writer-payload.sha256`. Empty/repeated time_line behavior is covered.
- New 30 and isolation 21 pass; focused 739/2, mandatory 386 and TIME-03/NEXT-02 support set (110 independently run) pass.

## Blocker

### HC-B-F1 (P1, IN_SCOPE) - Thread/Branch context still loses reply/edit; matrix and payload proof overclaim it

- Contract: `HC-TIME-SMART-CONTEXT` explicitly includes direct Global/Thread/Reply-context; arch contract section 3.2 names `thread_chain.format_chain_line` and B action `ответ на ...`/`ред. ...`; `HC-TIME-PAYLOAD-PROOF` requires the final payload, not DTO/select-only.
- Actual code: `_render_thread`/`_render_branch` call `thread_chain.format_chain_line` / `render_speech_line`. `format_chain_line` calls `format_context_item` without `reply_to` or `edited_at`; `ChainItem` has `reply_to_item_id` but no `edited_at`; `render_speech_line` also has no edit stamp. The new `get_messages_around` SELECT fields are therefore not consumed by the Thread/Branch renderer.
- Independent check: `ChainItem(uid=7, name="A", text="x", item_id="tg:12", reply_to_item_id="tg:11", ts=1704067200)` -> `format_chain_line` output `[01.01.2024 00:00 UTC | A [7] | tg:12]: x`, with no `ответ на` and no `ред.`. The Thread/Branch context is a real Writer block (`<Conversation_Thread>`/`<Conversation_Branch>`), but the proof JSON contains no such block; the matrix row claims reply/edit for `Global/Thread/Reply/current`.
- Expected: a storage row with reply/edit metadata must surface those fields in the final Writer payload for Thread/Branch too (or the slice must formally exclude Thread and remove the matrix/payload claim). Current evidence is storage/DTO-only for this channel.
- Fix direction: carry `reply_to`/`edited_at` into `ChainItem` and pass them through `format_chain_line`/`render_speech_line`, or render Thread/Branch via the already-updated `_context_row_line`; add a final-payload test with `<Conversation_Thread>` and a reply/edit row. If `thread_chain.py` is truly outside frozen B write scope, get an explicit Architect scope adjustment and move the channel to C2/ACCEPT; do not claim it as delivered in B.

## Known test-shape shift (non-blocking for B product, test-only addendum required)

- `tests/test_history_segments.py::TestBoundaryContinuity::test_intra_page_cut_reply_keeps_connection` fails at `seg 3` start 121 vs expected 122. Independent probe: with reply segment on row 111, `slot=sum(len(lines[:11])+1)` yields segment ranges `100..110`, `111..120`, `121..130`, `131..139`; coverage `complete=1`. Row 122 replies to 121 but both are now inside segment 3, so the old test no longer exercises a second cross-segment connection; no reply data is lost.
- This is a legal test-shape shift: the fixture computes its slot from pre-B line lengths while additive reply metadata lengthens line 111. The product behavior (reply edge, complete coverage) is correct. The test file is outside B write scope and was deselected; a conscious test-only addendum should recompute the slot from the actual rendered lines (or choose a reply row across the new cut). This is not a product regression or B blocker.

## Other non-blocking / evidence notes

- **HC-B-NB2:** `test_ur_c_clock::TestFallbackAdapterClock::test_generous_budget_keeps_block_intact_same_asof` fails identically on A tip 65866171 and B (pre-existing fallback capacity assertion; artifacts match).
- **HC-B-NB3:** the evidence claims `TIME-03/NEXT-02 108 passed` but does not record the exact command. Independent run of the relevant five-file set produced 110 passed; no TIME-03/NEXT-02 failure or ranking/recency change was observed.
- **HC-B-NB4:** `sent_at` is added to the three SELECT lists and is tested as storage, but the message Writer line uses `timestamp` only; if source date and event timestamp differ, the model still sees only one label. The matrix should state this limitation or render the source date explicitly. It is not a separate blocker while `timestamp` remains the event label and `sent_at` is identical on live rows.
- Episode facade does not expose event_start/end; B correctly falls back to recorded/unknown and does not invent event time. valid_from/valid_to remain honest defaults 0 in this line.

## C2 / ACCEPT remaining

- **C2:** call-site in `_send_direct_answer` only; reuse `telegram_markup.py`; no `/summary`, global parse_mode or send defaults; partial Rich failure without duplicates.
- **ACCEPT:** paired baseline/candidate on read-only real archive; History/time/channel/Telegram/free-speech batteries; actual final payload capture including Thread/Branch; TIME-03/NEXT-02; production SHA; no owner QA.

## Verdict

- `NEEDS_FIXES` for slice B: the core metadata/taxonomy/payload seams are strong, but the contract's direct Thread/Branch channel does not deliver reply/edit and the evidence claims it does. Test-shape shift is non-blocking and test-only; pre-existing ur_c_clock and the unrecorded 108 command are evidence notes, not product blockers.
