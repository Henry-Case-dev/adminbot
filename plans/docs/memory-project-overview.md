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
