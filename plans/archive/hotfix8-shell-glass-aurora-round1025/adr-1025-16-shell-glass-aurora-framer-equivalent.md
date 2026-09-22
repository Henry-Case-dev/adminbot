# ADR-1025-16 — Эквивалент Framer Motion на Vue-стеке, серо-графитовый shell v3 (§4), CSS-aurora/mesh вместо conic-wash

- **Статус:** Proposed → **Approved** (Step 2 @Architect, 22.09.2026; human gate отключён — решения приняты и обоснованы).
- **Дата:** 2026-09-22
- **Раунд:** 10.25, внеплановый хотфикс-8 `hotfix8-shell-glass-aurora-round1025` (T-2745…T-2789), Волна 1.7.
- **Связано:** `spec.md` этой папки; UPD2 `plans/current_task.md:6156-6496`; `plans/ARCHITECTURE.md` §57/§58/§59/§60/§61; **ADR-1025-13** (D2/D3/D4 — AMEND), **ADR-1025-9** (D2/D3 — уточнение/REVISE), ADR-1025-12 (D1/D3/D5 — сохранить), ADR-1024-24 (fullscreen-sync — сохранить), ADR-1016-2 / ADR-1024-13 (CSP/zero-build/`ui_flags`), ADR-1025-2 (F0 `persistItems`).
- **Затрагивает:** `web/static/app.css`, `web/index.html`, `web/app.js`, `web/static/telegram-init.js`, `config/settings.py` (env-only `ClassVar` + `APP_VERSION`), `web/api/routes.py` (аддитивно `ui_flags`), `tools/ui_round1025_matrix.py`, тесты (`tests/**`, `tests/js/**`), отчёты `plans/reports/round1025_hotfix8_*.md`.

## Контекст

Живая приёмка после hotfix7/§59 выявила, что shell и фон не соответствуют ТЗ (UPD2 §1):

- **Shell слился с карточками.** Панели несут `data-glass="a"` (`index.html:55` sidebar, `:92` header, `:3789` drawer, `:3824` bottom-nav, `:3840` more-sheet). Правило `[data-glass="a"]::before` (`app.css:1142-1157`) рисует **цветную** teal/blue/violet линзу-реплику (`linear-gradient(var(--grad-a),--grad-b,--grad-c)`, opacity .14) с radial-mask — это и есть «дешёвый ореол/фиолетовая аура» по краям shell. Плюс завышенные `--shell-border-color .20` и `--shell-highlight .18` (`:81,:83`) и мягкий `--glass-shadow` дают ощущение «карточка получила blur».
- **Значения shell ≠ §4.** `--shell-bg rgba(33,37,45,.62)`, `saturate(120%)`, shadow `0 12px 30px -18px` — расходятся с целевыми §4 (`rgba(24,28,38,.72)`/mobile .78, `saturate(115%)`, `0 8px 24px rgba(0,0,0,.18)`).
- **Фон мёртв.** Один `body::before` conic (`:163-177`), `--grad-speed 75s`, opacity `.30` — визуально «заморожен»; blob/morph/grain отсутствуют (§1.3, §6).
- **Стек-конфликт §2.** UPD2 просит «Framer Motion / React / текущий стек». Проект — **Vue 3 global zero-build + CSP `script-src 'self'`** (ADR-1016-2/ADR-1024-13). Framer Motion — React-библиотека с npm-сборкой → подключить нельзя без нарушения CSP и смены стека.

**Инварианты:** Δ DDL = 0, Δ каталога = 0, CSP/zero-build, запрет WebGL и новых библиотек, env-only UI-флаги, нативные кнопки Telegram CSS не двигать, IA F1 / store F4 §37–§42 / `persistItems` F0 / SaveBar F9 / `computeBottomOffset`+hotfix4 / fullscreen-sync ADR-1024-24 — сохранить; R17/R18.

## Решение

### D1. Framer Motion — объективный отказ; эквивалент на текущем стеке

UPD2 §2 просит Framer Motion и React. **Прямое подключение невозможно** и фиксируется как объективное ограничение, а не отказ от задачи: Framer Motion — React-only и распространяется как npm-пакет, требующий сборки/bundler; React меняет стек проекта (Vue 3 global zero-build); внешний CDN и inline-скрипты запрещены CSP `script-src 'self'` (ADR-1016-2/ADR-1024-13). Всё, что просится «для анимации и микродвижений», реализуется эквивалентным набором:

1. **CSS animations/transitions (основное)** — `@keyframes`, `transition`, easing, `transform`/`opacity` (композиторный путь). Покрывает микродвижения shell, hover/press, морфинг форм.
2. **Web Animations API (WAAPI)** — для динамических/прерываемых последовательностей, где CSS-классов мало; тот же движок, ноль зависимостей.
3. **SVG-фильтры** — `feGaussianBlur`/`feTurbulence`/`feDisplacementMap` (движок уже есть: inline `#lg-lens`, `index.html:37`) для преломления/шума.
4. **Canvas 2D + rAF** — только если CSS объективно недостаточен (фон/преломление), один цикл, пауза при `document.hidden` и `prefers-reduced-motion`.

Spring/инерция Framer эмулируются CSS `cubic-bezier`/WAAPI-`easing`. WebGL и сторонние библиотеки запрещены.

### D2. Shell v3: отдельные токены §4 + нейтральный графитовый glass без цветной линзы

- **Токены (§4, `:root`):** `--shell-bg rgba(24,28,38,0.72)` (mobile ≤767 — `rgba(24,28,38,0.78)`), `--shell-border-color rgba(255,255,255,0.08)`, `--shell-highlight rgba(255,255,255,0.06)`, `--shell-shadow 0 8px 24px rgba(0,0,0,0.18)`, `--shell-blur blur(18px) saturate(115%)` (+`-webkit-`). `--shell-*` — **отдельные** от `--glass-*`; карточные токены/палитра §8 не меняются.
- **Снятие ореола:** панели (sidebar/header/drawer/bottom-nav/more-sheet) переводятся с `data-glass="a"` на **`data-glass="shell"`**. Цветная линза `[data-glass="a"]::before` на них **отключается** (её носителями остаются только контентные allow-узлы: `.card[data-glass="a"]`, cognition-graph и т.п.). Вводится нейтральный рецепт: `--shell-bg` + `--shell-blur` + тонкая обводка + мягкий inner highlight (`inset 0 1px 0`) + `--shell-specular` + `--shell-texture` + **бесцветный** sheen `[data-glass="shell"]::after` (переиспользует `filter: var(--glass-displace)`, opacity ≤ .05, `pointer-events:none`, под контентом, без radial-цветной маски). **Никакого внешнего glow/виньетки.**
- **Побочный эффект:** shell выходит из перф-бюджета `UI_LENS_MAX_NODES` (работает по `[data-glass="a"]`) → бюджет линзы целиком достаётся контенту.
- **Глубина:** фон → карточки (`--glass-bg`, `--card-shadow`) → shell (плотнее/серее, `--shell-bg`) → модалки (плотнее). Shell не окрашивается в сине-фиолетовый тон карточек. AA ≥ 4.5:1 пересчитывается.
- **Радиусы:** sidebar `0`/большой внешний; topbar-элементы/pill/selector/floating `14–18px`; mobile shell blocks `16–20px`.
- **Флаг:** `UI_SHELL_V3` (default ON). OFF → значения `--shell-*` hotfix7 (мягкий откат значений); цветная линза **не возвращается** — её снятие является частью исправления, а не настройкой.

### D3. Aurora/mesh background в рамках CSP (REVISE фона §10 F2)

- **Механика — CSS-first:** 3–5 больших **размытых blob** (radial-gradient + blur) в отдельном заднем слое (`pointer-events:none`, ниже `#app`), анимируются композиторно (`transform`/`opacity` + мягкий morph формы), разные длительности и отрицательные `animation-delay` (разные фазы). **Без WebGL.**
- **Canvas 2D+rAF — только фолбэк** при доказанной нехватке CSS на реальном WebView (решение и замер — `evidence.md`; один rAF, DPR cap ≤2, пауза hidden).
- **Палитра §10:** teal/violet/blue/indigo (`--grad-a #42D6C4`, `--grad-b #77A8FF`, `--grad-c #A78BFA`, производные глубокий teal/индиго), **без оранжевого**; слабый grain.
- **Скорость:** «медленно, но заметно» — не «заморожено» и не «психоделика»; без агрессивной пульсации.
- **Пауза/доступность:** существующий `html.lg-bg-paused` (`app.js:10029-10033`, единый `visibilitychange`-обработчик, без второго) + `prefers-reduced-motion` → статичное атмосферное состояние.
- **Разделение:** фон — отдельный слой, не создаёт ореол вокруг shell и не ухудшает контраст текста.
- **Сохранение:** `@property --grad-angle` + `grad-spin`/`grad-drift` **остаются** для `.grad-band`/`.btn-accent`/`.tab-btn.active` (не ломать маркер-механику ADR-1025-9 D3).
- **Флаг:** `UI_AURORA_BG_ENABLED` (default ON). OFF → прежний conic page-wash `body::before`.

### D4. Геометрия / mobile / fullscreen / SaveBar (UPD2 §1.1, §5.3–§5.5, §7)

