# ASAP-UI-02 — compliance matrix vs ACTUAL HEAD

Source: `plans/current_task.md` L1751–2004 (ASAP-UI-02).
Inspected: worktree `evol-71536a366a11-c63f6f44`, branch `evol/impl`, HEAD `6a424416`, uncommitted slice = memory-record modal fix (read-only here, not audited as final).
Not a new register: `пункт → состояние → доказательство → минимальная дельта → владелец`.

Productive default path: `uiFlag()` returns **true** for absent flags (`web/app.js:8570`) → IA v2 + `UI_HEADER_COMPACT_V2` are ON. Breakpoints: `shellMode = ≥1200 desktop / 768–1199 compact / <768 mobile` (`web/app.js:11505`).

## 1. Navigation §2.1

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| Desktop single sidebar + low topbar | DONE_AND_VERIFIED | `web/index.html:108-155` (`aside.app-sidebar`, one nav registry `sidebarGroups`), CSS only ≥1200 `app.css:2704-2707`, collapse rail `app.css:5829-5833` (EVOL-023) | — | — |
| Tablet: sidebar **or** drawer, no duplicate menu | DONE_AND_VERIFIED | drawer `index.html:12979-13012` + `app.css:2742-2763`; sidebar force-hidden `app.css:2704`; drawer force-hidden only inside `@media(min-width:1200px)` `app.css:2738-2739`; screenshots `evidence/w7-nav-tablet-drawer.png`, `w9-responsive-mid-768x1024-*` | — | — |
| **Mobile: no persistent bottom navbar, drawer instead** | **DONE_AND_VERIFIED (ASAP-UI-02 §2.1, 31.10.2026)** | `nav.mobile-topnav` и его ландшафтный рейл удалены (`web/index.html`, `web/static/app.css`); единый drawer `v-if="iaV2 && hasDrawer"` (`hasDrawer` = `shellMode !== 'desktop'`, `web/app.js`), кнопка `[data-drawer-trigger]` в шапке на mobile И tablet; закрытый drawer за краем (`transform: translateX(-105%)`); scroll-lock `.app-shell.drawer-open`; `--bottom-nav-h` и `_syncBottomNavMetric` удалены | — (сделано в этой волне) | ✅ закрыто |
| Drawer reachable on phone | **DONE_AND_VERIFIED** | кнопка навигации рендерится на `<1200`; e2e: 390/667/320 открывают drawer, все 8 разделов, фокус внутрь, Esc + возврат фокуса; скрины `evidence/w7-nav-mobile-drawer.png`, `w7-nav-landscape-drawer.png` | — | ✅ закрыто |
| No simultaneous bottom tabs + top tabs + drawer | **DONE_AND_VERIFIED** | один механизм навигации на breakpoint: sidebar ≥1200 / drawer <1200; в «⋯» разделов нет; инвентарь 19×6 = 114 ячеек без второго навбара | — | ✅ закрыто |
| Internal tabs only for screen subsections | DONE_AND_VERIFIED | `oversightSetTab` tabs screen-local; глобального ряда табов в IA v2 нет | — | — |
| Old tests encode bottom nav | **DONE_AND_VERIFIED (переписаны)** | `asap8_w2_shell_mobile_nav_test.js` (полностью под drawer/«⋯»), `asap8_d1213_save_contract_test.js`, `asap42_step2c2_layout_test.js`, `cfg04_forms_contract_test.js`, `round1025_shell_breakpoints/hotfix4/hotfix7/hotfix9`, `round1025_ia_routing_test.js`, `routing_test.js`, `evol_w9_responsive_test.js` + 12 python-файлов и live-инструменты `ui_evol_w7_nav_e2e.py`, `ui_evol_w9_responsive_e2e.py`, `ui_round1025_matrix.py`, `ui_w4_ui_e2e.py`, `ui_speech_mobile_entry_e2e.py`, `ui_asap8_v6_d1213_e2e.py`, `ui_asap8_w2_fullscreen_e2e.py`; ни один запрет не ослаблен — менялись только пины отменённой панели | — | ✅ закрыто |

