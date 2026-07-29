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

## Epic 6: Dead Page V2 — Event-driven reposts (2026-07-11) ✅ DONE

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

## Epic 10: War Words Redesign (F5v2) — 2026-07-16 ✅ DONE

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
- [x] T-054: Fix WarWordFilter — caption support + expand keywords
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
- [x] T-055: Add channel repost detection handler for military channels
  - **Pattern:** Использовать существующий шаблон из `handlers/dead_page_trigger.py`
  - **Target channels:** Channel ID 1654872411 ("ЧП Пермь") + username-based matching
  - **Detection:** И по ID, и по username (как dead_page_trigger делает двойную проверку)
  - **Filter:** `UserIdFilter(settings.SLAVIK_USER_ID)` — только сообщения Славы
  - **Reply:** Случайная фраза из пула (T-056) через `message.reply()`
  - **Handler priority:** Router зарегистрирован перед slavik_router (T-060)
  - **File:** `handlers/war_words_trigger.py` — новый файл

### Random reply pool
- [x] T-056: Create random reply pool + `random.choice()` logic
  - **Current:** Одиночный хардкод `"трясло ебаное"` в `war_word_handler`
  - **New:** Extensible reply pool (5 phrases) + `random.choice(WAR_REPLIES)`
  - **Extensibility:** Добавление новой фразы = новая строка в списке
  - **Reply mechanism:** `await message.reply(reply_text)` — reply_to mechanism

### Logging
- [x] T-057: Add comprehensive Better Stack logging
  - INFO: keyword matched, channel repost detected, reply sent
  - WARNING: filter miss (caption empty, origin not channel)
  - ERROR: handler failures
  - Context per log: chat_id, user_id, matched keyword, channel source, chosen reply text

### Testing
- [x] T-058: Create/extend tests — filter, handler, integration (~28 tests)
  - Filter tests: text-only, caption, empty, caption-only, case insensitivity, word boundary
  - Handler tests: keyword → random reply, verify message.reply(), verify randomness
  - Channel repost handler tests: target channel ID/username, non-target, user forward, non-forward

### Configuration
- [x] T-059: Update `config/settings.py` with `WAR_CHANNEL_IDS`, `WAR_CHANNEL_USERNAMES`, `WAR_REPLIES`

### Integration
- [x] T-060: Register `war_alert_router` in `bot.py` (position 4b между dead_page_router и slavik_router)

### Documentation
- [x] T-061: Update README — document F5 v2 (expanded keywords, channel repost detection, random reply pool, caption support)

### QA & Deploy
- [x] T-062: Run full pytest suite — verify no regressions, ~280 tests
- [x] T-063: Deploy to server — git pull, restart, smoke test, Verify Better Stack

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

## Epic 12: Багфикс репостов + slavic_na_litso.jpg (2026-07-25) ✅ DONE

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

**Итог:** Баг исправлен в v2.9.1 (убран конфликт lambda-фильтров в war_alert).
Дополнительные debug-логи для forwarded-сообщений добавлены в v2.9.2.

- [x] T-078-A: Провести расследование — diagnostic-логи, проверить гипотезы 1-4
- [x] T-078-B: Исправить баг (убраны lambda-фильтры, мешавшие WarWordFilter)
- [x] T-078-C: Добавить comprehensive logging для диагностики forwarded-сообщений

**Файлы:** `handlers/war_alert.py`, `filters/war_word.py`, `filters/user_id.py`

### T-079: Реализация фичи — картинка slavic_na_litso.jpg каждый N-й ответ "пошёл нахуй"

- [x] T-079-A: Добавить `SLIVIC_NA_LITSO_INTERVAL: int = 10` в `config/settings.py` + `.env.example`
- [x] T-079-B: Добавить метод `increment_and_get_slavic_reply_count` в `DatabaseService`
- [x] T-079-C: Модифицировать `slavik_catchall_handler` в `handlers/slavik.py` — каждый N-й ответ = фото вместо текста
- [x] T-079-D: Comprehensive logging (INFO: photo sent, counter reset)

### T-080: Тесты для багфикса репостов (T-078)
- [x] T-080-A–F: 6 тестов — forwarded message с war keywords, без, от не-Славы, оба хендлера, интеграционный тест

### T-081: Тесты для фичи slavic_na_litso.jpg (T-079)
- [x] T-081-A–H: 8 тестов — N-1 текстовых, N-й фото, сброс, F3 независимость, F4 независимость, конфиг, 0=выключено, несколько чатов

### T-082: Обновление README, коммит, пуш
- [x] T-082-A–D: README, ARCHITECTURE, MEMORY обновлены, коммит на русском в main

### T-083: Деплой на сервер
- [x] T-083-A–F: Git pull, .env, restart, smoke tests (forward + photo), Better Stack verified

---

## Epic 13: Otboy Service (F9) — 2026-07-26 ✅ DONE

> **Цель:** Создать standalone scalable сервис, который работает для ВСЕХ пользователей чата
> (не user-specific). При обнаружении слова "отбой" в сообщениях, репостах или подписях
> к медиа — бот отвечает картинкой `media/otboy.jpg` с нативным цитированием слова "отбой"
> через Telegram quote API.
>
> **Архитектурное требование:** Изоляция — сервис не должен влиять на другие фичи бота.
> Архитектура должна быть отревьюена sub-agent'ом ДО начала реализации.
>
> **Cooldown:** Настраиваемый через settings, default=0 (без ограничений).

