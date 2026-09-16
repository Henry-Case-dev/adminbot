# Эпик round1020-UPD3 — доработка фронтенда мини-аппа (UI-rework)

> **Статус: ✅ COMPLETED + DEPLOYED + ЗААРХИВИРОВАН** (17.09.2026 · commit `ec93c3d`). Эпик **10.20** возвращён владельцем
> на доработку после **визуальной инспекции мини-аппа (скриншоты)** (UPD3): **бэкенд — ок**, **БЛОК 3 (UX/UI) провален**.
> **5 дефектов исправлены**; @Reviewer — **Approved** (итерация 2, реальный Chromium), @Scanner — **0 Critical / 0 High**
> (M-1/L-1/L-2 закрыты); полный `pytest` — **6574 passed / 0 failed**; задеплоено (@DevOps), прод-CSS подтверждён, `PRAGMA user_version=12`.
> **⏸ Осталось (human-pending):** живая приёмка владельцем — WebView (Telegram Android / Nekogram) + скриншот-приёмка §7.5.
> **Архив:** `plans/archive/round1020-ui-rework/`.
> **История провала:** отчёт Оркестратора о готовности UI признан **галлюцинацией**; @Reviewer получил **выговор** за пропуск.
> **Владелец: никаких отчётов о готовности до реального фикса** — только проверяемые DOM/CSS-доказательства.
> **Тип:** frontend (TMA: `web/index.html`, `web/static/app.css`, `web/app.js`) + аддитивные фиксы `web/api/*`.
> **Приоритет:** **P0** (все 5 дефектов — блокеры повторной приёмки). **Меню/навигацию НЕ менять.**
> **Нумерация:** продолжает T-1931 (10.20) → **T-1933 … T-1942**.
> **⚠️ T-1932 зарезервирована** follow-up'ом «fallback точки 7» (`vector_search` → `list[str]`, R26 ADR-1020-1) —
> **в этот эпик НЕ входит**, не занимать номер.
> **ТЗ:** `plans/current_task.md` — **UPD3, строки 365–411** (5 дефектов, стр. 375–401; R17-вопрос — стр. 407–411).
> **Предыдущий эпик (архив):** `plans/archive/round1020-lore-compiler-rag-refactor/` (T-1866…T-1931, фазы A–H).
> **Baseline:** HEAD после `995cf83`+`741b77c`; pytest **6546 passed / 0 failed**; каталог **439/409/414/92/90/20**; SQLite **v12**;
> APP_VERSION **2.57.0** (кэш-бастинг CSS/JS через `?v=`).
> **R18 (Secret Scrubbing):** перед коммитом/деплоем/архивацией — скан `plans/**` на креды; значение SSH-пароля из
> `current_task.md` **не цитировать** (R17/О6). В тестах — только фейковые `last4`.

## 1. Цель

Довести БЛОК 3 до фактического соответствия ТЗ (UPD3) и **доказать это рендером, а не grep'ом по исходникам**.
Пять дефектов из визуальной инспекции владельца:

1. **Нет Liquid Glass** — фоны модалок/карточек сплошные тёмные.
2. **CSS Grid проигнорирован** — «Модули» и «ИИ» на десктопе в одну колонку.
3. **КРИТИЧНО: пустые поля ввода** (two-way binding) — `Пароль Betterstack SQL` / `Пользователь Betterstack SQL`
   пустые при наличии данных в БД; секрет обязан показывать `••••••••••••`.
4. **Фоновый градиент** — слишком медленный/скучный; нужен оранжевый в палитре и заметные переливы (5–8s).
5. **Кривая sticky-панель** «Отмена/Сохранить» — сломала padding/margin модалок, перекрывает контент.

Плюс процессная цель: **исключить ложноположительное ревью** (в 10.20 UI «прошёл» по формальным признакам).

## 2. Дефекты UPD3 (дословная суть + факты из кода)

