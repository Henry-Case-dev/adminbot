# RELEASE-INC-25882 — изолированный релиз incident fix (2.58.82) на прод: отчёт

Дата: 2026-10-16 UTC (17.10 local). Лейн: RELEASE-INC-25882 (release engineer).
Владелец: prod-верификация следующего планового прогона + закрытие фантома; изолированные релизы одобрены.

## Вердикт (одной строкой)

**Кандидат `7e9ce8cb` (2.58.82) задеплоен и здоров; фантом `da33f05d…` ЗАКРЫТ (FAILED, 0 нетерминальных);
graceful-дренаж Summary работает. НО обязательный live-чек «нет `stop-sigterm timed out`» НЕ выполнен:
процесс зависает ПОСЛЕ `bye` и всё равно получает SIGKILL через 60 с (n=2, воспроизведено в steady-state).
Итог: FAILED по одному обязательному пункту; откат НЕ выполнялся (не оправдан — текущее состояние строго лучше),
остаток → Builder→Reviewer.**

## Deploy binding

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | локальный репо `C:\Code\Python\adminbot`, ветка `release/incident-2.58.82`, релизный коммит `7e9ce8cb93a05859c3c2feb9499ea838aca9cff1` |
| База ветки | **`6d4b9a7d`** (задеплоенный 2.58.81) — выбрана вместо `4bdaa0a0`: изоляционный лог `6d4b9a7d..ветка` = ровно cherry-pick + bump; дельта деплоя = только инцидент-фикс |
| Состав | `6d4b9a7d` + cherry-pick `e4bb51d8` (применился ЧИСТО; авто-merge только в `services/summary_generator.py`, хунки не пересекаются) = `7ab0ef53` + bump = `7e9ce8cb` |
| Push | `git push -u origin release/incident-2.58.82` (обычный, без force); origin = `7e9ce8cb` |
| Сервер | fetch + `git checkout -B release/incident-2.58.82 origin/release/incident-2.58.82`; HEAD сервера = `7e9ce8cb` (tracking), TRACKED_MOD=0, COMMITS_ON_BRANCH=2 |
| MUTABLE_WORKTREE_REQUIRED | **no** — деплой из immutable закоммиченного дерева; main worktree и WIP соседних лейнов не тронуты |
| DDL / миграции | ΔDDL = 0 |
| Версии | 2.58.81 → **2.58.82** (31 файл, 33 ins/33 del: settings + README + F8-meta (HEAD `7ab0ef53`) + 24 py + 4 JS) |

## Изоляция SOUL-1 (проверено)

1. `git log --oneline 6d4b9a7d..release/incident-2.58.82` = **ровно 2 коммита**: `7e9ce8cb` (bump), `7ab0ef53` (cherry-pick).
2. Diff по SOUL-1 файлам (`services/prompt_registry.py|prompt_factory.py|prompt_composer.py|style_policy.py|chat_prompts.py|response_extent.py|direct_l1.py`) = **пуст** (0 байт, `soul1-diff-empty.txt`).
3. Дельта ветки vs deployed = **57 файлов** = 26 инцидент + 31 bump (`delta-vs-deployed.txt`); ничего иного.
4. Инцидент-код на ветке vs master `e4bb51d8` — **байт-в-байт**, кроме двух SOUL-1-хунков `resolve_prompt` в `summary_generator.py` (они — master-only, на ветке их нет по построению; `incident-code-identical-to-master.txt`). `bot.py` = `aeca676e…` (хэш из review).
5. На сервере: W1 (`prompt_registry.py`/`prompt_factory.py`) и W3 (`style_policy.py`) — отсутствуют; стекло цело (scale=32, lg-lens-map, стенд 404); `param_catalog.py` == deployed.

## Фокусные проверки ветки (worktree `OPENCODE_WORKFLOW_SCRATCH/incident-release-25882`, main worktree не тронут)

