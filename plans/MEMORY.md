# MEMORY.md — AdminBot

> **Версия:** v2.17.0 (IMPLEMENTED) — READY FOR DEPLOY
> **Дата:** 2026-08-02
> **Статус:** Epics 1-18 DEPLOYED ✅. Epic 19 IMPLEMENTED ✅. 509 тестов.
> **Текущий коммит:** `c4694c0` (v2.16.0 deployed), master branch.
> **Сервер:** nik@198.46.175.136:/var/www/admin_bot, PID 694761, memory 140.1M, 0 errors.

---

## 🔍 Context Sync Summary (2026-08-02) — Epic 19 FINAL SYNC

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-18** | ✅ DEPLOYED | 120+ задач T-001–T-115 + T2/T3/T4 + Epic 18 A/B/C. v2.16.0 в продакшене. |
| **Epic 19** | 🟢 IMPLEMENTED | Olya Service — IMPLEMENTED and APPROVED by Reviewer. 8 задач T-131–T-138 COMPLETE. 31 new tests. |
| **Review** | ✅ APPROVED | 6 issues fixed (3 HIGH, 2 MEDIUM, 1 LOW). KG populated with OlyaReviewFixes. |
| **Сервер** | ✅ ACTIVE | nik@198.46.175.136:/var/www/admin_bot. systemctl: running. v2.16.0 в проде. |

---

## 🟢 Epic 19: Olya Service — v2.17.0 (IMPLEMENTED, 2026-08-02)

> **Цель:** Создать standalone сервис для пользователя @ole4444444ka (ID 834424825).
> При получении видео-сообщения (или репоста видео) от этого пользователя бот отправляет
> случайный медиа-файл из `media/olya/cringe/` — без reply, без quote, plain send.

### User Story

| Элемент | Значение |
|---------|----------|
| **Целевой пользователь** | ID 834424825, юзернейм @ole4444444ka |
| **Триггер** | Сообщение с видео (или репост видео) от целевого пользователя |
| **Условие A** | Видео содержит текст «Спасибо, что пользуетесь - @SaveAsBot'ом» ИЛИ это репост из @SaveAsBot (channel ID 523131145) → отправить случайный файл |
| **Условие B** | Видео от целевого пользователя, НО нет ключевого текста И не репост → ВСЁ РАВНО отправить файл |
| **Тип отправки** | Plain send — НЕ reply, без quote, без reply_to_message_id |
| **Медиа-типы** | Любые (photo, video, animation/GIF, audio и т.д.) — как в CommonRelay |
| **GIF-детекция** | Если имя файла содержит "gif" → отправлять как animation |
| **Cooldown** | Настраиваемый, по умолчанию 60 секунд (1 минута) |
| **Отключение** | Полное отключение фичи через конфиг (OLYA_ENABLED=false) |
| **Медиа-директория** | `media/olya/cringe/` — уже существует, содержит olya_cringe_01.mp4 |

### Конфигурация (планируется)

| Переменная | Тип | По умолчанию | Назначение |
|-----------|-----|-------------|------------|
| `OLYA_ENABLED` | bool | `True` | Полное отключение сервиса |
| `OLYA_USER_ID` | int | `834424825` | Целевой пользователь |
| `OLYA_COOLDOWN_SECONDS` | float | `60.0` | Cooldown между отправками (0 = без ограничений) |
| `OLYA_MEDIA_DIR` | str | `media/olya/cringe` | Директория с медиа-файлами |
| `OLYA_CAPTION_TEXT` | str | `Спасибо, что пользуетесь - @SaveAsBot'ом` | Ключевой текст для Condition A (пустая строка = отключено) |
| `OLYA_CHANNEL_IDS` | str | `523131145` | ID каналов для детекции репостов (пустая строка = отключено) |
| `OLYA_MEDIA_TYPE` | str | `video` | Тип медиа-триггера: `video`, `photo`, или `video,photo` |

### Архитектурный план

```
Сообщение с видео от @ole4444444ka
        │
        ▼
┌─────────────────────────────────┐
│  OlyaVideoFilter               │
│  - UserIdFilter(834424825)     │
│  - F.content_type == VIDEO     │
│  (или PHOTO если OLYA_MEDIA_TYPE включает photo) │
│  - Condition A/B detection     │
│  - Возвращает dict или False   │
└──────────────┬──────────────────┘
               │ matched → handler
               ▼
┌─────────────────────────────────┐
│  olya_handler (handlers/olya.py)│
│  → OlyaRelay.send_olya()       │
│  → plain send (NO reply)       │
│  → return UNHANDLED (propagate) │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  OlyaRelay (services/olya_relay.py) │
│  - _scan_directory("cringe")   │
│  - _detect_media_type()        │
│  - plain send (bot.send_*)     │
│  - cooldown (in-memory, per-chat) │
└─────────────────────────────────┘
```

