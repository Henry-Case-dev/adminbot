# deployment.md — S8 `summary-analytics-adapter-round1026` (T-3433, @DevOps — прод-поставка)

> **Feature:** `summary-analytics-adapter-round1026` (Эпик 2, §23–§25/§29/§30/§111/§112; ADR-1026-10 D1–D10) · **Дата:** 2026-09-24 · **Оператор:** @DevOps
> **Базис:** HEAD до деплоя **`2ffeb6a`** == `origin/master` (closing-docs S7); annotated-тег **`pre-round1026-s8`** (tag-obj **`eeb960b4`**) → **`2ffeb6a`**; релизные коммиты **`64cdb0e`** (код+тесты) + **`7c5338e`** (планы).
> **Окружение:** прод `/var/www/admin_bot` (`nik@198.46.175.136`), systemd-юнит `admin_bot`, venv Python 3.12.
> **Решение ADR-1026-10 D9:** deploy = **ДА**, bump `APP_VERSION` 2.58.26 → **2.58.27**. Единый Reviewer gate — **Approved C0/H0** (отдельного Scanner-approval нет).

## Вердикт: **VERIFIED** ✅

Рантайм S8 доставлен на прод: fast-forward `aa42a04..7c5338e`, сервис `active (running)` (MainPID **540872**, NRestarts **0**, ExecMainStatus **0**), `/api/health` = **200**, `/healthz` version = **2.58.27**, `/web/` cache-bust `?v=2.58.27` = **12** (placeholder `__APP_VERSION__` = **0**), новый роут `GET /api/analytics/execution/latest` **жив** (401 `missing init data` — штатная авторизация), `database is locked` = **0**, Traceback/ImportError/ERROR/CRITICAL после рестарта = **0**, `import services.execution_graph_source` **OK**, `PUBLISH_*` = **0**, бот и планировщик Саммари стартуют, **Δ DDL = 0**, публикационный путь не изменён.

---

## 1. Коммиты и push

| Что | Commit | Сообщение | Файлов |
|---|---|---|---|
| Код + тесты + `config/settings.py` + `README.md` | **`64cdb0e`** | `feat(round1026): S8 — adapter аналитики Саммари (ExecutionGraph-узлы Filter/L1/L2/Formatting, §112-метрики, GET /api/analytics/execution/latest) (APP_VERSION 2.58.27)` | 34 |
| Планы: feature-папка S8 + `audit_backlog` + `MEMORY`/meta/state | **`7c5338e`** | `docs(plans): round1026 S8 — ревью-артефакты и аудит (единый Reviewer gate, binding 2ffeb6a)` | 9 |
| deploy-doc (этот файл) | см. docs-коммит ниже | `plans/features/summary-analytics-adapter-round1026/deployment.md` | 1 |

- **Push:** `origin/master`, **без force** — **`2ffeb6a..7c5338e`** (2026-09-24 06:31:24 +12 / 2026-09-23 **18:31:24 UTC**).
- `APP_VERSION`: **2.58.26 → 2.58.27** (bump в `config/settings.py`, cache-bust `?v=__APP_VERSION__`, README `v2.58.27`).
- `plans/current_task.md` и машинный блок `OPENCODE_WORKFLOW_STATE_V1` не редактировались вручную.

## 2. Проверка привязок Reviewer (T-3428/T-3429) перед релизом

