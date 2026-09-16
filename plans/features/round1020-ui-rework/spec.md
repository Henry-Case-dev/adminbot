# spec.md — `round1020-ui-rework` (UPD3: исправление UI-дефектов эпика 10.20)

> **Статус:** ARCHITECTURE_READY (Шаг 2, режим доработки)
> **Источник требований:** `plans/current_task.md` §UPD3 (строки 365–403), R18 (Secret Scrubbing).
> **Базовый эпик (проваленная UI-часть):** `plans/archive/round1020-lore-compiler-rag-refactor/` §5 (БЛОК 3: T-1894…T-1902).
> **Область:** ТОЛЬКО фронтенд мини-аппа (`web/index.html`, `web/app.js`, `web/static/app.css`) + осознанное обновление тестов. Код бота/сервисов — вне скоупа (см. §9).
> **R18:** в документах и коде не появляется ни одного секрета/пароля; в примерах — только маска `••••••••••••`.

---

## 0. Резюме root-cause (почему заявленные Liquid Glass / Grid не появились)

Три независимые причины, каждая из которых по отдельности достаточна для провала:

| # | Root cause | Доказательство | Тип |
|---|---|---|---|
| RC-A | **Правило Liquid Glass накрыло не те селекторы.** Основной потребитель — класс `.card` (**94 вхождения** в `web/index.html`), и он в группу glass **не входит**; он читает `--surface-glass: rgba(22,22,22,.72)` (alpha .72) и поверх почти чёрного `--surface-0:#0E0E0E`. Визуально = сплошной тёмный. | `web/static/app.css:8,120-128,786-797`; `web/index.html` — 94 `class="…card…"` | CSS/селекторы |
| RC-B | **Backdrop «стекла» нечем блюрить.** Page-wash (`body::before`) собран из «скучных» цветов с `opacity:.16` и `animation: grad-drift 18s`; база — плотный `body{background:#0E0E0E}`. Прозрачность .5–.72 поверх равномерно-тёмного фона неотличима от solid. | `web/static/app.css:18-19,92-107` | палитра/фон |
| RC-C | **На модалках включён «solid-убийца».** Разметка несёт `class="modal-card card card-solid …"`; `.card-solid{background:rgba(22,22,22,.88)}`, а `@supports not` фолбэк добивает `.modal-card` до `rgba(22,22,22,.92)` на WebView без `backdrop-filter`. Спасает только порядок исходников — контракт хрупкий и противоречивый. | `web/index.html:746,1259,1311,1452,2658`; `web/static/app.css:129-131,804-806` | каскад/инверсия замысла |

**Дополнительно (Grid):** T-1899 фактически поменял только `auto-fill → auto-fit` + центровку у `.module-list`/`.hub-grid`, а ветка **«ИИ» = `llm_providers`** (единственный реально одноколоночный раздел) получает свою разметку из блока `web/index.html:214-220` — `<div class="col-span-full grid gap-3">` + `.prov-block … max-w-3xl mx-auto`, **без auto-fit-контейнера**. Это и есть «Grid проигнорирован» на «ИИ».

**Дополнительно (пустые поля):** секреты **никогда** не префиллятся — так было спроектировано и закреплено тестом (`tests/js/round1020_ui_test.js:120-122`: «секрет НЕ префиллится (маска)»), а маска жила только в `placeholder`/бейдже. Секрет, у которого нет ни значения в поле, ни бейджа (generic-модалка модуля, `web/index.html:798-807`), выглядит «абсолютно пустым».

**Отвергнутые (проверено — НЕ причина):**
- **CSS-файл не подключён.** Подключён вторым, после Tailwind: `web/index.html:19` (tailwind) → `:22` (app.css). `/static/app.css` отдаётся выделенным маршрутом с `Cache-Control: no-cache, no-store, must-revalidate` (`web/app.py:240-245`) — stale-cache версия **исключена** (см. §7.6 — всё равно перепроверить на прод-хосте).
- **Tailwind-утилиты `bg-*` перебивают glass.** В разметке `bg-white/10`, `bg-violet-600`, `bg-black/20` стоят только на тумблерах/логах/чипах, **не** на `.card`/`.modal-card`/панелях. Tailwind — предсобранный, без `!important` и без CSS-layers. Единственный «solid-surface» — проектный класс `.card-solid` (RC-C).
- **`app.css` затёрт Tailwind preflight.** Preflight не задаёт `background` для `.card`/`.modal`.
- **`APP_VERSION` не поднят.** `config/settings.py:1274` = `2.57.0` не менялся в коммите раунда — но `app.css` отдаётся `no-store`, поэтому роли не играет (кэш-бастинг `?v=` влияет только на субсет шрифта, `web/static/app.css:50-58`). **В рамках фикса APP_VERSION не трогаем.**

---

## 1. Дефект 1 — Liquid Glass не работает (сплошные тёмные фоны)

