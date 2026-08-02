# MEMORY.md — AdminBot

> **Версия:** v2.18.0 (DEPLOYED, Epic 20)
> **Дата:** 2026-08-02
> **Статус:** ВСЕ 20 Epic'ов DEPLOYED ✅. 570 тестов PASS. Бот активен в продакшене.
> **Текущий коммит:** `242cbac` (v2.18.0 deployed), master branch.
> **Сервер:** nik@198.46.175.136:/var/www/admin_bot, systemctl active (running), 0 errors.

---

## 🔍 Context Sync Summary (2026-08-02) — Epic 20 FINAL SYNC (DEPLOYED)

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-20** | ✅ DEPLOYED | 130+ задач T-001–T-115 + T2/T3/T4 + Epic 18 A/B/C + Epic 19 T-131–T-138 + Epic 20 T-139–T-148. v2.18.0 в продакшене. |
| **Epic 20** | ✅ DEPLOYED | Slavik Random Media Enhancement — DEPLOYED. Commit 242cbac. 570 тестов. 6 media types. |
| **Review** | ✅ PASS | 570 tests pass. Zero regressions. |
| **Сервер** | ✅ ACTIVE | nik@198.46.175.136:/var/www/admin_bot. systemctl: active (running). Git pull успешен. Commit 242cbac. |

---

## ✅ Epic 19: Olya Service — v2.17.0 (DEPLOYED, 2026-08-02)

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
| **T-138** | Деплой на сервер, коммит, пуш, рестарт | DevOps | ✅ DEPLOYED (f57add4, 2026-08-02) |

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

## ✅ Epic 20: Slavik Random Media Enhancement — v2.18.0 (DEPLOYED, 2026-08-02)

> **Цель:** Расширить поддержку медиа-типов в slavik random media picker до полного паритета с CommonRelay.
> **Статус:** DEPLOYED ✅ — все 10 задач T-139–T-148 выполнены и задеплоены. 570 тестов проходят. Бот активен.
> **Версия:** v2.18.0 (deployed). Commit: `242cbac`. Pushed to origin/master.
> **Deploy:** Server nik@198.46.175.136:/var/www/admin_bot. Git pull → systemctl status active (running).

### Overview

Epic 20 расширяет `handlers/slavik.py` с 3 до 6 поддерживаемых медиа-типов: photo, video, animation, **audio**, **voice**, **document**. Документ служит универсальным fallback-ом для любых неподдерживаемых форматов (PDF, MKV, ZIP и т.д.). GIF-детекция усилена word-boundary проверками (паритет с CommonRelay Epic 18 fix).

### Ключевые ограничения

| Ограничение | Детали |
|-------------|--------|
| **Scope** | Только `handlers/slavik.py` — 3 приватные функции |
| **Новые файлы** | ❌ Ни одного |
| **Изменения роутера** | ❌ Позиция, фильтры, хэндлеры — без изменений |
| **Изменения БД** | ❌ `slavic_photo_count_tick` не меняется |
| **Изменения конфига** | ❌ Никаких новых env-переменных |
| **Reply behaviour** | ❌ Уже корректно — `message.answer_*` делает reply без quote |

### Design Decisions (D49–D53)

| # | Решение | Описание |
|---|---------|----------|
| **D49** | Reply без quote — CONFIRMED | `message.answer_*()` методы уже делают auto-reply без quote. Менять ничего не надо. |
| **D50** | Media type parity | Расширение с 3 до 6 типов: +audio (.mp3), +voice (.ogg), +document (всё остальное) |
| **D51** | GIF detection hardened | `filepath.stem` → `filepath.name` с 3 word-boundary проверками (`_gif`, `startswith("gif")`, `.gif.`) |
| **D52** | Document fallback | `_detect_slavik_media_type()` всегда возвращает `str` (не `str\|None`). Любой файл отправляется как document. |
| **D53** | Code scope | Только 3 функции в 1 файле. ~30 строк изменений. |

### Media Type Matrix (после Epic 20)

| Расширение | Условие | Тип | Send метод |
|-----------|---------|-----|-----------|
| `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp` | — | `photo` | `answer_photo` |
| `.mp4`, `.mov`, `.webm` | нет "gif" в имени | `video` | `answer_video` |
| `.mp4`, `.mov`, `.webm` | есть "gif" (word-boundary) | `animation` | `answer_animation` |
| `.mp3` | — | `audio` | `answer_audio` |
| `.ogg` | — | `voice` | `answer_voice` |
| всё остальное | — | `document` | `answer_document` |

### Задачи Epic 20

| Task | Название | Компонент | Статус |
|------|----------|-----------|--------|
| **T-139** | Архитектурное проектирование | `plans/ARCHITECTURE.md` Section 28 | ✅ IMPLEMENTED |
| **T-140** | Расширить `_detect_slavik_media_type()` — audio, voice, document | `handlers/slavik.py` | ✅ IMPLEMENTED |
| **T-141** | Усилить GIF-детекцию — `filepath.stem` → `filepath.name` + word-boundary | `handlers/slavik.py` | ✅ IMPLEMENTED |
| **T-142** | Реализовать document fallback (всегда возвращать str) | `handlers/slavik.py` | ✅ IMPLEMENTED |
| **T-143** | Добавить audio/voice/document send-ветки в `_send_slavik_media()` | `handlers/slavik.py` | ✅ IMPLEMENTED |
| **T-144** | Per-entry OSError handling + INFO-лог в `_pick_random_slavik_media()` | `handlers/slavik.py` | ✅ IMPLEMENTED |
| **T-145** | Unit-тесты `_detect_slavik_media_type` — новые типы + GIF + регрессия | `tests/` | ✅ IMPLEMENTED |
| **T-146** | Unit-тесты `_send_slavik_media` — 6 send-методов | `tests/` | ✅ IMPLEMENTED |
| **T-147** | Unit-тесты `_pick_random_slavik_media` — document fallback + OSError | `tests/` | ✅ IMPLEMENTED |
| **T-148** | Синхронизация документации (MEMORY.md, board.md, backlog.md) | `plans/` | ✅ IMPLEMENTED |

