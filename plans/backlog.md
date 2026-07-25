# AdminBot — Product Backlog

## Epic 1: Рефакторинг (Code Quality)
- [x] T-001: Вынести API_TOKEN в .env / конфигурацию
- [x] T-002: Создать requirements.txt с закреплёнными версиями (aiogram, python-dotenv, aiosqlite)
- [x] T-003: Создать единую структуру проекта (config/, handlers/, services/, tests/)
- [x] T-004: Унифицировать обработку ошибок и логирование
- [x] T-005: Создать общий базовый класс для фильтров

## Epic 2: Новые функции
- [x] T-006 (slavik): При возвращении Славы в чат → "ДОЛБОЕБ ВЕРНУЛСЯ"
- [x] T-007 (slavik): Dead-page посты — рандомное фото + рандомный текст из media/dead-page. При входе сразу, если присутствует — 2 раза/сутки
- [x] T-008 (slavik): Каждые 5 сообщений → гифка (mp4 как GIF без звука) из media/
- [x] T-009 (slavik): На «КУЧА/Куча/Кучи» → "ДАЛБАЕБ" с цитированием слова
- [x] T-010 (slavik): На военные слова (летит, дрон, вспышка, прилет, укрытие, бункер, ракета + синонимы) → "трясло ебаное" с цитированием (ТОЛЬКО для Славы)
- [x] T-011 (alan): Каждые 10 сообщений от @Alan_Z (id 138811255) → reply random-фразой про тренировки/лонгковид/фьючерсы/нейросети/жим дьявола

## Epic 3: Тестирование и CI
- [x] T-012: Написать модульные тесты на ВСЕ хендлеры
- [x] T-013: Написать тесты на все корнер-кейсы (пустой текст, нецелевой пользователь, границы счётчиков)
- [x] T-014: Написать интеграционные тесты (полный пайплайн сообщения)

## Epic 4: Документация
- [x] T-015: README.md с ироничной документацией (установка, запуск, описание функций)

## Epic 5: Багфиксы и рефакторинг (2026-07-07)
- [x] T-016 (kostik): Рефакторинг — probability-based reply + extensible reply pool
- [x] T-017 (kucha): Fix KuchaWordFilter regex — удалён ложный «ек» из опциональной группы

---

## Epic 6: Dead Page V2 — Event-driven reposts (2026-07-11)

> **Цель:** Перевести dead-page с time-based расписания (morning/evening) на event-driven:
> репост из @d_pages → forward случайного поста из приватного канала 4228645624
> (бот — админ), с fallback на локальный `media/dead_page/`.

### Конфигурация и планирование
- [x] T-018: Обновить `config/settings.py` + `.env.example` — добавить новые параметры (DEAD_PAGE_CHANNEL_ID, DEAD_PAGE_SOURCE_USERNAME, DEAD_PAGE_POST_ON_JOIN, DEAD_PAGE_COOLDOWN_SECONDS, DEAD_PAGE_MAX_FORWARD_RETRIES, DEAD_PAGE_CAPTION_MAX_CHARS), удалить MORNING_HOUR/EVENING_HOUR/POLL_INTERVAL
- [x] T-019: Обновить план `DEAD_PAGE_V2_PLAN.md` — синхронизировать с user feedback (forward вместо create+copy, канал 4228645624, fallback)

### Новые модули
- [x] T-020: Создать `services/dead_page_relay.py` — DeadPageRelay: forward случайного поста из канала + fallback на локальные медиа
- [x] T-021: Создать `handlers/dead_page_trigger.py` — Router + handler: ловит forward_origin типа MessageOriginChannel с username="d_pages", вызывает DeadPageRelay

### Рефакторинг существующего кода
- [x] T-022: Упростить `services/scheduler.py` — убрать `while True` loop, `_tick`, morning/evening логику. Оставить только `signal_immediate_post` с проверкой `DEAD_PAGE_POST_ON_JOIN`
- [x] T-023: Добавить миграцию БД — новая таблица `channel_state`, колонка `timestamp` в `dead_page_posts`, новые методы `was_dead_page_recently`, `record_dead_page_post`, `get_last_known_message_id`, `update_last_known_message_id`

