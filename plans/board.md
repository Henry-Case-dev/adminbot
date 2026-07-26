# AdminBot — Kanban Board

## 📋 Backlog

### Epic 13: Otboy Service (F9) — 2026-07-26 🔵 NEW
- [ ] T-084: Архитектурное проектирование и ревью (sub-agent review до реализации)
  - [ ] T-084-A: Спроектировать архитектуру сервиса — модули, изоляция, поток данных
  - [ ] T-084-B: Sub-agent ревью архитектуры — проверить изоляцию, масштабируемость, отсутствие влияния на другие фичи
  - [ ] T-084-C: Согласовать финальный дизайн с PM
- [ ] T-085: Создать `filters/otboy_word.py` — OtboyWordFilter
  - [ ] T-085-A: Реализовать фильтр — проверка `message.text`, `message.caption`, `message.forward_origin` (text forwarded-сообщений)
  - [ ] T-085-B: Детект слова "отбой" (регистронезависимый, word-boundary)
  - [ ] T-085-C: Логирование срабатывания фильтра (INFO: chat_id, user_id, source field)
- [ ] T-086: Создать `services/otboy_relay.py` — OtboyRelay (standalone scalable service)
  - [ ] T-086-A: Реализовать OtboyRelay — инкапсулированный сервис без глобального состояния
  - [ ] T-086-B: Метод `send_otboy(chat_id, reply_to_message_id, quote_text)` — отправка `media/otboy.jpg` с reply_to + цитированием
  - [ ] T-086-C: Cooldown-логика — проверка `OTBOY_COOLDOWN_SECONDS`, thread-safe
  - [ ] T-086-D: Comprehensive logging (INFO: photo sent, cooldown active, cooldown expired)
- [ ] T-087: Создать `handlers/otboy.py` — otboy_router
  - [ ] T-087-A: Handler: OtboyWordFilter → вызов OtboyRelay.send_otboy()
  - [ ] T-087-B: Reply с `reply_to_message_id` (Telegram native reply-to)
  - [ ] T-087-C: Цитирование ТОЛЬКО слова "отбой" через Telegram quote API (native citation)
  - [ ] T-087-D: Обработка ошибок (файл не найден, Telegram API error)
- [ ] T-088: Конфигурация — `OTBOY_COOLDOWN_SECONDS` в `config/settings.py` + `.env.example`
  - [ ] T-088-A: Добавить `OTBOY_COOLDOWN_SECONDS: int = 0` (0 = no cooldown)
  - [ ] T-088-B: Обновить `.env.example` с описанием параметра
- [ ] T-089: Зарегистрировать `otboy_router` в `bot.py`
  - [ ] T-089-A: Определить правильную позицию в router order (до user-specific роутеров, после системных)
  - [ ] T-089-B: Зарегистрировать роутер с include_router
  - [ ] T-089-C: Инициализировать OtboyRelay при старте
  - [ ] T-089-D: Убедиться, что роутер не влияет на propagation других хендлеров
- [ ] T-090: Тесты для Otboy Service (~10 тестов)
  - [ ] T-090-A: Фильтр — текст с "отбой" → срабатывает
  - [ ] T-090-B: Фильтр — caption с "отбой" → срабатывает
  - [ ] T-090-C: Фильтр — forwarded message text с "отбой" → срабатывает
  - [ ] T-090-D: Фильтр — текст без "отбой" → не срабатывает
  - [ ] T-090-E: Фильтр — регистронезависимость ("Отбой", "ОТБОЙ")
  - [ ] T-090-F: Хендлер — reply_to_message_id совпадает с исходным message_id
  - [ ] T-090-G: Хендлер — quote захватывает только слово "отбой"
  - [ ] T-090-H: Cooldown — второй вызов в пределах cooldown не отправляет фото
  - [ ] T-090-I: Cooldown — после истечения cooldown фото отправляется снова
  - [ ] T-090-J: Интеграционный тест — проверка propagation (не блокирует другие хендлеры)
- [ ] T-091: Обновление документации — README, ARCHITECTURE, MEMORY
  - [ ] T-091-A: README.md — добавить секцию F9 (Otboy Service)
  - [ ] T-091-B: ARCHITECTURE.md — router order, data flow, OtboyRelay
  - [ ] T-091-C: MEMORY.md — project state, features table, version bump
