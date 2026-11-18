# SCH — Scheduler: блокировка event loop и misfire (LVS-SCH-01..05)

- Дата: 2026-11-18
- Слайс: `SCH` эпика `llm-vision-scheduler-p0` (position 1, P0)
- База: deployed `ea9f760f` (2.58.214), ветка `release/mod-acl-w2b3-2.58.214`
- Ветка: `fix/p0-scheduler-loop`, worktree
  `WorkspaceData/worktrees/.../p0-scheduler-loop-0e77d29079bd-f6ad282d`
  (housekeeping `worktree-path` + `register-worktree`, unit `builder-sch`)
- Кандидат кода: `03b4358f` (ранее в документе стоял `28c0e7c8` — тот же
  diff, но коммит вне текущей истории: дерево `28c0e7c8` и `03b4358f`
  идентично, `git merge-base --is-ancestor 28c0e7c8 HEAD` → 1, ни одна ветка
  его не содержит)
- r2-правки поверх кандидата: `491066378` (F1 `_signal_release`, F3 clamp, тесты)
- Статус: REVIEW (не VERIFIED, не bump, не deploy)
- Требования: LVS-SCH-01, LVS-SCH-02, LVS-SCH-03, LVS-SCH-04, LVS-SCH-05
- Карта `requirements-map.json` и `progress_scope.json` не редактировались.

## 1. Что исправлено

| Блок | Файл:строка (кандидат) | Изменение |
|---|---|---|
| B1 (primary) | `services/slot_claims.py:448`, `:475` | `store.try_claim(...)` → `await asyncio.to_thread(store.try_claim, ...)` в обеих ветках (due → fire, окно прошло → честный skip). Схема, `INSERT OR IGNORE`/CAS, `timeout=5`, `busy_timeout=5000` и возвращаемая семантика не менялись; соединение по-прежнему создаётся внутри вызова — уже в worker-thread. |
| A (lifecycle) | `summary_scheduler.py:69,176`; `goodmorning_scheduler.py:42,116`; `nostalgia_worker.py:160,941`; `uptime_heartbeat.py:30-31,69,74`; `lore_worker.py:267,444`; `dream_worker.py:293,659,670`; `memory_maintenance.py:180-182,366-473`; `memory_backup.py:54,82` | Явный `misfire_grace_time` вместо заводского 1 s APScheduler 3.x. Значения по джобам: 30 / 30 / 30 / 30+300 / 60 / 300+300 / 60+300+3600 / 3600. r2: для hot/конструктор-параметризуемых интервалов (nostalgia, uptime, dream, lore, merge/review/WAL) значение клампится к фактическому интервалу — `grace = max(1, min(константа, интервал))` (§8). |
| B2 (backpressure) | `services/summary_scheduler.py:216-258` | Разделены фазы: сначала claim всех due-чатов в `due_chats`, затем `generate_and_send` по списку. Порядок чатов и `chat_timeout` сохранены, новой конкурентности нет. |
| B3 (same class) | `services/publication_coordination.py:782,877,892,911,923,937,952,967` | `precheck/snapshot`, `acquire` (включая manual-retry), `begin_sending`, `release`, `claim_manual_priority`, `release_manual_priority` — sync store-вызовы переведены в `asyncio.to_thread`. CAS/таблица не менялись; сигнал release-event из worker-thread исправлен в r2 (§8). Включено после RED-теста (см. §2). |

Не тронуты: L1/модель/LLM-клиент, Vision, QRNG, UI, `meme_initiative` и
`memory_backup` sync-fallback (B4 — backlog, не доказаны), таблицы/CAS,
порядок роутеров. `vision_media_tick` — интервал фактически `VISION_TICK_SECONDS = 5`
(не 30 s), grace 30 s уже стоял и не менялся; `grace > интервал` у этой джобы —
pre-existing несогласованность, не регрессия кандидата и не входит в r2 (§7,
backlog).
anticliche (3600 s) уже имел grace — не менялся (проверяется статическим тестом
по всем `add_job`).

## 2. RED на базе `ea9f760f` (измерено)

`tests/test_p0_scheduler_loop.py` на базе (финальная версия тестов): **6
failed / 4 passed**.

