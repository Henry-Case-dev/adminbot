# INC-SUMMARY-01-SHUTDOWN — грациозная остановка + финализатор Summary-ранов

Дата: 17.10.2026. Lane: `INC-FIX-SHUTDOWN` (writer: shutdown/recovery path + диагноз).
Деплоя/SSH/коммитов нет. Вход: `incident-summary-01-prod-forensics.md` (прод-факты),
`incident-summary-01-code-analysis.md`, `incident-summary-01-fix-report.md` (границы sibling-полосы: её
финализатор на старте/SIGTERM был явно ВНЕ scope — это моя полоса).

## 1. Диагноз: почему КАЖДЫЙ рестарт кончался SIGKILL через 60 с

Прод-факт (форензика): 8/8 рестартов 12.10–16.10 → `State 'stop-sigterm' timed out. Killing.` →
SIGKILL на 60-й секунде (`TimeoutStopUSec=1min`), `on_shutdown` не исполнялся ни разу (в журнале нет
«Bot shutting down...»). Причина — **две независимые ошибки в проводке сигналов `bot.py`**:

1. **SIGTERM переустанавливал aiogram** (до фикса: `bot.py:1250` создаёт `dp.start_polling(bot)` c
   `handle_signals=True` по умолчанию). Порядок установки хендлеров в проде:
   `bot.py:1269-1271` (`loop.add_signal_handler(sig, stop_event.set)`) → `bot.py:1277`
   `await server.serve()` → uvicorn `capture_signals()` делает `signal.signal(SIGTERM, handle_exit)`
   (`uvicorn/server.py:330`) → первое реальное засыпание loop'а запускает polling-таску → aiogram
   делает `loop.add_signal_handler(SIGTERM, _signal_stop_polling)` (`aiogram/dispatcher/dispatcher.py:571-585`),
   а `add_signal_handler` внутри — это `signal.signal(sig, _sighandler_noop)`
   (CPython `asyncio/unix_events.py:116`) → **хендлер aiogram перекрывает и uvicorn, и наш**.
   Следствие: SIGTERM останавливает только polling (`dispatcher.py:516` — та самая строка
   «Received SIGTERM signal» в прод-журнале), `server.should_exit` **не выставляется**, `serve()`
   не возвращается — graceful-путь недостижим. Подтверждено журналом: SIGTERM обработан aiogram'ом,
   а `on_shutdown` не запускался.
2. **`stop_event` не имел потребителя**: `watcher = asyncio.create_task(stop_event.wait())`
   (до фикса `bot.py:1274`) никто не ожидал и не использовал — таска отменялась в `finally`, не влияя
   ни на что. Т.е. даже если бы выиграл наш хендлер, `stop_event.set()` не завершил бы `serve()`:
   `request_shutdown` (единственный, кто выставляет `should_exit`, `bot.py:1226-1232` до фикса) был
   подключён только к dev-`ControlService`, не к сигналам.

Итог: процесс жил до SIGKILL; `finally` корутины прогона не исполнялся → терминала нет →
нетерминальная строка `summary_runs` + `start`-без-терминала в `mca_events` = вечный «running»
в UI/Oversight. Плюс отсутствовал финализатор нетерминальных ранов (watchdog репает только
`task_jobs`; startup-recovery не было).

Что удерживало процесс в drain-окне (форензика): `compress_and_purge` → `_compress_purge_extract_only`
без общего дедлайна — но остановка была бы неграциозной и без неё (п.1-2).

## 2. Что реализовано (file:line)

