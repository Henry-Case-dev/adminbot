# F10 — §71 единый Playwright-прогон (T-3104/T-3105/T-3106)

> **Тип:** живой локальный прогон Chromium. **Правило:** Chromium ≠ Telegram WebView;
> локальный прогон НЕ заменяет live-приёмку владельца (§71/10.20-UPD3/10.21).
> **Инварианты:** Δ DDL=0, Δ каталога=0, CSP/zero-build, R17/R18 — соблюдены
> (изменён только `tools/**`, рантайм не тронут).

## Инструмент и запуск

- Харнесс: `tools/ui_round1025_matrix.py` (расширен аддитивно, ADR-1025-24 D5).
- Новое: вьюпорт **низкого окна Telegram Desktop** `1280×400` + короткий
  `viewportStableHeight = innerHeight − 120 = 280` (`LOW_TG_WINDOW`); базовые
  10 размеров × 5 режимов не изменены.
- Команда: `.venv/Scripts/python.exe tools/ui_round1025_matrix.py`
- Артефакты: `tools/_ui_round1025_raw.json` (gitignored) + `tools/_ui_round1025_shots/`.

## Результат (числа)

**Итог: `failures: 0`** (10 вьюпортов × 19 маршрутов + низкое окно).

| Вьюпорт | маршрутов | overflow | root `scrollWidth` | `innerWidth` |
|---|---|---|---|---|
| 320×700 | 19 | 0 | 320 | 320 |
| 360×780 | 19 | 0 | 360 | 360 |
| 390×844 | 19 | 0 | 390 | 390 |
| 430×932 | 19 | 0 | 430 | 430 |
| 768×1024 | 19 | 0 | 768 | 768 |
| 1024×768 | 19 | 0 | 1024 | 1024 |
| 1280×800 | 19 | 0 | 1280 | 1280 |
| 1440×900 | 19 | 0 | 1440 | 1440 |
| 1920×1080 | 19 | 0 | 1920 | 1920 |
| 2560×1440 | 19 | 0 | 2560 | 2560 |
| **1280×400 (низкое окно TG Desktop)** | 19 | 0 | 1280 | 1280 |

- Низкое окно: `stableHeight=280`, `innerHeight=400`, sidebar=216px, overflow-маршрутов
  нет; `_low_tg_failures` (h-scroll, sidebar/header в границах, нижние панели в
  `stableHeight`, touch ≥44) — 0 срабатываний.
- §71-инвариант `documentElement.scrollWidth <= innerWidth + 1` — выполняется на всех
  маршрутах/вьюпортах (в т.ч. низком окне).
- Реальные `boundingClientRect`: sidebar (≥1200), drawer (768–1199), bottom-nav (<768)
  взаимоисключающе; нижняя панель/шторка в `stableHeight`; touch-таргеты ≥44px —
  покрыто существующими пробами матрицы (`_vertical_failures`, `_h9_failures`,
  `_scope_failures`, `_low_tg_failures`) — 0 нарушений.
- Маршруты (19): `#/`, `#/oversight`, `#/how`, `#/modules`, `#/ai`, `#/ai/llm`,
  `#/ai/prompts`, `#/ai/smart-cache`, `#/ai/names`, `#/memory`, `#/memory/rag`,
  `#/memory/lore`, `#/access`, `#/permsoc`, `#/status/graph` + workspace
  `#/modules/factcheck`, `#/modules/factcheck/models`, `#/modules/direct/models`,
  `#/modules/summary`.

## Скриншоты (T-3106, свежие)

`plans/reports/round1025_f10_shots/`: `1280x800_root.png`, `390x844_root.png`,
`1280x800_fullscreen.png`, `390x844_fullscreen.png`, `1280x400_low_tg_root.png`,
`320x700_root.png`, `768x1024_root.png`, `1280x800_memory.png`.
Полный набор (root/memory/ws_models/fullscreen по всем вьюпортам) —
`tools/_ui_round1025_shots/` (gitignored).

## НЕ принято / ограничения

- Локальный Chromium **не** доказывает поведение в Telegram WebView → live-гейт
  владельца = **PENDING** (не закрывается здесь).
- Наблюдаемый побочный шум: локальный http-сервер логирует 404 для запросов
  `/api/memory/*` из не-перехваченного окна (фоновые повторные запросы); на
  `failures` не влияет (`failures: 0`), как и в baseline F1.
