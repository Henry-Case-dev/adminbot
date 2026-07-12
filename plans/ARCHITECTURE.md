# ARCHITECTURE.md — AdminBot

> **Версия:** v2.1.0
> **Дата:** 2026-07-11
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
│   ├── dead_page_trigger.py        # Repost detector: catches forwards from @d_pages (F2)
│   └── slava_presence.py           # ChatMemberUpdated handler (F1) + new_chat_members fallback
│
├── services/
│   ├── __init__.py
│   ├── database.py                 # DatabaseService — aiosqlite query executor
│   ├── media_picker.py             # MediaService — random jpg + random txt from dead_page/
│   ├── scheduler.py                # SchedulerService — simplified, join trigger only (F2)
│   ├── dead_page_relay.py          # DeadPageRelay — channel forward + fallback service (F2)
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
│   ├── test_scheduler.py           # F2: scheduler loop logic (simplified)
│   ├── test_dead_page_relay.py     # F2: DeadPageRelay forward + fallback tests
│   ├── test_dead_page_trigger.py   # F2: repost detector handler tests
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
│  │  4. dead_page_router  (F2 repost trigger)          │   │
│  │     └─ imports handlers/dead_page_trigger.py      │   │
│  │        └─ imports services/dead_page_relay.py     │   │
│  │           ├─ imports services/database.py         │   │
│  │           ├─ imports services/media_picker.py     │   │
│  │           └─ imports config/settings.py           │   │
│  │                                                   │   │
│  │  5. slavik_router  (user_id=479167456)            │   │
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
│  │  6. vasya_router  (text filters, no user restrict)│   │
│  │     └─ imports handlers/vasya.py                  │   │
│  │        ├─ VasyaFilter → "АДМИН"                   │   │
│  │        │  └─ imports filters/vasya_name.py        │   │
│  │        └─ StrictAdminFilter → "ВАСЯ"              │   │
│  │           └─ imports filters/admin_word.py        │   │
│  │                                                   │   │
│  │  SIMPLIFIED SCHEDULER (started in bot.py main()):  │   │
│  │  ┌─────────────────────────────────────────────┐  │   │
│  │  │ scheduler (F2 join trigger only)             │  │   │
│  │  │  └─ imports services/scheduler.py            │  │   │
│  │  │     └─ imports DeadPageRelay                 │  │   │
│  │  └─────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘

SHARED DEPENDENCIES (imported by many):
┌──────────────────────┐    ┌──────────────────────┐
│ config/settings.py    │    │ services/database.py  │
│ (Settings dataclass)  │    │ (aiosqlite wrapper)   │
└─────────┬────────────┘    └──────────┬────────────┘
          │                            │
    bot.py, scheduler.py          dead_page_relay.py,
    dead_page_relay.py            message_counter.py,
                                  slava_presence.py,
                                  scheduler.py
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

REPOST (event-driven, primary trigger):
  Telegram API → any user forwards a message from @d_pages into the chat
    → Dispatcher.message handler
    → dead_page_trigger.py::on_forward(message: Message)
    → Check: message.forward_origin is MessageOriginChannel
      AND origin.chat.username == 'd_pages'
    → Check: anti-spam cooldown (DB: was_dead_page_recently?)
    → Check: Slava presence (DB: is_present? — future-proofing)
    → DeadPageRelay.send_dead_page(chat_id)
      → DB insert: dead_page_posts(chat_id, slot='repost', date=today, timestamp=now)

ON JOIN (parameterized, optional):
  F1 handler → SchedulerService.signal_immediate_post(chat_id)
    → Check: DEAD_PAGE_POST_ON_JOIN=True?
    → DeadPageRelay.send_dead_page(chat_id)
      → DB insert: dead_page_posts(chat_id, slot='join', date=today, timestamp=now)

SCHEDULED (time-based): REMOVED in v2 — no morning/evening slots

── CHANNEL POST PICKING STRATEGY ────────────────────

DeadPageRelay.get_last_known_message_id(channel_id=4228645624):
  → DB query: SELECT value FROM channel_state WHERE key='last_msg_id:4228645624'
  → Returns int (0 if no known messages)

DeadPageRelay._forward_random_post(target_chat_id):
  INPUT: target_chat_id, channel_id=4228645624, max_retries=10
  
  Algorithm:
    1. last_id = await db.get_last_known_message_id(channel_id)
    2. if last_id < 1: return False (no known messages)
    3. tried = set()
    4. For attempt in range(max_retries):
         msg_id = random.randint(1, last_id)
         if msg_id not in tried:
           tried.add(msg_id)
           try:
             await bot.forward_message(
               chat_id=target_chat_id,
               from_chat_id=channel_id,
               message_id=msg_id
             )
             await db.update_last_known_message_id(channel_id, max(msg_id, last_id))
             return True
           except TelegramBadRequest if "message to forward not found":
             continue  # retry with different msg_id
           except: raise
    5. return False (all retries exhausted)