### 1.1 Root cause (с `файл:строка`)
1. `.card` не входит в glass-группу, alpha `.72`: `web/static/app.css:8` (`--surface-glass:rgba(22,22,22,.72)`), `:120-128` (`.card{background:var(--surface-glass);backdrop-filter:blur(20px)…}`), `:786-797` (группа glass без `.card`).
2. `.card-solid` (alpha `.88`) стоит **вместе** с `.modal-card` в 5 модалках: `web/index.html:746,1259,1311,1452,2658`.
3. `@supports not (backdrop-filter)` → `.glass-panel,.modal-card{background:rgba(22,22,22,.92)}`: `web/static/app.css:804-806` (WebView без поддержки = гарантированно solid).
4. `blur` = `12px` (токен `:34`) и `20px` (`.card` `:123`) вместо требуемых `16px`.
5. Backdrop прозрачности не даёт: `web/static/app.css:92-107` (см. Дефект 4).
6. Селектор `.oversight-panel` (`:788`) в разметке **отсутствует** — мёртвый селектор; «Сводка» держится только на `.glass-panel` (`web/index.html:975`).

### 1.2 Целевой контракт (обязателен)
**Токены** (`web/static/app.css`, блок `:root`):
```css
--glass-bg: rgba(20, 25, 30, 0.5);          /* требование ТЗ */
--glass-bg-strong: rgba(20, 25, 30, 0.85);  /* sticky/шапка/фолбэк — читаемость */
--glass-blur: blur(16px);                   /* требование ТЗ */
--glass-border-color: rgba(255, 255, 255, 0.12);
--glass-border: 1px solid var(--glass-border-color);
```
**Правило применения** («glass set» — несёт стекло):
```css
.card,
.modal-card,
.module-card,
.hub-card,
.prov-block,
details.advanced,
.scope-panel,
.glass-panel,
.oversight-panel,
.sticky-save {
  background-color: var(--glass-bg);
  -webkit-backdrop-filter: var(--glass-blur) saturate(140%);
  backdrop-filter: var(--glass-blur) saturate(140%);
  border: var(--glass-border);
}
```
**НЕ несёт стекло** (grid-контейнеры — только раскладка): `.module-list`, `.hub-grid`, `.prov-grid` → `background: transparent; border: 0; backdrop-filter: none;`.
Обязательные условия:
- **G1.1** `.card` и `.modal-card` входят в glass set (иначе RC-A воспроизводится).
- **G1.2** Из всех 5 модалок удалить класс `card-solid`: `class="modal-card card card-solid p-5 …"` → `class="modal-card card p-5 …"`. Запрещённая комбинация `modal-card card card-solid` в `index.html` — **0 вхождений** (проверяется тестом).
- **G1.3** `.card-solid` остаётся только там, где действительно нужна плотная подложка: `.scope-panel` (`web/index.html:67`) и `header.header-sticky` (там уже перебит `rgba(22,22,22,.96)`, `web/static/app.css:604-611`). Никаких `!important`.
- **G1.4** `@supports not` фолбэк переписать на glass set и `--glass-bg-strong`:
  ```css
  @supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .card, .modal-card, .module-card, .hub-card, .prov-block,
    details.advanced, .scope-panel, .glass-panel { background-color: var(--glass-bg-strong); }
  }
  ```
- **G1.5** (читаемость, НЕ-обязательно) вложенные карточки не блюрят повторно: `.card .card, .modal-body .card { backdrop-filter: none; -webkit-backdrop-filter: none; background-color: rgba(255,255,255,.04); }` — чтобы alpha не складывалась до solid.
- **G1.6** Контейнеры `.hub-grid`/`.module-list`/`.prov-grid` **исключить** из glass set и обнулить (`border:0; background:transparent; backdrop-filter:none`) — устраняет «панель-слэб/рамку вокруг сетки» и даёт blur карточкам, а не обёртке.
- **G1.7** `.modal-backdrop` сохраняет затемнение `rgba(0,0,0,.5)` + `blur(16px)` (согласовать с токеном).

### 1.3 Разметка/размеры
- `.modal-card` получает `border-radius: var(--radius-lg)` и `overflow: hidden` (иначе фон карточек вылезает за скругление) — см. Дефект 5.

---

## 2. Дефект 2 — CSS Grid проигнорирован («Модули»/«ИИ» — одна колонка)

### 2.1 Root cause
- **«ИИ» (`llm_providers`):** контейнер карточек — `<div v-if="activeTab === 'llm_providers'" class="col-span-full grid gap-3">` (`web/index.html:214`). У него **нет** `grid-template-columns` → одна колонка по умолчанию. Карточки — `<section class="prov-block card p-4 max-w-3xl mx-auto w-full">` (`web/index.html:220,364`) → ширина ограничена 768px и центрируется. Это единственный реально одноколоночный раздел.
- **«Модули» (`modules`):** `.module-list` (`web/static/app.css:239-246`) имеет `repeat(auto-fit, minmax(300px,1fr))`, но контракт ТЗ требует `minmax(320px)` и `gap:1rem`; значения 300px/.75rem + `max-width:1100px` дают 1–2 колонки на ноутбучной ширине и не «заполняют пространство».
- `.hub-grid` (`:264-270`) — то же (300px/.75rem), плюс правило мобильного схлопывания `@media (max-width:479px){.hub-grid{grid-template-columns:1fr}}` (`:314-315`) — оставить.

