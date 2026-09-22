# deployment.md — HOTFIX8 `hotfix8-shell-glass-aurora-round1025`

> **Статус:** **`VERIFIED`** (Step 9 / T-2787 [@DevOps]).
> **Предусловия:** @Reviewer **Approved** (`review.md`); @Scanner **Critical 0 / High 0 / Medium 0** (`plans/reports/round1025_hotfix8_scanner_audit.md`); Merge — `plans/ARCHITECTURE.md` §62.
> **Дата релиза:** 22.09.2026. **Рестарт прода:** `06:47:44 UTC` (`18:47:44 +12:00`).
> **Код:** `98551b2` (feat) → `5124522` (chore bump) → `1a8ed18` (docs). Раннее в том же файле — baseline T-2745 (см. «Приложение»).

## Окружение

- Прод-VPS `racknerd-f4e3456` (`198.46.175.136`), каталог `/var/www/admin_bot`.
- systemd-сервис `admin_bot` (`ExecStart=/var/www/admin_bot/venv/bin/python bot.py`), API на `127.0.0.1:8000`; webapp `https://admin-bot.duckdns.org/web/`.
- Доступ @DevOps: SSH-ключ (паспорт/host не печатаются), sudo NOPASSWD для `systemctl restart/status admin_bot` и `journalctl -u admin_bot`.

## Артефакты и коммиты

| Артефакт | Значение |
|---|---|
| Коммит кода/тестов | `98551b2` — `feat(round1025): hotfix8 — shell v3 (тёмно-серый glass, снят ореол/линза), CSS-aurora фон, геометрия mobile/fullscreen (UPD2)` (13 файлов) |
| Коммит bump (`APP_VERSION`/README/пины) | `5124522` — `chore(round1025): bump APP_VERSION 2.58.10 -> 2.58.11 (cache-bust shell/aurora) + README` (9 файлов) |
| Коммит планов | `1a8ed18` — `docs(plans): round1025 hotfix8 — Merge §62 + архивация + Scanner-аудит` (16 файлов) |
| Push | `origin/master`: `a1e6db3..1a8ed18` (без force) |
| Прод HEAD (было → стало) | `af137cd` → **`1a8ed18`** (`git pull --ff-only`, **fast-forward**, без merge-коммита) |
| `APP_VERSION` (прод) | 2.58.10 → **2.58.11** (`config/settings.py:1715`) |
| Точка отката | тег `pre-round1025-hotfix8` → `a1e6db3` (локально и в `origin`; проверен) |
| Бэкапы (R18) | `var/backups/hotfix8-round1025-20260922-180028/` + `.env.bak.round1025-hotfix8` — **не удалялись** |

## Ход релиза

1. Локально (WC): bump `APP_VERSION` 2.58.10 → 2.58.11, синхронизированы `README.md` (`v2.58.11`) и версии-пины тестов; `?v=__APP_VERSION__` — без изменений (единый источник), инвалидация WebView = bump + рестарт.
2. Проверки WC: `node --check web/app.js` + `telegram-init.js` OK; JS-маркер **`HOTFIX8-SHELL-AURORA-OK`**; целевые pytest **162 passed**; полный pytest **8272 passed / 0 failed**; `git diff --check` exit 0; скан диффа/untracked на секреты — 0 находок.
3. Коммиты `98551b2` → `5124522` → `1a8ed18`; `git push origin master` → `a1e6db3..1a8ed18` (exit 0, без force).
4. Прод: `git fetch` → `git pull --ff-only` → **fast-forward** `af137cd..1a8ed18`; рабочее дерево чистое (tracked — без изменений).
5. Прод: `sudo -n systemctl restart admin_bot` → **active (running)**, `Main PID 110149`, старт `06:47:44 UTC`.
6. Пост-рестартные проверки (см. ниже).

## Проверки (фактические)

