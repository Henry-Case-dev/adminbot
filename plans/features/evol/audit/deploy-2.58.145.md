# EVOL — выпуск 2.58.145: система контролов, клавиатурная адаптация, честный прогресс/моушен

Дата: 31.10.2026, 16:13–16:21 UTC (новый VPS `192.255.209.205`). Роль: DevOps.
Итог: **успешный выпуск, прод на 2.58.145 @ `4bf3604a`.**

## 1. Привязка выпуска

| Параметр | Значение |
|---|---|
| `DEPLOY_SOURCE` | commit `4bf3604a3f79c3c0ad91b9bbac12ab750c7cb3ad` (ветка `release/2.58.145`) |
| Reviewed candidate | `c89b08ef` (EVOL-043 review-fix; EVOL-043/044/045 приняты Reviewer) |
| Bump-коммит | `4bf3604a` (2.58.144 → 2.58.145; 31 файл / 32 вхождения, набор пин-файлов идентичен 2.58.144) |
| Предыдущий прод (baseline) | `ebec502b` — 2.58.144, SQLite `user_version=40` |
| FF-проверка | `git merge-base --is-ancestor ebec502b 4bf3604a` → OK (сервер: `FF_OK`) |
| Push | `origin/release/2.58.145` = `4bf3604a` (проверено `ls-remote`) |
| `MUTABLE_WORKTREE_REQUIRED` | **no** — сборка из чистого worktree на `c89b08ef`, правка только пин-файлов; изменённые `web/**` из общей ветки в релиз не попали (`git diff c89b08ef HEAD -- web/` = 0 файлов) |
| Write scope на проде | `git checkout -B release/2.58.145`, ветка/HEAD; файлов приложения деплой не меняет |
| Схема/миграции | Δ DDL = 0 (`user_version` остаётся 40), Δ внешних зависимостей = 0 |

Проверки до выпуска: `compileall` rc=0; node 5/5 OK (4 hotfix-пина + `asap_ui02_status_ribbons`);
pin-pytest **868 passed, 0 failed**; тесты выпускаемых фич — `test_webapp_evol_w11_controls.py` 41 passed + `evol_w11_controls_test.js` OK.

## 2. Ход выпуска (3 SSH-подключения: recon + основной прогон + контрольный, fail2ban-режим)

- **recon 16:13:47 UTC**: `HEAD=ebec502b`, ветка `release/2.58.144`, dirty=1 (`?? .cache/` — неотслеживаемый, пре-существующий), сервис `active`, `MainPID=781799`, `NRestarts=0`, `/healthz` 200 `2.58.144`, публичный HTTPS 200, ошибок за 30 мин нет, диск 21%.
- **основной прогон 16:15:19 UTC**: fetch → `origin/release/2.58.145 = 4bf3604a` → `FF_OK` → снимок БД `/tmp/predeploy-258145.db` (1 679 773 696 Б) → `git checkout -B release/2.58.145 origin/release/2.58.145` → `HEAD=4bf3604a` (совпал с кандидатом) → `systemctl restart admin_bot` (16:15:37 UTC).
- **контрольный прогон 16:20:29 UTC** (через ~5 мин): состояние стабильно, `MainPID=801759` тот же, `NRestarts=0`.

## 3. Проверки после выпуска

| Проверка | Результат |
|---|---|
| `/healthz` | **200** `{"status":"ok","version":"2.58.145"}` (локально и по публичному HTTPS) |
| `/web/` | **200**, 1 072 450 Б |
| `/api/health` (127.0.0.1:8000) | **200** |
| Сервис | `active`, `MainPID=801759`, **`NRestarts=0`** (за 8 мин наблюдения) |
| Число процессов | **1** (`/var/www/admin_bot/venv/bin/python /var/www/admin_bot/bot.py`) |
| Ошибки | `Traceback/ERROR` за 8 мин — **0**; WARNING — нет |
| SQLite | `user_version=40` (без изменений), `quick_check` = ok |
| Media | tracked 65, каталогов 7 — без изменений |
| Git на проде | `4bf3604a`, ветка `release/2.58.145`, dirty=1 (тот же `?? .cache/`) |

## 4. Смоук развёрнутых ассетов (только чтение, без отправок в Telegram)

| Актив | Проверка |
|---|---|
| `/static/app.css` | 359 441 Б, sha256 `990864351064C17A…` — **байт-в-байт** с `web/static/app.css` кандидата |
| `/web/app.js` | 1 548 790 Б, sha256 `98FCCE9007318855…` — **байт-в-байт** с `web/app.js` кандидата |
| `/web/` (HTML) | отличается от `web/index.html` кандидата только подстановкой `__APP_VERSION__` → `2.58.145` (15 подстановок, −105 Б) |
| Маркеры EVOL-043 (контролы) | `ctl-toggle` 45 в HTML / 26 в CSS, `ctl-progress` 25 / 51, `--ctl-` 98 в CSS |
| Маркеры EVOL-044 (клавиатура) | `--motion-` 25, `kb-offset` 20, `vv-h` 5, `kb-open` 4 в CSS; `visualViewport` 18 в JS |
| Маркеры EVOL-045 (прогресс) | `_ctlProgressModel` 12 в развёрнутом JS, `role="progressbar"` 11, `data-state` 11 |

Отправок в Telegram не производилось (только HTTPS GET, git и systemctl).

## 5. Откат

- Цель: `ebec502b` (2.58.144), схема та же (v40) → откат схемо-безопасен.
- Механика: `git checkout -B release/2.58.144 ebec502b` + `systemctl restart admin_bot` + повторный `/healthz` (ожидается `2.58.144`).
- Снимок БД до выпуска: `/tmp/predeploy-258145.db` (1 679 773 696 Б).
- Текущее состояние: откат не потребовался, предыдущая версия остаётся доступной в `origin/release/2.58.144`.

## 6. Замечания

- Накопленные правки репозитория в общей ветке (`plans/**`, скриншоты других лент) в релиз не включались — сборка шла из чистого worktree на принятом коммите.
- Функциональная приёмка UI/поведения — за Reviewer; здесь подтверждена только идентичность и работоспособность развёрнутого артефакта.
