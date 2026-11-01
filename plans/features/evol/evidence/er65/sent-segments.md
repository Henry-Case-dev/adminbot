# ER-65 / ER-S42 / ER-09 — фактически отправляемые сегменты промптов

> СГЕНЕРИРОВАННЫЙ АРТЕФАКТ. Не редактировать руками.
> Перегенерация: `py -3 tools/er65_prompt_segment_snapshot.py --write`
> Проверка байтовой стабильности: `py -3 tools/er65_prompt_segment_snapshot.py --check`

## Что это

Снимок снят на транспортной границе (`llm.generate(messages, ...)` и `llm.generate_chat(messages, tools=...)`) при прогоне реальных швов сборки. Тела промптов не переписаны: system и user-часть собирает сам код, инструмент только фиксирует байты, длины, `sha256`, порядок блоков и манифест композера.

**Основной режим — боевой:** `mode=prod_on`, композер ON, все оси включены (Core / identity / Expression / lessons / speech / response_plan в system). Заводской OFF-контур (`mode=factory_off`) снят отдельно и помечен как вторичный: он боевым режимом не является.

* Python 3.12.0 (Windows), токенизатор: `tiktoken`
* Канон: Registry `soul1-w3-1`, заводской набор `f84baaf69559`, нарушения печатей: нет
* Сеть: blocked (socket.connect/connect_ex бросают); PG: PG-стенд (ConfigLayer): присутствует слой с флагами гейтов; документы владельца character.core/expression/persona отсутствуют намеренно (PG недоступен)
* Стадий: **27** (боевых 18 + вторичных OFF 9), сегментов сообщений: **58** (system 27 / user 27 / assistant 2 / tool 2)
* Детерминированность: два независимых процесса, совпадение `True`, ядро снимка `1586144bcec0b40b…`

## Боевая карта гейтов

| Ось | Значение в снимке |
| --- | --- |
| `character_core_enabled` | True |
| `character_layers_enabled` | True |
| `expression_examples_enabled` | True |
| `humor_craft_enabled` | True |
| `humor_feedback_enabled` | True |
| `humor_library_enabled` | True |
| `persona_enabled` | True |
| `response_plan_enabled` | True |
| `smart_verbalizer_modes_enabled` | True |
| `speech_style_policy_enabled` | True |
| `unified_composer_enabled` | True |

env-оси выставлены: `UNIFIED_COMPOSER_ENABLED=1`, `CHARACTER_CORE_ENABLED=1`, `SPEECH_STYLE_POLICY_ENABLED=1`, `HUMOR_LIBRARY_ENABLED=1`, `HUMOR_FEEDBACK_ENABLED=1`, `HUMOR_CRAFT_ENABLED=1`

Источники значений (проверяемые артефакты репозитория):

* plans/features/soul-1/release-2.58.86-report.md — `.env`: UNIFIED_COMPOSER_ENABLED=1, HUMOR_CRAFT_ENABLED=1, HUMOR_LIBRARY_ENABLED=1, HUMOR_FEEDBACK_ENABLED=1; PG (jsonb bool): flags.unified_composer_enabled, flags.humor_craft_enabled, flags.humor_library_enabled, flags.humor_feedback_enabled = true; `/api/speech/overview`: «gates: все 10 ON» (unified_composer_enabled, character_core_enabled, speech_style_policy_enabled, humor_library_enabled, humor_feedback_enabled, persona_enabled, character_layers_enabled, experience_lessons_enabled, smart_verbalizer_modes_enabled, response_plan_enabled)
* plans/features/asap-speech-arch/evidence/p0-hotfix/probes_final2/raw_new_code_A.json — `gates` харнесса (читает `prompt_composer.gates_from_config()` на проде, pg_read_only=on): unified_composer_enabled/character_core_enabled/persona_enabled/character_layers_enabled/smart_verbalizer_modes_enabled/expression_examples_enabled/humor_library_enabled/humor_craft_enabled = true
* plans/features/add-exp/evidence/f0/README.md — live `resolve_gates(chat)` → все оси ON, `composer_enabled_now=true`; `character.core` и `character.expression` есть в PG (документы владельца)
* plans/features/release-then-migrate/evidence/inventory-old-vps.md — в прод `.env` присутствует ключ UNIFIED_COMPOSER_ENABLED

## Ограничения снимка (что именно не боевые байты)

* PG недоступен: документы владельца `character.core` (в проде revision 5, owner_edit), `character.expression` (sharp/profanity allowed) и `character.persona` не читаются. Действуют ЗАВОДСКИЕ редакции Core (`source=default`, `origin=factory`, ревизия `fac:…`) и заводские Expression-настройки; личность передаётся объявленным `character_block`. Структура слоёв и их порядок — боевые, тексты этих трёх документов — заводские, а не владельческие.
* `style_policy`-слой в снимке присутствует с честной причиной `style_policy_absent`: действующие правила стиля живут в PG-документе владельца, которого офлайн нет.
* Снят один chat_id и один ход; per-chat override другого чата может менять текст и набор блоков.
* Сеть заблокирована на время прогона (socket.connect бросает), поэтому приём payload провайдером и usage не проверяются.

## Стадии и сегменты

