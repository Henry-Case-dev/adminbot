# Spec: F16 `youtube-multimodal-download-fallback-round1024` — YouTube+summary: скачать → мультимодалка → фолбэк субтитры

> **Раунд:** 10.24 (UPD4 кластер B + **UPD5**) · **Приоритет:** P0 · **Шаг 2 @Architect** · **Тип:** backend видео-пайплайн (роутер 0e)
> **Задачи:** T-2313…T-2321 (`tasks.md`) + дельта UPD5 (T-2337…T-2342).
> **Baseline:** HEAD `00eab85`; прод `4314ea4`. Отчёт @Memory: `upd4-live-bug-clusters-round1024` (кластер B).
> **Источники:** `plans/current_task.md` UPD4 (стр. 274–400, кейс `1TON5W_SNKY`) **+ UPD5 (строка 403)**; `plans/backlog.md` §«Раунд 10.24» (F16); `plans/features/round1024-architecture.md`; `plans/features/round1024-upd4-architecture.md`; архив `plans/archive/video-multimodal-pipeline-and-incidents/spec.md`.
> **UPD5 (решения владельца):** (1) порядок «download → мультимодалка → фолбэк субтитры» **подтверждён**; (2) cookies/POT-provider/resident-proxy на проде **разрешены** → опциональный credentialed-уровень для age-restricted; (3) `транскрипт` — сырой транскрипт **курсивом**, выжимка — отдельный путь; в tool calling два инструмента (`summarize_video`/`transcribe_video`, см. F14/ADR-1024-15).
> **R17/R18:** секреты/подписанные `/media/`-URL не логируются и не цитируются. Формат ответа — русский.

---

## 1. Цель

Устранить прод-баг: запрос «Бот че за видос `<youtube-url>`» уходит в LLM **URL страницы** (`https://www.youtube.com/watch?v=…`) как `video_url`, поэтому мультимодальная модель физически не видит видеоряд → L1/L2 падают → остаётся L3-субтитры; для age-restricted видео субтитры **PERMANENT** → пользователь получает ложное «автор видоса зажал субтитры, пересказывать нечего».

**Целевой порядок (решение владельца):** для `kind=youtube` + `mode=summary`:

```
1) скачать видеофайл (существующий VideoDownloader → yt-dlp)
2) опубликовать файл (media_share) и дать мультимодалке РЕАЛЬНЫЙ видеофайл (L1 → L2)
3) при провале/недоступности мультимодалки — честный фолбэк на субтитры (L3)
```

Фактически это перенос на YouTube-URL уже работающей нативной схемы `download → media_share.publish_media_file → summarize_media_url` (`handlers/youtube.py:630-662`, `:957-968`) с сохранением субтитрового пути как фолбэка.

---

## 2. Что уже есть (координаты, не переизобретаем)

| Узел | Где | Состояние |
|---|---|---|
| URL-ветка summary (роутер 0e) | `handlers/youtube.py:1003-1069` (`_process_youtube_summary`) | cache → `summarize_cascade` → фразы; **байт-в-байт** по архиву |
| Роутинг YouTube+summary | `handlers/youtube.py:1105-1110` | `_classify_video_request` → kind=youtube/mode=summary |
| **Корень бага** | `services/youtube_summarizer_service.py:46-48` (`_canonical_youtube_url`), `:62-154` (`summarize_cascade`) | в OpenRouter уходит **URL страницы** — не файл |
| Мультимодалка по произвольному URL | `services/youtube_summarizer_service.py:235-309` (`summarize_media_url`) | L1→L2, отказ/пусто/таймаут → `VideoLevelError`; RAG не подмешивается |
| Публикация файла | `handlers/youtube.py:630-662` (`_publish_and_cascade`), `services/media_share.py` (`enabled`, `publish_media_file`, `delete_file`) | проверено на native/direct/platform ветках |
| Скачивание ссылок | `handlers/youtube.py:678-686` (`_download_url` → `_media_downloader.download(url, "360")`) | YouTube → yt-dlp (`YTDLP_FOR_YOUTUBE`, POT/proxy/cookies через `build_ytdlp_base_opts()`) |
| Нативная схема-эталон | `handlers/youtube.py:957-968` (native+summary) | fetch → publish → L1/L2 → STT-фолбэк |
| Движок субтитров | `services/youtube_transcript_engine.py:178-199` (yt-dlp, `extract_info=None`), `:400-422` (transcript-api: `RequestBlocked/IpBlocked`→TRANSIENT, `AgeRestricted`→PERMANENT), `:148-154` (итоговый raise) | причина age-restricted уже классифицируется, но **не доходит** до выбора фразы |
| Фразы | `services/smartmodule_phrases.py:62` (`YOUTUBE_ERROR_PHRASES`, вкл. «автор видоса зажал субтитры…») | age-restricted неотличим от «нет субтитров» |
| Документация | `plans/ARCHITECTURE.md` §13/§15 (стр. 229, 247–255) | зафиксировано «суммаризация каскадом; сигнатуры не менялись» → **AMEND** |

