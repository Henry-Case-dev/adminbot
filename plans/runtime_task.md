# Runtime Task — ASAP 7

Feature: `asap7-cognitive-direct-pipeline`
Task source: user-owned `plans/current_task.md`, раздел «ASAP 7 — Cognitive Direct Pipeline + Module Contract + Cover Truth + Multi-chat Corrective Audit» (конец файла, ~строки 31769–33788). Этот файл — только recovery-указатель, не дубликат требований.
Status: in_progress — Phase 0 forensic audit (§25: без кодинга до audit report)

Baseline: HEAD 08a8849 (uncommitted шум: services/disk_retention.py, plans/MEMORY.md, backlog.md, tools/_ui_mca12_stories_e2e.json — зафиксировать в аудите как аномалию baseline), prod 2.58.71 (8b44669).

## Карта работ (полные требования — в current_task.md ASAP 7)
- A: Direct L1 Planner (pre-tool semantic) → Tools → L2 Writer; расширить существующий Decision Maker, не плодить 3-й мозг; L1 = 1 LLM call + L2 = 1 call; отдельный model slot L1 в MiniApp (§2)
- B: убрать semantic-hardcode из MCA-23 primary path; response_extent.py — только compatibility/fallback/explicit-form (§3)
- C: Module Contract — Product Complete = runtime + module/submodule + master toggle + settings + effective state + диагностика + Help + tests + live acceptance; ModuleSpec/registry + invariant test (§4)
- D: Initiative/Intents — первый corrective case: backend есть, MODULES-регистрации нет (§5)
- E: аудит «backend есть, модуля нет» по всем крупным фичам (§6)
- F: новый чат не появляется в selector — membership lifecycle join/leave/re-add/migration/fallback (§7)
- G: Cover Prompt Truth — root cause style-only cover; live preview exact compiled prompt; Run Inspector admin-only exact prompt; style-only anomaly guard; E2E A/B с semantic markers (§8–12)
- §13: провал прозрачности ASAP 5 (задачи закрыты, хвосты ушли в backlog) — поднять spec ASAP 5, закрыть missing

## Гипотезы старта H1–H5 (§1.3) — Phase 0
H1 response_extent.py = hardcode-классификатор вместо semantic planning; H2 существующие Direct L1/L2 (synthesizer+verbalizer) = post-tool System2, не требуемый pre-tool L1; H3 _SANDWICH_REMINDER/промпт-хвосты душат extent; H4 prod acceptance MCA-23 не завершена; H5 Help обещает больше реальности planner.

## Фазы (§21)
0 Scanner/forensic → 1 Architect → 2 Builder F1–F9 (deployable slices) → 3 Reviewer → 4 Scanner dead-path audit → 5 DevOps deploy. DoD §23, отчёт §24, запрещённые решения §22 (22 пункта).

## Phase 0 lanes (read-only; каждый пишет только свой файл в plans/features/asap7-cognitive-direct-pipeline/)
- P7-A audit-direct.md: H1–H3, полный Direct call graph, CLAIM(Direct-пункты отчёта ASAP 6 фазы 2)
- P7-B audit-cover.md: seams Summary→cover_prompt→compiler→provider request, style-only root cause, CoverPromptManifest/Run Inspector reality
- P7-C audit-modules-chat-claims.md: module inventory, Initiative, chat_profiles→/api/access/chats→selector, CLAIM(ANU/MCA-17 19+2/v34/Help/prod 2.58.71)

## Инварианты
- current_task.md READ-ONLY; R17: секреты (ANU ключ и пр.) не копировать в отчёты/код/логи; SSH на 198.46.175.136 запрещён (fail2ban), только HTTP /healthz.
- Owner-contracts §0 не ломать: Force = REPLY, SILENT direct → 🗿, реакции = полноценный исход; модели не хардкодить; без 3-го LLM-прохода в Direct (§2.7); L1 не получает весь Writer-контекст (§2.9); полный prompt модели — только в admin-only диагностике (§0).
- Verdict-словарь §1.2: VERIFIED / PARTIAL / FALSE / LIVE_PENDING / UNVERIFIED / SUPERSEDED. pytest green ≠ acceptance.
