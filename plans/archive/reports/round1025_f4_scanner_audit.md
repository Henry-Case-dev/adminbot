# Round 10.25 F4 `module-catalog-quickpanel-store-round1025` — Scanner-аудит (Step 6, T-2651)

> **Дата:** 22.09.2026. **Аудитор:** @Scanner (focused diff-based). **Проверяемая база:** HEAD `b5f8348` + рабочее дерево (правки **НЕ закоммичены**). Тег отката `pre-round1025-f4`.
> **Вход:** `spec.md`, `adr-1025-14-module-store-and-catalog.md`, `evidence.md` (iter1 + iter2 F4-M1), `review.md` (iter1 Changes requested → Builder fix), мастер-ТЗ `plans/current_task.md` (§31–§45, §72/§73). Файл untracked, не изменялся (R17/R18).
> **APP_VERSION:** `2.58.9`.
> **Код не менялся; отчёты/карты обновлены.** Секреты/сырые значения не цитировались.

---

## 1. Вердикт

**Critical 0 / High 0 / Medium 0 / Low 2 / Info 3. К деплою — ДА.** Обязательных возвратов @Builder нет; находки Low — owned follow-up, не блокеры. Пакет изоляции scope, единой мутации, структурного отката и `localStorage`-избранного выполнен корректно; инварианты (Δ DDL=0, Δ каталога=0, CSP/zero-build, без новых API/библиотек) удержаны. Fix F4-M1 подтверждён независимо (пробой JS-раннера и инспекцией `_moduleRuntimeState`).

---

## 2. Таблица severity

| ID | Ур. | Место | Суть | Статус |
|---|---|---|---|---|
| L-F4S-1 | Low | `web/app.js:4428-4432`, `:6432`, `:2785-2787` | `stickyFailedKeys` (F0) не сбрасывается при смене области → «Есть проблемы»/фильтр протекают между чатами | open |
| L-F4S-2 | Low | `web/app.js:4356-4360`, `:4382-4386` | родительский гейт проверяется по **эффективному** значению, а не `global_value` (в ТЗ/ADR — «выключен **глобально**») | open |
| I-F4S-1 | Info | `MODULES` (`web/app.js:501-510`), `services/feature_gates.py:106-136` | kill-switch `flags.dream_enabled`/`flags.nostalgia_enabled` вне `REGISTRY` → F4 их не видит (Δ каталога=0); статус Сна/Ностальгии по kill-switch не моделируется | known limitation |
| I-F4S-2 | Info | — | Playwright-матрица и живой Telegram WebView (T-2656) @Scanner не воспроизводились (опора на evidence @Builder + review iter1) | open (opener) |
| I-F4S-3 | Info | L-F4-1/L-F4-6 (`review.md` §4) | техдолг зафиксирован @Builder (двойной `loadConfig` в ветке 409; молчаливый пропуск при гонке scope) — не блокеры, остаются видимыми | open (follow-up) |

---

## 3. Находки (доказательства)

### L-F4S-1 — Low: `stickyFailedKeys` протекает между областями в счётчиках/фильтре
- **Где:** `moduleCounters` (`web/app.js:1547-1551`) и `filteredModules` (`:1603-1607`) вызывают `_moduleSaveFailed(m)` (`:4428-4432`), который читает **глобальный** (не scope-ключевой) `this.stickyFailedKeys` по `toggleKey`.
- **Почему протекает:** `persistItems` пишет `this.stickyFailedKeys = failed.map(k)` (`:6432`). `setActiveChat` чистит только `moduleOptimistic`/`modulePending`/`moduleSaveError` (`:2785-2787`); `loadConfig` чистит только `moduleSaveError` (`:5924`). `stickyFailedKeys` не scope-ключевой и не сбрасывается при смене области.
- **Репро (по коду):** провалить переключение модуля в чате A (сеть/409) → `stickyFailedKeys=[ключ]`; перейти в чат B → `moduleCounters.issues` и фильтр «Есть проблемы» содержат модуль A, пока не выполнится следующая запись (любая).
- **Влияние:** только UI-индикаторы/фильтр (ложный «Есть проблемы» в чужом чате). Данные и серверная конфигурация не затронуты.
- **Remediation:** сбрасывать `stickyFailedKeys` в `setActiveChat` (симметрично L-F4-3) либо сделать его scope-ключевым (правка F0). Низкий приоритет.
- **Связь:** расширение класса, который закрывал L-F4-3; сам `stickyFailedKeys` — наследство F0, F4 впервые потребляет его в счётчиках (§6.4 spec).

