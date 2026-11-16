# MOD-ACL-UX-01 M2.1 — per-chat adapters для 12 модулей (corrective после ревью)

**Статус:** corrective-кандидат; независимое ревью обязательно. `VERIFIED` не
заявляется, деплой не выполнялся.

**База:** `bca18c1e` (2.58.205, schema 47). **Ветка:**
`acl/m2.1-perchat-adapters`. **Corrective code commit:** `b278a547`
(13 files, +514/−155). **Срез целиком:** `bca18c1e..b278a547` — 37 files,
+1885/−173. **Требования среза:** `MAC-AC-04`, `MAC-S2-TT-5`, `MAC-S10-01`,
`MAC-S15-12`, `MAC-S2-SHARED-01`; consumer-proof для `MAC-S0-01`,
`MAC-S2-TT-4`, `MAC-S2-91`, `MAC-S2-116`, `MAC-AC-02`.

## 1. Что исправлено по замечаниям Reviewer

| # | Замечание | Фактическое исправление | Проверка |
|---|---|---|---|
| F1 | initiative: product master-AND (`intents_enabled`) глушил CHAT ON | `mca_gates.intents_env_enabled()` — только env `MCA_INTENTS_ENABLED`; `observer_enabled`/`chat_capability_state` используют его как emergency. Authoritative global для `initiative.enabled` — `flags.initiative_enabled` (через `chat_params.read_global` + явный `global_value`). Тик не ранний `disabled` | `test_initiative_global_off_chat_on_is_on`, `test_initiative_global_default_is_master_not_legacy_global`, `test_initiative_global_on_chat_off_is_off`, `test_initiative_emergency_env_overrides_chat`, `test_initiative_scheduler_ticks_when_chat_is_on` |
| F2 | character: `if not self_model_enabled(): return False` — product-AND | `self_model_enabled_for_chat` = только `resolve_module_capability("character")`: global default `flags.self_model_enabled` → CHAT override; env `MCA_SELF_MODEL_ENABLED` — `emergency_block` реестра | `test_character_global_off_chat_on_is_on`, `test_character_global_on...` (в adapters: CHAT OFF), `test_character_emergency_env_blocks_chat_on`, `test_character_usage_per_chat` |
| F3 | random: `random_source_enabled()` = env AND product; пул глушился | `random_source_enabled()` — env-only (живость пула); `random_source_enabled_for_chat` — только `module_enabled(module_id="random")` (global default `memory.random_enabled` → CHAT override, env — emergency) | `test_random_global_off_chat_on_is_on`, `test_random_chat_off_keeps_global_pool`, `test_random_emergency_env_blocks_chat_on`, `test_random_usage_per_chat` |
| F4 | тесты/мутации закрепляли запрещённую семантику | Инвертированы `test_initiative_*`, `test_character_global_*`, `test_random_global_*`; mutation №1 теперь восстанавливает product-AND и убивается | RED/GREEN + `mutations.json` (3/3 killed) |
| F5 | factcheck tool: глобальный `hot.get`, `active_tools()` без chat_id | `active_tools(..., factcheck_enabled=...)`; `active_tools_for_chat(chat_id, ...)`; `fact_check_tool_enabled_for_chat` = env/временная ось + `module_enabled("factcheck")`; Direct-пути (`direct_chat_service`) переведены на per-chat обёртку; readiness `_build_fact_check` — тот же резолвер | `test_factcheck_tool_path_per_chat`, focused Direct/handler tests |
| F6 | checkup readiness: глобальный `CHECKUP_KEY` | `_build_health` использует `feature_gates.module_enabled(chat_id, key=CHECKUP_KEY, default=...)`; readiness = effective_runtime | `test_checkup_readiness_per_chat` |
| F7 | transcribe DI только при глобальном ON → `UNHANDLED` после рестарта | `bot.py` подключает СУЩЕСТВУЮЩИЙ общий `voice_service` ВСЕГДА; per-chat гейт остаётся в handler. Новый сервис не поднимается (инстанс уже создан для медиа-ветки youtube) | `test_transcribe_handler_per_chat`, `test_voice_transcription_di_is_not_conditional` |
| F8 | stories: per-chat гейт до ACL → утечка бита чужого чата | `_require_scope_access` вызывается сразу после `X-Chat-Id` во всех 4 read-endpoint; гейт — после ACL. POST-контур уже проверял права | `test_stories_read_api_per_chat`, `test_stories_acl_precedes_per_chat_gate` |
| F9 | fail-closed при исключении резолвера не был зафиксирован | Решение явно: **fail-closed** (False), без fallback на глобальное значение. Резолвер in-memory/hot, исключение = дефект состояния; fallback скрыл бы потерю per-chat контекста. Записано в docstring и тесте | `test_module_enabled_fail_closed_on_resolver_error` |
| F10 | evidence: несуществующие пути, смешанные diff-цифры | `tests-summary.json` содержит 24 реальных focused-файла, точные SHA/цифры; RED/GREEN артефакты перегенерированы | `tests-summary.json`, `pytest-red-base.txt`, `pytest-green.txt/.xml` |

## 2. Семантика GLOBAL/CHAT

Реализована каноническая семантика **GLOBAL default → CHAT override**
(owner input §0.1/§2.1/§2.3.1; design §12.2/§12.5.1; plan §3.3;
`MAC-S2-TT-4`):

