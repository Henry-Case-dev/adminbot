# Отчёт @Reviewer — раунд 10.24, F19 `media-transcribe-tool-round1024` (шаг 5)

> Коммит: `ad5078e`. Метод: прочитаны `spec.md`, `ADR-1024-20.md`, `tasks.md`,
> `plans/features/round1024-upd4-architecture.md` §3.5/§7, `ADR-1024-15.md` §2.1/§2.3,
> `plans/current_task.md` UPD5 (стр. 403); `git show ad5078e --stat`,
> `git diff ad5078e^ ad5078e`; сверка кода `services/tool_schemas.py`,
> `services/tool_router.py`, `services/native_media.py`, `handlers/youtube.py`,
> `handlers/voice_transcription.py`, `handlers/video_download.py`,
> `config/settings.py`, `plans/docs/canon/architecture.md`; прогон
> `.venv/Scripts/python.exe -m pytest -q`.
> R17/R18: значения `.env`/токенов/`file_id`/URL не цитируются; только `chat_id`,
> классы исключений и координаты кода.

## Статус

**Changes Requested**

Функционально фича собрана: канон R9 честно доведён до **10** (`transcribe_video`
10-м, первые 9 — байт-в-байт), команда «транскрипт» принудительно повторяет STT
ГС/кружка, YouTube/любое видео отдаёт сырой транскрипт курсивом, temp чистится в
`finally`, egress/`parse_mode`/DDL/каталог/порядок роутеров не тронуты, полный
pytest — **7768 passed, 0 failed**, `git diff --check` чист. Однако **заявленный
инвариант идемпотентности памяти выполнен эвристикой, которая ломается на
роликах/ГС с подписью (caption)**: `memorize_facts` молча пропускается при
**первом** форс-повторе, если строка в БД несёт не расшифровку, а текст подписи.
Плюс есть неоттестированная «мёртвая» ветка доставки и мелкие расхождения
kill-switch со спекой. В таком виде это не «done», а «почти done».

## Findings по severity

### Critical — нет

### High — нет

### Medium

**[Severity: Medium]**
File: `handlers/voice_transcription.py`
Location: `_PLACEHOLDER_TEXTS` 138–141, `_row_has_transcript` 144–166,
`_inject_memory` 178–179 и 189–194
Problem: защита «не дублировать GraphRAG-факт» построена на признаке
«`smart_messages.text` непустой и не из списка плейсхолдеров». Но observer
(`handlers/summary.py:168-204`) пишет в `text` **подпись медиа** (`message.text
or message.caption`), а не только пусто/плейсхолдер. Для голосового/кружка с
подписью (`[voice]` + `caption`) строка ДО авто-транскрибации = подпись →
`_row_has_transcript` возвращает `True`. Если авто-транскрибация не сработала
(ровно тот сценарий, ради которого фича и делалась), первый форс-повтор
«транскрипт» обновит `smart_messages.text` реальным транскриптом, но
`memorize_facts` **не вызовет** — новый текст не попадёт в GraphRAG, а
`R7`-митигация спеки (§7) не сработает. Дополнительно `_PLACEHOLDER_TEXTS`
содержит `"[кружок]"`, которого в словаре `_MEDIA_DESCRIPTIONS`
(`services/summary_xml.py:21-30`; `video_note` → `"video"`) нет — «защита»
путает реальный плейсхолдер и подпись.
Why it matters: тихая деградация памяти — владелец явно просил повтор, «если
авто не сделал», и ожидает, что текст попадёт в память; вместо этого факт
потерян без ошибки в логах. Регресс невидим для тестов, т.к. тест (b) берёт
`row={"text": "[голосовое]"}` — в бою такой строки нет (без подписи там пусто,
с подписью — подпись).
Required fix: считать строку «уже расшифрованной» **только если** текст не
пуст, не входит в плейсхолдеры **и не совпадает с подписью исходного
медиа-сообщения** (`getattr(media_message, "caption", None)`/`text`). Передавать
подпись в `_row_has_transcript`/`_inject_memory`; добавить тест
`force_repeat` на ГС с `caption` (ожидание: `memorize_facts` вызван один раз) и
тест на повтор уже расшифрованного ГС с подписью (ожидание: не вызван).

