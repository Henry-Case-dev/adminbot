# P0-FTS-INDEX-INTEGRITY-01 — полный аудит путей мутации + follow-up (2026-11-28)

Продолжение evidence `plans/features/p0-fts-index-integrity-01/evidence/builder-2026-11-28.md`
(коммит `791d2eba9`); исходный файл не переписывается.

- Source: `plans/features/p0-fts-index-integrity-01/source-2026-11-28.md`
  (sha256 `0019377a617ce174156b54b23fd252193ab53c17018b13259e4b60fec1d27670`)
- Map: `plans/features/p0-fts-index-integrity-01/requirements-map.json`
  (10 required; FTSI-01..04, FTSI-ACC-01..06)
- Base (deployed 2.58.259): `1defb4e05`
- Branch: `fix/fts-index-integrity`
- Линия на момент возобновления: `d48c4f4de` (код+тесты) и `791d2eba9`
  (предыдущий evidence) уже были в ветке; рабочее дерево содержало незакоммиченный
  follow-up ниже. Ничего не откатывалось.
- **Кандидат этой сессии: `954a9734e850662824470a422f01c2d5e79513ca`,
  tree `0051765cedd007e280fd670ebc85b796c8887a6e`**

## 1. Причина (подтверждена)

`graph_facts_fts` — external-content FTS5 (`content='graph_facts',
content_rowid='id'`). FTS5 не наблюдает записи в content-таблицу; каждый писатель
обязан явно синхронизировать индекс.

Утечка — `INSERT OR REPLACE INTO graph_facts` в
`services/dossier_rebuild_jobs.py::restore_user_snapshot` (строка 612):

1. конфликт по НЕ-PK UNIQUE `idx_graph_facts_history_import(chat_id, fact,
   message_timestamp)` — REPLACE удаляет **чужую** строку (другой id), её
   FTS/docsize-запись остаётся навсегда: `docsize` > `graph_facts`, `MATCH`
   возвращает несуществующий id (класс симптома 2.58.259: 44 216 vs 44 196);
2. замена текста по PK — старый код удалял FTS-строку **после** подмены
   content-строки, поэтому снимались новые токены/docsize, а старые токены
   оставались в инвертированном индексе (`MATCH` на удалённую формулировку).

## 2. Аудит ВСЕХ путей мутации `graph_facts` (кандидат `954a9734e`)

Поиск: `rg "INSERT (OR IGNORE )?INTO graph_facts|INSERT OR REPLACE INTO
graph_facts|DELETE FROM graph_facts|UPDATE graph_facts SET|graph_facts_fts"`
по `services/ handlers/ tools/ web/` (вне `plans/ tests/`).

| Путь | FTS-синхронизация | Вердикт |
|---|---|---|
| `database.py::insert_graph_fact` (10412) | INSERT FTS в той же транзакции | ок |
| `activate_dossier_generation` — новый `portrait` (6354) | **не было** | **исправлено** (6443) |
| `activate_dossier_generation` — `person_fact`/`meme` (6517/6546) | INSERT FTS | ок |
| `activate_dossier_generation` — замена портрета (6476–6485) | DELETE FTS → UPDATE → INSERT | ок |
| `update_dossier_portrait` (13487–13493) | DELETE FTS → UPDATE → INSERT | ок |
| `delete_graph_fact` (12476) | FTS delete **до** content delete | ок |
| `purge_expired_graph_facts` (11436) | FTS delete `IN (...)` **до** content delete | ок |
| `clear_direct_dialogue` / `forget_direct_facts` / `forget_memory_facts` (12045/12090/12153) | FTS delete **до** content delete | ок |
| `purge_unconfirmed_graph_facts` (12628) | FTS delete **до** content delete | ок |
| `memory_rebuild.delete_generated_facts` (110) — sanitize/cleanup досье | `_guarded_delete` FTS **до** content | ок |
| `restore_user_snapshot` (dossier rollback) | diff `{id: fact}` до/после REPLACE: vanished → FTS5 `'delete'` старым текстом; changed → delete+insert; new → insert; одна транзакция | исправлено `d48c4f4de` |
| `set_belief_status`/`reinforce`/`resurrect`, `touch_graph_facts`, `confirm/invalidate`, provenance/validity/`supersedes` | меняют только метаданные/веса/статусы, текст не меняется | ок |
| `memory_maintenance._merge_cluster` | новый факт через `insert_graph_fact`; источники — только `supersedes`/validity | ок |
| миграции v4/v5/v7/v8/v9/… rebuild `graph_facts` (7375–7837 и др.) | id и текст сохраняются 1:1, FTS не пересоздаётся (прецеденты D201) | ок (DDL не добавлялся) |
| прочие `INSERT INTO graph_facts` вне `database.py` | не найдено | — |

