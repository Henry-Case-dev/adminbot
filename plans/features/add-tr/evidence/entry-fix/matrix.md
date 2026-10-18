# ADD-TR.2 / слайс ADTR-ENTRY — evidence (lane ADTR-ENTRY-FIX)

- Дата: 19.10.2026. Кандидат: рабочее дерево на базе `76b156e0` (без коммита, на ревью).
- Изменённые файлы (git hash-object, sha12):
  - `handlers/direct_chat.py` — `0bcc9170393e` (было `3a7a5118`)
  - `services/direct_chat_service.py` — `870f74fd279f` (было `37446129`)
  - `tests/test_addtr_entry_caption.py` (новый, `TEST-LIFECYCLE: CONTRACT owner=ADTR-ENTRY`) — `220d2c393c21`
  - `tests/test_budget_global_toggle_round1024.py`, `tests/test_mca07_retrieval_context_round1027.py` — паритет стабов `_render_current_question(..., extra_markers=())` (расширенная сигнатура).
- RED → GREEN:
  - RED: `red.txt` (ImportError `_message_user_text`: входной API отсутствует; сбор матрицы до реализации) +
    поведенческий `red-behavior.txt` (`probe_red_vs_green.py` на committed-байтах: photo+caption →
    `UNHANDLED`, `handle_calls=0`; `<Current_Question>` теряет текст подписи — только маркер).
  - GREEN: `green-core.txt` (489 passed) и `green-direct-cluster.txt` (669 passed); тот же пробник в рабочем
    дереве: Direct активируется (`handle_calls=1`), подпись + MessageRef в `<Current_Question>`.
- Живой прод/SSH не трогался (lane-правило). UI не менялся — Playwright/Browser Use не применимы (бэкендный вход).

## Что реализовано (минимально, строго §ADD-TR.2)