Диагностика прода (лог `1TON5W_SNKY`, `plans/current_task.md:277,322,364`): `yt-dlp: extract_info returned None` + `transcript-api: list failed (PERMANENT) … age-restricted` → `YouTubeTranscriptUnavailableException` → пул 5.6.

---

## 3. Требуемое поведение

### 3.1. Матрица F16 (только `kind=youtube` + `mode=summary`)

1. **Fast-path кэша** — без изменений (cache-key `cache.build_key("youtube", video_id)`, `handlers/youtube.py:1009-1016`).
2. **Слот пула per-chat** — без изменений (до/после cache как сейчас).
3. **Шаг A (новый) — скачивание видео.**
   - Условие входа: флаг `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED` ON **и** доступный
     мультимодальный клиент (`_service.video_client is not None` и `.available`)
     **и** `media_share.enabled()` **и** `_media_downloader is not None` **и** чат
     допущен раскаткой (см. §9). **Уточнение (review iter1, Finding High):** без
     доступного видео-клиента скачивание бессмысленно — субтитровый фолбэк
     скачанный файл не использует, поэтому шаг A/B пропускается (парность с
     native/direct-ветками) и сразу идёт шаг C.
   - URL скачивания: канонический `https://www.youtube.com/watch?v={video_id}` (это вход для yt-dlp, а **не** `video_url` для OpenRouter).
   - Качество: `360` (переиспользуем `_URL_QUALITY`; экономия времени/диска).
   - Бюджет: `asyncio.wait_for(..., timeout=YOUTUBE_MULTIMODAL_DOWNLOAD_TIMEOUT_SECONDS)` (default 240с).
   - **Credentialed-уровень (UPD5, разрешён владельцем):** при наличии на проде YouTube **cookies /
     POT-provider (bgutil) / resident-proxy** скачивание использует их через `build_ytdlp_base_opts()`
     — age-restricted/защищённые видео становятся достижимыми (и для видо­ряда, и для фолбэк-субтитров).
     Уровень **опционален** и гейтится флагом `YOUTUBE_CREDENTIALED_LEVEL_ENABLED` (env-only, default ON):
     OFF → скачивание только публичных ресурсов (прежнее поведение), age-restricted → честный фолбэк.
     Значения (пути cookies, URL POT/proxy) живут **только в `.env`** — в spec/логи не попадают (R17/R18);
     логируется лишь **presence** (`set|empty`) по каждому из трёх (cookies/POT/proxy).
   - Любой сбой (`DownloadBusyError`/`DownloadTooBigError`/`DownloadError`/`DownloadUnavailableError`/timeout/неожиданное) — **тихий** для юзера, WARNING в лог (класс исключения + safe-`reason`, **без URL**), переход к шагу C. Фраз пользователю на этом шаге НЕ шлём.
4. **Шаг B (новый) — публикация + мультимодалка.**
   - `ticket, text_out = await _publish_and_cascade(bot, chat_id, str(path), _LABEL_YT_URL)` (`_LABEL_YT_URL = "youtube-file"`).
   - `_publish_and_cascade` внутри: `publish_media_file` → `summarize_media_url(video_url=ticket.abs_url, label=...)` → `delete_file` в `finally`.
   - Успех (`text_out` непустой) → `send_chunked_reply` реплаем на target, `cache.set`, INFO-лог, **return** (субтитры не трогаем). Память мультимодального успеха НЕ пишем (паритет с native/direct/platform: инъекция памяти — только на путях с транскриптом/субтитрами; NFR-1/R16).
   - Неуспех/публикация выключена/файл > `MEDIA_SHARE_MAX_MB` → `(ticket, None)` → шаг C (ticket удаляется в `finally` хендлера).
5. **Шаг C (фолбэк) — субтитры.**
   - `text_out = await _service.summarize_cascade(video_id, on_retry=..., chat_id=..., rag_query=text)` — теперь это **только L3-субтитры** (см. §4/§5).
   - Успех → `send_chunked_reply` + `cache.set` (как сейчас).
   - Исключения маппятся как сейчас (см. §3.3), но `YouTubeTranscriptUnavailableException` с `reason == "age_restricted"` → **отдельный** пул `YOUTUBE_AGE_RESTRICTED_PHRASES`.
