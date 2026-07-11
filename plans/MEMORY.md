# MEMORY.md — AdminBot

> **Версия:** v2.0.0 (Dead Page V2)
> **Дата:** 2026-07-12
> **Статус:** PRODUCTION-READY — Dead Page V2 implemented, 137 tests pass, 6 routers active

---

## 📋 Project Overview

**AdminBot** — юмористический Telegram-бот для личного чата трёх друзей (Слава, Костик, Вася).  
Написан на **Python** с использованием **aiogram 3.x**. Работает через long-polling.

### Стек
| Компонент | Технология | Статус |
|-----------|-----------|--------|
| Рантайм | Python 3.x + asyncio | ✅ |
| Фреймворк | aiogram 3.x | ✅ |
| База данных | SQLite (local_database.db) | ✅ 4 таблицы, WAL mode |
| Конфигурация | .env + config/settings.py | ✅ Все настройки через env |
| Тесты | pytest + pytest-asyncio | ✅ 137 тестов PASS |
| Документация | ARCHITECTURE.md, MEMORY.md | ✅ |

### Пользователи чата

| Персона | User ID | Прозвище | Роутер |
|---------|--------|----------|--------|
| **Слава (Slavik)** | `479167456` | «Куча» | `handlers/slavik.py` |
| **Костик (Kostik)** | `350803143` | — | `handlers/kostik.py` |
| **Вася (Vasya)** | no ID | — | `handlers/vasya.py` |
| **@Alan_Z** | `138811255` | — | `handlers/alan.py` |

---

## 🏗️ Key Architectural Decisions

### 1. Модульная архитектура (v2.0.0)
Проект разбит на 6 директорий с чёткими import rules:
```
config/    → handlers/ ← filters/    → services/ → tests/
```
- `handlers/` NEVER import from other `handlers/` modules
- `filters/` NEVER import from `handlers/` or `services/`
- `services/` can import from `config/` and other `services/`
- `bot.py` is the ONLY module that wires routers together

### 2. Router Priority Order (КРИТИЧНО)
Роутеры подключаются в **строгом порядке** в `bot.py`:
```
1. ChatMemberUpdated (slava_presence_router) — F1 + new_chat_members fallback
2. kostik_router (user_id=350803143)
3. alan_router (user_id=138811255) + DB counter — F6
4. dead_page_router — Dead Page V2 trigger from @d_pages forwards
5. slavik_router (user_id=479167456) + middleware F3 + F4 + F5 + catch-all
6. vasya_router (text filters, no user restriction)
```
**Причина:** User-ID-based routers BEFORE text-based routers. ChatMemberUpdated separate from Message handlers. Dead Page trigger after Alan, before Slava-specific handlers.

### 3. 6 фич (F1–F6) — ВСЕ РЕАЛИЗОВАНЫ И ПРОТЕСТИРОВАНЫ

| # | Фича | Реализация | Фильтр/Сервис |
|---|------|------------|---------------|
| **F1** | Детект возвращения Славы → «ДОЛБОЕБ ВЕРНУЛСЯ» | `handlers/slava_presence.py` | `DatabaseService`, `SchedulerService` |
| **F2** | Dead Page V2: forwardMessage из relay-канала @d_pages + fallback на local media + join trigger | `DeadPageRelay` + `DeadPageTrigger` + `SchedulerService` | `dead_page_posts`, `channel_state` tables |
| **F3** | GIF каждые 5 сообщений Славы | `MessageCounterMiddleware` | `message_counters` table |
| **F4** | «КУЧА» → «ДАЛБАЕБ» | `handlers/slavik.py` | `KuchaWordFilter` |
| **F5** | Военные слова → «трясло ебаное» | `handlers/slavik.py` | `WarWordFilter` |
| **F6** | @Alan_Z → random reply каждые 10 сообщений (тренировки/лонгковид/фьючерсы/нейросети/жим дьявола) | `handlers/alan.py` | `UserIdFilter`, `DatabaseService` |

### 4. Database Schema (SQLite, 4 tables)

| Таблица | Назначение | Ключевые колонки |
|---------|-----------|-----------------|
| `user_presence` | Присутствие пользователя (F1, F2) | `user_id`, `chat_id`, `is_present` |
| `message_counters` | Счётчик сообщений (F3) | `chat_id`, `user_id`, `count` |
| `dead_page_posts` | Учёт dead-page постов (F2 V2) | `chat_id`, `slot` (repost/join), `timestamp` |
| `channel_state` | Ключ-значение для отслеживания (F2 V2) | `key` (TEXT PK), `value` (TEXT) |

