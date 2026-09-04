# Раунд 4: собственный BetterStack-хендлер + детект отказов видео + память-команды «запомни/забудь» + промпт-баг TMA + даты в RAG

Дизайн-раунд 04.09.2026, 5 блоков (T-705…T-726; продолжает T-704/база 3088816). Ссылки: `plans/features/betterstack-own-handler-video-memory-cmds/tasks.md`, живой план `plans/docs/memory-project-overview.md`, образец формата — `plans/archive/video-multimodal-pipeline-and-incidents/spec.md`. Код проверен точечно: `bot.py` (104-145, 600-697), `.venv/Lib/site-packages/logtail/{handler,frame,uploader,flusher}.py`, `services/video_cascade_client.py`, `services/youtube_summarizer_service.py`, `handlers/youtube.py` (518-600, 936-1023), `config/settings.py` (:391/:478-494/:752-753), `services/database.py` (схема/миграции v1-v4/:1098-1168/:1291-1432), `services/summary_memory.py` (:118-193/:471-489/:1194-1310/:1466-1589), `services/direct_chat_service.py`, `handlers/direct_chat.py`, `services/pg_db.py` (:31-99), `services/config_cache.py` (:226-260), `web/app.js` (536-566), `web/api/routes.py` (97-139, 228-266), `services/param_catalog.py` (GroupSpec/`_PROMPTS`/`_FLAGS`/`_LIMITS`), `services/hot_config.py`, `services/smartmodule_phrases.py`, `.env.example`, `.gitignore`, каталог OpenRouter (живой API 04.09.2026).

## 1. Обзор (Overview)

Пять блоков работ по итогам раунда 3 и прод-наблюдений (см. tasks.md; проблемы 1–4 + блок 5):

**ПРОБЛЕМА 1 — BetterStack остаётся чёрным ящиком.** hotfix 30.08 (`uvicorn log_config=None`, bot.py:626-634) и диагностика раунда 3 стоят, но сам `logtail-python 0.4.0` по-прежнему теряет события ТИХО: `handler.py` — `pipe = Queue(maxsize=1000)`, `raise_exceptions=False`, `drop_extra_events=True` (при Full — молчаливый `dropcount += 1` БЕЗ лога); `flusher.py` — ошибки отправки печатаются только `print(...)` в консоль и только после 3 ретраев; `uploader.py` — msgpack + `Bearer`, host `https://in.logs.betterstack.com`. Формат фрейма (`frame.py`): `{dt: ISO-UTC, level: lower, severity: levelno/10, message, context: {runtime: {function,file,line,thread_id,thread_name,logger_name}, system: {pid,process_name}}}`. Плюс: `aiogram.event` (aiogram 3.31 dispatcher.py:174-185) логирует КАЖДЫЙ апдейт на INFO («Update id=… is handled/not handled …») — уровня никто не задаёт → спам в панели. Решение: собственный `BetterStackHandler` с logtail-совместимым фреймом и полной наблюдаемостью (маркер, счётчики, rate-limited журнал ошибок, дропы не тихие).

**ПРОБЛЕМА 2 — отказные ответы мультимодалок проходят как успех.** Проверено в коде: оба каскадных цикла (`youtube_summarizer_service.py:97-140` `summarize_cascade` и `:242-284` `summarize_media_url`) считают успехом ЛЮБОЙ непустой ответ после `cleanup_llm_text` — текст «не вижу видео»/«can't see the video» от L1/L2 уходит юзеру как «выжимка». Пустой контент уже трактуется как отказ уровня (`video_cascade_client.py:143-144` — `VideoLevelError('empty content')`, без повтора). Живой каталог OpenRouter (API 04.09.2026) подтверждает research:
- `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` — **единственная free с audio+video**: `text+image+audio+video->text`, контекст 256k;
- `minimax/minimax-m3:free` — `text+image+video->text`, контекст 1M (audio НЕТ);
- `google/gemma-4-31b-it:free` — `text+image+video->text` (audio НЕТ; AI Studio не берёт прямые .mp4).
Free-роуты не гарантируют доставку видео → «не вижу видео»/короткие заглушки вместо выжимки. Детект отказов компенсирует + каскад уводит на следующий уровень/субтитры/STT.

**ПРОБЛЕМА 3 — нет команд «запомни/забудь» в direct_chat.** Есть `/forget` (только `origin='bot_direct_reply'` + FTS, свой scope, direct_chat.py:253-272), `/clear`, `protected_facts` (в проде пуста; в контекст direct_chat идёт блоком `<protected_facts>`, `direct_chat_service.py:624-637`), авто-`memorize_facts`. RBAC чата сегодня — ТОЛЬКО `settings.ADMIN_USER_ID`; PG-роли (`bot_admins` telegram_id/role_name, pg_db.py:51-59; сиды 5885953495=admin, 1313107079/134812796=moderator) используются только в TMA. ConfigCache API: `get_role(telegram_id)`, `roles()`, `admins()` (:234-256). Юзер хочет: «бот, запомни …» / «бот, забудь …» в чате.

**ПРОБЛЕМА 4 — промпт-баг TMA.** `web/app.js saveConfigItem` (:548-553): `isNaN(value)` применяется ко ВСЕМ не-json полям → для str («текст») `isNaN('текст') === true` → ложный тост «Некорректное значение…». Сервер (`routes.py _coerce_value` :97-139) для str принимает всегда (в т.ч. пустую строку — «промпт не может быть пустым» в коде СЕЙЧАС НЕТ, задача T-719 формулировала как существующий 422 — это уточнение: 422 предстоит добавить). Пустая '' в PG хранится как есть и `hot.get` вернёт её вместо code-дефолта (config_cache.get возвращает '' если ключ есть) → пустой системный промпт = сломанный бот.

**БЛОК 5 — research/процесс.** `migrate_history/` (~602 МБ, 3 JSON, НЕ в .gitignore — `?? migrate_history/` в дереве; риск коммита). 3 РАЗНЫХ чата: `2661910336` («10.08.2025.json», 168,2 МБ, апр25-авг25 — юзер просил именно его), `2417005237` («10.2024.json», 151,1 МБ, окт24-мар25), `1691371902` («желтая до 10.2024.json», 255,1 МБ, дек22-окт24). Дат в RAG-фактах нет (голый текст; `created_at` в БД есть) → «что было N-числа» через RAG не работает.

### Цели раунда

1. (T-706/T-707) Собственный `BetterStackHandler` с logtail-совместимым фреймом, наблюдаемостью (маркеры/счётчики/журнал) и чистым завершением; гашение INFO-спама `aiogram.event`.
2. (T-709/T-710) Детект отказных/пустых ответов видео-моделей (маркерный, без правки промптов) + смена дефолтов видео-моделей по живому каталогу OpenRouter.
3. (T-712…T-716) Память-команды «запомни/забудь» в direct_chat: хранилище, удаление, RBAC (админ/модер/юзер), тумблер, фразы.
4. (T-718…T-720) Промпт-баг TMA: валидация по типу на фронте + серверный 422 пустых prompts/content.
5. (T-721…T-725) Research-отчёты (импорт истории, sqlite→PG), `.gitignore` для `migrate_history/`, даты в RAG-фактах, правило авто-коммита memory-sync в project.md.
6. (T-726) Финал @DevOps: полный pytest, деплой, live-верификация.

### Сценарии пользователя

- «бот, запомни: у нас бензин только на АЗС Лукойл» → бот отвечает «запомнил», факт участвует в RAG («на какой заправке заправляемся?» — бот отвечает по памяти). «бот, забудь бензин» → «забыл N фактов»; админ может забыть про всё в чате, юзер — только своё (и только при включённом тумблере).
- Кидаешь «че за видос» → L1-модель отвечает «не вижу видео» → бот НЕ шлёт это юзеру, а пробует L2 → субтитры/STT; если L2 тоже отказывает — STT-фолбек (нативные файлы) или субтитры (YouTube).
- В админке сохраняешь промпт с кавычками и переносами → без ложного тоста; пустой промпт → честный тост/422 «не может быть пустым».
- «что было 20 мая?» → RAG-факты в контексте приходят с датой «[2025-05-20] …» → модель может ответить про дату.
- События бота видны во вкладке BetterStack в logtail-совместимом формате; в journald — счётчики/ошибки отправки, никаких тихих потерь.

### Границы (НЕ ломать)

- **Порядок регистрации роутеров `bot.py` (366-471) не меняется ни на строку**; direct_chat 0h и его команды `/clear /persona /tone /forget` не ломаются; новые команды живут ВНУТРИ существующего direct-chat-триггера (отдельный роутер НЕ регистрируется — см. 3.4.2).
- YouTube-каскад и медиа-флоу (`youtube.py`, `summarize_cascade`, `summarize_media_url`, `_publish_and_cascade`, `_summarize_and_send`) — поведение не меняется, КРОМЕ детекта отказов (3.2); системные промпты (каноны) НЕ правятся (решение 3.2.3); роуты/код gemma-4-31b НЕ удаляются.
- `memorize_facts`/экстрактор/`FACT_EXTRACT_PROMPT` (канон R46-2) — байт-в-байт; `query_chat_memory` (L1-инструмент с датами «[Имя 2025-05-15]:») — НЕ трогается.
- `protected_facts` неприкосновенны (админу тоже — вне скоупа); `/forget` и его FTS-семантика не меняются (только параллельный новый путь «забудь»).
- logtail-python остаётся в requirements (см. 3.1.7) — только импорт/использование убирается из bot.py.
- Каноны `plans/docs/canon/*` и промпты не меняются вовсе (3.2.3) — правок канон-эталонов в этом раунде нет.
- `APP_VERSION` не меняем; существующие pg-ключи/env не переименовываем (env добавляется, старое имя остаётся алиасом).
- Полный pytest — 0 failed; `git diff --check` чист; `node --check web/app.js` чист.

