# MEMORY.md — AdminBot

> **Версия:** v3.0.0-planning
> **Дата:** 2026-07-16
> **Статус:** Epic 10 PLANNING 🔵 — War Words Redesign (F5v2). 10 задач T-054–T-063. 190 tests pass baseline. ARCHITECTURE.md Section 21 finalized. Knowledge Graph synced.

---

## 🔍 Context Sync Summary (2026-07-16)

| Area | Status | Notes |
|------|--------|-------|
| **Monitoring** | ✅ COMPLETE | Epic 7 finished: Sentry (error tracking) + Logtail (cloud logging) via Better Stack. |
| **Epic 8 (F7)** | ✅ FIXED | F7 Alan Greeting Video now functional — T-053 propagation bug resolved. UNHANDLED sentinel fix. 190 tests pass. |
| **Epic 9 (Bugfixes)** | ✅ COMPLETE | T-046 (Critical) + T-047 (High) — implemented with D16-D21. |
| **Epic 10 (Admin Commands)** | ✅ COMPLETE | `/deadpage` and `/alangreet` — first Command() filter usage. 181 tests passing. |
| **Epic 11 (Bugfix T-052)** | ✅ COMPLETE | Sequential scanning fix for DeadPageRelay. D28-D30 implemented. 185 tests pass. |
| **T-053 (Critical Bugfix)** | ✅ COMPLETED | Propagation-stopping bug FIXED. UNHANDLED in 3 slava_presence handlers + 2 alan_greeting defence-in-depth. 190 tests pass. Reviewer approved. |
| **Epic 10 (War Words Redesign)** | 🔵 PLANNING | F5v2: caption fix (T-057), 90+ keywords, channel repost detection, random reply pool, 8 log events. 10 tasks T-054–T-063. Target ~223 tests. |
| **Routers** | 🔵 8 routers (planned) | war_alert_router at position 4b (NEW). Full order: 0:admin → 1:slava_presence → 1b:alan_greeting → 2:kostik → 3:alan → 4:dead_page → 4b:war_alert → 5:slavik → 6:vasya |
| **MEMORY.md** | ✅ UPDATED | v3.0.0-planning — this file (Epic 10 PLANNING). |
| **ARCHITECTURE.md** | ✅ UPDATED | v3.0.0-planning — Section 21: F5v2 War Words Alert Redesign. D28-D35 in Decision Log. |
| **Knowledge Graph** | ✅ SYNCED | Epic 10, F5v2, war_alert_router, handlers/war_alert.py, T-054–T-063, D28–D35 entities created. F5 deprecated. Relations established. |
| **board.md** | ✅ UPDATED | Epic 10 in Backlog + Architect sections (T-054–T-063). |
| **backlog.md** | ✅ UPDATED | Epic 10: War Words Redesign — 10 tasks fully specified. |

---

## 📋 Project Overview

**AdminBot** — юмористический Telegram-бот для личного чата трёх друзей (Слава, Костик, Вася).  
Написан на **Python** с использованием **aiogram 3.x**. Работает через long-polling.

### Стек
| Компонент | Технология | Статус |
|-----------|-----------|--------|
| Рантайм | Python 3.x + asyncio | ✅ |
| Фреймворк | aiogram 3.7+ | ✅ |
| База данных | SQLite (local_database.db) | ✅ 4 таблицы, WAL mode |
| Конфигурация | .env + config/settings.py | ✅ Все настройки через env |
| Тесты | pytest + pytest-asyncio | ✅ 190 тестов PASS (v2.6.0) |
| Документация | ARCHITECTURE.md, MEMORY.md | ✅ |
| Мониторинг | ✅ Sentry + Logtail | Error tracking + cloud logging via Better Stack |

### Мониторинг и логирование (Epic 7 — COMPLETE ✅)

На **2026-07-12** интеграция Better Stack завершена:

| Аспект | Состояние | Детали |
|--------|-----------|--------|
| **Логирование** | ✅ Dual-output | StreamHandler (консоль) + LogtailHandler (Better Stack cloud) |
| **Error tracking** | ✅ Интегрирован | `sentry-sdk` v2.64.0, инициализация в `bot.py`, traces_sample_rate=1.0 |
| **Sentry** | ✅ Guarded | `sentry_sdk.init(dsn=SENTRY_DSN)` — пропускается если DSN пуст |
| **Logtail/BetterStack** | ✅ Guarded | `LogtailHandler(source_token=LOGTAIL_SOURCE_TOKEN)` — пропускается если токен пуст |

### Пользователи чата

