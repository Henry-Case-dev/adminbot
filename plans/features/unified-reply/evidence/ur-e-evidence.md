# UR-E evidence — речь: снятие автоподражания, один deterministic style-pass, без mood-ярлыка

Slice: `UR-E` · Candidate: branch `ur/e-speech`, head `64b7a34f` (base `9a996c79`, `evol/impl`;
кодовые коммиты 6d550bfe -> cb8f6c2c -> 64b7a34f).
Карта: `plans/features/unified-reply/requirements-map.json` (slice `UR-E`, 10 строк).
Основной тест-файл: `tests/test_ur_e_speech.py` (12 тестов, CONTRACT owner=UNIFIED-REPLY/UR-E).
Композиция с коррективом: REMOVE-LEGACY-REPHRASING (RLR/BGS) уже сделал
`public_speech_guard`/style-path observability-only; UR-E ничего из этого не возвращает.

## Что изменено (один слой речи)

* **UR-14/UR-RES-06**: секция `<style_anchors>` («подражай общей интонации этих ответов»)
  из `last_bot_replies` удалена из активной сборки Direct (`_build_user_content`);
  инициативная сборка якорей не имела — инвариант «нет `<style_anchors>`/"подражай"»
  закреплён тестом на оба триггера. Удалены мёртвые помощники `_build_style_anchors`,
  `_detect_sticky`, `_normalize_first_word`, `_STYLE_ANCHOR_LOOKBACK/_STICKY_*`.
  История реплик бота не тронута: `bot_replies`/`mca_bot_outputs` читаются как раньше
  (тест подтверждает читаемость), реплики остаются фрагментами диалога, не инструкцией.
* **UR-16**: лексический mood-ярлык (`зло/радостно` → «подстрой тон») удалён из payload L2
  (`_build_mood_block`/`_parse_mood_words`/init-поля сняты). `CHAT_MOOD_ENABLED` больше не
  создаёт скрытых директив ни при ON, ни при OFF; тон выбирает L1 (оси tone/
  emotional_mirroring плана), owner style и character приоритетнее (без новых текстов).
* **UR-15** (композиция с существующим): character/style входы доезжают до ЕДИНСТВЕННОГО
  Writer-вызова (`_l2_write_answer`) и единственной композиции system
  (`_compose_speech_system` → `prompt_composer.compose_speech_system`, манифест слоёв);
  детерминированные правила владельца (`style_policy.apply_style_policy`) применяются ровно
  один раз на триггер (direct_pre_send / initiative_pre_send), без repair-callback (0 LLM);
  стилевое нарушение не перегенерирует ответ; protected spans (код/URL/JSON/цитаты) не
  повреждаются. Повторы/переписывания не возвращались — весь набор RLR/BGS зелёный.
* **UR-BAN-07**: алиасы, prompt versioning (`prompt_registry.declare_prompt/seal_integrity`),
  владельческие speech instructions (`resolve_prompt("prompts.direct_chat_verbalizer_…")`),
  ограничения доступа к chat data (`get_protected_facts`, DEFAULT_EXEMPTIONS), SafeFetcher,
  SendRecheck — структурный тест подтверждает, что ничего не удалено.
* Владельческие промпты/библиотеки примеров не менялись (0 текстов промптов в диффе);
  новые классификаторы не добавлялись; delivery-логика инициативы не тронута.

## Покрытие по строкам карты (`tests/test_ur_e_speech.py`, кандидат 64b7a34f)

