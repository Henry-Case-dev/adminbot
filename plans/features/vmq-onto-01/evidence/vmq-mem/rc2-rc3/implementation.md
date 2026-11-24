# VMQ-MEM-RC2+RC3 (D3+D2) — implementation evidence (2026-11-23)

Статус: **candidate for independent Reviewer**, не VERIFIED и не product-code
approval. `VMQ-MEM-02/03/04` остаются REVIEW. RC1 (`a5fee8c7d`,
`services/mca_episodes.py`) в этот инкремент не входит и не менялся.

## 1. Lineage / scope

| Что | Значение |
|---|---|
| Base | `b81ec52aa4834896c8e901269e69058612ae81bf` (2.58.238) |
| Branch | `fix/vmq-mem-rc2-rc3` |
| Contract | `08851280e` — `corrective-contract-2026-11-23.md`, §4.2/§4.3 |
| Files | `services/mca_retrieval_context.py`, `services/direct_chat_service.py`, `services/database.py` (bounded helper) |
| Tests | `tests/test_vmq_mem_rc2_message_rank.py`, `tests/test_vmq_mem_rc3_period_slots.py` |
| Probes | `evidence/vmq-mem/rc2-rc3/rc2_probe.py`, `rc3_probe.py` + JSON |
| Diff | `evidence/vmq-mem/rc2-rc3/candidate.diff` |
| Test log | `evidence/vmq-mem/rc2-rc3/tests.txt` |

Не менялись: `services/mca_episodes.py`, DDL/ACL/UI/embedding, новый store,
квоты/годовые доли, `progress_scope.json`, `workflow_state.md`, map/status.
Один retrieval-движок: explicit-year message-rank идёт через `retrieve()` +
новый bounded DB-helper; прямого обхода `retrieve` нет.

## 2. RC2 (D3) — explicit-year message rank

- `RetrievalRequest.lexical_window_rank: bool = False` — аддитивное поле;
  default сохраняет прежний `order="time"` byte-identical.
- `_build_old_episodes` при explicit year ставит `lexical_window_rank=True`;
  `stats["year_window_order"]="rank"`.
- `retrieve` для этого режима:
  - narrow content-match: 4-значный год, годовые слова и служебные
    предлоги/местоимения исключены (`_explicit_year_message_keywords`);
  - match требует co-occurrence минимум двух content-основ (OR по парам
    `("stem1"* AND "stem2"*)`), чтобы короткие сообщения с одним словом не
    забивали rank;
  - year-window делится на bounded chunks (`_window_chunks`, 4);
  - `DatabaseService.search_messages_fts_ranked_window`: bounded time-index
    candidate cap (`m.id IN (SELECT rowid FROM smart_messages_fts MATCH ?)` +
    `ORDER BY m.timestamp DESC LIMIT cap`), затем FTS `rank` только для
    candidate rowid; финальный порядок — rank, не time.
- Full rank-скан года не выполняется; candidate pool честно ограничен
  `candidate_cap` (sampling).

Snapshot `snapshot-2.58.225.db` (`b907…`, read-only):

| Метрика | Old `order="time"` | New rank window |
|---|---:|---:|
| 60823 position | absent | **2** |
| 60823 in top8/top16 | false / false | **true / true** |
| years | 2025 | 2025 |
| latency | 2 502 ms | **99.7 / 99.8 / 101.7 ms** (3 runs) |

`rc2-snapshot.json`: `old_target_absent=true`, `new_target_top8=true`,
`new_target_top16=true`, `new_years_2025_only=true`. December-only messages
(`в 2025 году…`) не входят в новый match; 2024/2026 исключены окном.
Unit `test_rc2_*`: RED old target absent; GREEN target top8; December not
selected; 2024/2026 absent; service `_build_old_episodes` uses rank window.

## 3. RC3 (D2) — explicit-year base/slots

