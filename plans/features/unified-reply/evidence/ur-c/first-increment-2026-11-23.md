# UR-C first increment — ContextSelection live-wiring trace/design — 2026-11-23

**Task:** `unified-reply` UR-C, depends UR-B; bounded first increment only.
**Base:** `33d6b0974` (UR-B evidence HEAD; code `462cf1b22`).
**Branch:** `fix/ur-c-context-selection`.
**Product code:** none changed in this increment.
**Increment:** trace/design of the live `ContextSelection` seam. Stopped before a material architecture change; no new gate/threshold.
**Rows:** 44 PENDING `UR-C`; no VERIFIED. UR-A/UR-B remain PARTIAL.

## 1. Exact 44 PENDING rows, grouped by dependency

Source: `plans/features/unified-reply/requirements-map.json` (slice `UR-C`, items + additional requirements), state at master `8be55c487`.

| Group | Rows | Actual blocker |
|---|---|---|
| A. Live `ContextSelection` wiring | `UR-09.1`, `UR-09.2`, `UR-09.6`, `UR-09.7`, `UR-11.6`, `UR-12.4`, `UR-23.6`, `UR-23.8`, `UR-BAN-04` | selection is built only in the initiative L2 path; direct L2 and both L1 paths do not use it |
| B. L1 pre-truncation / selected fragments | `UR-RES-03`, `UR-09.9`, `UR-10`, `UR-10.0`, `UR-10.2`, `UR-10.5` | `direct_l1.build_l1_context` still uses `L1_WINDOW_MESSAGES=20` / `L1_WINDOW_LINE_CHARS=200`; direct L1 feeds raw window rows |
| C. Single allocator / capacity / legacy caps | `UR-11`, `UR-11.1`, `UR-11.4`, `UR-11.7`, `UR-11.8` | direct path uses the old `ContextPiece` + `allocate_budget` path; `allocate_selection` has no live caller outside `build_context_selection` |
| D. Memory types / retrieval / pagination | `UR-13`, `UR-13.1`, `UR-13.4`, `UR-13.6`, `UR-13.8`, `UR-BAN-03` | tests exist for selection pieces, but type separation, identity-prior and physical pagination are not proven on the live path |
| E. Summary / legacy summary params | `UR-12.1`, `UR-12.2`, `UR-12.3`, `UR-12.5` | summary lifecycle/watermark is in `direct_context_composer`; catalog/legacy labels are outside the current code seam |
| F. UI/param-catalog rows | `UR-21.02`, `UR-21.03`, `UR-21.04`, `UR-21.05`, `UR-21.06`, `UR-21.07`, `UR-21.08`, `UR-21.09`, `UR-21.10`, `UR-21.11`, `UR-21.12`, `UR-21.14`, `UR-21.16`, `UR-21.18` | require `web/**` and `services/param_catalog.py`; belongs to UR-F, not this code slice |

Check: A 9 + B 6 + C 5 + D 6 + E 4 + F 14 = **44**.

## 2. Actual live trace

### 2.1 Direct L2 path

`DirectChatService._build_user_content` (`services/direct_chat_service.py:11084`) builds the legacy block list:
`map -> branch -> rag -> global -> thread -> target -> relations -> protected -> lore -> current`.

Inside it, composer-aware allocation still uses the old per-block API:

- `_composer.ContextPiece` construction: `:12304`
- `_composer.allocate_budget(...)`: `:12316` (primary) and `:12441` (fallback)

There is **no** `_composer.build_context_selection(...)` or `_composer.allocate_selection(...)` call in the direct path. The direct turn therefore does not produce or consume a `ContextSelection`.

### 2.2 Initiative L2 path

`generate_initiative_reply` is the only live caller:

- `_composer.collect_window_fragments(...)`: `:17743`
- `_composer.build_context_selection(...)`: `:17751`
- selected rows are filtered back from their `source_id` and then rendered by `_l1.render_window_lines(...)`: `:17770`

This is a real live use, but only for the initiative Writer's fresh window; it is not the shared L1/L2 selection required by the UR-C acceptance.

### 2.3 Composer API

- `ContextSelection`: `services/direct_context_composer.py:1017`
- `allocate_selection(...)`: `:1585`
- `build_context_selection(...)`: `:1829`; it calls `allocate_selection` at `:1924`
- `collect_window_fragments(...)`: `:1933`