- **Desktop:** sidebar **208–224px** (сужение с 232px, `padding-left` согласован); gap header↔первая карточка **16–20px** (через `--header-h`/`scroll-padding-top`/отступ первой карточки); floating-контролы не конфликтуют с контентом.
- **Mobile:** порядок header → строка селектор/профиль → контент → bottom nav → safe-area-bottom; **без горизонтальной прокрутки**; карточки с breathing space.
- **Fullscreen:** никакие блоки не исчезают; selector/cards/bottom-nav сохраняют геометрию; Telegram WebView sizing проверяется live; единый источник высоты `--shell-h` (ADR-1025-13 D1) не дублируется.
- **SaveBar:** не перекрывает инпуты, не конфликтует с внутренним скроллом (сохранить `scroll-padding-bottom`/`.sticky-spacer`/`:has()`-логику `app.css:1283-1337`); CTA/Cancel не ломают layout на малой высоте/клавиатуре; логика F9 не дублируется.
- **Сохранить:** `computeBottomOffset`/hotfix4 (ADR-1025-12 D3), fullscreen-sync ADR-1024-24, IA F1, F5 §61, store F4 §37–§42.

### D5. Границы displacement, инварианты, флаги

- **SVG displacement:** разрешён на декоративных слоях (content-линза `data-glass="a"` + бесцветный shell-sheen `[data-glass="shell"]::after`) — под контентом, `pointer-events:none`; **запрещён** на тексте/интерактиве, `backdrop-filter: url()` запрещён; deny-list tier C не расширяется.
- **Инварианты:** Δ DDL = 0; Δ каталога = 0; CSP/zero-build; без WebGL/новых библиотек/CDN/Framer Motion/React; не редизайн; F1/F2/F3/F4/F5, F0 `persistItems`, F9 SaveBar, нативные кнопки/`--header-h`, палитра §8 — не ломать; R17/R18.
- **Флаги (env-only `ClassVar`, default ON, Δ каталога = 0):** `UI_SHELL_V3`, `UI_AURORA_BG_ENABLED` (+ унаследованные `UI_SHELL_GLASS_V2`, `UI_SHELL_LAYOUT_V2`, hotfix6/7-флаги).

## SUPERSEDE / AMEND

| Ранее | Действие | Что именно / почему |
|---|---|---|
| **ADR-1025-13 D3** (shell-токены `.62/.90/.20/.18`, `saturate(120%)`, `--shell-shadow 0 12px 30px -18px`) | **AMEND → D2** | Значения → §4 (`rgba(24,28,38,.72)`/mobile .78, border .08, highlight .06, shadow `0 8px 24px rgba(0,0,0,.18)`, `saturate(115%)`); карточные `--glass-*`/§8 не меняются |
| **ADR-1025-13 D3** (цветная линза `[data-glass="a"]` на панелях = ореол) | **AMEND/REVISE → D2** | Панели → `data-glass="shell"`; цветная линза/ореол сняты; нейтральный бесцветный sheen; прочие носители `data-glass="a"` не затронуты |
| **ADR-1025-13 D4** (`UI_SHELL_LAYOUT_V2`, выравнивание header/mobile) | **AMEND → D4** | Сохраняется; уточнены sidebar 208–224px, gap 16–20px, mobile-порядок, SaveBar↔скролл |
| **ADR-1025-9 D2** (значения токенов/уровни glass) | **Уточнение → D2** | Добавлен shell-v3-рецепт; карточный `--glass-bg`, уровни A/B/C, deny-list — без изменений |
| **ADR-1025-9 D3 + фон §10 (F2)** (conic page-wash `body::before`) | **REVISE → D3** | Page-wash заменяется aurora/mesh; `@property --grad-angle`+`grad-spin`/`grad-drift` **сохраняются** для `.grad-band`/кнопок |
| **ADR-1025-12 D1** (foreground-линза/feature-detect) | **НЕ отменяется** | Механизм преломления/`UI_LENS_MAX_NODES`/tier-лестница; shell просто выходит из бюджета линзы |
| **ADR-1025-12 D3** (`computeBottomOffset` = max) | **НЕ отменяется** | Нижняя панель/шторка — прежняя компенсация |
| **ADR-1025-12 D5** (нативные кнопки, `--header-h`, fullscreen) | **НЕ отменяется** | Компоновка шапки/резерв высоты сохраняются |
| **ADR-1024-24** (fullscreen-sync) | **НЕ отменяется** | Источник истины — TMA |
| **ADR-1025-8/hotfix4, ADR-1025-10/F3, ADR-1025-1/F1, F0 `persistItems`, F4 §37–§42, F5 §61** | **НЕ отменяются** | Порядок навигации, safe-area, IA, write-path, store-контракт, workspace |

## Последствия

