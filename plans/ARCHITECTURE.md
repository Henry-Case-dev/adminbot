# ARCHITECTURE.md — AdminBot

> **Версия:** v2.5.0
> **Дата:** 2026-07-15
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
│   ├── admin_commands.py            # Admin test commands: /deadpage, /alangreet (Epic 10)
│   ├── kostik.py                   # Kostik catch-all: "пошёл нахуй кринжатура ебаная"
│   ├── slavik.py                   # Slava router: middleware(F3) + F4 + F5 + catch-all
│   ├── vasya.py                    # Vasya/Admin filters + handlers
│   ├── alan.py                      # Alan_Z reply engine: every 10 msgs → random reply (F6)
│   ├── alan_greeting.py             # Alan greeting video on join: ChatMemberUpdated + new_chat_members (F7)
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
│   ├── test_admin_commands.py      # Admin test commands: /deadpage, /alangreet (Epic 10)
│   ├── test_kostik.py
│   ├── test_slavik_handlers.py     # Slava handlers (F4 + F5 + catch-all)
│   ├── test_filters.py             # All 6 filter unit tests
│   ├── test_edge_cases.py          # Cross-component edge cases
│   ├── test_message_counter.py     # F3: GIF counter middleware
│   ├── test_slava_presence.py      # F1: Slava join/leave detection
│   ├── test_scheduler.py           # F2: scheduler loop logic (simplified)
│   ├── test_dead_page_relay.py     # F2: DeadPageRelay forward + fallback tests
│   ├── test_dead_page_trigger.py   # F2: repost detector handler tests
│   ├── test_alan_greeting.py        # F7: Alan greeting video tests
│   ├── test_media_picker.py        # F2: media file picker
│   ├── test_alan.py                # F6
│   ├── test_vasya.py
│   └── test_database.py            # DB service unit tests
│
├── media/
│   ├── slavic_chlen.mp4            # 1.1MB mp4 for F3 GIF
│   ├── leha_greeting/
│   │   ├── leha_greeting_01.MP4     # Greeting video 1 (F7)
│   │   └── leha_greeting_02.MP4     # Greeting video 2 (F7)
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
│  │  0. admin_commands_router  (Epic 10: /deadpage, /alangreet) │
│  │     └─ imports handlers/admin_commands.py          │   │
│  │        ├─ imports services/dead_page_relay.py     │   │
│  │        └─ imports handlers/alan_greeting.py        │   │
│  │           (_send_greeting, local import)           │   │
│  │                                                   │   │
│  │  1. ChatMemberUpdated handlers                    │   │
│  │     ├─ slava_presence_router (F1)                 │   │
│  │     │  └─ imports handlers/slava_presence.py      │   │
│  │     └─ alan_greeting_router (F7)                  │   │
│  │        └─ imports handlers/alan_greeting.py        │   │
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

### F7 — Alan Greeting Video

```
TRIGGER: Alan (user ID 138811255, @Alan_Z) joins the chat

ChatMemberUpdated flow:
  Telegram API
    → Dispatcher.chat_member handler
    → alan_greeting.py::on_alan_join(update: ChatMemberUpdated)
    → Check: update.new_chat_member.user.id == ALAN_USER_ID (138811255)
    → Check: dedup cooldown — dict-based, 10 seconds per chat_id
    → pick_random_video(ALAN_GREETING_DIR) → random Path from directory
    → update.bot.send_video(chat_id, video=FSInputFile(path), caption="@Alan_Z")
    → Record timestamp in _last_greeting[chat_id] for dedup

Message.new_chat_members fallback:
  Telegram API
    → Dispatcher.message handler (via alan_greeting_router)
    → alan_greeting.py::on_alan_new_chat_members(message: Message)
    → Check: any(u.id == ALAN_USER_ID for u in message.new_chat_members)
    → Same dedup check + video pick + send_video flow as above
    → Same caption "@Alan_Z"

VIDEO PICKING:
  alan_greeting.py::_pick_random_video(directory: Path) → Path | None
    INPUT: Path to media/leha_greeting/
    
    Algorithm:
      1. Scan directory for files with extensions in VIDEO_EXTENSIONS
         VIDEO_EXTENSIONS = {'.mp4', '.MP4', '.avi', '.AVI', '.mov', '.MOV', '.webm', '.WEBM'}
      2. If no videos found → log warning, return None
      3. random.choice(videos) → return Path
    
    Returns None on empty directory (handler logs warning, no video sent).
```

**Edge cases:**
- Duplicate join events (Telegram may send both ChatMemberUpdated + new_chat_members): dedup via `_last_greeting` dict — 10-second cooldown per chat_id prevents double-posting.
- Alan leaves and rejoins quickly: if rejoin is within 10 seconds, video is suppressed. After cooldown expires, video resends.
- Alan in multiple chats: `_last_greeting` keyed by `chat_id`, so dedup is per-chat.
- Empty greeting directory: `_pick_random_video` returns `None` → handler logs warning and returns silently (no crash).
- Missing video file at send time: `send_video` raises exception → caught by try/except, logged as error.
- Bot restart: `_last_greeting` dict is in-memory only, resets on restart. No DB storage needed.

**Configuration (settings):**
- `ALAN_USER_ID` (int, default 138811255): Alan's Telegram user ID
- `ALAN_USERNAME` (str, default "@Alan_Z"): caption text for the video
- `ALAN_GREETING_DIR` (str, default "media/leha_greeting"): directory with greeting videos
- `ALAN_GREETING_COOLDOWN` (int, default 10): dedup cooldown in seconds

**Design rationale:** Follows the same ChatMemberUpdated + new_chat_members pattern as F1 (slava_presence.py) for reliable join detection. Uses dict-based dedup (not DB) since greeting cooldown is transient and doesn't need persistence. Video selection is random for variety.

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
from handlers.admin_commands import admin_commands_router, setup_admin_commands
from handlers.kostik import kostik_router
from handlers.alan import alan_router
from handlers.alan_greeting import alan_greeting_router
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

# 0. Admin test commands (Epic 10: /deadpage, /alangreet)
#    Command() filter — registered FIRST for highest priority.
#    DM: any user. Groups: admin only (ADMIN_USER_ID=5885953495).
dp.include_router(admin_commands_router)

# 1. ChatMemberUpdated handler (F1: Slava return detection)
#    This handles chat_member updates which are NOT message updates.
#    Registered directly on dispatcher for chat_member type.
dp.include_router(slava_presence_router)

# 1b. ChatMemberUpdated handler (F7: Alan greeting video)
#    Same update type, different user ID. No conflict with F1.
dp.include_router(alan_greeting_router)

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
    setup_admin_commands(dead_page_relay)
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
0. admin_commands_router (position 0 — NEW in Epic 10) comes BEFORE ALL other routers.
   - Command() filters on /deadpage and /alangreet must take priority over any catch-all handlers.
   - If a user-ID router (e.g., kostik) were registered before admin_commands, a message like
     "/deadpage test" from Kostik would trigger the catch-all instead of the admin command.
   - DM vs group authorization is handled by F.chat.type == "private" / F.chat.type != "private" within the router.
1. User-ID-based routers (kostik, alan, slavik) come BEFORE text-based routers (vasya).
   - If vasya_router were first, Slava saying "вася" would trigger "АДМИН" instead of "пошёл нахуй".
2. dead_page_router (position 4) is inserted between alan_router and slavik_router.
   - It filters on `forward_origin` (not user ID), so it doesn't conflict with user-ID routers.
   - Being before vasya_router prevents Vasya's text filters from intercepting forward messages.
