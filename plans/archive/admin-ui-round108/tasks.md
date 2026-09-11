# admin-ui-round108 — tasks.md

> **✅ СТАТУС: ЗАВЕРШЕНО И ЗААРХИВИРОВАНО (11.09.2026, @PM Step 8 Archive Phase).**
> Фича перенесена из `plans/features/admin-ui-round108/` в
> **`plans/archive/admin-ui-round108/`** (плоский kebab-case, как существующие архивы).
> Итог: полный pytest — **5076 passed / 0 failed** (база 10.7 = 5042 → **+34**); @Reviewer —
> **APPROVED WITH MINOR ISSUES** (doc-nit исправлен); @Scanner — **0 blocker / 0 major**
> (2 minor R10.8-1 Esc / R10.8-5 `APP_VERSION`+cache-bust субсета — закрыты точечно до Merge;
> 3 info R10.8-2/-3/-4 — техдолг) (`plans/reports/round10.8_scanner_audit.md`); @Architect —
> архитектура влита в `plans/ARCHITECTURE.md` (**§29** + связанные §1/§9/§25). Каталог-инвариант:
> **REGISTRY 392 / GROUPS 91 / Settings 364** (mapped 89). Артефакты сохранены: `spec.md`,
> `ADR-001-access-windows-modal.md`, `ADR-002-icon-subset-parity.md`, `tasks.md`.
> **ОТКРЫТО (live-верификация на реальном Android):** **T-1254** (логи: ширина/дата/текст/
> отсутствие невидимого поля) и **T-1258** (три отдельных окна «Доступов») — реальное
> Android-устройство/Telegram в среде @Builder недоступно; статически покрыто
> (`tests/test_webapp_round108_ui.py`, JS-юнит), финальная live-проверка остаётся за
> владельцем/QA. **Статус: НЕ ЗАКРЫТЫ.**
> **ВНИМАНИЕ:** пост-архивная фаза @DevOps (commit/push/deploy/live-smoke, T-1265…T-1267)
> выполняется ПОСЛЕ архива; статусы `[ ]` в секции @DevOps отражают состояние на момент
> архивации. **README-счётчик тестов показывает 5073 — @DevOps должен выставить 5076.**

