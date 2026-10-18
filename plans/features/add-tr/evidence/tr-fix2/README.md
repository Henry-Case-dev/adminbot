# TR-FIX2 — reply-путь Direct: MessageRef фото + claim reply-фактчека

Лейн: **TR-FIX2** (живая приёмка **2.58.91**, findings 3/5 + оценка 4).
Кандидат-база: `aea597485a32` (HEAD, docs p0v acceptance-91 cleanup).
Прод/SSH не использовались; всё воспроизведено и проверено локально.
Коммита нет — слайс на ревью.

## Рут-причины

### 1. reply-на-фото → неверный MessageRef — ЭТО ПРОДУКТ (не харнесс)

Живое: `recognize_image target=1165613` (ответ бота) вместо фото `1165606`.

Разбор процедуры харнесса (`harness/accept91_live.py`, scenario_vision):
* синтетический reply-ход строился как `msg_id=anchor.message_id` (id
  последнего реального ответа бота, 1165613), `reply_to_message` = фото
  1165606 — т.е. **id текущего сообщения был переиспользован** (в реальном
  Telegram новое сообщение получило бы свежий id). Это fidelity-оговорка
  харнесса, но она **не является причиной**:
* продукт вообще не смотрит на `reply_to_message` в этом пути: цель
  дет. шага `image_understanding` бралась из
  `ToolContext.reply_to_message_id`, а он в `direct_chat_service` ставится
  = `message.message_id` (текущее сообщение-вопрос), см.
  `services/direct_execution.py` (ветка `image_understanding`);
* воспроизведение обеих вариантов (харнесс-точный id ответа бота и «живой»
  свежий id) даёт одинаковый неверный результат — доказательство:
  `red-head.txt` (`assert 999 == 700` и `assert 1000 == 700`), тест
  `TestReplyPhotoTarget::test_live_sequence_harness_message_id` /
  `::test_live_sequence_fresh_message_id` (RED на `aea597485a32`);
* двухходовая последовательность (своё фото → ответ бота → reply на ДРУГОЕ
  фото) показывает, что дело не в «последнем медиа»: ход 1 целится верно
  (640), ход 2 — в текущее сообщение (999) вместо replied-фото (700).

**Фикс**: медиа-цель хода разрешается один раз в `direct_chat_service`
(своё медиа сообщения (A) → текущее, иначе reply-медиа (B) →
`reply_to_message` — тот же приоритет, что у канонических маркеров
`_render_current_question`), кладётся в `ToolContext.media_target_message_id`
и используется дет. деривацией и fallback'ом `_recognize_image`.

### 2. CFG-06: claim из reply-вопроса — ЭТО ПРОДУКТ

Живое (`scenario-4-exact.json`): «бот, это правда?» → tool вызван, но
`claim = «бот, это правда?»`, target = триггер, не в `smart_messages` →
`temporal_envelope_rejected`; explicit+registered → `ready/supported`.

