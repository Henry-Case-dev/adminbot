# ADR-1028-13 — mca-11-tools-costs: ToolResult, учёт расходов и денежные лимиты OFF

**Статус:** Proposed (Step 2 @Architect, design-freeze, 05.10.2026; санкции T-4943/T-4944) → **Accepted по merge** (`plans/ARCHITECTURE.md` §117).
**Фича:** `mca-11-tools-costs` (эпик `memory-context-autonomy`, Wave 2 — последний хвост; после неё Wave 3).
**Номер проверен:** `ADR-1028-13` нигде не занят (grep по `plans/**`); последний фактический — ADR-1028-12 (mca-15, Accepted 05.10.2026).
**Источник:** `plans/current_task.md:730–761` §15; приёмки A20/A21 `:901–902`, A28 `:909`; §20.2 `:1026`; план `mca-round1027-plan.md:119–121, :203 (R2), :235, :415 (Q14)`.
**Детали решений:** `plans/features/mca-11-tools-costs/spec.md` §2–§9 (design-freeze).

## Контекст

Существующий контур инструментов уже имеет out-of-band envelope (`ADR-1026-15`, `tool_loop.py:74–105, :144–222`) и лимиты A2 (6/4/2/360, `TOOL_CHAIN_LIMITS_ENABLED`), durable-очередь `task_jobs` (mca-01), леджер отправок `mca_bot_outputs` (mca-22), событийный контракт `mca_events` (mca-13), учёт `llm_usage_events` + `price_known` (ADR-1023-7) и денежные настройки владельца (unit-лимиты image/worker/chat). Владелец требует: типизированные результаты инструментов с честными статусами (A20), `delivery_unknown` без слепого повтора (A21), учёт расходов с unknown ≠ 0, новые **денежные** лимиты **OFF** (A28, §20.2), стадии `tools.chain` (GEN-R17). Вторые механизмы (статус-словарь/леджер/очередь/словарь/сборщик) запрещены.

## Решения

- **D1. ToolResult — единственный структурированный контракт результата.** Дом — `services/tool_result.py`; 7 статусов (`ok/empty/error/timeout/cancelled/denied/delivery_unknown`) + правила деривации; envelope — существующие ключи + аддитивные (`category/retryable/duration_ms/usage/external_operation_id/evidence_refs/partial`); legacy `skipped` канонизируется в `denied`, `not_found`/`unsupported` — в `empty`, `partial` сохраняется в payload. Сырой output в журнал не пишется (R17). Категории канона 12: `memory_read/external_read/paid_media/admin`; права не расширяются. Совместимость mca-15: `MetricResult.status` авторитетен в payload (AM-9 ADR-1028-12), маппинг фиксирован. OFF = K1. (spec §2)
- **D2. Пределы — поверх существующих cap'ов без ослабления A2.** Числа 6/4/2/360 + `MCA_TOOL_TRANSIENT_RETRIES_MAX=2` — env-only ClassVar'ы с текущими дефолтами; enforcement в `tool_loop`; mca-11 не добавляет chain-level авто-повторов в direct loop; media async — REUSE `media_execution`/`task_jobs` с профильным deadline; на пределе — явный результат/причина. (spec §3)
- **D3. Идемпотентность и `delivery_unknown` — REUSE mca-01/22.** `task_jobs.coalesce_key` = idempotency key (детерминированный хэш), `mca_bot_outputs`/content-hash — отправки, `mca_watchdog.mark_delivery_unknown` + `mca_trace` guard — запрет слепого повтора; провайдерская идемпотентность — где есть; exactly-once не обещается. Второй очереди/леджера нет. OFF = K2. (spec §4)
- **D4. Учёт расходов — один леджер, unknown ≠ 0.** Единственный денежный леджер — `llm_usage_events` (SOURCES += `embedding`/`media`, код-only); новые точки записи: embeddings и медиа-провайдеры; детализация по операции — `mca_events.usage_json` (cached tokens/currency/price_version); агрегаты — существующий `execution_graph_source` (второй сборщик запрещён); нет цены → unknown (не 0). OFF = K3. (spec §5)
- **D5. Денежные лимиты нового механизма: `enabled=false`.** Модуль `services/mca_money_limits.py`; master `MCA_MONEY_LIMITS_ENABLED=false` (owner §20.2); scopes direct/autonomous/maintenance; sentinel-семантика REUSE `budget_limits`; семантика будущего включения (резерв/overshoot/reconcile, приоритет direct, intake не блокируется) реализована и инертна; существующие финансовые настройки владельца не стираются; скрытого «рекомендованного бюджета» нет. (spec §6)
- **D6. `tools.chain` v2 — стадии route→execute→deliver→account.** AMEND реестра mca-17a; события в единственное хранилище `mca_events` через `emit_mca_event`; widget-ID `"Tool chain"` — контракт mca-17c (UI не делается); reason_code +1 (`cost_unknown`); OFF = K4 (честный `not_run`). (spec §7)
- **D7. Kill-switches — env-only:** K1 `MCA_TOOL_RESULT_ENABLED` (ON), K2 `MCA_TOOL_DELIVERY_GUARD_ENABLED` (ON), K3 `MCA_COST_ACCOUNTING_ENABLED` (ON), K4 `MCA_TOOL_CHAIN_STAGES_ENABLED` (ON), K5 `MCA_MONEY_LIMITS_ENABLED` (**OFF**); существующие master'ы переиспользуются; реестр `mca_gates.KILL_SWITCHES`. (spec §8)
- **D8. Санкции:** Δ DDL **0** (SQLite v26 без миграций; PG no-op); Δ каталога **0** (F8 NOT_APPLICABLE, 489); канон 12 без изменений; reason_code **+1**; Risk **R2**; deploy **CA-11** (2.58.56→2.58.57), rollback soft env / cold revert; merge §117. (spec §9)
- **D9. Границы:** mca-09 (action-schema), mca-10b (те же инструменты), mca-16 (не reward), mca-17c (только контрактные ID/единицы), mca-release (деньги OFF). (spec §10)

