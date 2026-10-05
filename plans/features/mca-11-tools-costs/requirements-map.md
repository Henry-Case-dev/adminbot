# MCA-11 `mca-11-tools-costs` — requirements-map (Step 1 @PM, 05.10.2026)

Feature: **`mca-11-tools-costs`** — ToolResult и доставка, учёт расходов, денежные лимиты OFF (эпик `memory-context-autonomy`, Wave 2 — последний хвост волны; после него — Wave 3).
Источник: `plans/current_task.md:730–761` (§15; файл НЕ изменялся, R17). Смежные обязательные: §19 приёмки `:901–902` (A20/A21), `:909` (A28); §20.2 `:1006–1030` — «Новые денежные ограничения | OFF» `:1026`, «Доступные текущие инструменты автономно | ON по категориям раздела 2» `:1022`; §21 `:1046–1093`; §2 п.7–8/10 (GEN-R7/R8/R10 — `mca-round1027-plan.md:31–34`); §4 ToolExecutor `:93`.
Планирование: `plans/docs/mca-round1027-plan.md:119–121` (REQ MCA11-R1…R3), строка фичи `:203`, Wave 2 `:235`, Wave 3 `:238–239`, открытый вопрос №14 `:415`; `plans/backlog.md:13`.
Нумерация задач: **T-4942+** (max занятого = T-4941, `plans/features/mca-15-chat-statistics/tasks.md:72`; совпадений T-4942…T-496x в репо нет — проверено grep).

---

## 1. Подтверждение: следующая незавершённая MCA-задача

Порядок из плана (Wave 2 `:235` → Wave 3 `:238–239`; дубль — `backlog.md:13`):

**Wave 2 (когниция):** `mca-04b` ∥ `mca-05` ∥ `mca-06` ∥ `mca-08` ∥ `mca-15` ∥ **`mca-11`** (после 01+13).

| Фича | Статус | Ссылка |
|---|---|---|
| `mca-04b-dossier-rebuild` | ✅ 2.58.41 + ARCHIVED | `plans/archive/mca-04b-dossier-rebuild-round1029/` |
| `mca-05-episodes-stories` | ✅ 2.58.42 + ARCHIVED | `plans/archive/mca-05-episodes-stories-round1029/` |
| `mca-06-sleep-paradigms` | ✅ 2.58.49 + ARCHIVED | `plans/archive/mca-06-sleep-paradigms-round1034/` |
| `mca-08-character-speech` | ✅ 2.58.55 + ARCHIVED | `plans/archive/mca-08-character-speech-round1035/` |
| `mca-15-chat-statistics` | ✅ RELEASED + VERIFIED 2.58.56 (T-4941 reconcile/archive в работе) | `plans/workflow_state.md` NOTE 45 |
| **`mca-11-tools-costs`** | ⏭️ **следующая незавершённая Wave 2 — последний хвост волны** | `mca-round1027-plan.md:203` |
| `mca-10a-random-source-anu` | Wave 3; берётся после хвоста Wave 2 | `mca-round1027-plan.md:205` |

**Почему `mca-11`, а не Wave 3 (`mca-10a`):** зависимости у обоих закрыты (`mca-11`: mca-01+mca-13 — ✅ §95/§94; `mca-10a`: mca-13 — ✅), но порядок задаёт документ: Wave 2 (`:235`) идёт до Wave 3 (`:238–239`), а внутри Wave 2 не закрыт только `mca-11` (строка `:203` против `:205`). Последнее документированное указание — T-4941 (`mca-15/tasks.md:72`): «Следующая — Wave 2 хвост (`mca-11`) либо Wave 3 (`mca-10a`) по документам, без ожидания владельца» — хвост назван первым. Прецедент шага назад: `mca-15` выбран как «Wave 2 tail» именно перед mca-11 (`mca-15/requirements-map.md:25–27`, `mca-08/requirements-map.md:14`: «Wave 2 (`mca-15`/`mca-11` по приоритету)»; `workflow_state.md` NOTE 38: «Wave 2 tail; before mca-11»). Дополнительно `mca-11` — зависимость Wave 3 (`mca-09` deps `mca-07, mca-08, mca-11`, `:204`, `:239`), её закрытие держит очередь. Критический путь `:250` (`…mca-07 → mca-10a…`) — маркер длиннейшей цепочки, а не порядок очереди; Wave-порядок остаётся документированным.

