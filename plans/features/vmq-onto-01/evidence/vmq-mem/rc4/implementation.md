# VMQ-MEM-RC4 (A2+D4) — implementation evidence (2026-11-23)

Статус: **candidate for independent Reviewer**, не VERIFIED и не product-code
approval. `VMQ-MEM-02/03/04` остаются REVIEW. RC1/RC2+3 не переписываются;
base — одобренный `3d33b15f9`.

## 1. Lineage / scope

| Что | Значение |
|---|---|
| Base | `3d33b15f912585b75f66f10eed29d6a69f1fc406` (RC2+RC3 candidate) |
| Branch | `fix/vmq-mem-rc4` |
| Contract | `08851280e` — `corrective-contract-2026-11-23.md`, §5.1 |
| Product files | `services/text_morphology.py`, `services/mca_retrieval_context.py`, `services/summary_memory.py` |
| Tests | `tests/test_vmq_mem_rc4_short_stem.py`; affected `test_vmq_mem_slice_d.py` expectation for A1P (RC4 strict subject) |
| Probe | `evidence/vmq-mem/rc4/rc4_probe.py` + `rc4-snapshot.json` |
| Test log | `evidence/vmq-mem/rc4/tests.txt` |
| RED log | `evidence/vmq-mem/rc4/red.txt` (RC4-R1-01 before fix) |
| Diff | `evidence/vmq-mem/rc4/candidate.diff` |

Не менялись: DDL/ACL/UI/embedding, new store/queue/quotas, `progress_scope.json`,
`workflow_state.md`, map/status. RC1/RC2+3 product files не переписаны.

## 2. A2 — retrieval-only short stem

- `text_morphology.short_stem_word(word)` — additive helper; global
  `stem_word`/min-stem 4 не изменены. `шизах`/`шизы` → `шиз`; `шиз` → `шиз`;
  `год`/`чат` stems blocked; `2025`/4-char `годы`/`году`/`чата` не дают
  short variant.
- `period_subject_stems` использует **одну альтернативную** нормализацию:
  short stem вместо обычной основы, не два stem одновременно. Поэтому одно
  слово не может дать два «общих» стема и обойти порог 2.
- `period_subject_shared(..., explicit_year=...)` and `period_subject_stems`
  use the same normalization; threshold `PERIOD_MIN_SHARED_STEMS=2` and
  soft-fallback condition not changed.
- `build_fts_query(..., mode="prefix_or_stem_short")` — additive mode;
  default `prefix_or` and `prefix_or_stem` unchanged. Period retrieval uses
  the additive mode; non-period callers remain byte-identical.

Snapshot `snapshot-2.58.225.db` (read-only; facts, full A1 period match):

| Метрика | Old | New |
|---|---:|---:|
| `шизах` matching facts | **2** | **103** |
| shared≥2, pool 32 | 1 | **4** |
| shared≥2, pool 64 | 1 | **5** |
| years in new pool 64 | — | 2023/2024/2025/2026 |
| accepted old under historical | — | **2024:1** (2026:3; no 2023/2025 in top selection) |

`шизах` 2026 does not replace the old fact: 2024 is accepted. The contract's
5/7 figure counts normal+short variants of the same word twice; this
implementation intentionally uses one normalization to preserve threshold
semantics (and existing A1P regression). The stronger invariant — 103 facts,
old year accepted, no E noise — is met.

E-control: `short_stem_word("годы")==""`, `short_stem_word("чата")==""`;
`period_subject_stems("...чата...годы...")` keeps `годы`/`чата`, does not add
`год`/`чат`; `build_fts_query` short mode contains no `"год"*`/`"чат"*`.

### 2.1. RC4-R1-01 corrective (stopword short-stem bypass)

Reviewer blocker: non-explicit `period_subject_stems` applied `short_stem_word`
to service 3-char tokens (`что/для/меня`), so unrelated facts shared those
short stems and bypassed the `>=2` threshold.