| Персона | User ID | Прозвище | Роутер |
|---------|--------|----------|--------|
| **Слава (Slavik)** | `479167456` | «Куча» | `handlers/slavik.py` |
| **Костик (Kostik)** | `350803143` | — | `handlers/kostik.py` |
| **Вася (Vasya)** | no ID | — | `handlers/vasya.py` |
| **@Alan_Z** | `138811255` | — | `handlers/alan.py` (F6) + `handlers/alan_greeting.py` (F7) |
| **Admin** | `5885953495` | — | `handlers/admin_commands.py` (Epic 10) |

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

### 2. Router Priority Order (КРИТИЧНО — v3.0.0-planned)
Роутеры подключаются в **строгом порядке** в `bot.py`:
```
0.  admin_commands_router (Command filters) — /deadpage, /alangreet (Epic 10 Admin Commands)
1.  ChatMemberUpdated (slava_presence_router) — F1 + new_chat_members fallback
1b. ChatMemberUpdated (alan_greeting_router)   — F7: Alan join → greeting video (D19 lambda filter added)
2.  kostik_router (user_id=350803143)
3.  alan_router (user_id=138811255) + DB counter — F6
4.  dead_page_router — Dead Page V2 trigger from @d_pages forwards
4b. war_alert_router  ← NEW (Epic 10) — F5v2: war keywords (Slava) + channel repost detection (any user)
5.  slavik_router (user_id=479167456) + middleware F3 + F4 + catch-all
6.  vasya_router (text filters, no user restriction)
```
**Причина:** Command routers registered FIRST to intercept /commands before text-based handlers. war_alert_router at 4b: must fire BEFORE slavik catch-all ("пошёл нахуй") but AFTER dead_page (so @d_pages reposts handled first). F5 (WarWordFilter handler) REMOVED from slavik_router — replaced by war_alert_router.

### 3. 8 фич (F1–F7 + Epic 10) — ВСЕ РЕАЛИЗОВАНЫ И ПРОТЕСТИРОВАНЫ

| # | Фича | Реализация | Фильтр/Сервис | Статус |
|---|------|------------|---------------|--------|
| **F1** | Детект возвращения Славы → «ДОЛБОЕБ ВЕРНУЛСЯ» | `handlers/slava_presence.py` | `DatabaseService`, `SchedulerService` | ✅ |
| **F2** | Dead Page V2: forwardMessage из relay-канала @d_pages + fallback на local media + join trigger | `DeadPageRelay` + `DeadPageTrigger` + `SchedulerService` | `dead_page_posts`, `channel_state` tables | ✅ |
| **F3** | GIF каждые 5 сообщений Славы | `MessageCounterMiddleware` | `message_counters` table | ✅ |
| **F4** | «КУЧА» → «ДАЛБАЕБ» | `handlers/slavik.py` | `KuchaWordFilter` | ✅ |
| **F5** | Военные слова → «трясло ебаное» (DEPRECATED) | `handlers/slavik.py` → replaced by `handlers/war_alert.py` | `WarWordFilter` | ❌ DEPRECATED |
| **F5v2** | War Words Alert Redesign — caption fix, 90+ keywords, channel repost detection, random reply pool | `handlers/war_alert.py` (NEW) | `WarWordFilter` (updated), `UserIdFilter` | 🔵 PLANNING |
| **F6** | @Alan_Z → random reply каждые 10 сообщений | `handlers/alan.py` | `UserIdFilter`, `DatabaseService` | ✅ |
| **F7** | Alan join → random greeting video из media/leha_greeting/ | `handlers/alan_greeting.py` | `ChatMemberUpdatedFilter`, `FSInputFile` | ✅ |
| **E10** | Admin test commands: /deadpage, /alangreet | `handlers/admin_commands.py` | `Command()`, `message.delete()`, `ADMIN_USER_ID` | ✅ |

### 4. Database Schema (SQLite, 4 tables)

| Таблица | Назначение | Ключевые колонки |
|---------|-----------|-----------------|
| `user_presence` | Присутствие пользователя (F1, F2) | `user_id`, `chat_id`, `is_present` |
| `message_counters` | Счётчик сообщений (F3, F6) | `chat_id`, `user_id`, `count` |
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
| **Monitoring (v2.1.0)** | `bot.py` (init) | `sentry-sdk` v2.64.0, `logtail-python` v0.4.0 |

### 6. Filters (5 классов)

| Фильтр | Файл | Используется |
|--------|------|-------------|
| `UserIdFilter` | `filters/user_id.py` | kostik, slavik, alan routers |
| `VasyaFilter` | `filters/vasya_name.py` | vasya router |
| `StrictAdminFilter` | `filters/admin_word.py` | vasya router |
| `KuchaWordFilter` | `filters/kucha_word.py` | slavik router (F4) |
| `WarWordFilter` | `filters/war_word.py` | war_alert router (F5v2, was slavik router F5) |

### 7. Config (all env-configurable via settings.py)

