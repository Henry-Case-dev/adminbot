# EXTRA-визуальный эпик round 10.26 — POLYGONAL LUMINESCENCE — `tasks.md`

> **Источник:** `plans/current_task.md`, строки **7485–8755** (§0–§17) — прочитано **дословно**; файл НЕ изменялся (R17/R18).
> **Статус:** ✅ **COMPLETED + MERGED (§72) + ARCHIVED** (Шаг 8 @PM, T-3216, 23.09.2026; архив — `plans/archive/polygonal-luminescence-round1026/`). Step 2 @Architect ✅ (`spec.md` + ADR-1026-3 Accepted фактом мержа §72). **Step 4 @Builder — РЕАЛИЗОВАНО** (блоки 0/A–I, K; `APP_VERSION` 2.58.19). Блок **J — BLOCKED (PENDING OWNER, §12/§13.2)**: прототип не проходит п.1/5/7 headless → glass-интеграция не выполнена, `UI_LIQUID_GLASS_LIB` default OFF (**не `[x]`**). @Reviewer **Approved** (T-3213); @Scanner **C0/H0/M0/L3/I4 → «к деплою ДА»** (T-3214; `plans/reports/round1026_visual_scanner_audit.md`); Merge `plans/ARCHITECTURE.md` **§72** (T-3215). Полный pytest **8520/0**, JS **43/43**, Playwright polygon **0 failures**, матрица §71 **0 failures**. Маркер `POLYGON-LUMINESCENCE-OK`.
> **Deploy:** ✅ **Шаг 9 @DevOps (T-3217) — VERIFIED** (`APP_VERSION` 2.58.18 → **2.58.19** → **2.58.20**; `deployment.md` VERIFIED). Правка владельца v2.58.20 — мерцание свечения фона ×2 медленнее. **Метрики:** ✅ T-3218 (Шаг 10 @Memory) — `plans/metrics.md` строка + раздел **10.26-VISUAL** + KG-синк (не коммичено до закрывающего docs-коммита @DevOps). **Live-гейты — `[ ]` PENDING OWNER VERIFICATION** (реальный Telegram WebView/WebKit; стекло п.1/5/7; §17).
> **Baseline (Step 0):** HEAD **`9d046e5`** (== `origin/master`), `APP_VERSION` **2.58.18**; pytest `.venv` **8501/0**, JS **42/42**; каталог **467/426/442/100/98/21**; **Δ DDL = 0**.
> **ID:** **T-3162…T-3219 (58)**; дублей нет (максимум занятого — S1 Эпика 2 **T-3161**).
> **Маркер:** `POLYGON-LUMINESCENCE-OK`.

---

## 0. Инварианты (обязательны для каждой задачи)

- **Δ DDL = 0.**
- **Δ каталога:** предварительно **0** (флаг/настройки — env-only `ClassVar`, прецедент `UI_AURORA_FLOW_V2`/`UI_LIQUID_GLASS_LIB`); **окончательно — @Architect (Step 2)**.
- CSP `script-src 'self'`, zero-build (ADR-1016-2 / ADR-1024-13); vendor — **same-origin** (`web/static/vendor/`), **без CDN**.
- R17/R18: `plans/current_task.md` не трогать; бэкапы/теги не удалять.
- **Не ломать:** §57–§71 / F0–F11 / S1, IA/навигация, сердцебиение (§11/§15), настройки бота, публикацию.
- **Гейт S6/S10** (публикация/hybrid Эпика 2) — **закрыт до live-приёмки Эпика 1** (ADR-1025-24 D4). **Не трогать.**
- **Один активный фоновый рендерер** (не запускать одновременно Aurora + CSS blobs + page wash + Polygonal).
- **«Не объявлять готово по pixel diff»** — субъективное качество не подтверждается одним diff/наличием Canvas (§14/§15).
- **Белые непрозрачные прямоугольники стекла не повторять** (hotfix10/ADR-1025-18 D1); frosted ≠ рефракция; Sidebar/Header графитовые.
- **Не зацикливаться на декоре (§17):** после проверенных критериев приёмки — продолжить `current_task.md`, а не новую итерацию эффектов.
- **`[ ]` Живой Telegram WebView** — **PENDING OWNER VERIFICATION** (§17; не основание останавливать workflow). Аналогично `[ ]`: стекло п.1 (реальная рефракция) / п.5 (внешний ореол) / п.7 (перф WebView) — PENDING OWNER.