6. **Уборка:** скачанный `path` — `os.unlink` в `finally`; `ticket` — `media_share.delete_file` в `finally` (best-effort; TTL — страховка).

### 3.2. Что НЕ меняется (границы F16)

- Роутинг/классификация `_classify_video_request` (`handlers/youtube.py:365-405`), `_parse` (D126), триггеры/префиксы, кулдаун, слот пула, счётчики.
- `kind=youtube` + `mode=transcript` (`_process_youtube_transcript:824-878`) — **байт-в-байт**.
- `native`/`direct_url`/`platform_url` ветки (`:716-819`, `:883-998`) — **байт-в-байт**.
- Немедиа и не-summary ветки 0e, роутеры 0a–0i/4e, порядок регистрации `bot.py` — не трогаем (инвариант «порядок роутеров не сдвигается»).
- Успешность/фразы `kind=youtube`+`summary`, кэш, 🗿-молчание, пулы 5.5/5.6/5.8 — сохраняются.
- `parse_mode` plain-каналов, egress-реестр, `imported-history-immutable`, `manual-overrides-immutable` — не трогаем.
- `summarize_media_url`, `summarize_transcript` — без регресса.

### 3.3. Карта исключений (сохраняется)

| Исключение | Реакция |
|---|---|
| `LLMBadResponseError` | `react_moai` (🗿-молчание) — как сейчас |
| `YouTubeTranscriptUnavailableException` | `_reply` пул 5.6 (или **5.6-age** при `reason=="age_restricted"`), реплай на `target` |
| `LLMError` | `_reply` пул 5.5 |
| любое иное | `logger.exception` + пул 5.5 |
| сбои скачивания/публикации/мультимодалки | **тихий** WARNING + переход на фолбэк (не доходят до юзера) |

### 3.4. Разделение «выжимка vs транскрипт» (UPD5)

Владелец закрепил: «что на видео»/«че за видос» — это **выжимка**; `транскрипт` — **сырая
транскрибация**. Для YouTube это два **разных** пути с разным итогом:

| Запрос | mode | Путь 0e | Итог | Формат |
|---|---|---|---|---|
| «че за видос» / «о чем видео» / «поясни за видос» | `summary` | `_process_youtube_summary` (A→B→C, §3.1) | **выжимка** (мультимодалка по файлу, фолбэк — L3-субтитры) | обычный текст (F16/F6) |
| «транскрипт» | `transcript` | `_process_youtube_transcript` | **сырой транскрипт** (субтитры; при недоступности — download→STT) | **курсив** |

1. **`транскрипт` отдаёт голый сырой транскрипт курсивом.** Формат — тот же, что у ГС/кружков:
   `_send_transcript_reply` (HTML первая часть, `<i>…</i>`, эскейп после резки; остаток — plain-чанки).
   **Никакой саммаризации на transcript-пути нет** — это отдельный путь, не задевающий A→B→C.
2. **Выжимка — отдельный путь.** `summary` не отдаёт сырой транскрипт; `transcript` не делает
   выжимку. Смешение запрещено (иначе нарушается ожидание пользователя, UPD5).
3. **Tool-level (F14/F19).** В обычном диалоге (без префикса-триггера) выбор делают инструменты
   `summarize_video` (выжимка) и `transcribe_video` (сырой текст) — контракт в ADR-1024-15
   §2.3-bis, финальную реализацию `transcribe_video`/команду «транскрипт» вливает **F19**
   `media-transcribe-tool-round1024` (ступень **F16 → F19** по `handlers/youtube.py`).
   F16 **не трогает** `services/tool_schemas.py`/`services/tool_router.py` (эксклюзив F14/F19), но
   гарантирует, что YouTube-движок отдаёт сырой транскрипт и корректный `reason`.
4. **`parse_mode` (R16/R17/R18).** Курсив — это **форматирование** локального HTML-канала
   (`parse_mode="HTML"` только на transcript-доставке), глобальный `parse_mode=None` plain-каналов
   не меняется; текст эскейпится (`escape`), теги не рвутся на стыках чанков (`split_transcript_first`).
5. **Принудительный повтор для ГС/кружка.** Триггер `транскрипт` также повторяет транскрибацию
   голосового/видео-кружка, если авто-транскрипция не сработала. Видео-часть (video/video_note)
   покрывается `_process_video_media`/`_process_youtube_transcript`; ГС (voice) — слоем
   `handlers/voice_transcription.py`. **Граница F16:** F16 отвечает за видео/YouTube-часть; слой ГС —
   вне F16, но триггер-контракт общий (см. `services/command_registry.py`).

