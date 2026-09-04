# Memory: Project Overview (актуальные факты)

Консолидация «живых» фактов из MEMORY.md (прежний `plans/MEMORY.md`, удалён 03.09.2026; журналы эпиков — в git-истории как история).

## Стек (актуально)

- Python 3.12+, asyncio; aiogram 3.x; LLM deepseek-v4-flash (apinet.cloud, фолбэк DeepSeek); эмбеддинги gemini-embedding-001 (dim 3072); Groq whisper-large-v3 → OpenRouter.
- Память бота: SQLite + sqlite-vec + FTS5 (L1/L2/L3 + GraphRAG v2); PG-миграция = Epic 86 (backlog.md).
- Админка: FastAPI + PostgreSQL 16 (asyncpg, 127.0.0.1:8000), ConfigCache/hot.get, param_catalog 265 записей, RBAC v2, фронт Vue3+Tailwind CDN.
- Тесты: pytest + pytest-asyncio; 3280 passed на 31.08 (прод-база растёт: v2.51.0 → 3111+ по README). Правило: полный прогон перед коммитом.

## Прод-инфраструктура

- Сервер 198.46.175.136, `/var/www/admin_bot`, пользователь nik, systemd `admin_bot` (git pull --ff-only, TimeoutStopSec=30).
- Docker (все 127.0.0.1): postgres:16, cobalt, telegram-bot-api (локальный Bot API).
- Внешний HTTPS: DuckDNS + Caddy 2.11.4 + Let's Encrypt (admin-bot.duckdns.org; сертификат 30.08→28.11.2026). ngrok отключён.
- Мониторинг: Sentry, Better Stack Logtail, journald (SystemMaxUse=200M).

## Админ-иды и роли

- `5885953495` → admin (владелец; ADMIN_USER_ID по умолчанию; seed `services/pg_db.py`).
- Дополнительные роли в `bot_roles`/`bot_admins` (admin/moderator; пример тестов: 1313107079 → moderator).
- Бот: @PERMsoc_bot (id 8802473181), супергруппа -1002661910336; смена токена бота завершена 01.09 (значения не хранятся).

## Версия прода

- v2.51.0+ (Epic 85 «TMA Admin Dashboard & Dynamic RBAC» — DONE & DEPLOYED 30.08; релизная линия: v2.43.0 Epic 60 … v2.49.0 Epic 79, последующие хотфиксы 01–03.09 в master).
- История релизов/эпиков — `MEMORY.md` в git-истории (до 03.09.2026).

## Открыто на человеке

- F-3: username скам-сообщения → вердикт утечка/фейк (T-666).
- F-2: контрольное открытие мини-аппа из Telegram ([tma-auth] valid=True role=admin).
- F-4: живая проверка всех вкладок админки (десктоп/Android/Nekogram).
- F-6: подтверждение эффекта алиасов в живом чате.
- Ссылки на фичи: `features/scam-incident-security-followup/`, `features/admin-debug-webview/`, `features/frontend-admin-bugfixes/`, `features/user-aliases-admin/`.

## Активный эпик (2026-09-04): мультимодальная саммаризация + Tool Calling + фиксы реакций + UX/UI админки

- Воркфлоу OpenSpec (шаги 0–9). **Шаги 0–1 выполнены (04.09)**: Memory sync + планирование @PM — `plans/features/multimodal-summarization-tools-reactions-ui/tasks.md` (T1–T34), запись добавлена в `plans/backlog.md`; следующий шаг: @Architect → `spec.md`.
- **Статус после Шага 3 (Memory sync, 04.09): Шаги 0–2 выполнены, дизайн готов** — `plans/features/multimodal-summarization-tools-reactions-ui/spec.md` (~672 стр., FR-1..FR-29, NFR-1..NFR-6, AC-1.x..AC-5.x) создан @Architect; KG обновлён (файловые сущности + relations); **далее: @Builder → реализация T1–T34**.
- Часть 1 — каскадная мультимодальная выжимка видео: OpenRouter `video_url`, primary `minimax/minimax-m3:free`, fallback `google/gemma-4-31b-it:free`, затем фолбэк на субтитры.
- Часть 2 — Tool Calling в подсервисе `smartmodule`: tools `execute_web_search`, `query_chat_memory`.
- Часть 3 — фиксы реакций: тумблеры `reactions.vasya_enabled` / `reactions.kucha_enabled` (default `false`), `flags.mimic_enabled=false`, `reactions.alan_mimic_enabled=false`, `reactions.slavik_user_id`; переименование Alan → Леха.
- Часть 4 — UX/UI рефакторинг Vue админки: группировка разделов, Key-Value редактор для `limits.summary_aliases`, нейминг Леха.
- KG: сущность `epic: multimodal-summarization-tools-reactions-ui` + агенты (PM/Architect/Builder/Reviewer/DevOps/Memory), relations `assigned to`; observation на AdminBot.
- **ВЫПОЛНЕНО (04.09.2026)**: все шаги 0–9 завершены — коммиты e3e7fd5..ae9b4f8 (7 шт., пуш 780e8d7..e3e7fd5), pytest 3447 passed / 0 failed, деплой active (e3e7fd5, health HTTP 200), архив в `plans/archive/multimodal-summarization-tools-reactions-ui/` ({spec.md,tasks.md}), ARCHITECTURE.md §13, backlog.md «Выполнен и заархивирован», README обновлён (Леха, новые параметры); APP_VERSION не менялась — 2.51.0.