| Переменная | По умолчанию | Назначение |
|-----------|-------------|------------|
| `API_TOKEN` | (required) | Telegram Bot Token |
| `DB_PATH` | `local_database.db` | SQLite database path |
| `MEDIA_BASE` | `media` | Media files directory |
| `ADMIN_USER_ID` | `5885953495` | Admin user ID (Epic 10) |
| `SLAVIK_USER_ID` | `479167456` | Slava's Telegram user ID |
| `KOSTIK_USER_ID` | `350803143` | Kostik's Telegram user ID |
| `ALAN_USER_ID` | `138811255` | Alan's Telegram user ID |
| `ALAN_REPLY_INTERVAL` | `10` | Reply every N messages from Alan (F6) |
| `ALAN_USERNAME` | `@Alan_Z` | Caption for F7 greeting video |
| `ALAN_GREETING_DIR` | `media/leha_greeting` | F7 greeting videos directory |
| `ALAN_GREETING_COOLDOWN` | `10` | F7 dedup cooldown seconds |
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
| `SENTRY_DSN` | (optional) | Better Stack Sentry-compatible DSN |
| `LOGTAIL_SOURCE_TOKEN` | (optional) | Better Stack Logtail source token |
| `WAR_CHANNEL_IDS` | `1654872411` | 🔵 Comma-separated channel IDs for war repost detection (F5v2) |
| `WAR_CHANNEL_USERNAMES` | `` | 🔵 Comma-separated channel usernames for war repost detection (F5v2) |
| `WAR_REPLIES` | `` | 🔵 Comma-separated custom reply phrases (F5v2, default: 5 hardcoded) |

---

## 🆕 Recent Changes

### T-053: Propagation Bug Fix — COMPLETED ✅ (2026-07-15)

**Overview:**
Critical bugfix for propagation-stopping behavior in `handlers/slava_presence.py`. Three handlers (`on_user_join`, `on_user_leave`, `on_new_slava_member`) returned bare `return` (None) when the user is not Slava (ID 479167456), which stopped aiogram 3.x event propagation. Fix: return `UNHANDLED` sentinel from `aiogram.dispatcher.event.bases`. **IMPLEMENTED, tested (190 tests pass), reviewed, and approved.**

**Architecture Decisions:**

| ID | Decision | Description | Status |
|----|----------|-------------|--------|
| D22 | Return `UNHANDLED` from slava_presence handlers | Three handlers in `slava_presence.py` return `UNHANDLED` (not None) when user != SLAVIK_USER_ID. Import from `aiogram.dispatcher.event.bases`. +2 defence-in-depth UNHANDLED in `alan_greeting.py`. | ✅ Implemented |
| — | D19 Correction | D19's assumption that "aiogram 3.x calls all matching handlers" was **incorrect**. D22 corrects D19. The lambda-filter in D19 was necessary but **not sufficient** — the real root cause was propagation stopping. | ✅ Corrected |

**Implementation Summary:**

| File | Change | Lines |
|------|--------|-------|
| `handlers/slava_presence.py` | +1 import (`UNHANDLED`), 3 return-site fixes (+ explicit end-of-function return) | +4 changes |
| `handlers/alan_greeting.py` | +1 import (`UNHANDLED`), 2 return-site fixes (defence-in-depth in on_alan_join + on_alan_new_member) | +3 changes |
| `tests/test_slava_presence.py` | +4 unit tests (A: on_user_join UNHANDLED, B: on_user_leave UNHANDLED, C: on_new_slava_member UNHANDLED, D: empty new_chat_members UNHANDLED) | +4 tests |
| `tests/test_alan_greeting.py` | +1 integration test (E: Router.propagate_event verifies Alan greeting fires after fix) | +1 test |

**Behavior Changes (Verified):**
| Scenario | Before | After |
|----------|--------|-------|
| Slava joins | F1: "ДОЛБОЕБ ВЕРНУЛСЯ" | Same ✅ |
| Alan joins | ❌ No greeting (propagation stopped) | ✅ Greeting video sent |
| Any other user joins | None returned, propagation stopped | UNHANDLED returned, propagation continues ✅ |

**Review Findings (all resolved):**
- Reviewer approved all changes. 190 tests pass with zero regressions.

**Knowledge Graph Operations:**
- **Entities updated**: 7 (T-053 → COMPLETED, F7 → FIXED, F1 → updated, D22 → IMPLEMENTED, slava_presence.py → FIXED, alan_greeting.py → FIXED, AdminBot → v2.6.0)
- **Observations deleted**: 19 (old spec/bug observations)
- **Observations added**: 28 (completion/fix verification)
- **Relations deleted**: 1 (blocks_before_T-053_fix)
- **Relations added**: 3 (implements T-053→D22, propagates_to slava_presence→alan_greeting, has_decision AdminBot→D22)

---