---

## 4. Изменения по файлам

### 4.1. `services/youtube_summarizer_service.py` (F16-эксклюзив)

- **Удалить** `_canonical_youtube_url` (единственный источник бага) и её использование.
- **`summarize_cascade(video_id, *, on_retry=None, chat_id=None, rag_query=None) -> str`** — сохранить сигнатуру, **изменить тело**: метод становится **субтитровым фолбэком (L3)** — делегирует в `self.summarize(...)` без каких-либо L1/L2-попыток и без `video_client`. Обновить docstring: мультимодалка выполняется вызывающим по **опубликованному файлу** через `summarize_media_url`.
- `summarize`, `summarize_media_url`, `summarize_transcript` — **не трогать** (кроме общего docstring модуля: отразить новую роль `summarize_cascade`).
- `video_client` в `__init__` остаётся (нужен `summarize_media_url`).

**Почему так, а не «параметр `media_url`»:** публикацию/удаление файла и таймауты уровня уже инкапсулирует `_publish_and_cascade` (`:630-662`) — переиспользуем проверенный native/direct/platform-путь. Хендлер композирует «файл-мультимодалка» и «субтитры», а не сервис. Это прямо реализует T-2316 (L1/L2 получают видеоряд) за счёт перевода L1/L2 на `summarize_media_url` по файлу.

### 4.2. `handlers/youtube.py` (F16-эксклюзив)

- `_process_youtube_summary` (`:1003-1069`) — новая композиция A→B→C (§3.1) с `try/finally`-уборкой `path`/`ticket`.
- Новые модульные константы/хелперы:
  - `_LABEL_YT_URL = "youtube-file"`;
  - `_yt_multimodal_enabled() -> bool` (ClassVar-флаг);
  - `_yt_multimodal_timeout() -> float` (ClassVar, safe-clamp ≥ 30);
  - `_yt_multimodal_allowed(chat_id) -> bool` (env-allowlist, §9);
  - `_download_youtube_silent(video_id|url, timeout) -> Path | None` — `asyncio.wait_for` вокруг `_media_downloader.download(...)`, все `Download*Error`/timeout → `None` + R17-safe WARNING. Логировать факт конфигурации `cookies/pot/proxy` как `set|empty` (значения — НЕТ).
- Импорт `YOUTUBE_AGE_RESTRICTED_PHRASES`.
- В `except YouTubeTranscriptUnavailableException` (`:1053-1057`) — выбор пула по `getattr(exc, "reason", "")`.
- Поведение при флаге OFF / `media_share.enabled()==False` / `_media_downloader is None` / недоступном видео-клиенте (`_service.video_client` is None или `.available is False`) — шаг A+B пропускается, сразу C (совместимость с текущими тестами без изменения их ожиданий).

### 4.3. `services/youtube_transcript_engine.py` (F16-эксклюзив)

- `YouTubeTranscriptUnavailableException` — добавить опциональный `reason: str = "unavailable"` (сохранить позиционный `message`).
- `_fetch_segments` (`:404-422`): `AgeRestricted` → `reason="age_restricted"`; `RequestBlocked`/`IpBlocked` → `reason="transient"`; прочее → `reason="unavailable"`.
- `fetch_transcript` итоговый raise (`:148-154`): вычислить `reason` через приоритет `age_restricted` → `transient` → `unavailable` (по классам/атрибутам обоих движков); сообщение не ломать (тесты на текст остаются, добавляется атрибут).
- Использование разрешённых владельцем cookies/POT/proxy — реализовано через `build_ytdlp_base_opts()`/`_transcript_proxy_config()`. **UPD5:** credentialed-уровень — в scope как **опциональная** возможность (флаг `YOUTUBE_CREDENTIALED_LEVEL_ENABLED`, §9), значения только в `.env`. Требуется presence-диагностика (`cookies|pot|proxy = set|empty`, без значений, см. 4.2) и честный фолбэк при отсутствии/отказе кредитных ресурсов.

### 4.4. `services/smartmodule_phrases.py` (общий, вливается по ступени F16 → далее)

- Добавить **append-only** пул `YOUTUBE_AGE_RESTRICTED_PHRASES: tuple[str, ...]` (2–3 фразы, строчные, в стиле существующих, без пересечений с `YOUTUBE_ERROR_PHRASES`/5.9–5.13/NFR-7).
  - Смысл: «видео с возрастным порогом, без авторизации/пропусков я его не вижу; субтитры тоже закрыты» — понятная причина вместо ложной «битой ссылки».
