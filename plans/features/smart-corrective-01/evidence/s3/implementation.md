# SMART-CORRECTIVE-01 — S3-BUDGET implementation evidence

Статус: **REVIEW** (кандидат для независимого ревью; не VERIFIED).
Дата: 2026-11-14.

## Идентичность кандидата

- Epic: `smart-corrective-01`, срез `S3-BUDGET`.
- Базовая линия: `release/2.58.200` @ `13884daa32e5cf2a1c05c5c43188ca299f8179f8`
  (код = deployed `0e4a144db476a1535ae3a2b79a7cce30354ad866`).
- Ветка среза: `sc/corrective-s3`.
- Code candidate commit: `0577019b651fcd7eb226003810445d5a6c9fdfea`
  (production-код + тесты; evidence-запись — отдельный коммит после него).
- Worktree:
  `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-8d0575b5`
  (managed `WorkspaceData/worktrees`, registered как `s3-budget`).

### Отклонение от буквальной базы (обосновано)

Брифинг предписывал `git worktree add ... release/2.58.200`. Ветка создана от
`sc/corrective-s1s2` @ `057b65c9` — **это та же release-линия**
(`git merge-base sc/corrective-s1s2 release/2.58.200` = `13884daa`), master
не участвует. Причина: deliverable 2 (контракт S1 — `outcome`/`progress_id`/
`continuation`) требует реального кода S1/S2, иначе проводка континуации была
бы мёртвой и недоказуемой. Diff среза:

- `git diff sc/corrective-s1s2...sc/corrective-s3` — только S3 (3 файла);
- `git diff release/2.58.200...sc/corrective-s3` — S1/S2 (`source_reader.py` +
  их тесты/evidence) и S3. Отдельного master-мусора нет.

## Изменённые файлы

Production (единственный файл):

- `services/tool_router.py` — `_budget_policy()`, передача `chat_id`/
  `budget_enforced`/`cursor` в `reader.run()`, reuse-контракт, наблюдаемость.

Тесты:

- `tests/test_smart_corrective_budget_policy.py` (new, 17 tests).
- `tests/test_tool_router.py` (+3 durable regressions: `_RecordingSourceReader`
  + `TestReadSourceCodeBudgetPropagation`).

Документ: этот файл.

`services/worker_budget.py` **не изменялся**: фоновый контур уже резолвит
политику через тот же мастер-флаг для своего scope
(`worker_budget.consume` → `budget_gate.budgets_enabled(_scope_chat_id(scope))`,
`services/worker_budget.py:364,374-381`). Второго механизма там нет, правка
ничего бы не исправила.

## Точный путь propagation (file:line, кандидат)

1. `ToolContext.chat_id` — область исполнения задачи
   (`services/tool_router.py:1296-1322`; конструируется на ход в
   `direct_chat_service`, `factcheck_service`, `handlers/checkup.py:244`).
2. `ToolRouter._budget_policy(ctx)` (`services/tool_router.py:3350-3383`):
   один резолв на контекст хода через существующий предикат
   `source_reader.budget_limits_enforced(scope)` (`:3371`) →
   `services.budget_gate.resolve_budgets` (chat override → global →
   заводской default). Кэш живёт в `ctx._tool_budget_policy` и инвалидируется
   при смене scope; ON/OFF нигде не хардкодится (нет chat_id → резолвер
   читается для `None`, глобальный слой).
3. `ToolRouter._read_source_code()` (`services/tool_router.py:3385-3634`):
   - политика читается ОДИН раз (`:3480`), cursor — как есть (`:3482`);
   - reuse не применяется к продолжению (`:3491-3492`, «already delivered
     page» не отдаётся повторно);
   - `reader.run(..., chat_id=chat_id, budget_enforced=bool(...), cursor=cursor)`
     (`:3517-3526`);
   - effective-политика пишется в out-of-band `ctx.evidence_limits`
     (`budgets_enforced`, `budget_scope_chat`, `budget_policy_failed`).
4. `SourceReader.run()` (`services/source_reader.py:2575-2581`) принимает
   `chat_id`/`budget_enforced`/`cursor`; при явном `budget_enforced` предикат
   НЕ читается повторно (`:2622-2629`) — одна политика на вызов.
5. Fallback local→remote (`services/source_reader.py:2492-2520`) работает на
   том же `_RunState` → политика сохраняется (доказано spy-тестом).
