# MCA-10a `mca-10a-random-source-anu` — evidence (T-4966…T-4983, блоки A–E + сводный пакет)

**Дата:** 05.10.2026. **Роль:** @Builder (Step 3, блоки A+B). **Санкции:** ADR-1028-14 / spec §13
(D1–D12), `DESIGN_FROZEN`. `plans/current_task.md` не изменялся (R17).

**Fingerprint:** HEAD `c49ee02` (docs PM-archive; спец-база `8ea8c1f` + docs) + рабочее дерево
(ниже). Python 3.12.0, `.venv`. Прод-версия не менялась: `APP_VERSION=2.58.57` (bump — T-4985).

## Изменённые компоненты

| Файл | Δ |
|---|---|
| `services/mca_random_source.py` | **new** — единственный сервис: `RandomSourceService` (async), `ExplorationPolicy` (чистая логика + DI), `CoreDreamRandomSource` (sync-адаптер mca-06), `AnuClient`, `RandomStore` (v27) |
| `services/database.py` | Δ DDL **v27**: 4 таблицы + 3 индекса, `MigrationStep(27,"random_source")`, self-guard, PG no-op |
| `config/settings.py` | K1–K4 (`MCA_RANDOM_*_ENABLED`, env-only, default ON) + env-лимиты (circuit 3/60, min interval 1.0, retention 90/10000, Trial 100/1rps, hex size 4) |
| `services/mca_gates.py` | `KILL_SWITCHES` +4 + резолверы (`random_*_enabled`, лимиты; не бросают) |
| `services/mca_events.py` | `REASON_CODES` **ровно +2**: `quantum_activated`, `quota_exhausted` (единый словарь) |
| `services/dream_worker.py` | стык mca-06 без fork: `await mca_random_source.for_dream(...)` вместо `default_source` (K1 OFF → бит-в-бит default); снят неиспользуемый импорт |
| `bot.py` | `bind_db(db)` + один refill/активация при старте (fail-open; K1/K2 OFF → no-op) |
| `tests/test_mca10a_random_source_block_a_round1037.py` | **new** — T-4970 |
| `tests/test_mca10a_random_source_block_b_round1037.py` | **new** — T-4975 |
| `tests/test_mca01_tx_task_supervisor_round1027.py` | allowlist write-точек `database.py` 162→165 (v27: 3 commit, L-MCA14-3) |
| `tests/test_mca05_episodes_stories_round1027.py` | tail-mark реестра v26→v27 (конвенция волн) |
| `tests/test_mca08_style_form.py` | `_tail_version()` вместо хардкода 26 (fresh/reinit/v25→v26-тест) |

## Focused-проверки (точные команды и числа)

```
.venv\Scripts\python.exe -m pytest tests/test_mca10a_random_source_block_a_round1037.py -q
  → 19 passed (3.14s)   # A18: rejection/uniformity, choose (пул без основного,
                          # одна проверка, недопустимые измерения, K4 OFF,
                          # воспроизводимость по журналу), режимы/hot-персистентность,
                          # PRNG auto-seed/source_impl, n=1 без расхода,
                          # durable-запас/crash-семантика, стык mca-06 (K1 OFF
                          # byte-for-byte default; chunk+flush; fallback OFF→None)
.venv\Scripts\python.exe -m pytest tests/test_mca10a_random_source_block_b_round1037.py -q
  → 20 passed (3.62s)   # A19: origin-guard, контракт клиента (params/типы/hex/
                          # validation/redirect/401+breaker half-open/429
                          # Retry-After/min interval/timeout sent vs Connect),
                          # активация (реальная партия→quantum_activated; 200-без-
                          # валидации≠активация; блокеры; смена ключа→unverified→сразу),
                          # квота (global/оценка/unknown≠failed/period-rollover F-1),
                          # fallback on/off, refill watermark/buffer/K3,
                          # singleflight+task_jobs, авто-возврат к quantum
.venv\Scripts\python.exe -m pytest tests/test_mca14_schema_additive_round1027.py \
  tests/test_mca01_tx_task_supervisor_round1027.py \
  tests/test_mca13_event_contract_round1027.py tests/test_mca06_sleep_i_round1037.py \
  tests/test_mca08_style_form.py tests/test_mca05_episodes_stories_round1027.py \
  tests/test_mca11_money_limits_round1028.py tests/test_dream_worker.py -q
  → 281 passed (22.23s)
.venv\Scripts\python.exe -m pytest tests/test_round1025_f8_registry.py -q
  → 29 passed (2.70s)   # каталог не менялся (Δ=0 в блоках A+B; F8 — блок C)
```
Итого focused: **349 passed, 0 red** (полный suite не гонялся — по санкции; платных вызовов нет).

