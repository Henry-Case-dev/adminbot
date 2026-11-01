# ER-65 / ER-S42 / ER-09 — фактически отправляемые сегменты промптов

> СГЕНЕРИРОВАННЫЙ АРТЕФАКТ. Не редактировать руками.
> Перегенерация: `py -3 tools/er65_prompt_segment_snapshot.py --write`
> Проверка байтовой стабильности: `py -3 tools/er65_prompt_segment_snapshot.py --check`

## Что это

Снимок снят на транспортной границе (`llm.generate(messages, ...)` и `chat_with_tools(llm, payload, tools=...)`) при прогоне реальных швов сборки. Тела промптов не переписаны: система и user-часть собираются самим кодом, инструмент только фиксирует байты, длины, `sha256` и порядок блоков.

* Python 3.12.0 (Windows), токенизатор: `tiktoken`
* Канон: Registry `soul1-w3-1`, заводской набор `de8e77a2a3f4`, нарушения печатей: нет
* Режим: offline: no network (socket blocked), no PG, no Telegram; композер (`unified_composer_enabled`) = False
* Стадий: **17**, сегментов сообщений: **34** (system 17 / user 17), суммарно 121911 символов (211115 байт UTF-8)
* Детерминированность: два независимых процесса, совпадение `True`, ядро снимка `2efbeabfecd68c91…`

## Стадии и сегменты

| Стадия | Роль | Символов | sha256 (12) | Блоков | Неатрибутировано |
| --- | --- | --- | --- | --- | --- |
| `direct.l1_planner` | system | 13965 | `eb496e938c49` | 1 | 0 |
| `direct.l1_planner` | user | 679 | `0ac3f5d353cf` | 5 | 6 |
| `direct.l2_writer.direct` | system | 5189 | `0f778962e071` | 3 | 2 |
| `direct.l2_writer.direct` | user | 1748 | `60557f8f2e84` | 9 | 12 |
| `direct.l1_planner.tools` | system | 13965 | `eb496e938c49` | 1 | 0 |
| `direct.l1_planner.tools` | user | 679 | `0ac3f5d353cf` | 5 | 6 |
| `direct.l2_writer.tool_evidence` | system | 5189 | `0f778962e071` | 3 | 2 |
| `direct.l2_writer.tool_evidence` | user | 2540 | `59538a0510f6` | 10 | 12 |
| `direct.l2_writer.deterministic_fallback_plan` | system | 5192 | `3777cd74c36a` | 3 | 2 |
| `direct.l2_writer.deterministic_fallback_plan` | user | 1537 | `84d25d097f2c` | 9 | 12 |
| `direct.tool_phase.model_driven` | system | 5961 | `fa18451557a4` | 3 | 2 |
| `direct.tool_phase.model_driven` | user | 767 | `1508171490b4` | 7 | 10 |
| `direct.system2.stage1` | system | 1107 | `6bae7eb26bc3` | 1 | 0 |
| `direct.system2.stage1` | user | 329 | `76143220398f` | 2 | 0 |
| `direct.system2.stage2` | system | 5192 | `3777cd74c36a` | 3 | 2 |
| `direct.system2.stage2` | user | 232 | `47ee6857d5c8` | 1 | 0 |
| `direct.single.legacy_no_tools` | system | 5961 | `fa18451557a4` | 3 | 2 |
| `direct.single.legacy_no_tools` | user | 767 | `1508171490b4` | 7 | 10 |
| `direct.l2_writer.layered` | system | 5374 | `4e4ed6b8babf` | 7 | 6 |
| `direct.l2_writer.layered` | user | 1150 | `d6bb293af57a` | 13 | 12 |
| `direct.l2_writer.fallback_model_repack` | system | 5374 | `4e4ed6b8babf` | 7 | 6 |
| `direct.l2_writer.fallback_model_repack` | user | 1150 | `1068de784d23` | 13 | 12 |
| `direct.l2_writer.fallback_model_capacity` | system | 5374 | `4e4ed6b8babf` | 7 | 6 |
| `direct.l2_writer.fallback_model_capacity` | user | 709 | `7ed533ba7ed8` | 6 | 192 |
| `factcheck.single` | system | 5385 | `c616aef501c7` | 3 | 2 |
| `factcheck.single` | user | 222 | `e8275d4a239a` | 5 | 4 |
| `factcheck.stage1_analyst` | system | 2031 | `9573b3d86161` | 1 | 0 |
| `factcheck.stage1_analyst` | user | 222 | `e8275d4a239a` | 3 | 4 |
| `factcheck.stage2_verbalizer` | system | 1601 | `a1512229147a` | 3 | 2 |
| `factcheck.stage2_verbalizer` | user | 303 | `7e6d8d8dbc58` | 1 | 0 |
| `initiative.l1_planner` | system | 13965 | `eb496e938c49` | 1 | 0 |
| `initiative.l1_planner` | user | 1199 | `2e4cca3fabf2` | 5 | 8 |
| `initiative.l2_writer` | system | 5189 | `0f778962e071` | 3 | 2 |
| `initiative.l2_writer` | user | 1664 | `eb2643c7d819` | 4 | 4 |

