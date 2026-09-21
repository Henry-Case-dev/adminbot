# HOTFIX7 — `hotfix7-shell-glass-heartbeat-round1025` — Step 2 design (`spec.md`)

> **ТЗ:** **UPD «Срочный фикс текущего фронта»**, `plans/current_task.md`, строки **6073–6154** (UPD 1–7). `current_task.md` **НЕ изменялся** (untracked; R18).
> **Тип:** UI + shell/glass/heartbeat (web, **zero-build**). **Приоритет:** P0 (выше F4).
> **Автор:** @Architect (Step 2), 22.09.2026. **Статус:** Proposed → к реализации.
> **ADR:** `adr-1025-13-shell-glass-heartbeat-v2.md` (D1–D5, AMEND-карта, альтернативы).
> **Задачи:** T-2658…T-2694 (`tasks.md` этой папки). Трассируемость — §3.
> **Инварианты:** Δ DDL = 0, Δ каталога = 0 (`REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418`), CSP/zero-build, **запрет WebGL** (Canvas 2D разрешён), R17/R18.
> **Первоисточники:** `plans/ARCHITECTURE.md` §54/§56/§57/§58; `plans/archive/hotfix6-webview-shell-heartbeat-round1025/adr-1025-12-*.md`; `plans/archive/design-tokens-liquidglass-v2-round1025/adr-1025-9-*.md`; код `web/static/app.css`, `web/app.js`, `web/index.html`, `web/static/telegram-init.js`, `tools/ui_round1025_matrix.py`.

---

## 1. Scope / Excluded scope

### 1.1 Scope (обязательный объём — UPD 1–6)

- **D1** — единый механизм высот shell и предсказуемая геометрия в **normal и fullscreen** (desktop + mobile TMA WebView); heartbeat **виден** во всех режимах; исправление конфликта `min-height` / `height:100dvh` / `overflow:hidden`.
- **D2** — premium-визуал Canvas 2D «Сердцебиение»: мониторинговый вид вместо «линия + плавающая точка»; цвет/интенсивность по состояниям; reduced-motion-фолбэк; FPS-бюджет. **Семантика ADR-1025-12 D4 не отменяется.**
- **D3** — отдельный слой glass-shell: серо-графитовые токены `--shell-*`, отличные от карточных `--glass-*`; рецепт liquid glass (base + blur + внутренняя подсветка + тонкая обводка + слабый specular + аккуратная текстура); глубина «фон → shell → карточки»; удаление грубого затемнения; контраст AA ≥ 4.5:1.
- **D4** — выравнивание shell: header без наезда, цельные sidebar/topbar, mobile safe-area / Telegram chrome / нижний bar / fullscreen.
- **D5** — совместимость и инварианты, AMEND-карта (ADR-1025-12 D2/D4; уточнение ADR-1025-9 D2), env-only флаги, обязательная приёмка UPD 6 (5 режимов) и доработка `tools/ui_round1025_matrix.py`.

### 1.2 Excluded scope (не делаем)

- **Новый редизайн с нуля** и смена информационной архитектуры (IA F1) — маршруты `#/…`, меню, разделы, порядок навигации hotfix4 сохраняются байт-в-байт.
- Изменение **semantics** heartbeat: `_heartbeatTransition`/`heartbeatSample` (пороги, EMA, гистерезис, dwell, `missing ≠ bad`, UNKNOWN) — только визуал (ADR-1025-12 D4).
- Отмена/переписывание **ADR-1025-12 D1** (foreground-линза/feature-detect), **D3** (`computeBottomOffset = max`), **D5** (нативные кнопки, `--header-h`, fullscreen-sync **ADR-1024-24**), deny-list tier C.
- Backend/DDL/каталог: `services/param_catalog.py`, миграции, `services/**` (кроме аддитивного `ui_flags`) — **не трогаются**. Store-контракт F4 §37–§42 и write-path F0 `persistItems` — **не переписываются**.
- WebGL, внешние ассеты/CDN/data-URI, новые зависимости/state-библиотеки. Звук heartbeat, «BPM»-числа, исторические графики — нет.

---

## 2. Диагностика (подтверждение первопричин по коду)

Все первопричины, переданные @Memory, **подтверждены по коду** (Step 2):

