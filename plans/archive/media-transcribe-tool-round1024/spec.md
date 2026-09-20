# Spec: media-transcribe-tool-round1024 (F19, UPD5 №3)

> **Раунд:** 10.24 · **Фича:** F19 `media-transcribe-tool-round1024` · **Приоритет:** P1 · **Шаг 2 @Architect**
> **ТЗ:** `plans/current_task.md`, секция **UPD5** (строка 403) — untracked, **НЕ коммитить**, секреты не цитировать (R17/R18).
> **Задачи:** `tasks.md` (T-2343…T-2352).
> **Baseline:** HEAD `a406440` (F18); прод — предыдущий задеплоенный коммит раунда 10.24. SQLite **v12**.
> **ADR:** `ADR-1024-20.md` (**AMEND** ADR-1020-4 п.2.1 «R9 9→10», **AMEND** ADR-1024-15 §2.1/§2.3, ADR-1015-3).
> **Контракт-источник (Z14):** `plans/features/native-media-tools-round1024/spec.md` §4.4 + `ADR-1024-15.md` §2.1/§2.3-bis — F14 фиксирует **контракт** (два инструмента, `url` необязателен, `source:["link","reply"]`, `ToolContext.native_media`), **F19 реализует** финальную схему/диспатч/команду/счётчик.
> **Ступени общих файлов:** `services/tool_schemas.py` + `services/tool_router.py` — **F14 → F19**; `handlers/youtube.py` — **F14 → F16 → F19**; `handlers/voice_transcription.py` + `handlers/media_common.py` — **F19** (эксклюзив).
> **Предусловие:** F14 (`native-media-tools`) и F16 (`youtube-multimodal-download-fallback`) влиты. Если F14/F16 ещё не влиты на момент старта F19 — F19 применяет их контракт из их spec **дословно** и стыкуется по ступеням (см. §5, §11).
> **Флаг:** `MEDIA_TRANSCRIBE_TOOL_ENABLED` (env-only `ClassVar`, **default ON**, вне `param_catalog`).
> **Δ DDL = 0**, **Δ каталога = 0**.

---

## 1. Цель

Владелец (UPD5 №3) зафиксировал **разделение инструментов по функциям** и семантику команды:

- «Что на видео», «че за видос», «о чем видео» и подобные — это запрос **выжимки** (саммаризации).
- «транскрипт» — отдельная команда именно для **транскрибации**: принудительно повторяет транскрибацию ГС/кружка, если авто-транскрибация не сработала, и так же работает для любого видео; для YouTube отдаёт **голый транскрипт аудио курсивом** в стиле ГС/кружков.

Требуется:

1. В tool calling — **два различимых инструмента**: `summarize_video` (**выжимка**, без `mode`) и `transcribe_video` (**сырой дословный текст**). LLM выбирает инструмент по формулировке пользователя; `tool_choice` **не** форсируется (канон ADR-1020-7 / backlog §16 п.2).
2. Команда «транскрипт»: принудительный повтор транскрибации ГС/кружка (не полагается на авто-путь) и сырой транскрипт курсивом для любого видео, включая YouTube-URL.
3. Канон инструментов **R9: 9 → 10** (`transcribe_video` — 10-й, в конец); закрыть рассинхрон комментария-счётчика (техдолг 10.23 **I2**).

---

## 2. Что уже есть (координаты, не переизобретаем)