### Low

**[Severity: Low]**
File: `handlers/voice_transcription.py`
Location: `_reply_media` 216–232 (ветка `bot.send_message` 229–232)
Problem: ветка «иное → `bot.send_message`» недостижима: оба вызова
`transcribe_media_message` передают `reply_to_id`, равный `message_id` самого
медиа (`_process:349-350`, `force_repeat_from_reply:341-343`), поэтому всегда
исполняется `media_message.reply`. Ветка не покрыта ни одним тестом — это
неоттестированный код на пути доставки (и потенциально новая egress-точка, если
её когда-то начнут использовать).
Why it matters: мёртвый/непокрытый путь на критичном для R16/egress слое; при
будущем вызове с иным `reply_to_id` поведение никак не проверено.
Required fix: либо удалить параметр `reply_to_id` и ветку `bot.send_message`
(упростить до `media_message.reply`), либо оставить и добавить тест с
`reply_to_id != media_message.message_id`, фиксирующий `bot.send_message` +
`reply_to_message_id`.

**[Severity: Low]**
File: `handlers/voice_transcription.py` / `handlers/youtube.py`
Location: `force_repeat_from_reply` 331–336 vs `_resolve_voice_media` 403–422
Problem: классификация выбирает цель «своё сообщение приоритетнее реплая», а
исполнение (`force_repeat_from_reply`) — «реплай приоритетнее своего». Для
edge-кейса «ГС с подписью, который сам является реплаем на другой ГС» эти два
пути разойдутся: классификация квалифицирует своё медиа, а транскрибироваться
будет медиа реплая.
Why it matters: рассинхрон приоритета источника между классификацией и
исполнением — источник будущих багов и путаницы при поддержке.
Required fix: вынести выбор целевого медиа в один общий хелпер и использовать
его и в `_resolve_voice_media`, и в `force_repeat_from_reply` (один порядок).

**[Severity: Low]**
File: `handlers/youtube.py`
Location: `youtube_handler` 1277–1282, `_handle_voice_command` 431–450
Problem: в OFF-состоянии kill-switch `MEDIA_TRANSCRIBE_TOOL_ENABLED=false`
спеке §9 обещан «прежний нейтральный ответ». Фактически запрос теперь
классифицируется как `kind="voice"` и проходит через `cooldown_touch`
(стр. 1277) до ветки `voice`; при кулдауне пользователь получит throttle-фразу
вместо нейтральной, а кулдаун будет израсходован. До F19 ветка «нет цели» звала
`_reply(COMMAND_NO_TARGET_PHRASES)` ДО кулдауна.
Why it matters: kill-switch перестаёт быть байт-в-байт откатом — обещание
спеки/ADR об откате не выполняется полностью.
Required fix: при `not _media_transcribe_enabled()` (и при недоступной цели)
обрабатывать voice-команду **до** `cooldown_refresh`/`cooldown_touch` —
как прежний `request is None` (нейтральный ответ без списания кулдауна).

**[Severity: Low]**
File: `handlers/video_download.py` / `services/native_media.py`
Location: `_native_video_media` 175–188; `AUDIO_KINDS`/`MEDIA_KINDS`
`services/native_media.py:34-39`; `services/tool_router.py:109-111`
Problem: спека §5 прямо относит `handlers/video_download.py` в «**не трогаются
F19**», но коммит его меняет (добавлен фильтр `VIDEO_KINDS`). Правка
**обоснована** (без неё после аддитивного расширения
`resolve_reply_video` Fast-Track «скачай» по реплаю на ГС скачивал бы голос) и
покрыта существующим тестом `tests/test_video_download.py:2249-2274` — это не
регресс. Но расхождение кода и спеки не закрыто документально; вдобавок
`AUDIO_KINDS`/`MEDIA_KINDS` объявлены, но нигде не используются (дублируют
`_NATIVE_TRANSCRIBE_KINDS` в `tool_router`).
Why it matters: спека/tasks вводят в заблуждение следующего исполнителя
(«файл не трогать» — а он тронут); мёртвые константы провоцируют дрейф набора
kind-ов между `native_media` и `tool_router`.
Required fix: внести `handlers/video_download.py` в таблицу изменений §5/§3.2
спеки и tasks как «F19 (регресс-фильтр Fast-Track)», либо вынести фильтр в
`resolve_reply_video` API; `_NATIVE_TRANSCRIBE_KINDS` заменить на
`native_media.MEDIA_KINDS` (единый источник) и либо задействовать
`AUDIO_KINDS`, либо удалить.

