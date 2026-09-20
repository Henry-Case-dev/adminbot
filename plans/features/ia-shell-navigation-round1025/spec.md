# F1 — `ia-shell-navigation-round1025` · локальная спецификация

> **Раунд:** 10.25 (Эпик 1 «Liquid Glass Control Center»).
> **Мастер-ТЗ:** `plans/current_task.md` v6.0 (§0, §1, §4–§7, §68, §70, §71, §79, §116, §117). Файл — `untracked`, в git **не коммитить**, секреты не цитировать (R17/R18).
> **Задачи:** T-2388…T-2409 (`tasks.md` этой папки).
> **Тип:** информационная архитектура + app shell. Vue 3 global zero-build, self-host, CSP `script-src 'self'`.
> **Статус:** Step 2 @Architect — спроектировано. Реализация — @Builder (Step 4).
> **Связанные ADR:** `ADR-1025-1` (эта папка), `ADR-1024-13` (доставка `ui_flags`), `ADR-1018-6` (nav-матрица), `ADR-001` (route-driven окна «Доступов»), `ADR-1016-2` (self-host/CSP).

---

## 1. Цель

Заменить плоскую верхнюю полосу из 6 равнозначных пунктов на **иерархическую информационную архитектуру по §4** и **раздельные desktop/mobile app shell’ы (§6/§7)**, не потеряв **ни одного** существующего экрана, параметра, виджета, права или значения (§1/§79/§116).

F1 — **структурный каркас** раунда: он задаёт разделы, маршруты, раскладку shell, точки доступа к областям и оффлайн-контракт «новый ↔ старый интерфейс». Визуальный слой (стекло, токены) — F2; состав виджетов Статуса — F11; селектор области — F3; композиция «Памяти/Аналитики» — F6; PERMsoc — F7; состояния сохранения/секретов — F9.

**Три правила-ограничителя:**
1. **Δ ParamSpec / GROUPS = 0.** Меняются только **nav-метаданные** (`NAV_ORDER`, `NAV_TITLES`, `TAB_NAV`) и UI-структура. Ни один `pg_key`, группа, дефолт или смысл `null/0/-1/""` не меняется.
2. **Δ DDL = 0.** SQLite остаётся `v12`, новых PG-таблиц нет.
3. **Существующие API не меняются**; единственное аддитивное поле — `IA_V2_ENABLED` в уже существующем `GET /api/me.ui_flags`.

---

## 2. Границы

### 2.1. In scope (F1)
- Новая IA §4: Публичные (Статус, Справка), Административные (Модули, ИИ, **Память**, Доступы), Локальное (PERMsoc).
- Статус — стартовая страница (`#/`); Статус/Справка — всем, остальные — по правам.
- Выделение **Памяти** в отдельный админ-раздел (`memory_rag`, `chat_lore`, `relations` переезжают nav-разделом из «ИИ»).
- Переименование «Сводка» → **«Аналитика»** (label), открывается из Статуса; отдельной конкурирующей главной «Обзор» **не создаём**.
- Hash-роутер: новые маршруты/подмаршруты, deeplinks, алиасы трасс, fallback мусорного hash → `#/`.
- Desktop app shell ≥1200 px: sidebar ≈232 px + header ≈64 px + контент; ограничение форм 1200–1440 px.
- Mobile app shell <768 px: компактный header, одна колонка, **нижняя навигация** (админ: Статус/Модули/ИИ/Ещё; пользователь: Статус/Справка), меню «Ещё», сложные редакторы отдельными экранами.
- Адаптивность §70 (4 диапазона), отсутствие горизонтального скролла страницы, touch-таргеты ≥44×44.
- TMA-интеграция §7: `BackButton`, `viewportStableHeight`, `safeAreaInset`, `contentSafeAreaInset` (расширение `web/static/telegram-init.js`).
- «Справка» §68: desktop — оглавление + контент; mobile — поиск/оглавление/текст; якоря. **Стиль текста не менять.**
- «Доступы» §68: desktop — матрица прав; mobile — последовательный редактор ролей. Семантику RBAC не менять; права решает сервер.
- Виджеты Статуса остаются смонтированными и доступными (polная композиция — F11); логи **не выносим** на отдельную страницу.
- Kill-switch `IA_V2_ENABLED` (env-only `ClassVar`, default **ON**), OFF → прежний navbar байт-в-байт.
- Атомарное обновление маркер-тестов и каталога.

