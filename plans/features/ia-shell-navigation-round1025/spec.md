# F1 — `ia-shell-navigation-round1025` · локальная спецификация

> **Раунд:** 10.25 (Эпик 1 «Liquid Glass Control Center»), **Wave 1** (после F0).
> **Мастер-ТЗ:** `plans/current_task.md` v6.0 (§0, §1, §4–§7, §68, §70, §71, §79, §116, §117) **+ блок UPD (строки 3718–5918): ЧАСТЬ II §7–§10 — решения Human Gate по F1; ЧАСТЬ I — F0**. Файл — `untracked`, в git **не коммитить**, секреты не цитировать (R17/R18).
> **Задачи:** T-2388…T-2409 (`tasks.md` этой папки).
> **Тип:** информационная архитектура + app shell. Vue 3 global zero-build, self-host, CSP `script-src 'self'`.
> **Статус:** Step 2 @Architect — **AMEND (после F0 Merge + UPD Human Gate)**. Реализация — @Builder (Step 4).
> **Предшественник (Wave 0):** **F0 `f0-config-bugfixes-round1025` — ✅ COMPLETED/DEPLOYED/ARCHIVED** (commit `3a91c84`, Merge §52). F0 изменила `web/app.js`: `persistItems()`, `saveState`, `notify()`, per-field ошибки, safe-area тосты; `services/*`: `write_transaction`, анти-клише. **F1 обязан переиспользовать этот слой (ARCHITECTURE.md §52), а не дублировать.**
> **Baseline после F0:** pytest **7946/0**; JS-гейты **19/19**; SQLite `user_version=12`; каталог `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418`; `web/app.js` ≈ **8175** строк.
> **Связанные ADR:** `ADR-1025-1` (эта папка), `ADR-1025-2/3/4/5` (F0), `ADR-1024-13` (доставка `ui_flags`), `ADR-1018-6` (nav-матрица), `ADR-001` (route-driven окна «Доступов»), `ADR-1016-2` (self-host/CSP).

---

## 1. Цель

Заменить плоскую верхнюю полосу из 6 равнозначных пунктов на **иерархическую информационную архитектуру по §4** и **раздельные desktop/mobile app shell’ы (§6/§7)**, не потеряв **ни одного** существующего экрана, параметра, виджета, права или значения (§1/§79/§116).

F1 — **структурный каркас** раунда: он задаёт разделы, маршруты, раскладку shell, точки доступа к областям и оффлайн-контракт «новый ↔ старый интерфейс». Визуальный слой (стекло, токены) — F2; состав виджетов Статуса — F11; селектор области — F3; композиция «Памяти/Аналитики» — F6; PERMsoc — F7; состояния сохранения/секретов — F9.

**Правила-ограничители (обновлены после F0/UPD):**
1. **Δ ParamSpec / GROUPS = 0.** Меняются только **nav-метаданные** (`NAV_ORDER`, `NAV_TITLES`, `TAB_NAV`) и UI-структура. Ни один `pg_key`, группа, дефолт или смысл `null/0/-1/""` не меняется.
2. **Δ DDL = 0.** SQLite остаётся `v12`, новых PG-таблиц нет.
3. **Существующие API не меняются**; единственное аддитивное поле — `IA_V2_ENABLED` в уже существующем `GET /api/me.ui_flags`.
4. **F0-слой сохранения — неприкосновенен.** AppShell/навигация **переиспользуют** `persistItems()`, `saveState`, `notify()`, per-field ошибки и safe-area тосты из F0 (`ARCHITECTURE.md` §9/§52). Никаких новых «useState-подобных»/параллельных состояний сохранения, никаких обходов `persistItems`. Тесты F0 остаются зелёными (pytest 7946/0, JS 19/19).
5. **Эпик 2 не трогаем.** В F1 **не менять**: алгоритмы Саммари, роутинг моделей, генерацию обложки, публикацию Rich Message (UPD §9.6).
6. **`IA_V2_ENABLED` — временный механизм отката**, не постоянная «вторая архитектура» (UPD §9.5): legacy-константы сохраняются до стабилизации, затем удаляются отдельной задачей.

---

## 2. Границы

### 2.1. In scope (F1)
- Новая IA §4: Публичные (Статус, Справка), Административные (Модули, ИИ, **Память**, Доступы), Локальное (PERMsoc).
- Статус — стартовая страница (`#/`); Статус/Справка — всем, остальные — по правам.
- Выделение **Памяти** в отдельный админ-раздел (`memory_rag`, `chat_lore`, `relations` переезжают nav-разделом из «ИИ»).
- Переименование «Сводка» → **«Аналитика»** (label), открывается из Статуса; отдельной конкурирующей главной «Обзор» **не создаём**.
- Hash-роутер: новые маршруты/подмаршруты, deeplinks, алиасы трасс, fallback мусорного hash → `#/`.
- Desktop app shell ≥1200 px: sidebar ≈232 px + header ≈64 px + контент; ограничение форм 1200–1440 px.
- **Tablet/compact 768–1199 px: БЕЗ постоянного sidebar** (UPD §8.3) — компактная навигация или **drawer**; полноценный sidebar только с 1200 px; селектор области остаётся легкодоступным.
- Mobile app shell <768 px: компактный header, одна колонка, **нижняя навигация ровно из 4 пунктов** (админ: **Статус/Модули/ИИ/Ещё**; пользователь: Статус/Справка), «Память» — внутри «Ещё» (UPD §8.4), сложные редакторы отдельными экранами. **Никакой полосы из 7 вкладок.**
- **Вложенные страницы:** показывать текущий раздел и понятный путь назад (breadcrumb/родительский хлебный путь + TMA BackButton), UPD §8.4.
- Адаптивность §70 (4 диапазона), отсутствие горизонтального скролла страницы, touch-таргеты ≥44×44.
- **Четыре ответа Human Gate (§8):** «Аналитика» — технический маршрут `#/oversight`, пользовательское имя «Аналитика», переход из Статуса, дублирующей страницы нет; «Профиль» — **существующий блок** Telegram-пользователя/администратора, новый экран не создаётся, профиль не путать с личностью бота; «Планшет» — drawer/компакт; «Нижнее меню» — 4 пункта.
- **Генеральные переключатели модулей (UPD §9.1):** сохранить быстрый toggle модуля из каталога (глобально/для чата) без открытия страницы параметров; если новый каталог F4 ещё не готов — **оставить доступ к старому работающему каталогу** (не подменять заглушкой).
- **Единое каноническое состояние (UPD §9.2):** ключ `scope_type + scope_id + module_id`, одно действие = одна серверная мутация, все представления синхронизированы; **согласовать с F4** (`ModuleConfigurationStore`), в F1 — не дублировать состояние.
- **Существующие виджеты (UPD §9.3):** без полноценного переноса (F6/F11) **сохранить доступ** к мониторингу интеллекта, убеждениям, парадигмам, эволюции характера, виджетам сна, живой ленте досье, дереву LLM-вызовов, графу связей, логам. **Не заменять работающие страницы заглушками.**
- **Аккордеоны промптов (UPD §7):** снять как **основной** способ навигации из 10.24 (финальное решение по §48/§69 — за F5); основные редакторы промптов доступны непосредственно, аккордеоны — только для второстепенных настроек.
- Атомарное обновление маркер-тестов и каталога **с сохранением зелёных F0-тестов**.
- TMA-интеграция §7: `BackButton`, `viewportStableHeight`, `safeAreaInset`, `contentSafeAreaInset` (расширение `web/static/telegram-init.js`).
- «Справка» §68: desktop — оглавление + контент; mobile — поиск/оглавление/текст; якоря. **Стиль текста не менять.**
- «Доступы» §68: desktop — матрица прав; mobile — последовательный редактор ролей. Семантику RBAC не менять; права решает сервер.
- Виджеты Статуса остаются смонтированными и доступными (polная композиция — F11); логи **не выносим** на отдельную страницу.
- Kill-switch `IA_V2_ENABLED` (env-only `ClassVar`, default **ON**), OFF → прежний navbar байт-в-байт.
- Атомарное обновление маркер-тестов и каталога.

