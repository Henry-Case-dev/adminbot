# MODEL-SWAP-01..05 — implementation evidence (2026-11-25)

- **Owner contract:** `plans/owner_inputs/2026-11-24-embedding-vmq-ibm-qrng-ux.md` §2; rows `MODEL-SWAP-01..05` in `requirements-map.json`; slice `MODEL-SWAP` in `slice-graph.json`.
- **Base:** production `5621bda8d` (`2.58.244`).
- **Code candidate:** `ba761b74e` on `feat/model-swap-2026-11-25` (implementation `3e079d26e` + target-dimension alignment `ba761b74e`; this evidence file is a follow-up docs commit).
- **No DDL, no new store, no new flag.** Reused existing tables/statuses; the only durable marker is `config_revision = "model_swap:<source_fp>"` on the existing generation row.

## Result per row

| Row | Implementation | Test proof |
|---|---|---|
| MODEL-SWAP-01 | Provider/key/endpoint changes never enter the flow: UI guard only fires for `models.embedding_model_name` / `models.embedding_dim`; `start_model_swap`/preview compare canonical `model_space_identity` (lowercase, provider namespace/`models/` stripped) and return `required=False` without registering a generation. | `test_model_swap_01_provider_only_no_generation`, `test_model_swap_01_canonical_model_name_is_same_space`; UI provider-only scenario (no preview call, normal config save). |
| MODEL-SWAP-02 | `GET /api/memory/embedding-change/preview` returns `old_model`, `new_model`, `old_dims`, `new_dims`, `requires_rebuild`, and a Russian reason naming the old/new model and why the derived vector index must be rebuilt. `saveBlock`/`persistItems` show the warning panel in «Модели и подключения» and do NOT persist the model/dim before confirmation. Provider fields may save normally. | `test_model_swap_02_warning_names_old_and_new`, `test_model_swap_02_dimension_only_requires_rebuild`; UI warning scenario at 1440 and `config_posts == 0` before confirm. |
| MODEL-SWAP-03 | Confirm calls `start_model_swap`: registers target generation(s) and durable `task_jobs`, does not change config. Existing resume ticker runs the shadow rebuild with P3 priority and checkpoints; `run_job` marks the target `ready` and the tick finalizes when all targets are ready. Cancel drops shadows/cancels jobs, leaving the old ACTIVE intact. Crash recovery: stale running → queued; `ready` → finalized by the next tick. Progress = `task_jobs` checkpoint; errors = durable `reason_code`. | `test_model_swap_03_04_05_full_flow`, `test_model_swap_03_resume_after_restart_from_checkpoint`, `test_model_swap_03_cancel_keeps_old_index`, `test_model_swap_03_crash_after_ready_finalized_by_tick`, `test_model_swap_api_start_and_state`, `test_model_swap_03_executor_uses_target_model_override`; UI progress `123 из 500`, state `building`, no overflow/console errors at 1440×900 and 390×844. |
| MODEL-SWAP-04 | During the build the effective config keeps the old model; the ACTIVE generation and live vectors are untouched. Search continues on the old index through the configured (compatible) model. If that model is unavailable, the panel reports the fallback channels (FTS, graph, episodes, archive, operational context) and the existing memory paths stay in place. | `test_model_swap_03_04_05_full_flow` asserts config cache still empty, old ACTIVE still `active`, `_index_generation_ok == True`, old live vectors unchanged; state exposes `old_index_serving`/`fallback_channels`. |
| MODEL-SWAP-05 | New vectors are written only to the existing per-generation shadow table with the target dimension; live swap (`_activate`) and config switch happen only after every target with source is `ready`. Source fingerprint is re-checked inside validation and activation; a config change during build aborts with `source_identity_changed`. Source facts (`graph_facts`/`smart_archive_facts`) are never modified. Dimension changes rebuild the shadow/live DDL at the target dimension. | `test_model_swap_03_04_05_full_flow`, `test_model_swap_05_source_change_during_build_never_activates`, `test_model_swap_05_dimension_change_switches_ddl` (live DDL `float[4]`, `memory._vec_dim == 4`). |

## State machine (durable, derived from existing rows/jobs)

