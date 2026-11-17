# Release 2.58.213 — MOD-ACL-UX-01 M4A W2b B2 (сборка, REVIEW)

| Поле | Значение |
|---|---|
| Дата сборки | 2026-11-17 |
| Ветка | `release/mod-acl-w2b2-2.58.213` |
| База (предыдущий релиз / откат) | `e070c229bfdafcc9b07115ad55fba8dde2e8cffb` (2.58.212) |
| Approved candidate | `7441fd8facb282e8b1c2117ee9307268a119545a` (W2b B2; Reviewer: **Approved for 2.58.213 release preparation**, затем дельта-ревью Needs Fixes F1) |
| Fix commit (F1/F2/F3/F4) | `a2f92b7d97310c66a1786556c2794c5386887e89` |
| Content tip | `a2f92b7d97310c66a1786556c2794c5386887e89` |
| Bump commit | `86d39a48151d1a881c00516fced3aec56d39172f` |
| Версия | 2.58.213 (bump не менялся) |
| Статус | **REVIEW** (не деплой, не VERIFIED) |
| Деплой | не выполнялся; production не затронут |

## Состав

| Блок | Файлов | Строк |
|---|---|---|
| W2b B2 candidate (`e070c229..7441fd8f`) | 6 | +1492 / -103 |
| Bump 2.58.212→2.58.213 (`7441fd8f..86d39a48`) | 30 | +31 / -31 |
| Release evidence (`86d39a48..fc4e9a7c`) | 5 | +475 |
| F1/F2/F3/F4 fix (`fc4e9a7c..a2f92b7d`) | 5 | +369 / -14 |
| **Итого от базы до content tip** (`e070c229..a2f92b7d`) | **41** | **+2355 / -136** |

Продуктовый diff fix-коммита: `web/app.js` (scope-aware кэш + epoch-guard
`loadTemporalRuns`/`loadLessons`, row-level `historyRowCanDetail`),
`web/index.html` (кнопка «Детали» только при `run_id`); тесты и e2e —
`tests/js/mod_acl_ux_m4a_w2b_history_test.js`,
`tools/ui_mod_acl_m4_catalog_e2e.py`; `limitations.md` (F2/F3/F4).
`web/static/app.css` не изменялся (использованы существующие
`.module-history*`). Продуктовых файлов сверх B2/B2-fix/bump нет;
`services/`, `web/api/`, `database/`, `deploy_v2.9.2.py`,
`module_registry.py`, ACL, prompt registry, storage и `WS_OVERVIEW_LIVE`
не изменялись. Версия/пины остались 2.58.213.

## Содержание B2 (H-1…H-7) и F1

- `factcheck.temporal.runs` → существующий
  `GET /api/factcheck/temporal/runs?limit=20` (`{runs}`), детали —
  существующая модалка `openTemporalDetail(run_id)` только при наличии id
  (row-level guard, F2).
- `memory.lessons` → существующий `GET /api/memory/lessons` (конверт
  `{enabled,state,count,lessons}`); строка «уроков: N / state», фильтр по
  статусу урока, `updated_at`/`created_at`, `scope`/`scope_chat_id`.
- Вкладка «История» объявлена у `mod_factcheck`/`mod_experience`, рендерится
  только при `ready && rows > 0`; `403 → denied`, `503/available:false/
  enabled:false → off`, сеть/битый конверт `→ error`, пустой источник
  `→ empty`; неизвестный `history_source` — ни запроса, ни вкладки.
- «Обзор»: один блок «Сейчас» + 3–5 событий своего источника без дублей;
  второй список журнала Фактчека удалён, `data-factcheck-temporal` сохранён
  как адрес блока (MCA-20/B07). `observed_at` не выдаётся за активность.
- Deep link `#/modules/<slug>/history`: панель загрузки, при
  `empty/denied/off` однократный переход на bare без цикла (в т.ч. для
  не-владельца — `denied` без запроса).
- Один существующий лоадер на источник, без нового поллера; вкладка и
  простой не добавляют запросов.
- **F1 (cross-scope):** 30-с кэш `temporalRuns` помечен `{scopeKey, epoch}` и
  используется только в своей области; `loadTemporalRuns`/`loadLessons`
  фиксируют `scopeEpoch` до запроса и отбрасывают поздний ответ другой
  области (then/catch/finally), не перезаписывая `temporalRuns`/
  `lessonsData`/мету текущего ключа. Область B не получает строк/`ready`/
  `empty` области A без своего запроса.

## Bump (30 файлов / 31 строка)

- `config/settings.py`: `APP_VERSION = "2.58.213"` + changelog
  «Prior 2.58.212» (BOM/CRLF сохранены; строка APP_VERSION остаётся LF, как
  в базе).
- `plans/docs/param-registry-round1025.meta.md`: APP_VERSION.
- 24 py-пина + 4 JS-пина в escaped-форме `2\.58\.213` (30 замен в 29 файлах;
  `test_webapp_round1026_polygon.py` содержит 2 пина). Набор файлов —
  фактический набор bump-коммита `f7e61eb0` (2.58.212), применён
  2.58.212→2.58.213.
