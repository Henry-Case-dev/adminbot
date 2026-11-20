# MOD-ACL-UX-01 M4A W2c — navigation/layout/wireframe (candidate)

| Поле | Значение |
|---|---|
| Дата | 2026-11-20 11:55 +12:00 |
| Base / rollback | `d03027b1bc3811a0614c5a2e38342eb9e77c4ea5` — production 2.58.220 (content `8e05e9a4`, schema 48, DDL 0) |
| Branch | `release/mod-acl-w2c-2.58.221` (без bump `APP_VERSION`; target 2.58.221 собирается позже) |
| Строки | `MAC-S5-NAV-01`, `MAC-S5-LAY-01`, `MAC-S5-WF-01` |
| Write scope | `web/app.js`, `web/index.html`, `web/static/app.css`; тесты/e2e/evidence |
| Backend/API/DDL/flags/prompts/storage | не изменялись |

## R2 — исправление трёх review blockers (2026-11-20)

1. **F1 test regression.** `_memoryGroups`, `memorySubgroupChips` и
   `_permsocOwnerGroups` вызывают `submoduleOwnedGroups` только через
   `typeof … === 'function'`; урезанные юнит-контексты
   `round1025_f7_permsoc_local_test.js` и `routing_test.js` снова зелёные,
   production-контракт фильтрации не изменён.
2. **F2 touch.** Анкер `.module-catalog .module-parent-chip` на
   `max-width:1199px`/coarse получает `min-height:44px` и прозрачные
   `padding-block:14px; margin-block:-14px`; визуальная пилюля остаётся 16 px,
   карточки держат 132–164. Playwright: чипы 44 px на 768/390/320, overflow 0.
3. **F3 layout.** Коллапс `.workspace-split` перенесён на `max-width:1199px`;
   на 1024/1152/1199 блоки стоят друг под другом, на 1200/1680 — 8/4
   (main/side 629/307 и 949/467).

## Что реализовано

- **NAV-01.** `parent_id` DTO → чип-ссылка владельца у 4 подмодулей:
  `stories/experience/random` → `Часть «Памяти»` → `#/memory/rag`;
  `character` → `Часть «PERMsoc»` → `#/permsoc`. Чип есть на карточке каталога
  и в шапке страницы модуля; клик по чипу карточки не открывает саму карточку.
  На `#/memory/rag`/`#/permsoc` группы подмодулей больше не выводятся вторым
  набором полей — строка `Настраивается в «<Модуль>» →` с прямым deep link.
  Ссылки «Обзора» стали реальными `<a href="#/modules/<slug>/<tab>">` (открытие
  в новой вкладке), при клике сохраняется прежняя запись памяти вкладки.
- **LAY-01.** Desktop sidebar 216 px (диапазон 190–220). Сложный и
  инфраструктурный модуль — рабочая область до 1440 px (на 1680 фактически
  1432); малый/`maintenance` — простая колонка 900–1000 px (на 1440/1280/1680
  фактически 1000). `8/12 + 4/12` — только явный opt-in wrapper на
  `mod_direct/models`, где уже есть два независимых sibling-блока (стадии и
  L1-сводка); на остальных страницах wrapper отсутствует. Tablet/mobile — одна
  колонка; touch-цели ≥44 px (включая `tech-key`, tabs, tri-state, inputs,
  summary); горизонтального overflow нет (320/390/768/1280/1440/1680).
- **WF-01.** Одна шапка модуля (одна `[data-workspace-head]`, один H1);
  «Обзор» сложного модуля — 5 реальных событий; классы
  complex/small/infrastructure/maintenance размечены в DOM; подписи зоны
  «Расширенные» нормализованы в `Расширенные системные (N)`.

## Доказательства

- RED на base: `red-node-d03027b1b.txt` (падение нового node-теста до правки).
- Node: `node-tests-candidate.txt` — **9 файлов, 0 fail**:
  M3 routes 235, M4 catalog 207, module params 64, review fixes 75,
  W2a 141, W2b 356, W2c **83** проверки, F7 PERMsoc-local и routing_test.