### 2.2 Целевой контракт
- **G2.1** Единый класс-контейнер `prov-grid` для ветки «ИИ»: `<div v-if="activeTab === 'llm_providers'" class="col-span-full prov-grid">` (`web/index.html:214`).
- **G2.2** Новое правило:
  ```css
  .prov-grid,
  .module-list,
  .hub-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 1rem;
    width: 100%;
    align-content: start;
  }
  ```
  Центровку (`justify-content:center; max-width; margin-inline:auto`) можно сохранить, но `max-width` не должен давать <2 колонок на десктопе (проверяется визуально в §7.5).
- **G2.3** Снять `max-w-3xl mx-auto` с `.prov-block` (`web/index.html:220,364`) — карточки заполняют трек; при необходимости оставить `max-w-none`.
- **G2.4** Мобильное поведение: `@media (max-width: 479px){ .prov-grid, .hub-grid, .module-list { grid-template-columns: 1fr; } }` (сохранить существующую логику).
- **G2.5** Контейнер `.prov-grid` не должен иметь `col-span-full` внутри вложенной `grid`-ветки с иным track-контекстом — при необходимости заменить на `grid-column: 1 / -1` в CSS.
- **G2.6** Сетки «Сводка» (`main` `web/index.html:141-142`, inline `repeat(auto-fill, minmax(320px,1fr))`) — НЕ трогать, кроме выноса inline-стиля в класс (опционально).

---

## 3. Дефект 3 — КРИТИЧНО: пустые поля ввода (`Пароль/Пользователь Betterstack SQL`)

### 3.1 Цепочка root cause (catalog → API → state → render)
| Звено | Факт | Файл:строка |
|---|---|---|
| Каталог | `CHECKUP_BETTERSTACK_SQL_USER` и `CHECKUP_BETTERSTACK_SQL_PASSWORD` помечены `secret=True`, категория `keys_betterstack` | `services/param_catalog.py:503-506`, `GroupSpec` `:183-184` |
| Таб | Вкладка «Диагностика» = `TAB_MOD_CHECKUP`; маппинг `(CATEGORY_KEYS, {"keys_betterstack"})` | `services/param_catalog.py:1952-1958`, `:1846` |
| API | Секреты **всегда** отдаются как `{configured, last4}` (и для global admin) | `web/api/routes.py:231-240` (маска), `:341-342` (применение) |
| Состояние | `keyDrafts` живёт отдельно от `configItems`; при загрузке сбрасывается в `{}`, маска нигде не сеется | `web/app.js:3446-3460` (loadConfig), `:2652` (cancel) |
| Рендер | 3 места биндят `v-model="keyDrafts[item.key]"` → **пустая строка**; маска — только в `placeholder` или бейдже | `web/index.html:553-556` (+бейдж `:549`), `:638-641` (+бейдж `:634`), `:798-805` (**без бейджа — «абсолютно пусто»**) |
| Тест-«замок» | Тест прямо закрепляет пустой инпут: «секрет НЕ префиллится (маска)» | `tests/js/round1020_ui_test.js:120-122` |

**Вывод:** это не «упавший two-way binding» для обычных полей (там `v-model="item.value"` работает), а **осознанно write-only рендер секретов** + отсутствие маски-значения в самом инпуте. На вкладке «Диагностика» (generic-ветка) пользователь видит пустое поле и лишь `placeholder`/бейдж.

### 3.2 Целевой контракт (инвариант)
> **INV-3:** Если для параметра в БД есть непустое значение, то по месту его рендера инпут **не пуст**: не-секрет → фактическое значение; секрет (`{configured:true}`) → маска `••••••••••••`. Пусто — **только** при реальном `null`/`undefined`/`''`/`{configured:false}`.