── FALLBACK ─────────────────────────────────────────

DeadPageRelay._send_local_dead_page(chat_id):
  → Only used if channel forward fails or is unavailable
  → MediaService.pick_random() → send_photo + send_message(text)
  → Uses local media/dead_page/ directory (old method)

── SENDING ──────────────────────────────────────────

DeadPageRelay.send_dead_page(chat_id):
    try:
        success = await self._forward_random_post(chat_id)
        if not success:
            raise RuntimeError("All forward retries exhausted")
    except Exception:
        logger.warning("Channel forward failed. Falling back to local media.")
        await self._send_local_dead_page(chat_id)
        # Fallback format:
        photo_path, text = await self.media.pick_random()
        caption = text[:DEAD_PAGE_CAPTION_MAX_CHARS]
        await bot.send_photo(chat_id, FSInputFile(photo_path), caption=caption)
        if len(text) > DEAD_PAGE_CAPTION_MAX_CHARS:
            await bot.send_message(chat_id, text=text[DEAD_PAGE_CAPTION_MAX_CHARS:])
```

**Anti-spam cooldown:**
```python
DEAD_PAGE_COOLDOWN_SECONDS = 10  # min interval between reposts in same chat

# DB check:
SELECT 1 FROM dead_page_posts
WHERE chat_id = ? AND slot = 'repost' AND timestamp > ?
```

**Channel configuration:**
```python
DEAD_PAGE_SOURCE_CHANNEL_USERNAME = "d_pages"       # forward_origin match
DEAD_PAGE_SOURCE_CHANNEL_ID = 4228645624            # private channel with posts
DEAD_PAGE_POST_ON_JOIN = True                       # enable join trigger
DEAD_PAGE_COOLDOWN_SECONDS = 10                     # anti-spam
DEAD_PAGE_CAPTION_MAX_CHARS = 1024                  # fallback caption limit
DEAD_PAGE_MAX_FORWARD_RETRIES = 10                  # pick random post attempts
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
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    slot      TEXT    NOT NULL,
    date      TEXT    NOT NULL,
    timestamp INTEGER
);
```

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Auto-increment PK |
| chat_id | INTEGER | Telegram chat ID |
| slot | TEXT | One of: 'repost', 'join' |
| date | TEXT | ISO date string YYYY-MM-DD |
| timestamp | INTEGER | Unix time (seconds) for anti-spam cooldown |

**Slot types (v2):** 'morning' and 'evening' removed. Only 'repost' and 'join' remain.
Old morning/evening records stay in DB as history; new code does not create or query them.

**Queries:**
```sql
-- Check if repost in cooldown window (anti-spam)
SELECT 1 FROM dead_page_posts
WHERE chat_id = ? AND slot = 'repost' AND timestamp > ?;

-- Check if join post already made today
SELECT 1 FROM dead_page_posts
WHERE chat_id = ? AND slot = 'join' AND date = ?;

-- Insert post record (with timestamp for anti-spam)
INSERT INTO dead_page_posts (chat_id, slot, date, timestamp)
VALUES (?, ?, ?, ?);
```

The `date` column stores `datetime.date.today().isoformat()` (e.g., "2026-07-11").
The `timestamp` column stores `int(time.time())` — Unix epoch seconds.

### Table: `channel_state`

```sql
CREATE TABLE IF NOT EXISTS channel_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

| Column | Type | Description |
|--------|------|-------------|
| key | TEXT | State key (e.g., "last_msg_id:4228645624") |
| value | TEXT | State value (string representation) |

**Queries:**
```sql
-- Get last known message ID for a channel
SELECT value FROM channel_state WHERE key = 'last_msg_id:4228645624';

-- Update last known message ID (upsert)
INSERT OR REPLACE INTO channel_state (key, value)
VALUES ('last_msg_id:4228645624', '150');
```

This key-value table tracks per-channel metadata. Initially used for storing the
`last_known_message_id` for the dead-page source channel, enabling the
`random.randint(1, last_id)` forward strategy. Extensible for future channel tracking.

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
from services.dead_page_relay import DeadPageRelay
from services.media_picker import MediaService

# Routers
from handlers.kostik import kostik_router
from handlers.alan import alan_router
from handlers.dead_page_trigger import dead_page_router, setup_dead_page
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

# 4. Dead Page router — repost trigger (F2)
#    Catches forward_origin from @d_pages, fires DeadPageRelay
#    BEFORE slavik_router to ensure reposts are handled independently
setup_dead_page(dead_page_relay, db)
dp.include_router(dead_page_router)

