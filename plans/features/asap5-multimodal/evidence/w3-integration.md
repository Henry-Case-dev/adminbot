# ASAP5 W3 — INTEGRATION: кросс-модульные матрицы §23–§26 (evidence, 27.10.2026)

Слайс `ASAP5-INTEGRATION` (Part VI source-2026-10-26). База: `release/p0-2026-10-26`
@ `35ca5ba7` (W1+W2 merged, all green), ветка `task/asap5-integration` — W1+W2+фиксы
в ОДНОМ дереве. Файл матриц: `tests/test_asap5_integration_w3.py` — **66 passed**
(офлайн; LLM/Telegram/сети нет, `.env` в ворктрие отсутствует — Vision-транспорт /
LLM / отправка — контрактные моки, честно отделённые; НЕ-тестируемое офлайн
помечено `needs-real-env` в карте, не выдумано).

Каждая строка = один тест СКВОЗНОГО потока (id/состояния/маркеры payload), не
финальных формулировок. Реальные компоненты: `handlers.summary`-шов, `mca_vision`
(intake→durable job→analysis→render), `chat_context.build_chat_context`,
`DirectChatService._render_current_question` / `_resolve_earlier_image_markers`,
`factcheck_service.resolve_claim_publication`, `ToolRouter` (generate_image /
edit_image), `capability_registry`, `tool_schemas`, `NostalgiaWorker`,
`message_identity.save_live_message`, реальный SQLite (`DatabaseService`).

## 0. Дефекты, найденные матрицами и исправленные (по владеющему компоненту)

1. **`services/database.py::get_smart_message_by_tg_id` — SELECT без
   `media_group_id`.** Whole-post путь фактчека
   (`resolve_claim_publication`, P0-FACTCHECK media §3) читает сохранённую
   строку именно этим ридером; колонки в таблице не было в SELECT → на
   durable-строках (оркестратор v2 / реконструкция без aiogram-target) альбом
   НЕ находился (`media_group_id=None` → element_rows=[target] → OCR/подписи
   остальных элементов альбома терялись, album-проверки неполноты не
   запускались). Компонентные тесты P0-FACTCHECK не ловили (двойники строк
   несли поле, реальный ридер — нет). Фикс: `media_group_id` добавлен в
   SELECT (аддитивно). Регрессия: `tests/test_asap5_integration_w3.py::
   test_b01*` (RED на базе: image_count=1 вместо 2) + full
   factcheck/database/identity-контуры зелёные.
2. **`services/mca_vision.py::runtime_snapshot` — счётчик `queue.failed`
   всегда 0 на реальной БД.** `int((row or {}).get("n") or 0)` — у реального
   aiosqlite.Row нет `.get` (компонентный тест использовал dict-двойник) →
   исключение тихо ловилось → админ-diag §22 «с ошибкой: 0» врал на проде.
   Фикс: `dict(row)` перед чтением. Регрессия: `test_c16_admin_diag_queue_
   and_last_error` (реальная БД: failed=1, last_error.reason_code читается).

Оба фикса минимальные, в владеющих компонентах; файлы: `services/database.py`,
`services/mca_vision.py`.

## 1. Матрица A — Media × Vision × Direct Chat (§24, 22 + ключевой)