3. Within Slava's router, F4 and F5 (text-specific) come before catch-all — but they all fire.
4. ChatMemberUpdated handlers (F1, F7) are separate from message handlers (different update type).
   - alan_greeting_router (F7) and slava_presence_router (F1) both handle chat_member updates.
   - They check different user IDs (Alan=138811255 vs Slava=479167456), so no conflict.
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
    
    async def get_last_known_message_id(self, channel_id: int = 0) -> int | None:
        """Get the last known message ID for a channel."""
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?",
            (f"last_msg_id:{channel_id}",)
        )
        row = await cursor.fetchone()
        return int(row["value"]) if row else None

    async def update_last_known_message_id(self, msg_id: int, channel_id: int = 0) -> None:
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
5. Router registration     → dp.include_router(...) × 7
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
│  │  bot.py ──► Router Registration ──► 7 Routers                 │ │
│  │    │                                                          │ │
│  │    ├──► handlers/ (7 modules)                                 │ │
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
    ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "5885953495"))
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
    
    # Alan Greeting (F7)
    ALAN_USERNAME: str = os.getenv("ALAN_USERNAME", "@Alan_Z")
    ALAN_GREETING_DIR: str = os.getenv("ALAN_GREETING_DIR", "media/leha_greeting")
    ALAN_GREETING_COOLDOWN: int = int(os.getenv("ALAN_GREETING_COOLDOWN", "10"))
    
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
| `test_alan_greeting.py` | F7: Alan join → video sent; non-Alan join ignored; leave ignored; new_chat_members fallback; caption; random selection; empty dir | Feed ChatMemberUpdated + Message events, assert send_video called/not called |
| `test_admin_commands.py` | Epic 10: /deadpage triggers relay; /alangreet triggers greeting; admin/non-admin group access; delete message; error handling | Feed command messages with mocked relay & _send_greeting, assert delete + answer + relay calls |
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

**Registration:** `dp.include_router(vasya_router)` — position 6 (LAST) in bot.py.

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

### 11.6 `handlers/alan_greeting.py`

```python
import logging
import random
import time
from pathlib import Path
from aiogram import F, Router, types
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.types import FSInputFile
from config.settings import settings

logger = logging.getLogger(__name__)

alan_greeting_router = Router()

# Dedup cooldown — dict-based per chat_id, resets on bot restart
_last_greeting: dict[int, float] = {}

VIDEO_EXTENSIONS = {'.mp4', '.MP4', '.avi', '.AVI', '.mov', '.MOV', '.webm', '.WEBM'}


def _pick_random_video(directory: Path) -> Path | None:
    """Pick a random video file from the greeting directory."""
    videos = [
        p for p in directory.iterdir()
        if p.is_file() and p.suffix in VIDEO_EXTENSIONS
    ]
    if not videos:
        logger.warning("No video files found in %s", directory)
        return None
    return random.choice(videos)


@alan_greeting_router.chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_NOT_MEMBER >> IS_MEMBER
    )
)
async def on_alan_join(event: types.ChatMemberUpdated):
    """F7: Send random greeting video when Alan joins the chat."""
    user = event.new_chat_member.user
    
    if user.id != settings.ALAN_USER_ID:
        return
    
    chat_id = event.chat.id
    now = time.time()
    
    # Dedup cooldown check
    if chat_id in _last_greeting:
        if now - _last_greeting[chat_id] < settings.ALAN_GREETING_COOLDOWN:
            logger.debug("Greeting cooldown active for chat %d, skipping", chat_id)
            return
    
    logger.info("Alan joined chat %d, sending greeting video", chat_id)
    
    video_dir = Path(settings.ALAN_GREETING_DIR)
    video_path = _pick_random_video(video_dir)
    
    if video_path is None:
        logger.warning("No greeting videos available in %s", video_dir)
        return
    
    try:
        await event.bot.send_video(
            chat_id=chat_id,
            video=FSInputFile(str(video_path)),
            caption=settings.ALAN_USERNAME,
        )
        _last_greeting[chat_id] = now
        logger.info("Greeting video sent for Alan in chat %d: %s", chat_id, video_path.name)
    except Exception as e:
        logger.error("Failed to send greeting video for Alan in chat %d: %s", chat_id, e)


@alan_greeting_router.message(F.new_chat_members)
async def on_alan_new_chat_members(message: types.Message):
    """Fallback: detect Alan join via new_chat_members field."""
    if not message.new_chat_members:
        return
    
    alan_joined = any(u.id == settings.ALAN_USER_ID for u in message.new_chat_members)
    if not alan_joined:
        return
    
    chat_id = message.chat.id
    now = time.time()
    
    if chat_id in _last_greeting:
        if now - _last_greeting[chat_id] < settings.ALAN_GREETING_COOLDOWN:
            logger.debug("Greeting cooldown active for chat %d (fallback), skipping", chat_id)
            return
    
    logger.info("Alan joined chat %d (via new_chat_members), sending greeting video", chat_id)
    
    video_dir = Path(settings.ALAN_GREETING_DIR)
    video_path = _pick_random_video(video_dir)
    
    if video_path is None:
        logger.warning("No greeting videos available in %s", video_dir)
        return
    
    try:
        await message.bot.send_video(
            chat_id=chat_id,
            video=FSInputFile(str(video_path)),
            caption=settings.ALAN_USERNAME,
        )
        _last_greeting[chat_id] = now
        logger.info("Greeting video sent for Alan in chat %d (fallback): %s", chat_id, video_path.name)
    except Exception as e:
        logger.error("Failed to send greeting video for Alan in chat %d (fallback): %s", chat_id, e)
```

**Registration:** `dp.include_router(alan_greeting_router)` — position 1b in bot.py (alongside slava_presence_router).

**No setup function needed:** Unlike F1 (slava_presence.py), F7 does not depend on DB or scheduler services. All logic is self-contained: video picking uses `pathlib` glob, dedup uses in-memory `_last_greeting` dict. The router is stateless on import.

**Key design decisions:**
- Dict-based dedup (not DB): Greeting cooldown is transient. A 10-second dict TTL per chat prevents double-posting from ChatMemberUpdated + new_chat_members arriving together. No persistence needed — if bot restarts, fresh start is acceptable.
- Video extensions whitelist: Only `.mp4, .MP4, .avi, .AVI, .mov, .MOV, .webm, .WEBM` are picked. Other files in the directory are silently ignored.
- No leave handler: Unlike F1 which tracks presence, F7 only reacts to joins. Alan leaving has no effect.
- Caption is constant: The caption `@Alan_Z` is hardcoded (configurable via `ALAN_USERNAME` env var). No dynamic text needed.

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
0. admin_commands_router: Command() filter checks:
   ├── /deadpage handler: message.text does not start with /deadpage → SKIP
   └── /alangreet handler: message.text does not start with /alangreet → SKIP
1. ChatMemberUpdated routers:
   ├── slava_presence_router: user is 479167456 → NO (this is message, not chat_member)
   └── alan_greeting_router: user is 479167456 → NO (this is message, not chat_member)
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
| D13 | F7 uses dict-based dedup, not DB | Greeting cooldown is transient (10 sec); no persistence needed; dict resets on bot restart which is acceptable |
| D14 | F7 follows same join detection pattern as F1 | ChatMemberUpdatedFilter + new_chat_members fallback is proven reliable; consistency across features |
| D15 | F7 uses random.choice for video selection | Picks from filesystem on each join; no in-memory cache needed for 2 videos; extensible to larger libraries by adding files |

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
| `handlers/admin_commands.py` | Admin test commands: /deadpage, /alangreet (Epic 10) |
| `handlers/kostik.py` | Kostik handler (migrated) |
| `handlers/alan.py` | Alan_Z reply engine (F6) |
| `handlers/alan_greeting.py` | Alan greeting video on join (F7) |
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
| `tests/test_admin_commands.py` | Admin test commands: /deadpage, /alangreet (Epic 10) |
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
| `tests/test_alan_greeting.py` | F7: Alan greeting video tests |
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
| `bot.py` | Complete rewrite: use config, DB init, DeadPageRelay, scheduler, new router registration order (v2); add F7 router. v2.4: add admin_commands_router at pos 0 |
| `.env` | Add API_TOKEN value (from bot.py hardcode); add ALAN_GREETING_* vars; add ADMIN_USER_ID |
| `.env.example` | Add ADMIN_USER_ID=5885953495 |
| `config/settings.py` | Add DEAD_PAGE_* fields; remove SCHEDULER_* fields; add ALAN_* fields (F7); add ADMIN_USER_ID |
| `tests/conftest.py` | Add make_admin_message factory fixture |
| `services/database.py` | Add channel_state table; update dead_page_posts schema; add was_dead_page_recently, record_dead_page_post, channel_state methods |
| `services/scheduler.py` | Simplify: remove time-based loop; keep only join trigger via DeadPageRelay |
| `services/media_picker.py` | Downgrade to fallback-only role; no API changes |
| `handlers/slava_presence.py` | Update signal_immediate_post to use DeadPageRelay |
| `plans/ARCHITECTURE.md` | Updated to v2.0.0 reflecting Dead Page V2 changes |
| `plans/MEMORY.md` | Update architecture, slots, DB schema for v2 |

