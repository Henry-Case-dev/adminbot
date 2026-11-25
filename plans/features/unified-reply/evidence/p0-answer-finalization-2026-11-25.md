# P0 corrective — финализация ответа и публикация «Летописца» (lane A)

Дата: 2026-11-25. Ветка: `fix/p0-answer-finalization`. База: `e3467ccb787709650af3f493a88861e60ac51684`
(2.58.245 — evidence `release-2.58.246/deploy-2.58.246.md` отсутствует, деплой 2.58.246 не подтверждён).

Owner-контракт (verbatim, неизменяемые источники):
* `plans/owner_inputs/2026-11-25-p0-intent-memory-answer-quality.md` (sha256 `0d2b3516…20a94`), §2 и §4 — объём этой полосы; §1/§6 — ограничения.
* `plans/owner_inputs/2026-11-25-p0-acceptance-boundaries-amendment.md` (sha256 `02a8e2ce…982c`) — приёмка инженерная, без метрик «естественности».

Requirement IDs (эта полоса): `P0-AQ-4.1` (запрет программных пользовательских ответов),
`P0-AQ-4.2` (семантика финализации/деградации), `P0-AQ-2.1` (гейт публикации Летописца),
`P0-AQ-4.3` (служебный контекст не становится ответом).

## 1. Установленные факты (pre-fix, база e3467ccb)

### 1.1 Захардкоженный «частичный отчёт» вместо ответа модели

| Место (база) | Роль |
|---|---|
| `services/tool_loop.py:1436` `_structured_partial` | собирал готовый пользовательский текст: «Исследование остановлено: …», «Это частичный результат: финальный LLM-вызов недоступен …», «Запрос: …», «Подтверждённые данные (результаты инструментов):», «Непроверено: …», «Полные результаты вызовов сохранены в журнале прогона …» |
| `services/tool_loop.py:1504` `structured_partial_from_result` | публичная обёртка того же шаблона для живого Direct-пути (S7-шов) |
| `services/tool_loop.py:2121` (`_finish_degraded`) | вызывал `_structured_partial(..., require_content=True)` при недоступном/пустом финальном Writer'е |
| `services/tool_loop.py:2129` | `TOOL_LOOP_FALLBACK_PHRASE` («Чет долго думал…») как ответ при полном отсутствии данных |
| `services/direct_chat_service.py:249,7869` | живой путь: пустой L2 + `evidence_sources` → тот же детерминированный partial публиковался пользователю |
| `services/tool_loop.py:1546`/`2129` (`_finalize_error_text`) | человекочитаемые коды ошибок внутри этого шаблона |

Причина (механизм): внутреннее техническое состояние (статусы инструментов, коды отказа,
provenance, счётчики) **превращалось в готовую разговорную речь программным кодом**. Это не
«неудачная формулировка»: любой сбой финального Writer'а при наличии tool-результатов
публиковал отчёт от лица бота.

Производственный сценарий A (owner §1): `download_media` сам отправил видео в чат и вернул
`{"status":"success",…}`; финальный текст модели был пуст → публиковался «Исследование
остановлено: …». Классификация «инструмент уже доставил результат» существовала только для
подавления Writer'а (`services/response_extent.py:856` `media_writer_needed`,
`services/tool_loop.py:1672` `media_delivered`), но **не** для финализации: доставленный
артефакт + пустой LLM давали технический отчёт и ложный статус незавершённого исследования.

### 1.2 Летописец: подмена ответа Writer готовой историей

`services/direct_l1.py:625-672` `lore_story_delivery_allowed` (база):
* `LORE_STORY_ACTS = {"creative", "historical_recall"}` — «творческий» акт разрешал подмену;
* неопределённая интенция → `return True` (fail-open), легаси `task_kind` без структуры → `True`,
* исключение → `True`.

Вызывающие: `services/direct_chat_service.py:2013` `lore_story_override` (прямая подмена
доставленного текста), `:2040` `lore_verbatim_allowed` → `ToolContext.lore_verbatim_instruction`
→ `services/tool_router.py:7610` «верни story ДОСЛОВНО» в payload Writer'а.
Следствие: на `creative` (шутка/стихи/план) и на неопределённом интенте ответ Writer'а
заменялся готовой историей Летописца либо Writer эхом возвращал её.

### 1.3 Специализированные пути (перечислены, классифицированы ниже)

* `services/checkup_service.py:765/794` — `research_partial_note`/`research_not_executed_note`
  добавляют «Примечание: это частичный результат — …» к отчёту чекапа (админ-команда).
* `services/factcheck_service.py:4174` `_temporal_fallback_text` — детерминированный
  вердикт-текст фактчека при недоступном вербализаторе.
* `services/direct_chat_service.py:8133/8150` `CHAT_ERROR_PHRASES`, `:7333` `DEFAULT_NO_KEY_REPLY`
  — единственная фраза при полном отказе провайдера (нет генеративного пути вовсе).
* `services/response_extent.py:836` `clarification_question` — фиксированный уточняющий вопрос.

## 2. Что изменено (cause-level)