### Позиция роутера

Новый `olya_router` регистрируется на позиции **4d** (между common и slavik):
```
0:admin → 1:slava_presence → 1b:alan_greeting → 2:kostik → 3:alan →
4:dead_page → 4b:war_alert → 4c:common → 4d:olya → 5:slavik → 6:vasya
```

### Задачи Epic 19

| Task | Название | Компонент | Статус |
|------|----------|-----------|--------|
| **T-131** | Архитектурное проектирование Olya Service | `plans/` | ✅ IMPLEMENTED |
| **T-132** | Создать `filters/olya_video.py` — OlyaVideoFilter | `filters/` | ✅ IMPLEMENTED |
| **T-133** | Создать `services/olya_relay.py` — OlyaRelay (plain send) | `services/` | ✅ IMPLEMENTED |
| **T-134** | Создать `handlers/olya.py` — olya_router + handler | `handlers/` | ✅ IMPLEMENTED |
| **T-135** | Добавить конфигурацию в `config/settings.py` + `.env.example` | `config/` | ✅ IMPLEMENTED |
| **T-136** | Зарегистрировать `olya_router` в `bot.py` (позиция 4d) | `bot.py` | ✅ IMPLEMENTED |
| **T-137** | Полное тестовое покрытие — фильтр, сервис, хендлер, corner cases | `tests/` | ✅ IMPLEMENTED |
| **T-138** | Деплой на сервер, коммит, пуш, рестарт | DevOps | 🔵 READY FOR DEPLOY |

### Ключевые отличия от CommonRelay

| Аспект | CommonRelay (common) | OlyaRelay (olya) |
|--------|---------------------|-------------------|
| **Триггер** | DangerWordFilter / OtboyWordFilter (любой пользователь, текстовые слова) | UserIdFilter + ContentTypeFilter (конкретный пользователь + видео) |
| **Отправка** | Reply + quote (`reply_parameters`) | **Plain send** (без reply, без quote) |
| **Cooldown** | Dual-layer (общий + danger-specific) | Single-layer (только olya) |
| **Конфиг** | COMMON_* / DANGER_* | OLYA_* |
| **Медиа-тип** | Все типы | Все типы (та же логика _detect_media_type) |
| **GIF-детекция** | word-boundary checks на filepath.name | Та же логика |
| **Отключение** | Пустая строка DANGER_WORDS | OLYA_ENABLED=false |

### Файлы Epic 19

| Файл | Тип | Назначение |
|------|-----|------------|
| `filters/olya_video.py` | **CREATE** | OlyaVideoFilter: user ID + video content type + SaveAsBot detection |
| `services/olya_relay.py` | **CREATE** | OlyaRelay: plain send media, cooldown, reuse media-type logic |
| `handlers/olya.py` | **CREATE** | olya_router + olya_handler |
| `config/settings.py` | MODIFY | +7 OLYA_* полей в Settings dataclass |
| `.env.example` | MODIFY | +7 OLYA_* параметров с описаниями |
| `bot.py` | MODIFY | import olya_router, регистрация на позиции 4d, инициализация OlyaRelay |
| `tests/test_olya.py` | **CREATE** | ~15-20 тестов: фильтр, сервис, хендлер, cooldown, corner cases |

### Медиа-директория

```
media/olya/cringe/
├── olya_cringe_01.mp4    (существует)
└── (дополнительные файлы добавляются по мере необходимости)
```

### Review Fixes (6 issues — 3 HIGH, 2 MEDIUM, 1 LOW)

| Priority | ID | Описание | Компонент | Статус |
|----------|----|----------|-----------|--------|
| **HIGH** | 1 | UNHANDLED propagation — olya_handler теперь возвращает UNHANDLED для event flow к slavik_router | `handlers/olya.py` | ✅ FIXED |
| **HIGH** | 2 | GIF false-positive — `_detect_media_type()` использует filepath.name word-boundary, не .stem | `services/olya_relay.py` | ✅ FIXED |
| **HIGH** | 3 | Silent exceptions — добавлен per-entry OSError handling с WARNING logging в `_scan_directory()` | `services/olya_relay.py` | ✅ FIXED |
| **MEDIUM** | 1 | OSError в scan — каждый os.scandir() entry обёрнут в try/except OSError | `services/olya_relay.py` | ✅ FIXED |
| **MEDIUM** | 2 | Test assertion mismatch — исправлены expected values для plain send (без ReplyParameters) | `tests/test_olya.py` | ✅ FIXED |
| **LOW** | 1 | README metrics — обновлён с Olya Service описанием, конфигом и позицией роутера | `README.md` | ✅ FIXED |

