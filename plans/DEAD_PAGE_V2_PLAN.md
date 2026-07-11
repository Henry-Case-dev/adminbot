# План рефакторинга модуля Dead Page v2

> **Статус:** Replanned — user feedback applied (2026-07-11)
> **Задача:** Перевести dead-page посты с расписания на event-driven: репост из @d_pages → forward случайного поста из приватного канала (или fallback на локальные медиа).

---

## 1. Что меняется (user feedback summary)

| # | Изменение | Подробности |
|---|-----------|-------------|
| 1 | Приватный канал | Создан: invite `https://t.me/+5byEeAqnGf40ZDky`, ID `4228645624`. Бот — админ. |
| 2 | Бот НЕ создаёт посты в канале | Бот НЕ генерирует новый контент. Он берёт **существующий случайный пост** из канала и **форвардит** его в чат. |
| 3 | Fallback обязателен | Если канал недоступен или forward fails → fallback на старый механизм (локальный `media/dead_page/`) |
| 4 | Join-триггер Slava остаётся | Параметр `DEAD_PAGE_POST_ON_JOIN`, по умолчанию `True` |
| 5 | morning/evening слоты удалены | Из БД `dead_page_posts` и из кода. Только слоты `repost` и `join`. |
| 6 | Проверка присутствия Slava сохранена | Для будущего масштабирования (может пригодиться) |
| 7 | Остальные функции Slava не трогаем | F1, F3, F4, F5, catch-all — без изменений |
| 8 | Comprehensive logging | Во всём dead_page модуле |
| 9 | Comprehensive tests | Покрытие всех новых функций |

---

## 2. Архитектура: было → стало

```
ДО:
  SchedulerService
    ├─ while True: poll каждые 60с
    ├─ проверка morning/evening слотов
    ├─ pick_random() из локального media/dead_page/
    ├─ sendPhoto (caption 1024 chars) + sendMessage (хвост)
    └─ signal_immediate_post (join trigger)

ПОСЛЕ:
  DeadPageRelay (новый сервис)
    ├─ pick_random_channel_post(chat_id=4228645624)
    │   └─ стратегия: храним last_known_msg_id в БД / config
    │      → random.randint(1, last_known_msg_id)
    │      → forwardMessage в целевой чат
    │      → при ошибке: ретрай с другим random ID (до N попыток)
    ├─ fallback: _send_local_dead_page(chat_id) — старый механизм
    └─ логирование каждого шага

  RepostDetector (новый handler)
    └─ Ловит forward_origin типа MessageOriginChannel с username="d_pages"
       → вызывает DeadPageRelay.send_dead_page(chat_id)

  SchedulerService → упрощается
    └─ Только signal_immediate_post (join trigger) + DEAD_PAGE_POST_ON_JOIN
       Больше НЕ крутит while True / morning / evening логику
```

---

## 3. Детали реализации

### 3.1 Как бот берёт случайный пост из канала

Telegram Bot API не имеет метода «дай случайное сообщение». Стратегия:

1. **Хранить `last_known_message_id`** в таблице `dead_page_posts` или в новой таблице `channel_state` (ключ-значение). Обновлять при каждом успешном форварде (message_id успешного поста = новый максимум).
2. При триггере: `random_id = random.randint(1, last_known_message_id)`.
3. `await bot.forward_message(chat_id=target, from_chat_id=CHANNEL_ID, message_id=random_id)`.
4. Если `BadRequest: message to forward not found` → ретрай до `MAX_FORWARD_RETRIES` раз.
5. Если все ретраи провалились → **fallback**: `_send_local_dead_page()`.

**Начальное значение `last_known_message_id`**: можно установить руками в `.env` (`DEAD_PAGE_CHANNEL_LAST_MSG_ID`) или вычислить через `getUpdates` / `getChat`.

### 3.2 Forward vs Copy