**Почему не другие:** `mca-16`/`mca-10a`/`mca-09`/`mca-10b` — Wave 3 (после хвоста Wave 2); `mca-18/19/20` — Wave 4; `mca-12/17c/21` — Wave 5; `mca-22` — RELEASED 2.58.44 + ARCHIVED; `mca-23` заперт до конца MCA-очереди (`current_task.md:20852–20859`).

**Проверка расхождений:** рабочая KG-выжимка (`adminbot_mca_round_1027`) устарела — группировала `mca-15` в Wave 3 и вовсе не упоминает `mca-11`; авторитет — план/backlog/T-4941 (прецедент фиксации расхождения — `mca-15/requirements-map.md:31`). Других расхождений не найдено.

---

## 2. Требования владельца (§15 `:730–761`)

Сквозная рамка: REUSE (`GEN-R19`, `:47`), «уже исправленное подтвердить тестом, а не дублировать»; один координатор/словарь событий/леджер доставки; §20.2 — все функции ON, кроме новых денежных лимитов OFF (`:1026`) и stub §14.12.

| REQ | Требование (суть §15) | Якорь | Проверяемый критерий | Приёмки |
|---|---|---|---|---|
| **MCA11-R1** | ToolResult: status `ok/empty/error/timeout/cancelled/denied/delivery_unknown`, output, evidence refs, error code, retryable, duration, usage/cost, external operation ID; возврат строки с текстом ошибки ≠ ok. Категории: read-only память / внешнее чтение / платное медиа / административные; права не расширять; инициатива — те же инструменты и защита. Конечный timeout/шаги/retries: стартово ≤6 вызовов и 2 transient retries на идемпотентный вызов; media async с профильным deadline и сохранённым статусом; числа видимы в настройках; на пределе — явный результат и причина. Side effects: idempotency key + operation state; неясная доставка → `delivery_unknown`, без слепого повтора; provider idempotency где есть; не обещать exactly-once. | §15.1 `:738–748` | (R1a) fixture «ошибка/timeout инструмента» → status error/timeout, не ok (A20); (R1b) fixture «неясный результат платного API/отправки» → `delivery_unknown`, один внешний вызов, нет слепого дубля (A21); (R1c) категории различимы, admin-права не расширены; (R1d) лимиты достигаются явным результатом+причиной, существующие цепочки не ослаблены; (R1e) повтор при подтверждённом успехе запрещён | A20 `:901`, A21 `:902` |
| **MCA11-R2** | Учёт по чату, операции, trigger, модели и provider: input/output/cached tokens при наличии, embeddings, медиа, реальные/оценочные деньги, валюта, версия тарифов. Неизвестная стоимость = unknown, не ноль. Использовать существующую аналитику и карту вызовов. Все сетевые/фоновые ограничения имеют единицы, область, текущее значение и причину; различать финансы, токены контекста, concurrency, размер файла, deadline, антиспам и актуальность намерения в UI и логах. | §15.2 `:750–754`, `:760` | (R2a) fixture «нет цены/ошибка тарифов» → unknown, не 0; (R2b) разрез по чату/операции/trigger/модели/provider виден; (R2c) единицы/область/значение/причина у лимитов; (R2d) финансы не смешаны с токенами/concurrency/deadline/антиспамом | A21 `:902` |
| **MCA11-R3** | Новые денежные лимиты: `enabled=false`; отдельно direct/autonomous/maintenance при будущем включении. Существующие явные финансовые настройки владельца не стирать; если ограничивают работу — показать их и отличие от новых defaults. Никакого скрытого «рекомендованного бюджета». При включении: резервирование ожидаемой стоимости конкурентных операций, overshoot неточной оценки, согласование остатка; не обещать абсолютный потолок при неизвестном usage; уменьшать сначала необязательную инициативу/фон, приоритет direct; ограничение может остановить платные вызовы, но не приём и сохранение исходных сообщений. | §15.2 `:756–758` | (R3a) дефолт — OFF, поведение байт-в-бит 2.58.56 (A28); (R3b) настройки владельца не тронуты, различие с новыми defaults показано; (R3c) fixture (тестовая активация) «лимит исчерпан» → платные вызовы стоп, intake/сохранение живут; (R3d) нет скрытого лимита под другим названием | A28 `:909` |
| GEN-R7 (сквозное) | Денежные лимиты по умолчанию OFF; расходы учитывать; механизм будущих лимитов без искусственного обеднения поведения. | `mca-round1027-plan.md:31`; `current_task.md:27` | то же, что R2/R3 | A28 |
| GEN-R8 (сквозное) | Техзащита от циклов/OOM/повторов/лавины включена; не задаёт норму сообщений бота. | `mca-round1027-plan.md:32`; `current_task.md:28` | лимиты loop/delivery — технические, нормы сообщений не вводят | A02/A37 (вторично) |
| GEN-R10 (сквозное) | Автономные платные медиа — в пределах доступного; раздельные выключатели; без новых подписок/прав/ЛС. | `mca-round1027-plan.md:34`; `current_task.md:30–31` | платные категории уважают существующие выключатели; новых подписок/прав нет | A20/A21 |
| GEN-R17 (контракт) | Процесс `tools.chain` — строка матрицы §27.1: стадии исполнения/доставки/учёта + widget-ID для mca-17c (рендер не здесь). | §27.1 `:1358`; `mca_process_registry.py:565` | стадии видны на реальном запуске; OFF → честный `not_run` | A48/A73 (частично) |