| # | Первопричина | Подтверждение (код) |
|---|---|---|
| P1 | **Shell слился с карточками** | `.app-sidebar` (`app.css:1570`), `.app-drawer` (`:1593`), `.bottom-nav` (`:1618`), `.more-sheet` (`:1668`) используют `background: var(--glass-bg)` — **тот же токен**, что карточки `.card/.module-card/.hub-card` (`:1037`). Одинаковы `--glass-blur`, `--glass-border`, `--glass-shadow`. |
| P2 | **«Дешёвый» heartbeat** | `_hbDraw` (`app.js:6635-6678`): бегущая синусоида `Math.sin(phase + t*freq)` + отдельный импульс-отрезок, сдвигающийся `pulseX = ((t*1000)%span)/span*w` = «линия + плавающая точка». |
| P3 | **«Грязный» вид** | Тяжёлая `--glass-shadow: 0 18px 40px -18px rgba(3,7,18,.75)` (`:60`), плотный `body::before` `opacity:.42` (`:126-138`), `--glass-bg-strong` alpha `.85` (`:53`). |
| P4 | **Fullscreen-высоты** | `.app-shell` одновременно `min-height: var(--tg-viewport-stable-height, 100vh)` (`:805-810`) **и** `.fullscreen-mode { height:100dvh; overflow:hidden }` (`:819-828`). При расхождении stable-height и `dvh` `min-height` может превысить `height` → flex-колонка переполняет shell, `overflow:hidden` обрезает низ; старые WKWebView без `dvh` → `height:auto` при `min-height` = stable → скачок. |
| P5 | **Производная P4** | `.scroll-area` в fullscreen — единственный скроллер (`flex:1 1 auto; min-height:0`), но shell не ограничен снизу корректно; `.status-block__grid` (`:992-997`) — grid `1fr`/`1.4fr 1fr 1.2fr`; heartbeat — первая секция. Дополнительный разрыв — `@supports not (backdrop-filter)` (`:1159-1168`) возвращает панелям **карточный** `--glass-bg-strong`. |

**Важно:** точный сценарий «heartbeat исчезает в fullscreen» **не воспроизводится headless** — это **live-гейт** (T-2682). Дизайн D1 устраняет класс причин (смешанные высоты + неявный overflow), а матрица (T-2681) добавляет **форсированный fullscreen**-прогон с проверкой видимости heartbeat.

---

## 3. Трассируемость UPD → решение → задача

| UPD (строки `current_task.md`) | Требование | Решение | Задачи |
|---|---|---|---|
| UPD 1 (6076–6080) | Стабильная геометрия; в fullscreen ничего не пропадает/режется; heartbeat виден; container sizing/overflow/z-index/sticky/safe-area/высоты | **D1** | T-2661…T-2665, T-2681, T-2682 |
| UPD 2 (6082–6093) | Premium pulse-индикатор; цвет по метрикам; пульс/свечение; не `translateX`; читаемость; normal/fullscreen/mobile | **D2** | T-2666…T-2670 |
| UPD 3 (6095–6101) | Header/sidebar серо-графитовые, отдельный слой, не в цвет карточек | **D3** | T-2671, T-2672 |
| UPD 4 (6103–6115) | Liquid glass: base + blur + подсветка + обводка + specular + текстура + глубина; без виньетки/грязи; премиально | **D3** | T-2673…T-2677 |
| UPD 5 (6117–6122) | Header без наезда; цельные sidebar/topbar; mobile safe-area/chrome/bottom-bar/fullscreen | **D4** | T-2678…T-2680 |
| UPD 6 (6124–6136) | 5 режимов + Playwright + live WebView | **D1/D5** | T-2681…T-2683 |
| «Важно» (6150–6154) | Без редизайна; не ломать IA; не «косметический blur» | **D5**, §1.2 | T-2684, T-2685 |

Открытые вопросы @PM **(a)–(e)** закрыты решениями D1–D3 ниже и ADR-1025-13; вопрос **(f)** — зона @PM (UPD 7).

---

## 4. Решения

### D1. Единый механизм высот shell + стабильная геометрия (UPD 1)

**D1.1 — единственный источник высоты (ред. review F-2: реальный фолбэк).** Вводим один токен-сток `--shell-h` в `:root`:

```css
--shell-h: 100vh;   /* базовое значение: объявлено ВСЕГДА и валидно везде */
```
Прогрессивное улучшение — **только внутри `@supports`**. Причина: значения custom properties **не валидируются при разборе** — браузер хранит почти любое значение и объявляет результат невалидным лишь при `var()`-подстановке (invalid at computed-value time). Поэтому прежняя цепочка `100vh → 100dvh → min(100dvh,…)` в WebView без `dvh`/`min()` **не** давала `100vh`: `min-height: var(--shell-h)` становился невалидным и падал в initial `auto` (в fullscreen — `height:auto`).

```css
@supports (height: 100dvh) and (height: min(100dvh, 100dvh)) {
  :root {
    --shell-h: min(100dvh, var(--tg-viewport-stable-height, 100dvh));
  }
}
```
- Старый движок без `dvh`/`min()` не заходит в `@supports` → остаётся **гарантированно валидный `100vh`** (не `auto`/`0`).
- Современный движок вне Telegram: `--shell-h = min(100dvh,100dvh) = 100dvh`; в TMA при наличии `--tg-viewport-stable-height` берётся **минимум** с `dvh` → shell не выше видимой области (устраняет обрезку низа).
- **Запрещено** одновременно задавать конкурирующие `min-height`/`height` c разными значениями.
- **Эмпирика (T-2681).** Playwright-проба `F7_PROBE_JS` сравнивает валидную prod-структуру (`base 100vh` + апгрейд за `@supports`) с прежней цепочкой на синтетическом стенде, где отсутствие `dvh` эмулируется заведомо неподдерживаемой единицей в `@supports`-условии: база обязана дать высоту видимой области, а прежняя цепочка — схлопнуться (в Chromium `min-height` → `0px`/`auto`). `_hotfix7_failures` валит прогон, если база не равна вьюпорту или если `.app-shell` получает `min-height: auto`.

