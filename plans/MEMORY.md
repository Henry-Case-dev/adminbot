# MEMORY.md — AdminBot

> **Версия:** v2.12.0
> **Дата:** 2026-07-28
> **Статус:** Epics 1-15 IMPLEMENTED ✅. 372 тестов. Бот активен.
> **Commit:** Epic 15 — Common Service Refactoring + Danger Detection (F9 → unified architecture).

---

## 🔍 Context Sync Summary (2026-07-28) — IMPLEMENTED

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-14** | ✅ COMPLETE | 99 tasks T-001–T-099 deployed. |
| **Epic 15** | ✅ IMPLEMENTED | Otboy → Common Service. 372 тестов. DangerWordFilter. |
| **MEMORY.md** | ✅ UPDATED | v2.12.0 — this file. |

---

## 📋 Project Overview

**AdminBot** — юмористический Telegram-бот для личного чата трёх друзей (Слава, Костик, Вася).  
Написан на **Python** с использованием **aiogram 3.x**. Работает через long-polling.

### Стек
| Компонент | Технология | Статус |
|-----------|-----------|--------|
| Рантайм | Python 3.x + asyncio | ✅ |
| Фреймворк | aiogram 3.7+ | ✅ |
| База данных | SQLite (local_database.db) | ✅ 5 таблиц, WAL mode |
| Конфигурация | .env + config/settings.py | ✅ Все настройки через env |
| Тесты | pytest + pytest-asyncio | ✅ 372 тестов PASS (v2.12.0) |
| Документация | ARCHITECTURE.md, MEMORY.md | ✅ |
| Мониторинг | ✅ Sentry + Logtail | Error tracking + cloud logging via Better Stack |

### Пользователи чата

| Персона | User ID | Прозвище | Роутер |
|---------|--------|----------|--------|
| **Слава (Slavik)** | `479167456` | «Куча» | `handlers/slavik.py` |
| **Костик (Kostik)** | `350803143` | — | `handlers/kostik.py` |
| **Вася (Vasya)** | no ID | — | `handlers/vasya.py` |
| **@Alan_Z** | `138811255` | — | `handlers/alan.py` (F6 + F7v2) + `handlers/alan_greeting.py` (F7) |
| **Admin** | `5885953495` | — | `handlers/admin_commands.py` (Epic 9) |

---

## 🏗️ Key Architectural Decisions

### 1. Router Priority Order (КРИТИЧНО — v2.12.0)
```
0.  admin_commands_router (Command filters) — /deadpage, /alangreet
1.  ChatMemberUpdated (slava_presence_router) — F1
1b. ChatMemberUpdated (alan_greeting_router) — F7: Alan join → greeting video
2.  kostik_router (user_id=350803143)
3.  alan_router (user_id=138811255) + DB counter — F6 + F7v2 silence greeting
4.  dead_page_router — Dead Page V2 trigger from @d_pages
4b. war_alert_router — F5v2: war keywords (Slava) + channel repost detection
4c. common_router — F9+: otboy_handler + danger_handler (ALL users, shared cooldown)
5.  slavik_router (user_id=479167456) + middleware F3 + F4 + catch-all + F8
6.  vasya_router (text filters, no user restriction)
```

### 2. Фичи (F1–F10)

| # | Фича | Реализация | Статус |
|---|------|------------|--------|
| **F1** | Детект возвращения Славы → «ДОЛБОЕБ ВЕРНУЛСЯ» | `handlers/slava_presence.py` | ✅ |
| **F2** | Dead Page V2: forwardMessage из @d_pages + fallback | `DeadPageRelay` + `DeadPageTrigger` | ✅ |
| **F3** | GIF каждые 5 сообщений Славы | `MessageCounterMiddleware` | ✅ |
| **F4** | «КУЧА» → «ДАЛБАЕБ» | `handlers/slavik.py` + `KuchaWordFilter` | ✅ |
| **F5v2** | War Words Alert: caption fix, 90+ keywords, channel repost, random replies | `handlers/war_alert.py` | ✅ |
| **F6** | @Alan_Z → random reply каждые 10 сообщений | `handlers/alan.py` | ✅ |
| **F7** | Alan join → random greeting video | `handlers/alan_greeting.py` | ✅ |
| **F7v2** | Alan silence greeting — "Леха проснулся" | `handlers/alan.py` (inlined) | ✅ |
| **F8** | slavic_na_litso.jpg — каждый N-й ответ "пошёл нахуй" → фото | `handlers/slavik.py` | ✅ |
| **E9** | Admin test commands: /deadpage, /alangreet | `handlers/admin_commands.py` | ✅ |
| **F9** | Otboy Service — детект "отбой" (все пользователи) → common/otboy/ media | `handlers/common.py` (`otboy_handler`) + `CommonRelay` | ✅ v2.12.0 |
| **F10** | Danger Detection — 22 Cyrillic danger keywords → common/danger/ media | `handlers/common.py` (`danger_handler`) + `DangerWordFilter` | ✅ v2.12.0 |

