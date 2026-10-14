# Задачи: admin-debug-webview

## /debug_config (T-656…T-658)

- [x] T-656 — /debug_config (DM + GET /api/debug/config) — DONE & DEPLOYED (коммит `63a9e10`, `a46dada`; MEMORY.md).
- [x] T-657 — ngrok systemd — DONE (MEMORY.md); **суперсед** T-659 (ngrok disabled+inactive, MEMORY.md).
- [x] T-658 — /debug_config v2 (key=value, env-имена) — DONE (коммит `a46dada`, ARCH 84.20).

## Внешний HTTPS (T-659…T-661)

- [x] T-659 — DuckDNS + Caddy + Let's Encrypt (admin-bot.duckdns.org, Caddy 2.11.4, LE 30.08→28.11.2026) — DONE (MEMORY.md, коммит `38f1c7a`).
- [x] T-660 — инцидент «2 вкладки + спиннеры» — root cause подтверждён (ngrok interstitial), устранён переходом на DuckDNS (MEMORY.md, ARCH 84.21–84.22).
- [x] T-661 — версионирование статики `?v=` + Cache-Control — DONE (коммит `a46dada`, ARCH 84.21.2).

## Человеческая верификация

- [ ] ⏸ ждёт человека: контрольное открытие мини-аппа из Telegram (кнопка меню BotFather на https://admin-bot.duckdns.org/web/) + проверка [tma-auth] valid=True role=admin.

## Регресс

- [ ] регресс: полный pytest.
