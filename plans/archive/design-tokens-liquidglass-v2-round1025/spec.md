# F2 `design-tokens-liquidglass-v2-round1025` — локальная спецификация

> **Раунд:** 10.25, Эпик 1, Волна 1 (F2 ∥ F3). **Задачи:** T-2529…T-2562 (`tasks.md`).
> **Мастер-ТЗ:** `plans/current_task.md` §8 (палитра/кнопки), §9 (Liquid Glass A/B/C), §10 (фон), §70 (адаптив), §71 (Playwright), §117 п.7–8/п.12. Файл — untracked, не коммитить; секреты не цитировать (R17/R18).
> **Статус:** Step 2 @Architect — спроектировано. Реализация — @Builder (Step 4).
> **ADR:** `adr-1025-9-design-tokens-liquidglass-v2.md` (D1–D6).
> **Baseline:** HEAD `f2328fb`, APP_VERSION **2.58.4**, pytest **8071/0**, JS **23/23**, matrix 0, `database is locked`=0, SQLite v12.

## Инварианты
1. **Δ DDL = 0**, **Δ каталога = 0**; CSP/zero-build (никаких новых библиотек, никакого WebGL/воркеров на карточках).
2. Не ломать F0 save-слой, F1 shell/safe-area/навигацию, hotfix-фиксы, Эпик 2/промпты. `web/app.js`/`app.css`/`index.html` — строго сериализованы (F1 → **F2** → F3).
3. **Код + эталон + тест — одним коммитом** (project.md); маркер-тесты обновлять атомарно. R17: без секретов в логах/скриншотах; бэкапы/теги/`stash@{0}` не удалять.
4. `services/**`, `web/api/**`, `web/app.py`, `services/param_catalog.py` — **не трогаются** (кроме палитры в `web/app.js:6344-6345`).

---

## 1. SUPERSEDE / AMEND (объявлено в ADR-1025-9)

**SUPERSEDE (значения):** OD4/Relume-палитра (`app.css:5-19`: `--surface-0..3`, `--text-1..3`, `--teal-500 #14CBB6`, `--purple-*`) → §8; градиент 10.20-UPD3 (`:20-24,47`: `--grad-d #FF8A3D`, `--grad-speed:6s`) → §10; glass 10.20 (`:36-42`) → §9 A/B/C; статус-цвета (`:18-19`) → §8 (`#F6C56F`/`#F07178`); фолбэки Telegram-темы (`telegram-init.js:14-17` `#161616/#0E0E0E`) и палитра графиков (`app.js:6344-6345`) → §8; ожидания ~11 тестов (список в `tasks.md` блок 4) — **SUPERSEDE ожиданий, не проверок**; устаревшая ссылка `plans/round1025-architecture.md:118` («F2/ADR-1025-2») → **ADR-1025-9**.

**AMEND ADR-1020-9** (значения палитры/glass/градиента) — **сохраняются механики**: glass-`@supports`-фолбэк, CSS Grid `minmax`, `SECRET_MASK`/`hasSecretMask`, sticky + `.sticky-spacer`, reduced-motion/contrast-гашение.

**НЕ отменяется:** CSP/zero-build; `@property --grad-angle` + `grad-spin/grad-drift` **как механика** (цвета/длительность меняются — D3); F1/hotfix4-достижения (`--tg-viewport-bottom-offset`, `viewport-fit=cover`, `.bottom-nav`/`.more-sheet`, порядок навигации, safe-area).

## 2. Решения по открытым вопросам (D1–D6, ADR-1025-9)

1. **Номер ADR:** `ADR-1025-9` (1…8 заняты). Ссылку `round1025-architecture.md:118` исправить (T-2562).
2. **Уровень A (D2):** **один** inline-SVG `feDisplacementMap`-фильтр в `web/index.html` (CSP-safe, без внешних/data-URI-дублей), ссылка `backdrop-filter: url(#lg-displace)`; применяется **по `data-glass="a"`** (opt-in allow-list), а не ко всем `.card`. `backdrop-filter: url()` надёжно лишь в Chromium → **progressive enhancement**: Level A включается только при поддержке, иначе B. WebKit **добавить как опциональную пробу** в харнесс; если движок недоступен — зафиксировать ограничением отчёта (прецедент ADR-1021-6).
3. **Kill-switch (D2):** **не вводим.** Env-only флаг потребовал бы доставки через `/api/me.ui_flags` (`web/api/routes.py`) — файл в F2 **не трогается**; деградацию дают лестница A→B→C + `prefers-reduced-motion` + тег отката. (Если владелец позже потребует — отдельной фичей с правкой routes.py.)
4. **Механика фона (D3):** **сохраняем** `@property --grad-angle` + `grad-spin/grad-drift` (по `tasks.md` «НЕ отменяется») — меняем только **цвета** (убрать `--grad-d`/оранжевый) и **длительности** (60–90 с; вторичные 90–120 с). Гарантия §10: **blur viewport не анимируется**; фон-псевдоэлемент ограничен; при деградации FPS (§71) — задокументированный фолбэк на transform/opacity-слои (D3-alt).
5. **Контраст (D4):** порог для `.75rem` (12 px — **нормальный**, не крупный) — **4.5:1** (WCAG AA). Коррекция оттенков §8 **разрешена** ТЗ «ради контраста»: допускается лёгкое осветление `--text-2/--text-3`/акцентов **без смены характера** палитры; итог — таблицей «пара→ratio→PASS» в ADR/отчёте.
6. **Inventory-тест (D5):** гибрид — **жёсткий эталон-список** имён токенов/классов/диапазонов (presence, ловит удаление) + **авто-скан `web/**`** на отсутствие OD4-литералов (`#FF8A3D`, `#161616`, `#14CBB6`, `#0E0E0E` и т.п.) (absence, ловит остатки). Списки — по **стабильным именам/паттернам**, не по целым CSS-блокам (анти-хрупкость для F4/F11).
7. **«Крупный элемент» (D2):** критерий — **явный opt-in `data-glass="a"`** (детерминированно, deny-list безопасен по умолчанию) + страховка: не применять, если min-сторона элемента `<240px` и/или это текстовый контейнер (deny-list §9: `textarea`/таблицы прав/логи/формы/редакторы промптов).
8. **Харнесс §71 (D6):** **расширять `tools/ui_round1025_matrix.py`** (единый харнесс, 10 вьюпортов) F2-пробами: computed-стили токенов, диапазоны длительностей, наличие/отсутствие glass (allow/deny), `prefers-reduced-motion`, `document.hidden`-пауза, rects; плюс опциональная WebKit-проба. Отдельный харнесс не заводим (риск дрейфа).