6. Reuse: `_source_pointer` (`services/tool_router.py:3654-3697`) сохраняет
   `outcome/partial/query/operation/progress_id/idempotency_key/continuation/
   source_selection`; `_source_reuse_payload` (`:3754-3862`) возвращает их и
   provenance identity (`repo/commit/operation/outcome/progress_id`), т.е.
   повторный вызов не теряет исследование S1.

### Исходный дефект (deployed 0e4a144d)

- `release/2.58.200:services/tool_router.py:3463-3469` — `reader.run(...)` без
  `chat_id`/`budget_enforced` (и без `cursor`).
- `release/2.58.200:services/source_reader.py:2471,2487-2491` — читатель эти
  параметры принимал и при `None` резолвил `flags.budgets_enabled` без
  контекста чата.

## RED → GREEN

RED (те же 17 тестов на pre-fix `tool_router.py`:
`git checkout sc/corrective-s1s2 -- services/tool_router.py`, затем восстановление
`git checkout HEAD -- services/tool_router.py`):

```
py -3 -m pytest tests/test_smart_corrective_budget_policy.py -q
=> 10 failed, 7 passed
```

Падения: `test_global_off_reaches_reader`, `test_chat_off_overrides_global_on`,
`test_chat_on_overrides_global_off`, `test_no_chat_id_reads_resolver_for_global_scope`,
`test_policy_of_one_chat_is_not_used_for_another`,
`test_one_resolve_per_turn_and_reader_does_not_re_resolve`,
`test_router_has_no_second_budget_switch`,
`test_chat_off_ignores_operator_caps_through_router`,
`test_repeated_call_reuses_same_policy_and_identity`,
`test_cursor_is_forwarded_and_bypasses_reuse`. Причина ровно исходный дефект:
`reader.calls[-1]` не содержит `chat_id`/`budget_enforced`, cursor теряется,
env-потолки применяются к чату с OFF. Оставшиеся 7 — контракты, которые не
зависят от проводки (bounded failure, fuse, safety-guard, связанные контуры,
пустые слои → factory ON).

GREEN (кандидат `0577019b`):

```
py -3 -m pytest tests/test_smart_corrective_budget_policy.py -q
=> 17 passed
py -3 -m pytest tests/test_tool_router.py -q
=> 49 passed
py -3 -m pytest tests/test_tool_router.py \
  tests/test_smart_corrective_budget_policy.py \
  tests/test_budget_unlimited_round1019.py tests/test_evol_source_reader.py \
  tests/test_evol_evidence_window.py tests/test_smart_c1_source_reader_limits.py \
  tests/test_smart_corrective_source_reader.py tests/test_deploy_identity_d4b.py \
  tests/test_tool_loop.py tests/test_tool_chains_round1026.py \
  tests/test_checkup_service.py tests/test_checkup_contract.py \
  tests/test_selfdiag_corrective_research.py tests/test_smart_exec_selfdiag.py \
  tests/test_smart_exec_evidence.py tests/test_diagnostic_policy.py \
  tests/test_prompt_readback.py -q
=> 678 passed, 3 warnings
py -3 -m pytest tests/test_factcheck_service.py \
  tests/test_factcheck_tools_round1020.py tests/test_factcheck_tool_route_cfg06.py \
  tests/test_mca11_tool_result_round1028.py tests/test_mca11_chain_stages_round1028.py -q
=> 102 passed, 2 warnings
py -3 -m py_compile services/tool_router.py
=> OK
```

Предупреждения pytest — известный `Unknown config option: timeout` (плагин
timeout не установлен); на результат не влияют.

## Что именно проверяют тесты (кандидат)

Матрица effective policy (настоящий `budget_gate` с fake-слоями hot/chat_params,
spy снимает `_RunState.budget_enforced`/`limit_files/depth/requests` реального
`SourceReader`):