```text
stable ──preview(space differs)──▶ warning (no write / no generation)
warning ──confirm──▶ target rows: building + jobs queued   (config = OLD)
queued ─▶ building (checkpoint/heartbeat) ─▶ validated ─▶ ready
ready (all required indexes) ─▶ per-index atomic shadow swap ─▶ config switch ─▶ active
building/ready ──cancel──▶ cancelled (shadow dropped; old ACTIVE untouched)
failed/paused ──resume──▶ queued (same generation/checkpoint)
crash: stale running ──tick──▶ queued; ready ──tick──▶ finalize
```

`model_swap_state` is read-only and reports `state`, `processed`, `total`, `errors`, `old_model`, `new_model`, `old_index_serving`, `can_cancel`, `can_resume`. No separate state table or flag.

## Reused vs new

**Reused (unchanged mechanisms):** `mca_embedding_index_generations` + `building → building_target → catching_up → ready → active`, `register_embedding_target_generation`, `_ensure_job`/`task_jobs` checkpoints/heartbeat/`RebuildLease`, `_validate`/`_activate` shadow swap, resume ticker, `_source_empty`/`_source_total`, `ConfigCache.set_many`, `model_space_identity`.

**New, minimal:** swap branch in `maybe_schedule_rebuilds`; target-model override in `EmbeddingExecutor.embed`/`execute_embed` (used only by the swap rebuild); collective `_finalize_model_swap`; three read-only/control endpoints in `web/api/memory_agi.py`; warning/progress panel in the embeddings block; the swap marker in `config_revision`.

## Tests (actual results)

Environment: global Python 3.12 (`C:\Users\main\AppData\Local\Python\bin\python.exe`), `PYTHONPATH=<worktree>`, `-p no:cacheprovider`.

| Run | Result |
|---|---|
| `tests/test_embed_model_swap_ux.py` (13 tests incl. Playwright UI 1440/390) | **13 passed** |
| Focused embed/generation regression: `test_graphrag_identity_reindex`, `test_embed_simplify_2026_11_24`, `test_embed_identity_compat_restart_legacy`, `test_p0_embed_admission_msi`, `test_p0_embed_503_failover`, `test_embed_identity_compat`, `test_asap6_embedding_generations`, `test_summary_memory`, `test_embedding_control_plane_asap4`, `test_webapp_memory_overview_api` | **268 passed** |
| Same new file at base `5621bda8d` (RED) | **13 failed** — backend `AttributeError: module 'services.graphrag_rebuild' has no attribute 'start_model_swap'`; UI waits for `[data-embed-swap-warning]` timeout |
| Broader embed/graphrag/rebuild filter | **678 passed, 5 pre-existing failures** (verified identical at base `5621bda8d`: `test_asap5_graphrag_recovery::test_warning_coalesced_not_repeated`, `test_graphrag_rebuild_asap32::test_not_serviceable_warning_coalesced`, 3 × `test_image_generation_round1023` tool-order) |
| `node --check web/app.js` | OK |

UI check (Playwright, real `web/index.html` + `web/app.js`, route-stubbed API): desktop 1440×900 and mobile 390×844 — warning names both models, confirm starts the flow, progress shows `123 из 500`, `state=building`, `documentElement.scrollWidth <= innerWidth`, `console errors == []`; provider-only edit shows no warning and performs a normal config save.

## Honest residuals

1. **No production model change / rebuild was executed** (owner prohibition in §2). All rebuild evidence uses deterministic fake embeddings; real-provider rebuild remains to be exercised when a real model change is confirmed.
2. **Direct `POST /api/config` of the model key bypasses the confirm UI** and follows the legacy config-first auto-rebuild (FTS-only during that rebuild). The supported user flow is the embeddings block/advanced guard; adding a server-side 409 to the generic config endpoint was outside this slice (`routes.py` not in `MODEL-SWAP` write scope).
3. A new model with a different vector length requires the operator to set `models.embedding_dim` in the same confirmation. Otherwise the rebuild fails safely with `dim_changed`; the old index keeps serving and the UI shows the error.
4. `old_model_available` is inferred from the configured connection profiles, not from a live health probe; actual provider failure degrades to the other memory channels through existing code.
5. Swap rebuild requires `EMBED_CONTROL_PLANE_ENABLED=ON` (production default). With it OFF the job fails safely and the old index remains.
6. No DDL and no new flag were needed.
