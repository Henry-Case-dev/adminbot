# review.md — `polygonal-luminescence-round1026` (Step 5 @Reviewer, T-3213)

- **Feature-ID:** `polygonal-luminescence-round1026`
- **Status:** **Approved**
- **Базис:** HEAD `9d046e5` (== `origin/master`, == annotated-тег `pre-round1026-visual`). Изменения — рабочим деревом (не закоммичены) + новые файлы.
- **Маркер:** `POLYGON-LUMINESCENCE-OK`. **APP_VERSION** `2.58.19` (синхронно settings/README/`?v=`).
- **Вердикт:** блокеры Critical/High/Medium отсутствуют. Все заявленные @Builder цифры воспроизведены независимо. Блок J (glass-интеграция) корректно заблокирован гейтом §13.2. Живое WebView-качество — **PENDING OWNER VERIFICATION**.

## Проверки (выполнено независимо)

| Проверка | Результат |
|---|---|
| `node --check` polygon-background.js / app.js / glass.js | OK |
| `node tests/js/*.js` | **43/43, 0 failing** |
| `.venv python -m pytest -q` | **8520 passed, 0 failed** (1 warning, stdlib) |
| `tools/ui_round1026_polygon.py` | **0 failures**, errors=0 по всем 4 кейсам |
| `tools/ui_round1025_matrix.py` (§71, polygon OFF) | **0 failures** (10+low-TG) |
| `git diff --check` | чисто (только LF→CRLF warnings) |
| Δ каталога | **0**: `param_catalog.py` не тронут; 467/426/100/98/21 |
| Δ DDL | **0**: `services/pg_db.py`/`db/**` не менялись |
| SHA vendor delaunator | `7707D7FE…C1BE` == README/тест |
| `Math.random` в модуле | **0** (только в комментариях); seed `20260923` + mulberry32 |
| Один рендерер | Playwright `visibleBgCanvases=1`, `#aurora-flow-canvas`отсутствует; `aurora-flow.js` не самостартует |
| R17/R18 | `current_task.md` не изменён; тег `pre-round1026-visual`→`9d046e5`; `var/backups/visual-round1026-*`; `stash@{0}` цел |

## §14/§15 — воспроизведённые цифры (из `tools/_ui_round1026_raw.json`)

| Кейс | nodes/tris | median_shift | corr(0,20с) | lilac | cyan | edge | local_ratio |
|---|---|---|---|---|---|---|---|
| desktop Статус | 110/189 | 1.0/1.41/1.41 | 0.942 | 6.84 % | 8.10 % | 0.306 | 2.19 |
| mobile Статус | 55/93 | 1.41/2.0/1.41 | 0.892 | 3.14 % | 4.71 % | 0.271 | 2.27 |

Fullscreen: `frameCount` растёт (521→570 / 666→715), `nodeCount` неизменен (seed не сброшен), `rect.x=0`, `rect.w==vw` → нет сдвига/полосы. Проверка движения **не тавтологична**: локальные максимумы яркости (позиция), `corr`, композиция по hue — не «canvas в DOM». `getDiagnostics()` = 11 полей, в UI не выведен.

## Блок J (стекло) — суждение

Корректно заблокирован. Прототип (gitignored) с явным `source`+`mode:'webgl'` дал `mode=refraction`, `white_frac=0.0046`, без WebGL-конфликта; пп. **1/5/7 честно помечены PENDING OWNER** и не выданы за пройденные. `UI_LIQUID_GLASS_LIB` = **default OFF**; `glass.js::sync` источник не передаёт → функциональные цели (селектор/⛶/карточки) не тронуты, белые прямоугольники hotfix10 не вернулись. Правка `detectMode` (распознаёт `data-render="webgl"`) лишь честность отчёта. Sidebar/Header — без изменений (графитовые).

## Находки

**Blocking (Critical/High/Medium):** нет.

**Non-blocking debt (Low):**
1. **L-1 (Low, честность отчёта).** `plans/reports/round1026_polygon_background_ui_report.md` §4: cyan mobile заявлен 4.4 %, факт 4.71 %; lilac mobile 3.8 % vs 3.14 %; §3 median_shifts «1.41/1.41/1.41» vs факт `[1.0,1.41,1.41]`. Порог-выводы не меняются. Правка — косметическая.
2. **L-2 (Low, §13/SC-33).** `drawFacets`/`drawNodes` на каждом кадре создают мелкие массивы (`mix()`→`ca/cb/col`). Топология и узловые буферы переиспользованы (typed arrays), но «нулевых аллокаций на кадр» нет. Headless ~60 FPS, ускоренного деградирования не наблюдается → не блокер.
3. **L-3 (Low).** `getDiagnostics().isPaused` не отражает pause по `document.hidden` (отдельный `visPaused`). §13 (stop rAF при hidden) соблюдён; поле — вспомогательное.