| Сценарий | RED-факт на базе |
|---|---|
| B1 claim при чужом write-lock 500 ms | max gap event loop = **546 ms** (тест падал на `gap < 0.1`); в предыдущем прогоне 532 ms; claim завершился только после release |
| B3 publication acquire при том же lock | max gap = **547 ms** |
| B2 claim-first summary | claim второго чата отсутствует, пока идёт первый прогон → `second is not None` падает |
| uptime late run | `job.misfire_grace_time == 1` (заводской) |
| runtime job contract | `summary_job: grace=1, ожидалось 30` |
| static add_job contract | 18 вызовов `add_job` без `misfire_grace_time` |

Четыре теста на базе проходят осознанно: exactly-one claim + CAS (поведение
не должно меняться), «один INSERT на запуск» (heartbeat уже был идемпотентен),
и оба сценария APScheduler misfire — это проверка механизма библиотеки
(grace 1 s → skip, grace 5 s → один запуск), а не дефекта продукта.

## 3. GREEN на кандидате `03b4358f`

`tests/test_p0_scheduler_loop.py`: **10 passed** на коде `03b4358f`;
**12 passed** после r2 (добавлены F1- и F3-тесты, §8).

Измерено тем же сценарием (lock 500 ms, probe 5 ms):

```text
slot_claim:   gap_ms=16.0  claim_ms=544  action=fire  fired=1
publication:  gap_ms=16.0  claim_ms=540  granted=True
```

Ожидание осталось (≈0.54 s внутри worker-thread, как и требует lock), но loop
свободен: gap 16 ms против 546/547 ms на базе (в предыдущем прогоне 532 ms).

Дополнительные проверки в тестах:

- ровно один claim на слот; второй вызов → `skip_busy`; строка `fired=0`
  перебронируется CAS при смене instant (атомарность сохранена);
- claim-first: пока первый чат «генерируется», строка второго уже `fired=1`,
  `reason_code=''`; после завершения — оба чата по порядку; повторный тик в
  том же due-окне не даёт дублей и не пишет `missed_slot_expired`;
- uptime: ровно 1 INSERT на запуск, два разных запуска → 2 строки; late run в
  пределах явного grace (30 s) → ровно 1 INSERT;
- publication: после освобождения lock бронь выдана, `claimed → sending →
  release` пишет watermark (`last_publish_kind=initiative`), т.е. publish-
  контракт не изменился;
- runtime-контракт: у всех запущенных сервисов (summary, goodmorning,
  nostalgia, lore, dream, memory maintenance, memory backup, uptime) grace
  равен ожидаемому, `coalesce=True`, `max_instances=1`, grace ≤ интервала;
- статический контракт: каждый `add_job` в `services/*.py` объявляет
  `misfire_grace_time` (после фикса — 0 нарушений).

## 4. Мутации (каждая убивает тест)

| Мутация | Результат |
|---|---|
| M1: вернуть sync `store.try_claim` в loop | KILLED — 1 failed |
| M2: вернуть sync `self._store.acquire` в loop | KILLED — 1 failed |
| M3: переплёл claim+generate (старое поведение) | KILLED — 1 failed |
| M4: убрать grace у `summary_job` | KILLED — 2 failed |
| M5: убрать grace у `uptime_heartbeat` | KILLED — 2 failed |
| M6 (r2): вернуть прямой `event.set()` в `SqliteClaimStore.release` | KILLED — `RuntimeError: Non-thread-safe operation invoked on an event loop other than the current one`; тест `FAILED` (§8) |
| M7 (r2): убрать clamp у `uptime_heartbeat` (константа 30 s) | KILLED — `uptime_heartbeat: grace=30 > interval=10.0` (§8) |

Скрипт мутаций восстанавливал исходное содержимое после каждого прогона.

## 5. Регрессии (затронутый neighbourhood)

r1-прогоны: `pytest -q -p no:randomly`, worktree кандидата.

