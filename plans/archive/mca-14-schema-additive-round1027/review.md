# `mca-14-schema-additive` — ревью (повторный единый gate волны 0 MCA, round 10.27)

> **Feature-ID:** `mca-14-schema-additive`. **Risk-Level:** **R3** (миграции/backup напрямую влияют на сохранность данных).
> **Status: Approved.**
> **Дата / агент:** 26.09.2026, @Reviewer (обе линзы в одном gate; Scanner отсутствует).
> **Deploy:** `DEFERRED_TO_RELEASE` (§20; изменения в рабочем дереве, коммитов НЕТ; `APP_VERSION` 2.58.31 без bump).
> **Цикл:** итер.1 — `Needs Fixes` (B-MCA14-1) → rework @Builder → **итер.2 — Approved** (binding новый).

## Binding (точное ревьюируемое состояние)

- **Git base:** HEAD `05bc8704c2de5e7de1d5d04ac34df763d35219aa` (intake round1027). Все изменения фичи — **не закоммичены**; ревью рабочего дерева.
- **Reviewed-Commit:** `05bc8704c2de5e7de1d5d04ac34df763d35219aa`.
- **Diff-SHA256 (`git diff --binary HEAD`):** `fbf2eea45be890fb32925b3de67d9039a92430971efb4ae4618c54ae64058299`.
- **Working-Tree-Hash (SHA-256 детерминированного манифеста 59 записей: staged/unstaged diff + содержимое untracked, каждая строка `path<TAB>sha256`, sha256 от join; исключены 7 артефактов ревью/workflow — 4 `review.md`, `plans/reports/full_audit_results.md`, `plans/reports/global_map.md`, `plans/workflow_state.md`):** `9cd581e4549e2fc0fd53599ade14b507b42f87e8a864899c3486e8d78b144a97`.
- **Product-Code-Hash (доп., `services/` + `config/` + `bot.py` + `tests/`, 37 записей):** `9d9254187b50c71b6067aa1ad52c4a3cdaad7c1579ee7ed780752a23fab64827`.
- **Spec-Hash:** `898a183de05e270856cbccd33c78f4a4cc074852ba764174f2677c4c4b343b6c` (изменён санкцией @Architect: REQ-08 `T-3759`→`T-3752/T-3754`).
- **ADR-1027-1-Hash:** `4765e26cda8e2a10c036843e520f68cb13303edae81c8ebdadbf17c1c3b553d3`.
- **tasks-Hash:** `a5717a1f90635f3ce49fef5a6ede6782d0ce0606fbd6796b47113e80d84a23f6`.

> Хэш рабочего дерева зафиксирован **до** записи этого `review.md`. Любая правка кода/спеки после фиксации делает вердикт stale.

## 1. Объём проверки

- **Requirements-линза:** REQ-MCA14-01…10 и SC-01…SC-13 (spec §2/§6), A28, конструкция Δ DDL v13/v14/v15, порядок по возрастанию, аддитивность/rollback-compat, R17-логи.
- **Focused change-audit:** `services/database.py` (`MigrationStep`, `migration_steps`, `_run_migrations`, `_ensure_migration_book`, `_migrate_schema_migrations_v13`, `_migrate_task_jobs_v14`, `_migrate_mca_events_v15`), `services/memory_backup.py::migration_backup` (+`_free_space_check`/`_read_back`), `services/disk_retention.py::prune_migration_backups`, `services/mca_gates.py`, `config/settings.py`.

## 2. Независимый прогон (факт)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **9588 passed, 0 failed** (1 FastAPI-deprecation warning; leaked aiosqlite — нет) |
| mca-14 suite | `pytest tests/test_mca14_schema_additive_round1027.py` | **17 passed** |
| JS vm-харнесс | `node` по всем 47 `tests/js/*.js` | **47/47 ok** |
| Git hygiene | `git diff --check` | чисто (exit 0) |

Числа совпадают с `evidence.md`/`mca-wave0-rework-evidence.md` (`9588/0`, `47/47`, mca-14 `17`).

## 3. Coverage REQ/SC → evidence

