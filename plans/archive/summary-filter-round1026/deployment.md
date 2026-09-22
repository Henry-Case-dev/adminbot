# deployment.md — S1 `summary-filter-round1026` (T-3157, Step 9 @DevOps — прод-поставка)

> **Feature:** `summary-filter-round1026` (Эпик 2, S1) · **Дата:** 2026-09-23 · **Оператор:** @DevOps
> **Базис:** HEAD до деплоя `01f3c57`; точка отката — annotated-тег **`pre-round1026-s1`**.
> **Предыдущая запись T-3129 (NOT_APPLICABLE)** — это блок 0 (baseline/точка отката), сохранена в истории git (коммиты `89bda3d`, `01f3c57`); ниже — фактический деплой рантайма S1.

## Вердикт: **VERIFIED**

Рантайм S1 доставлен на прод, сервис `active (running)`, `/api/health` = **200**, фактический `APP_VERSION` = **2.58.18**, `database is locked` = **0**, бот и саммари-планировщик стартуют без ошибок (новый модуль импортируется).

---

## 1. Среда

| Параметр | Значение |
|---|---|
| Среда | Прод (VPS), `nick@198.46.175.136`, рабочий каталог `/var/www/admin_bot` |
| Сервис | `admin_bot.service` (systemd), `WEB_PORT=8000`, публичный хост `admin-bot.duckdns.org` |
| Python | `venv` Python 3.12.3 |
| Доступ | SSH (пароль из локального gitignored `deploy_commands.txt`; `sudo -n` недоступен → sudo через PTY) |

## 2. Коммиты и push

| Что | Хеш | Сообщение |
|---|---|---|
| Код + тесты | `4cd4ae6` | `feat(round1026): S1 — алгоритмическая предфильтрация Саммари (summary_filter, каталог+8, per-chat tумблер, интеграция в L1-вход, логи FILTER_*, APP_VERSION 2.58.18)` |
| Планы/доки | `89bda3d` | `docs(plans): round1026 S1 — Merge §71 + архивация + Scanner-аудит (+переиздание F8 по ADR-1026-2)` |

- **Push:** `01f3c57..89bda3d  master -> master` (origin `Henry-Case-dev/adminbot`); `origin/master` = `89bda3d`. Force-push не использовался.
- **Тег отката:** `pre-round1026-s1` (annotated, tag-object `10a5c74` → `01f3c57`), присутствует в origin.
- `stash@{0}` не трогался (R18). `deploy_commands.txt` не изменялся.

## 3. Деплой (traceable)

- **Сервер до деплоя:** HEAD `e7170b7` (F11-merge), `APP_VERSION` 2.58.17, `admin_bot` — `active`.
  - *Примечание:* расхождение `e7170b7` vs локальный `01f3c57` — сервер отставал на 5 документных/тестовых коммитов; `pre-round1026-s1`(`01f3c57`) является потомком `e7170b7`, поэтому ff-only корректен.
- **Pull:** `cd /var/www/admin_bot && git pull --ff-only origin master` → `Updating e7170b7..89bda3d  Fast-forward` (94 files, +4442/−326). После pull HEAD = `89bda3d`. Ошибка ff-only не возникала (рабочее дерево чистое, кроме untracked `.bak`).
- **Restart:** `sudo systemctl restart admin_bot` → сервис вернулся `active (running)`, новый `MainPID`, `ActiveEnterTimestamp = 2026-09-22 23:16:26 UTC` (локально `2026-09-23 ~11:16 +12`).

