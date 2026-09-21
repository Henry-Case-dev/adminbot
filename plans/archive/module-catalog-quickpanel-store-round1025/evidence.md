# F4 `module-catalog-quickpanel-store-round1025` — Evidence (@Builder, Step 4)

> **Раунд:** 10.25 (Эпик 1, Волна 2). **Дата:** 22.09.2026.
> **База диффа:** `b5f8348` (HEAD на старте, ветка hotfix7/2a67829-линия), тег отката `pre-round1025-f4`.
> **APP_VERSION:** `2.58.9` (bump с `2.58.8`, T-2653). **Не деплой, не merge.**
> **Секреты/R18:** значения не печатались; `plans/current_task.md` не изменялся и не коммитился.

## 1. Изменённые файлы (реализация + тесты)

| Файл | Изменение |
|---|---|
| `web/app.js` | `MODULES`: `keywords`/`runtimeGate`/`parentGate`, витринные названия «Сводки чатов»/«Ответы в чате» (D5). Store: `storeScope/storeKey/_moduleById/_isActiveScope/_moduleConfigItem/getModuleState/_moduleRuntimeState/moduleRuntimeNotice/moduleStateText/moduleSourceText/modulePendingFor/moduleSaveErrorFor/moduleEnabled/toggleModule/setModuleState/refreshModuleState/subscribeModuleState`. Избранное: `_quickpicksStorageKey/_lsGet/_lsSet/_defaultQuickpicks/_sanitizeQuickpicks/_readQuickpicks/_writeQuickpicks/initQuickpicks/isQuickpick/toggleQuickpick`. Шов `openModuleWorkspace`. Computed: `moduleCounters/moduleQuery/quickpickCandidates/quickpickModules/quickpickVisible/quickpickHiddenCount/moduleFilterOptions/filteredModules`. `created()`/`loadMe()` — инициализация избранного |
| `web/index.html` | Страница «Модули» §32: счётчики §45 → панель избранного §34/§35 → поиск+фильтры §44 → каталог §32 в обёртке `.module-catalog`; карточка §33 (верхняя строка icon+title+toggle, описание, фактическое состояние/источник/предупреждение/ошибка, «В избранное», «Настроить»); головной тумблер в модалке; «Настроить» → `openModuleWorkspace(m)` |
| `web/static/app.css` | `.module-card` → колонка + `.module-card-head`; изолированные правила `.module-catalog`/`.module-list` (container-тиры ≤3/2/1); `.module-quick` ≤4/2/1; `.module-toolbar`/`.module-search`/`.module-filters`; `.module-toggle` тач-цель ≥44×44 + спиннер `.is-saving`; счётчики/состояние/действия/empty-state |
| `tests/js/round1025_f4_module_store_test.js` | **новый** JS-раннер `MODULE-STORE-OK` — §38 ключ, get/set/refresh/subscribe, одна мутация, in-flight, откат §41, stale §42/§73, overlay, счётчики §45, поиск §44, избранное §34–§36, `moduleRuntimeNotice` §43, §72, шов D6 |
| `tests/js/round1025_f4_catalog_ui_test.js` | **новый** `MODULE-CATALOG-OK` — структура/порядок §32, сетка ≤3/2/1 и панель ≤4/2/1, тач-цель 44×44, «карточка ≠ тумблер», «Настроить»→шов, нет карусели/второго каталога |
| `tests/test_webapp_f4_round1025.py` | **новый** структурные/маркерные инварианты (20 тестов): контракт store, overlay не мутирует `configItems`, применение по key+epoch, `configItemNotice` не изменён, `runtimeGate` 9/4 + parentGate, Δ каталога=0, CSP/zero-build, нет новых API/библиотек |
| `tests/test_webapp_js_unit.py` | регистрация двух новых JS-раннеров (аддитивно) |
| `tests/test_webapp_nav_disclosure_ui.py` | атомарно: `openModuleWindow(m)`→`openModuleWorkspace(m)` в HTML + `openModuleWindow: function` в JS (модалка сохранена) |
| `tests/test_scope_selector_round1025.py`, `tests/test_webapp_design_tokens_round1025.py`, `tests/test_webapp_hotfix6_round1025.py`, `tests/test_webapp_hotfix7_round1025.py`, `tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js` | атомарный версионный пин `2.58.8` → `2.58.9` |
| `config/settings.py` | `APP_VERSION = "2.58.9"` |
| `README.md` | `**Версия:** v2.58.9` (синхронно с `test_app_version_matches_readme`) |

