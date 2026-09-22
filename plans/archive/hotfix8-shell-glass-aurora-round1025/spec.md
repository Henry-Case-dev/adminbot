# spec.md — HOTFIX8 `hotfix8-shell-glass-aurora-round1025` (Step 2 @Architect)

> **ТЗ:** UPD2 «СРОЧНОЕ УТОЧНЕНИЕ ПО SHELL / LIQUID GLASS / BACKGROUND» в `plans/current_task.md`, **строки 6156–6496** (прочитан дословно; сам `current_task.md` **не изменялся**, R18).
> **Тип:** UI + shell/glass/aurora (web, Vue 3 global zero-build). **Приоритет:** P0, выше F6.
> **Задачи:** T-2745…T-2789 (`tasks.md`). **ADR:** `adr-1025-16-shell-glass-aurora-framer-equivalent.md`.
> **Baseline:** HEAD `a1e6db3`, `APP_VERSION` 2.58.10, JS 32 файла, каталог 459/98/96/21/418, SQLite v12 (из `plans/workflow_state.md` / `plans/MEMORY.md`, Step 0 @Memory).
> **Статус:** Proposed (Step 2). Human gate отключён (UPD2 §10).

## 1. Scope

Косметически **не** ограниченная доводка: три объективных дефекта текущего фронта (UPD2 §1) устраняются по конкретным требованиям §4/§6/§7/§9.

**В scope:**
- **A (layout).** Устранить съезды/наложения/перекрытия shell, mobile, fullscreen и конфликт SaveBar↔внутренний скролл (§1.1, §5.3–§5.5, §7).
- **B (Liquid Glass).** Отделить shell-токены от карточных; вернуть серо-графитовый стеклянный характер; убрать цветную линзу/ореол/виньетку; тонкая обводка, мягкий inner highlight, subtle specular + текстура, очень слабое преломление (§1.2, §3, §4, §5.1–§5.3).
- **C (background).** Заменить почти мёртвый conic-wash (`--grad-speed 75s`, opacity .30) на живой aurora/mesh-фон в палитре §8/§10, пауза при `document.hidden`, `prefers-reduced-motion` (§1.3, §6).
- **D.** Обязательная приёмка: 5 режимов (§8.5) + 12 критериев §9; аудит остатка ТЗ и продолжение (§10).

**Вне scope (excluded):**
- Редизайн с нуля; смена IA/маршрутов; замена задачи псевдо-glass (§10 «Важно»).
- Backend, БД, `services/param_catalog.py`, любые API-контракты (Δ DDL = 0, Δ каталога = 0).
- Новые библиотеки (включая **Framer Motion/React**), WebGL, CDN, сборщик (CSP/zero-build, ADR-1016-2 / ADR-1024-13).
- Нативные кнопки Telegram (⋮/Закрыть/Свернуть) — CSS не двигать (§604/§642/§56/§59).
- Переписывание `persistItems` (F0), store-контракта F4 §37–§42, F1/F2/F3/F5 §61, SaveBar F9 (только согласование, без дублирования логики).

## 2. Трассируемость UPD2 → требование → решение → задача

| UPD2 | Требование (наблюдаемое) | Решение | Задачи |
|---|---|---|---|
| §1.1 (6170–6180) | Нет съездов/наложений; стабильный fullscreen/mobile; bottom-nav не перекрывает контент; SaveBar↔скролл разведены | ADR-16 D4 | T-2748…T-2756 |
| §1.2/§3/§4 (6181–6300) | Shell = серо-графитовый glass-слой ≠ карточки; **нет** ореола/виньетки/цветной ауры; точные токены §4 | ADR-16 D2 | T-2757…T-2766 |
| §1.3/§6 (6189–6387) | Фон живой (не статичный), 3–5 blob, палитра, фазы, morphing, grain, скорость | ADR-16 D3 | T-2767…T-2773 |
| §5.1–§5.4 | Sidebar 208–224px; topbar-элементы не «плавают»; mobile top shell компактен; bottom nav с safe-area/hit-area | ADR-16 D2/D4 | T-2752, T-2756, T-2763, T-2764, T-2765 |
| §5.5 | Modal/drawer/settings: нет конфликта скролла; SaveBar не перекрывает инпуты; CTA/Cancel на малой высоте | ADR-16 D4 | T-2754, T-2755 |
| §7 (6389–6413) | Геометрия desktop/tablet/mobile/fullscreen; gap header↔карточка 16–20px; без h-scroll | ADR-16 D4 | T-2749…T-2753 |
| §8 (6416–6445) | Порядок: shell-токены → панели → фон → mobile → 5 режимов | ADR-16 D1–D5 | T-2757 → … → T-2774 |
| §9 (6448–6467) | 7 «не принято» + 5 «принято» | §6 ниже | T-2775, T-2777 |
| §10 (6470–6496) | Без human gate; аудит остатка; отчёт 3 пункта | — | T-2778…T-2780 |
| §2 (6196–6216) | Framer Motion/React/SVG-фильтры | **ADR-16 D1** | T-2747, T-2762 |

