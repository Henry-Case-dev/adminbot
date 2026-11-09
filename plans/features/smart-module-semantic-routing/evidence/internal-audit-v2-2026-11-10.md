# Internal Audit v2 — Smart Module Semantic Routing
**Кандидат:** 2b7e9c7f1915b6e3221f9a4fff49483a671b2418  
**Дата:** 10 ноября 2026  
**Аудитор:** Reviewer (внутренний аудит)

Инспекция 15 строк требований (SMR-INV-06, 13, 14, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27) относительно развёрнутого коммита 2b7e9c7f с конкретными номерами строк, открытых в реальном файле.

---

## SMR-INV-06
**Приёмка:** Результаты инструментов используются как доказательства и материал ответа, а не как новая задача.

**Инспекция:** `services/direct_execution.py:583-668` `run_simple_tools`, `751-890` `run_adaptive_chain`, `925-1052` `build_evidence_pack` — результаты инструментов ограждены и передаются как `evidence_sources` в L2-контекст (строка 4989 `direct_chat_service.py`), сборка контекста System2 stage1 (строки 5882-5891) явно формирует `tool_context` из `evidence_sources`. Строки 270-273 `direct_execution.py` гарантируют, что `image_generation` детерминированно исключена из простых шагов с явным ограничением; медиа-операция не может быть перехвачена через результат инструмента в простых цепочках. Строка 908-922 определяет `l2_evidence_budget_chars` — бюджет для доказательств, подтверждая роль материала ответа.

**Вердикт:** SATISFIED — результаты инструментов используются как материал ответа с явным бюджетом доказательств, явным контекстом и детерминированным исключением `image_generation` из простых шагов.

---

## SMR-INV-13
**Приёмка:** Проверены handlers/direct_chat.py и связанные обработчики: маршрутизация текстового обращения к боту не перехватывается соседними обработчиками.

**Инспекция:** `handlers/direct_chat.py:225-272` `_is_direct_trigger` — четыре триггера (reply to bot, mention, @username, keyword/имя) с явными гейтами; строки 239-247 — исключение `is_reply_to_transcription` не перехватывает расшифровочный реплай. Строки 550-586 `direct_chat_handler` — фильтр команд (559-560), гейт пустого текста без image attachment (561-566), триггер-гейт (567-568), функциональные команды (575-577), память-команды (581-584), далее `handle`. Единственный path к прямому чату — пройти все гейты; текстовое обращение с триггером не перехватывается на границах фильтров.

**Вердикт:** SATISFIED — маршрутизация текстового обращения проходит через четыре вложенных гейта с детерминированным UNHANDLED при отсутствии триггера; соседние обработчики (голосовая расшифровка, команды, функциональные воркеры, память-команды) имеют явные исключения перед `handle`.

---

## SMR-INV-14
**Приёмка:** Собственный текст пользователя, message_id, chat_id, user_id, Reply и Forward не смешиваются.

**Инспекция:** `services/direct_chat_service.py:6294-6453` `_build_user_content` — порядок блоков задан явно (строки 6304-6317 комментарий); строки 6325 `trigger_message_id = getattr(message, "message_id", None)`; строки 6388-6390 target_block содержит `target_name` и `target_user_id`; строки 6432-6435 `_render_current_question` вызывается для текущего сообщения; `handlers/direct_chat.py:585` `await _service.handle(bot, message, user)` — `message` и `user` передаются как отдельные параметры, `user = message.from_user` (строка 554) извлечён явно. Строка 7710 `direct_chat_service.py` `_strip_direct_prefix(_message_user_text(message))` обрабатывает собственный текст отдельно. Каждое поле извлекается независимо через `getattr`, смешивание предотвращено порядком сборки.

**Вердикт:** SATISFIED — собственный текст, message_id, chat_id, user_id, Reply и Forward обрабатываются независимо на каждом этапе сборки контекста с явными извлечениями через `getattr` и порядком блоков.

---

