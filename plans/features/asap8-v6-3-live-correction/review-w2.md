# REV-W2 — независимый ревью Wave 2 (U01/U02/U07/U08), кандидат c053528

Ревьюер: REV-W2 (leaf-lens, read-only; артефакт — только этот файл). Дата: 2026-10-15.
Кандидат: HEAD `c053528` (Wave 2), база сверки `f1418d7`. Все заявления лейнов проверены
по коду/диффу/evidence независимо, не по отчётам.

## Вердикт

**Approved (в объёме Wave 2).** Блокеров нет. Live-проверки (реальные клиенты TMA/Windows,
CSP на проде, FPS на физических устройствах) — честно отложены в Wave 4 по w2-contract
(V06/U07.3b, V07-live) — здесь не блокер.

## 1. CORR-1 gate — «background unchanged, glass changed»: ВЫПОЛНЕНО

- `git diff f1418d7 HEAD -- web/static/polygon-background.js` → **0 строк**; также 0 строк
  для `aurora-flow.js`, `telegram-init.js`, `glass.js` (адаптер не понадобился — vanilla-путь).
- Hunks `app.css` (полный список `-U0`): только glass-токены 46–68 (−`--glass-displace`,
  +`--lg-*`; существующие ключи не переименованы), glass-tier секция 1500–1680,
  touch-цели ~1361–1405, `.mobile-topnav` 2443–2470, append-only W2-секции с 3041.
  **Ни одного hunk внутри фоновых секций** (body::before/after, .aurora-bg, .grad-band,
  .polygon-background-canvas, .aurora-flow-canvas ~290–320). Разметка aurora в
  `index.html` не тронута; скрипты — только append (probe/policy), порядок §1.3.4 соблюдён
  (probe → glass.js → policy → app.js → telegram-init.js последним).
- Тест-стенд не протекает в прод: `glass-teststand` не упоминается в index.html/app.js/app.css
  (только собственные файлы стенда + glass_probe_test).
- Новые CSS-анимации `none` касаются только glass-декора (`lg-panel__*`, `lg-mini-lens::after`
  при `lg-bg-paused`/reduced-motion) — фон не затронут; `_fsRedraw`/`_auroraResize` —
  перенос предсуществующего HOTFIX9-D7 поведения, не визуальное изменение фона.

## 2. Приёмочная ведомость Wave 2