| Контур | Координаты (baseline) |
|---|---|
| Схемы инструментов: `summarize_video` c `mode: summary\|transcript`, `download_media`, `generate_image`, `TOOL_CALLING_TOOLS`, комментарий-счётчик «7» | `services/tool_schemas.py:123-147`; `:148+`; `:250`; `:241` (счётчик), `:268` (`TOOL_CALLING_TOOLS`) |
| Dispatch инструментов (реестр, контракт «никогда не бросает») | `services/tool_router.py:408-432`; `_summarize_video` `:725-780`; `_video_transcript` `:761-770`; `_download_media` `:795-909` |
| `ToolDeps` / `ToolContext` (аддитивные поля) | `services/tool_router.py:321-403` |
| Таймауты/капы tool-пути | `_DOWNLOAD_TOOL_TIMEOUT=180.0`, `_SUMMARIZE_TOOL_TIMEOUT=300.0`, `_SUMMARIZE_TRANSCRIPT_CAP=20000`, `_MEMORY_MAX_SYMBOLS=3500` (`:72-92`) |
| Сборка `ToolContext` в direct_chat (эмиссия `native_media` — F13) | `services/direct_chat_service.py:747-761` |
| Канонические триггеры (группа `youtube`: `транскрипт` / `че за видос` / `о чем видео` / `поясни за видос`) | `services/command_registry.py:25` |
| Выбор режима YouTube-команды | `handlers/youtube.py:360-362` (`_request_mode`: «транскрипт» → `transcript`) |
| Классификация видео-запроса (kind × mode) | `handlers/youtube.py:365-420` (`_classify_video_request`); `_resolve_video_media` `:~320-336` (voice/video_note **не** квалифицируются) |
| Сырой транскрипт YouTube курсивом (командный путь 0e) | `handlers/youtube.py:824-870` (`_process_youtube_transcript`), `:461-474` (`_send_transcript_reply`) |
| Сырой транскрипт direct/platform-URL курсивом | `handlers/youtube.py:718-752` (`_process_url_media`, `mode=transcript`) |
| Сырой транскрипт нативного видео/документа курсивом | `handlers/youtube.py:883-998` (`_process_video_media`, `mode=transcript`) |
| STT видео-файла + фразы деградации | `handlers/youtube.py:429-456` (`_transcribe_video_file`, `_stt_or_phrase`) |
| Авто-транскрибация ГС/кружка (observer 0i) | `handlers/voice_transcription.py:153-216` (`_process`), `:223-231` (`voice_transcription_handler`) |
| Детектор «reply на расшифровку» | `handlers/voice_transcription.py:93-118` (`_is_transcription_target`, `is_reply_to_transcription`) |
| Формат «транскрипт как у кружков» (D268/D272) | `handlers/media_common.py:101-124` (`split_transcript_first`, `format_transcript_html`) |
| Egress-реестр (курсив — существующий allowlisted путь) | `services/telegram_send.py:40-70` (`SEND_POINTS`/`SEND_ALLOWLIST`; `handlers/voice_transcription.py` — allowlist «ASR-транскрипт»); `_send_once` через `services/smartmodule_utils.py` |
| STT-сервис | `SmartModule/service.py` (`VoiceTranscriber.transcribe_voice`, `EmptyTranscript`, `TranscriptionUnavailable`) |
| Downloader (link-путь) | `tools/video_downloader.py:303+` (`VideoDownloader.download`), `DownloadError` |
| Тесты канона инструментов | `tests/test_tool_calling_round1015.py:100-110,639`; `tests/test_tool_download_quality_round1017.py:356-359`; `tests/test_tool_schemas.py` |
| Тесты YouTube/ГС | `tests/test_youtube_handlers.py`, `tests/test_youtube_video_media.py`, `tests/test_voice_transcription.py` |

---

## 3. Требуемое поведение

### 3.1. Разделение инструментов и канон (T-2344/T-2349)

1. `summarize_video` — **только выжимка**. Параметр `mode` **удаляется**; `url` становится необязательным; добавляется `source: enum["link","reply"]` (контракт F14 §4.4).
2. `transcribe_video` — **только сырая транскрибация** (дословный текст, без пересказа). Новый, **10-й** в `TOOL_CALLING_TOOLS` (в конец; порядок первых 9 — байт-в-байт).
3. `TOOL_CALLING_TOOLS` → `len == 10`; комментарий-счётчик в шапке модуля и у списка приведён к фактическому (закрыт I2). Синхронно актуализируется `plans/docs/canon/architecture.md` (секция `TOOL_SCHEMAS`).
4. `active_tools(...)`/`factcheck_tools(...)`: фактчекер по-прежнему **без** видео-инструментов (3). В LLM-список `transcribe_video` попадает только при `MEDIA_TRANSCRIBE_TOOL_ENABLED` ON (см. §9).

