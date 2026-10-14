# Scanner-аудит — round1020 UPD3 (T-1941, независимый re-audit рендера/поведения)

> **Дата:** 17.09.2026 · **Агент:** @Scanner · **Baseline:** HEAD `a67f83d` + рабочее дерево (`web/*`, `tests/*`, `plans/*`).
> **Предмет:** доработка UI round1020 (`round1020-ui-rework`), дефекты 1–5 + Critical-фиксы итерации 2.
> **Цель:** найти то, что пропустил @Reviewer (он проверял реальным Chromium в итерации 2).
> **R18:** реальные секреты не приводились; использованы только маска `••••••••••••`, фейковые `FAKE`/`REALKEY_1`/`PROVKEY_1`.
>
> **Метод (независимый от Reviewer):** собственные зонды — реальный **Chromium 151 (Playwright, Python API)** с
> настоящими `web/static/vendor/tailwind.css` + `web/static/app.css` (CSSOM `getComputedStyle`/`getBoundingClientRect`
> на реальных классах и структурах разметки) + Node-прогон **настоящего** `web/app.js` (адверсариальные кейсы маски)
> + полный pytest + JS-гейты + `git diff`. Grep-«доказательства существования строки» не использовались.

## Сводка severity

| Severity | Кол-во | Статус |
|---|---|---|
| Critical | **0** | — |
| High | **0** | — |
| Medium | **1** | новый (не блокер) |
| Low | **3** | 1 подтверждает Low-итерации-2, 2 новых |
| Info | **3** | — |

**ВЕРДИКТ: нет Critical/High.** T-1941 может быть отмечен; возврат к @Builder не требуется.

---

## 1. Подтверждено (сырые выводы)

### 1.1 Liquid Glass (CSSOM, реальный Chromium)

Токены (`getComputedStyle(documentElement)`): `--glass-bg rgba(20, 25, 30, 0.5)`, `--glass-blur blur(16px)`,
`--grad-speed 6s`, `--grad-d #FF8A3D`, `--sticky-save-h 4.5rem`.

Computed (viewport 1440 / 400 — совпадает):
```
.modal-card   bg rgba(20, 25, 30, 0.5) | backdrop blur(16px) saturate(1.4) | border 1px solid rgba(255,255,255,0.12)
.card         bg rgba(20, 25, 30, 0.5) | blur(16px) saturate(1.4)
.module-card  bg rgba(20, 25, 30, 0.5) | blur(16px) saturate(1.4)
.hub-card     bg rgba(20, 25, 30, 0.5) | blur(16px) saturate(1.4)
.prov-block   bg rgba(20, 25, 30, 0.5) | blur(16px) saturate(1.4)   ← standalone (вне .modal-body)
details.advanced  bg rgba(20,25,30,0.5) | blur(16px)
.scope-panel  bg rgba(20, 25, 30, 0.5) | blur(16px) saturate(1.4)   (несмотря на класс card-solid — инертен)
.glass-panel  bg rgba(20, 25, 30, 0.5) | blur(16px) saturate(1.4)
sticky-save   bg rgba(20, 25, 30, 0.85) | blur(16px)
```
Вложенные карточки не «кирпич»:
```
.card .card            → rgba(255,255,255,0.04), backdrop none
.modal-body .card      → rgba(255,255,255,0.04), backdrop none
```
Grid-контейнеры прозрачны:
```
.prov-grid / .module-list / .hub-grid → background rgba(0,0,0,0) | blur none | border 0px none
```
Tailwind `bg-*` на узлах стекла — **0**; `card-solid` в разметке — **2** (`header.header-sticky`, `scope-panel`),
обе вне модалок. `modal-card card card-solid` — **0**.

**Каверат зонда (не дефект):** `.modal-body .card` перебивает стекло `.prov-block`, **если** prov-block окажется
внутри модалки; в реальной разметке prov-blocks живут в ветке `llm_providers` (не в `.modal-body`) → эффект не возникает.
`.hub-card` border-color в момент замера интерполирован transition'ом (`transition: border-color .12s`) — артефакт замера, целевое
значение `rgba(255,255,255,0.12)`.

### 1.2 Grid (≥2 трека)