### 3. Database Schema (SQLite, 5 tables)

| Таблица | Назначение | Ключевые колонки |
|---------|-----------|-----------------|
| `user_presence` | Присутствие пользователя (F1, F2) | `user_id`, `chat_id`, `is_present` |
| `message_counters` | Счётчик сообщений (F3, F6) | `chat_id`, `user_id`, `count` |
| `dead_page_posts` | Учёт dead-page постов (F2 V2) | `chat_id`, `slot`, `timestamp` |
| `channel_state` | Ключ-значение (F2 V2, F7v2) | `key` (TEXT PK), `value` (TEXT) |
| `relay_album_map` | Трекинг media_group_id для альбомов (Epic 14) | `message_id` (INTEGER PK), `media_group_id` (TEXT, INDEXED) |

### 4. Config (env-configurable via settings.py)

| Переменная | По умолчанию | Назначение |
|-----------|-------------|------------|
| `API_TOKEN` | (required) | Telegram Bot Token |
| `SLAVIK_USER_ID` | `479167456` | Slava's Telegram user ID |
| `KOSTIK_USER_ID` | `350803143` | Kostik's Telegram user ID |
| `ALAN_USER_ID` | `138811255` | Alan's Telegram user ID |
| `ALAN_SILENCE_GREETING_HOURS` | `6.0` | F7v2: hours of silence before greeting (prod=2) |
| `ADMIN_USER_ID` | `5885953495` | Admin user ID (Epic 9) |
| `GIF_INTERVAL` | `5` | Send GIF every N messages |
| `GIF_PATH` | `media/slavic_chlen.mp4` | GIF file path |
| `WAR_CHANNEL_IDS` | `1654872411` | War repost detection channel IDs (F5v2) |
| `WAR_CHANNEL_USERNAMES` | `` | War repost detection channel usernames (F5v2) |
| `WAR_REPLIES` | `` | Custom war reply phrases (F5v2) |
| `SLIVIC_NA_LITSO_INTERVAL` | `10` | F8: каждый N-й "пошёл нахуй" → фото |
| `COMMON_COOLDOWN_SECONDS` | `0` | F9/F10: shared cooldown for common sub-services (0=off) |
| `COMMON_MEDIA_BASE` | `media/common` | F9/F10: base directory for common/otboy/ and common/danger/ |
| `DANGER_WORDS` | `(22 keywords)` | F10: comma-separated danger keywords for DangerWordFilter |

---

## ✅ Epic 15: Common Service Refactoring — 2026-07-28 IMPLEMENTED

> **Цель:** Переименовать otboy service → common service, добавить Danger Detection (F10),
> унифицировать архитектуру для поддержки нескольких sub-services.
> **Результат:** v2.12.0. 372 теста. 4 файла создано, 3 изменено, 3 удалено.

### Что изменилось

| Действие | Файл | Описание |
|----------|------|----------|
| ✅ Created | `handlers/common.py` | Двух-handler роутер: `otboy_handler` + `danger_handler` |
| ✅ Created | `services/common_relay.py` | `CommonRelay` с unified `send_common(subdir)` |
| ✅ Created | `filters/danger_word.py` | `DangerWordFilter` — 22 кириллических danger keyword |
| ✅ Created | `tests/test_common.py` | 81 тест (filter, handler, relay, migration) |
| ✅ Modified | `bot.py` | `common_router` replaces `otboy_router`, `CommonRelay` replaces `OtboyRelay` |
| ✅ Modified | `config/settings.py` | `OTBOY_*` removed, `COMMON_COOLDOWN_SECONDS` + `COMMON_MEDIA_BASE` + `DANGER_WORDS` added |
| ✅ Modified | `.env.example` | New COMMON_* vars, DANGER_WORDS documented |
| ❌ Deleted | `handlers/otboy.py` | Replaced by `handlers/common.py` |
| ❌ Deleted | `services/otboy_relay.py` | Replaced by `services/common_relay.py` |
| ❌ Deleted | `tests/test_otboy.py` | Replaced by `tests/test_common.py` (25 → 81 tests) |

### CommonRelay — Unified Media Service

- **Unified API:** `send_common(chat_id, message_id, matched_word, subdir)` — один метод для otboy и danger
- **Media type auto-detection:** photo (.jpg/.jpeg/.png/.webp/.bmp), video (.mp4/.mov/.webm без "gif"), animation (.mp4/.mov/.webm с "gif" в имени)
- **`_scan_directory(subdir)`:** случайный файл из `media/common/{subdir}/`
- **Shared cooldown:** один `dict[int, float]` для всех sub-services (`COMMON_COOLDOWN_SECONDS`)
- **Reply-to + quoting** сохранён: `ReplyParameters(message_id, quote=matched_word)`

### DangerWordFilter — F10 Danger Detection