| Требование | Статус | Ключевое доказательство (проверено по коду, не по отчёту) |
|---|---|---|
| U01 row B = 3+«Ещё» из канонического navItems, RBAC | VERIFIED | app.js:2553–2565 (fixed [status,oversight,modules], more = navItems − fixed); node-тест deepStrictEqual; e2e: 4 сегмента по 70px, x≥16, right=304≤320 |
| U01 popover «Ещё»: Esc/outside/focus-return/scroll-lock/ARIA | VERIFIED | app.js:8536–8596 + guard escClose:8616; applyRoute:8314–8315 закрывает при любом маршруте; e2e-чеки esc/outside/focus/scrollLock = true на 320/360/390/430/zoom200; z-55/56, role=menu |
| U01 desktop sidebar не тронут | VERIFIED | diff app.js по sidebar — только строка комментария; bu_oversight_desktop_1280.png; e2e desktop-инварианты |
| U01 header ≤124px, числа | VERIFIED | w2_shell_e2e.json: before 225.6 (navScrollW 455>288 — лента за экраном) → after **116.2** @320–430, 93.8 landscape; scrollWidth==innerWidth |
| U01 без горизонтальной ленты | VERIFIED | `class="mobile-topnav"` без scroll-thin; flex:1 1 0; navScrollW==navClientW==288@320; анти-маркеры в репинах |
| U01 ID-чип убран из шапки | VERIFIED | app.css:3159 `.app-shell.shell-mobile .scope-tech{display:none}`; ID — в профиле «Ещё» (moreMenuProfileId) |
| U01 нет второго заголовка/breadcrumb в шапке | VERIFIED | app.css:3133 `header-title-wrap{display:none}` на mobile |
| U02 dropdown: 7 вкладок, без «Логов», ARIA, deep-link | VERIFIED | oversightTabs 8 записей → oversightMobileTabs фильтрует logs (app.js:2582–2586); выбор через существующий oversightSetTab:9455 (hash/deep-link/lazy не тронуты); listbox/option/aria-selected; desktop ≥768 — прежняя панель; e2e u02_* |
| U07 isFullscreen — единственный источник; legacy-инверсия удалена | VERIFIED | app.js:12970 зеркало `s.actualFullscreen === true`; инверсии/`!== 'boolean'`-угадывания в app.js нет (grep); fallback-путь читает только SDK-boolean; репин #8 банит инверсию ассертом |
| U07 tdesktop → hidden | VERIFIED | policy:65,88–92 `tdesktop_disabled_until_e2e`; e2e S3: кнопки нет, html.fs-hidden, data-fs-reason, 0 вызовов API |
| U07 launch-Fullscreen без второго request | VERIFIED | policy init:491–502 requestFullscreen не шлёт вовсе; request():408–417 guard ALREADY_FULLSCREEN; e2e S6: 0 request на старте, сразу exit |
| U07 UNSUPPORTED / ALREADY_FULLSCREEN / ack-timeout | VERIFIED | policy:355–381 (UNSUPPORTED — состояние без изменений; ALREADY — пересчёт из SDK без ложного SUCCESS), 281–296 (таймаут задаётся/очищается, факт не инвертирует); unit-матрица + e2e S5 (тосты) |
| U07 float только android/ios/weba + csa≥36, иначе inline/hidden | VERIFIED | FLOAT_PLATFORMS/FLOAT_MIN_CSA_TOP=36, slotFromGeometry с hasBoolean (старый SDK без boolean → inline); unit-матрица 15 кейсов; e2e S1/S2/S8 (csa=36→float y=42, csa=0→inline) |
| U07 hit-area ≥44 без перекрытия native | VERIFIED | css:1044 min 44×44 (измерено 49×44); float top=csa.top+6; e2e elementFromPoint в зонах ⋮/✕ → header, не кнопка; формула max(env,--tg-*) дословно §2.1 |
| U07 BotFather не мутируется | VERIFIED | В диффе нет API-вызовов; только комментарии и текст ошибки-подсказки владельцу |
| U07 Node-матрица + Playwright route-mock осмысленны | VERIFIED | asap8_w2_fullscreen_policy_test.js — реальный mock SDK/машина состояний (не «тест ради теста»: считает вызовы API, pending, таймеры); _results.json 7 сценариев/70 проверок с геометрией/aria/счётчиками |
| U07 live (Windows/Android/iOS, V06) | UNVERIFIED → BLOCKED_ACCESS | Честно отложено в Wave 4 (w2-contract §4.2.5/R3); mock ≠ VERIFIED_LIVE — в отчётах не заявлен |
| U08 probe-gating (без probe → Tier B) | VERIFIED | glass-probe.js — настоящий canvas render-тест (полосы 7px не кратны сдвигу 8px, пиксельная сверка), кэш, offscreen; app.js _probeTierA: probe-missing/pending → tier b + перекур reconcile; CSS-дефолт :not([data-glass-tier="a"]) = frost-hero |
| U08 url(#lg-lens) только в glass-слоях и только при tier="a" | VERIFIED | css:1563–1565 и 3439–3441 — единственные CSS-вхождения, оба при tier="a"; inline — только в _syncLensFilters при isA (даунгрейд снимает inline); пины ban url() в голых правилах A |
| U08 нет filter:url на тексте/корне | VERIFIED | grep: только backdrop-цепочки; `[data-glass="a"]::before` — tint без filter; .lg-panel__content без фильтра; тест-инварианты glass_probe_test |
| U08 слои lg-panel + pointer-events:none декора | VERIFIED | css:3406–3442 (__backdrop/__tint/__rim/__specular, pointer-events:none); атрибутивный путь ::before/::after — тоже pointer-events:none, z:-1; hit-тест elementFromPoint = контент |
| U08 mask-composite fallback | VERIFIED | css:1595–1602 @supports not → inset box-shadow rim; evidence fallback-sim + кликабельность |
| U08 Tier-карта U08.4 | VERIFIED | index.html: hero status ×1 `data-glass="a"` (6870), oversight-tabs b, overview-карточки b, cognition-graph ×2 c, logs c, «Ещё» c, shell=shell; массовые карточки — Tier B материал blur 16→8 |
| U08 reduced-motion / low-end → Tier B, стекло не убит | VERIFIED | reconcileLiquidGlass:8446–8454 reasons; CSS сохраняет статичные rim/tint; evidence real reduced-motion hero |
| U08 Tier A численно (сканлайн) + 1:1 до/после | VERIFIED | row-y112 (центр dx=0), row-y124/130 (кромка −5…+5), row144 (контроль 0, corr=1.0) — числа в JSON реальны; before/after стенд + реальный Status |
| U08 hit-тест + контраст | VERIFIED | ui-acceptance §5.3: elementFromPoint = контент; контраст 13.1:1 ≥ 4.5 |
| U08 физический mid-range Android FPS / реальный Telegram | UNVERIFIED → BLOCKED_ACCESS | headless-прокси 60fps честно помечен ограничением; Wave 4 |
| Анти-фейк: репины не ослаблены | VERIFIED (выборочно) | #8/#9/#14 — новые ассерты строже (бан-листы + tier-гейт), старый интент жив у нового владельца (policy/probe); замены маркеров задокументированы в 3 отчётах |
| B05 «отключение polling» | N/A_WITH_REASON | Вне Wave 2 (позже), в W2 не трогался |

Итого: VERIFIED 24, UNVERIFIED (live, контрактно Wave 4) 2, N/A 1, FAILED 0.

## 3. Неблокирующие находки

- **N1** (contract-nit): `.lg-mini-lens` определён (app.css:3518+) и используется только в
  тест-стенде; прод-⛶ носит собственный glass-материал `.header-fs-btn::before`
  (32px круг, rim, один верхний inset-блик — визуальный критерий U08.4d выполнен).
  Имя из frozen-списка §3.4 на ⛶ не применено. → W3/W4: применить класс либо ревизия контракта.
- **N2** (dead asset): `web/static/vendor/lg-lens-map.png` нигде не подключён (карта —
  data-URI в index.html). 6.7KB мёртвого файла в прод-статике.
- **N3** (экспозиция): `/static/glass-teststand.html` доступен без auth на проде
  (mount web/app.py:332). CORR-1 locацию «glass-teststand» разрешает, в прод-UI ссылок нет,
  данных нет. → W4-hardening: за gate или из прод-пакета.
- **N4** (evidence-полнота U08.5.1): 1:1 crop маленького ⛶-контрола в glass-evidence
  отсутствует (материал виден в S1/S8 fullscreen-снимках); Modules-ре-скрин честно
  заменён стендом (documented env-limitation). → W4: добрать close-up.
- **N5** (dead code): дубликат `_prefersReducedMotion` в app.js:18314 и 18333 (тела
  идентичны, второй выигрывает). Убрать первый.

## 4. Что проверено лично / что переиспользовано

Лично: git-диффы (web/, config/ vs f1418d7, hunk-карта app.css), код policy/probe/app.js/
index.html/app.css, evidence-JSON (shell before/after числа, fullscreen S1–S8, glass
row-*.json), репины #8/#9/#10/#14 по диффу, порядок скриптов, отсутствие протечек стенда.
Прогнано самостоятельно: **node tests/js — 81/81 PASS**; **pytest 9 файлов — 231 passed**.
Переиспользованы (не опровергнуты): Browser Use-кадры, ui-acceptance-скриншоты,
числа FPS (headless-прокси).

## 5. Связка вердикта

Кандидат: **c053528** (web/+config/settings.py UI_LENS_MAX_NODES=3+tests+evidence).
Любое изменение web/ или config-флагов обнуляет эту оценку до ре-чека затронутых пунктов.
Live-часть (V06/V07, реальные клиенты, прод-CSP, физический FPS) — Wave 4; до неё
parent не DONE.