### 5. Services

| Сервис | Файл | Зависимости |
|--------|------|------------|
| `DatabaseService` | `services/database.py` | aiosqlite, asyncio.Lock |
| `MediaService` | `services/media_picker.py` | random, glob, Path (stateless) |
| `SchedulerService` | `services/scheduler.py` | DatabaseService, DeadPageRelay, asyncio |
| `DeadPageRelay` | `services/dead_page_relay.py` | DatabaseService, MediaService, aiogram Bot |
| `MessageCounterMiddleware` | `services/message_counter.py` | DatabaseService (aiogram middleware) |

### 6. Filters (5 классов)

| Фильтр | Файл | Используется |
|--------|------|-------------|
| `UserIdFilter` | `filters/user_id.py` | kostik, slavik, alan routers |
| `VasyaFilter` | `filters/vasya_name.py` | vasya router |
| `StrictAdminFilter` | `filters/admin_word.py` | vasya router |
| `KuchaWordFilter` | `filters/kucha_word.py` | slavik router (F4) |
| `WarWordFilter` | `filters/war_word.py` | slavik router (F5) |

### 7. Config (all env-configurable via settings.py)

| Переменная | По умолчанию | Назначение |
|-----------|-------------|------------|
| `API_TOKEN` | (required) | Telegram Bot Token |
| `DB_PATH` | `local_database.db` | SQLite database path |
| `MEDIA_BASE` | `media` | Media files directory |
| `SLAVIK_USER_ID` | `479167456` | Slava's Telegram user ID |
| `KOSTIK_USER_ID` | `350803143` | Kostik's Telegram user ID |
| `ALAN_USER_ID` | `138811255` | Alan's Telegram user ID |
| `ALAN_REPLY_INTERVAL` | `10` | Reply every N messages from Alan |
| `KOSTIK_REPLY_PROBABILITY` | `1.0` | Probability of Kostik reply (0.0–1.0) |
| `GIF_INTERVAL` | `5` | Send GIF every N messages |
| `GIF_PATH` | `media/slavic_chlen.mp4` | GIF file path |
| `DEAD_PAGE_DIR` | `media/dead_page` | Dead page local media directory |
| `DEAD_PAGE_CHANNEL_ID` | `4228645624` | Relay channel ID for forwardMessage |
| `DEAD_PAGE_CHANNEL_USERNAME` | `@d_pages` | Channel username for trigger detection |
| `DEAD_PAGE_FORWARD_COOLDOWN` | `600` | Anti-spam cooldown (seconds) |
| `DEAD_PAGE_POST_ON_JOIN` | `True` | Enable dead page on Slava join |
| `DEAD_PAGE_REPOST_COOLDOWN` | `600` | Repost cooldown (seconds) |
| `DEAD_PAGE_RETRY_MAX` | `5` | Max retries for forwardMessage |
| `DEAD_PAGE_JOIN_DEDUP` | `10` | Dedup window for join events (seconds) |

---

## 🆕 Recent Changes

### Dead Page V2 — Complete (2026-07-12)

**Overview:**
F2 redesigned from time-based scheduler (morning/evening) to event-driven architecture. Dead page posts now come from a private Telegram channel `@d_pages` via `forwardMessage`, with local media fallback.

**New Files:**
| File | Purpose |
|------|---------|
| `services/dead_page_relay.py` | Forwards random post from relay channel (ID 4228645624) to target chat. Retry logic (max 5), fallback to local MediaService, anti-spam cooldown. |
| `handlers/dead_page_trigger.py` | Detects `MessageOriginChannel` forwards from `@d_pages`. Checks Slava presence + cooldown before posting. Registered as `dead_page_router` at position 4. |
| `tests/test_dead_page_relay.py` | 4 tests: success, fallback, cooldown, retry exhaustion |
| `tests/test_dead_page_trigger.py` | 4 tests: origin detection, presence gate, cooldown gate, valid forward |

