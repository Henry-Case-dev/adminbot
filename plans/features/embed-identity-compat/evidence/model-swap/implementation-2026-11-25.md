# MODEL-SWAP-01..05 — implementation evidence (2026-11-25)

- **Owner contract:** `plans/owner_inputs/2026-11-24-embedding-vmq-ibm-qrng-ux.md` §2; rows `MODEL-SWAP-01..05` in `requirements-map.json`; slice `MODEL-SWAP` in `slice-graph.json`.
- **Base:** production `5621bda8d` (`2.58.244`).
- **Code candidate:** `21da28821` on `feat/model-swap-2026-11-25` (review-r1 corrective F1/F2/F3/F4; parent `4aec98f13`, implementation `3e079d26e` + `ba761b74e`; this evidence file is a follow-up docs commit).
- **No DDL, no new store, no new flag.** Reused existing tables/statuses; the only durable marker is `config_revision = "model_swap:<source_msi>"` on the existing generation row (canonical MSI, provider/URL/key excluded).

## Result per row

| Row | Implementation | Test proof |
|---|---|---|
| MODEL-SWAP-01 | Provider/key/endpoint changes never enter the flow: UI guard only fires for `models.embedding_model_name` / `models.embedding_dim`; `start_model_swap`/preview compare canonical `model_space_identity` (lowercase, provider namespace/`models/` stripped) and return `required=False` without registering a generation. | `test_model_swap_01_provider_only_no_generation`, `test_model_swap_01_canonical_model_name_is_same_space`; UI provider-only scenario (no preview call, normal config save). |
| MODEL-SWAP-02 | `GET /api/memory/embedding-change/preview` returns `old_model`, `new_model`, `old_dims`, `requires_rebuild`, and a Russian reason naming the old/new model and why the derived vector index must be rebuilt; `new_dims` is actual-only (never the old value for a new model). The UI obtains the real dimension via `POST /api/memory/embedding-change/probe` (one real embeddings call) or asks for it explicitly with >0 validation; confirm is blocked until known. `saveBlock`/`persistItems` show the warning panel in «Модели и подключения» and do NOT persist the model/dim before confirmation. Provider fields may save normally. | `test_model_swap_02_warning_names_old_and_new`, `test_model_swap_02_dimension_only_requires_rebuild`, F2 tests below; UI warning at 1440 with old/new and actual `4`, `config_posts == 0` before confirm. |
| MODEL-SWAP-03 | Confirm calls `start_model_swap`: registers target generation(s) and durable `task_jobs`, does not change config. Existing resume ticker runs the shadow rebuild with P3 priority and checkpoints; `run_job` marks the target `ready` and the tick finalizes when all targets are ready. Cancel drops shadows/cancels jobs, leaving the old ACTIVE intact; a `failed` job is explicitly cancellable. Crash recovery: stale running → queued; `ready` → finalized by the next tick. Progress = `task_jobs` checkpoint; errors = durable `reason_code` (human label in UI, code in diagnostics). | `test_model_swap_03_04_05_full_flow`, `test_model_swap_03_resume_after_restart_from_checkpoint`, `test_model_swap_03_cancel_keeps_old_index`, `test_model_swap_03_crash_after_ready_finalized_by_tick`, `test_model_swap_api_start_and_state`, `test_model_swap_03_executor_uses_target_model_override`, F1 tests below; UI progress `123 из 500`, state `building`, no overflow/console errors at 1440×900 and 390×844. |
| MODEL-SWAP-04 | During the build the effective config keeps the old model; the ACTIVE generation and live vectors are untouched. Search continues on the old index through the configured (compatible) model. If that model is unavailable, the panel reports the fallback channels (FTS, graph, episodes, archive, operational context) and the existing memory paths stay in place. | `test_model_swap_03_04_05_full_flow` asserts config cache still empty, old ACTIVE still `active`, `_index_generation_ok == True`, old live vectors unchanged; state exposes `old_index_serving`/`fallback_channels`. |
| MODEL-SWAP-05 | New vectors are written only to the existing per-generation shadow table with the target dimension; live swap (`_activate`) and config switch happen only after every target with source is `ready`. The source guard compares the canonical source MSI (model+dimension+preprocessing), so provider/URL/credential edits during a rebuild do not abort it; a real space change aborts with `source_space_changed`. Source facts (`graph_facts`/`smart_archive_facts`) are never modified. Dimension changes rebuild the shadow/live DDL at the target dimension. | `test_model_swap_03_04_05_full_flow`, `test_model_swap_05_source_change_during_build_never_activates`, `test_model_swap_05_dimension_change_switches_ddl`, F1 provider-drift test below. |

## State machine (durable, derived from existing rows/jobs)

```text
stable ──preview(space differs)──▶ warning (no write / no generation)
warning ──confirm──▶ target rows: building + jobs queued   (config = OLD)
queued ─▶ building (checkpoint/heartbeat) ─▶ validated ─▶ ready
ready (all required indexes) ─▶ per-index atomic shadow swap ─▶ config switch ─▶ active
building/ready ──cancel──▶ cancelled (shadow dropped; old ACTIVE untouched)
failed ──cancel──▶ cancelled (failed job CASes to cancelled; old ACTIVE untouched)
failed/paused ──source MSI restored──▶ resume ──▶ queued (same durable target)
crash: stale running ──tick──▶ queued; ready ──tick──▶ finalize
```

`model_swap_state` is read-only and reports `state`, `processed`, `total`, `errors`, `old_model`, `new_model`, `old_index_serving`, `can_cancel`, `can_resume`. No separate state table or flag.

## Reused vs new

