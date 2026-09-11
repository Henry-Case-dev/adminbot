# spec.md — admin-ui-round108 (Раунд 10.8)

> **FEATURE:** `plans/features/admin-ui-round108/`
> **РАУНД:** 10.8 (UI-полировка после задеплоенного 10.7, commit `7f3b790`, прод fast-forward, health 200).
> **Автор спеки:** @Architect (Step 2). **Только диагноз и точный фикс-план — НЕ реализация.**
> **Вход:** `tasks.md` (рекогносцировка @PM, file:line), `web/index.html`, `web/app.js`,
> `scripts/build_font_subset.py`, `tests/*`, `plans/reports/round10.7_scanner_audit.md`.
> **Baseline:** pytest **5042 passed / 0 failed 1 warning**; `node --check web/app.js` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог **REGISTRY 392 / GROUPS 91 / Settings 364**
> (mapped 89); SQLite v8; ноль PG-DDL; `bot.py`/`media/` не тронуты.
> **Связанные ADR:** `ADR-001-access-windows-modal.md`, `ADR-002-icon-subset-parity.md`.

---

## 0. Учёт аудита @Scanner (ОБЯЗАТЕЛЬНО — проверено перед проектированием)

Прочитан новейший отчёт `plans/reports/round10.7_scanner_audit.md` (11.09.2026), а также
`audit_backlog.md`, `global_map.md`, `full_audit_results.md`, `round10.6_scanner_audit.md`.

| Находка | Severity | Применимость к 10.8 | Решение |
|---|---|---|---|
| **R10.7-3** `copiedTimer` не очищается при смене вкладки (`app.js:741-742,3344-3352`) | info | В UI-скоупе, дёшево | **ВКЛЮЧАЕМ** (§3.5) |
| **R10.7-4** `test_font_subset` проверяет JS, а не cmap субсета (`tests/test_font_subset.py:73`) | info | В UI-скоупе, критично для п.2 | **ВКЛЮЧАЕМ** (§2.4) |
| **R10.7-1** gap-fill помечает незавершённый слот `down` (`services/status_service.py`) | minor | Вне UI-скоупа | Кандидат 10.9 (T-1250) |
| **R10.7-2** `[-288:]` может отбросить ранний `up` (`services/status_service.py`) | info | Вне UI-скоупа | Кандидат 10.9 |
| **R10.7-5** неточная формулировка причины `copyAllLogs` | info | Не код | Учтено, не дублируем |
| **R10.6-1** дубль generic-рендера `llm_providers` (21 дубль) | minor | Опционально P2 | T-1250 (только если не раздувает риск) |
| **R10.6-2** SSRF `https` / **R10.6-3** 422-эхо `api_key` | security | Вне UI | Не брать в 10.8 |
| **R106-5** мёртвые `ICONS` | info | **Закрыто в 10.7** | Не регрессировать |

**Scanner-инварианты, которые держит 10.8:** каталог 392/91/364; SQLite v8; ноль PG-DDL;
`bot.py`/`media/` нетронуты; секретов нет; `fontTools` — build-time only.

---

## 1. Пункт 1 — Переименование разделов (T-1243/T-1244/T-1245/T-1246)

### 1.1 Канонический словарь (единственный источник истины по подписям)

| Ключ маршрута (НЕ менять) | Было | **Стало** | Где |
|---|---|---|---|
| `#/how` | Как это работает | **Справка** | `NAV_ITEMS`, `TABS.info.label`, `index.html` header |
| `#/ai` | Настройки AI | **ИИ** | `NAV_ITEMS`, `HUBS['#/ai'].title` |
| `#/permsoc` | Функции PERMsoc | **PERMsoc** | `NAV_ITEMS`, `TABS.permsoc.label`, `index.html` header |
| `#/access` | Доступы и Роли | **Доступы** | `NAV_ITEMS`, `TABS.access.label`, `HUBS['#/access'].title`, aria-label |
| `#/oversight` | Oversight | **Сводка** | `TABS.oversight.label`, `index.html` header + hub-card |
| `#/` | Статус | Статус (без изменений) | — |
| `#/modules` | Модули | Модули (без изменений) | — |

> **Route-ключи `how/ai/permsoc/access/oversight` и `activeNav`/`routeToTab` НЕ менять.**
> Идентификаторы JS (`loadOversight`, `oversightData`, `#/oversight`) остаются — меняются
> только видимые подписи.

### 1.2 Точный фикс (file:line)

**`web/app.js`**
- `:43` `TABS.prompts.icon` `'🧠'` → `'description'` (см. §2; это icon-поле, не label).
- `:156` `TABS.permsoc.label` `'Функции PERMsoc'` → `'PERMsoc'`.
- `:171` `TABS.access.label` `'Доступы и Роли'` → `'Доступы'`.
- `:184` `TABS.status.icon` `'📊'` → `'monitoring'` (см. §2).
- `:186` `TABS.info.label` `'Как это работает'` → `'Справка'`.
- `:189` `TABS.oversight.label` `'Oversight'` → `'Сводка'`; `icon: '🛰️'` → `'radar'` (см. §2).
- `:248` `NAV_ITEMS[1].label` `'Как это работает'` → `'Справка'`.
- `:250` `NAV_ITEMS[3].label` `'Настройки AI'` → `'ИИ'`.
- `:251` `NAV_ITEMS[4].label` `'Функции PERMsoc'` → `'PERMsoc'`.
- `:253` `NAV_ITEMS[5].label` `'Доступы и Роли'` → `'Доступы'`.
- `:262` `HUBS['#/ai'].title` `'Настройки AI'` → `'ИИ'`.
- `:289` `HUBS['#/access'].title` `'Доступы и Роли'` → `'Доступы'`; `:290` subtitle → `'Матрица ролей, локальные админы, роли'`.
- `:298` `HUBS['#/access'].cards[2].title` `'Администраторы'` → `'Роли'` (см. §4).
- Комментарии с устаревшими подписями — почистить для grep-гейта: `:4` (`«Как это работает»` → `«Справка»`), `:602`, `:1645` (`«Функции PERMsoc»` → `«PERMsoc»`), `:1884`, `:3404`.

