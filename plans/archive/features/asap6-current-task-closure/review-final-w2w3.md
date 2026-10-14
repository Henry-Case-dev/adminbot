# ASAP 6 — Final Review Gate (W2-EF + W3-M core), 08.10.2026

Reviewer: independent final gate. Candidate = worktree @ HEAD f1c78ce (full unstaged diff + untracked).
Binding: worktree fingerprint f1c78ce + diff on 08.10.2026; evidence env = local .venv, prod NOT touched.

## Acceptance ledger

| Item | Status | Evidence |
|---|---|---|
| A1 Cap убит в каноне+вербализаторе; слепки байт-в-байт | VERIFIED | runtime import: cap-строк нет в CHAT_SYSTEM_PROMPT/DIRECT_VERBALIZER_SYSTEM_PROMPT, есть в PREV_*; test_prev_snapshots_keep_cap_text |
| A2 PG-миграции (ступень №9, verbalizer первые ступени, custom→skip, rollback-стек, resolve) | VERIFIED | prompt_migrations.py + TestMca23Migration (incl. test_resolve_after_migration_gives_new_canon, custom нетронут) |
| A3 response_extent: explicit-приоритет, micro fast path 0 LLM, extent-блоки без ёлочек/тире, alias §5, scrub | VERIFIED | response_extent.py + TestClassifyRequestGoldens/TestPromptConflictScrubLive |
| A4 CoordinatorDecision +5 полей, fail-open, fast path без новых LLM-вызовов | VERIFIED | __post_init__ нормализация; classify 0 LLM; call-count измерение НЕ сделано (DoD-48 residual) |
| A5 Verbalizer executor: extent_block="" байт-паритет (factcheck/summary не сломаны) | VERIFIED | test_compose_without_extent_byte_parity; summary/factcheck файлы: 0 extent-упоминаний |
| A6 Rich delivery: report/deep_research И ≥400; fallback на ТОТ ЖЕ answer; ledger/dedup/freshness целы | VERIFIED | _send_direct_answer rich-ветка fail-open; finally set_dedup(answer_text) сохранён; test_rich_failure_falls_back_to_plain |
| A7 llm_client max_output_tokens: None → ключа нет | VERIFIED | payload-тест TestLLMGenerateMaxTokens |
| A8 REACT/SILENT/🗿/force-keyword не тронуты | VERIFIED | тесты не переписывались (3 патча plan-OFF — изоляция); полный прогон |
| A9 Golden A/B/C/L соответствуют §44 | VERIFIED | test_mca23_response_plan.py: фанфик→longform; да/нет→micro; коротко vs подробно → explicit |
| A10 Переписанные тесты санкционированы (MCA-23 §10) | VERIFIED | test_no_global_hard_cap_mca23 ассертит НОВЫЙ owner-контракт, не подгонка |
| A11 Summary не тронут MCA-23 | VERIFIED | 0 extent/mca23-hits в summary_*/handlers/summary |
| B1 8 вкладок в #/oversight, Δendpoint=0 | VERIFIED | oversightTabs[8]; routes pin f25e759e цел; новых fetch нет |
| B2 Переносы: логи-вьюер, история ключей→Модели, Run Inspector→Саммари; v-if-гварды | VERIFIED | index.html 4202 (summary), 4808 (models); js-тест tabs |
| B3 Status KEEP-блоки, strip честный, случайность <details>, hero только при проблемах | VERIFIED | скриншоты status_desktop/mobile + bu_status_strip; v-if statusProblemsCount:5956 |
| B4 Guard-фиксы (vector_memory.indexes, storiesSummary.progress) | VERIFIED | app.js:13728 цепочка; index.html:6513/6476 |
| B5 Честность данных («—», без fake %) | VERIFIED | скриншоты: «нет данных», «1 из 1 OK», «запас 128/1024» |
| B6 js 68/68 | VERIFIED | прогнано ревьювером: 68/68 PASS |
| B7 Скриншоты читаемы, protected живы | VERIFIED | 5 скриншотов просмотрено (overview/logs/status desktop+mobile/bu_strip) |
| C1 Полный pytest | FAILED | 12574 passed / **15 failed = 4 pre-existing (по списку) + 11 NEW** — см. findings |
| C2 js | VERIFIED | 68/68 |
| C3 R17 | VERIFIED | 0 секретов (diff + 45 untracked текстовых) |
| C4 routes pin f25e759e | VERIFIED | sha256 совпадает |
| C5 telegram_send allowlist 1 запись | VERIFIED | +7 строк, только SEND_ALLOWLIST |
| S-scope MCA-23 §52 DoD полный | UNVERIFIED | доставлено ядро; Planner-LLM/tool_policy-исполнение/ResponseDocument/media-ветка/ExecutionGraph planned-vs-actual/Analytics Response Pipeline/Golden E2E A–R/call-count/prompt-conflict UI/Help re-sync/production acceptance — НЕ доставлено (фаза 2) |