Проверка владельца (§15 `:736`): ошибочный инструмент имеет ошибочный статус; расходы разделены по назначениям; новые денежные ограничения выключены.

---

## 3. Reuse-inventory (переиспользовать; вторых механизмов не создавать)

- **Tool loop/лимиты:** `services/tool_loop.py:43–52` (`TOOL_MAX_ROUNDS=4`, `TOOL_MAX_TOTAL_CALLS=6`, `_TOOL_MAX_SAME_CALL=2`, `TOOL_CHAIN_MAX_METERED_CALLS=4`), kill-switch `TOOL_CHAIN_LIMITS_ENABLED` (`:122–127`); `services/tool_router.py:570` `ToolContext` (+`:635` `metric_results`), `:451` `_stats_json_payload`, `:848` `_query_chat_memory_stats`; `services/tool_schemas.py:547` `TOOL_CALLING_TOOLS` (канон 12, `:579/:588/:597`).
- **Учёт/цены/аналитика:** `services/usage_events.py` (`llm_usage_events`, `SOURCES` включая `image`), `services/llm_pricing.py` (`resolve_price`/`compute_cost`, `price_known=false` при неизвестной цене — «unknown ≠ 0» уже смоделировано), `services/pg_db.py:310–332` (DDL+индексы; таблица `llm_model_prices`), `services/execution_graph_source.py:26/:799` (агрегаты токенов/стоимости; второй сборщик запрещён), `web/api/analytics.py`.
- **Существующие бюджеты (НЕ денежные):** `services/budget_limits.py:1–24` (sentinel-семантика), `services/auto_budget.py`, `worker_budget.py`, `budget_gate.py`, `summary_budget_auto.py`, `summary_hybrid_budget.py` — токены/контекст/воркеры; новые денежные лимиты не смешивать и не стирать.
- **Доставка/идемпотентность:** `services/bot_output_ledger.py:4` + `services/database.py:2815/2858/2874` (durable `mca_bot_outputs`, mca-22), `services/mca_watchdog.py:239` `mark_delivery_unknown`, `services/mca_trace.py:512–514` (запрет слепого повтора), `task_jobs`/`services/task_supervisor.py` (mca-01/14 — durable operation state), update-дедуп mca-22.
- **События/реестр/гейты:** `services/mca_events.py:60–70` — коды `delivery_unknown`, `financial_limit_disabled`, `financial_limit_reached`, `tool_step_limit`, `deadline_exceeded` уже в едином словаре; `services/mca_process_registry.py:565–574` (процесс `tools.chain` v1, widget «Tool chain»); `services/mca_gates.py` (прецедент env-only kill-switch).
- **SafeFetcher (mca-02):** `services/safe_fetch.py:89–106` `SafeFetchError(code, stage, reason, retryable)` → маппинг в ToolResult; carry-over M-MCA02-3 (`fetch_article` → сюда; `backlog.md:30`).
- **Платное медиа/видео:** `services/media_execution.py`, `services/image_generation.py`, `services/video_cascade_client.py:196–203` (retryable-логика) — async deadline/статус.
- **Финальная сборка:** `services/negative_constraints.py` (`verbalize_validated`; numeric guard mca-15), `services/direct_chat_service.py` (потребитель результатов инструментов).

