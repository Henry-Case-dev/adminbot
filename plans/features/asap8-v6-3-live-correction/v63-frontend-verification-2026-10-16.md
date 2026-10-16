# V63-FE-2 — Frontend verification verdict (ASAP 8 v6.3, UI lane)

**Lane:** V63-FE-2 (verify + evidence only, no application-code changes) · **Date:** 2026-10-16
**Candidate fingerprint (exact, current worktree — NOT a commit):**
HEAD `a854ad953d360e0dcda1174b3a171cdecebc0417` **+ uncommitted worktree delta**:
`web/app.js` sha256 `5F8FEFF6A0C2FEC2B7DBEAAE97088F11B466184008ED9014806145A20838EF92`,
`web/index.html` sha256 `E209D5FAF7E8E54A907A35C570ABA9F574CBFA9FBAE2AE1FC8C95E53BE26B3E0`,
`web/static/app.css` sha256 `FBEBC0618F119616199CC5D2E6F72DAE39E7CC228DFC7F490B8ECA3D21E6D2A7`
(+ `services/disk_retention.py` +34, `services/param_catalog.py` +18). All six suites serve the
**working-tree `web/`** directory, so every number below belongs to that fingerprint.

---

## 1. Artifact authenticity — the "430/768 do not exist" claim is FALSE

The prior audit counted PNGs only in the older feature folders and missed
`evidence/v63-frontend/`. Truth established from the files themselves (PNG IHDR + pixel
variance, script `png_verify.py` → scratch `v63fe/png_verify.json`):

| Viewport class | PNGs | IHDR confirmed | Bytes / pixel σ | Blank? |
|---|---|---|---|---|
| 320×700 | 8 | yes | 39 112 – 90 015 B · σ 30.4–40.7 | no |
| 360×780 | 5 | yes | 63 993 – 99 919 B · σ 30.7–36.1 | no |
| 390×844 | 9 | yes | 49 181 – 110 306 B · σ 28.9–38.6 | no |
| 430×932 | 5 | yes | 88 889 – 122 145 B · σ 29.7–35.7 | no |
| 667×375 (landscape) | 5 | yes | 66 820 – 75 427 B · σ 26.9–34.9 | no |
| 768×1024 | 5 | yes | 113 386 – 478 413 B · σ 27.5–34.3 | no |
| 1024×768 | 5 | yes | 123 554 – 505 820 B · σ 24.9–34.1 | no |
| 1440×900 | 7 | yes | 113 909 – 531 662 B · σ 24.4–31.2 | no |

49 PNGs, all 8-bit truecolor, every one non-blank (min 0 / max 255, σ ≥ 24).
`v63-frontend/` is the **largest** PNG set in the feature (49 of 157 total). The audit's
"430/768 missing" statement is **wrong**; its narrower statement is right — see below.

### Viewport capture vs full-page scroll (harness source preserved)

The generating script is recoverable (`scratch/v63fe/v63fe_shots.py`, port 8861, reusing the real
suite harness `ui_round1025_matrix._Handler` + the real `/api/*` stubs of all six suites; the SDK
is `ui_asap8_w2_fullscreen_e2e.mock_sdk_js`). Its `SCENARIOS` tuple sets
`full_page=True` **by design for the `status` route only**, everything else viewport-sized.
Measured against IHDR:

| File | IHDR | Verdict |
|---|---|---|
| `status_768x1024.png` | 768×**4780** | **full-page scroll** (content 4667 px) — audit correct |
| `status_1024x768.png` | 1024×**3991** | **full-page scroll** (not caught by the audit) |
| `status_1440x900.png` | 1440×**3939** | **full-page scroll** (not caught by the audit) |
| `status_{320,360,390,430,667}*.png` | = viewport | genuine viewport capture (content fits) |
| all `analytics_*`, `modules_*`, `style_editor_*`, `cover_editor_*`, `more_*`, `*_dropdown_open_*`, `fullscreen_*` | = viewport | genuine viewport capture |

