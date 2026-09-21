# deployment.md — F4 `module-catalog-quickpanel-store-round1025`

> Шаг 9 (Deploy Phase) @DevOps, T-2655. Пакет прошёл @Reviewer **Approved** (`review.md`, итер. 2) и @Scanner **Critical 0 / High 0 / Medium 0** (`plans/reports/round1025_f4_scanner_audit.md`); Merge §60 и архивация выполнены (commit `28eb02d`).

- **Результат:** `VERIFIED`
- **Окружение:** прод-VPS `racknerd-f4e3456` (`/var/www/admin_bot`), systemd-юнит `admin_bot` (`User=root`, `ExecStart=/var/www/admin_bot/venv/bin/python bot.py`), API на `127.0.0.1:8000`; публичный webapp `https://admin-bot.duckdns.org/web/`.
- **Дата деплоя:** 2026-09-22 (локально @DevOps, `+12:00`). Серверная отметка старта сервиса — `Mon 2026-09-21 21:34:03 UTC`; логи старта бота — `2026-09-21 21:34:24 UTC` (совпадает: локальное 09:34 `+12:00`). Расхождения часов нет.

## Артефакты

| Что | Значение |
|---|---|
| Коммит кода/тестов | `7f9fed1` — `feat(round1025): F4 — каталог модулей, панель избранного, ModuleConfigurationStore, единая мутация/откат §40–§42, APP_VERSION 2.58.9` |
| Коммит планов | `28eb02d` — `docs(plans): round1025 F4 — Merge §60 + архивация + Scanner-аудит` |
| Коммит деплой-док | `docs(deploy): round1025 F4 — прод-деплой VERIFIED (APP_VERSION 2.58.9) + deployment.md` (этот файл; последний коммит `master`) |
| Push | `origin/master`: `b5f8348..28eb02d` (без force) |
| Задеплоенный HEAD | `28eb02d` (== `origin/master` на момент `git pull`) |
| `APP_VERSION` (дерево прода) | **2.58.9** |
| Тег отката | `pre-round1025-f4` → `b5f8348` (не трогался; на прод прилетел при `git fetch` — сохранён) |
| Бэкапы | `var/backups/f4-round1025-20260922-073051/` (локально), `f4` `.env.bak.round1025-f4`; **не удалялись** (R18) |

## Ход релиза

1. **Локально, до коммита:** `git diff --check` exit 0; сканы диффа и untracked на секреты — **0 находок** (нет `.env*`, zip, скриншотов, `var/backups`, `deploy_commands.txt` в индексе); `node --check web/app.js` → OK; `node tests/js/round1025_f4_module_store_test.js` → `MODULE-STORE-OK`; `node tests/js/round1025_f4_catalog_ui_test.js` → `MODULE-CATALOG-OK`.
2. **Локально, тесты:** целевые (`test_webapp_f4_round1025` + `js_unit` + `nav_disclosure_ui` + `scope_selector` + `design_tokens` + `hotfix6` + `hotfix7`) → **172 passed**; полный `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` → **8229 passed / 0 failed** (1 сторонний `StarletteDeprecationWarning`, 105.8 с).
3. **Локально:** `git commit` ×2 (`7f9fed1` код+тесты, 15 файлов; `28eb02d` планы, 16 файлов с `R077`-переименованием `plans/features/.../tasks.md` → `plans/archive/.../tasks.md`) → `git push origin master` → `b5f8348..28eb02d` (exit 0).
4. **Прод до релиза:** `HEAD=2a67829`, `APP_VERSION=2.58.8`, `systemctl is-active admin_bot` = `active`, health 200; tracked-изменений нет.
5. **Прод:** `git fetch --prune origin` → `2a67829..28eb02d` (+ tag `pre-round1025-f4`); `git pull --ff-only` → **Fast-forward** `2a67829..28eb02d`, конфликтов нет.
6. **Прод:** `sudo -n systemctl restart admin_bot` → exit 0; процесс инициализировался ~16 с (health `000` на 1–2 попытках — норма старта бота), затем **200**.
7. **Проверки после рестарта** — см. таблицу. Первые ~16 сек процесс поднимался.

