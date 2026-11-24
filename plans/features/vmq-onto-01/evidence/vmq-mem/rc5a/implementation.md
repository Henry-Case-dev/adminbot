# VMQ-MEM-RC5a (C1, producer-only) — implementation evidence (2026-11-23)

Статус: **candidate for independent Reviewer**, не VERIFIED и не product-code
approval. `VMQ-MEM-02/03/04` остаются REVIEW. RC5a меняет только **новые
записи**; существующие 598/6810 `world_knowledge`-строк не переписываются
(RC5b — отдельное решение).

## 1. Lineage / scope

| Что | Значение |
|---|---|
| Base | `385e9b091628f6ce4d770c97de7b37cf2ae814c9` (RC4 approved) |
| Branch | `fix/vmq-mem-rc5a` |
| Contract | `08851280e` — `corrective-contract-2026-11-23.md`, §5.2 |
| Product file | `services/summary_memory.py` (producer only) |
| Test | `tests/test_vmq_mem_rc5a_fact_durability.py` |
| Probe | `evidence/vmq-mem/rc5a/rc5a_probe.py` + `rc5a-snapshot.json` |
| RED log | `evidence/vmq-mem/rc5a/red.txt` |
| Test log | `evidence/vmq-mem/rc5a/tests.txt` |
| Diff | `evidence/vmq-mem/rc5a/candidate.diff` |

Не менялись: `mca_episodes.py`, `mca_retrieval_context.py`,
`direct_chat_service.py`, `database.py`/DDL, ACL/UI/embedding, card/links
(RC6a), thresholds, map/status, `progress_scope.json`/`workflow_state.md`.

## 2. Producer change

- `fact_durability_decision` добавляет аддитивный `nonpersonal_kind` для
  явных `world_news`/`quote`; durable-факт без этого маркера больше не
  считается «явно world» на уровне producer.
- `_attach_fact_provenance` получает `nonpersonal_kind` и после резолва
  `subject_ref_id`:
  - если `method == "world_knowledge"`, `subject_ref_id` resolved и
    `nonpersonal_kind` пуст — запись переводится в `third_party` (или
    `self_report`, если speaker совпал с субъектом), `assertion_kind =
    "biographical"`;
  - явный `world_news`/`quote` (`nonpersonal_kind` заполнен) сохраняет
    world/quote-атрибуцию;
  - `provenance=OFF`, bot-origin, unresolved subject — без изменений.
- `target_user`/subject_ref/fact content не переписываются; меняются только
  attribution/assertion columns новой строки через существующий
  `record_fact_provenance`/`update_fact_provenance_columns`.
- Никакого UPDATE существующих 598/6810 строк, backfill или migration.

## 3. Acceptance

Unit/integration (`tests/test_vmq_mem_rc5a_fact_durability.py`):

- `fact_durability_decision`:
  - durable `subject_type=world` → `nonpersonal_kind=""`;
  - `world_news` → `world_news`;
  - `quote` → `quote`.
- New persisted fact `chat_history`, subject `Леха`, `subject_ref_id` resolves:
  - before fix: `attribution_method=world_knowledge`;
  - after fix: `third_party`/`self_report`, `assertion_kind != world_knowledge`,
    `subject_ref_id` non-null.
- Explicit `nonpersonal_kind="world_news"`: new fact remains
  `world_knowledge/world_knowledge`.
- Existing legacy row with `world_knowledge/world_knowledge` is unchanged
  after attaching a new fact.

Snapshot read-only (`snapshot-2.58.225.db`, `b907…`, mode=ro&immutable=1):

| Метрика | Значение |
|---|---:|
| confirmed facts | 32 133 |
| subject_ref confirmed | 6 909 |
| subject_ref world_knowledge | **6 810** |
| Леха ref confirmed | 611 |
| Леха ref world_knowledge | **598** |

`subject_ref_world_unchanged=true`, `leha_world_unchanged=true`,
`no_rewrite_path=true`.

## 4. Tests / checks

```
python -m pytest -q \
  tests/test_evol006_fact_quality.py \
  tests/test_mca04a_provenance_round1027.py \
  tests/test_summary_memory.py \
  tests/test_memory_unified_retrieval.py \
  tests/test_mem_time_policy.py \
  tests/test_mem_time_natural_scenarios.py \
  tests/test_mca22_truthset_round1027.py \
  tests/test_belief_decay.py \
  tests/test_vmq_mem_rc5a_fact_durability.py \
  tests/test_vmq_mem_rc4_short_stem.py \
  tests/test_vmq_mem_rc2_message_rank.py \
  tests/test_vmq_mem_rc3_period_slots.py \
  tests/test_mca07_retrieval_context_round1027.py \
  tests/test_mca05_episodes_stories_round1027.py \
  tests/test_vmq_m1_episode_contract.py \
  tests/test_p0_old_lore_quarantine.py \
  tests/test_direct_chat.py \
  tests/test_history_isolation.py
635 passed
```

`py_compile` — exit 0; `git diff --check` — exit 0; snapshot probe — exit 0.

## 5. Remaining / RFL

- Existing 598/6810 rows are **not** rewritten; card years/links remain RC6a,
  C row remains REVIEW.
- The producer override uses `subject_ref_id` resolution; if a fact's subject
  is unresolved/ambiguous, it stays world (honest unknown), not personal.
- World/news/quote remain world/quote; no topic dictionary or new classifier.
- RC5a is new-write-only; RC5b is a separate data/read-path decision.
- No deploy/SSH/LLM; no `progress_scope.json`/`workflow_state.md` edits.

## 6. Hygiene

Probe JSON contains counts only; no fact texts. Temporary diagnostics outside
evidence removed. Candidate SHA — HEAD `fix/vmq-mem-rc5a` at handoff; product
diff — `candidate.diff` against `385e9b0916`.
