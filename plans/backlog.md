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

## Epic 7: Better Stack Monitoring Integration (2026-07-12)

> **Цель:** Интегрировать Sentry (error tracking) и Logtail (log aggregation) от Better Stack
> для production-grade мониторинга бота.

### Подготовка окружения
- [ ] T-029: Добавить sentry-sdk и logtail-python в requirements.txt с закреплёнными версиями (sentry-sdk==2.64.0, logtail-python==0.4.0)
- [ ] T-030: Установить sentry-sdk и logtail-python в venv проекта
- [ ] T-031: Добавить SENTRY_DSN и LOGTAIL_SOURCE_TOKEN в .env.example
- [ ] T-032: Добавить SENTRY_DSN и LOGTAIL_SOURCE_TOKEN в .env (создать по шаблону .env.example, если отсутствует)

### Интеграция в код
- [ ] T-033: Инициализировать Sentry SDK в bot.py (импорт после load_dotenv, traces_sample_rate=1.0)
- [ ] T-034: Настроить Logtail logging handler (LogtailHandler на root logger рядом с StreamHandler, source token из LOGTAIL_SOURCE_TOKEN)

### Верификация
- [ ] T-035: Написать и запустить smoke test — отправить тестовый лог + тестовую ошибку в облако
- [ ] T-036: Запустить существующий тестовый suite (pytest), убедиться что ничего не сломалось

### Документация
- [ ] T-037: Обновить ARCHITECTURE.md — добавить секцию мониторинга (@Architect)

---

## Epic 8: Alan Greeting Video (F7) — 2026-07-13

> **Цель:** Когда пользователь Alan (ID 138811255, @Alan_Z) заходит в чат, бот отправляет
> случайное видео из `media/leha_greeting/` с тегом @Alan_Z в подписи.

### Конфигурация
- [ ] T-038: Добавить `ALAN_USERNAME`, `ALAN_USER_ID` и `ALAN_GREETING_DIR` в `config/settings.py` + `.env.example`

### Хендлер
- [ ] T-039: Создать `handlers/alan_greeting.py` — `alan_greeting_router`:
  - `ChatMemberUpdatedFilter` (IS_NOT_MEMBER → IS_MEMBER) + `new_chat_members` fallback
  - Рандомное видео из `media/leha_greeting/` → `send_video` (не animation/GIF, не document)
  - Caption: `@Alan_Z`
  - Comprehensive logging (info: join detected, sent; warning: no videos; error: failure)

### Интеграция
- [ ] T-040: Зарегистрировать `alan_greeting_router` в `bot.py` (позиция 1, рядом с `slava_presence_router`)

### Тестирование
- [ ] T-041: Написать `tests/test_alan_greeting.py` (7-8 тестов):
  - Alan join → video sent with caption
  - Non-Alan join → ignored
  - Alan leave → ignored
  - `new_chat_members` fallback
  - Random selection (multiple videos)
  - Caption contains @Alan_Z
  - Empty `media/leha_greeting/` → graceful handling
  - Error during send → logged

### Документация
- [ ] T-042: Обновить `ARCHITECTURE.md` (F7 data flow, router order, directory listing)
- [ ] T-043: Обновить `MEMORY.md` (project state, features table)

### QA
- [ ] T-044: Прогнать все тесты, убедиться в отсутствии регрессий
- [ ] T-045: Code review и QA

### Багфиксы (2026-07-13)
- [ ] T-046: БАГФИКС: Dead Page Relay — ALL RANGES EXHAUSTED (Critical)
  - Исправить `_build_search_ranges()` в `services/dead_page_relay.py`: добавить `_DISCOVERY_RANGES` как fallback после anchored ranges, чтобы при росте канала >200 сообщений алгоритм не ограничивался узким окном [1,200].
  - Исправить `continue` на строке ~106 — dedup при `last_msg_id=100` не должен сжигать 2 из 10 слотов попыток.
  - Добавить WARNING-лог при входе в fallback `_DISCOVERY_RANGES`.
  - [ ] T-047: БАГФИКС: Alan Greeting Video — сервис никогда не срабатывает (High)
  - Поднять diagnostic-логи c DEBUG до INFO уровня в `handlers/alan_greeting.py` (строки 84, 87), чтобы join-события были видны в Better Stack.
  - Добавить уникальный lambda-фильтр `event.new_chat_member.user.id == settings.ALAN_USER_ID` в `alan_greeting_router` для архитектурного разделения с `slava_presence_router` (у обоих `ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER)`).
  - Написать интеграционный тест с обоими роутерами на одном dispatcher — проверка отсутствия конфликтов фильтров.