## Контракт: чекбоксы

- [x] **Канон:** `TOOL_CALLING_TOOLS == 10`; `transcribe_video` — 10-й, в конец
  (`tool_schemas.py:337-348`); первые 9 имён/схем — без правок (diff правок
  первых 9 схем не содержит); `active_tools`/`factcheck_tools` не сломаны
  (`factcheck_tools` = 3, `:398-415`); комментарий-счётчик и module-docstring
  актуализированы («R9 = **10**», I2 закрыт), `docs/canon/architecture.md`
  синхронизирован (10 инструментов, `summarize_video` без `mode`).
- [x] **Definition:** EN; `transcribe_video` = «RAW verbatim … do NOT summarize»,
  `summarize_video` = «Make a SUMMARY … not the raw transcript»; `url` не
  обязателен (`required: []`), `source: enum["link","reply"]`,
  `additionalProperties: false` (`tool_schemas.py:134-199`).
- [x] **Команда «транскрипт»:** ГС/кружок — форс-повтор STT
  (`handlers/youtube.py:431-450, 1278-1282` → `voice_transcription.
  force_repeat_from_reply`); любое видео — сырой транскрипт; YouTube — голый
  субтитр курсивом (`_send_transcript_reply`, `mode=transcript` не тронут);
  temp в `finally` (`voice_transcription.py:294-299`, `tool_router.py:961-965,
  976-981`); флаг гейтит рантайм (схема/счётчик безусловны).
- [~] **Идемпотентность `memorize_facts`:** механизм есть (`force=True` +
  `_row_has_transcript`), но с Medium-дефектом на ГС/кружках с подписью —
  см. Findings.
- [x] **Инварианты:** `imported-history-immutable` (только штатный
  `UPDATE smart_messages.text`); egress-реестры не расширялись (курсив —
  существующий allowlisted путь; инструмент возвращает строку); локальный
  `parse_mode="HTML"`, глобальный `parse_mode=None` не тронут; R16/R17/R18;
  порядок роутеров `bot.py` не сдвинут.
- [x] **Δ DDL = 0** (нет правок `services/database.py`/схем); **Δ каталога = 0**
  (`MEDIA_TRANSCRIBE_TOOL_ENABLED` — env-only `ClassVar`, вне `param_catalog`,
  `config/settings.py:693-701`).
- [x] **Тесты (a)–(i):** присутствуют в `tests/test_media_transcribe_tool_
  round1024.py`; ассерты `== 9` обновлены в 7 файлах; тесты содержательны
  (проверяют STT-повтор, курсив, флаг, ошибки-строки, R17-caplog, dispatch
  link/native/voice, идемпотентность), не тавтологичны. Пробел: нет теста на
  ГС с подписью (см. Medium) и на ветку `bot.send_message` (см. Low).
- [x] **Полный pytest:** `.venv/Scripts/python.exe -m pytest -q` →
  **7768 passed, 1 warning** (0 failed); `git diff --check` — чисто.

## Точный список для исправления (Changes Requested)

1. **Medium:** починить детекцию «строка уже несёт расшифровку» на
   `handlers/voice_transcription.py:144-166/178-179` (учесть подпись медиа,
   не считать её транскриптом); добавить тесты на ГС/кружок с подписью (первый
   форс-повтор → `memorize_facts` вызван; повтор после расшифровки → не вызван).