- Файл общий с F14/F15 (native-media-tools / UX) — правка только добавлением пула; порядок вливания и отсутствие конфликтов — на @Builder (T-2318/T-2319).

### 4.5. `config/settings.py` (общий, блок F16 — последним по ступени)

Новые **env-only `ClassVar`** (в `param_catalog` НЕ входят → **Δ каталога = 0**, `dataclasses.fields` их не видит):

| Поле | Тип | Default | Смысл |
|---|---|---|---|
| `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED` | `ClassVar[bool]` | `True` | kill-switch: OFF → сразу субтитровый L3 без скачивания |
| `YOUTUBE_MULTIMODAL_DOWNLOAD_TIMEOUT_SECONDS` | `ClassVar[float]` | `240.0` | бюджет скачивания ветки |
| `YOUTUBE_MULTIMODAL_DOWNLOAD_CHAT_IDS` | `ClassVar[str]` | `""` | CSV chat_id для поэтапной раскатки; пусто = все чаты |
| `YOUTUBE_CREDENTIALED_LEVEL_ENABLED` | `ClassVar[bool]` | `True` | **UPD5:** разрешает credentialed-уровень (cookies/POT/proxy) для age-restricted; OFF → только публичное, честный фолбэк |

---

## 5. Контракты

### 5.1. `YoutubeSummarizerService.summarize_cascade` (переопределённая семантика)

```python
async def summarize_cascade(
    self, video_id: str,
    on_retry: Callable[[int, int], Awaitable[None]] | None = None,
    chat_id: int | None = None,
    rag_query: str | None = None,
) -> str:
    """СУБТИТРОВЫЙ ФОЛБЭК (L3). Мультимодальный L1/L2 здесь БОЛЬШЕ НЕ выполняется:
    YouTube-страница (watch?v=) не является валидным video_url для OpenRouter.
    Мультимодалка для youtube+summary выполняется хендлером по опубликованному
    файлу (media_share → summarize_media_url) ДО вызова этого метода.
    Возвращает текст выжимки; исключения движка/LLM — наружу (фразы у хендлера)."""
    return await self.summarize(video_id, on_retry=on_retry,
                                chat_id=chat_id, rag_query=rag_query)
```

- Поведение без `video_client`: идентично (L3).
- `summarize_media_url(*, chat_id, video_url, label)` — **без изменений** (L1→L2, `VideoLevelError` наружу).

### 5.2. Хелперы хендлера

```python
_LABEL_YT_URL = "youtube-file"

def _yt_multimodal_enabled() -> bool: ...          # ClassVar, default True
def _yt_multimodal_timeout() -> float: ...          # ClassVar, default 240.0, clamp >= 30
def _yt_multimodal_allowed(chat_id: int) -> bool: ...# CSV allowlist; пусто -> True

async def _download_youtube_silent(url: str, timeout: float) -> Path | None:
    """Тихое скачивание 360p для youtube+summary. None = не скачалось (WARNING,
    R17-safe: класс исключения + reason, без URL). Юзеру фраз не шлём."""
```

### 5.3. Движок субтитров

```python
class YouTubeTranscriptUnavailableException(Exception):
    def __init__(self, message: str, *, reason: str = "unavailable") -> None: ...
    reason: str  # "age_restricted" | "transient" | "unavailable"
```

### 5.4. Фразы

```python
# services/smartmodule_phrases.py (append-only)
YOUTUBE_AGE_RESTRICTED_PHRASES: tuple[str, ...] = (
    "...",  # 2–3 формулировки: возрастной порог/нужна авторизация, субтитры закрыты
)
```

---

## 6. Тесты

**Обязательные (воспроизводят баг `1TON5W_SNKY`):**

