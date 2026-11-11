# UR-F шаг 3 — UI инспектора хода (карточки, подписи, мобильная вёрстка)

База: `d8270517` (шаги 1–2 приняты), ветка `ur/f-inspector-step1`.
Контракт: `ur-f-inspector-contract.md` §5 (UI) и §4 (имена полей).
Внешние источники не использовались: правка только по данным, которые уже
отдаёт `GET /api/direct/turn-diagnostics` (шаг 2).

## Что изменено

| файл | дельта |
|---|---|
| `web/app.js` | словари подписей кодов (`TURN_CODE_DICTS`), четыре чистых хелпера (`turnCodeText`/`turnCodeWord`/`turnIdText`/`turnShortWhen`), 20 методов карточек, состояние раскрытия `turnDiagOpen`. Логика шага 2 и бэкенд не тронуты. |
| `web/index.html` | содержимое четырёх карточек: русские названия, source/clock/budget/counts/blocks/dropped/self_outputs/search/links/style, кнопки «показать ещё». Каркас (3 уровня, 4 карточки, `grid gap-2 md:grid-cols-2`, `data-turn-stage`) сохранён. |
| `web/static/app.css` | один слой `[data-turn-inspector] … .turn-wrap` (`overflow-wrap: anywhere`) — иначе длинный URL/id некому переносить: `break-words` в prebuilt-Tailwind нет. |
| `tools/ui_urf_visual_e2e.py` | стаб ответа дополнен секциями шага 3; новый probe шага 3; `--only-inspector` для узкого прогона. Проверки прежних экранов волны сохранены. |
| `tests/js/ur_f_inspector_step3_test.js` | новый JS-unit (node) на реальном `app.js`. |
| `tests/test_webapp_js_unit.py` | регистрация нового JS-unit (одна функция). |
| `tests/test_ur_f_inspector_step3_ui.py` | новый набор: структура/подписи/пустота/сворачивание/мобильность + живой Playwright-прогон. |

DDL = 0, эндпоинтов не добавлено, шаг-2 проекция не менялась.

## Карточки и их содержимое (§5)

1. **Планирование (L1)**: «отвечал: <алиас> (сообщение N, dd.mm hh:mm)»,
   «в ответ на: <алиас> (сообщение M)» или «не ответ на сообщение»;
   действие L1 с подписью кода; время хода (`clock`); «часы поданы на этапах:
   L1, инструменты, ответ»; LLM-вызовы; причина остановки хода.
2. **Инструменты и поиск**: раунды/деградация; строки `tools[]` с подписью
   статуса; покрытие; решение о поиске словами + код моно; «что сделано»
   (выполнялся/итог/причина/число источников); ссылки «заголовок → адрес»,
   дата публикации или «дата публикации не сообщается источником»;
   «поиск не дал ссылок».
3. **Что видел ответ**: завершение Writer'а (подпись `finish_reason`),
   перезаписи/отказ/проверки/источник текста; блоки манифеста — счётом;
   версии разделов промпта с человеческими именами; бюджет одной строкой;
   счётчики «доступно/вошло»; вертикальные строки блоков (понятное имя,
   даты в поясе чата, токены, приоритет вытеснения, ссылки на id); список
   «не вошло, потому что …»; «свои реплики в истории разговора (не образец
   стиля)».
4. **Операции и доставка**: прежняя цепочка `ops[]` с подписью каждой
   операции, честный итог доставки, причина расхождения digest, правила
   стиля «сработало правило: <имя> · итог · причина (код)».

## Словари (расшифровка кодов, UR-20)

`TURN_CODE_DICTS` (в `app.js` рядом с `turnOpLine`/`turnClockLine`):

