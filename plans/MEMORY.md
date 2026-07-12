# MEMORY.md — AdminBot

> **Версия:** v2.2.0
> **Дата:** 2026-07-13
> **Статус:** ALL 8 Epics Complete — F7 (Alan Greeting Video) implemented, reviewed, and approved. 7 routers, 164 tests pass, production-ready.

---

## 🔍 Context Sync Summary (2026-07-13)

| Area | Status | Notes |
|------|--------|-------|
| **Monitoring** | ✅ COMPLETE | Epic 7 finished: Sentry (error tracking) + Logtail (cloud logging) via Better Stack. |
| **Epic 8 (F7)** | ✅ COMPLETE | F7 implemented, tested, reviewed. 164 tests pass. 3 review fixes applied (B1, M1, M2). |
| **Routers** | ✅ 7 routers | Added alan_greeting_router at position 1b for F7. |
| **MEMORY.md** | ✅ ACCURATE | v2.2.0 — this file. |
| **ARCHITECTURE.md** | ✅ ACCURATE | v2.2.0 with §11.6 Alan Greeting Video + design decisions D13-D15. |
| **board.md** | ⚠️ STALE | Known issue — does not reflect Epic 8 yet. |
| **backlog.md** | ⚠️ STALE | Same as board.md. Code + ARCHITECTURE.md are authoritative. |

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
| Тесты | pytest + pytest-asyncio | ✅ 164 тестов PASS |
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

### 2. Router Priority Order (КРИТИЧНО — v2.2.0)
Роутеры подключаются в **строгом порядке** в `bot.py`:
```
1.  ChatMemberUpdated (slava_presence_router) — F1 + new_chat_members fallback
1b. ChatMemberUpdated (alan_greeting_router)   — F7: Alan join → greeting video
2.  kostik_router (user_id=350803143)
3.  alan_router (user_id=138811255) + DB counter — F6
4.  dead_page_router — Dead Page V2 trigger from @d_pages forwards
5.  slavik_router (user_id=479167456) + middleware F3 + F4 + F5 + catch-all
6.  vasya_router (text filters, no user restriction)
```
**Причина:** User-ID-based routers BEFORE text-based routers. ChatMemberUpdated separate from Message handlers. F1 and F7 both handle chat_member updates but check different user IDs (Slava=479167456 vs Alan=138811255) — no conflict.

### 3. 7 фич (F1–F7) — ВСЕ РЕАЛИЗОВАНЫ И ПРОТЕСТИРОВАНЫ

| # | Фича | Реализация | Фильтр/Сервис | Статус |
|---|------|------------|---------------|--------|
| **F1** | Детект возвращения Славы → «ДОЛБОЕБ ВЕРНУЛСЯ» | `handlers/slava_presence.py` | `DatabaseService`, `SchedulerService` | ✅ |
| **F2** | Dead Page V2: forwardMessage из relay-канала @d_pages + fallback на local media + join trigger | `DeadPageRelay` + `DeadPageTrigger` + `SchedulerService` | `dead_page_posts`, `channel_state` tables | ✅ |
| **F3** | GIF каждые 5 сообщений Славы | `MessageCounterMiddleware` | `message_counters` table | ✅ |
| **F4** | «КУЧА» → «ДАЛБАЕБ» | `handlers/slavik.py` | `KuchaWordFilter` | ✅ |
| **F5** | Военные слова → «трясло ебаное» | `handlers/slavik.py` | `WarWordFilter` | ✅ |
| **F6** | @Alan_Z → random reply каждые 10 сообщений | `handlers/alan.py` | `UserIdFilter`, `DatabaseService` | ✅ |
| **F7** | Alan join → random greeting video из media/leha_greeting/ | `handlers/alan_greeting.py` | `ChatMemberUpdatedFilter`, `FSInputFile` | ✅ |

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

---

## 🆕 Recent Changes

### Epic 8: Alan Greeting Video — IMPLEMENTED ✅ (2026-07-13)

**Overview:**
F7 greets Alan (@Alan_Z, ID 138811255) with a random video when he joins the chat. Uses the same ChatMemberUpdatedFilter + new_chat_members fallback pattern as F1 (slava_presence.py). Dict-based dedup with 10-second cooldown — no DB dependency. **Implemented, tested (164 tests pass), reviewed, and approved.**

**Architecture:**
- **Detection**: `ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER)` + `F.new_chat_members` fallback
- **Dedup**: In-memory `_last_greeting` dict keyed by `chat_id` with 10s cooldown (ALAN_GREETING_COOLDOWN=10)
- **Video picking**: `random.choice()` over files in `media/leha_greeting/` with whitelisted extensions (.mp4/.avi/.mov/.webm)
- **Sending**: `bot.send_video()` with `FSInputFile` + caption `@Alan_Z`
- **Stateless router**: No setup function, no DB or scheduler dependency
- **2 videos**: `leha_greeting_01.MP4`, `leha_greeting_02.MP4`

