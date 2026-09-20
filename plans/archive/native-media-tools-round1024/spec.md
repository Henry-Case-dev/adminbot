# Spec: native-media-tools-round1024 (F14, UPD4 баг A-2)

> **Раунд:** 10.24 · **Фича:** F14 `native-media-tools-round1024` · **Приоритет:** P1 · **Шаг 2 @Architect**
> **ТЗ:** `plans/current_task.md`, секция UPD4 (строки 274–279) **+ UPD5 (строка 403)**, untracked (R18 — не коммитить, секреты не цитировать).
> **Задачи:** `tasks.md` (T-2299…T-2306 + дельта UPD5 T-2333…T-2335).
> **Baseline:** HEAD `00eab85`; прод `4314ea4`; pytest 7xxx/0; SQLite v12.
> **ADR:** `ADR-1024-15.md` (AMEND ADR-1020-4 **R9 9→10**, ADR-1015-3, ADR-1016-1 §2, ADR-1017-2).
> **UPD5 (главное):** инструменты **разделяются по функциям** — выжимка (`summarize_video`) и транскрибация (`transcribe_video`) — два отдельных инструмента с чёткими EN-определениями, чтобы LLM сама выбирала сырой транскрипт или выжимку. Канон R9: **10 инструментов**.
> **Границы:** F13 `native-reply-media-context-round1024` (медиа в контексте) · F15 `video-download-native-ux-round1024` (формулировки/меню) · **F19 `media-transcribe-tool-round1024`** (UPD5 №3: финальная реализация `transcribe_video`/канон 10/команда «транскрипт» — ступень **F14 → F19** по `services/tool_schemas.py`/`services/tool_router.py`).
> **Ступень UPD5:** F14 фиксирует **контракт** (две функции, `summarize_video` = выжимка, `transcribe_video` = сырой текст) и правит `summarize_video`; финальную схему/диспетчер `transcribe_video` и счётчик **10** вливает **F19** (T-2344/T-2345/T-2349) поверх F14. F15/F16/F19 читают этот контракт.
> **Флаг:** `NATIVE_MEDIA_TOOLS_ENABLED` (env-only `ClassVar`, default **ON**).

---

## 1. Цель

Устранить баг A-2 отчёта @Memory: «Бот скачай видос» реплаем на **нативное TG-видео**,
у которого в caption есть ссылка, фейлится как URL-скачивание.

Сейчас `handlers/video_download.py` собирает ссылки из своего сообщения **и реплая**
(`_extract_urls`), поэтому caption-URL реплая уводит запрос в URL-ветку (probe → bounded
fallback), хотя в реплае лежит живое нативное видео. При провале probe юзер видит
«⏳ Скачивание без выбора качества…» и общую фразу («че ты мне суешь? я не могу это скачать»),
без объяснения причины. Инструменты `summarize_video`/`download_media` вообще не умеют
нативное медиа: у них `url` — единственный обязательный аргумент.

**Что должно стать:** нативное медиа приоритетнее caption-URL; понятный отказ probe с
записью реальной причины в лог; инструменты умеют скачать/выжимать видео из реплая
(нативного источника) без потери ссылочного пути.

**UPD5 — разделение инструментов по функциям.** Владелец закрепил семантику:
«что на видео» / «че за видос» и подобные — это запрос **выжимки** (саммаризации);
`транскрипт` — запрос **сырой транскрибации**. Соответственно в tool calling нужны
**два отдельных инструмента** с чёткими определениями, а не один `summarize_video` с
`mode: summary|transcript`. Так LLM по формулировке пользователя сама выбирает, что нужно:
`summarize_video` (выжимка) или `transcribe_video` (голый транскрипт). Канон R9 → **10**.

---

## 2. Что уже есть (не переизобретаем)