### Интеграция
- [x] T-024: Обновить `bot.py` — зарегистрировать `dead_page_router` (позиция 4 между alan и slavik), инициализировать `DeadPageRelay`, подключить relay к `slava_presence`
- [x] T-025: Добавить comprehensive logging во все dead_page модули (relay, trigger, scheduler, database)

### Документация и тесты
- [x] T-026: Обновить `MEMORY.md` и `ARCHITECTURE.md` — отразить новую архитектуру, слоты БД, router order, F2 v2
- [x] T-027: Написать/переписать тесты — `test_dead_page_relay.py`, `test_dead_page_trigger.py`, удалить/переписать `test_scheduler.py`, обновить `test_database.py`
- [x] T-028: Прогнать все тесты, убедиться что 100% новых функций покрыто, старые тесты не сломаны

---

## Epic 7: Better Stack Monitoring Integration (2026-07-12) ✅ DONE

> **Цель:** Интегрировать Sentry (error tracking) и Logtail (log aggregation) от Better Stack
> для production-grade мониторинга бота.

### Подготовка окружения
- [x] T-029: Добавить sentry-sdk==2.64.0 и logtail-python==0.4.0 в requirements.txt
- [x] T-030: Установить sentry-sdk и logtail-python в venv проекта
- [x] T-031: Добавить SENTRY_DSN и LOGTAIL_SOURCE_TOKEN в .env.example
- [x] T-032: Добавить SENTRY_DSN и LOGTAIL_SOURCE_TOKEN в .env

### Интеграция в код
- [x] T-033: Инициализировать Sentry SDK в bot.py (traces_sample_rate=1.0)
- [x] T-034: Настроить LogtailHandler на root logger (dual-output: консоль + облако)

### Верификация
- [x] T-035: Написать и запустить smoke test — тестовый лог + тестовая ошибка в облако
- [x] T-036: Запустить существующий тестовый suite (pytest), убедиться что ничего не сломалось

### Документация
- [x] T-037: Обновить ARCHITECTURE.md — добавить секцию мониторинга (@Architect)

---

## Epic 8: Alan Greeting Video (F7) — 2026-07-13 ✅ DONE

> **Цель:** Когда пользователь Alan (ID 138811255, @Alan_Z) заходит в чат, бот отправляет
> случайное видео из `media/leha_greeting/` с тегом @Alan_Z в подписи.

### Конфигурация
- [x] T-038: Добавить `ALAN_USERNAME`, `ALAN_USER_ID` и `ALAN_GREETING_DIR` в `config/settings.py` + `.env.example`

### Хендлер
- [x] T-039: Создать `handlers/alan_greeting.py` — `alan_greeting_router`:
  - `ChatMemberUpdatedFilter` (IS_NOT_MEMBER → IS_MEMBER) + `new_chat_members` fallback
  - Рандомное видео из `media/leha_greeting/` → `send_video`
  - Caption: `@Alan_Z`
  - Comprehensive logging

### Интеграция
- [x] T-040: Зарегистрировать `alan_greeting_router` в `bot.py` (позиция 1b, рядом с `slava_presence_router`)

### Тестирование
- [x] T-041: Написать `tests/test_alan_greeting.py` (7-8 тестов)

### Документация
- [x] T-042: Обновить `ARCHITECTURE.md` (F7 data flow, router order, directory listing)
- [x] T-043: Обновить `MEMORY.md` (project state, features table)

### QA
- [x] T-044: Прогнать все тесты, убедиться в отсутствии регрессий
- [x] T-045: Code review и QA

---

## Багфиксы (2026-07-13 – 2026-07-15) ✅ DONE

- [x] T-046: БАГФИКС: Dead Page Relay — ALL RANGES EXHAUSTED (Critical)
  - Исправлен `_build_search_ranges()` в `services/dead_page_relay.py`: добавлен `_DISCOVERY_RANGES` как fallback.
  - Исправлен `continue` dedup — не сжигает слоты попыток.
  - Добавлен WARNING-лог при входе в fallback `_DISCOVERY_RANGES`.

