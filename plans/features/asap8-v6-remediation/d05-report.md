# D05 — Experience hybrid detector / durability / scope / usefulness (ASAP 8 v6, P1)

Lane: P1-D05 · Baseline: HEAD `2ef6189` · Режим: writer · Статус: implemented, не закоммичено

## Что сделано (по контракту v6 D05 §C / v5 §18E)

### 1. Hybrid production feedback entry (§18E.1) — `services/mca_experience_jobs.py`
Детерминированный semantic detector обычного чата (worker-проход, батч
`review_batch_max`, БЕЗ LLM) как шаг 1b `_detect_chat_feedback` внутри
существующего durable-job `experience.review` (тот же singleflight/checkpoint;
`services/memory_maintenance.py` НЕ менялся — точка вызова `_tick_experience_review`
уже в worker-цикле).
- Чистая классификация `classify_chat_message`: приоритет сомнительного — шутка /
  агрессия / мнение третьего лица / спор / forward / команда / репля другому
  участнику → deliberate skip с кодом причины (никогда не истина/lesson);
  high-confidence: preference (закрытый набор «ключ.значение»: address.*,
  reply_length.*, reply_language.*), коррекция ошибки/процесса (2-е лицо),
  перволичная фактическая самокоррекция («я не из …» → fact_user).
- Кто говорит: `ADMIN_USER_ID` → owner/participant_correction; reply-target
  (tg_message_id → smart_messages) — ответ ДРУГОМУ участнику = спор → skip.
- Запись — только через существующий `record_feedback` (candidate ≠ fact ≠
  lesson; K1/K2-гейты, dedup_key = sha1(source_kind, chat, "chat_message", msg_id));
  `signal` — только типизированные коды/числа (class, preference token,
  user_id/author_user_id, msg, reply_to) — R17, сырой текст не хранится.
- Telemetry: события `detector_scan` (скан/детект/skip/сбои + коды причин) и
  `detector_signal` (по кандидату) через единственный `emit_mca_event`.

### 2. Долговечность (§18E.2/X1) — курсор только после durable обработки
- Новый durable курсор `cursor_message_rowid` (+ наследование из терминального
  прогона, как остальные курсоры).
- `_detect_chat_feedback` / `_capture_feedback` / `_capture_tool_events`:
  курсор продвигается ТОЛЬКО после успешной записи ИЛИ deliberate skip;
  технический сбой записи → курсор остаётся на предыдущей строке, pass
  останавливается, счётчик `capture_write_failures` → следующий проход
  повторяет (idемпотентно: dedup_key/idempotency_key → ровно один durable event).

### 3. Ключи уроков (§18E.3/X2)
`_lesson_exists` включает subject (`applicability`, напр. `tool:A` vs `tool:B`;
пользовательская preference `user:N pref:key.value`); P1 передаёт applicability;
пустой applicability нормализован в "" (P2-уроки), NULL-legacy учтён. Повтор
того же события → skip (идемпотентность сохранена).

### 4. Конкретность preference (§18E.4/X3)
- Applicability несёт нормализованную форму `user:<id> pref:<key>.<value>`
  (закрытый набор + синонимы + `custom.<token>` для safe-токенов ручного API);
  сырой текст пользователя не сохраняется, рекомендация — только канон.
- Идемпотентный повтор (тот же ключ+значение) → skip; явная поздняя замена
  (тот же ключ, другое значение) → `lesson.revise` → новая версия, старая
  superseded (не инжектируется: `list_scope_candidates` отдаёт только active).
- Анти-ping-pong: P3 обходит feedback в порядке rowid DESC — новейший сигнал
  ключа выигрывает, старые конфликтующие — deliberate skip
  (`preference_superseded_signals`); плюс защита по ts.
- Provenance: durable ссылка на сообщение-источник в signal (`msg`) и
  evidence-link `derived_from` → SourceRef(message) у урока.