| # | Дефект (из UPD3) | Требование владельца | Факты в коде (что искать/править) |
|---|---|---|---|
| **1** | **Liquid Glass отсутствует, верстка сломана.** «Никакого эффекта стекла нет. Фоны модалок и карточек — сплошной тёмный цвет». | `.modal`, `.card`, панели → `background-color: rgba(20,25,30,0.5)` + `backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);` | `web/static/app.css`: `:root --glass-bg: rgba(30,35,40,0.6)`, `--glass-blur: blur(12px)` (стр. 33–36); `.card` использует `--surface-glass: rgba(22,22,22,.72)` (стр. 8, 121–128); **`.card-solid` = `rgba(22,22,22,.88)`** (стр. 129–131) — навешен на **каждую** модалку в разметке (`index.html:746, 1259, 1311, 1452, 2658` — `modal-card card card-solid`); блок T-1898 (стр. 785–797) **вешает фон/бордер на grid-контейнеры** `.module-list`/`.hub-grid` (панель-слэб вместо стеклянных карточек). `--surface-glass` при 0.72 поверх `#0E0E0E` визуально = сплошной. |
| **2** | **CSS Grid проигнорирован.** «В разделах Модули и ИИ на десктопе карточки всё ещё идут в одну колонку». | Контейнер карточек → `display:grid; grid-template-columns: repeat(auto-fit, minmax(320px,1fr)); gap:1rem;`. «Заставьте карточки заполнять пространство!» | `app.css`: `.module-list` (стр. 239–246) и `.hub-grid` (стр. 264–270) сейчас `minmax(300px,1fr)` + `gap:.75rem`, `.module-list` `max-width:1100px`; родитель — `<main class="... grid gap-4 grid-cols-1">` (`index.html:141`), контейнеры `index.html:149`, `713`. Проверить каскад против Tailwind-утилит (`web/static/vendor/tailwind.css` грузится **до** `app.css`). |
| **3** | **КРИТИЧНО: пустые поля ввода.** «`Пароль Betterstack SQL` и `Пользователь Betterstack SQL` АБСОЛЮТНО ПУСТЫЕ. Данные из базы не прокидываются». | Если секрет есть в БД — инпут **ДОЛЖЕН** показывать `••••••••••••`. Пусто **только** при реальном `null`. «Проверьте во ВСЕХ модулях». | `web/app.js::blockFieldValue` (стр. 2813–2820): для `it.value = {configured,last4}` (это ровно то, что отдаёт `web/api/routes.py::_mask_secret`, стр. 231–240) возвращает `''` → инпут пуст (маска уходит только в **placeholder**, стр. 2848–2853). Второй путь — generic-keys в модалке модуля: `index.html:798–805` (`v-model="keyDrafts[item.key]"`) — поле **намеренно** пустое «Новый ключ», маски нет. Поля Betterstack: `services/param_catalog.py:503–506` (`CHECKUP_BETTERSTACK_SQL_USER`, `CHECKUP_BETTERSTACK_SQL_PASSWORD`, **оба `secret=True`**), группа `keys_betterstack` (стр. 183) → модалка `mod_checkup` («Диагностика», `app.js:90, 361`). **Ловушка:** `saveBlock` (стр. 2927–2950) и `saveKeyItem` (стр. 3823–3842) пишут значение как есть — маска не должна сохраниться как реальный секрет. |
| **4** | **Фоновый градиент.** «Анимация слишком медленная и незаметная, цвета скучные». | (1) `animation-duration: 5s`…`8s`; (2) добавить **оранжевый** к сиреневому и бирюзовому/циан; (3) отрегулировать углы — переливы **явно видны**. | `app.css`: `--grad-speed: 14s` (стр. 19); палитра `--grad-a:#664EA0` (сиреневый), `--grad-b:#14CBB6` (бирюза/циан), `--grad-c:#8D6BDC` (стр. 18) — оранжевого нет; `@keyframes grad-spin` `135deg→495deg` (стр. 74), `body::before` `animation: grad-drift 18s`, `opacity:.16` (стр. 97–107); `.grad-band/.btn-accent/.tab-btn.active` `conic-gradient` (стр. 76–80). Отдельно — `@media (prefers-reduced-motion)` / `(prefers-contrast: more)` (стр. 108–118) обязаны остаться. |
| **5** | **Кривая sticky-панель.** «Выглядит неаккуратно, сломала отступы (padding/margin) в модалках. Переверстайте: гармонично прилипает к низу и не перекрывает контент». | Панель аккуратно прилипает к низу, **не перекрывает** контент, не ломает отступы модалок. | `app.css`: `.sticky-save` (стр. 809–822) — `position:sticky; bottom:0; padding:.5rem .25rem .25rem; margin-top:.75rem; border-top` (панель «дорисовывает» свои отступы поверх родительских); рендер — `index.html:704` (`<sticky-save class="col-span-full">` в конце config-ветки), модалка модуля — `index.html:758` (`.modal-body` `max-height:80dvh; overflow-y:auto`), футер модалки — `index.html:964`. Нижний `safe-area-inset-bottom` не учтён. |

## 3. Требования (сводно)

**Дефект 1 (Liquid Glass):**
- [x] `.modal`/`.modal-card`, `.card`, панели (`.oversight-panel`, `.hub-card`, `.module-card`, `.prov-block`, `details.advanced`, `.scope-panel`) → фон `rgba(20,25,30,0.5)` **вместе** с `backdrop-filter: blur(16px)` и `-webkit-backdrop-filter: blur(16px)`.
- [x] Никакой класс/правило (`card-solid`, `--surface-glass`) не должен «съедать» стекло в модалках и карточках.
- [x] Фон/бордер **снимаются** с grid-контейнеров (`.module-list`, `.hub-grid`) — стекло живёт на карточках, а не на их обёртке.
- [x] Фолбэки сохраняются: `@supports not (backdrop-filter)` → плотный фон; `prefers-reduced-motion`/`prefers-contrast` — как есть.

