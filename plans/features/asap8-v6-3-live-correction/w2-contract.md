# W2-CONTRACT — Wave 2 (SHELL / FULLSCREEN / GLASS): владение файлами, слоты, merge-порядок

Статус: **КАНОНИЧЕСКИЙ контракт Wave 2** (asap8-v6-3-live-correction). В конфликтных случаях
для W2 этот файл старше заметок в waves.md. Составлен Architect-лейном ARCH-W2, проверен по
коду HEAD `a03d87b`. `web/` и `config/` байт-идентичны baseline f58a644 (проверено
`git diff --stat f58a644 HEAD -- web/ config/` → пусто), поэтому все номера строк ниже —
действующие адреса.

Лейны: **W2-L1 SHELL** (U01, U02, UI B01.4-контракт), **W2-L2 FULLSCREEN** (U07, платформы TMA),
**W2-L3 GLASS** (U08, REQ-U08-1-AUDIT/PROBE). Барьер: REV-W2 + before/after скриншоты (REQ-0-3).

---

## 0. Проверенная карта общего кода (baseline, актуальна на a03d87b)

| Файл | Размер | Релевантные секции (строки baseline) |
|---|---|---|
| `web/app.js` | 18970 строк | `mobileTopnavItems` 2530–2532; `sidebarItems` 2523; `isMobileShell/hasSidebar` 2554–2562; data `isFullscreen` 2108; computed `liquidGlassLib` 4296, `uiFlag` 6290; mounted-init регион **4998–5007** (FS: 4998; GLASS: 5002–5003; SHELL: 5007 `_initHeaderHeight`); teardown-вызов 18472; fullscreen-блок **12791–12911** (`toggleFullscreen` 12802, legacy-инверсия **12818–12821**, `initFullscreen` 12835, `setFullscreenFromTma` 12869, `teardownFullscreen` 12900); glass-блок **18045–18252** (`_liquidGlassSupported` 18049, `_glassTierOverride` 18058, `_lensMaxNodes` 18065, `reconcileLiquidGlass` 18081, `_lgSchedule` 18126, `_initLiquidGlassObserver` 18145, `_initHeaderHeight` **18167** — исторически лежит в glass-соседстве, но принадлежит SHELL, `setBgPaused` 18191, `_syncBgLayer` 18208, `_syncGlassLib` 18246) |
| `web/index.html` | 8807 строк | meta viewport-fit=cover 7; SDK `<head>` sync 17; liquidglass css 27; SVG `#lg-lens` defs **30–49**; header 120–279; `.header-fs-btn` **162–169**; `mobile-topnav` **264–278**; class-binding `.app-shell` **66**; oversight-tabs панель с `data-glass="a" data-oversight-tabs` 3884; hero `data-glass="a"` 6770; графики `data-glass="a"` 6935/7810; `[data-glass-surface]` 6752–6753; блок `<script>` **8871–8904** (liquidglass vendor 8884 → aurora 8888 → polygon 8894 → **glass.js 8895** → app.js 8901 → **telegram-init.js 8904, последним**) |
| `web/static/app.css` | 2961 строк | токены `--glass-*` 51–68 и `--shell-*` 86+; `[data-glass="a"]` base 356–358; `header.header-sticky` **956–980** (материал 967–977 = GLASS, геометрия/padding 978–979, 986–1021 = SHELL); `.header-compact-v2` + `.header-fs-btn` inline-правило 1008–1012; геометрия `.app-shell/.scroll-area/.fullscreen-mode` **1023–1094**; fullscreen-инсеты шапки 1110–1114; `.glass-surface` 1431–1450; линза/tier-секция **1500–1680** (`[data-glass="a"]::before` 1522, `[data-glass="shell"]` 1544, downgrade 1574, `"b"` 1585, `"c"` 1595–1607, reduced-motion 1646–1670); `.mobile-topnav` **2447–2480** |
| `web/static/telegram-init.js` | 169 строк | **Единственный writer** CSS-переменных `--tg-safe-area-inset-*`, `--tg-content-safe-area-inset-*`, `--tg-viewport-stable-height`, `--tg-viewport-bottom-offset`, `--app-usable-height`; подписки `viewportChanged`/`safeAreaChanged`/`contentSafeAreaChanged` + window resize + visualViewport (147–162) |
| `web/static/glass.js` | 184 строки | адаптер vendored-библиотеки; SELECTOR строго `[data-glass-surface]`; честный режим `frosted|refraction`; API `window.__LiquidGlass.{sync,dispose,mode}` |
| `web/static/vendor/` | — | `liquidglass.core.0.5.3.css` (3670 B) + `liquidglass.core.0.5.3.min.js` (77015 B) **фактически присутствуют**, README.md; SDK `telegram-web-app.js` pinned |
| `config/settings.py` | — | `UI_GLASS_TIER_OVERRIDE='auto'` 1247; `UI_LENS_MAX_NODES=6` 1253; **`UI_LIQUID_GLASS_LIB=False` 1305–1306 (OFF — подтверждено)**; `UI_POLYGON_BG_ENABLED=True` 1315 |
| `web/api/routes.py` | 393–433 | экспорт env-флагов в `GET /api/me.ui_flags` (R16-аддитивный механизм, Δ каталога = 0) |
| `tests/js/*.js` | — | Node assert-тесты структуры: маркерные строки (`class="mobile-topnav scroll-thin"` и т.п.); pytest-семена `test_asap42_step2c2_miniapp_seams.py:528–541` |

