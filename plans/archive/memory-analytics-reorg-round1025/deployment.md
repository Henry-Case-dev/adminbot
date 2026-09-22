# deployment.md — F6 `memory-analytics-reorg-round1025`

> **Статус:** **`VERIFIED`** (Step 9 / T-2916 [@DevOps]).
> **Предусловия:** @Reviewer **Approved** (итерация 2, T-2911; H1/H2/M-F6S-1 закрыты — `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 2 / Info 4 → «к деплою — ДА»** (`plans/reports/round1025_f6_scanner_audit.md`); Merge — `plans/ARCHITECTURE.md` **§65** (@Architect, Step 7); архивация F6 выполнена (папка фичи → `plans/archive/memory-analytics-reorg-round1025/`).
> **Дата релиза:** 23.09.2026 (проектный календарь, WC). **Прод-таймстемпы (UTC, clock прод-хоста):** ff-pull `2026-09-22 14:27:14Z` (reflog `HEAD@{2026-09-22 14:27:14 +0000}: pull --ff-only: Fast-forward`); рестарт/старт юнита `ActiveEnterTimestamp=Tue 2026-09-22 14:28:31 UTC`; проверки `14:28–14:30Z`. ⚠️ Расхождение ~1 сутки между clock WC (`Wed 2026-09-23`) и clock прод-хоста (`Tue 2026-09-22`) — в таблицах ниже приведены фактические прод-значения.

## Окружение

- Прод-VPS `racknerd-f4e3456` (`198.46.175.136`), каталог `/var/www/admin_bot`; webapp `https://admin-bot.duckdns.org/web/`.
- systemd-юнит `admin_bot` (`ExecStart=/var/www/admin_bot/venv/bin/python bot.py`), API на `127.0.0.1:8000`.
- Доступ @DevOps: SSH-ключ (`nik@racknerd-f4e3456`); `sudo -n /usr/bin/systemctl restart admin_bot` — NOPASSWD, выполнено без пароля. Секреты/пароли не печатались (R17/R18).

## Артефакты и коммиты

| Артефакт | Значение |
|---|---|
| Коммит кода/тестов | `02b99e9` — `feat(round1025): F6 — Аналитика + adapter ExecutionGraph (execution_graph.js), 2 режима карты, интерактивность/фильтры/поиск, честные §28-состояния, раздел «Память» (AMEND-1 §52), APP_VERSION 2.58.14` (**24 файла, +1901/−357**; включает новый `web/static/execution_graph.js`) |
| Коммит планов | `cddacda` — `docs(plans): round1025 F6 — Merge §65 + архивация + Scanner-аудит` (**15 файлов, +816/−40**) |
| Коммит деплой-дока | `docs(deploy): round1025 F6 — прод-деплой VERIFIED (APP_VERSION 2.58.14) + deployment.md` (этот файл; последний коммит `master`) |
| Push | `origin/master`: `f103992..cddacda` (без force, exit 0); `git ls-remote` → `refs/heads/master` = `cddacda` |
| Прод HEAD (было → стало) | `24dc7e3` → **`cddacda`** (`git pull --ff-only origin master`, **Fast-forward** `24dc7e3..cddacda`) |
| `APP_VERSION` (прод) | 2.58.13 → **2.58.14** (`config/settings.py:1739`) |
| Точка отката | аннотированный тег `pre-round1025-f6` (объект `f8ad1d5`) → **`f103992`**; прилетел на прод при `git fetch --tags`, сохранён |
| Бэкапы (R18) | `var/backups/**` (root-owned, не тронут), `./backups`; теги `pre-round1025*` (8 на проде); `stash@{0}` (прод: `pre-10.15-deploy info_text.md drift`; WC: `wip(f1)…`) — **не удалялись**; `deploy_commands.txt`/`plans/current_task.md` не изменялись; force-push не применялся |

## Ход релиза

1. **WC-инспекция:** `git status` / `git diff --stat` — ожидаемый набор (код: `web/app.js`, `web/index.html`, `web/static/app.css`, **новый** `web/static/execution_graph.js`, `config/settings.py`, `README.md`; тесты; планы). В коммит **не** попали `.env*` (13 ignored), `current_task.md`, `*.zip`, `deploy_commands.txt`, `var/backups`, `tools/_ui_*` (все gitignored/`!!`). `web/api/analytics.py` в дереве **не изменён** (доверие git). Скан диффа и новых файлов на секреты — **0 находок**.
2. **Локальная верификация (WC):** `node --check web/app.js` / `web/static/execution_graph.js` — OK; JS-тесты `tests/js/*` — **37/37 PASS (0 fail)**; F6 pytest — **19 passed**; маркер-набор (`js_unit`/`design_tokens`/`scope_selector`/`hotfix6–10`) — **203 passed**; `git diff --check` = exit 0; **Δ DDL = 0** (`git diff --stat HEAD -- services handlers migrate_history migrations alembic web/api` пусто).
3. **Коммиты** `02b99e9` (код+тесты) → `cddacda` (планы); `git push origin master` → `f103992..cddacda` (exit 0, без force).
4. **Прод pre-state:** HEAD `24dc7e3`, `APP_VERSION` 2.58.13, юнит `active`, tracked-дерево чистое (untracked `info_text.md.bak.*`/`local_database.db.bak.*` — не мешают).
5. **Прод:** `git fetch origin --tags` → `24dc7e3..cddacda` (+ tag `pre-round1025-f6`) → `git pull --ff-only origin master` → **Fast-forward** `24dc7e3..cddacda`; `APP_VERSION` = 2.58.14; tracked-дерево чистое.
6. **Прод:** `sudo -n /usr/bin/systemctl restart admin_bot` (exit 0) → `active (running)`, `MainPID 202155`, `NRestarts 0`, старт `14:28:31 UTC`.
7. **Пост-рестартные проверки** — см. ниже.

## Проверки (фактические)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active** |
| `MainPID` / `NRestarts` / `ActiveEnterTimestamp` | `202155` / `0` / `Tue 2026-09-22 14:28:31 UTC` |
| `GET http://127.0.0.1:8000/api/health` | **HTTP 200** |
| `GET /healthz` | **200**, тело `{"status":"ok","version":"2.58.14"}` |
| `APP_VERSION` в прод-дереве | **2.58.14** (`config/settings.py:1739`) |
| `GET /web/` / `/web/index.html` | **200** / **200** |
| served `?v` | `?v=2.58.14` — **10** вхождений в HTML (`app.js`, `app.css`, `execution_graph.js`, vendor/glass/aurora) |
| Плейсхолдер `__APP_VERSION__` в отдаваемом HTML | **0** (заменён) |
| Новый adapter same-origin | `GET /static/execution_graph.js?v=2.58.14` → **200**, маркер `ExecutionGraph` присутствует; тег подключён **до** `app.js` |
| Ключевые ассеты | `/web/app.js?v=2.58.14` → **200**; `/static/app.css?v=2.58.14` → **200** |
| Внешние/off-origin скрипты (`src=http`) | **0** (CSP `script-src 'self'`) |
| `database is locked` (окно `14:27–14:30Z`, `systemctl status -n 3000`) | **0** |
| `Traceback` / `ERROR` (то же окно) | **0 / 0** |
| Лог старта | `[uptime] heartbeat started`, `[webapp] lifespan started | pg_available=True`, `Start polling`, `Run polling for bot @PERMsoc_bot` |

> Ранее выполненный `curl /static/app.js` дал 404 — ожидаемо: `app.js` монтируется на `/web/app.js` (`app.mount("/web", …)`), а adapter — на `/static/execution_graph.js` (`app.mount("/static", …)`); оба маршрута same-origin. Проверено корректными URL.

## Схема данных и инварианты

- **Δ DDL = 0**: миграции не запускались; `services/**`, `handlers`, `migrations`, `alembic`, `web/api` вне диффа; SQLite `user_version` не менялся.
- **Δ каталога = 0**: `services/param_catalog.py` не тронут; 459/98/96/21/418.
- **CSP same-origin / zero-build**: adapter `execution_graph.js` — внешний same-origin `<script src>` с `?v=`, без CDN/инлайна/data-URI; 0 внешних `src`.
- Progressive delivery 10/50/100 % не применяется (один прод, прецедент §53–§65); поставка = bump `APP_VERSION` + cache-bust `?v=__APP_VERSION__`.
- Откат-контур сохранён: `TOKEN_FLOW_NODEFLOW_ENABLED=OFF` (рендер → прежние плоские бейджи), `TOKEN_ANALYTICS_ENABLED=OFF` (серверный kill-switch). Новый флаг не вводился.

## Откат (готовность)

- **Hard rollback:** `git checkout pre-round1025-f6` (→ `f103992`) `+ sudo -n /usr/bin/systemctl restart admin_bot` (или `git revert 02b99e9`).
- **Soft rollback:** env-only флаги выше (требует рестарта) либо «Сброс» фильтров/смена режима в UI.
- Тег `pre-round1025-f6` → `f103992`; бэкапы/теги/`stash@{0}` **не удалялись** (R18). Force-push не выполнялся. Изменения чисто клиентские/аддитивные (UI + bump) — откат не затрагивает схему данных.

## Границы доказательств (важно)

- **HTTP 200 / health / ответ ассетов ≠ доказательство корректного layout и корректности данных.** Приведённые проверки подтверждают **только** доставку и доступность билда на проде (ff-pull, рестарт, health, версия, served `?v`, adapter same-origin, `database is locked`=0).
- **Живой Telegram WebView (Android/iOS) + реальный PG-пайплайн `/analytics/*` (карта вызовов, режимы §26, фильтры §27, side-panel/bottom-sheet, превью Статуса §21, раздел «Память» §52–§56) прод-проверкой НЕ измерены** — Playwright/матрица работали на стабах, headless ≠ WebView. **PENDING OWNER VERIFICATION** (T-2917).
- Остаточный техдолг (не блокеры): L-F6S-1 (`fromSummary` `priceKnown:true` при неизвестной агрегатной цене), L-F6S-2 (OFF-ветка kill-switch не byte-identical) — зафиксированы в `review.md`/аудите.

## Handoff

**RESULT: DEPLOYED — VERIFIED.** F6 `memory-analytics-reorg-round1025` выкачена на прод: коммиты `02b99e9` (код+тесты, 24 файла) → `cddacda` (планы, 15 файлов), push `f103992..cddacda` (без force); прод Fast-forward `24dc7e3..cddacda` (`14:27:14Z`), `admin_bot` **active** (`MainPID 202155`), `/api/health` **200**, `/healthz`/`APP_VERSION` = **2.58.14**, served `?v=2.58.14`, `execution_graph.js` **200** same-origin, внешних скриптов=0, `database is locked`=0, Traceback/ERROR=0, `pg_available=True`. Откат — тег `pre-round1025-f6` → `f103992`. Открыт **только live-гейт владельца (T-2917: WebView + реальный PG-пайплайн)**. Далее: @Orchestrator — @Architect reconciliation (§65), @PM archive-close, @Memory metrics/KG (Шаг 10), затем следующая фича.