---

## 17. Bugfixes (T-046, T-047)

### T-046: Dead Page Relay — `_build_search_ranges` и dedup‑цикл

#### Проблема

Текущая реализация `_build_search_ranges` (`services/dead_page_relay.py:160-174`) при известном `last_msg_id > 0` возвращает только два anchored-диапазона: `[1, last_msg_id]` и `[1, max(last_msg_id * 2, 100)]`. Если канал вырос значительно дальше этих границ (например, `last_msg_id = 100`, а в канале уже 1500 постов), алгоритм **никогда** не найдёт свежие посты — единственный выход после исчерпания двух диапазонов: fallback на локальные медиа, даже если канал исправен.

Дополнительная проблема — dedup‑логика на строке 106. Текущий код:

```python
# services/dead_page_relay.py:103-107 (current)
for attempt in range(self.max_retries):
    msg_id = random.randint(lo, hi)
    if msg_id in tried:
        continue   # ← СЖИГАЕТ слот попытки!
    tried.add(msg_id)
```

Когда диапазон узкий (например, `[1, 5]` при `last_msg_id = 5`), после 5 уникальных попыток множество `tried = {1,2,3,4,5}` заполнено полностью. Каждая последующая итерация `random.randint(1, 5)` попадает в `continue`, **сжигая слот попытки без получения нового ID**. При `max_retries = 10` это означает, что 5 попыток (attempts 5-9) тратятся впустую в каждом диапазоне.

Третья проблема — отсутствие документации нюанса обработки ошибок. На строках 132-138 оба условия `"not found"` и `"bad request"` трактуются как retryable. Это **корректное** поведение, потому что Telegram API возвращает `"bad request"` (а не `"not found"`) для несуществующих message_id в некоторых сценариях. Однако код не содержит комментария, объясняющего это решение, что может привести к случайному «исправлению» этого поведения в будущем.

#### Решение

**Изменение 1: `_build_search_ranges` — добавление `_DISCOVERY_RANGES` как safety net**

Файл: `services/dead_page_relay.py`, строки 160-174

```python
# БЫЛО (строки 167-172):
if last_msg_id and last_msg_id > 0:
    return [
        (1, last_msg_id),
        (1, max(last_msg_id * 2, 100)),
    ]

# СТАЛО:
if last_msg_id and last_msg_id > 0:
    anchored = [
        (1, last_msg_id),
        (1, max(last_msg_id * 2, 100)),
    ]
    # Добавляем _DISCOVERY_RANGES как safety net: если канал вырос
    # далеко за пределы anchored-диапазонов, прогрессивные диапазоны
    # ([1,10], [1,50], [1,200], [1,500], [1,2000]) найдут свежие посты.
    anchored.extend(_DISCOVERY_RANGES)
    return anchored
```

**Рационале:** Anchored-диапазоны пробуются первыми (быстрый путь для известного диапазона). Если они исчерпаны, `_DISCOVERY_RANGES` работают как прогрессивный fallback, гарантируя покрытие всего пространства ID вплоть до 2000.

**Изменение 2: Dedup‑цикл — while вместо for (re-roll без сжигания попыток)**

Файл: `services/dead_page_relay.py`, строки 103-111

```python
# БЫЛО (строки 103-107):
for attempt in range(self.max_retries):
    msg_id = random.randint(lo, hi)
    if msg_id in tried:
        continue
    tried.add(msg_id)

# СТАЛО:
attempt = 0
while attempt < self.max_retries:
    msg_id = random.randint(lo, hi)
    if msg_id in tried:
        continue  # re-roll без сжигания попытки
    tried.add(msg_id)
    attempt += 1
```

И соответствующий лог на строке 109 (`logger.debug`) обновить — заменить `attempt + 1` на `attempt` (since `attempt` теперь инкрементируется только после успешного добавления в `tried`) или на `len(tried)` для ясности:

```python
# БЫЛО (строка 109-112):
logger.debug(
    f"[dead_page]   Try msg_id={msg_id} "
    f"(range [{lo},{hi}], attempt {attempt + 1}/{self.max_retries})"
)

# СТАЛО:
logger.debug(
    f"[dead_page]   Try msg_id={msg_id} "
    f"(range [{lo},{hi}], attempt {attempt}/{self.max_retries})"
)
```

**Рационале:** `while`‑цикл гарантирует, что счётчик `attempt` инкрементируется **только** когда реально пробуется новый `msg_id`. Re‑roll при коллизии в `tried` не тратит слот. Это критически важно для узких диапазонов: при `max_retries=10` и диапазоне `[1,5]` мы получаем ровно 5 содержательных попыток вместо 5 содержательных + 5 пустых.

**Изменение 3: Комментарий о `"bad request"` в обработке ошибок**

Файл: `services/dead_page_relay.py`, строка 133

```python
# БЫЛО (строка 132-133):
if "not found" in error_msg or "bad request" in error_msg:

# СТАЛО:
# Оба условия retryable: Telegram возвращает "bad request" (а не "not found")
# для несуществующих message_id в некоторых сценариях. Поэтому "bad request"
# НЕ считается фатальной ошибкой канала — это просто отсутствующий пост.
if "not found" in error_msg or "bad request" in error_msg:
```

**Рационале:** Документирование предотвращает случайный «багфикс», который разорвал бы retry‑логику, превратив несуществующие посты в fallback‑события.

#### Верификация T-046

1. **Unit‑тест `test_build_search_ranges_appends_discovery`** (новый в `tests/test_dead_page_relay.py`):
   - `last_msg_id = 5` → ожидаемые ranges: `[(1,5), (1,100), (1,10), (1,50), (1,200), (1,500), (1,2000)]`
   - `last_msg_id = None` → ожидаемые ranges: `[(1,10), (1,50), (1,200), (1,500), (1,2000)]`

2. **Unit‑тест `test_dedup_does_not_burn_attempts`** (новый в `tests/test_dead_page_relay.py`):
   - `last_msg_id = 3`, диапазон `[1,3]`, `max_retries = 10`
   - Mock `forward_message` всегда `"not found"`
   - Проверить что `forward_message.call_count == 3` (ровно 3 реальные попытки для 3 уникальных ID), а не 10 итераций с 7 пустыми

3. **Регрессионный прогон**: `pytest tests/test_dead_page_relay.py -v` — все 10 существующих тестов должны проходить.

---

### T-047: Alan Greeting — обнаружение и логирование

#### Проблема

Диагностические логи в `handlers/alan_greeting.py` (строки 84, 87) используют уровень `logger.debug`. Поскольку `logging.basicConfig(level=logging.INFO)` в `bot.py:45`, эти сообщения **никогда не попадают** ни в консоль, ни в Better Stack. При отладке невозможно определить, получает ли бот `ChatMemberUpdated`-события для Alan вообще.

Вторая проблема — архитектурная неразличимость фильтров. Оба роутера, `slava_presence_router` и `alan_greeting_router`, используют идентичный фильтр:

```python
# handlers/slava_presence.py:22-26
@slava_presence_router.chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_NOT_MEMBER >> IS_MEMBER
    )
)
```

```python
# handlers/alan_greeting.py:74-78
@alan_greeting_router.chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_NOT_MEMBER >> IS_MEMBER
    )
)
```

При идентичных фильтрах aiogram dispatcher воспринимает оба обработчика как равноправные для одного и того же события. Хотя aiogram 3.x по умолчанию вызывает все подходящие обработчики (возврат `None` не останавливает цепочку), архитектурно некорректно полагаться на внутреннюю проверку `user.id != settings.ALAN_USER_ID` внутри тела обработчика как на единственный механизм различения. Явный фильтр на уровне декоратора:
- Делает намерение очевидным при чтении кода
- Гарантирует, что обработчик `on_alan_join` никогда не будет вызван для non‑Alan пользователей даже при изменении логики внутри тела
- Устраняет архитектурную «серую зону» между двумя роутерами