```
viewport 1440 → .prov-grid "348px 348px 348px 348px" (4) при контейнере 1408px
              .module-list "356px 356px 356px" (3)
              .hub-grid  "330.656px 330.672px 330.656px" (3)
viewport 1000 → .prov-grid "322.656px 322.672px 322.656px" (3)
viewport 999  → 3 трека; viewport 400 → все "400px" (1fr по @media ≤479px)
```
Ветка «ИИ» (`index.html:214`, `365`) — класс `prov-grid`; `max-w-3xl` в разметке — **0 вхождений**.
`.hub-head` внутри `.prov-grid` имеет `grid-column: 1 / -1` (`app.css:276`) → реальный рендер: заголовок на всю ширину
(`hh = [x=0, w=1408]`), блоки ниже — не ломает сетку (Reviewer этого не измерял).

### 1.3 Маска секретов (адверсариальный Node-прогон на реальном `app.js`)

Дополнительно к кейсам теста T-1939 (которые я прогнал) проверены НЕ покрытые сценарии:
```
A saveBlock: draft.base_url изменён + секрет-композит mask+'REALKEY'
  → 1 POST, body ["models.llm_base_url"="https://new/v1"]  (секрет отброшен, несекретное сохранено)  PASS
B saveBlock: draft.base_url изменён + РЕАЛЬНЫЙ новый ключ 'REALKEY_1'
  → 1 POST, 2 items, keys.llm_api_key="REALKEY_1"                                                    PASS
C testBlock: base_url+model изменены + секрет-композит
  → body {"block":"b3","base_url":"https://db/v1","model":"m1","api_key":""}  (сентинела нет)         PASS
D saveKeyItem(композит mask+'typed') → 0 POST, toast ["Уже сохранено","warn"]                          PASS
E dirtyKeyItems(композит) = 0; (реальный) = 1                                                          PASS
F не-секретное поле, текст которого СОДЕРЖИТ сентинел → сохранено ВЕРБАТИМ (guard не применяется)     PASS
G hasSecretMask(mask+X|X+mask|''|null|undefined|12345) — семантика корректна                              PASS
```
**Иные пути утечки маски — не найдены:** `kv-editor`/`list-editor` (источники в `services/param_catalog.py:1646-1653`)
не могут получить `secret=True` запись (`_KEYS` → 2-кортеж без widget; `widget` только у limits/reactions/prompts —
не секреты); `saveConfigItem` (тумблеры/select) недостижим для секретов (`dirtyItems` исключает `secret`/`keys`).
Секреты в модульной модалке идут только через `keyDrafts` → `saveKeyItem`.

**Бэкенд-совместимость фикса подтверждена:** `services/llm_probe.py:308-311` — при пустом `api_key`
резолвится **сохранённый** ключ блока («пустой api_key → резолвим сохранённый ключ блока»). Поэтому
`testBlock`/`testField`, отправляющие `''` вместо маски, не ломают «Проверить» для уже настроенного провайдера.
`/api/config` всегда маскирует секреты `{configured,last4}` (`web/api/routes.py:231-240`) — сырое значение в инпут не попадает.

### 1.4 Градиент

```
--grad-d #FF8A3D; --grad-speed 6s (∈ [5,8])
body::before: conic-gradient(... rgb(102,78,160), rgb(20,203,182), rgb(255,138,61), ...), opacity 0.42,
              animationName "grad-spin, grad-drift", animationDuration "6s, 6s"
prefers-reduced-motion:reduce → animationName none, opacity .35, linear-gradient(...)
prefers-contrast:more         → animationName none, opacity 1
```

### 1.5 Sticky

Modal-ветка (`.modal-card > .modal-body > … + .sticky-save`), 40 полей, 1440×800:
```
scroller .modal-body: clientH 604, overflowY auto, paddingBottom 0px, scrollPaddingBottom 72px
stickyBottom = 700.6, scrollerBottom = 701 → зазор 0.4px; lastFieldBottom = 634.4 → gap_last_to_sticky +8px
overlap = false
```
Scroll-area ветка — см. Medium-1 (есть зазор). Inline `max-height:80dvh/70dvh` — **0**; `.modal-body` без inline `max-height`.

### 1.6 Инварианты/регрессии