| # | Тест | Файл | Проверяет |
|---|---|---|---|
| T1 | `summarize_cascade` без медиа **не вызывает** `video_client` (страница больше не уходит) | `tests/test_video_cascade.py` | корневой баг |
| T2 | `_publish_and_cascade` вызывает `summarize_media_url` **с `/media/`-URL**, а не с `watch?v=` | `tests/test_youtube_video_media.py` / `test_video_cascade.py` | видеоряд реально передан |
| T3 | youtube+summary: download → publish → L1-успех → `send_chunked_reply` + `cache.set`, субтитры не запускались | новый `tests/test_youtube_multimodal_download_round1024.py` | порядок 1→2 |
| T4 | мультимодалка падает (`VideoLevelError`) → фолбэк на `summarize_cascade` (субтитры) | там же | порядок 3 |
| T5 | скачивание падает/таймаут → тихий фолбэк на субтитры (без промежуточной фразы) | там же | деградация |
| T6 | `media_share.enabled() == False` → download **не вызывается**, сразу субтитры | там же | NFR-8 |
| T7 | флаг OFF → download **не вызывается**, сразу субтитры | там же | kill-switch/откат |
| T8 | `YouTubeTranscriptUnavailableException(reason="age_restricted")` → `YOUTUBE_AGE_RESTRICTED_PHRASES` | там же | T-2317 |
| T9 | age-restricted reason доезжает из движка (`AgeRestricted` → `reason`) | `tests/test_youtube_transcript_engine.py` (или новый) | T-2317 |
| T10 | R17: в логах ветки нет подписанного `/media/…?s=` URL и нет параметров секрета | там же (caplog) + egress-guard | R17/NFR-3 |
| T11 | пул `YOUTUBE_AGE_RESTRICTED_PHRASES` не пересекается с прочими | существующий тест непересечения фраз | NFR-7 |
| T12 | 🗿/5.5/5.8, кэш-hit, кэш-инвалидация не сломаны | `tests/test_youtube_handlers.py`, `test_epic37_router_isolation.py` | регресс |

**Адаптация существующих тестов (осознанно):**
- `tests/test_video_cascade.py`: удалить импорт `_canonical_youtube_url`; L1/L2-тесты (`test_l1_ok_*`, `test_l1_fail_falls_to_l2`, `test_rag_prefix_*`, `test_memorize_not_called_on_video_path`, `test_empty_model_skips_level` и т.п.) перевести на `summarize_media_url` (там L1/L2 и живут) либо переписать под новую семантику `summarize_cascade` (L3-only). НЕ удалять покрытие транзиентов/refusal/timeouts — перенести на `summarize_media_url`.
- `tests/test_youtube_handlers.py` / `test_epic37_router_isolation.py`: остаются зелёными без правки при OFF-условиях (нет downloader/secret → старое поведение). Точные `assert_awaited_once_with` уточнить.
- `tests/test_tool_calling_round1015.py`: tool-путь `summarize_cascade(video_id)` теперь субтитровый (эффективно как раньше, минус бесполезные 2×120с) — проверить/подправить ожидания.
- `tests/test_param_catalog.py`: счётчики **не меняются** (ClassVar).

**Definition of Done:** полный `pytest` — 0 failed; `git diff --check` чист; R16 (аддитивность), R17 (логи), R18 (секреты не коммитим); Δ DDL = 0.

---

## 7. Риски

| # | Риск | Уровень | Митигация |
|---|---|---|---|
| R1 | Рост времени/стоимости ветки (download ≤240с + L1/L2 до 240с + субтитры) — NFR-4 архива (~5–6 мин) | High | бюджет-таймаут скачивания; kill-switch; allowlist-раскатка; согласование цены с владельцем (Open Q №1) |
| R2 | YouTube скачивание требует POT/proxy/cookies; без них age-restricted → только честный фолбэк | High | переиспользование `build_ytdlp_base_opts()`; presence-диагностика; Open Q №2 |
| R3 | Расхождение с архивным «байт-в-байт» | High | явный AMEND (§12), тест-эталоны «байт-в-байт» для всех немедиа/не-summary веток |
| R4 | Утечка подписанного `/media/` URL в логи | Medium | R17-маскирование (прецедент `_publish_and_cascade`); тест T10 |
| R5 | Двойное скачивание/рост диска | Medium | один download; subtitle-фолбэк — субтитры (`skip_download=True`), не повторный файл; `os.unlink`/`delete_file`/TTL; orphan-thread при timeout скачивания — унаследованное поведение `VideoDownloader`, мониторит @DevOps |
| R6 | Отравление кэша неуспехом | Low | `cache.set` только на успешный текст (как сейчас) |
| R7 | Удаление page-URL-ветки меняет tool-путь | Low | эффективное поведение tool-пути не ухудшается (page-URL всегда падал); отдельный `media_url`-путь для tool — вне скоупа (§13) |

---

## 8. Критерии приёмки