Реализация (единый механизм, во всех ветках):
- **G3.1** В `web/app.js` ввести константу `SECRET_MASK = '••••••••••••'` (ровно 12 символов) и предикат `isSecretMask(v)`.
- **G3.2a** **Путь provider-блоков:** `blockFieldValue` (`web/app.js:2813-2820`) при `it.value` = объект `{configured:true, …}` возвращает `SECRET_MASK` (а не `''`); при `{configured:false}`/`null` → `''`; строка → как есть. `blockFieldPlaceholder` (`:2848-2854`) сохраняется как подсказка «Новый ключ (заменить)…».
- **G3.2b** **Путь generic/modal keys:** метод `_seedSecretMasks()`: для каждого `item` из `configItems`, где `(item.category === 'keys' || item.secret) && isKeyConfigured(item) && !keyDrafts[item.key]` → `keyDrafts[item.key] = SECRET_MASK`. Вызывать: в конце `loadConfig` (после `:3446`/`:3460`), в `_snapshotConfig`, в `cancelModalEdits` (вместо `keyDrafts = {}`, `:2652`), и после успешного `saveKeyItem` (`:3842`).
- **G3.3** `dirtyKeyItems` (`web/app.js:1344-1352`), `blockDrafts` и `saveModalEdits` (`:2656+`) считают маску **не-изменением**: `drafts[it.key] && !isSecretMask(drafts[it.key])`.
- **G3.4** `saveKeyItem` (`:3823-3852`) и `saveBlock` (`:2927-2950`) при `isSecretMask(value)` не делают POST (тихий no-op / `return false`, опционально тост «значение уже сохранено»).
- **G3.5** UI-подсказка: в `web/index.html:798-807` добавить тот же бейдж `configured ••••` (как `:549`/`:634`) — чтобы место без маски было невозможно спутать с «не настроено». Класс `input` — `field` + `autocomplete="off"` (уже есть).
- **G3.6** Фокус на поле с маской: `@focus` → выделить текст (`$event.target.select()`), чтобы первое нажатие заменяло маску (стандартный UX «Новый ключ (заменить)…»).
- **G3.7** Секреты НЕ логировать и НЕ отправлять: маска — UI-сентинел; она не должна попадать ни в `POST /api/config`, ни в `configSnapshot`, ни в `blockDrafts`/`keyDrafts` как «пользовательский ввод» (guard в `saveBlock`/`saveKeyItem`; `_snapshotConfig` `:2638-2643` читает `configItems`, а не черновики — проверить и покрыть тестом).
- **G3.8** `inputType` (`web/app.js:3731-3734`) не меняется; секретное поле по-прежнему `type=password` (до `keyReveal`).
- **G3.9** **Проверить во ВСЕХ модулях** — все 3 точки бинда `keyDrafts` (`:556`, `:641`, `:805`) + LLM-провайдеры (`blockFieldPlaceholder` `web/app.js:2848-2854`, уже показывает `configured ••••last4`) должны удовлетворять INV-3. Каталог/бэкенд **не трогаем**: оба Betterstack-поля остаются секретами (см. ADR D5).

---

## 4. Дефект 4 — Фоновый градиент (5–8 s, +оранжевый, углы, reduced-motion)

### 4.1 Root cause
- Палитра без тёплого: `--grad-a/b/c` = фиолетовый/бирюза/лаванда — `web/static/app.css:18`.
- Page-wash: `background: linear-gradient(120deg, a,b,c)`, `opacity:.16`, `animation: grad-drift 18s … alternate`, база `body{background:#0E0E0E}` — `web/static/app.css:92-107`. Медленно, бледно, «скучно».
- Акценты (`.grad-band/.btn-accent/.tab-btn.active`) крутят `--grad-angle` через `grad-spin var(--grad-speed)` (14s) — `:74-81`.

### 4.2 Целевой контракт
```css
:root {
  --grad-a:#664EA0;   /* фиолетовый  */
  --grad-b:#14CBB6;   /* циан/бирюза */
  --grad-c:#8D6BDC;   /* лаванда/сирень */
  --grad-d:#FF8A3D;   /* ОРАНЖЕВЫЙ (новое требование) */
  --grad-speed:6s;    /* 14s → 6s: 5–8 s (T-1937); покрывает и wash, и акценты */
  --grad-ease:cubic-bezier(0,0,.2,1);
}
@keyframes grad-spin { from { --grad-angle: 0deg; } to { --grad-angle: 360deg; } }
@keyframes grad-drift { from { background-position: 0% 50%; } to { background-position: 100% 50%; } }
body::before {
  content:''; position:fixed; inset:-10%; z-index:0; pointer-events:none;
  background: conic-gradient(from var(--grad-angle) at 50% 50%,
    var(--grad-a), var(--grad-b), var(--grad-d), var(--grad-c), var(--grad-a));
  background-size: 200% 200%;
  animation: grad-spin var(--grad-speed) linear infinite,
             grad-drift var(--grad-speed) var(--grad-ease) infinite alternate;
  opacity:.42;
}
html { background-color: var(--surface-0); }
body { background: transparent; }
#app { position: relative; z-index: 1; }
```
- **G4.1** `opacity` поднять с `.16` до `≈.40–.45`; конусный градиент с вращающимся `--grad-angle` даёт явно видимые переливы (углы «отрегулированы»).
- **G4.2** `--grad-speed` строго в диапазоне **5–8 s** (значение **6s**). Единый токен (T-1937): он же ускоряет `.grad-band`/`.btn-accent`/`.tab-btn.active` — принимается осознанно (14s воспринималось как «неживое»), с `prefers-reduced-motion`-гашением.
- **G4.3** Fallback без `@property` (движки без интерполяции custom-property): второй `animation: grad-drift …` уже обеспечивает движение `background-position` — сохранить.
- **G4.4** `prefers-reduced-motion` — обязательно:
  ```css
  @media (prefers-reduced-motion: reduce) {
    body::before { animation: none !important; opacity:.35;
      background: linear-gradient(135deg, var(--grad-a), var(--grad-b), var(--grad-c)); }
    .grad-band, .btn-accent, .tab-btn.active { animation: none !important; }
    :root { --grad-angle: 135deg; }
  }
  ```