**New Files:**
| File | Purpose |
|------|---------|
| `handlers/alan_greeting.py` | ChatMemberUpdated + new_chat_members handlers for Alan join (F7). Exports `alan_greeting_router`. |
| `tests/test_alan_greeting.py` | 16 tests: join→video, non-Alan ignored, leave ignored, fallback, caption, random selection, empty dir, cooldown, etc. |

**Modified Files:**
| File | Changes |
|------|---------|
| `bot.py` | Register `alan_greeting_router` at position 1b |
| `config/settings.py` | Add `ALAN_USERNAME`, `ALAN_GREETING_DIR`, `ALAN_GREETING_COOLDOWN` |
| `.env.example` | Add `ALAN_USERNAME`, `ALAN_GREETING_DIR`, `ALAN_GREETING_COOLDOWN` |

**Tasks (implemented):**
| Task | Description | Status |
|------|-------------|--------|
| T-038 | Add `ALAN_USERNAME`, `ALAN_GREETING_DIR`, `ALAN_GREETING_COOLDOWN` to `config/settings.py` | ✅ |
| T-039 | Create `handlers/alan_greeting.py` with ChatMemberUpdated + new_chat_members handlers | ✅ |
| T-040 | Register `alan_greeting_router` at position 1b in `bot.py` | ✅ |
| T-041 | Create `tests/test_alan_greeting.py` (16 test scenarios) | ✅ |
| T-042 | Update `plans/ARCHITECTURE.md` to v2.2.0 with F7 design | ✅ |
| T-043 | Update `plans/MEMORY.md` with F7 knowledge graph | ✅ |
| T-044 | Run full test suite — 164 tests pass, zero regressions | ✅ |
| T-045 | QA review: verified with Builder + Reviewer pipeline, 3 fixes applied | ✅ |

**Review Findings (3 issues, all fixed):**
| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| **B1** | Critical | `_last_greeting` timestamp set before `send_video` → cooldown consumed on failed sends | Set `_last_greeting[chat_id] = time.time()` only after `success` check |
| **M1** | Moderate | No `os.path.isfile()` guard in video enumeration → subdirectories treated as files | Added `os.path.isfile(f)` condition in list comprehension |
| **M2** | Moderate | Dead `setup_alan_greeting` function referenced in design docs (router is stateless) | Removed stale function reference; `alan_greeting_router` imported directly |

**Architecture Decisions (D13-D15):**
- **D13**: Dict-based dedup, not DB — Greeting cooldown is transient; dict resets on bot restart which is acceptable
- **D14**: Same join detection pattern as F1 — ChatMemberUpdatedFilter + new_chat_members fallback is proven reliable
- **D15**: `random.choice` for video selection — picks from filesystem on each join; no cache needed for small directory

### Epic 7: Better Stack Monitoring — COMPLETE ✅ (2026-07-12)

**Overview:**
Add observability to AdminBot via Better Stack — error tracking (Sentry) and cloud logging (Logtail). Zero-instrumentation design. Both guarded — bot runs normally without credentials.

**Test Results:** 146 tests pass (was 137 before Epic 7). Zero regressions.

### Dead Page V2 — Complete (2026-07-12)

F2 redesigned from time-based to event-driven architecture. Dead page posts come from private Telegram channel `@d_pages` via `forwardMessage`.

### Phase 1 — Initial Implementation (2026-07-07)

All 6 features (F1-F6) implemented from scratch in modular architecture. 5 routers, 4 services, 6 filters, 3 DB tables. 109 tests pass.

---

### Project Structure (actual)

```
C:\Code\Python\adminbot\
├── bot.py                    (entry point, 7 routers, Sentry + Logtail init)
├── requirements.txt          (v2.1.0: +sentry-sdk, +logtail-python)
├── .env.example              (complete: all 24+ settings documented, incl. F7 vars)
├── .env                      (created: SENTRY_DSN, LOGTAIL_SOURCE_TOKEN, API_TOKEN)
├── venv/                     (virtual environment — gitignored)
├── README.md
├── config/
│   └── settings.py           (all settings env-configurable, +ALAN_* F7 vars)
├── handlers/
│   ├── kostik.py             (catch-all)
│   ├── slavik.py             (F3 middleware + F4 kucha + F5 war + catch-all)
│   ├── vasya.py              (VasyaFilter + StrictAdminFilter)
│   ├── alan.py               (F6: reply engine)
│   ├── alan_greeting.py      (F7: Alan join → random greeting video) 🔶 NEW
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
│   ├── dead_page_relay.py    (forwardMessage + retry + fallback)
│   └── message_counter.py
├── tests/
│   ├── conftest.py
│   ├── test_filters.py
│   ├── test_kostik.py
│   ├── test_slavik_handlers.py
│   ├── test_vasya.py
│   ├── test_alan.py
│   ├── test_alan_greeting.py  (F7: Alan greeting video tests) 🔶 NEW
│   ├── test_slava_presence.py
│   ├── test_database.py
│   ├── test_scheduler.py
│   ├── test_dead_page_relay.py
│   ├── test_dead_page_trigger.py
│   ├── test_message_counter.py
│   ├── test_media_picker.py
│   ├── test_edge_cases.py
│   └── test_monitoring_smoke.py
├── media/
│   ├── slavic_chlen.mp4
│   ├── leha_greeting/         🔶 NEW (F7)
│   │   ├── leha_greeting_01.MP4
│   │   └── leha_greeting_02.MP4
│   └── dead_page/
│       ├── page_1.txt
│       └── slavic_ava.jpg
└── plans/
    ├── ARCHITECTURE.md       (v2.2.0 with §11.6 F7 design + D13-D15)
    ├── MEMORY.md             (v2.2.0 — this file)
    ├── board.md
    └── backlog.md
```

