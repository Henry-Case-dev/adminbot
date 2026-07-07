# ARCHITECTURE.md — AdminBot

> **Версия:** v1.0.0
> **Дата:** 2026-07-07
> **Назначение:** Единый источник истины (Single Source of Truth) для Builder. Каждый обработчик, каждый фильтр, каждый SQL-запрос описан здесь.

---

## 1. Directory Structure (Final)

```
C:\Code\Python\adminbot\
├── bot.py                          # Entry point: build Dispatcher, register routers, start polling
├── requirements.txt                # Pinned dependencies
├── .env                            # API_TOKEN=<token> (git-ignored)
├── .env.example                    # API_TOKEN=your_token_here
├── README.md                       # F8: Ironic documentation
│
├── config/
│   ├── __init__.py
│   └── settings.py                 # Dataclass + dotenv loader; global singleton `settings`
│
├── filters/
│   ├── __init__.py
│   ├── user_id.py                  # UserIdFilter(BaseFilter) — reusable for any user
│   ├── vasya_name.py              # VasyaFilter(BaseFilter) — regex "вас[иеёяю]"
│   ├── admin_word.py              # StrictAdminFilter(BaseFilter) — exact word "админ"
│   ├── kucha_word.py              # KuchaWordFilter(BaseFilter) — "куч[аиеуюйе]" (F4)
│   └── war_word.py                # WarWordFilter(BaseFilter) — 21 war word + synonym (F5)
│
├── handlers/
│   ├── __init__.py
│   ├── kostik.py                   # Kostik catch-all: "пошёл нахуй кринжатура ебаная"
│   ├── slavik.py                   # Slava router: middleware(F3) + F4 + F5 + catch-all
│   ├── vasya.py                    # Vasya/Admin filters + handlers
│   ├── alan.py                      # Alan_Z reply engine: every 10 msgs → random reply (F6)
│   └── slava_presence.py           # ChatMemberUpdated handler (F1) + new_chat_members fallback
│
├── services/
│   ├── __init__.py
│   ├── database.py                 # DatabaseService — aiosqlite query executor
│   ├── media_picker.py             # MediaService — random jpg + random txt from dead_page/
│   ├── scheduler.py                # SchedulerService — asyncio background loop (F2)
│   └── message_counter.py          # MessageCounterMiddleware — aiogram inner middleware (F3)
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Shared fixtures: mock bot, mock message, in-memory DB, event loop
│   ├── test_kostik.py
│   ├── test_slavik_handlers.py     # Slava handlers (F4 + F5 + catch-all)
│   ├── test_filters.py             # All 6 filter unit tests
│   ├── test_edge_cases.py          # Cross-component edge cases
│   ├── test_message_counter.py     # F3: GIF counter middleware
│   ├── test_slava_presence.py      # F1: Slava join/leave detection
│   ├── test_scheduler.py           # F2: scheduler loop logic
│   ├── test_media_picker.py        # F2: media file picker
│   ├── test_alan.py                # F6
│   ├── test_vasya.py
│   └── test_database.py            # DB service unit tests
│
├── media/
│   ├── slavic_chlen.mp4            # 1.1MB mp4 for F3 GIF
│   └── dead_page/
│       ├── page_1.txt              # Obituary text (19 lines, UTF-8)
│       └── slavic_ava.jpg          # Photo (35KB)
│
└── plans/
    ├── ARCHITECTURE.md             # ← THIS FILE
    ├── MEMORY.md
    ├── board.md
    └── backlog.md
```

**Migration notes:**
- `vasya_module.py` → removed (logic moves to `handlers/vasya.py` + `filters/vasya_name.py` + `filters/admin_word.py`)
- `kostik_module.py` → removed (logic moves to `handlers/kostik.py` + `filters/user_id.py`)
- `slavik_module.py` → removed (logic moves to `handlers/slavik.py` + `filters/user_id.py` + `services/message_counter.py`)
- `local_database.db` → kept, schema created on first run by `DatabaseService.initialize()`

---

## 2. Component Dependency Diagram

```
┌─────────────────────────────────────────────────────────┐
│  bot.py (entry point)                                    │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Dispatcher                                       │   │
│  │                                                   │   │
│  │  REGISTRATION ORDER (TOP → BOTTOM = FIRST CHECK): │   │
│  │                                                   │   │
│  │  1. ChatMemberUpdated handler  (F1)               │   │
│  │     └─ imports handlers/slava_presence.py         │   │
│  │                                                   │   │
│  │  2. kostik_router  (user_id=350803143)            │   │
│  │     └─ imports handlers/kostik.py                 │   │
│  │        └─ imports filters/user_id.py              │   │
│  │                                                   │   │
│  │  3. alan_router     (user_id=138811255) + DB counter         │   │
│  │     └─ imports handlers/alan.py                               │   │
│  │        └─ imports filters/user_id.py               │   │
│  │                                                   │   │
│  │  4. slavik_router  (user_id=479167456)            │   │
│  │     └─ imports handlers/slavik.py                 │   │
│  │        ├─ middleware: MessageCounterMiddleware    │   │
│  │        │  └─ imports services/message_counter.py  │   │
│  │        │     └─ imports services/database.py      │   │
│  │        ├─ handler F4: KuchaWordFilter             │   │
│  │        │  └─ imports filters/kucha_word.py        │   │
│  │        ├─ handler F5: WarWordFilter               │   │
│  │        │  └─ imports filters/war_word.py          │   │
│  │        └─ catch-all handler                       │   │
│  │           └─ imports filters/user_id.py           │   │
│  │                                                   │   │
│  │  5. vasya_router  (text filters, no user restrict)│   │
│  │     └─ imports handlers/vasya.py                  │   │
│  │        ├─ VasyaFilter → "АДМИН"                   │   │
│  │        │  └─ imports filters/vasya_name.py        │   │
│  │        └─ StrictAdminFilter → "ВАСЯ"              │   │
│  │           └─ imports filters/admin_word.py        │   │
│  │                                                   │   │
│  │  BACKGROUND TASKS (started in bot.py main()):      │   │
│  │  ┌─────────────────────────────────────────────┐  │   │
│  │  │ scheduler_task (F2)                          │  │   │
│  │  │  └─ imports services/scheduler.py            │  │   │
│  │  │     ├─ imports services/database.py          │  │   │
│  │  │     └─ imports services/media_picker.py      │  │   │
│  │  └─────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘

SHARED DEPENDENCIES (imported by many):
┌──────────────────────┐    ┌──────────────────────┐
│ config/settings.py    │    │ services/database.py  │
│ (Settings dataclass)  │    │ (aiosqlite wrapper)   │
└─────────┬────────────┘    └──────────┬────────────┘
          │                            │
    bot.py, scheduler.py          scheduler.py,
                                  message_counter.py,
                                  slava_presence.py
```

**Import rules:**
- `handlers/` NEVER import from other `handlers/` modules (each is self-contained)
- `filters/` NEVER import from `handlers/` or `services/`
- `services/` can import from `config/` and other `services/` (only DB is shared)
- `bot.py` is the ONLY module that imports routers and wires them together
- `config/settings.py` has NO internal imports (pure dataclass + os.environ)

---

## 3. Data Flow for Each Feature

### F1 — Slava Return Detection

```
TRIGGER: Telegram sends ChatMemberUpdated or Message with new_chat_members

ChatMemberUpdated flow:
  Telegram API
    → Dispatcher.chat_member handler
    → slava_presence.py::on_slava_chat_member(update: ChatMemberUpdated)
    → Check: update.new_chat_member.user.id == 479167456
      AND update.old_chat_member.status in ('left','kicked','restricted')
      AND update.new_chat_member.status == 'member'
    → update.bot.send_message(chat_id, "ДОЛБОЕБ ВЕРНУЛСЯ")
    → DatabaseService.set_slava_present(chat_id, user_id, True)
    → SchedulerService.signal_immediate_post(chat_id)  [see F2 below]
    → (scheduler resumes if it was paused)

Message.new_chat_members fallback:
  Telegram API
    → Dispatcher.message handler (via dedicated router)
    → slava_presence.py::on_new_chat_members(message: Message)
    → Check: any(u.id == 479167456 for u in message.new_chat_members)
    → message.answer("ДОЛБОЕБ ВЕРНУЛСЯ")
    → Same DB + scheduler steps as above

LEAVE detection (sets presence=False, pauses scheduler):
  ChatMemberUpdated with old_status='member', new_status='left'/'kicked'
    → DatabaseService.set_slava_present(chat_id, user_id, False)
```

