# P0-HC C2 — integration of the safe Telegram egress into ordinary Direct

- Feature: `p0-history-coverage-temporal-egress`, slice `HC-EGRESS` (C2).
- Contract: `plans/features/p0-history-coverage-temporal-egress/arch-contract-2026-11-21.md`
  §4.2 (call-site order), §4.3 (payload proof), §5.2 (C2 write scope).
- Branch: `p0/hc-c2`; base B tip `d8c8db4b5`; C1 commit `743286354`; product
  release line `1fe684d36` (2.58.225 line). Candidate commit: see the branch
  tip recorded in `c2-tests.json` (the commit containing this file).
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\p0-history-coverage-temporal-e-cbf9b3fab6a8-683cfa06`.
- Status: implementation + self-checks complete; **REVIEW**, not VERIFIED, not
  deployed. No version bump, no deploy, no map/`progress_scope`/`workflow_state`
  edits.

## Product change

`services/direct_chat_service.py` (+31 lines, one import + one branch):

1. `from services import telegram_markup as _tm` (module import only).
2. Inside `_send_direct_answer`, in the ordinary-Direct branch only
   (`not (lore or deep_research)`), after the single existing
   `_verify_style_payload(text, ..., stage="direct_plain")`:
   - the decision source is `_tm.sanitize_outgoing(text)`; C1 documents that it
     applies `sanitize_outgoing` before parsing/rendering, so the decision and
     the trace digest describe the same payload the recipient can see;
   - `plain` → the pre-existing `_send_traced` → `send_chunked_reply` call is
     reached unchanged (no extra kwargs without `correlation_id`; byte-parity);
   - `telegram_html` → `_tm.render_telegram_html` for the `html_escape` trace
     op, the real egress guard result for `egress_sanitize`, then
     `_tm.send_structured(bot, chat_id, text, reply_to, document=doc)`.
     `note_delivery(channel="html")` records the returned first id, then the
     method returns that id immediately — no second send path is entered.

Untouched: rich branch and Rich-fail fallthrough, lore/deep_research safe-HTML
and their plain fallbacks, `send_chunked_reply` defaults, global `parse_mode`,
`/summary`, generation/prompts. `document.plain_text()` is the delivery source
(`text = doc.plain_text()` already existed); `remember_bot_reply` and
`_ledger.record_delivered_output` keep receiving the original `answer` and the
first `message_id`, exactly as before.

`services/telegram_markup.py` is unchanged in this slice (C1 commit).

## What the call-site actually verifies (new suite, 30 tests)

`tests/test_p0_hc_egress_c2.py` asserts recorded Bot API payloads, not DTOs:

- casual/literal/escaped text → no `parse_mode`, exact source bytes, reply
  target preserved (existing `send_chunked_reply` path);
- structural Markdown (bold, list, quote, heading, fence, code, link) →
  one `parse_mode="HTML"` call, no raw `**`/`` ` ``, no `entities` kwarg;
- HTML specials escaped, link rendered as `<a href>` with escaped `&`;
- egress-guard markers (`<thought>`) never reach the payload and the trace
  `delivered_digest` equals the actual payload digest;
- exactly one `html_escape`, one `egress_sanitize`, one `telegram_chunk` op;
  no `plain_render` op for the HTML turn;
- long answer → tag-safe UTF-16 chunks, reply only on the first;
- partial `TelegramBadRequest` on chunk *k* → plain only that chunk
  (`html_to_plain`), prior chunks not re-sent, no LLM, stop on repeated
  failure, first delivered id returned;
- `TelegramRetryAfter` → one retry of the same chunk;
- `document` source wins over positional text, `plain_text()` stays the
  source, returned id is the downstream identifier, egress writes no ledger;
- rich success never reaches the structured path; Rich fail then structured
  on the same answer; lore/deep_research outputs and long-lore plain fallback
  unchanged; `/summary` has no dependency on the new module.

## Checks (actual, from the C2 worktree)

Interpreter `C:\Code\Python\adminbot\.venv\Scripts\python.exe`
(Python 3.12.0, pytest 9.1.1), commands run from the worktree root.

