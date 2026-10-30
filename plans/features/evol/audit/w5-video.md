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
