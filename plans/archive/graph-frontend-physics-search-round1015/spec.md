# Спека F2 — `graph-frontend-physics-search-round1015` (Физика `barnesHut` + поиск по графу)

> **Статус:** ✅ COMPLETED (Step 4 @Builder, 14.09.2026). Реализовано T-1559…T-1564; гейты T-1558/T-1565 за @Architect/@Reviewer.
> **Раунд:** 10.15. **Тип:** frontend (`web/app.js`, `web/index.html`). **Приоритет:** P1. **T-ID:** T-1558…T-1565.
> **ТЗ:** `plans/current_task.md` §1 (frontend-часть). **Зависимости:** F1 (backend-выборка) — визуальный эффект зависит от связного графа.
> **Конфликт файлов:** `web/index.html` делит с F5 — вливать ступенями (F2 → F5).
> **Baseline:** HEAD `798e044`; pytest 5589/0; каталог 435/406/411/90/88/19.

## 1. Цель

Кластеры графа должны «разлетаться» (физика отталкивания `barnesHut` вместо текущей физики по умолчанию), а инпут «Поиск по графу» должен центрировать/фокусировать камеру на узле по имени. Не сломать self-host `vis-network` (ADR-1013-2), `reducedMotion`, подпись `_cognitionGraphSig` и `destroy`-дисциплину (R10.11-5/ISSUE-4).

**Текущее состояние:** `web/app.js:5244-5283` `renderCognitionGraph`; физика — `{ stabilization: { iterations: 120, fit: true } }` без solver (`:5267-5269`); `_graphSignature` `:5234-5243`; lazy-load `ensureVisNetwork` `:5197-5219`; разметка «Мониторинг Интеллекта» `web/index.html:2911-2982`, контейнер графа `:2980`.

## 2. Scope

**In scope**
- Заменить опции физики в `renderCognitionGraph` на `barnesHut` (сохранить `reducedMotion → physics:false` и стабилизацию).
- Добавить в разметку секции графа (`index.html` около `:2972-2980`) поле «Поиск по графу» + кнопку сброса вида.
- Методы `searchCognitionGraph`, `clearCognitionGraphSearch` в `app.js`; повторный поиск при гонке lazy-load.
- Маркер-тесты UI; обновление JS-unit.

**Out of scope**
- Backend-выборка (F1). Релокация статистики/бейджи (F5).
- Новые CDN/`v-html` (запрещено, ADR-1013-2). Новые каталог-ключи (Δ=0).

## 3. Контракты/API

Новых API нет. Поиск работает по уже загруженному `cognitionGraphData.nodes[].label` (R16: `id` — ключ, поиск по `label`, НЕ по id). Изменений `/api/memory/graph` нет.

## 4. Конфиг физики (точный)

F2-Q3 RESOLVED: физика **включается только при рендере** и стабилизируется; при `reducedMotion` — выключена (существующая ветка сохраняется).

```js
var options = {
  nodes: { shape: 'dot', size: 14, font: { size: 12, color: '#e5e7eb' } },
  edges: { arrows: 'to', smooth: true,
           color: { color: 'rgba(148,163,184,.45)' },
           font: { size: 10, color: '#94a3b8' } },
  interaction: { hover: true, dragNodes: true, dragView: true, zoomView: true },
  physics: this.reducedMotion ? false : {
    solver: 'barnesHut',
    barnesHut: {
      gravitationalConstant: -8000,   // расталкивание (негатив)
      centralGravity: 0.3,            // удержание в кадре
      springLength: 120,              // длина пружины рёбер
      springConstant: 0.04,
      damping: 0.09,                  // гасит «болтанку»
      avoidOverlap: 0.2               // не даёт слипаться
    },
    stabilization: { enabled: true, iterations: 250, updateInterval: 25, fit: true },
    minVelocity: 0.75
  },
  groups: { user: { color: '#a78bfa' }, topic: { color: '#38bdf8' },
            event: { color: '#f59e0b' }, fact: { color: '#34d399' } }
};
```

- Значения — код-константы (без каталога). Подбор на Android WebView — live-чеклист (T-1565).
- `stabilization.fit: true` — после стабилизации граф вписывается в контейнер (текущее поведение).
- `_cognitionGraphSig` и `destroy`-дисциплина НЕ меняются: физика задаётся при создании `vis.Network`, пересоздание — только при изменении подписи.