- `_rag_unified_rows` вычисляет `period_intent` один раз; explicit-year base
  фильтруется по целевому году до append. Out-of-year/unknown-year строки не
  доставляются, если target-материал существует.
- Если target-материала нет ни в base, ни в period-пуле, сохраняется прежний
  base как honest missing-information fallback (существующий S7), а не
  выдуманный год.
- Period slots для explicit year — ресурсная ёмкость `limit - len(target base)`
  (или `limit` при fallback-проверке), не `limit//5` и не годовая доля.
  Глобальный `_RAG_PERIOD_SLOT_DIV` не менялся.
- `period_message_candidates` / `_used` / `_reason` пишутся в
  `_rag_period_stats`; message-кандидаты не выбрасываются молча
  (`fact_only_consumer`).
- Explicit-year profile append отключён, чтобы не добавить out-of-year факты.
- Current-state (`operative`/без explicit year) остаётся свежим; текущая
  ветка `current` не запускается при explicit year.

Snapshot `snapshot-2.58.225.db` (read-only, real MemoryManager FTS fallback):

| Метрика | Explicit 2025 | Current-state control |
|---|---:|---:|
| rows | 12 | 12 |
| years | **2025:12** | **2026:12** |
| `base_out_of_year_dropped` | 10 | 0 |
| `base_out_of_year_candidates` | 10 | 0 |
| `breadth_cap` | 10 | 2 |
| `period_message_candidates` | 12 | 16 |
| `period_message_candidates_reason` | `fact_only_consumer` | `fact_only_consumer` |
| latency | 1 434 ms | — |

`rc3-snapshot.json`: all pass true. Fact-block 12/12 — 2025; target message
60823 не является graph_fact, поэтому в fact-блоке его нет; он доставляется
как message-anchor через RC2 `<Old_Episode>` (см. `rc2-snapshot.json`).

## 4. Tests / checks

```
python -m pytest -q \
  tests/test_vmq_mem_rc2_message_rank.py \
  tests/test_vmq_mem_rc3_period_slots.py \
  tests/test_mca07_retrieval_context_round1027.py \
  tests/test_mca05_episodes_stories_round1027.py \
  tests/test_mem_time_natural_scenarios.py \
  tests/test_mem_time_policy.py \
  tests/test_memory_unified_retrieval.py \
  tests/test_vmq_m1_episode_contract.py \
  tests/test_p0_old_lore_quarantine.py \
  tests/test_direct_chat.py \
  tests/test_history_isolation.py
408 passed
```

`py_compile` — exit 0. `git diff --check` — exit 0. Snapshot probes — exit 0.
`test_mem_time_natural_scenarios.py::test_s7_missing_information_is_honest`
preserved via fallback; current-state tests remain green.

## 5. Remaining / RFL

- **RFL-1:** vector leg unavailable (`compat_not_proven`); RC2 uses message
  FTS/rank, RC3 uses existing FTS fallback. Full KNN path not certified.
- **RFL-2:** L1 `memory_scope`/`response_act` and Writer/Telegram not observed.
- **RFL-3:** snapshot 2.58.225 < deployed 2.58.238 and 2.58.230 embeddings fix;
  final re-measure on fresh 2.58.236+ snapshot.
- **RFL-8:** latency measured on local read-only snapshot, p50 ~100 ms for
  RC2; full production Writer block budget not measured.
- **B/D rows remain REVIEW.** RC2 improves `<Old_Episode>` message anchor;
  RC3 improves explicit-year fact block. RC1/B2/RC7 and legacy bridge remain
  separate. VERIFIED не заявляется.
- No deploy/SSH/LLM/Telegram; no map/progress/workflow edits.

## 6. Hygiene

Probe scripts are in `evidence/vmq-mem/rc2-rc3/`; JSON contains only IDs,
years, counters and latency, no texts. Temporary files outside evidence were
removed. Candidate SHA — HEAD `fix/vmq-mem-rc2-rc3` at handoff; product diff —
`candidate.diff` against `b81ec52aa`.
