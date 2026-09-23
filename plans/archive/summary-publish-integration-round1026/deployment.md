# deployment.md — S6 `summary-publish-integration-round1026` (T-3459, @DevOps — прод-поставка)

> **Feature:** `summary-publish-integration-round1026` (Эпик 2, §100–§106; ADR-1026-11 D1–D10) · **Дата:** 2026-09-24 · **Оператор:** @DevOps
> **Базис:** HEAD до деплоя **`197891f`** == `origin/master` (closing-docs S8); annotated-тег **`pre-round1026-s6`** (tag-obj **`6fd4a9d6`**) → **`197891f`**; релизные коммиты **`d0d634c`** (код+тесты) + **`cebd950`** (планы).
> **Окружение:** прод `/var/www/admin_bot` (`nik@198.46.175.136`), systemd-юнит `admin_bot`, venv Python 3.12 (`venv/bin/python`).
> **Решение ADR-1026-11 D9:** deploy = **ДА**, bump `APP_VERSION` 2.58.27 → **2.58.28**. Единый Reviewer gate — **Approved C0/H0** (отдельного Scanner-approval нет).

## Вердикт: **VERIFIED** ✅

Рантайм S6 доставлен на прод: fast-forward **`7c5338e..cebd950`**, сервис `active (running)` (MainPID **575712**, NRestarts **0**, ExecMainStatus **0**), `/api/health` = **200**, `/healthz` version = **2.58.28**, `/web/` cache-bust `?v=2.58.28` = **12** (placeholder `__APP_VERSION__` = **0**), `APP_VERSION` прод-venv = **2.58.28**, импорты изменённых модулей **OK** (включая no-loss guard `rich_document_limits` и §106-коды), `database is locked` = **0**, Traceback/ImportError/CRITICAL/ERROR после рестарта = **0**, `PUBLISH_*` = **0** (до первого реального прогона Саммари — ожидаемо, события аддитивны), бот и планировщик Саммари стартуют, **Δ DDL = 0**, §104-контур не тронут.

---

## 1. Коммиты и push

| Что | Commit | Сообщение | Файлов |
|---|---|---|---|
| Код + тесты + `config/settings.py` + `README.md` | **`d0d634c`** | `feat(round1026): S6 — интеграция публикации Саммари (§100–§105: единый rich/plain-путь, H1, no-loss fallback, §106-коды, PUBLISH_*) (APP_VERSION 2.58.28)` | 46 (+2505/−361) |
| Планы: feature-папка S6 + `audit_backlog` + `MEMORY`/meta/architecture/state | **`cebd950`** | `docs(plans): round1026 S6 — ревью-артефакты и аудит (единый Reviewer gate, binding 197891f)` | 10 (+881/−13) |
| deploy-doc (этот файл) | см. docs-коммит ниже | `plans/features/summary-publish-integration-round1026/deployment.md` | 1 |

- **Push:** `origin/master`, **без force** — **`197891f..cebd950`** (2026-09-24 09:28 +12 / 2026-09-23 **21:28 UTC**).
- **Иммутабельные артефакты (git-объекты):** tree `d0d634c` = **`da5a2de8484228b7e511978929d140912be4d3ae`**; tree `cebd950` = **`618ca43b16bb004ef03ba879e7e9f0ddf0bc7c92`**.
- `APP_VERSION`: **2.58.27 → 2.58.28** (bump в `config/settings.py`, cache-bust `?v=__APP_VERSION__`, README `v2.58.28`).
- `plans/current_task.md` и машинный блок `OPENCODE_WORKFLOW_STATE_V1` вручную не редактировались; amend/force не применялись.

## 2. Проверка привязок Reviewer (T-3454/T-3455) перед релизом