| # | Сценарий §24 | Результат | Артефакт (тест) |
|---|---|---|---|
| A01 | Обычное фото | PASS | `test_a01_plain_photo_full_flow_to_direct_chat` |
| A02 | Изображение-документ | PASS | `test_a02_document_image_same_pipeline` |
| A03 | Статический стикер | PASS | `test_a03_static_sticker` |
| A04 | GIF | PASS | `test_a04_gif_animation_cover_frame` |
| A05 | TGS | PASS | `test_a05_tgs_sticker_cover` |
| A06 | WebM-стикер | PASS | `test_a06_webm_video_sticker_cover` |
| A07 | Превью видео | PASS | `test_a07_video_preview_not_full_view` |
| A08 | Превью видеосообщения | PASS | `test_a08_video_note_preview_distinct` |
| A09 | Медиа с подписью | PASS | `test_a09_media_with_caption` |
| A10 | Медиа без подписи | PASS | `test_a10_media_without_caption` |
| A11 | Reply на медиа | PASS | `test_a11_reply_targets_exact_media` |
| A12 | Медиагруппа | PASS | `test_a12_media_group_album_per_message` |
| A13 | Пересланная публикация | PASS | `test_a13_forwarded_post_provenance` |
| A14 | Повторное использование готового анализа | PASS | `test_a14_reuse_ready_analysis_no_new_call` |
| A15 | Распознавание ещё в работе | PASS | `test_a15_in_progress_recognition_pending` |
| A16 | Изменение состояния между сообщениями | PASS | `test_a16_state_changes_between_messages` |
| A17 | Ошибка постановки задания | PASS | `test_a17_enqueue_error_no_fake_pending` |
| A18 | Ошибка распознавания | PASS | `test_a18_recognition_error_distinct_line` |
| A19 | Восстановление после рестарта | PASS | `test_a19_restart_recovery_durable_job` |
| A20 | Отключённый модуль | PASS | `test_a20_module_disabled_honest` |
| A21 | Отсутствующий исходный файл | PASS | `test_a21_missing_source_file_honest` |
| A22 | Одновременная обработка нескольких медиа | PASS | `test_a22_concurrent_multi_media` |
| A23 | КЛЮЧЕВОЙ: вопрос во время работы Vision | PASS | `test_a23_key_scenario_question_while_working` |

Доказанные инварианты (проверяются строками, не декларируются): asset_id =
sha256(chat:tg:file_unique_id:variant) на каждом шаге; per-message состояния
W2 (pending/no_text/failure-строки различимы, pending только при живой
задаче, job_linked); честность превью (VIDEO_PREVIEW_NOTE «не полный
просмотр», ANIMATION_PREVIEW_NOTE «движение не анализируется», mp4-источник —
honest unsupported, file_id кандидата = обложка); payload Direct Chat строится
сквозным `build_chat_context` с media-блоками фасада D9; Current_Question
несёт `[медиа: … tg:id]`; ключевой сценарий: pending + маркер без выдуманных
описаний и без «не могу просматривать», после завершения — результат
используется.

## 2. Матрица B — Media × Fact-check (whole-post)

| # | Сценарий | Результат | Артефакт |
|---|---|---|---|
| B01 | Альбом, OCR обоих элементов | PASS (после фикса №1) | `test_b01_album_whole_post_ocr_all_elements` |
| B02 | Альбом с pending-элементом | PASS | `test_b02_album_pending_member_honest_notice` |
| B03 | Пост-стикер в image-контуре | PASS | `test_b03_sticker_post_image_contour` |
| B04 | Видео-пост через превью-контур | PASS | `test_b04_video_post_preview_material_no_false_failure` |
| B05 | Сбой чтения Vision → честная оговорка | PASS | `test_b05_vision_failed_technical_notice` |
| B06 | no_text ≠ «распознавание не готово» | PASS | `test_b06_no_text_no_false_pending` |

## 3. Матрица C — Image-gen × Direct Chat × Admin (§25, 14 + §22)

| # | Сценарий §25 | Результат | Артефакт |
|---|---|---|---|
| C01 | Создание изображения (реальный раннер) | PASS | `test_c01_create_image_actual_route` |
| C02 | Успешная отправка (reply-доставка) | PASS | `test_c02_successful_send_delivery_reply` |
| C03 | Ошибка генерации (реальный reason) | PASS | `test_c03_generation_error_real_reason` |
| C04 | Ошибка отправки (send_failed) | PASS | `test_c04_send_error_honest` |
| C05 | Повтор после отправки (already_handled) | PASS | `test_c05_follow_up_after_send_skipped` |
| C06 | Редактирование по reply (реестр → submit_edit) | PASS | `test_c06_edit_via_reply_uses_registry_source` |
| C07 | Редактирование ранее созданного (бот-медиа шов W1) | PASS | `test_c07_edit_earlier_bot_created_image` |
| C08 | Уточнение (один clarify, TTL-дедуп) | PASS | `test_c08_clarify_once_not_repeated` |
| C09 | Сохранение исходника между сообщениями | PASS | `test_c09_source_preserved_between_messages` |
| C10 | Недоступность только Vision | PASS | `test_c10_only_vision_unavailable` |
| C11 | Недоступность только Image Generation | PASS | `test_c11_only_imagegen_unavailable` |
| C12 | Недоступность только Image Edit | PASS | `test_c12_only_edit_unsupported` |
| C13 | Штатный fallback (анонс инструментов) | PASS | `test_c13_normal_fallback_no_image_tools` |
| C14 | Отсутствие ложных обещаний | PASS | `test_c14_no_false_promises_after_failure` |
| C15 | §22 Типы медиа = фактические гейты enqueue | PASS | `test_c15_admin_media_types_reflect_reality` |
| C16 | §22 Диагностика = фактические task_jobs | PASS (после фикса №2) | `test_c16_admin_diag_queue_and_last_error` |

