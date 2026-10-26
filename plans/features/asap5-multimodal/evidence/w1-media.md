# ASAP5 W1 — MEDIA-RECOGNITION: универсальное распознавание медиа (§9–§11)

Слайс: `ASAP5-MEDIA-RECOGNITION` (строки карты REQ-MEDIA-TYPES / REQ-MEDIA-REPRESENTATION /
REQ-MEDIA-PIPELINE). Ветка `task/asap5-media`, база `release/p0-2026-10-26` @ `1b93c6db`.
Кандидат: см. §5 (commit SHA). Ограничения лейна: без нового пайплайна/провайдера/второго
LLM-вызова; без Nostalgia/Vision-состояний/image-gen (параллельные слайсы).

## 1. Честная матрица возможностей (§9, TYPES)

Источник истины — `mca_vision.media_capability()` поверх `extract_image_assets()`
(тот же код, что и intake; тесты читают ровно его токены):

| Тип (§9) | Детект | Адаптер / asset_kind | Путь представления | Статус |
|---|---|---|---|---|
| Фото | `message.photo` (крупнейший) | `photo` / size_variant `large` | Vision (OCR + описание), авто-джоб | SUPPORTED — было |
| Изображение документом | `document` + `image/*` | `document` | Vision, авто-джоб | SUPPORTED — было |
| Статический стикер | `sticker` (не animated/video) | `sticker` (webp) | Vision, авто-джоб | SUPPORTED — было |
| GIF | `animation` (mp4) + `animation.thumbnail` | `animation` (источник) + **`animation_preview`** (НОВОЕ) | источник — честно зарегистрирован (D18); обложка — Vision с маркировкой «движение не анализируется» | ЗАКРЫТО в W1 (обложка) |
| Telegram Animation | `animation` + thumbnail | `animation` + **`animation_preview`** | как GIF | ЗАКРЫТО в W1 (обложка) |
| Анимированный TGS | `sticker.is_animated` + `sticker.thumbnail` | `animation` / variant `sticker` + **`animation_preview`/`sticker_preview`** (НОВОЕ, Bot API ≥7.2) | источник честно не анализируется; обложка — Vision | ЗАКРЫТО в W1 (обложка) |
| Видеостикер WebM | `sticker.is_video` + thumbnail | как TGS | как TGS | ЗАКРЫТО в W1 (обложка) |
| Превью обычного видео | `video.thumbnail` | **`video_preview`** (НОВОЕ) | Vision по кадру-обложке (тот же 1 вызов на актив) | **ЗАКРЫТО в W1** |
| Превью видеосообщения | `video_note.thumbnail` | **`video_preview`** / variant `video_note_preview` (НОВОЕ) | Vision по кадру-обложке | **ЗАКРЫТО в W1** |
| Медиа внутри альбомов | `media_group_id` | photo/document/sticker + preview видео | тот же единый путь, каждый item — свой актив + `media_group_id` | SUPPORTED — было, расширено видео |

Вне визуальной матрицы (не типы §9): voice/audio — свой STT-пайплайн
(`handlers/voice_transcription.py`), визуального кандидата нет — честное отсутствие;
не-изображение документом — кандидата нет; видео без thumbnail — кандидата нет
(честная строка `NO_VISUAL_CONTENT_LINE` в рендере, не выдумка).
Дублирования адаптеров нет: новые типы реализованы существующим intake-адаптером
в `mca_vision` (общий хелпер `_append_preview_candidate`), новая система не создана.

## 2. Изменения (кандидат)

`services/mca_vision.py`:
1. Константы `ASSET_KIND_VIDEO_PREVIEW = "video_preview"` и
   `ASSET_KIND_ANIMATION_PREVIEW = "animation_preview"`, обе в
   `SUPPORTED_ASSET_KINDS` (обложки — растр, реальные файлы Bot API).
2. `extract_image_assets()`: общий хелпер `_append_preview_candidate()` —
   адаптеры превью для `video.thumbnail`, `video_note.thumbnail`,
   `animation.thumbnail` (GIF) и `sticker.thumbnail` (TGS/WebM, Bot API ≥7.2);
   aiogram 3.31 поле `thumbnail` (+ fallback `thumb`). Без file_id/
   file_unique_id — честный пропуск (превью нет — кандидата нет).
   file_id кандидата = file_id обложки, не носителя.
3. `media_capability()` + токены `REPRESENTATION_VISION/UNSUPPORTED/NONE` —
   read-only матрица возможностей (единый источник для тестов/evidence).
