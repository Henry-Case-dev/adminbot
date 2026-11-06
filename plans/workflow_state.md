# Workflow state

Task: UNIFIED-REPLY (UR-A..G merged; UR-G 31/40 bound, 9 rows blocked on UR-C-SCHED/UR-23.4/UR-26.x/preprod/postdeploy — UR-C-SCHED and UR-23.4 since shipped 2.58.161) + REMOVE-LEGACY-REPHRASING-01 (2.58.159, DoD lines await prod observation) + BEHAVIOR-GATES-SIMPLIFICATION-01 (BGS-01..05 shipped/bound, 06 UI shipped/bound, 07/08 open) + EPIC-CM-VISUAL-01 (map ~145+/226 bound; residual batches merged) + PVR-FC-CORRECTIVE-01 (PVR-BACKEND+UI merged/bound 27+6 rows; FC-BACKEND merged, bound 27 rows; PVR-04 redesign/PVR-06/C3.11 open) + search short-tokens (shipped) + MENU-01 Telegram group deep links (порт 14400b73 на evol/impl, ветка int/evol-port-menu01-rci-evol-impl) + EVOL-REPLY-CONTEXT-INTEGRITY RCI-02..04 (FactCheck ambiguity-контекст, порт 1703ff46) + EPIC-MEMORY-COGNITIVE-02 (контракты заморожены, реализация не начата)
Task source: plans/owner_inputs/2026-11-05-unified-reply.md, 2026-11-05-remove-legacy-rephrasing-v2.md, 2026-11-05-behavior-gates-simplification.md, 2026-11-05-pvr-fc-corrective-01.md, 2026-11-07-epic-memory-cognitive-02.md, 2026-11-07-context-integrity-factcheck-clean-publication.md, 2026-11-01-current_task-snapshot-MISSING.md (provenance записи вместо утраченного снапшота)
Status: in_progress
Primary phase: implementation
Active feature: MENU-01 + RCI FactCheck-контекст (портированы на evol/impl) / PVR-FC-CORRECTIVE-01 / UR-C-CLOCK closure после 2.58.161
Active lanes: lanes закрыты (провайдерские обрывы, не инженерные результаты); новая работа — порт на evol/impl в ветке int/evol-port-menu01-rci-evol-impl: docs 571a5737..6aa68e66, MENU-01 14400b73, RCI FactCheck 1703ff46. Независимые ревью MENU-01 и RCI и PVR-04 (350cb228) — UNVERIFIED, требуют переотправки
Join barriers: MENU-01 = порт 14400b73 (base 8bb2800f); RCI = RCI-02..04 (порт 1703ff46); PVR-04 = 350cb228 (base df02ab0c); OI-2026-11-07 зарегистрированы в progress_scope (снапшот 2026-11-01 утрачен, честная провенанс-запись); MEMORY-реализация заблокирована до приёмки contracts.md; production-трасса Reply — PENDING_EXTERNAL
Next unlocks: (1) приёмка порта (docs/MENU-01/RCI) независимым ревью; (2) reconcile UR-C-CLOCK rows и bind только доказанного; (3) PVR-04 review; (4) memory maps + contracts → старт MEMORY-01; (5) live BotFather/Telegram/ACL остаются PENDING_EXTERNAL

Last verified: prod 2.58.161 @ a563ee31 (healthz 2.58.161; app.js served sha256 705a28cd27292e64931e3f47a4936a7fdbf1250edddce69c73b8d4061fe491f9 == local; timezones 401 unauth; migration v42 applied; slot_claims exists; deploy outside due-window — honest skip_expired, no catch-up; rollback 2.58.160 @ 309f69c2 pin by SHA); FC-BACKEND approved+bound 27 rows (pins re-approved a9e91310); PVR-UI approved+bound 6 rows; UR-23.4 bound VERIFIED (factcheck ledger + summary full-text)
Next unlocks: (1) PVR-04 redesign + PVR-06 per-block + C3.11 (PVR-FC open wave); (2) UR-26.3/4/5 summary payload matrix (closes UR-30.4/E4); (3) BGS-07/08; (4) PVR-E2E/EPIC-CLOSE waves; (5) CMV residual tail
Next execution: runnable
Review: approved (UR-C-SCHED 164 passed, FC-BACKEND, PVR-BACKEND, PVR-UI, UR-E/UR-D/UR-F, BGS-05); pending (MENU-01 14400b73 порт, RCI 1703ff46 порт, PVR-04 350cb228)
Deployment: verified (2.58.161 @ a563ee31; rollback 2.58.160 @ 309f69c2 PIN BY SHA — origin/release/2.58.160 moved to 3e7fc51d deploy-doc commit, own session's doc push). Порт на evol/impl НЕ деплоился
Human gate: none
Progress scope: plans/progress_scope.json | унифицирован после порта планировочных артефактов master (44 задачи / 54 owner_inputs; строки обеих линий сохранены, конфликт id evol-reply-context-integrity-01 вынесен отдельным id evol-reply-context-integrity-rci)
Platform note: Reviewer-agent model was exhausted earlier — reviews ran via general agent in adversarial mode, disclosed; owner switched models, regular Reviewer agent re-tested working on latest dispatches
Updated: 2026-11-07T08:50:00+12:00
