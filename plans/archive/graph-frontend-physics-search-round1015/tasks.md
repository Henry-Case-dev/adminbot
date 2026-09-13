# Фича F2 — `graph-frontend-physics-search-round1015` (Физика графа + поиск, frontend)

> **Статус: ✅ COMPLETED** (Step 4 @Builder, 14.09.2026). Реализовано T-1559…T-1564,
> гейты T-1558/T-1565 за @Architect/@Reviewer. pytest **5619 passed / 0 failed**,
> `node --check` clean, `JS-UNIT-OK`.
> **Раунд:** 10.15. **Нумерация:** T-1558…T-1565 (продолжает F1 T-1557).
> **Тип:** frontend. **Приоритет:** **P1**.
> **Зависимости:** **F1** (`graph-sampling-centrality-round1015`, §1 backend) — для осмысленного
> графа с рёбрами. **Конфликт файлов:** `web/index.html` делит с **F5** — вливать согласованно.
> **ТЗ:** `plans/current_task.md`, раздел **1** (frontend-часть: `barnesHut` + «Поиск по графу»).
> **Эпик:** `Epic: Багфиксы Графа памяти, Воркера Сна и Ностальгии round1015`.
> **Baseline:** HEAD `798e044`; pytest **5589 passed / 0 failed**; каталог **435/90/406/411/88/19**.

## 0. Цель

Включить физику отталкивания `barnesHut`, чтобы кластеры разлетались; добавить простой инпут
«Поиск по графу», центрирующий камеру на узле по имени. Сохранить self-host `vis-network`
(ADR-1013-2), `reducedMotion`, подпись данных `_cognitionGraphSig` и `destroy` при уходе.

**Текущее состояние (Step 0):** `web/app.js:5244-5283` `renderCognitionGraph` + `destroyCognitionGraph`;
`_graphSignature` `:5234-5243`; lazy-load `ensureVisNetwork` `:5197-5219`; опции физики сейчас —
`{ stabilization: { iterations: 120, fit: true } }` (`:5267-5269`, barnesHut НЕ задан);
`web/index.html` — секция «Мониторинг Интеллекта» `:2911-2960` (граф внутри), vendor
`web/static/vendor/vis-network/vis-network.min.js`.

## 1. Требования (дословно из ТЗ §1)

- [ ] **Frontend (vis-network):** включить физику отталкивания (`barnesHut`), чтобы кластеры красиво
  разлетались, а не слипались.
- [ ] Добавить простой инпут **«Поиск по графу»**, который будет центрировать камеру на узле по имени.

## 2. Целевые модули (`file:line` на HEAD `798e044`)

- `web/app.js:5244-5283` — `renderCognitionGraph`/`destroyCognitionGraph` (physics-опции `:5259-5272`).
- `web/app.js:5234-5243` — `_graphSignature` (не ломать; при необходимости — учёт подсветки).
- `web/app.js:897-905` — data-поля `cognitionGraphData`/`_cognitionGraphSig`/`cognitionVisLoaded`.
- `web/index.html:2911-2960` — блок «Мониторинг Интеллекта» (место для инпута и/или контейнера графа).
- Тесты: `tests/test_webapp_round1014_ui.py` (маркеры UI), `tests/js/routing_test.js`; новый
  `tests/test_webapp_round1015_ui.py`.

## 3. Инварианты (constraints — не нарушать)

- **⛔ Новых CDN/`v-html` нет** — `vis-network` только self-host (ADR-1013-2), DOMPurify-правило.
- `reducedMotion` → физика не запускается (сохранить ветку `physics:false`).
- 15с-polling не должен сбрасывать drag/zoom/physics при неизменных данных (`_cognitionGraphSig`,
  ISSUE-4/R10.11-5) — пересоздавать сеть только при реальном изменении.
- `destroy` при уходе со `status` (R10.11-5) сохранить; stale-инстансы не создавать.
- R16: `id` — ключ, поиск по `label` (не по id); R17 безопасность.
- Каталог-инварианты **435/90/406/411/88/19** — Δ=0.
- `media/`/`.env` не трогать; порядок роутеров `bot.py` не трогать.
- **Ревью-гейты:** полный `pytest` 0 регрессий, `node --check web/app.js`,
  `node tests/js/routing_test.js` → `JS-UNIT-OK`, маркер-тесты UI, русские conventional commits.

## 4. Зависимости

- **Вверх:** **F1** (§1 backend) — фронт показывает результат нового алгоритма.
- **Вниз:** нет.
- **Конфликт файлов:** `web/index.html` делят F5/F2 — вливать ступенями (F1 → F2, затем F5).

## 5. Definition of Done

- [ ] `barnesHut` включён (springLength/avoidOverlap/gravitationalConstant) — кластеры не слипаются.
- [ ] Инпут «Поиск по графу» центрирует камеру на найденном узле (подстрока, без регистра) и
  подсвечивает его; «не найдено» → понятная обратная связь, сеть не ломается.
- [ ] `reducedMotion`, `_cognitionGraphSig`, `destroy` работают как раньше.
- [ ] `node --check` clean, `routing_test` OK, полный `pytest` — **0 failed**.

## 6. Чек-лист задач

- [ ] **T-1558 (@Architect, гейт):** спека physics-опций (barnesHut: `springLength`,
  `avoidOverlap`, `gravitationalConstant`, `damping`, `centralGravity`) + UX поиска (центрирование vs
  `focus`/`moveTo`, порог зума, подсветка, поведение при пустом вводе и без совпадений).
- [x] **T-1559 (@Builder):** заменить физику в `renderCognitionGraph` (`app.js:5259-5272`) на
  `barnesHut`; сохранить `reducedMotion`-ветку и стабилизацию.
- [x] **T-1560 (@Builder):** разметка инпута «Поиск по графу» в секции «Мониторинг Интеллекта»
  (`web/index.html:2911-2960`) — поле ввода + иконка/кнопка, доступность (`aria-label`, Enter).
- [x] **T-1561 (@Builder):** метод `searchCognitionGraph` в `app.js`: нормализация (casefold,
  обрезка), поиск по `label`, `network.focus`/`moveTo` + `selectNodes`, `toast` при отсутствии;
  сброс подсветки на пустом вводе.
- [x] **T-1562 (@Builder):** не ломать `_graphSignature`/`destroy`/polling; повторный поиск при
  отсутствии инстанса → дождаться рендера (защита от гонки lazy-load).
- [x] **T-1563 (@Builder):** маркер-тесты UI (`tests/test_webapp_round1015_ui.py`): инпут/`barnesHut`
  присутствуют в разметке/JS; при наличии — JS-unit.
- [x] **T-1564 (@Builder):** прогон гейтов: `node --check web/app.js` clean,
  `node tests/js/routing_test.js` → `JS-UNIT-OK`, полный `pytest` **0 failed**, `git diff --check`;
  русский commit.
- [ ] **T-1565 (@PM/@Reviewer, гейт):** сверка DoD, live-чеклист владельцу (Android: физика/поиск).

## 7. Открытые вопросы (@Architect → владелец)

- **F2-Q1:** поведение при нескольких совпадениях — первое / цикл по Enter / выпадающий список?
- **F2-Q2:** поиск ищет только по `label` узла или и по `relation_type` рёбер?
- **F2-Q3:** включать ли физику постоянно или off после стабилизации (экономия Android WebView)?
- **F2-Q4:** нужен ли сброс зума/камеры после поиска (кнопка «Сбросить вид»)?

## 8. Feature flag / progressive delivery

- **Feature flag:** не требуется (render-only). Rollback = `git revert`.
- **Progressive delivery:** неприменимо.
