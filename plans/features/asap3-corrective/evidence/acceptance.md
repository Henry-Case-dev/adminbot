# ASAP 3 Corrective — сводная приёмка §8 / §10

Lane: `ASAP3-ACCEPT` · 23.10.2026 · только тесты и документы, реализация не переписывалась.
Источник: `plans/features/asap3-corrective/source-2026-10-23.md` §8 (S1–S10, A1–A16), §9, §10.
Дизайн: `arch-design.md` §10 (тест-план), §11 (миграция).

Кандидат кодовых фаз: `f30feb30` (style), `bfc12366` (identity rework), `02434414` (UI).
Прогон приёмки: `69c7a068` + коммит приёмки `804b68b1` (тесты + однострочный fail-open
фикс в `generate_initiative_reply`, см. §6.2).

## 1. Метод и границы

- Сеть, прод, SSH, живые Telegram-сообщения **не использовались** — рамка полосы.
- Доказательство — durable pytest-тесты на фактическом коде путей (реальный
  `chat_params`, реальный `StylePolicyValidator`/`apply_style_policy`, реальный
  API-сборщик Inspector), а не изолированные заглушки там, где это возможно.
- UI-рендер и живой браузер уже доказаны в `evidence/ui-phase.md`
  (`tests/ui_asap3_hint_speech_e2e.py`, 7 проверок; скриншоты
  `evidence/shots/*.png`). Повторно не запускались: UI-приёмка идёт отдельной полосой.
- Прод-конфигурация и живой TMA — postdeploy; точный read-only план в
  `migration.md` §5.

## 2. Прогон (числа)

```text
tests/test_asap3_style_hint_limits.py        16 passed
tests/test_asap3_identity_aliases.py         22 passed
tests/test_asap3_acceptance.py (новый)        7 passed
------------------------------------------------------
ASAP3 total                                    45 passed   (3.72 s)

Затронутые style/identity/iniциатива (11 файлов):
  + test_soul1_style_policy, test_soul1_style_payload,
    test_soul1_composer_layers, test_soul1_core_composer_integration,
    test_summary_aliases, test_aliases_render_round1024,
    test_soul1_w5_initiative_vitality, test_soul1_direct_prompt_reads
  итог: 188 passed, 1 warning (Starlette/httpx deprecation), 8.24 s
```

## 3. Матрица Style Policy (S1–S10)

| ID | Что проверяется | Доказательство | Статус |
|---|---|---|---|
| S1 | >400 симв. инструкций при OFF: ни одна активная не потеряна, порядок детерминирован | `test_asap3_style_hint_limits.py::test_s1_long_hint_is_not_truncated_when_limit_off` | PASS |
| S2 | >5 мягких привычек: все 9 в фактическом блоке, `included == total` | `::test_s2_more_than_five_soft_instructions_all_present` | PASS |
| S3 | Включённый лимит: превышение видно (`included < total`, `excluded` с `user_limit`, `overflow`), режутся только целые строки; UI показывает предупреждение и список | `::test_s3_user_limit_overflow_is_visible_with_reason`, `::test_s3_chars_limit_drops_whole_lines_only`; UI — `ui-phase.md` §2, `ui_asap3_hint_speech_e2e.py` | PASS |
| S4 | Изменение лимита применяется без рестарта на уровне effective policy | `::test_s4_limit_change_applies_without_restart`; **новый** `test_asap3_acceptance.py::test_s4_saved_limit_applies_next_resolve_without_restart` (реальный `chat_params.set_chat_params` → инвалидация → `effective_style_policy`) | PASS |
| S5 | Лимит чата A не меняет чат B | `::test_s5_chat_limits_do_not_leak_between_chats`; тот же инвариант в новом S4-тесте | PASS |
| S6 | `—` → `-` в обычной речи, идемпотентно, доходит до outbound-прохода; остаточное `—` в payload — `conflict`/`mismatch`, а не `styled=true` | `::test_s6_dash_is_replaced_in_plain_speech`, `::test_s6_dash_reaches_outbound_pass`; **новый** `::test_s6_outbound_verify_flags_remaining_dash` | PASS |
| S7 | URL, код, JSON, дословная цитата, HTML-разметка/атрибут ссылки, inline-код и version-literal сохраняются без повреждений | `::test_s7_protected_segments_keep_original_dash`; **новый** `test_asap3_acceptance.py::test_s7_markup_link_code_and_version_survive` | PASS |
| S8 | Отключённое правило тире (global / chat по id) не вмешивается в текст | `::test_s8_disabled_dash_rule_does_not_touch_text` | PASS |
| S9 | Inspector отдаёт фактически включённые инструкции, а не желаемые настройки; блок = собранный из global+chat | `::test_s9_structure_reports_actually_included_rules`; **новый** `test_asap3_acceptance.py::test_s9_inspector_summary_matches_actual_assembly` (`hint_text == policy.hint`, счётчики, источник, лимит, причины исключения) | PASS |
| S10 | Остальные лимиты не скрывают потерю: 13 привычек сохраняются, >64 — блокирующая диагностика; потолок правил — то же; бюджет композера виден как `budget_excluded` и не выдаётся за лимит владельца | `::test_s10_soft_instruction_cap_no_longer_silent`; **новые** `test_asap3_acceptance.py::test_s10_rules_cap_is_blocking_diagnostic_not_silent_cut`, `::test_s10_budget_exclusion_is_not_disguised_as_user_limit`, `::test_s10_composer_style_layer_exclusion_is_visible` | PASS |