**Раунд:** **10.8** (подтверждён; продолжает задеплоенный 10.7).
**Фича:** `plans/archive/admin-ui-round108/` (kebab: `admin-ui-round108`; перенесена @PM Step 8 11.09.2026).
**Статус:** ✅ **РЕАЛИЗАЦИЯ ЗАВЕРШЕНА; фича заархивирована 11.09.2026** (@PM Step 8). Финальный pytest — **5076 passed / 0 failed** (node clean, cmap-паритет 37/37). Открытыми остаются только live-проверки на реальном Android/телефоне (**T-1254/T-1258 — за владельцем/QA**) и процессы @DevOps (commit/push/deploy, T-1265…T-1267) — пост-архив. — 11.09.2026.
**Нумерация задач:** **T-1243…** (продолжает T-1242 — финал 10.7).
**Роли:** `@Architect` (design/spec), `@Builder` (реализация), `@DevOps` (commit/push/deploy), `@Scanner` (аудит), `@Reviewer`.
**Преемник:** 10.7 `admin-ui-bugfixes-round107` (архив; задеплоен 11.09.2026; commit `7f3b790`, прод fast-forward, health 200).
**Базовая линия:** pytest **5042 passed / 0 failed**; `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог **REGISTRY 392 / GROUPS 91 / Settings 364** (mapped 89).
**Правило:** `@PM не пишет код`. Архитектурные решения и `spec.md` — за `@Architect`.

---

## 0. Запрос владельца (дословно, для трассируемости)

1. Rename main sections: «Доступы и роли» → «Доступы»; «Функции PERMsoc» → «PERMsoc»; «Настройки AI» → «ИИ»; «Как это работает» → «Справка»; «Oversight» → «Сводка».
2. Replace remaining EMOJI in blocks/sub-sections inside sections with icons.
3. Fix LOGS regression on Android: table width broke; DATE disappeared; error text column is one character wide; the invisible selection field is STILL in the first column (10.7 did not fully fix it). Must work correctly on Android.
4. Access section: «Матрица ролей», «Локальные админы», «Администраторы» must EACH open in a SEPARATE window (not all on one screen). Rename «Администраторы» → «Роли». Keep «Мой доступ» and «Telegram ID админа» unchanged.
5. Remove the outer GLOBAL badge to the right of the chat selector (duplicate of the one inside the selector).
**Плюс:** README restructure (ironic tone preserved): most-important-for-users section, management+deploy guide, and a changelog under a collapsible (`<details>`). Russian commit, push, deploy, plain-language report.

---

## 1. Учёт аудита @Scanner (обязательный routine)

- [x] **Прочитан новейший аудит:** `plans/reports/round10.7_scanner_audit.md` (0 blocker / 0 major; 1 minor R10.7-1; info R10.7-2…R10.7-5). Также просмотрены `audit_backlog.md`, `global_map.md`, `full_audit_results.md`.
- **R10.7-4 (info, font-test gap):** тест `test_font_subset` проверяет наличие PUA-кода в JS, а не глиф в cmap субсета → **включено в 10.8 как T-1249** (особенно важно, т.к. пункт 2 добавляет новые иконки в субсет).
- **R10.7-1 (minor, gap-fill помечает незавершённый слот `down`)** и **R10.7-2 (info, `[-288:]`)** — `services/status_service.py`, **вне UI-скоупа 10.8**; кандидаты P2/10.9 (см. T-1250, опционально).
- **R10.7-3 (info, `copiedTimer` не очищается при смене вкладки)** — `web/app.js`; **опционально** (T-1250), закрывается только если не раздувает риск раунда.
- **R10.6-1 (minor: дублирующий generic-рендер на `llm_providers`, 21 дубль; T-1234 не выполнен в 10.7)** — **опционально P2** (T-1250).
- **R10.6-2 (SSRF `https`) и R10.6-3 (422-эхо `api_key`, R17)** — вне UI-скоупа; кандидаты отдельного раунда (в 10.8 не брать).
- **R10.7-5 (info, неточная формулировка причины `copyAllLogs`)** — учтено: в tasks 10.8 причину не дублируем.

---

## 2. Рекогносцировка @PM — карта кода (file:line)

> Опорные точки для `@Architect` (spec.md) и `@Builder`. **Не** готовые решения.

### 2.1 Пункт 1 — переименования разделов (меню, табы, хабы, заголовки)

- **NAV_ITEMS (нижнее/верхнее меню, 6 пунктов):** `web/app.js:246-255`
  - `:248` `label: 'Как это работает'` → **«Справка»**
  - `:250` `label: 'Настройки AI'` → **«ИИ»**
  - `:251` `label: 'Функции PERMsoc'` → **«PERMsoc»**
  - `:253` `label: 'Доступы и Роли'` → **«Доступы»**
- **TABS (заголовки/табы контента):** `web/app.js:156` (`permsoc` «Функции PERMsoc»), `:171` (`access` «Доступы и Роли»), `:186` (`info` «Как это работает»), `:189` (`oversight` «Oversight»). Также `:184` (`status`).
- **HUBS:** `web/app.js:261-303` — `#/ai` `title:'Настройки AI'` (`:262`) → «ИИ»; `#/access` `title:'Доступы и Роли'` (`:289`) → «Доступы»; подзаголовки/карточки `:263-301`.
- **routeToTab / route-маппинги:** `web/app.js:784-794` (ключи `how/ai/permsoc/access` — **не менять**, меняются только `label`).
- **Шаблон index.html:** `:809` «🎭 Функции PERMsoc»; `:1489` «🛰️ Global Oversight»; `:2413` «Oversight» (hub-card); `:2596` «Как это работает»; `:1583` `aria-label="Доступы и роли"`.
- **README:** таблица разделов `README.md:456` (`👥 Доступы и Роли`) и narrative-разделы раундов (`:358-403`) — синхронизировать (пункт F).
- **Тесты, завязанные на подписи (обновить):** `tests/test_webapp_hubs_matrix_ui.py:14-15`; `tests/test_webapp_parity_smoke.py:21-25`; `tests/test_frontend_tab_mapping.py:210-211`; `tests/test_round106_ia_smoke.py:123-124`; `tests/test_webapp_key_availability_ui.py:70`; `tests/test_webapp_rbac_ui.py:94`; `tests/test_webapp_lore_ui.py:201`.
- **ВНИМАНИЕ (не переименовывать):** каталог-заголовок группы `by_id["flags_permsoc"].title_ru == "Функции PERMsoc: рубильники"` (`tests/test_param_catalog.py:346,382`) — это заголовок **параметра**, не пункт меню. Решение зафиксировать в spec у `@Architect`.

### 2.2 Пункт 2 — emoji в блоках/подсекциях → Material-иконки