# 5. Slava router — user ID 479167456
#    Middleware: MessageCounterMiddleware (F3: GIF every 5 msgs)
#    Handler 1: KuchaWordFilter → "ДАЛБАЕБ" (F4)
#    Handler 2: WarWordFilter → "трясло ебаное" (F5)
#    Handler 3: Catch-all → "пошёл нахуй"
dp.include_router(slavik_router)

# 6. Vasya router — text filters, NO user restriction
#    Handler 1: VasyaFilter → "АДМИН"
#    Handler 2: StrictAdminFilter → "ВАСЯ"
dp.include_router(vasya_router)

# ═══════════════════════════════════════════════════════════

async def on_startup():
    """Initialize DB schema, create services, start scheduler."""
    db = DatabaseService("local_database.db")
    await db.initialize()
    media = MediaService(settings.DEAD_PAGE_DIR)
    dead_page_relay = DeadPageRelay(
        bot=bot, db=db, media=media,
        channel_id=settings.DEAD_PAGE_SOURCE_CHANNEL_ID,
        max_retries=settings.DEAD_PAGE_MAX_FORWARD_RETRIES
    )
    scheduler = SchedulerService(bot, db, dead_page_relay)
    # Inject dependencies into handlers
    setup_dead_page(dead_page_relay, db)
    # Schedule on_startup injects relay into scheduler
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
2. dead_page_router (position 4) is inserted between alan_router and slavik_router.
   - It filters on `forward_origin` (not user ID), so it doesn't conflict with user-ID routers.
   - Being before vasya_router prevents Vasya's text filters from intercepting forward messages.