2. **Low:** решить судьбу недостижимой ветки `bot.send_message` в
   `_reply_media` (`handlers/voice_transcription.py:229-232`) — удалить или
   покрыть тестом с иным `reply_to_id`.
3. **Low:** унифицировать приоритет цели (своё vs реплай) между
   `_resolve_voice_media` (`handlers/youtube.py:403-422`) и
   `force_repeat_from_reply` (`handlers/voice_transcription.py:331-336`).
4. **Low:** при `MEDIA_TRANSCRIBE_TOOL_ENABLED=false` отдавать нейтральный
   ответ **до** списания youtube-кулдауна (`handlers/youtube.py:1277-1282`).
5. **Low:** отразить правку `handlers/video_download.py` в спеке/tasks (F19,
   регресс-фильтр Fast-Track); убрать дублирование
   `_NATIVE_TRANSCRIBE_KINDS` ↔ `native_media.MEDIA_KINDS`.

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 2 — коммит `e0da0f4` (`fix(... review iter1)`)

> Метод: `git show e0da0f4 --stat`, `git diff e0da0f4^ e0da0f4` (5 файлов:
> `handlers/voice_transcription.py`, `handlers/youtube.py`,
> `services/native_media.py`, `services/tool_router.py`,
> `tests/test_media_transcribe_tool_round1024.py`); поверх влит несвязанный
> F3 `68b7c81` (web/analytics — к F19 отношения не имеет, в анализ не включён);
> целевые тесты + полный pytest; ручная probe-проверка деградаций STT.

## Статус

**Changes Requested**

Все пять findings итерации 1 закрыты корректно (см. ниже). Но повторный аудит
вскрыл **новый Medium-дефект на командном пути форс-повтора**: при деградации
STT пользователь получает **два** ответа — корректную фразу деградации из
авто-пути И поверх неё ложную нейтральную «нет цели». Это ломает UX и
расходится со спекой §3.2.3/§3.2.6.

## Findings итерации 2 по severity

### Critical — нет

### High — нет

### Medium

**[Severity: Medium]**
File: `handlers/youtube.py` (`_handle_voice_command`, 417–436) +
`handlers/voice_transcription.py` (`transcribe_media_message` 234–321,
`force_repeat_from_reply` 323–342)
Problem: `transcribe_media_message` возвращает `False` в **двух разных
смыслах**: (а) цели/сервиса нет — сообщение НЕ отправлено; (б) транскрибация
запускалась, но деградировала — фраза **уже отправлена**
(`VT_TOO_LONG_PHRASES` 259–262, `VT_SILENCE_PHRASES` 282–287,
`VT_ALL_FAILED_PHRASES` 288–293), после чего `return False`.
`force_repeat_from_reply` просто пробрасывает этот `False`, а
`_handle_voice_command` по `not handled` отправляет **ещё одну** нейтральную
фразу `COMMAND_NO_TARGET_PHRASES`. Проверено probe-тестом
(`EmptyTranscript` и `TranscriptionUnavailable`, ГС реплаем): получено
**2 сообщения** — «…деградация…» от ASR + «нет цели»; то же для превышения
длительности.
Why it matters: пользователь, у которого ГС реально был целью, получает
противоречивый второй ответ «нет цели», хотя цель была. Прямое расхождение со
спекой: §3.2.3 — «фразы деградации … как в авто-пути» (там ровно одно
сообщение), §3.2.6 — нейтральный ответ только «голос без цели». Теста на этот
путь нет — существующие тесты проверяют только успех.
Required fix: разделить «нет цели» и «цель была, но деградация». Простейший
вариант — `force_repeat_from_reply` возвращает `True`, если цель найдена и
`transcribe_media_message` **был вызван** (деградационная фраза уже отправлена),
и `False` только когда цели нет (`media_message is None`) или `_service is None`;
не путать с исключением (его по-прежнему ловит `_handle_voice_command` →
нейтральный фолбэк). Альтернатива — вернуть тристейт («no_target» / «handled» /
«sent_ok») и в `_handle_voice_command` отдавать нейтраль только на `no_target`.
Добавить регресс-тесты: реплай на ГС с `EmptyTranscript`,
`TranscriptionUnavailable` и `duration > лимита` → **ровно один** ответ
(фраза деградации), нейтральная фраза отсутствует.