- [ ] T-052: БАГФИКС: Dead Page Relay — sequential scanning для sparse channels (Critical)
  - Проблема: текущий алгоритм (random probing, 5 retries/range, 35 total attempts) работает для DENSE каналов, но проваливается на SPARSE каналах (1 пост из 2000 ID — вероятность попадания ~2%). Production log: chat_id=5885953495, DB last_msg_id=100, все 7 ranges exhausted, fallback на локальные медиа.
  - Решение: добавить sequential scanning для narrow ranges (≤ 50 ID). При обнаружении narrow range (`hi - lo <= 50`) переключаться с random probing на линейное сканирование ID от lo до hi включительно. Range (1,10) гарантированно найдёт пост с message_id=3.
  - Изменения: модифицировать `_probe_range()` в `services/dead_page_relay.py` — перед random retries проверить `if hi - lo + 1 <= 50`, затем перебор ID последовательно через `bot.forward_messages()` с проверкой исключений.
  - Логирование: INFO при входе в sequential mode ("Narrow range [lo,hi]: switching to sequential scan"), INFO при успешном нахождении ("Sequential scan hit: message_id=X at attempt Y").

---

## Epic 9: Admin Test Commands (2026-07-14)

> **Цель:** Добавить команды Telegram для ручного тестирования фич админом.
> Первый в проекте command handler и первый опыт удаления сообщений ботом.
> 
> **Контекст:** На данным момент в кодовой базе нет ни одного command handler'а
> (Message.filter(F.text.startswith("/"))), ни одного вызова delete_message.
> Оба механизма реализуются с нуля. Команды регистрируются в общем роутере
> `handlers/admin_commands.py` на позиции 0 в `bot.py` (перед всеми существующими).

### Конфигурация
- [ ] T-048: Admin test command для dead_page_relay (`/deadpage`)
  - `config/settings.py` + `.env.example`: добавить `ADMIN_USER_ID=5885953495`
  - Создать `handlers/admin_commands.py` — `admin_router: Router`
  - `Message.filter(F.text.startswith("/deadpage"))`
  - DM (private chat): работает для любого пользователя
  - Группы: работает только для админа (`message.from_user.id == settings.ADMIN_USER_ID`), не-админам — игнорировать (молча)
  - После успешной обработки: `await message.delete()` — удаление команды из чата
  - Основная логика: `await relay.send_dead_page(chat_id, slot="manual")` — отправка dead-page (channel forward или local fallback), бот автоматически отвечает постом в чат
  - Comprehensive logging (info: команда получена, dead page отправлен; warning: не-админ в группе; error: delete_message failure)
  - Регистрация в `bot.py`: позиция 0 (перед `slava_presence_router`), инжект relay через `setup_admin_commands(relay)` или замыкание

- [ ] T-049: Admin test command для alan_greeting (`/alangreet`)
  - Добавить handler в `handlers/admin_commands.py` (тот же роутер, что T-048)
  - `Message.filter(F.text.startswith("/alangreet"))`
  - DM: работает для любого пользователя
  - Группы: админ только (`ADMIN_USER_ID`)
  - `await message.delete()` — удаление команды из чата
  - Логика: импортировать `_send_greeting` из `handlers.alan_greeting` → `await _send_greeting(message.bot, chat_id)` — отправка greeting-видео с caption `@Alan_Z`
  - Comprehensive logging: команда получена, greeting отправлен/не отправлен
  - Регистрация: тот же `admin_router`, уже зарегистрированный в T-048

### Верификация
- [ ] T-050: Запустить тест-сьют pytest, убедиться в отсутствии регрессий
- [ ] T-051: Написать тесты на admin_commands (минимум 6 тестов):
  - DM: /deadpage → relay.send_dead_page вызван с slot="manual", сообщение удалено
  - DM: /alangreet → _send_greeting вызван, сообщение удалено
  - Группа: админ (5885953495) → команда срабатывает
  - Группа: не-админ → команда игнорируется
  - DM: delete_message error → logged but not fatal
  - Группа: delete_message error → logged but not fatal

---

**Status: Epic 1–8 DONE (Epic 7 in planning). Epic 9: Admin Test Commands — T-048 through T-051 ready for development.**
**Date: 2026-07-14**