**Reused (unchanged mechanisms):** `mca_embedding_index_generations` + `building → building_target → catching_up → ready → active`, `register_embedding_target_generation`, `_ensure_job`/`task_jobs` checkpoints/heartbeat/`RebuildLease`, `_validate`/`_activate` shadow swap, resume ticker, `_source_empty`/`_source_total`, `ConfigCache.set_many`, `model_space_identity`.

**New, minimal:** swap branch in `maybe_schedule_rebuilds`; target-model override in `EmbeddingExecutor.embed`/`execute_embed` (used only by the swap rebuild); collective `_finalize_model_swap`; four read-only/control endpoints in `web/api/memory_agi.py` (preview/state/probe/start, plus cancel/resume); warning/progress panel in the embeddings block; the swap marker in `config_revision`.

## Review r1 corrective (F1–F4)

- **F1 — canonical source guard + recoverable failed.** The durable marker now stores the canonical source MSI (`model_space_identity`: model/dimension/preprocessing), not the provider-inclusive fingerprint. `_validate`, `_activate`, the scheduler and state compare that MSI, so changing the provider/URL/key during a rebuild does not abort it. A real space change still aborts (`source_space_changed`). `model_swap_state` adds `source_space_current`; `failed` is always `can_cancel`, and `can_resume` is true only when the current MSI again equals the source. `cancel_model_swap` CASes a failed job to cancelled; `resume_model_swap` reopens a failed job only when the source MSI matches, and the tick then schedules it.
- **F2 — real new dimension.** `POST /api/memory/embedding-change/probe` performs one real embeddings call with the selected model through the existing credential pool and returns the actual vector length (no secrets). The UI calls it when the model changes and no explicit dimension is supplied; the warning shows the actual new dimension or an explicit numeric input, and Confirm stays disabled until a valid dimension exists. `POST .../start` probes automatically when `dim` is absent and returns 422 `dimension_required` if the probe fails; `start_model_swap` itself refuses a model change without a dimension. `preview` never substitutes the old dimension for the new model.
- **F3 — copy.** Warning renders old/new models and dimensions on separate lines with explicit ` · размерность N`; equal dimensions show «Размерность не меняется (N).» instead of an “old vs new” contradiction; no missing space / «8 изм.» artifact.
- **F4 — no raw codes on screen.** Panel errors use Russian human labels; raw `reason_code` is available only inside the collapsible `data-embed-swap-diagnostics` details (UI test asserts the code is not in the visible error line).

RED on parent candidate `4aec98f13`: all six new corrective tests failed before this commit (provider drift → false `source_identity_changed`; failed Cancel no-op; failed Resume no-op; missing dimension accepted/old dims; probe endpoint absent; probe-failure path absent).

## Tests (actual results)

Environment: global Python 3.12 (`C:\Users\main\AppData\Local\Python\bin\python.exe`), `PYTHONPATH=<worktree>`, `-p no:cacheprovider`.

| Run | Result |
|---|---|
| `tests/test_embed_model_swap_ux.py` (19 tests incl. Playwright UI 1440/390, probe/manual-dimension scenarios) | **19 passed** |
| Focused embed/generation regression: `test_graphrag_identity_reindex`, `test_embed_simplify_2026_11_24`, `test_embed_identity_compat_restart_legacy`, `test_p0_embed_admission_msi`, `test_p0_embed_503_failover`, `test_embed_identity_compat`, `test_asap6_embedding_generations`, `test_summary_memory`, `test_embedding_control_plane_asap4`, `test_webapp_memory_overview_api` | **268 passed** |
| Same new file at base `5621bda8d` (initial RED) | **13 failed** — `AttributeError: start_model_swap`; UI warning selector absent |
| Six corrective tests at parent `4aec98f13` (review-r1 RED) | **6 failed** — provider drift false-failed, failed cancel/resume no-op, missing/new dimension cases, probe API absent |
| Broader embed/graphrag/rebuild filter | **685 passed, 5 pre-existing failures** (verified identical at base `5621bda8d`: `test_asap5_graphrag_recovery::test_warning_coalesced_not_repeated`, `test_graphrag_rebuild_asap32::test_not_serviceable_warning_coalesced`, 3 × `test_image_generation_round1023` tool-order) |
| `node --check web/app.js` | OK |

UI check (Playwright, real `web/index.html` + `web/app.js`, route-stubbed API): desktop 1440×900 and mobile 390×844 — warning names both models plus actual new dimension `4`, probe called once, confirm sends `{model, dim: 4}`, progress `123 из 500`, `state=building`, human error label with raw code only in diagnostics, no horizontal overflow, `console errors == []`; provider-only edit shows no warning and saves normally; probe-failure fallback shows the dimension input, keeps Confirm disabled until `6` is entered, and starts with `dim: 6`.

## Honest residuals

1. **No production model change / rebuild was executed** (owner prohibition in §2). All rebuild evidence uses deterministic fake embeddings and a stubbed dimension probe; the first real model change remains the final live proof for 03/04/05 (`delivered_awaiting_evidence`, agents perform it, not the owner).
2. **MS-R1-B1 remains BACKLOG_ONLY:** a direct `POST /api/config` of the model key during an active swap bypasses the UI. Existing safety still prevents mixing (new vectors only in shadow), and a failed swap is now cancellable; a state-aware 409/cancel-on-config-change is a separate task outside this slice.
3. **Dimension probe needs a usable provider credential and network.** If the probe fails, the confirm dialog requires an explicit integer dimension (>0); a wrong manual value fails safely with `dim_changed` and the old index remains. Probe cost is one `POST /embeddings` per confirmation, not per page view.
4. `old_model_available` is inferred from the configured connection profiles, not from a live health probe; actual provider failure degrades to the other memory channels through existing code.
5. Swap rebuild requires `EMBED_CONTROL_PLANE_ENABLED=ON` (production default). With it OFF the job fails safely and the old index remains.
6. No DDL and no new flag were needed.
