# Spec F6 — `role-matrix-settings-actualization` (Матрица ролей = фактическая структура разделов мини-аппа)

> **Раунд:** 10.18 (Step 2 @Architect, **итерация 2 после human-gate**, 15.09.2026). **Тип:** backend/access + frontend. **Приоритет:** P2.
> **ADR:** `adr-1018-6-role-matrix-actualization.md` (обязателен).
> **Задачи:** T-1750…T-1757. **Сводит** Δ каталога всех фич. **Baseline:** HEAD `118a03c`; pytest 6007 passed; каталог 435/406/411/90/88/19.
> **Источник:** `plans/current_task.md` §5 (строки 89–90) + **UPD п.4** (строка 124).
> **Решение владельца (UPD п.4):** F6 эталон = **фактическая карта миниаппа** (`web/app.js`), подтверждено «как есть». Дополнительно (UPD п.2) F2 **не вводит флаги** → Δ каталога раунда сокращается (см. §5).

## 1. Контекст и цель

ТЗ §5 сформулировано кратко: «актуализировать в разделе Матрица ролей структуру настроек согласно тому как они реально распределены в разделах миниапп». Матрица (`GET /api/access/param_permissions` → `matrixSections()` в `web/app.js`) группирует **все** параметры каталога по 19 «секциям» = config-вкладкам (`TAB_RULES`/`CONFIG_TAB_TITLES`), но **не отражает фактическую иерархию мини-аппа** (navbar → hub → секция) и содержит расхождение подписей.

**Цель:** матрица = фактическое распределение настроек по разделам мини-аппа (единый источник с `web/app.js::TABS`/`NAV_ITEMS`/`HUBS`), RBAC-права согласованы, каталог-инвариант зафиксирован.

## 2. Фактическое распределение (определено из кода, а не угадано)

Источник — `web/app.js`:
- `NAV_ITEMS` (`:256-265`), 6 пунктов: `status` («Статус»), `how` («Справка»), `modules` («Модули»), `ai` («ИИ»), `permsoc` («PERMsoc»), `access` («Доступы»).
- `HUBS` (`:270-318`): `#/ai` — 7 config-карточек + special `#/ai/persona`; `#/access` — 3 карточки (Матрица ролей/Локальные админы/Роли).
- `MODULES` (`:323-357`), 11 карточек: `mod_summary…mod_checkup`, `mod_sleep`, `mod_nostalgia` (все `menu:'modules'`).
- `TABS` (`:18-180`): 19 config-вкладок с полем `menu` (`'modules'|'ai'|'permsoc'|'access'`).

Фактическая иерархия настроек (19 секций, 3 nav-родителя с настройками + группа «Прочее» — см. §3.1/ADR-1018-6 D4):

| Nav (факт) | Секции (tab_id) | TABS.label |
|---|---|---|
| **Модули** `#/modules` (витрина 11 модулей, окна) | `mod_summary, mod_direct, mod_factcheck, mod_search, mod_transcribe, mod_video_summary, mod_media_download, mod_web, mod_checkup, mod_sleep, mod_nostalgia` | Саммаризация, Прямые ответы, Фактчек, Поиск, Транскрипт голосовых и видео, Выжимка видео, Скачивание медиа, Веб-страницы, Диагностика, Сон, Ностальгия |
| **ИИ** `#/ai` (hub, 7 карточек + «Личность») | `llm_providers, prompts, memory_rag, smart_cache, people_names, relations, chat_lore` | LLM Провайдеры, Промпты, Память, Умный кэш, Имена, Участники и отношения, Лор чата |
| **PERMsoc** `#/permsoc` | `permsoc` | PERMsoc |
| **Доступы** `#/access` (без параметров каталога) | — (3 карточки: Матрица ролей/Локальные админы/Роли) | — |

**Найденный дрейф (конкретный):**
- `CONFIG_TAB_TITLES[TAB_PERMSOC]` = `"Функции PERMsoc"` (`services/param_catalog.py:1770`), тогда как фактическая подпись раздела мини-аппа = `"PERMsoc"` (`web/app.js:145` label, `NAV_ITEMS:261`). Матрица показывает устаревшую подпись.
- Матрица не отражает «родителя» (nav/hub): все 19 секций — плоский список.

Порядки `TAB_RULES` (`param_catalog.py:1773-1881`) и `TAB_SECTION_ORDER` (`web/app.js:188-194`) **совпадают** — дрейфа порядка нет.

## 3. Требуемое поведение

