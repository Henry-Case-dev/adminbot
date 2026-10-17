# WIN-GLASS-P0 — evidence index

Все артефакты получены на кандидате (рабочее дерево поверх `a891b721`, без
коммита). Скриншоты — Playwright/Chromium mobile-эмуляция (390×844, DPR 2) и
desktop (1440×900, DPR 1); фон — polygon-canvas, `?bgseed=20260923`,
rAF фона остановлен после прогрева (freeze-frame только в тестовом захвате).

| Артефакт | Что показывает |
|---|---|
| `e2e/_results.json` | полный машинный результат WIN-GLASS e2e: 37 проверок (A 21, C 4, B 10, D 2), проба, тиры/reasons, состав слоёв (≤3), метрики пикселей, сдвиг линий, раскладка (0 сдвинутых rect'ов), перф (`paintMs`), FS-аудит, отсутствие window-hack'ов |
| `e2e/refract_off.png` / `e2e/refract_on.png` | RED/GREEN на реальном фоне: кромка карточки без слоя и со слоем (смещение геометрии у кромок, текст/кнопки идентичны) |
| `e2e/pattern_off.png`, `e2e/pattern_off2.png` | RED/шумовой контроль: контрастный паттерн (псевдослучайные полосы 3–13 px в canvas фона) без слоя; OFF↔OFF → 0 px (corr 1.0) |
| `e2e/pattern_on.png` | GREEN: линии у левой/правой кромки смещены (−26/+32 device px = −13/+16 CSS px, corr 0.92/0.97), центр — 0 px (corr 1.0) |
| `fs-regression/_results.json`, `fs-regression/_run.log` | существующий FS e2e (12 сценариев, 166 проверок) — PASS, регрессий полосы управления нет; копия сделана перед возвратом чужого каталога evidence к HEAD |
| `frozen-assets.txt` | `tools/soul1_w4_frozen_check.py` → `FROZEN-ASSETS-OK`: polygon-фон/карта линзы/токены/стекло-классы не изменились, LF-инвариант цел |
| `polygon-e2e-pre-existing-failures.log` | `tools/ui_round1026_polygon.py`: 4 падения — **предсуществующий** дрейф ожиданий (11 vs 19 полей `getDiagnostics`, ASAP-3.1), к лейну не относятся |

Отладочные скрипты (не являются evidence): `OPENCODE_WORKFLOW_SCRATCH/win-glass/`
(`diag_*.py` — почему композит DOM не измерим, влияние фильтра на яркость,
какие слои затемняют фон).
