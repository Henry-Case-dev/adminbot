# deployment.md — hotfix7 `hotfix7-shell-glass-heartbeat-round1025`

> Шаг 9 (Deploy Phase) @DevOps, T-2690. Пакет прошёл @Reviewer **Approved** (итер. 2, `review.md`) и @Scanner **Critical 0 / High 0 / Medium 0** (`plans/reports/round1025_hotfix7_scanner_audit.md`); Merge §59 и архивация выполнены.

- **Результат:** `VERIFIED`
- **Окружение:** прод-VPS `racknerd-f4e3456` (`/var/www/admin_bot`), systemd-юнит `admin_bot` (`User=root`, `ExecStart=/var/www/admin_bot/venv/bin/python bot.py`), API на `127.0.0.1:8000`; публичный webapp `https://admin-bot.duckdns.org/web/`.
- **Дата деплоя:** 2026-09-22 (локально @DevOps). Серверная отметка старта сервиса — `Mon 2026-09-21 18:53:26 UTC` (серверный часовой пояс/сдвиг даты; логи первого старта 18:53:53 UTC).

## Артефакты

| Что | Значение |
|---|---|
| Коммит кода/тестов | `7073e34` — `fix(round1025): hotfix7 — … APP_VERSION 2.58.8` |
| Коммит планов | `a9cec67` — `docs(plans): round1025 hotfix7 — Merge §59 + архивация + Scanner-аудит/AA/аудит ТЗ` |
| Коммит деплой-док | `docs(deploy): round1025 hotfix7 — прод-деплой VERIFIED (APP_VERSION 2.58.8) + deployment.md` (этот файл; последний коммит `master`) |
| Push | `origin/master`: `5a5465c..a9cec67` (без force) |
| Задеплоенный HEAD | `a9cec67` (== `origin/master`) |
| `APP_VERSION` (дерево прода) | **2.58.8** |
| Тег отката | `pre-round1025-hotfix7` → `5a5465c` (не трогался) |
| Бэкапы | `hotfix7-round1025-20260922-052812/` сохранён; baseline-корректный `hotfix7-round1025-baseline-20260922-065606/` (см. §«Follow-up») |

## Ход релиза

1. Локально: прогоны перед коммитом — `node --check web/app.js` OK; `tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js` → `HOTFIX7-SHELL-GLASS-HEARTBEAT-OK`; целевые pytest **156 passed**; полный pytest **8207 passed / 0 failed**; `git diff --check` exit 0.
2. Локально: `git commit` ×2 (`7073e34`, `a9cec67`) → `git push origin master` → `5a5465c..a9cec67` (exit 0).
3. Прод до релиза: `HEAD=9f179a8`, `APP_VERSION=2.58.7`, `systemctl is-active admin_bot` = `active`; локально изменённых tracked-файлов нет (только untracked `info_text.md.bak.*`).
4. Прод: `git fetch` → `9f179a8..a9cec67`; `git pull --ff-only` → **fast-forward**, `HEAD=a9cec67` (без merge-конфликтов).
5. Прод: `sudo -n systemctl restart admin_bot` → exit 0; `active (running)`, `SubState=running`, `MainPID=4162467`.
6. Проверки после рестарта (§ниже). Первые ~7 сек процесс инициализировался (норма для старта бота).

## Проверки (фактические результаты)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active** |
| `GET http://127.0.0.1:8000/api/health` | **HTTP 200**, тело `{"status":"ok"}` |
| `APP_VERSION` в прод-дереве | **2.58.8** (`config/settings.py`) |
| `/` | 307 → `http://127.0.0.1:8000/web/` |
| `/web/` (index) | **200** |
| served HTML ссылается на ассеты | `app.css?v=2.58.8`, `app.js?v=2.58.8`, `telegram-init.js?v=2.58.8` |
| Плейсхолдер `__APP_VERSION__` в отдаваемом HTML | **0** (заменён) |
| `GET /static/app.css` | 200; маркер `--shell-h` ×19 (hotfix7 CSS реально отдан) |
| `GET /web/app.js` | 200; маркеры `_hbDrawPremium` ×2, `shellLayoutV2` ×1 (hotfix7 JS реально отдан) |
| `database is locked` в свежих логах юнита | **0** (из 147 строк `systemctl status`) |
| `Traceback` в логах после рестарта | **0** |
| `ERROR`/`CRITICAL` в логах после рестарта | **0** |
| «Bot started, listening…» / lifespan | 1 / 1 (успешный старт) |