**Edge cases:**
- Duplicate join events (Telegram may send both ChatMemberUpdated + new_chat_members): dedup via DB flag — `set_slava_present` is idempotent, `signal_immediate_post` checks if already posted in last 10 seconds.
- Bot restart while Slava is present: DB stores presence, scheduler picks up state on startup.
- Slava in multiple chats: DB key is `(user_id, chat_id)`.

### F2 — Dead Page Posts

```
── POST TRIGGERS ───────────────────────────────────

ON JOIN (immediate):
  F1 handler → SchedulerService.signal_immediate_post(chat_id)
    → scheduler checks DB: has this chat been posted in last 10 seconds?
    → if NO: MediaService.pick_random() → send_photo + send_message(text)
    → DB insert: dead_page_posts(chat_id, slot='join', date=today, timestamp=now)

SCHEDULED (twice daily, only when Slava is_present=True):
  SchedulerService._loop() runs every 60 seconds:
    1. Query DB: is_slava_present(chat_id) for all tracked chats
    2. For each chat where is_present=True:
       a. Get current time → determine slot: 'morning' (10:00-10:59) or 'evening' (20:00-20:59)
       b. Query DB: has this (chat_id, slot, date=today) been posted?
       c. If NO and current time is within the slot window:
          → MediaService.pick_random() → send_photo + send_message(text)
          → DB insert: dead_page_posts(chat_id, slot, date=today)
    3. asyncio.sleep(60)

── MEDIA PICKING ────────────────────────────────────

MediaService.pick_random():
  INPUT:  base_path = "media/dead_page/"
  OUTPUT: tuple[str_path_to_jpg, str_text_content]

  Algorithm:
    jpgs = sorted(glob.glob(f"{base_path}/*.jpg"))   # → ["media/dead_page/slavic_ava.jpg"]
    txts = sorted(glob.glob(f"{base_path}/*.txt"))   # → ["media/dead_page/page_1.txt"]
    photo_path = random.choice(jpgs)
    text_path = random.choice(txts)
    with open(text_path, 'r', encoding='utf-8') as f:
        text_content = f.read()
    return (photo_path, text_content)

── SENDING ──────────────────────────────────────────

SchedulerService.send_dead_page(chat_id, bot):
    photo_path, text = await MediaService.pick_random()
    
    # Send photo with caption
    await bot.send_photo(
        chat_id=chat_id,
        photo=FSInputFile(photo_path),
        caption=text[:1024]  # Telegram caption limit
    )
    
    # If text exceeds 1024 chars, send remainder as separate message
    if len(text) > 1024:
        await bot.send_message(chat_id=chat_id, text=text[1024:])
```

**Scheduler state machine:**
```
                    ┌──────────────────┐
                    │  IDLE (no task)   │
                    └───────┬──────────┘
                            │ bot.startup
                            ▼
                    ┌──────────────────┐
            ┌──────►│   RUNNING_LOOP   │◄─────────┐
            │       │  (sleep 60s)     │          │
            │       └───────┬──────────┘          │
            │               │ check time + presence │
            │               ▼                      │
            │       ┌──────────────────┐          │
            │       │  SENDING_POST    │          │
            │       └───────┬──────────┘          │
            │               │ done                 │
            │               └──────────────────────┘
            │
            │       ┌──────────────────────┐
            └───────│  IMMEDIATE_TRIGGER   │
                    │  (from F1 handler)   │
                    └──────────────────────┘
```

**Time slot configuration (hardcoded constants in SchedulerService):**
```python
MORNING_START = 10  # hour
MORNING_END = 11    # exclusive
EVENING_START = 20  # hour
EVENING_END = 21    # exclusive
```

### F3 — Slava GIF Counter

```
TRIGGER: Every message from user 479167456

DATA FLOW:
  Message arrives → slavik_router middleware chain
    → MessageCounterMiddleware.__call__()
      1. Extract chat_id = message.chat.id, user_id = message.from_user.id
      2. new_count = await DatabaseService.increment_message_count(chat_id, user_id)
         -- SQL: INSERT OR REPLACE INTO message_counters VALUES (?, ?, COALESCE((SELECT count FROM message_counters WHERE chat_id=? AND user_id=?), 0) + 1)
         -- Returns the NEW count (after increment)
      3. if new_count % 5 == 0:
           await message.answer_animation(
               animation=FSInputFile("media/slavic_chlen.mp4"),
               caption=None
           )
      4. Pass to next handler (no short-circuit: middlewares don't consume updates)

  → Then continues to F4/F5/catch-all handlers (all handlers fire independently)

PERSISTENCE:
  - Counter persists in SQLite across bot restarts
  - Counter resets... requirement doesn't specify reset. Decision: NEVER reset.
    But could add: counter % 1000 cycles back (or just let it grow indefinitely;
    integer overflow in SQLite is not a concern for typical chat volumes)

RESET (optional, implement if asked):
  - New function: DatabaseService.reset_message_count(chat_id, user_id)
  - Sets count = 0
```

**Edge cases:**
- Counter goes from 0 to 1 on first message: requires INSERT (not just UPDATE).
- Concurrent messages in rapid succession: SQLite handles this; aiosqlite serializes access within the same event loop.
- Bot restarts: counter survives (persisted in DB).

### F4 — KUCHA Words

```
TRIGGER: Message from user 479167456 containing "куча"/"кучи"/"кучу" etc.

FLOW:
  Message arrives → slavik_router handlers (in order)
    → Handler 1: @slavik_router.message(KuchaWordFilter())
      → KuchaWordFilter checks: message.text matches r'куч[аеиуюйеё]'
        (using re.IGNORECASE, word boundaries)
      → If TRUE: await message.reply("ДАЛБАЕБ")
      → Handler returns (aiogram continues to next handler anyway)

    → Handler 2: F5 (WarWordFilter) — fires independently
    → Handler 3: catch-all — fires independently ("пошёл нахуй")

RESULT: If Slava writes "куча дрон летит", ALL THREE handlers fire:
  → "ДАЛБАЕБ" (F4)
  → "трясло ебаное" (F5, matches дрон AND летит — fires once per message)
  → "пошёл нахуй" (catch-all)
```

**KuchaWordFilter regex detail:**

```python
import re
# Final implementation (filters/kucha_word.py):
_PATTERN = re.compile(
    r'(?<![а-яё])куч(?:а|и|е|у|ей|ею|ам|ами|ах)?(?![а-яё])',
    re.IGNORECASE
)
```

**Matches (valid forms of «куча»):**
куча, кучи, куче, кучу, кучей, кучею, куч, кучам, кучами, кучах

**Does NOT match (excluded by design):**
- кучка, кучки, кучек — diminutive «кучка» (different word)
- кучерявый, кучковаться — unrelated words sharing the «куч» stem
- Any word where «куч» is followed by Cyrillic letters not in the valid suffix list

The negative lookbehind `(?<![а-яё])` and lookahead `(?![а-яё])` ensure whole-word matching within Cyrillic text. The optional group lists only legitimate inflectional suffixes of «куча». The `re.IGNORECASE` flag handles uppercase input (КУЧА, Куче, etc.).

### F5 — War Words

```
TRIGGER: Message from user 479167456 containing military/drone words

FLOW:
  Message arrives → slavik_router handlers
    → Handler 2: @slavik_router.message(WarWordFilter())
      → WarWordFilter checks: message.text contains any of 21 keywords
      → If TRUE: await message.reply("трясло ебаное")

SAME as F4: fires independently alongside F4 and catch-all.

WAR WORD LIST (hardcoded in WarWordFilter):
  летит, летает, прилетел, прилетает, летят,
  дрон, дроны, дронов, беспилотник,
  вспышка, вспышки,
  прилет, прилёт, прилетел,
  укрытие, укрытия,
  бункер, бункера,
  ракета, ракеты, ракет
```