Вывод: после `d48c4f4de` в коде оставался **один** несогласованный путь —
прямой INSERT нового портрета досье (обход `insert_graph_fact`): строка попадала
в `graph_facts`, но не в FTS → `missing_docsize`, `MATCH` пуст до следующего
обновления портрета или rebuild. Исправлено в `954a9734e` (7 строк) + тест.

## 3. Выбранный способ

Только код, **без DDL, без миграции, без триггеров, `user_version` не менялся**.
Явная команда FTS5 в существующих путях записи (source п.2 допускает
«триггеры или явная команда в существующем пути»):
`INSERT INTO graph_facts_fts(rowid, fact)` для нового портрета; `'delete'` с
явным старым текстом в restore. Maintenance — штатные `inspect/repair` в
`services/memory_rebuild.py` и `manage.py memory fts-check|fts-repair`
(новых демонов/планировщиков/подсистем нет).

## 4. RED / GREEN (7 тестов, `tests/test_fts_index_integrity_floor.py`)

База `1defb4e05` (тесты скопированы, код базы):

```
pytest tests/test_fts_index_integrity_floor.py -q
6 failed, 1 passed
```

- `test_restore_unique_conflict_leaves_no_orphan_docsize` — `assert 2 == 1`
  (docsize 2, facts 1, orphan 1) — **поведенческий RED**;
- `test_restore_text_replacement_drops_old_tokens` — `assert [1] == []`
  (MATCH на старый текст возвращает живую строку) — **поведенческий RED**;
- `test_dossier_portrait_insert_is_fts_indexed` — `assert 1 == 0`
  (facts 1, docsize 0, MATCH пуст) — **поведенческий RED** (эта сессия);
- `test_clean_database_has_no_fts_discrepancy`,
  `test_fts_repair_heals_artificial_orphan_and_is_idempotent`,
  `test_cli_fts_check_and_repair` — падение из-за отсутствия новой
  API/CLI (ImportError/argparse choice) — RED «функция отсутствует»;
- `test_match_after_delete_returns_no_deleted_row` — **проходит и на базе**
  (негативный контроль: обычный `delete_graph_fact` уже был корректен).

Кандидат `954a9734e`:

```
pytest tests/test_fts_index_integrity_floor.py -q     -> 7 passed
```

## 5. Прогоны (независимо, эта сессия)

| Набор | База `1defb4e05` | Кандидат `954a9734e` |
|---|---|---|
| `test_dossier_rebuild_round1022` + `test_mca04b_dossier_rebuild_round1027` + `test_memory_dossiers_cleanup_round1022` + `test_memory_rebuild_round1021` + `test_memory_commands` | 210 passed | 210 passed |
| `test_graphrag_database` | 56 passed | 56 passed |
| `test_graph_facts_origin_v9` | 15 passed | 15 passed |
| `test_history_graph_worker` | 54 passed | 54 passed |
| `test_graphrag_memory` | 181 passed | 181 passed |
| `test_database` | 98 passed | 98 passed |
| Финальный срез (7 новых + dossier/cleanup + `test_database` + `test_graphrag_database`) | — | **272 passed** |
| Два известных red-а (ниже) | 2 failed | 2 failed, те же node id/assert |

Предсуществующие red-ы (не связаны с FTS фактов; воспроизведены на базе и
кандидате одинаково, `assert 2 == 1`, счётчик coalesced-предупреждений):

- `tests/test_asap5_graphrag_recovery.py::test_warning_coalesced_not_repeated`
- `tests/test_graphrag_rebuild_asap32.py::test_not_serviceable_warning_coalesced`

