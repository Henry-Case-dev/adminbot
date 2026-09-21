# F4 `module-catalog-quickpanel-store-round1025` — Review (@Reviewer, T-2650)

> **Дата:** 22.09.2026. **Проверяемая база:** HEAD `b5f8348` + рабочее дерево (изменения не закоммичены).
> **APP_VERSION:** `2.58.9`. **Ревью не менял код** (проверка/доказательства — вне репо, temp).
> **Статус:** ✅ **Approved (итерация 2).** Итерация 1 — ❌ Changes requested (F4-M1 + Low); фикс проверен, блокеров нет. Детали — §8.

---

## 1. Вердикт

Реализация F4 в целом качественная и в основном соответствует `spec.md`/`ADR-1025-14`: единый store, одна мутация, структурный откат, scoped-ключи/stale-epoch, избранное в `localStorage`, поиск/синонимы, шов «Настроить». Все заявленные Прогоны **воспроизведены** независимо (pytest 8229/0, JS-маркеры, Playwright-матрица, Δ каталога/DDL=0). Однако найден **подтверждённый дефект** классификации фактического состояния §43/§45: модуль, который глобально выключен и локально «включён» при `gate='global'`, отображается как «Включён» и **не попадает в «Есть проблемы»**, хотя сам же helper показывает «Не работает: отключён глобально». Требуется фикс (небольшой) и повторная проверка.

---

## 2. Выполненные проверки (воспроизведённые цифры)

| Проверка | Результат |
|---|---|
| `node --check web/app.js` / `telegram-init.js` | OK |
| `node tests/js/round1025_f4_module_store_test.js` | `MODULE-STORE-OK` |
| `node tests/js/round1025_f4_catalog_ui_test.js` | `MODULE-CATALOG-OK` |
| `node tests/js/round1021_ui_audit_test.js` | `JS-UNIT-OK` |
| `pytest tests/test_webapp_f4_round1025.py + маркеры (UI-rework1020 / nav_disclosure / 104 / 106-ia / js_unit / scope_selector)` | **165 passed** |
| Полный `.venv\Scripts\python.exe -m pytest -q` | **8229 passed / 0 failed** (1 сторонний `StarletteDeprecationWarning`) |
| `git diff --check` | чисто (только CRLF-предупреждения git) |
| Δ каталога | `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418` → **0** |
| Δ DDL | `services/`, `web/api/`, миграций/БД **нет в диффе** → **0** |
| Playwright (Chromium, статика `web/` + intercept `/api/**`, `#/modules`) | колонки `.module-list` **1/1/2/2/2/3** (320/390/768/1024/1280/1440); `.module-quick` **1/2/2/2/2/4**; тач-цель тумблера **44×44**; гориз. overflow **0**; 13 карточек; счётчики на месте |
| Playwright — поиск | «саммари» → ровно «Сводки чатов» |
| Playwright — §72/§40 | клик по тумблеру в панели → **ровно 1 POST `/api/config`**; панель и карточка каталога синхронно `checked=false`; модалка «Настроить» → заголовок «Сводки чатов», головной тумблер `checked=false` |
| Playwright — «карточка ≠ тумблер» | клик по телу карточки → **0 POST**, состояние не изменилось |
| Инварианты | нет `services/param_catalog.py`/`web/api/routes.py` в диффе; новых библиотек/CDN/эндпоинтов/WebGL нет (инвариант-тест зелёный); `plans/current_task.md` не изменялся/не коммитился |

Инспекция кода: `storeScope/storeKey/getModuleState/setModuleState/refreshModuleState/subscribeModuleState`, `moduleOptimistic/modulePending/moduleSaveError` (единый канонический источник — `configItems`), `moduleEnabled/toggleModule` делегируют в store, `openModuleWorkspace → openModuleWindow`, `moduleRuntimeNotice` отдельно от `configItemNotice`, контракт F0 (`persistItems`) переиспользован, новых write-path нет.

---

## 3. Блокирующие находки

### F4-M1 — Medium (требование-блокирующее): конфликт `gate='global'` (глобально OFF + локально ON) не считается «Есть проблемы» и подписывается «Включён»

**Где:** `web/app.js` — `_moduleRuntimeState()` (стр. ~4347–4361), `moduleStateText()` (~4396–4405), `moduleCounters()` / `filteredModules()` (~1537–1615).