- [ ] T-092: Деплой на сервер + smoke tests
  - [ ] T-092-A: Git pull на сервер
  - [ ] T-092-B: Обновить .env (если переопределён OTBOY_COOLDOWN_SECONDS)
  - [ ] T-092-C: Restart бота
  - [ ] T-092-D: Smoke test: сообщение с "отбой" → reply с otboy.jpg
  - [ ] T-092-E: Smoke test: forwarded-сообщение с "отбой" → reply с otboy.jpg
  - [ ] T-092-F: Smoke test: проверить, что другие фичи не сломаны
  - [ ] T-092-G: Verify Better Stack логи

---

## 🔧 In Progress

*(нет активных задач)*

---

## ✅ Done

### Epic 12: Багфикс репостов + slavic_na_litso.jpg — 2026-07-25
- [x] T-078: Расследование и исправление бага с репостами Славы (war_alert не ловит forwarded messages)
  - [x] T-078-A: Расследование — diagnostic-логи, проверка гипотез (UserIdFilter для forwarded, message.text/caption, порядок хендлеров, propagation)
  - [x] T-078-B: Исправление бага
  - [x] T-078-C: Comprehensive logging для forwarded-сообщений
- [x] T-079: Реализация фичи — slavic_na_litso.jpg каждый N-й ответ "пошёл нахуй"
  - [x] T-079-A: Добавить `SLIVIC_NA_LITSO_INTERVAL` в config/settings.py + .env.example
  - [x] T-079-B: Добавить счётчик в DatabaseService
  - [x] T-079-C: Модифицировать slavik_catchall_handler в handlers/slavik.py
  - [x] T-079-D: Comprehensive logging
- [x] T-080: Тесты для багфикса репостов (test_war_alert.py — 6 тестов)
- [x] T-081: Тесты для фичи slavic_na_litso.jpg (test_slavik_handlers.py — 8 тестов)
- [x] T-082: Обновление README + ARCHITECTURE.md + MEMORY.md, коммит, пуш
- [x] T-083: Деплой на сервер + smoke tests

### Epic 11: Alan Silence Greeting (F7v2 — "Леха проснулся") — 2026-07-18
- [x] T-064: Добавить ALAN_SILENCE_GREETING_HOURS в config/settings.py + .env.example
- [x] 👤 T-065 (@Architect): Решение о хранилище — БД через channel_state
- [x] T-066: Реализовать get/set_alan_last_message_ts в DatabaseService
- [x] T-067: Встроить silence-логику в alan_handler (handlers/alan.py)
- [x] T-068: Логика детекта "молчал >= N часов → написал" → _send_greeting()
- [x] T-069: Обновление таймера при КАЖДОМ сообщении Алана
- [x] T-070: Edge cases — baseline, N=0, несколько чатов, restart persistence, cooldown
- [x] T-071: Детальное логирование каждого этапа
- [x] T-072: Интеграция в bot.py — без изменения порядка роутеров
- [x] T-073: Тесты — 19 новых тестов
- [x] T-074: Обновить README.md
- [x] T-075: Прогнать полный pytest suite — 271 тест, без регрессий
- [x] T-076: Коммит на русском в main, пуш
- [x] T-077: Деплой на сервер + ALAN_SILENCE_GREETING_HOURS=2

### Epic 10: War Words Redesign (F5v2) — 2026-07-16
- [x] T-054: Fix WarWordFilter — caption support + expand WAR_WORDS keywords (90+ форм)
- [x] T-055: Add channel repost detection handler for military channels (war_words_trigger.py)
- [x] T-056: Replace single hardcoded reply with extensible pool + random.choice()
- [x] T-057: Add comprehensive Better Stack logging
- [x] T-058: Create/extend tests — filter, handler, integration (~28 tests)
- [x] T-059: Update config/settings.py — WAR_CHANNEL_IDS, WAR_CHANNEL_USERNAMES, WAR_REPLIES
- [x] T-060: Register war_alert_router in bot.py (position 4b)
- [x] T-061: Update README — document F5v2
- [x] T-062: Run full pytest suite — verify no regressions (~280 tests)
- [x] T-063: Deploy to server

### Epic 9: Admin Test Commands (2026-07-14)
- [x] T-048: /deadpage — ручной вызов DeadPageRelay.send_dead_page()
- [x] T-049: /alangreet — ручной вызов _send_greeting()
- [x] T-050: Прогнать pytest — без регрессий
- [x] T-051: Тесты на admin_commands (6 тестов)