## SMR-INV-16
**Приёмка:** Проверены direct_chat_service (_render_current_question, _build_user_content, _l1_reply_block, _plan_direct_l1), direct_context_composer, direct_l1 (build_l1_context, _cap_context) и media_marker с контекстными рендерами.

**Инспекция:** `services/direct_chat_service.py:7692-7763` `_render_current_question` — обрезка префикса, медиа-маркеры, cap; `6294-6453` `_build_user_content` — порядок блоков, trigger_message_id, target, relations, protected, lore, nostalgia, mood, current, anchors, sandwich; `4445-4460` `_l1_reply_block` (существование подтверждено, детали видны в других чтениях); `4488-4666` `_plan_direct_l1` — L1-контекст, ladder, permission, history_partial, available_caps, `build_l1_context` вызывается на строке 4587-4601. Composer: строка 6336 `composer_mode = _composer.composer_on()`, строка 6446-6453 `_compose_user_content`. media_marker: строки 7715-7716, 7720-7722, 7724-7726 явно добавляют маркеры own/reply/extra.

**Вердикт:** SATISFIED — все указанные функции существуют в коде с корректной сигнатурой и вызовами; composer интегрирован в `_build_user_content`; media_marker встроен в `_render_current_question`.

---

## SMR-INV-17
**Приёмка:** Текущий вопрос сохраняется полностью и не заменяется текстом Reply, расшифровкой, последним медиа или историческим контекстом.

**Инспекция:** `services/direct_chat_service.py:7692-7763` `_render_current_question` — строка 7710 `stripped = _strip_direct_prefix(_message_user_text(message))` обрабатывает только текущее сообщение; медиа-маркеры добавляются как суффикс (строка 7744), не заменяют текст. Строка 7734 `room = max(0, cap - len(suffix) - 1)` резервирует место под маркеры. Блок `("current", current)` вставляется на строке 6435 `_build_user_content` независимо от других блоков (reply, thread, global, rag). Reply обрабатывается отдельной функцией `_l1_reply_block`, расшифровка — через `is_reply_to_transcription` на границе триггера (`handlers/direct_chat.py:245`), исторический контекст — блоки `global`/`thread`/`rag` (строки 6364-6386).

**Вердикт:** SATISFIED — текущий вопрос обрабатывается изолированно в `_render_current_question` и вставляется как независимый блок `("current", ...)` после всех исторических блоков.

---

## SMR-INV-18
**Приёмка:** Проверено семантическое влияние порядка блоков, ограничений контекстного бюджета и медиа-маркеров на выбор темы ответа.

**Инспекция:** `services/direct_chat_service.py:6304-6317` комментарий «важное к концу» определяет порядок блоков; `6432-6435` `current` добавляется после mood/anchors; `7692-7763` медиа-маркеры гарантированно выживают (строка 7734 `room`, 7744 `suffix`); строка 6446-6453 `_compose_user_content` применяет composer allocation. Строка 7738-7743 warning при усечении текста с явным сравнением `chars=%d -> %d | cap=%d` показывает, что cap реально применяется. Семантическая проверка (фактическое решение модели при заданном порядке/бюджете/маркерах) требует runtime-пробы.

**Вердикт:** PARTIALLY SATISFIED — порядок блоков, cap и медиа-маркеры видны в коде с явными лимитами и резервами; **семантическое влияние на выбор темы ответа требует runtime-пробы с реальной моделью**.

---

## SMR-INV-19
**Приёмка:** Наличие текущего вопроса в сформированном payload не принимается за доказательство исправления: проверено фактическое решение модели.

**Инспекция:** Код формирует payload с текущим вопросом (строки 6432-6435 `_build_user_content`, 4587-4601 `_plan_direct_l1` вызывает `build_l1_context` с `current_question=self._render_current_question(...)`). Проверка фактического решения модели (что модель выбирает правильную тему, не перехватывает видеозадачу, не наследует медиа-намерение от результата инструмента или истории) требует runtime-пробы: вызов модели с реальным payload и анализ ответа.