**Не изменялись (инварианты):** `services/param_catalog.py`, `web/api/routes.py`, `services/chat_params.py`, `services/database.py`, `bot.py`, `handlers/**`, миграции/БД, `plans/current_task.md`.

## 2. Прогоны (факт)

| Команда | Результат |
|---|---|
| `node --check web/app.js` | OK |
| `node --check web/static/telegram-init.js` | OK |
| `node tests/js/round1025_f4_module_store_test.js` | `MODULE-STORE-OK` (exit 0) |
| `node tests/js/round1025_f4_catalog_ui_test.js` | `MODULE-CATALOG-OK` (exit 0) |
| `pytest tests/test_webapp_f4_round1025.py -q` | **20 passed** |
| Полный `pytest -q --timeout=120 -p no:cacheprovider` | **8229 passed, 0 failed** (база 8207; +22 новых теста) |
| `pytest tests/test_webapp_js_unit.py` (все раннеры, включая F4) | passed |
| `git diff --check` | чисто (только CRLF-warnings git) |
| **Playwright (Chromium) live-зонд** (статика `web/` + API-интерцепт, `#/modules`) | см. §2a |

Δ каталога = **0**: `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418` (факт команды).
Δ DDL = **0**: `services/database.py` и миграции вне диффа.

## 2a. Playwright (реальный Chromium) — матрица раскладки и §72

Метод: локальная раздача `web/` + перехват `/api/*` (фейковый админ, безопасные заглушки; R17),
переход `#/modules`, замер `getComputedStyle`. Артефакт-скрипт — вне репозитория (temp).

| Ширина | `.module-list` колонок | `.module-quick` колонок | Тач-цель тумблера | Гориз. overflow | Счётчики |
|---|---|---|---|---|---|
| 320 | 1 | 1 | 44×44 | 0 | 13 Всего / 1 Вкл / 12 Выкл / 0 Проблем |
| 390 | 1 | 2 | 44×44 | 0 | те же |
| 768 | 2 | 2 | 44×44 | 0 | те же |
| 1024 | 2 | 2 | 44×44 | 0 | те же |
| 1280 | 2 | 2 | 44×44 | 0 | те же |
| 1440 | 3 | 4 | 44×44 | 0 | те же |

- **§44 поиск:** запрос «саммари» → 1 карточка, первая — **«Сводки чатов»**.
- **§32/§33:** карточек 13, фильтров 5, поле поиска на месте, длина панели — 4 избранных.
- **§72 (единый переключатель):** клик по тумблеру «Сводки чатов» в панели избранного →
  **ровно 1** `POST /api/config` → карточка каталога `checked=False`, головной тумблер модалки
  `checked=False`, счётчики «0 Включено / 13 Выключено» — три представления синхронны.
- **D6:** «Настроить» открывает модалку, головной тумблер в модалке присутствует.
- Примечание: ошибка `uptime_seconds` в консоли — артефакт зонда (заглушка `/api/status` = `{}`),
  к модулям не относится.

## 3. Покрытые приёмочные сценарии