- **Система иконок:** `ICONS` (PUA-карта, 20 иконок) `web/app.js:207-228`; `TAB_ICON` `:230-242`; `iconGlyph(name)` `:2164-2165`; `tabMat(id)` `:2167-2170`; рендер `<span class="msr">{{ iconGlyph('...') }}</span>`.
- **Сборка субсета (offline, build-time):** `scripts/build_font_subset.py` — `ICON_NAMES` `:46-53`; деривация PUA `:86-119`; запуск `python scripts/build_font_subset.py`. Артефакт: `web/static/fonts/material-symbols-rounded.woff2` (в git), источник 5.11 МиБ — gitignored.
- **Тест субсета:** `tests/test_font_subset.py:64-74` (см. T-1249 — усилить проверкой cmap).
- **Реальные emoji, подлежащие замене (видимые заголовки/подсекции/кнопки):**
  - `web/app.js:43` `'🧠'` (Промпты), `:184` `'📊'` (Статус), `:189` `'🛰️'` (Oversight).
  - `web/index.html:809` 🎭, `:975` 👁/🙈 (reveal), `:1173` 📊, `:1209`/`:1220`/`:1380`/`:2478` 🧠, `:1416` 🛡, `:1420` 🗑, `:1452` 🌟, `:1489` 🛰️, `:1802` ⚙, `:1828`/`:1840`/`:1853` 👥, `:1935` 💾, `:1949`/`:2198`/`:2320` ⚙️, `:2146` 📝, `:2166`/`:2424` 🤖, `:2258` 🚚, `:2279` 👑, `:2434` 🔄, `:2438` ⏹, `:2442` ▶, `:2450` 🖥, `:2498` 📈, `:2509` 🔑, `:2548`/`:2699` 📜, `:2930` 🗑.
  - **Не трогать (не emoji-заголовки):** ✕ (закрыть), ⛶ (fullscreen), ▸/▾ (тогглы), ↪ (reset override), ⟳/↻, ←/→, ↔, а также стрелки в комментариях JS.
- **Тест, завязанный на emoji:** `tests/test_webapp_nav_disclosure_ui.py:238` (`"⚙️ Настройки отношений"` — обновить вместе с заменой).
- **Контракт:** новые Material-имена + PUA-коды обязаны быть в `ICONS`, в `ICON_NAMES` билд-скрипта и в cmap пересобранного субсета (иначе — tofu).

### 2.3 Пункт 3 — регрессия логов на Android (главное)

- **Шаблон блока логов:** `web/index.html:2545-2589`
  - фильтр-строка `:2547-2555`; нативный `<select v-model="logLevel">` `:2549-2551`; «Копировать всё» `:2554`;
  - панель `<div class="log-panel scroll-thin" ref="logPanel">` `:2565`;
  - `<pre v-else class="log-code break-all"><code>` `:2568`;
  - строка `<span class="log-row ...">` `:2569-2587`; **первый элемент строки — `<button class="log-toggle">` с глифом `▸`/`▾`** `:2574-2577` (**главный кандидат «невидимого selection-поля» первой колонки**: глиф отсутствует в Android-шрифте → пустая невидимая кнопка); level `:2578-2580`; ts `:2581`; logger `:2582`; msg `:2583` (`flex-1 min-w-0`); exc `:2585`.
- **CSS:** `.log-row` `:404`; `.log-panel` `:419-426`; `.log-code` `:427-433` (`white-space: pre-wrap; word-break: break-all`); `.log-level` `:436-437` (`min-width:4.5rem`); **`.log-ts` `:438-441` (`width:8ch; white-space:nowrap; tabular-nums`)**; `.log-logger` `:442-445` (`max-width:8rem`); `.log-msg` `:446-448`; `.log-panel .log-code` `:450`; media ≤479 `.log-logger{display:none}` `:302`.
- **JS:** `fmtLogTime` `web/app.js:3285-3291` — **возвращает только `HH:MM:SS`** (полная дата только в `:title` через `fmtLogTs` `:3279-3282`) → **root-cause «DATE disappeared»** на тач-устройствах, где `title` недоступен; `logText` `:3305-3308`; `copyText` (ghost-textarea) `:3309-3342`; `copyLogRow` `:3344-3352`.
- **Гипотезы Android-поломки (подтвердить @Architect в spec / live DOM):**
  1. строка лога — inline-`<span class="log-row">` внутри `<pre>` (`white-space: pre-wrap`), а вложенный `<span class="flex ...">` — flex; на старом Chromium/WebView контейнинг-блок схлопывается → ширина/колонки ломаются;
  2. жёсткие `4.5rem + 8ch + 8rem` на узком экране > доступной ширины → `.log-msg` получает ~0 и переносится по символу («колонка в один символ»);
  3. нативный `<select>` и/или отсутствующий глиф `▸`/`▾` дают «невидимое поле»;
  4. «table width broke» — из-за inline/flex и `break-all` на `.log-code`.