**Genuine full-viewport evidence exists for all 8 viewport classes.** Gap: `status` has **no**
single-viewport capture at 768/1024/1440 (`w3-evidence-status/w3_status_desktop_1440.png` is
1440×3934, also full-page). `fullscreen_tdesktop_1440x900.png` is a **1440×900 viewport** capture
but is **not** fullscreen: `fsBtn=null, fsAriaLabel=null, fsVisible=false`, no `fullscreen-mode`
class (measurements `fullscreen/tdesktop_1440x900`). It documents the U07.3 desktop policy
(control hidden), so **there is zero fullscreen-mode capture at any desktop size**.
Real rendered inspection (Browser Use, `execute`): `status_320x700.png`, `more_menu_open_390x844.png`,
`analytics_dropdown_open_390x844.png`, `fullscreen_390x844_fs.png`, `status_768x1024.png`,
`fullscreen_tdesktop_1440x900.png` — all render the real app, header row A + row B + content,
no horizontal overflow, no clipped controls.

---

## 2. Measurements / probe findings (real, from the preserved artifacts)

| Claim | Evidence | Result |
|---|---|---|
| horizontal overflow | `_v63fe_measurements.json` 43 states | `hOverflow=false`, `scrollWidth==vw` in **43/43** |
| console errors | `_v63fe_measurements.json` `console_errors` | **`[]`** (0 error states / 43) |
| header budget U01.3 | measurements | mobile 116.2, compact(768/1024) 113.4, desktop 109.4, landscape 93.8 — all ≤124 |
| row B | measurements `nav` | 4 equal segments, h=47.2 (mob) / 35 (667), last item right == vw−16 |
| U02 dropdown at 320/390 | `_v63fe_probe2.json` `u02` | `ddDisplay=block`, trig `Раздел:Обзор▾`, 8 tabs hidden at 1024 (`none`) |
| U02 full list | `_v63fe_probe2.json` `*_options` | exactly 7: Обзор / Процессы / Запуски / Инциденты / Память и интеллект / Модели и расходы / Саммари — **«Логи» absent** |
| «Ещё» content | `_v63fe_probe2.json` `more` | open, 5 items: Справка, ИИ, Память, Доступы, PERMsoc |
| glass tiers | `_v63fe_probe2.json` `glass` | modules `[data-glass]`=2, `.lg-panel*`=0; status 6 / hero-lens 1; analytics 6 / `.glass-panel`=3; `scrollW==vw` all |
| fullscreen mode | measurements `fullscreen/{320,390}_fs` | `shellClass` gains `fullscreen-mode`, `aria-pressed="true"`, label «Выйти из полноэкранного режима», header 118.6 |
| tdesktop | measurements `fullscreen/tdesktop_1440x900` | control hidden — policy shot, **not** a fullscreen shot |

### Gap closure performed by this lane (new `_v63fe2_*` artifacts)

- `_v63fe2_reverify.json` — 32 states (8 viewports × status/analytics/modules/editor) re-measured
  by me on the current worktree: **0 hOverflow, 0 console errors**, header heights reproduce
  exactly (116.2/113.4/109.4/93.8) → the preserved artifacts match the current candidate.
- `_v63fe2_u02_more.json` — U02 now proven at **all** <768 widths incl. landscape
  (`ddDisplay=block`, the exact 7 options, `menuInViewport=true`) and **tabs `display:block` at
  768/1024/1440**; «Ещё» 5 items + Esc closes + focus returns at 320/360/390/430/667.
  Lane 1 had only 320/390 — 360/430/667 were DOM-unproven before.
- `_v63fe2_rowa_safearea.json` — U01.2: chat `ID` **absent** from the permanent header in 5/5
  cases, selector `title` = full long Russian name, `scrollWidth==clientWidth` (no overflow),
  fs hit-box 49×44 / icon 18×18, no overlap with the selector. U07.2: `contentSafeAreaInset.top`
  47/56 and landscape top 24 **are** honoured (fs button y 10→57/66/30), 0 console errors.

---

## 3. Six frontend suites — real results (current worktree, each script's own harness)

Run: `.venv\Scripts\python.exe tools/<script>` from repo root (no `--help`, no rewrite).

