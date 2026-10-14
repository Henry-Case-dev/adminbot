# round 10.26 — Polygonal Luminescence: приёмочный отчёт (§19)

> **Фича:** `polygonal-luminescence-round1026` (EXTRA, визуальный) · **ADR:** ADR-1026-3
> **Маркер:** `POLYGON-LUMINESCENCE-OK` · **Сборка:** `APP_VERSION` **2.58.19**
> (bump 2.58.18 → 2.58.19) · **Флаг:** `UI_POLYGON_BG_ENABLED` (env-only, default ON)
> **HEAD (базис):** `9d046e5` · **Вьюпорты:** desktop 1440×900, mobile 390×844.
> **Инварианты:** Δ DDL = 0, Δ каталога = 0 (467/426/442/100/98/21), CSP `script-src 'self'`.

## 1. Идентификация

| Параметр | Значение |
|---|---|
| Рендерер | `web/static/polygon-background.js` (Canvas 2D, Delaunator 5.0.0) |
| Откат | `UI_POLYGON_BG_ENABLED=false` → Dark Aurora Flow (`aurora-flow.js`, OGL, сохранён) |
| Триангуляция | `Delaunator.from` (vendored IIFE `delaunator.5.0.0.min.js`, ISC, SHA в vendor README) |
| Стекло | `@liquidglassjs/core` 0.5.3 (не добавлялась вторая библиотека); default OFF |

## 2. Диагностика `getDiagnostics()` (11 полей §14.1, не в UI)

| Кейс | renderer | canvasW×H | DPR | nodeCount | triangleCount | frameCount | isPaused | isReducedMotion | contextLost |
|---|---|---|---|---|---|---|---|---|---|
| desktop Статус | canvas2d | 1440×900 | 1 (Playwright) | **110** | **189** | растёт | false | false | false |
| mobile Статус | canvas2d | 390×844 | 1 | **55** | **93** | растёт | false | false | false |

Бюджет §6.1 (90–140 / 45–75) соблюдён; DPR-кап 2 / 1.5 соблюдён.

## 3. Движение (кадры 0/5/10/20 с, §14.2)

Метрика — медианный сдвиг локальных максимумов яркости (позиции узловых ячеек),
не яркость:

| Кейс | median_shifts (5/10/20 с) | corr(0,20с) | Вывод |
|---|---|---|---|
| desktop Статус | 1.41 / 1.41 / 1.41 ячейки | 0.943 | **меняется положение**, не только яркость |
| mobile Статус | 1.41 / 1.41 / 1.41 ячейки | 0.893 | **меняется положение** |

Fullscreen: `frameCount` растёт (110/189: 521→548→570; 55/93: 666→694→715),
`nodeCount` не меняется (seed не сброшен), `rect.x=0`, `rect.w == innerWidth`
(нет левой полосы/сдвига).

## 4. Композиция §14.3 (программно)

| Кейс | сиреневые | циановые | яркие | edge-density | local_ratio |
|---|---|---|---|---|---|
| desktop Статус | 6.7 % | 8.2 % | 20.1 % | 0.306 | **2.19** |
| mobile Статус | 3.8 % | 4.4 % | 3.6 % | 0.274 | **2.28** |

Сиреневые и циановые области присутствуют; граней/линий — 27–31 % ячеек;
яркость локальна (`local_ratio` > 2 — топ-10 % ячеек ярче среднего более чем в 2×).

## 5. Материалы §14.4 (gitignored `tools/_ui_round1026_shots/`)

`desktop_status_{normal,fullscreen}.png`, `mobile_status_{normal,fullscreen}.png`,
`desktop_modules_{normal,fullscreen}.png`, `mobile_modules_{normal,fullscreen}.png`
(+ сырой `tools/_ui_round1026_raw.json`). Видеозапись не снималась (недоступна
headless) — **PENDING OWNER**.

## 6. Сравнение с Aurora (SC-39)

