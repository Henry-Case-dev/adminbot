# SMART-CORRECTIVE-01 — S6 prompt guard (EVOL-016 corrective)

Статус: **REVIEW** (кандидат для независимого ревью; не VERIFIED).
Дата: 2026-11-15.
Источник: `plans/features/smart-corrective-01/evidence/prompt-cutover-investigation.md`
+ owner corrective §8.1 / AC-15 / AC-19 (новее EVOL-012).

## Идентичность кандидата

- Epic: `smart-corrective-01`, срез `S6-prompt-guard`.
- Базовая линия: `release/smart-corrective-01` @ `409f4e8a`
  (`409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9`, задеплоенный поезд 2.58.201).
- Рабочая ветка: `sc/corrective-s6-guard`.
- Commit кандидата: `a8b6197f`
  (`a8b6197fc49142097a3ea14e76d10a0bcec5a1eb`) —
  `fix(prompts): keep saved chat edition over factory cutover (S6 guard)`.
- Worktree:
  `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-3aa92750`
  (managed `WorkspaceData/worktrees`, registered как `s6-prompt-guard`).
- Версия не менялась; заводской текст, метки и печати не менялись
  (`git diff --name-only 409f4e8a` — только 5 файлов ниже). Бамп до 2.58.202 и
  деплой — задача release train, не этого среза.

## Причина (воспроизведена кодом и тестами)

`pinned` выставлялся только по последнему событию `baseline_assign`
(`_apply_scope_release` → `read_baseline_event`). Ручная редакция владельца без
явного назначения baseline попадала в обычную ветку `new_factory_revision`:
заводская ревизия активировалась, chat-override снимался
(`_write_active_value` + `remove_chat_override`). Production 2.58.201:
`rev:d31300ef35a0` (manual, 12 469 симв., sha `31d17506…`) сохранена, но
неактивна; активна factory `rev:9ed7b22b0d8c`.

## Что изменено

### 1. Guard в автомате релиза (`services/prompt_release_policy.py`)

- Новый read-метод стора `read_live_manual_revision(block_id, scope, chat_id)`
  — последняя сохранённая (`origin='manual'`, `retired=false`) ревизия адресата.
  Тело не читается (как в списках): нужны идентичность и sha.
  Реализован в `MemoryPromptJournal` (по тому же фильтру адресата, что и
  остальные чтения) и в `PgPromptJournal` (SQL `_LIVE_MANUAL_REVISION_SQL`,
  существующий индекс `(block_id, scope, created_at)`; чтение идёт на коннекте
  транзакции релиза через `_run_on_conn`, т.е. под тем же advisory-локом).
- В `_apply_scope_release` после pinned-ветки: для `scope=chat` и плана
  `activate`/`legacy_cutover` при наличии такой ревизии
  - заводская ревизия **пишется в историю** (`origin=factory`,
    `reason=factory_release`) — поставка не теряется;
  - `_write_active_value` **не вызывается**, `remove_chat_override`/`notify_chat`
    **не вызываются**;
  - пишется событие `deploy_activate / skipped_same /
    detail_code=factory_superseded_manual` с указателем на действующую ревизию
    (указатель применённой метки двигается → следующий рестарт — истинный no-op);
  - в результат релиза отдаётся та же пара `skipped_same` +
    `factory_superseded_manual`.
- Явный `baseline_assign` обрабатывается **выше** и сохраняет приоритет:
  `PLAN_ACTIVATE_PINNED` / `factory_superseded_pinned`, прежняя pin-политика.
- `history_reason_text` объясняет новый код человеческим языком (история версий
  показывает, почему заводская строка неактивна). DDL/флагов/настроек нет,
  bytes ручной ревизии и активных значений не переписываются, клонов нет.

### 2. Контракт-документ

`docs/prompt-versioning-contract.md` §3.2: добавлена строка про поведение при
деплое в chat scope с сохранённой ручной ревизией (`factory_superseded_manual`).

### 3. Тесты

Новые (в `tests/test_smart_corrective_prompt_delivery.py`, раздел 8; тот же
CONTRACT-файл corrective-среза, стенд `FakeCache`/`FactoryEdition` +
`MemoryPromptJournal`):

| Тест | Что утверждает (наблюдаемо) |
|---|---|
| `test_manual_chat_edition_survives_factory_cutover` | ручная редакция чата без `baseline_assign`: результат `skipped_same/factory_superseded_manual`, override побайтно тот же, ручная ревизия (body и sha) не изменилась, заводская B в истории этого чата ровно одна, новых ревизий ровно 2 (global+chat), чат не уведомлялся, событие журнала с новым кодом, global получил заводской текст; повторный прогон — 0 новых строк и 0 записей |
| `test_guard_is_isolated_to_the_chat_with_manual_edition` | чат с сохранённой редакцией удержан, другой чат без ручной ревизии получает `applied/factory_activate`, его override снят, байты снятого override сохранены в истории |
| `test_explicit_baseline_assign_still_wins_over_manual_guard` | явный owner baseline даёт прежний `PLAN_ACTIVATE_PINNED` / `factory_superseded_pinned`, override цел, указатель метки и baseline прежние |
| `test_preserved_manual_edition_without_override_is_not_replaced` | состояние после 2.58.201 (override снят, редакция сохранена): релиз не выдумывает заводской override, ревизия не retired и не переписана |