### T-052: Sequential Scan for Sparse Channels — COMPLETED ✅ (2026-07-14)

**Overview:**
Bugfix for `DeadPageRelay._try_forward_from_channel`. Root cause: random probing fails on sparse channels where only 1 post exists across 2000 message IDs. The random strategy (`random.randint`) has low probability of hitting the single valid ID. **Fix**: sequential scanning for ranges with <= 50 IDs, guaranteeing post discovery regardless of channel density. **Implemented, tested (185 tests pass), reviewed, and approved.**

**Architecture Decisions (D28-D30):**

| ID | Decision | Description | Status |
|----|----------|-------------|--------|
| D28 | Sequential Threshold 50 | Ranges with <= 50 IDs get sequential scan instead of random probing. Guarantees post discovery. | ✅ Implemented |
| D29 | Sequential Error Handling | Sequential scan reuses same error logic as random: 'not found'/'bad request' → continue; other errors → return False. | ✅ Implemented |
| D30 | Sequential DB Ceiling Update | `update_last_known_message_id` called on sequential success, same as random path. | ✅ Implemented |

**Implementation Summary:**
- Modified `_try_forward_from_channel()` in `services/dead_page_relay.py`: added sequential scan path for ranges where `range_size <= 50`
- Sequential scan iterates from `last_known_id + 1` through `max_known_id`, attempting `forwardMessage` for each ID
- Reuses existing error handling: `MESSAGE_ID_INVALID`, `MESSAGE_NOT_FOUND`, `BAD_REQUEST: message to forward not found` → `continue`; all other errors → return `False`
- On first successful forward: updates `last_known_message_id` via `update_last_known_message_id`, returns the forwarded message
- **4 new tests** added: `test_sequential_scan_small_range`, `test_random_probe_large_range`, `test_sequential_scan_updates_last_id`, `test_sequential_scan_error_handling`
- **185 tests total passing** (was 181), zero regressions

**Review Findings (all resolved):**
- Epic 11 passed reviewer audit. All changes approved. 185 tests pass with zero regressions.

### Epic 10: Admin Test Commands v2.4.0 — COMPLETED ✅ (2026-07-14)

**Overview:**
Two admin-only slash commands for manual testing: `/deadpage` triggers DeadPageRelay immediately, `/alangreet` posts a random greeting video. First-time use of aiogram's `Command()` filter and `message.delete()` in this project. Restricted to `ADMIN_USER_ID=5885953495`. **Implemented, tested (181 tests pass), reviewed, and approved.**

**Tasks:**
| Task | Description | Priority | Status |
|------|-------------|----------|--------|
| T-048 | `/deadpage` — trigger DeadPageRelay immediately | Standard | ✅ COMPLETED |
| T-049 | `/alangreet` — post random Alan greeting video | Standard | ✅ COMPLETED |

**Architecture Decisions (D22-D25):**
| ID | Decision | Description |
|----|----------|-------------|
| D22 | `Command()` filter at position 0 | Admin commands intercepted before text handlers |
| D23 | `ADMIN_USER_ID` guard via inline check | Only admin can execute commands; others silently ignored |
| D24 | `message.delete()` for command cleanup | Keeps chat clean — command messages deleted after 1.5s delay |
| D25 | Constants for magic numbers | `COMMAND_DELETE_DELAY=1.5s`, `GREETING_MISSING_REPLY` — no hardcoded values |

**Implementation Summary:**
- **T-048 (`/deadpage`)**: Invokes `DeadPageRelay.relay_dead_page()` directly. If relay succeeds → `<печенька>`, if failure → error message. Uses `Command("deadpage")` filter with admin guard.
- **T-049 (`/alangreet`)**: Picks random video from `ALAN_GREETING_DIR`, sends via `bot.send_video()` with `FSInputFile` + caption. If no media found → informative reply. Uses `Command("alangreet")` filter with admin guard.
- **Both commands**: Delete the user's command message after 1.5s delay via `asyncio.create_task()`. Silent no-op for non-admin users.
- **New file**: `handlers/admin_commands.py` — stateless, no DB dependency, no setup function.
- **New tests**: `tests/test_admin_commands.py` — 17 tests covering /deadpage (7), /alangreet (7), and edge cases (3: non-admin, unknown command, concurrency).

**Review Findings (all resolved):**
- Epic 10 passed reviewer audit. All changes approved. 181 tests pass with zero regressions.

### Epic 9: Bugfixes v2.3.0 — COMPLETED ✅ (2026-07-14)

**Overview:**
Two critical production bugs fixed. T-046 fixes DeadPageRelay range exhaustion, T-047 fixes Alan greeting detection. 32 tests pass. Decisions D16-D21.

### Epic 8: Alan Greeting Video — IMPLEMENTED ✅ (2026-07-13)