1. Для `kind=youtube`+`mode=summary` `OpenRouterVideoClient.summarize` получает **опубликованный файл-URL** (`…/media/<uuid>.mp4?e=…&s=…`), а не `https://www.youtube.com/watch?v=…`.
2. Порядок гарантирован: скачивание → мультимодалка → при провале/недоступности — субтитры.
3. Провал мультимодалки и/или невозможность скачать не дают ложную фразу; итог — выжимка либо честная причина.
4. Age-restricted (`reason="age_restricted"`) → отдельный понятный пул фраз, причина в логе; без ложной «битой ссылки».
5. Cache/🗿/5.5/5.6/5.8/консьюм не сломаны; transcript/native/direct/platform ветки — байт-в-байт.
6. `pytest` 0 failed; `git diff --check` чист; Δ DDL = 0; Δ каталога = 0; R16/R17/R18 соблюдены.
7. Live (T-2321): «Бот че за видос `<youtube-url>`» → мультимодальная выжимка; age-restricted без пропусков → понятный фолбэк.

---

## 9. Флаг, поэтапная раскатка и Feature Flags

- **Master kill-switch:** `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED` (env-only `ClassVar`, default **ON**).
  - **ON:** шаги A+B (скачать → опубликовать → мультимодалка) → фолбэк C.
  - **OFF:** шаг A+B пропускается, сразу C (субтитровый L3). Деградации нет; шум/нагрузка от скачивания исключены.
- **Бюджет:** `YOUTUBE_MULTIMODAL_DOWNLOAD_TIMEOUT_SECONDS` (default 240, clamp ≥ 30).
- **Progressive delivery (на усмотрение владельца, P0):** `YOUTUBE_MULTIMODAL_DOWNLOAD_CHAT_IDS` — CSV chat_id; пусто = все чаты. Позволяет раскатку internal → 10% → 50% → 100% **без редеплоя**. `_yt_multimodal_allowed(chat_id)` учитывает allowlist; при пустом значении поведение = прежнее (все чаты).
- **Credentialed-уровень (UPD5):** `YOUTUBE_CREDENTIALED_LEVEL_ENABLED` (env-only `ClassVar`, default **ON**)
  — при наличии cookies/POT/resident-proxy в `.env` разрешает yt-dlp/transcript-engine их использовать
  (age-restricted становится достижим). OFF → поведение только на публичных ресурсах (деградации UX нет:
  age-restricted → `YOUTUBE_AGE_RESTRICTED_PHRASES`). **Значения — только `.env`; логируется presence.**
- **Разделение инструментов** (`summarize_video`/`transcribe_video`, канон 10) — **F14/ADR-1024-15**,
  не часть F16; F16 в tool-слой не вносит изменений.
- Каталоговых рубильников НЕ добавляем (рулит env); UI не трогаем.

---

## 10. Откат

1. **Флаг OFF** (`YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED=false`, рестарт) → ветка мгновенно возвращается к субтитровому L3 без скачивания. Это и есть «прежний субтитровый L3» из `tasks.md`.
2. **Полный откат** — `git revert` коммита фичи (восстанавливает, в т.ч., удалённую page-URL-ветку `summarize_cascade`/`_canonical_youtube_url`).
3. **Осознанное уточнение:** флаг НЕ возвращает отправку URL страницы в OpenRouter — удаление этой ветки является безусловным багфиксом (страница никогда не была валидным `video_url`). Байт-в-байт-откат `summarize_cascade` возможен только через `git revert`.
4. Δ DDL = 0, Δ каталога = 0 → миграций/сидов нет.

---

## 11. Инварианты (нарушать нельзя)

1. **`imported-history-immutable`** — `smart_messages`/FTS/vec/`import_checkpoints`/`imported_history_*.jsonl` не мутируются и не удаляются.
2. **egress** — новых send-точек нет: `_reply`/`send_chunked_reply`/`react_moai`/`_send_once` (transcript HTML) уже в реестре `SEND_POINTS`/`SEND_ALLOWLIST`; реестр не расширяется.
3. **R16** — API/сигнатуры расширяются совместимо (`reason` — опциональный атрибут; `YOUTUBE_CREDENTIALED_LEVEL_ENABLED` — аддитивный `ClassVar`); **R17** — логи/отчёты без секретов, без подписанных `/media/` URL и без значений cookies/POT/proxy (только `set|empty`); **R18** — секреты из `current_task.md` не коммитить/не цитировать.
4. **`parse_mode=None`** — plain-каналы: обычные тексты уходят через существующие `send_chunked_reply`; доставка не меняется. Исключение — **локальный** `parse_mode="HTML"` на transcript-доставке (`_send_once`/`_send_transcript_reply`, `<i>`-курсив, эскейп), который существовал и сохраняется; глобальный `parse_mode` не трогается.
5. **`manual-overrides-immutable`** — не затрагивается.
6. **Порядок роутеров `bot.py`** — не сдвигается; правки — только внутренняя логика/DI-вызовы.
7. **Δ DDL = 0** — новых таблиц/колонок/миграций нет; SQLite остаётся `v12`.
8. **Δ каталога = 0** — только env-only `ClassVar` (вне `param_catalog`); счётчики `test_param_catalog` не меняются.
9. **physical-two-call-pipeline** — не затрагивается (ветка 0e вне System 2); фоновые вызовы не добавляются.
10. **`tma-menu-freeze`** — меню/табы/разделы не трогаются.

