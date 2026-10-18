# ADTR-TOOLS — bounded-аудит tool-inventory (документально, 19.10.2026)

Слайс ADTR-TOOLS (`plans/features/add-tr/requirements-map.json`),
задача §ADD-TR.3 п.5: «аудит всего доступного tool inventory на логические
несоответствия между schemas, доступными сервисами, гейтами и семантической
маршрутизацией; исправлять доказанные дефекты в существующих компонентах,
без неограниченного расширения scope».

Правки этого лайна — только доказанный дефект `get_bot_health`
(capability+деривация+реестр). Остальные строки — **наблюдения**, не правки.

Колонки: tool (schema `TOOL_CALLING_TOOLS`) → L1-capability
(`direct_capabilities.CAPABILITY_TOOLS`) → дет. деривация (`simple_tools`,
`direct_execution.derive_simple_steps`) → исполнитель/гейты → прод-статус
(recon 19.10, `evidence/recon/prod_recon-tr-2026-10-19.txt`) → расхождение.

| tool | L1-capability | дет. деривация (simple) | гейты/исполнитель | прод (recon) | расхождение / примечание |
|---|---|---|---|---|---|
| `query_chat_memory` | `chat_memory` | `_QUERY_CAPS` (query) | — | — | нет |
| `dig_into_lore` | `historical_search` | `_QUERY_CAPS` (query) | lore-флаг (аргумент `active_tools`) | 1× `denied tool_step_limit` | нет (лимит — честный отказ) |
| `compile_lore_story` | `historical_search` | `_QUERY_CAPS` (topic) | `flags.lore_compiler_enabled` | — | нет |
| `execute_web_search` | `web_search` | `_QUERY_CAPS` | — | — | нет |
| `fetch_article` | `fetch_url` | отдельная ветка (url из query/reply/`resolved_url`; нет ссылки → честная limitation) | `ARTICLE_TOOL_ENABLED` | — | нет |
| `summarize_video` | `video_summary` | `{}` (router берёт ctx) | COBALT (реестр) | 2× error | pre-existing (не ADD-TR); деривация без видео-цели отвечает ошибкой честно |
| `download_media` | `media_download` | `{}` | yield 0f/4e при `flags.download_enabled` | 1× error | pre-existing (не ADD-TR) |
| `transcribe_video` | `transcription` | `{}` | `MEDIA_TRANSCRIBE_TOOL_ENABLED` | — | нет |
| `get_recent_history` | `chat_history` | `_QUERY_CAPS` | — | 1× timeout | pre-existing (не ADD-TR) |
| `get_user_context` | `user_memory` | person/purpose | `MEMORY_LOOKUP_ENABLED` | — | нет |
| `recognize_image` | `image_understanding` | target = `ctx.reply_to_message_id` = **текущее** сообщение (`direct_chat_service.py:2991-2992`) | `MCA_VISION_TOOL_ENABLED` + vision-гейт | 14 вызовов / 0 данных (`vision_unavailable`) | **(A)** photo+caption — цель верна; **(B)** текстовый reply→фото дет. шаг целится в текущее (текстовое) сообщение → `resolve_target_assets` → `missing` (LLM-путь передаёт явный target из медиа-маркеров). Владелец — VISION-FIX-CORE / ADTR-VERIFY (S2); здесь только фиксация |
| `fact_check` | `fact_check` | claim=query[:300] + reply target | 3 гейта (env+каталог+master) | 3× `TOOL_CALL_COMPLETE ok` | нет |
| `generate_image` | `image_generation` | **запрещена по конструкции** («side-effect — не исполнено») | `flags.image_generation_module_enabled` | tool-вызовов 0; Fast-Track живой | не дефект: `simple_tools` не запускает side-effect (ADR-1023/§18C.7), выбирается adaptive/пре-гейт/§5.10-дверь. «0 вызовов моделью» — следствие маршрута, а не поломки. Live-матрица S6 — postdeploy |
| `get_bot_health` | **`health` — добавлено этим лайном** (`direct_capabilities.py:46`) | **`health_N {}` — добавлено** (`direct_execution.py:295-306`) | `flags.checkup_enabled` (тот же, что 0g) + DI-проверка (`tool_router.py:2673-2697`) | **0 вызовов** за историю (GAP до фикса) | фикс: capability в resolved-наборе + честный реестр (`checkup_module_disabled`) + дет. шаг. Живые вызовы — postdeploy |

Капability-слой (не тулы):

| capability | тул | расхождение |
|---|---|---|
| `statistics` | — (по конструкции) | нет: L1 `no_tool`, реестр `unsupported` — честно |
| все 14 имён из `CAPABILITY_TOOLS` | есть | после фикса: реестр знает КАЖДОЕ имя (тест `test_every_l1_capability_is_known_to_registry`, теперь с `health`) |

Кросс-срезовые наблюдения (без правок в этом лайне):

1. **UI-витрина «Возможности бота»** (`capability_registry._DEFAULT_VIEW_IDS`)
   не содержит `health`: карточка чекапа в витрине не появится. Требование
   ADD-TR.3 п.4 — про исполнение инструмента, не про витрину; UI-решение
   оставить владельцу/следующему срезу (не расширяем scope).
2. **`METERED_TOOLS`** не содержит `get_bot_health` (ADR-1026-15 D3:
   «free/local»), при этом `_get_bot_health` выполняет LLM-чекап внутри.
   Действующая конструкция: «кулдаун не применяем, ограничение — лимиты
   tool-loop» (`tool_router.py:2673-2677`); после этого лайна свободная
   форма доходит до инструмента чаще, чем раньше. Ограничение стоимости —
   per-turn лимиты цепочки + dedup (≤2 одинаковых вызова на ход); дневного
   кулдауна у tool-пути нет по конструкции 0g/tool. Пометить Reviewer'у.
3. **Ошибки прод-инструментов** `download_media`/`summarize_video`/
   `get_recent_history` — pre-existing наблюдения recon §3, не ADD-TR
   (вне scope этого лайна).
4. **ADD-TR.4** (адаптер `analyze_image_bytes` для исходящей генерации) —
   отдельный слайс ADTR-POSTGEN, не здесь.
