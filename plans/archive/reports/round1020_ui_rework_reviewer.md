# Reviewer-отчёт — round1020 UPD3 (T-1940, гейт фактического рендера)

> **Дата:** 17.09.2026 · **Ревьюер:** @Reviewer · **Baseline:** HEAD `a67f83d` + рабочее дерево (незакоммиченные правки `web/*`, `tests/*`).
> **R18:** секреты не раскрываются; в примерах — только маска `••••••••••••` и фейковый `last4=FAKE`.
> **Метод:** независимый CSS-парсер/резолвер каскада + **реальный Chromium (Playwright 151.0.7922.34)**, в котором смонтирован
> **настоящий** `web/index.html` + `web/app.js` + `web/static/app.css` (застабены только `/api/*` и Telegram SDK), с измерением
> `getComputedStyle`/`getBoundingClientRect` на фактических DOM-узлах. Grep-доказательства как единственное основание не использовались.
>
> **Апдейт (Re-review итерация 2, 17.09.2026):** Critical-1, Critical-2 и High-1 **закрыты**; ключевой сценарий сохранения
> подтверждён фактическим POST. Итоговый вердикт итерации 2 — **APPROVED** (см. раздел «Re-review (итерация 2)» в конце файла).
> VERDICT ниже (`NEEDS FIXES`) — исторический, для итерации 1.

## ВЕРДИКТ (итерация 1): **NEEDS FIXES** (Critical)

Liquid Glass, Grid, градиент, sticky и маска в целом **фактически работают** — это подтверждено реальным render-зондом
(computed-стили, треки, отсутствие перекрытия, маска в инпутах Betterstack). Но **инвариант R31/INV-3 сломан на пути LLM-провайдеров**:
у 3 prоvider-инпутов секрета нет `@focus select()` (G3.6), а guard `isSecretMask` сравнивает **только точное** равенство.
Реальный клик оставляет каретку в конце маски → ввод нового ключа даёт `••••••••••••+новый_ключ`, и `saveBlock`/`saveKeyItem`
**отправляют эту строку в `POST /api/config`, перезаписывая реальный секрет**. Это ровно R31 — порча BYOK-кредов.

---

## 1. Таблица проверок (1–9) со СЫРЫМИ выводами

