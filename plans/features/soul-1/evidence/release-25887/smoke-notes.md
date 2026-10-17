# Prod smoke 2.58.87 (live origin) — 2026-10-17 23:0xZ

Инструменты и результаты:

1. Playwright MCP (Chromium), viewport 390x844:
   - `https://admin-bot.duckdns.org/web/#/` — title ok, shell mobile рендерится,
     auth-гейт («Миниапп открыт без Telegram-контекста…»), `.oversight-tabs`
     не рендерится без Telegram-контекста;
   - CSS живой: `<link href="/static/app.css?v=2.58.87">` → 200,
     `oversight-dd-open` ×2, `overflow: visible !important` — присутствует;
     прямой fetch `/web/static/app.css` — то же;
   - консоль: 1 ERROR (favicon.ico 404 — известный, не код приложения),
     5 warnings (vendored SDK stub вне Telegram);
   - скриншоты: `smoke-prod-390-playwright.png`,
     `smoke-prod-390-oversight-playwright.png` (deep-link `#/oversight` —
     тот же auth-гейт).
2. Browser Use (реальный Chrome, CDP Emulation 390x844... фактический vw=390):
   - тот же origin: `app.css?v=2.58.87` 200, marker ×2, overflow-правило есть,
     auth-гейт; скриншот `smoke-prod-390-browseruse.png`.

Вердикт: живой origin отдаёт **новые байты** (sha12 `d700df753d6d` — совпадает
с кандидатом и с локальным harness-прогоном shell-e2e). Живой тап-hit-тест по
dropdown на origin **невоспроизводим без Telegram initData** → owner-check
(визуальная приёмка тапа владельцем в реальном клиенте).
