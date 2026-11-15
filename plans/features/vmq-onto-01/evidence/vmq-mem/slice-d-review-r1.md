# VMQ Slice D — independent review r1 (2026-11-15)

Reviewer: DeepSeek V4.1 Flash (`opencode-go/deepseek-v4.1-flash`), session `ses_e2221abb6ffeSaFVCOq0pGps8K`.
Candidate: `vmq/slice-d` HEAD `dbaf1a6d` (code `693b70e1`, evidence `bfd87014`, harness `dbaf1a6d`), base `2b419aa2`, clean.
Verified on a read-only prod-DB copy (2,043,181 chat messages, schema 47). Verdict preserved unchanged.

## Verdict: Needs Fixes — not Approved, not VERIFIED, do not deploy

| Area | Verdict |
|---|---|
| VMQ-MEM-04 | Needs Fixes — A1P parity measured, but `topic_parity` is over-generalized (D2) and leaks into current state (D1) |
| VMQ-TIME-01 | Needs Fixes — A1P/T2 multi-year confirmed; T3 control did not exercise the mechanism; protection only via L1 `operative` |
| VMQ-TIME-02 | Needs Fixes — P1 absence/multi-period confirmed; P2 tool profile stays single-year (D3); only 2 participants measured (D4) |
| VMQ-TIME-04 | Needs Fixes — fail-closed window, `status_not_usable`, explicit 2023 and `<Old_Episode>` confirmed; machine-readable stage trace not emitted (D5) |
| VMQ-TIME-06 | CONFIRMED with limitation — inventory/invariants agree; semantic leg unavailable (`compat_not_proven`), honestly recorded |
| VMQ-TIME-07 | Needs Fixes / GAP — class matrix taken, labeled set not independent, precision 1.0 trivial, T3 not measured (D6) |

## Defects

- **D1 — BLOCKER, IN_SCOPE (MEM-04/TIME-01/06/07):** under `memory_scope=auto`, old rows displace current rows in current-state questions. Reproduced on the real `_rag_unified_rows`: `"как сейчас дела с мулянкой?" -> 2022:1, 2024:1, 2026:8`; `"что сейчас с Алиной?" -> 2022:1, 2023:1, 2026:8`; synthetic full path drops current ids 8008/8009. Expected: current-state answers keep current rows; need a structural guard and a T3 test that really passes through `topic_parity`. The measured T3 looked clean only because period fill never ran (`usable=3 < limit//2`, `period_stats={}`, subject token `E1` shorter than 4 chars).
- **D2 — HIGH/MEDIUM, IN_SCOPE (MEM-04):** `topic_parity` does not require a shared stem between the two old rows. Reproduced: 2023 `"шизы обсуждали"` (stem `шизы`) + 2024 `"на конфе шумели"` (stem `конф`) -> both accepted, `topic_quota=2`. Code counts `soft_pool` by `shared>=1` with the query but not between rows (`mca_retrieval_context.py:890-903`). Measured A1P selected 2859/3324 (both about the conference, not about "шизы").
- **D3 — MEDIUM, IN_SCOPE (TIME-02):** tool biography for the top author stays single-year: `_get_user_context(person, purpose=biography)` returns 10/10 facts from 2026; `get_author_message_periods` has 2024/2025 but is called only when `not covered_old and len(facts) < max_items` (`tool_router.py:4704-4715`, max_items 10).
- **D4 — MEDIUM, EVIDENCE_GAP (TIME-02):** measured on 2 participants instead of the required ≥3 (including top author and participants with confirmed 2023-2024 history).
- **D5 — MEDIUM, IN_SCOPE/EVIDENCE_GAP (TIME-04):** new stage fields (`pool_status/dropped_status/pool_expired/dropped_budget/age_policy`) stay in `_rag_period_stats`; the product log/turn trace emits only `rejected_subject/period_kept/vector_*` (`direct_chat_service.py:14791-14803`). No per-block year composition or per-stage rejection trace.
- **D6 — MEDIUM, EVIDENCE_GAP (TIME-07):** all 8 cases use the same distractor `"погода и дорога"` with zero shared stems, so distractors can never be selected; precision is computed over the same `topic_stems` used for selection. 1.0 is structural, not independent.
- **D7 — LOW, EVIDENCE_GAP:** `slice-d-tests-2026-11-15.json:29` lists a non-existent test `TestPlainQuestionParity::test_one_stem_row_is_still_rejected`; the real fifth passed test is `test_reason_codes_stay_consistent` (count 13/5 correct, list wrong).
- **D8 — MEDIUM, EVIDENCE_GAP:** negative tests do not discriminate the main risk: `test_current_state_pool_is_untouched` uses one old row; `test_two_old_years_without_shared_stem_do_not_trigger` uses rows with 0 shared stems with the query; `test_operative_policy_is_not_weakened` is vacuous on an empty `accepted`; `test_year_loss_categories` checks `dropped_budget` only as `int >= 0`.

## Independently confirmed

- Candidate tests: 18 passed; focused 163 passed; related Direct Chat/ToolRouter 416 passed; history/episode/MCA07 94 passed.
- RED on base `2b419aa2`: 13 failed / 5 passed reproduced (passed list differs from evidence — D7).
- Mutations reproduced: `len(topic_years)>=2 -> >=1`; window check disabled; `if bound -> if False` — each killed its target test.
- Real copy: A1 `2023:1, 2024:1, 2026:8`; A1P same with `topic_quota=2`; D 2023 `2023:1, 2026:8` explicit-year; T2 `2023:1, 2024:1, 2026:8`; T3 `2026:10` with `period_stats={}` (mechanism not exercised); `<Old_Episode>` 2023 two spans/18 messages; P1 subject facts 23 unconfirmed/2026, 0 confirmed; P1 messages 2023/2024/2025; P2 subject profile 10/10 2026, messages 2024/2025.
- Vector leg: 21,771 rowids; 21,152 facts with vector; dims 3072; `gemini-embedding-001`; `compat_not_proven`; KNN not called; `provider_unavailable` is a separate embed failure.
- Invariants: one `retrieve()` contract, one bundle per turn, DDL 0, `database.py` SELECT-only, no new flags/hot_config/composer/LLM/embedding pipeline, prompts/settings untouched.

## Limitations

No live process (L1 emission, Writer, Global_Context, hot cache, rerank, answer generation); vector leg `compat_not_proven`; one chat, one query per class; full 20k suite not run; 3 of 6 mutations reproduced; TIME-07 synthetic only; no UI/visual changes.

## Conclusion

No row can be marked VERIFIED. Factual TIME-06 inventory and the fail-closed/Old_Episode part of TIME-04 are confirmed; TIME-01/02 only partially (P1, reply path); MEM-04 and TIME-07 are not confirmed. Required fixes: current-state guard and a "pool without shared stem" negative test (MEM-04), multi-year tool profile (TIME-02), product trace of stage fields (TIME-04), competing-distractor labeled set (TIME-07), corrected evidence list and strengthened negatives.