| Контур | Координаты |
|---|---|
| Fast-Track роутер 4e (позиция 4e в `bot.py`, регистрируется всегда, гейт — hot-флаг `flags.download_enabled`) | `handlers/video_download.py:239` (`video_download_handler`) |
| Ветвление «есть ссылки → URL-ветка, иначе нативное медиа» | `handlers/video_download.py:245-276` |
| Сбор ссылок из text/caption своего сообщения **и реплая** | `handlers/video_download.py:144-161` (`_extract_urls`) |
| Квалификация документа-видео / резолв медиа реплая | `handlers/video_download.py:100-140` (`_document_is_video`, `_reply_video_media`) |
| Нативный путь пересылки | `handlers/video_download.py:736-770` (`_handle_native_media`, `fetch_media_to_tmp`) |
| Прогресс/фразы без меню, bounded fallback, классификатор probe | `handlers/video_download.py:439-483` (`_download_without_menu`, `_probe_error_phrase`, `_fallback_phrases`) |
| Пул фраз ошибок | `tools/video_download_phrases.py` (`VD_ERROR_PHRASES`, `VD_UNAVAILABLE_PHRASES`, `VD_SERVICE_DOWN_PHRASES`, …) |
| Схемы инструментов (обязательный `url`) | `services/tool_schemas.py:120-172` (`TOOL_SUMMARIZE_VIDEO`, `TOOL_DOWNLOAD_MEDIA`) |
| Реестр/канон инструментов и устаревший комментарий | `services/tool_schemas.py:1-25` (общий docstring), `:241` (`TOOL_CALLING_TOOLS`) |
| Dispatch инструментов + `ToolDeps`/`ToolContext` | `services/tool_router.py:321-432`; `_summarize_video` `:725-780`; `_download_media` `:795-909` |
| Медиа-резолвер YouTube (единый источник квалификации видео) | `handlers/youtube.py:286-333` (`_document_is_video`, `_resolve_video_media`, `_video_suffix`) |
| Нативный каскад 0e (public URL → L1/L2 → STT) | `handlers/youtube.py:630-662` (`_publish_and_cascade`), `:883-998` (`_process_video_media`) |
| Публикация файла и STT | `services/media_share` (модульный сервис), `handlers/youtube.py:429-456` (`_transcribe_video_file`/`_stt_or_phrase` через `VoiceTranscriber`) |
| Контекст вызова инструмента (собирается в direct_chat) | `services/direct_chat_service.py:747-761` |

---

## 3. Требуемое поведение

### 3.1. Fast-Track: приоритет нативного медиа (T-2302)

1. Триггер «скачай/загрузи/стяни» в начале остатка — как сейчас.
2. **Сначала** ищется нативное видео-медиа:
   - своё сообщение: `video` (с `file_id`) **или** `document`, прошедший квалификацию
     `_document_is_video` (mime `video/*`; при пустом mime — расширение из `_VIDEO_DOC_EXTENSIONS`);
   - иначе — медиа реплая (`_reply_video_media`).
   Приоритет: **своё медиа → медиа реплая**.
3. Если нативное медиа найдено → `_handle_native_media` **всегда**, даже если в text/caption
   своего сообщения или реплая есть http(s)-ссылки.
4. Если нативного медиа нет → прежняя логика: `_extract_urls`; ссылки есть → URL-ветка;
   ссылок нет → `VD_NO_LINK_PHRASES`.
5. **Исправление латентного бага (в скоупе F14):** своё сообщение-документ обязано
   квалифицироваться через `_document_is_video`. Сейчас любой `document` (например PDF)
   уходит в `_handle_native_media` и падает на `send_video`. После фикса невидео-документ
   → ветка «нет ссылки» (`VD_NO_LINK_PHRASES`), а не «нативное видео».

**Решение по конфликту «видео + caption-URL»:** нативное медиа побеждает (см. ADR §Решение п.1).
Пользовательский выбор/уведомление при конфликте — зона F15 (T-2307/T-2309).

### 3.2. Понятный отказ probe (T-2303)

1. Реальная причина probe уже пишется в лог (класс + safe-reason). Требуется **не маскировать**
   её общей фразой: `_probe_error_phrase(reason)` для probe-причин (`probe_timeout`,
   `probe_failed`) должен возвращать **отдельный пул** `VD_PROBE_FAIL_PHRASES`, а не
   `VD_ERROR_PHRASES`.