### Sprint Status (board.md)

| Status | Tasks |
|--------|-------|
| **Done** | T-001 – T-045 (all 45 tasks) ✅ |

> All 8 Epics complete (45 tasks). Epic 8 (F7) — implemented, tested, reviewed, approved.

---

## 🔗 Knowledge Graph Status

- **Fully synchronized** with current project state (v2.2.0 post-implementation)
- **Epic 8 (Alan Greeting Video)**: COMPLETE. F7 entity updated with implemented status, 164 tests, 3 reviewer fixes (B1/M1/M2). New relations: `feature_of` (F7→AdminBot), `registered_in` (alan_greeting→Router Architecture), `epic_of` (Epic 8→AdminBot). Stale `setup_alan_greeting` observation deleted from `handlers/alan_greeting.py`. Entities updated: `AdminBot` (v2.2.0, 164 tests), `Epic 8` (complete), `handlers/alan_greeting.py` (post-review fixes), `bot.py`, `config/settings.py`.
- **Epic 7 (Better Stack Monitoring)**: COMPLETE. 146 tests at the time.
- **Epic 6 (Dead Page V2)**: COMPLETE. 137 tests at the time.
- **All 8 Epics complete**: 45 tasks (T-001 – T-045) implemented. 164 tests pass. Production-ready.

---

## 📊 Workflow Completion Log — 2026-07-13

### Full Multi-Agent Pipeline (Epic 8: F7 Alan Greeting Video)

| Stage | Agent | Status | Details |
|-------|-------|--------|---------|
| **Step 0** | Memory | ✅ | Context sync — identified F7 requirements, prepared Epic 8 context |
| **Step 1** | PM | ✅ | backlog.md and board.md updated with Epic 8 tasks (T-038 – T-045) |
| **Step 2** | Architect | ✅ | `ARCHITECTURE.md` v2.2.0 with §11.6 Alan Greeting Video + D13-D15 |
| **Step 3** | Memory | ✅ | Knowledge graph updated with F7 entities, relations, observations (design phase) |
| **Step 4** | Builder | ✅ | Implemented `handlers/alan_greeting.py`, `tests/test_alan_greeting.py`, updated `bot.py`, `config/settings.py`, `.env.example` |
| **Step 5** | Reviewer | ✅ | Found 3 issues — B1 (timestamp-after-send), M1 (is_file guard), M2 (dead setup) |
| **Step 6** | Builder (fixes) | ✅ | All 3 review issues fixed — verified in code |
| **Step 7** | DevOps | ✅ | Full test suite: 164 tests pass (zero regressions). Plans synced (backlog.md, board.md, ARCHITECTURE.md) |
| **Step 8** | Memory | ✅ | **THIS STEP** — Knowledge graph post-implementation sync + MEMORY.md final |

### Operations Summary (Final)

| Operation | Count | Status |
|-----------|-------|--------|
| **New entities created** | 4 | `F7 — Alan Greeting Video`, `handlers/alan_greeting.py`, `media/leha_greeting/`, `Epic 8 — Alan Greeting Video` |
| **New relations created** | 11 | detects_join_for, uses, follows_pattern_of, implemented_by, part_of, belongs_to, has_feature, has_epic, feature_of, registered_in, epic_of |
| **Entities updated (post-implementation)** | 6 | `AdminBot` (v2.2.0, 164 tests, F7 implemented), `F7` (implemented + review fixes), `Epic 8` (complete), `handlers/alan_greeting.py` (B1/M1/M2 fixes), `bot.py` (position 1b), `config/settings.py` (F7 vars) |
| **Stale observations deleted** | 1 | `handlers/alan_greeting.py`: removed stale "Exports setup_alan_greeting" |
| **MEMORY.md updated** | ✅ | v2.2.0 post-implementation — all 8 Epics complete, 164 tests, production-ready |
| **ARCHITECTURE.md** | ✅ | v2.2.0 with §11.6 Alan Greeting Video, §15 D13-D15 |

---

*Последнее обновление: 2026-07-13 — Step 8 Memory Agent Final Sync (F7 Post-Implementation — All 8 Epics Complete)*

---

## ✅ FINAL COMPLETION STAMP — 2026-07-13

> **F7 Alan Greeting Video — полный цикл (8 шагов) завершён.**
> 164 теста, v2.2.0, готово к деплою.
> Все 8 Epic'ов (45 задач T-001 – T-045) выполнены.
> Проект **PRODUCTION-READY**.
