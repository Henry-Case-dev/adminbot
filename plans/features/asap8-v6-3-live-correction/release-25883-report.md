# RELEASE-INC-25883 — финальный изолированный инцидент-релиз (2.58.83): отчёт

Дата: 2026-10-16 18:07–18:12 UTC (+ follow-up после 19:00 UTC). Лейн: RELEASE-INC-25883 (release engineer).
Владелец: закрытие INC-SUMMARY-01 (graceful exit) + отложенная проверка планового прогона Summary.

## Вердикт (одной строкой)

**Кандидат `448cc81a` (2.58.83) задеплоен на прод и здоров; обязательный live-чек graceful-exit ВЫПОЛНЕН:
`stop-sigterm timed out` ИСЧЕЗ (B2_STOPSIGTERM=0, SIGKILL нет), `Polling stopped` идёт ДО `bye`,
`runtime sqlite closed` есть, `SUMMARY_SHUTDOWN_SQLITE_LEFTOVER` отсутствует (open=0 строки нет);
нетерминальных Summary-ранов 0, фантом остаётся FAILED. Отложенный плановый прогон 19:00 UTC
состоялся УЖЕ на 2.58.83 и дал РЕАЛЬНУЮ публикацию (rich `message_id=1162997`, терминал DEGRADED —
предсуществовавший legacy-fallback Hybrid-L2, не связан с инцидент-фиксом).
Coverage-гейт родительской карты остаётся RED (карта не про инцидент, DO_NOT_TOUCH) → за parent/PM.**

## Deploy binding

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | локальный репо `C:\Code\Python\adminbot`, ветка `release/incident-2.58.83`, релизный коммит `448cc81a9eab590ea6de599f478220dd00abd3d1` |
| База ветки | **`7e9ce8cb`** (задеплоенный 2.58.82) |
| Состав | `7e9ce8cb` + cherry-pick **`0a532f9e`** (residual exit fix; применился ЧИСТО) = `7ebb44d4` + bump = **`448cc81a`** |
| Residual-fix commit на master | **`0a532f9e`** (parent `e4bb51d8`), 17 файлов, `git diff --cached --name-only` проверен перед коммитом; в локальной истории master её родитель — коммит W10 `c8cf77a5` (см. §master re-sync) |
| Push | `git push -u origin release/incident-2.58.83` (обычный, без force) |
| Сервер | fetch + `git checkout -B release/incident-2.58.83 origin/release/incident-2.58.83`; HEAD `448cc81a`, TRACKED_MOD=0, COMMITS_ON_BRANCH=**2**, DELTA_FILES=**48** (17 инцидент + 31 bump) |
| MUTABLE_WORKTREE_REQUIRED | **no** — деплой из immutable закоммиченного дерева; main worktree (W10 lane, SOUL-1 WIP) не тронут |
| DDL / миграции | ΔDDL = 0 |
| Версии | 2.58.82 → **2.58.83** (31 файл, 33 ins/33 del: settings + README + F8-meta (HEAD `7ebb44d4`) + 24 py + 4 JS) |
| Rollback | `release/incident-2.58.82` = `7e9ce8cb` (2.58.82) |

## Изоляция (проверено)

1. `git log --oneline 7e9ce8cb..release/incident-2.58.83` = **ровно 2 коммита** (`448cc81a` bump, `7ebb44d4` cherry-pick) — `evidence/release-25883/branch-log.txt`.
2. Diff по SOUL-1 файлам (`services/prompt_registry.py|prompt_factory.py|prompt_composer.py|style_policy.py|chat_prompts.py|response_extent.py|direct_l1.py`) = **пуст** (`soul1-diff-empty.txt`, 0 байт).
3. Diff по W10 файлам (`services/capability_registry.py|direct_capabilities.py|direct_chat_service.py|image_generation.py|chat_prompts.py|prompt_registry.py`) = **пуст** (`w10-diff-empty.txt`, 0 байт).
4. Дельта vs deployed = **17 файлов** (`isolation-note.txt`); на сервере `W1_REGISTRY_ABSENT=1`, `W1_FACTORY_ABSENT=1`, `W3_STYLE_ABSENT=1`, `W10_CAPREG_ABSENT=1` (W10-файл `capability_registry.py` на прод НЕ попал), стекло цело (`SCALE32=1`, `LENS_MAP_REF=1`, стенд 6×404).
5. Дельта деплоя не касается файла/ассетов предсуществующего RED-пина `test_modal_backdrop_blur_token`; на сервере `web/*` == байтам релизного коммита.