### L-F4S-2 — Low: родительский гейт сравнивается по эффективному значению, а не по глобальному
- **Где:** `_moduleRuntimeState` (`web/app.js:4356-4360`) и `moduleRuntimeNotice` (`:4382-4386`) проверяют `_findConfigItem(m.parentGate).value === false`.
- **Требование:** `spec.md` §3.2 / ADR §D3 — «родительский гейт выключен **глобально**»; регистрация роутеров 0a–0i (`bot.py:752-786`) использует `hot.get("flags.summary_enabled")` **без чата**.
- **Наблюдение:** `item.value` — эффективное значение (`override → global → default`). Если у `flags.summary_enabled` есть локальный override ON при глобально OFF, то `p.value === true` → дочерний модуль (напр. `mod_factcheck` с глобальным ON) получает `runtime='on'`, хотя роутеры не зарегистрированы и модуль фактически не работает.
- **Влияние:** подпись фактического состояния и счётчики §43/§45 для дочерних модулей в узком сценарии (нужен chat-override родителя). Модуль-родитель (`mod_summary`) в этом же сценарии показывается корректно (`blocked`, fix F4-M1).
- **Remediation:** сравнивать `global_value === false` (для форсированного гейта по коду). Низкий приоритет; фиксировать как follow-up.

---

## 4. Инварианты (проверено)

| Инвариант | Факт |
|---|---|
| Δ DDL = 0 | `services/`, `web/api/`, `migrations/`, `bot.py`, `handlers/**` **не в диффе** → нет новых таблиц/миграций/эндпоинтов |
| Δ каталога = 0 | `services/param_catalog.py` не тронут; `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418` (тест `test_catalog_delta_zero` + прямой прогон) |
| Новые API/библиотеки | Нет: в диффе нет новых `/api/*`, `fetch`/`import`/`require`, state-библиотек; используется `GET/POST /api/config` через `persistItems` (F0) |
| CSP / zero-build | Нет внешних URL/CDN/data-URI/новых inline-скриптов; добавлены только CSS-правила + `@keyframes module-spin`; WebGL не добавлялся |
| `APP_VERSION` 2.58.9 | Синхронен: `config/settings.py:1702`, `README.md:5` (v2.58.9), тесты-пины, cache-bust `?v=__APP_VERSION__` (`index.html:21/24/4008/4011`) |
| Маркер-тесты сетки | Общий triple-rule `.prov-grid, .module-list, .hub-grid` **не изменён**; F4-правила изолированы (`@container`); маркеры grid (1020/1021/104/nav) зелёные; `nav_disclosure` **усилен** (L-F4-4: `>Настроить</button>` вместо вакуумной подстроки) — ослаблений нет |
| R17 | В коде/отчётах нет секретов и сырых значений; toast использует только `toggleKey`; console-логов в F4-коде нет |
| R18 | Тег `pre-round1025-f4` есть; бэкап `var/backups/f4-round1025-20260922-073051/` есть; `.env.bak.round1025-f4` есть; `stash@{0}` цел; `plans/current_task.md` не изменялся (gitignored, untracked) |
| Гигиена | В изменениях нет `.env`/zip/скриншотов; `git status --porcelain -uall` — только ожидаемые `plans/**` и `tests/**`; `git diff --check` exit 0 |

---

## 5. Логика §40–§42 / изоляция чатов

- **Одна мутация:** `setModuleState` делает **ровно один** `await this.persistItems([...])` (`app.js:4493-4495`); второго write-path нет (`saveConfigItem` в блоке отсутствует — проверено маркер-тестом `test_single_write_path`). Три представления читают один store (`moduleEnabled`/`toggleModule`).
- **Структурный откат:** оптимистично мутируется **только** overlay `moduleOptimistic[key]`; `configItems[i].value` не трогается до подтверждения (`app.js:4485-4489`), поэтому откат конструктивен. При ошибке/409 overlay снимается, `prevValue` восстанавливается, показывается понятная ошибка, авто-ретраев нет (`:4532-4546`).
- **Stale-ответ:** `epoch` и `key` фиксируются до `await` (`:4479`, `:4472`); применение — только при `sameScope = (epoch === this.scopeEpoch)` (`:4503`); `activeChatId` в обработке результата не читается (маркер `test_apply_by_key_and_epoch`); `reload()` для чужой области — no-op (`:4510-4519`).
- **Блокировка повтора:** F4-guard `modulePending[key]` + вторая линия F0 in-flight по `toggleKey` (`skipped`).
- **Изоляция (§73):** stale-ответ A не меняет B — подтверждено JS-пробой (f) (независимый прогон @Scanner).
- **RBAC:** `setModuleState` проверяет `canEditModule` (тост без права), тумблеры `:disabled` при `!canEditModule`; `_isActiveScope` блокирует мутацию для неактивной области.
- **Fix F4-M1:** `_moduleRuntimeState` при `gate='global'` + `global_value===false` + `effective===true` (неглобальная область) возвращает `blocked` (`:4361-4366`); `moduleStateText` → «Включён, но не работает»; счётчики/фильтр относят к «Есть проблемы», не к «Включено». Подтверждено пробой (o) и независимым прогоном.