### 2.2. Out of scope (F1) — явно уезжает в другие фичи
| Тема | Владелец |
|---|---|
| Токены Liquid Glass, палитра, фон/градиент, преломление | **F2** `design-tokens-liquidglass-v2` |
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
| `:218-224` | `status`(`always`), `info`(`always`), `oversight` (label **«Сводка»**) |
| `:233-240` | `TAB_SECTION_ORDER` (21) — порядок секций матрицы |
| `:244-245` | `NAV_GROUP_ORDER = ['modules','ai','permsoc']`, `NAV_GROUP_TITLES` — зеркало backend (тест паритета) |
| `:310-319` | `NAV_ITEMS` — **ровно 6**: status/how/modules/ai/permsoc/access |
| `:324-372` | `HUBS` — `#/ai` (8 карточек, включая «Память», «Лор чата», «Участники и отношения», «Личность»), `#/access` (3) |
| `:690-724` | `ROUTE_TO_TAB` |
| `:725-736` | `TAB_TO_ROUTE` |
| `:737` | `ROOT_ROUTES` |
| `:740-748` | `ROUTE_ALIAS` (legacy → канон) |
| `:749-759` | `ROUTE_PARENT` |
| `:762-781` | `normalizeRoute/routeToTab/tabToRoute/routeParent/routeDepth` |
| `:785-791` | `hubVisible(route, canViewTab)` |
| `:1192-1206` | computed `navItems` (фильтр по правам) |
| `:1207-1216` | computed `activeNav` |
| `:1218-1227` | computed `hubCards` |
| `:2571-2589` | `uiFlag(name)` (default **true**) + `_flagTabHidden(tabId)` |
| `:2981-3027` | `applyRoute(route)` — ROUTE_ALIAS, RBAC, kill-switch, replaceState |
| `:3033-3049` | `navigateTo/openTab/navTo` |
| `:5315-5321` | matrix grouping по `it.nav / it.nav_order / it.nav_title` |

### 3.3. Разметка/CSS
- `web/index.html:26` — `.app-shell`; `:29-124` — `.main-header` (scope-dropdown `:47-89`, identity `:95-111`, **`.navbar-band` :115-123**); `:3614` — `app.js`.
- `web/static/app.css:248-273` — `.navbar-band/.nav-link/.nav-label`; `:319-343` — `.scope-*`; `:653-668` — `.app-shell`/`.scroll-area`/`.fullscreen-mode`; `:672-690` — safe-area.
- `web/static/telegram-init.js` (18 строк) — только ready/expand/цвета; BackButton/safe-area **не** обрабатываются.

### 3.4. Доставка UI-флагов и права
- `web/api/routes.py:316-375` — `GET /api/me` → `ui_flags` (только bool): `TOKEN_FLOW_NODEFLOW_ENABLED`, `IMAGE_MODULE_CARD_ENABLED`, `PROMPTS_UI_V2_ENABLED`, `BYOK_IMAGE_KEY_ENABLED`, `DOSSIER_LIVE_FEED_ENABLED`, `ALIASES_KEYSVALUE_RENDER_ENABLED`. Паттерн env-only `ClassVar` — `config/settings.py:619-661`.
- `web/api/access.py:332-366` — матрица отдаёт `nav/nav_title/nav_order` из `tab_nav`/`NAV_ORDER`/`NAV_TITLES`; авто-подхватит новый раздел.
- `web/app.js:1196` `canViewTab`: `status/info` — `always` (всем); остальное по секциям RBAC.