---

## 1. Файловое владение и merge-порядок

### 1.1. Решение: параллельная работа + фиксированный rebase-порядок, БЕЗ полной сериализации

Полная сериализация не требуется и вредна: GLASS-CORE (render-probe, `.lg-panel`-система,
аудит U08.1, vendored-библиотека) не зависит от выхода SHELL/FULLSCREEN. Требуются:
(а) секционное разграничение с маркерами, (б) append-only новые блоки с lane-тегами,
(в) **интеграционный порядок SHELL → FULLSCREEN → GLASS-INTEGRATE**, (г) три именованных
hot-spot с первым владельцем (§1.4).

Каждый лейн работает в своём worktree/ветке. Merge в master строго в порядке:
**1) SHELL, 2) FULLSCREEN (rebase на SHELL), 3) GLASS (rebase на оба; его
интеграционная часть)**. Rebase ожидаемо конфликтует только в hot-spots §1.4 — там
действует правило первого владельца.

### 1.2. Матрица владения

Легенда: **W** = пишет; **R** = только читает; **W\*** = пишет строго в пределах маркированных
секций/свойств; «новое» = append-only блок с маркером `/* ═══ W2-<LANE>: … ═══ */`.

| Файл | SHELL | FULLSCREEN | GLASS |
|---|---|---|---|
| `web/app.js` | W*: `mobileTopnavItems` 2530–2532 → новый computed (4 фикс. пункта + «Ещё»); nav/shell computed 2521–2562; блок «Ещё»-меню (state+методы) — новый блок возле nav-комputed; `_initHeaderHeight` **18167–18189 (переносится в собственность SHELL, физически можно не переносить)**; U02 `oversightTabs`-computed; mounted-строка 5007 | W*: fullscreen-блок **12791–12911 целиком** (замена legacy-инверсии 12818–12821, см. §4); вызовы 4998 и 18472; data-поле `isFullscreen` 2108 + новые зеркала policy (`fsCanOffer`, `fsReason`); mounted-строка 4998 | W*: glass-блок **18045–18252** (кроме 18167–18189); `_syncBgLayer`/`setBgPaused` 18191–18240; computed `liquidGlassLib` 4296; `glassTierDiag`-state; mounted-строки 5002–5003 и 4881/4956; вызов `teardownFullscreen`-строку 18472 НЕ трогает |
| `web/index.html` | W*: header row A/row B 120–172 **без** `.header-fs-btn` (узел 162–169 переходит FULLSCREEN, SHELL сохраняет его позицию в DOM и не стилизует); `mobile-topnav` 264–278 → новая разметка row B + «Ещё»-popover (новый блок после header); U02 oversight-tabs разметка 3884+ | W*: узел `.header-fs-btn` **162–169 полностью** (v-if/aria/title); +1 строка `<script src="/static/fullscreen-policy.js">` перед app.js (8901); строка 66: только элемент `'fullscreen-mode': isFullscreen` | W*: SVG `#lg-lens` 30–49; **значения** атрибутов `data-glass*` во всём файле; `[data-glass-surface]` узлы 6752+; vendor-строки 27/8884 (только при ревендоринге); +1 строка `<script src="/static/glass-probe.js">` (рядом с 8895); строка 66: только элемент `'shell-glass-v2'` |
| `web/static/app.css` | W*: геометрия `header.header-sticky` (978–979, 986–1021, 1096–1100); `.mobile-topnav` 2447–2480; breadcrumb/hub; новый блок «Ещё»-popover | W*: селекторы `.fullscreen-mode*` 1036–1042, 1053–1059, 1063–1078, 1087–1092, 1110–1114; **новая секция** `/* ═══ W2-FULLSCREEN ═══ */` (fs-slot-float, геометрия ⛶, disabled/hint-состояния) | W*: токены `--glass-*`/`--shell-*` **значения** (51–105: добавлять `--lg-*` можно, переименовать/удалить существующие ключи нельзя — их читают все); `[data-glass="a"]` 356; секция 1500–1680 целиком; `.glass-surface` 1431–1450; новая секция `/* ═══ W2-GLASS: lg-panel ═══ */`; в правиле `header.header-sticky` 956–980 — только строки материала 964–977 (background/border-color/box-shadow/backdrop-filter) |
| `web/static/telegram-init.js` | R | **R (правка запрещена по умолчанию)** — все нужные данные уже в CSS-полях и SDK; правка допускается только при доказанном дефекте, отдельным коммитом с пометкой в отчёте лейна | R |
| `web/static/glass.js` | R | R | W (адаптер — часть U08.3) |
| `web/static/fullscreen-policy.js` | — | **W (новый файл, см. §2.2)** | R |
| `web/static/glass-probe.js` | R | R | **W (новый файл, см. §3.3)** |
| `config/settings.py` | R | R | W*: только добавление/правка комментариев и значений по умолчанию glass-флагов 1239–1316; новые env-флаги — по образцу R16/R17 (bool/str/int, Δ каталога = 0) |
| `web/api/routes.py` | R | R | W*: только блок ui_flags 399–429 (добавление glass-флагов) |
| `tests/js/`, pytest-семена | W*: только assertions своего скоупа (mobile-topnav/navItems/«Ещё») | W*: assertions `.header-fs-btn`/policy | W*: assertions glass/vendor/probe |

