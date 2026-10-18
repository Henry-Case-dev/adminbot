# INC-SUMMARY-01 — прод-форензика «зависшего» Summary-прогона (read-only)

Лейн: INC-SUMMARY-01 (devops-форензика). Дата сбора: 2026-10-16 ~14:09–14:16 UTC.
Прод: `198.46.175.136` (`racknerd-f4e3456`), сервис `admin_bot`, каталог `/var/www/admin_bot`.
Деплой: **2.58.81 @ `6d4b9a7d`**, ветка `release/glass-2.58.81`, HEAD сервера = `6d4b9a7d` (совпадает с релизом).
Сервер живёт в **UTC**; часы владельца/машины задач — **UTC+12** (17.10 01:00:06 local = 16.10 13:00:06 UTC).
SSH: **3 логина** (recon + main + follow-up), все успешные, read-only, без ретраев. Секреты замаскированы.

## Вердикт (одной строкой)

Прогон **не завис**: процесс, выполнявший его, был **SIGKILL-нут рестартом деплоя** через 62 с после старта
(run start 13:00:06 UTC, SIGTERM 13:00:08, SIGKILL 13:01:08). Терминальное событие не эмитилось →
UI/Oversight показывает вечный `running` (это **фантомная запись**, а не работающий пайплайн).

## Хронология (UTC = сервер; local = UTC+12)

| Время UTC | Local (UTC+12) | Событие (источник) |
|---|---|---|
| 07:00:00 | 16.10 19:00 | cron 12:00 YEKT → run `30b3677b758246188363aeb2561d1402` (старый PID 2594113) |
| 07:14:40 | 16.10 **19:14** | `SUMMARY_PUBLISH` rich + `SUMMARY_RUN_DONE` degraded — **последняя успешная публикация** (= слова владельца «19:14») |
| 13:00:00.026 | 17.10 01:00:00 | cron 18:00 YEKT: `SummarySchedulerService._tick` в **старом** PID 2815638 |
| 13:00:05.922 | 01:00:05 | `summary: cron skip (disabled, source=chat) | chat_id=-1004482340693` |
| **13:00:06.182** | **01:00:06** | `SUMMARY_START | run_id=da33f05db7754a38bdea7d591cf6eccc | chat_id=-1002661910336 | mode=hybrid_l2 | manual=False` (= «01:00:06» владельца) |
| 13:00:06 | 01:00:06 | durable `summary_runs` row CREATED (`created_at=1792155606`); `mca_events` `SUMMARY_RUN_START` (id 59275) |
| 13:00:08.135 | 01:00:08 | **SIGTERM** (деплой 2.58.81, фаза D `systemctl restart`); aiogram: «Received SIGTERM signal» |
| 13:00:21 / 13:00:40 / 13:01:04 | 01:00:21…01:01:04 | старый процесс **продолжал run**: `graph_extract` LLM OK ×3 (lat 5.0/7.3/10.5 с) + `graph: triplets=19/22/13` + write saved |
| **13:01:08** | 01:01:08 | systemd: `State 'stop-sigterm' timed out. Killing.` → **SIGKILL** PID 2815638; `Failed with result 'timeout'`; сразу `Started` нового PID **2854731** (= ExecMainStartTimestamp) |
| 13:01:27 | 01:01:27 | новый процесс: миграции промптов, `user_version=35`, `SmartModule scheduler started (cron 0,6,12,18 Asia/Yekaterinburg)` |
| 13:01:28 → now | — | никаких `SUMMARY_*`/`SUMMARY_RESUME` от нового процесса; следующий cron 19:00 UTC (17.10 00:00 YEKT) ещё не наступал |

## Застрявший run (БД, read-only SQLite `local_database.db`)

* `summary_runs`: `('da33f05db7754a38bdea7d591cf6eccc', -1002661910336, 'CREATED', manual=0, window_from/to=NULL,
  source_ref/publication_status/publication_result_ref/pipeline_health=NULL, created=updated=1792155606)` —
  единственная нетерминальная строка во всей таблице (`states: CREATED 1 / DEGRADED 30 / DONE 21`). Дублей нет.