- [x] T-047: БАГФИКС: Alan Greeting Video — сервис никогда не срабатывает (High)
  - Подняты diagnostic-логи c DEBUG до INFO уровня в `handlers/alan_greeting.py`.
  - Добавлен уникальный lambda-фильтр `event.new_chat_member.user.id == settings.ALAN_USER_ID`.
  - Написан интеграционный тест с обоими роутерами на одном dispatcher.

- [x] T-052: БАГФИКС: Dead Page Relay — sequential scanning для sparse channels (Critical)
  - Добавлен sequential scanning для narrow ranges (≤ 50 ID).
  - При `hi - lo <= 50` переключается на линейное сканирование ID.
  - Логирование: INFO при sequential mode, INFO при hit.

- [x] T-053: БАГФИКС: Propagation-stopping bug в slava_presence.py — F7 Alan greeting полностью сломана в production (Critical)
  - Fix 1: Возврат `UNHANDLED` из хендлеров slava_presence.py (on_user_join, on_user_leave, on_new_slava_member).
  - Fix 2: Убрана избыточная проверка user ID в alan_greeting.py.
  - Fix 3: Интеграционный тест с реальной диспетчеризацией через Dispatcher.
  - Fix 4: НЕ РЕАЛИЗОВАН (UserIdFilter на уровне декоратора — не нужен, Fix 1 работает).

---

## Epic 9: Admin Test Commands (2026-07-14) ✅ DONE

> **Цель:** Добавить команды Telegram для ручного тестирования фич админом.
> Первый в проекте command handler и первый опыт удаления сообщений ботом.

### Конфигурация
- [x] T-048: Admin test command для dead_page_relay (`/deadpage`)
  - `config/settings.py` + `.env.example`: `ADMIN_USER_ID=5885953495`
  - Создан `handlers/admin_commands.py` — `admin_router: Router`
  - `Command("deadpage")` filter
  - DM: работает для любого пользователя
  - Группы: только админ (`ADMIN_USER_ID`)
  - `await message.delete()` — удаление команды из чата
  - Основная логика: `await relay.send_dead_page(chat_id, slot="manual")`
  - Comprehensive logging

- [x] T-049: Admin test command для alan_greeting (`/alangreet`)
  - Добавлен handler в `handlers/admin_commands.py` (тот же роутер)
  - `Command("alangreet")` filter
  - DM: любой пользователь. Группы: админ только.
  - `await message.delete()`
  - Логика: `_send_greeting` из `handlers.alan_greeting`

### Верификация
- [x] T-050: Прогнать тест-сьют pytest, убедиться в отсутствии регрессий
- [x] T-051: Написать тесты на admin_commands (6 тестов: DM deadpage, DM alangreet, группа админ, группа не-админ, DM delete error, группа delete error)

---

## Epic 10: War Words Redesign (F5v2) — 2026-07-16 🔵 PLANNING

> **Цель:** Переработать F5 (War Words) — исправить баг с caption (фильтр пропускает
> текст в подписях к медиа/форвардам), расширить словарь ключевых слов, добавить
> детекцию репостов из военных Telegram-каналов, заменить одиночный хардкод-ответ
> на рандомный пул фраз, обеспечить детальное Better Stack логирование и 100% тестовое
> покрытие.
>
> **Контекст:** Текущий WarWordFilter проверяет только `message.text`, пропуская
> `message.caption` (форварды с медиа несут текст в caption). Ключевых слов всего 27 форм
> в 8 корнях. Ответ один: "трясло ебаное". Нет детекции репостов из каналов.
> В проекте уже есть паттерны для решения: dead_page_trigger.py (forward_origin + channel ID)
> и alan.py (рандомный пул reply + random.choice).