**Дефект 2 (CSS Grid):**
- [x] `.module-list` и `.hub-grid` → строго `display:grid; grid-template-columns: repeat(auto-fit, minmax(320px,1fr)); gap:1rem;` (заполняют ширину; центровка сохраняется).
- [x] Убедиться, что Tailwind-утилиты родителя (`grid-cols-1`) и порядок подключения CSS не ломают треки.

**Дефект 3 (binding / маска секрета — CRITICAL):**
- [x] Единый sentinel `SECRET_MASK = '••••••••••••'`; `configured:true` → инпут показывает маску; `null`/`configured:false` → пусто.
- [x] Покрыть **все** пути: provider-блоки (`blockFieldValue`), модалку модуля (basic + advanced), generic config (keys-шаблоны `index.html:544`, `632`).
- [x] Маска **никогда** не отправляется на сервер (`saveBlock`/`saveKeyItem`) и не становится `baseline`/`draft`.
- [x] Поля Betterstack SQL (user + password) — проверены отдельно (эталон кейса владельца).

**Дефект 4 (градиент):**
- [x] `animation-duration` градиента ∈ **5–8s**; в палитре — **оранжевый** рядом с сиреневым и циан/бирюзовым; углы настроены так, чтобы переливы были **явно видны** (не «еле заметная подсветка»).
- [x] Градиент остаётся фоном (не под текстом напрямую) и не ухудшает контраст WCAG AA.

**Дефект 5 (sticky-save):**
- [x] Панель прилипает к низу скролл-контейнера, не перекрывает последний элемент/контент, не ломает padding/margin модалки, учитывает `safe-area-inset-bottom`.
- [x] Сохраняется функциональность: `<sticky-save>` — единственный способ сохранения на config-вкладках (регресс S10.20-1 не вернуть).

**Процессное (обязательное):**
- [x] Тесты — **DOM/CSS-ассерты** (каскад/вычисленные значения/поведение JS), а не «строка есть в файле».
- [x] @Reviewer проверяет **фактический рендер**: computed-стили, классы в DOM, значения инпутов, отсутствие перекрытия.

**Feature Flags / Progressive Delivery:** UI-доработка — **безусловная** (CSS/JS), флаг не вводится, каталог-Δ = **0**.
Поэтапная раскатка (10/50/100%) **не применяется** — иначе дефект остаётся у части пользователей. Откат — `git revert`.
Обязательный «кэш-гейт» доставки: `?v=__APP_VERSION__` (при необходимости бамп `APP_VERSION`, `config/settings.py:1274`) —
иначе клиент может крутить старый CSS.

## 4. Definition of Done (эпик)

- [x] **Дефект 1:** каскад-резолвер (T-1939) показывает итоговый фон модалки/карточки = `rgba(20,25,30,0.5)` и `backdrop-filter`/`-webkit-backdrop-filter` = `blur(16px)`; ни один `.modal-card` не нейтрализован `.card-solid`/`--surface-glass`; grid-контейнеры без фона.
- [x] **Дефект 2:** `.module-list`/`.hub-grid` содержат точную тройку grid-правил; при ширине ≥ 1000px — **≥ 2 трека** (замер `gridTemplateColumns`).
- [x] **Дефект 3:** для `{configured:true}` во **всех** модулях инпут показывает `••••••••••••`; пусто только при `null`; маска **не** уходит на сервер (тест); поля `Пароль/Пользователь Betterstack SQL` подтверждены.
- [x] **Дефект 4:** `animation-duration` ∈ [5s, 8s]; оранжевый присутствует в палитре градиента; углы/видимость подтверждены; `prefers-reduced-motion`/`prefers-contrast` работают.
- [x] **Дефект 5:** панель `position:sticky; bottom:0`, контент не перекрыт (offset-замер + визуально), отступы модалки не сломаны, safe-area учтён.
- [x] **Тесты red→green:** новые тесты (T-1939) **падают до фикса** и зелёные после (red-прогон зафиксирован в отчёте) — исключает ложную приёмку.
- [x] Полный `pytest` — **0 failed**; JS-гейты (`node --check web/app.js`, `JS-UNIT-OK`, `VUE-MOUNT-OK`) чистые; `git diff --check` clean.
- [x] **Меню/навигация не изменены** (снимок навигации 25 вкладок + navbar + 12 карточек модулей зелёный).
- [x] **R18-скан** `plans/**` чист (секретов нет; значения не цитируются).
- [x] **Фактический рендер подтверждён @Reviewer** (верификационный отчёт с сырыми выводами CSSOM-зондов + served-CSS) и **независимо @Scanner**; доказательство вида «класс где-то есть» **не принимается**.
- [x] **Деплой** @DevOps выполнен; на прод-URL подтверждено, что отдаётся новый CSS (без секретов в выводе), бот `systemctl active`.

## 5. Чек-лист задач

### T-1933 (@Architect, гейт) — UI-контракт доработки (класс-карта + каскад + sentinel маски)