Обновлены тесты, кодировавшие прежнее поведение (осознанно, потому что новый
owner-контракт §8.1/AC-19 его отменяет именно для chat scope с сохранённой
редакцией):

| Файл | Что изменено и почему |
|---|---|
| `tests/test_evol016_prompt_activation.py::test_scope_global_and_two_chats` | последний блок: новая метка больше **не снимает** сохранённую ручную редакцию чата 111 — проверяются `factory_superseded_manual`, целый override, ручная и заводская ревизии в истории. Прежние шаги (override без ручной ревизии снимается в историю, рестарт ничего не делает) не менялись |
| `tests/test_prompt_baseline.py::test_unpinned_chat_scope_keeps_previous_policy` | переименован в `test_unpinned_chat_scope_without_saved_edition_keeps_previous_policy`: обычная политика проверяется на override без сохранённой ручной ревизии (теперь это и есть «незакреплённый scope») |
| `tests/test_prompt_baseline.py::test_chat_baseline_is_isolated_between_two_chats` | чат B получает override без ручной ревизии, чтобы изоляция baseline оставалась различимой (A удержан pin, B — обычный cutover) |

Docstring'ы обоих файлов дополнены оговоркой про guard.

## RED → PASS

RED (старое поведение воспроизведено точечным отключением guard —
`manual_revision = None` после чтения, затем откат): падают ровно
`test_manual_chat_edition_survives_factory_cutover`,
`test_guard_is_isolated_to_the_chat_with_manual_edition` и
`test_scope_global_and_two_chats` — то есть тесты ловят именно снятие override и
активацию factory поверх ручной редакции. Pin-тест и тест «override без ручной
ревизии» в RED остаются зелёными (их поведение не меняется).

PASS на кандидате `a8b6197f`:

```
py -3 -m pytest tests/test_smart_corrective_prompt_delivery.py \
  tests/test_smart_corrective_budget_policy.py \
  tests/test_smart_corrective_completion.py tests/test_smart_corrective_input.py \
  tests/test_smart_corrective_source_reader.py tests/test_prompt_baseline.py \
  tests/test_evol016_prompt_activation.py tests/test_evol016_prompt_journal_v39.py \
  tests/test_evol017_prompt_history_ui.py tests/test_evol018_prompt_audit.py \
  tests/test_prompt_history_pagination.py tests/test_prompt_readback.py \
  tests/test_prompt_versioning_enforcement.py tests/test_pvr_backend_state.py \
  tests/test_pvr_rev01_prompt_conflict_no_write.py \
  tests/test_asap_prompt_history_integrity.py tests/test_evol012_barrier_retired.py -q
→ 320 passed, 2 skipped
```

```
py -3 -m pytest tests/test_checkup_prompts.py tests/test_checkup_contract.py \
  tests/test_checkup_service.py tests/test_checkup_handlers.py \
  tests/test_checkup_logs_fetcher.py tests/test_p0_checkup_core_contract.py \
  tests/test_p0_prompts_core.py tests/test_expression_isolation_followup.py \
  tests/test_prompt_migrations.py tests/test_soul1_factory_defaults.py \
  tests/test_soul1_registry_legacy_removal.py tests/test_direct_chat_prompts.py \
  tests/test_summary_prompts.py -q
→ 331 passed
```

```
py -3 -m pytest tests/test_checkup_handlers.py tests/test_evol016_prompt_journal_v39.py \
  tests/test_evol017_prompt_history_ui.py tests/test_prompt_field_audit.py \
  tests/test_prompt_history_pagination.py tests/test_prompt_readback.py \
  tests/test_prompt_versioning_enforcement.py tests/test_pvr_rev01_prompt_conflict_no_write.py \
  tests/test_prompts_round1024.py tests/test_summary_asap21_prompt_migrations.py \
  tests/test_soul1_direct_prompt_reads.py tests/test_soul1_legacy_custom_preserved.py \
  tests/test_soul1_core_version_propagation.py tests/test_round1025_f8_registry.py -q
→ 264 passed, 1 pre-existing failure (см. ниже)
```

```
py -3 -m pytest tests/test_evol016_prompt_activation.py tests/test_evol016_prompt_journal_v39.py \
  tests/test_evol017_prompt_history_ui.py tests/test_evol018_prompt_audit.py \
  tests/test_prompt_baseline.py tests/test_prompt_history_pagination.py \
  tests/test_prompt_readback.py tests/test_prompt_versioning_enforcement.py \
  tests/test_prompt_field_audit.py tests/test_prompt_migrations.py \
  tests/test_pvr_backend_state.py tests/test_pvr_rev01_prompt_conflict_no_write.py \
  tests/test_asap_prompt_history_integrity.py tests/test_evol012_barrier_retired.py -q
→ 274 passed, 2 skipped, 1 pre-existing failure
```

