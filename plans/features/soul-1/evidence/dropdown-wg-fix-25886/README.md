# DROPDOWN-WG — мобильный dropdown «Раздел: …▾» (Аналитика) заблокирован карточкой

Дата: 2026-10-18 · лейн: DROPDOWN-WG (writer web/** + tests/**, без коммита) ·
прод-линия: 2.58.86 (`release/soul1-2.58.86`, d5191450), предыдущие 2.58.85
(`release/win-glass-2.58.85`, 95526863) и 2.58.84 (`release/fs-2.58.84`, 0b7a0aca).

## 1. Симптом (прод, мобильный)

В «Аналитике» открытый список «Раздел: …▾» не отвечает на тап:
`document.elementFromPoint` в центре опции = соседняя карточка
`div.card.glass-panel.p-4.col-span-full`; Playwright click падает с
`intercepts pointer events`. Визуально панель списка НЕ видна (см.
`shot-red-prod-25886-390.png`), хотя `.oversight-mobile-panel` есть в DOM
и `visible` для Playwright.

## 2. Атрибуция (A/B, изолированные worktree, один и тот же probe)

| Дерево | Коммит | viewport | elementFromPoint(центр «Память и интеллект») | тап → hash |
|---|---|---|---|---|
| 2.58.84 (до WG) | 0b7a0aca | 390×844 | `BUTTON.oversight-mobile-option` | `#/oversight?tab=memory` ✅ |
| 2.58.85 (WIN-GLASS-P0) | 95526863 | 390×844 | `DIV.card.glass-panel …` | нет перехода ❌ |
| 2.58.86 (прод) | d5191450 | 390×844 | `DIV.card.glass-panel …` | нет перехода ❌ |
| 2.58.86 (прод) | d5191450 | 667×375 | `INPUT.field w-40` (карточка ниже) | нет перехода ❌ |

**Вывод: это регресс WIN-GLASS-P0 2.58.85** (до WG тап работал). Не
предсуществующий дефект и не SOUL-1: на 2.58.84 зелено, на 2.58.85/86 красно.

JSON-пробы: `attr-pre_wg-25884-green.json`, `attr-wg-25885-red.json`,
`attr-prod-25886-red.json`, `attr-prod-25886-667x375-red.json`.

## 3. Корень

`web/static/glass-refraction.js::rebuild()` (WIN-GLASS-P0, новый файл 2.58.85)
помечает карточку-поверхность `.oversight-tabs` (`data-glass-tier="a"`,
`data-lg-refract="1"`) и пишет inline:

```
:528  surface.style.overflow = 'clip';
:529  if (!rec.prevIsolation) surface.style.isolation = 'isolate';
:533  if (pos === 'static') surface.style.position = 'relative';
```

Открытая панель `web/static/app.css:3402` `.oversight-mobile-panel`
(`position:absolute; z-index:46`) выходит НИЖЕ края карточки
(panel bottom 522 vs card bottom 194 в 390×844) → `overflow: clip` её
обрезает: содержимое не рисуется и не участвует в hit-testing.
`elementFromPoint` возвращает следующую карточку-поверхность (у неё тоже
inline `overflow:clip; isolation:isolate; position:relative`, она идёт позже
в дереве и перехватывает тап). Существующий подъём карточки
`.oversight-tabs.oversight-dd-open { position:relative; z-index:45 }`
(app.css:1429) сам по себе уже не помогает, потому что панель обрезана
контейнером.

Инструментальная проба механизма (in-situ, только CSS-инъекция
`overflow: visible !important` на 2.58.86 без правок файлов):
`attr-prod-25886-css-hypothesis-green.json` → hit = опция, тап =
`#/oversight?tab=memory`. Это подтверждает, что блокирует именно клип,
а не z-order.

## 4. Правка (минимальная, web-only)

`web/static/app.css` (рабочая строка `:1430`; diff +9/−1 — строка правила и
расширенный комментарий):

```diff
     .oversight-tabs.oversight-dd-open { position: relative; z-index: 45; }
+    .oversight-tabs.oversight-dd-open { overflow: visible !important; }
```

+ регресс-ассерт U02.4 в существующем guard-тесте
`tests/js/asap8_w2_shell_mobile_nav_test.js` (TEST-LIFECYCLE:
REGRESSION owner=DROPDOWN-WG).

Почему безопасно:
* действует ТОЛЬКО пока список открыт (Vue-класс `oversight-dd-open`);
  при закрытии inline `overflow: clip` возвращается сам;
* `!important` — единственный способ перебить inline-стиль слоя рефракции;
* слой преломления продолжает жить на карточке: canvas по размеру
  поверхности, маска/рамка на месте (рефракционный e2e 37/37; область панели
  списка совпадает с до-WG кадром 2.58.84 на 99.3% пикселей при пороге >12 —
  остаточные отличия от полупрозрачного фона и изменений 2.58.85/86 вне
  dropdown);
* Tier/бюджеты/probe-логика (`app.js`) не тронуты; полигон/CSS-токены не
  тронуты (frozen-check OK).

Fingerprint правки: `web/static/app.css` sha256
`D700DF753D6D897FC3BD51334BD57489507674E8348C057AF77B7FAAF4E2DD2B`;
`tests/js/asap8_w2_shell_mobile_nav_test.js` sha256
`62F7C2C4B167AAD8F242D9C83E02F8E752D53A2765161E09FFD41264477A3BBC`.
Оба файла байт-идентичны в master (dcea204b) и release/soul1-2.58.86 (d5191450):
`git diff release/soul1-2.58.86 master -- web/static/app.css
tests/js/asap8_w2_shell_mobile_nav_test.js` → пусто ⇒ правка переносима на
прод-линию 1:1. (Прочие tests/** линии релиза отличаются только пинами версии
и правкой не затронуты.) Кандидат правки = master dcea204b + эти 2 файла
in-place (без коммита).

## 5. Проверки (что прогнано)

Правка проверялась в изолированном worktree
`OPENCODE_WORKFLOW_SCRATCH/dropdown-wg-fix` (master + правка, байт-идентично
главному дереву).

| Проверка | Результат |
|---|---|
| Точечный hit-тест 390×844 (probe: elementFromPoint + тап) | ✅ hit = `BUTTON.oversight-mobile-option`, тап → `#/oversight?tab=memory` |
| То же 320×700 и 667×375 | ✅ (667×375 — опция предварительно доскроллена внутрь панели) |
| `tools/ui_asap8_w2_shell_e2e.py` (U01+U02, тот самый тест релиза) | ✅ `failed_checks {}`, **W2-SHELL-E2E-OK** |
| Тот же e2e БЕЗ правки (A/B `dropdown-wg-before`) | ❌ воспроизводит: `Timeout 8000ms … div[data-refract-layer="on"][data-glass-reason="refract-layer"].card… intercepts pointer events` |
| `node tests/js/*` (87 файлов) | ✅ **87/87 OK** |
| Guard-тест `asap8_w2_shell_mobile_nav_test.js` без правки | ❌ падает на новом U02.4 (тест имеет зуб) |
| `tools/ui_win_glass_refraction_e2e.py` (WIN-GLASS-P0) | ✅ **37/37** (21+4+10+2), WG-REFRACT-E2E-OK |
| `tools/ui_asap8_w2_fullscreen_e2e.py` (FS-полоса) | ✅ **12/12, 166 checks** |
| frozen-check (адаптер для worktree, base dcea204b) | ✅ frozen assets/polygon/anchors/CRLF/WG-маркеры сохранены; изменён ровно `web/static/app.css` |
| Browser Use, реальный Chrome (390×844, SDK android, стаб-сервер 8897) | ✅ панель отрисована поверх карточек (`shot-realchrome-fix-390.png`), elementFromPoint = опция, реальный ввод → `#/oversight?tab=memory` |

Примечание к Browser Use: под `Emulation.setDeviceMetricsOverride`
координаты ввода в harness масштабируются ~×1.3 (507/390) — компенсация
×1.3 выбирает ровно «Память и интеллект» (без компенсации выбиралась
соседняя опция). Это особенность эмуляции harness, не продукта; точный
выбор опции независимо подтверждён Playwright-прогоном.

## 6. Риски и хвосты

* Правка затрагивает только открытое состояние одного dropdown; рефракция на
  карточке при открытом списке остаётся без клипа — canvas слоя меньше
  поверхности, на скриншотах артефактов нет. Кромки/блюр карточки не менялись.
* Аналогичный класс риска (popup внутри клипа поверхности рефракции) стоит
  держать в голове при добавлении новых всплывающих списков внутри
  glass-карточек — текущий фикс точечный, по симптом-контракту.
* Не коммичено: дифф на ревью (2 файла). Дальше — независимое ревью,
  затем штатный релиз по PET-режиму.

## 7. Файлы evidence

* Пробы: `attr-pre_wg-25884-green.json`, `attr-wg-25885-red.json`,
  `attr-prod-25886-red.json`, `attr-prod-25886-667x375-red.json`,
  `attr-prod-25886-css-hypothesis-green.json`, `fix-probe-390-green.json`,
  `fix-probe-320-green.json`, `fix-probe-667x375-green.json`.
* Скриншоты: `shot-red-prod-25886-390.png` (панель не видна),
  `shot-green-pre-wg-25884-390.png` (до WG — панель видна),
  `shot-green-fix-390.png`, `shot-green-fix-320.png`,
  `shot-green-fix-667x375.png`, `shot-realchrome-fix-390.png`.
* Логи: `log-shell-e2e-fix.txt`, `log-shell-e2e-before.txt`,
  `log-refraction-e2e-fix.txt`, `log-fs-matrix-fix.txt`,
  `log-frozen-check-fix.txt`, `log-node-guards-fix.txt`,
  `log-guard-test-fix.txt`, `log-guard-test-before.txt`.

Скрипты прогонов (scratch, вне репозитория):
`%OPENCODE_WORKFLOW_SCRATCH%\dropdown-wg\{probe.py, node_sweep.py,
frozen_check_dropdown_wg.py, visual_server.py}`.