## 2. Требования (Requirements)

### Функциональные — Часть B (BetterStack)

- FR-B1 (хендлер). Новый модуль `services/betterstack_handler.py`: `BetterStackHandler(logging.Handler)` с конструктором `(source_token, host="in.logs.betterstack.com", level=logging.INFO, buffer_size=2000, flush_interval=1.0, batch_size=500, timeout=10.0)`. Фоновый daemon-thread-флашер: раз в `flush_interval` (1 с) выгребает до `batch_size` (500) событий из буфера и отправляет одним POST. Формат фрейма — logtail-совместимый (3.1.2), отправить одним JSON-массивом (`Content-Type: application/json`, тело — `json.dumps(frames, ensure_ascii=False)`), эндпоинт `https://{host}/{source_token}` (token в path, БЕЗ Bearer — инструкция; BetterStack принимает оба способа; путь выбран, т.к. проще и не светит заголовок). Никаких `raise_exceptions`/тихих дропов.
- FR-B2 (наблюдаемость). Стартовое событие: с токеном — `logger.info("[betterstack] attached | token_len=N | handler=own-v1")` (N = длина токена, НЕ сам токен); без токена — `logger.warning("[betterstack] skipped (no BETTERSTACK_SOURCE_TOKEN)")`. Маркер пишется ПОСЛЕ подключения log_ring (фикс-прецедент раунда 3, M3: виден и в journald, и в /api/status/logs). Счётчики хендлера `sent/failed/dropped` (+ `get_stats()`); журнал сбоев отправки — `logger.warning("[betterstack] send failed | reason=… | failed=%d")` НЕ чаще 1 раза в 60 с (rate-gate, первая ошибка логируется сразу); дроп при полном буфере — WARNING не чаще 1/60 с с накопленным `dropped`; восстановление после серии сбоев — `logger.info("[betterstack] send ok | recovered | streak=%d")`. Рекурсии нет: записи собственного модульного логгера (`record.name` == имени логгера модуля) НЕ эхосируются в сеть (см. 3.1.5), log_ring их при этом видит (ring-фильтр режет только `logtail*`).
- FR-B3 (завершение). В `bot.py::main()` финальный `finally` (:689-693): маркер `logger.info("[betterstack] shutdown flush")` + существующий `logging.shutdown()` (закрывает хендлер → `close()` → досыл остатка буфера, 3.1.6). SIGKILL/TimeoutStopSec — документированная потеря буфера (≤2000 событий), как было с logtail.
- FR-B4 (тишина aiogram). Сразу после `basicConfig` (bot.py, ~:115): `logging.getLogger("aiogram.event").setLevel(logging.WARNING)` — INFO-спам «Update id=… is/not handled» (aiogram 3.31 dispatcher.py:174-185) уходит; WARNING/ERROR событий в этом логгере нет — ничего полезного не теряется. Уровень root INFO сохраняется.
- FR-B5 (конфиг/env). Чтение токена: `os.getenv("BETTERSTACK_SOURCE_TOKEN") or os.getenv("LOGTAIL_SOURCE_TOKEN")` — новый env предпочтителен, старое имя остаётся обратно-совместимым алиасом (прод-`.env` не требует мгновенной правки). `.env.example`: строка переименовывается + комментарий (3.1.7). В param_catalog/infra — без изменений (env-only, не PG).

### Функциональные — Часть C (видео: отказы и дефолты)