- **Контекст 10.7 (что уже пробовали):** `plans/archive/admin-ui-bugfixes-round107/tasks.md:177-192` (§3a — «невидимый div/input слева от select INFO»; статически не воспроизведён; кандидаты: ghost-textarea, Vue-комментарии, grid `main`), `:194-199` (§3b колонки), `:254-264` (T-1231…T-1233). В шаблоне буквального скрытого `<input>`/`<div>` перед select нет.
- **Требование:** корректная работа на реальном Android (Telegram WebView) — live-проверка обязательна (см. QA §5), эмуляция desktop недостаточна.

### 2.4 Пункт 4 — «Доступы»: три подраздела отдельными окнами + переименование

- **Экран «Доступы»:** `web/index.html:1577-1783` — единый экран `.acc` (аккордеон).
  - заголовки: `:1584-1587` «Администраторы» (`isAccessOpen('admins')`), `:1615-1618` «Матрица ролей» (`roles`), `:1736-1739` «Локальные админы» (`local`);
  - панели: `:1588-1613` `#acc-admins`/`#sec-admins`, `:1619-1734` `#acc-roles`/`#sec-roles`+`#sec-matrix`, `:1740-1782` `#acc-local`/`#sec-local`;
  - вне `.acc` (всегда видны): «Мой доступ» `:1785-1795` (**не менять**), «Промпты» `:1797-1805`, «Telegram ID админа» `:1810+` (**не менять**).
- **Логика аккордеона/роутинга:** `accessOpen` data `web/app.js:603`; `applyRoute` `#/access/*` → `accessOpen` `:1851-1857`; `setAccess`/`isAccessOpen` `:1884-1890`; hub-карточки `HUBS['#/access']` `:288-302` (route `#/access/roles|local|admins` + `section`); `openHubCard` `:2062-2069` (navigate + `scrollToId`) — **сейчас обе/все секции рендерятся на одном экране**.
- **Паттерн «отдельного окна», который уже есть в проекте (модули):** `openModuleWindow` `web/app.js:1892+`; `activeModule` `:811-819`; `openModuleId` data; модалка `web/index.html:1240-1260`; `_ensureModuleData`. `@Architect` — решить, переиспользовать ли модалку модулей или отдельные hash-экраны, и как сохранить deep-link/`BackButton`.
- **Тесты, завязанные на секции/роуты:** `tests/test_webapp_hubs_matrix_ui.py:34-44` (`sec-matrix/sec-local/sec-admins`), `tests/test_webapp_back_button.py:41-42` (`#/access/roles|local|admins`), `tests/test_frontend_tab_mapping.py:204`/`tests/test_round106_ia_smoke.py:131` (`accessOpen`), `tests/js/routing_test.js:236` (`accessOpen`).
- **Требование:** «Администраторы» → **«Роли»**; «Мой доступ» и «Telegram ID админа» остаются без изменений.

### 2.5 Пункт 5 — внешний GLOBAL-бейдж (дубль)

- **Внутри селектора (оставить):** `web/index.html:638-641` — `<span class="badge" :class="scopeKind==='global' ? 'badge-muted' : 'badge-info'">{{ scopeLabel }}</span>`.
- **Внешний (удалить):** `web/index.html:672-674` — `<span v-if="!isChatContext()" class="badge badge-muted shrink-0">{{ scopeLabel }}</span>`.
- **Соседний бейдж `#id` для чата/ЛС (оставить):** `:669-671`.
- `scopeLabel` computed `web/app.js:923-926`; `isChatContext` не найден в шаблоне рядом — учесть в spec (проверить, не используется ли внешний бейдж где-то ещё; grep по `scopeLabel`/`!isChatContext`).

### 2.6 README restructure

- **Структура сейчас:** заголовок+интро `README.md:1-9`; «Быстрый старт» `:11-24`; «Где живут настройки» `:27-36`; «Как узнать Telegram ID» `:40-44`; «Функции бота» `:48-402` (per-round narrative: 10.3 `:334`, 10.4 `:344`, 10.5 `:358`, 10.6 `:374`, 10.7 `:389`); «Служебное» `:404`; Docker `:423`; «Админка (TMA)» `:443+`; «Справочник параметров» `:495+`; «Как менять тексты» `:816`; «Тестирование» `:852`; «Мониторинг» `:870`; «Известные нюансы» `:890`.
- Сейчас в README только **2 `<details>`**; changelog-раздел отсутствует.
- **Цель:** (a) блок «самое важное для пользователя» наверх; (b) консолидированный гайд «управление + деплой»; (c) changelog под `<details>` (ироничный тон сохранить, канон стиля — как в разделах раундов `:358-403`).
- README-раздел про раздел «Доступы» `:456` — обновить под новые подписи (пункт 1) и новое поведение (пункт 4).