Используем **`forwardMessage`** (не `copyMessage`), потому что:
- Сохраняет оригинальное авторство канала (пометка «Forwarded from»)
- Не требует прав на создание постов (нужен только доступ к каналу)
- Полная подпись / медиа пересылаются как есть

### 3.3 Fallback-механизм

```python
async def send_dead_page(self, target_chat_id: int) -> None:
    """Try channel forward first, fall back to local media."""
    try:
        success = await self._forward_random_post(target_chat_id)
        if not success:
            raise RuntimeError("All forward retries exhausted")
        logger.info(f"Dead page forwarded to chat {target_chat_id}")
    except Exception as e:
        logger.warning(f"Channel forward failed: {e}. Falling back to local media.")
        await self._send_local_dead_page(target_chat_id)
```

### 3.4 Join-триггер

Оставляем текущий механизм в `slava_presence.py` → `scheduler.signal_immediate_post()`, но он теперь вызывает НЕ `_send_dead_page` напрямую, а новый `DeadPageRelay.send_dead_page()`. Параметр `DEAD_PAGE_POST_ON_JOIN` (default `True`) позволяет отключить.

### 3.5 Удаление morning/evening слотов

Из БД: слоты `morning` и `evening` больше не создаются. Таблица `dead_page_posts` теперь содержит только `repost` и `join`. Альтернативно — добавить колонку `timestamp` (Unix time) для анти-спам проверки (cooldown между repost в одном чате).

**Миграция БД (новая схема):**
```sql
-- Добавляем колонку timestamp если её нет
ALTER TABLE dead_page_posts ADD COLUMN timestamp INTEGER;

-- Старые morning/evening записи остаются в БД (история), 
-- но новый код их не создаёт и не проверяет.
```

### 3.6 Анти-спам cooldown

```python
DEAD_PAGE_COOLDOWN_SECONDS: int = 10  # мин. интервал между repost в одном чате
```

Проверка: `SELECT 1 FROM dead_page_posts WHERE chat_id=? AND slot='repost' AND timestamp > ?`

### 3.7 Проверка присутствия Slava

Сохраняется вызов `db.is_present(slavik_id, chat_id)` перед отправкой. Если Slava не в чате — не шлём. Может пригодиться при масштабировании на другие каналы/чаты.

---

## 4. Новые файлы / изменения

| Файл | Действие |
|------|----------|
| `config/settings.py` | Добавить: `DEAD_PAGE_CHANNEL_ID`, `DEAD_PAGE_SOURCE_USERNAME`, `DEAD_PAGE_POST_ON_JOIN`, `DEAD_PAGE_COOLDOWN_SECONDS`, `DEAD_PAGE_CAPTION_MAX_CHARS`, `DEAD_PAGE_MAX_FORWARD_RETRIES`, `DEAD_PAGE_CHANNEL_LAST_MSG_ID`. Удалить: `MORNING_HOUR`, `EVENING_HOUR`, `POLL_INTERVAL`. |
| `.env.example` | Синхронизировать с новыми параметрами |
| `handlers/dead_page_trigger.py` | **Новый:** Router с handler'ом, ловящим репосты из `@d_pages` |
| `services/dead_page_relay.py` | **Новый:** `DeadPageRelay` — forward случайного поста из канала + fallback |
| `services/scheduler.py` | Упростить: убрать `while True` loop, `_tick`, morning/evening. Оставить `signal_immediate_post` (с проверкой `DEAD_PAGE_POST_ON_JOIN`). |
| `services/database.py` | Обновить: убрать `has_post_today` (morning/evening), добавить `was_dead_page_recently` (cooldown), обновить `record_post` (slot + timestamp). |
| `bot.py` | Зарегистрировать `dead_page_router`, инициализировать `DeadPageRelay`, подключить его к `slava_presence` |
| `tests/` | Удалить `test_scheduler.py` (или переписать). Добавить `test_dead_page_relay.py`, `test_dead_page_trigger.py`. Обновить `test_database.py`. |
| `plans/MEMORY.md` | Обновить архитектуру, слоты, схему БД |
| `plans/ARCHITECTURE.md` | Обновить описание F2, диаграмму, router order |

