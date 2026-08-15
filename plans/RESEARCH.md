# RESEARCH: Telegram API + aiogram 3.x контекст

**Дата исследования:** 2026-08-16 (PM) → **верификация @Architect (T-173-F): 2026-08-16**
**Цель:** фактический контекст для архитектуры Telegram-бота (aiogram 3 + SQLite/aiosqlite + sqlite-vec + FTS5 + APScheduler + OpenAI-совместимый LLM API).

> ✅ **T-173-F выполнен (@Architect, 2026-08-16).** Данные ниже верифицированы/дополнены инструментами
> из требования R18. Ограничения инструментов зафиксированы в секции «Методология». Нумерация секций
> a)–h) сохранена, правки — инлайном в секциях + новые блоки «T-173-F» в конце секций e), g), h).

---

## Методология исследования (context7 + duckduckgo/exa) — T-173-F, 2026-08-16

| Инструмент | Статус | Что получено |
|------------|--------|--------------|
| **context7** (`context7_resolve-library-id` + `context7_query-docs`) | ❌ НЕДОСТУПЕН — MCP-сервер возвращает `Invalid API key. Please check your API key. API keys should start with 'ctx7sk' prefix` (проблема конфигурации сервера, не transient: 2 попытки) | — |
| **duckduckgo** (MCP `duckduckgo_web_search`) | ❌ НЕДОСТУПЕН — `DDG detected an anomaly in the request, you are likely making requests too quickly` (2 попытки) | — |
| **exa** (`exa_web_search_exa`, `exa_web_fetch_exa`) — резервный инструмент по R18 | ✅ РАБОТАЕТ | Telegram-лимиты (4096, 1 msg/s/чат, 20 msg/min группа, ~30 msg/s глобально), sqlite-vec issue #45 (Windows MSVC), FTS5 токенизация/BM25, aiogram+APScheduler паттерны, DeepSeek OpenAI-совместимость |
| **webfetch** (docs.aiogram.dev, документация aiogram 3.30.0) | ✅ РАБОТАЕТ (страницы тяжёлые, контент подтверждён — сигнатуры и версии совпали с уже зафиксированными данными) | BaseMiddleware, Router/Dispatcher, aiogram 3.30.0 актуальна |

**Правило на будущее:** context7 и duckduckgo в текущей конфигурации среды недоступны; рабочий стек для верификации — exa + webfetch официальных доков.

### Новые данные, полученные при верификации (2026-08-16)

