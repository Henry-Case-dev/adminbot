# Исследование и рекомендации по подсервису `direct_chat` (AdminBot)

**Контекст:** Telegram-бот на aiogram 3.x. Подсервис `direct_chat` отвечает на сообщения,
адресованные боту: reply на своё сообщение, упоминание `@username`/text_mention, или
fallback-regex. Все ответы — строгий reply на обращающегося. Контекст собирается через LLM
(RAG-память + ветка reply + глобальный контекст), есть token-bucket throttle.

**Ключевые файлы:** `handlers/direct_chat.py`, `services/direct_chat_service.py`.

**Метод:** поиск по DuckDuckGo/Exa по кейсам похожих ботов + документация aiogram 3.x
(официальные docs aiogram.dev). Context7 был недоступен (нет валидного API-ключа), поэтому
документация взята напрямую с docs.aiogram.dev и GitHub-обсуждений aiogram.

---

## 1. Обработка упоминаний / ключевых слов (mention & keyword triggers)

**Что уже сделано (хорошо):** в `direct_chat.py` реализованы 3 триггера — reply на бота,
entities (mention/text_mention) и fallback-regex. Это соответствует лучшим практикам.

**Рекомендации:**

- **Нормализация упоминаний.** По документации aiogram 3.x `MessageEntity` типа `mention`
  не несёт поле `username` — юзернейм извлекается через `entity.extract_from(text)`
  (`docs.aiogram.dev/en/latest/api/types/message_entity.html`). В коде это уже сделано
  (`_has_bot_mention`). Стоит добавить **bare-username** (без `@`, как в `telebot-pb`
  https://github.com/romanurban/telebot-pb — матчинг по `username` и паттернам имён) и
  **skip для форвардов/сервисных** сообщений.
- **Негативные ключевые слова (exclusions).** По опыту Telegram keyword-мониторинга 2026
  (https://telega.to/blog/telegram-keyword-monitoring-bot-2026) — добавить список
  исключений, чтобы не отвечать на «@bot хай» в спам-группах. Минимальная длина сообщения
  (≥ 2–3 слова) снижает шум.
- **Команды внутри диалога.** Сейчас сообщения, начинающиеся с `/`, возвращают `UNHANDLED`
  (строка 84). Это правильно — команды не перехватываются. Но стоит поддержать
  **внутридиалоговые команды** (см. раздел 4), парся их до возврата `UNHANDLED`.
- **Групповая приватность.** Для ответов на `@username` в группах боту нужен **выключенный
  Group Privacy** (иначе он не видит сообщения без упоминания). `telebot-pb` это явно
  документирует. Стоит проверить настройку через BotFather и задокументировать в README.

---

## 2. Контекстные LLM-диалоги (context window, memory, RAG)

**Что уже сделано:** ветка reply (`_build_conversation_thread`), RAG-память, Global_Context,
UserResolutionMap, LRU-кэш `_bot_replies` — солидная архитектура.

**Рекомендации (на базе найденных кейсов):**

- **Тримминг по токенам, а не по символам.** В `direct_chat_service.py` лимиты заданы в
  символах (`CHAT_GLOBAL_CONTEXT_MAX_CHARS`, `CHAT_THREAD_MAX_CHARS`). По кейсу aiogram +
  Claude (https://johal.in/build-telegram-bot-python-313-aiogram-310-claude) оценка по
  символам ошибается до 40% на смешанном языке; рекомендуют `tiktoken` для подсчёта токенов.
  Стоит перейти на токен-бюджет контекста.
- **Суммаризация старых сообщений.** LangChain-документация
  (https://docs.langchain.com/oss/javascript/langchain/short-term-memory) рекомендует при
  превышении окна не просто отсекать, а **суммировать** (summarization middleware) — иначе
  теряется смысл. `LLM_Memory` (https://github.com/ArhyPlayer/LLM_Memory) реализует гибрид:
  короткая память (deque последних N) + долгая (ChromaDB) + тезисы в БД. Можно добавить
  слой «тезисов» в `_bot_replies`/memory.
- **Пер-пользовательская изоляция контекста.** Уже реализовано по `user_id` — это верно
  (https://www.youngju.dev/blog/chatbot/2026-03-03-telegram-langchain-rag-bot-guide.en
  подчёркивает изоляцию per-user). Добавить **TTL хранилища в БД** (а не только in-memory
  LRU), чтобы контекст переживал рестарт (сейчас throttle и `_bot_replies` in-memory, сброс
  при рестарте — см. комментарии в коде).
- **RAG top-K + MMR.** Пример RAG-цепочки (ChromaDB, `k=4`, MMR) — хороший референс для
  настройки `get_rag_context` (разнообразие результатов, а не только релевантность).
- **Стриминг ответа.** `ai-microcore` (https://github.com/Nayjest/ai-microcore) и кейс
  johal.in показывают стриминг с `edit_text` + индикатор `ChatAction.TYPING`. Сейчас ответ
  целиком через `send_chunked_reply` — добавить typing-индикатор и постепенный апдейт текста
  улучшит UX (особенно при долгих ответах LLM).

---

## 3. Анти-спам и throttle (ключевые слова «бот», «ботохуета» и т.п.)

**Что уже сделано:** `DirectChatThrottle` (token bucket, per (chat,user), R50-7). Это уже
хорошо закрывает флуд от одного юзера.

**Рекомендации:**

- **Глобальный throttle (per-bot, а не per-chat).** Telegram лимиты — **на бота целиком**,
  а не на чат (https://grammy.dev/advanced/flood). При нескольких чатах in-memory
  per-(chat,user) не спасёт от 429 на уровне бота. Нужен глобальный счётчик + обработка
  `TelegramRetryAfter` (уже есть в примере ai-microcore).
- **Семантический/паттерн-спам-фильтр.** `tg-spam` (https://github.com/umputun/tg-spam)
  даёт практики: лимит упоминаний (`--meta.mentions-limit`), «mention-only» чек, короткие
  флуд-сообщения, similarity-порог. `censor-tg-bot` (https://github.com/capcom6/censor-tg-bot)
  — плагинные стратегии (keyword/ratelimit/regex) с приоритетами. Стоит добавить:
  - блок «только упоминание бота + мусор» (цифры/пунктуация) → не отвечать;
  - дедуп повторяющихся обращений (один и тот же текст N раз);
  - **чёрный список фраз** (в т.ч. «ботохуета») — через config, не хардкод.
- **Reputation/бан за повторы.** `rspamd-telegram-bot`
  (https://github.com/akey098/rspamd-telegram-bot) и `tg-spam` ведут репутацию юзера; при
  превышении — молчать/делать warn. Для `direct_chat` достаточно «молчать после N
  кулдаунов подряд» вместо фразы.
- **Анти-петля (reply-loop).** Уже частично закрыто (бот не отвечает сам себе, `user.id ==
  _bot_id`). Добавить защиту от **двух ботов**, переписывающихся друг с другом (bus-flag в
  `telebot-pb`), если в группе несколько ботов.

---

## 4. Интересные фичи «личного ассистента»

- **Персона / тон (persona & mood).** `Alya-Bot` (https://github.com/Afdaan/Alya-Bot-Telegram)
  и `TISM` (https://github.com/DisruptiveCollective/TISM) дают `/setpersonality`,
  мульти-настроение, эволюцию отношений. Для AdminBot уместно: **per-chat persona** (тон
  модератора vs дружелюбный), переключаемая командой внутри диалога.
- **Внутридиалоговые команды** (inline-управление без выхода из чата): `/clear` (сброс
  контекста), `/persona <...>`, `/tone formal|casual`, `/forget`. Шаблон из johal.in и
  Byeol (https://github.com/openmaya/byeol) — команды прямо в потоке.
- **Эмоции / mood-детект.** `Alya-Bot` детектит эмоции собеседника. Опционально: менять тон
  ответа по настроению сообщения.
- **Проактивность (nudge/re-engage).** `telebot-pb` шлёт nudge при бездействии; `byeol` —
  проактивный коучинг. Для AdminBot это может быть: бот сам напоминает о незакрытых
  обращениях (но осторожно — сейчас бот строго реактивный по 58.4, это менять по согласованию).
- **Инструменты (MCP/tools).** `telebot-pb` подключает MCP-тулы (погода, факты, картинки).
  AdminBot может давать боту доступ к внутренним командам (статус сервиса, справка) через
  tool-calling LLM.
- **TTS / голос.** опционально, как в heatherbot (https://github.com/dvoraknc/heatherbot).

---

## 5. Избежание конфликтов нескольких хендлеров на одно сообщение

**Что уже сделано:** `direct_chat_handler` возвращает `UNHANDLED`, когда не сработал
триггер — пропагация живёт, другие роутеры (admin_commands и т.д.) получают событие. Это
корректный паттерн aiogram 3.x.

**Рекомендации (документация aiogram 3.x):**

- **Порядок регистрации = приоритет.** В aiogram 3.x обработка останавливается на первом
  совпавшем наборе фильтров; порядок — по регистрации (if-elif-else семантика). Источник:
  GitHub Issue #208 (https://github.com/aiogram/aiogram/issues/208) и Discussion #1550
  (https://github.com/aiogram/aiogram/discussions/1550). В `bot.py` `direct_chat_router`
  подключается «сразу после 0g checkup, до admin_commands» (комментарий в
  `direct_chat.py:3`) — это правильно, т.к. direct_chat матчит узко (только триггеры).
- **`SkipHandler` — анти-паттерн.** Discussion #1550 прямо называет `raise SkipHandler`
  анти-паттерном, ведущим к неожиданному поведению. Текущий код НЕ использует его — молодцы.
  Если понадобится несколько реакций на одно сообщение — лучше **один хендлер + вызов
  нескольких use-case функций** (рекомендация из того же discussion).
- **Явная регистрация `.register()`** для контроля порядка (Issue #942
  https://github.com/aiogram/aiogram/issues/942 — фильтр-фабрику убрали, фильтры задаются
  явно и в порядке). Стоит убедиться, что все узкие хендлеры зарегистрированы до широких
  (catch-all).
- **Global filters на router.** aiogram 3.x поддерживает глобальные фильтры роутера
  (документация миграции 2→3) — можно вынести «не команды / не бот / есть текст» в
  глобальный фильтр роутера, снизив дублирование.
- **Middleware вместо «pre-handler».** Для сквозной логики (логирование, rate-limit,
  antiflood) — inner/outer middleware (https://docs.aiogram.dev/en/v3.23.0/dispatcher/middlewares.html),
  а не отдельный хендлер. Сейчас throttle внутри `handle()` — можно вынести в middleware
  роутера `direct_chat`, чтобы не дублировать в каждом сервисе.

---

## 6. Эпик 52 (T-412, R52-5) — Direct Chat: ресёрч и рекомендации (keyword-триггеры, контекст, InaccessibleMessage)

> **Метод:** как и в прошлый раз, context7 MCP (Invalid API key) и duckduckgo (аномалии)
> недоступны — работал стек **exa** (+ webfetch) и живой `inspect` установленного
> aiogram 3.29.1 (venv проекта) для подтверждения Bot API-фактов. Дата: 2026-08-23.

### 6.1 Краткое резюме

Индустрия 2025–2026 по «боту-товарищу в группе» сошлась на паттернах, большинство из
которых в AdminBot уже есть:

- **Trigger-сет «reply / mention / trigger-word»** с word-boundary — стандарт (tva.sg,
  Talon, OpenClaw): mention-first, keyword — осознанное расширение, всегда в связке с
  фильтрами шума. Подтверждает дизайн 61.5.1.
- **Двухслойная архитектура «ingestion → execution»** (aeqi mention-gating, tva.sg
  silent-log): бот читает ВСЁ (контекст копится в фон), отвечает ТОЛЬКО по триггеру.
  У AdminBot это уже работает: observer пишет память на каждое сообщение, direct_chat
  отвечает узко. Хорошая новость: паттерн не надо достраивать, надо не сломать.
- **Контекст: rolling summarization вместо обрезки** (Anthropic, OpenAI cookbook,
  tianpan, niteagent): 70–80% токен-бюджета → суммаризация старого, последние N
  verbatim. Текущая обрезка по символам (CHAT_*_MAX_CHARS) — самое слабое место.
- **Бюджет: троттлинг + кэш + (опционально) дешёвый triage-гейт** (openclaw-triage-gate:
  −75–90% токенов в группах). Bucket 3/300с как нижняя граница — ОК, но нужен потолок
  на чат в целом (см. 6.6).
- **D214 ПОДТВЕРЖДЁН** тремя источниками, включая inspect aiogram 3.29.1 (см. 6.7).

### 6.2 Оптимизация триггеров (подтверждение 61.5.1 + рекомендации)

**Паттерн 61.5.1 подтверждён:** явные lookarounds
`(?<![0-9a-zа-яё_])бот(?:…)?(?![0-9a-zа-яё_])` эквивалентны `\b` (Python 3 `re` —
Unicode-aware, кириллица работает), но читаемее и явно не матчат подчёркивание.
Тест-кейсы 61.5.3 («робот»/«ботва»/«работа»/«забота») корректны — совпадает с
индустриальным «word-boundary regex, чтобы advisor не срабатывал на advisory»
(tva.sg).

Рекомендации по снижению ложных срабатываний (референсы: Discord AutoMod allow-list,
mavibot «Ignore triggers», tg-spam):

- **NFKC-нормализация + lower перед матчем** (`unicodedata.normalize("NFKC", text)`):
  iOS-клавиатуры шлют разложенную кириллицу/широкие буквы; hashbot «fuzzy mode»
  нормализует так же. Дёшево, ловит «Б0Т»-класс.
- **Минимум 2 слова для keyword-ветки** («бот.» / «бот!!!» не триггерят, «бот, чекни» —
  да). Reply/mention-ветки не трогаем. mavibot прямо советует: триггер не должен быть
  одним словом.
- **Стоп-фразы через конфиг** (не хардкод): «бот в помощь», «бот не в теме», «бот,
  подожди» — exclude-список в settings, проверяется ДО OR-триггеров.
- **Стрипинг триггера из query** (Talon): перед LLM убирать «бот»/«@бот» из текста
  запроса («@bot что за погода?» → «что за погода?») — меньше токенов и меньше
  соблазна LLM комментировать слово «бот».
- **Дедуп повторов** (tg-spam similarity, rspamd): одинаковый текст N раз в окне →
  один ответ, дальше молчание. Прямо закрывает «бот бот бот…» — флуд-кейс.
- **Чёрный список фраз-дразнилок** — в тот же конфиг.

Связь с разделом 3: там уже были mention-only-чек, дедуп и чёрный список — здесь они
получают подтверждение из свежих кейсов и конкретные точки применения для keyword-ветки.

### 6.3 Управление контекстом (windows, суммаризация, thread vs global)

Текущая модель (Global_Context окно + Conversation_Thread + RAG_Memory) — комбинация
Window/Summary/Vector памяти, по классификации youngju — это «правильная смесь».
Слабые места:

- **Токен-бюджет вместо char-лимитов** (уже в разделе 2; подтверждаем вторым эшелоном
  индустрии: niteagent, youngju, bessavagner — `tiktoken` надёжнее оценок по символам).
- **Rolling summarization** (tianpan, OpenAI cookbook): при заполнении 70–80% бюджета
  старые сообщения НЕ отрезаются, а сливаются в бегущее саммари чата; последние
  20–30 сообщений остаются verbatim. Для AdminBot: ленивая фоновая регенерация саммари
  (fire-and-forget, прецедент memorize_facts), хранение в БД/SmartCache с TTL, не в
  памяти. Триггер — 80%, не 100% (niteagent: «сжатие занимает ход, нужен запас»).
- **Бюджет по категориям** (niteagent): system ~5% / history ~30% / thread ~20% /
  RAG ~15% / генерация 15–25% / headroom 10%. Сейчас Global_Context может съесть весь
  бюджет и не оставить места под ответ.
- **Thread vs Global:** ветка reply — «working memory» (правильно), Global — «недавний
  контекст». Добавить **supersession-маркеры** (tianpan): явное «забудь/сбрось»
  (`/clear` из раздела 4) и **must-preserve-поля** (имена, решения, обещания) — выносить
  в слоты, а не в прозу саммари (entity-preserving summarization, tianpan). Граф знаний
  Epic 26 уже делает это на уровне фактов.
- **Context poisoning** (OpenAI cookbook): ошибочный факт в саммари отравляет будущие
  ходы — «вчерашний план рулит сегодняшним». Митигация: логгировать промпты/выводы
  саммари, свежий факт побеждает (mem0: recent wins), противоречия помечать UNVERIFIED.

### 6.4 Память (долгосрочная, facts, настроения — в духе GraphRAG Epic 26)

- **Memory formation вместо суммаризации** (Mem0, DIANA, kotodamai): не компрессировать
  всё, а выборочно копить факты. У проекта это уже есть: GraphRAG (Epic 26) +
  memorize_facts с origin='bot_direct_reply'. Рекомендации поверх:
  - **Пер-пользовательские профили** (DIANA: raw + durable facts + dated events +
    interaction stats; kotodamai: contact_profiles): агрегировать факты о юзере из
    direct_chat-диалогов — имя, тон, интересы, «темы-кнопки» юзера. У AdminBot уже есть
    aliases (каскад имён) — добавить слой «факты о человеке» в GraphRAG-узлы.
  - **Decay + конфликт-резолюция**: старые факты слабее, свежий побеждает (Mem0);
    TTL уже есть (GRAPH_FACT_TTL_DAYS).
  - **Consolidation-интервал** (kotodamai: 1800с — забавное совпадение со
    SmartCache TTL): периодический пересмотр фактов, а не только per-message.
  - **НЕ сохранять мусор/токсичность** (R46-2 уже запрещает; direct_chat пишет
    «query\nanswer» только после успешной отправки — канон соблюдён).

### 6.5 Стиль/персона

- **Структура персоны** (kotodamai/telegram-persona): style_rules (исполняемые правила
  с confidence и evidence), per-contact/group profiles, topic_graph, memes. AdminBot —
  не userbot-клоун, но лёгкая версия уместна: per-chat overlay тона (раздел 4 уже
  рекомендовал) + few-shot.
- **Стилевые якоря:** LLM лучше держит стиль, если видит 2–3 своих последних ответа.
  Уже делается через Conversation_Thread (бот-сообщения из _bot_replies) — усилить
  явной секцией `<Your_recent_style>`: «вот как ты отвечал недавно, держи тон».
- **Пост-процессинг** (heatherbot 7-stage filter): резать thinking-теги, маркдаун-обёртки,
  AI-дисклеймеры, самопризнания «я ИИ» перед отправкой. Дёшево, заметно «человечнее».
- **Человеческие тайминги** (icarus, kotodamai WPM=40, read receipts): typing-индикатор
  (ChatActionSender — подтверждён в 3.29.1, см. 6.8) + короткая пауза 0.5–2с перед
  ответом. Крошечная правка, много живости. Но: паузу НЕ делать при кулдаун-фразах
  (они и так мгновенны и это правильно).
- **Температура:** один канал, общий LLM — не крутить на горячую; вынести в конфиг
  (прецедент ai-responder: creative/precise/balanced/chatty). Для фактов — ниже, для
  «настроения» — выше; без фанатизма.

### 6.6 Троттлинг/бюджет (R52-5 п.2 — ответ на вопрос)

**«Достаточно ли token-bucket 3 заряда / 300с per (chat,user)?» — да, как нижняя
граница per-user. НО есть дыры:**

- Keyword-триггер расширяет поверхность: 50 юзеров × 3 заряда = до 150 генераций/300с
  на один чат (насколько позволит Bot API). Bucket per-(chat,user) это не режет.
  **Нужен потолок на чат/день** (RunGuard «budget cap», OpenAI «decision waterfall»:
  лимиты + кредиты как слои одного решения): N генераций на чат в сутки, дальше —
  вежливое молчание (фраза из пула «лимит на сегодня»).
- **Triage-гейт** (openclaw-triage-gate, kotodamai DECISION_LLM_MODEL, GroupGPT
  Intervention Judge): дёшевая LLM «RESPOND/SKIP» (max_tokens=10) перед дорогой →
  −75–90% токенов в «всегда-на» режимах. Для AdminBot НЕ обязателен (триггер и так
  узкий), но это самый дешёвый рычаг при росте keyword-нагрузки. Обязательный контракт:
  **fail-open** (ошибка триажа → отвечать, лучше потратить токены, чем молчать).
- **Семантический кэш** (tianpan): SmartCache TTL 1800с уже есть — расширить ключ на
  (chat_id, user_id, normalized_text): один и тот же вопрос дважды → ответ из кэша без
  LLM. Заодно решает дедуп из 6.2.
- **Circuit breaker** (RunGuard): N LLM-ошибок подряд → тишина 5 минут вместо фразы из
  пула (сейчас каждая ошибка — фраза; при больном LLM это мини-спам).
- **Глобальный per-bot throttle + TelegramRetryAfter** (уже в разделе 3): с keyword
  актуальность растёт — flood-лимиты Telegram считаются на бота целиком
  (grammy.dev/advanced/flood).

### 6.7 Удаление/редактирование сообщений, InaccessibleMessage (R52-5 п.3 — ПОДТВЕРЖДЕНИЕ D214)

**D214 подтверждён тремя источниками: core.telegram.org/bots/api, changelog Bot API,
живой inspect aiogram 3.29.1 (venv проекта):**

1. **delete-updates боту не приходят** — в Bot API нет события удаления сообщений в
   группах. Активного детекта не существует.
2. **`getMessage` удалён из Bot API 8.3** — в aiogram 3.29.1 метода нет (проверено:
   `hasattr(Bot, "get_message") == False`). Активный probe невозможен.
3. **`InaccessibleMessage` = {chat, message_id, date}**, `date == 0` для удалённых
   (проверено: `model_fields == {chat, message_id, date}`, default `date=0`), поле
   `from_user` ОТСУТСТВУЕТ.
4. **Тип `reply_to_message` в aiogram — `Message | None`**: на runtime там может лежать
   InaccessibleMessage; детект D214 `getattr(reply_to, "date", 1) == 0` — корректный
   идиоматичный способ. Отсутствие `from_user` делает `_is_direct_trigger` безопасным
   для InaccessibleMessage (подтверждает 61.6.1).
5. **Чистый quote (выделение текста) НЕ несёт ссылки на оригинал**: `Message.quote` —
   только текст + entities, message_id оригинала в update отсутствует → детект
   удалённого по чистому quote **НЕВОЗМОЖЕН**. Known limitation — подтверждает риск
   из 61.9.
6. **deleteMessage:** свои сообщения — всегда; чужие — только админ/can_delete_messages;
   **лимит 48 часов**; ошибки 400 «message can't be deleted» / 403. Для T-417: 403 →
   фраза (уже в D214), «message not found»-класс 400 → считать удалённым (идемпотентно).
7. **edited_message приходит** (бот получает редактирования видимых сообщений):
   рекомендация — на редактирование СВОИХ ответов обновлять текст в `_bot_replies`
   (цепочка Conversation_Thread остаётся правдивой); на редактирование юзером
   триггерного сообщения НЕ переотвечать (двойной расход, открытый кейс «правка →
   ре-генерация» — не закладываться).
8. **Реакции:** `Bot.set_message_reaction` подтверждён в 3.29.1; админ-права НЕ нужны;
   custom-emoji требуют allowlist (available_reactions); update'ы реакций юзеров бот
   получает только админом + allowed_updates — на это не закладываться.

### 6.8 Интеграции

- **Typing-индикатор:** `ChatActionSender` (aiogram.utils.chat_action) — подтверждён
  в 3.29.1; привязать к `llm.generate` (старт TYPING → стоп после ответа). Уже
  рекомендовано в разделе 2 (стриминг) — typing дешевле стриминга и закрывает 90% UX.
- **Реакции-ack:** при пустом ответе LLM — реакция 👀 на триггер вместо текста
  (Hermes-паттерн, подробно 6.9.2).
- **Веб-поиск/фактчек:** SmartModule (Epic 33) уже консьюмит «найди/проверь» раньше 0h —
  в direct_chat НЕ дублировать; только связка, если понадобится.
- **Кнопки (callback):** «подробнее»/«эскалация» — реактивности не противоречит;
  опционально, не на старте.
- **Мемы/стикеры:** репертуар по настроению (telegram-persona memes.json) — опционально.
- **Force reply — НЕ использовать** (pcraft: путает пользователей).
- **Голос/TTS** (heatherbot, tanya voice notes) — отметка на будущее, не для AdminBot.

### 6.9 Что НЕ делать (анти-паттерны из кейсов)

1. **Выключать Group Privacy без собственного фильтра** → бот отвечает на каждое
   сообщение (tva.sg, OpenClaw, core FAQ). Обратная сторона: keyword-триггер БЕЗ
   выключенного privacy не работает вообще (см. 6.10) — это осознанное ТЗ-решение,
   фильтр в `_is_direct_trigger` уже узкий.
2. **Пустой ответ LLM → текстовая фраза** (Hermes-кейс): `Bad Request: message text is
   empty` → общий except → пул фраз. У AdminBot риск есть ровно такой же
   (send_chunked_reply с пустой строкой). Фикс: `strip()` → пусто = молчание +
   реакция-ack + маркер в память «триггер был, ответа нет».
3. **Force reply** — путает пользователей (pcraft).
4. **SkipHandler** — анти-паттерн aiogram (раздел 5).
5. **Гонки генераций в одном чате:** `handle()` — async, два «бот»-сообщения подряд →
   два параллельных LLM-вызова, ответы могут прийти в обратном порядке (Hermes:
   два триггера в одну секунду → перезапись сессии). Фикс: **per-chat asyncio.Lock**
   вокруг generate (в духе философии T-410 «одно действие»).
6. **Контекст-отравление** (OpenAI cookbook, tianpan): устаревшие факты в саммари
   рулят новыми ходами — `/clear`, must-preserve, лог саммари.
7. **Хардкод списков слов/фраз** — конфиг (раздел 3, повтор; с keyword-веткой
   становится критичным — список будет расти).
8. **Ответы-ошибки как «легитимная история»** (Hermes): фоллбек-фразы не должны
   попадать в память как факты. У AdminBot memorize_facts идёт только после успешной
   отправки — канон соблюдён, не сломать.

### 6.10 Ограничения Bot API (сводно, влияют на фичи)

| Ограничение | Следствие для direct_chat |
|---|---|
| Group Privacy ON: бот видит только команды/reply/mention; каждое сообщение доступно только ОДНОМУ privacy-боту; отключение — BotFather + пере-добавление в каждую группу | **Keyword-триггер «бот» ТРЕБУЕТ privacy Disable** — иначе «бот» в тексте невидим. Задокументировать в README + связать с разделом 1 |
| Боты не видят сообщения других ботов (кроме Bot-to-Bot Communication Mode) | Платформенная анти-петля bot↔bot; режим НЕ включать |
| Flood-лимиты per-bot + retry_after | Глобальный throttle обязателен при keyword (раздел 3) |
| deleteMessage: свои всегда / чужие только с правами, 48 часов | T-417: 403 → фраза (в дизайне); «not found» → идемпотентно удалён |
| InaccessibleMessage {chat, message_id, date=0}; getMessage удалён (8.3) | Только пассивный детект (D214); probe невозможен |
| Чистый quote без message_id оригинала | quote-детект невозможен (known limitation) |
| message_reaction update'ы — только админ + allowed_updates; custom-emoji — allowlist | Реакции бота — «в одну сторону» (бот → чат) |
| edited_message доступен | Обновлять _bot_replies при редактировании своих ответов |

### 6.11 Рекомендации по приоритетам (для Epic 52 и после)

| Приоритет | Рекомендация | Зачем | Сложность |
|---|---|---|---|
| **P0** | Задокументировать Group Privacy Disable (keyword без него не работает) | базовая функциональность | низкая |
| **P0** | per-chat asyncio.Lock вокруг генерации | порядок ответов при спаренных триггерах | низкая |
| **P0** | Глобальный per-bot throttle + TelegramRetryAfter | flood-безопасность (раздел 3) | средняя |
| **P1** | Токен-бюджет + rolling summarization (70–80%) | качество на длинных диалогах | средняя |
| **P1** | Empty-answer guard (strip + реакция вместо фразы) | Hermes-кейс, защита от 400 | низкая |
| **P1** | edited_message → обновление _bot_replies | правдивость Thread-цепочек | низкая |
| **P1** | Дедуп (chat,user,text) через SmartCache-ключ | экономия LLM + анти-флуд | низкая |
| **P2** | Triage-гейт (дёшевая LLM RESPOND/SKIP, fail-open) | −75–90% токенов при росте | средняя |
| **P2** | Дневной бюджет генераций на чат (wallet) | защита от «бот»-марафонов толпой | средняя |
| **P2** | Стилевые якоря + пост-процессинг + typing-индикатор | «человечность» | низкая |
| **P2** | Стоп-фразы / минимум слов / NFKC для keyword-ветки | меньше ложных срабатываний | низкая |

---

## Сводный чек-лист улучшений (приоритет)

1. **Высокий приоритет (надёжность):** глобальный per-bot throttle + обработка
   `TelegramRetryAfter`; персистентность контекста/троттла в БД (переживание рестарта);
   токен-бюджет вместо char-лимитов.
2. **Средний (качество):** суммаризация старого контекста; стриминг + typing-индикатор;
   негативные ключевые слова и паттерн-спам-фильтр (`mention-only`, дедуп); bare-username.
3. **Низкий (фичи):** per-chat persona/mood; внутридиалоговые команды (`/clear`, `/persona`,
   `/tone`); MCP-тулы; документировать Group Privacy + порядок роутеров.
4. **Эпик 52 / keyword-ветка (T-412, детали в разделе 6):** P0 — задокументировать Group
   Privacy Disable (иначе keyword не работает), per-chat lock генераций, глобальный
   per-bot throttle; P1 — токен-бюджет + rolling summarization, empty-answer guard,
   edited_message-обновление `_bot_replies`, дедуп через SmartCache-ключ; P2 — triage-гейт,
   дневной wallet на чат, стилевые якоря/пост-процессинг/typing, стоп-фразы + NFKC +
   минимум слов для keyword-ветки.

## Источники

- aiogram 3.x docs — Filtering events / Magic filters / Middlewares: https://docs.aiogram.dev/en/latest/
- aiogram GitHub Discussion #1550 (SkipHandler анти-паттерн): https://github.com/aiogram/aiogram/discussions/1550
- aiogram GitHub Issue #208 (порядок хендлеров): https://github.com/aiogram/aiogram/issues/208
- aiogram GitHub Issue #942 (явные фильтры): https://github.com/aiogram/aiogram/issues/942
- grammY Flood Limits (глобальные лимиты Telegram per-bot): https://grammy.dev/advanced/flood
- Telegram keyword monitoring 2026 (exclusions, rate limits): https://telega.to/blog/telegram-keyword-monitoring-bot-2026
- Aiogram + Claude case study (тримминг, стриминг, Redis): https://johal.in/build-telegram-bot-python-313-aiogram-310-claude
- LangChain RAG Telegram bot (per-user memory, MMR): https://www.youngju.dev/blog/chatbot/2026-03-03-telegram-langchain-rag-bot-guide.en
- LLM_Memory (гибрид памяти, persona): https://github.com/ArhyPlayer/LLM_Memory
- ai-microcore (стриминг edit_text, typing): https://github.com/Nayjest/ai-microcore
- telebot-pb (mentions, multi-persona, bus, claiming): https://github.com/romanurban/telebot-pb
- tg-spam (mentions-limit, similarity, reputation): https://github.com/umputun/tg-spam
- censor-tg-bot (plugin ratelimit/keyword/regex): https://github.com/capcom6/censor-tg-bot
- rspamd-telegram-bot (flood/repeat, reputation): https://github.com/akey098/rspamd-telegram-bot
- Alya-Bot / TISM (persona, mood): https://github.com/Afdaan/Alya-Bot-Telegram , https://github.com/DisruptiveCollective/TISM
- byeol (ReAct agent, внутридиалоговые команды): https://github.com/openmaya/byeol
- LangChain short-term-memory (summarization): https://docs.langchain.com/oss/javascript/langchain/short-term-memory
- **Epic 52 / T-412 (раздел 6):**
- Telegram Bot API — InaccessibleMessage / deleteMessage / Privacy Mode: https://core.telegram.org/bots/api
- Telegram Bots FAQ (privacy, «одно сообщение — один бот», чужие боты невидимы): https://core.telegram.org/bots/faq
- Bot-to-bot communication (анти-петля на уровне платформы): https://core.telegram.org/api/bots/bot-to-bot
- Bot API changelog (8.3: getMessage удалён): https://core.telegram.org/bots/api-changelog
- tva.sg — scaling Telegram assistant (trigger-сет, silent-log контекста): https://www.tva.sg/insights/scaling-telegram-ai-assistant-solo-to-team
- tva.sg — Hermes tuning (пустой ответ, реакция-ack, конкурентные триггеры): https://www.tva.sg/insights/tuning-hermes-style-agent-grows-with-your-project
- Talon group chat (mention через entities, triggerWords, стриппинг триггера): https://talond.dev/blog/2026-05-01-group-chat/
- OpenClaw — mention-only в группах: https://openclawdocs.com/channels/telegram/group-mentions/
- Papercraft — боты в группах (privacy, force reply против): https://pcraft.dev/book/groups
- aeqi mention-gating (двухслойный ingestion/execution): https://aeqi.ai/docs/patterns/mention-gating
- Anthropic — context engineering (compaction, note-taking, бюджет): https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- OpenAI cookbook — session memory (trimming vs summarization, context poisoning): https://developers.openai.com/cookbook/examples/agents_sdk/session_memory
- tianpan — context window cliff (rolling buffer, entity-preserving, supersession, бюджет): https://tianpan.co/blog/2026-04-19-context-window-cliff-long-conversation-strategies
- niteagent — context window management (слои window/summary/priority, 75% триггер): https://niteagent.com/blog/2026-07-16-agent-context-window-management-guide/
- youngju — multi-turn context management 2026 (типы памяти, Summary Buffer): https://www.youngju.dev/blog/chatbot/2026-03-04-chatbot-multi-turn-context-management-2026.en
- bessavagner — pruning by summarization: https://bessavagner.com/blog/pruning-chat-context-by-summarization/
- Mem0 — LLM chat history summarization (memory formation, decay, conflicts): https://mem0.ai/blog/llm-chat-history-summarization-guide-2025
- kotodamai/telegram-persona (style_rules, contact/group profiles): https://github.com/kotodamai/telegram-persona
- kotodamai/kotodamai-telegram (decision LLM, human simulation, consolidation 1800с): https://github.com/kotodamai/kotodamai-telegram
- icarus (typing-индикатор, задержки, суммирующая память): https://github.com/Ycmelon/icarus
- DIANA (layered SQLite memory, daily mood, факты о юзере): https://github.com/mattabott/diana
- Tanya (SOUL.md, mood/state, heartbeat): https://github.com/opxiahub/tanya
- openclaw-triage-gate (дешёвый триаж RESPOND/SKIP, fail-open): https://github.com/as3445/openclaw-triage-gate
- GroupGPT (Intervention Judge, дешёвый триаж до дорогой LLM): https://arxiv.org/html/2603.01059
- Discord AutoMod (allow_list, стратегии keyword-матчинга): https://docs.discord.com/developers/resources/auto-moderation
- mavibot (match types, «Ignore triggers»): https://mavibot.ai/docs/chatbot-builder-setting-trigger-type
- OpenAI — beyond rate limits (лимиты + кредиты одним waterfall): https://openai.com/index/beyond-rate-limits/
- RunGuard — AutoGen cost control (circuit breaker, budget cap, циклы): https://runguard.dev/blog/autogen-cost-control-loop-detection.html
- hashbot fuzzy mode (NFKC-нормализация имён): https://hashbot.com/docs/fuzzy-mode
- StackOverflow — deleteMessage 400 (права, 48 часов): https://stackoverflow.com/questions/47064078/