**Modified Files:**
| File | Changes |
|------|---------|
| `config/settings.py` | 7 new `DEAD_PAGE_*` env vars. Removed: `MORNING_HOUR`, `EVENING_HOUR`, `POLL_INTERVAL`. Added: `DEAD_PAGE_CHANNEL_ID`, `DEAD_PAGE_CHANNEL_USERNAME`, `DEAD_PAGE_FORWARD_COOLDOWN`, `DEAD_PAGE_POST_ON_JOIN`, `DEAD_PAGE_REPOST_COOLDOWN`, `DEAD_PAGE_RETRY_MAX`, `DEAD_PAGE_JOIN_DEDUP`. |
| `services/scheduler.py` | V2 simplified: time-based morning/evening removed. Only handles `signal_immediate_post()` for join trigger. `run()` is no-op loop (sleeps 3600s). Delegates to `DeadPageRelay`. |
| `services/database.py` | New `channel_state` table (key-value). New methods: `was_dead_page_recently()`, `record_dead_page_post()`, `get_last_known_message_id()`, `update_last_known_message_id()`. Migration: `ALTER TABLE dead_page_posts ADD COLUMN timestamp`. |
| `bot.py` | `dead_page_router` registered at position 4. `DeadPageRelay` + `DeadPageTrigger` initialized via `setup_dead_page()`. |
| `tests/test_database.py` | Updated: `channel_state` tests, `was_dead_page_recently`, `record_dead_page_post` |
| `tests/test_scheduler.py` | Rewritten: 5 V2 tests (join post, dedup window, post_on_join=False gate, relay delegation, no-op loop) |

**Test Results:**
- **137 tests pass** (no regressions from existing features)
- 13 new tests: test_scheduler.py (5), test_dead_page_relay.py (4), test_dead_page_trigger.py (4)
- All existing Slava handlers (F3/F4/F5), Alan (F6), Kostik, Vasya tests unchanged and passing
- Fixed 1 test issue: frozen dataclass patching → post_on_join constructor parameter

**Reviewer Audit:**
- 5 critical + 11 warning issues identified and all resolved
- Critical fixes: retry dedup set, forward_id extraction, DEAD_PAGE_REPOST_COOLDOWN config, handler cooldown check, scheduler delegation

**Architecture Decision — Why trigger-based instead of time-based:**
- Time-based (morning/evening) required bot to be running at specific times
- Event-driven from Telegram forwards is more reliable and user-controlled
- Relay channel approach enables posting from any device without bot commands
- Local media fallback ensures posts continue if channel is inaccessible

### Phase 1 — Initial Implementation (2026-07-07)
- All 6 features (F1-F6) implemented from scratch in modular architecture
- 5 routers, 4 services, 6 filters, 3 DB tables created
- 109 tests pass (up from 0 before implementation)
- 12 test files covering all handlers, filters, services, edge cases

### Post-Review Fixes (2026-07-07)

| ID | Fix | Files Affected |
|----|-----|---------------|
| **B1** | KuchaWordFilter regex tightened from `[а-яё]*` to precise declension matching | `filters/kucha_word.py` |
| **H1+H2** | Legacy modules deleted (`kostik_module.py`, `slavik_module.py`, `vasya_module.py`); filter-level tests added for `VasyaFilter` and `StrictAdminFilter` | Root + `tests/test_filters.py` |
| **M1** | `new_chat_members` fallback handler added for F1 (redundant detection) | `handlers/slava_presence.py` |
| **M4** | DB fixture reverted to manual event loop (no async fixture issues) | `tests/conftest.py` |
| **M5** | All settings now configurable via environment variables | `config/settings.py` |
| **L3** | `on_shutdown` hook added to bot.py (DB cleanup deferred) | `bot.py` |

### Alan_Z Refactor (2026-07-07)
- Onupon (id 1060441536) replaced with Alan_Z (id 138811255) in F6
- F6 refactored: periodic reply engine (every 10 msgs → random phrase from pool of 20+)
- `handlers/onupon.py` DELETED, `handlers/alan.py` CREATED
- `filters/username.py` DELETED (dead code)
- 115 tests pass after refactor

### Kostik Handler Refactor (2026-07-07)
- Probability-based replies: `KOSTIK_REPLY_PROBABILITY` (default 1.0)
- Extensible `KOSTIK_REPLIES` pool (8 variants)
- KuchaWordFilter fix: removed 'ек' from suffix group → no more false positive on 'кучек'
- 130 tests pass after refactor

---

### Project Structure (actual)