**WarWordFilter matching algorithm:**
```python
# Precompile all patterns at module level
WAR_PATTERNS = [re.compile(rf'\b{re.escape(word)}\b', re.IGNORECASE) for word in WAR_WORDS]

class WarWordFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        return any(p.search(message.text) for p in WAR_PATTERNS)
```

**Deduplication note:** "прилетел" appears in both "летит" synonyms AND "прилет" synonyms. This is intentional — only needs to match once. The `any()` short-circuits on first match.

### F6 — Alan_Z Reply Engine

```
TRIGGER: Every 10th message from user ID 138811255 (@Alan_Z)

FLOW:
  Message arrives → alan_router message handlers
    → @alan_router.message(UserIdFilter(settings.ALAN_USER_ID))
      → UserIdFilter checks: message.from_user.id == 138811255
      → DatabaseService.increment_and_get_count(chat_id, user_id) → new_count
      → If new_count % ALAN_REPLY_INTERVAL == 0:
        → random.choice(ALAN_REPLIES) → reply_text
        → await message.reply(reply_text)
      → If not divisible: silently pass (no reply)

Reply pool (~20 variants) covers topics:
  - тренировки, лонгковид, фьючерсы, нейросети, жим дьявола
  - configurable via ALAN_REPLIES list in handlers/alan.py
  - extensible: add strings to ALAN_REPLIES list

Uses shared message_counters DB table (same as F3 for Slava).
ALAN_REPLY_INTERVAL=10 (configurable via settings/env).
```

**Design rationale:** Unlike the old F6 (Onupon catch-all "пес пидор"), the new F6 is a periodic reply engine. Every 10 messages from Alan triggers a random reply from a curated pool showing extreme interest in his favorite topics. The reply is NOT a catch-all on every message — it only fires every 10th message. Uses `UserIdFilter` (not `UsernameFilter`) for reliable ID-based matching.

---

## 4. Database Schema

**Database file:** `local_database.db` (SQLite3, accessed via aiosqlite)

**All tables created by `DatabaseService.initialize()` on first run (IF NOT EXISTS).**

### Table: `user_presence`

```sql
CREATE TABLE IF NOT EXISTS user_presence (
    user_id  INTEGER NOT NULL,
    chat_id  INTEGER NOT NULL,
    is_present INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, chat_id)
);
```

| Column | Type | Description |
|--------|------|-------------|
| user_id | INTEGER | Telegram user ID (e.g., 479167456) |
| chat_id | INTEGER | Telegram chat ID |
| is_present | INTEGER | 1 = present in chat, 0 = left/kicked |

**Queries:**
```sql
-- Set presence (upsert)
INSERT OR REPLACE INTO user_presence (user_id, chat_id, is_present)
VALUES (?, ?, ?);

-- Check if present
SELECT is_present FROM user_presence WHERE user_id = ? AND chat_id = ?;

-- Get all chats where user is present (for scheduler)
SELECT chat_id FROM user_presence WHERE user_id = 479167456 AND is_present = 1;
```

### Table: `message_counters`

```sql
CREATE TABLE IF NOT EXISTS message_counters (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
```

| Column | Type | Description |
|--------|------|-------------|
| chat_id | INTEGER | Telegram chat ID |
| user_id | INTEGER | Telegram user ID (Slava = 479167456) |
| count | INTEGER | Cumulative message count, never resets |

**Queries:**
```sql
-- Increment and return new count (atomic upsert + increment)
INSERT INTO message_counters (chat_id, user_id, count)
VALUES (?, ?, 1)
ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1;

-- Get current count
SELECT count FROM message_counters WHERE chat_id = ? AND user_id = ?;

-- Reset count (optional)
UPDATE message_counters SET count = 0 WHERE chat_id = ? AND user_id = ?;
```

**Note:** The increment SQL uses `ON CONFLICT DO UPDATE` which is SQLite 3.24.0+ syntax. The `RETURNING` clause (SQLite 3.35.0+) could return the new count atomically, but to maximize compatibility, we use a separate SELECT after the upsert. Better approach: wrap in a transaction or use a single query:

```sql
INSERT INTO message_counters (chat_id, user_id, count)
VALUES (?, ?, 1)
ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1
RETURNING count;
```

If `RETURNING` is not available, use:
```python
async def increment_message_count(self, chat_id: int, user_id: int) -> int:
    async with self._lock:
        await self.db.execute(
            "INSERT INTO message_counters (chat_id, user_id, count) VALUES (?, ?, 1) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1",
            (chat_id, user_id)
        )
        await self.db.commit()
        cursor = await self.db.execute(
            "SELECT count FROM message_counters WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
```

### Table: `dead_page_posts`

```sql
CREATE TABLE IF NOT EXISTS dead_page_posts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    slot    TEXT    NOT NULL,
    date    TEXT    NOT NULL
);
```

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Auto-increment PK |
| chat_id | INTEGER | Telegram chat ID |
| slot | TEXT | One of: 'morning', 'evening', 'join' |
| date | TEXT | ISO date string YYYY-MM-DD |

**Queries:**
```sql
-- Check if morning slot already posted today
SELECT 1 FROM dead_page_posts
WHERE chat_id = ? AND slot = 'morning' AND date = ?;

-- Check if evening slot already posted today
SELECT 1 FROM dead_page_posts
WHERE chat_id = ? AND slot = 'evening' AND date = ?;

-- Check if any post in last N seconds (dedup for immediate join posts)
SELECT 1 FROM dead_page_posts
WHERE chat_id = ? AND slot = 'join' AND date = ?;

-- Insert post record
INSERT INTO dead_page_posts (chat_id, slot, date) VALUES (?, ?, ?);
```

The `date` column stores `datetime.date.today().isoformat()` (e.g., "2026-07-07").

---

## 5. Router/Handler Registration Order in bot.py

```python
# bot.py — EXACT registration order (DO NOT REORDER)

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import ChatMemberUpdated
from aiogram.fsm.storage.memory import MemoryStorage

from config.settings import settings
from services.database import DatabaseService
from services.scheduler import SchedulerService

# Routers
from handlers.kostik import kostik_router
from handlers.alan import alan_router
from handlers.slavik import slavik_router
from handlers.vasya import vasya_router
from handlers.slava_presence import slava_presence_router

logging.basicConfig(level=logging.INFO)

bot = Bot(token=settings.API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ═══════════════════════════════════════════════════════════
# REGISTRATION ORDER (CRITICAL — DO NOT CHANGE)
# ═══════════════════════════════════════════════════════════

# 1. ChatMemberUpdated handler (F1: Slava return detection)
#    This handles chat_member updates which are NOT message updates.
#    Registered directly on dispatcher for chat_member type.
dp.include_router(slava_presence_router)

# 2. Kostik router — user ID 350803143
#    Catch-all: ANY message type → "пошёл нахуй кринжатура ебаная"
dp.include_router(kostik_router)

# 3. Alan router — user ID 138811255
#    Periodic: EVERY 10th message → random reply (F6)
dp.include_router(alan_router)

# 4. Slava router — user ID 479167456
#    Middleware: MessageCounterMiddleware (F3: GIF every 5 msgs)
#    Handler 1: KuchaWordFilter → "ДАЛБАЕБ" (F4)
#    Handler 2: WarWordFilter → "трясло ебаное" (F5)
#    Handler 3: Catch-all → "пошёл нахуй"
dp.include_router(slavik_router)

# 5. Vasya router — text filters, NO user restriction
#    Handler 1: VasyaFilter → "АДМИН"
#    Handler 2: StrictAdminFilter → "ВАСЯ"
dp.include_router(vasya_router)

# ═══════════════════════════════════════════════════════════

async def on_startup():
    """Initialize DB schema and start scheduler."""
    db = DatabaseService("local_database.db")
    await db.initialize()
    scheduler = SchedulerService(bot, db)
    asyncio.create_task(scheduler.run())

async def main():
    await on_startup()
    print("Бот запущен и слушает чат...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
```

**Why this order matters:**
1. User-ID-based routers (kostik, alan, slavik) come BEFORE text-based routers (vasya).
   - If vasya_router were first, Slava saying "вася" would trigger "АДМИН" instead of "пошёл нахуй".
2. Within Slava's router, F4 and F5 (text-specific) come before catch-all — but they all fire. Order within the router just determines handler index, not exclusivity.
3. ChatMemberUpdated handler is separate from message handlers (different update type).
4. Alan comes before Slava — different users, but clean ordering.