## Фокусные проверки кандидата (detached worktree `OPENCODE_WORKFLOW_SCRATCH/inc83-tests`, HEAD `448cc81a`)

| Проверка | Результат |
|---|---|
| `tests/test_summary_inc01_exit.py` + `test_summary_inc01_pregen_bounds.py` + `test_summary_inc01_shutdown.py` | **33 passed** (6 + 13 + 14) |
| Регресс-поверхность (те же 22 сьюта sibling-полосы) | **674 passed**, 2 warnings |
| Source-пины `bot.py` (77 файлов по glob-паттернам релизного отчёта: t5150*/menu/permsoc/webapp_*/mca10c/11/17a/19/graphrag_memory/summary_deploy+publish/asap8_f5/betterstack/log_ring/smoke1016) | **1881 passed / 1 failed** |
| 4 JS-пина (после bump) | `HOTFIX7/8/9/10 … OK` (4/4) |
| `tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 572 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны` |

Единственный FAIL — `tests/test_webapp_ui_rework_round1020.py::TestLiquidGlass::test_modal_backdrop_blur_token`:
**предсуществующий**, воспроизведён в изолированном прогоне на ЗАДЕПЛОЕННОМ `7e9ce8cb` (1 failed) и на
кандидате (1 failed); файл теста и ассеты в дельте релиза не менялись; у соседней полосы уже есть незакоммиченный
re-pin (HOTFIX-TIERA). В дельту 2.58.83 не входит.

Отличие от прошлого релиза: прошлый лейн гонял «89 файлов» пинов и получил 2046 passed; мой glob-набор даёт
**77 файлов** (1881 passed / 1 failed) — тот же класс (файлы, читающие `bot.py` как текст) и тот же единственный
предсуществующий RED.

## Прод-верификация (всё с сервера; лог `evidence/release-25883/ev_deploy_run.txt`)

### Артефакты и отдача (Фаза C/C2/E)
- 18 raw-файлов == байтам релизного коммита: `bot.py` `b5190efe…` (residual fix), `summary_run_store.py`
  `13b2f02a…`, `test_summary_inc01_exit.py` `e485aa06…`, `_inc01_exit_child.py` `8e39c116…`,
  `config/settings.py` `e2b06872…`, `web/*`, `services/param_catalog|mca_gates|pipeline_events|summary_generator|summary_memory|summary_scheduler`, оба inc01-теста, meta, README.
- healthz loopback и 443: `{"status":"ok","version":"2.58.83"}`; `/web/` = substituted-байты `c1987340…`
  (14×`2.58.83`, 0×`2.58.82`); `/static/app.css` substituted `d14a7818…`; `/web/static/app.css` raw `c28d4c89…`;
  `/web/app.js` raw `828d265b…`; стенд 6 путей 404; живые ассеты и `/healthz` 200.
- Runtime-проба: `version=2.58.83`, W1/W3/W10 отсутствуют, `pregen_bounds_enabled=True`, `run_durable_enabled=True`,
  `orphan_grace=30.0`, `stale_run_seconds=900`, и все четыре маркера residual-фикса:
  `_close_runtime_sqlite_db=True`, `_stop_polling_task=True`, `_leftover_sqlite_connections`+`SUMMARY_SHUTDOWN_SQLITE_LEFTOVER=True`,
  `_emit_closed_run_terminal_event=True`.

### Graceful exit — обязательный чек ИНЦИДЕНТА
Рестарт №1 останавливал СТАРЫЙ 2.58.82 (фикса в нём нет — последний неграциозный стоп неустраним задним числом):
`STOPSIGTERM=1`, `ERR=1`, `CRIT=0`, `TB=0`.

