# P0 FACTCHECK MEDIA — изображения, альбомы, пересланные публикации

Ветка: `task/factcheck-media`, база — production `2.58.130` (`534ac7dd`).
Источники требований: `source-2026-10-25.md` (§1–§9),
`source-owner-clarification-2026-10-25.md` (уточнение №1),
`source-owner-clarification-2-2026-10-25.md` (уточнение №2) и
`owner-decision-wide-context-2026-10-25.md` (решение о дефолте).

Живых сообщений в Telegram не отправлялось. К production/SSH/БД сервера
подключений не было, секреты не читались, зависимостей не добавлялось.
Production-факты ниже — из recon владельца, не перепроверялись по SSH.

## 1. Сквозной аудит: где терялись данные

Путь: `update → reply → message storage → media group reconstruction →
OCR/Vision → Fact-check context → provider payload → model → response`.

| Этап | Что происходило по факту | Потеря | После исправления |
|---|---|---|---|
| Telegram update | Альбом приходит отдельными сообщениями; **caption только на одном элементе**, `media_group_id` есть у всех | Текст есть только у одного элемента | — (свойство Telegram) |
| Reply | `message.reply_to_message` = конкретный элемент; у не-caption элемента `text`/`caption` пустые | Цель без текста | Reply — только точка входа (уточнение 25.10) |
| Message storage | `summary_observer` (0a) пишет **каждый** элемент в `smart_messages` с `media_group_id`, `caption`, `media_type`, `origin_*` | durable-данные **есть**, но их никто не читал | `get_smart_messages_by_media_group` (тот же `chat_id` + `media_group_id`) |
| Media group reconstruction | `services/media_group_buffer.py`: in-memory, TTL 60 c, только caption + `first_message_id`, **без изображений**, пуст после рестарта; при промахе — сразу «пусто» | Альбом и все фото терялись | Durable-реконструкция из `smart_messages`; буфер остаётся same-turn fast-path |
| OCR / Vision | `mca_vision.render_media_context_async` отдаёт OCR + визуальное описание **сохранённого** анализа; активы регистрируются на приёме | В проде (temporal ON) Vision **не вызывался вообще**: `load_claim_media` был подключён только в v2 (флаг OFF) | `load_claim_media` читает все элементы публикации; вызывается из handler и v2 |
| Fact-check context | `_extract_target_text` возвращал `None` → `FACTCHECK_EMPTY_CONTEXT_PHRASES` **до** поиска, vision и проверки окружения | «и че тут проверять, пустоту?» | Пусто в цели → обязательное окно 200–300 + reply-цепочка; отказ называет, что проверено (уточнение №2) |
| Payload | `check_claim`/`build_envelope` получали только текст цели | — | Тезис = текст/подписи всей публикации + OCR + визуальное описание (помечены как данные изображения/модели) |
| Model / response | — | — | Плюс честная оговорка о неполноте/недоступности в ответе (не в тезисе и не в поиске) |

### Подтверждённый production-случай (recon владельца)

Чат `-1002661910336`, `media_group_id=14343246299290082`: 10 фото, подпись
**2846 симв. только на первом элементе `1175403`**, пересылка канала
«НУЛЕВЫЕ+ @epoha00» (`origin_message_id=45653`). Цель reply — `1175411`
(9-й элемент): text пуст, caption нет, фото есть, `media_group_id` есть,
forward есть; вызов — `1175414`. Между записью буфера и вызовом **84.1 с**
при TTL 60 с → буфер вернул None → ветка 5.3 «пустота». Подпись уже лежала
в `smart_messages` (id=2363791, 2846 симв.). Vision не вызывался; у цели
анализ был ready (описание 268 симв., OCR 0), по альбому 5 из 10 анализов
failed.