4. Рендер D9: для превью видео — обязательная заметка `VIDEO_PREVIEW_NOTE`
   («проанализировано превью (кадр-обложка), не полный просмотр»); для обложек
   анимаций — `ANIMATION_PREVIEW_NOTE` («движение не анализируется»); при
   наличии обложки в блоке противоречивая строка D18 «не применимо» не
   выводится (без обложки — сохраняется); медиа-строка без визуальных
   кандидатов (видео/GIF без превью, media_type video/animation/sticker) даёт
   честный блок `NO_VISUAL_CONTENT_LINE` вместо молчаливого отсутствия блока;
   текстовые/голосовые строки по-прежнему None (не тронуты).
5. `recognize_target()`: в ready-полезную нагрузку (оба пути — cache и fresh)
   добавлен маркер `asset_kind` (аддитивно; consumers JSON терпят лишний ключ).

`services/media_download.py` — изменений не требует: превью качается
существующим `mca_vision.download_telegram_file` (тот же bot.get_file/download,
что у фото; в локальном режиме — тот же aiogram-резолв file_path).

## 3. Представление (§10, REPRESENTATION) — уровень за уровнем

- Статические изображения → действующий Vision (без изменений).
- Анимации (GIF/Animation/TGS/WebM) → **обложка (thumbnail) через существующий
  Vision** — корректное визуальное представление для текущей модели с явной
  маркировкой «превью анимации, движение не анализируется»; исходные байты
  (mp4/TGS/WebM) остаются честно зарегистрированным unsupported-источником
  (D18); при отсутствии обложки — строка D18 «не применимо» сохраняется.
- Понимание движения (информативные кадры) — НЕ реализовано и НИГДЕ не
  заявляется: требует извлечения кадров (ffmpeg) = новый пайплайн, запрещён
  границами W1; обложка никогда не выдаётся за анализ движения (условная
  клаузула §10 «если необходимо понимание движения» — задокументирована как
  вне границ волны).
- Видео: анализ превью (кадр-обложка) — ЗАКРЫТО с обязательной маркировкой
  «превью, не полный просмотр»; полного просмотра у системы нет и не
  заявляется; «только описание» — описание приходит из того же Vision-вызова
  (канал `visual_descriptions` P0-DELTA сохранён); «нет доступного содержимого» —
  явная честная строка для видео/анимации без превью.
- Превью не выдаётся за полный просмотр (заметка в каждой строке рендера и
  маркер `asset_kind: video_preview` в tool-полезной нагрузке), и видео с
  пригодным превью больше не «полностью недоступно».

## 4. Единый пайплайн (§11, PIPELINE)

11 форматов из §11 против реестра `mca_media_assets` (тесты в
`tests/test_p0_vision_fix_core.py`, секция ASAP5):

| Формат | chat_id | message_id | asset_id | file_id | Связь с сообщением | Статус |
|---|---|---|---|---|---|---|
| Обычное вложение | ✔ | ✔ | ✔ | ✔ | `message_key = chat:tg` | VERIFIED |
| Reply на изображение | ✔ | ✔ (reply_tg) | ✔ точный (make_asset_id) | ✔ | резолв по reply | VERIFIED |
| Reply на GIF | ✔ | ✔ | ✔ (его обложка) | ✔ обложки | резолв по reply, байты mp4 — honest-хвост unsupported | VERIFIED |
| Reply на стикер | ✔ | ✔ | ✔ | ✔ | резолв по reply | VERIFIED |
| Reply на видео | ✔ | ✔ | ✔ (его превью) | ✔ обложки | резолв по reply, не сосед | VERIFIED |
| Пересланные | ✔ | ✔ | ✔ | ✔ | реестр по chat:tg; forward-поля — в smart_messages (D3) | VERIFIED |
| Медиагруппы | ✔ | ✔ | ✔ (item свой) | ✔ | `media_group_id` на активе | VERIFIED |
| С подписью / без | ✔ | ✔ | ✔ | ✔ | caption не влияет на реестр (хранится в smart_messages) | VERIFIED |
| Ранее сохранённые вложения | ✔ | ✔ | ✔ | ✔ | активы читаются по (chat, tg) из реестра | VERIFIED |
| Медиа, созданное ботом | ✔ | ✔ | ✔ | ✔ | тот же intake-путь из observer-ветки собственных сообщений (шов закрыт, см. §7) | VERIFIED |

