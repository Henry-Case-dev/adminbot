# deployment.md — A1 `tool-coordinator-round1026` (T-3522, @DevOps — прод-поставка и активация)

> **Feature:** `tool-coordinator-round1026` (Эпик 3 «Agentic Intelligence», Wave 1; §13/§14; ADR-1026-14 D1–D10) · **Дата:** 2026-09-24 · **Оператор:** @DevOps
> **Базис до деплоя:** HEAD **`e3ea367`** == `origin/master`; annotated-тег **`pre-round1026-a1`** (tag-obj **`3244c61e`**) → **`e3ea367`**; релизные коммиты **`b32c46a`** (код+тесты) + **`b1c02a3`** (планы).
> **Окружение:** прод `/var/www/admin_bot` (`nik@198.46.175.136`), systemd-юнит `admin_bot`, venv Python 3.12.
> **Решение ADR-1026-14 D7:** deploy = **ДА**, bump `APP_VERSION` 2.58.29 → **2.58.30**; Risk **R2**; единый Reviewer gate — **Approved C0/H0** (отдельного Scanner-approval нет).

## Вердикт: **VERIFIED** ✅

Программный слой Координатора инструментов доставлен на прод и **активация подтверждена на уровне эффективного значения**: fast-forward **`04f5ae1..b1c02a3`**, сервис `active (running)` (MainPID **652183**, NRestarts **0**, ExecMainStatus **0**), `/api/health` = **200**, `/healthz` version = **2.58.30**, served cache-bust `?v=2.58.30` = **12** (placeholder `__APP_VERSION__` = **0**), `APP_VERSION` прод-venv = **2.58.30**, **эффективный `DIRECT_COORDINATOR_ENABLED` = True** (code-default ON; `.env` без override), `coordinator_enabled()` = **True**, импорт `services.direct_chat_service` — **OK**, prompt-синк штатный («уже новый канон» ×13, «канон обновлён» ×0), `database is locked` = **0**, Traceback/ImportError/ERROR/CRITICAL = **0**, DDL в логах = **0**, бот и планировщики стартуют, **Δ DDL = 0**; §104-контур, промпты/канон, `tool_loop`, `web/**`, `db/**`, каталог — вне диапазона деплоя. **Live-приёмка владельца (реальный direct-чат, §13/§14) — PENDING OWNER VERIFICATION.**

---

## 1. Коммиты и push

| Что | Commit | Сообщение | Файлов |
|---|---|---|---|
| Код + тесты + `config/settings.py` (kill-switch/версия) + `README.md` + провенанс-штамп meta | **`b32c46a`** | `feat(round1026): A1 — единый координатор инструментов в Синтезаторе (программный слой решения о действии, kill-switch DIRECT_COORDINATOR_ENABLED) (APP_VERSION 2.58.30)` | 27 (+920/−34) |
| Планы: feature-папка A1 + `audit_backlog` + `MEMORY`/`workflow_state` | **`b1c02a3`** | `docs(plans): round1026 A1 — ревью-артефакты и аудит (единый Reviewer gate, binding e3ea367)` | 8 (+722/−11) |
| deploy-doc (этот файл) | см. docs-коммит ниже | `plans/features/tool-coordinator-round1026/deployment.md` | 1 |

- **Push:** `origin/master`, **без force** — **`e3ea367..b1c02a3`** (коммиты 2026-09-24 15:49:33 / 15:49:48 +12). `origin/master` == `b1c02a3` (подтверждено `git ls-remote` до и после).
- **Иммутабельные артефакты (git-объекты):** tree `b32c46a` = **`f5819df16f75826ec11f52f2f46f1d780ac88db4`**; tree `b1c02a3` = **`64210cfd737dff667585e79bdbf6ca5bfa3dc24c`**.
- `APP_VERSION`: **2.58.29 → 2.58.30** (bump в `config/settings.py`; cache-bust `?v=__APP_VERSION__`; README `v2.58.30`; провенанс-штамп `param-registry-round1025.meta.md`).
- `plans/current_task.md` и машинный блок `OPENCODE_WORKFLOW_STATE_V1` вручную не редактировались (машинный блок закоммичен как есть, `workflow_checkpoint` не вызывался); amend/force не применялись. Секреты не коммитились (`.env`/`media/`/`deploy_commands.txt` — gitignored, вне коммитов).

## 2. Проверка привязок Reviewer (перед релизом)

