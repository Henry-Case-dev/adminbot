# Фича F3 — `persona-ui-tab-round1014` (UI: подраздел «Личность» в разделе «ИИ»)

> **Статус: ✅ COMPLETED** (Step 4 @Builder, 13.09.2026). Код + тесты готовы; ждёт ревью/деплой (T-1503/T-1504).
> **Раунд:** 10.14. **Нумерация:** T-1498…T-1504 (продолжает T-1497).
> **Тип:** frontend. **Приоритет:** P1.
> **Зависимости:** **F2** (API персоны). **ТЗ:** `plans/current_task.md` §3 + UPD п.2. **Baseline:** HEAD `2edc65b`.

## 0. Цель

В `#/ai` — карточка «Личность» и экран-форма ТОЛЬКО статических параметров (Имя, Биография, Характер, «Осознаёт себя
ИИ»). Реактивно зависит от выбранного чата. Никакой визуализации. Флаги ON по умолчанию (UPD п.2).

## 1. Требования (ТЗ §3 + UPD п.2)

- [x] Внутри корневого раздела «ИИ» — подраздел «Личность».
- [x] Реактивная зависимость от выбранного чата (Global ↔ чат).
- [x] Форма ТОЛЬКО статических параметров; никакой визуализации.
- [x] Флаги включены по умолчанию.

## 2. Целевые модули (`file:line` на HEAD `2edc65b`)

- `web/app.js`: `HUBS['#/ai']` `:270-296`; `ROUTE_TO_TAB` `:572`; `ROUTE_PARENT` `:619`; state `:860+`;
  methods `loadPersona/savePersona/resetPersona`; `setTab` `:2607`; `setActiveChat` `:1621`.
- `web/index.html`: special-screen `v-else-if="activeTab==='persona'"` (рядом с `info`).
- `web/api/routes.py` (F2)*: `GET/PUT/DELETE /api/persona`.
- **НЕ трогать:** `TABS`/`TAB_SECTION_ORDER`/`TAB_RULES`/`CONFIG_TAB_TITLES` (special-screen, Δ=0).
- Тесты: `tests/test_webapp_round1014_ui.py`, `tests/js/routing_test.js`.

## 3. Инварианты (обновлено)

- ✅ PG-DDL разрешён, но F3 Δ каталога = **0** (персона — PG-API, special-screen).
- ⛔ **`TABS.length == 19`** и `TAB_SECTION_ORDER` не менять (иначе падает зеркало TAB_RULES).
- ⛔ Порядок роутеров `bot.py` не трогать. `media/`/`.env` не трогать.
- **R17/R16**; никаких новых `v-html`/CDN.
- Scope-сохранение не затирает чужой scope (согласовано с F5).
- **Ревью-гейты:** полный `pytest` 0 регрессий, `node --check web/app.js`, `node tests/js/routing_test.js`,
  R17-скан, русские conventional commits.

## 4. Зависимости

- **Вверх:** **F2** (API + контракт).
- **Вниз:** **F6** (гайд ссылается на вкладку). **F4** параллельна (обе зависят от F2), но `web/app.js`/`index.html`
  делят F3/F4/F6/F7 — вливать ступенями.

## 5. Definition of Done

- [x] В `#/ai` есть карточка/экран «Личность»; маршрут работает.
- [x] Форма ровно 3 поля + чекбокс; визуализаций нет.
- [x] Scope-реактивность: не затирает введённое; читает свой скоуп.
- [ ] Сохранение переживает рестарт `admin_bot` (гейт T-1503).
- [x] `TABS`/`TAB_RULES` не изменены; полный `pytest` 0 failed; `node --check` clean; `JS-UNIT-OK`.

## 6. Чек-лист задач

- [x] **T-1498 (@Builder):** карточка/маршрут «Личность» в Hub «ИИ» (`HUBS`, `ROUTE_TO_TAB`, `ROUTE_PARENT`),
  special-screen-форма (3 поля + чекбокс) в `web/index.html`; без визуализаций.
- [x] **T-1499 (@Builder):** `loadPersona`/`savePersona`/`resetPersona` через `/api/persona`; индикатор
  scope/наследования; бейдж «выключено» при `persona_enabled=false` + disabled-контролы.
- [x] **T-1500 (@Builder):** scope-реактивность (`setActiveChat`/`setTab`/`scopeEpoch`), пустое значение ≠ дефолт,
  сброс override.
- [x] **T-1501 (@Builder):** тесты: маркеры UI, роутинг, инвариант `TABS.length==19`/`'persona' not in TABS`,
  scope-реактивность.
- [x] **T-1502 (@Builder):** `node --check web/app.js`, `node tests/js/routing_test.js`, полный `pytest` (0 failed),
  `git diff --check`.
- [ ] **T-1503 (@PM/@Reviewer, гейт):** сверка DoD/инвариантов, «сохранил → рестарт → значение на месте».
- [ ] **T-1504 (@PM/@DevOps):** live-чеклист владельцу (Android/Telegram).

## 7. Открытые вопросы (закрыты)

- **F3-Q1:** special-screen (не config-вкладка). **F3-Q2:** пустые поля. **F3-Q3:** bool. **F3-Q4:** кнопка сброса — да.

## 8. Feature flag / progressive delivery

- `flags.persona_enabled` **ON**; OFF → бейдж + disabled. Rollback = `git revert`. Live-проверка владельцем.
