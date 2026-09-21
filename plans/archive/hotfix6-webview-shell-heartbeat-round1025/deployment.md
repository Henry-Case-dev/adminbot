# deployment.md — hotfix6 `hotfix6-webview-shell-heartbeat-round1025`

> Шаг 9 (Deploy Phase) @DevOps. Пакет прошёл @Reviewer **Approved** и @Scanner **Critical 0 / High 0**; Merge §58 и архивация выполнены.

- **Результат:** `VERIFIED`
- **Окружение:** прод-VPS `racknerd-f4e3456` (`/var/www/admin_bot`), systemd-юнит `admin_bot`, серверный порт API `8000`.
- **Дата деплоя:** 2026-09-22 (локально) / серверная отметка старта сервиса `2026-09-21 15:29:05 UTC`.

## Артефакты

| Что | Значение |
|---|---|
| Коммит кода/тестов | `055525c` — `fix(round1025): hotfix6 — … APP_VERSION 2.58.7` |
| Коммит планов | `ba75751` — `docs(plans): round1025 hotfix6 — Merge §58 + архивация + Scanner-аудит/AA-контраст` |
| Задеплоенный HEAD | `ba75751` (== `origin/master`) |
| `APP_VERSION` (в дереве) | `2.58.7` |
| Тег отката | `pre-round1025-hotfix6` |
| Бэкап | `var/backups/hotfix6-round1025-20260922-013551/` (не удалялся) |

## Ход релиза

1. Локально: `git commit` ×2 → `git push origin master` → `441e8f7..ba75751`.
2. Прод: `cd /var/www/admin_bot && git pull --ff-only` → **fast-forward** `4cde1bc..ba75751` (без merge-конфликтов).
3. Прод: `sudo -n systemctl restart admin_bot` → `active (running)`, Main PID `4121677`.
4. Health-check после рестарта — порт отдаёт ответ на первой повторной пробе (в первые ~5 сек процесс ещё инициализировался, что нормально для старта бота).

## Проверки (фактические результаты)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | `active` |
| `GET http://127.0.0.1:8000/api/health` | **HTTP 200** (`{"status":"ok"}`) |
| `APP_VERSION` в прод-дереве | **2.58.7** |
| served HTML (`/web/`) ссылается на ассеты | `app.css?v=2.58.7`, `app.js?v=2.58.7`, `telegram-init.js?v=2.58.7` |
| `GET /static/app.css?v=2.58.7` | 200 |
| `GET /web/app.js?v=2.58.7` | 200 |
| `GET /static/telegram-init.js?v=2.58.7` | 200 |
| Плейсхолдер `__APP_VERSION__` в отдаваемом HTML | 0 (заменён) |
| `database is locked` в логах юнита | **0** |
| `Traceback` в логах после рестарта | 0 |
| ERROR-строки в логах после рестарта | 0 |

## Миграции

- **Δ DDL = 0**, миграций БД нет; SQLite `user_version` не менялся. Изменения — код фронта/бэкенда + env-only флаги `UI_GLASS_TIER_OVERRIDE` / `UI_HEARTBEAT_CANVAS_ENABLED` / `UI_HEADER_COMPACT_V2` / `UI_LENS_MAX_NODES` (Δ каталога = 0, доставка через `GET /api/me.ui_flags`).

## Откат (готовность)

- Hard rollback: `git revert <commit>` (или checkout `pre-round1025-hotfix6`) + `systemctl restart admin_bot`.
- Soft rollback без редеплоя: env-флаги (`UI_HEARTBEAT_CANVAS_ENABLED=false` → legacy-SVG; `UI_HEADER_COMPACT_V2=false`; `UI_GLASS_TIER_OVERRIDE=a/b/c`).
- Бэкапы/теги/`stash@{0}` **не удалялись** (R18).

## Ограничения / открытое

- **Live-гейты владельца (T-2617 и ранее открытые T-2409/T-2505/T-2527):** реальный Telegram WebView (преломление линзы, стекло панелей, положение ⛶ vs нативные кнопки, fullscreen, FPS). Headless/серверная проверка их не покрывает — унаследованное ограничение.
- **Техдолг (не блокеры):** перф-замер линзы (M-H6-1), `role="img"`→button, скролл линзы, README-счётчик тестов.

## Security-замечание (не блокер релиза)

- Рабочий untracked-файл `deploy_commands.txt` (`.gitignore`) содержит plaintext-учётки/токены. В git/индекс/коммиты **не попал** (проверено `git status --ignored`, скан диффа — чисто). Рекомендация владельцу: хранить через менеджер секретов; ротация — по решению владельца (прецедент R17/UPD3 §4).
