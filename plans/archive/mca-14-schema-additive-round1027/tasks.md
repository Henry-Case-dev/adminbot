# `mca-14-schema-additive` — MCA-14: схема, совместимость и восстановление (round 10.27)

> **Статус:** 🟦 PLANNING — Step 1 @PM. Код НЕ менялся. Secret-дисциплина (R17/R18).
> **Эпик:** Раунд 10.27 `memory-context-autonomy` (MCA), **Wave 0** (фундамент, dependency root для data-фич). **Фича-ID:** `mca-14-schema-additive`.
> **Тип:** data/infra — аддитивные миграции, backup, rollback-compat, kill-switch-политика. **P0-enabler** (все последующие DDL-изменения идут через этот механизм).
> **ТЗ-источник (IMMUTABLE):** `plans/current_task.md` v1.8, **§18** «MCA-14 — схема, совместимость и восстановление» (`:856–872`); §2.3/§2.6 (`:23`, `:26`); §20.1 п.3–4 (`:996–997`); §22 (`:1066`); проверка §19 **A28**.
> **Приёмочный ориентир §19:** **A28** (новый деплой на БД с сохранёнными false-настройками → все новые согласованные функции реально включены).
> **Зависимости:** нет обязательных предшественников. **Потребляется:** `mca-01` (durable jobs), `mca-03`/`mca-04a/b` (SourceRef/EvidenceLink/backfill), `mca-17a` (process-registry/span/incident), `mca-10a` (draw/buffer), `mca-16` (experience/lessons), `mca-18` (SelfModel/traits), `mca-19` (MediaAsset/MediaAnalysis), `mca-20` (ClaimEnvelope/verdict-cache). **Совместно с Wave 0:** `mca-13` (event-контракт), `mca-01` (транзакции). **Порядок применения Δ DDL волны 0:** v13 (`mca-14`) → v14 (`mca-01`) → v15 (`mca-13`) по возрастанию. T-3757 использует durable `task_jobs` (T-3740, `mca-01`) — мягкая связка `mca-14` → `mca-01` → `mca-14` без жёсткого цикла (T-3754 → T-3740 → T-3757).
> **Baseline (Step 0 @Memory, 26.09.2026):** HEAD `7165ff7`; `APP_VERSION` **2.58.31**; SQLite DDL **v12** (следующая версия — по решению @Architect); каталог **473/430/448/102/100/21**; канон **12**; pytest **9513/0** + JS **47/47** (прошлый verified). **Deploy — `DEFERRED_TO_RELEASE`.** Точка отката — анкер `7165ff7` + backup-копия БД.
> **Risk — `R3`** (санкция @Architect ADR-1027-1; binding-reviewed-commit — @Reviewer): миграции/backup напрямую влияют на сохранность данных. При R3 — `threat-failure-analysis.md` (Блок G).
> **Числа (финал, санкция @Architect — ADR-1027-1 D8/D9):** **Δ DDL = v13** (`schema_migrations`; волна 0 — v13/v14/v15, применение по возрастанию версии); **Δ каталога = 0** (F8 NOT_APPLICABLE); `APP_VERSION` без bump.

## Трассируемость (REQ → verbatim §ТЗ → блок → задачи → приёмка)

| REQ | Источник (verbatim, `current_task.md`) | Блок | Задачи | SC (спека) | ADR-1027-1 (D) | Приёмка |
|---|---|---|---|---|---|---|
| MCA14-R1 | §18 «Аддитивные идемпотентные обновления схемы с отдельной версией. Сначала backup согласованным для используемой БД способом, затем проверка свободного места и применение. Не копировать один основной SQLite-файл без учёта WAL.» (`:864`) | B, C | T-3754, T-3755 | SC-01…SC-04 | D1, D2 | A28 |
| MCA14-R2 | §18 «Стабильные ID старой памяти сохраняются. Новые nullable поля получают честный unknown… Индексы добавлять по реальным запросам и explain.» «Не переименовывать и не удалять старые таблицы.» (`:864–866`) | D | T-3756, T-3758 | SC-05, SC-06 | D3, D5 | A28, A87 |
| MCA14-R3 | §18 «Архивные jobs не держат долгую транзакцию на весь диапазон. Чтение, LLM и короткая запись разделены. При прерывании задача продолжает с последнего подтверждённого checkpoint. Уникальные ключи защищают повторное применение и параллельный старт.» (`:868`) | E | T-3757 | SC-07, SC-08 | D4 | A02, A51, A89 |
| MCA14-R4 | §18 «Совместимый откат кода должен оставлять новые данные. Если предыдущая версия несовместима… подготовить исправленный rollback build или forward fix… Backup restore — аварийный сценарий.» (`:870`) | F | T-3758 | SC-09 | D6 | A28 |
| MCA14-R5 | §18 «Все функции имеют оперативный kill switch для аварии, но релиз запускается с ними включёнными. Отключение из-за подтверждённого сбоя фиксируется… нельзя объявить задачу завершённой с молча отключённой функцией.» (`:872`) | F | T-3759 | SC-10 | D7 | A28 |
| MCA14-R6 | §18 + рамка §1.1 (D8): механизм брони/санкции Δ DDL для всего эпика | A, B | T-3752, T-3754 | SC-11 | D8 | gate |
| MCA14-R7 | §17.3 R17; §19 A53: логи миграций/backup без секретов/путей; события по `mca-13` | G | T-3761 | SC-13 | D2, D7 | A53 |
| MCA14-ACC | A28 (§19): новый деплой на БД с сохранёнными false-настройками → функции включены | G | T-3760 | SC-12 | D2, D7 | A28 |