## 2. Topbar §2.2

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| Nav button in topbar | **DONE_AND_VERIFIED** | `[data-drawer-trigger]` в шапке на mobile+tablet, inline-SVG menu-глиф (`ui-ic`, 20px), hit 44×44, `aria-label="Открыть навигацию"`, `aria-expanded` = `drawerOpen` | — | ✅ закрыто |
| Section name exactly once | **DONE_AND_VERIFIED (ревью-фикс F1, 31.10.2026)** | `.header-title` виден и на телефоне; контентный дубль скрыт на ВСЕХ ширинах правилом верхнего уровня `.app-shell.ia-v2 .hub-head .hub-title { display: none; }` (было заперто в `@media (min-width:768px)` → на 390 имя стояло дважды в #/ai, #/modules, #/memory, #/access); крошка `breadcrumb` на mobile скрыта; e2e `title_once` (видимые вхождения, а не только шапка): 4 маршрута × 320/390 = ровно 1; живой Chromium 320/390 — то же (`evidence/w7-nav-live-fix2-{320,390}-header.png`, `w7-nav-probe.json.title_once`) | — | ✅ закрыто |
| Chat scope switcher, one instance, all routes | DONE_AND_VERIFIED | `index.html:260-307` single `scope-wrap` + in-panel search + avatars; badge `CHAT/GLOBAL`; full name in options `:299`; screenshots `w7-nav-desktop-scope-panel.png`, `w7-nav-mobile-scope-panel.png`; **ревью-фикс F2 (31.10.2026):** на 320–419 имя выбранного чата ОСТАЁТСЯ в триггере (ellipsis 35/45 px при 320, 62 px при 390, полное — в `title` на 60 знаков и в панели), место освобождено переносом ghost-⛶ в «⋯» (`data-fs-menu-item`, hit 44) | — | ✅ закрыто |
| Avatar + compact actual-role badge visible | **DONE_AND_VERIFIED** | markup `.header-user-name` (скрыт на mobile) + `.header-user-role` (виден, ellipsis, полное имя роли в `title`) + `.header-user-initial` (фолбэк аватара без фото); прежнее `.header-user span{display:none}` удалено; e2e 320/390/667/1280 — бейдж виден | — | ✅ закрыто |
| Visual logo removed | **DONE_AND_VERIFIED** | `.sidebar-brand`/`.sidebar-brand-title`/`.mobile-brand` удалены из `index.html` и CSS; верхняя строка панели — `.sidebar-top` с одной функциональной кнопкой `data-sidebar-collapse`; `buildFsGeomText` фиксирует отсутствие узлов бренда | — | ✅ закрыто |
| Long chat name truncates visually only | DONE_AND_VERIFIED | `.scope-name.truncate` + `:title` `index.html:269-275`, full text in option `:299-300`; `w9` ellipsis check + `w7-nav-*` shots | — | — |
| Secondary actions entry (search/fullscreen/help) | PARTIAL | fullscreen ghost icon 18px / hit 44×44 `index.html:236-247`, `app.css:1146`, `app.css:3712`; help is nav route `#/how`; **app-wide search absent** (EVOL-037 PENDING, no palette/`Ctrl+K` in code) | add search entry when EVOL-037 lands; nothing to build now | PM/UI (blocked on EVOL-037) |
| No second header row | DONE_AND_VERIFIED | `display:contents` single row `app.css:1135`, `app.css:5695`; low landscape one row 48px `app.css:6029-6051` | — | — |

## 3. Icons §2.3

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| Single icon system, stroke/size/hit-area | DONE_AND_VERIFIED | Material Symbols Rounded self-host `web/static/fonts/material-symbols-rounded.woff2` + `iconGlyph()`; 20–21px `app.css:2793`, `app.css:5901`; touch ≥44 `app.css:2791-2804`, coarse media `app.css:6147-6151`; `aria-label`/`title` everywhere | — | — |
| Drawer icon = menu/sidebar glyph | **DONE_AND_VERIFIED** | inline-SVG menu-глиф класса `ui-ic` (20px) в `[data-drawer-trigger]`, hit 44×44, спокойный hover/focus; шрифтовой сабсет (37 PUA-глифов) не расширялся — тот же inline-SVG приём, что у ⛶ | — | ✅ закрыто |
| «Ещё» = ellipsis, not grid | **DONE_AND_VERIFIED** | `[data-more-trigger]` — горизонтальное троеточие (inline-SVG), `aria-label="Дополнительные действия"`; `grid_view` в шапке отсутствует; тест `asap8_w2_shell_mobile_nav_test.js` это фиксирует | — | ✅ закрыто |
| Quiet borders/backgrounds, no pulsing | DONE_AND_VERIFIED | `.btn-ghost` transparent `app.css:525-541`; новые `.header-nav-btn/.header-more-btn` — прозрачные, hover rgba .06, без анимаций; reduced-motion guards сохранены | — | — |
| More-menu holds only secondary actions | **DONE_AND_VERIFIED** | «⋯» содержит только служебное действие (admin-диагностика `data-fs-geom-diag-entry`) и блок профиля (имя/роль/ID области); списка разделов нет — `mobileMoreItems`/`moreMenuPick` удалены, разделы только в drawer | — | ✅ закрыто |

## 4. Scroll / Telegram §2.4

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| No arbitrary hide-on-scroll / jumping header | DONE_AND_VERIFIED | no scroll-direction header code (grep `hideOnScroll/lastScroll/scrollDir` empty); sticky single row `app.css:1135`, height by components | — | — |
| No duplicated Telegram chrome | DONE_AND_VERIFIED | `fullscreen-policy.js` single ⛶ node + `html.fs-hidden`/`data-fs-reason`; native Back used when available (`index.html:178-183`); `static/telegram-init.js`; tests `tests/js/asap8_w2_fullscreen_policy_test.js`, `T-1099` fallback rule | — | — |
| Drawer: backdrop, esc/outside, focus restore, keeps section/scope | DONE_AND_VERIFIED | `index.html:12979-12986` (`inert`, `aria-hidden`, `@keydown.esc`), `drawer-backdrop` `app.css:2761-2763`; `toggleDrawer/closeDrawer` state in `app.js`; screenshot `w7-nav-live-tablet-900-drawer.jpg`; **ревью-фикс F3 (31.10.2026):** Tab/Shift+Tab замкнуты внутри панели (`drawerOnKeydown`, e2e: 10 Tab → 8 разных пунктов, выхода нет), глобальный `escClose()` закрывает открытый drawer и при фокусе ВНЕ панели, `goBack()` сначала закрывает панель (маршрут не меняется) | — | ✅ закрыто |
| Landscape: no second permanent row | **DONE_AND_VERIFIED** | `<768` landscape: ландшафтный рейл удалён вместе с `mobile-topnav`; шапка остаётся одной строкой (`header.header-sticky.header-compact-v2 { flex-wrap: nowrap; min-height: 48px }`), резерв `padding-right: 58px` убран; e2e 667×375 — 1 ряд, drawer открывается | — | ✅ закрыто |
| Keyboard / safe areas / no horizontal overflow | DONE_AND_VERIFIED | `--kb-offset` из `visualViewport` `app.js:7447-7461`; safe-area vars в shell/header; инвентарь после правки: `evidence/w9-responsive-inventory.json` 19 маршрутов × 8 вьюпортов = 152 ячейки, `hScroll 0`, `offscreen 0`, `clipped 0`; `w7-nav-inventory.json` 114 ячеек, failures 0 | — | — |

## 5. Design system §3

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| Existing token set, no second system | DONE_AND_VERIFIED | `app.css:57-160`: `--surface-0..3`, `--text-1..3`, `--ok/--warn/--err(+ -bg, -text)`, `--teal/purple/magenta/indigo`, `--h1..h6`, `--tx-large..tiny`, `--space-1..8`, `--control-h/-sm/-touch`, `--btn-h`, `--radius-sm..full/xl`, `--border-hairline:1px`, `--shadow-sm..xl`, `--glass-*`, `--overlay-bg/-z:50/-radius`, `--focus-ring`, `--dur-fast/-normal/-slow`, `--ease-out`, `--sfeed-*`, `--health-*` | — | — |
| One visual role = one component type | PARTIAL | canonical `.btn/.btn-ghost/.field/.card/[data-glass]/health-glass-surface`, module/record/speech screens reuse them (EVOL-022/023/026-030); residual local paddings (`app.css:1403`, `1469-1470`, `4194`, `4549-4553`) | normalize only touched screens; no global restyle | UI lane (controls) |
| Single optical border, no double contours | DONE_AND_VERIFIED | one hairline token `--border-hairline`/`--glass-border` `app.css:76`, `.card` uses `--card-border`; seam regression test `tests/js/evol_glass_seam_test.js`, `tests/js/glass_probe_test.js` | — | — |
| Glass optics / polygon bg / refraction untouched | DONE_AND_VERIFIED | `static/glass.js`, `glass-refraction.js`, `polygon-background.js`, `aurora-flow.js` untouched by EVOL UI waves; health tint changes `background-color` only `app.css:5242-5256`; tests `tests/js/glass_refraction_test.js`, `tools/ui_win_glass_refraction_e2e.py` | — | — |
| Contrast / disabled vs loading / error not color-only | DONE_AND_VERIFIED | `.btn-ghost:disabled{opacity:.4}` `app.css:537`, `.is-saving`/`.is-readonly` states `index.html:5283-5284`; error lines are text (`module-error`, `data-sfeed-error` `index.html:12021`); save chip `role=status` `index.html:217-225` | — | — |

## 6. Cards / modals / overlay / forms §4

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| System card: title+status+reason+time+one detail path | DONE_AND_VERIFIED | `health-glass-surface` `app.js:28247-28346` (label/reason/time/link), CSS `app.css:5262-5340`; status block `index.html:11304-11448` | — | — |
| Record card: entity/date/text/provenance, opens the same record | DONE_AND_VERIFIED | `.sfeed-item` rows `index.html:11578-11591`, `12034-12045`; `openStatusRecord()` opens record by id | — | — |
| One detail standard (modal desktop / sheet mobile), same `record_id` | PARTIAL | record modal `index.html:13107-13145` (`role=dialog`, `aria-modal`, Esc/✕/outside, focus trap+return, `sfeed-modal-open` scroll lock, dl with missing→«нет данных», provenance section); active uncommitted slice fixes memory-record modal — must not be duplicated | finish in progress lane; no separate implementation here | UI lane (record modal, busy) |
| One z-index / portal / focus / backdrop system | PARTIAL | tokens `--overlay-z:50` `app.css:113`, but concrete z values still vary: drawer 40 `app.css:2758`, backdrop 35 `app.css:2762`, modal `app.css:1034/1094`; modals live outside `main.scroll-area` (`index.html:13100-13106`) | align to `--overlay-z` + one background-layer scale when touching those files | UI lane (overlay) |
| Toggles: server confirmation, scope, no duplicate master in details | DONE_AND_VERIFIED | module card master `data-module-global-toggle` `index.html:5283-5293` with pending/confirm/revert (`moduleGlobalPendingFor`), per-chat separate `:5297-5314`, `global` reuse explains reason `:5317-5323`; tests `tests/test_webapp_evol_w10_sections.py:337-488` (`TestEvol026Widgets`, `TestEvol027Catalog`) | — | — |
| Select/combobox identical placement, mobile sheet | PARTIAL | scope listbox is custom a11y listbox with flip `scopePanelStyle` `index.html:282-306`; other screens still use `.field` selects | converge on the same listbox component when a screen is touched | UI lane (controls) |
| Prompts/long settings: one full editor per object, versions, dirty state | DONE_AND_VERIFIED | `speech-fullscreen` editor `index.html:13051-13064`; prompt library editor + versions (EVOL-028/AI hub, commit `d7eef0f9`); dirty counter `headerSaveChip` `index.html:217-225` | — | — |

## 7. Section order §5

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| Status: health → map → **one** widget with 4 ribbons → others | **CONFLICTS_WITH_NEW_CONTRACT** | actual order: hero+health `11304/11344` → graph `11457` + sleep card `11518` (same row) → intel card with **3** ribbons `11557-11650` → budgets `12059` → heatmap `12104` → dossier `12199`; «Новые факты» is a **separate** card far below `12014-12047` | move facts ribbon into the intel widget (4 sections), place widget directly under map, move sleep card below the widget; no new components (`v-sfeed` rows reused) | UI lane (status) |
| Analytics = trends/causes/history + memory stories/episodes | DONE_AND_VERIFIED | heatmap/dossier moved to Status, full memory stories to Analytics (commit `d7eef0f9`); `TestEvol030AccessAndAnalytics` `tests/test_webapp_evol_w10_sections.py:647`; shots `w10-sec-*` | — | — |
| Modules: no KPI header, card master toggle, effective state, one path to settings | DONE_AND_VERIFIED | `index.html:5240-5349` (caption, no KPI row, `data-module-global-toggle`, effective line `moduleEffectiveLine`, single «Настроить»); evidence `w10-sec-modules-toggle-1280x900.png` | — | — |
| AI/Speech: one editor per object, Personality merged, Core≠SelfModel | DONE_AND_VERIFIED | AI hub + `#speech-persona` deep-link, Personality moved (commit `d7eef0f9`); `TestEvol028AiHub:489`; `ui_soul1_w*_speech_e2e.py` | — | — |
| Memory / Access / deep routes on the same contract | DONE_AND_VERIFIED | memory catalog + entity detail, access matrix (commits `d7eef0f9`, `1e0ad895`); `TestEvol029MemoryCatalog:536`, `TestEvol030:647`; 19 routes responsiveness `w9-responsive-inventory.json` | — | — |

## 8. Health tint §6

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| States bound to real signals, red glass, text+icon | DONE_AND_VERIFIED | `healthStateFrom()` `app.js:28206-28241`, `healthView` paints only degraded/failed `app.js:28020`; CSS `app.css:5242-5256` (bg alpha 0.5/0.85, no second blur/shadow/overlay); reason+time+label `app.js:28340-28345`; tests `tests/js/evol032_health_glass_test.js:21-46,141-157`; `w10-sec-*` red-surface shots | — | — |
| `warning` = red, lower intensity than `failed`, distinct name | PARTIAL | no `warning` state exists; heartbeat `warning` is mapped onto `degraded` (32% `--err`, alpha .5) and `critical`→`failed` (55%) — intensity order correct (`evol032_health_glass_test.js:152-153`), but no contract-named warning token/label and degraded may also fire from other signals | add explicit `warning` state + fill token below degraded, keep single `systemHealth→glassTint`; do not recolor on log `WARN` | UI lane (glass health) |
| unknown/disabled neutral, data cards never alarmed | DONE_AND_VERIFIED | no fill rule for `unknown`/`disabled` `evol032_health_glass_test.js:45-46`; `paints` flag limited to degraded/failed `app.js:28020` | — | — |

## 9. Ribbons §7

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| Same compact-row grammar, dates, detail opening | DONE_AND_VERIFIED | `.sfeed-item` shared classes `index.html:11578-11650`, `12034-12046`; `statusRowDateLabel`/`statusRowTitle` | — | — |
| Smooth continuous motion, not row-step scroll | DONE_AND_VERIFIED | sub-pixel engine `app.js:28359-28431` (`state.y` fraction, `scrollTop` quantized write), single `DEFAULTS` token (`speedPxS 16`, `resumeMs 2600`, `endHoldMs 1600`, `rewindMs 900`, `startHoldMs 600`) `app.js:28360-28366`; no per-frame data/LLM fetch (`loadDossierFeed` on interval only `app.js:10299-10310`) | — | — |
| Pause on wheel/touch/drag/key/selection, both directions, resume from current position | DONE_AND_VERIFIED | listeners `app.js:28493-28548`, `pauseManual()` keeps live `scrollTop` `app.js:28682-28699`, `hasSelectionInside` | — | — |
| Modal keeps ribbon paused, then resumes | DONE_AND_VERIFIED | `v-sfeed="statusRecordOpen"` on all four viewports (`index.html:11570,11595,11628,12031`), `setModal` `app.js:28701-28707` | — | — |
| reduced-motion: no auto motion, manual access | DONE_AND_VERIFIED | one media-query listener for all viewports `app.js:28435-28446`, `active()` excludes `reduced` `app.js:28558-28562`; `tests/js/evol001_005_widgets_test.js` | — | — |

## 10. Cognitive map §8

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| Map gestures / label priority / composition | **NOT_APPLICABLE** (until EVOL-COG) | `EVOL-COG-MAP` is PENDING, queue «последним» (`plans/features/evol/requirements-map.json` L1240-1335 slices `EVOL-COG-MAP`); backend map API exists and is used by today's card: `GET` graph consumed by `cognitionGraphData` (`index.html:11456-11475`); **map UI (Cytoscape/collision/LOD) not built** — today's card is the legacy vis-network «Граф связей» | implement inside EVOL-COG slice; §2/§5 must not be "closed" by pretending the graph satisfies it | Architect+UI (COG, queued) |
| Ordering dependency | note | §5.3 already requires map above the 4-ribbon widget; the ribbon/widget move must not wait for EVOL-COG (order is satisfiable with the current card) | do ribbon re-grouping now, map replacement later | PM |

## 11. Global search §9

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| EVOL-037 command palette (desktop topbar + `Ctrl+K`, mobile entry → sheet) | **MISSING** | `EVOL-037` status PENDING, slice `EVOL-UI-SEARCH` (`requirements-map.json` L604); no palette code: grep `ctrlKey/metaKey/command-palette` in `web/app.js` → no palette, no `Ctrl+K` handler, no search markup in `web/index.html` | build in its own slice; ASAP-UI-02 only reserves the topbar entry point | Builder (EVOL-UI-SEARCH) |
| Local table filters stay local; result opens exact object with focus+scope | PARTIAL | local filters exist (memory/modules/analytics); deep-links by hash work (`#/ai/prompts`, `#/status/graph`, `#/access/...`); no cross-app search→focus path | part of EVOL-037 | Builder (EVOL-UI-SEARCH) |

## 12. Motion/progress §10, keyboard/safe-area §11

| item | state | evidence | minimal delta | owner |
|---|---|---|---|---|
| Motion only on real state change, no global shimmer/pulsing | DONE_AND_VERIFIED | `--dur-*`/`--ease-out` tokens `app.css:96`; heartbeat indicator driven by real signal `app.js:20793-20852`; reduced-motion guards `app.css:2452,2859`, `app.js:6925-6927` | — | — |
| Progress = real value/period/denominator, unknown ≠ 100% | DONE_AND_VERIFIED | `index.html:11422-11441` renders «нет данных» and width 0 instead of fake fill; budgets card «Без лимита» without bar `index.html:12059+` | — | — |
| Single motion tokens for transitions and ribbons | PARTIAL | CSS tokens + one JS `DEFAULTS` (`app.js:28360`); no single cross-cutting motion token shared by CSS and JS | optional: expose feed timing as CSS/JS token when that file is touched | UI lane (motion) |
| Widths 320/360/390/430, landscape, 600/768/1024, 1440/1920, large font, zoom 200% | DONE_AND_VERIFIED | `evidence/w9-responsive-inventory.json`: 19 routes × 8 viewports, `failures: []`; zoom/font shots `w9-responsive-zoom200-390x844.png`, `w9-responsive-font125-390x844.png`; `w9 `coarse` 44px` shots | re-shoot after nav change | UI lane (nav) + DevOps evidence |
| Keyboard does not hide caret/Save/Close; long IDs no overflow; one loading/empty/error/permission system | DONE_AND_VERIFIED | `--kb-offset` `app.js:7447-7461`, modal padding `app.css:2289`; ellipsis tokens for long names `w9` checks; empty/error states `data-sfeed-empty`/`data-sfeed-error` `index.html:12021-12029`, `spinner`, permission hints `index.html:5281`, `5385-5396` | — | — |
| Back closes inner layer first, not Mini App | PARTIAL | native BackButton policy `static/fullscreen-policy.js` + `index.html:178-183`; per-layer Back for drawer/search/sheet still relies on Esc/close buttons in most surfaces | one Back-stack entry per overlay when touched | UI lane (overlay) |

## §12 — 17 mandatory scenarios → existing evidence

| # | scenario | evidence today | verdict |
|---|---|---|---|
| 1 | phone portrait: no bottom nav, drawer covers all sections, minimal topbar | `evidence/w7-nav-mobile-header.png`, `w7-nav-mobile-drawer.png`, `w9-responsive-phone-*` (после ASAP-UI-02 §2), инвентарь 114+152 ячейки | **PASS** |
| 2 | phone landscape / low viewport | `w7-nav-landscape-drawer.png`, `w9-responsive-land-667x375-*`: одна строка шапки, рейла нет | PASS |
| 3 | identity: no Adminbot logo, avatar+role compact | `w7-nav-fs-ghost-header-390.png` (аватар-инициал + бейдж роли), `w7-nav-desktop-modules.png` (sidebar без слово-марки) | PASS |
| 4 | long chat name, scope for 2 chats + global | `w7-nav-desktop-scope-panel.png`, `w7-nav-mobile-scope-panel.png`, w9 ellipsis check | PASS |
| 5 | «Ещё» = ellipsis, secondary only | `w7-nav-mobile-more.png` — троеточие + только служебное действие и профиль | PASS |
| 6 | stable header, Back order (drawer/search/sheet/fullscreen/TG) | `w7-nav-live-scope-esc-focus-1280.png`, `tests/js/asap8_w2_fullscreen_policy_test.js`, w9 CLS check | PASS (Back-stack partial) |
| 7 | overlay at edges not clipped, focus returns | `w7-nav-case-320x700/z1`, `w7-nav-case-1280x800-*`, `w7-nav-live-scope-panel-focus-1280.png`, `w7-nav-inventory.json` | PASS |
| 8 | common controls on 3 unrelated screens | `tests/js/cfg04_forms_contract_test.js`, `tests/js/asap42_step2c2_layout_test.js`, `tests/test_webapp_evol_w10_sections.py` | PASS (unit/contract level) |
| 9 | module global toggle real state + revert | `TestEvol027Catalog`, `evidence/w10-sec-modules-toggle-1280x900.png` | PASS |
| 10 | four ribbons in one block, autoscroll/pause/resume | `tests/js/evol001_005_widgets_test.js` (engine), but layout is 3+1 blocks | **blocked by §5 grouping** |
| 11 | embedded map swipe scrolls page, «Исследовать» mode | no assertion; legacy vis-network card only | MISSING (EVOL-COG) |
| 12 | fullscreen map, LOD, camera restore | `tools/ui_asap8_w2_fullscreen_e2e.py`, `w7-nav-live-fs-ghost-*` | PARTIAL (legacy graph) |
| 13 | health tint 5 states, red glass optics in motion | `tests/js/evol032_health_glass_test.js`, `tools/ui_win_glass_refraction_e2e.py` | PASS except explicit `warning` |
| 14 | search + deep link, RBAC, return restores draft | deep-links tested per screen; **no global search** | MISSING (EVOL-037) |
| 15 | keyboard/zoom 200%, Save/Close reachable, no overflow | `w9-responsive-zoom200-390x844.png`, `w9-responsive-zoom200-1280x800.png`, `w9-nav-case-320x700-z2` | PASS |
| 16 | per-screen routes not back to old controls | `tools/ui_evol_w10_sections_e2e.py` (6 routes × 1280/390), `w10-sec-*` | PASS |
| 17 | perf: no mass jank/repaint, glass before-after | `tools/ui_win_glass_refraction_e2e.py`, `tests/js/glass_probe_test.js`, `tests/js/glass_refraction_test.js` | PASS (re-check after nav change) |

## Already satisfied vs new conflicts (how the new contract interacts with old tickets)

- Satisfied, do not rebuild: EVOL-022 (glass tokens/components), EVOL-023 (desktop sidebar + collapse + ghost fullscreen), EVOL-024 (topbar overlay/overflow/focus), driver of EVOL-026–030 (section split, modules master toggle, AI/speech editors, memory/access catalogs), EVOL-032 (health→glass tint), EVOL-001–005 (ribbons controller).
- **Уже заменено этой волной (31.10.2026):** EVOL-025 bottom sections panel (`mobile-topnav` + ландшафтный рейл) → единый drawer; W2-SHELL `sidebar-brand`/`mobile-brand` → удалено; W2-SHELL `grid_view` «Ещё» → троеточие; W2-SHELL mobile `header-user span{display:none}` → виден бейдж роли; тесты, пинившие нижнюю панель, переписаны под drawer.
- Остаётся заменить: F11 Status layout (3+1 ribbons, sleep card between map and ribbons) → one 4-ribbon widget under map; `warning`-токен в проходе по glass-здоровью; overlay z-index по `--overlay-z`.
- Тесты, требовавшие отменённый дизайн, переписаны (не «откат контракта»): `asap8_w2_shell_mobile_nav_test.js`, `asap8_d1213_save_contract_test.js`, `asap42_step2c2_layout_test.js`, `cfg04_forms_contract_test.js`, `round1025_shell_breakpoints_test.js`, `round1025_hotfix4/7/9_*`, `round1025_ia_routing_test.js`, `routing_test.js`, `evol_w9_responsive_test.js`, `tests/test_webapp_evol_w7_nav.py`, `tests/test_webapp_evol_w9_responsive.py` + 12 python-файлов и live-инструменты (`ui_evol_w7_nav_e2e.py`, `ui_evol_w9_responsive_e2e.py`, `ui_round1025_matrix.py`, `ui_w4_ui_e2e.py`, `ui_speech_mobile_entry_e2e.py`, `ui_asap8_v6_d1213_e2e.py`, `ui_asap8_w2_fullscreen_e2e.py`).

## Counts

Rows assessed: **59**. DONE_AND_VERIFIED **46**, PARTIAL **9**, MISSING **1** (глобальный поиск EVOL-037), CONFLICTS_WITH_NEW_CONTRACT **2** (Статус: 3+1 ленты и `warning`-семантика — отдельные проходы), NOT_APPLICABLE **1** (COG §8).
Срез навигации/топбара/иконок (§1–§4 + §3): 21 строка, все DONE_AND_VERIFIED этой волной — см. раздел «Срез ASAP-UI-02 §2» ниже.
Conflicts-by-ticket после волны: EVOL-025 ×2 → закрыто; W2-SHELL/asap8 ×3 → закрыто; F11/EVOL-026 layout ×1 и EVOL-032 (`warning`) — остаются.

---

## Срез ASAP-UI-02 §2 — навигация / топбар / иконки (31.10.2026)

Сделано в этой волне (все строки §1–§4 выше, кроме поиска), доказательства:

- **Навигация:** постоянная нижняя панель (`nav.mobile-topnav`, 3 раздела + «Ещё») и её ландшафтный правый рейл удалены полностью — разметка, CSS, метрика `--bottom-nav-h`, наблюдатель `_syncBottomNavMetric`, компьютеды `mobileTopnavItems`/`mobileMoreItems`/`moreMenuTriggerLabel`/`moreMenuActive`/`moreMenuPick`. Единственный механизм — drawer `v-if="iaV2 && hasDrawer"` (`hasDrawer = shellMode !== 'desktop'`) с кнопкой в шапке; закрытый drawer за краем, открытый блокирует скролл контента (`.app-shell.drawer-open main.scroll-area`).
- **Топбар:** одна строка на телефоне: навигация → название раздела (`.header-title`, ellipsis) → селектор области → аватар/инициал + бейдж фактической роли (`.header-user-role`, полное имя в `title`) → ghost-⛶ → «⋯». Крошка на телефоне скрыта (имя не дублируется). `≤419px` имя чата и его аватар в триггере уступают место названию раздела и роли — бейдж области CHAT/GLOBAL не обрезается; `≤359px` дополнительно скрыт `▾` и сокращён бейдж роли. Hit-цели кнопок остаются 44×44 на всех ширинах (включая 320).
- **Иконки:** `[data-drawer-trigger]` — menu-глиф, `[data-more-trigger]` — горизонтальное троеточие (не четыре квадрата); обе — inline-SVG `ui-ic` 20px в той же Material-семье, что ⛶ (шрифтовой сабсет 37 глифов не расширялся, второго набора иконок нет).
- **Логотип:** `.sidebar-brand`/`.sidebar-brand-title`/`.mobile-brand` удалены из разметки и CSS; верхняя строка sidebar — `.sidebar-top` с одной функциональной кнопкой; техническое имя/API/аватар бота не затронуты.
- **Меню «⋯»:** только второстепенные действия (admin-диагностика геометрии ⛶) и профиль (имя/роль/ID области) — списка разделов в нём больше нет.

Проверки: `tests/test_webapp_evol_w7_nav.py` (30 passed, новый класс `TestAsapUi02Navigation`), `tests/test_webapp_evol_w9_responsive.py` (31 passed), `tests/test_webapp_evol_w10_sections.py` (35 passed), 18 JS-юнит-файлов зелёные, `tools/ui_evol_w7_nav_e2e.py` → `EVOL-W7-NAV OK` (инвентарь 19×6 = 114 ячеек, failures 0), `tools/ui_evol_w9_responsive_e2e.py` → `EVOL-W9-RESPONSIVE OK` (19×8 = 152 ячейки, hScroll 0 / offscreen 0 / clipped 0). Живой Chromium: 320×700, 390×844, 667×375, 812×375, 768×1024, 1024×768, 1280×800, 1440×900.

Открытые строки среза: **приложение-wide поиск (EVOL-037)** — отдельная очередь, точка входа в топбаре зарезервирована (сейчас её нет by design).

---

Итог: из 59 проверенных строк — 46 соответствуют и подтверждены кодом/тестами/живым рендером (включая весь срез навигации/топбара/иконок §1–§4), 9 частичные (деталь-стандарт, z-index-слой, select/combobox, warning-токен, контрольные локальные отступы, four-ribbon группировка, Back-стек для поиска), 1 отсутствует (глобальный поиск EVOL-037), 2 противоречат новому контракту (разорванные 4 ленты в Статусе + сопутствующие токены) и 1 не применимо (когнитивная карта ждёт EVOL-COG).
Главные оставшиеся дельты: свести четыре ленты в один блок сразу под картой (Статус), добавить `warning`-токен в проходе по glass-здоровью, выровнять overlay z-index по `--overlay-z`, затем EVOL-037 (поиск) и EVOL-COG (карта) как отдельные очереди.
Навигационная часть ASAP-UI-02 §2 закрыта: нижней панели нет, drawer один, логотип удалён, роль видна, «⋯» — троеточие, ландшафтного рейла нет.