| группа | примеры |
|---|---|
| `block` | `global_tail→свежие сообщения`, `global_middle→подобранные сообщения`, `global_head→конспект`, `episode→старые эпизоды`, `rag→память, факты`, `thread/branch→ветка ответов`, `protected→защищённые факты`, `sandwich→напоминание`, `map→карта участников`, `current/target/relations/lore/correction/history_supplement/nostalgia/mood/anchors`; короткие имена контракта `MAP`, `Branch`, `Anchor`, `TTL`; машинные теги пути без композера (`Tool_Evidence`, `Current_Question`, `Global_Context`, `RAG_Memory`, `Old_Episode`, `Conversation_Thread`, `Conversation_Branch`, `UserResolutionMap`, `protected_facts`, `chat_lore`, `Target_User`, `Correction_Frame`, `History_Supplement`, `Fresh_Chat_Window`, `user_relations`, `deferred_request`, `Initiative_Context`, `Expression_Settings`, `prev_context`, `next_context`, `segment`, `untagged`) |
| `ops` | `l2_scrubber`, `reasoning_marker_strip`, `machine_marker_strip`, `lore_story_override`, `evidence_egress_guard`, `owner_style_punctuation`, `rich_render`, `html_escape`, `plain_render`, `egress_sanitize`, `telegram_chunk`, `unexplained_text_change` |
| `search_decision` | `required→поиск обязателен`, `beneficial→поиск полезен`, `not_applicable→поиск не нужен` |
| `search_status` / `search_skip` | `ok, empty, timeout, contradictory, unavailable, skipped_not_required, privacy_blocked` / `participation_without_text, search_intent_not_applicable, no_resolved_tools, search_tool_absent, user_forbidden_external, empty_query, qualified_verified_reuse, search_contradictory` |
| `rule_status` | `pass, repaired, exempted, conflict, failed, denied, not_applicable` |
| `rule_kind` | `dash, quotation_marks, forbidden_chars, line_breaks, trailing_period, emoji, one_word, extent` |
| `rule_reason` | `protected_verbatim, soft_habit_writer_only, emoji_removed, dash_replaced, rule_params_absent, forbidden_chars_removed, quotes_normalized, quotes_removed, quotes_in_protected, owner_rule_vs_task, covered_by_extent_check, blank_line_runs_collapsed, line_breaks_exceeded, ellipsis_kept, kind_handler_absent, rule_error` (составные `a:b` раскрываются по частям) |
| `drop_reason` | `budget_exceeded, compressed, physical_overflow, duplicate_source, correction_unbound, superseded_by_user_correction` |
| `tool_status`, `action`, `trigger`, `finish`, `stage`, `priority`, `policy_mode`, `window_source`, `id_ns`, `style_source`, `writer_name`, `prompt_key` | статусы инструментов; действия L1; причины запуска хода; `finish_reason`; стадии часов `l1/tool/l2`; приоритет вытеснения `p0…p3`; режимы бюджета `unlimited/dynamic/cap/legacy_budget/fallback_recompose`; источник окна `model_map/env_override/unknown_fallback`; пространства имён id (`msg, tg, row, fact, episode, summary, web, src, source, bot_output, bot_output_tg`); источник правил; имена писателей; ключи промптов (`prompts.direct_chat_verbalizer_system_prompt`, `prompts.direct_l1_planner_system_prompt`) |

Неизвестный код в любом месте → **«код: <значение>»**. `trace_id` подписан
«код хода (служебный, по нему собрана трасса)». `id` печатаются словами
(«сообщение 987654321012», «факт памяти 42», «конспект -100500:2») без
разрядных пробелов и без обрезки.

## Честная пустота и усечение

* `selection/search/style = null` и `stages.* = false` → «нет данных (трасса
  старше версии)» / «…не зафиксировано (трасса старше версии)»; отсутствующее
  число — словом «неизвестно», никогда `0` (UR-20.5/20.6).
* `clock.stages` = `null` (неизвестно) отличается от `[]` (часы не подавались).
* `truncated` объясняется словами: «запись сокращена — блоки: показаны 7 …;
  потерянные: показаны первые 2 из 9; свои реплики: показаны 1 …». Обычный ход
  (без `truncated`) никакого флага не показывает.
* Правило со статусом `pass` не называется «сработавшим»: «правило проверено,
  нарушений нет: <имя>» (иначе строка противоречит сама себе). Сработавшие
  (`repaired/conflict/failed/denied`) — ровно формулировкой контракта.

## Сворачивание и мобильная вёрстка

Пороги `TURN_LIST_LIMITS = {blocks: 5, links: 3, rules: 4}`; по умолчанию
свёрнуто, кнопка «показать ещё N» раскрывает (состояние `turnDiagOpen`, только
экран; при смене хода сбрасывается). Строки — `flex flex-col` + `.turn-wrap`
(`overflow-wrap: anywhere`), без таблиц и без `truncate` на id/датах; <768px —
одна колонка (каркас `md:grid-cols-2` не менялся).

## Проверки