- **Reviewed-Commit `197891fdb643a914f771b818d9f84c385dc0706b`** — подтверждён: локальный HEAD до коммитов == `origin/master` == цель annotated-тега `pre-round1026-s6` (tag-obj `6fd4a9d6`, проверено `git cat-file`/`git rev-parse`).
- **Spec-Hash `77c1777558e5e842aa0bc01f84b21dd31deaa2fcbab51b2b5df06b47ea3bf11a`** — пересчитан байт-в-байт (SHA-256 `spec.md`) — **совпал**.
- **Working-Tree-Hash `4c7b2917205e14a682f495adfadb13bbfc1f949f8dc56deda1960b83c97f59c4`** — манифест воспроизведён **точно**: из заявленного в `review.md` diff-SHA `7096e17e…` + 6 per-file хэшей untracked-файлов повторно вычислен ровно `4c7b2917…` (структура рецепта подтверждена).
  - **Все 6 untracked-хэшей совпали байт-в-байт** с `review.md`: adr `026e883c…`, evidence `861cb4ec…`, spec `77c17775…`, tasks `2f5dfd3f…`, `tests/test_summary_publish_integration_round1026.py` `3808e324…`, `tests/js/round1026_s6_publish_test.js` `9e8c3b51…`.
  - **Все 16 хэшей product code/тестов/конфига из `evidence.md` §6 пересчитаны — MATCH** (formatter/generator/run_log/l2_writer/execution_graph_source/`web/app.js`/`execution_graph.js`/`analytics.py`/`settings.py`/`README.md`/тесты).
  - **Единственная дельта дерева от ревью-состояния** — служебный машинный блок `plans/workflow_state.md` (обновлён `workflow_checkpoint` @Orchestrator; mtime **09:22:17**, уже **после** финализации `review.md` в **09:21:28**). Поэтому текущая diff-компонента WTH (`git diff 197891f` = `2967f89d…`, полный WTH = `33093cf4…`) не совпадает с ревью-значением байт-в-байт — тот же принятый паттерн, что в S7/S8 (служебная запись после фиксации вердикта).
  - **Product code / тесты / конфиг / spec после ревью не менялись:** mtime всего кода/тестов/`config/settings.py`/`README.md` ≤ **09:02:19**, `audit_backlog.md` 09:20:34 (до хэширования), `review.md` 09:21:28; единственный файл новее — `plans/workflow_state.md` (машинный блок). Материального дрейфа нет → к деплою допущено.

## 3. Локальный CI перед коммитами (воспроизведено @DevOps)