- «Reply именно на это изображение, без соседнего файла»: `resolve_target_assets`
  резолвит по reply_tg_id; несколько supported без селектора → `ambiguous` (не
  случайный выбор); тест `test_asap5_reply_targets_exact_media_not_neighbor`.
- «Не заставлять пересказывать доступное медиа»: превью видео теперь доходит
  до tool `recognize_image` (готовый анализ + `asset_kind`) и рендера контекста.
- Интеграционный шов Direct Chat (auto-target «ранее присланного») — ЗАКРЫТ
  в §7: `_IMAGE_REF_KINDS` включает preview-kind.

## 5. Прогоны

База (до изменений, worktree = `1b93c6db`):
- `tests/test_p0_vision_fix_core.py` — 54 passed
- `tests/test_factcheck_media_2026_10_25.py` — 53 passed (требование регрессии)
- `test_vision_adapt + test_vision_dl_fix + test_media_download` — 22 passed, 38 skipped (env-зависимые скипы, паритет с базой)

RED (честность тестов):
- 18/18 новых asap5-тестов падают на базовом `services/mca_vision.py` (16 в
  прогоне -k capability/preview…; 2 — reply_targets_exact/album_mixed);
- 4 падения на промежуточном кандидате 96b8b443 для animation-preview
  дополнений (matrix[gif_animation], reply_targets, distinct_and_honest,
  render_honesty) — тесты защищают новое поведение, а не существующее.

PASS (кандидат, финальная версия):
- `tests/test_p0_vision_fix_core.py` — 74 passed (54 прежних + 20 новых)
- Регрессия факчек-медиа: `test_factcheck_media_2026_10_25.py` — 53 passed (зелёный)
- Полный контур одним прогоном (16 файлов: core + factcheck-media + vision_adapt +
  vision_dl_fix + media_download + slavik_media_types + mca19 block a/c/d/g +
  rework_r1 + mca17_perimeter + factcheck_p0_fc + addtr_postgen +
  native_reply_media_context + hotfix_round1025) — **400 passed, 38 skipped**
  (тот же env-скип-набор, что в базе)
- `compileall services tests` — OK

Команда воспроизведения (из корня worktree):
`...python.exe -m pytest tests/test_p0_vision_fix_core.py tests/test_factcheck_media_2026_10_25.py -q`

## 6. Границы честного (не закрыто W1)

1. Понимание движения через информативные кадры (GIF/видео) — требует
   извлечения кадров (новый пайплайн), вне границ W1; не реализовано и не
   заявляется; обложка честно маркируется как «движение не анализируется».
2. ~~Бот-собственное медиа не попадает в реестр~~ — ЗАКРЫТО финализацией
   (шов 1, см. §7).
3. ~~Direct Chat `_IMAGE_REF_KINDS` — шов для W2~~ — ЗАКРЫТО финализацией
   (шов 2, см. §7).
4. Полный просмотр видео (в отличие от анализа обложки) — не существует в
   системе и не заявляется; видео-инструменты (transcribe/summarize) остаются
   нативному слою по ранее принятому решению владельца.
5. Дублирование `_IMAGE_REF_KINDS` — существующее; адаптеры не дублировались.

## 7. Финализация REQ-MEDIA-PIPELINE: закрытие двух швов

Оба шва из честного остатка §4/§6 закрыты минимальными изменениями БЕЗ нового
пайплайна/провайдера/LLM-вызова (границы слайса соблюдены). Ностальгия-файлы
параллельного лейна `task/asap5-nostalgia` не тронуты.

### 7.1 Шов 1 — медиа, созданное ботом (intake)

`handlers/summary.py` (observer, ветка скипа собственных сообщений): перед
`return UNHANDLED` — тот же intake-путь, что у пользовательского медиа:
`mca_vision.register_intake_assets(_db, message, message_row_id=None)` →
`enqueue_intake_jobs` (реестр → durable-джоба, D18-порядок сохранён).
Fail-open (сбой реестра не роняет observer); гейты те же K1/K2/requested.
Сообщение бота в контент чата по-прежнему НЕ пишется (прежний дизайн
сохранён байт-в-байт для текста и всего не-медиа: `extract_image_assets`
пуст → активов нет → поведение идемпотентно прежнему).

