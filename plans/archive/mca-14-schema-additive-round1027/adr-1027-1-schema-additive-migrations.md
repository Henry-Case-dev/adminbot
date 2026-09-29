# ADR-1027-1 — `mca-14-schema-additive`: аддитивный идемпотентный migration-runner с реестром/версиями, backup с WAL + free-space + read-back, стабильные ID и честный unknown, индексы по explain, rollback-compat (rollback build / forward fix), единая kill-switch-политика и **механизм заявки Δ DDL для всего эпика** — Δ DDL = v13 (`schema_migrations`), Δ каталога = 0, R3

- **Статус:** **✅ Accepted** — фактом мержа волны 0 MCA (round 10.27, 26.09.2026) в `plans/ARCHITECTURE.md` **§93** (`mca-14-schema-additive`). На момент Step 2 @Architect — Proposed; Accepted только по Merge.
- **Фича:** `mca-14-schema-additive` (Wave 0, P0-enabler). **Deploy:** `DEFERRED_TO_RELEASE` (§20).
- **ТЗ-основание:** `plans/current_task.md` §18 (`:856–872`), §20.1 п.3–4, §22; приёмка §19 **A28**; R17/R18.
- **Baseline:** HEAD `7165ff7`; `APP_VERSION` 2.58.31; SQLite DDL **v12**; каталог `473/430/448/102/100/21`; канон 12.
- **Связано:** REUSE `services/memory_backup.py` (VACUUM INTO), `services/database.py` (existing `_migrate_*`), ADR-1024-18/F0.5 (`DB_LOCK_RESILIENCE_ENABLED` — не дублировать); AMEND `services/database.py::initialize`; контракт-мост с `mca-01`/`mca-13`; рамка `plans/docs/mca-round1027-arch-frames.md`.

## Контекст

§18 требует: аддитивные идемпотентные обновления схемы с отдельной версией; **сначала backup согласованно с БД (с учётом WAL)**, затем проверка свободного места и применение; не переименовывать/не удалять старые таблицы; стабильные ID старой памяти; новые `nullable`-поля = честный unknown; индексы по реальным запросам и `explain`; архивные jobs без долгой транзакции с checkpoint/resume и уникальными ключами; совместимый откат кода оставляет новые данные (rollback build / forward fix; backup restore — аварийный); оперативный kill-switch у каждой функции, релиз — ON, OFF фиксируется с причиной/временем/планом.

**Фактическое состояние baseline (сверено с рабочей веткой).**
- Миграции — **hardcoded-последовательность** вызовов `_migrate_*` в `DatabaseService.initialize()` (`services/database.py:640–651`); каждый шаг идемпотентен self-guard'ом (`sqlite_master`/`PRAGMA table_info`) и ставит `PRAGMA user_version` (`:77–113`; текущая цель **v12**, `_migrate_graph_facts_metadata_v12` `:1446–1492`). Книги применённых миграций нет.
- Backup — **уже есть** консистентный `VACUUM INTO` (`memory_backup.py:110`) с fallback `sqlite3 .backup`; но он **не** привязан к применению миграции, нет free-space-проверки и read-back копии.
- `DB_LOCK_RESILIENCE_ENABLED`/F0.5 (ADR-1024-18) — существующий env-only `ClassVar` kill-switch (`config/settings.py:1277`), `write_transaction` с single-writer lock. **Не дублируется.**
- PG (`pg_db.py`) — идемпотентный `CREATE TABLE IF NOT EXISTS` при старте; новых PG-таблиц не требуется (GEN-R4).

## Решения

**D1. Версия схемы и migration-runner: реестр шагов + книга `schema_migrations`; Δ DDL = v13.**
- **Выбрано:** заменить hardcoded-последовательность на **регистрируемый** runner. `MigrationStep{version:int, name:str, apply}`; `_run_migrations()`: `current = PRAGMA user_version`; применить шаги `version > current` по возрастанию; писать `schema_migrations(version, name, applied_at, checksum)`; фиксировать `user_version`. Legacy-БД (v1…v12 без книги) → back-fill baseline-ряда, шаги v1…v12 не переисполняются.
- **Обоснование:** (i) параллельная разработка волн не будет конфликтовать в общей последовательности — фича добавляет **свою** строку реестра; (ii) двойная идемпотентность (`version >` + self-guard) — безопасный повтор; (iii) сохраняется существующий контракт `PRAGMA user_version` и все `_migrate_*`; (iv) книга даёт аудит/дрейф-детект (`checksum`).
- **Альтернатива:** оставить hardcoded и добавлять `_migrate_v13()` вручную — отклонено: каждое последующее Δ DDL требовало бы правки общей функции, конфликты мержа, нет реестра/аудита.