| Стадия | Режим | Путь | Роль | Символов | sha256 (12) | Блоков | Неатрибутировано |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `direct.l1_planner` | prod_on | l1 | system | 15453 | `09f3d533d173` | 1 | 0 |
| `direct.l1_planner` | prod_on | l1 | user | 679 | `0ac3f5d353cf` | 5 | 0 |
| `direct.l2_writer.direct` | prod_on | l1 | system | 7718 | `9d767f32a789` | 9 | 8 |
| `direct.l2_writer.direct` | prod_on | l1 | user | 1748 | `60557f8f2e84` | 9 | 2 |
| `direct.l1_planner.tools` | prod_on | l1 | system | 15453 | `09f3d533d173` | 1 | 0 |
| `direct.l1_planner.tools` | prod_on | l1 | user | 679 | `0ac3f5d353cf` | 5 | 0 |
| `direct.l2_writer.tool_evidence` | prod_on | l1 | system | 7718 | `9d767f32a789` | 9 | 8 |
| `direct.l2_writer.tool_evidence` | prod_on | l1 | user | 2567 | `79fb867d4a2b` | 10 | 2 |
| `direct.l2_writer.deterministic_fallback_plan` | prod_on | l1 | system | 7721 | `f54eac49d24c` | 9 | 8 |
| `direct.l2_writer.deterministic_fallback_plan` | prod_on | l1 | user | 1537 | `84d25d097f2c` | 9 | 2 |
| `direct.tool_phase.model_driven` | prod_on | legacy_l1_off | system | 8490 | `a77bf0e36ce8` | 9 | 8 |
| `direct.tool_phase.model_driven` | prod_on | legacy_l1_off | user | 767 | `1508171490b4` | 7 | 2 |
| `direct.tool_phase.tool_round` | prod_on | legacy_l1_off | system | 8490 | `a77bf0e36ce8` | 9 | 8 |
| `direct.tool_phase.tool_round` | prod_on | legacy_l1_off | user | 767 | `1508171490b4` | 7 | 2 |
| `direct.tool_phase.tool_round` | prod_on | legacy_l1_off | assistant | 0 | `e3b0c44298fc` | 0 | 0 |
| `direct.tool_phase.tool_round` | prod_on | legacy_l1_off | tool | 57 | `580242f6cf5f` | 1 | 0 |
| `direct.system2.stage1` | prod_on | legacy_l1_off | system | 1107 | `6bae7eb26bc3` | 1 | 0 |
| `direct.system2.stage1` | prod_on | legacy_l1_off | user | 349 | `52793b5f312a` | 2 | 0 |
| `direct.system2.stage2` | prod_on | legacy_l1_off | system | 7721 | `f54eac49d24c` | 9 | 8 |
| `direct.system2.stage2` | prod_on | legacy_l1_off | user | 232 | `47ee6857d5c8` | 1 | 0 |
| `direct.single.legacy_no_tools` | prod_on | legacy_l1_off | system | 8490 | `a77bf0e36ce8` | 9 | 8 |
| `direct.single.legacy_no_tools` | prod_on | legacy_l1_off | user | 767 | `1508171490b4` | 7 | 2 |
| `direct.l2_writer.layered` | prod_on | l1 | system | 8037 | `c79a1ddacf75` | 17 | 16 |
| `direct.l2_writer.layered` | prod_on | l1 | user | 1016 | `cb8fbdf58cd4` | 9 | 8 |
| `direct.l2_writer.fallback_model_repack` | prod_on | l1 | system | 8037 | `c79a1ddacf75` | 17 | 16 |
| `direct.l2_writer.fallback_model_repack` | prod_on | l1 | user | 1016 | `bd815c5825c7` | 9 | 8 |
| `direct.l2_writer.fallback_model_capacity` | prod_on | l1 | system | 8037 | `c79a1ddacf75` | 17 | 16 |
| `direct.l2_writer.fallback_model_capacity` | prod_on | l1 | user | 709 | `7ed533ba7ed8` | 6 | 192 |
| `factcheck.single` | prod_on | factcheck | system | 6226 | `07013281498c` | 3 | 2 |
| `factcheck.single` | prod_on | factcheck | user | 222 | `e8275d4a239a` | 5 | 4 |
| `factcheck.stage1_analyst` | prod_on | factcheck | system | 2872 | `806d6cc6af77` | 1 | 0 |
| `factcheck.stage1_analyst` | prod_on | factcheck | user | 222 | `e8275d4a239a` | 3 | 0 |
| `factcheck.stage2_verbalizer` | prod_on | factcheck | system | 1601 | `a1512229147a` | 3 | 2 |
| `factcheck.stage2_verbalizer` | prod_on | factcheck | user | 303 | `7e6d8d8dbc58` | 1 | 0 |
| `initiative.l1_planner` | prod_on | initiative | system | 15453 | `09f3d533d173` | 1 | 0 |
| `initiative.l1_planner` | prod_on | initiative | user | 1199 | `2e4cca3fabf2` | 5 | 0 |
| `initiative.l2_writer` | prod_on | initiative | system | 7718 | `9d767f32a789` | 9 | 8 |
| `initiative.l2_writer` | prod_on | initiative | user | 1664 | `eb2643c7d819` | 4 | 0 |
| `direct.l1_planner` | factory_off | l1 | system | 15453 | `09f3d533d173` | 1 | 0 |
| `direct.l1_planner` | factory_off | l1 | user | 679 | `0ac3f5d353cf` | 5 | 0 |
| `direct.l2_writer.direct` | factory_off | l1 | system | 5189 | `0f778962e071` | 3 | 2 |
| `direct.l2_writer.direct` | factory_off | l1 | user | 1748 | `60557f8f2e84` | 9 | 2 |
| `direct.tool_phase.model_driven` | factory_off | legacy_l1_off | system | 5961 | `fa18451557a4` | 3 | 2 |
| `direct.tool_phase.model_driven` | factory_off | legacy_l1_off | user | 767 | `1508171490b4` | 7 | 2 |
| `direct.tool_phase.tool_round` | factory_off | legacy_l1_off | system | 5961 | `fa18451557a4` | 3 | 2 |
| `direct.tool_phase.tool_round` | factory_off | legacy_l1_off | user | 767 | `1508171490b4` | 7 | 2 |
| `direct.tool_phase.tool_round` | factory_off | legacy_l1_off | assistant | 0 | `e3b0c44298fc` | 0 | 0 |
| `direct.tool_phase.tool_round` | factory_off | legacy_l1_off | tool | 57 | `580242f6cf5f` | 1 | 0 |
| `direct.system2.stage1` | factory_off | legacy_l1_off | system | 1107 | `6bae7eb26bc3` | 1 | 0 |
| `direct.system2.stage1` | factory_off | legacy_l1_off | user | 349 | `52793b5f312a` | 2 | 0 |
| `direct.system2.stage2` | factory_off | legacy_l1_off | system | 5192 | `3777cd74c36a` | 3 | 2 |
| `direct.system2.stage2` | factory_off | legacy_l1_off | user | 232 | `47ee6857d5c8` | 1 | 0 |
| `direct.l2_writer.layered` | factory_off | l1 | system | 5374 | `4e4ed6b8babf` | 7 | 6 |
| `direct.l2_writer.layered` | factory_off | l1 | user | 1150 | `d6bb293af57a` | 13 | 12 |
| `direct.l2_writer.fallback_model_repack` | factory_off | l1 | system | 5374 | `4e4ed6b8babf` | 7 | 6 |
| `direct.l2_writer.fallback_model_repack` | factory_off | l1 | user | 1150 | `1068de784d23` | 13 | 12 |
| `direct.l2_writer.fallback_model_capacity` | factory_off | l1 | system | 5374 | `4e4ed6b8babf` | 7 | 6 |
| `direct.l2_writer.fallback_model_capacity` | factory_off | l1 | user | 709 | `7ed533ba7ed8` | 6 | 192 |