## F-1 (review Medium, micro-round) — period-aware квота

* **Finding:** `quota_record`/`quota_snapshot` не сбрасывались по `period` — после
  первого месяца Trial «оценка» показывала `remaining=0` навсегда при видимом
  текущем периоде (нечестное число на витрине; безопасное направление — 429
  остаётся авторитетным).
* **Fix (только `services/mca_random_source.py`, `RandomStore.quota_record` +
  `quota_snapshot`):** UPSERT сбрасывает счётчики прошлого периода до инкремента
  (`CASE WHEN mca_random_quota_state.period = excluded.period ...`), `last_*`
  очищаются/обновляются по тому же условию; снимок при stale-периоде читается
  read-only как нули текущего периода. 429/`last_reason`, `unknown ≠ failed`,
  K2/fallback-логика не менялись; Δ DDL=0 (схема v27 не тронута).
* **Pre-fix RED (доказательство):** новый тест
  `test_quota_period_rollover_honest_remaining` до фикса падал
  `assert 100 == 0` (snapshot тащил счётчики прошлого месяца); после фикса — passed.
* **Рerun:** quota-focused `-k quota` → **3 passed**; block B → **20 passed**;
  block A → **19 passed**.

## OFF-паритет (проверен тестами)

* **K1 OFF** → `for_dream` возвращает `DeterministicUniformRandomSource`; items/meta
  **равны** `mca_dream_random.default_source` (byte-for-byte); draw → deferred
  `disabled`, новых записей нет; события не эмитятся (`_emit` gated).
* **K2 OFF** → effective=pseudorandom с причиной `disabled`; квантовый запас не
  расходуется; fallback OFF → отложено с `disabled`; ANU-запросов нет.
* **K3 OFF** → `refill_if_needed` = disabled, HTTP-запросов 0.
* **K4 OFF** → `choose` = primary, probability-draw 0.
* **fallback=false** → PRNG-подстановки нет; необязательное отложено с причиной
  (`provider_unconfigured`/`disabled`), сеть не вызывается (draw — локальный);
  прямые функции не затронуты (код-путь не изменён).

## Δ DDL v27 — локальная верификация (факты)

* fresh: `PRAGMA user_version=27`; таблицы `mca_random_batches`, `mca_random_draws`,
  `mca_random_quota_state`, `mca_random_state`; индексы
  `idx_mca_random_batches_created`, `idx_mca_random_draws_created`,
  `idx_mca_random_draws_chat`; книга `schema_migrations` → (27, `random_source`).
* повторный `initialize` (рестарт): user_version 27, строк v27 в книге — 1 (0 дублей).
* симуляция прод-пути v26→v27 (drop v27-артефактов + `user_version=26`): миграция
  применилась; backup-guard создал `pre_migration_20261005_135813.db`, read-back
  копии = 26; повтор — no-op.
* PG: `rg -c "mca_random" services/pg_db.py` → **0** (PG no-op, GEN-R4).
* K1–K4: default ON, env-оверрайдов 0 (`config.settings` факт).
* Водяной знак/журнал: smoke — reserve/reopen → `reserved_upto` не сбрасывается,
  диапазон не выдаётся повторно; `prune` (90д/3 строки) удалил 2/5.

## R17 / секрет

* Ключ ANU — только header `x-api-key`; в URL/логах/событиях/таблицах его нет; в v27
  хранится только `key_fingerprint = sha256(key)[:12]` (сервер-only).
* Очищенная ошибка провайдера маскирует ключ (`***`) — тест `validation_failures`.
* Журнал draw: ровно 15 колонок (ID/числа/коды/enum; кандидаты — ID, cap 50),
  порог `probability` пишется в probability- и selection-строки (воспроизведение
  выбора без новых чисел), тест контракта колонок.

## Заметки для Builder-2 (блоки C–E + T-4983)

1. **T-4976/T-4977/T-4978 (блок C):** рантайм уже читает `keys.random_quantum_*`
   (`_hot_setting` с fail-open на дефолты) и `memory.random_*`
   (`worker_settings.resolve_setting`, per-chat) — нужны каталог (+13), Settings
   `RANDOM_QUANTUM_API_KEY` (secret-контур, `{configured,last4}`), F8-переиздание
   (489→502/105→107/103→105, TAB_RULES in-place, delta 78→91, secret 32→33, routes
   +1 `POST /api/random/test` → `service.test_connection(draft_key=...)`).