Правило эволюции тестов: маркерные CONTRACT-тесты предыдущих раундов (D13 «нет bottom-nav»,
hotfix-структуры) при смене канона U01 заменяются на новые маркеры нового канона
(«4 destination + Ещё»), а не удаляются молча. В отчёте лейна — список замен тест-маркеров.

### 1.3. Индексные точки: где разные лейны не пишут в одну строку

1. `index.html:66` class-binding `.app-shell` — массив из трёх владений: SHELL владеет
   `'shell-'+shellMode`/`ia-v2`/`shell-flex-v3`-элементами, FULLSCREEN — элементом
   `'fullscreen-mode'`, GLASS — `'shell-glass-v2'`. Каждый правит ТОЛЬКО свой элемент.
2. `app.js:mounted` 4994–5007 — каждый лейн правит только свои строки вызовов
   (SHELL 5007, FS 4998, GLASS 5002–5003); новые вызовы — append в конец региона с
   lane-комментарием, без переотступов чужих строк.
3. `app.js:data()` — SHELL: nav/«Ещё»-состояние; FS: 2108 + новые fs-поля; GLASS:
   `glassTierDiag`. Новые поля — в отдельных строках своего лейна.
4. Блок `<script>` index.html 8883–8904 — только append строк (FS перед 8901, GLASS рядом
   с 8895), порядок загрузки не менять: SDK(17) → … → liquidglass(8884) → glass-probe →
   glass.js(8895) → fullscreen-policy → app.js(8901) → telegram-init.js(8904, последним).

