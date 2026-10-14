# Round 10.27 — волновой релиз §93–§100: финальная инвентаризация + матрица пинов + drift-отчёт (T-4042)

- **Фича:** `mca-wave-package-release-1027`; **задача:** T-4042 [@PM, поддержка @DevOps].
- **Дата исполнения:** 29.09.2026. **Роль:** @PM (read-only; код/коммиты не тронуты; `plans/current_task.md` не менялся).
- **Момент замера:** HEAD == origin/master == **`8bd1389`**; staged = **0**; прод-анкер кода `2deb287` (2.58.35).
- **Назначение:** вход агрегатного release-gate **T-4045** (пункты 1, 2, 5 чек-листа spec §3) и композиции **T-4046** (карта файлов).
- **Нормативные источники:** spec фичи §3 (метод пинов), §4.2 (классификация (a)/(b)/(c)), §6.3 (вердикт-правило mca-07, 5 шагов), §12.1/§12.2; архивы `plans/archive/mca-*-round1027/`.
- **R17/R18:** секреты не цитируются; бэкапы/теги не трогались.

---

## 1. Финальный замер рабочего дерева и классификация по spec §4.2

### 1.1. Замер (факт)

`git status --porcelain`: **всего 157 записей = M 106 + untracked 51 + staged 0.**

Дельта против предыдущих замеров (spec §12.1):

| Замер | Untracked | Пояснение дельты |
|---|---|---|
| @PM (планирование) | 50 | до создания папки релиз-фичи |
| @Architect (повторный, шапка spec) | 51 | +1 = `plans/features/mca-wave-package-release-1027/` |
| **T-4042 финальный (этот отчёт)** | **51** (157 суммарно) | структура дерева стабильна; отчёт T-4042 ещё не существовал на момент замера |
| Прогноз на момент гейта T-4045 | **52** (158 суммарно) | +1 = **сам этот отчёт** (`plans/reports/round1027_wave_release_inventory.md`) — собственный артефакт T-4042, класс (a5), уходит в docs-коммит T-4046 |

Ожидание «~157 записей» подтверждено: факт **157**. Все прочие значения шапки spec (M=106) подтверждены.

### 1.2. Классификация каждой записи

**(a) Волновой пакет §93–§100 + docs релиза — 139 записей:**

| Подкласс | Состав | Кол-во |
|---|---|---|
| (a1) wave-код untracked — целиком в feat-коммит | 8 сервисов `services/{task_supervisor,message_identity,provenance,safe_fetch,mca_process_registry,mca_trace,mca_watchdog,mca_incidents}.py`; 8 py-тестов `tests/test_mca{01,02,03,04a,07,13,14,17a}*_round1027.py`; 1 JS-тест `tests/js/round1027_mca17a_observability_ui_test.js`; UI-harness mca-17a ×3 (`tools/ui_round1027_mca17a_observability.py`, `tools/_ui_round1027_mca17a.{json,png}`) | **20** |
| (a2) wave-M product-code | bot.py; handlers ×2 (`chat_lifecycle`, `summary`); services ×22 (в т.ч. `database.py`, `direct_chat_service.py`, `summary_memory.py`, `web_content_extractor.py`, `youtube_transcript_engine.py`, `lore_worker.py`, `dossier_prompts.py`, `dream_worker.py`, `smartmodule_*` ×2 и др.); web ×3 (`api/oversight.py`, `api/routes.py`, `index.html`); tools ×3 (`history_import/loader.py`, `history_import/parser.py`, `video_downloader.py`) | **31** |
| (a3) wave-M тесты | 68 файлов `tests/test_*.py` (в т.ч. 16 файлов с version-head re-pin 18→19, 46 файлов из ASAP-overlap — см. §5) | **68** |
| (a4) wave/docs-M plans | `plans/ARCHITECTURE.md` (+340, хунки §93–§100), `plans/MEMORY.md`, `plans/backlog.md`, `plans/metrics.md`, `plans/reports/global_map.md`, `plans/workflow_state.md`, `plans/features/mca-asap-summary-hotfix/evidence.md` | **7** |
| (a5) docs релиза untracked — в docs-коммит | 10 архивов `plans/archive/mca-*-round1027/` (8 фич + wave0 + wave1); `plans/docs/mca-round1027-{plan,arch-frames}.md`; `plans/features/mca-wave-package-release-1027/`; **+1 на гейте: этот отчёт** | **13** (12 сейчас + отчёт) |