### Low (информационно, не блокирует)

**[Severity: Low]** File: `handlers/youtube.py:1247-1253`
Перенос voice-ветки до `cooldown_refresh`/`cooldown_touch` (Low 4) закрыл
OFF-фиделити, но как побочный эффект **убран youtube-кулдаун и в ON-состоянии**:
форс-повтор «транскрипт» по ГС больше не троттлится. Спека этого не требует
(R8 — accepted Low), спец-ограничения авто-пути (лимит длительности, STT-таймаут)
сохранены, поэтому не блокирую. Рекомендация: осознанно зафиксировать в
spec §9/R8 как принятое решение (либо вернуть bounded-троттлинг ON).

## Закрытие findings итерации 1 (по коду и тестам)

- [x] **Medium (подпись ≠ расшифровка):** `_row_has_transcript` принимает
  `media_caption`; пустая/плейсхолдер/подпись → `False`
  (`handlers/voice_transcription.py:144-176`); `_PLACEHOLDER_TEXTS` теперь из
  `services.summary_xml._MEDIA_DESCRIPTIONS.values()` (снят несуществующий
  `"[кружок]"`); `_inject_memory` передаёт `message.text or message.caption`
  (`:184-189`) — та же формула, что у observer (`handlers/summary.py:168`).
  Тесты: `test_caption_row_is_not_a_transcript` (подпись → memorize вызван),
  `test_caption_repeat_after_transcript_skips_memorize` (реальная расшифровка →
  не вызван), `test_caption_video_note_placeholder_still_memorizes`
  (`video_note`→«[видео]» → вызван). Содержательны, не тавтологичны.
- [x] **Low 2 (ветка `bot.send_message`):** покрыта
  `test_reply_target_id_uses_send_message` (`reply_to_id=555` ≠ `message_id`);
  проверяет `reply_to_message_id`/`parse_mode="HTML"` и отсутствие `voice.reply`.
- [x] **Low 3 (приоритет цели):** введён единый
  `native_media.voice_media_message` (своё > реплай, строгий `file_id`),
  используется и в `handlers/youtube.py:_resolve_voice_media`, и в
  `voice_transcription.force_repeat_from_reply`; локальный `_has_voice_media`
  удалён. Тест `test_own_voice_priority_over_reply` (своё ГС, реплай на другое
  ГС → транскрибируется своё, `MP4/OGG`-формат корректен).
- [x] **Low 4 (kill-switch байт-в-байт):** voice-ветка поднята ДО
  `cooldown_refresh`/`remaining`/`touch` (`handlers/youtube.py:1247-1253`);
  OFF → нейтральный ответ без списания кулдауна (прежнее поведение
  `request is None`). См. побочный эффект выше.
- [x] **Low 5 (спека/дубли):** `plans/features/media-transcribe-tool-round1024/spec.md`
  §4.6/§5 и `tasks.md` T-2345 отражают регресс-фильтр Fast-Track
  `handlers/video_download.py::_native_video_media`; `_NATIVE_VIDEO_KINDS`/
  `_NATIVE_TRANSCRIBE_KINDS` удалены, `_resolve_tool_source` использует
  `native_media.VIDEO_KINDS`/`MEDIA_KINDS` (единый источник), `AUDIO_KINDS`
  больше не мёртвая константа.

## Контракт (итерация 2)

- [x] **Канон 10:** не тронут (`e0da0f4` не правит `services/tool_schemas.py`);
  `TOOL_CALLING_TOOLS == 10`, `transcribe_video` — 10-й/в конец, первые 9
  байт-в-байт.