| GLOBAL | CHAT | Результат |
|---|---|---|
| ON | INHERIT | ON |
| ON | OFF | OFF |
| OFF | INHERIT | OFF |
| OFF | ON | **ON (только этот чат)** |

Продуктовый GLOBAL — наследуемый дефолт, а не запрет. `emergency_block`
(env-оси `MCA_INTENTS_ENABLED`, `MCA_SELF_MODEL_ENABLED`,
`MCA_RANDOM_SOURCE_ENABLED`, `MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED`,
`MCA_STORIES_VITRINA_ENABLED`) остаётся отдельной осью и перекрывает
`desired`, не подменяя сохранённый выбор.

Shared-сервисы: глобальный OFF больше не останавливает общий пул/модель/
планировщик; он выключает использование по INHERIT-чатам, а явный CHAT ON
исполняется в своём чате (owner §2.3: чатовый OFF запрещает потребление, а
не общий worker).

## 3. Изменённые файлы corrective-коммита

`b278a547` — 13 files, +514/−155:

- `services/initiative_observer.py`, `services/mca_gates.py` — F1/F2/F3;
- `services/chat_params.py` — аддитивный `global_value`/`global_source` у
  `resolve_param_capability` (владелец capability передаёт authoritative
  global; второго резолвера/приоритета нет);
- `services/feature_gates.py` — явный fail-closed (F9);
- `services/tool_schemas.py`, `services/direct_chat_service.py`,
  `services/capability_registry.py` — F5/F6;
- `bot.py` — F7;
- `web/api/stories.py` — F8;
- тесты: `test_mod_acl_ux_01_m21_adapters.py`,
  `test_mod_acl_ux_01_m21_gates.py`, `test_asap8_f5_module_truth.py`,
  `test_mca18_self_model_block_a_round1042.py` (их ожидания описывали
  отменённый product-AND).
- evidence: `evidence/m21/**`.

Запрещённые файлы не изменялись: `module_registry.py`, `permissions.py`,
`access.py`, prompt registry, VMQ QRNG, `cognitive_map.py`,
`config_cache.py`, `param_catalog.py`. DDL/миграций/новых флагов/second ACL
нет; stored values не переписываются.

## 4. Проверки

- **RED на базе `bca18c1e`:** обновлённые M2.1-тесты скопированы в чистый
  архив базы → **44 failed / 3 passed** (`pytest-red-base.txt`).
- **GREEN на кандидате:** 24 focused-файла → **476 passed, 0 failed, 0
  skipped** (`pytest-green.txt`, `pytest-green.xml`, `tests-summary.json`).
- **Мутации:** 3/3 killed (`mutations.txt`, `mutations.json`):
  1. восстановление product-AND в initiative emergency → убит
     `test_initiative_global_off_chat_on_is_on`;
  2. игнорирование chat override (global scope) → убит
     `test_character_global_off_chat_on_is_on`;
  3. игнорирование env `MCA_INTENTS_ENABLED` → убит
     `test_initiative_emergency_env_overrides_chat`.
- **Поведенческие тесты 12 модулей:** Direct/factcheck/search/web/
  transcribe/video_summary/media_download/checkup + stories/character/random/
  initiative — GLOBAL OFF+CHAT ON и GLOBAL ON+CHAT OFF; для shared —
  дополнительно emergency env.
- **Структурные guard'ы:** отсутствие второго резолвера/ACL
  (`test_no_second_resolver_or_acl`), отсутствие записи stored values
  (`test_adapter_does_not_rewrite_stored_values`).
- **Pre-existing failures базы** (воспроизведены на `bca18c1e`, вне M2.1):
  `test_initiative_coordination::test_act_on_opportunity_conflict_defers_to_intent`,
  `::test_evaluate_phase_precheck_blocks_before_llm`,
  `::test_t1_nostalgia_delegated_refusal_sends_nothing`,
  `::test_t5_every_text_send_site_passes_publish_guard`,
  `test_soul1_w5_observer_gates::test_initiative_writer_shares_core_style_and_persona`.

## 5. Конфигурация и ограничения

- Effective configuration: env-оси проверяются как emergency (тесты с
  `SimpleNamespace(MCA_INTENTS_ENABLED=False)` и `module_registry.env_enabled`);
  GLOBAL/CHAT — через реальный `chat_params`-кэш тестового чата; factory
  defaults не перетираются.
- `flags.initiative_observer_enabled` остаётся собственной осью тика
  наблюдателя (не master инициативы). Master карточки —
  `flags.initiative_enabled`; per-chat — `initiative.enabled`.
- `stories` manage-контур (`stories_manage_enabled`) остаётся глобальным:
  M2.1 закрывает read-контур, как записано в постановке.
- Live production probe не выполнялся (деплой вне задачи); production
  effective-state не заявляется.
- `VERIFIED` не заявляется: требуется независимое ревью.

## 6. Артефакты

- `evidence/m21/pytest-red-base.txt` — RED базы (44/3).
- `evidence/m21/pytest-green.txt` / `.xml` — GREEN кандидата (476).
- `evidence/m21/tests-summary.json` — машиночитаемая сводка с точными SHA,
  24 focused-файлами и diff-цифрами.
- `evidence/m21/mutations.txt` / `mutations.json` — 3 мутации, все killed.
- `evidence/m21/implementation.md` — этот файл.
