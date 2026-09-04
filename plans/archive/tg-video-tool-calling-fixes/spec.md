# TG-видео (нативные файлы) + хардненинг скачивания + Tool Calling: промпт/count

Bugfix-раунд 04.09.2026, 3 части (T-667…T-685, продолжает T-666). Ссылки: `plans/features/tg-video-tool-calling-fixes/tasks.md`, живой план `plans/docs/memory-project-overview.md`, образец формата — `plans/archive/multimodal-summarization-tools-reactions-ui/spec.md`. Проверено на локальном master e3e7fd5 (3447 passed); незакоммичен только `plans/docs/memory-project-overview.md`.

## 1. Обзор (Overview)

Три блока дефектов, найденных после эпика 04.09 (ae9b4f8..e3e7fd5):

**ПРОБЛЕМА 1 — TG-видео не транскрибируются.** Триггеры «транскрипт/че за видос/о чем видео/поясни за видос/перескажи видос/че в видосе» (`handlers/youtube.py:47-50`, substring-матч) живут в роутере 0e, но `_parse` (:85-107) требует YouTube-URL в text/caption/reply — без URL возвращает `(None, None)` → UNHANDLED. Обычные видео (`message.video`), видео-документы (`message.document` c mime `video/*`) и репосты видео (forward: `message.video` + `forward_origin`) НИГДЕ не транскрибируются: единственный медиа-хендлер — `F.voice | F.video_note` (`handlers/voice_transcription.py:337`). Публичных URL у TG-файлов нет (локальный Bot API 127.0.0.1:8081, наружу только 22/443), ffmpeg в проекте нет — значит «видео» для STT это **файл в tmp → существующий каскад VoiceTranscriber** (Groq whisper upload принимает mp4-контейнер как есть; OpenRouter — `input_audio` с форматом m4a для mp4, уже работает для video_note).

**ПРОБЛЕМА 1b — маршрутизация скачивания.** `tools/video_downloader.py::is_direct_media_url` (:169-179) считает «прямой медиа-ссылкой» ЛЮБОЙ http(s)-URL, чей путь оканчивается `.mp4|webm|mov|mkv|avi|gif` — включая теоретические CDN/редиректные ссылки YouTube/TikTok/VK и т.п., где прямой стрим отдаст HTML/403/бесконечный редирект. В direct-ветке `handlers/video_download.py:199-244` нет `cooldown_touch` (баг против :264, D279-семантика). Реплай «скачай» на чужое видео-сообщение/документ не разбирается (ветка 186-196 смотрит только на медиа самого вызова; `reply_target` игнорируется) → юзер получает `VD_NO_LINK_PHRASES` вместо пересылки (`_handle_native_media`, :486-518, работает и ждёт вызова).

**ПРОБЛЕМА 2 — direct_chat Tool Calling не срабатывает на счётные вопросы.** `CHAT_SYSTEM_PROMPT` (`services/chat_prompts.py:3-14`) не упоминает инструменты; прод-значение `prompts.direct_chat_system_prompt` засижено из старого канона (`param_catalog.py:240-241`, `ON CONFLICT DO NOTHING`) — смена текста в коде прод НЕ обновит. Description'ы `tool_schemas.py` не покрывают счётные вопросы («сколько раз», «когда упоминали»). `query_chat_memory` (`tool_router.py:132-167`) отдаёт только сниппеты top-40 (без счётчика и диапазона дат) — модель физически не может ответить «N раз» точно. `tool_loop.py:37-49` при `LLMError` на 1-м раунде тихо деградирует в обычный ответ.

### Сценарии пользователя

- Кидаешь видео-файл (или репост видео) и пишешь/реплаишь «транскрипт» → бот присылает расшифровку; «че за видос / о чем видео / поясни за видос / перескажи видос / че в видосе» → едкая выжимка по расшифровке.
- Реплаишь «скачай» на видео-сообщение/видео-документ → бот пересылает файл; «скачай https://…mp4» → прямой стрим (остаётся), при этом честно работает кулдаун; «скачай <ссылка на TikTok/YouTube, даже оканчивающаяся .mp4>» → идёт в yt-dlp/cobalt, а не в прямой стрим.
- В прямом чате спрашиваешь «сколько раз за неделю упоминали бензин?» → модель вызывает `query_chat_memory` (в логах `[tools] round=… tool=query_chat_memory`), получает число + диапазон дат и отвечает точно.

### Цели фикса

1. Нативный TG-видео-путь в `handlers/youtube.py` (медиа-детекция + лимиты до скачивания + VoiceTranscriber + выдача по триггерам + память), общий хелпер скачивания медиа.
2. Хардненинг direct-стрима (список платформ-исключений), реплай «скачай» на нативные медиа, cooldown в direct-ветке.
3. Tool Calling: прод-диагностика до фикса → новый канон промпта с ИНСТРУМЕНТЫ-блоком + легаси-константа + автозамена ТОЛЬКО байт-в-байт-легаси в PG → расширенные description'ы → count/диапазон дат в `query_chat_memory`.

### Границы (НЕ ломать)

- **Порядок регистрации роутеров `bot.py` (353-457) НЕ меняется ни на строку**: 0e youtube (:373-374) → 0f web → 0g checkup → 0h direct_chat (:386-387) → 0i voice_transcription (:390-391, гейт = summary_enabled И enable_voice_transcription) → 4e video_download (:445-451, гейт download_enabled) → 5 slavik (:454) → 6 vasya (:457). Расширяется только ВНУТРЕННЯЯ логика существующих хендлеров (0e — медиа-ветка; 4e — reply-на-медиа и cooldown; 0h-сервисы — промпт/description/count).
- YouTube-URL-ветка `youtube.py` (кэш по video_id, on_retry-нотификатор, каскад L1/L2/L3, троттлинг-реплаи на вызов, фразы 5.5/5.6/5.8, 🗿) — байт-в-байт.
- Реакции: Славик/Вася/Оля/common/dead page/war_alert/goodmorning/kostik/alan — не трогаем; медиа-приоритеты внутри slavik — не трогаем.
- Кружочки/голосовые (`F.voice|F.video_note`) — остаются строго за voice_transcription 0i (включая репосты кружочков). Новая ветка 0e НЕ матчит voice/video_note.
- direct_chat: CB, throttle, per-chat lock, дедуп, memorize, бюджеты контекста, команды /clear /tone /persona /forget — не меняются.
- Поведение инструментов search/factcheck/summary/web/checkup/voice — нулевой диф (инструменты только в direct_chat).
- `APP_VERSION` не меняем. Существующие pg-ключи и env-имена не переименовываем и их значения не перезатираем (кроме явной миграции канона 3.3(б)). Секреты не коммитим (только `.env.example`).
- Полный pytest — 0 failed; `git diff --check` чист.

## 2. Требования (Requirements)

### Функциональные — Часть 1 (TG-видео)