## 4. Матрица алиасов (A1–A16)

Все — `tests/test_asap3_identity_aliases.py` (22 теста).

| ID | Проверка | Тест | Статус |
|---|---|---|---|
| A1 | Глобальный алиас выше nickname/username/памяти | `test_a1_global_alias_beats_nickname_username_memory` | PASS |
| A2 | Чатовый алиас перекрывает глобальный только в своём чате | `test_a2_chat_alias_wins_only_in_its_chat` | PASS |
| A3 | Частичный чатовый словарь наследует остальные глобальные | `test_a3_partial_chat_map_inherits_global_aliases` | PASS |
| A4 | Изменение глобального алиаса — со следующего хода без рестарта | `test_a4_global_change_applies_next_turn` | PASS |
| A5 | Изменение чатового алиаса — со следующего хода без рестарта | `test_a5_chat_change_applies_next_turn_without_restart` | PASS |
| A6 | После рестарта действуют сохранённые алиасы | `test_a6_after_restart_saved_aliases_apply` | PASS |
| A7 | Удаление чатового override возвращает глобальный | `test_a7_delete_chat_override_returns_global` | PASS |
| A8 | Удаление глобального возвращает следующий источник | `test_a8_delete_global_alias_returns_next_source` | PASS |
| A9 | Один uid с разными историческими именами — один человек | `test_a9_one_uid_many_historical_names_is_one_person` | PASS |
| A10 | Старый `author_name` не переопределяет алиас | `test_a10_old_author_name_does_not_override_alias` | PASS |
| A11 | Имя из GraphRAG не переопределяет алиас в UserResolutionMap | `test_a11_old_graphrag_name_does_not_override_in_resolution_map` | PASS |
| A12 | Параллельные чаты без утечки локальных override | `test_a12_parallel_chats_do_not_leak_overrides` | PASS |
| A13 | Direct, Summary, инициатива, инструменты, media — один порядок | `test_a13_direct_summary_tool_and_media_share_one_order`, `test_a13_initiative_l1_and_l2_use_alias_not_author_name` | PASS |
| A14 | Цитаты и исторический текст не повреждаются при смене алиаса | `test_a14_quotes_and_history_text_untouched` | PASS |
| A15 | Недоступная/битая конфигурация — `scope_report.ok=false` + причина, а не подмена старым алиасом без диагностики | `test_a15_unavailable_config_is_diagnosed_not_silent`, `test_a15_invalid_json_is_diagnosed` | PASS |
| A16 | Полный путь: Telegram ID → effective alias → контекст → результат | `test_a16_harness_telegram_id_to_context_and_result` (fake PG-участники → `_active_participants` → `_build_alias_map` → `_resolve_name`) | PASS (harness) |
| A16 live | Тот же путь на production-сообщении | — | **NOT_TESTED** (postdeploy, вне полосы: сеть/прод запрещены; план — `migration.md` §5.6) |

Дополнительно к A-матрице: `test_empty_alias_value_does_not_rename_or_hide_global`,
`test_double_encoded_global_json_still_merges`, `test_diag_aliases_merged_view_only_with_show_names`,
`test_dossier_keeps_fact_with_stable_uid_after_rename` — все PASS.

## 5. Критерии §10

| # | Критерий | Доказательство | Статус |
|---|---|---|---|
| 10.1 | Все инструкции без включённых лимитов попадают в сборку | S1/S2 | PASS |
| 10.2 | Пользовательские лимиты не действуют скрытно без диагностики | S3, S10 | PASS |
| 10.3 | Строгое правило дефиса включено по умолчанию и работает на исходящих | S6 (factory-правило, validator + `apply_style_policy`, payload-verify) | PASS (код/локально); живая доставка — postdeploy |
| 10.4 | Приоритет имён един во всех речевых маршрутах | A13, A1–A3 | PASS |
| 10.5 | Чатовые алиасы переопределяют глобальные по uid с наследованием | A2, A3, A7 | PASS |
| 10.6 | Изменения алиасов применяются после сохранения без рестарта | A4, A5 (+ S4 для лимитов) | PASS |
| 10.7 | История не теряется, переименование не создаёт новую личность | A9, A14, `test_dossier_keeps_fact_with_stable_uid_after_rename` | PASS |
| 10.8 | UserResolutionMap не даёт модели противоречивых имён одного uid | A11, A13, A16 harness | PASS |
| 10.9 | Регрессионные тесты + проверка на реально действующей конфигурации | 45/188 passed; прод-конфигурация — **NOT_TESTED** (read-only план `migration.md` §5) | PASS (тесты) / NOT_TESTED (прод) |
| 10.10 | Нет нового хардкода/отдельной подсистемы/глобальной замены строк | `git diff f30feb30^..HEAD -- services web bot.py handlers manage.py` не добавляет строк с именами/ID из тестов (grep по добавленным строкам пуст); глобальной замены имён нет — A14/A11 + `merge` по uid | PASS (проверка диффа; финальная оценка — Reviewer) |