**Overview:**
F7 greets Alan (@Alan_Z, ID 138811255) with a random video when he joins the chat. Dict-based dedup with 10-second cooldown. 164 tests pass. Decisions D13-D15.

### Epic 7: Better Stack Monitoring — COMPLETE ✅ (2026-07-12)

Add observability via Better Stack — error tracking (Sentry) and cloud logging (Logtail). Zero-instrumentation. Guarded — bot runs normally without credentials.

### Dead Page V2 — COMPLETE (2026-07-12)

F2 redesigned from time-based to event-driven architecture. ForwardMessage from private channel `@d_pages`.

---

### Project Structure (actual)

```
C:\Code\Python\adminbot\
├── bot.py                    (entry point, 8 routers, Sentry + Logtail init)
├── requirements.txt          (v2.1.0: +sentry-sdk, +logtail-python)
├── .env.example              (complete: all 25+ settings documented, incl. ADMIN_USER_ID)
├── .env                      (created: SENTRY_DSN, LOGTAIL_SOURCE_TOKEN, API_TOKEN)
├── venv/                     (virtual environment — gitignored)
├── README.md
├── config/
│   └── settings.py           (all settings env-configurable, +ADMIN_USER_ID)
├── handlers/
│   ├── admin_commands.py     (Epic 10: /deadpage, /alangreet — Command filter + admin guard)
│   ├── war_alert.py           🔵 PLANNED (Epic 10 F5v2: war keywords + channel repost detection)
│   ├── kostik.py             (catch-all)
│   ├── slavik.py             (F3 middleware + F4 kucha + catch-all; F5 REMOVED → war_alert.py)
│   ├── vasya.py              (VasyaFilter + StrictAdminFilter)
│   ├── alan.py               (F6: reply engine)
│   ├── alan_greeting.py      (F7: Alan join → random greeting video, D19 lambda filter added)
│   ├── slava_presence.py     (F1: ChatMemberUpdated + new_chat_members fallback)
│   └── dead_page_trigger.py  (F2 V2: @d_pages forward detection + relay trigger)
├── filters/
│   ├── user_id.py
│   ├── vasya_name.py
│   ├── admin_word.py
│   ├── kucha_word.py
│   └── war_word.py
├── services/
│   ├── database.py           (4 tables: +channel_state, +timestamp)
│   ├── media_picker.py
│   ├── scheduler.py          (V2 simplified: join-only)
│   ├── dead_page_relay.py    (forwardMessage + retry + fallback, D16-D18 fixes)
│   └── message_counter.py
├── tests/
│   ├── conftest.py
│   ├── test_filters.py
│   ├── test_kostik.py
│   ├── test_slavik_handlers.py
│   ├── test_vasya.py
│   ├── test_alan.py
│   ├── test_alan_greeting.py  (F7: Alan greeting video tests, D21 integration test)
│   ├── test_slava_presence.py
│   ├── test_database.py
│   ├── test_scheduler.py
│   ├── test_dead_page_relay.py (D16-D18: discovery ranges + dedup tests)
│   ├── test_dead_page_trigger.py
│   ├── test_message_counter.py
│   ├── test_media_picker.py
│   ├── test_admin_commands.py  (Epic 10: 17 tests for /deadpage + /alangreet)
│   ├── test_war_alert.py        🔵 PLANNED (Epic 10 F5v2: 15 tests for war alert handlers)
│   ├── test_edge_cases.py
│   └── test_monitoring_smoke.py
├── media/
│   ├── slavic_chlen.mp4
│   ├── leha_greeting/         (F7)
│   │   ├── leha_greeting_01.MP4
│   │   └── leha_greeting_02.MP4
│   └── dead_page/
│       ├── page_1.txt
│       └── slavic_ava.jpg
└── plans/
    ├── ARCHITECTURE.md       (v3.0.0-planned with Section 21: F5v2 War Words Alert Redesign + D28-D35)
    ├── MEMORY.md             (v3.0.0-planning — this file)
    ├── board.md
    └── backlog.md
```

### Epic 10: War Words Redesign (F5v2) — PLANNING 🔵 (2026-07-16)

**Overview:**
Full redesign of F5 War Words feature. Fixes caption bug (T-057: only `message.text` checked, `message.caption` silently ignored), expands keyword dictionary from 27 to 90+ forms, adds channel repost detection from military Telegram channels, replaces single hardcoded "трясло ебаное" with random reply pool, and adds 8 distinct Better Stack log events.

**Architecture Decisions (D28-D35):**

