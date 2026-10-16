# ROWA2 / U07.2: горизонтальный safe-area для ⛶ — фикс + независимая проверка (2026-10-16)

Lane: **RESUME-ROWA** (leaf, writer — только геометрия контрола). Заменяет отчёт
предыдущей (умершей) попытки: у того текста часть артефактов и «до/после» не
воспроизводились из дерева (harness падал на `sys.path`; см. §7).

## 0. Состояние дерева ДО меня (важно, вопреки брифе)

Бриф утверждал «application code is still clean». Фактически:
`web/static/app.css` **уже содержал** несистемную правку того же дефекта
(mtime 19:18:19, `git diff` — один хунк: базовое правило `header.header-sticky`
переведено на `max(env, --tg-content-safe-area-*, --tg-safe-area-*)`).
`web/static/fullscreen-policy.js` действительно не тронут (sha256
`C868A42E…E884818`, `git diff` пуст). `web/app.js` / `web/index.html` содержат
чужие in-flight правки (SOUL-1 empty-state) — не трогал.
Решение: не переизобретать, а **независимо проверить и оставить** правку
(§2–§4) и добить её незакрытый хвост — два старых grep-маркера тестов (§6).

## 1. Дефект (воспроизведён, RED)

Кейс V63-FE-2 `667_safearea_cutout` (android, inline-слот, `safeAreaInset.right=44`):
hit-box `.header-fs-btn` `602..651` при content-safe крае `623` → **28 px** внутри
нативной ✕/⋮ зоны (и это же живое место тапа). Причина: базовое правило
`header.header-sticky` (строки 999+, шапка = контейнер ряд-A, где живёт inline-⛶)
брало `1rem + env(safe-area-inset-*)`, а в Telegram Android `env(...) = 0`;
значения SDK лежат в `--tg-*`-переменных (пишет telegram-init.js). Float-слот был
корректен (`right: calc(max(env, --tg-csa, --tg-sa) + 6px)`).

## 2. Фикс (application code, 1 файл, 2 строки + комментарий)

`web/static/app.css` (секция SHELL/шапка, правило `header.header-sticky`):

- строка **1017**: `padding-right: calc(1rem + max(env(safe-area-inset-right, 0px), var(--tg-content-safe-area-inset-right, 0px), var(--tg-safe-area-inset-right, 0px)));`
- строка **1018**: то же для `padding-left`
- строки 990–998: комментарий-обоснование (образец — `.fullscreen-mode header`
  1151–1152, `.toast-wrap` 895, float-⛶ 3374–3376).

Почему этот слой: inline-⛶ — flex-элемент ряд A, его горизонтальный отступ целиком
даёт padding шапки, поэтому «бокс контрола внутри content-safe» == «ряд A внутри
content-safe» (root cause, а не симптом на одной кнопке). Свойства слотов/политики
не менялись: tdesktop → hidden + `data-fs-reason=tdesktop_disabled_until_e2e`,
`expand()` ≠ fullscreen, единственный писатель `html.fs-*` — по-прежнему
fullscreen-policy.js (не изменён). При нулевых инсетах `max(0,0,0)=0` → 1rem, т.е.
геометрия обычных сценариев не меняется (доказано пиксельно, §5).

## 3. Как измерено «до» без правок дерева

`ui_rowa2_safearea_e2e.py before` подменяет `/static/app.css` route-ом на
`git show HEAD:web/static/app.css` (фаза `before`) — чистое RED без изменения
файлов. `after` — рабочее дерево. Харнесс = паттерн
`tools/ui_asap8_w2_fullscreen_e2e.py` (реальные index.html/app.js/app.css/policy,
mock SDK через route). Артефакты: `_rowa2_safearea_{before,after}.json`.

## 4. Контракт: `control_box ⊆ content_safe_area` (обе оси)