**Соответствие ID:** табличные `MCA14-R1…R5` ↔ спека `REQ-MCA14-01…07`; `MCA14-R6` ↔ `REQ-MCA14-08`; `MCA14-R7` ↔ `REQ-MCA14-10`; `MCA14-ACC` ↔ `REQ-MCA14-09`.

## Карта решений ADR-1027-1 → задачи (сверка @PM, T-3753)

| Решение ADR-1027-1 | Суть | SC | Задачи |
|---|---|---|---|
| D1 (runner/v13) | реестр шагов + `schema_migrations`; двойная идемпотентность; legacy back-fill | SC-01, SC-02 | T-3754 |
| D2 (backup/WAL/read-back) | `VACUUM INTO` + free-space + `integrity_check`/`user_version` | SC-03, SC-04 | T-3755 |
| D3 (ID/unknown) | сохранение ID/таблиц; nullable = `NULL`/unknown | SC-05 | T-3756 |
| D4 (archive-job) | короткая tx/checkpoint/resume/уникальный ключ; `task_jobs` (mca-01) | SC-07, SC-08 | T-3757 |
| D5 (индексы) | только по `EXPLAIN QUERY PLAN` | SC-06 | T-3758 |
| D6 (rollback-compat) | rollback build/forward fix; restore — аварийный | SC-09 | T-3758 |
| D7 (kill-switch) | env-only `MCA_SCHEMA_MIGRATIONS_ENABLED`; OFF фиксируется | SC-10 | T-3759 |
| D8 (механизм Δ DDL) | бронь версий в рамке + санкция @Architect | SC-11 | T-3752, T-3754 |
| D9 (Δ каталога=0) | F8 NOT_APPLICABLE | — | T-3759 |
| A28/R17 | migration smoke/A28 + R17-логи | SC-12, SC-13 | T-3760, T-3761 |

## Приёмочные инварианты MCA-14 (нарушение = НЕ принято)

1. Любое обновление схемы — аддитивное, идемпотентное, с отдельной версией; повторный прогон не создаёт дублей. **MCA14-R1; T-3754.**
2. Перед применением — backup, согласованный с БД (учёт WAL), с проверкой чтения копии; при недостатке места — явная ошибка, а не частичное применение. **MCA14-R1; T-3755.**
3. Старые ID/таблицы сохраняются; новые nullable-поля = честный unknown (не выдуманный источник). **MCA14-R2; T-3756.**
4. Индексы — по реальным запросам (explain), не «все комбинации». **MCA14-R2; T-3758.**
5. Архивные jobs без долгой транзакции; resume с checkpoint; уникальные ключи против повторного применения/параллельного старта. **MCA14-R3; T-3757.**
6. Несовместимый откат кода запрещён: rollback build / forward fix; backup restore — аварийный сценарий. **MCA14-R4; T-3758.**
7. У каждой функции есть оперативный kill-switch (env-only, default ON); OFF не оставляет «молча отключённую» функцию без фиксации причины. **MCA14-R5; T-3759.**
8. A28: на БД с сохранёнными false-настройками все согласованные функции реально включаются (недостаточно новых defaults). **T-3760.**
9. Deploy `DEFERRED_TO_RELEASE`; R17: значения секретов/пути не логируются. **T-3761.**

## Блок 0 — Step 0 / baseline (T-3750) + Step 1 (T-3751)