### Risky Check Items — Resolved

| RC | Описание | Статус |
|----|----------|--------|
| RC1 | OlyaVideoFilter не конфликтует с common_router — оба могут срабатывать на одном сообщении, UNHANDLED propagation обеспечивает | ✅ Resolved |
| RC2 | Plain send без reply — send_photo/send_video/send_animation работают без reply_parameters | ✅ Resolved |
| RC3 | Video content type filter — корректно обрабатывает и native video, и репосты | ✅ Resolved |
| RC4 | OLYA_MEDIA_TYPE=photo поддержка — добавлен F.content_type == ContentType.PHOTO в фильтр | ✅ Resolved |
| RC5 | Cooldown per-chat реализован — OlyaRelay использует time.monotonic() с dict[chat_id] | ✅ Resolved |
| RC6 | OlyaRelay gracefully обрабатывает пустую директорию — WARNING log + return False | ✅ Resolved |

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
| Тесты | pytest + pytest-asyncio | ✅ 509 тестов PASS (v2.17.0 implemented) |
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
4c. common_router — F9/F10: otboy_handler + danger_handler (ALL users, DUAL cooldown: common + danger-specific)
4d. olya_router — F11: Olya video trigger (user_id=834424825) + plain send media from media/olya/cringe/
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
| **F9** | Otboy Service — детект "отбой" (все пользователи) → common/otboy/ media | `handlers/common.py` (`otboy_handler`) + `CommonRelay` | ✅ v2.15.0 |
| **F10** | Danger Detection — 135+ keywords (единый DANGER_WORDS из word_lists.py) | `handlers/common.py` (`danger_handler`) + `DangerWordFilter` + `CommonRelay` (dual-layer cooldown, word-boundary GIF detection, per-entry OSError handling) | ✅ v2.16.0 |
| **F11** | Olya Service — видео от @ole4444444ka → случайный cringe media, plain send | `handlers/olya.py` + `OlyaRelay` + `OlyaVideoFilter` | ✅ v2.17.0 |

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
| `DANGER_COOLDOWN_SECONDS` | `60.0` | F10: danger-specific cooldown (dual-layer: common + danger). Не влияет на otboy. 0=off. ✅ v2.16.0 |
| `COMMON_MEDIA_BASE` | `media/common` | F9/F10: base directory for common/otboy/ and common/danger/ |
| `DANGER_WORDS` | `(135+ keywords)` | F10: comma-separated danger keywords (единый источник: filters/word_lists.py) |
| `OLYA_ENABLED` | `True` | F11: enable/disable Olya Service (0=off) |
| `OLYA_USER_ID` | `834424825` | F11: Olya's Telegram user ID (@ole4444444ka) |
| `OLYA_COOLDOWN_SECONDS` | `60.0` | F11: cooldown between Olya media sends (0=off) |
| `OLYA_MEDIA_BASE` | `media/olya/cringe` | F11: media directory for Olya cringe files |
| `OLYA_CAPTION_TEXT` | `(SaveAsBot text)` | F11: key caption text for Condition A detection |
| `OLYA_SAVEASBOT_CHANNEL_IDS` | `523131145` | F11: channel IDs for SaveAsBot repost detection |
| `OLYA_ALWAYS_SEND` | `True` | F11: always send media regardless of caption/repost match |

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

## ✅ Epic 18: Danger Service Fixes — v2.15.0 → v2.16.0 (DEPLOYED, 2026-08-02)

> **Цель:** Исправить 3 бага в CommonRelay/Danger service — file scanning robustness, GIF detection, dual cooldown.
> **Статус:** DEPLOYED ✅ — все 3 бага FIXED и в продакшене. Full multi-agent цикл: Architect → Builder → Reviewer → Memory → DevOps.
> **Версия:** v2.16.0 (deployed). Commit: `c4694c0`.

### 3 Бага — ВСЕ FIXED