---

## 12. AMEND архивной границы

Осознанно **пересматривается** инвариант архива `plans/archive/video-multimodal-pipeline-and-incidents/spec.md`:

| Ссылка | Прежнее | Новое (AMEND F16) |
|---|---|---|
| spec.md:37 («YouTube-URL-ветка summary … байт-в-байт») | не менять YouTube+summary | **изменяется**: добавляется шаг «скачать → мультимодалка»; байт-в-байт гарантируется для **всех немедиа и не-summary** веток, `mode=transcript`, native/direct/platform |
| spec.md:52 (FR-B5 «youtube+summary — текущий `summarize_cascade` L1/L2/L3 без изменений») | L1/L2 по URL страницы + L3 | L1/L2 **по опубликованному файлу** (`summarize_media_url`), L3 — субтитровый фолбэк |
| spec.md:241 («youtube+summary: `_parse`-путь целиком … байт-в-байт») | байт-в-байт целиком | сохраняются `_parse`/D126, cache-key, on_retry-нотификатор, 🗿, 5.5/5.6/5.8, консьюм; изменяется только **источник видеоряда** перед L3 |

Также AMEND документации: `plans/ARCHITECTURE.md` §13/§15 (стр. 233, 252) — строка «`summarize_cascade`/`summarize`/`summarize_transcript`-сигнатуры не менялись» уточняется (сигнатура та же, семантика `summarize_cascade` — L3-only). Обновление — на шаге 7 @Architect (T-2318/T-2319).

**Что остаётся байт-в-байт:** transcript-ветка (**формат** — сырой транскрипт курсивом, §3.4), native/direct/platform, «скачай» 4e, реакции, память, кулдаун, кэш-ключ, фразы 5.5/5.6/5.8. Разделение «выжимка/транскрипт» на tool-уровне — F14 (не меняет handler-ветки F16).

---

## 13. Вне скоупа

- **Выжимка** через tool-путь YouTube (`tool_router._video_summary`) — остаётся субтитровой (эффективно
  как раньше); отдельный follow-up: прокинуть downloader/media_share в summary-ветку инструмента.
  Транскрибация через инструмент — **`transcribe_video`** (F14, ADR-1024-15 §2.3-bis); F16 даёт движку
  сырой транскрипт и `reason`.
- Извлечение субтитров из уже скачанного `info` (оптимизация «одно скачивание на всё»).
- CSAM/abuse-политики, изменение пулов 5.5/5.6/5.8.
- UI-TMA, каталог, System 2.
- Слой авто-транскрипции **ГС (voice)** (`handlers/voice_transcription.py`) — F16 покрывает
  видео/YouTube; принудительный повтор ГС триггером `транскрипт` живёт в слое голоса (общий контракт
  триггера, см. §3.4 п.5).
- **Аутентификация YouTube (cookies/POT/proxy) — В SCOPE (UPD5),** но как **опциональный** уровень
  (§3.1/§9), включаемый владельцем через `.env`; F16 не хранит и не печатает значения.

---

## 14. Ссылки

- Задачи: `plans/features/youtube-multimodal-download-fallback-round1024/tasks.md` (T-2313…T-2321)
- ADR: `plans/features/youtube-multimodal-download-fallback-round1024/ADR-1024-17.md`
- Архив-граница: `plans/archive/video-multimodal-pipeline-and-incidents/spec.md` (37, 52, 241)
- Архитектура: `plans/features/round1024-architecture.md`; `plans/ARCHITECTURE.md` §13/§15/§16
- Backlog: `plans/backlog.md` §«Раунд 10.24» (F16; Open Q №1–2 **закрыты UPD5**)
- Живой баг: `plans/current_task.md` (UPD4 B, стр. 277, 322, 364; **UPD5, стр. 403**)
- Инструменты (разделение выжимка/транскрипт): `plans/features/native-media-tools-round1024/{spec.md,ADR-1024-15.md}`
- Код: `handlers/youtube.py`, `services/youtube_summarizer_service.py`, `services/youtube_transcript_engine.py`, `services/media_share.py`, `services/smartmodule_phrases.py`, `tools/video_downloader.py`, `config/settings.py`
