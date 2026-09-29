# `mca-14-schema-additive` — threat / failure analysis (R3, ядро v13)

> **Risk:** R3 (миграции/backup напрямую влияют на сохранность данных).
> **Объём:** реализованное в сессии 1 (T-3754/3755/3756/3758/3759).

## Блок G — модель угроз и отказов

| # | Угроза / отказ | Механизм защиты | Тест / доказательство |
|---|---|---|---|
| G1 | Повторный прогон миграции создаёт дубли/повреждает данные | double-idempotency: guard `version > current` + self-guard шага | `test_idempotent_reinitialize_zero_duplicates` |
| G2 | Legacy-БД (v1…v12) переисполняет старые шаги | `version > current` пропускает v1…v12; baseline-ряд в книге | `test_legacy_v12_backfill` |
| G3 | Частичное применение при провале (нет backup/места) | backup ДО шагов; провал → явная ошибка, ничего не применено | `test_migration_fails_if_backup_fails`, `test_migration_backup_insufficient_space` |
| G4 | Копия БД без учёта WAL (потеря свежих данных) | `VACUUM INTO` (WAL-консистентно), не `copy` файла | `test_migration_backup_created_and_readable` |
| G5 | Неконсистентная/битая копия принята за backup | read-back: `integrity_check=ok` + совпадение `user_version` | `test_migration_backup_created_and_readable` |
| G6 | Утечка пути/имени копии в логи (R17) | логи без путей (только «created + read-back ok») | ревью кода `memory_backup.migration_backup` |
| G7 | Переименование/удаление старых таблиц | только аддитивный `CREATE TABLE IF NOT EXISTS` | `test_legacy_ids_preserved` |
| G8 | Выдуманный источник вместо честного unknown | новые nullable = NULL | `test_new_nullable_columns_are_null` |
| G9 | OFF-путь незаметно меняет поведение | OFF → legacy `_migrate_*`, книги нет, v12 | `test_kill_switch_off_legacy_path` |
| G10 | Rollback кода теряет новые данные | аддитивность; `schema_migrations` безвредна | manifest §4 evidence |

## Остаточные риски (открыты)

- **T-3757 archive-job** не реализован (ждёт `task_jobs` v14) — длинная
  транзакция на диапазон не устранена для архивных job'ов.
- **A28** (деплой на БД с сохранёнными false-настройками) — релизная проверка
  на `mca-release`, вне рамок фичи.
- **T-3760/T-3761** (smoke+R17-интеграция, события MCA-13) — следующий батч.
- Широкий legacy-охват (разные v1…v11 фикстуры) — покрыты точечно; полный
  матричный smoke — T-3760.


## Сессия 2 — дополнительные угрозы/защиты (v14/v15 через реестр)

| # | Угроза / отказ | Механизм защиты | Тест |
|---|---|---|---|
| G11 | Прямой ALTER вне реестра (v14/v15) | только строки `MigrationStep` (v14 `task_jobs`, v15 `mca_events`) | `test_v14_v15_tables_and_order` |
| G12 | Повтор v14/v15 создаёт дубли | `CREATE TABLE/INDEX IF NOT EXISTS` + `version > current` + книга | `test_v14_v15_idempotent` |
| G13 | Понижение `user_version` при повторном initialize | `_migrate_schema_migrations_v13` ставит 13 только если `< 13` | `test_idempotent_reinitialize_zero_duplicates`, `test_v14_v15_idempotent` |
| G14 | Legacy v12 без v14/v15 | последовательное применение v13→v14→v15 | `test_legacy_v12_gains_v14_v15` |

### Остаточные риски (сессия 2, открыты)
- A28 (live на БД с false-настройками) — релизная проверка `mca-release`.
- R17-интеграция стадий миграции/backup в MCA-17a — следующая фича (T-3761).

## Rework по review (B-MCA14-1, L-MCA14-1…3)

| # | Угроза / отказ | Механизм защиты | Тест |
|---|---|---|---|
| G13a | Преждевременная фиксация `user_version=13` до v1…v12 → на fresh-БД при сбое повторный `initialize()` пропускает шаги (немонотонность + окно невосстановимости) | книга создаётся `_ensure_migration_book()` без `PRAGMA user_version`; версию v13 фиксирует сам шаг в общем цикле после v12 (и только если `< 13`) | `test_fresh_init_failure_on_early_step_recovers`, `test_v13_book_and_user_version` |
| G15 | `pre_migration_*` копии копятся, а ротация трогает daily-бэкапы (L-MCA14-1) | отдельный `prune_migration_backups` по реальному паттерну `pre_migration_*.db` (keep=1); daily-префиксы не матчатся | `test_prune_migration_backups_keeps_one_and_spares_daily` |
| G16 | Оценка свободного места занижена в WAL-тяжёлом состоянии (L-MCA14-2) | free-space учитывает `-wal`-файл до `VACUUM INTO` | `test_migration_backup_insufficient_space` (free-space guard) |