## 4. Health / смоук-проверки (факт)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active (running)** ✅ |
| `GET /api/health` (127.0.0.1:8000) | **HTTP 200**, `{"status":"ok"}` ✅ |
| `GET /web/` | **HTTP 200** ✅ |
| served cache-bust | `?v=2.58.18` на ассетах `/web/` ✅ |
| `APP_VERSION` в дереве сервера | `"2.58.18"` (`config/settings.py`) ✅ |
| `database is locked` (journal, последние 600 строк) | **0** ✅ |
| Импорт нового рантайма: `import services.summary_filter, services.summary_generator` | `IMPORT_OK 1 True` (файл `summary_filter.py` загружен) ✅ |
| Старт бота | `Start polling for bot @PERMsoc_bot`, роутеры зарегистрированы ✅ |
| Старт саммари-планировщика | `SmartModule scheduler started (cron 0,6,12,18 Asia/Yekaterinburg)` ✅ |
| Миграции | не запускались; **Δ DDL=0** (схема не тронута) ✅ |

## 5. Инварианты

- Δ DDL=0 (схема/миграции вне diff); Δ каталога — санкция ADR-1026-1 D1 (ровно +8/+2, итог 467/426/442/100/98/21).
- Публикация/промпты/XML — вне diff (D4-гейт); ровно 2 LLM-вызова; CSP/zero-build; R17/R18.
- Корректность кода подтверждена @Reviewer `Approved` (итер.2) и @Scanner C0/H0/M0/L1; локальный CI `.venv` pytest **8501/0**, JS **42/42**, `git diff --check` = 0.

## 6. Откат (готовность)

- **Жёсткий:** `git checkout pre-round1026-s1` (tag `10a5c74`→`01f3c57`) + `sudo systemctl restart admin_bot` → снятие модуля `summary_filter` и врезки в `_run`.
- **Мягкий (hot, без рестарта):** флаг каталога `flags.summary_filter_enabled=false` (OFF) → фильтр не вызывается, `xml.build(rows)` — **байт-в-байт** прежний вход L1.
- Бэкапы: `var/backups/s1-round1026-*`, `.env.bak.round1026-s1` — сохранены (R18).

## 7. Остаточные наблюдения (честно, non-blocking)

1. **Stop-фаза рестарта:** при остановке прошлого процесса systemd зафиксировал `Failed to kill control group ... Invalid argument` и `Failed with result 'timeout'` — graceful-shutdown превысил `TimeoutStopSec`, systemd эскалировал; новый процесс стартовал чисто и сервис `active`. Похоже на присущую боту задержку остановки (polling/uvicorn/пулы), S1 её не меняет. Рекомендуется понаблюдать и при повторе разобрать порядок shutdown (отдельная задача, не блокер S1).
2. **Гигиена секретов:** в диффе коммитов секретов нет. Локальный `deploy_commands.txt` (gitignored) хранит SSH-креды в открытом виде — рекомендован перевод в secret-manager/env и **ротация** (вне рамок S1).

## 8. Явная оговорка приёмки

**HTTP 200 и старт сервиса ≠ корректная работа самого фильтра.** Проверено только: поставка кода, загрузка модуля, старт компонентов, отсутствие ошибок импорта/блокировок БД. **Live-проверка алгоритма фильтра** (per-chat ON/OFF, качество отсева на реальном окне, `FILTER_*`-логи с `run_id`, сохранность публикации) — **PENDING OWNER VERIFICATION (D4)**, выполняется владельцем в проде профильным сценарием.

---

## Handoff
**RESULT: VERIFIED — `summary-filter-round1026` S1 @Orchestrator** — коммиты `4cd4ae6`/`89bda3d` запушены (`01f3c57..89bda3d`), сервер `e7170b7..89bda3d` **ff-only**, `admin_bot` **active**, `/api/health` **200**, `APP_VERSION` **2.58.18**, served `?v=2.58.18`, `database is locked` **0**, бот/саммари-планировщик стартуют, новый модуль импортируется, Δ DDL=0. Откат: тег `pre-round1026-s1`(→`01f3c57`) + soft-флаг `flags.summary_filter_enabled=OFF`. Дальше: @Orchestrator — Architect reconciliation §71, PM-архив, Memory sync, metrics, следующий F. **Live-корректность фильтра — на OWNER (D4).**
