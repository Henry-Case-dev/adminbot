# P0 memory-relevance — lane B, review r2 corrections

Review artifact: `plans/features/vmq-onto-01/evidence/p0-memory-relevance-review-r2.md`
(sha256 `d9b40fa32a7217ab59a078e9077d04bb9c5e8fa614661746f516087e8e7a8b78`),
session `ses_dedb91aa3ffeXDm00hkcwnee3D`. Reviewed tip `351c298c7`; base
`e3467ccb7`. Same branch/worktree; F1 confirmed resolved and F2 partially
resolved by the reviewer's own measurements.

## 1. F3 (blocking) — originals-only block carried no `<RAG_Memory>`

**Cause.** `_build_rag_block` wrapped only the facts path
(`return f"<RAG_Memory>\n{content}\n</RAG_Memory>"`), while its early returns
with originals and zero facts returned a bare `<Memory_Originals>`.
`_apply_plan_memory_scope` locates the block to rebuild by
`str(block).startswith("<RAG_Memory>")` and returns the list unchanged
otherwise — so in exactly the zero-facts case the layer was added for, the
plan's author/period never reached `retrieve` and the author's speech never
reached the payload.

**Fix (both options the review allowed, smallest consistent pair).**
1. One wrapper helper: `_wrap_rag_block(body)` is used by **every** return of
   `_build_rag_block` (facts, dedup-empty, originals-only, final). Facts path
   output is byte-identical; originals-only now yields
   `<RAG_Memory>\n<Memory_Originals>…\n</RAG_Memory>`.
2. `_apply_plan_memory_scope` inserts the rebuilt block at `rag_ctx["index"]`
   when the pre-plan payload had **no** RAG block at all (no facts and no
   originals), instead of silently returning the list. Guard: insertion only
   when `rag_ctx["block"]` was empty, so an untagged-but-present block is never
   duplicated; the tagged-block replacement path is unchanged.
3. Period-pool reuse is keyed by `(chat, query, author)`. The pre-plan pool is
   built without an author (author is unknown before L1); reusing it inside the
   plan rescope would keep the author out of retrieval — the pool is therefore
   re-read once when the author changes.

## 2. Real-archive zero-facts check (own run)

Read-only `local_database_2026-09-04_history.db`, chat `-1002661910336`,
author `147734047`, query «поздравления 2025», `FakeMemory` with no facts
(pre-plan block built by the real `_build_rag_block`):

    PRE-plan block: '<RAG_Memory>\n<Memory_Originals>\n[31.12.2025 19:01 UTC | 5929079345 …' 
                    prefix wrapper = True, len = 4503   (other participants' material)
    rescope:        retrieve calls = 2 | author axes = [(), (147734047,)] | period_fill = [False, True]
    payload:        blocks = 1 | starts <RAG_Memory> = True | <Memory_Originals> = True
                    | merged length = 1171   (the author's own speech replaced the 4503-char block)

Before the fix the same scenario produced 0 retrieve calls and an unchanged
payload (reviewer probe A / their `P_R2_2`).

## 3. Tests (RED → GREEN)

New `tests/test_p0_memory_relevance_r2.py` (4 tests, real SQLite, real
`_build_rag_block` pre-plan block — no synthetic placeholder):

| Test | previous tip `351c298c7` | this tip |
|---|---|---|
| `TestOriginalsOnlyBlockIsARagBlock::test_zero_facts_originals_carry_the_wrapper` | RED | GREEN |
| `TestPlanAuthorReachesRetrieveAtZeroFacts::test_real_preplan_block_is_replaced_by_author_speech` | RED | GREEN |
| `…::test_absent_block_is_inserted_at_its_slot` | RED | GREEN |
| `…::test_recipient_plan_does_not_read_author` | RED (no retrieve call at all) | GREEN (retrieve called, no author axis) |

Numbers: previous tip **4 failed**; this tip **4 passed**. Together with the
earlier suites: `test_p0_memory_relevance.py` 11 passed,
`test_p0_memory_relevance_r1.py` 10 passed (25 passed across the three files).
The r1 test `test_rescope_passes_author_and_period_to_retrieve` no longer hands
the rescope a hand-written `<RAG_Memory>` placeholder: it now builds the
pre-plan block with the real `_build_rag_block` (the coverage gap the review
named).

Regression runs on this tip:
- `test_tool_router`, `test_mca15_chat_statistics_round1028`,
  `test_memory_unified_retrieval`, `…_06` — 210 passed.
- `test_vmq_mem_*` — 1 failed / 160 passed; the failure
  (`test_vmq_mem_slice_b::…never_adds_current_year`) fails identically on base.
- direct group + `test_ur_c_3_real_fts` + `test_ur_context_selection` +
  `test_history_isolation` — 7 failed / 106 passed; the same 7 pre-existing.
- `test_memory_quality_contract_07` (2), `test_speech_p0_a2_memory` (1),
  `test_memory_identity`, `test_ur_13_memory_types_scale`, `test_mem_time_policy`,
  `test_memory_period_vector_leg` — 3 failed / 127 passed, all three
  pre-existing.
- `py_compile` OK; `git diff --check` clean.

## 4. O1 — bounded partial-range sampling (stated, not fixed here)

For a **partial** `time_from/time_to` range (not a calendar year) the author
read uses the existing per-year query: it takes the newest `limit//5` rows of
each covering year and only then filters to the exact range. A range whose
author activity is older than those newest rows of the year can therefore yield
nothing, even though the author wrote inside the range. Explicit-year periods
(the owner-visible scenario and the only period the deterministic resolver
produces) are not affected: the year read is the requested period itself.
Closing O1 would need a range-aware author index read; that is not added here —
the limitation is stated instead of implied by "newest in year".

## 5. Other r2 non-blocking items

- O2 (live leg `dataclasses.replace` on a non-dataclass twin) unchanged; no
  production twin exists. The broad `except` around the live leg remains the
  existing fail-open.
- O3 (with `period_fill=True` the live leg enters the existing period vector
  leg) unchanged; contract-aligned, no live-shape test added.
- N2/N6/N8 unchanged (diagnostic `reason_code`; no Writer leg in the replay;
  facts/vector legs unusable on the local archive).
