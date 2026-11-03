# PVR-S2 — owner baseline: отчёт лейна

Ветка `pv/baseline`, база `b8ea1d8c` (worktree от `evol/impl`),
кандидат коммита `fb41b346` (`feat(prompts): PVR-S2 owner baseline as journal
pointer ...`).

Контракт: `plans/features/prompt-versioning-ux/arch/versioning-ux-contract.md`
§2.1–2.5, §4, §7.3 п.4–6; требования владельца §4 (все пункты) и §6 (бэкенд).

## Что сделано (без DDL, без второго хранилища)

Baseline = **событие существующего журнала `prompt_activations`**, а не таблица
и не копия текста:

* `kind='baseline_assign'` (`revision_id=<существующая ревизия>`,
  `detail_code='baseline:<origin>'`), `kind='baseline_clear'` (`revision_id=''`);
* `outcome='recorded'` — `read_applied` читает только `applied|skipped_same`,
  поэтому указатель «активная ревизия» такими событиями не двигается и откат
  кода безопасен;
* действующий baseline = ПОСЛЕДНЕЕ такое событие по `activation_id` для
  `(block_id, scope, chat_id)` (`_BASELINE_SQL`, индекс
  `idx_prompt_activations_latest` уже покрывает поиск);
* DDL-дельты нет: `JOURNAL_DDL` не изменён, `baseline` в нём не встречается
  (проверяется тестом).

### Путь чтения

`prp.read_baseline(block_id, scope, chat_id)` →
`store.read_baseline_event(...)` (`MemoryPromptJournal` и `PgPromptJournal`)
→ `_baseline_payload(...)`: `source` (`owner|factory`), `baseline`
(`revision_id/assigned_at/assigned_by/origin/sha256_12/chars/retired/
schema_compat/compatible/is_active/available`), `cleared_at/cleared_by`.
Тела текста не отдаются (список/карточка), полный текст — существующим
`/api/prompts/revisions/{id}/source`.

### Путь записи

`assign_baseline` / `clear_baseline`: `ensure_journal` → **тот же**
advisory-лок `APPLY_LOCK_SQL` (`hashtext('prompt_release_apply')`) → одна
транзакция (`SET LOCAL lock_timeout='5s'` в `_PgTx.__aenter__`) → все чтения
(ревизия, текущий baseline, `read_applied`) на `_tx_conn` → `insert_activation`
→ commit. Порядок операций проверяется трассировкой стора
(`lock → tx_enter → insert:baseline_assign:recorded → tx_exit`).

### Политика релиза при pin

`activation_plan(..., pinned=False)` + `PLAN_ACTIVATE_PINNED`; pin читается В
ТОЙ ЖЕ транзакции релиза. Для закреплённого scope: ревизия `origin=factory`
пишется в историю, значение не пишется, чатовый override НЕ снимается,
событие `deploy_activate/skipped_same`, `detail_code='factory_superseded_pinned'`,
`factory_revision_applied=<новая метка>`, `revision_id=<действующая активная>`.
`pinned=False` по умолчанию — прежняя семантика для всех существующих вызовов.

## HTTP-слой (те же маршруты промптов, без второго API)

| Метод/путь | Тело | Что делает |
|---|---|---|
| `GET /api/prompts/{key}/baseline` | — (`X-Chat-Id` → скоуп чата) | чтение указателя + `capabilities` |
| `POST /api/prompts/{key}/baseline` | `{revision_id}` | «Назначить базовой» (не активирует) |
| `DELETE /api/prompts/{key}/baseline` | — | «Снять назначение» (текст не меняется) |
| `POST /api/prompts/{key}/baseline/restore` | — | «Восстановить базовую» (`baseline_restore`) |
| `POST /api/prompts/{key}/factory/restore` | `{confirm:true}` | «Вернуть исходную из кода» (`factory_restore`) |
| `POST /api/prompts/revisions/{id}/copy-to-global` | `{target_chat_id?}` | копия чатового текста как НОВОЙ глобальной ревизии |