Provenance автора: схема реестра v32 (колонки автора нет — schema change вне
границ) не меняется; авторство фиксируется честно на существующей оси —
durable job payload несёт `user_id = id` бота-автора (`from_user.id`), плюс
связь `chat_id:tg_message_id` сообщения бота (по нему reply-путь резолвит
актив). Строки `smart_messages` для бота нет — это прежний дизайн observer,
не потеря данных реестра (активы самодостаточны для tool/reply-путей).
Рендер inline-контекста (`render_media_context_async`) требует строку
smart_messages и для бот-медиа честно не строится — representation доступна
через reply/tool-путь (`resolve_target_assets` → `recognize_target`), что и
есть контракт §11 «не заставлять пересказывать».

Тесты (`tests/test_p0_vision_fix_core.py`):
- `test_asap5_bot_media_intake_via_observer` — INTEGRATION: реальный
  aiogram-Message от бота (from_user is_bot=True) через `summary_observer`:
  контент-строки НЕТ, актив зарегистрирован (chat_id/tg_message_id/
  asset_kind/file_id/message_key), payload джобы `user_id=999` (бот-автор),
  job → ready → `recognize_target(reply_tg_id)` → `status=ready`,
  `asset_kind=photo` — representation без ручного пересказа.
- `test_asap5_bot_text_message_not_intake_not_saved` — CONTRACT границы:
  текст бота — прежнее поведение (ни строки контента, ни активов).

### 7.2 Шов 2 — preview-kind в Direct Chat auto-target

`services/direct_chat_service.py`: `_IMAGE_REF_KINDS` =
`{"photo","document","sticker"} ∪ {"video_preview","animation_preview"}` —
auto-target «ранее присланного изображения» (способ C,
`_resolve_earlier_image_markers`) treats preview-покрытое медиа так же, как
reply/tool-пути. Однозначность не ослаблена: `seen` по tg_message_id
(`setdefault`), два разных media-сообщения в окне → цели НЕТ (тест).
NB: отдельного kind `sticker_preview` в реестре НЕ существует — превью
стикера (TGS/WebM) хранится как kind `animation_preview` +
`size_variant="sticker_preview"` (см. `_append_preview_candidate`);
комплект непрерывности = эти два kind. `animation` (честный
unsupported-хвост) кандидатом остаться не мог и не стал.

Тесты (`tests/test_addtr_entry_caption.py`, TestAdtrEntryEarlierImageRef):
- `test_video_preview_kind_resolves_as_earlier_target` — маркер
  `[медиа: video_preview tg:500]`.
- `test_animation_preview_kind_resolves_as_earlier_target` — маркер
  `[медиа: animation_preview tg:501]` (покрывает и sticker-preview-вариант).
- `test_gif_rows_resolve_via_cover_only` — GIF (animation+animation_preview,
  один tg) резолвится по обложке, unsupported-хвост не создаёт двусмысленности.
- `test_two_preview_media_ambiguous_no_marker` — два preview-медиа → цели
  НЕТ (однозначность сохранена; зелёный и на базе — граница).

### 7.3 Прогоны (кандидат финализации)

RED: 4 новых теста падали на кандидате 38c3e1f1 (bot-media intake через
observer отсутствовал; preview-kind не резолвились auto-target'ом);
boundary-тест текста бота — зелёный на базе (фиксирует прежнее поведение).

PASS (кандидат финализации, ветка `task/asap5-media`):
- `test_p0_vision_fix_core.py` — 76 passed (74 прежних + 2 новых bot-media)
- `test_addtr_entry_caption.py` + `test_summary_handlers.py` — 101 passed
  (вкл. 4 новых preview-kind тестов и регресс `test_bot_own_message_skipped`)
- Регрессия факчек-медиа: `test_factcheck_media_2026_10_25.py` — зелёный
- Полный 16-файловый контур (core + factcheck-media + vision_adapt +
  vision_dl_fix + media_download + slavik_media_types + mca19 a/c/d/g +
  rework_r1 + mca17_perimeter + factcheck_p0_fc + addtr_postgen +
  native_reply_media_context_round1024 + hotfix_round1025_media) —
  **440 passed, 0 failed**
- `compileall services handlers` — OK

Команда (из корня worktree):
`py -3 -m pytest tests/test_p0_vision_fix_core.py tests/test_factcheck_media_2026_10_25.py -q`

### 7.4 Честный остаток после финализации

- Inline-рендер бот-медиа в контексте истории (без reply/tool) — не строится
  (нет строки smart_messages, прежний дизайн); контракт §11 выполняется
  reply/tool-путём.
- `sticker_preview` — size_variant, не kind (документировано в 7.2).