- **Repro:** query `что было для меня?`; facts
  `что было для меня и работа` and `что было для тебя`.
- **Before:** `strict=2`, `dropped=0` (unrelated `тебя` accepted).
- **After:** `strict=1`, `dropped=1`; only the matching fact accepted.
- **Fix:** `_MESSAGE_WINDOW_STOPWORDS` are excluded from short-normalization
  before it runs; their normal len>=4 stem (e.g. `меня`) remains for
  distinguishing subjects. Short variant is content-only; one-normalization,
  threshold `2` and soft-fallback condition unchanged.
- RED/GREEN: `red.txt` — падение на старом behavior; focused 6/6, full 699.

## 3. D4 — year tokens out of explicit-year content match

- `_period_fts_keywords(..., explicit_year=True)` removes 4-digit year,
  year words (`год/года/году/годы/годов/...`) and service prepositions;
  non-explicit path keeps old behavior.
- Explicit D query: old keywords
  `[известно, конфликте, корсара, олей, 2025, году]`; new —
  `[известно, конфликте, корсара, олей]`. Old match has `"2025"*`/`"году"*`,
  new match does not.
- Explicit `retrieve` window: 32 candidates, **all 2025**, `has_2024=false`,
  `has_2026=false`.
- Current-state/no-year path keeps base fresh: `test_rc3_current_state_stays_fresh`
  and S7 pass; RC4 changes only explicit/year-token FTS.

## 4. Tests / checks

```
python -m pytest -q \
  tests/test_vmq_mem_rc4_short_stem.py \
  tests/test_vmq_mem_rc2_message_rank.py \
  tests/test_vmq_mem_rc3_period_slots.py \
  tests/test_mca07_retrieval_context_round1027.py \
  tests/test_mca05_episodes_stories_round1027.py \
  tests/test_mem_time_natural_scenarios.py \
  tests/test_mem_time_policy.py \
  tests/test_memory_unified_retrieval.py \
  tests/test_vmq_m1_episode_contract.py \
  tests/test_p0_old_lore_quarantine.py \
  tests/test_mca15_chat_statistics_round1028.py \
  tests/test_vmq_mem_slice_d.py \
  tests/test_memory_period_vector_leg.py \
  tests/test_summary_memory.py \
  tests/test_belief_decay.py \
  tests/test_mca22_truthset_round1027.py \
  tests/test_direct_chat.py \
  tests/test_history_isolation.py
699 passed
```

`py_compile` — exit 0; `git diff --check` — exit 0. Snapshot probe — exit 0.

Affected expectation update: `test_vmq_mem_slice_d::test_a1p_historical_vs_auto`
now expects `2024:1 + 2026:9` because `шизах` is a strict subject match and
soft-fallback no longer adds unrelated `конфа` 2023; auto remains 2026:10.
This is the RC4 intent, not a threshold change.

## 5. Remaining / RFL

- **RFL-1:** vector leg unavailable; probes/RC2/RC3 FTS fallback only.
- **RFL-2:** L1 `memory_scope`/`response_act`, Writer/Telegram not observed.
- **RFL-3:** snapshot 2.58.225 < deployed 2.58.238 / 2.58.230 embeddings fix.
- A2 shared counts are pool-dependent: 4/32 and 5/64 under one-normalization;
  contract's 5/7 double-count variant is intentionally not used.
- D4 explicit-year fact block still has no graph_fact 60823; message anchor is
  delivered by RC2 `<Old_Episode>`, not RC3 fact block.
- `VMQ-MEM-02/03/04` remain REVIEW; no VERIFIED. RC5/RC6/RC7 separate.
- No deploy/SSH/LLM; no map/progress/workflow edits.

## 6. Hygiene

Probe JSON contains only IDs/years/counters, no texts. Temporary diagnostics
outside evidence removed. Candidate SHA — HEAD `fix/vmq-mem-rc4` at handoff;
product diff — `candidate.diff` against `3d33b15f9`.