---

## 6. Filter Class Designs

### 6.1 UserIdFilter (`filters/user_id.py`)

```python
from aiogram.filters import BaseFilter
from aiogram.types import Message


class UserIdFilter(BaseFilter):
    """
    Passes only messages from specified user IDs.
    Works with ANY message type (text, photo, sticker, voice, etc.).
    
    Usage:
        @router.message(UserIdFilter(350803143))
        async def handler(message: Message): ...
    """
    def __init__(self, *user_ids: int):
        self.user_ids = set(user_ids)
    
    async def __call__(self, message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in self.user_ids
```

**Migration:** Replaces `lambda msg: msg.from_user.id in ALLOWED_USERS` in both kostik_module.py and slavik_module.py.

### 6.2 VasyaFilter (`filters/vasya_name.py`)

```python
import re
from aiogram.filters import BaseFilter
from aiogram.types import Message


class VasyaFilter(BaseFilter):
    """
    Matches messages containing any variation of "Vasya" (Вася).
    Supports transliterated input: Vasya, Vasia, Vasiliy, васюша, etc.
    
    Algorithm:
      1. Transliterate Latin chars to Cyrillic.
      2. Strip all non-Cyrillic characters.
      3. Search for stem "вас" + vowel ending.
    """
    
    # Precompiled transliteration map
    _TRANSLIT = str.maketrans({
        'v': 'в', 'V': 'в',
        'a': 'а', 'A': 'а',
        's': 'с', 'S': 'с',
        'y': 'я', 'Y': 'я',
        'i': 'и', 'I': 'и',
        'h': 'ш', 'H': 'ш',
        'l': 'л',
    })
    
    _STEM_PATTERN = re.compile(r'вас[иеёяю]')
    _CLEAN_PATTERN = re.compile(r'[^а-яё]')
    
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        
        # Step 1: Replace multi-char transliterations
        text = message.text.lower()
        text = text.replace("sh", "ш").replace("ya", "я").replace("iy", "ий")
        text = text.replace("ch", "ч").replace("kh", "х")
        
        # Step 2: Translate remaining Latin chars
        text = text.translate(self._TRANSLIT)
        
        # Step 3: Keep only Cyrillic
        clean = self._CLEAN_PATTERN.sub('', text)
        
        return bool(self._STEM_PATTERN.search(clean))
```

**Migration note:** Logic taken verbatim from existing `vasya_module.py::VasyaFilter.__call__`. No behavior change.

### 6.3 StrictAdminFilter (`filters/admin_word.py`)

```python
import re
from aiogram.filters import BaseFilter
from aiogram.types import Message


class StrictAdminFilter(BaseFilter):
    """
    Matches messages where 'админ' appears as an exact standalone word.
    Strips leading/trailing punctuation before checking.
    """
    
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        
        text = message.text.lower().strip()
        # Strip punctuation from both ends
        clean = re.sub(r'^[,\.!?\*_\-]+|[,\.!?\*_\-]+$', '', text)
        words = clean.split()
        return 'админ' in words
```

### 6.4 KuchaWordFilter (`filters/kucha_word.py`)

```python
import re
from aiogram.filters import BaseFilter
from aiogram.types import Message


class KuchaWordFilter(BaseFilter):
    """
    Matches messages containing the word stem 'куч-' (КУЧА and all declensions).
    Case-insensitive, using Unicode word boundaries.
    
    Matches: куча, кучи, куче, кучу, кучей, кучею, кучам, кучами, кучах
    Does NOT match: кучевой (but does match the 'куче' part — acceptable false positive)
    """
    
    _PATTERN = re.compile(r'\bкуч[а-яё]*\b', re.IGNORECASE)
    
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        return bool(self._PATTERN.search(message.text))
```

### 6.5 WarWordFilter (`filters/war_word.py`)

```python
import re
from aiogram.filters import BaseFilter
from aiogram.types import Message


class WarWordFilter(BaseFilter):
    """
    Matches messages containing military/drone-related words.
    Case-insensitive, word-boundary matching.
    
    Triggers on: летит, летает, прилетел, прилетает, летят,
                 дрон, дроны, дронов, беспилотник,
                 вспышка, вспышки,
                 прилет, прилёт, прилетел,
                 укрытие, укрытия,
                 бункер, бункера,
                 ракета, ракеты, ракет
    """
    
    WAR_WORDS = [
        # лететь family
        'летит', 'летает', 'прилетел', 'прилетает', 'летят', 'летел',
        # дрон family
        'дрон', 'дроны', 'дронов', 'беспилотник', 'беспилотники',
        # вспышка family
        'вспышка', 'вспышки', 'вспышке',
        # прилет family
        'прилет', 'прилёт', 'прилетел', 'прилетит',
        # укрытие family
        'укрытие', 'укрытия', 'укрытии',
        # бункер family
        'бункер', 'бункера', 'бункере',
        # ракета family
        'ракета', 'ракеты', 'ракет', 'ракете',
    ]
    
    # Precompiled patterns with word boundaries and escaping
    _PATTERNS = [
        re.compile(rf'(?<![а-яё]){re.escape(word)}(?![а-яё])', re.IGNORECASE)
        for word in WAR_WORDS
    ]
    
    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        # Short-circuit on first match
        return any(p.search(message.text) for p in self._PATTERNS)
```

**Note:** Using `(?<![а-яё])...(?![а-яё])` (negative lookbehind/lookahead for Cyrillic) instead of `\b` because Python's `\b` can behave unexpectedly with certain Cyrillic edge cases. This ensures we only match whole words.

---

## 7. Service Class Interfaces

### 7.1 DatabaseService (`services/database.py`)

```python
import aiosqlite
from pathlib import Path


class DatabaseService:
    """
    Async SQLite wrapper using aiosqlite.
    Manages schema creation, connection lifecycle, and all queries.
    
    Thread safety: aiosqlite serializes within the event loop.
    Use asyncio.Lock for atomic read-modify-write operations.
    """
    
    _SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS user_presence (
            user_id    INTEGER NOT NULL,
            chat_id    INTEGER NOT NULL,
            is_present INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (user_id, chat_id)
        );
        
        CREATE TABLE IF NOT EXISTS message_counters (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            count   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        );
        
        CREATE TABLE IF NOT EXISTS dead_page_posts (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            slot    TEXT    NOT NULL,
            date    TEXT    NOT NULL
        );
    """
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Open connection, create tables, enable WAL mode."""
        self.db = await aiosqlite.connect(str(self.db_path))
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.executescript(self._SCHEMA_SQL)
        await self.db.commit()
    
    async def close(self) -> None:
        if self.db:
            await self.db.close()
    
    # ── Slava Presence ──────────────────────────────────
    
    async def set_presence(self, user_id: int, chat_id: int, present: bool) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO user_presence (user_id, chat_id, is_present) VALUES (?, ?, ?)",
            (user_id, chat_id, 1 if present else 0)
        )
        await self.db.commit()
    
    async def is_present(self, user_id: int, chat_id: int) -> bool:
        cursor = await self.db.execute(
            "SELECT is_present FROM user_presence WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        )
        row = await cursor.fetchone()
        # Default: if no row, assume NOT present
        return bool(row and row["is_present"])
    
    async def get_present_chats(self, user_id: int) -> list[int]:
        cursor = await self.db.execute(
            "SELECT chat_id FROM user_presence WHERE user_id = ? AND is_present = 1",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [row["chat_id"] for row in rows]
    
    # ── Message Counters ────────────────────────────────
    
    async def increment_and_get_count(self, chat_id: int, user_id: int) -> int:
        """Atomically increment counter and return new value."""
        async with self._lock:
            await self.db.execute(
                "INSERT INTO message_counters (chat_id, user_id, count) "
                "VALUES (?, ?, 1) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1",
                (chat_id, user_id)
            )
            await self.db.commit()
            cursor = await self.db.execute(
                "SELECT count FROM message_counters WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            row = await cursor.fetchone()
            return row["count"]
    
    async def get_count(self, chat_id: int, user_id: int) -> int:
        cursor = await self.db.execute(
            "SELECT count FROM message_counters WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        row = await cursor.fetchone()
        return row["count"] if row else 0
    
    async def reset_count(self, chat_id: int, user_id: int) -> None:
        await self.db.execute(
            "UPDATE message_counters SET count = 0 WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        await self.db.commit()
    
    # ── Dead Page Posts ─────────────────────────────────
    
    async def has_post_today(self, chat_id: int, slot: str) -> bool:
        """Check if a post of given slot has been made today."""
        today = datetime.date.today().isoformat()
        cursor = await self.db.execute(
            "SELECT 1 FROM dead_page_posts WHERE chat_id = ? AND slot = ? AND date = ?",
            (chat_id, slot, today)
        )
        row = await cursor.fetchone()
        return row is not None
    
    async def record_post(self, chat_id: int, slot: str) -> None:
        """Record that a post was made."""
        today = datetime.date.today().isoformat()
        await self.db.execute(
            "INSERT INTO dead_page_posts (chat_id, slot, date) VALUES (?, ?, ?)",
            (chat_id, slot, today)
        )
        await self.db.commit()
```