- **G4.5** `@media (prefers-contrast: more)` — сохранить отключение фоновой анимации (расширить селектор `body::before`, как сейчас `:113-118`).
- **G4.6** Оранжевый входит в stops `conic-gradient` (`.grad-band/.btn-accent/.tab-btn.active`, `:76-80`), в `body::before` (`:103`) и, при желании, в `--accent-grad` (`:40`) — «оранжевый к сиреневому/циану».
- **G4.7** Градиент — единственный источник «подсветки» для glass: без видимого wash `backdrop-filter: blur(16px)` неотличим от solid (RC-B). Дефекты 1 и 4 обязаны ехать одним релизом.

---

## 5. Дефект 5 — Sticky-панель: сломала отступы, перекрывает контент

### 5.1 Root cause
- Панель **модалки** лежит в `.modal-footer`, который стоит **после** скролл-контейнера `.modal-body` (inline `style="max-height:80dvh;overflow-y:auto"`): `web/index.html:758` (body) → `:964-969` (footer). `position:sticky;bottom:0` вне скролл-контейнера → панель не «прилипает», а висит в обычном потоке и/или всплывает относительно вьюпорта при переполнении карточки.
- `padding:.5rem .25rem .25rem` + `margin-top:.75rem` + `modal-footer mt-3` + `modal-card p-5` → асимметричные/двойные отступы: `web/static/app.css:809-822`.
- `background: var(--glass-bg)` (alpha .6) + blur → сквозь панель виден контент (выглядит «перекрывает контент»).
- Вкладки: `<sticky-save class="col-span-full">` — grid-ребёнок `main.scroll-area` (`web/index.html:704,1549`); `bottom:0` + `scroll-padding-bottom` отсутствие → край контента может оказаться под панелью (`web/static/app.css:619-621` — только `padding:1rem`).
- Досье-модалка: `<footer class="sticky-save">` стоит **после** `.modal-body` (`web/index.html:2669→2694`) — та же ошибка.

### 5.2 Целевой контракт
**Единое правило `.sticky-save` (и вкладки, и модалки — sticky сохраняем, T-1938):**
```css
:root { --sticky-save-h: 4.5rem; }
.sticky-save {
  position: sticky; bottom: 0; z-index: 5;   /* в потоке, НЕ absolute */
  display:flex; align-items:center; gap:.5rem;
  padding:.6rem .75rem;
  padding-bottom: calc(.6rem + env(safe-area-inset-bottom, 0px));
  margin:0;
  border-top: var(--glass-border);
  background-color: var(--glass-bg-strong);   /* .85 → контент НЕ просвечивает */
  -webkit-backdrop-filter: var(--glass-blur);
  backdrop-filter: var(--glass-blur);
}
```
**Модалки:**
```css
.modal-card { display:flex; flex-direction:column;
  max-height: min(90dvh, 46rem); overflow:hidden; }
.modal-body { flex:1 1 auto; min-height:0; overflow-y:auto;
  overscroll-behavior:contain;
  scroll-padding-bottom: var(--sticky-save-h); }
.modal-footer { flex:0 0 auto; margin-top:0; }
```
- **G5.1** `<sticky-save>` переносится **внутрь** скролл-контейнера `.modal-body` последним ребёнком (сейчас — снаружи, в `.modal-footer`, `web/index.html:964-969`): `position:sticky;bottom:0` работает только внутри скроллера. `.modal-footer` остаётся для кнопки «Закрыть».
- **G5.2** Убрать inline `style="max-height:80dvh;overflow-y:auto;"` из 4 модалок и `max-height:70dvh` из досье (`web/index.html:758,1269,1321,1462,2669`) — размер живёт в CSS (`.modal-body`).
- **G5.3** Досье-модалка: `<footer class="sticky-save">` (`web/index.html:2694`) переносится внутрь `.modal-body` (перед `</div>` `:2693`).
- **G5.4** Панель остаётся в потоке на позиции конца контента → на максимальном скролле последнее поле **видно** (панель ниже него), транзиентное наложение при скролле — штатное поведение sticky-action-bar.
- **G5.5** `scroll-padding-bottom`/`padding-bottom` скролл-контейнера ≥ `--sticky-save-h` — фокус/`scrollIntoView` не уезжает под панель.
- **G5.6** Единый вертикальный ритм: `margin:0`; `padding:.6rem .75rem`; `mt-3` у `.modal-footer` убрать (устранить «сломанные отступы»).

**Конфиг-вкладки (панель — grid-ребёнок `main.scroll-area`):**
```css
.scroll-area:has(> .sticky-save) {
  padding-bottom: calc(1rem + var(--sticky-save-h));
  scroll-padding-bottom: var(--sticky-save-h);
}
@supports not (selector(:has(*))) {
  .scroll-area { padding-bottom: calc(1rem + var(--sticky-save-h)); }
}
```
- **G5.7** Панели обязаны присутствовать во **всех** ветках сохранения (config/modules/access — регресс S10.20-1 не возвращать).