- [ ] **T-3750 [@Memory/@Orchestrator — подтверждение Step 0]** — **Цель:** зафиксировать baseline (HEAD `7165ff7`, 2.58.31, SQLite v12, каталог, канон 12, pytest/JS). **Выход:** подтверждение в KG/`workflow_state`. **Критерий:** baseline-анкер/точка отката согласованы. **Зависимости:** Step 0 ✅.
- [ ] **T-3751 [@PM — Step 1: `tasks.md`]** — **Цель:** разложить §18, создать этот файл. **Выход:** `plans/features/mca-14-schema-additive/tasks.md`. **Критерий:** REQ/инварианты/блоки согласованы; орфанов нет. **Зависимости:** T-3750.

## Блок A — Step 2 spec + ADR / сверка (T-3752…T-3753)

- [ ] **T-3752 [@Architect]** — **Цель:** `spec.md` (REQ-MCA14-01…; границы с MCA-13/17) + **новый ADR**. Решения: (i) следующая schema-версия и migration-runner (идемпотентный, версионируемый); (ii) backup-механизм с учётом WAL + проверка чтения; (iii) политика nullable/unknown и стабильных ID; (iv) индекс-политика (explain); (v) контракт archive-job (checkpoint/уникальный ключ/resume), разделяемый с `mca-01`; (vi) rollback-build/forward-fix контракт; (vii) единая kill-switch-политика (env-only `ClassVar`, имена/default ON, OFF-паритет); (viii) агрегатная Δ DDL/Δ каталога-санкция по всем фичам; (ix) финальный Risk. **Выход:** `spec.md` + ADR (Proposed). **Критерий:** каждый REQ имеет SC; §18 не сужен. **Зависимости:** T-3751.
- [x] **T-3753 [@PM — сверка]** — **Цель:** сверка `tasks.md` ↔ `spec.md` ↔ ADR; SC/ADR-колонки; вердикт. **Выход:** `PLANNING_CONSISTENT` либо список расхождений. **Критерий:** scope/risk/приёмка/rollback согласованы. **Зависимости:** T-3752. — **Вердикт Step 2b @PM (26.09.2026): PLANNING_CONSISTENT** (SC/ADR-колонки заполнены и совпадают; scope/исключения/risk R3/приёмка A28/deploy `DEFERRED_TO_RELEASE`/rollback согласованы; 1 неблокирующее редакционное расхождение — REQ-MCA14-08: в `spec.md` задачи `T-3754, T-3759`, в `tasks.md`/ADR-1027-1 (D8) — `T-3752, T-3754`); детали — `plans/features/mca-wave0-reconciliation.md`.

## Блок B — аддитивные идемпотентные миграции (T-3754)

- [x] **T-3754 [@Builder — migration framework]** — **Цель:** отдельная версия схемы + идемпотентный аддитивный аппликатор; повторный прогон не создаёт дублей; совместимость с существующим механизмом migrations (`services/database.py`). **Выход:** правки + тесты. **Критерий:** MCA14-R1 → SC; инвариант 1; A28. **Зависимости:** T-3753. — **✅ Выполнено 26.09.2026:** реестр `MigrationStep` (v1…v13; `_migrate_*` REUSE); `_run_migrations` (книга `schema_migrations`, `user_version`, legacy back-fill, идемпотентный повтор); v13 `_migrate_schema_migrations_v13`. Тесты: `test_v13_book_and_user_version`, `test_idempotent_reinitialize_zero_duplicates`, `test_legacy_v12_backfill`.

## Блок C — backup/WAL + проверка места (T-3755)

- [x] **T-3755 [@Builder — backup + free-space + read-back]** — **Цель:** backup согласованно с используемой БД (с WAL), проверка свободного места, проверка чтения копии; при недостатке места — явная ошибка. **Выход:** правки + тесты. **Критерий:** MCA14-R1 → SC; инвариант 2; A28. **Зависимости:** T-3754. — **✅ Выполнено 26.09.2026:** `services/memory_backup.py::migration_backup` (`VACUUM INTO` + free-space + read-back `integrity_check`/`user_version`; R17-safe логи без путей), вызывается runner'ом ДО применения шагов; провал → явный отказ. Тесты: `test_migration_backup_*`, `test_migration_fails_if_backup_fails`.

## Блок D — стабильные ID, unknown, индексы (T-3756, T-3758)