Полные тексты сегментов и порядок блоков — в `sent-segments.json` (поле `stages[].messages[]`).

## Структура сообщений

Наблюдаемые роли в фактических payload'ах: `system, user`.
Ни одна стадия не отправляет сообщение с ролью `developer` или `tool`: во всём контуре Direct/FactCheck/Initiative — ровно два сообщения, `system` (канал/личность/стиль/канон) и `user` (вопрос + контекст + план + evidence). Результаты инструментов едут ТЕКСТОМ внутри user-части (`<Tool_Evidence>`), а не отдельными `role="tool"`-сообщениями. Схемы инструментов передаются вне `messages` — отдельным аргументом транспорта `tools=[...]` (зафиксировано на стадии `direct.tool_phase.model_driven`).

## Какая стадия когда срабатывает

| Стадия | Название | Точка вызова |
| --- | --- | --- |
| `direct.l1_planner` | L1 Planner (плановый JSON, Direct-ход) | `services/direct_chat_service.py::DirectChatService._plan_direct_l1 (messages@5368)` |
| `direct.l2_writer.direct` | L2 Writer — прямой ответ без инструментов | `services/direct_chat_service.py::DirectChatService._l2_write_answer (messages@6972)` |
| `direct.l1_planner.tools` | L1 Planner — план с capabilities_needed=web_search | `services/direct_chat_service.py::DirectChatService._plan_direct_l1 (messages@5368)` |
| `direct.l2_writer.tool_evidence` | L2 Writer — после инструментальной фазы (Tool_Evidence) | `services/direct_chat_service.py::DirectChatService._l2_write_answer (messages@6972)` |
| `direct.l2_writer.deterministic_fallback_plan` | L2 Writer — деградированный путь: L1 недоступен, план детерминированный (0 LLM-вызовов планера) | `services/direct_chat_service.py::DirectChatService._plan_direct_l1 → direct_l1.fallback_plan → _l2_write_answer` |
| `direct.tool_phase.model_driven` | Tool-фаза (legacy): system+user payload и схемы инструментов | `services/direct_chat_service.py::DirectChatService.handle → build_messages@4044 → chat_with_tools@4322` |
| `direct.system2.stage1` | System2 Stage-1 (машинная справка по выводу инструментов) | `services/direct_chat_service.py::_synthesize_direct_answer (messages@7168)` |
| `direct.system2.stage2` | System2 Stage-2 (вербализатор валидированной справки) | `services/direct_chat_service.py::_synthesize_direct_answer (messages@7255)` |
| `direct.single.legacy_no_tools` | Legacy одиночный вызов без инструментов (тот же payload, что tool-фаза) | `services/direct_chat_service.py::DirectChatService.handle → llm.generate(step='single')@4341` |
| `direct.l2_writer.layered` | L2 Writer со всеми слоями хода (identity/style/lessons/speech/time/evidence) | `services/direct_chat_service.py::DirectChatService._l2_write_answer (messages@6972)` |
| `direct.l2_writer.fallback_model_repack` | L2 Writer — пересборка пакета под окно fallback-модели (пакет помещается целиком) | `services/direct_execution.py::build_l2_fallback_adapter → llm_client payload fallback_payload_adapter` |
| `direct.l2_writer.fallback_model_capacity` | L2 Writer — честный capacity-исход под окно fallback-модели (fallback_window_exceeded) | `services/direct_execution.py::build_l2_fallback_adapter → llm_client payload fallback_payload_adapter` |
| `factcheck.single` | FactCheck — одиночный путь (канон + критика + Core/стиль) | `services/factcheck_service.py::_check_claim_pipeline (messages@1527)` |
| `factcheck.stage1_analyst` | FactCheck Stage-1 — аналитик (JSON по claim + выдача поиска) | `services/factcheck_service.py::_check_claim_two_call (messages@1542)` |
| `factcheck.stage2_verbalizer` | FactCheck Stage-2 — вербализатор валидированной справки | `services/factcheck_service.py::_check_claim_two_call (messages@1595)` |
| `initiative.l1_planner` | Инициатива — решение L1 (reply/react/silent) | `services/direct_chat_service.py::plan_initiative_decision (messages@11807)` |
| `initiative.l2_writer` | Инициатива — тот же L2 Writer (writer='initiative_writer') | `services/direct_chat_service.py::generate_initiative_reply → _l2_write_answer (messages@6972)` |