### 7.2 MediaService (`services/media_picker.py`)

```python
import glob
import random
from pathlib import Path


class MediaService:
    """
    Picks random media files from media/dead_page/ directory.
    Stateless — no DB dependency.
    
    Caches file lists on first call; refreshes if a file is missing.
    """
    
    def __init__(self, media_base: str = "media/dead_page"):
        self.base = Path(media_base)
        self._photos: list[Path] | None = None
        self._texts: list[Path] | None = None
    
    def _refresh(self) -> None:
        """Scan directory for .jpg and .txt files."""
        self._photos = sorted(
            Path(p) for p in glob.glob(str(self.base / "*.jpg"))
        )
        self._texts = sorted(
            Path(p) for p in glob.glob(str(self.base / "*.txt"))
        )
    
    async def pick_random(self) -> tuple[str, str]:
        """
        Returns (photo_path, text_content).
        
        Raises FileNotFoundError if no photos or no texts found.
        """
        if self._photos is None or self._texts is None:
            self._refresh()
        
        if not self._photos:
            raise FileNotFoundError(f"No .jpg files in {self.base}")
        if not self._texts:
            raise FileNotFoundError(f"No .txt files in {self.base}")
        
        photo_path = str(random.choice(self._photos))
        text_path = random.choice(self._texts)
        text_content = text_path.read_text(encoding='utf-8')
        
        return photo_path, text_content
```

### 7.3 MessageCounterMiddleware (`services/message_counter.py`)

```python
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import Message, FSInputFile
from services.database import DatabaseService


class MessageCounterMiddleware(BaseMiddleware):
    """
    Inner middleware for slavik_router.
    
    On every message from a user on this router:
      1. Increments the DB counter for (chat_id, user_id).
      2. If new count is divisible by 5, sends slavic_chlen.mp4 as animation.
      3. Passes to next handler (does NOT consume the update).
    
    Attached to slavik_router via:
        slavik_router.message.middleware(MessageCounterMiddleware(db))
    """
    
    GIF_PATH = "media/slavic_chlen.mp4"
    INTERVAL = 5  # Send GIF every N messages
    
    def __init__(self, db: DatabaseService):
        self.db = db
        super().__init__()
    
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user_id = event.from_user.id
        chat_id = event.chat.id
        
        new_count = await self.db.increment_and_get_count(chat_id, user_id)
        
        if new_count % self.INTERVAL == 0:
            await event.answer_animation(
                animation=FSInputFile(self.GIF_PATH)
            )
        
        return await handler(event, data)
```

**Why middleware and not a handler:**
- Middleware fires BEFORE handlers and does not consume the update.
- A handler with a filter would work too, but middleware is the semantically correct pattern for "observe and act without preventing other handlers."
- The middleware passes through to all downstream handlers (F4, F5, catch-all).

### 7.4 SchedulerService (`services/scheduler.py`)

```python
import asyncio
import datetime
from aiogram import Bot
from aiogram.types import FSInputFile
from services.database import DatabaseService
from services.media_picker import MediaService


class SchedulerService:
    """
    Background scheduler for dead-page posts (F2).
    
    Runs an infinite loop:
      - Every 60 seconds, checks if it's time to post.
      - Two slots: morning (10:00) and evening (20:00).
      - Only posts if Slava is_present in the chat.
      - Also accepts immediate triggers from F1 (join detection).
    
    Lifecycle:
      - Created in bot.py on_startup().
      - Started via asyncio.create_task(scheduler.run()).
      - Runs until bot shutdown (task cancelled).
    """
    
    MORNING_HOUR = 10
    EVENING_HOUR = 20
    POLL_INTERVAL = 60  # seconds
    DEDUP_WINDOW = 10   # seconds — prevent duplicate join posts
    
    def __init__(self, bot: Bot, db: DatabaseService, target_user_id: int = 479167456):
        self.bot = bot
        self.db = db
        self.target_user_id = target_user_id
        self.media = MediaService()
        self._last_join_post: float = 0  # monotonic timestamp for dedup
        self._immediate_queue: asyncio.Queue[int] | None = None
    
    async def run(self) -> None:
        """Main loop. Never returns unless cancelled."""
        self._immediate_queue = asyncio.Queue()
        while True:
            try:
                await self._tick()
            except Exception as e:
                logging.error(f"Scheduler tick error: {e}")
            try:
                # Wait but also handle immediate triggers
                await asyncio.wait_for(
                    self._immediate_queue.get(),
                    timeout=self.POLL_INTERVAL
                )
                # Immediate trigger received
                chat_id = self._immediate_queue.get_nowait()  # not quite right — need to drain
            except asyncio.TimeoutError:
                pass  # Normal — just the poll interval elapsed
    
    async def _tick(self) -> None:
        """Check and post for all present chats."""
        now = datetime.datetime.now()
        current_hour = now.hour
        
        # Determine active slot
        slot = None
        if self.MORNING_HOUR <= current_hour < self.MORNING_HOUR + 1:
            slot = 'morning'
        elif self.EVENING_HOUR <= current_hour < self.EVENING_HOUR + 1:
            slot = 'evening'
        
        if slot is None:
            return  # Not a posting window
        
        # Get all chats where Slava is present
        chats = await self.db.get_present_chats(self.target_user_id)
        
        for chat_id in chats:
            already_posted = await self.db.has_post_today(chat_id, slot)
            if not already_posted:
                await self._send_dead_page(chat_id, slot)
    
    async def signal_immediate_post(self, chat_id: int) -> None:
        """Called by F1 handler when Slava joins."""
        now = asyncio.get_event_loop().time()
        if now - self._last_join_post < self.DEDUP_WINDOW:
            return  # Dedup: already posted on join recently
        self._last_join_post = now
        await self._send_dead_page(chat_id, 'join')
        if self._immediate_queue:
            await self._immediate_queue.put(chat_id)
    
    async def _send_dead_page(self, chat_id: int, slot: str) -> None:
        """Pick random media and post to chat."""
        try:
            photo_path, text = await self.media.pick_random()
        except FileNotFoundError as e:
            logging.error(f"Dead page media missing: {e}")
            return
        
        caption = text[:1024]  # Telegram caption limit
        
        try:
            await self.bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(photo_path),
                caption=caption
            )
            if len(text) > 1024:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text[1024:]
                )
        except Exception as e:
            logging.error(f"Failed to send dead page: {e}")
            return  # Don't record the post if sending failed
        
        await self.db.record_post(chat_id, slot)
```

**Wait, there's a problem with the immediate queue draining. Let me redesign the `run()` method:**

```python
async def run(self) -> None:
    """Main loop. Processes ticks and immediate triggers."""
    self._immediate_queue = asyncio.Queue()
    while True:
        try:
            # Process any pending immediate triggers
            while not self._immediate_queue.empty():
                chat_id = self._immediate_queue.get_nowait()
                await self._send_dead_page(chat_id, 'join')
            
            await self._tick()
        except Exception as e:
            logging.error(f"Scheduler error: {e}")
        
        # Wait for next tick or immediate signal
        try:
            await asyncio.wait_for(
                self._immediate_queue.get(),
                timeout=self.POLL_INTERVAL
            )
        except asyncio.TimeoutError:
            pass
```

Actually even simpler — just use a simple sleep loop and check both conditions:

```python
async def run(self) -> None:
    """Main scheduler loop."""
    while True:
        try:
            await self._tick()
        except Exception as e:
            logging.error(f"Scheduler tick error: {e}")
        await asyncio.sleep(self.POLL_INTERVAL)
```

And `signal_immediate_post` just calls `_send_dead_page` directly. The scheduler loop handles timed posts. Join posts are handled synchronously in the event handler. This is cleaner.

---

## 8. Scheduler Design for Dead Page Posts (F2)

### Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      bot.py main()                        │
│                                                          │
│  1. Create DatabaseService                               │
│  2. db.initialize() — creates tables                     │
│  3. Create SchedulerService(bot, db)                     │
│  4. asyncio.create_task(scheduler.run())                 │
│  5. dp.start_polling(bot)                                │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │ SchedulerService.run()                           │    │
│  │                                                  │    │
│  │  while True:                                     │    │
│  │    await self._tick()                            │    │
│  │    await asyncio.sleep(60)                       │    │
│  │                                                  │    │
│  │  _tick():                                        │    │
│  │    now = datetime.now()                          │    │
│  │    slot = determine_slot(now.hour)  # or None    │    │
│  │    if slot is None: return                       │    │
│  │    chats = await db.get_present_chats(slava_id)  │    │
│  │    for chat_id in chats:                         │    │
│  │      if not await db.has_post_today(chat, slot): │    │
│  │        await self._send_dead_page(chat, slot)    │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │ F1 Handler (join detection)                      │    │
│  │   scheduler.signal_immediate_post(chat_id)       │    │
│  │   └─> _send_dead_page(chat_id, slot='join')      │    │
│  │       (dedup via 10-sec window)                  │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### Posting Windows

| Slot | Start Hour | End Hour | Description |
|------|-----------|----------|-------------|
| morning | 10 | 11 (exclusive) | Morning dead-page post |
| evening | 20 | 21 (exclusive) | Evening dead-page post |
| join | N/A | N/A | Immediate post on Slava join |

### Deduplication

1. **Scheduled posts**: `has_post_today(chat_id, slot)` checks DB. If the slot was already posted today, skip. This prevents double-posting if the scheduler ticks twice within the same hour window.
2. **Join posts**: `signal_immediate_post` tracks `_last_join_post` monotonic time. If called within 10 seconds of the last join post, it's a duplicate Telegram event and gets skipped. Also records to DB with slot='join' and today's date, so subsequent ticks within the same hour won't double-post.

### Graceful Shutdown

The scheduler task runs forever. On bot shutdown (SIGINT/Ctrl+C):
- `dp.start_polling()` raises `CancelledError`.
- The `asyncio.create_task(scheduler.run())` task is automatically cancelled when the event loop closes.
- No explicit cleanup needed for the scheduler itself; DB connection closing is handled by `DatabaseService.close()` if needed.

---

## 9. Configuration Module Design (`config/settings.py`)

```python
import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load .env from project root (one level above config/)
load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Application configuration. All values from environment / .env."""
    
    API_TOKEN: str = os.getenv("API_TOKEN", "")
    
    # Database
    DB_PATH: str = os.getenv("DB_PATH", "local_database.db")
    
    # User IDs
    KOSTIK_USER_ID: int = int(os.getenv("KOSTIK_USER_ID", "350803143"))
    SLAVIK_USER_ID: int = int(os.getenv("SLAVIK_USER_ID", "479167456"))
    ALAN_USER_ID: int = int(os.getenv("ALAN_USER_ID", "138811255"))
    ALAN_REPLY_INTERVAL: int = int(os.getenv("ALAN_REPLY_INTERVAL", "10"))
    
    # Scheduler
    SCHEDULER_MORNING_HOUR: int = int(os.getenv("SCHEDULER_MORNING_HOUR", "10"))
    SCHEDULER_EVENING_HOUR: int = int(os.getenv("SCHEDULER_EVENING_HOUR", "20"))
    SCHEDULER_POLL_INTERVAL: int = int(os.getenv("SCHEDULER_POLL_INTERVAL", "60"))
    
    # GIF counter
    GIF_INTERVAL: int = int(os.getenv("GIF_INTERVAL", "5"))
    GIF_PATH: str = os.getenv("GIF_PATH", "media/slavic_chlen.mp4")
    
    # Dead page media
    DEAD_PAGE_DIR: str = os.getenv("DEAD_PAGE_DIR", "media/dead_page")
    
    # Debug
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")


# Global singleton — import as `from config.settings import settings`
settings = Settings()
```

**Import pattern:** Every module imports `settings` — never creates its own Settings instance.

---

## 10. Test Strategy

### Test Framework

- **pytest** with **pytest-asyncio** for async test support.
- **pytest-mock** for mocking (or `unittest.mock` built-in).
- In-memory SQLite (`:memory:`) for database tests (no file I/O).

### Test Fixtures (`tests/conftest.py`)

```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from aiogram import Bot, Dispatcher
from aiogram.types import Message, Chat, User, ChatMemberUpdated, ChatMember
from services.database import DatabaseService


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db():
    """In-memory SQLite database with schema initialized."""
    db_service = DatabaseService(":memory:")
    db_service.db_path = ":memory:"  # Override path for in-memory
    await db_service.initialize()
    yield db_service
    await db_service.close()


@pytest.fixture
def mock_bot():
    """Mock aiogram Bot — all send_* methods are AsyncMock."""
    bot = MagicMock(spec=Bot)
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_animation = AsyncMock()
    bot.send_video = AsyncMock()
    return bot


def make_message(
    text: str | None = None,
    user_id: int = 123456,
    username: str | None = None,
    chat_id: int = -100123,
    new_chat_members: list[User] | None = None,
) -> Message:
    """Factory for test Message objects."""
    user = User(id=user_id, is_bot=False, first_name="Test", username=username)
    chat = Chat(id=chat_id, type="group")
    return Message(
        message_id=1,
        date=...,
        chat=chat,
        from_user=user,
        text=text,
        new_chat_members=new_chat_members,
    )


def make_chat_member_updated(
    user_id: int,
    old_status: str,
    new_status: str,
    chat_id: int = -100123,
) -> ChatMemberUpdated:
    """Factory for test ChatMemberUpdated objects."""
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=chat_id, type="group")
    old_cm = ChatMember(user=user, status=old_status)
    new_cm = ChatMember(user=user, status=new_status)
    return ChatMemberUpdated(
        chat=chat,
        from_user=user,
        date=...,
        old_chat_member=old_cm,
        new_chat_member=new_cm,
    )
```

### Test Categories

#### A. Filter Unit Tests (no bot needed)

| Test File | What It Tests |
|-----------|---------------|
| `test_filters.py` | `UserIdFilter` passes/rejects; `KuchaWordFilter` matches declensions; `WarWordFilter` matches all war words; `VasyaFilter` matches variants; `StrictAdminFilter` matches exact "админ" |
| `test_edge_cases.py` | Cross-component edge cases: zero/negative IDs, mixed case, boundaries, router priority simulation |

#### B. Handler & Service Tests (mock bot + DB)

| Test File | What It Tests | Mock Strategy |
|-----------|---------------|---------------|
| `test_kostik.py` | Kostik handler replies "пошёл нахуй кринжатура ебаная" | Feed message, assert reply |
| `test_slavik_handlers.py` | Slava: Kucha→"ДАЛБАЕБ", War→"трясло ебаное", catch-all→"пошёл нахуй" | Feed messages, assert replies |
| `test_message_counter.py` | F3: every 5th message sends GIF animation | Feed messages, verify send_animation called at count % 5 == 0 |
| `test_slava_presence.py` | F1: ChatMemberUpdated → "ДОЛБОЕБ ВЕРНУЛСЯ", presence updates | Feed ChatMemberUpdated events, assert messages + DB updates |
| `test_scheduler.py` | F2: Scheduler tick logic, dedup, posting windows | Mock DB, advance time, verify posts at correct hours |
| `test_media_picker.py` | F2: MediaService random file picker | Mock filesystem, test selection logic |
| `test_alan.py` | F6: reply fires every 10 msgs, random selection, configurable interval | Feed messages, mock DB counter, assert reply timing |
| `test_vasya.py` | Vasya/Admin handlers | Feed "вася"/"админ" text, assert "АДМИН"/"ВАСЯ" replies |

