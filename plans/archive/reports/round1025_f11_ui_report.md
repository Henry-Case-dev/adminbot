# F11 `status-showcase-dashboard-round1025` — UI-отчёт (§70/§71)

> **Агент:** @Builder (T-3087). **Дата:** 23.09.2026. **Инструмент:** `tools/ui_round1025_matrix.py`.

## Итог

**`failures: 0`** на 10 вьюпортах §70 (+ fullscreen-режим) для всех маршрутов, включая новый аддитивный `#/status/graph`.

- Артефакты: `tools/_ui_round1025_raw.json` (реальные `boundingClientRect`), скриншоты `tools/_ui_round1025_shots/*.png`.
- Итоговая строка прогона: `[matrix] failures: 0`.
- Анти-регресс: baseline-worktree HEAD `25cc19c` — `[matrix] failures: 0`.

## Матрица вьюпортов

| Вьюпорт | shell | F11 §12 | overflow |
|---|---|---|---|
| 320×700 | mobile (bottom-nav 4) | 1 колонка, порядок §12 | нет |
| 360×780 | mobile | 1 колонка | нет |
| 390×844 | mobile | 1 колонка | нет |
| 430×932 | mobile | 1 колонка | нет |
| 768×1024 | compact (drawer) | 6 колонок (все `span 6`) | нет |
| 1024×768 | compact | 6 колонок | нет |
| 1280×800 | desktop (sidebar) | 12 колонок: 5/7, 8/4, 12, 7/5, 12, 12 | нет |
| 1440×900 | desktop | 12 колонок | нет |
| 1920×1080 | desktop | 12 колонок | нет |
| 2560×1440 | desktop | 12 колонок | нет |

## F11-пробы (реальные rect'ы)

- `.status-grid` виден; при ≥992 спаны Hero/метрики/граф/сон соответствуют 5/7/8/4 (допуск 6 %).
- Строки §12 (совпадение `top`): Hero↔метрики, граф↔сон, превью↔факты — только desktop.
- Бюджеты видны; `.status-grid--legacy` отсутствует при `UI_STATUS_GRID_V2=ON`.
- `#/status/graph`: `visible=true`, контейнер `.cognition-graph`, кнопка «Закрыть», без overflow.

## Правки инструмента (не меняют проверок) — обоснование анти-регрессом

1. **`_reset_scroll(page)`** перед shell8/H9/H10-пробами: навигация внутри одной вкладки (`#/status/graph` → `#/`) НЕ сбрасывает скролл (by design F1 — сброс только при смене вкладки), поэтому пробы получали прокрученный layout.
2. **Сохранение/восстановление скролла** в `PROBE_JS`/`F7_PROBE_JS`/H9/H10 после `scrollIntoView`: F11 добавил прокручиваемую сетку на Статусе, из-за чего `heartbeat.scrollIntoView` в F7-пробе прокручивал страницу и ломал последующие `headerCardGap`/`headerOverlapsCard`/`hbVisible`.
3. **H10-изоляция**: hit-тест цели центрирует её перед `elementFromPoint` (`.status-block` теперь ниже фолда на узком экране) и возвращает скролл — rect по-прежнему топ-якорный.
4. В `ME_JSON` добавлен `UI_STATUS_GRID_V2: True` (целевая композиция), в `ROUTES` — `#/status/graph`.

Все правки проверены на baseline `25cc19c` (0 failures) — то есть инструмент не «подыгрывает» F11.

## Ограничение

Успешный локальный Chromium-прогон **не заменяет** живую приёмку Telegram WebView/TMA (T-3097, гейт владельца): HTTP 200 / Playwright ≠ корректный UI в клиенте.