- [x] Зафиксировать **класс-карту**: какой DOM-узел обязан нести glass-фон (`modal-card`, `card`, `hub-card`, `module-card`, `oversight-panel`, `prov-block`, `details.advanced`, `scope-panel`), а какой — **нет** (grid-контейнеры `.module-list`/`.hub-grid`).
- [x] Зафиксировать **каскадный контракт**: порядок `vendor/tailwind.css` → `app.css`; правило, кто выигрывает у `.card-solid`/`--surface-glass`; решение «убрать `card-solid` из разметки **или** явный override `.modal-card.card-solid`» (одно, не оба).
- [x] Зафиксировать **sentinel маски** `SECRET_MASK = '••••••••••••'` и инвариант «маска никогда не сохраняется и не становится baseline/draft».
- [x] Токены/значения: `--glass-bg: rgba(20,25,30,.5)`, `--glass-blur: blur(16px)`; grid-тройка; градиент (5–8s + оранжевый токен + углы); sticky-save (отступы + safe-area).
- [x] Артефакт: `plans/features/round1020-ui-rework/ui-contract.md` (+ при необходимости правки `spec.md`). **Зависит:** ничего. **Гейт для T-1934…T-1938.**

### T-1934 (@Builder) — Дефект 1: Liquid Glass + сломанная верстка

- [x] `web/static/app.css`: `:root` — `--glass-bg: rgba(20, 25, 30, 0.5)`, `--glass-blur: blur(16px)`; `-webkit-backdrop-filter` рядом с `backdrop-filter` **в каждом** glass-правиле.
- [x] Перевести `.card` (стр. 121–128) с `--surface-glass` (0.72) на `--glass-bg`; пересмотреть алиасы `--card-bg`/`--surface-glass` (чтобы не переопределяли стекло).
- [x] Убрать нейтрализацию: `.card-solid` `rgba(22,22,22,.88)` (стр. 129–131) — снять класс `card-solid` с модалок (`index.html:746, 1259, 1311, 1452, 2658`) **или** задать явный приоритет `.modal-card.card-solid` (по контракту T-1933).
- [x] Снять фон/бордер с **grid-контейнеров** `.module-list`/`.hub-grid` (стр. 789–790); оставить стекло на `.module-card`/`.hub-card`.
- [x] Применить glass к `.oversight-panel`, `.prov-block`, `details.advanced` (стр. 881–888), `.scope-panel` (стр. 294–299).
- [x] Сохранить `@supports not ((backdrop-filter…)) → rgba(22,22,22,.92)` (стр. 804–806) и `prefers-reduced-motion`/`prefers-contrast`.
- [x] **DoD:** T-1939 подтверждает итоговый фон модалки/карточки = `rgba(20,25,30,0.5)` + `blur(16px)`; grid-контейнеры без фона.

### T-1935 (@Builder) — Дефект 2: CSS Grid (Модули + ИИ)

- [x] `app.css`: `.module-list` (стр. 239–246) → `display:grid; grid-template-columns: repeat(auto-fit, minmax(320px,1fr)); gap:1rem;` (центровку `justify-self:center`/`margin-inline:auto` сохранить; `max-width` — только если не мешает заполнению, финальное решение в T-1933).
- [x] `app.css`: `.hub-grid` (стр. 264–270) → та же тройка.
- [x] Проверить разметку: `index.html:141` (`<main class="... grid grid-cols-1">`), `index.html:149` (`.hub-grid`), `index.html:713` (`.module-list`) — контейнеры являются grid-контейнерами, Tailwind-утилиты не перебивают треки.
- [x] **DoD:** при ширине ≥ 1000px `gridTemplateColumns` даёт **≥ 2 трека**; на мобильном — 1; карточки заполняют ширину, «пустого места слева» нет.

### T-1936 (@Builder) — Дефект 3 (CRITICAL): two-way binding + маска секретов

- [x] `web/app.js`: ввести `SECRET_MASK = '••••••••••••'` + `isSecretMask(v)`; `blockFieldValue` (стр. 2813–2820): для объекта `{configured:true, last4}` → `SECRET_MASK`; `configured:false`/`null` → `''`; строка → как есть.
- [x] `web/app.js::saveBlock` (стр. 2927–2950): пропускать значение, равное маске («не изменено»); не создавать `blockDrafts` при программном предзаполнении маски.
- [x] `web/app.js::saveKeyItem` (стр. 3823–3842): `if (value && !isSecretMask(value))` — иначе no-op (+ toast «значение уже сохранено»), маска **не** уходит в POST.
- [x] `web/index.html`: keys-путь в модалке модуля (стр. 798–805), generic config (стр. 544–556) и advanced-путь (стр. 632+) — при `isKeyConfigured(item)` предзаполнять инпут маской (с сохранением placeholder «Новый ключ (заменить)…»); очистка маски по фокусу/вводу.
- [x] Отдельно проверить **эталон владельца**: `Пароль Betterstack SQL` + `Пользователь Betterstack SQL` (модалка `mod_checkup`, группа `keys_betterstack`; `services/param_catalog.py:503–506` — **только чтение**).
- [x] Аудит **всех** модулей: keys-группы (`keys_*`), provider-блоки, advanced-секции, BYOK-путь — пусто только при реальном `null`.
- [x] **R18/R17:** в коде/тестах — только маска/фейковый `last4`, никаких реальных значений и никаких кредов в отчётах.
- [x] **DoD:** JS-тест «`blockFieldValue({configured:true,last4:'1234'}) === SECRET_MASK` (не `''`)», «`saveKeyItem`/`saveBlock` с маской → 0 запросов», «пусто при `configured:false`», «ввод реального значения → сохранение уходит».