- [x] **Инварианты:** `imported-history-immutable` (только штатный
  `UPDATE smart_messages.text`); egress не расширен (новых send-точек нет,
  `handlers/voice_transcription.py` уже в `SEND_ALLOWLIST`; guard-тест
  `test_outgoing_guard_round1022.py` зелёный); R16/R17/R18 (в логах только
  `source`/`kind`/`out_chars`/`error=<Class>`, `voice_media_message` не логирует
  id); локальный `parse_mode="HTML"`, глобальный `parse_mode=None` не тронут;
  порядок роутеров `bot.py` не сдвинут.
- [x] **Δ DDL = 0** (`services/database.py` не тронут); **Δ каталога = 0**
  (`config/settings.py` в `e0da0f4` не тронут; правка settings — из F3).
- [x] **Тесты:** целевые (`-k "caption or TargetSelection or reply_target"` — 5
  passed; регресс Fast-Track — 1 passed). Полный pytest →
  **7776 passed, 1 warning, 0 failed**; `git diff --check` — чисто.
- [ ] **Командный путь деградации:** двойной ответ — см. Medium выше.

## Точный список для исправления (итерация 2)

1. **Medium:** убрать двойной ответ при деградации ASR на командном пути
   (`handlers/youtube.py:_handle_voice_command` + `handlers/voice_transcription.py:
   force_repeat_from_reply`/`transcribe_media_message`): нейтральная фраза —
   только когда цели/сервиса нет; после уже отправленной фразы деградации
   (`VT_TOO_LONG_PHRASES`/`VT_SILENCE_PHRASES`/`VT_ALL_FAILED_PHRASES`) — без
   второй. Добавить регресс-тесты на 3 деградации (ровно один ответ).
2. **Low (информационно):** зафиксировать в spec §9/R8 сознательный отказ от
   youtube-кулдауна на voice-команде в ON (либо вернуть bounded-троттлинг).

---

# Итерация 3 (финальная) — коммит `0587c9b` (`fix(... review iter2)`)