### 1.4. Hot-spots и первые владельцы

| Hot-spot | Файл:зона | Первый владелец | Остальные |
|---|---|---|---|
| HS-1 | `index.html:66` + header-разметка 120–172 | **SHELL** | FS и GLASS rebase; конфликт не разрешать самовольно — брать версию SHELL и заново внести свой элемент/узел |
| HS-2 | `app.js` mounted-регион + data() | **SHELL** (merge №1) | FS, GLASS rebase по §1.3.2–3 |
| HS-3 | `app.css` правило `header.header-sticky` 956–980 | **SHELL** (геометрия/padding) | GLASS вносит материал (964–977) повторным apply при rebase; property-наборы не пересекаются, конфликт текстовый — разрешается по владельцу свойства |

### 1.5. Почему не серилизуем GLASS после SHELL целиком

Единственный реально общий селектор GLASS↔SHELL — `header.header-sticky`. Он разрезается
по свойствам (геометрия/материал, §1.4 HS-3), а интеграционные зависимости GLASS
(mini-lens на ⛶, tier popover) выражаются классами, имена которых заморожены в этом
контракте (§3.4), поэтому GLASS-CORE полностью параллелен. Полная сериализация дала бы
ложную безопасность: те же hot-spots пришлось бы разруливать на rebase в любом случае.

### 1.6. Картика параллельной безопасности

| Зона | Классификация |
|---|---|
| app.js fullscreen-блок 12791–12911 | PARALLEL_SAFE (эксклюзив FS) |
| app.js glass-блок 18045–18252 (без 18167) | PARALLEL_SAFE (эксклюзив GLASS) |
| app.js nav-комputed + «Ещё» | PARALLEL_SAFE (эксклюзив SHELL) |
| mounted-регион, data(), index.html:66, script-блок | SERIALIZE (порядок §1.1, правила §1.3–1.4) |
| app.css header-sticky 956–980 | SERIALIZE (property-split HS-3) |
| app.css fullscreen-селекторы / lg-секция / mobile-topnav | PARALLEL_SAFE |
| telegram-init.js | READ_ONLY_PARALLEL (для всех) |
| index.html SVG #lg-lens, data-glass значения, vendored | PARALLEL_SAFE (эксклюзив GLASS) |
| `.header-fs-btn` узел + fullscreen-policy.js | PARALLEL_SAFE (эксклюзив FS) |
| VERIFIED_LIVE U07 на реальных клиентах | BLOCKED_BY:Wave4-E2E (mock-only ≠ verified, V06/U07.3b) |

---

## 2. Контракт слота fullscreen в новой шапке (U01 ↔ U07)

### 2.1. Решение по слоту: ОДИН DOM-узел, два режима, решает политика

Кнопка ⛶ — **один** элемент `<button class="header-fs-btn">` (наследник текущего узла
index.html 162–169). Владелец узла и его стилей — **FULLSCREEN**. SHELL проектирует row A
так, чтобы правая часть строки 1 терпела наличие/отсутствие кнопки в потоке (flex + gap),
и **не стилизует** `.header-fs-btn` вовсе. Двух узлов / дублирования aria не создаём.

Режимы (выбирает `fullscreen-policy.js`, поле `slot`):

- `inline` (по умолчанию): кнопка в потоке row A справа (как сегодня, compact-v2 order 5).
  Обязательный режим при: отсутствие Telegram, `web`/`weba` без SDK-boolean, `unknown`,
  `csa.top === 0`, ошибка измерений.