## Findings (blocking)

F1 (High, NEW): test_ia_shell_round1025::TestNoCompetingHome::test_no_obzor_screen —
строка `label: 'Обзор'` теперь в app.js (sub-tab Аналитики). В HEAD строки нет → NEW.
Санкция владельца: current_task:30978-30988 (вкладка «Обзор» внутри существующего Analytics route).
Фикс: амортизировать инвариант с NOTE-санкцией (запрет конкурирующей ГЛАВНОЙ «Обзор»
сохранить: маршрут '#/': 'status', top-level nav без «Обзор»; sub-tab oversight разрешён).

F2 (High, NEW): test_mca23_response_plan::test_env_zero_disables + test_env_override_clamped —
в изоляции 40/40 PASS, в полном прогоне FAIL (order-dependent): тесты патчат КЛАСС Settings,
а код читает config.settings.settings (инстанс-first; в полном прогоне модульный атрибут
затенён). Фикс: monkeypatch на инстансе `config.settings.settings` (raising=False), не на классе.

F3 (High, NEW): 4 bounds-гарда не амортизированы (в HEAD PASS, сейчас FAIL):
test_summary_deploy_round1026::TestBounds::test_forbidden_paths_unchanged,
test_summary_execution_graph_round1026::TestBoundaries, test_summary_publish_integration_round1026::TestBoundaries,
test_unified_image_request_round1026::TestBoundsA3 — претендуют telegram_send.py/chat_prompts.py/prompt_migrations.py.
Прецедент амортизации уже применён в test_tool_coordinator::TestBounds (NOTE-модель) —
повторить те же NOTE-исключения здесь (MCA-23 §10/§11 + SEND_ALLOWLIST 1 запись).

F4 (High, NEW): Status DOM-инварианты не амортизированы под санкционированный Wave-2 редизайн
(visual-preservation-map REDESIGN-строки): test_webapp_round1014_ui::TestStatusLayoutOrderF7 ×2
(«История доступности ключей» переехала в Модели — тест считает блок потерянным),
test_webapp_f11_round1025::test_dom_order_section12, test_webapp_key_availability_ui::test_no_hardcoded_provider_markers_in_registry.
Фикс: обновить маркеры/порядок под НОВЫЙ санкционированный layout (перенесённые блоки
ассертить в новом доме), НЕ удалять ассерты защиты от потери/дублирования.

## Findings (non-blocking / residual)

N1 (Medium): _SANDWICH_REMINDER («отвечай коротко, по делу…») — последний юзер-блок; для
longform-планов остаётся мягкий конфликт с extent-блоком (§11 класс). Рекомендация фазе 2:
гасить/переформулировать sandwich при plan.is_longform() (1 строка + тест).

N2: MCA-23 §52 остатки (фаза 2, обязателно внутри ОТКРЫТОЙ задачи): Planner до tools
(LLM-план/tool_policy исполнение), ResponseDocument/эквивалент, media-ветка Delivery Router,
ExecutionGraph planned-vs-actual, Analytics Response Pipeline, Golden E2E A–R, call-count
измерение (§45/DoD-48), prompt conflict/migration UI (§49), Help re-sync (§50/DoD-53),
production acceptance (§48). Запрет владельца current_task:29853-29861: закрывать
current_task формулировкой «MCA-23 future/owner later/backlog» НЕЛЬЗЯ.

N3: пустой декоративный glass-surface на скриншотах — артефакт evidence-сервера
(UI_LIQUID_GLASS_LIB=ON); прод-дефолт OFF (не рендерится). Не дефект.

N4: rich-ветка пишет в ledger/дедуп исходный `answer`, а доставляет strip_lore_html(answer);
расхождение только для HTML-акцентов. Приемлемо (plain-фолбэк идентичен 1:1); учесть в фазе 2.

## Pre-existing (не блокируют, по списку Orchestrator)
tool_loop (query_chat_memory_count), nav_disclosure (memory_rag_and_sleep_tabs),
status_control (status_public_for_all_roles), mca09-registry (registry_process_intent_initiative).
betterstack/dream_worker флейки в этом прогоне не выпали.

## Verdict

**Needs Fixes** (F1-F4 — все NEW, все воспроизводимы, фикс — амортизация тестов под
санкционированные контракты + изоляция; продуктового регресса в этих 11 не обнаружено).
Готовность к деплою: НЕ готов до F1-F4 (гейт: полный зелёный прогон на точном кандидате).
После F1-F4: деплой ядра возможен (аддитивно, kill-switch DIRECT_RESPONSE_PLAN_ENABLED /
DIRECT_RICH_DELIVERY_ENABLED, rollback-стек PREV_CHAT_MCA23/PREV_CHAT_VERBALIZER_MCA23);
MCA-23 остаётся in_progress до фазы 2 + live acceptance; закрытие ASAP 6 без §52 — запрещено владельцем.