**(b) Уже на проде через import-closure `2deb287` — 0 записей в статусе (пропустить):**
Все 4 файла **чистые**, blob-хэши рабочего дерева == blob-хэшам `2deb287` (проверено `git hash-object` vs `git rev-parse 2deb287:<file>`):

| Файл | sha256 рабочего дерева | Статус |
|---|---|---|
| `services/mca_gates.py` | `220788d5cffc4db4…` | чист, идентичен проду |
| `services/mca_retrieval_context.py` | `2623d81ed3525904…` | чист, **== пину mca-07 `2623D81E…`** |
| `services/mca_events.py` | `e22c9fb9d1ee5712…` | чист, идентичен проду |
| `services/token_counter.py` | `b4a0cbfd88e5aaac…` (protected spans) | чист, идентичен проду |

**(c) Чужое/вне релиза — 18 записей, решения уже закреплены spec §4.2:**

| Подкласс | Состав | Кол-во | Решение |
|---|---|---|---|
| (c1) harness-инфра | `.playwright-mcp/`, `node_modules/`, `package.json`, `package-lock.json` | **4** | **никогда не коммитится** (конвенция WTH); остаются untracked; `.gitignore` не менять |
| (c2) hygiene docs-коммита | скриншоты `tools/asap2_*.png` ×7 + `tools/asap21_*.png` ×5 + `tools/_asap3_wth.py` | **13** | **коммитится на месте** (пути не переезжают: ссылки `tools/…` в закоммиченных §101/§102/deployment.md не должны рваться) |
| (c3) вне релиза | `plans/features/mca-04b-dossier-rebuild/` | **1** | Wave 2; остаётся WIP-untracked до своего фичевого цикла |

**Сходимость: 139 (a) + 0 (b) + 18 (c) = 157 = факт замера.** Orphan-записей нет; каждая строка статуса классифицирована.

---

## 2. Матрица контент-пинов по 8 фичам (spec §3)

Метод: исторические WTH (`9cd581e4…` wave-0, `09f2d9e9…` wave-1, `0501ea9b…` mca-04a, `75D55F53…` mca-07, `462e721b…` mca-17a) считались от Reviewed-Commit `05bc870` и после 3 ASAP-релизов **байт-в-байт невоспроизводимы** — принято как данность (spec §3). Верификация — по пер-файловым пинам архивов + релизным пинам T-4042.

