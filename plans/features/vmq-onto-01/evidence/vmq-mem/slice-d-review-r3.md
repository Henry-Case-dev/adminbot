# VMQ Slice D — independent re-review r3 (2026-11-15)

Reviewer: DeepSeek V4.1 Flash (`opencode-go/deepseek-v4.1-flash`), session `ses_e2221abb6ffeSaFVCOq0pGps8K`.
Candidate: `vmq/slice-d` HEAD `8fbd2ffb` (code `ef568e6f` + `456cf769`), previous `c4b2c1c2`, base `2b419aa2`, clean.
Scope: `git diff c4b2c1c2..8fbd2ffb` (authority, removal of guard/topic, N2, trace, tests). Verdict preserved unchanged.

## Verdict: Needs Fixes — not Approved, not VERIFIED, do not deploy.

| ID | Verdict | Evidence |
|---|---|---|
| D1 | PARTIAL | Full claimed paths closed: `«как дела с мулянкой?»`, `«что сейчас с Алиной?»` with subject, `«расскажи, что сейчас с мулянкой?»` -> `2026:10`, `replace_allowed=0`, `period_fill=0`, profile reads 0. Remaining: (1) real `«что нового у Алины?»` -> `2025:6, 2026:4` — 2025 rows come from **base-retrieval**, not period; (2) synthetic `auto_no_replace` (base 8) -> 8 current + 1 old, `period_fill=1`, profile read 1. |
| D2 | CLOSED (removed) | `topic_parity`, `topic_*`, guard, `is_current_state_query`, `_PERIOD_CURRENT_MARKERS`, `PERIOD_DROP_CURRENT_STATE` removed; no references in services/tests/web/UI. |
| D3/N2 | CLOSED | `target=max(1,reserve,free)`, two passes; 1 fact + 6 messages -> 7 facts, 3 old years, limit 10. |
| D4 | CLOSED | P1/P2/P3 in corpus evidence; P3 history 2023–2024. |
| D5 | MOSTLY CLOSED | `memory_period` fields, `memory_scope` in L1 card, allowlist enum-only; residual profile contribution not attributed in `auto_no_replace`. |
| D6 | PARTIAL | Hard 0.5 real; core 1.0 structural; T3-labeled test vacuous (`pool:1`, `delivered:0` literals, no retrieval call). |
| D7 | CLOSED | RED 16/6, passed list matches. |
| D8 | PARTIAL | D1 tests now use `_build_rag_block` with subject; no partial-profile test, no real base-2025 test; T3-labeled vacuous. |
| N1 | PARTIAL | Full paths closed; base-2025 and `auto_no_replace` profile-fill remain. |
| N2/N3/N4/N6 | CLOSED | Reserve floor; parity removed; trace authority; tests not weakened for two-stem positive. |
| N5 | PARTIAL | Tests real for full path, not for partial profile/base-2025. |

## New findings

- **N7 — HIGH (IN_SCOPE per reviewer):** real `«что нового у Алины?»` under `auto` -> `2025:6, 2026:4` from base-retrieval; expected `2026:10`.
- **N8 — MEDIUM (IN_SCOPE):** `auto_no_replace` with base 8 reads profile and adds 1 old row into free slots (`period_fill=1`); expected profile reads 0.
- **N9 — MEDIUM (EVIDENCE_GAP):** T3-labeled test is vacuous (literals, no retrieval).
- **N10 — HIGH (EVIDENCE_GAP):** L1 `memory_scope` not measured (`key_present=false`, `LLMTransportError`); honest gap, but MEM-04/TIME-01 cannot be confirmed.
- **N11 — MEDIUM/GAP:** TIME-02 reply path under `auto` is `2026:10`; multi-period only in tool biography; depends on unmeasured L1.

## Independent numbers

22 passed slice_d; 272 focused; 496 direct/tool/trace; RED 16/6; mutations: authority->True 7 failed, ->False 4 failed, `trimmed=rows` under historical 1 failed. Real copy: A1P auto `2026:10`, historical `2023:1,2024:1,2026:8`; A1 same; T2 plan_act multi-year; D 2023 `2023:1,2026:8`; profile current `2026:10`; `«что нового у Алины?»` `2025:6,2026:4`; partial base 8 + profile 2023 -> 8+1; N2 7 facts; L1 error.

## Limitations

No live L1/Writer/rerank; vector leg `compat_not_proven`; one chat/copy; no human relevance labels; full suite not run; visual layer untouched.

## Conclusion

TIME-06 confirmable; TIME-04 mostly; TIME-02 partially; MEM-04/TIME-01 not confirmable with unmeasured L1; TIME-07 not confirmed. No row may be marked VERIFIED.
