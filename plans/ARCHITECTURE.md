# AdminBot — ARCHITECTURE.md (карта системы)

Компактная карта системы для навигации по коду и планам. Детальная история (84.x секции, ~17k строк) — в git-истории (прежний `plans/ARCHITECTURE.md`, до реструктуризации 03.09.2026); эталоны промптов — в `docs/canon/`; аксиомы и каноны «НЕ трогать» — в `project.md`. Единственный источник истины по коду — сам код (`bot.py`, сервисы).

## 1. Обзор

AdminBot — юмористический Telegram-бот «товарищ» для личного чата друзей + админ-инструмент: Telegram Mini App (TMA) дашборд https://admin-bot.duckdns.org/web/. Бот @PERMsoc_bot (id 8802473181), супергруппа -1002661910336. Прод-версия: v2.51.0+ (Epic 85 «TMA Admin Dashboard & Dynamic RBAC», деплой 30.08.2026). Стек: Python 3.12 / aiogram 3.x / FastAPI / SQLite+vec+FTS5 / PostgreSQL 16 (asyncpg) / Vue3+Tailwind CDN (см. project.md).

## 2. Telegram-слой: роутеры

Полный порядок, приоритеты и фильтры хендлеров — `bot.py:340-447` (единственный источник истины). Здесь — только карта порядка регистрации (узкие до широких, `return UNHANDLED`-пропагация, D49):

| Порядок | Роутер/область | Ключевые команды и функции |
|---|---|---|
| 0a | summary_observer | наблюдение за чатом для саммари |
| 0b | summary | /summary, /sum |
| 0c | factcheck | фактчек-триггер (reply + «фактчек») |
| 0d | search | умный поиск (умный-запрос-триггер) |
| 0e | youtube | выжимка YouTube / расшифровка TG-видео («транскрипт/че за видос») |
| 0f | web | выжимка веб-страницы по ссылке |
| 0g | checkup | /checkup, /checkup_server |
| 0h | direct_chat | «бот, …»: reply/mention/keyword → LLM-ответ |
| 0i | voice_transcription | транскрибация кружков/голосовых |
| 0 | admin_commands | админ-DM (/mimic /deadpage /alangreet), /ban и пр. |
| 0 | menu | /menu (Mini App / настройки) |
| 0 | debug_config | /debug_config (DM + GET /api/debug/config) |
| 0 | info | /info (rich-отчёт, D224/R44-1) |
| 1 | slava_presence | присутствие Славы (join/reactions) |
| 1b | alan_greeting | приветствие Алана |
| 2 | kostik | Kostik-релеи и реакции |
| 3 | alan | Alan-релеи, UAF-фильтр |
| 4 | dead_page | Dead Page: repost/join из канала |
| 4b | war_alert | военная сводка |
| 4c | common | common-контент (мемы/пулы) |
| 4d | olya | Olya-сервис (caption/репост) |
| 4.5 | video_download | «скачай …» → yt-dlp/Cobalt / прямой стрим / нативные медиа |
| 5 | slavik | Slavik-релеи |
| 6 | vasya | Vasya-релеи |

Код: `handlers/`, `bot.py` (диспетчер, эхо-лошадь). Персональные фичи (F1–F11, E9) и сервисы описаны в разделах ниже по мере релевантности.

## 3. Память (SmartModule)

Трёхуровневая память бота (`SmartModule/`, `services/`):

- **L1**: окно последних сообщений диалога (running window).
- **L2 сырьё**: 30 дней, FTS5-поиск по сырым сообщениям.
- **L3 факты**: 90 дней, sqlite-vec `float[3072]` (cosine KNN), дедуп (0.95 / 0.85–0.95).

**GraphRAG v2** (Epic 46, v2.35.0): граф `nodes/edges` — узлы entity (user/topic), рёбра с весами; TTL: веб 14 дней, чат ∞; running summary (COMPRESS_PROMPT); MMR λ=0.6, fetch_k=20; time-decay half-life 60 дней; TTL+LRU кэши; int8+float реранк; embed-кэш (SHA-256, f16); профили (пер-пользовательские канон-профили), эпизод-merge, «золотые вопросы»; FACT_EXTRACT_PROMPT (канон R46-2) → nodes/edges/facts с origin/expires_at.