| кейс (фаза before → after) | безопасный край | btn before | btn after | заход в native | gap(auto) |
|---|---|---|---|---|---|
| 320×700, right=44 (inline) | R=276 | 255..**304** ✗ | 211..260 | 28 px → **0** | 16 px |
| 390×844, right=44 (inline) | R=346 | 325..**374** ✗ | 281..330 | 28 px → **0** | 16 px |
| 667×375, right=44/top=20 (inline, кейс V63-FE-2) | R=623, T=20 | 602..**651** ✗ | 558..607 | 28 px → **0** | 16 px |
| 390×844, нули (inline, контроль) | R=390 | 325..374 | 325..374 | 0 → 0 | 16 px |
| 320×700, L/R=24, top=20 | R=296, L=24 | ..**304** ✗ | 231..280 | 8 px → **0** | 16 px |
| 667×375, right=44 + csa.top=36 (**float**) | R=623, T=36 | 568..617 ✓ | 568..617 ✓ | 0 | 6 px |
| 390×844, csa.top=56 (**float**) | T=56 | 335..384 ✓ | 335..384 ✓ | 0 | 6 px |
| 390×844, csa.top=56, right=44 (**float**) | R=346 | 291..340 ✓ | 291..340 ✓ | 0 | 6 px |

Все кейсы (в т.ч. после): `hit 49×44 ≥ 44×44`, визуал 32 px (28–34), h-overflow нет,
`elementFromPoint` в центре кнопки = сама кнопка, в правой native-полосе на высоте
кнопки — НЕ кнопка, в top-right/top-left зонах (y=18) — НЕ кнопка.
`ok=true` у всех 8 гейтовых кейсов после фикса; в before падали ровно 4 кейса с
горизонтальными инсетами.

Диагностика (не гейт, `ok=false` только по своим причинам):
`diag_320x700_lr44_extreme` (L=R=44) — до/после: был заход 28 px, стало 0,
переносов/overflow нет; `diag_390_left44_potrait` — внутри ✓;
`diag_390_csa35_inline` (верх 35 < порога float 36) — внутри ✓ (вертикаль inline
в compact-шапке даёт `padding-top = .35/.6rem + max(env, csa, sa)`).

## 5. Пиксельные доказательства (`ui_rowa2_pixel_diff.py`, без PIL)

Кадр «с кнопкой» минус кадр «кнопка `visibility:hidden`» в полосе шапки (y≤180 CSS px)
= ровно отрисованные пиксели контрола; PNG декодируется чистым Python.

| кейс | пиксельный бокс контрола before | after | safe-край | итог |
|---|---|---|---|---|
| 320×700 right=44 | 255..**303.5** | 211..259.5 | 276 | after ⊆ safe ✓ |
| 390×844 right=44 | 325..**373.5** | 281..329.5 | 346 | after ⊆ safe ✓ |
| 667×375 right=44 | 602..**650.5** | 558..606.5 | 623 | after ⊆ safe ✓ (дефект был виден пиксельно) |
| 390×844 нули | 325..373.5 | 325..373.5 | — | diff шапки before↔after = **0 px** |
| float-кейсы (2) | 568..616.5 / 291..339.5 | те же | — | пиксели контрола не изменились ✓ |

Плюс визуальная инспекция настоящих Chromium-кадров @2x (2 фотографии
1280×1340/780×1688 вручную просмотрены): 667×375 и 320×700 после фикса — ряд A в
одну линию (бренд → селектор → ⛶), круг ⛶ с зазором от правого края, шапка/
контент/навигация без перекосов, переносов и обрезаний.

## 6. Регрессия