---

## 4. Conflict-audit (CA-11-1…10)

| # | Конфликт-кандидат | Существующий контракт | Действие mca-11 | Правило |
|---|---|---|---|---|
| CA-11-1 | Подмена/дубль статус-словаря mca-15 | `MetricResult`/count status mca-15 (T-4941 handoff: «совместимость count status с ToolResult»; CA-15-7 `mca-15/requirements-map.md:80`) | Count status встраивается в ToolResult-совместимую форму; контракт mca-15 не подменять, второго словаря статусов нет | handoff T-4941 |
| CA-11-2 | Второй леджер доставки | mca-22: durable `mca_bot_outputs`, exact duplicate guard, update-дедуп (`:15896–15931` ТЗ mca-22) | `delivery_unknown`/idempotency — REUSE mca-22 + `mca_watchdog`/`mca_trace`; второй ledger/дедуп запрещён | mca-22; `:748` |
| CA-11-3 | Второй словарь событий/телеметрия | mca-13 `REASON_CODES` (`mca_events.py:60–70`), реестр mca-17a | Только аддитивные коды (базовые уже есть) и AMEND `tools.chain`; второй канал запрещён | §17/§27.1 |
| CA-11-4 | Вторая очередь/состояние операций | mca-01/14 `task_jobs`, TaskSupervisor | Operation state/idempotency keys — REUSE; второй очереди нет | §5.2; `:748` |
| CA-11-5 | Расхождение ошибок SafeFetcher | mca-02 `SafeFetchError(code/stage/reason/retryable)` | `fetch_article`/внешнее чтение маппится в ToolResult без второго error-контракта (M-MCA02-3) | `backlog.md:30`; `:742` |
| CA-11-6 | Смешение денег с существующими бюджетами | token/context/worker-бюджеты (auto/worker/summary); `budget_limits` sentinels | Новые денежные лимиты отдельные, OFF; существующие настройки владельца не стирать, показать отличие; sentinel-семантику REUSE | GEN-R7; `:756` |
| CA-11-7 | Ослабление существующих лимитов цепочек | `TOOL_CHAIN_LIMITS_ENABLED`, 6/4/2 (`tool_loop.py:43–52`) | Стартовая политика §15.1 (≤6/2) согласуется с существующими cap'ами без ослабления A2-защиты; точная семантика — @Architect | `:746`; GEN-R8 |
| CA-11-8 | Второй постпроцессор/нормализация поведения деньгами | mca-08 form-guard, mca-15 numeric guard, запрет второго парафразера | Учёт/лимиты не вводят вторых guard'ов и не «обедняют» поведение скрыто | `:1161`; mca-08/15 |
| CA-11-9 | Конфликт с action-schema mca-09 / применениями mca-10b | mca-09 Decision `reply/react/silent/tool`; mca-10b использует те же инструменты | mca-11 даёт контракт инструментов/лимитов; action-schema и контур инициатив не менять | `:744`; `:204` |
| CA-11-10 | UI/витрина раньше времени | mca-17c — рендер аналитики/действий | Только контрактные ID стадий/единиц; UI не делать (решение о минимальном отображении настроек — @Architect) | GEN-R17; прецедент CA-15-9 |

Сквозные запреты: R17 (секреты/сырой текст не журналировать), не изменять `plans/current_task.md`, не трогать runtime вне санкций, не создавать вторые identity/provenance/retrieval/постпроцессор/леджер/очередь/словарь/координатор/LLM-провайдер.

---

## 5. Что уже покрыто и что реально добавляет mca-11

| Область | Уже есть (проверить, не дублировать) | Реально добавить в mca-11 |
|---|---|---|
| Результаты инструментов | строковый контур tool_router/tool_loop; structured JSON у stats-режима (mca-15) | Типизированный ToolResult (7 статусов, refs/error code/retryable/duration/usage/external op ID), категории, интеграция всех потребителей |
| Лимиты | `TOOL_CHAIN_LIMITS_ENABLED` + cap'ы 6/4/2 | Политика §15.1 (≤6 вызовов / 2 transient retries), media async deadline, настройки, явный результат на пределе |
| Доставка | mca-22 ledger/дедуп, `mca_watchdog`, `mca_trace` | Idempotency key/operation state для side effects; `delivery_unknown` для Telegram/платных провайдеров без слепого повтора |
| Учёт расходов | `llm_usage_events` + `llm_model_prices` + `price_known`, агрегаты ExecutionGraph | Полный разрез чат/операция/trigger/модель/provider; embeddings/медиа; валюта/версия тарифов; unknown≠0 в отчётности |
| Лимиты денег | нет денежного механизма (только token/context-бюджеты) | Новый механизм `enabled=false`, direct/autonomous/maintenance, семантика будущего включения |
| Наблюдаемость | `tools.chain` v1, словарь reason_code | Стадии исполнения/доставки/учёта + widget-ID для mca-17c |