- Playwright W2c: `e2e-w2c.json` / `e2e-w2c-summary.txt` — **6 viewport
  (1680/1440/1280/768/390/320), 0 failures**: 21 карточка, 4/3/2/1,
  parent-чипы и deep links, owner-ссылки, 8/4 пропорции (~2:1), ширины
  1432/1000, touch 0 нарушений, overflow 0, JS-ошибок 0. Дополнительно
  split-проверки на 1024/1152/1199 (одна колонка) и 1200/1680 (8/4);
  catalog parent-чипы 44 px на 768/390/320.
- Broad JS sweep: `broad-js-candidate.txt` — **124 теста, 4 fail**;
  `broad-js-base.txt` — **123 теста, те же 4 fail** (`asap6_wave2_ux_tabs`,
  `evol_cog_scene`, `round1025_ia_routing`, `ur_ui_settings`) — новых
  падений 0; два F1-теста зелёные.
- Регресс существующего M4A e2e: `regression-e2e-summary.txt` —
  `M4A-CATALOG-E2E OK | failures=0` (W2a/W2b сценарии).
- Python affected suite: `python-tests-candidate.txt` — **218 passed, 6 failed**;
  те же 6 падают на base (`python-preexisting-base.txt`) — это устаревшие
  ожидания (`test_webapp_round1020_ui`, `test_webapp_f5_round1025`,
  `test_webapp_nav_disclosure_ui`), не регресс W2c. Две проверки подписи
  «Расширенные» в `test_webapp_nav_disclosure_ui.py`/`test_webapp_round1011_ui.py`
  обновлены под контракт WF-01; они зелёные.
- `tools/ui_cmv_perf_parity.py` (threshold 12/1.5%): `visual-parity-cmv.json`
  (base vs candidate) и `visual-parity-cmv-base2.json` (base vs base-повтор).
  Инструмент на сцене cognition map нестабилен: base-vs-base даёт те же
  `fails=6` и близкие проценты, поэтому candidate нельзя отличить от шума.
  Это ограничение инструмента, не доказательство регресса.
- Целевой diff тех же поверхностей: `visual-parity-surfaces.json` —
  каталог **0.318 % / 0.000 % (ok)**, summary 1440 **0.000 % (ok)**;
  изменения на 4.9–31.9 % относятся ровно к заявленным W2c-поверхностям
  (ширина малых вкладок, 8/4, owner-ссылки, touch-размеры).
- Browser Use (реальный Brave, CDP): open `#/modules` — 21 карточка, 4
  parent-чипа; `#/modules/experience` — `Часть «Памяти»` → `#/memory/rag`;
  `#/modules/direct/models` — split 2 children, main 779 / side 382;
  `#/permsoc` — `Настраивается в «Характер» →`; `#/modules/nostalgia/settings`
  — ширина 1000. Скриншоты: `browseruse/catalog-1440.png`,
  `experience-1440.png`, `direct-models-1440.png`, `permsoc-1440.png`,
  `nostalgia-1440.png` (путь в общем run-артефакте; ниже).
- Playwright-скриншоты (8 ключевых, коммитятся): `shots/` (включая
  `catalog-memory-390.png`, `split-1024.png`, `split-1200.png`).
  Полный набор 6 viewport — в
  `C:\Users\main\.config\opencode\WorkspaceData\runs\e31efba8c3a07ef5\mod-acl-ux-01-w2c-1c42e502b218\artifact-017df521dc\shots-r2`.

## Ограничения

- `APP_VERSION` не bump; карта/`workflow_state` не менялись; deploy не
  выполнялся; строки остаются PENDING/REVIEW до независимого Reviewer и
  выката на точный SHA.
- Cognition-map parity tool нестабилен (см. выше); для W2c использованы
  целевой diff, измерения пропорций и Browser Use.
- Python pre-existing 6 failures не относятся к W2c и воспроизводятся на base;
  отдельный backlog-fix не входит в эту ветку.
