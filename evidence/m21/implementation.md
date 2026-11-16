# MOD-ACL-UX-01 M2.1 — per-chat adapters для 12 модулей (corrective D1–D4)

**Статус:** corrective-кандидат; независимое ревью обязательно. `VERIFIED` не
заявляется, деплой не выполнялся.

**База:** `bca18c1e` (2.58.205, schema 47). **Ветка:**
`acl/m2.1-perchat-adapters`. **Текущий corrective code commit:**
`1a417917f128521f988fca9845f45ed3a6c6a7a5` (16 files, +490/−76). Предыдущие
шаги лейна: `b278a547` (F1–F10), `9b78b6ab` (test-only), `299ac2b7` (evidence).
**Кумулятивный срез `bca18c1e..1a417917`:** 44 files, +3516/−249 (включает
предыдущие M2.1-коммиты; evidence-коммит добавляет только `evidence/m21`).
**Требования среза:** `MAC-AC-04`, `MAC-S2-TT-5`, `MAC-S10-01`, `MAC-S15-12`,
`MAC-S2-SHARED-01`; consumer-proof для `MAC-S0-01`, `MAC-S2-TT-4`,
`MAC-S2-91`, `MAC-S2-116`, `MAC-AC-02`.

## 1. Что исправлено в этом corrective (D1–D4)

| # | Замечание | Фактическое исправление | Проверка |
|---|---|---|---|
| D1 | initiative не публикует при GLOBAL OFF + CHAT ON: `candidate_from_trigger`, `handle_initiative`, `intent_decision_enabled`, `IntentService.create_intent` держали product master-AND | Продуктовый master (`flags.initiative_enabled`) — наследуемый GLOBAL-дефолт, решает per chat. `candidate_from_trigger` читает только env-ось `MCA_INTENTS_ENABLED`; `IntentService.create_intent/list_active/due_candidates` и `handle_initiative` спрашивают `initiative_observer.initiative_chat_enabled` (канонический `chat_params`-резолвер); lifecycle (`defer/resume/mark_attempt/close/note_writer_failure`), гигиена и heartbeat-хост используют аварийную env-ось; `intent_decision_enabled`/`send_recheck_enabled`/`intent_heartbeat_enabled` больше не зависят от product master; due-скан фильтрует чаты per chat | `test_initiative_publishes_when_global_off_chat_on` (реальные `candidate_from_trigger` + `handle_initiative` → отправка через `telegram_send.send_text`), `test_initiative_create_intent_is_per_chat` (реальный `DatabaseService` + `IntentService.create_intent/list_active`), mutation 1 |
| D2 | командный force-repeat transcribe игнорировал чатовый OFF | `handlers.voice_transcription.force_repeat_from_reply` (его зовёт `handlers/youtube._handle_voice_command`) проверяет `flags.enable_voice_transcription` per chat каноническим `feature_gates.module_enabled` ДО STT; ошибка резолвера → fail-closed | `test_force_repeat_transcribe_per_chat` (GLOBAL ON+CHAT OFF → STT не зван; GLOBAL OFF+CHAT ON → зван), mutation 2 |
| D3 | character frame не рендерился при GLOBAL OFF + CHAT ON: точка сборки читала глобальный `self_model_enabled()` | `build_persona_prompt_block(..., chat_id=)` берёт кадр из пина ЭТОГО чата (`run_frame_for_chat`; чужой/отсутствующий пин → legacy). Production-точки (`resolve_character_block`, Direct system prompt, payload estimate) передают `chat_id`; сами не резолвят второй раз — решение уже принято `self_model_enabled_for_chat` | `test_character_frame_renders_when_global_off_chat_on` (ctx.frame_version + `<FRAME>`; GLOBAL ON даёт тот же блок; CHAT OFF → legacy), mutation 3 |
| D4 | устаревший docstring `_build_health` («per-chat слоя нет») | docstring описывает реальный per-chat `feature_gates.module_enabled` | source-proof + focused GREEN |

### Ранее закрытые F1–F10 (сохранены)