| # | Suite | Result | Counts | Failing node IDs |
|---|---|---|---|---|
| 1 | `ui_asap8_w2_shell_e2e.py` | **PASS** | 129/129 checks, console 0 | none (`w2_shell_e2e.json:failed_checks={}`) |
| 2 | `ui_asap8_w2_fullscreen_e2e.py` | **PASS** | 7/7 scenarios, 70 checks (21+10+4+2+13+5+15) | none |
| 3 | `ui_asap8_w3_editor_e2e.py` | **PASS** | 40 passed / 0 failed | none |
| 4 | `ui_asap8_w3_modules_e2e.py` | **PASS** | 45/45 checks, console 0 | none |
| 5 | `ui_asap8_w3_analytics_e2e.py` | **PASS** | 74 passed / 0 failed, 21 screenshots | none (`failed:{}`) |
| 6 | `ui_asap8_v63_w3_status_e2e.py` | **PASS** | 26/26 checks, console 0 | none |
| | **total** | **6/6 PASS** | **384 checks, 0 failures, 0 console errors** | — |

All suites were runnable (system Python lacks `playwright`; the `.venv` interpreter has it).
No suite was unrunnable in this environment.

---

## 4. Per-UI-requirement verdict (source: `source-lines-37423-EOF.md` L121–L336, L418–L449)