- **Reviewed-Commit `e3ea367a5dd9961365e89f40eb183b86e20f1cf4`** — подтверждён: локальный HEAD до коммитов == `origin/master` == цель annotated-тега `pre-round1026-a1` (tag-obj `3244c61e`).
- **Spec-Hash `b37b9a509cf868ac752cbf9043cd306bbea7bd481d517eda9131dd68f85c2821`** — пересчитан (SHA-256 `spec.md`) — **совпал**; ADR/evidence/tasks/новый тест — **все 5 untracked-хэшей совпали байт-в-байт** с `review.md` (`0d992a42…`, `6c85d9c6…`, `b37b9a50…`, `50f662dd…`, `44738081…`).
- **Working-Tree-Hash `4361f0111fcd87414c5e20fe9932df447bb5125a26a2b2ce0f74da5020b5a67f`** — рецепт воспроизведён **точно**: из заявленного в `review.md` diff-SHA `9ede44d3…` + 5 per-file хэшей untracked повторно вычислен ровно `4361f011…` (арифметика рецепта консистентна).
  - **Хэши product-файлов из `evidence.md` §6 пересчитаны — MATCH:** `services/direct_chat_service.py` `B0F8BB07…`, `config/settings.py` `28C554BB…`, `README.md` `01B8621E…`, `plans/docs/param-registry-round1025.meta.md` `B0BCDB72…`, `tests/test_tool_coordinator_round1026.py` `44738081…`.
  - **Единственная дельта дерева от ревью-состояния** — служебный машинный блок `plans/workflow_state.md` (обновлён `workflow_checkpoint` @Orchestrator; mtime **13:24:25**, уже **после** финализации `review.md` 13:23:52; rev 62→63, phase review→delivery). Текущая diff-компонента WTH (`git diff e3ea367` = `7a3a3776…`) не совпадает с ревью-значением байт-в-байт — **тот же принятый паттерн, что в S6/S7/S8/S10** (служебная запись после фиксации вердикта).
  - **Product code / тесты / конфиг / spec после ревью не менялись:** mtime всего кода/тестов/`config/settings.py`/`README.md`/meta ≤ **13:14:35**, `review.md` 13:23:52; позже — только `workflow_state.md`. Материального дрейфа нет → к деплою допущено.
  - **Сверка staged-контента:** финальный staged-diff кода/тестов **байт-в-байт** равен нормализованному worktree-diff, проверенному Reviewer (`ba471758…`); `git hash-object` каждого файла == его staged-блоб (0 расхождений). Технический нюанс подготовки — §9 п.3.

## 3. Локальный CI перед коммитами (воспроизведено @DevOps)

