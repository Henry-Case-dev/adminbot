# UR-B — привязка доказательств (bookkeeping PM)

- Срез: `UR-B` «Tools и поиск: общий executor, Search-first, приватный публичный запрос, трасса источников».
- Замержено в `evol/impl`: ветка `ur/b-search` @ `5adaa21b` → merge `da6299e9`
  («merge: BGS-01 privacy veto removal (ur/b-search 5adaa21b) into evol/impl»).
- Владелец карты: `plans/features/unified-reply/requirements-map.json`. Эта запись — сводка привязки, а не самостоятельное доказательство.
- Локальный прогон: `tests/test_unified_reply_ur_b_search_first.py`,
  `tests/test_unified_reply_ur_b_no_topic_veto.py`,
  `tests/test_unified_reply_ur_b_review_fixes.py` — зелёные на текущем дереве `evol/impl @ 1cb76b62`.

## Что реально изменено merge `da6299e9`

| Файл | Δ | Смысл |
|---|---|---|
| `services/direct_execution.py` | +1091 | `run_tool_phase` (единый исполнитель), `ToolEvidence`, `build_search_query`, `_strip_sensitive`, честные статусы, трасса |
| `services/direct_l1.py` | +137 | ось `knowledge_origin`/`search_intent` в `L1Plan`, `normalize_search_intent`, `resolve_search_axis` |
| `services/direct_chat_service.py` | 3 строки | только докстринг политики (удалено упоминание privacy-вето) |
| `services/evidence_policy.py` | 22 | снятие содержательного privacy-вето (BGS-01) |
| `tests/test_unified_reply_ur_b_*.py` | +1273 | контракт оси, search-first, гигиена payload, честные статусы |

## Привязано `VERIFIED` (13 строк)

| Строка | Доказательство (файл::тесты) |
|---|---|
| `UR-03.2` | структурная проверка: единственный `class ToolRouter` (`services/tool_router.py`), `WebSearchAgent` в дереве отсутствует |
| `UR-06`, `UR-06.1` | `test_identical_schema_for_initiative_path`, `TestSearchAxisSchema` — одна схема для Direct/Initiative |
| `UR-06.2` | `test_open_world_without_intent_normalized_to_required`, `test_mixed_without_intent_normalized_to_required`, `test_missing_search_tool_required_is_unavailable` |
| `UR-06.3` | `test_chat_only_not_applicable_preserved`, `test_chat_only_joke_no_search`, `TestNoTopicVeto` |
| `UR-06.4` | `test_runtime_policy_and_user_forced_not_demoted`, `test_explicit_internet_request_makes_real_call`, `TestExplicitRequestForcesRequired` |
| `UR-07`, `UR-07.1` | `TestPayloadHygiene` (телефон/почта/t.me/id/`sk-`/`ghp_` вычищены, имя сохранено, весь чат не уходит, чистка идемпотентна) + `test_no_privacy_classifier_left_in_module`, `test_private_sounding_text_never_yields_privacy_blocked` |
| `UR-07.2` | `test_no_invented_sources`, `test_empty_result_honest`, `test_contradictory_results_not_evidence` |
| `UR-07.4` | `test_full_source_addressable_beyond_payload`, `test_orchestrator_evidence_is_addressable_and_bounded` |
| `UR-08`, `UR-08.1` | `test_trace_fields_and_emission_are_private_safe` (ровно 7 полей трассы, приватный текст и id не попадают) |
| `UR-10.4` | `test_whole_chat_is_not_sent` (`search_task` = исходный запрос), `test_orchestrator_evidence_is_addressable_and_bounded` (структурное усечение не рвёт слово) |

## Осталось `PENDING` (11 строк) и почему

| Строка | Причина |
|---|---|
| `UR-03` | `run_tool_phase` не подключён к живым маршрутам: `direct_chat_service.py:4777` (Direct) и `:12932` (Initiative) продолжают вызывать `_l1_tool_phase` → `run_adaptive_chain`/`run_simple_tools`. Единый tool-этап на двух режимах в проде не включён |
| `UR-RES-02` | то же: «ответ инициативы несёт настоящий вызов поиска» требует подключения исполнителя на инициативном маршруте |
| `UR-03.1` | права/состояние провайдеров до планирования (`direct_capabilities`) срезом не менялись; dedup/ошибки/время в одной `ToolEvidence` тестами не проверены |
| `UR-06.5` | SILENT/REACT покрыты (`test_silent_react_zero_tool_calls`), но «Observer не выполняет постоянный поиск по каждому окну» тестами не проверено |
| `UR-07.3` | дата источника и остановка adaptive при отсутствии прироста доказательств не проверены |
| `UR-07.5` | отсутствие добавочной LLM-«надзирателя» не проверено (проверено только отсутствие повторного вызова при reuse) |
| `UR-08.2` | `live_required=true` (preprod), размеченного набора и реального прогона нет |
| `UR-17.7`, `UR-17.8` | диалоговые сценарии требуют E2E/live (`UR-G`), юнит-тестов нет |
| `UR-BAN-01` | запрет поиска на реакцию/молчание покрыт, часть про Observer — нет |
| `UR-BAN-02` | отсутствие бесконечных tool-loop/retry и границы prompt тестами не проверены |

## Открытая находка (блокирует закрытие среза, не карту)

Ось `knowledge_origin`/`search_intent` **не запрашивается у модели**: имена полей встречаются
только в `services/direct_l1.py` и `services/direct_execution.py`, в каноне промпта L1
(`services/prompt_registry.py`) их нет — в отличие от ранее добавленного поля `recheck`,
для которого ревизия промпта зафиксирована (`prompt_registry.py:175-177`, `:2808-2809`).
Сам код это признаёт: `resolve_search_axis` — «пока канон промпта L1 не дополнен полями оси,
это единственный живой сигнал в проде».

Следствие: в живом ходе `search_intent` остаётся пустым, нормализация
`open_world|mixed → required` не срабатывает, а `run_tool_phase` никто не вызывает.
Срез доставил контракт, исполнитель и тесты, но не включил поведение.

Нужно решение координатора: либо подключение входит в `UR-A` (`_execute_turn`), либо
`UR-03`/`UR-RES-02`/`UR-06*` требуют отдельного Builder-шага (промпт-ревизия + замена
`_l1_tool_phase` на `run_tool_phase` в двух call-site).