```
C:\Code\Python\adminbot\
├── bot.py                    (entry point, 6 routers, on_startup/on_shutdown)
├── requirements.txt
├── .env.example              (complete: all 19+ settings documented)
├── README.md
├── config/
│   └── settings.py           (all settings env-configurable, 7 DEAD_PAGE_* vars)
├── handlers/
│   ├── kostik.py             (catch-all "пошёл нахуй кринжатура ебаная")
│   ├── slavik.py             (F3 middleware + F4 kucha + F5 war + catch-all)
│   ├── vasya.py              (VasyaFilter + StrictAdminFilter)
│   ├── alan.py               (F6: reply engine — random phrase every 10 msgs)
│   ├── slava_presence.py     (F1: ChatMemberUpdated + new_chat_members fallback)
│   └── dead_page_trigger.py  (F2 V2: @d_pages forward detection + relay trigger)
├── filters/
│   ├── user_id.py
│   ├── vasya_name.py
│   ├── admin_word.py
│   ├── kucha_word.py         (B1 fix: precise declension regex)
│   └── war_word.py
├── services/
│   ├── database.py           (4 tables: +channel_state, +timestamp, anti-spam methods)
│   ├── media_picker.py
│   ├── scheduler.py          (V2 simplified: join-only, delegates to DeadPageRelay)
│   ├── dead_page_relay.py    (NEW: forwardMessage + retry + fallback)
│   └── message_counter.py
├── tests/
│   ├── conftest.py           (M4 fix: manual event_loop, session scope)
│   ├── test_filters.py
│   ├── test_kostik.py
│   ├── test_slavik_handlers.py
│   ├── test_vasya.py
│   ├── test_alan.py
│   ├── test_slava_presence.py
│   ├── test_database.py      (updated: channel_state + dead_page V2 methods)
│   ├── test_scheduler.py     (rewritten: 5 V2 tests)
│   ├── test_dead_page_relay.py     (NEW: 4 tests)
│   ├── test_dead_page_trigger.py   (NEW: 4 tests)
│   ├── test_message_counter.py
│   ├── test_media_picker.py
│   └── test_edge_cases.py
├── media/
│   ├── slavic_chlen.mp4
│   └── dead_page/
│       ├── page_1.txt
│       └── slavic_ava.jpg
└── plans/
    ├── ARCHITECTURE.md
    ├── MEMORY.md
    ├── board.md
    └── backlog.md
```

### Sprint Status (board.md) — FINAL

| Status | Tasks |
|--------|-------|
| **Backlog** | none |
| **In Progress** | none |
| **Done** | **T-001 – T-028 (all 28 tasks)** ✅ |

> ✅ Board.md and backlog.md synced. Epic 1–6 fully complete.

### Legacy Migration — COMPLETE
- `vasya_module.py` → **DELETED** → `handlers/vasya.py` + `filters/vasya_name.py` + `filters/admin_word.py`
- `kostik_module.py` → **DELETED** → `handlers/kostik.py` + `filters/user_id.py`
- `slavik_module.py` → **DELETED** → `handlers/slavik.py` + `filters/user_id.py` + `services/message_counter.py`
- `handlers/onupon.py` → **DELETED** → `handlers/alan.py`
- `filters/username.py` → **DELETED** (dead code)

### Remaining Technical Debt (LOW — Not Blocking)

| ID | Description | Rationale |
|----|------------|----------|
| **H3** | No dispatcher integration tests | Unit tests cover all components; integration deferred |
| **L1** | README uses platform-specific Windows commands | Acceptable for Windows-first project |
| **L2** | Quoting not implemented in response text | Telegram `message.reply()` covers the need |
| **L4** | MediaService cache never invalidates | Acceptable for small media directory |
| **L5** | VasyaFilter translit order edge case | Latin-first order may miss mixed inputs |

---

## 🔗 Knowledge Graph Status

- **Fully synchronized** with final project state (v2.0.0)
- **Final entities**: 1 Project, 3 Architecture, 2 Milestones, 1 Test Strategy, 6 Features (F1-F6), 4 Users, 6 Handlers, 5 Services, 5 Filters, 4 DB tables, 1 Pending (5 LOW items)
- **Epic 6 (Dead Page V2)**: T-018 – T-028 all complete. 137 tests passing, 5 critical + 11 warning reviewer findings resolved.
- **Key new components**: DeadPageRelay (forwardMessage + retry + fallback), DeadPageTrigger (@d_pages forward detection), channel_state table

---

*Последнее обновление: 2026-07-12 — Dead Page V2 Final Sync (Memory Agent)*
