# deployment.md — F5 `module-workspace-tabs-round1025`

> Шаг 9 (Deploy Phase) @DevOps, T-2741. Пакет прошёл @Reviewer **Approved** (`review.md`) и @Scanner **Critical 0 / High 0 / Medium 0 / Low 0** (`plans/reports/round1025_f5_scanner_audit.md`); Merge §61 и архивация выполнены (commit `0d3ea40`).

- **Результат:** `VERIFIED`
- **Окружение:** прод-VPS `racknerd-f4e3456` (`/var/www/admin_bot`), systemd-юнит `admin_bot` (`User=root`, `ExecStart=/var/www/admin_bot/venv/bin/python bot.py`), API на `127.0.0.1:8000`; публичный webapp `https://admin-bot.duckdns.org/web/`.
- **Дата деплоя:** 2026-09-22 (локально @DevOps, `+12:00`, 17:47). Серверная отметка старта сервиса — `Tue 2026-09-22 05:45:46 UTC` (совпадает: локальное 17:45 `+12:00`). Расхождения часов нет.

## Артефакты

| Что | Значение |
|---|---|
| Коммит кода/тестов | `63dddd3` — `feat(round1025): F5 — workspace модулей (маршруты/табы), библиотека промптов (один источник), модели/подключения §49, §84/§85 UI, APP_VERSION 2.58.10` |
| Коммит планов | `0d3ea40` — `docs(plans): round1025 F5 — Merge §61 + архивация + Scanner-аудит` |
| Коммит деплой-док | `docs(deploy): round1025 F5 — прод-деплой VERIFIED (APP_VERSION 2.58.10) + deployment.md` (этот файл; последний коммит `master`) |
| Push | `origin/master`: `12a55bb..0d3ea40` (без force) |
| Задеплоенный HEAD | `0d3ea40` (== `origin/master` на момент `git pull`) |
| `APP_VERSION` (дерево прода) | **2.58.10** |
| Тег отката | `pre-round1025-f5` (не трогался; прилетел на прод при `git fetch` — сохранён) |
| Бэкапы | `.env.bak.round1025-f5` (gitignored, локально); **не удалялись** (R18) |

## Ход релиза

1. **Локально, до коммита:** `git status` / `git diff --stat` — 22 tracked-изменения + 5 untracked (архив, 2 отчёта, 3 новых JS-теста, 1 новый Python-тест). Сканы диффа и untracked на секреты — **0 находок**; в индекс не попали `.env*`, `current_task.md`, `web.zip`, скриншоты, `deploy_commands.txt`, `var/backups`, `tools/_ui_*` (последние gitignored).
2. **Локально, тесты:** целевые F5 (`test_webapp_f5_round1025` + `js_unit` + `design_tokens` + `scope_selector` + `round1011_ui`) → **120 passed / 0 failed** за 3.74 с (`node` недоступен — JS-unit помечены skip, как в прошлых раундах).
3. **Локально:** `git commit` ×2 (`63dddd3` код+тесты, 18 файлов; `0d3ea40` планы, 15 файлов с переносом `plans/features/.../tasks.md` → `plans/archive/.../tasks.md`) → `git push origin master` → `12a55bb..0d3ea40` (exit 0).
4. **Прод до релиза:** `HEAD=28eb02d`, `systemctl is-active admin_bot` = `active`; tracked-изменений нет (только untracked `info_text.md.bak.*`).
5. **Прод:** `git fetch origin` → `28eb02d..0d3ea40` (+ tag `pre-round1025-f5`); `git pull --ff-only origin master` → **Fast-forward** `28eb02d..0d3ea40`, конфликтов нет, `HEAD=0d3ea40`.
6. **Прод:** `systemctl restart admin_bot` (sudo) → процесс инициализировался; `ActiveEnterTimestamp=Tue 2026-09-22 05:45:46 UTC`.
7. **Проверки после рестарта** — см. таблицу.

## Проверки (фактические результаты)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active** |
| `MainPID` / `NRestarts` / `ActiveEnterTimestamp` | `96796` / `0` / `Tue 2026-09-22 05:45:46 UTC` |
| `GET http://127.0.0.1:8000/api/health` | **HTTP 200** |
| `GET http://127.0.0.1:8000/healthz` | **200**, тело `{"status":"ok","version":"2.58.10"}` |
| `APP_VERSION` в прод-дереве | **2.58.10** (`config/settings.py:1702`) |
| `/` | 307 → `http://127.0.0.1:8000/web/` |
| served HTML ссылается на ассеты | `app.css?v=2.58.10`, `app.js?v=2.58.10` |
| `GET /web/app.js?v=2.58.10` | **200**; F5-маркер `promptLibrary` присутствует (библиотека промптов реально отдана) |
| `database is locked` в свежих логах юнита | **0** (из последних 3000 строк `systemctl status`) |
| `Traceback` в логах после рестарта | **0** |

> Источник логов: `journalctl` требует пароль sudo, поэтому свежие логи снимались через `systemctl status admin_bot --no-pager -n 3000`.

## Миграции

- **Δ DDL = 0**, миграций БД нет; SQLite `user_version` не менялся. Изменения — фронт (`app.js`/`index.html`/`app.css`) + `config/settings.py` (bump версии) + `README.md` + тулинг (`tools/ui_round1025_matrix.py`) + тесты/планы. `services/`, `web/api/`, миграции, `bot.py`, `handlers/**` — вне диффа.

## Откат (готовность)

- Hard rollback: `git revert <commit>` (или `git checkout pre-round1025-f5`) + `systemctl restart admin_bot`.
- Тег `pre-round1025-f5` присутствует на проде; бэкапы/теги/`stash@{0}` **не удалялись** (R18). Force-push не выполнялся.
- Изменения чисто клиентские/аддитивные (UI «Модули» + bump версии) — откат не затрагивает схему данных.

## Ограничения / открытое

- **Live-гейт владельца (реальный Telegram WebView)** — **открыт**: маршруты/вкладки workspace, библиотека промптов, модели/подключения §49 и UI §84/§85 на живом TMA серверной проверкой не покрываются. Наследуемые live-гейты — также за владельцем.
- Follow-up-замечания @Scanner (Low/Info) зафиксированы в `plans/reports/round1025_f5_scanner_audit.md`; релиз-блокеров нет.

## Security-замечание (не блокер релиза)

- `deploy_commands.txt` (gitignored) в коммиты/индекс/отчёты **не попал**, не изменялся (R17/R18-политика владельца «не трогать»). Деплой выполнен по **SSH-ключу** (`nik@racknerd-f4e3456`); при `systemctl restart` sudo запросил пароль — использован из `deploy_commands.txt` через переменную, в логи/отчёты **не печатался**.
- `.env` / `.env.bak.round1025-*` — gitignored; содержимое не читалось/не печаталось.

## Handoff

**RESULT: DEPLOYED — VERIFIED.** F5 `module-workspace-tabs-round1025` задеплоена на прод (`0d3ea40`): fast-forward, `admin_bot` active, health 200, `healthz`/`APP_VERSION` = **2.58.10**, served `?v=2.58.10`, `database is locked` = 0. Следующие шаги: @Architect — реконсиляция, @PM — архивация/закрытие задач, @Memory — синк KG/метрик (Шаг 10). Открыт только live-гейт владельца.