## Активный bugfix-раунд (04.09.2026): видео-транскрипты + Tool Calling

- Воркфлоу OpenSpec (шаги 0–9). **Статус: Step 0 — контекст-синк @Memory + диагностика (04.09.2026)**; KG: сущность `bugfix: video-transcript-and-tool-calling` (bugfix-epic) + relations `assigned to` (PM/Architect/Builder/Reviewer/DevOps/Memory) и `concerns` (AdminBot).
- Контекст: предыдущий эпик `multimodal-summarization-tools-reactions-ui` завершён и задеплоен (ae9b4f8..e3e7fd5, 3447 passed, бот active); рабочие директории и прод — без изменений (сервер 198.46.175.136, `/var/www/admin_bot`, systemd `admin_bot`).
- **Проблема 1 (видео)**: команды «транскрипт»/«че за видос» не реагируют на обычное Telegram-видео (тестировано на видео из репоста); перепроверить, что видео по прямым ссылкам/нативные видео скачиваются штатно (не в обход yt-dlp/cobalt).
- **Проблема 2 (tool calling)**: запрос «бот, сколько раз в чате упоминался бензин» НЕ вызывает инструмент `query_chat_memory` (несколько вызовов, ошибок в логах нет) — проверить, прописаны ли инструменты в промптах; то же для поиска `execute_web_search`.
- **Проблема 3 (DevOps)**: закоммитить всё незакоммиченное, запушить и задеплоить на сервер 198.46.175.136.
- Следующий шаг: @Orchestrator → распределение по ролям; @PM планирование (Step 1), затем диагностика проблем 1–2.
- **Step 3 Memory sync (04.09.2026): Steps 1–2 выполнены** — `plans/features/tg-video-tool-calling-fixes/tasks.md` (T-667..T-685, создан @PM, запись в `plans/backlog.md`) + `plans/features/tg-video-tool-calling-fixes/spec.md` (@Architect, дизайн частей 1/1b/2 готов, AC-1.x..AC-3.x) — **далее @Builder** (реализация T-668..T-682, затем @Reviewer). KG обновлён: файловые сущности `tasks.md`/`spec.md` + relations (`PM created`, `Architect created`, `includes`, `designed_by`, `implements`).
- **ВЫПОЛНЕНО (04.09.2026)**: все шаги 0–9 закрыты — коммиты 5b518e5..e000297 (5 шт., пуш e3e7fd5..e000297), pytest 3526 passed / 0 failed, деплой active (e000297, Main PID 3232067 на 198.46.175.136), миграция промпта сработала ([prompt_migration] легаси-канон заменён новым), health HTTP 200; root cause tools-бага (aiosqlite.Row.get AttributeError) исправлен dict-нормализацией; архив в `plans/archive/tg-video-tool-calling-fixes/` ({spec.md,tasks.md}), ARCHITECTURE.md §14, backlog «Выполнен и заархивирован»; раунд закрыт, APP_VERSION не менялась — 2.51.0.

## Активный раунд 3 (04.09.2026): betterstack, видео-мультимодалка, «сцуко»

- Воркфлоу OpenSpec (шаги 0–9). **Статус: Step 0 — контекст-синк @Memory + диагностика (сервер 198.46.175.136 + код) (04.09.2026)**; KG: сущность `bugfix: betterstack-video-multimodal-sucko` (bugfix-epic) + relations `assigned to` (PM/Architect/Builder/Reviewer/DevOps/Memory) и `concerns` (AdminBot).
- Контекст: раунды 1–2 закрыты и задеплоены (мультимодалка `multimodal-summarization-tools-reactions-ui` e3e7fd5, видео-багфикс `video-transcript-and-tool-calling` e000297, pytest 3526 passed); прод: 198.46.175.136, `/var/www/admin_bot`, systemd `admin_bot`, health HTTP 200.
- **Проблема 1 (Betterstack)**: логи пропали с момента наката эпиков (мультимодалка + видео-багфикс) — проверить на сервере 198.46.175.136, снять реальные логи, разобрать ошибки.
- **Проблема 2 (нативные видео TG)**: тест 1 — бот ответил, но «не видит картинку, только звук»; тест 2 — обе модели (minimax+gemma) упали и субтитров не было; разобрать по логам.
- **Проблема 3 (уточнение логики выжимки)**: YouTube/yt-dlp + нативные + прямые ссылки → мультимодальные minimax+gemma, при неудаче — выжимка субтитров; «че за видос/о чем видео/поясни за видос» — выжимка для ВСЕХ типов видео (reply-режим, «триггер ссылка», caption-режим); «транскрипт» — как транскрибация кружков («Имя: текст курсивом») для всех типов видео в тех же 3 режимах.
- **Проблема 4 (инцидент «сцуко»)**: бот в каждом сообщении добавляет «сцуко» в начало — расследовать (промпты/контекст/память/что менялось в эпиках).
- Следующий шаг: @Orchestrator → распределение по ролям; диагностика проблем 1–2 и 4 на проде + код.
- **Step 3 Memory sync (04.09.2026): Steps 1–2 выполнены** — `plans/features/video-multimodal-pipeline-and-incidents/tasks.md` (T-686..T-704, 19 задач, секции A–E; создан @PM, запись в `plans/backlog.md`) + `plans/features/video-multimodal-pipeline-and-incidents/spec.md` (@Architect: media_share HMAC+TTL 900с /media/, роутер kind×mode в youtube.py, summarize_media_url L1/L2 без RAG, «транскрипт»-формат кружков для всех типов, честная выжимка ≥100 симв, STT-таймауты 120с + гейты 25/20МБ, CHECK-миграция user_version 4, анти-залипание style_anchors + TTL 30 дней, BetterStack startup-маркер [logtail] + logging.shutdown()) — **далее @Builder** (реализация T-686..T-704, затем @Reviewer). KG обновлён: файловые сущности tasks.md/spec.md + relations (`PM created`, `Architect created`, `includes`, `designed_by`, `implements`).
- **ВЫПОЛНЕНО (04.09.2026)**: коммиты c9cdc66..3088816, 3618 passed, деплой active, Caddy /media/, миграции v4/TTL, чистка сцуко 5→0, betterstack live-тест отправлен; архив plans/archive/video-multimodal-pipeline-and-incidents/