## 3. Решения (полное обоснование — ADR-1025-16)

- **D1 — Framer Motion: объективный отказ + эквивалент.** UPD2 §2 просит Framer Motion/React. Framer Motion **React-only** и требует npm-сборки — несовместим с Vue 3 global zero-build + CSP `script-src 'self'` (ADR-1016-2/ADR-1024-13). **Эквивалент на текущем стеке (приоритет):** (1) **CSS animations/transitions** (keyframes, easing, `transform`/`opacity` — композиторный путь) — основное для shell/микродвижений; (2) **Web Animations API** — для динамических/прерываемых последовательностей, где CSS-ключей мало; (3) **SVG-фильтры** (`feGaussianBlur`/`feTurbulence`/`feDisplacementMap`) — преломление/шум (движок уже есть: inline `#lg-lens`, `index.html:37`); (4) **Canvas 2D + rAF** — только если CSS объективно недостаточен (фон/преломление), с паузой при hidden/reduced-motion. WebGL и новые библиотеки запрещены. Spring/инерционные эффекты Framer эмулируются CSS `cubic-bezier`/WAAPI-`easing`.
- **D2 — shell-токены и стекло.** Значения строго по §4 (см. §4 ниже). Shell-токены `--shell-*` — **отдельные**, карточные `--glass-*` не трогаются. Панели (`sidebar`, `header`, `drawer`, `bottom-nav`, `more-sheet`) переводятся с `data-glass="a"` на **`data-glass="shell"`**: снимается цветная teal/blue/violet линза `[data-glass="a"]::before` (источник ореола/виньетки), вводится нейтральный графитовый рецепт (base `--shell-bg` + `--shell-blur` + тонкая обводка + мягкий inner highlight + subtle specular/текстура + очень слабый **нейтральный** sheen). Никакого внешнего glow. Контраст AA ≥ 4.5:1 сохраняется.
- **D3 — aurora/mesh в рамках CSP.** Предпочтительно **CSS-слои**: 3–5 больших размытых blob (radial-gradient + blur, `transform`/`opacity`/morph формы), разные длительности и отрицательные `animation-delay`, палитра §10 (teal/violet/blue/indigo, без оранжевого), слабый grain. Скорость «медленно, но заметно». Пауза `html.lg-bg-paused` (`app.js:10029-10033`) + `prefers-reduced-motion` → статичный атмосферный снимок. **Canvas 2D+rAF — только фолбэк** при доказанной нехватке CSS (решение фиксируется в `evidence.md`). Фон — отдельный задний слой (`z-index` ниже `#app`), без ореола вокруг shell, без ухудшения контраста.
- **D4 — геометрия.** Единый сток высоты `--shell-h` (нормальный/полноэкранный режимы) сохраняется; sidebar в 208–224px; gap header↔первая карточка 16–20px; mobile-порядок header → строка селектор/профиль → контент → bottom nav → safe-area; без h-scroll; fullscreen без исчезновений (fullscreen-sync ADR-1024-24, `computeBottomOffset`/hotfix4 — сохраняются); SaveBar не перекрывает инпуты и не конфликтует с внутренним скроллом (сохранить `scroll-padding-bottom`/`.sticky-spacer`, согласовать с F9).
- **D5 — границы/инварианты.** Δ DDL = 0, Δ каталога = 0; CSP/zero-build; без WebGL/новых библиотек/CDN; не редизайн; не ломать F1/F2/F3/F4/F5; SVG-displacement — только на декоративном слое (см. §5), никогда на тексте/интерактиве, `backdrop-filter: url()` запрещён (прецедент hotfix6). Флаги — env-only, default ON, Δ каталога = 0.

## 4. Точные значения shell (§4) и три слоя

| Токен | Значение (§4) | Было (hotfix7) |
|---|---|---|
| `--shell-bg` | `rgba(24,28,38,0.72)` | `rgba(33,37,45,0.62)` |
| `--shell-bg` (mobile ≤767) | `rgba(24,28,38,0.78)` | — |
| `--shell-border-color` | `rgba(255,255,255,0.08)` | `rgba(178,190,208,0.20)` |
| `--shell-highlight` | `rgba(255,255,255,0.06)` | `rgba(255,255,255,0.18)` |
| `--shell-shadow` | `0 8px 24px rgba(0,0,0,0.18)` | `0 12px 30px -18px rgba(3,7,18,0.55)` |
| `--shell-blur` | `blur(18px) saturate(115%)` (+`-webkit-`) | `blur(18px) saturate(120%)` |
| Радиусы | sidebar `0`/большой внешний; topbar/pill/selector/floating `14–18px`; mobile blocks `16–20px` | `14px`/`.9rem` и т.п. |

