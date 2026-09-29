# MCA (round 10.27) — Wave 0: сводное ревью единого gate (Step 5 @Reviewer) — повторный цикл

> **Агент:** @Reviewer (единый gate: требования/корректность + фокусированный аудит изменений; Scanner отсутствует).
> **Дата:** 26.09.2026. **Фичи:** `mca-14-schema-additive`, `mca-13-event-contract`, `mca-01-tx-task-supervisor`.
> **Deploy:** `DEFERRED_TO_RELEASE` (§20; коммитов НЕТ — ревью рабочего дерева; `APP_VERSION` 2.58.31 без bump).
> **Детальные вердикты:** `plans/features/mca-{14,13,01}-*/review.md` (этот файл — сводка; финальные статусы — там же).

## 1. Binding (единое рабочее дерево для трёх фич; пересчитан после rework)

- **Git base / Reviewed-Commit:** `05bc8704c2de5e7de1d5d04ac34df763d35219aa` (intake round1027; `APP_VERSION` 2.58.31; DDL v13/v14/v15; Δ каталога = 0).
- **Diff-SHA256 (`git diff --binary HEAD`):** `fbf2eea45be890fb32925b3de67d9039a92430971efb4ae4618c54ae64058299`.
- **Working-Tree-Hash (детерминированный манифест 59 записей: staged/unstaged diff + содержимое untracked, строка `path<TAB>sha256`, sha256 от join; исключены 7 артефактов ревью/workflow — 4 `review.md`, `plans/reports/full_audit_results.md`, `plans/reports/global_map.md`, `plans/workflow_state.md`):** `9cd581e4549e2fc0fd53599ade14b507b42f87e8a864899c3486e8d78b144a97`.
- **Product-Code-Hash (доп., `services/` + `config/` + `bot.py` + `tests/`, 37 записей):** `9d9254187b50c71b6067aa1ad52c4a3cdaad7c1579ee7ed780752a23fab64827`.
- **Spec/ADR/tasks-хэши (новые, сверены с санкцией @Architect):**
  - mca-14: spec `898a183d…` (REQ-08 → `T-3752/T-3754`), ADR `4765e26c…`, tasks `a5717a1f…`;
  - mca-13: spec `c93dcbf8…` (§1.1 carry-over register + SC-16 `retention`), ADR `496e90ed…` (AMEND-1/2/3), tasks `8b796c0c…` (T-3773 `[~]`);
  - mca-01: spec `92b1a2b7…`, ADR `d67378ff…`, tasks `4bd71685…` (T-3736/T-3746 к правде).
- Хэш рабочего дерева зафиксирован **до** записи `review.md`; сами `review.md` — артефакты ревью и в reviewed-state не входят. Любая правка кода/спеки после фиксации делает вердикты stale.

## 2. Таблица вердиктов (итер.2)

| Фича | Risk | Вердикт | Blocking | Low/debt | Ключевое |
|---|---|---|---|---|---|
| `mca-14-schema-additive` | R3 | **Approved** | — | L-MCA14-4 | B-MCA14-1 закрыт: `user_version` фиксирует сам шаг v13 после v12; fresh-init восстановление; backup перед шагами |
| `mca-13-event-contract` | R2 | **Approved** | — | L-MCA13-1/5/6 | B-MCA13-1 закрыт (e2e-маскирование лога+durable); §17.4 backend закрыт, UI — санкц. carry-over (§1.1/AMEND-1) |
| `mca-01-tx-task-supervisor` | R3 | **Approved** | — | L-MCA01-5/6/7 | B-MCA01-1/2/3/4 закрыты; fencing store+result-path + тест; остаток — симметрия токена на cancel/fail (Low) |

## 3. Независимый прогон (факт)

| Проверка | Результат |
|---|---|
| Полный pytest (`pytest -q`, `.venv`) | **9588 passed, 0 failed** (1 FastAPI-deprecation warning; `leaked aiosqlite` — нет) |
| Новые тесты mca-01 / mca-13 / mca-14 | **33 / 25 / 17 passed** (= 75) |
| JS vm-харнесс (`node`, все 47 `tests/js/*.js`) | **47/47 ok** |
| `git diff --check` | чисто (exit 0) |