## 6. Что добавлено этой полосой

### 6.1 Durable-тест `tests/test_asap3_acceptance.py` (7 тестов)

`TEST-LIFECYCLE: CONTRACT/REGRESSION owner=ASAP3-ACCEPT §8 S4-S10`.

| Тест | Закрытый пробел |
|---|---|
| `test_s4_saved_limit_applies_next_resolve_without_restart` | S4 на фактическом save-пути: реальная транзакция `chat_params.set_chat_params`, реальная инвалидация `ChatParamsCache`, затем `effective_style_policy` — без рестарта; заодно S5 (второй чат не затронут) |
| `test_s6_outbound_verify_flags_remaining_dash` | S6 вторая половина: остаточное `—` в payload = `conflict`/`mismatch`, чистый payload = `ok` |
| `test_s7_markup_link_code_and_version_survive` | S7 расширен: HTML-атрибут ссылки, inline-код, version-literal целы, обычная речь заменена |
| `test_s9_inspector_summary_matches_actual_assembly` | S9 на уровне API Inspector: `hint_text` равен фактическому блоку, счётчики/источник/лимит/причины совпадают |
| `test_s10_budget_exclusion_is_not_disguised_as_user_limit` | S10: `budget_excluded` не выдаётся за `user_limit`, `payload_included=false` честно |
| `test_s10_rules_cap_is_blocking_diagnostic_not_silent_cut` | S10: потолок правил — `rules_truncated` в fatal + виден в витрине документа |
| `test_s10_composer_style_layer_exclusion_is_visible` | S10: слой Style Policy в композере при малом бюджете — `budget_excluded` из закрытого набора `SKIP_REASONS` |

### 6.2 Найденный и исправленный реальный дефект

Затронутый прогон выявил падение существующего durable-контракта
`test_soul1_style_payload.py::test_initiative_writer_returns_raw_text_for_the_single_pass`:
`generate_initiative_reply` напрямую обращался к `self.aliases`, а частично
собранный объект (`__new__` без DI) атрибута не имеет — `AttributeError`
вместо fail-open. Минимальный фикс: `getattr(self, "aliases", None)` в одной
строке (`services/direct_chat_service.py:8836`), тот же fail-open, что и в
`_refresh_turn_aliases`. После фикса файл — 12 passed. Поведение реальных
экземпляров не меняется (атрибут всегда установлен конструктором).

### 6.3 Что переиспользовано без изменений

- S1–S3, S5, S8, S9 (структура), S10 (привычки) — `test_asap3_style_hint_limits.py`;
- S4 (кэш-уровень) — там же;
- все A1–A15 + A16 harness — `test_asap3_identity_aliases.py`;
- бюджетные слои композера — `test_soul1_composer_layers.py::test_core_is_never_evicted_by_additive_budget`;
- UI-видимость S3/S9 — `evidence/ui-phase.md` + `tests/ui_asap3_hint_speech_e2e.py`.

## 7. Что осталось вне полосы

1. **A16 live / 10.3 live / 10.9 прод-конфигурация** — postdeploy DevOps по
   read-only плану `migration.md` §5 (эффективная политика, dash, Inspector,
   смена лимита/алиаса без рестарта).
2. **Живой Telegram Mini App на прод-конфигурации** — отдельная UI/DevOps
   проверка; локальный реальный браузерный рендер уже пройден (`ui-phase.md` §5).
3. Полный `pytest` всего репозитория не запускался: рамка полосы — целевые
   файлы; широкий прогон остаётся за Reviewer/DevOps.

## 8. Наблюдения (не блокеры)

- `related-nonblocking / uncertain`: `<code>…</code>` HTML-тело не входит в
  защищённые сегменты (`telegram_entity` — только сами теги). В текущих речевых
  маршрутах обычный ответ уходит `parse_mode=None` (тег — литерал, не код), а
  safe-HTML ветка (lore/deep_research) получает Style Policy уже по plain-тексту
  до escape. Поэтому S7 не нарушен; отдельная проверка потребуется, только если
  появится исходящий payload с реальным `parse_mode=HTML` и кодом внутри
  `<code>`. `segment()` в этой полосе не менялся (arch-design §8).
