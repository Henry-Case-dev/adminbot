# F-01 — activation self-check must consume the deposited batch

**Defect (2.58.217 delta review, non-blocking):**
`RandomSourceService._confirm_activation(batch_id)` called
`self._store.reserve_chunk(1, config_fingerprint=self._current_fingerprint())`.
`reserve_chunk` selected the oldest consumable batch matching the strict
fingerprint clause, which admits `config_fingerprint IS NULL` rows. An older
LfDR batch (inserted with `config_fingerprint=None`) or a legacy NULL ANU batch
could therefore satisfy the activation self-check, while
`RandomSourceService.activate()` wrote
`mca_random_state.activation_batch_id = <newly fetched ANU batch>`. All draws
remained honestly `source=quantum` and the provider stayed hardware ANU for the
consumed value, but the attribution (`activation_batch_id`, journal batch) was
wrong: the state named a batch that had not produced the self-check value.

## Fix (single mechanism, additive)

`services/mca_random_source.py` (product commit `00d9ce3f84b4b83126d3f5544268c627e82df13c`):

1. `RandomStore._batch_clause(batch_id)` — additive exact predicate:
   - `None` → no filter (existing callers unchanged);
   - non-empty string → `AND batch_id = ?`;
   - empty/whitespace → `AND 0` (never a silent unscoped fallback).
2. `RandomStore.reserve_chunk(k, *, config_fingerprint=None, provider_ids=None,
   batch_id=None)` — new optional keyword. The only other caller (dream chunk,
   line 3589) passes no `batch_id`, so refill/draw/dream selection and
   oldest-first order are unchanged. No DDL, no second store, no schema change.
3. `_confirm_activation(batch_id)` now reserves with `batch_id=str(batch_id)` and
   refuses a chunk whose `item.batch_id` differs from the requested batch
   (contract guard). The journal record is built from the consumed item
   (`provider=item.provider, batch_id=item.batch_id`), and the state write happens
   only after a successful `pick`, so `activation_batch_id` names the batch that
   actually produced the value.
4. If the exact batch has no consumable value: `reserve_chunk` returns `[]`,
   `_confirm_activation` returns `False`, no foreign batch is consumed, no
   journal row and no activation state are written. `activate()` reports
   `validation_failed` with `deposited=false`; the refill path simply does not
   claim activation (the durable batch remains for the next attempt).

Configuration/factory defaults, gates, `APP_VERSION` (2.58.217), schema (48) and
all other random paths are untouched. No bump, no deploy, no production access.

## Evidence

- `red-base.txt` — final tests on clean detached `f68e7631d` (product untouched):
  **3 failed, 1 passed**. Mixed-batch: older LfDR batch consumed, ANU batch left
  at `(0,0)`; negative: `_confirm_activation` returned `True` from the foreign
  batch; store-level: no `batch_id` keyword (TypeError). Single-batch case passes
  on base (baseline).
- `tests.json` — batches and exact commands:
  - `f01-focused`: 4/4;
  - `focused-random-expanded` (P1/P2/P3 + blocks A–E + QND/JS): 314/0;
  - `mandatory-386` (24-file shared-code batch): 386/0;
  - `schema-apps-197`: 197/0.
- `mutations.json` + `mutation_probe.py` — 3/3 killed, exact bytes restored
  (sha256 before/after `0827075a…`):
  - M1 scope removed → 3 failed;
  - M2 silent unscoped fallback when target batch is empty → negative test failed;
  - M3 original defect + forced journal attribution → 3 failed.

## API change

`RandomStore.reserve_chunk` gains the keyword-only optional `batch_id`
(default `None`). Existing call sites and behavior are preserved; the new
parameter is used only by the activation self-check.

## Limitations / honest gaps

- The negative case calls `_confirm_activation` directly: the public activation
  path always inserts a fresh consumable batch, so an exhausted target batch can
  only appear through a crash/partial write between insert and self-check.
- Provider responses are injected; no real ANU request was made (network-free,
  temp SQLite). This is a provenance/scope fix, not a randomness-quality change.
- The pre-existing crash window between `reserve_chunk` and journal flush is
  unchanged (watermark may lose a reserved value; it is never reissued).

## Reviewer questions

1. Is the additive `batch_id` predicate the right minimal shared mechanism
   (versus adding `provider_ids` to the self-check)?
2. Is the consumed-item contract guard required by the invariant or redundant
   defense?
3. Is a direct `_confirm_activation` negative test acceptable given the public
   path cannot produce an exhausted fresh batch?

**Status:** REVIEW — independent approval required; no bump/deploy/integration.