| Батч | Результат |
|---|---|
| `test_p0_scheduler_loop` + `test_summary_scheduler` + `test_ur_c_sched` + `test_uptime_heartbeat` | 43 passed |
| `test_scheduler` + `test_goodmorning` + `test_lore_worker` + dream-батч (7 файлов) | 178 passed |
| nostalgia-батч (10 файлов, включая `test_qnd_schedule`, `test_qnd_publication`) | 167 passed |
| `test_memory_maintenance` + `test_memory_communities_maintenance` + `test_memory_backup` | 37 passed |
| `test_p0_meme_publication_hotfix` + `test_publication_binding_delivery` + `test_qnd_publication` + `test_initiative_publications_api` | 103 passed |
| `test_evol014_meme_initiative` + `test_meme_init_diagnostics` + `test_p0im_s5_meme_marker_interrupt` | 128 passed |
| `test_database` + `test_hot_config` + `test_mca01_tx_task_supervisor_round1027` + 4 migration/schema файла | 188 passed, 1 failed |
| `test_initiative_coordination` | 56 passed, 4 failed |
| r2: `test_p0_scheduler_loop` + `test_uptime_heartbeat` + `test_lore_worker` + `test_dream_worker` + `test_nostalgia_worker` + `test_goodmorning` | 168 passed |
| r2: `test_scheduler` + `test_summary_scheduler` + `test_memory_maintenance` | 37 passed |
| r2: `test_p0_meme_publication_hotfix` + `test_meme_init_diagnostics` | 93 passed |
| r2: `test_initiative_coordination` | 56 passed, 4 failed (те же pre-existing) |

r2-прогоны: `C:\Code\Python\adminbot\.venv\Scripts\python.exe -m pytest -q
-p no:cacheprovider` (pytest 9.1.1, pytest-asyncio 1.4.0, pytest-timeout 2.4.0,
APScheduler 3.11.3), worktree кандидата, `-q` без `-p no:randomly`
(random-order плагин в окружении отсутствует). Четыре падения
`test_initiative_coordination` в r2 воспроизведены на `72fbfe41` — коммите
ДО r2 (изолированное дерево через `git archive`, без изменения worktree):
те же 4 node id, значит r2 их не вносит; на базе `ea9f760f` они были
воспроизведены ещё в r1 (см. ниже).

Итого по neighbourhood r1: **900 passed**, 5 failed — все 5 **воспроизведены на
базе `ea9f760f`** (отдельный detached worktree, удалён после проверки):

- `test_initiative_coordination`: `test_act_on_opportunity_conflict_defers_to_intent`,
  `test_evaluate_phase_precheck_blocks_before_llm`,
  `test_t1_nostalgia_delegated_refusal_sends_nothing`,
  `test_t5_every_text_send_site_passes_publish_guard` — 4 failed и на базе, и на
  кандидате (базовый прогон с базовым `publication_coordination.py` дал те же
  node id; diff их не вызывает и не лечит);
- `test_mca01_tx_task_supervisor_round1027::test_write_points_go_through_single_writer`
  — 1 failed на базе и на кандидате (`meme_initiative.py`,
  `prompt_release_policy.py` — файлы вне diff).

Полный `tests/` — 21 770 тестов, не запускался (вне слайса). «Mandatory 386»
в артефактах карты/плана не зафиксирован как список файлов/узлов, поэтому
вместо реконструкции неизвестного набора выполнен полный затронутый
neighbourhood (900 passed).

## 6. Конфигурация

- Новых флагов/env/hot-ключей нет; значения grace — код-константы рядом с
  каждым планировщиком, поэтому effective-config пользователя не меняется.
- r2: при hot/конструктор-интервале меньше константы grace (например
  `limits.qnd_heartbeat_seconds=10`, `heartbeat_seconds=10`,
  `limits.lore_tick_minutes=1`, `limits.db_wal_checkpoint_hours=0.05`)
  джоба получает `grace = max(1, min(константа, интервал))`. На заводских
  значениях числа не изменились — это подтверждает прежний runtime-тест
  `test_all_started_jobs_declare_expected_explicit_grace` (тот же
  `EXPECTED_GRACE`), поэтому пользовательская конфигурация при штатных
  значениях читается как раньше.
- `misfire_grace_time` — целые секунды (APScheduler 3.11.3 отвергает float:
  `misfire_grace_time must be either None or a positive integer`).
- `timeout=5`/`busy_timeout=5000` сохранены: ожидание теперь в worker-thread,
  не в loop.
- Порядок/частота работ не менялись; затронуты только graceful-окна и место
  ожидания.

## 7. Ограничения и честные границы

- `PublicationCoordinator.available()` остаётся sync (`table_present()` —
  чтение `sqlite_master`): это не 5-секундный write-wait, публичный sync-API
  используется и вне async-путей; в B3 не входит.
- `asyncio.to_thread` использует default executor: массовых параллельных
  claim'ов нет (тик summary последовательный, goodmorning последовательный),
  каждая операция короткая; лимит потоков default executor не менялся.
- Grace не восстанавливает пропущенную минуту `uptime_heartbeat` — поздний
  sample пишется, разрыв в истории остаётся честным; это не «разрывов нет».
