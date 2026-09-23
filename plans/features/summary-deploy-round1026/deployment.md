# deployment.md — S10 `summary-deploy-round1026` (T-3478, @DevOps — прод-поставка и активация)

> **Feature:** `summary-deploy-round1026` (Эпик 2, §107/§114/§115/§116/§117; ADR-1026-12 D1–D8) · **Дата:** 2026-09-24 · **Оператор:** @DevOps
> **Базис до деплоя:** HEAD **`76abf91`** == `origin/master` (closing-docs S6); annotated-тег **`pre-round1026-s10`** (tag-obj **`be7760295`**) → **`76abf91`**; релизные коммиты **`415a861`** (код+тесты) + **`04f5ae1`** (планы).
> **Окружение:** прод `/var/www/admin_bot` (`nik@198.46.175.136`), systemd-юнит `admin_bot`, venv Python 3.12 (`venv/bin/python`).
> **Решение ADR-1026-12 D7:** deploy = **ДА**, bump `APP_VERSION` 2.58.28 → **2.58.29**; версия риска **R2**. Единый Reviewer gate — **Approved C0/H0** (отдельного Scanner-approval нет).

## Вердикт: **VERIFIED** ✅

Рантайм S10 доставлен на прод и **активация Hybrid-пайплайна Саммари подтверждена на уровне эффективного значения**: fast-forward **`cebd950..04f5ae1`**, сервис `active (running)` (MainPID **595858**, NRestarts **0**, ExecMainStatus **0**), `/api/health` = **200**, `/healthz` version = **2.58.29**, served cache-bust `?v=2.58.29` = **12** (placeholder `__APP_VERSION__` = **0**), `APP_VERSION` прод-venv = **2.58.29**, **эффективный `SUMMARY_HYBRID_L2_ENABLED` = True** (code-default ON; `.env` без override), `SUMMARY_FILTER_ENABLED` = **True**, слоты `SUMMARY_L1_*`/`SUMMARY_L2_*` пусты → глобальная модель, канон L1/L2 и миграции промптов импортируются, `database is locked` = **0**, Traceback/ImportError/CRITICAL/ERROR после рестарта = **0**, бот и планировщик Саммари стартуют, **Δ DDL = 0** (миграции не запускались), §104-контур не тронут. **§115 пп.1–4 подтверждены сейчас; пп.5–7 (штатный запуск/логи/публикация) — PENDING OWNER VERIFICATION на ближайшем плановом тике (0/6/12/18 Asia/Yekaterinburg).**

---

## 1. Коммиты и push

| Что | Commit | Сообщение | Файлов |
|---|---|---|---|
| Код + тесты + `config/settings.py` + docstrings + `README.md` + провенанс-штамп meta | **`415a861`** | `feat(round1026): S10 — активация Hybrid-пайплайна Саммари (SUMMARY_HYBRID_L2_ENABLED default ON, §107) + §114-harness + §117 results (APP_VERSION 2.58.29)` | 38 (+706/−79) |
| Планы: feature-папка S10 + `audit_backlog` + `MEMORY`/`workflow_state` | **`04f5ae1`** | `docs(plans): round1026 S10 — ревью-артефакты, §115/§117, аудит (единый Reviewer gate, binding 76abf91)` | 11 |
| deploy-doc (этот файл) | см. docs-коммит ниже | `plans/features/summary-deploy-round1026/deployment.md` | 1 |

- **Push:** `origin/master`, **без force** — **`76abf91..04f5ae1`** (коммиты 2026-09-24 11:06:51 / 11:06:58 +12). `origin/master` == `04f5ae1`.
- **Иммутабельные артефакты (git-объекты):** tree `415a861` = **`ece707e75e16c3a57e42350d206432011000705a`**; tree `04f5ae1` = **`2404b8771be36b7ee18e5657a4d74da044f74ba9`**.
- `APP_VERSION`: **2.58.28 → 2.58.29** (bump в `config/settings.py`, cache-bust `?v=__APP_VERSION__`, README `v2.58.29`).
- `plans/current_task.md` и машинный блок `OPENCODE_WORKFLOW_STATE_V1` вручную не редактировались; amend/force не применялись. Секреты не коммитились (`.env`/`media/`/`deploy_commands.txt` — вне коммитов).

## 2. Проверка привязок Reviewer (T-3474/T-3475) перед релизом