---

## 3. Задачи (checklist)

> Формат: `- [ ] **T-NNNN [@Роль] Pn** — задача`. `@PM` код не пишет. Архитектура — только `@Architect`.

### Секция A — Пункт 1: переименование разделов

- [x] **T-1243 [@Architect] P0** — `spec.md`: зафиксировать финальную карту переименований (только `label`/`title`/заголовки; route-ключи `how/ai/permsoc/access` НЕ трогать), включая: aria-label `index.html:1583`, README, `aria-label` навбара, и явно — что каталог-группа `«Функции PERMsoc: рубильники»` НЕ переименовывается (это параметр, не меню). Определить единый источник подписи (TABS/NAV_ITEMS/HUBS) чтобы избежать рассинхрона.
- [x] **T-1244 [@Builder] P0** — переименовать в `web/app.js`: NAV_ITEMS `:248,250,251,253`; TABS `:156,171,186,189`; HUBS `#/ai.title :262`, `#/access.title :289` (+ подзаголовки, если содержат старые имена); заголовки в `web/index.html:809,1489,2413,2596`.
- [x] **T-1245 [@Builder] P0** — обновить тесты подписей: `tests/test_webapp_hubs_matrix_ui.py:14-15`, `tests/test_webapp_parity_smoke.py:21-25`, `tests/test_frontend_tab_mapping.py:210-211`, `tests/test_round106_ia_smoke.py:123-124` (заменить старые строки на новые: «Справка», «ИИ», «PERMsoc», «Доступы», «Сводка»). Grep по репозиторию на оставшиеся старые подписи.
- [x] **T-1246 [@Builder] P1** — сверить, что hash-роуты и `routeToTab` не сломаны (ключи не менялись); `tests/js/routing_test.js` без правок логики.

### Секция B — Пункт 2: emoji → иконки

- [x] **T-1247 [@Architect] P0** — `spec.md`: таблица «emoji → Material-имя» для всех видимых emoji из §2.2 (включая кнопки 🛡/🗑/💾/👁/🙈/🔄/⏹/▶/⚙️), с явным списком «не трогать» (✕/⛶/▸/▾/↪/⟳/←/→/↔). Определить, добавляем ли **новые** Material-имена в `ICONS` (напр. `psychology`, `dashboard`, `satellite_alt`, `group`, `content_save`, `inventory_2`, `smart_toy`, `description`, `shield`, `delete`, `refresh`, `stop`, `play_arrow`, `dns`, `trending_up`, `key`, `history`, `settings`, `engineering`, `crown`, `luggage`, `visibility`/`visibility_off`, `auto_awesome`) и обязать пересобрать субсет.
- [x] **T-1248 [@Builder] P0** — добавить новые Material-имена + PUA-коды в `ICONS` (`web/app.js:207-228`), заменить emoji в `web/app.js:43,184,189` и в перечне `web/index.html` (§2.2) на `<span class="msr">{{ iconGlyph('...') }}</span>`; обновить `tests/test_webapp_nav_disclosure_ui.py:238`.
- [x] **T-1249 [@Builder] P0** — расширить `ICON_NAMES` в `scripts/build_font_subset.py:46-53`, **пересобрать** `web/static/fonts/material-symbols-rounded.woff2` (`python scripts/build_font_subset.py`) и **усилить** `tests/test_font_subset.py` (R10.7-4): открывать WOFF2 через `fontTools`, парсить `ICONS` из `web/app.js` и проверять, что каждый PUA-код присутствует в cmap субсета; плюс проверка, что в шаблоне не осталось заменённых emoji. Добавить новые имена иконок в `TAB_ICON` при необходимости. **Не** коммитить исходник 5.11 МиБ.
- [x] **T-1250 [@Builder] P2 (опционально)** — если не раздувает риск: R10.7-3 (`clearTimeout(copiedTimer)` в `setTab`/`beforeUnmount`), R10.6-1 (дубль generic-рендера `llm_providers`, 21 дубль). R10.7-1/-2 (`status_service.py`) — только если явно согласованы; иначе отметить кандидатами 10.9.
  - ✅ R10.7-3 закрыт (`setTab` очищает `copiedTimer`/`copiedIndex`). R10.6-1 (generic-дубль `llm_providers`) сознательно **не** брался — риск больше пользы; остаётся кандидатом 10.9. R10.7-1/-2 — кандидаты 10.9.

### Секция C — Пункт 3: регрессия логов на Android

