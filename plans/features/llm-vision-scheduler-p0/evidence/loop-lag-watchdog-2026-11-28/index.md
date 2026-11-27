# F-STALL-01 — bounded loop-lag watchdog (2026-11-28)

Диагностический сторож задержек event loop. Продуктовое поведение не меняется:
модуль только наблюдает, ничего не отменяет/не прерывает, не завершает процесс
и не создаёт файлов-артефактов.

## 1. Кандидат

| Поле | Значение |
|---|---|
| Base | `886d11073cfdaa4646597c3a2b1ae09fde42c342` (развёрнутая 2.58.258) |
| Branch | `feat/loop-lag-watchdog` |
| Candidate (code) | `79f251587874d3f9a98cc6e9ad59921a8c73279b` |
| Worktree | `WorkspaceData/worktrees/c742e4de9e92c489/llm-vision-scheduler-p0-09bee2fc3ea3-d737cadc` |

Файлы: `services/loop_lag_watchdog.py` (новый), `bot.py` (+17/−1: старт в
`on_startup`, остановка в `on_shutdown`), `tests/test_loop_lag_watchdog.py`
(новый). `config/settings.py`, `routes.py`, version-пины и запрещённые
файлы не изменены (`git diff --stat 886d11073..HEAD` — только эти три файла).

## 2. Механизм и параметры

* `loop.call_later` раз в `tick_s` обновляет heartbeat (`_last_beat`), без
  отдельной asyncio-задачи.
* daemon-поток `loop-lag-watchdog` сравнивает heartbeat с `time.monotonic()`.
  Дамп делает **поток**, а не callback: callback в loop исполняется только после
  разблокировки, когда кадр виновника уже ушёл; поток снимает стек, пока loop
  ещё стоит, поэтому `file:line` блокирующего кадра сохраняется.
* При `lag >= threshold_s`: один `faulthandler.dump_traceback(all_threads=True)`
  в RAM-буфер (`memfd_create` на Linux; `TemporaryFile` delete-on-close на
  Windows) и одна WARNING-запись с `lag_ms`, `threshold_ms` и снимком
  (`snapshot_begin … snapshot_end`, `extra.event=loop_lag`, `loop_lag_ms`,
  `loop_lag_threshold_ms`, `loop_lag_snapshot_chars`).
* Антифлуд: повторный дамп не чаще `min_interval_s`; подавления считаются в
  `watchdog.suppressed`.
* Fail-open: ошибка старта/тика/дампа логируется один раз (`_error_logged`) и
  не ломает старт; при закрытом loop watcher просто останавливается.
* Выключение: `LOOP_LAG_WARN_S=0` (или явный `enabled=False`) — не стартует.
* Настройка только env (settings.py не тронут):

| Env | Default | Смысл |
|---|---|---|
| `LOOP_LAG_WARN_S` | `5.0` | порог лага, s; `0` — off; пусто/мусор/NaN/отрицательное — заводской `5.0` |
| `LOOP_LAG_MIN_INTERVAL_S` | `60.0` | антифлуд, s |
| `DEFAULT_TICK_S` | `1.0` | период heartbeat/проверки |

Ограничения: снимок обрезается до `SNAPSHOT_MAX_CHARS = 262_144` символов
(только хвост). Поток-наблюдатель не сможет снять дамп, только если C-код
удерживает GIL без переключения (для чистого Python GIL переключается каждые
5 ms, поэтому кадр снимается). Деплоя не было, прод не затрагивался.

## 3. RED/GREEN

RED (база без модуля, тот же тестовый файл):

```
$ mv services/loop_lag_watchdog.py <tmp>; pytest tests/test_loop_lag_watchdog.py -q
E   ImportError: cannot import name 'loop_lag_watchdog' from 'services'
1 error in 0.26s  (7 tests uncollected)
```

GREEN (кандидат `79f251587`):

```
$ pytest tests/test_loop_lag_watchdog.py -v
7 passed in 13.27s
```

| Node | Проверяет |
|---|---|
| `test_blocked_loop_reports_nonzero_lag_and_thread_snapshot` | блокировка `time.sleep(2.0)` при пороге 0.3 s → ровно 1 WARNING; `loop_lag_ms >= 300` (на прогоне ≈2 s); снимок непуст и содержит кадр заблокированного loop (имя теста в стеке) |
| `test_idle_loop_has_no_reports` | 2 s без блокировки, ≥20 heartbeat → 0 записей, `triggers=0` |
| `test_antiflood_one_record_per_blocked_episode` | 2 s блокировка → 1 запись; вторая блокировка внутри 60 s → по-прежнему 1, `suppressed>=1` |
| `test_invalid_env_falls_back_to_factory_and_starts` | `LOOP_LAG_WARN_S=not-a-number`, `LOOP_LAG_MIN_INTERVAL_S=abc` → `5.0/60.0`, старт OK; `-3` → `5.0` |
| `test_empty_env_uses_factory_threshold` | env отсутствует → `5.0` |
| `test_env_zero_disables_watchdog` | `LOOP_LAG_WARN_S=0` → `start()==False`, `start_from_env() is None` |
| `test_no_running_loop_start_is_fail_open` | `start()` вне loop из worker-thread → `False`, без исключения |

RED/GREEN подтверждают именно поведение: на базе модуля нет (ImportError), на
кандидате — реальные срабатывания/антифлуд/выключение/деградация env.

## 4. Смежные проверки

* `tests/test_t5150_startup_migrations_round1046.py tests/test_monitoring_smoke.py
  tests/test_smoke_round1016_fixes.py tests/test_smoke_round1016_tool_loop.py`
  → `31 passed in 16.41s`.
* `tests/test_round106_ia_smoke.py` → `3 failed, 42 passed`. Те же три red-а
  воспроизведены на базе `886d11073` (`3 failed, 42 passed`), к изменению
  отношения не имеют:
  * `tests/test_round106_ia_smoke.py::TestRuntimeGates::test_youtube_gate_only_summary`
  * `tests/test_round106_ia_smoke.py::TestModulesAndAi::test_modules_exactly_11`
  * `tests/test_round106_ia_smoke.py::TestA6A7A9::test_access_windows`
* `python -m py_compile bot.py services/loop_lag_watchdog.py
  tests/test_loop_lag_watchdog.py` → exit 0.
* `import bot` (с тестовым форматом `API_TOKEN`) → `bot_import_ok True`.

## 5. Изоляция записи

`git diff --stat 886d11073..HEAD`:

```
 bot.py                          | 18 ++-
 services/loop_lag_watchdog.py   | 345 ++++++++++++++++++++++++++++++++++++++++
 tests/test_loop_lag_watchdog.py | 184 +++++++++++++++++++++
 3 files changed, 546 insertions(+), 1 deletion(-)
```

`git diff 886d11073 -- config/settings.py routes.py services/factcheck_planner.py
services/search_aggregator.py services/mca_retrieval_context.py
services/direct_chat_service.py services/direct_execution.py web` — пусто;
version-пины (bump-набор 29 файлов/34 вхождения) не изменены.

## 6. Что осталось непроверенным

* Реальный прод-лаг этим кандидатом не воспроизводился (деплоя не было); при
  повторе инцидента запись `loop_lag | lag_ms=…` даст полный стек всех потоков.
* Снимок с C-расширением, удерживающим GIL, и «мгновенный» кадр внутри
  release-сборки Python не тестировались; на чистом Python механизм покрыт
  тестом с блокирующим кадром.