| # | Проверка | Статус | Сырой вывод |
|---|---|---|---|
| 1 | **Каскад, а не наличие** (независимый парсер `cascade_audit.py`) | PASS (кроме G3.6) | `glass_set_order=198`; для всех glass-селекторов winner = правило order 198: `background-color: var(--glass-bg)`, `backdrop-filter` **и** `-webkit-backdrop-filter: var(--glass-blur)…`; `opaque_overrides=[]`; `!important_on_glass=[]`; `.card-solid` **не** связан с модалками; `card_rules`: order 16 `.card`→`var(--glass-bg)`, order 198 `.card`→`var(--glass-bg)`, order 203 `@supports not` `.card`→`var(--glass-bg-strong)`. `modal-card card card-solid` = **0**. `card-solid` в index = 2 (header + scope-panel). |
| 2 | **CSSOM-зонд (реальный Chromium)** | PASS | `.modal-card` → `backgroundColor: "rgba(20, 25, 30, 0.5)"`, `backdropFilter: "blur(16px) saturate(1.4)"`, `display:flex`, `maxHeight:736px`. `.card`(config) → `rgba(20,25,30,0.5)`/`blur(16px) saturate(1.4)`. `.module-card` → `rgba(20,25,30,0.5)`/`blur(16px) saturate(1.4)`. `.prov-block` → `rgba(20,25,30,0.5)`/`blur(16px) saturate(1.4)`. `.hub-card` → `rgba(20,25,30,0.5)`/`blur(16px)`. `.glass-panel` → `rgba(20,25,30,0.5)`/`blur(16px)`. `body` прозрачен, `#app` `z-index:1`. |
| 3 | **Grid ≥2 трека @≥1000px** | PASS | Desktop 1440×900: `.prov-grid` = `340px 340px 340px 340px` (4 трека, w=1408); `.module-list` = `356px 356px 356px` (3, w=1100); `.hub-grid` = `330.656px 330.672px 330.656px` (3). Мобайл 400px: все три = `368px` (1 трек). Ветка «ИИ» содержит `prov-grid` (2 контейнера), `max-w-3xl` в `index.html` = **0**. Grid-контейнеры: `backgroundColor rgba(0,0,0,0)`, `border 0`, `backdropFilter none`. |
| 4 | **Маска секретов** | PASS по рендеру / **FAIL по безопасности** | Реальный Chromium, модалка «Диагностика»: `Пользователь Betterstack SQL` → value `••••••••••••` (len **12**), `type=password`, badge `configured ••••FAKE`; `Пароль Betterstack SQL` → то же; не настроенный ключ → `""`, badge `не настроен`. `@focus select()` × 3; `v-model="keyDrafts[item.key]"` × 3. **НО** provider-инпуты (index.html:243,279,377) **без** focus-select → см. Critical ниже. |
| 5 | **Градиент** | PASS | `--grad-d:#FF8A3D`; `--grad-speed:6s`; `body::before` computed: `backgroundImage: conic-gradient(… rgb(255,138,61) …)`, `opacity:0.42`, `animationDuration:6s, 6s`, `animationName:grad-spin, grad-drift`; `prefers-reduced-motion:reduce` → `animationName:none, opacity:.35, linear-gradient(...)`; `prefers-contrast:more` → `animationName:none, opacity:1`. |
| 6 | **Sticky** | PASS | Config: `.sticky-save` `position:sticky, bottom:0, background rgba(20,25,30,0.85), blur(16px), z-index:5`; `.scroll-area` `padding-bottom:88px`, `scroll-padding-bottom:72px`. Нет inline `max-height:80dvh/70dvh` (0). Fullscreen-режим, max-scroll: `stickyTop=754` vs `lastBottom=738` → **gap=+16px** (нет перекрытия). Модалка: `.modal-body` scroll (clientHeight 606, scrollTop 1469=max), `stickyTop=701` vs `lastCardBottom=672` → **gap=+29px**; `stickyInBody=true`, `footerHasSticky=false`. Ветки: access → `areaSticky=true`; modules-модалка → `stickyInBody=true`; досье → `.modal-body > .sticky-save`=true. |
| 7 | **Red→green** | PASS | RED (git stash поверх pre-fix `web/*`): `pytest tests/test_webapp_ui_rework_round1020.py` → **19 failed, 7 passed**; `node tests/js/round1020_ui_rework_test.js` → `AssertionError: isSecretMask — метод: actual 'undefined' expected 'function'`. GREEN после восстановления: **26 passed**; `JS-UNIT-OK`. |
| 8 | **Инварианты** | PASS | Снимок навигации: 25 вкладок + 6 nav + 12 модулей — зелёные (`TestNavigationSnapshot`, JS-снимок). `services/**`, `web/api/**`, `web/app.py`, `web/static/vendor/**` — **0 изменений** (`git diff --name-only` пуст); `param_catalog.py` Δ=**0**. R18-скан diff + новых файлов: 2 совпадения — обе строки кода (`this.blockFieldValue(f)`, `isSecretMask(...)`), секретов нет. `git diff --check` → clean. |
| 9 | **Полный прогон** | PASS | `.venv/Scripts/python.exe -m pytest tests/ -q --timeout=300` → **6572 passed, 1 warning in 111.18s** (baseline 6546 + 26 новых). `node --check web/app.js` → OK; `round1020_ui_rework_test.js` → `JS-UNIT-OK`; `round1020_ui_test.js` → `JS-UNIT-OK`; `routing_test.js` → `JS-UNIT-OK`; `vue_mount_test.js` → `VUE-MOUNT-OK`. Local served-CSS: `tests/test_webapp_api.py::TestStatic` → **15 passed** (assert'ит `--glass-blur: blur(16px)`, `backdrop-filter: var(--glass-blur) saturate(140%)`, `Cache-Control: no-cache, no-store, must-revalidate`). |

### Доказательство Critical (сырые выводы)

**a) Реальный Chromium — provider-инпут vs generic-инпут (одинаковый сценарий: клик мышью → ввод одного символа):**
```
generic (модалка, @focus select есть):
  generic_after_click_selection: {start:0, end:12, len:12}   // маска выделена целиком
  generic_after_type:            {len:1, startsWithMask:false}  // 'X' заменил маску
provider (нет @focus select):
  prov_after_click_selection:    {start:12, end:12, len:12}  // каретка В КОНЦЕ, маска НЕ выделена
  prov_after_type:               {len:13, draft:[["keys.llm_api_key",13,false]]}
```
**b) Node (тот же `web/app.js`, что в браузере) — что уйдёт на сервер:**
```
blockFieldValue(secret configured) = "••••••••••••"  len 12  isMask true
saveBlock(draft = exact mask)      -> POSTs: 0
saveBlock(draft = mask + "X")      -> POSTs: 1
   body: {"items":[{"key":"keys.llm_api_key","value":"••••••••••••X"}]}
saveKeyItem(keyDrafts = mask + "X")-> POSTs: 1
   body: {"items":[{"key":"keys.x","value":"••••••••••••X"}],"updated_at":null}
```

