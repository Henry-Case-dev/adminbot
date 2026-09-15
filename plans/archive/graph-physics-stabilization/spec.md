# Spec F4 — `graph-physics-stabilization` (150 итераций + отключение физики по `stabilizationIterationsDone`)

> **Раунд:** 10.18 (Step 2 @Architect, 15.09.2026). **Тип:** frontend (`web/app.js`, vis-network). **Приоритет:** P1.
> **ADR:** `adr-1018-4-graph-physics-stabilization.md` (AMEND F2 10.15).
> **Задачи:** T-1736…T-1741. **Зависит:** F3 (ёмкость 500–800 узлов). **Baseline:** HEAD `118a03c`; pytest 6007 passed.
> **Источник:** `plans/current_task.md` §3.3 (строки 72–74).

## 1. Контекст и цель

После F3 граф вырастает до 500–800 узлов, физика отталкивания может тормозить. Цель: короткая стабилизация (`iterations: 150`) и **автоотключение физики** по событию `stabilizationIterationsDone`/`stabilized` → пользователь зумит/двигает граф при ~60 FPS. Сохранить зум/перетаскивание/поиск/подсветку/`reducedMotion`.

## 2. Текущее поведение (сверено с кодом)

`renderCognitionGraph` (`web/app.js:5277-5324`):
- `physics: this.reducedMotion ? false : { solver:'barnesHut', barnesHut:{…}, stabilization:{ enabled:true, iterations:250, updateInterval:25, fit:true }, minVelocity:0.75 }` (`:5302-5317`).
- Физика **всегда включена** (при не-reducedMotion) — с раунда 10.15 F2 (`iterations: 250`).
- `_graphSignature` (`:5267-5276`) включает `degree`; при изменении данных → `destroyCognitionGraph()` (`:5377-5383`) и полное пересоздание `vis.Network`.
- Поиск (`searchCognitionGraph`, `:5329-5364`) использует `focus`/`selectNodes` с `anim` (учитывает `reducedMotion`).
- Polling 15с: если подпись не изменилась, сеть не пересоздаётся (`:5288`).
- self-host vis-network (ADR-1013-2); внешних CDN нет (ADR-1016-2).

## 3. Требуемое поведение

1. `physics.stabilization.iterations = 150`.
2. Слушатель `stabilizationIterationsDone` (и/или `stabilized`) → `physics.enabled = false` **после** первичной расстановки.
3. Повторный рендер/`destroy` корректно пересоздаёт сеть (не «залипает» выключенная физика).
4. `reducedMotion` → физика изначально `false`; поиск/подсветка не затронуты.
5. Зум/перетаскивание/бейджи/поиск сохранены.

## 4. Технический дизайн (`web/app.js`)

### 4.1. Опции
```js
physics: this.reducedMotion ? false : {
  solver: 'barnesHut', barnesHut: { /* без изменений */ },
  stabilization: { enabled: true, iterations: 150, updateInterval: 25, fit: true },
  minVelocity: 0.75,
},
```
Новые/обновлённые константы (код, каталог-Δ=0):
```js
var GRAPH_PHYSICS_ITERATIONS = 150;
var GRAPH_PHYSICS_DISABLE_ON_STABILIZE = true;
```
(вынести рядом с другими graph-константами в модуле; маркеры для JS-тестов).

### 4.2. Отключение физики
После создания сети:
```js
this.cognitionNetwork = new window.vis.Network(el, { nodes, edges }, options);
if (!this.reducedMotion && GRAPH_PHYSICS_DISABLE_ON_STABILIZE) {
  var net = this.cognitionNetwork;
  var _off = function () {
    // guard: ТОЛЬКО тождество инстанса. destroyed/isDestroyed в self-host
    // vis-network v9.1.9 отсутствуют — проверять их нельзя (B3-1).
    if (net && net === self.cognitionNetwork) {
      try { net.setOptions({ physics: { enabled: false } }); } catch (e) {}
    }
  };
  net.once('stabilizationIterationsDone', _off);
  net.once('stabilized', _off);
}
```
- Использовать `once`, не `on` (не копим обработчики при повторных рендерах).
- Guard **только** по `net === this.cognitionNetwork` (B3-1: `destroyCognitionGraph` обнуляет `this.cognitionNetwork=null` → уничтоженный инстанс отсекается; полей `destroyed`/`isDestroyed` в self-host vis-network **v9.1.9 НЕТ** — прежняя формулировка была мёртвым guard-ом). JS-тест `tests/js/routing_test.js` подтверждает: вызов `setOptions({physics:{enabled:false}})` по событию нового инстанса; старый инстанс после `destroy` вызова НЕ получает; пересоздание сети; отсутствие слушателей при `reducedMotion`.
- `destroyCognitionGraph` (`:5377-5383`) уже вызывает `network.destroy()` и обнуляет `_cognitionGraphSig` → новый рендер создаёт сеть заново с `physics.enabled` из опций (не «залипает»).
- `reducedMotion`: физика изначально `false`, слушатели не навешиваем.

### 4.3. Совместимость
- Поиск (`:5329-5364`) работает на выключенной физике (focus/selectNodes не требуют physics).
- Повторный рендер при смене данных (подпись) → `destroy` → новый инстанс с физикой, стабилизация, отключение.
- Опции `interaction`, `groups`, `nodes`, `edges` — без изменений.

## 5. Изменения схемы / каталога / env

- DDL нет; каталог **Δ=0** (UI-константы); env/`.env` не трогать; внешних CDN не вводить (ADR-1013-2/1016-2).

## 6. Влияние на тесты

- `tests/js/routing_test.js` — маркеры: `iterations: 150` (или `GRAPH_PHYSICS_ITERATIONS`), наличие `stabilizationIterationsDone`/`stabilized`, `physics: { enabled: false }`, сохранение `reducedMotion`, `once(` вместо `on(`.
- `node --check web/app.js`; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `node tests/js/vue_mount_test.js` → `VUE-MOUNT-OK`.
- Полный `pytest` 0 failed (бэкенд не затронут); `git diff --check`.
- Визуальная проверка десктоп + мобильный (500–800 узлов).

## 7. Rollout / feature-flag / откат

- Флаг не требуется (UI-опция). Rollback = `git revert`.
- Порядок: **после F3** (ёмкость). `web/app.js` делится с F2 — вливать ступенями F2 → F4.
- Progressive delivery неприменим; визуальная проверка.

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | Конфликт с F2 10.15 (`iterations:250`, физика всегда on) | ADR-1018-4 фиксирует новое поведение; JS-маркер |
| R2 | «Замороженный» неоптимальный layout | 150 итераций + визуальная проверка; при необходимости — ручной drag |
| R3 | Повторный рендер оставит физику выключенной | `once` + guard + destroy → пересоздание с options |
| R4 | Сломан `reducedMotion`/поиск/подсветка | маркеры T-1739 + ревью T-1740 |
| R5 | `web/app.js` делится с F2 | ступенчатое вливание |

## 9. Открытые вопросы для human-gate

1. **`iterations=150` при 800 узлах достаточно?** → **Рекомендация:** да (ТЗ §3.3); при плохом layout — увеличить до 200 отдельной правкой (не блокер).
2. **Отключать ли физику также при `reducedMotion=false`, но малом N (<50)?** → **Рекомендация:** нет (единое поведение).