### Bugfix: Caption support + keyword expansion
- [ ] T-054: Fix WarWordFilter — caption support + expand keywords
  - **Bug:** `__call__` проверяет только `message.text`, пропускает `message.caption`
  - **Fix:** Проверять `message.text or message.caption` (оба поля)
  - **Keyword expansion:** Добавить слова и словоформы (существующие 27 форм + новые):
    - `опасность`, `опасности`, `опасность` — danger
    - `БПЛА` — UAV (Russian acronym; case-insensitive match)
    - `ракета`, `ракеты`, `ракет`, `ракете`, `ракетная`, `ракетной`, `ракетную`, `ракетные` — missile
    - `укрытие`, `укрытия`, `укрытии`, `укрытий` — shelter
    - `убежище`, `убежища`, `убежищу`, `убежищем` — refuge
    - `бункер`, `бункера`, `бункере`, `бункеров` — bunker
    - `внимание` — attention/alert
    - `беспилотной`, `беспилотная`, `беспилотные`, `беспилотник`, `беспилотники` — UAV/drone
    - `оповещение`, `оповещения`, `оповещении` — notification/alert
  - **Architecture:** Добавить слова в `WAR_WORDS` list, паттерны пересобираются автоматически
  - **File:** `filters/war_word.py`

### Channel repost detection
- [ ] T-055: Add channel repost detection handler for military channels
  - **Pattern:** Использовать существующий шаблон из `handlers/dead_page_trigger.py`:
    `F.forward_origin` → `isinstance(origin, MessageOriginChannel)` → check `origin.chat.id`
  - **Target channels:**
    - Channel ID 1654872411 ("ЧП Пермь")
    - "Радар по всей России | БПЛА" (ID TBD, match by username)
  - **Detection:** И по ID, и по username (как dead_page_trigger делает двойную проверку)
  - **Filter:** `UserIdFilter(settings.SLAVIK_USER_ID)` — только сообщения Славы
  - **Reply:** Случайная фраза из пула (T-056) через `message.reply()`
  - **Handler priority:** Router зарегистрирован перед slavik_router (T-060), чтобы репост-детекция срабатывала до catch-all
  - **File:** `handlers/war_words_trigger.py` — новый файл

### Random reply pool
- [ ] T-056: Create random reply pool + `random.choice()` logic
  - **Current:** Одиночный хардкод `"трясло ебаное"` в `war_word_handler`
  - **New:** Extensible reply pool в виде списка строк
  - **Initial pool (5 phrases):**
    1. `"потрясись"`
    2. `"повизжи"`
    3. `"прячься под шконку быстрее"`
    4. `"закрой ушки и считай до десяти"`
    5. `"поплачь"`
  - **Selection:** `random.choice(WAR_REPLIES)` — как в `ALAN_REPLIES` в handlers/alan.py
  - **Extensibility:** Добавление новой фразы = новая строка в списке
  - **Backward compatibility:** Старый `"трясло ебаное"` убран
  - **Reply mechanism:** `await message.reply(reply_text)` — reply_to mechanism

### Logging
- [ ] T-057: Add comprehensive Better Stack logging
  - **Levels:**
    - `INFO`: keyword matched, channel repost detected, reply sent
    - `WARNING`: filter miss (caption empty, origin not channel)
    - `ERROR`: handler failures
  - **Context per log:** chat_id, user_id, matched keyword, channel source, chosen reply text
  - **Files to instrument:** `filters/war_word.py`, `handlers/war_alert.py`

### Testing
- [ ] T-058: Create/extend tests — filter, handler, integration
  - **Filter tests** (`tests/test_war_word_filter.py` — новый файл, ~12 tests):
    - text-only match, caption match, empty text + empty caption, caption-only match
    - all new keyword forms, case insensitivity, word boundary test
    - non-Slava user with war word
  - **Handler tests** (`tests/test_war_alert.py` — обновить, ~6 tests):
    - war word keyword → random reply from pool
    - verify `message.reply()` called, verify randomness (10x)
    - no war word + Slava → catch-all "пошёл нахуй"
    - no war word + non-Slava → no reply
  - **Channel repost handler tests** (`tests/test_war_words_trigger.py` — новый файл, ~10 tests):
    - forward from target channel ID → reply triggered
    - forward from target channel username → reply triggered
    - forward from non-target channel → no reply
    - forward from user (not channel) → no reply
    - non-forward message → no reply
    - non-Slava forward from target → no reply
    - verify `message.reply()` called with reply from pool
    - empty caption → still triggers (channel match, not keyword match)