### T-1936-fix (@Builder) — доработка после ревью T-1940 (Critical-1/Critical-2/High-1)

> Итерация фиксов round1020 UPD3 по `plans/reports/round1020_ui_rework_reviewer.md` (вердикт NEEDS FIXES).
> Правки только во фронтенде (`web/app.js`, `web/index.html`, `web/static/app.css`) + тесты. Бэкенд/`web/api/**`/каталог/БД не трогались.

- [x] **Critical-1 (R31/INV-3):** `web/app.js` — введён `hasSecretMask(v) = String(v ?? '').indexOf(SECRET_MASK) !== -1`; на него переведены **все** guard'ы (`saveKeyItem`, `saveBlock`, `testBlock`, `testField`, `dirtyKeyItems`). Композит `маска+ввод` (`••••••••••••X`) → no-op, 0 POST; в `/api/llm/test` маска/композит не уходят (шлётся `''`, бэкенд резолвит сохранённый ключ).
- [x] **Critical-2 (G3.6):** `web/index.html` — на 3 provider-инпута `:value="blockFieldValue(f)"` (стр. ~243/280/379) добавлены `@focus="$event.target.select()"` + `@mouseup.prevent` (клик+ввод заменяет маску, а не дописывает к ней).
- [x] **High-1:** `tests/js/round1020_ui_rework_test.js` — регресс-кейсы: композит `mask+'X'` → 0 POST для `saveKeyItem` **и** `saveBlock`; `testBlock`/`testField` не шлют композит; точная маска → 0 POST (не регрессировать); `dirtyKeyItems`: композит ≠ изменение; 3× `@focus select`+`@mouseup.prevent` у provider-инпутов. **Red→green** зафиксирован (деградация guard до точного равенства → AssertionError; после фикса — `JS-UNIT-OK`).
- [x] **Low:** помечены мёртвый токен `--surface-glass` и неиспользуемый `data.secretMask` (комментарии); инертный `.scope-panel card-solid` не трогали.
- [x] **Гейты:** `node --check web/app.js` OK; `round1020_ui_rework_test.js`/`round1020_ui_test.js`/`routing_test.js` = `JS-UNIT-OK`; `vue_mount_test.js` = `VUE-MOUNT-OK`; полный `pytest tests/ -q --timeout=300` = **6572 passed / 0 failed**.

### T-1936-fix2 (@Builder) — финальные фиксы по независимому аудиту T-1941 (M-1/L-1/L-2)

> Итерация 3 по `plans/reports/round1020_ui_rework_scanner_audit.md` (0 Critical/0 High; 1 Medium + 2 Low).
> Правки только во фронтенде (`web/app.css`, `web/index.html`, `web/app.js`) + осознанное обновление тестов.
> Меню/бэкенд/`web/api/**`/каталог/БД не трогались.

- [x] **M-1 (Medium):** `web/static/app.css` — убран резервный `padding-bottom: calc(1rem + var(--sticky-save-h))` у `.scroll-area:has(> .sticky-save)` (он сужал content-box и «подвешивал» sticky-панель на 88px выше низа). Теперь `padding-bottom: 0` (снятие fullscreen-паддинга) + `scroll-padding-bottom: var(--sticky-save-h)`; место над панелью резервирует спейсер `.sticky-spacer` (`height: var(--sticky-save-h)`, `pointer-events: none`) в потоке непосредственно **перед** `<sticky-save>` (в config- и access-ветках). Фолбэк `@supports not (selector(:has(*)))` больше не добавляет `padding-bottom` (заодно закрыт L-3). `safe-area-inset-bottom` остаётся на самой панели.
- [x] **Chromium-зонд (Playwright, реальный app.css):** fullscreen-скроллер, 40 блоков — было `bandBelow = 88` (sticky.bottom = 712 при scrollport = 800), стало `bandBelow = 0` (sticky.bottom = 800) на `scrollTop` 0/1000/max; `overlap = false`, последний контент выше панели.
- [x] **L-1 (Low):** `web/index.html` — 3 provider-инпута: безусловные `@focus="$event.target.select()"`/`@mouseup.prevent` заменены на условные по `f.secret` (`@focus="f.secret && …select()"`, `@mouseup="f.secret && $event.preventDefault()"`) — выделение/защита только для секретных; не-секретные (`base_url`/`model`/`display_name`) снова ставят каретку мышью. Secret-only `@focus select` у `keyDrafts`-полей (3 точки) не затронут.
- [x] **L-2 (Low):** `web/app.js` — при композите маски (`mask+X`) тост «Уже сохранено» заменён на понятную подсказку-константу `SECRET_MASK_HINT`: «Поле содержит маску сохранённого секрета — выделите поле и введите значение заново». Сохранение остаётся no-op (0 POST), маска/композит на сервер не уходят (R31).
- [x] **Тесты (red→green):** `tests/test_webapp_ui_rework_round1020.py` + `tests/js/round1020_ui_rework_test.js` — ассерты «у скролл-контейнера нет резервного `padding-bottom` / только `scroll-padding-bottom`», «`.sticky-spacer` резервирует место перед панелью», «условный `@focus f.secret`, безусловных обработчиков нет», «фолбэк без `padding-bottom`», «сообщение при композите». Red зафиксирован (2 python + 1 js assert падали на старом коде).
- [x] **Гейты:** `node --check web/app.js` OK; `routing_test.js`/`vue_mount_test.js`/`round1020_ui_test.js`/`round1020_ui_rework_test.js` — OK; полный `pytest tests/ -q --timeout=300` = **6574 passed / 0 failed**.