## 1. Трассируемость REQ → блоки

| REQ (ТЗ) | Блоки |
|---|---|
| §0/§1 замена Aurora на полигональную сцену | B, C, D, E |
| §2 стек (Delaunator / Canvas 2D / OGL / `@liquidglassjs/core`) | A, B |
| §3 контракт модуля + адаптер + один рендерер | B |
| §4 композиция 4 слоя (A–D) | C |
| §5 палитра (11 цветов, сиреневые заметны, локальные яркие) | D |
| §6 сеть/seed/триангуляция/фильтр/топология | C |
| §7 свет (излучение/грани/узлы/линии/bloom) | E |
| §8/§9 переливы и анимация | F |
| §10/§11 canvas, resize, fullscreen/TMA | H |
| §12 Liquid Glass (прототип → точечно) | I, J |
| §13 производительность | G |
| §14 диагностика/Playwright/композиция/материалы | K |
| §15/§16 критерии и порядок | L (+ все) |
| §17 продолжение workflow | Q |

---

## Блок 0 — Baseline + design (T-3162…T-3165)

- **T-3162 · @DevOps** — *точка отката.* **Готово, когда:** annotated-тег **`pre-round1026-visual`** → `9d046e5` в origin; бэкап `var/backups/visual-round1026-<ts>/` + `.env.bak`; `stash@{0}` цел (R18). **Файлы:** git-тег; `var/backups/**`.
- **T-3163 · @Architect** — *Step 2.* **Готово, когда:** `spec.md` + ADR (создаётся @Architect) фиксируют: новый модуль vs замена `aurora-flow.js`; env-only флаг (`UI_POLYGON_BG`) vs каталог (Δ каталога = ?); SUPERSEDE/AMEND (ADR-1025-17 D6, ADR-1025-18 D1); OGL (оставить/Canvas-2D-only); deploy+bump; форму приёмочного отчёта. **Файлы:** `plans/archive/polygonal-luminescence-round1026/{spec.md,adr-*.md}`.
- **T-3164 · @Memory** — *Step 3 graph.* **Готово, когда:** KG-связи `VISUAL-polygonal-luminescence-round1026` ↔ ADR/спек + `supersedes` Aurora, `amends` glass. **Файлы:** KG.
- **T-3165 · @PM** — *реконсиляция.* **Готово, когда:** `tasks.md` сверен с `spec.md`; расхождения → @Architect через @Orchestrator (Builder не изобретает решение). **Файлы:** этот файл.

## Блок A — Vendor Delaunator 5.0.0 (T-3166…T-3169)

- [x] **T-3166 · @Builder** — `tools/vendor`: `delaunator@5.0.0` (`--save-exact`) + entry в `build.mjs` (esbuild IIFE). **Готово, когда:** зависимость зафиксирована, сборка детерминирована. **Файлы:** `tools/vendor/{package.json,package-lock.json,build.mjs}`.
- [x] **T-3167 · @Builder** — сборка output. **Готово, когда:** `web/static/vendor/delaunator.5.0.0.min.js` + SHA-256 + строка лицензии в `README.md`. **Файлы:** `web/static/vendor/**`.
- [x] **T-3168 · @Builder** — подключение. **Готово, когда:** `<script src="/static/vendor/…">` до `app.js`; CSP same-origin; **0 CDN-хостов**. **Файлы:** `web/index.html`.
- [x] **T-3169 · @Builder** — тесты vendor. **Готово, когда:** no-CDN инвариант + наличие vendor + `node --check`; **Δ каталога = 0**. **Файлы:** `tests/js/**`.

## Блок B — Прототип `polygon-background.js` (§3) (T-3170…T-3174)

- [x] **T-3170 · @Builder** — скелет модуля. **Готово, когда:** контракт `start/stop/pause/resume/resize/getDiagnostics()` в отдельном модуле (не в `app.js`). **Файлы:** `web/static/polygon-background.js`.
- [x] **T-3171 · @Builder** — адаптер. **Готово, когда:** `window.__AuroraFlow` совместим (существующие вызовы не переписываются). **Файлы:** `polygon-background.js`, `web/app.js`.
- [x] **T-3172 · @Builder** — переиспользование lifecycle. **Готово, когда:** `ensureCanvas`/`measure`/`resize`+`ResizeObserver` перенесены из `aurora-flow.js`. **Файлы:** `polygon-background.js`.
- [x] **T-3173 · @Builder** — один активный рендерер. **Готово, когда:** в DOM нет второй анимирующейся сцены; лишние `rAF` погашены. **Файлы:** `web/app.js::_syncBgLayer`, `app.css`.
- [x] **T-3174 · @Builder** — изолированный прототип-харнесс. **Готово, когда:** отдельная демо-страница (gitignored `tools/` или отдельный статик) для итераций. **Файлы:** `tools/**`.

