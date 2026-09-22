# REVIEW — hotfix10 `hotfix10-liquidglass-rollback-shell-geometry-round1025` (T-2865, итерация 2)

- **Reviewer:** @Reviewer (независимо; живой WebView не проверялся)
- **Вердикт:** **Approved**
- **База:** HEAD `5184584` + рабочее дерево; UPD4 `plans/current_task.md:7267-7482`; spec/ADR-1025-18/tasks/evidence.
- **Воспроизведено мной:** `node --check` ×3 OK; JS-юниты **35/35 OK**; `.venv python -m pytest -q` → **8319 passed**; `tools/ui_round1025_matrix.py` → **failures: 0** (10 вьюпортов normal+fullscreen, OFF на 5 ширинах); `git diff --check` чисто; Δ каталога=0 (`param_catalog.py` без `UI_LIQUID_GLASS_LIB`, 459/98/96/21/418); Δ DDL=0 (миграции не тронуты).

## Находки итерации 1 — статус

| # | Sev | Статус | Доказательство (мой независимый прогон) |
|---|---|---|---|
| H-1 | High | **Закрыто** | `.status-block`: на 320/360/390/430 + fullscreen `clientH==scrollH` (567/532/508/508), `elementFromPoint` центра `.hb-canvas`/`.status-block__bot`/`__server` = сам элемент (`hit=True`). Фикс `main.scroll-area { grid-auto-rows: max-content }` (app.css:1132, вне media-query). Откат фикса в живом DOM (`grid-auto-rows:auto`) → гейт даёт **failures=1** на 390/430 normal+fullscreen (`scrollH=508 > clientH=32`) → **гейт не вакуумный**. Desktop/fullscreen тоже `clientH==scrollH` (227). |
| L-H10-1 | Low | **Закрыто** | `v-if="liquidGlassLib"` на `[data-glass-surface]` (index.html); OFF-проба на 320/360/390/430/1280: `surfaceCount=0, psTotal=0, mountedCount=0`; ON: `surfaceCount=1, psTotal=4`. |
| L-1 | Low | **Закрыто** | Живые ON→`dispose()`: root теряет `data-glass`/`data-uid`/`data-render`/`data-lg-*`/inline `--g-radius|--g-tint|--g-margin` и класс `ps-glass`; `psChildren=0`. Остаётся пустой `style=""` — безвредно. |
| L-2 | Low | **Закрыто** | `.env.example` обновлён: `UI_LIQUID_GLASS_LIB (default OFF)`, «только frost-fallback» убрано; проверено тестами. |

## Подтверждённые требования (повторно, без регрессий)

- §1/§2: `UI_LIQUID_GLASS_LIB` default OFF; целевой SELECTOR только `[data-glass-surface]`; `purge/clearAttrs` идемпотентны; OFF `0/.ps-glass*`, ON `psFunctional=[0,0,0]`, after unmount `0`; режим `frosted` (рефракция только при `.ps-glass__refract`); белые слои не применяются к функц. целям, `--glass-paper` тёмный (#151B2A).
- §3: `main.x=216`, `right=innerW`, `background=rgba(9,13,23,0.62)`, лимит 1100px, отрицательных margin нет.
- §4: второй вычет снят; `.more-sheet` — один offset; legacy `.bottom-nav` fixed только под `.shell-layout-legacy`; nav 4×h44 `hitSelf`, `bottom ≤ usable`.
- §6/фон: `__AuroraFlow.resize` экспортирован и вызывается (`_onResize`/`setFullscreenFromTma`/`visualViewport`/`ResizeObserver`); `setSize`+`gl.viewport`+`uRes` из buffer; canvasRect = viewport; кадры 0/5/10/20с движутся; новых CSS-градиентов поверх WebGL нет.
- Инварианты: CSP same-origin (vendored, без CDN/инлайна); тег `pre-round1025-hotfix10` и `stash@{0}` на месте; `current_task.md` не изменён; APP_VERSION 2.58.13; маркер-тесты обновлены атомарно (27 в H10-файле), не ослаблены; `main.scroll-area` grid-фикс класс/дизайн сердцебиения не затронул.

## Новые находки

Нет.

## Non-blocking debt (не блокирует)
- Trivial: после `dispose()` на root остаётся пустой атрибут `style=""` (все `--g-*` сняты) — косметика, влияния нет.

## Unavailable checks
- Живой Telegram WebView (WebKit/Android/iOS): реальные инсеты, нативный fullscreen, FPS — **PENDING OWNER VERIFICATION** (UPD4 §7/§8). Дефект H-1 — кросс-браузерный CSS-дефект, подтверждён в Chromium; результат Chromium не выдаётся за WebView. Дефект не объявляется устранённым по сборке/вердикту Reviewer.

## Handoff
`RESULT: Approved — @orchestrator: T-2865 закрыт, можно запускать T-2866 (@Scanner) и T-2867 (деплой, HTTP 200 ≠ layout); не объявлять визуальный фикс закрытым до live-проверки владельца (PENDING OWNER VERIFICATION); после деплоя — немедленно F6 (T-2869).`