Capability claim vs фактический маршрут: dispatch `generate_image` идёт через
РЕАЛЬНЫЙ unified request → `run_image_request` → `generate_and_send` (квота/
idem/доставка) до контрактного мока провайдера `ig.generate`; `edit_image` —
через Capability Registry (`image_edit` ready/unsupported/not-ready) и
СУЩЕСТВУЮЩИЙ `media_execution.submit_edit` с исходником из канонического
реестра intake (file_id реального актива скачивается). capability_view:
`image_generation=ready` при `image_edit=unsupported` (операции независимы).
Канон 15 инструментов, `edit_image` в хвосте (C13).

## 4. Матрица D — Nostalgia × provenance (§23, 16)

| # | Сценарий §23 | Результат | Артефакт |
|---|---|---|---|
| D01 | Спонтанное уместное воспоминание | PASS | `test_d01_spontaneous_appropriate_memory` |
| D02 | Неожиданная осмысленная ассоциация | PASS | `test_d02_unexpected_but_meaningful_association` |
| D03 | Случайный факт без ложной связи | PASS | `test_d03_random_fact_without_false_link` |
| D04 | Репост старой новости (лейбл в пуле) | PASS | `test_d04_repost_old_news_provenance` |
| D05 | Старый локальный мем (секция) | PASS | `test_d05_old_local_meme_section` |
| D06 | Факт об участнике (target_user-лейбл) | PASS | `test_d06_participant_fact_labelled` |
| D07 | Смешение несвязанных событий → отказ | PASS | `test_d07_mixing_unrelated_events_declined` |
| D08 | Противоречивый текст → отказ | PASS | `test_d08_contradictory_text_declined` |
| D09 | Бессмысленная концовка (без цензуры) | PASS | `test_d09_meaningless_ending_not_censored` |
| D10 | Отказ UNCHANGED | PASS | `test_d10_unchanged_decline` |
| D11 | Ошибка provenance (лейбл без источника) | PASS | `test_d11_provenance_error_honest_label` |
| D12 | Self-echo (исключение своих слов) | PASS | `test_d12_self_echo_excluded` |
| D13 | Опубликованное не пере-предлагается (cooldown) | PASS | `test_d13_published_memory_not_reproposed` |
| D14 | Активный разговор (сценарий A, quiet не применяется) | PASS | `test_d14_active_conversation_scenario_a` |
| D15 | Затишье (сценарий B, quiet hours) | PASS | `test_d15_lull_quiet_hours_scenario_b` |
| D16 | Legacy и delegated-маршруты | PASS | `test_d16_legacy_and_delegated_routes` |

Содержательность проверяется по payload (user-блок LLM: пул с provenance-
лейблами, golden с target_user, секции лора/мемов; system-блок: анти-вымысел/
несвязанность/UNCHANGED), исходам воркера (sent/skipped+self_decline/
unchanged/cooldown; дневной лимит не тратится отказом) и делегированию
(`prepared_text_ref="nostalgia:…"`, path=initiative, без второго send-пути).
Помех от новых типов медиа нет: ностальгия читает year-back-пул smart_messages
— медиа-строки W1 в пул года не попадают как текст (проверяется косвенно
D01–D16 на реальном `save_live_message`; interference-чек — E02: медиа-строки
не попадают в текстовый рендер ностальгии).