- FR-1. Если сообщение с триггером (text или caption, substring-правило как сегодня) не содержит YouTube-URL, НО в `message` или `message.reply_to_message` есть медиа, квалифицируемое как «видео» (`message.video`; `message.document` с mime `video/*`; документ без mime/с mime `application/octet-stream`-подобным — по имени `file_name`, расширения mp4/webm/mov/mkv/avi; репосты — те же поля, aiogram даёт форвард-видео как обычный `message.video` + `forward_origin`, аналогично форвард-video_note в voice-пути) — роутер 0e перехватывает и обрабатывает как видео-файл. Voice/video_note/audio в квалификацию НЕ входят (0i не трогаем). Видео БЕЗ триггера — как раньше, пропагация жива.
- FR-2. Приоритет: если в text/caption (своём или реплая) есть YouTube-URL — работает ровно старая URL-ветка (L1/L2/L3), медиа-ветка не запускается, даже если медиа тоже есть.
- FR-3. Лимиты ДО скачивания: размер из `video.file_size`/`document.file_size` > `limits.video_transcribe_max_size_mb` (дефолт 50) → фраза-отказ, файл НЕ качается; длительность `video.duration` > `limits.video_transcribe_max_duration_seconds` (дефолт 600) → фраза-отказ, файл НЕ качается. У `document` длительности нет (TG не отдаёт) — проверяется только размер; у `video` duration обязателен (int), при отсутствии/0 — не блокируем.
- FR-4. Скачивание — общий хелпер `fetch_media_to_tmp` (services/media_download.py), единый для voice и видео: локальный режим (`flags.download_enabled`) = get_file + копия с диска `TELEGRAM_API_FILES_DIR/<bot_id>:<token>/<file_path>` retry×3 + fallback `bot.download`; облако = `bot.download`. Tmp-уборка в `finally` на 100% путей.
- FR-5. Транскрибация: файл → существующий `VoiceTranscriber.transcribe_voice(path, audio_format)` (каскад Groq→OpenRouter, тот же путь, что у video_note: Groq — upload mp4 как есть; OpenRouter — `input_audio`, формат по расширению `.mp4 → m4a`). Ошибки каскада — `TranscriptionUnavailable`/`EmptyTranscript` из `SmartModule.service`.
- FR-6. Выдача: триггер «транскрипт» (substring) → сырой текст расшифровки чанками (≤4096, `send_chunked_reply`, plain, первая часть реплаем на медиа/вызов); остальные триггеры → LLM-выжимка существующим каноном `prompts.youtube_system_prompt` (НЕ новый промпт: расшифровка файла — это текст, канон «по предоставленной текстовой расшифровке» семантически точен; `{max_symbols}` — .replace; контекст — `<transcript>` с жёстким срезом `[:max_symbols]`, прецедент truncation движка субтитров), RAG-префикс как в L3. Пустой ответ LLM → 🗿-молчание (существующая ветка `LLMBadResponseError`).
- FR-7. Память: после успеха — двойная инъекция как у voice: `update_smart_message_text(chat_id, message.message_id, text)` (строка-плейсхолдер сообщения → расшифровка, становится FTS-искомой) + `memorize_facts` с обёрткой `wrap_media_fact(type='video', …)` (у форвардов — `forwarded/forward_from`), `source_type="video_transcript"`. Сбои памяти — WARNING, не роняют ответ.
- FR-8. Graceful degradation: STT-каскад упал/пусто → вежливые фразы из новых пулов (без трейсбеков юзеру, WARNING-логи, поток жив); битый/обрезанный файл, сетевые сбои скачивания → фраза; медиа-детекция упала с исключением → `UNHANDLED` (не ронять чужие роутеры).
- FR-9. Новые горячие ключи `limits.video_transcribe_max_size_mb`, `limits.video_transcribe_max_duration_seconds` (категория limits, группа `limits_media`) + Settings/env-фолбеки; ПЕРЕД фиксацией дефолтов Builder проверяет фактические лимиты Groq (whisper upload) и OpenRouter (`input_audio`) и при необходимости корректирует дефолты/README (см. 6).
- FR-10. Кэш: медиа-ветка НЕ пишет в smart_cache (у файла нет стабильного «канонического» ключа; кулдаун youtube-роутера уже ограничивает частоту). Кулдаун — общий с youtube (cooldown_touch до обработки, как в URL-ветке).

### Функциональные — Часть 1b (скачивание)