### Configuration
- [ ] T-059: Update `config/settings.py` with new env vars + `.env.example`
  - `WAR_CHANNEL_IDS`: list[int] — ID военных каналов (default: [1654872411])
  - `WAR_CHANNEL_USERNAMES`: list[str] — usernames военных каналов (default: [])
  - `WAR_REPLIES`: list[str] — опциональный env-переопределяемый пул ответов (default: пустой — используется хардкод-пуль)

### Integration
- [ ] T-060: Register `war_alert_router` in `bot.py`
  - **Position:** Между dead_page_router (#4) и slavik_router (#5)
  - **Actual position:** 4b в router order
  - **Wire-up:** `setup_war_alert()` — аналог `setup_dead_page()`

### Documentation
- [ ] T-061: Update README — document F5 v2
  - Expanded keyword list (categories: дроны, ракеты, опасность, убежища, оповещение)
  - Channel repost detection (список каналов)
  - Random reply pool (5 phrases, extensible)
  - Caption support (bugfix)

### QA & Deploy
- [ ] T-062: Run full pytest suite — verify no regressions, all new functions covered
  - Target: ~28 новых тестов (12 filter + 6 handler + 10 trigger)
  - Verify: существующие 271 тест не сломаны
- [ ] T-063: Deploy to server
  - Git pull, restart bot
  - Smoke test: send war keyword → random reply; forward from target channel → random reply
  - Verify Better Stack logs appear

---

## Epic 11: Alan Silence Greeting (F7 v2 — "Леха проснулся") — 2026-07-18 ✅ DONE

> **Цель:** Расширить F7 (Alan Greeting Video). Кроме приветствия при join-событии,
> бот должен отправлять то же самое приветственное видео, когда Алан (id 138811255)
> присутствует в чате, молчит дольше N часов, а затем пишет любое сообщение.
> N по умолчанию = 6 часов, настраивается через .env, значение 0 = функция отключена.
> На проде: N=2 часа для живого теста.
>
> **Архитектурное решение:** БД через `channel_state` (`alan_last_msg:{chat_id}`).
> Silence-логика встроена в существующий `alan_handler` (handlers/alan.py) — без нового роутера.
> Общий anti-spam через `_last_greeting` dict (совместно с F7 join).

- [x] T-064: Добавить `ALAN_SILENCE_GREETING_HOURS` в `config/settings.py` + `.env.example`, default=6.0, 0=выключено
- [x] 👤 T-065 (@Architect): Решение о хранилище — БД через channel_state (Section 22.2)
- [x] T-066: Реализовать `get_alan_last_message_ts` / `set_alan_last_message_ts` в DatabaseService
- [x] T-067: Встроить silence-логику в `alan_handler` (handlers/alan.py) — НЕ создавать новый handler/router
- [x] T-068: Логика детекта "молчал >= N часов → написал" → вызов `_send_greeting()`
- [x] T-069: Обновление таймера при КАЖДОМ сообщении Алана
- [x] T-070: Edge cases — baseline, N=0, несколько чатов, restart persistence, cooldown sharing
- [x] T-071: Детальное логирование каждого этапа (INFO/WARNING/ERROR)
- [x] T-072: Интеграция в `bot.py` — без изменения порядка роутеров (inlining в alan_handler)
- [x] T-073: Тесты (DB + handler + integration) — 19 новых тестов
- [x] T-074: Обновить README.md
- [x] T-075: Прогнать полный pytest suite — 271 тест, без регрессий
- [x] T-076: Коммит на русском (conventional commits) в main, пуш
- [x] T-077: Деплой на сервер + `ALAN_SILENCE_GREETING_HOURS=2`

---

## Epic 12: Багфикс репостов + slavic_na_litso.jpg (2026-07-25) 🔵 NEW

> **Цель:** (A) Исправить баг — war_alert не ловит forwarded-сообщения Славы с военными
> словами. (B) Добавить фичу — каждый N-й ответ "пошёл нахуй" заменять на картинку
> `slavic_na_litso.jpg` со сбросом счётчика.
>
> **Контекст:** Файл `media/slavic_na_litso.jpg` уже существует. Счётчик ответов
> "пошёл нахуй" должен быть независим от F3 GIF-счётчика (MessageCounterMiddleware).
> N настраивается через .env (по умолчанию 10).

### T-078: Расследование и исправление бага с репостами Славы (war_alert)

**Проблема:** Бот перехватывает фразы о "бпла" и "ракетах", которые пишет сам Слава,
но НЕ перехватывает его репосты (forwarded messages) и текст в этих репостах.

**Текущий код:**
- `handlers/war_alert.py` — два хендлера на одном роутере:
  1. `war_keyword_handler`: `UserIdFilter(settings.SLAVIK_USER_ID)` + `WarWordFilter()` — ловит сообщения Славы с военными словами
  2. `war_channel_repost_handler`: `F.forward_origin` — ловит репосты из целевых каналов
- `filters/war_word.py` — `WarWordFilter` проверяет `message.text or message.caption`
- `filters/user_id.py` — `UserIdFilter` проверяет `message.from_user.id`

**Гипотезы для расследования:**
1. Срабатывает ли `UserIdFilter` для forwarded-сообщений? В aiogram `message.from_user` для forwarded — это тот, кто переслал (т.е. Slava). Проверить.
2. Доступен ли `message.text` / `message.caption` для forwarded-сообщений? Проверить структуру Message в aiogram 3.x для forwarded messages.
3. Порядок вызова хендлеров: оба хендлера на одном роутере. `war_channel_repost_handler` (F.forward_origin) может совпадать для forwarded-сообщений Славы и "перехватывать" их до `war_keyword_handler`. Проверить propagation и порядок.
4. Возможно ли, что `F.forward_origin` фильтр в Handler 2 останавливает обработку до Handler 1? Проверить флаг `propagation` в aiogram.

**Что нужно сделать:**
- [ ] T-078-A: Провести расследование — написать diagnostic-логи, проверить гипотезы 1-4
- [ ] T-078-B: Исправить баг (конкретный фикс зависит от результатов расследования)
- [ ] T-078-C: Добавить comprehensive logging для диагностики forwarded-сообщений

**Файлы:** `handlers/war_alert.py`, `filters/war_word.py`, `filters/user_id.py`

### T-079: Реализация фичи — картинка slavic_na_litso.jpg каждый N-й ответ "пошёл нахуй"

**Требование:**
- В папке `media/` уже есть файл `slavic_na_litso.jpg`
- Бот по сервису slavic отправляет "пошёл нахуй" в ответ на каждое сообщение Славы
- Отсчитывать, сколько раз ответ "пошёл нахуй" был отправлен
- На N-й раз (по умолчанию 10) вместо текста отправлять картинку `slavic_na_litso.jpg`
- После отправки картинки счётчик сбрасывается, и дальше идут обычные "пошёл нахуй"
- Счётчик должен удобно настраиваться через конфиг (env)
- Существующая логика не должна пострадать (частота ответов та же, F3 GIF-счётчик работает независимо)

**Текущий код:**
- `handlers/slavik.py` — catch-all хендлер: `@slavik_router.message(UserIdFilter(settings.SLAVIK_USER_ID))` → `"пошёл нахуй"`
- `services/message_counter.py` — `MessageCounterMiddleware` на `slavik_router`, считает сообщения и отправляет GIF каждые 5
- `config/settings.py` — `GIF_INTERVAL: int = 5`

**Реализация:**
- [ ] T-079-A: Добавить `SLIVIC_NA_LITSO_INTERVAL: int = 10` в `config/settings.py` + `.env.example`
- [ ] T-079-B: Добавить метод `increment_and_get_slavic_reply_count` в `DatabaseService` (или переиспользовать `message_counters` с отдельным user_id/key)
- [ ] T-079-C: Модифицировать `slavik_catchall_handler` в `handlers/slavik.py`:
  - После инкремента счётчика: если `count % INTERVAL == 0` → `send_photo(slavic_na_litso.jpg)` вместо `reply("пошёл нахуй")`
  - После отправки фото счётчик сбрасывается (или продолжает считать по модулю)
- [ ] T-079-D: Comprehensive logging (INFO: photo sent, counter reset)

**ВАЖНО — изоляция:**
- Не трогать `MessageCounterMiddleware` (F3 GIF-счётчик) — он считает ВСЕ сообщения Славы
- Новый счётчик считает только ответы "пошёл нахуй" (независимый счётчик)
- F4 (KuchaWordFilter) и F5v2 (war_alert) продолжают работать независимо

**Файлы:** `handlers/slavik.py`, `config/settings.py`, `.env.example`, `services/database.py`

### T-080: Тесты для багфикса репостов (T-078)

- [ ] T-080-A: Тест: forwarded message от Славы с war keywords в text → war_keyword_handler срабатывает
- [ ] T-080-B: Тест: forwarded message от Славы с war keywords в caption → war_keyword_handler срабатывает
- [ ] T-080-C: Тест: forwarded message от Славы БЕЗ war keywords → war_keyword_handler НЕ срабатывает
- [ ] T-080-D: Тест: forwarded message от НЕ-Славы с war keywords → war_keyword_handler НЕ срабатывает
- [ ] T-080-E: Тест: оба хендлера (keyword + repost) не конфликтуют на одном роутере
- [ ] T-080-F: Интеграционный тест с Dispatcher: forwarded message → правильный handler fired

**Файлы:** `tests/test_war_alert.py` (обновить)

### T-081: Тесты для фичи slavic_na_litso.jpg (T-079)

- [ ] T-081-A: Тест: N-1 обычных ответов "пошёл нахуй" → reply с текстом
- [ ] T-081-B: Тест: N-й ответ → send_photo с slavic_na_litso.jpg вместо текста
- [ ] T-081-C: Тест: после фото счётчик сбрасывается → следующий N-1 ответов снова текстом
- [ ] T-081-D: Тест: F3 GIF-счётчик не зависит от нового счётчика (разные счётчики)
- [ ] T-081-E: Тест: F4 (KuchaWordFilter) не ломает счётчик "пошёл нахуй"
- [ ] T-081-F: Тест: конфигурация через .env — `SLIVIC_NA_LITSO_INTERVAL` меняет N
- [ ] T-081-G: Тест: `SLIVIC_NA_LITSO_INTERVAL=0` → фича отключена, всегда текст
- [ ] T-081-H: Тест: несколько чатов — независимые счётчики

**Файлы:** `tests/test_slavik_handlers.py` (обновить)

### T-082: Обновление README, коммит, пуш

- [ ] T-082-A: Обновить README.md — добавить секцию F5v2 bugfix (forwarded messages) и F8 (slavic_na_litso.jpg)
- [ ] T-082-B: Обновить ARCHITECTURE.md — добавить секцию про новый счётчик и forwarded-сообщения
- [ ] T-082-C: Обновить MEMORY.md — отразить изменения
- [ ] T-082-D: Коммит на русском (conventional commits) в main, пуш

### T-083: Деплой на сервер

- [ ] T-083-A: Git pull на сервере nik@198.46.175.136:/var/www/admin_bot
- [ ] T-083-B: Обновить .env на сервере (если нужны новые переменные)
- [ ] T-083-C: Restart бота
- [ ] T-083-D: Smoke test: Слава делает forward с "бпла" → war_alert срабатывает
- [ ] T-083-E: Smoke test: проверить, что slavic_na_litso.jpg отправляется каждый N-й раз
- [ ] T-083-F: Verify Better Stack логи

---

**Status: Epics 1–9, 11 DONE ✅. Epic 10 (War Words Redesign): T-054–T-063 — PLANNING 🔵. Epic 12 (Bugfix Reposts + slavic_na_litso.jpg): T-078–T-083 — NEW 🔵.**
**Date: 2026-07-25**