### T-1937 (@Builder) — Дефект 4: фоновый градиент (оранжевый + скорость + углы)

- [x] `app.css`: `--grad-speed` 14s → **6s** (диапазон 5–8s); добавить оранжевый токен (напр. `--grad-orange:#F97316`) и включить его в stops `conic-gradient` (стр. 76–80), `--accent-grad` (стр. 40) и/или `body::before` (стр. 103).
- [x] Отрегулировать углы: `@property --grad-angle` initial + `@keyframes grad-spin` (стр. 44, 74) кратно числу стопов; `@keyframes grad-drift` (стр. 75) + `background-size: 200% 200%` — переливы **явно заметны**.
- [x] Поднять видимость page-wash: `body::before { opacity: .16 → .28–.35 }` (стр. 106) — без потери контраста текста (текст на плотных подложках).
- [x] Сохранить `@media (prefers-reduced-motion)` и `(prefers-contrast: more)` (стр. 108–118).
- [x] **DoD:** CSS-ассерт `animation-duration` градиента ∈ [5s, 8s]; оранжевый stop присутствует; углы заданы; reduced-motion/contrast гасят анимацию. Градиент заметен **под модалкой** (связь с дефектом 1 — стекло читается только на цветном фоне).

### T-1938 (@Builder) — Дефект 5: переверстать sticky-save

- [x] `app.css::.sticky-save` (стр. 809–822): аккуратное прилипание к низу — корректные `padding`/`margin`, `padding-bottom: calc(.5rem + env(safe-area-inset-bottom, 0px))`, панель в потоке (не `absolute`), фон glass + `z-index` без перекрытия контента.
- [x] `web/index.html`: дать скролл-контейнерам запас снизу (`padding-bottom`/`scroll-padding-bottom`) — последний элемент не уходит под панель; проверить модалку модуля (стр. 758, `.modal-body max-height:80dvh`) и финальную config-ветку (стр. 704), а также ветки modules/access (регресс S10.20-1 не вернуть).
- [x] Проверить desktop + mobile (≤ 479px): отступы модалки не сломаны, панель не «наезжает» на футер/кнопки.
- [x] **DoD:** CSS-ассерт `position:sticky` + `bottom:0` + safe-area; offset-замер показывает, что нижний элемент контента НЕ перекрыт; панель присутствует в каждой ветке (config/modules/access), как в S10.20-1.

### T-1939 (@Builder) — тесты: DOM/CSS-ассерты (каскад + поведение), red→green

- [x] Новый `tests/js/round1020_ui_rework_test.js` (node): `blockFieldValue` маска/пусто; `saveKeyItem`/`saveBlock` не пишут маску; sentinel-хелперы; sticky-dirty. Запуск → `JS-UNIT-OK`.
- [x] Новый `tests/test_webapp_ui_rework_round1020.py`:
  - [x] **CSS-парсер по селекторам** (не «строка есть в файле»): извлечь правила `app.css` и проверять объявления **именно** у `.modal-card`, `.card`, `.module-list`, `.hub-grid`, `.sticky-save`.
  - [x] **Каскад-резолвер**: для реальной цепочки классов из разметки (`.modal-card.card.card-solid`) вычислить победителя (специфичность + порядок) и проверить фон = `rgba(20,25,30,0.5)`, `backdrop-filter`/`-webkit-backdrop-filter` = `blur(16px)`.
  - [x] **Разметка**: ни один `.modal-card` не несёт `.card-solid` (либо override выигрывает); grid-контейнеры — без `background`.
  - [x] **Grid**: точная тройка (`display:grid`; `repeat(auto-fit, minmax(320px,1fr))`; `gap:1rem`) у `.module-list`/`.hub-grid`.
  - [x] **Градиент**: `animation-duration` ∈ [5s, 8s]; оранжевый stop/токен; углы; reduced-motion/contrast.
  - [x] **Sticky**: `position:sticky`, `bottom:0`, safe-area, отсутствие `absolute`.
  - [x] **Снимок навигации** (меню НЕ изменено) — как в `tests/test_webapp_round1020_ui.py`.