- **Reviewed-Commit `76abf911eee7ffc731cbf0fa9a2227b1a21f8c38`** — подтверждён: локальный HEAD до коммитов == `origin/master` == цель annotated-тега `pre-round1026-s10` (tag-obj `be7760295`; проверено `git show-ref --tags`).
- **Spec-Hash `41ee0c6e7b102a21be34223578df0fbb03b759741a911ce39be9b34c8079ae3c`** — пересчитан байт-в-байт (SHA-256 `spec.md`) — **совпал**.
- **Working-Tree-Hash `a17093d83db7a8434411567090611b1502264d4eb52a38c60a07ca6ea18646a9`** — структура рецепта воспроизведена **точно**: из заявленного в `review.md` diff-SHA `8b8fd7c3…` + 8 per-file хэшей untracked-файлов повторно вычислен ровно `a17093d8…`.
  - **Все 8 untracked-хэшей совпали байт-в-байт** с `review.md`: adr `9de3e08e…`, evidence `75977629…`, procedure-115 `f2118692…`, results `781867a0…`, sec114-harness `b5fac423…`, spec `41ee0c6e…`, tasks `c2bf9b55…`, `tests/test_summary_deploy_round1026.py` `8d502858…`.
  - **Все 20 хэшей product code/тестов/конфига из `evidence.md` §7 пересчитаны — MATCH** (`config/settings.py`, `services/summary_generator.py`, `services/summary_l2_writer.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md` + 15 тест-модулей).
  - **Единственная дельта дерева от ревью-состояния** — служебный машинный блок `plans/workflow_state.md` (обновлён `workflow_checkpoint` @Orchestrator; mtime **10:52:53**, уже **после** финализации `review.md`) и служебная запись аудита `plans/reports/audit_backlog.md` (mtime **10:51:39**). Поэтому текущая diff-компонента WTH (`git diff 76abf91` = `01a593bb…`) не совпадает с ревью-значением байт-в-байт — **тот же принятый паттерн, что в S6/S7/S8** (служебная запись после фиксации вердикта).
  - **Product code / тесты / конфиг / spec после ревью не менялись:** mtime всего кода/тестов/`config/settings.py`/`README.md` ≤ **10:31:15**, `audit_backlog.md`/`workflow_state.md` — служебные (позже, оркестратор-managed). Материального дрейфа нет → к деплою допущено.

## 3. Локальный CI перед коммитами (воспроизведено @DevOps)