- [x] **T-1251 [@Architect] P0** — `spec.md`: root-cause анализ Android-регрессии логов (§2.3) с финальными решениями: (a) заменить inline-`<span class="log-row">` на блочный контейнер/`display:block` (или table-семантику) внутри `<pre>`; (b) адаптивная раскладка колонок level/date/logger под узкий Android (рассмотреть перенос level+date на первую строку, message — на вторую; убрать `break-all` у `.log-code`); (c) вернуть **дату** (не только `HH:MM:SS`) либо видимой, либо гарантированно доступной без hover; (d) устранить «невидимое selection-поле» — заменить/скрыть `▸`/`▾`-кнопку так, чтобы она не выглядела пустым полем (иконка из субсета, либо `v-if` только при наличии `exc_text`, либо явная визуальная метка); (e) подтвердить, что ghost-textarea (`app.js:3309-3342`) не влияет. Не менять контракт `/api/logs`.
- [x] **T-1252 [@Builder] P0** — реализовать фиксы шаблона `web/index.html:2545-2589` и CSS `:400-463`; при правке `fmtLogTime`/`fmtLogTs` (`web/app.js:3285-3291`, `:3279-3282`) сохранить копирование (`logText`) и разворот стека.
- [x] **T-1253 [@Builder] P0** — обновить/добавить тесты логов: `tests/test_webapp_round107_ui.py`, при необходимости `tests/test_webapp_status_control.py`; проверки — на отсутствие `break-all`-конфликта, наличие даты, отсутствие «пустого» тумблера-первой-колонки. JS-проверки — в `tests/js/routing_test.js` при добавлении логики.
- [ ] **T-1254 [@Builder] P0** — **live-верификация на реальном Android** (Telegram WebView): ширина строк не ломается, дата видна, текст ошибки не в один символ, в первой колонке нет невидимого поля. Результат — в отчёт (пункт G). **Статус: НЕ ВЫПОЛНЕНО — реальное Android-устройство в среде @Builder недоступно. Задача не закрыта; требуется live-проверка владельцем/QA. Статическая верификация (тесты, node, cmap) пройдена.**

### Секция D — Пункт 4: подразделы «Доступов» отдельными окнами

- [x] **T-1255 [@Architect] P0** — `spec.md`: выбрать механизм «отдельного окна» (модалка по паттерну `openModuleWindow` `app.js:1892+`, или отдельные hash-экраны `#/access/roles|local|admins` без одновременного рендера остальных) с сохранением deep-link, `BackButton`, RBAC (`canViewTab('access')`) и `sec-*`-якорей (если сносим — обновить тесты). Зафиксировать: переименование «Администраторы» → «Роли», «Мой доступ» и «Telegram ID админа» — **без изменений** (и всегда доступны).
- [x] **T-1256 [@Builder] P0** — реализовать раздельные окна для «Матрица ролей»/«Локальные админы»/«Роли» (`web/index.html:1577-1782`, `web/app.js:288-302,603,1851-1857,1884-1890,2062-2069`); убрать одновременный рендер (аккордеон) в пользу выбранного механизма.
- [x] **T-1257 [@Builder] P0** — обновить тесты: `tests/test_webapp_hubs_matrix_ui.py:34-44`, `tests/test_webapp_back_button.py:41-42`, `tests/test_frontend_tab_mapping.py:204`, `tests/test_round106_ia_smoke.py:131`, `tests/js/routing_test.js:236`; добавить проверку, что «Мой доступ»/«Telegram ID админа» не затронуты и доступны.
- [ ] **T-1258 [@Builder] P1** — live-smoke на телефоне: каждая из трёх кнопок открывает отдельное окно; «Роли» названы верно; «Мой доступ»/«Telegram ID админа» на месте. **Статус: НЕ ВЫПОЛНЕНО — живой телефон/Telegram в среде @Builder недоступен; статически покрыто `tests/test_webapp_round108_ui.py`, deep-link/BackButton проверены JS-юнитом.**

### Секция E — Пункт 5: удаление внешнего GLOBAL-бейджа

- [x] **T-1259 [@Builder] P1** — удалить `web/index.html:672-674` (внешний `<span v-if="!isChatContext()">…scopeLabel…</span>`); оставить внутренний бейдж `:638-641` и `#id`-бейдж `:669-671`. Grep на неиспользуемость `scopeLabel` вне селектора; при необходимости удалить мёртвый return-путь (computed `app.js:923-926` нужен и внутри селектора — не удалять).
- [x] **T-1260 [@Builder] P1** — тест: в блоке шапки ровно один GLOBAL-бейдж (внутри trigger); обновить `tests/test_webapp_round107_ui.py`/релевантный шаблонный тест.

### Секция F — README restructure