---

## 2. Найденные проблемы

**[Severity: Critical]**
Файл: `web/app.js`
Location: `isSecretMask` (стр. 18) и его потребители — `saveKeyItem` (стр. 3862), `saveBlock` (стр. 2970), `testBlock` (стр. 2910), `testField` (стр. 2941), `dirtyKeyItems` (стр. 1357).
Problem: guard понимает под «маской» **только точное** `v === SECRET_MASK`. Значение `SECRET_MASK + <введённый текст>` маской не считается и уходит в `POST /api/config`.
Why it matters: реальный сценарий замены ключа (клик + ввод) даёт композит `••••••••••••<ключ>`; `saveBlock`/`saveKeyItem` сохраняют его как секрет → **реальный ключ в БД перезаписывается строкой с точками** (порча BYOK, риск R31, явно названный в spec §11/§3.3).
Required fix: ввести `hasSecretMask(v)` = `String(v).indexOf(SECRET_MASK) !== -1` и во всех guard'ах считать «маской» **любое** значение, содержащее сентинел (`!hasSecretMask(...)`); для `saveKeyItem` — либо no-op с тостом, либо отрезать маску перед POST. Обязательно добавить JS-тест «`mask + 'X'` → 0 запросов» для обоих путей.

**[Severity: Critical]**
Файл: `web/index.html`
Location: provider-инпуты `:value="blockFieldValue(f)"` — строки **243, 279, 377** (обычные и advanced provider-блоки).
Problem: на masked-полях провайдеров отсутствует `@focus="$event.target.select()"` (спец G3.6 требует его «на поле с маской»). Реальный клик в Chromium оставляет selection `[12,12]` (каретка в конце), поэтому первый введённый символ **дописывается к маске**, попадая в `blockDrafts`.
Why it matters: естественное действие админа «клик в поле → набрать новый ключ → Сохранить» портит сохранённый секрет (см. Critical выше); для сравнения, 3 generic-инпута (`index.html:556,642,813`) с `@focus select()` проверены и работают (`selection [0,12]`).
Required fix: добавить `@focus="$event.target.select()"` (и, желательно, `@mouseup.prevent` для устойчивости к mouseup) на инпуты строк 243, 279, 377; дополнительно застраховаться на уровне save-guard (см. пункт выше). Покрыть JS-тестом композитного значения.

**[Severity: High]**
Файл: `tests/js/round1020_ui_rework_test.js`
Location: кейсы «R31 GUARD» (стр. 186–228).
Problem: тест проверяет только `blockDrafts`/`keyDrafts`, **точно равные** маске. Композит `mask + 'X'` не покрыт.
Why it matters: именно этот пробел пропустил Critical-дефект; без регресс-кейса R31 может вернуться незамеченным.
Required fix: добавить кейсы: `saveKeyItem` и `saveBlock` при значении `SECRET_MASK + 'X'` → **0 POST**; `blockFieldValue` не должен позволять отправить композит.

### Некритичные наблюдения (не блокируют, к устранению)

- **[Low]** `web/index.html:67` — `.scope-panel card-solid`: класс инертен, т.к. одноимённый селектор в glass-set (order 198) перебивает `.card-solid` (order ~17). Computed = glass `rgba(20,25,30,0.5)`. По `ui-contract.md §1` `.scope-panel` = стекло, поэтому не нарушение, но `card-solid` здесь — мёртвый/вводящий в заблуждение класс (и конфликт с формулировкой G1.3).
- **[Low]** `web/static/app.css:7` — токен `--surface-glass` больше не используется нигде (осталась только дефиниция). Удалить либо задокументировать.
- **[Low]** `web/app.js:900` — `data.secretMask` выставлен, но нигде не потребляется (только контракт/удобство тестов). Не покрыт ни одним тестом.
- **[Info]** `.card .card, .modal-body .card { background: rgba(255,255,255,.04); backdrop-filter:none }` (G1.5, необязательный) — вложенные карточки почти «прозрачны»; визуально оценить на §7.5.

