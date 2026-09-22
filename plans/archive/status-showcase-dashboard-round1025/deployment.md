# deployment.md — F11 `status-showcase-dashboard-round1025`

> **Статус:** **`VERIFIED`** (Шаг 9 / T-3096 [@DevOps]).
> **Предусловия:** @Reviewer **Approved** (итер. 2, T-3091; H-F11S-1 «счётчики логов 0/1» закрыт — `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 → «к деплою ДА»** (итер. 2, T-3092; `plans/reports/round1025_f11_scanner_audit.md`); Merge — `plans/ARCHITECTURE.md` **§69** (@Architect); архивация — `plans/archive/status-showcase-dashboard-round1025/` (@PM). Точка отката — тег **`pre-round1025-f11`** → **`25cc19c`**.
> **Дата деплоя:** WC — 23.09.2026 (Wed); UTC-факт (clock сервера) — **Tue 2026-09-22 20:56:02Z → 20:58:20Z**. Рестарт `admin_bot` — **20:57:13Z**; health-подтверждение 200 — **20:57:35Z** (после поднятия uvicorn). Расхождение дат ~1 сутки, clock WC (`Wed 2026-09-23`) vs clock прод-VPS (`Tue 2026-09-22`) — ожидаемо для этой площадки.

## Окружение

- Прод-VPS `racknerd-f4e3456` (`198.46.175.136`), каталог `/var/www/admin_bot`; webapp `https://admin-bot.duckdns.org/web/`.
- systemd-юнит `admin_bot` (`Restart=always`), API на `127.0.0.1:8000`.
- Доступ @DevOps: SSH-ключ (`nik@198.46.175.136`); `sudo -n /usr/bin/systemctl restart admin_bot` — NOPASSWD, выполнено без запроса пароля (exit 0). `journalctl` доступен без sudo (группа `systemd-journal`).

## Верифицированные артефакты

| Артефакт | Значение |
|---|---|
| Коммит код/тесты | **`f3e9195`** (`f3e9195f9fc9260a5ee10b3dea8f5cb485f62c4c`) — `feat(round1025): F11 — витрина Статуса (12-кол. сетка, Hero/метрики, виджет сна, расширенный граф + #/status/graph, Новые факты/бюджеты, счётчики логов counts, APP_VERSION 2.58.17)` (**30 файлов, +1719/−119**; `web/index.html`, `web/app.js`, `web/static/app.css`, `web/api/routes.py`, `services/log_ring.py`, `config/settings.py`, `.env.example`, `README.md`, `tools/ui_round1025_matrix.py`, F11-тесты + маркер-правки) |
| Коммит планы | **`e7170b7`** (`e7170b7f1e4e2368efd27c3352899dd590d62ddb`) — `docs(plans): round1025 F11 — Merge §69 + архивация + Scanner-аудит` (**16 файлов, +812/−32**; §69, MEMORY, backlog, workflow_state, reports, архив `plans/archive/status-showcase-dashboard-round1025/`, перенос `plans/features/…/tasks.md`) |
| Коммит деплой-отчёт | `docs(deploy): round1025 F11 — прод-деплой VERIFIED (APP_VERSION 2.58.17) + deployment.md` (после этого отчёта) |
| Push | `origin/master`: `25cc19c..e7170b7` (exit 0, без force); `git ls-remote` = `e7170b7`; тег `pre-round1025-f11` на origin = `3a5b67b` (аннотир. объект) → commit `25cc19c` |
| Pre-state прод | `c610c5f` (F9-docs), `APP_VERSION` 2.58.16, `admin_bot` **active** (`MainPID 254733`), tracked-dirty = 0 |
| Fast-forward прод | `git fetch origin --tags` (RC 0) → `git pull --ff-only origin master` **Fast-forward** `c610c5f..e7170b7` (`PULL_RC=0`), POST_HEAD=`e7170b7`, POST_DIRTY=0 |
| `APP_VERSION` (прод) | 2.58.16 → **2.58.17** (`config/settings.py:1756`) |
| Точка отката | тег `pre-round1025-f11` = **`25cc19c61ef4b02e887c04ecbffea21e7dc9b46b`** (`25cc19c`; локально **и** на проде, `pre-round1025-f11^{commit}`) |

> Примечание по ff: прод стоял на `c610c5f` (F9 Merge-docs), т.к. финальная F9-синхронизация (`49c1ae1`/`25cc19c`) и F11 одним Fast-forward пришли сразу; `--ff-only` не потребовал merge/rebase.

## Верификация (факт)

| Проверка | Результат |
|---|---|
| `sudo -n systemctl restart admin_bot` | exit 0 |
| `systemctl is-active admin_bot` | **active** |
| `ActiveState`/`SubState`/`MainPID`/`NRestarts`/`ActiveEnterTimestamp` | `active`/`running`/`280171`/`0`/`Tue 2026-09-22 20:57:13 UTC` |
| `GET http://127.0.0.1:8000/api/health` | **HTTP 200** |
| `GET /healthz` | **200**, тело `{"status":"ok","version":"2.58.17"}` |
| `APP_VERSION` на проде | **2.58.17** (`config/settings.py:1756`) |
| `GET https://admin-bot.duckdns.org/web/` | **200** |
| served `?v` | `?v=2.58.17` — **10** вхождений в HTML; stale `v=2.58.16` = **0** |
| `/web/app.js?v=2.58.17` / `/web/static/app.css?v=2.58.17` | **200** / **200** |
| `database is locked` (окно ~15 мин, `journalctl`) | **0** |
| `Traceback` / `ERROR` / `CRITICAL` (окно ~15 мин) | **0** |
| Логи старта | `Bot started, listening for messages...`; `[webapp] lifespan started \| pg_available=True`; `Start polling`; `Run polling for bot @PERMsoc_bot id=8802473181`; `Started`+`Stopped` = 2 |

> **Прозрачность старта:** первый же health-опрос сразу после рестарта (через ~4 с) отдал `000` на `127.0.0.1:8000` и `502` на `/web/` — uvicorn ещё не поднял сокет (~20:57:1xZ). К `20:57:35Z` (`lifespan started`) `/api/health` = **200**, `/healthz` = 2.58.17; это нормальное окно прогрева, не инцидент.

## Инварианты: Δ DDL и Δ каталога

- **Δ DDL = 0**: `migrations`/`alembic`/`models`/`*.sql` вне диффа `25cc19c..e7170b7`; новых endpoint/полей БД нет; живой SQLite `user_version` не менялся. Откат по БД не требуется.
- **Δ каталога = 0**: `services/param_catalog.py` **не тронут** (459/418/434/98/96/21 без изменений); флаг `UI_STATUS_GRID_V2` — env-only kill-switch, в `param_catalog` **не входит**.
- **CSP / zero-build**: правки только `web/app.js`/`web/index.html`/`web/static/app.css`; kill-switch доставляется во фронт через `GET /api/me.ui_flags` (наружу только bool); cache-bust `?v=__APP_VERSION__` → `?v=2.58.17`; без CDN/inline/`eval`/новых библиотек.
- Progressive delivery (10/50/100 %) не применяется (как и в §53–§69): затвор — bump `APP_VERSION` + cache-bust.

## R18 / гигиена

- Тег `pre-round1025-f11` = `25cc19c` — **цел** (локально и на проде).
- `stash@{0}` — **цел**: прод `pre-10.15-deploy info_text.md drift`.
- Бэкапы **не трогались**: `./backups` (6 записей) — read-only проверка; `var/backups` не читался/не изменялся.
- `plans/current_task.md` и `deploy_commands.txt` — **не изменялись/не коммитились**; force-push — не применялся; в индекс не попали `.env*`, zip, скриншоты, `tools/_ui_*`, `var/backups`.
- Локальная валидация перед деплоем: `node tests/js/*.js` — **42/42 PASS, 0 fail** (в т.ч. `F11-STATUS-GRID-OK`, `F11-HEARTBEAT-OK`, `F11-LOG-COUNTS-OK`); `git diff --check` — OK.

## Откат (готовность подтверждена, не выполнялся)

- **Hard rollback:** `cd /var/www/admin_bot && git checkout pre-round1025-f11` (= `25cc19c`) `+ sudo -n /usr/bin/systemctl restart admin_bot` (либо `git revert f3e9195 e7170b7` + restart).
- **Soft rollback (область «Статус» без редеплоя):** `UI_STATUS_GRID_V2=false` в `.env` + `restart` → одноколоночный безопасный режим `.status-grid--legacy`. Это **НЕ byte-identical legacy-DOM** (осознанное решение, M-F11S-1): Hero/метрики, сон, факты, бюджеты, счётчики остаются, но в одну колонку. Полный откат — git-тег/реверт.
- Δ DDL = 0 → миграционный откат не нужен. Тег/бэкапы/`stash@{0}` не удалять (R18).

## Явные ограничения (важно)

- **HTTP 200 / health / served `?v` ≠ корректный layout.** Верифицирован **деплой-гейт** (ff-pull, рестарт, health, версия, served `?v`, `database is locked`=0, отсутствие ошибок старта), а **не** визуальная корректность и не сохранность виджетов.
- **Живой TMA/WebView (§70/§77):** 12-колоночная сетка §12, Hero/метрики §13/§14, виджет сна §17, расширенный граф §16 + маршрут `#/status/graph`, «Новые факты»/«бюджеты» §19, счётчики логов §20 — поведение в реальном Telegram WebView (Android/iOS), touch/скролл/адаптив headless-инструментами **не проверялись** → **PENDING OWNER VERIFICATION (T-3097)**. Workflow не останавливается (UPD §8).

## Handoff

**RESULT: DEPLOYED — VERIFIED.** F11 `status-showcase-dashboard-round1025` выведена на прод: коммиты `f3e9195` (код+тесты, 30 файлов) → `e7170b7` (планы, 16 файлов), push `25cc19c..e7170b7` (без force); прод Fast-forward `c610c5f..e7170b7`, `admin_bot` **active** (`MainPID 280171`, `NRestarts 0`), `/api/health` **200**, `/healthz`/`APP_VERSION` = **2.58.17**, served `?v=2.58.17` (10 вхождений, stale 0), `/web/app.js`/`/web/static/app.css` — 200, `database is locked`=0, Traceback/ERROR/CRITICAL=0, `pg_available=True`, polling `@PERMsoc_bot`. Δ DDL=0, Δ каталога=0. Откат — тег `pre-round1025-f11` (=`25cc19c`) и/или soft-флаг `UI_STATUS_GRID_V2=false`. Живой гейт **PENDING OWNER VERIFICATION (T-3097: TMA/WebView — сетка/Hero/сон/граф/факты/счётчики; HTTP 200 ≠ корректный layout)**. Следующие: @Orchestrator — @Architect reconciliation (§69), @PM archive-close, @Memory metrics/KG (Шаг 10); далее — F10 `epic1-verification-round1025`.
