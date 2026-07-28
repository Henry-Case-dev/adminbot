# MEMORY.md — AdminBot

> **Версия:** v2.12.1 (implemented)
> **Дата:** 2026-07-29
> **Статус:** Epics 1-16 DEPLOYED ✅. 387 тестов (v2.12.1).
> **Commit:** Epic 16 — post-implementation sync complete.

---

## 🔍 Context Sync Summary (2026-07-29) — Epic 16 IMPLEMENTED

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-14** | ✅ COMPLETE | 99 tasks T-001–T-099 deployed. |
| **Epic 15** | ✅ DEPLOYED | Otboy → Common Service. v2.12.0. 372 тестов. |
| **Epic 16** | ✅ IMPLEMENTED | Bugfixes v2.12.0→v2.12.1. 7 задач (T-109–T-115). Review passed. |
| **MEMORY.md** | ✅ UPDATED | v2.12.1 — this file, post-implementation sync complete. |

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
| Тесты | pytest + pytest-asyncio | ✅ 387 тестов PASS (v2.12.1) |
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

### 1. Router Priority Order (КРИТИЧНО — v2.12.1)
```
0.  admin_commands_router (Command filters) — /deadpage, /alangreet
1.  ChatMemberUpdated (slava_presence_router) — F1
1b. ChatMemberUpdated (alan_greeting_router) — F7: Alan join → greeting video
2.  kostik_router (user_id=350803143)
3.  alan_router (user_id=138811255) + DB counter — F6 + F7v2 silence greeting
4.  dead_page_router — Dead Page V2 trigger from @d_pages
4b. war_alert_router — F5v2: war keywords (Slava) + TargetChannelFilter repost detection
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
| **F5v2** | War Words Alert: caption fix, 90+ keywords, TargetChannelFilter, random replies | `handlers/war_alert.py` | ✅ |
| **F6** | @Alan_Z → random reply каждые 10 сообщений | `handlers/alan.py` | ✅ |
| **F7** | Alan join → random greeting video | `handlers/alan_greeting.py` | ✅ |
| **F7v2** | Alan silence greeting — "Леха проснулся" | `handlers/alan.py` (inlined) | ✅ |
| **F8** | slavic_na_litso.jpg — каждый N-й ответ "пошёл нахуй" → фото | `handlers/slavik.py` | ✅ |
| **E9** | Admin test commands: /deadpage, /alangreet | `handlers/admin_commands.py` | ✅ |
| **F9** | Otboy Service — детект "отбой" (все пользователи) → common/otboy/ media | `handlers/common.py` (`otboy_handler`) + `CommonRelay` | ✅ |
| **F10** | Danger Detection — 135+ keywords (v2.12.1) | `handlers/common.py` (`danger_handler`) + `DangerWordFilter` | ✅ v2.12.1 |

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
| `DANGER_WORDS` | `(WAR_WORDS — 135+ keywords)` | F10: comma-separated danger keywords (v2.12.1: полный WAR_WORDS из war_word.py) |

---

## ✅ Epic 16: Bug Fixes — v2.12.0 → v2.12.1 (IMPLEMENTED, 2026-07-29)

> **Цель:** Patch-release багфиксов без новых фич. 7 задач (T-109–T-115).
> **Статус:** IMPLEMENTED ✅ — Review passed, все тесты зелёные (387 PASS).
> **Результат:** 5 файлов изменено (1 новый, 4 модифицированных). +15 тестов.

### Задачи Epic 16 — ВСЕ COMPLETED

| Task | Название | Компонент | Статус |
|------|----------|-----------|--------|
| **T-109** | DangerWordFilter expansion | `filters/danger_word.py` | ✅ 22→135+ слов из WAR_WORDS |
| **T-110** | Collect-then-Group heuristic | `services/dead_page_relay.py` | ✅ probe&collect → один forward_messages() |
| **T-111** | Дополнительные тесты | `tests/` | ✅ +15 тестов (387 total) |
| **T-112** | Документация | `plans/` | ✅ ARCHITECTURE.md + MEMORY.md synced |
| **T-113** | Проверка DEAD_PAGE_RELAY_CHANNEL_ID | Конфигурация | ✅ Channel ID валидирован |
| **T-114** | TargetChannelFilter | `filters/target_channel.py` (NEW) | ✅ Кастомный BaseFilter |
| **T-115** | Propagation fix в war_alert | `handlers/war_alert.py` | ✅ F.forward_origin→TargetChannelFilter |

### T-109: DangerWordFilter — расширение до 135+ слов
- **Было (Epic 15):** 22 keywords
- **Стало (Epic 16):** Все 135+ словоформ из `filters/war_word.py::WAR_WORDS`
- **17+ семантических семейств:** БПЛА, ракета/ракетный, дрон/беспилотник, опасность/опасен, тревога, сирена, атака, угроза, обстрел, взрыв, вспышка, убежище/укрытие/бункер, падение/сбитие, эвакуация, отбой, летит/прилет, беспилотный
- **Overlap с WarWordFilter by design:** оба сервиса срабатывают на одном сообщении

### T-110: DeadPageRelay — Collect-then-Group heuristic
- **Было (v2.11.0):** forward primary → probe forward (+1,+2,...) → probe backward (-1,-2,...) — каждый sibling отдельным forward_message + delete
- **Стало (v2.12.1):**
  - Фаза 1: Probe & collect — пробинг соседних ID (±9) с date-matching (±2s), сбор всех matching ID в список
  - Фаза 2: Один `forward_messages(chat_id, from_chat_id, message_ids=all_ids)` для всего альбома
- **Преимущества:** чище лента (нет deleted ghost messages), меньше API вызовов, атомарная отправка альбома

### T-114/T-115: TargetChannelFilter — новый фильтр + propagation fix
- **Файл:** `filters/target_channel.py` (NEW)
- **Проблема:** `F.forward_origin` матчил ВСЕ forwarded-сообщения → блокировал propagation к common_router (position 4c)
- **Решение:** `TargetChannelFilter` — кастомный `BaseFilter`, матчит только каналы из `WAR_CHANNEL_IDS`/`WAR_CHANNEL_USERNAMES`
- **handlers/war_alert.py:** `@war_alert_router.message(TargetChannelFilter())` заменил `@war_alert_router.message(F.forward_origin)`
- **Non-war forwarded →** propagation продолжается → common_router получает сообщения

### Test Suite (387 total)

| Area | Count | Delta |
|------|-------|-------|
| Baseline (Epic 15) | 372 | — |
| Danger words (135+) | +8 | test_common.py |
| Collect-then-Group edge cases | +4 | test_dead_page_relay.py |
| TargetChannelFilter + propagation | +3 | test_war_alert.py |
| **Total** | **387** | **+15 net** |

### Changed Components

| Файл | Тип изменения | Задача |
|------|---------------|--------|
| `filters/danger_word.py` | MODIFIED | T-109: расширение списка до 135+ слов |
| `services/dead_page_relay.py` | MODIFIED | T-110: Collect-then-Group heuristic |
| `filters/target_channel.py` | **NEW** | T-114: новый фильтр TargetChannelFilter |
| `handlers/war_alert.py` | MODIFIED | T-115: замена F.forward_origin на TargetChannelFilter |
| `tests/test_common.py` | MODIFIED | T-111: новые тесты danger words |
| `tests/test_dead_page_relay.py` | MODIFIED | T-111: тесты Collect-then-Group edge cases |
| `tests/test_war_alert.py` | MODIFIED | T-111: тесты propagation fix |

### Risky Check Items — Resolved

| RC | Описание | Статус |
|----|----------|--------|
| RC1 | DangerWordFilter и WarWordFilter дублируют проверки | ✅ By design — оба срабатывают |
| RC2 | Date proximity ±2s в Collect-then-Group | ✅ Known limitation — принято |
| RC3 | TargetChannelFilter ленивая инициализация | ✅ Используется существующий _is_target_channel() helper |

---

## Previous Epic: 15 — Common Service Refactoring (SUPERSEDED)

> Original Epic 15 (v2.12.0) is now superseded by v2.12.1 (Epic 16).
> All functionality preserved under `handlers/common.py` + `CommonRelay`.

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
| v2.12.0 | 2026-07-28 | Epic 15 (Common Service) | T-100–T-107 | 372 |
| **v2.12.1** | **2026-07-29** | **Epic 16 (Bug Fixes)** | **T-109–T-115** | **387** |

---

### Sprint Status

| Status | Tasks |
|--------|-------|
| **Done** | T-001 – T-115 (115 задач across 16 Epics) ✅ |
| **Planned** | — (backlog empty) |

> Epics 1-16 COMPLETE & DEPLOYED. AdminBot v2.12.1 — Production-Ready.
> 387 тестов, 10 роутеров, 5 таблиц БД, Sentry + Logtail мониторинг.
> Все 16 Epic'ов завершены. Zero known bugs.

---

*Последнее обновление: 2026-07-29 — EPIC 16 IMPLEMENTED. Post-implementation sync: Knowledge Graph полностью синхронизирован — сущности Epic-16-Bug-Fixes (IMPLEMENTED), TargetChannelFilter (IMPLEMENTED), DangerWordFilter (расширен до 135+), DeadPageRelay (Collect-then-Group). Созданы 13 новых observation, 5 новых сущностей (AdminBot-v2.12.1, T-109, T-110, T-114, T-115), 11 новых отношений. MEMORY.md обновлён до v2.12.1 (implemented) с 387 тестами.*
