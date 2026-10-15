# W2-GLASS — отчёт лейна (U08: настоящий optical Liquid Glass)

Лейн: W2-L3 GLASS · HEAD baseline: `f1418d7` · Дата: 2026-10-15
Статус Tier A: **optical Tier A passed (Chromium, доказано численно)** ·
Tier B: **passed** · Tier A на WebKit: честный Tier B (PENDING-PLATFORM по
движку, не по недоделке — bug 245510).

## 1. Аудит ДО правок (U08.1, REQ-U08-1-AUDIT)

Зафиксировано на HEAD до CSS-правок (стенд `glass-teststand.html` с легаси-репликой +
реальное приложение с моками):

- Карточки `[data-glass="a"]`: `blur(16px)+saturate(140%) + rgba-tint`; сетка/волна
  под карточкой **не изгибаются** (`u08-1-before-grid-row.png`).
- «Линза» была `filter:url(#lg-lens)` (feTurbulence) на `::before` **с собственным
  градиентом** — искажение случайного градиента самой карточки, а не подложки =
  gradient decoration, не refraction (классификация в `ui-acceptance.md` §(b)).
- `[data-glass="a"]` висел также на tabs-панели oversight и на **графах связей**
  (cognition-graph ×2) — против U08.4a («граф — Tier C/Solid»).
- Vendored `liquidglass.core.0.5.3` (UI_LIQUID_GLASS_LIB=OFF): по hotfix10-контракту
  монтируется только на декоративный `[data-glass-surface]` и честно отдаёт
  `frosted` без предоставленного WebGL-источника; прод-default OFF оправдан
  (hotfix10: белые frosted-подмены на функциональных целях). Решение: **флаг
  оставлен OFF**, U08-оптику несёт vanilla progressive-слой (ниже).
- `_liquidGlassSupported` = `CSS.supports('filter','url(#…)')` — формальный true без
  доказательства рендера (WebKit bug 245510: backdrop-filter url() рендерится в
  Chromium и НЕ рендерится в Safari 16/TP при формальном passing parse).
- Источники (research-gate): bugs.webkit.org 245510 (Chromium — работает, Safari —
  нет, Firefox — не подтверждён), техника `backdrop-filter: blur() url(#map) +
  feImage-PNG` (liquid-glass-react README).

## 2. Что реализовано

### 2.1 Render-probe `web/static/glass-probe.js` (новый, REQ-U08-1-PROBE)
- `window.__GlassProbe.probe() → Promise<{tierA, reason, engine, svgRender,
  backdrop, ms}>`; кэш за сессию; без Vue; CSP-safe.
- Реальный рендер-тест: одноразовый SVG-фильтр `#lg-probe-disp`
  (feFlood-константа R=0.7529 + feDisplacementMap scale=32 → сдвиг ≈8px) рисуется
  на canvas поверх детерминированной полосатой мишени (период 7px — **не кратен
  сдвигу**, иначе diff≈0); пиксельная сверка: B≠A и B ≈ A, сдвинутый на 8px.
- Engine — capability-сигнал семейства (`window.chrome` / `InstallTrigger`),
  не UA-парсинг. `tierA = svgRender && backdrop && engine==='chromium'`;
  WebKit → reason `engine-webkit-backdrop-url-no`; чистая функция решения
  `decide()` покрыта Node-тестами (матрица 7 кейсов).
- Загружен ДО glass.js/app.js (index.html, порядок §1.3.4 контракта).

### 2.2 Слоистая модель `.lg-panel` (U08.2, имена §3.4 заморожены)
- CSS: `.lg-panel`, `__backdrop/__tint/__rim/__specular/__content`,
  `--hero/--soft/--solid`, `.lg-mini-lens` — новая секция `/* ═══ W2-GLASS ═══ */`
  (append-only) + правки в собственных зонах (tokens `--lg-*` — ключи `--glass-*`
  не переименовывались; `[data-glass]`-рецепты; downgrade; @supports-фолбэки).
- Атрибутивный путь `[data-glass]` — та же z-order-семантика псевдослоями
  (разрешено ТЗ U08.2): root=backdrop (backdrop-filter), `::before`=tint+sheen
  (z:-1), `::after`=rim-ring+specular+chromatic fringe (masked ring 1.5px).