Вывод: durable-данные были на месте, ломалась сборка тезиса. Текущий
кандидат на этом же входе читает 10 элементов, берёт подпись с 1-го,
подключает готовые анализы (5 из 10) и честно сообщает о нераспознанной
части (тест `test_production_shape_album_10_caption_first_reply_ninth`).
Дополнительно (уточнение №2) подпись теперь видна и в широком окне: даже
если бы альбом не собрался, окружение отдало бы тот же тезис.

## 2. Что изменено

| Файл | Изменение |
|---|---|
| `services/database.py` | `get_smart_messages_by_media_group(chat_id, media_group_id)` — durable элементы альбома (ASC, `reply_to_id` включён); `get_smart_messages_reply_to(chat_id, reply_to_id, media_only=…)` — структурная связь «альбом отвечает на текст поста». Соседние сообщения не подмешиваются. |
| `services/factcheck_service.py` | `load_claim_media`: читает **все** `message_ids`, агрегирует подписи, OCR (нумерованные блоки при альбоме) и визуальные описания; `expected_images`/`pending_count` отличают «изображения нет» / «недоступно» / «часть не распознана». `ClaimPublication` + `resolve_claim_publication`: публикация целиком (durable альбом → буфер fast-path → цель), обратная связь reply→альбом, текст поста отдельным сообщением, `augmented`, `album_incomplete`, `forward_source`, honest `notice()`. |
| `services/mca_vision.py` | Аддитивный ключ `visual_descriptions` в `render_media_context_async` (описание — отдельным каналом, не OCR). Существующие потребители не затронуты. |
| `handlers/factcheck.py` | `_resolve_publication` перед проверкой пустоты; `_empty_content_phrase` различает: пусто / изображение не прочитано / распознавание не готово / нет проверяемого утверждения; оговорка добавляется к ответу (не к тезису); claim_text для envelope при собранном тексте; атрибуция пересланной публикации из сохранённой строки. |
| `services/factcheck_orchestrator.py` | v2 использует тот же резолвер (одна реализация), envelope получает собранный текст, notice — из публикации. |
| `services/factcheck_context.py` | `wide_context_enabled()` → default **True** (явное `false` = откат); окно видит `caption` (раньше фото-строки с подписью молча выбрасывались из окна). |
| `services/factcheck_suitability.py` | `ContextClaim`/`ContextProbe`, `find_context_claim` (ближайший тезис окна; триггер и цель исключены), `resolve_context_claim` (reply-цепочка через существующий `collect_thread_chain` + окно W1; гейт не читается для пустой цели). |
| `services/smartmodule_phrases.py` | Три честных пула media + `FACTCHECK_CONTEXT_EMPTY_PHRASES` (с `{scope}`/`{scope_of}`/`{window}`) и `FACTCHECK_CONTEXT_ERROR_PHRASES`. `FACTCHECK_EMPTY_CONTEXT_PHRASES` больше не используется для пустой цели (только DI-off/совместимость). |
| `config/settings.py` | `FACTCHECK_WIDE_CONTEXT_ENABLED` default **True** (решение владельца 25.10.2026). |
| `services/config_migrations.py` + `bot.py` | `migrate_factcheck_wide_context_default`: одноразовый false→true с маркером `flags.factcheck_wide_context_default_v1`; после маркера ручное выключение не перетирается; PG down → skip. Вызов в `main()` рядом с миграцией окна. |
| `services/param_catalog.py` + `plans/docs/param-registry-round1025.tsv` | Описание тумблера «Модули → Фактчек» под новый дефолт (окно 200–500, дефолт 300, откат без рестарта). Группа/вкладка не менялись; TSV переэмитирован генератором (`--check OK`, 582 строки). |
| `services/media_group_buffer.py` | Докстринг: буфер = fast-path, источник истины — `smart_messages` (код буфера не менялся). |
| `tests/test_factcheck_media_2026_10_25.py` | 40 unit-тестов на вход пайплайна (не только на финальную фразу). |
| `tests/test_factcheck_wide_context_default_2026_10_25.py` | 11 тестов дефолта/миграции/каталога/проводки широкого контекста. |

Новых LLM/OCR/Vision-провайдеров, таблиц, миграций и квот инструкций нет.