| Req | Verdict | Basis (exact artifact / command) |
|---|---|---|
| U01.1 | VERIFIED-BY-AGENT | shell 129/129 (`m*:rowB=4`, `порядокСтатусАналитикаМодули`, `все4видныЦеликом`, `desktop:sidebarВидна>=1200`, `desktop:mobileTopnavНЕТ`) + `_v63fe2_u02_more.json` + `more_menu_open_390x844.png` |
| U01.2 | VERIFIED-BY-AGENT | shell `zoom200:селекторКомпактен<половиныRowA` + `_v63fe2_rowa_safearea.json` (`chatIdInHeader=false` ×5, `title`=full name, `scrollW==clientW`) |
| U01.3 | VERIFIED-BY-AGENT | shell `*:headerВБюджете<=124` (116.2/113.4/109.4/93.8), `*:rowB40-50` (47.2), `landscape667:rowB30-50` |
| U01.4 | VERIFIED-BY-AGENT | shell `menu_flow` 16 checks ×6 viewports + `menu:deepLink#/ai`, `menu:менюЗакрытоПослеПерехода`, `menu:триггерЕщё•ИИ` + `_v63fe2_u02_more.json` (escCloses/focus) |
| U01.5 | VERIFIED-BY-AGENT | measurements `contentStart.y == headerH` (116/113/109/94) on all 43 states; `status_*.png` |
| U02.1 | VERIFIED-BY-AGENT | shell `u02.1:desktopТабыВидны`, `u02.1:desktopDropdownСкрыт` + `_v63fe2_u02_more.json` (`tabsDisplay=block`, 8 tabs @768/1024/1440) + `after_u02_desktop_1280.png` |
| U02.2 | VERIFIED-BY-AGENT | shell `u02:*` 17 checks (`полныйСписок7`, `логиНЕТвСписке`, `опцииВВьюпорте320-390`, `ariaSelectedНаОбзоре`) + `_v63fe2_u02_more.json` (all <768) + `analytics_dropdown_open_{320,390}.png` |
| U02.3 | VERIFIED-BY-AGENT | shell `u02:hashTabMemory`, `u02:deepLinkSummary`, `u02:возвратОбзор`, `u02:deepLinkRunsФильтр`, `u02:фильтрStatusСохранён`; analytics 74 checks |
| U03.1–U03.4 | VERIFIED-BY-AGENT | status suite 26 checks (`sleep_panels_single`, `no_dup_sleep_badges`, `no_1970`, `sleep_unknown_label`, `expired_layout`, `mem_tech_present`, `initiative_*`, `experience_windows`) + `status_*.png` |
| U04.1–U04.2 | VERIFIED-BY-AGENT | status suite `logs_in_status_grid`, `log_rows_rendered`, `log_counters`, `log_filters_present`, `copy_row_no_crash`, `analytics_no_logs_tab/block`, `legacy_redirect_canon`, `anchor_scroll_visible` |
| U05.1 / U05.2 | VERIFIED-BY-AGENT | analytics suite 74 checks + 21 full-screen screenshots (`w3a_*` 1440/320/390/667) |
| U05.3 | **OWNER-ONLY (data part)** | "7 визуализаций D12 на **подтверждённых** данных" needs real production data; stub render path is agent-checked, values are not |
| U05.4 | VERIFIED-BY-AGENT | full-screen screenshots exist at 1440/320/390/667 for overview/processes/runs/memory/models/story cards (21 in `w3-evidence-analytics`) |
| U06.1–U06.3 | VERIFIED-BY-AGENT (UI contract) | editor suite 40 checks + `cover_editor_{320,390,1440}.png`; **real provider** "Test Edit → результат/история" and actual model/route/limit = owner-only |
| U07.1 policy adapter | VERIFIED-BY-AGENT (mock) | fullscreen suite 7/7 / 70 checks (route-mock SDK per `w2-contract` §4.2.1) |
| U07.2 mobile geometry | VERIFIED-BY-AGENT (mock) | S1: visual 32×32, hit 49×44, aria by ACK; `_v63fe2_rowa_safearea.json` top/bottom insets honoured |
| U07.2 horizontal insets | **FAILED** | `_v63fe2_rowa_safearea.json` case `667_safearea_cutout`: with `safeAreaInset/right=44` the fs hit-box `right=651` while the safe right edge is `667−44=623` → 28 px of the hit target sits inside the native right zone. Left/right insets are ignored; only top/bottom are applied. Reproducible with the mock SDK |
| U07.3 / U07-SYM-DESKTOP | **OWNER-ONLY** | real Windows Telegram Desktop: native HWND/drag/close, actual window after ⛶. `S3/S7_tdesktop_hidden` prove only the *policy* (control hidden), not the native outcome |
| U07-SYM-ANDROID | geometry VERIFIED-BY-AGENT / native adjacency **OWNER-ONLY** | 30–34 px visual + 44 px hit agent-measured; real ✕/⋮ adjacency and "tap near ⋮ not intercepted" need the real Android client |
| U07-LAUNCHMODE | **OWNER-ONLY** | BotFather Main App `Launch Mode=Fullscreen` (no second `requestFullscreen`, no programmatic BotFather edit) |
| U08.0–U08.2 material/contract | VERIFIED-BY-AGENT | `_v63fe_probe2.json` `glass` tier map + `w2-evidence-glass` 41 PNG (before/after on agent-made grid & wave) |
| U08.3 real refraction / U08.5 four signs | **OWNER-ONLY (visual judgement) + agent evidence present** | `w2-evidence-glass/u08-5-after-grid-hero-left-edge-3x.png`, `u08-5-measure-hero-on/off.png`, `u08-5-3-contrast-hero-src.png`, `u08-5-*-reduced-motion*` are agent-made; "линия заметно изгибается у края" on the **real Telegram WebView** is the owner's call |
| U08.4 per-screen tiering | VERIFIED-BY-AGENT | status hero-lens 1 (`data-glass="a"` 2), modules 2, analytics 6/3; `scrollW==vw` everywhere |
| V01–V04 | out of frontend scope | backend/cover initiative, Experience, Memory, Cover — not this lane |
| V05 UI/operational | VERIFIED-BY-AGENT | suites 1/4/6/5: 3 tabs+«Ещё», single sleep block, Status-only logs, analytics tabs, no h-overflow at 320/390/landscape |
| V06 | **OWNER-ONLY** | BotFather Main App in Windows Telegram Desktop with `Launch Mode=Fullscreen`, real drag/close, real TMA ack |
| V07 | **OWNER-ONLY** | edge distortion visible behind the hero on a real client + low-end Android FPS + reduced-motion on real device |

**Counts: 25 VERIFIED-BY-AGENT · 1 FAILED (U07.2 horizontal safe-area insets) · 9 OWNER-ONLY
(U05.3, U06 real-provider part, U07.3/U07-SYM-DESKTOP, U07-SYM-ANDROID native adjacency,
U07-LAUNCHMODE, U08.3/U08.5 visual judgement, V06, V07).**

---

## 5. Owner checklist (minimal, exact)

1. **Windows Telegram Desktop** — open Main App from BotFather, press the web ⛶ in the AdminBot
   header, confirm the window does **not** collapse into a small undraggable/unclosable box; then
   press it again and confirm a working exit. Record client version + `isFullscreen` before/after.