- [x] **T-3756 [@Builder — сохранение ID/таблиц + unknown]** — **Цель:** старые ID/таблицы не переименовывать/не удалять; новые nullable-поля = честный unknown; без выдуманного источника. **Выход:** правки + тесты. **Критерий:** MCA14-R2 → SC; инвариант 3. **Зависимости:** T-3754. — **✅ Выполнено 26.09.2026:** v13 аддитивна (`CREATE TABLE IF NOT EXISTS`); legacy ID сохраняются; новые nullable = NULL. Тесты: `test_legacy_ids_preserved`, `test_new_nullable_columns_are_null`.
- [x] **T-3758 [@Builder — индексы + rollback-compat]** — **Цель:** индексы по реальным запросам/explain; совместимый откат кода оставляет новые данные; для несовместимой версии — rollback build / forward fix; backup restore — аварийный сценарий. **Выход:** правки + манифест rollback-build + тесты. **Критерий:** MCA14-R2/-R4 → SC; инварианты 4, 6; A28. **Зависимости:** T-3754. — **✅ Выполнено 26.09.2026 (ядро):** v13 — только `version INTEGER PRIMARY KEY` (индекс не нужен, обосновано); аддитивность обеспечивает rollback-compat (откат кода оставляет `schema_migrations`); манифест rollback-build — в `evidence.md`. Индексные манифесты v14/v15 — их фичи.

## Блок E — archive jobs без долгой транзакции (T-3757)

- [x] **T-3757 [@Builder — job-контракт checkpoint/уникальный ключ]** — **Цель:** архивные jobs не держат долгую транзакцию на весь диапазон (чтение/LLM/короткая запись разделены); resume с последнего подтверждённого checkpoint; уникальные ключи против повторного применения и параллельного старта; согласовано с TaskSupervisor `mca-01`. **Выход:** правки + тесты. **Критерий:** MCA14-R3 → SC; инвариант 5; A02/A51/A89. **Зависимости:** T-3754, T-3740 (TaskSupervisor). — **✅ Выполнено 26.09.2026:** контракт поверх `task_jobs` (T-3740): `TaskJobStore.save_checkpoint`/`get_checkpoint` (R17-safe JSON в `payload`, короткая tx); уникальный `coalesce_key` = повторный/параллельный старт не создаёт дубль. Тесты: `test_archive_job_checkpoint_resume`, `test_a51_takeover_no_duplicate`.

## Блок F — rollback-compat + kill-switch-политика (T-3758…T-3759)

- [x] **T-3759 [@Builder — kill-switch-политика]** — **Цель:** единая оперативная политика kill-switch для всех функций (env-only, default ON, OFF-паритет); отключение из-за сбоя фиксируется с причиной/временем/планом. **Выход:** правки + реестр kill-switch. **Критерий:** MCA14-R5 → SC; инвариант 7; A28. **Зависимости:** T-3753. — **✅ Выполнено 26.09.2026:** реестр `KILL_SWITCHES` в `services/mca_gates.py` (имена/default/OFF-паритет); `MCA_SCHEMA_MIGRATIONS_ENABLED` env-only ClassVar. Тесты: `test_kill_switch_off_legacy_path`, `test_kill_switch_defaults_on`.

## Блок G — тесты/наблюдаемость/ревью (T-3760…T-3762)

- [x] **T-3760 [@Builder/@Tester — migration smoke + A28]** — **Цель:** migration smoke, backup read-back, идемпотентный повтор, rollback build; A28 (БД с сохранёнными false-настройками → функции включены). **Выход:** тесты + evidence. **Критерий:** инвариант 8; A28. **Зависимости:** T-3754…T-3759. — **✅ Выполнено 26.09.2026:** `tests/test_mca14_schema_additive_round1027.py` (15 тестов: fresh/legacy smoke, read-back, идемпотентность, v14/v15, порядок); A28 (live на БД с false-настройками) — релизная проверка `mca-release`.
- [~] **T-3761 [@Builder — R17/MCA-13/17 интеграция]** — **Цель:** логи миграций/backup без секретов/путей; события по `mca-13`; регистрация стадий миграции/backup (MCA-17). **Выход:** правки + тесты. **Критерий:** инвариант 9. **Зависимости:** T-3760, T-3767. — **◐ Частично 26.09.2026:** логи миграций/backup R17-safe (без полных путей); контракт `mca_events` доступен (T-3767 ✅). Стадии MCA-17a — следующая фича.
- [ ] **T-3762 [@Reviewer/@Architect — ревью/merge]** — **Цель:** ревью (обе линзы; при R3 — `threat-failure-analysis.md`), Merge в `plans/ARCHITECTURE.md` (**§93+**), ADR Accepted. **Выход:** `review.md`, Merge. **Критерий:** release-blocking findings закрыты; deploy `DEFERRED_TO_RELEASE`. **Зависимости:** T-3760, T-3761.

## Критерий готовности фичи

Migration framework + backup/WAL + неизменность ID + job-контракт + rollback-compat + kill-switch-политика реализованы; smoke/A28 проходят; @Reviewer Approved; Merge (§93+) — @Architect. **Deploy — `DEFERRED_TO_RELEASE`.**