### Изображение не становится доказательством

Изображения (OCR и описание) добавляются ТОЛЬКО в тезис (`<claim>`), никогда
в evidence/RAG/поисковую выдачу. В envelope-ветке при пустом evidence сервер
принудительно ставит `insufficient_evidence` (TH-5) — «подтверждено»
изображением получить нельзя; в legacy-ветке grounding-якоря строятся только
из RAG/поиска/tool-контекста. Плюс подписи: «OCR, не слова автора» и
«результат модели; не доказывает подлинность, дату или место».

### Общие пути медиа (§8)

Дефект **локальный**: `mca_vision` корректно хранит активы/анализ каждого
элемента, `summary_observer` корректно пишет все элементы. Ломалась сборка
тезиса именно в factcheck. Direct Chat, Observer, Initiative, Memory, Summary
не строят «публикацию из reply-цели» и не переписывались. Общие правки —
аддитивный ключ `visual_descriptions` и два read-метода `DatabaseService`.

## 3. Уточнение владельца 25.10.2026: что изменилось после него

До уточнения реализация уже собирала все элементы `media_group_id` и все
подписи. Уточнение расширило трактовку: **reply на фото — только точка
входа**, проверяется весь пост; текст поста может быть отдельным сообщением;
ответ на текст поста обязан давать тот же охват.

Что добавлено после уточнения:

1. **Обратная связь «текст поста → альбом».** Если цель — текст без
   изображения, резолвер ищет сообщения того же чата с
   `reply_to_id = цель` и `media_group_id` (структурная связь, не соседство).
   Ровно одна группа → она и есть публикация; несколько групп (неоднозначно) →
   не угадываем.
2. **Текст поста отдельным сообщением.** Если элемент альбома отвечает на
   текстовое сообщение (`reply_to_id`), его текст добавляется к публикации
   (первым) — вместе с подписями элементов. Соседние сообщения без такой
   связи не подмешиваются (§3.8).
3. **Одинаковый охват.** Ответ на текст поста и на любое его фото даёт один
   и тот же набор изображений и текста; тесты подтверждают идентичный вход.
4. **Честная частичная готовность.** Для production-случая 5/10 анализов
   failed: текст готовых анализов используется, ответ говорит «Часть
   изображений публикации ещё не распознана — учтено то, что уже прочитано»
   (раньше сказал бы «проверен только текст сообщения», что занижало охват).
5. **Границы.** Одиночное фото вне альбома/поста проверяется само (прежнее
   правило); неоднозначные/соседние сообщения не объединяются.

## 3a. Уточнение №2 (25.10.2026): пустая цель → окно окружения

Правило: «в цели нет проверяемого материала» — не отказ. Сначала обязательны
reply-цепочка и окно 200–300 сообщений, и только потом возможен честный отказ
с указанием, что проверено.

Реализация (существующие механизмы, не новый):

1. `handlers/factcheck.py` при пустом тезисе вызывает
   `resolve_context_claim` **до** любой фразы отказа.
2. Цепочка: существующий `services/thread_chain.collect_thread_chain` от
   родителя цели (`target.reply_to_message` / `reply_to_id` строки), бот-ходы
   тезисом не считаются.
3. Окно: существующий `services/factcheck_context.build_wide_context`
   (дефолт 300, кап 500, кеш 120 с, строго `chat_id`). Для пустой цели
   гейт `wide_context_enabled` НЕ читается — режим обязателен; флаг остаётся
   откатом для непустых целей.
4. Кандидат: ближайшее к цели сообщение с структурным предикатом
   (`_has_predicate`/≥6 содержательных токенов), кроме цели и сообщения-
   команды «фактчек». Найденный текст становится тезисом, окно+цепочка —
   `chat_context`; второй раз окно не собирается (`context_feed`).