## 5. UX поиска (точный)

F2-Q1 RESOLVED: **первое совпадение + циклический перебор по повторному Enter**. F2-Q2 RESOLVED: поиск **только по `label`** узла (не по рёбрам).

**Разметка** (`web/index.html`, внутри блока «Граф связей», рядом со счётчиком, `~:2973-2978`):
```html
<div class="graph-search">
  <input type="search" class="input graph-search__input"
         placeholder="Поиск по графу…" aria-label="Поиск узла по имени"
         v-model.trim="graphSearchQuery"
         @keydown.enter.prevent="searchCognitionGraph()"
         @keydown.esc="clearCognitionGraphSearch()">
  <button class="btn-ghost text-xs" type="button"
          @click="searchCognitionGraph()"
          :disabled="!cognitionNetwork">Найти</button>
  <button class="btn-ghost text-xs" type="button"
          @click="clearCognitionGraphSearch()"
          :disabled="!cognitionNetwork">Сбросить вид</button>
  <span v-if="graphSearchStatus" class="text-xs text-gray-500">{{ graphSearchStatus }}</span>
</div>
```
Класс `.graph-search` — flex-wrap, отступ сверху 8px; на узких экранах переносится в столбик.

**Логика** (`app.js`, новые data-поля: `graphSearchQuery: ''`, `graphSearchStatus: ''`, `_graphSearchMatches: []`, `_graphSearchIdx: 0`):
```js
searchCognitionGraph: async function () {
  var q = String(this.graphSearchQuery || '').trim().toLowerCase();
  if (!this.cognitionNetwork) {
    // гонка lazy-load: дождаться рендера и повторить один раз
    await this.renderCognitionGraph();
    if (!this.cognitionNetwork) return;
  }
  if (!q) { this.clearCognitionGraphSearch(); return; }
  var nodes = (this.cognitionGraphData && this.cognitionGraphData.nodes) || [];
  var hits = nodes.filter(function (n) {
    return String(n.label || '').toLowerCase().indexOf(q) !== -1;
  });
  if (!hits.length) {
    this._graphSearchMatches = []; this._graphSearchIdx = 0;
    this.graphSearchStatus = 'Ничего не найдено';
    this.toast('В графе нет узла «' + q + '»', 'warn');
    return;
  }
  // циклический перебор при повторном поиске того же запроса
  if (q !== this._graphSearchLastQ) { this._graphSearchIdx = -1; }
  this._graphSearchLastQ = q;
  this._graphSearchMatches = hits;
  this._graphSearchIdx = (this._graphSearchIdx + 1) % hits.length;
  var node = hits[this._graphSearchIdx];
  var anim = this.reducedMotion
    ? false : { duration: 600, easingFunction: 'easeInOutQuad' };
  this.cognitionNetwork.focus(node.id, { scale: 1.1, animation: anim });
  this.cognitionNetwork.selectNodes([node.id]);
  this.graphSearchStatus = 'Найден: ' + node.label +
    (hits.length > 1 ? ' (' + (this._graphSearchIdx + 1) + '/' + hits.length + ')' : '');
},
clearCognitionGraphSearch: function () {
  this.graphSearchQuery = ''; this.graphSearchStatus = '';
  this._graphSearchMatches = []; this._graphSearchIdx = 0;
  this._graphSearchLastQ = '';
  if (this.cognitionNetwork) {
    this.cognitionNetwork.selectNodes([]);
    var anim = this.reducedMotion ? false : { duration: 500 };
    this.cognitionNetwork.fit(anim);
  }
}
```
- **Пустой ввод:** Enter/esc → сброс подсветки и `fit()` (сеть не пересоздаётся).
- **Нет совпадений:** `graphSearchStatus='Ничего не найдено'` + `toast('warn')`; сеть не ломается, подсветка не меняется.
- **`reducedMotion`:** `focus`/`fit` без анимации.
- **Не ломать polling:** поиск не вызывает `loadCognition`/пересоздание сети; 15с-polling и `_graphSignature` нетронуты.
- **destroy:** при уходе с «Статуса» `destroyCognitionGraph` обнуляет инстанс; при возврате поиск пересоздаст сеть через `renderCognitionGraph`.

