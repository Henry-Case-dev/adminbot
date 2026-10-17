# SOUL-1 / W4 — покрытие требований (SOUL-06 / SOUL-07 / SOUL-08 / SOUL-AMD.2.6)

Слайс: `W4` (Humor Craft + Few-Shot библиотека + Humor Feedback Loop + жанровые
рамки авторских текстов). Кандидат — рабочее дерево поверх
`c5900874a4d8319d1066a2a548a2450449eb8712` (коммитов нет, деплоя нет).

Легенда статусов:
`VERIFIED-BY-TEST` — покрыто Durability-тестами слайса и/или прогоном UI;
`PENDING-LIVE` — требует живых пользователей/чатов/канарейки (SOUL-08.12,
AMD.2.6 в части проводки снов/лора/историй).

Источники доказательств: `focused-tests.txt` (78 тестов слайса),
`perimeter.txt` (3864 passed, 0 failed), `parity-off.json`, `js-smoke.txt`
(11 JS-сторожей), `frozen-assets.txt` (замороженный фон/линза + LF),
`mutation-witness.json` (9/9 мутаций убито), `ui-report.json` (failures=0),
`api-fixture.json`, `shots/` (22 кадра), `shots_live/` (4 живых кадра),
`test-nodes.txt` (78 узлов).

## SOUL-06 — Humor Craft

| req_id | статус | доказательство |
|---|---|---|
| SOUL-06.0 | VERIFIED-BY-TEST | `test_gate_defaults_off_and_is_env_and_catalog`, `test_rendered_layer_lands_in_composer_once`, `test_probe_gives_measurable_layer_for_each_technique` (слой, ревизия, токены на каждый приём) |
| SOUL-06.1 | VERIFIED-BY-TEST | `test_each_technique_is_registered_factory_edition[absurd_escalation]`, заводской текст `humor.technique.absurd_escalation` (предпосылка → следствия → вывод) |
| SOUL-06.2 | VERIFIED-BY-TEST | то же для `literalism` + `test_no_repeated_templates_and_no_tool_call_names` (буквализм без шаблонов) |
| SOUL-06.3 | VERIFIED-BY-TEST | то же для `deadpan`; `test_short_extents_do_not_break_length_contract` (deadpan единственный уместный в one_word/micro) |
| SOUL-06.4 | VERIFIED-BY-TEST | то же для `bureaucratic_logic`; текст прямо запрещает однообразное ведомство (`test_technique_texts_never_prescribe_frequency_or_profanity`) |
| SOUL-06.5 | VERIFIED-BY-TEST | то же для `unexpected_analogy` (отдалённая область + конкретные детали) |
| SOUL-06.6 | VERIFIED-BY-TEST | `test_common_guard_is_registered_and_carries_the_criterion` (уместность/связность, не частота мата), `test_selection_requires_l1_advice_and_respects_serious_context`, `test_no_repeated_templates_and_no_tool_call_names` (`нет ты`/`классика жанра`), `test_negative_feedback_weakens_strategy_in_context` |
| SOUL-06.7 | VERIFIED-BY-TEST | `test_craft_off_keeps_core_and_marks_reason` (диагностическое выключение при живом Core), `test_probe_gives_measurable_layer_for_each_technique` (тест влияния приёмов), `test_zero_extra_llm_calls_on_normal_answer` (**ровно 1 вызов Writer**), `test_candidate_eval_is_bounded_and_off_by_default` + `test_candidate_eval_failure_is_honest_noop` (опциональная оценка ≤2 кандидата/≤1 вызов, default OFF) |

## SOUL-07 — Few-Shot библиотека

