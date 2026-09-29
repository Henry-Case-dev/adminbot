# `mca-17a-observability-core` — единый Reviewer gate (T-3885, round 10.27)

> **Итерация 2 (повторный gate).** Прошлый вердикт — `Needs Fixes` (High F1/F2,
> Medium F3/F4, F5→@Architect). Builder выполнил rework (F1/F2/F3/F4 + Lows
> F6/F8/F9/F10/F11), @Architect санкционировал F5 в scope `mca-17a`
> (AMEND F5/ADR-1027-8 **D16**) и Builder дореализовал read-only данные-API
> ядра + refresh существующего индикатора ≤10 s. Spec/ADR изменились → binding
> **пересчитан** (старые `spec bd2a5249…`, `adr 98b20fa9…` устарели).

- **Feature-ID:** `mca-17a-observability-core`
- **Risk-Level:** **R3** — ратифицирован (подтверждён фактическим diff:
  `flush_events`/`prune_events` подключены в фоновый контур и конкурируют за
  single-writer lock с direct flow; v19 меняет схему; watchdog меняет
  durable-статусы; read-only transport инцидентов/реестра — под RBAC).
- **Status:** **Approved** — блокирующих findings нет. F1–F11 **закрыты**;
  F12 (промежуточно заподозрен) **опровергнут** независимой проверкой.
- **Deploy:** `DEFERRED_TO_RELEASE` (пер-фичевого деплоя нет).
- **ADR-1027-8:** `Proposed` на момент ревью; переводится в `Accepted` через
  Merge §100+ (следующий шаг @Architect — Merge §100+ по `Approved`).

## Binding (пересчитан по рабочему дереву, итерация 2)

