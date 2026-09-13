# Spec F3 — `persona-ui-tab-round1014` (UI: подраздел «Личность» в разделе «ИИ»)

> **Статус: ✅ COMPLETED** (Step 2 @Architect, **итерация 2**, 13.09.2026).
> **Раунд:** 10.14. **T-ID:** T-1498…T-1504. **ТЗ:** `plans/current_task.md` §3 + UPD п.2.
> **Зависимости:** **F2** (`GET/PUT/DELETE /api/persona`). **Baseline:** HEAD `2edc65b`.
> **ADR:** `persona-storage-core-round1014/adr-1014-1-persona-storage.md`.
> **Ревизия:** storage — PG (не каталог), поэтому «Личность» — **special-tab** (как «Справка»), без Δ `TAB_RULES`.

---

## §0. Решения Architect (кратко)

| Вопрос | Решение |
|---|---|
| **F3-Q1** вкладка vs секция | **Отдельный special-screen** `activeTab==='persona'` (маршрут `#/ai/persona`), **НЕ** config-вкладка `TABS`/`TAB_RULES`. Причина: поля персоны — PG-API, не каталог; иначе ломается инвариант «TABS — зеркало TAB_RULES». Аналог special-экрана `info`. |
| **Каталог-Δ** | **+0** (никаких `content.persona_*`, `TAB_RULES`/`CONFIG_TAB_TITLES` = 19 без изменений). |
| **F3-Q2** пустое значение | Показываем **пустые поля + плейсхолдер**, не дефолты; API отдаёт `values`/`is_global`/`scope`. |
| **F3-Q3** `is_aware_ai` | Двухсостояние bool (наследование = отсутствие строки чата). Чекбокс отражает значение своего скоупа. |
| **F3-Q4** сброс | Кнопка «Сбросить к глобальному» (chat-scope) → `PUT {reset:true}`. |
| Форма | Кастомная (3 текстовых поля + чекбокс), пишет `PUT /api/persona`. Никакой визуализации (traits — F4). |
| Флаги | `flags.persona_enabled` **ON**; вкладка видима; OFF → бейдж «выключено» + disabled-контролы. |

---

## §1. Цель и scope

В `#/ai` появляется карточка «Личность» → экран с формой ТОЛЬКО статических параметров (Имя, Биография, Характер,
чекбокс «Осознаёт себя ИИ»). Реактивно зависит от выбранного чата (Global ↔ чат). Никакой визуализации.

**In scope:** карточка в Hub «ИИ»; маршрут `#/ai/persona`; special-screen-форма; scope-реактивность; индикация «не задано»/наследование; сброс override; бейдж выключенного флага.

**Out of scope:** лента черт и метрики (F4); storage/API (F2); гайд (F6); изменения `TABS`/`TAB_RULES`.

---

## §2. Изменения (`file:line` на HEAD `2edc65b`)

### 2.1. Бэк
- `services/param_catalog.py` — **Δ нет** (персона — PG-API). Единственный новый ключ раунда, влияющий на экран — `flags.persona_enabled` (F2).
- `web/api/routes.py` — endpoints уже в F2; F3 только потребляет.

### 2.2. `web/app.js`
| Точка | Изменение |
|---|---|
| `HUBS['#/ai'].cards` `:274-296` | карточка `{icon:'psychology', title:'Личность', subtitle:'Имя, биография, характер, осознание ИИ', route:'#/ai/persona', tab:'persona'}` |
| `ROUTE_TO_TAB` `~:572` | `'#/ai/persona': 'persona'` |
| `ROUTE_PARENT` `~:619` | `'#/ai/persona': '#/ai'` |
| `TAB_TO_ROUTE` | `persona: '#/ai/persona'` |
| `TABS`/`TAB_SECTION_ORDER` | **НЕ добавлять** (special-screen, как `info`/`status`) |
| state `:860+` | `personaDraft`, `personaMeta`, `personaLoading`, `personaBusy` |
| methods (новые) | `loadPersona()`, `savePersona()`, `resetPersona()` — через `this.api('/api/persona')` (авто `X-Chat-Id`) |
| `setTab` `:2607+` | при `id==='persona'` → `loadPersona()` (по образцу `info`) |
| `setActiveChat` `:1621` | сброс `personaDraft={}`/`personaMeta=null` + `loadPersona()` при активном экране (единый scope-сброс, согласовано с F5) |