**Требование:** `spec.md` §6.4 — в «Есть проблемы» входит «конфликт runtime↔конфигурация (§3.2: «Не работает: отключён глобально»/override не влияет)»; §3.2 — при `global_value===false && effective===true && gate==='global'` показывать «Не работает: отключён глобально». Комментарий самого кода (`web/app.js:4344`) определяет `blocked` как «включён, но **глобальный**/родительский гейт выключен».

**Наблюдение (воспроизведено независимым JS-пробником на `web/app.js`, сценарий `scope='chat'`, `flags.summary_enabled: value=true, global_value=false, chat_source='chat'`):**
```
runtime = on | display = true
notice  = «Не работает: отключён глобально (локальное значение сохранено)»
stateText = «Включён»
counters = {"total":13,"on":1,"off":0,"issues":12}   ← summary НЕ в issues
issues-filter ids = [...12 прочих модулей...]          ← summary отсутствует
```
В `_moduleRuntimeState` ветка «включён при `gate='global'`» возвращает `'on'` (ветка `blocked` срабатывает только для `parentGate`). Поэтому тумблер/подпись и счётчик «Включено» показывают рабочее состояние, которого нет, а «Есть проблемы» и фильтр «Есть проблемы» этот случай пропускают. Симметричный случай (`inert`, override-выключение при `gate='global'`) в «Есть проблемы» попадает — асимметрия подтверждает непреднамеренность.

**Влияние:** счётчик «Включено»/«Есть проблемы» и подпись фактического состояния искажены для реально нерабочего модуля (реальные чаты: `flags.summary_enabled` глобально OFF в чате с локальным override ON). Степень ограничена UI-индикаторами (предупреждающая строка ⚠ «Не работает…» на карточке показывается), поэтому Medium, а не High.

**Точное корректирующее действие (@Builder):**
1. В `_moduleRuntimeState`: при `eff === true && gate === 'global'` и `item.global_value === false` → вернуть `'blocked'` (учтя `parentGate` как сейчас).
2. `moduleStateText` для `blocked` уже даёт «Включён, но не работает» — проверить, что этот случай его достигает.
3. `moduleCounters`/`filteredModules` для `issues` уже учитывают `'blocked'` — дополнительный код не нужен, но обязательно подтвердить пробой.
4. Добавить negative/поведенческую пробу в `tests/js/round1025_f4_module_store_test.js`: gate=`global`, `global_value=false`, `effective=true` → `runtime==='blocked'`, `stateText==='Включён, но не работает'`, счётчик `issues` включает модуль, `on` его не включает.

**Метод проверки:** повторный `node tests/js/round1025_f4_module_store_test.js`/`node --check`, целевой pytest F4-маркеров; независимый пробник того же сценария; полный pytest (0 регрессий).

---

## 4. Неблокирующий долг (Low/Info)

| ID | Ур. | Место | Суть | Рекомендация |
|---|---|---|---|---|
| L-F4-1 | Low | `web/app.js:4528–4532` | На ветке 409 `setModuleState` делает **второй** `loadConfig()` поверх re-read самого F0 (`spec.md` §3.3 п.9 — «один re-read»). Лишний GET, не искажает данные. | Убрать/условить повторный reload либо зафиксировать как осознанный defensive re-read. |
| L-F4-2 | Low | `setModuleState` error-branch / scope-change | `moduleSaveError[key]` не сбрасывается при смене области или внешнем `loadConfig` — сообщение об ошибке может «висеть» до следующей мутации. | Сбрасывать ошибку при успешном reload активной области. |
| L-F4-3 | Low | `setActiveChat` (`web/app.js:2786+`) | `moduleOptimistic`/`modulePending`/`moduleSaveError` не очищаются при смене scope (ключи scope-специфичны, отображения нет, но при «зависшем» запросе записи накапливаются). | Добавить очистку/ограничение карт при `setActiveChat`. |
| L-F4-4 | Low | `tests/test_webapp_nav_disclosure_ui.py:191+` | Маркер `assert "Параметры" in html` после переименования кнопки в «Настроить» выполняется за счёт постороннего текста («Параметры модуля ещё не загружены») — проверка стала вакуумной. | Заменить/дополнить на `>Настроить</button>` (в F4-тесте уже покрыто). |
| L-F4-5 | Info | `web/app.js` | computed `moduleQuery` не используется (`filteredModules` считает `q` локально) — мёртвый код. | Удалить или задействовать. |
| L-F4-6 | Low | §73-гонка | При незавершённом запросе чата A то же действие по тому же модулю в чате B молча пропускается (in-flight-guard F0 по `toggleKey`, а не по scope-ключу) — по дизайну `spec.md` §3.3 п.4, но без обратной связи пользователю. | Рассмотреть тост/уведомление «запрос уже выполняется» (не блокер). |

