# deployment.md — F9 `secrets-and-save-states-round1025`

> **Статус:** **`VERIFIED`** (Step 9 / T-3058 [@DevOps]).
> **Предусловия:** @Reviewer **Approved** (итер. 2, T-3054; H-F9S-1 + L-F9S-1..4 закрыты — `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 / Info 2 → «к деплою ДА»** (`plans/reports/round1025_f9_scanner_audit.md`); Merge — `plans/ARCHITECTURE.md` **§68** (@Architect, T-3056); архивация — `plans/archive/secrets-and-save-states-round1025/` (@PM, T-3057). Точка отката — тег `pre-round1025-f9` → `93432c0`.
> **Дата деплоя:** WC — 23.09.2026 (Wed); UTC-факт (clock сервера) — **Tue 2026-09-22 18:48:41 → 18:50:03Z**. Рестарт `admin_bot` — `18:49:41Z`; `Start polling` — `18:50:03Z`; health-подтверждение — `~18:49:5xZ` (200 в первом же опросе после старта). Расхождение дат: ~1 сутки, clock WC (`Wed 2026-09-23`) vs clock прод-VPS (`Tue 2026-09-22`) — ожидаемо для этой площадки.

## Окружение

- Прод-VPS `racknerd-f4e3456` (`198.46.175.136`), каталог `/var/www/admin_bot`; webapp `https://admin-bot.duckdns.org/web/`.
- systemd-юнит `admin_bot` (`Restart=always`), API на `127.0.0.1:8000`.
- Доступ @DevOps: SSH-ключ (`nik@198.46.175.136`); `sudo -n /usr/bin/systemctl restart admin_bot` — NOPASSWD, выполнено без запроса пароля (exit 0).

## Верифицированные артефакты

| Артефакт | Значение |
|---|---|
| Коммит код/тесты | **`f5fbd5f`** (`f5fbd5f5d4a4f6e8fbd19f4e8a36c51faf189452`) — `feat(round1025): F9 — единый secret-field (маска-индикатор, «Ключ установлен», Заменить/Удалить без нового API), SaveBar-добор (клавиатура/safe-area), §51-ui, APP_VERSION 2.58.16` (**31 файл, +1315/−198**; `web/app.js`, `web/index.html`, `web/static/app.css`, `config/settings.py`, `README.md`, F9-тесты + маркер-правки) |
| Коммит планы | **`c610c5f`** (`c610c5f340f47b26faa705b25515b38a37b6fba9`) — `docs(plans): round1025 F9 — Merge §68 + архивация + Scanner-аудит` (**15 файлов**; §68, MEMORY, backlog, workflow_state, reports, архив `plans/archive/secrets-and-save-states-round1025/`, перенос `plans/features/…/tasks.md`) |
| Коммит деплой-отчёт | `docs(deploy): round1025 F9 — прод-деплой VERIFIED (APP_VERSION 2.58.16) + deployment.md` (после этого отчёта) |
| Push | `origin/master`: `93432c0..c610c5f` (exit 0, без force); `git ls-remote` = `c610c5f` |
| Pre-state прод | `908f471` (F7-docs), `APP_VERSION` 2.58.15, `admin_bot` **active**, tracked-dirty = 0 |
| Fast-forward прод | `git fetch origin --tags` (RC 0) → `git pull --ff-only origin master` **Fast-forward** `908f471..c610c5f` (`PULL_RC=0`), POST_HEAD=`c610c5f`, POST_DIRTY=0 |
| `APP_VERSION` (прод) | 2.58.15 → **2.58.16** (`config/settings.py:1748`) |
| Точка отката | тег `pre-round1025-f9` = **`93432c04d0ed706a12b9ef56fe3e0cae0307d4dc`** (`93432c0`; локально **и** на проде) |

> Примечание по ff: прод стоял на `908f471` (последний docs-коммит F7), т.к. **F8 deploy = NOT_APPLICABLE** и прод не подтягивал F8-документацию; ff-пул `908f471..c610c5f` принёс F8-доки + F9-код/доки одним Fast-forward. `--ff-only` не потребовал merge/rebase.

## Верификация (факт)

| Проверка | Результат |
|---|---|
| `sudo -n systemctl restart admin_bot` | exit 0 |
| `systemctl is-active admin_bot` | **active** |
| `ActiveState`/`SubState`/`MainPID`/`NRestarts`/`ActiveEnterTimestamp` | `active`/`running`/`254733`/`0`/`Tue 2026-09-22 18:49:41 UTC` |
| `GET http://127.0.0.1:8000/api/health` | **HTTP 200** `{"status":"ok"}` |
| `GET /healthz` | **200**, тело `{"status":"ok","version":"2.58.16"}` |
| `APP_VERSION` на проде | **2.58.16** (`config/settings.py:1748`) |
| `GET https://admin-bot.duckdns.org/web/` / `/web/index.html` | **200** / **200** |
| served `?v` | `?v=2.58.16` — **10** вхождений в HTML; stale `v=2.58.15` = **0** |
| `/web/app.js?v=2.58.16` / `/web/static/app.css?v=2.58.16` | **200** / **200** |
| `GET /api/status` | `{"detail":"missing init data"}` (TMA-auth активен, ожидаемо) |
| `database is locked` (окно ~15 мин, `journalctl`) | **0** |
| `Traceback` / `ERROR|CRITICAL` (окно ~15 мин) | **0 / 0** |
| Логи старта | `Bot started, listening for messages...`; `[webapp] lifespan started \| pg_available=True`; `Start polling`; `Run polling for bot @PERMsoc_bot id=8802473181` |

## Инварианты: Δ DDL и Δ каталога

- **Δ DDL = 0**: `migrations`/`alembic`/`migrate_history` и `web/api/**` вне диффа `93432c0..c610c5f`; новых endpoint/полей БД нет; живой SQLite `user_version` не менялся. Откат по БД не требуется.
- **Δ каталога = 0**: `services/param_catalog.py` не тронут (Δ каталога=0/Δ DDL=0); секреты (28) — перегруппировка/UI (20 UI + 8 env-only), не новые Spec.
- **CSP / zero-build**: правки только `web/app.js`/`web/index.html`/`web/static/app.css`; `secret-field` — x-template, без CDN/inline/`eval`/новых библиотек; cache-bust `?v=__APP_VERSION__` → `?v=2.58.16`.
- Progressive delivery (10/50/100 %) не применяется (как и в §53–§67): затвор — bump `APP_VERSION` + cache-bust.

## R18 / гигиена

- Тег `pre-round1025-f9` = `93432c0` — **цел** (локально и на проде).
- `stash@{0}` — **цел**: прод `pre-10.15-deploy info_text.md drift`; рабочая копия `wip(f1): IA v2 round1025 …` (pre-existing).
- Бэкапы **не трогались**: `./backups` (4 записи), `var/backups` (root-owned, для `nik` пуст/недоступен) — read-only проверка.
- `plans/current_task.md` и `deploy_commands.txt` — **не изменялись/не коммитились**; force-push — не применялся; в индекс не попали `.env*`, zip, скриншоты, `tools/_ui_*`, `var/backups`.
- **Примечание:** `.env.bak.round1025-f9`, упомянутый в плане фичи, на проде **отсутствует**. F9 — UI-only (Δ DDL=0, env-переменные не менялись), создание нового env-бэкапа не требуется; откат обеспечивается git-тегом.

## Откат (готовность подтверждена, не выполнялся)

- **Hard rollback:** `cd /var/www/admin_bot && git checkout pre-round1025-f9` (= `93432c0`) `+ sudo -n /usr/bin/systemctl restart admin_bot` (либо `git revert f5fbd5f c610c5f` + restart).
- **Soft rollback:** не применим (нет feature-flag/env-гейта у F9; изменение — bump `APP_VERSION` + cache-bust, откат только через тег/реверт).
- Δ DDL = 0 → миграционный откат не нужен. Тег/бэкапы/`stash@{0}` не удалять (R18).

## Явные ограничения (важно)

- **HTTP 200 / health / served `?v` ≠ корректный UI и корректная работа с секретами.** Верифицирован деплой-гейт (ff-pull, рестарт, health, версия, served `?v`, `database is locked`=0, отсутствие ошибок старта).
- **Живой TMA/WebView:** клавиатура/SaveBar-safe-area, поведение `secret-field` (маска-индикатор, «Ключ установлен», «Заменить»/«Удалить») в реальном Telegram WebView (Android/iOS) **не проверялись** headless-инструментами → **PENDING OWNER VERIFICATION (T-3059)**. Workflow не останавливается (UPD §8).

## Handoff

**RESULT: DEPLOYED — VERIFIED.** F9 `secrets-and-save-states-round1025` выведена на прод: коммиты `f5fbd5f` (код+тесты, 31 файл) → `c610c5f` (планы, 15 файлов), push `93432c0..c610c5f` (без force); прод Fast-forward `908f471..c610c5f`, `admin_bot` **active** (`MainPID 254733`, `NRestarts 0`), `/api/health` **200**, `/healthz`/`APP_VERSION` = **2.58.16**, served `?v=2.58.16` (10 вхождений, stale 0), `/web/app.js`/`/web/static/app.css` — 200, `database is locked`=0, Traceback/ERROR/CRITICAL=0, `pg_available=True`, polling `@PERMsoc_bot`. Δ DDL=0, Δ каталога=0. Откат — тег `pre-round1025-f9` (=`93432c0`). Живой гейт **PENDING OWNER VERIFICATION (T-3059: TMA/WebView — клавиатура/safe-area + secret-field; HTTP 200 ≠ корректный UI/секреты)**. Следующие: @Orchestrator — @Architect reconciliation (§68), @PM archive-close, @Memory metrics/KG (T-3060, Шаг 10); далее — **F11 `status-showcase-dashboard-round1025`**, затем F10 `epic1-verification-round1025`.