---

## 5. Новые параметры конфигурации

```python
# config/settings.py — изменения:

# УДАЛИТЬ:
#   MORNING_HOUR, EVENING_HOUR, POLL_INTERVAL

# ДОБАВИТЬ:
DEAD_PAGE_CHANNEL_ID: int = 4228645624          # Приватный канал с dead-page постами
DEAD_PAGE_SOURCE_USERNAME: str = "d_pages"       # Канал, репосты из которого триггерят
DEAD_PAGE_POST_ON_JOIN: bool = True              # Слать при входе Slava в чат
DEAD_PAGE_COOLDOWN_SECONDS: int = 10             # Мин. интервал между repost
DEAD_PAGE_CAPTION_MAX_CHARS: int = 1024          # Лимит caption для fallback (старый метод)
DEAD_PAGE_MAX_FORWARD_RETRIES: int = 10          # Макс. попыток найти валидный post_id
DEAD_PAGE_CHANNEL_LAST_MSG_ID: int = 0           # Начальный last_known_message_id (0 = авто)

# ОСТАВИТЬ:
DEAD_PAGE_DIR: str = "media/dead_page"           # Локальная папка (для fallback)
```

---

## 6. Логика handler'а (псевдокод)

```python
# handlers/dead_page_trigger.py

import logging
from aiogram import Router, F, types
from aiogram.types import MessageOriginChannel
from config.settings import settings

logger = logging.getLogger(__name__)

dead_page_router = Router()

# Dependencies injected from bot.py
_relay = None
_db = None

def setup_dead_page(relay, db):
    global _relay, _db
    _relay = relay
    _db = db


@dead_page_router.message(F.forward_origin)
async def on_forward(message: types.Message):
    origin = message.forward_origin

    if not isinstance(origin, MessageOriginChannel):
        logger.debug(f"Forward origin is not a channel: {type(origin).__name__}")
        return

    if origin.chat.username != settings.DEAD_PAGE_SOURCE_USERNAME:
        logger.debug(f"Forward from @{origin.chat.username}, not @{settings.DEAD_PAGE_SOURCE_USERNAME}")
        return

    chat_id = message.chat.id
    logger.info(f"Repost from @{settings.DEAD_PAGE_SOURCE_USERNAME} detected in chat {chat_id}")

    # Anti-spam cooldown
    if _db and await _db.was_dead_page_recently(chat_id, settings.DEAD_PAGE_COOLDOWN_SECONDS):
        logger.debug(f"Cooldown active for chat {chat_id}, skipping")
        return

    # Check Slava presence (future-proofing)
    if _db:
        present = await _db.is_present(settings.SLAVIK_USER_ID, chat_id)
        if not present:
            logger.debug(f"Slava not present in chat {chat_id}, skipping")
            return

    if _relay:
        await _relay.send_dead_page(chat_id)
        if _db:
            await _db.record_dead_page_post(chat_id, slot="repost")
```

---

## 7. Логика DeadPageRelay (псевдокод)