5. Ничего нет → `FACTCHECK_CONTEXT_EMPTY_PHRASES` с фактическим числом
   проверенных сообщений и scope («цель» / «цель с изображением»).
   Окно не собралось → `FACTCHECK_CONTEXT_ERROR_PHRASES` (техническая
   причина, не «фактов нет»).
6. Соседние сообщения вне окна/цепочки не объединяются: окно — существующий
   `get_messages_around` по `chat_id`; caption теперь входит в окно.

Тесты (в `tests/test_factcheck_media_2026_10_25.py`,
`TestOwnerClarification2ContextWindow`): утверждение в предыдущем сообщении;
выше по reply-цепочке (вне окна); в обсуждении дальше 6 сообщений
(проверяется фактический `before` > 6); нигде нет утверждений → отказ с
числом окна; чужой `chat_id` не используется; команда «фактчек …» не
становится тезисом; проводка не зависит от гейта.

## 3b. Решение владельца (25.10.2026): широкий контекст по умолчанию

1. `config/settings.py`: `FACTCHECK_WIDE_CONTEXT_ENABLED` default **True**.
2. `wide_context_enabled()`: fallback **True**; явный hot/env `false` =
   откат без рестарта (действует и для непустых целей).
3. Одноразовая идемпотентная миграция
   `migrate_factcheck_wide_context_default` (существующий
   `services/config_migrations.py`, вызов в `bot.py main()`):
   * сохранён `false` от прежнего дефолта → `true` + маркер
     `flags.factcheck_wide_context_default_v1`;
   * маркер есть → no-op: ручное выключение владельца сохраняется;
   * ключа нет → ничего (hot.get отдаст новый дефолт); PG down → skip.
4. Каталог: тумблер уже в группе `flags_module_factcheck` (вкладка
   `mod_factcheck`, «Модули → Фактчек»); обновлено описание под новый
   дефолт. `tools/gen_param_registry_round1025.py --check` → OK (582
   строки); Δ каталога = 0 (ключи/GROUPS/TAB не менялись), переутверждён
   только hash описания в F8-инварианте. `FACTCHECK_SUITABILITY_GATE_ENABLED`
   остаётся default OFF (решение владельца касалось только широкого окна;
   гейт — отдельный миграционный рубильник).
5. Проводка проверена не флагом: тест непустой цели получает широкий фид
   (`<chat_context>` + сообщение дальше 6) и реальный `before` > 6;
   пустая цель собирает окно даже при принудительно выключенном гейте.

## 4. Регрессия по 15 случаям §9 (+ уточнение)

Все проверки — `tests/test_factcheck_media_2026_10_25.py` (реальный
`load_claim_media`/резолвер, фейковый Vision-ответ; БД — фейк или настоящий
`DatabaseService` во временной папке).