---

## 3. Проверка DoD (spec §10)

| DoD | Статус |
|---|---|
| 1. Дефекты 1–5 закрыты по G1–G5 | **Частично:** G1/G2/G4/G5 — подтверждены; **G3.6 не выполнен** на provider-инпутах → INV-3/R31 нарушены |
| 2. Red→green зафиксирован | ✅ (19 failed/7 passed → 26 passed; node assertion → JS-UNIT-OK) |
| 3. Новые/обновлённые тесты + полный pytest + JS-гейты + `git diff --check` | ✅ 6572 passed; JS-UNIT-OK ×2; VUE-MOUNT-OK; routing OK; diff --check clean |
| 4. Снимок навигации не изменён | ✅ 25 вкладок + 6 nav + 12 модулей |
| 5. Прод-верификация `§7.6` (новый CSS на прод-хосте) | ⏸ **ОТКРЫТО** — прод не задеплоен (T-1942); локально TestStatic 15 passed |
| 6. Визуальная приёмка §7.5 (скриншоты desktop/Android/Nekogram) | ⏸ **ОТКРЫТО** — нет реального устройства/скриншотов |
| 7. R18 чист | ✅ |
| 8. Reviewer-протокол §8 + re-audit @Scanner + @DevOps | ⏸ Reviewer выполнил; Scanner/DevOps — впереди |

**T-1940 в `tasks.md` НЕ отмечен** (вердикт Needs fixes).

---

## 4. Ограничения (что невозможно проверить без реального браузера/деплоя)

1. **Целевые WebView (Telegram Android WebView, Nekogram/iOS WKWebView)** недоступны. Прогон — Chromium 151 (Playwright).
   В Chromium `CSS.supports('-webkit-backdrop-filter','blur(1px)') === false`, computed `-webkit-backdrop-filter` пуст — проверить
   фактическое применение `-webkit-` префикса можно только на WebKit. Статически объявление присутствует во всех glass-правилах
   (независимый парсер подтверждает `-webkit-backdrop-filter: var(--glass-blur) …`).
2. **Прод-хост `/static/app.css`** (T-1940 п.1 в формулировке «на тестовом стенде» = локально проверен через TestClient; **прод — нет**):
   остаётся **открытым до деплоя T-1942**; не выдаётся за пройденный.
3. **Скриншоты §7.5** (визуальная приёмка 1440×900 / Android / Nekogram) — не приложены.
4. `prefers-contrast: more` эмулирован средствами Playwright (`contrast="more"`); поведение иных движков не проверено.
5. Прократический `-webkit-backdrop-filter` и «живые» touch-жесты ввода маски на мобильных не воспроизведены (десктопный клик мышью
   ведёт себя иначе, чем tap в WebView) — но дефект provider-пути воспроизведён и на десктопном клике.

---

## 5. Что осталось проверить после деплоя / устранения

1. Закрыть Critical (provider `@focus select()` + save-guard на «contains mask») и добавить регресс-тесты.
2. Повторно прогнать red→green для новых кейсов и полный `pytest`.
3. T-1942 (@DevOps): пуш/деплой; `curl` прод-`/static/app.css` — подтвердить `blur(16px)`, `rgba(20, 25, 30, 0.5)`,
   `Cache-Control: no-cache, no-store, must-revalidate` (без печати секретов).
4. Визуальная приёмка §7.5: desktop 1440×900 (⛶), Telegram Android, Nekogram — стекло, ≥2 колонок «Модули»/«ИИ», маска Betterstack,
   градиент 5–8 s с оранжевым, sticky без перекрытия.
5. T-1941 (@Scanner): независимый re-audit (в т.ч. воспроизвести зонд композитной маски).

---

## Re-review (итерация 2) — 17.09.2026