- **22 keywords:** бпла, ракетная, опасность, тревога, внимание всем, сирена, атака, угроза, обстрел, воздушная, баллистическая, шахед, шахеды, крылатая, дрон, дроны, беспилотник, беспилотники, взрыв, взрывы, прилет, прилеты
- **Regex:** Cyrillic word boundaries `(?<![а-яё])...(?![а-яё])` + `re.IGNORECASE`
- **Pattern borrowed** from `WarWordFilter` (`filters/war_word.py`)
- **Configurable** via `DANGER_WORDS` env var (comma-separated)
- **Checks** both `message.text` and `message.caption`
- **Returns** `{"matched_word": match.group()}` for Telegram quote API

### Router Architecture (common_router at position 4c)

```
4c. common_router (name="common")
    ├── otboy_handler  (OtboyWordFilter)   → CommonRelay.send_common(subdir="otboy")
    └── danger_handler (DangerWordFilter)   → CommonRelay.send_common(subdir="danger")
```

- `OtboyWordFilter` (`filters/otboy_word.py`) — **PRESERVED**, unchanged
- Both handlers share same `CommonRelay` instance with shared cooldown
- Works for ALL users (no `UserIdFilter`)
- `setup_common(relay)` — DI function called in `bot.on_startup()`

### Test Suite (372 total)

| Area | Count | Delta |
|------|-------|-------|
| Baseline (Epic 14) | 316 | — |
| Otboy tests deleted | -25 | `tests/test_otboy.py` deleted |
| New common tests | +81 | `tests/test_common.py` created |
| **Total** | **372** | **+56 net** |

### Config Migration

| Old (Epic 13) | New (Epic 15) | Notes |
|---------------|---------------|-------|
| `OTBOY_COOLDOWN_SECONDS` (float) | `COMMON_COOLDOWN_SECONDS` (float, default 0) | Shared across sub-services |
| `OTBOY_PHOTO_PATH` (`media/otboy.jpg`) | `COMMON_MEDIA_BASE` (`media/common`) | Directory-based, scans subdirs |
| — | `DANGER_WORDS` (str, csv) | New: 22 Cyrillic keywords default |

---

## Previous Epic: 13 — Otboy Service (F9) — SUPERSEDED by Epic 15

> Original Epic 13 (v2.10.0, commit `251acef`) is now superseded. All functionality preserved,
> refactored under `handlers/common.py` + `CommonRelay` with unified architecture.

Epic 13 created: `filters/otboy_word.py`, `services/otboy_relay.py`, `handlers/otboy.py` (3 files).
Epic 15 preserves `filters/otboy_word.py`, replaces the other 2 with `handlers/common.py` + `services/common_relay.py`.

---

## Previous Completed Epics

| Version | Date | Epic | Tasks | Tests |
|---------|------|------|-------|-------|
| v1.0.0 | 2026-07-07 | Epic 1-4 | T-001–T-017 | 130 |
| v2.0.0 | 2026-07-12 | Epic 6 (Dead Page V2) | T-018–T-028 | 137 |
| v2.1.0 | 2026-07-12 | Epic 7 (Monitoring) | T-029–T-037 | 146 |
| v2.2.0 | 2026-07-13 | Epic 8 (F7 Alan Greeting) | T-038–T-045 | 164 |
| v2.3.0 | 2026-07-14 | Bugfixes T-046–T-047 | T-046–T-047 | 32 |
| v2.4.0 | 2026-07-14 | Epic 9 (Admin Commands) | T-048–T-051 | 181 |
| v2.5.0 | 2026-07-14 | T-052 (Sequential Scan) | T-052 | 185 |
| v2.6.0 | 2026-07-15 | T-053 (Propagation Fix) | T-053 | 190 |
| v2.7.0 | 2026-07-16 | Epic 10 (F5v2 War Words) | T-054–T-063 | 252 |
| v2.8.0 | 2026-07-18 | Epic 11 (F7v2) | T-064–T-077 | 271 |
| v2.9.2 | 2026-07-26 | Epic 12 (F8) | T-078–T-083 | 280 |
| v2.10.0 | 2026-07-26 | Epic 13 (F9 Otboy) | T-084–T-092 | 305 |
| v2.11.0 | 2026-07-28 | Epic 14 (Album Fix) | T-093–T-099 | 316 |
| **v2.12.0** | **2026-07-28** | **Epic 15 (Common Service)** | **T-100–T-107** | **372** |

---

### Sprint Status

| Status | Tasks |
|--------|-------|
| **Done** | T-001 – T-107 (107 tasks across 15 Epics) ✅ |
| **In Progress** | — |

> Epics 1-15 COMPLETE. 107 задач. 372 теста. 10 роутеров. 5 таблиц БД.  
> AdminBot v2.12.0 — PRODUCTION-READY.

---

*Последнее обновление: 2026-07-28 — EPIC 15 COMPLETE: Common Service Refactoring + Danger Detection. Otboy service → Common service. 81 новых тестов в test_common.py. Knowledge graph обновлён: 10 новых сущностей (Epic-15-Common-Service, CommonRelay, DangerWordFilter, common-service, 4 File entities, AdminBot-v2.12.0) + 16 отношений. Old otboy entities marked DELETED/SUPERSEDED.*