## Порядок блоков (что реально склеено в каждом сегменте)

### `direct.l1_planner` → system

`prompt:prompts.direct_l1_planner_system_prompt`

### `direct.l1_planner` → user

`section:[СООБЩЕНИЕ]` → `section:[ПОСЛЕДНИЕ СООБЩЕНИЯ]` → `section:[УЧАСТНИКИ]` → `section:[ПАМЯТЬ (срез)]` → `payload:mca07_bundle_slice`

### `direct.l2_writer.direct` → system

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]`

### `direct.l2_writer.direct` → user

`layer:time_line` → `separator` → `tag:Response_Plan` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question` → `canon:no_meta_closing`

### `direct.l1_planner.tools` → system

`prompt:prompts.direct_l1_planner_system_prompt`

### `direct.l1_planner.tools` → user

`section:[СООБЩЕНИЕ]` → `section:[ПОСЛЕДНИЕ СООБЩЕНИЯ]` → `section:[УЧАСТНИКИ]` → `section:[ПАМЯТЬ (срез)]` → `payload:mca07_bundle_slice`

### `direct.l2_writer.tool_evidence` → system

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]`

### `direct.l2_writer.tool_evidence` → user

`layer:time_line` → `separator` → `tag:Response_Plan` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question` → `payload:tool_evidence_block` → `canon:no_meta_closing`

### `direct.l2_writer.deterministic_fallback_plan` → system

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]`

### `direct.l2_writer.deterministic_fallback_plan` → user

`layer:time_line` → `separator` → `tag:Response_Plan` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question` → `canon:no_meta_closing`

### `direct.tool_phase.model_driven` → system

`prompt:prompts.direct_chat_system_prompt` → `separator` → `mode_or_extent_block[0]`

### `direct.tool_phase.model_driven` → user

`layer:time_line` → `separator` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question`

### `direct.system2.stage1` → system

`prompt:prompts.direct_chat_synthesizer_system_prompt`

### `direct.system2.stage1` → user

`payload:mca07_bundle_slice` → `payload:synthesis_input`

### `direct.system2.stage2` → system

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]`

### `direct.system2.stage2` → user

`payload:stage2_reference_json`

### `direct.single.legacy_no_tools` → system

`prompt:prompts.direct_chat_system_prompt` → `separator` → `extent_block[0]`

### `direct.single.legacy_no_tools` → user

`layer:time_line` → `separator` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question`

### `direct.l2_writer.layered` → system

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]` → `separator` → `layer:character_block` → `separator` → `layer:style_requests`

