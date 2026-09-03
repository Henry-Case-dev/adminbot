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
| 0e | youtube | выжимка видео по ссылке |
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
| 4.5 | video_download | «скачай …» → yt-dlp/Cobalt |
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

- **VideoDownloader** (Tools/, НЕ SmartModule): Cobalt (docker) + локальный yt-dlp для YouTube (PO Token, ffmpeg merge, глобальный лок, кулдаун 5м, прогресс-бар 84.23); триггер «скачай|загрузи|…»; поддержка WebApp-выбора видео.
- **VoiceTranscriber**: Groq→OpenRouter fallback, гейты длительности, локальный Bot API для кружков.
- **Локальный telegram-bot-api** контейнер (aiogram `is_local=True`, FSInputFile).
- **cookies-пайплайн** (Epic 79): YOUTUBE_COOKIES_FILE, chmod 600.

## 9. Админка (Epic 85, v2.51.0+)

Самый насыщенный слой (код: `web/`, `services/pg_db.py`, `services/config_cache.py`, `services/hot_config.py`, `services/param_catalog.py`, `services/status_service.py`, `services/control_service.py`, `services/log_ring.py`, `webapp/`-модули):

- **Один event loop**: FastAPI (uvicorn, 127.0.0.1:8000) + aiogram polling (graceful shutdown SIGTERM ≤10с, `bot.py:565-593`).
- **PostgreSQL 16** (docker, только 127.0.0.1): таблицы `bot_settings` (key/value JSONB, updated_by/updated_at), `bot_roles`, `bot_admins`, `uptime_events`; asyncpg-пул с json/jsonb codecs (фикс `300866d`).
- **ConfigCache + hot.get**: чтение параметров `hot.get(key, default)` с кастом по каталогу (кэш → PG → дефолт); `param_catalog` — 265 записей (prompts 9, models 26, keys 16, limits 120, flags 41, reactions 35, content 1, infra 21; группы/описания 84.24).
- **RBAC v2**: permissions {sections, params, keys, actions, wildcard}; неймспейсы `param.`/`key.`/`section.`/`action.`; матчинг exact→секция→wildcard; guard последней wildcard-админа (409); маскировка ключей `{configured,last4}`; roles: admin/moderator.
- **REST /api/\***: config/info/admins/roles/status/status-logs/control/debug/config; полномочия per-key (can_edit_param/can_view_key_value, `webapp/deps.py`); 503 при PG down.
- **log_ring**: deque 1000 + sanitize (секреты маскируются); **status_service**: psutil, LLM-health, uptime-бакеты (30d/7d/24h/1h); **uptime_heartbeat** 60с, retention 72ч; **control_service**: restart/stop/start, дебаунс 30с, polkit 50-adminbot-control.rules.
- **Фронт** (`web/index.html`, `web/app.js`): Vue3+Tailwind CDN zero-build, 6+ вкладок (Конфиг/Статус/Логи/Роли/Админы/Control), DOMPurify, статика `?v=`+Cache-Control, TMA-авторизация (initData HMAC, TMA_AUTH_MAX_AGE), /menu + WebApp-кнопка «🛠 Меню бота» (themeParams, фолбэк в группах).

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
