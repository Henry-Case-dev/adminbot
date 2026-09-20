# Spec — providers-fullscreen-advanced-fix-round1024 (F24, раунд 10.24 / UPD6)

> **Фича:** `plans/features/providers-fullscreen-advanced-fix-round1024/` · **Раунд 10.24 (UPD6, боевой UI-баг)** · создано @Architect 20.09.2026 (Step 2).
> **Вход:** `tasks.md` (Step 1 @PM, T-2380…T-2387), `plans/current_task.md` UPD6 (стр. 90–104), разведка @Memory (координаты подтверждены).
> **ADR:** `ADR-1024-24.md` (в т.ч. **AMEND решения 10.10** — `plans/archive/admin-ui-round1010/spec.md:53`).
> **Baseline:** HEAD `00eab85`; pytest 7424/0; APP_VERSION 2.57.0; SQLite v12.
> **Тип:** web-UI багфикс (Vue 3.5.42 in-DOM + интеграция Telegram WebApp). Бэкенд, каталог, БД — не трогаются.

---

## 0. Инварианты (проверять на Step 6/7; нарушать нельзя)

1. **`tma-menu-freeze`** — состав/порядок пунктов и вкладок (`TABS`, `MODULES`, `TAB_RULES`, `TAB_NAV`, `CONFIG_TAB_TITLES`) **не меняется**. Новых вкладок/пунктов меню нет.
2. **Δ каталога = 0** — новых `ParamSpec`/`GroupSpec`/ключей нет.
3. **Δ DDL = 0** — SQLite `v12` не трогать, PostgreSQL не трогать.
4. **R16** — API не меняются вообще (web-слой; `/api/me`, `/api/config`, `/api/status` — байт-в-байт).
5. **R17/R18** — секреты не цитировать/не логировать; никаких токенов/кред в коде, тестах, отчётах, ADR. Изменения — только клиентские.
6. **CSP / zero-build** — никаких новых JS-библиотек/CDN; `tests/js/vue_mount_test.js` остаётся зелёным (нет inline-скриптов, нет внешних ресурсов).
7. **`parse_mode=None`** — web-слой текстовую доставку не касается.
8. **Порядок роутеров `bot.py`** не сдвигается (web-слой его не импортирует); `media/` и `.env` не трогать.
9. **Совместимость по умолчанию** — вне fullscreen и на других вкладках поведение байт-в-байт прежнее (кроме исправленного раскрытия).
10. **Ступень общих файлов** — `web/app.js` + `web/index.html` встраиваются в web-очередь раунда **F3 → F5 → F6 → F11 → F4 → F10** (`+F24`); `web/app.js` также правит **F21** → сериализовать (без одновременного редактирования).

### 0.1 Учёт @Scanner
Разведка проводилась по текущему `HEAD`. Первопричина и координаты в `tasks.md`/`current_task.md` подтверждены чтением кода (см. §2). Учтён конфликт с решением 10.10 (§ AMEND в ADR-1024-24). Новых находок Scanner по фиче нет; при появлении — инкорпорировать на Step 7.

---

## 1. Цель

Устранить живой дефект владельца: в разделе **«Провайдеры»** (вкладка `llm_providers`) аккордеон **«Расширенные системные»** (advanced-настройки) **схлопывается/пропадает при переходе TMA в fullscreen** и не переживает ре-рендер/ремаунт вкладки.

**Формулировка результата:**
- Раскрытие advanced-аккордеона — **реактивное состояние** приложения (не чтение `localStorage` на каждом рендере) и **переживает** вход/выход из fullscreen, ре-рендер и ремаунт.
- Флаг fullscreen у Vue — **производный от фактического состояния TMA** (`Telegram.WebApp.isFullscreen` + события), а не «оптимистичная инверсия»; подписки корректно снимаются при размонтировании.
- Область фикса — **все связанные `details.advanced`** (единый механизм), а не только «Провайдеры» (§5.3).

---

