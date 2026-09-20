# Ревью F24 — `providers-fullscreen-advanced-fix-round1024` (раунд 10.24, UPD6)

**Статус:** Approved (итерация 2; итерация 1 была Changes Requested)

**Ревьюер:** @Reviewer · **Объект:** итерация 1 — `2b0759e`; итерация 2 — `1e21112` · **Дата:** 20.09.2026
**Спека:** `plans/features/providers-fullscreen-advanced-fix-round1024/spec.md`, `ADR-1024-24.md`, `tasks.md`
**Секреты:** не цитировались (R17/R18).

---

## Резюме

Первопричина закрыта по существу: `:open` переведён на реактивный стейт (`computed advancedOpen/provAdvancedOpen/chatLoreAdvancedOpen`), `localStorage` стал только персистом, `toggleExpand` синхронизируется из факта DOM (`$event.target.open`) — осцилляция исключена, `isFullscreen` синхронизирован с TMA и корректно отписывается в `beforeUnmount`. 5 биндинг-сайтов изменены ровно, `:1040`-эквивалент (текущий `web/index.html:1132`) не тронут, пины переведены (не удалены), инварианты целы. Полный pytest — **7884 passed / 0 failed**, все JS-гейты зелёные, `node --check`/`git diff --check` чисты.

Однако **не выполнен подпункт §5.4 спеки (cache-bust `APP_VERSION`/README), при этом `T-2385` отмечен `[x]`** — это ложный чекбокс и незакрытая часть контракта фичи. Требую исправление до апрува. Остальные находки — Low.

---

## Findings по severity

### [Medium] §5.4 cache-bust не выполнен; задача T-2385 ложно закрыта
- Файлы: `config/settings.py:1589`, `README.md:5`, `plans/features/providers-fullscreen-advanced-fix-round1024/tasks.md:49`
- Проблема: `APP_VERSION = "2.57.0"` не поднят (baseline `00eab85` тоже `2.57.0`), шапка README не обновлена, синхронности по `tests/test_webapp_round108_ui.py:222` нет нового значения. При этом `T-2385` (`§6.1 + §6.3 + §5.4 (cache-bust)`) отмечен `[x]`.
- Почему важно: `web/app.js`/`web/index.html` отдаются с `?v=2.57.0`. Штатная защита (`web/app.py` `CacheControlStaticFiles`, `Cache-Control: no-cache` + ETag) риск сглаживает, но спека §5.4/риск R5 прямо требует bump «не ниже baseline+1, одно на раунд». F24 — последняя фича web-очереди (F3→F5→F6→F11→F4→F10→+F24), т.е. именно здесь ожидается раундовый bump. Без него нельзя гарантировать владельцу доставку фикса в TMA (это и есть исходный боевой дефект).
- Required fix: синхронно поднять `APP_VERSION` до согласованного с web-очередью значения (`>= 2.58.0`) и обновить шапку `README` («v2.58.0»), чтобы `tests/test_webapp_round108_ui.py::test_app_version_matches_readme` остался зелёным; либо письменно зафиксировать решение о round-level bump в `tasks.md`/`ADR-1024-24` и снять `[x]` с T-2385 до его фактического выполнения.

### [Low] `initFullscreen` — утечка/дубль подписки при исключении на втором `onEvent`
- Файл: `web/app.js:4095-4111` (метод `initFullscreen`)
- Проблема: `_fsSubscribed = true` выставляется только ПОСЛЕ обоих `onEvent(...)`. Если `onEvent('viewportChanged', …)` бросит, первый листенер (`fullscreenChanged`) останется зарегистрированным, а `_fsOnFullscreen` будет перезаписан новой ссылкой при повторном вызове → старый слушатель невозможно снять (`offEvent` получит не ту ссылку) + двойной вызов `setFullscreenFromTma`.
- Почему важно: спека §4.3/D1 требует «guard против двойных подписок» и корректной отписки ровно по тем же ссылкам; в аварийной ветке контракт нарушается (утечка листенеров на iOS WebView/легаси-SDK).
- Required fix: в `catch` сбрасывать `_fsOnFullscreen = null; _fsOnViewport = null; _fsSubscribed = false;` (и, при необходимости, пробовать `offEvent` уже зарегистрированного первого), чтобы повторный `initFullscreen()` поднимал состояние с чистого листа.

### [Low] `toggleFullscreen` присваивает потенциально устаревший `wa.isFullscreen`
- Файл: `web/app.js:4074-4089`
- Проблема: сразу после `requestFullscreen()/exitFullscreen()` читается `wa.isFullscreen`; свойство может не успеть обновиться синхронно, и `isFullscreen`/иконка `⛶` (`web/index.html:109`) на короткое время отразит неверный режим.
- Почему важно: п.3.5/§8 спеки требует синхронности `⛶` фактическому состоянию; события `fullscreenChanged`/`viewportChanged` коррекцию дадут, но кратковременно UI врёт.
- Required fix (рекомендация): не присваивать «оптимистично-устаревшее» значение — полагаться на событие (при наличии подписки), либо перечитывать `isFullscreen` отложенно (microtask/`requestAnimationFrame`) после transition.