### Epic 8: Alan Greeting Video (F7) — 2026-07-13
- [x] T-038: Add ALAN_USERNAME, ALAN_USER_ID, ALAN_GREETING_DIR to config
- [x] T-039: Create handlers/alan_greeting.py (join + fallback + video + caption)
- [x] T-040: Register alan_greeting_router in bot.py (position 1b)
- [x] T-041: Write tests/test_alan_greeting.py (7-8 tests)
- [x] T-042: Update ARCHITECTURE.md
- [x] T-043: Update MEMORY.md
- [x] T-044: Run all tests — no regressions
- [x] T-045: Code review and QA

### Epic 7: Better Stack Monitoring Integration (2026-07-12)
- [x] T-029: Add sentry-sdk==2.64.0 and logtail-python==0.4.0 to requirements.txt
- [x] T-030: Install sentry-sdk and logtail-python into venv
- [x] T-031: Add SENTRY_DSN and LOGTAIL_SOURCE_TOKEN to .env.example
- [x] T-032: Add SENTRY_DSN and LOGTAIL_SOURCE_TOKEN to .env
- [x] T-033: Initialize Sentry SDK in bot.py
- [x] T-034: Configure LogtailHandler on root logger
- [x] T-035: Write and run smoke test
- [x] T-036: Run pytest — no regressions
- [x] T-037: Update ARCHITECTURE.md with monitoring section

### Epic 6: Dead Page V2 — Event-driven reposts
- [x] T-018: Update config/settings.py + .env.example
- [x] T-019: Update DEAD_PAGE_V2_PLAN.md
- [x] T-020: Create services/dead_page_relay.py
- [x] T-021: Create handlers/dead_page_trigger.py
- [x] T-022: Simplify services/scheduler.py
- [x] T-023: DB migration (channel_state, timestamp, new methods)
- [x] T-024: Update bot.py (register dead_page_router #4, init DeadPageRelay)
- [x] T-025: Add comprehensive logging to dead_page modules
- [x] T-026: Update MEMORY.md and ARCHITECTURE.md
- [x] T-027: Write/rewrite tests
- [x] T-028: Run all tests and verify coverage

### Epic 1: Рефакторинг
- [x] T-001: Вынести API_TOKEN в .env / конфигурацию
- [x] T-002: Создать requirements.txt с закреплёнными версиями
- [x] T-003: Создать единую структуру проекта
- [x] T-004: Унифицировать обработку ошибок и логирование
- [x] T-005: Создать общий базовый класс для фильтров

### Epic 2: Новые функции
- [x] T-006 (F1): При возвращении Славы в чат → «ДОЛБОЕБ ВЕРНУЛСЯ»
- [x] T-007 (F2): Dead-page посты — рандомное фото + текст
- [x] T-008 (F3): Каждые 5 сообщений → GIF через MessageCounterMiddleware
- [x] T-009 (F4): «КУЧА» → «ДАЛБАЕБ» с KuchaWordFilter
- [x] T-010 (F5): Военные слова → «трясло ебаное» (DEPRECATED — заменено на F5v2)
- [x] T-011 (F6): Каждые 10 сообщений @Alan_Z → reply random-фразой

### Epic 3: Тестирование и CI
- [x] T-012: Модульные тесты на все хендлеры
- [x] T-013: Тесты на все корнер-кейсы
- [x] T-014: Интеграционные тесты

### Epic 4: Документация
- [x] T-015: README.md с ироничной документацией

### Epic 5: Багфиксы
- [x] T-016 (Kostik): Probability-based reply engine + extensible pool
- [x] T-017 (Kucha): Fix KuchaWordFilter regex

### Bugfixes (Critical/High) — 2026-07-13 to 2026-07-15
- [x] T-046: Dead Page Relay — ALL RANGES EXHAUSTED (Critical)
- [x] T-047: Alan Greeting Video — service never fires (High)
- [x] T-052: Dead Page Relay — sequential scanning for sparse channels (Critical)
- [x] T-053: Propagation-stopping bug in slava_presence.py — F7 completely broken (Critical)

### Remaining LOW (not blocking)
- [ ] H3: Dispatcher integration tests — deferred
- [ ] L1: README platform-specific Windows commands
- [ ] L2: Quoting in response text (reply_to covers)
- [ ] L4: MediaService cache invalidation
- [ ] L5: VasyaFilter translit order edge case

---

**Updated:** 2026-07-26 — Epic 13 (Otboy Service F9) added to Backlog. Epics 10 и 12 moved to Done (implemented in v2.9.0–v2.9.2, not previously checked off). v2.9.2 — 280 tests.

(End of file)