## 2. Что уже есть (координаты подтверждены)

| Что | Где | Примечание |
|---|---|---|
| Вкладка «Провайдеры» | `web/app.js:36-47` (`llm_providers`) | блок «Подключения» — `web/index.html:214-338` |
| Outer advanced-аккордеон «Расширенные системные» (Провайдеры) | `web/index.html:559-562` | `<component :is="activeTab==='llm_providers' ? 'details' : 'div'">`, `:open="...expandOpen(activeTab,'prov-advanced')..."`, `@toggle="...toggleExpand(activeTab,'prov-advanced')"`; контент `:571-916` |
| Inner `details.advanced` (та же болезнь) | `web/index.html:526-527`, `:804-806`, `:1990-1992` (bare `expandOpen(activeTab)`), `:2358-2360` (`expandOpen('chat_lore')`) | class `advanced mt-4` |
| Отдельный lightweight `<details>` | `web/index.html:1040-1062` | **без** class `advanced`, **без** биндинга/персиста — вне скоупа (§5.3) |
| Стейт аккордеона | `expandOpen` `web/app.js:3768-3772`; `toggleExpand` `:3773-3779`; ключ `_expandKey` `:785-787` | **читает/пишет `localStorage` напрямую** — нереактивно |
| «Мёртвое» поле | `data.expand: {}` `web/app.js:831` | сейчас не обновляется и не используется |
| Fullscreen-флаг | `isFullscreen: false` `web/app.js:939` | инициализируется константой, `Telegram.WebApp.isFullscreen` **не читается** |
| `toggleFullscreen` | `web/app.js:3651-3665` | оптимистичная инверсия локального флага; `requestFullscreen`/`exitFullscreen` в try/catch |
| Кнопка `⛶` | `web/index.html:108-110` | `@click="toggleFullscreen()"` |
| Класс режима | `web/index.html:26` | `.app-shell :class="{ 'fullscreen-mode': isFullscreen }"` |
| CSS режима | `web/static/app.css:659-668,686-690` | меняет только height/overflow + safe-area 10.10; **скрытий нет** |
| TMA-подписки | `web/app.js:1650-1651` (`onEvent('ready', …)`) — единственная | подписок на `fullscreenChanged`/`viewportChanged`/`safeAreaChanged` **нет** |
| Жизненный цикл | `created` `web/app.js:1568`; `mounted` `:1581`; `beforeUnmount` `:6856` | образец off-паттерна — `_onVisibility` `:1600-1604,6862-6866` |
| JS-тесты | `tests/js/*.js` (`routing_test.js`, `vue_mount_test.js`, `round1024_budget_toggle_test.js`) | запуск `node tests/js/<name>.js`; pytest-обёртка `tests/test_webapp_js_unit.py` |
| Cache-bust | `__APP_VERSION__` → `config/settings.py:1444` (`APP_VERSION = "2.57.0"`); подстановка `web/app.py:98-121` | `?v=` в `index.html:19,22,3412` |

### 2.1 Root cause (подтверждено)

Два независимых разрыва, которые складываются:

1. **Разрыв «TMA-fullscreen ↔ Vue».** `isFullscreen` инициализируется `false` и меняется только инверсией локального флага (`toggleFullscreen`, `:3651-3665`). При переходе в fullscreen, инициированном **нативной кнопкой Telegram**, Vue-флаг остаётся `false` (подписок на события нет) → `.fullscreen-mode` не применяется/запаздывает, а представление вкладки пересобирается. Источник истины у Vue и TMA рассинхронизирован.
2. **Нереактивный стейт аккордеона.** `:open` вызывает `expandOpen()` (`:3768-3772`), которая читает `localStorage` — Vue **не отслеживает** это как реактивную зависимость. При ремаунте/ре-рендере `<details>` пересоздаётся, а `:open` берёт значение вне реактивной системы → схлопывание. Поле `data.expand` (`:831`), которое должно было быть реактивным стейтом, — мёртвое.