| Сценарий | Тест | Наблюдение |
|---|---|---|
| global OFF | `test_global_off_reaches_reader` | reader: OFF, limits 0 |
| пустые слои | `test_factory_default_on_reaches_reader` | reader: ON (factory default) |
| global ON + chat OFF | `test_chat_off_overrides_global_on` | DM-чат: OFF |
| global OFF + chat ON | `test_chat_on_overrides_global_off` | чат: ON |
| нет chat_id | `test_no_chat_id_reads_resolver_for_global_scope` | резолвер вызван с `None`, не хардкод |
| A OFF / B ON | `test_policy_of_one_chat_is_not_used_for_another` | [False, True, False] |
| nested/repeat | `test_one_resolve_per_turn_and_reader_does_not_re_resolve` | 1 резолв на ctx, Reader предикат не читает |
| fallback | `test_local_to_remote_fallback_keeps_policy` (OFF/ON) | политика сохранена на fallback |
| reuse | `test_repeated_call_reuses_same_policy_and_identity` | 0 сети, identity/continuation сохранены |
| continuation | `test_cursor_is_forwarded_and_bypasses_reuse` | cursor до Reader, reuse не затеняет |
| OFF vs env-квоты | `test_chat_off_ignores_operator_caps_through_router` | 10 файлов, limits 0 при env 1/1/1 |
| ON vs env-квоты | `test_on_applies_configured_caps` | limits 1/1/1, <10 файлов |
| безопасность | `test_off_keeps_security_guard` | denied-путь = permission_denied |
| OFF ≠ ∞ | `test_off_does_not_mean_infinite_execution` | bounded отказ + fuse независим |
| единый механизм | `test_router_has_no_second_budget_switch` | Router не импортирует `budget_gate` |
| связанные контуры | `test_chain_contours_use_same_resolver_with_chat_scope` | tool_loop/direct/worker: тот же флаг, свой chat scope |

Durable regressions исходного дефекта (`tests/test_tool_router.py`):
`test_chat_and_effective_policy_reach_reader[False/True]`,
`test_cursor_reaches_reader_and_bypasses_reuse`.

## Покрытие строк S3-BUDGET

| req_id | Статус кандидата | Доказательство |
|---|---|---|
| `SC-SEARCH-OFF` | REVIEW | `test_chat_off_ignores_operator_caps_through_router`: env-потолки 1/1/1 при OFF → 10 файлов, `applied_limits` zeros. |
| `SC-BUD-FIND-01` | REVIEW (подтверждение) | `release/2.58.200:services/source_reader.py:2471,2487-2491`: сигнатура принимает `chat_id`/`budget_enforced`; кандидат `source_reader.py:2575-2629`. |
| `SC-BUD-FIND-02` | REVIEW (подтверждение) | `release/2.58.200:services/tool_router.py:3463-3469` — вызов без параметров; RED-прогон на pre-fix коде (9 failed). |
| `SC-BUD-FIND-03` | REVIEW (подтверждение) | RED: `reader.calls` без `chat_id`/`budget_enforced` → политика резолвилась без чата. |
| `SC-BUD-FIX` | REVIEW | Путь propagation §1-6 выше; 17 новых тестов + 3 регрессии. |
| `SC-BUD-RESOLVER` | REVIEW | Тесты матрицы идут через настоящий `budget_gate`/`worker_settings` (chat → global → factory), не через подменённый булев флаг. |
| `SC-BUD-NOSECOND` | REVIEW | `test_router_has_no_second_budget_switch` (нет импорта `budget_gate` в Router) + `test_one_resolve_per_turn...` (один резолв, Reader не переопределяет). |
| `SC-BUD-CONTEXT` | REVIEW | `test_global_off_reaches_reader`, `test_chat_off_overrides_global_on`, `test_chat_on_overrides_global_off`. |
| `SC-BUD-NOCROSS` | REVIEW | `test_policy_of_one_chat_is_not_used_for_another`: A OFF / B ON / A OFF на одном Router+Reader. |
| `SC-BUD-NOIMPLICIT` | REVIEW | `test_no_chat_id_reads_resolver_for_global_scope`: при отсутствии chat_id резолвер вызван с `None`; ON/OFF не хардкодится. |
| `SC-BUD-RELATED` | REVIEW | `TestRelatedContours` + чтение кода: `tool_loop._resolve_chain_limits`, `direct_execution.resolve_chain_limits_for`, `worker_budget.consume` используют тот же `budget_gate`; второго ON/OFF нет. |
| `SC-BUD-NOTINF` | REVIEW | `test_off_does_not_mean_infinite_execution`: bounded отказ провайдера (≤2 попыток) и fuse `MCA_TOOL_CHAIN_TIMEOUT_SECONDS` действует при OFF. |
| `SC-BUD-SAFETY` | REVIEW | `test_off_keeps_security_guard` (пути/deny) + неизменённые физические пределы S2 (`SOURCE_READ_MAX_FILE_BYTES`, `applied_limits`, `test_smart_c1_source_reader_limits.py`). |
| `SC-BUD-GUARD` | REVIEW | `test_off_does_not_mean_infinite_execution`: `resolve_chain_limits(budgets_enabled=True)` без явной политики → `max_* = 0` (нет скрытых потолков), fuse проверяется до `limits_on`. |
| `SC-BUD-PROGRESS` | REVIEW (частично S4) | S3 доказывает: при OFF общий счётчик не останавливает исследование (10 вызовов при env total=1). Решение «продолжать по прогрессу» — семантика S4 (`tool_loop`/`CheckupService`). |
| `SC-BUD-PARTIAL` | REVIEW (частично S4) | `test_cursor_is_forwarded_and_bypasses_reuse`: `outcome=partial`, cursor, стабильный `progress_id`, повтор не отдаёт прочитанное; честный partial-отчёт чекапа — S4. |