- [x] **Обязательно:** снять **red-прогон до фикса** (зафиксировать, что новые ассерты падают на текущем коде) → после фикса **green**. Приложить вывод в отчёт.
- [x] Полный `pytest tests/` — 0 регрессий; `node --check web/app.js`; `git diff --check` clean.

### T-1940 (@Reviewer, гейт) — верификация ФАКТИЧЕСКОГО рендера/классов

> **Запрещено** принимать доказательство вида «класс присутствует / CSS-строка есть / где-то есть панель».
> Верификация — по **фактическому рендеру** и **отдаваемым сервером** артефактам.

- [x] (1) Подтвердить, что **отдаваемый** CSS содержит новые значения (запрос `/web/static/app.css` на локальном/тестовом стенде; **без секретов** в выводе) — исключает «в репо есть, клиент видит старое». *(локальный TestStatic → 41 passed вместе с ui_rework; прод — T-1942)*
- [x] (2) CSSOM-зонд (готовый сниппет в отчёте): `getComputedStyle(document.querySelector('.modal-card'))` → `backgroundColor === 'rgba(20, 25, 30, 0.5)'`, `backdropFilter` содержит `blur(16px)` — **во всех** модалках (modules/access/dossier/confirm), не в одной.
- [x] (3) Grid: `getComputedStyle(document.querySelector('.module-list')).gridTemplateColumns` и `.hub-grid` → **≥ 2 трека** при ширине 1280px. *(1440px: 4/3/3 трека; 400px — 1)*
- [x] (4) Маска: в модалке «Диагностика» значения инпутов `Пароль Betterstack SQL`/`Пользователь Betterstack SQL` = `••••••••••••` (при наличии в БД); проверить ≥ 1 поле в каждом модуле. *(+ композит `mask+X` → 0 POST)*
- [x] (5) Sticky: нет перекрытия контента (визуально + offset-замер) во всех ветках (config/modules/access). *(gap +16px / +29px)*
- [x] (6) Градиент: `animation-duration` ∈ [5s, 8s], оранжевый виден, переливы заметны. *(6s, `#FF8A3D`)*
- [x] Отчёт `plans/reports/round1020_ui_rework_reviewer.md` с **сырыми** выводами зондов и списком проверенных модалок. *(секция «Re-review (итерация 2)»)*
- [x] **Контекст провала:** в 10.20 UI «прошёл» ревью по формальным признакам, а живая приёмка T-1904 осталась ⏸. В этот раз **код-гейт самодостаточен** — без отсылки «человек проверит потом».

### T-1941 (@Scanner, независимый re-audit) — рендер/классы + served-CSS + регрессии

- [x] Независимо воспроизвести зонды T-1940 (своими средствами) на фактическом рендере: glass/`backdrop-filter`, grid-треки, маска, градиент, отсутствие перекрытия sticky-панелью. *(Chromium 151 CSSOM + Node-пробы; отчёт `round1020_ui_rework_scanner_audit.md`)*
- [x] Проверить, что **меню/навигация/разделы не изменены** (снимок; сравнение с 10.20). *(25 tabs / 6 nav / 12 modules)*
- [x] Проверить served-CSS/`APP_VERSION` (`?v=` cache-bust) и отсутствие серверного пути отдачи «пустого CSS». *(локально `TestStatic`+`ui_rework` 41 passed; прод — T-1942)*
- [x] R18: скан `plans/**` на креды; проверить, что отчёты/логи не содержат значений. *(0 совпадений)*
- [x] Finding-таблица (Critical/High/Medium/Low/Info) + ре-проверка закрытий. **0 Critical / 0 High / 1 Medium / 3 Low / 3 Info** → блокеров нет. Отчёт `plans/reports/round1020_ui_rework_scanner_audit.md`.

### T-1942 (@DevOps, гейт) — деплой + прод-проверка доставки CSS

- [x] Пуш + деплой по протоколу (`git pull`, `systemctl restart admin_bot`, `systemctl status admin_bot`); секреты в репо/выводе **не хранить** (R17/R18).
- [x] Прод-проверка: бот `active`; отдаётся **новый** CSS (проверка без печати секретов); UI-страница открывается.
- [x] Зафиксировать в отчёте: коммит, статус сервиса, подтверждение доставки CSS/`APP_VERSION`.

## 6. Feature Flags / Progressive Delivery

