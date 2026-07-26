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

## Epic 13: Otboy Service (F9) — 2026-07-26 🔵 NEW

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
- [ ] T-084: Спроектировать архитектуру сервиса + sub-agent review
  - [ ] T-084-A: Спроектировать архитектуру — модули, изоляция, поток данных (OtboyWordFilter → otboy_router → OtboyRelay)
  - [ ] T-084-B: Sub-agent ревью архитектуры — проверить изоляцию, масштабируемость, отсутствие влияния на другие фичи
  - [ ] T-084-C: Согласовать финальный дизайн с PM

### Фильтр
- [ ] T-085: Создать `filters/otboy_word.py` — OtboyWordFilter
  - [ ] T-085-A: Реализовать фильтр — проверка `message.text`, `message.caption`, и текста forwarded-сообщений
  - [ ] T-085-B: Детект слова "отбой" (регистронезависимый, word-boundary \bотбой\b)
  - [ ] T-085-C: Логирование срабатывания фильтра (INFO: chat_id, user_id, source field — text/caption/forward)

### Сервис
- [ ] T-086: Создать `services/otboy_relay.py` — OtboyRelay (standalone scalable service)
  - [ ] T-086-A: Реализовать инкапсулированный сервис без глобального состояния
  - [ ] T-086-B: Метод `send_otboy(chat_id, reply_to_message_id, quote_text)` — отправка `media/otboy.jpg`
  - [ ] T-086-C: Cooldown-логика — проверка `OTBOY_COOLDOWN_SECONDS`, thread-safe per-chat
  - [ ] T-086-D: Comprehensive logging (INFO: photo sent, cooldown active, cooldown expired)

### Хендлер
- [ ] T-087: Создать `handlers/otboy.py` — otboy_router + handler
  - [ ] T-087-A: Handler: OtboyWordFilter → OtboyRelay.send_otboy()
  - [ ] T-087-B: Reply с `reply_to_message_id` (Telegram native reply-to)
  - [ ] T-087-C: Цитирование ТОЛЬКО слова "отбой" через Telegram quote API (native citation)
  - [ ] T-087-D: Обработка ошибок (файл не найден, Telegram API error, permission denied)

### Конфигурация
- [ ] T-088: Добавить `OTBOY_COOLDOWN_SECONDS` в `config/settings.py` + `.env.example`
  - [ ] T-088-A: `OTBOY_COOLDOWN_SECONDS: int = 0` (0 = no cooldown, отправка на каждое "отбой")
  - [ ] T-088-B: Обновить `.env.example` с описанием параметра и дефолтным значением

### Интеграция
- [ ] T-089: Зарегистрировать `otboy_router` в `bot.py`
  - [ ] T-089-A: Определить правильную позицию — перед user-specific роутерами (slavik, alan)
  - [ ] T-089-B: Зарегистрировать `dp.include_router(otboy_router)`
  - [ ] T-089-C: Инициализировать OtboyRelay при старте бота
  - [ ] T-089-D: Убедиться, что propagation не блокирует другие хендлеры

### Тестирование
- [ ] T-090: Написать тесты для Otboy Service (~10 тестов)
  - [ ] T-090-A: Фильтр — текст с "отбой" → срабатывает
  - [ ] T-090-B: Фильтр — caption с "отбой" → срабатывает
  - [ ] T-090-C: Фильтр — forwarded message text с "отбой" → срабатывает
  - [ ] T-090-D: Фильтр — текст без "отбой" → не срабатывает
  - [ ] T-090-E: Фильтр — регистронезависимость ("Отбой", "ОТБОЙ", "ОтБой")
  - [ ] T-090-F: Хендлер — `reply_to_message_id` совпадает с исходным `message_id`
  - [ ] T-090-G: Хендлер — quote захватывает только слово "отбой" (не всё сообщение)
  - [ ] T-090-H: Cooldown — второй вызов в пределах cooldown не отправляет фото
  - [ ] T-090-I: Cooldown — после истечения cooldown фото отправляется снова
  - [ ] T-090-J: Интеграционный тест — propagation (не блокирует другие хендлеры на том же сообщении)

### Документация
- [ ] T-091: Обновить документацию
  - [ ] T-091-A: `README.md` — добавить секцию F9 (Otboy Service), описание, настройки
  - [ ] T-091-B: `ARCHITECTURE.md` — router order, data flow диаграмма, секция OtboyRelay
  - [ ] T-091-C: `MEMORY.md` — project state, features table, version bump v2.10.0

### Деплой
- [ ] T-092: Деплой на сервер + smoke tests
  - [ ] T-092-A: Git pull на сервер nik@198.46.175.136:/var/www/admin_bot
  - [ ] T-092-B: Обновить .env (если переопределён OTBOY_COOLDOWN_SECONDS)
  - [ ] T-092-C: Restart бота
  - [ ] T-092-D: Smoke test: сообщение с "отбой" → reply с otboy.jpg + quote "отбой"
  - [ ] T-092-E: Smoke test: forwarded-сообщение с "отбой" → reply с otboy.jpg
  - [ ] T-092-F: Smoke test: caption на фото с "отбой" → reply с otboy.jpg
  - [ ] T-092-G: Проверить, что другие фичи не сломаны (прогнать полный тест-сьют)
  - [ ] T-092-H: Verify Better Stack логи (INFO: otboy detected, photo sent)

---

**Status: Epics 1–12 DONE ✅. Epic 13 (Otboy Service F9): T-084–T-092 — NEW 🔵.**
**Date: 2026-07-26 | v2.9.2 (280 tests) → v2.10.0 (Epic 13 target)**
