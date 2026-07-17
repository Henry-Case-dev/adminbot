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

- [ ] T-053: БАГФИКС: Propagation-stopping bug в slava_presence.py — F7 Alan greeting полностью сломана в production (Critical)
  - Проблема: три хендлера в `handlers/slava_presence.py` (`on_user_join`, `on_user_leave`, `on_new_slava_member`) возвращают `None` (bare `return`) когда пользователь не Slava. В aiogram 3.x возврат `None` из обработчика останавливает propagation события. Поскольку `slava_presence_router` зарегистрирован ПЕРЕД `alan_greeting_router`, он перехватывает ВСЕ join-события, и Alan's router никогда их не получает. F7 сломана полностью.
  - Fix 1 (PRIMARY, @Builder): Возвращать `UNHANDLED` из хендлеров slava_presence.py
    - Файл: `handlers/slava_presence.py`
    - Импортировать `UNHANDLED` из aiogram
    - В `on_user_join` (строка ~33): `return` → `return UNHANDLED` когда `user.id != SLAVIK_USER_ID`
    - В `on_user_leave` (строка ~63): `return` → `return UNHANDLED` когда `user.id != SLAVIK_USER_ID`
    - В `on_new_slava_member` (строка ~75): `return` → `return UNHANDLED` когда `not message.new_chat_members`
  - Fix 2 (DEFENCE-IN-DEPTH, @Builder): Убрать или конвертировать избыточную проверку user ID в alan_greeting.py
    - Файл: `handlers/alan_greeting.py`
    - В `on_alan_join` (строки ~87-89): проверка `if user.id != settings.ALAN_USER_ID: return` избыточна, поскольку lambda-фильтр в декораторе уже гарантирует вызов только для Alan. Убрать или конвертировать в `return UNHANDLED`.
  - Fix 3 (TESTS, @Builder): Добавить интеграционный тест с реальной диспетчеризацией
    - Текущий `test_both_routers_dispatch_correctly` вызывает `on_alan_join()` напрямую — в обход диспетчера
    - Новый тест: создать Dispatcher, зарегистрировать оба роутера, скормить `ChatMemberUpdated` update, проверить что Alan's greeting срабатывает (send_video вызван)
    - Новый тест: проверить что когда slava_presence возвращает `UNHANDLED`, propagation продолжается к следующему роутеру
  - Fix 4: НЕ РЕАЛИЗОВАНО (UserIdFilter на уровне декоратора для Slava — не нужен если Fix 1 работает)

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

## Epic 10: War Words Redesign (F5) — 2026-07-16

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
  - **Backward compatibility:** Существующие 27 keyword форм сохраняются. Формат списка не меняется — легко добавлять новые слова
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
  - **Current:** Одиночный хардкод `"трясло ебаное"` в `war_word_handler` (handlers/slavik.py:19)
  - **New:** Extensible reply pool в виде списка строк
  - **Initial pool (5 phrases):**
    1. `"потрясись"`
    2. `"повизжи"`
    3. `"прячься под шконку быстрее"`
    4. `"закрой ушки и считай до десяти"`
    5. `"поплачь"`
  - **Selection:** `random.choice(WAR_REPLIES)` — как в `ALAN_REPLIES` в handlers/alan.py:93
  - **Extensibility:** Добавление новой фразы = новая строка в списке. Опционально: env-конфигурируемый пул (`WAR_WORDS_REPLY_POOL`) из T-059
  - **Backward compatibility:** Старый `"трясло ебаное"` убран; новый пул используется и в war_word_handler (keyword match), и в war_words_trigger (channel repost)
  - **Reply mechanism:** `await message.reply(reply_text)` — reply_to mechanism (уже используется)