### 3.2. Команда «транскрипт» — принудительный повтор ГС/кружка (T-2346)

**Сценарий:** авто-транскрибация (observer 0i) не сработала; пользователь **реплаем** на голосовое/кружок пишет каноническую команду (`Бот, транскрипт` / `Олег, транскрипт`, префикс — существующий механизм `command_prefix`).

1. Команда «транскрипт» при `youtube`-триггере и цели-реплае, который является `voice`/`video_note`, **принудительно** запускает транскрибацию этого медиа (скачивание во tmp → STT → ответ).
2. Ответ — **сырой транскрипт курсивом** тем же форматом, что авто-путь (D268/D272: `<b>{имя}</b> 🗣: <i>{текст}</i>`, локальный `parse_mode="HTML"`), реплаем на **целевое** медиа-сообщение (паритет с авто-путём).
3. Повтор **всегда** перезапускает STT (не читает кэш/уже отправленный текст). Формат и фразы деградации (`VT_SILENCE_PHRASES`/`VT_ALL_FAILED_PHRASES`/`VT_TOO_LONG_PHRASES`) — как в авто-пути.
4. Инъекция памяти: `UPDATE smart_messages.text` — идемпотентен; `memorize_facts` выполняется **только если** строка ещё не содержала расшифровку (защита от дублей GraphRAG-фактов при повторе).
5. Temp-файл удаляется в `finally` на 100% путей (инвариант 71.4 п.5).
6. Приоритет цели: своё видео/видео-документ (native) → медиа реплая; `voice`/`video_note` рассматриваются, если видео-медиа нет. Голос без цели → прежний нейтральный ответ `COMMAND_NO_TARGET_PHRASES` (не ломаем).

**Почему в `handlers/youtube.py` (0e), а не в `handlers/voice_transcription.py` (0i):** текстовая команда проходит роутеры в порядке `bot.py` — youtube 0e (`bot.py:766`) **раньше** direct_chat 0h (`:779`) и voice_transcription 0i (`:783`). Сейчас `_triggered_body` ловит команду, `_classify_video_request` не находит видео-цель и отдаёт нейтральную фразу. Поэтому квалификация reply-voice добавляется в `youtube.py`, а сами шаги транскрибации переиспользуются из `voice_transcription.py` (см. §4.5). Порядок роутеров `bot.py` **не сдвигается**.

### 3.3. «транскрипт» для любого видео (T-2347)

1. **YouTube-URL**: `mode=transcript` → субтитры (`YouTubeTranscriptEngine.fetch_transcript`, raw); при недоступности — download → STT. Доставка — **голый транскрипт курсивом** `_send_transcript_reply` (существующий путь `_process_youtube_transcript`). Поведение — **байт-в-байт** (регресс-инвариант F16).
2. **direct/platform-URL**: `mode=transcript` → download → STT → курсив (`_process_url_media`). Без изменений.
3. **Нативное видео/видео-документ (реплай/своё)**: `mode=transcript` → download → STT → курсив (`_process_video_media`). Без изменений.
4. **Не подменять выжимкой**: ветка `mode=transcript` не проходит через LLM-каскад/`summarize*`, не отдаёт пересказ и не требует слота per-chat LLM-пула (как сейчас).
5. Master-флаг `flags.video_summary_enabled` гейтит **только** `mode=summary`; `транскрипт` продолжает работать (сохраняется).

### 3.4. Tool-путь `transcribe_video` (T-2345)

1. **Источник** (та же модель, что у F14 для `summarize_video`/`download_media`):
   - http(s)-`url` → ссылочный путь;
   - пустой/не-http `url`/`source=="reply"` при наличии `ctx.native_media` → нативный путь;
   - иначе → понятная строка-ошибка (не исключение).
2. **Ссылочный путь:**
   - YouTube → субтитры raw (переиспользуется `_video_transcript`, cap `_SUMMARIZE_TRANSCRIPT_CAP`); при недоступности субтитров → `deps.downloader.download(url, None)` → STT `deps.transcriber`;
   - direct/platform → download (`_DOWNLOAD_TOOL_TIMEOUT`) → STT raw.
