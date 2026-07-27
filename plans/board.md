# AdminBot — Kanban Board

## 📋 Backlog

### Epic 15: Common Service — Rename + Media Upgrade + Danger — 2026-07-28 🔵 NEW
- [ ] 👤 T-100 (@Architect): Архитектурное проектирование Common Service + sub-agent review
  - [ ] T-100-A: Спроектировать архитектуру — модули, data flow, directory structure, контракты
  - [ ] T-100-B: Sub-agent ревью — изоляция, масштабируемость, корректность rename, media type detection
  - [ ] T-100-C: Согласовать финальный дизайн с PM
- [ ] T-101: Переименование файлов и модулей (otboy → common)
  - [ ] T-101-A: `handlers/otboy.py` → `handlers/common.py` (router: common_router, сохранить otboy_handler)
  - [ ] T-101-B: `services/otboy_relay.py` → `services/common_relay.py` (OtboyRelay → CommonRelay)
  - [ ] T-101-C: `filters/otboy_word.py` — оставить как есть; СОЗДАТЬ `filters/danger_word.py` (DangerWordFilter)
  - [ ] T-101-D: Обновить все импорты в bot.py (4 строки)
  - [ ] T-101-E: Grep-проверка: нет dead imports/ссылок на "otboy" (кроме otboy_handler)
- [ ] T-102: Конфигурация — переименовать и добавить env-переменные
  - [ ] T-102-A: OTBOY_COOLDOWN_SECONDS → COMMON_COOLDOWN_SECONDS
  - [ ] T-102-B: `OTBOY_PHOTO_PATH` → удалить, добавить `COMMON_MEDIA_BASE = "media/common"` (subdirs: `otboy`/`danger` разрешаются динамически через параметр `subdir`)
  - [ ] T-102-C: Создать директории `media/common/otboy/` и `media/common/danger/` (filesystem migration, см. ARCHITECTURE.md §26.16)
  - [ ] T-102-D: Обновить .env.example (новые ключи с описаниями)
- [ ] T-103: Upgrade media-обработки — directory-based picker с авто-детекцией типа
  - [ ] T-103-A: CommonRelay._pick_media(media_dir) — сканирует директорию, случайный файл
  - [ ] T-103-B: _detect_media_type(filename) → photo/video/animation (jpg/mp4/mp4 с "gif")
  - [ ] T-103-C: _send_media(chat_id, filepath, media_type, reply_params) — dispatcher
  - [ ] T-103-D: send_otboy() — использовать _pick_media + _send_media вместо хардкода
  - [ ] T-103-E: Логирование media type chosen
- [ ] T-104: Новая функция детекции опасных слов (danger)
  - [ ] T-104-A: DangerWordFilter в filters/danger_word.py — DANGER_WORDS + pattern compilation
  - [ ] T-104-B: CommonRelay.send_danger() — _pick_media(DANGER_DIR) + _send_media + reply_to + quote
  - [ ] T-104-C: danger_handler в common.py — DangerWordFilter → relay.send_danger()
  - [ ] T-104-D: Reply-to + quote mechanism — идентичен otboy (ReplyParameters с matched_word)
  - [ ] T-104-E: Comprehensive logging для danger