**Positive:** shell становится визуально отдельным серо-графитовым стеклянным слоем (не «ещё одна карточка») без ореола/виньетки; точные значения §4; живой атмосферный фон в палитре §8/§10; стабильная геометрия desktop/mobile/fullscreen и разведённые SaveBar↔скролл; два независимых env-отката; инварианты, IA и прецеденты (CSP/zero-build/no-WebGL) не нарушены; shell освобождает бюджет перф-линзы.

**Negative/издержки:** реальная геометрия fullscreen и FPS blob/displacement на слабом WebView **не воспроизводимы headless** — обязателен live-гейт владельца (T-2776); ручная пересборка AA-таблицы; «премиальность» оценивает владелец (риск приёмки); визуальные правки требуют атомарного обновления маркеров тестов.

**Ограничения:** Δ DDL = 0, Δ каталога = 0; `services/**`/`web/app.py` не трогаются; без новых зависимостей/WebGL/data-URI/внешних ассетов; `current_task.md` не изменяется (R18).

## Альтернативы

| Альтернатива | Почему отклонена |
|---|---|
| Подключить Framer Motion (+React) | Нарушает CSP `script-src 'self'`, ломает zero-build и меняет стек проекта; UPD2 §2 сам оговаривает «если библиотека подходит стеку» |
| Импортировать Framer/иной аниматор с CDN | Прямо запрещено CSP/инвариантом |
| Оставить цветную линзу, лишь ослабить alpha | Не устраняет корень (§1.2 «дешёвый ореол/фиолетовая аура») |
| Убрать `::before` только сужением селектора, не меняя атрибут | Shell остаётся в `data-glass="a"`-бюджете и наследует чужой контракт; явный `data-glass="shell"` чище |
| Вернуть shell непрозрачным (tier C) | Убирает стекло, требуемое §3/§4 |
| WebGL/шейдеры для «оптического» стекла/фона | Запрещено инвариантом; CSS/Canvas 2D достаточно |
| Canvas 2D+rAF как основная механика фона | Дороже CSS по CPU/батарее на слабом WebView; оставлен фолбэком |
| Оставить conic-wash, лишь ускорить | UPD2 §6 прямо требует aurora/mesh вместо «обычного переливающегося градиента» |
| Ввести каталоговые тумблеры shell/фона | Δ каталога ≠ 0 — нарушение; env-only `ClassVar` сохраняет нулевую дельту |
| Обойтись без флагов | Два самых рискованных (не воспроизводимых headless) изменения остались бы без мягкого отката |
| Фиксировать высоту shell и в normal-режиме | Ломает нативный скролл и IA (прецедент F1) |

## Верификация

- **Playwright (5 режимов + 10 вьюпортов §71):** computed `background-color`/`border-color`/`box-shadow` shell **≠** карточных; на shell **нет** цветного `::before`-градиента; на shell `backdrop-filter` содержит `blur(18px) saturate(115%)`; aurora-слой присутствует и анимируется (не static), при `document.hidden` — `lg-bg-paused`, при reduced-motion — `animation: none`; `scrollWidth ≤ innerWidth+1`; `rect.bottom ≤ innerHeight+1`; gap header↔первая карточка 16–20px; sidebar 208–224px; hit-area bottom-nav ≥44×44.
- **JS/node-юниты:** `node --check`; маркеры новых shell/animation-токенов; сохранность `computeBottomOffset`/fullscreen-sync/`reconcileLiquidGlass`-семантики (shell вынесен из `[data-glass="a"]`).
- **AA:** таблица «пара → эффективный фон (худшая фаза aurora) → ratio → PASS/FAIL».
- **Инварианты:** Δ DDL = 0; Δ каталога = 0 (459/98/96/21/418); CSP/zero-build; отсутствие WebGL/Framer Motion/новых библиотек; нативные кнопки/`--header-h`; IA/маршруты; `persistItems`; store F4 §37–§42; `git diff --check`.
- **Только реальный Telegram WebView (владелец, T-2776):** mobile fullscreen — shell серый/отделён, ореола нет, стекло subtle, фон живой, ничего не съезжает, bottom nav/SaveBar не перекрывают контент, FPS blob.
- **Не воспроизводимо headless (зафиксировать):** точное поведение fullscreen в TMA, реальные `safeAreaInset`/`contentSafeAreaInset`, геометрия нативных кнопок, устройство-зависимый FPS.

## Откат

- **Hard:** тег `pre-round1025-hotfix8` (T-2745) + `git revert` коммитов пакета + возврат `APP_VERSION`/`?v=`.
- **Soft (env-only, без редеплоя):** `UI_SHELL_V3=false` (значения `--shell-*` → hotfix7); `UI_AURORA_BG_ENABLED=false` (aurora → прежний conic page-wash); наследуемые `UI_SHELL_GLASS_V2`/`UI_SHELL_LAYOUT_V2`/hotfix6-флаги остаются рабочими.
- Бэкапы/теги/`stash@{0}` не удалять (R18).