1. Матрица группируется/подписывается по фактической структуре мини-аппа: **nav → секция → группа → параметр**. Фактически рендерится **4** nav-группы: **3** из backend `NAV_ORDER` (`modules`/`ai`/`permsoc`) + **«Прочее»** (`it.nav || 'other'`, fallback-заголовок `'Прочее'`) для 5 категоризированных content-параметров с `tab=None` (`content.media_share_dir`, `content.media_public_base_url`, `content.info_how_it_works`, `content.intelligence_guide`, `content.no_key_reply`); content-параметры вне nav мини-аппа — осознанно (ADR-1018-6 D4).
2. Подписи секций совпадают с фактическими `TABS[].label` (исправить `permsoc`).
3. `param_permissions_list` отдаёт аддитивные `nav`, `nav_title`, `nav_order` (R16-safe).
4. RBAC-права табов/параметров согласованы, недостижимых прав нет.
5. Каталог-инвариант зафиксирован явными числами (ADR), пин-тесты обновлены.
6. UI мини-аппа рендерит матрицу по новой структуре; регресса разделов/адаптива нет.

## 4. Технический дизайн

### 4.1. Backend: единый источник nav-разметки (`services/param_catalog.py`)

Новые метаданные (Python, **не** REGISTRY-записи, catetory-счётчики не растут):
```python
NAV_MODULES, NAV_AI, NAV_PERMSOC = "modules", "ai", "permsoc"
NAV_TITLES: dict[str, str] = {"modules": "Модули", "ai": "ИИ", "permsoc": "PERMsoc"}
NAV_ORDER: tuple[str, ...] = ("modules", "ai", "permsoc")
# tab_id → nav (исчерпывающе, 19)
TAB_NAV: dict[str, str] = {
    TAB_MOD_SUMMARY: NAV_MODULES, TAB_MOD_DIRECT: NAV_MODULES,
    ...  # 11 mod_* → modules
    TAB_LLM_PROVIDERS: NAV_AI, TAB_PROMPTS: NAV_AI, TAB_MEMORY_RAG: NAV_AI,
    TAB_SMART_CACHE: NAV_AI, TAB_PEOPLE_NAMES: NAV_AI, TAB_RELATIONS: NAV_AI,
    TAB_CHAT_LORE: NAV_AI,
    TAB_PERMSOC: NAV_PERMSOC,
}
def tab_nav(tab_id: str) -> str | None: ...
```
Тест инварианта: каждый из 19 tab_id ∈ `TAB_NAV`; значения ⊆ `NAV_TITLES`.
**Исправить подпись:** `CONFIG_TAB_TITLES[TAB_PERMSOC] = "PERMsoc"`.

### 4.2. Backend: `web/api/access.py::param_permissions_list` (`:319-360`)

Аддитивно к текущему ответу (`tab/tab_title/group/group_title/group_order/category/title/secret`):
```python
nav = tab_nav(tab) if tab else None
matrix["nav"] = nav
matrix["nav_title"] = NAV_TITLES.get(nav) if nav else None
matrix["nav_order"] = NAV_ORDER.index(nav) if nav in NAV_ORDER else 999
```
Импортировать `tab_nav`/`NAV_TITLES`/`NAV_ORDER` из `services.param_catalog`. Контракт не ломается (аддитивность, R16).

### 4.3. Frontend (`web/app.js::matrixSections`, `:3617-3662`; `web/index.html:1315-1347`)

- Секции группировать по `nav` (fallback — текущий `TAB_SECTION_ORDER`): порядок `nav_order` → `TAB_SECTION_ORDER` внутри nav.
- Заголовки: `nav_title` (крупный) → `sec.title` (tab_title) → группа.
- Убрать зависимость только от `TAB_SECTION_ORDER` (оставить как fallback).
- Поиск/фильтр по ключу/названию сохранить; адаптив/аккордеоны — без регресса.
- **B4-info(a):** фактически рендерится **4** nav-группы: 3 из `NAV_ORDER` (`modules`/`ai`/`permsoc`) + «Прочее» (`it.nav || 'other'`, fallback-заголовок `'Прочее'`) для **5** content-параметров с `tab=None` (`content.media_share_dir`, `content.media_public_base_url`, `content.info_how_it_works`, `content.intelligence_guide`, `content.no_key_reply`). Content-параметры вне nav мини-аппа — осознанно, не «мёртвая» группа.
- **B4-4:** JS-константы `NAV_GROUP_ORDER`/`NAV_GROUP_TITLES` (`web/app.js:198-199`) закреплены parity-тестом с backend `NAV_ORDER`/`NAV_TITLES` (вариант «б» — минимально инвазивно).

### 4.4. RBAC-политика

- Новых секций/категорий RBAC **не вводится** (`known_sections()` без изменений).
- Матрица — только global admin (`access.py:328-330`); override — `PUT /api/access/param_permissions/{key}`.
- Проверить отсутствие «мёртвых» прав: каждый из 19 tab_id имеет ≥1 группу/параметр (кроме content-групп с `tab=None`).

## 5. Изменения схемы / каталога / env (санкционированный Δ)

