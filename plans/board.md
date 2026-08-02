# AdminBot — Kanban Board

## 📋 Backlog

### Epic 19: Сервис Olya — автоответ на видео от @ole4444444ka — 2026-08-02 🔵 PLANNED

- [ ] T-131: Создать `filters/olya_video.py` — `OlyaVideoFilter` (UserId 834424825 + видео + детекция SaveAsBot)
- [ ] T-132: Создать `services/olya_relay.py` — `OlyaRelay` (plain send, медиа-автоопределение, cooldown)
- [ ] T-133: Создать `handlers/olya.py` — `olya_router` + `olya_handler` + `setup_olya()`
- [ ] T-134: Добавить конфигурацию Olya в `config/settings.py` (+8 полей) и `.env.example`
- [ ] T-135: Зарегистрировать `olya_router` в `bot.py` (позиция 4d, после common_router, до slavik_router)
- [ ] T-136: Написать тесты `tests/test_olya.py` (15-20 тестов: фильтр, сервис, хендлер, интеграционные, corner cases)
- [ ] T-137: Обновить README.md — добавить документацию Epic 19
- [ ] T-138: Деплой на сервер (git pull, systemctl restart, проверка статуса)

### Epic 18: Danger Service Fixes — File Selection, GIF Detection, Cooldown — 2026-08-02 🔵 IN PROGRESS

**T-122: Investigate and fix file scanning/selection in CommonRelay**
- [ ] T-122-A: Проверить `_scan_directory` — error handling (FileNotFoundError, PermissionError)
- [ ] T-122-B: Проверить `_pick_media` — random.choice на списке файлов
- [ ] T-122-C: Убедиться: нет хардкодных индексов, имён, счётчиков
- [ ] T-122-D: Фильтрация — только медиа-расширения (исключить .gitkeep, .DS_Store, Thumbs.db)
- [ ] T-122-E: `send_common()` — вызов `_pick_media` с правильным subdir
- [ ] T-122-F: `send_danger()` — subdir="danger" через `COMMON_MEDIA_BASE`
- [ ] T-122-G: Comprehensive логирование: количество файлов, выбранный файл
- [ ] T-122-H: Edge: пустая директория → WARNING, graceful return
- [ ] T-122-I: Edge: 1 файл → всегда выбирается
- [ ] T-122-J: Edge: 14+ файлов → все достижимы через random.choice

**T-123: Fix and verify GIF detection in filename**
- [ ] T-123-A: Проверить `_detect_media_type` — `"gif" in filepath.stem.lower()`
- [ ] T-123-B: `Path.stem` возвращает имя без расширения (danger_02_gif из danger_02_gif.mp4)
- [ ] T-123-C: Case-insensitive: gif, GIF, Gif, GiF → animation
- [ ] T-123-D: Все позиции "gif": danger_02_gif.mp4, danger_gif_02.mp4, danger_nahryuck_gif.mp4, danger_zelelyot_gif_02.mp4, gif_danger_01.mp4
- [ ] T-123-E: Без "gif" → video (не animation): danger_01.mp4, danger_03.mp4
- [ ] T-123-F: .gif-файлы → photo (image), не animation
- [ ] T-123-G: .webm с "gif" → animation, без "gif" → video
- [ ] T-123-H: `_send_media()` dispatch: animation → send_animation, video → send_video, photo → send_photo

**T-124: Add DANGER_COOLDOWN_SECONDS config with independent cooldown tracking**
- [ ] T-124-A: Поле `danger_cooldown: int = 60` в `CommonRelay.__init__`
- [ ] T-124-B: `_last_danger_by_chat: dict[int, float]` — независимый трекинг
- [ ] T-124-C: `send_otboy()` → COMMON_COOLDOWN_SECONDS + `_last_common_by_chat`
- [ ] T-124-D: `send_danger()` → DANGER_COOLDOWN_SECONDS + `_last_danger_by_chat`
- [ ] T-124-E: Per-chat изоляция для danger-cooldown
- [ ] T-124-F: Thread-safety: словари `_last_otboy_by_chat` и `_last_danger_by_chat` независимы
- [ ] T-124-G: DEBUG/INFO при cooldown active/expired для danger
- [ ] T-124-H: Edge: `DANGER_COOLDOWN_SECONDS=0` → без ограничений