---

## 6. Feature Flags / Progressive Delivery

- **Оценка релевантности:** фикс — UI/CSS-only. Серверный feature-flag (`services/feature_gates.py`) **не требуется** (ADR D6): включение/выключение булева гейта не управляет CSS, а вносит лишнюю связанность.
- **User-level progressive delivery:** `@media (prefers-reduced-motion: reduce)` (G4.4) и `@media (prefers-contrast: more)` (G4.5) — обязательные «per-user» деградации анимации/контраста.
- **Kill-switch без редеплоя (опционально, CSS-level):** вынести интенсивность wash в токен `--grad-opacity`. @DevOps может откатить визуал правкой одного токена; полноценный откат — `git revert` коммита (атомарный).
- **Rollback:** один коммит = один revert. Миграций БД/контрактов нет (кроме правок `plans/**` и тестов).
- **Кэш-гейт доставки (T-1938/T-1942):** `/static/app.css` отдаётся `no-store` (`web/app.py:240-245`), поэтому бамп `APP_VERSION` (`config/settings.py:1274`) для CSS **не обязателен**; `?v=__APP_VERSION__` критичен только для субсета шрифта (`web/static/app.css:50-58`). НО T-1940/T-1942 **обязаны** подтвердить, что прод-хост отдаёт новый CSS; если нет — единственная не-CSS причина «UI не изменился» (бамп `APP_VERSION`/проверка Caddy).

---

## 7. Стратегия тестирования (обязательная)

### 7.1 Принцип
Прошлый провал вызван **string-presence** проверками: тесты искали подстроки токенов (`tests/test_webapp_round1020_ui.py:155-165`, `tests/js/round1020_ui_test.js:435-439`), а не **эффективные** селекторы/каскад/состояние. Все новые проверки обязаны быть **каскад- и состояние-ориентированными**.

### 7.2 Статические CSS-ассерты (новый `tests/test_webapp_ui_rework_round1020.py`, T-1939)
1. `--glass-bg: rgba(20, 25, 30, 0.5)`, `--glass-blur: blur(16px)`, `--glass-bg-strong`.
2. Для **каждого** селектора из glass set (`.card`, `.modal-card`, `.module-card`, `.hub-card`, `.glass-panel`) — найти его правило и убедиться, что `background-color`/`background` ссылается на `var(--glass-bg)` (или `rgba(20,25,30,0.5)`) **и** есть `backdrop-filter` со `blur(16px)`.
3. **Анти-override:** после glass-правила в файле нет правила, задающего непрозрачный `background`/`background-color` для тех же селекторов (скан по всем блокам, где встречается селектор; отдельно — запрет `.card-solid` в паре с `.modal-card`).
4. `'modal-card card card-solid' not in INDEX` — 0 вхождений.
5. `.prov-grid`, `.module-list`, `.hub-grid` содержат `repeat(auto-fit, minmax(320px, 1fr))` и `gap: 1rem`.
6. `.sticky-save` содержит `position: sticky` и `bottom: 0`; `.modal-footer > .sticky-save` — `position: static`; `scroll-padding-bottom` присутствует.
7. Нет inline `max-height:80dvh` / `max-height:70dvh` у `.modal-body`.
8. **Anti-utility:** ни один элемент с классом `modal-card`/`card`/`prov-block`/`hub-card` не несёт Tailwind `bg-`/`bg-[` в `class`-атрибуте (regex по `index.html`).
9. `--grad-d` = оранжевый, `--grad-speed` ∈ [5s, 8s], `@media (prefers-reduced-motion: reduce)` отключает `body::before` и `grad-spin`/`grad-drift`.

### 7.3 JS-юнит-тесты (новый `tests/js/round1020_ui_rework_test.js`, T-1939; расширить `tests/js/round1020_ui_test.js`)
- **Обновить** существующий кейс `T-1895a` (`:100-137`): «секрет НЕ префиллится» → «секрет префиллится **маской**»; `blockFieldValue` для секрета остаётся `''` (LLM-провайдеры — отдельный путь), но `keyDrafts`-ветка → `SECRET_MASK`.
- Новые кейсы:
  - `_seedSecretMasks` из `configItems=[{key:'CHECKUP_BETTERSTACK_SQL_PASSWORD', secret:true, value:{configured:true,last4:'XXXX'}}]` → `keyDrafts[key] === SECRET_MASK`; для `{configured:false}` и `null` → поле пустое.
  - `stickyDirtyCount === 0` при только «масковых» черновиках; `saveModalEdits` не делает POST.
  - `saveKeyItem` с `value === SECRET_MASK` → без POST.
  - INV-3: для каждого не-секретного `configItem` с непустым `value` рендерится непустое значение; пусто только при `null` (параметризованный обход всех ключей).
  - Grid: `INDEX` содержит `prov-grid` в ветке `llm_providers`; `max-w-3xl` не стоит на `.prov-block`.
  - Виджеты `keyvalue`/`list`/`select`/`bool` — проверка `blockDrafts`-путей (регресс «пустых полей» во всех модулях).

