# REV-TR-FIX2 — вердикт (reply-ref + фактчек-claim; живая приёмка 2.58.91)

Независимое ревью. Read-only (V-FIX2-файлы не тронуты); этот коммит — только данный документ.

**Кандидат (uncommitted поверх `aea59748` = HEAD):** `services/direct_chat_service.py` blob12 `6de9b0d1ef39`; `services/direct_execution.py` `c4b48bcb14c9`; `services/tool_router.py` `7eb2a253d5c3`; `services/temporal_factcheck.py` `dba596979239`; новый `tests/test_tr_fix2_reply_ref.py` `005f77983cc0` (8 тестов). Хеши сверены в дереве и в изолированном worktree; дифф = +103/−5 в 4 сервисах + новый тест.

## 1. reply-ref — подтверждено; RED→GREEN воспроизведён
Код: медиа-цель хода разрешается **один раз** в `direct_chat_service` (своё медиа → текущее сообщение; иначе reply-медиа → `reply_to_message`, тот же приоритет, что у канонических маркеров) и кладётся в `ToolContext.media_target_message_id`; деривация `image_understanding` (`direct_execution`) и fallback `_recognize_image` (`tool_router`) используют её. В reply-пути нет опоры на `message.message_id` (он остаётся только паритетным дефолтом «нет reply → текущее»). Мой прогон в изолированном worktree: **RED 8/8 на `aea59748`** (включая `assert 999 == 700` и `assert 1000 == 700`), **GREEN 8/8** после патча; три кейса на месте: харнесс-точный id ответа, свежий id, двухходовый «своё фото(640)→ответ→reply на другое фото(700)» (ассерт `[OTHER, PHOTO]`, не «последнее медиа»).

## 2. CFG-06 claim — подтверждено
`ToolContext.reply_source_message_id/_text` (заполняет `direct_chat_service`); `temporal_factcheck.is_referential_claim()` — референтные формы («это правда?», «проверь его слова», «не врёт?») с границами: длина ≤80 и `\bчто\b` → False (собственный claim «правда ли, что …» не затирается; «как работает фактчек?» → False). Деривация и `ToolRouter._fact_check` берут claim=текст replied (bounded 300, как в деривации), target=envelope=replied-сообщение (при `target_msg is None или ==триггер`). Тест с зарегистрированным replied: `ready`, `claim==CLAIM`, durable `target_tg_message_id==replied` — проверено и прогоном (8/8).

## 3. L1 cold start — отложение приемлемо
Код не менялся (подтверждено диффом). Backlog-док: корень — внешний холодный HTTP-путь провайдера/сети (15.0 с = таймаут на границе; медленным был весь первый LLM-трафик процесса); варианты (warmup/keep-warm, +таймаут, retry, dedicated-слот) разобраны с трейд-оффами; дана дешёвая диагностика для следующей приёмки. Правка соразмерно не обоснована; owner-выбор по затратам — только если повторится (WAITING_EXTERNAL/backlog, не гейт).

## 4. Числа — воспроизведены с честной поправкой
- Новый файл: RED **8/8** на базе, GREEN **8/8** — совпало.
- Affected sweep (142 файла; в изолированном worktree): patched **4056 passed / 5 failed**; на **чистой базе** (без патча, без нового файла) — **4048 passed / те же 5 failed**. Итог: **все 5 падений pre-existing** (2 миграционных v35-пина + 2 `send_rich_message` + 1 summary-publish; 3 «лишних» дополнительно подтверждены изолированным прогоном на базе), кандидат новых падений не даёт (разница 4048→4056 = ровно +8 новых тестов). Нюанс: в отчёте лейна «4059/2» — те же pre-existing, но 3 из них там не всплыли (среда/порядок); существо подтверждено, не блокер. Транзиенты (routes-пины V-FIX2-WIP, init-arch флейк) — не этого лейна.

## 5. Дисциплина
Периметр TR-FIX2 = ровно 4 сервиса + 1 новый тест; `services/mca_vision.py` (+287) и `web/api/routes.py` (+27) — WIP параллельного V-FIX2 (backfill/sweep), этим лейном не тронуты; мой коммит — только этот вердикт.

## Леджеру (рекомендация)
- `ADTR-ENTRY-REFS`: **живая поправка** — live-провал (reply-на-фото давал target=сообщение-ответ) закрыт фиксом `6de9b0d1ef39`; пере-верификация — в повторной живой приёмке (tool-args `recognize_image target` = id фото из reply; own-media ход — паритет).
- `ADTR-TOOLS-FACTCHECK`: **код → VERIFIED** (claim/target reply-фактчека; границы детектора), **live → READY_FOR_LIVE** (повторная приёмка: «бот, это правда?» → claim=replied, target=replied, `ready`).
- L1 cold-start — **backlog-строка** (диагностика в следующей приёмке; код не менялся).

## Вердикт
**Approved.** Обе продуктовые первопричины (3/5) закрыты точечно и воспроизводимо; границы (детектор, паритеты) соблюдены; отложение L1 cold-start обосновано; блокеров нет.
