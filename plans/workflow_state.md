# Workflow State (operational checkpoint)

> Краткий оперативный чекпоинт оркестратора. Не транскрипт. Обновляется после каждого верифицированного шага.

- **task_id:** round1025-hotfix7-shell-glass-heartbeat (внеплановый приоритетный пакет; имя рабочее)
- **Запрос (источник):** **UPD «Срочный фикс текущего фронта»** в `plans/current_task.md`, **строки 6073–6154** (дословно прочитан Step 0, файл НЕ изменялся). Это новый авторитетный приоритетный запрос, выше F4.
- **HEAD при старте:** `5a5465c` (== `origin/master`; рабочее дерево содержит только правки `plans/`: MEMORY/backlog/workflow_state/features-F4-tasks; код не менялся)
- **Активный пакет:** UPD-фикс `hotfix7-shell-glass-heartbeat-round1025` — **Step 0 @Memory (только анализ; код не трогался)**
- **Активная фича (прежняя):** `module-catalog-quickpanel-store-round1025` (F4) — **⏸ PAUSED (Step 0–1 done)**, возврат после UPD-фикса
- **APP_VERSION:** 2.58.7 (deployed; на Шаге 0 не менялся)

## Статус шагов (строгий воркфлоу) — HOTFIX7 (UPD-фикс)
| Шаг | Агент | Статус | Evidence |
|---|---|---|---|
| 0 context | @Memory | ✅ | Дословный разбор UPD (6073–6154), карта кода UPD 1–6, конфликт-чек с hotfix6/ADR-1025-12, черновой аудит остатка `current_task.md`, риски, baseline, KG-узлы HOTFIX7 |
| 1 plan | @PM | ⏳ | Декомпозиция блоков UPD 1–6 (+ аудит-хвост UPD 7); задачи продолжать с **T-2658** (максимум занятого ID — T-2657, F4) |
| 2 design | @Architect | pending | spec.md + **ADR-1025-13** (номер свободен; F4-ADR не оформлен — переиспользовать/развести при старте) |
| 3 graph | @Memory | ⏳ | KG Step 0 записан; синк plan/design — после Шагов 1–2 |
| baseline | @DevOps | pending | точка отката (`pre-round1025-hotfix7`) — при старте реализации |
| 4 build | @Builder | pending | — |
| 5 review | @Reviewer | pending | — |
| 6 audit | @Scanner | pending | — |
| 7 merge | @Architect | pending | — |
| 8 archive | @PM | pending | — |
| 9 deploy | @DevOps | pending | — |
| 10 metrics | @Memory | pending | строка в `plans/metrics.md` для HOTFIX7 **ещё не создана** (не выдумывать до верификации) |

## UPD — суть (сверено с файлом, строки 6073–6154)
1. **Layout + fullscreen:** стабилизировать геометрию header/sidebar/main/bottom-nav; в fullscreen ничего не пропадает/не обрезается/не наезжает; **виджет «Сердцебиение» не должен исчезать в fullscreen** (container sizing, overflow, z-index, sticky/fixed, safe-area, расчёт высот, поведение Telegram fullscreen/webview).
2. **Полностью переделать «Сердцебиение»:** premium pulse/heartbeat (не «линия + плавающая точка»); цвет/интенсивность от реальных метрик (норма — бирюзово-зелёный, warning — янтарный/оранжевый, critical — красно-розовый); анимация пульса/свечения; **без «плавающей точки»** и без бесконечного CSS `translateX`; состояние читается с первого взгляда; проверить normal/fullscreen/mobile.
3. **Glass — панели остаются серо-графитовыми** и визуально отдельным слоем; не сливаться с карточками; shell и карточки — разные тон/глубина.
4. **Настоящий liquid glass:** полупрозрачный серо-графитовый base + backdrop blur + мягкая внутренняя подсветка + тонкая светлая обводка + слабый specular highlight + аккуратный шум/текстура + разделение фон/shell/карточки по глубине; **без грубой виньетки и грязного затемнения**.
5. **Shell:** header выровнять (без наезда на контент); sidebar/topbar — цельные shell-элементы; mobile — safe-area, Telegram chrome, нижний bar, fullscreen; устранить все съезды.
6. **Обязательная проверка:** desktop normal/fullscreen, tablet, mobile regular, **mobile fullscreen внутри Telegram WebView**; скриншоты + Playwright (heartbeat виден везде; header не ломается; glass quality; sidebar/topbar серые и отделены; ничего не съезжает).
7. **После фиксов (без human gate):** аудит `current_task.md` → все невыполненные задачи → продолжить по приоритетам; частично сделанные — проверить и довести; в отчёте явно: (1) что исправлено по UI, (2) какие пункты оставались, (3) что взято следующим. Не делать редизайн с нуля, не ломать IA, не упрощать до «косметического blur».