| # | Фича | Файл/артефакт | Пин из архива | Текущий sha256 (факт) | Класс | Вердикт |
|---|---|---|---|---|---|---|
| 1 | mca-14 | миграции v13–v15 в `services/database.py` (M-хунки) | WTH wave-0 `9cd581e4…` (невоспроизводим); пер-файлового пина нет | M-дифф волновой (см. §5); релизный пин фиксирует T-4045 | допуск | пин закрепляется на гейте |
| 2 | mca-13 | `services/mca_events.py` | пер-файлового пина в ревью нет; blob `2deb287` `e22c9fb9…`; пин mca-17a `e22c9fb9d1ee5712` | `e22c9fb9d1ee5712…` == blob прода == пин mca-17a | **СОВПАДЕНИЕ** | уже на проде (b); совпадение зафиксировано |
| 3 | mca-01 | `services/task_supervisor.py` | WTH wave-0; финальный пин mca-17a (AMEND correlation/fencing L-MCA01-5) `a54ba23f88b154a0` | `a54ba23f88b154a0…` — **совпал** | **СОВПАДЕНИЕ** (по последнему ревью, амендившему файл) | пин подтверждён |
| 4 | mca-01 | `tests/test_mca01_tx_task_supervisor_round1027.py` | пер-файлового пина нет | `7f14d133f6c592fc…` | допуск | релизный пин закрепляется |
| 5 | mca-03 | `services/message_identity.py` | WTH wave-1 `09f2d9e9…` (невоспроизводим); Feature-Diff-SHA256 `4c34c771…` (частичный) | `160cdd33e3893311…` | допуск | релизный пин закрепляется |
| 6 | mca-03 | `tests/test_mca03_message_identity_round1027.py` | пер-файлового пина нет | `5e5c4ec0081298d8…` | допуск | релизный пин закрепляется |
| 7 | mca-02 | `services/safe_fetch.py` | пин evidence (до-rework): `575941F8766995FB…` (1048 строк) | `2f0a217604fe2438…` (1084 строки) | **ДОКУМЕНТИРОВАННОЕ КАСАНИЕ** | +36 строк = rework **B-MCA02-1** (пер-фазные таймауты) внутри собственного ревью; код перепроверен: `asyncio.timeout(prof.timeout)` на стр. 598/689 и `SafeFetchError("safe_fetch_timeout", stage="stream", retryable=True)` на стр. 608/723 (эратум delivery L-2, санкция review round-2 §11.4: фактическая форма вызова — позиционные аргументы `("safe_fetch_timeout", "stream", True)`, семантика та же) — **ровно строки, процитированные в review.md итер.2** (Approved). Третьи лица (mca-04a/07/17a, ASAP) файл не трогали. Релизный пин `2f0a2176…` |
| 8 | mca-02 | `tests/test_mca02_safe_fetch_round1027.py` | пер-файлового пина нет (focused 63 passed) | `768efca11e87aec8…` | допуск | релизный пин закрепляется |
| 9 | mca-04a | `services/provenance.py` | WTH `0501ea9b…` + Untracked-Manifest `3aa25317…` (58 файлов; оба невоспроизводимы) | `531cfb252664d090…` | допуск | релизный пин закрепляется |
| 10 | mca-04a | `tests/test_mca04a_provenance_round1027.py` | пер-файлового пина нет | `23b561aeebbd4eec…` | допуск | релизный пин закрепляется |
| 11 | mca-07 | `services/mca_retrieval_context.py` | пин review `2623D81E…` | `2623d81ed3525904…` == blob `2deb287` | **СОВПАДЕНИЕ** | уже на проде (b) |
| 12 | mca-07 | `tests/test_mca07_retrieval_context_round1027.py` | пин review `C292E50F…` | `92bfa016ac335d66…` — **дрейф** | **ДОКУМЕНТИРОВАННОЕ КАСАНИЕ** | разбор по §6.3 — см. §3 (вердикт: допустимо) |
| 13 | mca-13 | `tests/test_mca13_event_contract_round1027.py` | пер-файлового пина нет (focused 25) | `1137493a93efe060…` | допуск | релизный пин закрепляется |
| 14 | mca-14 | `tests/test_mca14_schema_additive_round1027.py` | пер-файлового пина нет (focused 33) | `7aaf6086d0bf44f4…` | допуск | релизный пин закрепляется |
| 15–21 | mca-17a | 4 сервиса: `mca_process_registry.py` / `mca_trace.py` / `mca_watchdog.py` / `mca_incidents.py` | пины evidence `61a17910926014ea` / `96c8c0e4b29c9c30` / `3da3c135f254269e` / `12b25c11248d7aff` | `61a17910926014ea…` / `96c8c0e4b29c9c30…` / `3da3c135f254269e…` / `12b25c11248d7aff…` — **все совпали** | **СОВПАДЕНИЕ ×4** | пин подтверждён |
| 22–24 | mca-17a | тест py / тест JS / UI-harness | пины evidence `eb3614d04f6f093e` / `928c36c490973301` / `16f70ae986d41922` | `eb3614d04f6f093e…` / `928c36c490973301…` / `16f70ae986d41922…` — **все совпали** | **СОВПАДЕНИЕ ×3** | пин подтверждён |
| 25 | mca-17a | `services/mca_gates.py` + `config/settings.py` + `web/app.js` | пины evidence `220788d5…` / `5e7e11de…` / `0ad05ed7…` | gates `220788d5…` **совпал** (на проде); `settings.py`/`app.js` **не в M-списке** — их волновые хунки уехали на прод через ASAP-коммиты | СОВПАДЕНИЕ / **уже на проде** | отмечено для композиции: (b)-подобные, в feat-коммит не включать |

**Итог по классам матрицы:** СОВПАДЕНИЕ — **12** позиций (вкл. blob-верификацию прода); ДОКУМЕНТИРОВАННОЕ КАСАНИЕ — **2** (safe_fetch, mca-07-тест); **НЕДОКУМЕНТИРОВАННЫЙ ДРЕЙФ — 0**. Допуск (закрепление релизных пинов, пер-файловых пинов в архиве нет) — 8 позиций. **Эскалаций на per-file re-review нет.**