| Проверка | Результат |
|---|---|
| `pytest tests/test_summary_inc01_pregen_bounds.py tests/test_summary_inc01_shutdown.py` | **27 passed** (13+14) |
| Регресс-поверхность §5 (22 сьюта) | **674 passed** |
| Source-пины `bot.py` (76 файлов: t5150*, menu, permsoc, webapp_*, mca10c/11/17a/19, graphrag_memory, summary_deploy/publish, asap8_f5, betterstack, log_ring, smoke1016) | **1874 passed / 1 failed** — `test_modal_backdrop_blur_token` RED; **предсуществующий**: воспроизведён на чистом `6d4b9a7d` (отдельный worktree), файл+CSS на ветке == master; у соседнего лейна уже есть незакоммиченный re-pin (HOTFIX-TIERA, приказ владельца); вне дельты релиза |
| `tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 572 == REGISTRY…` (до и после bump) |
| После bump: 24 py-пина (полигон 2) | **868 passed** |
| После bump: node hotfix7–10 | **4/4 OK** |

## Прод-верификация (всё с сервера)

### Сервис и артефакты
- `active/running`, ExecMainStatus=0; healthz loopback и 443: `{"status":"ok","version":"2.58.82"}`.
- 14 raw-файлов на сервере == байтам релизного коммита (вкл. все 7 инцидент-файлов + 2 инцидент-теста).
- Отдача: `/web/` sha == ожидаемым substituted-байтам (`ea59ab75…`, 2.58.82×14, 2.58.81×0); `/static/app.css` substituted `ea481612…`; `/web/static/app.css` raw `c28d…`; `/web/app.js` (корректный путь) raw `828d…` 200; стенд 6 путей 404; живые ассеты 200. `/web/static/app.js`=404 — **известный wrong-path артефакт чек-скрипта** (тот же 404 был у 2.58.81; реальный путь `/web/app.js`).
- Runtime-проба: version=2.58.82; W1/W3 отсутствуют; каталог-ключ есть; `lxml_html_clean`/`trafilatura` ok; `pregen_bounds_enabled=True`; `run_durable_enabled=True`; `orphan_grace=30.0`; `stale_run_seconds=900`; `handle_signals=False` в `bot.py`; `_recover_orphan_summary_runs` присутствует.

### Фантом `da33f05db7754a38bdea7d591cf6eccc` — ЗАКРЫТ
Журнал (старт 2.58.82, 16:12:30 UTC):
```
SUMMARY_ORPHAN_RUN_CLOSED | run_id=da33f05db7754a38bdea7d591cf6eccc | chat_id=-1002661910336 | state=CREATED | age_s=11544 | closed=True | reason=orphan_no_owner — нетерминальный ран без живого владельца закрыт FAILED (публикация не трогалась)
[shutdown] startup recovery: закрыто 1 нетерминальных Summary-ранов без живого владельца | run_ids=['da33f05db7754a38bdea7d591cf6eccc']
```
БД (read-only SQLite, после 3 рестартов):
```
phantom_row: ('da33f05db7754a38bdea7d591cf6eccc', -1002661910336, 'FAILED', 0, None, None, None, 1792155606, 1792167150)
phantom_stages: (373, 'run', 'failed', 'orphan_no_owner', 1792167150, 1792167150)
nonterminal_count: (0,)   nonterminal_rows: []   states: DEGRADED 30 / DONE 21 / FAILED 1
```
`publication_status` не трогался (None). Нетерминальных Summary-ранов — **0** (перепроверено после рестартов №2 и №3).

