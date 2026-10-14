# ASAP 6 — Current-Task Audit Matrix (компактная, Wave 0, 07.10.2026)

Статусы: VERIFIED | PARTIAL | REGRESSED | MISSING | CONTRADICTED_BY_UI | BLOCKED_REAL_HUMAN_GATE | N/A
Принцип: архивный «done» не засчитывается при противоречии коду/runtime.

| # | Требование (current_task) | Код/факт | Статус | Gap / next action |
|---|---|---|---|---|
| 1 | MCA-01..22 базовая программа | round 10.48/10.49 RELEASED+VERIFIED, прод 2.58.69 | PARTIAL | Живёт; owner-гейты остались открытыми (см. backlog Round 10.48/ASAP5); переоткрытие — только по конкретным регрессиям |
| 2 | MCA-23 Unified Response Orchestrator | 0 вхождений ResponsePlan; нет feature-папки; workflow_state заявляет done | **MISSING** | Реализовать полностью по §33–52 (Wave 3), затем Help re-sync |
| 3 | ANU quantum активирован при деплое (§14.2-14.4) | runtime `provider_unconfigured`; ключ не сохранён в protected store; UI рендерит параметры группы как секреты («Ключ установлен» на endpoint/defaults) | **CONTRADICTED_BY_UI + REGRESSED** | S2: taxonomy fix + сохранить owner-ключ + реальный /api/random/test + selected=effective=quantum |
| 4 | MCA-17: новый процесс без наблюдаемости = незавершённая интеграция (§27) | mca_process_registry: 41 процесс, 21×«инструментирование mca_events не подключено» | **REGRESSED** | S3/S8: coverage matrix + реальная инструментировка; not_implemented честно отделить |
| 5 | Summary Hybrid стабильность (ASAP-цепочка) | `_deterministic_unusable_proof` = любой quote_reason_codes → repaired=blocker → Legacy; тесты ASAP5 канонизируют баг | **REGRESSED** | S1: repaired≠blocker; текущие blockers пересчитываются; тесты переписать |
| 6 | Embeddings Fallback 1/2 независимые профили (ASAP 5 §13C) | backend keys есть (`embedding_fallback1/2_*`), UI зеркалит через shared `models.embedding_fallback_*` | **CONTRADICTED_BY_UI** | S4: UI на независимые поля + quota group + effective model |
| 7 | Embedding generations multi-chat safety (ASAP 5 §13D) | таблица generations без chat_id/namespace ownership | **PARTIAL** | S5: scope+совместимость+safe migration; оценка объёма отдельная |
| 8 | Paradigms: конкретная причина пустого пула (ASAP 5 §13A) | gate≠last-attempt сделано в ASAP 5; live evidence «Парадигм: 0» без реального controlled run | **UNVERIFIED** | S9-до: controlled deep sleep run с полным отчётом стадий |
| 9 | GraphRAG: building → active lifecycle (ASAP 3.2/5) | future-resume тик сделан; live статус требует проверки прогресса/блокеров | **UNVERIFIED** | Live-проверка: прогресс/lease/blocker, отсутствие спама WARN |
| 10 | Random fallback честный config-state (ASAP 5 §14) | explicit pseudorandom без WARN; quantum+no-key → понятный blocker | PARTIAL | Закрывается вместе с S2 |
| 11 | Status = живая витрина (MCA-12/17 + ASAP 6 §12) | provider dumps/tech IDs на Status, cockpit-feel | **PARTIAL** | S6 с visual-preservation-map (protected: сон/ticker/graph/ленты) |
| 12 | Analytics = диагностическая зона (§13) | infinite-scroll свалка без навигации | **PARTIAL** | S7 вкладки/якоря + human naming |
| 13 | Playwright + Browser Use для UI-правок (ASAP 5 §15) | правило закреплено; следить в Wave 2 | PARTIAL | Применять в S6/S7 |
| 14 | workflow_state соответствует current_task | заявляет done при MISSING MCA-23 | **CONTRADICTED** | Исправлен уже: status in_progress до закрытия ASAP 6 |
| 15 | Секреты не в логах/отчётах (R17) | R17-сканы в релизах 0 | VERIFIED | Продолжать в Waves |

Полнота: матрица расширяется по мере Wave 0 сканов (MCA-17 mapping, UX survey). Финальная coverage-gate перед done — против полного current_task §25 DoD.
