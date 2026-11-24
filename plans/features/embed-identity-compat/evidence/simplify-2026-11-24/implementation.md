# SIMPLIFY 2026-11-24 — implementation evidence (embedding compat simplification)

- Branch: `fix/embed-simplify-2026-11-24`, base `a200b8c9a` (release 2.58.240 tip;
  no newer 2.58.240 tip existed in the checkout).
- Owner source: `plans/owner_inputs/2026-11-24-embedding-vmq-ibm-qrng-ux.md` §1, §6.
- PM rows: `SIMPL-01..07`, slice `SIMPLIFY` (`requirements-map.json` /
  `slice-graph.json`, canonical planning working copy).
- SIMPL-05 input (read-only audit, basis `6123a1469`):
  `plans/features/embed-identity-compat/evidence/audit-2026-11-24.md`,
  sha256 `6be1e9dd1240758272de434902924f8f7d1697116323e01a294261b896d02f46`.
  Files are uncommitted PM artifacts in the canonical planning checkout; this
  evidence references them instead of duplicating them.
- DDL = 0, no new flags/tables/identity systems, no config/settings change, no
  vector rewrite, no rebuild, no network/LLM/prod access.

## Per-row result

| Row | Change (file:line) | Proving test | Deliberately kept |
|---|---|---|---|
| SIMPL-01 provider/endpoint/key/alias/PCI/quota ≠ space change | `services/embedding_control_plane.py:3047` canonical model in MSI (`_canonical_model_name` `:3560`, shared with probe `:3574`); **review r1 F1**: legacy ACTIVE-row comparison also canonical `:3150`; credential health keyed by key value `:738/:774/:803` + `credential_key_fingerprint:265`; executor uses it `:1742/:1772/:1945/:1979/:2057/:2400` | `test_simpl01_provider_endpoint_change_keeps_index_serviceable`, `test_simpl01_msi_ignores_provider_namespace`, `test_simpl01_legacy_namespaced_model_is_not_a_new_space`, `test_simpl01_auth_failed_is_per_key_and_expires` | MSI as the only space authority; ACTIVE+equal-MSI instant path already present at base (verified, not re-added); PCI stored as provenance |
| SIMPL-02 compatible fallback usable for write **and** search; no per-endpoint block | `services/summary_memory.py:3211` `_serving_route_space_matches` (MSI equality) replaces PCI/primary comparison; call at `:3411` | `test_simpl02_cache_gate_uses_model_space_not_provider`; existing `tests/test_p0_embed_admission_msi.py::test_same_msi_different_pci_writes_and_semantic_search` (real write + semantic KNN via fallback) | `_serving_route_write_allowed` per-leg MSI check (unchanged); generation/adoption gates |
| SIMPL-03 incompatibility only from model/vector properties | No new positive proof invented: resolver still returns `insufficient` (not `incompatible`) without MSI/admission, and `incompatible` only on model/dims/preprocessing (`embedding_control_plane.py:3841-3903`, unchanged) | `test_simpl03_missing_provenance_is_not_incompatible` | dimension/model/declared-dims checks (`:3559-3578`), `incompatible → controlled_migration` |
| SIMPL-04 probe light/non-blocking; probe failure does not stop memory | removed compat pause: `embedding_control_plane.py:4339-4350` no longer calls `_pause_rebuild_under`; dead `_PAUSED_BY_COMPAT` + function removed; legacy compat pauses are still resumed/cancelled (`:4200-4222`); reads-on-insufficient gate `summary_memory.py:2936-3079` | `tests/test_embed_identity_compat.py::test_insufficient_does_not_pause_rebuild_until_verdict`, `tests/test_embed_identity_compat_restart_legacy.py::test_b1_restart_then_insufficient_keeps_job_running_without_rebuild`, `test_simpl02_insufficient_active_equal_dims_serves_reads` | one probe per init/tick, numeric floors/hit5, `needs_probe` state, legacy durable-pause recovery |
| SIMPL-05 dated audit, duplicate mechanisms removed | Audit accepted as input (link above); diff removes dead process set/function and merges duplicate vector validation into one helper (`llm_client.py:413`, used `:3049/:3108`); cache gate merged to MSI | `test_simpl02_cache_gate_uses_model_space_not_provider`, `test_simpl07_msi_and_admission_formats_unchanged`; code audit of diff (6 files) | MSI, durable admission (`admit1:`), probes, generation/shadow/backfill, migration chunks, quota parking |
| SIMPL-06 response validation preserved/extended | `services/llm_client.py:413` count/non-empty/uniform-dims/finite-number guard, applied to both `embed()` and `embed_once()`; probe numeric/dims/model checks untouched | `test_simpl06_control_plane_rejects_malformed_vectors`, `test_simpl06_real_incompatibility_still_blocks_write` | canary drift write block, probe floors, dims/model checks, controlled migration |
| SIMPL-07 no new identity systems/DDL, history untouched | No tables/columns/registries added; MSI/admission formats unchanged (`embedding_control_plane.py:3047-3058`, `:3203-3232`) | `test_simpl07_msi_and_admission_formats_unchanged`; `git diff` contains no DDL | existing MSI/admission records; stored vectors and generations |

