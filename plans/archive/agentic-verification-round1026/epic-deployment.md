# epic-deployment.md — Эпик 3 «Agentic Intelligence» (round 10.26) — агрегатный эпик-релиз (T-3730, @DevOps)

> **Тип:** **агрегатный эпик-релизный деплой-рекорд Эпика 3** (release policy **EPIC_ONLY**; агрегатный Reviewer gate — `plans/reports/round1026_epic3_aggregate_review.md`, ADR-1026-23 D7/D10).
> **Дата:** 2026-09-25 · **Оператор:** @DevOps · **Risk:** **R3** (deployment-инфраструктура, общие live-модули чата, A5 PG-DDL).
> **Включённые фичи (все индивидуально `Approved`, `plans/archive/*-round1026/`):** A0 `agentic-audit` (read-only, deploy N/A), A1 `tool-coordinator` (**уже на проде с 2.58.30**), A2 `tool-chains`, A3 `unified-image-request`, A5 `image-daily-limit`, A6 `memory-lookup-api`, A4 `image-context-memory`, A7 `decision-making`, A8 `telegram-reactions`, A9 `agentic-events-graph`, A10 `agentic-verification` (приёмочный отчёт `plans/reports/round1026_a10_acceptance.md`; 6 owner-гейтов — PENDING OWNER VERIFICATION, non-blocking).
> **Окружение:** прод `/var/www/admin_bot` (`nik@198.46.175.136`, `racknerd-f4e3456`), systemd-юнит `admin_bot` (User=root, venv `/var/www/admin_bot/venv`, Python 3.12).
> **Binding (агрегатный gate):** Reviewed-Commit **`e8646af`** / WTH **`8a00476a…`** / Spec-Manifest **`d7d8a926…`**.

## Вердикт: **VERIFIED** ✅

Агрегатный эпик-кандидат A2–A9 + A10 доставлен на прод и **подтверждён на уровне эффективных значений**: fast-forward прода **`b1c02a3..89a1261`**, HEAD прода **`89a1261`**; сервис `active (running)` (MainPID **948338**, NRestarts **0**, ExecMainStatus **0**); `/api/health` = **200**; `/healthz` version = **2.58.31**; served cache-bust `?v=2.58.31` = **12** (placeholder `__APP_VERSION__` = **0**); **все 9 новых env-kill-switch'ей эффективно = True** (code-default ON, прод-`.env` без override); **A5 DDL применена** — PG-таблица `image_reservation` существует (10 колонок + 2 индекса + pkey, 0 строк — инертна); `database is locked` = **0**; Traceback/ImportError/ERROR/CRITICAL = **0/0/0/0**; бот и планировщики стартуют; **Δ каталога=0** (473/430/448/102/100/21), канон **12**, SQLite **v12**. **Live-приёмка владельца (6 owner-гейтов, §52/прод-пробы) — PENDING OWNER VERIFICATION** (не блокер релиза по дизайну A3/A5/F10; никогда не репортится закрытой).

---

## 1. Ре-верификация binding перед доставкой (независимо @DevOps)

| Компонент | Заявлено gate | Пересчёт @DevOps | Итог |
|---|---|---|---|
| Reviewed-Commit (HEAD == baseline-анкер) | `e8646af2bcaa79b55cadda756d0e8cc7789fe24f` | локальный HEAD до коммитов == `e8646af` | ✅ совпал |
| **Spec-Manifest §82–§92** | `d7d8a926e0edc356b95e8f9fcbb34a7fee80a394eb1ee01d5da11f4138e59a9f` | **воспроизведён точно**: манифест `plans/archive/<folder>/<file> <sha256>`, порядок фич (spec→adr) A0,A1,A2,A3,A5,A6,A4,A7,A8,A9,A10, join `"\n"` + trailing `"\n"`; все **22/22** per-file sha совпали | ✅ |
| `STATUS` компонент WTH | `cabfcc3249723fd819196f3bd99a42f5a7d9da08516471cfcae1c1c3eb6131ab` | sha256(UTF-8, sorted `git status --porcelain` без агрегатного отчёта) = `cabfcc32…` (106 строк = 86 tracked M + 20 untracked-входов) | ✅ byte-exact |
| `UNTRACKED` компонент WTH | `bdde7cd1e10116286084b2d70d9901566b05a2851ac5826d3845df657456edf3` | sha256(UTF-8, манифест `<relpath> <sha256>` по 62 untracked, без агрегатного отчёта) = `bdde7cd1…` | ✅ byte-exact |
| `DIFF` компонент WTH / WORKING_TREE_HASH | `84279255…` / `8a00476a…` | `git diff e8646af --binary` = `9d396aae…` — **не** совпал | ⚠️ объяснено ниже, non-blocking |

