# MEMORY-07 — клауза схемы v44: доказательство выкладки 2.58.167

Артефакт PM: привязка **только клаузы схемы** требования MEMORY-07
(«v44 применён на реальной БД, повтор — no-op, таблицы пусты и инертны»).
Остальная часть MEMORY-07 (сборка, веса, lifecycle, подписи, стабильность ID,
ассоциативный retrieval) **не реализована** и остаётся `PENDING`.

| Поле | Значение |
|---|---|
| Deployed | `153063b2826228b699786c911151b4348555bd48` (`release/2.58.167`, версия 2.58.167) |
| Одобренный кандидат | `8b5907b079db76bfda2a724654ffb66d842f63a3` (parent `8d9b37796d9bfc8df35c338f98e9c36d6fb15e70`) |
| Предыдущий прод | 2.58.166 @ `b2744b58fce42066b26bc76b3ebbae41c7deaf1e` |
| Отчёт DevOps | `plans/features/memory-cognitive-02/reports/deploy-2.58.167.md` (закоммичен в `d0a3123586c2df114070e37707aa9c0fb00a6463`, ветка `integ/unify-release`) |
| Продуктовый код в этой волне | только аддитивный шаг схемы; поведение не меняется |
| Хранилище | прод `/var/www/admin_bot`, SQLite, single-writer |

Сверено локально в репозитории: `153063b2^` = `8b5907b0` — релизный коммит есть
ровно одобренный кандидат плюс бамп версии, отдельного кода в нём нет.

## 1. Что именно доказано этой привязкой

1. Шаг `v44` (`memory_communities_v44`) применён на реальной прод-БД: `user_version`
   43 → 44, `schema_migrations` 32 → 33, добавлены ровно две таблицы сообществ и
   три их индекса; ни одна существующая таблица не удалена и не изменена.
2. Повтор шага — no-op (по коду шага и по прогону на копии БД): DDL 5 выражений,
   все `CREATE ... IF NOT EXISTS`, без `ALTER`/`DROP`/`INSERT`/`UPDATE`/`DELETE`;
   раннер пропускает шаги с `version <= user_version`.
3. Обе таблицы **пусты** и **инертны**: в коде кандидата нет ни одной записи в них,
   единственное чтение (`services/mca_retrieval_context.py::_community_candidates`,
   существует с 2.58.166) защищено проверкой наличия таблицы и на пустой таблице
   возвращает `[]`.
4. Целостность: `quick_check` и `integrity_check` — `ok`; DDL/индексы `nodes`,
   `edges`, `graph_facts`, `smart_messages`, `mca_entity_canonical`,
   `graph_facts_vec`, `schema_migrations` полностью совпадают с преддеплойным
   снимком (сравнение на сервере, `compare_258167.sh`).

## 2. Схема: до → после (прод, из отчёта DevOps)

| Метрика | До (снимок) | После |
|---|---|---|
| `user_version` | 43 | **44** |
| `schema_migrations` | 32 строки | **33** строки, хвост `(44, 'memory_communities_v44')` |
| таблиц (без `sqlite_*`) | 125 | **127** (`mca_community_builds`, `mca_community_members`) |
| индексы сообществ | — | **3**: `idx_mca_community_builds_chat_status`, `idx_mca_community_members_node`, `idx_mca_community_members_community` |
| `mca_community_builds` | таблицы нет | есть, **0 строк** |
| `mca_community_members` | таблицы нет | есть, **0 строк** |
| `quick_check` | ok | **ok** (`integrity_check` тоже ok) |
| DDL/индексы `nodes`, `edges`, `graph_facts`, `smart_messages`, `mca_entity_canonical`, `graph_facts_vec`, `schema_migrations` | — | **идентичны** снимку до выкладки |
| удалённые таблицы | — | **нет ни одной** |

Счётчики данных (снимок `predeploy-258167.db`, 1 740 234 752 б, read-back ok):

| Таблица | До | После | Комментарий |
|---|---|---|---|
| `smart_messages` | 2 073 204 | 2 073 222 | Δ — только живой трафик: все строки `id <= 2 395 432` на месте, 2 073 204 из 2 073 204 (`intact=True`), удалений нет |
| `nodes` | 33 243 | 33 243 | без изменений |
| `edges` | 64 431 | 64 431 | без изменений |
| `graph_facts` | 23 301 | 23 301 | без изменений |
| `schema_migrations` | 32 | 33 | +1 (шаг v44) |

## 3. Точные строки журнала миграции (прод, 2026-11-08)

```
08:41:02 [database] migrations: start | current user_version=43 | pending=[44]
08:41:02 [database] migration backup-guard: start | target_version=43 (VACUUM INTO + read-back)
08:41:26 memory_backup: pre-migration copy created + read-back ok | target_version=43
08:41:26 [disk_retention] migration backup rotated out | name=pre_migration_20261107_155353.db
08:41:26 [database] migration backup-guard: done in 24.1s
08:41:26 [database] migration v44: mca_community_builds, mca_community_members
08:41:26 [database] migration v44 applied in 0.0s | memory_communities_v44
08:41:26 [database] migrations: complete | user_version=44 | total 24.1s
```

Порядок существенен: сначала backup-guard (`VACUUM INTO` + read-back, 24.1 s),
только потом применение шага (0.0 s — DDL двух пустых таблиц и трёх индексов).
Итоговое `user_version=44` зафиксировано самим шагом, а строка книги добавлена
раннером (`INSERT OR REPLACE ... checksum`).