| ID | Decision | Description | Status |
|----|----------|-------------|--------|
| D28 | Separate `war_alert_router` | New router at position 4b instead of extending slavik_router. Follows dead_page_trigger.py pattern. | 🔵 Planned |
| D29 | Two handlers on same router | Handler A: Slava + keywords. Handler B: any user + channel forward. Both share WAR_REPLIES pool. | 🔵 Planned |
| D30 | Check `message.text or message.caption` | Fixes T-057: caption-only keywords were silently ignored. Uses `or` idiom (telegram sends text OR caption, never both). | 🔵 Planned |
| D31 | Reply pool in handler, not filter | Filter is pure boolean. Reply logic belongs in handler. Follows alan.py pattern. | 🔵 Planned |
| D32 | Dual channel check (ID + username) | More resilient: ID survives username changes, username covers privacy-restricted IDs. Follows dead_page_trigger.py. | 🔵 Planned |
| D33 | Configurable via .env | Keywords/replies/channels extensible without code changes. Comma-separated env vars, sensible defaults. | 🔵 Planned |
| D34 | Random reply via `random.choice()` | Replaces single "трясло ебаное". 5 default phrases. Extensible pool. Pattern from alan.py. | 🔵 Planned |
| D35 | Position 4b (dead_page → war_alert → slavik) | Before slavik catch-all so keywords fire first. After dead_page so @d_pages handled first. | 🔵 Planned |

**Tasks:**
| Task | Description | Priority | Status |
|------|-------------|----------|--------|
| T-054 | Fix WarWordFilter — caption support + 90+ keywords | Critical | 🔵 PLANNING |
| T-055 | Channel repost detection handler (Handler B) | High | 🔵 PLANNING |
| T-056 | Random reply pool + `random.choice()` | Standard | 🔵 PLANNING |
| T-057 | Better Stack logging — 8 log events | Standard | 🔵 PLANNING |
| T-058 | Tests — ~33 new tests (filter + handler + edge) | Standard | 🔵 PLANNING |
| T-059 | Config: WAR_CHANNEL_IDS, WAR_CHANNEL_USERNAMES, WAR_REPLIES | Standard | 🔵 PLANNING |
| T-060 | Register `war_alert_router` in bot.py at position 4b | Standard | 🔵 PLANNING |
| T-061 | Update README — F5 v2 documentation | Low | 🔵 PLANNING |
| T-062 | Run full pytest suite — verify ~223 tests pass | Standard | 🔵 PLANNING |
| T-063 | Deploy to server | Standard | 🔵 PLANNING |

**Key Files:**
| File | Action | Description |
|------|--------|-------------|
| `filters/war_word.py` | MODIFY | Caption support (`text or caption`), 90+ keywords in 11 families |
| `handlers/war_alert.py` | CREATE | New router with 2 handlers + reply pool + setup + logging |
| `handlers/slavik.py` | MODIFY | Remove F5 (WarWordFilter handler + import). Keep F4 + catch-all |
| `config/settings.py` | MODIFY | +3 fields (WAR_CHANNEL_IDS, WAR_CHANNEL_USERNAMES, WAR_REPLIES), +2 helpers |
| `bot.py` | MODIFY | +1 import, +1 setup_war_alert(), +1 dp.include_router (pos 4b) |
| `.env.example` | MODIFY | +3 entries for war alert config |
| `tests/test_filters.py` | MODIFY | +13 WarWordFilter tests (caption, new keywords) |
| `tests/test_war_alert.py` | CREATE | +15 handler tests (both handlers, logging, config) |
| `tests/test_edge_cases.py` | MODIFY | +5 edge case tests (router order, regression) |

**Keyword Expansion (27 → 90+):**
- `лететь` family: летит, летает, прилетел, прилетает, летят, летел, летела, летели, летящий, летящие (10)
- `дрон/БПЛА` family: дрон, дроны, дронов, беспилотник, беспилотники, беспилотной, беспилотная, беспилотное, беспилотные, беспилотного, беспилотных, беспилотному, бпла (13)
- `вспышка` family: вспышка, вспышки, вспышке, вспышкой, вспышек (5)
- `прилет` family: прилет, прилёт, прилетел, прилетит, прилетела, прилетят (6)
- `укрытие` family: укрытие, укрытия, укрытии, укрытий, укрыться (5)
- `убежище` family: убежище, убежища, убежищу, убежищем, убежищ (5)
- `бункер` family: бункер, бункера, бункере, бункером, бункеров (5)
- `ракета` family: ракета, ракеты, ракет, ракете, ракетой, ракетная, ракетной, ракетные, ракетных, ракетное, ракетную, ракетного (12)
- `опасность` family: опасность, опасности, опасностью, опасностей, опасно (5)
- `внимание/оповещение`: внимание, внимания, оповещение, оповещения, оповещению, оповещением (6)
- `тревога` family: тревога, тревоги, тревогу, тревогой (4)

**Reply Pool (WAR_REPLIES):**
1. "потрясись"
2. "повизжи"
3. "прячься под шконку быстрее"
4. "закрой ушки и считай до десяти"
5. "поплачь"

