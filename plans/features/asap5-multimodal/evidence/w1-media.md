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
| GIF | `animation` (mp4) | `animation` | зарегистрирован честно, не анализируется (D18) | UNSUPPORTED (honest) — было |
| Telegram Animation | `animation` | `animation` | зарегистрирован честно, не анализируется | UNSUPPORTED (honest) — было |
| Анимированный TGS | `sticker.is_animated` | `animation` / variant `sticker` | зарегистрирован честно, не анализируется | UNSUPPORTED (honest) — было |
| Видеостикер WebM | `sticker.is_video` | `animation` / variant `sticker` | зарегистрирован честно, не анализируется | UNSUPPORTED (honest) — было |
| Превью обычного видео | `video.thumbnail` | **`video_preview`** (НОВОЕ) | Vision по кадру-обложке (тот же 1 вызов на актив) | **ЗАКРЫТО в W1** |
| Превью видеосообщения | `video_note.thumbnail` | **`video_preview`** / variant `video_note_preview` (НОВОЕ) | Vision по кадру-обложке | **ЗАКРЫТО в W1** |
| Медиа внутри альбомов | `media_group_id` | photo/document/sticker + preview видео | тот же единый путь, каждый item — свой актив + `media_group_id` | SUPPORTED — было, расширено видео |

Вне визуальной матрицы (не типы §9): voice/audio — свой STT-пайплайн
(`handlers/voice_transcription.py`), визуального кандидата нет — честное отсутствие;
не-изображение документом — кандидата нет; видео без thumbnail — кандидата нет
(честная строка `NO_VISUAL_CONTENT_LINE` в рендере, не выдумка).
Дублирования адаптеров нет: новый тип реализован существующим intake-адаптером
в `mca_vision`, новая система не создана.

## 2. Изменения (кандидат)

`services/mca_vision.py`:
1. Константа `ASSET_KIND_VIDEO_PREVIEW = "video_preview"`, включена в
   `SUPPORTED_ASSET_KINDS` (кадр-обложка — растр, реальный файл Bot API).
2. `extract_image_assets()`: адаптеры превью для `video.thumbnail` и
   `video_note.thumbnail` (aiogram 3.31: поле `thumbnail`; fallback `thumb`);
   без file_id/file_unique_id — честный пропуск (превью нет — кандидата нет).
   file_id кандидата = file_id обложки, не самого видео.
3. `media_capability()` + токены `REPRESENTATION_VISION/UNSUPPORTED/NONE` —
   read-only матрица возможностей (единый источник для тестов/evidence).
4. Рендер D9: для превью-актива обязательная заметка `VIDEO_PREVIEW_NOTE`
   («видео: проанализировано превью (кадр-обложка), не полный просмотр») перед
   содержимым кадра; pending-строка превью отличима; медиа-строка без визуальных
   кандидатов (видео без превью, media_type video/animation/sticker) даёт честный
   блок `NO_VISUAL_CONTENT_LINE` вместо молчаливого отсутствия блока; текстовые/
   голосовые строки по-прежнему None (не тронуты).
5. `recognize_target()`: в ready-полезную нагрузку (оба пути — cache и fresh)
   добавлен маркер `asset_kind` (аддитивно; consumers JSON терпят лишний ключ).

`services/media_download.py` — изменений не требует: превью качается
существующим `mca_vision.download_telegram_file` (тот же bot.get_file/download,
что у фото; в локальном режиме — тот же aiogram-резолв file_path).

## 3. Представление (§10, REPRESENTATION) — уровень за уровнем

- Статические изображения → действующий Vision (без изменений).
- Анимации (GIF/TGS/WebM) → зарегистрированы, явная строка «распознавание
  изображений не применимо» (D18, сохранено); своего LLM-вызова нет.
- Понимание движения/извлечения кадров (ffmpeg) — НОВЫЙ пайплайн, владельцем
  запрещён на W1 («без нового пайплайна») — честно НЕ заявлено как умение.
