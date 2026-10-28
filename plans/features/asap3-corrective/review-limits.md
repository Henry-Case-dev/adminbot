# Review — ASAP3 §2 limits inventory (lane REV-ASAP3-LIMITS)

Candidate: `b90049afcab85e1708eb384c0604f3340bdb50c3` (24.10.2026).
Binding: `git diff b90049af -- services/mca_expression.py services/dossier_prompts.py services/mca_sample_library.py services/direct_chat_service.py tests/test_asap3_hidden_limits.py` is empty; working HEAD (`edda97ce`) advanced with unrelated inspector changes. Review read-only.

## Verdict: **Needs Fixes**

2 of 4 declared HIDDEN_LOSS fixes are only partial; the inventory's "4/4 fixed" and one TECHNICAL_VISIBLE row are not supported by code. No regression and no safety-budget weakening found.

## Acceptance ledger

| Item | Status | Evidence |
|---|---|---|
| #11 current question cap → WARN numbers | VERIFIED (minor edge) | `direct_chat_service.py:6665-6681`; test `test_current_question_truncation_is_logged` |
| #12 dossier 10 items + 1200 chars → visible | **FAILED** | char budget WARN works, but 10-item cap is applied before formatter and stays silent (`:8108-8113`) |
| #13 expression examples → `budget_excluded` / kept=X/Y | **FAILED (partial)** | token/char loss visible; 4-item cap applied in resolver before counters (`mca_sample_library.py:1417`) stays silent |
| #14 sample field clip → WARN | VERIFIED (visibility), untested | `mca_sample_library.py:565-587`; owner UI path already 422 via `SampleWrite` max_length (`web/api/speech.py:3466-3469`) |
| Inventory completeness / classes | **FAILED** | row #19 claims "WARN экстрактора" for 8000-char tail; no WARN exists (`summary_memory.py:3308`) |
| No new limits system; budgets unchanged | VERIFIED | diff only adds counters/logs; no catalog/env additions; 140 tokens/700 chars/4 items, 1200 chars, 800 chars, 2000/4000 unchanged |

## Blocking findings

### F1 (BLOCKER) — dossier item cap (10) is still a silent loss; card count lies
`services/direct_chat_service.py:8108-8113`: `facts/protected/lore` and `memes` are sliced to `_PERSONA_MAX_ITEMS=10` **before** `format_dossier_block`, so `stats` only ever sees ≤10 and reports `truncated=False`. `get_persona_card` returns all facts (only links use SQL LIMIT) — probe with 30 facts + 5 protected + 15 memes, irony ON:
`карточка: Вася / знаю о тебе: 10 фактов` and exactly 10 fact lines, 10 memes, no WARN (`OPENCODE_WORKFLOW_SCRATCH/rev_limits_dossier_probe.py`).
Impact: owner memory beyond 10 items silently absent; displayed "10 фактов" is false when more exist (also links are capped by SQL LIMIT with no total). Recheck: same probe must log `facts_kept=10/35` and show a truthful total ("10 из 35"). Minimal fix: compute totals before slice, pass into WARN, make count truthful; add one test through `build_persona_card`.

### F2 (BLOCKER) — expression 4-item cap is still silent; counters under-report
`services/mca_sample_library.py:1417-1418` breaks the approved-row loop at 4. Therefore `render_expression_examples_block` never sees more than 4 rows in production: `ExampleRender.total_items`/`dropped` describe the resolver output, not "сколько строк было у владельца" as the docstring/evidence claim. Probe: 20 approved rows → resolver 4, render `total=4 included=4 dropped=0 limited_by=""`, zero WARN (`OPENCODE_WORKFLOW_SCRATCH/rev_limits_expr_probe.py`). Manifest shows only the rendered block.
Impact: approved examples #5..N never reach runtime and are never reported — the item half of HIDDEN_LOSS #13 remains hidden. `test_expression_examples_item_cap_is_counted_not_silent` and the partial-drop test mock 6 rows, a seam the real resolver cannot produce (test green ≠ contract). Recheck: 20 approved rows through the real resolver seam → WARN `kept=4/20 | by=items`.

### F3 (BLOCKER) — inventory row #19 misclassified: 8000-char extractor tail has no WARN
`services/summary_memory.py:3308` does `tail = text[-8000:]` with no length comparison/log (`_FACT_EXTRACT_MAX_CHARS` used only at 164/1254/3308); `:1254` same for YouTube compression input. Row #19 says `TECHNICAL_VISIBLE (WARN экстрактора)`, so long owner text silently loses its earlier part during memory extraction — a 5th HIDDEN_LOSS, not a visible technical limit. Consequences: §2 count "4 HIDDEN_LOSS, fixed 4/4" and HID-TECH-VISIBLE are not supported.
Minimal fix: WARN with `chars -> 8000` before slicing (or honestly reclassify + fix visibility); one unit test.

## Related small

- No test asserts `persona dossier capped` from `build_persona_card` or `field clipped` from `_clip_field`; both integration points are unverified.
- `direct_chat_service.py:6674-6675`: when `room == 0` (markers fill cap) the whole question is dropped with no WARN — narrow edge of #11.
- `#14` inventory wording ("владелец мог вставить длиннее — резалось молча") is unreachable through the owner UI: `SampleWrite` -> 422; the WARN is defense-in-depth, not a repaired owner-facing loss. Cosmetic, but evidence must say so.
- Requirements map rows HIDDEN-LIMITS are still `PENDING` with empty evidence (PM/bookkeeping; gate `--stage review` cannot pass until bound).

## Checks run (verified, not reused)

- `tests/test_asap3_hidden_limits.py` — 7 passed.
- `test_add_exp_expression.py + test_samples_fewshot.py` — 52 passed.
- `test_dossier_irony.py + test_chat_lore.py + test_direct_chat.py` — 193 passed.
- `test_asap3_style_hint_limits.py + test_asap3_acceptance.py + test_asap3_identity_aliases.py` — 45 passed.
- `test_dossier_prompts.py + test_soul1_w4_sample_library.py` — 52 passed.
- `test_soul1_w4_examples_scope.py + test_samples_categories.py + test_samples_factory_persist.py` — 29 passed.
- Total 378 passed, 0 failed. Tests are green but do not cover F1-F3.

## Deferral judgment

- Dossier budget configurability: deferral is legitimate (technical/defensive limit; §2 requires visibility, not a new knob) — but only after the 10-item cap is made visible.
- UI length counter in sample editor: not mandatory; the API already rejects >2000/4000 with 422. WARN is sufficient. Separate UI lane, not a blocker.
- No new global limits system introduced — requirement satisfied.

## Can it ship ("в поезд")?

As code: yes for a routine deploy — payload bytes unchanged, safety budgets untouched, 378 tests green, no regression found. As "S10 / limits inventory closed": **no** — 2 residual silent losses and one false TECHNICAL_VISIBLE remain. Do not mark HIDDEN-LIMITS VERIFIED on this evidence.