**Better Stack Log Events (8):**
| Event | Level | Context |
|-------|-------|---------|
| Module initialization | INFO | reply count, channel IDs, usernames |
| Keyword match (Handler A) | INFO | user_id, chat_id, msg_id, text (first 100 chars) |
| Reply sent (keyword) | INFO | reply text, msg_id, chat_id |
| Forward not a channel | DEBUG | origin type |
| Channel repost detected (Handler B) | INFO | channel_id, username, chat_id, user_id |
| Reply sent (repost) | INFO | reply text, msg_id, chat_id |
| Reply send failure (any) | ERROR | reply text, msg_id, exception |
| Pattern compile warning | WARNING | word, error |

### Sprint Status (board.md)

| Status | Tasks |
|--------|-------|
| **Done** | T-001 – T-053 (all 53 tasks) ✅ |
| **Planned** | T-054 – T-063 (Epic 10: War Words Redesign) 🔵 |
| **In Progress** | — |

> Epics 1–12 complete (53 tasks). Epic 10 (F5v2) PLANNING — 10 tasks ready. 190 tests pass baseline. Target: ~223 tests after implementation.

---

## 🔗 Knowledge Graph Status

- **Fully synchronized** with current project state (v3.0.0-planning — Epic 10 PLANNING)
- **Epic 10 (War Words Redesign)**: 🔵 PLANNING. 10 tasks (T-054–T-063). 8 new architecture decisions (D28–D35). Relations: `contains` (10 tasks), `redesigns` (F5), `creates` (handlers/war_alert.py), `implements` (F5v2), `modifies` (WarWordFilter, handlers/slavik.py, config/settings.py, bot.py), `has_decision` (D28–D35).
- **F5v2 (War Words Alert Redesign)**: 🔵 PLANNING. Replaces deprecated F5. Two detection mechanisms: keyword (Slava) + channel repost (any user). Relations: `replaces` (F5), `uses` (war_alert_router), `implemented_in` (handlers/war_alert.py), `has_decision` (D28–D35).
- **war_alert_router**: 🔵 PLANNING. New router at position 4b. 2 handlers + WAR_REPLIES pool. Relations: `uses_filter` (WarWordFilter, UserIdFilter), `part_of` (Router Architecture), `registered_before` (slavik_router).
- **handlers/war_alert.py**: 🔵 PLANNING. New file. Relations: `defines` (war_alert_router), `part_of` (AdminBot).
- **WarWordFilter**: 🔵 PLANNED update. Caption support (fixes T-057), 90+ keywords in 11 families. Relations: `defines` (filters/war_word.py), `fixes` (T-054).
- **F5: Drone/War Word Reply**: ❌ DEPRECATED. Replaced by F5v2. Old handler removed from slavik.py. Relations: `redesigns` (Epic 10), `replaces` (F5v2).
- **handlers/slavik.py**: 🔵 PLANNED modification. F5 handler + WarWordFilter import removed. Now: F4 + catch-all + middleware. Relations: `uses_filter` → WarWordFilter DELETED.
- **AdminBot entity**: 🔵 v3.0.0 planned. Relations: `planned_epic` (Epic 10), `planned_feature` (F5v2), `has_router` (war_alert_router).
- **Bot.py**: 🔵 PLANNED modification. +1 import, +1 setup_war_alert(), +1 dp.include_router (pos 4b). 8 routers total.
- **config/settings.py**: 🔵 PLANNED modification. +3 fields (WAR_CHANNEL_IDS, WAR_CHANNEL_USERNAMES, WAR_REPLIES), +2 helpers.
- **AdminBot Router Architecture**: 🔵 v3.0.0-planned. 8 routers. Position 4b: war_alert_router. F5 removed from slavik_router.
- **All previous Epics (1-12)**: 53 tasks (T-001 – T-053) implemented. 190 tests pass. Production-ready.

---

## 📊 Workflow Completion Log — 2026-07-16

### Memory Agent — Epic 10 Context Sync

| Stage | Agent | Status | Details |
|-------|-------|--------|---------|
| **Step 0** | Memory | ✅ | Context sync — prepared AdminBot v2.6.0 context. Pulled ARCHITECTURE.md Section 21, board.md, backlog.md. |
| **Step 1** | PM | ⏳ | backlog.md and board.md updated with Epic 10 tasks (T-054–T-063) — ALREADY DONE in board/backlog |
| **Step 3** | Memory | ✅ | **THIS STEP** — Knowledge graph synced + MEMORY.md updated to v3.0.0-planning |

### Operations Summary — v3.0.0 Planning (Epic 10 Context Sync)

