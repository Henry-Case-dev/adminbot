# A7 `decision-making-round1026` — Threat / Failure Analysis (R3-артефакт, T-3661)

- **Risk:** R3 (spec §13 / ADR-1026-20 D12). Формат: **threat → mechanism → code → test**.
- Все ссылки на тесты — `tests/test_decision_making_round1026.py` (89 сценариев),
  если не указано иное. Полный регресс: **9392 passed / 0 failed**.
- **Ссылки на код** указывают на **фактическую точку исполнения** (`handle()`-ветку
  либо чистую функцию), а не на функции, которые только строят/логируют причину
  (корректировка F-1/F-7 ревизии T-3663).

| # | Threat | Mechanism (как предотвращено) | Code (фактическая точка) | Named test |
|---|---|---|---|---|
| 1 | **Ложное молчание съедает реальную задачу** | Приоритет §3.3: explicit_request/question/`expects_tool_result`/статья-ответ/сработавший пре-гейт разрешаются **ветками 1–4** политики **до** любой ветки silent (7–9); silent только для тривиальных классов/не-адресованных | `_decision_pre_action:801` (ветки 1–4 раньше 7–9); `_decision_message_class:772`; контекст `_decision_context:1065` | `TestPolicy::test_short_real_question_replies`, `test_explicit_request_replies`, `test_expects_tool_result_replies`, `test_expects_tool_result_beats_ack_silence`, `test_bare_question_punctuation_replies`, `TestAdversarial::test_silence_never_eats_task`, `test_explicit_and_question_never_silent` |
| 2 | **Ложный ответ/лишний текстовый вызов на тривиальном** | `silent`/`react` — короткое замыкание **в `handle()`**: `return` до сборки system prompt, до Stage-1/Stage-2 и до отправки | `handle():1258–1286` (Phase P); `return` на silent `:1274–1277`, на react `:1279–1286` | `TestHandleOrder::test_silent_no_verbalizer_no_send`, `test_react_no_verbalizer_target_trigger`, `test_await_count_zero_on_silent_path` |
| 3 | **Вербализатор тратится на silent/react** | Возврат из `handle()` до гейта Stage-2 (`:1443–1452`); spy: `_synthesize_direct_answer` не вызван, `llm.generate.await_count == 0` (без 3-го вызова) | `handle():1274–1286` (короткое замыкание); гейт Stage-2 `:1443–1452` | `TestHandleOrder::test_silent_no_verbalizer_no_send`, `test_await_count_zero_on_silent_path`, `test_react_no_verbalizer_target_trigger` |
| 4 | **Служебный JSON/объект решения утекает в чат** | `CoordinatorDecision` — внутренний объект без `to_json`; Stage-1/Stage-2 JSON не меняются; в чат уходит только текст/реакция | `CoordinatorDecision:591`; Stage-контракты не тронуты | `TestDecisionContract::test_decision_is_internal_not_json`, `test_stage_json_contracts_unchanged` |
| 5 | **Случайность просачивается в выбор действия** | Политика — чистые детерминированные функции; `random` отсутствует; реакция фиксированная 🗿 | `_decision_pre_action:801`; `REACTION_MOAI:477` | `TestPolicy::test_deterministic_no_randomness`, `test_policy_has_no_random` |
| 6 | **Бот становится полностью пассивным** | `silent` не универсален: задачи/вопросы всегда отвечают; не-адресованное молчит только при `IGNORE_TRIVIAL`; в ЛС ветка «не адресовано» не включается | `_decision_pre_action:801` (ветки 5–10; `not context.addressed and not context.is_private`) | `TestAdversarial::test_robot_not_fully_passive`, `TestPolicy::test_acknowledgement_ignore_off_reply_or_react`, `test_private_overrides_not_addressed` |
| 7 | **Контекст §47 прочитан неверно → неправильное действие** | Консервативный `addressed` (при отсутствии явного сигнала — True; в ЛС — всегда True); изображение — через `message_media_type`; статья/не-фото медиа → `expects_tool_result`; fail-open контекст → reply | `_decision_addressed:1042`, `_decision_context:1065`, `_decision_pre_action:801` (ветка 4) | `TestDecisionContextFields::test_article_sets_expects_tool_result`, `test_document_result_sets_expects_tool_result`, `test_photo_is_image_not_tool_result`, `test_private_marks_addressed`, `test_group_reply_to_other_not_addressed`; `TestHandleOrder::test_context_image_laugh_reacts`, `test_context_question_after_image_replies`, `test_not_addressed_silent`, `test_private_chat_reply_to_other_still_replies` |
| 8 | **Kill-switch не работает → нет отката** | `DIRECT_DECISION_MAKING_ENABLED` env-only per-call; OFF → Phase P не строится, `action` ∈ {tool,reply}, логи A1-формата; `reason_code=disabled` фиксируется (F-5) | `decision_making_enabled:635`; `handle():1258–1264` | `TestBounds::test_kill_switch_default_on`, `TestHandleOrder::test_off_killswitch_parity_reply`, `test_off_killswitch_reason_disabled` |
| 9 | **Реакция ставится не на то сообщение** | `target_message_id` = id trigger-сообщения пользователя (не `reply_to_id`); исполнение — reuse `react_moai` | `handle():1279–1286` (`react_moai(bot, chat_id, pre_target)`); `_decision_pre_action` возвращает `target_message_id` | `TestHandleOrder::test_react_no_verbalizer_target_trigger` |
| 10 | **Недоступный инструмент → молчание/выдуманный успех** | Runtime: деградация/провал tool-цикла идёт по reply-ветке `handle()` — деградация логируется (`:1411`), Stage-2 пропускается (`:1445`), непустой частичный финал отправляется (`:1460`,`:1481`), пустой → safety-net 🗿 (`:1467`), а ошибки → текст (`:1505`,`:1519`). `_coordinator_reason` только **обогащает** причину (`tool_unavailable`), не управляет ветвлением | `handle():1411–1528` (runtime); `_coordinator_reason:720`, `build_coordinator_decision:736` (reason) | `TestHandleOrder::test_tool_degraded_sends_reply_not_silence`, `TestPhaseT::test_tool_unavailable_reason_and_reply`, `test_degraded_tool_reason_unavailable`, `TestAdversarial::test_tool_unavailable_is_reply_not_silence` |
| 11 | **Регрессия настроек/каталога (лишние параметры, сломанный F8)** | Ровно 3 параметра + 1 группа; Δ ровно +3/+1; F8 `--check` OK; global/local через `get_chat_param` | `param_catalog.py:359,856–865,2168–2170`; `settings.py:1407–1412`; `_decision_toggles:1112` | `TestSettings::test_exactly_three_params_and_one_group`, `test_three_params_in_catalog`, `test_toggles_global_resolution`, `test_toggles_local_override`; `TestBounds::test_counts_sanctioned` |
| 12 | **Утечка приватного контента в логи (R17)** | Логи решения — только enum/id/числа; текст сообщений не пишется | `_log_decision_short_circuit:909`, `_log_coordinator_decision:872` | `TestReasonAndR17::test_logs_r17_safe`, `test_closed_vocabulary` |
| 13 | **Двойное молчание с `CHAT_SILENCE_*`** | Троттлинг/кулдаун-стак — барьер **до** Phase P; A7 работает только для допущенных сообщений | `handle()` (throttle/CB до Phase P, `:1146–1193`) | `TestHandleOrder::test_throttle_runs_before_decision` |
| 14 | **Новый механизм реакции / вызов `setMessageReaction` (граница A8)** | A7 не вызывает `set_message_reaction`; reuse существующего `react_moai` | `direct_chat_service.py` (grep: 0 вхождений) | `TestBounds::test_no_set_message_reaction_direct_call` |
| 15 | **Ошибка/пустой ответ LLM → молчание вместо честной ошибки** | Существующий safety-net не сломан: `LLMBadResponseError` → 🗿 (не текст-заглушка), `LLMError`/unexpected → фраза `CHAT_ERROR_PHRASES` (текст), не тишина | `handle():1377–1380` (empty→🗿), `:1505–1517`, `:1519–1528` | `TestHandleOrder` (reply-ветки) + A1-регресс `tests/test_direct_chat.py` |