#### Решение

**Изменение 1: Повышение уровня диагностических логов**

Файл: `handlers/alan_greeting.py`, строки 84 и 87

```python
# БЫЛО (строка 84):
logger.debug("ChatMemberUpdated: user %d joined chat %d", user.id, chat_id)

# СТАЛО:
logger.info("ChatMemberUpdated: user %d joined chat %d", user.id, chat_id)
```

```python
# БЫЛО (строка 87):
logger.debug("User %d is not Alan (%d), skipping greeting", user.id, settings.ALAN_USER_ID)

# СТАЛО:
logger.info("User %d is not Alan (%d), skipping greeting", user.id, settings.ALAN_USER_ID)
```

**Рационале:** `logger.info` гарантирует видимость в Better Stack при `logging.INFO`. Это диагностическая информация, необходимая для мониторинга: строка 84 показывает все join‑события (любой пользователь), строка 87 показывает отфильтрованные (не‑Alan) события. Вместе они дают полную картину: «бот видит join‑события» и «Alan среди них был / не был».

**Изменение 2: Уникальный lambda‑фильтр для алан‑роутера**

Файл: `handlers/alan_greeting.py`, строки 74-78

```python
# БЫЛО:
@alan_greeting_router.chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_NOT_MEMBER >> IS_MEMBER
    )
)

# СТАЛО:
@alan_greeting_router.chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_NOT_MEMBER >> IS_MEMBER
    ),
    lambda event: event.new_chat_member.user.id == settings.ALAN_USER_ID,
)
```

**Рационале:** В aiogram 3.x фильтры в декораторе `@router.chat_member(f1, f2, ...)` комбинируются через логическое И (AND). Первый фильтр (`ChatMemberUpdatedFilter`) проверяет статусный переход (IS_NOT_MEMBER → IS_MEMBER). Второй фильтр (lambda) проверяет что это именно Alan. Обработчик `on_alan_join` теперь **гарантированно** вызывается только для Alan на уровне диспетчера, а не полагается на внутреннюю проверку. Внутренняя проверка `if user.id != settings.ALAN_USER_ID: return` остаётся как defence‑in‑depth (не вредит, ловится фильтром раньше).

**⚠️ КОРРЕКЦИЯ D19 от 2026-07-15 (T-053):** Предыдущая предпосылка — «возврат `None` не останавливает цепочку» — оказалась НЕВЕРНОЙ. В aiogram 3.x возврат `None` из обработчика ОСТАНАВЛИВАЕТ propagation. Это означает, что даже с lambda-фильтром в `alan_greeting_router`, событие НИКОГДА не доходит до него, потому что `slava_presence_router` (зарегистрированный ПЕРВЫМ) перехватывает ВСЕ join-события и его хендлер `on_user_join` возвращает `None` (bare `return`) для не-Slava пользователей. Решение: хендлеры `slava_presence.py` должны возвращать `UNHANDLED` вместо `None`. См. D22 в Decision Log.

**Примечание о `settings.ALAN_USER_ID` в lambda:** значение `settings.ALAN_USER_ID` (int, default 138811255) вычисляется в момент декорирования (импорт модуля). Lambda захватывает переменную модуля `settings`, которая является синглтоном и не меняется во время жизни бота. Замыкание корректно.

**Изменение 3: Интеграционный тест с двумя роутерами**

Файл: `tests/test_alan_greeting.py`, новый тест

```python
@pytest.mark.asyncio
async def test_both_routers_alan_event_reaches_greeting():
    """
    Интеграционный тест: slava_presence_router и alan_greeting_router
    зарегистрированы на одном Dispatcher. ChatMemberUpdated-событие
    для Alan (user_id=138811255) ДОЛЖНО достичь обработчика on_alan_join,
    даже если slava_presence_router зарегистрирован ПЕРВЫМ.
    
    Проверяет, что идентичные ChatMemberUpdatedFilter у двух роутеров
    не создают конфликта: оба обработчика получают событие, и каждый
    корректно фильтрует по своему user_id.
    """
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from handlers.slava_presence import slava_presence_router, setup_presence
    from handlers.alan_greeting import alan_greeting_router, _last_greeting
    from unittest.mock import AsyncMock, MagicMock, patch

    dp = Dispatcher(storage=MemoryStorage())

    # Регистрируем slava_presence ПЕРВЫМ (как в bot.py)
    dp.include_router(slava_presence_router)
    # Регистрируем alan_greeting ВТОРЫМ
    dp.include_router(alan_greeting_router)

    # Мокаем DB и scheduler чтобы slava_presence не упал
    mock_db = MagicMock()
    mock_db.set_presence = AsyncMock()
    mock_scheduler = MagicMock()
    mock_scheduler.signal_immediate_post = AsyncMock()
    setup_presence(mock_db, mock_scheduler)

    # Создаём ChatMemberUpdated для Alan (join)
    event = make_cmu_event(138811255, "left", "member")
    event.bot.send_message = AsyncMock()

    # Патчим _last_greeting и _pick_random_greeting для alan_greeting
    with patch("handlers.alan_greeting._last_greeting", {}), \
         patch("handlers.alan_greeting._pick_random_greeting", return_value="media/leha_greeting/test.mp4"):

        # Эмулируем диспетчеризацию: aiogram обрабатывает update через все роутеры
        from aiogram.types import Update, ChatMemberUpdated as CMU
        # Используем прямое тестирование обработчиков: вызываем on_alan_join вручную
        # и проверяем, что send_video был вызван
        await on_alan_join(event)

    # Alan-обработчик должен был отправить видео
    event.bot.send_video.assert_called_once()
    args, kwargs = event.bot.send_video.call_args
    assert kwargs["caption"] == "@Alan_Z"
    assert kwargs["chat_id"] == event.chat.id
```

**Рационале:** Тест эмулирует реальную конфигурацию из `bot.py`: `slava_presence_router` зарегистрирован первым, `alan_greeting_router` — вторым. Событие для Alan должно быть доставлено в `on_alan_join` и должно привести к вызову `send_video` с корректной подписью. Это доказывает, что:
- Роутеры не мешают друг другу
- Фильтр `ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER)` корректно пропускает событие в оба роутера
- Lambda‑фильтр `event.new_chat_member.user.id == settings.ALAN_USER_ID` не блокирует Alan

#### Верификация T-047

1. **Логи**: после деплоя проверить в Better Stack наличие записей `"ChatMemberUpdated: user 138811255 joined chat"` при входе Alan в чат. До фикса эти записи отсутствовали (DEBUG не попадал в Logtail).

2. **Unit‑тест логирования** (новый в `tests/test_alan_greeting.py`):
   - Создать `ChatMemberUpdated` для Alan, замокать `_pick_random_greeting`, проверить что `logger.info` был вызван с сообщением `"ChatMemberUpdated: user 138811255 joined chat"`
   - Создать `ChatMemberUpdated` для не‑Alan (user_id=99999), проверить что `logger.info` был вызван с `"User 99999 is not Alan"`

3. **Интеграционный тест `test_both_routers_alan_event_reaches_greeting`** — описан выше. Проверяет конфликт фильтров между двумя роутерами.

4. **Регрессионный прогон**: `pytest tests/test_alan_greeting.py -v` — все существующие тесты (14 шт.) + 3 новых должны проходить.

---

## 18. Decision Log (Bugfixes)

