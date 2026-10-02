# ASAP-4 — reuse-inventory.md (Step 1 @PM, 02.10.2026)

Принцип владельца: «ASAP-4 НЕ должен строить второй GraphRAG, второй Cover Style pipeline или второй Summary» — production closure существующих механизмов (`current_task.md:16596–16615`, R4-G-001).

Существование всех путей проверено на рабочем дереве 02.10.2026 (Test-Path/Get-Item). Отклонения от списка в запросе Orchestrator'а зафиксированы явно.

---

## 1. Запрошенные файлы — статус существования

| Запрошенный путь | Факт | Роль |
|---|---|---|
| `services/summary_memory.py` | ✅ существует (~239 KB) | Окно сообщений, RAG/vector/graph память, retrieval-источники Summary |
| `services/graphrag_rebuild.py` | ✅ существует (~42 KB) | Rebuild-джобы GraphRAG, чекпоинты, TaskJobStore, lifecycle gen |
| `services/media_execution.py` | ✅ существует (~40 KB) | MediaExecutionPolicy / adaptive policy (ASAP-3.2 зона 2) |
| `services/model_capacity.py` | ✅ существует (~39 KB) | MODEL_CONTEXT_WINDOWS / capacity resolver (ASAP-3.1/3.2 зона 3) |
| `services/cover_style_registry.py` | ✅ существует (~35 KB) | Cover Style Registry: профили/ассеты/references/counter (EXTRA + hotfix 2.58.43) |
| `cover_style_pipeline.py` | ✅ по пути **`services/cover_style_pipeline.py`** (~12 KB) — в корне репо файла нет | Style pipeline (оркестрация style stage) |
| `services/summary_semantic_reduction.py` | ✅ существует (~10 KB) | Hierarchical semantic reduction (ASAP-3.2 зона 4, ADR-1028-5 D8) |
| `services/summary_fact_package.py` | ✅ существует (~60 KB) | FactPackage build/сериализация/coverage |
| `summary_l2_writer.py` | ✅ по пути **`services/summary_l2_writer.py`** — в корне файла нет | L2 Writer (Эпик 2 S5) |
| `summary_article_formatter.py` | ✅ по пути **`services/summary_article_formatter.py`** — в корне файла нет | Rich/plain formatter (Эпик 2 S5) |

Имена `services/summary_hybrid_pipeline.py`, `services/analytics_service.py`, `services/task_jobs.py` — **не существуют**; их роль выполняют (проверено rg/каталогом):

| Искали | Фактический носитель |
|---|---|
| summary_hybrid_pipeline | `services/summary_generator.py` (~131 KB) — оркестратор Hybrid L1/L2/Legacy + publication |
| analytics_service | `web/api/analytics.py` + `web/api/routes.py` + mca-17a observability core (`mca_events`/`mca_pipeline_runs`) |
| task_jobs (store) | `services/task_supervisor.py` (mca-01, TaskJobStore/`task_jobs`+`write_transaction`); потребители: `graphrag_rebuild.py`, `cover_style_jobs.py`, `mca_episode_jobs.py`, `media_execution.py` |

## 2. Полная reuse-карта по перечню владельца §1 (current_task.md:16600–16613)

| Механизм ASAP-3.2 | Где живёт (проверено) | Что ASAP-4 делает (зона) | Что ASAP-4 НЕ делает |
|---|---|---|---|
| Embedding generation registry | mca-07: SQLite v18 `mca_embedding_index_generations` (+3 индекса); код — `services/graphrag_rebuild.py`, `services/summary_memory.py` | Zone A: расширяет жизненный цикл control-plane'ом (quota groups, scheduler, credentials); generation-реестр остаётся единственным | Второй реестр поколений; изменение v18-схемы без MigrationStep |
| BUILDING → validate → ACTIVE lifecycle | ASAP-3.2 зона 1 (ADR-1028-5 D1/D3), activation — mca-04b (N-MCA07-1, `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED`) | Zone A: добавляет паузируемые состояния (paused_rate_limit/paused_provider), resume same generation, детальную диагностику KNN (§24–§31) | Новый lifecycle-контракт поверх старого; автосмену модели embedding |
| FTS fail-soft | `services/summary_memory.py` + SmartModule A06-путь (прод-логи §0) | Zone A: сохраняется во всех non-active состояниях (§26) | Удаление/усложнение fallback |
| GraphRAG rebuild jobs | `services/graphrag_rebuild.py` (resumable, checkpoint, §85 background completion — ADR-1028-5 D2) | Zone A: единый scheduler P0–P3, quota-group cooldown, общий limiter на оба index (§17/§22/§23) | Вторая очередь задач; отмена честной финализации состояний |
| Provider discovery | ASAP-3.2 зона 3 (Text Capacity Resolver, adapters, `services/model_capacity.py`) | Zone A: provider-agnostic embedding adapter поверх discovery (§13) | Дубликат discovery-механизма |
| MediaExecutionPolicy | `services/media_execution.py` (adaptive policy, durable state, restart recovery — ADR-1028-5 D4–D7) | Zone B: production path Style Edit опирается на неё; capability check `image_edit` (§47) | Новая media-политика |
| Cover Style Registry/Jobs/Provenance | `services/cover_style_registry.py`, `services/cover_style_pipeline.py`, `services/cover_style_jobs.py`, `services/cover_style_edit.py`, `services/cover_style_assets.py`; API `web/api/cover_styles.py`; EXTRA 2.58.39 + hotfix 2.58.43 + ADR-1028-5 D14 | Zone B: selection snapshot, COVER_STYLE_SELECTION, единый pipeline для всех outcomes, видимые reason codes, provenance при fallback (§36–§49) | Второй registry/секундный seed; ломку PgDatabase-vs-Pool контракта (закрыт D14) |
| Seeded `Медведь Press` | PG-сид (EXTRA/ASAP-3.2 D14), профиль medved_press, ассет medved_press.png | Zone B: реальная приёмка на нём (§41/§48/§78) | Пересид экспериментов |
| Per-chat selected style | `cover_style_select` (chat_params-путь, хотфикс 2.58.43) | Zone B: persistence-тест §73, snapshot на run (§36) | Новая точка хранения выбора |
| Summary Hybrid/Legacy fail-soft | `services/summary_generator.py` (+ `summary_l1_*`, `summary_l2_writer.py`, `summary_xml.py`, `summary_throttling.py`) | Zone C/D: закрытие трёх regressions, bounded revision loop, quote repair; fail-soft сохраняется (§50.29/§50.35/§50.38) | Второй Summary-пайплайн; ослабление attribution (§54) |
| Full-window/chunking contracts | ASAP-3.1 (Auto Budgets, `summary_hybrid_budget.py`, `summary_budget_auto.py`) + ASAP-3.2 зона 4 (`summary_semantic_reduction.py`, coverage metrics D8/D9) | Zone C: too_many_facts → chunking/sharding/merge; Legacy без silent XML 50k (§51–§59) | Правка MAX_SUMMARY_PARTS (§58 — не трогать); ножницы-трункейшн |
| Analytics | mca-17a observability core (`mca_events`, `mca_pipeline_runs`, реестр процессов, ADR-1027-8) + ASAP-3.2 зона 7 (actual snapshot, GraphRAG health — ADR-1028-5 D12/D13) + `web/api/analytics.py` | Zone E: Run Inspector / карта пайплайна / embedding-панель — из structured events (§60–§61.16) | Новый корневой dashboard; парсинг логов (§61.12) |

