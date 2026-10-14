# round1025 / hotfix7 — отчёт обязательной проверки UPD 6 (Playwright-матрица)

- **Пакет:** `hotfix7-shell-glass-heartbeat-round1025` (T-2681, ADR-1025-13)
- **Инструмент:** `tools/ui_round1025_matrix.py` (расширен: 5 логических режимов + `F7_PROBE_JS`/`_hotfix7_failures`)
- **Дата:** 22.09.2026 · **Валюта:** HEAD рабочего дерева (без коммита), `APP_VERSION` **2.58.8**
- **Артефакты (gitignored):** `tools/_ui_round1025_raw.json`, `tools/_ui_round1025_shots/*.png` (+10 новых `*_fullscreen.png`)

## Что прогонялось (5 режимов)

Каждый из 10 вьюпортов §71 (320×700 … 2560×1440) прогоняется в **normal** и **fullscreen**:

| Логический режим | Вьюпорты | Как форсировался fullscreen |
|---|---|---|
| desktop normal / desktop fullscreen | 1280×800, 1440×900, 1920×1080, 2560×1440 | `Telegram.WebView.receiveEvent('fullscreen_changed',{is_fullscreen:true})` |
| tablet | 768×1024, 1024×768 | то же |
| mobile regular / mobile fullscreen | 320×700, 360×780, 390×844, 430×932 | то же + симуляция нижнего бара (`stable = innerHeight−56`) |

## Результат (факт)

- **Прогон 1:** 1 FAIL — `768x1024 console: net::ERR_CONNECTION_TIMED_OUT` (внешний ресурс, сеть стенда).
- **Прогон 2 (повтор):** `[matrix] failures: 0` — **все 10 вьюпортов × (normal + fullscreen) без замечаний**. Флейк внешнего ресурса не воспроизвёлся (к shell/glass/heartbeat не относится).

Проверки `_hotfix7_failures` (все пройдены):

| Проверка UPD 6 | Доказательство (computed) |
|---|---|
| heartbeat виден везде (normal + fullscreen) | `.hb-canvas` существует, `visible`, `rect.h ≥ 1`, после `scrollIntoView` целиком во вьюпорте; класс `hb-<state>` проставлен (в стенде — `hb-unknown`, т.к. `/api/status`-стаб без `uptime.generated_at` → честный UNKNOWN, не «0») |
| header не ломается | `.header-title-wrap`/`.header-fs-btn`/селектор в вьюпорте; `--header-h` резерв (проверки hotfix6 сохранены) |
| glass shell качественный | shell-панели несут `backdrop-filter` ≠ none; `--shell-blur` = `blur(18px) saturate(120%)` |
| sidebar/topbar серые и отделены от карточек | норма 1280×800: header `rgba(24,28,35,.9)`, sidebar/bottom-nav `rgba(33,37,45,.62)` ≠ card `rgba(21,27,42,.5)`; `--shell-bg` ≠ `--glass-bg` |
| ничего не съезжает | `scrollWidth ≤ innerWidth+1`; `body::before` opacity = 0.30 (≤0.32, виньетка убрана); vertical-инварианты hotfix4 (`rect.bottom ≤ innerHeight/stable`) сохранены |
| §9-инвариант | `backdrop-filter: url(` — **0** совпадений в подключённых стилях |

`appShell` в fullscreen: 1280×800 → `h = 800 = innerHeight` (вне Telegram), mobile 320×700 → `h = stable = innerHeight−56` (shell ровно по видимой области, низ не обрезается).

### Round 2 (review F-2): реальный фолбэк высоты (`--shell-h`)

- Проба `F7_PROBE_JS`/`f2ShellH` добавлена: на синтетическом стенде воспроизводит прежнюю цепочку объявлений custom property и эмулирует отсутствие `dvh` (заведомо неподдерживаемая единица в `@supports`-условии).
- Прогон 3 (после правки F-2): `[matrix] failures: 0` (10 вьюпортов × normal/fullscreen). Для 1280×800: база `100vh` → `min-height = 800px = innerHeight`; прежняя цепочка → `0px` (баг воспроизведён, эмуляция рабочая); `.app-shell` в normal → `800px` (не `auto`), в fullscreen → `0px` (по D1.2, `min-height:0`).

## Сохранённые пробы (регресс не ослаблен)

Палитра §8/фон §10 (60–90 c / 90–120 c), glass allow/deny + tier A маркеры, `@supports`-фолбэк, AA `.text-gray-500`, AA панельного текста, flex/overflow, порядок навигации, F3-селектор области, reduced-motion, hidden-пауза — все без FAIL.

## Честные ограничения (НЕ воспроизводится headless)

- **Реальный Telegram WebView / фактический fullscreen** (mobile fullscreen inside Telegram) — только live-гейт **T-2682** (владелец). Матрица форсирует событие SDK на локальном http-стенде; это проверяет раскладку/токены, но не поведение нативного клиента.
- **FPS glow/specular** на слабом устройстве — live-гейт (перф-бюджет лишь ограничен кэпом DPR/свечения).
- **«Премиальность»** (визуальная оценка) — глазами владельца по скриншотам/live; автоматике недоступна.
- Стаб `/api/status` не содержит `uptime.generated_at` → состояние heartbeat `UNKNOWN` (корректная семантика «нет данных», не артефакт).

## Вердикт по автоматической части UPD 6

**PASS** (Playwright-матрица 5 режимов: 10 вьюпортов × normal/fullscreen, 0 FAIL). Live-пункт T-2682 остаётся открытым (владелец).