| Проверка | Команда | Результат |
|---|---|---|
| Полный регресс pytest | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=120` | **9026 passed / 0 failed** (151.61 s, 1 warning) — совпадает с ревью (9026/0) |
| JS (все файлы) | цикл `node tests/js/*.js` (47 файлов) | **OK=47 FAIL=0** — совпадает с ревью (47/47) |
| `git diff --check` | — | exit **0** |
| Каталог параметров | `tools/gen_param_registry_round1025.py --check` | **CHECK OK**: реестр 469 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны |
| Версия | импорт `config.settings` | `APP_VERSION` **2.58.29**; README `v2.58.29` |
| Секрет-скан релизного diff + untracked | regex `api_key/secret/password/bearer/private key/sk-…/bot-token` | diff: только имя env-переменной `SUMMARY_L2_API_KEY` (пустой default); untracked: R17-тест-константа `_SECRET` + проза `results.md`/`spec.md` — **реальных секретов нет**. `.env`/`media/`/`deploy_commands.txt` в коммиты не входили (gitignored) |
| Флак-кандидат | повтор полного прогона после teardown-таймаута `test_summary_memory.py` | **9026/0** (флак D-c не воспроизвёлся; см. §10) |

## 4. Прод-деплой (traceable)

- **Сервер до деплоя:** HEAD `cebd950`, `APP_VERSION` 2.58.28, `admin_bot` — `active`, MainPID **575712**, NRestarts 0; 13 pre-existing untracked `*.bak`-файлов (не наши, не тронуты; до/после — 13).
- **Pull:** `cd /var/www/admin_bot && git pull --ff-only origin master` → **`cebd950..04f5ae1` Fast-forward** (включает S6 closing-docs `b889019`/`76abf91` + релиз S10 `415a861`/`04f5ae1`). После pull HEAD = **`04f5ae1`** == `origin/master`.
- **Restart:** `sudo -n systemctl restart admin_bot` → exit **0**; сервис `active` с **2026-09-23 23:08:27 UTC** (`ExecMainStartTimestamp`/`ActiveEnterTimestamp`).
- **Состояние:** MainPID **595858**, NRestarts **0**, ExecMainStatus **0**, ActiveState `active`.

## 5. Health / смоук-проверки (факт)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active (running)** ✅ |
| `GET /api/health` (127.0.0.1:8000) | **HTTP 200** ✅ |
| `GET /healthz` | **HTTP 200** `{"status":"ok","version":"2.58.29"}` ✅ |
| served cache-bust `/web/` | `?v=2.58.29` — **12** вхождений; placeholder `__APP_VERSION__` = **0** ✅ |
| `APP_VERSION` в venv прода | **2.58.29** ✅ |
| Импорт изменённых модулей (prod venv) | `config.settings`, `services.summary_prompts`, `services.prompt_migrations`, `services.param_catalog` → **OK**; `PROMPT_MIGRATIONS`-реестр присутствует ✅ |
| `database is locked` (журнал, окно после рестарта, 168 строк) | **0** ✅ |
| Traceback / ImportError (с рестарта) | **0** ✅ |
| ERROR / CRITICAL (с рестарта) | **0** ✅ |
| DDL-операторы в логах (`CREATE/ALTER/DROP TABLE|INDEX`) | **0** ✅ |
| `PUBLISH_*` / `SUMMARY_START` в логах | **0 / 0** ✅ — до ближайшего реального прогона Саммари (события аддитивны; это норма) |
| Старт бота | `Start polling` / `Run polling for bot` ✅ |
| Планировщики (apscheduler + Саммари) | `Scheduler started` (×6) / `SummarySchedulerService` initialized ✅ |
| Миграции БД | не запускались; **Δ DDL=0** — `git diff --name-only cebd950..HEAD -- db` = **0** ✅ |

## 6. Верификация активации (§107; §115 пп.1–4)

- **(а) Эффективное значение (прод-venv):** `SUMMARY_HYBRID_L2_ENABLED` = **True** (code-default ON после bump 2.58.29) ✅
- **(б) Прод-`.env`:** ключ `SUMMARY_HYBRID_L2_ENABLED` — **отсутствует** (`grep -c '^SUMMARY_HYBRID_L2_ENABLED' .env` = **0**) → override нет, активация произошла штатно (не заблокирована) ✅
- **(в) Фильтр + роутинг + промпты:** `SUMMARY_FILTER_ENABLED` = **True** (default ON, не менялся); ключ `flags.summary_hybrid_l2_enabled` — **не в каталоге** (`get_by_pg_key(...) is None`), `flags.summary_filter_enabled` — **в каталоге**; слоты `SUMMARY_L1_MODEL_NAME`/`SUMMARY_L2_MODEL_NAME` = `''` → глобальная основная модель; канон L1/L2 и миграции промптов импортируются ✅
- **Резолв-цепочка** `per-chat → hot → env/default` сохранена байт-в-байт (AST-идентичность подтверждена ревью); при отсутствии override эффективный режим = **ON** без ручного действия. «Ручная активация» не выполнялась (запрещена §107).
- **Kill-switch (готов, не исполнялся):** явный `SUMMARY_HYBRID_L2_ENABLED=false` в `.env` + рестарт → возврат к legacy `_generate_two_call`; либо non-catalog `flags.summary_hybrid_l2_enabled=false`; либо per-chat override.

## 7. §115 — статус проверок

| # | Проверка | Статус |
|---|---|---|
| 1 | Hybrid активен | ✅ подтверждено сейчас: эффективный `SUMMARY_HYBRID_L2_ENABLED` = **True** |
| 2 | Фильтр включён | ✅ подтверждено сейчас: `SUMMARY_FILTER_ENABLED` = **True** |
| 3 | Модели L1/L2 | ✅ подтверждено сейчас: слоты пусты → глобальная модель (независимый резолв сохранён) |
| 4 | Загрузка промптов | ✅ подтверждено сейчас: канон L1/L2 + `PROMPT_MIGRATIONS` импортируются |
| 5 | Штатный запуск | ⏳ **PENDING OWNER VERIFICATION** — ближайший плановый тик cron **0/6/12/18 Asia/Yekaterinburg** (не триггерился искусственно) |
| 6 | Логи всех этапов | ⏳ **PENDING OWNER VERIFICATION** — появятся на первом рабочем прогоне (`SUMMARY_START(mode=hybrid_l2)` → … → `SUMMARY_COMPLETE`) |
| 7 | Публикация | ⏳ **PENDING OWNER VERIFICATION** — rich (`PUBLISH_RICH_COMPLETE` + `message_id`) либо plain (`PUBLISH_TEXT_COMPLETE`); качество rich/plain — владелец |

**Примечание.** §114-предполётный harness (11/11, 0 реальных отправок) выполнен локально до деплоя — `sec114-harness.md`; тестовые результаты в основной чат **не публиковались**. Публикация §115 п.5/7 — легитимный первый рабочий прогон (в этом и смысл проверки).

## 8. Инварианты

- **Δ DDL = 0** (миграции не запускались; `db/**` вне диапазона деплоя; 0 DDL в логах).
- **Δ каталога = 0** — `services/param_catalog.py` вне diff; F8 не переиздаётся; `--check` OK (реестр 469).
- **0 новых внешних зависимостей** (манифесты/локи вне diff); **CSP/zero-build** (`web/**` вне diff); **2-вызовность** (0 новых LLM-вызовов).
- **§104-контур не тронут:** `git diff --name-only 76abf91..HEAD -- services/image_generation.py services/telegram_send.py services/summary_prompts.py services/summary_test_run.py web/api/routes.py db services/param_catalog.py bot.py` = **0**.
- **R17:** логи/события — числа/коды/id; сырые тексты/ключи не логировались (секрет-скан чист; `_SECRET`-константа — только тест).
- Pre-existing untracked `*.bak` на проде (13) не трогались.

## 9. Откат (готовность; не исполнялся) и R18

- **Soft (обратимый, без переписывания кода):** `SUMMARY_HYBRID_L2_ENABLED=false` в `.env` + `sudo -n systemctl restart admin_bot` → возврат к legacy `_generate_two_call`; либо non-catalog `flags.summary_hybrid_l2_enabled=false`; либо per-chat override.
- **Жёсткий:** `git revert 415a861 04f5ae1` (или `git checkout pre-round1026-s10`) + рестарт.
- **Тег:** annotated **`pre-round1026-s10`** → **`76abf91`** (tag-obj `be7760295`; цель отката, `APP_VERSION` 2.58.28).
- **Бэкапы (R18, не удалялись):** `var/backups/s10-round1026-20260924-100654/` (5 items) + `.env.bak.round1026-s10`; `stash@{0}` (round1025) не тронут; история не перезаписывалась, force-push/amend не применялись.
- Откат **не потребовался** — деплой и верификация успешны.

## 10. Честные ограничения

1. **Live-приёмка владельца — PENDING OWNER VERIFICATION.** Реальная публикация Саммари в Telegram (rich с обложкой/H1 либо plain с жирным заголовком) в этом gate **не выполнялась** — искусственно публикация в основной чат **не триггерилась**; §115 пп.5–7 ожидают ближайшего планового тика (0/6/12/18 Asia/Yekaterinburg).
2. **`PUBLISH_*` / `SUMMARY_START` = 0 сейчас — ожидаемо:** события появятся при первом реальном прогоне; аддитивность и R17-safe подтверждены ревью.
3. **WTH-дельта:** полный WTH рабочего дерева отличается от binding только служебными записями `plans/workflow_state.md` (машинный блок, обновлён `workflow_checkpoint` @Orchestrator) и `plans/reports/audit_backlog.md` (запись аудита) — тот же принятый паттерн, что в S6/S7/S8; продуктовые/тестовые/спец-артефакты совпадают с ревью байт-в-байт.
4. **Feature-артефакты после ревью не изменялись** (сохранение байт-точности ревью-манифеста); деплой-факты зафиксированы здесь (не в `evidence.md`/`procedure-115.md`/`results.md`).
5. **Флак `test_summary_memory.py`** (teardown-таймаут Windows asyncio) встретился при первом прогоне и не воспроизвёлся при повторе (9026/0) — инфраструктурный шум D-c, не регресс.

---

## Handoff

**RESULT: VERIFIED (T-3478) @Orchestrator** — коммиты **`415a861`** (код+тесты+`config/settings.py`+docstrings+`README.md`+meta, APP_VERSION 2.58.29) + **`04f5ae1`** (планы: feature-артефакты + аудит + MEMORY/state) + deploy-doc (этот файл); push `origin/master` **`76abf91..04f5ae1`** без force; прод `/var/www/admin_bot` fast-forward **`cebd950..04f5ae1`** (2026-09-23 23:08 UTC); `systemctl restart` → **active** (MainPID **595858**, NRestarts 0); `/api/health` **200**; `/healthz` **2.58.29**; served `?v=2.58.29` (×12, placeholder 0); **эффективный `SUMMARY_HYBRID_L2_ENABLED` = True** (code-default ON, `.env` без override — активация штатная, не заблокирована); `SUMMARY_FILTER_ENABLED` = True; L1/L2-слоты → глобальная модель; промпты/миграции импортируются; `database is locked`=0; Traceback/ERROR/CRITICAL/ImportError=0; бот/планировщик стартуют; **Δ DDL=0**; §104-контур не тронут. §115 пп.1–4 — ✅ сейчас; пп.5–7 — **PENDING OWNER VERIFICATION** (ближайший тик 0/6/12/18 Asia/Yekaterinburg). Откат: soft `SUMMARY_HYBRID_L2_ENABLED=false`+рестарт; hard `git revert 415a861 04f5ae1` / `checkout pre-round1026-s10`; бэкапы/тег/`stash@{0}` целы (R18). Далее по процессу: @Orchestrator (reconciliation), merge/архив (T-3476/T-3477 при необходимости), @PM/@Memory, метрики, handoff Эпика 2 (T-3479/T-3480).