### Logging
- [ ] T-057: Add comprehensive Better Stack logging
  - **Levels:**
    - `INFO`: keyword matched (какое слово, chat_id, user_id), channel repost detected, reply sent
    - `WARNING`: filter miss (caption empty, origin not channel)
    - `ERROR`: handler failures
  - **Context per log:** chat_id, user_id, matched keyword, channel source, chosen reply text
  - **Files to instrument:** `filters/war_word.py`, `handlers/slavik.py` (war_word_handler), `handlers/war_words_trigger.py`
  - **Consistency:** Использовать тот же стиль логов, что в dead_page_trigger.py и alan.py

### Testing
- [ ] T-058: Create/extend tests — filter, handler, integration
  - **Filter tests** (`tests/test_war_word_filter.py` — новый файл, ~12 tests):
    - text-only match (existing keywords)
    - caption match (новые keywords)
    - empty text + empty caption → no match
    - caption-only match → match
    - text present but no war word → no match
    - caption present but no war word → no match
    - all new keyword forms (опасность, БПЛА, ракетная, etc.)
    - case insensitivity (бпла, БПЛА, Бпла)
    - word boundary test — "внимание" matches, "внимательный" doesn't
    - non-Slava user with war word — filter passes, handler ignores (проверка UserIdFilter)
  - **Handler tests** (`tests/test_slavik_handlers.py` — обновить, ~6 tests):
    - war word keyword → random reply from pool (verify reply in WAR_REPLIES)
    - verify `message.reply()` called (reply_to mechanism)
    - verify randomness (run 10x, assert at least 2 different replies)
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
    - multiple channels in list — ID match works for any
  - **Integration tests** (`tests/test_slavik_handlers.py` — обновить):
    - full pipeline: handler registered on dispatcher → message → reply

### Configuration
- [ ] T-059: Update `config/settings.py` with new env vars + `.env.example`
  - `WAR_WORDS_CHANNEL_IDS`: list[int] — ID военных каналов для репост-детекции (default: [1654872411])
  - `WAR_WORDS_CHANNEL_USERNAMES`: list[str] — usernames военных каналов (default: [])
  - `WAR_WORDS_REPLY_POOL`: list[str] — опциональный env-переопределяемый пул ответов (default: пустой — используется хардкод-пуль в коде из T-056)
  - Формат в .env: comma-separated (напр. `WAR_WORDS_CHANNEL_IDS=1654872411,123456789`)