## Блок C — Геометрия/узлы/seed/триангуляция/фильтр (§4/§6) (T-3175…T-3179)

- [x] **T-3175 · @Builder** — узлы. **Готово, когда:** desktop 90–140 / mobile 45–75, кластеризация, **фикс. seed**, без пересоздания на кадре. **Файлы:** `polygon-background.js`.
- [x] **T-3176 · @Builder** — триангуляция. **Готово, когда:** `Delaunator.from(points)`, индексы → грани. **Файлы:** `polygon-background.js`.
- [x] **T-3177 · @Builder** — фильтр треугольников. **Готово, когда:** учтены длина ребра/площадь/кластер/расстояние до света; нет длинных линий через viewport и плотной решётки. **Файлы:** `polygon-background.js`.
- [x] **T-3178 · @Builder** — топология. **Готово, когда:** пересчёт с ограниченной частотой, плавное смешивание, без резких скачков. **Файлы:** `polygon-background.js`.
- [x] **T-3179 · @Builder** — композиция A–D. **Готово, когда:** неравномерная плотность, зоны индиго/сирень/циан/нити, без равномерной сетки. **Файлы:** `polygon-background.js`.

## Блок D — Полупрозрачные грани + палитра (§5) (T-3180…T-3183)

- [x] **T-3180 · @Builder** — палитра. **Готово, когда:** 11 цветов — единые константы (без разбросанных RGB). **Файлы:** `polygon-background.js`.
- [x] **T-3181 · @Builder** — грани. **Готово, когда:** многопроходная полупрозрачная заливка, контроль итоговой яркости, без сплошного белого. **Файлы:** `polygon-background.js`.
- [x] **T-3182 · @Builder** — сиреневые области. **Готово, когда:** lilac/lavender/violet занимают **заметную** часть композиции. **Файлы:** `polygon-background.js`.
- [x] **T-3183 · @Builder** — локальность яркости. **Готово, когда:** насыщенные зоны локальны, нет равномерного свечения на весь экран. **Файлы:** `polygon-background.js`.

## Блок E — Локальный свет + bloom (§7) (T-3184…T-3188)

- [x] **T-3184 · @Builder** — фоновое излучение. **Готово, когда:** световые области привязаны к кластерам, мягкие радиальные градиенты, без одного blur на viewport. **Файлы:** `polygon-background.js`.
- [x] **T-3185 · @Builder** — свечение граней. **Готово, когда:** 3 прохода; `globalCompositeOperation` `screen`/`lighter`; без «белого пятна». **Файлы:** `polygon-background.js`.
- [x] **T-3186 · @Builder** — узлы. **Готово, когда:** центр+ореол+рассеяние; тиры слабые/умеренные/яркие; не все белые. **Файлы:** `polygon-background.js`.
- [x] **T-3187 · @Builder** — линии. **Готово, когда:** тонкие; glow — выборочно, не на всех рёбрах. **Файлы:** `polygon-background.js`.
- [x] **T-3188 · @Builder** — bloom. **Готово, когда:** offscreen уменьшенного разрешения + мягкое размытие + композиция; **не** `filter:blur` на полноэкранном Canvas. **Файлы:** `polygon-background.js`.

## Блок F — Переливы + движение (§8/§9) (T-3189…T-3192)

- [x] **T-3189 · @Builder** — цветовой morph. **Готово, когда:** плавные переходы (Violet→Lilac→Ice Blue; Cyan→Electric Blue→Lavender), без резких/случайных цветов. **Файлы:** `polygon-background.js`.
- [x] **T-3190 · @Builder** — дрейф световых центров. **Готово, когда:** центры смещаются в кластерах; яркость граней — от расстояния. **Файлы:** `polygon-background.js`.
- [x] **T-3191 · @Builder** — импульсы. **Готово, когда:** редкие плавные усиления на пересечениях, без стробоскопа/синхронной пульсации. **Файлы:** `polygon-background.js`.
- [x] **T-3192 · @Builder** — движение узлов. **Готово, когда:** база + амплитуда **4–18 px** + своя фаза; различимо за **5–10 с**; детерминированно. **Файлы:** `polygon-background.js`.