> Метод: `git show 0587c9b --stat`, `git diff 0587c9b^ 0587c9b` (3 файла:
> `handlers/voice_transcription.py`, `handlers/youtube.py`,
> `tests/test_media_transcribe_tool_round1024.py`); поверх влит несвязанный
> F3-ревизион `8bbd17e` (web/analytics — в анализ F19 не включён);
> целевой файл тестов + полный pytest; независимая probe-проверка деградаций
> и no-service (без опоры на тесты Builder'а).

## Статус

**Approved**

Medium итерации 2 закрыт по существу и независимо проверен: при деградации ASR
(пустой транскрипт / `TranscriptionUnavailable` / превышение длительности) — ровно
**один** ответ (фраза деградации), ложной нейтральной «нет цели» больше нет;
нейтральный ответ уходит **только** при `no_target` (нет сервиса/цели). Low
(кулдаун voice-команды) зафиксирован в `spec.md` §9 + R8 как accepted Low.
Канон 10 цел, инварианты держатся, полный pytest — **7786 passed / 0 failed**,
`git diff --check` чист. Единственное оставшееся замечание — Low (authorless-
медиа), вынесено как follow-up и приёмку не блокирует.

## Findings итерации 3 по severity

### Critical — нет

### High — нет

### Medium — нет

### Low (follow-up, не блокирует приёмку)

**[Severity: Low]**
File: `handlers/voice_transcription.py` (`transcribe_media_message`, 234–321) +
`handlers/youtube.py` (`_handle_voice_command`, 417–443)
Problem: `transcribe_media_message` возвращает `False` без отправки сообщения
ещё в двух ранних ветках — `user is None` (стр. 244–246, медиа из канала/поста
без автора) и `user.id == _bot_id` (медиа самого бота). `force_repeat_from_reply`
маппит любой `False`, кроме `no_target`, в `FORCE_REPEAT_HANDLED`
(стр. 351–354), поэтому на такие медиа командный путь теперь молчит:
probe подтвердил `n_reply=0, n_send=0` при реплае «транскрипт» на голосовое без
`from_user` (до этого фикса уходил нейтральный ответ). Ветка `media is None`
недостижима (цель уже провалидирована `voice_media_message`), `_service is None`
перехватывается в `force_repeat_from_reply` → `no_target`.
Why it matters: узкий класс входных данных (медиа без автора: посты канала,
форварды канала, голос бота) — явная команда остаётся без ответа. Инварианты
R16/17/18 не нарушены (R16 — аддитивность API; авто-путь 0i такие медиа и
раньше не транскрибировал, атрибуция автора невозможна), поэтому не блокирую.
Required fix (follow-up): отличать «цель найдена, но ответ не отправлен» от
«деградация отправлена» — например, тристейт и у `transcribe_media_message`
(`sent_ok` / `degraded_sent` / `nothing_sent`), и маппить `nothing_sent` в
`no_target`, чтобы вызывающий отдал нейтральный фолбэк («нет тишины»).
Тест: реплай «транскрипт» на `voice` с `from_user=None` → ровно один
нейтральный ответ.

## Закрытие Medium/Low итерации 2

- [x] **Medium (двойной ответ при деградации):** введён тристейт
  `FORCE_REPEAT_NO_TARGET` / `FORCE_REPEAT_HANDLED` / `FORCE_REPEAT_SENT_OK`
  (`handlers/voice_transcription.py:327-329,332-354`);
  `_handle_voice_command` шлёт нейтраль **только** при `no_target`
  (`handlers/youtube.py:427-441`); исключение по-прежнему → нейтральный фолбэк
  (`:430-435`). Независимая probe: silence / all-failed / too-long / ok →
  `voice.reply=1`, `bot.send_message=0`; `_service=None` → нейтраль
  (`bot.send_message=1`). Тесты Builder'а
  `TestDegradationSingleAnswer` (4 шт.) содержательны, не тавтологичны.
- [x] **Low (кулдаун voice-команды):** зафиксировано в
  `plans/features/media-transcribe-tool-round1024/spec.md` §9 (стр. 287) и R8
  (стр. 264): voice-команда обрабатывается до кулдауна и в ON не троттлится;
  ограничители — явность команды, лимит длительности, STT-таймаут. Accepted Low.

## Контракт (итерация 3)

- [x] **Канон 10:** `0587c9b` не правит `services/tool_schemas.py` /
  `services/tool_router.py`; `TOOL_CALLING_TOOLS == 10`, `transcribe_video` —
  10-й/в конец, первые 9 байт-в-байт.
- [x] **Инварианты:** `imported-history-immutable` (только штатный
  `UPDATE smart_messages.text`); egress не расширен (новых send-точек нет,
  модуль в `SEND_ALLOWLIST`; guard-тест `test_outgoing_guard_round1022.py`
  зелёный); R16 (изменение возврата `force_repeat_from_reply` — внутренний
  контракт, публичные API не тронуты) / R17 (новых чувствительных логов нет) /
  R18; локальный `parse_mode="HTML"`, глобальный `parse_mode=None` не тронут;
  порядок роутеров `bot.py` не сдвинут.
- [x] **Δ DDL = 0** (`services/database.py` не тронут); **Δ каталога = 0**
  (`config/settings.py` в `0587c9b` не тронут).
- [x] **Тесты:** целевой файл `tests/test_media_transcribe_tool_round1024.py` —
  **31 passed**; полный pytest → **7786 passed, 1 warning, 0 failed**;
  `git diff --check` — чисто.
- [x] **Независимая probe** (Medium): деградации/успех → ровно один ответ,
  нейтраль только при отсутствии сервиса.

## Вердикт

**Approved.** Medium итерации 2 закрыт, все findings итераций 1–2 закрыты,
канон/инварианты в силе, тесты зелёные. Открытый Low (authorless-медиа) —
follow-up вне блокирующего scope. @Orchestrator: можно двигаться дальше
(T-2351 закрыт, далее T-2352 @DevOps).
