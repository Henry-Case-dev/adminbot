# MCA Wave 0 — сводный evidence rework по единому Reviewer gate (round 10.27)

> **Фичи:** `mca-01-tx-task-supervisor`, `mca-13-event-contract`,
> `mca-14-schema-additive`. **Дата:** 26.09.2026. **Deploy:** `DEFERRED_TO_RELEASE`
> (§20; коммитов НЕТ; `APP_VERSION` 2.58.31 без bump).
> **Вход:** `mca-wave0-review.md`, `review.md` трёх фич,
> `mca-wave0-rework-instructions.md`.
> **Binding:** Reviewed-Commit `05bc8704c2de5e7de1d5d04ac34df763d35219aa`;
> Working-Tree-Hash `cc7e3c0acb6e23d46cca7c421fadf31e799311e05fd60798201bfdc81cd84e9a`
> — **stale после rework**; пересчёт binding делает @Reviewer на повторном gate.

## 1. Итоговые числа (факт)

| Прогон | Команда | Старт rework | Финал |
|---|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | 9574 / 0 | **9588 passed, 0 failed** (164с; 1 warning — FastAPI deprecation; leaked/timeout — нет) |
| mca-01 | `pytest tests/test_mca01_tx_task_supervisor_round1027.py` | 27 | **33 passed** |
| mca-13 | `pytest tests/test_mca13_event_contract_round1027.py` | 18 | **25 passed** |
| mca-14 | `pytest tests/test_mca14_schema_additive_round1027.py` | 15 | **17 passed** |
| JS vm-харнесс | `node` по всем `tests/js/*.js` (47 файлов) | 47/47 | **47/47 ok** |
| Git hygiene | `git diff --check` | чисто | чисто (exit 0) |

Δ каталога = **0** (`param_catalog.py` вне diff); Δ DDL = v13/v14/v15 (реестр
`mca-14`, порядок по возрастанию; новых версий нет).

## 2. Блокеры — статус и проверка

| Блокер | Статус | Фикс | Тест |
|---|---|---|---|
| B-MCA01-1 (High) write-механизм/аудит | ✅ закрыт | единый single-writer (`serialized()`/`@_serialized_write`/`write_transaction`), инвентарь + allowlist | `test_write_points_go_through_single_writer`, `test_no_nested_raw_lock_in_serialized_methods` |
| B-MCA01-2 (High) deadlock важной очереди | ✅ закрыт | `asyncio.Condition.wait_for` + `notify_all` | `test_important_queue_no_deadlock_on_overflow` |
| B-MCA01-3 (Medium) fencing не enforced | ✅ закрыт | `finish`/`heartbeat`/`save_checkpoint` обусловлены токеном; `run()` передаёт токен | `test_stale_fencing_owner_write_rejected` |
| B-MCA01-4 (Medium) rollback вне lock | ✅ закрыт | recovery строго под `_single_writer` | `test_degraded_recovery_rollback_under_lock` |
| B-MCA13-1 (High) R17-маскирование | ✅ закрыт | `sanitize()` всех строковых/JSON-полей до буфера/лога; `_emit_log` defense-in-depth | `test_masking_of_secrets_in_event_and_log`, `test_masking_persisted_durable_mca_events` |
| B-MCA13-2 (Medium) §17.4 метрики/фильтры | ◐ ядро реализовано, UI передан | `mca_events.metrics()` — все группы §17.4, UNKNOWN≠0; `query_events` фильтры; UI SC-13/SC-14 → `mca-17a` (нужна санкция @Architect) | `test_metrics_covers_17_4_groups_with_unknown`, `test_metrics_computes_real_groups_from_store`, `test_query_events_reason_filter_and_limit` |
| B-MCA14-1 (Medium) порядок `user_version` | ✅ закрыт | книга без `PRAGMA`; v13 фиксирует версию в цикле после v12 и только `< 13` | `test_fresh_init_failure_on_early_step_recovers` |
| L-MCA01-1…3, L-MCA13-2…4, L-MCA14-1…3 | ✅ исправлены/покрыты | см. `mca-01/evidence-rework.md` §5, `mca-13/evidence.md` §6, `mca-14/evidence.md` §6 | соответствующие тесты |
| L-MCA13-1 (flush/prune wiring) | → перенос | durable-часть library-only (событий в hot-path нет); flush/prune к shutdown/планировщику — `mca-17a` | зарегистрировано в `mca-13/evidence.md` §6 |
| Ниты @PM: spec mca-14 REQ-08 `T-3759`→`T-3752`; `retención` (mca-13 SC-16); «Блок C» (mca-13 tasks) | → @Architect | правки spec — зона @Architect (не правились) | отмечено в evidence фич |