- FR-C1 (детект отказов). Чистая функция `is_refusal_response(text) -> bool` в `services/video_cascade_client.py` (единая точка, импортируется обоими каскадами): нормализация (lower, срез пунктуации/апострофов/звёздочек, схлопывание пробелов) → True если (а) длина нормализованного текста < `VIDEO_REFUSAL_MIN_CHARS` (15) ИЛИ (б) найдена подстрока из маркер-списка. Маркер-список и порог — константы в `services/smartmodule_phrases.py` (стиль VIDEO_*-секции, :200-234), см. 3.2.2. Только мультимодальные уровни L1/L2.
- FR-C2 (поведение). В обоих каскадных циклах после `cleanup_llm_text`: пустой текст → как сейчас (continue/«empty answer»); `is_refusal_response(text)` → WARNING-лог `"[video cascade] %s refusal → next | model=%s | reason=refusal…"` и: L1 → следующий уровень; L2 → `VideoLevelError("refusal …")` наружу (youtube URL-каскад: фолбек на L3-субтитры; файловый `summarize_media_url`: хендлер `youtube.py:587-590` уже делает STT-фолбек). Отказной текст юзеру НЕ уходит; «успешный» короткий текст в STT-путь НЕ подмешивается (STT только при отказе/пустоте — по решению юзера).
- FR-C3 (дефолты). `config/settings.py:752-753`: `VIDEO_PRIMARY_MODEL` → `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (единственная free с audio+video; id проверен по живому каталогу), `VIDEO_FALLBACK_MODEL` → `minimax/minimax-m3:free`. Каталог `param_catalog.py:399-402` — описания актуализировать; `.env.example` — значения+комментарий. Модели остаются hot-настройками (`hot.get("models.video_primary_model", …)` читается на каждый вызов). Значения в прод-PG (уже сидированные старым дефолтом) автоматически НЕ перезаписываются — деплойная заметка @DevOps: два клика в TMA (см. 4; авто-миграция небезопасна: старый дефолт неотличим от осознанного выбора юзера).
- FR-C4 (не ломать). gemma-4-31b-it:free и пр. из кода/каталога не удаляются; роуты остаются. Тест дефолтных строк.

### Функциональные — Часть D (память-команды)

- FR-D1 (распознавание). В `handlers/direct_chat.py::direct_chat_handler` ПОСЛЕ триггера (:300-301), ДО `service.handle`: парсинг памяти-команды (3.4.2). Синтаксис (после необязательного обращения «бот(…)?»/«@username» с разделителем): `запомни|запомнить|запиши` + `\s*[,:]?\s*` + текст (факт) → remember; `забудь` + `\s*[:]?\s*` + (текст | пусто) → forget/noarg. Валидный синтаксис команды → ответ/подтверждение и **consume** (в LLM не уходит). Reply на бота разрешает команду и без «бот». Не-команды (в т.ч. «бот, …» обычный вопрос) — как раньше в `handle()` (кулдаун/LLM нетронуты).
- FR-D2 (хранилище remember). `origin='user_memory'` в `graph_facts` (вариант А): миграция CHECK v5 (3.4.3). Факт хранится ВЕРБАТИМ (без LLM-экстракции — `memorize_facts` НЕ используется; отдельный путь): `weight=1.0`, `status='confirmed'`, `target_user` = канон-имя автора (алиас-резолв, `_resolve_name`) для рядового юзера; `target_user=NULL` для админа/модера (факт чата); `expires_at = now + limits.memory_commands_remember_ttl_days*86400` (дефолт 365; 0/пусто = вечно; множитель (0.5+weight) НЕ применяется — TTL задан прямо). Exact-дедуп: `origin='user_memory' AND target_user IS [NOT DISTINCT FROM] ? AND lower(fact)=lower(?)` → не вставлять повторно (ответ «уже знал» + лог). Факт немедленно FTS-иском; vec-строка — через существующий `_insert_graph_vec_row` + `_embed` с fail-open (embed-сбой → WARNING, FTS жив), иначе добьёт ленивый `backfill_graph_fact_vectors` на старте. Факт участвует в RAG для ВСЕХ (не только автора): принудительно `include_direct_reply`-подобного исключения НЕТ (user_memory не входит в фильтр bot_direct_reply). Временные «старые нерелевантные» замещаются новыми: expiry + обычный supersede/quota-механизм (не protected).
- FR-D3 (удаление forget). Новый DB-метод (3.4.5): выборка ТОЛЬКО `origin='user_memory'` по scope — админ/модер: весь чат; юзер (тумблер on): `target_user` = его канон-имя. Матч — FTS-prefix первого слова (по аналогии `_fts_forget_query`) → кандидаты, Python-фильтр «каждое слово запроса содержится в lower(fact)» (AND-семантика, до 5 слов длиной ≥3, fail-open → 0). Удаление: строки `graph_facts` + `graph_facts_fts` + best-effort `graph_facts_vec`; на каждый удалённый факт — журнал `graph_fact_compressions` `(reason='user_forget', fact_before=<текст>)` (:1422-1432). `protected_facts` неприкосновенны (отдельная таблица, в выборку не попадают структурно). Ответ — с числом удалённых; 0 → фраза «не нашёл». `/forget`, `/clear` — без изменений.
- FR-D4 (RBAC). Новый лёгкий модуль `services/chat_access.py`: `is_admin(telegram_id)`, `is_moderator(telegram_id)` (роль `admin`|`moderator`), `privilege(telegram_id) -> "admin"|"moderator"|"user"` — синхронно поверх `hot.get_config_cache()` (`get_role`/`admins()`, config_cache.py:234-255); `settings.ADMIN_USER_ID` всегда admin; PG недоступен/роль не найдена → только ADMIN_USER_ID привилегирован. Никаких новых PG-запросов в горячем пути (RAM-кэш).
- FR-D5 (тумблер). `flags.memory_commands_user_enabled` (bool, дефолт **false**): settings-поле `MEMORY_COMMANDS_USER_ENABLED` (env) + param_catalog `_FLAGS` группа `flags_memory` + `.env.example`. Тумблер false + не-админ/не-модер → команда consumed + случайная фраза из пула `CHAT_MEMORY_CMD_DENIED_PHRASES` (LLM не вызывается). Тумблер true → юзеры: remember (своё, target_user=себе), forget (только свои факты). Админ/модер работают ВСЕГДА.
- FR-D6 (фразы). Новые константы в `services/smartmodule_phrases.py` (строчные, без эмодзи, стиль R13/CHAT_FORGET_*:160-162): пулы `CHAT_MEMORY_REMEMBERED_PHRASE` (с цитатой {факт}), `CHAT_MEMORY_ALREADY_KNOWN_PHRASES`, `CHAT_MEMORY_FORGOT_DONE_PHRASE` ({n}, {запрос}), `CHAT_MEMORY_FORGOT_NONE_PHRASES` ({запрос}), `CHAT_MEMORY_FORGET_NOARG_PHRASES`, `CHAT_MEMORY_TOO_SHORT_PHRASES`, `CHAT_MEMORY_CMD_DENIED_PHRASES`. Тесты непересечения (стиль `test_direct_chat_prompts.py:122-142`).

### Функциональные — Часть E (промпт-баг TMA)

- FR-E1 (фронт). `web/app.js saveConfigItem` (:536-566): числовые проверки (`isFinite`) ТОЛЬКО для `int`/`float`; `json` — JSON.parse (ошибка → тост «Невалидный JSON…»); `str`/`bool` — `isNaN` НЕ применяется; для str: `null/undefined` → тост; для категорий `prompts`/`content` пустая/whitespace-строка → тост «…не может быть пустым»; прочие str — любое непустое значение ок. `node --check web/app.js`.
- FR-E2 (сервер). `web/api/routes.py post_config`: ПОСЛЕ `_coerce_value`, если `spec.category in (CATEGORY_PROMPTS, CATEGORY_CONTENT)` и `isinstance(value, str)` и `not value.strip()` → `HTTPException(422, f"{item.key}: не может быть пустым")`. Единая точка валидации (защищает любых клиентов); для остальных категорий пустая строка ОСТАЁТСЯ валидной (пустая модель = ступень отключена: `youtube_summarizer_service.py:102-105/247-251`; пустой ключ = disabled — легитимные сценарии).
- FR-E3. Регресс: числовые поля с мусором → 422 как раньше; `test_webapp_api` зелёный; промпты с кавычками/переносами/спецсимволами сохраняются байт-в-байт.

### Функциональные — Часть F (даты в RAG, research, процесс)

- FR-F1 (даты). Рендер фактов в `build_rag_context` (summary_memory.py:471-489): фактам с `created_at` добавляется префикс даты `[%Y-%m-%d] ` (UTC, из `created_at` unix-ts) — ВСЕМ origin (chat_history и остальным). Формат для `chat_history`/user_memory: `[2025-05-20] факт`; для знаниевых origin — дата ПЕРЕД существующим origin-префиксом: `[2025-05-20] [Из статьи]: факт`. Функция принимает кортежи `(origin, fact)` (legacy, без даты — совместимость старых вызовов/тестов) и `(origin, fact, created_at)` (с датой); продакшн-вызов `get_rag_context` (:1489) переводится на 3-кортежи. Архивные префиксы `_RAG_PREFIXES` сохраняются. L1 `query_chat_memory`, persona-карточки, `<protected_facts>` — НЕ трогаются.
- FR-F2 (research-отчёты). `plans/docs/memory-import-research.md` и `plans/docs/sqlite-to-pg-research.md` — пишет docs-агент по данным блока 5 (T-721/T-722); ключевые цифры дата-сета переданы в разделе 6/приложении ниже.
- FR-F3 (.gitignore). `migrate_history/` — добавить; verify `git status` чист от migrate_history (файлы untracked — `git rm --cached` не нужен).
- FR-F4 (процесс). `plans/project.md`, раздел «Git и процессы»: правило — в конце КАЖДОГО раунда @DevOps автоматически коммитит memory-sync-файлы (`plans/docs/memory-project-overview.md` и пр.) docs-коммитом на русском БЕЗ запроса, ПЕРЕД коммитом grep-проверка на секреты (`rg -i 'token|secret|password|api[_-]?key'` по diff + визуально; `.env` не коммитить). Применяется по факту в этом раунде (G2).

### Нефункциональные

- NFR-1. Новый хендлер не роняет логирование: `emit` никогда не бросает/не блокирует надолго (append под коротким lock); ошибки отправки живут в собственном модульном логгере с рекурсией-гейтом.
- NFR-2. Память-команды не стоят в троттлинге direct_chat (до `handle()`), но глобальные лимиты чата/анти-спам сохраняются: при отключённом тумблере фразы-отказы дешёвые, LLM не вызывается.
- NFR-3. Секреты: токен BetterStack в логах только как `token_len`; фреймы проходят `log_ring.sanitize` (R17) перед отправкой; URL `/media` с подписями в логи не пишутся (прецедент раунда 3).
- NFR-4. Тайминги не растут: детект отказов — синхронный substring (микросекунды); дата-префикс — в рендере, без SQL-изменений и доп. запросов.
- NFR-5. Изоляция: порядок роутеров bot.py без диф; команды direct_chat-семьи не пересекаются с youtube/web/…-роутерами и с `/`-командами (проверка `text.startswith("/")` раньше).
- NFR-6. Фразы-пулы раунда не пересекаются ни между собой, ни с существующими (тест); пул CHAT_MEMORY_CMD_DENIED_PHRASES — ≥2 фразы (random.choice).

## 3. Технический дизайн

### 3.1 BetterStack: свой хендлер — `services/betterstack_handler.py`

#### 3.1.1 Почему свой, а не фикс logtail

logtail 0.4.0 теряет события без следов (Queue-Full → `dropcount += 1`; ошибки — `print` в flusher, `Fake500` в uploader; ретраи 1/10/60с синхронно в потоке). Чтобы получить наблюдаемость, пришлось бы переписывать половину пакета. Свой хендлер ≈ 150 строк с тестами и без чужого поведения; фрейм-совместимость сохраняется вручную (3.1.2) — парсинг в панели BetterStack не меняется.

#### 3.1.2 Фрейм (эталон — logtail/frame.py)

```python
def make_betterstack_frame(record: logging.LogRecord, message: str) -> dict:
    """logtail-совместимый фрейм (logtail/frame.py). dt — ISO-UTC из
    record.created; level — levelname.lower(); severity = levelno // 10.
    message — ПРОШЕДШИЙ sanitize (R17). file — relative к CWD при
    возможности, иначе pathname. Доп. атрибуты записи (extra) НЕ включаем."""
    return {
        "dt": datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc).isoformat(),
        "level": (record.levelname or "info").lower(),
        "severity": int(record.levelno) // 10,
        "message": message,
        "context": {
            "runtime": {"function": record.funcName, "file": _rel_file(record.pathname),
                        "line": record.lineno, "thread_id": record.thread,
                        "thread_name": record.threadName, "logger_name": record.name},
            "system": {"pid": record.process, "process_name": record.processName},
        },
    }
```

- `message = self.format(record)` (дефолтный Formatter — `%(message)s` + текст исключения при `exc_info`; в bot.py formatter задан только console) → затем `log_ring.sanitize(message)` — R17-маскировка ДО ухода в облако.
- ВАЖНО: bot.py-маркеры вроде «[betterstack] attached» попадают в панель как обычные события (логируются ДО создания/через root) — как и раньше с logtail.

#### 3.1.3 Буфер и флашер

- `self._buffer: deque[dict] = deque(maxlen=buffer_size)` (2000); `threading.Lock`.
- daemon-thread флашер стартует в `__init__`: цикл `stop_event.wait(flush_interval)` → захват до `batch_size` событий (drain под lock) → `_post(items)` ВНЕ lock.
- `_post`: `urllib.request` (stdlib — новых зависимостей нет; requests не обязателен) POST `https://{host}/{token}`, headers `Content-Type: application/json` + `User-Agent: adminbot/own-v1`, body `json.dumps(list_of_frames, ensure_ascii=False).encode("utf-8")`, `timeout=timeout` (10 с). 2xx → `stats["sent"] += n`, сброс `fail_streak`; при `fail_streak > 0` — INFO-восстановление. Не-2xx/исключение → `stats["failed"] += n`, `fail_streak += 1`, WARNING-журнал по rate-gate.
- Rate-gate журнала: `_last_warn_ts`; первая ошибка — сразу, следующие — не чаще 1/60 с (иначе счётчик только растёт). Дроп при полном буфере: `dropped += 1` в emit + rate-limited WARNING «buffer full — dropped=%d».
- Ретраи ВНУТРИ флашера: до 1 повтора на транзиентное (сеть/5xx) с паузой 1 с — остаётся в потоке, не блокирует бота; исчерпание → WARNING-ветка выше.

#### 3.1.4 Завершение

- `flush()` (синхронный): drain всего остатка и `_post` в вызывающем потоке (для shutdown).
- `close()`: `stop_event.set()` → `thread.join(timeout=…)` → `flush()` остатка (по батчам) → `super().close()`. Вызывается `logging.shutdown()` из bot.py `finally` — штатный SIGTERM путь досылает ≤2000 событий. SIGKILL/TimeoutStopSec 30 с — потеря буфера, документировано (прецедент 3.8 раунда 3).

#### 3.1.5 Анти-рекурсия

- Внутренний логгер модуля: `_logger = logging.getLogger(__name__)` (`services.betterstack_handler`).
- `emit`: `if record.name == __name__ or record.name.startswith(__name__ + "."): return` — собственные журналы (send failed/recovery/drop) НЕ эхосируются обратно в буфер (иначе сбой сети порождал бы бесконечный цикл «warning → отправка → warning»).
- Console/ring получают эти записи штатно: `log_ring` фильтрует только логгеры `logtail*` (log_ring.py:87-92) — журнал BetterStackHandler виден в journald и /api/status/logs (это и есть наблюдаемость).

