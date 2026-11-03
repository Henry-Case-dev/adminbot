# PVR-S2 - независимое ревью (owner baseline)

**Вердикт: Approved для слияния слайса.** Гейт карты эпика не закрыт (см. раздел "Карта требований"); на слияние S2 и старт PVR-S3 это не влияет.

- Кандидат: ветка `pv/baseline`, HEAD `c3ea182b` (код `fb41b346`), база `b8ea1d8c`; дерево на момент ревью чистое.
- Дифф: `services/prompt_registry.py`, `services/prompt_release_policy.py`, `web/api/routes.py`, новый `tests/test_prompt_baseline.py`, `tests/test_evol016_prompt_journal_v39.py` (+10 строк), отчёт лейна.
- Контракт: `arch/versioning-ux-contract.md` §2, §4, §7.3 п.4-7. ТЗ владельца: `plans/owner_inputs/2026-11-04-epic-prompt-versioning-ux-01.md` §4 (все пункты) и §6 (бэкенд).

## Три опоры приёмки

- **Implementation.** Проверены `activation_plan(..., pinned)` + `PLAN_ACTIVATE_PINNED` (`prompt_registry.py:751-801`), pinned-ветка `_apply_scope_release` (`prompt_release_policy.py:1600-1686`), `read/assign/clear/restore_baseline`, `restore_shipped_factory`, `copy_revision_to_global`, `_revision_gate`, `read_baseline_event` в обоих сторах, HTTP-слой `web/api/routes.py:3826-4235`. Baseline - событие `prompt_activations` с `outcome=recorded`; `read_applied` читает только `applied|skipped_same` (`_LAST_APPLIED_SQL`), поэтому указатель активной ревизии не двигается.
- **Test validity.** Прочитаны тела и утверждения `tests/test_prompt_baseline.py` (27 тестов): байтовые сверки (`cache.values[...]` и `store.read_global`), точные счётчики событий и ревизий, `detail_code`, отказы с причиной, идемпотентность, трассировка `lock -> tx_enter -> insert -> tx_exit`, сбой `fail_at=insert_activation`. Тавтологий и моков вместо проверяемого шва нет; RBAC тестами не покрыт и закрыт отдельной пробой (строка 8).
- **Independent challenge.** Сценарии, которых нет у Builder: перезапуск после pinned-поставки в чатовом scope; снятие назначения, затем новая метка; миграция на всех блоках с предзаполненными значениями; hidden/code-only и обычный пользователь на всех шести новых маршрутах; копирование одинаковых байтов из двух чатов; первый размеченный релиз при уже назначенной базовой.

## Поклаузно