| Check | Result | Evidence |
|---|---|---|
| RED at B tip `d8c8db4b5` (module absent) | collection `ImportError` | `c2-red-at-b-tip.txt` |
| RED at C1 head `743286354` (no call-site) | **17 failed, 13 passed** — exactly the HTML-channel expectations | `c2-red-at-c1-head.txt` |
| New C2 suite, final tree | **30 passed** | `c2-tests-c2-final.txt` (`c2-tests-c2-suite.txt` = same suite earlier) |
| C1 suite `tests/test_p0_hc_telegram_egress.py` | **78 passed** | `c2-tests-c1-suite.txt`, `c2-tests-c1-final.txt` |
| Mandatory 24-file regression (same set as 2.58.210/2.58.225) | **386 passed** | `c2-mandatory-386.txt` |
| A: `test_p0_hc_coverage.py` | **62 passed** | `c2-focus-coverage.txt` |
| A: `test_history_pages.py` + `test_history_segments.py` | **64 passed** | `c2-focus-history-pages-segments.txt` |
| B: `test_p0_hc_temporal.py` | **35 passed** | `c2-focus-temporal.txt` |
| B: `test_history_isolation.py` | **21 passed** | `c2-focus-history-isolation.txt` |
| Delivery router: `test_mca23_planned_vs_actual.py` | **24 passed** | `c2-focus-mca23.txt` |
| Edited oracles: `test_evol015_quote_pipeline.py`, `test_lore_compiler_round1020.py`, `test_soul1_style_payload.py` | **61 passed** | `c2-focus-edited-oracles-a.txt` |
| Edited oracle: `test_rlr_dcs_postprocess.py` | **17 passed** | `c2-focus-edited-rlr.txt` |
| Edited oracle: `TestDeepResearchDelivery` | **3 passed** | `c2-focus-verbilizer-edited-class.txt` |
| `test_direct_chat.py` (not in mandatory set) | **156 passed, 5 failed** — same 5 fail at C1 head without C2 | `c2-focus-direct-chat-summary.txt`, `c2-preexisting-thread-oracle-at-c1-head-summary.txt` |
| `test_verbilizer_response_modes_round1023.py` (whole file) | **88 passed, 1 failed, 2 errors** — same at C1 head | `c2-focus-edited-oracles-b-summary.txt`, `c2-preexisting-verbilizer-at-c1-head-summary.txt`, `c2-preexisting-verbilizer-single-at-c1-head.txt` |
| Mutations (7, explicit patches) | **7/7 KILLED** | `c2-mutations-verify.txt` |
| Bot API payload proof | captured | `c2-payload-proof.txt` |

Command lines (exact):

```text
python -m pytest tests/test_p0_hc_egress_c2.py -q
python -m pytest tests/test_p0_hc_telegram_egress.py -q
python -m pytest tests/test_round1025_f8_registry.py tests/test_mca23_planned_vs_actual.py tests/test_mod_acl_ux_01_m4_catalog.py tests/test_mod_acl_ux_01_m3_module_routes.py tests/test_mod_acl_ux_01_m4_module_params.py tests/test_asap7_module_registry.py tests/test_asap7_module_completeness.py tests/test_asap8_f5_module_truth.py tests/test_asap8_v63_b06_summary_scope.py tests/test_asap8_v63_b07_temporal_factcheck.py tests/test_asap8_v6_p1_d11_registry.py tests/test_asap8_v6_wa1_config_cache.py tests/test_factcheck_post_release_w2.py tests/test_mca18_self_model_block_a_round1042.py tests/test_mod_acl_ux_m2_capability_state.py tests/test_mod_acl_ux_m2_consumers.py tests/test_mod_acl_ux_m2_resolver.py tests/test_mod_acl_ux_m2_runtime_edges.py tests/test_mod_acl_ux_01_m21_adapters.py tests/test_mod_acl_ux_01_m21_gates.py tests/test_mod_acl_ux_m2_tristate_write.py tests/test_mod_acl_ux_m2_inflight.py tests/test_mod_acl_ux_01_m1_acl_false_403.py tests/test_webapp_js_unit.py -q
```

The focused runs were split per file/group only to fit the unstable local
runner; each command is the ordinary `python -m pytest <files> -q`.

## Payload proof (fake Bot API)

`c2-payload-proof.txt` (JSON) shows the recorded calls:

- casual: `parse_mode=null`, text byte-identical, `reply_to_message_id=42`;
- structured: one `parse_mode="HTML"` call, `<b>Итог</b>` and `•` list items;
- long: 2 chunks, both HTML, reply only on the first, `returned_id=1001`;
- partial fallback: HTML chunk 1 rejected (no id), plain fallback of **only**
  that chunk, `returned_id=1001` (first delivered);
- document: accessed `document.plain_text()` (`**из документа**`), positional
  text ignored, HTML payload, id returned.

## Test-oracle edits (5 files) — deliberate, not weakened

1. `tests/test_evol015_quote_pipeline.py` — **stale pre-B oracle**. B
   (HC-B-F1) added the additive `ответ на …` segment to the canonical line.
   The edit asserts the fixture's real reply edge (`tg:500`, uid 2), absence
   of `edited_at`, and builds the expected line with `reply_to="tg:500 (uid 2)"`;
   the byte-parity assertion itself is kept.