## Unavailable checks (не объявляются пройденными)

- Реальная оптическая рефракция стекла, внешний ореол, читаемость/плавность и FPS в живом Telegram WebView; видеозапись анимации; сравнение до/после Aurora на полигональном пути — **PENDING OWNER VERIFICATION** (§17). В this-environment эти проверки не воспроизводимы.

## Handoff

**RESULT: Approved @Orchestrator** — Critical/High = 0, Medium-блокеров нет; `review.md` = `plans/archive/polygonal-luminescence-round1026/review.md`. Эпик готов к T-3214 @Scanner и деплою (T-3217). Low-1…3 — в техдолг; живой WebView-гейт не останавливает workflow (§17), но не помечен пройденным.

---

# Addendum — правка владельца T-3220/T-3221 (v2.58.20, re-review @Reviewer)

- **Status:** **Approved**. База diff — `1ad98ca` (HEAD, == tag `pre-round1026-visual`). Изменения — рабочим деревом.
- **Суть правки:** «мерцание свечения фона в 2× медленнее» — замедлены только интенсивность/радиус свечения, ровно ×2.

## Проверка → результат (независимо воспроизведено)

| Проверка | Результат |
|---|---|
| `PULSE_SPEED_MIN` 0.05→0.025, `PULSE_SPEED_MAX` 0.15→0.075, `GLOW_SHIMMER_SPEED` 0.06→0.03 | ✅ ровно ÷2 (проверено значением: `0.025*2===0.05`, `0.075*2===0.15`, `0.03*2===0.06`) |
| Затронуто только свечение | ✅ `pulseSp` влияет лишь на альфу/радиус ореолов (стр. 512/521-522/532/540); `GLOW_SHIMMER_SPEED` — только на радиус radial-glow (стр. 418) |
| Позиция/оттенок/дрейф не тронуты | ✅ `sp1 0.10+rng()*0.22`, `sp2 0.08+rng()*0.18`, `morphPhase sin(t*0.06+ph)`, `sin(t*0.045)`, `cos(t*0.038)` — без изменений |
| Топология/перф | ✅ `TOPO_HZ = 4`, DPR-кап, бюджеты узлов не менялись |
| Тест red→green | ✅ Копия с откатом констант → `ERR_ASSERTION` (actual 0.1 vs expected 0.05); Python-гейт аналогично (`abs(val*2-base)`). Не тавтологичен |
| `getDiagnostics()` | ✅ 11 полей, без расширения |
| `Math.random()` / один рендерер | ✅ 0 вхождений (кроме комментариев); Playwright `visibleBgCanvases=1`, `#aurora-flow-canvas` отсутствует |
| `node --check` | ✅ OK |
| все `tests/js/*.js` | ✅ **43/43, 0 failing** |
| `.venv\Scripts\python.exe -m pytest -q` | ✅ **8525 passed, 0 failed** (1 stdlib-warning) |
| `tools/ui_round1026_polygon.py` | ✅ **0 failures** (desktop+mobile; свежий `_ui_round1026_raw.json`) |
| `git diff --check` | ✅ чисто (только LF→CRLF) |
| Δ DDL / Δ каталога | ✅ 0: `services/**`, `db/**`, `param_catalog.py` вне диффа; 467/426/442/100/98/21 проходит |
| Версия / стекло / маркеры | ✅ `APP_VERSION` 2.58.20 синхронен settings/README; `web/static/` тронут только polygon-background.js (glass J не тронут); re-pin — только строки версии, `==` не ослаблен |
| R17/R18 | ✅ tag `pre-round1026-visual` цел; `*.bak.*` на месте; `stash@{0}` присутствует |

## §15 (качество не ухудшено)

Позиционное движение сохранено (`total_shift 1.41`, `corr(0,20с) 0.941/0.895`), `frameCount` растёт, `nodeCount` не сброшен, `rect.x=0`, `rect.w==vw` → нет полосы/скачка. Композиция/палитра в допуске §14.3 (lilac/cyan/edge/local_ratio). Замедлено только свечение — по прямому требованию владельца.

## Находки

- **Blocking:** нет.
- **Low (техдолг):** наследуются L-1…L-3 базового review без изменений.

## Unavailable

Живое качество (плавность/заметность мерцания в Telegram WebView, «на глаз») — **PENDING OWNER VERIFICATION**.

**RESULT: Approved @Orchestrator** — T-3220/T-3221 подтверждены; блокеров нет, `review.md` обновлён.
