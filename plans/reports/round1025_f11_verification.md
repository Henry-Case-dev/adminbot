# F11 `status-showcase-dashboard-round1025` — верификация §11/§18/§77 + UI §70

> **Агент:** @Builder (T-3085/T-3086/T-3087/T-3088/T-3089). **Дата:** 23.09.2026.
> **Baseline:** HEAD `25cc19c`, `APP_VERSION` 2.58.16. **После F11:** `APP_VERSION` 2.58.17.
> **Инварианты:** Δ DDL=0, Δ каталога=0, CSP/zero-build, §15/§18/§20 не переписаны.

## T-3085 — §18 «Мониторинг Интеллекта» (только верификация, код НЕ менялся)

Подтверждено (статические маркеры + JS-маркер-тест):

| Сущность | Требование §18 | Факт |
|---|---|---|
| Убеждения | живая лента, время+текст, длинные раскрываются, скролл не сбрасывается | `cognitionBeliefsLoop` + `_ribbonLoop` (не тронуты); `ribbon-ts`/`truncate`; анимация CSS `ribbon-scroll` (позиция — CSS-transform, не сбрасывается; `prefers-reduced-motion` → статичный список) |
| Парадигмы | реальные данные/история/причина отсутствия | `cognitionParadigmsLoop` + `ribbon-empty__reason` (`cognitionParadigmsEmptyReason`); данные из `/api/memory/dream/beliefs?kind=paradigm` |
| Эволюция характера | реальные черты/история/состояние экстрактора | `cognitionTraitsLoop` + `_traitsAdapter` (`/api/persona`), бейдж `personaExtractorBadge` |

**Код §18 не изменён:** `git diff` затрагивает только обёртку карточки (удалён вынесенный граф §16) и класс `sg-12`; три `class="ribbon"` и их содержимое сохранены байт-в-байт. Три самостоятельные области НЕ смешаны.

## T-3086 — §11 чек-лист сохранности виджетов (0 потерянных)

| §11 виджет | Где в F11-композиции | Evidence |
|---|---|---|
| состояние бота | Hero §13 (`.status-hero`) + секция «Бот» в метриках | `status-hero`, `status-block__bot` |
| CPU / RAM / диск | `.status-block__server` (7 кол.) | `statusSys.cpu/mem/disk` |
| аптайм | Hero/метрики (`humanizeUptime`) | `humanizeUptime` в обеих |
| живое сердцебиение §15 | `.status-block__pulse` (внутри метрик) | `hb-canvas`/`ekg-trace` не тронуты |
| граф связей | `.status-graph` (строка 2, §16) | `ref="cognitionGraph"` |
| обычный/глубокий сон + бейджи | `.status-sleep` (4 кол.) | `dreamPhaseBadge`/`deepPhaseBadge`/`sleepWidget` |
| убеждения/парадигмы/эволюция | «Мониторинг Интеллекта» (12) | `cognition*Loop` |
| живая лента досье | «Новые факты» §19 (5) | `factsFeed` (reuse `dossierFeed`) |
| бюджеты интеллекта | `.status-budgets` (12) | `budgetInfo`/`memoryContext`/`cognition.dream.budget` |
| превью карты LLM | `.exec-preview` (7, строка 4) | `loadExecPreview` (F6) |
| события | ленты §18 + «Аналитика» (существующие поверхности) | не удалены |
| логи | `#status-logs` (12, строка 6) | viewer не переписан |

Дополнительно сохранены: «Доступность ключей», «История доступности ключей», «Здоровье памяти», media-health — отдельные карточки сетки (`12`). **Потерянных виджетов: 0** (проверено `tests/test_webapp_f11_round1025.py::TestD7WidgetPreservation`).

## T-3087 — Playwright §70/§71 (10 вьюпортов + низкое TG Desktop)

`tools/ui_round1025_matrix.py`: 320×700, 360×780, 390×844, 430×932, 768×1024, 1024×768, 1280×800, 1440×900, 1920×1080, 2560×1440 + fullscreen-режим.