Narrowed rows: `DEC-07` no longer gates reads on a missing permit for
`insufficient`+ACTIVE+equal-dims (`summary_memory.py:3015-3028` returns
reads-open/writes-closed); `ACC-14/CANARY-02/IDENT-05/CANARY-09/10/DEC-10/ACC-11`
still hold for proven model/vector incompatibility (tests `simpl03`, `simpl06`).

## What was already true at base (not claimed as new)

- Provider-only change with an ACTIVE row carrying `model`+`dims`+preprocessing
  already resolved `compatible/INSTANT` without a probe (`embedding_control_plane.py:3841-3869`).
  The new test pins this as a regression guard; the newly fixed gaps were
  namespaced-model MSI, `auth_failed` permanence, probe-pause, insufficient reads
  and the cache gate.
- Write path already re-admitted fallback legs by MSI; only the cache gate was
  PCI-based.

## Review r1 corrective — SIMPL-R1-F1 (blocking, fixed)

Reviewer artifact: `evidence/simplify-2026-11-24/review-r1.md` (candidate
`e67378335`, verdict NEEDS_FIXES, blocking `SIMPL-R1-F1`).

- Defect: `_row_space_differs_provably` compared the model as a RAW string, so a
  legacy ACTIVE row (MSI not derivable) storing `models/gemini-embedding-001`
  against configured `gemini-embedding-001` was declared
  `incompatible/identity_changed -> controlled_migration` — a provider-namespace
  difference treated as a space change, violating owner §1 / SIMPL-01/03.
- Fix: `services/embedding_control_plane.py:3150` now compares
  `_canonical_model_name(model) != _canonical_model_name(model_now)` — the SAME
  single-source canonicalizer already used by MSI (`:3047`) and the probe
  comparison (`:3574`); no second normalization implementation. Dimension
  comparison (`_dims_differ`) and generation parameters are unchanged.
  A genuinely different model still yields `identity_changed -> incompatible ->
  controlled_migration`.
- Regression test:
  `tests/test_embed_simplify_2026_11_24.py::test_simpl01_legacy_namespaced_model_is_not_a_new_space`
  — legacy ACTIVE `models/gemini-embedding-001` + configured
  `gemini-embedding-001` stays `insufficient/msi_unavailable`, reads open
  (`_index_generation_ok=True`), writes text-only; then
  `text-embedding-004` → `incompatible/identity_changed/controlled_migration`,
  reads closed.
- RED proof: temporarily restored the raw comparison `model != model_now`
  (original line), ran the new test → **1 failed**:
  `assert 'incompatible' == 'insufficient'`; restored the canonical form and
  re-ran → green. `git diff` after restore shows only the intended 5-line hunk.
- Backlog `SIMPL-R1-F2` (the `<= 1` assertion in
  `test_p0_embed_admission_msi.py::test_different_msi_is_text_only`) was NOT
  changed: it is a non-blocking reviewer backlog item; the write-gate invariant
  is unchanged and covered by `_vec_write_allowed is False` in the same test.
- Pre-existing red stays exactly 2 (warning coalescing), reproduced at base
  `a200b8c9a`; unrelated to this corrective.

## Verification (actual, this worktree)