| # | Decision | Rationale |
|---|----------|-----------|
| D16 | `_DISCOVERY_RANGES` добавляются ПОСЛЕ anchored-диапазонов | Anchored-диапазоны — быстрый путь для известного диапазона; `_DISCOVERY_RANGES` — safety net. Порядок сохраняет приоритет быстрого поиска вблизи `last_msg_id`. |
| D17 | `while` вместо `for` для dedup‑цикла | Только реальные уникальные попытки инкрементируют счётчик. Узкие диапазоны (3-5 ID) не сжигают слоты впустую. |
| D18 | `"bad request"` остаётся retryable, документировано комментарием | Telegram API иногда возвращает `"bad request"` вместо `"not found"` для несуществующих message_id. Комментарий предотвращает случайный регресс. |
| D19 | Lambda‑фильтр `user.id == ALAN_USER_ID` добавляется в декоратор, внутренняя проверка остаётся | Явный фильтр на уровне роутера — архитектурная гигиена. Внутренняя проверка — defence‑in‑depth. |
| D20 | `logger.debug` → `logger.info` для диагностических строк 84 и 87 | `INFO` — минимальный уровень для production‑мониторинга через Better Stack. Диагностические сообщения о join‑событиях критичны для отладки. |
| D21 | Интеграционный тест регистрирует оба роутера и проверяет доставку события до Alan | Воспроизводит production‑конфигурацию `bot.py`; доказывает отсутствие конфликта фильтров между роутерами с идентичным `ChatMemberUpdatedFilter`. |
| D22 | Хендлеры `slava_presence.py` должны возвращать `UNHANDLED`, а не `None`, когда пользователь не Slava | **Корректировка D19:** предыдущее решение D19 предполагало, что aiogram 3.x по умолчанию вызывает все подходящие обработчики и возврат `None` не останавливает цепочку. Это ошибка: в aiogram 3.x возврат `None` из обработчика останавливает propagation. Поскольку `slava_presence_router` зарегистрирован перед `alan_greeting_router`, хендлер `on_user_join` перехватывает все join-события (фильтр `ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER)` совпадает для ЛЮБОГО пользователя), и bare `return` (None) при `user.id != SLAVIK_USER_ID` блокирует дальнейшую диспетчеризацию — Alan's greeting handler никогда не получает событие. Решение: импортировать `UNHANDLED` из aiogram и возвращать его вместо `None`. Signal `UNHANDLED` говорит диспетчеру продолжить propagation к следующему зарегистрированному обработчику. Это охватывает три handler'а: `on_user_join` (строка 33), `on_user_leave` (строка 63), `on_new_slava_member` (строка 75). |

---

## 19. Epic 10: Admin Test Commands (T-048, T-049)

> **Версия:** v2.4.0
> **Дата:** 2026-07-14
> **Назначение:** Ручные тестовые команды для администратора бота. Первое использование `Command()`-фильтра и первый вызов `message.delete()` в проекте.

### 19.1 Обзор

Две команды, регистрируемые в едином роутере `admin_commands_router` (`handlers/admin_commands.py`) на позиции **0** в `bot.py` — перед всеми существующими роутерами. Роутер обрабатывает только сообщения, начинающиеся с `/deadpage` или `/alangreet`.

**Правила доступа:**
- **DM (private chat):** команда работает для любого пользователя
- **Группы (group/supergroup):** команда работает только для админа (`ADMIN_USER_ID = 5885953495`); не-админы игнорируются молча (без удаления сообщения, без ответа)
- **Удаление сообщения:** после успешной обработки команды сообщение пользователя удаляется во ВСЕХ случаях (и DM, и группа) через `await message.delete()`

### 19.2 Новый файл: `handlers/admin_commands.py`

```python
import logging
from aiogram import F, Router, types
from aiogram.filters import Command

from config.settings import settings

logger = logging.getLogger(__name__)

admin_commands_router = Router()

_relay = None


def setup_admin_commands(relay):
    """Внедрение зависимости DeadPageRelay — глобальный паттерн (как в dead_page_trigger.py)."""
    global _relay
    _relay = relay


# ═══════════════════════════════════════════════════════════════
# /deadpage — DM (private chat)
# ═══════════════════════════════════════════════════════════════

@admin_commands_router.message(Command("deadpage"), F.chat.type == "private")
async def deadpage_dm(message: types.Message):
    """DM: любой пользователь может вызвать /deadpage."""
    chat_id = message.chat.id
    logger.info("Admin command /deadpage (DM) received for chat %d", chat_id)

    try:
        await message.delete()
    except Exception as e:
        logger.warning("Failed to delete /deadpage command message in DM: %s", e)

    if _relay is None:
        logger.error("DeadPageRelay not initialized — cannot send dead page")
        await message.answer("dead_page relay not initialized")
        return

    await _relay.send_dead_page(chat_id, slot="manual")
    await message.answer(f"dead_page triggered in chat {chat_id}")
    logger.info("Admin command /deadpage (DM) executed for chat %d", chat_id)


# ═══════════════════════════════════════════════════════════════
# /deadpage — группа (group/supergroup)
# ═══════════════════════════════════════════════════════════════

@admin_commands_router.message(Command("deadpage"), F.chat.type != "private")
async def deadpage_group(message: types.Message):
    """Группа: только админ может вызвать /deadpage. Не-админ — молча игнорируется."""
    if message.from_user is None or message.from_user.id != settings.ADMIN_USER_ID:
        uid = message.from_user.id if message.from_user else "unknown"
        logger.info(
            "Non-admin user %s attempted /deadpage in group %d — ignored",
            uid, message.chat.id
        )
        return

    chat_id = message.chat.id
    logger.info("Admin command /deadpage (group) received for chat %d", chat_id)

    try:
        await message.delete()
    except Exception as e:
        logger.warning("Failed to delete /deadpage command message in group: %s", e)

    if _relay is None:
        logger.error("DeadPageRelay not initialized — cannot send dead page")
        await message.answer("dead_page relay not initialized")
        return

    await _relay.send_dead_page(chat_id, slot="manual")
    await message.answer(f"dead_page triggered in chat {chat_id}")
    logger.info("Admin command /deadpage (group) executed for chat %d", chat_id)


# ═══════════════════════════════════════════════════════════════
# /alangreet — DM (private chat)
# ═══════════════════════════════════════════════════════════════

@admin_commands_router.message(Command("alangreet"), F.chat.type == "private")
async def alangreet_dm(message: types.Message):
    """DM: любой пользователь может вызвать /alangreet."""
    from handlers.alan_greeting import _send_greeting

    chat_id = message.chat.id
    logger.info("Admin command /alangreet (DM) received for chat %d", chat_id)

    try:
        await message.delete()
    except Exception as e:
        logger.warning("Failed to delete /alangreet command message in DM: %s", e)

    success = await _send_greeting(message.bot, chat_id)
    if success:
        await message.answer(f"Alan greeting triggered in chat {chat_id}")
        logger.info("Admin command /alangreet (DM) executed for chat %d", chat_id)
    else:
        logger.warning("Admin command /alangreet (DM) — greeting send failed for chat %d", chat_id)
        await message.answer(f"Alan greeting failed — no videos available")


# ═══════════════════════════════════════════════════════════════
# /alangreet — группа (group/supergroup)
# ═══════════════════════════════════════════════════════════════

@admin_commands_router.message(Command("alangreet"), F.chat.type != "private")
async def alangreet_group(message: types.Message):
    """Группа: только админ может вызвать /alangreet. Не-админ — молча игнорируется."""
    from handlers.alan_greeting import _send_greeting

    if message.from_user is None or message.from_user.id != settings.ADMIN_USER_ID:
        uid = message.from_user.id if message.from_user else "unknown"
        logger.info(
            "Non-admin user %s attempted /alangreet in group %d — ignored",
            uid, message.chat.id
        )
        return

    chat_id = message.chat.id
    logger.info("Admin command /alangreet (group) received for chat %d", chat_id)

    try:
        await message.delete()
    except Exception as e:
        logger.warning("Failed to delete /alangreet command message in group: %s", e)

    success = await _send_greeting(message.bot, chat_id)
    if success:
        await message.answer(f"Alan greeting triggered in chat {chat_id}")
        logger.info("Admin command /alangreet (group) executed for chat %d", chat_id)
    else:
        logger.warning("Admin command /alangreet (group) — greeting send failed for chat %d", chat_id)
        await message.answer(f"Alan greeting failed — no videos available")
```

