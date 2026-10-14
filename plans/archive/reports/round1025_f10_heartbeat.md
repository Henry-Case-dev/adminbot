# F10 — §77 свод heartbeat (T-3112)

> **Тип:** свод. Переиспользует `plans/reports/round1025_f11_verification.md`
> (T-3088, таблица §77) + живой прогон состояния из матрицы §71. Дублей нет.

## Источник (F11, ADR-1025-23)

`plans/reports/round1025_f11_verification.md` → T-3088 (§77):

| Требование §77 | Реализация | Проверка |
|---|---|---|
| HEALTHY / WARNING / CRITICAL / UNKNOWN | `hbState` + `heartbeat` computed | JS-тест `F11-HEARTBEAT-OK`; матрица: класс `hb-<state>` проставлен (`_hotfix7_failures`) |
| Изменение цвета/частоты/амплитуды | `_hbDrawPremium` (Canvas 2D) | F11 JS-тест |
| Потеря телеметрии | `loadStatus` catch → `_applyHeartbeatSample({missing:true})` → UNKNOWN | F11 JS-тест |
| Восстановление | успешный `loadStatus` → возврат из UNKNOWN | F11 JS-тест |
| Reduced motion | `reducedMotion` + CSS `@media (prefers-reduced-motion)` | матрица (F2 reduced-motion-контекст, animation-name=none) |
| Отсутствие избыточных запросов | polling `startStatusPolling` (30 с), rAF не опрашивает сеть | F11 JS-тест |

## Живой прогон F10 (подтверждение)

- Матрица §71: `.hb-canvas` существует, `hbVisible=true`, состояние `hb-<state>`
  проставлено, overflow контейнера отсутствует — на всех 10 вьюпортах и низком
  окне TG Desktop (`failures: 0`).
- Пробы `H10_PROBE_JS` (`hbHit`/`botHit`/`serverHit`) — сердцебиение
  hit-testable по центру, не обрезано (`_h10_status_card_failures` — 0 срабатываний).

## Итог

§77 подтверждён сводом F11 + живым прогоном. **НЕ принято:** новых дефектов нет.
Ограничение: Chromium ≠ Telegram WebView → live-гейт владельца **PENDING**.