2. **BotFather → Main App → Launch Mode = Fullscreen** — reopen and confirm no second
   `requestFullscreen` is sent and an **exit** button is offered immediately; never let the code
   edit BotFather itself.
3. **Android Telegram portrait + landscape** — check ⛶ is a small round 30–34 px control in the top
   web strip next to ✕/⋮, that taps on ⋮ and ✕ still work, and that the hit area does not cover the
   native right zone in landscape (this is the FAILED item above — re-check after the fix).
4. **Real safe areas** — iPhone notch and Android landscape cutout: header/⛶ must stay below the
   inset, no horizontal overflow, no clipped control.
5. **Status/Analytics/Modules at 320/390 and 1440 on the real client** — row B fully visible,
   «Ещё» sheet opens/closes, analytics dropdown lists all 7 sections and never «Логи».
6. **Liquid Glass** — on the real Status hero confirm the line/wave bends behind the rim and the
   centre stays readable; check Modules cards and Analytics tables stay solid; note FPS on a
   low-end Android and with reduced motion.
7. **Style editor** — one real Test Edit against a real Base + logo reference; confirm the compiled
   prompt ≤800 chars, the actual model/route/limit shown, and that text selection survives polling.

---

## 6. Incidental findings

| Class | Finding |
|---|---|
| current-blocker | U07.2 ignores horizontal (`left`/`right`) `safeAreaInset`/`contentSafeAreaInset` for the fullscreen control — hit-box overlaps the native right zone in landscape cutouts (`_v63fe2_rowa_safearea.json`). Agent-reproducible, one-layer fix. |
| related-nonblocking | `status_768x1024/1024x768/1440x900.png` and `w3_status_desktop_1440.png` are full-page, not single-viewport — owner asked for "скриншоты всего экрана", which these satisfy, but there is **no** desktop single-viewport status capture anywhere in the feature. |
| related-nonblocking | `fullscreen_tdesktop_1440x900.png` name implies a fullscreen demo; its content is the tdesktop-hidden policy shot. No fullscreen-mode capture exists at any desktop size. |
| related-nonblocking | No dropdown-open screenshot at 360/430/667 and no «Ещё» screenshot at 320/360/430 (DOM now proven by `_v63fe2_u02_more.json`). |
| related-nonblocking | U01.2 accessible name: chat selector `title` carries the full name but `aria-label` is the generic «Выбор контекста» (`_v63fe2_rowa_safearea.json`) — full name is reachable, but not as the computed accessible name. |
| related-nonblocking | Glass: `.lg-panel*` counts are 0 (vendored `liquidglass` lib stays OFF); the U08.2 layer structure is realised via `[data-glass]` / pseudo-layers, which the source permits, but the literal class contract is not observable in the DOM. |
| uncertain | Whether `S3/S7` tdesktop-hidden policy plus owner confirmation is accepted as closing U07.3 — that is a Reviewer/Architect call, not a Builder one. |

## 7. Evidence index (this lane)

- preserved, verified: `evidence/v63-frontend/_v63fe_measurements.json`, `_v63fe_probe2.json`, 49 PNG
- new: `evidence/v63-frontend/_v63fe2_reverify.json`, `_v63fe2_u02_more.json`, `_v63fe2_rowa_safearea.json`
- suites: `w2-evidence-shell/w2_shell_e2e.json`, `w2-evidence-fullscreen/_results.json`,
  `w3-evidence-editor/w3_editor_e2e_after.json`, `w3-evidence-analytics/` (21 PNG),
  `w3-evidence-status/`, `w2-evidence-glass/` (41 PNG)
- harness sources (recovered, read-only): `scratch/v63fe/v63fe_shots.py`, `v63fe_probe2.py`
- external claims: none required in this lane (no provider/API/library facts asserted).

**@Orchestrator** — lane V63-FE-2 complete: 6/6 suites green (384 checks, 0 console errors), the
"430/768 missing" audit claim refuted, one agent-reproducible defect found (U07.2 horizontal
safe-area), 9 items need the real Telegram client and are handed to the owner checklist.