Матрица §71 (`tools/ui_round1025_matrix.py`) намеренно зафиксирована на откатном
пути Aurora (`UI_POLYGON_BG_ENABLED=false`) → **0 failures** (регрессии нет).
Полигональный фон проверен отдельным прогоном `tools/ui_round1026_polygon.py` →
**0 failures**. Оба пути проверены в одинаковых viewport'ах; визуальное сравнение
по скриншотам — материал для владельца (PENDING OWNER).

## 7. Стекло (§12)

Прототип (T-3201/T-3202): см. `plans/reports/round1026_polygon_glass_prototype.md`.
Режим `refraction` с явным `source`; белого прямоугольника нет (white_frac 0.46 %);
конфликта WebGL нет; mobile ~60 FPS. Пп. 1/5/7 — **PENDING OWNER**. Интеграция в
UI (блок J) **не выполнена** (гейт §13.2 не пройден headless); `UI_LIQUID_GLASS_LIB`
остаётся default OFF. `blur ≠ рефракция`; hotfix10 не повторён.

## 8. Инварианты (с доказательствами)

| Инвариант | Доказательство |
|---|---|
| Δ DDL = 0 | новых миграций/таблиц нет; `services/pg_db.py` не менялся (заморожен `test_round1025_f8_registry`) |
| Δ каталога = 0 | `UI_POLYGON_BG_ENABLED` ∉ `pc.REGISTRY`; 467/426/442/100/98/21 (`tests/test_webapp_round1026_polygon.py`) |
| CSP `script-src 'self'` / no-CDN | все `<script src>` same-origin; vendor local; тест `test_no_cdn_hosts` |
| Один активный рендерер | ON → `#polygon-background`, `#aurora-flow-canvas` отсутствует, `visibleBgCanvases=1` |
| R17/R18 | `plans/current_task.md` не изменялся; бэкапы/теги не трогались |
| pytest | зелёный полный прогон (см. evidence.md) |
| JS-тесты | 43/43 файлов `node tests/js/*.js` = OK |
| `git diff --check` | чисто (см. evidence.md) |

## 9. §15 «НЕ завершено, если…» — по пунктам

| Пункт | Статус |
|---|---|
| Градиент вместо полигонов | ✅ полигональные грани (edge 0.27–0.31, triangleCount 189/93) |
| Сиреневые почти отсутствуют | ✅ 3.8–6.7 % пикселей |
| Светятся только точки, не грани | ✅ 3 прохода заливки граней + свечение рёбер |
| Равномерная заливка | ✅ `local_ratio` 2.19–2.28 |
| Хаотичная плотная паутина | ✅ фильтр рёбер (MAX_EDGE_NORM), тонкие батч-линии |
| Резкие скачки формы | ✅ топология ≤4 Гц + fade 320 мс; позиции в нормализованном пространстве |
| Анимация почти незаметна | ✅ median shift 1.41/20 с, corr 0.89–0.94 |
| Сдвиг влево/полоса у Sidebar в fullscreen | ✅ `rect.x=0`, `rect.w==vw` |
| Несколько фоновых рендереров | ✅ `visibleBgCanvases=1`, Aurora не запущена |
| Стекло даёт непрозрачные прямоугольники | ✅ не интегрировано; прототип white_frac 0.46 % |
| Фон мешает читать параметры | ✅ canvas `pointer-events:none`, z-index 0, вне контейнеров; AA-материалы для владельца |
| Заметная просадка производительности | ⚠ headless ~60 FPS; реальный WebView — **PENDING OWNER** |

## 10. Ограничения / техдолг + live-статус

- **PENDING OWNER VERIFICATION:** реальная оптическая рефракция стекла (п.1),
  субъективный внешний ореол (п.5), перф/плавность и читаемость в реальном
  Telegram WebView; видеозапись анимации.
- Блок **J** (точечная glass-интеграция) заблокирован гейтом §13.2.
- Сравнение «до/после» с Aurora именно на полигональном пути — материал для
  владельца (аппаратно не воспроизводимо headless).