---

## 6. Совместимость

- **IA F1 / навигация:** маршруты/меню/`TABS` не менялись; `openModuleWindow` сохранён как регресс-путь, добавлен шов `openModuleWorkspace` (`app.js:4664-4666`). `TABS[].label`/`PROVIDER_BLOCKS` не тронуты (витринные имена — только в `MODULES`).
- **Shell/glass hotfix6/7:** изменения только внутри страницы «Модули» (`.module-catalog`/`.module-quick`/`.module-toolbar` + карточка); `--shell-h`, safe-area, fullscreen-sync, glass-токены не затронуты.
- **Палитра/фон F2:** новых цветовых литералов нет — используются существующие токены (`--teal-500`, `--warn`, `--err`, `--text-*`, `--surface-*`, `--radius-full` — все определены).
- **F3 guard/RBAC:** `scopeEpoch`/`_scopeGuard`/`configSourceLabel`/`configItemNotice` переиспользованы; `configItemNotice` не изменён (маркер зелёный). Override не уничтожается (`DELETE /api/config/chat/{key}` из F4 не вызывается).
- **F0 save-path:** `persistItems` не переписан; `saveConfigItem`/`notify` не дублируются.

---

## 7. Изменённые файлы (F4, рабочее дерево vs `b5f8348`)

- **Код:** `web/app.js`, `web/index.html`, `web/static/app.css`.
- **Версия/доки:** `config/settings.py` (`2.58.9`), `README.md` (`v2.58.9`).
- **Тесты (новые):** `tests/js/round1025_f4_module_store_test.js`, `tests/js/round1025_f4_catalog_ui_test.js`, `tests/test_webapp_f4_round1025.py`.
- **Тесты (правки):** `tests/test_webapp_js_unit.py` (+2 раннера), `tests/test_webapp_nav_disclosure_ui.py` (L-F4-4, усиление), пины версии в `tests/test_scope_selector_round1025.py`, `tests/test_webapp_design_tokens_round1025.py`, `tests/test_webapp_hotfix6_round1025.py`, `tests/test_webapp_hotfix7_round1025.py`, `tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js`.
- **Plans (untracked, Step 2/4/6):** `spec.md`, `adr-1025-14-*.md`, `evidence.md`, `review.md`; `tasks.md` (чекбоксы).
- **Не изменялись:** `services/param_catalog.py`, `web/api/routes.py`, `services/chat_params.py`, `services/database.py`, `bot.py`, `handlers/**`, миграции, `plans/current_task.md`.

---

## 8. Прогоны (independent @Scanner)

| Проверка | Результат |
|---|---|
| `node --check web/app.js` / `web/static/telegram-init.js` | OK |
| `node tests/js/round1025_f4_module_store_test.js` | `MODULE-STORE-OK` (exit 0) |
| `node tests/js/round1025_f4_catalog_ui_test.js` | `MODULE-CATALOG-OK` (exit 0) |
| `node tests/js/round1021_ui_audit_test.js` | `JS-UNIT-OK` (exit 0) |
| Целевые pytest (F4 + UI-rework1020 + nav_disclosure + 104 + 106-ia + js_unit + scope_selector) | **165 passed** |
| Полный `pytest -q -p no:cacheprovider` | **8229 passed / 0 failed** (1 сторонний `StarletteDeprecationWarning`) |
| `git diff --check` | exit 0 (только CRLF-предупреждения git) |
| Δ каталога / Δ DDL | 0 / 0 |
| Не в диффе | `web/api/`, `services/`, миграции, `bot.py`, `handlers/` |
| XSS | Новых `v-html`/`innerHTML`/`insertAdjacentHTML` нет; `localStorage`-id валидируются по `MODULES`, рендер — из доверенных `MODULES` |
| WebGL / CDN | Нет (Canvas 2D — наследство hotfix6/7; новых внешних ссылок нет) |

**Не воспроизводилось:** Playwright-матрица (нет `playwright` в среде @Scanner) и живой Telegram WebView (T-2656) — см. I-F4S-2.

---

## 9. Handoff

**RESULT: SCANNED — F4 `module-catalog-quickpanel-store-round1025` (Critical 0 / High 0 / Medium 0 / Low 2 / Info 3). К деплою — ДА.** @Orchestrator, обязательных возвратов @Builder нет; L-F4S-1/L-F4S-2 — owned follow-up (можно закрыть в F0-правке `stickyFailedKeys` и в `runtimeGate`/parent-gate follow-up, не блокируют этот пакет). I-F4S-2 (живой TMA, T-2656) остаётся за владельцем. Артефакты: этот отчёт; синхронизированы `full_audit_results.md`, `audit_backlog.md`, `global_map.md`. Коммит/деплой не выполнялись.