**`web/index.html`**
- `:809` `<div ...>🎭 Функции PERMsoc</div>` → Material-иконка `admin_panel_settings` + текст `PERMsoc` (см. §2).
- `:1489` `🛰️ Global Oversight` → Material-иконка `radar` + текст `Сводка`.
- `:2413` `<span class="hub-card-title block">Oversight</span>` → `Сводка`.
- `:2593` комментарий `"Как это работает"` → `"Справка"`.
- `:2596` header `<... iconGlyph('help') ...> Как это работает` → `Справка`.
- `:801` комментарий `вкладки «Функции PERMsoc»` → `«PERMsoc»`.
- `:1583` `aria-label="Доступы и роли"` — при реструктуризации §4 либо удаляется, либо → `aria-label="Доступы"`.

**`README.md`** — таблица разделов `:451-456`, narrative `:362`, `:378`, `:382`, `:385` → новые подписи (см. §6).

### 1.3 ЯВНОЕ исключение (НЕ переименовывать)

- **Каталог-группа** `by_id["flags_permsoc"].title_ru == "Функции PERMsoc: рубильники"`
  (`services/param_catalog.py`; пинится `tests/test_param_catalog.py:346,382`) — это заголовок
  **параметра**, не пункт меню. **НЕ трогать.**
- «Администраторы чата» (`index.html:2279`, `chat_lore`) — **НЕ переименовывать** (пинится
  `tests/test_webapp_lore_ui.py:201`). Переименовывается только подраздел «Доступов» (§4).
- Идентификаторы/методы `loadOversight`, `oversight*`, route `#/oversight` — не трогать.
- Спецсимволы ✕/⛶/▸/▾/↪/⟳/↻/←/→/↔ и disclosure-шевроны `▶` в `<summary>` — не трогать (§2).

### 1.4 AC-1 и тесты

**AC-1:** в навбаре/хабах/заголовках ровно `Статус, Справка, Модули, ИИ, PERMsoc, Доступы`
(+ `Сводка` как заголовок Oversight-экрана); старые лейблы отсутствуют в `web/`; hash-ключи
и deep-link не изменены.

**Обновить тесты:**
- `tests/test_webapp_parity_smoke.py:19-26` — `REFERENCE_SECTIONS` на новые 6 пар; `:151` `"Oversight" in _HTML` → `"Сводка" in _HTML` + `"'#/oversight'" in _JS`.
- `tests/test_webapp_hubs_matrix_ui.py:14-15` — новые лейблы; `:25` `openHubCard(c)` остаётся.
- `tests/test_frontend_tab_mapping.py:210-211` — уже проверяет отсутствие `ℹ️`/`🔐`; добавить отсутствие старых лейблов (см. §9 grep-гейт).
- `tests/test_round106_ia_smoke.py:123-124` — оставить (проверяют отсутствие emoji-строк).
- **Добавить** `test_round108_renames` (в новом `tests/test_webapp_round108_ui.py`): старые лейблы
  не встречаются в `web/app.js`/`web/index.html`; новые присутствуют; `"Функции PERMsoc: рубильники"`
  в каталоге не изменён.

---

## 2. Пункт 2 — Emoji в блоках/подсекциях → Material-иконки (T-1247/T-1248/T-1249)

### 2.1 Механизм

Рендер: `<span class="msr" aria-hidden="true">{{ iconGlyph('имя') }}</span>`.
`ICONS` (`web/app.js:207-228`) — PUA-карта; `TAB_ICON` (`:230-242`) — tab.id → имя.
Субсет собирается оффлайн `scripts/build_font_subset.py` из исходника 5.11 МиБ (gitignored);
в git — только `web/static/fonts/material-symbols-rounded.woff2` + LICENSE.

### 2.2 Точная таблица замен (file:line → Material-имя)

**Существующие имена (уже в `ICONS`, пересборка для них не нужна):**

| file:line | Emoji | Что это | Material-имя |
|---|---|---|---|
| `index.html:809` | 🎭 | Заголовок вкладки PERMsoc | `admin_panel_settings` |
| `index.html:1173` | 📊 | «Бюджет фона» | `monitoring` |
| `index.html:1380` | 🧠 | «Синтез (сон)» | `bedtime` |
| `index.html:1452` | 🌟 | «Ностальгия» | `history` |
| `index.html:1489` | 🛰️ | «Global Oversight» → «Сводка» | `radar` |
| `index.html:1828/1840/1853` | 👥 | «Участники и отношения» | `group` |
| `index.html:2036` (comment) | 📜 | «Лор чатов» | `auto_stories` |
| `index.html:2166` | 🤖 | «Авто-лор» | `smart_toy` |
| `index.html:2279` | 👑 | «Администраторы чата» | `admin_panel_settings` |
| `index.html:2424` | 🤖 | «Бот» | `smart_toy` |
| `index.html:2434` | 🔄 | кнопка «Рестарт» | `restart_alt` |
| `index.html:2478` | 🧠 | карточка провайдера | `smart_toy` |
| `index.html:2699` | 📜 | «История изменений» | `history` |
| `app.js:43` | 🧠 | `TABS.prompts.icon` | `description` |
| `app.js:184` | 📊 | `TABS.status.icon` | `monitoring` |
| `app.js:189` | 🛰️ | `TABS.oversight.icon` | `radar` |
| `index.html:1143` (comment) | 🧩 | «Модули» | `extension` |
| `index.html:1578` (comment) | 👥 | «Управление доступом» | `group` |
| `index.html:2404` (comment) | 📊 | «Статус» | `monitoring` |