- [ ] T-105: Интеграция в bot.py — импорты, регистрация, инициализация
  - [ ] T-105-A: Импорты: common_router, setup_common, CommonRelay
  - [ ] T-105-B: dp.include_router(common_router) — позиция 4c сохраняется
  - [ ] T-105-C: on_startup(): CommonRelay(bot, settings.COMMON_COOLDOWN_SECONDS), setup_common(relay)
  - [ ] T-105-D: Проверить propagation (оба handler'а возвращают None)
- [ ] T-106: Тесты (~20+ тестов)
  - [ ] T-106-A: Переименовать test_otboy.py → test_common.py, обновить импорты
  - [ ] T-106-B: Перенести 11 тестов OtboyWordFilter (обновить импорты)
  - [ ] T-106-C: Перенести 6 тестов otboy_handler (OtboyRelay → CommonRelay)
  - [ ] T-106-D: CommonRelay.send_otboy — image → send_photo
  - [ ] T-106-E: CommonRelay.send_otboy — video → send_video
  - [ ] T-106-F: CommonRelay.send_otboy — video с "gif" → send_animation
  - [ ] T-106-G: _pick_media — пустая директория, не-медиа файлы
  - [ ] T-106-H: DangerWordFilter — текст/caption с опасными словами → срабатывает
  - [ ] T-106-I: DangerWordFilter — без слов → False, регистр, word boundary
  - [ ] T-106-J: danger_handler — делегирует в relay.send_danger
  - [ ] T-106-K: CommonRelay.send_danger — случайный медиа, правильный тип
  - [ ] T-106-L: Cooldown — общий для otboy+danger, per-chat изоляция
  - [ ] T-106-M: Интеграция — propagation: common_router не блокирует другие
  - [ ] T-106-N: Интеграция — сообщение с "отбой" и опасным словом → оба handler'а
- [ ] T-107: Обновление документации — README, ARCHITECTURE, MEMORY
  - [ ] T-107-A: README.md — F9 → "Common Service", danger detection, media type matrix
  - [ ] T-107-B: ARCHITECTURE.md — router order 4c: common_router, CommonRelay, data flow
  - [ ] T-107-C: MEMORY.md — project state, features table, v2.12.0
- [ ] T-108: QA — тесты, коммит, деплой
  - [ ] T-108-A: pytest — 316+ тестов, 0 регрессий, coverage ≥ 100% новых модулей
  - [ ] T-108-B: Коммит на русском (conventional commits) в main, пуш
  - [ ] T-108-C: Деплой — git pull, обновить .env, restart
  - [ ] T-108-D: Smoke test: "отбой" → reply с медиа из common/otboy, quote "отбой"
  - [ ] T-108-E: Smoke test: "ракетная опасность" → reply с медиа из common/danger, quote
  - [ ] T-108-F: Smoke test: другие фичи не сломаны (слава, war_alert, алан, вася, костик)
  - [ ] T-108-G: Verify Better Stack логи

---

## 🔧 In Progress

*(нет активных задач)*

---

## ✅ Done

### Epic 14: Media Group Album Fix — 2026-07-28
- [x] T-093: Новая таблица relay_album_map + 3 CRUD метода в database.py
- [x] T-094: channel_post handler в bot.py для отслеживания media_group_id
- [x] T-095: Модифицировать DeadPageRelay._try_forward_from_channel() — DB lookup + forward_messages()
- [x] T-096: Эвристический fallback — пробинг соседних message_id ±1..9
- [x] T-097: Дедупликация media_group в dead_page_trigger.py
- [x] T-098: Тесты (10 cases) — DB + heuristic + dedup + integration
- [x] T-099: QA — pytest (316 tests), обновление документации, v2.11.0

### Epic 13: Otboy Service (F9) — 2026-07-26
- [x] T-084: Архитектурное проектирование и ревью (sub-agent review)
- [x] T-085: Создать filters/otboy_word.py — OtboyWordFilter
- [x] T-086: Создать services/otboy_relay.py — OtboyRelay
- [x] T-087: Создать handlers/otboy.py — otboy_router
- [x] T-088: Конфигурация — OTBOY_COOLDOWN_SECONDS, OTBOY_PHOTO_PATH
- [x] T-089: Зарегистрировать otboy_router в bot.py (позиция 4c)
- [x] T-090: Тесты для Otboy Service (10 тестов — filter + handler + relay + integration)
- [x] T-091: Документация — README, ARCHITECTURE, MEMORY, v2.10.0
- [x] T-092: Деплой на сервер + smoke tests

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

**Updated:** 2026-07-28 — Epics 13 & 14 archived to Done. Epic 15 (Common Service) added to Backlog. v2.11.0 — 316 tests baseline, v2.12.0 target.

(End of file)