Честные оговорки о прогонах:

- один объединённый прогон 4 файлов (`graphrag_database` + `origin_v9` +
  `history_graph_worker` + `graphrag_memory`) прервался по pytest-timeout в
  teardown фикстуры `test_graphrag_memory.py::db` (`loop.run_until_complete(
  d.close())`); изолированный `test_graphrag_memory.py` — 181 passed и на базе,
  и на кандидате; это артефакт окружения/teardown, не падение теста;
- прогоны выполнены интерпретатором `C:\Code\Python\adminbot\.venv\Scripts\python.exe`
  с `cwd` соответствующего worktree; работа только на временных БД, прод —
  read-only.

## 6. Производство (DevOps; выполняет отдельная роль после ревью)

WORKDIR `/var/www/admin_bot`; БД — штатный путь настроек (в командах ниже
`local_database.db`; если effective-путь иной, взять его из конфигурации).

1. Выкатить одобренный кандидат (`git pull --ff-only` + `systemctl restart
   admin_bot`), миграций нет, `user_version` не меняется.
2. BEFORE (read-only, `mode=ro`):
   `python manage.py memory fts-check --db local_database.db`
   Ожидаемо на данных 2.58.259: `ok=False`, `facts=44196`, `docsize=44216`,
   `orphan_docsize=20`, `db_integrity` содержит `malformed inverted index for
   FTS5 table main.graph_facts_fts`; `fts_integrity=skipped_readonly`
   (спец-команда FTS5 на ro-соединении недоступна; структурная проверка —
   `PRAGMA integrity_check`).
3. Снять «до» по содержимому (не меняется rebuild'ом):
   `sqlite3 local_database.db "SELECT COUNT(*), MAX(id), SUM(LENGTH(fact)) FROM graph_facts;"`
4. REPAIR (пишет только производный индекс, идемпотентно):
   `python manage.py memory fts-repair --db local_database.db`
   Ожидаемо: `rebuilt=yes`, `after`: `facts == fts_docs == docsize`,
   `orphan_docsize=0`, `missing_docsize=0`, `db_integrity=ok`, rc=0.
5. VERIFY:
   - `python manage.py memory fts-check --db local_database.db` → `ok=True`, rc=0;
   - повторный `python manage.py memory fts-repair ...` → `rebuilt=no`;
   - `sqlite3 local_database.db "PRAGMA integrity_check;"` → `ok`;
   - строка из п.3 — те же `COUNT/MAX(id)/SUM(LENGTH(fact))` (пользовательские
     строки не тронуты);
   - MATCH-smoke существующим поиском памяти возвращает строки без ошибок;
   - в journal за окно наблюдения нет новых FTS-ошибок.
6. Ограничения/откат: DDL и пользовательские данные не меняются; `'rebuild'`
   повторяем, поэтому достаточно повторного rebuild или штатного pre-deploy
   бэкапа БД. Кодовый фикс предотвращает повторное накопление; 20 исторических
   orphan-строк чинятся однократным rebuild. Ретроспективно привязать каждую
   историческую строку к конкретному rollback нельзя — это зафиксировано в
   предыдущем evidence.

## 7. Границы

Изменены только `manage.py`, `services/database.py`,
`services/dossier_rebuild_jobs.py`, `services/memory_rebuild.py`,
`tests/test_fts_index_integrity_floor.py` и evidence. `web/**`,
`services/factcheck_planner.py`, `search_aggregator.py`,
`mca_retrieval_context.py`, `direct_chat_service.py`, `bot.py`,
`services/loop_lag_watchdog.py`, version-пины и карты не тронуты.
vec (`graph_facts_vec`) вне области и не менялся.

## 8. Артефакты (git)

- `954a9734e` — follow-up фикс + тест (tree `0051765c…`)
- `d48c4f4de` — основная синхронизация FTS + maintenance (tree `eab99c6b…`)
- `791d2eba9` — предыдущий evidence
- blob-хеши кандидата: `database.py 1c3056db…`, `dossier_rebuild_jobs.py
  cffa0384…`, `memory_rebuild.py 6ae2c3b9…`, `manage.py 19ab7505…`,
  `test_fts_index_integrity_floor.py 42d7ab6b…`
