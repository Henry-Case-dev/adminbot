# deployment.md — HOTFIX10 `hotfix10-liquidglass-rollback-shell-geometry-round1025`

> **Статус:** **`VERIFIED`** (Step 9 / T-2867 [@DevOps]).
> **Предусловия:** @Reviewer **Approved** (итерация 2, T-2865; блокер **H-1** и Low **L-H10-1**/**L-1**/**L-2** закрыты — `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 / Info 1 → «к деплою ГОТОВО»** (`plans/reports/round1025_hotfix10_scanner_audit.md`); Merge — `plans/ARCHITECTURE.md` **§64** (@Architect, Step 7).
> **Дата релиза:** 23.09.2026 (проектный календарь). **Прод-таймстемпы (UTC, clock прод-хоста):** ff-pull `2026-09-22 12:45:12Z`; рестарт и старт юнита `2026-09-22 12:46:21Z`; проверки `12:46–12:47Z`. ⚠️ Наблюдается расхождение ~1 сутки между clock WC и clock прод-хоста (прод: `Tue 2026-09-22`, WC: `Wed 2026-09-23`); в таблицах ниже приведены фактические прод-значения.

## Окружение

- Прод-VPS `racknerd-f4e3456` (`198.46.175.136`), каталог `/var/www/admin_bot`.
- systemd-сервис `admin_bot` (`ExecStart=/var/www/admin_bot/venv/bin/python bot.py`), API на `127.0.0.1:8000`; webapp `https://admin-bot.duckdns.org/web/`.
- Доступ @DevOps: SSH-ключ (паспорт/host значений паролей не печатались); sudo NOPASSWD — `/usr/bin/systemctl {start,stop,restart,status} admin_bot` и `/usr/bin/journalctl -u admin_bot` (доп. аргументы этих команд вне whitelist — учитывалось).

## Артефакты и коммиты

| Артефакт | Значение |
|---|---|
| Коммит кода/тестов | `bf086d4` — `fix(round1025): hotfix10 — откат glass с функциональных целей (UI_LIQUID_GLASS_LIB OFF, GlassSurface на 1 декоративном), единая подложка Main, единая модель высоты, восстановление .status-block (grid-auto-rows), resize OGL-фона в fullscreen, APP_VERSION 2.58.13` (23 файла, +1259/−51) |
| Коммит планов | `24dc7e3` — `docs(plans): round1025 hotfix10 — Merge §64 + архивация + Scanner-аудит` (14 файлов, +737/−12) |
| Push | `origin/master`: `5184584..24dc7e3` (без force, exit 0); `git ls-remote` → `refs/heads/master` = `24dc7e3` |
| Прод HEAD (было → стало) | `8d61926` → **`24dc7e3`** (`git pull --ff-only`, **Fast-forward** `8d61926..24dc7e3`, reflog `HEAD@{2026-09-22 12:45:12 +0000}: pull --ff-only: Fast-forward`) |
| `APP_VERSION` (прод) | 2.58.12 → **2.58.13** (`config/settings.py:1739`) |
| Точка отката | аннотированный тег `pre-round1025-hotfix10` (объект `0f96dcc`) — локально и в `origin` (`git ls-files`/`ls-remote`); проверен |
| Бэкапы (R18) | `var/backups/**` (20 записей, не тронуты), теги `pre-round1025-hotfix*` (9), `stash@{0}` — **не удалялись**; `deploy_commands.txt`/`plans/current_task.md` не изменялись (R17/R18); force-push не применялся |

## Ход релиза

1. **WC-инспекция:** `git status`/`git diff --stat` — ожидаемый набор; в коммит не попало секретов/`.env`/`current_task.md`/zip/`deploy_commands.txt`/`var/backups`/`tools/_ui_*` (артефакты матрицы `tools/_ui_round1025_*` — gitignored, проверено `git check-ignore`). `web/api/routes.py` в дереве **не изменён** (в сообщении задачи упоминался ошибочно — доверие git).
2. **Локальная верификация (WC):** `node --check` `app.js`/`glass.js`/`aurora-flow.js`/hotfix10-JS — OK; полный `pytest -q` → **8319 passed / 0 failed** (1 warn Starlette, не блокер; 110s) — совпадает с baseline Builder/Scanner; матрица `tools/ui_round1025_matrix.py` — **failures: 0** (10 вьюпортов, normal+fullscreen); `git diff --check` = 0.
3. **Коммиты** `bf086d4` → `24dc7e3`; `git push origin master` → `5184584..24dc7e3` (exit 0, без force).
4. **Прод pre-state:** HEAD `8d61926`, `APP_VERSION` 2.58.12, tracked-дерево чистое, юнит `active`.
5. **Прод:** `git fetch` → `git pull --ff-only` → **Fast-forward** `8d61926..24dc7e3`; `APP_VERSION` = 2.58.13; tracked-дерево чистое.
6. **Прод:** `sudo -n /usr/bin/systemctl restart admin_bot` → сервис `active (running)`, `Main PID 181526`, старт `12:46:21 UTC`.
7. **Пост-рестартные проверки** (см. ниже).

## Проверки (фактические)

| Проверка | Результат |
|---|---|
| `systemctl status admin_bot` | **active (running)**, `Main PID 181526`, старт `2026-09-22 12:46:21 UTC` |
| `GET http://127.0.0.1:8000/api/health` | **HTTP 200** |
| `GET /healthz` | **200**, тело `{"status":"ok","version":"2.58.13"}` |
| `APP_VERSION` в прод-дереве | **2.58.13** (`config/settings.py:1739`) |
| served `/web/` — версия ассетов | `?v=2.58.13` (уникальный, cache-bust) |
| Плейсхолдер `__APP_VERSION__` в отдаваемом HTML | **0** (заменён) |
| Декоративный `data-glass-surface` в отдаваемом HTML | **1** (изолированный `GlassSurface`, `v-if=liquidGlassLib`) |
| Новые/ключевые ассеты same-origin | `app.css` **200**, `app.js` **200**, `glass.js` **200**, `aurora-flow.js` **200** |
| Внешние/off-origin скрипты в HTML | **0** (`src="http`) — CSP `script-src 'self'` |
| `database is locked` (окно `12:45–12:59Z`, 147 строк journal) | **0** |
| `Traceback` / `ERROR` (то же окно) | **0 / 0** |
| Лог старта | `Bot started, listening for messages...`, `Start polling`, `[webapp] lifespan started | pg_available=True`, `Run polling for bot @PERMsoc_bot` |
| Эффективный флаг стекла | `UI_LIQUID_GLASS_LIB` в прод-`.env` **не задан** → default **OFF** (`settings.py:765–766`); `.ps-glass*` на функциональных целях отсутствует |

> **Локальные проверки (WC) — не прод-факты:** `pytest 8319 passed/0`, `node --check` OK, матрица `failures: 0` отражают рабочее дерево и headless-Chromium; они **не** являются доказательством корректного layout в живом Telegram WebView.

## Схема данных и инварианты

- **Δ DDL = 0**: SQLite `user_version=12`; миграции не запускались, `services/**`/БД вне диффа.
- **Δ каталога = 0**: REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / Settings 418; `services/param_catalog.py` не тронут; флаги — env-only `ClassVar` (вне `pc.REGISTRY`).
- **CSP same-origin**: 0 внешних `src`/`href`, без CDN/инлайна/data-URI; `--shell-texture`=0; `backdrop-filter:url(`=0.
- **Откат стекла применён**: `UI_LIQUID_GLASS_LIB` default **OFF**; преломление/стекло монтируется только на 1 изолированный декоративный `[data-glass-surface]`.
- Progressive delivery 10/50/100 % не применяется (один прод, прецедент §53–§63); поставка = bump `APP_VERSION` + cache-bust `?v=__APP_VERSION__`.
- Секреты не цитировались (R17/R18).

## Откат

- **Hard rollback (полный возврат к hotfix9-поведению):** `git revert bf086d4` (или `git checkout pre-round1025-hotfix10` → `0f96dcc`) + `sudo -n /usr/bin/systemctl restart admin_bot`. Именно этот путь — корректный откат UPD4, т.к. суть хотфикса в **отключении** библиотеки на функциональных целях.
- **Soft rollback (env-only, требует рестарта — не возвращает hotfix9-дефект):** `UI_LIQUID_GLASS_LIB=true` повторно включает библиотеку **на изолированном декоративном `GlassSurface`** (новый код), а не на функциональных элементах; `UI_SHELL_FLEX_V3=false` / `UI_SHELL_GRAPHITE_V3=false` / `UI_AURORA_FLOW_V2=false` — legacy-геометрия/токены/фон.
- Тег `pre-round1025-hotfix10` → `0f96dcc`; бэкапы/теги/`stash@{0}` **не удалялись** (R18). Отдельный `.env.bak.round1025-hotfix10` **не создавался** (hotfix10 не изменяет `.env`; флаги env-only с default OFF) — в отличие от формулировки §64; актуален существующий `.env.bak.round1025-hotfix`.

## Границы доказательств (важно)

- **HTTP 200 / health / ответ ассетов ≠ доказательство корректного layout.** Приведённые проверки подтверждают **только** доставку и доступность билда на проде (ff-pull, рестарт, health, версия, served `?v`, отсутствие внешних скриптов, `database is locked`=0).
- **Корректность геометрии/стекла на реальной цели НЕ измерена прод-проверками.** Headless-Chromium-матрица (failures: 0) **не равна** Telegram WebView.
- **Живой Telegram WebView (Android/iOS)** — реальные insets/клавиатура, «карточка Status видима и не схлопывается», отсутствие двойного safe-area, поведение единой подложки Main, честный resize OGL-фона в fullscreen, FPS glass/aurora, WebKit-`feDisplacementMap` — **PENDING OWNER VERIFICATION** (T-2862; headless-непроверяемо).

## Handoff

**RESULT: DEPLOYED — VERIFIED.** HOTFIX10 `hotfix10-liquidglass-rollback-shell-geometry-round1025` выкачена на прод: коммиты `bf086d4` (код+тесты) → `24dc7e3` (планы), push `5184584..24dc7e3` (без force); прод Fast-forward `8d61926..24dc7e3` (`12:45:12Z`), `admin_bot` active (`Main PID 181526`), `/api/health` **200**, `/healthz`/`APP_VERSION` = **2.58.13**, served `?v=2.58.13`, `data-glass-surface`=1, внешних скриптов=0, `database is locked`=0, Traceback/ERROR=0. Откат — тег `pre-round1025-hotfix10` → `0f96dcc`. Открыт **только live-гейт владельца (T-2862, WebView)**. Далее: @Orchestrator — @Architect reconciliation, @PM archive-close, @Memory metrics/KG, затем следующая фича **F6** `memory-analytics-reorg-round1025` (T-2869).