## Блок R — Правка владельца (v2.58.20): «мерцание свечения» ×2 (T-3220…T-3223)

> **Источник:** owner-правка после прод-деплоя 2.58.19 (HEAD `1ad98ca`): «сделай
> мерцание свечения фона в два раза медленнее». Это уточнение временно́го
> параметра (не смена дизайна: палитра/композиция/структура не меняются).

- [x] **T-3220 · @Builder** — определить параметры «мерцания свечения». **Факт:** импульсы свечения узлов/ореолов §8.3 (`pulseSp`) и «дыхание» радиуса фонового свечения §7.1 (radial radius). НЕ мерцание: движение узлов §9, цветовой morph §8.1, дрейф световых центров §8.2, каденция топологии §6.4. **Файлы:** `web/static/polygon-background.js`.
- [x] **T-3221 · @Builder** — замедлить ровно ×2 (частота ÷2, период ×2); именованные константы `PULSE_SPEED_MIN/MAX`, `GLOW_SHIMMER_SPEED`. **Файлы:** `web/static/polygon-background.js`.
- [x] **T-3222 · @Builder** — регресс-тест «период = прежний ×2» (JS + Python); падает при возврате прежней скорости. **Файлы:** `tests/js/round1026_polygon_background_test.js`, `tests/test_webapp_round1026_polygon.py`.
- [x] **T-3223 · @Builder** — bump `APP_VERSION` 2.58.19 → 2.58.20 (+ `README.md`/meta + re-pin версии в 15 тестах) — cache-bust ассета. **Файлы:** `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, тесты.

## Блок G — Производительность (§13) (T-3193…T-3196)

- [x] **T-3193 · @Builder** — mobile-бюджет. **Готово, когда:** меньше узлов/треугольников, DPR-кап, меньше offscreen glow, ~30 FPS. **Файлы:** `polygon-background.js`.
- [x] **T-3194 · @Builder** — аллокации. **Готово, когда:** топология не на каждый кадр; переиспользование буферов/массивов. **Файлы:** `polygon-background.js`.
- [x] **T-3195 · @Builder** — hidden/reduced-motion. **Готово, когда:** hidden → stop `rAF`, возврат → resume; `prefers-reduced-motion` → качественная **статика** (не удалять геометрию). **Файлы:** `polygon-background.js`.
- [x] **T-3196 · @Builder** — context-loss/Vue. **Готово, когда:** `webglcontextlost` → 2D-фолбэк; нет Vue re-render на кадр. **Файлы:** `polygon-background.js`, `web/app.js`.

## Блок H — Resize + fullscreen/TMA (§10/§11) (T-3197…T-3200)

- [x] **T-3197 · @Builder** — canvas-геометрия. **Готово, когда:** `#polygon-background` (`position:fixed; inset:0; pointer-events:none`) вне max-width-контейнеров; ясный z-порядок. **Файлы:** `polygon-background.js`, `app.css`.
- [x] **T-3198 · @Builder** — resize. **Готово, когда:** CSS-размер + drawing buffer + scale; без скачка/полосы. **Файлы:** `polygon-background.js`.
- [x] **T-3199 · @Builder** — fullscreen/TMA. **Готово, когда:** существующий viewport-адаптер; seed **не сбрасывается**; анимация не останавливается. **Файлы:** `web/app.js::_auroraResize/setFullscreenFromTma`, `telegram-init.js`.
- [x] **T-3200 · @Builder** — без левой полосы. **Готово, когда:** нет двойного вычета Sidebar / цветной полосы слева. **Файлы:** `app.css`, `polygon-background.js`.

## Блок I — Glass-прототип + 7 проверок (§12.2/§12.3) (T-3201…T-3203)