* `summary_run_stages`: строк для run_id **нет** (ни одна стадия не записалась) → «stages 0/0» в UI.
* `mca_events`: ровно **1 событие** у run: `(id=59275, ts=1792155606, SUMMARY_RUN_START, outcome=start, stage=start,
  pipeline_run_id=da33f05…, pipeline_type=summary, usage_json={"mode":"hybrid_l2","manual":false})`. Терминала нет.
* Сравнение: предыдущий run `30b3677b…` = 49 событий, последние — `SUMMARY_PUBLISH`/`SUMMARY_RUN_DONE` (degraded).
* `summary_source_windows`: окна у stuck-run нет (умер до SOURCE_WINDOW) — только у прошлых 5 run'ов (всего 51).

## Где реально остановился процесс (доказано)

1. `_durable_run_create` прошёл (строка CREATED) → дальше по коду `memory.compress_and_purge(chat_id)`.
2. Хот-конфиг (PG `bot_settings`): `memory.infinite_retention=true`, `limits.full_memory_retention_days=30`,
   `limits.summary_compress_batch=50`, `flags.summary_enabled=true`, `flags.graph_rag_enabled=true` →
   работала ветка **`_compress_purge_extract_only`** (без сжатия): `smart_archive_facts=0` строк, сырьё не удалялось
   (2 023 810 строк в чате), а граф пополнялся.
3. Журнал: 13:00:21 / 13:00:40 / 13:01:04 — три успешных LLM-вызова `purpose=graph_extract` + `graph: triplets=19/22/13`
   + `pipeline_step component=graph step=write status=ok reason=saved`. **Петля работала штатно** (~20 с/батч), не висела.
4. Никаких `SOURCE_WINDOW`/L1/L2/LLM-стадий у stuck-run нет — до них не дошло (умер раньше).
5. Деградация embedding-контура (`embedding generation not serviceable`, quota-parked, FTS-fallback) — фоновая,
   была и у прошлых прогонов; граф-запись от неё не зависит (facts text-only). На инцидент не влияла.

## Почему нет терминального события (доказано)

* Терминал эмитится в `finally` корутины `_run()` (`finish_run` + `pipeline_events.summary_done_from_ctx` +
  `_durable_run_finish`). **SIGKILL не даёт исполнить `finally`** — события нет.
* `on_shutdown` (bot.py) **не запускался вовсе**: в журнале нет ни «Bot shutting down...», ни `[shutdown] closer…`,
  ни «SmartModule scheduler stopped» — graceful-путь не сработал (см. ниже про хронический SIGKILL).
* Watchdog есть (`mca_watchdog`, `WATCHDOG_SWEEP` каждые 60 с — живой), но он следит только за `task_jobs`
  (`running` + stale heartbeat). Summary-run — не task_job → **его никто не финализирует**.
* Нетерминальные строки `summary_runs` TTL-purge не чистит (гейт «только терминальные») — фантом живёт вечно.
* UI/Oversight (`oversight_router._derive_status`) считает run `running`, пока в `mca_events` есть `start` без терминала.

## Механика рестарта (важно для релиз-инженера)

**Все рестарты сервиса как минимум с 12.10 завершаются SIGKILL ровно через 60 с** (TimeoutStopUSec=1min):
12.10 ×3, 13.10 ×1, 15.10 ×2, 16.10 ×2 (09:43 и 13:00) — везде `Stopping → Received SIGTERM → State 'stop-sigterm'
timed out. Killing. → SIGKILL → Started`. Graceful-путь (`stop_event`/`on_shutdown`) не срабатывает ни разу —
это **хроническое** свойство текущего рантайма, а не особенность этого деплоя. Следствие: любой рестарт во время
Summary-прогона гарантированно рождает такой фантом (и обрывает прогон без терминала).
Примечание: именно петля `compress_and_purge` держала процесс занятым в drain-окне 13:00:08→13:01:08
(LLM-вызовы продолжались до последней секунды) — но остановка была бы неграциозной и без неё.

## Scheduler/конкурентность/очередь

* `max_instances=1 + coalesce=True`: следующий тик после 13:00 не пропускался — его просто не было (cron 19:00 UTC).
  Новый процесс перерегистрировал джоб в 13:01:27; пропущенных/поставленных в очередь тиков нет.
* Слот конкурентности (per-chat in-memory permit) умер вместе со старым процессом; новый процесс **ничего не держит**.
  `task_jobs`: активных (queued/running) **нет** вообще; summary-подобных job'ов нет (только cover_* прошлых run'ов, completed).
