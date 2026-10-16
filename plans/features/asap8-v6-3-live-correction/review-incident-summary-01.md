# REVIEW-INC — независимая проверка фикса инцидента INC-SUMMARY-01 (stuck Summary)

Дата: 17.10.2026. Лейн: REVIEW-INC (read-only; деплой/SSH/коммитов нет).
Кандидат: HEAD `4c8405e7` + незакоммиченные правки двух полос (INC-FIX + INC-FIX-SHUTDOWN).
Привязка: sha256 файлов совпали с обоими fingerprint'ами
(`evidence/incident-summary-01/_fix_candidate_fingerprint.txt`,
`_shutdown_fingerprint.txt`): bot.py `aeca676e…`, summary_generator `d8623e02…`,
summary_scheduler `693487f5…`, summary_run_store `aa81a1b3…`, summary_memory `77e192df…`,
mca_gates `a7480da8…`, pipeline_events `27599291…`, оба новых теста — MATCH.
Три файла, которые полоса shutdown правила после fingerprint'а полосы fix
(generator/scheduler/run_store), соответствуют shutdown-fingerprint'у — правки объявлены.

## Вердикт

**Approved.** Реальная причина инцидента (SIGKILL-сирота без терминала) — **устранена**:
(а) graceful-путь снова достижим (измерено: 0.16–0.19 с вместо 60 с → SIGKILL),
(б) терминал пишется дренажом/`finally`,
(в) любой остаточный нетерминальный ран закрывается финализатором на старте процесса
(или штатным stale-closer'ом следующего прогона чата), а не живёт вечно.
Остаточные пути к нетерминальному рану перечислены в §8 — все самоизлечиваются.

## 1. Диагноз подтверждён (по установленным пакетам)

Цепочка перекрытия сигналов (прод-механика «60 с → SIGKILL, `on_shutdown` не запускался»):

* uvicorn 0.52.4 `server.py:80` (`serve()` → `capture_signals()`) и `:330`
  (`signal.signal(sig, self.handle_exit)`); `handle_exit` выставляет `should_exit` (`:342-347`).
* aiogram 3.31.0 `dispatcher.py:571-585`: при `handle_signals=True` (старый дефолт)
  `loop.add_signal_handler(SIGTERM, _signal_stop_polling)`; `:516` — та самая строка
  «Received SIGTERM signal» из прод-журнала.
* CPython `asyncio/unix_events.py:116`: `add_signal_handler` внутри делает
  `signal.signal(sig, _sighandler_noop)` и перезаписывает asyncio-обработчик.

Порядок до фикса: наш `add_signal_handler(stop_event.set)` → `await server.serve()`
(uvicorn ставит `handle_exit`) → первый запуск polling-таски (aiogram перекрывает ОБА:
Python-уровень → noop, asyncio-уровень → `_signal_stop_polling`). SIGTERM останавливал
только polling; `should_exit` не выставлялся; `serve()` не возвращался; `on_shutdown`
не исполнялся; `finally` прогона не исполнялся → SIGKILL через 60 с → вечный «running».
Прод-журнал (aiogram-строка + отсутствие «Bot shutting down…») это подтверждает.
Второй баг — `stop_event` без потребителя (`watcher` создавался и отменялся) — тоже
подтверждён по старому коду.

Фикс: `bot.py:1370` `start_polling(..., handle_signals=False)`; `:1192-1214`
`_install_signal_handlers` (POSIX `add_signal_handler`, Windows `signal.signal` +
`call_soon_threadsafe`) → `request_shutdown` (`:1341-1347`: stop_event + should_exit);
`:1396-1402` живой watcher; `:1404-1438` фаза `stopping` до отмены polling, затем
`on_shutdown` → дренаж.

Честная деталь по платформам: на Windows (дев) uvicorn `capture_signals` перекрывает наш
fallback-обработчик, пока идёт `serve()`, — в моём прогоне процесс останавливал именно
`Server.handle_exit` (он тоже выставляет `should_exit`, graceful-путь тот же). На POSIX
(прод) наш asyncio-обработчик сохраняется и срабатывает вместе с uvicorn-обработчиком
(оба идемпотентны). Путь «наш обработчик сам инициирует остановку» доказан тестом с
фейковым сервером (`test_sigterm_stops_process_via_our_handler_without_uvicorn_signals`).

## 2. Моё воспроизведение SIGTERM (реальный процесс, реальный uvicorn, реальный сигнал)

Скрипт: `OPENCODE_WORKFLOW_SCRATCH/incident-review/review_sigterm_repro.py` (три сценария).
Числа (Windows-дев, настоящий `bot.main()`):

| Состояние | Остановка | Терминал рана | Отправок |
|---|---|---|---|
| idle (нет прогонов) | **0.174 с** | — | 0 |
| in-flight прогон в LLM-стадии | **0.158 с** | FAILED/`shutdown` | 0 |
| in-flight обслуживание памяти (30 с) | **0.157 с** | FAILED/`shutdown` | 0 |

Повтор демо полосы (`_shutdown_sigterm_demo.py`) — PASS: 0.191 с / 0.173 с, терминал
`run/failed/shutdown`, `send_message=0`, обслуживание памяти после abort не продолжилось.
Все 4 строки фаз в журнале; `[shutdown] bye | elapsed_ms=`. Бюджет дренажа 20 с << systemd
`TimeoutStopSec=60 с`.

## 3. Дубли публикации / удаление памяти / ослабление границ

* Дренаж/финализатор не содержат ни одного send-пути: `abort_in_flight` только помечает
  контекст, отменяет таски и (backstop) пишет терминал; тесты и мой прогон — 0 отправок.
* `publication_status`: backstop/stale/orphan-closer (`close_stale_run`) его НЕ трогают
  (только `state` + стадия); `set_summary_run_publication` на уровне БД никогда не
  перезаписывает `published` (`database.py:4951-4952`); `_durable_run_finish` выставляет
  `failed` лишь для неопубликованного рана. Публикация опубликованного рана исключена.
* Ран с окном → resume ТОГО ЖЕ run_id (`get_active_summary_run_for_chat` + `run_has_window`);
  ран без окна → FAILED/`stale_no_window` + НОВЫЙ run_id (тесты обоих полос + мой прогон).
  Повторная отправка того же окна невозможна: абортированный ран терминален (не резюмится),
  опубликованный — gate `skip`, `publishing` — reconcile-лестница (pre-existing).
* Память: границы sibling-полосы нетронуты (sha256 совпал): бюджет 600 с, кап 20,
  no-progress guard, hard-fuse 900 с, пермит 300 с, stale 900 с, тик 3600 с; kill-switch
  default ON. Удаления/TTL/cutoff не менялись; extract-only по-прежнему маркирует
  `history_processed` и сохраняет батч при сбое (тесты). Ничего из памяти не удаляется.

## 4. Орфаны/устаревшие раны

`close_orphan_runs` переиспользует `close_stale_run` (дубля логики нет), grace 30 с,
ран с окном не трогается (resume §21), свежий (моложе grace) не трогается, владельцы
защищены (`_LIVE_RUN_IDS` в stale-closer'е, `_LIVE_RUN_TASKS` в дренаже). Вызов в
`on_startup` (`bot.py:460`) стоит ДО старта планировщика/поллинга — гонки нет.
`live_run_ids`-параметр прод-вызовом не передаётся, но на старте живых владельцев нет по
построению; от оверлапа защищает grace (см. §8).

## 5. Наблюдаемость (без нового UI)

Стадии `run_permit`/`run_memory_maintenance`/`run_source_window` видимы в существующих
liveness-карточках Analytics (`pipeline_analytics._liveness_cards` пропускает семейство
`run*`; тест через `collect_run(...)["liveness"]`); `duration_ms` в SOURCE_WINDOW —
допустимое поле mca_events. Причина остановки доходит до терминальной записи рана:
стадия `run`/failed/`reason_code=shutdown` + `SUMMARY_FAILED … reason=shutdown`.

## 6. Тесты

* `test_summary_inc01_shutdown.py` + `test_summary_inc01_pregen_bounds.py` — **27 passed**.
* Регресс-поверхность sibling-полосы (22 сьюта) — **674 passed** (совпало с отчётом).
* `test_bot_main_flow.py` + `t5150`-пин старт-порядка — **10 passed**.
* Полный прогон на текущем дереве — **13910 passed, 1 failed** (677 с):
  `test_nostalgia_worker.py::TestLLMAndSend::test_one_llm_call_one_send` — вне полосы:
  файл в изоляции 26 passed; в группе `mca09 block_a..e + nostalgia` воспроизводится
  1 фейл с РАЗНОЙ жертвой (я видел `test_handle_initiative_cancelled_by_recheck`,
  `test_candidate_ready_defers_intent_backoff`, `test_nostalgia_uses_background_role`,
  `test_year_back_candidate_sent`; полоса видела свои два), лог `initiative_decided |
  silent | stage=nostalgia_due` — order/time-зависимый флейк контура intents/initiative,
  файлы инцидента в нём не участвуют.
* Два фейла, о которых сообщала полоса shutdown: `test_soul1_factory_defaults::
  test_factory_default_is_the_catalog_code_canon` СЕЙЧАС ЗЕЛЁНЫЙ (файл 13 passed;
  `prompt_registry.py` правился W10 в 03:28 уже после их прогона — атрибуция «чужая
  in-flight полоса» подтверждена; W10-CAPABILITY действительно в полёте, workflow_state).
  `test_mca09…block_e` — тот же order-dependent флейк (в изоляции 15/15, три повтора;
  в группе плавает жертва).

## 7. Недекларированные изменения

Диффы всех 7 файлов инцидента содержат ТОЛЬКО хунки инцидента (проверены целиком:
сигналы/дренаж/финализатор/границы/стадии/гейты); совпадение хэшей с обоими
fingerprint'ами; тесты/демо/evidence на месте. Прочие изменённые файлы дерева —
объявленная работа соседних полос (soul-1 W10 и др.), в скоуп инцидента не входят.

## 8. Остаточные риски (честно)

Пути, которыми ран может остаться нетерминальным (все — класс «жёсткий обрыв»,
все самоизлечиваются):
1. SIGKILL/питание/падение процесса в любом месте прогона (включая окно между
   созданием рана и терминалом) → закрывается `close_orphan_runs` при следующем старте
   (возраст > 30 с) или stale-closer'ом следующего прогона чата.
2. Дренаж исчерпал бюджет (`left>0`) или запись терминала не удалась (БД/лок) →
   то же закрытие на следующем старте.
3. Узкая гонка: прогон, прошедший проверку приёма до `request_stop`, ждёт пермит дольше
   снимка дренажа и стартует после него; отмена на teardown — терминал обычно успевает,
   иначе см. п.1.
4. Отключение `SUMMARY_PREGEN_BOUNDS_ENABLED=0` (аварийный откат) снимает и стартовый
   финализатор, и stale-closer — при этом сценарии фантомы снова возможны до следующего
   включения; дефолт ON.
5. Оверлап двух живых процессов (ручной запуск): grace 30 с защищает только свежие раны;
   в проде рестарты последовательные (systemd), оверлапа нет.
6. Дубли доставки: смерть ровно между доставкой в транспорт и записью ledger →
   reconcile-лестница может повторить отправку (pre-existing at-least-once, не изменён).
   Дренаж наоборот СНИЖАЕТ этот класс: остановленный ран становится терминальным FAILED
   и не резюмится. Аборт посреди send может пометить доставленное как failed (unknown
   outcome) — косметика, повторной отправки того же окна нет.
7. Прочие closer'ы `on_shutdown` без таймаута (llm/search/checker/PG) — pre-existing;
   дренаж Summary идёт ПЕРВЫМ, новые строки `bye|elapsed_ms` покажут медленные фазы;
   при сумме > 60 с снова возможен SIGKILL, но фантом уже не выживет (см. п.1).

Новых путей, создающих НОВЫЙ фантом или дубль, правкой не добавлено.

## 9. Проверка на проде после деплоя (обязательная)

1. Рестарт сервиса: нет `State 'stop-sigterm' timed out. Killing.`; есть
   `[shutdown] signal handlers installed | signals=(2, 15)`, `phase=stopping` →
   `SUMMARY_SHUTDOWN_DRAIN phase=draining` → `phase=finalized` → `[shutdown] bye | elapsed_ms=`.
2. Старт: фантом `da33f05d…` закрыт (`SUMMARY_ORPHAN_RUN_CLOSED`/`stale_no_window`) либо
   уже самоизлечился resume'ом; ран с окном — `SUMMARY_ORPHAN_RUN_KEPT reason=has_window`.
3. Следующий плановый прогон: стадии `run_permit`/`run_memory_maintenance`/
   `run_source_window` видны в Analytics, терминал DONE/DEGRADED, при большом бэклоге —
   `extract-only bounded | reason=…`.
4. В `summary_runs` после любого рестарта не остаётся нетерминальных строк.

## 10. Parent-замечания (не блокеры этой полосы)

* В `requirements-map.json` нет записей INC-SUMMARY-01 — инцидент живёт по инструкции
  владельца; parent должен покрыть его в ledger/release-evidence.
* Флейк блока mca09/nostalgia (контур intents/initiative, `direct_chat_service.py` под
  активной правкой W10) — отдельная задача тест-здоровья дерева, не инцидент.
* Деплой: инцидент-коммиты выносить изолированно (как glass), SOUL-1 не выпускать;
  systemd-юнит менять не требуется (опционально TimeoutStopSec=90 как запас).