Рестарт №2 останавливал НОВЫЙ 2.58.83 (процесс 2916597), порядок строк журнала:
```
18:10:14,607 services.summary_scheduler INFO [shutdown] summary: stopped accepting new work | phase=stopping
18:10:14,610 aiogram.dispatcher INFO Polling stopped for bot @PERMsoc_bot id=8802473181 - 'Базовичок'
18:10:14,627 aiogram.dispatcher INFO Polling stopped
18:10:14,885 __main__ INFO [shutdown] polling stop | graceful=True | elapsed_ms=277
18:10:14,899 services.summary_generator INFO SUMMARY_SHUTDOWN_DRAIN | phase=draining | in_flight=0 | cancelled=0 | timeout_s=20.0
18:10:14,900 services.summary_generator INFO SUMMARY_SHUTDOWN_DRAIN | phase=finalized | finalized=0 | left=0 | elapsed_ms=1
18:10:14,900 __main__ INFO [shutdown] summary drain done | in_flight=0 | cancelled=0 | finalized=0 | left=0 | elapsed_ms=1
18:10:15,134 __main__ INFO [shutdown] runtime sqlite closed
18:10:15,377 __main__ INFO [shutdown] bye | elapsed_ms=770
```
Т.е. `Polling stopped` (aiogram) идёт **ДО** `bye` (за 0.75 с), `runtime sqlite closed` — последним closer'ом,
`bye | elapsed_ms=770` — финал; после `bye` процесс выходит сам (тишины до SIGKILL нет).
Итоговые счётчики по этому рестарту: **`B2_STOPSIGTERM=0`**, `B2_KILLING=0`,
`B2_LEFTOVER=0` (строки `SUMMARY_SHUTDOWN_SQLITE_LEFTOVER` НЕТ), `B2_POLL_STOPPED=2`, `B2_ERR=0`, `B2_CRIT=0`, `B2_TB=0`;
`systemctl`: active/running, `ExecMainStatus=0`, `NRestarts=0`, MainPID 2916763 (старт 18:10:18 UTC).
Т.е. graceful-последовательность уложилась в 0.77 с, процесс вышел САМ, SIGKILL/`stop-sigterm timed out` нет.

### Фантом и нетерминальные раны (после деплоя)
`nonterminal_count = 0`; `da33f05d…` = FAILED/`orphan_no_owner`, `publication_status=None`;
`[shutdown] startup recovery: нетерминальных Summary-ранов без живого владельца нет`.

## Плановый прогон 19:00 UTC (отложенная проверка владельца)

**Что было ДО деплоя.** На момент деплоя сервер `NOW_UTC=2026-10-16 18:08:33`, т.е. ожидаемый тик
**19:00 UTC ещё не наступал** (крон `0,6,12,18 Asia/Yekaterinburg` = 13:00/19:00/01:00/07:00 UTC).
В окне «от деплоя 2.58.82 до деплоя 2.58.83»: журнал 16.10 15:00→18:08 (6978 строк) содержит только
старты/стопы процессов-планировщиков (16:12:30 / 16:14:03 / 16:21:59) и одну строку Summary —
закрытие фантома `SUMMARY_ORPHAN_RUN_CLOSED | da33f05d… | age_s=11544 | reason=orphan_no_owner` (16:12:30);
в БД `runs_since_deploy` = только сам фантом (создан 13:00:06, закрыт 16:12:30), `SUMMARY_SOURCE_WINDOW`-событий нет.
**Т.е. ни одного нового планового прогона за это окно не было; ничего не «потерялось» — между 13:00 и 19:00 UTC тиков нет.**