## 3. Сопутствующая инфраструктура (не трогаем, но зависим)

- `services/task_supervisor.py` — TaskSupervisor + TaskJobStore (`task_jobs`): durable-джобы, чекпоинты, resume. Все новые джобы (embedding scheduler) — через него.
- `services/llm_client.py` — существующий LLM client: §13 «не переписывать без причины»; embedding execution выносится над ним.
- `services/pg_db.py` + asyncpg — Connections layer (источник connection metadata для quota groups, R4-A-003).
- `services/summary_run_log.py`, `summary_prompts.py`, `summary_l1_contract.py`, `summary_l1_clusterizer.py`, `summary_l1_repair.py`, `summary_test_run.py` — контур Hybrid: трассировка событий (база zone E), промпты (миграция §50.3), dry-run (приёмка).
- `services/summary_scheduler.py` — cron-публикации; вход в единый run trace (§60).
- MCA-22: `mca_source_refs`/`mca_evidence_links`/`mca_bot_outputs` (v17/v22), Quote Resolver ladder (ADR-1028-6 D3) — для zone D quote-валидации (см. conflict-audit.md §4).
- `services/mca_events.py:REASON_CODES` — словарь reason codes, расширяемый прецедентом mca-03/04a/07/22 (база для новых reason codes зон A/C/D).

## 4. Открытые хвосты, с которыми сталкивается ASAP-4 (не авто-scope, решение @Architect/Orchestrator)

1. **L-EXTRA-6** — `TaskJobStore.save_checkpoint` перезаписывает бизнес-payload (Follow-up EXTRA, backlog п.88): зона B/C затрагивает Cover Jobs — кандидат на закрытие при касании.
2. **L-EXTRA-7** — `cover_job_key` из UUID correlation_id: end-to-end resume через рестарт требует стабильного run_id — напрямую связано с R4-B-001 (selection snapshot/run_id).
3. **`update_reference` rowcount → 200** (Follow-up EXTRA п.3, non-blocking): при касании Registry в зоне B.
4. **L-ASAP31-4** — dry-run `summary_test_run.py:590` без resolver-бюджета: влияет на «Протестировать стиль»/тест-контур зоны B (R4-B-005 единый resolver).
5. **GraphRAG resume после honest-fail** (Follow-up ASAP-3.2 п.1): `graph_facts_vec` gen=1 в терминальном `failed` на 429 — ASAP-4 §24 меняет политику на paused/resume (см. conflict-audit.md — нужен AMEND ADR-1028-5).
6. **smart_archive `failed/knn_smoke_failed`** (Follow-up ASAP-3.2 п.2): разбор root cause и повторный запуск — ровно то, что делает R4-A-026/027/041.
7. **DC-4** — edit-capable image provider в Connections (owner precondition): реальная приёмка §48/§78 возможна только при настроенном Qwen-connection (платные вызовы — владелец).
8. **FACT_PACKAGE_TRUNCATED семантика** (Follow-up ASAP-3.1 п.5, исследование владельца): пересекается с R4-D-031/032 — per-topic cap vs бюджетный потолок; закрыть одним контрактом при касании зоны C/D.

## 5. Что НЕ переиспользуется / запрещено

- Второй GraphRAG, второй Cover Style pipeline, второй Summary (R4-G-001).
- Redis/new infra для multi-process coordination без необходимости (R4-A-020, `current_task.md:17111`).
- Автоматическая миграция на `gemini-embedding-2` (R4-A-013).
- Правка `MAX_SUMMARY_PARTS` (R4-C-010), удаление алгоритмической предфильтрации из ASAP-2.1 (R4-D-038), ослабление quote-attribution проверок (R4-C-006).
- Новый корневой Analytics-dashboard (R4-E-002: «в существующей Analytics, не новый отдельный продукт»).