## 3. Изменённые/созданные файлы rework-сессии

**Код:**
- `services/mca_events.py` — §17.4 единый адаптер `metrics()` (все группы,
  UNKNOWN≠0) + runtime-контур; тестовые L-MCA13-2/L-MCA13-4 фиксы уже в коде.
- `services/database.py` — in-process `database_lock_retry_total()` (метрика
  §17.4 «lock retries»); фикс self-дедлока `slavic_photo_count_tick`
  (B-MCA01-1/H25).
- `services/task_supervisor.py` — B-MCA01-2/3 (Condition, fencing-enforcement),
  L-MCA01-3 (singleflight до durable-enqueue), B-MCA01-4 в `database.py`.
- `services/memory_backup.py` / `services/disk_retention.py` — L-MCA14-1/2
  (`prune_migration_backups`, учёт WAL).
- `bot.py` — L-MCA01-2 (`BaseException` в shutdown-closers).

**Тесты:**
- `tests/test_mca01_tx_task_supervisor_round1027.py` (+6 к review: deadlock,
  fencing, degraded-rollback, write-audit AST, nested-lock guard).
- `tests/test_mca13_event_contract_round1027.py` (+7: masking e2e ×2, метрики
  ×3, reason-filter, log-level/env lows).
- `tests/test_mca14_schema_additive_round1027.py` (+2: fresh-init recovery,
  prune pre-migration backups).
- `tests/test_summary_handlers.py` — без изменений (временная диагностика
  снята; регресс закрыт кодом).
- `tests/test_tool_coordinator_round1026.py` — scope-guard обновлён: NOTE
  round1027/ADR-1027-3 D3 для `services/summary_memory.py` (§7 mca-01 evidence).

**Docs:** `tasks.md` (T-3736/T-3746 mca-01; T-3773 mca-13 → `[~]`),
`evidence.md` (mca-01 §5, mca-13 §6, mca-14 §6), `evidence-rework.md` (mca-01),
`threat-failure-analysis.md` (mca-01 H21–H25/H17a/H23; mca-14 G13a/G15/G16),
этот файл.

## 4. Осознанные переносы / санкции

1. **B-MCA13-2 UI-часть (SC-13/SC-14):** метрики на витрине, переходы из
   карточек, логи в существующем viewer — перенос в `mca-17a`. Обоснование:
   ADR-1027-2 D8 запрещает новые endpoint/панели (только REUSE), витрина =
   контур наблюдаемости MCA-17a поверх того же `mca_events`. Backend-адаптер
   §17.4 реализован в mca-13. **Требуется санкция @Architect**; T-3773 → `[~]`.
2. **L-MCA13-1 flush/prune wiring:** интеграция durable flush/prune в
   worker-loop/планировщик — `mca-17a` (durable-часть — library-only; события
   задач эмитятся, flush вызывается по месту).
3. **T-3746 стадии/виджет MCA-17a**, **T-3757** (archive-job поверх `task_jobs`),
   **T-3761 стадии MCA-17a** — согласованные границы волны 0 (spec §1).
4. **Ниты @PM spec/tasks** — зона @Architect/@PM, не правились.
5. **Регресс cross-round guard round-1026** — минимальная санкционированная
   правка теста (см. §3), т.к. MCA-01 законно меняет `summary_memory.py`.

## 5. Готовность к повторному ревью

- Все High/Medium блокеры закрыты тестами; Lows исправлены или явно
  зарегистрированы; полный pytest и JS зелёные; `git diff --check` чист.
- Binding — **stale** (правки после wt-хэша `cc7e3c0a`); @Reviewer выполняет
  единый повторный gate (обе линзы) на новом рабочем дереве: пересчёт
  Diff-SHA256/Spec/ADR/tasks-хэшей, проверка release-blocking findings.
- Без коммитов/тегов; `APP_VERSION` 2.58.31; Δ каталога = 0.
