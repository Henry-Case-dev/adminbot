# UR-C-2 seam trace — direct L2 ContextSelection wiring — 2026-11-24

**Task:** `unified-reply` UR-C-2, rows `UR-09.1`, `UR-09.2`, `UR-09.6`, `UR-09.7`, `UR-11.6`, `UR-BAN-04`.
**Base:** `50981ca88` (UR-C-1 evidence HEAD; code `b381a13de`).
**Branch:** `fix/ur-c-2-context-selection`.
**Product code:** none changed in this increment.
**Result:** stopped before a material seam/architecture decision; no new gate, no allocator rewrite, no UI.

## 1. Rows and actual blocker

All six rows share the same blocker: `ContextSelection` is assembled/used only for the **initiative L2 fresh window**, not for the **direct L2 block path**.

| Row | Acceptance focus | Actual state at base |
|---|---|---|
| `UR-09.1` | fast window tail is not the information ceiling; old branch via retrieval/source refs | `get_window_messages` feeds the old block builders; `mca_retrieval_context` is called inside `_build_rag_block`/episode builders, not through `ContextSelection` |
| `UR-09.2` | fixed P0→… priority order with provenance per fragment | `ContextSelection`/`build_context_selection` exist, but direct L2 never builds one; its order is the old block `CANONICAL_ORDER` of `ContextPiece` |
| `UR-09.6` | exact/lexical/reply memory first, then vector/episodes, dedup by source ID and meaning | `collect_memory_fragments` exists but has **no live caller**; direct L2 uses `_build_rag_block` text |
| `UR-09.7` | running summary/wide background as low-trust topic map, not replacing sources | direct L2 uses `global_head/middle/tail` block text; no `SummaryMapRef`/selection authority in live path |
| `UR-11.6` | P0 request/addressee/reply/tools/facts/corrections; old summaries/anchors not P0 | P0 is encoded in old block priority (`BLOCK_PRIORITY`), not in a live `ContextSelection` provenance |
| `UR-BAN-04` | old summary/bot answers/graph links are not equal facts; bot words remain communication | old `RAG_Memory`/`Global_Context` text blocks carry no per-fragment authority; bot statements are not a live `self_outputs` selection |

Rows remain **PARTIAL**; no VERIFIED.

## 2. Actual live trace

### 2.1 Direct L2

`DirectChatService._build_user_content` (`services/direct_chat_service.py:11104`) collects blocks and calls `_compose_user_content` (`:12126`).

Inside `_compose_user_content`:

- candidates are block pairs (`kind`, `text`) at `:12173`;
- `global_head/middle/tail`, `thread`, `episode`, `rag`, `target`, relations, protected, lore, current are candidate blocks;
- allocation is **old** `_composer.allocate_budget` at `:12336` (primary) and `:12461` (fallback);
- materialization is `_finalize_allocation` at `:12367`, which emits `<Global_Context>` and canonical block text.

There is **no** `build_context_selection`/`allocate_selection` in the direct path.

### 2.2 Initiative L2 (only live selection)

`generate_initiative_reply` does:

- `collect_window_fragments` at `:17779` (actual base line);
- `build_context_selection` at `:17787`;
- filters window rows by selected `source_id` and renders them at `:17806` (approx).

It uses selection only for the **fresh window**; memory/self-output/summary are not selected there either.

### 2.3 Composer API

- `ContextSelection` — `services/direct_context_composer.py:1017`
- `allocate_selection` — `:1585`
- `build_context_selection` — `:1829` (calls `allocate_selection` at `:1924`)
- `collect_memory_fragments` — `:1964`
- `collect_self_output_fragments` — `:2059`

Static call-site probe on the base:
`build_context_selection` only `direct_chat_service.py:17787`;
`allocate_selection` only internal `direct_context_composer.py:1924`;
direct path has only `allocate_budget` at `:12336/12461`;
`collect_memory_fragments` and `collect_self_output_fragments` have no live caller.

## 3. Why a minimal wire is not safe

To wire direct L2 to the **same** selection result, four contracts must be chosen, not guessed:

1. **Fragment producers:** which existing source becomes `thread`/`fresh_neighbours`/`memory`/`self_outputs`/`summary_map`/`background`:
   - window rows (easy),
   - reply `chain` items,
   - RAG facts/episodes (`_build_rag_block` currently returns formatted text),
   - durable bot outputs (`collect_self_output_fragments`; no live caller),
   - summary/global middle rows.
2. **Materializer:** `ContextSelection` has no L2 block renderer. Direct `_finalize_allocation` emits block text from old `ContextPiece`; it cannot emit `<Global_Context>/<RAG_Memory>/<Conversation_Thread>/<Old_Episode>` from selected fragments. The composer docstring says materialize belongs to `DirectChatService._compose_user_content`, but no such materializer exists.
3. **P0/authority mapping:** direct P0 is block-kind priority (`BLOCK_PRIORITY`); `ContextSelection` P0/authority is fragment role/authority. Mapping current/reply/target/relations/protected/lore/facts to fragment roles changes UI provenance and block order.
4. **Fallback:** if selection raises or is over budget, does direct L2 keep the old block path, or use a reduced selection? This is user-visible and must be explicit.

Doing this as a “small” edit would create a second selection/allocator path or silently drop block content. Both are forbidden by the task.

## 4. Options (for Architect/PM decision)

| Option | Scope | Consequence |
|---|---|---|
| A1. Window-only selection parity | use `collect_window_fragments`/`build_context_selection` for direct L2 window only, keep old block allocation for other blocks | low risk; does **not** satisfy UR-09.6/09.7/11.6/BAN-04 fully; rows remain partial |
| A2. Full fragment materializer | build selection from window/chain/RAG/ledger/summary, add L2 materializer to `_compose_user_content`, replace old block allocation | architecture-sized; required for all six rows; must preserve canonical block tags/order and P0 |
| A3. Hybrid | selection for window/memory, old allocation for remaining blocks | explicitly a second allocator/selection; forbidden by the task |

Recommended next step: Architect/PM chooses A1 (bounded, but partial) or A2 (full, but a dedicated seam). No code is written until then; no new gate, no threshold.

## 5. Verification

- `tests/test_ur_context_selection.py` + `test_ur_bot_output_history.py` + affected context suite (including UR-C-1) — **311 passed** at base `50981ca88`.
- No product/test/config diff; `git diff --check` clean.
- No `py_compile` product change (none).
- No map/status/`progress_scope.json`/`workflow_state.md`; no deploy/SSH/LLM.

## 6. RFL / readiness

- **Blocker `URC2-SEAM-01`:** no materializer from `ContextSelection` to direct L2 blocks and no live producers for memory/self-output/summary. This is an architecture/contract decision; do not implement by duplicating allocator.
- Production trace/effective config not read; no owner QA.
- All six rows remain PARTIAL; no VERIFIED.
- Readiness: evidence-only; ready for Architect/PM seam decision, not code review.
