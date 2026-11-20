# W2c card-height fix — независимое targeted review r1

Роль: **Reviewer** (subagent). Модель: **DeepSeek V4.1 Flash 1017** (opencode-go/deepseek-v4.1-flash).
Дата: **2026-11-20, 15:26 +12:00** (03:26 UTC). Режим: read-only по продукту/тестам/картам; единственная запись — этот файл в main checkout, **без коммита**. Нет deploy, SSH, production, release и заявления VERIFIED.

Кандидат: ветка fix/mod-acl-w2c-card-height, tip **51bad063ff47750798b6419456862f83f7db3ca5**; продуктовый фикс **80955000806a0f5fc5a855e72a19b1ce1d039dc5**; база **67ef30cd120163132a2f2e894a0fe474bba9623d**. Проверка — в worktree WorkspaceData/worktrees/c742e4de9e92c489/mod-acl-ux-01-w2c-card-height-caddbb386ab0-865847a1 @ 51bad063f, tracked tree чистый; main checkout master @ df7e21f2a — только этот файл.

    {
      "review": "W2c postdeploy card-height fix (2.58.221 rollback corrective)",
      "verdict": "APPROVED_FOR_RELEASE_PREPARATION",
      "candidate": "51bad063ff47750798b6419456862f83f7db3ca5",
      "product_fix": "80955000806a0f5fc5a855e72a19b1ce1d039dc5",
      "base": "67ef30cd120163132a2f2e894a0fe474bba9623d",
      "covered_ids": ["MAC-S5-CAT-01 (card height 132–164)", "MAC-S5-LAY-01 (affected card layout only)"],
      "product_delta": "web/static/app.css +6/-1; web/index.html +1/-1; web/app.js untouched",
      "version_bump": "none (product-only branch; release line still carries 2.58.221 bump)",
      "independent_runs": {
        "card_height_long_content_3vp": "0 failures; 162.06 / titleH 18 / desc 32 / label 13 at 1680, 1440, 320",
        "w2c_playwright_6vp": "0 failures; 21 cards; 162 at 1680/1440/1280; 132/146/162 at 768/390/320; chips 16/44; overflow 0",
        "m4a_catalog_e2e": "M4A-CATALOG-E2E OK | failures=0",
        "node_w2c_7": "0 fail: 235 / 207 / 64 / 75 / 141 / 356 / 84",
        "affected_python": "same 6 failing nodeids reproduced; no new failure; exact historical 218/6 file batch not reconstructed (see limitations)",
        "mutation_title_clamp_removed": "KILLED: 24 failures / 179.56 / titleH 35 at 3 viewports"
      },
      "real_chrome_browser_use": "1680/1440/320: 160.76, titleH 17.5, ellipsis active, :title full, labels white-space normal, docWidth == viewport",
      "blocking_findings": [],
      "non_blocking": ["EVID-1", "TEST-1", "EVID-2", "UX-1"],
      "residual": [
        "no production/Linux deployed-byte run; postdeploy W2c/M4A + Browser Use still required",
        "committed card-height screenshots are top-of-page, not the media row; independent screenshots supplied in the review run",
        "exact 218/6 affected-Python batch composition was never recorded; exact 218 count not reproduced"
      ],
      "next_action": "Builder/PM merge or cherry-pick the product fix + test/tool into the release line, cut 2.58.222, deploy, then deployed-byte W2c/M4A and Browser Use on the affected media row. No VERIFIED before that."
    }

## 1. Точное дерево и границы