2. `tests/test_lore_compiler_round1020.py::test_normal_answer_stays_plain` —
   the test targets the plain path; `**...**` now legitimately goes through
   the HTML channel, so its input became markup-free ("обычный ответ"). The
   plain-channel and byte assertions remain exact.
3. `tests/test_rlr_dcs_postprocess.py` —
   `test_table_and_list_delivered_without_new_generation` is now parametric on
   the expected channel: table (not in the C1 subset) stays plain byte-parity;
   list is `HTML` with the exact `•` payload. The previous conditional (accept
   either channel) was tightened, not loosened. The owner-rules test asserts
   `parse_mode="HTML"` and `<code>print(1)</code>` (not merely a substring),
   while URL/content preservation stays.
4. `tests/test_soul1_style_payload.py` — protected fragment `` `report.txt` ``
   became `report.txt`: the code span is delivered as `<code>report.txt</code>`,
   so the content-preservation assertion uses the content; the remaining
   protected fragments (URLs, versions, path, call) are unchanged.
5. `tests/test_verbilizer_response_modes_round1023.py::test_casual_stays_plain` —
   same rationale as (2): markup input moved out of the plain-channel test.

No assertion was deleted or relaxed to make C2 pass; all five are channel/oracle
updates forced by the contract (`HC-EGRESS-CHANNEL-CHOICE`) or by B's additive
reply segment (1).

## Mutations

`c2-mutations-verify.txt` re-creates one explicit patch per named property of
`c2-mutations.txt` (the previous helper was not preserved):

| ID | Mutation | Result |
|---|---|---|
| M1 | no HTML channel in ordinary Direct | 17 failed → KILLED |
| M2 | failed chunk re-sends already delivered chunks | 2 failed → KILLED |
| M3 | plain delivery gains `parse_mode="HTML"` | 8 failed → KILLED |
| M4 | `/summary` imports the egress module | 1 failed → KILLED |
| M5 | reply target on every chunk | 1 failed → KILLED |
| M6 | successful delivery returns no id | 10 failed → KILLED |
| M7 | trace records raw Markdown instead of delivered HTML | 2 failed → KILLED |

The historical `c2-mutations.txt` reports the same kill set with M7=1 failure
(a slightly different trace mutation); the property is the same and is
re-verified here. Every patch was restored byte-for-byte (`sha256` checked).

## Pre-existing failures on the C2 base (not candidate regressions)

Verified in a temporary detached worktree at C1 head `743286354` (without the
C2 diff), then removed:

- `tests/test_direct_chat.py`: 5 thread/branch oracle tests fail because B's
  additive reply segment is not in their expected line
  (`c2-preexisting-thread-oracle-at-c1-head-summary.txt`). Same class as oracle
  edit (1), but outside the C2 write scope; **backlog for the B line**, not
  fixed here.
- `tests/test_verbilizer_response_modes_round1023.py`:
  `test_summary_kill_switch_off_prev_narrator` fails identically at C1 head
  (`c2-preexisting-verbilizer-single-at-c1-head.txt`), and
  `test_no_bullet_ban_in_deep_research` parameters error with
  `ValueError: the environment variable is longer than 32767 characters`
  (Windows environment limit) at C1 head too
  (`c2-preexisting-verbilizer-at-c1-head-summary.txt`). The oversized raw logs
  were compacted to the failure/summary lines only.

## Limitations

- Payload evidence is a **fake Bot API** capture of `bot.send_message` calls:
  real Telegram HTML entity acceptance, entity boundaries and client rendering
  were not observed; no live chat, no production host, no network sends.
- HTML rejection/fallback is simulated by injected `TelegramBadRequest`; a real
  Telegram rejection message text may differ.
- The decision uses `sanitize_outgoing(text)` before `decide_markup` (arch
  §4.2 names `decide_markup(text)`): this is the C1-documented guard order, so
  the trace digest matches the payload the recipient sees; for markup-only
  transformations it is equivalent.
- C2 does not change generation, prompts, personality, `parse_mode` defaults,
  `send_chunked_reply`, `/summary`, rich or lore/deep_research paths.
- The `channel` value in the optional humor-feedback metadata remains the
  pre-existing two-value `rich|plain` vocabulary for this new HTML path; this
  is a non-blocking cosmetic observation (backlog), not part of the C2
  acceptance contract.

## Configuration and cleanup

- No new flags, no factory-canon/prompt changes, no DDL/migrations, no version
  bump, no deploy. Chunk limit is the existing `_CHUNK_LIMIT=4096`.
- The C2 worktree remains for review; the two temporary baseline worktrees and
  their tool-managed intelligence scratch were removed after evidence capture
  (`unit-close` reports `cleanup_complete=true`).