```
py -3 -m py_compile services/prompt_release_policy.py \
  tests/test_smart_corrective_prompt_delivery.py tests/test_prompt_baseline.py \
  tests/test_evol016_prompt_activation.py → 0
git diff --check → clean
```

### Pre-existing failures (не связаны со срезом; воспроизведены на базе `409f4e8a`)

1. `tests/test_prompt_field_audit.py::test_every_editable_prompt_has_reachable_surface`
   — падает и на базовом worktree `409f4e8a` (тот же тест, тот же результат).
2. `tests/test_soul1_registry_completeness.py::test_registry_consumer_pointers_point_at_real_lines`
   — падает и на базовом worktree `409f4e8a`.

Оба уже зафиксированы как incidental в `evidence/s6/implementation.md`;
поведение среза их не меняет.

`ADMINBOT_TEST_PG_DSN` в окружении не задан → живой PG-тест
`test_apply_release_on_live_postgres` честно skipped (2 skipped — тот же набор,
что и в S6-кандидате). Новый SQL подписан тем же приведением типов, что и
существующий `_HAS_IMPORT_SQL`, но на живом PostgreSQL не исполнялся в этом
прогоне — это ограничение, см. ниже.

## Матрица поведения (chat scope, новая заводская метка)

| Состояние чата | Поведение | detail_code | override |
|---|---|---|---|
| сохранённая ручная ревизия, без `baseline_assign` (**случай владельца**) | заводская ревизия → в историю, значение не пишется | `factory_superseded_manual` | сохранён побайтно |
| сохранённая ручная ревизия + явный `baseline_assign` | pinned-политика (как раньше) | `factory_superseded_pinned` | сохранён побайтно |
| override без ручной ревизии (legacy/без журнала) | обычный cutover (как раньше) | `factory_activate` | снят, байты в истории |
| метка не менялась (рестарт) | истинный no-op: ни строк, ни записей | `restart_same_revision` | не трогается |
| сохранённая ревизия есть, override отсутствует (состояние после 2.58.201) | чат не входит в релиз, заводской override не выдумывается | — | отсутствует |

Изоляция: guard проверяет адресата (`block_id, scope='chat', chat_id`), поэтому
другой чат того же блока получает заводскую поставку как обычно (тест выше).

## Ограничения / что осталось непроверенным

1. **Data-only возврат `rev:d31300ef35a0` в CHAT_C2 — отдельное действие
   DevOps после выката** (штатный `activate_revision`, ожидаемый
   `activate:manual`/`applied`). Guard не активирует сохранённую редакцию сам:
   он лишь не даёт заводской поставке занять её место. До этого шага
   эффективный текст CHAT_C2 остаётся global/factory — ровно то состояние,
   которое создал 2.58.201.
2. Живой PostgreSQL не запускался (нет DSN в окружении): SQL нового чтения
   проверен статически (типизация как у существующего `_HAS_IMPORT_SQL`) и на
   in-memory двойнике. Postdeploy-проверка effective-state и журнала — на
   release train (2.58.202).
3. Композиция «дрейф журнала + сохранённая ручная редакция»: снимок и ERROR
   `activation_drift` пишутся как раньше, затем guard удерживает override.
   Внутренний текст ERROR-сообщения `_check_activation_drift` («заводская
   ревизия активируется в этой же транзакции») в этом редком сочетании
   неточен; данные/журнал корректны, строка `factory_superseded_manual` идёт
   следом в том же apply.
4. Явный ручной «вперёд» на заводскую ревизию (EVOL-017 `activate_revision`
   для `origin=factory`) не снимает признак сохранённой ручной редакции:
   последующие заводские поставки для такого чата остаются заблокированными
   до `baseline_assign`/иной явной политики. Это осознанно минимальное
   поведение по §8.1; отдельная семантика «явно вернулся на factory» не
   вводилась.
5. Никаких флагов/настроек срез не добавляет: поведение включается самим
   релизом (запуск `apply_release` на старте), owner-значения не меняются.
   `checkup_enabled` и прочие production-флаги не затрагивались.
6. Заводской текст не менялся (`services/checkup_prompts.py`,
   `services/prompt_registry.py` в diff отсутствуют) — guard не является
   способом «поправить качество» текстом; правки качества остаются за
   S6/последующими срезами.

## Домохозяйство

- Disposable-аллокаций/проб не создавалось (тесты и RED-прогон — внутри
  worktree). `run-close` применять нечего; worktree сохранён
  зарегистрированным (`s6-prompt-guard`) для Reviewer.
