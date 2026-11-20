# HC-TIME (slice B) — implementation and evidence

- Task: `p0-history-coverage-temporal-egress-01`, slice `HC-TIME` (B).
- Base: A tip `658661710add58b88dfcb7a18a43bd7ad15d5f89` (product A `a58104f691ff3a7d2c2a543d6bb5646dfc5b3fd4`, base `1b7d43333b5be8fcbceff2fc82ff8436e5947e9d` / 2.58.225).
- Branch: `p0/hc-b`; worktree `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\p0-history-coverage-temporal-e-cbf9b3fab6a8-912d3c5b` (installed `workflow_housekeeping.py worktree-path` + `git worktree add`, `register-worktree`).
- Product/tests candidate: `1fe684d369d753449cf1bdc974de6fdefdd1c8ca`; evidence commit adds only `evidence/time/**`.
- Scope: only B product files + `tests/test_history_isolation.py` + new `tests/test_p0_hc_temporal.py` + `evidence/time/**`.
- HC-B-F1 addendum (Reviewer-directed): `services/thread_chain.py` and the test-only `tests/test_history_segments.py` addendum are included; PM amends the graph.
- No DDL, indexes, ORDER BY, ranking/`rag_ts`/`_apply_filters`, flags, prompts, version bump or deploy.

## 1. What was lost before B

`smart_messages` already stored `sent_at`, `edited_at`, `reply_to_id`, `reply_to_author_id`, but the operational readers did not select them:

- `DatabaseService.get_smart_window` / `get_recent_messages` / `get_messages_around` returned rows without `sent_at/edited_at/reply_to_author_id`;
- therefore `_context_row_line` and `ToolRouter._history_lines` could not render a reply edge or an edit;
- graph facts exposed `rag_ts = COALESCE(message_timestamp, created_at)` without saying which source won, so a `created_at`-only fact could read as a month-of-event;
- `RetrievalCandidate` had `sent_at` only, with no machine distinction source/recorded/event/unknown and no episode event window;
- `time_line` showed the chat's local zone while message lines are UTC, with no single legend.

The mandatory storage→Writer regression is exactly this: metadata exists in storage but is lost before the model.

## 2. Implemented behavior (B)

### `services/canonical_context.py`

- Additive closed taxonomy constants: `TIME_ORIGIN_SOURCE|EVENT|RECORDED|UNKNOWN`, `RECORDED_DATE_LABEL`, `REPLY_EDGE_PREFIX`, `EDITED_SEGMENT_PREFIX`.
- `format_context_item` / `format_speech_item` gained additive kwargs `time_origin`, `reply_to`, `edited_at` with defaults equal to the old bytes. Header order:
  `[ДД.ММ.ГГГГ ЧЧ:ММ UTC | [дата записи] | автор | ID | [ответ на …] | [ред. …] | Переслано: …]: текст`.
- `recorded` is added only for `kind=fact`; month remains first, so `canonical_line_pattern(KIND_FACT)` and `CONTEXT_POINTS` `direct_rag`/`legacy_rag` still match.
- `_fmt_ts` bytes were not changed: `msg` is minute-UTC, `fact`/`archive` remain month-only.

### `services/database.py`

Read-only SELECT lists only, exactly the three allowed methods:

- `get_smart_window` and `get_recent_messages`: `+ sent_at, edited_at, reply_to_author_id`;
- `get_messages_around` `_fields`: the same three.

No other SQL, DDL, index, ORDER BY or filters changed.

### `services/direct_chat_service.py`

- `_context_row_line` renders `ответ на tg:<reply_to_id> [(uid <reply_to_author_id>)]` and `ред. <UTC>` in both raw and speech projection; absent fields keep byte parity.
- `_ha_fmt_ts` remains the UTC renderer (`format_utc_timestamp`); a B guard test pins it (the base 2.58.225 already had the UTC fix from VMQ/MEM-TIME).
- `_chat_time_line` and a `time_snapshot` object do not exist in this line (removed by UR-C-CLOCK); the single clock is `chat_clock`/`render_chat_time_context`. B does not introduce a second clock or a second `time.time()`: relative windows resolve from the passed `turn_as_of` (A), and the focused `tests/test_ur_c_clock.py` covers IANA/DST/local-midnight on the same snapshot.
- `_TIME_ZONE_LEGEND` + `_with_time_zone_legend`: one phrase appended to the Writer `time_line`; applied in `_l2_write_answer` (all Writer invocations, including initiative) and the legacy `build_messages` path. Empty `time_line` stays empty; repeated assembly does not duplicate the phrase. `chat_clock.py` is outside B scope and was not touched.
- `_rag_meta_from_record` carries `time_origin`; `_rag_rows_with_ranks` emits the 8th tuple element at the Direct-RAG boundary.

