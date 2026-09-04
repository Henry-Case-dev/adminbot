# Раунд 3: универсальный видео-маршрутизатор + публикация временных медиа + инциденты (STT/память/«сцуко»/BetterStack)

Дизайн-раунд 04.09.2026, 4 части (T-686…T-704; продолжает T-685/база e000297). Ссылки: `plans/features/video-multimodal-pipeline-and-incidents/tasks.md`, живой план `plans/docs/memory-project-overview.md`, образцы формата — `plans/archive/tg-video-tool-calling-fixes/spec.md`, `plans/archive/multimodal-summarization-tools-reactions-ui/spec.md`. Код проверен точечно: `handlers/youtube.py` (457 строк, медиа-ветка Части 1 уже на месте), `SmartModule/service.py`, `SmartModule/transcriber/*`, `services/video_cascade_client.py`, `services/youtube_summarizer_service.py`, `services/database.py`, `services/summary_memory.py`, `tools/video_downloader.py`, `web/app.py`, `bot.py`, `config/settings.py`.

## 1. Обзор (Overview)

Четыре блока работ по итогам прод-инцидентов 04.09 (см. tasks.md; проблемы 1–4):

**ПРОБЛЕМЫ 2+3 — видео.** Медиа-ветка Части 1 (репост TG-видео + «че за видос») имеет ТОЛЬКО STT-канал: визуального (мультимодального) пути у неё нет. 02:45 «немое» видео → STT вернул 29 символов → выжимка строилась по RAG-памяти (`summarize_transcript` подмешивал `rag_query=text`), ответ был «про память», а не про ролик. 03:21 — Groq timeout (10 с) → OpenRouter HTTP 400 (m4a-base64 на большом mp4) → OpenRouter timeout (15 с) → `TranscriptionUnavailable` → фраза-отказ. Прямые `.mp4`-ссылки и платформы (tiktok/instagram/vk…) по «че за видос <url>» не обрабатываются вовсе (`handlers/youtube.py:_parse` требует только youtube_id; прямые ссылки живут лишь в 4e «скачай»). «транскрипт»-режим медиа-ветки — plain-текст («Имя 🗣:\nтекст`) БЕЗ HTML-формата кружков. Память видео падает: SQLite-CHECK `graph_facts.origin` не содержит `video_transcript` (и `voice_transcript`) → `insert_graph_fact` молча скипается per-fact except-веткой (`summary_memory.py:1311-1316`). Плюс INFO-маркер «smart_message row not found» (`youtube.py:240`) при репостах видео самим ботом (observer 0a не сохраняет сообщения бота, `handlers/summary.py:166-167`).

**ПРОБЛЕМА 4 — «сцуко».** Причина установлена (промпт в БД == канон): слово впервые сгенерировала сама модель в 03:43:55, далее самоподкрепление через `style_anchors` (`_build_style_anchors`, direct_chat_service.py:534-556 — «держи тон» + дословные хвосты последних ответов) и RAG-факты `origin='bot_direct_reply'` без TTL (`CHAT_DIRECT_REPLY_TTL_DAYS=None` = вечно). Новое поведение НЕ запрещает мат — только убирает залипание.

**ПРОБЛЕМА 1 — BetterStack.** Код/инфра на месте (токен 26 символов, сеть 200), но после жёсткого рестарта 02:11:14 события в панель не идут. Тихие потери logtail 0.4.0 (Queue 1000, `raise_exceptions=False`, `drop_extra_events=True`), отсутствие стартовой диагностики.

### Цели раунда

1. (T-687) Подсистема публикации временных медиа-файлов с HMAC-signed URL + TTL (эндпоинт `/media/{file_id}?e=&s=` в FastAPI; внешний домен через Caddy-заметку @DevOps) — единственный путь к мультимодальному «просмотру» нативных TG-видео и скачанных файлов через OpenRouter.
2. (T-688) Универсальный маршрутизатор видео-запроса в 0e: матрица (kind: youtube/direct_url/platform_url/native) × (mode: summary/transcript) с сохранением лимитов, кулдауна, изоляции роутеров и YouTube-каскада байт-в-байт.
3. (T-689/T-691) Мультимодальный каскад по опубликованному URL + честная выжимка (только по реальному контенту, без RAG-памяти как источника «о чём видео»).
4. (T-690) «транскрипт» для ВСЕХ типов, оформление как у кружков (HTML, автор, «(переслал X)»).
5. (T-692) STT: таймауты под видео, размерные гейты провайдеров, ретрай-политика транзиентных.
6. (T-693/T-694) Фиксы памяти: CHECK-миграция (включая `voice_transcript`) + фолбек отсутствующей строки smart_messages.
7. (T-696/T-697) Анти-залипание style_anchors + TTL bot_direct_reply по умолчанию 30 дней.
8. (T-700/T-701) BetterStack: стартовая диагностика + документация live-теста @DevOps.

### Сценарии пользователя

- Кидаешь/репостишь видео и пишешь «че за видос» → бот **смотрит ролик** мультимодальной моделью (L1/L2) по временной публичной ссылке и едко пересказывает; «немое» видео с музыкой → честная фраза, а НЕ выжимка по памяти чата. «транскрипт» → расшифровка, оформленная как у кружков.
- Пишешь «че за видос https://…/clip.mp4» → сначала прямая мультимодалка по ссылке, при провале — скачивание → публикация → повтор; «транскрипт https://…/clip.mp4» → скачивание → STT.
- Пишешь «че за видос <tiktok/instagram/vk-ссылка>» → скачивание (yt-dlp/cobalt, существующий `VideoDownloader`) → публикация → мультимодалка; «транскрипт <ссылка>» → скачивание → STT.
- «транскрипт <youtube-url>» → **субтитры текстом** (замена прежнего поведения «выжимка»); при недоступности субтитров — скачивание → STT.
- В прямом чате после серии одинаково начатых ответов бота → бот перестаёт повторять одно и то же первое слово (анти-залипание); факты «что бот отвечал юзеру» живут 30 дней.

### Границы (НЕ ломать)

- **Порядок регистрации роутеров `bot.py` (366-471) не меняется ни на строку**: 0a observer → 0b summary → 0c factcheck → 0d search → 0e youtube (:386-388) → 0f web → 0g checkup → 0h direct_chat → 0i voice_transcription → … → 4e video_download (:457-465, гейт `download_enabled`) → 5 slavik → 6 vasya. Расширяется ТОЛЬКО внутренняя логика хендлеров/сервисов и DI-вызовы внутри on_startup.
- **YouTube-URL-ветка для mode=summary** (`handlers/youtube.py` `_parse`/каскад/cache/🗿/5.x) — байт-в-байт для немедиа-запросов. Меняется только: запрос с «транскрипт» (см. T-690) получает субтитры-текст вместо каскада.
- Кружочки/голосовые (0i) и их формат/автор/память — не трогаем; новые ветки 0e НЕ матчат voice/video_note.
- Реакции Славик/Вася/Оля/common/dead page — не трогаем. Скачивание 4e (триггеры «скачай») — не трогаем (никаких новых веток в 4e).
- `APP_VERSION` не меняем. Существующие pg-ключи/env не переименовываем; секреты только в `.env`/`.env.example`-заметка.
- Полный pytest — 0 failed; `git diff --check` чист.

## 2. Требования (Requirements)

### Функциональные — Часть B (видео-пайплайн)

- FR-B1 (публикация). Новый модуль `services/media_share.py`: `publish_media_file(src_path) -> ShareTicket(file_id, rel_url, abs_url)` — атомарная публикация копией в `MEDIA_SHARE_DIR` под именем `{uuid}.{ext}` (uuid4 hex, ext из исходника в белом списке `mp4/webm/mov/mkv/avi`), попутная ленивая чистка файлов старше TTL; `sign(file_id, expires_ts) -> str` — HMAC-SHA256; `build_media_url(...) -> str` — относительный `/media/{file_id}?e={exp}&s={sig}`; `delete_file(file_id)` — best-effort; `cleanup_expired()` — на старте. Публикация **отключена** при пустом `MEDIA_SHARE_SECRET` (все вызовы — no-op c WARNING-логом; видео-пайплайн честно деградирует на STT-путь).
- FR-B2 (эндпоинт). В `web/app.py` (фабрика `create_app`) — `GET /media/{file_id}` с query `e`, `s`: `file_id` строго по маске `[0-9a-f]{32}\.(mp4|webm|mov|mkv|avi)`; проверка подписи `hmac.compare_digest` и срока; файл найден → `FileResponse` с `media_type` по расширению, `Content-Disposition: inline; filename={file_id}`; битая подпись/просрочка → 403; файла нет → 404; мусорный file_id → 404 (не 500, без traversal). Эндпоинт НЕ под TMA-авторизацией (безопасность — подпись+TTL+случайный id).
- FR-B3 (маршрутизация). Хендлер 0e расширяется классификацией запроса. Порядок приоритетов: (1) YouTube-URL (текст вызова ИЛИ reply-таргета, `extract_youtube_video_id`, D126-семантика сохраняется) → kind=youtube; (2) прямая медиа-ссылка (`tools.video_downloader.is_direct_media_url`) → kind=direct_url; (3) известная платформа (`_is_platform_url`: tiktok/instagram/vk/…, dot-граница) → kind=platform_url; (4) нативное медиа (video/document-video на вызове или reply, `_resolve_video_media`, voice/video_note НЕ квалифицируются) → kind=native; (5) ничего → UNHANDLED (пропагация живёт). Триггер остаётся прежним substring-правилом по тексту/caption вызова (`_has_trigger`).
- FR-B4 (mode). «транскрипт» в тексте вызова (substring) → mode=transcript; иначе mode=summary (семантика «самый специфичный запрос», прецедент Части 1).
- FR-B5 (матрица поведения, kind × mode):
  - youtube+summary — текущий `summarize_cascade` L1/L2/L3 без изменений.
  - youtube+transcript — `engine.fetch_transcript(video_id, cap≈20000)`; недоступность → скачивание yt-dlp (существующий `VideoDownloader`, качество 360) → STT; STT пуст → фраза; выдача форматом 3.3.
  - direct_url+summary — мультимодалка L1/L2 **напрямую** по внешней ссылке; провал уровня/недоступность → скачать `download_direct` → опубликовать → L1/L2 по `/media/` URL → провал → STT → честная выжимка/фраза.
  - direct_url+transcript — скачать `download_direct` → STT → текст кружков; скачать нельзя → фраза.
  - platform_url+summary — скачать «в тихую» (VideoDownloader, качество 360, без probe-меню) → опубликовать → L1/L2 → STT-фолбек.
  - platform_url+transcript — скачать → STT → текст.
  - native+summary — fetch_media_to_tmp → опубликовать → L1/L2 по `/media/` → фолбек: STT → если транскрипт содержателен (порог 3.4) → выжимка по транскрипту; иначе честная фраза.
  - native+transcript — fetch_media_to_tmp → STT → текст кружков.
- FR-B6 (лимиты). Нативные медиа — существующие гейты ДО скачивания (`video_transcribe_max_size_mb` 50 / `video_transcribe_max_duration_seconds` 600). Ссылочные источники — лимиты downloader'а (`VD_MAX_BYTES`/`DownloadTooBigError` и пр.); длительность неизвестна → не блокируем, решает каскад. Публикация — потолок `MEDIA_SHARE_MAX_MB` (по умолчанию 200): файл больше → публикация no-op + WARNING (fallback на STT, где применимо).
- FR-B7 (память). Двойная инъекция для всех успешных видео-путей как у voice: `update_smart_message_text` (только native — там есть строка-носитель медиа с плейсхолдером) + `memorize_facts` c `wrap_media_fact(media_type="video", …)` и `source_type="video_transcript"`. Для URL-режимов L1-обновление не делается (текст запроса — не плейсхолдер), факт-инъекция — да. Сбои памяти — WARNING, ответ не роняем.
- FR-B8 (транскрипт-формат). Выдача mode=transcript единообразна для всех kind: первая часть — `parse_mode=HTML`, «<b>{имя}</b> {«(переслал X)» для форвардов} 🗣: <i>{текст}</i>» реплаем на целевое сообщение (эталон кружков `voice_transcription.py:202-215` и `_resolve_transcript_author`, `media_common.py:40-59`); текст длиннее лимита → чанкинг (см. 3.3). Из выдачи mode=transcript исключены выжимка/фразы-пулы LLM — ТОЛЬКО текст (+память по FR-B7).
- FR-B9 (честная выжимка). `summarize_transcript` (выжимка по текстовой расшифровке) вызывается ТОЛЬКО при `len(transcript.strip()) >= limits.video_summary_min_chars` (дефолт 100). Иначе — фразы нового пула «в ролике нет разборчивой речи» (стиль пулов, без пересечений; тест на непересечение). RAG-подмес (`get_rag_context`) из user-контента **файловых** выжимок убирается полностью (источник «о чём видео» — только транскрипт/видео). YouTube-каскад (L1/L2/L3-субтитры) — RAG оставляем как есть (вне скоупа, fail-open прежний).
- FR-B10 (STT-надёжность). (а) `VoiceTranscriber.transcribe_voice(..., timeout=…)` — таймаут параметризуем: видео-вызовы передают `limits.video_stt_timeout_seconds` (дефолт 120), голосовые — прежний путь (10/15). (б) Размерные гейты провайдеров: файл больше `stt_groq_max_upload_mb` (25) → Groq-стратегия skipped с логом; больше `stt_openrouter_max_upload_mb` (20) → OpenRouter skipped (защита от HTTP 400 base64-пакетов); обе пусты → `TranscriptionUnavailable` → фраза. (в) Один повтор стратегии на транзиентные таймауты/5xx/транспорт (backoff 2с) — на уровне `VoiceTranscriber`, голосовые тоже (редкий путь, не влияет на типичную латентность).

### Функциональные — Часть C («сцуко»)

- FR-C1 (анти-залипание якорей). `_build_style_anchors`: выборка расширенного пула последних ответов (count + lookback 5); если ≥2 кандидатов из последних `count` начинаются с одного и того же первого слова (нормализация: lower, без пунктуации, длина ≥3) — такие ответы исключаются из якорей (выбираются более старые различные; не осталось ни одного → секции нет). Текст-инструкция секции заменяется: «вот твои недавние ответы, держи общую интонацию, но НЕ копируй дословно и не начинай каждый ответ с одного и того же слова:». Код + тесты.
- FR-C2 (TTL bot_direct_reply). Кодовый дефолт `settings.CHAT_DIRECT_REPLY_TTL_DAYS = 30` (сейчас None); `.env` оверрайдит (пусто → дефолт 30, явный `0` в PG/.env = вечно, уважается); `param_catalog.py:598`-дефолт 30; применение — существующее в `summary_memory.py:1229-1232`; backfill существующих NULL-фактов (`origin='bot_direct_reply' AND expires_at IS NULL` → `expires_at = created_at + 30*86400`), идемпотентный, на старте. Тест: новое памятование получает expires_at по дефолту; .env-оверрайд работает.
- FR-C3 (@DevOps прод-чистка): бэкап БД; `DELETE` graph_facts + bot_replies c «сцуко»; verify до/после. (задача T-698).
- FR-C4 (@PM отчёт): причина + фиксы + логи-наблюдения. (задача T-699).

### Функциональные — Часть D (BetterStack)

- FR-D1 (диагностика на старте). После `basicConfig` (bot.py:104-116), до создания сервисов: `logger.info("[logtail] attached | token_len=%d | logtail=%s", len(token), version)` при токене; при отсутствии токена — `logger.warning("[logtail] skipped (no LOGTAIL_SOURCE_TOKEN)")`. Версия — `importlib.metadata.version("logtail-python")` в try/except. Единая инициализация (модульный импорт — один раз), дублей нет.
- FR-D2 (завершение). В конце `main()` (после `on_shutdown()`/`cache.close()`, в `finally` блока сервера) — попытка мягкого закрытия логов: `logger.info("[logtail] shutdown flush")` + `logging.shutdown()` в try/except с комментарием-предупреждением (см. 3.8). Без гарантий при SIGKILL (TimeoutStopSec — DevOps, T-701).

### Нефункциональные

- NFR-1. Юзер не видит промежуточных ошибок (STT/скачивание/публикация/мультимодалка) — только итог или существующие фразы/молчание; трейсбеки только в лог.
- NFR-2. Временные файлы: публикация строго TTL (дефолт 15 мин) + удаление сразу после обработки + ленивая чистка каталога при публикации и на старте; каталог не копится. Скачивание во временные файлы — удаление в `finally` на 100% путей (прецедент).
- NFR-3. Безопасность /media: uuid-имена, HMAC-подпись (секрет только в env, R17: НЕ логируется, НЕ в логах URL с подписью), TTL, белый список расширений, отсутствие path-traversal (маска file_id), каталог публикации вне web-статики.
- NFR-4. Тайминги: мультимодальный уровень ≤ `models.video_timeout_seconds` (120), STT-стратегия ≤ `limits.video_stt_timeout_seconds` (120); суммарно видео-ветка не «висит» дольше ~5-6 минут (каскад таймаутов + LLM-выжимка с собственными таймаутами).
- NFR-5. `media_share`-функции не блокируют event loop (копирование/удаление — `asyncio.to_thread`).
- NFR-6. Изоляция роутеров (0e vs 0f/0g/0h/0i/4e/реакции) — тесты по образцу `test_epic37_router_isolation.py`; порядок bot.py — диф-проверка.
- NFR-7. Фразы-пулы раунда не пересекаются ни между собой, ни с существующими (тест).
- NFR-8. Пустой `MEDIA_SHARE_SECRET`/выключенная публикация = честный fallback на STT (и фразы) БЕЗ падений и WARNING-спама.

## 3. Технический дизайн

### 3.0 Новые настройки и REGISTRY

`config/settings.py` (блок рядом с `VIDEO_TRANSCRIBE_*`, ~:727-732):

```python
# ── Публикация временных медиа для мультимодалки (раунд 3, T-687) ──
# Секрет подписи /media-URL. ПУСТО = публикация ОТКЛЮЧЕНА (fallback на STT).
# Отдельный env (R17): НЕ деривим от API_TOKEN/LLM-ключей.
MEDIA_SHARE_SECRET: str = os.getenv("MEDIA_SHARE_SECRET", "")
MEDIA_SHARE_DIR: str = os.getenv("MEDIA_SHARE_DIR", "media/share")
# TTL опубликованного файла, сек; <60 → дефолт 900 (WARNING).
MEDIA_SHARE_TTL_SECONDS: int = _env_int_min("MEDIA_SHARE_TTL_SECONDS", 900, 60)
# Внешний базовый URL для сборки абсолютного video_url (отдаёт Caddy → FastAPI).
MEDIA_PUBLIC_BASE_URL: str = _env_str("MEDIA_PUBLIC_BASE_URL",
                                       "https://admin-bot.duckdns.org")
# Потолок публикации: файл больше → не публикуем (WARNING; fallback STT/фраза).
MEDIA_SHARE_MAX_MB: int = _env_int("MEDIA_SHARE_MAX_MB", 200)

# ── Видео-выжимка и STT (раунд 3, T-689/T-691/T-692) ──
# Таймаут ОДНОЙ STT-стратегии для видео-файлов (перекрывает groq/openrouter
# таймауты на вызов; голосовые НЕ трогают).
VIDEO_STT_TIMEOUT_SECONDS: float = _env_float_min("VIDEO_STT_TIMEOUT_SECONDS", 120.0, 5.0)
# Мин. длина транскрипта для «честной выжимки» (иначе фраза «нет речи»).
VIDEO_SUMMARY_MIN_CHARS: int = _env_int_min("VIDEO_SUMMARY_MIN_CHARS", 100, 1)
# Размерные гейты STT-провайдеров (Builder сверяет с фактическими лимитами
# ДО деплоя): Groq upload ~25МБ; OpenRouter input_audio base64 — консервативно 20МБ.
STT_GROQ_MAX_UPLOAD_MB: int = _env_int("STT_GROQ_MAX_UPLOAD_MB", 25)
STT_OPENROUTER_MAX_UPLOAD_MB: int = _env_int("STT_OPENROUTER_MAX_UPLOAD_MB", 20)
```

`services/param_catalog.py` — новые записи REGISTRY (формат строк списков как в файле):

| settings_field | pg_key | категория | группа | secret |
|---|---|---|---|---|
| `MEDIA_SHARE_SECRET` | `keys.media_share_secret` | keys | новая `keys_media` | **true** |
| `MEDIA_SHARE_DIR` | `content.media_share_dir` | content | `content_media` (новая) | — |
| `MEDIA_PUBLIC_BASE_URL` | `content.media_public_base_url` | content | `content_media` | — |
| `MEDIA_SHARE_TTL_SECONDS` | `limits.media_share_ttl_seconds` | limits | `limits_media` | — |
| `MEDIA_SHARE_MAX_MB` | `limits.media_share_max_mb` | limits | `limits_media` | — |
| `VIDEO_STT_TIMEOUT_SECONDS` | `limits.video_stt_timeout_seconds` | limits | `limits_media` | — |
| `VIDEO_SUMMARY_MIN_CHARS` | `limits.video_summary_min_chars` | limits | `limits_media` | — |
| `STT_GROQ_MAX_UPLOAD_MB` | `limits.stt_groq_max_upload_mb` | limits | `limits_media` | — |
| `STT_OPENROUTER_MAX_UPLOAD_MB` | `limits.stt_openrouter_max_upload_mb` | limits | `limits_media` | — |

Сид автоматический (pg_db `ON CONFLICT DO NOTHING`). Обновить `test_param_catalog.py`: `test_settings_field_count` 253 → 262, `len(GROUPS)` 61 → 63, counts категорий (+keys/content/limits). `.env.example` — +строки с комментариями (значение секрета НЕ коммитим).

### 3.1 Подсистема публикации — `services/media_share.py` + эндпоинт в `web/app.py`

#### Почему отдельный каталог, а не раздача из `docker/telegram-bot-api`

Файлы локального Bot API — вся медиа-история бота (чужие документы/фото/видео), раздавать их наружу нельзя. Публикуем ТОЛЬКО точечно скачанные видео с коротким TTL; имя файла = случайный uuid — никакой привязки к file_id Telegram.

#### Модуль `services/media_share.py`

```python
_EXT_WHITELIST = frozenset({"mp4", "webm", "mov", "mkv", "avi"})
_SHARE_FILE_RE = re.compile(r"^[0-9a-f]{32}\.(mp4|webm|mov|mkv|avi)$")

@dataclasses.dataclass(frozen=True)
class ShareTicket:
    file_id: str          # "<uuid32>.<ext>"
    expires: int          # unix-ts
    sig: str              # hex HMAC-SHA256
    rel_url: str          # "/media/{file_id}?e={expires}&s={sig}"
    abs_url: str          # MEDIA_PUBLIC_BASE_URL + rel_url

def enabled() -> bool            # bool(secret)
def publish_media_file(src_path: str, ttl_seconds: int) -> ShareTicket | None
def sign(file_id: str, expires: int) -> str
def verify(file_id: str, expires: int, sig: str) -> bool   # hmac.compare_digest
def delete_file(file_id: str) -> None                      # best-effort, to_thread
def cleanup_expired(now: int | None = None) -> int         # ленивая чистка каталога
def build_media_url(file_id: str, expires: int) -> str
```

- `publish_media_file`: no-op при пустом секрете (WARNING `[media_share] disabled (no secret) — STT fallback`); ext из `Path(src_path).suffix`, не в белом списке → no-op; размер > `MEDIA_SHARE_MAX_MB` → no-op + INFO; копия `shutil.copyfile` в `asyncio.to_thread` в `MEDIA_SHARE_DIR/{uuid32}.{ext}` (каталог `mkdir(parents=True, exist_ok=True)`); перед копией — `cleanup_expired()` (удалить `*.{ext}` c mtime старше TTL); вернуть ticket.
- Имя файла-на-диске и `file_id` совпадают (`<uuid>.<ext>`) → эндпоинту не нужен реестр/индексация: `path = share_dir / file_id` при проверенной маске (traversal невозможен структурно).
- `sign`: `hmac.new(secret.encode(), f"{file_id}:{expires}".encode(), hashlib.sha256).hexdigest()`. `expires` = `int(time.time()) + ttl`.
- URL: `/media/{file_id}?e={expires}&s={sig}` (query, а не path-сегменты — проще для логов/проксирования; полный URL с `s=` НЕ логируем, R17).
- `delete_file` вызывается обработчиком в `finally` после мультимодального каскада (файл больше не нужен; TTL — страховка от падений/ретраев уровня).

#### Эндпоинт (в `create_app`, рядом с `@app.get("/")`):

```python
_EXT_MEDIA_TYPES = {"mp4": "video/mp4", "webm": "video/webm",
                    "mov": "video/quicktime", "mkv": "video/x-matroska",
                    "avi": "video/x-msvideo"}

@app.get("/media/{file_id}", include_in_schema=False)
async def media_file(file_id: str, e: str = "", s: str = ""):
    """Отдача опубликованного видео по подписанному URL (раунд 3, T-687).
    403 — битая подпись/просрочка; 404 — нет файла/мусорный id."""
    ...
    FileResponse(path, media_type=..., headers={"Content-Disposition":
        f'inline; filename="{file_id}"'})
```

Проверки: `file_id` против `_SHARE_FILE_RE` (иначе 404); `e` int и `int(time.time()) <= e` (иначе 403); `verify(...)` (иначе 403); `path.exists()` (иначе 404). Отдаёт uvicorn-сервер (127.0.0.1:8000) — наружу файл приходит через **Caddy** (`https://admin-bot.duckdns.org/media/*` → `127.0.0.1:8000`; конфиг Caddy НЕ в репо — маршрут добавляет @DevOps, T-704). Отдавать напрямую через Caddy-файловый модуль не требуется: проксирование на FastAPI достаточно (файл маленький: ≤200 МБ, TTL 15 мин).

#### Сборка абсолютного video_url для мультимодалки

`abs_url = MEDIA_PUBLIC_BASE_URL.rstrip("/") + rel_url` — передаётся в `OpenRouterVideoClient.summarize(video_url=…)`. Если публикация выключена (секрет пуст) или файл не опубликовался — уровни L1/L2 на `/media/` **пропускаются сразу** (лог `[video cascade] file publish unavailable — skip L1/L2`), без таймаутов 120с×2 → честный fallback STT.

### 3.2 Универсальный маршрутизатор видео-запроса (0e, `handlers/youtube.py`)

#### Классификация (новый модульный хелпер в `youtube.py`)

Триггер-проверка остаётся первой (как сейчас в `_parse`/`_resolve_video_media`). Классификация:

```python
@dataclasses.dataclass(frozen=True)
class _VideoRequest:
    kind: str            # "youtube" | "direct_url" | "platform_url" | "native"
    mode: str            # "summary" | "transcript"
    url: str | None      # для url-кидов (исходный, как ввёл юзер)
    media: _VideoMedia | None
    source: types.Message   # сообщение, на которое реплаим/с которого читаем
```

Псевдокод `_classify_video_request(message)`:

```
text  = message.text or message.caption or ""
if not _has_trigger(text): return None
reply = message.reply_to_message
# 1) youtube: D126-семантика _parse БЕЗ изменений (reply-таргет приоритетнее вызова)
video_id = extract_youtube_video_id(reply-текст) or extract_youtube_video_id(text)
if video_id: return kind=youtube (canonical URL не нужен — каскад работает по id)
# 2/3) НЕ-youtube URL: сначала текст вызова, затем reply-таргет (в порядке появления)
for src in (message, reply):
    if src is None: continue
    for url in _extract_urls(src.text or src.caption or ""):
        if is_direct_media_url(url): return kind=direct_url, url=url
        if _is_platform_url(url):    return kind=platform_url, url=url
# 4) нативное медиа (свой приоритетнее reply) — существующий _resolve_video_media
media = _resolve_video_media(message)   # (внутри уже _has_trigger)
if media: return kind=native
return None   # UNHANDLED
```

- `_extract_urls` — переиспользовать существующий извлекатель URL (`handlers/video_download.py` `_extract_urls`-эквивалент; если нет общего — маленький regex-хелпер в `services/smartmodule_urls.py`, без дублирования).
- Порядок `direct_url` vs `platform_url`: `is_direct_media_url` сам исключает платформы (FR-11 прошлого раунда) — порядок веток не важен, но пишем platform-проверку второй.
- mode: `want_raw = "транскрипт" in text.lower()` (по тексту вызова).

#### DI (бот.py, ВНУТРИ summary-блока, порядок регистрации роутеров не трогаем)

К существующему `setup_youtube_video_media(voice_service, db, aliases, memory, bot.id)` добавляется **общий** инстанс `VideoDownloader(settings.COBALT_API_URL, settings.DOWNLOAD_DIR)` (создаётся в summary-блоке рядом с voice_service; лёгкий, клиенты ленивые — D261) и медиа-шара: `setup_youtube_media_share(...)`/аргументы в тот же setup — downloader + `media_share`-функции. Ключевой момент: ссылочные ветки 0e НЕ гейтятся `flags.download_enabled` (это флаг фичи «скачай», 4e-регистрацию он не трогает; скачивание по ссылкам для пересказа — часть summary-функционала, локальный yt-dlp и cobalt — легитимные инструменты). Семафор-лок скачивания общий (один инстанс на процесс — гонок «скачай» + пересказ нет).

#### Потоки kind × mode (детали)

**youtube+summary**: `_parse`-путь целиком (cache по video_id, on_retry-нотификатор, каскад, 🗿) — байт-в-байт.

**youtube+transcript** (новое; заменяет прежнее «транскрипт <yt-url> = каскад-выжимка» — отметить в отчёте юзеру T-699):

```
1. engine.fetch_transcript(video_id, cap=_YT_TRANSCRIPT_CAP=20000, on_retry=None)
   → успех: выдача 3.3 (автор = юзер, задавший запрос)
2. YouTubeTranscriptUnavailableException → скачать: downloader.download(url, "360")
   (yt-dlp при YTDLP_FOR_YOUTUBE; иначе cobalt) → STT файла (timeout=120) →
   текст 3.3; пустой/недоступный STT → пул 5.11
3. память (FR-B7), smart_cache НЕ пишем
```

**direct_url+summary**:

```
1. L1/L2 на исходный внешний URL (canonical-каскад по video_id НЕ нужен):
   _service.summarize_media_url(video_url=url, ...)  # 3.2.1
2. Провал L1/L2 (VideoLevelError/empty/timeout обеих) →
   скачать downloader.download(url, "360")  # direct-ветка стримом внутри
   → publish_media_file → (публикация есть) L1/L2 на abs_url /media/
   → всё ещё пусто/провал → STT файла → честная выжимка (3.4) / фраза
3. публикация недоступна (нет секрета) → пропуск пункта L1/L2-на-/media/,
   сразу STT-фолбек
```

**platform_url+summary**: как direct_url+summary, но без шага «L1/L2 на внешний URL» (платформенный URL мультимодалке обычно недоступен/требует сессии) — сразу скачивание → публикация → L1/L2 → STT-фолбек.

**platform_url/direct_url+transcript**: скачивание (как выше) → STT (timeout 120) → текст 3.3; `DownloadTooBigError`/`DownloadUnavailableError`/`DownloadBusyError`/сеть → пул 5.11; EmptyTranscript → пул 5.12.

**native+summary** (расширение Части 1): fetch_media_to_tmp (гейты 50МБ/600с до скачивания, прежние) → `publish_media_file(tmp)` → если опубликован: L1/L2 на `/media/` abs_url (обёртка-каскад 3.2.1 с `video_id="tg-file"`), успех → выдача; провал/пусто → STT (прежний каскад) → честная выжимка 3.4. Не опубликован (нет секрета/слишком большой/не тот ext) → сразу прежний STT-путь Части 1. Триггер «транскрипт» → mode=transcript → прежний STT → текст 3.3.

**native+transcript** (замена plain-выдачи Части 1 на HTML 3.3; STT-логика прежняя).

Все ветки: кулдаун общий (touch ДО обработки, как сейчас), консьюм на 100% путей, `LLMBadResponseError` → 🗿-молчание, `LLMError` → `LLM_ERROR_PHRASES`, неожиданное → logger.exception + фраза. Мультимодалка файла использует **тот же** `OpenRouterVideoClient` (общий с YouTube-каскадом) — доступность/ключ/таймаут уже едины.

#### 3.2.1 `YoutubeSummarizerService.summarize_media_url` (новый метод; `summarize_cascade`/`summarize`/`summarize_transcript` НЕ меняются)

```python
async def summarize_media_url(self, *, chat_id: int, video_url: str,
                              label: str = "tg-file") -> str:
    """L1→L2 мультимодального каскада по ПРОИЗВОЛЬНОМУ video_url
    (опубликованный файл / прямая ссылка). Субтитров (L3) нет — провал
    обеих моделей = VideoLevelError-семейство наружу (хендлер делает STT-
    фолбек). RAG-контекст НЕ подмешивается (B5: честная выжимка)."""
```

Механика — копия цикла уровней `summarize_cascade` (:84-145): system = `YOUTUBE_VIDEO_SYSTEM_PROMPT.replace("{max_symbols}", …)`, user = `<video_id>{label}</video_id>\n\nпосмотри ролик по ссылке и перескажи, что в нём происходит.` (без RAG-префикса), `video_client.summarize(model=…, video_url=…, …)`; таймаут уровня/`asyncio.wait_for` те же; `VideoLevelError`/пусто → на следующий уровень; обе пусты → проброс последней ошибки (или кастомного `VideoLevelError("file cascade empty")`) — хендлер ловит и деградирует на STT. Логи: `[video cascade] file OK | level=…` / WARNING-причины (URL/подпись не логируются — R17; в логах только `file_id`-хвост).

### 3.3 Формат «транскрипт» (как у кружков) + чанкинг

Единый рендер в новом чистом хелпере `handlers/media_common.py` (переиспользуется всеми ветками; поведение кружков 0i не трогаем):

```python
def format_transcript_html(name: str, text: str,
                           forwarder: str | None = None) -> str:
    """D268/D272-эталон: '<b>{name}</b> {(переслал {f})} 🗣: <i>{text}</i>'.
    html.escape для всех полей; якорь детектора 74.C («🗣:») сохраняется."""
```

- Имя автора: **native** — `_resolve_transcript_author(source)` (форвард → автор источника + «(переслал {переславший})», как в кружках `voice_transcription.py:207-213`); **ссылочные kind** — автор запроса (каскад AliasResolver от `message.from_user`, без «(переслал)»).
- Чанкинг: `_MAX_TG_TEXT = 4096`. Первая часть — реплаем на целевое сообщение (медиа/ссылочный пост), содержит лейбл + `<i>`-текст (весь чанк внутри `<i>`, текст эскейпится ПОСЛЕ резки по границе ~4030 символов, резка — по последнему пробелу/переносу). Части 2+ — обычные `send_chunked_reply`-части (plain), РЕПЛАЕМ только первая (прецедент send_chunked_reply Части 1). Обрезка html-разметки на стыках чанков невозможна, т.к. каждый чанк экранируется/оборачивается отдельно.
- Изменение против Части 1: `want_raw` native-ветка больше НЕ шлёт plain «Имя 🗣:\nтекст», а шлёт HTML-первую часть (детектор реплаев direct_chat 74.C смотрит на plain-текст цели — «🗣:» присутствует, прежний формат-якорь цел).
- Память (FR-B7): L1-обновление строки — только для native (там строка медиа); для ссылочных — пропуск L1 с INFO-логом. GraphRAG-факт — всегда (после фикса B7 CHECK).

### 3.4 Честная выжимка (B5)

- `services/youtube_summarizer_service.py::summarize_transcript` (файловая выжимка): убрать `rag_query`-подмес (`get_rag_context`) из user-контента; user = `<video_id>tg-file</video_id>\n\n<transcript>…</transcript>`; сигнатура упрощается (`summarize_transcript(*, chat_id, transcript)`) — правятся вызовы в `youtube.py`. (Youtube-каскад `summarize_cascade`/`summarize` RAG оставляют как есть.)
- В `handlers/youtube.py` — общий гейт перед выжимкой по транскрипту:
  `if len((transcript or "").strip()) < min_chars: → VIDEO_NO_SPEECH_PHRASES` (consume). `min_chars = hot.get("limits.video_summary_min_chars", settings.VIDEO_SUMMARY_MIN_CHARS)`.
- Это же правило применяется в direct_url/platform_url/native summary-фолбеках ПОСЛЕ STT (мультимодальный успех L1/L2 фразу не требует — модель видела видео/кадры).

Фразы (`services/smartmodule_phrases.py`, 5.13 — после 5.12; все строчные, без пересечений с 5.9-5.12 и остальными):

```python
# 5.13 — «немое» видео: речь есть, но для честной выжимки недостаточна
VIDEO_NO_SPEECH_PHRASES: tuple[str, ...] = (
    "в ролике почти нет речи, пересказывать нечего",
    "пара слов на весь видос — выжимку строить не из чего",
    "разборчивой речи в видео нет, я пас на пересказ",
)
```

### 3.5 STT: таймауты и HTTP 400 (T-692)

Проверено в коде: `VoiceTranscriber.transcribe_voice` (SmartModule/service.py:74-96) — per-strategy `asyncio.wait_for(strategy.transcribe(...), timeout=strategy.timeout)`; `GroqTranscriber.timeout`/клиент — `hot models.groq_timeout` (дефолт `settings.GROQ_TIMEOUT` **10.0**, settings.py:736); `OpenRouterTranscriber.timeout` — `models.openrouter_timeout` (дефолт **15.0**, settings.py:746). Клиент AsyncOpenAI строится с этим же timeout → httpx-рид-таймаут равен стратегии, поэтому «перекрыть» можно только на уровне вызова SDK.

Дизайн:
- `BaseTranscriber.transcribe(file_path, *, timeout: float | None = None)` (оба транскрайбера): `timeout` прокидывается в `client.audio.transcriptions.create(..., timeout=timeout)` / `client.chat.completions.create(..., timeout=timeout)` (SDK поддерживает per-request timeout). Существующий `self.timeout` остаётся дефолтом для голосовых (вызовы 0i не меняются).
- `VoiceTranscriber.transcribe_voice(file_path, audio_format, *, timeout: float | None = None)`: effective = timeout or strategy.timeout; `wait_for(strategy.transcribe(..., timeout=effective), timeout=effective)`. Видео-ветки вызывают `transcribe_voice(path, "mp4", timeout=hot video_stt_timeout)` — 120с дефолт.
- **Размерные гейты ДО запроса** (в цикле стратегий, до `strategy.transcribe`): `os.path.getsize(path) > mb*1024*1024` → стратегия skipped (`logger.warning("[transcribe] %s skipped (file %d MB > limit %d MB)", …)`). Обе skipped → `saw_failure=False` → `EmptyTranscript` НЕ подходит (файл не пуст) → поднимаем `TranscriptionUnavailable` напрямую (ветка фразы 5.11). Голосовые (ogg, ≤600с, <10МБ) гейты не заденут.
- HTTP 400 OpenRouter: вероятная причина — слишком большой base64 JSON (m4a-объявление корректно, `openrouter_transcriber.py:87-100`) и/или перегрузка free-моделей. Лечим гейтом выше + оставляем retry-роутер (403/400 → повтор openrouter/free). Если 400 сохранится на файлах ≤20МБ — Builder фиксирует в отчёте (открытый вопрос 1): возможно, потребуется вторая попытка с пустым форматом или строка «аудио недоступно».
- **Ретрай-политика**: Groq уже ретраит 429 (внутренний backoff, max 3). Добавляем ОДИН повтор на уровне стратегии-цикла `VoiceTranscriber` при транзиентных `asyncio.TimeoutError`/5xx/транспорте (backoff 2.0с) — «1 стартовая + 1 повтор», прецедент `video_cascade_client.py` (`_LEVEL_RETRY_BACKOFF`). Итог для юзера: 03:21-сценарий теперь = Groq 120с (реальный шанс на длинное видео) → OpenRouter (≤20МБ) → фраза только при полном провале.
- Человечные фразы для размерных лимитов файлов уже есть (5.10 «50 мб» — нативный гейт); ссылочный файл, скачанный больше 50МБ (STT-лимит), → пул 5.10/5.11 (см. 4).

### 3.6 Баги памяти (T-693/T-694)

#### B7 — CHECK `graph_facts.origin` (T-693)

Проверено: constraint живёт в **SQLite**-схеме (`services/database.py:146-148` CREATE + пересоздание в `_migrate_direct_chat_v2` :299-314, guard `"bot_direct_reply" not in row["sql"]`). PostgreSQL-схемы graph_facts СЕЙЧАС НЕТ (`pg_db.py` — только bot_settings/bot_roles/bot_admins/uptime_events); эпик 86 «GraphRAG→PG» — будущий, при его реализации origin-список синхронизировать (заметка в коде/README). В списке отсутствуют `voice_transcript` И `video_transcript` → инъекции кружков (Epic 67!) и видео молча скипаются (`summary_memory.py:1311-1316` per-fact except, `saved=0 skipped=N`).

Фикс (по D201-паттерну, id сохраняются → FTS/vec валидны):

1. `_SCHEMA_SQL` CREATE TABLE: origin IN (…, 'bot_direct_reply', 'voice_transcript', 'video_transcript') — новый полный список в одном месте (константа `_GRAPH_FACT_ORIGINS_SQL`).
2. Новая идемпотентная миграция `_migrate_video_origins_v4` (вызов в `initialize()` после `_migrate_epic60_v3`; константа `_SCHEMA_VERSION_VIDEO_ORIGINS = 4`):
   - guard: `SELECT sql FROM sqlite_master … name='graph_facts'`; если `"video_transcript" not in row["sql"]` → пересоздание с сохранением ВСЕХ колонок (id, chat_id, fact, origin, expires_at, created_at, target_user, weight, status, last_confirmed_at, supersedes — статусы/веса из Epic 60 добавлялись отдельными ALTER, в rebuild включаем) + `INSERT … SELECT` + DROP old + индексы `idx_graph_facts_chat_origin`, `idx_graph_facts_target_user`;
   - `PRAGMA user_version = 4`. Повторный запуск — no-op (guard + PRAGMA).
   - FTS5 `graph_facts_fts` НЕ пересоздаётся (content-таблица пересоздана с теми же rowid — прецедент D201; content='graph_facts' резолвится динамически).
3. Тест: старая схема (без origins) → initialize → в sqlite_master.sql есть 'video_transcript'; INSERT origin='voice_transcript' и 'video_transcript' успешны; id существующих фактов сохранены; факт попадает в `get_rag_context`.

#### B8 — «smart_message row not found» (T-694)

Проверено: observer 0a (`handlers/summary.py:157-212`) сохраняет сообщение с `media_type='video'` (текст может быть None) и `tg_message_id`, НО пропускает: (а) сообщения самого бота (`user.id == _bot_id`, :166-167 — репосты каналов/деад-пейджей ботом); (б) апдейты без `from_user` (канальные посты); (в) сообщения, уже ушедшие из L1-окна (сжатие/ретенция 30 дней) — «реплай на старое видео». Именно (а) — массовый кейс группы (видео-репост канала ботом).

Решение (точное): в `_inject_video_memory` (handlers/youtube.py:228-257) и НЕ меняя `update_smart_message_text` (database.py:727-755):

```
updated = await _media_db.update_smart_message_text(chat_id, source.message_id, transcript)
if not updated:
    # Причина (лог): бот-репост / канал / строка ушла в архив (ретенция).
    # Создаём строку ТОЛЬКО если сообщение принадлежит реальному юзеру
    # (не боту): контент юзера должен оставаться FTS-искомым (прецедент D267).
    user = source.from_user
    if user is not None and user.id != _media_bot_id:
        await _media_db.save_smart_message(
            user_id=user.id, chat_id=chat_id, text=transcript,
            reply_to_id=..., timestamp=int(source.date.timestamp()),
            media_type="video", author_name=<резолв как в observer>,
            is_forward=origin is not None,
            forward_source=..., message_id=source.message_id)
        logger.info("[youtube] smart_message row created (missing) | chat=… msg=…")
    else:
        logger.info("[youtube] smart_message row not found (bot/canal media) — skip L1")
# GraphRAG-факт — безусловно (после B7-фикса)
```

Никаких молчаливых падений: INFO/дебаг-причина в логе на каждом исходе; исключения — WARNING, поток жив. Тест: (1) существующая строка — update; (2) строки нет, from_user юзер — создана новая (методы save/mock); (3) строки нет, from_user = бот — skip + факт-инъекция всё равно вызвана; (4) отсутствие tg_message_id в save — не ломает.

### 3.7 «Сцуко» (T-696/T-697)

#### C1 — анти-залипание `_build_style_anchors` (direct_chat_service.py:534-556)

```python
_STYLE_ANCHOR_LOOKBACK = 5   # буфер выборки поверх count (ищем «разные» якоря)
_STICKY_MIN_WORD_LEN = 3     # короче — не считаем «словом-префиксом» (a/и/в…)

@staticmethod
def _normalize_first_word(text: str) -> str:
    """lower, обрезка пунктуации хвоста, длина >= _STICKY_MIN_WORD_LEN → слово."""
    m = re.match(r"\s*([а-яёa-z0-9]+)", str(text).lower())
    return m.group(1) if m else ""

async def _build_style_anchors(self, chat_id: int) -> str:
    """…; анти-залипание: если >=2 из последних `count` ответов начинаются с
    одного слова — такие НЕ попадают в якоря (более старые различные или "")."""
    if not enabled: return ""
    count = hot limits.chat_style_anchors_count (>=1)
    replies = await self.db.last_bot_replies(chat_id, count + _STYLE_ANCHOR_LOOKBACK, time.time())
    if not replies: return ""
    selected = []
    used_prefixes: set[str] = set()
    sticky_prefixes = _detect_sticky(replies[-count:])   # префиксы с частотой >=2
    for text in reversed(replies):                        # от свежих к старым
        if len(selected) >= count: break
        first = self._normalize_first_word(text)
        if first and (first in sticky_prefixes or first in used_prefixes):
            continue                                       # залипший/повтор
        used_prefixes.add(first)
        selected.append(text)
    if not selected: return ""                             # секции нет (см. edge)
    body = "\n".join(f"{i}. {t[:anchor_cap]}"
                     for i, t in enumerate(reversed(selected), 1))  # хронология ASC
    return f"<style_anchors>\nподражай общей интонации этих ответов, "
           f"но НЕ копируй дословно и не начинай каждый ответ с одного и того "
           f"же слова:\n{body}\n</style_anchors>"
```

- `_detect_sticky(window)`: Counter первых слов; вернуть {w: cnt ≥ 2}.
- Шаблон секции меняется байт-в-байт (новая строка-эталон в тестах). Раньше 14/16 ответов со «сцуко,» — теперь такой ответ (и второй с тем же префиксом) исключается из якорей; модель получает либо разнообразные якоря, либо ничего.
- Побочный эффект: последний ответ со «сцуко,» НЕ исключается, если префикс встретился 1 раз — НЕ «запрет мата», а только де-залипание (требование).

#### C2 — TTL bot_direct_reply (T-697)

- `config/settings.py:493`: `CHAT_DIRECT_REPLY_TTL_DAYS: int | None = _env_int_optional("CHAT_DIRECT_REPLY_TTL_DAYS", 30)` (комментарий: «0 = вечно; пусто/отсутствие → 30»).
- `services/param_catalog.py:598`: дефолт 30.
- `summary_memory.py:1229-1232` — код уже читает `hot.get("limits.chat_direct_reply_ttl_days", settings.CHAT_DIRECT_REPLY_TTL_DAYS)`; `or 0` сохраняется (0/None → expires_at NULL). Логика не меняется.
- **Миграция прод-значения PG**: по образцу `migrate_direct_chat_prompt_if_legacy` (chat_prompts.py:47-66) — функция `migrate_direct_reply_ttl_default(cache)` в `services/summary_memory.py` (или chat_prompts.py, duck-typed cache): ключ `limits.chat_direct_reply_ttl_days` отсутствует → no-op (сид поставит 30); значение `None`/пусто (легаси-сид) → `cache.set(key, 30, "limits")`; значение `0` или число (явный выбор/уже мигрировано) → не трогаем. Вызов в `bot.py::main()` рядом с prompt-миграцией (:540-544). PG down → skip (R6).
- **Backfill существующих фактов** (NULL → expires_at): новая идемпотентная функция `MemoryManager.backfill_direct_reply_ttl()` — `UPDATE graph_facts SET expires_at = min(created_at + ttl*86400, <now>) WHERE origin='bot_direct_reply' AND expires_at IS NULL` при ttl>0; запуск из on_startup (в summary-блоке после DI памяти, fire-and-forget/await — короткий); лог `[graphrag] bot_direct_reply backfill | rows=%d`. Повторный старт безвреден (NULL-строк больше нет).
- Результат: новые bot_direct_reply-факты живут ~30 дней (expiry учитывается в RAG-чтениях — уже реализовано), «сцуко»-факты старше 30 дней умирают сами; точечная чистка — T-698.

### 3.8 BetterStack (T-700/T-701)

Код — только диагностика + мягкое завершение:

1. **Старт** (bot.py, сразу после `logging.basicConfig` :115; в коде блок стоит ПОСЛЕ подключения `log_ring` :135-142 — fix-round 04.09 M3: маркер обязан попасть и в `/api/status/logs`, поэтому порядок «attach log_ring → маркер»):

```python
logtail_version = "?"
try:
    from importlib import metadata as _md
    logtail_version = _md.version("logtail-python")
except Exception:
    pass
if logtail_token:
    logger.info("[logtail] attached | token_len=%d | logtail=%s",
                len(logtail_token), logtail_version)
else:
    logger.warning("[logtail] skipped (no LOGTAIL_SOURCE_TOKEN)")
```

   (Маркер пишется и в консоль, и в log_ring → виден в journald и /api/status/logs — диагностика «слушает ли хендлер».)
2. **Завершение**: в `main()` финальный `finally` (:607-626) после `cache.close()`:

```python
logger.info("[logtail] shutdown flush")
try:
    logging.shutdown()   # close() всех хендлеров: logtail флашит очередь; НЕ
    # в on_shutdown/до выхода асинхронных задач (см. hotfix uvicorn dictConfig —
    # дефолтный dictConfig делал shutdown на СТАРТЕ и дедлочил флашер; здесь —
    # самый конец процесса, логов после нет).
except Exception:
    pass
```

   SIGKILL/TimeoutStopSec обойти нельзя (потеря буфера до 1000 событий — документированное поведение 0.4.0). Требование к @DevOps: мягкий restart (SIGTERM) на проде и **живой тест**: тестовое событие из-под учётки сервиса в `in.logs.betterstack.com`; проверить вкладку/тариф/источник (T-701). `uvicorn log_config=None`, уровень INFO, буфер 1000, raise_exceptions=False — НЕ меняем.
3. Наблюдаемость потерь без рекурсии: писать в logtail о потерях нельзя из самого хендлера; вместо этого маркеры «attached»/«skipped» + инструкция DevOps сверять `tail journalctl` vs BetterStack. `log_ring`-фильтр не трогаем.

### 3.9 Файлы-кандидаты изменений

| Файл | Изменение |
|---|---|
| `config/settings.py` | +9 полей (см. 3.0), дефолт `CHAT_DIRECT_REPLY_TTL_DAYS=30` |
| `services/param_catalog.py` | +9 REGISTRY-записей, 2 новых GroupSpec (`keys_media`, `content_media`), дефолт `limits.chat_direct_reply_ttl_days` 30 |
| `services/media_share.py` | **новый**: publish/sign/verify/delete/cleanup/build_media_url (3.1) |
| `web/app.py` | эндпоинт `GET /media/{file_id}` + маска/подпись/TTL/FileResponse (3.1) |
| `handlers/youtube.py` | классификатор `_classify_video_request`, матрица kind×mode (3.2), общий гейт честной выжимки (3.4), HTML-транскрипт (3.3), память-фолбек B8 (3.6), вызовы STT c timeout |
| `services/youtube_summarizer_service.py` | +`summarize_media_url` (3.2.1); `summarize_transcript` без RAG (3.4) |
| `services/youtube_prompts.py` | (без изменений — каноны переиспользуются) |
| `services/media_download.py` | (без изменений; переиспользуется) |
| `SmartModule/service.py` | `transcribe_voice(..., timeout=None)`, size-гейты провайдеров, +1 транзиентный повтор (3.5) |
| `SmartModule/transcriber/base.py`, `groq_transcriber.py`, `openrouter_transcriber.py` | `transcribe(..., timeout=None)` → per-request timeout; `max_upload_mb`-атрибут стратегии (3.5) |
| `services/database.py` | DDL origin-список + `_migrate_video_origins_v4` (user_version 4) (3.6) |
| `services/summary_memory.py` | +`backfill_direct_reply_ttl`; миграция дефолта TTL (3.7) |
| `services/chat_prompts.py` | (без изменений; образец миграции) |
| `services/direct_chat_service.py` | анти-залипание `_build_style_anchors` + новый шаблон секции (3.7) |
| `handlers/media_common.py` | +`format_transcript_html` (3.3) |
| `services/smartmodule_phrases.py` | +5.13 `VIDEO_NO_SPEECH_PHRASES` |
| `bot.py` | DI: общий VideoDownloader в summary-блоке; вызов `migrate_direct_reply_ttl_default`; старт-маркер logtail; финальный flush (порядок роутеров НЕ меняется) |
| `README.md`, `.env.example`, `plans/docs/memory-project-overview.md` | @DevOps-правки |

## 4. Пограничные случаи и решения (Edge cases)

- **«транскрипт» медиа-ветки меняет формат**: plain «Имя 🗣:\nтекст» Части 1 → HTML «<b>Имя</b> 🗣: <i>текст</i>» (3.3). Детектор direct_chat 74.C (якорь «🗣:») совместим (смотрит plain-представление). Обновить тесты Части 1 (test_youtube_video_media.py).
- **«транскрипт <youtube-url>» меняет поведение** (было: каскад-выжимка → станет субтитры-текст; при недоступных субтитрах — скачивание+STT). Отметить в отчёте юзеру (T-699). smart_cache при этом не пишется (кэш — только summary-результаты).
- **Мультимодалка по `/media/` требует публичного доступа OpenRouter к `admin-bot.duckdns.org`**: Caddy-маршрут добавляет @DevOps ДО live-теста (T-704). Пока маршрута нет/секрет пуст → L1/L2 на /media пропускаются сразу (лог) → STT-фолбек (медленно НЕ становится: таймаутов 120с×2 нет).
- **Публикация недоступна (секрет пуст)** при summary на нативном/платформенном видео → ровно поведение Части 1 (STT+выжимка/фраза); при этом короткий STT-текст (<100 символов) даёт честную фразу, а НЕ выжимку по памяти (B5 — поведение 02:45 исправлено даже без мультимодалки).
- **Прямые ссылки с защитой (403/реферер)**: `download_direct` уже ретраит с Referer; после исчерпания — пул 5.11. Мультимодалка «напрямую по ссылке» может упасть на 403 для CDN → это и есть сигнал к скачиванию (матрица B5, шаг 2).
- **Скачанный файл больше 50МБ/лимитов STT** (проверка после скачивания по `Path.stat().st_size`): mode=transcript → пул 5.10 (лимит размера); mode=summary → если публикация возможна (≤200МБ) — только мультимодалка, STT-фолбек с фразой 5.11 при пустоте. Гейт длительности для ссылок отсутствует (неизвестна) — принято (решает каскад). *(правка fix-раунд 04.09, M2/m6 — решение @Builder+@Reviewer для мержа: пул унифицирован — «слишком большой размер» ВЕЗДЕ 5.10 `VIDEO_MEDIA_TOO_BIG_PHRASES`, вкл. `DownloadTooBigError` downloader'а (в 3.2 он указан в 5.11 — расхождение решено в пользу 5.10: размерная фраза честнее; 5.11 — только «недоступно»: сеть/DRM/сервисы); summary-файл 50–200МБ НЕ отсекается от публикации → L1/L2 на /media (потолок 200МБ — внутри `publish_media_file`, M2), при пустоте мультимодалки — фраза 5.11; STT-путь для >50МБ невозможен структурно.)*
- **DownloadBusyError** (глобальный лок downloader'а занят «скачай»): мгновенная честная фраза пула 5.11 (не очередь/не блокировка хендлера).
- **YouTube-видео без субтитров + недоступное скачивание** (DRM/live/возраст): `DownloadUnavailableError` → пул 5.11; юзеру без трейсбеков.
- **Дубликат фактов** (тот же ролик: субтитры youtube_content + наш video_transcript): дедуп 64.1 (exact/KNN) сработает — не плодим.
- **Voice/video_note в 0e**: квалификация native — только video/document; кружки/войсы по-прежнему обслуживает 0i (не пересекаемся; тест-изоляция).
- **Видео И YT-ссылка в caption** (репост ролика): `_parse`/классификация ставит youtube выше native — медиа не качаем (структурно, как FR-2 Части 1).
- **Неизвестный URL (не youtube/direct/platform) + триггер**: UNHANDLED → пропагация (0f web/web-триггеры не пересекаются с `_YOUTUBE_TRIGGERS`; сообщение может дойти до 4e/других — их триггеры свои).
- **«немое» видео с музыкой, STT вернул мусор 10-40 символов**: `<100` → 5.13-фраза (никакой RAG-выжимки). Multimodal при этом успел: ответ L1/L2 строится по кадрам — это ок (визуал — реальный контент).
- **Очень длинные субтитры YouTube (mode=transcript)**: cap 20000 символов → ~5 чанков по 4096; текст в память — capped-версия (прецедент движка).
- **Опубликованный файл удалён до запроса OpenRouter** (редкая гонка TTL=900с ≫ каскад): 403/404 от `/media/` = VideoLevelError('status=403/404') → следующий уровень/фолбек STT — самоизлечимо.
- **`voice_transcript`-инъекции прошлых раундов молча скипались** (тот же CHECK): B7 чинит и кружочки — поведение voice НЕ меняется, но факты начнут реально сохраняться (тест).
- **Секция style_anchors пуста** после фильтрации (все ответы залипли одним словом): секция не строится (безопаснее, чем слать модель-«попугая»); поведение «пустого» варианта = как при выключенном флаге.
- **Юзер явно поставил TTL=0 (вечно)**: миграция C2 его не трогает (значение 0 ≠ легаси-NULL); backfill тоже no-op.
- **logtail без токена**: warning-маркер при старте; остальное поведение прежнее (хендлер не создаётся).
- **SIGKILL/TimeoutStopSec 30с**: очередь logtail (1000) может потеряться — документировано; мягкий SIGTERM-путь должен укладываться в 30с (DevOps T-701, пересечение T-655). Код в 3.8 не блокирует.
- **Windows-дев** (SIGTERM недоступен): сигнальная часть — как сегодня (SIGINT); flush-код общий в finally.

## 5. Критерии приёмки (Acceptance criteria)

**Часть B (видео-пайплайн)**
- AC-B1. `MEDIA_SHARE_SECRET` пуст → publish no-op/WARNING, видео-ветки честно деградируют (STT/фразы), тестов нет падений; задан → ticket с rel/abs URL, файл в `MEDIA_SHARE_DIR`, TTL из настроек.
- AC-B2. Эндпоинт /media: валидная подпись+срок → 200 video/* inline; просрочка → 403; битая подпись → 403; чужой/мусорный file_id → 404; traversal-попытки (`../`, `%2e%2e`) → 404; файл удалён после delete_file → 404.
- AC-B3. Классификация (unit): reply-медиа; caption-триггер на своём видео; «триггер <mp4-url>»; «триггер <tiktok-url>»; «триггер <youtube-url>» (в т.ч. в reply-таргете); видео+ссылка → URL-кид; голое «че за видос» без URL/медиа → UNHANDLED; voice/video_note → НЕ 0e.
- AC-B4. Матрица (mock LLM/downloader/media_share): youtube+summary = старый путь (diff-регресс); youtube+transcript — субтитры-текст / недоступность → download+STT; direct_url+summary — L1/L2 на внешний URL → (провал) download → publish → L1/L2 на /media → STT; direct_url+transcript — download+STT; platform_url+summary/transcript — download 360+публ+каскад / STT; native+summary — publish→L1/L2→STT-фолбек; native+transcript — STT.
- AC-B5. Публикация недоступна → пропуск L1/L2 (лог), без 120с-таймаутов.
- AC-B6. Честная выжимка: транскрипт <100 символов → фраза 5.13, в ответе НЕТ фактов RAG/памяти; user-контент `summarize_transcript` без `<context>/<user_gossip>` (мок памяти не вызывается); ≥100 → выжимка по транскрипту.
- AC-B7. «транскрипт»-выдача: HTML-эталон == кружковому (bold-имя/🗣:/italic, форвард — «(переслал X)»); длинный текст — чанки ≤4096, первая часть реплаем; автор: native — автор медиа, ссылки — автор запроса.
- AC-B8. Память: native — L1-update + memorize(`video_transcript`); URL-режимы — только memorize; строка отсутствует: юзер-медиа → INSERT (создана, FTS-искома); бот-медиа → INFO-skip; сбой памяти → WARNING, ответ жив.
- AC-B9. CHECK-миграция: свежая БД — origin-список включает voice/video_transcript; старая (user_version 3) → v4 с сохранением id/весов; INSERT обоих origins успешен; факт виден в get_rag_context.
- AC-B10. STT: `transcribe_voice(timeout=120)` — клиент получил per-request timeout 120 (mock-проверка kwarg); голосовые — прежние 10/15; файл > гейта → стратегия skipped (лог), обе → TranscriptionUnavailable; транзиентный timeout → 1 повтор.
- AC-B11. Изоляция: порядок bot.py без диф; тесты `test_epic37_router_isolation.py`-стиля зелёные; `test_youtube_handlers.py`-регресс (включая «триггер без URL и медиа → UNHANDLED») без правок кроме необходимых.

**Часть C («сцуко»)**
- AC-C1. `_build_style_anchors`: сэмпл [«сцуко, бля…», «сцуко, ну…», «да норм…»] → якоря без первых двух (или пусто при count=3 и всех залипших); префикс 1 раза — остаётся; инструкция секции — новый текст (эталон в тесте); lookback работает (нужные старые ответы подтягиваются).
- AC-C2. `CHAT_DIRECT_REPLY_TTL_DAYS` дефолт 30 (settings+param); .env=0 → вечно; memorize bot_direct_reply → expires_at≈now+30д×(0.5+weight); миграция: PG-NULL → 30 (set вызван), 0/число → не тронут, PG down → skip; backfill: NULL-строки получают expires_at, повторный запуск — no-op.
- AC-C3. Пул 5.13 не пересекается с существующими (тест smartmodule_phrases).

**Часть D (BetterStack)**
- AC-D1. Старт без токена → «[logtail] skipped (no LOGTAIL_SOURCE_TOKEN)»; с токеном → «[logtail] attached | token_len=N | logtail=x.y.z»; строка видна в journald/статус-логах; дублей хендлера нет.
- AC-D2. Завершение: при штатном выходе — «[logtail] shutdown flush» без исключений/зависаний (полный pytest + ручной прогон main-флоу в тестах не блокирует).

**Регресс**
- AC-R1. Полный pytest — 0 failed; `git diff --check` чист; коммиты по частям (B→C→D→E).
- AC-R2. `test_param_catalog` зелёный после обновления counts (253→262 поля, 61→63 группы).
- AC-R3. Деплой (T-704): Caddy /media/* → 127.0.0.1:8000; live-проверки (нативное видео «че за видос» — выжимка по видео; прямая ссылка; «транскрипт» всех kind; «немое» видео — честная фраза); маркер «[logtail] attached» в journald; события в BetterStack.

## 6. План миграции/докатки

### Тесты (создать/править)

Создать:
- `tests/test_media_share.py` — publish/sign/verify/delete/cleanup_expired, маска file_id, no-op без секрета, ext-whitelist, размерный потолок; эндпоинт /media (TestClient): 200/403/404/traversal/просрочка/inline-headers.
- `tests/test_video_router.py` (или расширить `test_youtube_video_media.py`) — классификация kind×mode (AC-B3), матрица потоков с моками `summarize_media_url`/`download`/`publish_media_file`/`transcribe_voice`, честная фраза, отсутствие RAG в файловой выжимке, память-фолбек B8, изоляция 0e vs 0f/0g/0h/0i/4e/реакции.
- `tests/test_video_stt_timeouts.py` — per-request timeout kwarg, size-гейты, транзиентный повтор.
- В `tests/test_database.py`/`test_graphrag_database.py` — `_migrate_video_origins_v4` (старая схема → новая; id/веса сохранены; INSERT voice/video_transcript; user_version=4; повторный запуск no-op).
- В `tests/test_direct_chat.py` (или `test_direct_chat_prompts.py`) — C1-кейсы (AC-C1); C2: TTL-дефолт/миграция/backfill (мок cache/db).

Править:
- `tests/test_param_catalog.py` — counts (см. 3.0).
- `tests/test_youtube_video_media.py` — «транскрипт»-выдача HTML (эталон), гейт честной выжимки (вместо прежнего summarize при любом тексте), новые вызовы STT (timeout).
- `tests/test_voice_transcription.py` — регресс формата (не меняется), при необходимости моки timeout-аргумента.
- `tests/test_youtube_summarizer_service.py` — `summarize_transcript` без RAG (мок memory не вызван), +`summarize_media_url` (мок video_client, L1/L2-цикл, пусто→VideoLevelError).
- `tests/test_youtube_handlers.py` — регресс URL-ветки (summary), «транскрипт <yt-url>» новый кейс.
- `tests/test_video_download.py` — регресс (скачивание «в тихую» quality=360).
- `tests/test_smartmodule_phrases.py`/`test_direct_chat_prompts.py:79-99`-стиль — 5.13 без пересечений; шаблон style_anchors-эталон.
- `tests/test_config_cache.py`/hot-тесты — при необходимости (новые категории).

### Документация и деплой (@DevOps/PM)

- README: видео-режимы для ВСЕХ типов (выжимка vs «транскрипт»), публикация `/media/` (TTL/секрет/Caddy), лимиты, честное поведение «немого» видео, STT-таймауты/гейты (T-702).
- `.env.example`: `MEDIA_SHARE_SECRET` (обязателен для мультимодалки; пусто — fallback), `MEDIA_SHARE_DIR`, `MEDIA_SHARE_TTL_SECONDS`, `MEDIA_PUBLIC_BASE_URL`, `MEDIA_SHARE_MAX_MB`, `VIDEO_STT_TIMEOUT_SECONDS`, `VIDEO_SUMMARY_MIN_CHARS`, `STT_GROQ_MAX_UPLOAD_MB`, `STT_OPENROUTER_MAX_UPLOAD_MB`, `CHAT_DIRECT_REPLY_TTL_DAYS` (комментарий: пусто=30, 0=вечно).
- `plans/docs/memory-project-overview.md`, `plans/backlog.md` — статусы.
- DevOps: Caddy `/media/*` → 127.0.0.1:8000; прод-чистка «сцуко» (T-698, бэкап до); live-тест BetterStack + TimeoutStopSec (T-701); деплой/верификация (T-704).

### Каскад развёртывания

1. Коммиты по частям: B1 (media_share+эндпоинт) → B2-B6 (роутер/матрица/STT) → B7/B8 (память) → C (якоря/TTL) → D (logtail) → E (README/тесты); каждый — локальный прогон затронутых тестов, финальный — ПОЛНЫЙ pytest (0 failed).
2. Прод: pull + рестарт; авто-миграции (CHECK v4, TTL-миграция/backfill) сработают на старте (лог-маркеры); DevOps добавляет Caddy-маршрут ДО live-теста видео.
3. Live-верификация (T-704): нативное TG-видео «че за видос» (L1/L2 по /media), «транскрипт» (HTML), прямая .mp4-ссылка, «немое» видео → честная фраза; старт-маркер logtail + события в BetterStack.

## Открытые вопросы (для @Builder/@PM/@DevOps)

1. Фактические лимиты провайдеров ДО фиксации дефолтов: Groq whisper upload (МБ) и OpenRouter `input_audio` (МБ) — Builder проверяет; при необходимости корректируются `STT_GROQ_MAX_UPLOAD_MB`/`STT_OPENROUTER_MAX_UPLOAD_MB` и `VIDEO_TRANSCRIBE_MAX_SIZE_MB` (код не зависит — значения горячие).
2. «Транскрипт <yt-url>» меняет прежнее поведение (субтитры вместо каскада) — подтвердить вкус владельца (иначе — отдельный триггер «субтитры»).
3. Media-шара в режиме transcript не используется (только summary) — если PM захочет видео-«пересказ-по-файлу» и для транскрипт-режима, добавляется опция (вне текущего скоупа).
4. Cap транскрипта YouTube 20000 символов (≈5 сообщений) — вкусовая граница; при необходимости — отдельная настройка.
5. Размерный потолок публикации 200 МБ — если PM хочет «очень большие» ролики для мультимодалки (дольше/дороже/риск таймаутов), потолок поднимается настройкой; STT-путь для них всё равно ограничен ~25 МБ.