- **DDL/SQL:** не требуется.
- **Каталог-инвариант (единый свод раунда, итерация 3 после реализации F5):**
  - `REGISTRY` **435 → 436** (только F1: `BETTERSTACK_HOST`; env-only infra). F6 сама — **Δ=0** записей.
  - F5 фича-флаг **не вводится** (UPD п.2/п.4, ADR-1018-5 D6) → Δ F5 = 0.
  - `GROUPS` **90 → 90**, `mapped` (`_TAB_BY_GROUP`) **88 → 88**, `TAB_RULES`/`CONFIG_TAB_TITLES` **19 → 19**.
  - `Settings` **406 → 406**; `categorized` (`param_permissions`) **411 → 411** (F6 не меняет состав).
  - Изменения F6 — **только текст подписи** `TAB_PERMSOC` («Функции PERMsoc» → «PERMsoc») + аддитивные метаданные `TAB_NAV`/`NAV_*` (Python, не записи каталога).
- **env:** не трогать.

### Свод Δ раунда 10.18 (для @Reviewer/@Scanner) — **итерация 3 (реализация)**
| Источник | REGISTRY | Settings | GROUPS | mapped | TAB_RULES |
|---|---|---|---|---|---|
| Baseline 10.17 | 435 | 406 | 90 | 88 | 19 |
| F1 | **+1** | 0 | 0 | 0 | 0 |
| F2 | **0** (флаги исключены — UPD п.2, базовая логика) | 0 | 0 | 0 | 0 |
| F3 | 0 (DDL `edges.fact_id` — не каталог) | 0 | 0 | 0 | 0 |
| F4 | 0 | 0 | 0 | 0 | 0 |
| F5 | **0** (фича-флаг **не вводится** — UPD п.2, ADR-1018-5 D6) | 0 | 0 | 0 | 0 |
| F6 | 0 | 0 | 0 | 0 | 0 |
| F7 (`settings-worker-sync`) | 0 | 0 | 0 | 0 | 0 |
| **Итог** | **436** | **406** | **90** | **88** | **19** |

`categorized` (`len(param_permissions.items)`) = **411** — не меняется.
Точные значения зафиксированы пин-тестами (`tests/test_frontend_tab_mapping.py::test_mapped_and_counts`, `tests/test_webapp_api.py::TestParamPermissionFlagsApi::test_param_permissions_matrix_metadata_and_coverage`).

## 6. Влияние на тесты

- `tests/test_frontend_tab_mapping.py`: `REGISTRY == 436` (после F1); `_TAB_BY_GROUP == 88`, `GROUPS == 90`, `TAB_RULES == 19` — без изменений; новый тест `TAB_NAV` (19 ключей, значения ⊆ NAV_TITLES).
- Пин-тесты `REGISTRY == 435` обновить → 436 (перечень в F1 §6).
- `tests/test_webapp_rbac_ui.py`/`test_access*.py`: аддитивные `nav/nav_title/nav_order` в `/api/access/param_permissions`; 403 для не-global-admin не меняется.
- Тест подписи: `CONFIG_TAB_TITLES[TAB_PERMSOC] == "PERMsoc"`.
- JS: `node --check web/app.js`; `JS-UNIT-OK`; `VUE-MOUNT-OK`; маркеры `matrixSections` по `nav`.
- Полный `pytest` 0 failed; `git diff --check`.

## 7. Rollout / feature-flag / откат

- Флаг не требуется (структура админки). Rollback = `git revert`.
- Порядок: **последняя** (P2); сводит Δ каталога (F1 +1, возможно F2/F5) в единый инвариант.
- Проверка в админке: десктоп + мобильный.

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | ТЗ §5 неоднозначно | Раздел 2 фиксирует факт из кода; human-gate Q1 |
| R2 | Перестройка ломает каталог-инвариант | Δ=0 у F6; обновление пин-тестов F1-Δ |
| R3 | Δ конфликтует с F1/F2/F5 | Единый свод (§5) |
| R4 | RBAC-права недостижимы | Тест: каждый tab_id имеет группы; ревью |
| R5 | Регресс UI/адаптива | JS-гейты + визуальная проверка |
| R6 | Дрейф подписей при будущих правках UI | Инвариант: `TABS[].label` ↔ `CONFIG_TAB_TITLES` (тест-паритет) |

## 9. Открытые вопросы

**Принято владельцем (UPD п.4):** эталон = **фактическая карта миниаппа** (`web/app.js`); п.2 — F2 без флагов; лимиты графа/`importance=1`/BetterStack env-host — «как есть». Q1 закрыт. Q5 закрыт частично (F2-флагов нет; F5-флаг остаётся как rollback-механизм).

Осталось уточнить при реализации:
1. **Группировать ли матрицу по навбару (3 «родителя» + группа «Прочее») или оставить плоские 19 секций?** → **Рекомендация:** группировать по nav, с сохранением 19 секций внутри.
2. **Включать ли `#/access` как «секцию» матрицы?** → **Рекомендация:** нет (нет параметров каталога).
3. **Спец-экран «Личность» (`#/ai/persona`)** → **Рекомендация:** не включать (нет ParamSpec; RBAC через действие `edit_persona`).
4. **Нужен ли UI-тумблер для F5-флага?** → см. §5 (итог 437/407 vs 436/406).