| # | Требование | Итог | Наблюдаемые факты |
|---|---|---|---|
| 1 | Baseline - указатель, DDL-дельты нет | **PROVEN** | `git diff b8ea1d8c..fb41b346 -- services/pg_db.py` = 0 строк; в диффе `prompt_release_policy.py` нет ни одной строки `JOURNAL_DDL`/`CREATE TABLE`; тест `baseline not in JOURNAL_DDL` проходит; `_BASELINE_SQL` - только `SELECT ... FROM prompt_activations`. Назначение не пишет значение: `store.read_global` = прежние байты, `read_applied.revision_id` и `factory_revision_applied` не двигаются, +1 событие `baseline_assign/recorded`. |
| 2 | Assign != activate, clear != смена текста, свои события с автором и временем, идемпотентность | **PROVEN** | assign: `applied=True, outcome=recorded, active_text_changed=False`, событие `(baseline_assign, recorded)`, `detail_code=baseline:factory`, `actor=owner`, время из БД. Повтор: `baseline_same/skipped_same`, +0 событий (сравнение с последним событием внутри транзакции). clear: `cleared_revision_id` = прежний, `revision_id` пустой, байты и указатель прежние, повтор: `baseline_absent`, +0. |
| 3 | Pinned scope: ревизия в историю, ни baseline, ни ручной текст не перетираются; следующий рестарт - истинный no-op | **PROVEN** (оговорка N1) | Global: `detail_code=factory_superseded_pinned`, `outcome=skipped_same`, `store.read_global` = байты ручной правки, `sha12(FACTORY_B)` в истории, `factory_revision_applied=fac:sha12(narrator-b)`, baseline прежний; рестарт: dAct=0, dRev=0, `activation_drift` = 0. Chat (мой прогон): deploy `activate_pinned/skipped_same`, override = CHAT TEXT; рестарт `no_op/restart_same_revision`, dAct=0, dRev=0, дрейфа нет, override цел. Unpinned: global -> `applied/factory_activate` (байты FACTORY_B), chat -> override снят. После снятия назначения новая метка снова `applied/factory_activate`. |
| 4 | Изоляция чатов; снятие override наследует global effective, а не чатовый baseline | **PROVEN** | Два чата: pinned A сохраняет свой текст, чат B теряет override (обычная политика), baseline B = None, глобального baseline за компанию нет. `remove_prompt_override`: override удалён, `read_applied` чата не сдвинут, `_read_override_value(...) is None`, глобальное значение = MANUAL_M, чатовый baseline в журнале остался и НЕ применён, событие `chat_inherit_reset`. |
| 5 | Чужая/retired/несовместимая ревизия не активируется и не назначается; отказ с причиной | **PROVEN** | `_revision_gate`: чужой scope -> retired -> schema_compat. `revision_foreign_scope` (чужой чат, чат->global, global->чат), `revision_unknown` (другой блок), `revision_retired`, `schema_incompatible` (плюс schema_compat в ответе): `applied=false`, +0 событий, байты прежние. HTTP: 200 с `applied=false`, `reason`, `reason_text`; копирование и фабрика - 422 с `code` и `reason_text`. Тихих no-op нет. Чтение и diff retired/несовместимой доступны, `compatible=false` показывается. |
| 6 | copy-to-global: провенанс и scope сохранены, чужой revision_id не перепривязывается | **PROVEN** (неточность N2) | Новая ревизия `origin=restored`, `reason=copied_from_chat:<id>`, тело = источник, `scope=global`, `chat_id=None`, источник `scope=chat`/`chat_id` не изменён, `revision_id` источника другой, активный текст и число событий не меняются. Источник-global -> `copy_source_not_chat`; цель-чат -> `copy_target_is_global_only`. |
| 7 | Миграция ничего не назначает | **PROVEN** | `apply_release` по всем блокам на пустом журнале: baseline-событий 0, виды событий входят в legacy_import/deploy_activate/manual_edit/integrity_reject; повторный прогон: dAct=0, dRev=0, 0 baseline-событий, `read_baseline_event` = None для всех PG-блоков. `capture_pre_versioning_values` вызывается внутри `apply_release` (строка 1389) и baseline не пишет. |
| 8 | RBAC новых маршрутов = матрица правки; hidden/code-only без активных кнопок | **PROVEN** | Обычный пользователь (USER_ID): 403 на POST/GET/DELETE `.../baseline`, `.../baseline/restore`, `.../factory/restore`, `.../copy-to-global`; +0 событий, +0 ревизий. Hidden (`prompts.summary_cover_style_id`): все capabilities false, POST/DELETE baseline -> 422 "значение задаётся в разделе Mini App". code-only (`identity.no_ai_disclosure`): все capabilities false, POST baseline -> 422 "нет переключаемого значения". Тексты в baseline-ответе не отдаются (только sha256_12, длина, провенанс). |
| 9 | Тексты промптов не изменены; нет второго реестра/журнала; нет новых LLM/бюджетов; дисциплина транзакции как у activate_revision | **PROVEN** | `tests/test_evol018_prompt_audit.py` не изменён (нет в диффе) и зелёный. В диффе нет `CREATE TABLE`/`ALTER TABLE`, `prompt_versions_v2`, `max_tokens`/`token_budget`/`llm_client`. Baseline пишется: `ensure_journal` -> `apply_lock()` (тот же `hashtext(prompt_release_apply)`) -> `transaction()` с `SET LOCAL lock_timeout=5s` (в `_PgTx.__aenter__`) -> `insert_activation` -> commit; трассировка теста `lock, tx_enter, insert:baseline_assign:recorded, ..., tx_exit`. Сбой вставки -> исключение, ни события, ни изменения. |

## Независимые пробы (исполнены)