---

## 6. Зависимости и открытые заявки @Architect (Step 2 обязателен)

**Закрытые зависимости:** `mca-01` ✅ §95 (транзакции/очереди), `mca-13` ✅ §94 (события), `mca-14` ✅ §93 (схема), `mca-17a` ✅ §100 (реестр/trace), `mca-22` ✅ 2.58.44 (ledger доставки/дедуп — REUSE), `mca-02` ✅ §97 (SafeFetcher; M-MCA02-3), `mca-15` ✅ 2.58.56 (handoff: count status совместим с ToolResult).

**Заявки на санкции (решение @Architect; PM не решает):**
1. **ToolResult-контракт:** поля/статусы/категории; совместимость с MetricResult mca-15, координатором и финальной сборкой; где живёт (один модуль).
2. **Idempotency/operation state:** REUSE `task_jobs`/`mca_bot_outputs`/`mca_watchdog`/`mca_trace` vs Δ DDL; провайдерская идемпотентность; границы «не обещать exactly-once».
3. **Учёт расходов:** расширение `llm_usage_events` (поля/источники) vs аддитивная Δ DDL; точки записи embeddings/медиа; валюта/версия тарифов; контракт «unknown ≠ 0».
4. **Денежные лимиты:** где живёт конфиг (env-only vs каталог/БД; §20.2 OFF), имена, sentinel-семантика; показ существующих настроек владельца и отличия (UI-часть — решение).
5. **Kill-switches:** env-only список (default ON кроме денежных OFF); OFF = паритет 2.58.56; reason_code — минимальные аддитивные добавления (базовые уже в словаре).
6. **Loop-лимиты:** согласование §15.1 (≤6/2) с существующими cap'ами (`tool_loop.py:43–52`) без ослабления A2.
7. **Media async:** профильный deadline/статус (REUSE `task_jobs`-профиль), отдельный от HTML-лимитов.
8. **Risk:** плановый **R2** (`:203`) — подтвердить; при R3 — `threat-failure-analysis.md`.
9. **Deploy:** практика CA-11 (пер-фичевый bump, прецедент mca-06/08/15) либо DEFERRED_TO_RELEASE — решение @Architect.

**Owner-часть live:** реальные платные вызовы/чат — `PENDING OWNER` без имитации (no-false-acceptance `:15167`, прецедент ASAP 4.4/mca-15 T-4940).

---

## 7. Out of scope (явно)

- Intent/Decision lifecycle, `reply/react/silent/tool` — **mca-09**; применения случайности — **mca-10a/10b**; опыт/уроки (расходы не reward) — **mca-16**; рендер UI/аналитики и диагностические действия — **mca-17c**; гайды — **mca-21**; SelfModel/vision/временной фактчек — **mca-18/19/20**; истории — **mca-12**; единый релиз/effective state — **mca-release**.
- Вторые: статус-словарь, леджер доставки, очередь операций, словарь событий, сборщик аналитики, постпроцессор, координатор, LLM-провайдер.

---

## 8. Маппинг «REQ → приёмки → задачи»

| REQ | Приёмки | Задачи tasks.md |
|---|---|---|
| MCA11-R1 | A20, A21 | T-4945…T-4949 |
| MCA11-R2 | A21 | T-4950…T-4952 |
| MCA11-R3 | A28 | T-4953…T-4955 |
| GEN-R17 (контракт) | A48/A73 (частично) | T-4956 |
| Сводная проверка/ревью | §19 `:874–976`, §21 | T-4958…T-4959 |
| Deploy/live/reconcile | §20 `:986–1045`, no-false-acceptance `:15167` | T-4960…T-4962 |

**Статус документа:** `PLANNING_CONSISTENT` — при условии санкций @Architect (T-4943/T-4944) по пунктам §6. Код на шаге PM не менялся; `plans/current_task.md` не изменялся (R17).