**НОВЫЕ имена (добавить в `ICONS` + `ICON_NAMES`, пересобрать субсет):**

| file:line | Emoji | Что это | Material-имя |
|---|---|---|---|
| `index.html:975` | 👁 / 🙈 | reveal/скрыть ключ | `visibility` / `visibility_off` |
| `index.html:1209,1220` | 🧠 | «Тяжёлые фичи» | `psychology` |
| `index.html:1416` | 🛡 | «защитить» | `shield` |
| `index.html:1420,2930` | 🗑 | удалить | `delete` |
| `index.html:1802,1949,2198,2320,2313(c)` | ⚙/⚙️ | настройки/шестерёнка | `settings` |
| `index.html:1935` | 💾 | сохранить | `save` |
| `index.html:2146` | 📝 | «Ручной лор» | `edit_note` |
| `index.html:2258` | 🚚 | «Переезд чата» | `swap_horiz` |
| `index.html:2438` | ⏹ | кнопка «Стоп» | `stop` |
| `index.html:2442` | ▶ | кнопка «Старт» | `play_arrow` |
| `index.html:2450` | 🖥 | «Сервер» | `dns` |
| `index.html:2498` | 📈 | «Аптайм» | `trending_up` |
| `index.html:2509` | 🔑 | «Доступность ключей API» | `key` |
| `index.html:2548` | 📜 | «Логи» | `receipt_long` |

> Итого **17 новых** Material-имён. Дефолтный `TAB_ICON` дополнить при необходимости
> (например, `prompts` уже `description`; `status`/`oversight` уже заданы).

### 2.3 ЯВНО «НЕ ТРОГАТЬ»

`✕` (закрыть), `⛶` (fullscreen), `▸`/`▾` (log-toggle/scope trigger), `↪` (reset override),
`⟳`/`↻`, `←`/`→`/`↔`, стрелки в JS-комментариях, **и disclosure-шевроны `▶` в `<summary>`
«Расширенные настройки»** (`index.html:1026,1994,2362`) — это UI-глифы, не emoji.
Заменяется только `▶` **кнопки «Старт»** (`:2442`) → `play_arrow`.
Также **не трогать** `scope trigger ▾` (`:642`).
Комментарии с pictographic-emoji (1143/1486/1578/1828/2036/2404) — вычистить emoji
(заменить на текстовое имя), чтобы единый grep-гейт §9 был чистым.

### 2.4 Пересборка субсета — ОБЯЗАТЕЛЬНЫЙ шаг (T-1249)

**Проблема идемпотентности (важно):** `scripts/build_font_subset.py:132-137` считает субсет
актуальным по маркеру `build/font_source.sha256` (только sha исходника). Правка `ICON_NAMES`
**не** меняет sha исходника → скрипт скажет «up-to-date» и **не пересоберёт** → новые иконки
дадут tofu. **Требуемый фикс скрипта:** маркер должен учитывать и список иконок, например
ключ `sha256(source_sha + '|' + ','.join(ICON_NAMES))`. (Реализует @Builder.)

**Порядок:**
1. `ICON_NAMES` (`build_font_subset.py:46-53`) → ровно множество ключей `ICONS` ∪ новые 17.
   Удалить 6 мёртвых, оставшихся с 10.7: `account_balance_wallet`, `speed`, `stop_circle`,
   `theater_comedy`, `toggle_off`, `toggle_on`. Итог: **20 + 17 = 37** имён.
2. Скрипт: вместе с `build/subset_unicodes.txt` писать `build/icon_codepoints.json`
   (`{name: "U+XXXX"}`, сортировка по имени) — артефакт для сверки `ICONS`. `build/` gitignored.
3. Маркер идемпотентности — с учётом `ICON_NAMES` (см. выше).
4. Запуск: `.venv\Scripts\python.exe scripts/build_font_subset.py` (исходник 5.11 МиБ на месте,
   gitignored; `fontTools`+`brotli` из `scripts/requirements-font.txt`).
5. Перенести PUA-коды новых 17 имён в `ICONS` (`web/app.js:207-228`) из
   `build/icon_codepoints.json` — **1:1**, без «на глаз».
6. Проверить: размер субсета `< 60_000` B (`test_subset_shipped_small`); `wOF2`-магия.
7. **Не коммитить** исходник 5.11 МиБ (gitignore проверяется тестом).

### 2.5 Усиление теста субсета (R10.7-4) — `tests/test_font_subset.py`

- **Парсер `ICONS`:** regex по блоку `var ICONS = {` в `web/app.js` → `{name: codepoint}`.
- **Парсер `ICON_NAMES`:** regex по кортежу в `scripts/build_font_subset.py`.
- **Тест A (без fontTools, жёсткий):** множество `ICONS` == множество `ICON_NAMES`
  (нет drift, нет мёртвых, нет пропущенных). Заменить слабую проверку `assert "'\\ue887'" in js`.