Хранилище: SQLite (`services/database.py`, `services/summary_memory.py`). **Миграция GraphRAG на PostgreSQL 16 = Epic 86** (глобальный эпик в `backlog.md`, future/planned). Промпты: каноны R46-2/R46-4, EXTRACT_PROMPT — `docs/canon/`.

## 4. direct_chat_service

Подсервис ответов на обращения к боту (`handlers/direct_chat.py`, `services/direct_chat_service.py`):

- Контекст-партишн: `[map, RAG_Memory, Target_User, Protected_Facts, Mood, Global_Context, Thread, Style_Anchors]`.
- Токен-бюджет: tiktoken `o200k_base` (0.3 токена/символ рус.); бегущий конспект; каскад имён alias→nickname→username→user_id (summary_aliases, AliasResolver).
- Троттлинг: SQLite `user_version=3`, per-chat `asyncio.Lock` (D113).
- Команды: /clear /persona /tone /forget; стилевые якоря, mood-инъекция (полный трек RESEARCH — `docs/research-directchat-digest.md`).

## 5. llm_client

Единый LLM-клиент (`services/llm_client.py`): httpx, ретраи (капс + jitter + Retry-After), circuit breaker, фолбэк-провайдер (apinet.cloud → DeepSeek direct), temperature-пресеты, маскировка LLMAuthError (v3), health-чек. Эмбеддинги gemini-embedding-001 (3072); Groq whisper-large-v3 → OpenRouter (транскрибация).

## 6. Поиск и анализ контента

| Подсистема | Механика | Код |
|---|---|---|
| SearchAggregator | каскад Tavily→Exa→DDG, таймауты 5/10/15с, пустые ключи = skip (D104) | `services/search_aggregator.py` |
| FactCheck | cooldown 300с per (chat,user); поиск ПЕРВЫМ шагом, LLM только при успехе сети; XML `<claim>`+`<search_results>` | `services/factcheck_service.py`, `handlers/factcheck.py` |
| YouTube | yt-dlp + transcript-api fallback, PO Token bgutil, прокси xray/Webshare, cookies-пайплайн, гейт YTDLP_FOR_YOUTUBE | `services/youtube*.py` |
| Web | trafilatura→Tavily→Exa | `services/web*.py` |
| Checkup | Betterstack (Logtail) → journalctl fallback | `handlers/checkup*.py` |
| /summary | APScheduler расписание 0/6/12/18; принудительный вызов | `services/summary_memory.py` |
| /info | rich-отчёт из `info_text.md` (D224, R44-1) | `services/info_service.py` |

Промпты-эталоны (SEARCH/YOUTUBE/WEBPAGE/CHECKUP/FACTCHECK + R46-4-инструкция) — `docs/canon/architecture.md` + `docs/canon/backlog.md`.

## 7. Медиа-релеи

CommonRelay, OlyaRelay, DeadPageRelay, MimicRelay, AlanRelay (`handlers/`), MessageCounterMiddleware. Медиа-контент живёт в `media/` и управляется сознательно (project.md). Dead Page v2 (реализован, Epic 2/14): репост из приватного канала @d_pages + fallback на `media/dead_page/`.

## 8. Видео и транскрибация

- **VideoDownloader** (Tools/, НЕ SmartModule): Cobalt (docker) + локальный yt-dlp для YouTube (PO Token, ffmpeg merge, глобальный лок, кулдаун 5м, прогресс-бар 84.23); триггер «скачай|загрузи|…»; поддержка WebApp-выбора видео; хардненинг прямых ссылок и нативные медиа-реплаи — §14.
- **VoiceTranscriber**: Groq→OpenRouter fallback, гейты длительности; голосовые/кружочки (0i) и нативные TG-видео (0e, §14) на одном инстансе-семафоре; локальный Bot API для кружков.
- **Локальный telegram-bot-api** контейнер (aiogram `is_local=True`, FSInputFile).
- **cookies-пайплайн** (Epic 79): YOUTUBE_COOKIES_FILE, chmod 600.

## 9. Админка (Epic 85, v2.51.0+)

Самый насыщенный слой (код: `web/`, `services/pg_db.py`, `services/config_cache.py`, `services/hot_config.py`, `services/param_catalog.py`, `services/status_service.py`, `services/control_service.py`, `services/log_ring.py`, `webapp/`-модули):