Разбор: канонический reply-фактчек 0g (`handlers/factcheck.py`) берёт claim
из replied-сообщения; tool-путь так не умел вовсе — в `ToolContext` не было
ни текста replied-сообщения, ни его id (только id-триггер). Отсюда и
наблюдаемый claim-вопрос. Плюс envelope-цель для reply-кейса должна быть
replied-сообщение (источник claim'а), а не сообщение-вопрос.

**Фикс (единый пайплайн `fact_check`, без второго пути)**:
* `ToolContext` получил `reply_source_message_id` / `reply_source_text`
  (replied-сообщение; заполняет `direct_chat_service`);
* `temporal_factcheck.is_referential_claim()` — референтные формы
  («это правда?», «проверь его слова», «не врёт?»); собственный claim
  («правда ли, что …») и нереферентные вопросы («как работает фактчек?»)
  не подменяются;
* дет. деривация (`derive_simple_steps`) и адаптер `ToolRouter._fact_check`
  (LLM-путь) применяют одно правило: claim := текст replied-сообщения,
  target := replied-сообщение; дальше — тот же envelope-путь.

### 3. L1 cold start — НЕ в этом лейне (backlog-note)

Первый/второй L1-вызовы в процессе: ровно 15.0 с → timeout →
`fallback=deterministic`; тёплый — 2.2 с. Разбор и варианты:
`backlog-l1-coldstart.md` (правка кода соразмерной не признана: корень —
внешний холодный HTTP-путь провайдера/сети, наблюдался в отдельном
harness-процессе; стартовый warmup не переживает простой, а поднятие
первого таймаута/ретрай — продуктовый трейд-офф, не мой). Код НЕ менялся.

## Изменения (файлы + sha12 контента)

| файл | sha12 | что |
|---|---|---|
| `services/direct_chat_service.py` | `6de9b0d1ef39` | разрешение `media_target_message_id` + `reply_source_*` в `ToolContext` |
| `services/direct_execution.py` | `c4b48bcb14c9` | цель `image_understanding` из media-цели; референтный claim/target для `fact_check` |
| `services/tool_router.py` | `7eb2a253d5c3` | поля `ToolContext`; fallback `_recognize_image`; нормализация claim/target в `_fact_check` |
| `services/temporal_factcheck.py` | `dba596979239` | `is_referential_claim()` (+ регекс референтных форм) |
| `tests/test_tr_fix2_reply_ref.py` | `005f77983cc0` | новые тесты (8) |

`services/mca_vision.py` и `web/api/routes.py` НЕ трогались (лейн V-FIX2).

## Тесты (RED → GREEN)

Новый файл `tests/test_tr_fix2_reply_ref.py` (TEST-LIFECYCLE: REGRESSION
owner=TR-FIX2/live-25891):
* точная живая последовательность (photo → ответ бота → reply к фото):
  харнесс-точный id и «живой» свежий id; двухходовая версия с ДРУГИМ фото
  (не «последнее медиа»);
* CFG-06: reply «бот, это правда?» при зарегистрированном replied-сообщении
  → `ready`, claim = текст replied-сообщения, `mca_factcheck_runs.target_tg_message_id`
  = replied-сообщение; сквозь реальный ход (L1 → simple_tools → единый
  пайплайн) — те же claim/target в дет. шаге и в envelope-ссылке;
* границы детектора: «это правда?»/«проверь его слова»/«не врёт?» → True;
  «как работает фактчек?», «правда ли, что …», собственный текст → False;
* паритет: без media-цели деривация остаётся прежней (текущее сообщение).

Артефакты: `red-head.txt` (+ `red-head-raw.txt` — полный вывод) — RED на
`aea597485a32`, `green.txt` (8/8), `green-affected.txt` (affected-sweep,
142 файла: **4059 passed, 2 failed** — оба pre-existing, доказано прогоном
на чистом `aea597485a32`: `test_migration_v35_idempotent_twice`,
`test_backup_guard_fires_before_pending_step`, `assert 36 == 35` — пины
миграций v35 при актуальной v36).

## Что проверять в повторной живой приёмке

1. reply-на-фото («бот, прочитай надпись» на фото): в tool-args
   `recognize_image target` = **id фото из reply** (не текущего сообщения);
   own-media ход — цель = своё сообщение (паритет).
2. reply «бот, это правда?» на сообщение пользователя с утверждением:
   claim = текст replied-сообщения, target = replied-сообщение, ожидаемый
   исход — `ready` (при рабочем провайдере/кэше), не
   `temporal_envelope_rejected`; «как работает фактчек?» — обычный ответ без
   подстановки.
3. (backlog) L1 cold start: замерить первый L1-вызов после рестарта —
   см. `backlog-l1-coldstart.md`.

## Оговорки / incidental findings

* **V-FIX2 параллельно правит `services/mca_vision.py`,
  `web/api/routes.py` и их тесты** в этом же рабочем дереве. Во время моих
  батч-прогонов из-за этого транзиентно падали 3 routes-пина
  (`test_round1025_f8_registry::test_routes_file_unchanged`,
  `test_mca23_planned_vs_actual::test_routes_pin_untouched`,
  `test_mca10b...block_d::test_blockE_f8_check_green_and_baselines`) — это
  их re-pin в процессе; после их синхронизации пинов батч зелёный (кроме
  pre-existing). Также их новый тест
  `test_p0_vision_fix_core::test_fix2_backfill_rearms_transient_terminal_job`
  падает (`IntegrityError mca_media_analyses`) — WIP их лейна, к TR-FIX2
  отношения не имеет (мой диф не касается mca_vision/анализов).
* Транзиент: `test_p0_init_arch_fix_observer::...full_opportunity[20]`
  упал в одном батч-прогоне (`counters["sent"] == 0`), в повторных
  прогонах и на HEAD зелёный — таймингозависимый флейк, не связан с диффом
  (мой диф не касается initiative_observer).
* 2 pre-existing падения (миграционные пины v35) — вне TR-FIX2, чинить не
  в этом лейне.