## 5. Матрица E — Cross-cutting (§26 + горизонтальные контракты)

| # | Проверка | Результат | Артефакт |
|---|---|---|---|
| E01 | Provenance-лейблы согласованы на 4 путях | PASS | `test_e01_forward_provenance_consistent_across_paths` (Vision payload «Переслано из Хабр»; chat_context «Переслано: Хабр»; factcheck forward_source; ностальгия «| Переслано: Хабр]») |
| E02 | Честные unsupported-состояния | PASS | `test_e02_honest_unsupported_states_distinct` (видео без обложки: NO_VISUAL_CONTENT_LINE; голосовая — вне фасада) |
| E03 | (C)-резолв не выдумывает цель | PASS | `test_e03_auto_target_no_guess_for_ambiguity` (пусто/2+ → (); GIF резолвится только обложкой `animation_preview`) |
| E04 | §26 Reviewer: реальные контракты | PASS | `test_e04_reviewer_real_contracts_available` (исходные данные, маршрут, вызванный инструмент с аргументами и результатом, durable task_jobs completed, готовые записи Vision, raw output, итоговые сообщения; nostalgia_log.meta.reason — причина публикации, фиксируется D01/D16) |
| E05 | Нет искусственных квот инструкций | PASS | `test_e05_no_artificial_instruction_quota_in_markers` (cap Current_Question — лимит данных с гарантированным выживанием маркера; honest-строки — различимые факты, ≥5 состояний) |

## 6. Прогоны и регрессия затронутых швов

- **Матрицы:** `py -3 -m pytest tests/test_asap5_integration_w3.py -q` →
  **66 passed** (кандидат: интеграционное дерево с фиксами №1–№2).
- **Регрессия фиксов (фокус):** `tests/test_p0_vision_fix_core.py` +
  `tests/test_asap5_image_admin.py` + `tests/test_factcheck_media_2026_10_25.py`
  + `tests/test_database.py` → **265 passed**; `test_nostalgia_worker.py` +
  `test_nostalgia_prompts.py` + `test_addtr_entry_caption.py` +
  `test_native_reply_media_context_round1024.py` + `test_chat_lore.py` +
  `test_webapp_api.py` → **324 passed**; `test_mca03_message_identity_
  round1027.py` + `test_asap3_identity_aliases.py` → **60 passed**;
  factcheck/cfg02a/tool_schemas/media_group_buffer/summary_publish →
  **158 passed, 1 failed** (см. §7).
- W1/W2 контрактные наборы на кандидате: `tests/test_p0_vision_fix_core.py`
  (114) и `tests/test_asap5_image_admin.py` (29) — зелёные, изменений контрактов
  нет (фиксы аддитивные).

## 7. Инцидентальные находки

- `tests/test_summary_publish_integration_round1026.py::
  TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article` — падает
  УЖЕ НА БАЗЕ `35ca5ba7` (проверено git-stash прогоном без изменений лейна);
  summary-путь, вне скоупа ASAP5-INTEGRATION. `unrelated/pre-existing`,
  перенесено в бэклог-замечание для ответственного лейна.
- Bound-цикл транзиентных неудач vision-джоб (next_retry) не является
  дефектом: A21/C16 дожимают bounded-retry до терминала рабочим циклом —
  контракт D20 подтверждён (4 попытки, затем честный failed).

## 8. Границы честного (needs-real-env — не закрыто офлайн, заявлений нет)

1. Живой Telegram-рендер payload / фактическая доставка send_photo в чат —
   `needs-real-env` (preprod): офлайн доказана запись delivery-вызова в
   контрактный мок отправки.
2. Реальный провайдер Vision/изображений (генерация байтов, edit-результат) —
   `needs-real-env`: транспорт/адаптер — контрактные моки, маршруты и исходы
   доказаны до границы сети.
3. Рестарт реального процесса (сигнал/деплой) — смоделирован новыми объектами
   store/worker на durable-строках (A19); живой рестарт — preprod.