## Effective configuration (evidence)

- `flags.budgets_enabled`: заводской default **ON**
  (`config/settings.py:3045`, env `BUDGETS_ENABLED`); глобальный слой —
  `bot_settings` через `hot_config`/`ConfigCache`; chat override —
  `chat_profiles.chat_params.overrides` (`services/worker_settings.py:82-97`,
  `services/budget_gate.py:116-180`).
- Приоритет не менялся: chat override → global → factory; known OFF не
  превращается в ON из-за ошибки чтения (`budget_gate.resolve_budgets`).
- ON-квоты остаются **явной** операторской политикой: `SOURCE_READ_MAX_*`
  читаются только из env (`source_reader._env_policy_int`), chain-потолки —
  `MCA_TOOL_MAX_*` (`0` = политика не задана). Заводских потолков нет.
- Тестовая среда: fake-слои `hot._cache` и `chat_params._chat_params_cache` +
  spy на `budget_gate.budgets_enabled`/`source_reader.budget_limits_enforced`.
  Это test-only подмена слоёв, а не production-флаг; код приложения читает
  реальные слои.
- Production precedence не проверялась в этой полосе (нет production-доступа):
  effective-state на проде фиксируется на этапе S8 DevOps.

## Известные ограничения и межсрезовые вопросы

1. **`services/tool_schemas.py` не объявляет `cursor`** для
   `read_source_code` (файл вне write-scope S3 и не принадлежит ни одному
   срезу графа). Router теперь принимает и передаёт `cursor`, но модель видит
   его только в `continuation.next_arguments.cursor`; для строгих провайдеров
   (`additionalProperties: false`) свойство нужно объявить. Требуется
   согласование Orchestrator/Architect; минимальная добавка:
   `"cursor": {"type": "string", "description": "Opaque continuation token
   from a previous result's continuation.cursor; pass it back unchanged with
   the same repo/ref/query/symbol."}`. Без этого проводка работает, но
   discoverability континуации неполная.
2. **S4 owns completion semantics**: progress-based продолжение, чекап-partial
   и различение причин ограничений. S3 даёт политику, OFF/ON-семантику и
   identity/continuation в tool-result.
3. **Предсуществующие (не связанные) падения тестов на базовой линии**
   (`BACKLOG_ONLY`, идентичны на `sc/corrective-s1s2` без правки S3):
   - `tests/test_budget_global_toggle_round1024.py::TestMasterPriority`
     (3 теста): `TypeError: _StubDirectChat._make.<locals>._Svc._render_thread()
     got an unexpected keyword argument 'projection'` — устаревшая заглушка
     теста контекст-сжатия;
   - `tests/test_tool_coordinator_round1026.py::TestBounds`
     (`test_canon_twelve_tools`: ожидает 17 инструментов, в линии 18;
     `test_forbidden_paths_out_of_diff`: устаревший baseline web/-путей).
   Оба случая воспроизводятся на pre-fix коде и в S3 ничего не меняют; на
   работоспособность среза не влияют, но должны быть учтены в общем прогоне
   релизного поезда.
4. **Reuse остаётся in-memory и claim-bound** (существующий контракт): S3 не
   меняет namespace/scope; политика бюджета не входит в ключ reuse, потому что
   reuse не вызывает Reader и не создаёт квот; effective-политика пишется в
   `evidence_limits` для наблюдаемости.
5. **Deployed-проверка не выполнялась**: полоса без production-доступа и без
   платных вызовов. Все доказательства — preprod/test-уровня.

## Хозяйство (workspace)

- Создан и зарегистрирован один worktree `s3-budget` (оставлен для review).
- Disposable probe-аллокаций (`WorkspaceData/runs/`) не создавалось: тесты и
  компиляция выполнялись в worktree, артефактов вне репозитория нет.
- Временных копий репозитория/зависимостей не создавалось.