- **Тест B (cmap, R10.7-4):** `fontTools.ttLib.TTFont(SUBSET).getBestCmap()`; каждый PUA-код
  из `ICONS` присутствует в cmap. Обернуть `pytest.importorskip("fontTools")` (build-time dep,
  в runtime `requirements.txt` не входит), но в DoD 10.8 — тест обязан **выполняться** (не skip)
  на dev-машине, где `fontTools` установлен (`scripts/requirements-font.txt`).
- **Тест C:** в `web/index.html`/`web/app.js` отсутствуют pictographic-emoji из §2.2
  (список кодов; disclosure `▶`/спецсимволы исключены явно).
- **Тест D:** `ICON_NAMES` не содержит 6 мёртвых имён 10.7.

**AC-2:** нет pictographic-emoji в перечисленных местах; каждый PUA-код `ICONS` есть в cmap
пересобранного субсета; размер `< 60 КБ`; спецсимволы §2.3 не заменены; визуально нет tofu.

**Тесты, завязанные на emoji (обновить):**
- `tests/test_webapp_nav_disclosure_ui.py:238` `html.index("⚙️ Настройки отношений")` →
  найти по `id`/тексту без emoji (`"Настройки отношений"` + `iconGlyph('settings')`).
- `tests/test_round106_ia_smoke.py:122-128` — оставить/дополнить новыми именами.

---

## 3. Пункт 3 — Регрессия ЛОГОВ на Android (ГЛАВНЫЙ ПРИОРИТЕТ) (T-1251/T-1252/T-1253/T-1254)

### 3.1 Root causes — доказательства

**(a) «Невидимое selection-поле в первой колонке».**
`web/index.html:2574-2577` — `<button class="log-toggle">` с текстовым глифом `▸`/`▾`
(U+25B8 `BLACK RIGHT-POINTING SMALL TRIANGLE` / U+25BE). Эти кодпоинты **не входят** в субсет
Material (`web/static/fonts/material-symbols-rounded.woff2`) и часто отсутствуют в системном
шрифте Telegram WebView на Android → кнопка рендерится пустой/нулевой ширины, но остаётся
`<button>` в первом столбце → визуально «пустое поле». 10.7 искал скрытый `<input>`/`<div>` и
не нашёл (их нет — это button). CSS `.log-toggle` (`index.html:407-417`) без фона/рамки делает
её неотличимой от пустого поля.

**(b) «Дата исчезла».**
`web/app.js:3285-3291` `fmtLogTime` возвращает только `HH:MM:SS`; полная дата — лишь в
`:title="fmtLogTs(log.ts)"` (`index.html:2581`). На тач-устройстве `title` недоступен (нет hover)
→ дата не видна вообще. Это регрессия 10.7 (`tasks.md` 10.7 §3b: «compact HH:MM:SS, title — полный»).

**(c) «Текст ошибки в один символ» + сломанная ширина.**
Строка лога — inline `<span class="log-row">` (`index.html:2569`) внутри `<pre class="log-code break-all"><code>`
(`:2568`) с `white-space: pre-wrap` (`:430`). Вложенный `<span class="flex items-start gap-2">`
(`:2573`) — flex внутри `pre`; на старом Chromium/Android WebView контейнерный блок схлопывается.
Плюс жёсткий бюджет колонок: `.log-level min-width:4.5rem` (`:436`) + `.log-ts width:8ch` (`:439`)
+ `.log-logger max-width:8rem` (`:443`) ≈ 264px на 360px-экране, `.log-msg` объявлен `flex-1 min-w-0`
(`:2583`, `:446-448`) → на сообщение остаётся ~1 символ. `.log-code { word-break: break-all }`
усугубляет перенос по символу.

**(d) R10.7-3:** `copiedTimer` (`app.js:741-742`) очищается только при следующем клике
(`:3346`); при уходе с `status` в течение 800 мс `setTimeout` всё равно срабатывает.

**Что НЕ причина (подтверждено):** ghost-textarea копирования (`app.js:3309-3342`) —
`position:fixed; left:-9999px; opacity:0; contain:strict`, удаляется в `finally`; на раскладку
не влияет. Контракт `/api/logs` не меняется.

### 3.2 Точный фикс — шаблон (`web/index.html:2565-2588`)

Заменить `<pre class="log-code break-all"><code>` + inline-`<span class="log-row">` на
**блочную структуру**: контейнер `<div class="log-code">`, строка `<div class="log-row">`,
шапка `<div class="log-head">` (toggle + level + ts + logger) и отдельный `<div class="log-msg">`
**на всю ширину** (стек — гарантирует реальную ширину и перенос), затем `log-exc`.

Ключевые требования к разметке:
- `.log-toggle` рендерится **только при `log.exc_text`**; иначе — неинтерактивный
  `<span class="log-toggle-spacer" aria-hidden="true">` (та же ширина, ноль фокуса/полей).
- Глиф toggle — Material-иконка: `chevron_right` (свёрнуто) / `expand_more` (развёрнуто)
  через `iconGlyph(...)`; добавить `:aria-expanded` и `:aria-label`.
- `log-ts` показывает **дату и время** (см. 3.3); `:title` остаётся полным `fmtLogTs`.
- `log-msg` — блочный, `white-space: pre-wrap`, `overflow-wrap: anywhere`, реально тянется
  на ширину карточки.