| # | Замечание | Исправление | Проверка |
|---|---|---|---|
| F1 | initiative: product master-AND глушил CHAT ON | env `intents_env_enabled()`; authoritative global `flags.initiative_enabled` через `chat_params.read_global` + явный `global_value` | `test_initiative_global_off_chat_on_is_on`, `test_initiative_global_default_is_master_not_legacy_global`, `test_initiative_global_on_chat_off_is_off`, `test_initiative_emergency_env_overrides_chat`, `test_initiative_scheduler_ticks_when_chat_is_on` |
| F2 | character: `if not self_model_enabled(): return False` | `self_model_enabled_for_chat` = `resolve_module_capability("character")`; env — `emergency_block` | `test_character_global_off_chat_on_is_on`, `test_character_chat_off_does_not_stop_global_model`, `test_character_emergency_env_blocks_chat_on`, `test_character_usage_per_chat` |
| F3 | random: пул глушился product-AND | `random_source_enabled()` env-only (живость пула); использование — `module_enabled(module_id="random")` | `test_random_global_off_chat_on_is_on`, `test_random_chat_off_keeps_global_pool`, `test_random_emergency_env_blocks_chat_on`, `test_random_usage_per_chat` |
| F4 | тесты/мутации закрепляли запрещённую семантику | инвертированы; мутации убиваются | RED/GREEN + `mutations.json` |
| F5 | factcheck tool: глобальный `hot.get`, `active_tools()` без chat_id | `active_tools_for_chat`; `fact_check_tool_enabled_for_chat`; Direct-пути и readiness — тот же резолвер | `test_factcheck_tool_path_per_chat` |
| F6 | checkup readiness: глобальный `CHECKUP_KEY` | `_build_health` → `feature_gates.module_enabled(chat_id, key=CHECKUP_KEY)` | `test_checkup_readiness_per_chat` |
| F7 | transcribe DI только при глобальном ON | общий `voice_service` подключается всегда; per-chat гейт в handler | `test_voice_transcription_di_is_not_conditional` |
| F8 | stories: per-chat гейт до ACL | `_require_scope_access` до гейта во всех read-endpoint | `test_stories_acl_precedes_per_chat_gate` |
| F9 | fail-closed при исключении резолвера не зафиксирован | явно fail-closed, без fallback | `test_module_enabled_fail_closed_on_resolver_error` |
| F10 | evidence: несуществующие пути, смешанные diff-цифры | точные SHA/цифры/артефакты | `tests-summary.json` |

## 2. Семантика GLOBAL/CHAT (не изменилась в D1–D4)

Каноническая семантика **GLOBAL default → CHAT override** (owner §0.1/§2.1/
§2.3.1; design §12.2/§12.5.1; plan §3.3; `MAC-S2-TT-4`):

| GLOBAL | CHAT | Результат |
|---|---|---|
| ON | INHERIT | ON |
| ON | OFF | OFF |
| OFF | INHERIT | OFF |
| OFF | ON | **ON (только этот чат)** |

`emergency_block` (env-оси `MCA_INTENTS_ENABLED`, `MCA_SELF_MODEL_ENABLED`,
`MCA_RANDOM_SOURCE_ENABLED`, `MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED`,
`MCA_STORIES_VITRINA_ENABLED`) — отдельная ось, перекрывает `desired`, не
подменяя сохранённый выбор.

Для initiative это теперь проведено до конца: продуктовый GLOBAL OFF не
останавливает shared-тик/пул и не глушит явный CHAT ON ни на создании
намерения, ни на решении, ни на публикации; чатовый OFF запрещает потребление
этого чата, не останавливая общий worker.

## 3. Изменённые файлы corrective-коммита `1a417917`

- `services/mca_gates.py` — K1-зависимость K2/K3/K4 только от env-оси;
- `services/initiative_observer.py` — единая per-chat проверка
  `initiative_chat_enabled` (наблюдатель использует её же);
- `services/mca_intents.py` — `candidate_from_trigger` (env-only),
  `create_intent`/`list_active`/`due_candidates` (per chat), lifecycle и
  heartbeat-хост (emergency);
- `services/direct_chat_service.py` — `handle_initiative` (K3 + per chat),
  producer `unanswered_question` (env-ось), передача `chat_id` в точку сборки
  persona-блока (system prompt + payload estimate);
- `services/bot_persona.py` — `run_frame_for_chat` + `chat_id` в
  `build_persona_prompt_block`;
- `handlers/voice_transcription.py` — per-chat гейт в `force_repeat_from_reply`;
- `services/capability_registry.py` — D4 docstring `_build_health`;
- тесты: `test_mod_acl_ux_01_m21_gates.py` (+2 реальных D1-теста),
  `test_mod_acl_ux_01_m21_adapters.py` (+D2/D3), `test_asap7_module_registry.py`,
  `test_asap8_f5_module_truth.py` (две runtime-точки transcribe),
  `test_asap8_f6_initiative.py`, `test_asap8_v6_c06a_heartbeat.py`,
  `test_mca09_intents_block_{a,b,c}_round1040.py` (K1 OFF выражен env-осью).

