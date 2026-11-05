# RLR-07-PROOF — матрица исполнимых путей ответа на HEAD

Ветка: `evol/impl`, HEAD `c8d9866e2d740f7d51fd9cc5a7610e07ee6138ae`
(merge RLR-04 direct-chat postprocessing removals).
Обновление 2026-11-05 на HEAD `9ca6bb07`: пересняты только ДВЕ изменившиеся
зоны — строка 31/Q6 (явная трансформация: RLR-03.3, ветка c39e371d,
merge `15e8bcc3`) и строка 19/Q3 + покрытие R-08.14 (продолжение
`finish_reason=length`, ветка 673677a1, merge `8eb6893b`); остальная
таблица — снимок `c8d9866e` без изменений.
Основание: `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md` §8 R-07/R-08,
R-09; карта `plans/features/remove-legacy-rephrasing/requirements-map.json`
(`R-07.1`, `R-07.2`, `R-08.1`…`R-08.21`, `R-08.CFG`).

Дата снятия: 2026-11-05. Тип работы: только чтение кода + один прогон тестов,
изменений кода нет (`RLR-07-PROOF` = документ + доказательства).

## 1. Метод и границы

Как установлена достижимость (не grep по имени функции):

1. import graph и call sites: `services/direct_chat_service.py` (`_handle_turn`,
   `_l2_write_answer`, `generate_initiative_reply`, `handle_initiative`),
   `services/direct_execution.py`, `services/direct_l1.py`,
   `services/negative_constraints.py`, `services/style_policy.py`,
   `services/outgoing_guard.py`, `services/tool_loop.py`,
   `services/tool_router.py`, `services/factcheck_service.py`,
   `services/summary_generator.py`, `services/summary_l2_writer.py`,
   `services/summary_l2_review.py`, `services/llm_client.py`,
   `services/smartmodule_utils.py`, `services/response_freshness.py`,
   `services/smart_cache.py`, воркеры `nostalgia_worker`, `meme_initiative`,
   `*_relay`.
2. Гейты и ключи: `services/direct_l1.py::direct_l1_enabled` (env
   `DIRECT_L1_ENABLED` AND hot `flags.direct_l1_enabled`),
   `config/settings.py::resolve_legacy_rephrasing_env_flag`
   (`SYSTEM2_DIRECT_ENABLED` → всегда `False`),
   `mca_gates.speech_style_policy_enabled`, `mca_gates.numeric_claim_guard_enabled`,
   `mca_gates.intents_enabled/intent_decision_enabled`,
   `evidence_policy.egress_guard_enabled`, `SYSTEM2_FACTCHECK_ENABLED`,
   `SUMMARY_L2_REVIEW_ENABLED`.
3. Проверено отсутствие удалённых входов: `_synthesize_direct_answer` не
   существует; `verbalize_validated` вызывается ровно из 4 production-точек
   (`direct_chat_service:7628`, `factcheck_service:2267`, `factcheck_service:3005`,
   `summary_generator:4248`); loops/retries свободной речи отсутствуют.
4. Прогон на этом HEAD: `pytest tests/test_rlr_no_second_author.py
   tests/test_rlr_verbalize_scope.py tests/test_rlr_dcs_postprocess.py
   tests/test_rlr_factcheck_numeric_stage.py -q` → **57 passed**.

Чего этим документом установить нельзя (и это не выдаётся за проверенное):

- **Фактические значения прод-конфигурации** (`flags.direct_l1_enabled` в PG,
  env VPS, per-chat overrides). Установлены только правила резолва и дефолты
  (`DIRECT_L1_ENABLED` default ON `settings.py:654`; hot-ключ default ON
  `direct_l1.py:829`). Реальные значения читаются на live-шаге RLR-07.
- Живой прогон LLM и сравнение `raw_final` с Telegram payload — это R-09,
  не R-07.

Колонка «авторских генераций» = число **независимых финальных авторских**
текстов, из которых реально формируется доставленный ответ на этом пути
(L1-планирование и структурные JSON-стадии сюда не входят; transport retry
в HEAD отсутствует, а продолжение при `finish_reason=length` остаётся тем же
автором — см. строку 19).

## 2. Матрица путей (35 строк)

