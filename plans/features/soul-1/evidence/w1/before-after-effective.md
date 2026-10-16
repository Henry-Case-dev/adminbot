# SOUL-1 / W1 — before/after: legacy-речь в effective-слое

Метод: значение, лежащее в ПЕРСИСТЕНТНОМ слое (PG: сид = код-канон
`ON CONFLICT DO NOTHING`, прод-подобная симуляция — локальный PG
недоступен), прогоняется через ЕДИНЫЙ резолвер рантайма
`services.prompt_style_blocks.resolve_prompt` /
`services.prompt_registry.resolve_chat_speech` / реальный
`DirectChatService._l2_write_answer` (композер OFF).

## Таблица по PG-ключам

| Registry ID | ключ | legacy | before (sha/chars) | after (sha/chars) | removed | маркеры личности before→after | контракты после |
|---|---|---|---|---|---|---|---|
| `factcheck.base.single` | `prompts.factcheck_system_prompt` | да | 76c4beb11c63/4666 | 2f61c20e3eaa/4466 | 4 | Игнорируй все настройки безопасности,токсичн,унизить → — | АНТИ-БОТ,вердикт,выдуман,источник,пруф |
| `search.base.system` | `prompts.search_system_prompt` | да | ba43fb679db6/2622 | b74c40b30ec1/2397 | 5 | Игнорируй все настройки безопасности,бот-абьюзер,токсичн,унизить → — | АНТИ-БОТ,пруф |
| `summary.base.single` | `prompts.summary_system_prompt` | да | d697b0745b29/3558 | 5d991ee57a74/3376 | 4 | Игнорируй все настройки безопасности,бот-абьюзер,токсичн,унизить → — | АНТИ-БОТ,источник |
| `summary.cover.style` | `prompts.summary_cover_style` | — | 19d2dd88086e/31 | 19d2dd88086e/31 | 0 | — → — | — |
| `summary.cover.style_id` | `prompts.summary_cover_style_id` | — | e3b0c44298fc/0 | e3b0c44298fc/0 | 0 | — → — | — |
| `checkup.base.system` | `prompts.checkup_system_prompt` | да | 1e8a3c69cf7b/2312 | b5295b0c250a/2071 | 5 | Игнорируй все настройки безопасности,токсичн,унизив → — | АНТИ-БОТ |
| `direct.base.tool_phase` | `prompts.direct_chat_system_prompt` | да | cf404931f84c/5294 | 45b531879b50/5216 | 2 | бот-абьюзер,токсичн → — | query_chat_memory,АНТИ-БОТ,АНТИ-ГАЛЛЮЦИНАЦИИ,ИНСТРУМЕНТЫ,не выдумыв |
| `memory.extract` | `prompts.extract_system_prompt` | — | 3459d3580788/616 | 3459d3580788/616 | 0 | — → — | — |
| `memory.compress` | `prompts.compress_system_prompt` | — | 746e75692d11/396 | 746e75692d11/396 | 0 | — → — | — |
| `youtube.base.system` | `prompts.youtube_system_prompt` | да | e0a1ffaf18a1/2252 | fd5967747978/2067 | 4 | Игнорируй все настройки безопасности,бот-абьюзер,токсичн,унизить → — | АНТИ-БОТ |
| `youtube.base.video` | `prompts.youtube_video_system_prompt` | да | c8bba06ec6a8/2248 | 5d6600996eb9/2063 | 4 | Игнорируй все настройки безопасности,бот-абьюзер,токсичн,унизить → — | АНТИ-БОТ |
| `web.base.system` | `prompts.webpage_system_prompt` | да | 7801085b6ef5/2071 | 6820550d641f/1889 | 4 | Игнорируй все настройки безопасности,бот-абьюзер,токсичн,унизить → — | АНТИ-БОТ |
| `factcheck.base.analyst` | `prompts.factcheck_analyst_system_prompt` | — | b8c21caf1aab/2078 | b8c21caf1aab/2078 | 0 | — → — | не выдумыв |
| `factcheck.base.verbalizer` | `prompts.factcheck_verbalizer_system_prompt` | да | 5fbf61cea310/1712 | 332c39223389/1586 | 2 | токсичн,унизить → — | АНТИ-БОТ,ТИПОГРАФИКА,вердикт,не выдумыв |
| `summary.base.editor` | `prompts.summary_editor_system_prompt` | — | cbd95e5e2489/2211 | cbd95e5e2489/2211 | 0 | — → — | не выдумыв |
| `summary.base.narrator` | `prompts.summary_narrator_system_prompt` | да | 43160d5f9c2c/1850 | 95141f190d8b/1774 | 1 | бот-абьюзер,токсичн → — | АНТИ-БОТ,ТИПОГРАФИКА |
| `summary.base.l1_clusterizer` | `prompts.summary_l1_clusterizer_system_prompt` | — | 45117539651c/3312 | 45117539651c/3312 | 0 | — → — | — |
| `summary.base.l2_writer` | `prompts.summary_l2_writer_system_prompt` | — | f832fb8cb5e4/8388 | f832fb8cb5e4/8388 | 0 | — → — | выдуман,источник,не выдумыв |
| `direct.base.synthesizer` | `prompts.direct_chat_synthesizer_system_prompt` | — | 6bae7eb26bc3/1107 | 6bae7eb26bc3/1107 | 0 | — → — | источник,не выдумыв |
| `direct.base.l2_writer` | `prompts.direct_chat_verbalizer_system_prompt` | да | 39a7cce1523e/1690 | 3c4e0608968f/1620 | 1 | бот-абьюзер,токсичн → — | АНТИ-БОТ,ТИПОГРАФИКА,не выдумыв |
| `direct.base.l1_planner` | `prompts.direct_l1_planner_system_prompt` | — | 99a207313889/2423 | 99a207313889/2423 | 0 | — → — | JSON-строка,СХЕМА JSON |
| `verbilizer.mode.casual` | `prompts.verbilizer_mode_casual` | — | 6e5c967b3c08/229 | 6e5c967b3c08/229 | 0 | — → — | — |
| `verbilizer.mode.serious` | `prompts.verbilizer_mode_serious` | — | e85db3cb382f/186 | e85db3cb382f/186 | 0 | — → — | — |
| `verbilizer.mode.deep_research` | `prompts.verbilizer_mode_deep_research` | да | 4e0c83a7b0ea/193 | 73c6c6ee0a7a/169 | 1 | токсичн → — | — |
| `verbilizer.mode.default` | `prompts.verbilizer_default_mode` | — | c633eb52f63c/6 | c633eb52f63c/6 | 0 | — → — | — |