## Активный раунд 4 (04.09.2026): betterstack-uvicorn, видео-research, память (импорт/миграция/команды), промпт-баг TMA

- Воркфлоу OpenSpec (шаги 0–9). **Статус: Step 0 — контекст-синк @Memory (04.09.2026)**; KG: сущность `bugfix: betterstack-video-research-memory-commands` (bugfix-epic) + relations `assigned to` (PM/Architect/Builder/Reviewer/DevOps/Memory) и `concerns` (AdminBot).
- Контекст: раунды 1–3 закрыты и задеплоены (видео-багфикс `video-transcript-and-tool-calling` e000297; betterstack-мультимодалка `betterstack-video-multimodal-sucko` 3088816, pytest 3618 passed); прод: 198.46.175.136, `/var/www/admin_bot`, systemd `admin_bot`, health HTTP 200.
- **Проблема 1 (Betterstack)**: live-маркер в панели так и не появился; расследование юзера: uvicorn при старте переопределяет корневой логгер и сносит LogtailHandler → решение: `log_config=None` при старте uvicorn + заглушить «Update is not handled» (aiogram.event) до уровня WARNING.
- **Проблема 2 (нативное видео)**: «че за видос» → ответ «разборчивой речи нет» — похоже, minimax/gemma не получают видео; research: реальная поддержка видео у `minimax/minimax-m3:free` и `google/gemma-4-31b-it:free` в OpenRouter + лимиты (размер/длительность/формат).
- **Проблема 3 (исследование импорта)**: папка `migrate_history` — история чата 2661910336 за годы; как импортировать в память/GraphRAG (способы, стоимость, время); метаданные сообщений должны сохраняться; проверить, что метаданные сейчас идут с сообщениями в долгосрочную память. Итог — отчёт.
- **Проблема 4 (отчёт)**: миграция памяти sqlite→PG — риски простыми словами.
- **Проблема 5 (фича)**: команды «бот, запомни …» / «бот, забудь …» — доступ админ+модер; обычным юзерам — пул едких фраз; тумблер в миниаппе для юзеров.
- **Проблема 6 (баг TMA)**: при изменении любого промпта в миниаппе → ошибка «Некорректное значение для prompts.factcheck_system_prompt».
- **Проблема 7 (правило)**: авто-коммит memory-sync без запроса юзера + проверка на секреты перед коммитом.
- Следующий шаг: @Orchestrator → распределение по ролям; @PM планирование (Step 1), @Researcher — исследовательские задачи (проблемы 2–3), диагностика проблем 1/6/7, реализация проблемы 5.
- **Step 3 Memory sync (04.09.2026): Steps 1–2 выполнены** — `plans/features/betterstack-own-handler-video-memory-cmds/tasks.md` (T-705..T-726, 22 задачи, секции A–G; создан @PM, запись в `plans/backlog.md`) + `plans/features/betterstack-own-handler-video-memory-cmds/spec.md` (@Architect: собственный `services/betterstack_handler.py` вместо logtail-python, маркерный детект отказных ответов видео + дефолты nemotron-omni/minimax-m3:free, память-команды «запомни/забудь» с RBAC/тумблером, фикс промпт-бага TMA, даты [%Y-%m-%d] в RAG-фактах, `.gitignore` += `migrate_history/`, авто-коммит memory-sync) — **далее @Builder** (реализация, затем @Reviewer). KG обновлён: файловые сущности tasks.md/spec.md + relations (`PM created`, `Architect created`, `includes`, `designed_by`, `implements`).
