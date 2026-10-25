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
| `services/factcheck_service.py` | `load_claim_media`: читает **все** `message_ids`, агрегирует подписи, OCR (нумерованные блоки при альбоме) и визуальные описания; бюджет — **на элемент**; `truncated`-флаг; `expected_images`/`pending_count` отличают «изображения нет» / «недоступно» / «часть не распознана». `ClaimPublication` + `resolve_claim_publication`: публикация целиком (durable альбом → буфер fast-path → цель), обратная связь reply→альбом, текст поста отдельным сообщением, `album_incomplete` (цель/≥2/буфер/id-gap), `material_context()` для описаний, `forward_source`, honest `notice()`. |
| `services/media_group_buffer.py` | Дополнительно хранит набор id элементов (`get_media_group_ids`) — честная оценка полноты durable-альбома; caption-контракт не изменён (пустой caption → None). |
| `services/mca_vision.py` | Аддитивный ключ `visual_descriptions` в `render_media_context_async` (описание — отдельным каналом, не OCR). Существующие потребители не затронуты. |
| `handlers/factcheck.py` | `_resolve_publication` перед проверкой пустоты; `_empty_content_phrase` различает: пусто / изображение не прочитано / распознавание не готово / нет проверяемого утверждения; оговорка добавляется к ответу (не к тезису); claim_text для envelope при собранном тексте; атрибуция пересланной публикации из сохранённой строки. |
| `services/factcheck_orchestrator.py` | v2 использует тот же резолвер (одна реализация), envelope получает собранный текст, notice — из публикации. |
| `services/factcheck_context.py` | `wide_context_enabled()` → default **True** (явное `false` = откат); окно видит `caption` (раньше фото-строки с подписью молча выбрасывались из окна). |
| `services/factcheck_suitability.py` | `ContextClaim`/`ContextProbe`, `find_context_claim` (ближайший тезис окна; триггер и цель исключены), `resolve_context_claim` (reply-цепочка через существующий `collect_thread_chain` + окно W1; гейт не читается для пустой цели). |
| `services/smartmodule_phrases.py` | Три честных пула media + `FACTCHECK_CONTEXT_EMPTY_PHRASES` (с `{scope}`/`{scope_of}`/`{window}`) и `FACTCHECK_CONTEXT_ERROR_PHRASES`. `FACTCHECK_EMPTY_CONTEXT_PHRASES` больше не используется для пустой цели (только DI-off/совместимость). |
| `config/settings.py` | `FACTCHECK_WIDE_CONTEXT_ENABLED` default **True** (решение владельца 25.10.2026). |
| `services/config_migrations.py` + `bot.py` | `migrate_factcheck_wide_context_default`: одноразовый false→true с маркером `flags.factcheck_wide_context_default_v1`; после маркера ручное выключение не перетирается; PG down → skip. Вызов в `main()` рядом с миграцией окна. |
| `services/param_catalog.py` + `plans/docs/param-registry-round1025.tsv` | Описание тумблера «Модули → Фактчек» под новый дефолт (окно 200–500, дефолт 300, откат без рестарта). Группа/вкладка не менялись; TSV переэмитирован генератором (`--check OK`, 582 строки). |
| `tests/test_factcheck_media_2026_10_25.py` | 53 unit-теста на вход пайплайна (не только на финальную фразу), включая 13 review-fix тестов. |
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

## 4a. Review fixes (25.10.2026, кандидат c7514ce4 → review fixes)

Независимое ревью вернуло Needs Fixes по 6 пунктам. Исправления — минимальные,
на существующих механизмах; новых LLM-вызовов/квот инструкций нет.

### 1. Тихая обрезка материала изображений

- Было: единый `max_chars=2000` на всю публикацию → 10 фото × ~400 симв. OCR
  давали тезис 2000, `FOTO6..FOTO10` отсутствовали, описания не входили,
  оговорки не было.
- Стало: лимит — **на один элемент** (`max(200, max_chars)`), все элементы
  альбома попадают в материал. При превышении лимита элемента —
  `ClaimMediaMaterial.truncated=True` и оговорка «Текст части изображений
  обрезан по лимиту…» в ответе.