- `float`: `position: fixed`; геометрия ТОЛЬКО из Telegram-переменных (никогда не
  `env()`-одиночка — в Telegram Android env часто 0):
  `top: calc(var(--tg-content-safe-area-inset-top, 0px) + 6px)`,
  `right: calc(max(env(safe-area-inset-right,0px), var(--tg-content-safe-area-inset-right,0px), var(--tg-safe-area-inset-right,0px)) + 6px)`.
  Условие включения: `platform ∈ {android, ios, weba}` И `hasRequestFullscreen` И
  `csaTop >= 36` (px). Кнопка при этом визуально 30–34px (min 28), hit-area ≥44×44 без
  захода в native-зоны. Бюджет высоты шапки ≤108–124px действует только для `inline`;
  геометрия `float` — полноэкранная overlay-геометрия U07 и из бюджета исключена (прямо
  разрешено U01).
- `hidden`: `tdesktop` до успешного platform-specific e2e (U07.1a) и клиенты без
  `exitFullscreen`/`requestFullscreen` вовсе. Подсказка-причина — в data-атрибуте
  `data-fs-reason`, для tdesktop кнопка скрыта (рекомендация: скрыть, а не disabled —
  меньше риск мёртвого контрола; возврат по feature-gate после реального Windows e2e).

При `slot=inline` SHELL гарантирует: правый край row A не переполняется при 320px; при
`slot=float` FULLSCREEN сам добавляет верхний резерв через
`html.fs-slot-float header.header-sticky.header-compact-v2 { padding-top: … }` в СВОЕЙ
css-секции — SHELL не обязан это предусматривать, но обязан не ломаться при наличии класса.

### 2.2. `web/static/fullscreen-policy.js` — новый файл (владелец FULLSCREEN)

IIFE по образцу `glass.js`/`telegram-init.js` (CSP-safe, без Vue, без inline). Загружается
до `web/app.js` (§1.3.4). Публичное API:

```text
window.__FullscreenPolicy = {
  state: () => ({ telegramPlatform, sdkVersion, hasRequestFullscreen, hasExitFullscreen,
                  actualFullscreen, launchFullscreen, requestPending, lastError,
                  canOfferFullscreen, canOfferExit, reason, slot,
                  viewport: {width, height, stableHeight, safeAreaInset, contentSafeAreaInset} }),
  request(), exit(),            // единственные пути к wa.requestFullscreen/exitFullscreen
  subscribe(fn),                // явные события -> Vue-зеркало; НЕ Vue-reactive (§4)
  slotFromGeometry(platform, csaTop, hasReq), decideOffer(...)   // чистые функции для unit-тестов
}
```

Требования: чистые функции доступны без DOM (window-guard) для Node-тестов; таймауты ack —
внутри политики; повторный тап/rotation не создаёт параллельных запросов; `isFullscreen` —
только из SDK, **удалить legacy-инверсию app.js:12818–12821** («не инвертировать локальный
Vue-флаг, когда SDK не отдаёт isFullscreen» — U07.1); launch-mode fullscreen на старте —
повторный `requestFullscreen()` не отправлять, сразу кнопка выхода (U07.1e); Windows-старт
в проблемном fullscreen — один мягкий `exitFullscreen()` при наличии API, иначе
документированное ограничение (не чинить CSS-«полномочиями»).

### 2.3. Единый источник правды viewport/safe-area