#### C. Database Unit Tests

| Test File | What It Tests |
|-----------|---------------|
| `test_database.py` | `initialize()` creates 3 tables. `increment_and_get_count()` returns 1,2,3... `set_presence`/`is_present` roundtrip. `has_post_today`/`record_post` roundtrip. Concurrent `increment_and_get_count` serialization. |

#### D. Edge Cases

Every test file includes edge case tests:

| Edge Case | Test |
|-----------|------|
| Empty message text (`message.text is None`) | All text filters return False |
| Missing `from_user` | `UserIdFilter` returns False |
| Slava in multiple chats | DB composite key `(chat_id, user_id)` isolates counters |
| Bot restarts | Counters survive (DB persistence); presence state survives |
| Duplicate join events | Scheduler dedup window prevents double immediate post |
| Midnight boundary | `has_post_today` uses date string; new day = new slots |
| Scheduler running with no chats | `get_present_chats` returns `[]` — no-op |
| Missing media files | `MediaService.pick_random()` raises `FileNotFoundError`; scheduler catches and logs |
| Very long dead-page text | Split at 1024 chars; caption + follow-up message |
| GIF path missing | `FSInputFile` raises; middleware should catch (or let it propagate for visibility) |
| Slava leaves during scheduler tick | `is_present` check catches it; no post sent |

#### E. Running Tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=. --cov-report=term-missing
```

### Test Invariants

1. **No real Telegram API calls.** All `bot.send_*` methods are mocked.
2. **No real file I/O** except for reading test fixtures. Database tests use `:memory:`.
3. **Tests are isolated.** Each test creates fresh fixtures; no shared state between tests.
4. **Handler order tests.** Specific test verifies that Slava's "вася" triggers slavik handler, NOT vasya handler (router order matters).

---

## 11. Handler Module Specifications

### 11.1 `handlers/kostik.py`

```python
from aiogram import Router, types
from filters.user_id import UserIdFilter
from config.settings import settings

kostik_router = Router()

@kostik_router.message(UserIdFilter(settings.KOSTIK_USER_ID))
async def kostik_handler(message: types.Message) -> None:
    await message.reply("пошёл нахуй кринжатура ебаная")
```

**Registration:** `dp.include_router(kostik_router)` — position 2 in bot.py.

### 11.2 `handlers/alan.py`

```python
from aiogram import Router, types
import random
from filters.user_id import UserIdFilter
from config.settings import settings
from services.database import DatabaseService

alan_router = Router()
alan_db: DatabaseService | None = None

# Reply pool — extensible: add new strings to extend
ALAN_REPLIES = [
    "так интересно, продолжай",
    "ух ты! а что еще расскажешь интересного? Давай что-нибудь про нейросети или тренировки!",
    # ... ~20 total variants covering тренировки, лонгковид, фьючерсы, нейросети, жим дьявола
]

def setup_alan(db: DatabaseService) -> None:
    global alan_db
    alan_db = db

@alan_router.message(UserIdFilter(settings.ALAN_USER_ID))
async def alan_handler(message: types.Message) -> None:
    if alan_db is None:
        return
    count = await alan_db.increment_and_get_count(message.chat.id, message.from_user.id)
    if count % settings.ALAN_REPLY_INTERVAL == 0:
        await message.reply(random.choice(ALAN_REPLIES))
```

**Registration:** `dp.include_router(alan_router)` — position 3 in bot.py.
**Setup:** `setup_alan(db)` called in `on_startup()` to inject DB dependency.

### 11.3 `handlers/slavik.py`

```python
from aiogram import Router, types
from filters.user_id import UserIdFilter
from filters.kucha_word import KuchaWordFilter
from filters.war_word import WarWordFilter
from config.settings import settings
from services.message_counter import MessageCounterMiddleware
from services.database import DatabaseService

slavik_router = Router()


def setup_slavik_router(db: DatabaseService) -> Router:
    """
    Configure slavik_router with middleware and handlers.
    Must be called after DB is initialized.
    
    Handler order within router:
      1. F4: KuchaWordFilter → "ДАЛБАЕБ"
      2. F5: WarWordFilter → "трясло ебаное"
      3. Catch-all: any message → "пошёл нахуй"
    
    Middleware (F3): MessageCounterMiddleware — counts every 5th msg, sends GIF.
    """
    
    # Middleware: F3 — GIF counter
    slavik_router.message.middleware(
        MessageCounterMiddleware(db)
    )
    
    # Handler 1: F4 — KUCHA words
    @slavik_router.message(
        UserIdFilter(settings.SLAVIK_USER_ID),
        KuchaWordFilter()
    )
    async def kucha_handler(message: types.Message) -> None:
        await message.reply("ДАЛБАЕБ")
    
    # Handler 2: F5 — War words
    @slavik_router.message(
        UserIdFilter(settings.SLAVIK_USER_ID),
        WarWordFilter()
    )
    async def war_handler(message: types.Message) -> None:
        await message.reply("трясло ебаное")
    
    # Handler 3: Catch-all — ANY message from Slava
    @slavik_router.message(UserIdFilter(settings.SLAVIK_USER_ID))
    async def slavik_catchall(message: types.Message) -> None:
        await message.reply("пошёл нахуй")
    
    return slavik_router
```

**Wait — there's a problem.** In aiogram 3.x, when you stack multiple filters on a handler via decorator arguments, the handler fires only if ALL filters pass. So `UserIdFilter(settings.SLAVIK_USER_ID)` combined with `KuchaWordFilter()` means the handler fires only for messages from Slava that also contain a kucha word. This is correct.

But there's a subtlety: the F4 handler and F5 handler and catch-all handler ALL will be evaluated. For a message from Slava that says "куча дрон", all three handlers' filters will pass, and all three handlers will fire. This is the desired behavior.

**However**, in aiogram 3.x, there's a concept of handler "voting." If one handler handles the update, does it prevent others from handling it? In aiogram 3, by default, **all matching handlers fire** (unlike aiogram 2 where you needed to return True/False). So this design is correct.

**Registration in bot.py:**
```python
from handlers.slavik import slavik_router, setup_slavik_router

# ... after DB init ...
setup_slavik_router(db)
dp.include_router(slavik_router)
```

### 11.4 `handlers/vasya.py`

```python
from aiogram import Router, types
from filters.vasya_name import VasyaFilter
from filters.admin_word import StrictAdminFilter

vasya_router = Router()

@vasya_router.message(VasyaFilter())
async def reply_to_vasya(message: types.Message) -> None:
    await message.reply("АДМИН")

@vasya_router.message(StrictAdminFilter())
async def reply_to_admin(message: types.Message) -> None:
    await message.reply("ВАСЯ")
```

**Registration:** `dp.include_router(vasya_router)` — position 5 (LAST) in bot.py.

### 11.5 `handlers/slava_presence.py`

```python
import logging
from aiogram import Router, types, F
from aiogram.types import ChatMemberUpdated
from config.settings import settings

logger = logging.getLogger(__name__)

slava_presence_router = Router()


@slava_presence_router.chat_member()
async def on_slava_chat_member(update: ChatMemberUpdated) -> None:
    """
    F1: Detect when user 479167456 (re)joins the chat via ChatMemberUpdated.
    
    Triggers when:
      - old status was 'left', 'kicked', or 'restricted'
      - new status is 'member' or 'administrator'
      - user ID matches SLAVIK_USER_ID
    """
    user = update.new_chat_member.user
    if user.id != settings.SLAVIK_USER_ID:
        return
    
    old_status = update.old_chat_member.status
    new_status = update.new_chat_member.status
    
    was_absent = old_status in ('left', 'kicked', 'restricted')
    is_present = new_status in ('member', 'administrator')
    
    if was_absent and is_present:
        logger.info(f"Slava returned to chat {update.chat.id}")
        await update.bot.send_message(
            chat_id=update.chat.id,
            text="ДОЛБОЕБ ВЕРНУЛСЯ"
        )
    elif new_status in ('left', 'kicked'):
        logger.info(f"Slava left chat {update.chat.id}")