Полные тексты сегментов и порядок блоков — в `sent-segments.json` (поле `stages[].messages[]`).

## Структура сообщений

Роли во всём снимке: `assistant, system, tool, user`; в боевых стадиях: `assistant, system, tool, user`.

* `system` (индекс 0) — канон канала + Core/identity/Expression/lessons/speech/plan (боевая сборка композера).
* `user` — вопрос + контекст + план + evidence.
* `assistant` и `tool` появляются ТОЛЬКО в model-driven tool-цикле (`tool_loop.chat_with_tools`, раунды 2+): модель возвращает `tool_calls`, исполнитель отвечает сообщением `role="tool"` с результатом. Это снято стадиями `direct.tool_phase.model_driven` (раунд 1) и `direct.tool_phase.tool_round` (раунд 2). На L1-пути (боевой по умолчанию, `DIRECT_L1_ENABLED=True`) инструментальная фаза детерминированная и сообщений `assistant`/`tool` не отправляет.
* `developer` не используется ни одной стадией — проверено по фактическим ролям всех сегментов снимка.

Схемы инструментов передаются вне `messages` — аргументом транспорта `tools=[...]` (зафиксировано у tool-стадий).

## Слои боевой сборки (манифест композера)

| Слой | Рендерился (стадий) | Пропущен | Ревизии |
| --- | --- | --- | --- |
| `channel_contract` | 15 | 0 | `09f3d533d173`, `68f0233d7050`, `7a5aea1b73a4`, `6bae7eb26bc3` |
| `channel_output` | 0 | 15 | — |
| `context_lessons` | 9 | 28 | `967168fb043a`, `3ee71340094e`, `b67aef6dcf09` |
| `core` | 11 | 4 | `fac:8dbb8c10ddc6` |
| `expression` | 11 | 4 | `e94abb8521ea` |
| `few_shot` | 0 | 30 | — |
| `humor_craft` | 0 | 15 | — |
| `identity` | 3 | 12 | `bd902f20c0ca2ab8` |
| `response_plan` | 11 | 4 | `a5146b0033b2`, `5c2c19523c24` |
| `self_model_traits` | 0 | 15 | — |
| `style_policy_hint` | 0 | 15 | — |

Слой присутствует в payload, если он `rendered`; причина пропуска видна в поле `composer_layers[].skip_reason` соответствующей стадии, полный манифест — в `sent-segments.json` (`composer_manifests`).

Стадии, где личность (`identity`) реально отрендерена: `direct.l2_writer.layered`, `direct.l2_writer.fallback_model_repack`, `direct.l2_writer.fallback_model_capacity`. В остальных боевых стадиях `identity` честно пропущен (`identity_absent`): PG-персона офлайн недоступна.

## Какая стадия когда срабатывает