## Покрытие ревизии T-3663 (F-1…F-9)

- **F-1:** end-to-end `handle()`-тесты tool-пути и degraded-tool добавлены
  (`TestHandleOrder::test_tool_path_runs_tools_then_final_action`,
  `test_tool_degraded_sends_reply_not_silence`); 2-вызовность измерена в
  `test_await_count_two_on_tool_path` (та же функция, что и в A1, но в A7-файле).
- **F-2:** §47-поля `reply_to_is_article`/`is_private`/`expects_tool_result`
  реально вычисляются (`_decision_context:1065`) и читаются политикой
  (`_decision_pre_action:801`, ветка 4 / ветка 8).
- **F-3:** `?`/`???`/`?!` → `question` (`_decision_message_class:772`,
  `_QUESTION_PUNCT_RE`).
- **F-5:** OFF kill-switch → `reason_code=disabled` (`handle():1258–1263`).

## Остаточные риски / не покрыто

- Недоступность реакции в конкретном чате (альтернатива/отказ) — **A8** (§41); A7
  полагается на fail-silently `react_moai` (эффект = молчание, без длинного текста).
- `bot_replied_recently` трактуется как «пользователь ответил на сообщение бота»
  (reply-ветка §45, `bot_replied_recently=reply_to_bot`); более тонкая детекция
  «продолжение не нужно» — предмет A8/A9. Отдельного хранилища нет (ADR D8).
- `expects_tool_result` до LLM — эвристика (статья/не-фото медиа в ответе на
  сообщение бота); точный `tool_trace`-сигнал действует после LLM (Фаза T).