**D1.2 — два явных режима (никаких смешанных объявлений):**
- **Normal (`.app-shell:not(.fullscreen-mode)`):** `min-height: var(--shell-h); height: auto; overflow: visible;` — страница скроллится нативно, header `sticky`.
- **Fullscreen (`.fullscreen-mode`):** `height: var(--shell-h); max-height: var(--shell-h); min-height: 0; overflow: hidden;` — shell ровно по видимой области, **единственный** скроллер внутри — `.scroll-area` (`overflow-y:auto; min-height:0`).
- Удаляется старое `.app-shell { min-height: var(--tg-viewport-stable-height,100vh) }` в текущем виде и `.fullscreen-mode{height:100dvh}` — заменяются на D1.1/D1.2.

**D1.3 — overflow / вложенный скролл.** `overflow:hidden` на `.fullscreen-mode` остаётся (клиппует всплывающие слои shell), но теперь согласован с `--shell-h`. `.scroll-area` в fullscreen: `overflow-y:auto`, `overscroll-behavior:contain`, `padding-bottom` = резерв под `.bottom-nav` + safe-area + `--tg-viewport-bottom-offset`. Горизонтальный скролл запрещён (`scrollWidth <= clientWidth`).

**D1.4 — z-index / stacking (документируется и фиксируется):** фон `body::before` (0) < контент `#app` (1) < сайдбар/стекло панелей (30) < sticky-header (40) < bottom-nav/drawer (40) < more-sheet (50) < модалки (выше). Heartbeat — внутри `.scroll-area` (слой контента), своих z-index не получает; клиппинг контейнера запрещён.

**D1.5 — safe-area / Telegram chrome / sticky.** Сохраняется существующая схема `max(env(safe-area-inset-*), --tg-safe-area-inset-*, --tg-content-safe-area-inset-*)` для header/sidebar/bottom-nav/more-sheet и `viewport-fit=cover`. `--tg-viewport-bottom-offset` (= `computeBottomOffset`, ADR-1025-12 D3) **не меняется**. Нативные кнопки Telegram (⋮/Закрыть/Свернуть) **CSS не двигаются** (вне DOM) — резерв высоты через `--header-h` (ResizeObserver, `app.js:8564-8586`) сохраняется.

**D1.6 — явная гарантия видимости heartbeat.** `.status-block__pulse`/`.hb-wrap`/`.hb-canvas` не получают `display:none`, `height:0` или наследованный клиппинг от `.fullscreen-mode`. Минимальная высота канваса сохраняется (`56px`; `52px` ≤767). В fullscreen `.scroll-area` стартует с heartbeat в первой секции статуса (`#/`) — проверяется матрицей.

**Проверка:** Playwright **5 режимов** (desktop normal / desktop fullscreen / tablet / mobile regular / mobile fullscreen) + **реальный Telegram WebView** (T-2682) — см. §8.

---

### D2. Receipt: premium heartbeat на Canvas 2D (UPD 2)

**Стек — переиспользуем:** Canvas 2D + `requestAnimationFrame`, существующий цикл `startHeartbeatCanvas`/`_hbFrame`/`stopHeartbeatCanvas` (`app.js:6589-6633`), DPR-масштабирование, пауза по `document.hidden` и вне вкладки «Статус», `UI_HEARTBEAT_CANVAS_ENABLED` OFF → legacy SVG байт-в-байт. **WebGL запрещён.**

**D2.1 — мониторинговый рендер: sweep-wipe ECG (не translateX).**
- **Форма сигнала** — реалистичный кардиокомплекс `ecg(u)`, `u∈[0,1)` период одного удара: изолиния; зубец **P** (гауссов пик ≈ +0.08, u≈0.18); **Q** (≈ −0.10, u≈0.34); **R** (≈ +1.00, u≈0.365); **S** (≈ −0.22, u≈0.39); зубец **T** (≈ +0.20, u≈0.55). Значение — сумма гауссиан от базовой линии. Это **не синусоида**.
- **Развёртка (sweep-wipe):** «луч» идёт слева-вправо за `sweepPeriod`; позади луча трасса яркая, впереди — приглушённая изолиния; в начале нового прохода трасса обновляется. Так ведёт себя реальный монитор; **горизонтального переноса всей линии и «плавающей точки» нет**.
- **Число комплексов на проход** `beatsPerSweep` — от состояния (норма 3 → warning 4 → critical 5), а не от выдуманного BPM.
- **Свечение и пульс:** `ctx.shadowBlur` (cap radius) для трассы и «головы луча»; при проходе лучом R-пика — **вспышка-взрыв** (radial glow, затухание ≈0.35 c) — «удар». **Дыхание яркости** — общий `globalAlpha` модулируется медленной синусоидой (≈0.15 Гц).
- **Сетка монитора:** очень бледная (alpha ≈0.05–0.07), опционально кэшируется (offscreen) при resize; не перегружает кадр.
- **Без тултипа внутри canvas:** интерактив (`toggleHeartbeatTip`, hover/tap, `aria-*`) сохраняется.