| Bug | Название | Описание | Компонент | Статус |
|-----|----------|----------|-----------|--------|
| **A** | File scanning robustness | Per-entry OSError handling + INFO-level file logging | `services/common_relay.py::_scan_directory()` | ✅ FIXED |
| **B** | GIF detection fix | `filepath.name` + word-boundary checks (`_gif`, `gif`, `.gif`) | `services/common_relay.py::_detect_media_type()` | ✅ FIXED |
| **C** | Dual cooldown | `DANGER_COOLDOWN_SECONDS` (60.0) — danger-specific cooldown, otboy excluded | `services/common_relay.py`, `config/settings.py`, `bot.py` | ✅ FIXED |

### Bug A: File Scanning Robustness — FIXED

```
Проблема: os.scandir() выбрасывает OSError на отдельных entries
(permission denied, corrupted filesystem) → весь _scan_directory() падал.

Решение: try/except OSError вокруг каждого entry в цикле os.scandir().
Одна ошибка не ломает весь скан. + INFO-лог каждого файла.

Реализация:
  for entry in os.scandir(scan_dir):
      try:
          if entry.is_file():
              filepath = Path(entry.path)
              logger.info("Scanned file in %s: %s (%d bytes)", subdir, filepath.name, filepath.stat().st_size)
              files.append(filepath)
      except OSError as e:
          logger.warning("Skipping unreadable entry in %s: %s", subdir, e)
```

### Bug B: GIF Detection Fix — FIXED

```
Проблема: _detect_media_type() использовала filepath.stem для проверки 'gif'.
Файл danger_02_gif.mp4 → stem='danger_02_gif' → но старая проверка
не матчила → отправлялся как video вместо animation.

Решение: Использовать filepath.name (полное имя) с 3 word-boundary проверками:
  1. '_gif' in name    — подчёркивание перед gif
  2. name.startswith('gif')  — начинается с gif
  3. '.gif' in name    — расширение .gif

danger_02_gif.mp4 → name='danger_02_gif.mp4' → '_gif' in name → True → animation ✅
Все легитимные видео (без _gif маркера) → video как раньше.
```

### Bug C: Dual Cooldown — FIXED

```
Проблема: COMMON_COOLDOWN_SECONDS блокировал ВСЕ sub-services одинаково.
Не было способа задать отдельный cooldown для danger, не влияя на otboy.

Решение: DANGER_COOLDOWN_SECONDS (float, default 60.0) + два раздельных dict:
  _last_common  — общий cooldown (все sub-services)
  _last_danger  — danger-specific cooldown (только danger)

Логика send_common():
  1. Проверить общий cooldown (_last_common) — если активен, return для всех
  2. Если subdir='danger' → проверить danger cooldown (_last_danger) — если активен, return
  3. Otboy (subdir='otboy') НЕ подвержен danger cooldown

Конструктор: CommonRelay(bot, cooldown_seconds, danger_cooldown_seconds, media_base)
bot.py: CommonRelay(bot, settings.COMMON_COOLDOWN_SECONDS, settings.DANGER_COOLDOWN_SECONDS, settings.COMMON_MEDIA_BASE)
```

### Файлы Epic 18 — ВСЕ IMPLEMENTED

| Файл | Тип изменения | Задача | Статус |
|------|---------------|--------|--------|
| `services/common_relay.py` | MODIFY | Bug A (OSError handling + logging) + Bug B (word-boundary GIF detection) + Bug C (dual-layer cooldown) | ✅ IMPLEMENTED |
| `config/settings.py` | MODIFY | Bug C: `DANGER_COOLDOWN_SECONDS: float = float(os.getenv('DANGER_COOLDOWN_SECONDS', '60.0'))` | ✅ IMPLEMENTED |
| `bot.py` | MODIFY | Bug C: `CommonRelay(bot, ..., settings.DANGER_COOLDOWN_SECONDS, ...)` | ✅ IMPLEMENTED |
| `.env.example` | MODIFY | Bug C: `DANGER_COOLDOWN_SECONDS=60.0` | ✅ IMPLEMENTED |
| `tests/test_common.py` | MODIFY | Bug A, B, C: +23 теста (OSError handling, GIF detection, dual cooldown) | ✅ 124 теста |

### Architectural Decisions (D49–D51) — IMPLEMENTED

| # | Решение | Описание | Статус |
|---|---------|----------|--------|
| **D49** | Per-entry OSError handling | Оборачивать каждый entry в try/except, а не весь scandir(). Одна ошибка не ломает сервис. | ✅ IMPLEMENTED |
| **D50** | filepath.name + word-boundary GIF detection | Использовать полное имя файла (с расширением), не stem. Три word-boundary проверки исключают ложные срабатывания. | ✅ IMPLEMENTED |
| **D51** | Dual-layer cooldown (common + danger) | Два раздельных in-memory dict. Danger получает двухслойную защиту от спама, otboy — только общий cooldown. | ✅ IMPLEMENTED |