- [x] **T-3201 · @Builder** — прототип. **Готово, когда:** новый фон + 1 стеклянная поверхность + линии/узел позади + текст/иконка поверх. **Файлы:** `tools/**` (gitignored).
- [x] **T-3202 · @Builder** — 7 проверок. **Готово, когда:** (1) преломление реально; (2) текст чёткий; (3) не перекрывает кнопку; (4) **нет белого прямоугольника**; (5) нет яркого внешнего ореола; (6) нет конфликта WebGL-контекстов; (7) mobile-перф приемлема. **Файлы:** `tools/**`, отчёт.
- [x] **T-3203 · @Builder** — честность режима. **Готово, когда:** `backdrop blur` **не** выдаётся за рефракцию; детект режима задокументирован. **Файлы:** `web/static/glass.js`, отчёт.

## Блок J — Точечная glass-интеграция (§12/§12.4) (T-3204…T-3206)

- [ ] **T-3204 · @Builder** — интеграция. **Готово, когда:** только изолированный декор — селектор области / `⛶` / декор Статуса (не Vue-компоненты). **Файлы:** `web/static/glass.js`, `web/index.html`.
- [ ] **T-3205 · @Builder** — графит shell. **Готово, когда:** Sidebar/Header графитовые, без фиолетового ореола и без компенсации яркости. **Файлы:** `app.css`.
- [ ] **T-3206 · @Builder** — контраст. **Готово, когда:** параметры читаемы; прозрачность всех карточек не снижена ради фона. **Файлы:** `app.css`, отчёт AA.

> **Блок J — BLOCKED (PENDING OWNER, §12/§13.2).** Гейт §13.2 (AD-D6) не пройден headless: п.1
> (реальная оптическая рефракция) и п.5 (внешний ореол) не воспроизводимы без
> реального устройства, п.7 (перф WebView) — PENDING OWNER. По §13.2 эпик
> поставляет **только фон**; `mountGlass` со `source` в основной UI **не**
> подключён, `UI_LIQUID_GLASS_LIB` остаётся default **OFF** (hotfix10 не
> повторяем). Прототип и его результат — `plans/reports/round1026_polygon_glass_prototype.md`;
> `glass.js::detectMode` улучшен для честного распознавания WebGL-пути (T-3203).

## Блок K — Playwright + диагностика (§14) (T-3207…T-3210)

- [x] **T-3207 · @Builder** — `getDiagnostics()`. **Готово, когда:** возвращает `renderer/canvasWidth/canvasHeight/devicePixelRatio/nodeCount/triangleCount/frameCount/lastFrameTime/isPaused/isReducedMotion/contextLost`; **не в UI**. **Файлы:** `polygon-background.js`.
- [x] **T-3208 · @Builder** — движение. **Готово, когда:** Playwright кадры **0/5/10/20 с**; меняется **положение** элементов, не только яркость; анимация жива после fullscreen. **Файлы:** `tools/ui_round1025_matrix.py` / новый скрипт.
- [x] **T-3209 · @Builder** — композиция. **Готово, когда:** программно подтверждены узлы/полигоны/линии/сиреневая+циановая области/локальные яркие; **не** один тест «Canvas в DOM». **Файлы:** `tools/**`.
- [x] **T-3210 · @Builder** — материалы. **Готово, когда:** Desktop/Mobile × Статус/Модули, normal/fullscreen + короткая запись. **Файлы:** `plans/reports/**`.

## Блок L — Приёмка §15 + материалы (T-3211…T-3212)

- [x] **T-3211 · @Builder/@Reviewer** — чек-лист §15. **Готово, когда:** каждый пункт «НЕ завершено, если…» проверен явно; при провале — возврат в соответствующий блок. **Файлы:** этот файл, отчёт.
- [x] **T-3212 · @Builder** — сравнение с Aurora. **Готово, когда:** новый фон vs предыдущая Aurora в одинаковых условиях. **Файлы:** `plans/reports/**`.

## Блок M — Ревью/аудит (T-3213…T-3214)

- [x] **T-3213 · @Reviewer** — **Готово, когда:** `Approved` (или итерации с закрытыми блокерами) — `review.md`. **Файлы:** `review.md`.
- [x] **T-3214 · @Scanner** — **Готово, когда:** Critical/High = 0 (+ Low/Info) → «к деплою ДА»; аудит-отчёт. **Файлы:** `plans/reports/**`.

## Блок N — Merge (T-3215)

- [x] **T-3215 · @Architect** — **Готово, когда:** `plans/ARCHITECTURE.md` §(новый) с инвариантами, AMEND/SUPERSEDE-картой, deploy-строкой, техдолгом. **Файлы:** `plans/ARCHITECTURE.md`. **Факт:** Merge **§72** (23.09.2026); ADR-1026-3 Accepted.