#### 3.1.6 bot.py-интеграция

```python
from services.betterstack_handler import BetterStackHandler   # заменяет from logtail import LogtailHandler
betterstack_token = os.getenv("BETTERSTACK_SOURCE_TOKEN") or os.getenv("LOGTAIL_SOURCE_TOKEN")
handlers = [console_handler]
if betterstack_token:
    handlers.append(BetterStackHandler(source_token=betterstack_token, level=logging.INFO))
logging.basicConfig(level=logging.INFO, handlers=handlers)
...
logging.getLogger("aiogram.event").setLevel(logging.WARNING)   # FR-B4, сразу после basicConfig
```

Стартовый маркер — ПОСЛЕ attach log_ring (:123-125), по образцу :134-144:

```python
if betterstack_token:
    logger.info("[betterstack] attached | token_len=%d | handler=own-v1", len(betterstack_token))
else:
    logger.warning("[betterstack] skipped (no BETTERSTACK_SOURCE_TOKEN)")
```

В финальном finally (:689) маркер меняется на `"[betterstack] shutdown flush"`, `logging.shutdown()` остаётся (он же вызывает `close()` хендлера → FR-B3). `importlib.metadata.version("logtail-python")`-блок удаляется.

#### 3.1.7 logtail-python в requirements — оставить

Решение: **пакет остаётся** (не удаляем строку из requirements; не чистим .venv). Импорт из bot.py убирается, других использований нет (проверено: только bot.py). Причина: ноль риска для деплоя/тестов, зависимость лёгкая; «чистое» удаление ничего не даёт, кроме лишнего diff в lock-файлах. `.env.example`: строка `LOGTAIL_SOURCE_TOKEN=…` заменяется на

```
# BetterStack logs (own handler, раунд 4): пусто = хендлер не создаётся.
# Старое имя LOGTAIL_SOURCE_TOKEN читается как запасное (алиас).
BETTERSTACK_SOURCE_TOKEN=your_betterstack_source_token_here
```

#### 3.1.8 Стартовый тест-маркер и поведение без токена

- С токеном: маркер «attached» уходит и в journald/ring, и (первым событием) в BetterStack — live-диагностика «слушает ли хендлер» (аналог T-700).
- Без токена: «skipped» warning, хендлер не создаётся, остальное поведение прежнее.

### 3.2 Видео: детект отказных ответов (FR-C1/FR-C2)

#### 3.2.1 Где применять

Уровень применения — **каскады** (`youtube_summarizer_service.py`), а не `OpenRouterVideoClient.summarize`: детект работает над `cleanup_llm_text`-результатом (маркеры типа `**не вижу видео**` после cleanup чище), и в лог пишется контекст уровня (`level/model/video_id`). Обе точки:
- `summarize_cascade` (:124-135): после `text = cleanup_llm_text(raw)` и проверки пустоты — `if is_refusal_response(text): logger.warning("[video cascade] %s refusal → next | model=%s video_id=%r", …); continue`.
- `summarize_media_url` (:271-283): то же, но L2-отказ формирует `last_reason = "refusal"` → финальный `VideoLevelError("refusal | label=…")` (хендлер `youtube.py:587-590` ловит → STT-фолбек).

`video_cascade_client.summarize` НЕ меняется (пустой content уже `VideoLevelError('empty content')` без повтора — :143-154). `summarize`/`summarize_transcript` (текстовые LLM-пути L3/файл) — НЕ трогаются (отказы «не вижу видео» там невозможны по построению — есть транскрипт).

#### 3.2.2 Маркеры и порог (smartmodule_phrases.py)

```python
# ── Раунд 4 (T-709, FR-C1): маркеры отказных ответов видео-моделей (L1/L2).
# Матч ПО НОРМАЛИЗОВАННОМУ тексту (lower, без пунктуации/апострофов/звёздочек).
VIDEO_REFUSAL_MIN_CHARS = 15     # ответ короче порога — не выжимка, отказ
VIDEO_REFUSAL_MARKERS: tuple[str, ...] = (
    # RU
    "не вижу видео", "не вижу ролик", "не вижу видеоролик",
    "не могу посмотреть видео", "не могу посмотреть ролик",
    "не могу просмотреть", "не могу открыть видео", "не могу получить доступ",
    "не имею доступа к видео", "нет доступа к видео", "видео недоступно",
    "ролик недоступен", "видео не загрузилось", "не загрузилось видео",
    "не получил видео", "не могу обработать видео", "не могу разобрать видео",
    "не могу посмотреть сам ролик",
    # EN (в нормализованной форме — без апострофов)
    "no video", "no video content",
    "cant see the video", "cannot see the video", "cant watch the video",
    "cannot watch the video", "cant view the video", "cannot view the video",
    "dont have access", "do not have access", "no access to the video",
    "unable to view", "unable to watch", "cannot access the video",
    "cant access the video", "video is not available", "video is unavailable",
    "failed to process the video", "couldnt load the video",
    "i cant view the video", "i cannot view the video",
)
```

#### 3.2.3 Промпт-маркер vs маркерный детект — РЕШЕНИЕ

**Маркерный детект БЕЗ правки системных промптов** (T-711 закрывается как «marker-детект без правки промпта»). Причины: (а) системный промпт — канон (правка = атомарный коммит + PG-миграция значения `prompts.youtube_video_system_prompt` — тяжёлый путь ради симптома, который чинится на 10 строк кода); (б) модель, не получившая видео, и без маркера пишет отказные фразы — список перекрывает живые формулировки (RU+EN), короткие заглушки ловятся порогом 15 символов; (в) маркер VIDEO_UNAVAILABLE в промпте не гарантирует, что free-роут его выполнит, — детект всё равно нужен как страховка; промпт-маркер можно добавить позже отдельной фичей, если список начнёт пропускать живые отказы.

`is_refusal_response` (в `video_cascade_client.py`, чистая функция):

```python
_REFUSAL_STRIP_RE = re.compile(r"[^\w\s]+", re.UNICODE)   # пунктуация/апострофы/звёздочки

def normalize_for_refusal(text: str) -> str:
    return _REFUSAL_STRIP_RE.sub(" ", str(text or "")).lower()

def is_refusal_response(text: str) -> bool:
    s = " ".join(normalize_for_refusal(text).split())
    if not s:
        return False                     # пустота обрабатывается ДО (empty answer)
    if len(s) < VIDEO_REFUSAL_MIN_CHARS:
        return True                      # короче порога — не выжимка (заглушка)
    return any(m in s for m in VIDEO_REFUSAL_MARKERS)
```