| Проверка | Команда | Результат |
|---|---|---|
| tip/родители | git rev-parse HEAD; git log --format='%H %P %s' -3 | tip 51bad063f; product 809550008 ← 67ef30cd; test a90f152da; docs 51bad063f |
| полный diff vs base | git diff --name-status 67ef30cd..51bad063f | только: web/static/app.css, web/index.html, tests/js/mod_acl_ux_m4a_w2c_navigation_layout_test.js, tools/ui_mod_acl_w2c_card_height_e2e.py, plans/.../fix-card-height/** |
| product diff | git diff --stat 67ef30cd..809550008 | web/index.html 2 +1/-1, web/static/app.css 6 +5/-1; app.js не менялся |
| backend/API/DDL/flags/prompts/storage | проверка списка файлов и diff | изменений нет; config/settings.py не менялся, APP_VERSION не бампался |
| тест | git diff 67ef30cd..51bad063f -- tests/js/... | +2 строки: статическая проверка white-space:nowrap + text-overflow:ellipsis у .module-card .module-title; 83 → 84 проверки |
| чистота | git status --porcelain; git hash-object vs HEAD:path | 0 строк; app.css 7a45bff0…, index.html b74e4430… совпадают с HEAD; после мутации восстановлено побайтно |

Продуктовый diff:

    - <div class="module-title text-sm font-semibold">{{ m.title }}</div>
    + <div class="module-title text-sm font-semibold" :title="m.title">{{ m.title }}</div>
    ...
     .module-card .module-title {
       font-size: 14px; line-height: 1.25;
    +  display: block; min-width: 0;
    +  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
     }

## 2. Причина и семантика фикса

- Падение 2.58.221: карточки медиа-ряда 179.5625 при контракте 132–164; разница с обычной 162.0625 ровно **17.5 px** = 14 px × 1.25 — одна дополнительная строка заголовка. Grid row-stretch поднимал весь ряд; в M4A также mod_vision, conflict/badge/D2/W2a-строки — все та же высота.
- У .module-card .module-title не было ограничения строки; на production ширине карточки 286 px (1440) заголовок переносился на вторую строку.
- Фикс — ровно однострочный clamp заголовка + :title с полным текстом. Описание (-webkit-line-clamp: 2), контрол, tri-state, badge, parent-чип, split, footer и glass-токены не изменены. Дизайн прямо допускает это для узких ширин: design-m3-2026-11-16.md:925 — «длинные названия обрезаются с title/раскрытием».
- D2 сохранён: .module-card .module-control-row__label остаётся white-space: normal; overflow: visible; text-overflow: clip; clamp применяется только к .module-title.
- Селектор .module-card .module-title не задевает .module-quick-meta .module-title (другой контекст) и другие поверхности.

## 3. Независимые прогоны (собственные, не из evidence)

Рабочий чекаут — candidate worktree @ 51bad063f. Стенды — существующие e2e-харнессы, реальные web/index.html + web/static/*, API — фикстуры этих харнессов; production не затрагивался.

| Батч | Результат |
|---|---|
| py tools/ui_mod_acl_w2c_card_height_e2e.py (long content, chat scope) | **0 failures**, 3 viewports. 1680/1440/320: все 4 карточки **162.06**, titleH=18, descH=32, labelH=13; полный текст в DOM; failures=[] |
| py tools/ui_mod_acl_m4a_w2c_e2e.py | **viewports=6, failures=0**; 21 карточка; 4/4/3/2/1/1; heights 162/162/162/132-146-162/132-146-162/132-146-162; parent chips 16 px на desktop и 44 px на 768/390/320; split 1024/1152/1199 stack, 1200/1680 8/4; horizontal overflow 0; JS pageerror 0 |
| py tools/ui_mod_acl_m4_catalog_e2e.py | **M4A-CATALOG-E2E OK / failures=0** (13 проверок: высоты, 409, badge, D2 labels, denied, touch 44) |
| Node 7 файлов | **0 fail**: M3 235, M4 catalog 207, params 64, review 75, W2a 141, W2b 356, W2c **84** |
| Affected Python (6 nodeids) | воспроизведены те же 6 падений: nav_disclosure_ui 2, round1020_ui 3, f5_round1025 1; причины — устаревшие структурные assert'ы (var MODULES = [, setModuleScopeState, NAV_ITEMS, m.routeSlug, старый label); app.js этим фиксом не менялся |
| Affected Python, 13-файловый webapp-набор | **304 passed / 6 failed** (тот же набор 6); это не исторические 218/6 — состав исходного батча в evidence не записан, см. §7 |

## 4. Мутация (фальсификация)

В candidate worktree временно удалена строка white-space: nowrap; overflow: hidden; text-overflow: ellipsis; **только** из блока .module-card .module-title; затем git checkout -- web/static/app.css, хеш сверен.

| Мутация | Результат |
|---|---|
| clamp удалён | **KILLED**: failures=24 (4 карточки × height+title × 3 viewport), 179.56, titleH=35 на 1680/1440/320; после восстановления app.css = 7a45bff0… == HEAD |

Это независимо подтверждает, что 132–164 достигается именно clamp'ом, а не ослаблением ассерта: сам height-ассерт остался прежним.

## 5. UI/UX — оба слоя

**Playwright (детерминированно):** long-content harness и W2c 6 viewport — результаты выше. Дополнительно собственным probe измерены titleScrollW > titleClientW (ellipsis реально работает) и metaRight < cardRight (нет выезда за карточку) на 1680/1440/320.

**Browser Use (реальный Chrome, тот же web/index.html; API-стабы локального стенда):**
- 1680, 1440, 320; chat scope; длинные заголовки/описания.
- Все 4 карточки и mod_vision: **160.76 px**, titleH=17.5, scrollWidth > clientWidth для длинных заголовков, :title равен полному тексту, white-space: normal у chat-label, document.documentElement.scrollWidth == innerWidth (overflow 0).
- Визуально: однострочные заголовки с ellipsis, полные подписи действий, описания 2 строки, контролы/«Открыть» доступны, горизонтального клиппинга и наложений нет.
- Скриншоты: WorkspaceData/runs/c742e4de9e92c489/mod-acl-ux-01-1e46be007668/probe-7c471c7457/media-shots/browseruse-{1680,1440,320}.png; полный JSON — media-probe.json.
- Ограничение: консоль/сеть Browser Use отдельно не логировались; JS-ошибки проверялись Playwright-харнессом (0).

## 6. Соседние поверхности

- **W2a/W2b:** node 141/356 — 0 fail; правки не затрагивают их CSS/разметку.
- **Parent chips / split / touch:** W2c 6 viewport 0 fail; чипы 44 px на 768/390/320, split 1024/1152/1199 stack, 1200/1680 8/4, overflow 0.
- **Badges/glass:** M4A e2e 0 fail по badge/409/D2/mobile; glass-токены и .module-effective-inline не в diff; визуальный проход не показал регрессий.
- **D2:** подписи не обрезаны (white-space: normal), M4A D2-проверка прошла; clamp только заголовка.
- **Безопасность/данные:** только CSS/HTML-атрибут; новых API/DDL/флагов/промптов/хранилищ нет; :title Vue-экранируется, XSS-вставки нет.

## 7. Findings и ограничения

**Блокирующих продуктовых дефектов нет.** Найдено non-blocking:

- **EVID-1 (BACKLOG_ONLY, доказательство).** Закоммиченные card-height-*.png сняты в начале страницы и **не показывают** медиа-ряд с изменёнными карточками; green.json/red.json — основное доказательство. Мои независимые скриншоты медиа-ряда лежат в run-каталоге. В следующем прогоне — прокрутить к mod_transcribe перед screenshot.
- **TEST-1 (BACKLOG_ONLY, покрытие).** Новый node-ассерт проверяет CSS-clamp, но **не** проверяет :title; харнесс читает textContent, а не атрибут. Продукт проверен собственным probe; тестовую проверку атрибута добавить отдельно, не блокирует.
- **EVID-2 (BACKLOG_ONLY, гигиена).** Исторический набор «affected Python 13 файлов / 218 passed» не имеет записанного состава; точные 218 не воспроизведены. Воспроизведены 6 падающих nodeids и отсутствие новых падений. Записать command/файлы в evidence.
- **UX-1 (RESIDUAL, не дефект).** На touch полный длинный заголовок доступен через открытие карточки/workspace, не по hover; дизайн (§4.1, line 925) прямо допускает title/раскрытие. Не блокирует.

Ограничения ревью:

- Нет production/SSH/deploy/live TMA и нет deployed-byte прогона; production Linux font metrics локально не воспроизведены. Поэтому 2.58.222 postdeploy обязан повторить W2c/M4A и Browser Use на реальном checkout.
- Синтетические длинные заголовки — воспроизводят тот же дефект (179.56 / +17.5 px), но не являются реальным production-контентом; сам clamp не зависит от текста.
- red.log/green.log и red-shots из analysis.md лежат в run-каталоге, не в коммите; в коммите только red.json/green.json и три верхних скриншота.
- Полного повторного ревью W2c и всех соседних строк нет — только затронутый участок и риски; W2c-строки остаются **REVIEW**, VERIFIED не заявляется.
- Run-каталог WorkspaceData/runs/c742e4de9e92c489/mod-acl-ux-01-1e46be007668/probe-7c471c7457 — owned probe этой ревизии; серверы 8824/8825 остановлены, вкладки Browser Use закрыты; каталог подлежит unit-close после приёмки ревью.

## Verdict

**APPROVED FOR RELEASE PREPARATION.** Продуктовый diff ровно 2 web-файла (+6/−1), без app.js/backend/API/DDL/flags/prompts/storage и без bump; clamp однострочный, :title сохраняет полный текст, D2 не затронут. Независимо: long-content 0 failures / 162.06, W2c 6 viewport 0, M4A 0, node 7/0, мутация удаления clamp убивает контракт (24/179.56), реальный Chrome 1680/1440/320 — 160.76, ellipsis и полный :title.

**Next:** Builder/PM merge или cherry-pick 809550008 (+ test/tool) в release-линию, cut **2.58.222**, deploy; затем deployed-byte W2c/M4A + Browser Use на медиа-ряду. VERIFIED — только после этого; текущий вердикт его не заменяет.
