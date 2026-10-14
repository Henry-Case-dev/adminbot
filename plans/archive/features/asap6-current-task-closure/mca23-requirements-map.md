# MCA-23 карта现状 (Wave 3 prep, 07.10.2026)

Источник: W3-prep скан. Полный отчёт сохранён в сессии Orchestrator; ниже — рабочие якоря для брифа Wave 3.

## Якоря кода

| Пункт | Локация | Суть для MCA-23 |
|---|---|---|
| Hard cap system | chat_prompts.py:232 (_CHAT_R1021_BASE) + слепки :74-182 | канон «СТРОГО 1-2 предложения» — менять канон + слепки |
| Hard cap verbalizer | chat_prompts.py:291 (правило 5) | unconditional «Коротко» — удалить/заменить extent-логикой |
| Sandwich reminder | direct_chat_service.py:345-347 | вторичный cap-хвост |
| response_mode enum | system2_handoff.py:41; MODE_BLOCKS prompt_style_blocks.py:113-175 | casual/serious/deep_research — гибрид стиль+канал |
| Выбор mode ПОСЛЕ tools | system2_handoff.py:38-47 (Stage-1) | план должен быть ДО execution |
| Verbalizer compose | prompt_style_blocks.py:268-312; вызов direct_chat_service.py:3046-3050 | станет исполнителем ResponsePlan |
| Deep_research → safe-HTML | direct_chat_service.py:2839-2842, _send_direct_answer :3123-3156 | delivery-роутер сейчас 2-веточный (plain/safe-HTML) |
| Decision Maker | direct_llm_react.py (весь) + direct_chat_service.py:1289-1747, :2404-2638 | REPLY/REACT/SILENT в Stage-1 вызове |
| Force-keyword | direct_chat_service.py:851-874, :2042-2051 | force → гарантированный REPLY |
| 🗿 ack | direct_chat_service.py:1673-1711 | единственный hardcode-реакция, оставить |
| CoordinatorDecision | direct_chat_service.py:1050-1135 | носитель ResponsePlan; action до LLM, style после (:2705) — нужна двухфазность |
| Tool loop | tool_loop.py:297-663; TOOL_MAX_ROUNDS=4; caps :50-53 | линейный model-driven; TOOL_PLAN_CREATED :421-425 (постфактум) |
| str-инвариант ToolLoopResult | tool_loop.py:80-116 | downstream опирается на str — не ломать |
| System2 | direct_chat_service.py:2960-3118; гейт :2687-2693 | при невалидном JSON всё отбрасывается (:3030-3034) — нужен механизм частичного сохранения |
| Rich transport | telegram_send.py:190-221 send_rich_message; limits summary_article_formatter.py:257 | переиспользовать для Direct rich |
| Model slots | model_slots.py:84-218 | max_output_tokens для Direct НЕ управляется — нужен механизм длины |
| EvidenceBundle | mca_retrieval_context.py:199-239; сборка direct_chat_service.py:2162-2165 | основа planned-graph |
| Intent | mca_intents.py (IntentService :945); handle_initiative :6346-6542 | 3 разных источника текста (direct/nostalgia/нет) — унифицировать writer |
| ExecutionGraph | execution_graph_source.py:38-96 (9 агентных этапов); DECISION_* :1995-2106 | planned-vs-actual частично; нужен pre-execution plan-объект |
| No-replay | response_freshness.py; direct_chat_service.py:1815-1835, 2752-2808; ledger mca_bot_outputs v22 | MCA-22 инварианты сохранить при новых каналах |
| Casual lowercase | chat_prompts.py:211; MODE_CASUAL prompt_style_blocks.py:113-118 | чисто prompt-driven; НЕ трогать Summary/factcheck каноны |

## PG-ключи для миграции (обязательно)

1. prompts.direct_chat_system_prompt — новая ступень (прецедент prompt_migrations.py:111-119)
2. prompts.direct_chat_verbalizer_system_prompt — ступеней нет вообще → первый PREV-слепок
3. prompts.direct_chat_synthesizer_system_prompt — response_mode-блок
4. prompts.verbilizer_mode_casual — скрытый extent-cap («короткие рубленые»)
5. prompts.verbilizer_mode_serious
6. prompts.verbilizer_mode_deep_research
7. prompts.verbilizer_default_mode (casual)

Риск: mode-блоки ОБЩИЕ для factcheck/summary verbalizer'ов через compose_verbalizer_system — изменение extent-правил заденет другие каналы.

## Топ-5 рисков интеграции

1. PG-канон vs код: cap в прод-значениях PG + миграций для verbalizer-ключей нет → без PG-миграции фикс «только в коде» не изменит прод.
2. Двухфазность: action до LLM, style после Stage-1 → ResponsePlan как новый объект planned→actual.
3. Общие mode-блоки между каналами.
4. ToolLoopResult str-инвариант.
5. Дедуп/freshness/ledger идемпотентность при rich/media каналах.
