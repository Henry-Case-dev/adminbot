# MEMORY.md — AdminBot

> **Версия:** v2.10.0
> **Дата:** 2026-07-26
> **Статус:** Epics 10, 11, 12, 13 DEPLOYED ✅. 305 тестов. Бот активен (сервер nik@198.46.175.136).

---

## 🔍 Context Sync Summary (2026-07-26)

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-9** | ✅ COMPLETE | Epics 1-9 завершены (T-001 – T-051). |
| **Bugfixes T-046–T-053** | ✅ COMPLETE | Dead Page Relay, Alan Greeting, Propagation — все исправлены. |
| **Epic 10 (F5v2)** | ✅ DEPLOYED | War Words Redesign — T-054–T-063 выполнены. Commit 40afe97. |
| **Epic 11 (F7v2)** | ✅ DEPLOYED | Alan Silence Greeting в production. Commit 7f09dba. ALAN_SILENCE_GREETING_HOURS=2. |
| **Epic 12 (F8)** | ✅ DEPLOYED | Багфикс репостов war_alert + фича slavic_na_litso.jpg. Commit 27654ac (v2.9.2). |
| **Epic 13 (F9)** | ✅ DEPLOYED | Otboy Service — T-084–T-092 выполнены. Все 9 задач + 4 дефекта ревью исправлены. |
| **Routers** | ✅ 10 routers | 0:admin → 1:slava_presence → 1b:alan_greeting → 2:kostik → 3:alan → 4:dead_page → 4b:war_alert → 4c:otboy → 5:slavik → 6:vasya. |
| **MEMORY.md** | ✅ UPDATED | v2.10.0 — this file. |
| **ARCHITECTURE.md** | ✅ UPDATED | v2.10.0 — F9 Otboy Service полностью задокументирован (секции 3/F9, 6.6, 7.6, 5/Registration Order). |
| **board.md** | ✅ UPDATED | Epic 13 в Backlog. Epics 10, 12 в Done. |
| **backlog.md** | ✅ UPDATED | Epic 13 добавлен. Epics 10, 12 отмечены DONE. |

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
| Тесты | pytest + pytest-asyncio | ✅ 305 тестов PASS (v2.10.0) |
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

### 1. Router Priority Order (КРИТИЧНО — v2.10.0)
```
0.  admin_commands_router (Command filters) — /deadpage, /alangreet
1.  ChatMemberUpdated (slava_presence_router) — F1
1b. ChatMemberUpdated (alan_greeting_router) — F7: Alan join → greeting video
2.  kostik_router (user_id=350803143)
3.  alan_router (user_id=138811255) + DB counter — F6 + F7v2 silence greeting
4.  dead_page_router — Dead Page V2 trigger from @d_pages
4b. war_alert_router — F5v2: war keywords (Slava) + channel repost detection
4c. otboy_router — F9: "отбой" detection (ALL users) → otboy.jpg with quote
5.  slavik_router (user_id=479167456) + middleware F3 + F4 + catch-all + F8
6.  vasya_router (text filters, no user restriction)
```

### 2. 11 фич (F1–F9)

| # | Фича | Реализация | Статус |
|---|------|------------|--------|
| **F1** | Детект возвращения Славы → «ДОЛБОЕБ ВЕРНУЛСЯ» | `handlers/slava_presence.py` | ✅ |
| **F2** | Dead Page V2: forwardMessage из @d_pages + fallback | `DeadPageRelay` + `DeadPageTrigger` | ✅ |
| **F3** | GIF каждые 5 сообщений Славы | `MessageCounterMiddleware` | ✅ |
| **F4** | «КУЧА» → «ДАЛБАЕБ» | `handlers/slavik.py` + `KuchaWordFilter` | ✅ |
| **F5v2** | War Words Alert: caption fix, 90+ keywords, channel repost, random replies (DEPLOYED v2.7.0) | `handlers/war_alert.py` | ✅ |
| **F6** | @Alan_Z → random reply каждые 10 сообщений | `handlers/alan.py` | ✅ |
| **F7** | Alan join → random greeting video | `handlers/alan_greeting.py` | ✅ |
| **F7v2** | Alan silence greeting — "Леха проснулся" | `handlers/alan.py` (inlined) | ✅ |
| **F8** | slavic_na_litso.jpg — каждый N-й ответ "пошёл нахуй" → фото (DEPLOYED v2.9.2) | `handlers/slavik.py` | ✅ |
| **E9** | Admin test commands: /deadpage, /alangreet | `handlers/admin_commands.py` | ✅ |
| **F9** | Otboy Service — детект "отбой" (все пользователи) → otboy.jpg с quote | `handlers/otboy.py` + `OtboyRelay` | ✅ DONE |