## Верифицированные результаты Step 0 (evidence, 22.09.2026)
- **Baseline (локально):** HEAD `5a5465c`; `APP_VERSION` **2.58.7**; pytest 8185/0 и JS 26/26 — по подтверждённой записи Step 0 F4 (в этом сеансе не перезамерялись); каталог REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / Settings 418.
- **Карта кода shell/layout:** `.app-shell` (flex-колонка) `web/static/app.css:805-810`; `.scroll-area` `:811-818`; `.fullscreen-mode` `:819-828`; `header.header-sticky` `:747-759`; `header-compact-v2` `:765-800`; desktop sidebar/drawer/bottom-nav/more-sheet `:1560-1674`. Разметка shell — `web/index.html:47-230` (`.app-shell`+`aside.app-sidebar`+`header.main-header`+`main.scroll-area`), heartbeat — `web/index.html:2778-2815`.
- **Карта кода fullscreen:** класс `fullscreen-mode` — `web/index.html:49`; `isFullscreen` state `web/app.js:1094`; `toggleFullscreen` `app.js:4717-4744`; `initFullscreen` `:4750-4780`; `setFullscreenFromTma` `:4784-4791`; `teardownFullscreen` `:4795-4806`; safe-area/offset — `web/static/telegram-init.js:36-89` (`computeBottomOffset`, `--tg-*`); `--header-h` (ResizeObserver) — `app.js:8564-8586`.
- **Карта кода heartbeat:** разметка `web/index.html:2786-2815`; computed `heartbeat` `app.js:1722-1740`, `heartbeatLegacy` `:1746-1784`; Canvas цикл `startHeartbeatCanvas`/`_hbFrame`/`_hbDraw` `app.js:6589-6678`; state-machine `_heartbeatTransition` `:6440-6507`; телеметрия `heartbeatSample` `:6512-6561`; CSS `.ekg*`/`.hb-*` `app.css:856-913`.
- **Карта кода glass:** токены `app.css:52-65`; `.card` `:169-176`; `card-solid` `:178-180`; glass-set карточек `:1028-1043`; линза `[data-glass="a"]::before` `:1053-1092`; tier B/C `:1095-1120`; `@supports`-фолбэк `:1159-1173`; inline SVG-фильтр `#lg-lens` `index.html:34-46`; панели `:1564-1574/1589-1598/1609-1623/1659-1674`; reconcile `app.js:8500-8560`.
- **Конфликт-чек (факт по коду):** (1) `.app-sidebar` использует **тот же** `--glass-bg` (rgba(21,27,42,.5)), что и `.card`/`.module-card`/`.hub-card` → тон/глубина shell и карточек **идентичны** (корень UPD 3); header держит `--glass-bg-strong` (.85) из-за приоритета `header.header-sticky` (0,1,1) над `[data-glass="a"]` (0,1,0). (2) В `_hbDraw` есть **сдвигающийся вбок импульс** `pulseX = ((t*1000)%span)/span*w` (`app.js:6672-6674`) — это и есть «плавающая точка»; основная линия — бегущая синусоида `:6658-6666`; свечения/сердцебиения/интенсивности нет (корень UPD 2). (3) `--glass-shadow` `rgba(3,7,18,.75)` + `body::before` conic-градиент (opacity .42) + плотная `.85` дают «грязное затемнение» (кандидат корня UPD 4).
- **Граница F4:** `plans/features/module-catalog-quickpanel-store-round1025/tasks.md` — Step 1 @PM готов (T-2619…T-2657, 39); Step 2 @Architect (spec/ADR) НЕ начинался.

## Неразрешённое / открытое (HOTFIX7)
- **Решение (Step 1/2):** как разделить shell и карточки по тону/глубине — новые токены (`--shell-*`/card) vs развести существующие `--glass-*` без Δ каталога (предпочтительно — CSS-токены только).
- **Решение (Step 1/2):** как сохранить «серый/графитовый» тон shell при уже принятой палитре §8 (`--glass-bg` сейчас синевато-графитовый) — уточнение значений, не отказ от §8 (AMEND ADR-1025-9 D2 / ADR-1025-12).
- **Решение:** новый визуальный язык heartbeat — Canvas 2D (reuse текущий движок/состояния) vs гибрид (Canvas + CSS-обвязка); обязательные требования — без «плавающей точки», с пульсом/свечением, цвет/интенсивность от метрик.
- **Решение:** причина «сердцебиение исчезает в fullscreen» — подтвердить Playwright/живым WebView (Step 0 не воспроизводит; кандидаты: `min-height` vs `height` у `.app-shell`, переполнение/обрезка, `--header-h`, позиция `bottom-nav`).
- **Наследуемые live-гейты владельца (не блокеры):** T-2617 (hotfix6, WebView) + F2 T-2561, F3, hotfix5, F1 T-2409, hotfix3 T-2505, hotfix4 T-2527.