## Блок O — Архив (T-3216)

- [x] **T-3216 · @PM** — **Готово, когда:** `plans/archive/polygonal-luminescence-round1026/` (spec + ADR + tasks + evidence + review + deployment), ID сохранены, ссылки разрешены. **Файлы:** `plans/archive/**`. **Факт:** ✅ выполнено (Шаг 8 @PM, 23.09.2026).

## Блок P — Deploy (T-3217)

- [x] **T-3217 · @DevOps** — **Готово, когда:** bump `APP_VERSION`, push без force, прод ff, `/api/health` 200, served `?v=`, `database is locked`=0, `deployment.md` VERIFIED. **Файлы:** `web/app.py`/`index.html`, `deployment.md`. **Статус:** ✅ **VERIFIED** (Шаг 9 @DevOps + addendum-правка), коммиты `76fc5e1`/`bf46360`/`1ad98ca` (2.58.19) + `306778a`/`a50b014`/`54c6445` (2.58.20); health 200, `database is locked`=0; `deployment.md` VERIFIED.

## Блок Q — Метрики/KG + продолжение §17 (T-3218…T-3219)

- [x] **T-3218 · @Memory** — **Готово, когда:** `plans/metrics.md` строка + KG-синк. **Файлы:** `plans/metrics.md`, KG. **Статус:** ✅ выполнено (Шаг 10 @Memory, 23.09.2026): `plans/metrics.md` строка + раздел **10.26-VISUAL** + техдолг §72.5; KG — `VISUAL-polygonal-luminescence-round1026` → DEPLOYED, созданы `release-round1026-visual` + `metric-snapshot-round1026-visual-final` + `tech-debt-round10.26-visual`. Закрывающий docs-коммит — @DevOps.
- [ ] **T-3219 · @PM/@Orchestrator** — **продолжение `current_task.md` (§17).** **Готово, когда:** остаток ТЗ сверен, следующий actionable пункт назван; **возобновлена приостановленная S2**; live-гейты помечены PENDING OWNER VERIFICATION. **Не зацикливаться на декоре.** **Файлы:** `plans/workflow_state.md`, `plans/backlog.md`. **Статус:** ⏳ PENDING (S2 `summary-context-restore` возобновляется после деплоя, Шаг 9).

---

## Открытые вопросы для @Architect (Step 2)

1. Новый модуль `polygon-background.js` vs замена `aurora-flow.js` (судьба файла для отката).
2. Флаг: env-only (`UI_POLYGON_BG`?) vs каталог → **Δ каталога = 0 или ≠ 0**.
3. Место прототипа: gitignored `tools/` vs отдельная статик-страница.
4. Судьба `aurora-flow.js` / `UI_AURORA_FLOW_V2` — SUPERSEDE/откат (ADR-1025-17 D6).
5. OGL 1.0.11 — оставить для отката/GPU или Canvas-2D-only.
6. deploy + bump `APP_VERSION` (ДА/НЕТ/NOT_APPLICABLE) — обосновать.
7. Форма приёмочного отчёта (разделы §15/§14).

## Handoff

- **✅ Завершено:** Step 2 @Architect (`spec.md`/ADR-1026-3), Step 3 @Memory (KG), блок 0 @DevOps (тег `pre-round1026-visual` + бэкап), T-3165 @PM реконсиляция, блоки A–L, @Reviewer/@Scanner, Merge §72, **архивация (Шаг 8 @PM, T-3216)**.
- **✅ Выполнено:** **Шаг 9 @DevOps (T-3217)** — деплой **VERIFIED** (bump `APP_VERSION` 2.58.18 → 2.58.19 → **2.58.20**, push/прод/health) → **Шаг 10 @Memory (T-3218)** — `plans/metrics.md` + KG + техдолг §72.5.
- **▶️ Далее:** **Шаг 11 @PM/@Orchestrator (T-3219)** — продолжить `plans/current_task.md`, **возобновить S2 `summary-context-restore`** (§17/§90–§92), не зацикливаться на декоре.
- Гейт **S6/S10** не снимается; **S2 — PAUSED до деплоя EXTRA-эпика** (§72.8).
- Live-гейты — **`[ ]` PENDING OWNER VERIFICATION**; блок **J/стекло** — BLOCKED гейтом §13.2.