- Postdeploy-замер lag и отсутствие WARN 09:21-типа — задача DevOps после
  деплоя (не выполнялось).
- Реальный provider/LLM-прогон для этого слайса не требуется (блок был до
  генерации).
- 5 падающих тестов — pre-existing на базе, не кандидаты на исправление в
  этом слайсе.
- Claim-first резервирует слоты всех due-чатов ДО генерации. Если процесс
  упадёт между claim и генерацией позднего чата, его слот останется `fired=1`
  без фактического прогона — та же потеря работы, что раньше записывалась как
  `missed_slot_expired`, но строка уже не покажет пропуск. Durable run-state /
  смена CAS-семантики запрещены scope, поэтому postdeploy-приёмка проверяет
  сверку `slot_claims` ↔ `summary_runs` исполняемым запросом (§9), а не только
  отсутствие WARN.
- `vision_media_tick`: интервал 5 s, grace 30 s (pre-existing, вне diff) —
  инвариант `grace ≤ интервал` для этой джобы не выполняется; поведение
  остаётся безопасным за счёт `coalesce=True`/`max_instances=1` (поздний тик
  исполняется один раз, дублей нет). Не исправлялось в r2: `services/mca_vision.py`
  вне назначенного write-scope, дефект существовал до кандидата — backlog для
  владельца слайса (не блокирует текущую приёмку, регрессии нет).

## 8. Corrective r2 (F1, F3)

Причина r2 — два дефекта, найденных при ревью r1.

### F1: `SqliteClaimStore.release` сигналил waiter из worker-thread

`PublicationCoordinator.release` вызывает store через `asyncio.to_thread`
(B3), т.е. `SqliteClaimStore.release` исполняется в чужом потоке. Прежний код
звал `asyncio.Event.set()` напрямую: под debug-loop это
`RuntimeError: Non-thread-safe operation invoked on an event loop other than
the current one`, без debug — незащищённая запись в ready-queue loop и
потерянный wakeup. `acquire(manual=True, wait_for_sending=…)` мог не
проснуться до таймаута и вместо брони получить `publication_in_flight`.

Исправление: `_signal_release` (`services/publication_coordination.py:306`)
вызывает `loop.call_soon_threadsafe(event.set)` для loop-владельца события
(`_RELEASE_EVENT_LOOPS`, заполняется в `_release_event`); прямой `set()`
остаётся только когда вызов уже в том же loop (или loop неизвестен).
`clear()/wait()` остаются в loop-thread. CAS, SQL и семантика release не
менялись.

Тест: `tests/test_p0_scheduler_loop.py::TestReleaseEventThreadSafety::test_manual_waiter_wakes_after_release_from_worker_thread`
— реальный путь `acquire(manual=True, wait_for_sending=5.0)` →
`coordinator.release(...)` при `loop.set_debug(True)`; probe-event
подтверждает, что waiter уже внутри `wait()`, и измеряется задержка
пробуждения.

Измерено на fixed-коде (debug-loop, 3 прогона того же сценария вне pytest):
`wake_ms = 16.0 / 16.0 / 16.0`, `released=True`, `granted=True`.

Мутация M6 (вернуть прямой `event.set()`): тест `FAILED`; диагностический
прогон печатает `release raised RuntimeError: Non-thread-safe operation
invoked on an event loop other than the current one`, waiter остаётся
неразбуженным (`waiter done=False`). Побочный факт: после такой мутации
разборка loop в процессе зависает (ready-queue повреждена чужим потоком),
поэтому RED-прогон ограничен внешним таймаутом — это свойство дефекта, не
теста.

### F3: `grace` мог быть больше эффективного интервала

Hot/конструктор-значения интервала могут быть меньше код-константы grace
(nostalgia/uptime heartbeat, lore/dream tick minutes, merge/review/WAL).
Теперь `grace = max(1, min(константа, эффективный интервал))`
(`memory_maintenance._job_grace` + локальные `tick_grace` в
nostalgia/uptime/dream/lore). Заводские значения не меняются (§6).

Тест: `...::TestSchedulerJobContract::test_grace_is_clamped_to_effective_not_default_interval`
— проверяются именно не-дефолтные значения:

| Джоба | Эффективный интервал | grace |
|---|---|---|
| `uptime_heartbeat` | 10 s (`heartbeat_seconds=10`) | 10 |
| `nostalgia_tick` | 10 s (`limits.qnd_heartbeat_seconds=10`) | 10 |
| `lore_worker_tick` | 60 s (`limits.lore_tick_minutes=1`) | 60 |
| `dream_tick` / `deep_sleep_tick` | 60 s (`memory.dream_tick_minutes=1`) | 60 / 60 |
| `graph_episode_merge` | 864 s (`…merge_interval_days=0.01`) | 864 |
| `db_wal_checkpoint` | 180 s (`db_wal_checkpoint_hours=0.05`) | 180 |

Тест дополнительно проверяет инвариант `grace ≤ interval` для всех джоб этих
пяти сервисов, а не только для перечисленных id.

Мутация M7 (вернуть константу 30 s у `uptime_heartbeat`): `1 failed`,
`uptime_heartbeat: grace=30 > interval=10.0`.

Итог r2: `tests/test_p0_scheduler_loop.py` — **12 passed**.

## 9. Postdeploy сверка `slot_claims` ↔ `summary_runs` (исполнимый SQL)

Запуск после деплоя (read-only, WAL не блокируется):

```bash
sqlite3 -readonly -header -column /var/www/admin_bot/local_database.db \
        < plans/features/llm-vision-scheduler-p0/evidence/sch/sch_reconcile.sql
```

Файл `sch_reconcile.sql` лежит рядом с этим evidence и содержит ровно те три
запроса, что ниже (сверено нормализованным сравнением: 3/3 совпадают);
`slot_utc_instant` и `created_at` — epoch-секунды UTC, окно слота —
полуинтервал `[slot_utc_instant, следующий слот)`, для последнего слота чата
граница `+86400 s`. Для окна «с даты деплоя» добавить в CTE `summary_slots`
условие `AND local_date >= '<YYYY-MM-DD>'`.

Q1 — по каждому `fired=1` слоту число auto-прогонов (`manual=0`) в его окне:

```sql
WITH summary_slots AS (
    SELECT chat_id, local_date, local_slot, slot_utc_instant, fired
    FROM slot_claims
    WHERE kind = 'summary'
),
bounded AS (
    SELECT s.chat_id, s.local_date, s.local_slot, s.slot_utc_instant,
           COALESCE(
               (SELECT MIN(n.slot_utc_instant) FROM summary_slots n
                 WHERE n.chat_id = s.chat_id
                   AND n.slot_utc_instant > s.slot_utc_instant),
               s.slot_utc_instant + 86400) AS window_end
    FROM summary_slots s
    WHERE s.fired = 1
)
SELECT b.chat_id, b.local_date, b.local_slot,
       datetime(b.slot_utc_instant, 'unixepoch') AS slot_utc,
       b.window_end - b.slot_utc_instant AS window_seconds,
       (SELECT COUNT(*) FROM summary_runs r
         WHERE r.chat_id = b.chat_id
           AND r.manual = 0
           AND r.created_at >= b.slot_utc_instant
           AND r.created_at <  b.window_end) AS runs_in_window
FROM bounded b
ORDER BY b.slot_utc_instant, b.chat_id;
```

Q2 — сводка по тем же окнам:

```sql
WITH summary_slots AS (
    SELECT chat_id, local_date, local_slot, slot_utc_instant, fired
    FROM slot_claims
    WHERE kind = 'summary'
),
bounded AS (
    SELECT s.chat_id, s.slot_utc_instant,
           COALESCE(
               (SELECT MIN(n.slot_utc_instant) FROM summary_slots n
                 WHERE n.chat_id = s.chat_id
                   AND n.slot_utc_instant > s.slot_utc_instant),
               s.slot_utc_instant + 86400) AS window_end
    FROM summary_slots s
    WHERE s.fired = 1
),
counted AS (
    SELECT b.chat_id,
           (SELECT COUNT(*) FROM summary_runs r
             WHERE r.chat_id = b.chat_id
               AND r.manual = 0
               AND r.created_at >= b.slot_utc_instant
               AND r.created_at <  b.window_end) AS runs_in_window
    FROM bounded b
)
SELECT COUNT(*) AS fired_slots,
       SUM(CASE WHEN runs_in_window = 0 THEN 1 ELSE 0 END) AS gaps_no_run,
       SUM(CASE WHEN runs_in_window = 1 THEN 1 ELSE 0 END) AS ok_one_run,
       SUM(CASE WHEN runs_in_window >= 2 THEN 1 ELSE 0 END) AS dups_multi_run
FROM counted;
```

Q3 — обратная сторона: auto-run без покрывающего `fired=1` слота.