2. **Смена ключа без рестарта:** ключ резолвится per-call; после сохранения —
   следующий `activate()`/refill (кнопка) активирует сразу; состояние до проверки —
   `unverified` (реализовано).
3. **T-4979/T-4980 (блок D):** контракт готов — `status_snapshot()` (selected/
   effective/anu_state/blocker/reserve/last_batch/draws/quota/fallback),
   `recent_draws(limit, chat_id)`, `quota_snapshot()`; только чтение, без внешних
   вызовов; врезка в существующий «Статус».
4. **T-4981/T-4982 (блок E):** процесс `random.source` v1 в
   `mca_process_registry` ещё НЕ зарегистрирован (вне scope A+B). События уже
   эмитятся единым `emit_mca_event` (component `random`, notable-only):
   `random_activation`/`random_batch`/`random_fallback`; per-draw — журнал.
   REASON_CODES +2 исполнено.
5. **T-4983:** при сводном прогоне учесть обновления соседних тестов под v27-tail
   (`test_mca01` allowlist, `test_mca05` mark, `test_mca08` helper) — это следствие
   санкционированного Δ DDL, не регресс.
6. **T-4985 (deploy):** `APP_VERSION` не бампался (2.58.57 — шаг деплоя); миграция
   v27 идемпотентна/аддитивна, backup-guard проверен локально; live-ключ ANU —
   PENDING OWNER (T-4986), mock/fallback активацией не считается (конструктивно).

## Incidental findings (не блокируют, вне slice)

* `TaskSupervisor.run(kind="refill")` трактуется супервизором как второстепенный
  класс: при переполнении bounded-очереди refill отклоняется с видимой причиной
  `queue_full` и повторится на следующем draw/старте (spec D2 требует именно
  `kind="refill"`). Severity low, same-feature contract.
* Pre-existing (mca-01): во втором coalesce-окне `TaskSupervisor.run` коалесцированный
  дубликат может финализировать durable-строку первого владельца (`_safe_finish` с
  тем же job_id). Наблюдалось как возможный `cancelled` в `task_jobs` при гонке;
  singleflight/один HTTP-запрос сохраняются. Не чинилось (чужой контур, не влияет
  на корректность refill: батч один, квота одна).

---

# Блоки C–E + сводный пакет (T-4976…T-4983, 05.10.2026, Builder-2)

**Fingerprint:** HEAD `c49ee02` + рабочее дерево (uncommitted, продолжение блоков
A+B). Python 3.12.0, `.venv`; node v24.16.0. `APP_VERSION` НЕ менялся (2.58.57;
bump — T-4985). `plans/current_task.md` не изменялся (R17).

## Изменённые компоненты (C–E)