- `filter:url()` **нигде** кроме backdrop-цепочек Tier A — grep/тест-инварианты
  (`glass_probe_test.js`: `.lg-panel__content` без filter, html без filter:url,
  url(#lg-lens) только с backdrop-filter).
- mask-composite fallback: `@supports not (...)` → rim через inset box-shadow;
  скриншот fallback-симуляции + клик-тест — `u08-5-3-fallback-sim-*` (U08.5.3).

### 2.3 Настоящая линза (U08.3a–c) — и как её почти потеряли
- Фильтр `#lg-lens` (имя заморожено) переписан: `feImage` PNG-карта смещения
  256×256 (R=X, G=Y; rect-норма, центр r<0.62 неподвижен, smoothstep-набег
  **bend=8px к центру**; генератор `OPENCODE_WORKFLOW_SCRATCH/w2-glass/
  gen_lens_map.js`, Paeth, 6.7KB) + `feDisplacementMap scale=16`, sRGB.
  Применяется как `backdrop-filter: blur(5px) saturate(140%) url(#lg-lens)`
  — рефракция **заднего** слоя (Chromium).
- **Root-cause ловушка (зафиксирована диагностикой `lg-diag.html`, удалён
  после прогона)**: `feImage width="100%"` внутри скрытого `<svg width=0>`
  резолвится в нулевой viewport → карта прозрачна → равномерный сдвиг
  `scale*(0−0.5) = −8px` по всему пятну (сначала численно и поймали:
  «линза» без профиля). Лечение: явный subregion `x/y/width/height` +
  **JS-синхронизация под фактический border-box каждого tier-A узла**
  (`app.js::_syncLensFilters`: пул ≤3 клонов фильтра, реюз по размеру ±2px,
  resize через существующий `_lgResizeObserver`; inline `backdrop-filter`
  только на tier-`a`, на downgraded — снятие inline → CSS frost-fallback).
- data:-URI карты (не внешний файл): feImage по внешнему URL в связке
  backdrop-filter надёжнее с inline; CSP `img-src data:` разрешён; +8.9KB в
  index.html.
- Probe-гейт: до первого успешного probe узел живёт как Tier B (frost);
  `probe-pending` → перекур reconcile по готовности.

### 2.4 Tier-карта экранов (U08.4, значения `data-glass*` — эксклюзив лейна)
| Экран/узел | было | стало |
|---|---|---|
| Status hero `.status-hero` | a | **a** (Tier A, единственный hero; `probe-chromium`) |
| oversight-tabs | a | **b** (chrome) |
| oversight overview/autobudget блоки (×3) | a | **b** |
| cognition-graph (×2) | a | **c** (solid поверх фона — надписи не плывут) |
| статус-логи, logs-link | c | c |
| Массовые карточки `.card/.module-card/…` | (base) | Tier B материал: blur 16→**8px**, inset-кромки, hover-specular |
| Шапка/sidebar `[data-glass="shell"]` | shell | shell (материал не тронут — property-split HS-3; снят только бессмысленный `filter:url` с sheen) |
| Popover «Ещё» / ⛶ | — | словарь для SHELL/FULLSCREEN: `c` (solid) / `.lg-mini-lens` (CSS-класс готов, файлы FULLSCREEN не правились) |

### 2.5 Перф/деградация (U08.3e)
- Никаких rAF/анимаций в стекле; `html.lg-bg-paused` + `prefers-reduced-motion`
  запрещают анимации декора; reduced-motion/low-end (`deviceMemory<4` или
  `cores≤2`) → tier A выкл (reason `reduced-motion`/`low-end`), **стекло не
  убивается** (frost+static rim/tint остаются) — проверено live
  (`heroTier="b"`, `reason="reduced-motion"`).
- Кап Tier A: `min(UI_LENS_MAX_NODES, 3)`; дефолт флага 6→**3**
  (`config/settings.py`, значение glass-флага — в скоупе).
- FPS: до 60.2 / после 60.2 avg (p95 16.8ms, 0 дропов>25ms, 3с скролл-тест
  Status) — headless-desktop прокси; ографичения в ui-acceptance.md.

## 3. Маркеры тестов — замены по правилу w2-contract §1.2

| Тест | старый маркер | новый маркер |
|---|---|---|
| round1025_design_tokens_test §5 | feTurbulence+feGaussianBlur в #lg-lens | feImage + data:image/png;base64 карта + glass-probe.js до app.js |
| round1025_design_tokens_test §6 | `css.supports('filter','url(#lg-lens)')`; fake `_liquidGlassSupported` | `__GlassProbe`+`_probeTierA`; fake `_probeTierA`; кап 3; reasons `svg-render-failed`; вне-канон `CSS.supports` запрещён |
| round1025_hotfix6 §A | «нигде нет backdrop url-фильтра (§9)»; foreground-линза ::before; radial-маска; дефолт капа 6 | backdrop url только в app.css (tier-A цепочки); ::before без filter; mask-composite ring; дефолт 3 (U08.3d SUPERSEDE §9) |
| НОВЫЙ tests/js/glass_probe_test.js | — | CONTRACT: decide()-матрица ×7, API-форма, порядок загрузки, запреты filter:url, файлы стенда/карты |

Полный tests/js-свип: все зелёные, кроме ПРЕДСУЩЕСТВУЮЩЕГО падения
`round1025_hotfix6` в секции **D (toggleFullscreen — зона FULLSCREEN-лейна)**:
воспроизведено на чистом HEAD (`git stash` прогон, exit 1 до моих правок).

## 4. Evidence-пути (w2-evidence-glass/)

`ui-acceptance.md` (4 признака + PASS/FAIL, сводные числа) · before:
`u08-1-before-{grid,wave}-*`, `u08-1-BEFORE-real-status-desktop.png`,
`…-mobile-390.png` · after: `u08-5-final-*`, `u08-4-real-status-{desktop,mobile}.png`
· измерения: `row-y112/124/130.json`, `row144.json`, `bend2-result.json`,
`u08-5-measure-hero-{on,off}.png` · fallback: `u08-5-3-fallback-sim-*` ·
reduced-motion: `u08-5-final-reduced-motion-hero.png`,
`u08-5-2-real-reduced-motion-hero.png` · контраст: `u08-5-3-contrast-hero-src.png`
(13.1:1).

## 5. Честный статус и риски

- **Tier A (Chromium): PASSED.** Численно: центр 0 / кромка ±5..8px к центру /
  контроль 0 corr=1.0; визуально 3x-кропы. Не «прозрачность+blur».
- **WebKit/iOS TMA: Tier B (PENDING-PLATFORM).** probe даёт
  `engine-webkit-backdrop-url-no`; fallback = frost+rim+specular (не пустое
  стекло). Если Apple починит url()-backdrop — tier A включится сам после
  обновления `_test.decide` (одна строка + проверка на устройстве).
- **Не проверено физическим mid-range Android** (среда недоступна): FPS —
  headless-прокси; компенсации — blur 8px, ≤3 линз, no-rAF, пауза фона.
- Live VERIFIED на реальных Telegram-клиентах — Wave 4 (по контракту W2).
- Инцидент (исправлен): промежуточный PowerShell-конвейер `-replace` повредил
  кодировку web/index.html; файл восстановлен из git, правки внесены повторно
  кодировкобезопасно (edit-инструмент/Node-fs), дифф проверен (29+/18− до
  сплайса карты), Node-маркерные тесты зелёные. Урок: только fs-сплайсы.

## 6. Churn (файлы лейна)

- NEW: `web/static/glass-probe.js`, `web/static/glass-teststand.{html,css,js}`
  (fixture, не маршрут), `web/static/vendor/lg-lens-map.png` (6.7KB),
  `tests/js/glass_probe_test.js`
- EDIT: `web/index.html` (SVG #lg-lens + data-URI карты, +glass-probe.js,
  data-glass значения ×7), `web/static/app.css` (токены --lg-*, recipes a/b/shell,
  @supports-фолбэки, W2-GLASS секция), `web/app.js` (glass-блок 18045–18252:
  probe/tier/low-end/_syncLensFilters; дефолт капа 3), `config/settings.py`
  (UI_LENS_MAX_NODES default 3 + комментарий), тест-маркеры (§3).
- НЕ тронуто: polygon-background.js / aurora-* / фоновые секции CSS (фриз
  владельца — подтверждено), telegram-init.js, fullscreen-policy.js,
  header-геометрия/mobile-topnav (SHELL), fullscreen-блок (FULLSCREEN),
  `UI_LIQUID_GLASS_LIB` (остался False), services/backend.