**Следствие:** раскрытие не является частью реактивного состояния приложения и не гарантируется после пересборки DOM.

### 2.2 Важное ограничение (риск R1)

Полный ремаунт WebView при fullscreen **не воспроизводится локально**. Фикс проектируется так, чтобы работать в обоих сценариях:
- **частичный ре-рендер** (реактивное состояние живёт в корневом Vue-приложении) — `advancedOpen`/`provAdvancedOpen` переживают;
- **полная перезагрузка страницы** (если WebView реально перезагружает) — `initExpandState()` в `created()` восстанавливает состояние из `localStorage`.

Обязательна **live-приёмка в TMA** (T-2387). Если после фикса дефект сохраняется — эскалация @Architect (см. §8 R1).

---

## 3. Требуемое поведение

1. Пользователь раскрывает «Расширенные системные» на «Провайдерах».
2. Вход в fullscreen (нативная кнопка Telegram **или** `⛶`) → аккордеон **остаётся раскрытым**.
3. Выход из fullscreen → аккордеон **остаётся раскрытым** (состояние не меняется).
4. Повторный ре-рендер вкладки (переключение вкладки туда-обратно, загрузка конфига) → раскрытие сохраняется.
5. Кнопка `⛶` синхронна фактическому состоянию TMA: если fullscreen включён нативно, `title`/иконка отражают «выйти», и наоборот.
6. Вне Telegram / при старом SDK без методов — приложение **не падает**, поведение не хуже прежнего (аккордеон работает как обычный `<details>`).
7. Раскрытие **не форсируется**: по умолчанию advanced свёрнуты (если пользователь их не открывал) — сохраняется текущая семантика (см. O2 §11).

---

## 4. Контракты

### 4.1 C1 — Реактивный стейт аккордеона

- **Источник рендера:** реактивная карта `expand` (существующее `data.expand`, `web/app.js:831`) — единственный источник истины для `:open`.
- **`localStorage` — персист, не источник рендера.** Чтение `localStorage` в шаблоне/`render` недопустимо.
- **Инициализация** — ровно один раз, в `created()` (до первого рендера), новым методом `initExpandState()`: скан `localStorage` по префиксу `adminbot.expand:`, значения `'1'` → `expand[<key>] = true`. Обёрнуто в `try/catch` (приватный режим/недоступность → стейт пустой, поведение «свёрнуто»).
- **Ключи** (`_expandKey(tabId, scope)` `web/app.js:785-787`) — **без изменений**, обратная совместимость формата `adminbot.expand:<tab>[:<scope>]` сохраняется.
- **Чтение для рендера** — через computed-аксессоры (реактивные значения, без вызова state-функций в шаблоне):
  - `advancedOpen` → `!!this.expand[_expandKey(this.activeTab)]` — для inner-зон (`:526`, `:804`, `:1990`, `:2358`).
  - `chatLoreAdvancedOpen` → `!!this.expand[_expandKey('chat_lore')]` — для `:2358` (explicit-tab зона; эквивалент `advancedOpen` на этой вкладке, но фиксирует исходный ключ).
  - `provAdvancedOpen` → `!!this.expand[_expandKey('llm_providers', 'prov-advanced')]` — для outer-зоны «Провайдеров» (`:559`).
- **Совместимость методов** (используются JS-юнитами): `expandOpen(tabId, scope)` сохраняется, но читает **реактивное** `this.expand` (не `localStorage`); `toggleExpand(tabId, scope, ev)` (§4.2).
- **Мёртвое поле становится живым:** комментарий `web/app.js:831` обновляется (поле — реальный реактивный стейт аккордеонов).

### 4.2 C2 — `toggleExpand` синхронизирует, а не инвертирует

Сигнатура: `toggleExpand(tabId, scope, ev)`.