---

## 3. Вердикт по drift-теста mca-07 — правило spec §6.3, 5 шагов

| Шаг | Действие | Факт |
|---|---|---|
| 1 | Пересчёт sha256 текущего `tests/test_mca07_retrieval_context_round1027.py` | `92bfa016ac335d66b3065445fe585e16216386a6ae5201921681cbb69eae5fa7` — дрейф подтверждён, находка не устаревшая (≠ пин `C292E50F…`) |
| 2 | Статический инвентарь тест-имён vs архивный эталон (focused 43 passed; файл untracked, git-истории нет — инвентарь архива единственный эталон, принято как данность) | **ровно 43** `def test_*` (0 классов, 991 строка); оба известных архиву имени на месте: `test_mca07_reason_codes_registered`, `test_mca07_kill_switches_registered_and_default_on`; инвентарь == 43 ✔ |
| 3 | Классификация дельты: (a) ASAP-пины/фикстуры vs (b) семантика | **класс (a)**: голова DDL перепинована `== 18` → `== 19` (строки 42/44/110) при сохранении исторических имён `test_v18_*` — ровно санкционированная категория mca-17a: evidence.md, раздел «Re-pin (конвенция волн: только version/count/boundary)»: «`== 18` → `== 19` — 16 файлов (… `test_mca03/04a/07_…`). Ослабления проверок нет — только замена номера head-версии»; review.md mca-17a: «Re-pin/AMEND тестов — только version/count/boundary/sha256; структурные проверки сохранены». Признаков класса (b) не найдено: assertions §11.1–§11.4 на месте, удалений/переименований тестов нет |
| 4 | Вердикт: инвентарь == 43 И дельта ⊆ (a) | **ДОПУСТИМО с фиксацией.** Релизный пин — `92bfa016ac335d66b3065445fe585e16216386a6ae5201921681cbb69eae5fa7`; исторический `C292E50F…` остаётся фактом архива |
| 5 | Контроль: focused-прогон | **43 passed** (прогон 29.09.2026, `.venv`, 4.32 s) ✔ |

**Побочные наблюдения (косметика, не блокеры, волна-атрибутированы):** в `tests/test_database.py` docstring `test_user_version_is_3_after_initialize` содержит остаревший пин «user_version == 13» (эпоха волны-0) при фактическом assert `== 19`; комментарий «MCA-07 v18 — head» при assert 19. Пин-значения верны, имена сохранены — правило «только замена номера» соблюдено на уровне утверждений. _Диспозиция delivery (эратум L-1, санкция review round-2 §11.4): docstring-косметика кодом НЕ правится (правка тестов после гейта = недопустимый дрейф binding); зафиксирована настоящей пометкой, исправление docstring — кандидат в следующий волновой re-pin._

---

## 4. Kill-switch инвентарь

### 4.1. mca-17a — точный состав: ровно 8 env-флагов (пин T-4042)

Нормативная база: блок **«mca-17a (ADR-1027-8 D12)»** реестра `KILL_SWITCHES` в `services/mca_gates.py` (строки 109–143 — ровно 8 записей) + формула метрик/задач архива «**8 kill-switch + fault-injection OFF dev-only**» + evidence «7 под-гейтов + fault-injection» (7 под-гейтов + 1 master = 8). Предварительная разбивка «5 + reuse + dev-only» из §0.1 tasks.md **не подтвердилась** и заменяется этим пином (spec §12.2).

1. `MCA_OBSERVABILITY_ENABLED` — master; OFF → паритет baseline целиком;
2. `MCA_PROCESS_REGISTRY_ENABLED` — OFF → реестр процессов не публикуется/не регистрируется;
3. `MCA_TRACE_SPAN_ENABLED` — OFF → события без расширенных span-полей (только контракт MCA-13);
4. `MCA_JOB_LIFECYCLE_ENABLED` — OFF → lifecycle/partial/degraded/linked job не вычисляются;
5. `MCA_HEARTBEAT_WATCHDOG_ENABLED` — OFF → нет watchdog/takeover/stale-детекта;
6. `MCA_INCIDENTS_ENABLED` — OFF → инциденты не группируются/не ведутся;
7. `MCA_INCIDENT_PUSH_ENABLED` — OFF → доставка инцидентов в миниапп выключена;
8. `MCA_TELEMETRY_SPOOL_ENABLED` — OFF → нет дискового spool/degraded-счётчика (structural fallback).