### 2.2. Out of scope (F1) — явно уезжает в другие фичи
| Тема | Владелец |
|---|---|
| Токены Liquid Glass, палитра, фон/градиент, преломление — **Human Gate зафиксировал палитру `#090D17`/`#151B2A`** и требование сохранить атмосферный градиент (замедлить/ослабить) | **F2** `design-tokens-liquidglass-v2` |
| Снятие аккордеонов промптов как основной навигации (финальная реализация §48/§69, workspace-табы) | **F5** `module-workspace-tabs` (см. §2.1) |
| Селектор области (визуал и логика Глобально/Чат/ЛС) | **F3** `global-scope-selector` |
| Каталог модулей, избранное, `ModuleConfigurationStore` | **F4** `module-catalog-quickpanel-store` |
| Workspace-табы модуля (§46/§48) | **F5** `module-workspace-tabs` |
| ExecutionGraph, «Аналитика» наполнение, перенос памяти/лора | **F6** `memory-analytics-reorg` |
| Локальный PERMsoc-контекст (§60–§67) | **F7** `permsoc-local-space` |
| Реестр параметров, карта виджетов, инвентарь/бэкап (Wave 0) | **F8** `parameter-registry-widget-map` |
| Секреты, SaveBar, состояния сохранения | **F9** `secrets-and-save-states` |
| Playwright-матрица как приёмка Эпика 1 | **F10** `epic1-verification` |
| Композиция виджетов Статуса (§11–§20), логи-вьюер детально | **F11** `status-showcase-dashboard` |
| Эпик 2 (Summary Hybrid Pipeline) | вне Эпика 1 |

> **Важно по §68:** F1 делает **layout-трансформацию** «Справки» и «Доступов» (оглавление/поиск/якоря; мобильный последовательный редактор ролей), но **не переписывает контент, тексты и стиль** (это сохраняемо-инвариантно) и не вводит новые права.

---

## 3. Текущее состояние (факты из кода)

### 3.1. Каталог и nav-метаданные — `services/param_catalog.py`
| Якорь | Что там | Следствие |
|---|---|---|
| `:2029-2031` | `NAV_MODULES="modules"`, `NAV_AI="ai"`, `NAV_PERMSOC="permsoc"` | 3 nav-раздела |
| `:2033-2037` | `NAV_TITLES = {modules:"Модули", ai:"ИИ", permsoc:"PERMsoc"}` | нет «Памяти» |
| `:2039` | `NAV_ORDER = (NAV_MODULES, NAV_AI, NAV_PERMSOC)` | порядок матрицы |
| `:2045-2067` | `TAB_NAV` — 21 config-вкладка → nav | `chat_lore`/`relations`/`memory_rag` → `ai` |
| `:2070-2072` | `def tab_nav(tab_id)` | helper для API/тестов |
| `:2075-2201` | `TAB_RULES` (21 вкладка) | **не меняем** |
| `:2203-2236` | `_TAB_BY_GROUP` (96), `tab_group_ids`, `group_tab` | строится из `TAB_RULES` |
| `:2247+` | `known_sections()` | RBAC-валидация |

Эталонные счётчики baseline (тесты): `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings fields 418`.

### 3.2. Фронтенд — `web/app.js`
| Якорь | Что там |
|---|---|
| `:42-225` | `TABS = [...]` (26: 21 config + modules + status + info + oversight + access…); `.menu` — метаданные (реально не влияют на рендер) |
| `:218-225` | `status`(`always`), `info`(`always`), `oversight` (label **«Сводка»**) |
| `:233-240` | `TAB_SECTION_ORDER` (21) — порядок секций матрицы |
| `:244-245` | `NAV_GROUP_ORDER = ['modules','ai','permsoc']`, `NAV_GROUP_TITLES` — зеркало backend (тест паритета) |
| `:310-319` | `NAV_ITEMS` — **ровно 6**: status/how/modules/ai/permsoc/access |
| `:324-372` | `HUBS` — `#/ai` (8 карточек, включая «Память», «Лор чата», «Участники и отношения», «Личность»), `#/access` (3) |
| `:377-425` | `MODULES` (13 карточек с `toggleKey`) — **не трогать состав** |
| `:431-621` | `PROVIDER_BLOCKS` — **не трогать** |
| `:690-724` | `ROUTE_TO_TAB` |
| `:725-736` | `TAB_TO_ROUTE` |
| `:737` | `ROOT_ROUTES` |
| `:740-748` | `ROUTE_ALIAS` (legacy → канон) |
| `:749-759` | `ROUTE_PARENT` |
| `:762-781` | `normalizeRoute/routeToTab/tabToRoute/routeParent/routeDepth` |
| `:785-791` | `hubVisible(route, canViewTab)` |
| `:1204-1218` | computed `navItems` (фильтр по правам) |
| `:1219-1229` | computed `activeNav` |
| `:1230-1239` | computed `hubCards` |
| `:2630-2650` | `uiFlag(name)` (default **true**) + `_flagTabHidden(tabId)` |
| `:3033-3088` | `applyRoute(rawHash)` — ROUTE_ALIAS, RBAC, kill-switch, replaceState |
| `:3089-3105` | `navigateTo/openTab/navTo` |
| `:4329+` | `canViewTab(tabId)` — `always` для status/info |
| `:5675-5690` | matrix grouping по `it.nav / it.nav_order / it.nav_title` |
| **F0-слой сохранения (не ломать):** | |
| `:1656-1671` | computed `saveState` (`loading\|saving\|error\|conflict\|dirty\|clean`) + `stickyFieldFailed(key)` |
| `:5148-5165` | `notify(operationId, result, items)` — один итог на операцию |
| `:5201-5290` | `persistItems(items, opts)` — **единственный** write-path (guard in-flight, scope-split, 409-recovery) |
| `:8127-8131` | computed `saveState` внутри `<sticky-save>` (читает root, не дублирует) |
| `:8132+` | `stateLabel` (без мёртвой ветки `saved`) |

### 3.3. Разметка/CSS (после F0)
- `web/index.html:26` — `.app-shell`; `:29-124` — `.main-header` (scope-dropdown `:47-89`, identity `:95-111`, **`.navbar-band` :115-123**); `:3240` — `<footer class="sticky-save">` (F0); `:3517` — `.toast-wrap` (F0); `app.js` — синхронный `<script src="/web/app.js?v=__APP_VERSION__">` в конце body.
- `web/static/app.css:248-273` — `.navbar-band/.nav-link/.nav-label`; `:319-343` — `.scope-*`; `:562` — `.toast-wrap` (F0; safe-area — правка F0); `:679-698` — `.app-shell`/`.scroll-area`/`@media (max-width:768px)`; `:918-1002` — `.sticky-save` + `[data-save-state="error|conflict"]` (F0); safe-area TG — блок `max(env, --tg-*-safe-area-*)`.
- `web/static/telegram-init.js` (18 строк) — только ready/expand/цвета; BackButton/safe-area **не** обрабатываются.