- Инварианты: каталог параметров **645 / 121 / 119 / 22**, Settings **472**,
  миграции **47/47**, DDL **0**; новых флагов, миграций, composer, промптов,
  моделей, агентов и эндпоинтов нет; `deploy_v2.9.2.py` не изменялся.

## Гейты (фактические прогоны, cwd = release worktree, content tip)

| Гейт | Результат |
|---|---|
| Обязательный pytest (M4A/M2/M2.1 + f8 + mca23 + webapp JS unit), 24 файла | **386 passed, 0 failed** |
| 24 bumped py-файла (пины) | **856 passed, 4 failed** — те же pre-existing epic-scope guards |
| W2b node-юнит (B1+B2+F1) | **237 проверок OK** |
| W2a node-юнит | **141 проверка OK** |
| `routing_test.js` | **JS-UNIT-OK** |
| W11/W12 guard-тесты | **2 passed** |
| `tests/test_webapp_*.py` (64 файла) | 33 failed / 1455 passed — **те же 33 pre-existing**, новых нет |
| Полный `tests/js/*.js` (121, без fixture) | **117 passed**, те же 4 pre-existing fail |
| Playwright e2e, 5 viewport | **failures=0**, 5 viewports, 93 flows (30 B2) |
| B2 e2e факты | factcheck: Обзор 5 строк/1 блок, История 6 строк/6 ключей; experience: Обзор 3/1, История 4 строки, «уроков: 4 / implemented»; detail по `run_id` = 1 запрос; 403/503/available:false/enabled:false → нет вкладки; deep link → bare; один ряд чипов; 390: 6/4 строк, scrollWidth 390 |
| F1 e2e (cross-scope) | 1280 и 390, factcheck и experience: A→B→A (390-back добавлен e2e-only после content tip), строки только своей области (`A-run`/`B-run`, `A-lesson@1`/`B-lesson@1`), по 1 своему запросу на область, `scrollWidth=vw`, строки 12px; factcheck-perchat — синтетический стаб по `X-Chat-Id` (реальный per-chat кейс — `memory.lessons`, `?chat_id=`) |
| `node --check web/app.js` | rc 0 |
| `git diff --check e070c229..a2f92b7d` | rc 0 |

## Manifest (dry-run на чистом дереве content tip)

`python tools/release_manifest.py --dry-run` при реконструированном
документированном состоянии прода 2.58.212 (deployed
`e070c229bfdafcc9b07115ad55fba8dde2e8cffb`, previous manifest branch
`release/mod-acl-w2b-2.58.212`; production не читался):

version **2.58.213**, deployed_sha **a2f92b7d97310c66a1786556c2794c5386887e89**,
previous_sha **e070c229bfdafcc9b07115ad55fba8dde2e8cffb**, previous_version
2.58.212, release_branch **release/mod-acl-w2b2-2.58.213**, dirty_tracked
**false**, effect deploy, schema 1. `.deploy` создан только для реконструкции
и удалён после прогона; дерево чистое до и после. Полный JSON —
`manifest-dry-run.json`. Последующие e2e/docs-only правки (390-back,
формулировки) продукт/версию не меняют — `deployed_sha` остаётся `a2f92b7d`.

## Откат

Цель `e070c229bfdafcc9b07115ad55fba8dde2e8cffb` (2.58.212), схема 47,
DDL 0, данные/настройки не меняются; состояние истории —
in-memory/client-side (`historyMeta` в JS и id вкладки в localStorage),
серверных данных для отката нет. См. `rollback.json`.

## Evidence

- `assembly.md` (этот файл), `tests-2.58.213.json`,
  `manifest-dry-run.json`, `rollback.json`, `limitations.md`;
- W2b B2 RED/мутации и F1 RED: `evidence/m4a/w2b2/red-e070c229.txt`
  (F1 RED/мутации — в `tests-2.58.213.json`, раздел `f1_cross_scope`);
- W2b B1 baseline: `evidence/release-2.58.212/`;
- W2a baseline: `evidence/release-2.58.211/`.
- Product content tip — `a2f92b7d`; последующие docs/e2e-only правки
  (390-back проверка в `tools/ui_mod_acl_m4_catalog_e2e.py` и evidence)
  продукт/версию не меняют, `deployed_sha` манифеста остаётся `a2f92b7d`.

## Что этот релиз не делает

Не деплоит, не заявляет VERIFIED, не включает B3 (`oversight:summary.window`/
`oversight:random.uses`), W2c (NAV/LAY/WF), W3 (живые 403/503/stale/
disabled), M4B/M4C. `MAC-S5-TAB-01`, `MAC-S5-TAB-06`, `MAC-S5-EMPTY-01`,
`MAC-AC-07` закрываются только после B3.
