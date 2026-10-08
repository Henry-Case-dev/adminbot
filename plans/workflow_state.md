# Workflow State

Task: ASAP 7 — Cognitive Direct Pipeline + Module Contract + Cover Truth + Multi-chat Corrective Audit
Task source: current_task.md (раздел ASAP 7, конец файла; USER-OWNED READ-ONLY)
Status: in_progress
Primary phase: prepare (Phase 0 — forensic audit, без кодинга до audit report)
Active feature: asap7-cognitive-direct-pipeline

Baseline: HEAD 08a8849 (uncommitted шум: services/disk_retention.py, plans/MEMORY.md, backlog, tools/_ui_mca12_stories_e2e.json — зафиксировать в аудите), prod 2.58.71 (8b44669). ASAP 6 core закрыт, фаза 2 MCA-23 core задеплоена; live-acceptance фазы 2 осталась владельцу (= гипотеза H4).

Active lanes (Phase 0 = DONE, 3/3 аудита в plans/features/asap7-cognitive-direct-pipeline/):
- P7-A done: audit-direct.md — H1–H4 подтверждены
- P7-B done: audit-cover.md — style-only гипотеза (стиль первым + GENERATE без лимита)
- P7-C done: audit-modules-chat-claims.md — chat selector root cause (observer chat_member vs my_chat_member, chat_lifecycle.py:76/148; upsert_profile_on_join мёртв; fallback отсутствует); Initiative/Stories/SelfModel orphan; MCA-17 «19+2» SUPERSEDED (факт: 47 карточек, 40 instrumented)

Active lanes (Phase 1 = DONE):
- ARC-1 done: architecture.md — «Вопросов владельцу: нет»; отдельный pre-tool L1 (fused отклонён), Синтезатор → deterministic packaging, Вербализатор → L2 на всех путях; Cover: F8→F6→F7, порядок строки STORY→CONTEXT→STYLE; модули: аддитивный registry; chat: my_chat_member + fallback

Active lanes (Phase 2, Wave 1 — 3 параллельных writer-лейны, write-области непересекающиеся):
- F5 | Builder | done | Chat lifecycle | bg:ses_ee2cf832fffdYR5ZiaMmc5XuS1 | my_chat_member + fallback + refresh UX + badge; 22 теста passed; Orchestrator-проверка: хендлеры :87/:180, middleware bot.py:902 — ок; отчёт f5-report.md. Live-чек «добавил бота → чат в селекторе» = owner-гейт после деплоя
- F8 | Builder | done | Cover read-path | bg:ses_ee2cf831bffeekzXGLBU5XNfAU | include_prompt admin-only fail-closed + UI exact prompt; 12 тестов passed + Playwright; Δroutes=0; Orchestrator-проверка: analytics.py:621/645-655, reader cover_style_jobs.py:1328 — ок; отчёт f8-report.md. Live-чек (2 разных summary → сверка final_prompt) = owner-гейт после деплоя
- F3 | Builder | writer | Module registry | bg:ses_ee2cf832fffe9byGy2Uc46SSb4 | module_registry.py + Initiative карточка + M1/M4/M2

Join-reconcile (Wave 1):
- JOIN DONE: совместный прогон test_asap7_* = 48 passed; test_round1025_f8_registry = 29 passed (пин переутверждён F3 штатно); catalog_zero_delta = 3 passed (дельта каталога осознанная); node --check OK
- F5/F8 отчёты перепроверены точечно Orchestrator-ом (хендлеры :87/:180, middleware bot.py:902, analytics.py:621/645-655, reader cover_style_jobs.py:1328)
- REV-1 | Reviewer | read-only | Wave 1 | bg:ses_ee25f2212ffeIVVhHFrWNqcorZ | adversarial-ревью write-scope дисциплины + контрактов + целостности волны

P7-A ключевые находки (перепроверены Orchestrator-ом grep/read):
- H1 TRUE: classify_request (response_extent.py:270) — 0-LLM regex-план до LLM (direct_chat_service.py:2315); social_chat→compact; multi-tool только 2+URL
- H2 TRUE: L1/L2 = post-tool System2 (гейт требует ToolLoopResult+tool_trace, :2807-2818); UI L1/L2 биндятся на один models.llm_model_name (web/app.js:10359)
- H3 PARTIAL: cap удалён из канона/PG, но _SANDWICH_REMINDER «коротко, по делу» безусловно последним блоком каждого промпта (:3637-3638) → D11 FAIL
- H4 TRUE (LIVE_PENDING): 08a8849 — golden 18/18 stub, live за владельцем; прод 2.58.71 healthz 200
- P1 баги: env kill-switch-ы (DIRECT_TOOL_PLAN_ENABLED и др.) не объявлены в config/settings.py → заявленный откат не работает; Decision Task сплавлен с tool-loop (SILENT после платных тулов возможен); P2: Analytics 24ч/7д = in-memory ~15-20 прогонов

P7-B ключевые находки (перепроверены Orchestrator-ом grep):
- Сборка промпта идёт BASE_STYLE→STORY_SCENE→SUMMARY_CONTEXT (cover_prompt_assembly.py:154,209-215) — стиль ПЕРВЫЙ; GENERATE-маршрут не резолвит prompt-limit провайдера (image_generation.py: match=0) → вероятный style-only симптом: provider-side кап молча режет хвост (story+context). Runtime-подтверждение — через durable-артефакты (media job prompt / task_jobs cover_base final_prompt), читателей НЕ существует
- Прозрачность FALSE: Run Inspector исключает промпты (analytics.py:622-624), UI показывает только char counts (index.html:795-841); Assembly VERIFIED; anomaly guard §11 отсутствует; «один compiler» нарушен (Summary Test — легаци 2-компонентная сборка, summary_test.py:370)
- Баги → F6 (guard+GENERATE-limits+ordering), F7 (live editor exact text, 3 компилятора), F8 (production manifest read path + UI exact)

Join barriers:
- Wave 1 join (F5+F8+F3) → reconcile (app.js секции, index.html регионы) → Reviewer Wave 1 → commit+deploy → Wave 2 (F1 ∥ F6) → Wave 3 (F2 ∥ F7 ∥ F4) → F9 → финальный full suite → production acceptance (DoD §23)

Last verified:
- current_task.md прочитан полностью (33 788 строк), ASAP 7 §25: старт с forensic, не с кодинга
- HEAD 08a8849 = docs-коммит, оставлявший live acceptance владельцу (совпадает с H4)
- Spot-checks: _SANDWICH_REMINDER безусловный (:3637-3638); kill-switch-ов нет в config/; classify_request до LLM (:2315); cover порядок BASE_STYLE первым (:154); GENERATE без лимита (image_generation.py); chat_lifecycle на chat_member-observer (:76,148)

Next unlocks:
- Wave 1 join → Reviewer → deploy → Wave 2 (F1 Direct L1 core ∥ F6 Cover content-loss)
Review: pending (REV-1 идёт по Wave 1)
Deployment: pending (после Approved: commit+deploy Wave 1)
Human gate: none
Updated: 2026-10-09 (старт ASAP 7 Phase 0)