---

## 5. Покрытие требований/доказательств

| Требование | Покрытие | Статус |
|---|---|---|
| §32 порядок/сетка ≤3/2/1 | HTML + CSS + Playwright | ✅ |
| §33 карточка, 44×44, «карточка ≠ тумблер», «Настроить» | HTML/CSS + Playwright (0 POST по телу; 44×44) | ✅ |
| §34–§36 панель/избранное (`localStorage`, fail-open, не конфиг) | JS-тест (j) + код | ✅ |
| §37 единое состояние (3 представления) | JS-тест (l), Playwright §72 | ✅ |
| §38 ключ scope/module | JS-тест (a) | ✅ |
| §39 store API | JS-тест (m) + pytest | ✅ |
| §40 одна мутация | JS-тест (c), Playwright (1 POST) | ✅ |
| §41 блокировка/индикатор/откат | JS-тест (d)/(e) + код | ✅ |
| §42/§73 stale/изоляция | JS-тест (f) + инспекция key+epoch | ✅ (браузерно не воспроизводилось — см. §6) |
| §43 наследование/override | JS-тест (k) + `moduleRuntimeNotice` | ⚠️ частично: notice верен, но runtime-классификация одного случая — см. F4-M1 |
| §44 поиск/синонимы | JS-тест (i) + Playwright | ✅ |
| §45 счётчики, unknown≠off, noToggle, uiFlag | JS-тест (h) + Playwright | ⚠️ F4-M1 (конфликт `gate='global'` не в issues) |
| §72/§73 тесты | JS-тесты (l)/(f) | ✅ |
| §79/§116 инварианты | pytest-маркеры + инвариант-тесты | ✅ |
| Δ DDL=0 / Δ каталога=0 / CSP / без новых API-библиотек | команды/тесты/дифф | ✅ |

---

## 6. Недоступные проверки (что осталось не подтверждённым)

- **Реальный Telegram WebView** (mobile 320–390, тач, §72/§73 вживую) — live-гейт владельца **T-2656**; Playwright — desktop-эмуляция.
- **§73-гонка в браузере** (управляемая задержка ответа при смене чата) не воспроизводилась: покрыта поведенческим JS-тестом (f) и инспекцией кода (применение по `key`+`epoch`, `activeChatId` в обработке результата не читается).
- **`tools/ui_audit_round1021.py`** в среде не запускается (дрейф in-memory стаба `ConfigCache`, не связан с F4) — заменён собственным Playwright-зондом.

---

## 7. Handoff

**RESULT: Changes requested — F4 `module-catalog-quickpanel-store-round1025` (1 Medium, требование-блокирующее: F4-M1).**
@Orchestrator, верни @Builder точечно:
1. F4-M1: `web/app.js` — `_moduleRuntimeState` должен возвращать `blocked` для `gate='global' && global_value===false && effective===true`; подтвердить `stateText` «Включён, но не работает», попадание в счётчик/фильтр «Есть проблемы» и отсутствие в «Включено»; добавить пробу в `tests/js/round1025_f4_module_store_test.js`.
2. Прогнать: `node tests/js/round1025_f4_module_store_test.js`, `node tests/js/round1025_f4_catalog_ui_test.js`, `node --check web/app.js`, полный pytest (0 регрессий).
   Low-долг (L-F4-1…L-F4-6) — не блокирует, зафиксировать в tech-debt.
После фикса — повторное ревью (T-2650 iter2). @Scanner (T-2651) может стартовать параллельно.

**Путь отчёта:** `plans/features/module-catalog-quickpanel-store-round1025/review.md`.

---