**T-125: Update config/settings.py and .env.example**
- [ ] T-125-A: `DANGER_COOLDOWN_SECONDS: int = 60` в settings.py
- [ ] T-125-B: `DANGER_COOLDOWN_SECONDS=60` в .env.example
- [ ] T-125-C: `COMMON_COOLDOWN_SECONDS` без изменений (default=0)
- [ ] T-125-D: Параметр читается из os.getenv
- [ ] T-125-E: Документировать разницу в описании параметров

**T-126: Update bot.py for new CommonRelay initialization**
- [ ] T-126-A: `on_startup()` → `CommonRelay(..., danger_cooldown=settings.DANGER_COOLDOWN_SECONDS)`
- [ ] T-126-B: Импорты актуальны
- [ ] T-126-C: Сигнатура `CommonRelay.__init__`: `cooldown_seconds` + `danger_cooldown`
- [ ] T-126-D: `setup_common(relay)` передаёт relay в handler'ы
- [ ] T-126-E: Propagation не сломан (handler'ы возвращают None)

**T-127: Comprehensive tests for all fixes**
- [ ] T-127-A: `_scan_directory` — возвращает все медиа-файлы
- [ ] T-127-B: `_scan_directory` — исключает не-медиа
- [ ] T-127-C: `_scan_directory` — пустая директория → [], без исключений
- [ ] T-127-D: `_pick_media` — random.choice равномерно распределён (100 выборок из 14)
- [ ] T-127-E: `_pick_media` — 1 файл → всегда он
- [ ] T-127-F: `_detect_media_type` — все позиции "gif" (5+ паттернов, параметризованный)
- [ ] T-127-G: `_detect_media_type` — без "gif" → video
- [ ] T-127-H: `_detect_media_type` — case-insensitive: GIF, Gif, gif
- [ ] T-127-I: `_detect_media_type` — image-расширения → photo
- [ ] T-127-J: `_detect_media_type` — не-медиа → None/exception
- [ ] T-127-K: `send_danger()` — cooldown active → не отправляет
- [ ] T-127-L: `send_danger()` — cooldown expired → отправляет
- [ ] T-127-M: `send_danger()` — DANGER_COOLDOWN_SECONDS=0 → без ограничений
- [ ] T-127-N: `send_otboy()` — COMMON_COOLDOWN_SECONDS (независимо от danger)
- [ ] T-127-O: Интеграция: otboy cooldown не блокирует danger, danger cooldown не блокирует otboy
- [ ] T-127-P: Интеграция: per-chat изоляция для обоих cooldown
- [ ] T-127-Q: `send_common()` — полный пайплайн
- [ ] T-127-R: Regression: существующие test_common.py тесты проходят
- [ ] T-127-S: `pytest` — полный suite, 0 регрессий

**T-128: Update README.md with changes**
- [ ] T-128-A: Common Service — 3 исправления (file selection, GIF detection, cooldown)
- [ ] T-128-B: `DANGER_COOLDOWN_SECONDS` в таблице конфигурации
- [ ] T-128-C: GIF detection logic: любая позиция "gif" → animation
- [ ] T-128-D: Version bump v2.15.0 → v2.16.0
- [ ] T-128-E: Changelog v2.16.0

**T-129: Run full test suite, verify no regressions**
- [ ] T-129-A: `pytest -v` — все тесты
- [ ] T-129-B: Coverage `services/common_relay.py` ≥ 100%
- [ ] T-129-C: 14 файлов danger/ доступны (после деплоя)
- [ ] T-129-D: GIF detection для всех 14 реальных имён
- [ ] T-129-E: Better Stack: нет ERROR/WARNING от danger

**T-130: Deploy to server**
- [ ] T-130-A: Git commit (conventional commits) в main
- [ ] T-130-B: Git push
- [ ] T-130-C: SSH → сервер → git pull
- [ ] T-130-D: .env: DANGER_COOLDOWN_SECONDS=60
- [ ] T-130-E: Проверить `media/common/danger/` — 14 файлов, chmod 644
- [ ] T-130-F: Restart бота
- [ ] T-130-G: Smoke: danger-слово → случайный danger-файл, правильный тип
- [ ] T-130-H: Smoke: gif-файл → animation (не video)
- [ ] T-130-I: Smoke: danger через 30 сек → cooldown active
- [ ] T-130-J: Smoke: otboy → независим от danger-cooldown
- [ ] T-130-K: Smoke: danger через 60+ сек → отправляет снова
- [ ] T-130-L: Проверить другие фичи: слава, war_alert, алан, вася, костик, dead_page
- [ ] T-130-M: Better Stack логи verified

---

## 🔧 In Progress

### Epic 18: Danger Service Fixes — 2026-08-02 🔵

- [ ] T-122: Investigate and fix file scanning/selection in CommonRelay
- [ ] T-123: Fix and verify GIF detection in filename
- [ ] T-124: Add DANGER_COOLDOWN_SECONDS config with independent cooldown tracking
- [ ] T-125: Update config/settings.py and .env.example
- [ ] T-126: Update bot.py for new CommonRelay initialization
- [ ] T-127: Comprehensive tests for all fixes
- [ ] T-128: Update README.md with changes
- [ ] T-129: Run full test suite, verify no regressions
- [ ] T-130: Deploy to server

---

## ✅ Done

### Epic 17: Danger Word Fix — 2026-07-30
- [x] T-115: Проверить медиа-файлы danger/ на сервере
  - [x] T-115-A-E: SSH проверка, права, diff
- [x] T-116: Проверить и исправить DangerWordFilter
  - [x] T-116-A-G: 91+ слов, word-boundary, регистронезависимость, caption, логирование
- [x] T-117: Проверить war_alert_router ↔ common_router interaction
  - [x] T-117-A-F: порядок роутеров, F.forward_origin → TargetChannelFilter, propagation
- [x] T-118: Проверить и исправить CommonRelay.send_common
  - [x] T-118-A-G: _scan_directory, _pick_media, _detect_media_type, _send_media, error handling
- [x] T-119: Тесты для danger_word
  - [x] T-119-A-I: 91+ слов, регистр, word boundary, caption/forward, cooldown, integration, pytest
- [x] T-120: README — changelog, v2.12.2 → v2.15.0
- [x] T-121: Деплой на сервер
  - [x] T-121-A-H: git pull, .env, restart, smoke tests, Better Stack

### Epic 16: Bug Fixes Sprint — 2026-07-29 ✅ ARCHIVED (→ Epic 17)
- [x] Epic 16 archived 2026-07-30. Danger_word fix → Epic 17. DeadPageRelay album fix → deferred.
- [x] T-109: DangerWordFilter — RCA completed (22 слова → нужно 91+)
- [x] T-114: war_channel_repost_handler — RCA completed (F.forward_origin блокирует)
- [x] T-113: DEAD_PAGE_RELAY_CHANNEL_ID — RCA completed
- [ ] T-110: DeadPageRelay album fix — DEFERRED
- [ ] T-111: Тесты — DEFERRED
- [ ] T-112: Документация — DEFERRED

### Epic 15: Common Service — Rename + Media Upgrade + Danger — 2026-07-28
- [x] 👤 T-100 (@Architect): Архитектурное проектирование Common Service + sub-agent review
  - [x] T-100-A: Спроектировать архитектуру — модули, data flow, directory structure, контракты
  - [x] T-100-B: Sub-agent ревью — изоляция, масштабируемость, корректность rename, media type detection
  - [x] T-100-C: Согласовать финальный дизайн с PM
- [x] T-101: Переименование файлов и модулей (otboy → common)
  - [x] T-101-A: handlers/otboy.py → handlers/common.py
  - [x] T-101-B: services/otboy_relay.py → services/common_relay.py
  - [x] T-101-C: filters/otboy_word.py оставлен; СОЗДАН filters/danger_word.py (DangerWordFilter)
  - [x] T-101-D: Обновлены все импорты в bot.py
  - [x] T-101-E: Grep-проверка — нет dead imports
- [x] T-102: Конфигурация — переименованы и добавлены env-переменные
  - [x] T-102-A: OTBOY_COOLDOWN_SECONDS → COMMON_COOLDOWN_SECONDS
  - [x] T-102-B: OTBOY_PHOTO_PATH удалён, добавлен COMMON_MEDIA_BASE
  - [x] T-102-C: Созданы директории media/common/otboy/ и media/common/danger/
  - [x] T-102-D: Обновлён .env.example
- [x] T-103: Upgrade media-обработки — directory-based picker с авто-детекцией типа
  - [x] T-103-A: CommonRelay._pick_media(media_dir)
  - [x] T-103-B: _detect_media_type(filename) → photo/video/animation
  - [x] T-103-C: _send_media(chat_id, filepath, media_type, reply_params)
  - [x] T-103-D: send_otboy() использует _pick_media + _send_media
  - [x] T-103-E: Логирование media type
- [x] T-104: Новая функция детекции опасных слов (danger)
  - [x] T-104-A: DangerWordFilter — DANGER_WORDS + pattern compilation
  - [x] T-104-B: CommonRelay.send_danger() — _pick_media + _send_media + reply_to + quote
  - [x] T-104-C: danger_handler в common.py
  - [x] T-104-D: Reply-to + quote mechanism (ReplyParameters)
  - [x] T-104-E: Comprehensive logging для danger
- [x] T-105: Интеграция в bot.py
  - [x] T-105-A: Импорты: common_router, setup_common, CommonRelay
  - [x] T-105-B: dp.include_router(common_router) — позиция 4c
  - [x] T-105-C: on_startup(): CommonRelay, setup_common(relay)
  - [x] T-105-D: Propagation проверен (оба handler'а возвращают None)
- [x] T-106: Тесты (~20+ тестов)
  - [x] T-106-A: test_otboy.py → test_common.py
  - [x] T-106-B: 11 тестов OtboyWordFilter перенесены
  - [x] T-106-C: 6 тестов otboy_handler перенесены (OtboyRelay → CommonRelay)
  - [x] T-106-D–G: Media type detection, _pick_media edge cases
  - [x] T-106-H–I: DangerWordFilter тесты (срабатывает/не срабатывает/регистр/word boundary)
  - [x] T-106-J–K: danger_handler + CommonRelay.send_danger тесты
  - [x] T-106-L: Cooldown тесты (общий для otboy+danger, per-chat)
  - [x] T-106-M–N: Интеграция — propagation + диспетчеризация
- [x] T-107: Документация — README, ARCHITECTURE, MEMORY обновлены, v2.12.0
- [x] T-108: QA — тесты, коммит, деплой
  - [x] T-108-A: pytest — 316+ тестов, 0 регрессий
  - [x] T-108-B: Коммит на русском (conventional commits) в main, пуш
  - [x] T-108-C: Деплой на сервер — git pull, .env, restart
  - [x] T-108-D: Smoke test: «отбой» → медиа из common/otboy
  - [x] T-108-E: Smoke test: «ракетная опасность» → медиа из common/danger
  - [x] T-108-F: Smoke test: другие фичи не сломаны
  - [x] T-108-G: Better Stack логи verified

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

**Updated:** 2026-08-02 — Epic 17 archived (DONE). Epic 18 (Danger Service Fixes) created. v2.16.0 target.