### Архитектурное проектирование и ревью
- [x] T-084: Спроектировать архитектуру сервиса + sub-agent review
  - [x] T-084-A: Спроектировать архитектуру — модули, изоляция, поток данных (OtboyWordFilter → otboy_router → OtboyRelay)
  - [x] T-084-B: Sub-agent ревью архитектуры — проверить изоляцию, масштабируемость, отсутствие влияния на другие фичи
  - [x] T-084-C: Согласовать финальный дизайн с PM

### Фильтр
- [x] T-085: Создать `filters/otboy_word.py` — OtboyWordFilter
  - [x] T-085-A: Реализовать фильтр — проверка `message.text`, `message.caption`, и текста forwarded-сообщений
  - [x] T-085-B: Детект слова "отбой" (регистронезависимый, word-boundary \bотбой\b)
  - [x] T-085-C: Логирование срабатывания фильтра (INFO: chat_id, user_id, source field — text/caption/forward)

### Сервис
- [x] T-086: Создать `services/otboy_relay.py` — OtboyRelay (standalone scalable service)
  - [x] T-086-A: Реализовать инкапсулированный сервис без глобального состояния
  - [x] T-086-B: Метод `send_otboy(chat_id, reply_to_message_id, quote_text)` — отправка `media/otboy.jpg`
  - [x] T-086-C: Cooldown-логика — проверка `OTBOY_COOLDOWN_SECONDS`, thread-safe per-chat
  - [x] T-086-D: Comprehensive logging (INFO: photo sent, cooldown active, cooldown expired)

### Хендлер
- [x] T-087: Создать `handlers/otboy.py` — otboy_router + handler
  - [x] T-087-A: Handler: OtboyWordFilter → OtboyRelay.send_otboy()
  - [x] T-087-B: Reply с `reply_to_message_id` (Telegram native reply-to)
  - [x] T-087-C: Цитирование ТОЛЬКО слова "отбой" через Telegram quote API (native citation)
  - [x] T-087-D: Обработка ошибок (файл не найден, Telegram API error, permission denied)

### Конфигурация
- [x] T-088: Добавить `OTBOY_COOLDOWN_SECONDS` в `config/settings.py` + `.env.example`
  - [x] T-088-A: `OTBOY_COOLDOWN_SECONDS: int = 0` (0 = no cooldown, отправка на каждое "отбой")
  - [x] T-088-B: Обновить `.env.example` с описанием параметра и дефолтным значением

### Интеграция
- [x] T-089: Зарегистрировать `otboy_router` в `bot.py`
  - [x] T-089-A: Определить правильную позицию — перед user-specific роутерами (slavik, alan)
  - [x] T-089-B: Зарегистрировать `dp.include_router(otboy_router)`
  - [x] T-089-C: Инициализировать OtboyRelay при старте бота
  - [x] T-089-D: Убедиться, что propagation не блокирует другие хендлеры

### Тестирование
- [x] T-090: Написать тесты для Otboy Service (~10 тестов)
  - [x] T-090-A: Фильтр — текст с "отбой" → срабатывает
  - [x] T-090-B: Фильтр — caption с "отбой" → срабатывает
  - [x] T-090-C: Фильтр — forwarded message text с "отбой" → срабатывает
  - [x] T-090-D: Фильтр — текст без "отбой" → не срабатывает
  - [x] T-090-E: Фильтр — регистронезависимость ("Отбой", "ОТБОЙ", "ОтБой")
  - [x] T-090-F: Хендлер — `reply_to_message_id` совпадает с исходным `message_id`
  - [x] T-090-G: Хендлер — quote захватывает только слово "отбой" (не всё сообщение)
  - [x] T-090-H: Cooldown — второй вызов в пределах cooldown не отправляет фото
  - [x] T-090-I: Cooldown — после истечения cooldown фото отправляется снова
  - [x] T-090-J: Интеграционный тест — propagation (не блокирует другие хендлеры на том же сообщении)

### Документация
- [x] T-091: Обновить документацию
  - [x] T-091-A: `README.md` — добавить секцию F9 (Otboy Service), описание, настройки
  - [x] T-091-B: `ARCHITECTURE.md` — router order, data flow диаграмма, секция OtboyRelay
  - [x] T-091-C: `MEMORY.md` — project state, features table, version bump v2.10.0

### Деплой
- [x] T-092: Деплой на сервер + smoke tests
  - [x] T-092-A: Git pull на сервер nik@198.46.175.136:/var/www/admin_bot
  - [x] T-092-B: Обновить .env (если переопределён OTBOY_COOLDOWN_SECONDS)
  - [x] T-092-C: Restart бота
  - [x] T-092-D: Smoke test: сообщение с "отбой" → reply с otboy.jpg + quote "отбой"
  - [x] T-092-E: Smoke test: forwarded-сообщение с "отбой" → reply с otboy.jpg
  - [x] T-092-F: Smoke test: caption на фото с "отбой" → reply с otboy.jpg
  - [x] T-092-G: Проверить, что другие фичи не сломаны (прогнать полный тест-сьют)
  - [x] T-092-H: Verify Better Stack логи (INFO: otboy detected, photo sent)

---

## Epic 14: Media Group Album Fix — 2026-07-28 ✅ DONE

> **Цель:** Исправить баг в DeadPageRelay: при наличии альбома (media group из 2-10 фото)
> в relay-канале, `bot.forward_message()` (singular) форвардит только одно фото. Остальные
> теряются. Решение: DB-трекинг `media_group_id` через новую таблицу `relay_album_map`,
> использование `bot.forward_messages()` (plural) для сохранения группировки альбома,
> и эвристический fallback для старых постов без DB-записей.
>
> **Ограничения:** Все остальные функции бота не должны быть затронуты. Новые env vars
> не требуются (пороги хардкодед: ±2s окно дат, ±9 диапазон проб, до 2 consecutive gaps).
> Не сломать существующие 305 тестов. aiogram 3.x, Python 3.11+.

