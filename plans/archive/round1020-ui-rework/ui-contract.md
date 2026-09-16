# ui-contract.md — UI-контракт доработки (T-1933, @Architect)

> Короткий «единственный источник истины» для @Builder. Полная логика/root-cause — в `spec.md`, решения — в `adr/ui-rework-1020.md`.
> **R18:** только маска `••••••••••••` / фейковый `last4`; реальные значения не приводить.

## 1. Класс-карта (кто несёт стекло, кто — нет)

| DOM-узел (селектор) | Стекло? | Фон | Blur | Примечание |
|---|---|---|---|---|
| `.modal-card` (`index.html:746,1259,1311,1452,2658`) | **ДА** | `var(--glass-bg)` = `rgba(20,25,30,.5)` | `blur(16px)` | **убрать класс `card-solid`** из разметки |
| `.card` (94 узла) | **ДА** | `var(--glass-bg)` | `blur(16px)` | уйти от `--surface-glass` (.72) |
| `.hub-card` | **ДА** | `var(--glass-bg)` | `blur(16px)` | |
| `.module-card` | **ДА** | `var(--glass-bg)` | `blur(16px)` | |
| `.prov-block` (`index.html:220,364`) | **ДА** | `var(--glass-bg)` | `blur(16px)` | + снять `max-w-3xl` |
| `details.advanced` | **ДА** | `var(--glass-bg)` | `blur(16px)` | состав групп не менять |
| `.scope-panel` (`index.html:67`) | **ДА** | `var(--glass-bg)` | `blur(16px)` | |
| `.glass-panel` (Сводка, `index.html:975`) | **ДА** | `var(--glass-bg)` | `blur(16px)` | не удалять класс |
| `.oversight-panel` | ДА (селектор) | `var(--glass-bg)` | `blur(16px)` | **в разметке отсутствует** — оставлен для совместимости |
| `.sticky-save` | **ДА** | `var(--glass-bg-strong)` = `rgba(20,25,30,.85)` | `blur(16px)` | плотнее ради читаемости |
| `.module-list`, `.hub-grid`, `.prov-grid` | **НЕТ** | `transparent` | `none` | только раскладка (`border:0`) |
| `.card-solid` | **НЕТ** (только `.scope-panel`-фолбэк/шапка) | `rgba(22,22,22,.88)` | — | в модалках запрещён |
| `header.header-sticky` | **НЕТ** | `rgba(22,22,22,.96)` | — | намеренно плотная шапка (`app.css:604-611`) |

## 2. Каскадный контракт

- **Порядок подключения:** `vendor/tailwind.css` (`index.html:19`) → `app.css` (`index.html:22`). Tailwind — предсобранный, без `!important`/`@layer`; при равной специфичности выигрывает `app.css`.
- **Запрещённые комбинации в разметке:** `modal-card card card-solid` — **0 вхождений**; Tailwind `bg-*` на glass-узлах — **0 вхождений**.
- **Выбор из двух (T-1933):** `card-solid` **удаляется из разметки модалок** (не override). Одно решение, не оба.
- **Кто выигрывает у `.card-solid`/`--surface-glass`:** сам glass-set-селектор, но только если он стоит в исходнике **позже** и не перебит более специфичным правилом. `@supports not` — единственный разрешённый override (плотный фон).
- **Проверка каскада:** для реальной цепочки `class="modal-card card …"` вычислить победителя (специфичность + порядок) → итог `background-color: rgba(20,25,30,.5)`, `backdrop-filter: blur(16px)`, `-webkit-backdrop-filter: blur(16px)`.

## 3. Токены (точные значения)

```css
--glass-bg: rgba(20, 25, 30, 0.5);
--glass-bg-strong: rgba(20, 25, 30, 0.85);
--glass-blur: blur(16px);
--glass-border-color: rgba(255, 255, 255, 0.12);
--glass-border: 1px solid var(--glass-border-color);
--grad-a:#664EA0; --grad-b:#14CBB6; --grad-c:#8D6BDC; --grad-d:#FF8A3D; /* +оранжевый */
--grad-speed: 6s;                 /* 5–8 s; и wash, и акценты */
--sticky-save-h: 4.5rem;          /* запас снизу скролл-контейнеров */
```