### 3.5. Маркер-тесты, которые сейчас фиксируют СТАРУЮ IA (подлежат SUPERSEDE, см. §8)
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
- **«Сводка» → «Аналитика»** — меняется **только label**; канонический hash-ключ `#/oversight` сохраняем ради стабильности deeplink’ов и не-ломания API/тестов. Открывается карточкой из Статуса (уже так).
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
Grid/Flexbox; `container queries` там, где поведение зависит от ширины **компонента** (карточки модулей, панель быстрыхmodule-переключателей, матрица). Никакого горизонтального скролла **страницы**; переключатели не обрезаются.

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

Инвариант: `set(TAB_NAV) == set(CONFIG_TAB_TITLES)` (21) и `set(TAB_NAV.values()) == set(NAV_ORDER)` — сохраняются.

### 5.2. `config/settings.py`
Добавить env-only `ClassVar` в блок 10.24-флагов (после `:661`):
```python
# Раунд 10.25 (F1, ADR-1025-1): env-only ClassVar kill-switch новой IA/app-shell.
# default ON, Δ каталога = 0 (в param_catalog НЕ входит). Доставка —
# GET /api/me.ui_flags (ADR-1024-13). OFF → прежний navbar байт-в-байт.
IA_V2_ENABLED: ClassVar[bool] = _env_bool("IA_V2_ENABLED", True)
```

### 5.3. `web/api/routes.py`
`/api/me.ui_flags` (`:347-374`) — аддитивно `"IA_V2_ENABLED": bool(settings.IA_V2_ENABLED)`. Наружу — только bool (R16/R17).

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
| `:1192-1206` | computed `navItems`: ветвление по `this.iaV2` (V2-набор vs legacy) |
| `:1207-1216` | computed `activeNav` + ветка `#/memory` |
| `:1218-1227` | computed `hubCards`: выбор `HUBS_V2`/`HUBS` по `iaV2` |
| новое | computed `iaV2` → `this.uiFlag('IA_V2_ENABLED')`; `isMobileShell`; `bottomNavItems`; `mobileMoreItems`; `sidebarItems` |
| `:2571-2580` | `uiFlag` не меняем (default ON уже корректен) |
| `:2981-3027` | `applyRoute`: учесть новые алиасы; kill-switch ветки для вкладок — как есть |
| `:4188` `canViewTab` | `status/info` всегда; `memory` — по hub-видимости |

**Критично:** legacy-константы `NAV_ITEMS`/`HUBS` остаются литерально неизменными — это гарант «OFF байт-в-байт».

### 5.5. `web/index.html`
- `:26` `.app-shell` — добавить класс-состояние shell (`shell-desktop`/`shell-mobile`, от `isMobileShell`).
- `:29-124` header — разделить заголовок/селектор/identity; добавить `<aside class="app-sidebar">` перед контентом (только ≥1200 px) с `sidebarItems` + группой `local` (PERMsoc) внизу.
- Добавить `<nav class="bottom-nav">` (только <768 px) с `bottomNavItems` + шторку «Ещё» (`mobileMoreItems`).
- Сохранить `.navbar-band` для **legacy-режима** (рендерится только при `!iaV2`).
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
- OFF-поведение: `navItems`/`hubCards`/разметка возвращают **legacy-набор**; `.navbar-band` рендерится как сейчас; sidebar/bottom-nav не появляются.
- Возврат ручки: env `IA_V2_ENABLED=true` **или** `git revert`.

---

## 7. Инварианты сохранности (§1/§79/§116)

1. **Ни один параметр не потерян**: `REGISTRY 459`, `GROUPS 98`, `_TAB_BY_GROUP 96`, `TAB_RULES 21`, `Settings fields 418`, набор `pg_key` и `group_tab` — **неизменны** (Δ=0).
2. **Ни одно значение не переписано**: UI не пишет в БД при открытии форм; никаких новых дефолтов/скрытых миграций (§1).
3. **Технические ключи не переименованы**; `null/0/-1/""` сохраняют смысл.
4. **Локальное не перезаписывается глобальным**; смена scope не переносит черновики (F3 логика; F1 не ломает существующие guard’ы `scopeEpoch`).
5. **Все существующие визуализации/виджеты Статуса сохранены** (граф, сон/бейджи, мониторинг интеллекта, лента досье, логи, метрики).
6. **Логи остаются в нижней части Статуса**; отдельной технической страницы не создаём (§20).
7. **PERMsoc локальный**; в глобальные настройки не переносится.
8. **Справка**: тексты/стиль v5 не изменяются.
9. **RBAC-семантика не меняется**; права проверяет сервер.
10. **CSP/zero-build**: ни одного inline-скрипта/стиля, только self-host (`vue_mount_test.js`).
11. **Ответы API аддитивны** (R16); логи/скриншоты без секретов (R17).
12. **`plans/current_task.md` не коммитится**, секреты не цитируются (R17/R18).

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

