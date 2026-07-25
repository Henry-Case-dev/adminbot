# MEMORY.md — AdminBot

> **Версия:** v2.9.0-planning
> **Дата:** 2026-07-25
> **Статус:** Epic 12 (Bugfix Reposts + slavic_na_litso.jpg) — PLANNING. Epic 11 DEPLOYED ✅. 271 тест. Бот активен (PID 262625, сервер nik@198.46.175.136).

---

## 🔍 Context Sync Summary (2026-07-25)

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-9** | ✅ COMPLETE | Epics 1-9 завершены (T-001 – T-051). |
| **Bugfixes T-046–T-053** | ✅ COMPLETE | Dead Page Relay, Alan Greeting, Propagation — все исправлены. |
| **Epic 10 (F5v2)** | 🔵 PLANNING | War Words Redesign — T-054–T-063. 10 задач готовы. |
| **Epic 11 (F7v2)** | ✅ DEPLOYED | Alan Silence Greeting в production. Commit 7f09dba. ALAN_SILENCE_GREETING_HOURS=2. |
| **Epic 12 (NEW)** | 🔵 PLANNING | Багфикс репостов war_alert + фича slavic_na_litso.jpg. 6 задач (T-078–T-083). |
| **Routers** | ✅ 9 routers | 0:admin → 1:slava_presence → 1b:alan_greeting → 2:kostik → 3:alan → 4:dead_page → 4b:war_alert → 5:slavik → 6:vasya. |
| **MEMORY.md** | ✅ UPDATED | v2.9.0-planning — this file. |
| **ARCHITECTURE.md** | ⚠️ ТРЕБУЕТ ОБНОВЛЕНИЯ | Секция F5v2 (war_alert) требует обновления после T-078. Нужна новая секция для slavic_na_litso.jpg. |
| **board.md** | ✅ UPDATED | Epic 12 в Backlog. Epic 11 + Epics 7-9 + bugfixes в Done. |
| **backlog.md** | ✅ UPDATED | Epic 12 добавлен. Epics 7-11 актуализированы. |

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
| Тесты | pytest + pytest-asyncio | ✅ 271 тест PASS (v2.8.0) |
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

### 1. Router Priority Order (КРИТИЧНО — v2.9.0)
```
0.  admin_commands_router (Command filters) — /deadpage, /alangreet
1.  ChatMemberUpdated (slava_presence_router) — F1
1b. ChatMemberUpdated (alan_greeting_router) — F7: Alan join → greeting video
2.  kostik_router (user_id=350803143)
3.  alan_router (user_id=138811255) + DB counter — F6 + F7v2 silence greeting
4.  dead_page_router — Dead Page V2 trigger from @d_pages
4b. war_alert_router — F5v2: war keywords (Slava) + channel repost detection
5.  slavik_router (user_id=479167456) + middleware F3 + F4 + catch-all
6.  vasya_router (text filters, no user restriction)
```

### 2. 10 фич (F1–F7v2 + Epic 9 + Epic 12)

| # | Фича | Реализация | Статус |
|---|------|------------|--------|
| **F1** | Детект возвращения Славы → «ДОЛБОЕБ ВЕРНУЛСЯ» | `handlers/slava_presence.py` | ✅ |
| **F2** | Dead Page V2: forwardMessage из @d_pages + fallback | `DeadPageRelay` + `DeadPageTrigger` | ✅ |
| **F3** | GIF каждые 5 сообщений Славы | `MessageCounterMiddleware` | ✅ |
| **F4** | «КУЧА» → «ДАЛБАЕБ» | `handlers/slavik.py` + `KuchaWordFilter` | ✅ |
| **F5v2** | War Words Alert: caption fix, 90+ keywords, channel repost, random replies | `handlers/war_alert.py` | 🔵 PLANNING (Epic 10) |
| **F6** | @Alan_Z → random reply каждые 10 сообщений | `handlers/alan.py` | ✅ |
| **F7** | Alan join → random greeting video | `handlers/alan_greeting.py` | ✅ |
| **F7v2** | Alan silence greeting — "Леха проснулся" | `handlers/alan.py` (inlined) | ✅ |
| **E9** | Admin test commands: /deadpage, /alangreet | `handlers/admin_commands.py` | ✅ |
| **F8** | slavic_na_litso.jpg — каждый N-й ответ "пошёл нахуй" → фото | `handlers/slavik.py` | 🔵 PLANNING (Epic 12) |

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
| `SLIVIC_NA_LITSO_INTERVAL` | `10` | 🔵 NEW (Epic 12): каждый N-й "пошёл нахуй" → фото |