**D2.2 — цвет/интенсивность по состояниям (палитра §8, single-source; ред. review F-3/F-4).** Цвета читаются из **статус-токенов** (`--ok`, `--warn`, `--err`, `--text-3`) через `getComputedStyle` **однократно на смену состояния** (кэш), с §8-фолбэками. HEALTHY/WARNING/CRITICAL используют **тот же источник, что и бейдж** `.hb-<state>` — трасса и подпись больше не расходятся (прежний teal `--teal-500` для HEALTHY был исключением):

| Состояние | Ядро | Свечение (alpha) | Амплитуда | Период прохода | Характер |
|---|---|---|---|---|---|
| HEALTHY (норма) | green `#3DD68C` (`--ok`) | `rgba(61,214,140,.45)` | базовая | спокойный (крупный) | редкий ровный ритм, мягкое свечение |
| WARNING | amber `#F6C56F` (`--warn`) | `rgba(246,197,111,.60)` | выше | чаще | ощутимо чаще/резче |
| CRITICAL | red-pink `#F07178` (`--err`) | `rgba(240,113,120,.85)` | высокая | самый частый | резкая трасса, **заметно сильнее свечение** (множитель `shadowBlur` ×1.5) |
| UNKNOWN | muted `#A2B0C6` (`--text-3`) | без glow (α `0`) | низкая | медленный/почти статичный | приглушённая изолиния, **без** выдуманных значений |

Альфа свечения (`glowAlpha`) и множитель `shadowBlur` (`glowScale`) — **лестница от состояния** (`.45/.60/.85/0` и `×0.9/×1.1/×1.5`); вспышка R-пика масштабируется той же альфой. Интенсивность — **производная от уже существующих** `hbState` и `hbEma`: амплитуда, резкость, частота и сила glow. Число/BPM **не показываем**.

**D2.3 — сохранение честной семантики (НЕ отменяется).** `_heartbeatTransition` (`app.js:6440-6507`), `heartbeatSample` (`:6512-6561`), `_applyHeartbeatSample`, EMA/гистерезис/dwell, `missing ≠ bad`, UNKNOWN, тултип, поллинг 30 с (`GET /api/status`, без нового поллера) — **без изменений**. Меняется только `_hbDraw` (+ вспомогательные приватные функции рисования).

**D2.4 — reduced-motion.** Один статичный кадр: полная ECG-трасса в цвете состояния, без луча/свечения/дыхания; текст и бейдж состояния сохранены. `_prefersReducedMotion()` используется как сейчас.

**D2.5 — бюджет FPS/нагрузки.** Один rAF-цикл (уже); `dt` клампится (после смены вкладки нет прыжка); `DPR` cap = 2; `shadowBlur` ограничен; сетка кэшируется; пауза при `document.hidden`/не-`status`; допускается адаптивный пропуск кадров при низком FPS (внутренняя константа, без env-ручки). Замер FPS — live-гейт T-2682 (преемник M-H6-1).

**D2.6 — флаг.** `UI_HEARTBEAT_PREMIUM` (env-only, default **ON**): OFF → **текущий** canvas-рендер (синусоида + импульс) для мягкого отката D2 без редеплоя. При `UI_HEARTBEAT_CANVAS_ENABLED=OFF` — legacy SVG (как сейчас).

---

### D3. Glass shell: отдельный слой + рецепт liquid glass (UPD 3–4)

**D3.1 — новые shell-токены (grey-graphite), не карточные.** В `:root` добавляются (карточные `--glass-*` **не меняются** по семантике):

```css
/* Серо-графитовый слой shell (не цвет карточек; derived from §8 neutrals, без смены палитры) */
--shell-bg:            rgba(33, 37, 45, 0.62);
--shell-bg-strong:     rgba(24, 28, 35, 0.90);   /* header: плотнее — читаемость поверх скролла */
--shell-border-color:  rgba(178, 190, 208, 0.20);
--shell-border:        1px solid var(--shell-border-color);
--shell-highlight:     rgba(255, 255, 255, 0.18);   /* тонкая верхняя внутренняя подсветка */
--shell-highlight-soft:rgba(255, 255, 255, 0.05);   /* нижняя внутренняя */
--shell-shadow:        0 12px 30px -18px rgba(3, 7, 18, 0.55);  /* мягче карточной */
--shell-blur:          blur(18px) saturate(120%);   /* стекляннее и серее карточного */
--shell-specular:      linear-gradient(160deg, rgba(255,255,255,.10), rgba(255,255,255,.02) 42%, transparent 72%);
--shell-texture:       repeating-linear-gradient(135deg, rgba(255,255,255,.020) 0 1px, transparent 1px 3px); /* faux-noise, без ассетов/data-URI */
--card-shadow:         0 8px 20px -14px rgba(3, 7, 18, 0.45);   /* карточки ближе к фону */
```