- **`failures: 0`** (артефакт: `tools/_ui_round1025_raw.json`, скриншоты `tools/_ui_round1025_shots/*.png`).
- Нет горизонтального скролла (`scrollWidth <= innerWidth+1`) на всех вьюпортах и маршрутах (включая новый `#/status/graph`).
- Новые F11-пробы: спаны §12 (Hero 5 / метрики 7 / граф 8 / сон 4 от ширины `.status-grid` при ≥992; полная ширина при ≤991), строки §12 (совпадение `top` для Hero/метрики, граф/сон, превью/факты), отсутствие `.status-grid--legacy` при ON, экран `#/status/graph` (шторка/маршрут, контейнер графа, кнопка «Закрыть»).
- **Анти-регресс матрицы:** baseline-worktree `25cc19c` — `failures: 0`. Правки `tools/ui_round1025_matrix.py`: (1) `_reset_scroll` перед shell8/H9/H10 — навигация внутри вкладки не сбрасывает скролл (F1 by design: сброс только при смене вкладки); (2) восстановление скролла в `PROBE_JS`/`F7_PROBE_JS`/H9/H10 после `scrollIntoView` — иначе проба сама прокручивала страницу и ложно-красно отмечала «header перекрывает карточку»/нулевую видимость heartbeat (появление прокручиваемой сетки сузило высоту строки Статуса).

## T-3088 — §77 тест-план heartbeat (реализация §15 НЕ переписывалась)

Проверено (статические маркеры + JS-маркер `F11-HEARTBEAT-OK` в `tests/js/round1025_f11_status_grid_test.js`):

| Пункт §77 | Факт |
|---|---|
| HEALTHY/WARNING/CRITICAL/UNKNOWN | `hbState` + `heartbeat` computed (не тронуты; OFF-дэшборд `heartbeatCanvasEnabled` работает) |
| цвет/частота/амплитуда | `_hbDrawPremium` (canvas) — `colors/freq/amp` по состоянию |
| потеря телеметрии | `loadStatus` catch → `_applyHeartbeatSample({missing:true})` → UNKNOWN |
| восстановление | следующий успешный `loadStatus` → сэмпл → состояние |
| reduced motion | `reducedMotion` → статичный кадр/HB; CSS `@media (prefers-reduced-motion)` без анимации |
| отсутствие избыточных запросов | телеметрия в ритме `startStatusPolling` (30 с); rAF только рисует снимок, сеть в кадре отсутствует |

Контракт `.status-block { max-width:100%; overflow:hidden; }` и `.hb-wrap { min-height:56px }` сохранены (пины hotfix6/10 зелёные).

## T-3089 — §117 п.7–10

| Пункт | Артефакт/факт |
|---|---|
| скриншоты desktop/mobile | `tools/_ui_round1025_shots/{320x700,360x780,...,2560x1440}_root.png` (+ fullscreen) |
| Liquid Glass | декоративный `[data-glass-surface]` при `UI_LIQUID_GLASS_LIB=ON`; функциональные цели (`.status-block`/`.scope-trigger`/⛶) стеклом не покрыты (H10-пробы `failures: 0`) |
| сердцебиение | §77-таблица выше; `hbVisible` в матрице подтверждён |
| интерактивная карта токенов (превью §21 — F6) | `exec-preview` размещено (7 кол., строка 4), компонент/данные F6 не менялись |

## Остаточные риски / не подтверждено локально

- **T-3097 (владелец):** живая приёмка Telegram WebView/TMA (сетка/граф/сон/ленты/логи) — НЕ подтверждена; локальный Chromium ≠ WebView.
- 5 предсуществующих pytest-fail (Telegram send-wrappers, `test_outgoing_guard_round1022`/`test_summary_cover_round1023`) — падают и на baseline `25cc19c`, к F11 не относятся.
- `F11-FU-DOSSIER-TS` (время/тип фактов) и `F11-FU-GRAPH-ALIAS` — follow-up вне F11.