| REQ | SC | Evidence | Итог |
|---|---|---|---|
| REQ-01 аддитивные идемпотентные миграции | SC-01, SC-02 | `test_v13_book_and_user_version`, `test_idempotent_reinitialize_zero_duplicates`, `test_v14_v15_idempotent`, `test_legacy_v12_backfill` | ✅ |
| REQ-02 backup/WAL/место/read-back | SC-03, SC-04 | `test_migration_backup_created_and_readable/_insufficient_space`, `test_migration_fails_if_backup_fails` | ✅ |
| REQ-03 стабильные ID/unknown | SC-05 | `test_legacy_ids_preserved`, `test_new_nullable_columns_are_null` | ✅ |
| REQ-04 индексы по explain | SC-06 | v13 без индекса (PK=rowid); v14/v15 индексы под запросы; `test_v14_v15_indices_present` | ✅ |
| REQ-05 archive-job checkpoint/resume/unique | SC-07, SC-08 | `test_archive_job_checkpoint_resume`, `test_a51_takeover_no_duplicate` | ✅ (контракт; сам архив — волны 1–5) |
| REQ-06 rollback-compat | SC-09 | аддитивность + манифест evidence §4 | ✅ |
| REQ-07 kill-switch | SC-10 | `test_kill_switch_off_legacy_path`, `test_kill_switch_defaults_on` | ✅ |
| REQ-08 механизм Δ DDL | SC-11 | рамка §1.1 + реестр `MigrationStep`; spec-ссылка исправлена | ✅ |
| REQ-09 A28 (false-настройки→ON) | SC-12 | unit `test_kill_switch_defaults_on`; live — релизная (`mca-release`) | ⚠ допустимо (spec §8) |
| REQ-10 R17 логи/backup | SC-13 | `migration_backup`-лог без путей (только `target_version`); ошибки backup без путей | ✅ |

**tasks.md статусы правдивы.**

## 4. Проверка закрытия B-MCA14-1 (итер.1)

- **Локация фикса:** `services/database.py:1060-1064` (`_ensure_migration_book` без `PRAGMA`), `:1109-1130` (v13 фиксирует `user_version` только при `current < 13`), `:1080-1096` (цикл `version > current` по возрастанию).
- **Независимая проверка:** pre-call с установкой `user_version=13` **удалён**; книга создаётся helper'ом без изменения `user_version`; baseline-ряд для legacy `current>0`; версии применяются в порядке v1…v15. Тест `test_fresh_init_failure_on_early_step_recovers` инъектирует сбой на v1 свежей БД, проверяет `user_version != 13` после фейла и полное восстановление v1…v12 на повторе. **Закрыто.**
- **Остаточная неопределённость (не блокирует):** тест инъектирует сбой *до* тела v1, не проверяя частичный внутренний commit внутри `_migrate_*`; сами `_migrate_*` self-guarded/идемпотентны (ADR-1027-1 D1).

## 5. Проверка Lows (итер.1)

- **L-MCA14-1 [Low]:** исправлено — `prune_migration_backups` (`disk_retention.py:297-319`) ротирует `pre_migration_*.db` до 1 отдельно и не трогает daily-бэкапы; вызывается из `migration_backup`; тест `test_prune_migration_backups_keeps_one_and_spares_daily`. ✅
- **L-MCA14-2 [Low]:** исправлено — `_free_space_check` учитывает `-wal` (`memory_backup.py:211-215`). ✅
- **L-MCA14-3 [Low]:** санкционировано комментарием в `_run_migrations` (`:1083-1087`): runner работает до старта сервинга, прямые `execute+commit` безопасны. ✅
- **Nit @PM (REQ-08):** исправлено @Architect в spec (`T-3752, T-3754`). ✅

## 6. Focused audit coverage / counterexamples checked

- **Монотонность `user_version`:** fresh (0) → 1…15; legacy v12 → baseline + v13…v15; повторный `initialize` → 0 шагов. Понижения нет (v13 guard `<13`; v14/v15 исполняются только при `version>current`). ✅
- **Backup до шагов:** `if current > 0 and any(version>current)` → на fresh-БД backup не берётся (нечего), на legacy берётся до применения. ✅
- **Провал backup → отказ:** `migration_backup` бросает `MigrationBackupError` до `_ensure_migration_book`/шагов; тест подтверждает `user_version==12`, книга не создана. ✅
- **Аддитивность:** только `CREATE TABLE/INDEX IF NOT EXISTS`; старые таблицы/ID сохраняются (`test_legacy_ids_preserved`). ✅
- **R17:** новые логи `migration_backup`/`prune_migration_backups` — без путей/секретов (только `target_version`/имя файла в дневной ротации — pre-existing). ✅

## 7. Blocking findings

**Нет.** B-MCA14-1 закрыт; новых блокеров не выявлено.

## 8. Non-blocking (Low / debt)

- **L-MCA14-4 [Low, doc]:** spec D5-подобная нестыковка отсутствует; нит: `test_migration_backup_insufficient_space` переопределяет `shutil.disk_usage` глобально (работает, т.к. `_free_space_check` импортирует `shutil` локально) — на будущее безопаснее патчить `_free_space_check`.
- **Unavailable (релизные, вне gate):** live A28 на БД с сохранёнными false-настройками и mutation smoke — на `mca-release` (spec §8); полный матричный smoke legacy v1…v11 (threat §Остаточные риски).

## 9. Вывод

Фича соответствует spec/ADR, Δ DDL=v13/v14/v15 аддитивен и монотонен, backup перед миграцией и восстановление fresh-БД работают; независимый полный прогон зелёный. **Approved** на binding выше. Merge §93+ и `ADR-1027-1 → Accepted` — за @Architect по факту завершения волны.