### 5. Resume неполных кандидатов (§18E.5/X4)
`_resume_incomplete` — каждый проход находит актуальные версии в статусе
candidate/validated и доводит их: validated → activate (crash после verify);
candidate → повторная детерминированная валидация (preference — по durable
provenance из feedback-сигналов fail-closed; generalization — по evidence links).
Семантический отказ (мало эпизодов / нет provenance) ≠ transient failure:
строка остаётся candidate и пере-проверяется следующим bounded проходом —
эпизоды накапливаются → eventual validation.

### 6. Справедливость outcomes (§18E.6/X5)
`_link_outcomes`: структурно несопоставимые строки (нет chat/trace) исключены
из скана (deliberate skip, остаются unknown, счётчик `outcomes_unmatchable`);
вращающийся durable курсор `link_scan_application_id` (+наследование) с wrap
при окне < limit — старые permanently-unknown не блокируют новые matchable;
unknown остаётся unknown (не авто-success, не удаление).

### 7. Scope (U4)
Детектор гейтится `learning_enabled_for_chat` ДО записи: global master OFF →
job честно `disabled`, все чаты молчат, stored per-chat override не читается на
запись и не переписывается; ON + chat OFF → skip только этого чата (курсор
продвигается). Уроки — scope chat/user_in_chat, never global (детектор не
создаёт shared технических уроков — только существующий классифицированный
технический источник tool_call).

### 8. Operator UI (§18E.7/U8) — `web/index.html` + `web/app.js`
- Человеческая цепочка «Заметил исправление → Выделил возможный урок →
  Проверил → Сохранил → Применил позже → Помогло/Не помогло/Пока неизвестно»:
  в существующем виде «Самообучение» oversight (`data-d05="chain"`) и в
  существующей карточке «Опыт и уроки» Памяти (`data-d05="memory-chain"`).
- Полезность `lessonUsefulness`: known_pos/(known_pos+known_neg) + sample →
  «80% · 10 известных», unknown отдельно («? 7»); < 5 известных → «Недостаточно
  данных» (не 0%); нет данных → строка не рендерится; per-lesson колонка
  «Полезность» в таблице уроков. Без «AI IQ».
- Данные — существующая read-only воронка `GET /api/oversight/experience/funnel`
  (глобальный админ; ленивая догрузка при входе в Память + watcher
  isGlobalAdmin на позднюю авторизацию) и существующий `/api/memory/lessons`.
- Попутный точечный фикс необходимой связки: `loadLessons` строила
  `/api/memory/lessons&chat_id=…` (нет `?`) при выбранном чате → 404; теперь
  `_cidQuery(true)`.

## Тесты
`tests/test_asap8_v6_d05_experience.py` — НОВЫЙ, 18 тестов
(TEST-LIFECYCLE: CONTRACT owner=asap8-v6/D05; реальный sqlite DatabaseService):
E2E preference-коррекция → candidate → active → match → applied → outcome;
E2E owner-факт-коррекция ×3 → failure_pattern (порог 3 НЕ ослаблен);
негативы (шутка/агрессия/третье лицо/спор/forward/команда/«я не знаю») — ни
feedback, ни уроков, deliberate skip с курсором; reply-другому-участнику = спор;
X1 (сбой записи → курсор на месте → retry → ровно 2 события; сбой capture —
без потери); X2 (два инструмента → два scoped урока; ретрай идемпотентен);
X3 (замена supersede'ит, старая не инжектируется, анти-ping-pong); X4 (crash
после create/после verify → resume; semantic rejection → eventual validation);
X5 (новая matchable за старой unknown; unmatchable исключены и посчитаны,
unknown сохранён); U4 (master OFF → disabled + override не переписан; chat OFF
локален; урок чата A не в чате B); R17 (signal без текста) + OFF-гейт.
`tests/js/asap8_v6_d05_experience_ui_test.js` — НОВЫЙ (node): usefulness 8/10 →
«80% · 10 известных» + unknown 7; sample<5 → «Недостаточно данных»; chain из
воронки; disabled → null; ленивый single-flight фетч только у админа.