Обновляемые существующие тесты — см. §8.3 и таблицу §3.5.

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
| R10 | Конфликт со ступенями общих файлов (F2/F3 идут после F1) | Medium | Порядок web: F1 → F2 → F3 → … → F9 → F10; F1 не оставляет заглушек «на потом» в общих файлах |

---

## 10. Критерии готовности (DoD)

1. `#/` открывает Статус; Статус/Справка доступны всем; админ-разделы — по правам (§4/T-2394).
2. «Память» — отдельный nav-раздел; PERMsoc локален; «Сводка» → «Аналитика» из Статуса; раздел «ИИ» не удалён (§4/§47/T-2395).
3. Стабильные deeplinks (разделы/подстраницы/`#/memory/*`); мусорный hash → `#/` без падения (T-2396).
4. Desktop ≥1200: sidebar ≈232 + header ≈64 + контент; формы 1200–1440; без поломок на 1280/1440/1920/2560 (T-2397).
5. Mobile <768: компактный header, одна колонка, нижняя навигация админ/пользователь, «Ещё» (Справка/Память/Доступы/PERMsoc/Профиль); **нет** горизонтальной полосы из 7 вкладок; touch ≥44×44 (T-2398).
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

---

## 11. План проверки F1 (кратко)

1. `node --check web/app.js`; `node tests/js/routing_test.js`; `node tests/js/vue_mount_test.js`; новые `tests/js/round1025_*`.
2. `pytest tests/test_param_catalog.py tests/test_frontend_tab_mapping.py tests/test_round106_ia_smoke.py tests/test_webapp_nav_disclosure_ui.py tests/test_webapp_parity_smoke.py tests/test_webapp_hubs_matrix_ui.py tests/test_ia_shell_round1025.py tests/test_ia_inventory_round1025.py`.
3. Полный `pytest` — без регрессий к baseline **7911/0**.
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

## 13. Открытые вопросы к владельцу (Human Gate)

1. **Hash «Аналитики»:** оставляем каноническим `#/oversight` (label «Аналитика») — согласны? Альтернатива: ввести `#/analytics` как канон с алиасом `#/oversight`.
2. **PERMsoc в mobile-«Ещё»** присутствует по §7 — подтверждаете состав «Ещё» (Справка/Память/Доступы/PERMsoc/Профиль), включая «Профиль» как новый экран (или это существующий identity-блок)?
3. **Tablet 768–991:** sidebar не включаем до ≥1200 (только ≥1200 desktop), на 768–1199 — верхняя навигация/упрощённый shell. Подтверждаете?
4. **Кол-во пунктов в mobile-bottom-nav администратора** строго 4 (Статус/Модули/ИИ/Ещё) — не добавлять «Память» напрямую?

---

## 14. Ссылки
- `plans/features/ia-shell-navigation-round1025/tasks.md`, `adr-1025-1-ia-v2.md`
- `plans/round1025-architecture.md`
- `plans/features/parameter-registry-widget-map-round1025/` (F8, Wave 0 — инвентарь/бэкап)
- `plans/features/global-scope-selector-round1025/` (F3), `design-tokens-liquidglass-v2-round1025/` (F2), `status-showcase-dashboard-round1025/` (F11)
- `plans/reports/round1024_scanner_audit.md` §2, `round1023_scanner_audit.md` §2, `round1020_ui_rework_scanner_audit.md`
- `plans/ARCHITECTURE.md`, `plans/project.md`