- **Один event loop**: FastAPI (uvicorn, 127.0.0.1:8000) + aiogram polling (graceful shutdown SIGTERM ≤10с, `bot.py:565-593`).
- **PostgreSQL 16** (docker, только 127.0.0.1): таблицы `bot_settings` (key/value JSONB, updated_by/updated_at), `bot_roles`, `bot_admins`, `uptime_events`; asyncpg-пул с json/jsonb codecs (фикс `300866d`).
- **ConfigCache + hot.get**: чтение параметров `hot.get(key, default)` с кастом по каталогу (кэш → PG → дефолт); `param_catalog` — 276 записей (prompts 10, models 29, keys 12, limits 122, flags 42, reactions 38, content 1, infra 22; группы/описания 84.24, 61 группа после эпика 04.09.2026, +2 limits — bugfix-раунд 04.09.2026, §14).
- **RBAC v2**: permissions {sections, params, keys, actions, wildcard}; неймспейсы `param.`/`key.`/`section.`/`action.`; матчинг exact→секция→wildcard; guard последней wildcard-админа (409); маскировка ключей `{configured,last4}`; roles: admin/moderator.
- **REST /api/\***: config/info/admins/roles/status/status-logs/control/debug/config; полномочия per-key (can_edit_param/can_view_key_value, `webapp/deps.py`); 503 при PG down.
- **log_ring**: deque 1000 + sanitize (секреты маскируются); **status_service**: psutil, LLM-health, uptime-бакеты (30d/7d/24h/1h); **uptime_heartbeat** 60с, retention 72ч; **control_service**: restart/stop/start, дебаунс 30с, polkit 50-adminbot-control.rules.
- **Фронт** (`web/index.html`, `web/app.js`): Vue3+Tailwind CDN zero-build, декларативные вкладки (эпик 04.09.2026): конфиг-табы «LLM Провайдеры»/«Промпты»/«Лимиты»/«Память и RAG»/«Реакции и Триггеры» через generic-рендер (sources: категории/группы, `widget:'keyvalue'` → kv-editor) + «Доступы» (роли/админы)/«Статус» (health/логи/control)/«Как это работает», DOMPurify, статика `?v=`+Cache-Control, TMA-авторизация (initData HMAC, TMA_AUTH_MAX_AGE), /menu + WebApp-кнопка «🛠 Меню бота» (themeParams, фолбэк в группах).

## 10. Мониторинг и инфраструктура

- Sentry, Better Stack Logtail (BETTERSTACK_TOKEN), journald SystemMaxUse=200M.
- Прод: сервер 198.46.175.136, `/var/www/admin_bot`, systemd `admin_bot` (TimeoutStopSec=30), пользователь nik, polkit-правила для control.
- Docker: postgres:16 + cobalt + telegram-bot-api (все связаны через 127.0.0.1).
- Внешний HTTPS: DuckDNS (admin-bot.duckdns.org) + Caddy 2.11.4 + Let's Encrypt (сертификат 30.08→28.11.2026); ngrok-туннель отключён (T-657 superseded T-659).

## 11. Каноны и эталоны

- Указатель на `docs/canon/architecture.md` (EXTRACT/CHECKUP/SEARCH/YOUTUBE/WEBPAGE/FACTCHECK) и `docs/canon/backlog.md` (R11/R42-6/R46-2/R46-4).
- `info_text.md` — сид-файл /info (D224: DEFAULT_INFO_TEXT = info_text.md = ARCH 53.3 = R44-1).
- Правило: канон меняется только атомарно — эталон + код + тесты одним коммитом (D123).

## 12. Внешние интеграции

Провайдеры и системы (значения ключей — только на сервере, `.env`; R17): Telegram Bot API (локальный контейнер + облачный), apinet.cloud (LLM), DeepSeek (фолбэк), gemini embeddings, Groq, OpenRouter, Tavily, Exa, DuckDuckGo, Betterstack (Logtail), Sentry, Caddy + Let's Encrypt, DuckDNS, xray/Webshare прокси, cobalt, bgutil PO Token.

## 13. Эпик 04.09.2026 — видео-выжимка (video_url), Tool Calling, гейты реакций, UX/UI админки