- `log-exc` — блочный (`display:block`), `white-space: pre-wrap`.
- Сохранить: `@click="copyLogRow(log, i)"`, `:class="{'log-copied': copiedIndex === i}"`,
  `@click.stop` на toggle, `title="Клик — копировать строку"`, `v-if`-ветки loading/empty.

### 3.3 Точный фикс — JS (`web/app.js`)

- `fmtLogTime(ts)` (`:3285-3291`): вернуть компактную **дату+время** `DD.MM HH:MM:SS`
  (напр. `11.09 14:32:07`, `tabular-nums`), fallback для невалидного ts — `String(ts).slice(...)`.
  Полный формат `fmtLogTs` (`:3277-3282`) сохранить для `:title` и `fmtTs`.
- `copyLogRow` (`:3344-3352`) и `logText` (`:3305-3308`) — без изменений контракта.
- `setTab(id)` (`:2172`): в начале добавить очистку подсветки копирования
  (`clearTimeout(this.copiedTimer); this.copiedTimer = null; this.copiedIndex = null;`) — R10.7-3.

### 3.4 Точный фикс — CSS (`web/index.html:400-463`, media `:302`)

- `.log-code`: заменить `white-space: pre-wrap` + `word-break: break-all` на
  `white-space: normal` + `word-break: normal` (Tailwind-класс `break-all` из шаблона убрать).
- `.log-row` → `display:block`; `.log-head` → `display:flex; flex-wrap:wrap; align-items:baseline;`
  `gap:.25rem .5rem; min-width:0`.
- `.log-toggle`: `display:inline-flex; flex:0 0 1.25rem; width/height:1.25rem; padding:0;`
  `background:none; border:0;` иконка 1rem; **не** выглядит полем.
  `.log-toggle-spacer`: `flex:0 0 1.25rem; width:1.25rem`.
- **Удалить** жёсткие `.log-level{min-width:4.5rem}`, `.log-ts{width:8ch}`,
  `.log-logger{max-width:8rem}`. Оставить `.log-ts{white-space:nowrap; tabular-nums}`.
- `.log-msg{display:block; margin-top:2px; word-break:break-word; overflow-wrap:anywhere; white-space:pre-wrap}`.
- `.log-exc{display:block; margin:0}`.
- `@media (max-width:479px) .log-logger{display:none}` — сохранить.

### 3.5 AC-3 и live-верификация (T-1254)

**AC-3:** на реальном Android (Telegram WebView):
(a) ширина строк не выходит за экран; (b) **дата видна** (не только время);
(c) текст ошибки занимает нормальную ширину и переносится; (d) в первой колонке **нет**
невидимого selection-поля; (e) копирование строки / «Копировать всё» / разворот стека работают.
Десктоп не регрессирует.

**Live-проверка обязательна** (эмуляция desktop недостаточна). Если Android недоступен —
эскалация владельцу, задачу **не закрывать**.

**Тесты обновить/добавить:**
- `tests/test_webapp_tma_fixes_ui.py:23-30` (`<pre ... break-all>` → `<div class="log-code">`);
  `:43-49` (`log-toggle` → `iconGlyph` toggle + `log-toggle-spacer`).
- `tests/test_webapp_round107_ui.py:83-90` — убрать `min-width:4.5rem`/`width:8ch`-маркеры,
  добавить новые (`.log-msg` перенос, `.log-code` без break-all).
- **Добавить** в `tests/test_webapp_round108_ui.py`: `fmtLogTime` содержит дату (регэксп
  `\d\d\.\d\d`), нет `break-all`/`pre-wrap` в `.log-code`, toggle использует `iconGlyph`,
  spacer существует, `copiedTimer` очищается в `setTab`.
- JS-юнит (опц., `tests/js/routing_test.js`): `fmtLogTime` возвращает `DD.MM HH:MM:SS`.

---

## 4. Пункт 4 — «Доступы»: три подраздела отдельными ОКНАМИ + переименование (T-1255/T-1256/T-1257/T-1258)

> Решение: **route-driven модальные окна** (паттерн `modal-backdrop`/`openModuleWindow`),
> НЕ отдельные hash-экраны и НЕ текущий аккордеон. Обоснование — ADR-001.

### 4.1 Текущее состояние

`web/index.html:1577-1783` — единый экран `.acc` (эксклюзивный аккордеон):
заголовки `:1584-1587` «Администраторы» (`isAccessOpen('admins')`), `:1615-1618` «Матрица ролей»
(`roles`), `:1736-1739` «Локальные админы» (`local`); панели `#acc-admins/#sec-admins`,
`#acc-roles/#sec-roles + #sec-matrix`, `#acc-local/#sec-local`. Вне аккордеона —
«Мой доступ» `:1785-1795`, «Промпты» `:1797-1805`, «Telegram ID админа» `:1810+`.
Логика: `accessOpen` (`app.js:603`), `applyRoute` (`:1851-1857`), `setAccess`/`isAccessOpen`
(`:1884-1890`), `HUBS['#/access']` (`:288-302`), `openHubCard` (`:2062-2069`).

### 4.2 Целевое поведение

- `#/access` — **hub-экран с карточками** (как сейчас): `Матрица ролей` / `Локальные админы` / `Роли`.
- Клик по карточке → переход на `#/access/roles|local|admins` → **открывается модальное окно**.
- Соответствие окон (маршрут → окно → содержимое, id сохраняются):
  | Маршрут | Заголовок окна | Содержимое |
  |---|---|---|
  | `#/access/roles` | **Матрица ролей** | `#sec-roles` (определения ролей, заголовок «Роли») + `#sec-matrix` |
  | `#/access/local` | **Локальные админы** | `#sec-local` (как сейчас, «Локальные админы чата») |
  | `#/access/admins` | **Роли** (было «Администраторы») | `#sec-admins` (список назначений ролей) |