Static call-site probe (`ast` over `services/direct_chat_service.py` and `services/direct_context_composer.py`):
`build_context_selection` = only line `17751`; `allocate_selection` = only internal line `1924`; direct path has only `allocate_budget` at `12316/12441`.

### 2.4 L1 path

`_l1.build_l1_context` still uses:

- `L1_WINDOW_MESSAGES = 20` (`services/direct_l1.py:1679`)
- `L1_WINDOW_LINE_CHARS = 200` (`:1698`)
- `render_window_lines(window, L1_WINDOW_MESSAGES, ...)` (`:2363`)

Direct `_plan_direct_l1` passes the raw `window`; initiative `plan_initiative_decision` also passes its own full window. `Current_Question` is full, but the window is still pre-truncated.

## 3. Why the first code increment is blocked

A safe implementation of group A requires a material projection decision, not a mechanical edit:

1. **Block mapping:** which `ContextSelection` fields render as `Current_Question`, `Conversation_Thread`, `Global_Context`, `RAG_Memory`, `Old_Episode`, `UserResolutionMap`, `Conversation_Branch` and relations blocks. The contract keeps these blocks as render projections, but the exact mapping (especially memory vs background vs summary) is not encoded as a single adapter.
2. **Stage timing:** build one selection before L1 and project it for L1, then reuse it for L2 (different budgets) versus build L2 selection after L1/tools. Contract §2.2 says L1/L2 get different projections of one selection; current direct code builds blocks before L1 and allocates again inside L2.
3. **Ownership of producers:** retrieval (`mca_retrieval_context`), self-output ledger (`bot_output_ledger`/`thread_chain`), summary map and evidence must feed the same selection; today the old direct path merges some of them into block strings and the initiative path uses a separate collector.
4. **Fallback semantics:** if `build_context_selection` raises or exceeds budget, must direct L2 keep the old block path, or use a bounded selected fallback? This changes user-visible context and needs an explicit rule.
5. **L1/L2 budget split:** which stage budget is authoritative for selection, and how the selected fragments are re-projected without a second independent cap; this is the UR-11/UR-10 contract boundary.

These are architecture/product contract choices. Guessing them would violate the “one context contract” and risk visible regressions in the direct path.

## 4. Options for the next increment

| Option | Change | Risk / rows | Recommendation |
|---|---|---|---|
| A1. Shadow selection trace only | Build `ContextSelection` on the direct path, emit provenance via existing turn diagnostics, leave payload unchanged | low risk; closes **no** acceptance row, but proves mapping/fixtures | safe first experiment if a trace is wanted |
| A2. L1-only selected projection | Feed selected fragments into `build_l1_context`; keep direct L2 old path | medium; can address UR-10/10.2/10.5 partially; still no shared L1/L2 selection | requires Architect mapping decision |
| A3. Full L1+L2 single selection | Build one selection; render all existing blocks from it; retire old direct `ContextPiece` allocation | high; required for most UR-C rows; largest regression surface | needs Architect decision and a dedicated review |

No option is implemented in this increment. No new gate, no threshold, no prompt weakening.

## 5. Verification

- `tests/test_ur_context_selection.py` — **38 passed** together with `tests/test_ur_bot_output_history.py`.
  Command: `python -m pytest tests/test_ur_context_selection.py tests/test_ur_bot_output_history.py -q -p no:cacheprovider`.
- No product/test/config change; `git diff --check` exit 0.
- `py_compile` not applicable: no Python file changed; existing suites import the modules.
- No map/status/`progress_scope.json`/`workflow_state.md`; no deploy/SSH/LLM.

## 6. RFL / blocker

- **Blocker `URC-FIRST-01` (architecture/contract):** choose the ContextSelection projection mapping and stage timing (A1/A2/A3) before wiring the direct path. This blocks group A/B/C code, not the whole queue.
- Group F (14 rows) is UR-F/param-catalog/UI, not this code lane; it should not be pulled into UR-C.
- Group D/E tests can be added independently only after the selection is live; otherwise they keep proving a test-only path.
- Production trace and effective config were not read; no owner QA.
- Rows remain PARTIAL; no VERIFIED.

## 7. Readiness

This branch contains evidence/design only. It is ready for an Architect/PM decision on A1/A2/A3, not for a code Reviewer. The next code increment starts only after that decision; no new gate is created.