### Risky Check Items — Resolved

| RC | Описание | Статус |
|----|----------|--------|
| RC1 | Изменение конструктора CommonRelay ломает bot.py? | ✅ Resolved — `bot.py` обновлён, 478 тестов проходят. |
| RC2 | GIF detection может дать ложный negative на легитимных видео? | ✅ Resolved — word-boundary проверки (`_gif`, `.gif`, `startswith('gif')`) проверены. Обычные имена видео не матчатся. |
| RC3 | Danger cooldown может блокировать легитимные danger-сообщения? | ✅ Resolved — 60s default, env-configurable. 0 = отключено. Dual-layer логика проверена тестами. |

### Test Suite (478 total)

| Area | Count | Delta |
|------|-------|-------|
| Baseline (Epic 17 + v2.15.0) | 458 | — |
| Epic 18: Bug A, B, C tests | +20 | test_common.py: 124 total (101 baseline + 23 new Epic 18) |
| **Total** | **478** | **+20 net** |

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
| v2.13.0 | 2026-07-30 | Epic 17 (Danger Word Fix) | T2–T4 | 399 |
| v2.15.0 | 2026-08-02 | 4 Major Fixes (propagation, mimic v2, slavik random media, dead_page relay) | — | 458 |
| **v2.16.0** | **2026-08-02** | **Epic 18 (Danger Service Fixes)** | **A/B/C** | **478** |
| **v2.17.0** | **2026-08-02** | **Epic 19 (Olya Service)** 🟢 | **T-131–T-138** | **509** |

---

### Sprint Status

| Status | Tasks |
|--------|-------|
| **Done** | T-001 – T-115 + T2/T3/T4 + v2.15.0 fixes + Epic 18 A/B/C (DEPLOYED across 18 Epics) ✅ |
| **Done** | Epic 19: T-131 – T-138 (IMPLEMENTED and APPROVED, ready for deploy) 🟢 |
| **Pending** | Epic 19: T-138 (Deploy to server) 🔵 |

> Epics 1-18 DEPLOYED ✅. Epic 19 (Olya Service) IMPLEMENTED — approved by Reviewer, ready for deployment.
> 509 тестов, 11 роутеров, 5 таблиц БД, Sentry + Logtail мониторинг. Commit: c4694c0.
> 19 Epic'ов: 18 deployed + 1 implemented and approved. Ноль известных багов.

---

## 🚀 Deployment Details

| Параметр | Значение |
|----------|----------|
| **Версия в проде** | v2.16.0 (deployed) |
| **Следующая версия** | v2.17.0 (Epic 19 — Olya Service, IMPLEMENTED — READY FOR DEPLOY) |
| **Текущий коммит** | `c4694c0` (v2.16.0 deployed) |
| **Дата** | 2026-08-02 |
| **Сервер** | nik@198.46.175.136 |
| **Путь** | /var/www/admin_bot |
| **Статус** | systemctl status adminbot → active (running), PID 694761, memory 140.1M |
| **Git remote** | origin/master — pushed успешно |
| **Тесты** | 509 PASS (все зелёные) |
| **Эпики** | 1-18 DEPLOYED ✅, 19 IMPLEMENTED ✅ (READY FOR DEPLOY) |
| **Задачи** | T-001 – T-115 + T2/T3/T4 + v2.15.0 fixes + Epic 18 A/B/C (DEPLOYED), T-131–T-138 (IMPLEMENTED) |
| **Ошибки** | 0 errors в логах. Все сервисы инициализированы корректно. |

---

*Обновление: 2026-08-02 — EPIC 19 STATUS: IMPLEMENTED ✅. Olya Service полностью реализован и одобрен Reviewer-ом. 4 новых файла (filters/olya_video.py, services/olya_relay.py, handlers/olya.py, tests/test_olya.py), 4 изменённых (config/settings.py, bot.py, .env.example, README.md). 31 новый тест (+ 6 review fixes). Все 509 тестов проходят. 6 review issues исправлено (3 HIGH: UNHANDLED propagation, GIF false-positive, silent exceptions; 2 MEDIUM: OSError in scan, test assertion; 1 LOW: README metrics). Knowledge Graph синхронизирован: Epic-19-Olya-Service статус IMPLEMENTED, создан OlyaReviewFixes, все задачи T-131–T-136 статус IMPLEMENTED, T-138 статус READY FOR DEPLOY. MEMORY.md обновлён — Epic 19 статус DESIGNED → IMPLEMENTED. Готово к деплою на сервер.*