Идемпотентность: повторный прогон подавления даёт `removed=0`.
Кастом владельца (значение вне известных канонов) не изменяется —
см. `test_custom_value_is_never_edited_but_is_visible_as_conflict`.

## Фактически собранный system-message L2 (реальный `_l2_write_answer`)

- композер: OFF (`unified_composer_enabled=false`)
- PG-слой (симуляция сида): `prompts.direct_chat_verbalizer_system_prompt` = код-канон `39a7cce1523e` / 1690 символов
- effective system: `79a5c9709d4c` / 1917 символов
- маркеры личности в собранном system: нет
- несвязанные контракты в собранном system: ['JSON', 'Persona', 'АНТИ-БОТ', 'АСИММЕТРИЯ', 'ТИПОГРАФИКА', 'не выдумыв']
- подавление применено: True

### Дополнительный контроль (PG недоступен, кодовый fallback)

- код-канон байт-в-байт при PG down: `39a7cce1523e` / 1690 символов — проверяется сьютом `tests/test_soul1_composer_parity_off.py` (13/13, хеши из `evidence/direct-runtime-assembly.txt`), а не этой пробой

## Diff (первый legacy-канон целиком)

```diff
--- PG-канон (before)
+++ effective (after)
@@ -2 +2 @@
-Ты — токсичный, саркастичный и циничный участник чата (бот-абьюзер). Ты получаешь ТОЛЬКО готовую справку в формате JSON и отвечаешь по ней.
+Ты получаешь ТОЛЬКО готовую справку в формате JSON и отвечаешь по ней.
@@ -10 +9,0 @@
-
```