| # | Изменение | Где |
|---|---|---|
| 1 | Хендлер сигналов = `request_shutdown` (stop_event **+** `server.should_exit`), fail-open установка: POSIX `add_signal_handler`, Windows-дев `signal.signal` + `call_soon_threadsafe` | `bot.py:1185-1212` (`_install_signal_handlers`), вызов/лог `:1388-1390` |
| 2 | aiogram больше не трогает сигналы: `dp.start_polling(bot, handle_signals=False)` (корень п.1) | `bot.py:1366` |
| 3 | `stop_event` получил потребителя: watcher вызывает `request_shutdown` (идемпотентно) | `bot.py:1392-1397` |
| 4 | Фаза `stopping` до отмены polling: планировщик снят, новые прогоны не принимаются | `bot.py:1405-1413`, `services/summary_scheduler.py:219-232` (`stop_accepting`) |
| 5 | Bounded drain in-flight прогонов: пометка контекста причиной → `Task.cancel()` → `asyncio.wait(budget)` → терминал пишет сам `finally`; не успевшим — backstop-терминал (REUSE `close_stale_run`) | `services/summary_generator.py:528-625` (`request_stop`/`accepting_runs`/`abort_in_flight`), бюджет `services/summary_scheduler.py:39-64` (`SUMMARY_SHUTDOWN_DRAIN_SECONDS`, default 20 с), `drain_runs` `:242-249` |
| 6 | Реестр живых владельцев с таском и контекстом (`_LIVE_RUN_TASKS`) — регистрация рядом с `_LIVE_RUN_IDS`, снятие после терминальной записи | `services/summary_generator.py:456-466`, `:789`, `:984` |
| 7 | Новые прогоны во время остановки не начинаются (run-row не создаётся) + тик не стартует | `services/summary_generator.py:638-646`, `services/summary_scheduler.py:159-168` |
| 8 | Startup-recovery орфан-ранов: нетерминальный ран БЕЗ окна и без живого владельца → FAILED/reason (reuse stale-closer), ран С окном не трогается (resume §21), свежий ран (grace 30 с) не трогается | `services/summary_run_store.py:311-400` (`orphan_grace_seconds`/`list_nonterminal_runs`/`close_orphan_runs`), вызов: `bot.py:1087-1120` (`_recover_orphan_summary_runs`) → `on_startup` `bot.py:460` |
| 9 | Наблюдаемость: по одной строке на фазу — `phase=stopping` → `SUMMARY_SHUTDOWN_DRAIN \| phase=draining \| in_flight=N` → `phase=finalized \| finalized=M \| left=K` → `[shutdown] bye \| elapsed_ms=`; причина видна в Analytics через существующую поверхность (`summary_run_stages`: `run`/`failed`/`reason_code=shutdown`) | `bot.py:1122-1136`, `:1436`; `services/summary_generator.py:566-620`; `services/summary_scheduler.py:230` |

## 3. Локальная демонстрация (исполнено, настоящий SIGTERM процессу)

Скрипт-артефакт: `evidence/incident-summary-01/_shutdown_sigterm_demo.py`,
вывод: `evidence/incident-summary-01/_shutdown_sigterm_demo_output.txt` (exit code 0, `ИТОГ: PASS`).

Сценарий: реальный `bot.main()` (реальный uvicorn на эфемерном порту) + реальный прогон Summary,
вошедший в обслуживание памяти (`compress_and_purge` спит 30 с) → процессу доставлен
`signal.raise_signal(SIGTERM)`.

```
[demo] main() поднят (реальный uvicorn), start_polling kwargs={'handle_signals': False}
[demo] SIGTERM-хендлер до сигнала: <bound method Server.handle_exit ...> (не SIG_DFL: True)
[demo] бюджет дренажа = 20.0 с
[demo] процесс остановился сам за 0.193 с (SIGKILL не потребовался)
[demo] runs=[{'run_id': 'c37fd788…', 'state': 'FAILED', 'publication_status': 'failed'}]
[demo] stages=[{'run_permit','ok','immediate'}, {'run','failed','shutdown'}]
[demo] отправок сводки (bot.send_message): 0
[demo] обслуживание памяти продолжилось после abort: False
[demo] run_task завершён: True, отменён: True
INFO bot: [shutdown] signal handlers installed | signals=(2, 15)
INFO services.summary_scheduler: [shutdown] summary: stopped accepting new work | phase=stopping …
INFO services.summary_generator: SUMMARY_SHUTDOWN_DRAIN | phase=draining | in_flight=1 | cancelled=1 | timeout_s=20.0
WARNING services.summary_run_log: SUMMARY_FAILED | run_id=c37fd788… | stage=shutdown | reason=shutdown
INFO services.summary_generator: SUMMARY_SHUTDOWN_DRAIN | phase=finalized | finalized=1 | left=0 | elapsed_ms=0
INFO bot: [shutdown] bye | elapsed_ms=0
[demo] пустая система (нет прогонов): остановка за 0.173 с
[demo] ИТОГ: PASS
```

