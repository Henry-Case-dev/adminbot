# UR-A — один движок хода (Direct + Initiative): сдача Builder

- **Срез:** `UR-A` (Contract §2.1/§2.4/§6, checkpoint-1: контракты сфризены).
- **Ветка:** `ur/a-turn-engine` от `1cb76b62` (`evol/impl`).
- **Кандидат:** см. HEAD ветки на момент сдачи (коммиты `f0214f1d`, `2c10bbcc`,
  `72a78067`, `1c2e03bc` + evidence-коммит).
- **Проверено на:** Windows, локальный `pytest`, фейки `tests/test_direct_chat.py`.
- Статус строк карты (`UR-RES-01`, `UR-01..UR-01.6`, `UR-02..UR-02.4`) — **не
  VERIFIED Builder'ом**: это делает Reviewer после независимой проверки; здесь
  только кандидат и наблюдаемые доказательства.

## Что сделано

1. `services/turn_types.py` (новый, контракт-модуль без логики исполнения):
   `TurnRequest` + ссылочные типы (`ReplyParentRef`, `AddresseeRef`,
   `OpportunityRef`, `SlotBudgetMeta`, `ToolStateSnapshot`, `DeliveryPolicy`),
   `TurnType`, `TurnPolicy`, неизменяемая таблица `TURN_POLICIES`,
   `resolve_turn_type`/`turn_policy`. Датаклассы §2.2 (`ContextSelection`) и
   §2.3 (`ToolEvidence`) **не дублируются**: они уже определены владельцами
   `direct_context_composer.py` (UR-C) и `direct_execution.py` (UR-B) — карта
   соответствия в docstring модуля.
2. `services/direct_l1.py`: трасса хода `record_turn_trace/get_turn_trace/
   last_turn_request/reset_turn_trace` (bounded, process-local, без текстов в
   БД/лог) — запись несёт сам объект `TurnRequest` и резолв политики.
3. `services/direct_chat_service.py`:
   - `_resolve_turn_slot_meta` — ОДИН резолв permission-ключа, слота и бюджета
     L1 (`authorize_l1_call` + `resolve_l1_model` + `resolve_l1_context_budget`)
     на оба триггера (UR-02.1);
   - `_resolve_turn_tool_state` — ОДИН резолв фактических capabilities/allowlist
     (UR-01.5/UR-02.3);
   - `_build_turn_request` — единственный конструктор `TurnRequest` для обоих
     входов (+ `_turn_aliases_snapshot`, `_build_reply_parent_ref`);
   - `_execute_turn(req, ...)` — единственный исполнитель планирующей стадии:
     резолв типа хода/политики, запись трассы, ladder слот→main, bounded repair
     невалидного JSON, retry без temperature, учёт usage, `L1_PLAN`-событие
     (теперь и для инициативы, с `resolved`-инструментами), диагностика с
     `trigger_type/plan_schema/slot_policy/repair_policy/available_capabilities`,
     durable `plan_meta`;
   - `_plan_direct_l1` и `plan_initiative_decision` — только адаптеры: сборка
     контекста своего триггера + `TurnRequest` + общий исполнитель.

## Удалено

- Дублирующий L1-код прямого хода (собственный `_record_llm_call`, ladder,
  repair, temperature-retry, usage, `emit_l1_plan_event`, `record_l1_diagnostics`,
  `_attach_l1_plan_meta`) — 7 786 символов, одна копия осталась в `_execute_turn`.
- Прямой `self.llm.generate(step="l1_planner")` из `plan_initiative_decision` и
  `build_l1_context(..., capabilities=())` — «облегчённого» инициативного L1 и
  пустого списка прав больше нет (grep-assert в тесте).
- Отдельный `record_l1_diagnostics(source="initiative_l1", ...)` — заменён общей
  диагностикой исполнителя.

## Гарантируемое равенство и чем доказано