**Три слоя глубины:** фон (aurora, отдельный задний слой, `z-index` < `#app`) → карточки (`--glass-bg`, `--card-shadow`, alpha .5) → shell (графит `--shell-bg`, плотнее/серее, тонкая обводка, мягкий highlight) → модалки (плотнее card). Shell **не** перекрашивается в сине-фиолетовый тон карточек.

## 5. SVG displacement — границы (решение (e))

- **Разрешено:** существующая foreground-линза `[data-glass="a"]::before` на контентных карточках (allow-list, min-сторона ≥240px, deny-list tier C) — без изменений; **один** новый **нейтральный** sheen на shell (`[data-glass="shell"]::after`, безцветный, `opacity` ≤ .05, `pointer-events:none`, под контентом, `filter: var(--glass-displace)` переиспользует `#lg-lens`) — «заметно лишь при внимательном рассмотрении».
- **Запрещено:** `backdrop-filter: url(...)`; displacement на тексте/интерактивных элементах; цветная реплика-градиент с radial-mask на shell; внешнее свечение; расширение deny-list (textarea/таблицы/логи/формы/редакторы — уровень C).
- Палитра §8 не меняется; в палитре фона нет оранжевого.

## 6. Наблюдаемое поведение, приёмочные сценарии и failure cases

**Принято (UPD2 §9):** shell — тёмно-серый glass-слой ≠ карточка; стекло subtle/дорогое; фон живой/атмосферный; desktop/mobile/fullscreen стабильны; единый polished UI.
**НЕ принято (любой п. = возврат):** shell как карточка; яркий ореол вокруг shell; дешёвый blur/виньетка; статичный фон; mobile перекрывает контент; SaveBar↔скролл конфликт; shell не отделён по глубине.

**5 обязательных режимов (§8.5):** desktop normal · desktop fullscreen · tablet · mobile portrait · **mobile fullscreen inside Telegram WebView** (live, владелец).

**Проверяемые инварианты (Playwright-матрица):** computed `background-color`/`border-color`/`box-shadow` shell `≠` карточных; на shell нет цветного `::before`-градиента; `backdrop-filter` содержит `blur(18px) saturate(115%)`; shell `background-image` не содержит teal/violet градиента; `scrollWidth ≤ innerWidth+1`; `rect.bottom ≤ innerHeight+1`; gap header↔карточка ∈ [16,20]px; sidebar width ∈ [208,224]px; aurora-анимация активна (не static), при `hidden` — `lg-bg-paused`, при reduced-motion — `animation: none`; hit-area bottom-nav ≥44×44.

**Failure cases (обязательны к обработке):**
- нет `backdrop-filter` (старый WebView) → плотный фолбэк `--shell-bg-strong`, читаемость сохраняется;
- `prefers-reduced-motion` → shell-анимации отключены, aurora статична, контраст не ниже;
- `document.hidden` → aurora пауза (без второго `visibilitychange`-обработчика);
- малая высота/клавиатура → CTA/Cancel SaveBar доступны, инпуты не перекрыты;
- fullscreen TMA → ничего не исчезает, высота не «дёргается»;
- отсутствие `playwright` в среде → Info (не блокер), live-гейт владельца обязателен.

## 7. Интерфейсы, данные, совместимость

- **Frontend-only:** `web/static/app.css`, `web/index.html` (inline SVG-фильтры/слой aurora/атрибуты `data-glass`), `web/app.js`, `web/static/telegram-init.js`, `tools/ui_round1025_matrix.py`, тесты/маркеры.
- **Контракт атрибута:** `data-glass` получает значение **`shell`** (нейтральный shell-рецепт); значения `a`/`b`/`c` и deny-list — без изменений. `reconcileLiquidGlass` (`app.js:9922-9962`) продолжает работать только с `[data-glass="a"]` — shell из перф-бюджета линзы выводится (побочный плюс).
- **API:** без изменений. Новые env-only `ClassVar` в `config/settings.py` + аддитивно в `GET /api/me.ui_flags`: **`UI_SHELL_V3`** (default ON; OFF → значения `--shell-*` hotfix7 без цветной линзы) и **`UI_AURORA_BG_ENABLED`** (default ON; OFF → прежний conic page-wash). Δ каталога = 0.
- **Данные/миграции:** нет. Δ DDL = 0 (SQLite v12), Δ каталога = 0.
- **Совместимость:** сохранены `--shell-h`, `computeBottomOffset`, fullscreen-sync ADR-1024-24, `--header-h`, нативные кнопки, IA F1, store F4 §37–§42, `persistItems` F0, SaveBar F9.