| # | Случай §9 | Тест | Что проверяется на входе |
|---|---|---|---|
| 1 | Текстовый фактчек без изображений | `TestTextOnlyUnchanged::test_text_only_factcheck_input_unchanged`, `test_cache_hit_notice_free_for_text` | `check_claim` получает ровно текст; ответ без оговорок |
| 2 | Одна фотография с подписью | `TestSingleImage::test_photo_with_caption_and_ocr` | подпись + OCR в тезисе |
| 3 | Одна фотография без подписи | `test_photo_without_caption_uses_ocr_not_empty` | пайплайн запущен, тезис = OCR, пустой фразы нет |
| 4 | Скриншот с текстовым утверждением | `test_screenshot_multiple_text_blocks` | все OCR-блоки + описание в тезисе |
| 5 | Альбом из нескольких фотографий | `TestAlbumResolution::test_reply_to_any_element_reads_whole_publication[71/72/73]` | `render` вызван для 71,72,73; в тезисе подпись + OCR всех |
| 6 | Caption у первого изображения | те же параметры `[71]`, `caption_tg=71` | подпись 1-го доходит |
| 7 | Caption у другого изображения | `test_caption_on_non_first_element` | подпись 2-го элемента доходит при reply на 3-й |
| 8 | Reply на первый/средний/последний | параметры `[71, 72, 73]` | одинаковый полный вход, reply на ЦЕЛЕВОЕ |
| 9 | Пересланный альбом | `TestForwardedPublication::test_forwarded_album_keeps_caption_images_and_source`, `test_forwarded_album_source_falls_back_to_stored_row` | caption+изображения+forward_source; слова «фактчек» в тезисе нет |
| 10 | Пересланная одиночная фотография | `test_forwarded_single_photo_without_caption` | OCR + атрибуция канала |
| 11 | Альбом с неполными данными | `test_album_with_missing_element_is_partial`, `test_album_group_read_failure_*` | использовано что есть; оговорка в ответе, не в тезисе |
| 12 | Ошибка получения медиафайла | `TestMediaFailureSemantics::test_vision_error_without_text_is_technical_not_empty` | техническая фраза, НЕ пустая, `check_claim` не вызван |
| 13 | Недоступность Vision-провайдера | `test_vision_unavailable_with_caption_still_checks_text` | проверка по подписи идёт, в ответе честная оговорка |
| 14 | Изображение без проверяемого утверждения | `test_image_without_verifiable_claim_checks_context`, `test_image_pending_is_honest_pending` | сначала проверяется окружение; отказ называет окно; pending — отдельная честная причина |
| 15 | Текст и изображения, которые его не подтверждают | `TestTextAndContradictingImage::test_claim_carries_text_and_image_material_separately` | в тезисе слова автора, OCR и описание (помечено «не доказывает подлинность») |

Уточнение владельца 25.10:

| Проверка | Тест | Что проверяется |
|---|---|---|
| Ответ на текстовую часть поста | `TestOwnerClarification2026_10_25::test_reply_to_text_part_covers_whole_post` | текст поста + подпись альбома + все 3 фото (render 200/201/202/203), reply на цель |
| Текст поста отдельным сообщением рядом с альбомом | `test_post_text_as_separate_message_next_to_album` | текст родительского сообщения попал в тезис; все фото, не только цель |
| Текст+подпись с разных сообщений, соседи не слиты | `test_parent_text_included_but_neighbours_not_merged` | оба текста, «соседнее сообщение» отсутствует |
| Production-форма (10 фото, подпись 2846 на 1-м, reply на 9-е, 5 failed) | `test_production_shape_album_10_caption_first_reply_ninth` | все 10 id, длинная подпись цела, честная оговорка о части изображений, «пустоты» нет |

Дополнительно: `test_truly_nothing_refusal_names_checked_window` (отказ
называет окно вместо общей фразы), `test_repost_variant_caption_command_is_not_a_claim`
(D121 не сломан), `TestTemporalEnvelopeUsesPublication` (собранный текст
доходит до `envelope.claim_text` на реальной БД), `TestDurableAlbumStorage`
(SQL: порядок, отсутствие соседей), два unit-теста агрегации
`load_claim_media`, 11 тестов дефолта/миграции/каталога/проводки в
`tests/test_factcheck_wide_context_default_2026_10_25.py`.

## 5. Прогоны (реальный вывод)

```
$ py -3 -m pytest tests/test_factcheck_media_2026_10_25.py tests/test_factcheck_wide_context_default_2026_10_25.py tests/test_factcheck_handlers.py tests/test_factcheck_service.py tests/test_factcheck_context_cfg06.py tests/test_factcheck_deep_context_round1023.py tests/test_context_limits_round1019.py tests/test_webapp_round109_ui.py -q
216 passed, 2 warnings in 6.81s
```

```
$ py -3 -m pytest tests -k "factcheck or vision or media_group" -q --ignore=tests/test_p0_vision_ui_e2e.py
1 failed, 707 passed, 15005 deselected, 4 warnings in 36.75s
FAILED tests/test_soul1_registry_completeness.py::test_legacy_persona_canons_are_registered_with_revision_labels
```

```
$ py -3 tools/gen_param_registry_round1025.py --check
CHECK OK: реестр 582 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны.
```