3. **Нативный путь:** `fetch_media_to_tmp` → STT `deps.transcriber.transcribe_voice` (лимиты размера/длительности — как в `handlers/youtube.py:893-910`); temp чистится в `finally`.
4. **Принимаемые виды медиа:** `video`, видео-`document`, а также `voice`/`video_note` (аддитивное расширение native-резолвера, §4.4). `summarize_video`/`download_media` voice/video_note **не** принимают (понятная ошибка).
5. **Контракт ответа:** инструмент возвращает **сырую строку** (как query-инструменты), усечённую `_MEMORY_MAX_SYMBOLS`; описание прямо запрещает пересказ. Инструмент **никогда не бросает** (контракт `dispatch`); таймаут — `_SUMMARIZE_TOOL_TIMEOUT`. Лимиты tool-loop (4 раунда / 2 вызова) **не меняются**.
6. **Egress не расширяется:** tool не отправляет сообщений; «курсив» живёт только на командном пути (§3.2/§3.3) через уже allowlisted точки.

### 3.5. Без команды «транскрипт» — прежнее авто-поведение (T-2348)

Без явной команды/инструмента поведение не меняется: авто-транскрибация ГС/кружка (0i) — как раньше (байт-в-байт); «что на видео»/«че за видос» → **выжимка** (`summarize_video`/командный `mode=summary`), а не сырой текст, и наоборот.

---

## 4. Контракты

### 4.1. `TOOL_TRANSCRIBE_VIDEO` (EN, канон R9 — 10-й, в конец)

```python
TOOL_TRANSCRIBE_VIDEO = {
    "type": "function",
    "function": {
        "name": "transcribe_video",
        "description": (
            "Transcribe a video or voice note into RAW verbatim text (an "
            "audio transcript), without retelling. Call when the user "
            "explicitly asks for a 'transcript'/'transcription' or to repeat/"
            "re-transcribe a voice message, video note or video. Source is a "
            "link (YouTube/platforms/direct) OR the media from the replied "
            "message. Return the raw transcript VERBATIM - do NOT summarize, "
            "shorten or retell it."),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": ("Video link (YouTube/platforms/direct "
                                        "file). Omit when the media comes from "
                                        "the replied message.")},
                "source": {"type": "string",
                           "enum": ["link", "reply"],
                           "description": ("Where to take the media from: "
                                           "'link' - use url; 'reply' - use the "
                                           "video/voice from the replied "
                                           "message.")},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}
```

`TOOL_CALLING_TOOLS` дополняется `TOOL_TRANSCRIBE_VIDEO` **в конец** → `len == 10`.

### 4.2. `summarize_video` (EN; `mode` удалён, источник как в F14)

Оставляем ровно схему F14 §4.4 (выжимка). Ключевые различители для LLM:

- `summarize_video.description` — «Make a SUMMARY … Returns a SUMMARY, not the raw transcript».
- `transcribe_video.description` — «RAW verbatim text … do NOT summarize, shorten or retell».

`download_media` — без изменений по смыслу (та же модель `url`/`source` из F14).

### 4.3. Dispatch `transcribe_video` (`services/tool_router.py`)

```python
# реестр dispatch += "transcribe_video": self._transcribe_video

async def _transcribe_video(self, arguments: dict, ctx: ToolContext) -> str:
    # 1) резолв источника (url http(s) → link; иначе ctx.native_media → native;
    #    иначе → строка «ОШИБКА transcribe_video: нет источника»)
    # 2) link:  YouTube → _video_transcript (raw, cap);
    #           иначе    → downloader.download → transcriber.transcribe_voice (raw)
    # 3) native: fetch_media_to_tmp → transcriber.transcribe_voice (raw)
    # 4) вернуть _truncate(raw, _MEMORY_MAX_SYMBOLS); НИКОГДА не бросать
```