- Ключ: `k = _expandKey(tabId, scope)`.
- Если доступен `ev && ev.target && typeof ev.target.open === 'boolean'` → **`next = ev.target.open`** (факт DOM).
- Иначе (юнит-тесты/legacy-вызов без события) → `next = !this.expand[k]` (инверсия — прежнее поведение).
- Запись: `this.expand[k] = next` (реактивно) **и** `localStorage.setItem(k, next ? '1' : '')` (персист, формат сохранён).
- Обёрнуто в `try/catch`.

**Почему так (важно):** `@toggle` в `<details>` срабатывает и при **программной** установке `open` из состояния Vue. При общих bare-ключах (несколько `details` на одной вкладке делят `adminbot.expand:<tab>`) инверсия вызвала бы осцилляцию (открыли A → Vue открыл B → `toggle` B инвертировал ключ → закрылись оба). Синхронизация из `ev.target.open` идемпотентна и стабильна.

### 4.3 C3 — Синхронизация fullscreen с TMA

- **Источник истины:** `Telegram.WebApp.isFullscreen` + события TMA. Локальный флаг — производный.
- **Инициализация** (`initFullscreen()`): если `window.Telegram.WebApp` доступен и `typeof isFullscreen === 'boolean'` → `this.isFullscreen = isFullscreen`. Вызов — в `mounted()` и повторно в обработчике `onEvent('ready', …)` (контекст Telegram может появиться позже).
- **Подписки** (`initFullscreen()`, ровно один раз — guard-флаг): `onEvent('fullscreenChanged', handler)` и `onEvent('viewportChanged', handler)`. Оба handler'а вызывают `setFullscreenFromTma()`:
  - `setFullscreenFromTma()`: при наличии `Telegram.WebApp.isFullscreen === boolean` → `this.isFullscreen = isFullscreen`; иначе — no-op (не угадывать).
- **Отписки** (`teardownFullscreen()`, вызывается в `beforeUnmount` `web/app.js:6856`): `offEvent('fullscreenChanged', <тот же fn>)` и `offEvent('viewportChanged', <тот же fn>)`; ссылки обнуляются, guard-флаг сбрасывается. Паттерн — как у `_onVisibility` (`:1600-1604,6862-6866`).
- **`toggleFullscreen()`** — остаётся **user-action** (`requestFullscreen`/`exitFullscreen`, try/catch). Флаг:
  - если `typeof Telegram.WebApp.isFullscreen === 'boolean'` → взять фактическое значение;
  - иначе (старый SDK) → инверсия локального флага (legacy-совместимость).
  - События `fullscreenChanged`/`viewportChanged` — окончательная коррекция.
- **`safeAreaChanged` не подписываем:** safe-area решается CSS-переменными `--tg-*` (10.10, `web/static/app.css:686-690`), JS-состояние не требуется. Вне скоупа.
- **Безопасность вне TG / old SDK:** все обращения к `window.Telegram && Telegram.WebApp` и методам событий — под guard'ами и `try/catch`; отсутствие методов → no-op, без исключений.

### 4.4 C4 — Хук жизненного цикла

- `created()` — добавить `this.initExpandState()`.
- `mounted()` — добавить `self.initFullscreen()` (и в `ready`-обработчике — тоже).
- `beforeUnmount()` — добавить `this.teardownFullscreen()`.

---

## 5. Изменения по файлам

### 5.1 `web/app.js`

1. **Модульный уровень** (рядом с `_onVisibility`): `_fsSubscribed = false`, `_fsOnFullscreen = null`, `_fsOnViewport = null`.
2. **`data`**: `expand` (`:831`) — обновить комментарий (реактивный стейт аккордеонов); остальное без изменений.
3. **`created`** (`:1568`): вызвать `this.initExpandState()`.
4. **`mounted`** (`:1581`): вызвать `self.initFullscreen()`; в `onEvent('ready')` (`:1650-1657`) — `self.initFullscreen()`.
5. **`computed`**: добавить `advancedOpen`, `chatLoreAdvancedOpen`, `provAdvancedOpen` (см. §4.1). Проверить, что не конфликтуют с существующими именами.
6. **`methods`**:
   - `expandOpen(tabId, scope)` — читает реактивное `this.expand` (сигнатура сохранена).
   - `toggleExpand(tabId, scope, ev)` — контракт C2.
   - `initExpandState()` — контракт C1.
   - `initFullscreen()`, `setFullscreenFromTma()`, `teardownFullscreen()` — контракт C3.
   - `toggleFullscreen()` (`:3651-3665`) — контракт C3 (без «угадывания», кроме legacy-фолбэка).