- **Флаг не вводится** (каталог-Δ = **0**): доработка UI — безусловная, как и весь БЛОК 3 раунда 10.20.
- **Поэтапная раскатка 10→50→100% не применяется** (иначе дефект остаётся у части пользователей).
- **Откат:** `git revert` (безусловная фича). Отдельных toggle нет.
- **Кэш-гейт доставки (обязателен):** `?v=__APP_VERSION__` для `app.css`/`app.js`; при необходимости — бамп `APP_VERSION`
  (`config/settings.py:1274`); проверка фактической отдачи нестареющего CSS (T-1940 п.1, T-1942).

## 7. Риски

| # | Риск | Почему это важно | Мера |
|---|---|---|---|
| **R27** | **Ложная приёмка** (корень провала): ревью проверяло «класс/панель где-то есть», а не каскад/вычисленный стиль и не отдаваемый клиенту артефакт; живая приёмка `T-1904` осталась ⏸ | Именно так UI «прошёл» при фактически неработающих дефектах 1/2/3 | T-1939: CSS-парсер **по селекторам** + каскад-резолвер + **red→green**; T-1940: CSSOM-зонд + served-CSS; явный запрет «grep-доказательства» |
| **R28** | **Каскад/нейтрализация стекла**: `.card-solid` (0.88) и `--surface-glass` (0.72) перебивают прозрачность; Tailwind-утилиты грузятся раньше, но могут влиять на потомков | Фон останется «сплошным кирпичом» (дефект 1) | T-1933 каскадный контракт; T-1934 убрать `.card-solid`/переопределить; T-1939 резолвер для реальной цепочки классов |
| **R29** | **Стекло не видно без цветного фона**: `body::before` c `opacity:.16` под тёмной подложкой — блюрить нечего | Даже с `blur(16px)` владелец увидит «не стекло» | Дефект 4 (градиент) усиливает фон; проверка стекла **на участке с градиентом** (T-1940 п.2) |
| **R30** | **Кэш статики**: клиент/WebView отдаёт старый `app.css` (нет бампа `APP_VERSION`) | Фикс в репо ≠ фикс в браузере владельца | T-1940 п.1 (served-CSS), T-1942 (прод-проверка), `?v=`/`no-store` |
| **R31** | **Маска сохраняется как секрет**: предзаполнение инпута `••••` попадает в `keyDrafts`/`blockDrafts` → `POST /api/config` перезапишет реальный ключ точками | **Порча данных/BYOK** | T-1936: `isSecretMask`-guard в `saveBlock`/`saveKeyItem`; тест «маска → 0 запросов»; очистка по фокусу |
| **R32** | **Grid ломается родителем**: `<main class="grid grid-cols-1">` + Tailwind-каскад | Одна колонка сохранится (дефект 2) | T-1935 проверка обеих сторон; T-1939 ассерт тройки правил; замер треков в T-1940/1941 |
| **R33** | **Sticky-save перекрывает контент** или ломает padding/margin (повтор дефекта 5) | Повторный провал приёмки; регресс S10.20-1 (потеря сохранения) | T-1938: запас снизу у скролл-контейнера + safe-area; offset-замер; проверка присутствия панели во **всех** ветках |
| **R34** | **Fallback/`@supports` потеряны** (Android/Nekogram WebView без `backdrop-filter`, `@property`) | Текст на прозрачном фоне → нечитаемость | T-1934/T-1937 сохраняют `@supports not`, `prefers-reduced-motion`, `prefers-contrast`; проверка в T-1940 |
| **R35** | **R18/R17**: реальные секреты в тестах/отчётах; значения полей Betterstack | Утечка кредов в git | Только маска/фейковый `last4`; скан `plans/**` в T-1941; значение SSH-пароля не цитировать |
| **R36** | **Не менять меню**: соблазн «починить» верстку перестановкой разделов/карточек | Прямой запрет владельца (БЛОК 3, стр. 92) | Констрейнт §3; снимок навигации в T-1939/T-1941 |

## 8. Handoff

- **Вход (Step 2):** @Architect — T-1933 (UI-контракт) → разблокирует @Builder.
- **Реализация (Step 4):** @Builder — T-1934…T-1939.
- **Верификация (Step 5–6):** @Reviewer — T-1940 (гейт фактического рендера) → @Scanner — T-1941 (независимый re-audit).
- **Деплой (Step 9):** @DevOps — T-1942.
- **Архив (Step 8):** @PM — перенести `plans/features/round1020-ui-rework/` → `plans/archive/` **после** подтверждённого рендера и деплоя.
- **Статус для @Orchestrator:** ✅ **COMPLETED + DEPLOYED + ЗААРХИВИРОВАН** (commit `ec93c3d`). Критерий выхода выполнен:
  T-1934…T-1938 закрыты с DOM/CSS-доказательствами, T-1939 red→green, T-1940/T-1941 подтвердили рендер, T-1942 задеплоил.
- **⏸ Остаток (human-pending):** живая приёмка владельцем — WebView (Telegram Android / Nekogram) + скриншот-приёмка §7.5.