Запрещённые файлы не изменялись: `module_registry.py`, `permissions.py`,
`access.py`, prompt registry, VMQ QRNG, `cognitive_map.py`, `config_cache.py`,
`param_catalog.py`. DDL/миграций/новых флагов/second ACL нет; stored values не
переписываются.

## 4. Проверки

- **RED на базе `bca18c1e`:** новые D1/D2/D3 тесты (4 node ids) в чистом
  архиве базы → **4 failed / 0 passed** (`pytest-red-base-d1d3.txt`).
  Предыдущий RED-набор F1–F10 сохранён: 44 failed / 3 passed
  (`pytest-red-base.txt`).
- **GREEN на кандидате `1a417917`:** 24 focused-файла → **480 passed, 0
  failed, 0 skipped** (`pytest-green.txt`, `pytest-green.xml`,
  `tests-summary.json`).
- **Мутации:** 3/3 killed (`mutations.txt`, `mutations.json`):
  1. product-AND возвращён в `handle_initiative` → убит
     `test_initiative_publishes_when_global_off_chat_on`;
  2. per-chat гейт снят в `force_repeat_from_reply` → убит
     `test_force_repeat_transcribe_per_chat`;
  3. точка сборки снова читает только глобальный `self_model_enabled()` →
     убит `test_character_frame_renders_when_global_off_chat_on`.
- **Реальные швы (не pre-check):** `candidate_from_trigger`,
  `handle_initiative` (фактическая отправка через
  `telegram_send.send_text`), `IntentService.create_intent/list_active` на
  реальном `DatabaseService`, `force_repeat_from_reply` (AST-ветка handler'а
  youtube), `resolve_character_context` → `build_persona_prompt_block`.
- **Дополнительные прогоны (не входят в 24):** `test_mca09_intents_block_{a–e}`,
  `test_mca09_intents_off_parity`, `test_asap8_f6_initiative`,
  `test_asap8_v6_c06a_{heartbeat,status_ui}`, `test_nostalgia_*`,
  `test_mca10b_random_applications_*`, `test_ur_*`, `test_rlr_acceptance_rows`,
  `test_soul1_*`, `test_evol_*`, `test_status_service`,
  `test_history_retention_toggle`, `test_media_transcribe_tool_round1024`,
  `test_bot_persona`, `test_persona_prompt`, `test_mca18_*` — все зелёные,
  кроме перечисленных ниже pre-existing.
- **Pre-existing failures (вне M2.1; воспроизведены на HEAD `299ac2b7`):**
  `test_initiative_coordination` (4),
  `test_soul1_w5_observer_gates::test_initiative_writer_shares_core_style_and_persona`,
  `test_mca18_block_ef_round1042::test_resolve_character_context_legacy_on_error`,
  `test_initiative_speech_layers_chat_overrides` (4). Первые два класса — тот
  же сломанный writer-stub (`_StubService` без `_writer_evidence_capacity`).

## 5. Конфигурация и ограничения

- Effective configuration: env-оси проверяются как emergency (тесты патчат
  `mca_gates.intents_env_enabled`); GLOBAL/CHAT — через реальный
  `chat_params`-кэш тестового чата; factory defaults не перетираются.
- `flags.initiative_observer_enabled` остаётся собственной осью тика
  наблюдателя; master карточки — `flags.initiative_enabled`; per-chat —
  `initiative.enabled`.
- `stories` manage-контур (`stories_manage_enabled`) остаётся глобальным:
  M2.1 закрывает read-контур, как записано в постановке.
- Live production probe не выполнялся (деплой вне задачи); production
  effective-state не заявляется.
- Per-chat резолв в due-скане: один вызов на чат за тик (кэш `chat_params`
  TTL 120 с; холодный кэш → существующий read-path PG, без нового
  хранилища/DDL).
- `VERIFIED` не заявляется: требуется независимое ревью.

## 6. Артефакты

- `evidence/m21/pytest-red-base.txt` — RED базы F1–F10 (44/3).
- `evidence/m21/pytest-red-base-d1d3.txt` — RED базы для новых D1/D2/D3 (4/4).
- `evidence/m21/pytest-green.txt` / `.xml` — GREEN кандидата (480).
- `evidence/m21/tests-summary.json` — машиночитаемая сводка с точными SHA,
  24 focused-файлами, новыми тестами, RED-наборами и diff-цифрами.
- `evidence/m21/mutations.txt` / `mutations.json` — 3 мутации, все killed.
- `evidence/m21/implementation.md` — этот файл.