### 7.4 Python-тесты webapp
- Обновить осознанно (упадут от контракта — это ожидаемо и должно быть явно отражено в tasks):
  - `tests/test_webapp_api.py:1208` (`backdrop-filter: blur(20px) saturate(140%)` → новый токен),
  - `tests/test_webapp_avatars_ui.py:440-441` (`animation: grad-drift 18s`, `--grad-speed:14s`),
  - `tests/test_webapp_round109_ui.py:198-199` (`--grad-speed:14s`, `grad-drift 18s`),
  - `tests/test_webapp_back_button.py:246` (если меняется форма `grad-spin`),
  - `tests/test_webapp_round1020_ui.py:152-172` (`test_glass_tokens`/`test_grid` — заменить на §7.2).
- Сохранить зелёными: снимок навигации (`test_webapp_round1020_ui.py:36-64`), `test_webapp_avatars_ui.py:428` (`main-header … card-solid`), `tests/js/vue_mount_test.js`, `tests/js/routing_test.js`.

### 7.5 Визуальная приёмка (человек/скриншоты — гейт T-1904)
- Вьюпорты: десктоп 1440×900 (fullscreen ⛶), Telegram Android WebView, Nekogram (iOS).
- Экраны: «Модули», «ИИ» (LLM Провайдеры), «Диагностика», модалка модуля, конфиг-вкладка (Промпты), досье.
- Чеклист: (1) сквозь карточки/модалки виден градиент; (2) «Модули» и «ИИ» ≥2 колонок на десктопе; (3) Betterstack-поля не пусты (маска/значение); (4) фон переливается 5–8s с оранжевым; (5) sticky-панель не перекрывает поля и не «двойнит» отступы.

### 7.6 Прод-верификация (различить «код неверен» и «не задеплоено»)
- `curl -s https://<host>/static/app.css | grep -c 'blur(16px)'` и `grep -c 'rgba(20, 25, 30, 0.5)'`.
- Ответ `/static/app.css` — `Cache-Control: no-cache, no-store, must-revalidate` (`web/app.py:240-245`).

---

## 8. Как @Reviewer ОБЯЗАН проверять (обязательный протокол, чтобы не повторить пропуск)

**Запрещено** закрывать UI-задачу по факту «строка есть в файле». Обязательны все шаги:

1. **Проверить серверный артефакт** (§7.6) — если `blur(16px)`/`rgba(20,25,30,0.5)` не отдаются прод-хостом, фикс не задеплоен → BLOCKER.
2. **Каскад, а не наличие.** Для каждого элемента разметки с ролью modal/card/panel выписать **все** его классы, найти **выигрывающее** правило и подтвердить effective `background-color` (alpha ≤ .5–.85) + `backdrop-filter: blur(16px)`. Проверка: в `index.html` нет `modal-card … card-solid`, нет Tailwind `bg-*` на этих элементах.
3. **Отсутствие перекрытия.** Явно прочитать `.card`, `.card-solid`, `@supports not`, `.modal-card` в порядке исходников и доказать, что ни одно более позднее правило не задаёт solid-фон для glass-селекторов.
4. **Маска секретов.** Проверить `SECRET_MASK`, `_seedSecretMasks` и все **3** точки `v-model="keyDrafts[...]"`; выполнить JS-кейс «configured → непустая маска; null → пусто; маска не отправляется на сервер». Отдельно — «Диагностика» (`keys_betterstack`, оба ключа) и **сквозной обход всех модулей** (§7.3 INV-3).
5. **Grid.** Проверить, что контейнер ветки `llm_providers` имеет `prov-grid` с `repeat(auto-fit, minmax(320px,1fr))`, `.prov-block` без `max-w-3xl`, и что на десктопе фактически ≥2 колонки (скриншот, а не CSS-строка).
6. **Sticky.** Проверить, что в модалках панель `static` внутри flex-колонки, `.modal-body` — единственный скроллер, нет inline `max-height:80dvh`; на вкладках — `scroll-padding-bottom`/`padding-bottom`; скриншот с прокруткой до конца.
7. **Градиент.** Проверить наличие оранжевого токена, `--grad-speed` ∈ [5,8] s, движение видно, `prefers-reduced-motion` отключает анимацию.
8. **Регресс.** `node tests/js/*.js`, `pytest tests/test_webapp*`; изменения чужих тестов — только перечисленные в §7.4, каждое с обоснованием.
9. **R18.** Скан диффа/`plans/**` на секреты; в отчёте — только `[REDACTED]`.

---