| Данные | Писатель | Читатели |
|---|---|---|
| `--tg-safe-area-inset-*`, `--tg-content-safe-area-inset-*`, `--tg-viewport-stable-height`, `--tg-viewport-bottom-offset`, `--app-usable-height` | **telegram-init.js (единственный)** | CSS всех лейнов (calc/max), никто не пишет вторично |
| факты SDK (platform, isFullscreen, insets, viewport*, события fullscreen*) | Telegram.WebApp | читают только telegram-init.js (для переменных) и fullscreen-policy.js (для состояния); `app.js` напрямую `wa.safeAreaInset` не читает |
| `--header-h` | **app.js `_initHeaderHeight` (SHELL)** — измерение фактического bounding rect | FULLSCREEN (float-геометрия, scroll-padding), все |
| `--shell-*` токены (значения) | GLASS (материал §4 UPD3 §8) | SHELL (геометрия шапки/сайдбара) |
| `html.fs-slot-float`, `html.fs-hidden`, `data-fs-reason` | fullscreen-policy.js | CSS FS |
| `html.lg-bg-paused`, aurora/polygon классы | app.js `_syncBgLayer`/`setBgPaused` (GLASS-скоуп) | CSS GLASS |

Запрещено: второму модулю писать `--tg-*`/`--app-usable-height`; FullscreenPolicy
пересчитывать safe-area самостоятельно; SHELL читать `Telegram.WebApp` напрямую.

---

## 3. GLASS ↔ SHELL: слоистая модель

### 3.1. Разделение «материал / геометрия»

- GLASS владеет **материалом**: `background`, `backdrop-filter`, `box-shadow`,
  `border-color`/rim, `--shell-*`/`--glass-*` значения, слои `.lg-panel__*`,
  `[data-glass="a|b|c|shell"]`-правила (1500–1680).
- SHELL владеет **геометрией**: `position/display/flex/padding/z-index/height` шапки,
  row A/B, popover-раскладка, `mobile-topnav`, scroll-резервы.
- На `header.header-sticky` это property-split HS-3: базовое правило 956–980 SHELL не
  переписывает в своей работе; материал U08.4e («графит со светлой кромкой, не чёрная
  полоса, плотный при скролле») GLASS реализует в секции `[data-glass="shell"]`/`--shell-*`
  и/или переопределением материала в своей маркированной секции.

### 3.2. Жёсткие запреты (U08.2/U08.3, проверяемые)

- `filter: url(#lg-lens)` — только на изолированном декоративном `::before`-слое
  (`[data-glass="a"]::before`, текущий паттерн 1522) или `.lg-panel__backdrop`.
  **Запрещено** на корне карточки, на `header-sticky`, `html/body`, на текстовых узлах и
  `.lg-panel__content`.
- Ни один декоративный слой не перехватывает pointer events (`pointer-events: none`
  обязательно), не затуманивает текст, не перекрывает scroll-container и Telegram
  native hit-зоны.
- Tier-разметка shell: шапка/`mobile-topnav` = Tier B; «Ещё»-popover = solid
  (`data-glass="c"`); ⛶ = круглая мини-линза класса `lg-mini-lens` (Tier B материал);
  Status hero = Tier A opt-in (`data-glass="a"`, ≤ UI_LENS_MAX_NODES); таблицы/логи/
  редакторы/графики = Tier C. SHELL ставит атрибуты по этому словарю при создании
  разметки (например новый dropdown U02 → `data-glass="c"`); дальнейшая перетюсовка
  значений — эксклюзив GLASS.
- Никакого клонирования live DOM с текстом/данными и никакого покадрового html2canvas;
  clone-путь допустим только для стабильного декоративного фона (aurora/polygon canvas)
  при доказанной синхронности регистрации (U08.3).

### 3.3. Render-probe — `web/static/glass-probe.js` (новый файл, эксклюзив GLASS)

Причина: текущий `_liquidGlassSupported` (app.js:18049) — `CSS.supports('filter','url(#…)')`,
что по U08.3 не является доказательством рендера (WebKit/Telegram WebKit может
игнорировать). Новый модуль: IIFE, `window.__GlassProbe = { probe(): Promise<{tierA:boolean, reason:string}> }`,
реальный рендер-тест (offscreen-узел с фильтром + пиксельная сверка отличия от
неотфильтрованного), кэш результата за сессию, без Vue. `reconcileLiquidGlass` переходит
на probe (async, с сохранением существующих budget/override/reduced-motion-приоритетов).
Остальные лейны probe **не вызывают и не импортируют**.