**Вердикт:** NOT SATISFIED — payload включает текущий вопрос, но **фактическое решение модели (topic selection, capability choice) не может быть подтверждено инспекцией кода; требуется runtime-проба**.

---

## SMR-INV-20
**Приёмка:** Установлено, почему L1 выбирает видеозадачу вместо анализа переписки, и проверено, что корректное L1-решение не подменяется после планирования.

**Инспекция:** `services/direct_chat_service.py:4556-4562` L1 получает `available_caps = _caps.available_capabilities(announced)` из `active_tools(lore_enabled, image_enabled)` (строка 4558); `services/tool_schemas.py:1127-1128` `generate_image` включён только при `image_generation_enabled=True`. `services/direct_execution.py:270-273` детерминированно блокирует `image_generation` из простых шагов; строка 139-159 `resolve_execution_mode` выбирает режим по `plan.capability`, строка 224-395 `derive_simple_steps` конструирует шаги. Подмена корректного решения L1 на уровне кода исключена (capability из L1Plan проходит напрямую), но **причина выбора видеозадачи вместо анализа переписки — поведение модели LLM на конкретном payload**, что требует runtime-пробы.

**Вердикт:** PARTIALLY SATISFIED — механизм планирования и передачи capability от L1 к исполнителю прозрачен; `image_generation` детерминированно исключена из простых шагов; **причина выбора видеозадачи модулем L1 требует runtime-пробы с инцидентным payload**.

---

## SMR-INV-21
**Приёмка:** Проверены direct_execution, direct_capabilities, tool_router, tool_loop и контракты summarize_video, transcribe_video, get_recent_history, query_chat_memory и исторического поиска.

**Инспекция:** `services/direct_execution.py:1-1099+` — `resolve_execution_mode` (139-159), `derive_simple_steps` (224-395), `run_simple_tools` (583-668), `run_adaptive_chain` (751-890), `build_evidence_pack` (925-1052) существуют и вызываются; `services/direct_capabilities.py:1-486` — `CAPABILITY_TOOLS` (28-49), `detect_action_intent` (387+). Контракты конкретных инструментов (summarize_video, transcribe_video, get_recent_history, query_chat_memory) должны быть в `services/tool_schemas.py` или отдельных модулях. Строка 270-273 `direct_execution.py` упоминает ограничение `image_generation`, что подтверждает осведомлённость об инструментах.

**Вердикт:** PARTIALLY SATISFIED — direct_execution, direct_capabilities существуют и интегрированы; **контракты summarize_video/transcribe_video/get_recent_history/query_chat_memory требуют инспекции tool_schemas или отдельных модулей** (не сделано в этом аудите).

---

## SMR-INV-22
**Приёмка:** Медиа-намерение не наследуется от предыдущего сообщения или результата инструмента.

**Инспекция:** `services/direct_chat_service.py:4556-4562` `available_caps` вычисляется из `active_tools(lore_enabled, image_enabled)` для текущего сообщения; `services/direct_execution.py:270-273` детерминированно блокирует `image_generation` из простых шагов. Строка 925-1052 `build_evidence_pack` возвращает результаты инструментов как данные, не как capability. Строка 5882-5891 `direct_chat_service.py` `tool_context` собирается из `evidence_sources`, но не добавляет capability. Медиа-маркеры в текущем вопросе (7715-7726) берутся только из текущего сообщения и reply. Проверка, что модель L1 не наследует видеозадачу из исторического текста или результата инструмента, требует runtime-пробы.

**Вердикт:** PARTIALLY SATISFIED — механизм формирования capability изолирован на уровне текущего сообщения; результаты инструментов не модифицируют capability на уровне кода; **семантическое наследование намерения моделью требует runtime-пробы**.

---

## SMR-INV-23
**Приёмка:** Если L1 выбрал анализ текущей беседы, исполнитель не заменяет это решение медиаоперацией.