| набор | результат |
|---|---|
| `node tests/js/ur_f_inspector_step3_test.js` | `UR-F-STEP3-OK` |
| `tests/test_ur_f_inspector_step3_ui.py` (новый) | 36 passed |
| `tests/test_ur_f_inspector_step1.py` + `step2.py` | 55 + 19 passed |
| `tests/test_ur_c_clock.py`, `test_ur_d_writer.py`, `test_ur_e_speech.py`, `test_ur_turn_engine.py` | 74 passed |
| `tests/test_direct_chat.py` | 156 passed |
| `tests/test_webapp_js_unit.py` | 40 passed, 4 failed — те же 4 падают на базе `92070d0e` (glass/heartbeat/aurora пины) |
| `test_webapp_evol_w7/w9/w10/w11/w12/w13/w14/w15/w16` + `parity_smoke` + `design_tokens_1025` + `test_ur_ui_effective_config` | 307 passed |
| `tests/test_mca23_planned_vs_actual.py` | 23 passed + 1 failed (`test_routes_pin_untouched`) — падает одинаково на базе `92070d0e` и `dbf89a96` (устаревший пин) |
| `tests/test_round1025_f8_registry.py` | 1 failed (`test_routes_file_unchanged`) — пин ложен уже на `dbf89a96` (sha256 базы не совпадает); на `92070d0e` зелёный |

Сводный прогон «web/direct наборов» на одной и той же выборке:
база `92070d0e` — 351 passed / 5 failed; кандидат доработки — 351 passed /
6 failed (дельта ровно один уже устаревший пин `test_routes_file_unchanged`,
который на `dbf89a96` тоже падает).

Живой прогон `tools/ui_urf_visual_e2e.py` (1440×900 и 390×844): `URF-VISUAL-OK`,
консоль браузера чиста (0 ошибок). Отчёт: `urf/urf-step3-visual-report.json`.

| вьюпорт | h-скролл | карточки | свёрнуто | раскрытие | сырых кодов |
|---|---|---|---|---|---|
| 1440×900 | нет | 4 (2×2) | 5 / 3 / 4 | 7 / 4 / 6 | 0 |
| 390×844 | нет | 4 (1 колонка) | 5 / 3 / 4 | 7 / 4 / 6 | 0 |

Снимки: `urf/urf-step3-before-inspector-{desktop-1440,mobile-390}.png` (до,
старый UI с сырыми кодами), `urf/urf-step3-after-inspector-{desktop-1440,mobile-390}.png`,
по карточкам `urf-step3-after-{writer,tools,delivery}-*.png`, раскрытые списки
`urf-step3-after-expanded-mobile-390.png`, живой Chrome (Browser Use)
`urf-step3-bu-{mobile-390,desktop-1440}.png`.

Доработка шага 3 (четыре гэпа): свежий прогон того же инструмента —
`urf/urf-step1-gaps-visual-report.json` (sha256
`76a9eca80ff1933b91b56bff201a3e0028220c59bd2b704d3ae40f806653c3ec`),
снимки `urf/urf-step1-gaps-desktop-1440.png`, `urf/urf-step1-gaps-mobile-390.png`.
В отчёте — реальные строки DOM: `sourceLine`, `clockLine`, `modelL1`,
`modelL2`, `blockSummaries` (см. таблицу «было → стало» выше); `unexplained=[]`,
`clipped=[]`, `console_error_count=0`, `hScroll=false` на обоих вьюпортах.

## Чего не хватило из бэкенда (не патчил, сообщаю)

> **Обновление (доработка шага 3, ветка `ur/f-inspector-step1`):** пункты 1 и 2
> ЗАКРЫТЫ ниже — см. раздел «Доработка: четыре гэпа приёмки».

1. **Дата сообщения, на которое отвечали.** `source.reply_to_id` есть, даты
   нет — строка «в ответ на: … (сообщение M)» без времени. Нужен
   `reply_to_message_ts` в контекст-событии.
2. **Дата у конспекта.** Контракт §5 предполагал «конспект до <дата>», но
   стабильный id `summary:<chat>:<level>` даты не несёт; показывается
   «конспект -100500:2». Нужен date-поле в id/блоке, если это важно.
3. **Итоги списков при `truncated`.** Точное «показаны первые N из M» возможно
   только для `dropped` (`dropped_total`); для блоков, ссылок и своих реплик
   тотала нет, поэтому формулировка честная, но без M — нужны
   `blocks_total`/`self_outputs_total`.
4. **Имена блоков манифеста Writer'а** приходят в двух разных формах
   (`layer:block_id` от композера и машинный тег `<Tool_Evidence>` без него).
   Единого словаря для них нет, поэтому в карточке они показаны счётом
   («Блоков в запросе: 2 · показано: 2»), а не строками — иначе в проде
   появлялись бы «код: ctx:thread».
5. **`style.rules[]` содержит и не сработавшие правила** (`pass`, `exempted`,
   `not_applicable`). UI формулирует их честно; если контракт требует только
   `FIRED_STATUSES`, фильтровать должен бэкенд, иначе карточка выглядит
   длиннее, чем «сработавшие правила».

