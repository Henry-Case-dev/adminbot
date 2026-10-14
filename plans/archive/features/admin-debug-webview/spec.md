# /debug_config и внешний HTTPS (F-2)

## Контекст и цель

Follow-up Epic 85 (T-656…T-661) + инциденты 30.08 (MEMORY.md: «2 вкладки + спиннеры», ngrok interstitial). Цель: прозрачная проверка цепочки «Mini App → БД → кэш → RAM» (дамп конфигурации только из RAM) и стабильный внешний HTTPS без ngrok. Основной код закрыт и задеплоен; остаётся человеческая верификация.

## Архитектурные привязки

- **84.18** — /debug_config: дамп ТОЛЬКО из RAM (meta: pid/keys_total/cache_loaded_at/app_version; маскировка значений; html.escape; чанкинг ≤4096).
- **84.20** — формат v2 `key = value`, env-имена case-insensitive, маркер изменённого параметра.
- **84.21** — root cause «2 вкладки + спиннеры» (кэш WebView/статики) + версионирование статики `?v=`.
- **84.22** — DuckDNS + Caddy + Let's Encrypt (замена ngrok interstitial; ngrok disabled+inactive).

## Границы

Инфраструктура DuckDNS уже сделана @DevOps. Вне скоупа — ротация секретов и прочий хардненинг (см. F-3). Не менять формат вывода без согласования.

## Связи с другими фичами

- F-1 (`features/post-deploy-admin-minors/`) — T-648…T-654 верифицируются через /debug_config.
- F-4 (`features/frontend-admin-bugfixes/`) — фронт, статика `?v=`.
- F-5 (`features/config-read-path-audit/`) — сквозная проверка «изменение параметра → /debug_config <ENV_NAME>».

## Критерии готовности

- Открытие мини-аппа из Telegram (кнопка меню BotFather) показывает [tma-auth] valid=True role=admin.
- /debug_config (DM и GET /api/debug/config) отдаёт актуальные значения из RAM.
- Внешний https://admin-bot.duckdns.org/web/ стабилен (нет 404/interstitial ngrok).
- Человеческий вердикт по контрольному открытию зафиксирован (пункт ⏸ «ждёт человека» — контрольное открытие мини-аппа, tasks.md).
- Полный pytest — 0 failed.
