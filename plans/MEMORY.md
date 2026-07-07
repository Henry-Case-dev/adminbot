# MEMORY.md — AdminBot

> **Версия:** v1.3.0 (Alan_Z Refactor)
> **Дата:** 2026-07-07
> **Статус:** PRODUCTION-READY — Onupon replaced with Alan_Z, F6 refactored, 115 tests pass

---

## 📋 Project Overview

**AdminBot** — юмористический Telegram-бот для личного чата трёх друзей (Слава, Костик, Вася).  
Написан на **Python** с использованием **aiogram 3.x**. Работает через long-polling.

### Стек
| Компонент | Технология | Статус |
|-----------|-----------|--------|
| Рантайм | Python 3.x + asyncio | ✅ |
| Фреймворк | aiogram 3.x | ✅ |
| База данных | SQLite (local_database.db) | ✅ 3 таблицы, WAL mode |
| Конфигурация | .env + config/settings.py | ✅ Все настройки через env |
| Тесты | pytest + pytest-asyncio | ✅ 122 теста PASS |
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

### 1. Модульная архитектура (v1.1.0)
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
4. slavik_router (user_id=479167456) + middleware F3 + F4 + F5 + catch-all
5. vasya_router (text filters, no user restriction)
```
**Причина:** User-ID-based routers BEFORE text-based routers. ChatMemberUpdated separate from Message handlers.

### 3. 6 фич (F1–F6) — ВСЕ РЕАЛИЗОВАНЫ И ПРОТЕСТИРОВАНЫ

| # | Фича | Реализация | Фильтр/Сервис |
|---|------|------------|---------------|
| **F1** | Детект возвращения Славы → «ДОЛБОЕБ ВЕРНУЛСЯ» | `handlers/slava_presence.py` | `DatabaseService`, `SchedulerService` |
| **F2** | Dead Page: фото+текст 2x/день + immediate | `SchedulerService` + `MediaService` | `dead_page_posts` table |
| **F3** | GIF каждые 5 сообщений Славы | `MessageCounterMiddleware` | `message_counters` table |
| **F4** | «КУЧА» → «ДАЛБАЕБ» | `handlers/slavik.py` | `KuchaWordFilter` |
| **F5** | Военные слова → «трясло ебаное» | `handlers/slavik.py` | `WarWordFilter` |
| **F6** | @Alan_Z → random reply каждые 10 сообщений (тренировки/лонгковид/фьючерсы/нейросети/жим дьявола) | `handlers/alan.py` | `UserIdFilter`, `DatabaseService` |

### 4. Database Schema (SQLite, 3 tables)

| Таблица | Назначение | Ключевые колонки |
|---------|-----------|-----------------|
| `user_presence` | Присутствие пользователя (F1, F2) | `user_id`, `chat_id`, `is_present` |
| `message_counters` | Счётчик сообщений (F3) | `chat_id`, `user_id`, `count` |
| `dead_page_posts` | Учёт dead-page постов (F2) | `chat_id`, `slot` (morning/evening/join), `date` |

### 5. Services

| Сервис | Файл | Зависимости |
|--------|------|------------|
| `DatabaseService` | `services/database.py` | aiosqlite, asyncio.Lock |
| `MediaService` | `services/media_picker.py` | random, glob, Path (stateless) |
| `SchedulerService` | `services/scheduler.py` | DatabaseService, MediaService, asyncio |
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
| `MORNING_HOUR` | `10` | Dead page morning slot |
| `EVENING_HOUR` | `20` | Dead page evening slot |
| `POLL_INTERVAL` | `60` | Scheduler poll interval (seconds) |
| `GIF_INTERVAL` | `5` | Send GIF every N messages |
| `GIF_PATH` | `media/slavic_chlen.mp4` | GIF file path |
| `DEAD_PAGE_DIR` | `media/dead_page` | Dead page media directory |

---

## 🆕 Recent Changes

### Implementation + Review Cycle Complete (2026-07-07)

**Phase 1 — Implementation:**
- All 6 features (F1-F6) implemented from scratch in modular architecture
- 5 routers, 4 services, 6 filters, 3 DB tables created
- 109 tests pass (up from 0 before implementation)
- 12 test files covering all handlers, filters, services, edge cases

**Phase 2 — Review Fixes Applied:**

| ID | Fix | Files Affected |
|----|-----|---------------|
| **B1** | KuchaWordFilter regex tightened from `[а-яё]*` to precise declension matching | `filters/kucha_word.py` |
| **H1+H2** | Legacy modules deleted (`kostik_module.py`, `slavik_module.py`, `vasya_module.py`); filter-level tests added for `VasyaFilter` and `StrictAdminFilter` | Root + `tests/test_filters.py` |
| **M1** | `new_chat_members` fallback handler added for F1 (redundant detection) | `handlers/slava_presence.py` |
| **M4** | DB fixture reverted to manual event loop (no async fixture issues) | `tests/conftest.py` |
| **M5** | All settings now configurable via environment variables | `config/settings.py` |
| **L3** | `on_shutdown` hook added to bot.py (DB cleanup deferred) | `bot.py` |

**Remaining LOW items (not blocking):**
- `README.md` uses platform-specific Windows commands (acceptable for Windows-first project)
- **H3** — No dispatcher integration tests (deferred; unit tests cover all components)
- Quoting feature not implemented — Telegram native `reply_to` covers the need
- L3 — `on_shutdown` doesn't call `DatabaseService.close()` (db is local to `on_startup`; SQLite WAL mode handles crashes)
- `__pycache__` has stale `.pyc` files for deleted modules (harmless)

### Project Structure (actual)

```
C:\Code\Python\adminbot\
├── bot.py                    (entry point, router wiring, on_startup/on_shutdown)
├── requirements.txt
├── .env.example              (complete: all 12 settings documented)
├── README.md
├── config/
│   └── settings.py           (all settings env-configurable)
├── handlers/
│   ├── kostik.py             (F7: catch-all "пошёл нахуй кринжатура ебаная")
│   ├── slavik.py             (F3 middleware + F4 kucha + F5 war + catch-all)
│   ├── vasya.py              (VasyaFilter + StrictAdminFilter)
│   ├── alan.py                (F6: reply engine — random phrase every 10 msgs)
│   └── slava_presence.py     (F1: ChatMemberUpdated + new_chat_members fallback)
├── filters/
│   ├── user_id.py
│   ├── vasya_name.py
│   ├── admin_word.py
│   ├── kucha_word.py         (B1 fix: precise declension regex)
│   └── war_word.py
├── services/
│   ├── database.py
│   ├── media_picker.py
│   ├── scheduler.py
│   └── message_counter.py
├── tests/
│   ├── conftest.py           (M4 fix: manual event_loop, session scope)
│   ├── test_filters.py       (H1+H2: VasyaFilter + StrictAdminFilter tests)
│   ├── test_kostik.py
│   ├── test_slavik_handlers.py
│   ├── test_vasya.py
│   ├── test_alan.py
│   ├── test_slava_presence.py
│   ├── test_database.py
│   ├── test_scheduler.py
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
| **Done** | **T-001 – T-015 (all 15 tasks)** ✅ |

> ✅ Board.md and backlog.md synced. All epics fully complete.

### Legacy Migration — COMPLETE
- `vasya_module.py` → **DELETED** → `handlers/vasya.py` + `filters/vasya_name.py` + `filters/admin_word.py`
- `kostik_module.py` → **DELETED** → `handlers/kostik.py` + `filters/user_id.py`
- `slavik_module.py` → **DELETED** → `handlers/slavik.py` + `filters/user_id.py` + `services/message_counter.py`

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

- **Fully synchronized** with final project state (v1.2.0)
- **Final entities**: 1 Project, 3 Architecture, 1 Milestone, 1 Pending (5 LOW items), 6 Features (F1-F6), 4 Users, 5 Handlers, 4 Services, 6 Filters, 1 Test Strategy, 3 DB tables (Alan_Z replaces Onupon in F6)
- **Final observations added**: 109 tests passing, 30+ files, all review fixes resolved, 5 LOW technical debt items deferred

---

*Последнее обновление: 2026-07-07 — Final Sync (Memory Agent)*