### `direct.l2_writer.layered` → user

`layer:time_line` → `separator` → `layer:plan_block` → `separator` → `layer:speech_understanding` → `separator` → `layer:verified_lessons` → `separator` → `layer:user_block_global_context` → `separator` → `layer:tool_evidence_block` → `separator` → `canon:no_meta_closing`

### `direct.l2_writer.fallback_model_repack` → system

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]` → `separator` → `layer:character_block` → `separator` → `layer:style_requests`

### `direct.l2_writer.fallback_model_repack` → user

`layer:time_line` → `separator` → `layer:plan_block` → `separator` → `layer:speech_understanding` → `separator` → `layer:verified_lessons` → `separator` → `layer:user_block_global_context` → `separator` → `canon:no_meta_closing` → `separator` → `layer:tool_evidence_block`

### `direct.l2_writer.fallback_model_capacity` → system

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]` → `separator` → `layer:character_block` → `separator` → `layer:style_requests`

### `direct.l2_writer.fallback_model_capacity` → user

`layer:time_line` → `separator` → `payload:l2_fallback_truncation_marker` → `payload:tool_evidence_block` → `payload:l2_capacity_note`

### `factcheck.single` → system

`prompt:prompts.factcheck_system_prompt` → `separator` → `block:factcheck_critique_section(self_assessed)`

### `factcheck.single` → user

`layer:claim` → `separator` → `layer:user_hint` → `separator` → `layer:search_results`

### `factcheck.stage1_analyst` → system

`prompt:prompts.factcheck_analyst_system_prompt`

### `factcheck.stage1_analyst` → user

`tag:claim` → `tag:user_hint` → `tag:search_results`

### `factcheck.stage2_verbalizer` → system

`prompt:prompts.factcheck_verbalizer_system_prompt` → `separator` → `prompt:prompts.verbilizer_mode_serious`

### `factcheck.stage2_verbalizer` → user

`payload:factcheck_analysis_json`

### `initiative.l1_planner` → system

`prompt:prompts.direct_l1_planner_system_prompt`

### `initiative.l1_planner` → user

`section:[СООБЩЕНИЕ]` → `section:[ПОСЛЕДНИЕ СООБЩЕНИЯ]` → `section:[УЧАСТНИКИ]` → `section:[ДОСТУПНЫЕ ВОЗМОЖНОСТИ]` → `section:[УСЛОВИЯ]`