- Таймаут `_SUMMARIZE_TOOL_TIMEOUT`; лог R17-safe (`[tools] transcribe_video | source=link|native | kind=… | out_chars=N | error=<Class>`).
- При `deps.transcriber is None` / нет downloader / пустой результат / `EmptyTranscript` / `TranscriptionUnavailable` → понятная строка «ОШИБКА … сервис недоступен / пусто», цикл жив.
- `deps.downloader`-ветка чистит temp в `finally`.

### 4.4. Аддитивное расширение native-резолвера (координация F14 → F19)

`services/native_media.py` (модуль F14) аддитивно (R16) расширяется:

- `NativeMedia.kind ∈ {"video","document","voice","video_note"}`;
- `resolve_reply_video(...)` (эмиссия F13) начинает возвращать также `voice`/`video_note` (своё медиа → медиа реплая);
- `download_to_tmp` работает с полем `media` (VoiceVideoNote имеет `file_id`/`file_size`/`duration`) — сигнатура не меняется.

Потребители: `transcribe_video` принимает все `kind`; `summarize_video`/`download_media` — только `video`/`document` (иначе понятная ошибка). Это **расширение**, существующие семантика/квалификация `video`/`document` не переписываются. Если F14 уже влит и `native_media.py` заморожен под F14 — правка согласуется как ступень **F14 → F19** (тем же порядком, что `tool_schemas`/`tool_router`).

**F19 (регресс-фильтр Fast-Track, review iter1):** расширение `resolve_reply_video` до voice/video_note затрагивает единственного потребителя вне F19 — `handlers/video_download.py::_native_video_media` (Fast-Track «скачай», роутер 4e). Там добавлен фильтр по `native_media.VIDEO_KINDS`: голосовое/кружок реплая НЕ квалифицируются как «нативное видео» (поведение Fast-Track для `video`/документ — байт-в-байт, голос обслуживает только `transcribe_video`). Наборы kind-ов — единый источник: `native_media.VIDEO_KINDS` / `native_media.MEDIA_KINDS` (без дублей в `tool_router`). Выбор цели voice-медиа («своё > реплай») — общий хелпер `native_media.voice_media_message` для классификации (0e) и исполнения (0i).

### 4.5. Функция принудительного повтора (`handlers/voice_transcription.py`, F19-эксклюзив)

Рефакторинг `_process` без смены поведения авто-пути:

```python
async def transcribe_media_message(media_message, bot, *,
                                   reply_to_id: int | None = None,
                                   force: bool = False) -> bool:
    """Скачивание → STT → курсив (D268) → инъекция памяти (идемпотентно).
    force=True — повторить STT, не доверяя авто-результату; memorize_facts
    только если строка ещё не содержала расшифровку."""

async def force_repeat_from_reply(bot, command_message) -> bool:
    """Команда «транскрипт» реплаем на voice/video_note → transcribe_media_message."""
```

- `voice_transcription_handler._process(message, bot)` → тонкая обёртка `transcribe_media_message(message, bot, reply_to_id=message.message_id, force=False)` (поведение байт-в-байт).
- `handlers/youtube.py` вызывает `force_repeat_from_reply` при `request.kind == "voice"` (импорт **на уровне функции** — избегаем цикла `youtube ↔ voice_transcription`).
- Ответ реплаем на **целевое** медиа (`reply_to_id = target.message_id`), формат — существующий `format_transcript_html`/D268.

### 4.6. Классификация голоса в `handlers/youtube.py` (F19, поверх F16)

- `_classify_video_request`: перед `return None` добавить квалификацию reply-цели (и, при наличии, своего сообщения) как `voice`/`video_note` → `_VideoRequest(kind="voice", mode="transcript", …)`. Порядок приоритетов сохраняется: YouTube-URL → не-YouTube URL → native video/document → **voice/video_note** → None.
- `youtube_handler`: ветка `kind == "voice"` → `force_repeat_from_reply`; под существующим гейтом `MEDIA_TRANSCRIBE_TOOL_ENABLED`.
- `_request_mode` не меняется («транскрипт» → `transcript`).
- Канонические триггеры — без изменений (`command_registry.py` уже содержит «транскрипт» в группе `youtube`); новые синонимы **не** вводятся.

---

## 5. Изменения по файлам

