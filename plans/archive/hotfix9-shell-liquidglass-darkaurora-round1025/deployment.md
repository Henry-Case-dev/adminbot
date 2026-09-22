# deployment.md — HOTFIX9 `hotfix9-shell-liquidglass-darkaurora-round1025`

> **Статус:** **`VERIFIED`** (Step 9 / T-2837 [@DevOps]).
> **Предусловия:** @Reviewer **Approved** (итерация 2, T-2835); @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 / Info 3** (`plans/reports/round1025_hotfix9_scanner_audit.md`); Merge — `plans/ARCHITECTURE.md` §63.
> **Дата релиза:** 22.09.2026. **Pull:** `~10:29Z`; **рестарт прод:** `10:30:50 UTC` → юнит `active` `10:31:50 UTC`; **бот готов:** `10:32:10 UTC`; **проверки:** `10:32–10:34 UTC`.

## Окружение

- Прод-VPS `racknerd-f4e3456` (`198.46.175.136`), каталог `/var/www/admin_bot`.
- systemd-сервис `admin_bot` (`ExecStart=/var/www/admin_bot/venv/bin/python bot.py`), API на `127.0.0.1:8000`; webapp `https://admin-bot.duckdns.org/web/`.
- Доступ @DevOps: SSH-ключ (паспорт/host не печатаются); sudo NOPASSWD для абсолютного `/usr/bin/systemctl {start,stop,restart,status} admin_bot` и `/usr/bin/journalctl -u admin_bot`.

## Артефакты и коммиты

| Артефакт | Значение |
|---|---|
| Коммит кода/тестов/vendor | `470b63a` — `feat(round1025): hotfix9 — flex-геометрия shell + мобильная nav, удаление диагональной текстуры, графит-токены, назначение преломления (vendored liquidglass/ogl), Dark Aurora Flow, modal footer, fix heartbeat fullscreen, APP_VERSION 2.58.12` (36 файлов) |
| Коммит планов | `8d61926` — `docs(plans): round1025 hotfix9 — Merge §63 + архивация + Scanner-аудит` (13 файлов) |
| Push | `origin/master`: `b374c0f..8d61926` (без force, exit 0) |
| Прод HEAD (было → стало) | `1a8ed18` → **`8d61926`** (`git pull --ff-only`, **Fast-forward**, reflog `HEAD@{0}: pull --ff-only: Fast-forward`) |
| `APP_VERSION` (прод) | 2.58.11 → **2.58.12** (`config/settings.py:1734`) |
| Точка отката | аннотированный тег `pre-round1025-hotfix9` (объект `9f8f4fc` → коммит `b374c0f`) — локально и в `origin` (`git ls-remote`); проверен |
| Бэкапы (R18) | `var/backups/**`, теги и `stash@{0}` — **не удалялись**; `deploy_commands.txt`/`plans/current_task.md` не изменялись; force-push не применялся |

## Ход релиза

1. **WC-инспекция:** `git status`/`git diff --stat` — ожидаемый набор; секретов/`.env*`(кроме `.env.example`-шаблона)/`current_task.md`/zip/`deploy_commands.txt`/`var/backups` в коммит не попало.
2. **Vendor/ignore:** новые бандлы `web/static/vendor/{ogl.1.0.11.min.js,liquidglass.core.0.5.3.min.js,liquidglass.core.0.5.3.css,README.md}` попадают в коммит; `tools/vendor/node_modules/` и `tools/_hotfix9_glass_probe/` — gitignored (проверено `git check-ignore`). **SHA-256 vendored 3/3 совпали** с `web/static/vendor/README.md`.
3. **Проверки WC:** `node --check` `app.js`/`telegram-init.js`/`aurora-flow.js`/`glass.js`/vendored-бандлы/`build.mjs` — OK; полный pytest **8291 passed / 0 failed** (1 warn Starlette, не блокер).
4. **Коммиты** `470b63a` → `8d61926`; `git push origin master` → `b374c0f..8d61926` (exit 0, без force).
5. **Прод:** `git fetch` → `git pull --ff-only` → **Fast-forward** `1a8ed18..8d61926`; tracked-дерево чистое.
6. **Прод:** `sudo -n /usr/bin/systemctl restart admin_bot` → сервис `active (running)`, `Main PID 154704`.
7. **Пост-рестартные проверки** (см. ниже).

## Проверки (фактические)