| Проверка | Результат |
|---|---|
| `systemctl status admin_bot` | **active (running)**, SubState=running, `Main PID 110149` |
| `GET http://127.0.0.1:8000/api/health` | **HTTP 200** |
| `GET /healthz` | **200**, тело `{"status":"ok","version":"2.58.11"}` |
| `APP_VERSION` в прод-дереве | **2.58.11** (`config/settings.py:1715`) |
| served HTML — ассеты | `app.css?v=2.58.11`, `app.js?v=2.58.11` |
| Плейсхолдер `__APP_VERSION__` в отдаваемом HTML | **0** (заменён) |
| Маркеры shell v3/aurora в отдаваемых ассетах | CSS: `--shell-bg`×15, `@keyframes aurora`×7, `bg-wash-legacy`×4; JS: `UI_SHELL_V3`×1, `UI_AURORA_BG_ENABLED`×2 |
| `database is locked` (пост-рестарт, последние 400 строк журнала) | **0** |
| `Traceback` / `ERROR` (пост-рестарт) | **0 / 0** |
| Лог старта | `Start polling` (`@PERMsoc_bot`), `lifespan started | pg_available=True` |

> Исторический полный журнал (~174k строк) содержит старые записи прошлых раундов; метрики выше считаны только по пост-рестартному окну (`06:47:44 UTC` →).

## Схема данных и инварианты

- **Δ DDL = 0**, миграции не запускались (SQLite `user_version` не менялся). Изменения клиентские (`app.css`/`app.js`/`index.html`) + аддитивные (`web/api/routes.py` — флаги в `ui_flags`), `config/settings.py` (+2 env-only `ClassVar`, bump), `.env.example`, README, тесты, план-доки.
- **Δ каталога = 0** (459/98/96/21/418); новые флаги — вне `param_catalog` (env-only, default ON, доставка `GET /api/me.ui_flags`, наружу только bool).
- Progressive delivery 10/50/100 % не применяется (один прод, прецедент §53–§59); поставка = bump `APP_VERSION` + cache-bust `?v=__APP_VERSION__`.
- Секреты не цитировались (R17/R18).

## Откат

- **Hard rollback:** `git revert 98551b2 5124522` (или `git checkout pre-round1025-hotfix8` → `a1e6db3`) + `sudo systemctl restart admin_bot`.
- **Soft rollback без редеплоя (env-only, default ON):** `UI_SHELL_V3=false` (значения `--shell-*` hotfix7; цветная линза не возвращается — её снятие часть исправления §1.2) и `UI_AURORA_BG_ENABLED=false` (прежний conic page-wash `body::before`). Требует рестарта.
- Тег `pre-round1025-hotfix8` → `a1e6db3`; бэкапы/теги/`stash@{0}` **не удалялись** (R18).

## Handoff

**RESULT: DEPLOYED — VERIFIED.** HOTFIX8 `hotfix8-shell-glass-aurora-round1025` выкачена на прод: fast-forward `af137cd..1a8ed18`, `admin_bot` active (Main PID 110149), `/api/health` 200, `/healthz`/`APP_VERSION` = **2.58.11**, served `?v=2.58.11`, маркеры shell v3/aurora присутствуют, `database is locked`=0, Traceback/ERROR=0. Открыт **только live-гейт владельца T-2776** (реальный Telegram WebView). Далее: @Architect — реконсиляция, @PM — закрытие, @Memory — метрики 10.25-HOTFIX8 + KG (Шаг 10, T-2789), затем **F6** `memory-analytics-reorg-round1025`.

---

## Приложение — baseline T-2745 (сохранено)

| Артефакт | Значение |
|---|---|
| Тег отката | `pre-round1025-hotfix8` → `a1e6db3141dc81843309400af66a06f363ddadd3` |
| Бэкап (git archive HEAD) | `var/backups/hotfix8-round1025-20260922-180028/` (5 файлов + `BASELINE.md`) |
| Бэкап окружения | `.env.bak.round1025-hotfix8` (размер/SHA256 == `.env`; содержимое не печаталось) |
| Baseline pytest | **8251 passed / 0 failed / 0 skipped** (1 warning Starlette, не блокер) |
| Baseline прочего | `APP_VERSION` **2.58.10**; JS **32/32** `node --check` OK; `git diff --check` 0; Δ DDL=0; Δ каталога=0 (459/98/96/21/418) |
| Git | ничего не коммитилось; `current_task.md`/`deploy_commands.txt` не изменялись (R18) |