## 8. Итерация 2 (T-2650, 22.09.2026) — ✅ Approved

**Проверено изменённое:** `web/app.js` (`_moduleRuntimeState`, `moduleStateText`, `moduleCounters`/`filteredModules`, `setActiveChat`, `loadConfig`, удаление `moduleQuery`), `tests/js/round1025_f4_module_store_test.js` (новая проба (o)), `tests/test_webapp_f4_round1025.py` (маркер блока), `tests/test_webapp_nav_disclosure_ui.py` (L-F4-4). `web/index.html` и `web/static/app.css` в итерации 2 не менялись.

| Находка | Статус | Доказательство |
|---|---|---|
| **F4-M1** (Medium, блокер) | ✅ **Закрыт** | `_moduleRuntimeState` (≈4356–4367) возвращает `blocked` при `gate==='global' && scope.type!=='global' && item.global_value===false`; `moduleStateText` → «Включён, но не работает». Независимый пробник: `runtime=blocked`, `stateText=«Включён, но не работает»`, notice §43 без изменений, счётчик `on=0 / issues=13` (конфликт в «Есть проблемы»), фильтр `issues` включает `mod_summary`, `on`/`off` — исключают. Ветки родительского гейта (срабатывает раньше), `per_chat`, `unknown`, `noToggle` и uiFlag OFF не задеты (тест (h)/(k)/(o) зелёные). |
| L-F4-2 (ошибка не сбрасывалась при reload) | ✅ Закрыто | `loadConfig` (≈5922–5924) очищает `moduleSaveError` на успешной загрузке активной области; порядок «reload → установка ошибки» в ветке ошибки сохранён. |
| L-F4-3 (карты операций не чистились при смене области) | ✅ Закрыто | `setActiveChat` (≈2782–2787) очищает `moduleOptimistic`/`modulePending`/`moduleSaveError`. |
| L-F4-4 (вакуумный маркер «Параметры») | ✅ Закрыто | `tests/test_webapp_nav_disclosure_ui.py` → `assert ">Настроить</button>" in html`. |
| L-F4-5 (мёртвый computed `moduleQuery`) | ✅ Закрыто | `moduleQuery` отсутствует в `web/app.js` и тестах; end-маркер `_block` в pytest обновлён на `quickpickCandidates: function`. |
| L-F4-1 (двойной re-read на 409) | ⏳ Техдолг | `setModuleState` (≈4539) сохраняет `await reload()` на conflict — осознанный defensive re-read; зафиксировано в `evidence.md` §6.2/§6.3. |
| L-F4-6 (§73-гонка: молчаливый пропуск действия в другом чате) | ⏳ Техдолг | По дизайну `spec.md` §3.3 п.4; зафиксировано в `evidence.md` §6.3. |

**Red→green пробы (o):** на копии `web/app.js` с удалённым блоком F4-M1 тест падает (`AssertionError … 'on' !== 'blocked'`, строка 549), с текущим кодом — `MODULE-STORE-OK`. Проба действительно защищает фикс.

**Повторно воспроизведённые цифры (итерация 2):** `node --check web/app.js`/`telegram-init.js` OK; `MODULE-STORE-OK`, `MODULE-CATALOG-OK`, `JS-UNIT-OK`; полный pytest **8229 passed / 0 failed** (1 стороннее `StarletteDeprecationWarning`); `git diff --check` exit 0; Δ каталога **0** (459/98/96/21/418); Δ DDL **0** (нет `services/`, `web/api/`, миграций в диффе); Playwright: колонки каталога **1/1/2/2/2/3**, панели **1/2/2/2/2/4**, тач **44×44**, overflow **0**, «саммари» → «Сводки чатов», тумблер панели → **1 POST**. Новых находок нет.

**На live-гейт (T-2656, только владелец):** реальный Telegram WebView — mobile-раскладка каталога/панели 320–390, тач-цели, §72/§73 вживую, сценарий конфликта «глобально OFF + локально ON» на реальном чате.

**RESULT: Approved** — F4 `module-catalog-quickpanel-store-round1025` (T-2650 iter2). @Orchestrator: блокеров нет; можно переходить к `@Scanner` (T-2651) и далее Step 7 merge. Открытый техдолг — L-F4-1, L-F4-6 (зафиксированы в `evidence.md`).