## 8. Безопасность/приватность

- CSP `script-src 'self'` без изменений; только inline `<svg>`-фильтры (уже есть) — без инлайновых скриптов, CDN, data-URI, внешних ассетов.
- **R17:** без секретов/сырых значений в логах/отчётах/скриншотах. **R18:** `current_task.md` — untracked, не коммитить/не изменять; теги/бэкапы `pre-round1025*` и `stash@{0}` не удалять.
- Perf-бюджет Telegram WebView: blob-слои — композиторные (`transform`/`opacity`), ограниченный `blur`, `contain`; Canvas-фолбэк (если) — один rAF, DPR cap ≤2, пауза при hidden.

## 9. Зависимости

F1 (IA) §54, F2 §57.1 (токены/§8/§10), F3 §57.3, F4 §60 (store), F5 §61, hotfix6/7 §58/§59 (линза/heartbeat/`--shell-h`), ADR-1024-24 (fullscreen-sync), ADR-1016-2/ADR-1024-13 (CSP/`ui_flags`). Блокирует F6 (снятие «ждёт» после HOTFIX8). Инструмент приёмки — `tools/ui_round1025_matrix.py`.

## 10. Тесты, деплой, откат

- **Юниты/маркеры:** обновить inventory-маркеры под новые shell/animation-токены и новый фон одним коммитом с кодом (без рассинхрона эталонов); сохранить `MODULE-*`/`PROMPTS-*`/`HOTFIX*-*`; `node --check web/app.js`/`telegram-init.js`; pytest целевой.
- **Матрица:** 5 режимов × 10 вьюпортов (§71) + перечисленные инварианты §6; артефакт — `plans/reports/round1025_hotfix8_ui_report.md`.
- **AA:** пересчитанная таблица «пара → эффективный фон → ratio → PASS» (худшая фаза aurora) → `plans/reports/round1025_hotfix8_contrast.md`.
- **Bump:** `APP_VERSION` 2.58.10 → 2.58.11 + cache-bust `?v=`.
- **Откат:** hard — тег `pre-round1025-hotfix8` (T-2745) + `git revert`; soft — env-only `UI_SHELL_V3=false`, `UI_AURORA_BG_ENABLED=false` (и унаследованные `UI_SHELL_GLASS_V2`/`UI_SHELL_LAYOUT_V2`), default ON.

## 11. AMEND-карта (детали — ADR-1025-16 §SUPERSEDE/AMEND)

| Ранее | Действие |
|---|---|
| **ADR-1025-13 D3** (shell-токены `.62/.90/.20/.18`, blur saturate 120%) | **AMEND → D2** — значения → §4 (`rgba(24,28,38,.72)`/mobile .78, border .08, highlight .06, shadow, saturate 115%); карточные токены не трогаются |
| **ADR-1025-13 D3** (цветная линза `[data-glass="a"]` на панелях) | **AMEND/REVISE → D2** — панели → `data-glass="shell"`, цветная линза/ореол сняты, нейтральный sheen |
| **ADR-1025-13 D4** (`UI_SHELL_LAYOUT_V2`, выравнивание) | **AMEND → D4** — сохраняется; gap 16–20px, sidebar 208–224px, mobile-порядок |
| **ADR-1025-9 D2** (значения токенов/glass-shell) | **Уточнение → D2** — новый shell-рецепт; карточный `--glass-bg`/палитра §8 не меняются |
| **ADR-1025-9 D3 + фон §10 (F2)** | **REVISE → D3** — conic page-wash → aurora/mesh; `@property --grad-angle`+`grad-spin`/`grad-drift` **сохраняются** для `.grad-band`/кнопок |
| ADR-1025-12 D1 (foreground-линза), D3 (`computeBottomOffset`), D5 (нативные кнопки/`--header-h`/fullscreen), ADR-1024-24, deny-list tier C, AA §8, F0 `persistItems`, F1 IA, F4 §37–§42 | **СОХРАНИТЬ** (не отменяются) |

## 12. Открытые вопросы / эскалации

**Блокирующих `ARCHITECT_DECISION_REQUIRED` нет** — все решения (a)–(e) из `tasks.md` разрешены выше и в ADR-1025-16. Единственный внешний гейт — **T-2776** (live-гейт владельца, реальный Telegram WebView): headless-матрица не измеряет реальный WebView, а именно там живёт риск геометрии/fullscreen/FPS. Это ограничение проверки, а не выбор владельца.

## 13. Расхождения spec ↔ tasks.md

Соответствий 1:1, расхождений нет: решения (a)–(e) покрыты D1–D5, все UPD2 §1–§10 трассированы на T-2748…T-2780, инварианты — на T-2781/T-2782. Возврат к @PM не требуется.