| Проверка | Команда | Результат |
|---|---|---|
| Полный регресс pytest (прогон 1) | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=120` | **9081 passed / 1 failed** (163.05 с) |
| Полный регресс pytest (прогон 2) | то же | **9081 passed / 1 failed** (156.28 с) |
| Падение — известный pre-existing флак | `tests/test_betterstack_handler.py::TestNoRedirect::test_real_302_not_followed_by_opener` | документирован ещё в аудите 10.19 (`S10.19-27`: «чувствителен к занятости портов/таймингам в CI — флейки-риск, не продуктовая проблема»); файл **вне diff A1**; в изоляции: одиночный прогон — passed (3.19 с), серия 10× — **9 passed / 1 failed**. Гейт @Reviewer по этому дереву — **9082/0** |
| JS (все 47 файлов) | цикл `node tests/js/*.js` | **OK=47 FAIL=0** — совпадает с ревью |
| `git diff --check` | — | exit **0** |
| Каталог параметров | `tools/gen_param_registry_round1025.py --check` | **CHECK OK**: реестр 469 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны; 469/100/98/21 (+426/444 — тесты F8/polygon зелёные) |
| Версия / kill-switch | импорт `config.settings`/`direct_chat_service` | `APP_VERSION` **2.58.30**; `settings.DIRECT_COORDINATOR_ENABLED` = **True**; `coordinator_enabled()` = **True**; kill-switch **не** в `REGISTRY` (env-only `ClassVar`) |
| Секрет-скан релизного diff + untracked | regex `api_key/secret/password/bearer/private key/sk-…/bot-token` | diff — **0 совпадений**; untracked — 3 совпадения = R17-тест-константа `query_secret` в новом тест-файле — **реальных секретов нет** |
| Границы diff | `git diff --name-only e3ea367 -- <запрещённые>` | **пусто** (`tool_loop.py`, `image_generation.py`, промпты, `param_catalog.py`, `execution_graph_source.py`, `web/**`, `db/**`, `plans/current_task.md`, манифесты) |
| Δ DDL | `git diff --name-only pre-round1026-a1 -- db/` | **пусто** (0) |
| Состав diff тестов | `--numstat` + фильтр не-версионных строк | все 22 re-pin-файла — **только строки версии**; 658 не-версионных строк = целиком новый `tests/test_tool_coordinator_round1026.py` |

## 4. Прод-деплой (traceable)

- **Сервер до деплоя:** HEAD `04f5ae1` (S10), `APP_VERSION` **2.58.29**, `admin_bot` — `active`, MainPID **595858**, NRestarts 0, ExecMainStatus 0; `.env` override `DIRECT_COORDINATOR_ENABLED` = **0** (ключ отсутствует); 13 pre-existing untracked `.bak` (не наши, не тронуты).
- **Pull:** `cd /var/www/admin_bot && git pull --ff-only origin master` → **`04f5ae1..b1c02a3` Fast-forward** (включает A0 closing-docs `e8065e9`/`e3ea367` + релиз A1 `b32c46a`/`b1c02a3`). После pull HEAD = **`b1c02a3`** == `origin/master`.
- **Restart:** `sudo -n systemctl restart admin_bot` → exit **0**; сервис `active` с **2026-09-24 03:53:01 UTC** (`ExecMainStartTimestamp`).
- **Состояние после:** MainPID **652183**, NRestarts **0**, ExecMainStatus **0**, ActiveState `active` (стабильно при повторной проверке).

## 5. Health / смоук-проверки (факт)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active (running)** ✅ |
| `GET /api/health` (127.0.0.1:8000) | **HTTP 200** ✅ (на 6-й секунде после рестарта — 000: сервер ещё поднимался; повтор с паузой — 200) |
| `GET /healthz` | `{"status":"ok","version":"2.58.30"}` ✅ |
| served cache-bust `/web/` | `?v=2.58.30` — **12** вхождений; placeholder `__APP_VERSION__` = **0** ✅ |
| `APP_VERSION` в venv прода | **2.58.30** ✅ |
| Импорт `services.direct_chat_service` (prod venv) | **OK** ✅ |
| **Kill-switch (эффективно)** | `settings.DIRECT_COORDINATOR_ENABLED` = **True**; `coordinator_enabled()` = **True** ✅ |
| Прод-`.env` | ключ `DIRECT_COORDINATOR_ENABLED` — **отсутствует** (`grep -c '^DIRECT_COORDINATOR_ENABLED' .env` = **0**) → override нет, активация штатная (не заблокирована) ✅ |
| Prompt-синк | `[prompt_migration]` ×**13**, все — **«уже новый канон»**; «канон обновлён» = **0** ✅ (промпты A1 не менял) |
| `database is locked` (окно после рестарта) | **0** ✅ |
| Traceback / ImportError | **0 / 0** ✅ |
| ERROR / CRITICAL | **0 / 0** ✅ |
| DDL-операторы в логах (`CREATE TABLE` и др.) | **0** ✅ |
| Старт бота | `Start polling` ✅ |
| Планировщики | `Scheduler started` ×2 / `SummarySchedulerService` ×1 ✅ |
| Порт | `:8000` слушается ✅ |
| Миграции БД | не запускались; **Δ DDL=0** — `git diff --name-only 04f5ae1..b1c02a3 -- db` = **0** ✅ |

## 6. Активация и kill-switch

- **Эффективное значение (прод-venv):** `DIRECT_COORDINATOR_ENABLED` = **True** (code-default ON после bump 2.58.30) ✅; резолв per-call (`getattr(settings, "DIRECT_COORDINATOR_ENABLED", True)`), каталог не растёт.
- **Прод-`.env`:** ключ отсутствует → override нет; активация произошла штатно по push/ff, **не заблокирована** (явного `false` нет).
- **Hot-OFF (готов, не исполнялся):** `DIRECT_COORDINATOR_ENABLED=false` в `.env` + `sudo -n systemctl restart admin_bot` → точный legacy-путь direct-чата (координатор не строится). `SYSTEM2_DIRECT_ENABLED=false` по-прежнему отключает System-2-путь целиком (существующее поведение).

## 7. Инварианты

- **Δ DDL = 0** (миграции не запускались; `db/**` вне диапазона; 0 DDL в логах).
- **Δ каталога = 0** — `services/param_catalog.py` вне diff; kill-switch env-only, ∉ `REGISTRY`; `--check` OK (реестр 469); F8 не переиздаётся.
- **0 новых внешних зависимостей** (манифесты/локи вне diff); **CSP/zero-build** (`web/**` вне diff).
- **Промпты/канон не менялись** — `services/chat_prompts.py`/`prompt_migrations.py`/`summary_prompts.py` вне diff; ADR-1013-3 **NOT_APPLICABLE**; prompt-синк «уже новый канон».
- **§104 `generate_image` и §85-UI не тронуты** — вне diff (`git diff --name-only 04f5ae1..b1c02a3 -- services/image_generation.py web services/param_catalog.py db` = 0).
- **2-вызовность System 2 сохранена** (`await_count==2`, тесты зелёные); wire-поле `action` не введено.
- **R17:** логи/события координатора — числа/коды/id/имена инструментов; сырые тексты/ключи не логируются (секрет-скан чист).
- **R18:** тег/бэкапы/`stash@{0}` не удалялись; pre-existing untracked `.bak` на проде (13) не трогались.

## 8. Откат (готовность; не исполнялся) и R18

- **Soft (обратимый, без переписывания кода):** `DIRECT_COORDINATOR_ENABLED=false` в `.env` + рестарт → точный legacy-путь.
- **Жёсткий:** annotated-тег **`pre-round1026-a1`** → **`e3ea367`** (tag-obj `3244c61e`) + `git revert b32c46a b1c02a3` (или `git checkout pre-round1026-a1`) + рестарт. Канон-откат **не требуется** (промпты не менялись).
- **Бэкапы (R18, не удалялись):** `var/backups/a1-round1026-20260924-124338/` (`config/`, `services/`, `web/` снапшоты + `BASELINE.md` + `pytest.log`); `.env.bak.round1026-a1`; `stash@{0}` (round1025) не тронут; история не перезаписывалась, force-push/amend не применялись.
- Откат **не потребовался** — деплой и верификация успешны.

## 9. Честные ограничения

1. **Live-приёмка владельца — PENDING OWNER VERIFICATION.** Реальный direct-чат (§13/§14: намерение/адресат/память → инструменты → решение о действии → Вербализатор) в этом gate **не прогонялся** — события `[coordinator] decision`/`[coordinator] outcome` появятся на реальных ходах; OFF/legacy-эквивалентность и 2-вызовность подтверждены тестами (9 комбинаций @Reviewer + 56 тестов координатора).
2. **Флак `test_betterstack_handler.py::test_real_302_not_followed_by_opener`** — pre-existing (документирован с 10.19), вне diff A1, в изоляции 9/10 зелёный; два полных прогона @DevOps: 9081/1 (тот же тест), гейт @Reviewer: 9082/0. Рекомендация аудита S10.19-27 (flaky-marker/retry) остаётся открытой — не блокер A1.
3. **Техническая заметка подготовки коммита:** при стейджинге временная локальная настройка `core.autocrlf` привела к CRLF-индексации части тест-файлов; исправлено `git add --renormalize`, настройка восстановлена; финальный staged-diff кода/тестов **байт-в-байт** равен ревью-нормализованному diff (`ba471758…`) — в коммит ушло ровно проверенное содержимое.
4. **Счётный нюанс документации:** в `evidence.md`/`review.md` число re-pin тест-файлов указано 21; фактически **22** (проверено `--numstat`: все — только строки версии). Содержательного расхождения нет.
5. **WTH-дельта:** полный WTH рабочего дерева отличается от binding только служебным машинным блоком `plans/workflow_state.md` (обновлён `workflow_checkpoint` @Orchestrator после фиксации `review.md`) — принятый паттерн S6/S7/S8/S10; продуктовые/тестовые/спец-артефакты совпадают с ревью байт-в-байт.

---

## Handoff

**RESULT: VERIFIED (T-3522) @Orchestrator** — коммиты **`b32c46a`** (код+тесты+`config/settings.py`+`README.md`+meta, APP_VERSION 2.58.30) + **`b1c02a3`** (планы: feature-артефакты + аудит + MEMORY/state) + deploy-doc (этот файл); push `origin/master` **`e3ea367..b1c02a3`** без force; прод `/var/www/admin_bot` fast-forward **`04f5ae1..b1c02a3`** (2026-09-24 03:53 UTC); `systemctl restart` → **active** (MainPID **652183**, NRestarts 0, ExecMainStatus 0); `/api/health` **200**; `/healthz` **2.58.30**; served `?v=2.58.30` (×12, placeholder 0); **эффективный `DIRECT_COORDINATOR_ENABLED` = True** (code-default ON, `.env` без override — активация штатная, не заблокирована); `coordinator_enabled()` = True; импорт `services.direct_chat_service` OK; prompt-синк «уже новый канон» ×13 / обновлён ×0; `database is locked`=0; Traceback/ImportError/ERROR/CRITICAL=0; DDL=0; бот/планировщики стартуют; **Δ DDL=0**; §104/§85-UI/промпты/`tool_loop` вне diff. Откат: soft `DIRECT_COORDINATOR_ENABLED=false`+рестарт; hard `pre-round1026-a1` → `e3ea367` + `git revert b32c46a b1c02a3`; бэкапы/тег/`stash@{0}` целы (R18). Далее по процессу: @Orchestrator (reconciliation/checkpoint), T-3520/T-3521 (merge/архивация) и T-3523/T-3524 (@PM) — вне T-3522; затем **A2** (`tool-chains`, §15–§17). Live-приёмка §13/§14 — **PENDING OWNER VERIFICATION**.