**Вне восьмёрки:** `MCA_TELEMETRY_STORE_ENABLED` и `MCA_EVENT_CONTRACT_ENABLED` — флаги wave-0-блока реестра (ось mca-13/durable-персистенции, потребляются mca-17a в паре — «wiring flush/prune уважает оба»); `MCA_FAULT_INJECTION_ENABLED` — dev/test-only, default **OFF**, вне `KILL_SWITCHES`, на проде не включается (spec архива §5.4/§5.5, §27.9).

### 4.2. Полный инвентарь волны (по код-реестру, сверка предварительного списка §0.1)

`KILL_SWITCHES` = **26 product-флагов** в трёх блоках + 1 dev-only вне реестра. Все default ON, env-only `ClassVar`, резолв per-call, OFF = точный паритет baseline, Δ каталога = 0:

| Фича | Флаги | Кол-во |
|---|---|---|
| mca-14 | `MCA_SCHEMA_MIGRATIONS_ENABLED` | 1 |
| mca-13 | `MCA_EVENT_CONTRACT_ENABLED`, `MCA_TELEMETRY_STORE_ENABLED` (durable-ось; потребляется mca-17a) | 2 |
| mca-01 | `MCA_TX_OWNERSHIP_ENABLED`, `MCA_TASK_SUPERVISOR_ENABLED` | 2 |
| mca-03 | `MCA_MESSAGE_IDENTITY_ENABLED`, `MCA_MESSAGE_REVISION_TRACKING_ENABLED` | 2 |
| mca-02 | `MCA_SAFE_FETCH_ENABLED`, `MCA_EGRESS_GUARD_ENABLED` (+env-конфиг `SAFE_FETCH_TRUSTED_HOSTS/PORTS`, `SAFE_FETCH_UPSTREAM_PROXY` — не kill-switch) | 2 |
| mca-04a | `MCA_PROVENANCE_ENABLED`, `MCA_FACT_ATTRIBUTION_ENABLED`, `MCA_EVIDENCE_RECONSTRUCTION_ENABLED` | 3 |
| mca-07 | `MCA_RETRIEVAL_CONTEXT_ENABLED`, `MCA_TYPED_RERANKER_ENABLED`, `MCA_EVIDENCE_BUNDLE_ENABLED`, `MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED`, `MCA_CONTEXT_ANSWER_CACHE_ENABLED`, `MCA_SUMMARY_SINGLEFLIGHT_ENABLED` | 6 |
| mca-17a | восьмёрка из §4.1 | 8 |
| dev-only | `MCA_FAULT_INJECTION_ENABLED` (default OFF, вне реестра, на проде OFF) | 1 |
| **Итого** | | **26 product + 1 dev-only = 27** |

Отличие от предварительной оценки «≈25 (2 переиспользуются)»: факт — **26 product** (предварительный список недосчитал `MCA_TELEMETRY_SPOOL_ENABLED`, `MCA_TRACE_SPAN_ENABLED`, `MCA_JOB_LIFECYCLE_ENABLED`, `MCA_HEARTBEAT_WATCHDOG_ENABLED` и ошибочно включал `MCA_TELEMETRY_STORE_ENABLED` в восьмёрку mca-17a). Для T-4045 п.5 (env-проба всех флагов) нормативен этот список.

---

## 5. Смешанные хунки: файловая атрибуция M-файлов

Пересечение M-списка с объединённым перечнем файлов трёх ASAP-фeat-коммитов (`3e8594b` ASAP-2 — 44 файла, `219a55c` ASAP-2.1 — 99, `2deb287` ASAP-3 — 37; уникальных 127):

