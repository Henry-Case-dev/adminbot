# AdminBot — Kanban Board

## 📋 Backlog

### Epic 9: Admin Test Commands (2026-07-14)
- [ ] T-048: `/deadpage` — ручной вызов DeadPageRelay.send_dead_page(). DM: всем. Группа: админу. Сообщение команды удаляется. Новый handlers/admin_commands.py + config ADMIN_USER_ID=5885953495 + регистрация router #0 в bot.py.
- [ ] T-049: `/alangreet` — ручной вызов _send_greeting() с @Alan_Z видео. DM: всем. Группа: админу. Сообщение удаляется. В том же admin_commands.py.
- [ ] T-050: Прогнать pytest — убедиться в отсутствии регрессий
- [ ] T-051: Написать тесты на admin_commands (6 тестов: DM deadpage, DM alangreet, группа админ, группа не-админ, DM delete error, группа delete error)

### Epic 8: Alan Greeting Video (F7) — 2026-07-13
- [ ] T-038: Add ALAN_USERNAME, ALAN_USER_ID and ALAN_GREETING_DIR to config/settings.py + .env.example
- [ ] T-039: Create handlers/alan_greeting.py (ChatMemberUpdated join + new_chat_members fallback + random video send_video + @Alan_Z caption + logging)
- [ ] T-040: Register alan_greeting_router in bot.py (position 1, alongside slava_presence_router)
- [ ] T-041: Write tests/test_alan_greeting.py (7-8 tests: join, non-Alan, leave, fallback, random, caption, empty dir, error)
- [ ] T-042: Update ARCHITECTURE.md (F7 data flow, router order, directory listing)
- [ ] T-043: Update MEMORY.md (project state, features table)
- [ ] T-044: Run all tests — verify no regressions
- [ ] T-045: Code review and QA

### Bugfixes (Critical/High)
- [ ] T-046: Dead Page Relay — ALL RANGES EXHAUSTED. Fix `_build_search_ranges()` fallback to `_DISCOVERY_RANGES`; fix dedup `continue` burning attempt slots.
- [ ] T-047: Alan Greeting Video — service never fires. Raise logs DEBUG→INFO; add unique lambda filter `user.id == ALAN_USER_ID`; integration test with both routers.
- [ ] T-052: Dead Page Relay — sequential scanning for sparse channels. Add linear scan for narrow ranges (≤ 50 ID) in `_probe_range()` to guarantee hit on sparse channels (1 post out of 2000 IDs). Switch from random probing to sequential forward_messages() when `hi - lo ≤ 50`.

### Epic 7: Better Stack Monitoring Integration
- [ ] T-029: Add sentry-sdk==2.64.0 and logtail-python==0.4.0 to requirements.txt
- [ ] T-030: Install sentry-sdk and logtail-python into project venv
- [ ] T-031: Add SENTRY_DSN and LOGTAIL_SOURCE_TOKEN to .env.example
- [ ] T-032: Add SENTRY_DSN and LOGTAIL_SOURCE_TOKEN to .env (create from .env.example if missing)
- [ ] T-033: Initialize Sentry SDK in bot.py (after load_dotenv, traces_sample_rate=1.0)
- [ ] T-034: Configure LogtailHandler on root logger alongside StreamHandler
- [ ] T-035: Write and run smoke test script — test log + test error to verify cloud delivery
- [ ] T-036: Run pytest — verify no regressions

## 🔧 In Progress

## ✅ Done

### Epic 6: Dead Page V2 — Event-driven reposts
- [x] T-018: Update config/settings.py + .env.example (new params, remove MORNING_HOUR/EVENING_HOUR/POLL_INTERVAL)
- [x] T-019: Update plan DEAD_PAGE_V2_PLAN.md with user feedback (forward + channel 4228645624 + fallback)
- [x] T-020: Create services/dead_page_relay.py (channel forward + fallback)
- [x] T-021: Create handlers/dead_page_trigger.py (repost detector, forward_origin filter)
- [x] T-022: Simplify services/scheduler.py (remove loop, keep join trigger only)
- [x] T-023: DB migration (channel_state table, timestamp column, new methods)
- [x] T-024: Update bot.py (register dead_page_router #4, init DeadPageRelay, wire to slava_presence)
- [x] T-025: Add comprehensive logging to dead_page module (relay, trigger, scheduler, DB)
- [x] T-026: Update MEMORY.md and ARCHITECTURE.md (new F2 architecture, router order, DB schema)
- [x] T-027: Write/rewrite tests (test_dead_page_relay.py, test_dead_page_trigger.py, drop old scheduler tests, update test_database.py)
- [x] T-028: Run all tests and verify coverage (all new functions covered, no regressions)

### Epic 1: Рефакторинг
- [x] T-001: Вынести API_TOKEN в .env / конфигурацию
- [x] T-002: Создать requirements.txt с закреплёнными версиями
- [x] T-003: Создать единую структуру проекта (config/, handlers/, filters/, services/, tests/)
- [x] T-004: Унифицировать обработку ошибок и логирование
- [x] T-005: Создать общий базовый класс для фильтров

### Epic 2: Новые функции
- [x] T-006 (F1): При возвращении Славы в чат → «ДОЛБОЕБ ВЕРНУЛСЯ» + new_chat_members fallback
- [x] T-007 (F2): Dead-page посты — рандомное фото + текст 2x/день + при входе
- [x] T-008 (F3): Каждые 5 сообщений → GIF через MessageCounterMiddleware
- [x] T-009 (F4): «КУЧА» → «ДАЛБАЕБ» с KuchaWordFilter (precise regex)
- [x] T-010 (F5): Военные слова → «трясло ебаное» для Славы (WarWordFilter)
- [x] T-011 (F6): Каждые 10 сообщений @Alan_Z (id 138811255) → reply random-фразой (UserIdFilter + DB counter)

### Epic 3: Тестирование и CI
- [x] T-012: Модульные тесты на все хендлеры (109 тестов, 12 файлов)
- [x] T-013: Тесты на все корнер-кейсы (пустой текст, нецелевой пользователь, границы)
- [x] T-014: Интеграционные тесты (unit tests покрывают все компоненты; H3 deferred)

### Epic 4: Документация
- [x] T-015: README.md с ироничной документацией

### Epic 5: Багфиксы
- [x] T-016 (Kostik): Probability-based reply engine + extensible pool (KOSTIK_REPLY_PROBABILITY)
- [x] T-017 (Kucha): Fix KuchaWordFilter regex — remove "ек" from optional group
- [x] B1: KuchaWordFilter — precise declension matching regex
- [x] H1: Filter-level tests for VasyaFilter, StrictAdminFilter
- [x] H2: Legacy modules deleted (kostik, slavik, vasya)
- [x] M1: new_chat_members fallback for F1
- [x] M4: DB fixture stable (manual event loop)
- [x] M5: All settings env-configurable via settings.py
- [x] L3: on_shutdown cleanup hook in bot.py

### Remaining LOW (not blocking)
- [ ] H3: Dispatcher integration tests — deferred
- [ ] L1: README platform-specific Windows commands
- [ ] L2: Quoting in response text (reply_to covers)
- [ ] L4: MediaService cache invalidation
- [ ] L5: VasyaFilter translit order edge case

## 👤 Architect
- [ ] T-037: Update ARCHITECTURE.md with monitoring section (@Architect)

---

**Updated:** 2026-07-14 — Epic 9 (Admin Test Commands) added to Backlog (T-048–T-051). First command handlers + message deletion in project.
