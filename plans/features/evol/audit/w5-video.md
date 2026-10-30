# W5 — видео: запрос → репост → одна выжимка (EVOL §4)

Кандидат: worktree `evol/impl` @ `18baa36b` + незакоммиченный дельта этой задачи.
Ветка: `evol/impl`. Коммитов не делалось (по указанию оркестратора).

## 1. Что было сломано на реальном HEAD (адресный аудит)

Проверены фактические точки: `handlers/youtube.py` (`_triggered_body`,
`_classify_video_request`, `_resolve_video_media`, `youtube_handler`),
`handlers/direct_chat.py` (функциональный yield), `handlers/video_download.py`
(Fast-Track «скачай»), `services/native_media.py`, `services/command_registry.py`,
`services/command_prefix.py`, `services/smartmodule_phrases.py`, порядок роутеров
`bot.py` (0a observer → 0e youtube → 0f web → 0h direct → 4e download).

Найденные причины (не «симптомы»):

1. **Просьба без медиа отвечала мгновенно.** `_classify_video_request` → `None`
   → `youtube_handler` сразу отправлял `COMMAND_NO_TARGET_PHRASES`
   («а ссылку-то приложить?»). Подтверждённый сценарий §4.1 (сначала просьба,
   потом отдельным сообщением ролик) физически не мог сработать.
2. **Естественная просьба не распознавалась как видео-запрос.**
   Канонические триггеры youtube — только `транскрипт / че за видос /
   о чем видео / поясни за видос`. «Сделай выжимку видео» не входило ни в одну
   группу (`выжимка` — триггер группы `web`, причём с якорем `^`), поэтому
   сообщение уходило в LLM/direct-путь, а там решение принимала модель
   (отсюда «не вижу видео» и случайный выбор `download_media`).
3. **Не было связи «запрос ↔ сообщение-носитель».** Медиа, пришедшее
   следующим сообщением, никто не сопоставлял с запросом: у запроса не было ни
   `media_tg_message_id`, ни `correlation_id`, ни ключа идемпотентности.
4. **Дубли дорогой работы.** Два участника, спрашивающие про один ролик, давали
   два независимых анализа и два ответа; кулдаун списывался дважды.
5. **Противоречащие ответы.** Один и тот же запрос мог быть отвечен и
   youtube-веткой, и обычным LLM-путём (никакого «потребления» запроса на
   ожидании не было).

## 2. Что реализовано

### Новый модуль `services/video_intent.py` (733 строки, ΔDDL = 0)

Единое разрешение намерения **и** источника ДО любого media-tool:

* `VideoIntent`: `chat_id`, `request_tg_message_id`, `request_user_id`,
  `intent ∈ {summary, transcript, download, describe, unknown}`,
  `media_tg_message_id`, `media_owner_user_id`,
  `source_kind ∈ {native_video, video_document, video_note, url,
  platform_forward, unresolved}`, `source_ref` (`file_unique_id` / нормализованный
  `yt:<id>` / хеш пути URL), `resolution ∈ {resolved, waiting, ambiguous,
  unavailable}`, `reason_code`, `correlation_id`, `job_id`.
* Приоритет источника §4.2: 1) reply/цитата с медиа → 2) медиа/URL в самом
  запросе → 3) окно соседства того же чата/ветки → 4) ожидание медиа после
  запроса. На шагах 3–4 берётся **только однозначный** кандидат: сначала
  сообщения *после* запроса, затем *до*; внутри набора обязан быть один
  `source_ref`, иначе `ambiguous` (случайная подстановка исключена).
* Окно соседства — ограниченное кольцо на чат (`limits.video_intent_window_messages`,
  `limits.video_intent_window_max_age_seconds`), ветка (`message_thread_id`)
  обязана совпадать → нет кросс-чат/кросс-топик привязки.
* Pending-намерения (§4.3) — короткоживущий реестр в памяти, тот же паттерн, что
  существующий `_PENDING` меню качества в `handlers/video_download.py`: **новых
  таблиц/очередей нет**. TTL — общая конфигурация
  `limits.video_intent_pending_ttl_seconds` (fallback
  `settings.VIDEO_INTENT_PENDING_TTL_SECONDS = 90`). Истечение TTL → **ровно
  один** ответ с просьбой прислать ролик (запись удаляется до отправки, повторный
  `expire` не дублирует). Реестр in-memory: рестарт не привязывает старый запрос
  к чужому ролику и не публикует дубль (задним числом намерение не воскресает).