- Меню: 25 вкладок (JS-снимок `round1020_ui_rework_test.js`), **6** NAV_ITEMS (`app.js:282-291`), 12 модулей — не изменены.
- `git diff --name-only -- services/ web/api/ web/app.py web/static/vendor/` → **пусто**; `services/param_catalog.py` Δ=0.
- R18-скан изменённых/новых файлов (`sk-…`, `ghp_…`, `AKIA…`, `AIza…`) — **0 совпадений**; в тестах только `FAKE`/`REALKEY_1`.
- `git diff --check` → clean (только LF/CRLF-warning).

### 1.7 Прогоны

```
.venv/Scripts/python.exe -m pytest tests/ -q --timeout=300   → 6572 passed, 1 warning in 101.16s
tests/test_webapp_api.py::TestStatic + tests/test_webapp_ui_rework_round1020.py → 41 passed
node --check web/app.js            → OK
node tests/js/routing_test.js      → JS-UNIT-OK
node tests/js/vue_mount_test.js    → VUE-MOUNT-OK
node tests/js/round1020_ui_test.js → JS-UNIT-OK
node tests/js/round1020_ui_rework_test.js → JS-UNIT-OK
git diff --check                   → clean
```

---

## 2. Findings

### [Medium] M-1 — sticky-save «висит» на 88px выше низа экрана в config-вкладках (fullscreen)

**Файл:** `web/static/app.css:895-898`
```css
.scroll-area:has(> .sticky-save) {
  padding-bottom: calc(1rem + var(--sticky-save-h));   /* 88px */
  scroll-padding-bottom: var(--sticky-save-h);
}
```
**Проблема:** `padding-bottom` у скролл-контейнера сдвигает **content-box** вверх; `position: sticky; bottom: 0` у панели
не может выйти за content-box, поэтому панель постоянно прижата к нижней границе контент-бокса, а не к низу вьюпорта.
Сырые замеры (Chromium, 1440×800, `main.scroll-area` = скроллер, `<div class="sticky-save">` — прямой child):
```
scrollTop=0    → sticky.bottom = 712, scrollport.bottom = 800   (bandBelow = 88)
scrollTop=1000 → sticky.bottom = 712                            (bandBelow = 88)
scrollTop=max  → sticky.bottom = 712                            (bandBelow = 88)
контроль (padding-bottom:0 !important) → sticky.bottom = 800    (bandBelow = 0)
```
Итог: 88px пустой полосы **всегда** под панелью в fullscreen (⛶) на config-вкладках; визуально панель «парит» в середине низа.
Modal-ветка сделана правильно — только `scroll-padding-bottom` (`app.css:886-892`) → панель прижата к низу (зазор 0.4px).
**Почему пропустил Reviewer:** итерация 1 измерила `padding-bottom:88px` как PASS, не заметив, что padding **смещает саму панель**;
итерация 2 config-ветку не переизмеряла.
**Рекомендация:** убрать `padding-bottom` у `.scroll-area`, оставить только `scroll-padding-bottom` (как `.modal-body`);
либо `margin-bottom` у последнего контент-элемента. Функционально не блокирует (панель видима/кликабельна, данные не теряются).

### [Low] L-1 — `@focus select()` + `@mouseup.prevent` на **всех** provider-полях, включая не-секретные

**Файл:** `web/index.html:244`, `:281`, `:380`
**Сырой вывод (Chromium, реальные обработчики focus→select + mouseup→preventDefault на input с `abcdefghijkl`):**
```
1-й клик в конец поля → selection [0,12]; повторный клик → снова [0,12]; клик в середину → [0,12]
ввод 'Z' → value "Z" (полная замена)
контроль без mouseup.preventDefault → 1-й клик [12,12], ввод → "abcdefghijklX"
```
Мышь **не может** поставить каретку в не-секретных полях (`display_name`/`base_url`/`model`) — каждый клик выделяет всё;
клавиатура работает (`Home/End/←→`). На R31/сохранение не влияет; Review-итерация-2 отметила это как Low — **подтверждаю Low**.
Рекомендация: `@focus="f.secret && $event.target.select()"`, `@mouseup="f.secret && $event.preventDefault()"`.

### [Low] L-2 — композит маски и «Уже сохранено»: silent-no-op на WebView без рабочего select