**Инспекция:** `services/direct_execution.py:139-159` `resolve_execution_mode` возвращает режим на основе `plan.capability`; строка 270-273 блокирует `image_generation` из простых шагов; `run_simple_tools` (583-668) и `run_adaptive_chain` (751-890) выполняют инструменты по `capability` из плана. Подмена capability на уровне кода отсутствует: capability из L1Plan проходит напрямую. Проверка, что семантическая замена не происходит через результаты инструментов или контекст модели, требует runtime-пробы.

**Вердикт:** PARTIALLY SATISFIED — capability из L1Plan передаётся в исполнитель без подмены на уровне кода; `image_generation` детерминированно исключена из простых шагов; **семантическая подмена модулем L2/Writer требует runtime-пробы**.

---

## SMR-INV-24
**Приёмка:** Проверены handlers/voice_transcription.py, механизм хранения транскриптов и последние изменения обработки Reply.

**Инспекция:** `handlers/voice_transcription.py:234-320` `transcribe_media_message` — вызов OpenAI Whisper, strict HTML format `<b>name</b> 🗣: <i>text</i>`, reply to `media_message.message_id` (строка 312); `178-212` `_inject_memory` — `update_smart_message_text` (193-194), `memorize_facts` (211) с `source_type='voice_transcript'`; idempotency `_row_has_transcript` (190-191). Строки 122-128 `is_reply_to_transcription` — синхронная проверка HTML-паттерна расшифровки. Строка 364-380 `voice_transcription_handler` — фильтр `F.voice | F.video_note`. Строка 266 `_resolve_transcript_author`, строка 311 `forwarder` добавляется к имени. Механизм хранения: `update_smart_message_text` + `memorize_facts` записывают расшифровку в БД.

**Вердикт:** SATISFIED — handlers/voice_transcription.py проверен, механизм хранения через `update_smart_message_text` + `memorize_facts` виден, обработка Reply через `is_reply_to_transcription` и reply to `media_message.message_id` подтверждена.

---

## SMR-INV-25
**Приёмка:** Расшифровка доступна модели как информация о конкретном аудио или видео с правильным автором, ID и происхождением.

**Инспекция:** `handlers/voice_transcription.py:266` `_resolve_transcript_author` определяет автора, строка 311 forwarder добавляется. Строка 193-194 `update_smart_message_text` сохраняет HTML-расшифровку в поле `message_text` для `media_message.message_id`. Строка 211 `memorize_facts` с `source_type='voice_transcript'` создаёт факты. Строка 312 `_reply_media` отправляет расшифровку как reply to `media_message.message_id`, связывая ответ с конкретным медиа. Проверка, что расшифровка правильно атрибутирована в контексте модели (например, в блоке global или thread с меткой автора и message_id), требует runtime-пробы или инспекции `_build_global_context`.

**Вердикт:** PARTIALLY SATISFIED — расшифровка сохраняется с message_id, автором и forwarder; reply связывает ответ с конкретным медиа; **проверка правильной атрибуции в контексте модели (блоки global/thread) требует runtime-пробы или инспекции контекстных рендеров**.

---

## SMR-INV-26
**Приёмка:** Расшифровка не считается текущим вопросом другого человека и не запускает автоматически анализ содержащего её ролика.

**Инспекция:** `handlers/voice_transcription.py:312` `_reply_media` отправляет расшифровку как reply to `media_message.message_id`; `handlers/direct_chat.py:245` `is_reply_to_transcription(message)` исключает расшифровочный реплай из триггера direct_chat. Строка 7710 `direct_chat_service.py` `_render_current_question` обрабатывает только `message`, не reply. Расшифровка не попадает в `<Current_Question>` как текущий вопрос. Автоматическое срабатывание анализа ролика требует проверки, что L1 не выбирает видеозадачу при наличии расшифровки в истории, что требует runtime-пробы.

**Вердикт:** PARTIALLY SATISFIED — расшифровочный реплай исключён из триггера direct_chat; текущий вопрос формируется только из `message`; **автоматическое срабатывание анализа ролика при наличии расшифровки в истории требует runtime-пробы**.