Спека: `plans/features/multimodal-summarization-tools-reactions-ui/spec.md` (T1–T34). Полный pytest 3447 passed / 0 failed. Четыре линии:

- **Видео-каскад (`video_url`)** — пересказ YouTube до пути субтитров пробует «посмотреть ролик» мультимодальной моделью OpenRouter. `services/video_cascade_client.py`: `OpenRouterVideoClient` — payload `content = [{"type":"text"},{"type":"video_url","video_url":{"url": watch?v=…}}]`, ключ — hot-точка `keys.openrouter_api_key` (пусто → путь выключен, сразу субтитры); `services/youtube_summarizer_service.py::summarize_cascade` — L1 `models.video_primary_model` (дефолт `minimax/minimax-m3:free`) → L2 `models.video_fallback_model` (дефолт `google/gemma-4-31b-it:free`) → L3 прежняя логика субтитров. Сбой уровня (4xx/5xx/транспорт/таймаут/пустой ответ) молча уводит на следующий; ретрай уровня — только транзиентное (429/5xx/транспорт, ≤1 повтор); таймаут уровня — `models.video_timeout_seconds` (120с). Промпт видеорежима — PG-ключ `prompts.youtube_video_system_prompt` (код-канон `services/youtube_prompts.py::YOUTUBE_VIDEO_SYSTEM_PROMPT`). Интеграция — единственная замена вызова в `handlers/youtube.py` (`summarize_cascade`); кэш по `video_id`, троттлинг и фразы хендлера прежние. Видео-файлы из чата без ссылки каскад (video_url) не получают — их обрабатывает STT-ветка роутера 0e (см. §14).
- **Tool Calling (только `direct_chat`)** — модель сама решает, когда «загуглить» или «вспомнить». `services/tool_schemas.py`: `execute_web_search` (каскад SearchAggregator Tavily→Exa→DDG) и `query_chat_memory` (окно/FTS/факты/RAG через MemoryManager; enum `time_range`). `services/llm_client.py`: новый `generate_chat` (tools/tool_choice в payload `/chat/completions`, датаклассы `LLMChatResult`/`LLMToolCall`); легаси `generate` и контракт `{model, messages, temperature}` не менялись. `services/tool_loop.py::chat_with_tools`: цикл tool_calls → `role:"tool"` → повтор, жёсткий лимит ≤4 вызовов LLM (`TOOL_MAX_ROUNDS`); провайдер без tools → один обычный ответ без них. `services/tool_router.py`: реестр исполнения (`ToolDeps`/`ToolContext`/`ToolRouter.dispatch`) — всегда возвращает строку результата (в т.ч. «ОШИБКА: …»), произвольный код не исполняется. `DirectChatService` включает цикл только при переданном `tool_router` (`tool_router=None` → ровно старое поведение); ручные триггеры «найди/загугли» не менялись.
- **Реакции — runtime-гейты** (все тумблеры default `false`, читаются `hot.get`, переключение в админке без рестарта): `reactions.vasya_enabled` («Вася ↔ АДМИН», `handlers/vasya.py`), `reactions.kucha_enabled` («куча → ДАЛБАЕБ», `handlers/slavik.py::kucha_handler`; гифка Славика от тумблера не зависит), `flags.mimic_enabled` — глобальный рубильник common-мимикрии (`handlers/common.py::mimic_handler`; славячий mimic в `handlers/slavik.py` изолирован — на `limits.slavik_mimic_*`), `reactions.alan_mimic_enabled` — доп. разрешение именно на Леху (нужны оба флага; id — `reactions.alan_user_id`). Медиа `slavic_chlen.mp4` — строго Славику: гейт по `reactions.slavik_user_id` в `MessageCounterMiddleware` (не-Славик счётчик не инкрементит, гифка не шлётся). Роутеры зарегистрированы как раньше: выключенный тумблер — `return UNHANDLED` без сообщений (порядок `bot.py` не менялся).
- **UX/UI админки** — вкладки декларативны (TABS/TAB_RULES, один generic-рендер вместо дублей-шаблонов): «LLM Провайдеры» (models+keys), «Промпты», «Лимиты», «Память и RAG» (`limits_memory`/`limits_graph`/`flags_memory` + релокация 4 параметров окон/RAG между группами каталога, pg-ключи те же), «Реакции и Триггеры» (все группы `reactions` + `flags_media`), «Доступы», «Статус», «Как это работает». `limits.summary_aliases` — `widget:'keyvalue'` (новое поле `ParamSpec`) → компонент `kv-editor` (пары «ID → имя», валидация пустых/дублей, сохранение через POST /api/config). Переименование «Alan/Алан» → «Леха» — только отображаемые тексты (каталог, фронт, README, .env.example); код-идентификаторы, env и pg-ключи `ALAN_*`/`alan_*`, RBAC-секции не переименовывались.
- **Новые настройки** (Settings ↔ REGISTRY ↔ авто-сид в PG `ON CONFLICT DO NOTHING`): `VIDEO_PRIMARY_MODEL`/`models.video_primary_model` = `minimax/minimax-m3:free`; `VIDEO_FALLBACK_MODEL`/`models.video_fallback_model` = `google/gemma-4-31b-it:free`; `VIDEO_TIMEOUT_SECONDS`/`models.video_timeout_seconds` = `120.0` (мин 5); `VASYA_ENABLED`/`reactions.vasya_enabled` = `False`; `KUCHA_ENABLED`/`reactions.kucha_enabled` = `False`; `MIMIC_ENABLED`/`flags.mimic_enabled` = `False`; `ALAN_MIMIC_ENABLED`/`reactions.alan_mimic_enabled` = `False`; плюс PG-only промпт `prompts.youtube_video_system_prompt`. Каталог: 61 группа (+2), 274 записи (+8: модели +3, prompts +1, flags +1, reactions +3).