**Файл:** `web/app.js:3877` (toast) + `web/app.js:1358-1368` (`dirtyKeyItems`).
Тост «Уже сохранено» при композите вводит в заблуждение (значение **не** сохранено), но через UI недостижим:
`dirtyKeyItems` отфильтровывает композит → sticky-панель пишет «Нет изменений», `saveModalEdits` не вызывает `saveKeyItem`.
Сырой вывод (Node, реальный `app.js`): `saveKeyItem(mask+'typed') → 0 POST, toast ["Уже сохранено","warn"]`.
Следствие: если на конкретном Android/iOS WebView `@focus select()`/`@mouseup.prevent` не дадут select-all, набранный
ключ молча не сохранится (guard защищает от порчи, но UX теряет ввод). На проверенном Chromium сценарий не воспроизводится.
Рекомендация (фоллоу-ап): текст «Поле изменено — введите ключ заново» или авто-очистка маски при первом вводе (input-хук).

### [Low] L-3 — `@supports not (:has())` добавляет 88px всем `.scroll-area`

**Файл:** `web/static/app.css:899-901`. Фолбэк `@supports not (selector(:has(*)))` вешает `padding-bottom: 88px`
на **любой** `.scroll-area`, включая ветки без `.sticky-save` (например, «Модули») → на старых WebView постоянная
пустая полоса снизу. Некритично; следствие того же M-1.

### [Info] I-1 — `isSecretMask` остаётся строгим равенством и не используется рантаймом

`web/app.js:18` + экспорт `:3871`. Рантайм-пути используют только `hasSecretMask`; `isSecretMask` вызывается лишь тестами.
Двусмысленный публичный метод — риск будущего ошибочного применения. Рекомендуется удалить или явно задокументировать.

### [Info] I-2 — `--surface-glass` сохранён как алиас (`.5`), потребителей нет (`app.css:9-11`).

### [Info] I-3 — `data.secretMask` (`app.js:908`) не потребляется рантаймом (контракт/тесты).

---

## 3. Проверка DoD (T-1941)

| Пункт | Статус | Доказательство |
|---|---|---|
| Независимо воспроизвести зонды T-1940 | ✅ | CSSOM Chromium: glass/blur/grid/gradient/sticky |
| Меню/навигация/разделы не изменены | ✅ | 25 tabs / 6 nav / 12 modules |
| served-CSS / отсутствие «пустого» CSS | ✅ | `TestStatic` + `test_webapp_ui_rework_round1020.py` → 41 passed (локально) |
| R18: `plans/**` и отчёты без значений | ✅ | скан patterns — 0 |
| Finding-таблица + ре-проверка закрытий | ✅ | этот отчёт |
| Композит маски (Critical-1) во всех путях | ✅ | Node-кейсы A–G |
| `@focus select` на provider-полях (Critical-2) | ✅ (с оговоркой L-1) | Chromium-замер [0,12] на первом клике |
| Регресс-тесты (High-1) | ✅ | `round1020_ui_rework_test.js` JS-UNIT-OK |

## 4. Ограничения

1. **Прод-хост** `/static/app.css` (T-1942/@DevOps) — **не проверен** до деплоя.
2. **Живые WebView** (Telegram Android, Nekogram/iOS WKWebView): фактическое применение `-webkit-backdrop-filter`,
   поведение `select()`/`:has()` на тапе — недоступны; проверялись Chromium 151 + статический `@supports`-фолбэк.
3. Замеры sticky — на воспроизведённых структурах разметки (`main.scroll-area` / `.modal-body`), не на полном
   Vue-рендере живого приложения (стабы `/api/*` не поднимались).
4. Скриншоты визуальной приёмки §7.5 (desktop/Android/Nekogram) — не приложены.

## 5. Что осталось проверить после деплоя

1. T-1942: прод-`/static/app.css` → `blur(16px)`, `rgba(20, 25, 30, 0.5)`, `Cache-Control: no-store` (без печати секретов).
2. Живые WebView: маска + тап; поведение `:has()`/`select()`; `-webkit-backdrop-filter`.
3. Визуально: M-1 (88px полоса под sticky-панелью в fullscreen config-вкладках) — решить, чинить ли фоллоу-апом.
4. Скриншоты §7.5.