7. **`beforeUnmount`** (`:6856`): вызвать `this.teardownFullscreen()`.
8. **Комментарии-докстроки** над `toggleFullscreen`/`expandOpen`/`toggleExpand` обновить (убрать «события fullscreenChanged не ждём» — теперь ждём; зафиксировать AMEND 10.10).

### 5.2 `web/index.html` (ровно 5 биндинг-сайтов)

| Строки | Было | Стало |
|---|---|---|
| `526-527` | `:open="expandOpen(activeTab)"` / `@toggle="toggleExpand(activeTab)"` | `:open="advancedOpen"` / `@toggle="toggleExpand(activeTab, null, $event)"` |
| `559-562` | `:open="activeTab==='llm_providers' ? expandOpen(activeTab,'prov-advanced') : null"` / `@toggle="activeTab==='llm_providers' && toggleExpand(activeTab,'prov-advanced')"` | `:open="activeTab==='llm_providers' ? provAdvancedOpen : null"` / `@toggle="activeTab==='llm_providers' && toggleExpand(activeTab, 'prov-advanced', $event)"` |
| `804-806` | как `526-527` | `:open="advancedOpen"` / `@toggle="toggleExpand(activeTab, null, $event)"` |
| `1990-1992` | как `526-527` | `:open="advancedOpen"` / `@toggle="toggleExpand(activeTab, null, $event)"` |
| `2358-2360` | `:open="expandOpen('chat_lore')"` / `@toggle="toggleExpand('chat_lore')"` | `:open="chatLoreAdvancedOpen"` / `@toggle="toggleExpand('chat_lore', null, $event)"` |

- `web/index.html:1040-1062` — **не трогать** (нет class `advanced`, нет биндинга/персиста; см. §5.3).
- Структура меню/вкладок, `:is`, `<summary>`, `v-if`/`v-for` — **не меняются**.

### 5.3 Скоуп (решение O3)

**Выбран общий реактивный механизм для всех `details.advanced` с биндингом** (5 сайтов выше). Обоснование: один и тот же дефект (нереактивный `:open`) присутствует во всех зонах; единый фикс дешевле и предотвращает повторный баг на других вкладках. Раздельные ключи (`bare` vs `'prov-advanced'`) **сохраняются** — внешняя зона и inner-группы не конфликтуют.
**Вне скоупа:** `web/index.html:1040-1062` (lightweight `<details>` без `advanced`-класса и без персиста) — оставлен как есть, кандидат follow-up (не менять поведение).

### 5.4 Cache-bust / версия (риск R5)

- Поднять `APP_VERSION` (`config/settings.py:1444`) и синхронно шапку `README` (прецедент 10.10 / `tests/test_webapp_round108_ui.py:224`) — иначе TMA может отдать закэшированный `app.js`.
- Значение версии **согласовать с web-очередью** (одно на раунд; не ниже baseline+1). Механизм подстановки `?v=__APP_VERSION__` (`index.html:3412`) уже есть — новый код не нужен.

---

## 6. Тесты

### 6.1 Обновить существующие пины (ОБЯЗАТЕЛЬНО, атомарный коммит)

Старые пины жёстко зашивают вызов `expandOpen(...)` в шаблоне — после §5.2 их нужно привести к новому контракту (иначе ложные падения):