### `services/summary_memory.py` (narrow)

- `_fact_time_origin(row)`: `message_timestamp` → `source`, `created_at` → `recorded`, neither → `unknown`; `rag_ts` unchanged.
- `_fact_prefix(..., time_origin)` appends `| дата записи` after the month only for `recorded`.
- `_format_origin_labeled_line` reads the 8th tuple element and passes `time_origin` to `format_context_item`/`format_speech_item`.
- `with_meta` dicts (`_search_graph_facts`, `_knn_graph_facts`) expose `time_origin` for the Direct-RAG tuple builder.
- `build_rag_context` structure/order was not changed (verified by an equality test).

### `services/tool_router.py`

- `_format_timestamp` remains UTC (already fixed at base); a B guard test pins it.
- `_history_lines` renders the same additive reply/edit segments for `get_recent_messages` rows; absent fields keep the old canonical bytes.
- Window parser/header/A routing were not touched (A preserved).

### `services/mca_retrieval_context.py`

- `RetrievalCandidate` additive fields with `/` defaults: `time_kind=""`, `recorded_at=0`, `valid_from=0`, `valid_to=0`, `event_start=0`, `event_end=0`, `discovered_at=0`.
- Message constructor: `time_kind=source|unknown`, `recorded_at=ingested_at` when the channel provides it.
- Fact constructors: `message_timestamp` → `source`, `created_at` → `recorded`, neither → `unknown`; `recorded_at=created_at`; `valid_from/valid_to` read when present in the row; `sent_at` unchanged (COALESCE).
- Episode constructor: explicit `event_start_ts/event_end_ts` → `event`; `discovered_at`/`created_at` → `recorded`; legacy `last_ts` → `source`; `sent_at` unchanged.
- Reply-chain: `time_kind=source` when a chain ts exists, otherwise `unknown`.
- `score`, channel ranks, `_apply_filters` and dedup were not changed.

### `services/thread_chain.py` (HC-B-F1)

- `ChainItem` additively gains `edited_at` and `reply_to_author_id` at the END (old positional constructions remain valid).
- `collect_thread_chain` fills them from the row it already reads via `get_smart_message_by_tg_id` (that SELECT already includes both; no new SQL/DDL).
- `format_chain_line` (raw Thread/Branch/factcheck) passes `reply_to="tg:<parent> [(uid N)]"` and `edited_at` to `format_context_item`; absent fields keep old bytes.
- `render_speech_line` does NOT print raw `tg:`/uid (existing speech contract): reply remains the existing `↳ Reply M…` relation, edit is an additive `(ред. … UTC)` clause after the text. Thus edit/reply metadata still reaches the speech payload without breaking the `| M…]` slot contract.

## 3. Deliberate deviations / scope boundaries

1. **8th tuple element is emitted at the Direct-RAG dict→tuple boundary** (`_rag_rows_with_ranks`), not by changing the legacy `get_rag_facts`/`_search_graph_facts` 7-tuple contract. Reason: `tests/test_graphrag_memory.py` (outside B write scope) pins the public 7-tuple shape; the Writer-facing Direct-RAG tuple now carries `time_origin` and `_format_origin_labeled_line` consumes it. `build_rag_context` remains structurally untouched.
2. **`valid_from/valid_to` stay 0 in this line.** `database.py` B scope is limited to the three `smart_messages` SELECTs; extending the `graph_facts` SELECTs would exceed the frozen slice scope. The DTO fields exist with honest defaults and are populated only if a caller's row already carries them.
3. **Episode event columns are row-aware only.** `services/mca_episodes.py`/the facade are outside B write scope and do not expose `event_start_ts/event_end_ts`; B never invents an event window and falls back to honest `recorded`/`unknown`.
4. **UTC legend lives in the Writer assembly** (`direct_chat_service`), not in `chat_clock.py` (out of scope). It is one phrase, idempotent, and does not rewrite `_fmt_ts`.
5. **`_ha_fmt_ts`/`_format_timestamp` already used UTC at A/2.58.225.** B adds discriminating guard tests and a mutation, not a duplicate “fix”.
6. **Thread-scope 8th/bytes caveat:** the Reviewer-directed addendum to `tests/test_history_segments.py` recomputes the second cross-cut reply at the now-legitimate 120|121 cut; the test keeps checking a reply connection *through* the cut and is green. `test_evol015_quote_pipeline::test_d_plain_reply_byte_parity` still compares raw Thread output against the pre-B oracle (no reply argument) and is therefore expected to fail after HC-B-F1; it is outside the authorized addendum scope and is recorded as `known-test-shape-evol015-byte-parity.txt`.
7. **Known pre-existing failure:** `tests/test_ur_c_clock.py::TestFallbackAdapterClock::test_generous_budget_keeps_block_intact_same_asof` fails identically on A tip `65866171` and on this candidate (fallback capacity marker under its tight synthetic budget). Artifacts: `red-base/preexisting-ur-c-clock-at-65866171.txt`, `red-base/preexisting-ur-c-clock-at-hc-b.txt`; not caused by B.