### 3.4. Доставка UI-флагов и права (после F0)
- `web/api/routes.py:321-375` — `GET /api/me` → `ui_flags` (только bool): `TOKEN_FLOW_NODEFLOW_ENABLED` (`:352`), `IMAGE_MODULE_CARD_ENABLED`, `PROMPTS_UI_V2_ENABLED`, `BYOK_IMAGE_KEY_ENABLED`, `DOSSIER_LIVE_FEED_ENABLED`, `ALIASES_KEYSVALUE_RENDER_ENABLED`. **F1 добавляет сюда `IA_V2_ENABLED`.** Паттерн env-only `ClassVar` — `config/settings.py` (блок 10.24-флагов; F0-флаги `DB_LOCK_RESILIENCE_ENABLED`/`ANTICLICHE_MAX_*` — там же).
- `web/api/access.py:332-366` — матрица отдаёт `nav/nav_title/nav_order` из `tab_nav`/`NAV_ORDER`/`NAV_TITLES`; авто-подхватит новый раздел.
- `web/app.js:4329+` `canViewTab`: `status/info` — `always` (всем); остальное по секциям RBAC.

### 3.5. Слой сохранения после F0 — обязателен к переиспользованию (ARCHITECTURE.md §52)
F0 (Merge) ввела в `web/app.js` **единый контракт сохранения**, который F1 **обязан** переиспользовать, а не обходить:
- **`persistItems(items, opts)`** (`:5201`) — единственный write-path; guard in-flight по ключу, scope-split chat/global, обязательный `updated_at` для chat, 409-recovery. Любая новая форма/редактор F1 обязаны сохранять через него.
- **`saveState`** (root computed, `:1659`; `sticky-save`-зеркало `:8127`) — `loading|saving|error|conflict|dirty|clean`; F1 **не вводит** параллельные флаги состояния формы.
- **`notify(operationId, result, items)`** (`:5148`) + `toast` — один итог на операцию, `err>warn>ok`, очередь ≤3, safe-area; F1 **не шлёт** несколько тостов на одно действие и не дублирует дедуп.
- **Per-field ошибки** — `stickyFieldFailed(key)` (`:1669`) + `[data-save-state]` (`app.css:1001`).
- Правило при конфликте интересов: **приоритет — сохранить контракт F0** (ARCHITECTURE.md §52.6); F1 не «оптимизирует» и не переписывает `persistItems`/`saveState`/`notify`. Любое расширение — аддитивно и с зелёными F0-тестами (`tests/test_save_state_machine_round1025.py`, `tests/js/round1025_save_state_test.js`).

### 3.6. Маркер-тесты, которые сейчас фиксируют СТАРУЮ IA (подлежат SUPERSEDE, см. §8)
| Файл | Что фиксирует |
|---|---|
| `tests/test_frontend_tab_mapping.py:62-72` | `NAV_ORDER == ("modules","ai","permsoc")`; `tab_nav(TAB_CHAT_LORE)=="ai"` |
| `tests/test_frontend_tab_mapping.py:273-277` | `"sidebar" not in HTML` |
| `tests/test_webapp_nav_disclosure_ui.py:24-34` | `menu: 'ai'` и `sidebar` отсутствует |
| `tests/test_round106_ia_smoke.py:95-111` | `sidebar`/`MENU_ORDER` отсутствуют |
| `tests/test_webapp_parity_smoke.py:19-26,113-116` | `REFERENCE_SECTIONS` — ровно 6 |
| `tests/test_webapp_hubs_matrix_ui.py:14-20` | 6 nav + `navTo('#/oversight')` |
| `tests/test_webapp_round1020_ui.py:53-65` | 6 nav-пунктов |
| `tests/test_webapp_ui_rework_round1020.py:194-199` | 6 nav-пунктов |
| `tests/js/routing_test.js:331-339` | `navItems == ['status','how','modules','ai','permsoc','access']` |
| `tests/js/round1020_ui_test.js:94-97` | 6 nav-пунктов |
| `tests/js/round1021_ui_audit_test.js:229-236` | `navCount == 6` |
| `tests/test_webapp_round108_ui.py:46-64` | `label: 'Сводка'`, `#/oversight` |
| `tests/test_webapp_back_button.py:37-46` | membership старых маршрутов (остаются валидными) |

---

## 4. Целевое состояние

### 4.1. Дерево IA и hash-маршруты

```
ПУБЛИЧНЫЕ (всем)
  #/                         Статус        tab=status      [стартовая, always]
    #/oversight              Аналитика     tab=oversight   (открывается из Статуса)
  #/how                      Справка       tab=info        [always]

АДМИНИСТРАТИВНЫЕ (по правам)
  #/modules                  Модули        tab=modules     (витрина 11 модулей)
    #/modules/budgets        Бюджеты       tab=mod_budgets
    #/modules/images         Генерация изображений  tab=mod_images   [kill-switch]
    (workspace модулей §46 — F5)
  #/ai                       ИИ            tab=llm_providers  (hub)
    #/ai/llm                 Модели и подключения   tab=llm_providers
    #/ai/prompts             Библиотека промптов    tab=prompts
    #/ai/smart-cache         Умный кэш              tab=smart_cache
    #/ai/names               Имена и алиасы         tab=people_names
    #/ai/persona             Личность и стиль       tab=persona (special-screen)
  #/memory                   Память        tab=memory_rag  (hub)   ← НОВЫЙ РАЗДЕЛ
    #/memory/rag             Память и RAG           tab=memory_rag
    #/memory/lore            Лор чата               tab=chat_lore
    #/memory/relations       Участники и отношения  tab=relations
  #/access                   Доступы       tab=access      (hub)
    #/access/roles           Матрица ролей
    #/access/local           Локальные админы
    #/access/admins          Роли

ЛОКАЛЬНОЕ ПРОСТРАНСТВО (по правам)
  #/permsoc                  PERMsoc       tab=permsoc

LEGACY-АЛИАСЫ (не 404, ведут в новый дом)
  #/ai/memory    → #/memory
  #/ai/lore      → #/memory/lore
  #/ai/relations → #/memory/relations
  #/ai/limits → #/ai ; #/ai/sleep → #/modules ; #/ai/nostalgia → #/modules
  #/modules/{features,switches,reactions,custom} → #/modules
```

Правила:
- **Одна главная.** Статус — единственная «главная» (`#/`). Отдельного «Обзора» **нет** (§4).
- **«Сводка» → «Аналитика»** — меняется **только label**; канонический hash-ключ **`#/oversight` утверждён владельцем** (UPD §8.1 — дублирующую страницу не создавать); alt `#/analytics` **не вводим**. Открывается карточкой из Статуса (уже так).
- **«Профиль» — существующий блок** Telegram-пользователя/администратора (identity в header), **не новый экран** (UPD §8.2); не путать с «Личностью» бота (`#/ai/persona`).
- **Вложенные страницы** показывают текущий раздел и понятный путь назад (UPD §8.4): breadcrumb-заголовок раздела + родительский hash (`ROUTE_PARENT`) + TMA `BackButton`.
- **PERMsoc остаётся локальным** и в sidebar — отдельным нижним пунктом; в глобальные настройки не переносится (§4/§60).
- **ИИ не удаляется** и не превращается в свалку: память/лор/отношения уходят в «Память»; имена и умный кэш остаются в «ИИ» (§47).
- Неизвестный/мусорный hash → `#/` без падения (`normalizeRoute` возвращает `null` → `initialRoute`).