- `tests/test_webapp_round1011_ui.py`:
  - `:210` — `"expandOpen(activeTab, 'prov-advanced')"` → `"provAdvancedOpen"` (в HTML).
  - `:211` — `"toggleExpand(activeTab, 'prov-advanced')"` → `"toggleExpand(activeTab, 'prov-advanced', $event)"`.
  - `:214` — `"toggleExpand: function (tabId, scope)"` → `"toggleExpand: function (tabId, scope, ev)"`.
  - `:217` — `':open="expandOpen(activeTab)"'` → `':open="advancedOpen"'`.
  - **Оставить** `:213` (`"expandOpen: function (tabId, scope)"`) и `:215` (`"function _expandKey(tabId, scope)"`).
- `tests/test_webapp_nav_disclosure_ui.py`:
  - `:139` и `:246` — `"expandOpen(activeTab)"` → `advancedOpen`.
  - **Оставить** `:105-106` (`expandOpen`/`toggleExpand` в `js`) и `:99` (`<details class="advanced`).
- `tests/test_ui_verbilizer_tabs_round1023.py`:
  - `:399` — `"expandOpen(activeTab)" in self.HTML` → `"advancedOpen" in self.HTML`.
- `tests/js/routing_test.js`:
  - `:1331-1332` — ctx дополнить `expand: {}` (методы читают/пишут `this.expand`); сценарии раздельных ключей (`:1319-1360`) сохранить.

> **Правило:** эти пины — не «удалить тест», а **перевести на новый контракт**; смысл проверок (раздельные ключи, базовое раскрытие) сохраняется.

### 6.2 Новый JS-юнит — `tests/js/round1024_providers_fullscreen_test.js` (маркер `PROVIDERS-FS-OK`)

Загрузка `web/app.js` в stubbed-окружении (по образцу `routing_test.js`/`round1024_budget_toggle_test.js`: `Vue.createApp` перехватывает opts). Проверки:

1. **Реактивность `:open` (без чтения localStorage в рендере):**
   - исходник `methods.expandOpen` **не содержит** `localStorage.getItem`;
   - `ctx = { expand: {} }`; `toggleExpand(ctx, 'llm_providers', 'prov-advanced')` → `ctx.expand['adminbot.expand:llm_providers:prov-advanced'] === true` **и** `localStorage` `=== '1'`;
   - `expandOpen(ctx, 'llm_providers', 'prov-advanced') === true`.
2. **Переживание ремаунта:** новый чистый ctx, поверх того же `localStorage`, вызвать `initExpandState()` → `expandOpen` снова `true` (модель полной перезагрузки WebView).
3. **`initExpandState`:** мок `localStorage` с `length`/`key(i)` (ключ `adminbot.expand:*`, значение `'1'`) → соответствующая запись `expand` истинна; значение `''` игнорируется.
4. **Синхронизация из события (C2):** `toggleExpand(ctx, tab, scope, { target: { open: true } })` → true, повторно `{ target: { open: true } }` → остаётся true (идемпотентность); `{ target: { open: false } }` → false.
5. **Fullscreen init/события/отписка (C3):** мок `window.Telegram.WebApp = { isFullscreen: true, onEvent(n, cb){…}, offEvent(n, cb){…} }`:
   - `initFullscreen()` → `isFullscreen === true`, `onEvent` вызван для `'fullscreenChanged'` и `'viewportChanged'`;
   - после смены `WebApp.isFullscreen = false` вызов пойманного `fullscreenChanged`-cb → `isFullscreen === false`; `viewportChanged` аналогично;
   - `teardownFullscreen()` → `offEvent` вызван для обоих событий с **теми же** fn-ссылками; повторный вызов не бросает.
6. **Безопасность вне TG:** `window.Telegram = null` → `initFullscreen()`/`teardownFullscreen()`/`toggleFullscreen()` не бросают; SDK без `onEvent`/`offEvent` → no-op.
7. **Раздельные scope-ключи:** `_expandKey('llm_providers') !== _expandKey('llm_providers','prov-advanced')` (регресс 10.11).