Без `--ignore` тот же прогон добавляет 7 ERROR из `test_p0_vision_ui_e2e.py`
(`ModuleNotFoundError: No module named 'playwright'` — модуль не установлен в
этом окружении).

Падение `test_soul1_registry_completeness.py` **pre-existing и не связано** с
задачей: на чистом `534ac7dd` (git stash всех правок) тот же тест падает так
же (`verbilizer.mode.deep_research`, реестр промптов).

```
$ py -3 -m py_compile handlers/factcheck.py services/factcheck_service.py services/factcheck_orchestrator.py services/database.py services/mca_vision.py services/smartmodule_phrases.py services/media_group_buffer.py services/factcheck_context.py services/factcheck_suitability.py services/config_migrations.py services/param_catalog.py config/settings.py bot.py tests/test_factcheck_media_2026_10_25.py tests/test_factcheck_wide_context_default_2026_10_25.py
py_compile: OK
```

## 6. Честные ограничения

1. **Production-строка PERMsoc** в БД не читалась мной (recon владельца —
   основание, SSH не использовал). Для повторной проверки после выката:
   строка лога `[factcheck] no claim in target/context | chat=… | target=… |
   group=… | probed=… | image=… | vision_failed=… | pending=… | window=… |
   chain=…`; при штатной работе — отсутствие этой строки и вердикт по
   подписи. SQL (read-only) при необходимости:
   ```sql
   SELECT tg_message_id, media_type, media_group_id, reply_to_id,
          length(caption) AS caption_len, length(text) AS text_len,
          is_forward, forward_source, sent_at
   FROM smart_messages
   WHERE chat_id = -1002661910336
     AND media_group_id = '14343246299290082'
   ORDER BY tg_message_id;
   ```
2. **Vision-анализ может быть не готов или failed** (в разобранном случае
   5/10). Изображение не выдумывается: тезис строится по подписи/OCR,
   ограничение называется в ответе. On-demand ожидание 45 c
   (`mca_vision.recognize_target`) сознательно не вызывается: это платный
   вызов и задержка на каждом фактчеке.
3. **Описание изображения — результат модели**, не доказательство
   подлинности/даты/места (явно в тезисе; в evidence не попадает).
4. **Пересланная публикация анализируется в копии этого чата.** `origin_chat_id`
   /`origin_message_id` — метаданные; удалённый оригинал не выкачивается.
5. **Текст поста отдельным сообщением** подключается только по структурной
   связи `reply_to` (одношаговая, однозначная группа); произвольные соседние
   сообщения не объединяются. Если Telegram хранит текст поста иначе (без
   reply-связи), он не будет угадан — это осознанное ограничение §3.8.
6. **v2-оркестратор (флаг OFF)** получил тот же резолвер, но live не
   проверялся; покрыт unit-тестами.
7. `tests/test_p0_vision_ui_e2e.py` не запускался (нет `playwright`);
   UI-контракт этой задачей не менялся.
8. Метки материала («OCR, не слова автора», «результат модели…») идут в
   поисковый запрос вместе с текстом (как и прежний OCR-путь v2). Честность
   вывода это не ломает; запрос может слегка размываться.
9. **Кандидат из окружения выбирается детерминированно** (ближайшее сообщение
   со структурным предикатом, без LLM-классификатора). В шумном чате ближайшее
   утверждение может оказаться не тем, что имел в виду человек; цепочка
   reply/окно и автор/ID видны модели в `<chat_context>`, а бот не выдумывает
   тезис. Это осознанный компромисс против прежнего «проверять нечего».
10. **Широкий контекст теперь дефолт**: откат — тумблер «Модули → Фактчек»
    (hot, без рестарта). Миграция поднимает только унаследованный `false` и
    ставит маркер; при недоступном PG она пропускается и повторится на
    следующем старте. `FACTCHECK_EMPTY_CONTEXT_PHRASES` остаётся только для
    DI-off/совместимости — в прод-пути пустая цель всегда сначала смотрит
    окружение.