| Стадия | Название | Точка вызова |
| --- | --- | --- |
| `direct.l1_planner` | L1 Planner (плановый JSON, Direct-ход) | `services/direct_chat_service.py::DirectChatService._plan_direct_l1 (messages@5368)` |
| `direct.l2_writer.direct` | L2 Writer — прямой ответ без инструментов | `services/direct_chat_service.py::DirectChatService._l2_write_answer (messages@6972)` |
| `direct.l1_planner.tools` | L1 Planner — план с capabilities_needed=web_search | `services/direct_chat_service.py::DirectChatService._plan_direct_l1 (messages@5368)` |
| `direct.l2_writer.tool_evidence` | L2 Writer — после инструментальной фазы (Tool_Evidence) | `services/direct_chat_service.py::DirectChatService._l2_write_answer (messages@6972)` |
| `direct.l2_writer.deterministic_fallback_plan` | L2 Writer — деградированный путь: L1 недоступен, план детерминированный (0 LLM-вызовов планера) | `services/direct_chat_service.py::_plan_direct_l1 → direct_l1.fallback_plan → _l2_write_answer` |
| `direct.tool_phase.model_driven` | Tool-фаза (model-driven): первый запрос цикла + схемы инструментов | `services/direct_chat_service.py::handle → build_messages@4044 → tool_loop.chat_with_tools@4322 (раунд 1)` |
| `direct.tool_phase.tool_round` | Tool-фаза (model-driven): второй запрос цикла — assistant.tool_calls + роль tool с результатом | `services/tool_loop.py::chat_with_tools (round 2, payload_messages.append assistant/tool @853/@889)` |
| `direct.system2.stage1` | System2 Stage-1 (машинная справка по выводу инструментов) | `services/direct_chat_service.py::_synthesize_direct_answer (messages@7168)` |
| `direct.system2.stage2` | System2 Stage-2 (вербализатор валидированной справки) | `services/direct_chat_service.py::_synthesize_direct_answer (messages@7255)` |
| `direct.single.legacy_no_tools` | Legacy одиночный вызов без инструментов | `services/direct_chat_service.py::handle → llm.generate(step='single')@4341` |
| `direct.l2_writer.layered` | L2 Writer со всеми слоями хода (identity/style/lessons/speech/time/evidence) | `services/direct_chat_service.py::DirectChatService._l2_write_answer (messages@6972)` |
| `direct.l2_writer.fallback_model_repack` | L2 Writer — пересборка пакета под окно fallback-модели (пакет помещается целиком) | `services/direct_execution.py::build_l2_fallback_adapter → llm_client payload fallback_payload_adapter` |
| `direct.l2_writer.fallback_model_capacity` | L2 Writer — честный capacity-исход под окно fallback-модели (fallback_window_exceeded) | `services/direct_execution.py::build_l2_fallback_adapter → llm_client payload fallback_payload_adapter` |
| `factcheck.single` | FactCheck — одиночный путь (канон + критика + Core/стиль) | `services/factcheck_service.py::_check_claim_pipeline (messages@1527)` |
| `factcheck.stage1_analyst` | FactCheck Stage-1 — аналитик (JSON по claim + выдача поиска) | `services/factcheck_service.py::_check_claim_two_call (messages@1542)` |
| `factcheck.stage2_verbalizer` | FactCheck Stage-2 — вербализатор валидированной справки | `services/factcheck_service.py::_check_claim_two_call (messages@1595)` |
| `initiative.l1_planner` | Инициатива — решение L1 (reply/react/silent) | `services/direct_chat_service.py::plan_initiative_decision (messages@11807)` |
| `initiative.l2_writer` | Инициатива — тот же L2 Writer (writer='initiative_writer') | `services/direct_chat_service.py::generate_initiative_reply → _l2_write_answer (messages@6972)` |
| `direct.l1_planner` | L1 Planner (плановый JSON, Direct-ход) | `services/direct_chat_service.py::DirectChatService._plan_direct_l1 (messages@5368)` |
| `direct.l2_writer.direct` | L2 Writer — прямой ответ без инструментов | `services/direct_chat_service.py::DirectChatService._l2_write_answer (messages@6972)` |
| `direct.tool_phase.model_driven` | Tool-фаза (model-driven): первый запрос цикла + схемы инструментов | `services/direct_chat_service.py::handle → build_messages@4044 → tool_loop.chat_with_tools@4322 (раунд 1)` |
| `direct.tool_phase.tool_round` | Tool-фаза (model-driven): второй запрос цикла — assistant.tool_calls + роль tool с результатом | `services/tool_loop.py::chat_with_tools (round 2, payload_messages.append assistant/tool @853/@889)` |
| `direct.system2.stage1` | System2 Stage-1 (машинная справка по выводу инструментов) | `services/direct_chat_service.py::_synthesize_direct_answer (messages@7168)` |
| `direct.system2.stage2` | System2 Stage-2 (вербализатор валидированной справки) | `services/direct_chat_service.py::_synthesize_direct_answer (messages@7255)` |
| `direct.l2_writer.layered` | L2 Writer со всеми слоями хода (identity/style/lessons/speech/time/evidence) | `services/direct_chat_service.py::DirectChatService._l2_write_answer (messages@6972)` |
| `direct.l2_writer.fallback_model_repack` | L2 Writer — пересборка пакета под окно fallback-модели (пакет помещается целиком) | `services/direct_execution.py::build_l2_fallback_adapter → llm_client payload fallback_payload_adapter` |
| `direct.l2_writer.fallback_model_capacity` | L2 Writer — честный capacity-исход под окно fallback-модели (fallback_window_exceeded) | `services/direct_execution.py::build_l2_fallback_adapter → llm_client payload fallback_payload_adapter` |