## 4. Код кандидата `8b5907b0` (проверено PM по blob-ам git)

| Файл (git blob) | Содержание |
|---|---|
| `services/memory_communities.py` (`5a3ceb135586b4f86602225c75c92d4d5491e0be`, content sha256 `f0948fb87f33b86da5a2b33067b88b01ec23df156c051969932591676c274b77`) | владелец DDL: `COMMUNITY_BUILDS_DDL_SQLITE`, `COMMUNITY_MEMBERS_DDL_SQLITE`, `COMMUNITY_INDEX_DDL`; имя шага `memory_communities_v44`; закрытые значения `status` |
| `services/database.py` (`3488d881d9044a17550260f00ef9166a27cd5db4`) | `_SCHEMA_VERSION_MEMORY_COMMUNITIES = 44`, `MigrationStep(44, …)`, `_migrate_communities_v44()` применяет DDL владельца; собственных копий DDL нет |
| `services/mca_retrieval_context.py` (`4a364effa8f68826d342ad06749a7de647bf25ff`) | `_community_candidates` — единственное чтение, под guard `sqlite_master` |
| `tests/test_memory_communities_migration.py` (`8db0aa56471dfc7635f7289084561ff47eb78dc6`) | 5 тестов: регистрация шага после v43, свежая БД (таблицы+колонки), повтор no-op с сохранением строк, апгрейд v43-БД без изменения её данных, пустота таблиц при обычных записях памяти |

Независимая проверка PM (stdlib `sqlite3`, только чтение git-блобов, без правки
продуктового кода; прогон
`…/WorkspaceData/runs/c742e4de9e92c489/memory-cognitive-02-52a705214107/probe-0095544b1b/probe_v44_idempotency.py`):

- 5 DDL-выражений, все с `IF NOT EXISTS`, ни одного `ALTER`/`DROP`/`INSERT`/`UPDATE`/`DELETE`;
- свежая БД: двойное применение → набор объектов и их `sql` идентичны, обе таблицы 0 строк, `quick_check ok`;
- v43-подобная БД (свои `nodes`/`edges`/`graph_facts`/`smart_messages`/`mca_entity_canonical`/`schema_migrations`, 32 строки книги, `user_version=43`): двойное применение → DDL всех существующих объектов **байт-в-байт** тот же, книга не изменилась (32 → 32), `user_version` меняет только сам шаг, после шага книга 33 строки с хвостом `(44, memory_communities_v44)`, `quick_check`/`integrity_check ok`.

## 5. Честная граница доказанного

- **Таблицы инертны сейчас, а не «работают»**: строк 0, писателя нет ни в одном
  файле кандидата, построителя сообществ (`B4`) нет, веса рёбер нет, lifecycle
  `building → active → superseded/failed` нет, подписей/метрик сообщества нет.
- **Гейт `MCA_MEMORY_COMMUNITIES_ENABLED` default OFF — это контракт, а не
  зарегистрированный флаг на этой волне.** В коде `8b5907b0` такого ключа в
  реестре гейтов нет (он упоминается только в `contracts.md` и комментариях).
  Фактическая причина тишины канала в 2.58.167 иная и проверяемая: канал
  `community` включается только при `mode == "thematic"`, читает
  `mca_community_members` и на пустой таблице возвращает `[]`, после чего
  `channels` не пополняется. Регистрация флага и проверка «только активная
  сборка» — работа следующей волны (MEM-07.2/07.3).
- **Живой тематический retrieval с сообществами не проверялся и не мог быть
  проверен**: членства нет, любая выдача канала `community` пуста по
  определению. Отправок в чаты владельца в этой волне не было.
- **Не доказано**: качество/устойчивость сообществ, стабильность
  `community_id`, split/merge, ассоциативный поиск как гипотеза, UI-карта
  (MEMORY-08). Всё это остаётся `PENDING` в карте.
- Откат: кодовый (`release/2.58.166` @ `b2744b58`) + снимки
  `/tmp/predeploy-258167.db` и `/tmp/predeploy-258166.db`; схемный откат не
  нужен — старый код этих таблиц не читает, `DROP` не требуется.

## 6. Что MEMORY-07 ещё нужно (для снятия PENDING)

Построитель сообществ на backend по реальным узлам/рёбрам в chat scope с
весами (`confirmed`/`tentative`/`legacy`/`cooccurrence`), асинхронный
инкрементальный lifecycle с проверкой затронутых компонент и восстановлением
drift, подписи из реальных топ-сущностей с источниками и метриками, стабильность
структуры/`community_id` при split/merge, ассоциативный поиск как гипотеза без
перевода в «доказано», join активной сборки в retrieval и регистрация гейта —
то есть MEM-07.1…MEM-07.6 (все `PENDING`).

## 7. Провенанс

- `plans/features/memory-cognitive-02/reports/deploy-2.58.167.md` —
  sha256 `dc90b0d77136f765703b03b41fae67a2ca4c24d605e9daee4e531cbcdc3add89`
  (блоб из `d0a31235`, содержимое не изменялось).
- Прогон PM-пробы: `probe-0095544b1b/probe_v44_idempotency.py` +
  `probe_v44_idempotency.out` (временный run, закрывается после привязки;
  результаты перенесены в §4 этого артефакта).