```sql
WITH summary_slots AS (
    SELECT chat_id, local_date, local_slot, slot_utc_instant, fired
    FROM slot_claims
    WHERE kind = 'summary'
),
bounded AS (
    SELECT s.chat_id, s.slot_utc_instant,
           COALESCE(
               (SELECT MIN(n.slot_utc_instant) FROM summary_slots n
                 WHERE n.chat_id = s.chat_id
                   AND n.slot_utc_instant > s.slot_utc_instant),
               s.slot_utc_instant + 86400) AS window_end
    FROM summary_slots s
    WHERE s.fired = 1
)
SELECT r.run_id, r.chat_id,
       datetime(r.created_at, 'unixepoch') AS run_utc, r.state
FROM summary_runs r
WHERE r.manual = 0
  AND NOT EXISTS (
      SELECT 1 FROM bounded b
       WHERE b.chat_id = r.chat_id
         AND r.created_at >= b.slot_utc_instant
         AND r.created_at <  b.window_end)
ORDER BY r.created_at;
```

### Прогон на синтетической схеме (результат)

Схема: боевые DDL `SLOT_CLAIMS_DDL_SQLITE` и `_SUMMARY_RUNS_DDL` (in-memory
SQLite), 9 строк `slot_claims` (8 summary: 7 `fired=1`, 1 `fired=0`
`missed_slot_expired`; 1 `goodmorning`), 8 строк `summary_runs` (1 `manual=1`,
1 без `fired=1`-слота, две в одном окне). Фактический вывод:

```text
Q1: 7 строк
  -1005 00 runs_in_window=1   -1001 00 runs_in_window=1
  -1005 06 runs_in_window=1   -1002 06 runs_in_window=0
  -1001 06 runs_in_window=1   -1003 12 runs_in_window=0
  -1002 12 runs_in_window=2
Q2: fired_slots=7  gaps_no_run=2  ok_one_run=4  dups_multi_run=1
Q3: 1 строка (r-1007-orphan, chat -1007)
```

Ожидания для прода после деплоя (окно с даты деплоя): `gaps_no_run = 0`,
`dups_multi_run = 0`, Q3 = 0 строк, `ok_one_run = fired_slots`.

Как читать расхождение:

- `runs_in_window = 0` — слот забронирован, auto-прогона в окне нет. Каждая
  такая строка = потерянный запуск (падение процесса между claim и run-row;
  `manual` сюда не входит осознанно). Разобрать по `chat_id`/`local_date`/
  `local_slot`: сверить `state` в `summary_runs`, WARN/ERROR в логах вокруг
  `slot_utc`; это P0-сигнал, не «шум».
- `runs_in_window >= 2` — два auto-run в одном окне слота: repair/retry-путь
  или запуск мимо claim. Само по себе не доказывает дефект, но каждый случай
  просматривается (`run_id`, `state`, `created_at`).
- Q3 > 0 — auto-run без `fired=1`-слота своего чата: запуск прошёл мимо
  claim-first (старый код/другой путь); сверить задеплоенный SHA.
- `fired=0` (`missed_slot_expired`) и `manual=1` из сверки исключены
  намеренно: первого не должно быть run'ов, второй не является слот-прогоном.

## 10. Гигиена

- `git diff --check` чист; EOL/BOM файлов совпадают с базой (после правки
  CRLF-флипа у `summary_scheduler.py`, `uptime_heartbeat.py`,
  `publication_coordination.py` diff снова минимальный).
- Временный detached worktree для base-проверки удалён без force; временные
  скрипты измерений/мутаций лежат вне репозитория.
- r2: изолированное дерево `72fbfe41` для проверки pre-existing падений
  получено через `git archive` (tar 836 МБ) во временный каталог вне
  репозитория; после прогона tar и распакованное дерево (828 МБ) удалены,
  worktree кандидата не менялся. Скрипты r2 (мутации, замер F1, синтетический
  SQL) — вне репозитория, в `%TEMP%\opencode`.
- r2: после каждой мутации файл восстановлен из бэкапа; `git status
  --porcelain` пуст, sha256 восстановленных файлов совпал с бэкапом.
- r2: добавлен компактный исполнимый артефакт
  `plans/features/llm-vision-scheduler-p0/evidence/sch/sch_reconcile.sql`
  (3 read-only SELECT, §9); на синтетической схеме прогнан именно он.
- Production не затрагивался; артефактов на сервере не создавалось.