- Probe: `claim_len 4605`, `all_foto=True`, `desc10_in_claim=True`,
  `truncated=False` (10 × 400).
- Тесты: `test_all_album_images_survive_per_element_budget`,
  `test_overlong_image_is_flagged_with_notice`.

### 2. Неполный альбом выдавался за полный

- Было: `album_incomplete` только при исключении чтения группы; 2/3 durable-
  строк с потерянной подписью → тихий неполный тезис.
- Стало: неполнота ставится при (а) отсутствии цели среди durable-строк,
  (б) меньше двух строк на media group (Telegram: ≥2), (в) известных из
  same-turn буфера id, которых нет в durable-строках, (г) разрыве
  последовательности `tg_message_id` (альбом идёт пачкой). Буфер теперь
  хранит набор id элементов (`get_media_group_ids`); для публикации
  «текст + альбом по reply» цель — не элемент группы, ложной неполноты нет.
- Probe: `album_incomplete=True`, notice «Элементы альбома прочитаны не
  полностью…».
- Тесты: `test_missing_durable_row_is_partial_via_buffer`,
  `test_missing_row_detected_by_id_gap_without_buffer`,
  `test_missing_target_row_is_partial`,
  `test_single_durable_row_for_group_is_partial`; тест буфера обновлён
  (captionless-альбом теперь хранит только id, caption остаётся None).

### 3. Описание изображения становилось «тезисом»

- Было: `text_suffix` = OCR + описания; фото без подписи/OCR с описанием
  «на фото мужчина на мосту» → `check_claim` вызывался с описанием.
- Стало: OCR — материал тезиса, описание — контекст. Без OCR/подписи тезис
  пуст → честная фраза `FACTCHECK_IMAGE_NO_CLAIM_PHRASES`, `check_claim` не
  вызывается. С подписью/OCR описание идёт в тезис (как ожидает ревью) или
  отдельным non-evidence `<chat_context>`-блоком (`material_context()`),
  когда OCR нет.
- Probe: `claim_text=''`, `desc_ctx=True`.
- Тесты: `test_description_without_ocr_is_not_a_claim`,
  `test_description_with_caption_is_context_not_claim`,
  `test_all_album_images_survive_per_element_budget` (описание + OCR).

### 4. Красный тест старого контракта

- `tests/test_epic33_router_isolation.py`:
  `test_album_without_caption_goes_empty_context_full_pipeline` →
  `test_album_without_caption_is_not_empty_context`. Контракт: альбом без
  подписи и без Vision-активов → техническая/ожидающая фраза, НЕ «пусто»;
  `check_claim` не вызывается. `test_album_reply_uses_buffered_caption_...`
  обновлён под wide-контекст и честную оговорку о недоступных изображениях.
- Полный прогон без playwright: новых падений нет (см. §5).

### 5. Короткий проверяемый тезис в окружении

- Было: `_claim_like_text("Мост обрушился вчера") == False`,
  `"Курс 95" == False` → ложный отказ.
- Стало: recall-предикат: числа/даты независимо от длины; предикат W2;
  глагольная форма (в т.ч. возвратная) + ≥2 содержательных токена.
  Филлеры («ага», «ну такое», «лол», эмодзи) отсекаются
  `is_conservatively_irrelevant`.
- Probe: `Мост обрушился вчера=True`, `Курс 95=True`, `12.10.2026=True`,
  `ага/ну такое/лол=False`.
- Тесты: `test_claim_like_predicate_recall_and_fillers`,
  `test_short_claim_in_previous_message`, `test_numeric_short_claim_in_window`.

### 6. Нерелевантная непустая цель и reply-цепочка

- Было: probe только при `not target_text`; wide-фид возвращался без
  reply-цепочки.
- Стало: консервативно нерелевантная непустая цель («лол», «ага», эмодзи)
  запускает тот же probe; найденный тезис заменяет реакцию. В
  `build_factcheck_context` добавлена существующая цепочка
  `collect_thread_chain`/`render_reply_chains` — родитель старше окна
  попадает в фид. Команды «фактчек …» (и текущая, и прошлые) исключаются.
- Тесты: `test_irrelevant_target_uses_previous_claim`,
  `test_reply_parent_outside_window_in_wide_feed`,
  `test_trigger_message_never_becomes_claim`.