### `initiative.l2_writer` → system

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]`

### `initiative.l2_writer` → user

`tag:Response_Plan` → `tag:Initiative_Context` → `tag:Fresh_Chat_Window` → `canon:no_meta_closing`

## Эффективные ревизии и печати канона

`act:` — действующая редакция текста, `fac:` — заводская редакция по печати реестра, `found_at` — позиция в байтах сегмента. Порядок `found_at` обязан возрастать: перестановка блоков в сборке это ломает.

| Стадия | Ключ | block_id | act | fac | source | found_at |
| --- | --- | --- | --- | --- | --- | --- |
| `direct.l1_planner` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.l1_planner` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:eb496e938c49` | `fac:eb496e938c49(l1-planner-external-claims-recheck)` | code_default | 0 |
| `direct.l1_planner` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | -1 |
| `direct.l2_writer.direct` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.l2_writer.direct` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:eb496e938c49` | `fac:eb496e938c49(l1-planner-external-claims-recheck)` | code_default | -1 |
| `direct.l2_writer.direct` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |
| `direct.l1_planner.tools` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.l1_planner.tools` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:eb496e938c49` | `fac:eb496e938c49(l1-planner-external-claims-recheck)` | code_default | 0 |
| `direct.l1_planner.tools` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | -1 |
| `direct.l2_writer.tool_evidence` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.l2_writer.tool_evidence` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:eb496e938c49` | `fac:eb496e938c49(l1-planner-external-claims-recheck)` | code_default | -1 |
| `direct.l2_writer.tool_evidence` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |
| `direct.l2_writer.deterministic_fallback_plan` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.l2_writer.deterministic_fallback_plan` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:eb496e938c49` | `fac:eb496e938c49(l1-planner-external-claims-recheck)` | code_default | -1 |
| `direct.l2_writer.deterministic_fallback_plan` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |
| `direct.tool_phase.model_driven` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | 0 |
| `direct.tool_phase.model_driven` | `prompts.direct_chat_synthesizer_system_prompt` | `direct.base.synthesizer` | `act:6bae7eb26bc3` | `fac:6bae7eb26bc3(synthesizer-r1023)` | code_default | -1 |
| `direct.tool_phase.model_driven` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | -1 |
| `direct.system2.stage1` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.system2.stage1` | `prompts.direct_chat_synthesizer_system_prompt` | `direct.base.synthesizer` | `act:6bae7eb26bc3` | `fac:6bae7eb26bc3(synthesizer-r1023)` | code_default | 0 |
| `direct.system2.stage1` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | -1 |
| `direct.system2.stage2` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.system2.stage2` | `prompts.direct_chat_synthesizer_system_prompt` | `direct.base.synthesizer` | `act:6bae7eb26bc3` | `fac:6bae7eb26bc3(synthesizer-r1023)` | code_default | -1 |
| `direct.system2.stage2` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |
| `direct.single.legacy_no_tools` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | 0 |
| `direct.l2_writer.layered` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |
| `direct.l2_writer.fallback_model_repack` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |
| `direct.l2_writer.fallback_model_capacity` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |
| `factcheck.single` | `prompts.factcheck_system_prompt` | `factcheck.base.single` | `act:aa6a2ed38b4c` | `fac:aa6a2ed38b4c(factcheck-r1022)` | code_default | 0 |
| `factcheck.single` | `prompts.factcheck_critique_directive` | `factcheck.critique.directive` | `act:cfcd9009df17` | `fac:cfcd9009df17(factcheck-critique-w5)` | code_default | 4470 |
| `factcheck.stage1_analyst` | `prompts.factcheck_system_prompt` | `factcheck.base.single` | `act:aa6a2ed38b4c` | `fac:aa6a2ed38b4c(factcheck-r1022)` | code_default | -1 |
| `factcheck.stage1_analyst` | `prompts.factcheck_analyst_system_prompt` | `factcheck.base.analyst` | `act:9573b3d86161` | `fac:9573b3d86161(factcheck-analyst-r1023-f3)` | code_default | 0 |
| `factcheck.stage1_analyst` | `prompts.factcheck_verbalizer_system_prompt` | `factcheck.base.verbalizer` | `act:42442333d77d` | `fac:42442333d77d(factcheck-verbalizer-w1)` | code_default | -1 |
| `factcheck.stage1_analyst` | `prompts.verbilizer_mode_serious` | `verbilizer.mode.serious` | `act:0ffb292caf70` | `fac:0ffb292caf70(mode-r1023)` | code_default | -1 |
| `factcheck.stage2_verbalizer` | `prompts.factcheck_system_prompt` | `factcheck.base.single` | `act:aa6a2ed38b4c` | `fac:aa6a2ed38b4c(factcheck-r1022)` | code_default | -1 |
| `factcheck.stage2_verbalizer` | `prompts.factcheck_analyst_system_prompt` | `factcheck.base.analyst` | `act:9573b3d86161` | `fac:9573b3d86161(factcheck-analyst-r1023-f3)` | code_default | -1 |
| `factcheck.stage2_verbalizer` | `prompts.factcheck_verbalizer_system_prompt` | `factcheck.base.verbalizer` | `act:42442333d77d` | `fac:42442333d77d(factcheck-verbalizer-w1)` | code_default | 0 |
| `factcheck.stage2_verbalizer` | `prompts.verbilizer_mode_serious` | `verbilizer.mode.serious` | `act:0ffb292caf70` | `fac:0ffb292caf70(mode-r1023)` | code_default | 1445 |
| `initiative.l1_planner` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:eb496e938c49` | `fac:eb496e938c49(l1-planner-external-claims-recheck)` | code_default | 0 |
| `initiative.l1_planner` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | -1 |
| `initiative.l2_writer` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:eb496e938c49` | `fac:eb496e938c49(l1-planner-external-claims-recheck)` | code_default | -1 |
| `initiative.l2_writer` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |

## Что доказано

1. Для каждой стадии существует ровно тот payload, который уходит в транспорт; структура `system@0` + `user` (у tool-фазы — плюс схемы инструментов) подтверждена фактическими `messages`.
2. Длины и `sha256` каждого сегмента воспроизводятся байт-в-байт в двух независимых процессах.
3. Каждый блок, пришедший через именованный шов (`prompt_style_blocks.resolve_prompt`, `prompt_registry.resolve_chat_speech`), найден в финальном тексте сегмента и в порядке вызова — то есть канон не потерян и не переставлен относительно порядка сборки.
4. Слои хода (личность, style-просьбы, verified-lessons, speech, time-line, plan, tool-evidence) присутствуют в тот момент и в том порядке, в каком их собирает код (`direct.l2_writer.layered`).
5. Деградированный путь: при отказе L1 модель-планер вообще не получает успешного вызова, а Writer получает детерминированный план (`direct.l2_writer.deterministic_fallback_plan`); при переключении на fallback-модель пакет пересобирается её же адаптером — сняты оба исхода, `fallback_repacked` и `fallback_window_exceeded`.

## Что НЕ доказано (нужен живой вызов модели)

* Что провайдер принял payload (HTTP 200), фактический `usage`, соблюдение моделью инструкций и качество ответа.
* Что боевой чат действительно получает тот же текст: в боте действуют персистентные переопределения владельца (`hot`/`chat_params`) и PG-личность; здесь снят заводской канон, `source="default"`.
* Что payload не изменился между этим снимком и моментом деплоя: снимок привязан к конкретным `sha256` файлов сборки (поле `sources`).

## Наблюдения по порядку блоков

* `direct.l2_writer.fallback_model_repack`: блок `layer:tool_evidence_block` (объявлен №9) стоит в байтах ПОСЛЕ блока №10. Это наблюдаемое поведение существующего кода, а не решение снимка: в пересборке под окно fallback-модели `<Tool_Evidence>` доезжает после закрывающего требования Writer'а. Тест фиксирует это явно, чтобы изменение порядка не проходило незаметно.

## Происхождение снимка (какой код собирал payload)

| Файл | Строк | sha256 |
| --- | --- | --- |
| `services/chat_prompts.py` | 1583 | `4942cdb1da53961d…` |
| `services/direct_chat_service.py` | 13228 | `ebbd6d8a893b8068…` |
| `services/direct_execution.py` | 1368 | `90a16202ea960d4e…` |
| `services/direct_l1.py` | 1616 | `351c5f3549de8d3c…` |
| `services/factcheck_prompts.py` | 555 | `33db123961f7e024…` |
| `services/factcheck_service.py` | 2414 | `e4dbe97d5c2a12e3…` |
| `services/negative_constraints.py` | 933 | `e1ca1844e2edfdbe…` |
| `services/payload_builder.py` | 36 | `30645fbba34850c4…` |
| `services/prompt_composer.py` | 2392 | `15f5705cc91ede08…` |
| `services/prompt_registry.py` | 3697 | `5da4422e9826e7d5…` |
| `services/prompt_style_blocks.py` | 920 | `ebc5be8c44c39b8e…` |
| `services/response_extent.py` | 768 | `851befe528339388…` |

## Откуда берётся неатрибутированный остаток

Блоки, которые рендерятся внутри функций без именованного шва (например режимный/extent-блок внутри `compose_verbalizer_system` или конкатенация канонических абзацев в `build_l1_context`), остаются `unattributed` со своим `offset`/`sha256`. Это не потеря: весь текст сегмента целиком покрыт `sha256`, но не атрибутирован по имени шва.