### Database
- [x] T-093: Новая таблица `relay_album_map` + 3 CRUD метода в `services/database.py`
  - [x] T-093-A: Создать таблицу `relay_album_map` (message_id INTEGER PK, media_group_id TEXT NOT NULL) в `_ensure_tables`
  - [x] T-093-B: Реализовать `insert_relay_album_entry(message_id, media_group_id)` — запись альбома
  - [x] T-093-C: Реализовать `get_media_group_id(message_id)` — получить media_group_id по message_id (или None)
  - [x] T-093-D: Реализовать `delete_relay_album_entries(message_ids: list[int])` — очистка после обработки

### Tracking
- [x] T-094: Новый `channel_post` handler в `bot.py` для отслеживания media_group_id
  - [x] T-094-A: Создать handler — ловит все посты в relay-канале (DEAD_PAGE_CHANNEL_ID)
  - [x] T-094-B: Извлечь `media_group_id` из `Message` (если есть) — записать в БД через `insert_relay_album_entry`
  - [x] T-094-C: Логирование: INFO при записи альбома, DEBUG для одиночных постов

### Forwarding — DB Path
- [x] T-095: Модифицировать `DeadPageRelay._try_forward_from_channel()` — DB lookup + `forward_messages()` (plural)
  - [x] T-095-A: После выбора random message проверить БД (`get_media_group_id`)
  - [x] T-095-B: Если media_group_id найден — запросить из БД все message_id с тем же media_group_id
  - [x] T-095-C: Использовать `bot.forward_messages()` (plural API) для форвардинга всех сообщений альбома одним вызовом
  - [x] T-095-D: После успешного форварда — вызвать `delete_relay_album_entries` для очистки
  - [x] T-095-E: Логирование: INFO — album forwarded (N messages, media_group_id), WARNING — partial forward

### Forwarding — Heuristic Fallback (старые посты без DB-записей)
- [x] T-096: Эвристический fallback — пробинг соседних message_id ±1..9
  - [x] T-096-A: Если `get_media_group_id` вернул None (старый пост) — войти в эвристический режим
  - [x] T-096-B: Пробинг: получить сообщения с ID от (picked_id - 9) до (picked_id + 9) из relay-канала
  - [x] T-096-C: Фильтрация: оставить только те, у которых дата в пределах ±2s от даты выбранного сообщения
  - [x] T-096-D: Непрерывность: собрать последовательные message_id (разрешено до 2 consecutive gaps)
  - [x] T-096-E: `bot.forward_messages()` для всех подходящих siblings
  - [x] T-096-F: `bot.delete_message()` для проб, которые не вошли в группу (non-matching probes)
  - [x] T-096-G: Обработка ошибок: если probe не найден (Message to forward not found) — пропустить
  - [x] T-096-H: Логирование: INFO — heuristic mode activated, N siblings found, N probes deleted

### Deduplication
- [x] T-097: Модифицировать `handlers/dead_page_trigger.py` — дедупликация media_group
  - [x] T-097-A: Отслеживать `media_group_id` входящих сообщений из @d_pages
  - [x] T-097-B: Если `media_group_id` уже обработан — пропустить (не вызывать `send_dead_page()` повторно)
  - [x] T-097-C: `send_dead_page()` вызывается только один раз на альбом
  - [x] T-097-D: Логирование: INFO — media_group dedup skipped, DEBUG — first occurrence

### Testing
- [x] T-098: Тесты (9+ cases) — DB + heuristic + dedup paths
  - [x] T-098-A: DB insert + get + delete media_group_id
  - [x] T-098-B: DB path — найден media_group_id → forward_messages вызывается с корректными ID
  - [x] T-098-C: DB path — одиночное сообщение (нет media_group_id) → forward_message (singular, без изменений)
  - [x] T-098-D: Heuristic — соседние сообщения с датой ±2s найдены → forward_messages с корректными ID
  - [x] T-098-E: Heuristic — неродственные сообщения (дата вне ±2s) отфильтрованы
  - [x] T-098-F: Heuristic — non-matching probes удалены через delete_message
  - [x] T-098-G: Heuristic — 2 consecutive gaps разрешены, 3+ gaps разрывают группу
  - [x] T-098-H: Dedup — повторный media_group_id не вызывает send_dead_page
  - [x] T-098-I: Интеграционный тест — полный пайплайн (channel_post → DB → forward_messages → dedup)
  - [x] T-098-J: Регрессионный тест — существующие тесты dead_page_relay не сломаны

### QA
- [x] T-099: Прогнать полный тест-сьют + обновить документацию
  - [x] T-099-A: `pytest` — все 305+ тестов проходят без регрессий
  - [x] T-099-B: Обновить `ARCHITECTURE.md` — секция DeadPageRelay, таблица relay_album_map, router order с channel_post handler
  - [x] T-099-C: Обновить `MEMORY.md` — project state, features table, version bump v2.11.0
  - [x] T-099-D: Обновить `README.md` — если требуется

---

## Epic 15: Common Service — Rename + Media Upgrade + Danger Detection — 2026-07-28 ✅ DONE