**Что произошло ПОСЛЕ деплоя (тик 19:00 UTC уже на 2.58.83).**
```
19:00:05,141 services.summary_scheduler INFO summary: cron skip (disabled, source=chat) | chat_id=-1004482340693
19:00:05,183 services.summary_run_log INFO SUMMARY_START | run_id=73f16a62c1e247438aa5badf2b288ca9 | chat_id=-1002661910336 | mode=hybrid_l2 | manual=False
19:07:37,839 mca_events INFO SUMMARY_SOURCE_WINDOW | duration_ms=63 | usage_json={"input_count": 1016} | run_id=73f16a62…
19:07:38,043 mca_events INFO SUMMARY_SOURCE_WINDOW_READY | {"messages": 1016, "durable": true}
19:11:50,638 mca_events INFO SUMMARY_PUBLISH | outcome=start
19:13:03,839 summary_run_log INFO COVER_COMPLETE | status=ok | duration_ms=72145
19:16:06,554 mca_events INFO COVER_STYLE_SUCCEEDED | style_id=medved_press | duration_ms=182652
19:16:06,620 summary_run_log INFO PUBLISH_RICH_START | method=sendRichMessage
19:16:08,130 summary_run_log INFO PUBLISH_RICH_COMPLETE | message_id=1162997 | duration_ms=1510
19:16:08,155 mca_events INFO SUMMARY_PUBLISH | outcome=success | status=rich | duration_ms=257516 | message_id=1162997
19:16:08,164 summary_run_log INFO SUMMARY_COMPLETE | status=ok | duration_ms=962982 | cover_status=ok | publication_status=ok | health=degraded | fallback=legacy | coverage=0.0
19:16:08,167 mca_events INFO SUMMARY_RUN_DONE | status=degraded | duration_ms=962983 | {"publication": "rich", "message_id": 1162997, "fallback": "legacy"}
```
Стадии рана `73f16a62c1e247438aa5badf2b288ca9` (durable `summary_run_stages`):
`run_permit` ok/`immediate` (0 с) → `run_memory_maintenance` ok 452 с → `run_source_window` ok 0 с →
`l1` ok → `l2` **attempted_invalid** (`unknown_field`) → `final_policy` **LEGACY_FALLBACK** → `run` ok.
Терминал: `summary_runs.state=DEGRADED`, **`publication_status='published'`**; второй целевой чат
(`-1004482340693`) штатно пропущен как выключенный в своей конфигурации (`cron skip (disabled, source=chat)`).

**Ответы на вопросы владельца (прямо):**
1. Прогоны: один плановый ран — `73f16a62c1e247438aa5badf2b288ca9` (19:00:05 → 19:16:08 UTC, 963 с).
2. Стадии и `duration_ms`: см. выше; `SUMMARY_SOURCE_WINDOW duration_ms=63` (1016 сообщений, окно durable).
3. **Реальная публикация БЫЛА**: rich-сообщение `message_id=1162997` в чат `-1002661910336` (19:16:08 UTC).
4. Терминальное состояние: **DEGRADED** (health=degraded) с `publication_status='published'` — деградация
   предсуществующая и НЕ связана с инцидент-фиксом: Hybrid-L2 отвергнут валидатором
   (`SUMMARY_L2_STAGE status=attempted_invalid reason=unknown_field`, `L2_ERROR … LEVEL-3 legacy fallback`,
   `SUMMARY_LEGACY_FALLBACK fallback_engaged`), публикация ушла legacy-путём. Тот же профиль, что у 30 предыдущих
   DEGRADED-ранов; новый дефект не появился.
5. **Нетерминальных ранов 0**; фантом `da33f05d…` остаётся FAILED. Пропущенных тиков нет.

## Находки (честно)

1. **[Не блокер, предсуществующий]** `tests/test_webapp_ui_rework_round1020.py::TestLiquidGlass::test_modal_backdrop_blur_token`
   RED и на задеплоенном `7e9ce8cb`, и на кандидате; файл/ассеты в дельте релиза не менялись
   (`preexisting_red_pin.txt`). У соседней полосы — незакоммиченный re-pin (HOTFIX-TIERA). В дельту 2.58.83 не входит.
2. **[Инфо, исторический остаток]** Терминальное событие `SUMMARY_RUN_DONE` пишет только НОВЫЙ финализатор:
   у уже закрытого фантома `da33f05d…` в `mca_events` так и осталось одно `SUMMARY_RUN_START`, поэтому бейдж
   Oversight по ЭТОМУ рану может по-прежнему читаться «running», хотя durable-состояние FAILED. Исторический бэкфилл
   сознательно не делался (менял бы прошлые события) — задокументировано в residual-отчёте §4/§7. Для всех ранов,
   закрываемых начиная с 2.58.83, терминал пишется (проверено тестами №4/№5).