* Single-flight (§4.4): ключ `chat_id + source_ref + операция (+ версия)`.
  Почти одновременные запросы к тому же ролику дают **один** дорогой анализ,
  остальные — `joined_existing_job` без второго ответа и **без повторного
  списания кулдауна**.
* Наблюдаемость (§4.5): `emit()` с ограниченным кольцом событий и
  `correlation_id`; события `request_seen`, `waiting_for_media`, `media_matched`,
  `media_ambiguous`, `joined_existing_job`, `analysis_started`,
  `multimodal_success` / `transcript_fallback`, `delivered`, `failed` + коды
  причин. R17: в лог попадают только `chat_id`/`message_id`/код причины и
  **8-символьный хеш** ссылки на источник — сырые URL, `file_id` и тексты не
  логируются (проверено тестом).
* Классификаторы текста — единственный источник истины: `detect_intent`
  (summary / transcript / describe / download / unknown) и
  `DOWNLOAD_TRIGGER_RE`, который теперь использует и `handlers/video_download.py`.

### `handlers/youtube.py`

* `_VideoRequest` дополнен `source_ref`, `correlation_id`, `intent` и свойством
  `operation`; метаданные заполняются в `_with_meta` (классификация сохранена,
  публичная `_classify_video_request` — тонкая обёртка, поэтому существующие
  тесты классификации не менялись).
* `youtube_handler` стал тремя шагами: (1) наблюдение медиа/ссылок чата и
  привязка **ожидающих** запросов (`_observe_and_bind_pending` → медиа,
  закрывшее ожидание, потребляется этим путём), (2) канонический путь через
  единую точку исполнения `_dispatch_video_request`, (3) `_handle_unclassified`
  для естественных формулировок.
* `_dispatch_video_request` — единственное место, где решается «новая работа или
  join», где списывается кулдаун и где выбирается ветка (youtube / native /
  url / voice). Раньше эта логика была размазана по телу хендлера.
* `_handle_unclassified`: намерение + адресованность боту (`Бот,/Имя,` или reply
  на бота). `download` → `UNHANDLED` (это 4e, не анализ). Окно соседства
  применяется только при видео-контексте запроса — иначе «Бот, <веб-ссылка>
  выжимка» привязалось бы к чужому ролику из истории (найдено и исправлено
  регрессом `test_epic37_router_isolation`). `ambiguous` → один уточняющий
  ответ. Иначе — pending без мгновенного «видео нет».
* Кружок/голосовое: «транскрипт» по-прежнему идёт в существующий форс-повтор STT
  (0i, F19 не изменён); выжимка по кружку идёт существующим путём
  `_process_video_media` (мультимодалка → STT-фолбэк) и помечается событием
  `transcript_fallback` с причиной `audio_only_source` — транскрипция не выдаётся
  за просмотренное видео.
* `_emit_req`/`_emit_summary`: события в существующих ветках (native, url,
  youtube+summary/transcript) — `analysis_started`, `multimodal_success`,
  `transcript_fallback`, `delivered`, `failed` с кодами причин.

### `handlers/video_download.py`

* `_TRIGGER_RE = video_intent.DOWNLOAD_TRIGGER_RE` — один классификатор
  «скачивания» на два обработчика (анализ сюда не попадает).
* `request_seen` с `intent=download` и `correlation_id` — операция «скачивание»
  отделена от анализа в наблюдаемости. Публичный файл отдаётся только по
  явному «скачай/загрузи/стяни».

### `handlers/direct_chat.py` — изменений НЕ потребовалось (осознанно)

Роутер 0e (`bot.py:912`) исполняется **до** 0h direct_chat (`bot.py:922`), и
естественный видео-запрос теперь потребляется на 0e. Добавлять ещё одно правило
yield в direct_chat значило бы создать второго арбитра маршрутизации и вернуть
исходный дефект «один запрос — несколько задач». Проверено существующими
тестами `test_direct_chat*`, `test_command_registry_round1015` (yield-контракт),
`test_epic37_router_isolation` (web не потребляется youtube).

### Конфигурация и фразы

* `config/settings.py`: `VIDEO_INTENT_PENDING_TTL_SECONDS` (90),
  `VIDEO_INTENT_WINDOW_MESSAGES` (12), `VIDEO_INTENT_WINDOW_MAX_AGE_SECONDS` (900)
  — читаются через `hot.get("limits.video_intent_*", settings.…)`, т.е. общая
  конфигурация, а не скрытые константы.