## 3. Решения по блокам и точки изменения (file:line)

| Блок | Решение | Файлы |
|---|---|---|
| 1 — палитра §8 | **Переназначить значения** токенов (имена потребителей сохранить; лучше алиас, чем удалить); убрать мёртвые OD4/UP D3 значения; пересчитать статус-тинты; иерархия кнопок (primary/secondary/danger) | `web/static/app.css:5-19,47`; `web/static/telegram-init.js:14-17`; `web/app.js:6344-6345` |
| 2 — Liquid Glass A/B/C | 3 уровня + `@supports not (backdrop-filter)`→C; class-маркеры `glass-a`/`glass-b`/`data-glass`; deny-list; один SVG-фильтр | `web/index.html` (SVG `#lg-displace`); `web/static/app.css:36-42` + новые селекторы |
| 3 — фон §10 | 60–90 с / 90–120 с; убрать `--grad-d`/`--accent-grad`-оранжевый; пауза при `document.hidden`; reduced-motion/contrast | `web/static/app.css:20-24,47,51`; `web/app.js:7992-8008` (не ломать polling-паузу), CSS-анимации |
| 4 — маркеры | inventory-«множества» + атомарные коммиты | `tools/ui_round1025_matrix.py`, `tools/ui_audit_round1021.py:253`; список тестов из `tasks.md` блок 4 |
| 5 — Playwright §71 | 10 вьюпортов + F2-пробы + скриншоты (gitignored) | `tools/ui_round1025_matrix.py:307` |
| 6 — cache-bust | `APP_VERSION` 2.58.4 → **2.58.5** + `?v=`-пины + README | `config/settings.py`, `README.md`, тесты |

## 4. Проверяемость
- **Chromium (+опц. WebKit):** computed `backdrop-filter` на allow-list и его **отсутствие** на deny-list; уровни A/B/C и `@supports`-фолбэк; отсутствие искажений текстовых узлов; console/pageerror/CSP = 0.
- **Палитра:** computed-значения токенов §8; отсутствие OD4-литералов в `web/**`; контраст-таблица (в т.ч. `.75rem` ≥4.5:1).
- **Фон:** длительности в диапазонах §10 (не 6 с), нет `#FF8A3D`; 2–3 фазы цикла на скриншотах; пауза при `document.hidden`; `prefers-reduced-motion` → `animation-name: none`.
- **Раскладка:** `document.documentElement.scrollWidth <= window.innerWidth + 1`, `boundingClientRect` в границах, панель/safe-area (F1) не регрессируют; низкое окно TG Desktop.
- **Регресс:** pytest ≥8071/0 (+новые), JS ≥23/23 (+новые), matrix 0, `database is locked`=0, `node --check`, `git diff --check`; red→green на старом CSS.

## 5. Риски и откат
| Риск | Ур. | Снятие |
|---|---|---|
| Искажение текста/кнопок стеклом | High | уровень A только opt-in + deny-list; проверка computed/скриншоты |
| Потеря маркера при переименовании токенов | High | D5 hybrid-инвентарь + атомарные коммиты |
| CSP/zero-build нарушены | Critical | только inline SVG/data-URI, без библиотек/WebGL |
| Производительность стекла/фона | Medium | blur не анимируем; D3-alt (transform/opacity) как фолбэк |
| Регресс F1/hotfix4 (панель/safe-area) | High | §71-пробы rects; не трогать shell-токены |
| Читаемость `.75rem` | High | D4: 4.5:1 + разрешённая коррекция оттенков |
| Секреты в скриншотах/отчётах | Critical | скриншоты gitignored; R17/R18 |

**Откат:** тег `pre-round1025-f2` (T-2529) + `git revert` + возврат `APP_VERSION`/`?v=`. Бэкапы/теги/`stash@{0}` не удалять.

## 6. Покрытие
T-2529→§0; T-2530→§1/§2 (ADR-1025-9); T-2531…T-2537→Блок 1; T-2538…T-2543→Блок 2; T-2544…T-2549→Блок 3; T-2550…T-2553→Блок 4; T-2554…T-2556→Блок 5; T-2557→Блок 6; T-2558…T-2562→Блок 7. **Все 34 задачи покрыты.**

## 7. Ссылки
- `plans/features/design-tokens-liquidglass-v2-round1025/{tasks.md, adr-1025-9-design-tokens-liquidglass-v2.md}`
- `plans/ARCHITECTURE.md` §54/§55/§56; `plans/round1025-architecture.md` (стр. 118 → ADR-1025-9)
- ТЗ `plans/current_task.md` §8/§9/§10/§70/§71/§117; ADR-1016-2 (CSP), ADR-1020-9 (AMEND)