## История (завершённые пакеты раунда 10.25)
- **F4 `module-catalog-quickpanel-store-round1025` — ⏸ PAUSED (Step 0 @Memory + Step 1 @PM done, 22.09.2026).** `tasks.md` детализирован (блоки 0, A–H, 9; **T-2619…T-2657, 39**); `spec.md`/ADR — не начаты. Папка — `plans/features/module-catalog-quickpanel-store-round1025/`. **Возврат — после закрытия UPD-фикса.** Не дублировать/не ломать: scope-контракт F3 (§37–§42 store), F0 write-path (`persistItems`).
- **Волна 1.5 — `hotfix6-webview-shell-heartbeat-round1025` — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаги 7–10, 22.09.2026).** Архив — `plans/archive/hotfix6-webview-shell-heartbeat-round1025/` (spec.md + **ADR-1025-12** + tasks.md T-2581…T-2618 + deployment.md **VERIFIED**); Merge — `plans/ARCHITECTURE.md` **§58**. Код `055525c` + docs `ba75751`; прод fast-forward; APP_VERSION **2.58.7**; health 200; `database is locked` 0. Реализовано: **A** foreground-линза `[data-glass="a"]::before` + `filter:url(#lg-lens)`; **B** `computeBottomOffset()`; **C** Canvas 2D + rAF heartbeat §15; **D** двухстрочная шапка + ⛶ по safe-area. Техдолг §58.7 (M-H6-1, L-H6-1/-2/-3, I-H6-3). ⏳ T-2617 live. Откат: тег `pre-round1025-hotfix6` + `git revert`; soft — env `UI_HEARTBEAT_CANVAS_ENABLED`/`UI_HEADER_COMPACT_V2`/`UI_GLASS_TIER_OVERRIDE`. Бэкап `var/backups/hotfix6-round1025-20260922-013551/` и `stash@{0}` **НЕ удалять** (R18).
- **Волна 1 — `F2 design-tokens-liquidglass-v2-round1025` + `hotfix5 summary-cover-window-round1025` + `F3 global-scope-selector-round1025` — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (пакет `4cde1bc`, APP_VERSION 2.58.6, Merge §57).** Архивы — `plans/archive/design-tokens-liquidglass-v2-round1025/` (ADR-1025-9), `plans/archive/hotfix5-summary-cover-window-round1025/` (ADR-1025-11), `plans/archive/global-scope-selector-round1025/` (ADR-1025-10). @Scanner **C0/H0**; pytest 8146/5/1 (5 — env), JS 25/25; Δ DDL=0, Δ каталога=0.
- Ранее: F0 (Wave 0), hotfix-media, F1 (Wave 1), P0-fix (hotfix2), hotfix3, hotfix4 — все COMPLETED + MERGED + ARCHIVED + DEPLOYED (см. `plans/MEMORY.md` и `plans/ARCHITECTURE.md` §52–§56).

## Деплой
- Прод из среды @Memory не проверялся (нет SSH). Последнее подтверждённое состояние: HEAD **`ba75751`**, `APP_VERSION` **2.58.7**, `/api/health` 200, `database is locked` 0 (Шаг 9 @DevOps hotfix6, `deployment.md` **VERIFIED**).
- Откат: теги `pre-round1025*` + `git revert`; soft-откат hotfix6 — env-флаги. Бэкапы/теги/`stash@{0}` не удалять (R18).

## Last update
- 22.09.2026 — **Step 0 @Memory по НОВОМУ приоритетному UPD** (`plans/current_task.md`, строки 6073–6154, прочитан дословно, файл НЕ изменялся): F4 переведена в **⏸ PAUSED (Step 0–1 done)**, активный пакет — **UPD-фикс `hotfix7-shell-glass-heartbeat-round1025`**; зафиксированы карта кода UPD 1–5, конфликт-чек с hotfix6/ADR-1025-12 (слияние shell и карточек через общий `--glass-bg`; «плавающая точка» `_hbDraw`; кандидаты ломки fullscreen), черновой аудит остатка `current_task.md`, риски Critical/High, baseline, KG-узлы HOTFIX7. Код/коммиты/`current_task.md` не трогались. Следующий шаг — **Step 1 @PM** (декомпозиция UPD 1–6 + UPD 7-хвост).