- **Вне окон, всегда видны:** «Мой доступ», «Промпты» (условие как сейчас), «Telegram ID админа».
- На экране `activeTab==='access'` (когда открыто окно) дополнительно оставить три кнопки-плитки
  тех же окон + always-visible карточки, чтобы deep-link и переключение окон работали.

### 4.3 Точный фикс

**`web/app.js`:**
- `data.accessOpen` (`:603`) — **ключ сохранить**, семантика = id открытого окна
  (`null | 'roles' | 'local' | 'admins'`).
- `applyRoute` (`:1851-1857`): заменить на безусловную нормализацию —
  `accessOpen = route.indexOf('#/access/') === 0 ? route.substring('#/access/'.length) : null;`
  (устраняет stale-состояние при уходе на не-access маршрут).
- Удалить `setAccess` (`:1884-1886`). Добавить:
  - `openAccessWindow(id)` → {@RBAC-проверка `canViewTab('access')`} `navigateTo('#/access/' + id)`.
  - `closeAccessWindow()` → `navigateTo('#/access')`.
  - `isAccessOpen(id)` (`:1888-1890`) — оставить.
- `goBack` (`:2129-2135`): изменений **не требует** — `ROUTE_PARENT` (`:484-485`) уже отображает
  `#/access/*` → `#/access`; нативный BackButton и in-app `←` закрывают окно через hash.
- `HUBS['#/access']` (`:288-302`): `cards[2].title` `'Администраторы'` → `'Роли'`;
  `section` из access-карточек удалить (якорный скролл не нужен — окно само открывается);
  `openHubCard` (`:2062-2069`) оставить (навигация триггерит окно через `applyRoute`).
- Сохранить `canViewTab('access')`, `isGlobalAdmin`-условия на содержимом (role CRUD disabled,
  matrix `v-if="isGlobalAdmin"`, локальные админы disabled) — RBAC не ослаблять.

**`web/index.html:1577-1783`:**
- Убрать `.acc`-аккордеон (`acc-head`/`acc-panel`/`role=tablist`); вместо него:
  - три `.hub-card`/кнопки «Матрица ролей», «Локальные админы», «Роли» (обработчик
    `openAccessWindow('roles'|'local'|'admins')`);
  - три модалки `v-if="isAccessOpen('roles'|'local'|'admins')"` по паттерну `:1248-1260`
    (`class="modal-backdrop" @click.self="closeAccessWindow()"`, `role="dialog"`, `aria-modal`,
    `aria-labelledby`, заголовок + кнопка `✕` `@click="closeAccessWindow()"`, `@keydown.esc`);
  - сохранить id `sec-roles`, `sec-matrix`, `sec-local`, `sec-admins` на телах окон;
  - заголовки: `Матрица ролей`, `Локальные админы`, **`Роли`**; внутренний `<div>` `sec-admins`
    с `text-sm font-bold` «Администраторы» → «Роли» (дубль заголовка допустим, окна взаимоисключающие).
- Always-visible карточки (`:1785-1817+`) — **не трогать** (кроме ничего).

**CSS** (`index.html:236-244`): `.acc`/`.acc-head`/`.acc-panel` можно удалить (после снятия
всех использований); модальные классы `.modal-*` уже есть (`:511-521`).

### 4.4 Модалка открыта / закрыта / back / deep-link

| Сценарий | Поведение |
|---|---|
| Открыть | клик по плитке/карточке → `openAccessWindow(id)` → hash `#/access/<id>` → `applyRoute` ставит `accessOpen` → окно видно |
| Закрыть (✕ / backdrop / Esc) | `closeAccessWindow()` → `#/access` → `accessOpen=null` → hub-карточки |
| Нативный Back (Android) | `goBack()` → `routeParent('#/access/<id>')='#/access'` → окно закрыто, hub виден |
| In-app `←` (fallback) | то же, `routeDepth>0` |
| Deep-link `#/access/<id>` | `initialRoute`/`applyRoute` открывает нужное окно сразу; RBAC-гейт как сейчас |
| Уход на другой раздел | `applyRoute` обнуляет `accessOpen` (окно не «всплывает») |

### 4.5 AC-4 и тесты

**AC-4:** «Матрица ролей», «Локальные админы», «Роли» открываются **каждая в отдельном окне**
(не одновременно); «Администраторы» → «Роли»; «Мой доступ» и «Telegram ID админа» — без
изменений и всегда доступны; deep-link и BackButton не сломаны; RBAC сохранён.

**Обновить тесты:**
- `tests/test_frontend_tab_mapping.py:203-207` — `accessOpen`/`openAccessWindow`/`modal-backdrop`
  вместо `acc-head`/`role="tabpanel"`.
- `tests/test_round106_ia_smoke.py:130-137` — модальные маркеры вместо `setAccess`/`acc-head`/`tabpanel`;
  `isAccessOpen('roles'|'local'|'admins')` сохранить.
- `tests/test_webapp_hubs_matrix_ui.py:30-49` — `sec-*` и «Матрица ролей» сохранить; карточку
  `'Роли'` добавить.
- `tests/test_webapp_key_availability_ui.py:69` — слайсинг `html.index("Роли")` хрупок после
  реструктуризации; переписать на явные секции (`id="sec-roles"` … `id="sec-local"`).