### A. Механизм программного ответа удалён

`services/tool_loop.py`:
* `_structured_partial` **удалён**; вместо него `failure_state(...)` — структурное состояние
  (`status`, `stop_reason`, `finalize_error`, `usable/failed/calls`, `failed_tools`) без
  пользовательского текста.
* `structured_partial_from_result` **удалён** (вместе с `_excerpt`, `_last_user_text`,
  `_strip_clock_block`, `_item_has_content`).
* `TOOL_LOOP_FALLBACK_PHRASE` **удалён**.
* `_finish_degraded`: наличие данных → существующий финальный Writer по evidence; иначе
  последний авторский текст модели (`finalize_mode="partial_text"`), иначе честное состояние:
  `"delivered_artifact"` (инструмент уже доставил результат) или `"no_generative_path"`.
  Программного текста нет; факты остаются в `research_state`/envelope/логе.
* `_evidence_inventory`/`_finalize_directive` сохранены: реальное состояние (что получено,
  что отказало, причина остановки) уходит в **существующий** Writer-путь.
* `media_delivered` принимает и журнал envelopes (внутренний degraded-путь), не только result.

`services/direct_chat_service.py`:
* пустой ответ: если инструмент уже доставил артефакт (`image_delivered` или успешный
  media-инструмент по envelope) — текст не публикуется и повторной доставки нет, ход
  закрывается; иначе — честное молчание+🗿 с диагностикой (`degraded/reason/finalize/research`
  в логе). Вызов `structured_partial_from_result` удалён.

`services/checkup_service.py:763`: исключение дублирующей пометки для новых режимов
(`no_generative_path`/`delivered_artifact`) — соответствует смыслу прежнего условия.

### B. Семантика финализации (owner §4)

| Фактическое состояние | Поведение после фикса |
|---|---|
| Инструмент доставил запрошенный результат, Writer пуст | нет текста, нет повторной отправки, нет «незавершённого исследования»; `delivered_artifact` |
| Промежуточный/побочный успех, Writer пуст | вызван существующий recovery (финальный Writer по evidence); побочный успех не считается выполнением; при неудаче — `no_generative_path` |
| Частичные данные + рабочий Writer | нормальный ответ модели (`llm`) |
| Все генеративные пути недоступны | честное состояние, диагностика сохранена, без псевдо-ответа и без цикла |
| Повторные попытки финализации | внешние действия не повторяются: LLM-вызовы не диспатчат инструменты; доставка артефакта проверяется по envelope |

### C. Летописец

`services/direct_l1.py` `lore_story_delivery_allowed`:
* разрешение только при `structure="story"` или `response_act="historical_recall"`
  (легаси: `task_kind="historical_recall"` либо `creative_writing` + `structure="story"`);
* `creative` без story-формы — не разрешение; неопределённая интенция/нет плана/исключение —
  `False` (fail-closed): история идёт материалом в Writer;
* kill-switch `LORE_STORY_INTENT_GATE_ENABLED` OFF сохраняет прежнее поведение байт-в-байт.
Обновлены docstring'и `lore_story_override`/`lore_verbatim_allowed` (контракт тот же гейт).
Ностальгия/локальные мемы/исторические рассказы (`historical_recall`, `story`) не сужены.

### D. Служебный контекст

Проверены источники попадания в ответ: `_evidence_writer_note` (`[EVIDENCE]`-строка),
заголовки/статусы evidence pack (`build_evidence_pack`), plan-блок, `research_*_note`.
Программной публикации этих данных в обычных ответах после фикса нет: единственный
пользовательский текст формирует модель. Строки статусов остаются во **входе** Writer'а как
контракт доказательности (owner §4: структура ≠ текст ответа); их пересказ моделью — вопрос
контента/релевантности retrieval (полоса памяти), blacklist не вводился.

## 3. Тесты

Новый дискриминирующий файл: `tests/test_p0_answer_finalization.py` (13 тестов) — сценарии
owner §4/§2: доставленный артефакт + пустой Writer; промежуточный успех + recovery;
частичные данные + рабочий Writer; отсутствие генеративного пути; гейт Летописца
(`creative`/unknown/analysis → материал, а не ответ); пины отсутствия механизма в коде.

RED на базе e3467ccb (файл тестов скопирован в чистый worktree базы):
`10 failed, 3 passed` — падают именно новые контрактные проверки (артефакт, recovery-state,
честное состояние, гейт Летописца, отсутствие механизма); 3 проходят и на базе
(«запрошенная история публикуется», «модельный ответ при рабочем Writer», «analysis-план уже
блокировал подмену») — это позитивные контроли, не тавтологии.

