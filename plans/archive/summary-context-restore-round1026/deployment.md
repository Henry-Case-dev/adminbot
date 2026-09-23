# deployment.md — S2 `summary-context-restore-round1026` (T-3250, Шаг 9 @DevOps — прод-поставка)

> **Feature:** `summary-context-restore-round1026` (Эпик 2, S2, §90–§92/§107/§109) · **Дата:** 2026-09-23 · **Оператор:** @DevOps
> **Базис:** локальный/`origin` HEAD до деплоя `7895e77`; прод до деплоя `54c6445`. Точка отката — annotated-тег **`pre-round1026-s2`** (tag-object `8aa7b2b9` → `7895e77`).
> **Предусловия:** @Reviewer **Approved** (T-3245), @Scanner **C0/H0/M0/L2/I2 → к деплою ДА** (T-3246), Merge §73 @Architect (T-3248), архивация @PM (T-3249).

## Вердикт: **VERIFIED**

Рантайм S2 доставлен на прод, сервис `active (running)`, `/api/health` = **200**, фактический `APP_VERSION` = **2.58.21**, served `?v=2.58.21`, `database is locked` = **0**, новый модуль импортируется, планировщик Саммари стартует без ошибок.

---

## 1. Среда

| Параметр | Значение |
|---|---|
| Среда | Прод (VPS), `nick@198.46.175.136`, рабочий каталог `/var/www/admin_bot` |
| Сервис | `admin_bot.service` (systemd), `WEB_PORT=8000`, публичный хост `admin-bot.duckdns.org` |
| Python | `/var/www/admin_bot/venv/bin/python` (Python 3.12) |
| Доступ | SSH (ключ, BatchMode); `sudo -n` недоступен → sudo через PTY |

## 2. Коммиты и push

| Что | Хеш | Сообщение |
|---|---|---|
| Код + тесты | `eda7325` | `feat(round1026): S2 — восстановление контекста Саммари (summary_context_restore, reply-родители через thread_chain, соседи/cap/бюджет, §91/§92, RESTORE_* логи, APP_VERSION 2.58.21)` |
| Планы/доки | `6fa456c` | `docs(plans): round1026 S2 — Merge §73 + архивация + Scanner-аудит` |

- **Push:** `7895e77..6fa456c  master -> master` (origin `Henry-Case-dev/adminbot`); `origin/master` = `6fa456c`. **Force-push не использовался.**
- **Тег отката:** `pre-round1026-s2` (annotated, `8aa7b2b9` → commit `7895e77`), присутствует в `origin`; на прод догружен `git fetch --tags` (rollback-готовность на сервере подтверждена).
- `stash@{0}` не трогался (R18). `deploy_commands.txt` не изменялся.

## 3. Деплой (traceable)

- **Сервер до деплоя:** HEAD `54c6445` (визуальный эпик round1026), `APP_VERSION` 2.58.20, `admin_bot` — `active`.
  - *Примечание:* сервер отставал от `origin` на 1 коммит (`7895e77` — финальная синхронизация визуального эпика; `plans/workflow_state.md`/`plans/metrics.md` обновлены именно там). `54c6445` — предок `7895e77`, поэтому `--ff-only` корректен.
- **Pull:** `cd /var/www/admin_bot && git pull --ff-only origin master` → `Updating 54c6445..6fa456c  Fast-forward` (40 files, +2115/−64). После pull HEAD = `6fa456c`. Ошибка ff-only не возникала (рабочее дерево чистое, кроме untracked `.bak`).
- **Restart:** `sudo systemctl restart admin_bot` → сервис `active (running)`, новый `MainPID` = `384601`, `ActiveEnterTimestamp = 2026-09-23 05:39:59 UTC`.