**D3.2 — применение (shell-панели):** `.app-sidebar`, `.app-drawer`, `header.header-sticky`, `.bottom-nav`, `.more-sheet` получают `background: var(--shell-bg)` (header — `--shell-bg-strong`), `-webkit-backdrop-filter/backdrop-filter: var(--shell-blur)`, `border-color: var(--shell-border-color)`, `box-shadow: var(--shell-shadow)`, `inset 0 1px 0 var(--shell-highlight)`. **Карточки** (`.card`/`.module-card`/`.hub-card`/…) остаются на `--glass-bg`/`--glass-border`, но с **лёгкой** `var(--card-shadow)` — тоньше и ближе к фону. `@supports not (backdrop-filter)` (`:1159-1168`) для shell-панелей возвращает `--shell-bg-strong`, для карточек — `--glass-bg-strong`.

**D3.3 — рецепт liquid glass (все слои, без WebGL/ассетов):**
1. полупрозрачный серо-графитовый base (`--shell-bg`);
2. `backdrop-filter: var(--shell-blur)` (blur, не url);
3. очень мягкая внутренняя подсветка (два `inset`-highlight);
4. тонкая светлая полупрозрачная обводка (`--shell-border-color`);
5. слабый **specular** — `--shell-specular` как `::after`/слой `background-image`, opacity ≤.12, диагональ сверху; не «резиновый глянец»;
6. **аккуратная текстура** — `--shell-texture` alpha ≤.02, только shell;
7. глубина «фон → shell → карточки» (D3.4);
8. **без** грубой виньетки/грязного затемнения (D3.5);
9. контраст AA (D3.6).

**D3.4 — глубина:** фон — плоский wash; **карточки** — `--glass-bg` + `--card-shadow` (низкая «высота», близко к фону); **shell** — плотнее/темнее по тону (graphite) + `--shell-shadow` (слегка «отрывается» над контентом) + specular/обводка. Модалки/тултипы — над shell (сохраняют `--glass-shadow`).

**D3.5 — убрать «грязь»:** `--glass-shadow` alpha `.75 → ~.55` (или оставить только для модалок/тултипов, а карточкам дать `--card-shadow`); `body::before opacity .42 → .30` (reduced-motion `.35 → .26`), механику/цвета/длительности §10 **не менять** (нет оранжевого, 60–90 с / 90–120 с сохраняются). Никаких «виньеточных» радиальных затемнений не добавляем.

**D3.6 — контраст AA ≥ 4.5:1.** Пересчитать таблицу «пара → эффективный фон → ratio → PASS/FAIL» в `plans/reports/round1025_hotfix7_contrast.md` (метод ADR-1025-9 D4 / hotfix6: композит `--shell-bg`/`--glass-bg` поверх **худшей** фазы фона §10, порог 4.5 для `.75rem`/10 px). Обязательный охват: `.sidebar-link`, `.sidebar-link.active`, `.bottom-nav-label`, `.bottom-nav-link.active`, `.more-item`, текст header, `.hb-tip`. При провале — повышать **плотность** токена, **не** менять палитру §8. Аналитическая оценка: при `--shell-bg` alpha .62–.66 `--text-2 #AAB6C8` даёт ≈5.9–6.9:1, `--text-3 #A2B0C6` ≈5.5:1 — запас есть.

**D3.7 — `!=` deny-list tier C и линза не затрагиваются.** `[data-glass="a"]::before` и deny-list §9 остаются; на shell-панели `data-glass="a"` продолжает работать (линза поверх shell-подложки). Перф-кап `UI_LENS_MAX_NODES` и `UI_GLASS_TIER_OVERRIDE` сохраняются.

**D3.8 — флаг.** `UI_SHELL_GLASS_V2` (env-only, default **ON**): OFF → shell возвращается к общему `--glass-bg`/карточным токенам (поведение до HOTFIX7) без редеплоя.

---

### D4. Shell-выравнивание: header / sidebar / mobile (UPD 5)

**D4.1 — header без наезда.** Двухстрочная компактная композиция (hotfix6 D5) сохраняется под `UI_HEADER_COMPACT_V2`. Header — `--shell-bg-strong` (плотный), поэтому контент при скролле не «просвечивает грязно»; `--header-h` (ResizeObserver) остаётся единственным источником резерва (`scroll-padding-top` + при необходимости `padding-top` контента). Элементы строк (навигация/заголовок/⛶ / селектор/бейдж/аватар/роль) не перекрывают контент и нативные кнопки; при нехватке ширины — `ellipsis`/перенос, без горизонтального скролла.

**D4.2 — sidebar/topbar как единый shell-слой.** `.app-sidebar` (≥1200), `.app-drawer` (768–1199), `.bottom-nav`/`.more-sheet` (<768) — один набор `--shell-*` (тон/граница/радиусы/глубина/blur) → визуально цельный слой, отличимый от карточек. Drawer на 768–1199 корректен; `padding-bottom` учитывает safe-area/offset.