| Требование | Гарантия | Тест |
|---|---|---|
| UR-02/02.1 | слот (`l1_slot`/`main`), модель, бюджет и источник бюджета совпадают на обеих трассах | `test_slot_schema_and_repair_resolution_equal_on_both_traces` |
| UR-02.2 | схема плана, repair-политика, temperature, учёт usage — одна таблица и один код | `test_turn_policy_is_identical_for_both_triggers`, `test_invalid_json_repair_route_is_shared`, `test_usage_is_accounted_on_both_traces` |
| UR-02.3 | инициатива получает те же непустые capabilities, что прямой ход при равных флагах | `test_initiative_receives_real_capabilities`, `test_no_empty_capabilities_shortcut_left_in_engine_source` |
| UR-RES-01 | обе трассы исполняются одной функцией | `test_both_traces_execute_through_single_turn_engine` |
| UR-01..01.4, 01.6 | трасса несёт `TurnRequest`: полный текст (900+ символов), message_id, спикер, адресат, reply-parent, повод, права, слот, доставка | `test_trace_carries_turn_request_with_full_source_text`, `test_initiative_trace_carries_opportunity_and_addressee` |
| UR-01.1 | тип хода различает direct/initiative и резолвится одинаково | `test_same_input_resolves_same_turn_type` |
| Регресс | SILENT/REACT и явная просьба поиска не изменились | `test_silent_and_react_survive_single_engine`, `test_explicit_search_request_resolves_same_tools` |
| Право говорить | блок политики ключей: инициатива → `None` (SILENT), прямое обращение → проброс в sandbox-путь | `test_policy_block_keeps_initiative_silent_and_direct_raising` |

## Мутации (проверено, откатано)

- `capabilities=list(...)` → `capabilities=()` в инициативном адаптере:
  падают `test_no_empty_capabilities_shortcut_left_in_engine_source` и
  `test_initiative_receives_real_capabilities` (2 failed).
- Удаление `_l1.record_turn_trace(...)` из исполнителя: падают 4 теста трассы,
  включая равенство схемы/repair (4 failed).

## Прогоны

- `pytest tests/test_ur_turn_engine.py -q` → **15 passed**.
- `pytest tests/test_ur_turn_engine.py tests/test_direct_chat*.py -q` → **327 passed**.
- UR-A-смежные: `test_asap7_direct_l1`, `test_direct_l1_l1d_contract`,
  `test_direct_l1_corrective_r1`, `test_asap_fc_voice_l1_decision_profile`,
  `test_er08_limits_context`, `test_asap8_f6_initiative`,
  `test_asap8_v63_b01_initiative_observer`, `test_asap8_initreply_binding`,
  `test_initiative_delivery_telemetry`, `test_initiative_coordination`,
  `test_ur_context_selection`, `test_ur_bot_output_history`,
  `test_unified_reply_ur_b_*`, `test_soul1_composer_parity_off`,
  `test_soul1_machine_profile_no_core`, `test_asap3_identity_aliases`,
  `test_asap_speech_i_matrix` → **486 passed, 3 failed**.
- Широкий прогон `pytest tests -k "direct or initiative or l1_planner or turn_engine"`
  → **1235 passed, 9 failed** (все — известные/предсуществующие, см. ниже).

## Известные предсуществующие падения (проверены на чистом `1cb76b62`)

- `tests/test_initiative_coordination.py::test_act_on_opportunity_conflict_defers_to_intent`,
  `::test_evaluate_phase_precheck_blocks_before_llm`,
  `::test_t1_nostalgia_delegated_refusal_sends_nothing` — те же 3 падения на базе
  (порядок claim/publish-guard, к L1-движку отношения нет).
- `tests/test_direct_fallback_recompose_asap32.py` — 5 падений на базе
  (`generate_chat`/fallback-recompose, вне UR-A).
- `test_initiative_coordination.py::test_t4_diagnostics_publish_mode_is_coordinated`
  падает только в широком `-k`-прогоне (`aiosqlite: no active connection`),
  отдельно и в своём файле — passed: флейк окружения.

## Что НЕ доказано в этом срезе

- Живая прод-трасса (реальные модели/чаты) — не запускалась; проверка уровня
  Telegram не требуется этим срезом (контракт UX не менялся).
- `delivery`/recheck-поведение инициативы не переписывалось — его покрывают
  существующие интеграционные тесты `test_initiative_coordination`.
- Латентность/стоимость: инициатива теперь использует резолв слота (при
  настроенном dedicated-слоте — другой транспорт) и общий repair-маршрут; это
  требование UR-02, но фактический выбор модели в проде нужно увидеть в
  `get_l1_diagnostics`/`L1_PLAN` при следующем релизе.