### 4.2. Desktop shell (§6, ≥1200 px)
```
┌──────────────┬─────────────────────────────────────────────┐
│ Sidebar ~232 │ Header ~64 (заголовок + селектор области F3) │
│  Статус      ├─────────────────────────────────────────────┤
│  Справка     │                                             │
│  ─────────   │   Контент (формы 1200–1440; графики шире;   │
│  Модули      │   textarea не растягивать на 2560)          │
│  ИИ          │                                             │
│  Память      │                                             │
│  Доступы     │                                             │
│              │                                             │
│  ─────────   │                                             │
│  PERMsoc     │                                             │
└──────────────┴─────────────────────────────────────────────┘
```
Селектор области — в header (детали/реализация — F3 §5).

### 4.3. Mobile shell (§7, <768 px)
```
Компактный header (заголовок страницы)
Селектор области ПОД заголовком (F3)
Контент — одна колонка
─────────────────────────────
Нижняя навигация:
  Админ:     Статус | Модули | ИИ | Ещё
  Пользователь: Статус | Справка
Меню «Ещё»: Справка · Память · Доступы · PERMsoc · Профиль
```
- **Горизонтальной полосы из 7 вкладок нет** (ТЗ прямо запрещает).
- Разделы без прав скрыты; touch-цель ≥44×44; сложные редакторы — отдельными экранами.
- Учитываем `BackButton`, `viewportStableHeight`, `safeAreaInset`, `contentSafeAreaInset`.

### 4.4. Диапазоны адаптивности (§70)
`320–767 mobile` · `768–991 tablet` · `992–1199 compact desktop` · `≥1200 desktop`.
Grid/Flexbox; `container queries` там, где поведение зависит от ширины **компонента** (карточки модулей, панель быстрых module-переключателей, матрица). Никакого горизонтального скролла **страницы**; переключатели не обрезаются.

**Навигационная модель по диапазонам (UPD §8.3):**
| Диапазон | Навигация |
|---|---|
| 320–767 mobile | компактный header + **нижняя навигация из 4** (админ: Статус/Модули/ИИ/Ещё; пользователь: Статус/Справка), «Ещё» — шторка |
| 768–991 tablet | **без постоянного sidebar** — компактная навигация/кнопка **drawer**; селектор области легкодоступен |
| 992–1199 compact desktop | **без постоянного sidebar** — drawer либо компактная полоса; контент шире |
| ≥1200 desktop | постоянный **sidebar ≈232 px** + header ≈64 px |

Правило: постоянный sidebar появляется **строго с 1200 px**; в 768–1199 — временная (drawer/компакт), состояние не персистится как «включённый режим».

---

## 5. Точные точки изменения в коде

### 5.1. Бэкенд — `services/param_catalog.py` (nav-метаданные, Δ ParamSpec/GROUPS = 0)
| Якорь | Изменение |
|---|---|
| `:2030` рядом | Добавить `NAV_MEMORY = "memory"` |
| `:2033-2037` | `NAV_TITLES[NAV_MEMORY] = "Память"` |
| `:2039` | `NAV_ORDER = (NAV_MODULES, NAV_AI, NAV_MEMORY, NAV_PERMSOC)` |
| `:2061,2064,2065` | `TAB_MEMORY_RAG`, `TAB_RELATIONS`, `TAB_CHAT_LORE`: `NAV_AI → NAV_MEMORY` |
| Остальное | **не трогать** (TAB_RULES, GROUPS, REGISTRY, дефолты) |

Инвариант: `set(TAB_NAV) == set(CONFIG_TAB_TITLES)` (21) и `set(TAB_NAV.values()) == set(NAV_ORDER)` — сохраняются. **F0 `param_catalog.py` не трогала** — якоря актуальны; `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418` остаются неизменными.

### 5.2. `config/settings.py`
Добавить env-only `ClassVar` рядом с другими env-only kill-switch’ами: блок 10.24-UI-флагов (`:619-661`) и блок F0 (`DB_LOCK_RESILIENCE_ENABLED`/`ANTICLICHE_MAX_*`, `:986-998`):
```python
# Раунд 10.25 (F1, ADR-1025-1): env-only ClassVar kill-switch новой IA/app-shell.
# default ON, Δ каталога = 0 (в param_catalog НЕ входит). Доставка —
# GET /api/me.ui_flags (ADR-1024-13). OFF → прежний navbar байт-в-байт.
# ВРЕМЕННЫЙ механизм отката (UPD §9.5) — не постоянная вторая архитектура.
IA_V2_ENABLED: ClassVar[bool] = _env_bool("IA_V2_ENABLED", True)
```

### 5.3. `web/api/routes.py`
`/api/me.ui_flags` (`:351-374`) — аддитивно `"IA_V2_ENABLED": bool(settings.IA_V2_ENABLED)`. Наружу — только bool (R16/R17). Не трогать существующие ключи (F0-инвариант).

### 5.4. `web/app.js`
| Якорь | Изменение |
|---|---|
| `:42-225` `TABS` | `memory_rag`/`chat_lore`/`relations`: `menu:'ai' → menu:'memory'`; `oversight` label `'Сводка' → 'Аналитика'` |
| `:218-225` | `status` — помечаем как стартовую (`home`); Убедиться, что `#/` → `status` |
| `:244-245` | `NAV_GROUP_ORDER = ['modules','ai','memory','permsoc']`; `NAV_GROUP_TITLES` + `memory:'Память'` |
| `:310-319` | `NAV_ITEMS` (legacy, **не трогать**) + новый `NAV_ITEMS_V2` (7: status/how/modules/ai/memory/access/permsoc) с полем `group: 'public'\|'admin'\|'local'` |
| `:324-372` | `HUBS` (legacy, **не трогать**) + `HUBS_V2`: `#/ai` без memory/lore/relations; новый `#/memory` (3 карточки) |
| `:690-724` | `ROUTE_TO_TAB` + `'#/memory'`, `'#/memory/rag'`, `'#/memory/lore'`, `'#/memory/relations'` |
| `:725-736` | `TAB_TO_ROUTE`: `memory_rag:'#/memory/rag'`, `chat_lore:'#/memory/lore'`, `relations:'#/memory/relations'` |
| `:737` | `ROOT_ROUTES` + `'#/memory'` |
| `:740-748` | `ROUTE_ALIAS` + `#/ai/{memory,lore,relations}` → новые |
| `:749-759` | `ROUTE_PARENT` + новые подмаршруты `#/memory/*` → `#/memory` |
| `:1204-1218` | computed `navItems`: ветвление по `this.iaV2` (V2-набор vs legacy) |
| `:1219-1229` | computed `activeNav` + ветка `#/memory` |
| `:1230-1239` | computed `hubCards`: выбор `HUBS_V2`/`HUBS` по `iaV2` |
| новое | computed `iaV2` → `this.uiFlag('IA_V2_ENABLED')`; `isMobileShell`; `isDrawerOpen`; `bottomNavItems` (ровно 4); `mobileMoreItems`; `sidebarItems`; `breadcrumb` (текущий раздел + родитель) |
| `:2630-2650` | `uiFlag` не меняем (default ON уже корректен); `_flagTabHidden` — как есть |
| `:3033-3088` | `applyRoute`: учесть новые алиасы + breadcrumb; kill-switch ветки для вкладок — как есть |
| `:4329+` `canViewTab` | `status/info` всегда; `memory` — по hub-видимости |
| **F0-слой — НЕ ТРОГАТЬ** | `persistItems` (`:5201`), `saveState` (`:1659`), `notify` (`:5148`), `stickyFieldFailed` (`:1669`) — только **читать/переиспользовать**. Новые формы/страницы F1 сохраняют через `persistItems`, показывают состояние через `saveState`, уведомляют через `notify`. Запрещено: параллельные `saving`-флаги, прямые `toast()` на операцию, обход `persistItems` |