```python
# services/dead_page_relay.py

import random
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from services.media_picker import MediaService
from services.database import DatabaseService

logger = logging.getLogger(__name__)


class DeadPageRelay:
    def __init__(self, bot: Bot, db: DatabaseService, media: MediaService,
                 channel_id: int, max_retries: int = 10):
        self.bot = bot
        self.db = db
        self.media = media
        self.channel_id = channel_id
        self.max_retries = max_retries

    async def send_dead_page(self, target_chat_id: int) -> None:
        """Main entry: try channel forward, fallback to local media."""
        logger.info(f"Sending dead page to chat {target_chat_id}")
        try:
            success = await self._forward_random_post(target_chat_id)
            if not success:
                raise RuntimeError("All forward retries exhausted")
            logger.info(f"Successfully forwarded channel post to chat {target_chat_id}")
        except Exception as e:
            logger.warning(f"Channel forward failed: {e}. Falling back to local media.")
            await self._send_local_dead_page(target_chat_id)

    async def _forward_random_post(self, target_chat_id: int) -> bool:
        """Try to forward a random post from the channel. Returns True on success."""
        last_id = await self.db.get_last_known_message_id(self.channel_id)
        if last_id < 1:
            logger.warning(f"No known message IDs for channel {self.channel_id}")
            return False

        tried = set()
        for attempt in range(self.max_retries):
            msg_id = random.randint(1, last_id)
            if msg_id in tried:
                continue
            tried.add(msg_id)

            try:
                logger.debug(f"Attempt {attempt+1}: forwarding msg_id={msg_id}")
                await self.bot.forward_message(
                    chat_id=target_chat_id,
                    from_chat_id=self.channel_id,
                    message_id=msg_id,
                )
                # Update last known ID
                await self.db.update_last_known_message_id(self.channel_id, max(msg_id, last_id))
                return True
            except TelegramBadRequest as e:
                if "message to forward not found" in str(e).lower():
                    logger.debug(f"Message {msg_id} not found, retrying")
                    continue
                logger.error(f"Unexpected forward error for msg_id={msg_id}: {e}")
                raise
            except Exception as e:
                logger.error(f"Forward attempt {attempt+1} failed: {e}")
                raise

        logger.warning(f"All {self.max_retries} forward attempts exhausted")
        return False

    async def _send_local_dead_page(self, chat_id: int) -> None:
        """Fallback: pick random from local media/dead_page/ (old method)."""
        logger.info(f"Using local media fallback for chat {chat_id}")
        try:
            photo_path, text = await self.media.pick_random()
        except FileNotFoundError as e:
            logger.error(f"Local dead page media missing: {e}")
            return

        from config.settings import settings
        from aiogram.types import FSInputFile

        caption = text[:settings.DEAD_PAGE_CAPTION_MAX_CHARS]
        if len(text) > settings.DEAD_PAGE_CAPTION_MAX_CHARS:
            logger.warning(f"Text truncated: {len(text)} → {len(caption)} chars")

        await self.bot.send_photo(
            chat_id=chat_id,
            photo=FSInputFile(photo_path),
            caption=caption,
        )
        if len(text) > settings.DEAD_PAGE_CAPTION_MAX_CHARS:
            await self.bot.send_message(chat_id=chat_id, text=text[settings.DEAD_PAGE_CAPTION_MAX_CHARS:])
```

---

## 8. Router registration order (bot.py)

```python
# 1. ChatMemberUpdated handler (F1)
dp.include_router(slava_presence_router)

# 2. Kostik router
dp.include_router(kostik_router)

# 3. Alan router
dp.include_router(alan_router)

# 4. Dead Page trigger — NEW (репосты из @d_pages)
dp.include_router(dead_page_router)

# 5. Slava router
dp.include_router(slavik_router)

# 6. Vasya router
dp.include_router(vasya_router)
```

Логика: `dead_page_router` НЕ зависит от пользователя (репост может сделать кто угодно), но фильтруется по `forward_origin`. Должен быть ДО `vasya_router` чтобы текстовые фильтры Васи не перехватили репост раньше времени. Dead page router НЕ конфликтует с user-id-based роутерами (kostik/alan/slavik), потому что у них фильтр по ID пользователя, а dead_page — по forward_origin.

---

## 9. Изменения в slava_presence (join trigger)

```python
# handlers/slava_presence.py — signal_immediate_post теперь вызывает DeadPageRelay

async def on_user_join(event: types.ChatMemberUpdated):
    ...
    if settings.DEAD_PAGE_POST_ON_JOIN and _relay:
        await _relay.send_dead_page(chat_id)
        if _db:
            await _db.record_dead_page_post(chat_id, slot="join")
```

---

## 10. Изменения в БД (database.py)