## Проверки (фактические результаты)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active** |
| `MainPID` / `NRestarts` / `ActiveEnterTimestamp` | `807` / `0` / `Mon 2026-09-21 21:34:03 UTC` |
| `GET http://127.0.0.1:8000/api/health` | **HTTP 200**, тело `{"status":"ok"}` |
| `GET http://127.0.0.1:8000/healthz` | **200**, тело `{"status":"ok","version":"2.58.9"}` |
| `APP_VERSION` в прод-дереве | **2.58.9** (`config/settings.py:1702`) |
| `/` | 307 → `http://127.0.0.1:8000/web/` |
| `/web/` (index) | **200** |
| served HTML ссылается на ассеты | `app.css?v=2.58.9`, `app.js?v=2.58.9`, `telegram-init.js?v=2.58.9` |
| Плейсхолдер `__APP_VERSION__` в отдаваемом HTML | **0** (заменён) |
| `GET /static/app.css?v=2.58.9` | **200**; маркеры `module-catalog` ×4, `module-quick` ×9 (F4 CSS реально отдан) |
| `GET /web/app.js?v=2.58.9` | **200**; маркеры `ModuleConfigurationStore` ×2, `_moduleRuntimeState` ×2 (F4 JS реально отдан) |
| served index: F4-маркеры | `module-catalog` ×1, `module-quick` ×5 |
| `database is locked` в свежих логах юнита | **0** (из 142 строк `systemctl status`) |
| `Traceback` в логах после рестарта | **0** |
| `ERROR`/`CRITICAL` в логах после рестарта | **0** |
| `Bot started, listening…` / `lifespan started` | 2 / 1 (успешный старт; `pg_available=True`) |

> Источник логов: `journalctl` требует пароль sudo (sudoers разрешает только `systemctl`), поэтому свежие логи снимались через `systemctl status admin_bot --no-pager -n 3000` (обрезано до 142 строк вокруг старта).

## Миграции

- **Δ DDL = 0**, миграций БД нет; SQLite `user_version` не менялся. Изменения — фронт (`app.js`/`index.html`/`app.css`) + `config/settings.py` (bump версии) + README + тесты/планы. `services/`, `web/api/`, миграции, `bot.py`, `handlers/**` — вне диффа. Δ каталога = 0 (`REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418`).

## Откат (готовность)

- Hard rollback: `git revert <commit>` (или `git checkout pre-round1025-f4`) + `sudo systemctl restart admin_bot`.
- Тег `pre-round1025-f4` → `b5f8348`; бэкапы/теги/`stash@{0}` **не удалялись** (R18). Force-push не выполнялся.
- Изменения чисто клиентские/аддитивные (UI «Модули» + bump версии) — откат не затрагивает схему данных.

## Ограничения / открытое

- **Live-гейт владельца (реальный Telegram WebView)** — **открыт**: панель избранного, каталог/сетка модулей, отзывчивость тумблеров и фактическое состояние модулей на живом TMA серверной проверкой не покрываются. Наследуемые live-гейты (T-2682 и др.) — также за владельцем.
- **Follow-up (Low, не блокеры):** L-F4S-1 (`stickyFailedKeys` протекает между областями в счётчиках), L-F4S-2 (родительский гейт сравнивается по эффективному, а не глобальному значению); Info — kill-switch Сна/Ностальгии вне `REGISTRY`, Playwright-матрица и живой TMA не воспроизводились @Scanner. См. `plans/reports/round1025_f4_scanner_audit.md` §2.

## Security-замечание (не блокер релиза)

- Untracked `deploy_commands.txt` (gitignored, `.gitignore`) с plaintext-кредами прода в коммиты/индекс/отчёты **не попал** (сканы диффа и untracked чисты; файл не читался — R17). Деплой выполнен по **SSH-ключу** (`nik@racknerd-f4e3456`), пароль не использовался. Рекомендация владельцу о ротации **отклонена владельцем** (решение 22.09.2026: `deploy_commands.txt` не трогать; KG `deploy_commands_policy_round1025`, AcceptedDecision) — @DevOps зафиксировал и не исполняет.
- `.env` / `.env.bak.round1025-*` — gitignored; содержимое не читалось/не печаталось.

## Handoff

**RESULT: DEPLOYED — VERIFIED.** F4 `module-catalog-quickpanel-store-round1025` задеплоена на прод (`28eb02d`): fast-forward, `admin_bot` active, health 200, `APP_VERSION`/`healthz` = **2.58.9**, served `?v=2.58.9`, `database is locked` = 0. Следующие шаги: @Architect — реконсиляция, @PM — архивация/закрытие задач, @Memory — синк KG/метрик (Шаг 10). Открыт только live-гейт владельца.