- Видео: анализ превью (кадр-обложка) — ЗАКРЫТО с обязательной маркировкой
  «превью, не полный просмотр»; полного просмотра у системы нет и не
  заявляется; «только описание» — описание приходит из того же Vision-вызова
  (канал `visual_descriptions` P0-DELTA сохранён); «нет доступного содержимого» —
  явная честная строка для видео без превью.
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
| Reply на GIF | — | — | — | — | честный `unsupported` (animation), не случайный файл | VERIFIED (honest) |
| Reply на стикер | ✔ | ✔ | ✔ | ✔ | резолв по reply | VERIFIED |
| Reply на видео | ✔ | ✔ | ✔ (его превью) | ✔ обложки | резолв по reply, не сосед | VERIFIED |
| Пересланные | ✔ | ✔ | ✔ | ✔ | реестр по chat:tg; forward-поля — в smart_messages (D3) | VERIFIED |
| Медиагруппы | ✔ | ✔ | ✔ (item свой) | ✔ | `media_group_id` на активе | VERIFIED |
| С подписью / без | ✔ | ✔ | ✔ | ✔ | caption не влияет на реестр (хранится в smart_messages) | VERIFIED |
| Ранее сохранённые вложения | ✔ | ✔ | ✔ | ✔ | активы читаются по (chat, tg) из реестра | VERIFIED |
| Медиа, созданное ботом | — | — | — | — | observer пропускает собственные сообщения бота (`handlers/summary.py`, существующий дизайн; вне write_scope слайса) | PARTIAL (honest, задокументировано) |

- «Reply именно на это изображение, без соседнего файла»: `resolve_target_assets`
  резолвит по reply_tg_id; несколько supported без селектора → `ambiguous` (не
  случайный выбор); тест `test_asap5_reply_targets_exact_media_not_neighbor`.
- «Не заставлять пересказывать доступное медиа»: превью видео теперь доходит
  до tool `recognize_image` (готовый анализ + `asset_kind`) и рендера контекста.
- Интеграционный шов (вне write_scope W1, для W2/VISION): в
  `services/direct_chat_service.py` локальный список `_IMAGE_REF_KINDS =
  {"photo","document","sticker"}` (auto-target «ранее присланного изображения» в
  Direct Chat) дублирует резолюцию `SUPPORTED_ASSET_KINDS` и после W1 не включает
  `video_preview` — reply/tool-пути превью покрывают, авто-цель Direct Chat —
  нет. Классификация PIPELINE остаётся честной PARTIAL до этого шва.

## 5. Прогоны

База (до изменений, worktree = `1b93c6db`):
- `tests/test_p0_vision_fix_core.py` — 54 passed
- `tests/test_factcheck_media_2026_10_25.py` — 53 passed (требование регрессии)
- `test_vision_adapt + test_vision_dl_fix + test_media_download` — 22 passed, 38 skipped (env-зависимые скипы, паритет с базой)

RED (на базовом `services/mca_vision.py`, новые тесты):
- 18/18 новых asap5-тестов падают (16 в первом прогоне -k capability/preview…;
  2 — reply_targets_exact/album_mixed), что подтверждает: тесты защищают новое
  поведение, а не существующее.

PASS (кандидат):
- `tests/test_p0_vision_fix_core.py` — 72 passed (54 прежних + 18 новых)
- Регрессия факчек-медиа: `test_factcheck_media_2026_10_25.py` — 53 passed (зелёный)
- Расширенный контур: `test_mca19_block_a/c/d/g + rework_r1 + test_mca17_perimeter_events
  + test_factcheck_p0_fc + test_addtr_postgen + test_native_reply_media_context_round1024
  + test_hotfix_round1025_media + test_vision_adapt + test_vision_dl_fix +
  test_media_download + test_slavik_media_types` — 230 passed, 38 skipped (тот же
  скип-набор, что в базе) + 168 passed по второму пакету смежных наборов
- `compileall services tests` — OK

Команда воспроизведения (из корня worktree):
`...python.exe -m pytest tests/test_p0_vision_fix_core.py tests/test_factcheck_media_2026_10_25.py -q`

## 6. Границы честного (не закрыто W1)

1. GIF/Animation/TGS/WebM: контент не анализируется (D18 — свободная надстройка
   нативных видео-инструментов); регистрация и честные строки сохранены.
2. Извлечение информативных кадров видео — новый пайплайн, запрещён границами
   W1; не реализовано и не заявлено.
3. Бот-собственное медиа не попадает в реестр (observer скипает свои сообщения) —
   существующий дизайн `handlers/summary.py` вне write_scope слайса.
4. Direct Chat `_IMAGE_REF_KINDS` (auto-target) — шов для W2 (см. §4).
5. Дублирование `_IMAGE_REF_KINDS` — существующее; адаптеры не дублировались.
