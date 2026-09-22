# deployment.md — F7 `permsoc-local-space-round1025`

> **Статус:** **`VERIFIED`** (Step 9 / T-2960 [@DevOps]).
> **Предусловия:** @Reviewer **Approved** (итерация 3, T-2956; H-F7-1/M-F7-2/H-F7-7 + L-F7-3/5/8/9 закрыты — `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 3 / Info 3 → «к деплою — ДА»** (`plans/reports/round1025_f7_scanner_audit.md`); Merge — `plans/ARCHITECTURE.md` **§66** (@Architect, Step 7); архивация F7 выполнена (папка фичи → `plans/archive/permsoc-local-space-round1025/`). Точка отката `pre-round1025-f7` → `551847d` (на WC и на проде).
> **Дата релиза:** 23.09.2026 (проектный календарь, WC). **Прод-таймстемпы (UTC, clock прод-хоста):** `git fetch --tags` `16:30:35Z` (прилетел тег `pre-round1025-f7`); ff-pull `reflog: pull --ff-only origin master: Fast-forward` (`16:30–16:31Z`); рестарт/старт юнита `ActiveEnterTimestamp=Tue 2026-09-22 16:31:50 UTC`; проверки `16:31:50–16:33:30Z`. ⚠️ Расхождение ~1 сутки между clock WC (`Wed 2026-09-23`) и clock прод-хоста (`Tue 2026-09-22`) — в таблицах ниже приведены фактические прод-значения.

## Окружение

- Прод-VPS `racknerd-f4e3456` (`198.46.175.136`), каталог `/var/www/admin_bot`; webapp `https://admin-bot.duckdns.org/web/`.
- systemd-юнит `admin_bot` (`ExecStart=/var/www/admin_bot/venv/bin/python /var/www/admin_bot/bot.py`, `Restart=always`), API на `127.0.0.1:8000`.
- Доступ @DevOps: SSH-ключ (`nik@racknerd-f4e3456`); `sudo -n /usr/bin/systemctl restart admin_bot` — NOPASSWD, выполнено без пароля (exit 0). Секреты/пароли не печатались (R17/R18).

## Артефакты и коммиты

| Артефакт | Значение |
|---|---|
| Коммит кода/тестов | `6bf00e7` — `feat(round1025): F7 — локальное пространство PERMsoc (только чат, guard против записи в глобал), 6 блоков, OFF блока сохраняет дочерние, серверные per-chat гейты (реакции/расписания), подгруппы + ID-списки, APP_VERSION 2.58.15` (**33 файла, +1563/−133**; backend `services/{permsoc,feature_gates,goodmorning_scheduler}.py`, `handlers/{alan,alan_greeting,common,slavik,vasya,war_alert}.py`, `web/api/{gates,routes}.py`, `config/settings.py`, `README.md`; frontend `web/app.js`, `web/index.html`; `tools/ui_round1025_matrix.py`; новые F7-тесты + правки маркеров) |
| Коммит планов | `908f471` — `docs(plans): round1025 F7 — Merge §66 + архивация + Scanner-аудит` (**15 файлов, +925/−31**; §66, MEMORY, backlog, workflow_state, round1025-architecture, reports, архив фичи, `plans/features/…/tasks.md` → `plans/archive/…/tasks.md`) |
| Коммит деплой-дока | `docs(deploy): round1025 F7 — прод-деплой VERIFIED (APP_VERSION 2.58.15) + deployment.md` (этот файл; последний коммит `master`) |
| Push | `origin/master`: `551847d..908f471` (код+планы, exit 0, без force) и `908f471..e2b452c` (деплой-док); `git ls-remote` → `refs/heads/master` = `e2b452c` |
| Прод HEAD (было → стало) | `cddacda` → **`908f471`** (`git pull --ff-only origin master`, **Fast-forward** `cddacda..908f471`; reflog `HEAD@{0}: pull --ff-only origin master: Fast-forward`) |
| `APP_VERSION` (прод) | 2.58.14 → **2.58.15** (`config/settings.py:1748`) |
| Точка отката | аннотированный тег `pre-round1025-f7` (объект `8c2e608`) → **`551847d`** (`^{commit}` = `551847db4b6462fe998b64aa466503373740697a`); прилетел на прод при `git fetch --tags`, сохранён |
| Бэкапы (R18) | `var/backups/**` (root-owned) и `./backups` — **не тронуты** (ротация не выполнялась); тег `pre-round1025-f7` + ранее существовавшие теги (прод: **9** тегов всего, WC: **19**) — **не удалялись**; `stash@{0}` — **не удалялась** (прод: `pre-10.15-deploy info_text.md drift`, WC: `wip(f1)…`, обе pre-existing); `deploy_commands.txt` / `plans/current_task.md` не изменялись; force-push не применялся |

## Ход релиза

1. **WC-инспекция:** `git status` / `git diff --stat` — ожидаемый набор (код: `services/*`, `handlers/*`, `web/api/{gates,routes}.py`, `web/app.js`, `web/index.html`, `config/settings.py`, `README.md`; `tools/ui_round1025_matrix.py`; тесты; планы). В коммиты **не** попали `.env*` (`.env`, `.env.bak.round1025-*` — 14 ignored), `plans/current_task.md`, `web.zip`, `deploy_commands.txt`, `var/backups`, `tools/_ui_*` (все gitignored/`!!`). `services/param_catalog.py` в дереве **не изменён** (доверие git). Скан диффа и новых файлов (`tests/*`, `plans/archive/**`, `plans/reports/*`) на секреты — **0 находок**.
2. **Локальная верификация (WC):** `node --check web/app.js` / `tests/js/round1025_f7_permsoc_local_test.js` — exit 0; все `tests/js/*` — **38/38 OK (0 fail)**; F7 pytest (`test_permsoc_f7_round1025.py`, `test_webapp_f7_round1025.py`) — **33 passed**; маркер-набор (`js_unit`/`scope_selector`/`design_tokens`/`f6`/`hotfix6–10`) — **223 passed**; `py_compile` изменённых модулей — exit 0; `git diff --check` — exit 0.
3. **Коммиты** `6bf00e7` (код+тесты, 33 файла) → `908f471` (планы, 15 файлов); `git push origin master` → `551847d..908f471` (exit 0, без force).
4. **Прод pre-state:** HEAD `cddacda`, `APP_VERSION` 2.58.14, юнит `active`, tracked-дерево чистое.
5. **Прод:** `git fetch origin --tags` → `cddacda..908f471` + новый тег `pre-round1025-f7`; `git pull --ff-only origin master` → **Fast-forward** `cddacda..908f471`; `APP_VERSION` = 2.58.15; tracked-дерево чистое (`git status --porcelain` = 0).
6. **Прод:** `sudo -n /usr/bin/systemctl restart admin_bot` (exit 0) → `active (running)`, `MainPID 226878`, `NRestarts 0`, старт `16:31:50 UTC`.
7. **Пост-рестартные проверки** — см. ниже. Первый HTTP-проб (`~16:31:58Z`) дал `000` (сокет `:8000` уже LISTEN, но приложение ещё проходило инициализацию) → повторный проб `16:32:24Z` → **200**; в таблице ниже — устойчивый результат.

## Проверки (фактические)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active** |
| `ActiveState`/`SubState`/`MainPID`/`NRestarts`/`ActiveEnterTimestamp` | `active`/`running`/`226878`/`0`/`Tue 2026-09-22 16:31:50 UTC` |
| `GET http://127.0.0.1:8000/api/health` | **HTTP 200** |
| `GET /healthz` | **200**, тело `{"status":"ok","version":"2.58.15"}` |
| `APP_VERSION` в прод-дереве | **2.58.15** (`config/settings.py:1748`) |
| `GET /web/` / `/web/index.html` | **200** / **200** |
| served `?v` | `?v=2.58.15` — **10** вхождений в HTML |
| Плейсхолдер `__APP_VERSION__` в отдаваемом HTML | **0** (заменён) |
| Ключевые ассеты | `/web/app.js?v=2.58.15` → **200**; `/static/app.css?v=2.58.15` → **200** |
| Внешние/off-origin скрипты (`src=http`) | **0** (CSP `script-src 'self'`) |
| F7-маршруты живы (не 404) | `GET /api/me` → **401**; `GET /api/chat/-100123/gates` → **401**; `PUT` → **401** (TMA-auth обязателен, роутеры смонтированы) |
| `database is locked` (окно `16:31:40–16:33:23Z`, 143 строки журнала) | **0** |
| `Traceback` / `ERROR` / `CRITICAL` (то же окно) | **0 / 0 / 0** |
| Лог старта | `Bot started, listening for messages...`; `[uptime] heartbeat started: interval=60s retention=72h`; `Start polling`; `[webapp] lifespan started \| pg_available=True`; `Run polling for bot @PERMsoc_bot id=8802473181` |
| Прод-дерево после релиза | `git status --porcelain --untracked-files=no` = **0**; `cddacda..908f471` = **51 файл, +2614/−178** |

## Схема данных и инварианты

- **Δ DDL = 0**: файлов в `migrations`/`alembic`/`migrate_history` в диапазоне `cddacda..908f471` — **0**; миграции не запускались; SQLite `user_version` не менялся.
- **Δ каталога = 0**: `services/param_catalog.py` в диапазоне релиза не тронут.
- **Guard R17/R18:** per-chat блок-гейты «Общие реакции»/«Расписания» — env-only `PERMSOC_BLOCK_GATES_ENABLED` (ClassVar, default ON; в `param_catalog` НЕ входит, Δ=0), наружу только bool через `GET /api/me.ui_flags`; `permsoc*`-семейство в `web/api/gates.py` — `who_can_toggle='global'`, PUT/DM → 403.
- **CSP same-origin / zero-build:** без новых CDN; `?v=__APP_VERSION__` cache-bust.
- Progressive delivery 10/50/100 % не применяется (один прод, прецедент §53–§66); поставка = bump `APP_VERSION` + cache-bust `?v=__APP_VERSION__`.

## Откат (готовность)

- **Hard rollback:** `git checkout pre-round1025-f7` (→ `551847d`) `+ sudo -n /usr/bin/systemctl restart admin_bot` (или `git revert 6bf00e7` + `git revert 908f471`).
- **Soft rollback:** env-only `PERMSOC_BLOCK_GATES_ENABLED=OFF` (требует рестарта; серверные per-chat гейты → baseline, новые блок-тумблеры честно read-only) либо возврат мастера-гейта `permsoc` в OFF.
- Тег `pre-round1025-f7` → `551847d`; бэкапы/теги/`stash@{0}` **не удалялись** (R18). Force-push не выполнялся. Δ DDL = 0 → откат не затрагивает схему данных.

## Границы доказательств (важно)

- **HTTP 200 / health / ответ ассетов ≠ доказательство корректного layout и корректного поведения.** Приведённые проверки подтверждают **только** доставку и доступность билда на проде (ff-pull, рестарт, health, версия, served `?v`, роуты живы, `database is locked`=0).
- **Живой Telegram WebView/TMA (Android/iOS) + реальные фоновые задачи (утренняя рассылка с per-chat проверкой гейта `Расписания`, канонический `chat_id`, OFF блока сохраняет дочерние, guard «нет записи в global») прод-проверкой НЕ измерены** — Playwright/матрица работали на стабах, headless ≠ WebView. **PENDING OWNER VERIFICATION** (T-2961).
- Остаточный техдолг (не блокеры): L-F7S-1 (`_normalizeConfigItems{}` denylist для global-категории), L-F7-4 (`dead_page_post_on_join` не мигрирован), L-F7-6 (DM-попытка global admin → 403, pre-existing) — follow-up, см. `review.md`/аудит.

## Handoff

**RESULT: DEPLOYED — VERIFIED.** F7 `permsoc-local-space-round1025` выкачена на прод: коммиты `6bf00e7` (код+тесты, 33 файла) → `908f471` (планы, 15 файлов), push `551847d..908f471` (без force); прод Fast-forward `cddacda..908f471` (`16:30–16:31Z`), `admin_bot` **active** (`MainPID 226878`), `/api/health` **200**, `/healthz`/`APP_VERSION` = **2.58.15**, served `?v=2.58.15` (10 вхождений, плейсхолдер 0), `/web/app.js`/`/static/app.css` **200**, внешних скриптов=0, `/api/me` + `/api/chat/{id}/gates` → 401 (роуты живы), `database is locked`=0, Traceback/ERROR/CRITICAL=0, `pg_available=True`, polling `@PERMsoc_bot`. Δ DDL=0, Δ каталога=0. Откат — тег `pre-round1025-f7` → `551847d`; soft — `PERMSOC_BLOCK_GATES_ENABLED=OFF`. Открыт **только live-гейт владельца (T-2961: WebView/TMA + реальные фоновые задачи)**. Далее: @Orchestrator — @Architect reconciliation (§66), @PM archive-close, @Memory metrics/KG (Шаг 10), затем следующая фича (**F8 `parameter-registry-widget-map-round1025`**).
