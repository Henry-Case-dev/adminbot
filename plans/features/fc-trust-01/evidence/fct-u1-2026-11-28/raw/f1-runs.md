# FCT-U1-R1-F1 corrective — exact commands, file lists, results

Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\fc-trust-01-u1-3f69efb80e96-d491fedf`
Python: `C:\Code\Python\adminbot\.venv\Scripts\python.exe` (3.12.0, pytest 9.1.1)
Fix commit: `0fc7201ea` (parent `45313f3fb`, base `a2195fe3f`).
cwd для всех команд — корень worktree; `$env:PYTHONPATH` для probe — этот же корень.

## 1. Repro probe (`raw/probe_f1_repro.py`)

```
& $py plans/features/fc-trust-01/evidence/fct-u1-2026-11-28/raw/probe_f1_repro.py
```

| Прогон | Файл | Результат |
|---|---|---|
| до правки (кандидат `45313f3fb`) | `raw/probe-f1-before.txt` | все amount-кейсы `qualifies/indirect` + `time:year_conflict`, merged `insufficient_evidence`, `gap_note=""` |
| база `a2195fe3f` (`git checkout a2195fe3f -- services/search_aggregator.py`) | `raw/probe-f1-base.txt` | все кейсы `supports/direct`, merged `supported` (на базе year conflict отсутствует) |
| после правки (`0fc7201ea`) | `raw/probe-f1-after.txt` | amount-кейсы `supports/direct`, merged `supported`; `amount_plus_other_year` и `real_other_year` — `qualifies/indirect` + `time:year_conflict` |

## 2. Тесты (кандидат `0fc7201ea`)

| # | Команда | Результат | Файл |
|---|---|---|---|
| 1 | `pytest tests/test_fc_trust_relation_binding.py -q` | **32 passed** | `raw/green-f1-new-tests.txt` (перезаписан, 32) |
| 2 | `pytest tests/test_fc_trust_assertion_kind.py tests/test_fc_trust_relation_binding.py -q` | **51 passed** | `raw/green-f1-u1-51.txt` |
| 3 | `pytest tests/test_fc_trust_s1_contract.py tests/test_fc_trust_retrieval.py tests/test_fc_trust_verdict.py tests/test_fc_trust_render.py tests/test_fc_trust_assertion_kind.py tests/test_fc_trust_relation_binding.py -q` | **207 passed** | `raw/green-f1-focused-207.txt` |

### Широкий прогон (F3: точная команда и список файлов)

Полный список 62 файлов (фильтр имён `factcheck|search|voice|trust|temporal` по `tests/*.py`) —
`raw/broad-f1-files.txt`. Единый прогон всех 62 файлов дважды прерывался перезапуском сервера
инструментов (не падением тестов), поэтому выполнен четырьмя последовательными частями; каждая
часть — свой сохранённый список файлов и свой сырой вывод:

| Часть | Список файлов | Команда | Результат | Сырой вывод |
|---|---|---|---|---|
| 1 (1–16) | `raw/broad-f1-part1-files.txt` | `pytest @part1 -q` | 384 passed, **1 failed** | `raw/green-f1-broad-part1.txt` |
| 2 (17–32) | `raw/broad-f1-part2-files.txt` | `pytest @part2 -q` | 337 passed | `raw/green-f1-broad-part2.txt` |
| 3 (33–47) | `raw/broad-f1-part3-files.txt` | `pytest @part3 -q` | 381 passed | `raw/green-f1-broad-part3.txt` |
| 4 (48–62) | `raw/broad-f1-part4-files.txt` | `pytest @part4 -q` | 404 passed, **2 failed** | `raw/green-f1-broad-part4.txt` |

Итого: **1506 passed, 3 failed**. Все три падения — предсуществующие и совпадают с независимым
прогоном ревью r1 §3.3 (49 файлов, 1120/3):

* `tests/test_asap_fc_voice_l1_decision_profile.py::test_direct_service_l1_payload_gets_profile_from_turn_frame`
  (`_Stub._l1_reply_block()` не принимает `preserve=True`);
* `tests/test_selfdiag_corrective_research.py::TestContinuationContext::test_continuation_plan_uses_real_ledger_report_and_reads_code`;
* `tests/test_selfdiag_corrective_research.py::test_direct_l1_addendum_and_outage_keeps_previous_decision`.

## 3. Мутации (каждая — на `0fc7201ea`, откат `git checkout HEAD -- services/search_aggregator.py`)

| # | Мутация | Результат | Файл |
|---|---|---|---|
| A | `_year_conflict`: `return False` в начале (year conflict выключен) | **6 failed, 45 passed**: `test_passage_of_another_year_is_not_support`, 3× `test_any_other_year_is_a_conflict`, `test_planner_wrapper_passes_claim_timeframe`, **+ новый** `test_amount_and_real_other_year_still_conflict` | `raw/mutation-f1-a-no-year-conflict.txt` |
| B | `_explicit_years`: убрать фильтр `if not _year_is_quantity(...)` (старое поведение U1) | **5 failed, 46 passed**: 4 параметра `test_amount_instead_of_year_behaves_like_no_year` + `test_amount_instead_of_year_keeps_supported_verdict` | `raw/mutation-f1-b-amounts-as-years.txt` |

## 4. RED на базе `a2195fe3f`

```
git checkout a2195fe3f -- services/search_aggregator.py
pytest tests/test_fc_trust_relation_binding.py -q
git checkout HEAD -- services/search_aggregator.py
```

Результат: **6 failed, 26 passed** (`raw/red-f1-new-tests-on-base.txt`). Честная интерпретация:
новые amount-кейсы на базе **проходят** — они проверяют именно паритет с поведением «без года»
(на базе year conflict отсутствует вовсе). RED на базе даёт только кейс «сумма + реальный другой
год» (и четыре прежних conflict-теста U1), т.е. новая функциональность отличается от базы ровно
там, где должна.

## 5. Границы правки

`git show --stat 0fc7201ea` — 3 файла: `services/search_aggregator.py` (+36/−3),
`tests/test_fc_trust_relation_binding.py` (+54), `plans/backlog.md` (+8). `factcheck_service.py`,
`temporal_factcheck.py`, рендер, DDL, флаги, `prompt_registry.py` не тронуты. Полный
`git diff --name-status a2195fe3f 0fc7201ea` — `raw/scope-f1.txt` (остальные строки — исходный
U1-коммит `324923b19`, не этот corrective).