- [x] **T-1261 [@Architect] P1** — `spec.md`: зафиксировать целевую структуру README (разделы и порядок), правило «ироничный тон сохраняется», что уходит в `<details>`-changelog, что остаётся в «Быстром старте».
- [x] **T-1262 [@Builder] P1** — перестроить `README.md`: (a) блок «самое важное для пользователя» наверх; (b) консолидированный гайд «управление + деплой»; (c) changelog раундов под `<details>`; (d) обновить раздел про «Доступы» `:456` и подписи разделов; (e) шапка «Версия/Тестов/Раунд» → 10.8 + новый счётчик тестов. Ироничный тон сохранить.
- [x] **T-1263 [@Builder] P1** — проверить вложенные `<details>` (корректное открытие/закрытие), отсутствие дублированного текста, отсутствие секретов.

### Секция G — commit / push / deploy / report

- [x] **T-1264 [@Builder] P0** — прогнать полный QA (§5): `node --check web/app.js`, `node tests/js/routing_test.js`, полный pytest (база 5042, 0 регрессий), `git diff --check`.
  - ✅ `node --check web/app.js` — clean; `node tests/js/routing_test.js` — `JS-UNIT-OK`; pytest — **5073 passed / 0 failed** (5042 + 31 новых); `git diff --check` — только CRLF-warnings (чисто).
- [x] **T-1264-followup [@Builder] P0** — закрыть 2 minor из аудита @Scanner:
  - **R10.8-5 (cache-bust субсета):** `APP_VERSION` `2.51.0`→`2.52.0` (`config/settings.py`, синхрон с шапкой README); `@font-face` src → `...woff2?v=__APP_VERSION__` (`.woff2` отдаётся `max-age=86400` → старый URL кэшировался до 24ч и давал tofu на новых глифах). URL с версией отдаёт 200 `wOF2`. Тесты: `tests/test_webapp_api.py::test_index_version_query_param`, `tests/test_webapp_round108_ui.py::TestCacheBustAndEsc108`.
  - **R10.8-1 (Esc не закрывал окна «Доступов»):** глобальный `_onKeydown` → `_appVm.escClose()`; новый метод `escClose()` (модуль приоритетнее, затем `closeAccessWindow()`). Тесты: JS-юнит `escClose` в `tests/js/routing_test.js`, статический маркер в `TestCacheBustAndEsc108`.
  - ✅ `node --check` clean; `node tests/js/routing_test.js` — `JS-UNIT-OK`; полный pytest — **0 failed**.
- [ ] **T-1265 [@DevOps] P0** — русский conventional-commit одним атомарным коммитом (код+тесты+plans), push `origin/master`, `@DevOps` — деплой на прод (`git pull --ff-only`, без изменений `.env` — UI/docs-only, `systemctl restart admin_bot`, health 200, логи без ERROR/Traceback).
- [ ] **T-1266 [@DevOps] P1** — финальный memory-sync (docs(plans)-коммит) по правилу T-725; проверка на секреты перед docs-коммитом.
- [ ] **T-1267 [@DevOps] P0** — plain-language отчёт владельцу (что изменилось в UI, что починили в логах, отдельным окном доступы, README) + ссылки на spec/tasks/аудит.
- [ ] **T-1268 [@Scanner] P0** — аудит 10.8 после реализации: инварианты (каталог 392/91/364, SQLite v8, ноль новых PG-DDL, `bot.py` не тронут, `media/` не тронут, секретов нет), проверка cmap субсета vs `ICONS`, независимый прогон pytest, отчёт в `plans/reports/round10.8_scanner_audit.md`.
- [ ] **T-1269 [@PM] P0** — Step 8: после APPROVED/аудита перенести `plans/features/admin-ui-round108/` → `plans/archive/`, обновить `backlog.md` (статус ✅).

---

## 4. Acceptance criteria (по пунктам)