| Файл | Владелец / ступень | Что меняется |
|---|---|---|
| `services/tool_schemas.py` | **F14 → F19** | F19: `TOOL_TRANSCRIBE_VIDEO` (EN) + `TOOL_CALLING_TOOLS` → 10 (в конец); комментарий-счётчик → 10 (закрыт I2); импорт/модуль-докстринг. F14-часть (`summarize_video` без `mode`, `url`/`source`) не переписывается |
| `services/tool_router.py` | **F14 → F19** | F19: `dispatch += "transcribe_video": _transcribe_video`; реализация `_transcribe_video` (link YouTube→субтитры raw, иначе download+STT; native→STT); R17-лог; без правок F14-блоков (`native_media`/`transcriber`/`_summarize_video`/`_download_media`) |
| `services/native_media.py` | **F14 → F19** (аддитивно) | kinds `voice`/`video_note` в `resolve_reply_video`/`NativeMedia` |
| `handlers/youtube.py` | **F14 → F16 → F19** | F19: `_classify_video_request` + voice/video_note; ветка `kind=="voice"` → `force_repeat_from_reply`; гейт `MEDIA_TRANSCRIBE_TOOL_ENABLED`; регресс-гарантия `mode=transcript` (raw-курсив) не ломается |
| `handlers/voice_transcription.py` | **F19** (эксклюзив) | Рефактор `_process` → `transcribe_media_message(..., force=...)` + `force_repeat_from_reply`; `reply_to_id`-параметризация; идемпотентная инъекция памяти; auto-путь байт-в-байт |
| `handlers/media_common.py` | **F19** (эксклюзив) | (при необходимости) экспорт/переиспользование `format_transcript_html`/`split_transcript_first` вызывающими F19; поведение не меняется |
| `services/command_registry.py` | читается F19 | **без изменений** (группа `youtube` уже содержит «транскрипт»); новые триггеры не добавляются |
| `config/settings.py` | **F19** (аддитивный блок) | env-only `ClassVar MEDIA_TRANSCRIBE_TOOL_ENABLED` (default ON), вне `param_catalog` |
| `services/direct_chat_service.py` | F13 (эмиссия) | **без правок F19** (эмиссия `native_media` уже отдаёт расширенные kinds после §4.4) |
| `plans/docs/canon/architecture.md` | **F19** (docs) | секция `TOOL_SCHEMAS`: 10 инструментов, `summarize_video` без `mode`, `transcribe_video` EN-описание; AMEND-ссылки |
| `tests/…` | **F19** | см. §6 |
| `handlers/video_download.py` | F14/F15 → **F19** (регресс-фильтр Fast-Track) | Одна правка: `_native_video_media` фильтрует нативное медиа по `native_media.VIDEO_KINDS`, т.к. `resolve_reply_video` (расширенный F19 до voice/video_note, §4.4) иначе заставил бы Fast-Track «скачай» по реплаю на ГС пересылать голосовое. Поведение `video`/документ — байт-в-байт |
| `tools/video_download_phrases.py` | F14/F15 | **не трогается F19** |

**Δ DDL = 0**; **Δ каталога = 0** (env-only `ClassVar`); `media/`/`.env` не трогаются.

---

## 6. Тесты