- FR-11. `is_direct_media_url` возвращает False для «известных платформ» по hostname (схема/домен + поддомены), даже если путь оканчивается `.mp4|webm|mov|mkv|avi|gif` и даже с query/фрагментом после расширения. Список платформ (сопоставление суффиксов домена с dot-границей): `youtube.com`, `youtu.be`, `tiktok.com`, `instagram.com`, `facebook.com`, `fb.watch`, `vk.com`, `twitter.com`, `x.com`, `rutube.ru`, `vimeo.com`, `ok.ru`, `twitch.tv`, `kick.com`, `dzen.ru`, `vine.co`, `reddit.com` (+ любые поддомены). Такие URL уходят в прежние ветки: YouTube → yt-dlp (гейт `flags.ytdlp_for_youtube`), остальные → cobalt.
- FR-12. Реплай «скачай/загрузи/…» (триггер в начале строки вызова) на сообщение с `video`/`document` (mime video/* или имя-расширение, репосты — те же поля) без ссылок → `_handle_native_media` по медиа реплая (а не `VD_NO_LINK_PHRASES`); собственное медиа вызова — как раньше, приоритет за ним; приоритет ссылок (`_extract_urls`) не меняется.
- FR-13. `cooldown_touch` в direct-ветке (одиночная прямая ссылка): touch после успешного старта скачивания (после `reporter.start`, до/вокруг `download_direct`), не в except-ветках; refresh/remaining-проверка остаётся как есть; семантика «fail не жжёт кулдаун» — для провала ДО старта (неверный URL, отказ до начала стрима — исключения глотает except без touch).
- FR-14. Честные прямые ссылки стримом — ОСТАЮТСЯ (прод-хотфикс, намеренная фича): документируется в README (@DevOps) и отчёте; код не меняется (кроме хардненинга FR-11).

### Функциональные — Часть 2 (Tool Calling)

- FR-15. Прод-диагностика ДО фикса (этап Builder, T-678): проверить реальную причину «инструменты не вызываются» по маркерам прод-логов (см. 3.3(а)); результат — в spec-дополнение/отчёт PM до D2-D4.
- FR-16. Новый канон `CHAT_SYSTEM_PROMPT` (полный текст в 3.3(б)): токсичный стиль, «ленивая печать», лимит 1-2 предложений сохранены; добавлен блок ИНСТРУМЕНТЫ (query_chat_memory для истории/упоминаний/статистики, execute_web_search для свежих данных; «вызвал — отвечай по результату, цифры не выдумывай»). Старый канон сохраняется в коде как `LEGACY_CHAT_SYSTEM_PROMPT`.
- FR-17. Миграция прод-значения `prompts.direct_chat_system_prompt` при старте: текущее значение == `LEGACY_CHAT_SYSTEM_PROMPT` (байт-в-байт) → upsert новым каноном; кастом юзера (≠ легаси) — НЕ трогать; ключа нет в PG — ничего не делать (сид `ON CONFLICT DO NOTHING` уже вставил новый канон при `pg_db.init()`); PG недоступен — skip с логом. Сид-строку `param_catalog.py:240-241` и его code_source НЕ менять.
- FR-18. Description'ы `tool_schemas.py` расширяются (полные тексты в 3.3(в)): `query_chat_memory` — счёт/статистика/«когда», подсказка «про прошлое чата — сначала память»; `execute_web_search` — свежие/внешние/проверка. Имена инструментов, параметры, enum `time_range`, required — НЕ меняются (канон 3.3 эпика 04.09).
- FR-19. `query_chat_memory` возвращает модели: счётчик совпадений (FTS по `smart_messages`), диапазон дат первого/последнего совпадения, сниппеты (как сейчас, лимит 3500 символов суммарно). Новые DB/`MemoryManager`-методы — аккуратные дополнения (не трогая существующие сигнатуры), см. 3.3(г).
- FR-20. Логирование: INFO на каждый исполненный tool_call уже есть (`tool_loop.py:81` `[tools] round=… tool=…`); добавить INFO в `_query_chat_memory` со статистикой (count) и сохранить WARNING-деградацию `tool_loop.py:44-48`.

### Нефункциональные

- NFR-1. Юзер не видит промежуточных ошибок (STT-каскад, скачивание, DB/vector-память, count-ошибки) — только итог или существующие фразы/молчание.
- NFR-2. Совместимость: pg-ключи/env существующих параметров не меняются; 2 новых Settings-поля — парой с записями REGISTRY (тест полноты `test_param_catalog.py` остаётся зелёным после обновления ожиданий counts).
- NFR-3. Безопасность размера: видео-ветка не скачивает больше `video_transcribe_max_size_mb` (проверка ДО скачивания по file_size); direct-стрим — прежние `_DIRECT_MAX_BYTES`/`VD_MAX_BYTES`; нативные медиа не качаются повторно через сеть в обход локального диска.
- NFR-4. Таймауты: скачивание TG-медиа — под `asyncio.wait_for` (бюджет 180с на fetch+транскрибацию-каскад уже сам ограничен таймаутами стратегий; fetch-этап — 120с); суммарно видео-ветка не «висит» дольше ~5 минут (каскад STT ≤ ~60с типично + LLM-выжимка с собственными таймаутами LLMClient).
- NFR-5. Порядок регистрации `bot.py` (353-457) — без изменений (диф-проверка); полный pytest — 0 failed; `git diff --check` чист.
- NFR-6. Секреты не логируются (R17): `<bot_id>:<token>` — только как `_local_files_subdir` без логирования; новые значения — не секреты.
- NFR-7. Фразы-пулы видео не пересекаются с существующими (правило канона; проверка в тестах).

## 3. Технический дизайн

### 3.0 Настройки и REGISTRY (обе новые записи — категория limits)

`config/settings.py` (рядом с `VOICE_MAX_DURATION_SECONDS`, `config/settings.py:723-726`, в существующем блоке транскрибации):

```python
# ── Расшифровка нативных TG-видео (04.09.2026, Часть 1) ──
# Мягкие дефолты; перед деплоем Builder сверяет фактические лимиты
# Groq whisper upload / OpenRouter input_audio (см. Открытые вопросы).
VIDEO_TRANSCRIBE_MAX_SIZE_MB: int = _env_int("VIDEO_TRANSCRIBE_MAX_SIZE_MB", 50)
VIDEO_TRANSCRIBE_MAX_DURATION_SECONDS: int = _env_int(
    "VIDEO_TRANSCRIBE_MAX_DURATION_SECONDS", 600)
```

`services/param_catalog.py` `_LIMITS` (формат строк `(field, title, type, group, desc)`, рядом с `VOICE_MAX_DURATION_SECONDS`, :725-726, группа `limits_media` уже существует — новых групп/вкладок НЕ добавляем):

| settings_field | pg_key | env | type | group | title_ru / description |
|---|---|---|---|---|---|
| `VIDEO_TRANSCRIBE_MAX_SIZE_MB` | `limits.video_transcribe_max_size_mb` | VIDEO_TRANSCRIBE_MAX_SIZE_MB | int | `limits_media` | «Макс. размер видео для расшифровки, МБ» / «Видео больше этого размера по командам „транскрипт/че за видос/…” не расшифровывается. Проверяется по file_size ДО скачивания.» |
| `VIDEO_TRANSCRIBE_MAX_DURATION_SECONDS` | `limits.video_transcribe_max_duration_seconds` | VIDEO_TRANSCRIBE_MAX_DURATION_SECONDS | int | `limits_media` | «Макс. длительность видео для расшифровки, сек» / «Видео длиннее не расшифровывается. Telegram отдаёт длительность для видео-сообщений; у документов проверки длительности нет.» |

Сид — автоматический через `pg_db._seed_settings`/ConfigCache belt-and-suspenders (`ON CONFLICT DO NOTHING`), ручных строк не нужно. Обновить тесты counts (см. 6). `.env.example`: +2 строки с комментариями.

### 3.1 Часть 1 — нативное TG-видео в `handlers/youtube.py`

#### 3.1.1 Медиа-детекция (расширение, `_parse` НЕ меняется)

`_parse` (:85-107) и URL-ветка — байт-в-байт (FR-2, регресс тестов `_parse`). Новый модуль-хелпер в том же файле:

```python
_VIDEO_DOC_EXTENSIONS = ("mp4", "webm", "mov", "mkv", "avi")   # для document БЕЗ mime

@dataclasses.dataclass(frozen=True)
class _VideoMedia:
    source: types.Message      # сообщение, НА котором медиа (сам вызов или reply_target)
    media: object              # Video | Document (file_id/file_size/mime_type/...)
    kind: str                  # "video" | "document"

def _document_is_video(doc) -> bool:
    """Document → видео: mime video/*; mime пуст/None → расширение file_name;
    mime задан и не video/* → НЕ видео (mime авторитетнее имени)."""
    mime = str(getattr(doc, "mime_type", "") or "").strip().lower()
    if mime:
        return mime.startswith("video/")
    name = str(getattr(doc, "file_name", "") or "").lower()
    return any(name.endswith("." + ext) for ext in _VIDEO_DOC_EXTENSIONS)

def _resolve_video_media(message: types.Message) -> _VideoMedia | None:
    """Триггер есть (substring, тот же _has_trigger) + НЕТ YouTube-URL (по
    _parse это уже гарантировано вызывающим) + медиа «видео» на message ИЛИ
    reply_to_message → _VideoMedia. ВАЖНО: voice/video_note/audio НИКОГДА не
    квалифицируются (0i их обслуживает). Собственное медиа вызова
    приоритетнее медиа реплая. Любое исключение → None (не ронять роутер)."""
```

Вызов из `youtube_handler` (:114-116): `if target is None: media = _resolve_video_media(message); if media is None: return UNHANDLED; …ветка ниже…`. То есть порядок проверок:

1. `_parse` нашёл URL-путь → старый код целиком.
2. Иначе, если `_resolve_video_media` дал медиа → видео-ветка (консьюм: роутер 0e ответил — дальнейшая пропагация не идёт).
3. Иначе → `UNHANDLED` (как сегодня; тест «триггер без URL и без медиа → UNHANDLED» остаётся зелёным).

Случаи «текстовый вызов с YT-URL» vs «reply на видео-медиа» различаются тем, что URL-ветка проверяется ПЕРВОЙ и полностью исключает медиа-ветку; медиа-ветка смотрит только на `message.video`/`message.document` (в т.ч. форвард: aiogram кладёт вложение в те же поля, `forward_origin` при этом заполнен — прецедент voice D272/74.B). Капшен-видео с триггером в caption — обычный случай «собственное медиа + триггер в caption» (FR-1).

#### 3.1.2 Ветка обработки `_process_video_media` (в `youtube.py`)

DI: расширить модуль двумя глобалами + сеттером (URL-часть `setup_youtube` не трогаем):

```python
_media_transcriber: VoiceTranscriber | None = None   # ОБЩИЙ с voice (общий семафор D295)
_media_memory: MemoryManager | None = None
_media_db = None
_media_aliases: AliasResolver | None = None
_media_bot_id: int | None = None

def setup_youtube_video_media(transcriber, db=None, aliases=None,
                              memory=None, bot_id=None) -> None: ...
```

`bot.py` (on_startup, ВНУТРИ блока `flags.summary_enabled`, порядок регистрации роутеров НЕ трогаем): единый инстанс `VoiceTranscriber(max_concurrency=hot.get("models.groq_max_concurrency", …))` создаётся ДО `setup_youtube` (перенос строки :296-299 вверх, к блоку YouTube :229-241) и передаётся В ОБА места: `setup_youtube_video_media(voice_service, db, aliases, memory, bot.id)` и (при `enable_voice_transcription`) `setup_voice_transcription(voice_service, …)` как сегодня. Один инстанс = один общий семафор (голосовые и видео не устраивают гонку за Groq Free Tier). Лог включения VoiceTranscriber остаётся в ветке флага. Побочный эффект — ровно нулевой: при выключенном `enable_voice_transcription` инстанс просто создаётся (ключи пусты → стратегии skip), поведение voice-роутера не меняется, а видео-ветка работает независимо от voice-флага.

Псевдокод ветки (после cooldown_refresh/remaining/touch :120-127 — те же, что в URL-ветке):

```
size_mb   = hot.get("limits.video_transcribe_max_size_mb", settings.VIDEO_TRANSCRIBE_MAX_SIZE_MB)
dur_limit = hot.get("limits.video_transcribe_max_duration_seconds",
                    settings.VIDEO_TRANSCRIBE_MAX_DURATION_SECONDS)
file_size = getattr(media.media, "file_size", None)
if isinstance(file_size, int) and file_size > size_mb * 1024 * 1024:
    await _reply(bot, chat, random.choice(VIDEO_MEDIA_TOO_BIG_PHRASES), media.source.message_id)
    logger.info("[youtube] video-file too big | chat=%s bytes=%d", chat, file_size)   # consume
    return
duration = getattr(media.media, "duration", None)          # Video: int; Document: нет
if isinstance(duration, int) and duration > 0 and duration > dur_limit:
    … TOO_LONG фраза, consume …
async with typing_active(bot, chat):
    fd, path = tempfile.mkstemp(prefix="yv_", suffix=_suffix_for(media))   # .mp4/.webm/…/.ogg-нет
    os.close(fd)
    try:
        try:
            await asyncio.wait_for(fetch_media_to_tmp(bot, media.media, path), timeout=_FETCH_TIMEOUT=120.0)
        except Exception:
            logger.warning("[youtube] video-file fetch failed | chat=%s | %s", chat, type…)
            await _reply(bot, chat, random.choice(VIDEO_MEDIA_STT_UNAVAILABLE_PHRASES), …)  # consume
            return
        try:
            transcript = await _media_transcriber.transcribe_voice(path, "mp4")
        except EmptyTranscript:
            → VIDEO_MEDIA_EMPTY_PHRASES (consume)
        except TranscriptionUnavailable:
            → VIDEO_MEDIA_STT_UNAVAILABLE_PHRASES (consume)
    finally:
        os.unlink(path)   # гарантированная уборка (прецедент voice :309-314)
```

Дальше — по триггеру (решение FR-6): `want_raw = "транскрипт" in (text.lower())` — приоритет сырого транскрипта, если пользователь просил именно его (и «транскрипт» + другой триггер вместе → сырой; семантика «самый специфичный запрос»):

```
author = _resolve_author(media.source)      # форвард → источник, иначе from_user (см. 3.1.4)
if want_raw:
    label = f"{author} 🗣:"                  # plain-лейбл первой части (прецедент D268-текста)
    await send_chunked_reply(bot, chat, f"{label}\n{transcript}", media.source.message_id)
else:
    async with typing_active(bot, chat):
        text_out = await _service.summarize_transcript(   # 3.1.3
            chat_id=chat, rag_query=text, transcript=transcript)
        await send_chunked_reply(bot, chat, text_out, media.source.message_id)
await _inject_video_memory(media, author, transcript)      # 3.1.4, best-effort
logger.info("[youtube] video-file OK | chat=%s kind=%s chars=%d", chat, media.kind, len(transcript))
```

Исключения LLM-выжимки (`LLMBadResponseError` → 🗿-молчание; `LLMError` → фраза LLM_ERROR_PHRASES; `Exception` → logger.exception + LLM_ERROR_PHRASES) ловятся в НОВОЙ except-ветке вокруг медиа-блока (или переводом медиа-блока в общий try хендлера с флагом режима) — фразы и 🗿-поведение те же, что у URL-ветки; тексты не дублируются.

#### 3.1.3 `YoutubeSummarizerService.summarize_transcript` (L3-механика на файле)

Дополнительный метод (НЕ трогая `summarize`/`summarize_cascade`), переиспользует существующий канон:

```python
async def summarize_transcript(self, *, chat_id: int, rag_query: str,
                               transcript: str) -> str:
    """Выжимка по расшифровке ЛОКАЛЬНОГО видео-файла. Канон — тот же
    prompts.youtube_system_prompt (текстовая расшифровка). Возвращает
    cleanup-текст; пустой ответ → LLMBadResponseError (хендлер молчит+🗿)."""
    max_symbols = hot.get("limits.youtube_max_symbols", settings.YOUTUBE_MAX_SYMBOLS)
    system_prompt = hot.get("prompts.youtube_system_prompt", YOUTUBE_SYSTEM_PROMPT)
    rag = await self.memory.get_rag_context(chat_id, rag_query) if (
        self.memory is not None and rag_query) else ""      # best-effort fail-open как L3
    capped = str(transcript or "")[:max_symbols]            # прецедент: движок режет субтитры до max_symbols
    system = system_prompt.replace("{max_symbols}", str(max_symbols))
    user = (f"{rag}\n\n" if rag else "") + (
        "<video_id>tg-file</video_id>\n\n"
        f"<transcript>{escape_xml_text(capped)}</transcript>")
    raw = await self.llm.generate([
        {"role": "system", "content": system},
        {"role": "user", "content": user}])
    logger.info("youtube file-summary LLM OK | in_chars=%d out_chars=%d",
                len(capped), len(raw))
    raw = cleanup_llm_text(raw)
    if not raw.strip():
        raise LLMBadResponseError("youtube file summary: empty answer")
    return raw
```

#### 3.1.4 Автор, обёртка факта и память

- Чистые хелперы форвардов переезжают в новый модуль `handlers/media_common.py` (без изменения поведения): `_build_nickname`, `_resolve_transcript_author(aliases, message)`, `wrap_media_fact`, `_VT_UNKNOWN_AUTHOR`-константа (станет `MEDIA_UNKNOWN_AUTHOR`, значение «Неизвестный» сохраняется). `handlers/voice_transcription.py` импортирует их оттуда и переэкспортирует теми же именами (`from handlers.media_common import _build_nickname, _resolve_transcript_author, wrap_media_fact`), чтобы внешние точки (direct_chat `is_reply_to_transcription` и тесты `vt.wrap_media_fact`/`vt._resolve_transcript_author`) не менялись. `handlers/youtube.py` импортирует те же хелперы напрямую (прецедент импорта handler→handler: `factcheck.py:21`/`direct_chat.py:32`).
- `_inject_video_memory`: копия логики voice `_inject_memory` (:242-264) с `media_type="video"` и `source_type="video_transcript"`; `update_smart_message_text(chat_id, message.message_id, transcript)` (строка сообщения с видео) — только если `_media_db` задан; `memorize_facts(chat_id, wrap_media_fact("video", author, transcript, forward_source=…), source_type="video_transcript")` через `fire_and_forget`. Обе — best-effort, WARNING на сбой (поток не роняем).

#### 3.1.5 Фразы (новые пулы в `services/smartmodule_phrases.py`)

Стиль — как 5.x/VT; все строчные, без эмодзи/маркдауна, без пересечений между пулами и с существующими. Лимиты в тексте — литеральные («10 минут»/«50 мб»), как прецедент `VT_TOO_LONG_PHRASES` (канон не динамический; правится кодом/владельцем пула):

```python
# 5.9 — видео-файлы: слишком длинное (длительность) — проверка ДО скачивания
VIDEO_MEDIA_TOO_LONG_PHRASES: tuple[str, ...] = (
    "этот видос длиннее моих запасов терпения, расшифровываю только до 10 минут",
    "долгий ты видос кинул, шиз, лимит расшифровки 10 минут",
    "видео на полчаса? иди сам смотри, я не транскрибирую дольше 10 минут",
    "лимит длительности превышен, такое я не перевариваю",
)
# 5.10 — слишком большой размер (file_size) — проверка ДО скачивания
VIDEO_MEDIA_TOO_BIG_PHRASES: tuple[str, ...] = (
    "видос жирный, больше 50 мб я не тяну",
    "файл тяжелее моей базы, лимит 50 мб, режь и кидай кусками",
    "такой вес не подниму, ужми видео до 50 мб",
)
# 5.11 — STT-каскад/скачивание недоступно (общий пул отказа)
VIDEO_MEDIA_UNAVAILABLE_PHRASES: tuple[str, ...] = (
    "нейронки не смогли разобрать видео, попробуй переслать еще раз",
    "не вышло выдрать звук из видоса, сервера отказали",
    "транскрибация видео сдохла на обеих моделях, я пас",
)
# 5.12 — пустая расшифровка (тишина/музыка)
VIDEO_MEDIA_EMPTY_PHRASES: tuple[str, ...] = (
    "в видосе тишина или музыка без слов, текста нет",
    "ни одного слова в этой видяшке не нашлось, расшифровывать нечего",
    "звук в видео неразборчивый, пустая расшифровка вышла",
)
```

> Не кладём пулы в `SmartModule/phrases.py` рядом с VT-* — по задачам (T-670) новые пулы живут в `services/smartmodule_phrases.py`; тест непересечения пулов direct_chat их не включает, но правило канона (без повторов фраз) соблюдаем и покрываем тестом.

### 3.2 Часть 1b — хардненинг `is_direct_media_url` + нативные реплаи + cooldown

#### 3.2.1 `tools/video_downloader.py`

Новая константа + проверка (FR-11). Реализация — на hostname-суффиксах с dot-границей, БЕЗ регулярных выражений на весь URL:

```python
# Платформы, чьи ссылки НИКОГДА не являются прямым медиа-файлом, даже если
# путь оканчивается расширением (CDN/редирект/HTML-просмотр): стрим не
# даст файл → такие URL уходят в yt-dlp/cobalt как раньше.
_PLATFORM_HOST_SUFFIXES = frozenset({
    "youtube.com", "youtu.be", "tiktok.com", "instagram.com",
    "facebook.com", "fb.watch", "vk.com", "twitter.com", "x.com",
    "rutube.ru", "vimeo.com", "ok.ru", "twitch.tv", "kick.com",
    "dzen.ru", "vine.co", "reddit.com",
})

def _is_platform_url(url: str) -> bool:
    """hostname == суффикс или оканчивается на '.суффикс' (поддомены)."""
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return False
    return any(host == s or host.endswith("." + s) for s in _PLATFORM_HOST_SUFFIXES)

def is_direct_media_url(url: str) -> bool:
    """…как сейчас (схема/путь/расширение), НО False для платформ FR-11…"""
    if _is_platform_url(url):
        return False
    ...  # существующее тело без изменений
```

Потребители меняются автоматически: `VideoDownloader.download` (:266-268) для платформенного URL пойдёт в yt-dlp/cobalt; хендлер direct-ветка (:199) для него не сработает и уйдёт в обычный probe→quality-меню. `_YOUTUBE_HOSTS` (yt-dlp-гейт, D286) не трогаем: youtube.com и дочерние по-прежнему идут в yt-dlp, остальные платформы — cobalt. Ложных срабатываний «суффикс-маскировка» (`https://evil.com/v.mp4`, `https://youtube.com.evil.com/x.mp4`) нет: последний hostname = `youtube.com.evil.com` — суффиксу `youtube.com` не равен и на `.youtube.com` не оканчивается.

#### 3.2.2 `handlers/video_download.py`

- **Реплай «скачай» на нативные медиа (FR-12).** В ветке «urls пусты» (:186-196): сначала собственное медиа вызова (`message.video/document`) — как сегодня; затем `reply_target = message.reply_to_message` и его `video/document` (квалификация та же, что в 3.1.1: `mime video/*`, либо без mime — по расширению имени; voice/video_note НЕ подходят) → `_handle_native_media(bot, message, reply_media)`. Уточнение: для качества вместо `bot.download_file` (сеть + путь `/tmp/vd_native_*`) ветка переиспользует `fetch_media_to_tmp` из `services/media_download.py` (локальный Bot API: копия с диска; облако — download) и отправляет медиа как раньше. Не нашлось медиа нигде → `VD_NO_LINK_PHRASES` (consume) как сейчас.
- **Cooldown в direct-ветке (FR-13).** В :199-244 после `await reporter.start("⏳ Скачивание…")` и ДО `_downloader.download(...)` добавить `await cooldown_touch(_cooldown, chat_id, user_id)` (успешный старт скачивания жжёт кулдаун; все except-ветки touch не вызывают; повторный запрос в течение кулдауна получит `_cooldown_phrase` на входе ветки — refresh/remaining-проверка уже есть). Обновить семантику в тестах `TestCooldown`.

#### 3.2.3 README/отчёт (FR-14)

Прямые `.mp4`-ссылки (не платформы) — намеренная фича прод-хотфикса (tools/video_downloader.py:266-268): стрим с браузерным UA, при 403 — Retry с Referer, лимит `_DIRECT_MAX_BYTES`. Фиксируется в README разделом «Скачивание видео» (@DevOps, T-683) и отчётом юзеру; отдельного кода не требует.

### 3.3 Часть 2 — Tool Calling direct_chat

#### (а) Этап диагностики прод-логов ДО фикса (T-678, выполняет Builder/DevOps)

SSH `198.46.175.136`, service `admin_bot`:

```
journalctl -u admin_bot --no-pager | grep -E "\[tools\]|generate_chat OK|tool_calls" | tail -n 100
```

Что ищем и как читаем:
- `[tools] provider rejected tools — plain answer` — провайдер не принял tools (детерминированный 4xx на 1-м вызове) → причина НЕ в промпте: проверять конфигурацию модели/провайдера (apinet.cloud/v1, deepseek-v4-flash) и ветку деградации `tool_loop.py:44-48`.
- `LLM generate_chat OK … tool_calls=0` + НЕТ строк `[tools] round=… tool=…` — tools приняты, но модель не вызывает: причина в промпте/description → фиксы 3.3(б/в) — целевой сценарий.
- `[tools] round=1 | tool=execute_web_search …` — инструменты вызываются, но не на счётные вопросы памяти → фикс description + count (3.3(в/г)).
- `[tools] final round …` — цикл завершается штатно.

Результат — коротким дополнением к spec/отчётом PM до реализации D2-D4; если окажется «провайдер отвергает tools» — приоритеты фиксов сдвигаются на диагностику payload/провайдера (открытый вопрос №4).

#### (б) Новый канон `CHAT_SYSTEM_PROMPT` + легаси + миграция

`services/chat_prompts.py`: текущий текст (:3-14) становится константой `LEGACY_CHAT_SYSTEM_PROMPT` (байт-в-байт, без изменений). Новый `CHAT_SYSTEM_PROMPT` — ПОЛНЫЙ предлагаемый текст канона:

```
СИСТЕМНАЯ РОЛЬ:
Ты — токсичный, саркастичный и циничный участник чата (бот-абьюзер). Ты отвечаешь на прямые обращения пользователя (<Target_User>).
В блоке <Global_Context> находится фон беседы. В блоке <Conversation_Thread> — история вашего текущего диалога.

ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ:
1. Имитируй ленивую печать: только строчные буквы (включая начало предложений), без форматирования (никакого маркдауна).
2. Пунктуация базовая, без сложных тире.
3. Разрешен мат и сленг. Будь грубым, но по факту.

ИНСТРУМЕНТЫ:
У тебя есть инструменты — используй их, когда ответ требует данных, которых нет в контексте:
1. query_chat_memory — история и факты этого чата. Вызывай ПЕРВЫМ при вопросах про прошлое: «сколько раз упоминалось слово или тема», «когда это было», «кто говорил», любая статистика чата. Результат инструмента содержит число совпадений и даты — цифры бери только из него.
2. execute_web_search — свежие внешние данные: новости, проверка фактов в интернете, то, чего нет в контексте и памяти.
Вызвал инструмент — отвечай строго по его результату. Не выдумывай цифры и факты, которых нет в контексте или в результате инструмента.

ГЛАВНОЕ ОГРАНИЧЕНИЕ (КРИТИЧЕСКИ ВАЖНО):
Ты должен отвечать ОЧЕНЬ коротко. Твой ответ должен состоять СТРОГО ИЗ ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ. 
Не объясняй свои мысли, не пиши списки. Максимум пара язвительных фраз. Если напишешь больше двух предложений — система упадет.
```

Ограничения канона соблюдены: `<Target_User>` на месте; фигурных скобок нет; стиль и «1-2 предложения» сохранены; блок ИНСТРУМЕНТЫ — инструкция, а не образец ответа. Эталон байт-в-байт обновляется в `tests/test_direct_chat_prompts.py` (:31-42 — там же добавляется проверка, что `LEGACY_CHAT_SYSTEM_PROMPT` == старому эталону).

Миграция — функция в `services/chat_prompts.py` (duck-typed cache, без импорта config_cache — ноль риска циклов):

```python
_PROMPT_KEY = "prompts.direct_chat_system_prompt"

async def migrate_direct_chat_prompt_if_legacy(cache) -> bool:
    """True = значение обновлено (легаси → новый канон). Кастом юзера не
    трогаем; отсутствующий ключ не трогаем (сид вставит новый канон);
    PG недоступен — skip. Вызывается из bot.py main() сразу после cache.init()."""
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[prompt_migration] skip: PG недоступен")
        return False
    current = cache.get(_PROMPT_KEY)
    if current is None:
        logger.info("[prompt_migration] ключ отсутствует — сид сделает своё")
        return False
    if current == CHAT_SYSTEM_PROMPT:
        return False                                  # уже новый канон
    if current != LEGACY_CHAT_SYSTEM_PROMPT:
        logger.warning("[prompt_migration] кастом юзера — НЕ трогаем | chars=%d",
                       len(current))
        return False
    await cache.set(_PROMPT_KEY, CHAT_SYSTEM_PROMPT, "prompts")
    logger.info("[prompt_migration] легаси-канон заменён новым")
    return True
```

Точка вызова — `bot.py::main()` сразу после `await cache.init(); set_config_cache(cache)` (:522-524), до `on_startup()`. Механика доступа: `cache.get(key)` — in-memory (config_cache.py:226-228, значение уже нормализовано через `normalize_value` по типу каталога — для str это строка как есть); `cache.set(key, value, category)` — PG-апсерт + память (:268-290, категория `prompts`). Свежая инсталляция: `pg_db.init()` при `cache.init()` сидит ключ из code_source (новый канон) — миграция увидит `current == CHAT_SYSTEM_PROMPT` → no-op. Прод: значение = старый канон (сид 2026-05..) → замена. Кастом админки (правка через POST /api/config) → не трогаем (WARNING-лог). PG down (R6) → skip.

#### (в) Description'ы `services/tool_schemas.py` (полные тексты)

Имена/схемы/`required`/`time_range` enum — без изменений; правятся ТОЛЬКО description:

```python
TOOL_EXECUTE_WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "execute_web_search",
        "description": "Поиск в интернете (каскад Tavily→Exa→DuckDuckGo). "
                       "Вызывай, когда ответу нужны свежие или внешние факты: новости, "
                       "актуальные события, проверка информации, которой нет в контексте и в памяти.",
        ...
    },
}

TOOL_QUERY_CHAT_MEMORY = {
    "type": "function",
    "function": {
        "name": "query_chat_memory",
        "description": "Поиск по памяти бота: история этого чата, кто и когда писал, "
                       "долгосрочные факты, статистика упоминаний. Вызывай ПЕРВЫМ, когда вопрос "
                       "про прошлое чата: «сколько раз упоминалось слово или тема», «когда это "
                       "было», «кто говорил про …», «что писали раньше». Результат содержит число "
                       "совпадений и диапазон дат — отвечай точно по нему.",
        ...
    },
}
```

#### (г) `query_chat_memory` со счётчиком и диапазоном дат

Данные: `smart_messages` (chat_id, timestamp int, text) + внешне-контентная FTS5 `smart_messages_fts` (services/database.py:73-93; индекс `idx_smart_messages_chat_ts` по (chat_id, timestamp)). Существующий ранжированный поиск — `search_messages_fts` (:868-878). Дизайн: НОВЫЙ метод в `DatabaseService` (существующие не трогаем):

```python
async def search_messages_fts_count(self, chat_id: int, match_query: str,
                                    since_ts: int = 0) -> dict:
    """(count, first_seen, last_seen) по FTS-совпадениям smart_messages.
    since_ts>0 — окно по timestamp (в SQL, не пост-фильтр top-N)."""
    sql = ("SELECT COUNT(*) AS cnt, MIN(m.timestamp) AS first_ts, "
           "MAX(m.timestamp) AS last_ts FROM smart_messages m "
           "WHERE m.chat_id = ? AND m.id IN "
           "(SELECT rowid FROM smart_messages_fts WHERE smart_messages_fts MATCH ?)")
    params: list = [chat_id, match_query]
    if since_ts:
        sql += " AND m.timestamp >= ?"
        params.append(since_ts)
    cursor = await self.db.execute(sql, tuple(params))
    row = await cursor.fetchone()
    return {"count": int(row["cnt"] or 0) if row else 0,
            "first_seen": row["first_ts"] if row else None,
            "last_seen": row["last_ts"] if row else None}
```

`MemoryManager` (services/summary_memory.py, рядом с `search_long_term` :1025-1035) — фасад:

```python
async def count_mentions(self, chat_id: int, keywords_: list[str],
                         since_ts: int = 0) -> dict | None:
    """Счётчик совпадений по тем же токенам, что search_long_term.
    None — пустой FTS-запрос (нечего считать). Ошибки БД — наружу
    (ToolRouter ловит → fail-open текст)."""
    query = build_fts_query(keywords_)                  # summary_memory.py:314-326
    if not query:
        return None
    try:
        return await self.db.search_messages_fts_count(chat_id, query, since_ts)
    except Exception:
        logger.warning("SmartModule L2: count failed | chat_id=%s", chat_id, exc_info=True)
        raise
```

`ToolRouter._query_chat_memory` (:132-167) — правки точечные (порядок веток/сниппетов и лимит 3500 не меняются):

```python
since = _time_range_since(time_range)
# 1. FTS-строки (как сейчас: top-40 search_long_term + пост-фильтр окна)
… существующий код без изменений …
# 1b. Счётчик + диапазон дат (best-effort; ошибка не роняет результат)
stats = None
try:
    stats = await self.deps.memory.count_mentions(
        ctx.chat_id, keywords(query), since_ts=since)
except Exception:
    logger.warning("[tools] query_chat_memory count failed | query=%r", query, exc_info=True)
if isinstance(stats, dict) and stats.get("count"):
    logger.info("[tools] query_chat_memory | query=%r | count=%d | since_ts=%d",
                query, stats["count"], since)
# 2./3. vector/RAG-ветки — как сейчас (только при пустых строках)
…
if not lines and not (isinstance(stats, dict) and stats.get("count")):
    return f"По запросу «{query}» в памяти ничего не найдено."
parts = []
if isinstance(stats, dict) and stats.get("count"):
    period = _TIME_RANGE_LABELS.get(time_range, "за всё время")
    stamp = ""
    if stats.get("first_seen") or stats.get("last_seen"):
        first = _format_timestamp(stats.get("first_seen"))
        last = _format_timestamp(stats.get("last_seen"))
        if first and last and first != last:
            stamp = f" (с {first} по {last})"
    parts.append(f"Найдено {stats['count']} упоминаний «{query}» {period}{stamp}")
parts.extend(lines)
return _truncate("\n".join(parts), _MEMORY_MAX_SYMBOLS)
```

`_TIME_RANGE_LABELS = {"last_day": "за сутки", "last_week": "за неделю", "last_month": "за месяц", "all": "за всё время"}` (модульная константа рядом с `_TIME_RANGE_SECONDS`). Почему count через отдельный SQL, а не Python-пост-фильтр: строки режутся top-40 по rank ДО фильтра окна — точное «N раз в окне» из выборки не извлекается. Почему не трогаем `search_long_term`: сигнатура публична (вызывается из RAG-путей), счётчик нужен только инструменту; расхождение «сниппеты ≤40, count точный» для ответа модели не вредно (сниппеты — примеры, число — факт).

Модель получает `role:"tool"`-текст с «Найдено N упоминаний … (с … по …)» + сниппеты ≤3500 — этого достаточно для точного ответа «сколько раз/когда» (FR-19). Пусто → прежняя честная фраза (модель не выдумывает).

#### (д) Логирование

INFO на каждый исполненный tool_call уже есть: `tool_loop.py:81` (`[tools] round=%d | tool=%s | out_chars=%d`) — НИЧЕГО не добавляем. Дополняется INFO-статистика в самом `_query_chat_memory` (см. выше, блок 1b). Деградация 1-го раунда (`provider rejected tools`) и лимит раундов — WARNING, как сейчас.

### 3.4 Файлы-кандидаты изменений и новые тесты

Изменяемые/новые файлы (порядок — по частям, каждый PR/коммит зелёный):

| Файл | Изменение |
|---|---|
| `config/settings.py` | +2 поля `VIDEO_TRANSCRIBE_*` (блок транскрибации) |
| `services/param_catalog.py` | +2 записи `_LIMITS` (группа `limits_media`); сид и code_source НЕ трогаем |
| `services/media_download.py` | **новый**: `fetch_media_to_tmp`, `local_files_subdir` (перенос из voice без изменения поведения, R17-комментарии) |
| `handlers/voice_transcription.py` | импорт `fetch_media_to_tmp`/`local_files_subdir` из media_download (имена `_fetch_media_to_tmp`/`_local_files_subdir` сохраняются в неймспейсе модуля); чистые хелперы автора/факта — из `handlers/media_common.py` |
| `handlers/media_common.py` | **новый**: `_build_nickname`, `_resolve_transcript_author`, `wrap_media_fact`, `MEDIA_UNKNOWN_AUTHOR` (перенос из voice, значения байт-в-байт) |
| `handlers/youtube.py` | медиа-детекция (`_resolve_video_media`/`_document_is_video`), DI `setup_youtube_video_media`, ветка `_process_video_media`, импорт новых фраз/хелперов; `_parse`/URL-ветка не меняются |
| `services/youtube_summarizer_service.py` | +`summarize_transcript` (канон тот же) |
| `bot.py` | DI внутри summary-блока: общий VoiceTranscriber (перенос создания :296-299 вверх), вызовы `setup_youtube_video_media` и (флаг) `setup_voice_transcription`; вызов `migrate_direct_chat_prompt_if_legacy` в `main()` после `set_config_cache`; порядок регистрации роутеров — БЕЗ изменений |
| `tools/video_downloader.py` | `_PLATFORM_HOST_SUFFIXES`/`_is_platform_url`, гейт в `is_direct_media_url` |
| `handlers/video_download.py` | reply_target-медиа в ветке без ссылок (через `fetch_media_to_tmp`); `cooldown_touch` в direct-ветке |
| `services/chat_prompts.py` | `LEGACY_CHAT_SYSTEM_PROMPT` + новый канон + `migrate_direct_chat_prompt_if_legacy` |
| `services/tool_schemas.py` | description'ы (имена/схемы не меняются) |
| `services/database.py` | +`search_messages_fts_count` |
| `services/summary_memory.py` | +`count_mentions` |
| `services/tool_router.py` | count+диапазон в `_query_chat_memory`, `_TIME_RANGE_LABELS`, INFO-лог |
| `services/smartmodule_phrases.py` | +4 пула видео-фраз (5.9-5.12) |
| `README.md`, `.env.example` | пункты @DevOps (см. 6) |

Новые тест-файлы:

- `tests/test_media_download.py` — fetch_media_to_tmp: локальный режим (копия с диска, retry×3, fallback bot.download, отсутствие файла), облачный (download_enabled=False → bot.download), защита пути (R17), уборка.
- `tests/test_youtube_video_media.py` — хендлер-уровень: reply «транскрипт» на видео без URL; репост-видео (forward_origin); document mime video/*; document без mime по имени; триггер в caption у самого видео; voice/video_note НЕ перехвачены; лимиты размер/длительность ДО скачивания; «транскрипт» → сырой текст чанками; остальные триггеры → LLM-выжимка (мок `summarize_transcript`); EmptyTranscript/TranscriptionUnavailable/битый файл → фразы; память (мок db/memory); триггер без URL и без медиа → UNHANDLED; изоляция приоритетов 0e vs 0f/0g/0h/реакции (по образцу `tests/test_epic37_router_isolation.py`).
- `tests/test_tool_router.py` — новые кейсы count (см. 6).

### 4. Пограничные случаи и решения (Edge cases)

- **Reply «транскрипт» на кружок/голосовое.** Медиа-детекция 3.1.1 квалифицирует ТОЛЬКО `video`/`document`; `voice`/`video_note` в ней отсутствуют → роутер 0e возвращает UNHANDLED → апдейт доходит до 0i voice_transcription (зарегистрирован позже, bot.py:390-391) — транскрипция кружочков не меняется. Голосовые и так транскрибируются автоматически при приходе, без триггера.
- **Сообщение с видео И YT-ссылкой в тексте** (например, репост ролика с caption-ссылкой): `_parse` находит URL первым → URL-ветка (FR-2); медиа-файл не качается. Порядок проверок в хендлере гарантирует это структурно.
- **Видео больше лимита**: `file_size` известен ДО скачивания (поля Telegram) → фраза `VIDEO_MEDIA_TOO_BIG_PHRASES`, файл не качается (FR-3, NFR-3). Для `document` без file_size (редкость) лимит не применим → качаем, на этапе транскрибации ошибка → фраза 5.11.
- **Document без mime**: квалификация по `file_name` (mp4/webm/mov/mkv/avi); `application/pdf`+имя `.mp4` — НЕ видео (mime авторитетнее). Видео-документ с mime video/* и без file_name — видео.
- **Капшен-триггер у самого видео** («видео + „че за видос" в caption», без reply): message.caption уже входит в текст триггера (`_has_trigger`); медиа — собственное `message.video` → ветка работает.
- **Пересечение с «скачай»**: у `video_download` (4e) триггеры свои («скачай/…», `handlers/video_download.py:72-73`), с `_YOUTUBE_TRIGGERS` не пересекаются; видео с caption «скачай» не матчит 0e (нет YT-триггера) → дойдёт до 4e, где сработает собственная ветка нативного медиа (:186-196) как сегодня. Реплай «скачай» на чужое видео: URL в реплае есть → качество-меню (без изменений); URL нет → теперь `_handle_native_media` по медиа реплая (FR-12), раньше — `VD_NO_LINK_PHRASES`.
- **Выключенный `summary_enabled`**: роутер 0e не регистрируется (bot.py:373-374) → видео-ветка недоступна целиком (как и весь YouTube/память/direct_chat). Это текущая архитектурная граница (voice-транскрибация — внутри того же гейта, bot.py:390-391); документируем, НЕ меняем.
- **`enable_voice_transcription=False`**: кружочки/войсы молчат (0i не регистрируется), НО видео-ветка 0e работает (общий VoiceTranscriber создаётся в summary-блоке независимо от флага; пустые ключи → стратегии skip с WARNING). Семантика флага («транскрибация голосовых») не меняется.
- **`download_enabled=False`** (облачный Bot API): `fetch_media_to_tmp` идёт в `bot.download` — видео-ветка и `_handle_native_media` работают (скачивание TG-медиа легитимно в облаке). Видео-ветка НЕ гейтится флагом download_enabled (флаг — про локальный диск-хелпер, прецедент voice).
- **Длительность неизвестна**: `document` — всегда; проверка пропускается, лимит действует по размеру; очень длинное видео-документ упрётся в таймауты/лимиты STT → фраза 5.11. `video.duration` TG отдаёт всегда (int); 0/None → не блокируем (FR-3).
- **Пустой транскрипт** (тишина/музыка/битый звук): `EmptyTranscript` → `VIDEO_MEDIA_EMPTY_PHRASES`; STT-каскад упал → `VIDEO_MEDIA_UNAVAILABLE_PHRASES`. Трейсбеки юзеру не показываются (NFR-1), в логах WARNING (не ERROR-паника, T-672).
- **Длинный транскрипт**: «транскрипт» — `send_chunked_reply` (≤4096/чанк, только первая часть реплаем); выжимка — вход в LLM срезается `[:youtube_max_symbols]` (прецедент движка субтитров); сам транскрипт в память пишется целиком (как voice).
- **Деградация LLM в выжимке**: `LLMError` → `LLM_ERROR_PHRASES`, пустой ответ → 🗿-молчание (существующие ветки хендлера youtube); каскад STT при этом уже отработал — повторный запрос юзера попадёт в кулдаун и расшифровку придётся повторить (принято; кэша у файлов нет, FR-10).
- **Медиа-детекция упала** (кривое сообщение/исключение): `_resolve_video_media` ловит Exception → None → UNHANDLED (пропагация жива, чужие роутеры не задеты).
- **Миграция промпта**: PG выключен → skip (R6, бот жив на settings); значение == новый канон → no-op; == LEGACY → замена; кастом → НЕ трогаем (WARNING). Гонок нет: вызов в `main()` до `start_polling`, `cache.set` под asyncio.Lock.
- **Count и окно времени**: узкие окна (last_day/week) — count точен по SQL-фильтру since; vector/RAG-ветки инструмента по-прежнему только для широких окон (last_month/all), поведение не меняется. Сбой БД в count → fail-open (без заголовка, сниппеты как раньше).
- **Порядок описаний/триггеров инструментов**: промпт-блок и description'ы дополняют друг друга; модель сама решает (tool_choice="auto"). Для «сколько раз…» сработает `query_chat_memory` (AC-3.1 критерий — в логах `[tools] round=… tool=query_chat_memory`).

## 5. Критерии приёмки (Acceptance criteria)

**Часть 1 (нативное TG-видео)**
- AC-1.1. REGISTRY содержит `limits.video_transcribe_max_size_mb` и `limits.video_transcribe_max_duration_seconds` (type int, группа limits_media, дефолты 50/600); `test_param_catalog` зелёный после обновления counts; сид-записи появились в PG автоматически.
- AC-1.2. Unit: reply «транскрипт» на видео-сообщение (без URL) → fetch → VoiceTranscriber → чанковый текст; репост-видео (forward_origin) → автор источника в лейбле/факте; document video/* — транскрибируется; document без mime `.mkv` — транскрибируется; voice/video_note НЕ перехвачены; видео без триггера → UNHANDLED.
- AC-1.3. Лимиты: размер >50МБ и длительность >600с проверяются ДО скачивания (download/mock-fetch не вызван) + фразы из новых пулов; у document — только size-гейт.
- AC-1.4. Деградация: `EmptyTranscript` → фраза 5.12; `TranscriptionUnavailable` → фраза 5.11; битый файл/фетч-ошибка → фраза 5.11; поток жив; юзеру нет трейсбеков.
- AC-1.5. «транскрипт» → сырой текст; «че за видос/о чем видео/поясни за видос/перескажи видос/че в видосе» → LLM-выжимка каноном `prompts.youtube_system_prompt` (мок `summarize_transcript`); пустой ответ LLM → 🗿-молчание.
- AC-1.6. Память: `update_smart_message_text` вызван с расшифровкой; `memorize_facts(source_type="video_transcript")` c `<MediaMessage type="video" …>` (форвард — forwarded/forward_from); сбой памяти → WARNING, ответ уже отправлен.
- AC-1.7. Порядок регистрации роутеров bot.py не изменён (диф); изоляция 0e vs 0f/0g/0h/4e/реакции — тесты зелёные; 3447 старых тестов — без диф-падений (после обновления двух аудит-тестов voice, см. 6).
- AC-1.8. Live (T-685): репост TG-видео + «че за видос» отвечает выжимкой; «транскрипт» — текстом; лимитные файлы — фразами без скачивания.

**Часть 1b (скачивание)**
- AC-2.1. `is_direct_media_url` False для: `https://youtube.com/watch?v=X.mp4`? — нет, watch-URL без расширения; кейсы суффикс-маскировки: `https://vk.com/video-1_2?ext=.mp4` — уже не путь; главные тесты: `https://tiktok.com/@u/video/7` + `…/file.mp4?x=1`, `https://www.youtube.com/shorts/abc.mp4` (путь оканчивается `.mp4`), `https://x.com/i/videos/x.mp4`, `https://rutube.ru/video/x.mp4`, `https://evil.example.com/v.mp4` (НЕ платформа → True). Платформенные URL в `VideoDownloader.download` идут в yt-dlp (youtube) / cobalt (остальные) — мок-тесты веток.
- AC-2.2. Реплай «скачай» на чужое `video`/`document`(video) без ссылок → `_handle_native_media` (файл переслан); на voice/video_note → `VD_NO_LINK_PHRASES` (как сегодня); репост-видео — пересылается.
- AC-2.3. Direct-ветка: после успешного старта скачивания `cooldown_touch` вызван ровно один раз; провал ДО старта (probe/сеть до download_direct) — touch нет; повтор в кулдауне → `_cooldown_phrase`.
- AC-2.4. README-раздел «Скачивание видео» (прямые ссылки остаются стримом, платформы — yt-dlp/cobalt) — @DevOps.

**Часть 2 (Tool Calling)**
- AC-3.1. Live/лог-критерий: на «сколько раз упоминался бензин» в логах есть `[tools] round=… tool=query_chat_memory`; ответ содержит число из результата инструмента.
- AC-3.2. `CHAT_SYSTEM_PROMPT` == новому канону 3.3(б) байт-в-байт; `LEGACY_CHAT_SYSTEM_PROMPT` == старому канону байт-в-байт; `test_direct_chat_prompts.py` зелёный.
- AC-3.3. Миграция (unit, фейковый cache): легаси → set(новый) вызван; новый канон → не вызван; кастом → не вызван; `pg_available=False` → не вызван; `current is None` → не вызван.
- AC-3.4. Description'ы содержат новые тексты (счёт/«сколько раз»/«ПЕРВЫМ»/свежие данные) при неизменных name/parameters/enum; `test_tool_schemas.py` зелёный.
- AC-3.5. `query_chat_memory`: в выводе «Найдено N упоминаний „…" за сутки/неделю/месяц/всё время (с … по …)»; count=0 → честная фраза «ничего не найдено»; сбой count → fail-open (сниппеты без заголовка); лимит 3500 соблюдён.
- AC-3.6. `database.search_messages_fts_count`/`MemoryManager.count_mentions`: SQL-фильтр since, MIN/MAX, пустая выборка → count=0; FTS-запрос пуст → None/0 без падений.
- AC-3.7. Полная интеграция `chat_with_tools` (мок памяти с count): tool_calls=query_chat_memory → role:"tool" с числом → финальный текст с точным числом (по образцу tests/test_direct_chat.py:1845+).

**Регресс**
- AC-4.1. Полный pytest: 0 failed; `git diff --check` чист; коммиты по частям (1→1b→2→E), без секретов.
- AC-4.2. Деплой на 198.46.175.136 (pull --ff-only, restart admin_bot, status); live-верификация T-685; маркеры `[tools]`/`tool_calls=` в прод-логах проверены.
- AC-4.3. `APP_VERSION` не менялся; существующие ключи/env не переименованы; диф bot.py — только DI внутри summary-блока + вызов миграции (порядок роутеров не тронут).

## 6. План миграции/докатки

### Тесты (создать/править)

Создать:
- `tests/test_media_download.py` (см. 3.4) — кейсы, перенесённые из локально-режимных voice-тестов + новые.
- `tests/test_youtube_video_media.py` (см. 3.4) — AC-1.2…AC-1.6.
- В `tests/test_tool_router.py` — класс `TestQueryChatMemoryCount`: count в выводе (мок `memory.count_mentions`, AsyncMock возвращает dict), count=0 → «ничего не найдено», сбой count → сниппеты без заголовка (side_effect), last_day-лейбл, truncate-лимит; в существующих кейсах — добавить мок count_mentions (иначе AsyncMock-дефолт даст MagicMock → ветка заголовка не сработает, вывод останется прежним — тесты не падают, но моки уточняем).

Править:
- `tests/test_param_catalog.py` — `test_settings_field_count` 251→253; `test_group_counts_match_design` (counts категорий, limits +2); при наличии общего счётчика REGISTRY — +2; prompts-счётчик (10) и группы (61) НЕ меняются.
- `tests/test_voice_transcription.py` — (1) локально-режимные фикстуры: патч `services.media_download.settings` (в дополнение к `vt.settings`) и проверка вызова fetch-хелпера; (2) аудит-тест :393-398 («_fetch_media_to_tmp теперь в services/media_download.py») — обновить ожидание источника.
- `tests/test_direct_chat_prompts.py` — эталон нового канона (:31-42) + `LEGACY_CHAT_SYSTEM_PROMPT` == старому эталону + `test_no_format_placeholders`/`test_contains_target_user_placeholder`/`test_no_trailing_newline` на оба + класс `TestPromptMigration` (AC-3.3, фейковый cache).
- `tests/test_tool_schemas.py` — новые description'ы (подстроки «сколько раз», «ПЕРВЫМ», «свежие»), имена/enum/required без изменений.
- `tests/test_video_download.py` — `TestDirectMediaUrlHardening` (AC-2.1), `TestNativeMediaReply` (AC-2.2), кейсы cooldown direct-ветки (AC-2.3).
- `tests/test_youtube_handlers.py` — регресс: существующие (в т.ч. «триггер без URL → UNHANDLED» :309-315 — без медиа) зелёные без правок; при необходимости мелкие сетапы.
- `tests/test_summary_memory.py`/`tests/test_database.py` — `count_mentions`/`search_messages_fts_count` (AC-3.6).
- `tests/test_summary_generator.py:49-53`-паттерн фейковой памяти — не трогаем (отдельные новые моки в tool_router-тестах).

### Документация (@DevOps, T-683)

- README: раздел «Видео-команды» — нативные TG-видео («транскрипт» → расшифровка; «че за видос/…» → выжимка), лимиты (размер 50 МБ/длительность 10 мин, ключи админки), поведение «скачай» (прямые ссылки — стрим, платформы — yt-dlp/cobalt, реплай на видео — пересылка), Tool Calling в прямом чате (промпт-блок, description'ы, count) — кратко.
- `.env.example`: `VIDEO_TRANSCRIBE_MAX_SIZE_MB` / `VIDEO_TRANSCRIBE_MAX_DURATION_SECONDS` с комментариями.
- `plans/docs/memory-project-overview.md` — статусы частей; `plans/backlog.md` при необходимости.

### Каскад развёртывания

1. T-678: прод-диагностика логов (3.3(а)) → результат в spec/отчёт PM.
2. Коммиты по частям (1 → 1b → 2 → E), каждый с локальным прогоном затронутых тестов; перед каждым коммитом — затронутый набор, перед финальным — ПОЛНЫЙ pytest (0 failed).
3. Деплой (T-685, DevOps): `git pull --ff-only` + `systemctl restart admin_bot` на 198.46.175.136; сид новых ключей и миграция промпта (легаси→новый, при кастоме — нет) произойдут автоматически при старте; проверить лог `[prompt_migration]`.
4. Live-верификация: репост TG-видео «че за видос»; «скачай»-реплай на видео; счётный вопрос direct_chat; маркеры `[tools]`/`tool_calls=` в логах; лимитные кейсы.
5. Коммит незакоммиченного на русском: `plans/backlog.md`, `plans/features/tg-video-tool-calling-fixes/`, `plans/docs/memory-project-overview.md`, код/тесты частей; `.env` НЕ коммитим.

## Открытые вопросы (для @Builder/@PM/@DevOps)

1. Фактические лимиты API для фиксации дефолтов: Groq whisper upload (размер файла/длительность) и OpenRouter `input_audio` — Builder проверяет ДО коммита и при необходимости корректирует `VIDEO_TRANSCRIBE_MAX_SIZE_MB`/`MAX_DURATION_SECONDS` (код не зависит — значения горячие).
2. Пул `VIDEO_MEDIA_UNAVAILABLE_PHRASES` закрывает и сбой скачивания, и STT-каскад одной фразой (стиль-канон). Если PM хочет раздельные пулы (фетч vs STT) — добавляется 5-й пул, затрагиваются только фразы/тесты.
3. «транскрипт» + другой триггер вместе → сырой текст (решение 3.1.2). Альтернатива (выжимка приоритетнее) — одна строка; подтвердить вкус владельца.
4. Если прод-диагностика T-678 покажет «провайдер отвергает tools» (а не «tool_calls=0»): фикс смещается на диагностику payload/модели apinet.cloud (deepseek-v4-flash), промпт-миграция всё равно вкатывается (канон-гигиена).
5. Выжимка файла использует канон `prompts.youtube_system_prompt` (редактируемый PG-ключ). Если владелец захочет отдельный промпт для файлов — добавляется PG-only сид `prompts.video_file_system_prompt` + код-канон (обратная совместимость сохраняется: новый ключ с дефолтом-копией youtube-канона).