* `services/smartmodule_phrases.py`: пул 5.14 `VIDEO_INTENT_EXPIRED_PHRASES`
  (просьба прислать ролик) и 5.15 `VIDEO_INTENT_AMBIGUOUS_PHRASES` (два ролика
  рядом) — заводской редактируемый текст, стиль существующих пулов.

### Тесты

* Новый `tests/test_evol_video_intent.py` — 17 тестов (8 сценариев §4.5,
  часть параметризована).
* `tests/conftest.py`: autouse-фикстура `_reset_video_intent_state` — изоляция
  окна/pending/jobs между тестами и отключение фонового watchdog в тестах
  (иначе соседнее медиа одного теста привязывалось к запросу следующего: тот же
  `CHAT_ID`).
* Контрактные пины, которые проверяли **отменённое** поведение, обновлены
  вместе с реализацией: `test_command_registry_round1015`
  (`..._trigger_without_target_awaits_media`: нет мгновенной фразы, есть pending
  и ровно один ответ по TTL), `test_youtube_video_media`
  (`..._broken_media_resolve_does_not_crash`: консьюм + один ответ по TTL),
  `test_round106_ia_smoke` (source-пин гейта `flags.video_summary_enabled` под
  новую форму `getattr(request, "mode", "") == "summary"`; пины каталога:
  Settings 465→468 из-за трёх новых полей, REGISTRY/GROUPS/TAB_RULES без роста).

## 3. Маршруты обработки (фактические)