## Доработка: четыре гэпа приёмки (UR-20.4/20.5/20.6/20.8)

База доработки: `dbf89a96`. DDL = 0, новых событий = 0, новых маршрутов = 0.
Единственное новое поле события — числовая дата родителя ответа. Правки:
`services/turn_trace.py` (поле + слот), `services/direct_chat_service.py`
(продюсер даты родителя, диапазон окна конспекта в блоке `global_head`),
`web/api/routes.py` (одна строка строгого allowlist проекции), `web/app.js`,
`web/index.html` (строки карточек), `tools/ui_urf_visual_e2e.py` (стаб и
проверки), тесты.

| гэп | было (реальная строка карточки) | стало |
|---|---|---|
| UR-20.4 | `в ответ на: Борис (сообщение 987654321000)` | `в ответ на: Борис (сообщение 987654321000, 17.10 12:30)` |
| UR-20.5 | блок `конспект` без дат и без ссылок | `конспект до 15.10 10:40 · диапазон: 14.10 20:46 — 15.10 10:40 · единого id источника у конспекта нет` |
| UR-20.6 | только `· модель: test-model-8b` у L1 | `L1: модель test-model-8b · слот: выделенный планировщик (l1_slot) · fallback: … · запас на ответ 12 800` и `L2: api.example / test-model-8b · слот запроса: основной ответ (direct.primary) · отправлено max output tokens: 4 096` |
| UR-20.8/29.3 | `Время хода: Europe/Moscow · 2026-11-06T12:00:00+00:00 · источник: настройки чата` | `Время хода: Europe/Moscow · местное время 06.11 15:00 (+03:00) · UTC 2026-11-06T12:00:00+00:00 · источник: настройки чата · часы на этапах: L1, инструменты, ответ` |

Что именно знает код (и чего не выдумано):

* **Дата родителя** — `reply_to_message_ts` в событии `direct_turn_context`
  (тот же путь, где `source_message_ts`), в проекции — `source.reply_to_ts`
  через общий числовой предикат `_turn_int` (bool/NaN/∞/дробное → `null`).
  Родитель без даты → ключа нет вовсе (карточка не печатает выдуманное время).
* **Диапазон конспекта** — из существующей записи `chat_running_summary`
  (`window_start_ts`/`window_end_ts`). Единого `source_id` у конспекта нет:
  id не выдумывается, поэтому строка говорит «конспект до <дата>» и диапазон.
  Запись без `window_start_ts` (старая/двойник) даёт пустое начало, а не `1970`.
* **Слот L1** — `l1.slot` в событии `direct_turn_context` (`SlotBudgetMeta.slot`:
  `main` | `l1_slot`; у хода на выделенном слоте рядом стоит его модель). Слот
  L2 берётся из `selection.budget.slot` (`direct.primary`) и в L1 не
  подставляется. Трасса, записанная до появления поля, слота не имеет — только
  она даёт «слот не зафиксирован».
  Предел генерации L2 — `writer.completion.max_output_tokens_sent` (фактически
  отправленный), а не значение из конфига.
* **Часы** — локальные дата/время и смещение считаются из `clock.as_of_utc` в
  поясе чата (`Intl.DateTimeFormat` + `timeZoneName: 'longOffset'`); UTC-инстант
  и источник настройки остаются, присутствие часов на стадиях — в той же строке
  короткой формой (подробная формулировка с `null`/`[]` — отдельная строка).

## Остаётся риск

* Счётчик `included_messages` точен, а `blocks[].source_ids` в событии
  ограничены 8 — строка «вошло: …» внутри блока это срез; глобальный счётчик
  от него не зависит.
* Пороги сворачивания (5/3/4) — числа контракта; при росте лимитов событий
  они не пересчитываются автоматически.
* Доработка шага 3: слот L1 в трассе отсутствует (`l1` = action/plan/model/
  fallback), поэтому карточка говорит «слот не зафиксирован». Добавление
  `l1.slot` — изменение формы события (allowlist проекции), в этой правке
  запрещено; это отдельное решение (нужен ключ в `_TURN_CONTEXT_SCHEMA.l1`).
* `test_round1025_f8_registry.py::test_routes_file_unchanged` и
  `test_mca23_planned_vs_actual.py::test_routes_pin_untouched` — байтовые пины
  `web/api/routes.py`; они ложны уже на базе `dbf89a96` (sha256
  `0d15c690…` ≠ пин `1a7d0d4e…`/`8f5601a3…`), т.е. пин не сторожит ничего с
  шагов 1–2. Перепин не делался: это осознанное решение владельца канона
  (L-F11S-1), а не побочный эффект доработки.