**Scope-реактивность:** `api()` авто-ставит `X-Chat-Id` (`:1430`); черновик не «переживает» смену скоупа; `scopeEpoch`-гвард (по образцу relations) отбрасывает устаревшие ответы.

### 2.3. `web/index.html`
- Новый `<template v-else-if="activeTab === 'persona'">` (рядом с `activeTab==='info'`):
  - `v-if="personaLoading"` → spinner;
  - 3 поля: Имя (`input`), Биография (`textarea rows=3`), Характер (`textarea rows=4`);
  - чекбокс «Осознаёт себя ИИ»;
  - индикатор scope (`Global` / имя чата) + бейдж «унаследовано»/«переопределено»;
  - бейдж «Фича выключена» при `!personaMeta.persona_enabled` + disabled-контролы;
  - кнопки «Сохранить» (`savePersona`) и «Сбросить к глобальному» (`resetPersona`, chat-scope);
  - тосты успех/ошибка; **никаких** лент/графиков/списков traits.

Иконка `psychology` уже в `ICONS` (`web/app.js:224`).

## §3. API/контракты (из F2 §5)

- `GET /api/persona` → `{scope, chat_id, values{name,biography,system_prompt_overrides,is_aware_ai}, is_global, persona_enabled, dynamic_traits}`.
- `PUT /api/persona` body `{name?, biography?, system_prompt_overrides?, is_aware_ai?, reset?}`; chat-scope — UPSERT строки чата; `reset:true` → `DELETE` override; global — UPSERT global. Ошибки 403/409/422/503.
- `DELETE /api/persona` (chat-scope) — удаление override.

## §4. Конфиг/дефолты

Новых ключей F3 не вводит. Дефолт `flags.persona_enabled = True` (F2).

## §5. Feature flag / progressive delivery

- Экран видим всегда; при `persona_enabled=false` — бейдж + disabled-контролы (админ видит будущий раздел). Серверный гейт записи сохраняется.
- Rollback = `git revert`.

## §6. Тест-план

1. Маркеры UI (`tests/test_webapp_round1014_ui.py`): карточка «Личность» в `HUBS['#/ai']`; 4 контрола; кнопка сброса; отсутствие traits/лент; индикатор scope.
2. Роутинг: `routeToTab('#/ai/persona')=='persona'`, `routeParent('#/ai/persona')=='#/ai'` (JS-юнит).
3. **Инвариант special-tab:** `TABS.length==19` и `TAB_SECTION_ORDER` не изменились; `'persona'` НЕ в `TABS`.
4. Scope-реактивность: смена `activeChatId` → `loadPersona` с `X-Chat-Id`; черновик не затирает чужой scope.
5. Пустое значение ≠ дефолт; индикация «унаследовано»/«переопределено».
6. `node --check web/app.js`, `node tests/js/routing_test.js`, полный pytest 0 failed.

## §7. Критерии приёмки (DoD)

- [ ] В `#/ai` есть рабочая карточка «Личность»; маршрут `#/ai/persona` работает.
- [ ] Форма содержит ровно 3 текстовых поля + чекбокс; визуализаций нет.
- [ ] Смена scope перечитывает/сохраняет значения своего скоупа; не затирает введённое.
- [ ] «Не задано»/наследование явно отображается; кнопка сброса работает.
- [ ] `TABS`/`TAB_RULES` не менялись (Δ=0); сохранение переживает рестарт.
- [ ] Полный `pytest` 0 failed; `node --check` clean; `JS-UNIT-OK`.