Ответы baseline-действий имеют ТУ ЖЕ форму, что `GET .../baseline`
(`source`, `baseline`, `cleared_at`, `capabilities`) плюс служебные
`applied/outcome/reason/reason_text/active_unchanged`. `GET
/api/prompts/{key}/versions` дополнительно отдаёт `baseline` и `capabilities`
(`can_assign_baseline`, `can_clear_baseline`, `can_restore_baseline`,
`can_restore_factory`, `can_copy_to_global` для chat-скоупа) — UI-слайс не
делает второго запроса.

RBAC — как у записи значения: global → `can_edit_param`, chat → доступ к чату +
матрица чата; baseline read — право просмотра истории; hidden-ключи и
`code_only` не получают действий (422/`can_* = false`). Хук сервиса расширен
теми же действиями, что активация.

## Доказанные инварианты (тесты, с числами)

`tests/test_prompt_baseline.py` — **27 passed**. Ключевые утверждения:

1. `Назначить базовой` — только указатель: байты активного текста равны
   прежним (сверка и в кэше, и в самом хранилище `store.read_global`),
   `read_applied.revision_id`/`factory_revision_applied` не двигаются,
   `+1` событие `baseline_assign/recorded`, `detail_code='baseline:factory'`;
2. повтор назначения: `applied=false, reason=baseline_same`, прирост событий
   `0`;
3. `Снять назначение`: байты прежние, указатель прежний, событие
   `baseline_clear` с `revision_id=''`, `source` снова `factory`, повтор — no-op;
4. pinned global: значение = байты ручной правки (сравнение `.encode()`),
   `sha12(FACTORY_B)` присутствует в истории, `factory_revision_applied`
   двигается на `fac:sha12('narrator-b')`, baseline не переписан, следующий
   рестарт: `+0` активаций, `+0` ревизий, `0` строк `activation_drift`;
5. unpinned global: значение = байты `FACTORY_B`, `applied/factory_activate`;
6. pinned chat: override сохранён (`store.chat_overrides[CHAT_A][PG_KEY]`),
   глобальный (незакреплённый) scope получил новый заводской текст;
   unpinned chat: override снят (прежняя политика);
7. изоляция чатов: baseline A не виден чату B и глобальному; чат B получил
   обычную политику;
8. снятие чатового override: override удалён, `read_applied` чата не сдвинут,
   эффективный слой = global effective (своего значения нет), baseline чата
   остался в журнале и НЕ применён, событие `chat_inherit_reset`;
9. отказы: чужой чат → `revision_foreign_scope`, чатовая ревизия → global →
   `revision_foreign_scope`, чужая ревизия блока → `revision_unknown`;
   retired → `revision_retired`, `schema_compat` → `schema_incompatible`
   (при этом чтение/diff доступны, baseline читается как `compatible=false`);
10. `Восстановить базовую` = явная активация `baseline_restore` с байтами
    эталона; без назначенной базовой — `baseline_absent` и текст не изменён;
11. `Вернуть исходную из кода`: без `confirm` → `confirmation_required`,
    значение прежнее; с `confirm` → `factory_restore`, байты заводского текста,
    `baseline_cleared=false`, baseline на месте; сломанная печать →
    `factory_unverifiable`, значение прежнее;
12. copy-to-global: новая ревизия `origin=restored`,
    `reason='copied_from_chat:<id>'`, байты равны источнику, `revision_id`
    источника не перепривязан (scope/chat сохранены), активный текст не
    изменён, повтор `created=false`; источник-global → `copy_source_not_chat`;
13. миграция: после `apply_release` (все блоки) событий baseline `0`, набор
    видов событий ⊆ прежних, значения прежние; повторный прогон — тоже `0`;
14. сбой `insert_activation` → исключение и НИ одного события/изменения
    (транзакция целиком);
15. `JOURNAL_DDL`: ровно 2 таблицы, `baseline` не встречается;
    `_BASELINE_SQL` — только `SELECT ... FROM prompt_activations`;
