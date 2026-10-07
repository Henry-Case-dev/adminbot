# Runtime Task — ASAP 6 / P0

Feature: `asap6-current-task-closure` (Summary Hybrid Recovery + Observability & Status/Analytics UX Repair)
Task source: current_task.md, раздел «ASAP 6 / P0» (строки ~29604–31765) + BINDING ADDENDUM v2
Status: in_progress
Baseline: HEAD 42f8963, prod 2.58.69 (bea9101), v33 DDL=0

## Подтверждённые P0 findings (проверены по коду 07.10.2026)

1. **Summary Legacy-падение (§4)**: `services/summary_l2_review.py:408-412` `_deterministic_unusable_proof` → `bool(metrics.get("quote_reason_codes"))`; `services/summary_quote_repair.py` после успешного ремонта добавляет `quote_attribution_repaired` в `quote_reason_codes` → repaired трактуется как текущий hard blocker → Legacy. Тесты ASAP 5 (`tests/test_asap5_summary_domain.py`) канонизируют баг — переписать.
2. **MCA-23 отсутствует (§2 P0-A, §10)**: 0 вхождений ResponsePlan/response_plan в services/, нет plans/features/mca-23*. workflow_state.md ложно заявляет done. Реализовать после P0-регрессий по оригинальному контракту current_task.md (§33–52).
3. **ANU taxonomy bug (§6)**: web/app.js:10029, web/index.html:2681 — `item.category === 'keys' || item.secret` рендерит все параметры группы keys_random как secret-field («Ключ установлен» на endpoint/defaults). Реальный ключ `keys.random_quantum_api_key` не настроен → provider_unconfigured. Ключ владельца есть в current_task.md (строка ~1865) — сохранить через protected secret path, НЕ хардкодить, НЕ копировать в отчёты. Реальный `/api/random/test`, selected=effective=quantum.
4. **MCA-17 (§5)**: services/mca_process_registry.py — 41 процесс, 21 note «инструментирование mca_events не подключено». Coverage matrix + реальная инструментировка implemented+active процессов; not_implemented placeholders честно отделить. summary.hybrid/publish — adapter/link на Run Inspector.

## P1 findings

5. **Embeddings UI (§7)**: web/app.js зеркалит Fallback 1/2 через shared `models.embedding_fallback_base_url/model`; backend уже имеет `embedding_fallback1_*`/`embedding_fallback2_*` (каталог 529, добавлено в ASAP 5). UI исправить на независимые профили + quota group человечески + effective model.
6. **Embedding generations multi-chat safety (§8)**: таблица generations без chat_id/namespace ownership. Инвариант (chat_id/namespace, semantic_index) → 1 ACTIVE generation; классы совместимости INSTANT_COMPATIBLE/REINDEX_REQUIRED/INCOMPATIBLE_DIMENSION/COMPATIBILITY_UNKNOWN; global change не ломает существующие чаты; per-chat override с snapshot+delta+atomic promotion+rollback.
7. **GraphRAG/paradigms (§9)**: закрытие только по live evidence; controlled paradigm run; building без progress/lease — дефект observability.
8. **UX Status/Analytics (§11–16)**: Status = живая витрина (hero strip, компактные индикаторы, protected patterns: сон/бегущая строка убеждений/graph preview), Analytics = диагностические вкладки (Обзор/Процессы/Запуски/Инциденты/Память/Модели/Саммари/Логи). Playwright + Browser Use обязательны для каждого UI-изменения. visual-preservation-map.md от Architect до UI-writers.

## Внешние правила

- current_task.md — USER-OWNED READ-ONLY (R17: не редактировать).
- Секреты: ANU ключ не попадает в spec/evidence/reports/git/logs.
- Деплой по AGENTS.md: один recon + один деплой-коннект, fail2ban-паттерн; DDL/каталог/KS/reason-инварианты сверять; бэкап перед миграциями.
- Строгий Reviewer: VERIFIED/FAILED/UNVERIFIED/... — зелёные тесты не равны живому поведению.

## Порядок волн (ASAP 6 §18)

- Wave 0: параллельно read-only — audit matrix (Scanner A), MCA-17 mapping (Scanner C), UX survey (visual-preservation-map), Architect boundaries. DONE частично: P0 findings подтверждены локальным аудитом.
- Wave 1: Lane A (Summary quote state) + Lane B (ANU) + Lane C (MCA-17 batch) — непересекающиеся файлы.
- Wave 2: Lane D (embeddings) + Lane E (Status UX) + Lane F (Analytics UX) + C2 (остаток observability).
- Wave 3: MCA-23 реализация + Help re-sync + остатки audit.
- Финал: review → deploy → live acceptance (§22) → финальный отчёт (§26).

DoD: см. current_task.md ASAP 6 §25 (аудит/Summary/MCA-17/ANU/Embeddings/Paradigms/UX/Production).