| Operation | Count | Status |
|-----------|-------|--------|
| **Entities created** | 24 | Epic 10, F5v2, handlers/war_alert.py, war_alert_router, T-054–T-063 (10 tasks), D28–D35 (8 decisions) |
| **Entities updated** | 7 | AdminBot, F5 (DEPRECATED), WarWordFilter, handlers/slavik.py, config/settings.py, bot.py, Router Architecture |
| **New relations created** | 67 | contains(10), redesigns, creates, implements, modifies(4), replaces, uses, implemented_in, defines, part_of(2), uses_filter(2), registered_before, has_router, planned_epic, planned_feature, registers, fixes, tests, verifies, deploys, has_decision(16) |
| **Relations deleted** | 1 | handlers/slavik.py → WarWordFilter (uses_filter) — F5 removed from slavik |
| **MEMORY.md updated** | ✅ | v3.0.0-planning — Epic 10 PLANNING (T-054–T-063), F5 deprecated, F5v2 planned |
| **ARCHITECTURE.md** | ✅ | v3.0.0-planning — Section 21: F5v2 War Words Alert Redesign with D28-D35 |

---

## ✅ T-053 COMPLETION STAMP — 2026-07-15

> **T-053 Propagation Bug Fix — Implementation Complete ✅**
> Критический баг в `handlers/slava_presence.py` исправлен: все три хендлера (`on_user_join`, `on_user_leave`, `on_new_slava_member`)
> теперь возвращают `UNHANDLED` вместо `None` для пользователей, не являющихся Славой.
> `alan_greeting_router` (position 1b) теперь получает join-события — **F7 Alan Greeting функционирует в production.**
> **Defence-in-depth**: `on_alan_join` и `on_alan_new_member` в `alan_greeting.py` также возвращают `UNHANDLED`.
> **190 тестов** проходят (185 baseline + 5 новых: A/B/C/D unit + E integration).
> Reviewer утвердил. Багов не осталось.
>
> **📊 Final Knowledge Graph Operations:**
> - **Entities updated**: 7 (T-053, F7, F1, D22, slava_presence.py, alan_greeting.py, AdminBot)
> - **Observations deleted**: 19 (old spec/bug observations)
> - **Observations added**: 28 (completion/fix verification)
> - **Relations deleted**: 1 (blocks_before_T-053_fix → replaced by propagates_to)
> - **Relations added**: 3 (implements, propagates_to, has_decision)
> - **MEMORY.md**: v2.6.0
> - **ARCHITECTURE.md**: v2.6.0 (Section 20 implementation verified)

---

## 🚀 T-053 DEPLOYED — 2026-07-15

> **Commit:** `165691c`
> **Ветка:** `main` (pushed to `origin/master`)
> **Статус:** ✅ DEPLOYED ✅ — все изменения отправлены в production-репозиторий.
>
> **Состав коммита:**
> | Файл | Изменения |
> |------|----------|
> | `handlers/slava_presence.py` | +import UNHANDLED, 3 return-site fixes (on_user_join, on_user_leave, on_new_slava_member) |
> | `handlers/alan_greeting.py` | +import UNHANDLED, 2 defence-in-depth fixes (on_alan_join, on_alan_new_member) |
> | `tests/test_slava_presence.py` | +4 unit tests (A/B/C/D — UNHANDLED return verification) |
> | `tests/test_alan_greeting.py` | +1 integration test (E — Router.propagate_event verification) |
> | `plans/MEMORY.md` | v2.6.0 — T-053 COMPLETED |
> | `plans/ARCHITECTURE.md` | v2.6.0 — D22 implementation verified |
> | `plans/board.md` | T-053 moved to Done |
> | `plans/backlog.md` | T-053 in Bugfixes section |
>
> **Production Impact:**
> - 🔴 **Было:** F7 (Alan greeting video) сломан — видео НЕ отправлялось при заходе Алана.
> - 🟢 **Стало:** F7 функционирует в production. При заходе Алана → случайное greeting-видео.
> - 🟢 **Zero regressions:** все 190 тестов проходят (185 baseline + 5 новых T-053).
> - 🟢 **Zero known bugs:** все 53 задачи (T-001 – T-053) завершены.
>
> **Knowledge Graph Status:**
> - `AdminBot v2.6.0` Version entity created ✅
> - `commit 165691c` Commit entity created ✅
> - Relations: `is_version_of` (v2.6.0 → AdminBot), `committed_as` (v2.6.0 → 165691c), `contains_task` (165691c → T-053) ✅
> - `AdminBot` entity updated with deployment observation ✅
> - Zero stale/broken entities. Zero stale relations. Graph consistent. ✅

---

*Последнее обновление: 2026-07-16 — Epic 10 (War Words Redesign F5v2) PLANNING. 10 задач (T-054–T-063). 24 новых entity, 67 новых relations, 1 удалённый relation. Knowledge Graph полностью синхронизирован.*