3. Within Slava's router, F4 and F5 (text-specific) come before catch-all — but they all fire.
4. ChatMemberUpdated handler is separate from message handlers (different update type).
5. The simplified scheduler only handles the join trigger (signal_immediate_post);
   DeadPageRelay handles the actual posting logic for both repost and join triggers.

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
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   INTEGER NOT NULL,
            slot      TEXT    NOT NULL,
            date      TEXT    NOT NULL,
            timestamp INTEGER
        );
        
        CREATE TABLE IF NOT EXISTS channel_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
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
    
    async def was_dead_page_recently(self, chat_id: int, cooldown_seconds: int) -> bool:
        """Check if a repost was made in this chat within cooldown window."""
        import time
        threshold = int(time.time()) - cooldown_seconds
        cursor = await self.db.execute(
            "SELECT 1 FROM dead_page_posts WHERE chat_id = ? AND slot = 'repost' AND timestamp > ?",
            (chat_id, threshold)
        )
        row = await cursor.fetchone()
        return row is not None
    
    async def record_dead_page_post(self, chat_id: int, slot: str) -> None:
        """Record a dead page post with date and timestamp."""
        import time
        import datetime
        today = datetime.date.today().isoformat()
        now = int(time.time())
        await self.db.execute(
            "INSERT INTO dead_page_posts (chat_id, slot, date, timestamp) VALUES (?, ?, ?, ?)",
            (chat_id, slot, today, now)
        )
        await self.db.commit()
    
    # ── Channel State ───────────────────────────────────
    
    async def get_last_known_message_id(self, channel_id: int) -> int:
        """Get the last known message ID for a channel."""
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?",
            (f"last_msg_id:{channel_id}",)
        )
        row = await cursor.fetchone()
        return int(row["value"]) if row else 0
    
    async def update_last_known_message_id(self, channel_id: int, msg_id: int) -> None:
        """Update the last known message ID for a channel."""
        await self.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            (f"last_msg_id:{channel_id}", str(msg_id))
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
import logging
from aiogram import Bot
from config.settings import settings
from services.database import DatabaseService

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Simplified scheduler for dead-page posts (F2 v2).
    
    Handles ONLY the join trigger. Time-based scheduler (morning/evening)
    removed in v2 — replaced by event-driven repost trigger via dead_page_router.
    
    Lifecycle:
      - Created in bot.py on_startup().
      - Started via asyncio.create_task(scheduler.run()).
      - Runs until bot shutdown (task cancelled).
    """
    
    DEDUP_WINDOW = 10  # seconds — prevent duplicate join posts
    
    def __init__(self, bot: Bot, db: DatabaseService, relay, target_user_id: int = 479167456):
        self.bot = bot
        self.db = db
        self.relay = relay  # DeadPageRelay instance
        self.target_user_id = target_user_id
        self._last_join_post: float = 0
    
    async def run(self) -> None:
        """No-op loop. Join trigger is synchronous, repost is event-driven."""
        while True:
            await asyncio.sleep(3600)  # Keep task alive, no polling needed
    
    async def signal_immediate_post(self, chat_id: int) -> None:
        """Called by F1 handler when Slava joins. Delegates to DeadPageRelay."""
        if not settings.DEAD_PAGE_POST_ON_JOIN:
            logger.debug(f"Join trigger disabled, skipping chat {chat_id}")
            return
        
        now = asyncio.get_event_loop().time()
        if now - self._last_join_post < self.DEDUP_WINDOW:
            return  # Dedup: already posted on join recently
        self._last_join_post = now
        
        logger.info(f"Join trigger fired for chat {chat_id}")
        await self.relay.send_dead_page(chat_id)
        await self.db.record_dead_page_post(chat_id, 'join')
```

**Key change from v1:** The `while True` loop no longer polls for time slots.
The only purpose of `run()` is to keep the async task alive so that
`signal_immediate_post` remains callable from the F1 handler. The loop
sleeps for 1 hour — a no-op placeholder. Join posting is synchronous
(inline call from F1), repost is event-driven (dead_page_router fires
`relay.send_dead_page` directly).

### 7.5 DeadPageRelay (`services/dead_page_relay.py`)

```python
import random
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile
from config.settings import settings
from services.database import DatabaseService
from services.media_picker import MediaService

logger = logging.getLogger(__name__)


class DeadPageRelay:
    """
    Dead page post relay service (F2 v2).
    
    Tries to forward a random post from the private channel.
    Falls back to local media/dead_page/ if channel is unavailable.
    
    Does NOT generate new content — only forwards existing channel posts.
    """
    
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
                await self.db.update_last_known_message_id(
                    self.channel_id, max(msg_id, last_id)
                )
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
        
        caption = text[:settings.DEAD_PAGE_CAPTION_MAX_CHARS]
        if len(text) > settings.DEAD_PAGE_CAPTION_MAX_CHARS:
            logger.warning(f"Text truncated: {len(text)} -> {len(caption)} chars")
        
        await self.bot.send_photo(
            chat_id=chat_id,
            photo=FSInputFile(photo_path),
            caption=caption,
        )
        if len(text) > settings.DEAD_PAGE_CAPTION_MAX_CHARS:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text[settings.DEAD_PAGE_CAPTION_MAX_CHARS:]
            )
```

---

## 8. Dead Page Relay Design (F2 v2)

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         bot.py main()                                │
│                                                                     │
│  1. Create DatabaseService                                          │
│  2. db.initialize() — creates 4 tables (incl. channel_state)         │
│  3. Create MediaService(DEAD_PAGE_DIR)                              │
│  4. Create DeadPageRelay(bot, db, media, channel_id, max_retries)   │
│  5. Create SchedulerService(bot, db, relay)  — simplified           │
│  6. setup_dead_page(relay, db) — inject into handler                │
│  7. Register all routers                                            │
│  8. asyncio.create_task(scheduler.run())                            │
│  9. dp.start_polling(bot)                                           │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │ REPOST TRIGGER (event-driven, via dead_page_router)       │      │
│  │                                                          │      │
│  │  User forwards @d_pages post into chat                   │      │
│  │    → dead_page_trigger.on_forward()                      │      │
│  │    → Check: forward_origin is MessageOriginChannel       │      │
│  │    → Check: origin.chat.username == "d_pages"            │      │
│  │    → Check: anti-spam cooldown (was_dead_page_recently)  │      │
│  │    → Check: Slava presence (is_present — optional)       │      │
│  │    → relay.send_dead_page(chat_id)                       │      │
│  │      ├─ _forward_random_post(chat_id)                    │      │
│  │      │  └─ random.randint(1, last_known_msg_id)          │      │
│  │      │  └─ bot.forward_message()                         │      │
│  │      │  └─ update_last_known_message_id()                │      │
│  │      └─ (if all retries fail) _send_local_dead_page()    │      │
│  │    → db.record_dead_page_post(chat_id, slot='repost')    │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │ JOIN TRIGGER (synchronous, via F1 + SchedulerService)     │      │
│  │                                                          │      │
│  │  Slava joins chat                                        │      │
│  │    → F1: on_slava_chat_member()                          │      │
│  │    → scheduler.signal_immediate_post(chat_id)            │      │
│  │      → Check: DEAD_PAGE_POST_ON_JOIN == True?            │      │
│  │      → Check: dedup window (10 sec)                      │      │
│  │      → relay.send_dead_page(chat_id)                     │      │
│  │    → db.record_dead_page_post(chat_id, slot='join')      │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │ SchedulerService.run()  (simplified — no time-based logic) │      │
│  │                                                          │      │
│  │  while True:                                             │      │
│  │    await asyncio.sleep(3600)  # keep task alive          │      │
│  │  (signal_immediate_post is called synchronously by F1)   │      │
│  └──────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

### Forward-from-Channel Strategy

1. **Channel ID**: `DEAD_PAGE_SOURCE_CHANNEL_ID = 4228645624` (private channel)
2. **Message tracking**: `channel_state` table stores `last_known_message_id` per channel.
   Updated on each successful forward: `max(forwarded_id, last_id)`.
3. **Random pick**: `random.randint(1, last_known_message_id)` — picks any message_id
   in the range, even deleted ones (handled via retry).
4. **Retries**: Up to `DEAD_PAGE_MAX_FORWARD_RETRIES` (default 10) attempts with
   different random `message_id` values. Skips already-tried IDs.
5. **Error handling**: `TelegramBadRequest` with "message to forward not found"
   triggers retry. All other errors raise immediately (channel unavailable, bot
   not admin, etc.) — triggering the fallback.

### Fallback Mechanism

If `_forward_random_post` returns `False` or raises any exception:
- Falls back to `_send_local_dead_page(chat_id)` which uses `MediaService.pick_random()`
  from `media/dead_page/` directory (same as v1 sending logic).
- Uses `send_photo` with caption + optional `send_message` for overflow text.
- Caption limit: `DEAD_PAGE_CAPTION_MAX_CHARS` (default 1024).

### Anti-Spam Cooldown

- **Cooldown**: `DEAD_PAGE_COOLDOWN_SECONDS` (default 10) between reposts in same chat.
- **Check**: `was_dead_page_recently(chat_id, cooldown_seconds)` queries
  `dead_page_posts` where `slot='repost' AND timestamp > threshold`.
- **Scope**: Repost trigger only. Join trigger uses its own 10-second dedup window
  in SchedulerService (monotonic time, no DB query).

### Graceful Shutdown

The scheduler task runs forever (sleep loop). On bot shutdown:
- `dp.start_polling()` raises `CancelledError`.
- The `asyncio.create_task(scheduler.run())` task is automatically cancelled
  when the event loop closes.
- No explicit cleanup needed. DB connection closing is handled by
  `DatabaseService.close()` if needed.

---

## 9. Monitoring (Better Stack)

### 9.1 Overview

The monitoring layer integrates AdminBot with Better Stack — a unified observability platform. It provides:

- **Error Tracking (Sentry)**: Automatic capture of all unhandled exceptions with full stack traces, request context, and Telegram event data.
- **Structured Logging (Logtail)**: All `logger.info(...)`, `logger.warning(...)`, and `logger.error(...)` calls across all modules are streamed to the cloud in real time.
- **Zero-Instrumentation Design**: Sentry auto-instruments aiogram 3.x. No code changes in handlers or services are required — monitoring is added purely at the entry point (`bot.py`).

The architecture follows a **dual-output logging model**: structured logs go to both the console (`StreamHandler`) for local debugging and to Better Stack (`LogtailHandler`) for cloud observability.

### 9.2 Error Tracking (Sentry)

Sentry captures **all unhandled exceptions** automatically. This includes:
- Unexpected aiogram exceptions (API errors, network timeouts)
- Python runtime errors (AttributeError, ValueError, etc.)
- Database connection failures (aiosqlite errors)
- Any exception that propagates out of a handler without being caught

**Initialization** (in `bot.py`, immediately after `load_dotenv()`):

```python
import os
import sentry_sdk
from dotenv import load_dotenv

load_dotenv()

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    traces_sample_rate=1.0,
)
```

Key behaviors:
- `sentry_sdk.init()` is called **before** the logging setup and **before** the Bot/Dispatcher creation. This ensures errors during initialization are captured.
- `traces_sample_rate=1.0` means 100% of events are sent (suitable for low-traffic bots; lower for production at scale).
- Sentry auto-instruments aiogram via its integrations registry — no `aiogram`-specific integration import is needed.
- Errors are sent to the Better Stack backend at the URL provided by `SENTRY_DSN`.

### 9.3 Structured Logging (Logtail)

Logtail captures **all structured log output** from every module. Since the project uses a single root logger with `logging.getLogger(__name__)` instances, a single `LogtailHandler` on the root logger captures everything.

**Dual-Output Architecture:**

```
                    ┌─────────────────┐
                    │   Root Logger   │
                    │  (level=INFO)   │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
    ┌─────────────────┐  ┌──────────┐  ┌──────────────┐
    │  StreamHandler   │  │ Logtail  │  │  (future      │
    │  (console)       │  │ Handler  │  │   handlers)   │
    │  level: INFO     │  │ level:   │  │               │
    │                  │  │ INFO     │  │               │
    └────────┬────────┘  └────┬─────┘  └──────────────┘
             │                │
             ▼                ▼
        Local Console    Better Stack
        (docker logs,    (Logtail cloud
         systemd, etc.)   dashboard)
```

**Initialization** (in `bot.py`, after Sentry init):

```python
import logging
from logtail import LogtailHandler

# Formatter (same format as existing StreamHandler)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Root logger — base level
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)

# Logtail handler — cloud logging
logtail_handler = LogtailHandler(
    source_token=os.getenv("LOGTAIL_SOURCE_TOKEN")
)
logtail_handler.setLevel(logging.INFO)
logtail_handler.setFormatter(formatter)
root_logger.addHandler(logtail_handler)
```

All existing `logger.info(...)`, `logger.warning(...)`, and `logger.error(...)` calls across 7 modules (bot.py, 5 services, slava_presence.py) automatically flow to both outputs.

### 9.4 Environment Variables

Two new environment variables are added to `.env`:

| Variable | Purpose | Provider |
|----------|---------|----------|
| `SENTRY_DSN` | Data Source Name for Sentry error tracking | Better Stack (Sentry-compatible endpoint) |
| `LOGTAIL_SOURCE_TOKEN` | Ingest token for Logtail structured logging | Better Stack (Logtail source) |

Both are optional — the bot runs without them if not set, but monitoring will be inactive. No defaults are provided; if absent, monitoring is simply not initialized.

### 9.5 Initialization Flow

The startup sequence in `bot.py` is structured to ensure monitoring is active **before** any bot operations:

```
1. load_dotenv()          → Load .env file (already in config/settings.py)
2. sentry_sdk.init(...)   → Activate error tracking BEFORE anything else
3. Root logger setup      → Configure StreamHandler + LogtailHandler
4. Bot/Dispatcher creation → Bot(token=settings.API_TOKEN)
5. Router registration     → dp.include_router(...) × 6
6. on_startup()            → DB init, media service, DeadPageRelay, scheduler
7. dp.start_polling(bot)   → Begin polling
```

This order guarantees:
- Errors during **import** of any module are captured by Sentry.
- Errors during **initialization** (DB connection failure, etc.) are captured.
- Log output from all subsequent steps flows to both console and Better Stack.
- If any monitoring service fails to initialize, the bot still starts gracefully.

### 9.6 Architecture Diagram Addition

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AdminBot System Layers                        │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    MONITORING LAYER (NEW)                      │ │
│  │                                                               │ │
│  │  ┌─────────────────┐         ┌──────────────────┐            │ │
│  │  │  Sentry SDK     │         │  Logtail Handler  │            │ │
│  │  │  (Error Track.) │         │  (Structured Logs)│            │ │
│  │  │                 │         │                    │            │ │
│  │  │ Auto-captures:  │         │ Captures from:     │            │ │
│  │  │ • Unhandled exc │         │ • bot.py           │            │ │
│  │  │ • API errors    │         │ • all handlers/    │            │ │
│  │  │ • DB failures   │         │ • all services/    │            │ │
│  │  │ • Runtime errs  │         │ • all filters/     │            │ │
│  │  └────────┬────────┘         └────────┬─────────┘            │ │
│  │           │                           │                      │ │
│  │           └───────────┬───────────────┘                      │ │
│  │                       │                                      │ │
│  │                 Better Stack                                  │ │
│  │                 (Cloud Dashboard)                             │ │
│  └───────────────────────┬───────────────────────────────────────┘ │
│                          │                                         │
│  ┌───────────────────────┼───────────────────────────────────────┐ │
│  │              APPLICATION LAYER                                 │ │
│  │                                                               │ │
│  │  bot.py ──► Router Registration ──► 6 Routers                 │ │
│  │    │                                                          │ │
│  │    ├──► handlers/ (6 modules)                                 │ │
│  │    ├──► filters/  (5 classes)                                 │ │
│  │    └──► services/ (5 classes)                                 │ │
│  │                                                               │ │
│  │            ┌──────────────────────┐                           │ │
│  │            │   Database Layer     │                           │ │
│  │            │   (SQLite/aiosqlite) │                           │ │
│  │            └──────────────────────┘                           │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                  INFRASTRUCTURE                                 │ │
│  │  • Telegram Bot API  • .env Configuration  • Python 3.12       │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

The monitoring layer sits **above** the application layer — it observes everything below without modifying it. Sentry intercepts exceptions at the runtime level; Logtail intercepts log records at the logging framework level. Neither touches application code.

---

## 10. Configuration Module Design (`config/settings.py`)

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
    
    # Dead Page Relay (F2 v2)
    DEAD_PAGE_SOURCE_CHANNEL_USERNAME: str = os.getenv("DEAD_PAGE_SOURCE_CHANNEL_USERNAME", "d_pages")
    DEAD_PAGE_SOURCE_CHANNEL_ID: int = int(os.getenv("DEAD_PAGE_SOURCE_CHANNEL_ID", "4228645624"))
    DEAD_PAGE_RELAY_CHANNEL_ID: int = int(os.getenv("DEAD_PAGE_RELAY_CHANNEL_ID", "4228645624"))
    DEAD_PAGE_CAPTION_MAX_CHARS: int = int(os.getenv("DEAD_PAGE_CAPTION_MAX_CHARS", "1024"))
    DEAD_PAGE_COOLDOWN_SECONDS: int = int(os.getenv("DEAD_PAGE_COOLDOWN_SECONDS", "10"))
    DEAD_PAGE_POST_ON_JOIN: bool = os.getenv("DEAD_PAGE_POST_ON_JOIN", "True").lower() in ("true", "1", "yes")
    DEAD_PAGE_MAX_FORWARD_RETRIES: int = int(os.getenv("DEAD_PAGE_MAX_FORWARD_RETRIES", "10"))
    DEAD_PAGE_CHANNEL_LAST_MSG_ID: int = int(os.getenv("DEAD_PAGE_CHANNEL_LAST_MSG_ID", "0"))
    DEAD_PAGE_DIR: str = os.getenv("DEAD_PAGE_DIR", "media/dead_page")
    
    # GIF counter
    GIF_INTERVAL: int = int(os.getenv("GIF_INTERVAL", "5"))
    GIF_PATH: str = os.getenv("GIF_PATH", "media/slavic_chlen.mp4")
    
    # Debug
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")


# Global singleton — import as `from config.settings import settings`
settings = Settings()
```

> **Monitoring env vars:** `SENTRY_DSN` and `LOGTAIL_SOURCE_TOKEN` are consumed directly in `bot.py` via `os.getenv()` (not routed through the `Settings` dataclass). Their initialization and usage are documented in **Section 9 (Monitoring)**.

**Import pattern:** Every module imports `settings` — never creates its own Settings instance.

---

## 11. Test Strategy

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
| `test_database.py` | `initialize()` creates 4 tables (including channel_state). `increment_and_get_count()` returns 1,2,3... `set_presence`/`is_present` roundtrip. `was_dead_page_recently`/`record_dead_page_post` roundtrip. `get_last_known_message_id`/`update_last_known_message_id` roundtrip. Concurrent `increment_and_get_count` serialization. |

#### D. Edge Cases

Every test file includes edge case tests:

| Edge Case | Test |
|-----------|------|
| Empty message text (`message.text is None`) | All text filters return False |
| Missing `from_user` | `UserIdFilter` returns False |
| Slava in multiple chats | DB composite key `(chat_id, user_id)` isolates counters |
| Bot restarts | Counters survive (DB persistence); presence state survives |
| Duplicate join events | Scheduler dedup window prevents double immediate post |
| Midnight boundary | `record_dead_page_post` stores date string; new day = new slots |
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

## 12. Handler Module Specifications

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

**DB integration:** The `on_slava_chat_member` handler also calls `DatabaseService.set_presence()` and `SchedulerService.signal_immediate_post()` (which delegates to `DeadPageRelay.send_dead_page()`). This coupling is handled in bot.py by passing `db`, `scheduler`, and `relay` as extra data or through dependency injection.

**Refined approach — use dependency injection via aiogram's `data` dict or a simpler pattern:**

In bot.py, we store services on the bot instance or pass them through the dispatcher's workflow data:

```python
# bot.py — passing DB, relay, and scheduler to handlers
from aiogram import Dispatcher

# Store services on dispatcher's workflow data (accessible in handlers)
dp["db"] = DatabaseService("local_database.db")
dp["relay"] = DeadPageRelay(bot, db, media, channel_id=...)
dp["scheduler"] = SchedulerService(bot, db, dp["relay"])
```

Then in `slava_presence.py`:
```python
@slava_presence_router.chat_member()
async def on_slava_chat_member(update: ChatMemberUpdated, db: DatabaseService, scheduler: SchedulerService) -> None:
    # ... same logic ...
    if was_absent and is_present:
        await db.set_presence(user.id, update.chat.id, True)
        await update.bot.send_message(chat_id=update.chat.id, text="ДОЛБОЕБ ВЕРНУЛСЯ")
        await scheduler.signal_immediate_post(update.chat.id)
    elif new_status in ('left', 'kicked'):
        await db.set_presence(user.id, update.chat.id, False)
```

This uses aiogram's dependency injection (it resolves parameters from the dispatcher's `workflow_data` dict). Or we can use `**kwargs` pattern.

---

## 13. Dependency Summary

```python
# requirements.txt
aiogram>=3.7.0,<4.0.0
python-dotenv>=1.0.0
aiosqlite>=0.20.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
sentry-sdk==2.64.0
logtail-python==0.4.0
```

---

## 14. Handler Fire Order — Complete Example

Given a message from user 479167456 (Slava) in chat -100123 with text "куча дрон летит", here's the complete execution flow:

```
1. ChatMemberUpdated router: NOT triggered (this is a message, not chat_member update)
2. kostik_router: UserIdFilter checks — user is 479167456, not 350803143 → SKIP
3. alan_router: UserIdFilter checks — user is 479167456, not 138811255 → SKIP
4. dead_page_router: forward_origin filter checks — no forward_origin present → SKIP
5. slavik_router:
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

6. vasya_router:
   ├── VasyaFilter: "куча дрон летит" → no "вас" stem → SKIP
   └── StrictAdminFilter: "куча дрон летит" → no "админ" → SKIP

Result: 4 messages sent (GIF + "ДАЛБАЕБ" + "трясло ебаное" + "пошёл нахуй")
```

---

## 15. Key Design Decisions Log

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | F3 uses middleware, not handler | Middleware can observe and act without consuming the update; handlers still fire normally |
| D2 | F4/F5 fire alongside catch-all | Requirements say these are ADDITIONAL responses, not replacements |
| D3 | DatabaseService uses asyncio.Lock for counter increments | Prevents race condition in read-modify-write cycle |
| D4 | UserIdFilter is a class, not a lambda | Reusable, testable, follows existing BaseFilter pattern from vasya_module.py |
| D5 | Dead page posts use forwardMessage from channel, not local media | Event-driven (repost trigger); no time-based scheduler; random post from channel via random.randint strategy |
| D6 | Dead page has mandatory fallback to local media/dead_page/ | If channel is unavailable or all forward retries fail, old send_photo mechanism kicks in |
| D7 | channel_state table is a key-value store | Extensible pattern for per-channel metadata; initially tracks last_known_message_id for random forward strategy |
| D8 | Anti-spam cooldown via timestamp column | Prevents rapid repost spam; 10-second default; separate dedup for join trigger (monotonic time) |
| D9 | ChatMemberUpdated is PRIMARY for presence detection; new_chat_members is fallback | ChatMemberUpdated covers all status changes; new_chat_members only catches ADD events |
| D10 | DB path is configurable via .env | Allows switching DB files (e.g., for testing) |
| D11 | Each module handles its own imports | No circular dependencies; handlers depend on filters and services, never vice versa |
| D12 | bot.py wires everything together | Single composition root; no scattered configuration |

---

## 16. File Creation / Removal Checklist

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
| `handlers/dead_page_trigger.py` | Repost detector: catches forwards from @d_pages (F2) |
| `handlers/slava_presence.py` | Slava return/leave detection (F1) |
| `services/__init__.py` | Empty init |
| `services/database.py` | DatabaseService (aiosqlite wrapper + channel_state) |
| `services/media_picker.py` | MediaService (dead page file picker, fallback) |
| `services/scheduler.py` | SchedulerService (F2 simplified, join trigger only) |
| `services/dead_page_relay.py` | DeadPageRelay (channel forward + fallback, F2) |
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
| `tests/test_scheduler.py` | Scheduler logic tests (simplified) |
| `tests/test_dead_page_relay.py` | F2: DeadPageRelay forward + fallback tests |
| `tests/test_dead_page_trigger.py` | F2: repost detector handler tests |
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
| `media/dead_page/slavic_ava.jpg` | Used by F2 (fallback) |
| `media/dead_page/page_1.txt` | Used by F2 (fallback) |
| `local_database.db` | Kept as-is; schema applied on init; new tables added |
| `plans/MEMORY.md` | Project memory |
| `plans/board.md` | Kanban board |
| `plans/backlog.md` | Backlog |

### Files to MODIFY:

| File | Modifications |
|------|--------------|
| `bot.py` | Complete rewrite: use config, DB init, DeadPageRelay, scheduler, new router registration order (v2) |
| `.env` | Add API_TOKEN value (from bot.py hardcode) |
| `.env.example` | Add DEAD_PAGE_* env vars |
| `config/settings.py` | Add DEAD_PAGE_* fields; remove SCHEDULER_* fields |
| `services/database.py` | Add channel_state table; update dead_page_posts schema; add was_dead_page_recently, record_dead_page_post, channel_state methods |
| `services/scheduler.py` | Simplify: remove time-based loop; keep only join trigger via DeadPageRelay |
| `services/media_picker.py` | Downgrade to fallback-only role; no API changes |
| `handlers/slava_presence.py` | Update signal_immediate_post to use DeadPageRelay |
| `plans/ARCHITECTURE.md` | Updated to v2.0.0 reflecting Dead Page V2 changes |
| `plans/MEMORY.md` | Update architecture, slots, DB schema for v2 |