- **Reviewed-Commit `2ffeb6a3f95922ed4833110fe90634794ace0804`** — подтверждён: локальный HEAD до коммитов == `origin/master` == цель annotated-тега `pre-round1026-s8`.
- **Spec-Hash `f397f3fd378625c9ea958dcd934595316f28fdb6668ff3a970a2c21138d71a6f`** — пересчитан **байт-в-байт** (SHA-256 `plans/features/summary-analytics-adapter-round1026/spec.md`) — **совпал**.
- **Working-Tree-Hash `4151d36d7f87809e574c386d1a853ccc10307493049a3b23ff1f910e5681b014`** — манифест воспроизведён: из заявленного в `review.md` diff-SHA `3882c8a6…` + 7 per-file хэшей untracked-файлов повторно вычислен **ровно `4151d36d…`** (структура рецепта подтверждена).
  - **Все 7 untracked-хэшей совпали байт-в-байт** с `review.md`: adr `c11e297b…`, evidence `d4740b94…`, spec `f397f3fd…`, tasks `220adab7…`, `services/execution_graph_source.py` `948f7e78…`, `tests/js/round1026_s8_execution_graph_test.js` `82059cc7…`, `tests/test_summary_execution_graph_round1026.py` `7dc3bac3…`.
  - **Единственная дельта дерева от ревью-состояния** — служебный машинный блок `plans/workflow_state.md` (обновлён `workflow_checkpoint` @Orchestrator; mtime **06:21:40**, уже **после** финализации `review.md` в **06:20:50**). Поэтому diff-компонента WTH (`git diff 2ffeb6a`) уже не совпадает байт-в-байт: текущий diff-SHA = `f3da8b5f…`, а без машинного блока = `098eb164…` (ревью-значение `3882c8a6…` зафиксировано на ревью-редакции блока, недоступной для повторного вычисления). Это тот же принятый паттерн, что в S7 (deployment.md §2: rev4 → rev5 после ревью).
  - **Product code / тесты / конфиг / spec после ревью не менялись:** mtime всего кода/тестов/`config/settings.py`/`README.md` ≤ **06:09:58**, `audit_backlog.md` 06:19:48 (до хэширования), `review.md` 06:20:50; единственный файл новее — `plans/workflow_state.md` (машинный блок). Материального дрейфа нет → к деплою допущено.

## 3. Локальный CI перед коммитами (воспроизведено @DevOps)

| Проверка | Команда | Результат |
|---|---|---|
| Полный регресс pytest | `.venv\Scripts\python.exe -m pytest -q` | **8926 passed / 0 failed** (118.86 s, 1 warning) — совпадает с ревью (8926/0) |
| JS (все файлы) | `node tests/js/*.js` (46 файлов) | **OK=46 FAIL=0** — совпадает с ревью (46/46) |
| Импорт нового рантайма | `python -c "import services.execution_graph_source"` | **OK** (`build_graph`, `RunSnapshotStore`) |
| `git diff --check` | — | exit **0** |
| Секрет-скан диффа + untracked-кода | `rg -i "api[_-]?key\|secret\|password\|bearer\|PRIVATE KEY\|sk-…\|bot<id>:…"` | 0 реальных секретов (единственное совпадение — тест-ассерт *запрещённых* ключей); `.env`/`deploy_commands.txt`/`media/` в набор коммитов не входили (gitignored) |

## 4. Прод-деплой (traceable)

- **Сервер до деплоя:** HEAD `aa42a04`, `APP_VERSION` 2.58.26, `admin_bot` — `active`, MainPID **522392** (с 2026-09-23 17:01:27 UTC).
- **Pull:** `cd /var/www/admin_bot && git pull --ff-only origin master` → **`aa42a04..7c5338e` Fast-forward** (reflog: `7c5338e HEAD@{2026-09-23 18:31:59 +0000}: pull --ff-only origin master: Fast-forward`); 53 файла, +2527/−82. После pull HEAD = `7c5338e` == `origin/master`.
- **Restart:** `sudo -n systemctl restart admin_bot` → exit **0**; сервис `active` с **2026-09-23 18:33:10 UTC** (стоп-фаза graceful ~60 с, как в S7).
- **Состояние:** MainPID **540872**, NRestarts **0**, ExecMainStatus **0**, ActiveState `active`.

## 5. Health / смоук-проверки (факт)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active (running)** ✅ |
| `GET /api/health` (127.0.0.1:8000) | **HTTP 200** ✅ |
| `GET /healthz` | **HTTP 200** `{"status":"ok","version":"2.58.27"}` ✅ |
| served cache-bust `/web/` | `?v=2.58.27` — **12** вхождений; placeholder `__APP_VERSION__` = **0** ✅ |
| served `/web/static/execution_graph.js?v=2.58.27` | **HTTP 200** ✅ |
| `APP_VERSION` в venv прода | **2.58.27** ✅ |
| **Новый роут** `GET /api/analytics/execution/latest` | **жив** — **HTTP 401** `{"detail":"missing init data"}` (штатная авторизация, не ошибка; 200 при admin init-data) ✅ |
| Импорт нового рантайма | `import services.execution_graph_source` → **OK** (`build_graph`/`RunSnapshotStore`) ✅ |
| `database is locked` (с рестарта) | **0** ✅ |
| Traceback / ImportError (с рестарта) | **0** ✅ |
| ERROR / CRITICAL (с рестарта) | **0** ✅ |
| `PUBLISH_*` в логах | **0** ✅ |
| Старт бота | `Start polling` / `Run polling for bot` — 2 записи ✅ |
| Планировщик Саммари | `scheduler started` / `SummarySchedulerService` / `initialized` — 23 записи ✅ |
| Миграции БД | не запускались; **Δ DDL=0** — `git diff --name-only 2ffeb6a..HEAD -- db` = **0**, `CREATE/ALTER TABLE/INDEX` в логах = **0**; штатный startup-синк `services.prompt_migrations` — «уже новый канон» (без изменений, не DDL) ✅ |