**Критично:** legacy-константы `NAV_ITEMS`/`HUBS` остаются литерально неизменными — это гарант «OFF байт-в-байт».

### 5.5. `web/index.html`
- `:26` `.app-shell` — добавить класс-состояние shell (`shell-desktop`/`shell-compact`/`shell-mobile`, от breakpoint/`isMobileShell`).
- `:29-124` header — разделить заголовок/селектор/identity; добавить **breadcrumb** (текущий раздел + путь назад на вложенных).
- Добавить `<aside class="app-sidebar">` **строго ≥1200 px** с `sidebarItems` + группой `local` (PERMsoc) внизу; для **768–1199** — кнопка **drawer** (`isDrawerOpen`) с тем же составом (без постоянного sidebar).
- Добавить `<nav class="bottom-nav">` (только <768 px) с `bottomNavItems` (**ровно 4**) + шторку «Ещё» (`mobileMoreItems`: Справка/Память/Доступы/PERMsoc/Профиль); «Профиль» ссылается на **существующий** identity-блок.
- Сохранить `.navbar-band` для **legacy-режима** (рендерится только при `!iaV2`).
- **F0-разметку не ломать:** `<sticky-save>` (`:3240`) и `.toast-wrap` (`:3517`) остаются; новые экраны используют те же компоненты.
- «Справка»: desktop — двухколоночный layout (оглавление + контент, якоря); mobile — поиск/оглавление/текст. Контент/стиль не меняем.
- «Доступы»: desktop — существующая матрица; mobile — последовательный редактор ролей (без горизонтальной прокрутки).

### 5.6. `web/static/app.css`
- `:248-273` — `.navbar-band` оставить как legacy-стиль.
- Новые: `.app-sidebar` (≈232 px, sticky), `.bottom-nav` (fixed, safe-area), `.shell-grid`.
- `@media (min-width:1200px)` — двухколоночный shell; `@media (max-width:767px)` — bottom-nav + одна колонка; `:348/:351` — обновить адаптив.
- `container-type: inline-size` + `@container` для компонент-зависимых раскладок.
- Никакого `overflow-x` страницы; `env(safe-area-inset-*)`/TG-переменные — как в `:686-690`.

### 5.7. `web/static/telegram-init.js`
Добавить: `BackButton.onClick/offClick/show/hide`, `viewportStableHeight` → CSS-переменная, прокидывание `safeAreaInset`/`contentSafeAreaInset` в `--tg-*`. CSP-safe, без inline.

---

## 6. Контракты

### 6.1. API — новых эндпоинтов НЕТ
| Эндпоинт | Изменение | Инвариант |
|---|---|---|
| `GET /api/me` | + `ui_flags.IA_V2_ENABLED: bool` | R16 аддитивно; R17 только bool |
| `GET /api/access/param_permissions` (`web/api/access.py:332`) | авто: `nav` `chat_lore/relations/memory_rag` → `"memory"`, `nav_title="Память"`, `nav_order` пересчитывается | Контракт полей неизменен |
| `GET/POST /api/config*` | **без изменений** | сохранение значений 1:1 |
| Прочие `/api/*` | **без изменений** | — |

### 6.2. Данные
- **Нет миграций**: ни SQLite `user_version`, ни PG DDL.
- Значения глобальные/чатовые/ЛС, overrides, модели, ключи, промпты, словари, права, PERMsoc — читаются/пишутся теми же путями.

### 6.3. Роутинг-контракт
- `routeToTab`/`tabToRoute`/`routeParent`/`routeDepth` — чистые функции (покрыты `test_webapp_back_button.py`).
- Каждый новый маршрут обязан присутствовать в `ROUTE_TO_TAB` **и** (для вложенных) в `ROUTE_PARENT`; TAB_TO_ROUTE — обратный.
- Legacy-маршруты остаются в `ROUTE_TO_TAB` (валидные) **и** дублируются в `ROUTE_ALIAS` (канон через `replaceState`).
- Deeplinks стабильны: раздел, подстраница, `#/memory/*`.

### 6.4. UI-флаг
- `IA_V2_ENABLED` — только `ClassVar` (env), вне `param_catalog`; доставка через `ui_flags`; на фронте `uiFlag()` c default `true`.
- OFF-поведение: `navItems`/`hubCards`/разметка возвращают **legacy-набор**; `.navbar-band` рендерится как сейчас; sidebar/bottom-nav/drawer не появляются.
- **Статус механизма (UPD §9.5):** `IA_V2_ENABLED` — **временный** механизм отката F1, **не** постоянная «вторая архитектура». После стабилизации legacy-константы (`NAV_ITEMS`/`HUBS`/`.navbar-band`) и сам флаг удаляются отдельной задачей (post-Epic-1); в spec фиксируется как техдолг, не как долговременный контракт.
- Возврат ручки: env `IA_V2_ENABLED=true` **или** `git revert`; точка отката — T-2388 (бэкап + tag + `.env.bak`; `.env` вне git, секреты не выводить).

---

## 7. Инварианты сохранности (§1/§79/§116)

1. **Ни один параметр не потерян**: `REGISTRY 459`, `GROUPS 98`, `_TAB_BY_GROUP 96`, `TAB_RULES 21`, `Settings fields 418`, набор `pg_key` и `group_tab` — **неизменны** (Δ=0).
2. **Ни одно значение не переписано**: UI не пишет в БД при открытии форм; никаких новых дефолтов/скрытых миграций (§1).
3. **Технические ключи не переименованы**; `null/0/-1/""` сохраняют смысл.
4. **Локальное не перезаписывается глобальным**; смена scope не переносит черновики (F3 логика; F1 не ломает существующие guard’ы `scopeEpoch`).
5. **Все существующие визуализации/виджеты Статуса сохранены И доступны** (граф связей, сон/бейджи, мониторинг интеллекта, убеждения, парадигмы, эволюция характера, живая лента досье, дерево LLM-вызовов, логи, метрики). **Работающие страницы не заменяются заглушками** (UPD §9.3).
6. **Логи остаются в нижней части Статуса**; отдельной технической страницы не создаём (§20).
7. **PERMsoc локальный**; в глобальные настройки не переносится.
8. **Справка**: тексты/стиль v5 не изменяются.
9. **RBAC-семантика не меняется**; права проверяет сервер.
10. **CSP/zero-build**: ни одного inline-скрипта/стиля, только self-host (`vue_mount_test.js`).
11. **Ответы API аддитивны** (R16); логи/скриншоты без секретов (R17).
12. **`plans/current_task.md` не коммитится**, секреты не цитируются (R17/R18).
13. **F0-контракт сохранения сохранён** (ARCHITECTURE.md §52): `persistItems`/`saveState`/`notify`/per-field/safe-area — переиспользуются без дублирования; F0-тесты зелёные (pytest **7946/0**, JS **19/19**); при конфликте интересов приоритет — F0.
14. **Генеральные переключатели модулей доступны** (UPD §9.1): быстрый toggle глобально/для чата; при отсутствии нового каталога F4 — **старый работающий каталог** сохраняется, не отключается.
15. **Единое каноническое состояние модуля** `scope_type+scope_id+module_id`, одна мутация на действие (UPD §9.2) — F1 не создаёт независимых boolean'ов; интеграция со `store` F4.
16. **Эпик 2 не затронут** (UPD §9.6): Саммари/роутинг моделей/обложка/Rich Message — без изменений.
17. **Nested-навигация:** на вложенных страницах виден текущий раздел и путь назад (UPD §8.4); TMA `BackButton` возвращает на родителя.