| Проверка | Результат |
|---|---|
| `systemctl status admin_bot` | **active (running)**, `Main PID 154704`, старт `10:31:50 UTC` |
| `GET http://127.0.0.1:8000/api/health` | **HTTP 200** |
| `GET /healthz` | **200**, тело `{"status":"ok","version":"2.58.12"}` |
| `APP_VERSION` в прод-дереве | **2.58.12** (`config/settings.py:1734`) |
| served HTML — ассеты | `?v=2.58.12` (уникальный), плейсхолдер `__APP_VERSION__` = **0** |
| Новые ассеты same-origin | `aurora-flow.js` **200**, `glass.js` **200**, `vendor/ogl.1.0.11.min.js` **200**, `vendor/liquidglass.core.0.5.3.min.js` **200**, `vendor/liquidglass.core.0.5.3.css` **200** |
| Теги новых ассетов в отдаваемом HTML | `aurora-flow.js`, `glass.js`, `ogl.1.0.11.min.js`, `liquidglass.core.0.5.3.min.js`, `liquidglass.core.0.5.3.css` — присутствуют |
| Внешние/off-origin скрипты в HTML | **0** (`src="http`) |
| CSP | `default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors ...` — same-origin, без CDN |
| `database is locked` (tail 400 / tail 1500, пост-рестарт) | **0 / 0** |
| `Traceback` / `ERROR` (tail 400) | **0 / 0** |
| Лог старта | `Bot started, listening for messages...`, `Start polling` (`@PERMsoc_bot`), `lifespan started | pg_available=True` |

> **Опер. наблюдение (не блокер):** остановка старого юнита вышла за `TimeoutStopSec` — systemd зафиксировал `Main process exited, code=killed, status=9/KILL` / `Failed with result 'timeout'` и стартовал новый процесс. Новый процесс поднялся штатно (`active`, health 200). Это pre-existing поведение graceful-shutdown (долгий останов воркеров), **не** дефект hotfix9; кандидат на отдельную задачу по ускорению остановки.

## Схема данных и инварианты

- **Δ DDL = 0**, миграции не запускались. Изменения клиентские (`app.css`/`app.js`/`index.html`/`telegram-init.js` + новые `aurora-flow.js`/`glass.js`/vendored-бандлы) + аддитивные (`web/api/routes.py` — 4 флага в `ui_flags`), `config/settings.py` (+4 env-only `ClassVar`, bump), `.env.example`, README, `.gitignore`, tests, tools, план-доки.
- **Δ каталога = 0** (459/98/96/21/418); новые флаги — вне `param_catalog` (env-only, default ON, доставка `GET /api/me.ui_flags`, наружу только bool).
- Progressive delivery 10/50/100 % не применяется (один прод, прецедент §53–§63); поставка = bump `APP_VERSION` + cache-bust `?v=__APP_VERSION__`.
- Секреты не цитировались (R17/R18).

## Откат

- **Hard rollback:** `git revert 470b63a` (или `git checkout pre-round1025-hotfix9` → `b374c0f`) + `sudo -n /usr/bin/systemctl restart admin_bot`.
- **Soft rollback без редеплоя (env-only, default ON):** `UI_SHELL_FLEX_V3=false` (прежняя геометрия высот/fixed nav), `UI_SHELL_GRAPHITE_V3=false` / legacy `UI_SHELL_V3=false` (значения `--shell-*` hotfix8; текстура НЕ возвращается), `UI_LIQUID_GLASS_LIB=false` (только frost-fallback), `UI_AURORA_FLOW_V2=false` (прежний CSS-aurora). Требует рестарта.
- Тег `pre-round1025-hotfix9` → `b374c0f`; бэкапы/теги/`stash@{0}` **не удалялись** (R18).

## Границы доказательств (важно)

- **HTTP 200 / health / наличие ассетов ≠ доказательство корректного layout.** Проверки выше подтверждают лишь доставку и доступность билда на проде.
- **Живой Telegram WebView (Android/iOS)** — реальные insets/клавиатура, «панель целиком в экране», FPS стекла/фона, WebKit-поведение `feDisplacementMap`, fullscreen-сердцебиение — **PENDING OWNER VERIFICATION** (headless-непроверяемо).

## Handoff

**RESULT: DEPLOYED — VERIFIED.** HOTFIX9 `hotfix9-shell-liquidglass-darkaurora-round1025` выкачена на прод: Fast-forward `1a8ed18..8d61926`, `admin_bot` active (`Main PID 154704`), `/api/health` **200**, `APP_VERSION`/`/healthz` = **2.58.12**, served `?v=2.58.12`, новые ассеты (`aurora-flow.js`, `glass.js`, `vendor/*`) отдаются **200** same-origin, CSP без CDN, `database is locked`=0, Traceback/ERROR=0. Откат — тег `pre-round1025-hotfix9` → `b374c0f`. Открыт **только live-гейт владельца (T-2832, WebView)**. Далее: @Architect — реконсиляция, @PM — закрытие, @Memory — метрики + KG, затем следующая фича **F6** `memory-analytics-reorg-round1025`.