### 3. Database Schema (SQLite, 4 tables)

| Таблица | Назначение | Ключевые колонки |
|---------|-----------|-----------------|
| `user_presence` | Присутствие пользователя (F1, F2) | `user_id`, `chat_id`, `is_present` |
| `message_counters` | Счётчик сообщений (F3, F6) | `chat_id`, `user_id`, `count` |
| `dead_page_posts` | Учёт dead-page постов (F2 V2) | `chat_id`, `slot`, `timestamp` |
| `channel_state` | Ключ-значение (F2 V2, F7v2) | `key` (TEXT PK), `value` (TEXT) |

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
| `OTBOY_COOLDOWN_SECONDS` | `0` | F9: cooldown between otboy.jpg sends (0=no cooldown) |
| `OTBOY_PHOTO_PATH` | `media/otboy.jpg` | F9: path to otboy response image |

---

## ✅ Epic 13: Otboy Service (F9) — 2026-07-26 DONE

> **Цель:** Создать standalone scalable сервис для детекта слова "отбой" и ответа
> картинкой `media/otboy.jpg` с нативным цитированием через Telegram quote API.
> Работает для ВСЕХ пользователей чата (не user-specific).

### T-084: Архитектурное проектирование и ревью ✅ DONE
- Sub-agent review ДО начала реализации
- Проверка изоляции, масштабируемости, отсутствия влияния на другие фичи

### T-085: `filters/otboy_word.py` — OtboyWordFilter ✅ DONE
- Проверка `message.text`, `message.caption`, forwarded message text
- Регистронезависимый word-boundary детект "отбой"

### T-086: `services/otboy_relay.py` — OtboyRelay ✅ DONE
- Инкапсулированный сервис, thread-safe cooldown per-chat
- `send_otboy(chat_id, reply_to_message_id, quote_text)`

### T-087: `handlers/otboy.py` — otboy_router ✅ DONE
- Handler: OtboyWordFilter → OtboyRelay.send_otboy()
- Native Telegram reply-to + quote API (цитирование только "отбой")
- Guard: _relay is None → log + return None

### T-088: Конфигурация — `OTBOY_COOLDOWN_SECONDS` (default=0) ✅ DONE
### T-089: Регистрация otboy_router в bot.py (position 4c, до slavik) ✅ DONE
### T-090: Тесты (25 тестов: filter, handler, cooldown, propagation) ✅ DONE
### T-091: Документация (ARCHITECTURE, MEMORY) ✅ DONE
### T-092: Деплой на сервер + smoke tests ✅ DONE

**Review Defects Fixed:**
- D-1: guard `_relay is None` в хендлере ✅
- D-2: созданы 25 тестов ✅
- D-3: проверка существования файла при инициализации OtboyRelay ✅
- D-4: обновлён ARCHITECTURE.md ✅

**Архитектурный паттерн:**  
`OtboyWordFilter` (filter) → `otboy_router` (handler) → `OtboyRelay` (service)  
Аналог: `DeadPageTrigger` (handler) → `DeadPageRelay` (service), но без user-specific фильтрации.

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
| **v2.8.0** | **2026-07-18** | **Epic 11 (F7v2)** | **T-064–T-077** | **271** |
| **v2.9.0** | **2026-07-25** | **Epic 12 (F8)** | **T-078–T-083** | **271 (baseline)** |
| **v2.9.2** | **2026-07-26** | **Epic 12 bugfix** | **T-078-C debug logs** | **280** |
| **v2.10.0** | **2026-07-26** | **Epic 13 (F9 Otboy)** | **T-084–T-092** | **305** |

---

### Sprint Status

| Status | Tasks |
|--------|-------|
| **Done** | T-001 – T-092 (92 tasks) ✅ |
| **In Progress** | — |

> Epics 1-13 complete (92 tasks). Epic 13 (F9 Otboy Service) IMPLEMENTED — 9 tasks + 4 review defects fixed. 305 tests pass. Zero regressions. Project is PRODUCTION-READY + DEPLOYED.

---

*Последнее обновление: 2026-07-26 — Epic 13 (Otboy Service F9) IMPLEMENTED ✅. Knowledge graph синхронизирован: 5 сущностей обновлены. v2.10.0. 305 тестов.*