> **Цель:** (1) Переименовать сервис "otboy" → "common" — файлы, импорты, регистрации, env-настройки.
> Функция `otboy` (ответ на слово «отбой») сохраняет имя и поведение. (2) Upgrade media-обработки:
> вместо хардкодного `otboy.jpg` — подбор ЛЮБОГО файла из `\media\common\otboy\` с авто-детекцией типа
> (image→photo, video→video, video с "gif" в имени→animation). (3) Новая функция детекции опасных
> слов («бпла», «ракетная», «опасность» и др.) — заимствовать паттерн фильтра из Slavik/WarWordFilter,
> отправлять случайный контент из `\media\common\danger\` с теми же reply-to + quote механиками.
>
> **Границы:** Только файлы otboy-сервиса + конфигурация + тесты. Остальные фичи НЕ трогать.
> Все 316 тестов должны проходить. Архитектура ревьюится sub-agent'ом ДО реализации.

### Архитектурное проектирование и ревью
- [x] 👤 T-100 (@Architect): Спроектировать архитектуру Common Service + sub-agent review
  - [x] T-100-A: Спроектировать архитектуру — модули (common_handler, CommonRelay, CommonWordFilter + DangerWordFilter), data flow, directory structure, контракты
  - [x] T-100-B: Sub-agent ревью — проверить изоляцию от других фич, масштабируемость, корректность rename (без dead imports), media type detection matrix
  - [x] T-100-C: Согласовать финальный дизайн с PM

### Переименование файлов и модулей (otboy → common)
- [x] T-101: Переименовать файлы, классы, импорты, роутер
  - [x] T-101-A: Переименовать `handlers/otboy.py` → `handlers/common.py` (router: `otboy_router` → `common_router`, сохранить функцию `otboy_handler`)
  - [x] T-101-B: Переименовать `services/otboy_relay.py` → `services/common_relay.py` (класс `OtboyRelay` → `CommonRelay`)
  - [x] T-101-C: `filters/otboy_word.py` — оставить без изменений; СОЗДАТЬ `filters/danger_word.py` (новый файл, класс `DangerWordFilter`)
  - [x] T-101-D: Обновить ВСЕ импорты в `bot.py` (4 строки: router, setup, relay import, on_startup)
  - [x] T-101-E: Проверить grep-поиском отсутствие dead imports/ссылок на "otboy" во всём проекте (кроме функции `otboy_handler` и legacy-комментариев)

### Конфигурация (settings.py + .env.example)
- [x] T-102: Переименовать и добавить env-переменные
  - [x] T-102-A: `OTBOY_COOLDOWN_SECONDS` → `COMMON_COOLDOWN_SECONDS` (тот же default=0, общий cooldown для otboy и danger)
  - [x] T-102-B: `OTBOY_PHOTO_PATH` → удалить, добавить `COMMON_MEDIA_BASE: str = "media/common"` (subdirs: `otboy`/`danger` разрешаются динамически через параметр `subdir`)
  - [x] T-102-C: Создать директории `media/common/otboy/` и `media/common/danger/` (filesystem migration, см. §26.16)
  - [x] T-102-D: Обновить `.env.example` — заменить старые ключи на новые с описаниями и дефолтами

### Upgrade media-обработки (otboy function)
- [x] T-103: Directory-based media picker с авто-детекцией типа
  - [x] T-103-A: В `CommonRelay` — метод `_pick_media(media_dir)` сканирует директорию, выбирает случайный файл
  - [x] T-103-B: Реализовать `_detect_media_type(filename)` → `"photo" | "video" | "animation"`
    - `.jpg/.jpeg/.png/.webp/.bmp` → `"photo"` (send_photo)
    - `.mp4/.avi/.mov/.webm` без "gif" в имени → `"video"` (send_video)
    - `.mp4/.avi/.mov/.webm` с "gif" в имени → `"animation"` (send_animation / GIF)
  - [x] T-103-C: Реализовать `_send_media(chat_id, filepath, media_type, reply_params)` — единый dispatcher для всех трёх типов
  - [x] T-103-D: Обновить `send_otboy()` — использовать `_pick_media` + `_send_media` вместо хардкодного `FSInputFile`
  - [x] T-103-E: Логирование: INFO — media type chosen, file path, chat_id

### Новая функция детекции опасных слов (danger)
- [x] T-104: DangerWordFilter + danger_handler + CommonRelay.send_danger()
  - [x] T-104-A: Реализовать `DangerWordFilter` в `filters/danger_word.py` — список DANGER_WORDS (бпла, ракетная, опасность, тревога, внимание, сирена, атака, угроза, обстрел, воздушная + словоформы), pattern compilation как в WarWordFilter
  - [x] T-104-B: Реализовать `CommonRelay.send_danger(chat_id, message_id, matched_word)` — `_pick_media(subdir="danger")` (разрешается через `COMMON_MEDIA_BASE`) + `_send_media()` + reply_to + quote
  - [x] T-104-C: Добавить `danger_handler` в `handlers/common.py` — `DangerWordFilter()` → `_relay.send_danger()` (паттерн как у otboy_handler)
  - [x] T-104-D: Reply-to и quote mechanism — идентичен otboy (ReplyParameters с matched_word)
  - [x] T-104-E: Comprehensive logging для danger (INFO: word matched, media type, chat_id)

### Интеграция в bot.py
- [x] T-105: Обновить импорты, регистрацию и инициализацию
  - [x] T-105-A: Обновить импорты — `from handlers.common import common_router, setup_common`, `from services.common_relay import CommonRelay`
  - [x] T-105-B: Заменить `otboy_router` → `common_router` в `dp.include_router()` (позиция 4c сохраняется)
  - [x] T-105-C: Обновить `on_startup()` — `CommonRelay(bot, settings.COMMON_COOLDOWN_SECONDS)`, `setup_common(relay)`
  - [x] T-105-D: Убедиться, что propagation не блокирует другие хендлеры (оба handler'а возвращают None)

### Тестирование
- [x] T-106: Написать/обновить тесты (~20+ тестов)
  - [x] T-106-A: Переименовать `tests/test_otboy.py` → `tests/test_common.py`, обновить все импорты
  - [x] T-106-B: Тесты OtboyWordFilter — перенести существующие 11 тестов, обновить импорты
  - [x] T-106-C: Тесты otboy_handler — перенести существующие 6 тестов, заменить OtboyRelay → CommonRelay
  - [x] T-106-D: Тесты CommonRelay.send_otboy — image file → send_photo
  - [x] T-106-E: Тесты CommonRelay.send_otboy — video file → send_video
  - [x] T-106-F: Тесты CommonRelay.send_otboy — video с "gif" в имени → send_animation
  - [x] T-106-G: Тесты CommonRelay._pick_media — пустая директория, не-медиа файлы (graceful skip)
  - [x] T-106-H: Тесты DangerWordFilter — текст/caption с опасными словами → срабатывает
  - [x] T-106-I: Тесты DangerWordFilter — без опасных слов → False, регистронезависимость, word boundary
  - [x] T-106-J: Тесты danger_handler — делегирует в CommonRelay.send_danger с правильными параметрами
  - [x] T-106-K: Тесты CommonRelay.send_danger — случайный медиа из danger dir, правильный тип (image/video/animation)
  - [x] T-106-L: Тесты cooldown — общий cooldown для otboy и danger, per-chat изоляция
  - [x] T-106-M: Интеграционный тест — propagation: common_router не блокирует slavik/alan/vasya
  - [x] T-106-N: Интеграционный тест — диспетчеризация: сообщение с "отбой" и опасным словом → оба handler'а вызываются

### Документация
- [x] T-107: Обновить документацию
  - [x] T-107-A: `README.md` — переименовать F9 → "Common Service", добавить секцию danger detection, описать media type matrix
  - [x] T-107-B: `ARCHITECTURE.md` — обновить router order (4c: common_router), CommonRelay секцию, data flow с двумя handler'ами
  - [x] T-107-C: `MEMORY.md` — project state, features table, version bump v2.12.0

### QA и деплой
- [x] T-108: QA — тесты, коммит, деплой
  - [x] T-108-A: `pytest` — все 316+ тестов проходят, 0 регрессий, coverage ≥ 100% для новых модулей
  - [x] T-108-B: Коммит на русском (conventional commits) в main, пуш
  - [x] T-108-C: Деплой на сервер — git pull, обновить .env (COMMON_COOLDOWN_SECONDS, COMMON_MEDIA_BASE, DANGER_WORDS), создать директории (filesystem migration §26.16), restart
  - [x] T-108-D: Smoke test: сообщение с "отбой" → reply с медиа из common/otboy, quote "отбой"
  - [x] T-108-E: Smoke test: сообщение с "ракетная опасность" → reply с медиа из common/danger, quote слова
  - [x] T-108-F: Smoke test: проверить, что другие фичи не сломаны (слава, war_alert, алан, вася, костик)
  - [x] T-108-G: Verify Better Stack логи (INFO: otboy detected, danger detected, media type)

---

## Epic 16: Bug Fixes Sprint — 2026-07-29 ✅ ARCHIVED (→ Epic 17)

> **Цель:** Исправить критические баги, обнаруженные после деплоя Epic 14 (Album Fix) и Epic 15 (Common Service).
> **Архивирован 2026-07-30.** Danger_word fix выделен в Epic 17. DeadPageRelay album fix отложен.
>
> ### Сводка багов
>
> **Баг 1 — Репост из канала ломает группировку альбомов (DeadPageRelay):**
> Пользователь репостит из @d_pages. В relay-канале всего 2 поста: (A) обычный пост
> с картинкой, (B) альбом из 3 фото + caption. Алгоритм `_forward_with_heuristic()`
> форвардит каждое фото отдельным `forward_message()` — группировка разрушается.
> Эвристика data proximity (±2 сек) склеивает пост A + пост B в одну группу.
>
> **Баг 2 — Danger handler в Common Service не работает:**
> `danger_handler` не отвечает на слова «БПЛА», «ракета» и т.д.
> Два root cause: (A) `war_channel_repost_handler` (war_alert_router, позиция 4b)
> перехватывает ВСЕ forwarded-сообщения через `F.forward_origin` и блокирует
> propagation к common_router (позиция 4c). (B) `_DEFAULT_DANGER_WORDS` содержит
> всего 22 слова — нет «ракета», «укрытие», «бункер» и др. (в war_word.py 91+ слов).
>
> ---

### Bug 1: Репост из канала — исправление группировки альбомов

**Root Cause Analysis (подробно):**

Файл `services/dead_page_relay.py`, метод `_forward_with_heuristic()` (строки 273–362):
- **RC1:** Каждый sibling форвардится отдельным `forward_message()` (строки 282, 296, 326).
  Вместо этого нужно собрать все message_id в список и вызвать `forward_messages()` (plural)
  один раз — как это уже сделано в DB Path (строки 249–260).
- **RC2:** Эвристика `_ALBUM_DATE_TOLERANCE_S = 2 сек` (строки 303, 333) не различает
  «соседний пост того же альбома» и «соседний НЕЗАВИСИМЫЙ пост с близкой датой».
  Если пост A (картинка, msg_id=N) и пост B (альбом, msg_id=N+1) имеют даты в пределах
  ±2 сек, эвристика считает их одним альбомом → склеивает.
- **RC3:** Heuristic Path вызывается для старых постов, у которых нет записи в
  `relay_album_map` (БД-трекер добавлен только в Epic 14 и индексирует только новые посты).

**План исправления (приоритет: RC1 → RC2 → fallback-откат):**

- [ ] T-110: Fix `_forward_with_heuristic()` — переписать на коллективный forward
  - [ ] T-110-A: **(RC1 fix)** Переписать логику: сначала собрать все sibling message_id
    в список (probe → проверить дату → добавить в список БЕЗ немедленного forward),
    затем ОДИН вызов `bot.forward_messages(chat_id, from_chat_id, message_ids=sorted_ids)`.
    Удаление non-matching probes больше не нужно (ничего не форвардилось раньше времени).
  - [ ] T-110-B: **(RC2 fix)** Ужесточить критерий «тот же альбом»:
    - Если пробный пост имеет `media_group_id` — он часть альбома по определению.
    - Если у primary поста тоже есть `media_group_id` — сравнивать `media_group_id`;
      разные group_id = разные альбомы.
    - Date proximity использовать ТОЛЬКО как fallback, когда `media_group_id` отсутствует
      у обоих постов (старые одиночные посты без альбома).
  - [ ] T-110-C: **(Safety net)** Если переписывание heuristic занимает >2 часов —
    откатить метод `_forward_with_heuristic()` к версии до Epic 14 (простой
    `forward_message()` без probing). DB Path (Path 1) остаётся и покрывает новые посты.
  - [ ] T-110-D: **(Логирование)** Добавить INFO-лог при heuristic album forward:
    количество сообщений, IDs, `media_group_id` (если есть), причина группировки
    (media_group_id match vs date proximity).

- [ ] T-111-C: Тесты для альбомного forward
  - [ ] T-111-C1: Heuristic: альбом из 3 фото → один вызов `forward_messages()` с 3 ID
  - [ ] T-111-C2: Heuristic: обычный пост + соседний альбом НЕ склеиваются (разные media_group_id)
  - [ ] T-111-C3: Heuristic: два поста без media_group_id, даты >2 сек → не склеиваются
  - [ ] T-111-C4: Heuristic: два поста без media_group_id, даты ≤2 сек → склеиваются
  - [ ] T-111-C5: DB Path: альбом с записью в relay_album_map → `forward_messages()` (без изменений, no regression)
  - [ ] T-111-C6: Интеграционный: полный пайплайн trigger → relay → forward_messages

**Файлы для изменения:**
- `services/dead_page_relay.py` — `_forward_with_heuristic()` (строки 273–362)
- `tests/test_dead_page_relay.py` — добавить/обновить тесты

---

### Bug 2: Common Service danger_handler не работает

**Root Cause Analysis (подробно):**

**RC-A (Критический — блокирует forwarded-сообщения):**
`handlers/war_alert.py`, `war_channel_repost_handler` (строки 186–231):
- Фильтр `F.forward_origin` матчит ЛЮБОЕ forwarded-сообщение из любого канала.
- Для non-target каналов handler возвращает `None` (ранний return, строка 206).
- В aiogram 3.x: если handler был вызван (фильтр сматчил) — роутер считает update
  обработанным и НЕ передаёт его следующим роутерам.
- **Результат:** `common_router` (позиция 4c) НИКОГДА не видит forwarded-сообщения,
  потому что `war_alert_router` (позиция 4b) уже «съел» их через handler 2.
- **Затронутые сценарии:** Любой репост с текстом «бпла», «ракета» и т.д. → danger_handler молчит.

**RC-B (Существенный — узкий список слов):**
`filters/danger_word.py`, `_DEFAULT_DANGER_WORDS` (строки 18–41):
- Всего 22 слова. Отсутствуют: «ракета» и все словоформы (есть только «ракетная»),
  «укрытие», «бункер», «вспышка», «взрыв», «прилет», «отбой» и др.
- Для сравнения: `filters/war_word.py` → `WAR_WORDS` содержит 91+ словоформ.
- **Результат:** Даже для обычных (не-forwarded) сообщений, слова «ракета», «бпла»
  и другие military keywords не матчатся, если их нет в `_DEFAULT_DANGER_WORDS`.

**RC-C (Подтверждено — НЕ проблема):**
- `media/common/danger/` содержит файлы (`danger_01.mp4`, `danger_02_gif.mp4`) — ок.
- `war_keyword_handler` использует `UserIdFilter(SLAVIK)` — не блокирует non-Slava сообщения.
- `CommonRelay` инициализируется корректно в `bot.py:75-76`.

**План исправления:**

- [ ] T-114: Fix propagation stopper — `war_channel_repost_handler` блокирует common_router
  - [ ] T-114-A: Заменить фильтр `F.forward_origin` на кастомный фильтр, который
    матчит ТОЛЬКО target channels (по ID или username). Варианты реализации:
    - **Вариант A (рекомендуемый):** Вынести логику `_is_target_channel()` в отдельный
      `TargetChannelFilter(BaseFilter)` и использовать `@war_alert_router.message(TargetChannelFilter())`.
    - **Вариант B:** Оставить `F.forward_origin` но в начале handler'а сделать проверку —
      если non-target → НЕ возвращать None, а использовать механизм aiogram для
      передачи управления дальше (флаги или middleware).
  - [ ] T-114-B: Убедиться, что handler 2 (`war_channel_repost_handler`) больше
    НЕ срабатывает на forwarded из нецелевых каналов.
  - [ ] T-114-C: Проверить, что handler 1 (`war_keyword_handler`) по-прежнему работает
    для Славы (UserIdFilter + WarWordFilter) и не блокирует propagation.

- [ ] T-109: Fix DangerWordFilter — расширить список слов (из war_word.py)
  - [ ] T-109-A: Скопировать ВСЕ слова из `filters/war_word.py::WarWordFilter.WAR_WORDS`
    в `filters/danger_word.py::_DEFAULT_DANGER_WORDS`. Это ~91 словоформа (12 категорий:
    flight, drone/UAV, rocket/missile, shelter, bunker, flash/explosion, danger/alert,
    siren, attack/threat, fall/crash, evacuation, retreat).
  - [ ] T-109-B: Убедиться, что `_build_danger_patterns()` корректно компилирует
    word-boundary regex для всех слов (функция уже оттестирована — паттерн как в war_word.py).
  - [ ] T-109-C: Проверить регистронезависимость и word boundary:
    - «БПЛА» → матчит (уже в lowercase «бпла»)
    - «Ракета» / «РАКЕТА» → матчит
    - «ракетная» → матчит (уже было, no regression)
    - «подракетная» → НЕ матчит (word boundary)

- [ ] T-111-A: Тесты DangerWordFilter — расширенный список
  - [ ] T-111-A1: Все 91+ слов матчатся (параметризованный тест)
  - [ ] T-111-A2: Регистронезависимость: «БПЛА», «Ракета», «РАКЕТА»
  - [ ] T-111-A3: Word boundary: «ракета» матчит, «подракетная» нет
  - [ ] T-111-A4: Caption support: caption с danger word → матчит
  - [ ] T-111-A5: Forwarded message text с danger word → матчит
  - [ ] T-111-A6: No regression: все старые тесты OtboyWordFilter проходят

- [ ] T-111-D: Тесты propagation (интеграционные)
  - [ ] T-111-D1: Forwarded из non-target канала с danger word → common_router получает
    (проверка, что T-114 fix работает)
  - [ ] T-111-D2: Forwarded из target канала → war_alert_router обрабатывает,
    common_router ТОЖЕ может обработать (или блокируется — уточнить у PM)
  - [ ] T-111-D3: Обычное (не-forwarded) сообщение от non-Slava с «ракета» →
    danger_handler срабатывает, war_alert молчит
  - [ ] T-111-D4: Сообщение от Славы с «ракета» → war_keyword_handler срабатывает,
    danger_handler тоже срабатывает (два ответа на одно сообщение — ожидаемо?)

**Файлы для изменения:**
- `handlers/war_alert.py` — `war_channel_repost_handler` (строки 186–231)
- `filters/danger_word.py` — `_DEFAULT_DANGER_WORDS` (строки 18–41)
- `tests/test_common.py` — добавить тесты на расширенный DangerWordFilter
- `tests/test_war_alert.py` — добавить тест на propagation
- (опционально) `filters/target_channel.py` — новый фильтр для T-114-A

---

### Конфигурационный баг (T-113 — без изменений)

- [ ] T-113: Проверить DEAD_PAGE_RELAY_CHANNEL_ID на соответствие в .env и коде
  - [ ] T-113-A: Проверить знак значения (отрицательное vs положительное) в .env на сервере и локально
  - [ ] T-113-B: Проверить, как значение используется в коде (int vs str, сравнение с отрицательным числом)
  - [ ] T-113-C: При несоответствии — исправить и задокументировать в .env.example

---

### Тестирование (общее)

- [ ] T-111: Полный тестовый прогон
  - [ ] T-111-E: `pytest` — все существующие 316+ тестов проходят, 0 регрессий
  - [ ] T-111-F: Новые тесты T-111-C (альбомы, 6 шт.) + T-111-A (danger words, 6 шт.) + T-111-D (propagation, 4 шт.) → итого ~16 новых тестов

### Документация

- [ ] T-112: Синхронизировать документацию
  - [ ] T-112-A: Обновить board.md — отразить актуальное состояние Epic 16
  - [ ] T-112-B: Обновить backlog.md — этот файл
  - [ ] T-112-C: Обновить ARCHITECTURE.md — router order rationale (почему common_router после war_alert, propagation concern)
  - [ ] T-112-D: README.md — version bump v2.12.0 → v2.12.1, changelog

---

**Status: Epics 1–16 ARCHIVED ✅. Epic 17 (Danger Word Fix) — IN PROGRESS 🔵.**
**Date: 2026-07-30 | v2.12.1 (target)**

---

## Epic 17: Danger Word Fix — 2026-07-30 🔵 IN PROGRESS

> **Цель:** Исправить баг — фича danger_word в common сервисе не работает. Бот не реагирует
> на danger-слова («бпла», «ракета», «опасность» и др.) ни в личных, ни в групповых чатах.
>
> **Гипотезы бага:**
> - **H3 (наиболее вероятная):** Медиа-файлы `media/common/danger/` не задеплоены на сервер →
>   `_scan_directory` → `FileNotFoundError` → `send_common` молча падает.
> - **H1:** `war_alert_router` (позиция 4b) перехватывает сообщения до `common_router` (4c).
>   Фильтр `F.forward_origin` в `war_channel_repost_handler` матчит ЛЮБОЕ forwarded-сообщение,
>   блокируя propagation к common_router.
> - **H4:** Баг в `_build_danger_patterns` — некорректный regex.
> - **H5:** `otboy_handler` блокирует `danger_handler` (только для слова «отбой»).
>
> **Что работает:** `otboy` (тот же роутер, тот же relay, тот же код) — работает идеально ✅.

### T-115 (T1): Проверить наличие медиа-файлов danger/ на сервере
- [ ] T-115-A: Подключиться к серверу nik@198.46.175.136:/var/www/admin_bot
- [ ] T-115-B: Проверить наличие директории `media/common/danger/`
- [ ] T-115-C: Проверить наличие файлов `danger_01.mp4`, `danger_02_gif.mp4` (или любых медиа)
- [ ] T-115-D: Если файлы отсутствуют — скопировать/создать, проверить права (chmod 644)
- [ ] T-115-E: Сравнить локальную `media/common/danger/` с серверной (diff)

### T-116 (T2): Проверить и исправить DangerWordFilter (паттерны, инициализация)
- [ ] T-116-A: Проверить `_DEFAULT_DANGER_WORDS` — список слов (22 слова → нужно 91+ из war_word.py)
- [ ] T-116-B: Проверить `_build_danger_patterns()` — корректность word-boundary regex
- [ ] T-116-C: Проверить регистронезависимость: «БПЛА», «Ракета», «РАКЕТА», «бпла»
- [ ] T-116-D: Проверить word boundary: «ракета» матчит, «подракетная» нет
- [ ] T-116-E: Проверить `__call__` — проверка `message.text` и `message.caption`
- [ ] T-116-F: Скопировать ВСЕ слова из `filters/war_word.py::WAR_WORDS` в `_DEFAULT_DANGER_WORDS`
- [ ] T-116-G: Comprehensive logging: INFO при срабатывании фильтра (chat_id, user_id, matched_word, source field)

### T-117 (T3): Проверить взаимодействие war_alert_router и common_router
- [ ] T-117-A: Проверить порядок роутеров в `bot.py` (war_alert_router=4b, common_router=4c)
- [ ] T-117-B: Проверить `war_channel_repost_handler` — фильтр `F.forward_origin` матчит ВСЕ forwarded
- [ ] T-117-C: Проверить propagation: возвращает ли handler `None` для non-target каналов
- [ ] T-117-D: Заменить `F.forward_origin` на `TargetChannelFilter` (только target каналы)
  - Вариант A: Вынести `_is_target_channel()` в отдельный `TargetChannelFilter(BaseFilter)`
  - Вариант B: Оставить `F.forward_origin` + middleware для передачи управления дальше
- [ ] T-117-E: Проверить: forwarded из non-target канала → доходит до common_router
- [ ] T-117-F: Проверить: handler 1 (`war_keyword_handler`) не сломан

### T-118 (T4): Проверить и исправить CommonRelay.send_common (механизм отправки)
- [ ] T-118-A: Проверить `_scan_directory` — обрабатывает ли ошибки (FileNotFoundError, пустая папка)
- [ ] T-118-B: Проверить `_pick_media` — fallback при пустой директории, не-медиа файлы
- [ ] T-118-C: Проверить `_detect_media_type` — корректность для всех расширений
- [ ] T-118-D: Проверить `send_danger()` — параметры вызова `_pick_media(subdir="danger")`
- [ ] T-118-E: Проверить `_send_media()` — dispatch по типам (photo/video/animation)
- [ ] T-118-F: Добавить ERROR-лог при `FileNotFoundError` в `_scan_directory` (сейчас молча падает?)
- [ ] T-118-G: Добавить WARNING-лог при пустой директории danger/

### T-119 (T5): Добавить/исправить тесты для danger_word
- [ ] T-119-A: DangerWordFilter — все 91+ слов матчатся (параметризованный тест)
- [ ] T-119-B: DangerWordFilter — регистронезависимость («БПЛА», «Ракета», «РАКЕТА»)
- [ ] T-119-C: DangerWordFilter — word boundary («ракета» ✓, «подракетная» ✗)
- [ ] T-119-D: DangerWordFilter — caption и forwarded text support
- [ ] T-119-E: danger_handler — делегирует в CommonRelay.send_danger с правильными параметрами
- [ ] T-119-F: CommonRelay.send_danger — случайный медиа из danger dir, правильный тип
- [ ] T-119-G: CommonRelay — пустая директория danger/ (graceful handling)
- [ ] T-119-H: Интеграционный тест: propagation — war_alert + common_router interaction
- [ ] T-119-I: `pytest` — полный suite, 0 регрессий

### T-120 (T6): Обновить README
- [ ] T-120-A: Обновить секцию Common Service — описать danger_word fix
- [ ] T-120-B: Version bump: v2.12.1 → v2.12.2
- [ ] T-120-C: Добавить changelog entry

### T-121 (T7): Деплой на сервер
- [ ] T-121-A: Git pull на сервер nik@198.46.175.136:/var/www/admin_bot
- [ ] T-121-B: Проверить/создать директорию `media/common/danger/` с файлами
- [ ] T-121-C: Обновить .env (если требуется)
- [ ] T-121-D: Restart бота
- [ ] T-121-E: Smoke test: сообщение с «ракета» → reply с danger-медиа
- [ ] T-121-F: Smoke test: forwarded с «бпла» → reply с danger-медиа
- [ ] T-121-G: Smoke test: другие фичи не сломаны (слава, war_alert, алан, вася, костик)
- [ ] T-121-H: Verify Better Stack логи (INFO: danger detected, media type, FileNotFoundError resolved)

**Файлы для изменения:**
- `filters/danger_word.py` — расширить `_DEFAULT_DANGER_WORDS`, добавить логирование
- `handlers/war_alert.py` — `war_channel_repost_handler` (строки 186–231), заменить `F.forward_origin`
- `services/common_relay.py` — `_scan_directory`, `send_danger`, error handling
- `tests/test_common.py` — добавить тесты на расширенный DangerWordFilter, propagation
- `tests/test_war_alert.py` — propagation тесты
- `README.md` — changelog, version bump