## Порядок блоков (что реально склеено в каждом сегменте)

### `direct.l1_planner` → system (prod_on)

`layer:channel_contract:channel_canon`

### `direct.l1_planner` → user (prod_on)

`section:[СООБЩЕНИЕ]` → `section:[ПОСЛЕДНИЕ СООБЩЕНИЯ]` → `section:[УЧАСТНИКИ]` → `section:[ПАМЯТЬ (срез)]` → `payload:mca07_bundle_slice`

### `direct.l2_writer.direct` → system (prod_on)

`layer:channel_contract:channel_canon` → `separator` → `layer:core:core` → `separator` → `layer:response_plan:response_plan` → `separator` → `layer:speech_base` → `separator` → `layer:expression:expression`

### `direct.l2_writer.direct` → user (prod_on)

`layer:time_line` → `separator` → `tag:Response_Plan` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question` → `canon:no_meta_closing`

### `direct.l1_planner.tools` → system (prod_on)

`layer:channel_contract:channel_canon`

### `direct.l1_planner.tools` → user (prod_on)

`section:[СООБЩЕНИЕ]` → `section:[ПОСЛЕДНИЕ СООБЩЕНИЯ]` → `section:[УЧАСТНИКИ]` → `section:[ПАМЯТЬ (срез)]` → `payload:mca07_bundle_slice`

### `direct.l2_writer.tool_evidence` → system (prod_on)

`layer:channel_contract:channel_canon` → `separator` → `layer:core:core` → `separator` → `layer:response_plan:response_plan` → `separator` → `layer:speech_base` → `separator` → `layer:expression:expression`

### `direct.l2_writer.tool_evidence` → user (prod_on)

`layer:time_line` → `separator` → `tag:Response_Plan` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question` → `payload:tool_evidence_block` → `canon:no_meta_closing`

### `direct.l2_writer.deterministic_fallback_plan` → system (prod_on)

`layer:channel_contract:channel_canon` → `separator` → `layer:core:core` → `separator` → `layer:response_plan:response_plan` → `separator` → `layer:speech_base` → `separator` → `layer:expression:expression`

### `direct.l2_writer.deterministic_fallback_plan` → user (prod_on)

`layer:time_line` → `separator` → `tag:Response_Plan` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question` → `canon:no_meta_closing`

### `direct.tool_phase.model_driven` → system (prod_on)

`layer:channel_contract:channel_canon` → `separator` → `layer:core:core` → `separator` → `layer:response_plan:response_plan` → `separator` → `layer:speech_base` → `separator` → `layer:expression:expression`

### `direct.tool_phase.model_driven` → user (prod_on)

`layer:time_line` → `separator` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question`

### `direct.tool_phase.tool_round` → system (prod_on)

`layer:channel_contract:channel_canon` → `separator` → `layer:core:core` → `separator` → `layer:response_plan:response_plan` → `separator` → `layer:speech_base` → `separator` → `layer:expression:expression`

### `direct.tool_phase.tool_round` → user (prod_on)

`layer:time_line` → `separator` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question`

### `direct.tool_phase.tool_round` → assistant (prod_on)

_(один неразмеченный блок)_

### `direct.tool_phase.tool_round` → tool (prod_on)

`layer:tool_result`

### `direct.system2.stage1` → system (prod_on)

`layer:channel_contract:channel_canon`

### `direct.system2.stage1` → user (prod_on)

`payload:mca07_bundle_slice` → `payload:synthesis_input`

### `direct.system2.stage2` → system (prod_on)

`layer:channel_contract:channel_canon` → `separator` → `layer:core:core` → `separator` → `layer:response_plan:response_plan` → `separator` → `layer:speech_base` → `separator` → `layer:expression:expression`

### `direct.system2.stage2` → user (prod_on)

`payload:stage2_reference_json`

### `direct.single.legacy_no_tools` → system (prod_on)

`layer:channel_contract:channel_canon` → `separator` → `layer:core:core` → `separator` → `layer:response_plan:response_plan` → `separator` → `layer:speech_base` → `separator` → `layer:expression:expression`

### `direct.single.legacy_no_tools` → user (prod_on)

`layer:time_line` → `separator` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question`

### `direct.l2_writer.layered` → system (prod_on)

`layer:channel_contract:channel_canon` → `separator` → `layer:core:core` → `separator` → `layer:identity:identity` → `separator` → `layer:context_lessons:style_requests` → `separator` → `layer:context_lessons:verified_lessons` → `separator` → `layer:context_lessons:speech_understanding` → `separator` → `layer:response_plan:response_plan` → `separator` → `layer:speech_base` → `separator` → `layer:expression:expression`

### `direct.l2_writer.layered` → user (prod_on)

`layer:time_line` → `separator` → `layer:plan_block` → `separator` → `layer:user_block_global_context` → `separator` → `layer:tool_evidence_block` → `separator` → `canon:no_meta_closing`

### `direct.l2_writer.fallback_model_repack` → system (prod_on)