- **(a) Выбор инструмента LLM (сырой текст vs выжимка):** `summarize_video.description` требует выжимку и прямо отвергает сырой транскрипт; `transcribe_video.description` требует дословный текст и запрещает пересказ; обе EN, `additionalProperties:false`, `required` пуст/без `url`, присутствует `source`.
- **(b) «транскрипт» принудительно повторяет ГС/кружок:** reply «Бот, транскрипт» на `voice`/`video_note` (авто-путь «не сработал») → STT вызван **заново**, ответ курсивом `<b>…</b> 🗣: <i>…</i>` реплаем на целевое сообщение; temp удалён; повторный вызов не дублирует `memorize_facts` (идемпотентность).
- **(c) YouTube-URL + «транскрипт» → курсивный сырой транскрипт:** `_send_transcript_reply`/формат сырого текста, **без** саммаризации; direct/platform/native `mode=transcript` — тоже (регресс).
- **(d) Канон = 10:** `len(TOOL_CALLING_TOOLS) == 10`, 10-й — `transcribe_video`; порядок первых 9 байт-в-байт; `summarize_video` без `mode`; комментарий-счётчик актуализирован; обновляются существующие тесты-ассерты `== 9` (`test_tool_calling_round1015.py`, `test_tool_download_quality_round1017.py`).
- **(e) Dispatch/пути не сломаны:** `transcribe_video(url=<youtube>)` → субтитры raw; `transcribe_video(url=<direct/platform>)` → download+STT raw; `transcribe_video(source="reply")` при `ctx.native_media` (video/voice) → STT raw; `summarize_video`/`download_media` — ссылочные ветки и native/video байт-в-байт.
- **(f) Без команды — прежнее авто-поведение:** авто-транскрибация ГС/кружка (0i) не изменилась; «что на видео» → выжимка; «транскрипт» по видео → сырой текст (байт-в-байт там, где ветка не новая).
- **(g) Ошибки — не исключения:** `transcribe_video` без `url` и без `ctx.native_media` → строка «ОШИБКА …»; `deps.transcriber is None` → понятная строка; voice через `summarize_video` → понятная ошибка.
- **(h) Флаг:** `MEDIA_TRANSCRIBE_TOOL_ENABLED` OFF → `transcribe_video` не в `active_tools`, команда «транскрипт» по ГС даёт прежний нейтральный ответ; схема/канон (`TOOL_CALLING_TOOLS==10`) — безусловны.
- **(i) R17:** caplog нативного/ссылочного пути — нет `file_id`/URL/локальных путей (только `source`/`kind`/`out_chars`/`error=<Class>`).
- **Полный pytest — 0 failed; `git diff --check` чист.**

---

## 7. Риски и митигация

| # | Риск | Severity | Митигация |
|---|---|---|---|
| R1 | LLM путает `summarize_video` и `transcribe_video` | High | Однозначные EN-`description` (§4.1/§4.2) + тест (a); `tool_choice` не форсируется (канон) |
| R2 | Форс-повтор ломает авто-транскрибацию/идемпотентность | High | Повтор только по явной команде; `force`-параметр; идемпотентная инъекция памяти; тесты (b)/(f) |
| R3 | Расширение native-резолвера задевает F13/F14 | Medium | Аддитивные `kind`; существующие `video`/`document` байт-в-байт; ступень F14 → F19; тесты (e) |
| R4 | Конфликт правок `tool_schemas`/`tool_router` с F14 и `youtube.py` с F16 | Medium | Строгие ступени **F14 → F19**, **F16 → F19**; F19 не переписывает F14/F16-блоки |
| R5 | Voice-команда перехватывается/перехватывает другие роутеры | Medium | Квалификация в 0e до `return None`; `bot.py`-порядок не меняется; цель только при валидном reply voice/video_note; иначе прежний нейтральный ответ |
| R6 | Утечка `file_id`/URL в тексты/логи | Low | R17-лог только коды/классы/числа; caplog-тест (i) |
| R7 | Дубль GraphRAG-фактов при принудительном повторе | Low | `memorize_facts` только если строка не содержала расшифровку |
| R8 | Двойной расход STT/скачивания | Low | Повтор — только по явной команде; лимиты размера/длительности как в авто-пути; tool-таймауты. **Принято (review iter2):** voice-команда форс-повтора обрабатывается ДО youtube-кулдауна (OFF-фиделити, §9) и в ON-состоянии youtube-троттлингом НЕ ограничена — ограничители: явность команды, лимит длительности ГС и STT-таймаут |

---

## 8. Критерии приёмки

