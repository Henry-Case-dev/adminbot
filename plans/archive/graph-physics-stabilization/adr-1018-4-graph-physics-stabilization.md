# ADR-1018-4 — Физика графа: 150 итераций + авто-отключение по `stabilizationIterationsDone`

- **Статус:** Proposed
- **Дата:** 2026-09-15
- **Раунд:** 10.18, фича F4 `graph-physics-stabilization` (T-1736)
- **База:** HEAD `118a03c`.
- **AMEND:** **F2 раунда 10.15** (`graph-frontend-physics-search-round1015`, §36) — «barnesHut + физика всегда включена, `stabilization.iterations: 250`». Сохраняется barnesHut-конфигурация; заменяются `iterations` и политика «физика постоянно включена».
- **Связано:** ADR-1013-2 (vis-network, canvas, `reducedMotion`, destroy-дисциплина), ADR-1016-2 (CSP/self-host), ADR-1018-3 (плотность 500–800).

## Context

1. `renderCognitionGraph` (`web/app.js:5277-5324`) задаёт `stabilization.iterations: 250` и **не** отключает физику после расстановки (`:5302-5317`). При росте до 500–800 узлов (F3) постоянная симуляция тормозит Android WebView и мешает зуму/драгу.
2. ТЗ §3.3 требует: `iterations: 150` + обработчик `stabilizationIterationsDone`/`stabilized` → `physics.enabled = false`.
3. Существующие инварианты, которые нельзя сломать: `reducedMotion → physics:false`; `_graphSignature` + `destroyCognitionGraph` (пересоздание только при реальном изменении данных, ISSUE-4/R10.11-5); поиск `searchCognitionGraph` (focus/selectNodes); self-host vis-network (ADR-1013-2).
4. vis-network (self-host, v9.x) поддерживает события `stabilizationIterationsDone` и `stabilized` и `network.setOptions({physics:{enabled:false}})`.

## Decision

### D1. `stabilization.iterations = 150`
Вынести значение в модульную константу `GRAPH_PHYSICS_ITERATIONS = 150` (код, каталог-Δ=0; маркер для JS-тестов). `barnesHut`-параметры, `minVelocity`, `updateInterval:25`, `fit:true` — без изменений.

### D2. Авто-отключение физики
После создания сети — `net.once('stabilizationIterationsDone', off)` **и** `net.once('stabilized', off)`, где `off` вызывает `net.setOptions({physics:{enabled:false}})` под guard **только по тождеству** `net === this.cognitionNetwork` (B3-1: `destroyCognitionGraph` обнуляет `this.cognitionNetwork=null` → уничтоженный инстанс отсекается; `destroyed`/`isDestroyed` в self-host vis-network v9.1.9 ОТСУТСТВУЮТ). `once` (не `on`) — обработчики не накапливаются между рендерами.

### D3. Повторный рендер/`destroy`
`destroyCognitionGraph` (`:5377-5383`) уничтожает сеть и обнуляет подпись; следующий рендер создаёт **новый** `vis.Network` с физикой из `options` → «залипание» выключенной физики исключено. Дополнительных флагов не вводим.

### D4. `reducedMotion` — без изменений
При `reducedMotion` физика изначально `false`, слушатели **не** навешиваются (анимация/симуляция отключены — WCAG AA). Поиск и подсветка сохраняются (используют `focus`/`selectNodes`, не physics).

### D5. Поиск/подсветка/бейджи не затрагиваются
`searchCognitionGraph`, `clearCognitionGraphSearch`, бейджи `dreamPhaseBadge`/`deepPhaseBadge` — вне диффа. Выключенная физика не влияет на `focus`.

## Consequences

**Positive**
- Плавный старт и стабильные ~60 FPS при 500–800 узлах (после первичной стабилизации).
- Меньше CPU/батареи на Android WebView; drag/zoom отзывчивее.
- Минимальный объём правок (опции + 1 слушатель), каталог-Δ=0, без DDL/CDN.

**Negative**
- Layout фиксируется после 150 итераций; при неудачном начальном раскладе пользователь может «дожать» вручную (dragging работает).
- Один дополнительный обработчик на инстанс (снят `once`/`destroy`).
- Небольшое расхождение с прежним 250 (возможны иные визуальные формы).

## Alternatives

- **A1. Оставить `iterations:250` и физику включённой.** Отклонено: ТЗ §3.3; тормоза при 500–800.
- **A2. `physics.enabled=false` сразу (без стабилизации).** Отклонено: узлы слипнутся в кучу, нет раскладки.
- **A3. `on` вместо `once`.** Отклонено: утечка/повторные срабатывания при пересозданиях.
- **A4. Ручной `setTimeout` для отключения.** Отклонено: хрупко, не связано со фактом завершения стабилизации.
- **A5. Включить физику по кнопке «перетряхнуть».** Отложено (не требуется ТЗ; возможный follow-up).
- **A6. Отключать физику только при N>порога.** Отклонено: непредсказуемо; единое поведение проще и предсказуемее.

## References

- `web/app.js:5267-5276` (`_graphSignature`), `:5277-5324` (`renderCognitionGraph`, physics), `:5329-5364` (поиск), `:5377-5383` (`destroyCognitionGraph`), `:5385-5408` (polling)
- ADR-1013-2; ADR-1016-2; ADR-1018-3; §36 (F2 10.15)
- Задачи: T-1736 (ADR/spec), T-1737 (iterations), T-1738 (слушатель/пересоздание), T-1739 (JS-тесты), T-1740 (@Reviewer/@PM), T-1741 (гейты/commit).
