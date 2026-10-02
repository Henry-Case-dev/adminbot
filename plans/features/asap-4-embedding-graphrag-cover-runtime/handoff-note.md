# ASAP-4 — handoff-note.md (Step 2 @Architect → Orchestrator, 02.10.2026)

Роль: @Architect (fallback: основной named-Architect недоступен). Границы соблюдены: только design/docs — **без кода, без implementation, без коммитов**. `plans/current_task.md` не изменялся.

---

## Готово (4 файла, все записаны на диск)

| Файл | Содержание | Статус |
|---|---|---|
| `prod-facts.md` | Ответы **Q1–Q17** фактами с прода (journalctl-выдержки с теймстампами 29.09–01.10.2026, sqlite read-only: реестр поколений, task_jobs, счётчики; env-имена без значений ключей) + **Q18–Q37** решениями по коду/дизайну с код-якорями. Приложение воспроизводимости. | ✅ Полностью (37/37) |
| `spec.md` | Дизайн зон A–E: контракты (EmbeddingCredential/QuotaGroup, EmbeddingExecutor, scheduler P0–P3, state machine, KNN reason codes; cover snapshot/SELECTION/единый pipeline/reason codes; L1 capacity guard, quote repair, Legacy full-window; Writer/Reviewer/Revision; stage events, Run Inspector, coverage first-class). DDL delta (SQLite 22→23 additive, PG no-op), kill-switches env-only default-ON (12 флагов, OFF=bit-identical), rollback-матрица, матрица spec-раздел → T-4400+. | ✅ Полностью |
| `adr-1028-7-asap4-embedding-control-plane.md` | Номер сверен (`ls plans/archive`: существуют adr-1028-1…-6 → новый -7). **AM-1** AMEND ADR-1028-5 (429: honest-terminal → paused_rate_limit/resume); **D3** SUPERSEDE «L2 correction retry НЕ вводится» (процедура §50.65: старое решение найдено, bounded revision ×2, budget ≤6 вызовов, `review_degraded`-политика, rollback); **D4** prompt-миграция prose-first; **D1** EmbeddingExecutor + quota groups + scheduler; **D6** Cover единый pipeline (Hybrid+Legacy); **D5** revision = paragraph-patch (обоснование выбора §50.23); call budget §50.57 (happy/rev1/rev2/Legacy — таблица в D3.3 + prod-facts Q31). Supersede/amend register, sanctions, consequences. | ✅ Полностью |
| `handoff-note.md` | Этот файл. | ✅ |

ARCH-задачи эпика, закрытые этим пакетом: **T-4401 (A), T-4414 (B), T-4421 (C), T-4427 (D-ADR), T-4439 (E-schema)** — все пять ссылаются на созданные документы (мэппинг — spec.md §6).

## Ключевые прод-находки (кратко, для владельца/Orchestrator)

1. **Embeddings:** amplification 3×(3+2+2)=21 подтверждён на живом коде; Retry-After капится 8с; оба rebuild в `failed` (graph_facts_vec — 429 с checkpoint 5450/15277; smart_archive — `knn_smoke_failed` на **пустом source**, 0 фактов); ключи — 3 шт на одном endpoint, групп вероятно 2 (fallback#2 — другой аккаунт по коду), proof нет → default одна группа.
2. **Medved Press:** стиль НЕ «потерялся» — он **упал** с `not_configured` за 72мс на всех 3 runs (edit connection/model не настроены = owner-гейт DC-4); image API не вызывался; base cover публиковался; issue counter сгорал на фейлах; Legacy-путь style вызывает корректно.
3. **Summary:** `too_many_facts` — гильотина MAX_FACTS_PER_THREAD=30 при chunks=1 на окне 688; `quote_attribution` — баг §50.20 (reject найденных цитат с именем, quote_unverified=0); XML 50k-кап режет Legacy до 307/688 (4 случая); стирание истории `ctx.status→OK` подтверждено (summary_generator.py:840-841).

## Не сделано / риски / следующие шаги

- **Не в границах роли:** код, тесты, миграции, деплой — волны A–F по tasks.md (Builder/Reviewer/DevOps), начиная с T-4402+ (волна A разблокирована).
- **Owner-гейты (не блокируют код):** DC-4 — настроить edit-capable connection (иначе §48/§78 acceptance невозможен — прод доказал: сейчас style падает `not_configured`); платные live-вызовы §34/§77–§79; developer-labels quota group (Q1: без них все ключи = одна группа).
- **Точки верификации Builder'ом** (честно помечено в доках): строгость параллелизма двух rebuild-джобов под TaskSupervisor (T-4407); достаточность существующих FactPackage refs без новой schema (§50.7); живой контракт async Batch API перед включением `EMBED_ASYNC_BATCH_ENABLED`.
- **Ветка evidence §34:** если full ACTIVE физически долог на free-tier — acceptance допустим по scheduler-proof + меньший slice → ACTIVE; выбор фиксируется на T-4447.
- Нумерация DDL: прод уже на `user_version=22` (спека писалась с учётом; миграция целится в v23 — сверить на момент Builder'а).