**Дрейф WTH — только служебный машинный чекпоинт, не продукт.** Единственный tracked-файл, изменённый **после** фиксации агрегатного отчёта (report mtime `16:54:13`), — `plans/workflow_state.md` (`16:57:02`; `workflow_checkpoint` @Orchestrator, rev 170→171), ровно **12/12** строк диффа; `git diff --stat e8646af` итог **86 files, 5761(+)/1157(−)** совпал с заявленным в gate, а исключение `workflow_state.md` даёт 85/5749/1145. Весь продуктовый код, тесты, конфиг, lockfiles, спецификации/ADR-манифест и untracked-входы — **без дрейфа** (STATUS/UNTRACKED/Spec-Manifest byte-exact). Это **принятый паттерн A1/S6/S7/S8/S10** (служебная запись после фиксации вердикта). Материального дрейфа нет → approval **не устарел**, к деплою допущено.

## 2. Локальный CI (воспроизведено @DevOps)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest (до bump) | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | **9513 passed / 0 failed** (154.01 с) |
| Полный pytest (после bump/re-pin) | то же | **9513 passed / 0 failed** (157.50 с) |
| JS-гейты (все 47) | цикл `node tests/js/*.js` | **OK=47 / FAIL=0** |
| F8 registry | `python tools/gen_param_registry_round1025.py --check` | **CHECK OK**: реестр 473 == REGISTRY, R17-чисто, TSV/map идемпотентны |
| `git diff --check` | — | exit **0** |
| Секрет-скан (staged diff + untracked plans) | regex ключей/токенов/private-key | **0 реальных секретов** (5 совпадений — R17-тест-константы `secret = "…"`; 1 — текст самого отчёта) |

## 3. Bump и re-pin версии