| Файл | Δ |
|---|---|
| `config/settings.py` | +13 instance-полей `RANDOM_*` (memory.random_* ×4 + keys.random_quantum_* ×9; Settings 426→439) |
| `services/param_catalog.py` | +13 ParamSpec, +2 GroupSpec (`memory_random` order 4 / `keys_random` order 9), TAB_RULES in-place (`mod_sleep`+memory_random, `llm_providers`+keys_random), +3 select-пресета (RANDOM_SOURCE/PLAN/DATA_TYPE) |
| `services/mca_random_source.py` | `test_connection` → singleflight (`_check_task`/`_check_key`: повторные клики — один запрос; неожиданный сбой → честный `provider_unavailable`, не 500) |
| `web/api/routes.py` | +1 route `POST /api/random/test` (RBAC: global admin ИЛИ право `key.keys.random_quantum_api_key`; draft-ключ только в body) |
| `services/status_service.py` | аддитивное поле `random` в `build_snapshot` + `random_source_snapshot`/`_public_draw` (read-only, whitelist, `key_fingerprint` наружу НЕ отдаётся) |
| `services/mca_process_registry.py` | процесс `random.source` v1 (7 стадий, 3 notable-события, widget-ID, `_GATE_RESOLVERS`+1) |
| `web/app.js` | зеркало TABS (memory_random/keys_random), computed `randomSource`, методы `checkRandomConnection`/`randomCheckStatus`/`onKeyDraft`, state |
| `web/index.html` | группа ANU: кнопка «Проверить подключение» + панель результата; карточка «Источник случайности» на «Статусе» с клиентским раскрытием решений |
| `plans/docs/param-registry-round1025.tsv/.meta.md`, `screen-map`, `widget-map` | F8-переиздание (502/107/105/21, delta 91) + строка врезки в widget-map |
| `plans/reports/round1025_f8_config_diff.md` | переиздан тулом (baseline-снимки, diff=0; актуальные счётчики срезов) |
| `tests/fixtures/round1025/*` | counts/sha256/routes/catalog-baseline переизданы |
| `tools/gen_param_registry_round1025.py` | R17-скан: только истинные секреты (`spec.secret`), не-секретные keys-поля не дают ложный leak («ANU Quantum Numbers»/«uint16») |
| `tools/_mca10a_reissue_f8.py` | **new** — одноразовый F8-переиздатель (артефакты + фикстуры + catalog-guard'ы) |
| `tests/test_mca10a_random_source_block_c_round1037.py` | **new** — T-4978 (22 теста) |
| `tests/test_mca10a_random_source_block_d_round1037.py` | **new** — T-4980 (9 тестов) |
| `tests/test_mca10a_random_source_block_e_round1037.py` | **new** — T-4982 (8 тестов) |
| `tests/test_mca10a_random_source_js_round1037.py` + `tests/js/round1037_random_source_test.js` | **new** — JS-прогон node (T-4977/T-4979) |
| 46+ test-файлов | catalog-guard'ы 489→502 / 105→107 / 103→105 / 464→477 / 426→439 / secret 31→32 (санкционированное F8-переиздание) |
| `tests/test_round1025_f8_registry.py` | counts/delta 91/secret 41/`ROUTES_SHA256_F11` переутверждён |
| `tests/test_frontend_tab_mapping.py` | mod_sleep + memory_random; +3 select в наборе |
| `tests/test_migrate_env_to_pg.py` | keys-инсерты 21→31 (пре-существующий red 22≠21 закрыт санкционным переизданием) |
| `tests/test_status_service.py`, `tests/test_webapp_status_control.py` | состав snapshot + `random` (санкция D9) |

## Focused-проверки (точные команды и числа)

```
.venv\Scripts\python.exe -m pytest tests/test_mca10a_random_source_block_a_round1037.py \
  tests/test_mca10a_random_source_block_b_round1037.py \
  tests/test_mca10a_random_source_block_c_round1037.py \
  tests/test_mca10a_random_source_block_d_round1037.py \
  tests/test_mca10a_random_source_block_e_round1037.py \
  tests/test_mca10a_random_source_js_round1037.py \
  tests/test_round1025_f8_registry.py -q
  → 107 passed (6.9s)   # A 19 + B 19 + C 22 + D 9 + E 8 + JS 1 + F8 29

.venv\Scripts\python.exe -m pytest <все изменённые tests/*.py (52) + test_webapp_api + \
  test_webapp_js_unit + test_webapp_status_control + test_mca17a + status_section> -q
  → 2084 passed, 5 failed (все — пред-существующие, см. ниже; 98.25s)

.venv\Scripts\python.exe -m pytest tests/test_mca06_sleep_i_round1037.py tests/test_dream_worker.py \
  tests/test_mca13_event_contract_round1027.py tests/test_mca14_schema_additive_round1027.py \
  tests/test_mca01_tx_task_supervisor_round1027.py tests/test_mca05_episodes_stories_round1027.py \
  tests/test_mca08_style_form.py tests/test_mca11_money_limits_round1028.py \
  tests/test_mca02_safe_fetch_round1027.py tests/test_chat_params.py tests/test_status_service.py \
  tests/test_param_catalog.py tests/test_frontend_tab_mapping.py tests/test_ia_inventory_round1025.py \
  tests/test_webapp_parity_smoke.py tests/test_settings_persistence_round1014.py \
  tests/test_migrate_env_to_pg.py -q
  → 529 passed (после фиксов 3-х count-guard'ов; первый прогон 526+3F)

node tests/js/round1037_random_source_test.js → MCA10A-RANDOM-OK
```

## F8 — Δ каталога и переиздание (факты)

* `gen_param_registry_round1025 --check` → **CHECK OK: реестр 502 == REGISTRY,
  карта полна, R17-чисто, TSV/map идемпотентны**.
* REGISTRY 489→**502**, GROUPS 105→**107**, `_TAB_BY_GROUP` 103→**105**,
  TAB_RULES **21 in-place**, delta 78→**91**, Settings 426→**439**,
  screen-map +13, routes +1 (`POST /api/random/test`),
  `ROUTES_SHA256_F11 = 797e0deb3b897c996e0e345ba72b8b87c265641eeaae4c2624a0185be212ecae`.
* **Отклонение от санкционной цифры «secret 32→33» (spec↔код-контрадикция,
  честно):** F8-артефакт считает секретом `spec.secret or category==keys`
  (belt-and-suspenders) → 32→**41** (+9 keys-полей). Истинных `secret=True`:
  31→**32** (+1 api_key; guard `pc_secret_names` обновлён). Санкционная «33»
  не соответствует ни одной из двух семантик; выбран честный вариант без
  искажения namespace-таблицы §9. **Решение для Reviewer/Orchestrator.**
* `config_diff` переиздан: baseline-снимки обеих сторон из одного каталога →
  diff=0; актуальные счётчики срезов (global 357 / prompts 24 / models 63 /
  connections 33 / roles 10).

## OFF-паритет (по каждому kill-switch; подтверждён тестами)

* **K1 OFF** → dream = `default_source` бит-в-бит (A); `POST /api/random/test`
  → `disabled`, HTTP-запросов 0 (C); блок «Статус» → `enabled=false/disabled`
  без данных, сервис не вызывается (D); registry `random.source` → `disabled`
  (E); ключи/настройки инертны (значения читаются, runtime-эффектов нет).
* **K2 OFF** → effective=pseudorandom + blocker `disabled`, ANU-запросов нет;
  блок честно без quantum-статуса (D).
* **K3 OFF** → refill не запускается (B).
* **K4 OFF** → `choose` = primary без probability-draw (A).
* **fallback=false** → PRNG-подстановки нет; необязательное отложено (A/B).

## R17-скан (ключ ANU)

* Статически: `RANDOM_QUANTUM_API_KEY`/`keys.random_quantum_api_key` встречается
  только в settings/catalog/routes/service-константах; `logger.*` в
  `mca_random_source.py` ключ не печатает (скан по logger-вызовам — 0 совпадений
  с `key`); ключ — только header `x-api-key` (B).
* Тесты: `test_draft_key_not_in_logs` (caplog, draft-ключ), маска в
  `GET /api/config` {configured,last4}, `POST /api/random/test` без эха ключа,
  журнал draw — whitelist (D), события — единый `build_event` (E), F8-артефакты
  R17-чисты (`--check` + `test_no_open_secrets_in_artifacts`).
* Секрет ANU не в localStorage: JS-проверки не пишут ключ в storage (draft —
  in-memory `keyDrafts`; отдельные assert'ы в
  `tests/js/round1037_random_source_test.js` на отсутствие
  localStorage/sessionStorage-записей ключа); бандл не содержит значения
  (секрет — PG/.env; `index.html` содержит только имя ключа в условии шаблона).
* UI-проверка выполнена node-прогоном + статическим wiring (`data-random-source`/
  `data-random-check`/`data-random-draws`); полноценный Playwright-E2E не
  гонялся (focused-пакет по санкции; требует живого TMA/PG-контура — T-4986
  live-часть PENDING OWNER).

## Пред-существующие красные (не наши; evidence)

1. `tests/test_telegram_reactions_round1026.py::TestBoundaries::test_direct_safety_net_calls_legacy`
   — `services/direct_chat_service.py` не менялся (git diff пуст; счётчик 3 и на
   HEAD, ассерт `== 2` тоже на HEAD) → red до нашей Δ.
2. `tests/test_webapp_js_unit.py::{hotfix7,hotfix8,hotfix9,hotfix10}` (4 JS-пина)
   — пины `/APP_VERSION = "2.58.49"/`, фактический HEAD 2.58.57; JS-файлы и
   строка APP_VERSION нами не тронуты → red до нашей Δ; закрываются штатным
   release-pin bump на T-4985 (2.58.58).

## Заметки для T-4985 (deploy) / T-4986 (live)

* `APP_VERSION` не бампался (2.58.57); при бампе обновить 23+ release-pin теста,
  включая 4 JS-пина выше, и `plans/docs/param-registry-round1025.meta.md`.
* PG-миграция (`scripts/migrate_env_to_pg.py`) при деплое засидит 13 новых
  ключей (dry-run: keys 31; секрет — пусто/`configured`), без неё настройки
  видны только после сохранения; runtime работает на code-defaults.
* Live-ключ ANU — PENDING OWNER (T-4986): `POST /api/random/test` с реальным
  ключом + кнопка «Сохранить и применить»; mock/fallback активацией не считается.