- **§39/§38 (контракт store):** ключ `scope_type/scope_id/module_id` — global/чат A/чат B; `get/set/refresh/subscribe`; `node --check`.
- **§40 (одна мутация):** spy-транспорт (`persistItems`) — ровно 1 write на переключение; три представления (панель/карточка/модалка) читают один store.
- **§41 (запрос/откат):** in-flight guard по ключу (двойной тап = 1 запрос); оптимистично — только overlay, `configItems` не мутируется; ошибка → снятие overlay возвращает серверное значение + понятное сообщение, без авто-ретраев; спиннер `is-saving`.
- **§42/§73 (stale):** ответ чата A, пришедший после перехода в B, не меняет B (применение по `key`+`epoch`; `activeChatId` в обработке результата не читается).
- **§43 (наследование):** `moduleRuntimeNotice` — таблица 4 случаев (global/per_chat/unknown/inert) + родительский гейт (`flags.summary_enabled`, действует в любой области: «Не работает: отключён глобально»); `moduleStateText` для blocked — «Включён, но не работает»; `configItemNotice` (F3) не изменён; override не уничтожается.
- **§44 (поиск):** «Саммари»/«сводка»/«суммаризация»/`summary` → «Сводки чатов»; описание/тех.имя/синонимы; inline-фильтрация, без отдельной страницы.
- **§45 (счётчики):** «Всего / Включено / Выключено / Есть проблемы»; неизвестное ≠ выключено; `noToggle` — только «Всего»; `mod_images` при uiFlag OFF — вне витрины/поиска/панели/счётчиков.
- **§34–§36 (избранное):** `localStorage` `adminbot.modules_quickpicks.v1`; стартовый набор §34; save/restore; fail-open при битом JSON/недоступном хранилище; закрепление — ноль мутаций.
- **§33/D6:** «карточка ≠ тумблер»; тач-цель `.module-toggle` ≥44×44; «Настроить» → `openModuleWorkspace` → существующая модалка `openModuleWindow` (новых маршрутов нет).
- **§32/D7:** `.module-list` ≤3/2/1 изолированными правилами (не ломает общий triple-rule `.prov-grid/.module-list/.hub-grid`); `.module-quick` ≤4/2/1; без горизонтального скролла.

## 4. Что НЕ проверено / ограничения

- **Живой Telegram WebView** (mobile-раскладка 320–390, тач-цели, §72/§73 вживую) — за владельцем (T-2656). Playwright-зонд составлен на desktop-эмуляции, реальный TMA не задействован.
- **`tools/ui_audit_round1021.py`** (штатный аудит F6) в этой среде не запускается: его in-memory стаб `ConfigCache` не покрывает `/api/analytics/usage/summary` (добавлен в раунде 10.23) → 500 до загрузки. Это дрейф инструмента, не регресс F4; проверка выполнена собственным Playwright-зондом (§2a).
- **Дрейф `runtimeGate`↔серверный код:** метаданные (`keywords`/`runtimeGate`/`parentGate`) заданы по аудиту ADR-1025-14 §D3; при изменении серверного гейта модуля их нужно актуализировать (осознанный поддерживаемый риск ADR).
- **§73 (незавершённый запрос) в браузере** не воспроизводился отдельно (гонка требует управляемой задержки ответа); покрыт поведенческим JS-тестом (stale-ответ A не меняет B).
- `plans/archive/*/deployment.md`, `plans/metrics.md`, `plans/workflow_state.md`, `tasks.md` были Modified до старта F4 (работа PM/Architect раунда) — не трогались, кроме чекбоксов `tasks.md`.

## 5. Независимая проверка

Ожидается: `@Reviewer` (T-2650) — контракты §37–§42, откат §41, stale §42, сохранность §79/§116; `@Scanner` (T-2651) — scope-изоляция/RBAC/R17/Δ каталога-Δ DDL. Коммит/деплой не выполнялись.

## 6. Rework iter2 — фикс F4-M1 + Low (@Builder, 22.09.2026)

Источник: `review.md` (Changes requested, блокер F4-M1 + Low L-F4-1…L-F4-6).

### 6.1. Изменённые файлы (только дельта rework)