3. **[Инфо]** `reason_code` DONE-события (`orphan_no_owner`/`shutdown`) отбрасывается allowlist'ом `mca_events`
   — ровно как у штатного DONE-прогона; причина остаётся в durable `summary_run_stages`. Не регрессия.
4. **[Гигиена, чужая полоса]** В `evidence/incident-summary-01/` лежат untracked бинарные byproduct'ы проб
   (`probe_full_stack.db`, `.db-shm`, `.db-wal`) — я их сознательно НЕ коммитил (17 файлов коммита = только
   объявленные). Стоит убрать в scratch следующей полосе, которая владеет той папкой.
5. **[Coverage]** Гейт родительской карты RED (см. ниже) — не в скоупе изолированного релиза.

## Rollback (готовность; не потребовался)

```bash
ssh nik@198.46.175.136
cd /var/www/admin_bot
git checkout release/incident-2.58.82        # 7e9ce8cb = 2.58.82 (задеплоенный предшественник)
sudo systemctl restart admin_bot
curl -s http://127.0.0.1:8000/healthz        # ожидаем {"status":"ok","version":"2.58.82"}
```
Резерв: `git checkout --detach 7e9ce8cb93a05859c3c2feb9499ea838aca9cff1`. DDL-откат не нужен (DDL=0).
Мягкий откат фикса: `SUMMARY_PREGEN_BOUNDS_ENABLED=0` + рестарт (документированная парность;
снимает и orphan-recovery, и стартовый финализатор).

## Coverage-гейт

`requirements_gate check --map plans/features/asap8-v6-3-live-correction/requirements-map.json --stage release
--candidate 448cc81a --deployed-commit 448cc81a` → **FAIL (exit 1)** (`evidence/release-25883/gate-release-check.txt`):
карта привязана к кандидату `31c16555…` (волна SOUL-1/asap8-v6-3), записей инцидента INC-SUMMARY-01 в ней **0**;
карта НЕ правилась (DO_NOT_TOUCH, «зеленить» запрещено). Финальный re-capture — за parent/PM.

## master re-sync (версия 2.58.83 на master)

Локальный ref `master` на момент коммита = **`0a532f9e`** (residual-fix commit, parent `e4bb51d8`); origin/master
был `9d8aeaf9` (bump 2.58.82). Прямой FF/Push невозможен без искажения истории (ветки разошлись после `e4bb51d8`), а
двигать локальный ref в main worktree нельзя — там незакоммиченный WIP соседнего лейна (W10/SOUL-1),
включая файлы, которые задевает bump (например `tests/test_unified_image_request_round1026.py`).
Поэтому re-sync собран в отдельном worktree `OPENCODE_WORKFLOW_SCRATCH/inc83-master` на ветке
`inc83/master-resync` от `origin/master`:
- `2c1cca5d` = cherry-pick `0a532f9e` (residual fix; применился чисто),
- `998bf4e2` = cherry-pick `448cc81a` (bump 2.58.83; 31 файл, 33/33),
- `git merge-base --is-ancestor origin/master HEAD` → **FF-потомок** (push обычный, без force).

Проверки на re-sync: общие файлы (bot.py, summary_run_store, оба inc01-теста, settings, README, meta)
== релизной ветке **байт-в-байт**; `APP_VERSION = "2.58.83"`; 24 py-пина — **868 passed**; 4 JS-пина —
`HOTFIX7/8/9/10 … OK`; `gen_param_registry_round1025.py --check` → `CHECK OK: реестр 572 == REGISTRY…`.
Строки `2.58.82` остались ровно в 5 файлах — это исторические ссылки самого residual-фикса
(`bot.py`, `summary_run_store.py`, `test_summary_inc01_exit.py`, `_exit_diagnosis.txt`, shutdown-report), не пины.
Полное отличие re-sync от релизной ветки — только файлы SOUL-1 (мастер их несёт, изолированный релиз — нет).
Push: `git push origin inc83/master-resync:master` (FF `9d8aeaf9..998bf4e2`, без force) → **origin/master = `998bf4e2`**.
Детали и полный список отличий: `evidence/release-25883/master-resync.txt`.

