# `mca-14-schema-additive` — evidence (Step 4 @Builder, волна 0, сессия 1)

> **Фича-ID:** `mca-14-schema-additive`. **Сессия:** ядро v13 (T-3754/3755/3756/3758/3759).
> **Дата:** 26.09.2026. **Risk:** R3. **Deploy:** `DEFERRED_TO_RELEASE`.
> **Коммиты:** НЕ делались. **R17/R18:** секреты/полные пути не логируются.

## 1. Baseline / рабочее дерево

- **Анкер откатa:** `05bc8704c2de5e7de1d5d04ac34df763d35219aa`.
- **Текущий HEAD:** тот же — коммитов нет, правки в рабочем дереве.
- **`APP_VERSION`:** `2.58.31` без bump.
- **Δ DDL:** **v13** — `CREATE TABLE schema_migrations(version INTEGER PRIMARY
  KEY, name TEXT NOT NULL, applied_at INTEGER NOT NULL, checksum TEXT NOT NULL)`.
  Индексы не добавляются (`version` — rowid-алиас; EXPLAIN не требуется).
  **Δ каталога = 0**; PG — no-op.

## 2. Изменённые / созданные файлы

- `services/database.py` — `MigrationStep`, `migration_steps()`,
  `_run_migrations()`, `_migrate_schema_migrations_v13()`; `initialize()`
  роутится через runner (kill-switch) либо legacy-путь.
- `services/memory_backup.py` — `migration_backup()` (`VACUUM INTO` +
  free-space + read-back, R17-safe), `MigrationBackupError`.
- `config/settings.py` — `MCA_SCHEMA_MIGRATIONS_ENABLED` (env-only ClassVar).
- `services/mca_gates.py` — реестр `KILL_SWITCHES` + резолвер.
- `tests/test_mca14_schema_additive_round1027.py` (11 тестов).

## 3. Тесты (фактические числа)

| Прогон | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **9542 passed, 0 failed** |
| Новые mca-14 | `pytest tests/test_mca14_schema_additive_round1027.py` | **11 passed** |
| JS vm-харнесс | `node tests\js\*.js` | **47/47 ok** |

### Покрытые сценарии (SC)
- **SC-01:** legacy v12 → `user_version`=13; книга содержит baseline-ряд + v13;
  повторный прогон — 0 дублей.
- **SC-02:** свежая БД → та же версия/книга.
- **SC-03:** backup `VACUUM INTO`; недостаток места → явная ошибка, миграция не
  применена (нет частичного применения).
- **SC-04:** read-back копии `integrity_check=ok` + совпадение `user_version`.
- **SC-05:** legacy ID сохранены; новые nullable = NULL.
- **SC-10:** kill-switch OFF → legacy-путь, книги нет, `user_version`=12.

## 4. Rollback-build manifest (T-3758)

- **Совместимый откат кода:** `git revert`/`stash` → `05bc870` безопасен —
  `schema_migrations` аддитивна, старые таблицы/ID не тронуты, код не читает
  книгу при отсутствии runner'а (`MCA_SCHEMA_MIGRATIONS_ENABLED` OFF-путь).
- **Hot-откат:** `MCA_SCHEMA_MIGRATIONS_ENABLED=false` → legacy `_migrate_*`.
- **Backup restore:** только аварийный сценарий (не штатный переключатель).
- **Несовместимая версия:** forward fix / исправленный rollback build.

## 5. Остаётся / блокеры

- **T-3757 (archive-job на `task_jobs`)** — после T-3740 (v14, mca-01).
- **T-3760/T-3761 (smoke+A28 / R17-интеграция)** — T-3761 зависит от T-3767
  (`mca-13`); следующий батч/сессия.
- **v14 (`task_jobs`)/v15 (`mca_events`)** — свои фичи добавляют строки реестра.

## 6. Rework по review (B-MCA14-1, L-MCA14-1…3)

> Вход: `review.md` (Needs Fixes), `plans/features/mca-wave0-rework-instructions.md`.
> Binding ревью (Reviewed-Commit `05bc870`, wt `cc7e3c0a`) после rework — stale;
> re-review обязателен. Δ DDL/Δ каталога/`APP_VERSION` без изменений.

### B-MCA14-1 (Medium) — порядок `user_version` — исправлено

- `_run_migrations()` больше **не** вызывает pre-call `_migrate_schema_migrations_v13()`
  (тот безусловно ставил `user_version=13` до шагов v1…v12): книга создаётся
  отдельным `_ensure_migration_book()` (**без** `PRAGMA user_version`), а
  версию v13 фиксирует сам шаг v13 в общем цикле **после** v12; v13 ставит 13
  только если текущая версия `< 13` (монотонность, не понижает v14/v15).
- На fresh-БД сбой на v1 оставляет `user_version=0` (не 13) → повторный
  `initialize()` доводит схему до целевой, v1…v12 не пропускаются.
- Тест: `test_fresh_init_failure_on_early_step_recovers` (инъекция сбоя в v1 →
  `user_version != 13` → restart → target + `schema_migrations` v13 + схема).
- Legacy v12 (целевой прод-апгрейд) — без изменений (v1…v12 пропускаются
  штатно, backup до шагов).

### Lows

- **L-MCA14-1** — исправлено: `disk_retention.prune_migration_backups()`
  матчит реальный паттерн `pre_migration_*.db` (ротация до 1), daily-бэкапы
  (`local_database_*`/`memory_rebuild_*`) не трогаются; вызов из
  `memory_backup.migration_backup` (test:
  `test_prune_migration_backups_keeps_one_and_spares_daily`).
- **L-MCA14-2** — исправлено: free-space учитывает `-wal`-файл
  (`db_path.stat().st_size` + WAL) перед `VACUUM INTO`.
- **L-MCA14-3** — зафиксировано: прямые `execute+commit` в `_run_migrations`
  — санкционированное исключение (этап `initialize()` до старта сервинга, нет
  конкурентных писателей); комментарий в коде.
- **Ниты @PM (зона @Architect, не правились):** `spec.md` REQ-MCA14-08
  ссылается на `T-3759` вместо `T-3752`.

### Числа (rework)

| Прогон | Результат |
|---|---|
| `tests/test_mca14_schema_additive_round1027.py` | **17 passed** |
| Полный pytest | см. `../mca-wave0-rework-evidence.md` (финальные числа волны 0) |
| JS-харнесс | 47/47 ok (волна 0) |