1. **Единое потребление события**: `text` → `caption` (сервис и handler — один контракт);
   `entities`/`caption_entities` — пара без смещения (offset'ы валидны только к своей строке);
   пустой текст+без картинки — прежнее UNHANDLED (голос/видео/стикер идут в 0i и ниже);
   «голое» photo/image-document реплаем на бота (осознанное обращение) — активирует Direct;
   PDF-документ картинкой не считается (image-document = `mime image/*`, политика MCA-19).
   Отдельного «caption bot» нет — тот же роутер 0h и тот же `DirectChatService.handle`.
2. **Три способа ссылки на изображение**:
   - (A) photo+caption: текст подписи в `<Current_Question>` + `[медиа: photo tg:<id>]` самого сообщения;
   - (B) текстовый reply на photo/image-doc: ref из `reply_to_message` (маркер reply), reply-на-ботовский
     image-результат целится в картинку, а не в текст ответа (тест);
   - (C) явная ссылка на ранее присланное в чате изображение: bounded-резолв по каноническому реестру
     MCA-19 `mca_media_assets` (окно 1800 c, ≤24 строк, только `photo/document/sticker`, только `tg_message_id`
     старее текущего), ровно ОДНО изображение-сообщение → маркер того же диалекта в `<Current_Question>`;
     пусто/несколько/ошибка → БЕЗ маркера (никакого «угаданного» распознавания; уточнение — штатный
     clarify-путь L1/Writer). Vision OFF (env-мастер) = активы не регистрируются → резолв честно пуст.
3. **Подпись доходит до семантических путей**: `query` хода = text/caption → Fast-Track «нарисуй…» (query),
   L1-контекст, стат-интенты, mood, speech-оценка, F6-продюсер, image-пре-гейты — без новых писателей.
4. **Приоритеты и запреты не нарушены**: порядок роутеров не менялся (0c–0g консьюмят раньше 0h —
   тест «чекап»-подписи через Dispatcher); master-флаг модуля гейтит и caption-события; forward без
   обращения не перехватывается; cooldown/ACL/замки не трогались.

## Сценарная матрица (§ADD-TR.5, релевантная входу) — тест → статус

| Сценарий | Тест (текущий файл / регрессия) | Статус |
|---|---|---|
| S1 фото+caption «бот, что на этой картинке?» → Direct + правильный photo-ref | `test_photo_caption_botword_triggers_direct`, `test_current_question_carries_caption_and_photo_ref`, `test_real_photo_caption_mention_reaches_direct` | GREEN (сквозное исполнение `recognize_image` — вне лейна: VISION-FIX-CORE) |
| S2 текстовый reply на фото «бот, прочитай надпись» | `test_current_question_carries_reply_photo_ref_for_text_reply` (+ существующие media-маркеры/`_l1_reply_block`) | GREEN (вход); реальный OCR — вне лейна |
| S3 медиа без обращения — обычное поведение | `test_photo_caption_without_addressing_unhandled`, `test_photo_without_caption_and_without_addressing_unhandled`, `test_media_group_member_without_caption_unhandled`, `test_real_photo_caption_plain_unhandled`, `test_non_image_reply_to_bot_without_caption_unhandled` | GREEN |
| S4 «бот, что на картинке» без вложения → уточнение, не выдуманное распознавание | `test_no_assets_no_marker`, `test_two_images_ambiguous_no_marker`, `test_album_members_ambiguous_no_marker`, `test_current_message_asset_excluded`; уточнение — штатный L1/L2 clarify (вне правок) | GREEN (без «угаданной» цели) |
| S6/S7 «нарисуй»/«надо нарисовать» в подписи | `test_caption_reaches_image_route_query` (подпись доходит до image-маршрута как query) | GREEN (вход); единая генерация/списание — Fast-Track/§5.10 (вне лейна) |
| S11 «фактчек»/S12 «чекап» в подписях — приоритет 0c/0g | `test_canonical_checkup_caption_priority_over_direct` + существующие suite'ы факт-чека | GREEN |
| caption_entities: mention/text_mention/@-fallback | `test_caption_mention_entity_triggers`, `test_caption_text_mention_entity_by_user_id`, `test_caption_username_fallback_without_entities` | GREEN |
| media_group: caption 1-го/другого элемента; элемент без подписи | `test_media_group_caption_first_element_triggers`, `test_media_group_caption_other_element_triggers`, `test_media_group_member_without_caption_unhandled` | GREEN |
| forward_origin | `test_forwarded_photo_caption_without_addressing_unhandled` (+ существующие veto: image pre-gate `_forward_source_of`, capability-детектор `forwarded`) | GREEN |
| image-document vs прочий документ | `test_image_document_caption_triggers`, `test_pdf_document_reply_to_bot_unhandled`, `test_pdf_document_caption_with_addressing_triggers` | GREEN |
| reply на бот-овский image-результат → цель-картинка | `test_reply_to_bot_image_result_targets_image_not_text` | GREEN |
| (C) однозначное/неоднозначное/ошибка БД/kill-switch | `TestAdtrEntryEarlierImageRef` (10 кейсов) | GREEN |
| сквозной ход: caption доходит до LLM-контекста; пустой текст+фото-reply не падает | `test_handle_flow_caption_reaches_llm_context`, `test_handle_flow_bare_photo_reply_to_bot` | GREEN |

## Вне этого лейна (честные границы)

- Реальное исполнение `recognize_image` (bytes→анализатор, бот-картинки как активы) — VISION-FIX-CORE/ADTR-TOOLS
  (прод сейчас: `vision_unavailable`; рекон §4).
- Пост-генерационное описание bitmap — ADTR-POSTGEN (§ADD-TR.4).
- «Чекап по свободной форме» (get_bot_health в L1-подсети) — ADTR-TOOLS (рекон §3, GAP).
- Живые Telegram-проверки (S1–S5 в реальном чате) — ADTR-VERIFY (postdeploy).
- «Свободная семантика» («надо нарисовать», «посмотри, что на фото») исполняется существующими контурами
  (L1 §5.10 / vision intent); этот лейн гарантирует доставку события/подписи до них.

## Прогоны-регрессии (кроме green-файлов)

- `tests/test_asap7_direct_settings.py` — 2 падения (`test_migration_v35_idempotent_twice`,
  `test_backup_guard_fires_before_pending_step`) — **пред-существующие**: воспроизведены на чистом
  worktree HEAD (`f9283b3d`) без моих правок (устаревшие ожидания v35 при уже вкоммиченной v36).
- `tests/test_outgoing_guard_round1022.py::test_send_rich_message_*`, `tests/test_summary_publish_integration_round1026.py::test_on_l1_not_usable_level2_l2_publishes_article` —
  **пред-существующие** (падают на чистом HEAD).
- `tests/test_soul1_w4_humor_craft.py::test_registry_fingerprint_matches_declared_constant` — падает в
  общем worktree из-за **чужой незакоммиченной** правки промпта `internal.initiative_observer`
  (`services/initiative_observer.py`, лейн не мой); на чистом HEAD + только мои 2 файла — PASS
  (сравнение хэшей блоков реестра: diff = ['internal.initiative_observer']).
