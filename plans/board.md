# AdminBot — Kanban Board

## 📋 Backlog

### Epic 12: Багфикс репостов + slavic_na_litso.jpg (2026-07-25) 🔵 NEW
- [ ] T-078: Расследование и исправление бага с репостами Славы (war_alert не ловит forwarded messages)
  - [ ] T-078-A: Расследование — diagnostic-логи, проверка гипотез (UserIdFilter для forwarded, message.text/caption, порядок хендлеров, propagation)
  - [ ] T-078-B: Исправление бага (зависит от результатов расследования)
  - [ ] T-078-C: Comprehensive logging для forwarded-сообщений
- [ ] T-079: Реализация фичи — slavic_na_litso.jpg каждый N-й ответ "пошёл нахуй"
  - [ ] T-079-A: Добавить `SLIVIC_NA_LITSO_INTERVAL` в config/settings.py + .env.example
  - [ ] T-079-B: Добавить счётчик в DatabaseService
  - [ ] T-079-C: Модифицировать slavik_catchall_handler в handlers/slavik.py
  - [ ] T-079-D: Comprehensive logging
- [ ] T-080: Тесты для багфикса репостов (test_war_alert.py — 6 тестов)
- [ ] T-081: Тесты для фичи slavic_na_litso.jpg (test_slavik_handlers.py — 8 тестов)
- [ ] T-082: Обновление README + ARCHITECTURE.md + MEMORY.md, коммит, пуш
- [ ] T-083: Деплой на сервер + smoke tests

### Epic 10: War Words Redesign (F5v2) — 2026-07-16 🔵 PLANNING
- [ ] T-054: Fix WarWordFilter — caption support + expand WAR_WORDS keywords (90+ форм)
- [ ] T-055: Add channel repost detection handler for military channels (war_words_trigger.py)
- [ ] T-056: Replace single hardcoded reply with extensible pool + random.choice()
- [ ] T-057: Add comprehensive Better Stack logging
- [ ] T-058: Create/extend tests — filter, handler, integration (~28 tests)
- [ ] T-059: Update config/settings.py — WAR_CHANNEL_IDS, WAR_CHANNEL_USERNAMES, WAR_REPLIES
- [ ] T-060: Register war_alert_router in bot.py (position 4b)
- [ ] T-061: Update README — document F5v2
- [ ] T-062: Run full pytest suite — verify no regressions (~299 tests)
- [ ] T-063: Deploy to server

---

## 🔧 In Progress

*(нет активных задач)*

---

## ✅ Done

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

**Updated:** 2026-07-25 — Epic 12 (Bugfix Reposts + slavic_na_litso.jpg) added to Backlog. Epic 11 moved to Done. Epics 7-9 and bugfixes T-046–T-053 moved to Done. Epic 10 (War Words Redesign) stays in Backlog/Planning.