### 3.4. Замороженные имена (менять только через новый ревизионный коммит контракта)

`lg-panel`, `lg-panel--hero|--soft|--solid`, `lg-panel__backdrop|__tint|__rim|__specular|__content`,
`lg-mini-lens`, `data-glass ∈ {a,b,c,shell}`, `data-glass-downgraded`, `data-glass-tier`,
`data-glass-reason`, `data-glass-surface`, `#lg-lens`, `window.__LiquidGlass`,
`window.__GlassProbe`, `window.__FullscreenPolicy`, `html.fs-slot-float`.

### 3.5. Статус vendored-библиотеки (проверено)

`web/static/vendor/liquidglass.core.0.5.3.css` + `.min.js` существуют, подключены
(index.html 27, 8884), адаптер `glass.js` монтирует строго `[data-glass-surface]`
(index.html 6752), режим честно определяется как `frosted`/`refraction`
(WebGL-путь = единственная рефракция анимированного canvas). Прод-default
`UI_LIQUID_GLASS_LIB=False` (settings.py 1305–1306) — **выключен**. GLASS в U08.1
обязан: проверить, даёт ли lib реальную рефракцию подложки на стенде V07 (не пустой
декоративный блок), разобраться с причиной выкл. (hotfix10: белые frosted-подмены на
функциональных целях) и либо включить lib-путь точечно на hero, либо построить vanilla
progressive-слой; решение и лицензия/CSP-проверка — в отчёте лейна.

---

## 4. Non-reactivity-loop (U07.1) и тестовая стратегия W2

### 4.1. Политика без Vue-реактивных циклов

- `fullscreen-policy.js` не импортирует Vue, не держит ссылок на компонент; состояние —
  plain object; изменения состояния — только из SDK-событий
  (`fullscreenChanged`, `viewportChanged`, `fullscreenFailed`) и пользовательских
  `request()/exit()`.
- app.js подписывается через `subscribe(fn)` и копирует в Vue только отображаемые поля
  (`isFullscreen`, `fsCanOffer`, `fsReason`). Обратных путей «Vue computed → вызов policy →
  запись в Vue в том же тике» быть не должно: policy-методы возвращают результат по
  событию ack, а не синхронным присваиванием.
- `requestPending`/таймаут живут в политике; повторный тап при pending игнорируется;
  `fullscreenFailed(UNSUPPORTED)` → состояние без изменения; `ALREADY_FULLSCREEN` →
  перечитать SDK, кнопка = выход, без ложного SUCCESS.
- aria: `aria-pressed=true` строго при `actualFullscreen===true`; title по ack-состоянию;
  при ошибке — тост/текст причины, не молчание.

### 4.2. Тесты W2 (owner каждого набора — соответствующий лейн)

1. **Mock Telegram SDK (Playwright)**: перехват `**/static/vendor/telegram-web-app.js`
   (route-fulfill заглушкой) — НЕ addInitScript поверх реального SDK (он sync в `<head>`
   и перетер бы мок). Мок: platform, isFullscreen:boolean|undefined, методы
   request/exit + ручная эмиссия `fullscreenChanged`/`fullscreenFailed`
   (UNSUPPORTED/ALREADY_FULLSCREEN), `safeAreaInset`/`contentSafeAreaInset`,
   `viewportStableHeight`, `launchFullscreen`-старт.
2. **Матрица политики (unit, Node)**: `slotFromGeometry`/`decideOffer` по
   platform × capability × csaTop × launchFullscreen; отдельные случаи: SDK без boolean
   isFullscreen → нет инверсии, honest-disable (U07.1); tdesktop → hidden;
   ALREADY_FULLSCREEN → без второго request; повторный тап при pending.
3. **Геометрия шапки (Playwright)**: ширины 320/360/390/430 портрет + 667×375 landscape;
   row B = 4 пункта целиком, `document.documentElement.scrollWidth <= innerWidth`;
   `header.getBoundingClientRect()` числа в отчёт; hit-area ⛶ ≥44×44, при `float`
   rect.y ≥ csa.top, пересечений с зоной native ⋮/✕ нет (по мок-инсетам); «Ещё»-popover:
   Esc/outside-click/focus-return, без обрезки на 320px.
