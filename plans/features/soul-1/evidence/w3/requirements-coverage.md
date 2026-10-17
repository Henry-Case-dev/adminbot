# SOUL-1 / W3 — покрытие требований слайса (evidence map)

- **Lane:** W3-STYLE (Speech Style Policy + one_word/micro + антизалипинание).
- **Кандидат:** рабочее дерево `C:\Code\Python\adminbot` (без коммита; deploy не выполнялся).
- **Карты:** `requirements-map.json` (33 строки W3) + `requirements-map-amendment.json`
  (7 строк W3). Карты не редактировались (владелец — PM).
- **Артефакты:** `style-payload-demo.txt`, `parity-off.txt`, `focused-suites.txt`,
  `catalog-delta-decision.txt`, `cost-measurement.txt`, `style-contract-demo.txt`.
- **Отчёт:** `plans/features/soul-1/w3-style-report.md`.

Статусы ниже — самодекларация Builder; финальный статус ставит Reviewer/PM в карте.

| req_id | Статус | Где доказательство |
|---|---|---|
| SOUL-05.0 | COVERED | раздел покрыт под-строками 05.1–05.7 (таблица ниже) |
| SOUL-05.1 | COVERED | `direct_l1.COMIC_STRATEGIES:66`, `L1Plan.comic_strategy:133`, нормализация `:280`, `ResponsePlan.comic_strategy` (`response_extent.py:98`), совет в `build_l2_plan_block:760`; тест `test_comic_strategy_is_one_optional_advice_field` |
| SOUL-05.2 | COVERED (unit/integration) + `LIVE_UNVERIFIED` (live) | `to_response_plan:148` переносит `one_word` значением; блок `_EXTENT_BLOCKS["one_word"]`; тесты `test_one_word_reaches_payload_as_exactly_one_word`, `test_one_word_and_micro_have_their_own_blocks`; payload-демо §2 |
| SOUL-05.3 | COVERED (unit/integration) + `LIVE_UNVERIFIED` | `EXTENTS:41` содержит оба extent; `MICRO_WORD_RANGE:51`; тесты `test_micro_has_no_one_word_cap`, `test_micro_answer_is_not_collapsed_to_one_word` |
| SOUL-05.4 | COVERED | `test_explicit_user_length_limit_beats_comic_expansion`, `test_long_technical_request_is_not_truncated_by_old_cap`, `test_micro_far_overflow_is_observable_conflict_without_truncation` |
| SOUL-05.5 | COVERED (unit) + `LIVE_UNVERIFIED` | `check_extent:650`, `lexical_words:570`, `_one_word_tail_trim:596`; тесты `test_one_word_accepts_exactly_one_lexical_word`, `test_one_word_rejects_second_word_without_truncating`, `test_one_word_minimal_local_repair_of_service_tail`, `test_one_word_conflict_with_protected_content` |
| SOUL-05.6 | COVERED (payload-контур) + `LIVE_UNVERIFIED` | `test_trailing_period_removed_from_real_payload_url_intact`, `test_ten_plus_heterogeneous_inputs_on_delivery_contour`; демо §2 (`Да.` → payload `Да`, 1 лексическое слово) |
| SOUL-05.7 | PARTIAL | цепочка «один характер, несколько манер» проверена на одном слове/паре фраз/абзаце/технике (тесты + демо); SILENT/REACT и tool-result — вне diff (проверяются W5/live) |
| SOUL-09.0 | COVERED | модуль `style_policy` раздел 6 (`record_bot_output:1704`, `detect_repetition:1723`); 18 тестов `test_soul1_style_repetition.py` |
| SOUL-09.1 | COVERED | скользящее окно n-грамм (TTL/cap/изоляция чатов), цитаты и короткие привычки не наказываются: `test_sliding_window_sees_own_recent_phrases`, `test_ttl_expiry_ignores_old_phrases`, `test_short_habitual_phrase_is_not_punished`, `test_protected_repeat_is_not_touched` |
| SOUL-09.2 | COVERED | локальная замена до генерации (`_local_repetition_repair`), отсутствие лишней генерации (`test_repeat_does_not_trigger_extra_generation`), capped/TTL/архив ban-list (`test_dynamic_ban_list_is_capped_with_archive_and_ttl`), без имён/секретов (`test_ban_list_rejects_personal_names_and_secrets`) |
| SOUL-09.3 | NOT-IN-DIFF (сохранено) | `/style`, chat-scoped и отношения не изменялись; ядро не отключается (hard-правила живут в отдельном документе и не читают scoped-слой: тест `test_only_owner_api_writes_rules_and_no_other_layer_mutates_them`) |
| SOUL-16.0 | COVERED | отдельная сущность `style.policy` (документ + `style_policy_view`), не смешана с overrides/biography/extent/анти-клише; hard-правила исполняются программно (`StylePolicyValidator`) |
| SOUL-16.P1 | COVERED | разделение зафиксировано в шапке модуля и в `RULE_KIND_SPECS`; hint слоя 10 — короткий, исполнение — детерминированное |
| SOUL-16.1.1 | COVERED | `StylePolicyValidator:1537`, исходы `pass/repaired/exempted/conflict/failed/denied`; `test_hard_rule_is_executed_and_soft_is_writer_instruction_only`, `test_conflict_strategies_are_explicit` |
| SOUL-16.1.2 | COVERED | soft → `not_applicable:soft_habit_writer_only` + отдельные формулировки hint: `test_hint_carries_hard_and_soft_wording_separately` |
| SOUL-16.1.3 | COVERED | `CONTEXT_PACKS`/`rule_applies:703`, глобальный default + per-chat override + пакеты; `test_context_packs_are_separate`, `test_effective_policy_merges_chat_over_global_without_leakage` |
| SOUL-16.1.4 | COVERED | поля записи (тест `test_rule_record_has_every_required_field`), единый документ + витрина `style_policy_view:2197` + блок реестра `style.policy.hint` (без десятков `prompts.*`) |
| SOUL-16.1.5 | COVERED | `PRESET_SPECS:174` (5 шаблонов), комбинирование/свой профиль, ревизии/история в `save_policy_document:2088`; произвольный текст владельца — только soft-инструкция (кодовое исполнение чужого regex отсутствует: params типизированы) |
| SOUL-16.2.1 | COVERED (движок) + W6 (редактор) | классы `«» „“ “” " '`, апостроф/дюйм/литералы: `test_quotation_marks_unicode_classes_are_removed_safely`, `test_apostrophe_and_technical_literals_are_not_quotes`; выбор классов владельцем — параметр `classes` (UI — W6) |
| SOUL-16.2.2 | COVERED | hint требует переформулировки у Writer; валидатор правит только одиночные кавычки, многословные → conflict: `test_multiword_quote_is_not_blindly_removed_and_not_declared_pass` |
| SOUL-16.2.3 | COVERED | политика исключений + `exempted: protected_verbatim` / `conflict: owner_rule_vs_verbatim`; режим `deny_incompatible` честно блокирует: `test_exempt_protected_exempts_real_verbatim_content`, `test_denied_is_blocking_and_styled_false` |
| SOUL-16.2.4 | COVERED | пример иронии: `Ну это «гениальная» идея` → `Ну это гениальная идея` c `risk=irony_may_be_lost`; неудачный смысловой вариант не объявляется равноценным (многословные → conflict) |
| SOUL-16.3.1 | COVERED | `_apply_trailing_period` (последний содержательный знак, Unicode-пробелы/невидимые, entities); `test_trailing_period_message_final_only` |
| SOUL-16.3.2 | COVERED | `Ну да, логично.` → `Ну да, логично`; `Да, конечно. Вот почему` без изменений; one_word/micro независимы |
| SOUL-16.3.3 | COVERED | сегментация `segment:1048` (code/json/url/version/ellipsis/markup/entities/verbatim); `test_protected_spans_are_never_damaged_by_period_rule`, `test_ellipsis_is_separately_configurable` |
| SOUL-16.3.4 | COVERED | `test_no_service_tail_or_extra_whitespace_after_repair`; payload-демо §1 (post-sanitize payload, URL/версия целы); message_id/ссылки/сущности не меняются (правка только текста до сериализации) |
| SOUL-16.4.1 | COVERED | резолв до Writer (`resolve_style_policy_ref` в композере), короткий hint (≤400 симв., токены), один проход с фиксированным порядком, идемпотентность: `test_pass_is_idempotent`, `test_hint_is_bounded_and_carries_only_active_rules` |
| SOUL-16.4.2 | COVERED | `PRECEDENCE:109`; owner-hard не обходится входящим сообщением: `test_owner_hard_rule_is_not_bypassed_by_incoming_user_message`; конфликт диагностируется (`conflict`/`denied`/`task_precedence`) |
| SOUL-16.4.3 | COVERED | один владелец правил и один writer (`test_only_owner_api_writes_rules_and_no_other_layer_mutates_them`); Experience не включает глобальный запрет (ban-list ≠ правило) |
| SOUL-16.4.4 | PARTIAL | машинные стадии/структурированный вывод не получают правил (`test_machine_stage_gets_no_form_rules`, `test_machine_and_structured_outputs_are_untouched`); eligibility для финального Factcheck/редакционной Summary не подключена в этом diff (см. отчёт «Не выполнено в W3») |
| SOUL-16.4.5 | COVERED | 0 LLM-вызовов на нарушение (`test_zero_llm_calls_on_style_violations`), максимум 1 bounded ремонт по явному callback (`test_bounded_semantic_repair_is_at_most_one_and_only_on_conflict`), замеры в `cost-measurement.txt` |
| SOUL-16.5.3 | PARTIAL + `LIVE_UNVERIFIED` | 12 разнородных входов через Direct-delivery-контур (`test_ten_plus_heterogeneous_inputs_on_delivery_contour`, демо §3) + инициативный writer (`test_initiative_writer_uses_the_same_pass`); tool-backed ответ на тестовом контуре — покрыт частично (общий проход), реальная отправка в рабочий Telegram-чат не выполнялась (нет разрешения владельца/деплоя) |
| SOUL-AMD.1.6 | COVERED (unit/integration) + `LIVE_UNVERIFIED` | два разных режима без маппинга: `test_extents_are_distinct_and_no_silent_collapse`, `test_one_word_and_micro_have_their_own_blocks`; UI-часть — W6 |
| SOUL-AMD.1.7 | COVERED | соблюдение проверяется детерминированно без регенерации; ссылки/код/цитаты не ломаются: `test_protected_content_is_not_damaged_by_one_word`, `test_no_extra_llm_call_on_delivery_contour` |
| SOUL-AMD.2.4 | NOT-IN-DIFF (Core-проводка) | публичный Factcheck идёт через Core/жанровый слой — работа профилей композера (W2), не этого diff; со стороны формы подготовлен пакет `editorial` и защита источников (`test_editorial_output_keeps_sources_untouched`) |
| SOUL-AMD.2.5 | NOT-IN-DIFF (Core-проводка) | публичный Summary — тот же случай: пакет `editorial`/`channel_text_only` (W2-профили), в W3 — только правила формы и сохранность ссылок |
| SOUL-AMD.2.7 | PARTIAL | ответы на инструменты идут тем же проходом Direct (`apply_style_policy` в `_handle_turn`), tool evidence не изменяется (проход не читает user-часть); публичное сообщение о неудаче действия — вне diff (W10) |
| SOUL-AMD.2.9 | NOT-IN-DIFF (Core-проводка) | «нет сухой ассистентской речи» в Factcheck/Summary — жанровый слой/Core (W2/W4), не форма |
| SOUL-AMD.3.5 | COVERED | самостоятельный управляемый слой, строгие правила детерминированы, URL/цитаты/код/машинные данные защищены, применяется к Direct + Initiative (включая fallback-текст, если он идёт тем же проходом): `test_initiative_writer_uses_the_same_pass` |
