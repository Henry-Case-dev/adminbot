# M5A — закрытие 3 REVIEW строк (2.58.237, 2026-11-23)

Срез `mod-acl-ux-01` M5A: строки `MAC-S7-392` (`M5A-R1-02`), `MAC-S15-06`
(`M5A-R1-03`), `MAC-S7-LIMIT-01` (`M5A-R1-04`). Base — выкаченный
2.58.237 `f40402660`; ветка `fix/m5a-review-rows-2.58.237`; кандидат
`0907dbae6` (worktree
`WorkspaceData/worktrees/c742e4de9e92c489/mod-acl-ux-01-m5a-review-rows-64ac96e3def4-40d3ad51`).

Один writer: `services/experience_diagnostics.py` (API-витрина, read-only
поля) + M5A test/evidence. `services/mca_experience_jobs.py` (M5B), ACL/UI/
embedding/DDL, `progress_scope.json`, `workflow_state.md` не изменялись.
Deploy/SSH/LLM/prod не выполнялись.

## 1. Строки

| Строка | Finding | Что сделано | Тест |
|---|---|---|---|
| `MAC-S7-392` | `M5A-R1-02`: `learning_analytics.fresh_lag` не отдаёт `stage_status/partial/partial_reasons`; `semantic_batches_run` только в payload | API-витрина `fresh_lag` отдаёт 4 поля из того же durable payload (без изменения поведения обучения) | `test_api_learning_analytics_exposes_semantic_stage` |
| `MAC-S15-06` | `M5A-R1-03`: `test_h` — 1 detector-detected, не «3 verified кандидата» | Новый детерминированный сценарий: 3 РАЗНЫХ preference-кандидата (3 ключа), LLM unavailable → cursor 0, ничего не записано; resume → 3 durable feedback + 3 активных урока; повтор без дублей. Product code не потребовался | `test_s15_06_three_verified_candidates_stall_then_resume` |
| `MAC-S7-LIMIT-01` | `M5A-R1-04`: проверялись `proposed=0/lessons=0`, но не durable `mca_experience_feedback`/hypotheses | Тест дополнен durable-assert: 2 строки `source_kind='llm_hypothesis'`, `kind` = `strategy_success`/`topic_pattern`, `class=observation`, темы `weather`/`weekend`, уроков нет. Product code не потребовался | `test_strategy_success_topic_pattern_not_promoted_to_lessons` |

## 2. Код (14 строк, только API-витрина)

`_learning_analytics` (`services/experience_diagnostics.py`):

- `fresh_lag.stage_status` ← `semantic_progress.stage_status`, отсутствие
  снимка → `"unknown"` (не «completed»);
- `fresh_lag.partial` ← `semantic_progress.partial`;
- `fresh_lag.partial_reasons` ← список кодов причин;
- `fresh_lag.semantic_batches_run` ← durable `counters.semantic_batches_run`
  последнего review-job'а.

Поведение обучения/гейтов/порогов не менялось; поля read-only и не
дублируют источник: значения берутся из того же payload, который читает
`experience_pipeline_snapshot` (route `GET /api/experience/pipeline`,
`web/api/routes.py:7018-7019`).

## 3. RED / GREEN

RED (base `f40402660`, до product-правки):

```
FAILED test_api_learning_analytics_exposes_semantic_stage
  KeyError: 'stage_status'                     # fresh_lag без новых полей
```

Тесты строк 2–3 на базе проходят (поведение уже корректно — это были
пробелы доказательств, не дефекты); их различающая сила доказана
мутациями §4. Первая версия нового теста падала на `KeyError
'semantic_cursor:-100'`: при `llm=None` ключ курсора ещё не создан —
assert заменён на честное `.get(..., 0) == 0` (отсутствие = позиция 0).

GREEN (кандидат `0907dbae6`):

```
pytest tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py -q
24 passed

pytest <20 related experience/lesson/diagnostics files> -q \
  -k "not deep_sleep_not_mixed_with_lessons"
356 passed, 1 deselected
```

## 4. Мутации (реальный файл, восстановлен после каждой)

| # | Мутация | Убийца |
|---|---|---|
| M1 | `fresh_lag.stage_status` жёстко `"completed"` | `test_api_learning_analytics...`: `assert 'completed' == 'unavailable'` |
| M2 | при `llm is None` курсор чата ставится на `MAX(id)` (пропуск данных) | `test_h...` и `test_s15_06...`: `assert 3 == 0` |
| M3 | observation-кандидат пишется как `participant_correction` | `test_strategy_success...`: `proposed == 1` (гипотеза стала кандидатом в урок) |
| M4 | в signal для observation `kind` подменяется на `strategy_success` | новый durable-assert: `['strategy_success','strategy_success'] != ['strategy_success','topic_pattern']` |

После восстановления: `git status` чист, `git diff --check` exit 0.

## 5. Проверки

- `py_compile` (product+test): 0.
- `git diff --check`: 0.
- Plan gate: `stage=plan inventory=279 manual=102 scoped=0 errors=0`.
- Focused suite: 356 passed, 1 deselected.
- Pre-existing failure `tests/test_mca16_experience_block_d_round1039.py::
  test_deep_sleep_not_mixed_with_lessons` воспроизведён на base
  `f40402660` (статический assert `'graph_facts' not in <docstring>`,
  строка 310); в release evidence 2.58.237 он уже deselected — не связан с
  этим кандидатом.

## 6. Границы

- Это кандидат и evidence для независимого re-review; статус `VERIFIED`
  Builder не присваивает. Строки остаются `REVIEW` до вердикта Reviewer.
- `MAC-M5-01` остаётся PENDING (M5B/M5C), не затрагивался.
- Deploy/SSH/LLM/prod/live-наблюдений нет; DDL/ACL/UI/embedding нет.
- Map/`progress_scope.json`/`workflow_state.md` не редактировались;
  per-row артефакты (`mac-s7-392.md`, `mac-s15-06.md`,
  `mac-s7-limit-01.md`) созданы по `expected_evidence`.

## 7. Команды

```powershell
git worktree add <WorkspaceData>/worktrees/.../mod-acl-ux-01-m5a-review-rows-... -b fix/m5a-review-rows-2.58.237 f40402660
pytest tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py -q
pytest <20 related files> -q -k "not deep_sleep_not_mixed_with_lessons"
python -m py_compile services/experience_diagnostics.py tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py
git diff --check
requirements_gate.py check --map plans/features/mod-acl-ux-01/requirements-map.json --stage plan
```
