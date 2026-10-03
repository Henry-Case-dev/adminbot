# ASAP 4.1 — reuse-inventory.md (Step 1 @PM, 03.10.2026)

Целевое утверждение владельца: «Цель — один раз сделать Summary устойчивым архитектурно и прекратить чинить очередной timeout/cap отдельными заплатками» (`current_task.md:22361`). Инвентаризация фактического состояния дерева после ASAP-4 + пост-ASAP-4 corrective pass (прод 2.58.45+, SQLite v23) — проверено `Glob`/`Get-Content`/`rg` 03.10.2026. ASAP 4.1 должен **амендировать/расширять** существующие компоненты, не строить второй контур Summary.

---

## 1. Фактические файлы Summary-пайплайна после ASAP-4 (проверено в дереве)

| Файл | Состояние | Что даёт ASAP 4.1 |
|---|---|---|
| `services/summary_generator.py` | Есть; S7 run_id = correlation_id (ADR-1026-9 D1, :463); `_cap_legacy_chunks` — только Legacy output; MAX_SUMMARY_PARTS читается только в Legacy-путях (:144, :751) | Точка интеграции SummaryRun state machine; оркестрация перепевязывается на SourceWindow |
| `services/summary_l1_capacity.py` | **ASAP-4 зона C, D7.1 (T-4422)**; kill-switch `SUMMARY_L1_CAPACITY_GUARD_ENABLED` | **AMEND-цель #1**: planning-estimate sharding («раньше так было безопаснее») → whole-window-first; capacity-математика (planning estimate, required/reserve) переиспользуется, триггер решения меняется |
| `services/summary_legacy_fullwindow.py` | **ASAP-4 зона C, D7.3 (T-4424/T-4425)**; kill-switch `SUMMARY_LEGACY_FULL_WINDOW_ENABLED`; 50k-stop убран (R4-C-007/008), coverage target 100%, MAX_SUMMARY_PARTS не тронут | **Переиспользование + доуточнение**: §31 требует, чтобы Legacy начинал с SummarySourceWindow (source_ref), а не из независимого сборщика окна; capacity-aware legacy = extension |
| `services/summary_quote_repair.py` | **ASAP-4 зона C/D**; kill-switch `SUMMARY_QUOTE_REPAIR_ENABLED` | Переиспользование без изменений (атрибут-ремонт теперь валидируется против SourceWindow — R6-B-007) |
| `services/summary_l2_review.py` | **ASAP-4 зона D**; bounded revision, kill-switches `SUMMARY_L2_REVIEW_ENABLED`/`SUMMARY_REVISION_PATCH_ENABLED` | Расширение: Reviewer получает Full SourceWindow (R6-B-007); bounded revision сохраняется §18 |
| `services/summary_l2_writer.py` | **ASAP-4 зона D** | Расширение входа: source_window обязателен, fact_view опционален (R6-B-005/006) |
| `services/summary_fact_package.py` | Есть; сейчас бутылочное горло Writer | Понижение роли: derived view (R6-B-005); не удалять |
| `services/summary_semantic_reduction.py` | Есть (ASAP-3.2 D8/D9) | Переиспользование для CAPACITY_OVERFLOW merge (R6-A-009) |
| `services/summary_xml.py` | Есть; в `XmlGroundingBuilder` остался хвост-лог «XML context: hard cap %d chars reached» (:76) — dead-path при включённом legacy full-window; builder переиспользуется для сериализации окна | Допроверка в T-4611: dead-path 50k-stop недостижим (регресс §0-инцидента) |
| `services/summary_hybrid_budget.py` | Есть; «legacy MAX_SUMMARY_PARTS в Hybrid не используется — закреплено тестом» | Регресс-база DoD 13 |
| `services/summary_run_log.py` | Есть: RunContext (first-class run state: числа, R17), stage-логи, cover/publish-логи | **Переиспользование**: RunContext — заготовка durable-поля SummaryRun; сейчас это лог-объект, не persisted state machine |
| `services/summary_memory.py` / `summary_aliases.py` / `summary_prompts.py` / `summary_throttling.py` / `summary_scheduler.py` / `summary_cleanup.py` / `summary_article_formatter.py` / `summary_test_run.py` | Есть | Переиспользование без изменений (alias/roster, промпты, cron, тест-контур) |
| `services/model_capacity.py` | Есть (ASAP-3.1): карта `MODEL_CONTEXT_WINDOWS`; известный хвост — unknown_fallback консервативно 16384 (backlog Follow-up ASAP-3, п.1) | **AMEND-цель #2**: §5 запрещает name-based mapping как основной механизм → резолвер перестраивается на цепочку приоритетов 1–5 (runtime discovery → metadata → registry → override → conservative fallback); карта остаётся уровнем 3 |
| `services/llm_client.py` | Есть; `settings.LLM_TIMEOUT` (default 120s), `LLM_MAX_RETRIES`/backoff/fallback_max_retries — **вложенные retry-уровни** (:289–355); `total_budget_exceeded` (LLM_TOTAL_BUDGET asyncio.timeout, :11); `_LLM_STATS` | **AMEND-цель #3**: переход к LLMExecutionSupervisor (§22–§26); вложенные retry убрать; transport retry у下层 может остаться — решение @Architect (не менять договоры прочих потребителей llm_client без причины — прецедент R4-A-011) |
| `services/media_execution.py` | Есть (ASAP-3.2 D4–D7): MediaWindows adaptive (record_media_outcome, percentile), ImageProviderAdapter (capabilities), MediaJobState + media_job_key, async job polling, resolve_windows | **Прямой паттерн-донор** для LLMExecutionSupervisor: adaptive inactivity windows (Mode B), job state polling (Mode A), adapter capability declarations (§26) |
| `services/embedding_control_plane.py` | Есть (ASAP-4 зона A): executor с единым attempt-бюджетом, kill-switch pattern env-only OFF=бит-в-бит | Паттерн «один владелец retry» (R6-D-002) — прецедент уже принят; kill-switch-дисциплина для всех новых механизмов 4.1 |
| `services/direct_llm_react.py` | Есть (ASAP-3.1 REACT) | Относится к Direct-контур; в scope 4.1 не входит, кроме: capacity-supervisor интерфейсы не должны ломать Direct (M-ASAP31-2: tool-loop fallback payload — carry-over, не в 4.1) |