- `pytest tests/test_embed_simplify_2026_11_24.py` → **10 passed**.
- `pytest tests/test_embed_identity_compat.py tests/test_embed_identity_compat_restart_legacy.py tests/test_p0_embed_admission_msi.py tests/test_p0_embed_503_failover.py tests/test_embed_simplify_2026_11_24.py` → **75 passed**.
- `pytest tests/test_embedding_control_plane_asap4.py tests/test_embed_fallback_slots_routing.py tests/test_llm_client.py tests/test_embed_meta_wire.py tests/test_evol010_embedding_defects.py` → **209 passed**.
- `pytest tests/test_summary_memory.py` → **79 passed**.
- `pytest tests/test_graphrag_identity_reindex.py tests/test_graphrag_rebuild_asap32.py tests/test_asap5_graphrag_recovery.py tests/test_asap6_embedding_generations.py tests/test_mca07_retrieval_context_round1027.py` → **83 passed, 2 failed** — both failures are **pre-existing at base** (see below), unchanged by F1.
- `pytest tests/test_memory_period_vector_leg.py` → **31 passed**.
- Broad `pytest tests -k "embed or compat_msi or generation_index or retrieval_context"` (minus the heavy files above) → **246 passed** (pre-F1 run; F1 only narrows an incompatible branch).
- `python -m py_compile` on all changed modules/tests → exit 0.
- `git diff --check` → exit 0.

### RED proof on base `a200b8c9a` (original slice, 9 tests)

Implementation stashed (`git stash push -- services/... tests/...`), new test file
run unchanged against base code, then `git stash pop` (clean):

**5 failed, 4 passed**
- `test_simpl01_msi_ignores_provider_namespace` (MSI hash accepts `google/…` as a different space)
- `test_simpl01_auth_failed_is_per_key_and_expires` (no per-key health/TTL; `TypeError` on `key_fp`)
- `test_simpl02_insufficient_active_equal_dims_serves_reads` (reads closed on `insufficient`)
- `test_simpl02_cache_gate_uses_model_space_not_provider` (method absent; PCI gate)
- `test_simpl06_control_plane_rejects_malformed_vectors` (`DID NOT RAISE LLMBadResponseError`: NaN/inf/ragged pass)

4 passing on base are regression guards for behaviour already present
(`simpl01_provider_…`, `simpl03_…`, `simpl06_real_incompatibility_…`, `simpl07_…`).

### Pre-existing failures (NOT caused by this change)

`tests/test_graphrag_rebuild_asap32.py::test_not_serviceable_warning_coalesced`
and `tests/test_asap5_graphrag_recovery.py::test_warning_coalesced_not_repeated`
fail identically with the implementation stashed on base `a200b8c9a`
(building→superseded state transition emits a second warning). Not fixed here
(unrelated to SIMPLIFY; would be an incidental refactor).

## Residual risk (honest)

1. MSI canonicalization merges vendor models with the same basename
   (`vendorA/gemini-embedding-001` vs `vendorB/gemini-embedding-001`). Numeric
   probe/canary still catch actual drift where they run; rows whose MSI is
   derived from stored metadata are trusted without a new probe. Real different
   basenames/dimensions still produce `incompatible`.
2. On `insufficient`+ACTIVE+equal-dims, reads may rank against a possibly
   different (same-dim) space until the probe settles. Non-destructive: FTS,
   graph, episodes stay intact, and writes remain text-only.
3. `auth_failed` TTL allows at most one retry per 15 min against a still-bad
   key (cost, not data loss). A replaced key is never blocked.
4. A compatible fallback leg's vector may now enter `embedding_cache` under the
   configured MSI. If a provider silently swaps space under the same name,
   canary drift still blocks writes; cache hits return configured-space-keyed
   vectors only, and write admission is unchanged.
5. `SIMPL-01/02` are `live_required` (preprod): real NanoGPT-primary + Google
   reserve write/search were **not** exercised here (no prod/network/LLM in this
   lane). This remains an **open verification step for the release gate**:
   subagent observations cannot replace the preprod effective-state check
   (`ok=true` on real embed per provider path + one real index write + one
   semantic retrieval), and DevOps must record effective config/SHA.
6. Legacy compat pauses written by 2.58.240 remain readable/resumable; no new
   ones are created. Operator `paused` rows are never touched.
