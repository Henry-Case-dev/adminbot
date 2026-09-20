# Spec: image-module-toggle-round1024 (F5)

> Раунд 10.24 (UPD2 п.3 + UPD3 №1) · P1 · каталог + UI/web · Владелец: F5
> Ступень `param_catalog.py`: **F7 (Part 1, влит) → F5 → F6**
> Ступень `web/**`: **2-я** (F3 → **F5** → F6 → F11 → F4 → F10)
> **ADR:** ADR-1024-9 (AMEND ADR-1023-5 §D5)
> **✅ Human Gate №1 — ЗАКРЫТ (UPD3 №1):** отдельный пункт «Модулей»; запрет
> `tma-menu-freeze` снят **только для этого пункта**.

## 1. Цель

Вынести управление генерацией изображений **отдельным пунктом в меню «Модули»**:
карточка «Генерация изображений» с **главным тумблером** включения/отключения,
**по умолчанию ВКЛ глобально**. Сейчас тумблер спрятан внутри карточки «Прямые
ответы» (`mod_direct`), а в витрине «Модулей» карточки нет.

## 2. Что уже есть (координаты)

| Что | Где |
|---|---|
| Ключ `IMAGE_GENERATION_MODULE_ENABLED` (group `flags_module_images`, default True) | `services/param_catalog.py:954-959` |
| Группа `flags_module_images` (category `flags`) | `services/param_catalog.py:329-330` |
| Группа приписана к `TAB_MOD_DIRECT` (**источник проблемы**) | `services/param_catalog.py:2056-2059` |
| Вкладки/титулы/nav | `services/param_catalog.py:1952-2040` (`TAB_*`, `CONFIG_TAB_TITLES`, `TAB_NAV`) |
| Витрина `MODULES` (12 карточек: 11 mod_* + «Бюджеты») | `web/app.js:353-393` |
| `TABS` (config-вкладки, `menu:'modules'`) | `web/app.js:53-135` |
| `TAB_SECTION_ORDER` (порядок секций матрицы прав) | `web/app.js:212-219` |
| `TAB_ICON` | `web/app.js:270-283` |
| Провайдер-блок изображений (адрес/модель/GET/ключ) | `web/app.js:539-551` (`PROVIDER_BLOCKS`) |
| Пин-тесты | `tests/test_frontend_tab_mapping.py`, `tests/test_round106_ia_smoke.py`, `tests/test_webapp_round1020_ui.py`, `tests/js/round1020_ui_rework_test.js` |

## 3. Требуемое поведение

### 3.1. Δ каталога (точно)

| Сущность | Δ |
|---|---|
| `REGISTRY` (ключи) | **0** — `IMAGE_GENERATION_MODULE_ENABLED` уже есть |
| `GROUPS` / mapped | **0** — группа `flags_module_images` уже есть |
| `_TAB_BY_GROUP` | **0** — группа меняет владельца-вкладку, число не растёт |
| `TAB_RULES` (config-вкладок) | **20 → 21** (+`mod_images`) |
| `CONFIG_TAB_TITLES` / `TAB_NAV` | +`mod_images` → «Генерация изображений», nav `modules` |
| Витрина `MODULES` (JS) | **12 → 13** |

Комбинированно с Part 1 F7: `REGISTRY 457→458`, `GROUPS 96→97`,
`_TAB_BY_GROUP 94→95`, config-вкладок **21**, витрина **13**.

**Конкретные правки `param_catalog.py`:**
1. Новая константа `TAB_MOD_IMAGES = "mod_images"` (рядом с `TAB_MOD_BUDGETS`).
2. `CONFIG_TAB_TITLES[TAB_MOD_IMAGES] = "Генерация изображений"`.
3. `TAB_NAV[TAB_MOD_IMAGES] = NAV_MODULES`.
4. В `TAB_MOD_DIRECT` **убрать** `flags_module_images` из frozenset `flags`.
5. Новый rule `(TAB_MOD_IMAGES, ((CATEGORY_FLAGS, frozenset({"flags_module_images"})),))`.
   Провайдер-настройки (`models_images`/`keys_images`) **остаются** на
   `TAB_LLM_PROVIDERS` — «один дом», без дублирования владения.

### 3.2. Frontend

1. `TABS`: новая запись **точно в формате регулярки пин-теста**
   `{ id: 'mod_images', icon: 'grid_view', label: 'Генерация изображений', type: 'config', menu: 'modules', sources: [{ category: 'flags', groups: ['flags_module_images'] }] }`,
   вставленная **после `mod_budgets`** (append-only, не ломает порядок существующих).
2. `TAB_SECTION_ORDER`: добавить `'mod_images'` после `'mod_budgets'`.
3. `TAB_ICON`: `mod_images: 'grid_view'` (существующая иконка из subset — **без**
   изменения шрифтового сабсета; см. ADR-1024-9, альтернатива `image` отклонена).
4. `MODULES`: карточка после «Бюджеты»
   `{ id: 'mod_images', title: 'Генерация изображений', subtitle: 'Рисунки по просьбе', icon: 'grid_view', toggleKey: 'flags.image_generation_module_enabled', tab: 'mod_images' }`.
