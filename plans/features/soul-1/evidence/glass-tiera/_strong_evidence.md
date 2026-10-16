# TIERA-STRONG — evidence index (усиление рефракции Tier A, приказ владельца 2026-10-16)

Все артефакты этого прохода — с префиксом `_strong_` (замеры предыдущего
кандидата без префикса НЕ перезаписаны; `verify.json`/`shots.json`/`perf*.json`/
`real-*.png` — ДО, `_strong_*` — ПОСЛЕ).

## Что изменено в прод-конфиге

| файл | что | было → стало |
|---|---|---|
| `web/index.html` (фильтр `#lg-lens`) | карта смещения (256×256, R/G) + `feDisplacementMap scale` | пик 8 px / scale 16 → **пик 16 px / scale 32**; рампа `smoothstep(0.62…1.00)` → `(0.62…0.85)` + плато на внешних 15% полуоси |
| `tests/glass-teststand/glass-teststand.html` | та же инлайн-карта/scale (стенд в синхроне с приложением) | 8 px/16 → 16 px/32 |
| `config/settings.py:1245-1252` | комментарий `UI_LENS_MAX_NODES` (семантика hero-капа; линза им НЕ ограничена; kill-switch = `UI_GLASS_TIER_OVERRIDE=b`) | поведение не менялось |
| `web/static/app.css`, `web/app.js` | НЕ менялись (blur 5 px / alpha / rim / геометрия — как были) | — |
| `tests/ui_soul1_glass_tiera_e2e.py` | измерительный инструмент: мишень 24→48 px, окно 32→48, поиск ±12→±24, edge-band 24→40, pattern-period 48, guard'ы границ, `--prefix`, фикс `/__tier` (находка ревью №1) | — |

## Числа

* **Профиль карты** (`_strong_map_profile.txt`): A(s)=16.00 px при s=1.0 (было
  8.00), 11.48 при 0.80 (было 3.04), 0.06 px при s≤0.60 (центр — как был).
  Складка: max|dA/dx| = 0.889 при W=216 (минимальная реальная tier-A ширина),
  0.394 при 487, 0.157 при 1224 → <1 (зеркального отражения нет).
* **Сдвиг мишени** (`_strong_verify.json`, 77 pass / 1 fail): кромки 12–15 px на
  карточках/панелях/шапке (было 6–8), модалка 16.5 med / 23 max, сайдбар 7.0;
  центр 0.0 px (медиана 0.0, 60 окон на больших карточках).
* **Видимость на реальном фоне** (`_strong_visibility.json`, A vs A-без-lens,
  полоса 20 px у кромок, |ΔL| 0..255): средние по страницам edge_mean ×1.76–3.40,
  edge_p95 ×1.48–2.98; доля пикселей кромки с |ΔL|≥4 выросла 1.2–1.6% → 3.4–5.1%
  (сайдбар 2.5% → 8.9%); центр остался на уровне шума; внешние 3 px выросли
  пропорционально (0.3–0.4 → 0.6–1.5) — каймы/артефакта выборки нет.
* **Легибельность** (`_strong_legibility.json`): Δrect = 0.000 px на 7
  поверхностях (вкл. модалку); IoU маски глифов 0.984–1.0, сдвиг центроида
  ≤0.39 px; контраст-прокси текста к подложке ON vs OFF в пределах ±0.06.
* **Перф** (`_strong_perf-headed.json`, headed Chrome 390×844): `#/modules`
  p50/p95 16.7/16.8, 0 longtask (было 16.7/16.8, 0); `#/ai/llm` 16.7/34.1
  (было 16.7/33.1), TaskDuration 12.6% vs 12.2% (B); `#/` 16.7/33.6 vs tierB
  16.7/17.4 при равном main-thread (4.3% vs 4.4%).
* **Контексты**: `_strong_webview.json` (android_tma: 16 линз, scale=32, карта
  374×141; webkit_like: 0 линз, tier b=16/c=2, `engine-unproven-backdrop-url`).

## Визуальные пары ON/OFF на ОДНОЙ замороженной позиции фона (`?bgseed=424242` + `pause()`)

* desktop 1440 (реальный Chrome, Browser Use): `_strong_bu_desktop_{status,modules}_{ON,OFF}_1440.png`,
  усиленный дифф ×4 — `_strong_bu_desktop_{status,modules}_diffx4_1440.png`
  (mean|ΔL| 0.30/0.44, max 103.6/21.0 на ×1).
* Telegram-WebView-подобный контекст (Android UA, 390×844, DPR 2.625):
  `_strong_bu_tma_{status,modules}_{ON,OFF}_390.png` + `*_diffx4_390.png`
  (mean 1.29/0.76, max 106.9/59.3 на ×1).
* Честный фолбэк tier A vs tier B: `_strong_bu_tier{a,b}_modules_1440.png` +
  `_strong_bu_tierA_vs_B_diffx4_1440.png`.