## AMEND / SUPERSEDE register

| # | Отношение | Суть |
|---|---|---|
| **AM-1** | **AMEND ADR-1026-15 (D1/D3)** | envelope A2 → канонический ToolResult (7 статусов, аддитивные поля, `skipped→denied` при K1 ON); лимиты получают env-only override с текущими дефолтами; ослабления A2 нет; OFF (K1/`TOOL_CHAIN_LIMITS_ENABLED`) — паритет. |
| **AM-2** | **AMEND ADR-1023-7 (D3/D5)** | `SOURCES` расширяются `embedding`/`media`; добавляются точки записи (embeddings/медиа); контракт `price_known`/unknown ≠ 0 сохраняется; второй леджер не создаётся. |
| **AM-3** | **AMEND ADR-1027-8** | `ProcessDefinition tools.chain` v1→v2 (стадии route/execute/deliver/account, instrumentation, enabled_gate); REUSE единственного хранилища `mca_events`. |
| **AM-4** | **REUSE ADR-1028-6** | леджер отправок/дедуп mca-22 — без форка; idempotency/`delivery_unknown` только через существующие контуры. |
| **AM-5** | **CONFIRM ADR-1028-12 (AM-9)** | маппинг `MetricResult.status` → ToolResult зафиксирован (ok→ok, partial→ok+partial, unsupported→empty, error→error); контракт mca-15 не подменяется. |
| **AM-6** | **REUSE ADR-1027-2** | события — единственный словарь `REASON_CODES` и единственное хранилище `mca_events`; второй канал запрещён. |

Supersede: нет (ни один ADR не отменяется).

## Последствия и совместимость

- Потребители инструментов получают типизированный статус/retryable/usage без изменения модельно-видимого канала; envelope-расширение аддитивно (K1 OFF — байт-паритет 2.58.56).
- Расходы по embeddings/медиа становятся видимыми в существующей аналитике; unknown честно отделён от нуля.
- Денежные лимиты не влияют ни на один вызов до явного включения (дефолт OFF); при включении не блокируют приём сообщений.
- Риск R2: изменения аддитивны, без DDL/auth/публичных контрактов; основные failure-mode'ы (неясная доставка, неизвестная цена, лимит) имеют явные статусы/коды.

## Rollback

- **Soft:** K1–K4=false (K5 остаётся OFF) → поведение 2.58.56.
- **Cold:** git revert релизного коммита; миграций нет, SQLite v26 мультивалидна, backup/restore не требуется.

## Прод-валидация и история статуса

- 05.10.2026 — Proposed (Step 2 @Architect; design-freeze, санкции T-4943/T-4944; номер свободен).
- (Ожидается) merge §117 + deploy 2.58.57 VERIFIED → **Accepted**; live-часть T-4961 — `PENDING OWNER` (no-false-acceptance).