2. `reason ∈ {probe_bot_check, cobalt_down, direct_too_big/ytdlp_too_big/stream_too_big}`
   сохраняют существующий маппинг на `VD_UNAVAILABLE_PHRASES` / `VD_SERVICE_DOWN_PHRASES` /
   `VD_TOO_BIG_PHRASES`.
3. Причина probe пишется через R17-safe лог-точку (`error=<Class> reason=<code>`, без URL) и,
   где доступно, через `services.external_log.trace_step` (F2/logging-infra). Тексты фраз —
   зона F15 (T-2308): F14 добавляет пул и маппинг, F15 финализирует формулировки.

### 3.3. Инструменты и нативное медиа (T-2300/T-2301) + разделение функций (UPD5)

1. **Три медиа-инструмента с одной общей моделью источника** (`url`/`source` из §4.5):
   - `summarize_video` — **только выжимка** (саммаризация). Параметр `mode` **удаляется**
     (инструмент однозначен). Триггеры: «что на видео», «че за видос», «о чем видео»,
     «перескажи/выжимка видео».
   - `transcribe_video` — **только сырая транскрибация** (голый текст, без пересказа).
     Триггеры: явный запрос «транскрипт»/«транскрибация», принудительный повтор
     транскрибации ГС/кружка/видео.
   - `download_media` — скачивание/пересылка (без изменений, но `url`/`source` как выше).
2. `summarize_video` и `transcribe_video` принимают источник **«ссылка ИЛИ медиа из реплая»**:
   - `url: string` остаётся, но становится **необязательным**;
   - добавляется необязательный `source: enum["link","reply"]`;
   - выбор пути: http(s)-`url` → ссылочный путь (байт-в-байт как сейчас); иначе при наличии
     нативного медиа в контексте (`ctx.native_media`) → нативный путь; иначе — понятная ошибка-строка.
3. Нативный источник резолвится **не по тексту от модели**, а по объекту медиа в `ToolContext`
   (см. §4.3) — file_id нельзя восстановить из БД, поэтому bytes берём из разрешённого aiogram-объекта.
4. `download_media` (нативный): `fetch_media_to_tmp` → `send_media`; меню качества **не**
   предлагается (неприменимо); download-кулдаун **не** жжётся (это копирование файла TG, как в
   Fast-Track `_handle_native_media`, а не внешнее скачивание); лимит размера 2 ГБ (лимит TG).
5. `summarize_video` (нативный): скачивание во tmp → публикация через `services.media_share` +
   `deps.video.summarize_media_url` → при недоступности/пустом результате STT-фолбэк (если внедрён
   `deps.transcriber`). **Выжимка** — конденсат; сырой текст наружу не идёт.
6. `transcribe_video`: **сырой транскрипт без пересказа**.
   - native (видео/кружок из реплая) → STT (`deps.transcriber`), лимиты размера/длительности как
     в `handlers/youtube.py:893-910`;
   - YouTube-ссылка → существующий движок субтитров (`YouTubeTranscriptEngine.fetch_transcript`);
     при недоступности субтитров — download → STT (как в командном пути 0e);
   - платформа/direct-URL → download → STT.
   - **Контракт ответа:** инструмент возвращает **сырой текст** в tool_result; описание инструмента
     прямо запрещает модели пересказывать/сжимать. Командный путь `транскрипт` дополнительно шлёт
     голый транскрипт **курсивом** (см. F16) — это тот же стиль, что у ГС.
7. **Разделение по функциям (не путать):**
   - «что на видео»/«че за видос» → `summarize_video` (выжимка);
   - «транскрипт»/«транскрибация» → `transcribe_video` (сырой текст).
   LLM выбирает инструмент по определению (`description`), `tool_choice` не форсируется
   (сохраняем канон ADR-1020-7 / backlog §16 п.2).