- **50 M-файлов** имеют ASAP-историю (2 product-code: `services/direct_chat_service.py`, `services/summary_fact_package.py`; 2 web: `web/api/routes.py`, `web/index.html`; 46 тестов). Текущий рабочий дифф этих файлов = **остаток волновых хунков поверх уже-закоммиченных ASAP-хунков** (ASAP-часть в HEAD): выборочная проверка диффов подтверждает волновую природу остатка (version-head re-pin 18→19, wave-обновления тестов).
- **56 M-файлов** ни одним ASAP-коммитом не трогались → весь их текущий дифф волновой; механика whole-file безопасна.
- **`web/index.html`** — хирургический кейс спецификации подтверждён: 2 хунка, **+61 строка**, контент исключительно mca-17a UI (блок `mca-metrics-block`, бейджи инцидентов/degraded/gaps/spool, honest-unknown) — остаток WIP после хирургии ASAP-2.1, без чужих хунков.
- Проверка типичного re-pin-диффа (`tests/test_database.py`, 13 хунков; `test_graphrag_database.py`/`test_multilayer_extraction_round1021.py` по 5): только замены номеров head-версии `12 → 19` с сохранением структуры утверждений — конвенция mca-17a соблюдена (косметика см. §3).

**Рекомендация механики для T-4046 (по spec §4.1):** whole-file для 105 M-файлов + 1 хирургический (`web/index.html` — по карте, хотя фактически и его текущий дифф состоит только из волновых хунков, т.к. ASAP-часть уже в HEAD); обязательная верификация на чистом worktree до push (урок ASAP-3). Финальную hunk-сверку 50 overlap-файлов гейт фиксирует в новом агрегатном binding.

---

## 6. Эскалации и рекомендации агрегатному гейту T-4045

**Эскалации: 0.** Недокументированный семантический дрейф не обнаружен ни в одном волновом артефакте. Все 8 фич имеют вердикт (критерий T-4042 выполнен):

| Фича | Вердикт | Основание |
|---|---|---|
| mca-14 | допуск — контент-контроль + гейт | WTH невоспроизводим (данность); тест на месте; миграции в M-хунках |
| mca-13 | СОВПАДЕНИЕ (на проде) | blob == `e22c9fb9…`, пин mca-17a совпал |
| mca-01 | СОВПАДЕНИЕ (task_supervisor по финальному пину mca-17a) | `a54ba23f…` == пин |
| mca-03 | допуск — релизный пин | `160cdd33…` закреплён |
| mca-02 | ДОКУМЕНТИРОВАННОЕ КАСАНИЕ (rework B-MCA02-1) | код перепроверен по строкам review; релизный пин `2f0a2176…` |
| mca-04a | допуск — релизный пин | `531cfb25…` закреплён |
| mca-07 | **ДОПУСТИМО с фиксацией** (§6.3, 5/5 шагов) | релизный пин `92bfa016…`; focused 43 passed |
| mca-17a | СОВПАДЕНИЕ ×7 + reuse-совпадения | все пины evidence совпали |

**Рекомендации гейту:**

1. **Binding:** зафиксировать новый агрегатный WTH (рецепт Эпика 3: DIFF+STATUS+UNTRACKED, отчёт гейта исключён) + релизные per-file пины §7 — на момент гейта untracked будет **52** (157 + этот отчёт), что соответствует прогнозу §1.1 и не является дрейфом.
2. **Focused-срезы 8/8** с архивными счетами: 17/25/33/25/63/34/**43 (уже подтверждён повторно)**/70 (порядок: mca-14/mca-13/mca-01/mca-03/mca-02/mca-04a/mca-07/mca-17a). _Эратум delivery (санкция review round-2 §11.4): в исходном тексте была перестановка «33/…/17» — фактические/архивные счёта mca-14 = **17**, mca-01 = **33**._
3. **Hunk-сверка 50 overlap-файлов** (§5) — file-level атрибуция чистая; гейт подтверждает hunk-level при формировании нового binding (особенно `web/api/routes.py` — на нём висит frozen-hash пин `ROUTES_SHA256_F11` из F8-шума).
4. **Kill-switch-проба:** 26 product-флагов §4.2 + контроль `MCA_FAULT_INJECTION_ENABLED=false` на проде (dev-only).
5. **R17/R18:** стандартно — секретов в диффе нет (настоящий отчёт секретов не содержит), `current_task.md` не менялся.
6. **Косметика без блокировки:** docstring «== 13» в `test_database.py`; устаревшие комментарии «v18 — head» при корректных assert 19 — волновая атрибуция, исправление кодом вне скоупа релиза.
7. **(b)-файлы** в feat-коммит не включать; в отчёте композиции пометить «уже на проде» (§1.2).
8. **Блокеров для созыва гейта нет** — предварительное условие spec §1 («недокументированного семантического дрейфа нет») выполнено.