## 6. Инварианты

- Публикационный путь не изменён: `PUBLISH_*` в коде/логах — **0** (GATED S6/D4); `routes.py`/`param_catalog.py`/`image_generation.py`/`telegram_send.py`/`summary_xml.py`/`db/**`/`summary_test_run.py` вне релизного diff.
- Δ каталога = 0 (F8 не переиздаётся), **Δ DDL = 0**, 0 новых внешних зависимостей, CSP/zero-build — без изменений.
- 2-вызовность сохранена (S8 read-only, 0 новых LLM-вызовов); `price_known` — аддитивно (закрытие `L-F6S-1`).

## 7. Откат (готовность; не исполнялся)

- **Жёсткий:** `git revert 64cdb0e 7c5338e` (или `git checkout pre-round1026-s8`) + `sudo -n systemctl restart admin_bot`.
- **Тег:** annotated **`pre-round1026-s8`** → **`2ffeb6a`** (цель отката; `APP_VERSION` 2.58.26).
- **Бэкапы (R18, не удалялись):** `var/backups/s8-round1026-20260924-053821/` + `.env.bak.round1026-s8`; `stash@{0}` не тронут; история не перезаписывалась, force-push не применялся.
- Откат **не потребовался** — деплой и верификация успешны.

## 8. Честные ограничения

1. **HTTP 200/401 ≠ качество UI.** Подтверждены доставка, целостность, старт компонентов, отсутствие регрессий и живость нового роута; визуальное поведение §112-карты/узлов Filter/L1/L2/Formatting в реальном Telegram WebView — **PENDING OWNER VERIFICATION** (SC-18; соответствует ADR-1026-10 D1).
2. **Non-blocking техдолг (owned follow-up, не блокеры):** `L-R1026S8-1` (Low — `algorithm`-узел по одному `source_count`), `L-R1026S8-2` (Low — `metrics.context` не рендерится UI), `L-R1026S8-3` (Info — комментарий в `tests/test_round1025_f8_registry.py:125`); `L-R1026S7-1` (pre-existing, вне diff) — OPEN.
3. `evidence.md` намеренно **не изменялся** после ревью (сохранение байт-точности ревью-манифеста); деплой-факты зафиксированы здесь.

---

## Handoff

**RESULT: VERIFIED (T-3433) @Orchestrator** — коммиты **`64cdb0e`** (код+тесты+`config/settings.py`+`README.md`, APP_VERSION 2.58.27) + **`7c5338e`** (планы: ревью-артефакты + аудит) + deploy-doc (этот файл); push `origin/master` **`2ffeb6a..7c5338e`** без force; прод `/var/www/admin_bot` fast-forward **`aa42a04..7c5338e`** (2026-09-23 18:31:59 UTC); `systemctl restart` → **active** (MainPID **540872**, NRestarts 0, 18:33:10 UTC); `/api/health` **200**; `/healthz` **2.58.27**; `APP_VERSION` **2.58.27**; served `?v=2.58.27` (×12, placeholder 0); новый роут `GET /api/analytics/execution/latest` **жив** (401 `missing init data`); `import services.execution_graph_source` OK; `database is locked`=0; Traceback/ERROR/CRITICAL=0 после рестарта; `PUBLISH_*`=0; бот/планировщик Саммари стартуют; **Δ DDL=0**. Откат: `pre-round1026-s8`→`2ffeb6a` + `git revert 64cdb0e 7c5338e`; бэкапы/`stash@{0}` целы (R18). **Live-приёмка UI — PENDING OWNER VERIFICATION.** Далее по процессу: @Orchestrator (reconciliation), @PM (архив), @Memory (sync), метрики, следующий F.