---

## 🆕 Epic 12: Багфикс репостов + slavic_na_litso.jpg (2026-07-25) 🔵 PLANNING

### T-078: Багфикс — war_alert не ловит forwarded-сообщения Славы

**Проблема:** Бот перехватывает фразы о "бпла" и "ракетах", которые пишет сам Слава,
но НЕ перехватывает его репосты (forwarded messages) и текст в этих репостах.

**Гипотезы для расследования:**
1. `UserIdFilter` для forwarded-сообщений — `message.from_user` = тот кто переслал (Slava) → должно работать
2. `message.text` / `message.caption` для forwarded-сообщений — структура Message в aiogram 3.x
3. Порядок хендлеров на одном роутере — `war_channel_repost_handler` (F.forward_origin) может "перехватывать" forwarded-сообщения до `war_keyword_handler`
4. Propagation в aiogram — `F.forward_origin` фильтр может останавливать обработку

**Файлы:** `handlers/war_alert.py`, `filters/war_word.py`, `filters/user_id.py`

### T-079: Фича — slavic_na_litso.jpg каждый N-й ответ "пошёл нахуй"

**Требование:**
- `media/slavic_na_litso.jpg` уже существует
- Каждый N-й ответ "пошёл нахуй" (по умолчанию 10) → `send_photo` вместо текста
- Счётчик сбрасывается после отправки фото
- Независим от F3 GIF-счётчика (MessageCounterMiddleware)
- Конфигурация через `SLIVIC_NA_LITSO_INTERVAL` в .env

**Файлы:** `handlers/slavik.py`, `config/settings.py`, `.env.example`, `services/database.py`

### T-080: Тесты для багфикса репостов
6 тестов: forwarded + war keywords (text/caption), без keywords, не-Slava, конфликт хендлеров, интеграция.

### T-081: Тесты для slavic_na_litso.jpg
8 тестов: N-1 текстовых, N-й фото, сброс счётчика, независимость от F3, независимость от F4, конфигурация, отключение (0), несколько чатов.

### T-082: README + ARCHITECTURE + MEMORY + коммит + пуш
### T-083: Деплой на сервер + smoke tests

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
| v2.7.0 | 2026-07-16 | Epic 10 War Words (Planning) | T-054–T-063 | 252 |
| **v2.8.0** | **2026-07-18** | **Epic 11 (F7v2)** | **T-064–T-077** | **271** |
| **v2.9.0** | **2026-07-25** | **Epic 12 (Planning)** | **T-078–T-083** | **271 (baseline)** |

---

### Sprint Status

| Status | Tasks |
|--------|-------|
| **Done** | T-001 – T-077 (77 tasks) ✅ |
| **Planned** | T-054 – T-063 (Epic 10: War Words Redesign) 🔵 |
| **Planned (NEW)** | T-078 – T-083 (Epic 12: Bugfix Reposts + slavic_na_litso.jpg) 🔵 |
| **In Progress** | — |

> Epics 1-9, 11 complete (77 tasks). Epic 10 (F5v2) PLANNING — 10 tasks ready. Epic 12 NEW — 6 tasks ready. 271 tests pass. Zero regressions. Project is PRODUCTION-READY + DEPLOYED.

---

*Последнее обновление: 2026-07-25 — Epic 12 (Bugfix Reposts + slavic_na_litso.jpg) PLANNING. T-078–T-083 созданы. board.md и backlog.md синхронизированы. AdminBot v2.9.0-planning.*