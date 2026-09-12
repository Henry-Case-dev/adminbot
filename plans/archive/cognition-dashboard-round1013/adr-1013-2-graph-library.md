# ADR-1013-2 — Библиотека интерактивного графа (F5): vis-network vs d3.js

> Статус: **ACCEPTED**. Дата: 13.09.2026. Автор: @Architect (Step 2).
> Касается: F5 (T-1452). База: HEAD `ce25dc7`. Контекст: TMA / Android WebView,
> zero-build Vue3-global, CSP, offline.

## 1. Контекст

ТЗ §5 требует интерактивный force-directed граф (люди, события, убеждения,
связи), работающий в Telegram Mini App, в том числе на Android WebView.
Ограничения проекта (сверено):
- **zero-build**: единый `web/index.html` + `web/app.js`, Vue3-global;
- **CSP**: self-host DOMPurify (`script-src 'self'`); Chart.js сейчас с CDN
  (`cdn.jsdelivr.net`) — но тренд раундов 10.5 (OD14 шрифт self-host, OD18) —
  минимизировать внешние зависимости;
- **offline/Android**: сеть может быть недоступна, WebView слабее десктопа;
- уже используется `Chart.js` (не трогать), `web/static/vendor/` существует.

## 2. Решение

**Принять `vis-network` (standalone UMD) + `vis-data`, self-hosted** в
`web/static/vendor/vis-network/` (`vis-network.min.js`). Standalone-бандл
`vis-network.min.js` (v9.1.9) содержит `vis-data` внутри (отдельный
`vis-data.min.js` не коммитим), `window.vis` доступен после загрузки.
Подключение через `<script src="...">` с same-origin и cache-bust `?v=__APP_VERSION__`.
Загружать **лениво** — только при открытии вкладки «Статус» (динамическая
вставка `<script>` с проверкой `window.vis`), чтобы не утяжелять первичную загрузку TMA.
Рендер — Canvas (`vis-network` default), `physics` включается при N ≤ ~300 узлов
и выключается (`stabilization.iterations`) для больших графов.

## 3. Обоснование

| Критерий | vis-network | d3.js (d3-force + custom) |
|---|---|---|
| Force-directed «из коробки» | да | нет (собирать самому) |
| Drag/zoom/pan | да (built-in) | нет (собирать самому) |
| Рендер на Android WebView | Canvas (быстро, сотни узлов) | SVG (медленно) / Canvas вручную |
| Zero-build | UMD `<script>` | ESM/modular, часто нужен сборщик |
| Объём | ~1.1 МБ min (standalone) | ядро ~250 КБ, но +свой код |
| Тесты | статик-маркеры + JS-юниты данных | больше кода → больше тестов |
| Поддержка | активная, широкая | активная, но UI-слой = наш |

Ключевой аргумент — **нужен готовый интерактивный force-directed граф с
drag/zoom** (Obsidian-style) в zero-build TMA; `vis-network` даёт это без
собственного кода физики/камеры/хит-теста. `d3-force` лишь считает симуляцию —
рендер, камера, drag, hover, кластеризация и perf-бюджет остаются на нас.

## 4. Митигации объёма/риска

- **Self-host** (CSP `script-src 'self'`, offline, нет CDN-зависимости) +
  `.gitignore`-исключение тяжёлых source-map (по образцу OD18); коммитим только
  min-бандлы.
- **Ленивая загрузка** только на «Статус» → первичная загрузка TMA не растёт.
- **Лимиты**: ≤ `GRAPH_MAX_NODES=120` узлов, `GRAPH_MAX_EDGES=240` рёбер
  (серверный cap) → Canvas стабилен на Android.
- **`prefers-reduced-motion`**: physics/анимация отключаются (статические узлы
  с drag/zoom) — WCAG AA.
- **destroy-дисциплина** (R10.11-5/R10.10-3): `network.destroy()` при уходе с
  вкладки/`unmount`; в 15с-polling экземпляр НЕ пересоздаётся, если подпись
  данных (узлы/рёбра) не изменилась — drag/zoom/physics не сбрасываются
  (ISSUE-4).

## 5. Альтернативы

- **A1. d3.js (force + SVG/Canvas)** — отклонено: больше кода (камера/drag/хит-тест),
  риск perf на Android, нет выигрыша при нулевом bundler. Кандидат при отказе от vis.
- **A2. Cytoscape.js** — зрелая, canvas, но тяжёлее и API сложнее; лишние сущности
  (лейауты/расширения), нет преимуществ для ~120 узлов.
- **A3. Свой Canvas-рендер** — отклонено: неоправданная стоимость/тесты.
- **A4. CDN vis-network** — отклонено: офлайн/Android/CSP-риск; self-host
  безопаснее (прецедент DOMPurify).

## 6. Последствия

- В `web/index.html` — ленивый loader + `<div ref="cognitionGraph">`; в `web/app.js` —
  `renderCognitionGraph()` + model-функции (JS-юниты на данные/классы).
- Каталог/бэкенд-API графа — в `cognition-dashboard` spec (§3); библиотека
  НЕ влияет на контракты.
- Провенанс/версия `vis-network` фиксируется в `.gitignore`/README vendor-записи.