**D4.3 — mobile safe-area / chrome / нижний bar / fullscreen.** Сохраняются: `env(safe-area-inset-*)`, `--tg-safe-area-inset-*`, `--tg-content-safe-area-inset-*`, `viewport-fit=cover`, `--tg-viewport-bottom-offset` = max трёх инсетов (ADR-1025-12 D3), порядок навигации hotfix4/F1, fullscreen-sync **ADR-1024-24**. Ничего не уходит за экран: `rect.bottom <= innerHeight+1` (и `<= stableHeight+1` при симулированном баре).

**D4.4 — флаг.** `UI_SHELL_LAYOUT_V2` (env-only, default **ON**): OFF → прежний механизм высот/выравнивания (до HOTFIX7). Обоснование: полная геометрия fullscreen **не воспроизводится headless** и является самым рискованным изменением — нужен независимый откат без затрагивания glass/heartbeat.

---

### D5. Совместимость, инварианты, AMEND-карта (UPD 6)

**D5.1 — сохраняется без изменений:** Δ DDL = 0; Δ каталога = 0; CSP/zero-build (`script-src 'self'`, без CDN/data-URI/новых зависимостей); запрет WebGL (Canvas 2D/CSS-анимации разрешены); R17/R18 (без секретов/сырых значений в логах/отчётах; `current_task.md` untracked и не коммитится; теги/бэкапы/`stash@{0}` не удаляются); IA F1 (маршруты/меню/порядок навигации); write-path F0 `persistItems`; store-контракт F4 §37–§42; deny-list tier C; fullscreen-sync ADR-1024-24; нативные кнопки Telegram + `--header-h`; фон §10 и палитра §8 (значения `--surface-*`/`--text-*`/`--teal-*`/`--warn`/`--err`).

**D5.2 — AMEND-карта (полная — в ADR-1025-13):**

| Ранее | Действие | Что именно |
|---|---|---|
| **ADR-1025-12 D2** (стекло панелей = `--glass-bg`) | **AMEND → ADR-1025-13 D3** | shell получает **отдельные** `--shell-*` (graphite), header — `--shell-bg-strong`; blur/saturate/тень/blur-слой панели отличаются от карточек. Сохраняются: панели в glass-set (blur), AA-гарантия, `@supports`-фолбэк, deny-list |
| **ADR-1025-12 D4** (визуал heartbeat: синусоида+импульс) | **AMEND → ADR-1025-13 D2** | меняется **только рендер** (`_hbDraw` → ECG sweep-wipe + glow/дыхание). Сохраняются: Canvas 2D+rAF, телеметрия 30 с без нового поллера, state-machine/EMA/гистерезис/dwell, `missing≠bad`, UNKNOWN, «без выдуманного BPM», тултип, `UI_HEARTBEAT_CANVAS_ENABLED` OFF → legacy SVG, lifecycle, reduced-motion, C1 |
| **ADR-1025-9 D2** (значения токенов/уровни glass) | **Уточнение → ADR-1025-13 D3** | добавлен shell-слой `--shell-*`; карточный `--glass-bg` и §8-палитра **не меняются**; фон §10 (D3 ADR-1025-9) не отменяется |
| ADR-1025-12 **D1**, **D3**, **D5** | **НЕ отменяются** | foreground-линза/feature-detect; `computeBottomOffset = max`; нативные кнопки/`--header-h`/fullscreen-sync |
| ADR-1024-24 (fullscreen-sync) | **НЕ отменяется** | источник истины — TMA |
| ADR-1025-8/hotfix4, ADR-1025-10/F3, ADR-1025-1/F1 | **НЕ отменяются** (если геометрия нижнего bar не меняется) | порядок навигации, `viewport-fit=cover`, семантика селектора, IA |

**D5.3 — env-only флаги (default ON, вне `param_catalog`, Δ каталога = 0, доставка через `GET /api/me.ui_flags`):**

| Флаг | Тип | Default | Смысл / откат |
|---|---|---|---|
| `UI_SHELL_GLASS_V2` | `ClassVar[bool]` | ON | OFF → shell на общих карточных токенах (откат D3) |
| `UI_HEARTBEAT_PREMIUM` | `ClassVar[bool]` | ON | OFF → текущий canvas-рендер (синусоида+импульс) (откат D2) |
| `UI_SHELL_LAYOUT_V2` | `ClassVar[bool]` | ON | OFF → прежние высоты/выравнивание (откат D1/D4) |

Добавляются **аддитивно** в `config/settings.py` (рядом с блоком hotfix6, `:695-714`) и `web/api/routes.py::ui_flags` (`:383-392`), документируются в `.env.example`. Каталоговые ключи **не вводим**. Progressive delivery не применяется (один прод, прецедент §53–§58).

**D5.4 — F0/F4-контракты.** `persistItems`/`saveState`/`notify` (F0) и store-контракт F4 §37–§42 не трогаются — правки ограничены `web/**` (+ `config/settings.py`, `web/api/routes.py` — аддитивно) и тестами.

---

## 5. Interfaces / data contracts