### Graceful stop — фазы есть, но процесс НЕ выходит (обязательный чек НЕ выполнен)
Рестарт №2 (16:12:44) и №3 (16:20:39, steady-state) дают одинаковую картину:
```
[shutdown] summary: stopped accepting new work | phase=stopping (scheduler down, new runs refused)
SUMMARY_SHUTDOWN_DRAIN | phase=draining | in_flight=0 | cancelled=0 | timeout_s=20.0
SUMMARY_SHUTDOWN_DRAIN | phase=finalized | finalized=0 | left=0 | elapsed_ms=1
[shutdown] summary drain done | in_flight=0 | cancelled=0 | finalized=0 | left=0 | elapsed_ms=2
[shutdown] bye | elapsed_ms=523
[betterstack] shutdown flush
… тишина …
State 'stop-sigterm' timed out. Killing. → SIGKILL (ровно +60 с) → Failed with result 'timeout'
```
- `signals=(2, 15)` + `signal handlers installed` — есть (при старте).
- **НО `stop-sigterm timed out` присутствует на КАЖДОМ рестарте**: №1 (старый код, неустранимо — фикс не может примениться задним числом), №2 16:13:44, №3 16:21:39 — SIGKILL через 60 с.
- Механика (n=2): graceful-последовательность отрабатывает за ~0.5 с; зависание — ПОСЛЕ `bye`/`[betterstack] shutdown flush` (последняя поздняя строка `Polling stopped…` +0.36 с; далее тишина до SIGKILL). Демо полосы (`_shutdown_sigterm_demo.py`) этот участок не покрывал: `on_startup`/polling там замоканы, стек betterstack/apscheduler/aiohttp/PG не поднимался.
- Влияние: фантом НЕ создаётся (дренаж успевает; orphan-recovery закрывает остатки — доказано 0 нетерминальных); но рестарт = 60 с downtime + `Failed with result 'timeout'`. Неотслеженные гипотезы (для Builder): финальный флаш BetterStack (timeout 10 с/батч, DNS не покрыт таймаутом) / teardown `asyncio.run` (join default-executor; aiohttp ThreadedResolver / `asyncio.to_thread`).
- Журнал после рестарта №1 (deploy): `ERR=0 CRIT=0 TRACEBACK=0 database-locked=0` (222 строки). У контролируемых рестартов №2/№3 — по 1 ERROR: aiogram-cancel-шум при остановке (`Failed to fetch updates - TelegramNetworkError … ServerDisconnectedError`); CRITICAL/Traceback=0.

### Следующий плановый прогон
`SmartModule scheduler started (cron 0,6,12,18 Asia/Yekaterinburg)`; сейчас 16:25 UTC.
**Следующий тик: 2026-10-16 19:00 UTC = 17.10 00:00 YEKT = 17.10 07:00 UTC+12 (local владельца).**
Follow-up (ОДНА поздняя коннекция, read-only): журнал 19:00–19:30 + `summary_runs`/`summary_run_stages` нового рана — ожидаемо: НОВЫЙ run_id у чата `-1002661910336` (orphan закрыт, resume не будет), stage-строки `run_permit`/`run_memory_maintenance`/`run_source_window`, `duration_ms` в `SUMMARY_SOURCE_WINDOW`, терминал DONE/DEGRADED, нетерминальных 0.

## Находки

1. **[Материальная, обязательный чек §9.1] Процесс не выходит после graceful-последовательности** → `stop-sigterm timed out` + SIGKILL (n=2). НЕ блокирует ценность инцидент-фикса (фантомов нет), но нарушает обещанный «грациозный stop» и добавляет 60 с к каждому рестарту. Роут: Builder→Reviewer (bounded exit после flush; локализовать зависание faulthandler/py-spy или локальным репро полного стека). Откат не требуется.
2. **[Предсуществующая, тест-онли]** `test_webapp_ui_rework_round1020.py::test_modal_backdrop_blur_token` RED на `6d4b9a7d` и на master; соседний лейн уже готовит re-pin (незакоммичен). В дельту релиза не входит.
3. **[Инфо, UI-нюанс]** Oversight `/runs` деривит бейдж из `mca_events`; orphan-close пишет только `summary_runs`+stages → у `da33f05d…` в mca_events остался один `SUMMARY_RUN_START` без терминала, бейдж может читаться «running», хотя durable-состояние FAILED. Контракт полосы (review §9) — DB-уровень; флаг для parent/Reviewer, если приёмка владельца включает бейдж Oversight.
4. **[Инфо]** Чек `/web/static/app.js` в deploy-скрипте — wrong-path артефакт (тот же 404 у 2.58.81); корректный путь `/web/app.js` проверен отдельно (200, raw sha).