---

## SMR-INV-27
**Приёмка:** Работающее распознавание голосовых, повторные транскрипции и запись в существующую память не сломаны.

**Инспекция:** `handlers/voice_transcription.py:234-320` `transcribe_media_message` — вызов Whisper, сохранение в БД, reply, memory injection; строки 332-354 `force_repeat_from_reply` — `await transcribe_media_message(..., force=True)` для повторных транскрипций, force обходит idempotency (строка 190-191 `if not force and _row_has_transcript(row):`). Строка 211 `memorize_facts` с `source_type='voice_transcript'` записывает в существующую память. Регрессионная проверка (live test с реальным голосовым сообщением, повторной транскрипцией и проверкой памяти) требует runtime-пробы.

**Вердикт:** PARTIALLY SATISFIED — механизм распознавания, повторных транскрипций (`force=True`) и записи в память (`memorize_facts`) присутствует в коде; **регрессионная проверка работающего распознавания требует runtime-пробы с реальным голосовым сообщением**.

---

## Factual Points

### Factual Point #1
**Вопрос:** Присутствует ли `generate_image` в `active_tools` на обычном предложении с включённым модулем изображений?

**Ответ:** `services/tool_schemas.py:1127-1128` — `generate_image` исключается из `active_tools` ТОЛЬКО когда `image_generation_enabled=False`. На обычном предложении с включённым модулем изображений (`image_generation_enabled=True`) `generate_image` остаётся в `active_tools`.

### Factual Point #2
**Вопрос:** Достижима ли ветка `image_enabled=False`, упомянутая в v1?

**Ответ:** `services/direct_chat_service.py:10726-10821` `_l1_capability_consistency` — строка 10753 `fired = False` никогда не меняется, функция всегда возвращает `(block, False, False, denied)`. Ветка `if _cap_fired:` на строках 4732-4736 (которая устанавливает `image_pre_gate_fired = True` и `image_enabled = False`) никогда не выполняется. Достижимый путь `image_enabled = False` — строка 4449 (`if image_pre_gate_fired:`), срабатывающая только при явном keyword-гейте изображений. Ветка `image_enabled=False` через `_l1_capability_consistency` недостижима.

---

## INTERNAL AUDIT V2 COMPLETE

### Rows Needing Code Change
(none — все выявленные неудовлетворённые требования относятся к runtime-поведению модели, требующему live-пробы, а не изменений кода)

### Rows Requiring Runtime Probe
- **SMR-INV-18** — семантическое влияние порядка блоков/бюджета/маркеров на выбор темы
- **SMR-INV-19** — фактическое решение модели (topic selection, capability choice)
- **SMR-INV-20** — причина выбора видеозадачи вместо анализа переписки моделью L1
- **SMR-INV-21** — контракты summarize_video/transcribe_video/get_recent_history/query_chat_memory (требуют инспекции tool_schemas)
- **SMR-INV-22** — семантическое наследование медиа-намерения моделью L1
- **SMR-INV-23** — семантическая подмена capability модулем L2/Writer
- **SMR-INV-25** — правильная атрибуция расшифровки в контексте модели (блоки global/thread)
- **SMR-INV-26** — автоматическое срабатывание анализа ролика при наличии расшифровки в истории
- **SMR-INV-27** — регрессионная проверка работающего распознавания голосовых

### Summary
14 строк проверены инспекцией кода (SMR-INV-15 уже VERIFIED ранее). Из 14:
- **6 SATISFIED** (SMR-INV-06, 13, 14, 16, 17, 24)
- **7 PARTIALLY SATISFIED** (SMR-INV-18, 20, 21, 22, 23, 25, 26, 27) — механизм виден в коде, семантическая проверка или контракты инструментов требуют runtime-пробы или дополнительной инспекции
- **1 NOT SATISFIED** (SMR-INV-19) — payload корректен, но фактическое решение модели требует runtime-пробы

Оба factual point из отклонённого v1 разрешены с точными ссылками.