- `tests/test_webapp_back_button.py:35-44` — роуты `#/access/roles|local|admins` остаются (уже есть);
  добавить проверку `openAccessWindow`/`closeAccessWindow` и `ROUTE_PARENT`.
- `tests/js/routing_test.js:236` — `accessOpen` в ctx остаётся; добавить юнит: `applyRoute('#/access/roles')`
  → `accessOpen==='roles'`; `applyRoute('#/ai')` → `accessOpen===null`.
- **Добавить** `tests/test_webapp_access_windows_ui.py`: 3 `modal-backdrop` с `isAccessOpen(...)`,
  `openAccessWindow`, `closeAccessWindow`, отсутствие `acc-head`/`role="tabpanel"`,
  always-visible «Мой доступ»/«Telegram ID админа».

---

## 5. Пункт 5 — Удаление внешнего GLOBAL-бейджа (T-1259/T-1260)

**Root cause:** дубль индикатора контекста. Внутри селектора уже есть бейдж
`scopeLabel` (`index.html:638-641`), а сразу справа — внешний `v-if="!isChatContext()"`
`{{ scopeLabel }}` (`:672-674`), который дублирует GLOBAL и визуально «лишний».

**Фикс:**
- Удалить `web/index.html:672-674` (внешний `<span v-if="!isChatContext()" class="badge badge-muted shrink-0">{{ scopeLabel }}</span>`).
- **Оставить** внутренний бейдж `:638-641` и `#id`-бейдж `:669-671`.
- `scopeLabel` computed (`app.js:923-926`) и `isChatContext()` (`:1371-1373`) — **не удалять**
  (используются внутри селектора/бейджа `#id`).
- Grep-gate: `{{ scopeLabel }}` встречается ровно **1** раз (в триггере); строка
  `class="badge badge-muted shrink-0">{{ scopeLabel }}` отсутствует.

**AC-5:** в шапке ровно один GLOBAL-бейдж (внутри trigger); `#id` для ЧАТ/ЛС не затронут.

**Тест:** добавить в `tests/test_webapp_round108_ui.py` (или `test_webapp_round107_ui.py`)
подсчёт `{{ scopeLabel }}` == 1 и отсутствие внешнего паттерна.

---

## 6. Секция F — README restructure (T-1261/T-1262/T-1263)

**Целевая структура (ироничный тон сохраняется):**
1. Шапка: версия/раунд **10.8** + актуальный счётчик тестов (baseline 5042 + новые).
2. **«Самое важное для пользователя»** — наверх (что умеет бот, как открыть TMA).
3. Быстрый старт (сохранить).
4. **«Управление + деплой»** — консолидированный гайд (systemd `admin_bot`, `git pull --ff-only`,
   рестарт, health, `.env`).
5. Таблица разделов `:451-456` — новые подписи (Доступы / PERMsoc / ИИ / Справка / Сводка),
   описание окон «Доступов» (§4), фикс логов на Android (§3).
6. Narrative раундов `:334-403` + новый абзац 10.8.
7. **Changelog** раундов — под `<details>` (включая раунд 10.8).
8. Секретов нет; вложенные `<details>` корректно открываются/закрываются; дублей текста нет.

**AC-F:** есть блок «самое важное» наверху; есть гайд «управление+деплой»; changelog под
`<details>`; шапка актуальна; секретов нет.

---

## 7. Feature Flags / Progressive Delivery / Rollback

- **Feature flag НЕ требуется:** изменения UI-only (`web/*`, README, tests), без изменения
  API-контрактов, БД, PG-DDL и `bot.py`. Раскатка — обычным деплоем (`git pull --ff-only` +
  `systemctl restart admin_bot`), как в 10.7.
- **Kill-switch `ui.accessSeparateWindows` — НЕ вводим** (ADR-001): единый статический бандл TMA,
  прогрессивный роллаут 10/50/100% неприменим; откат — атомарный `git revert` коммита 10.8.
- **«Прогрессивная доставка»** в этом раунде реализуется как **обязательная live-верификация на
  реальном Android** (AC-3) перед объявлением раунда закрытым.

---

## 8. Консолидированный список файлов к изменению

| Файл | Что |
|---|---|
| `web/app.js` | п.1 лейблы/иконки TABS/NAV/HUBS; п.2 ICONS (17 новых); п.3 fmtLogTime/setTab; п.4 openAccessWindow/closeAccessWindow/applyRoute/HUBS.section |
| `web/index.html` | п.1 заголовки; п.2 emoji→icon (список §2.2); п.3 логи (шаблон+CSS); п.4 окна «Доступов»; п.5 удалить внешний бейдж |
| `scripts/build_font_subset.py` | ICON_NAMES (37, минус 6 мёртвых); экспорт `icon_codepoints.json`; маркер идемпотентности с учётом ICON_NAMES |
| `web/static/fonts/material-symbols-rounded.woff2` | пересобранный субсет (только артефакт; исходник не коммитить) |
| `README.md` | §6 |
| `tests/test_font_subset.py` | cmap-проверка + parity (R10.7-4) |
| `tests/test_webapp_tma_fixes_ui.py` | логи (pre/break-all/log-toggle) |
| `tests/test_webapp_round107_ui.py` | логи колонки |
| `tests/test_frontend_tab_mapping.py` | access windows |
| `tests/test_round106_ia_smoke.py` | access windows |
| `tests/test_webapp_hubs_matrix_ui.py` | лейблы/hub cards |
| `tests/test_webapp_parity_smoke.py` | REFERENCE_SECTIONS/oversight |
| `tests/test_webapp_nav_disclosure_ui.py` | emoji «Настройки отношений» |
| `tests/test_webapp_key_availability_ui.py` | слайсинг «Роли» |
| `tests/test_webapp_back_button.py` | access windows routes/ROUTE_PARENT |
| `tests/js/routing_test.js` | access window applyRoute (opt.) |
| **новый** `tests/test_webapp_round108_ui.py` | renames/emoji/badge/logs/access windows |
| **новый** `plans/features/admin-ui-round108/spec.md` (этот), `ADR-001`, `ADR-002` | — |