## 2. Инфраструктура durable/resume (для зоны C)

| Компонент | Состояние | Отношение к 4.1 |
|---|---|---|
| `task_jobs` / TaskJobStore (mca-01) | Есть: checkpoint/pause/resume, fencing token; использован cover-джобой (L-EXTRA-6: checkpoint в той же payload-колонке, где enqueue хранит бизнес-payload — перезапись атрибутов джобы) и дossier (R5) | Кандидат-носитель SummaryRun; обязателен reconcile: отдельная колонка/store или run-таблица — решение @Architect; учесть L-EXTRA-6 |
| L-EXTRA-7 (backlog Follow-up EXTRA, п.5) | Открыто: `cover_job_key` = UUID4 на запуск → кросс-рестарт resume требует стабильного `summary_run_id` | **Прямой вход в R6-C-002**: стабильный run_id — предпосылка «restart без дубликатов» |
| `mca_pipeline_runs` / `mca_events` (mca-17a) | Есть: 9 lifecycle-состояний, run partial/degraded/stalled, heartbeat/watchdog, incidents | REUSE для §42 events и DEGRADED-семантики; SummaryRun состояние = сервисная надстройка над этим |
| Publication idempotency (R4-D-051) | Есть: sent unknown → reconcile → потом retry | Регресс-база DoD 21 |
| Cover provenance (R4-B-009) + Inspector (R4-E) | Есть | База для Inspector-карточек §38–§41 (добавить поля, не новый продукт — R4-E-002 правило) |

## 3. Что уже закрыто ASAP-4 и только регрессируется (не переписывать)

- Bounded revision loop, Reviewer contract, finding codes, deterministic validator, formatter repair, publication ladder, idempotency, immutable stage history — зона D ASAP-4 (R4-D-001…066) — **сохраняется** (§18/§19 явно «сохраняется идея ASAP-4»).
- Legacy full-window contract, coverage target 100%, MAX_SUMMARY_PARTS semantics — зона C ASAP-4 (R4-C-007…010) — **сохраняется + расширяется** source_ref-входом.
- Cover Style pipeline единый production path (R4-B-003), provenance, reference integrity — **сохраняется**.
- Quote repair ladder + reason codes — **сохраняется**; противоречия с MCA-22 D3 уже сняты в ASAP-4 (extension, не fork).

## 4. Итоговые AMEND/NEW-зоны (для @Architect)

1. **AMEND #1 (ADR-1028-7 D7.1, зона C ASAP-4):** chunking/sharding-first → **whole-window-first**; chunking остаётся только в режиме CAPACITY_OVERFLOW (§3/§8). Возникающий вопрос для spec: как в WHOLE_WINDOW не допустить `too_many_facts`-класс invalid (компактная semantic map §12 — ожидаемый ответ; сверить контракт `MAX_FACTS_PER_THREAD=30` на whole-window запросе).
2. **AMEND #2 (ASAP-3.1 Model Capacity):** name-based карта `MODEL_CONTEXT_WINDOWS` → цепочка приоритетов §5 + serialized-prompt accounting §6 + cache/invalidation §7.
3. **AMEND #3 (llm_client timeout/retry):** fixed LLM_TIMEOUT + вложенные retry → LLMExecutionSupervisor (§22–§26); rename `total_budget_exceeded` (§30).
4. **NEW:** Immutable SummarySourceWindow (§2), CoverageLedger (§9), Durable SummaryRun state machine (§20–21), Inspector-карточки (§38–§41), structured events (§42).
5. **EXTENSION (bugfix в существующем контуре):** Medved Press connection inheritance (§35 — глобальный default image-edit provider), capability registry для image edit (§36).
