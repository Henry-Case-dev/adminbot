# VMQ-MEM-RC6a (C2; E1 excluded) — implementation evidence (2026-11-23)

Статус: **candidate for independent Reviewer**, не VERIFIED и не product-code
approval. `VMQ-MEM-02/03/04` остаются REVIEW. RC6a — read-path only; E1
(subject-threshold) не входит и не менялся.

## 1. Lineage / scope

| Что | Значение |
|---|---|
| Base | `4828f30a9b1dfb98771f0e8de20c07ae5f2ded95` (RC5a approved) |
| Branch | `fix/vmq-mem-rc6a` |
| Contract | `08851280e` — `corrective-contract-2026-11-23.md`, §5.3 |
| Product files | `services/database.py`, `services/mca_retrieval_context.py` |
| Test | `tests/test_vmq_mem_rc6a_persona_card.py` |
| Probe | `evidence/vmq-mem/rc6a/rc6a_probe.py` + `rc6a-snapshot.json` |
| Test log | `evidence/vmq-mem/rc6a/tests.txt` |
| Diff | `evidence/vmq-mem/rc6a/candidate.diff` |

Не менялись: `summary_memory.py`, `mca_episodes.py`, `direct_chat_service.py`,
DDL/migrations, ACL/UI/embedding, store/quotas, thresholds/E1, map/status,
`progress_scope.json`/`workflow_state.md`.

## 2. C2 — facts metadata

`DatabaseService.get_persona_card` now selects `message_timestamp`, `created_at`,
`subject_ref_id`, `tg_message_id` in addition to `fact`:

- `facts` remains the **same list of strings in the same order** (existing
  formatters/consumers unchanged);
- parallel `facts_meta` has the same order, each item:
  `{fact, message_timestamp, created_at, source_ref_id, tg_message_id}`;
  `source_ref_id` is the fact's existing stable `subject_ref_id` (no new column
  and no invented source);
- legacy `message_timestamp=NULL` remains NULL/`created_at` fallback as stored;
- read-only, no rewrite of existing rows.

## 3. C2 — alias/canon links

- `get_persona_card(..., alias_names=())` builds a bounded `IN` list from
  `name` + `alias_names`; exact `name` is always first, so exact-name behavior
  is preserved.
- `mca_retrieval_context._relations_projection` passes `query` + all
  `subject_names` as `alias_names` to `get_persona_card`; compatibility
  fallback retries old signatures without the new kwarg.
- No alias table/store/DDL; aliases are caller-provided read-path names.
- Exact node still works; alias-only node `леха вдовин` now finds links when
  `name="Леха"` has no exact user node.

## 4. Snapshot read-only

`snapshot-2.58.225.db`, `b907…`, `mode=ro&immutable=1`:

| Метрика | Exact `Леха` | `Леха` + alias `леха вдовин` |
|---|---:|---:|
| facts | 7 | 7 |
| facts_meta | 7 | 7 |
| order matches | true | true |
| known years | 2026 (7) | 2026 (7) |
| source_refs | 7 | 7 |
| tg sources | 6 | 6 |
| links | 0 | **20** |

Exact-name snapshot has no exact user node `Леха` (nodes are `леха вдовин` etc.),
so 0 is expected; exact-name path is covered by the fixture test with an exact
node. Alias path returns 20 links. No E1/threshold/current-state change.

## 5. Tests / checks

```
python -m pytest -q \
  tests/test_vmq_mem_rc6a_persona_card.py \
  tests/test_dossier_irony.py \
  tests/test_mca04a_provenance_round1027.py \
  tests/test_multilayer_extraction_round1021.py \
  tests/test_asap3_identity_aliases.py \
  tests/test_memory_unified_retrieval_06.py \
  tests/test_caps_tool_results.py \
  tests/test_direct_chat_relations_inject.py \
  tests/test_direct_chat_lore_inject.py \
  tests/test_memory_lookup_round1026.py \
  tests/test_mca07_retrieval_context_round1027.py \
  tests/test_memory_unified_retrieval.py \
  tests/test_mem_time_policy.py \
  tests/test_mem_time_natural_scenarios.py \
  tests/test_vmq_mem_rc5a_fact_durability.py \
  tests/test_vmq_mem_rc4_short_stem.py \
  tests/test_vmq_mem_rc2_message_rank.py \
  tests/test_vmq_mem_rc3_period_slots.py \
  tests/test_mca05_episodes_stories_round1027.py \
  tests/test_vmq_m1_episode_contract.py \
  tests/test_p0_old_lore_quarantine.py \
  tests/test_direct_chat.py \
  tests/test_history_isolation.py
728 passed
```

`py_compile` — exit 0; `git diff --check` — exit 0; snapshot probe — exit 0.
Focused `test_vmq_mem_rc6a_persona_card.py`: 3 passed (facts/order/metadata,
exact + alias links, `_relations_projection` alias pass-through, threshold
constant unchanged).

## 6. Remaining / RFL

- Existing 598/6810 world rows and card thinness remain RC5b/RC6a scope
  boundaries; no backfill or rewrite.
- Card years on snapshot are 2026 (created_at); legacy `message_timestamp=NULL`
  is honest, not invented.
- E1 subject-threshold explicitly excluded; `PERIOD_MIN_SHARED_STEMS=2` unchanged.
- Current-state query path untouched; no E1/threshold changes.
- `VMQ-MEM-02/03/04` remain REVIEW; no VERIFIED.
- No deploy/SSH/LLM; no map/progress/workflow edits.

## 7. Hygiene

Probe JSON contains counts/names only, no fact texts. Temporary diagnostics
outside evidence removed. Candidate SHA — HEAD `fix/vmq-mem-rc6a` at handoff;
product diff — `candidate.diff` against `4828f30a9`.
