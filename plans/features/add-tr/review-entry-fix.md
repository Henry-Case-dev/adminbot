# REV-ENTRY-FIX — вердикт (входной маршрутизатор ADD-TR.2 / слайс ADTR-ENTRY)

Независимое ревью. Read-only (чужие лейны не тронуты); этот коммит — только данный документ.

**Кандидат (uncommitted поверх `76b156e0`):** `handlers/direct_chat.py` blob12 `0bcc9170393e`, `services/direct_chat_service.py` `870f74fd279f`, новый `tests/test_addtr_entry_caption.py` `220d2c393c21` (44 теста, CONTRACT owner=ADTR-ENTRY), стабы `test_budget_global_toggle_round1024.py`/`test_mca07_retrieval_context_round1027.py` (по 1 строке). Хеши сверены и в дереве, и в моём изолированном worktree. HEAD уже `473b4a2a`, но `git diff 76b156e0 473b4a2a` по всем 5 файлам пуст — база не сдвинута по существу.

## 1. RED→GREEN — воспроизведено (committed-байты)
Свой прогон `probe_red_vs_green.py` в изолированном worktree `76b156e0`: на чистых committed-байтах — `UNHANDLED`/`handle_calls=0`, `<Current_Question>` только с маркером (`[медиа: photo tg:777]`, подпись потеряна); после применения кандидата — `result=None/handle_calls=1`, `'<Current_Question>\nчто на этой картинке? [медиа: photo tg:777]\n</Current_Question>'`. 4/4 строки совпали с `red-behavior.txt`.

## 2. Единое потребление — подтверждено кодом и тестами
`_effective_text`/`_message_user_text` (text→caption, strip, не-str→""), `_message_entities` (пары text/entities и caption/caption_entities без смешения), `_has_image_attachment` (photo-список или document `image/*`), `_has_bot_mention`/`_is_direct_trigger` — на паре из `_message_entities`. Handler: пустой текст без картинки → прежнее UNHANDLED (voice/video/sticker идут дальше как раньше); «голое» photo/image-doc активирует Direct только при осознанном обращении (reply/keyword — без текста невозможны); отдельного «caption bot» нет — тот же роутер и тот же `DirectChatService.handle`. Сервис: `query`/mood/speech/context — везде `_message_user_text`; `<Current_Question>` несёт подпись + собственный/ответный маркер. PDF картинкой не считается (`test_pdf_document_reply_to_bot_unhandled`; с обращением в подписи — текстовое событие, `test_pdf_document_caption_with_addressing_triggers`), image-document (`image/*`) — считается (`test_image_document_caption_triggers`).

## 3. Ref A/B/C — подтверждено; (C) соответствие §ADD-TR.2
(A) маркер самого сообщения + текст подписи в `<Current_Question>` (пробник, тест). (B) reply-текст → ref из `reply_to_message`; reply на ботовский image-результат целится в картинку (`test_reply_to_bot_image_result_targets_image_not_text`). (C) `_resolve_earlier_image_markers`: только когда нет own-media/reply, есть vision-intent, включён kill-switch маркеров; bounded-резолв по каноническому `mca_media_assets` (окно 1800 c, ≤24 строк, kind ∈ photo/document/sticker, только `tg_message_id` < текущего), ровно ОДНО изображение → маркер того же диалекта; пусто/несколько/ошибка/выключенный master → без маркера, fail-open, один резолв на ход (общий для контекста и L1). **Оценка: соответствует §ADD-TR.2** («явная ссылка… когда она однозначно разрешима», «не выдумывать изображение при отсутствии однозначной цели»); это осознанное консервативное решение. Риски (приняты, без блокера): изображение старше 30 мин → маркера нет (уточнение вместо «угаданной» цели — консервативно); единственный sticker в окне может стать целью для «что на картинке?» (реестр MCA-19 считает sticker ассетом; writer видит реальный ref); при vision OFF реестр пуст → резолв честно пуст. Тесты: 11 кейсов (однозначно/документ/два/альбом/нет активов/текущее исключено/без vision-intent/own-media/reply/no-db-error/fail-open).

## 4. Не сломано — подтверждено тестами
Порядок 0g→0i→0h: «чекап» в подписи консьюмится канон-хендлером раньше Direct, без двойной обработки (`test_canonical_checkup_caption_priority_over_direct` + suite факт-чека). Master-флаг модуля на caption (`test_module_flag_off_photo_caption_unhandled`). Forward без обращения не перехвачен (`test_forwarded_photo_caption_without_addressing_unhandled`). Cooldown/ACL не тронуты (дифф их не касается; UNHANDLED-пропагация сохранена). Fast-Track «нарисуй» в подписи доходит до image-контура (`test_caption_reaches_image_route_query`). Медиагруппы/меншены/@-fallback/бот-само-сообщения — отдельные кейсы, зелёные.

## 5. Числа
Мой перепрогон: новый файл **44 passed** ✓. Наборы лейна «green-core 489» и «green-direct-cluster 669» **буквально не сверяемы**: команды в evidence не записаны (только итоги), однозначно восстановить состав невозможно (10+ подмножеств дают 669). Мои перепрогоны прямых семейств: 13 `test_direct*.py` — **446 passed**, расширенный кластер (+asap7_direct_l1 +wc_direct_d03/d04/matrix +новый файл) — **585 passed**; 0 failed. Это minor evidence-gap (нет команд в логах) — рекомендую лейну дополнить evidence командными строками; на acceptance не влияет.

## 6. Дисциплина
Периметр лейна = ровно 5 файлов + `evidence/entry-fix/**`; стабы — паритет сигнатур (1 строка, ассерты не тронуты — diff проверен). `web/*` этим лейном не тронут: `web/static/app.css` — заявленный файл параллельного лейна ADTR-GRID (`evidence/grid-fix/grid-fix.md` §6, blob `6c9231663725`), равно как его e2e/пины; незакоммиченные чужие правки не смешивались. Мой коммит — только этот вердикт.

## Леджеру (рекомендация)
- `M-ADTR-ENTRY-EVENT` / `-TRIGGERS` / `-HANDLER` / `-REFS`: **код-часть → VERIFIED** по коммиту лейна (кандидат с этими blob12); **live-часть → READY_FOR_LIVE (postdeploy)**: реальный Direct в Telegram по сценариям §ADD-TR.5 строки 1–4 (photo+caption→ответ; reply-сценарии; запрос без цели→штатное уточнение; «нарисуй» в подписи→картинка) — агентские/owner-optional проверки после деплоя, не владельческий гейт (PET).
- `M-ADTR-ENTRY-SEMANTIC`: доставка события/подписи до семантических контуров — подтверждена; исполнение свободной семантики — существующие контуры (L1 §5.10 / vision intent) → живой остаток (postdeploy); консервативно не закрывать полностью.
- Риск-интерпретация (C) — см. §3 (принята; живая проверка S4-сценария входит в postdeploy-набор).

## Вердикт
**Approved.** RED→GREEN воспроизведён, семантика §ADD-TR.2 подтверждена кодом/тестами, приоритеты и запреты не нарушены. Единственное замечание — незафиксированные команды наборов 489/669 (minor, не блокирует).