8. Инструменты **никогда не бросают** — возвращают строку статуса/ошибки (контракт `dispatch`).
   Таймауты переиспользуются (`_DOWNLOAD_TOOL_TIMEOUT=180`, `_SUMMARIZE_TOOL_TIMEOUT=300`,
   для транскрибации — `_SUMMARIZE_TOOL_TIMEOUT`). Лимиты tool-loop (4 раунда / 2 вызова)
   **не меняются**.
9. **Egress не расширяется:** `transcribe_video` возвращает строку (как query-инструменты), а не
   отправляет сообщение; доставка «курсивом» живёт на командном пути через уже allowlisted
   `_send_transcript_reply`. Новых `SEND_POINTS`/`SEND_ALLOWLIST`-записей нет.

---

## 4. Контракты

### 4.1. `services/native_media.py` (новый модуль, единый источник квалификации)

```python
# frozen dataclass: сообщение-носитель + aiogram-объект Video/Document + kind
@dataclasses.dataclass(frozen=True)
class NativeMedia:
    source: types.Message   # сообщение-носитель (для reply/лог-контекста)
    media: object           # aiogram Video | Document
    kind: str               # "video" | "document"

def document_is_video(doc) -> bool: ...            # mime video/*; пусто → расширение
def resolve_reply_video(message) -> NativeMedia | None: ...  # своё медиа → медиа реплая
def media_suffix(media: NativeMedia) -> str: ...   # ".mp4" / по file_name
async def download_to_tmp(bot, media, *, timeout: float) -> Path: ...  # fetch_media_to_tmp + tmpfile
```

- `handlers/youtube.py:286-333` делегирует в этот модуль (устранение дублей квалификации),
  семантика байт-в-байт совпадает с текущей `_resolve_video_media`/`_document_is_video`.
- R17: модуль логирует только `chat_id`/`kind`/`bytes`, никогда file_id/URL/пути.

### 4.2. Fast-Track (`handlers/video_download.py`)

```python
def _native_video_media(message) -> object | None:
    # своё video/document(видео) → _reply_video_media(message); иначе None
```

Порядок в `video_download_handler`:
```
native = _native_video_media(message)
if native is not None:            # флаг NATIVE_MEDIA_TOOLS_ENABLED (иначе — прежний порядок)
    await _handle_native_media(bot, message, native); return None
urls = _extract_urls(message)
...                               # без изменений
```

### 4.3. `ToolContext` / `ToolDeps` (`services/tool_router.py`)

```python
class ToolContext:
    # аддитивно:
    native_media: NativeMedia | None = None   # резолвится DirectChat (F13), потребляется F14

class ToolDeps:
    # аддитивно (keyword-only, старые вызовы не ломаются):
    transcriber=None        # VoiceTranscriber | None — для native-transcript/STT-фолбэка
```

- **Интерфейс F13 → F14:** `direct_chat_service` (владелец — F13) при сборке `ToolContext`
  кладёт `native_media = native_media_module.resolve_reply_video(message)`. Это единственная
  строка связи; F14 определяет поле и потребление, F13 — эмиссию (T-2295). F14 тестируется
  юнит-уровнем через прямую инъекцию `ctx.native_media`, не требуя F13.
- `deps.transcriber` прокидывается DI в `bot.py` (тот же инстанс, что у youtube); `None` →
  нативный transcript честно возвращает «сервис недоступен».

### 4.4. Схемы (`services/tool_schemas.py`) — **канон R9 = 10 инструментов**

Порядок первых 9 — байт-в-байт (канон R9 до UPD5: `query_chat_memory`, `dig_into_lore`,
`execute_web_search`, `summarize_video`, `download_media`, `get_bot_health`,
`get_recent_history`, `compile_lore_story`, `generate_image`); **10-й — `transcribe_video`
в КОНЕЦ** (канон-дисциплина: новые имена добавляются в хвост, существующий порядок не сдвигается).

`summarize_video` — **выжимка** (`mode` удаляется; `url` необязателен; `+source`):