- **CSS-токены:** новые `--shell-*`, `--shell-h`, `--card-shadow` (значения — D1/D3). `--shell-h` — базовый `100vh` + `@supports`-апгрейд до `min(100dvh, var(--tg-viewport-stable-height, 100dvh))` (реальный фолбэк, D1.1-review-F-2). Потребители: shell-панели, `.app-shell`, `.scroll-area`, карточки. `data-glass="a"/"c"`, `data-glass-tier/reason/downgraded` — без изменений.
- **JS-публичные (без смены сигнатур):** `_hbDraw(ts)` (новый рендер), `_heartbeatTransition(sample, prev)`, `heartbeatSample()`, `_applyHeartbeatSample(sample)`, `startHeartbeatCanvas/stopHeartbeatCanvas/_hbFrame/_hbScheduleDraw` — семантика сохраняется; добавляются **приватные** helper-функции рисования (ecg-форма, sweep, glow).
- **`GET /api/me.ui_flags`:** аддитивно `UI_SHELL_GLASS_V2`, `UI_HEARTBEAT_PREMIUM`, `UI_SHELL_LAYOUT_V2` (bool).
- **Telegram-интеграция:** `computeBottomOffset()` (`telegram-init.js`) и `--tg-viewport-bottom-offset` — контракт неизменен; fullscreen-sync (ADR-1024-24) — неизменен.
- **Инструмент:** `tools/ui_round1025_matrix.py` — новые пробы (см. §7.2).

---

## 6. Observable behavior и failure cases

| Сценарий | Ожидаемое | Failure (детект) |
|---|---|---|
| Normal / desktop | header/сайдбар/main/bottom-nav стабильны; карточки тоньше shell; heartbeat виден и анимирован | горизонтальный скролл; heartbeat отсутствует; shell == карточки по тону |
| Fullscreen / desktop | ничего не пропадает/режется; heartbeat виден; shell ровно по видимой области | обрезка низа; «прыжок» высоты; heartbeat вне вьюпорта |
| Tablet (768–1199) | drawer-навигация, shell цельный, без наездов | drawer за экраном; наезд header на контент |
| Mobile regular | safe-area, bottom-bar в экране, heartbeat читаем | bottom-nav ниже `innerHeight`; heartbeat обрезан |
| Mobile fullscreen / TMA WebView | всё видимо, нативные кнопки не сдвинуты, heartbeat виден | скрытие heartbeat; сдвиг нативных кнопок; грязное затемнение |
| Состояния heartbeat | HEALTHY/WARNING/CRITICAL/UNKNOWN визуально различимы с первого взгляда; при отсутствии данных — UNKNOWN, не «0» | выдуманный BPM; «линия+точка»; state не читается |
| `prefers-reduced-motion` | статичный корректный кадр в цвете состояния | анимация продолжается |
| `UI_*` OFF | каждая область откатывается независимо, без редеплоя | откат затрагивает другие области; каталог изменён |
| Нет `backdrop-filter` | shell/карточки → плотный фолбэк, раскладка/контраст сохранены | прозрачность/нечитаемость |

---

## 7. Security / privacy / acceptance

### 7.1 Security & privacy (R17/R18)
- В логах/отчётах/маркерах — только числа/флаги/классы, без секретов, сырых значений, контента и URL с ключами.
- CSP/zero-build: inline `<svg>`-фильтр остаётся единственным; **data-URI и внешние ассеты для текстуры/specular не используются** (CSS-градиенты). WebGL отсутствует.
- `plans/current_task.md` не коммитится/не изменяется; теги/бэкапы/`stash` не удаляются (R18).

### 7.2 Обязательная приёмка UPD 6 (T-2681…T-2683)
**Playwright-матрица 5 режимов** (desktop normal, desktop fullscreen, tablet, mobile regular, mobile fullscreen) + скриншоты. В `tools/ui_round1025_matrix.py` добавляются:
- **режим fullscreen** (стаб `Telegram.WebApp.isFullscreen=true` + `fullscreenChanged`) и проверка `.app-shell.fullscreen-mode`;
- **видимость heartbeat** во всех режимах: `.hb-canvas` есть, `visible`, `rect.h ≥ 1`, rect внутри вьюпорта; `hbState` присутствует;
- **разделение shell/карточек по вычисленным токенам:** computed `background-color`/`border-color`/`box-shadow` у shell-панелей **не равны** карточным; `--shell-bg` существует и `≠ --glass-bg`;
- **отсутствие виньетки/грязного затемнения:** `body::before` opacity ≤ 0.32; alpha `--glass-shadow`/`--shell-shadow` ≤ порога; `backdrop-filter: url(` отсутствует;
- сохранение существующих проб (overflow, `rect.bottom <= innerHeight+1`, AA, glass allow/deny, reduced-motion).
- При отсутствии `playwright` в окружении — **Info, не блокер** деплоя (прецедент §57/§58); результаты — `plans/reports/round1025_hotfix7_ui_report.md`.

**Live-гейт T-2682 (владелец, реальный Telegram WebView):** mobile fullscreen внутри Telegram — heartbeat виден, header цел, glass качественный, sidebar/topbar серые и отделены, ничего не съезжает. Автоматизации недоступно — фиксируется как открытый live-гейт с инструкцией.

