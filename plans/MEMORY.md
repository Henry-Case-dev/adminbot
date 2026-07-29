# MEMORY.md — AdminBot

> **Версия:** v2.13.0 (APPROVED)
> **Дата:** 2026-07-30
> **Статус:** Epics 1-17 APPROVED ✅. 399 тестов. Бот активен в production (v2.12.1). v2.13.0 готов к деплою.
> **Commit:** Epic 17 — Danger Word Fix (APPROVED, awaiting deployment commit).

---

## 🔍 Context Sync Summary (2026-07-30) — Epic 17 APPROVED

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-16** | ✅ DEPLOYED | 115 задач T-001–T-115 deployed. |
| **Epic 17** | ✅ APPROVED | Danger Word Fix — v2.13.0. 399/399 тестов. |
| **MEMORY.md** | ✅ UPDATED | v2.13.0-approved — Epic 17 final state synced. |
| **Сервер** | ✅ ACTIVE | nik@198.46.175.136:/var/www/admin_bot. systemctl: running. |

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
| Тесты | pytest + pytest-asyncio | ✅ 399 тестов PASS (v2.13.0) |
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

### 1. Router Priority Order (КРИТИЧНО — v2.13.0)
```
0.  admin_commands_router (Command filters) — /deadpage, /alangreet
1.  ChatMemberUpdated (slava_presence_router) — F1
1b. ChatMemberUpdated (alan_greeting_router) — F7: Alan join → greeting video
2.  kostik_router (user_id=350803143)
3.  alan_router (user_id=138811255) + DB counter — F6 + F7v2 silence greeting
4.  dead_page_router — Dead Page V2 trigger from @d_pages
4b. war_alert_router — F5v2: war keywords (Slava) + TargetChannelFilter repost detection
4c. common_router — F9/F10: otboy_handler + danger_handler (ALL users, shared cooldown)
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
| **F10** | Danger Detection — 135+ keywords (единый DANGER_WORDS из word_lists.py) | `handlers/common.py` (`danger_handler`) + `DangerWordFilter` | ✅ v2.13.0 |

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
| `DANGER_WORDS` | `(135+ keywords)` | F10: comma-separated danger keywords (единый источник: filters/word_lists.py) |

---

## ✅ Epic 17: Danger Word Fix — v2.13.0 (APPROVED, 2026-07-30)

> **Цель:** Исправить баг, при котором common_router (position 4c) не получает сообщения от Славы с danger-словами.
> **Статус:** APPROVED ✅ — все задачи T2, T3, T4 выполнены, ревью пройдено, 399/399 тестов.
> **Версия:** v2.13.0 готов к деплою.

### Root Cause (подтверждённый)

```
Сообщение Славы: «летит дрон опасность»
    ↓
war_alert_router (4b): war_keyword_handler матчит (UserIdFilter + WarWordFilter)
    → выполняет message.reply(random_reply)
    → implicit return None  ← БЛОКИРУЕТ propagation
    ↓
Router.trigger() останавливается — common_router (4c) НЕ получает событие
    ↓