GREEN на кандидате:
* `tests/test_p0_answer_finalization.py` — **13 passed**.
* Затронутые наборы (tool_loop/finalization/lore/nostalgia/direct):
  `tests/test_tool_loop.py`, `test_tool_calling_round1015`, `test_smoke_round1016_tool_loop`,
  `test_agentic_ai_round1020`, `test_tool_coordinator_round1026`, `test_smart_g_finalize_round1114`,
  `test_smart_corrective_s7_reply`, `test_smart_corrective_completion`, `test_mca11_tool_result_round1028`,
  `test_factcheck_finalization`, `test_smart_p0_checkup`, `test_p0_delta_routing`,
  `test_lore_compiler_round1020`, `test_lore_worker`, `test_lore_prompts`, `test_chat_lore`,
  `test_direct_chat_lore_inject`, `test_direct_chat`, `test_asap7_direct_l1`,
  `test_nostalgia_layer_a`, `test_nostalgia_prompts`, `test_p0_answer_finalization`
  → **762 passed, 2 failed** (оба — pre-existing, см. §4).
* Дополнительно: `test_decision_making_round1026`, `test_mca15_chat_statistics_round1028`,
  `test_mca23_response_plan`, `test_rlr_dcs_postprocess`, `test_scanner_fixes_round1020`
  → **249 passed**.
* Повторный прогон ключевых после последних правок → **155 passed**.

Изменённые старые тесты (контракт изменён решением владельца, не ослабление):
* `tests/test_p0_delta_routing.py` — `creative`/unknown/без плана больше не разрешают подмену
  (owner 2026-11-25 §2); legacy `creative_writing` без `structure=story` → False;
  матрица маршрутов обновлена в колонке lore-gate. Анализ/research-запреты сохранены.
* `tests/test_smart_g_finalize_round1114.py`, `tests/test_smart_corrective_s7_reply.py`,
  `tests/test_agentic_ai_round1020.py`, `tests/test_tool_calling_round1015.py`,
  `tests/test_smoke_round1016_tool_loop.py`, `tests/test_tool_coordinator_round1026.py`,
  `tests/test_tool_loop.py` — вместо «частичного отчёта»/заглушки проверяются:
  ответ модели по evidence, `finalize_mode` (`llm`/`partial_text`/`delivered_artifact`/
  `no_generative_path`), пустой публикуемый текст и сохранённый журнал/директива Writer'а.
* `tests/test_smart_p0_checkup.py` — при полном отказе исследования чекап больше не публикует
  программный partial: `LLMBadResponseError` (существующий silence-путь) + телеметрия
  `research_status=partial`; проверка «Исследование остановлено» удалена как проверка
  удалённого контракта.

`py_compile` изменённых модулей — OK; `git diff --check` — OK.

## 4. Pre-existing / environment (не регрессии кандидата)

Проверено идентичным прогоном на базе e3467ccb:
* `test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools` — ожидает 17
  схем, фактически 18 (дрейф канона инструментов, `tool_schemas.py` не менялся). FAIL на базе.
* `...::test_forbidden_paths_out_of_diff` — `OSError [WinError 6]` в `subprocess.run(git …)`
  (окружение Windows/агентского раннера). FAIL на базе.
* `test_image_generation_round1023.py::...test_direct_chat_image_off_eight_tools` — тот же
  дрейф числа инструментов (14 vs 16). FAIL на базе.
* `test_mca16_experience_block_d_round1039.py::test_deep_sleep_not_mixed_with_lessons`,
  `test_tool_download_quality_round1017.py` (2) — FAIL на базе.
* `test_unified_image_request_round1026.py` (канон инструментов / git-diff) — тот же класс,
  что проверенные выше (файл не изменялся этим diff'ом).
* `test_selfdiag_corrective_research.py` (6) — `TypeError ... unexpected keyword 'preserve'`
  в тестовом стабе и `OSError [WinError 6]`; ни один из модулей полосы не менялся. Не
  перезапускался на базе: этот файл стабильно роняет оболочку агента (subprocess/handle),
  поэтому класс подтверждён по коду/сообщению, а не новым прогоном.

Широкий вспомогательный набор: **778 passed, 26 failed** — все перечисленные выше файлы не
входят в diff этой полосы; новых падений в затронутых модулях нет.

## 5. Что осталось (короткие факты)

1. `research_partial_note`/`research_not_executed_note` по-прежнему добавляют текстовую
   пометку к **отчёту чекапа** (админ-команда, технический отчёт по запросу). Это
   существующий специализированный контракт, разрешённый owner §4; в обычные ответы не
   попадает. Если владелец захочет убрать и её — потребуется отдельный LLM-финальный проход
   чекапа (сейчас нет).
2. `_temporal_fallback_text` фактчека остаётся детерминированным текстом **только** при
   недоступном вербализаторе (аварийный путь специализированного режима; owner §4 разрешает
   структуру фактчека). Не расширялось и не переносилось.
3. `CHAT_ERROR_PHRASES`/`DEFAULT_NO_KEY_REPLY` — единственная фраза при полном отказе
   провайдера (генеративного пути нет вовсе), не подмена выполнения запроса.
4. Строки `[EVIDENCE]`/статусов остаются во входе Writer'а (контракт доказательности).
   Пересказ статусов моделью лечится качеством retrieval/контекста (полоса памяти), не
   постпроцессором.
5. Выбор `download_media` в сценарии A (семантическая маршрутизация) — вне этой полосы;
   финализация больше не превращает его в технический отчёт и не дублирует доставку.