4. **Glass (Playwright + стенд)**: контрольный фон (прямые линии + волна), 1:1 crops
   Tier A vs Tier B vs reduced-motion; `elementFromPoint` в центре карточки = контент
   (декор не перехватывает); FPS-замер скролла на mid-range профиле; scrollWidth-проверка.
5. **before/after** одного маршрута и данных (REQ-0-3): до/после скриншоты в
   `plans/features/asap8-v6-3-live-correction/w2-evidence-<lane>.md` (SHELL: статус/модули/
   аналитика mobile; FS: шапка с ⛶ inline/float/hidden; GLASS: hero-карточка, модульная
   карточка, status). VERIFIED_LIVE U07 — только Wave 4 на реальных клиентах (V06,
   U07.3b), mock-прогоны верификацией fullscreen не считаются.

---

## 5. Риски и открытые вопросы

| # | Уровень | Риск / вопрос | Рекомендация |
|---|---|---|---|
| R0 | blocker-риск | app.js 18.9k строк, 3 лейна, смежный mounted-регион 4994–5007 | правила §1.3–1.4 обязательны; merge-окно: следующий лейн начинает rebase только после merge предыдущего в master |
| R1 | средний | удаление legacy-инверсии (12818–12821) меняет поведение на старых SDK (сейчас кнопка «работает» угадыванием) | это явно требовано U07.1; honest-disable + причина; покрыть unit-кейсом из §4.2.2 |
| R1 | средний | HS-3: материал/геометрия в одном CSS-правиле | property-split соблюдать буквально; конфликт всегда разрешается по владельцу свойства, не «чья ветка новее» |
| R2 | средний | GLASS: включение `UI_LIQUID_GLASS_LIB` или vanilla-слой — решение внутри лейна | критерий выбора: стенд V07 показывает реальную рефракцию; если lib даёт только frosted → vanilla progressive; дефолт прод-флага менять только с доказательством и rollback-флагом |
| R2 | низкий | `env()` в Telegram Android = 0 → float-геометрия мимо, если использовать только env | формула §2.1 (max из env + `--tg-*`) обязательна; unit-тест csa=0 → slot=inline |
| R2 | низкий | бюджет ≤108–124px vs float-резерв шапки | бюджет нормирован только на inline-режим (U01), в отчёте мерить оба режима раздельно |
| R3 | открытый вопрос владельцу (не блокирует W2) | tdesktop: скрыть кнопку vs disabled с подсказкой (ТЗ допускает оба) | по умолчанию hidden; изменить — одна константа политики + ревизия контракта |
| R3 | BLOCKED_ACCESS | iOS/реальный Windows Desktop в этой среде недоступны | честный `BLOCKED_ACCESS` в V06-строке, живые проверки — Wave 4 (уже отражено в waves.md риске №3) |

---

## 6. Приёмка контракта (checklist REV-W2 входа)

- [ ] Каждый лейн подтвердил в старте работ write-scope §1.2 и имена §3.4.
- [ ] Merge-порядок §1.1 соблюдён; hot-spots разрешены по §1.4.
- [ ] `fullscreen-policy.js` и `glass-probe.js` существуют, загружены по §1.3.4, unit-покрыты.
- [ ] telegram-init.js не изменён ни одним лейном (или изменение — отдельный мотивированный коммит).
- [ ] Удалена legacy-инверсия 12818–12821; `aria-pressed` только по SDK-факту.
- [ ] data-glass-словарь §3.2 применён в новой разметке SHELL/FS; запрет `filter:url` на тексте/корне не нарушен (grep-проверка в ревью).
- [ ] before/after-скриншоты по §4.2.5 приложены; числа header-геометрии на 320–430+landscape записаны.