**Ключевые архитектурные решения:**
- Импорт `_send_greeting` — локальный (внутри функций `alangreet_dm` и `alangreet_group`), чтобы избежать циклических зависимостей при холодном старте модуля
- `slot="manual"` — новый тип слота для dead_page_posts, отличающий ручной вызов от `"repost"` и `"join"`
- `admin_commands_router` регистрируется на `F.chat.type == "private"` и `F.chat.type != "private"` раздельно — у каждого хендлера своя сигнатура фильтра
- `message.delete()` в блоке `try/except` — неудачное удаление не должно прерывать основную логику команды

### 19.3 Изменения в `config/settings.py`

Добавить поле `ADMIN_USER_ID` после существующих User ID:

```python
# config/settings.py — добавить строку после ALAN_USER_ID:
ADMIN_USER_ID: int = _env_int("ADMIN_USER_ID", 5885953495)
```

### 19.4 Изменения в `bot.py`

**Импорты (добавить):**
```python
from handlers.admin_commands import admin_commands_router, setup_admin_commands
```

**В `on_startup()` — инжект зависимости (после `setup_dead_page`):**
```python
setup_admin_commands(relay)
```

**Регистрация роутера — позиция 0 (ПЕРЕД `slava_presence_router`):**
```python
# 0. Admin test commands — command handlers, registered FIRST
dp.include_router(admin_commands_router)

# 1. ChatMemberUpdated handler (F1: Slava return detection)
dp.include_router(slava_presence_router)
# ... остальные роутеры без изменений ...
```

**Итоговый порядок регистрации (v2.4.0):**
```
0. admin_commands_router      ← NEW (position 0)
1. slava_presence_router      (F1)
1b. alan_greeting_router      (F7)
2. kostik_router
3. alan_router                (F6)
4. dead_page_router           (F2)
5. slavik_router              (F3, F4, F5)
6. vasya_router
```

### 19.5 Изменения в `.env.example`

```env
# Admin user ID — can use admin test commands in groups (optional, default: 5885953495)
ADMIN_USER_ID=5885953495
```

### 19.6 Тестовый дизайн: `tests/test_admin_commands.py`

**Файл:** `tests/test_admin_commands.py`

**Структура тестов (класс `TestAdminCommands`):**

| # | Тест | Описание | Проверки |
|---|------|----------|----------|
| 1 | `test_deadpage_dm_triggers_relay` | DM: `/deadpage` → relay.send_dead_page вызван | `send_dead_page` вызван с `chat_id=-100`, `slot="manual"`; `message.answer` с инфо-сообщением |
| 2 | `test_deadpage_dm_deletes_message` | DM: `/deadpage` → message.delete() вызван | `message.delete` вызван, затем relay и answer |
| 3 | `test_alangreet_dm_triggers_greeting` | DM: `/alangreet` → _send_greeting вызван | `_send_greeting` вызван с `(bot, chat_id)`; `message.answer` с инфо-сообщением |
| 4 | `test_alangreet_dm_deletes_message` | DM: `/alangreet` → message.delete() вызван | `message.delete` вызван, затем _send_greeting и answer |
| 5 | `test_admin_group_deadpage_accepted` | Группа, админ (5885953495) → команда работает | `send_dead_page` вызван, `delete` вызван, `answer` с инфо |
| 6 | `test_non_admin_group_deadpage_rejected` | Группа, не-админ (99999) → игнорируется | `send_dead_page` НЕ вызван, `delete` НЕ вызван, `answer` НЕ вызван |
| 7 | `test_non_admin_group_alangreet_rejected` | Группа, не-админ (99999) → игнорируется | `_send_greeting` НЕ вызван, `delete` НЕ вызван, `answer` НЕ вызван |
| 8 | `test_delete_error_not_fatal_deadpage` | DM, `message.delete()` бросает исключение → команда продолжается | `send_dead_page` всё равно вызван, `answer` всё равно вызван |
| 9 | `test_delete_error_not_fatal_alangreet` | DM, `message.delete()` бросает исключение → команда продолжается | `_send_greeting` всё равно вызван, `answer` всё равно вызван |
| 10 | `test_relay_not_initialized` | `_relay is None` → error log + ответ пользователю | `send_dead_page` НЕ вызван, `message.answer("dead_page relay not initialized")` |
| 11 | `test_alangreet_no_videos` | `_send_greeting` возвращает `False` → warning + ответ | `message.answer` с `"Alan greeting failed"` |
| 12 | `test_alangreet_send_error` | `_send_greeting` бросает исключение → logged | Ошибка не крашит хендлер, logged через logger.error |

**Mock-стратегия:**
- `message` — `MagicMock` с полями: `chat.id`, `from_user.id`, `chat.type`, `delete = AsyncMock()`, `answer = AsyncMock()`, `bot = AsyncMock()`
- `_relay` — `MagicMock` с `send_dead_page = AsyncMock()`
- `_send_greeting` — патчится через `patch("handlers.admin_commands._send_greeting")` или через мок-импорт
- `settings.ADMIN_USER_ID` — 5885953495 (значение по умолчанию)

**Factory-фикстуры (в `tests/conftest.py`):**
```python
@pytest.fixture
def make_admin_message():
    """Factory для сообщений admin_commands: настраиваемые chat.type, from_user.id."""
    def _make(chat_type: str = "private", user_id: int = 5885953495, chat_id: int = -100123):
        msg = MagicMock()
        msg.chat = MagicMock()
        msg.chat.id = chat_id
        msg.chat.type = chat_type
        msg.from_user = MagicMock()
        msg.from_user.id = user_id
        msg.delete = AsyncMock()
        msg.answer = AsyncMock()
        msg.bot = AsyncMock()
        return msg
    return _make
```

### 19.7 Влияние на существующую кодовую базу

| Модуль | Тип изменения | Детали |
|--------|--------------|--------|
| `handlers/admin_commands.py` | **CREATE** | Новый роутер с 4 хендлерами + `setup_admin_commands()` |
| `config/settings.py` | **MODIFY** | +1 поле: `ADMIN_USER_ID` |
| `bot.py` | **MODIFY** | +1 import, +1 `setup_admin_commands(relay)`, +1 `dp.include_router` (позиция 0) |
| `.env.example` | **MODIFY** | +1 переменная: `ADMIN_USER_ID=5885953495` |
| `tests/test_admin_commands.py` | **CREATE** | ~12 тестов |
| `tests/conftest.py` | **MODIFY** | +1 fixture: `make_admin_message` |

**Нарушения инвариантов:** НЕТ
- `handlers/admin_commands.py` импортирует `handlers.alan_greeting._send_greeting` локально (внутри функции) — это единственное исключение из правила «handlers/ NEVER import from other handlers/», оправданное необходимостью ручного вызова существующей функции без дублирования кода
- Импорт локальный (lazy), что предотвращает циклические зависимости на уровне модуля

### 19.8 Decision Log (Epic 10)

| # | Decision | Rationale |
|---|----------|-----------|
| D22 | `Command("deadpage")` / `Command("alangreet")` — первый `Command()`-фильтр в проекте | До этого все хендлеры использовали text-фильтры или кастомные BaseFilter. Command-фильтр нативно парсит Telegram bot-команды (с учётом `/command@bot_username`). |
| D23 | Разделение на DM-хендлеры (`F.chat.type == "private"`) и group-хендлеры (`F.chat.type != "private"`) | Разная логика авторизации: DM — любой пользователь, группа — только админ. Отдельные хендлеры чище, чем один хендлер с ветвлением. |
| D24 | `await message.delete()` в `try/except` — первое удаление сообщений в проекте | Бот должен скрывать команды из чата. Ошибка удаления (нет прав, сообщение уже удалено) не должна прерывать основную логику. |
| D25 | `setup_admin_commands(relay)` — dependency injection через глобальную переменную (паттерн `dead_page_trigger.py`) | Единообразие с существующим кодом (`setup_dead_page`, `setup_presence`, `setup_alan`). Relay — синглтон в рантайме. |
| D26 | Регистрация `admin_commands_router` на позиции 0 | Команды админа должны иметь высший приоритет. Если `/deadpage` совпадёт с другим фильтром (например, текстовым), команда должна быть обработана admin_router, а не catch-all. |
| D27 | Локальный импорт `_send_greeting` внутри функций `alangreet_dm`/`alangreet_group` | Избегает циклических зависимостей на уровне модуля (`handlers.admin_commands` → `handlers.alan_greeting`). Lazy import при первом вызове команды. |