---

## 8. План атомарной миграции каталога и тестов

### 8.1. Принцип
Каталог-Δ = 0, поэтому «миграция каталога» = **изменение только nav-метаданных** + **атомарное** (одним коммитом с кодом) обновление маркер-эталонов. Разрыв коммитов ⟹ «подгонка эталонов» (Scanner 10.24 §2) — запрещено.

### 8.2. Что меняется / что остаётся
| Меняется | Остаётся неизменным |
|---|---|
| `NAV_ORDER`, `NAV_TITLES` (+memory), `TAB_NAV` (3 переноса) | `REGISTRY`, `GROUPS`, `ParamSpec`, дефолты `Settings` |
| `web/app.js` nav/HUBS/route-карты, labels | `TAB_RULES`, `TAB_SECTION_ORDER`, `MODULES`, `PROVIDER_BLOCKS`, `PERMSOC_OWNER_BLOCKS` |
| `ui_flags` (+1 bool) | `TAB_NAV` состав ключей (21), `pg_key` |
| shell-разметка/стили | API-эндпоинты и их схемы (кроме аддитивного поля) |

### 8.3. Атомарный набор коммитов (один PR/серия коммитов в одном цикле)
1. `services/param_catalog.py` (nav-метаданные) **одновременно** с `tests/test_frontend_tab_mapping.py`, `tests/test_param_catalog.py`, `tests/test_round106_ia_smoke.py`, `tests/test_webapp_parity_smoke.py`.
2. `config/settings.py` (`IA_V2_ENABLED`) + `web/api/routes.py` (`ui_flags`) + `tests/test_...` на флаг.
3. `web/app.js`/`index.html`/`app.css`/`telegram-init.js` **одновременно** с `tests/test_webapp_hubs_matrix_ui.py`, `tests/test_webapp_nav_disclosure_ui.py`, `tests/test_webapp_round1020_ui.py`, `tests/test_webapp_ui_rework_round1020.py`, `tests/test_webapp_round108_ui.py`, `tests/js/routing_test.js`, `tests/js/round1020_ui_test.js`, `tests/js/round1021_ui_audit_test.js`.
4. Новые тесты F1 (см. §8.5).
5. **Гарант F0-слоя:** F0-набор (`tests/test_save_state_machine_round1025.py`, `tests/test_anticliche_semantics_round1025.py`, `tests/test_db_lock_resilience_round1025.py`, `tests/js/round1025_save_state_test.js`) остаётся **зелёным** в каждом коммите F1 (baseline pytest 7946/0, JS 19/19). Изменения в `web/app.js` — только в зонах навигации/shell, не в `persistItems`/`saveState`/`notify`.

> **Расширение против `tasks.md` T-2393:** кроме 6 перечисленных там файлов, атомарно обновляются ещё **`test_webapp_parity_smoke.py`, `test_webapp_hubs_matrix_ui.py`, `test_webapp_round1020_ui.py`, `test_webapp_ui_rework_round1020.py`, `test_webapp_round108_ui.py`, `tests/js/round1020_ui_test.js`, `tests/js/round1021_ui_audit_test.js`** — они тоже пиннят «ровно 6 пунктов»/«sidebar отсутствует»/«Сводка». Иначе CI покраснеет.

### 8.4. Доказательство «ни один параметр не потерян»
1. **Заморозка до правок** (вход от F8): `tests/fixtures/round1025/catalog_baseline.json` — `sorted(REGISTRY.pg_key)`, `sorted(group.id)`, `{group_id: tab_id}`, счётчики.
2. **Новый тест** `tests/test_ia_inventory_round1025.py`:
   - `set(REGISTRY.pg_key) == baseline.keys` (равенство множеств, не размер);
   - `{g.id: group_tab(g.id) for g in GROUPS} == baseline.group_tab` (проверяет, что перенос nav **не** сменил вкладку-владельца группы);
   - `set(TABS)` ↔ `TAB_TO_ROUTE` ↔ `ROUTE_TO_TAB` — 100% покрытие (T-2402, «inventory ↔ IA-map»);
   - каждый `tab.id` из `TABS` достижим из `NAV_ITEMS_V2`/`HUBS_V2`/sidebar (нет «сирот»).
3. **A/B-конфигурации**: бэкап и сравнение до/после (§3 ТЗ) — по факту Δ DDL=0 и absence записи из UI, но фиксируем в отчёте F10.

### 8.5. Новые тесты (создаёт @Builder)
| Файл | Проверяет |
|---|---|
| `tests/test_ia_shell_round1025.py` | `NAV_ORDER`/`NAV_TITLES`; `TAB_NAV` переносы; `<aside class="app-sidebar">`/`bottom-nav` маркеры; `IA_V2_ENABLED` OFF/ON (computed `navItems` через JS-прогон); нет «Обзора» |
| `tests/test_ia_inventory_round1025.py` |覆盖率 «inventory ↔ IA-map»; никакой `pg_key`/группа не потерян |
| `tests/js/round1025_ia_routing_test.js` | новые маршруты/deeplink’и, legacy-алиасы, мусорный hash → `#/`, `navItems` V2 (7) и legacy (6) под флагом; `#/memory` hub |
| `tests/js/round1025_shell_breakpoints_test.js` | присутствие media `1200/768`, отсутствие 7-вкладочной полосы, `container-type` |

Обновляемые существующие тесты — см. §8.3 и таблицу §3.6.

---

## 9. Риски и их снятие