Инцидент `services/feature_gates.py`: diff/status — пусто (== HEAD, F-10 не сломан); новый `services/mca_gates.py` — отдельный модуль. Kill-switch'и: env-only `ClassVar`, default ON, per-call, не бросают; `DB_LOCK_RESILIENCE_ENABLED`/`AGENTIC_EVENTS_ENABLED` не дублированы.

## 4. Закрытие блокеров итер.1 (сверка)

| Блокер | Итог | Доказательство |
|---|---|---|
| B-MCA01-1 (High) write-механизм/аудит | ✅ closed | single-writer (`serialized()`/`@_serialized_write`/`write_transaction`); AST-инвентарь 49+53=102; guard-тесты зелёные |
| B-MCA01-2 (High) deadlock важной очереди | ✅ closed | `asyncio.Condition.wait_for`+`notify_all`; `test_important_queue_no_deadlock_on_overflow` |
| B-MCA01-3 (Medium) fencing | ✅ closed | `finish`/`heartbeat`/`save_checkpoint` обусловлены токеном; `test_stale_fencing_owner_write_rejected` (остаток — L-MCA01-5) |
| B-MCA01-4 (Medium) rollback вне lock | ✅ closed | recovery под `_single_writer`; `test_degraded_recovery_rollback_under_lock` |
| B-MCA13-1 (High) R17-маскирование | ✅ closed | `sanitize()` всех строковых/JSON-полей до буфера/лога/durable; 2 e2e-теста (caplog + строка `mca_events`); R2 ратифицирован |
| B-MCA13-2 (Medium) §17.4 UI | ✅ closed (backend + санкц. carry-over) | `metrics()` все группы + UNKNOWN≠0; `query_events` LIMIT; spec §1.1 + ADR AMEND-1/2; T-3773 `[~]` |
| B-MCA14-1 (Medium) порядок `user_version` | ✅ closed | книга без `PRAGMA`; v13 фиксирует версию в цикле после v12; `test_fresh_init_failure_on_early_step_recovers` |

**Lows итер.1:** L-MCA01-1…4, L-MCA13-2…4, L-MCA14-1…3 — исправлены; L-MCA13-1 — санкционированный перенос (`mca-17a`); ниты @PM (REQ-08, `retención`) — исправлены @Architect.

## 5. Сквозные (cross-cutting) findings

1. **Новых блокеров нет.** Все итер.1-блокеры закрыты на требуемом уровне.
2. **L-MCA01-5 (Low, new, «пограничный Medium»):** `TaskSupervisor.run()` не передаёт `fencing_token` в terminated-пути `cancelled`/`failed` (только в success). Blast radius ограничен (новая строка нового владельца не затрагивается; `result_ref` защищён). Исправить до первого production-подключения TaskSupervisor (`mca-17a`) + выровнять формулировку threat H17a.
3. **Doc-ниты (Low):** mca-01 tasks T-3736 «61+41» (факт 49+53) и устаревшие числа в T-3747 (`9542/0`, v13); mca-13 spec D5 «28 кодов» (факт 27 по §17.2); mca-13 tasks:17 «Блок C».
4. **Truthfulness статусов:** T-3736 теперь `[x]` правдив; T-3773 `[~]` (санкц. перенос) — молчаливое сужение снято.
5. **Latent-характер:** production-вызовов `TaskSupervisor`/`flush_events` пока нет — Low-остатки не проявляются в текущем релизе, но L-MCA01-5 должен быть закрыт до подключения потребителей.

## 6. Adjudication трактовок @Builder (повторно)

| Трактовка | Вердикт | Обоснование |
|---|---|---|
| T-3741/T-3742 durable partial unique `coalesce_key` | Законно | совпадает с рамкой §1.1.1/ADR-1027-3 D6; dedup + A51-тест |
| T-3746/T-3775/T-3761 (стадии/виджет MCA-17a) | Законно | spec §1 явно исключает реестр процессов/span/heartbeat (граница волны 0) |
| T-3736 (write-аудит) | Законно (`[x]` правдив) | охват закрыт single-writer + guard-тестами |
| T-3773 (SC-13/14 UI) | Законно (`[~]`) | санкц. перенос @Architect: spec §1.1 + ADR-1027-2 AMEND-1/2; T-3773 `[~]` |

