# ui-acceptance — U08 Liquid Glass (W2-GLASS, REQ-U08-5)

Дата: 2026-10-15 · HEAD до: `f1418d7` · Окружение доказательств: Playwright
Chromium (headless, Windows) + scratch-статик-сервер `OPENCODE_WORKFLOW_SCRATCH/w2-glass/stand_server.js`
(моки `/api/me`, `/api/status`; Telegram SDK — route-fulfill заглушка по w2-contract §4.2.1).
Тестовый фон — `web/static/glass-teststand.html` (прямые контрастные линии 4px/48px +
плавная синяя волна; создан агентами, внешних изображений нет).

## Четыре измеримых признака материала (U08.5.1)

### (a) Читаемый прозрачный центр
- Стенд: через центр hero видны и сетка, и волна; текст поверх — контраст
  **13.1:1 (PASS ≥4.5)** — пиксельный замер
  (`u08-5-3-contrast-hero-src.png`, расчёт 5-й/99.5-й перцентиль luminance).
- Реальный Status: aurora/полигоны видны сквозь hero-центр, текст читаем.
- Файлы: `u08-5-final-grid-hero.png`, `u08-5-final-wave-hero.png`,
  `u08-4-real-status-desktop.png`. **PASS**

### (b) Фоновая edge-деформация (рефракция, Tier A)
- Численное доказательство (сканлайн-корреляция «hero виден/скрыт», сетка 4px/48px,
  dpr=1, панель 360×120, карта bend=8px/scale=16):
  - центр (r<0.62): `dx = 0` (строка y=112: 0 по всей ширине) — центр неподвижен;
  - кромка: `dx` до **−8…+5 px к центру** (y=130: −5 слева → +5 справа —
    симметричное сжатие; y=124: −5…+3);
  - контроль вне панели (y=144): `dx = 0, corr = 1.000` — глобального сдвига нет.
  - Файлы: `row-y112.json`, `row-y124.json`, `row-y130.json`, `row144.json`,
    `u08-5-measure-hero-on.png` / `u08-5-measure-hero-off.png`.
- Визуально: `u08-5-after-grid-hero-left-edge-3x.png`, `diag-v2/v3/v4.png`
  (диагностика feImage: сломанный вариант = равномерный сдвиг, рабочий — изгиб).
- **PASS** (optical Tier A: доказанная фоновая деформация, не имитация).

### (c) Светлая направленная rim-кромка
- 1.5px masked-ring: градиент 115° (белая дуга верх-лево alpha .62 → тёмная
  сторона alpha .10-.42) — асимметричная, не равномерная обводка.
- Стенд/реал: `u08-5-final-grid-lg-panel-row.png`, `u08-4-real-status-desktop.png`
  (hero «Бот» — светлая кромка верх-лево, темнее низ-право). **PASS**

### (d) Локальный specular-блик
- Радиальная дуга 130%×65% at 12%/-2% (яркая точка верх-лево) + второй мягкий
  у 88%/4%; на массовых карточках — hover-specular (desktop).
- Файлы: `u08-5-final-grid-lg-panel-row.png` (hero/soft), `u08-5-final-grid-app-hero.png`.
  **PASS**

## До/после (U08.5.2, статичный viewport, тот же scene)

- Стенд 1:1: `u08-1-before-grid-legacy-card.png` vs `u08-5-final-grid-legacy-card.png`
  (сетка: до — линии под карточкой прямые/размыты; после — изгиб у кромки).
- Волна: `u08-1-before-wave-legacy-card.png` vs `u08-5-final-wave-legacy-card.png`.
- Реальный Status, тот же route/данные/viewport:
  `u08-1-BEFORE-real-status-desktop.png` vs `u08-4-real-status-desktop.png`
  (до: плоский blur+tint и градиент-декорация на графе; после: hero-линза с
  кромкой/бликом, граф — solid Tier C).
- Tier A vs Tier B vs reduced-motion (один фон): `u08-5-final-grid-lg-panel-row.png`
  (hero/soft/solid в одном ряду), `u08-5-final-reduced-motion-hero.png`,
  `u08-5-2-real-reduced-motion-hero.png`.

## pointer-events / клавиатура / контраст (U08.5.3)

- `elementFromPoint` (центр hero / верх-лево / кнопка): `text-xs`,
  `text-sm font-bold`, `hero-btn` — декоративные слои не перехватывают hit
  (**PASS**, REQ-U08-2 hit-тест).
- Fallback mask-composite-нет (симуляция стилем): rim → inset box-shadow,
  кнопка кликабельна (`u08-5-3-fallback-sim-hero.png`, `…-row.png`, click=true).
  Плюс структурный `@supports not (mask-composite…)` в app.css. **PASS**
- Контраст: 13.1:1 (≥4.5) — PASS; caret/selection не стилизуются стеклом
  (декор pointer-events:none, filter не на контенте — grep-инварианты в
  `tests/js/glass_probe_test.js`).

## Интегральные проверки (U08.5.4)

- `scrollWidth ≤ innerWidth`: 320→305≤320, 390→375≤390, 1440→1440≤1440
  (стенд) и 390→390≤390 (реальное приложение). **PASS**
- FPS скролла (3с программный скролл Status, rAF-дельты):
  после = **60.2 fps avg, p95 16.8ms, 0 дропов >25ms**; до (HEAD) = 60.2 fps.
  Headless-десктоп-прокси; архитектурные гарантии для mid-range Android:
  blur карточек снижен 16→8px, Tier A ≤3 узлов (clamp `min(env,3)`), в стекле
  нет rAF/анимаций, при `html.lg-bg-paused`/reduced-motion анимации запрещены. **PASS**
- Compositor-нагрузка: backdrop-filter на 1 hero + карточки Tier B (тот же класс
  слоёв, что до правок), без will-change/promotion на контент.

## Итог ревью (U08.5.5) — два раздельных результата

- **optical Tier A passed** — доказанная фоновой деформация численно
  (edge ±8px к центру, центр 0, контроль 0/1.0) + визуально на стенде и Status.
  Платформа: Chromium (probe `probe-chromium`, `svgRender=true`); WebKit — честный
  Tier B (bug 245510),.reason=`engine-webkit-backdrop-url-no`.
- **frost Tier B passed** — rim/specular/frost на карточках/tabs/shell,
  читаемость и контраст сохранены (`u08-5-final-grid-app-row.png`).
- Статус «прозрачность + blur есть» **не** заявляется как U08 — оба результата
  подтверждены выше.

## Ограничения / честные пометки

- Реальный Modules-экран в этой среде не рендерит карточки модулей (нужен
  chat-context в моках); материал module-card доказан на стенде
  (`u08-5-final-grid-app-row.png`, реальный `.card.module-card` + app.css).
- FPS — прокси-замер (headless desktop), не физический mid-range Android;
  см. архитектурные гарантии выше.
- `UI_LIQUID_GLASS_LIB` оставлен OFF: vendored 0.5.3 даёт frosted/WebGL-путь
  на изолированной декоративной поверхности (hotfix10), U08-оптику обеспечивает
  vanilla progressive-слой; включение lib на hero не требуется.