```python
# УДАЛИТЬ:
#   has_post_today(chat_id, slot) — больше не нужно для morning/evening

# ДОБАВИТЬ:
async def was_dead_page_recently(self, chat_id: int, cooldown_seconds: int) -> bool:
    """Check if dead page was posted in this chat within cooldown window."""
    import time
    threshold = int(time.time()) - cooldown_seconds
    cursor = await self.db.execute(
        "SELECT 1 FROM dead_page_posts WHERE chat_id=? AND slot='repost' AND timestamp > ?",
        (chat_id, threshold)
    )
    row = await cursor.fetchone()
    return row is not None

async def record_dead_page_post(self, chat_id: int, slot: str) -> None:
    """Record a dead page post with timestamp."""
    import time
    now = int(time.time())
    await self.db.execute(
        "INSERT INTO dead_page_posts (chat_id, slot, date, timestamp) VALUES (?, ?, ?, ?)",
        (chat_id, slot, datetime.date.today().isoformat(), now)
    )
    await self.db.commit()

async def get_last_known_message_id(self, channel_id: int) -> int:
    """Get the last known message ID for the channel."""
    cursor = await self.db.execute(
        "SELECT value FROM channel_state WHERE key=?",
        (f"last_msg_id:{channel_id}",)
    )
    row = await cursor.fetchone()
    return int(row["value"]) if row else 0

async def update_last_known_message_id(self, channel_id: int, msg_id: int) -> None:
    """Update the last known message ID for the channel."""
    await self.db.execute(
        "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
        (f"last_msg_id:{channel_id}", str(msg_id))
    )
    await self.db.commit()
```

**Новая таблица `channel_state`** (key-value store):
```sql
CREATE TABLE IF NOT EXISTS channel_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

**Миграция `dead_page_posts`:**
```sql
-- Добавляем timestamp, сохраняем обратную совместимость
ALTER TABLE dead_page_posts ADD COLUMN timestamp INTEGER;
```

---

## 11. Что НЕ меняется

- F1 (Slava return detection) — только обновляется вызов на `DeadPageRelay`
- F3 (GIF counter) — нет изменений
- F4 (KUCHA words) — нет изменений
- F5 (War words) — нет изменений
- F6 (Alan reply engine) — нет изменений
- Catch-all handlers (Kostik, Slava) — нет изменений
- Vasya router — нет изменений
- `media/dead_page/` директория — **сохраняется** для fallback
- MediaService — сохраняется для fallback
- `user_presence` таблица — без изменений

---

## 12. Открытые вопросы (решены)

1. ~~Нужно ли оставить отправку при входе Slava в чат?~~ **Да**, параметр `DEAD_PAGE_POST_ON_JOIN=True` (по умолчанию).
2. ~~Нужен ли fallback без канала?~~ **Да**, обязателен.
3. ~~Что делать с morning/evening слотами?~~ **Удалены** из кода и новых записей в БД. Старые записи остаются как история.
4. ~~Нужна ли проверка на присутствие Slava?~~ **Да**, сохраняется для будущего масштабирования.
5. ~~Как получить случайный пост из канала?~~ Стратегия `random.randint(1, last_known_msg_id)` + ретраи.

---

## 13. Резюме

| Компонент | Было | Стало |
|-----------|------|-------|
| Триггер отправки | Интервал (10:00/20:00) + join | **Репост из @d_pages** + join (опционально) |
| Источник контента | Локальный `media/dead_page/` | **Случайный пост из канала 4228645624** |
| Метод отправки | `sendPhoto` + `sendMessage` (2 поста) | `forwardMessage` (1 пост, сохраняет оригинал) |
| Fallback | Нет | **Локальный `media/dead_page/`** |
| SchedulerService | `while True` loop с sleep(60) | Только `signal_immediate_post` (join) |
| DB слоты | morning, evening, join | **repost, join** |
| Проверка присутствия | Да (is_present) | Да (сохранена) |
| Логирование | Минимальное | Comprehensive (debug/info/warning/error на каждом шаге) |
