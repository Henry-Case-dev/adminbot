# W7 — навигация, верхняя панель, единый переключатель области + сквозная очистка UI

Задача: **EVOL-023** (навигация/topbar/scope-switcher) + **EVOL-024** (сквозная
очистка интерфейса) из `plans/current_task.md` (§6, строки ~312–332).
Лейн: web/** (единственный UI-лейн этой волны). Оптика и данные вне `web/**`
не затрагивались.

Кандидат (worktree `evol/impl`): база `390cacaf` (первая редакция) →
`ca15a2f6` + правки §review-fix (31.10.2026). Хеши (sha256, первые 16) — на
состоянии ПОСЛЕ review-fix:

| файл | sha256 |
|---|---|
| `web/index.html` | `fb15f4131375c792` |
| `web/app.js` | `c1d726d18525f1e0` |
| `web/static/app.css` | `f0fef08b855042d4` |
| `tests/test_webapp_evol_w7_nav.py` (new) | `8b8d8063bc99131d` |
| `tests/js/evol_w7_nav_test.js` (new) | `5b4c806bb14d257f` |
| `tools/ui_evol_w7_nav_e2e.py` (new) | `bc54d51ed78cad73` |
| `tests/test_webapp_ui_rework_round1020.py` (re-pin) | `5ffca4d659e163f6` |
| `tests/js/evol032_health_glass_test.js` (re-pin) | `79b5bc9f693d78aa` |
| `tests/js/asap8_u084d_mini_lens_binding_test.js` (re-pin §review-fix) | `40ca36d334330280` |
| `tests/js/asap8_w2_fullscreen_policy_test.js` (re-pin §review-fix) | `faa4a7a19aadde14` |
| `tests/js/round1025_hotfix6_lens_heartbeat_shell_test.js` (re-pin §review-fix) | `01d7d4f216d9d199` |
| `evidence/w7-nav-inventory.json` (new) | `2cd1f8459d45962f` |

---

## 1. Что было сломано (замеры ДО правок)

Живой прогон настоящего `web/index.html` (Playwright, стабы API):

* **шапка desktop 1280×800 — 109 px**, из них вторая строка (область/ID/
  пользователь) занимала 39 px, а под заголовком оставалась пустая полоса;
* **крошка «Статус» над «Аналитикой»** — у верхнеуровневого раздела
  показывался фиктивный родитель (`breadcrumb` возвращал `root` для любого
  маршрута с parent `#/`);
* **topbar называл не раздел**: на хабе `#/ai` в шапке стояло
  «LLM Провайдеры» (подпись config-вкладки), а не «ИИ»;
* **выпадающая панель области**: `x=152` при sidebar `0…216` — панель
  накрывала боковую навигацию; `background-color: rgba(255,255,255,0.04)`,
  `backdrop-filter: none` — текст читался поверх движущегося фона. Причина
  архитектурная: `app.js` помечает панель `data-glass-nested="1"`
  («стекло в стекле», внутри backdrop-root шапки), а CSS гасит такие узлы до
  плоской белой .04 — для плавающего overlay это неверно;
* **дубль заголовка**: на `#/modules`/`#/access`/`#/memory` имя раздела
  стояло и в шапке, и крупным `.hub-title` в контенте;
* **нет свёртывания постоянной панели** на desktop (216 px всегда);
* **drawer (768–1199)**: открывался, но фокус оставался в шапке, Esc не
  обрабатывался панелью;
* **управляющие элементы без подписи**: на «Аналитике» безымянный `<select>`
  «по chat_id» рядом с селектором области читался как второй scope-выбор;
  33 иконочные кнопки `⟳` без доступного имени;
* `.viz-ovpop` / `.cover-menu` / `.scope-tech-body` — три разных рецепта
  подложки всплывающих меню.

## 2. Что сделано

### EVOL-023 §1 — архитектура «sidebar → разделам, topbar → контексту»

- desktop ≥1200: вторая строка шапки возвращается в тот же flex-ряд через
  `display: contents` (приём уже использовался legacy-веткой; разметка не
  дублируется, селектор остаётся один). Итог замера: **109 → 64 px**,
  `main.top == header.bottom` (перекрытия нет), резерв `--header-h` не тронут.
- 768–1199 по-прежнему двухстрочная компактная шапка ADR-1025-12 D5 — там
  ширины реально не хватает.
- `breadcrumb` — только на вложенных маршрутах; у верхнеуровневого раздела
  пути назад нет (фиктивная крошка «Статус» убрана).
- `headerTitle` берёт имя **раздела** из канонического реестра `navItems`,
  а не подпись config-вкладки (`#/ai` → «ИИ»).
- дубль имени в контенте убран: `≥768` `.hub-head .hub-title` скрыт
  (subtitle, счётчики, поиск/фильтры остаются), на `<768` заголовок шапки
  скрыт намеренно — там `.hub-title` единственный.

### EVOL-023 §2 — один Chat/Scope switcher для всех разделов

- переключатель остался ровно **один** (topbar), разделы читают `activeChatId`
  (PERMsoc/истории/оверрайды) — второго селектора области нет; добавлен
  маркер `data-nav-scope="unified"` и `aria-controls`/`id` для listbox.
- **разделение областей явное**: тип области в триггере (`GLOBAL`/`ЧАТ`/ЛС),
  блоки «Аналитики» подписаны сами — таблица чатов как «сводка всех чатов
  (кэш 60 с)», per-chat виджеты как «только этот чат»; смешения чисел
  per-chat и global в одном блоке нет (проверено живьём в обеих областях).
- геометрия: панель якорится по **левому** краю триггера (не уезжает под
  sidebar), кламп по вьюпорту остался в `positionScopePanel`, добавлен
  пересчёт при ресайзе/зуме; `max-height` ограничен видимой высотой.
- читаемость: новый слой overlay — токены `--overlay-bg/border/shadow/radius/z`
  (`rgba(23,28,42,0.94)` + hairline + тень); плавающие меню исключены из
  правила «стекло в стекле» селектором большей специфичности
  `[data-glass-nested="1"].scope-panel` и т.п. Рефракцию не имитируем: внутри
  backdrop-root предка она физически недостижима.
- длинные имена: `.scope-name` обрезается (ellipsis), бейдж типа области и ▾
  не сжимаются — проверено на имени 60+ символов, на 320/390/1280 и при зуме.

### EVOL-023 §3 — sidebar

- desktop: кнопка-«шеврон» (`data-sidebar-collapse`, 44×44, `aria-expanded`,
  title), rail-состояние 68 px (класс `sidebar-collapsed` на `.app-shell`),
  подписи скрыты, полные имена — в `title`/`aria-label`, контент сдвигается
  (`padding-left: 68px`), состояние персистится (`adminbot.sidebar_collapsed`).
- mobile/tablet: drawer получил `@keydown.esc`, перенос фокуса в панель при
  открытии и возврат фокуса в кнопку «Навигация» при закрытии; `inert`/
  `aria-hidden` уже были.
- состав разделов, маршруты и RBAC не менялись (пин реестра `NAV_ITEMS_V2`
  в тестах этой волны). Группировка/разделители остались прежними — новые
  уровни IA не выдумывались.

### EVOL-023 §4 — fullscreen

Механизм (`toggleFullscreen`, `fsSlot`, safe-area, восстановление) **не
менялся** — правки §review-fix касаются только внешнего вида кнопки и
возврата фокуса в селекторе области.

**Ревью W7 F1 (31.10.2026) — исправлено, см. §review-fix ниже.** Первая
редакция оставляла на ⛶ защищённую мини-линзу `.lg-mini-lens` и объясняла это
контрактом U08.4d/W2-GLASS. Ревью обоснованно отклонило: §4 требует
компактный иконочный контрол, а линза давала в шапке отдельный стеклянный
объект (радиальный градиент, рамка, rim `::after`, inset-блики,
`backdrop-filter`, тень). Теперь ⛶ — ghost-icon: прозрачная hit-цель 44×44 без
материала; `title`/`aria-label`/`aria-pressed` сохранены.

### EVOL-024 — сквозная очистка

- **инвентаризация**: 19 маршрутов × 6 вьюпортов (320/390/768/1024/1280/1920)
  — горизонтального скролла страницы нет ни на одном, элементов за вьюпортом
  нет, обрезанного текста без ellipsis нет.
- **единый overlay-слой**: `.scope-panel`, `.scope-tech-body`,
  `.more-menu-panel`, `.viz-ovpop`, `.cover-menu` — один токен-набор вместо
  трёх разных рецептов.
- **клавиатура/focus**: токены `--focus-ring`/`--focus-ring-offset` + видимый
  контур у `.sidebar-link`, `.scope-trigger`, `.scope-option`,
  `.mobile-topnav-link`, `.breadcrumb-link`; модалки (окно модуля, досье)
  получают фокус внутрь диалога через `_focusOpenedDialog` (Esc/возврат
  фокуса — существующими механизмами).
- **ясность действий**: сортировка «Аналитики» получила видимое имя
  «Сортировка» и человекочитаемые значения («по ID чата»), значения-ключи не
  изменились; контроль больше не читается как второй выбор области; на
  мобильном строка управления переносится, селектор не сжимается.
- **доступные имена**: 33 иконочные `⟳` получили `aria-label`/`title`
  «Обновить» (инвариант: у каждой `⟳`-кнопки есть доступное имя — тест).
- **пустые состояния**: проверены на месте и не «причёсаны» — «Бюджет
  недоступен», «Пока нечего показать — в графе памяти нет подтверждённых
  фактов», «PERMsoc работает только для конкретного чата…» (пин в тестах).
- плотность: редкие настройки остаются в `details.advanced`, power-user
  функции не удалялись; primary/secondary/danger (`btn-accent`/`btn-ghost`/
  `btn-danger`) не перекрашивались.

## 3. Проверки

### Структурные/юнит

* `tests/test_webapp_evol_w7_nav.py` — **22 passed** (новый: один переключатель
  области, компактный topbar, резерв под шапку, absence дубля заголовка,
  rail/персист, drawer focus/Esc, overlay-токены, focus-ring, модальный
  focus-хелпер, честные пустые состояния, доступные имена `⟳`, запуск
  JS-юнита).
* `tests/js/evol_w7_nav_test.js` — `JS-UNIT-OK` (breadcrumb/headerTitle/rail/
  drawer/`_focusOpenedDialog`).
* Обязательные из брифа: `tests/test_webapp_round1020_ui.py`,
  `tests/test_webapp_ui_rework_round1020.py` — зелёные; `node
  tests/js/round1020_ui_test.js`, `node tests/js/round1020_ui_rework_test.js` —
  `OK`. `tests/test_webapp_round1014_ui.py` — 33/34; единственное падение
  `TestCatalogInvariant::test_counts_unchanged` (558 против 570) вызвано
  чужими правками `services/param_catalog.py` (+92 строки в этом же worktree),
  не `web/**` (см. «Cross-lane наблюдение» ниже); на файле до этих правок
  набор был зелёным целиком.
* Набор UI/IA/webapp: **727 passed, 8 failed** — все восемь падают
  **идентично на базе HEAD** (проверено отдельным worktree на коммите
  `432c7593`): `round1021_ui_audit` (27≠28 вкладок), `round1024_image_module`,
  `soul1_w6_speech_ui` ×2, `webapp_api::test_param_permissions_matrix…`,
  `webapp_avatars_ui::test_close_and_fullscreen_buttons` (`✕` 6≠5),
  `round1024_nodeflow::test_no_english_jargon`, `tma_fixes_ui::test_logs_block_layout_mono`.
  JS-набор целиком: падают ровно те же 3 файла, что и на базе.

### Живой рендер (Playwright, детерминированно)

`tools/ui_evol_w7_nav_e2e.py` → **EVOL-W7-NAV OK**. Проверяет: высоту шапки
(≤76 desktop, ≤132 mobile), отсутствие перекрытия/горизонтального скролла,
ровно один переключатель, имя раздела, отсутствие дубля заголовка, ⛶ 44×44 +
tooltip, геометрию/подложку/поиск/Esc панели области, обрезку длинного имени
без наезда на бейдж, rail + персист после reload, drawer (фокус внутрь, Esc,
возврат фокуса), меню «Ещё» в границах вьюпорта, 320 px и zoom 200 %, модалку
(в вьюпорте, внутренний скролл, фокус внутри), медленный API (каркас цел).

Факты из прогона: desktop header `64`, `overlap 0`, панель области
`x=764`, `bg rgba(23,28,42,0.94)`, `overlapsSidebar=false`, rail `68` c
персистом, drawer `x=0` c фокусом внутри и возвратом в триггер,
mobile панель `16…316` при `vw=390`, zoom 200 % и 320 px без h-скролла.

### Живой рендер (Browser Use, реальный браузер)

Просмотрены вкладкой реального Chrome (движущийся полигональный фон,
DPR 1): desktop 1280 (шапка/меню/rail), tablet 900 (drawer), mobile 390
(шапка, панель области, «Сортировка»). Скриншоты:
`w7-nav-live-*.png|jpg` в этой же папке. Отмечено: в фоновой вкладке Chrome
тормозит CSS-transition drawer — после `activate_tab` панель встаёт на `x=0`;
это поведение браузера, не дефект CSS (подтверждено и Playwright-прогоном).

### Артефакты

`plans/features/evol/audit/evidence/`: `w7-nav-desktop-{modules,scope-panel,
rail,modal}.png`, `w7-nav-tablet-drawer.png`, `w7-nav-mobile-{scope-panel,
more}.png`, `w7-nav-case-{320x700-z1,1280x800-z2,1280x800-z1-d900}.png`,
`w7-nav-probe.json`, плюс кадры реального браузера `w7-nav-live-*`.

## 4. Переквалифицированные пины (осознанно, с комментариями)

1. `tests/test_webapp_ui_rework_round1020.py` — из `GLASS_SET` убран
   `.scope-panel`: он больше не стеклянная карточка, а слой overlay. Причина
   и фактический дефект зафиксированы в комментарии; новая поверхность защищена
   отдельной проверкой в `test_webapp_evol_w7_nav.py`
   (`test_scope_panel_geometry_and_overlay`, `test_single_overlay_contract`).
2. `tests/js/evol032_health_glass_test.js` — граница «секции здоровья» задана
   явно (до следующего баннера раздела), а не «до конца файла»: W7 добавила
   свою секцию ниже, из-за чего в окно проверки попадали чужие правила.
   Инварианты (нет внешнего glow/backdrop-filter в health-правилах) сохранены
   и стали точнее.
3. Счётчики вкладок/меню (28 вкладок, 8 пунктов nav, 6 legacy-пунктов)
   **не менялись** — эта волна их не трогает; предсуществующее расхождение
   `27≠28` оставлено как есть и зафиксировано в разделе «остаточные риски».

## 5. Что осталось / ограничения

* **Двухстрочная мобильная шапка** (область + строка разделов, 116 px)
  сохранена: это утверждённая схема U01.1/U01.3 (4 сегмента + «Ещё»),
  перекомпоновка — предмет EVOL-025 (адаптивность), не этой волны.
* **Модалки** не перекрашивались: `.modal-card` — Tier A стекло (EVOL-022),
  единый вид обеспечен токенами радиуса/тени, а не новой подложкой. Фокус,
  скролл и границы вьюпорта проверены живьём.
* **Кнопка ⛶** — ghost-icon без декоративной линзы (см. §review-fix, F1);
  материал `.lg-mini-lens` в CSS сохранён для glass-тест-стенда.
* `#/modules/direct/models`: три кнопки «Проверить» — одинаковое действие по
  стадиям (не та неоднозначность, что в Vision EVOL-019); добавлено доступное
  имя «Проверить стадию: …», текст не менялся (пины).
* Доступные имена добавлены иконочным `⟳`; прочие мелкие icon-only контролы
  (звёздочки, стрелки) — в бэклоге как `related-nonblocking`.
* Предсуществующие (не мои) падения перечислены в §3; они не связаны с
  `web/**` этой волны и воспроизводятся на базе.
* **Cross-lane наблюдение** (`related-nonblocking` для W7, блокирующее для
  владельца каталога): `tests/test_webapp_round1014_ui.py::TestCatalogInvariant::test_counts_unchanged`
  падает (`570 != 558`) из-за правок `services/param_catalog.py` (+92 строки
  другим лейном в этом же worktree). На базе `432c7593` этот файл проходит
  целиком (34 passed), к `web/**` отношения не имеет — пин счётчика должен
  переквалифицировать владелец каталога.

---

## 6. §review-fix — блокеры ревью EVOL-023 (31.10.2026)

Кандидат: worktree `evol/impl`, база `ca15a2f6` + правки этого раздела.
Затронуто: `web/index.html`, `web/static/app.css`, `web/app.js`,
`tests/test_webapp_evol_w7_nav.py`, `tests/js/evol_w7_nav_test.js`,
`tools/ui_evol_w7_nav_e2e.py`, плюс осознанная переквалификация трёх пинов
U08.4d/W2 (6.3). `web/static/glass.js`, `glass-refraction.js`,
`aurora-flow.js`, polygon-фон и `services/**` — **нулевой дифф**
(`git diff --stat` по ним пуст).

### 6.1 F1 (BLOCKER) — ⛶ больше не стеклянная линза

* **Было (замер до правки):** узел нёс `header-fs-btn lg-mini-lens`; computed:
  `background-image` = `radial-gradient(...)`,
  `border: 1px rgba(210,235,255,.35)`,
  `box-shadow: 0 4px 14px … + inset 0 ±1px`, `backdrop-filter:
  var(--lg-frost-hero)`, `border-radius: 50%`, плюс `::after`-rim. В шапке это
  читалось отдельным стеклянным объектом → §4 («компактный control с
  прозрачной областью нажатия») не выполнялся. Пин
  `test_ghost_icon_with_hit_area` при этом ТРЕБОВАЛ `lg-mini-lens` и проверял
  только отсутствие инлайнового `background` — то есть защищал дефект.
* **Стало:** класс `.lg-mini-lens` с узла снят; `.header-fs-btn` объявляет
  ghost-контракт (`background: transparent; border: 0; border-radius: 0;
  box-shadow: none; backdrop-filter: none; color: inherit`) и сохраняет
  `min-width/min-height: 44px`, `title`, `aria-label`, `aria-pressed`,
  `@click="toggleFullscreen()"`. Иконка остаётся видимой (`currentColor` →
  `rgb(244,247,251)`), hover/active — только `filter: brightness`.
* **Живой замер после правки** (computed, Chrome, настоящий `index.html`):
  * 1280 → `44×44 | rgba(0,0,0,0) | background-image none | shadow none |
    blur none | radius 0px | color rgb(244,247,251) | class
    "text-xs shrink-0 header-fs-btn" | title/aria «На весь экран»`;
  * 390 → те же значения.
  Скриншоты: `w7-nav-live-fs-ghost-1280.png`, `w7-nav-live-fs-ghost-390.png`,
  крупно `w7-nav-live-fs-ghost-btn-1280.png`/`-390.png`; детерминированно —
  `w7-nav-fs-ghost-header-1280.png`, `w7-nav-fs-ghost-header-390.png`.
* Материал `.lg-mini-lens` из CSS не удалён: он нужен изолированному
  `tests/glass-teststand` и Tier-A селекторам движка (`_lgGlassSelector`,
  `SURFACE_SELECTOR` не менялись). Удалена только привязка материала к
  функциональной кнопке.

### 6.2 F2 — Esc из поиска возвращает фокус в триггер

* **Было:** `closeScope()` только снимал `scopeOpen`; после Esc из поиска
  панель исчезала вместе с полем ввода, и `document.activeElement` падал на
  `BODY`. Клавиатурный пользователь терял точку возврата, а e2e проверял лишь
  «панель закрылась».
* **Стало:** `closeScope()` до снятия флага запоминает, был ли фокус внутри
  `.scope-panel`, и после закрытия возвращает фокус в `.scope-trigger` — тот
  же паттерн, что `closeDrawer` → `[data-drawer-trigger]`. Возврат только при
  реальном закрытии и только если фокус был в панели или уже потерян: чужой
  фокус не перебивается, повторный Esc идемпотентен, без DOM — no-op.
* **Проверки:** юнит `tests/js/evol_w7_nav_test.js` §7 (фокус из поиска →
  триггер, идемпотентность, чужой фокус, отсутствие DOM); e2e
  `desktop_scope_escape` → `{panel:false, tag:"BUTTON", isTrigger:true,
  expanded:"false"}`; живьём — клик в поле поиска, Esc → фокус на триггере с
  видимым кольцом (`w7-nav-live-scope-esc-focus-1280.png`).

### 6.3 Осознанно переквалифицированные пины (U08.4d/W2)

| файл | что было | почему изменено |
|---|---|---|
| `tests/js/asap8_u084d_mini_lens_binding_test.js` | требовал `lg-mini-lens` на ⛶ и материал в CSS | требование §4 его отменяет: проверка стала отрицательной (материала на кнопке нет), материал в CSS/движке сохранён; `TEST-LIFECYCLE` помечен `superseded-by EVOL-023 §4` |
| `tests/js/round1025_hotfix6_lens_heartbeat_shell_test.js` | пинил точный `class="… header-fs-btn lg-mini-lens"` | класс снят: пин проверяет `header-fs-btn` и отсутствие линзы |
| `tests/js/asap8_w2_fullscreen_policy_test.js` | «в правилах `.header-fs-btn` вообще нет `background:`» | ghost-контракт объявляет `background: transparent` явно; пин проверяет прозрачность + отсутствие градиента/рамки/тени/blur/скругления |
| `tests/test_webapp_evol_w7_nav.py::TestFullscreenContract::test_ghost_icon_with_hit_area` | требовал линзу | требует ghost: прозрачный фон, `border: 0`, `box-shadow: none`, `backdrop-filter: none`, 44×44, `title`/`aria-label`/`@click` |

Остальные пины не ослаблены: `round1025_design_tokens` (материал
`.lg-mini-lens` в CSS), `glass_probe`, `_lgGlassSelector`/`SURFACE_SELECTOR` —
зелёные без правок.

### 6.4 Машинная инвентаризация EVOL-024 (запрос ревью)

Раньше «19 маршрутов × 6 вьюпортов» было утверждением в отчёте без артефакта.
Теперь `tools/ui_evol_w7_nav_e2e.py` строит инвентарь сам: **19 маршрутов ×
6 вьюпортов = 114 ячеек** (320/390/768/1024/1280/1920; список маршрутов —
канонический из матрицы §71, второй реестр не заводится). Артефакт:
`evidence/w7-nav-inventory.json` — `cells[]` с `hScroll`, `offscreen`,
`clipped` на каждую пару плюс `summary`. Результат прогона:
`{"routes": 19, "viewports": 6, "cells": 114, "hScroll": 0, "offscreen": 0,
"clipped": 0, "failures": 0}`. Элемент внутри намеренного горизонтального
скроллера (табы «Аналитики», таблицы) дефектом не считается; обрезка текста
без `ellipsis` — считается.

### 6.5 Прогоны ревью-фикса

| команда | результат |
|---|---|
| `pytest tests/test_webapp_evol_w7_nav.py` | **22 passed** |
| `pytest tests/test_webapp_round1020_ui.py` | **24 passed** |
| `pytest tests/test_webapp_ui_rework_round1020.py` | **28 passed** |
| `node tests/js/evol_w7_nav_test.js` | `JS-UNIT-OK` |
| `node tests/js/round1020_ui_test.js` | `JS-UNIT-OK` |
| `node tests/js/round1020_ui_rework_test.js` | `JS-UNIT-OK` |
| `node tests/js/asap8_u084d_mini_lens_binding_test.js` | `MINI-LENS-BINDING-OK` |
| `node tests/js/round1025_hotfix6_lens_heartbeat_shell_test.js` | `HOTFIX6-LENS-HEARTBEAT-SHELL-OK` |
| `node tests/js/asap8_w2_fullscreen_policy_test.js` | `FS-POLICY-OK` |
| `node tests/js/round1025_design_tokens_test.js` | `JS-UNIT-OK` |
| `python tools/ui_evol_w7_nav_e2e.py` | `EVOL-W7-NAV OK`, инвентарь `failures: 0` |
| `pytest tests/test_webapp_js_unit.py` | 37 passed, 2 failed — **предсуществующие** (`round1021_ui_audit` 27≠28 вкладок, `round1024_image_module`), воспроизводятся на базе, к `web/**` отношения не имеют |

## Коротко по-русски

Верхняя панель стала компактной однострочной на десктопе (109 → 64 px, контент
начинается сразу под ней, пустая полоса и дублирующиеся заголовки убраны), в
шапке теперь правильное имя раздела, а не подпись внутренней вкладки. Один
переключатель чата/области на всё приложение: длинные названия аккуратно
обрезаются, выпадающее меню больше не заезжает под боковую навигацию и имеет
плотную читаемую подложку на движущемся фоне. Боковую панель можно свернуть в
иконки (состояние запоминается), на планшете шторка навигации корректно
забирает и возвращает фокус и закрывается по Esc. Заодно приведены к одному
виду всплывающие меню, добавлены видимые клавиатурные фокусы, понятная подпись
у сортировки в «Аналитике» и доступные имена у иконочных кнопок обновления.
Проверено на реальном рендере (десктоп 1280, планшет 900, телефон 390, 320 и
зум 200 %) — горизонтального скролла и перекрытий нет; 22 новых теста зелёные,
обязательные наборы зелёные, восемь падающих тестов — предсуществующие и
воспроизводятся на базе.

**Ревью-фикс (31.10.2026).** Кнопка «на весь экран» в шапке больше не выглядит
стеклянным кружком: осталась только иконка и невидимая область нажатия 44×44
(фон полностью прозрачный, без рамки, тени и размытия — проверено замером
computed-стилей и скриншотами на 1280 и 390). В переключателе чатов Esc из
поля поиска теперь возвращает фокус на сам переключатель, а не «теряет» его
в никуда. Добавлен машинный инвентарь вёрстки: 19 маршрутов × 6 вьюпортов =
114 ячеек, ни одной с горизонтальным скроллом, выходом за экран или обрезанным
без многоточия текстом (`evidence/w7-nav-inventory.json`).

## §review-fix — ASAP-UI-02 §2 (навигация/топбар/иконки), 31.10.2026

Основание: `plans/current_task.md` L1786–1818 (§2), `docs/ui-navigation-contract.md`,
матрица `asap-ui-02-matrix.md` (8 конфликтующих строк). Отменённые решения не
восстанавливались — заменено ровно конфликтующее.

### Что изменено в продукте

| Файл | Дельта |
|---|---|
| `web/index.html` | удалены `nav.mobile-topnav` (нижняя панель разделов), `.sidebar-brand`/`.sidebar-brand-title`, `.mobile-brand`; drawer и backdrop рендерятся по `iaV2 && hasDrawer`; кнопка навигации `[data-drawer-trigger]` (inline-SVG menu, `aria-label="Открыть навигацию"`, `aria-expanded`), точка входа `[data-more-trigger]` (троеточие) на mobile; `.header-user-name`/`.header-user-role`/`.header-user-initial`; `aria-current` у пунктов drawer; класс `drawer-open` на shell |
| `web/app.js` | удалены `mobileTopnavItems`, `mobileMoreItems`, `moreMenuTriggerLabel`, `moreMenuActive`, `moreMenuPick`, `_syncBottomNavMetric` (+ наблюдатель `_navObserver` и `--bottom-nav-h`); добавлены `hasDrawer`, `meUserTitle`, `meInitial`; диагностика ⛶ фиксирует отсутствие узлов бренда |
| `web/static/app.css` | удалены все правила `.mobile-topnav*` (включая ландшафтный рейл и резерв 58px), `.sidebar-brand*`, `.mobile-brand*`, `--bottom-nav-h`; мобильная шапка — одна строка (`flex-wrap: nowrap`) с названием раздела, областью, аватаром+ролью, ⛶ и «⋯»; `.ui-ic`/`.header-nav-btn`/`.header-more-btn` (20px знак, hit ≥44×44, тихий hover/focus); `.header-user-name{display:none}` вместо `.header-user span{display:none}`; меню «⋯» раскрывается под шапкой (не bottom-sheet); `.app-shell.drawer-open main.scroll-area{overflow:hidden}` |

### Проверки (текущий кандидат)

| команда | результат |
|---|---|
| `pytest tests/test_webapp_evol_w7_nav.py` | **30 passed** (новый класс `TestAsapUi02Navigation` — 8 проверок) |
| `pytest tests/test_webapp_evol_w9_responsive.py` | **31 passed** |
| `pytest tests/test_webapp_evol_w10_sections.py` | **35 passed** |
| `pytest` (12 переписанных legacy-файлов) | **303 passed** |
| `pytest` (5 файлов, читающих `ui_round1025_matrix.py`) | **217 passed** |
| `node tests/js/*` (18 файлов) | все зелёные (`W2-SHELL-UNIT-OK`, `EVOL-W9-RESPONSIVE-OK`, `JS-UNIT-OK`, `CFG04-FORMS-OK`, `ASAP42-STEP2C2-LAYOUT-OK`, `HOTFIX4/6/7/9-*`, `MODULE-CATALOG-OK`, `MCA12-STORIES-UI-OK`, `FS-POLICY-OK`) |
| `python tools/ui_evol_w7_nav_e2e.py` | **EVOL-W7-NAV OK**, инвентарь 19×6 = 114 ячеек, `hScroll 0 / offscreen 0 / clipped 0` |
| `python tools/ui_evol_w9_responsive_e2e.py` | **EVOL-W9-RESPONSIVE OK**, инвентарь 19×8 = 152 ячейки, `hScroll 0 / offscreen 0 / clipped 0` |
| `pytest tests -k "webapp or frontend or shell or nav or layout or responsive or asap8/42 or cfg04 or hotfix"` | 3084 passed, **12 failed — предсуществующие** (проверено на HEAD: `data-speech-entry` 0, `>✕</button>` 6, `badge-btn` 0 в HEAD — тесты/инструменты отстали от EVOL-028/026, к `web/**` этой волны отношения не имеют) |

Живой Chromium (Playwright, реальные `web/index.html`+`app.js` с API-стабами):
320×700, 390×844, 667×375, 812×375, 768×1024, 1024×768, 1280×800, 1440×900 —
нижней панели нет нигде, кнопка навигации открывает drawer со всеми 8
разделами (фокус внутрь, Esc, возврат фокуса), в шапке одна строка,
аватар-инициал + бейдж роли видимы, логотипа нет, «⋯» — троеточие, меню
раскрывается под шапкой, горизонтального скролла и перекрытий нет.
Скрины: `evidence/w7-nav-mobile-header.png`, `w7-nav-mobile-drawer.png`,
`w7-nav-mobile-more.png`, `w7-nav-landscape-drawer.png`,
`w7-nav-fs-ghost-header-390.png`, `w7-nav-desktop-modules.png`,
`w9-responsive-phone-*/land-*/mid-*/wide-*`.

### Осознанные компромиссы (зафиксированы, не «баги»)

- **320 px:** все обязательные элементы видны, hit-цели остаются 44×44;
  место берётся из второстепенных деталей (имя чата и аватар чата в триггере
  скрываются при `≤419px`, `▾` — при `≤359px`, бейдж роли — `4rem`).
  Название раздела на 320 обрезается до 2–3 символов: по §2.2 имя раздела —
  вторично («если есть место»), навигация/область/идентификация — постоянно.
  *(Обновлено §review-fix2: имя чата больше НЕ скрывается — приоритет
  изменён ревью, см. ниже.)*
- **Бейдж роли** ограничен `4.75rem` с ellipsis и полным значением в `title`
  (`admin`/`moderator`/`local_admin` помещаются целиком).

### Открытые пункты (не эта волна)

- `ui_asap8_w2_shell_e2e.py` — инструмент целиком описывает отменённую row B;
  пересборка под drawer — отдельная evidence-задача (не влияет на продукт).
- `ui_w4_ui_e2e.py`, `ui_speech_mobile_entry_e2e.py`, `ui_asap8_v6_d1213_e2e.py`
  падают на устаревших селекторах предыдущих волн (`[data-speech-card]`,
  `.intel-header .badge-btn`), а не на навигации; навигационные шаги в них уже
  переведены на drawer.
- EVOL-037 (глобальный поиск) и EVOL-COG (карта) — отдельные очереди.

## §review-fix2 — блокеры второго ревью ASAP-UI-02 §2 (31.10.2026)

Кандидат: `evol/impl` @ `64204306` + правки этого раздела (в рабочем дереве,
без коммита). Затронуто: `web/index.html`, `web/app.js`, `web/static/app.css`,
`tests/test_webapp_evol_w7_nav.py`, `tests/test_webapp_evol_w9_responsive.py`,
`tests/js/evol_w7_nav_test.js`, `tests/js/asap8_w2_shell_mobile_nav_test.js`,
`tools/ui_evol_w7_nav_e2e.py`. `services/**` и защищённая оптика — нулевой
дифф.

### F1 (BLOCKER) — имя раздела дублировалось на телефоне

* **Было (замер):** `.hub-head .hub-title` скрывался только внутри
  `@media (min-width: 768px)`, а ASAP-UI-02 §2.2 вернул название раздела в
  мобильную шапку — на 390 в `#/ai`, `#/modules`, `#/memory`, `#/access` имя
  стояло ДВАЖДЫ (шапка + заголовок хаба). Структурный тест этого не видел:
  он проверял только видимость шапки.
* **Стало:** одно правило верхнего уровня
  `.app-shell.ia-v2 .hub-head .hub-title { display: none; }` — имя раздела
  ровно один раз, в шапке, на любой ширине. Содержимое хаба (подзаголовок,
  поиск, фильтры, счётчики) не тронуто.
* **Проверки:** новый e2e-блок `title_once` в `tools/ui_evol_w7_nav_e2e.py`
  считает именно ВИДИМЫЕ вхождения (`display/visibility/rect`), а не только
  видимость шапки: 4 маршрута × 320/390 → `count = 1`;
  `TestAsapUi02Navigation::test_title_once_and_single_row` и
  `TestTopbar::test_no_duplicate_hub_title` дополнительно требуют, чтобы
  правило не было заперто в `@media`; JS-аналог — §4
  `asap8_w2_shell_mobile_nav_test.js`.

### F2 (BLOCKER) — на 320–419 выбранный чат не опознавался

* **Было:** `@media (max-width: 419px)` прятал `.scope-name` и аватар чата —
  в триггере оставался только бейдж «ЧАТ ▾».
* **Стало:** имя чата остаётся (ellipsis `clamp(2.5rem, 16vw, 5.5rem)`,
  при `≤359` — `2.8rem`), полное — в `title` и в раскрытой панели; место
  освобождено переносом ghost-⛶ в меню «⋯» (`data-fs-menu-item`,
  `moreMenuFullscreen()` → существующий `toggleFullscreen`, тот же `fsSlot`;
  выше 420 px пункт скрыт CSS, чтобы не дублировать ⛶ из шапки). Аватар чата
  уступает место имени; бейдж типа области `CHAT/GLOBAL` и ▾ не сжимаются.
* **Живой замер (Chromium, DPR 2):** 320 — имя `45 px` («Оче…»), бейдж «ЧАТ»
  `37 px`, аватар пользователя `24`, роль `45`, «⋯» `44`, горизонтального
  скролла нет; 390 — имя `62 px`. Пункт «На весь экран» в «⋯»: высота `44 px`,
  ширина `294/306 px`, внутри вьюпорта.

### F3 (BLOCKER) — drawer без ловушки Tab, Esc и Back

* **Было:** после 8-го пункта Tab уходил на BODY/кнопки шапки при открытой
  панели; `escClose()` про `drawerOpen` не знал (Esc не работал, если фокус уже
  вне панели); `goBack()` уводил маршрут под открытой панелью.
* **Стало:** `drawerOnKeydown($event)` — Tab/Shift+Tab замыкаются на
  первом/последнем фокусируемом пункте (тот же приём, что у «⋯»);
  `escClose()` получил ветку `if (this.drawerOpen) { this.closeDrawer(); return; }`
  (после «⋯», до остальных слоёв); `goBack()` первым делом закрывает панель.
  Закрытие, как и раньше, возвращает фокус в кнопку «Навигация».
* **Проверки:** e2e — 10 настоящих нажатий Tab: фокус прошёл 8 РАЗНЫХ пунктов
  и не вышел (`escaped: null`, `distinct: 8`; добавлена защита от «пустого»
  теста, если Tab не доставляется); Esc при фокусе ВНЕ панели
  (`[data-more-trigger]`) закрывает и возвращает фокус; `goBack()` закрывает
  панель, маршрут `#/oversight` не меняется. Живьём (Chromium): Tab с
  последнего пункта → первый, Shift+Tab с первого → последний
  (`defaultPrevented` + реальный `focus()`), Esc/Back — закрыто.

### Неблокирующее

* `.header-user-initial` раньше был оформлен ТОЛЬКО под `.shell-mobile` — на
  desktop/compact инициал выводился голым текстом. Правило поднято на уровень
  компонента (замер 1280: `24×24`, `radius 999px`, фон `.08`, рамка).

### Прогоны этого раздела

| команда | результат |
|---|---|
| `pytest tests/test_webapp_evol_w7_nav.py` | **33 passed** (было 30: +F2-тест, +F3-тест, +инициал; усилены F1-проверки) |
| `pytest tests/test_webapp_evol_w9_responsive.py` | **31 passed** (обновлён `test_header_keeps_required_controls` под перенос ⛶) |
| `pytest tests/test_webapp_evol_w10_sections.py` | **35 passed** |
| `node tests/js/evol_w7_nav_test.js` | `JS-UNIT-OK` (+§5b/5c/5d: ловушка, Esc/Back, пункт ⛶) |
| `node tests/js/asap8_w2_shell_mobile_nav_test.js` | `W2-SHELL-UNIT-OK` (+F1/F2/F3 пины) |
| `node tests/js/round1020_ui_test.js`, `round1020_ui_rework_test.js` | `JS-UNIT-OK` |
| `python tools/ui_evol_w7_nav_e2e.py` | **EVOL-W7-NAV OK**, инвентарь 19×6 = 114 ячеек, `hScroll 0 / offscreen 0 / clipped 0` |
| `python tools/ui_evol_w9_responsive_e2e.py` | **EVOL-W9-RESPONSIVE OK**, 19×8 = 152 ячейки, `hScroll 0 / offscreen 0 / clipped 0` |
| `pytest tests -k "webapp or … or hotfix"` | 2381 passed, 10 failed — **предсуществующие** (по HEAD: `>✕</button>` 6≠5, `data-speech-entry` 0, round1021/round1024-jargon/round1024-image + пять сервисных), к правкам `web/**` отношения не имеют |

Артефакты живого браузера: `evidence/w7-nav-live-fix2-320-header.png`,
`-390-header.png`, `-320-drawer.png`, `-390-drawer.png`, `-320-more.png`,
`-1280-header.png`; машинные факты — `evidence/w7-nav-probe.json`
(`title_once`, `mobile_scope`, `mobile_drawer_trap/closed/back`,
`mobile_fs_menu`).

Оговорка о инструменте: в Browser Use (реальный Chrome) синтетические
`Input.dispatchKeyEvent` для Tab/Esc в страницу не доставлялись, поэтому
поведение клавиатуры проверено (а) реальными DOM-событиями `KeyboardEvent`
через штатные обработчики и (б) Playwright с настоящим вводом (`Tab`/`Escape`),
где фокус действительно двигался между 8 пунктами.

## §review-fix3 — имя раздела читаемо на ЛЮБОЙ ширине (31.10.2026)

Микро-фикс по ревью: после скрытия `.hub-title` имя раздела живёт только в
шапке, и «показано один раз» недостаточно — оно должно быть ЧИТАЕМЫМ.
Замеры ревью в реальном Chromium: на 420/430 ширина `.header-title` = **0 px**,
на 460 — 10 px, на 500 — 43/52, на 320–375 видно 2–3 символа.

### Причина (не «мало места», а порядок сжатия)

1. `.header-title-wrap { min-width: 0 }` — резерва у имени раздела не было
   вообще, поэтому его ужимало первым.
2. `.header-scope-row` был `flex: 0 0 auto`, а `.scope-wrap` — тоже
   `0 0 auto`: ряд области держал свой max-content и не уступал ничего.
3. ghost-⛶ возвращался в шапку уже с 420 px (+44 px к строке) — ровно там,
   где имя раздела схлопывалось.

### Что сделано (`web/static/app.css`, один продуктовый файл)

* `--header-title-min: 3.5rem` (56 px при 14 px шрифте — целое «Модули», 52 px);
  `.header-title-wrap { min-width: var(--header-title-min) }`. Имя раздела
  больше не может стать нулевым; длинные имена — ellipsis (`.truncate`),
  а не исчезновение.
* Порядок жертв изменён: `.scope-wrap` — `flex: 0 1 auto; min-width:
  min-content` (ужимается ПЕРВЫМ, но не уже бейджа области и ▾),
  `.header-scope-row` — `flex: 0 1 auto` (ряд тоже уступает), а
  `.header-user` остаётся `0 0 auto` (идентификация не сжимается).
* ghost-⛶ уезжает в «⋯» до **519 px** включительно (`@media (max-width:
  519px)`): вход в полноэкранный режим остаётся РОВНО один (тот же `fsSlot`,
  тот же `toggleFullscreen` через `moreMenuFullscreen`).
* Бюджет строки добит только второстепенными деталями: ≤519 — короткий бейдж
  роли (3.4rem) и имя чата `clamp(2.5rem, 15vw, 5.5rem)`; ≤419 — инициал чата
  скрыт (он дублировал бейдж), бейдж роли 2.2rem, имя чата
  `clamp(2.2rem, 13vw, 6rem)`; ≤359 — плотнее внутренние отступы триггера и
  имя чата `clamp(2.2rem, 11vw, 2.5rem)`. Hit-цели (44×44) не тронуты.

### Замеры после фикса (реальный Chromium, `#/modules`, длинное имя чата)

| vw | было, `.header-title` | стало | имя чата | h-scroll |
|---|---|---|---|---|
| 320 | 34 (2–3 симв.) | **58** | 35 | нет |
| 360 | 33 | **63** | 47 | нет |
| 375 | 45 | **76** | 49 | нет |
| 390 | 58 | **89** | 51 | нет |
| 420 | **0** | **56** | 63 | нет |
| 430 | **0** | **58** | 65 | нет |
| 460 | **10** | **84** | 69 | нет |
| 500 | 43 | **118** | 75 | нет |
| 519 | 59 | **133** | 83 | нет |
| 520 (⛶ в шапке) | 60 | **60** | 83 | нет |

Проверено и на 19 маршрутах (инвентарь ниже) — ни горизонтального скролла,
ни выезда бейджа роли за вьюпорт: `offscreen 0`, `clipped 0`.

### Усиленные проверки

* `tools/ui_evol_w7_nav_e2e.py`: `title_once` теперь на **320/390/430/460/500**
  × 4 маршрута и проверяет не только «ровно одно видимое вхождение», но и
  `clientWidth >= min-width` резерва, `text-overflow: ellipsis` при обрезке и
  отсутствие h-скролла; добавлен `fs_entry` — вход в ⛶ ровно один
  (шапка ИЛИ «⋯», не оба и не ни одного).
* `tests/test_webapp_evol_w7_nav.py`: +`test_fullscreen_moves_to_more_until_520`,
  +`test_section_title_has_readable_reserve` (токен резерва, порядок ужимания,
  `min-width: min-content` у `.scope-wrap`); F2-тест больше не требует
  скрытия ⛶ именно в блоке ≤419.
* `tests/test_webapp_evol_w9_responsive.py`: окно секции 7000→9000 символов
  (правила выросли) и проверка переноса ⛶ под новый порог.
* `tests/js/asap8_w2_shell_mobile_nav_test.js`: порог ⛶ 419→519 и проверка
  нового порядка сжатия (ряд ужимается, идентификация пользователя — нет).

### Прогоны этого раздела

| команда | результат |
|---|---|
| `pytest tests/test_webapp_evol_w7_nav.py` | **35 passed** |
| `pytest tests/test_webapp_evol_w9_responsive.py`, `hotfix6`, `hotfix9` | **114 passed** |
| `pytest tests/test_webapp*.py` (54 файла) | 1281 passed, **5 failed — предсуществующие** (`>✕</button>` 6≠5, `break-all` в блоке логов, jargon round1024, круг round1021/1024-image; к шапке отношения не имеют) |
| `node tests/js/{evol_w7_nav,asap8_w2_shell_mobile_nav,round1020_ui_rework,round1025_scope_selector,round1025_shell_breakpoints,evol_w9_responsive,round1025_hotfix4_shell}_test.js` | все `…-OK` |
| `python tools/ui_evol_w7_nav_e2e.py` | **EVOL-W7-NAV OK**, 19×6 = 114 ячеек, `hScroll 0 / offscreen 0 / clipped 0`, `title_once` 20/20, `fs_entry` 5/5 |
| `python tools/ui_evol_w9_responsive_e2e.py` | **EVOL-W9-RESPONSIVE OK**, 19×8 = 152 ячейки, все нули |

Живая проверка (реальный Chrome, `stand_server.py` со стабами API и TMA в
`<head>`): 320 — «Модули» видно целиком, чат «Оч…/ЧАТ», роль «g…», «⋯» в
экране; 420 и 460 — «Модули» целиком, чат «Очень …/Очень д…», роль, «⋯»;
⛶ в шапке отсутствует до 519 включительно (уезжает в «⋯»), ниже 768 ничего не
выезжает за вьюпорт. Артефакты: `evidence/w7-nav-fix3-hdr-{320,420,430,460,
500,520}.png`, `evidence/w7-nav-fix3-title-widths.json`,
`evidence/w7-nav-probe.json` (`title_once`, `fs_entry`).

### Остаточные риски и оговорки

* В живом Chrome вне Telegram `fsSlot = hidden` (нет API полноэкранного
  режима), поэтому ⛶ там не рендерится вовсе — единственность входа в ⛶
  проверена Playwright-прогоном с TMA-стабом (кнопка есть, но скрыта ≤519).
* Заголовок с сохранением (`header-save-chip`) — переходное состояние
  (появляется только при dirty/saving/failed), в матрицу не входит: на 320 px
  при одновременно видимом чипе строка становится теснее ещё на ~46 px.
  Отдельным пунктом не чинилось, чтобы не уменьшать резерв имени раздела
  ради переходного индикатора; при появлении такого состояния на 320 px
  приоритет отдаётся имени раздела и идентификации чата.
* `pytest tests/test_webapp*.py` прогоняет `tests/test_webapp_evol_w10_sections.py`,
  который перегенерирует `evidence/w10-sec-*.png`: 20 файлов помечены
  изменёнными в рабочем дереве (содержимое — тот же штатный прогон, байты
  другие). Исходные байты в рабочем дереве не восстанавливались (`git
  checkout` запрещён в этой сессии) — это отмечается для релизного владельца.