### [Low] Пин `test_webapp_avatars_ui.py` устарел по смыслу (зелёный по совпадению)
- Файл: `tests/test_webapp_avatars_ui.py:232`
- Проблема: `assert "this.isFullscreen = !this.isFullscreen" in body` проходит только потому, что инверсия осталась в legacy-ветке; тест не отражает новый источник истины (`wa.isFullscreen` + события), т.е. не защищает контракт C3.
- Почему важно: пины должны проверять актуальное поведение, иначе регресс `toggleFullscreen` пройдёт незамеченным.
- Required fix: актуализировать проверку — ассертить наличие `typeof wa.isFullscreen === 'boolean'` / `this.isFullscreen = wa.isFullscreen`, сохранив инверсию как legacy-фолбэк.

### [Info] Расхождение заявленного числа тестов
- Заявлено «pytest 7882»; фактически на `2b0759e` — **7884 passed, 0 failed**. Нарушений нет (зелёное, ноль падений), но цифру в отчёте/`tasks.md` следует уточнить.

---

## Контракт

### Чекбоксы задач
- `T-2380`..`T-2384` — `[x]`, подтверждены реализацией.
- `T-2385` — `[x]`, но §5.4 (cache-bust) фактически не выполнен → см. Finding Medium.
- `T-2386` (@Reviewer) / `T-2387` (@DevOps live TMA) — `[ ]`, корректно (в работе).

### Инварианты
- `tma-menu-freeze` — **OK** (состав/порядок вкладок и меню не менялся).
- Δ DDL = 0, Δ каталога = 0 — **OK** (ассетов каталога/миграций нет).
- R16 (API) — **OK**; R17/R18 (секреты) — **OK** (в дифе секретов нет).
- `parse_mode=None` — **OK** (web-слой текстовую доставку не трогает).
- CSP / zero-build — **OK** (новых JS-библиотек/CDN нет; `vue_mount_test.js` зелёный).
- Feature flag — **не вводится** — **OK**.
- Скоуп — **OK**: ровно 5 биндинг-сайтов `details.advanced` (`web/index.html:609/611`, `643-646`, `893-895`, `2175-2177`, `2543-2545`); lightweight `<details>` (`web/index.html:1132`) без `class="advanced"`/персиста не тронут.

### Fullscreen ↔ TMA (C3/C4)
- Init из `Telegram.WebApp.isFullscreen` в `mounted` (`web/app.js:1860`) и в `ready` (`:1909`) — **OK**.
- Подписки `fullscreenChanged`/`viewportChanged` — **OK**; отписка в `beforeUnmount` (`:7454`) теми же fn-ссылками — **OK**; guard `_fsSubscribed` — **OK** (кроме edge-ветки, см. Low).
- Безопасные no-op вне TG/старого SDK (`try/catch`, проверки `typeof`) — **OK**.

### Реактивный аккордеон (C1/C2)
- `data.expand` — единственный источник `:open`; `computed` (`web/app.js:1178-1186`) — **OK**.
- `initExpandState()` в `created()` (`:1820`), скан по префиксу `adminbot.expand:`, `try/catch` — **OK**.
- `expandOpen` читает `this.expand`, `localStorage` в рендере не читается — **OK**.
- `toggleExpand(tabId, scope, ev)` синхронизирует из `ev.target.open` (идемпотентно), legacy-инверсия без события, персист `'1'/''` — **OK**.

### Тесты
- JS `tests/js/round1024_providers_fullscreen_test.js` → `PROVIDERS-FS-OK` — **OK** (реактивность, ремаунт, скан LS, идемпотентность C2, подписки/отписка/те же ссылки, вне TG, раздельные scope-ключи — не тавтологичны).
- Статический `tests/test_webapp_round1024_providers.py` — **OK**; обновлённые пины `test_webapp_round1011_ui.py`, `test_webapp_nav_disclosure_ui.py`, `test_ui_verbilizer_tabs_round1023.py`, `tests/js/routing_test.js` — переведены, не удалены — **OK**.
- Полный pytest — **7884 passed / 0 failed**; `node --check web/app.js` — OK; все `tests/js/*.js` — OK; `git diff --check` — чисто.

---

## Точный список исправлений (Changes Requested)