`layer:channel_contract:channel_canon` → `separator` → `layer:core:core` → `separator` → `layer:identity:identity` → `separator` → `layer:context_lessons:style_requests` → `separator` → `layer:context_lessons:verified_lessons` → `separator` → `layer:context_lessons:speech_understanding` → `separator` → `layer:response_plan:response_plan` → `separator` → `layer:speech_base` → `separator` → `layer:expression:expression`

### `direct.l2_writer.fallback_model_repack` → user (prod_on)

`layer:time_line` → `separator` → `layer:plan_block` → `separator` → `layer:user_block_global_context` → `separator` → `canon:no_meta_closing` → `separator` → `layer:tool_evidence_block`

### `direct.l2_writer.fallback_model_capacity` → system (prod_on)

`layer:channel_contract:channel_canon` → `separator` → `layer:core:core` → `separator` → `layer:identity:identity` → `separator` → `layer:context_lessons:style_requests` → `separator` → `layer:context_lessons:verified_lessons` → `separator` → `layer:context_lessons:speech_understanding` → `separator` → `layer:response_plan:response_plan` → `separator` → `layer:speech_base` → `separator` → `layer:expression:expression`

### `direct.l2_writer.fallback_model_capacity` → user (prod_on)

`layer:time_line` → `separator` → `payload:l2_fallback_truncation_marker` → `payload:tool_evidence_block` → `payload:l2_capacity_note`

### `factcheck.single` → system (prod_on)

`prompt:prompts.factcheck_system_prompt` → `separator` → `block:factcheck_critique_section(self_assessed)`

### `factcheck.single` → user (prod_on)

`layer:claim` → `separator` → `layer:user_hint` → `separator` → `layer:search_results`

### `factcheck.stage1_analyst` → system (prod_on)

`prompt:prompts.factcheck_analyst_system_prompt`

### `factcheck.stage1_analyst` → user (prod_on)

`tag:claim` → `tag:user_hint` → `tag:search_results`

### `factcheck.stage2_verbalizer` → system (prod_on)

`prompt:prompts.factcheck_verbalizer_system_prompt` → `separator` → `prompt:prompts.verbilizer_mode_serious`

### `factcheck.stage2_verbalizer` → user (prod_on)

`payload:factcheck_analysis_json`

### `initiative.l1_planner` → system (prod_on)

`layer:channel_contract:channel_canon`

### `initiative.l1_planner` → user (prod_on)

`section:[СООБЩЕНИЕ]` → `section:[ПОСЛЕДНИЕ СООБЩЕНИЯ]` → `section:[УЧАСТНИКИ]` → `section:[ДОСТУПНЫЕ ВОЗМОЖНОСТИ]` → `section:[УСЛОВИЯ]`

### `initiative.l2_writer` → system (prod_on)

`layer:channel_contract:channel_canon` → `separator` → `layer:core:core` → `separator` → `layer:response_plan:response_plan` → `separator` → `layer:speech_base` → `separator` → `layer:expression:expression`

### `initiative.l2_writer` → user (prod_on)

`tag:Response_Plan` → `tag:Initiative_Context` → `tag:Fresh_Chat_Window` → `canon:no_meta_closing`

### `direct.l1_planner` → system (factory_off)

`prompt:prompts.direct_l1_planner_system_prompt`

### `direct.l1_planner` → user (factory_off)

`section:[СООБЩЕНИЕ]` → `section:[ПОСЛЕДНИЕ СООБЩЕНИЯ]` → `section:[УЧАСТНИКИ]` → `section:[ПАМЯТЬ (срез)]` → `payload:mca07_bundle_slice`

### `direct.l2_writer.direct` → system (factory_off)

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]`

### `direct.l2_writer.direct` → user (factory_off)

`layer:time_line` → `separator` → `tag:Response_Plan` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question` → `canon:no_meta_closing`

### `direct.tool_phase.model_driven` → system (factory_off)

`prompt:prompts.direct_chat_system_prompt` → `separator` → `mode_or_extent_block[0]`

### `direct.tool_phase.model_driven` → user (factory_off)

`layer:time_line` → `separator` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question`

### `direct.tool_phase.tool_round` → system (factory_off)

`prompt:prompts.direct_chat_system_prompt` → `separator` → `mode_or_extent_block[0]`

### `direct.tool_phase.tool_round` → user (factory_off)

`layer:time_line` → `separator` → `tag:UserResolutionMap` → `tag:RAG_Memory` → `tag:Global_Context` → `tag:Target_User` → `tag:Current_Question`

### `direct.tool_phase.tool_round` → assistant (factory_off)

_(один неразмеченный блок)_

### `direct.tool_phase.tool_round` → tool (factory_off)

`layer:tool_result`

### `direct.system2.stage1` → system (factory_off)

`prompt:prompts.direct_chat_synthesizer_system_prompt`

### `direct.system2.stage1` → user (factory_off)

`payload:mca07_bundle_slice` → `payload:synthesis_input`

### `direct.system2.stage2` → system (factory_off)

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]`

### `direct.system2.stage2` → user (factory_off)

`payload:stage2_reference_json`

### `direct.l2_writer.layered` → system (factory_off)

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]` → `separator` → `layer:character_block` → `separator` → `layer:style_requests`

### `direct.l2_writer.layered` → user (factory_off)

`layer:time_line` → `separator` → `layer:plan_block` → `separator` → `layer:speech_understanding` → `separator` → `layer:verified_lessons` → `separator` → `layer:user_block_global_context` → `separator` → `layer:tool_evidence_block` → `separator` → `canon:no_meta_closing`

### `direct.l2_writer.fallback_model_repack` → system (factory_off)

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]` → `separator` → `layer:character_block` → `separator` → `layer:style_requests`