**D2. Backup с WAL, free-space и read-back: `VACUUM INTO` + проверки, ДО применения шага.**
- **Выбрано:** backup — **`VACUUM INTO`** (REUSE `memory_backup.py`), даёт консистентную копию включая WAL одним файлом; **free-space check** (`shutil.disk_usage` ≥ размер БД × коэффициент) до применения; **read-back** копии read-only (`PRAGMA integrity_check == ok`, совпадение `user_version`); провал любой проверки → отказ применять (никакого частичного применения). Копия одного файла без WAL — запрещена.
- **Обоснование:** §18 verbatim «не копировать один основной SQLite-файл без учёта WAL»; VACUUM INTO уже проверен на живой БД + fallback; read-back закрывает «резервная копия читается».
- **Альтернатива:** `shutil.copy` БД+`-wal`+`-shm` — отклонено (гонка, сложность); только `integrity_check` без read-back — отклонено (не доказывает читаемость).

**D3. Стабильные ID/таблицы и честный unknown.**
- **Выбрано:** старые таблицы/ID не переименовываются/не удаляются; rebuild-миграции (если понадобятся в других фичах) сохраняют **все** колонки и `id`; новые `nullable`-поля = `NULL`/`unknown` (не выдуманный источник); FTS/vec валидны.
- **Обоснование:** §18 verbatim; политика DDL `project.md:62`; R16 (id — ключ, не имя).
- **Альтернатива:** «чистка» таблиц пересозданием — запрещено.

**D4. Archive-job: короткая транзакция, checkpoint/resume, уникальный ключ; контракт общий с `mca-01`.**
- **Выбрано:** долгая работа = чтение → (LLM) → **короткая запись** через общий write-механизм (`mca-01`); транзакция не держится на диапазон; checkpoint после фиксации; уникальный ключ против повторного применения/параллельного старта. Durable-состояние — в `task_jobs` (`mca-01`/v14), поля `coalesce_key`/`generation`/`fencing_token`/`heartbeat_at`. Второго job-механизма нет.
- **Обоснование:** §18 + §5.2; REUSE прецедента `DossierRebuildJobStore` (файловый store с retention/registry) — но канонической durable-очередью становится `task_jobs` (транзакционно интегрируема, coalescing, bounded SQL).
- **Альтернатива:** собственный archive-job-store в `mca-14` — отклонено (дубль механизма).

**D5. Индексы — только по реальным запросам/explain.**
- Каждый индекс обосновывается `EXPLAIN QUERY PLAN` конкретного запроса в spec фичи-владельца; «все комбинации» запрещены. Для `mca-14` индексов нет (книга реестра — primary key).

**D6. Rollback-compat: аддитивность + rollback build / forward fix; restore — аварийный.**
- **Выбрано:** совместимый откат кода оставляет новые данные (аддитивные таблицы/колонки безвредны). Для несовместимой версии — **исправленный rollback build** или **forward fix**, не откат БД. Манифест rollback-build обязателен (T-3758). Backup restore — только аварийный сценарий.
- **Обоснование:** §18 verbatim; R18 (бэкапы/теги не удалять).

**D7. Единая kill-switch-политика и имена волны 0.**
- **Выбрано:** **env-only `ClassVar[bool] = _env_bool("NAME", True)`**, резолв per-call, никогда не бросает, OFF = паритет baseline; Δ каталога = 0. Имена волны 0 — в рамке §3. Для `mca-14`: `MCA_SCHEMA_MIGRATIONS_ENABLED`. OFF фиксируется в release-manifest/логе с причиной/временем/планом.
- **Обоснование:** §18 + §20.2 «релиз со всеми ON»; прецедент `DB_LOCK_RESILIENCE_ENABLED`/ADR-1026-22 D3; env-only → нет UI-параметра → F8 не запускается.
- **Альтернатива:** каталожный тумблер — отклонено (Δ каталога ≠ 0 без пользы).

**D8. Механизм объявления Δ DDL для всего эпика.**
- **Выбрано:** версии бронируются в `plans/docs/mca-round1027-arch-frames.md`; DDL-фича обязана заявить точные `CREATE/ALTER/INDEX` + версию + `nullable`/default + обратный путь и получить санкцию @Architect до Build; самовольный DDL запрещён. Волна 0: v13 (`schema_migrations`), v14 (`task_jobs`), v15 (`mca_events`).
- **Обоснование:** снимает вопрос §6.2 PM (агрегатная санкция Δ DDL) и риск конфликтов; соответствует §20 («совместимая схема»).

**D9. Δ каталога = 0; F8 не переиздаётся.**
- Новых параметров нет (env-only `ClassVar`), `param_catalog.py` вне diff, счётчики/`sha256`-пин без изменений. Правило F8-переиздания для последующих волн — рамка §2.