## 4. Health / смоук-проверки (факт)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active (running)** ✅ |
| `GET /api/health` (127.0.0.1:8000) | **HTTP 200**, `{"status":"ok"}` ✅ |
| `GET /web/` | **HTTP 200** ✅ |
| served cache-bust | `?v=2.58.21` на ассетах `/web/` ✅ |
| `APP_VERSION` (дерево сервера, `config/settings.py`) | `"2.58.21"` ✅ |
| `database is locked` (journal, последние ~900 строк) | **0** ✅ |
| Импорт нового рантайма: `import services.summary_context_restore, services.summary_generator` | `IMPORT_OK True True` (модуль `summary_context_restore.py` загружен, `SummaryGenerator` доступен) ✅ |
| Старт бота | `Run polling for bot @PERMsoc_bot id=8802473181` ✅ |
| Старт саммари-планировщика | `services.summary_scheduler - SmartModule scheduler started (cron 0,6,12,18 Asia/Yekaterinburg)` ✅ |
| Ошибки старта (`Traceback`/`CRITICAL`/`ImportError`) | **0** ✅ |
| Миграции | не запускались; **Δ DDL=0** (схема не тронута) ✅ |

## 5. Инварианты

- Δ DDL=0 (схема/миграции вне diff); Δ каталога=0 (`param_catalog.py` вне diff; REGISTRY 467 / GROUPS 100 / `_TAB_BY_GROUP` 98 / TAB_RULES 21 / Settings 426).
- Публикация/промпты/XML — вне diff (D4-гейт: `summary_xml.py`, `summary_prompts.py`, `image_generation.py`, `telegram_send.py` не тронуты); ровно 2 LLM-вызова; CSP/zero-build; R17 (логи `RESTORE_*` без контента)/R18.
- Локальный CI `.venv`: pytest **8569/0** (1 warning, deprecation), JS **43/43**, `git diff --check` = 0, импорт `services.summary_context_restore` OK.

## 6. Откат (готовность)

- **Жёсткий:** `git checkout pre-round1026-s2` (tag `8aa7b2b9`→`7895e77`) + `sudo systemctl restart admin_bot` → снятие модуля `summary_context_restore` и врезки в `_apply_filter`.
- **Мягкий (hot, без рестарта):** флаг каталога `flags.summary_filter_reply_context_enabled=false` (OFF) → S2 не вызывается, XML-вход = `FilterResult.kept` — **байт-в-байт** прежний вход S1. Резервный мастер-тумблер: `flags.summary_filter_enabled=false`.
- Бэкапы/теги: `var/backups/s2-round1026-*`, `.env.bak.round1026-s2`, тег `pre-round1026-s2` — сохранены (R18); `stash@{0}` цел.

## 7. Остаточные наблюдения (честно, non-blocking)

1. **Наполнение `bot_replies` в проде** влияет на реальный проход reply-цепочек (follow-up @Reviewer/@Scanner L-R1026S2-1/-2) — проверяется live-сценарием, не деплоем.
2. **Гигиена секретов:** в диффе коммитов секретов нет. Локальный `deploy_commands.txt` (gitignored) хранит SSH/sudo-креды в открытом виде — рекомендован перевод в secret-manager/env и **ротация** (вне рамок S2).

## 8. Явная оговорка приёмки

**HTTP 200 и старт сервиса ≠ корректность восстановления контекста Саммари.** Проверено только: поставка кода, загрузка нового модуля, старт компонентов, отсутствие ошибок импорта/блокировок БД, старт планировщика Саммари. **Live-проверка алгоритма восстановления** (reply-родители §90, соседи/cap/бюджет §89/§93, `RESTORE_*`-логи с `run_id`, сохранность `kept` и публикации, per-chat ON/OFF) — **PENDING OWNER VERIFICATION (D4)**, выполняется владельцем в проде профильным сценарием.

---

## Handoff
**RESULT: VERIFIED — `summary-context-restore-round1026` S2 @Orchestrator** — коммиты `eda7325`/`6fa456c` запушены (`7895e77..6fa456c`, без force), прод `54c6445..6fa456c` **ff-only**, `admin_bot` **active** (PID 384601), `/api/health` **200**, `APP_VERSION` **2.58.21**, served `?v=2.58.21`, `database is locked` **0**, бот `@PERMsoc_bot` polling, саммари-планировщик (cron 0,6,12,18) стартует, новый модуль импортируется, Δ DDL=0 / Δ каталога=0. Откат: тег `pre-round1026-s2`(→`7895e77`) + soft-флаг `flags.summary_filter_reply_context_enabled=false` (резерв `flags.summary_filter_enabled=false`). Дальше: @Orchestrator — Architect reconciliation §73, PM-архив, Memory sync, metrics, следующий F. **Live-корректность восстановления контекста — на OWNER (D4).**
