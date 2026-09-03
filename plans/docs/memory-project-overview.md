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

- F-3: ротация токена бота (BotFather /revoke), revoke GitHub PAT, приватизация репозитория, ротация ключей (T-665); username скам-сообщения → вердикт утечка/фейк (T-666).
- F-2: контрольное открытие мини-аппа из Telegram ([tma-auth] valid=True role=admin).
- F-4: живая проверка всех вкладок админки (десктоп/Android/Nekogram).
- F-6: подтверждение эффекта алиасов в живом чате.
- Ссылки на фичи: `features/scam-incident-security-followup/`, `features/admin-debug-webview/`, `features/frontend-admin-bugfixes/`, `features/user-aliases-admin/`.