Маркеры в списке хранятся уже в нормализованной форме (без апострофов — «can't» → «cant»). Важно: маркеры НЕ включают голое «не вижу»/«не могу» (могут быть частью содержательного ответа «не вижу смысла спорить…»), только сочетания с видео/ролик/доступ/получить/загрузить — низкий риск ложных срабатываний; порог 15 симв. ловит остатки.

### 3.3 Видео: дефолты моделей (FR-C3)

Проверено по живому каталогу OpenRouter (GET /api/v1/models, 04.09.2026):

| id | Провайдер | Modality (architecture) | Контекст | Вывод |
|---|---|---|---|---|
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | NVIDIA | text+image+**audio**+video → text | 256k | **единственная free с audio+video** — новая primary |
| `minimax/minimax-m3:free` | GMICloud | text+image+video → text | 1M | новая fallback (видит кадры) |
| `google/gemma-4-31b-it:free` | AI Studio | text+image+video → text | 262k | из дефолтов выпадает (audio нет; прямые .mp4 AI Studio не берёт); код/роуты остаются |

Ожидания на free-роутах: 20 rpm / 50-1000 req/день; доставка видео не гарантирована → при живых «не вижу видео» срабатывает каскад (3.2) и STT-фолбек. Audio-модальность nemotron звук НЕ даёт в текущем пайплайне (мы шлём только video_url; воспроизведение аудио-дорожки — отдельный формат `input_audio`/новый запрос — вне скоупа; audio+video означает, что у модели есть поддержка, но наш вызов остаётся video-only) — не обещать юзеру «слышит звук».

Изменения: `settings.py:752-753`; `.env.example:529-530` (значения + комментарий); `param_catalog.py:399-402` описания («первичная: NVIDIA Nemotron 3 Nano Omni (audio+video)…»). Прод-PG: НЕ авто-мигрировать (4-е место в Edge), DevOps выставляет в TMA при деплое (вкладка «LLM Провайдеры» → «Видео-выжимка») и делает live-проверку nemotron (T-726).

### 3.4 Память-команды «запомни/забудь» (Часть D)

#### 3.4.1 Выбор хранилища «запомни» — РЕШЕНИЕ: graph_facts origin `user_memory` (вариант А)

Взвешено: (б) `protected_facts` — вечные/личные, попадают только в блок `<protected_facts>` контекста target_user и НЕ участвуют в графовом RAG-поиске; «забудь» по словам их не найдёт (нужен отдельный механизм). Цель юзера — «бот знает факт и отвечает по нему» (RAG-семантика) + «забудь вычищает». Вариант А: факт виден семантическому поиску `get_rag_context` (KNN/FTS), дата-префикс (Часть F) работает, удаление — единый путь по тексту. Цена: CHECK-миграция v5 (3.4.3) — по образцу v4, риск минимальный (D201-прецедент дважды отработан). Принято: А. `protected_facts` остаются как есть (неприкосновенны).

#### 3.4.2 Распознавание (в `handlers/direct_chat.py`)

Отдельный роутер НЕ регистрируется (риск ложных срабатываний на обычных сообщениях; обращение «бот»/reply/mention — консистентно с direct_chat). Точка: `direct_chat_handler` (:290-302) после всех гейтов и `_is_direct_trigger` — перед `service.handle`:

```python
_PEER_PREFIX_RE = re.compile(r"^(?:(?:бот(?:ина|яра|ик)?|@[\w_]+)[,:]?\s+)+", re.IGNORECASE)
_CMD_REMEMBER_RE = re.compile(r"^(?:запомни|запомнить|запиши)\s*[,:]?\s+(.+)$", re.IGNORECASE)
_CMD_FORGET_RE   = re.compile(r"^забудь\s*[:]?\s*(.*)$", re.IGNORECASE)

def _parse_memory_command(raw: str) -> tuple[str, str] | None:
    """('remember'|'forget'|'forget_noarg', arg). Ищет команду в начале
    сообщения (после обращения «бот…»/«@ник»). None — не команда."""
    text = raw.strip()
    while True:
        m = _PEER_PREFIX_RE.match(text)
        if not m:
            break
        text = text[m.end():].strip()
    for rx, kind in ((_CMD_REMEMBER_RE, "remember"), (_CMD_FORGET_RE, "forget")):
        m = rx.match(text)
        if not m:
            continue
        arg = m.group(1).strip()
        if kind == "forget" and not arg:
            return "forget_noarg", ""
        if len(arg) < 3:
            return "too_short", ""
        return kind, arg
    return None
```

- «Бот»-обращение с заглавной/строчной — ок (IGNORECASE); «бот, забудь…» и «бот: запомни…» — ок; reply на бота без «бот» — тоже (триггер уже прошёл по reply).
- remember-аргумент: схлопывание пробелов, cap 500 символов (длиннее — усечение + INFO-лог; R17-здравый смысл против спама).
- Валидная команда → consumed: НЕ вызывается `service.handle` (троттлинг/кулдаун/LLM не задействованы — команды работают даже при активном кулдауне диалога).
- Управление (кто что может) — в сервисном слое (3.4.4); хендлер вызывает `service.remember_user_fact(...)` / `service.forget_user_facts(...)`, ловит результат и шлёт фразу из пула D6.

#### 3.4.3 Хранение: origin `user_memory` + миграция v5

1. `services/database.py`: в `_GRAPH_FACT_ORIGINS_SQL` (:21-24) добавить `'user_memory'`; константа `_SCHEMA_VERSION_USER_MEMORY = 5`; новый `_migrate_user_memory_v5` — точная копия паттерна `_migrate_video_origins_v4` (:408-456): guard `"user_memory" not in row["sql"]` → rebuild с сохранением ВСЕХ колонок + индексы + `PRAGMA user_version = 5`; вызов в `initialize()` после `_migrate_video_origins_v4`. FTS5 не пересоздаётся (rowid сохранены).
2. `services/summary_memory.py`: `_FACT_ORIGINS` (:71-74) += `'user_memory'` (для полноты/страховки guard'а memorize); `_origin_weight("user_memory") = 1.0`.
3. Новый метод `MemoryManager.remember_user_fact(chat_id, fact, *, target_user: str | None, ttl_days: int) -> str` ("saved" | "duplicate"):
   - exact-дедуп: `SELECT id FROM graph_facts WHERE chat_id=? AND origin='user_memory' AND lower(fact)=lower(?) AND (target_user IS ? OR target_user IS NULL)` (параметризация `IS ?` — SQLite допускает) → «duplicate»;
   - `db.insert_graph_fact(chat_id, fact, "user_memory", expires_at, target_user=…, weight=1.0)` (:1098-1123; FTS пишется внутри);
   - vec: если vec доступен — `_embed([fact])` + `_insert_graph_vec_row(...)` с try/except fail-open (WARNING, FTS жив); иначе ленивый backfill (существует, :925+).
   - expiry: `None` если `ttl_days in (None, 0)`, иначе `int(time.time() + ttl_days*86400)`.
4. Факт в RAG: `get_rag_context` ищет по всем origin, кроме фильтра `bot_direct_reply` (search_graph_facts_fts:1140-1141 `origin != 'bot_direct_reply'` — `user_memory` НЕ исключается автоматически; на vec-пути фильтр аналогичен). Участие подтверждается тестом (факт виден в контексте по словесному запросу).
5. Границы: user_memory не создаёт nodes/edges (прямой INSERT без LLM-экстрактора) — чистить при забывании только graph_facts/fts/vec (3.4.5), nodes/edges не задеты. Вес 1.0 участвует в обычном time-decay/supersede/quota как все (не protected) — «старые нерелевантные замещаются».

#### 3.4.4 Сервисный слой и права (`services/direct_chat_service.py`, `services/chat_access.py`)

В `DirectChatService` (уже имеет `memory`/`db`/`aliases`, __init__:119-125):

```python
async def remember_user_fact(self, chat_id: int, user, fact_text: str) -> str:
    """Привилегия: admin/mod — всегда; user — только при флаге
    flags.memory_commands_user_enabled. target_user: канон-имя (алиас-
    резолв) для user; None для admin/mod (факт чата). ttl: hot
    limits.memory_commands_remember_ttl_days (дефолт settings, 365)."""
    privilege = chat_access.privilege(user.id)
    if privilege in ("admin", "moderator"):
        target_user = None
    else:
        if not hot.get("flags.memory_commands_user_enabled", settings.MEMORY_COMMANDS_USER_ENABLED):
            return "denied"
        target_user = self._resolve_name(user)      # :860-865 (алиас-канон)
    result = await self.memory.remember_user_fact(
        chat_id, fact_text, target_user=target_user,
        ttl_days=hot.get("limits.memory_commands_remember_ttl_days", settings.MEMORY_COMMANDS_REMEMBER_TTL_DAYS))
    return result                                    # "saved" | "duplicate" | "denied"

async def forget_user_facts(self, chat_id: int, user, phrase: str) -> tuple[int, str]:
    """scope: user (тумблер on) — свои (target_user=канон-имя); admin/mod —
    весь чат (target_user любой). → (removed, query_text)."""
```

RBAC-хелперы `services/chat_access.py` (новый модуль, синхронный):

```python
def _cache() -> Any:
    from services import hot_config as hot
    return hot.get_config_cache()          # None до init — только ADMIN_USER_ID

def role_of(telegram_id: int) -> str | None:
    cache = _cache()
    if cache is None:
        return None
    return cache.get_role(telegram_id)     # RAM (config_cache.py:234); PG down → None

def is_admin(telegram_id: int) -> bool:
    return telegram_id == settings.ADMIN_USER_ID or role_of(telegram_id) == "admin"

def is_moderator(telegram_id: int) -> bool:
    return is_admin(telegram_id) or role_of(telegram_id) in ("moderator",)

def privilege(telegram_id: int) -> str:
    return "admin" if is_admin(telegram_id) else (
        "moderator" if is_moderator(telegram_id) else "user")
```

Фолбэк PG down: роли в RAM пусты → привилегирован только `settings.ADMIN_USER_ID` (R6). Никаких новых PG-запросов в горячем пути. Команды `/persona` и пр. НЕ переходят на chat_access (вне скоупа — там прежняя логика ADMIN_USER_ID).

#### 3.4.5 Удаление: DB-метод в `services/database.py`

```python
async def forget_memory_facts(self, chat_id: int, words: list[str],
                              target_user: str | None = None, now_ts: int = 0) -> int:
    """«забудь» (T-714/FR-D3): только origin='user_memory'. words — слова
    запроса (>=3 симв, до 5). FTS-prefix первого слова (fail-open → 0) →
    кандидаты; Python-фильтр: КАЖДОЕ слово содержится в lower(fact) (AND).
    target_user None → весь чат; иначе — свои факты юзера. Удаление:
    graph_facts + graph_facts_fts + best-effort graph_facts_vec; журнал
    graph_fact_compressions (reason='user_forget'). protected_facts в
    выборку не попадают (отдельная таблица)."""
```

- words: `re.findall(r"[0-9a-zа-яё]+", phrase.lower())`, `len>=3`, срез до 5; пусто → 0.
- FTS-запрос первого слова: `'"w0"*'` (build-style из `_fts_forget_query` :1320-1330) + `origin='user_memory'` + `chat_id` + (`target_user = ?` если задан) + живые (expires_at NULL/>now); `LIMIT 500`.
- Python-фильтр: `all(w in fact_lower for w in words)`; `fact_lower = fact.lower()`.
- Удаление по id: fts → fact → vec (try/except) → `log_fact_compression(chat_id, id, fact_before, None, "user_forget")` (:1422-1432); commit; return len.
- Экспирация NOT NULL-защиты нет — created_at/expires_at фильтруются в WHERE.
- Повторный вызов безвреден. Граница: НЕ удаляет chat_history/bot_direct_reply/прочее — только явно «запомненные» факты (семантика команды «забудь» = аннулировать «запомни»; для остального есть /forget и /clear).

#### 3.4.6 Новые настройки и каталог

`config/settings.py` (блок памяти, рядом с GRAPH_FACT_TTL_DAYS :391):

```python
# ── Раунд 4 (T-715, FR-D5): память-команды «запомни/забудь» для участников ──
# False = команды работают только у админа/модератора (юзеру — фраза-отказ).
MEMORY_COMMANDS_USER_ENABLED: bool = _env_bool("MEMORY_COMMANDS_USER_ENABLED", False)
# Срок «запомни» (origin user_memory), дней; 0 = вечно (экспирация выключена).
MEMORY_COMMANDS_REMEMBER_TTL_DAYS: int = _env_int("MEMORY_COMMANDS_REMEMBER_TTL_DAYS", 365)
```

`param_catalog.py`: `_FLAGS` += `("MEMORY_COMMANDS_USER_ENABLED", "Память-команды «запомни/забудь» для участников", "flags_memory", "Выключено — «запомни/забудь» доступны только админу и модераторам; участникам бот отвечает отказом и команду не исполняет.")`; `_LIMITS` += `("MEMORY_COMMANDS_REMEMBER_TTL_DAYS", "Срок «запомни» для участников, дней (0 = вечно)", "int", "limits_memory", "Через сколько дней забывается факт из «запомни». Пусто/0 — хранить вечно.")`. `.env.example` — обе строки. Сид в PG — автоматический (ON CONFLICT DO NOTHING; флаги-дефолты пишутся из settings, T-637-механика). Обновить тест-счётчики `test_param_catalog.py` (см. 6).

Флаги показываются в TMA на вкладке «Память и RAG» (правило tab-маппинга: группа `flags_memory` — на memory_rag; правок маппинга НЕ требуется — проверяется тестом `test_frontend_tab_mapping.py`).

#### 3.4.7 Фразы (FR-D6) — эталонные тексты

```python
# Раунд 4 (T-716, FR-D6): память-команды «запомни/забудь» (строчные, без
# эмодзи/маркдауна — стиль R13/CHAT_FORGET_*:160-162; {…} — .replace).
# {факт} — запомненный текст; {n} — число удалённых; {запрос} — аргумент.
CHAT_MEMORY_REMEMBERED_PHRASE = "запомнил: {факт}"
CHAT_MEMORY_ALREADY_KNOWN_PHRASES: tuple[str, ...] = (
    "это я уже знал, без толку повторять",
    "такое уже в памяти есть, не дублирую",
)
CHAT_MEMORY_FORGOT_DONE_PHRASE = "забыл {n} фактов про \"{запрос}\""
CHAT_MEMORY_FORGOT_NONE_PHRASES: tuple[str, ...] = (
    "в памяти про \"{запрос}\" ничего не нашёл",
    "не помню, чтобы запоминал про \"{запрос}\"",
)
CHAT_MEMORY_FORGET_NOARG_PHRASES: tuple[str, ...] = (
    "забудь что именно? напиши \"бот, забудь <что>\"",
    "скажи, что забыть, а то я не экстрасенс",
)
CHAT_MEMORY_TOO_SHORT_PHRASES: tuple[str, ...] = (
    "коротковато, уточни, что запомнить или забыть",
    "это слишком расплывчато, напиши конкретнее",
)
CHAT_MEMORY_CMD_DENIED_PHRASES: tuple[str, ...] = (
    "команды памяти для меня закрыты, это привилегия админов",
    "запоминать и забывать за тебя я не уполномочен",
    "тумблер память-команд для участников выключен, не в обиду",
)
```

(Точный байт-в-байт текстов фиксируется при реализации; кавычки-ёлочки «…» допустимы внутри строк — тесты непересечения по точным значениям.)

### 3.5 Промпт-баг TMA (Часть E)

#### 3.5.1 Фронт `web/app.js saveConfigItem` (замена :536-553)

```js
if (item.type === 'json') {
  if (typeof value === 'string') {
    try { value = JSON.parse(value); }
    catch (e) { this.toast('Невалидный JSON в ' + item.key, 'err'); return; }
  }
} else if (item.type === 'int') {
  value = parseInt(value, 10);
  if (!isFinite(value)) { this.toast('Некорректное значение для ' + item.key, 'err'); return; }
} else if (item.type === 'float') {
  value = parseFloat(value);
  if (!isFinite(value)) { this.toast('Некорректное значение для ' + item.key, 'err'); return; }
} else if (item.type === 'bool') {
  value = !!value;               // как раньше
} else if (value === null || value === undefined) {
  this.toast('Некорректное значение для ' + item.key, 'err'); return;
}
// str: пустая строка недопустима для prompts/content (сервер дублирует 422)
if (item.type === 'str' && typeof value === 'string'
    && (item.category === 'prompts' || item.category === 'content')
    && !value.trim()) {
  this.toast('Промпт не может быть пустым: ' + item.title, 'err'); return;
}
```

(фронт знает `item.category` из GET /api/config — routes.py:197-213; порядок toast-ов и тексты — на усмотрение Builder'а, смысл зафиксирован. `bool` сейчас рендерится чекбоксом — ветка защитная.)

#### 3.5.2 Сервер `web/api/routes.py post_config` (после :259-262)

```python
value = _coerce_value(spec, item.value)                    # ValueError → 422 (сущ.)
if spec.type == "str" and spec.category in (CATEGORY_PROMPTS, CATEGORY_CONTENT):
    if isinstance(value, str) and not value.strip():
        raise HTTPException(status_code=422,
                            detail=f"{item.key}: не может быть пустым")
```

Решение T-719 = **(а) серверный 422** (единая точка валидации для всех клиентов) + фронт-тост как UX-дубликат (E1). Уточнение факта: серверного 422 для пустых prompts в коде СЕЙЧАС не было (tasks.md описывал его как существующий) — добавляется этим раундом.

### 3.6 Даты в RAG-фактах (Часть F)

`build_rag_context` (summary_memory.py:471-489) — ЕДИНАЯ точка рендера RAG-фактов (`<user_gossip>`/`<bot_knowledge>`); других LLM-рендеров фактов нет (persona-карточки идут юзеру текстом, не LLM-контекст; `<protected_facts>` — отдельный блок без дат, не трогаем).

Новая сигнатура/логика:

```python
def _date_prefix(created_at) -> str:
    """'[%Y-%m-%d] ' из unix-ts (UTC); None/0 → ''."""
    if not created_at:
        return ""
    return datetime.datetime.fromtimestamp(int(created_at), datetime.timezone.utc).strftime("[%Y-%m-%d] ")

def build_rag_context(facts: list) -> str:
    """facts: (origin, fact) — БЕЗ даты (legacy, старые вызовы/тесты);
    (origin, fact, created_at) — с датой-префиксом '[%Y-%m-%d] ' ПЕРЕД
    текстом (gossip) и ПЕРЕД origin-префиксом (knowledge). Канон-структура
    R46-4 сохраняется (два пробела отступа; пустой блок — <block></block>).
    escape_xml_text обязателен."""
```

- gossip-строка: `"  " + date + escape_xml_text(fact)`; knowledge: `"  " + date + _RAG_PREFIXES.get(origin,"") + escape_xml_text(fact)`.
- Вызов `get_rag_context` (:1489): `build_rag_context([(origin, fact, created_at) for origin, fact, created_at in facts])` — created_at всегда есть (NOT NULL в схеме); legacy-ветка остаётся для совместимости тестов.
- `sort_by_timestamp` (DirectChat, :1487-1488) не меняется.
- L1 `query_chat_memory` (tool_router) не трогается — там уже «[Имя 2025-05-15]: текст».

### 3.7 Файлы-кандидаты изменений

| Файл | Изменение |
|---|---|
| `services/betterstack_handler.py` | **новый**: BetterStackHandler/make_betterstack_frame/flush/close/stats (3.1) |
| `bot.py` | замена LogtailHandler → BetterStackHandler (:110-115); `aiogram.event` WARNING (:после 115); маркеры attached/skipped (:127-144); shutdown-маркер (:689); удаление import logtail |
| `.env.example` | `BETTERSTACK_SOURCE_TOKEN` (+алиас-комментарий); новые видео-дефолты (:529-530); `MEMORY_COMMANDS_USER_ENABLED`, `MEMORY_COMMANDS_REMEMBER_TTL_DAYS` |
| `config/settings.py` | дефолты моделей (:752-753); +2 поля памяти (:391-блок) |
| `services/param_catalog.py` | +флаг (flags_memory), +лимит (limits_memory), описания видео-моделей (:399-402) |
| `services/smartmodule_phrases.py` | VIDEO_REFUSAL_* (3.2.2) + CHAT_MEMORY_* (3.4.7) |
| `services/video_cascade_client.py` | `normalize_for_refusal`/`is_refusal_response` (чистые функции) |
| `services/youtube_summarizer_service.py` | отказ-детект в `summarize_cascade`/`summarize_media_url` (3.2.1) |
| `services/database.py` | origin-список + `_migrate_user_memory_v5` (v5); `forget_memory_facts` (3.4.5) |
| `services/summary_memory.py` | `_FACT_ORIGINS`+`_origin_weight`('user_memory')=1.0; `remember_user_fact`; дата-префиксы в `build_rag_context`/`get_rag_context` (3.6) |
| `services/direct_chat_service.py` | `remember_user_fact`/`forget_user_facts` (3.4.4) |
| `services/chat_access.py` | **новый**: is_admin/is_moderator/privilege (3.4.4) |
| `handlers/direct_chat.py` | `_parse_memory_command` + ветка команд в `direct_chat_handler` (3.4.2) |
| `web/app.js` | saveConfigItem по типам (3.5.1) |
| `web/api/routes.py` | 422 пустых prompts/content (3.5.2) |
| `.gitignore` | `migrate_history/` |
| `plans/project.md` | правило авто-коммита memory-sync (T-725) |
| `plans/docs/memory-import-research.md`, `sqlite-to-pg-research.md` | **новые** research-отчёты (T-721/T-722, docs-агент) |

### 3.8 Состав финального коммита (G2, @DevOps)

Код/тесты B-F + `.env.example`/`.gitignore`/`plans/project.md` + research-отчёты + `plans/docs/memory-project-overview.md` (memory-sync, авто-коммит по правилу T-725) + `plans/features/betterstack-own-handler-video-memory-cmds/` (spec+tasks). НЕ коммитить: `.env`, `migrate_history/` (теперь в .gitignore). Пуш в origin/master; деплой 198.46.175.136 (pull + мягкий SIGTERM-рестарт); live-верификация по чек-листу T-726.

## 4. Пограничные случаи и решения (Edge cases)

- **«Бот, забудь» без аргумента** (или аргумент < 3 симв.: «забудь всё» → слово «всё» 2 символа) → фраза-подсказка/«коротковато», consumed (LLM не вызывается). «забудь всё» намеренно НЕ реализуем (без «всё», по задаче).
- **Команда в чате, где direct-chat-триггер не сработал** (нет reply/mention/«бот», юзер написал просто «забудь бензин»): direct_chat_handler вернёт UNHANDLED → сообщение уходит дальше по роутерам (их триггеры свои, вреда нет) — решение: «бот»-обращение или reply ОБЯЗАТЕЛЬНЫ (консистентно с direct_chat; отдельный префикс-роутер НЕ добавляем).
- **«бот, забудь бензин, но только про АЗС…»** — удаление по AND-словам до 5; 0 совпадений → «не нашёл»; риск «забыл N» при осмысленном тексте минимален (scope: только явные user_memory-факты).
- **Забывание чужих фактов юзером**: scope-фильтр `target_user` = канон-имя по алиасам — чужой факт (другой канон) не удалится; админ/модер — chat-wide (target_user любой).
- **Тумблер выключен**: юзер (не админ/модер) с валидной командой → дени-фраза + consumed (LLM не вызывается); админ/модер игнорируют тумблер. PG down → ролей в RAM нет → привилегирован только ADMIN_USER_ID (R6-фолбэк).
- **«запомни» с уже существующим фактом** (exact, lower): duplicate → фраза «уже знал»; повторная запись не плодится.
- **«запомни» длиннее 500 символов**: усечение + INFO-лог (кап против спама); TTL=365д по умолчанию — юзер захочет вечно → ставит 0 (документируется в описании ключа).
- **user_memory-факты и FTS/vec**: FTS-строка пишется в insert; vec-строка — fail-open при embed-сбое; после деплоя старые факты добирает существующий backfill на старте. Удалённый факт в vec остаётся «мусорной» строкой, но KNN-путь её игнорирует (get_graph_fact_records не находит строку — прецедент /forget).
- **Удаление не трогает protected_facts** (другая таблица, выборка по origin='user_memory' структурно их не содержит); админ тоже не может удалить protected этой командой (вне скоупа, /clear-прецедент).
- **Прод-PG видео-моделей НЕ мигрируется автоматически**: старое значение (minimax primary) неотличимо от осознанного выбора владельца → деплойная заметка DevOps: выставить в TMA; кодовые дефолты меняются для свежих установок/тестов.
- **gemma-4-31b-it:free остаётся доступной** как hot-значение — только дефолты сменились.
- **Отказ L1 + успех L2** (напр. nemotron отказал, minimax посмотрел кадры): юзер получает L2-выжимку — детект не мешает.
- **Короткий НО легитимный ответ** («просто смешной ролик» = 17 симв. — проходит; «мем с котом» = 11 → расценится отказом и уйдёт на L2/L3): риск принят — у выжимки-эталона требуются правила структуры (системный промпт просит пересказ по правилам), 15 симв. — консервативный порог; при ложных срабатываниях на проде порог поднимается константой (не hot) — решение задокументировать в отчёте.
- **Маркер в составе содержательного ответа** («…но в кадре не вижу видео, только фото»): substring-матч сработает → следующий уровень. Частота таких ответов у free-роутов мала; L2/L3 подстрахуют. (Если станет проблемой — маркеры переносятся на префикс-матч первых ~120 симв., фиксируется в отчёте.)
- **Дата-префикс меняет байтовый формат RAG-контекста** (добавляется текст в контекстные блоки): контекст чуть длиннее (11 симв./факт); бюджет-трекать не требуется (лимиты отсекают по символам, как и раньше). Старые тесты build_rag_context с 2-кортежами остаются валидными (legacy-ветка без даты) — новых эталонов добавить.
- **Дата в UTC**: created_at — unix; прод-сервер UTC; у вечерних сообщений (МСК) дата может отличаться от «локальной» на день. Решение: UTC единообразно (все метки бота UTC); при желании «чатового» пояса — отдельная фича (вопрос владельцу, см. Открытые вопросы).
- **aiogram.event = WARNING**: теряется INFO-спам «Update id=…»; важные события (ошибки апдейтов/обработки) логируются уровнями WARNING+ — не теряются. Прочие aiogram-логгеры не трогаем.
- **Пустой BETTERSTACK_SOURCE_TOKEN + пустой LOGTAIL_SOURCE_TOKEN** → «skipped» warning на старте, бот жив, поведение как раньше без хендлера.
- **Буфер переполнен** (панель недоступна минуты): дропы считаются и логируются ≤1/60с — не тихо; при восстановлении «send ok | recovered», очередь догоняет (последующие батчи).
- **HTTP 4xx от BetterStack** (битый токен/квота): НЕ ретраится внутри флашера (кроме 1 повтора на 5xx/сеть); WARNING ≤1/60с со счётчиком — DevOps видит причину в journald (маркер + счётчики).
- **`logging.shutdown()` на Windows-деве**: close() → join + flush — безопасно (таймауты); полный pytest не блокирует.
- **«забудь» в ответ на кружок/голосовой** (0i-триггер): direct_chat-гейт `is_reply_to_transcription` (:129-131) срабатывает РАНЬШЕ — команда уйдёт в 0i-путь, не в память-команды (текст там пустой) — поведение не меняется.

## 5. Критерии приёмки (Acceptance criteria)

**Часть B (BetterStack)**
- AC-B1. Фрейм-совместимость: `make_betterstack_frame` для INFO-записи возвращает ровно dt (ISO-UTC), level=«info», severity=1, message, context.runtime.{function,file,line,thread_id,thread_name,logger_name}, context.system.{pid,process_name} (мок LogRecord); WARNING → level=«warning», severity=2.
- AC-B2. Отправка (мок POST-сессии/urllib): успех → счётчик sent=n; HTTP 500/исключение → failed+=n + WARNING ≤1/60с (два сбоя подряд с интервалом <60с — одна строка в логе; >60с — вторая); восстановление → INFO «recovered | streak=N».
- AC-B3. Буфер: при заполнении (maxlen=маленький в тесте) → dropped растёт, WARNING-строка есть (не тихо); после flush буфер пуст.
- AC-B4. Старт bot.py-флоу (import-тест/мок): с токеном — маркер `[betterstack] attached | token_len=N | handler=own-v1` (N=длина, токена в логе НЕТ); без токена — `[betterstack] skipped (no BETTERSTACK_SOURCE_TOKEN)`.
- AC-B5. close()/flush(): досылает остаток (мок); повторный close безвреден; рекурсии нет — запись из модульного логгера хендлера не порождает новую отправку.
- AC-B6. `aiogram.event` level = WARNING (проверка после импорта bot.py-логики или эквивалента); root INFO не тронут.
- AC-B7. В сообщениях, уходящих в сеть, применён sanitize (R17): запись с «Authorization: Bearer sk-…» в message → в фрейме «***».

**Часть C (видео)**
- AC-C1. Таблица маркеров: каждый RU/EN маркер (в разных регистрах/пунктуации/`**…**`-обёртке) → is_refusal_response=True; не-отказные фразы (содержательные выжимки ≥15 симв., «не вижу смысла…», «не могу не отметить…») → False; текст ровно 14 симв. → True; ≥15 без маркеров → False.
- AC-C2. Каскад (мок video_client): L1 вернул отказной текст → пробуется L2; L1+L2 отказали → `summarize_cascade` уходит на L3-субтитры; `summarize_media_url` бросает VideoLevelError (reason содержит 'refusal') → хендлер делает STT-фолбек (существующая ветка); отказной текст юзеру НЕ отправлен; лог-строка «refusal → next» присутствует.
- AC-C3. Дефолты: `settings.VIDEO_PRIMARY_MODEL == "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"`, `VIDEO_FALLBACK_MODEL == "minimax/minimax-m3:free"` (тест строк); .env.example-значения совпадают; старые каскадные тесты зелёные.

**Часть D (память-команды)**
- AC-D1. Распознавание (unit на `_parse_memory_command`): «бот, запомни: X» / «Бот, запомни X» / «@ник запомни X» / «запиши X» / reply «забудь X» → команда+аргумент; «бот, что думаешь?» / «забудь» (noarg) / «запомни» (noarg, too_short) / «забудь а» → not-a-command/коротко по правилам; не-триггеры уходят в обычный direct_chat (тест маршрута).
- AC-D2. Хранение: «запомни …» (юзер, тумблер on) → INSERT origin='user_memory', weight=1.0, target_user=канон-имя юзера, expires_at≈now+TTL; админ → target_user NULL; duplicate (тот же факт) → повторно НЕ вставлен + фраза «уже знал»; факт виден в `get_rag_context` по словесному запросу (мок/FTS).
- AC-D3. Миграция v5: свежая БД — origin-список включает 'user_memory' (sqlite_master.sql); старая (user_version 4) → v5 с сохранением id/весов/статусов; INSERT 'user_memory' успешен; повторный запуск — no-op; FTS жив.
- AC-D4. Удаление: админ «забудь бензин» → удалены ВСЕ user_memory-факты чата, содержащие «бензин» (AND-слова); юзер (тумблер on) — только свои; 0 совпадений → 0 + фраза «не нашёл»; запись в graph_fact_compressions (reason='user_forget') на каждый; protected_facts НЕ удаляются; /forget и /clear не сломаны (регресс).
- AC-D5. Матрица прав (юзер × тумблер): (off,user)→дени-фраза+consumed, LLM не вызван (мок); (on,user)→remember/forget-свои; (*,moderator)→chat-wide; (*,admin)→chat-wide; PG-роли читаются из ConfigCache (мок get_role); PG down → только ADMIN_USER_ID.
- AC-D6. Фразы: пулы CHAT_MEMORY_* не пересекаются ни между собой, ни с существующими (тест-стиль test_direct_chat_prompts.py:122-142); no-emoji/lowercase-тест зелёный.

**Часть E (промпт-баг)**
- AC-E1. saveConfigItem: str-промпт с кавычками/переносами сохраняется без тоста; int-поле с «abc» → тост; пустой промпт → тост «не может быть пустым»; `node --check web/app.js` чист.
- AC-E2. Сервер: POST prompts.*/content.* пустой/whitespace строкой → 422; с кавычками/переносами/спецсимволами → 200, значение в PG == отправленному (байт-в-байт); пустая '' для models.video_primary_model → 200 (ступень отключается — легитимно); числовой мусор → 422 (регресс); `test_webapp_api` зелёный.

**Часть F (даты/RAG/процесс)**
- AC-F1. build_rag_context((origin, fact, created_at)): chat_history → `[2025-05-20] факт` внутри `<user_gossip>`; search_fact → `[2025-05-20] [Из твоего прошлого поиска]: факт` внутри `<bot_knowledge>`; legacy-2-кортежи → без дат (старые эталоны зелёные); created_at=0/None → без префикса; структура R46-4 байт-в-байт кроме префиксов.
- AC-F2. `get_rag_context` возвращает даты (интеграция, мок search) — «что было N-числа» поддерживается (формат-тест); query_chat_memory/`<protected_facts>` не менялись (diff-тест/регресс).
- AC-F3. .gitignore содержит migrate_history/; `git status` без migrate_history.
- AC-F4. project.md — правило авто-коммита memory-sync + grep-проверка секретов (раздел «Git и процессы»); research-отчёты созданы с цифрами из раздела 6.

**Регресс**
- AC-R1. Полный pytest — 0 failed; `git diff --check` чист; node --check чист.
- AC-R2. test_param_catalog зелёный (счётчики обновлены: +2 settings-поля, +1 flag, +1 limit-запись; проверка tab-маппинга flags_memory/limits_memory не потребовала правок).
- AC-R3. Деплой (T-726): маркер attached в journald; событие во вкладке BetterStack; «че за видос» с отказным L1 — каскад/субтитры/STT (не отказной текст); nemotron live-проверка; «запомни/забудь» админом и юзером (тумблер off/on); промпт с кавычками сохраняется в TMA; даты в RAG отвечают на «что было N-числа» (проверка юзером/DevOps).

## 6. План миграции/докатки

### Тесты (создать/править)

Создать:
- `tests/test_betterstack_handler.py` — make_betterstack_frame (AC-B1); emit→буфер→flush (мок urllib/`_post`): успех/5xx/сеть; rate-gate журнала (AC-B2); дроп при полном буфере (AC-B3); анти-рекурсия (AC-B5); sanitize в message (AC-B7); close досылает (AC-B5); стартовые маркеры attached/skipped (AC-B4, через хелпер bot.py-логики или эквивалентный тест).
- `tests/test_chat_access.py` — RBAC-матрица (мок ConfigCache: роль есть/нет/PG down/ADMIN_USER_ID): is_admin/is_moderator/privilege.
- `tests/test_memory_commands.py` (или в test_direct_chat.py/test_graphrag_database.py) — распознавание `_parse_memory_command` (AC-D1); маршрут direct_chat_handler (команда consumed, LLM не вызван; не-команда → handle); remember (AC-D2, мок db/vec); forget (AC-D4, incl. scope-матрица); RBAC×тумблер (AC-D5); регресс /forget /clear.
- В `tests/test_graphrag_database.py`/`test_database.py` — `_migrate_user_memory_v5` (AC-D3: старая схема v4 → v5, id сохранены, INSERT, no-op повторно); `forget_memory_facts` (AND-слова, scope, journal, fail-open FTS).
- В `tests/test_direct_chat_prompts.py` — включить новые пулы в тест непересечения (:122-142) + lowercase/no-emoji; эталонные строки CHAT_MEMORY_*.
- В `tests/test_youtube_summarizer_service.py`/`test_video_cascade.py` — is_refusal_response-таблица (AC-C1) + каскадные переходы (AC-C2, мок video_client) + дефолты (AC-C3).
- В `tests/test_webapp_api.py` — E2-кейсы (422 пустых prompts/content; байт-в-байт сохранение кавычек/переносов; '' у models ок; мусорный int → 422).

Править:
- `tests/test_graphrag_memory.py` — build_rag_context: новые эталоны с датой (3-кортежи) + legacy-без-даты сохранить; get_rag_context интеграция с датами (AC-F1/F2).
- `tests/test_param_catalog.py` — счётчики полей/групп (+2 settings, +flag/+limit); `tests/test_frontend_tab_mapping.py` — при необходимости (без правок маппинга, verify).
- `tests/test_smartmodule_phrases.py` — новые пулы/маркеры в проверках (нижний регистр маркеров — ок: маркеры в нижнем регистре по определению).
- Регресс-прогон: bot-флоу импортов (логtail-импорт удалён — тесты без logtail-пакета зелёные), youtube-каскад, direct_chat, webapp.

### Документация и деплой (@DevOps/PM)

- `.env.example`: BETTERSTACK_SOURCE_TOKEN (3.1.7), модели (:529-530), MEMORY_COMMANDS_* (3.4.6).
- `plans/project.md` — правило авто-коммита (T-725).
- `plans/docs/memory-project-overview.md` — синк после раунда (авто-коммит).
- Research-отчёты (docs-агент, T-721/T-722). **Ключевые цифры для memory-import-research.md**: migrate_history/ — 3 JSON Telegram Desktop export, ~602 МБ суммарно, ~1.27M сообщений, ТРИ разных чата: `2661910336` («10.08.2025.json», 168,2 МБ, период апр25–авг25 — юзер просил именно его), `2417005237` («10.2024.json», 151,1 МБ, окт24–мар25), `1691371902` («желтая до 10.2024.json», 255,1 МБ, дек22–окт24); формат записей `{id,type,date,date_unixtime,from,from_id,text,text_entities}`; ОТМЕТИТЬ юзеру: вероятно, считает 3 чата одним (вопрос в отчёт). Оценки стоимости/времени и рекомендации — пишет docs-агент (исходники: CONTEXT_RESEARCH.md/memory-project-overview.md; free-роуты OR 50 req/день непригодны; FTS5 бесплатно; эмбеддинги ~$0.3-5; LLM-факт-экстракция ~$3-15 на 100k DeepSeek-класса; время 1-3ч на 100k с параллелизмом). sqlite-to-pg-research.md — риски и границы из T-722 (CHECK/FTS5/vec/user_version→schema_version, aiosqlite→asyncpg, pgloader, конкурентность) — пишет docs-агент.
- DevOps прод: выставить модели в TMA (2 клика); мягкий рестарт; live-верификация чек-листа T-726.

### Каскад развёртывания

1. Коммиты по частям: B (betterstack_handler + bot.py + тесты) → C (маркеры/детект/дефолты) → D (память-команды: миграция v5 → сервисы → хендлер → фразы/RBAC/тумблер) → E (web) → F (даты/.gitignore/project.md) → research-отчёты → G2-финал. Каждый — локальный прогон затронутых тестов; финальный — ПОЛНЫЙ pytest (0 failed) + `git diff --check` + grep-проверка секретов.
2. Прод: pull + SIGTERM-рестарт; авто-миграция v5 (CHECK) сработает на старте; маркер attached в journald; BETTERSTACK_SOURCE_TOKEN (или legacy LOGTAIL_SOURCE_TOKEN) уже в .env.
3. Live-верификация (T-726) — по чек-листу в tasks.md; результаты + открытые вопросы — в отчёт PM.

## Открытые вопросы (для @Builder/@PM/@DevOps)

1. TTL «запомни» = 365 дней по умолчанию (0 = вечно). Владельцу: устраивает ли 365 или нужно «вечно» по умолчанию? (Код — hot-лимит, меняется в админке без деплоя.)
2. Дата-префикс в RAG — UTC (прод-сервер UTC). Для вечерних RU-сообщений «дата» может отличаться от МСК-локальной на день. Если нужен пояс чата (МСК) — отдельная маленькая фича (единый пояс в настройках).
3. Авто-миграция PG-значений видео-моделей сознательно НЕ делается (неотличимость ручного выбора от старого дефолта) — DevOps выставляет в TMA при деплое. Если владелец хочет авто — добавить миграцию «только если значение == старому дефолту ПАРЫ» с подтверждением.
4. Порог отказного ответа 15 символов — консервативный; живые ложные срабатывания (короткие легитимные выжимки) фиксируются в отчёте после деплоя и, при необходимости, порог/маркеры корректируются константой.
5. nemotron-omni:free «audio+video» — поддержка модальностей есть, но текущий вызов шлёт только video_url (аудио-дорожка не передаётся) — «слышит звук» юзеру НЕ обещаем; полноценный audio-путь — будущая фича, если владелец захочет.
6. Часть B не поднимает уровень «root» и не трогает `uvicorn log_config=None`; поведение панели при JSON-массиве на токене в path — подтверждается live-тестом (T-726); при проблемах — запасной вариант Bearer-заголовок (одна строка в `_post`).

## Приложение: соответствие задачам раунда

T-705 → этот spec; T-706/T-707/T-708 → 3.1/Часть B; T-709/T-710 → 3.2/3.3 (T-711 → 3.2.3 «marker-детект без правки промпта»); T-712/T-713/T-714/T-715/T-716/T-717 → 3.4/Часть D; T-718/T-719/T-720 → 3.5/Часть E; T-721/T-722 → research-отчёты (docs-агент); T-723 → .gitignore; T-724 → 3.6/Часть F; T-725/T-726 → 3.8/Часть G.