> **Baseline:** HEAD `a67f83d` + рабочее дерево (`web/app.js`, `web/index.html`, `tests/js/round1020_ui_rework_test.js`).
> **Метод итерации 2:** реальный Chromium (Playwright **1.62.0**, движок Chromium 151) с настоящими `index.html`/`app.js`/`app.css`
> (застабены только `/api/*` + Telegram SDK); Node-пробы на **реальном** `web/app.js`; red→green; полный `pytest`; R18-скан.
> **R18:** секреты не раскрываются — только маска `••••••••••••` и фейковые `NEWKEY_GEN_1`/`PROVKEY_1`.

### 1. Статус findings итерации 1

| Finding | Severity | Статус | Сырой вывод |
|---|---|---|---|
| **Critical-1** — композит `mask+X` уходит в `POST /api/config` | Critical | **Closed** | Node (реальный `app.js`): `saveBlock(exact mask)=0 POST`; `saveBlock(mask+"X")=0 POST`; `saveKeyItem(mask+"X")=0 POST, ok:false, toast ["Уже сохранено","warn"]`; `testBlock(mask+"X")` body `api_key:""`; `testField(mask+"X")` body `api_key:""`. Chromium e2e (принудительно `[12,12]` + ввод `Z`): input len **13** = `mask+Z`, `blockDrafts["keys.llm_api_key"]` len **13** (содержит маску) → клик Save → `POST /api/config = []` (**0 запросов**). |
| **Critical-2** — provider-инпуты без `@focus select()` | Critical | **Closed** | Chromium **реальный клик мышью**: provider `selection {start:0,end:12,len:12}` (маска выделена целиком); generic — тоже `[0,12]`. Render-probe `provmask.selectionAfterFocus [0,12,12]`, ввод `X` → len 1. В `index.html` ровно **3×** `@focus="$event.target.select()" @mouseup.prevent` (стр. 244/281/380 — provider-блоки). |
| **High-1** — нет регресс-кейсов на композит | High | **Closed** | `tests/js/round1020_ui_rework_test.js`: `hasSecretMask` (стр. 230–247), композит `saveKeyItem`+`saveBlock` (249–277), `testBlock`/`testField` (279–316), `dirtyKeyItems` (318–330), 3× focus (332–337). **RED→GREEN:** деградация guard до точного равенства + снятие `@focus` → `AssertionError: композит mask+X → true` (exit 1); восстановление → `JS-UNIT-OK` (exit 0). |
| Low — мёртвый токен `--surface-glass` | Low | **Closed** | Помечен комментарием в `app.css:7` (не удалён — допустимо). |
| Low — `data.secretMask` не потребляется | Low | **Closed** | Помечен комментарием `app.js:908` («контракт/тесты»). |
| Low — инертный `.scope-panel card-solid` | Low | **Won't fix (осознанно)** | Не трогали; computed = glass `rgba(20,25,30,0.5)`. Согласовано с ui-contract §1. |

### 2. Регрессия ключевого сценария «клик по маске → ввод нового ключа → Сохранить»

Реальный Chromium, тела POST захвачены из сетевого слоя:
```
A) generic модалка (CHECKUP_BETTERSTACK_SQL_USER):
   click → selection [0,12]; type "NEWKEY_GEN_1" → len 12
   Save → POST /api/config:
   {"items":[{"key":"CHECKUP_BETTERSTACK_SQL_USER","value":"NEWKEY_GEN_1"}],"updated_at":null}
   после сохранения инпут снова mask (len 12)
B) provider-блок (keys.llm_api_key):
   click → selection [0,12]; type "PROVKEY_1" → len 9
   Save → POST /api/config:
   {"items":[{"key":"keys.llm_api_key","value":"PROVKEY_1"}],"updated_at":null}
   после сохранения инпут снова mask (len 12)
```
**PASS** — новый ключ реально сохраняется, из-за no-op не теряется.

### 3. Не сломано (реальный рендер, сырые значения)