## 14. Bugfix 04.09.2026 — TG-видео по «транскрипт/че за видос», хардненинг прямых ссылок, Tool Calling в direct_chat

Спека: `plans/features/tg-video-tool-calling-fixes/spec.md` (T-667…T-685, продолжает §13). Полный pytest 3526 passed / 0 failed (новые `tests/test_media_download.py`, `tests/test_youtube_video_media.py`). Три линии:

- **TG-видео (Часть 1)** — роутер 0e `handlers/youtube.py` получил медиа-ветку: `_resolve_video_media` + `_document_is_video` (расширение `_parse` НЕ трогалось) — «видео» = `message.video` либо `message.document` (mime `video/*`; без mime — расширение `file_name` mp4/webm/mov/mkv/avi) на вызове или в `reply_to_message`; репосты работают (aiogram кладёт вложение в те же поля + `forward_origin`); `voice`/`video_note`/`audio` НЕ квалифицируются (0i не затронут); YouTube-URL в text/caption приоритетнее — URL-ветка проверяется первой и исключает медиа-ветку; триггер без URL и без медиа → прежний `UNHANDLED`. Скачивание — общий `services/media_download.py::fetch_media_to_tmp` (вынесен из voice_transcription, поведение без изменений: локальный режим `flags.download_enabled` — `get_file` + копия с диска `TELEGRAM_API_FILES_DIR/<bot_id>:<token>/` retry×3 + fallback `bot.download`; облако — `bot.download`; tmp-уборка в `finally`); им же пользуются голосовые (0i) и «скачай»-медиа (4.5). Чистые хелперы автора/факта — новый `handlers/media_common.py` (`_resolve_transcript_author`, `wrap_media_fact`, `MEDIA_UNKNOWN_AUTHOR`; voice_transcription реэкспортирует теми же именами). Лимиты ДО скачивания: `limits.video_transcribe_max_size_mb` (50 МБ, `file_size`) и `limits.video_transcribe_max_duration_seconds` (600 с, только у `video`; `document` — без проверки) в существующей группе `limits_media` (каталог +2 записи, Settings/env/сид PG, `param_catalog.py:727-732`). Транскрибация — ЕДИНЫЙ инстанс `VoiceTranscriber` (общий семафор с голосовыми: создание поднято в summary-блок `bot.py:238-247` до `setup_youtube`, каскад Groq→OpenRouter — upload mp4 / `input_audio` m4a); видео-ветка работает независимо от `enable_voice_transcription` (0i). Выдача: «транскрипт» (substring, приоритет) → сырой текст чанками ≤4096 (`send_chunked_reply` c автор-лейблом); остальные триггеры («че за видос/о чем видео/поясни за видос/перескажи видос/че в видосе») → LLM-выжимка `YoutubeSummarizerService.summarize_transcript` — тот же канон `prompts.youtube_system_prompt`, `<transcript>` со срезом `[:max_symbols]`, RAG-префикс; пустой ответ → 🗿-молчание (как URL-ветка). Память — двойная инъекция как у voice: `update_smart_message_text` + `memorize_facts` (`wrap_media_fact(type='video')`, у форвардов `forward_from`), `source_type='video_transcript'`; в `smart_cache` медиа-ветка не пишет (кулдаун — общий youtube, touch до обработки). Деградация: фразы-пулы 5.9–5.12 (`services/smartmodule_phrases.py`: TOO_LONG/TOO_BIG/UNAVAILABLE/EMPTY), WARNING-логи без трейсбеков юзеру; исключение медиа-детекции → `UNHANDLED`.
- **Скачивание (Часть 1b)** — `tools/video_downloader.py`: `_PLATFORM_HOST_SUFFIXES` — 17 платформ (youtube.com/youtu.be, tiktok.com, instagram.com, facebook.com/fb.watch, vk.com, twitter.com/x.com, rutube.ru, vimeo.com, ok.ru, twitch.tv, kick.com, dzen.ru, vine.co, reddit.com) → `is_direct_media_url` возвращает False для их ссылок даже с `.mp4`-расширением в пути (hostname-суффиксы с dot-границей, ловятся поддомены; маскировка `youtube.com.evil.com` — не ловится) → такие URL уходят в прежние ветки: yt-dlp (YouTube, гейт `flags.ytdlp_for_youtube`) / cobalt. `handlers/video_download.py`: реплай «скачай» без ссылок на чужое видео/документ (репосты — те же поля; mime `video/*` или имя-расширение; voice/video_note не подходят) → `_handle_native_media` по медиа реплая через `fetch_media_to_tmp` (собственное медиа вызова и URL — прежний приоритет; иначе — `VD_NO_LINK_PHRASES`); `cooldown_touch` в direct-ветке после `reporter.start` (:255-259) — успешный старт жжёт кулдаун, провал ДО старта — нет (D279). Честный стрим прямых `.mp4`-ссылок остаётся намеренной фичей (README, @DevOps).
- **Tool Calling (Часть 2)** — прод-диагностика до фикса (T-678): root cause прод-бага — строки FTS из `search_messages_fts` были реальными `aiosqlite.Row` без `.get` → `AttributeError` в `_query_chat_memory` (модель получала «ОШИБКА …» вместо данных, инструменты «не срабатывали») → dict-нормализация `rows = [dict(row) for row in rows]` (`tool_router.py:152-154`); плюс промпт не упоминал инструменты. Новый канон `CHAT_SYSTEM_PROMPT` (`services/chat_prompts.py`): добавлен блок ИНСТРУМЕНТЫ — `query_chat_memory` вызывать ПЕРВЫМ при вопросах о прошлом чата («сколько раз/когда/кто»), `execute_web_search` для свежих внешних данных, «цифры бери только из результата»; токсичный стиль и лимит 1-2 предложений сохранены; старый текст — константа `LEGACY_CHAT_SYSTEM_PROMPT` (эталон-проверка в `test_direct_chat_prompts`). Миграция `migrate_direct_chat_prompt_if_legacy(cache)` в `bot.py::main()` сразу после `cache.init()` (:537-544): прод-значение `prompts.direct_chat_system_prompt` заменяется ТОЛЬКО при байт-в-байт равенстве легаси; кастом юзера / отсутствующий ключ / PG down — no-op (сид `param_catalog` не трогался). Description'ы `tool_schemas.py` расширены (query_chat_memory — счёт/статистика/«когда»; execute_web_search — свежие/внешние факты; имена/схемы/`time_range` не менялись). Счётчик упоминаний: `database.py::search_messages_fts_count` (COUNT + MIN/MAX `timestamp` по FTS `smart_messages`, окно `since_ts` в SQL) + `MemoryManager.count_mentions` (те же токены FTS) → заголовок «Найдено N упоминаний „…" за сутки/неделю/месяц/всё время (с … по …)» + прежние сниппеты (≤3500); count=0 → «ничего не найдено»; сбой БД → fail-open (сниппеты без заголовка); INFO-лог `[tools] query_chat_memory | count=…`.