**pytest-обёртка:** добавить `test_js_unit_round1024_providers_fullscreen` в `tests/test_webapp_js_unit.py` (через `_run_js("tests/js/round1024_providers_fullscreen_test.js", "PROVIDERS-FS-OK")`).

### 6.3 Новый статический pytest — `tests/test_webapp_round1024_providers.py`

- В `web/index.html` для 5 зон: нет `expandOpen(` в `:open`; есть `advancedOpen`/`provAdvancedOpen`/`chatLoreAdvancedOpen`; `@toggle` использует `toggleExpand(` с `$event`.
- В `web/app.js`: есть `initExpandState`, `initFullscreen`, `setFullscreenFromTma`, `teardownFullscreen`; есть строки `'fullscreenChanged'`, `'viewportChanged'`, `offEvent`; `this.expand[` присутствует; `expandOpen` не содержит `localStorage.getItem`.
- `web/index.html:26` сохраняет `:class="{ 'fullscreen-mode': isFullscreen }"`.
- **Freeze:** число вкладок/пунктов меню не изменилось (атомарные пины раунда; не ослаблять).
- `node --check web/app.js` (в существующем прогоне) — OK.
- Сохранить зелёными: `tests/js/routing_test.js`, `tests/js/vue_mount_test.js` (CSP), `tests/test_webapp_round1010_ui.py` (fullscreen CSS/scroll), `tests/test_webapp_tma_fixes_ui.py`.

### 6.4 Live-приёмка (T-2387, @QA/@DevOps — обязательна)

Android (+ iOS при возможности): раскрыть advanced на «Провайдерах» → вход в fullscreen **нативной кнопкой Telegram** и через `⛶` → раскрытие сохраняется в fullscreen и при выходе; переключение вкладки туда-обратно сохраняет раскрытие; `⛶` синхронен фактическому режиму. Доказательство — скриншот/видео.

---

## 7. Риски

| # | Риск | Ур. | Митигация |
|---|---|---|---|
| R1 | Ремаунт/перезагрузка WebView при fullscreen не воспроизводима локально; фикс может не закрыть дефект | **High** | Дизайн покрывает оба сценария (реактивный стейт + `initExpandState` из localStorage); **обязательная live-приёмка** (T-2387); при сохранении дефекта — эскалация @Architect |
| R2 | Двойные подписки на TMA-события / утечка | Medium | Guard `_fsSubscribed`; `offEvent` с теми же fn-ссылками в `teardownFullscreen`; `try/catch` |
| R3 | Общий фикс задевает чужие вкладки; осцилляция при общих bare-ключах | Medium | C2 (синхронизация из `ev.target.open`, не инверсия); раздельные ключи сохранены; регресс-тесты (§6.2 п.7, §6.3) |
| R4 | `Telegram.WebApp`/события недоступны (браузер, старый SDK) | Low | Guard'ы + `try/catch` + legacy-фолбэк; поведение не хуже прежнего |
| R5 | Кэш статики отдаёт старый `app.js`/`index.html` | Low | `APP_VERSION`/`?v=` cache-bust синхронно (§5.4) |
| R6 | Ложные падения/«удалённые» пины | Medium | Явный список обновляемых пинов (§6.1); смысл проверок сохранён; @Scanner не считать правку пинов находкой |
| R7 | Программное открытие `<details>` кидает `toggle` | Medium | C2 + юнит на идемпотентность (§6.2 п.4) |
| R8 | Рассинхрон версии с web-очередью раунда | Low | Согласовать `APP_VERSION` (§5.4) |

---

## 8. Критерии приёмки