**НЕ трогать:** `services/param_catalog.py` (группа «Функции PERMsoc: рубильники»),
`services/status_service.py`, `web/api/*`, `bot.py`, `media/`, PG-схему, `/api/logs`.

---

## 9. Acceptance criteria (сводно) и grep-гейты

| # | AC |
|---|---|
| 1 | Ровно `Статус/Справка/Модули/ИИ/PERMsoc/Доступы` + заголовок `Сводка`; hash-ключи/deep-link целы; старые лейблы отсутствуют в `web/` |
| 2 | Нет pictographic-emoji из §2.2; все PUA `ICONS` в cmap субсета; субсет `< 60 КБ`; спецсимволы §2.3 целы |
| 3 | Android: ширина/дата/текст/нет невидимого поля/копирование; десктоп без регрессий; `copiedTimer` очищается |
| 4 | Три окна отдельно; `Администраторы→Роли`; «Мой доступ»/«Telegram ID админа» целы; deep-link/BackButton/RBAC целы |
| 5 | Ровно один GLOBAL-бейдж (в trigger); `#id` цел |
| F | README: «самое важное», гайд, changelog под `<details>`, шапка 10.8, секретов нет |

**Grep-гейты (обязательны, §5 QA tasks):**
- `web/app.js`/`web/index.html` не содержат `label: 'Настройки AI'`, `label: 'Функции PERMsoc'`,
  `label: 'Доступы и Роли'`, `label: 'Как это работает'`, `label: 'Oversight'`;
  не содержат `«Функции PERMsoc»`, `«Настройки AI»`, `«Доступы и Роли»`, `«Как это работает»`.
- `web/index.html` не содержит pictographic-emoji §2.2.
- `web/index.html` не содержит `acc-head`/`role="tabpanel"`.
- `web/index.html` содержит ровно один `{{ scopeLabel }}`.
- каталог `group_tab`/`title_ru` не изменён (пинится `test_param_catalog.py`).

---

## 10. Parity notes (без потери функциональности)

- **Лейблы** — меняются только отображаемые строки; маршруты, RBAC, загрузчики данных не тронуты.
- **Иконки** — визуальная замена; `TAB_ICON`/fallback сохраняют рендер; текст заголовков рядом
  с иконкой сохраняется.
- **Логи** — контракт `/api/logs`, `logText` (копирование), разворот стека, автоскролл к верху,
  `copyAllLogs`, ghost-fallback сохраняются; меняется только раскладка/формат времени.
- **Доступы** — всё содержимое (роли, матрица, локальные админы, назначения) сохраняется 1:1,
  меняется лишь контейнер (аккордеон → модалки) и заголовок; «Мой доступ»/«Промпты»/«Telegram ID
  админа» остаются вне окон и доступны как раньше.
- **Бейдж** — удаляется только дубль; функциональный индикатор контекста остаётся внутри селектора.

---

## 11. Остаточная неопределённость / риски

1. **Android-регрессия** не воспроизводится статически/на десктопе — финальное подтверждение
   только live на реальном устройстве (T-1254). Если устройство недоступно — эскалация, не закрывать.
2. **PUA-коды новых иконок** берутся из GSUB исходного шрифта; имена стандартные, но при отсутствии
   лигатуры билд-скрипт упадёт с явной ошибкой (`derive_pua_codepoints`). Риск низкий.
3. **`fontTools` в тест-окружении:** тест cmap требует `fontTools` (build-time dep). В `.venv`
   он есть (4.64.0); в DoD — тест обязан выполняться, не skip. Если CI без `fontTools` —
   добавить его в dev/test-окружение (не в runtime `requirements.txt`).
4. **Дубль заголовка «Роли»** (окно `#/access/admins` и карточка `sec-roles` в окне
   `#/access/roles`): окна взаимоисключающие, одновременного показа нет. Альтернатива при
   возражении владельца — переименовать внутреннюю карточку в «Определения ролей».
5. **TAB_ICON** уже покрывает prompts/status/oversight; если появятся новые tab.id — дополнить.
6. **`test_webapp_key_availability_ui.py:69`** — хрупкий слайсинг, обязателен апдейт (§4.5).

---

## 12. Трассируемость задач

| T | Пункт | Раздел спеки |
|---|---|---|
| T-1243/T-1244/T-1245/T-1246 | 1 | §1 |
| T-1247/T-1248/T-1249 | 2 | §2 |
| T-1251/T-1252/T-1253/T-1254 | 3 | §3 |
| T-1255/T-1256/T-1257/T-1258 | 4 | §4 |
| T-1259/T-1260 | 5 | §5 |
| T-1261/T-1262/T-1263 | F | §6 |
| T-1250 (opt) | R10.7-3/R10.6-1 | §3.3 |
| T-1264…T-1269 | QA/deploy/audit/archive | `tasks.md` |

*Spec generated by @Architect on 2026-09-11. Реализацию не содержит.*