```python
TOOL_SUMMARIZE_VIDEO = {
    "type": "function",
    "function": {
        "name": "summarize_video",
        "description": (
            "Make a SUMMARY (a condensed retelling) of a video: what it is "
            "about and its key points. Call when the user wants an overview of "
            "a video: 'what is this video about', 'what's in the video', "
            "'retell/summarize this clip'. Source is a link (YouTube/platforms/"
            "direct file) OR the video from the replied message. Returns a "
            "SUMMARY, not the raw transcript."),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": ("Video link (YouTube/platforms/direct "
                                        "file). Omit when the video comes from "
                                        "the replied message.")},
                "source": {"type": "string",
                           "enum": ["link", "reply"],
                           "description": ("Where to take the video from: "
                                           "'link' - use url; 'reply' - use the "
                                           "video/document from the replied "
                                           "message.")},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}
```

`transcribe_video` — **сырая транскрибация** (новый; та же модель источника):

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

`download_media` — без изменений по смыслу, но с той же моделью источника (`url` необязателен
+ `source`; `quality` без изменений).

- `TOOL_CALLING_TOOLS` += `TOOL_TRANSCRIBE_VIDEO` (в конец) → **`len == 10`**; комментарий-счётчик
  в шапке модуля (`:1-34`) и у `TOOL_CALLING_TOOLS` (`:241`) приводится к фактическому (10;
  закрывает рассинхрон «7» — техдолг 10.23 **I2**).
- Имена/порядок первых 9 **не меняются**. `active_tools(...)`/`factcheck_tools(...)` не меняются
  (фактчекер видео-инструментов не получает — остаётся 3).
- Удаление `mode` из `summarize_video` — **осознанная ревизия канона** (UPD5), а не побочный
  эффект: фиксируется AMEND ADR-1015-3/ADR-1020-4 в ADR-1024-15.
- **Ступень F14 → F19:** настоящая спека фиксирует **контракт и определения** обоих инструментов;
  финальную схему `transcribe_video` в коде, dispatch-ветку и счётчик **10** вливает
  **F19 `media-transcribe-tool-round1024`** (T-2344/T-2345/T-2349) — чтобы правка одного файла
  `services/tool_schemas.py`/`services/tool_router.py` не дублировалась. F14-приёмка проверяет
  контракт `summarize_video` и **согласованность** счётчика с F19, а не жёстко «9».

### 4.5. Dispatch инструментов

Приоритет резолва источника (общий для `summarize_video`/`transcribe_video`/`download_media`):

```
url http(s)                       → ссылочный путь (без изменений)
url пуст / source=="reply" /
url не-http (внутренний реф)      → native (если ctx.native_media есть; иначе понятная ошибка)
```

- `summarize_video` по ссылке: YouTube → `deps.video.summarize_cascade` (L3-субтитры, см. F16) /
  платформа,direct → `summarize_media_url` + download + STT-выжимка (паритет с 0e).
- `transcribe_video` по ссылке: YouTube → движок субтитров (raw); платформа,direct → download + STT (raw).
- `download_media` — как сейчас (ссылочный путь/меню качества/кулдаун не меняются).

---

## 5. Изменения по файлам

| Файл | Владелец | Что меняется |
|---|---|---|
| `services/native_media.py` | **F14** | **новый**: `NativeMedia`, `document_is_video`, `resolve_reply_video`, `media_suffix`, `download_to_tmp` |
| `handlers/youtube.py` | F14 (делегирование) | `_document_is_video`/`_resolve_video_media`/`_video_suffix` → вызовы `services.native_media` (семантика та же) |
| `handlers/video_download.py` | **F14** → F15 | `_native_video_media`; приоритет native над `_extract_urls`; квалификация своего document; `_probe_error_phrase` → `VD_PROBE_FAIL_PHRASES` |
| `tools/video_download_phrases.py` | F14 (механизм) → F15 (формулировки) | +`VD_PROBE_FAIL_PHRASES` (отдельный пул) |
| `services/tool_schemas.py` | **F14 → F19** | F14: `url` необязателен + `source` для `summarize_video`/`download_media`; `mode` убран у `summarize_video`; контракт `transcribe_video`. F19: финальная схема `TOOL_TRANSCRIBE_VIDEO` + счётчик **10** |
| `services/tool_router.py` | **F14 → F19** | F14: `ToolContext.native_media`; `ToolDeps.transcriber`; native-резолв/скачивание/выжимка (`_download_media`/`_summarize_video`). F19: dispatch-ветка `_transcribe_video` (raw) |
| `config/settings.py` | F14 | env-only `ClassVar NATIVE_MEDIA_TOOLS_ENABLED` (default ON), вне `param_catalog` |
| `bot.py` | F14 | DI-kwarg `transcriber=...` в `ToolDeps` (порядок роутеров не меняется) |
| `services/direct_chat_service.py` | **F13** | эмиссия `ToolContext.native_media` (интерфейсная строка T-2295) |
| `tests/…` | F14 | см. §6 |