- **Reviewed-Commit:** `05bc8704c2de5e7de1d5d04ac34df763d35219aa` (master).
- **Working-Tree-Hash (manifest):**
  `462e721b3a8230e65a2f86bb364468952b7e03a61e3f2df422497b0cf35218c0`.
  Manifest = sha256(`commit` + sha256(`git diff HEAD --binary`) + отсортированные
  строки `relative_path sha256(file)` по всем 81 untracked-файлам (кроме
  `node_modules/` и самого `review.md`). Diff-поток sha256 =
  `a1c1e1c224a75fbdf625e55e6edbd98b701900fa15b3daf67e7809e8d8e04c66`
  (9 461 117 байт).
- **Spec-Hash:** `c1378300c03ba3e5eb5b535610d0d2cabf9bebf46c569b08ae3ebebf5c65e4ca`
- **Tasks-Hash:** `ad045d1e0c616a7c3e3faf128040547d97a6759553c2e6aaca0b536e0118cb97`
- **ADR-Hash (`adr-1027-8-observability-core.md`):**
  `2a2ed9893052c90174d4fbf4b5f5285a63436b3562bf4af3acd427ecc79733f1`
- **Evidence-Hash:** `ae0d96e2ff7ab70d180ad3ce023ff03c13dae3564d9312700e56cf5d338ac207`
- **Threat-Hash:** `36e486a08506621ba4aa197c559f6292b2a905d641a75aaf70b289a7d7bbe89d`
- **Git base и inspected scope:** база — `05bc870`; модули mca-17a —
  `mca_process_registry.py`/`mca_trace.py`/`mca_incidents.py`/`mca_watchdog.py`
  (NEW, untracked), `mca_events.py`/`task_supervisor.py`/`database.py`/
  `mca_gates.py`/`config/settings.py`/`web/api/oversight.py`/`web/api/routes.py`/
  `web/app.js`/`web/index.html`/`bot.py`, `tests/test_mca17a_…py`,
  `tests/js/round1027_mca17a_ui_test.js`, `tools/ui_round1027_mca17a_observability.py`.
  `services/pg_db.py`, `param_catalog.py`, `plans/current_task.md` — **не тронуты**.

## Checks performed (независимо, в этой сессии)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest `.venv` | `python -m pytest -q -p no:cacheprovider` | **9828 passed, 0 failed, 1 warning** (247 s) |
| Focused mca-17a | `pytest tests/test_mca17a_observability_core_round1027.py -q` | **70 passed** (6.4 s) |
| JS vm-харнесс | `node` по каждому из 48 файлов `tests/js/*.js` | **48/48 OK** |
| `git diff --check` | — | чисто (только CRLF-warning autocrlf, exit 0) |
| Browser-Verification (Playwright) | `python tools/ui_round1027_mca17a_observability.py` | **0 failures**; SC-13/13b/14/16 |
| F1 grep-сверка | `test_registry_event_names_exist_in_code` + ручной скан `emit_mca_event/emit_stage/emit_stage_event` | каждое объявленное имя существует в коде |
| F1 flip-проверка | all 7 инструментированных процессов с реальными событиями | **`implemented`** (7/7) |
| F2 своп-очередь | чтение `flush_events` + `test_flush_concurrent_emit_not_lost`/`…failure_keeps_new_events` | потерь нет; счётчики честные |
| F5 endpoints | чтение `web/api/oversight.py` + 4 endpoint-теста + browser SC-16 | аддитивно на `oversight`, RBAC/cursor/гейты OK |
| Baseline-дефект `execMetricsRows` | `git show HEAD:web/app.js` / `HEAD:web/index.html` | дефект есть в baseline → не регресс |
| Re-pin/AMEND тестов | diff `tests/**` | только version/count/boundary/sha256; структурные проверки сохранены |

Browser-проверка — проектный Playwright-харнесс (тот же dev-стек, что
`tools/ui_round1025_matrix.py`): перехват `/api/*`, реальные `web/index.html`+
`web/app.js`, viewport 1280×800. Артефакт: `tools/_ui_round1027_mca17a.json`
(`sc13.text`, `sc14.text`, `sc16.changes_calls=[0,1,2,3,4,5]`,
`sc13b.badge_classes="badge badge-muted badge badge-warn"`,
`baseline_console_errors=2`). Отдельный Browser Use не требовался.

## Requirement/evidence coverage

- **SC-01/SC-02 (реестр процессов) — F1 ЗАКРЫТ.** `PROCESS_REGISTRY` (41 процесс):
  закрытые фичи ссылаются на **фактически эмитируемые** имена —
  `identity.resolve`→`message_revision`/`message_identity_migration`;
  `web.fetch`→`safe_fetch`; `provenance.record`→`memory_provenance`;
  `retrieval.query`→`mca07_retrieval`/`_reranker`/`_bundle`/`_budget`;
  `direct.reply`→`mca07_answer_cache`; mca-17a→`WATCHDOG_SWEEP`/`WATCHDOG_TAKEOVER`/
  `INCIDENT`. Независимо проверено: подача каждого процесса его реальных событий
  → **`implemented` для всех 7 инструментированных процессов**. Неинструментированные
  процессы — пустые `instrumentation`/`event_names` → честный `not_instrumented`.
  Placeholders `mca-09/10a/10b/11/15/16/18/19/20` — version `"0"` → `not_run`.
- **SC-03…SC-06** (trace/span, correlation, root+batch, monotonic/sequence): ok.
- **SC-07…SC-10** (lifecycle/honest outcome/linked job/interrupted): ok.
- **SC-11…SC-14** (heartbeat/watchdog/recovery/fencing): mechanisms ok; L-MCA01-5
  закрыт (fencing передан в cancelled/failed симметрично success; поведенческий
  takeover-тест `…cancelled_fencing_noop_after_takeover`).
- **SC-15/SC-16 (инциденты/доставка) — F5 ЗАКРЫТ.** Read-only данные-API ядра
  на **существующем** роутере `oversight`; RBAC global-admin; cursor-догон;
  refresh существующего индикатора `min(push_interval,10)s`.
- **SC-17 — F2 ЗАКРЫТ** (своп-очередь; молчаливой потери нет).
- **SC-18/SC-19** (control-plane/13 сценариев): ok.
- **SC-20 (REUSE, второй store запрещён):** подтверждено (`test_reuse_no_second_store`).
- **SC-21 (v19 аддитивна/идемпотентна/PG no-op):** подтверждено (6 тестов).
- **SC-22 (живые продюсеры метрик + wiring flush/prune):** ok (+ master-aware фон).

## Focused audit coverage

- **F1 на diff:** каждое из 87 объявленных имён событий встречается в коде;
  grep-тест осмыслен (`safe_fetch`/`message_revision`/`memory_provenance`/
  `WATCHDOG_*`/`INCIDENT`/mca07-префикс). Реальное событие переводит процесс
  `not_run → implemented`; `not_instrumented` честен.
- **F2 на diff:** `flush_events` снимает снимок и `_pending.clear()`
  **синхронно, без `await`** между ними; события, эмитированные во время
  `await write_transaction`, попадают в уже пустую очередь. Failure-ветка
  `_spool_append(pending)` спулит снимок, новые остаются. `dropped`/`gaps`
  инкрементируются при переполнении/исчерпании spool.
- **F5 на diff:** `GET /api/oversight/{processes,incidents,incidents/changes}` —
  аддитивно на `oversight_router` (новая панель/маршрут не созданы); RBAC
  `requires_global_admin()`; гейты `MCA_PROCESS_REGISTRY_ENABLED`/
  `MCA_INCIDENTS_ENABLED`/`MCA_INCIDENT_PUSH_ENABLED` (OFF → `enabled=false`);
  `since_ts`/`cursor`; реестр — только имена настроек (R17); инциденты без stack
  traces. Refresh — само-пере-планирующийся `setTimeout`-цикл
  (`startIncidentPolling` в `setTab('oversight')`), `stopIncidentPolling` при
  уходе; серверный интервал применяется клампом ≤10 s; reconnect-догон по cursor.
- **F3 на diff:** `mcaMetricsBadge`/`mcaDegradedLabel`/`mcaErrorsLabel` при
  `available===false`/`degraded_share===null` → `badge-muted` + «неизвестно».
- **R17:** `sanitize()` до записи во все каналы (caplog/durable/JSON-поля);
  endpoints не публикуют значения настроек/stack traces.
- **Контрольные границы diff:** `pg_db.py`/`param_catalog.py` вне diff.

## Counterexamples checked

1. **Реестр vs реальные события:** подача настоящих `safe_fetch`,
   `message_revision`, `memory_provenance`, `mca07_*`, `mca07_answer_cache`,
   `WATCHDOG_*`, `INCIDENT` → соответствующие процессы `implemented`;
   с «чужим» событием — `not_run`. Тесты
   `test_registry_real_events_flip_closed_features_to_implemented` + независимый
   прогон по всем 7 инструментированным процессам (7/7 `implemented`).
2. **Конкурентная запись во время flush:** эмиссия в окне `await` → события
   остаются в буфере (`pending_size()==2`), записываются следующим flush;
   `written=1`, затем `written2=2`. Тест:
   `test_flush_concurrent_emit_not_lost` (проходит).
3. **UI при недоступной телеметрии:** `available=false` → `badge-muted` (нет
   `badge-ok`), «ошибок/gaps/spool: неизвестно» — подтверждено JS-тестом и
   browser SC-13b (`badge_classes` без `badge-ok`).
4. **Восстановление консистентности после провала flush:** A→spool, B→буфер
   (`spooled_total()==1`, `pending_size()==1`) — нет потерь.
5. **Baseline-дефект `execMetricsRows`:** присутствует в `HEAD` (app.js:2582 в
   блоке `computed`, вызван как метод из шаблона index.html:2344) → не регресс
   mca-17a.
6. **Product-гейты реестра (кандидат F12):** независимая проверка показала, что
   `DIRECT_DECISION_MAKING_ENABLED`/`MCA_SAFE_FETCH_ENABLED`/… дефолтно `True`,
   и `runtime_status('direct.reply', event_names_present={'mca07_answer_cache'})`
   == **`implemented`**. Гипотеза о недостижимости `implemented` **опровергнута**;
   см. Non-blocking F12.

## Blocking findings

Нет. Все High/требование-блокирующие Medium из прошлой итерации (F1, F2, F3, F4,
F5) **закрыты** и подтверждены; ожидавшие repeat-нагрузки проверки пройдены.
Промежуточная гипотеза F12 (см. ниже) — **опровергнута** независимой проверкой.

## Non-blocking findings / debt

- **F12 — [Low] Product-гейты реестра резолвятся через `settings`, а не `mca_gates`.**
  `event_names` корректны и flip-поведение работает (7/7 `implemented` при
  дефолтных `True`). Но `enabled_gate` ряда процессов (`DIRECT_DECISION_MAKING_ENABLED`,
  `MCA_SAFE_FETCH_ENABLED`, `MCA_MESSAGE_IDENTITY_ENABLED`, `MCA_PROVENANCE_ENABLED`,
  `MCA_RETRIEVAL_CONTEXT_ENABLED`, `SUMMARY_*`/`DREAM_*`/`LORE_*` и др.)
  отсутствует в `_GATE_RESOLVERS` → `_settings_gate` читает `config.settings`
  напрямую (не per-call/master-aware). Практического дефекта при дефолтах нет,
  но при внешней смене product-настройки runtime-статус реестра и фактический
  kill-switch могут разойтись. Рекомендация (bounded follow-up, вне scope rework):
  унифицировать резолв product-гейтов через единый механизм.
- **F14 — [Low] `active_incidents` сортирует `severity DESC` лексикографически**
  — для текущих трёх констант (`ERROR`/`WARN`/`INFO`) даёт ожидаемый порядок, но
  хрупко; предпочтителен числовой ключ. Не блокирует.
- **F15 — [Low] Учёт `_dropped_total` при переполнении `_PENDING_MAX`.**
  `_dropped_total += 1` инкрементируется, а `deque(maxlen=256)` вытесняет
  старейшее — счётчик и фактическое вытеснение могут разойтись на единицу.
  Низкий риск; согласовать учёт `gaps` с реальным вытеснением.
- **F16 — [Low] `telemetry_freshness` возвращает `ok` при отсутствии активных
  задач** (пусто ≠ устарело). Приемлемо; зафиксировать явно для UI-паритета §27.5.
- **F17 — [Low] `_spool_append` выполняет синхронный файловый I/O** в failure-ветке
  `flush_events` (блокирует event loop). Замер под прод-объёмом — на `mca-release`.

## Unavailable checks

- **Live TMA WebView** (реальный Telegram WebView) — `PENDING OWNER VERIFICATION`
  (Chromium ≠ TMA; автоматизированный контур проверяет структуру/поведение
  SC-13/13b/14/16).
- **Нагрузочный замер** конкуренции single-writer lock под прод-объёмом и полный
  `DB_LOCK_RESILIENCE_ENABLED=false` — релизный (`mca-release`).
- **Полный e2e takeover** на реальном внешнем супервизоре процессов — релизный.

## MEMORY_DELTA (для Orchestrator)

- `mca-17a` — **Approved** (итерация 2, T-3885). F1–F11 **закрыты**; F12-гипотеза
  **опровергнута** (all 7 инструментированных процессов → `implemented` при
  дефолтных гейтах). Non-blocking debt: F12/F14–F17 (Low), релизные замеры.
- Binding (итог): Spec-Hash `c1378300…`, Tasks-Hash `ad045d1e…`, ADR-Hash
  `2a2ed989…`, Evidence-Hash `ae0d96e2…`, Threat-Hash `36e486a0…`,
  Working-Tree-Hash `462e721b…` (81 untracked). Старые хеши недействительны.
- Верифицировано независимо: pytest 9828/0, focused 70, JS 48/48, Playwright 0
  fail (SC-13/13b/14/16), `git diff --check` чисто.
- Следующий контроллерный шаг по `Approved` — **`delivery`/Merge §100+**; ADR-1027-8
  → `Accepted` по Merge. Утверждение привязано к Reviewed-Commit/Working-Tree-Hash
  выше — любое последующее изменение кода/спек делает его недействительным.

## Шаги для исполнителей

**@Architect:**
- Выполнить Merge §100+ в `plans/ARCHITECTURE.md` и перевести ADR-1027-8 в
  `Accepted` (по `Approved`). Желательно зафиксировать в ADR bounded-заметку по
  F12 (product-гейты реестра).

**state/@Orchestrator:**
- Маршрутизация: `review → delivery` (Merge §100+/приёмка). Checkpoint не трогаю сам.
- F12/F14–F17 зарегистрировать как bounded non-blocking debt (релизная
  нагрузка/унификация резолва гейтов), не блокировать Merge.

_Отчёт обновлён @Reviewer (T-3885) в рамках единого gate; код не изменялся,
`workflow_state.json`-checkpoint не редактировался; секреты источника не
цитировались (R17)._