danger_handler НЕ срабатывает — media из common/danger/ не отправляется
```

**Решение:** `return UNHANDLED` из `aiogram.dispatcher.event.bases` во всех 4 хэндлерах.

### Задачи Epic 17 — ВСЕ COMPLETED

| Task | Название | Компонент | Статус |
|------|----------|-----------|--------|
| **T2** | Merge словарей | `filters/word_lists.py` (CREATE) | ✅ Единый DANGER_WORDS (DRY) |
| **T3** | Propagation fix: return UNHANDLED | `handlers/war_alert.py`, `handlers/common.py` | ✅ 4 хэндлера |
| **T4** | CommonRelay audio + graceful degradation | `services/common_relay.py` | ✅ Audio/voice + warning |

### T2: Merge словарей — `filters/word_lists.py`

- **Создан** `filters/word_lists.py` с единым списком `DANGER_WORDS` (135+ словоформ, 17+ семантических семейств)
- `DangerWordFilter` (filters/danger_word.py) — импортирует `DANGER_WORDS` вместо локального `_DEFAULT_DANGER_WORDS`
- `WarWordFilter` (filters/war_word.py) — импортирует `DANGER_WORDS` вместо `WAR_WORDS` class variable
- Устранено полное дублирование: WAR_WORDS и _DEFAULT_DANGER_WORDS были идентичны
- `_build_patterns` / `_build_danger_patterns` остаются локальными в каждом фильтре

### T3: Propagation fix — `return UNHANDLED`

Канонический aiogram 3.x паттерн: хэндлер должен возвращать `UNHANDLED` sentinel для разрешения propagation к следующему роутеру.

**Импорт:** `from aiogram.dispatcher.event.bases import UNHANDLED`

| Файл | Хэндлер | Изменение |
|------|---------|-----------|
| `handlers/war_alert.py` | `war_keyword_handler` | `return UNHANDLED` в конце |
| `handlers/war_alert.py` | `war_channel_repost_handler` | `return UNHANDLED` в конце |
| `handlers/common.py` | `otboy_handler` | `return UNHANDLED` в конце |
| `handlers/common.py` | `danger_handler` | `return UNHANDLED` в конце |

**Порядок роутеров НЕ изменился:**
```
0:admin → 1:slava_presence → 1b:alan_greeting → 2:kostik → 3:alan →
4:dead_page → 4b:war_alert → 4c:common → 5:slavik → 6:vasya
```

### T4: CommonRelay — audio support + graceful degradation

- **Audio форматы:**
  - `.mp3` → `send_audio` (константа `MEDIA_AUDIO = "audio"`)
  - `.ogg` → `send_voice` (константа `MEDIA_VOICE = "voice"`)
- `_detect_media_type()` расширена: `.mp3` → `MEDIA_AUDIO`, `.ogg` → `MEDIA_VOICE`
- `_send_by_type()` расширена: `send_audio` и `send_voice` ветки
- **Graceful degradation:** `_scan_directory()` при `FileNotFoundError` → `logger.warning()` вместо `logger.exception()`

### Файлы Epic 17

| Файл | Тип | Статус |
|------|-----|--------|
| `filters/word_lists.py` | **CREATE** | ✅ IMPLEMENTED |
| `filters/danger_word.py` | MODIFY | ✅ IMPLEMENTED |
| `filters/war_word.py` | MODIFY | ✅ IMPLEMENTED |
| `handlers/common.py` | MODIFY | ✅ IMPLEMENTED |
| `handlers/war_alert.py` | MODIFY | ✅ IMPLEMENTED |
| `services/common_relay.py` | MODIFY | ✅ IMPLEMENTED |
| `tests/test_common.py` | MODIFY | ✅ 104 теста (+5 edge case) |

### Test Suite (399 total)

| Area | Count | Delta |
|------|-------|-------|
| Baseline (Epic 16) | 387 | — |
| Epic 17: edge cases + propagation | +12 | test_common.py (+5), propagation/integration (+7) |
| **Total** | **399** | **+12 net** |

### Risky Check Items — Resolved

| RC | Описание | Статус |
|----|----------|--------|
| RC1 | UNHANDLED может изменить поведение slavik_router catch-all? | ✅ Resolved — handler'ы common_router (otboy, danger) теперь возвращают UNHANDLED, propagation к slavik_router сохранён. war_alert_router больше не блокирует propagation. |
| RC2 | word_lists.py нарушает обратную совместимость? | ✅ Resolved — оба фильтра используют одинаковый список. Импорт из word_lists.py не меняет поведение. |
| RC3 | audio форматы: нужны ли media файлы? | ✅ Resolved — инфраструктурная поддержка. Файлы появятся позже при необходимости. |

---

## ✅ Epic 16: Bug Fixes — v2.12.0 → v2.12.1 (DEPLOYED, 2026-07-29)

> **Цель:** Patch-release багфиксов без новых фич. 7 задач (T-109–T-115).
> **Статус:** DEPLOYED ✅ — Commit b58d60f, сервер nik@198.46.175.136, systemctl active (running).
> **Результат:** 5 файлов изменено (1 новый, 4 модифицированных). +15 тестов. 387 PASS.

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
| v2.12.1 | 2026-07-29 | Epic 16 (Bug Fixes) | T-109–T-115 | 387 |
| **v2.13.0** | **2026-07-30** | **Epic 17 (Danger Word Fix)** | **T2–T4** | **399** |

---

### Sprint Status

| Status | Tasks |
|--------|-------|
| **Done** | T-001 – T-115 + T2, T3, T4 (117 задач across 17 Epics) ✅ |
| **Planned** | — (все Epic'ы завершены) |

> Epics 1-16 DEPLOYED ✅. Epic 17 APPROVED ✅ — готов к деплою. AdminBot v2.13.0 — Production-ready.
> 399 тестов, 10 роутеров, 5 таблиц БД, Sentry + Logtail мониторинг.
> 17 Epic'ов завершены. Ноль известных багов.

---

## 🚀 Deployment Details (Final)

| Параметр | Значение |
|----------|----------|
| **Версия** | v2.13.0 (APPROVED) |
| **Предыдущий коммит** | `b58d60f` (v2.12.1) |
| **Дата** | 2026-07-30 |
| **Сервер** | nik@198.46.175.136 |
| **Путь** | /var/www/admin_bot |
| **Статус** | systemctl status adminbot → active (running) |
| **Git remote** | origin/master — pushed успешно |
| **Тесты** | 399 PASS (все зелёные) |
| **Эпики** | 1-16 DEPLOYED ✅, 17 APPROVED ✅ |
| **Задачи** | T-001 – T-115 + T2/T3/T4 (117 задач) закрыты |

---

*Обновление: 2026-07-30 — EPIC 17 APPROVED. Knowledge Graph синхронизирован: обновлены entity Epic-17-Danger-Word-Fix (APPROVED), AdminBot-v2.13.0 (APPROVED/ready-for-deploy), DangerWordFilter, CommonRelay, common-service, war_alert_router, filters/word_lists.py, AdminBot, AdminBot Router Architecture, handlers/common.py, services/common_relay.py, handlers/war_alert.py, tests/test_common.py. MEMORY.md обновлён до v2.13.0-approved. Проект в продакшене (v2.12.1), Epic 17 готов к деплою. 399 тестов. Ноль регрессий. Ноль известных багов.*