# ASAP 6 Spec — Full Current Task Closure + Summary Hybrid Recovery + Observability & UX Repair

Feature: `asap6-current-task-closure`
Source: current_task.md «ASAP 6 / P0» + BINDING ADDENDUM v2 (строки ~29604–31765)
Baseline: HEAD 42f8963, prod 2.58.69, v33 DDL=0, каталог 529, KS 85

## 0. Принцип

current_task.md / последнее распоряжение владельца > production-код > живые проверки > тесты > архивные отчёты.
`Approved`/«current_task полностью выполнен» не доказывает выполнение, если код противоречит.

## 1. P0 фиксы (Wave 1)

### S1 — Summary quote state (Lane A)
Файлы: `services/summary_quote_repair.py`, `services/summary_l2_review.py`, `tests/test_asap5_summary_domain.py`, связанные.
Контракт:
- Разделить «историю ремонтов» (diagnostic) от «текущих unresolved blockers».
- `quote_reason_codes` после успешного ремонта НЕ является deterministic unusable proof.
- `_deterministic_unusable_proof` доказывает терминальность только по ТЕКУЩИМ unresolved hard-блокерам, пересчитанным по текущему документу.
- Hard safety сохраняется: неподтверждённые числа, выдуманные имена, неверная атрибуция, неубираемая цитата — fail-closed.
- Тесты ASAP 5, канонизирующие баг, переписать (RED→GREEN сценарии из §4.4 current_task).

### S2 — ANU secret taxonomy + активация (Lane B)
Файлы: `web/app.js`, `web/index.html`, `services/param_catalog.py` (при необходимости), web config API.
Контракт:
- Рендер secret-field только по `spec.secret == true`, НЕ по категории `keys`.
- Группа keys_random: один настоящий secret (random_quantum_api_key) + обычные параметры.
- Секрет не раскрывается: configured + last4, без plaintext GET.
- Ключ владельца (из user-owned source) сохранить через существующий protected secret persistence path — не хардкодить.
- Реальный `/api/random/test`: валидная ANU-партия, reserve, selected=effective=quantum.
- Status и Settings показывают одинаковый effective state.

### S3 — MCA-17 instrumentation (Lane C)
Файлы: `services/mca_process_registry.py`, `services/mca_events.py` (расширение API при необходимости), целевые модули процессов.
Контракт:
- Coverage matrix: для каждого implemented+active процесса — реальный event flow (start/стадии/terminal outcome/reason/run_id).
- Никаких fake events ради зелёных карточек.
- Специализированные журналы (pipeline_events, task_jobs) адаптируются в registry-маппинг, не дублируются.
- `not instrumented` допустим как audit finding, не как финальное состояние.
- summary.hybrid/publish — adapter/link к Run Inspector.
- not_implemented placeholders (context.compress, context.selective, memory.lifecycle, relations.semantic) остаются честными.
- Семантика состояний: active/disabled/not_run/not_implemented/unavailable/degraded/stale.

## 2. P1 (Wave 2)

### S4 — Embeddings UI (Lane D)
- Fallback 1/2: независимые поля `models.embedding_fallback1_*`/`fallback2_*` в UI, никакого зеркала через shared fallback_base_url/model.
- Quota group человечески (поле у credential + пояснение), raw alias-string в Advanced.
- Effective model показывать при inheritance.

### S5 — Embedding generations multi-chat safety (Lane D)
- Инвариант (chat_id/namespace, semantic_index) → одна ACTIVE generation.
- Классы совместимости: INSTANT_COMPATIBLE / REINDEX_REQUIRED / INCOMPATIBLE_DIMENSION / COMPATIBILITY_UNKNOWN. Equal dimension ≠ compatible.
- Global model change: новые чаты → новый default; существующие — pinned до controlled migration.
- Per-chat override: snapshot + chunked resumable backfill + delta catch-up + validation + atomic promotion + rollback retention.
- Provider alias drift: canary/resolved identity, без silent mixed-space writes.

### S6 — Status UX (Lane E)
- Hero health strip, компактные системные индикаторы (donut только при реальном denominator), «Интеллект сейчас», «Что недавно произошло», Graph preview с semantic zoom, provider/random strip.
- PROTECTED: блок «Сон и активность», бегущая строка убеждений (ticker), graph preview (узлы не удалять), живые ленты фактов/историй/личности, тёмная визуальная идентичность.
- Tech clutter (provider dumps, internal IDs, дубли) — свернуть в progressive disclosure / унести в Analytics.

### S7 — Analytics UX (Lane F)
- Внутри существующего #/oversight: вкладки/якоря Обзор/Процессы/Запуски/Инциденты/Память и интеллект/Модели и расходы/Саммари/Логи.
- Человеческий нейминг, technical details в Developer details.
- Один источник истины на метрику: Status=summary+link, Analytics=detail, Settings=config.

### S8 — MCA-17 batch 2 (Lane C2)
- Остатки процессной инструментировки после Wave 1.

## 3. Wave 3

### S9 — MCA-23 Unified Response Orchestrator
Реализация по ОРИГИНАЛЬНОМУ контракту current_task.md (§33–52): ResponsePlan канон, разделение осей action/task_kind/extent/structure/delivery/tool_policy, удаление глобального hard cap 1–2 предложения (включая PG/hot-config миграцию), Verbalizer fix, fast path micro, Planner до tools, multi-tool executor на базе Tool Loop, ResponseDocument + Delivery Router (plain/rich/media), RichMessage для Direct, fail-soft planner, plan validation, bounded execution, idempotency, ExecutionGraph planned-vs-actual, Analytics Response Pipeline, golden E2E A–R, Help re-sync.
Запрет: второй coordinator; producer/user-instruction конфликтов «longform vs строго 1-2 предложения».

### S10 — Help re-sync + остатки audit gaps.

## 4. Верификация

- Focused RED→GREEN на каждый фикс; affected neighborhood; полный pytest один раз перед release.
- Playwright + Browser Use для КАЖДОГО UI изменения (desktop/laptop/mobile), visual-preservation-map до старта UI-writers, Visual Neighborhood Sweep.
- Live production acceptance (§22): Summary (Hybrid runs, controlled Legacy, Inspector reason), ANU (ключ, /api/random/test, quantum), Embeddings (независимость, generation state), Paradigms (controlled deep sleep), MCA-17 (реальные traces), Status/Analytics (Playwright+Browser Use против живого MiniApp).
- Reviewer: строгие статусы VERIFIED/FAILED/UNVERIFIED/...; coverage gate против всего current_task перед done.

## 5. Деплой

Один SSH-коннект по AGENTS.md, pull --ff-only, DDL-инварианты сверить (ΔDDL=0 цель), бэкап при изменениях схемы, рестарт ×2, healthz, смоуки, boot-лог чистый. Секреты (ANU ключ) не в логах/отчётах.