| Ситуация | Путь | Видимый результат |
|---|---|---|
| «Бот, сделай выжимку видео» → пересланный ролик отдельным update | 0e: pending → `observe` привязывает ролик → `_dispatch_video_request` → `_process_video_media` (мультимодалка → STT-фолбэк) | один анализ, один ответ реплаем на сообщение с роликом |
| Ролик/URL **до** запроса | 0e: окно соседства → `window_before_request` | один ответ реплаем на ролик |
| Прямой reply на ролик | 0e: приоритет reply → `reply_media` | ответ на процитированный ролик (соседи игнорируются) |
| Два участника про один ролик | single-flight: второй — `joined_existing_job` | один исходящий итог, кулдаун списан один раз |
| Рядом два разных ролика | `ambiguous` | один уточняющий вопрос, анализа нет |
| «Скачай» | 4e `video_download_handler` (`intent=download`) | файл |
| «Сделай выжимку» | 0e анализ | текстовый ответ, **файла нет** |
| Кружок / forwarded / document(video/*) / платформенная ссылка / нет файла | классификация `video_note` / `platform_forward` / `video_document` / `url` / `waiting` | честный фолбэк (STT-выжимка, фраза провайдера) без имитации просмотра |
| Медиа не пришло / пришло в другой чат / TTL истёк | pending остаётся в своём чате, `expire` | ровно один ответ «перешли ролик»; кросс-чатовой привязки нет |

## 4. Результаты проверок

Офлайн, без живых отправок в Telegram (bot — `AsyncMock`, все внешние границы
замоканы: скачивание файла, публикация `/media`, LLM, STT).

* `tests/test_evol_video_intent.py` — **17 passed**.
* Затронутые/смежные наборы (youtube, video, media, native, direct_chat,
  routing, command registry, IA smoke, epic37 isolation, download):
  **854 passed, 0 failed** (прогон: `test_video_router`, `test_youtube_video_media`,
  `test_youtube_handlers`, `test_video_download`, `test_video_cascade`,
  `test_video_stt_timeouts`, `test_native_media_tools_round1024`,
  `test_native_reply_media_context_round1024`, `test_media_transcribe_tool_round1024`,
  `test_hotfix_round1025_media`, `test_media_share`, `test_media_download`,
  `test_direct_chat`, `test_direct_chat_handlers`,
  `test_command_registry_round1015`, `test_round106_gates`, `test_round106_ia_smoke`,
  `test_p0_delta_routing`, `test_epic37_router_isolation`, `test_evol_video_intent`).
* Сценарии §4.5 — все 8 покрыты и PASS (см. ниже).

| # | Сценарий | Тест | Итог |
|---|---|---|---|
| 1 | просьба → пересланный ролик отдельным update | `TestLateVideo::test_request_then_forwarded_video_one_analysis_one_reply` (+ строгая последовательность событий по `correlation_id`) | PASS |
| 2 | видео/URL до запроса | `TestMediaBeforeRequest::test_video_before_request_binds_from_window` | PASS |
| 3 | прямой reply на видео приоритетнее соседей | `TestReplyPriority::*` | PASS |
| 4 | два участника, один ролик → single-flight | `TestSingleFlight::test_two_users_same_video_one_analysis_one_reply` | PASS |
| 5 | два разных ролика → ambiguous | `TestAmbiguous::test_two_videos_ambiguous_no_random_pick` | PASS |
| 6 | «скачай» vs «сделай выжимку» | `TestOperations::*` | PASS |
| 7 | кружок / forwarded / document / платформа / нет файла | `TestSourceClassification::*` (4 теста) | PASS |
| 8 | медиа не пришло / другой чат / TTL | `TestPendingExpiry::*` (3 теста) | PASS |
| — | наблюдаемость без утечек | `TestLateVideo::test_no_raw_refs_in_events` | PASS |

## 5. Остаточные риски и честные ограничения

1. **Адресованность боту обязательна** для естественных формулировок
   («Бот,/Имя,» или reply на бота). Сообщение «сделай выжимку» без обращения и
   без канонического триггера намеренно НЕ перехватывается (иначе бот забирал бы
   обычную речь группы). Канонические триггеры (`транскрипт`, `че за видос`, …)
   работают как раньше.
2. **Pending-реестр in-memory.** После рестарта ожидание теряется молча (без
   дубля и без привязки к чужому ролику) — это осознанный компромисс вместо
   durable-очереди: §4.3 требует «существующий механизм, без новой тяжёлой
   очереди», а durable-запись повышала бы риск привязки старого запроса к новому
   ролику. Поведение: пользователь не получит ответ по истёкшему ожиданию —
   повторная просьба создаст новую работу.
3. **Повторный запрос после завершённого анализа — новая работа** (ответного
   кеша нет, EVOL-031 его удалил); идемпотентность ограничена single-flight на
   время выполнения. Это соответствует формулировке «кулдауны применяются к
   новой работе».
4. **Формулировки-синонимы** покрыты регулярками (`выжимк|перескаж|суть|
   краткое содерж`, `транскрипт|расшифров`, `че/что за видос|что происходит|
   опиши видео`). Экзотические формулировки могут не распознаться и уйдут в
   обычный путь — это деградация без ложного перехвата.
5. **Кружок/голосовое**: визуальный анализ не заявляется; при недоступной
   публикации файла выжимка строится по транскрипту и это видно в событиях
   (`transcript_fallback` / `audio_only_source`).
6. Живой прогон в реальном Telegram не выполнялся (задача требует офлайн-тестов
   §4.5); фактическая доставка проверена на моках Telegram API.

## 6. Побочные находки (не мои, не блокируют)

* `tests/test_youtube_multimodal_download_round1024.py` — 18 ошибок настройки:
  фикстура патчит `youtube_mod.get_smart_cache`, которого нет уже на HEAD
  (EVOL-031 удалил exact-match cache). Проверено: `git show HEAD:handlers/youtube.py`
  не содержит `get_smart_cache`. Это устаревший пин, требующий отдельной
  выравнивающей правки, не относящейся к §4.
* `tests/test_asap7_direct_settings.py` (2) и
  `tests/test_direct_fallback_recompose_asap32.py` (5) падают и на HEAD
  (проверено прогоном на чистом HEAD-чекауте) — не связаны с видео.
* `tests/test_native_reply_media_context_round1024.py` — 3 теста падают только
  в большом комбинированном прогоне (порядок), по отдельности и в парах
  проходят; область — композер прямого контекста (другая полоса работ).
  Требует отдельной изоляции состояния, к §4 не относится.

## 7. Git-гигиена

* Изменены (мои файлы): `config/settings.py`, `handlers/youtube.py`,
  `handlers/video_download.py`, `services/smartmodule_phrases.py`,
  `tests/conftest.py`, `tests/test_command_registry_round1015.py`,
  `tests/test_youtube_video_media.py`, `tests/test_round106_ia_smoke.py`.
* Новые: `services/video_intent.py`, `tests/test_evol_video_intent.py`,
  этот отчёт.
* `handlers/direct_chat.py` не изменялся (обоснование в §2).
* Создан вспомогательный чистый detached-worktree для сверки с HEAD:
  `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\evol-w5-video-baseline-81e00d6218f1-66e65637`
  (без уникальных коммитов; передать DevOps для `epic-close`/удаления).

## 8. §review-fix (31.10.2026) — два блокера ревью

Кандидат: `evol/impl` @ `3a0f89d2` + дельта этого review-fix. Офлайн-проверки,
живых отправок в Telegram нет (bot — `AsyncMock`).

### F1 (блокер). Ожидание регистрировалось только при слове «видео»

**Воспроизведено до правки** (тесты RED, оба падали на текущем кандидате):

* «Бот, сделай выжимку» → `UNHANDLED`, pending не создан; следующий update с
  пересланным роликом → `UNHANDLED`, 0 анализов, 0 ответов. Причина — гейт
  `not canonical and not mentions_video(text) and not has_pending(chat)`:
  буквальная формулировка §4.5 #1 («Сделай выжимку») не содержит слова
  «видео/видос/ролик» и отбрасывалась.
* Регресс от глобального `has_pending(chat)`: при активном ожидании ЛЮБОЕ
  адресованное сообщение со «суть/перескаж/выжимк» забиралось youtube-веткой.
  «Бот, сделай выжимку <веб-ссылка на статью>» не получало ответа, создавало
  ВТОРОЕ ожидание, и через TTL пользователь получал «перешли ролик» вместо
  выжимки статьи.

**Корень:** условие ожидания опиралось на наличие слова «видео» и на факт
чужого ожидания в чате, а не на «есть ли у просьбы ДРУГАЯ цель».

**Правка (`handlers/youtube.py`):**

* `has_pending(chat)`-побег удалён полностью; `mentions_video` больше не
  решает вопрос ожидания.
* `_has_foreign_url(text)` — новая проверка «в сообщении есть ссылка, но ни
  одна не видео-цель»: такая ссылка обслуживается 0f, ожиданием не
  перехватывается (запрет при веб-URL сохранён, как требовалось).
* Ожидание регистрируется для ПРОСЬБЫ об анализе без другой цели:
  канонический триггер ЛИБО императивная просьба (`_ANALYSIS_REQUEST_RE`
  — заменён на `_VIDEO_SUMMARY_LEXICON_RE`, см. §review-fix2:
  «сделай/перескажи/скинь/дай/…», «выжимка/транскрипт/краткое содерж» в
  начале остатка команды).
* `_addressed_to_bot` дополнен: в ЛИЧНОМ чате прямая императивная просьба об
  анализе считается обращением к боту (он единственный собеседник) — так
  работает буквальная формулировка §4.5 #1 без «Бот,». Обычная речь и вопросы
  («в чём суть?», «Олег, помнишь транскрипт того созвона?», «Олег,
  транскриптер») остаются обычной речью: императива в них нет, поэтому
  существующие пины `test_command_registry_round1015` (R10.15-3) не тронуты и
  зелёные.

**Тесты (`tests/test_evol_video_intent.py`, +8):**

* `TestWaitingWithoutVideoWord::test_literal_request_without_video_word_then_forwarded_video`
  — «Сделай выжимку» (без слова «видео») → pending → пересланный ролик →
  РОВНО один анализ и один ответ реплаем на ролик.
* `…::test_prefixed_request_without_video_word_waits` — «Бот, сделай выжимку» →
  pending без мгновенного «видео нет».
* `…::test_private_chat_question_is_not_hijacked` — «в чём суть?» в личке →
  `UNHANDLED`, ожидания нет.
* `TestOtherTargetNotConsumed::test_web_summary_not_consumed_while_pending_active`
  — при активном ожидании веб-выжимка статьи → `UNHANDLED`, ответ отдаёт
  0f/LLM, второго ожидания нет, новых событий нет.
* `…::test_web_summary_without_pending_not_consumed`,
  `…::test_video_url_still_analyzed` — веб-ссылка не перехватывается, видео-URL
  по-прежнему уходит в анализ.

### F2 (блокер). STT/аудио-фолбэк маскировался под просмотренное видео

**Воспроизведено:** честность была только в событиях
(`transcript_fallback`/`audio_only_source`), а пользователю уходила обычная
выжимка по транскрипту без пометки, что визуально видео не смотрели.

**Правка (`handlers/youtube.py`):** константа `TRANSCRIPT_ONLY_NOTE`
(«разбор по аудиодорожке — визуально видео не смотрел»); `_summarize_and_send`
получил параметр `note` и дописывает эту строку к выжимке. Пометка ставится
ТОЛЬКО на STT-ветках (`_process_video_media` — фолбэк файла/кружка/голосового
и `_process_url_media` — фолбэк скачанной ссылки). Мультимодальный путь
(`summarize_media_url`) не изменён и пометки не получает.

**Тесты:** `TestAudioOnlyReplyHonesty::test_audio_only_fallback_reply_marks_transcript_only`
(пометка в ответе, визуальный анализ не заявлен, `multimodal_success` нет) и
`…::test_multimodal_success_has_no_transcript_note` (мультимодалка без пометки).

**Вынужденное расширение правки тестов (вне исходного списка файлов).** Пометка
— часть текста ответа, поэтому 5 старых пинов, сверявших ТОЧНЫЙ текст
STT-выжимки, обновлены минимально (выжимка + `TRANSCRIPT_ONLY_NOTE`):
`tests/test_youtube_video_media.py` (2: `test_other_triggers_llm_summary`,
`test_caption_trigger_on_own_video`), `tests/test_video_router.py` (3:
`test_native_summary_cascade_fail_stt_fallback`,
`test_native_summary_no_publish_stt_fallback`,
`test_direct_url_fallback_download_publish_stt`). Смысл пинов сохранён
(«выжимка доставлена реплаем»), изменён только ожидаемый хвост-пометка.
Иначе F2 физически несовместим с этими пинами.

### Nonblocking (сделано в том же файле)

Канонический путь (reply/own media, включая reply+«транскрипт») теперь тоже
начинает цепочку §4.5 с `request_seen` → `media_matched` (reason
`reply_media`/`own_media`), а не сразу с `analysis_started`. Путь
pending-привязки не задет: там `request_seen` уже эмитился, точная
последовательность событий из `TestLateVideo` не изменилась.

### Проверки после правки (офлайн)

| Набор | Итог |
|---|---|
| `tests/test_evol_video_intent.py` | **25 passed** (было 17 + 8 новых) |
| `tests/test_epic37_router_isolation.py`, `test_command_registry_round1015.py`, `test_web_handlers.py`, `test_epic33_router_isolation.py`, `test_round106_gates.py`, `test_round106_ia_smoke.py`, `test_p0_delta_routing.py`, `test_direct_chat*.py` | **455 + 328 passed** |
| `test_youtube_video_media`, `test_youtube_handlers`, `test_video_router`, `test_video_download`, `test_video_cascade`, `test_video_stt_timeouts`, `test_native_*_round1024`, `test_media_transcribe_tool_round1024`, `test_hotfix_round1025_media`, `test_media_share`, `test_media_download` | **422 passed** |
| RED до правки | 5 падений (F1 ×2, F1-регресс, F2 ×2) → 0 после |

### Остаточные риски §review-fix

1. `_ANALYSIS_REQUEST_RE` (с §review-fix2 — `_VIDEO_SUMMARY_LEXICON_RE`) —
   эвристика формулировок; экзотическая просьба без видео-предмета и без
   канонического триггера уйдёт в обычный путь (деградация без ложного
   перехвата). Список глаголов и предметов — единственное место, где он задан.
2. В личном чате просьба с видео-предметом («сделай выжимку», «суть видео»)
   создаёт ожидание и после TTL отвечает «перешли ролик». Это требуемое
   поведение §4.3/§4.5 #1; общие императивы без видео-предмета ожидание НЕ
   создают (исправлено в §review-fix2).
3. Пометка `TRANSCRIPT_ONLY_NOTE` — статичная строка в `handlers/youtube.py`
   (не пул редактируемых фраз): каталог фраз (`smartmodule_phrases`) в этой
   правке не расширялся, чтобы не менять пины каталога.

## §review-fix2 — F3 (блокер): личка перехватывала обычную речь

**Симптом (регресс, внесён правкой F1).** В ЛИЧНОМ чате эвристика
`_ANALYSIS_REQUEST_RE` (глаголы `сделай/перескажи/расшифруй/скинь/дай/покажи/
нужн/хочу` + голая «суть») считала обращением к боту любую просьбу с общим
императивом. «Перескажи кратко», «Дай краткое содержание», «Хочу понять суть»,
«Покажи суть», «Перескажи это кратко», «Сделай краткое содержание», «Дай
краткое содержание статьи», «Перескажи кратко прошлый ответ» потреблялись
(`youtube_handler` → `None`, pending=1, мгновенного ответа нет), а после TTL
бот отвечал «ролика нет, разбирать нечего». `youtube_router` стоит перед
web/direct_chat, поэтому `None` останавливал цепочку — пользователь не получал
ответа вообще. В `3a0f89d2` эти формулировки уходили обычным путём.

**Воспроизведение (RED).** Новые кейсы в `tests/test_evol_video_intent.py`
падали до правки: 8 личных формулировок + групповое «Бот, перескажи кратко» →
`None` вместо `UNHANDLED`, pending=1.

**Правка (`handlers/youtube.py`, локальная).** `_ANALYSIS_REQUEST_RE` заменён
на `_VIDEO_SUMMARY_LEXICON_RE` — видео-лексикон, а не общие императивы:

* (а) видео-квалифицированный предмет сам по себе однозначен: «краткое
  содержание / пересказ / суть / смысл / транскрипт / расшифровка / текст» +
  «видео/видос/ролик/клип/кружок»;
* (б) просьба (`сделай/дай/покажи/скинь/пришли/нужн/хочу/перескажи/расшифруй`)
  + предмет-выжимка (`выжимк/транскрипт/расшифровк`) в пределах 40 символов;
* (в) голая «выжимка/транскрипт/расшифровка/краткое содержание» в начале
  сообщения — прежнее поведение сохранено.

`_addressed_to_bot` (личка) и условие ожидания в `_handle_unclassified`
используют один и тот же лексикон — это СУЖЕНИЕ прежнего условия, не
расширение: «Бот, перескажи кратко» в группе больше не создаёт ожидание, а
канонический триггер и «Сделай выжимку» работают как раньше. Гейт по чужой
веб-ссылке (`_has_foreign_url`) не тронут.

**Тесты (`tests/test_evol_video_intent.py`, +13 кейсов):**

* `TestPrivateChatOrdinarySpeechNotHijacked::test_ordinary_private_request_unhandled`
  (8 параметров) — «Перескажи кратко», «Дай краткое содержание», «Хочу понять
  суть», «Покажи суть», «Перескажи это кратко», «Сделай краткое содержание»,
  «Дай краткое содержание статьи», «Перескажи кратко прошлый ответ» →
  `UNHANDLED`, pending=0, ноль отправок (значит и TTL-ответа не будет), событий
  `waiting_for_media` по сообщению нет, анализ не вызывался.
* `…::test_group_ordinary_request_unhandled` — «Бот, перескажи кратко» в группе
  → `UNHANDLED`, ожидания нет.
* `…::test_video_lexicon_still_waits` (4 параметра) — «Сделай выжимку», «Дай
  краткое содержание видео», «Перескажи видео кратко», «Сделай транскрипт» →
  pending без мгновенного «видео нет» (лексикон не выключен целиком).
* Сохранены зелёными: буквальный §4.5 #1
  (`test_literal_request_without_video_word_then_forwarded_video` — pending →
  ролик → ровно один анализ и один ответ), «Бот, сделай выжимку» → pending,
  веб-URL не перехватывается (2 кейса), «в чём суть?» → `UNHANDLED`.

**Проверки после правки (офлайн, тот же кандидат):**

| Набор | Итог |
|---|---|
| `tests/test_evol_video_intent.py` | **38 passed** (было 25 + 13) |
| `test_epic37_router_isolation`, `test_command_registry_round1015`, `test_youtube_video_media`, `test_video_router` | **125 passed** (всего с первым набором 163) |
| Соседние `test_round106_gates`, `test_youtube_handlers`, `test_hotfix_round1025_media`, `test_media_transcribe_tool_round1024`, `test_video_download` | **186 passed** |
| RED до правки | 9 падений (8 личных + 1 групповой) → 0 после |

**Побочная находка (pre-existing, не связана с F3):**
`tests/test_youtube_multimodal_download_round1024.py` — 18 ошибок на фикстуре
`AttributeError: module 'handlers.youtube' has no attribute 'get_smart_cache'`;
атрибута нет и в `HEAD:handlers/youtube.py`, правка его не касается.

**Остаточный риск.** Эвристика остаётся эвристикой: просьба без видео-предмета
и без обращения («перескажи кратко») теперь уходит обычным путём (деградация
без ложного перехвата — правильная сторона ошибки). Просьбы с явным
видео-предметом («суть видео», «краткое содержание ролика») ловятся и без
императива.