**Δ каталога = 0** (env-only `ClassVar`); **Δ DDL = 0**.

---

## 6. Тесты

- **(a)** «скачай» реплаем на нативное видео **со ссылкой в caption** → вызван `_handle_native_media`,
  URL-ветка **не** задействована. + вариант: своё видео + caption-URL → native.
- **(b)** tool-call без `url` при `ctx.native_media` → `download_media` исполняется (fetch→send);
  `summarize_video` исполняется (публикация→мультимодалка→STT-фолбэк выжимки);
  `transcribe_video` исполняется (STT → сырой текст).
- **(c)** probe-fail (`probe_timeout`/`probe_failed`) → сообщение из `VD_PROBE_FAIL_PHRASES`
  (не из `VD_ERROR_PHRASES`); в логе `error=<Class> reason=<reason>` (caplog), без URL.
- **(d)** Канон-дисциплина: порядок первых 9 байт-в-байт; `summarize_video` без `mode`;
  у `summarize_video`/`transcribe_video`/`download_media` `required` пуст (или не содержит `url`),
  присутствует `source`; комментарий-счётчик приведён к фактическому. **Финальный `len(TOOL_CALLING_TOOLS) == 10`
  (10-й — `transcribe_video`) проверяется после ступени F19**; F14-приёмка — контракт + согласованность.
- **(d2)** **Разделение функций:** `summarize_video.description` требует выжимку и запрещает
  выдавать сырой транскрипт; `transcribe_video.description` требует дословный сырой текст и
  запрещает пересказ; обе схемы — EN, `additionalProperties:false`.
- **(d3)** Dispatch: `transcribe_video(source="reply")` при `ctx.native_media` → возвращает сырой
  STT-текст (не сжат); `transcribe_video(url=<youtube>)` → движок субтитров (raw); при недоступности
  — download+STT; ошибка без `native_media` — понятная строка, не исключение.
- **(e)** ссылочные ветки не сломаны: `download_media(url=…)` (direct/платформа/меню `tdq:`),
  `summarize_video(url=…)`, `transcribe_video(url=…)` — байт-в-байт ссылочное поведение/статусы.
- **(f)** невидео-документ (PDF) на своём сообщении «скачай» → `VD_NO_LINK_PHRASES`, не native.
- **(g)** новые `ToolDeps`/`ToolContext` поля аддитивны: старые вызовы конструкторов работают.
- **(h)** R17: file_id/URL/локальные пути не появляются в логах нативного пути (caplog).
- Полный pytest — 0 failed; `git diff --check` чист.

---

## 7. Риски и митигация

| # | Риск | Severity | Митигация |
|---|---|---|---|
| R1 | Изменение схем ломает tool-loop/фактчекер | High | `url` только ослаблен (необязателен), `active_tools`/`factcheck_tools` не тронуты; тесты (e)/(g); согласование ADR-1015-3 |
| R2 | Приоритет медиа ломает легитимный «скачай <ссылка>» | High | native-first только при фактическом видео в своём сообщении/реплае; тесты (a)/(e); UX-уведомление о конфликте — F15 |
| R3 | Двойное скачивание (native fetch + downloader) | Medium | нативный путь идёт только через `fetch_media_to_tmp`, downloader не вызывается; лимит 2 ГБ; tool-timeouts |
| R4 | Расхождение канона инструментов (число) | Medium | синхронная правка комментария + тест (d); ADR-1024-15 фиксирует **10** |
| R5 | Секреты/пути/file_id в логах | Low | R17-паттерн `error=<Class> reason=<code>`; caplog-тест (h) |
| R6 | F13 не успел отдать `native_media` → live-путь неактивен | Medium | F14 юнит-тестируется инъекцией ctx; интерфейс зафиксирован в §4.3; F14 стартует после контракта T-2291 |