1. Pinned chat + новая метка + повторный старт: dAct=0, dRev=0, drift=0, override CHAT TEXT цел.
2. `clear_baseline`, затем новая метка: `activate/applied/factory_activate`, в хранилище FACTORY_B (политика вернулась).
3. Миграция на всех размеченных блоках с предзаполненными значениями: 0 baseline-событий; второй прогон dAct=0, dRev=0.
4. RBAC, hidden и code-only - см. строку 8.
5. Копирование одинаковых байтов из двух чатов: `created=false` на втором, целевая ревизия одна (идентичность revision_id по байтам - свойство журнала).
6. Первый размеченный релиз при уже назначенной базовой и отсутствующем значении scope - см. N1.

## Мутации (этот же кандидат; файл восстановлен побайтово, sha256 совпал)

| Мутация | Результат |
|---|---|
| `activation_plan` игнорирует pinned (`pinned=False`) | **CAUGHT** - 2 failed: pinned global, pinned chat |
| `assign_baseline` дополнительно пишет активное значение | **CAUGHT** - 1 failed: `test_assign_baseline_is_pointer_only` (байты в хранилище) |
| `baseline_assign` с `outcome=applied` вместо recorded | **CAUGHT** - 1 failed (указатель read_applied сдвинулся) |
| автоназначение baseline в ветке `PLAN_LEGACY_CUTOVER` | **CAUGHT** - 1 failed: `test_release_migration_assigns_no_baseline` |

## Прогоны

| Набор | Итог |
|---|---|
| `tests/test_prompt_baseline.py` | 27 passed |
| evol018 audit, evol016 journal v39, evol016 activation, evol017 history ui | 47 passed, 1 skipped |
| meme pipeline, soul1 factory defaults, asap history integrity, evol017 history ui, prompt versioning enforcement | 70 passed, 1 skipped |

## Неблокирующие замечания

**N1 (точность контракта, не потеря данных).** В `activation_plan` ветка `if not has_import -> PLAN_LEGACY_CUTOVER` (строки 779-782) стоит раньше проверки `pinned` (789-796). Воспроизведено: scope с назначенной базовой, но без значения и без маркера импорта (достижимо, когда ревизия пришла через `copy-to-global`, а `capture_pre_versioning_values` нечего было импортировать) - первый размеченный релиз идёт по cutover и пишет заводской текст: `after = FACTORY B`, хотя `before` был пуст. Baseline-указатель цел, ручного текста в scope не было, история полна. На боевом состоянии (значение в bot_settings есть, capture создаёт маркер legacy_import, has_import=True) pinned-ветка срабатывает верно: assign -> release -> `activate_pinned`, значение сохранено. Рекомендация: перенести проверку pinned выше cutover (сохранив snapshot текущих байтов) и добавить один durable-тест "pinned + первый размеченный релиз". Места: `services/prompt_release_policy.py:1600-1616`, `services/prompt_registry.py:779-796`.

**N2 (честность провенанса в ответе).** `copy_revision_to_global` возвращает `copy_reason` текущего вызова, но при совпадении байтов отдаёт уже существующую ревизию с прежним `reason` (например `copied_from_chat:<A>`, хотя копировали из B) и `created=false`. Тело и scope корректны, перепривязки нет. Достаточно отдавать в ответе фактический `reason` сохранённой ревизии.

## Карта требований (для PM, до релиза эпика)

`plans/features/epic-prompt-versioning-ux-01/requirements-map.json` объявлен как `strict_evidence=true`, но `requirements` пуст (0 записей), `candidate_commit` пуст, `slice_graph_path=slice-graph.json`. Запуск `requirements_gate.py check --stage review --slice PVR-S2 --candidate c3ea182b...` даёт FAIL: `review scope has no requirements: PVR-S2` и `candidate mismatch`. Поведенческая приёмка слайса этим не отменяется (доказана выше по ТЗ владельца и контракту), но до parent DONE и релиза PM обязан завести слайсы и привязать доказательства к SHA. На старт PVR-S3 не влияет.

## Что вне S2 (для PVR-S4 / UI)

Кнопки и подписи, фраза "Базовая версия изменена, действующий текст пока прежний", разделение "Исходный из кода" и "Базовый, назначен владельцем", постраничная история. Новых бэкенд-эндпоинтов не требуется.

## Слияние

Кандидат пригоден к слиянию в интеграционную ветку: PVR-S3 (постраничная история) может стартовать на объединённом дереве. Условия: не менять тексты промптов, не добавлять DDL, сохранить `kind`/`outcome`-контракт и закрыть N1 до parent DONE.