- `config/settings.py`: `APP_VERSION` **2.58.30 → 2.58.31** (+ агрегатная провенанс-заметка: A2–A10, 10 kill-switch'ей ON, Δ каталога=0, A5 PG-DDL, bump).
- `README.md`: маркер `v2.58.30 → v2.58.31` + агрегатная запись о релизе A0–A10.
- `plans/docs/param-registry-round1025.meta.md`: провенанс `APP_VERSION` → **2.58.31**.
- **Re-pin версии-ассертов (обязательное следствие bump; прецедент A1 — 21 файл):** 27 тест-файлов обновлены `2.58.30 → 2.58.31` — 22 Python (`test_round1025_f8_registry`, `test_scope_selector`, `test_summary_*`, `test_webapp_*`, `test_tool_*`, `test_decision_making`, `test_image_context_memory`, `test_telegram_reactions`) + 4 JS (`round1025_hotfix7/8/9/10`). Только строки версии; полный pytest зелёный **9513/0** после re-pin.
- Cache-bust `?v=` — единый источник `APP_VERSION` (`web/index.html`/`app.css`/`app.js`/`telegram-init.js` → `__APP_VERSION__`), отдельных литералов версии в `web/**` нет.

## 4. Коммиты и push

| Что | Commit | Message | Файлов |
|---|---|---|---|
| **A** код+тесты+`config/settings.py`+`README.md`+F8-провенанс `meta.md` | **`e5bd73de50096ceecbc6a4e2fb08dba0c5d573c6`** | `feat(round1026): Эпик 3 aggregate — A2–A10 (единый эпик-релиз «Agentic Intelligence», APP_VERSION 2.58.31; release gate ADR-1026-23 D7/D10)` | 95 (+11871/−1159) |
| **B** планы: docs + 9 archive-папок A2–A10 (D-3) + reports + state | **`89a126170f82b79d34dadaa74f23d81bca9e3c1b`** | `docs(plans): round1026 Эпик 3 aggregate — A2–A10 (планы/архивы/отчёты, binding e8646af)` | 63 (+12158/−32) |
| **deploy-doc (этот файл)** | см. docs-коммит ниже | `docs(deploy): round1026 Эпик 3 aggregate — прод-деплой VERIFIED (APP_VERSION 2.58.31)` | 1 |

- **Push:** `origin/master`, **без force** — **`e8646af..89a1261`** (`henry@Hen…` → GitHub `Henry-Case-dev/adminbot`). `origin/master` до push == `e8646af`, после == **`89a1261`** (fast-forward `0/2` до push).
- **Иммутабельные артефакты (git-объекты):** tree `89a1261` = **`c64e28588b54206fc0bdc1a5f5bb9df7f9116d79`**; tree код-коммита `e5bd73d` = **`d39a93801a5bf0407a6c7e12d2f0408d99bbdd76`**; анкер `e8646af` tree = `8363435c2d29e4c60efbb014ccff42834d2443a3`.
- **D-3 staging выполнен:** 9 untracked archive-папок A2–A10 + `plans/reports/round1026_a10_acceptance.md` + `plans/reports/round1026_epic3_aggregate_review.md` включены в коммит B (рекорд gate стал durable). `plans/current_task.md` — **untracked, не коммитился** (R17/R18); `.env`/`media/`/`deploy_commands.txt`/`local_database.db` — gitignored, вне коммитов. Теги `pre-round1026-*` (**14**) и `stash@{0}` — **не тронуты** (R18).

## 5. Прод-деплой (traceable)

- **Сервер до деплоя:** HEAD `b1c02a3` (A1), `admin_bot` — `active`, MainPID **652183**; tracked-изменений нет (только pre-existing untracked `.bak`/`local_database.db.bak*`, не тронуты).
- **Pull:** `cd /var/www/admin_bot && git pull --ff-only origin master` → **`Updating b1c02a3..89a1261 — Fast-forward`** (включая A1 closing-docs `e8646af` + релиз A/B). После pull HEAD = **`89a1261`** == `origin/master`; `APP_VERSION` на проде = **2.58.31**.
- **Restart:** `sudo -n systemctl restart admin_bot` → exit **0**; `ExecMainStartTimestamp` = **Fri 2026-09-25 05:14:02 UTC**.
- **Состояние после:** MainPID **948338**, NRestarts **0**, ExecMainStatus **0**, ActiveState `active`.

## 6. Health / смоук-проверки (факт)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active (running)** ✅ |
| `GET /api/health` (127.0.0.1:8000) | **HTTP 200** ✅ |
| `GET /healthz` | `{"status":"ok","version":"2.58.31"}` ✅ |
| served cache-bust `/web/` | `?v=2.58.31` — **12** вхождений; placeholder `__APP_VERSION__` = **0** ✅ |
| `APP_VERSION` (prod venv) | **2.58.31** ✅ |
| `database is locked` | **0** ✅ |
| Traceback / ImportError | **0 / 0** ✅ |
| ERROR / CRITICAL | **0 / 0** ✅ |
| Старт бота | `Start polling` = **1**; `Run polling for bot @PERMsoc_bot` ✅ |
| Планировщики | `Scheduler started` = **10**; `[uptime] heartbeat started` ✅ |
| Web lifespan | `[webapp] lifespan started | pg_available=True` ✅ |
| Каталог (prod import) | REGISTRY **473** / GROUPS **102** / `_TAB_BY_GROUP` **100** / TAB_RULES **21** / Settings fields **430** ✅ |
| Канон инструментов (prod import) | `TOOL_CALLING_TOOLS` = **12** ✅ |
| DDL-операторы в логах (`CREATE TABLE`) | **0** (init не печатает DDL; применение подтверждено прямым PG-запросом — §7) |

## 7. A5 DDL — применение и подтверждение (метод: прямой PG-запрос)

- **Механизм:** `services/pg_db.py::DDL_STATEMENTS` содержит идемпотентные `CREATE TABLE IF NOT EXISTS image_reservation` + `CREATE INDEX IF NOT EXISTS idx_image_reservation_day_status` / `idx_image_reservation_chat_day`; применяются `PgDatabase.init()` при старте прода (до сидов). SQLite Δ DDL = **0** (v12).
- **Метод проверки:** скрипт на прод-venv, `load_dotenv('/var/www/admin_bot/.env')` → `POSTGRES_DSN` → `asyncpg.connect` → запросы `to_regclass`, `information_schema.columns`, `pg_indexes`, `count(*)` (**DSN не выводился** — R17).
- **Результат:** `RESULT=OK`; `TABLE = image_reservation`; колонки `['chat_id','created_at','day','delivery_failed','error_code','message_id','reservation_key','source','status','updated_at']`; индексы `['idx_image_reservation_chat_day','idx_image_reservation_day_status','image_reservation_pkey']`; `ROWCOUNT=0` → таблица **создана и инертна**. ✅

## 8. Инвентарь kill-switch'ей (эффективные значения, prod venv, `Settings`-инстанс)

| Gate | Эффективно (prod) | Прод-`.env` override |
|---|---|---|
| `DIRECT_COORDINATOR_ENABLED` (A1) | **True** | нет |
| `TOOL_CHAIN_LIMITS_ENABLED` (A2) | **True** | нет |
| `UNIFIED_IMAGE_REQUEST_ENABLED` (A3) | **True** | нет |
| `IMAGE_DAILY_LIMIT_ENABLED` (A5) | **True** | нет |
| `MEMORY_LOOKUP_ENABLED` (A6) | **True** | нет |
| `IMAGE_CONTEXT_MEMORY_ENABLED` (A4) | **True** | нет |
| `DIRECT_DECISION_MAKING_ENABLED` (A7) | **True** | нет |
| `REACTION_MECHANICS_ENABLED` (A8) | **True** | нет |
| `AGENTIC_EVENTS_ENABLED` (A9) | **True** | нет |

`grep -E '^(…9 ключей)=' .env` → **NONE** → override нет, активация штатная по code-default ON. Все env-only `ClassVar`, ∉ `REGISTRY`/`Settings`-поля (Δ каталога=0).

## 9. Инварианты

- **Δ каталога = 0:** prod import 473/102/100/21/430; `services/param_catalog.py` — часть принятого периметра A2–A9, но итог = baseline gate; F8 `--check` OK.
- **Канон = 12**, **SQLite = v12** (Δ DDL = 0), **PG +1 таблица** (`image_reservation`, единственная sanctioned-миграция A5).
- **0 новых внешних зависимостей** (`requirements.txt`/локи/vendor — вне diff vs `e8646af`).
- **CSP/zero-build** сохранён (`web/**` — только принятые A9/A10-изменения; CDN нет).
- **R17:** логи координатора/событий — числа/коды/id/имена инструментов; секрет-скан чист; DSN не выводился. **R18:** теги/бэкапы/`stash@{0}` не удалялись; pre-existing untracked `.bak` на проде не трогались; force-push/amend не применялись.

## 10. Watch-items и честные ограничения (non-blocking)

1. **6 owner-гейтов Эпика 3 (внешние, live) — PENDING OWNER VERIFICATION** (сценарии §52 пп. 1/2/4/10/18/22; прод-пробы HY-01/02/04/05/06, live URL, live toggle). Headless-контур их не закрывает; **не репортятся закрытыми**. Указатель — `plans/reports/round1026_a10_acceptance.md` (§7 watch/owner-register).
2. **A10 Low-1…Low-4** (провизорные `Tasks-Hash`/`ADR-Hash` в приёмочном отчёте) — документальные; агрегатный манифест построен по актуальным хешам; влияния на релиз нет.
3. **D-3** — выполнен в коммите B (архивы + отчёты стали tracked).
4. Residual'ы A4/A7/A9 (accepted boundary) — registered non-blocking на своих гейтах.
5. **WTH-дельта** — только служебный `plans/workflow_state.md` (см. §1).

## 11. Откат (готовность; не исполнялся)

- **Hot (без перезаписи кода):** OFF соответствующего env-kill-switch'а в прод-`.env` + `sudo -n systemctl restart admin_bot` — по фиче: A2 `TOOL_CHAIN_LIMITS_ENABLED=false`, A3 `UNIFIED_IMAGE_REQUEST_ENABLED=false`, A5 `IMAGE_DAILY_LIMIT_ENABLED=false`, A6 `MEMORY_LOOKUP_ENABLED=false`, A4 `IMAGE_CONTEXT_MEMORY_ENABLED=false`, A7 `DIRECT_DECISION_MAKING_ENABLED=false`, A8 `REACTION_MECHANICS_ENABLED=false`, A9 `AGENTIC_EVENTS_ENABLED=false`; A1 `DIRECT_COORDINATOR_ENABLED=false`; каждый gate независим и возвращает документированный legacy-путь.
- **Cold:** `git revert e5bd73d 89a1261` (или checkout анкера) до **`e8646af`** (tree `8363435c…`) + `git push` без force + прод `git pull --ff-only` + restart. Пер-фичевых annotated-тегов нет (EPIC_ONLY — ADR-1026-16 D8).
- **A5 DDL:** таблица `image_reservation` **аддитивна и инертна** (0 строк, читатель за OFF-флагом) → **отдельный DDL-откат/DROP не требуется**.
- Теги `pre-round1026-*`, бэкапы (`var/backups/a1-round1026-*`), `stash@{0}` — целы (R18). Откат **не потребовался** — деплой/верификация успешны.

---

## Handoff

**RESULT: `VERIFIED` (Эпик 3, round 10.26) @Orchestrator** — коммиты **`e5bd73d`** (код+тесты+`config/settings.py`+`README.md`+F8-meta, APP_VERSION 2.58.31) + **`89a1261`** (планы/архивы A2–A10/reports/state) + deploy-doc (этот файл); push `origin/master` **`e8646af..89a1261`** без force; прод `/var/www/admin_bot` fast-forward **`b1c02a3..89a1261`** (2026-09-25 05:14:02 UTC); `systemctl restart` → **active** (MainPID **948338**, NRestarts 0, ExecMainStatus 0); `/api/health` **200**; `/healthz` **2.58.31**; served `?v=2.58.31` (×12, placeholder 0); **все 9 kill-switch'ей эффективно = True** (code-default, `.env` без override); **A5 DDL применена** (PG `image_reservation` существует; 10 колонок + 2 индекса + pkey; 0 строк); `database is locked`=0; Traceback/ImportError/ERROR/CRITICAL=0; бот/планировщики стартуют; Δ каталога=0 (473/430/448/102/100/21), канон 12, SQLite v12; 0 новых зависимостей; R17/R18 чисты. Откат: hot — OFF env-kill-switch'ей; cold — revert/checkout к `e8646af`; A5 DDL не требует DROP. **Live-приёмка владельца (6 owner-гейтов) — PENDING OWNER VERIFICATION** (non-blocking). Далее по процессу: @Orchestrator (reconciliation/checkpoint, PM epic-archive, Memory sync, metrics) — **вне T-3730**.