Сравнение с прод-фактом: было 60.000 с → SIGKILL и терминала нет; стало **0.193 с** (in-flight прогон)
и **0.173 с** (пустая система), терминал `FAILED`/`reason=shutdown`, публикаций 0.

## 4. Тесты

Новый файл `tests/test_summary_inc01_shutdown.py` — **14 passed** (`pytestmark = asap41`;
`TEST-LIFECYCLE: REGRESSION owner=INC-SUMMARY-01/shutdown` в шапке и в docstring'ах):

1. `test_sigterm_during_inflight_run_terminal_state_bounded_exit` — настоящий uvicorn + настоящий
   SIGTERM: терминал `FAILED`/`shutdown`, 0 публикаций, `left=0`, остановка < бюджета, все 4 строки фаз;
2. `test_sigterm_stops_process_via_our_handler_without_uvicorn_signals` — фейковый сервер (выходит
   только по `should_exit`): остановку инициирует НАШ хендлер (без фикса тест висел бы);
3. `test_install_signal_handlers_registers_request_shutdown` — хендлер = `request_shutdown`;
4. `test_install_signal_handlers_windows_fallback` — Windows-ветка (`signal.signal`), с откатом хендлеров;
5. `test_drain_finalizes_inflight_run_reason_shutdown_no_send` — bounded abort (обслуживание памяти не
   продолжилось), терминал с причиной, догон в НОВОМ процессе = ровно 1 отправка;
6. `test_drain_idle_is_fast` — пустой дренаж < 0.5 с, честные счётчики;
7. `test_drain_two_chats_in_flight_both_finalized` — два чата в полёте → оба терминала;
8. `test_new_run_refused_after_stop` — новый ран не создаётся, отправки нет;
9. `test_stop_accepting_shuts_scheduler_and_tick_skips` — идемпотентность + тик не стартует;
10. `test_startup_recovery_closes_orphan_without_window` — орфан → FAILED/`orphan_no_owner`,
    `publication_status` не тронут; ран с окном и свежий ран не тронуты;
11. `test_startup_recovery_keeps_windowed_run_then_resumes_same_run_id` — resume того же run_id,
    ровно одна отправка;
12. `test_recover_orphan_helper_closes_and_logs` — функция, которую зовёт `on_startup`;
13. `test_bot_wiring_guard` — guard проводки: `on_startup` → startup-recovery, `on_shutdown` → дренаж,
    `start_polling(handle_signals=False)`;
14. `test_shutdown_env_axes_fail_safe` — env-ручки остановки (default/значение/мусор/floor).

Регресс-поверхность sibling-полосы (её список §5) — **674 passed**; совместно с новым файлом и
`test_bot_main_flow.py`, `test_summary_*`, `test_asap8_v63_b06_summary_scope` — **231 passed** в
отдельном прогоне (без warnings); файлы, читающие `bot.py` как текст (source-пины: `test_t5150*`,
`test_menu`, `test_permsoc`, `test_webapp_*`, `test_mca10c/11/17a/19`, `test_graphrag_memory`,
`test_summary_deploy/publish_integration`, `test_asap8_f5_module_truth`, `test_betterstack_handler`,
`test_log_ring`, `test_smoke_round1016_fixes`) — **626 passed**.
Полный прогон `pytest` (`--tb=line -rf`, без `-x`) — **13819 passed, 2 failed** (572 с),
`evidence/incident-summary-01/_shutdown_full_suite.txt`. Оба фейла — вне этой полосы
(доказательство: воспроизведение/изоляция ниже):

* `tests/test_soul1_factory_defaults.py::test_factory_default_is_the_catalog_code_canon` — падает и
  в одиночном прогоне; предмет — канон `prompt_registry.factory_default` vs код-каталог
  (`services/prompt_registry.py`), который правил СОСЕДНИЙ lane (коммит `4c8405e7`, SOUL-1 W3).
  Мои файлы этот контур не трогают. Классификация: `unrelated` (чужая активная полоса).
* `tests/test_mca09_intents_block_e_round1040.py` — в полном прогоне падает ОДИН тест файла
  (в двух прогонах — разные: `test_initiative_output_kind_and_single_send_path` и
  `test_handle_initiative_sent_single_transport_chunks`), а файл целиком в изоляции — **15 passed**,
  и группа `test_mca09_intents_block_a..e` — **72 passed**. Классификация: `pre-existing`
  order-dependent флейк (source-text ассерты о `_f6_create_future_intent`/initiative-пути;
  мои модули на этом пути не участвуют).

**Найдено и закрыто своей же правкой:** пины старт-порядка `test_t5150_startup_migrations_round1046`
берут ПЕРВОЕ вхождение литералов (`await server.serve()`, `await on_startup()`,
`server = uvicorn.Server(`) через `src.index(...)` — мой пояснительный комментарий содержал
`await server.serve()` и сдвигал пин. Комментарии переписаны без этих литералов, пин зелёный
(в коде рядом оставлено предупреждение для следующих правок).

## 5. Нужно ли менять systemd-юнит?

**Нет.** Приложение теперь выходит само за десятые доли секунды (демо: 0.19 с), то есть задолго до
`TimeoutStopUSec=1min`; юнит-файл трогать не требуется. Бюджет дренажа ограничен и настраиваем
(`SUMMARY_SHUTDOWN_DRAIN_SECONDS`, default 20 с — втрое меньше таймаута systemd).
Если оператор хочет запас на будущее — единственная осмысленная директива
`TimeoutStopSec=90` (в `[Service]` юнита `admin_bot`), но это не обязательно для закрытия инцидента.

## 6. Что не менялось

- Публикация: `_publication_gate`, `publication_status`, content-hash/reconcile-лестница — не тронуты;
  повторной отправки не бывает (абортированный ран закрывается FAILED, `publication_status` не
  перезаписывается; окно/данные памяти не удаляются).
- Каденс крона, окно 6 ч, `max_instances/coalesce`, семантика `history_processed`, границы
  sibling-полосы (`SUMMARY_PREGEN_BOUNDS_ENABLED` и её лимиты) — без изменений; новых флагов не
  включалось.
- SOUL-1, `services/style_policy.py`, карты, `plans/current_task.md`, `plans/workflow_state.md`,
  версии — не тронуты.

## 7. Честные ограничения / риски

1. **Хвост edge-case'ов остановки.** Backstop-терминал (когда `finally` не уложился в бюджет) пишет
   `FAILED` даже если публикация уже состоялась (тогда `publication_status='published'` остаётся) —
   это редкий случай (в демо/тестах `finalized` шёл штатным `finally`, backstop не потребовался).
   Читается честно: «опубликовано, но прогон прерван остановкой»; повторной отправки нет.
2. **Прочие closers `on_shutdown` не ограничены по времени** (llm/search/web/checker/PG-пул) — это
   pre-existing; моя полоса добавила только фазу Summary и её бюджет. Если прод-журнал после деплоя
   покажет медленную фазу, её нужно ограничивать отдельно (сейчас невидима — добавленные строки
   `phase=…`/`bye | elapsed_ms` как раз это и покажут).
   Отдельно: фоновый `MemoryMaintenanceService` (merge/review/WAL) не ожидается — его `shutdown()`
   снимает планировщик `wait=False` и возвращается сразу (pre-existing поведение, вне write-scope),
   т.е. процесс он не блокирует; его in-flight job при этом не отменяется явно (как и раньше).
3. **Проверка на проде** (вне этой полосы): после деплоя ожидаем в журнале `[shutdown] signal handlers
   installed | signals=(2, 15)`, четыре строки фаз при рестарте и отсутствие `stop-sigterm timed out`;
   орфан-строки закрываются на старте (`SUMMARY_ORPHAN_RUN_CLOSED`), ран с окном — резюмится как раньше.
4. **Кросс-платформенность сигналов**: на Windows (дев) `add_signal_handler` недоступен — используется
   `signal.signal`-ветка; прод (Linux) идёт штатным `add_signal_handler`. Обе ветки покрыты тестами.
5. **Manual `/summary` в окне остановки** получает молчаливый отказ (лог `new run refused`) — процесс
   в этот момент уже гасит polling, отдельная UX-фраза не вводилась (не расширяем user-visible
   поверхность без требования).
6. **Тесты локальны**: фикстура `bot_module` снимает `SENTRY_DSN`, который `.env` подкладывает в
   окружение при импорте `config.settings` — иначе ERROR-терминал абортированного прогона улетал бы
   в прод-Sentry. Демо-скрипт делает то же самое.
