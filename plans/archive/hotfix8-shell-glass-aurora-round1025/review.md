# review.md — HOTFIX8 `hotfix8-shell-glass-aurora-round1025` (Step 5 @Reviewer, T-2783)

**Feature-ID:** `hotfix8-shell-glass-aurora-round1025`
**Status: Approved**
**Дата:** 22.09.2026 · **База:** HEAD `a1e6db3`(+незакоммиченное рабочее дерево) · **APP_VERSION 2.58.10 (bump T-2786 — Block G, вне ревью-гейта)**

## Checks performed (независимо воспроизведено)

| # | Проверка | Команда/источник | Результат |
|---|---|---|---|
| 1 | Синтаксис JS | `node --check web/app.js` / `telegram-init.js` | OK (0) |
| 2 | JS-маркеры | `node tests/js/round1025_hotfix8_shell_aurora_test.js` | `HOTFIX8-SHELL-AURORA-OK` |
| 3 | Целевые pytest | `py -3 -m pytest tests/test_webapp_hotfix8_round1025.py …round1020.py …js_unit.py -q` | **100 passed** |
| 4 | Полный pytest | `py -3 -m pytest -q` | **8266 passed / 1 skipped / 5 failed** — совпадает с заявленным |
| 5 | 5 падений = env | baseline-worktree `a1e6db3` (тот же набор тестов) | **те же 5 FAILED** → пред-существующие (`InputRichMedia`/`rich`, вне web-UI) |
| 6 | Playwright 5 режимов/10 вьюпортов | `.venv\Scripts\python.exe tools/ui_round1025_matrix.py` | **failures: 0**; `tools/_ui_round1025_raw.json` |
| 7 | `git diff --check` | — | 0 whitespace-ошибок |
| 8 | Δ DDL / Δ каталога | diff (нет `services/**`, схем) + `test_catalog_invariants` | **0 / 0** (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / Settings 418) |
| 9 | R18 | `git tag -l`, `git stash list`, `git check-ignore` | тег `pre-round1025-hotfix8`→`a1e6db3`, `stash@{0}` целы; `current_task.md` — gitignored, не изменён/не коммичен |

## Requirement / evidence coverage (UPD2 §4/§6/§7/§9)

- **§4 shell — ДА.** Токены в `app.css`: `--shell-bg rgba(24,28,38,.72)`, mobile `.78`, border `.08`, highlight `.06`, shadow `0 8px 24px rgba(0,0,0,.18)`, `blur(18px) saturate(115%)`. Computed из raw.json: desktop sidebar/header `.72`, mobile header/bottom-nav/more-sheet `.78`, blur `blur(18px) saturate(1.15)`. Карточные `--glass-bg .5`/`-strong .85` не тронуты (marker `test_cards_not_repainted`).
- **§4/§9 нет цветной линзы — ДА.** Панели → `data-glass="shell"`; `shellA=False`; `::before` sidebar/header `content:none, bg:none`; `[data-glass="a"]::before` остаётся только у карточек. Sheen `::after` — бесцветный linear, `opacity: var(--shell-sheen-opacity)=.05`, `z-index:-1`, без `mask-image`.
- **§3 слои — ДА.** shell `rgba(24,28,38,.72/.78)` ≠ card `rgba(21,27,42,.5)`; фон — отдельный задний слой `z-index:0` < `#app{z-index:1}`.
- **§9 AA — ДА (пересчитано).** Их функции: single-layer teal 7.33 / mobile 7.55 (совпало с отчётом). Мой пессимистичный пересчёт (3 наложенных teal-слоя `.30`): text-2 **5.70:1**, text-1 **10.88:1**, mobile **6.24:1** → ≥4.5 PASS.
- **§6 фон — ДА.** 5 blob (`.b1…b5`), `animation-name=aurora-blob-1` (не static), `body::before aurora-flow 75s + aurora-morph 105s`, `body::after aurora-flow-rev`; палитра teal/blue/violet/indigo, оранжевого нет; пауза: `hidden {cls:true, ap:paused}`; reduced-motion `beforeAnim:none`; нет WebGL/`backdrop-filter:url()`/CDN/новых библиотек (rg: 0 совпадений).
- **§7/§5 геометрия — ДА.** sidebar **216** ∈[208,224]; gap header↔карточка **16** ∈[16,20] (normal и fullscreen); h-scroll 0 на всех вьюпортах; mobile-порядок (селектор под заголовком) и safe-area — checks пройдены; bottom-nav `bottom=644=stableHeight` (320×700); fullscreen: `.app-shell` виден, `h==innerH`, ничего не режется.
- **Validator:** флаги OFF → `shell-v3-off` (hotfix7-значения без возврата линзы) и `bg-wash-legacy` (legacy conic) присутствуют; reduced-motion/hidden/320/fullscreen подтверждены матрицей.
- **Инварианты:** F1/F2/F3/F4/F5/§61, `computeBottomOffset`, ADR-1024-24, `persistItems`, SaveBar (`sticky-save`/`scroll-padding-bottom`/`.sticky-spacer` не менялись) — регресс зелёный.