> Источник логов: `journalctl` требует пароль sudo (sudoers разрешает только `systemctl`), поэтому свежие логи снимались через `systemctl status admin_bot --no-pager -n 5000`. Обрезано до 147 строк вокруг старта.

## Миграции

- **Δ DDL = 0**, миграций БД нет; SQLite `user_version` не менялся. Изменения — фронт (`app.css`/`app.js`/`index.html`), бэкенд-аддитив (`web/api/routes.py`), `config/settings.py` (+3 env-only `ClassVar`, bump версии), `.env.example`, README, тесты, инструмент матрицы.
- Новые env-флаги (default ON, Δ каталога = 0, доставка `GET /api/me.ui_flags`, только bool): `UI_SHELL_GLASS_V2`, `UI_HEARTBEAT_PREMIUM`, `UI_SHELL_LAYOUT_V2`.

## Откат (готовность)

- Hard rollback: `git revert <commit>` (или checkout `pre-round1025-hotfix7`) + `sudo systemctl restart admin_bot`.
- Soft rollback без редеплоя: env-флаги `UI_SHELL_LAYOUT_V2=false` (геометрия), `UI_SHELL_GLASS_V2=false` (shell-токены), `UI_HEARTBEAT_PREMIUM=false` (canvas-legacy); `UI_HEARTBEAT_CANVAS_ENABLED=false` → legacy SVG. Требует рестарта.
- Тег `pre-round1025-hotfix7` → `5a5465c`; бэкапы/теги/`stash@{0}` **не удалялись** (R18).

## Follow-up (bounded, из review.md F-1 Low / Scanner I-H7-1)

- Файловый бэкап `var/backups/hotfix7-round1025-20260922-052812/` содержал снимок **рабочего дерева итерации 1**, а не pre-hotfix7 baseline → **исправлено аддитивно**: создан корректный baseline `var/backups/hotfix7-round1025-baseline-20260922-065606/` (снимок `5a5465c` через `git archive`, с манифестом SHA256 и `BASELINE.md`); в исходный `BASELINE.md` добавлена явная пометка-поправка. Прежний каталог сохранён (R18), для восстановления baseline не использовать.
- Остальные Low (L-H7-1 мёртвый `@supports`-фолбэк shell; L-H7-2 OFF-путь header/DPR-cap; L-H7-3 AA worst-case 4.44:1) — **не блокеры**, остаются открытыми follow-up пакета.

## Ограничения / открытое

- **Live-гейт владельца T-2682** (реальный Telegram WebView: heartbeat в fullscreen, качество glass, FPS glow/specular, старое поведение без `dvh`) — **открыт**; headless/серверная проверка его не покрывает. Наследуемые live-гейты (T-2617 и др.) — также за владельцем.

## Security-замечание (не блокер релиза)

- Untracked-файл `deploy_commands.txt` (gitignored, `.gitignore:20`) содержит **plaintext-креды прода** (SSH-логин/пароль, IP, git-pull-пароль) и monitoring-токен. В коммиты/индекс/отчёты **не попал** (`git status --ignored` подтверждает; сканы диффа и untracked-планов чисты). Деплой выполнен по **SSH-ключу**, пароль не использовался. Рекомендация владельцу: **ротировать все указанные креды** и хранить через менеджер секретов. **✅ ЗАКРЫТО решением владельца (22.09.2026): `deploy_commands.txt` не трогать, ротация кредов НЕ выполняется** — осознанный отказ владельца от security-рекомендации @DevOps/@Scanner (не техдолг, действий не требует; KG `deploy_commands_policy_round1025`).
- `.env` / `.env.bak.round1025-*` — gitignored, содержимое не читалось/не печаталось; `LOGTAIL_SOURCE_TOKEN` в прод-`.env` присутствует (значение не выводилось).