## 4. Requirement rows covered

Primary: `HC-TIME-SMART-CONTEXT`, `HC-TIME-HISTORY-TOOL`, `HC-TIME-RETRIEVAL`, `HC-TIME-EVIDENCE-WRITER`, `HC-TIME-FMT-PRECISION`, `HC-TIME-CANDIDATE-FIELDS`, `HC-TIME-CLOCK-TZ`, `HC-TIME-EVENT-VS-RECORDED`, `HC-TIME-MATRIX`, `HC-TIME-PAYLOAD-PROOF`, `HC-TIME-TAXONOMY`, `HC-TIME-RANGE-SEMANTICS`.
Supporting: `HC-ACC-TIME`, `HC-ACC-CHANNELS`.
A contracts preserved: no changes to the A window grammar/parser/route/header/coverage ledger; A focused set stays green except the explicitly noted exact-cut fixture assertion.

## 5. Payload proof (not DTO)

`evidence/time/payloads/capture_payloads.py` runs the real `DirectChatService._l2_write_answer` on an isolated in-memory SQLite fixture and stores the actual `messages` payload:

- `payloads/writer-payload.json` (anonymized: `A`/`B`, `message-0/1`, `fact-1`), `payloads/writer-payload.sha256` (`025a063c…`);
- observed: `reply_edge_in_user=true`, `edit_stamp_in_user=true`, `recorded_fact_label_in_user=true`, `utc_legend_count=1`, `clock_blocks=1`, `thread_block_in_user=true`, `branch_block_in_user=true`, `thread_has_reply/edit=true`, `branch_has_reply/edit=true`;
- the user content contains all channels at once: Global_Context line, `<Conversation_Thread>`, `<Conversation_Branch>`, `<RAG_Memory>` recorded fact, Tool_Evidence history line, plus one UTC legend after `</Chat_Time_Context>`. The Thread/Branch block carries both `ответ на tg:11 (uid 7)` and `ред. 01.01.2024 00:05 UTC`.

Production trace/real archive/effective release config are unavailable in this environment; this is an isolated fixture through the same payload builder, not production evidence.

## 6. Commands / results

- RED at A tip with B tests (source stashed): `22 failed, 29 passed` — `red-base/pytest-hc-b-at-65866171.txt`.
- HC-B-F1 RED on candidate `24f0f766`: `3 failed, 1 passed` — `red-base/hc-b-f1-red-at-24f0f766.txt`.
- New tests: `python -m pytest tests/test_p0_hc_temporal.py -q` → `35 passed`.
- History isolation: `21 passed`.
- Focused: `745 passed, 1 deselected` (666 core + 79 summary-memory; deselected only the pre-existing ur_c_clock failure) — `tests/focused.txt`, `tests/summary-memory.txt`.
- Thread/reply consumers (HC-B-F1): `367 passed, 1 deselected` (the deselected `test_evol015…byte_parity` is the pre-B oracle; expected fail artifact) — `tests/thread-chain.txt`.
- Mandatory 24-file set (same as A): `386 passed` — `tests/mandatory-386.txt`.
- TIME-03/NEXT-02/turn-clock 6-file set: `157 passed` — `tests/next02-time03.txt` (earlier 5-file run: 108; Reviewer's 110 used a different file set).
- Mutations (9): `mutations/*.txt` — original 6 plus f1-m1 (drop Thread reply), f1-m2 (drop Thread edited_at), f1-m3 (payload Thread content missing); each targeted test fails and passes again after restore.