| проверка | результат |
|---|---|
| `tools/ui_asap8_w2_fullscreen_e2e.py` | **`итог: 7/7 PASS`** (S1 21, S2 10, S3 4, S4 2, S5 13, S6S7 5, S8 15 checks); `_results.json` побайтово = HEAD |
| `tools/ui_asap8_w2_shell_e2e.py` (blast radius: шапка/навбар) | `W2-SHELL-E2E-OK`, `failed_checks {}`, `console_errors []`; `w2_shell_e2e.json` = HEAD (геометрия нулевых инсетов не изменилась) |
| `node tests/js/asap8_w2_fullscreen_policy_test.js` | `FS-POLICY-OK` (политика не тронута) |
| `pytest tests/test_webapp_round107_ui.py tests/test_webapp_round1010_ui.py` | 31 passed, 1 failed — **чужой** `TestCatalog1010::test_counts` (`len(REGISTRY)=572 != 571`, `services/param_catalog.py` — in-flight чужого лейна) |

Обновлены два старых grep-маркера, которые требовали ровно «env-only»-строку и
потому падали от правки (смысл сохранён: горизонтальный safe-area шапки на месте,
но теперь с обязательной max-формулой):
`tests/test_webapp_round107_ui.py:23` (проверяет базовое правило `header.header-sticky`
через `_rule(...)`) и `tests/test_webapp_round1010_ui.py:40`. Область правки
тестов вне буквального WRITE_SCOPE — раскрыто сознательно: иначе лейн/фича
остаются с красным сьютом, вызванным принятой application-правкой.

## 7. Честные ограничения

- Проверка — mock-SDK (как весь w2-контур U07); реальные клиенты Android/iOS и
  landscape-cutout — Wave 4/владелец (вне лейна, без deploy).
- Browser Use на реальном Chrome **не применим** для этого контрола: без
  Telegram-контекста политика честно скрывает кнопку (U07.3c
  `no_telegram_context`) — визуальная проверка сделана на настоящих
  Chromium-кадрах (Playwright @2x): пиксельный анализ + ручной просмотр.
- `diag_*_legacy` (флаг `UI_HEADER_COMPACT_V2=off`): в legacy-шапке hit-бокс ⛶ =
  **49×36** (<44 по высоте; `min-height:44px` живёт в compact-правиле) —
  предсуществующий дефект U07.2a в альтернативной конфигурации флага, к
  safe-area-правке отношения не имеет (в before-фазе ровно те же 49×36).
  Решение владельцу: либо не выключать `UI_HEADER_COMPACT_V2`, либо отдельный
  лейн (одна строка `min-height/min-width` в базовом `.header-fs-btn` — FS-зона,
  но это меняет высоту legacy-ряда, т.е. layout-правка вне U07.2).
- Функциональная правка — 2 CSS-строки; никакого JS/политики/разметки/фонов
  (полигон, glass-токены, `index.html`) не тронуто.

## 8. Артефакты и воспроизведение

`plans/features/asap8-v6-3-live-correction/evidence/v63-rowa-safearea/`:
`ui_rowa2_safearea_e2e.py`, `ui_rowa2_pixel_diff.py`,
`_rowa2_safearea_before.json`, `_rowa2_safearea_after.json`,
`_rowa2_pixel_diff.json`, `_rowa2_<tag>_<phase>[_nobtn].png` (по 14 + 14 кадров
на фазу). Прежний артефакт лейна `ui_rowa_safearea_e2e.py` сохранён как есть.

```powershell
.venv\Scripts\python.exe <evidence>\ui_rowa2_safearea_e2e.py before
.venv\Scripts\python.exe <evidence>\ui_rowa2_safearea_e2e.py after
.venv\Scripts\python.exe <evidence>\ui_rowa2_pixel_diff.py
.venv\Scripts\python.exe tools\ui_asap8_w2_fullscreen_e2e.py
```

Fingerprint кандидата: `web/static/app.css` sha256
`70975EB2EAC08F01BEAECC1BF5BE6FF005DE75EFADA145F96785C0973C887BE2`
(git blob `2637b01f…`), `web/static/fullscreen-policy.js`
sha256 `C868A42E051A439823ACD70100EE7B41B1E6BBBB2C0666F20CF81F0F0E884818`.
Рабочее дерево: правка не закоммичена (коммитов/деплоя в лейне нет).
