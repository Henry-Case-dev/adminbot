# F1 `ia-shell-navigation-round1025` — отчёт реализации и карта «старый → новый экран» (T-2409)

> **Раунд:** 10.25, Эпик 1 «Liquid Glass Control Center», Wave 1 (после F0 и ASAP-хотфикса).
> **Спека/ADR:** `plans/features/ia-shell-navigation-round1025/spec.md` + `adr-1025-1-ia-v2.md`.
> **Задачи:** `plans/features/ia-shell-navigation-round1025/tasks.md` (T-2388…T-2409).
> **Ветка:** `master`, база **`65e39fb`** (после хотфикса `hotfix-media-tma-round1025`).
> **Точка отката:** тег `pre-round1025-f1-resume` (создан при возобновлении T-2481) + `pre-round1025*`.
> **Статус:** реализация T-2388…T-2407 выполнена; **T-2408 (@Reviewer) и T-2409 (очистка бэкапа после утверждения владельцем) — открыты**.

## 1. Что сделано

| Слой | Файл | Содержание |
|---|---|---|
| Backend nav | `services/param_catalog.py` | `NAV_MEMORY="memory"`, `NAV_TITLES["memory"]="Память"`, `NAV_ORDER=(modules,ai,memory,permsoc)`; `TAB_NAV`: `memory_rag`/`relations`/`chat_lore` → `memory`. Δ ParamSpec/GROUPS/TAB_RULES = **0** |
| Флаг | `config/settings.py` | env-only `ClassVar IA_V2_ENABLED = _env_bool("IA_V2_ENABLED", True)` (вне каталога) |
| Доставка | `web/api/routes.py` | `GET /api/me.ui_flags` + аддитивное `"IA_V2_ENABLED": bool` (наружу только bool) |
| IA/роутинг | `web/app.js` | `TABS[].menu` (`memory_rag`/`relations`/`chat_lore` → `memory`), label `«Сводка»→«Аналитика»`; `NAV_GROUP_ORDER/TITLES` + `memory`; новые `NAV_ITEMS_V2` (7) и `HUBS_V2` (`#/ai` без памяти/лора/отношений + `#/memory`); маршруты `#/memory/*`, `ROOT_ROUTES`, `ROUTE_ALIAS`, `ROUTE_PARENT`; computed `iaV2`/`navItems`/`activeNav`/`hubCards`/`sidebarItems`/`sidebarGroups`/`bottomNavItems`/`mobileMoreItems`/`breadcrumb`; мусорный hash `#/…` → `#/` |
| Shell | `web/index.html` + `web/static/app.css` | Desktop sidebar ≈232 px (строго ≥1200) + header ≈64 px; tablet 768–1199 — **drawer** без постоянного sidebar; mobile <768 — компактный header + **bottom-nav ровно 4** + шторка «Ещё» (Справка/Память/Доступы/PERMsoc/Профиль); breadcrumb/назад; Справка (оглавление+поиск+якоря), Доступы (матрица/мобильный редактор) |
| TMA | `web/static/telegram-init.js` | `BackButton`, `viewportStableHeight`, `safeAreaInset`, `contentSafeAreaInset` → CSS-переменные `--tg-*` |
| Kill-switch | `web/app.js` | OFF (`IA_V2_ENABLED=false`) → legacy `NAV_ITEMS`/`HUBS`/`.navbar-band` (константы оставлены литерально неизменными) |
| F0-слой | `web/app.js` | `persistItems`/`saveState`/`notify`/`stickyFieldFailed` **не переписывались** (переиспользование контракта §52) |

## 2. Карта «старый экран → новый раздел IA» (§117 п.1)

### Публичные (всем)
| Старый | Новый | Примечание |
|---|---|---|
| `#/` Статус | `#/` **Статус** (стартовая, `home`) | единственная главная; виджеты сохранены |
| `#/oversight` «Сводка» | `#/oversight` **«Аналитика»** | менялся **только label**; переход из Статуса; дубля нет |
| `#/how` Справка | `#/how` **Справка** | layout desktop/mobile + якоря; тексты/стиль v5 не менялись |