1. **`config/settings.py` / `README.md`** — синхронно поднять `APP_VERSION` до раундовой версии (`>= 2.58.0`) и обновить шапку README; привести `tasks.md` (T-2385) в соответствие. Либо документально зафиксировать round-level bump и снять `[x]`.
2. **`web/app.js:4095-4111`** — в `catch` метода `initFullscreen` сбрасывать `_fsOnFullscreen/_fsOnViewport/_fsSubscribed`, чтобы исключение на втором `onEvent` не оставляло «бесхозную» подписку.
3. **`web/app.js:4074-4089`** — не фиксировать устаревшее `wa.isFullscreen` синхронно после `request/exitFullscreen`; опираться на событие либо перечитать отложенно.
4. **`tests/test_webapp_avatars_ui.py:232`** — актуализировать пин `toggleFullscreen` под новый источник истины.
5. **Отчёт/`tasks.md`** — уточнить фактическое число pytest (7884/0).

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 2 — ревью коммита `1e21112` (F24, review iter1)

**Статус: Approved**

**Объект:** `1e21112` («fix(web,tests,docs): раунд 10.24 F24 — cache-bust APP_VERSION, guard подписок, пин avatars»)
Учтено: поверх влит несвязанный F10-фикс `5021d1e` (к F24 не относится, не приписывается).

## Резюме

Все 5 замечаний итерации 1 закрыты по существу. Реализация не косметическая: guard подписок действительно снимает «бесхозный» листенер, `toggleFullscreen` переведён на отложенный re-read, cache-bust выполнен синхронно (код + README + пины тестов). Целевые гейты, все JS-гейты и полный pytest — зелёные. Новые тесты проверяют поведение, а не константы.

## Проверка исправлений (по пунктам)

**[Medium] §5.4 cache-bust — CLOSED**
- `config/settings.py:1589` → `APP_VERSION = "2.58.0"` (baseline+1); `README.md:5` → «v2.58.0»; `tests/test_webapp_api.py:1297-1307` синхронизированы на `?v=2.58.0`.
- `tests/test_webapp_round108_ui.py::test_app_version_matches_readme` — зелёный (в составе полного прогона).
- `T-2385` (`tasks.md`) обновлён корректно, ложный `[x]` устранён.

**[Low] `initFullscreen` — снятие подписки при сбое второго `onEvent` — CLOSED**
- `web/app.js:4117-4131`: `catch` делает best-effort `offEvent('fullscreenChanged', _fsOnFullscreen)` и сбрасывает `_fsOnFullscreen/_fsOnViewport/_fsSubscribed` → повторный `initFullscreen()` поднимается с чистого листа.
- Подтверждено JS-тестом (блок 5b): исключение на `viewportChanged` → первый листенер снят, guard сброшен, повторный init подписывает заново (`resub === 2`).

**[Low] `toggleFullscreen` — без синхронной фиксации устаревшего `wa.isFullscreen` — CLOSED**
- `web/app.js:4085-4094`: при отсутствии boolean — legacy-инверсия; при boolean — НЕ присваивается синхронно, планируется отложенный re-read (microtask + `requestAnimationFrame`) через `setFullscreenFromTma()`; окончательная коррекция — событиями.
- Подтверждено JS-тестом (блок 5c): синхронно флаг не меняется, rAF-колбэк применяет фактический режим, legacy-фолбэк инвертирует. Плюс статический `test_toggle_fullscreen_defers_state`.

**[Low] Пин `test_webapp_avatars_ui.py` — CLOSED**
- `tests/test_webapp_avatars_ui.py:225-239`: ассертит `typeof wa.isFullscreen !== 'boolean'`, `setFullscreenFromTma` и legacy-инверсию — отражает новый источник истины.

**[Info] Число тестов — CLOSED**
- `tasks.md` и отчёт фиксируют **7886 passed / 0 failed**; фактический прогон — **7886 passed / 0 failed** (совпадает).

## Инварианты (итерация 2)

- `tma-menu-freeze` — **OK** (меню/вкладки не менялись).
- R16 — **OK**; R17/R18 — **OK** (секретов нет).
- `parse_mode=None` — **OK**.
- Δ DDL = 0, Δ каталога = 0 — **OK** (нет миграций/ParamSpec).
- CSP / zero-build — **OK** (новых библиотек/CDN нет; `vue_mount_test.js` зелёный).
- Скоуп и реактивный аккордеон итерации 1 не изменены и остаются валидными.

## Гейты (итерация 2)

- Целевые pytest (F24 + обёртки + обновлённые пины + api/README-версии): **325 passed**.
- Полный pytest: **7886 passed / 0 failed**.
- JS: `round1024_providers_fullscreen_test.js` → `PROVIDERS-FS-OK`; `routing_test.js` → `JS-UNIT-OK`; `vue_mount_test.js` → `VUE-MOUNT-OK`; все `tests/js/*.js` — OK.
- `node --check web/app.js` — OK; `git diff --check 1e21112^ 1e21112` — чисто.

## Открытые пункты (не блокируют)

- `README.md:388,398` содержат «v2.57.0»/«2.57.0» в исторических заметках раунда 10.15 — это летопись, не шапка версии; тест сверяет шапку и зелёный. Правка не требуется.
- `T-2387` (live-приёмка TMA) остаётся `[ ]` — это @DevOps-контур, следует за ревью.

`**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.`