```

**Registration:** `dp.include_router(slava_presence_router)` — position 1 in bot.py.

**DB integration:** The `on_slava_chat_member` handler also calls `DatabaseService.set_presence()` and `SchedulerService.signal_immediate_post()`. This coupling is handled in bot.py by passing `db` and `scheduler` as extra data or through a callback.

**Refined approach — use dependency injection via aiogram's `data` dict or a simpler pattern:**

In bot.py, we store services on the bot instance or pass them through the dispatcher's workflow data:

```python
# bot.py — passing DB and scheduler to handlers
from aiogram import Dispatcher

# Store services on dispatcher's workflow data (accessible in handlers)
dp["db"] = DatabaseService("local_database.db")
dp["scheduler"] = SchedulerService(bot, dp["db"])
```

Then in `slava_presence.py`:
```python
@slava_presence_router.chat_member()
async def on_slava_chat_member(update: ChatMemberUpdated, db: DatabaseService, scheduler: SchedulerService) -> None:
    # ... same logic ...
    if was_absent and is_present:
        await db.set_presence(user.id, update.chat.id, True)
        await update.bot.send_message(...)
        await scheduler.signal_immediate_post(update.chat.id)
    elif new_status in ('left', 'kicked'):
        await db.set_presence(user.id, update.chat.id, False)
```

This uses aiogram's dependency injection (it resolves parameters from the dispatcher's `workflow_data` dict). Or we can use `**kwargs` pattern.

---

## 12. Dependency Summary

```python
# requirements.txt
aiogram>=3.0.0,<4.0.0
python-dotenv>=1.0.0
aiosqlite>=0.20.0
pytest>=8.0.0
pytest-asyncio>=0.24.0
pytest-mock>=3.12.0
pytest-cov>=5.0.0
```

---

## 13. Handler Fire Order — Complete Example

Given a message from user 479167456 (Slava) in chat -100123 with text "куча дрон летит", here's the complete execution flow:

```
1. ChatMemberUpdated router: NOT triggered (this is a message, not chat_member update)
2. kostik_router: UserIdFilter checks — user is 479167456, not 350803143 → SKIP
3. alan_router: UserIdFilter checks — user is 479167456, not 138811255 → SKIP
4. slavik_router:
   ├── Middleware: MessageCounterMiddleware fires
   │   ├── DB: increment_and_get_count(-100123, 479167456) → returns e.g. 25
   │   ├── 25 % 5 == 0 → TRUE
   │   └── bot.send_animation(FSInputFile("media/slavic_chlen.mp4"))  [GIF SENT]
   │
   ├── Handler 1 (F4): filter=UserIdFilter(479167456) AND KuchaWordFilter()
   │   ├── UserIdFilter: TRUE
   │   ├── KuchaWordFilter: "куча дрон летит" matches \bкуч[а-яё]*\b → TRUE
   │   └── message.reply("ДАЛБАЕБ")  [ДАЛБАЕБ SENT]
   │
   ├── Handler 2 (F5): filter=UserIdFilter(479167456) AND WarWordFilter()
   │   ├── UserIdFilter: TRUE
   │   ├── WarWordFilter: "дрон" matches, "летит" matches → TRUE
   │   └── message.reply("трясло ебаное")  [трясло ебаное SENT]
   │
   └── Handler 3 (catch-all): filter=UserIdFilter(479167456)
       ├── UserIdFilter: TRUE
       └── message.reply("пошёл нахуй")  [пошёл нахуй SENT]

5. vasya_router:
   ├── VasyaFilter: "куча дрон летит" → no "вас" stem → SKIP
   └── StrictAdminFilter: "куча дрон летит" → no "админ" → SKIP

Result: 4 messages sent (GIF + "ДАЛБАЕБ" + "трясло ебаное" + "пошёл нахуй")
```

---

## 14. Key Design Decisions Log

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | F3 uses middleware, not handler | Middleware can observe and act without consuming the update; handlers still fire normally |
| D2 | F4/F5 fire alongside catch-all | Requirements say these are ADDITIONAL responses, not replacements |
| D3 | DatabaseService uses asyncio.Lock for counter increments | Prevents race condition in read-modify-write cycle |
| D4 | UserIdFilter is a class, not a lambda | Reusable, testable, follows existing BaseFilter pattern from vasya_module.py |
| D5 | Scheduler polls every 60s, not event-driven | Simpler than precise scheduling; 60s granularity is fine for "twice a day" |
| D6 | Dead page text uses Telegram caption (1024 char limit) + fallback message | Standard approach for long text with photos |
| D7 | ChatMemberUpdated is PRIMARY for presence detection; new_chat_members is fallback | ChatMemberUpdated covers all status changes; new_chat_members only catches ADD events |
| D8 | DB path is configurable via .env | Allows switching DB files (e.g., for testing) |
| D9 | Each module handles its own imports | No circular dependencies; handlers depend on filters and services, never vice versa |
| D10 | bot.py wires everything together | Single composition root; no scattered configuration |

---

## 15. File Creation / Removal Checklist

### Files to CREATE:

| File | Purpose |
|------|---------|
| `requirements.txt` | Pinned dependencies |
| `.env.example` | Template for .env |
| `config/__init__.py` | Empty init |
| `config/settings.py` | Settings dataclass + dotenv loader |
| `filters/__init__.py` | Empty init |
| `filters/user_id.py` | UserIdFilter class |
| `filters/vasya_name.py` | VasyaFilter class (migrated) |
| `filters/admin_word.py` | StrictAdminFilter class (migrated) |
| `filters/kucha_word.py` | KuchaWordFilter class (F4) |
| `filters/war_word.py` | WarWordFilter class (F5) |
| `handlers/__init__.py` | Empty init |
| `handlers/kostik.py` | Kostik handler (migrated) |
| `handlers/alan.py` | Alan_Z reply engine (F6) |
| `handlers/slavik.py` | Slava handlers + setup (migrated + F3+F4+F5) |
| `handlers/vasya.py` | Vasya handlers (migrated) |
| `handlers/slava_presence.py` | Slava return/leave detection (F1) |
| `services/__init__.py` | Empty init |
| `services/database.py` | DatabaseService (aiosqlite wrapper) |
| `services/media_picker.py` | MediaService (dead page file picker) |
| `services/scheduler.py` | SchedulerService (F2 background loop) |
| `services/message_counter.py` | MessageCounterMiddleware (F3) |
| `tests/__init__.py` | Empty init |
| `tests/conftest.py` | Shared test fixtures |
| `tests/test_kostik.py` | Kostik tests |
| `tests/test_slavik_handlers.py` | Slava handlers (F4 + F5 + catch-all) |
| `tests/test_filters.py` | All filter unit tests |
| `tests/test_edge_cases.py` | Cross-component edge cases |
| `tests/test_message_counter.py` | F3: GIF counter middleware tests |
| `tests/test_slava_presence.py` | F1: Slava join/leave detection tests |
| `tests/test_media_picker.py` | F2: MediaService tests |
| `tests/test_scheduler.py` | Scheduler logic tests |
| `tests/test_alan.py` | F6 tests |
| `tests/test_vasya.py` | Vasya/Admin tests |
| `tests/test_database.py` | DB service tests |
| `README.md` | Ironic documentation (F8) |

### Files to DELETE (logic migrated):

| File | Migration Target |
|------|-----------------|
| `vasya_module.py` | `handlers/vasya.py` + `filters/vasya_name.py` + `filters/admin_word.py` |
| `kostik_module.py` | `handlers/kostik.py` + `filters/user_id.py` |
| `slavik_module.py` | `handlers/slavik.py` + `filters/user_id.py` + `services/message_counter.py` |

### Files to KEEP (no changes):

| File | Reason |
|------|--------|
| `media/slavic_chlen.mp4` | Used by F3 |
| `media/dead_page/slavic_ava.jpg` | Used by F2 |
| `media/dead_page/page_1.txt` | Used by F2 |
| `local_database.db` | Kept as-is; schema applied on init |
| `plans/MEMORY.md` | Project memory |
| `plans/board.md` | Kanban board |
| `plans/backlog.md` | Backlog |

### Files to MODIFY:

| File | Modifications |
|------|--------------|
| `bot.py` | Complete rewrite: use config, DB init, scheduler start, new router registration order |
| `.env` | Add API_TOKEN value (from bot.py hardcode) |