| # | Риск | Ур. | Снятие |
|---|---|---|---|
| R1 | SUPERSEDE маркер-тестов без атомарности → «подгонка эталонов» | High | Один коммит на слой (§8.3); новый inventory-тест сравнивает множества, а не размеры |
| R2 | Потеря экрана/параметра при переносе IA | Critical | Каталог-Δ=0; `test_ia_inventory_round1025`; карта «старый→новый экран» (T-2409) |
| R3 | Мобильный скролл/обрезание переключателей | High | §70 + bottom-nav; `container queries`; реальный Playwright (F10) + `scrollWidth`/`getBoundingClientRect` |
| R4 | `IA_V2_ENABLED` декларативен | Medium | Тест OFF/ON; legacy-константы оставлены литерально; OFF проверяется рендером `navItems`/`hubCards` |
| R5 | «Объявлено готово, но визуально провалено» (10.20-UI-rework / 10.22 F2) | High | Обязательная реальная Chromium/Playwright-приёмка (T-2407/F10), скриншоты desktop/mobile; запрет закрывать по отчёту |
| R6 | Утечка секрета из `current_task.md` | Critical | Не коммитить (untracked), не цитировать (R17/R18); T-2388 |
| R7 | Поломка `#/ai`-хаба после выноса 3 карточек | Medium | `hubVisible` уже допускает частичные права; `#/ai` сохраняет llm/prompts/smart-cache/names/persona; тест hub-карточек |
| R8 | Матрица прав «поехала» из-за нового `nav_order` | Medium | Обновить backend-паритет-тесты атомарно; `nav_order` пересчитывается из `NAV_ORDER.index` детерминированно |
| R9 | CSP: новых inline-скриптов/стилей | High | Всё в `app.js`/`app.css`; `vue_mount_test.js` — гейт |
| R10 | Конфликт со ступенями общих файлов (F2/F3 идут после F1) | Medium | Порядок web: **F0 (готово) → F1 → F2 → F3 → … → F9 → F10**; F1 не оставляет заглушек «на потом» в общих файлах |
| R11 | Регресс F0-слоя сохранения при правках `web/app.js` (одинаковый файл) | Critical | F1 трогает **только** зоны nav/shell/route; `persistItems`/`saveState`/`notify`/per-field не переписываются; F0-тесты в каждом коммите (§8.3 п.5); приоритет — контракт F0 |
| R12 | Потеря быстрого доступа к генеральным переключателям модулей до готовности каталога F4 | High | UPD §9.1: сохранить старый работающий каталог/витрину 11 модулей как fallback; не подменять заглушкой; toggle глобально/для чата |
| R13 | Возврат аккордеонов промптов как основной навигации | Medium | UPD §7: снять как основной способ; основные редакторы доступны непосредственно; финал — F5 |
| R14 | Затронуты алгоритмы Саммари/роутинг/обложка/Rich Message | High | UPD §9.6: F1 не меняет эти зоны; проверка диффа — нет правок `summary_*`/`image_generation`/публикации |
| R15 | Дублирование состояния модуля (независимые boolean) вопреки §9.2 | High | Ключ `scope_type+scope_id+module_id`, одна мутация; согласование с F4; тест «одно действие = одна мутация» (F4/§72) |

---

## 10. Критерии готовности (DoD)

1. `#/` открывает Статус; Статус/Справка доступны всем; админ-разделы — по правам (§4/T-2394).
2. «Память» — отдельный nav-раздел; PERMsoc локален; «Сводка» → «Аналитика» из Статуса; раздел «ИИ» не удалён (§4/§47/T-2395).
3. Стабильные deeplinks (разделы/подстраницы/`#/memory/*`); мусорный hash → `#/` без падения (T-2396).
4. Desktop ≥1200: sidebar ≈232 + header ≈64 + контент; формы 1200–1440; без поломок на 1280/1440/1920/2560 (T-2397). **768–1199:** постоянного sidebar нет — drawer/компакт, селектор области доступен (UPD §8.3).
5. Mobile <768: компактный header, одна колонка, нижняя навигация **ровно из 4** (админ: Статус/Модули/ИИ/Ещё; пользователь: Статус/Справка), «Ещё» (Справка/**Память**/Доступы/PERMsoc/Профиль); **нет** горизонтальной полосы из 7 вкладок; touch ≥44×44 (T-2398/UPD §8.4).
6. TMA: BackButton возвращает на родителя; safe-area не обрезает (T-2399).
7. «Справка»: якоря на desktop/mobile; стиль v5 не изменён (T-2400).
8. «Доступы»: mobile-редактор без горизонтального скролла; права решает сервер (T-2401).
9. 100% покрытие «inventory ↔ IA-map»; ни один `ParamSpec`/группа не удалены (T-2402).
10. Виджеты Статуса смонтированы и доступны; логи доступны со Статуса (T-2403).
11. `IA_V2_ENABLED` OFF → legacy-navbar байт-в-байт; тест обоих состояний (T-2404).
12. §70 проверено на 320/390/768/992/1200/1440+ (T-2405).
13. JS-гейты зелёные, новых inline-скриптов нет (T-2406).
14. Реальная Playwright/Chromium-матрица §71 + скриншоты (T-2407 / F10).
15. @Reviewer Approved (T-2408).
16. Карта «старый→новый экран» + очистка бэкапа после утверждения (T-2409).
17. **Human Gate §8:** «Аналитика» = технический `#/oversight` + имя «Аналитика» из Статуса (дубля нет); «Профиль» — существующий блок (не новый экран); tablet — drawer/компакт.
18. **Генеральные переключатели модулей** доступны из каталога (глобально/для чата) без открытия страницы параметров; при отсутствии нового каталога F4 — старый работает (UPD §9.1).
19. **Единое каноническое состояние** `scope_type+scope_id+module_id`, одно действие = одна мутация; независимых boolean нет (UPD §9.2; согласовано с F4).
20. **Виджеты сохранены и доступны** (мониторинг интеллекта/убеждения/парадигмы/эволюция/сон/досье/дерево вызовов/граф/логи) — без заглушек (UPD §9.3).
21. **F0-слой сохранения не сломан:** `persistItems`/`saveState`/`notify` переиспользованы; pytest 7946/0 и JS 19/19 зелёные (ARCHITECTURE.md §52).
22. **Эпик 2 не тронут:** Саммари/роутинг/обложка/Rich Message без изменений (UPD §9.6); `IA_V2_ENABLED` помечен как временный (UPD §9.5).

---

## 11. План проверки F1 (кратко)

1. `node --check web/app.js`; `node tests/js/routing_test.js`; `node tests/js/vue_mount_test.js`; новые `tests/js/round1025_*`.
2. `pytest tests/test_param_catalog.py tests/test_frontend_tab_mapping.py tests/test_round106_ia_smoke.py tests/test_webapp_nav_disclosure_ui.py tests/test_webapp_parity_smoke.py tests/test_webapp_hubs_matrix_ui.py tests/test_ia_shell_round1025.py tests/test_ia_inventory_round1025.py`.
3. Полный `pytest` — без регрессий к baseline **после F0 = 7946/0**; JS-гейты **19/19**; **F0-тесты зелёные** (`test_save_state_machine_round1025.py`, `test_anticliche_semantics_round1025.py`, `test_db_lock_resilience_round1025.py`, `tests/js/round1025_save_state_test.js`).
4. Ручной/Playwright прогон §71 по разрешениям, `scrollWidth <= innerWidth + 1`, `getBoundingClientRect`, скриншоты.
5. Проверка OFF/ON (`IA_V2_ENABLED=false`) — navbar возвращается к 6 пунктам.

---

## 12. Соответствие задачам `tasks.md` (T-2388…T-2409)