**Важно (координация, для parent/Orchestrator):** пока шёл релиз, соседний лейн W10 закоммитил свою работу
в main worktree ПОВЕРХ моего residual-коммита: локальный `master` = **`c8cf77a5`** (W10) →
`0a532f9e` (мой residual) → `e4bb51d8`. Поэтому локальный `master` и `origin/master` **разошлись**
(`git rev-list --left-right --count master...origin/master` = `2 3`): на origin — cherry-picks `2c1cca5d`+`998bf4e2`,
локально — `0a532f9e`+`c8cf77a5`. Локальный ref я сознательно НЕ трогал (WIP/коммит соседа целы;
`git checkout HEAD --` по 31 файлу, как в прошлом релизе, уничтожил бы чужой WIP). W10-коммиту при push
потребуется обычный `fetch`+`rebase` (или merge) на `origin/master` — это работа соседнего лейна, не релиза.
В дельту 2.58.83 W10 не попал: на сервере `capability_registry.py` отсутствует (проверено при C2 и в пробе).

## Журнал после рестартов (ERROR/CRITICAL/Traceback)

Окно «после деплоя» (18:08→19:22 UTC, 3018 строк): ровно **одна** строка `ERROR` и ноль `CRITICAL`/`Traceback` —
и она принадлежит СТАРОМУ процессу 2.58.82 при его остановке:
`18:08:40,747 aiogram.dispatcher - ERROR - Failed to fetch updates - TelegramNetworkError: … ServerDisconnectedError`
(известный aiogram-cancel-шум при гашении long-poll, тот же класс, что фиксировал релиз 25882).
**Новый процесс 2916763 (с 18:10:18): `ERR=0`, `CRIT=0`, `TB=0`** — включая весь плановый прогон 19:00–19:16.
Честные WARNING'и прогона (не ошибки): `SUMMARY_L2_STAGE failed/attempted_invalid reason=unknown_field`,
`L2_ERROR … LEVEL-3 legacy fallback`, `LEGACY_FALLBACK reason=l2_unusable`,
`summary cover: draft without visual prompt — fallback path`, `[cover_style_edit] provider 400 … classified=prompt_limit`
(повтор после укорачивания промпта прошёл). Секреты не печатались (скрабятся в раннере/чекере).

## SSH-коннекты (дисциплина AGENTS.md)

**5 логинов**, все одиночные, успешные, с разносом (без серии и без ретраев после auth): (1) recon 18:07;
(2) прогон деплоя, прерванный на read-only предпроверке (баг форматирования в моём диагностическом SQL — прод не тронут,
мутаций не было, 18:08); (3) основной деплой с двумя рестартами (18:08–18:11); (4) follow-up read-only после
планового тика (19:22); (5) точечная проверка ERROR-строк по PID (19:22). Больше идеала «recon+main» — из-за
read-only доразведки; все коннекты чистые, пароли не печатались.

## Evidence

`plans/features/asap8-v6-3-live-correction/evidence/release-25883/`: `branch-log.txt`, `soul1-diff-empty.txt`,
`w10-diff-empty.txt`, `isolation-note.txt`, `bump_run.txt`, `hashes.txt`, `pytest_incident_files.txt`,
`pytest_regression_674.txt`, `pytest_source_pins.txt`, `preexisting_red_pin.txt`, `gen_registry_check.txt`,
`ev_recon.txt`, `ev_deploy_run.txt`, `ev_after_tick.txt`, `ev_errlines.txt`, `gate-release-check.txt`,
`master-resync.txt`.
Скрипты: `OPENCODE_WORKFLOW_SCRATCH/deploy25883/` (bump/hashes/deploy/verify_after_tick). Worktrees:
`OPENCODE_WORKFLOW_SCRATCH/incident-release-25883` (ветка), `inc83-tests` (detached тесты), `inc83-master` (master re-sync).
Серверные логи: `/tmp/deploy25883_boot1.log` (стоп старого 2.58.82), `/tmp/deploy25883_boot2.log` (graceful-стоп 2.58.83),
`/tmp/deploy25883_since.txt` (окно с 2.58.82), `/tmp/deploy25883_after.log` (окно после деплоя),
`/tmp/deploy25883_backup/` (untracked-конфликты, 0 шт. — backup пустой).