| req_id | статус | доказательство |
|---|---|---|
| SOUL-07.0 | VERIFIED-BY-TEST | `test_migration_creates_table_and_indexes` (единственная новая таблица v36), `test_starter_set_is_original_diverse_and_unapproved` (18 оригинальных, ≥4 техник), `test_crud_roundtrip_with_revision_guard` |
| SOUL-07.1 | VERIFIED-BY-TEST | `test_seed_is_idempotent_and_drafts_stay_unapproved` (черновики без владельческого одобрения), `test_crud_roundtrip_with_revision_guard` (создание/правка/ревизия/архив/удаление/одобрение), `test_write_rejects_pii_and_missing_fields`, `test_registry_block_is_registered_with_factory_text` |
| SOUL-07.2 | VERIFIED-BY-TEST | `test_selection_returns_only_owner_approved_globals`, `test_cross_chat_isolation_is_hard`, `test_global_chat_scope_is_not_returned_to_other_chats`, `test_leakage_guard_double_defence_on_selection`, `test_selection_respects_extent_fit_and_budget`, `test_selection_is_diverse_and_bounded`, `test_recency_penalty_prefers_less_recently_used`, `test_policy_chat_override_does_not_leak_to_other_chat`; **FIX-W4/F1:** `test_foreign_chat_approve_and_archive_are_forbidden` (чужой chat-scoped пример → 403 на approve/archive/update/delete), `test_own_chat_approve_and_archive_still_work`, `test_global_samples_are_editable_by_any_chat_admin` |
| SOUL-07.3 | VERIFIED-BY-TEST | `test_ab_assignment_is_deterministic_and_pins_a_version` (A/B версий), `test_technique_bonus_follows_l1_advice`, трасса «почему выбраны» — `examples/why` в `ui-report.json` и `why` в `api-fixture.json`; метки источников (`owner_manual`/`bot_suggested`/`verified_success`) и `approval=proposed` для сидов — `test_seed_is_idempotent_and_drafts_stay_unapproved` |

## SOUL-08 — Humor Feedback Loop внутри Experience

| req_id | статус | доказательство |
|---|---|---|
| SOUL-08.0 | VERIFIED-BY-TEST | `test_no_second_learning_contour_is_created` (нет своих таблиц/джобов; проход вызывается существующим review-джобом) |
| SOUL-08.1 | VERIFIED-BY-TEST | `test_no_second_learning_contour_is_created` (новые типы evidence: `signal_json.domain=humor`, `humor_fit` в MEASUREMENTS, `humor_instruction` в VALIDATION_KINDS, канонические правила `humor_weaken_*/humor_strengthen_*`) |
| SOUL-08.2 | VERIFIED-BY-TEST | `test_send_metadata_is_bounded_and_typed` (только закрытый набор полей, секреты/тексты отбрасываются), `test_capture_send_writes_bounded_episode` (эпизод без сырых текстов, `tgmsg_*`) |
| SOUL-08.3 | VERIFIED-BY-TEST | `test_scenario_1_metaphor_picked_up`, `test_parse_classification_is_strict`, `resolve_signal` (одобрение только с семантикой) |
| SOUL-08.4 | VERIFIED-BY-TEST | `test_scenario_1_metaphor_picked_up` (метафора ≠ совпадение слов: класс `metaphor_continuation` только по семантике + `metaphor_continued`) |
| SOUL-08.5 | VERIFIED-BY-TEST | `test_scenario_2_stop_request_weakens_only_in_context` (ослабление в чате, не глобально), `test_single_explicit_request_applies_immediately`, `test_weaken_lesson_changes_next_answer_selection` |
| SOUL-08.6 | VERIFIED-BY-TEST | `test_scenario_4_nobody_comments_is_unknown_not_failure`, `test_unknown_window_is_not_failure`, `test_telemetry_is_honest_without_data` |
| SOUL-08.7 | VERIFIED-BY-TEST | `test_scenario_5_group_talks_elsewhere_is_not_success`, `test_scenario_3_dramatic_reaction_without_joke_is_not_success`, `test_window_candidates_enforce_time_and_linkage` (`no_linkage`, `cross_chat`) |
| SOUL-08.8 | VERIFIED-BY-TEST | `test_window_pass_survives_evaluator_outage` (оценщик недоступен → контур честно unknown, беседа не блокируется), `test_parse_classification_is_strict`, `test_positive_signal_requires_semantics_or_owner`, bounded batch/таймаут в `mca_humor_feedback.classify_rows` |
| SOUL-08.9 | VERIFIED-BY-TEST | `test_small_n_single_user_and_topic_are_guarded`, `test_brigading_and_engagement_gaming_are_guarded`, `test_reverse_causality_and_window_are_guarded`, `test_low_confidence_participant_signals_stay_hypotheses`, `test_lessons_never_rewrite_core`, `test_scenario_6_two_chats_evaluate_differently`, `test_scenario_7_one_person_reactions_do_not_inflate_success` |
| SOUL-08.10 | VERIFIED-BY-TEST (эффект) / PENDING-LIVE (реальный чат) | `test_weaken_lesson_changes_next_answer_selection` (следующая сборка: `humor_context_penalty`, штраф примеров), `test_scenario_6_two_chats_evaluate_differently`; живые диалоги — `PENDING-LIVE` (SOUL-08.12) |
| SOUL-08.11 | VERIFIED-BY-TEST | `test_decay_fades_preferences`, `test_owner_controls_pause_and_reset_keep_data`, `test_telemetry_is_honest_without_data`, **FIX-W4/F2:** `test_telemetry_counts_captured_sends` (`sends` = факт отправок, по чату и глобально), bounded retention (существующие `feedback/episode_retention_days`), видимые счётчики в «Обучении» |
| SOUL-08.12 | PENDING-LIVE | Семь сценариев реализованы как детерминированные симуляции (`test_scenario_1…7`) + честные live-маркеры в `SCENARIO_LIVE_MARKERS` (видны в UI). Живая атрибуция и влияние на выбор в реальных чатах — после деплоя/канарейки |