### Административные (по правам)
| Старый | Новый | Примечание |
|---|---|---|
| `#/modules` | `#/modules` | витрина 11 модулей (без изменений) |
| `#/modules/budgets`, `#/modules/images` | без изменений | `mod_budgets` / `mod_images` |
| `#/ai` (hub) | `#/ai` (hub) | **без** памяти/лора/отношений: llm, prompts, smart-cache, names, persona |
| `#/ai/llm`, `#/ai/prompts`, `#/ai/smart-cache`, `#/ai/names`, `#/ai/persona` | без изменений | — |
| `#/ai/memory` (Память) | **`#/memory/rag`** | legacy-алиас `#/ai/memory → #/memory` |
| `#/ai/lore` (Лор чата) | **`#/memory/lore`** | legacy-алиас `#/ai/lore → #/memory/lore` |
| `#/ai/relations` (Участники и отношения) | **`#/memory/relations`** | legacy-алиас `#/ai/relations → #/memory/relations` |
| — | **`#/memory`** (новый hub, 3 карточки) | Т-2395: отдельный раздел |
| `#/access` + `#/access/{roles,local,admins}` | без изменений | матрица/мобильный редактор |

### Локальное
| Старый | Новый | Примечание |
|---|---|---|
| `#/permsoc` | `#/permsoc` | остаётся **локальным**, отдельным нижним пунктом; в глобальные не перенесён |

### Legacy-алиасы (не 404, ведут в новый дом)
`#/ai/limits → #/ai`, `#/ai/sleep → #/modules`, `#/ai/nostalgia → #/modules`,
`#/modules/{features,switches,reactions,custom} → #/modules`,
`#/ai/memory → #/memory`, `#/ai/lore → #/memory/lore`, `#/ai/relations → #/memory/relations`.

> **Полнота:** все 26 `TABS` (21 config + modules/status/info/oversight/access) и хабы имеют место в новой IA; «сирот» нет; отдельного конкурирующего «Обзора» не создано (авто-тест `tests/test_ia_inventory_round1025.py`).

## 3. Проверка (фактические числа, 21.09.2026)

| Гейт | Результат |
|---|---|
| Полный `pytest -q --timeout=120` | **7996 passed / 0 failed** (baseline после хотфикса 7976 + 20 новых F1-тестов) |
| JS-гейты `tests/js/*` | **21/21 OK** (19 baseline + `round1025_ia_routing_test.js`, `round1025_shell_breakpoints_test.js`) |
| `node --check web/app.js` | OK |
| `git diff --check` | exit 0 |
| Каталог | `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / TAB_NAV 21 / CONFIG_TAB_TITLES 21` → **Δ = 0** |
| DDL | SQLite `user_version=12`, новых PG-таблиц нет → **Δ DDL = 0** |
| Playwright/Chromium §71 (`tools/ui_round1025_matrix.py`) | **0 нарушений**: 10 вьюпортов × 8 маршрутов; `scrollWidth ≤ innerWidth`; sidebar только ≥1200; drawer 768/1024; bottom-nav=4 только <768; touch ≥44 |

Артефакты матрицы: `tools/_ui_round1025_raw.json`, `tools/_ui_round1025_shots/*.png`.

> **Важно:** успешный локальный Chromium-прогон **не заменяет** живую приёмку в Telegram WebView (урок 10.20-UPD3/10.21); сквозная live-приёмка Эпика 1 — зона **F10**.

## 4. Ограничения/риски

- **T-2408** — независимая итерация @Reviewer ещё не пройдена.
- **T-2409** — бэкап `var/backups/f1-wip-20260921-015653/` и теги `pre-round1025*` **сохранены** до утверждения владельцем (R18); удалять нельзя.
- **Live-гейт владельца хотфикса** (T-2463/T-2472/T-2479) остаётся открытым и F1 не закрывает.
- `IA_V2_ENABLED` — **временный** механизм отката (UPD §9.5); legacy-константы и флаг удаляются post-Epic-1 (техдолг).
- Эпик 2 (Саммари/роутинг/обложка/Rich Message) не затронут.