## 9. Не-скоуп (явно)
- Бэкенд-логика, БД, миграции, `services/**`, `web/api/**` — **не трогаем**.
- `services/param_catalog.py`: **аддитивных правок НЕ требуется**. Оба Betterstack-ключа остаются `secret=True`; «Пользователь Betterstack SQL» маскируется как credential-пара (ADR D5). Если владелец позже захочет видеть логин открыто — это отдельная задача с явным решением по R17.
- Эндпоинт/формат `/api/config` (всегда `{configured,last4}`) — не меняем.
- Меню/навигация/состав вкладок (`25 вкладок + 6 nav + 12 модулей`) — инвариант (сохранить снимок навигации).
- `APP_VERSION`, CSP, Caddy, self-host — не трогаем.
- Досье/тикер/labels/Advanced-аккордеон (соседние T-1896/1897/1901/1902) — только регресс-проверка, не переписываем.

---

## 10. DoD (Definition of Done)
1. Все 5 дефектов закрыты по контрактам G1–G5; root-cause из §0–§5 устранён, а не замаскирован.
2. **Red→green:** новые ассерты (`tests/js/round1020_ui_rework_test.js`, `tests/test_webapp_ui_rework_round1020.py`) **падают на текущем коде** (red-прогон зафиксирован в отчёте) и зелёные после фикса.
3. `tests/test_webapp_ui_rework_round1020.py` и `tests/js/round1020_ui_rework_test.js` — зелёные; обновлённые `tests/js/round1020_ui_test.js` и перечисленные в §7.4 тесты — зелёные; полный `pytest tests/` — 0 регрессий; `node --check web/app.js`, `JS-UNIT-OK`, `VUE-MOUNT-OK`; `git diff --check` clean.
4. Снимок навигации не изменён (25 вкладок + navbar 6 + 12 карточек модулей).
5. Прод-верификация §7.6: прод-хост отдаёт **новый** CSS (`blur(16px)`, `rgba(20, 25, 30, 0.5)`), без печати секретов.
6. Визуальная приёмка §7.5 (скриншоты десктоп/Android/Nekogram) — приложена к отчёту.
7. R18: `plans/**` и дифф чистые; ни одного секрета (только `[REDACTED]`); значения Betterstack-полей не цитируются.
8. Reviewer-протокол §8 выполнен полностью (каждый пункт — с доказательством); независимый re-audit @Scanner воспроизвёл зонды; @DevOps подтвердил доставку CSS.

---

## 11. Риски
| # | Риск | Митигация |
|---|---|---|
| R-UI-1 | `backdrop-filter` не поддерживается в целевом WebView → fallback `.85` снова «solid» | `@supports not` + `--glass-bg-strong`; визуальная приёмка на Android/Nekogram; wash-градиент под панелью |
| R-UI-2 | Вложенные `.card` складывают alpha до solid | G1.5 (снять blur/снизить alpha у вложенных) + скриншот модалки модуля |
| R-UI-3 | Маска-сентинел утечёт в `POST /api/config` и перезапишет реальный секрет | G3.3/G3.4 + JS-тесты «маска не отправляется»; guard в `saveKeyItem` и `dirtyKeyItems` |
| R-UI-4 | `:has()` не поддержан → панель перекрывает низ контента | `@supports not (selector(:has(*)))` фолбэк с безусловным `padding-bottom` |
| R-UI-5 | Анимация градиента жрёт GPU на мобиле | `--grad-speed` = 6s (не быстрее 5s), один fixed-слой, `pointer-events:none`, `prefers-reduced-motion` |
| R-UI-6 | Массовое изменение CSS задело соседние фичи (досье/тикер/аккордеон) | Полный `pytest tests/` + точечный просмотр затронутых селекторов; правки только в рамках G1–G5 |
| R-UI-7 | «Пользователь Betterstack SQL» остаётся замаскирован → владелец не видит логин | ADR D5 фиксирует решение и альтернативу; при явном запросе — отдельная задача |
| R-UI-8 | Обновление «чужих» тестов маскирует регресс (прецедент R24) | В tasks перечислить **только** 4 файла из §7.4, каждое изменение — с diff-обоснованием в отчёте |
| R-UI-9 | Ложная приёмка «строка есть в файле» (корень провала 10.20, R27) | Red→green (§10.2) + CSSOM-зонды (§8.2) + served-CSS (§7.6) + запрет grep-доказательств |

---

## 12. Артефакты этой фазы (Шаг 2)

| Артефакт | Назначение |
|---|---|
| `plans/features/round1020-ui-rework/spec.md` | полный техдизайн + root-cause + тест-стратегия + Reviewer-протокол |
| `plans/features/round1020-ui-rework/ui-contract.md` | **T-1933:** класс-карта + каскадный контракт + sentinel + токены (рабочий контракт @Builder) |
| `plans/features/round1020-ui-rework/adr/ui-rework-1020.md` | ADR-1020-9: решения D1–D7 (glass/grid/маска/градиент/sticky/флаги) |
| `plans/features/round1020-ui-rework/tasks.md` | (PM) T-1933…T-1942 — задачи/DoD/риски R27–R36 |
| `plans/reports/round1020_ui_rework_reviewer.md` | (Reviewer, T-1940) сырые CSSOM-зонды + served-CSS |
| `plans/reports/round1020_ui_rework_scanner_audit.md` | (Scanner, T-1941) независимый re-audit |