| # | Пункт | Критерии приёмки |
|---|---|---|
| 1 | Rename sections | В навбаре/хабах/заголовках ровно: **Доступы**, **PERMsoc**, **ИИ**, **Справка**, **Сводка**. Старые строки отсутствуют в `web/` (кроме допустимых мест, зафиксированных в spec). Hash-ключи маршрутов не изменились; deep-link работает. Тесты подписей обновлены и зелёные. |
| 2 | Emoji → icons | В видимых заголовках/подсекциях/кнопках из перечня §2.2 нет pictographic-emoji; вместо них — Material-иконки через `iconGlyph`. Каждый PUA-код присутствует в cmap пересобранного субсета (проверка тестом). Спецсимволы ✕/⛶/▸/▾/↪/⟳/←/→ не заменены. Размер субсета остаётся «лёгким» (< 60 КБ по тесту). |
| 3 | Logs Android | На реальном Android (Telegram WebView): (a) ширина блока/строк не выходит за экран; (b) **дата видна** (не только время); (c) текст ошибки занимает нормальную ширину, не «один символ»; (d) в первой колонке **нет** невидимого selection-поля; (e) копирование строки/`Копировать всё`/разворот стека работают. Десктоп не регрессирует. |
| 4 | Access separate windows | «Матрица ролей», «Локальные админы», «Роли» открываются **каждая в отдельном окне** (не одновременно на одном экране). «Администраторы» переименованы в **«Роли»**. «Мой доступ» и «Telegram ID админа» — без изменений и доступны. Deep-link и `BackButton` не сломаны. RBAC сохраняется. |
| 5 | GLOBAL badge | В шапке остаётся **ровно один** GLOBAL-бейдж — внутри селектора контекста. Внешний бейдж справа от селектора удалён. Бейдж `#id` для ЧАТ/ЛС не затронут. |
| F | README | Есть блок «самое важное для пользователя» наверху; есть консолидированный гайд «управление + деплой»; changelog — под `<details>`; ироничный тон сохранён; шапка (версия/тесты/раунд) актуальна; секретов нет. |
| G | Process | Русский atomic-commit, push, деплой, health 200, 0 ERROR; plain-language отчёт владельцу; аудит `@Scanner` 0 blocker/0 major; фича заархивирована (@PM Step 8). |

---

## 5. QA / test plan

**Локальные команды (Windows, `.venv`):**
1. `node --check web/app.js` — синтаксис JS.
2. `node tests/js/routing_test.js` → ожидается `JS-UNIT-OK`.
3. `.venv\Scripts\python.exe -m pytest` — **базовая линия 5042 passed / 0 failed**; финал — 5042 + новые тесты, **0 failed**. `--timeout=120` (полный прогон ≤ 300с по правилу проекта).
4. `git diff --check` — чисто (LF/CRLF-warnings допустимы).
5. `.venv\Scripts\python.exe scripts/build_font_subset.py` — идемпотентно; размер субсета < 60 КБ.
6. Grep-гейты: нет старых подписей разделов; нет заменённых emoji в `web/index.html`/`web/app.js`; нет секретов в `git diff`.

**Инварианты (проверяет @Scanner/T-1268):** каталог **REGISTRY 392 / GROUPS 91 / Settings 364** (mapped 89); SQLite v8; **ноль новых PG-DDL**; `bot.py` не тронут; `media/` не тронут; секреты не в diff.

**Live-верификация (обязательна):**
- **Android (Telegram WebView, реальное устройство):** логи — ширина/дата/текст/первая колонка/копирование (AC-3).
- **Телефон:** доступы — три отдельных окна, подписи, «Мой доступ»/«Telegram ID админа» (AC-4).
- **Шапка:** единственный GLOBAL-бейдж (AC-5).
- **Навигация:** все 6 подписей меню + хабы + «Справка»/«Сводка» (AC-1).
- **Иконки:** визуально нет tofu/пустых квадратов после пересборки субсета (AC-2).

---

## 6. Feature flags & progressive delivery

- **Feature flag НЕ требуется:** изменения — UI-only (TMA `web/*` + README/docs), без изменений API-контрактов, схемы БД, PG-DDL и `bot.py`. Раскатка — обычным деплоем (`git pull` + restart), как в 10.7.
- **Роллбэк:** атомарный `git revert` коммита 10.8; `.env` не меняется.
- **Стадийность:** для TMA прогрессивный роллаут (10%→50%→100%) не применим (единый статический бандл); вместо этого — обязательная live-проверка на Android перед объявлением раунда закрытым.
- Если `@Architect` решит, что для пункта 4 нужна отдельная ветка поведения с возможностью отката — добавить **kill-switch** (напр. `ui.accessSeparateWindows`, default `true`); согласовать в spec и отразить здесь.

---

## 7. Definition of Done

- [ ] `spec.md` создан `@Architect`; все архитектурные решения зафиксированы.
- [ ] Все задачи T-1243…T-1267 выполнены или явно отклонены с обоснованием.
- [ ] Пункты 1–5 + README приняты по AC (§4).
- [ ] QA (§5) пройден; pytest ≥ 5042 passed / 0 failed; live Android-проверка выполнена.
- [ ] `@Reviewer` — APPROVED (или APPROVED WITH MINOR, исправлено).
- [ ] `@Scanner` — 0 blocker / 0 major (`plans/reports/round10.8_scanner_audit.md`).
- [ ] Commit/push/deploy/health/отчёт — выполнены (@DevOps).
- [ ] Архив: `plans/features/admin-ui-round108/` → `plans/archive/`; `backlog.md` обновлён (@PM Step 8).