## 5. Прогоны (реальный вывод)

Целевой набор ревью (5 файлов):

```
$ py -3 -m pytest tests/test_factcheck_media_2026_10_25.py tests/test_factcheck_handlers.py tests/test_factcheck_service.py tests/test_factcheck_context_cfg06.py tests/test_factcheck_deep_context_round1023.py -q
176 passed, 2 warnings in 4.66s
```

Расширенный набор (media + wide-default + handlers/service + cfg06 + deep +
buffer + epic33 + round109):

```
$ py -3 -m pytest tests/test_factcheck_media_2026_10_25.py tests/test_factcheck_wide_context_default_2026_10_25.py tests/test_factcheck_handlers.py tests/test_factcheck_service.py tests/test_factcheck_context_cfg06.py tests/test_factcheck_deep_context_round1023.py tests/test_media_group_buffer.py tests/test_epic33_router_isolation.py -q
202 passed, 2 warnings in 5.48s
```

```
$ py -3 -m pytest tests -k "factcheck or vision or media_group" -q --ignore=tests/test_p0_vision_ui_e2e.py
1 failed, 721 passed, 15005 deselected, 4 warnings in 39.64s
FAILED tests/test_soul1_registry_completeness.py::test_legacy_persona_canons_are_registered_with_revision_labels
```

Полный `tests` без playwright (реальный прогон, 13–14 мин):

```
кандидат: 38 failed, 15687 passed, 1 skipped, 1 error in 774.62s
база 534ac7dd (отдельный worktree, затем удалён):
          36 failed, 15624 passed, 1 skipped, 1 error in 842.26s
```

Детерминированное множество падений совпадает: 36 тестов падают и на базе,
и на кандидате (см. список ниже). Два дополнительных падения последнего
полного прогона — `test_mca09_intents_block_e_round1040::test_handle_initiative_cancelled_by_recheck`
и `test_soul1_w5_initiative_vitality::test_check_dry_run_reaches_mock_send_without_publishing`:
оба проходят в изоляции и в связке после всех factcheck-файлов (241 passed),
кода этого лейна не касаются → order/time-зависимые флейки полного прогона,
не детерминированные регрессии. Error — `test_samples_ui_e2e` (нет playwright).

Base = candidate (36): asap7_direct_settings (2), chat_keys (1),
direct_fallback_recompose_asap32 (5), history_cli (1),
hotfix_round1025_logging (1), mca20_rework1_f1_f2 (1),
outgoing_guard_round1022 (2), quota_removal_composer (4),
soul1_composer_parity_off (4), soul1_registry_completeness (1),
soul1_registry_legacy_removal (2), summary_asap2_failsoft_round1027 (1),
summary_l1_clusterizer (1), summary_publish_integration_round1026 (1),
summary_two_call_round1022 (1), t5150_startup_migrations_round1046 (5),
verbilizer_response_modes_round1023 (1), webapp_round1024_nodeflow (1),
webapp_tma_fixes_ui (1).

```
$ py -3 tools/gen_param_registry_round1025.py --check
CHECK OK: реестр 582 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны.
```

Без `--ignore` тот же широкий прогон добавляет 7 ERROR из
`test_p0_vision_ui_e2e.py` (`ModuleNotFoundError: No module named 'playwright'`
— модуль не установлен в этом окружении).

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
11. **Материал изображений теперь до ~20k символов** (2000 на элемент × 10).
    Это данные, не инструкции; при превышении лимита элемента — честная
    оговорка. Верхняя граница привязана к лимиту Telegram (10 элементов).
12. **Полнота альбома** оценивается консервативно: отсутствие цели/меньше
    двух строк/известные id буфера/разрыв последовательности. Разрыв id —
    сигнал Telegram-порядка (альбом идёт пачкой); если платформа когда-нибудь
    отдаст несмежные id, возможна ложная оговорка «прочитаны не полностью»
    (честная перестраховка, не потеря данных). Фраза «нет проверяемого
    утверждения» для изображения не называет число окна (окно при этом
    проверяется и пишется в лог) — так требует §4/§7/§9.14.