## 7. Рекомендация @Orchestrator

- **Волна 0 готова к merge/архивации:** все три фичи **Approved** на binding `9cd581e4…`. Deploy остаётся `DEFERRED_TO_RELEASE` (§20).
- **@Architect:** Merge §93+ (по факту завершения) + `ADR-1027-1/-2/-3 → Accepted`; зафиксировать carry-over register (§1.1) и L-MCA01-5 как вход `mca-17a`.
- **Watch-item для `mca-17a`/первого потребителя:** L-MCA01-5 (передавать `fencing_token` в cancelled/failed-пути `TaskSupervisor.run`); при подключении `flush_events` к hot-path — reassessment триггера конкуренции (кандидат R2→R3) — уже в spec §1.1.
- **@PM (не блокирует):** doc-ниты L-MCA01-6, L-MCA13-6, «Блок C» (mca-13 tasks:17).
- **Merge-процедура:** после merge/архивации — проверить, что SHA-256 `spec.md` перенесённых фич не изменились (кроме `Status Proposed→Accepted` у ADR, если применимо), и пере-pin агрегатного манифеста.
- **Binding-нюанс:** три фичи делят один Working-Tree-Hash; merge коммитит текущее reviewed-содержимое — новый коммит с байт-идентичным контентом допустим после сверки.

## 8. Handoff / state (для @Orchestrator — machine checkpoint пишет только Orchestrator)

- Статусы: `mca-14-schema-additive` = **Approved**; `mca-13-event-contract` = **Approved**; `mca-01-tx-task-supervisor` = **Approved**.
- Binding для всех: `Reviewed-Commit=05bc8704c2de5e7de1d5d04ac34df763d35219aa`, `Diff-SHA256=fbf2eea45be890fb32925b3de67d9039a92430971efb4ae4618c54ae64058299`, `Working-Tree-Hash=9cd581e4549e2fc0fd53599ade14b507b42f87e8a864899c3486e8d78b144a97`, `Product-Code-Hash=9d9254187b50c71b6067aa1ad52c4a3cdaad7c1579ee7ed780752a23fab64827`.
- Артефакты: `plans/features/mca-14-schema-additive/review.md`, `plans/features/mca-13-event-contract/review.md`, `plans/features/mca-01-tx-task-supervisor/review.md`, `plans/reports/full_audit_results.md` (запись round1027 wave0 re-review).

## 9. MEMORY_DELTA (для @Orchestrator → @Memory; только подтверждённое)

- `mca-14`: порядок `user_version` исправлен (книга без `PRAGMA`; v13 фиксирует версию после v12 в общем цикле) — fresh-init сбой восстанавливается; backup перед шагами; legacy v12 → v13/v14/v15. `prune_migration_backups` ротирует `pre_migration_*` отдельно.
- `mca-13`: `build_event` маскирует все строковые/JSON-поля через `sanitize()` до буфера/лога/durable (R17/SC-10 закрыт); backend §17.4 (`metrics`/`query_events`) реализован; UI SC-13/14 + flush/prune wiring — санкц. carry-over в `mca-17a` (spec §1.1, ADR-1027-2 AMEND-1/2). R2 сохранён.
- `mca-01`: единый single-writer закрыл write-точки (49+53 в `database.py` + 6 модулей); deadlock важной очереди устранён (`Condition`); fencing enforced в `finish`/`heartbeat`/`save_checkpoint`; recovery-rollback под lock. **Остаток L-MCA01-5:** `run()` не передаёт `fencing_token` в cancelled/failed-пути (Low; закрыть до `mca-17a`).
- Прогон: pytest 9588/0, JS 47/47, focused mca-01/13/14 = 33/25/17; `feature_gates.py` == HEAD.