| Задача | Где в spec | Комментарий |
|---|---|---|
| T-2388 | §8.4, §11 | точка отката/бэкап/baseline; `current_task.md` не коммитить |
| T-2389 | §3, §8.4 | read-only инвентаризация 26 TABS/6 NAV/хабы; вход для F8 |
| T-2390 | §4.1, §4.4 | карта IA + hash/deeplinks; отдельного «Обзора» нет |
| T-2391 | §5.1, §8.2 | `NAV_ORDER/TITLES/TAB_NAV`; переносы memory/lore/relations; Δ=0 |
| T-2392 | §5.4, §5.5 | `NAV_ITEMS_V2/TABS.menu/HUBS_V2`; hash-роутер без vue-router |
| T-2393 | §8.3, §8.5 | атомарные маркер-тесты + расширенный список файлов |
| T-2394 | §4.1, §10.1 | Статус — стартовая; публичные/приватные по правам |
| T-2395 | §4.1, §5.4 | Память отдельно; PERMsoc локален; Сводка→Аналитика; ИИ сохранён |
| T-2396 | §4.1, §6.3 | стабильные deeplinks; мусорный hash → `#/` |
| T-2397 | §4.2, §5.6 | desktop shell ≥1200 |
| T-2398 | §4.3, §5.5 | mobile shell <768, bottom-nav, «Ещё» |
| T-2399 | §5.7 | TMA BackButton/safe-area/viewport |
| T-2400 | §5.5, §10.7 | Справка desktop/mobile + якоря |
| T-2401 | §5.5, §10.8 | Доступы: матрица / мобильный последовательный редактор |
| T-2402 | §8.4, §8.5 | авто-тест покрытия inventory ↔ IA-map |
| T-2403 | §7.5, §7.6, §10.10 | виджеты Статуса; логи не выносим |
| T-2404 | §5.2, §5.3, §6.4, §9.R4 | kill-switch OFF/ON + тест |
| T-2405 | §4.4, §5.6 | адаптивность §70 |
| T-2406 | §11.1 | JS-гейты, CSP-safe |
| T-2407 | §11.4 | реальный Chromium/Playwright §71 |
| T-2408 | §10.15 | @Reviewer |
| T-2409 | §10.16 | карта «старые→новые экраны» + бэкап |

> **Полнота:** все 22 задачи (T-2388…T-2409) покрыты спецификацией. Специфичные для других фич детали (визуал F2, scope F3, store F4, workspace F5, Analytics F6, PERMsoc F7, реестр F8, secrets F9, приёмка F10, Статус-виджеты F11) вынесены в §2.2 с явными зависимостями.

---

## 13. Human Gate — решения владельца (UPD §7–§10, **ЗАКРЫТЫ**)

Владелец: **GO с уточнениями** (UPD §7). Ранее открытые 4 вопроса закрыты:

| # | Вопрос (1-я версия spec) | Решение владельца |
|---|---|---|
| 1 | Hash «Аналитики» | **Технический маршрут `#/oversight` сохранить**; пользовательское имя — **«Аналитика»**; переход из Статуса; **дублирующую страницу не создавать** (UPD §8.1). Альтернатива `#/analytics` — отклонена. |
| 2 | «Профиль» — новый экран? | **Существующий блок** Telegram-пользователя/администратора; новый экран не создавать; не путать с личностью бота (UPD §8.2). В mobile-«Ещё» «Профиль» ведёт на этот блок. |
| 3 | Tablet 768–1199 | **Без постоянного sidebar** — компактная навигация/drawer; полноценный sidebar **строго с 1200 px**; селектор области легкодоступен (UPD §8.3). |
| 4 | Mobile bottom-nav: ровно 4? | **Да, 4 пункта**: Статус/Модули/ИИ/Ещё; **«Память» — внутри «Ещё»**; на вложенных — текущий раздел + путь назад (UPD §8.4). |

Дополнительно закреплено: **разморозка меню** 10.20/10.21; **аккордеоны промптов** — не основная навигация (UPD §7); палитра `#090D17`/`#151B2A` + замедление градиента (зона F2, UPD §7); доп. требования §9 (генеральные переключатели, единое состояние, виджеты, права, откат, Эпик 2).

---

## 14. Ссылки
- `plans/features/ia-shell-navigation-round1025/tasks.md`, `adr-1025-1-ia-v2.md`
- `plans/round1025-architecture.md`
- `plans/features/parameter-registry-widget-map-round1025/` (F8, Wave 0 — инвентарь/бэкап)
- `plans/features/global-scope-selector-round1025/` (F3), `design-tokens-liquidglass-v2-round1025/` (F2), `status-showcase-dashboard-round1025/` (F11)
- `plans/reports/round1024_scanner_audit.md` §2, `round1023_scanner_audit.md` §2, `round1020_ui_rework_scanner_audit.md`
- **F0 (предшественник):** `plans/archive/f0-config-bugfixes-round1025/` (spec + ADR-1025-2/3/4/5), `plans/reports/f0-round1025-report.md`; контракт — **`plans/ARCHITECTURE.md` §9/§10/§52** (save-path/409, DB-lock, F0-инварианты)
- `plans/ARCHITECTURE.md`, `plans/archive/round1025-architecture.md` (карта раунда, после архивации) / `plans/round1025-architecture.md`, `plans/project.md`

---

## 15. Изменения относительно первой версии (Step 2 → Step 2 AMEND)

Первая версия spec/ADR была создана до блока UPD и до реализации F0. Дельта для @Builder:

| # | Что изменилось | Источник | Где в spec |
|---|---|---|---|
| 1 | **F0 — предшественник (Wave 0) уже реализован/задеплоен/заархивирован** (commit `3a91c84`). Baseline смещён: pytest 7911 → **7946/0**, JS **19/19** | F0 Merge | Шапка, §3.5, §8.3, §11 |
| 2 | **F1 обязан переиспользовать save-слой F0**: `persistItems`/`saveState`/`notify`/per-field/safe-area; никаких дублирующих состояний; при конфликте — приоритет F0 | F0 + задача | §1 правило 4, **§3.5**, §5.4, §7.13, §9.R11 |
| 3 | **Human Gate закрыт** (4 ответа владельца): Аналитика=`#/oversight`+имя «Аналитика»; Профиль=существующий блок; tablet 768–1199 без постоянного sidebar (drawer); mobile bottom = ровно 4, Память в «Ещё» | UPD §8 | §2.1, §4.1, §4.4, §13 |
| 4 | **Доп. требования §9 UPD:** генеральные переключатели модулей (сохранить доступ/старый каталог); единое каноническое состояние (`scope_type+scope_id+module_id`, одна мутация, согласование с F4); виджеты без заглушек; права; откат (`.env` вне git); `IA_V2_ENABLED` — **временный** механизм отката; **Эпик 2 не трогать** | UPD §9 | §1 правила 4–6, §2.1, §6.4, §7.13–17, §9.R12–15, §10.17–22 |
| 5 | **Аккордеоны промптов** сняты как **основной** способ навигации (финал — F5) | UPD §7 | §2.1, §2.2, §9.R13 |
| 6 | **Tablet 768–1199** явно отделён от desktop: постоянный sidebar только с 1200 px | UPD §8.3 | §4.4, §10.4 |
| 7 | **Точки изменения и якоря обновлены** под F0: `web/app.js` сдвинут (nav/shell-функции), добавлены якоря F0-слоя; §3.2/§3.3/§3.4/§5.4/§5.5 | F0 | §3, §5 |
| 8 | **Полный список маркер-тестов для атомарного обновления** зафиксирован (13 файлов) + гарант зелёных F0-тестов | F0 + ранее | §3.6, §8.3 |

> **Приоритеты для @Builder:** (1) сначала точка отката **T-2388**; (2) не трогать F0-слой сохранения; (3) атомарность код↔маркер-тесты; (4) не менять Эпик 2; (5) реальная Chromium-приёмка (не закрывать по отчёту).