### Функции для изменения

| Функция | Текущее поведение | Новое поведение |
|---------|-------------------|-----------------|
| `_detect_slavik_media_type(filepath) → str\|None` | 3 типа, `None` для unsupported | **6 типов**, всегда `str` (document fallback) |
| `_send_slavik_media(message, filepath, media_type)` | 3 send-ветки + хрупкий `else → answer_photo` | **6 send-веток**, убран хрупкий fallback |
| `_pick_random_slavik_media() → tuple\|None` | Фильтрует `media_type is not None`, нет OSError-handling | **Включает все файлы**, per-entry OSError try/except, INFO-лог |

### Тест-план (~31 тест)

| Категория | Количество | Описание |
|-----------|-----------|----------|
| Новые типы (audio/voice/document) | 7 тестов | .mp3, .ogg, .pdf, .mkv, .zip, без расширения, .txt |
| GIF-детекция (hardened) | 6 тестов | _gif, gif-prefix, .gif., gift != gif, обычное видео |
| Регрессия (существующие типы) | 8 тестов | photo (.jpg/.png/.webp/.bmp), video (.mp4/.mov/.webm), animation (.webm+gif) |
| Новые send-методы | 6 тестов | answer_photo, answer_video, answer_animation, answer_audio, answer_voice, answer_document |
| Document fallback | 3 теста | mix типов, только .pdf, .txt |
| Per-entry OSError | 1 тест | битый файл + нормальный |
| **Total** | **~31** | **509 baseline → ~540** |

### Риски

| Риск | Вероятность | Влияние | Митигация |
|------|-----------|---------|-----------|
| `answer_document()` не поддерживается старой версией aiogram | Низкая | Высокое | aiogram 3.29.1 (используется) поддерживает с 3.0 |
| Файлы без расширения падают при отправке | Низкая | Среднее | `FSInputFile` + `answer_document` обрабатывает любые файлы |
| Изменение сигнатуры ломает неучтённых вызывателей | Низкая | Низкое | Приватная функция, один caller в том же файле |
| GIF-детекция пропускает edge-case имена | Низкая | Среднее | Правила идентичны CommonRelay (Epic 18 verified) |

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
| **v2.17.0** | **2026-08-02** | **Epic 19 (Olya Service)** ✅ | **T-131–T-138** | **509** |
| **v2.18.0** | **2026-08-02** | **Epic 20 (Slavik Random Media Enhancement)** ✅ | **T-139–T-148** | **570** |

---

### Sprint Status

| Status | Tasks |
|--------|-------|
| **DEPLOYED** | T-001 – T-115 + T2/T3/T4 + v2.15.0 fixes + Epic 18 A/B/C (DEPLOYED across 18 Epics) ✅ |
| **DEPLOYED** | Epic 19: T-131 – T-138 (DEPLOYED to production, commit f57add4) ✅ |
| **DEPLOYED** | Epic 20: T-139 – T-148 (Slavik Random Media Enhancement — DEPLOYED, commit 242cbac, 570 tests) ✅ |

> Epics 1-20 DEPLOYED ✅. Проект PRODUCTION-READY v2.18.0. ФИНАЛЬНЫЙ СТАТУС: все Epic'ы завершены и задеплоены.
> 570 тестов. 11 роутеров, 5 таблиц БД, Sentry + Logtail мониторинг.
> Ноль известных багов. Все сервисы инициализированы корректно. Бот активен.

---

## 🚀 Deployment Details

| Параметр | Значение |
|----------|----------|
| **Версия в проде** | v2.18.0 (deployed) |
| **Следующая версия** | — (проект завершён, все 20 Epic'ов задеплоены) |
| **Текущий коммит** | `242cbac` (v2.18.0 deployed) — Epic 20 Slavik Random Media Enhancement |
| **Дата** | 2026-08-02 |
| **Сервер** | nik@198.46.175.136 |
| **Путь** | /var/www/admin_bot |
| **Статус** | systemctl status adminbot → active (running), 0 errors |
| **Git remote** | origin/master — pushed успешно |
| **Тесты** | 570 PASS (все зелёные) |
| **Эпики** | 1-20 DEPLOYED ✅. ФИНАЛЬНЫЙ СТАТУС. |
| **Задачи** | T-001 – T-115 + T2/T3/T4 + v2.15.0 fixes + Epic 18 A/B/C + Epic 19 T-131–T-138 + Epic 20 T-139–T-148 (ALL DEPLOYED) |
| **Ошибки** | 0 errors в логах. Все сервисы инициализированы корректно. |

---

*Обновление: 2026-08-02 — EPIC 20 STATUS: DEPLOYED ✅. Slavik Random Media Enhancement задеплоен в production. Scope: только handlers/slavik.py (3 функции) + tests/test_slavik_media_types.py (новый, 61 тест). 570 тестов проходят. 6 медиа-типов (photo/video/animation/audio/voice/document), document как универсальный fallback, GIF-детекция hardened (filepath.name + word-boundary). Никаких изменений роутеров, БД или конфигурации. Deployment: commit 242cbac на ветке master, пуш в origin/master, git pull на сервере nik@198.46.175.136:/var/www/admin_bot успешен. systemctl status adminbot → active (running). Все 20 Epic'ов (T-001–T-148 + T2/T3/T4 + fixes) COMPLETE и DEPLOYED. Проект в продакшене v2.18.0. ФИНАЛЬНЫЙ СТАТУС.*