| Файл | Изменение |
|---|---|
| `web/app.js` | **F4-M1:** `_moduleRuntimeState` — добавлена ветка `blocked` для `gate==='global' && scope.type!=='global' && item.global_value===false` при `eff===true` (симметрично `moduleRuntimeNotice`; в глобальной области `effective===global_value`, конфликта нет). `moduleStateText` для `blocked` уже отдаёт «Включён, но не работает»; `moduleCounters`/`filteredModules` уже относят `blocked` к «Есть проблемы» и не к on/off — код этих мест не менялся, подтверждено пробой. **L-F4-2:** успешный `loadConfig` активной области очищает `moduleSaveError`. **L-F4-3:** `setActiveChat` очищает `moduleOptimistic`/`modulePending`/`moduleSaveError` при смене области. **L-F4-5:** удалён мёртвый computed `moduleQuery`. |
| `tests/js/round1025_f4_module_store_test.js` | **новая проба (o)** F4-M1: `gate='global'` + `global_value=false` + `effective=true` (scope chat) → `runtime==='blocked'`, `moduleStateText==='Включён, но не работает'`, `moduleRuntimeNotice` §43 без изменений, счётчик `issues` включает модуль, `on`/`off` — нет, фильтр `issues` включает, `on`/`off` исключают; negative: глобально `true` → `on`, `on=1`/`issues=0`; `per_chat` override → `on`; global scope → `on`. |
| `tests/test_webapp_f4_round1025.py` | маркер `_block("moduleCounters…", "quickpickCandidates…")` после удаления `moduleQuery` (L-F4-5). |
| `tests/test_webapp_nav_disclosure_ui.py` | **L-F4-4:** вакуумная `assert "Параметры" in html` → точная `assert ">Настроить</button>" in html`. |

### 6.2. Прогоны (факт, iter2)

| Команда | Результат |
|---|---|
| `node --check web/app.js` / `web/static/telegram-init.js` | OK |
| `node tests/js/round1025_f4_module_store_test.js` | `MODULE-STORE-OK` (exit 0; включает пробу (o)) |
| `node tests/js/round1025_f4_catalog_ui_test.js` | `MODULE-CATALOG-OK` (exit 0) |
| `pytest tests/test_webapp_f4_round1025.py tests/test_webapp_nav_disclosure_ui.py tests/test_webapp_js_unit.py -q` | **60 passed** |
| Полный `pytest -q -p no:cacheprovider` | **8229 passed, 0 failed** (1 сторонний `StarletteDeprecationWarning`) |
| `git diff --check` | exit 0 (только CRLF-предупреждения git) |
| Δ каталога | `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418` → **0** |
| Δ DDL | `services/`, `web/api/`, `migrations/`, `bot.py`, `handlers/` — **не в диффе** → **0** |

### 6.3. Статус Low-долга

- **Исправлено:** L-F4-2, L-F4-3, L-F4-4, L-F4-5.
- **Оставлено явным техдолгом:** **L-F4-1** — повторный `loadConfig()` в ветке 409 `setModuleState` является **осознанным defensive re-read**: F0 сам делает re-read, но затем возвращает в элемент пользовательский черновик; повторный reload возвращает подтверждённое сервером значение. Удаление без изменения семантики F0/`conflict`-ветки небезопасно → зафиксировано как техдолг (не блокер).
- **Оставлено явным техдолгом:** **L-F4-6** — при незавершённом запросе чата A то же действие по тому же модулю в чате B молча пропускается (in-flight-guard F0 по `toggleKey`), без тоста. Поведение по дизайну `spec.md` §3.3 п.4; добавление тоста — за рамками минимального фикса → техдолг (не блокер).

Rework не деплоился/не мержился. `plans/current_task.md` не изменялся. Требуется повторное независимое ревью (`@Reviewer` T-2650 iter2) + аудит (`@Scanner` T-2651).