---

## 7. Релизные per-file пины (SHA-256, закреплено T-4042, 29.09.2026)

**Untracked wave-код/тесты (20):**

```
a54ba23f88b154a00342b894711ead75ff0742d819492159d726956294cef454  services/task_supervisor.py
160cdd33e3893311ff61ed40817d3c1cb4ce96f948467ba6f20ddc56eb4633f0  services/message_identity.py
531cfb252664d09047c3d1715fd6395f1c066e489215b44b902691fed63751c4  services/provenance.py
2f0a217604fe24383bd2c41cccf5ee3e358427c78adfe19f553ef75850e9d477  services/safe_fetch.py
61a17910926014ea02cf2cb406494563db377e8b5392468eacd0e78dcee14b1b  services/mca_process_registry.py
96c8c0e4b29c9c30eac6ce7c2fc8db60131ef810e7c71588bc897bd52f7bc64d  services/mca_trace.py
3da3c135f254269e085f2ff3778ba8140284adb0473769a92382a8895a1507e0  services/mca_watchdog.py
12b25c11248d7aff7757e62e67d7daa6fbd17c26e6ad18b0c331d1ed8d71c208  services/mca_incidents.py
7f14d133f6c592fc8636c6ef47c6f8102e154b5948089f592a9356997ce9076c  tests/test_mca01_tx_task_supervisor_round1027.py
768efca11e87aec8428f5d96d36893ff754c8516dac0b9755298246f6f95e0c7  tests/test_mca02_safe_fetch_round1027.py
5e5c4ec0081298d830055baf4b11cd94b9e3172febf1abf68154f2fa4a91dc99  tests/test_mca03_message_identity_round1027.py
23b561aeebbd4eec9336b4641ec90c250cca75bfd41e7b451c167374d6afce9f  tests/test_mca04a_provenance_round1027.py
92bfa016ac335d66b3065445fe585e16216386a6ae5201921681cbb69eae5fa7  tests/test_mca07_retrieval_context_round1027.py
1137493a93efe060432c1915b22fe955532df47c01d009de10a0700bf087fc33  tests/test_mca13_event_contract_round1027.py
7aaf6086d0bf44f43062129b884fae161f013b7535836071896585a82c8d5629  tests/test_mca14_schema_additive_round1027.py
eb3614d04f6f093ec1ad9c998d1c614706827e73a8fc3599e3da69d49cac8398  tests/test_mca17a_observability_core_round1027.py
928c36c4909733017eb72cba29bc95360195aefd04abea13ce7c760fc58d0117  tests/js/round1027_mca17a_observability_ui_test.js
16f70ae986d41922fdb3efb1653b5da40d478fa13a127fc4e2caaec50e22937a  tools/ui_round1027_mca17a_observability.py
f7347d0515c9cf901f6d8bd1b73029bdca36cfa28a864c89f6098e7959fa9ada  tools/_ui_round1027_mca17a.json
67c79fe66a0f9df0425533a589c178ba58c94bb30c0142bb26604c387ea232df  tools/_ui_round1027_mca17a.png
```

**Уже на проде (b, blob == `2deb287`):** `mca_gates.py` `220788d5cffc4db4…`, `mca_retrieval_context.py` `2623d81ed3525904…` (== архивный пин mca-07), `mca_events.py` `e22c9fb9d1ee5712…`, `token_counter.py` `b4a0cbfd88e5aaac…`.

**Ограничение метода (фиксация):** исторические WTH/манифесты невоспроизводимы после 3 ASAP-релизов — принято как данность (spec §3); для файлов без пер-файловых архивных пинов этот отчёт закрепляет **релизные** пины, которые T-4045 включит в новый агрегатный binding доставки.

---

_Отчёт исполнен @PM (T-4042, 29.09.2026). Read-only: код/коммиты/теги не тронуты; единственное изменение — создание этого файла. `plans/current_task.md` не менялся; секреты не цитировались (R17/R18). Не коммитить — забирается docs-коммитом T-4046._
