# WIN-GLASS-P0 — отчёт по P0-хотфиксу (Windows fullscreen + Android Liquid Glass)

Дата: 2026-10-18. Кандидат: рабочее дерево поверх `a891b721` (+ ledger `d98e55c6`),
**без коммита и деплоя** (релиз — отдельным лейном после ревью).
Границы: `web/static/glass-refraction.js` (новый), `web/static/glass-probe.js`,
`web/app.js`, `web/static/app.css`, `web/index.html`, тесты, `tools/`.
Не тронуты: `polygon-background.js`, карта линзы `#lg-lens`/`lg-lens-map`, токены
`--lg-*`, SOUL-1/Summary/CFG, чужие файлы лейнов.

---

## 1. Windows Telegram Desktop — геометрия fullscreen

### 1.1 Что видит владелец

Mini App при Launch Mode = Fullscreen открывается «автоматически», но окно
занимает часть монитора, смещено за края, панель задач видна, перетаскивание и
изменение размера не помогают.

### 1.2 Причина — дефект клиента Telegram Desktop (Windows), не наш CSS

| Факт | Источник |
|---|---|
| Панель mini app **изменяет размер** до fullscreen, но **не перемещается** в origin экрана: уезжает за правый/нижний край, панель задач остаётся видимой, ввод смещён. Воспроизводится и на одном мониторе 1920×1080; клиент в отчёте — 6.9.3 x64 | [telegramdesktop/tdesktop#30963](https://github.com/telegramdesktop/tdesktop/issues/30963) (open, label bug) |
| Причина в коде клиента: `SeparatePanel::toggleFullScreen()` вызывает `showFullScreen()`; у frameless-окна на Windows применяется размер, а перемещение теряется (класс багов QTBUG-39537/86899; у media viewer в клиенте уже есть явный workaround) | описание issue #30963 + PR [desktop-app/lib_ui#342](https://github.com/desktop-app/lib_ui/pull/342) |
| Исправление (в `lib_ui`) по состоянию 21.08.2026 **не влито**; мейнтейнер уточняет, что первопричина может быть в самом клиенте (`WA_Moved`) — то есть фикс ещё в работе | PR #342 (open, merge-commit `b0edefd`), комментарии в #30963 |
| Смещение **пропорционально** позиции главного окна Telegram: ближе к левому верхнему углу → панель почти на месте; на втором мониторе → позиционируется верно | issue #30963 (шаги/наблюдения) |
| Наш веб-код управлять нативным окном не может: в Mini Apps API нет ни одной функции геометрии окна, есть только `web_app_request_fullscreen` / `web_app_exit_fullscreen` (два postEvent) | `web/static/vendor/telegram-web-app.js:2837-2850`; реестр методов [core.telegram.org/bots/webapps](https://core.telegram.org/bots/webapps) |
| Наш контур не деградировал: авто-выход из стартового fullscreen удалён (FS-HOTFIX 18.10), `window.moveTo/resizeTo`-хаков нет, кнопка ⛶ работает по факту SDK | `web/static/fullscreen-policy.js:1-63,649-670`; проверка D (см. §3) |
| `100vw/100vh`, safe-area и `--tg-*` описывают только WebView внутри панели; на размер нативного окна они не влияют | `web/static/telegram-init.js`, `web/static/app.css` (комментарии §2.3 контракта) |

**Итог:** это клиентский дефект (`showFullScreen` без перемещения). «Починить
окно из веб-кода» нельзя; можно подтвердить ограничение на клиенте и дать
рабочее обходное действие + подготовить точный баг-репорт/проверку фикса.

### 1.3 Что сделано на нашей стороне

- Подтверждено доказательствами, что мы не усугубляем: стартовый fullscreen не
  гасится (нет авто-`exitFullscreen`), нет попыток двигать/масштабировать
  нативное окно (проверка **D** e2e: `window.moveTo/resizeTo` отсутствуют).
- Полоса управления проверена на реальных байтах кандидата: кнопка ⛶ в потоке,
  при launch-fullscreen кнопка = «выход», второй `requestFullscreen` не
  отправляется, состояние не инвертируется (проверка **B**, сценарий FS).
- Админ-диагностика геометрии (§8, off by default) даёт владельцу точный
  снимок факта для баг-репорта: platform/SDK/`isFullscreen`/viewport/dpr/
  insets/rect кнопки и шапки/`slot`+`reason` и копирование одной кнопкой.

### 1.4 Что делать владельцу (точный рабочий обход)

1. **Обход на текущем клиенте (подтверждён апстримом):** перед входом в mini app
   перетащите главное окно Telegram в **левый верхний угол** монитора (или
   перенесите Telegram целиком на другой монитор) — тогда fullscreen-панель
   встаёт на место. Проверка: панель закрывает экран, панель задач скрыта,
   курсор/тапы не смещены.
2. **Обход «перезапуск окна»:** выйти из полноэкранного режима кнопкой ⛶
   (панель вернётся в оконный вид) и снова войти ⛶ из окна, которое уже
   находится в левом верхнем углу.
3. **Правильное лечение** — исправление клиента (`lib_ui` PR #342 / связанные
   #31041, #31114, #343). До влития и релиза ничего в mini app этого не решает.
   Проверить версию Telegram Desktop: `Настройки → (внизу) версия` / `About`.
4. **Вариант «не стартовать в fullscreen» (если нужен обходной UX):** BotFather →
   `/mybots` → ваш бот → `Bot Settings` → `Configure Mini App` → выбрать Main
   Mini App → пункт про режим запуска (Launch Mode: Compact / Fullscreen;
   название пункта в текущих версиях BotFather может отличаться). Быстрая
   A/B-проверка без BotFather — открыть mini app ссылкой с `?mode=compact`
   (документированный параметр).
   **Честная оговорка:** это не лечит баг, а лишь избегает автоматического
   fullscreen при открытии — при ручном нажатии ⛶ дефект вернётся (тот же код
   клиента). Влияние на мобильные: приложение будет открываться не на весь
   экран (пользователь сможет развернуть вручную) — это глобальное изменение UX
   для всех платформ, поэтому по умолчанию НЕ предлагается.

### 1.5 `PENDING_OWNER_E2E` — Windows (точный сценарий)

1. Открыть adminbot mini app из Telegram Desktop (Windows) с Launch Mode =
   Fullscreen.
2. Ожидаемо (баг не исправлен в клиенте): панель растянута, но смещена.
   Сделать диагностику: `Меню → диагностика геометрии ⛶` (доступна глобальному
   админу), скопировать снимок.
3. Перетащить главное окно Telegram в **левый верхний угол** монитора, повторить
   вход в mini app → ожидаемо: fullscreen занимает рабочую область монитора
   минус панель задач, без смещения ввода.
4. Проверить переключение: ⛶ = выход (панель возвращается в оконный вид), ⛶ =
   вход, закрытие панели системной кнопкой, перетаскивание/размер в оконном
   режиме.
5. Сообщить: версия Telegram Desktop, результат шагов 2–4, снимок диагностики.

---

## 2. Android — оптическая рефракция (было «только blur»)

### 2.1 Причина

| Факт | Источник |
|---|---|
| Наш Tier A рисовал рефракцию через `backdrop-filter: … url(#lg-lens)` (SVG reference filter) | `web/app.css:1578-1581`, `web/app.js::_syncLensFilters` |
| `url()` **внутри** `backdrop-filter` — только Chromium; WebKit его не рендерит (bug 245510), Firefox — нет, и это не гарантировано в WebView мобильных клиентов | WebKit bug [245510](https://bugs.webkit.org/show_bug.cgi?id=245510), [mdn/browser-compat-data#24110](https://github.com/mdn/browser-compat-data/issues/24110), [Fyrd/caniuse#7354](https://github.com/Fyrd/caniuse/issues/7354) |
| Проба не могла отличить «url() рендерится в backdrop» от «движок chromium»: композит DOM-слоя из страницы **измерить нельзя** — `ctx.drawImage` принимает только image/canvas/video/ImageBitmap/OffscreenCanvas/VideoFrame, но не DOM-элемент (на кандидате получен `TypeError: The provided value is not of type …`) | проверено на кандидате (см. `evidence/e2e/_results.json`, отладка в scratch) |
| Итог: на Android WebView стекло показывало blur/frost, а обещанного «оптического смещения» не было. **Честная граница:** реальный Android WebView агентам недоступен, поэтому RED построен на (а) документированных дефектах выше и (б) замере «без слоя смещения нет» в mobile-эмуляции; фактический вид на телефоне — `PENDING_OWNER_E2E` (§5) | директива владельца (симптом) + источники выше; замеры §2.3 |

### 2.2 Решение: слой преломления контролируемого фонового слоя

Новый модуль `web/static/glass-refraction.js` (IIFE, CSP-safe, без Vue):

- для подтверждённого Tier A мобильных клиентов (`platform = android|ios` по
  факту SDK, + доказанный `svgRender` из canvas-пробы) создаёт декоративный
  `<canvas class="lg-refract">` **внутри** стеклянной поверхности;
- в него копируется **только контролируемый фон** (`#polygon-background`,
  тот же seeded-кадр; живой DOM с текстом НЕ клонируется) и к нему применяется
  существующий SVG-фильтр линзы: `filter: blur(5px) saturate(140%)
  url(#lg-refract-lens-N)` — как `--lg-frost-hero` на desktop;
- поверх копии запекается **собственная подложка поверхности** (цвет+alpha из
  computed style), иначе слой «съедал» затемнение подложки и кромки становились
  ярче (замер: +23 % luma → −1.9 % после правки);
- слой маскируется **рамкой у кромок** (20 px solid + 46 px fade): преломление
  видно там, где карта линзы даёт смещение, центр остаётся спокойным и не
  перекрывает контент под стеклом;
- бюджет: ≤ 4 поверхностей, DPR-кап 1.5, обновление ~25 FPS, пауза при
  `document.hidden`/reduced-motion, пропуск заведомо непрозрачных подложек
  (alpha ≥ 0.7 — линза под ними не видна), идемпотентные `sync()/dispose()`;
- **ручки/фолбэки:** `?glassrefract=off|on`, `?glassrefractmax=N`,
  `window.__GlassRefraction.diagnostics()`; без источника фона/карты линзы —
  честный отказ (`reason`), без ложного заявления «рефракция есть».

Изменения в существующем коде:

- `glass-probe.js`: `decide()` теперь отдаёт `refractionLayer` (возможность слоя
  = `svgRender && backdrop`), Tier A для desktop Chromium сохранён; проба НЕ
  притворяется, что умеет мерить `backdrop-filter: url()`.
- `app.js`: `_applyRefractLayer()` — носитель оптики: `backdrop` (desktop,
  прежний путь) / `layer` (android|ios) / `null` (честный frost); разметка
  `data-refract-layer="on"` + `data-glass-reason="refract-layer"`;
  `_syncLensFilters` не дублирует `url()` на таких поверхностях;
  `_syncGlassRefraction()` держит слой в синхроне с фоном/видимостью.
- `app.css`: для `data-refract-layer="on"` поверхность остаётся на
  `var(--lg-frost-hero)` **без** `url()` (в т.ч. для `.lg-panel--hero` —
  специфичность перекрыта явно).
- Desktop (tdesktop/macos/web) — путь не изменён: там по-прежнему
  `url()` в `backdrop-filter`; слой не создаётся (`layers=0`, проверка B).

### 2.3 Что реально измерено (числа)

| Метрика (android-эмуляция 390×844, DPR 2, фон `?bgseed=20260923`, rAF фона на паузе) | Значение |
|---|---|
| Слой создан: поверхностей с `data-refract-layer="on"` / canvas-слоёв | 16 / **3** (бюджет ≤3 = hero-кап U08.3d, `UI_LENS_MAX_NODES`) |
| Остаточный `url()` в `backdrop-filter` у layer-поверхностей | 0 из 16 |
| Смещение линий на контрастном паттерне, левая кромка | **−26 device px (−13 CSS px)**, corr 0.92 |
| … правая кромка | **+32 device px (+16 CSS px)**, corr 0.97 |
| … центр поверхности | **0 px**, corr 1.0 |
| Шум OFF↔OFF (контроль) | 0 px, corr 1.0 |
| Доля изменённых пикселей поверхности (ON vs OFF) | 0.149 |
| Энергия кромок / центра | 4.46 / 0.00 |
| Яркость кромок ON vs OFF | **−1.91 %** (было +23.1 % до запекания подложки) |
| Стоимость кадра слоя (копия фона + подложка в canvas) | **0.22 ms** средняя, 21.7 ms пик (91 кадр, эмуляция) |
| Кадры страницы со слоем | p50 16.7 ms (~60 FPS), p95 33.4 ms, max 33.4 ms (эмуляция) |
| Раскладка: 328 помеченных элементов, носители слоя | носители: **0 сдвинутых, 0 пропавших**; высота страницы 844 → 844 (у 2 не-носителей deep ниже видимой области rect «дрогнул» — живое обновление контента приложения, между прогонами значение меняется, к слою не относится) |
| Ошибки отрисовки слоя (`errors`) | 0 |
| Hit-тест центра поверхности | попадает в контент, не в слой; `pointer-events: none` |
| `filter: url()` на контенте поверхностей | 0 |
| Горизонтальный overflow | нет |

Скриншоты: `evidence/e2e/pattern_on.png` / `pattern_off.png` (паттерн),
`evidence/e2e/refract_on.png` / `refract_off.png` (реальный фон).

### 2.4 Сохранено / не изменено

- Полигональный фон production — байт-в-байт (`tools/soul1_w4_frozen_check.py` →
  `FROZEN-ASSETS-OK`; `polygon-background.js` не в diff).
- Карта линзы и фильтр `#lg-lens`/`lg-lens-map`/`feDisplacementMap` — те же
  (счётчики и хэши замороженных артефактов совпадают).
- Tier B/C и «стекло в стекле» не тронуты; стекло не заменено «голой
  прозрачностью»; текст/контролы не искажаются (слой под контентом, фильтры
  `url()` на контенте = 0).
- Desktop-путь (включая `.lg-panel--hero`) сохранён без изменений.

---

## 3. Проверки (что прогнано на кандидате)

| Проверка | Команда | Результат |
|---|---|---|
| Node-набор tests/js (все файлы) | `node tests/js/<file>.js` | **87/87 OK** (в т.ч. `glass_refraction_test.js` — 50 assert, `glass_probe_test.js` — 28) |
| WIN-GLASS e2e (android + desktop + паттерн + guard + раскладка + перф) | `.venv/Scripts/python.exe tools/ui_win_glass_refraction_e2e.py` | **37/37 checks, WG-REFRACT-E2E-OK** (A 21, C 4, B 10, D 2) |
| FS-полоса (существующий e2e, без регрессий) | `.venv/Scripts/python.exe tools/ui_asap8_w2_fullscreen_e2e.py` | **12/12 сценариев, 166/166 checks** |
| Замороженные артефакты | `py -3 tools/soul1_w4_frozen_check.py` | `FROZEN-ASSETS-OK` |
| Полигон-фон (real browser) | `.venv/Scripts/python.exe tools/ui_round1026_polygon.py` | рендер/сцена/бюджеты — без изменений; 4 падения **предсуществующие** (`getDiagnostics` полей 19 != 11 — дрейф ASAP-3.1, не связан с лейном) |

RED/GREEN (обязательный минимум):

- **RED (Android-класс):** при `?glassrefract=off` (и до правки) в рамке стекла
  смещения нет: OFF↔OFF = 0 px, corr 1.0; на контрастном паттерне линии стоят
  на месте.
- **GREEN:** при включённом слое линии у кромок смещаются на −13/+16 CSS px при
  corr 0.92–0.97, центр — 0 px; яркость кромок в пределах −2 %.

---

## 4. Риски и осознанно оставленное живым

1. **iOS не проверялся живьём** (клиента нет): iOS получает слой тем же правилом
   (mobile + `svgRender`). Логика безопасна (без источника фона — честный
   отказ), но фактический вид на iOS = `PENDING_OWNER_E2E`.
2. **Android WebView живьём не проверен**: все проверки — Chromium-эмуляция
   WebView (Playwright, mobile-вьюпорт). Разница возможна в `filter: url()` на
   элементе-canvas → закрывается owner-проверкой с реального телефона.
3. **Бюджет 4 поверхности**: остальные tier-A поверхности на мобильных остаются
   с честным frost (без лупы) — это осознанное ограничение по GPU
   («Tier A — только 1–3 hero-поверхности» + бюджет слоёв).
4. **Яркость/контраст** стабилизированы (−1.9 %), но на других подложках
   возможен сдвиг ±5–10 %: значение контролируется тем же замером в e2e и легко
   подстраивается (alpha/подложка/рамка).
5. **Полное устранение бага Windows невозможно из веб-кода** — до релиза клиента
   с фиксом остаётся обход (левый верхний угол / второй монитор / перезапуск
   окна). Изменение Launch Mode через BotFather **не лечит** дефект при ручном
   входе в fullscreen.
6. `tools/ui_round1026_polygon.py` — предсуществующий дрейф ожиданий (11 vs 19
   полей диагностики). Не трогал: вне границ лейна (incidental, related-nonblocking).

---

## 5. `PENDING_OWNER_E2E` (сводно)

| # | Проверка | Где | Что ожидать |
|---|---|---|---|
| 1 | Windows: вход в mini app (Launch Mode = Fullscreen) | Telegram Desktop, Windows | Панель занимает рабочую область монитора минус панель задач **после** обхода §1.4.1; без обхода — дефект клиента (снимок диагностики) |
| 2 | Windows: ⛶ вход/выход, закрытие, перемещение/размер в оконном режиме | там же | Кнопка = выход в fullscreen, вход возвращает режим, панель управляема |
| 3 | Android: рефракция у кромок | реальный Android + Telegram | Видно смещение фоновой геометрии у кромок стекла (не только blur); текст/кнопки не искажены |
| 4 | Android: перф и поведение при скролле/ротации | там же | Плавность без просадок, после возврата из фона слой на месте |
| 5 | iOS: рефракция у кромок (если есть устройство) | iPhone + Telegram | Ожидаемо: слой даёт смещение, frost сохранён |

Все пункты требуют реальных клиентов; агентам недоступны (Browser Use ≠
нативное окно и ≠ Android WebView).

---

## 6. Файлы и хэши (sha256_12)

| Файл | sha256_12 | Что |
|---|---|---|
| `web/static/glass-refraction.js` | `6a09d962d59d` | новый модуль слоя преломления (31744 B) |
| `web/static/glass-probe.js` | `b2e6a1f987c6` | `refractionLayer` в решении; честная фиксация, что композит DOM не измерим |
| `web/app.js` | `5a810c0f4443` | носитель оптики, разметка, синхрон слоя, бюджет из `UI_LENS_MAX_NODES` |
| `web/static/app.css` | `3c67a414da7b` | frost без `url()` при `data-refract-layer="on"` |
| `web/index.html` | `0971d49d5337` | подключение модуля до `app.js` |
| `tests/js/glass_refraction_test.js` | `4fc4f9ca7848` | unit-тесты слоя (50 assert) |
| `tests/js/glass_probe_test.js` | `bed0d1dfca67` | обновлённая матрица решения (28 assert) |
| `tools/ui_win_glass_refraction_e2e.py` | `612200f86b84` | e2e: рефракция + паттерн + desktop + guard + раскладка + перф |

Артефакты для строк карты требований (учётный лейн может привязать `artifact_path`):
`WG-WIN-01/04` → `report.md §1.2`, `owner-steps.md §A`; `WG-WIN-02/05` →
`owner-steps.md §A/§B`, `evidence/e2e/_results.json` (FS-аудит: launch-fullscreen
сохранён); `WG-WIN-03` → `evidence/fs-regression/_results.json` (12/12, 166
проверок); `WG-ANDROID-01` → `report.md §2.1` + `_results.json` (проба);
`WG-ANDROID-02/05` → `_results.json` (паттерн: −13/+16 CSS px, corr 0.92/0.97,
центр 0) + `evidence/e2e/pattern_on.png`/`pattern_off.png`;
`WG-ANDROID-03` → `_results.json` (`filteredContent=0`, `layerHit`, раскладка);
`WG-ANDROID-04` → `evidence/frozen-assets.txt` (`FROZEN-ASSETS-OK`) +
`_results.json` (`perf_mobile`: 0.22 ms/кадр, бюджет ≤3);
`WG-ANDROID-06` → `_results.json` (`layers=3 ≤ 3`, `refractOn=16` с frost).

Проверка «не трогали чужое»: артефакты другого лейна
(`plans/features/soul-1/evidence/fs-hotfix/e2e-w2/*`, `w4/frozen-assets.txt`),
перезаписанные прогоном штатных e2e-инструментов, **возвращены к HEAD**; копии
результатов моего прогона лежат в `evidence/fs-regression/` и
`evidence/frozen-assets.txt`.

Паттерн-доказательство из §C повторяет требование SOUL-17.5 (смещение линий под
линзой на контрастном тест-паттерне, freeze-frame только в тестовом захвате).

Runtime-точки входа: `web/static/glass-refraction.js`
(`window.__GlassRefraction`), `web/app.js::_applyRefractLayer/reconcileLiquidGlass/
_syncGlassRefraction`, `web/static/glass-probe.js` (`window.__GlassProbe`).
Durable-тесты: `tests/js/glass_refraction_test.js` (CONTRACT/REGRESSION —
WIN-GLASS-P0/п.2), `tests/js/glass_probe_test.js` (обновление существующего
CONTRACT), `tools/ui_win_glass_refraction_e2e.py` (INTEGRATION).