1. В «Провайдерах» раскрытие «Расширенных системных» переживает вход в fullscreen, пребывание в нём и выход (live TMA, доказательство).
2. `isFullscreen` инициализируется из `Telegram.WebApp.isFullscreen` и обновляется событиями `fullscreenChanged`/`viewportChanged`; подписки снимаются в `beforeUnmount`.
3. `:open` завязан на реактивные значения (`advancedOpen`/`provAdvancedOpen`/`chatLoreAdvancedOpen`); `localStorage` — только персист; повторный рендер/ремаунт не схлопывает аккордеон.
4. Нет регресса вне fullscreen и на других вкладках; раздельные `scope`-ключи не конфликтуют.
5. Инварианты §0 соблюдены: `tma-menu-freeze`, Δ DDL=0, Δ каталога=0, R16/R17/R18, CSP (нет новых библиотек), `parse_mode=None`.
6. Полный pytest — 0 failed; `node --check web/app.js` — OK; JS-тесты печатают `PROVIDERS-FS-OK`/`JS-UNIT-OK`; `git diff --check` чист.

---

## 9. Флаг / раскатка / откат

- **Feature flag: НЕ требуется** (чисто клиентский UI-фикс; продуктовый тумблер только вернул бы баг). Новых env-флагов и `ui_flags` не вводим — согласовано с решением F24 (`tasks.md`, `current_task.md` UPD6).
- **Раскатка:** обычная (атомарный код-коммит + cache-bust). Progressive delivery не требуется.
- **Откат (kill-switch):** `git revert` коммита F24 + синхронный откат `APP_VERSION`/`?v=` (cache-bust). Иных runtime-гейтов нет.
- Если владелец всё же захочет рубильник — использовать существующий enabler ADR-1024-13 (`ui_flags` из `/api/me`, default ON). @Architect **не рекомендует** (лишняя серверная поверхность для багфикса).

---

## 10. Маппинг задач

| Задача | Что |
|---|---|
| T-2380 | §1–§5 + ADR-1024-24 (этот файл) |
| T-2381 | §4.3/§5.1 п.4,7,8 — fullscreen-sync + `initFullscreen`/`setFullscreenFromTma`/`teardownFullscreen` + `toggleFullscreen` |
| T-2382 | §4.1/§4.2/§5.1 п.2,3,5,6 + §5.2 — реактивный аккордеон + `initExpandState` + биндинги |
| T-2383 | §5.3 — общий скоуп всех `details.advanced` (5 сайтов); `:1040` вне скоупа |
| T-2384 | §6.2 — `tests/js/round1024_providers_fullscreen_test.js` + обёртка |
| T-2385 | §6.1 (обновление пинов) + §6.3 (статический pytest) + §5.4 (cache-bust) |
| T-2386 | @Reviewer — §6.4/§8; проверка AMEND 10.10 |
| T-2387 | @DevOps/@QA — live-приёмка TMA (§6.4) + деплой |

---

## 11. Открытые вопросы к владельцу (Human Gate O) — с дефолтами @Architect

1. **O1 — платформа/канал.** *Дефолт:* фикс платформо-независим, live-приёмка на Android (+iOS при возможности); чиним и вход, и выход, и нативную кнопку, и `⛶`.
2. **O2 — раскрывать по умолчанию?** *Дефолт:* **нет**, сохраняем текущую семантику персиста (свёрнуто, если не открывали). Форсированное раскрытие не вводим.
3. **O3 — скоуп.** *Дефолт:* **общий** реактивный механизм для всех `details.advanced` с биндингом (5 сайтов); `:1040` вне скоупа.
4. **O4 — AMEND 10.10.** *Дефолт:* **применяем AMEND** (ADR-1024-24), т.к. живой дефект доказывает недостаточность решения 10.10. Требуется санкция владельца до реализации; проектирование выполнено на безопасном дефолте.

---

## 12. Handoff

`@Orchestrator Architecture phase complete, passing the baton.`
Вызовы: **@Builder** (T-2381/T-2382/T-2383/T-2384/T-2385 — по ступени `web/app.js`+`web/index.html`, после F10 и сериализации с F21), **@Reviewer** (T-2386), **@QA/@DevOps** (T-2387, live TMA).