## Coverage-гейт

`requirements_gate check --stage release --candidate 7e9ce8cb --deployed-commit 7e9ce8cb` → **FAIL (exit 1)**:
карта `asap8-v6-3-live-correction` не пересобрана под INC-SUMMARY-01 (в ней нет записей инцидента — review §10).
Карта НЕ правилась (DO_NOT_TOUCH; «зеленить» запрещено). Финальный re-capture — за parent/PM.

## Rollback (готовность; не потребовался)

```bash
ssh nik@198.46.175.136
cd /var/www/admin_bot
git checkout release/glass-2.58.81          # 6d4b9a7d = 2.58.81 (локальная ветка, ancestor)
sudo systemctl restart admin_bot
curl -s http://127.0.0.1:8000/healthz       # ожидаем {"status":"ok","version":"2.58.81"}
```
Резерв: `git checkout --detach 6d4b9a7d645dcd0e7bd6c63b1e3ce2d367b58221`. DDL-откат не нужен (DDL=0).
Мягкий откат фикса: `SUMMARY_PREGEN_BOUNDS_ENABLED=0` + рестарт (документированная парность; снимает и orphan-recovery).

## master re-sync

Cherry-pick bump-коммита на master → `9d8aeaf9` (31 файл, 33/33; 52 passed + CHECK OK); push `2e5aac1a..9d8aeaf9` (FF, без force) → **origin/master = `9d8aeaf9` (2.58.82)**.
**Отклонение (осознанное):** локальный ref `master` НЕ переведён (оставлен `e4bb51d8`), main worktree не тронут — в нём WIP соседнего лейна в `tests/test_unified_image_request_round1026.py`, который ЯВЛЯЕТСЯ одним из 31 версионного пина; операция прошлого лейна (`checkout HEAD -- 31 файлов`) уничтожила бы WIP. Push-only. Детали: `master-sync.txt`.

## SSH-коннекты (дисциплина AGENTS.md)

**7 логинов**, все одиночные, успешные, с разносом (минуты), без ретраев после auth: (1) recon; (2) основной деплой;
(3) verify (добивка после wrong-path-abort); (4) restart-probe №3 (ожидание sudo-промпта истекло — sudo-таймстамп закэширован, рестарт уже выполнялся); (5) status-check (PowerShell-манга `$(...)` — только чтение); (6) post-restart#3 check; (7) мини-fetch ERR-строк. Больше соединений, чем идеал «recon+main», — из-за аномалий (wrong-path abort и расследование зависания); все чистые.

## Evidence

`plans/features/asap8-v6-3-live-correction/evidence/release-25882/`: `branch-log.txt`, `soul1-diff-empty.txt`,
`delta-vs-deployed.txt`, `isolation-vs-master.txt`, `incident-code-identical-to-master.txt`, `pytest_incident_files.txt`,
`pytest_regression_674.txt`, `pytest_source_pins.txt`, `pytest_pin_failure_detail.txt`, `pytest_pin_failure_at_deployed_base.txt`,
`gen_registry_check_prebump.txt`, `gen_registry_check_after_bump.txt`, `bump_run.txt`, `pytest_pins_after_bump.txt`,
`node_hotfix7_10_after_bump.txt`, `ev_recon.txt`, `ev_deploy_run.txt`, `ev_verify_run.txt`, `ev_restart3_probe.txt`,
`ev_status_check1.txt`, `ev_restart3_check.txt`, `ev_boot3_err_lines.txt`, `master-sync.txt`, `gate-release-check.txt`.
Скрипты: `OPENCODE_WORKFLOW_SCRATCH/deploy25882/` (bump/deploy/verify/restart-probe/fetch). Worktree ветки: `OPENCODE_WORKFLOW_SCRATCH/incident-release-25882`.
Серверные логи: `/tmp/deploy25882_boot1.log`, `boot2.log`, `boot3.log`, `/tmp/deploy25882_backup/`.