| Req | Статус | Тест(ы) | Что доказывает |
|---|---|---|---|
| UR-14 | PROVEN | `TestNoAutoImitation::test_direct_writer_payload_has_no_anchors_with_history`, `test_initiative_writer_payload_has_no_anchors` (+ `TestStyleAnchorsAndMoodRemoved` в `tests/test_direct_chat.py`) | в payload обоих триггеров нет `<style_anchors>`/«подражай»; история читается (`last_bot_replies`) |
| UR-RES-06 | PROVEN | те же + `TestBanInvariantsIntact` | блока «подражай прошлым ответам» нет; владельческие инструкции/характер/библиотеки на месте |
| UR-15 | PROVEN (редакция BGS-04) | `TestCharacterStyleInputsOneWriter::*`, `TestOwnerRulesExactlyOnce::*`, `test_protected_spans_intact_deterministic_pass` | character/style — в один Writer-вызов и одну композицию; style-pass ровно 1× на триггер, repair=None; нарушение стиля → 2 шага LLM (без второго автора), `semantic_rewrite_count==0`; код-fence/URL байт-в-байт, `repair_used==0` |
| UR-16 | PROVEN | `TestMoodLabelGone::test_direct_payload_no_mood_label`, `TestNoAutoImitation::test_initiative_writer_payload_has_no_anchors` (+ mood-тесты `tests/test_direct_chat.py`) | `<mood>`/«подстрой тон» в payload нет при флаге ON и OFF |
| UR-BAN-07 | PROVEN | `TestBanInvariantsIntact::test_speech_infrastructure_not_removed` | алиасы/PVR/owner speech/ограничения данных/SafeFetcher/SendRecheck существуют |
| UR-17 | LEFT (не в срезе кандидата) | — | fixture `диалог.txt` (04.11.2026 07:50–08:00) в репозитории отсутствует; хронологическая серия с настоящими reply-edges и проверками поведения модели — preprod-валидация (live_when=preprod), честно не собирается без исходного файла |
| UR-17.2 | LEFT | — | различение игры/утверждения/подтверждённой памяти — поведение модели, требует fixture+живую модель |
| UR-17.3 | LEFT (детерминируемая часть покрыта UR-D) | `tests/test_ur_d_writer.py::TestDeliveryBoundary` | адресация speaker/target и «чужой ответ не уходит другому» доказана границей доставки UR-D (первый chunk с reply-привязкой, недоступная цель → cancel, `_validate_plan_target`); диалог-фикстура — LEFT |
| UR-17.4 | LEFT | — | атрибуция после коррекции — поведение модели, требует fixture+живую модель |
| UR-17.6 | LEFT | — | повтор шутки через несколько реплик — поведение модели (fixture+live); пост-L2 reroll по совпадению текстов УЖЕ снят коррективом RLR-04/R-05.1 — enforcing-ветка этой строки superseded_by REMOVE-LEGACY-REPHRASING, остаётся только наблюдение (`DIRECT_FINAL_REPEATED_TEXT`) |

Суперседированные строки: полностью superseded-строк в UR-E нет; UR-15 в карте уже несёт
поправку BGS-04 (Form/Numeric/Format — только реальные трансформации и протокольные
ошибки), которая и реализована; частичная superseded-заметка — UR-17.6 (см. выше).

## Мутация («второй style/generation pass не скрыть»)

* generation: `TestSecondPassMutation::test_second_generation_pass_is_caught_by_author_state`
  — второй литературный вызов того же хода даёт `semantic_rewrite_count == 1`
  (механизм `turn_trace.author_state`, тот же, что в `_l2_write_answer`).
* style: `test_second_style_pass_cannot_hide_from_turn_ops` — реальный ход содержит ровно
  одну ops-запись `owner_style_punctuation`; повторный проход форм на том же ходе немедленно
  виден в ops-трассе (не может пройти незамеченным).
* RED-check: против кода базы `9a996c79` (без изменений UR-E) падают ровно 2 payload-теста
  (`test_direct_writer_payload_has_no_anchors_with_history`,
  `test_direct_payload_no_mood_label`) — тесты ловят возврат автостиля/mood.

## Прогоны (worktree `WorkspaceData/worktrees/c742e4de9e92c489/unified-reply-41500c30aca7-2a1dd879`, py3.12)

* Команда брифа: `pytest tests/test_ur_e_speech.py tests/test_direct_chat*.py
  tests/test_ur_d_writer.py tests/test_rlr_*.py tests/test_bgs0*.py -q` →
  **586 passed, 0 failed** (в т.ч. test_ur_e_speech 12, test_direct_chat 158,
  handlers/prompts 112, ur_d_writer 17, RLR+BGS зелёные — корректив не деградировал).
* Смежные наборы (history_w4/mca07/budget_*/asap7_l1/add_exp/style_hint/context_scenarios/
  context_policy): 230 passed + **11 pre-existing падений, идентичных на базе `9a996c79`**
  (дрейф стабов `_render_thread(projection=…)` и схожие signature-mismatch в заглушках —
  не связаны с UR-E, воспроизводятся чекаутом базового service-файла).

## Честные ограничения

* Ключи `CHAT_STYLE_ANCHORS_*`/`CHAT_BUDGET_ANCHORS_RATIO` остались в `param_catalog.py`
  (catalog-метаданные/UI — вне write_scope UR-E, вывод из UI закреплён за UR-F);
  активный код их больше не читает. Аллокатор `_apply_context_budget` сохраняет
  generic-обработку kinds `mood`/`anchors` — производителей больше нет, путь мёртвый и
  безвредный (синтетические budget-тесты аллокатора не менялись).
* «Реплики бота остаются в thread/self_outputs» в production-окне — предмет UR-C/UR-23
  (ContextSelection в живом ходе); UR-E гарантирует только «не стилевая инструкция» и
  «история не удалена».