5. Карточка **и вкладка** гейтятся `uiFlag('IMAGE_MODULE_CARD_ENABLED')`.
   OFF → карточка скрыта (`visibleModules`), вкладка недоступна:
   диплинк `#/modules/images` откатывается на витрину `#/modules`
   (`applyRoute`), активация вкладки блокируется (`setTab`). RBAC имеет
   **приоритет** над kill-switch: если нет права на вкладку — штатный отказ
   на `#/`, а не редирект на витрину. `visibleTabs` — computed, НЕ
   подключённый к разметке (в UI нет полосы вкладок), поэтому UI-гейтом не
   является (review iter2). Группа `flags_module_images` живёт ровно на
   одной вкладке (`mod_images`, «один дом»), поэтому при OFF главный тумблер
   в UI **недостижим** — возврат ручки: env-флаг ON либо `git revert`
   (review iter1: ранее ошибочно заявлялась достижимость через `mod_direct`).

### 3.3. Дефолт и разрешение

- `IMAGE_GENERATION_MODULE_ENABLED` default **True** (код-дефолт каталога).
- Разрешение: `chat → global → default(True)`. Per-chat override по умолчанию не
  сеем; отображать «ON» при отсутствии сохранённого значения.
- Переиспользовать существующий `_resolve_bool`-путь фичи (не дублировать логику).

### 3.4. Инвариант `tma-menu-freeze`

- Исключение — **ровно** один новый пункт «Генерация изображений». Порядок/состав
  остальных пунктов «Модулей», nav-разделы, «ИИ»/PERMsoc — не двигать.

## 4. Изменения по файлам

| Файл | Что |
|---|---|
| `services/param_catalog.py` | §3.1 (TAB_MOD_IMAGES, titles/nav, перенос группы, TAB_RULES) |
| `web/app.js` | TABS/MODULES/TAB_SECTION_ORDER/TAB_ICON; `uiFlag` |
| `config/settings.py` + `routes.me` | `IMAGE_MODULE_CARD_ENABLED` (enabler) |
| `tests/test_frontend_tab_mapping.py` | 20→21; ALL_TABS +`TAB_MOD_IMAGES`; `mod_direct` без images; новый `test_mod_images_composition`; counts 95/97/458; parity JS label |
| `tests/test_round106_ia_smoke.py` | `toggleKey == 11` → **12**; +«Генерация изображений» в titles |
| `tests/test_webapp_round1020_ui.py` | EXPECTED_TABS +`mod_images`; `len(mods) == 12` → **13** |
| `tests/js/round1020_ui_rework_test.js` | `expectedTabs` +`mod_images`; `modules.length 12 → 13` |
| `tests/test_budget_settings_round1019.py` | (smoke) при наличии pin — обновить |

## 5. Контракты

- **Вкладка:** `mod_images` — конфиг-вкладка, nav `modules`, ровно одна группа
  `flags_module_images`.
- **Каждая конфиг-группа ровно на одной вкладке** (аудит `_TAB_BY_GROUP`) — инвариант
  сохраняется; дублирования `flags_module_images` в `mod_direct` быть не должно.
- **Паритет Python ↔ JS:** `CONFIG_TAB_TITLES['mod_images'] == 'Генерация изображений'`
  == `TABS` label.
- **OFF-флаг тумблера реально отключает фичу** (существующий гейт модуля).

## 6. Тесты

- **Python:**
  - `tab_group_ids(TAB_MOD_IMAGES) == {"flags_module_images"}`;
  - `flags_module_images not in tab_group_ids(TAB_MOD_DIRECT)`;
  - `pc.tab_nav(TAB_MOD_IMAGES) == pc.NAV_MODULES`;
  - `len(pc.TAB_RULES) == 21`, `set(CONFIG_TAB_TITLES) == set(TAB_NAV) == ALL_TABS`;
  - counts `95/97/458` (после Part 1 F7);
  - `get("IMAGE_GENERATION_MODULE_ENABLED").value is True` / `resolve` default ON;
  - JS-паритет: `{ id: 'mod_images', icon: '...', label: 'Генерация изображений'`.
- **JS (`tests/js/round1024_image_module_test.js`):** карточка присутствует в
  `MODULES`, `toggleKey` корректен, `modules.length === 13`, `node --check`.
- **Гейт:** `tests/js/vue_mount_test.js` зелёный.

## 7. Риски

| # | Риск | Ур. | Митигация |
|---|---|---|---|
| R1 | menu-freeze нарушен за пределами одного пункта | Low | ADR-1024-9 явно ограничивает исключение |
| R2 | Δ каталога ломает пин-тесты/счётчики | High | обновить все 4 пина **в одном коммите** (§4) |
| R3 | Дублирование тумблера (останется в `mod_direct`) | Medium | явный тест `not in tab_group_ids(TAB_MOD_DIRECT)` |
| R4 | per-chat override перекроет глобальный ON | Low | тест разрешения `chat → global → default(True)` |
| R5 | Иконка вне font-subset | Low | переиспользуем `grid_view` (в subset), без правки шрифта |

## 8. Критерии приёмки

- В «Модулях» есть отдельная карточка «Генерация изображений» с рабочим тумблером.
- По умолчанию фича **включена глобально**; выключение реально отключает фичу.
- Тумблер **не дублируется** в «Прямых ответах».
- Пин-тесты обновлены одним коммитом; pytest и JS-гейт зелёные.
- Порядок/состав остальных пунктов меню не изменён.

## 9. Флаг и откат

- `IMAGE_MODULE_CARD_ENABLED` (env-only `ClassVar`, **default ON**) через `ui_flags`;
  OFF → карточка скрыта.
- Откат: флаг OFF / возврат `flags_module_images` в `TAB_MOD_DIRECT` / `git revert`.
  Δ DDL = 0.