## Результаты прогонов (текущий candidate)
- `pytest tests/test_asap8_v6_d05_experience.py tests/test_mca16_experience_block_{a..f}_round1039.py tests/test_asap8_f5_module_truth.py tests/test_webapp_oversight_ui.py -q`
  → **131 passed**
- `node tests/js/*.js` (весь набор 77 файлов) → **0 failed**
- Обратно-совместимость: существующие mca16 (74), f5 (M6/U4), webapp/oversight
  пиры — зелёные на изменённом коде.

## Визуальные проверки (обязательные)
1. **Playwright (детерминированные flow-проверки)** — реальный web/index.html +
   app.js на локальном стаб-сервере (scratch `d05_visual_server.py`):
   `#/memory/rag` → `data-d05="memory-chain"` с точными числами и «Полезность:
   80% · 10 известных»; таблица уроков: колонка «Полезность» = «80% · 10
   известных · ? 7» и «Недостаточно данных · ? 2»; `#/oversight?view=learning` →
   `data-d05="chain"` + `data-d05="usefulness"`; негативный режим (малая
   выборка) → «Недостаточно данных»; desktop 1280×800 и mobile 390×844 —
   без console errors, без новой горизонтальной переполненности страницы.
   Скриншоты: `OPENCODE_WORKFLOW_SCRATCH/d05_memory_lessons_{desktop,mobile}.png`,
   `d05_oversight_learning_desktop.png`.
2. **Browser Use (реальный рендер Chrome)** — та же страница в живом Chrome:
   memory-chain и oversight chain/usefulness отрендерены (тексты совпадают),
   реальный скриншот oversight-вида подтверждает визуальную целостность
   (существующая воронка/«Эффект» сохранены, новые блоки в той же визуальной
   системе: badge-и, border, text-xs; шкал «IQ» нет).

## Изменённые файлы (в границах WRITE_SCOPE)
- `services/mca_experience_jobs.py` — детектор, X1/X2/X3/X4/X5, курсоры,
  счётчики (продакшен-вход + долговечность).
- `web/app.js` — lessonUsefulness/d05ExperienceChain, ленивая догрузка воронки,
  watcher, фикс `loadLessons` (? vs &).
- `web/index.html` — цепочка+полезность в «Самообучение» и в карточке
  «Опыт и уроки», колонка «Полезность».
- `services/memory_maintenance.py` — НЕ менялся (точка вызова детектора —
  существующий `_tick_experience_review` в worker-цикле).

## Incidental findings
- `related-nonblocking`: карточка «Опыт и уроки» на mobile шире вьюпорта
  (grid-item растёт от широкой таблицы; было и до D05 при 9 колонках, ~969px;
  сейчас ~1132px) — горизонтальный скролл внутри `overflow-x-auto`; зонa D13
  (universal mobile shell). Мои блоки не усугубляют: цепочка переносится/flex-wrap
  + overflow-x-auto, полезность — в существующей таблице.
- `unrelated/pre-existing`: page-level overflow 207px на `#/memory/rag` из-за
  `CANVAS.aurora-flow-canvas` (декоративный фон), одинаково с/без моих блоков.
- `fixed-in-pass` (necessary для виджета): `loadLessons` с `&` вместо `?`
  ломала таблицу уроков при выбранном чате.

## Остаточный риск / ограничения
- Детектор v1 — детерминированные русские паттерны (без LLM-классификации —
  по брифу опционально); соотношение полнота/точность на живом чате подлежит
  прод-наблюдению через `detector_scan` telemetry (коды причин). Ложные
  срабатывания не становятся истиной (candidate + валидация + ≥3 эпизода для
  generalization).
- Каденция детектора = каденция review-job (hourly/daily/weekly, default daily)
  — «по расписанию worker'а», не realtime.
- Live/prod-проверка на реальном чате — не входит в lane (нет деплоя из writer);
  отмечено как owner/DevOps gate.
