# Workflow State

Task: ASAP 8 v6 — corrective delta after F1–F9 (plans/ASAP8_v6_delta_after_F1-F9.md, USER-OWNED)
Task source: v6 delta — ВЫПОЛНЕНА (все 26 ID); исходный ASAP 8 — историческая задача
Status: deployed 2.58.78 — остался owner live-acceptance (Visual + прод-поведение) для formal close
Primary phase: done (deploy complete; owner gates pending)
Active feature: asap8-v6-remediation

Baseline: HEAD/prod = b9ea490 / 2.58.78 (healthz 200, journal чист). Вся линейка коммитов v6: bfbc3df→b9ea490 (Wave A/B/C + гигиена + D14 + bump). Известный uncommitted шум НЕ трогать: services/disk_retention.py + tests/test_disk_retention_deploy_backups.py (чужая D1-работа), plans/MEMORY.md, backlog.md, archive/, reports/mca20_wth, tools/_ui_mca12*, node_modules, AGENTS.md, package*.json, plans/ASAP8_v6_delta*.md (USER-OWNED).

Финальная reconciliation: plans/features/asap8-v6-remediation/f10-report.md — 26 ID, вердикты, 7 осознанных остатков, OWNER_VISUAL_PENDING отделён.

Завершено (v6, все REV Approved, деплой 2.58.78):
- Wave A: D02 supergroup migration bfbc3df; D08+D09 e606ec8; D01 dossier guard 6230fde
- Wave B: C06A initiative hot-toggle+funnel 5c521fd; D06 chat isolation cadd432; C03A styled recovery 8700628 (после REV-фикса Critical idempotency)
- Wave C: Direct D03+D04 + D07 overrides map 2ef6189 (после re-pin mca10b)
- P1: D05 Experience f2192b6; D09+D10+D11 2e40615 (после REV-фикса D10 fallback allowlist)
- UI: D12+D13 217c965 (после REV-фиксов F1 funnel sum + F2 role guard)
- D14 help v9/v6 + f10: 51a243f; bump 2.58.78: b9ea490
- Full sweep финал: 3 failed = 2 pre-existing (direct_chat_concurrency, asap5_paradigms_diagnostics — stash-верифицированы) + 1 flaky (nostalgia) — все задокументированы, вне зон

OpenViking: adminbot_asap8_reliability_cleanup.md + adminbot_asap8_workflow_lessons.md (round 1); v6-дельта — в f10-report.md (repo)

Owner live-чеки (Human Gate формального закрытия v6, §29/f10):
1. C03A: Summary со стилем → styled появляется; при фейле — Base + причина в Inspector; recovery восстанавливает без второй Base
2. C06A: Initiative ON → тик ≤300с без рестарта; воронка в Status показывает стадию
3. D08: тумблер Случайности работает (без «Параметр недоступен»)
4. D02: supergroup-перенос на живом чате (если случится)
5. D13: мобильная навигация верхняя, футер только при dirty; D12: Run Card'ы с честными стадиями
6. D05: цепочка опыта + полезность в Memory; D03/D04: Direct с ключами/инструментами
7. D09: Сон 00:00 = полночь; отложенные группы обрабатываются

Backlog (осознанные остатки v6, не блокируют): search_result producer (нет детерминированного сигнала); GraphRAG _vec_candidates анти-паттерн + partition key DDL (отдельный slice); 7 виджетов D12 §18I.12 (Sankey/heatmap/dependency map — данные готовы, рендер следующий); demote_reason в plan_meta; diction style_job_failed; Stories recall-эмиттер (mca-05); stories [:50] cap; Direct concurrency тест (stale счётчик); dossierSaving shared; Experience K2-OFF ре-обработка

Review: approved (все волны v6: A/B/C/P1/UI/D14)
Deployment: прод = 2.58.78/b9ea490 — полный v6
Human gate: owner visual/live чеки (список выше) — единственное условие формального закрытия v6
Updated: 2026-10-14 (v6 deployed 2.58.78; owner gates pending)
