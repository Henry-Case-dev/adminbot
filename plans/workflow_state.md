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

Active lanes (Wave 1 = DONE, закоммичена и запушена):
- e6670b0 feat(asap7-wave1) 2.58.72: F5+F8+F3, Review Approved (REV-1), version bump + 13 пинов, param-registry переиздан; push origin/master ok

Active lanes (Wave 1 = DONE): e6670b0 2.58.72 (F5+F8+F3, REV-1 Approved) — в проде
Active lanes (Wave 2 = DONE, закоммичена и запушена):
- 71b3b69 feat(asap7-wave2) 2.58.73: F1 (Direct L1 Planner, 37 тестов D1-D15, legacy-паритет) + F6 (Cover fix, 35 тестов, B11 closed речеком); REV-2 Approved; push ok

Active lanes (деплой W2 + Wave 3 — 3 Builder-лейны):
- DEPLOY-W2 | DevOps | done | Wave 2 | bg:ses_ee1f86c8affe80VtnNE9gm6b99 | VERIFIED: прод 71b3b69 = 2.58.73, healthz 200 внутрь+внешне, pull ff-only, sha256 5/5, рестарт 1х NRestarts=0, boot ERR=0 (1 known EmbeddingGroupCoolingDown — pre-existing), defaults: DIRECT_L1_ENABLED=True, story_first; rollback готов; evidence deploy-w2-evidence.md
- F2 | Builder | done | Direct settings+analytics | bg:ses_ee1f86c87ffe41l6RKxxZ6vzIs | 18 тестов; каталог 9 PG-only ключей L1; ΔDDL v35 plan_meta (backup-guard); durable-оси 24ч/7д; SECTION-DIRECT-UI (D-5, resolved, REV-2б по-русски); Playwright 28/28 + Browser Use; отчёт f2-report.md
- F2-FOLLOWUP | Builder | done | plan_meta wiring | bg:ses_ee19f2c5affewmDvCmOokzqN7A | fail-open UPDATE по corr (:261/:268/:3587/:3593), покрывает main+silent/react; whitelist+bounded; 57 passed (direct_settings+direct_l1)
- REV-3 | Reviewer | read-only | Wave 3 | bg:ses_ee14b95bfffebibAp4keuoOQxe | ретрай после отмены рантайма; adversarial: DDL/каталог/plan_meta + preview fail-closed + registry completeness + секции
- F7 | Builder | done | Cover live preview | bg:ses_ee1f86c87ffdzdjBkrem32a6So | 21 тестов (parity golden, fail-closed, honest no_context); Summary Test → compose_base_cover_prompt (перепроверено :421), preview-compile :1463; cleanup дубля; ROUTES pin цел; Playwright+Browser Use; отчёт f7-report.md
- F4 | Builder | done | Module completeness | bg:ses_ee1f86c89ffeBmqQVoH52N0gmv | registry +4 (stories/character/experience/random — перепроверено :102+, mca_gates 13 AND-гейтов F4 §3.3); 29/29 + соседи 384 passed; Playwright+Browser Use (хаб 19 карточек); отступ mca_gates задокументирован; отчёт f4-report.md

Join-reconcile (Wave 3):
- JOIN DONE: re-issue f8_baseline+param-registry (560/120/118), пины зелёные (29+24); полный asap7-набор 176 passed; node --check OK

Non-blocking (REV-2 → адресаты):
- #1 дубль _observed_limit_meta → F7 (cleanup)
- #2 L1_PLAN resolved пуст → F2 (Tools planned widget)
- #3 per-chat autonomous toggle семантика → F2 UI + F9 help
- #4/#6 — заметки/косметика, в backlog

Join-reconcile (Wave 2):
- JOIN DONE: test_asap7_direct_l1 + test_asap7_cover_fix + test_prompt_migrations = 109 passed в общем дереве; F6-флаг про миграции закрыт (F1 донёс лестницу)
- test_summary_publish_integration…l2_publishes_article — pre-existing RED на HEAD (вне волны)

Owner acceptance (живые проверки, не блокируют конвейер):
- Wave 1: чат-селектор (новый чат появляется); Run Inspector «Фактический промпт» — 2 разных саммари → сверка final_prompt (style-only?); карточка #/modules/initiative; badge «неактивен»
- Wave 2: Direct в чате — короткие контекстные вопросы («а этот?») понимаются по контексту; «распиши подробно» не режется; фанфик не 1-2 предложения; агрессия в уместном контексте — семантический отпор; обложки саммари — сюжет соответствует выжимке

Watch (не Wave 1, наблюдать): 1 traceback на буте EmbeddingGroupCoolingDown в embedding_canary_check — задокументированный fail-safe (FTS-only A06), домен embedding-квот из ASAP 4.4/5

Join-reconcile (Wave 1):
- JOIN DONE: test_asap7_* 48 passed; registry 29; zero_delta 3; node --check OK; конфликт пинов разрешён штатным re-issue
- REV-1 Approved: секции app.js не пересеклись; R17 fail-closed; effective_gate AND; pre-existing RED tool_loop подтверждён на чистом HEAD

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
- DEPLOY-W1 → owner live-чек (чат в селекторе; 2-click сверка final_prompt двух саммари в Run Inspector)
- Wave 2 join (F1+F6) → Reviewer → commit/deploy → Wave 3 (F2 ∥ F7 ∥ F4) → F9 → финальный full suite → production acceptance (DoD §23)
Review: approved (Wave 2, REV-2 + речек B11 closed)
Deployment: verified (Wave 2 в проде: 71b3b69 / 2.58.73; Wave 3 в работе)
Human gate: none
Updated: 2026-10-09 (Wave 2 закоммичена/запушена; деплой W2 + Wave 3 идут)