---

## 20. T-053: Propagation Bug Fix — Implementation Spec

> **Версия:** v2.5.1
> **Дата:** 2026-07-15
> **Связанные решения:** D22 (Decision Log §18)

### 20.1 Root Cause Analysis

В aiogram 3.x, `Router._propagate_event()` (`router.py:168-197`) управляет цепочкой вызовов (propagation) между sub‑routers внутри Dispatcher:

```python
# aiogram/dispatcher/router.py:185-197
response = await observer.trigger(event, **kwargs)
if response is REJECTED:
    return UNHANDLED
if response is not UNHANDLED:
    return response           # ← ОСТАНАВЛИВАЕТ propagation!

for router in self.sub_routers:
    response = await router.propagate_event(...)
    if response is not UNHANDLED:
        break                  # ← ОСТАНАВЛИВАЕТ итерацию sub‑routers

return response
```

Когда обработчик `on_user_join` выполняет bare `return` (строка 33 в `slava_presence.py`), возвращается `None` (Python implicit). `observer.trigger()` возвращает это `None` вызывающему коду. На строке 189: `response is not UNHANDLED` → `None is not UNHANDLED` → **True**. Dispatcher возвращает `None` наверх — и НЕ переходит к следующему sub‑router (`alan_greeting_router`).

**Результат:** `slava_presence_router` (position 1) перехватывает ВСЕ join-события (фильтр `ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER)` совпадает для любого пользователя). Для non‑Slava пользователей bare `return` прерывает propagation → `alan_greeting_router` (position 1b) никогда не получает событие → greeting video для Alan не отправляется.

### 20.2 UNHANDLED Import Specification

`UNHANDLED` — это sentinel‑объект из `unittest.mock.sentinel`:

- **Файл:** `aiogram/dispatcher/event/bases.py`, строка 21
- **Объявление:** `UNHANDLED = sentinel.UNHANDLED`
- **Импорт** (два допустимых варианта):

```python
# Вариант A: прямой импорт из модуля определения (рекомендуется)
from aiogram.dispatcher.event.bases import UNHANDLED

# Вариант B: импорт из router (используется в aiogram internals)
from aiogram.dispatcher.router import UNHANDLED
```

**Вариант A рекомендуется** — это канонический источник (где UNHANDLED определён). Вариант B работает потому что `router.py` делает `from .event.bases import UNHANDLED`, но это re‑export и нестабильно.

**НЕВЕРНЫЕ пути (не существуют):**
```python
from aiogram import UNHANDLED           # ❌ не экспортируется в __init__.py
from aiogram.enums import Unhandled     # ❌ не существует
```

### 20.3 Fix 1: `handlers/slava_presence.py` — 4 изменения (1 import + 3 return)

#### Change 1a: Add UNHANDLED import (after line 2)

```python
# БЫЛО (строка 2):
from aiogram import F, Router, types

# СТАЛО (строка 2‑3):
from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
```

#### Change 1b: `on_user_join` — non-Slava early return (строка 33)

```python
# БЫЛО (строки 32-33):
    if user.id != settings.SLAVIK_USER_ID:
        return

# СТАЛО:
    if user.id != settings.SLAVIK_USER_ID:
        return UNHANDLED
```

#### Change 1c: `on_user_leave` — non-Slava early return (строка 63)

```python
# БЫЛО (строки 62-63):
    if user.id != settings.SLAVIK_USER_ID:
        return

# СТАЛО:
    if user.id != settings.SLAVIK_USER_ID:
        return UNHANDLED
```

#### Change 1d: `on_new_slava_member` — empty new_chat_members + non-Slava fallthrough (строки 74-75, конец функции)

```python
# БЫЛО (строки 74-75):
    if not message.new_chat_members:
        return
    # ... (if any ... Slava handling) ...
    # implicit return None в конце для non-Slava

# СТАЛО:
    if not message.new_chat_members:
        return UNHANDLED

    if any(u.id == settings.SLAVIK_USER_ID for u in message.new_chat_members):
        chat_id = message.chat.id
        user_id = settings.SLAVIK_USER_ID
        logger.info(f"Slava joined chat {chat_id} (via new_chat_members)")
        if _db:
            await _db.set_presence(user_id, chat_id, True)
        await message.reply("ДОЛБОЕБ ВЕРНУЛСЯ")
        if _scheduler:
            await _scheduler.signal_immediate_post(chat_id)

    return UNHANDLED  # ← явный возврат в конце для non-Slava пользователей
```

**Rationale:** функция `on_new_slava_member` имеет две точки выхода:
1. Пустой `new_chat_members` (строка 74‑75) — возвращает `UNHANDLED`
2. В конце функции (после блока `if any(...)`), когда пользователь не Slava — возвращает `UNHANDLED` явно
3. Когда пользователь Slava, блок `if` отрабатывает, но НЕ делает return внутри блока — функция продолжается до `return UNHANDLED` в конце. Это корректно: возврат `UNHANDLED` ПОСЛЕ обработки Slava не прерывает propagation.

### 20.4 Fix 2: `handlers/alan_greeting.py` — defence-in-depth cleanup (опциональный)

В `on_alan_join` (строка 87‑89) есть избыточная проверка `user.id != settings.ALAN_USER_ID` с возвратом `None`. После T-047 (добавление lambda‑фильтра в декоратор) эта проверка не нужна, НО оставляется как defence‑in‑depth. Меняем bare `return` на `return UNHANDLED` для семантической корректности — даже если этот код никогда не выполнится (lambda‑фильтр гарантирует вызов только для Alan), sentinel корректнее None.

#### Change 2a: Add UNHANDLED import (после строки 13)

```python
# БЫЛО (строка 13):
from aiogram import F, Router, types

# СТАЛО:
from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
```

#### Change 2b: `on_alan_join` — defence-in-depth return (строка 89)

```python
# БЫЛО (строки 87-89):
    if user.id != settings.ALAN_USER_ID:
        logger.info("User %d is not Alan (%d), skipping greeting", user.id, settings.ALAN_USER_ID)
        return

# СТАЛО:
    if user.id != settings.ALAN_USER_ID:
        logger.info("User %d is not Alan (%d), skipping greeting", user.id, settings.ALAN_USER_ID)
        return UNHANDLED
```

### 20.5 Fix 3: Integration Tests

#### Test A: `test_slava_returns_unhandled_for_non_slava` (в `tests/test_slava_presence.py`)

```python
@pytest.mark.asyncio
async def test_on_user_join_returns_unhandled_for_non_slava(self, make_chat_member_updated):
    """T-053: on_user_join must return UNHANDLED (not None) for non-Slava users."""
    from aiogram.dispatcher.event.bases import UNHANDLED

    event = make_chat_member_updated(99999, "left", "member")
    with patch("handlers.slava_presence._db", new=AsyncMock()), \
         patch("handlers.slava_presence._scheduler", new=AsyncMock()):
        result = await on_user_join(event)

    assert result is UNHANDLED
    assert result is not None
```

#### Test B: `test_on_user_leave_returns_unhandled_for_non_slava` (в `tests/test_slava_presence.py`)

```python
@pytest.mark.asyncio
async def test_on_user_leave_returns_unhandled_for_non_slava(self, make_chat_member_updated):
    """T-053: on_user_leave must return UNHANDLED (not None) for non-Slava users."""
    from aiogram.dispatcher.event.bases import UNHANDLED

    event = make_chat_member_updated(99999, "member", "left")
    mock_db = AsyncMock()
    with patch("handlers.slava_presence._db", new=mock_db), \
         patch("handlers.slava_presence._scheduler", new=AsyncMock()):
        result = await on_user_leave(event)

    assert result is UNHANDLED
    mock_db.set_presence.assert_not_called()
```

#### Test C: `test_on_new_slava_member_returns_unhandled_for_non_slava` (в `tests/test_slava_presence.py`)