## 6. Точки изменения (file:line)

| # | Файл:строка | Изменение |
|---|---|---|
| 1 | `web/app.js:5259-5272` | `options.physics` → `barnesHut` (см. §4). |
| 2 | `web/app.js:897-905` | Новые data-поля поиска (см. §5). |
| 3 | `web/app.js:5244-5283` | Не менять `_graphSignature`/`destroy`-механику; `renderCognitionGraph` без ломки `reducedMotion`. |
| 4 | `web/app.js` (рядом с `renderCognitionGraph`) | Новые методы `searchCognitionGraph`, `clearCognitionGraphSearch`. |
| 5 | `web/index.html:2972-2980` | Разметка инпута/кнопок поиска в блоке «Граф связей». |
| 6 | `web/index.html` (CSS рядом с `.cognition-graph`, `:725-728`) | `.graph-search` flex-wrap/столбик на узком экране. |

**Не трогать:** `ensureVisNetwork` (self-host), `startCognitionPolling`/`stopCognitionPolling`, `destroyCognitionGraph`, `cognition-graph` контейнер.

## 7. Feature-флаг / progressive delivery

Не требуется (render-only). Rollback = `git revert`. Каталог-Δ=0.

## 8. Тест-план

- `tests/test_webapp_round1015_ui.py` (маркеры): наличие `barnesHut`/`solver:'barnesHut'` в `app.js`; наличие `graph-search`/`Поиск по графу`/`searchCognitionGraph` в `index.html`/`app.js`.
- `tests/js/routing_test.js` (+ при необходимости `tests/test_webapp_js_unit.py`): юнит `searchCognitionGraph`/`clearCognitionGraphSearch` на моке `cognitionNetwork` (`focus`/`selectNodes`/`fit` вызваны; пусто → без focus; нет hits → статус «Ничего не найдено»); `_graphSignature` не изменилась.
- `tests/test_webapp_round1014_ui.py` — проверить, что маркеры бейджей/лент не сломаны.
- **Гейты:** `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; полный `pytest` 0 failed; `git diff --check`; каталог Δ=0.

## 9. Открытые вопросы → решения

- **F2-Q1** несколько совпадений: первое + перебор по Enter (циклически).
- **F2-Q2** поиск: **только по `label`**.
- **F2-Q3** физика: включена постоянно (стабилизация + `damping`), off при `reducedMotion`. После стабилизации vis «замораживает» узлы (сеть не пересоздаётся) — экономия Android.
- **F2-Q4** сброс вида: кнопка «Сбросить вид» → `fit()`.

## 10. Риски

| Риск | Митигация |
|---|---|
| «Слипание»/долгая стабилизация на Android | Подбор `gravitationalConstant`/`avoidOverlap` live-чеклистом (T-1565); `stabilization.iterations=250`. |
| Поиск до загрузки vis-network | Ожидание `renderCognitionGraph` + повтор (гонка закрыта). |
| Слом 15с-polling | Поиск не трогает `loadCognition`/`_graphSignature`; тест на отсутствие пересоздания. |
| Переполнение строки на мобильном | `.graph-search` flex-wrap + столбик на узком экране. |

## 11. Критерии приёмки (DoD)

- [ ] `barnesHut` включён; кластеры не слипаются; `reducedMotion → physics:false`.
- [ ] Инпут «Поиск по графу» центрирует камеру на найденном узле (подстрока, без регистра), подсвечивает; несколько совпадений — перебор по Enter; «не найдено» — понятная обратная связь, сеть цела.
- [ ] Пустой ввод/esc — сброс подсветки + `fit()`.
- [ ] `_graphSignature`/`destroy`/15с-polling работают как раньше; self-host `vis-network` не изменён.
- [ ] `node --check` clean; `JS-UNIT-OK`; полный `pytest` 0 failed; каталог Δ=0.

## 12. Инварианты

ADR-1013-2 (self-host vis-network, без новых CDN/`v-html`), R10.11-5/ISSUE-4 (destroy-дисциплина, нет пере-рендера при той же подписи), R16/R17, `media/`/`.env`/порядок роутеров `bot.py` не трогать.
