# ASAP 8 v6 — Requirements Map (Phase 0)

Baseline: `1e980275ce5c857b825860b50a34a2486c790359` (release 2.58.77). Prod-fact: кандидат 1e98027 задеплоен (pull+restart RC=0), healthz 200 @ 2.58.77; целевые функциональные prod-пробы не выполнялись.

Детали: `ledger-c.md` (C-верды + evidence-точка), `ledger-d.md` (D-инвентаризация), `rca-c03a-styled-cover.md`, `rca-c06a-initiative.md`. Forensic: `forensic.md`.

## Coverage gate (26/26 ID)

| ID | Вердикт | Остаток (next action) | Lane |
|---|---|---|---|
| C01 | CODE_PRESENT_LIVE_UNVERIFIED | prod-проба живого Summary (granular telemetry, repairable абзац не уходит в Legacy) | P1 live |
| C02 | CODE_PRESENT_LIVE_UNVERIFIED | prod-сверка dry-run vs production (fingerprint/anchor parity) | P1 live |
| C03 | CODE_PRESENT_LIVE_UNVERIFIED | реальный styled-provider publish (зависит от C03A) | после C03A |
| C03A | PARTIAL | ABSENT: production retry/recovery styled; `semantic_preservation_failed`; restart-safe style job; publication linkage idempotency | **P0 lane C03A** |
| C04 | CODE_PRESENT_LIVE_UNVERIFIED | global-admin UI проба на проде | P1 live |
| C05 | CODE_PRESENT_LIVE_UNVERIFIED | рестарт с Summary OFF + hot-toggle проба | P1 live |
| C06 | PARTIAL | funnel не в UI; search_result producer не привязан; live E2E pending | **P0 lane C06A** |
| C06A | PARTIAL | hot-ON не регистрирует heartbeat-джобу (бот:101 memory_maintenance:185); funnel не рендерится; liveness in-memory | **P0 lane C06A** |
| C07 | CODE_PRESENT_LIVE_UNVERIFIED | live-резолв на прод-чате | P1 live |
| C08 | CODE_PRESENT_LIVE_UNVERIFIED | rotation против реальных prod-ключей | P1 live |
| C09 | CODE_PRESENT_LIVE_UNVERIFIED | живой proxy health/auth | P1 live |
| C10 | ABSENT | финальная reconciliation + f10-отчёт (test-pins ≠ F10) | финал (D14) |
| D01 | PARTIAL | dossier-половина: request_token/instance-guard на load/save/rebuild; settings-половина закрыта ранее (epoch-guard) | **P0 W-A2** (S) |
| D02 | FAILED | add_link→migrate skip bug (chat_lifecycle:243, chat_lore_store:754-756): ложный already_moved, сирота-профиль; real-storage тесты | **P0 W-A3** (M) |
| D03 | PARTIAL | dedicated L1 мимо key/budget policy (`llm._post(api_key=...)`); repair-attempt usage не пишется; temperature не в payload | **P0 W-C Direct** (M) |
| D04 | PARTIAL (ядро ABSENT) | execution_mode/simple_tools/adaptive_tool_chain/orchestrator отсутствуют (grep=0); evidence packer `packet[:4000]` first-source domination; L2 rebuild под fallback window частично | **P0 W-C Direct** (L) |
| D05 | PARTIAL | `record_feedback` без прод-вызовов (semantic detector отсутствует); курсор/жизненный цикл живы | P1 (L) |
| D06 | FAILED | KNN top-k до chat-фильтра (summary_memory.py:2752 признание в коде; `_dedup_knn` k=3 глобально) | **P0 Wave B** (M) |
| D07 | PARTIAL | нет global-view popover переопределивших чатов, bulk-confirm; модель/бейджи есть | **P1 Wave B** (M) |
| D08 | FAILED | root cause: config_cache.get_all() (:495-523) не синтезирует PG-only ключи без строки БД → memory.random_enabled отсутствует в /api/config → toast | **P0 W-A1** (S) + остаток §10.5 в P1 |
| D09 | PARTIAL | `int(... or 7)` deep_sleep_hour (dream_worker:1682) — 00:00→7; GraphRAG outcome-enum разрознен | **P0 W-A1** (S) + остаток P1 |
| D10 | PARTIAL | web-даты без parse-attempt, `date_parse_failed` отсутствует | P1 (M) |
| D11 | PARTIAL | registry = 5 модулей; Vision/Factcheck/Nostalgia/Dream/dossier/GraphRAG вне | P1 (S→M) |
| D12 | PARTIAL | фундамент есть; Unified Run Card, durable-семантика, Analytics-табы ABSENT | UI last (L) |
| D13 | PARTIAL | постоянный sticky-save + mobile bottom-nav/more-sheet — v5-решения НЕ выполнены | UI last (M+M) |
| D14 | ABSENT | F10-отчёт, help sync, plans-state — строго последний | финал (L) |

## P0 waves (по v6 §D; writer-scope disjoint)

- **Wave A** (запущена): W-A1 = D08-fix + D09-S (backend small); W-A2 = D01 (app.js dossier); W-A3 = D02 (chat migration real-storage)
- **Wave B**: C03A (styled recovery contract) ∥ C06A (initiative hot-toggle + funnel UI) ∥ D06 (chat isolation)
- **Wave C**: D03+D04 (Direct lane, merged contracts) ∥ D07
- **P1**: D05, D09-остаток, D10, D11 + C01–C09 live-пробы
- **UI last**: D12 → D13 → D14+C10

Правило волн: parallel только при disjoint WRITE_SCOPE; Reviewer по исходным ID; DevOps фиксирует deployed SHA + targeted probe.