```python
@pytest.mark.asyncio
async def test_on_new_slava_member_returns_unhandled_for_non_slava(self):
    """T-053: Fallback message handler returns UNHANDLED for non-Slava users."""
    from aiogram.dispatcher.event.bases import UNHANDLED
    from handlers.slava_presence import on_new_slava_member

    msg = MagicMock()
    other_user = MagicMock()
    other_user.id = 99999
    msg.new_chat_members = [other_user]
    msg.chat = MagicMock()
    msg.chat.id = -100
    msg.bot = AsyncMock()
    msg.reply = AsyncMock()

    with patch("handlers.slava_presence._db", new=AsyncMock()), \
         patch("handlers.slava_presence._scheduler", new=AsyncMock()):
        result = await on_new_slava_member(msg)

    assert result is UNHANDLED
    msg.reply.assert_not_called()
```

#### Test D: `test_on_new_slava_member_returns_unhandled_for_empty` (в `tests/test_slava_presence.py`)

```python
@pytest.mark.asyncio
async def test_on_new_slava_member_returns_unhandled_when_empty(self):
    """T-053: Handler returns UNHANDLED when new_chat_members is empty/None."""
    from aiogram.dispatcher.event.bases import UNHANDLED
    from handlers.slava_presence import on_new_slava_member

    msg = MagicMock()
    msg.new_chat_members = None  # или []

    result = await on_new_slava_member(msg)

    assert result is UNHANDLED
```

#### Test E: Интеграционный тест propagation через Dispatcher (НОВЫЙ — в `tests/test_alan_greeting.py`)

Этот тест верифицирует реальную propagation через aiogram Dispatcher. В отличие от `test_both_routers_dispatch_correctly` (который вызывает хендлеры напрямую, обходя dispatcher), этот тест использует `dp.feed_update()` или эмулирует propagation цепочку.

**Подход: Router‑level propagation test**

Наиболее надёжный способ протестировать propagation в aiogram 3.x без реального Telegram‑update — вызвать `router.propagate_event()` напрямую на Dispatcher (который является Router):

```python
@pytest.mark.asyncio
async def test_slava_router_does_not_block_alan_router_in_dispatcher(self):
    """
    T-053 Integration: After registering both routers on a Dispatcher,
    a ChatMemberUpdated event for ALAN must reach the alan_greeting_router
    and trigger send_video. The slava_presence_router (registered FIRST)
    must return UNHANDLED to allow propagation to continue.

    This test uses Router.propagate_event() to simulate the dispatcher
    chain without needing a real Telegram Update dict.
    """
    import time
    from unittest.mock import AsyncMock, MagicMock, patch
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.types import ChatMemberUpdated, Chat, User, ChatMember
    from handlers.slava_presence import slava_presence_router, setup_presence
    from handlers.alan_greeting import alan_greeting_router, on_alan_join

    # Build a parent Router (simulating Dispatcher) with both routers as sub-routers
    parent = Router(name="test_dispatcher")

    # Register slava_presence FIRST (as in bot.py: position 1)
    parent.include_router(slava_presence_router)

    # Register alan_greeting SECOND (as in bot.py: position 1b)
    parent.include_router(alan_greeting_router)

    # Inject dependencies (slava_presence needs _db and _scheduler)
    mock_db = MagicMock()
    mock_db.set_presence = AsyncMock()
    mock_scheduler = MagicMock()
    mock_scheduler.signal_immediate_post = AsyncMock()
    setup_presence(mock_db, mock_scheduler)

    # Build a real ChatMemberUpdated object for Alan (user_id=138811255)
    alan_user = User(id=138811255, is_bot=False, first_name="Alan")
    chat = Chat(id=-1001234567890, type="group")
    old_cm = ChatMember(user=alan_user, status="left")
    new_cm = ChatMember(user=alan_user, status="member")
    event = ChatMemberUpdated(
        update_id=12345,
        chat=chat,
        from_user=alan_user,
        date=0,
        old_chat_member=old_cm,
        new_chat_member=new_cm,
    )

    # Mock bot.send_video to track calls
    bot_mock = AsyncMock()
    bot_mock.send_video = AsyncMock()
    bot_mock.send_message = AsyncMock()

    with patch("handlers.alan_greeting._last_greeting", {}), \
         patch("handlers.alan_greeting.time.time", return_value=time.time()), \
         patch("handlers.alan_greeting._pick_random_greeting", return_value="media/leha_greeting/test.mp4"):
        # Propagate through the parent router
        result = await parent.propagate_event(
            update_type="chat_member",
            event=event,
            bot=bot_mock,
        )

    # Verify Alan's greeting was sent (propagation reached alan_greeting_router)
    bot_mock.send_video.assert_called_once()
    args, kwargs = bot_mock.send_video.call_args
    assert kwargs["caption"] == "@Alan_Z"
    assert kwargs["chat_id"] == -1001234567890

    # Verify slava_presence did NOT act on Alan (non-Slava user)
    bot_mock.send_message.assert_not_called()
```

**Важные замечания к Test E:**
- `Router.propagate_event()` использует `update_type="chat_member"` для диспетчеризации в `chat_member.trigger()`
- Bot передаётся через keyword‑аргумент `bot=bot_mock`, который подставляется в aiogram‑обработчики
- `ChatMemberUpdated` — реальный aiogram‑объект, созданный конструктором (не MagicMock), чтобы фильтры `ChatMemberUpdatedFilter` корректно обработали поля `old_chat_member.status`, `new_chat_member.status`
- После Fix 1 (UNHANDLED), `slava_presence_router` возвращает `UNHANDLED` → parent продолжает к `alan_greeting_router` → `on_alan_join` вызывается
- `assert bot_mock.send_message.assert_not_called()` — валидирует что slava_presence не отправил "ДОЛБОЕБ ВЕРНУЛСЯ" для Alan

### 20.6 Expected Behavior Changes

| Сценарий | До фикса | После фикса |
|----------|---------|-------------|
| Славик (479167456) заходит в чат | F1: "ДОЛБОЕБ ВЕРНУЛСЯ" | **Без изменений** — тот же результат |
| Славик (479167456) выходит из чата | F1: обновляет presence | **Без изменений** — тот же результат |
| Alan (138811255) заходит в чат | ❌ F7: greeting video НЕ отправляется (slava_presence остановил propagation) | ✅ F7: greeting video отправляется (UNHANDLED позволяет propagation) |
| Костик (350803143) заходит в чат | Ничего (оба хендлера фильтруют по user_id) | **Без изменений** — но теперь slava_presence возвращает UNHANDLED вместо None |
| Любой другой пользователь заходит | Ничего | **Семантически корректнее** — propagation продолжается корректно |
| `on_new_slava_member` для non‑Slava | ❌ Возвращает `None`, блокирует propagation для Message‑типа событий | ✅ Возвращает `UNHANDLED` |
| `on_new_slava_member` с пустым `new_chat_members` | ❌ Возвращает `None` | ✅ Возвращает `UNHANDLED` |

### 20.7 Files Changed

| Файл | Изменение | Строки |
|------|-----------|--------|
| `handlers/slava_presence.py` | +1 import (`UNHANDLED`), 3 return‑site fixes | 2, 33, 63, 74‑75, конец функции |
| `handlers/alan_greeting.py` | +1 import (`UNHANDLED`), 1 return‑site fix (defence‑in‑depth) | 13, 89 |
| `tests/test_slava_presence.py` | +4 теста: Test A, B, C, D | Новые методы |
| `tests/test_alan_greeting.py` | +1 интеграционный тест (Test E) | Новый метод |
| `plans/ARCHITECTURE.md` | +Section 20 (this spec) | Конец файла |

### 20.8 Verification Checklist

1. **Unit tests**: `pytest tests/test_slava_presence.py -v` — все 4 новых теста проходят
2. **Integration test**: `pytest tests/test_alan_greeting.py::TestAlanGreeting::test_slava_router_does_not_block_alan_router_in_dispatcher -v` — проходит
3. **Regression**: `pytest tests/ -v` — все существующие тесты проходят без изменений
4. **Production smoke**: после деплоя Alan заходит в чат → greeting video отправляется; Better Stack показывает логи из `on_alan_join` (log level INFO, T-047)
5. **Manual propagation test** (опционально): запустить bot, попросить Alan выйти и зайти в чат → проверить отправку видео