## Санкции и вердикты

- **Δ DDL = v13** — `schema_migrations` (одна книга реестра). PG — no-op. Старые таблицы/ID не трогаются.
- **Δ каталога = 0**; F8 (ADR-1026-2) **NOT_APPLICABLE**.
- **Kill-switch:** `MCA_SCHEMA_MIGRATIONS_ENABLED` (env-only, default ON); OFF → legacy-путь (паритет).
- **Risk:** **R3** (сохранность данных); `threat-failure-analysis.md` обязателен (Блок G). Триггеры понижения: доказанная полная аддитивность/идемпотентность/read-back на реальных БД — @Reviewer.
- **Обратный путь:** hot — env OFF; cold — `git revert` → `7165ff7`; `schema_migrations`/новые таблицы безвредны; restore — аварийный.
- **Release policy:** `DEFERRED_TO_RELEASE`.

## AMEND / REUSE-карта

| ADR / артефакт | Статус | Суть |
|---|---|---|
| `services/database.py::initialize` + `_migrate_*` | **AMEND** | hardcoded → реестр шагов; тела `_migrate_*` переиспользуются; `user_version` сохраняется |
| `services/memory_backup.py` (VACUUM INTO) | **REUSE** | backup-паттерн + fallback; добавляются free-space/read-back |
| ADR-1024-18 / F0.5 `DB_LOCK_RESILIENCE_ENABLED` | **REUSE / не дублировать** | существующий kill-switch уважается |
| `services/dossier_rebuild_jobs.py` | **REUSE (прецедент)** | durable job-store/retention/registry; канон — `task_jobs` (mca-01) |
| `project.md` политика DDL | **REUSE** | идемпотентность/сохранение id/обратный путь |
| ADR-1026-2 (F8) | **NOT_APPLICABLE** | Δ каталога = 0 |
| `mca-01`/`mca-13`/волны 1–5 | **Unblocks** | механизм Δ DDL/версии |

| Решение | Задачи |
|---|---|
| D1 (runner/v13) | T-3754 |
| D2 (backup/WAL/read-back) | T-3755 |
| D3 (ID/unknown) | T-3756 |
| D4 (archive-job) | T-3757 |
| D5 (индексы) | T-3758 |
| D6 (rollback-compat) | T-3758 |
| D7 (kill-switch) | T-3759 |
| D8 (механизм Δ DDL) | T-3752, T-3754 |
| D9 (Δ каталога=0) | T-3759 |
| A28/тесты | T-3760, T-3761 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Механизм миграций | hardcoded; реестр+книга | **реестр+книга** | параллельные волны, аудит, идемпотентность |
| Backup | copy файла; VACUUM INTO | **VACUUM INTO** | WAL-консистентность; REUSE; fallback |
| Read-back | нет; integrity+user_version | **integrity+user_version** | §18 «копия читается» |
| Archive-job дом | новый store; `task_jobs` | **`task_jobs`** (mca-01) | один механизм, транзакционность |
| Kill-switch | каталожный; env-only | **env-only ClassVar** | Δ каталога=0; hot-откат |
| Откат | restore БД; rollback build/forward fix | **rollback build/forward fix** | §18 verbatim; новые данные сохраняются |
| Risk | R2; R3 | **R3** | сохранность данных/backup/migration |

## Последствия

- Новые DDL-фичи заявляют версию в рамке и проходят backup+read-back; схема растёт аддитивно, `id`/таблицы сохранены, старые данные не теряются.
- Повторный запуск миграций — no-op; книга `schema_migrations` даёт аудит/дрейф-детект.
- Откат кода безопасен (новые данные остаются); restore БД — только аварийный сценарий.
- Δ каталога=0, F8 не переиздаётся; risk R3 + threat-артефакт; deploy `DEFERRED_TO_RELEASE`.

## Ссылки

- `plans/features/mca-14-schema-additive/{spec.md, tasks.md}` (spec — T-3752; сверка — @PM T-3753).
- Рамка: `plans/docs/mca-round1027-arch-frames.md` (§1 Δ DDL, §2 каталог/F8, §3 kill-switch, §4 нумерация).
- Код: `services/database.py` (`:77–113`, `:640–651`, `:1446–1492`); `services/memory_backup.py:110`; `services/dossier_rebuild_jobs.py:242`; `config/settings.py:1277`.
- ТЗ: `plans/current_task.md` §18 (`:856–872`), §20.1 (`:996–997`), §19 A28 (`:909`).
- Архитектура: merge → §93 (после §92).
- Точка отката: коммит `7165ff7` (пер-фичевых тегов нет).