* Предсказуемое само-лечение: тик 19:00 UTC (00:00 YEKT) вызовет `get_active_summary_run_for_chat` →
  **resume того же run_id** `da33f05…` (snapshot окна отсутствует → честный fresh-перечит, `resumed=False`, тот же run_id);
  успешный терминал по этому run_id уберёт фантом из UI. (Проверяемо одним read-only прогоном после 19:05 UTC.)
* Бэклог extract-only: необработанных live-строк 71 867; «созревших» (старше 30 дней) — **758** → ~16 батчей × 50,
  т.е. штатно ~5 мин на прогон (у прошлого run'а фаза extract ~3 мин, 7 LLM-вызовов) — не «часы».
* Ингест живой: 2 025 589 строк, последняя 14:10:42 UTC; за окно +1 643 сообщения.
* LLM: за окно ошибок/таймаутов нет (единственный `timeout` — `image_generate` 08:28 UTC, не связано).
* Локи: `database is locked` = 0 за окно; SQLite WAL 4.2 МБ; PG-снапшот чист (нет долгих запросов/ожиданий/блокировок).

## Вердикт по гипотезе владельца — **частично подтверждена**

* **Подтверждено**: unlimited memory ON (`memory.infinite_retention=true`); run действительно шёл внутри
  `compress_and_purge` → `_compress_purge_extract_only` (GraphRAG-петля до SOURCE_WINDOW, без общего дедлайна);
  петля — единственное, что удерживало процесс в drain-окне до SIGKILL.
* **Опровергнуто**: «петля висела/задержала публикацию на 48+ мин» — процесс убит через 62 с, петля шла штатно
  (~20 с/батч) и успела 3 батча; 48+ мин `running` — **фантом UI** из-за SIGKILL без терминала и отсутствия
  финализатора/вотчдога для summary-run, а не живой прогон.
* Сопутствующая причина (релиз-механика): рестарт деплоя совпал с cron-тиком (13:00:08 vs 13:00:06) — гонка
  «релиз × расписание»; плюс хронический неграциозный stop (60 с → SIGKILL) на всех рестартах.

## PROVEN / UNPROVEN

* **PROVEN**: timeline и SIGKILL (journald+systemd); состояние stuck-run (CREATED, 1 событие, 0 стадий);
  вход в extract-only петлю и её нормальный прогресс; отсутствие терминала/`on_shutdown`; отсутствие
  watchdog'а для summary-run; хот-конфиг (PG); пустая очередь task_jobs; чистые локи; хронический SIGKILL на всех
  рестартах с 12.10; отсутствие дублей run'а; предсказуемый resume тем же run_id на 19:00 UTC (код + строка CREATED).
* **UNPROVEN / границы**: точные причины неграциозного stop (почему не срабатывает `stop_event`/uvicorn/aiogram
  цепочка) — нужен отдельный разбор сигнальных хендлеров; фактический исход resume на 19:00 UTC (проверяемо);
  поведение при рестарте в других стадиях (L1/L2/publish) не наблюдалось в этом инциденте.

## Рекомендуемый следующий прод-проб (один, read-only)

После **19:05 UTC** (00:05 YEKT) один прогон: journal 19:00–19:30 + `summary_runs`/`mca_events` по `da33f05…` —
подтвердит, что resume-путь закрывает фантом тем же run_id (и что публикация 18:00 YEKT-крона состоялась).
Больше прод-коннектов для проектирования фикса не требуется; рекомендации по фиксу (финализатор орфанов на старте /
терминал при SIGTERM / релизный гейт «не рестартовать во время Summary-тика» / грациозный stop) — за parent-лейном.

## Evidence

`evidence/incident-summary-01/`: `recon.txt` (identity), `main.txt` (journal 12:30→now + 06:50–07:30, SQLite-дамп,
py-spy=n/a, net/ресурсы), `main2.txt` (история рестартов, SQLite-добивка, PG hot-config + снапшот), `probe.py`/`probe2.py`
(точные скрипты сбора; секреты читаются из `deploy_commands.txt` и не печатаются).
Скрипты/черновики: `OPENCODE_WORKFLOW_SCRATCH/incident-summary-01/`.