1. В tool calling два различимых инструмента: **выжимка** и **сырой транскрипт**; LLM выбирает по определению.
2. Команда «транскрипт» принудительно повторяет транскрибацию ГС/кружка и работает для любого видео; для YouTube — голый транскрипт аудио **курсивом**.
3. «Что на видео»/«че за видос» дают **выжимку**, а не сырой транскрипт (и наоборот).
4. Канон инструментов = **10**; рассинхрон I2 закрыт (комментарий + `docs/canon`); `active_tools`/`factcheck_tools` не сломаны.
5. Без команды «транскрипт» — прежнее авто-поведение (байт-в-байт).
6. Инструменты не бросают; egress-реестры не расширены; `parse_mode=None` не тронут.
7. Полный pytest — **0 failed**; `git diff --check` чист; **Δ DDL = 0**; **Δ каталога = 0**.

---

## 9. Флаг и раскатка

- **Флаг:** `MEDIA_TRANSCRIBE_TOOL_ENABLED` — env-only `ClassVar` в `config/settings.py`, **default ON**, вне `param_catalog`.
- **Гейтит:** (а) включение `transcribe_video` в LLM-список `active_tools`; (б) командный форс-повтор ГС/кружка в `handlers/youtube.py`.
- **НЕ гейтит:** наличие схемы `TOOL_TRANSCRIBE_VIDEO` и канон-счётчик **10** (`TOOL_CALLING_TOOLS`), а также удаление `mode` у `summarize_video` — это безусловная ревизия канона (UPD5), как и 8→9 ранее.
- **ON:** новое поведение. **OFF:** LLM видит 9 инструментов (прежний набор без `transcribe_video`); «транскрипт» по ГС/кружку → прежний нейтральный ответ; авто-транскрибация и видео-транскрипт-команды — как до F19.
- **Progressive delivery** (internal→10%→50%→100%) **не требуется** — kill-switch достаточен (прецедент 10.21–10.23).
- **Кулдаун voice-команды (review iter2, осознанно):** ветка `kind="voice"` в `youtube_handler` обрабатывается **до** `cooldown_refresh`/`cooldown_touch`, поэтому в ON-состоянии форс-повтор «транскрипт» по ГС/кружку youtube-кулдауном **не троттлится** (как и авто-путь 0i). Это цена OFF-фиделити kill-switch (при `MEDIA_TRANSCRIBE_TOOL_ENABLED=false` — ровно прежний нейтральный ответ без списания кулдауна). Ограничители расхода: явность команды, лимит длительности (`limits.voice_max_duration_seconds`) и STT-таймаут. Принято как R8-accepted Low.

## 10. Откат

- Мягкий: `MEDIA_TRANSCRIBE_TOOL_ENABLED=false` (возврат к прежнему поведению без `transcribe_video`/форс-повтора).
- Полный: `git revert` атомарного коммита F19.
- **Δ DDL = 0**, **Δ каталога = 0**; `media/`/`.env` не трогаются; миграций нет.

---

## 11. Инварианты (не нарушать)

- **`imported-history-immutable`** — `smart_messages`/FTS/vec/`import_checkpoints`/`imported_history_*.jsonl` не мутируются (кроме штатного идемпотентного `UPDATE smart_messages.text` транскрипта, как в существующем авто-пути).
- **Egress-реестр** — `SEND_POINTS`/`SEND_ALLOWLIST` **не расширяются**: доставка курсива идёт через существующие allowlisted `_send_transcript_reply` (`_send_once`/`services/smartmodule_utils.py`) и `handlers/voice_transcription.py` (уже в allowlist «ASR-транскрипт»); инструменты возвращают **строку**.
- **`parse_mode`** — локальный `parse_mode="HTML"` для курсива (существующий); глобальный `parse_mode=None` plain-каналов **не трогается**.
- **R16** — API аддитивен (`transcribe_video` — новый инструмент; `NativeMedia.kind` — расширение; `data`/схемы не ломаются).
- **R17** — логи/спеки/отчёты без `file_id`, публичных/подписанных URL, секретов (только `source`/`kind`/`script`/`out_chars`/`error=<Class>`).
- **R18** — `plans/current_task.md` не коммитить, значения секретов не цитировать.
- **Порядок роутеров `bot.py`** — не сдвигается.
- **Лимиты tool-loop** (4 раунда / 2 вызова) и tool-таймауты — не меняются.
- **Δ DDL = 0**, **Δ каталога = 0**; `media/`/`.env` не трогаются.