| № | Путь | Как достигается (call site, гейт) | Финальных авторских генераций | Постобработка и может ли менять смысл | Статус |
|---|---|---|---|---|---|
| 1 | Direct, ответ без tools | `_handle_turn` → `direct_l1_enabled()`=ON → `_plan_direct_l1` (`:4268`) → `_l1_tool_phase` вернул `None` (нет схем/роутера, `:6751`) → `_l2_write_answer` (`:5229`) | **1** (`l2_writer`) | `strip_reasoning_tags` (`:5280`), `apply_style_policy` (`:5418`), `sanitize_outgoing` в `_verify_style_payload`, `send_chunked_reply`. Смысл не меняет: маркеры/форма/escape/chunking | single-writer |
| 2 | Direct с tools/поиском/историей | тот же ход → `_evidence_preflight` (`:4757`) → `_l1_tool_phase`/`run_tool_phase` (`:4798`) → evidence-pack (`:5186`) → `_l2_write_answer` с `<Tool_Evidence>` (`:5237`) | **1** (`l2_writer`); 0..n оркестрационных вызовов tool-фазы текстом ответа не являются | как в (1) + `build_evidence_pack` (детерминированная упаковка), `history_assembly_block` (`:7543`) | single-writer |
| 2b | Tool-дайджест как evidence (`summarize_video`) | tool `summarize_video` (`tool_router:2443`) → `YoutubeSummarizerService.summarize` (`youtube_summarizer_service:82`, LLM `:117`) → результат в `Tool_Evidence` → `l2_writer` пересказывает | 1 финальная (`l2_writer`) + **1 авторская сводка инструмента** | сводка попадает в evidence как текст; L2 её пересказывает литературно | needs-check (Q1) |
| 3 | Direct при L1 OFF (легаси-ветка) | `direct_l1_enabled()`=OFF (env kill-switch или `flags.direct_l1_enabled=false`) → ветка `elif self.tool_router is not None` (`:4819`, `chat_with_tools`) либо `else self.llm.generate(step="single")` (`:4877`); блок `if direct_l1_on:` (`:5120`) не выполняется, L2 нет | **1** (финальный текст tool-loop / single-вызова) | как в (1); numeric-гард и duplicate-reroll отсутствуют (`:5290`–`:5382`) | single-writer |
| 4 | Старый флаг `SYSTEM2_DIRECT_ENABLED` = true/false/0/null | `settings.py:192-204` + `:604-605`: значение всегда `False`, потребителей в активном графе нет (комментарий `:5109-5119`) | **1** (маршрут не зависит от флага) | как в (1) | single-writer (флаг инертен) |
| 5 | Direct SILENT | матрица `_decision_pre_action` (`:3984`) или L1 `action=silent` (`:4365`–`:4395`) → `_execute_silent_ack` (`:3424`) | **0** | нет текста; возможен 🗿 в рамках конъюнкции | no-writer |
| 6 | Direct REACT | `_llm_react` LLM-линия (`:4010`, вызов `:4652`) или L1 `action=react` (`:4396`) → `react_moai` | **0** | нет текста | no-writer |
| 7 | Clarification (media/нет цели) | дет. `_extent.clarification_question` (`:4725`–`:4738`), либо L2-отказ + `needs_clarification` (`:5263`) | **0** | фиксированная фраза из кода | no-writer |
| 8 | Direct-картинка (keyword pre-gate, `generate_image`, `edit_image`) | `image_generation.maybe_handle_keyword` → `send_photo` (`image_generation:2174-2184`); tool `generate_image`/`edit_image` → `send_photo` (`tool_router:5426`); `tool_ctx.image_delivered` / `_image_delivery` → текст подавлен (`:5395`) | **0** текстовых | фото уходит из инструмента; промпт и служебный текст остаются внутренними (в meme-caption не попадают, `meme_initiative:2895`) | no-writer |
| 9 | Инструмент доставил медиа, план `delivery_hint=media` | `download_media` в `MEDIA_DELIVERY_TOOLS` (`tool_loop:116`) + `media_writer_needed`=False (`response_extent:754`) → `_media_skip=True` (`:5216`) → L2 не вызывается | **0** | файл отправлен инструментом, `ledger`/send reservation сохраняются | no-writer |
| 10 | Инструмент доставил медиа, план не media | `download_media` успешен, `media_writer_needed`=True → L2 всё равно пишет текст | **1** (`l2_writer`) | как в (1); второй текст не дублирует файл, а комментирует ход | single-writer |
| 11 | Initiative: reply (в т.ч. с поиском) | `handle_initiative` (`:13450`) → `plan_initiative_decision` (`:13654`) → `generate_initiative_reply` (`:13679`) → `_l2_write_answer` (`:12907`, writer=`initiative_writer`), evidence-pattern тот же (`:12806`, `:12859`) | **1** | `_style_initiative_text` (`:13230`) — один проход формы; SendRecheck/`send_text` (`:13888`); egress-guard только наблюдает (`:12918`) | single-writer |
| 12 | Initiative: silent | `decide_initiative` → `DELIVERY_SILENT` (`:13545`) или L1 `action!=reply` (`:13671`) | **0** | нет | no-writer |
| 13 | Initiative: react | L1 `action=react` (`:13665`) → `_execute_initiative_react` (`:13380`) | **0** | нет | no-writer |
| 14 | Initiative §18D: контекст сменился во время подготовки | `plan_logical_send` → `recheck_again` → ровно одна переоценка (`:13711`–`:13788`) → повторный `generate_initiative_reply` (`:13766`) | доставлено **1**; сгенерировано **≤2** в bounded-переоценке | первый текст не доставляется вовсе (не «переписывается»); проход формы выполняется по фактическому тексту (`:13725`) | single-writer (доставка) — уточнить в Q2 |
| 15 | Отказ провайдера / LLM outage | `except LLMError` (`:5551`) → `CHAT_ERROR_PHRASES`; initiative: `writer_failed` (`:13699`) | **0** | фиксированные фразы; возврата в legacy-текст нет | no-writer |
| 16 | Fallback-модель провайдера | `llm_client` ноги + `build_l2_fallback_adapter` (`:7585`, `_dx`) — та же стадия, защищённые блоки (вопрос/evidence/system) | **1** | пересборка payload, текст пишет одна модель (фоллбэк-нога); `semantic_rewrite_count` не растёт | single-writer |
| 17 | Отказ L1-планера | `l1_plan is None` → `_l1.fallback_plan(...)` + дет. capabilities (`:4297`–`:4336`) | **1** (`l2_writer`) | как в (1); planner_fallback_reason в телеметрии | single-writer |
| 18 | L2 пустой ответ / отказ | `_l2 is None` (`:5254`) или пустой `answer` (`:5340`) → тишина/🗿 либо дет. clarification | **0** | нет текста | no-writer |
| 19 | Длинный ответ / `finish_reason=length` | longform-план → `max_tokens=longform_max_output_tokens` (`:4466`); фактический `finish_reason` первого авторского вызова читает `_l2_cont.complete_truncated_answer` (`direct_chat_service:7913`, `step="l2_continuation"`; `services/l2_continuation.py`), потребители `is_truncated` есть | **1** (продолжение — ТОТ ЖЕ автор: написанный фрагмент идёт как assistant-реплика с явной границей накопленных токенов, system/user/план/evidence не меняются; не второй вариант с нуля) | склейка без дублей: точное эхо «хвост написанного → голова продолжения» снимается один раз, слово на стыке целое, «.» сразу после цифры — десятичная точка; `MAX_CONTINUATION_CALLS` ограничивает, `stop_reason` отдаётся наружу; невозможность продолжения — честный отказ (`IncompleteContinuation` → `None` вызывающего), обрезок не публикуется | single-writer |
| 20 | deep_research / отчёт (Rich ↔ HTML ↔ plain) | `response_plan.delivery_hint=="rich"` → `_rich_wanted` (`:5446`) → `_send_direct_answer`: rich (`:7716`) → safe-HTML (`:7739`) → plain (`:7754`) | **1** | три ветки одного текста; `strip_lore_html`/`escape_lore_html` — разметка, не смысл; fail ветки не перегенерируют | single-writer |
| 21 | Рассказ «Летописца» (`ctx.lore_compiled`) | L2 вызывается (`:5229`), затем `lore_story_override` (`:5287`) подменяет `answer` готовым текстом (`lore_compiler_service:242`, LLM `lore_writer`) | доставлен **1** (`lore_writer`), но в том же ходу сгенерирован и L2-текст | numeric-гард к рассказу не применяется (это авторская речь модели), см. `RLR-04` fix `d69f52da` | needs-check (Q4) |
| 22 | Factcheck: двухвызовный (Stage-1 JSON → Вербализатор) | `SYSTEM2_FACTCHECK_ENABLED` ON (`factcheck_service:2138`) → `_check_claim_two_call` (`:2177`): аналитик (`:2190`) → `verbalize_validated` (`:2267`) | **1** финальная (`stage2`); Stage-1 — структурный JSON, не речь | `_finalize_text` (`:2279`): `cleanup_llm_text`, `strip_phantom_tags` (детерминированно снимает выдуманные даты), `strip_lore_html`; при неподтверждённых числах — дет. отчёт (`:2289`) | single-writer |
| 23 | Factcheck: одиночный путь (kill-switch OFF или fallback после Stage-1) | `SYSTEM2_FACTCHECK_ENABLED` OFF либо `_check_claim_two_call` вернул `None` (невалидный JSON/сбой) → ветка 10.21 (`:2147`–`:2175`), один `_invoke_llm` | **1** (тот же Writer, без Stage-1-структуры) | тот же `_finalize_text`; критик-блок считается по наличию evidence, а не по структуре claims | single-writer |
| 24 | Factcheck: временной вердикт | `_temporal_verdict_json` (`:2860`) → `_temporal_verbalize` (`:2877`, `verbalize_validated` `:3005`) | **1** | `cleanup_llm_text` + `strip_reasoning_tags`; при неподтверждённых числах — `deterministic_temporal_report` (`:3025`) | single-writer |
| 25 | Factcheck: детерминированный структурный отчёт | `deterministic_analysis_report` (`:2289`) / `deterministic_temporal_report` (`:3025`) / `_temporal_fallback_text` (`:3030`) | **0** | сборка из кода по verified-структуре | no-writer |
| 26 | Summary System2: редактор → Рассказчик | Stage-1 редактор выдаёт JSON-handoff digest (`summary_generator:4192`) → Рассказчик через `verbalize_validated` (`:4248`) | **1** (`summary narrator`) | заголовок/обложка детерминированно (`:4260`), `pipeline_events` | single-writer |
| 27 | Summary L2 (документный контур): writer + bounded review/revision | `summary_l2_writer.run_l2` (`:1573`, 1 вызов + ≤1 correction) и `summary_l2_review` (writer 1 + reviewer ≤3 + revision ≤2, бюджет 6, `summary_l2_review:136`), master `SUMMARY_L2_REVIEW_ENABLED` | **1–2** (bounded loop внутри L2-стадии документа) | patch/full-document revision; это документный продукт, не разговорная реплика Direct/Initiative | needs-check (Q5) |
| 28 | Плановая текстовая инициатива (nostalgia, `prepared_text`) | `nostalgia_worker` генерирует текст (`nostalgia_worker:1792`) → `handle_initiative(prepared_text=...)` (`:1143`) → L2 не вызывается (`:13624`) | **1** (`nostalgia_worker`) | `_style_initiative_text` + SendRecheck (как в 11) | single-writer |
| 29 | Плановые медиа-релеи (goodmorning/common/dead_page/olya) | `goodmorning_relay:133`, `common_relay:192`, `dead_page_relay:693`, `olya_relay:72` — отправка файла + caption из источника | **0** | caption берётся из исходного контента, LLM не пишет | no-writer |
| 30 | Meme-инициатива (картинка) | `meme_initiative.consider_chat` → `_deliver_deferred_row` → `sender(chat_id, content, prompt)` (`:2895`), prompt **не** уходит caption | **0** | учёт/брони/ledger; текст в чат не отправляется | no-writer |
| 31 | Явная просьба «перепиши/переведи» | обычный ход → L2; сигнал — функциональное поле плана L1 `preserve_source_facts` (канон EVR5: `direct_l1:339/679`, секция контракта в `chat_prompts:1478-1497`); при true И реально поданном исходнике `_explicit_transform_contract` (`direct_chat_service:2709`) в шве `handle` строит `FormContract(source_text=<исходник>)` и передаёт её в `_l2_write_answer` (`:5423-5445`) | **1** | узкая проверка protected facts (числа/даты/отрицания — со скриптовой проверкой `_has_cyrillic`, имена ростера) ТОЛЬКО для явной трансформации с поданным исходником; сводка/пересказ и свободная речь — `form_contract=None` и уходят как написаны (один вызов Writer'а); нарушение → возвращается исходник, а не литературная правка | single-writer |
| 32 | Совпавший текст двух разных событий | `evaluate_duplicate` только наблюдает (`:5360`–`:5382`); duplicate-reroll удалён | **1** на событие | текст доставляется как написан; идемпотентность — по идентичности события, не по тексту | single-writer |
| 33 | Смерть/перезапуск после отправки | `check_update_seen`/`mark_update_seen` (`:3680`) поверх **durable SQLite** `smart_cache` (24 ч), маркировка ДО обработки (`response_freshness:118-128`); ledger `record_delivered_output` (`:5519`); брони публикаций в initiative/meme | **0** при повторной доставке того же update | повторной отправки того же логического ответа быть не должно; для Direct нет выделенного restart-теста | needs-check (Q7) |
| 34 | Нет ключа/квота (sandbox) | `NoApiKeyForChat` (`:4288`, `:4885`) → `_sandbox_no_key_reply` (`:6259`) | **0** | фиксированная фраза `content.no_key_reply` | no-writer |

Итог по строкам: **35** путей; **18** `single-writer`, **13** `no-writer`,
**4** `needs-check` (2b, 21, 27, 33). Строки 19 и 31 пересняты на HEAD
`9ca6bb07` (Q3 и Q6 решены); остальные — снимок `c8d9866e`.

## 3. Спец-случай A — factcheck: одиночный вызов и fallback без Stage-1

- Гейт: `settings.SYSTEM2_FACTCHECK_ENABLED` (default ON,
  `factcheck_service:2138`).
- ON → `_check_claim_two_call`: Stage-1 «Аналитик» (`_invoke_llm`, `step=stage1`)
  выдаёт **структуру** (findings/verdict/response_mode), а не публичную речь.
  Финальный текст пишет один `verbalize_validated` (`stage2`, `:2267`).
- Fallback в одиночный путь 10.21 (`:2147`) включается в трёх случаях:
  kill-switch OFF, исключение Stage-1 (`:2193`), невалидный JSON аналитика
  (`:2204`). В этом пути **нет структуры claims/sources**, поэтому:
  - критик-директива считается по наличию evidence, а не по вердикту
    (`:2161`–`:2165`);
  - числовой контракт строится только из writer-payload (data-stage
    metric_results отсутствуют), а неподтверждённые числа ведут к
    детерминированному отчёту, не к правке фразы;
  - автор по-прежнему один, второго писателя/судьи нет.
- Итог: обе ветки = 1 финальная авторская генерация; различаются источником
  структуры, а не числом авторов.

## 4. Спец-случай B — медиа, доставленное инструментом

- Список инструментов, доставляющих файл сами: `tool_loop:116`
  `MEDIA_DELIVERY_TOOLS = {download_media, generate_image, edit_image}`;
  успех = канонический `status=="ok"` (`tool_loop:334`).
- Решение «нужен ли Writer»: `response_extent.media_writer_needed` (`:754`) —
  только для плана с `delivery_hint=="media"`. Тогда `_media_skip=True`
  (`:5216`) и L2 не вызывается: **0** авторов, дубля текста нет.
- Если план не media (например, файл — побочный результат), L2 пишет
  сопровождающий текст: **1** автор, файл уже у пользователя.
- Картинки: `generate_image`/`edit_image` ставят `ctx.image_request_handled` /
  `tool_ctx.image_delivered`; текст хода подавляется (`:5395`), аварийные фразы
  тоже (`:5585`, `:5602`) — «MEME-IMAGE-ONLY», промпт в caption не уходит
  (`meme_initiative:2895`).
- Риск, который нельзя закрыть статикой: send/idempotency для медиа проверяется
  в R-08.19 живым прогоном.

## 5. needs-check — точные вопросы (без догадок)

| № | Путь | Вопрос, который нельзя решить статикой |
|---|---|---|
| Q1 | 2b, tool-дайджест | Считать ли LLM-сводку инструмента (`summarize_video`, `tool_router:2443`) «промежуточным свободным авторским черновиком» по §8 R-08.2, или это отдельный продуктовый инструмент, чей текст допустим как evidence? Если недопустим — нужен evidence-режим «только выдержки», это меняет контракт tool-слоя (и требует проверки остальных tool-дайджестов) |
| Q2 | 14, §18D-переоценка | Разрешает ли §8 R-07/DoD §10 вторую генерацию в bounded-переоценке инициативы (первый текст не доставляется), или требуется один генератор с детерминированной перепроверкой условий после генерации? |
| Q3 | 19, `finish_reason=length` | **Решено (RLR-08.14, ветка 673677a1, merge `8eb6893b`):** continuation размещён в L2-стадии того же автора — `services/l2_continuation.py`, шаг `step="l2_continuation"`, явная граница накопленных токенов, без второго «варианта с нуля»; исчерпанный лимит/сбой провайдера не публикуют обрезок (честный отказ). R-08.14 VERIFIED: `tests/test_rlr_length_continuation.py` (17 passed на дереве 8eb6893b) |
| Q4 | 21, рассказ «Летописца» | Должен ли L2 вообще вызываться при `ctx.lore_compiled` (сейчас генерируется текст, который затем подменяется текстом `lore_writer`)? Это лишняя платная генерация и два авторских текста в одном ходу |
| Q5 | 27, summary L2 review/revision | Bounded reviewer/revision (≤2 ревизии, `SUMMARY_L2_REVIEW_ENABLED`) — это документный контракт саммари (сохранить) или попадает под запрет §10 «нет post-L2 reroll»? Формулировка DoD говорит о Direct/Initiative reply |
| Q6 | 31, явная трансформация | **Решено (RLR-03.3, ветка c39e371d, merge `15e8bcc3`):** контракт подключён на Direct-пути от поданного исходника по сигналу `preserve_source_facts` (EVR5); сводка/пересказ осознанно БЕЗ контракта (защита честного пересказа от отката в эхо исходника), свободный ход без контракта. Скриптовая проверка отрицаний (`_has_cyrillic`) не ломает честный перевод латиницы. R-03.3 VERIFIED: `tests/test_rlr_explicit_transform.py` (12 passed на дереве 8eb6893b) |
| Q7 | 33, restart after send | Достаточно ли durable update-маркера (SQLite, 24 ч, маркировка ДО обработки) как доказательства «нет второй отправки», или нужен отдельный тест на уровне процесса (новый процесс + повторная доставка update) для Direct? |

## 6. Покрытие R-08 на этом HEAD

Дублирующие по смыслу сценарии покрываются одним тестом; ниже — минимальный
достаточный экземпляр с файлом и именем.

| Требование | Покрытие | Тест (file::test) |
|---|---|---|
| R-08.1 без tools → один L2 | да | `tests/test_asap7_direct_l1.py::TestGatesTopologyLegacy::test_topology_two_semantic_calls_on_reply_path`; `tests/test_rlr_verbalize_scope.py::test_free_form_text_with_all_diagnostics_is_delivered_as_written` |
| R-08.2 tools/evidence → один L2 | да (см. Q1 про дайджест) | `tests/test_rlr_no_second_author.py::TestToolFactsReachTheSingleWriter::test_evidence_pack_delivered_to_l2_with_attribution`; `tests/test_evol_evidence_routing.py::test_wave3_direct_sets_claim_keys_and_budget_before_tools` |
| R-08.3 инициатива reply/silent/react | да | `tests/test_asap8_f6_initiative.py::test_i4_reply_generates_via_existing_writer_and_sends`, `::test_i5_silent_sends_nothing`; `tests/test_evol_evidence_routing.py::test_scenario28_initiative_silent_makes_no_calls` |
| R-08.4 L1 off / старый флаг | да | `tests/test_rlr_no_second_author.py::TestNoSecondAuthor::test_flag_on_l1_off_tool_loop_is_the_only_author`, `::test_no_flag_value_restores_a_second_writer`; `tests/test_asap7_direct_l1.py::TestGatesTopologyLegacy::test_l1_off_legacy_byte_parity` |
| R-08.5 совпавший текст двух событий | да | `tests/test_rlr_dcs_postprocess.py::test_two_events_same_text_are_two_answers`, `::test_same_event_redelivery_is_blocked` |
| R-08.6 отрицания не правятся после L2 | да | `tests/test_bgs0304_negation_contract.py::test_free_generation_has_no_negation_gate`, `::test_no_second_generation_even_when_model_could_fix` |
| R-08.7 «не без таланта», «неделя», «небо» | да | `tests/test_bgs0304_negation_contract.py::test_ordinary_ne_ni_words_are_not_negation_cues`, `::test_ne_ni_prefix_words_produce_no_cue`; `tests/test_bgs0304_speech_observation.py::test_no_extra_generation_for_style_or_format` |
| R-08.8 мат/сарказм/странная речь | да | `tests/test_bgs0304_speech_observation.py::test_natural_phrase_passthrough_byte_identical`; `tests/test_rlr_verbalize_scope.py::test_free_form_text_with_all_diagnostics_is_delivered_as_written` |
| R-08.9 неподтверждённый факт при недоступном поиске | да | `tests/test_evol_evidence_routing.py::test_scenario7_categorical_nonexistence_is_observed_not_deleted`, `::test_scenario16_guard_hit_makes_no_second_call_and_keeps_joke` |
| R-08.10 stats/измерения | частично | `tests/test_mca15_chat_statistics_round1028.py::TestNumericGuardSendPaths::test_contract_from_ctx_claims_and_expected` (MetricResult→writer), `tests/test_rlr_dcs_postprocess.py::test_free_form_number_delivered_as_written` — нет теста «все числа в ответе пришли из MetricResult» |
| R-08.11 явный rewrite/translate | да | продовый шов: `tests/test_rlr_explicit_transform.py::test_explicit_rewrite_that_breaks_protected_facts_returns_source` (нарушение → исходник, не литературная правка), `::test_faithful_rewrite_is_delivered_as_written`, `::test_contract_signal_comes_from_the_plan_field_only`, `::test_free_form_reply_has_no_form_contract`; контракт: `tests/test_rlr_verbalize_scope.py::test_explicit_rewrite_validates_protected_facts_without_second_author`, `::test_explicit_rewrite_that_keeps_facts_is_delivered_as_written` |
| R-08.12 factcheck многосоставного утверждения | да | `tests/test_rlr_factcheck_numeric_stage.py::test_insufficient_evidence_stays_insufficient`, `::test_refuted_verdict_reports_without_softening` |
| R-08.13 невалидная схема tool-call | да | `tests/test_tool_loop.py::test_crushed_arguments_wrapped_by_loop`; `tests/test_rlr_verbalize_scope.py::test_invalid_machine_json_is_repaired_in_machine_stage_only` |
| R-08.14 `finish_reason=length` → продолжение | да | `tests/test_rlr_length_continuation.py::test_truncated_answer_is_continued_once_with_prefix` (тот же автор, префикс-граница), `::test_repeated_tail_is_removed_exactly_once` (эхо снимается ровно один раз), `::test_join_keeps_word_and_space_boundaries` (стык слова, десятичная точка), `::test_cap_exhausted_does_not_publish_truncated_text` и `::test_provider_error_during_continuation_is_honest` (честный отказ), `::test_continuation_is_not_a_semantic_rewrite` |
| R-08.15 fallback/отвал провайдера | да | `tests/test_rlr_no_second_author.py::TestNoLegacyFallbackFromL2::test_provider_error_is_honest_not_draft_not_second_author`; `tests/test_llm_completion_metadata_ur18.py::test_generate_string_unchanged_in_fallback`; `tests/test_direct_fallback_recompose_asap32.py` |
| R-08.16 HTML/Rich/plain один текст | да | `tests/test_rlr_dcs_postprocess.py::test_invalid_html_renders_same_text_plain`; `tests/test_mca23_phase2.py` (rich fail → plain, тот же документ) |
| R-08.17 длинная реплика / chunking | да | `tests/test_smartmodule_utils.py::test_long_text_chunked_reply_only_on_first`, `::test_chunks_do_not_break_words` |
| R-08.18 `no_quotes`/`no_emoji` один проход | да | `tests/test_rlr_dcs_postprocess.py::test_owner_rules_single_pass_and_protected_spans`; `tests/test_soul1_style_policy.py` |
| R-08.19 отправленная картинка/файл без второго текста | да | `tests/test_p0_meme_image_only.py::test_b_explicit_request_success_sends_only_the_image`, `::test_a_initiative_success_sends_only_the_image`, `::test_f2_llm_error_after_delivered_image_adds_no_text`; идемпотентность: `tests/test_initiative_coordination.py::test_duplicate_job_does_not_create_second_output_row` |
| R-08.20 перезапуск после отправки | частично | `tests/test_initiative_coordination.py::test_restart_reclaims_expired_claim_without_second_publication`; `tests/test_evol031_smart_cache_retirement.py::test_update_marker_roundtrip`. Для Direct ответа отдельного restart-теста нет → Q7 |
| R-08.21 негативные сценарии в реальных конфигах/гейтах | **нет** | прогон «матрица гейтов × сценарии» как один тест отсутствует |

### Рабочий список RLR-07 (сценарии без покрытия)

1. ~~**R-08.14**~~ — выполнено (ветка 673677a1, merge `8eb6893b`):
   `services/l2_continuation.py`, продолжение того же ответа с явной границей
   накопленных токенов; тесты `tests/test_rlr_length_continuation.py`
   (17 passed на дереве 8eb6893b).
2. **R-08.20** — restart-after-send для Direct: новый процесс, durable
   update-маркер, повторная доставка того же update не даёт второй отправки.
3. **R-08.21** — единый прогон негативных сценариев на реальных гейтах
   (`DIRECT_L1_ENABLED` on/off, `SYSTEM2_DIRECT_ENABLED` any,
   `SYSTEM2_VALIDATOR_LOOP_ENABLED` on/off, `SPEECH_STYLE_POLICY_ENABLED`,
   `SYSTEM2_FACTCHECK_ENABLED`, `SUMMARY_L2_REVIEW_ENABLED`), а не на моке
   идеального пути.
4. **R-08.10 (дополнить)** — тест «числа в доставленном ответе совпадают с
   `MetricResult` хода» на реальном пути stats, а не только на контракте.
5. ~~**R-08.11 (дополнить)**~~ — выполнено (RLR-03.3, ветка c39e371d,
   merge `15e8bcc3`): контракт подключён на Direct-пути от поданного
   исходника по сигналу `preserve_source_facts` (EVR5); прод-шов покрыт
   `tests/test_rlr_explicit_transform.py` (12 passed на дереве 8eb6893b).

## 7. Что подтверждено по R-07

- R-07.1 (достижимость всех перечисленных путей на HEAD) — таблица §2,
  все 35 строк привязаны к call sites/гейтам.
- R-07.2 (не по grep имени: import graph, call sites, toggles, реальные
  конфигурации/рантайм) — §1: проверены точки вызова `verbalize_validated`,
  отсутствие `_synthesize_direct_answer`, резолв флагов в
  `settings.py`/`direct_l1.py`, потребители `media_delivered`,
  `is_truncated`; фактическое число прогонов тестов указано.
- Открытые вопросы Q1, Q2, Q4, Q5, Q7 (Q3 и Q6 решены — строки 19 и 31
  пересняты на HEAD `9ca6bb07`) — единственное, что мешает закрыть R-07/R-08
  формально; выдуманных выводов в таблице нет.

## 8. Воспроизведение

```
git rev-parse HEAD                     # c8d9866e2d740f7d51fd9cc5a7610e07ee6138ae (снимок матрицы)
git rev-parse HEAD                     # 9ca6bb07 — актуальный HEAD зон 19/31 (refresh 2026-11-05)
python -m pytest tests/test_rlr_no_second_author.py \
  tests/test_rlr_verbalize_scope.py tests/test_rlr_dcs_postprocess.py \
  tests/test_rlr_factcheck_numeric_stage.py -q      # 57 passed
```