### `direct.l2_writer.fallback_model_repack` → user (factory_off)

`layer:time_line` → `separator` → `layer:plan_block` → `separator` → `layer:speech_understanding` → `separator` → `layer:verified_lessons` → `separator` → `layer:user_block_global_context` → `separator` → `canon:no_meta_closing` → `separator` → `layer:tool_evidence_block`

### `direct.l2_writer.fallback_model_capacity` → system (factory_off)

`prompt:prompts.direct_chat_verbalizer_system_prompt` → `separator` → `mode_or_extent_block[0]` → `separator` → `layer:character_block` → `separator` → `layer:style_requests`

### `direct.l2_writer.fallback_model_capacity` → user (factory_off)

`layer:time_line` → `separator` → `payload:l2_fallback_truncation_marker` → `payload:tool_evidence_block` → `payload:l2_capacity_note`

## Эффективные ревизии и печати канона

`act:` — действующая редакция текста, `fac:` — заводская редакция по печати реестра, `found_at` — позиция в байтах сегмента.

| Стадия | Ключ | block_id | act | fac | source | found_at |
| --- | --- | --- | --- | --- | --- | --- |
| `direct.l1_planner` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.l1_planner` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:09f3d533d173` | `fac:09f3d533d173(l1-planner-two-phase-precedence)` | code_default | 0 |
| `direct.l1_planner` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | -1 |
| `direct.l2_writer.direct` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.l2_writer.direct` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:09f3d533d173` | `fac:09f3d533d173(l1-planner-two-phase-precedence)` | code_default | -1 |
| `direct.l2_writer.direct` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |
| `direct.l1_planner.tools` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.l1_planner.tools` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:09f3d533d173` | `fac:09f3d533d173(l1-planner-two-phase-precedence)` | code_default | 0 |
| `direct.l1_planner.tools` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | -1 |
| `direct.l2_writer.tool_evidence` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.l2_writer.tool_evidence` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:09f3d533d173` | `fac:09f3d533d173(l1-planner-two-phase-precedence)` | code_default | -1 |
| `direct.l2_writer.tool_evidence` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |
| `direct.l2_writer.deterministic_fallback_plan` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | -1 |
| `direct.l2_writer.deterministic_fallback_plan` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:09f3d533d173` | `fac:09f3d533d173(l1-planner-two-phase-precedence)` | code_default | -1 |
| `direct.l2_writer.deterministic_fallback_plan` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |
| `direct.tool_phase.model_driven` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | 0 |
| `direct.tool_phase.model_driven` | `prompts.direct_chat_synthesizer_system_prompt` | `direct.base.synthesizer` | `act:6bae7eb26bc3` | `fac:6bae7eb26bc3(synthesizer-r1023)` | code_default | -1 |
| `direct.tool_phase.model_driven` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | -1 |
| `direct.tool_phase.tool_round` | `prompts.direct_chat_system_prompt` | `direct.base.tool_phase` | `act:7a5aea1b73a4` | `fac:7a5aea1b73a4(toolphase-runtime-evidence)` | default | 0 |
| `direct.tool_phase.tool_round` | `prompts.direct_chat_synthesizer_system_prompt` | `direct.base.synthesizer` | `act:6bae7eb26bc3` | `fac:6bae7eb26bc3(synthesizer-r1023)` | code_default | -1 |
| `direct.tool_phase.tool_round` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | -1 |
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
| `factcheck.single` | `prompts.factcheck_system_prompt` | `factcheck.base.single` | `act:d02776dec166` | `fac:d02776dec166(factcheck-phases-w17)` | code_default | 0 |
| `factcheck.single` | `prompts.factcheck_critique_directive` | `factcheck.critique.directive` | `act:cfcd9009df17` | `fac:cfcd9009df17(factcheck-critique-w5)` | code_default | 5311 |
| `factcheck.stage1_analyst` | `prompts.factcheck_system_prompt` | `factcheck.base.single` | `act:d02776dec166` | `fac:d02776dec166(factcheck-phases-w17)` | code_default | -1 |
| `factcheck.stage1_analyst` | `prompts.factcheck_analyst_system_prompt` | `factcheck.base.analyst` | `act:806d6cc6af77` | `fac:806d6cc6af77(factcheck-analyst-phases-w17)` | code_default | 0 |
| `factcheck.stage1_analyst` | `prompts.factcheck_verbalizer_system_prompt` | `factcheck.base.verbalizer` | `act:42442333d77d` | `fac:42442333d77d(factcheck-verbalizer-w1)` | code_default | -1 |
| `factcheck.stage1_analyst` | `prompts.verbilizer_mode_serious` | `verbilizer.mode.serious` | `act:0ffb292caf70` | `fac:0ffb292caf70(mode-r1023)` | code_default | -1 |
| `factcheck.stage2_verbalizer` | `prompts.factcheck_system_prompt` | `factcheck.base.single` | `act:d02776dec166` | `fac:d02776dec166(factcheck-phases-w17)` | code_default | -1 |
| `factcheck.stage2_verbalizer` | `prompts.factcheck_analyst_system_prompt` | `factcheck.base.analyst` | `act:806d6cc6af77` | `fac:806d6cc6af77(factcheck-analyst-phases-w17)` | code_default | -1 |
| `factcheck.stage2_verbalizer` | `prompts.factcheck_verbalizer_system_prompt` | `factcheck.base.verbalizer` | `act:42442333d77d` | `fac:42442333d77d(factcheck-verbalizer-w1)` | code_default | 0 |
| `factcheck.stage2_verbalizer` | `prompts.verbilizer_mode_serious` | `verbilizer.mode.serious` | `act:0ffb292caf70` | `fac:0ffb292caf70(mode-r1023)` | code_default | 1445 |
| `initiative.l1_planner` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:09f3d533d173` | `fac:09f3d533d173(l1-planner-two-phase-precedence)` | code_default | 0 |
| `initiative.l1_planner` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | -1 |
| `initiative.l2_writer` | `prompts.direct_l1_planner_system_prompt` | `direct.base.l1_planner` | `act:09f3d533d173` | `fac:09f3d533d173(l1-planner-two-phase-precedence)` | code_default | -1 |
| `initiative.l2_writer` | `prompts.direct_chat_verbalizer_system_prompt` | `direct.base.l2_writer` | `act:68f0233d7050` | `fac:68f0233d7050(l2-writer-evidence-discipline)` | code_default | 0 |