---

## 8. Критерии приёмки

1. Реплай «скачай» на нативное видео (в т.ч. с caption-URL) скачивает/пересылает **нативное**
   видео, не уходя в URL-ветку.
2. При probe-fail пользователь видит **понятную причину** (отдельный пул), причина есть в логах.
3. Инструменты умеют работать с нативным медиа из реплая; ссылочный путь не сломан.
4. Канон инструментов актуализирован: **10 инструментов** (`transcribe_video` — новый), устаревший
   комментарий исправлен.
5. Живой сценарий «Бот что на видео» (реплай на нативное видео) → выжимка через инструмент.
6. Полный pytest — 0 failed; `git diff --check` чист; **Δ DDL = 0**; **Δ каталога = 0**.

---

## 9. Флаг и раскатка

- **Флаг:** `NATIVE_MEDIA_TOOLS_ENABLED` — env-only `ClassVar` в `config/settings.py`,
  **default ON**, вне `param_catalog`. Гейтит (a) native-first маршрутизацию Fast-Track и
  (b) native-резолв в `tool_router`.
- **ON:** новое (исправленное) поведение. **OFF:** байт-в-байт прежнее по маршрутизации (urls-first;
  нативные вызовы без `url` → прежняя ошибка).
- **Разделение инструментов (`summarize_video`/`transcribe_video`, канон 10) — безусловно**, как и
  предыдущая ревизия канона 8→9: JSON-схемы не гейтятся runtime-флагом; флаг гейтит только
  native-first маршрутизацию Fast-Track и native-резолв в `tool_router`.
- Поэтапная раскатка internal→10%→50%→100% **не требуется** (прецедент 10.21–10.23);
  kill-switch достаточен.
- F15 имеет собственный флаг `VIDEO_DOWNLOAD_NATIVE_UX_ENABLED` (формулировки/меню) — он не
  дублирует F14-маршрутизацию.

## 10. Откат

- Флаг OFF; либо `git revert` атомарного коммита фичи.
- **Δ DDL = 0**, Δ каталога = 0, `media/` и `.env` не трогаются; новых миграций/таблиц нет.

## 11. Инварианты (не нарушать)

- **media-политика** — `media/` не добавляется/не удаляется; нативная пересылка работает с TG-объектом.
- **imported-history-immutable** — `smart_messages`/FTS/vec/`import_checkpoints` и `imported_history_*.jsonl` не мутируются.
- **R16** — API аддитивен (`transcribe_video` — новый инструмент; `ToolContext.native_media`/`ToolDeps.transcriber` — аддитивные поля); удаление `mode` у `summarize_video` — осознанный AMEND канона (UPD5), не API-ломание Python. **R17** — логи только коды/классы/числа, без URL/file_id/секретов; **R18** — `current_task.md` не коммитить, секреты не цитировать.
- **`parse_mode=None`** — plain-каналы сохраняются; текстовая доставка не меняется. «Курсив» сырого транскрипта — это **командный** путь (F16, `_send_transcript_reply`, локальный `parse_mode="HTML"` + `<i>`), не глобальный `parse_mode`; `transcribe_video` возвращает строку и доставку не форматирует.
- **egress** — `SEND_POINTS`/`SEND_ALLOWLIST` не меняются; новых send-точек нет (инструменты возвращают строку; курсив идёт через уже allowlisted `_send_transcript_reply`).
- **Порядок роутеров `bot.py`** не сдвигается (только DI-kwargs).
- **Δ DDL = 0.**