### 7.3 Тест/маркеры (T-2684/T-2685)
- Обновление/добавление маркеров (`tests/js/**`, webapp/frontend-тесты) **одним коммитом** с кодом: наличие `--shell-*`/`--shell-h`/`--card-shadow`; **реальный фолбэк `--shell-h`** (base `100vh` всегда + dvh/min()-апгрейд строго в `@supports`; отсутствие висячего `--shell-h:100dvh`; эмуляция «старого WebView» в пробе `F7_PROBE_JS`/`f2ShellH`); отсутствие «линии+точки» (нет `pulseX`-паттерна); presence `ecg`-рендера/`sweep`; HEALTHY на `--ok` (единство с бейджем, F-3); лестница `glowAlpha`/`glowScale` по состояниям (F-4); флаги; `node --check web/app.js` + `telegram-init.js`.
- Регресс: целевой pytest, `Δ DDL=0`, `Δ каталога=0` (459/98/96/21/418), `git diff --check`, отсутствие WebGL, нативные кнопки/`--header-h`/fullscreen-sync, IA, `persistItems`, store-контракт F4.

---

## 8. Test / deployment / rollback (пропорционально риску)

- **Подход:** маленький, но полный regression-набор (P0 hotfix): unit (state-machine/`computeBottomOffset` — уже есть), marker/regex, Playwright-матрица 5 режимов + 10 вьюпортов, AA-таблица, `node --check`, инварианты. Часть эффекта — **только live** (WebView), фиксируется как гейт.
- **Deploy:** bump `APP_VERSION` `2.58.7 → 2.58.8` + cache-bust `?v=` (`config/settings.py`, `README.md`, `web/index.html`); рестарт-требование отметить. Артефакт — `deployment.md` (VERIFIED/NOT_APPLICABLE) + `plans/workflow_state.md`.
- **Rollback:** hard — тег `pre-round1025-hotfix7` (T-2658) + `git revert` коммитов пакета + возврат версии/`?v=`; soft — env-only `UI_SHELL_GLASS_V2=false`, `UI_HEARTBEAT_PREMIUM=false`, `UI_SHELL_LAYOUT_V2=false` (или `UI_HEARTBEAT_CANVAS_ENABLED=false` → legacy SVG). Бэкапы/теги/`stash@{0}` не удалять (R18).

---

## 9. Risks

| Риск | Оценка | Митигация |
|---|---|---|
| Полная геометрия fullscreen **не воспроизводится headless** | высокий | D1 устраняет класс причин (единый `--shell-h`, явные режимы); матрица + **live-гейт T-2682**; независимый откат `UI_SHELL_LAYOUT_V2` |
| Перф-стоимость glow/`shadowBlur` на слабом WebView | средний | cap radius/DPR, кэш сетки, один rAF, пауза по hidden; замер FPS в live-гейте; откат `UI_HEARTBEAT_PREMIUM` |
| Регрессия AA при смене плотности shell | средний | новая AA-таблица worst-phase; при провале — повышение плотности, не палитры; запас по аналитической оценке |
| «Косметический blur» вместо премиального эффекта (риск приёмки) | средний | рецепт D3 (6 составляющих + глубина), ECG-монитор D2, приёмка скриншотами у владельца |
| Рассинхронизация эталонов тестов при смене визуала | низкий | обновление маркеров **атомарно** с кодом (T-2685) |
| Изменение фона §10 воспринимается как отмена ADR-1025-9 | низкий | меняется только opacity wash/«грязь», механика/цвета/длительности сохранены; AMEND-карта явная |

---

## 10. Open questions / decisions

- Решения **(a)–(e)** @PM закрыты: (a) shell-токены — новые `--shell-*` (D3.1); (b) глубина/AA — D3.4/D3.6; (c) метрика→визуал — D2.2 на базе `_heartbeatTransition`/`heartbeatSample`; (d) механизм высоты — `--shell-h` + два режима (D1.1/D1.2); (e) причина исчезновения heartbeat — класс причин по P4/P5, live-гейт.
- **`ARCHITECT_DECISION_REQUIRED` не требуется**: все выборы — технические и решаются в рамках зафиксированных инвариантов; user-owned tradeoff не обнаружен.
- Вопрос **(f)** (порядок продолжения после HOTFIX7) — зона @PM/UPD 7 (`round1025_tz_remaining_audit.md` §7–§8: возврат к F4).

---

## 11. Артефакты

- `plans/features/hotfix7-shell-glass-heartbeat-round1025/spec.md` (этот файл)
- `plans/features/hotfix7-shell-glass-heartbeat-round1025/adr-1025-13-shell-glass-heartbeat-v2.md`
- `plans/features/hotfix7-shell-glass-heartbeat-round1025/tasks.md` (T-2658…T-2694; соответствует spec — расхождений, требующих возврата @PM, нет)
- Ожидаемые (позже): `plans/reports/round1025_hotfix7_contrast.md`, `plans/reports/round1025_hotfix7_ui_report.md`, `plans/reports/round1025_hotfix7_scanner_audit.md`, `plans/archive/hotfix7-shell-glass-heartbeat-round1025/deployment.md`, интеграция — `plans/ARCHITECTURE.md` §59 (T-2688).