## Что доказано

1. Для каждой боевой стадии существует ровно тот payload, который уходит в транспорт; структура `system@0` + `user` подтверждена фактическими `messages`.
2. Core / identity / Expression / lessons / speech / response_plan участвуют в боевой сборке: они `rendered` в манифесте композера, их тексты найдены в system сегмента (см. блоки `layer:core:*`, `layer:identity:*`, `layer:expression:*`), ревизии зафиксированы.
3. model-driven tool-цикл снят целиком: раунд 1 (system+user) и раунд 2 (`assistant` с `tool_calls` + `role=tool` с результатом) — как их собирает `services/tool_loop.py`.
4. Длины и `sha256` каждого сегмента воспроизводятся байт-в-байт в двух независимых процессах.
5. Каждый блок, пришедший через именованный шов (`resolve_prompt`, `resolve_chat_speech`, `compose_prompt`, `build_l2_fallback_adapter`), найден в финальном тексте сегмента в порядке сборки.
6. Деградированные пути: отказ L1 → Writer с детерминированным планом; переключение на fallback-модель → пересборка её же адаптером, оба исхода сняты.

## Что НЕ доказано (нужен живой вызов модели)

* Приём payload провайдером (HTTP 200), фактический `usage`, ошибки провайдера, соблюдение моделью инструкций и качество ответа.
* Точные боевые тексты документов владельца: PG недоступен, поэтому Core/Expression — заводские редакции, личность — объявленный `character_block` (см. «Ограничения снимка»).
* Per-chat override другого чата.

## Наблюдения по порядку блоков

* `direct.l2_writer.fallback_model_repack`: блок `layer:tool_evidence_block` (объявлен №12) стоит в байтах ПОСЛЕ блока №13. Это наблюдаемое поведение существующего кода (дефект адаптера fallback-пересборки, вынесен в отдельную полосу), а не решение снимка.
* `direct.l2_writer.fallback_model_repack`: блок `layer:tool_evidence_block` (объявлен №10) стоит в байтах ПОСЛЕ блока №11. Это наблюдаемое поведение существующего кода (дефект адаптера fallback-пересборки, вынесен в отдельную полосу), а не решение снимка.

## Происхождение снимка (какой код собирал payload)

| Файл | Строк | sha256 |
| --- | --- | --- |
| `services/chat_prompts.py` | 1613 | `9274fe14bb7b4736…` |
| `services/direct_chat_service.py` | 13228 | `ebbd6d8a893b8068…` |
| `services/direct_execution.py` | 1368 | `90a16202ea960d4e…` |
| `services/direct_l1.py` | 1616 | `351c5f3549de8d3c…` |
| `services/factcheck_prompts.py` | 631 | `cc33b7046a08d730…` |
| `services/factcheck_service.py` | 2414 | `e4dbe97d5c2a12e3…` |
| `services/llm_client.py` | 2015 | `b79ef1680ad7a0be…` |
| `services/mca_expression.py` | 810 | `f292ad43e733e1b2…` |
| `services/negative_constraints.py` | 933 | `e1ca1844e2edfdbe…` |
| `services/payload_builder.py` | 36 | `30645fbba34850c4…` |
| `services/prompt_composer.py` | 2392 | `15f5705cc91ede08…` |
| `services/prompt_registry.py` | 3749 | `d6f872b614470242…` |
| `services/prompt_style_blocks.py` | 920 | `ebc5be8c44c39b8e…` |
| `services/response_extent.py` | 768 | `851befe528339388…` |
| `services/summary_xml.py` | 182 | `97f2a8c068191228…` |
| `services/tool_loop.py` | 1092 | `87cbfa92e6499529…` |

## Откуда берётся неатрибутированный остаток

Блоки, которые рендерятся внутри функций без именованного шва (`build_l1_context`, сборочные обёртки), остаются `unattributed` со своим `offset`/`sha256`. Это не потеря: весь текст сегмента покрыт `sha256`, но не атрибутирован по имени шва.