16. API: assign→read→clear (200, `source` меняется `owner`→`factory`), чужой
    чат 200 с `revision_foreign_scope` и `reason_text`, factory/restore без
    `confirm` → 422 `confirmation_required`, copy-to-global 200, `/versions`
    содержит `baseline` и `capabilities`.

### Мутации (тесты умеют падать; прогон на этом же кандидате)

| Мутация | Результат |
|---|---|
| `activation_plan`: игнорировать `pinned` (`if False and pinned`) | CAUGHT — 2 failed (pinned global + pinned chat) |
| `assign_baseline`: писать значение через `_write_active_value` | CAUGHT — 1 failed (pointer-only, сверка хранилища) |
| `baseline_assign`: `outcome='applied'` вместо `recorded` | CAUGHT — 1 failed |
| pinned-ветка: дополнительно снимать чатовый override | CAUGHT — 1 failed (pinned chat) |
| `_revision_gate`: пропускать чужой scope | CAUGHT — 1 failed (foreign) |
| `apply_release`: автоназначение baseline на миграции | CAUGHT — 1 failed (migration) |

Драйвер мутаций: `WorkspaceData/runs/.../mutate_baseline.py` (рабочий
каталог, не проект); после каждой мутации файл восстановлен побайтово.

## Прогоны

| Набор | Итог |
|---|---|
| `tests/test_prompt_baseline.py` | 27 passed |
| prompt/policy/factory/webapp-api (20 файлов) | 487 passed, 2 skipped |
| prompt/speech/policy/meme/config/lore/persona (по маске) | 1484 passed, 2 skipped |
| `tests/test_webapp_*.py` (весь webapp-набор) | 1460 passed, **3 failed — pre-existing** |
| `tests/test_evol018_prompt_audit.py` (не изменён) | 10 passed |

Pre-existing webapp-падения (`test_webapp_avatars_ui::test_close_and_fullscreen_buttons`,
`test_webapp_round1024_nodeflow::test_no_english_jargon`,
`test_webapp_tma_fixes_ui::test_logs_block_layout_mono`) воспроизводятся на базе
`b8ea1d8c` без моих изменений (проверено `git stash` → прогон → `stash pop`);
к промптам/baseline отношения не имеют.

Единственная правка существующего теста — двойник PG в
`tests/test_evol016_prompt_journal_v39.py` получил ветку `_BASELINE_SQL`:
строгий диспетчер по идентичности SQL-констант обязан знать новый ЧТЕНИЕ-запрос,
иначе реальный путь релиза падал «незнакомым SQL». Утверждения теста не
ослаблены.

## Что осталось для UI-слайса (PVR-S4)

1. Читать `baseline` + `capabilities` из существующего ответа `/versions`
   (или `GET .../baseline` при открытии карточки) — второго API не нужно.
2. Кнопки: «Назначить базовой» (`POST .../baseline`), «Снять назначение»
   (`DELETE .../baseline`), «Восстановить базовую» (`POST .../baseline/restore`),
   «Вернуть исходную из кода» (с подтверждением →
   `POST .../factory/restore` с `confirm:true`), «Скопировать как новую
   глобальную версию» (`POST /api/prompts/revisions/{id}/copy-to-global`).
3. Показывать `reason_text` при `applied=false` и явную фразу при назначении:
   «Базовая версия изменена, действующий текст пока прежний»
   (`active_text_changed=false`).
4. Различать в карточке две сущности: «Исходный из кода» (`source=factory`,
   `factory_revision`) и «Базовый, назначен владельцем» (`source=owner`,
   `baseline.assigned_by/assigned_at`); `is_active` — отдельный бейдж.
5. Чатовый скоуп: baseline читается с `X-Chat-Id`; снятие override и
   «Восстановить базовую для чата» — РАЗНЫЕ пункты меню (подписи не смешивать).
6. `compatible=false`/`retired=true` у baseline — показывать причину и
   блокировать активацию/назначение, оставляя просмотр и diff.