## 4. Grid-контракт

```css
.prov-grid, .module-list, .hub-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 1rem;
  width: 100%;
  border: 0; background: transparent; backdrop-filter: none;
}
@media (max-width: 479px) { .prov-grid, .module-list, .hub-grid { grid-template-columns: 1fr; } }
```
- «ИИ» = ветка `llm_providers` (`index.html:214`) → получить класс `prov-grid`. Дополнительного контейнера в CSS у неё сейчас нет — **это и есть пропущенная часть дефекта 2**.
- `.prov-block` — без `max-w-3xl mx-auto`.
- DoD: при ширине ≥1000px `gridTemplateColumns` даёт ≥2 трека.

## 5. Sentinel маски секретов

- **`SECRET_MASK = '••••••••••••'`** (ровно 12 символов) + `isSecretMask(v)` в `web/app.js`.
- **Инвариант INV-3:** значение есть → инпут не пуст (не-секрет = значение; секрет `{configured:true}` = маска). Пусто — только при `null`/`{configured:false}`.
- **Пути:**
  1. `blockFieldValue` (`app.js:2813-2820`) → маска для `{configured:true}` (provider-блоки).
  2. `_seedSecretMasks()` → `keyDrafts[key] = SECRET_MASK` для `(category==='keys' || secret) && isKeyConfigured(item)`; вызов из `loadConfig` (`:3446-3460`), `_snapshotConfig`, `cancelModalEdits` (`:2652`), после `saveKeyItem` (`:3842`).
- **Маска не сохраняется:** guard `isSecretMask` в `saveKeyItem` (`:3823-3852`) и `saveBlock` (`:2927-2950`); исключение из `dirtyKeyItems` (`:1344-1352`) и `blockDrafts`.
- **Фокус:** `@focus` → `select()`, чтобы первое нажатие заменяло маску.
- **Эталон кейса:** `CHECKUP_BETTERSTACK_SQL_USER` / `CHECKUP_BETTERSTACK_SQL_PASSWORD` (`services/param_catalog.py:503-506`, `secret=True`, группа `keys_betterstack`, вкладка «Диагностика») — сейчас пусты, обязаны показывать маску. Каталог **не менять**.

## 6. Sticky-контракт

```css
.sticky-save { position: sticky; bottom: 0; z-index: 5;
  padding: .6rem .75rem;
  padding-bottom: calc(.6rem + env(safe-area-inset-bottom, 0px));
  margin: 0; border-top: var(--glass-border);
  background-color: var(--glass-bg-strong);
  -webkit-backdrop-filter: var(--glass-blur); backdrop-filter: var(--glass-blur); }
.modal-card { display:flex; flex-direction:column;
  max-height:min(90dvh,46rem); overflow:hidden; }
.modal-body { flex:1 1 auto; min-height:0; overflow-y:auto;
  scroll-padding-bottom: var(--sticky-save-h); }
.scroll-area:has(> .sticky-save) {
  padding-bottom: calc(1rem + var(--sticky-save-h));
  scroll-padding-bottom: var(--sticky-save-h); }
@supports not (selector(:has(*))) { .scroll-area { padding-bottom: calc(1rem + var(--sticky-save-h)); } }
```
- `<sticky-save>` — **внутрь** скролл-контейнера: модалка (`index.html:967` → в конец `.modal-body` перед `:963`), досье (`:2694` → перед `:2693`).
- Убрать inline `max-height:80dvh/70dvh` (`index.html:758,1269,1321,1462,2669`).
- Панель обязана присутствовать в **всех** ветках сохранения (config/modules/access) — регресс S10.20-1 не возвращать.

## 7. Что НЕ делать

- Не менять меню/навигацию/состав вкладок (25 вкладок, 6 nav, 12 карточек).
- Не менять `services/param_catalog.py`, `web/api/**`, формат `/api/config`.
- Не вводить серверный фича-флаг и поэтапную раскатку 10/50/100 % — UI-фикс безусловный.
- Не бампать `APP_VERSION` «на всякий случай» (CSS отдаётся `no-store`).
- Не принимать «доказательство» вида «строка есть в файле».
