# VMQ Slice D — final predeploy approval (2026-11-15)

Reviewer: DeepSeek V4.1 Flash (`opencode-go/deepseek-v4.1-flash`), session `ses_e2221abb6ffeSaFVCOq0pGps8K`.
This artifact preserves the Reviewer's final verdict unchanged; the Reviewer does not edit files.

## Candidate

- Product code: `456cf769` (Slice D `ef568e6f` + predicate alignment), branch `vmq/slice-d`.
- Evidence tip: `69b5c9f9` (N9 test-only fix; `git diff 8fbd2ffb..69b5c9f9 -- services/` empty).
- Base / production / rollback: `2b419aa2` (2.58.204).
- DDL 0, schema 47, no new flags/hot_config/composer, owner prompts untouched.

## Verdict

**Approved (predeploy)** for product code `456cf769` / evidence tip `69b5c9f9`.

Confirmed: `period_replace_allowed` authority (`memory_scope` + `PeriodIntent.source`; `query_marker` cannot replace); D1 full paths under `auto` keep current rows (`2026:10`, `replace_allowed=0`, `period_fill=0`, profile reads 0 on a full slice); A1P/A1/T2 under `historical`/`historical_recall`; explicit year; N2 reserve-as-floor; trace/allowlist; invariants (one `retrieve()`/bundle, DDL 0, no new pipeline, owner prompts untouched); TIME-04 mostly; TIME-06.

N9 confirmed closed: the T3-labeled test now calls real `retrieve`/`_rag_unified_rows` on a non-empty pool (5 rows), asserts `delivered=0`, preserves current ids, `replace_allowed=0`, `period_skipped=auto_full_slice`; mutation `period_replace_allowed->True` yields `delivered=1` and fails the test.

Arbitration: N8 (partial base + one old row in a free slot) is the additive behaviour allowed by ARCH_DECISION — only the `period_fill` flag naming is backlog; N7 (`«что нового у Алины?»` -> 2025:6, 2026:4) is pre-existing base-retrieval ranking, not a Slice D regression; N10/N11 are honest L1-dependent gaps.

## Not confirmed (must not be marked VERIFIED)

- **VMQ-MEM-04, VMQ-TIME-01** — L1 `memory_scope` is UNKNOWN (`key_present=false`, `LLMTransportError`); after deployment `memory_scope` is recorded in `turn_trace`, so this is a postdeploy observation.
- **VMQ-TIME-02 reply path** — multi-period only in tool biography; reply under `auto` is 2026:10; depends on L1.
- **VMQ-TIME-07** — synthetic labeled set, hard 0.5, not an independent human reference (N9 closed).

## Conditions / limits

No live L1/Writer/rerank/Global_Context; vector leg `compat_not_proven`; one chat and one DB copy (2,043,181 messages); full 20k suite not run; visual layer untouched. The A1P parity under `auto` is explicitly not claimed; it is claimed only under L1 `historical`/`historical_recall` or an explicit year (ARCH_DECISION, owner formulation).

Deployment requires the assembled release train, independent delta review of the exact release tip, and a rollback to `2b419aa2`.