### Integration
- [ ] T-060: Register `war_words_trigger_router` in `bot.py`
  - **Position:** Между dead_page_router (#4) и slavik_router (#5)
  - **Rationale:** Репост-детекция должна срабатывать до slavik catch-all, но после dead_page_trigger
  - **Actual position:** 4b в router order
  - **Wire-up:** `setup_war_words_trigger()` — аналог `setup_dead_page()`, если нужны зависимости

### Documentation
- [ ] T-061: Update README — document F5 v2
  - Expanded keyword list (categories: дроны, ракеты, опасность, убежища, оповещение)
  - Channel repost detection (список каналов)
  - Random reply pool (5 phrases, extensible)
  - Caption support (bugfix)
  - Link to new env vars in .env.example

### QA & Deploy
- [ ] T-062: Run full pytest suite — verify no regressions, all new functions covered
  - Target: ~28 новых тестов (12 filter + 6 handler + 10 trigger)
  - Verify: существующие 190 тестов не сломаны
  - Coverage: 100% новых функций
- [ ] T-063: Deploy to server
  - Git pull, restart bot
  - Smoke test: send war keyword → random reply; forward from target channel → random reply
  - Verify Better Stack logs appear

---

## Epic 11: Alan Silence Greeting (F7 v2 — "Леха проснулся") — 2026-07-18

> **Цель:** Расширить F7 (Alan Greeting Video). Кроме приветствия при join-событии,
> бот должен отправлять то же самое приветственное видео, когда Алан (id 138811255,
> @Alan_Z) присутствует в чате, молчит дольше N часов, а затем пишет любое сообщение.
> Если Алан пишет раньше, чем истекли N часов — таймер молчания сбрасывается без
> отправки приветствия. N по умолчанию = 6 часов (эмуляция "сна"), настраивается
> через .env, значение 0 = функция отключена. После реализации и тестов — выставить
> N=2 часа на проде для живого теста.
>
> **Контекст:** Учитываются ТОЛЬКО сообщения самого Алана (id 138811255) — сообщения
> других пользователей не влияют на его таймер молчания. Приветствие переиспользует
> существующую `_send_greeting(bot, chat_id)` из `handlers/alan_greeting.py` (F7,
> случайное видео из `media/leha_greeting/`). Фича должна работать независимо от
> join-cooldown F7 (`_last_greeting` / `ALAN_GREETING_COOLDOWN`) — это разные триггеры
> (join vs "проснулся после сообщения"), но нужно явно проверить и протестировать
> отсутствие конфликтов между ними.
>
> **ВАЖНО — изоляция:** Фича не должна трогать порядок роутеров, F1-F6/F8, Epic10
> (war_alert), admin_commands. Новая логика трекинга сообщений Алана должна
> ОБЯЗАТЕЛЬНО возвращать `UNHANDLED` (см. баг T-053), чтобы не блокировать
> propagation к другим роутерам, которые тоже реагируют на сообщения Алана
> (F6 alan reply engine — каждое 10-е сообщение, F3 GIF-счётчик и т.д.).

### Архитектурное решение (требуется от @Architect)
- [ ] T-065: **Принять решение о хранилище `last_message_timestamp` Алана** — в памяти
  (dict `{chat_id: float}`, по аналогии с `_last_greeting` в alan_greeting.py) или в БД
  (новая таблица/колонка в `services/database.py`, переживает restart бота).
  - **Рекомендация PM: БД предпочтительнее.** Семантика фичи ("Алан спал N часов") по
    смыслу пользователя не должна ломаться перезапуском бота (деплой, краш, обновление
    зависимостей) — иначе после каждого restart таймер обнуляется и придётся ждать
    заново N часов, что не соответствует ожиданиям пользователя и не эмулирует "сон".
  - In-memory вариант проще и быстрее в реализации, но менее устойчив (см. edge case
    "перезапуск бота" в T-070).
  - **Финальное решение — на @Architect.** Если выбрана БД — учесть миграцию схемы
    (аналогично `channel_state` из Epic 6) и решить, где хранить: новая таблица
    `alan_activity` (chat_id, last_message_ts) или переиспользование `channel_state`
    с составным ключом `alan_last_msg:{chat_id}`.

### Конфигурация
- [ ] T-064: Добавить env-параметр в `config/settings.py` + `.env.example`
  - Предлагаемое имя: `ALAN_SILENCE_GREETING_HOURS` (float или int, часы) — финальное
    имя на усмотрение @Architect/@Builder, если конфликтует со стилем проекта
  - Default: `6` (часов)
  - `0` = функция полностью отключена (без трекинга или с трекингом, но без триггера
    — решить при реализации, см. T-070)
  - Документировать в `.env.example` рядом с существующими `ALAN_*` параметрами (F7)
  - Учесть, что изменение через `.env` требует **перезапуска бота** (dataclass
    `Settings` читается один раз при старте) — задокументировать это явно в комментарии
    к переменной и в README

### Трекинг активности Алана
- [ ] T-066: Реализовать хранение/обновление `last_message_timestamp` для Алана
  (per-chat, независимо в разных чатах) — конкретная реализация (dict или БД-таблица/
  методы `DatabaseService`) зависит от решения T-065
  - Учитывать ТОЛЬКО сообщения от `user.id == settings.ALAN_USER_ID`
  - Обновлять запись при КАЖДОМ сообщении Алана — независимо от того, сработало
    приветствие или нет (см. T-069)
- [ ] T-067: Реализовать перехват сообщений Алана без нарушения propagation
  - Новый handler/роутер ИЛИ встраивание в существующий `alan_router`
    (`handlers/alan.py`) — решение архитектуры/позиции роутера за @Architect/@Builder
  - **Обязательно** возвращать `UNHANDLED`, никогда не блокировать propagation к
    другим роутерам (F6 reply engine, F3 GIF-счётчик и др. также реагируют на
    сообщения Алана) — прямая защита от повторения бага T-053
  - Не менять порядок регистрации существующих роутеров в `bot.py`

### Детект "молчал > N часов → написал"
- [ ] T-068: Реализовать логику сравнения текущего времени сообщения с сохранённым
  `last_message_timestamp`
  - Если `ALAN_SILENCE_GREETING_HOURS == 0` → функция отключена, пропустить проверку
    (но не ломать трекинг обновления таймера, если он всё равно нужен для будущего
    включения фичи без потери истории — решить при реализации)
  - Если разница `now - last_message_timestamp >= ALAN_SILENCE_GREETING_HOURS * 3600`
    → считать, что Алан "проснулся", вызвать `_send_greeting(bot, chat_id)` из
    `handlers/alan_greeting.py` (переиспользование, не дублировать логику выбора видео)
  - Если разница меньше порога → НЕ отправлять приветствие, но таймер всё равно
    обновляется (см. T-069)
- [ ] T-069: Обновление/сброс таймера при КАЖДОМ сообщении Алана
  - Порядок операций: сначала прочитать старый `last_message_timestamp` и вычислить
    разницу/принять решение о триггере, ЗАТЕМ записать новый timestamp = текущее время
  - Обновление происходит независимо от результата триггера (сработало приветствие
    или нет) — это обычное поведение "любое сообщение Алана = новая точка отсчёта сна"

### Edge cases
- [ ] T-070: Покрыть и явно обработать следующие edge cases:
  - **Первое сообщение от Алана вообще** (нет записи `last_message_timestamp` для
    этого чата) — приветствие НЕ отправляется (нет базы для сравнения), просто
    записывается baseline timestamp. Залогировать отдельно ("first message from Alan
    in chat X, baseline recorded, no greeting").
  - **N=0 (отключено)** — проверить, что фича не срабатывает никогда, независимо от
    того, сколько реально прошло времени
  - **N меняется через .env "на лету"** — задокументировать, что изменение требует
    restart бота (см. T-064); никакого hot-reload не реализовывать (не входит в scope)
  - **Несколько чатов независимо** — таймер молчания у Алана в чате A не влияет на
    таймер в чате B; отдельный тест на 2+ чата одновременно
  - **Перезапуск бота** — поведение зависит от решения T-065:
    - если БД: таймер переживает restart (ожидаемое поведение по рекомендации PM)
    - если in-memory: таймер сбрасывается при restart (баг или "as designed" — явно
      задокументировать в README/ARCHITECTURE выбранное поведение, чтобы не считалось
      багом при следующем ревью)
  - **Конфликт/пересечение с F7 join-cooldown** (`_last_greeting` dict, 
    `ALAN_GREETING_COOLDOWN`) — это ДРУГОЙ, независимый триггер и cooldown. Явно
    протестировать сценарий: Алан заходит в чат (join greeting срабатывает) → сразу
    пишет сообщение, но молчал >N часов до этого (по старому timestamp) → нужно
    решить и задокументировать, срабатывает ли второе приветствие подряд, или это
    нежелательное дублирование, которое нужно гасить общим cooldown-ом. Рекомендация
    PM: избегать двух приветствий за короткий промежуток — либо переиспользовать тот
    же `_last_greeting` dict/cooldown как общий "анти-спам" слой для обоих триггеров,
    либо ввести отдельный небольшой cooldown между двумя типами приветствий. Финальное
    решение — на @Architect.

### Логирование (Better Stack)
- [ ] T-071: Добавить детальное логирование каждого этапа
  - `INFO`: сообщение от Алана обработано трекером — chat_id, user_id, elapsed since
    last message (в секундах/часах), сработал ли триггер
  - `INFO`: приветствие после молчания отправлено — chat_id, elapsed_hours, threshold_hours
  - `INFO`: таймер обновлён/сброшен без отправки (молчание короче порога) — chat_id,
    elapsed_hours, threshold_hours
  - `INFO`: первое сообщение от Алана в чате (baseline записан, без приветствия)
  - `WARNING`: функция отключена (N=0), сообщение получено но проверка пропущена
    (логировать один раз на старте бота, не на каждое сообщение — избежать спама логов)
  - `ERROR`: ошибка при чтении/записи timestamp (БД insert/update failure) или ошибка
    при вызове `_send_greeting`
  - Контекст в каждом логе: `chat_id`, `user_id` (всегда `ALAN_USER_ID`), elapsed time,
    threshold value
  - Стиль логов — консистентный с существующими модулями (`alan_greeting.py`,
    `dead_page_trigger.py`)

### Интеграция
- [ ] T-072: Зарегистрировать новую логику в `bot.py` в корректной позиции
  - Не менять порядок существующих роутеров (0, 1, 1b, 2, 3, 4, 4b, 5, 6)
  - Если реализовано как отдельный роутер — определить позицию (вероятно рядом с
    `alan_router`, позиция 3 или 3b) — решение @Architect/@Builder
  - Если встроено в существующий `alan_router`/`alan_greeting.py` — не нарушать их
    текущую логику (F6 reply-каждые-10-сообщений, F7 join-greeting)
  - Явно инициализировать зависимости (DB-соединение, если выбрано БД-хранилище) через
    `setup_*()` паттерн, как в остальных модулях

### Тестирование
- [ ] T-073: Написать тесты, максимальное покрытие
  - Первое сообщение Алана в чате → baseline записан, приветствие НЕ отправлено
  - Молчание >= N часов, затем сообщение Алана → приветствие отправлено
    (`_send_greeting` вызван), таймер сброшен
  - Молчание < N часов → приветствие НЕ отправлено, таймер всё равно обновлён на
    текущее время
  - Сообщение не от Алана (любой другой user_id) → таймер Алана не меняется, никакой
    реакции
  - `ALAN_SILENCE_GREETING_HOURS=0` → приветствие никогда не отправляется, независимо
    от длительности молчания
  - Несколько чатов одновременно — независимые таймеры (2+ чата в одном тесте)
  - Перезапуск/пересоздание сервиса — поведение согласно решению T-065 (тест на
    сохранение состояния если БД, либо явный тест на сброс если in-memory)
  - Тест на отсутствие конфликта с F7 join-cooldown (сценарий из T-070)
  - Интеграционный тест с реальным `Dispatcher`: зарегистрировать все роутеры,
    отправить сообщение от Алана, убедиться что: (а) новая логика сработала,
    (б) `UNHANDLED` дошло до `alan_router` (F6 reply engine не сломан), (в) остальные
    фичи (F3 GIF-счётчик и т.д.) продолжают получать событие
  - Прогнать полный существующий тестовый suite (252+ тестов) — убедиться в отсутствии
    регрессий

### Документация
- [ ] T-074: Переделать README.md — сохранить ироничный стиль, добавить секцию про
  новую фичу (F7 v2 / "Леха проснулся"), обновить таблицу функций/фич, задокументировать
  новый env-параметр из T-064 и его семантику (0 = выключено, требует restart)

### QA & Deploy
- [ ] T-075: Прогнать полный pytest suite — убедиться в отсутствии регрессий по всем
  8 роутерам и остальным Epic (1-10), проверить покрытие новых функций
- [ ] T-076: Коммит на русском по conventional commits в `main`, пуш
- [ ] T-077: Деплой на сервер + выставить `ALAN_SILENCE_GREETING_HOURS=2` в
  production `.env` для живого теста (вместо дефолтных 6 часов) — согласно
  требованию пользователя

---

**Status: Epic 1–8 DONE. Epic 9: Admin Test Commands — T-048 through T-051 ready. T-053 (Critical — F7 propagation bug) in Bugfixes. Epic 10: War Words Redesign — T-054 through T-063 in planning. Epic 11: Alan Silence Greeting (F7 v2) — T-064 through T-077 in planning, requires @Architect decision (T-065) before implementation.**
**Date: 2026-07-18**