1. **sqlite-vec Windows (важно, RESEARCH §e):** PyPI-колесо до v0.1.2-alpha.9 собиралось MinGW → MSVC-Python (python.org / Microsoft Store) падал с `The specified module could not be found` (issue asg017/sqlite-vec#45, #13). **С v0.1.2-alpha.9 автор перешёл на MSVC-сборку** — на Windows 11 + CPython 3.11/3.12 загрузка работает; в issue #13 подтверждено закрытие. Вывод: ставить `sqlite-vec>=0.1.2` (не alpha), но try/except при `load_extension` ВСЁ РАВНО обязателен (R3) — на проде и локально возможны любые окружения.
2. **Per-connection загрузка подтверждена на практике** (basic-memory issue #735): модуль vec0 регистрируется **на каждое соединение отдельно**; «no such module: vec0» на другом соединении — классический баг. В aiosqlite: `await db.enable_load_extension(True)` / `await db.load_extension(path)` (aiosqlite ≥ 0.20, async-методы) сразу после `connect()`.
3. **FTS5:** `unicode61` — регистронезависимый, без стемминга для русского; для fallback-поиска по русскому использовать точные токены и префиксы `term*`; `ORDER BY rank` (BM25); ввод от пользователя в MATCH — экранировать (оборачивать в кавычки), чтобы символы `"`, `*` не ломали парсер.
4. **APScheduler + aiogram 3 (актуальные примеры 2025–2026):** `AsyncIOScheduler` в том же event loop; `scheduler.start()` до `dp.start_polling(bot)`; `scheduler.shutdown()` в `finally`; `CronTrigger(hour="0,6,12,18", minute=0)`; ловить `aiogram.exceptions.TelegramRetryAfter` → `await asyncio.sleep(e.retry_after)`; persistent jobstore (SQLAlchemyJobStore) — ошибки pickle (`cannot pickle 'SSLContext' object`), использовать ТОЛЬКО MemoryJobStore.
5. **OpenAI-совместимый контракт (DeepSeek/шлюзы, 2026):** `/chat/completions` + `/embeddings`, `Authorization: Bearer`; шлюзы-агрегаторы (включая apinet.cloud) следуют этому контракту; base_url выносить в конфиг (`https://apinet.cloud/v1`), модель в конфиг; ответ `choices[0].message.content`; эмбеддинги `data[0].embedding`.

---

## a) aiogram 3.x: структура проекта, Router/Dispatcher, middleware, команды, Message.answer, лимит 4096

**Актуальная версия:** 3.30.0 (docs.aiogram.dev/en/latest). Требует Python 3.9+.

**Базовая структура:**
```python
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

bot = Bot(token=..., default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()

@router.message(CommandStart())
async def start(message: Message): ...
@router.message(Command("search"))
async def search(message: Message): ...

dp.include_router(router)      # роутеры вкладываются; Dispatcher сам является Router
await dp.start_polling(bot)    # long polling в текущем event loop
```

**BaseMiddleware — сигнатура (официально, docs.aiogram.dev):**
```python
from aiogram import BaseMiddleware
from typing import Any, Awaitable, Callable, Dict
from aiogram.types import TelegramObject, Message

class CounterMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data['counter'] = 1
        return await handler(event, data)
```

**Критично: как молчаливо прервать событие.** Официальная документация: "Middleware should always call `await handler(event, data)` to propagate event... **If you want to stop processing event in middleware you should not call `await handler(event, data)`**". То есть просто `return` (вернуть None) без вызова `handler` — апдейт молча отбрасывается, хендлер не выполняется. Исключения `CancelHandler`/`CancelUpdate` — внутренние механизмы диспетчера (используются фильтрами и внутри aiogram); в собственной middleware достаточно не вызывать `await handler(event, data)`.

**Два уровня регистрации middleware:**
- Outer (до фильтров): `dp.update.outer_middleware(...)` / `router.message.outer_middleware(...)` — вызывается на каждое событие.
- Inner (после фильтров, перед handler): `router.message.middleware(...)` — вызывается только когда фильтры прошли; в `data["handler"]` доступен выбранный хендлер (можно читать его атрибуты).

**Message.answer():** у объекта `Message` есть алиасы API-методов — `await message.answer(text)` автоматически подставляет `chat_id` текущего чата и вызывает `SendMessage`. Аналог напрямую: `await bot.send_message(chat_id=message.chat.id, text=...)`. `parse_mode` задаётся глобально через `DefaultBotProperties(parse_mode=ParseMode.HTML)` или per-call параметром.

**Лимит 4096:** Bot API принимает `text` длиной 1–4096 символов **после парсинга entities**. Длинные ответы (LLM) нужно резать на чанки ≤ 4096 и отправлять последовательно; разрывать по границам слов/абзацев.

---

## b) aiogram 3.x: медиа, user id/username/nickname, reply_to_message

**Поля `Message` (актуальная модель aiogram):**
- `message.from_user: User | None` — у `User`: `id` (int), `username` (str | None, без @), `first_name` (str), `last_name` (str | None), `full_name` (property).
- `message.photo: list[PhotoSize] | None` — список размеров; брать самый большой: `max(message.photo, key=lambda p: p.width * p.height)` → `file_id`.
- `message.video: Video | None` (имеет `file_id`, `duration`).
- `message.text: str | None`, `message.caption: str | None` (подпись к медиа).
- `message.reply_to_message: Message | None` — сообщение, на которое ответили. **Важно:** внутри `reply_to_message` поля `reply_to_message` уже НЕ будет (только один уровень вложенности).
- `message.media_group_id: str | None`.

**Фильтры:** `F.photo`, `F.video`, `F.text`, `F.reply_to_message`, `F.from_user.id == X`, `Command("x")`, `CommandStart()`.

**Отправка медиа:** `await message.answer_photo(photo=file_id_or_InputFile, caption="...")`, `await message.answer_video(...)`, `bot.send_photo(chat_id, photo, caption)`. Для файлов из памяти: `aiogram.types.BufferedInputFile(data: bytes, filename=...)` или `FSInputFile(path)`.

**Получение файла по file_id:** `file = await bot.get_file(file_id)` → `file.file_path`; скачивание: `await bot.download_file(file.file_path)` или `await bot.download(file, destination)`.

---

## c) APScheduler (AsyncIOScheduler) + aiogram

- `AsyncIOScheduler` работает в **том же** event loop, что и aiogram — один процесс, никаких тредов/мостов. Совместимо, т.к. aiogram 3 async-only.
- Таймзона: `scheduler = AsyncIOScheduler(timezone="Asia/Yekaterinburg")` и/или в триггере: `CronTrigger(hour=9, minute=0, timezone="Asia/Yekaterinburg")`.
- Регистрация: `scheduler.add_job(func, trigger=CronTrigger(...), kwargs={"bot": bot})`; `scheduler.start()` до `dp.start_polling(bot)`; `scheduler.shutdown()` в `finally`.
- Строковые TZ-имена работают через pytz/zoneinfo; APScheduler 3.x (3.10+) понимает и `zoneinfo.ZoneInfo`.

**Ошибка-ловушка:** НЕ использовать `SQLAlchemyJobStore`/персистентные jobstore с async-функциями — ошибка `TypeError: cannot pickle 'SSLContext' object` / `cannot pickle '_asyncio.Future' object`. Для простых задач достаточно дефолтного `MemoryJobStore`; периодика воссоздаётся при старте.

**Паттерн защиты от Telegram rate limits в задаче:** ловить `aiogram.exceptions.TelegramRetryAfter` и `await asyncio.sleep(e.retry_after)`, либо заранее вставлять `await asyncio.sleep(1)` между массовыми отправками.

---

## d) aiosqlite: асинхронные паттерны

```python
import aiosqlite

async with aiosqlite.connect("data.db") as db:      # авто-закрытие
    db.row_factory = aiosqlite.Row                   # доступ row['col'] и row[0]
    await db.execute("CREATE TABLE IF NOT EXISTS t(id INTEGER PRIMARY KEY, name TEXT)")
    await db.executemany("INSERT INTO t(name) VALUES (?)", [("a",), ("b",)])  # батч
    await db.commit()

    async with db.execute("SELECT * FROM t WHERE name LIKE ?", ("a%",)) as cur:
        async for row in cur:                        # row — aiosqlite.Row
            print(row["name"])
```

- Одно соединение = один внутренний thread с очередью запросов (все операции сериализуются, блокировки event loop нет). Для одного бота достаточно одного соединения; для конкурентного чтения можно открывать отдельные read-only соединения (`file:...?mode=ro`, `uri=True`).
- `await db.execute(...)` + `await db.commit()` обязательны (автокоммита нет); `db.total_changes` доступен.
- Индексы: `await db.execute("CREATE INDEX IF NOT EXISTS idx_t_name ON t(name)")`.
- PRAGMA: `journal_mode = WAL`, `busy_timeout = 5000`, `foreign_keys = ON`.

---

## e) sqlite-vec: установка, загрузка, vec0, KNN, проблемы Windows

**Установка:** `pip install sqlite-vec`. Векторы хранятся как BLOB (serialize: `struct.pack(f"{n}f", *vec)`).

**Загрузка в обычный sqlite3:**
```python
import sqlite3, sqlite_vec
db = sqlite3.connect(":memory:")
db.enable_load_extension(True)
sqlite_vec.load(db)                    # эквивалент db.load_extension(sqlite_vec.loadable_path())
db.enable_load_extension(False)
```

**Загрузка в aiosqlite (>= 0.20 есть async-методы):**
```python
import aiosqlite, sqlite_vec
db = await aiosqlite.connect("data.db")
await db.enable_load_extension(True)
await db.load_extension(sqlite_vec.loadable_path())   # путь к vec0.dll/so
await db.enable_load_extension(False)
```
Запасной вариант (private API, работает): `db._conn.enable_load_extension(True); db._conn.load_extension(path)` — но предпочтительны публичные async-методы. **Расширение загружается per-connection** — при пуле соединений грузить на каждом.

**vec0-таблица и KNN:**
```sql
CREATE VIRTUAL TABLE vec_items USING vec0(embedding float[768]);
INSERT INTO vec_items(rowid, embedding) VALUES (?, ?);   -- embedding = serialize_f32(list)

SELECT rowid, distance
FROM vec_items
WHERE embedding MATCH ?
ORDER BY distance
LIMIT 10;                          -- или: AND k = 10
```
- По умолчанию метрика L2; можно `distance_metric=cosine` в определении колонки.
- Доп. колонки: metadata (в WHERE KNN), partition key, auxiliary (`+col`) — для хранения текста/данных рядом с вектором.
- Альтернатива без vec0: обычная таблица + `vec_distance_cosine()/vec_distance_L2()` + ORDER BY.

**Известные проблемы Windows (issue asg017/sqlite-vec#45):**
- Python MSVC-сборки (официальный python.org / Microsoft Store) часто не могут загрузить DLL из PyPI-колеса (оно собрано MinGW): ошибка `sqlite3.OperationalError: The specified module could not be found`.
- Работает: Anaconda Python, MinGW-сборки Python; на macOS системный Python вообще без `enable_load_extension` (нужен Homebrew Python).
- Обходной путь: собрать vec0.dll самому через MSVC (`cl sqlite-vec.c -link -dll -out:sqlite-vec.dll`) или использовать запасной путь поиска (см. "Ключевые выводы").

> ✅ **T-173-F (2026-08-16):** с релиза **v0.1.2-alpha.9** (MSVC-сборка колеса) загрузка на Windows 11 +
> CPython 3.11/3.12 подтверждена работающей (issue #13 закрыт). Рекомендация: `sqlite-vec>=0.1.2`
> в requirements; **try/except вокруг load_extension обязателен в любом случае** (R3).

---

## f) SQLite FTS5: фоллбек текстового поиска

FTS5 **встроен в SQLite** (не требует загрузки расширений — важное преимущество как fallback).

```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(text);

-- MATCH: слово/фраза/префикс/булева логика
SELECT rowid, text FROM messages_fts WHERE messages_fts MATCH 'sqlite';        -- слово
SELECT * FROM messages_fts WHERE messages_fts MATCH '"точная фраза"';         -- фраза
SELECT * FROM messages_fts WHERE messages_fts MATCH 'trig*';                  -- префикс
SELECT * FROM messages_fts WHERE messages_fts MATCH 'a AND b NOT c';          -- логика
SELECT * FROM messages_fts WHERE messages_fts MATCH 'title:sqlite';           -- по колонке

-- BM25-ранжирование: чем МЕНЬШЕ rank, тем релевантнее
SELECT * FROM messages_fts WHERE messages_fts MATCH ? ORDER BY rank;
SELECT * FROM messages_fts WHERE messages_fts MATCH ? ORDER BY bm25(messages_fts, 10.0, 1.0);  -- веса колонок
```
- Дефолтный токенизатор `unicode61` — для русского языка работает по словам (без стемминга; `tokenize='porter'` — только английский). Для русского фоллбек-поиск по точным токенам/префиксам приемлем.
- MATCH регистронезависимый; `rank` — скрытая колонка; `ORDER BY rank` быстрее `ORDER BY bm25(ft)`.

> ✅ **T-173-F (2026-08-16):** пользовательский ввод в `MATCH` экранировать (кавычки вокруг фразы);
> `*`, `"`, `AND/OR/NOT` в тексте запроса — синтаксис FTS5. Для нашего fallback-поиска запрос строится
> ПРОГРАММНО из токенов окна L1 (не сырой пользовательский ввод) — обязательная обёртка-санитайзер.

---

## g) Telegram Bot API: лимиты, sendMessage, parse_mode

**Официальные лимиты (core.telegram.org/bots/faq):**
- Текст сообщения: **1–4096 символов** (после парсинга entities); подпись к медиа: 1024.
- **Не более ~1 сообщения в секунду в один чат** (короткие всплески допускаются, затем 429).
- **В группе — не более 20 сообщений в минуту**.
- Глобальная рассылка: ~30 msg/sec на бота (платные broadcasts — до 1000 msg/sec, требуют 100k Stars).
- При 429: поле `retry_after` (сек) — в aiogram исключение `TelegramRetryAfter`.
- Файлы: отправка до 50 МБ, `getFile` работает для файлов до 20 МБ.
- file_id можно считать постоянными.

**sendMessage (HTTP):**
```
POST https://api.telegram.org/bot<token>/sendMessage
{ "chat_id": <id>, "text": "...", "parse_mode": "HTML" | "MarkdownV2" }
```
parse_mode: HTML и MarkdownV2; в aiogram — `ParseMode.HTML` / `ParseMode.MARKDOWN_V2`.

---

## h) OpenAI-совместимый API (apinet.cloud)

**Стандартный OpenAI-совместимый контракт (его держат все шлюзы, включая apinet.cloud):**
```
POST <base>/v1/chat/completions
Authorization: Bearer <key>
{ "model": "...", "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
  "temperature": 0.7, "max_tokens": 1024 }
→ choices[0].message.content

POST <base>/v1/embeddings
{ "model": "...", "input": "текст" | ["текст1", ...] }
→ data[0].embedding: [float, ...]
```
- `temperature`: 0..2 (0 — детерминированно); `max_tokens` — лимит генерации.
- Ошибки: HTTP 400/401/403/429/500 + JSON `{"error": {"message": ..., "type": ...}}`; 429 — rate limit.
- Через httpx: `httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))`; ловить `httpx.TimeoutException`, `httpx.HTTPStatusError`, а также JSON-парсинг в try/except. **Асинхронный клиент переиспользовать** (одна сессия на приложение) либо закрывать в `async with`.
- Размерность эмбеддингов зависит от модели — определять из ответа при инициализации и хранить в схеме БД (колонка `float[dim]`).

**apinet.cloud специфика:** это "AI API Gateway" (агрегатор моделей). Сайт JS-heavy: статическая документация по URL https://apinet.cloud/docs не отдаёт текстовый контент; страницы /pricing, /docs существуют, но деталей в статике нет; поддержка — Telegram @apinet_support. **Вывод для архитектуры:** точный base URL и список моделей проверять в рантайме через `GET /v1/models` (или из личного кабинета); формат запросов считать OpenAI-совместимым (`/v1/chat/completions`, `/v1/embeddings`) и заложить конфигурационные параметры (base_url, model_chat, model_embedding, api_key) в env/config, а не хардкодить.

---

## Ключевые выводы и риски (для архитектуры)

1. **Прерывание апдейта в middleware aiogram 3:** официальный способ — НЕ вызывать `await handler(event, data)` (просто `return None`). `CancelUpdate`/`CancelHandler` — внутренние исключения aiogram, в пользовательской middleware их использовать не обязательно.
2. **Лимит 4096:** резать все ответы бота (особенно LLM-генерацию) на чанки ≤ 4096 по границам абзацев/предложений; HTML-разметка считается до парсинга — не разрывать entity-теги посередине.
3. **Rate limits:** 1 msg/sec/чат и 20 msg/min в группе → в рассылке/периодике: sleep(1) между отправками в один чат, ловить `TelegramRetryAfter` (sleep на `retry_after`), в группах не слать чаще 1 раза в 3+ сек.
4. **sqlite-vec на Windows — главный технический риск:** MSVC-Python (python.org / Microsoft Store) часто не грузит DLL из pip-колеса. Необходимо: (а) пробная загрузка расширения на старте с graceful fallback; (б) запасной путь — FTS5 (встроенный, работает везде) + при необходимости brute-force cosine в чистом Python для малых коллекций; (в) документировать Anaconda/Mingw-вариант и самостоятельную сборку MSVC DLL.
5. **Расширение грузится per-connection:** в aiosqlite использовать `await db.enable_load_extension(True)` / `await db.load_extension(path)` (aiosqlite ≥ 0.20) сразу после открытия каждого соединения.
6. **APScheduler:** только `MemoryJobStore` с async-задачами (persistent jobstore ломается на pickle); scheduler.start() до start_polling; shutdown() в finally; TZ="Asia/Yekaterinburg" в конструкторе и/или CronTrigger.
7. **FTS5 и русский:** токенизатор unicode61 без стемминга — приемлемо для поиска по точным словам и префиксам (`term*`); `ORDER BY rank` (меньше = релевантнее).
8. **apinet.cloud:** документация в статике недоступна; контракт OpenAI-совместимый, но base URL/модели подтверждать в рантайме (`/v1/models`) и выносить в конфиг; обязательны таймауты и обработка 429/5xx на стороне httpx.
9. **aiogram Message:** `from_user`, `photo` (брать максимальный PhotoSize), `video`, `caption`, `reply_to_message` (без вложенных reply) — всё доступно напрямую; `message.answer()`/`answer_photo()`/`answer_video()` с авто-подстановкой chat_id.

---

## Источники

- https://docs.aiogram.dev/en/latest/ (главная; версия 3.30.0)
- https://docs.aiogram.dev/en/latest/dispatcher/middlewares.html (BaseMiddleware, сигнатура, прерывание события)
- https://docs.aiogram.dev/en/latest/dispatcher/router.html (Router/Dispatcher)
- https://docs.aiogram.dev/en/latest/api/types/message.html (поля Message, алиасы answer*)
- https://docs.aiogram.dev/en/latest/api/methods/send_message.html (sendMessage)
- https://botfather.dev/news/lifecycle-of-an-update-in-aiogram (жизненный цикл апдейта, middleware)
- https://core.telegram.org/bots/faq (лимиты: 1 msg/sec, 20 msg/min в группе, ~30 msg/sec, 50 МБ/20 МБ)
- https://core.telegram.org/bots/api#sendmessage (формат sendMessage, 1–4096 символов, parse_mode)
- https://aiosqlite.omnilib.dev/ (паттерны aiosqlite)
- https://aiosqlite.omnilib.dev/en/v0.22.1/api.html (async enable_load_extension/load_extension)
- https://alexgarcia.xyz/sqlite-vec/python.html (Python-интеграция sqlite-vec)
- https://alexgarcia.xyz/sqlite-vec/features/knn.html (vec0 KNN, distance_metric)
- https://alexgarcia.xyz/sqlite-vec/features/vec0.html (типы колонок vec0)
- https://alexgarcia.xyz/sqlite-vec/compiling.html (компиляция DLL на Windows)
- https://github.com/asg017/sqlite-vec/issues/45 (проблема загрузки DLL на Windows MSVC Python)
- https://www.sqlite.org/fts5.html (FTS5: MATCH, bm25, rank)
- https://coddy.tech/docs/ru/sqlite/full-text-search (FTS5 на русском: MATCH-синтаксис, BM25)
- https://dev.to/castanderness/auto-posting-telegram-channel-bot-with-apscheduler-and-aiogram-3-kfe (AsyncIOScheduler + aiogram 3)
- https://stackoverflow.com/questions/76846860/how-can-i-send-a-message-in-telegram-with-apscheduler-and-aiogram (pickle-ошибки jobstore)
- https://stackoverflow.com/questions/72245946/setting-timezone-in-asyncioscheduler (настройка TZ в AsyncIOScheduler)
- https://apinet.cloud/ , https://apinet.cloud/docs , https://apinet.cloud/pricing (apinet.cloud, поддержка @apinet_support)
- https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/ (эталон OpenAI-совместимых /v1/chat/completions и /v1/embeddings)

### Источники, добавленные при верификации T-173-F (2026-08-16, exa + webfetch)

- https://core.telegram.org/bots/api + https://core.telegram.org/bots/faq — лимиты подтверждены: текст 1–4096 после парсинга entities; «avoid sending more than one message per second» в чат; «Bots cannot send more than 20 messages per minute to the same group»; ~30 msg/s глобально (exa, 2026-08-16)
- https://github.com/asg017/sqlite-vec/issues/13 — статус MSVC-колеса v0.1.2-alpha.9+, подтверждение фикса на Windows 11/Python 3.11–3.12 (exa, 2026-08-16)
- https://github.com/basicmachines-co/basic-memory/issues/735 — per-connection загрузка sqlite-vec: «no such module: vec0» на другом соединении пула (exa, 2026-08-16)
- https://audrey.feldroy.com/articles/2025-01-13-SQLite-FTS5-Tokenizers-unicode61-and-ascii — поведение unicode61: регистронезависимость, split по пунктуации, диакритика (exa, 2026-08-16)
- https://wiki.r-that.com/patterns/sqlite-fts5-search/ — FTS5 external-content + триггеры, экранирование MATCH-ввода (exa, 2026-08-16)
- https://apitube.io/blog/post/telegram-news-bot-python — aiogram 3.27 + AsyncIOScheduler в одном event loop, TelegramRetryAfter-паттерн (exa, 2026-08-16)
- https://api-docs.deepseek.com/ — DeepSeek OpenAI-совместимый контракт (base_url, api_key, model, messages) — эталон для apinet.cloud-шлюза (exa, 2026-08-16)
- https://docs.aiogram.dev/en/latest/ — aiogram 3.30.0 актуальна; сигнатуры BaseMiddleware/SendMessage подтверждены (webfetch, 2026-08-16)