| Проверка | Команда | Результат |
|---|---|---|
| Полный регресс pytest | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=120` | **9000 passed / 0 failed** (153.48 s, 1 warning) — совпадает с ревью (9000/0) |
| JS (все файлы) | `node tests/js/*.js` (47 файлов) | **OK=47 FAIL=0** — совпадает с ревью (47/47) |
| `git diff --check` | — | exit **0** |
| Каталог параметров | `tools/gen_param_registry_round1025.py --check` | **CHECK OK**: реестр 469 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны |
| Версия | импорт `config.settings` | `APP_VERSION` **2.58.28**; README `v2.58.28` |
| Секрет-скан релизного diff + untracked | regex `api_key/secret/password/bearer/private key/sk-…/bot-token` | diff: **0**; untracked: 4 совпадения — тест-константа `_SECRET_TEXT` в R17-тесте (проверяет, что текст **не** попадает в логи); реальных секретов нет. `.env`/`media/`/`deploy_commands.txt` в коммиты не входили (gitignored) |

## 4. Прод-деплой (traceable)

- **Сервер до деплоя:** HEAD `7c5338e`, `APP_VERSION` 2.58.27, `admin_bot` — `active`, MainPID **540872**; 13 pre-existing untracked `*.bak`-файлов (не наши, не тронуты; до/после — 13).
- **Pull:** `cd /var/www/admin_bot && git pull --ff-only origin master` → **`7c5338e..cebd950` Fast-forward** (65 файлов, +3622/−413; reflog: `cebd950 HEAD@{0}: pull --ff-only origin master: Fast-forward`). После pull HEAD = **`cebd950`** == `origin/master`.
- **Restart:** `sudo -n systemctl restart admin_bot` → exit **0**; сервис `active` с **2026-09-23 21:30:24 UTC** (стоп-фаза graceful ~60 с, как в S7/S8).
- **Состояние:** MainPID **575712**, NRestarts **0**, ExecMainStatus **0**, ActiveState `active`.

## 5. Health / смоук-проверки (факт)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active (running)** ✅ |
| `GET /api/health` (127.0.0.1:8000) | **HTTP 200** ✅ |
| `GET /healthz` | **HTTP 200** `{"status":"ok","version":"2.58.28"}` ✅ |
| served cache-bust `/web/` | `?v=2.58.28` — **12** вхождений; placeholder `__APP_VERSION__` = **0** ✅ |
| served `/web/static/execution_graph.js?v=2.58.28` | **HTTP 200** ✅ |
| `APP_VERSION` в venv прода | **2.58.28** ✅ |
| Импорт изменённых модулей (prod venv) | `services.summary_article_formatter`, `services.summary_generator` → **OK**; `rich_document_limits`/`chunk_plain_blocks`/`format_rich_html`/`document_from_plain_text` импортируются ✅ |
| Публикационный контур в артефакте | call-sites `log_publish_rich_start`/`log_publish_text_start` — по 2; константы `PUBLISH_RICH_START`/`PUBLISH_TEXT_START` — по 2; no-loss guard `rich_document_limits` в `_publish_rich_document` — **True**; §106-коды — **True** ✅ |
| `database is locked` (журнал с 21:30:00 UTC, 149 строк) | **0** ✅ |
| Traceback / ImportError (с рестарта) | **0** ✅ |
| ERROR / CRITICAL (с рестарта) | **0** ✅ |
| `PUBLISH_*` в логах | **0** ✅ — до следующего реального прогона Саммари; события §106/§109 **аддитивны** и появятся только при реальной публикации (это норма) |
| Старт бота | `Start polling` / `Run polling for bot` — 2 записи ✅ |
| Планировщики (Саммари/память/утро) | `scheduler started` / `SummarySchedulerService` / `initialized` — 23 записи ✅ |
| Миграции БД | не запускались; **Δ DDL=0** — `git diff --name-only 7c5338e..HEAD -- db` = **0**, `CREATE/ALTER TABLE/INDEX` в логах = **0** ✅ |

## 6. Инварианты

- **§104-контур не тронут:** `git diff --name-only 7c5338e..HEAD -- services/telegram_send.py services/image_generation.py services/summary_prompts.py services/summary_test_run.py web/api/routes.py db services/param_catalog.py bot.py` = **0**.
- **OFF-путь rich/plain:** живой публикационный путь не изменён в канале (reuse `sendRichMessage`; `telegram_send.py` вне diff); no-loss guard и §106-коды присутствуют в артефакте; `PUBLISH_*` эмитятся только при реальной публикации (сейчас 0).
- Δ DDL = 0, Δ каталога = 0 (F8 не переиздаётся), 0 новых внешних зависимостей, CSP/zero-build, 2-вызовность — без изменений.
- Pre-existing untracked `*.bak` на проде (13) не трогались.

## 7. Откат (готовность; не исполнялся)

- **Жёсткий:** `git revert d0d634c cebd950` (или `git checkout pre-round1026-s6`) + `sudo -n systemctl restart admin_bot`.
- **Тег:** annotated **`pre-round1026-s6`** → **`197891f`** (цель отката; `APP_VERSION` 2.58.27).
- **Бэкапы (R18, не удалялись):** `var/backups/s6-round1026-20260924-070835/` + `.env.bak.round1026-s6`; `stash@{0}` не тронут; история не перезаписывалась, force-push/amend не применялись.
- Откат **не потребовался** — деплой и верификация успешны.

## 8. Честные ограничения

1. **Live-приёмка владельца — PENDING OWNER VERIFICATION.** Реальная публикация Саммари в Telegram (rich с H1/обложкой, plain-фолбэк §105, §114-чек-лист) в этом gate не выполнялась; проверено на уровне артефакта/рантайма/логов (§5).
2. **`PUBLISH_*` = 0 сейчас — ожидаемо:** события появятся при следующем реальном прогоне Саммари (`PUBLISH_RICH_*`/`PUBLISH_TEXT_*`); аддитивность и R17-safe подтверждены ревью.
3. **Non-blocking техдолг (owned follow-up, не блокеры):** `L-R1026S6-D1` (Low — doc-drift spec §7/ARCHITECTURE §76.1: перенос rich-лимитов из форматтера в доставку; фикс на merge T-3457, @Architect), `L-R1026S6-D2` (Low — генерировать обложку после проверки `rich_document_limits`), Q1 (стриминг вне §105-контура, default OFF), Q2 (DB-сбои без §106-кода).
4. **WTH-дельта:** полный WTH рабочего дерева отличается от binding только служебным машинным блоком `plans/workflow_state.md` (см. §2, паттерн S7/S8); продуктовые артефакты совпадают с ревью байт-в-байт.
5. `evidence.md` намеренно **не изменялся** после ревью (сохранение байт-точности ревью-манифеста); деплой-факты зафиксированы здесь.

---

## Handoff

**RESULT: VERIFIED (T-3459) @Orchestrator** — коммиты **`d0d634c`** (код+тесты+`config/settings.py`+`README.md`, APP_VERSION 2.58.28) + **`cebd950`** (планы: ревью-артефакты + аудит) + deploy-doc (этот файл); push `origin/master` **`197891f..cebd950`** без force; прод `/var/www/admin_bot` fast-forward **`7c5338e..cebd950`** (2026-09-23 21:29 UTC); `systemctl restart` → **active** (MainPID **575712**, NRestarts 0, 21:30:24 UTC); `/api/health` **200**; `/healthz` **2.58.28**; `APP_VERSION` **2.58.28**; served `?v=2.58.28` (×12, placeholder 0); импорты изменённых модулей OK (no-loss guard + §106-коды в артефакте); `database is locked`=0; Traceback/ERROR/CRITICAL/ImportError=0 после рестарта; `PUBLISH_*`=0 (аддитивны, при реальном прогоне — норма); бот/планировщики стартуют; **Δ DDL=0**; §104-контур не тронут. Откат: `pre-round1026-s6`→`197891f` + `git revert d0d634c cebd950`; бэкапы/`stash@{0}` целы (R18). **Live-приёмка публикации — PENDING OWNER VERIFICATION.** Далее по процессу: @Orchestrator (reconciliation), merge T-3457, архив T-3458, @PM/@Memory, метрики, следующий F.