## SOUL-AMD.2.6 — Авторские тексты (сны/ностальгия/лор/истории)

| req_id | статус | доказательство |
|---|---|---|
| SOUL-AMD.2.6 | VERIFIED-BY-TEST (жанровые рамки + путь «Ностальгия») / PENDING (проводка снов, лора, историй) | `test_genre_blocks_are_registered_factory_editions`, `test_composer_off_returns_legacy_canon_byte_for_byte` (паритет OFF), `test_composer_on_adds_core_and_genre_rules` (Core + жанровая рамка), `test_nostalgia_path_uses_composed_system` (реальная публикация), `test_nostalgia_path_parity_when_composer_off`, `test_wired_and_pending_paths_are_visible_in_registry_notes` (честная граница видна в реестре) |

## FIX-W4 — закрытие блокеров REVIEW-W4 (F1/F2/F3 + заметка §6.1)

| Находка | Правка | Проверка (моё исполнение) |
|---|---|---|
| **F1** (SOUL-07.2) approve/archive не проверяли принадлежность чату | `web/api/speech.py`: единый `_guard_sample_chat_scope(...)` в approve/archive/update/delete (одна проверка на все мутации) | RED до правки: чужой chat-scoped пример → **200** (`fix-repro-red.txt`); GREEN: 403, данные не меняются, свой чат работает (`test_soul1_w4_examples_scope.py`) |
| **F2** (SOUL-08.11) `telemetry().sends` всегда 0 (битый биндинг) | `services/mca_humor_feedback.py`: `(SEND_TASK_TYPE,) + args` + WARNING вместо тихого `except` | RED: `sends=0` при записанном эпизоде; GREEN: `sends=1` по чату и глобально (`test_telemetry_counts_captured_sends`, проба `repro_f2.py`) |
| **F3** хаб объявлял «Примеры/Обучение» как не поставленные | `web/api/speech.py`: `_examples_card()`/`_learning_card()` — фактическое состояние и счётчики, честная причина при недоступной базе | payload настоящего обработчика: `карточек: 20 · эталонов: 4 · черновиков: 16` (было `slaйс W4`/`not_implemented`), живой кадр хаба `shots_live/fix_hub_1024.png` |
| Заметка §6.1 (выжившая мутация M11) | `tests/test_soul1_w4_humor_feedback.py`: точный кортеж `SEND_FIELDS` + точный набор ключей результата запинован | тест падает при расширении набора (мутация M11 убита) |

Живой прогон окна после правок (фикстура слайса): `sends: 1` при
`signals={metaphor_continuation: 1}` — противоречие из F2 закрыто и в evidence
(`evidence/w4/api-fixture.json`).

## Что осталось живым (честно)1. **SOUL-08.12** — семь сценариев на реальных людях и двух живых чатах
   (влияние на выбор примеров в следующем ответе). Симуляции и маркеры готовы.
2. **SOUL-AMD.2.6 (частично)** — проводка путей снов/глубокого сна/лора/историй:
   жанровые рамки зарегистрированы, хелпер готов, публикующий путь «Ностальгия»
   проведён; остальные пути — следующий слайс (отмечено в `note` блоков реестра).
3. **Канареечная проверка осей** — `HUMOR_CRAFT_ENABLED` /
   `HUMOR_LIBRARY_ENABLED` / `HUMOR_FEEDBACK_ENABLED` включаются владельцем
   после деплоя; по умолчанию все OFF (паритет подтверждён `parity-off.json`).