- **Liquid Glass CSSOM:** `.modal-card` → `backgroundColor rgba(20, 25, 30, 0.5)`, `backdropFilter blur(16px) saturate(1.4)`; то же у `.card`/`.module-card`/`.hub-card`/`.prov-block`/`.glass-panel`; `.prov-grid`/`.module-list`/`.hub-grid` → `rgba(0,0,0,0)`, `border 0`, `backdrop none`. Каскад: winner для всех glass-селекторов = order 198 (`var(--glass-bg)`), `opaque_overrides=[]`.
- **Grid ≥2 трека @1440px:** `.prov-grid` = `340px 340px 340px 340px` (4); `.module-list` = `356px 356px 356px` (3); `.hub-grid` = `330.656px 330.672px 330.656px` (3). Mobile 400px → все 1 трек (`368px`).
- **Градиент:** `--grad-d #FF8A3D`, `--grad-speed 6s`; `body::before` computed `conic-gradient(… rgb(255,138,61) …)`, `opacity 0.42`, `animationName grad-spin, grad-drift`, `animationDuration 6s, 6s`; `reduced-motion` → `none / 0.35 / linear-gradient`; `contrast:more` → `none / 1`.
- **Sticky:** config `gap +16px` (`stickyTop 754` vs `lastBottom 738`), modal `gap +29px` (`stickyTop 701` vs `lastCardBottom 672`); `stickyInBody=true` (modules/dossier), access `areaSticky=true`; `scroll-padding-bottom 72px`, `padding-bottom 88px`.
- **Меню-снимок:** JS-снимок 25 вкладок + 12 модулей — зелёный; `tests/test_webapp_round1020_ui.py` → **24 passed**.
- **Каталог Δ=0:** `git diff --name-only -- services/ web/api/ web/app.py web/static/vendor/` — пусто; `param_catalog.py` Δ=0.
- **R18:** скан изменённых/новых файлов + diff — 2 совпадения (`web/app.js:631,5474`), оба — длинные идентификаторы в комментариях, **не** в добавленных хунках; секретов нет.

### 4. Новые findings (не блокируют)

**[Low]** `web/index.html:243-245, 280-282, 379-381` — `@focus="$event.target.select()" @mouseup.prevent` навешены на **все** поля provider-блоков, включая не-секретные (`display_name`, `base_url`, `model`).
Сырой Chromium: не-секретное поле `Probe Model` (len 11) — первый клик → selection `[0,11]`, **второй клик → снова `[0,11]`**; позиционировать каретку мышью нельзя (клавиатура работает: `End` + `!` → `"Probe Model!"`).
Рекомендация (фоллоу-ап): применять select/`preventDefault` условно (`f.secret`), например `@focus="f.secret && $event.target.select()"` и `@mouseup="f.secret && $event.preventDefault()"`. На R31/сохранение не влияет; блокером не является (T-1936-fix предписывал атрибуты на 3 provider-инпута целиком).

**[Low/Info]** `web/app.js:3877` — при композите тост «Уже сохранено» вводит в заблуждение (значение **не** сохранено). На WebView, где `@focus select()` не срабатывает, новый ключ молча теряется. Проверить/поправить текст (напр. «Поле изменено — введите ключ заново») и покрыть на живых WebView (§7.5). Допустимо: spec G3.4 разрешает no-op.

### 5. Полный прогон

```
pytest tests/ -q --timeout=300                 → 6572 passed, 1 warning in 107.13s
tests/test_webapp_api.py::TestStatic + tests/test_webapp_ui_rework_round1020.py → 41 passed
tests/test_webapp_round1020_ui.py              → 24 passed
node --check web/app.js                        → OK
node tests/js/routing_test.js                  → JS-UNIT-OK
node tests/js/vue_mount_test.js                → VUE-MOUNT-OK
node tests/js/round1020_ui_test.js             → JS-UNIT-OK
node tests/js/round1020_ui_rework_test.js      → JS-UNIT-OK
git diff --check                               → clean
```

### 6. ВЕРДИКТ итерации 2: **APPROVED**

Critical-1, Critical-2, High-1 — **Closed**; ключевой сценарий сохранения подтверждён фактическим POST; регрессий не найдено.
Новые Low-findings вынесены в фоллоу-ап и блокерами не являются. **T-1940 отмечен в `tasks.md`.**

### 7. Остаётся проверить после деплоя (вне код-гейта)

1. **T-1942 (@DevOps):** прод-`/static/app.css` → `blur(16px)`, `rgba(20, 25, 30, 0.5)`, `Cache-Control: no-cache, no-store, must-revalidate` (без печати секретов).
2. **Живые WebView** (Telegram Android, Nekogram/iOS): фактическое применение `-webkit-backdrop-filter`; поведение `@focus select()` на **тапе** (если select не сработает — сработает no-op из Low выше).
3. **Скриншоты §7.5** (desktop 1440×900 / Android / Nekogram).
4. **T-1941 (@Scanner):** независимый re-audit (в т.ч. воспроизведение зонда композитной маски).
