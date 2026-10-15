# W2-SHELL — отчёт лейна (U01 мобильная шапка + U02 мобильные субвкладки Аналитики)

Лейн: **W2-L1 SHELL** · База: HEAD `f1418d7` · Статус: реализация завершена, проверена
автотестами + Playwright + Browser Use. НЕ коммитилось (по брифу). Merge — №1 в порядке
w2-contract §1.1 (FULLSCREEN и GLASS ребейзятся на эту версию hot-spot'ов).

## 1. Что реализовано

### U01 — мобильная шапка <768 (REQ-U01, U01.1–U01.5, REQ-U01-BASE)

- **Row B = ровно 4 сегмента** «Статус / Аналитика / Модули / Ещё ▾» в этом порядке,
  равные доли (`flex: 1 1 0`), без горизонтального скролла, высота 47.2px
  (portrait) / 35.2px (landscape). `mobileTopnavItems` больше НЕ отдаёт весь `navItems` —
  фиксированный список с тем же RBAC-фильтром; скрытые права не показываются.
- **Меню «Ещё»** (`mobileMoreItems`) — popover/sheet **поверх контента** (не ряд шапки):
  overlay + панель под шапкой (позиционирование от измеренной `--header-h`), solid-фон
  (`--surface-1`, SHELL-baseline читаемости; GLASS перетюсит через `data-glass="c"`),
  z-index 55/56 (выше шапки 40 и drawer'а, ниже модалок 59+), внутренний скролл
  (`max-height` от `100dvh`), `role="menu"/menuitem`, `aria-expanded`, `aria-current="page"`.
  Клавиатура: Esc (локально + guard первым в глобальном `escClose`), Tab-trap.
  Outside click по backdrop. Focus management: фокус в панель при открытии, **возврат в
  триггер при закрытии** (Esc/outside/pick). Body-scroll-lock без прыжков: класс
  `more-menu-open` на `.app-shell` → `main.scroll-area { overflow: hidden }`.
  Deep links: пункты идут через `shellNavTo` (hash-роутинг). Пункт меню закрывает меню.
- **Триггер «Ещё • …»**: активный раздел из меню отражается в триггере
  (`moreMenuTriggerLabel`) + подсветка (`moreMenuActive`).
- **Row A**: [←/AdminBot] — один слот (бренд только когда ← скрыта), компактный
  chat-селектор (flex+`clamp`, ellipsis, полное имя в `title`/`aria-label`), профиль
  компактно (аватар; имя/роль — в «Ещё»), `⛶` остаётся в правом краю row A (узел —
  собственность FULLSCREEN, SHELL его не стилизует). **`ID`-чип скрыт на mobile**
  (`.scope-tech`), ID области доступен в профиле меню «Ещё». Заголовок/крошки из
  мобильной шапки убраны (`header-title-wrap { display: none }`) — нет второго
  заголовка и третьей строки; контент начинается сразу под row B.
- Геометрия: явный `order` у flex-детей шапки на mobile (row A = 0/1/3/5, row B = 10) —
  без этого `flex-wrap` упаковывал topnav раньше scope-row и шапка разваливалась на
  3–4 линии (найдено и исправлено в ходе measured-проверки).
- **Нижний navbar НЕ возвращён**; desktop sidebar не тронута (desktop-проверки в e2e).
- Маршрутная целостность: `applyRoute` закрывает навигационные оверлеи при ЛЮБОЙ смене
  маршрута (назад/вперёд, hub-карточки — мимо `shellNavTo`) — дефект найден визуальной
  инспекцией, исправлен по root-cause.

### U02 — мобильные субвкладки Аналитики (REQ-U02, U02.1–U02.3)

- `<768`: лента обрезанных pills скрыта (`oversight-tabs__row { display: none }`),
  показан **один полноширинный dropdown** «Раздел: [текущая ▾]»
  (`oversight-mobile-dd`), полный список **ровно 7** вкладок: Обзор, Процессы, Запуски,
  Инциденты, Память и интеллект, Модели и расходы, Саммари. **«Логи» в списке НЕТ**
  (якорь-скролл — не режим; `oversightMobileTabs` фильтрует).
- Длинные метки — до 2 строк в меню (`white-space: normal` + line-clamp 2), на триггере
  ellipsis; `role="listbox"/option`, `aria-selected`; Esc + возврат фокуса в триггер;
  опции гарантированно в вьюпорте (проверено на 320–430).
- Выбор идёт **через существующий `oversightSetTab`** → `oversightTab`, hash
  (`?tab=…`/`?view=…`), deep-link, lazy-loading, фильтры и инциденты не тронуты
  (e2e: `tab=memory`, deep-link `?tab=summary`, `?view=runs&status=failed`, возврат на
  Обзор — всё живо).
- **Desktop ≥768 не изменён**: dropdown скрыт, горизонтальная tabs-панель работает
  (desktop-снимки + ассерты). Карточка при открытом dropdown поднимается над соседями
  (`oversight-dd-open`, grid-item z-index).

## 2. Измеренные числа (actual `getBoundingClientRect`, не media-query)

| Сценарий | header (полная шапка) | row B | scrollWidth | Бюджет |
|---|---|---|---|---|
| 320×700 портрет | **116.2** | 47.2 | 320 ≤ 320 ✓ | ≤124 ✓ |
| 360×780 портрет | **116.2** | 47.2 | 360 ≤ 360 ✓ | ✓ |
| 390×844 портрет | **116.2** | 47.2 | 390 ≤ 390 ✓ | ✓ |
| 430×932 портрет | **116.2** | 47.2 | 430 ≤ 430 ✓ | ✓ |
| 667×375 landscape | **93.8** | 35.2 (компакт) | 667 ≤ 667 ✓ | ✓ |
| 200% zoom (320 CSS px @2x) + длинный русский title | **116.2** | 47.2 | 320 ≤ 320 ✓ | ✓ |
| TMA resize collapsed 390×500 / expanded 844 | 116.2 / 116.2 | 47.2 | без overflow | ✓ |
| **before (baseline f1418d7)** 390 / 320 | **225.6** | 45.6, **scrollW 455 > 358/288** (лента 8 пунктов за экраном) | — | нарушение 225.6 > 124 |

Row A ≈ 59px (в границах ~40–48 контентной зоны + safe-area паддинги), row B 47.2
(цель ~42–48), суммарно 116.2 ≤ 124. Все 4 сегмента видны целиком на каждой ширине
(x ≥ 0, right ≤ innerWidth), последний пункт («Ещё») доступен; меню не обрезается
(panel rect в вьюпорте на 320). Полные пробы: `w2-evidence-shell/w2_shell_e2e.json`
(after, 129/129) и `w2_shell_e2e_before.json` (before).

## 3. Тесты

### Новые
- `tests/js/asap8_w2_shell_mobile_nav_test.js` — **TEST-LIFECYCLE: CONTRACT
  owner=REQ-U01/U02**: порядок row B, состав «Ещё», RBAC, «Ещё • …», отсутствие
  bottom-nav/ленты, popover-контракт (menu/aria/Esc/outside/focus/scroll-lock/z-index),
  ID вне шапки, U02 (7 без «Логи», ARIA, oversightSetTab, desktop-скрытие). → `W2-SHELL-UNIT-OK`.
- `tools/ui_asap8_w2_shell_e2e.py` — Playwright-матрица по ТЗ «Обязательные UI-тесты»:
  320/360/390/430 портрет, 667×375 landscape, 200% zoom (320@2x), TMA resize
  expanded/collapsed, длинный русский chat title; SDK — **route-mock**
  `**/static/vendor/telegram-web-app.js` (w2-contract §4.2.1, не addInitScript);
  ассерты: 4 сегмента целиком, последний доступен, меню не обрезано, Esc/outside/
  focus-return/scroll-lock, deep-link «ИИ» → `#/ai` + триггер «Ещё • ИИ»,
  U02 (полный список/без Логов/ARIA/hash/deep-link/фильтры/возврат), desktop-инварианты,
  `scrollWidth ≤ innerWidth`, console без ошибок. → **W2-SHELL-E2E-OK (129/129)**.
- before/after одного маршрута: `w2-evidence-shell/before_u01_status_390.png` vs
  `after_u01_status_390.png` (+320, landscape, zoom200, oversight) — baseline-корень
  `OPENCODE_WORKFLOW_SCRATCH/w2-before-f1418d7` (git worktree f1418d7), тот же порт/стабы.
- Browser Use (реальный рендер, Chrome, CDP-эмуляция 390×844@2x и 1280×800):
  `bu_status_390.png`, `bu_menu_390.png` (solid-панель, 5 RBAC-пунктов, профиль
  роль+ID), `bu_oversight_dd_390.png` (7 опций, активная подсвечена),
  `bu_oversight_desktop_1280.png` (sidebar+табы не изменены). Esc/focus-return и
  закрытие при смене маршрута подтверждены в реальном браузере.

### Замены маркеров старого канона (w2-contract §1.2, не молча)
| Тест | Старый маркер (D13-канон) | Новый (U01/U02) |
|---|---|---|
| `round1025_ia_routing_test.js` | mobileTopnavItems = весь navItems; `mobileMoreItems` undefined | row B = [status,oversight,modules]; `mobileMoreItems` = остальное; «Ещё • …»; RBAC |
| `routing_test.js` | то же | то же + покрытие реестра row B+«Ещё» |
| `asap8_d1213_save_contract_test.js` | `mobile-topnav scroll-thin`; `mobileMoreItems` undefined | `mobile-topnav` без scroll-thin; more-menu popover; `mobileMoreItems` определён |
| `asap42_step2c2_layout_test.js` | `mobile-topnav scroll-thin` | `mobile-topnav` (4+Ещё) |
| `round1025_shell_breakpoints_test.js` | `scroll-thin` маркер | новый маркер + анти-маркер ленты |
| `round1025_hotfix4_shell_test.js` | `scroll-thin` маркер | без scroll-thin |
| `asap6_wave2_ux_tabs_test.js` | `.oversight-tabs__row` overflow-x:auto на mobile | mobile-dropdown + скрытие pills <768 + desktop ≥768 |

Сохранены без изменений: отсутствие `.bottom-nav`/`.more-sheet`/`moreOpen`, landscape-
правило, reduced-motion, touch ≥44px.

## 4. Write-scope и чужие секции

Затронуто ровно по w2-contract §1.2: `web/app.js` (nav-секции: data `moreMenuOpen`/
`oversightMobileOpen`; computeds `mobileTopnavItems/mobileMoreItems/moreMenuTriggerLabel/
moreMenuActive/oversightMobileTabs/oversightTabLabel`; методы «Ещё»/U02; guard в
`escClose`; 2 строки закрытия оверлеев в `applyRoute` — root-cause для U01.4),
`web/index.html` (класс-binding элемент `more-menu-open` на :66, mobile-brand, row B,
popover после `</header>`, oversight-mobile-dd; сохранены чужие `fs-slot`/
`fullscreen-policy`/`glass-probe`/`data-glass="b"` узлы), `web/static/app.css`
(`.mobile-topnav` блок, oversight-mobile-правила, append-only блок `/* ═══ W2-SHELL ═══`
в конце файла). Геометрия `header.header-sticky` — только мобильные переопределения;
материал/glass-токены не тронуты (property-split HS-3 соблюдён).
**Не тронуто**: services/**, config/**, telegram-init.js, fullscreen-policy.js,
glass-probe.js, desktop sidebar, polygon-background.js (diff vs f1418d7 — 0 строк),
aurora-разметка.

## 5. Production background preservation (замечание владельца, доставленное в сессию)

Корректирующее требование о заморозке production background адресовано лейну
**W2-GLASS** (сессия ses_ec3252142ffe3X7SX42B54xn4U) и поступило в сессию W2-SHELL.
К своей зоне отношения не имеет, но SHELL проверил и подтверждает: **полигональный фон
не тронут** — `git diff f1418d7 -- web/static/polygon-background.js` пуст; в
добавленных строках SHELL (87 маркерных) нет ни одного фонового маркера
(aurora/polygon/feTurbulence/feImage/--glass-bg/--shell-bg/lg-lens); aurora-разметка
index.html в дифе отсутствует. Ограничение передано в отчёте для доставки владельцу
GLASS-лейна.

## 6. Инциденты и находки

- **Clobbering общих файлов параллельным лейном**: `web/index.html` был перезаписан
  чужой версией БЕЗ секций SHELL (при живых `fs-slot`/`fullscreen-policy`/`glass-probe`).
  По w2-contract §1.4 (HS-1: SHELL — первый владелец, конфликтные версии решаются
  в пользу SHELL) секции восстановлены поверх текущей базы с сохранением всех чужих
  узлов; целостность проверена маркерами + полным прогоном. Orchestrator: обсудить с
  FS/GLASS дисциплину rebase до merge-окна.
- `round1025_hotfix6_lens_heartbeat_shell_test.js` — падает на чистом HEAD f1418d7
  (воспроизведено через git stash) — **pre-existing, вне лейна**.
- `round1025_design_tokens_test.js` — падает из-за незавершённых правок
  **W2-FULLSCREEN** в общем `web/app.js` (их маркеры `W2-FULLSCREEN` в toggleFullscreen;
  старый тест ждёт legacy-инверсию, которую U07.1 заменяет) — обновление теста =
  ответственность FS-лейна в их отчёте.
- Мелочь: пустой глиф у несуществующей иконки — «Ещё» использует `grid_view` из
  существующей карты ICONS.

## 7. PENDING-live (для Wave 4 / V06)

- Живой Telegram Android/iOS WebView: safe-area с реальными инсетами (probe: 0),
  нативные зоны ⋮/✕ рядом с inline ⛶, поведение при реальном viewportChanged.
- VERIFIED_LIVE U01/U02 в реальном TMA (mock-only ≠ verified по V06) — не заявляется.
- `data-glass="c"` материал панелей — финальный тюнинг за GLASS-лейном (SHELL-baseline
  solid уже читаем).

## 8. Артефакты

- Отчёт: `plans/features/asap8-v6-3-live-correction/w2-reports/W2-SHELL.md`
- Evidence: `plans/features/asap8-v6-3-live-correction/w2-evidence-shell/`
  (before/after скриншоты, `w2_shell_e2e.json`, `w2_shell_e2e_before.json`, bu-кадры)
- Изменённые файлы: `web/app.js`, `web/index.html`, `web/static/app.css`;
  тесты: 1 новый + 6 обновлённых маркеров + `tools/ui_asap8_w2_shell_e2e.py`.
- Кандидат: рабочее дерево (без коммита) на базе `f1418d7` + W2-FULLSCREEN/W2-GLASS
  параллельные правки в общем worktree.