## Blocking findings

**Нет.** Критических/высоких/блокирующих требований-дефектов не подтверждено.

## Non-blocking debt (Low)

| ID | Находка | Доказательство | Действие |
|---|---|---|---|
| L-H8R-1 | В `round1025_hotfix8_contrast.md` `.bottom-nav-label` подписан как `--text-2 #AAB6C8`, фактический computed — `#F4F7FB` (text-1). Ошибка консервативна (реальность ярче → ratio выше). | raw.json `panelText.bottomNavLabel='rgb(244,247,251)'` | уточнить подпись @Builder |
| L-H8R-2 | Матричный F2-чекер снял количественный порог `body::before opacity>0.32` (виньетка) и заменил требование `grad-spin` на «любая живая анимация». Прямого bound яркости aurora нет; компенсировано `_hotfix8_failures` (blob≥3 + anim) и AA-контрастом панелей. Мой worst-case пересчёт всё равно PASS. | `tools/ui_round1025_matrix.py` diff, `_f2_failures` | опционально вернуть bound яркости |
| L-H8R-3 | `deployment.md` (T-2745) заявляет baseline `8251 passed / 0 failed / 0 skipped`; на этом окружении 5 env-падений воспроизводятся уже на `a1e6db3`. Документарное расхождение, не влияет на код. | baseline-worktree run | поправить @DevOps при T-2787 |
| L-H8R-4 | reduced-motion в матрице проверяет только `body::before` (не `.aurora-blob`); legacy-путь флагов OFF проверен статикой/маркерами, не рендером. Покрыто CSS-маркерами. | `F2_RM_PROBE_JS`, marker-тесты | bounded follow-up |
| L-H8R-5 | `[data-glass="shell"]` навешивает полный `border`; у sidebar/bottom-nav видимыми остаются боковые/нижние 1px-кромки (специфичность не переопределяет). Измеряемого влияния нет. | computed border panels | косметика, опц. |

## Unavailable checks

- **Реальный Telegram WebView** (fullscreen/safeArea/FPS 5×`52vmax` blob + SVG `filter:url(#lg-lens)` на 5 shell-`::after`): headless не воспроизводится → **live-гейт владельца T-2776** (зафиксирован как единственный внешний гейт).
- **SaveBar↔клавиатура на малой высоте**: headless не воспроизводимо; структурные инварианты round1020/SaveBar-тесты зелёные → тот же live-гейт.
- Полная геометрия bottom-nav в fullscreen проверена косвенно (`.app-shell`/heartbeat/gap) — см. T-2776.

## Handoff

**RESULT: Approved — HOTFIX8 `hotfix8-shell-glass-aurora-round1025` (T-2783 @Reviewer).** Доказательства: `plans/features/hotfix8-shell-glass-aurora-round1025/review.md`, `plans/reports/round1025_hotfix8_{contrast,ui_report}.md`, `tools/_ui_round1025_raw.json`. Блокеров нет; Low L-H8R-1…5 — follow-up. Дальше: **T-2784 @Scanner** → **Block G (T-2785 merge §62 → T-2786 bump 2.58.11 → T-2787 deploy + live-гейт T-2776 → T-2788/T-2789)**.
