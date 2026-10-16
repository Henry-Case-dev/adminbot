# ROW-A / U07.2: горизонтальный safe-area для кнопки ⛶ (fix 2026-10-16)

Lane: RESUME-ROWA (leaf, writer + verification). Scope: geometry only.

## Дефект (подтверждён репродом)
`_v63fe2_rowa_safearea.json` (harness `ui_rowa_safearea_e2e.py`, mock SDK,
inline-слот): при `safeAreaInset.right=44` на 667×375 hit-box `.header-fs-btn`
= `[602..651]` при безопасном правом крае 623 → **28 px внутри нативной
✕/⋮ зоны**. Совпало с референсом V63-FE-2 (`_v63fe2_rowa_safearea.json`,
case `667_safearea_cutout`, right=651) с точностью до пикселя. Второй случай:
320×700 с left/right=24 → 8 px за правым краем.

## Причина
Базовое правило `header.header-sticky` (шапка = контейнер inline-⛶, ряд A)
использовало ТОЛЬКО `env(safe-area-inset-left/right)`, который в Telegram
Android = 0. Значения SDK лежат в `--tg-safe-area-inset-*` /
`--tg-content-safe-area-inset-*` (пишет telegram-init.js), но базовый
padding их не читал. Float-слот уже корректен (`right: calc(max(...)+6px)`,
case `667_float_right44` → 617 ≤ 623).

## Фикс (минимальный, 1 файл)
`web/static/app.css`, правило `header.header-sticky` (строки ~1014–1015):
`padding-right/left` переведены на формулу
`calc(1rem + max(env(...), var(--tg-content-safe-area-inset-*, 0px), var(--tg-safe-area-inset-*, 0px)))`
— образец, уже применённый в репозитории (.fullscreen-mode header 1146–1147,
.toast-wrap 895, float-⛶ 3369–3371). При нулевых инсетах формула даёт те же
16px → визуальных сдвигов в обычных сценариях нет. Политика
(fullscreen-policy.js), `web/app.js`, `web/index.html`, glass/polygon — не
тронуты; семантика слотов (tdesktop → hidden, `tdesktop_disabled_until_e2e`;
expand() ≠ fullscreen; один источник) не изменена.

## До / После (hit-box, JSON `_v63fe2_rowa_safearea.json`)
| case | viewport | safe edge | ДО right | ПОСЛЕ btn | inside |
|---|---|---|---|---|---|
| 320_lr_insets (inline, L/R 24) | 320×700 | R=296, L=24 | 304 (8px в зоне) | 231..280 | все оси ✓ |
| 390_zero_inset (inline) | 390×844 | R=390 | 374 | 325..374 | ✓ |
| 667_safearea_cutout (inline, R 44) | 667×375 | R=623 | 651 (28px в зоне) | 558..607 | ✓ |
| 667_float_right44 (float, R 44) | 667×375 | R=623 | 617 | 568..617 | ✓ |

Все кейсы: hit 49×44 ≥ 44×44, визуал 32px (28–34), без h-overflow,
`control_box ⊆ content_safe_area` по обеим осям (`ok=true` для всех 6 кейсов).
Скриншоты: `_v63fe2_rowa_<tag>.png` (6 шт).

## Регрессия
`tools/ui_asap8_w2_fullscreen_e2e.py`: **итог: 7/7 PASS**
(S1 21, S2 10, S3 4, S4 2, S5 13, S6S7 5, S8 15 проверок).

## Артефакты
- `plans/features/asap8-v6-3-live-correction/evidence/v63-rowa-safearea/`
  `_v63fe2_rowa_safearea.json` + 6 PNG + исправленный harness
  `ui_rowa_safearea_e2e.py` (починка sys.path до repo/tools, имена с `_v63fe2_`).

## Ограничения / не гарантировано
- Пиксельная визуальная инспекция (Browser Use) невозможна: текущая модель
  не принимает изображения. Детерминированные геометрические проверки
  (rect ⊆ safe area, hit/визуал, overflow) выполнены Playwright-зондом.
- Проверено в моке (как и весь w2-контур); live-проверка на реальных
  клиентах — по плану Wave 4, вне этого лейна.
- Фикс меняет горизонтальный padding ВСЕЙ шапки (это контейнер кнопки и
  других правых элементов ряда A) — это root-cause, а не только кнопка;
  при нулевых инсетах геометрия не меняется.
