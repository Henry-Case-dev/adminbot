# Workflow State

Task: ASAP 8 — Reliability / Truthfulness / Module Runtime Cleanup
Task source: current_task.md (раздел ASAP 8, конец файла; USER-OWNED READ-ONLY)
Status: in_progress
Primary phase: build (Phase C — Builder slices; Phase A/B done 10.10)
Active feature: asap8-reliability-truthfulness-cleanup

Baseline: HEAD 0c4f3a5 (release 2.58.74 = ASAP 7 финал). Известный uncommitted шум (НЕ трогать): services/disk_retention.py, plans/MEMORY.md, backlog.md, archive/, reports/mca20_wth, tools/_ui_mca12_stories_e2e.json, node_modules, AGENTS.md, package*.json. plans/current_task.md — owner-owned вне master-трекинга, не коммитить.

Фазы (артефакты в plans/features/asap8-reliability-truthfulness/):
- Phase A forensic: DONE — audit-summary.md (2/2 CONFIRMED), audit-cover.md (4/4), audit-modules-infra.md (10/10 + Summary=замаскированный bootstrap-master в bot.py:840-874)
- Phase B Architect: DONE — architecture.md: F1-F10 контракты, ΔDDL=0, spine F1→F2→F3→F4→F5→F7→F10 serial; F6/F8/F9 PARALLEL_SAFE
- Формер F1 (ses_ede15e9a…, 10.10) не оставил артефактов — перезапущен

Active lanes:
- F1 | Builder | DONE | Summary L2 validator repair + granular diagnostics + UI truth | ses_ecf35a45fffeSS3N41pdTKv3en | 79 focused passed; полный summary-sweep 1659/2 pre-existing; node --check OK; Playwright+Browser Use; отчёт f1-report.md; кандидат в рабочем дереве (не закоммичен)
- F1 | Builder | done+committed | Summary L2 validator repair | 2.58.75 | REV-F1 Approved после речека anchor-механизма (zip→repair_projection, RED→GREEN, sweep main-env 1665/0); отчёт f1-report.md
- REV-F1 / REV-F1-2 | Reviewer | approved | блокер zip-рассинхрон закрыт (split наследует якоря, drop исключает, fail-closed), скоуп чист, aiogram-объяснение подтверждено (3.31.0 main env) | ses_ecee72565ffeKuqD4HR1Iz4Bkq | binding: финальный sweep выполнен Orchestrator-ом по критерию ревьюера
- F6 | Builder | writer | Initiative v2: producers→decision→L2 Writer(trigger=initiative)→SendRecheck→send + freshness recheck §18D + funnel | bg:ses_ecee72564ffeDrve3qZNVrKC7w | direct_chat_service/mca_intents/memory_maintenance/status_service/L1-parser; I1-I9

Next unlocks:
- F6 done → REV-F6 → commit → запуск F8 (Embeddings quota-groups; memory_maintenance.py освобождается после F6)
- Волна F2+F9 (запуск после коммита F1): F2 (spine: build_summary_execution_input, S5-S7) ∥ F9 (YouTube 407 permanent, Y1-Y5)
- Spine далее: F3 (Style preservation) → F4 (exact prompt UX) → F5 (module dependency truth) → F7 (Stories, BLOCKED_BY F5) → F10 (reconciliation, финал)

Join barriers:
- Каждый slice: focused тесты → Reviewer → коммит/деплой when safe → prod evidence (§27)
- Финал ASAP 8: production proof всех P0 + plans-state согласован + отчёт §30 (IMPLEMENTED/TESTED/DEPLOYED/LIVE VERIFIED/OWNER PENDING)

Last verified:
- 2026-10-13: read current_task.md полностью (до ~37k строк), активная задача = ASAP 8; HEAD/прод = 0c4f3a5/2.58.74; Phase A/B артефакты целы; старый F1 мёртв (0 артефактов), F1 перезапущен

Review: pending (per-slice после Builder)
Deployment: pending (slices по мере approve; база прода 2.58.74)
Human gate: только live-acceptance P0 владельца для закрытия ASAP 8 (§29; Direct core — без human gate по §0)
Updated: 2026-10-13 (ASAP 8 resume; F1 relaunch)
