# Release 2.58.214 — MOD-ACL-UX-01 M4A W2b B3 (сборка, REVIEW)

| Поле | Значение |
|---|---|
| Дата сборки | 2026-11-17 |
| Ветка | `release/mod-acl-w2b3-2.58.214` |
| База (предыдущий релиз / откат) | `34c25d0949f3d29edd6f8230fa27913608719526` (2.58.213) |
| Approved candidate | `283fc89ae1cc9f9bb7327c38323c9359d2286ccf` (W2b B3; Reviewer: **Approved for 2.58.214 release preparation**) |
| Content tip | `2b57443ad0b08195c07822a0c2c5b7eb13ee5d71` |
| Bump commit | `2b57443ad0b08195c07822a0c2c5b7eb13ee5d71` |
| Версия | 2.58.214 |
| Статус | **REVIEW** (не деплой, не VERIFIED) |
| Деплой | не выполнялся; production не затронут |

## Состав

| Блок | Файлов | Строк |
|---|---|---|
| W2b B3 candidate (`34c25d09..283fc89a`) | 6 | +1360 / -33 |
| Bump 2.58.213→2.58.214 (`283fc89a..2b57443a`) | 30 | +31 / -31 |
| Release evidence (`2b57443a..`) | 5 | см. коммит evidence |
| **Итого от базы до content tip** (`34c25d09..2b57443a`) | **36** | **+1391 / -64** |

Продуктовый diff: `web/app.js` (+228/-7 — presentation-map `oversight:*`,
`loadModuleRuns` с 30-с кэшем scope+epoch, `historyRowDetailHref`, ветки
представления прогона, `_ensureModuleData`/`_ensureHistoryForWorkspace`/
`refreshHistory`), `web/index.html` (+21/-5 — `data-summary-runs`/
`data-random-runs`, ссылка детали по `run_id`, обобщённое условие
«Обзор»-блока), `config/settings.py` (только APP_VERSION + changelog
bump-коммита). Тесты/стенд: `tests/js/mod_acl_ux_m4a_w2b_history_test.js`,
`tests/js/round1025_f5_workspace_route_test.js`,
`tools/ui_mod_acl_m4_catalog_e2e.py`.

Продуктовых файлов сверх B3/bump нет: `services/`, `web/api/`,
`services/module_registry.py`, ACL, prompt registry, `param_catalog`,
M2.1-адаптеры, storage, `web/static/app.css`, `WS_OVERVIEW_LIVE` и
`deploy_v2.9.2.py` не изменялись (`git diff --name-only` по этим путям пуст).

## Содержание B3 (H-1…H-7)

- `oversight:summary.window` / `oversight:random.uses` → существующий
  `GET /api/oversight/runs?pipeline_type=…&limit=20` (global admin,
  `global:true` без `X-Chat-Id`), `rows=runs`, `ts=started_ts`,
  ключ строки `pipeline_run_id`.
- `WORKSPACE_TABS`: `history` у `mod_summary`; собственная карта
  `mod_random: ['overview','settings','history']`; подпись `history:
  'История'` уже существует. Вкладка рендерится только при
  `ready && rows > 0`.
- `loadModuleRuns(source, force)` — один тонкий лоадер на источник:
  30-с кэш помечен `{scopeKey, epoch}`, поздний ответ чужой области
  отбрасывается epoch-guard'ом (then/catch/finally), полёт привязан к
  своей области, строки источников не смешиваются (`moduleRuns[source]`).
- Честные состояния: `403 → denied`, `503 / available:false / enabled:false
  → off` (off проверяется ДО массива: серверный disabled отдаёт и пустой
  `runs`), сеть/битый конверт `→ error`, `runs: [] → empty`; неизвестный
  `history_source` — ни запроса, ни вкладки; не-владелец — `denied` без
  запроса.
- Деталь строки — существующий deep link
  `#/oversight?view=runs&run_id=` (парсер `oversightParseDeepLink`,
  `oversightOpenRun`); без `pipeline_run_id` ссылки нет. Модалка фактчека
  (`data-temporal-run-btn`) сохранена через `v-else-if`.
- «Обзор»: «Сейчас» + до 5 событий своего журнала без дубля строки
  «Сейчас», один ряд чипов, адреса `data-summary-runs` / `data-random-runs`.
- Deep link `#/modules/<slug>/history` при `empty/denied/off` однократно
  уводит на bare; `history` никогда не дефолт; pending не стирает память
  вкладок (H-4); `observed_at` активностью не становится.

## Bump (30 файлов / 31 строка)

- `config/settings.py`: `APP_VERSION = "2.58.214"` + changelog
  «Prior 2.58.213» (BOM и CRLF сохранены: 3638 CRLF до и после).
- `plans/docs/param-registry-round1025.meta.md`: APP_VERSION.
- 24 py-пина + 4 JS-пина в escaped-форме `2\.58\.214` (30 замен в 29
  файлах; `test_webapp_round1026_polygon.py` содержит 2 пина). Набор файлов —
  тот же, что в bump-коммите 2.58.213 (`86d39a48`).
- Инварианты измерены на content tip: APP_VERSION **2.58.214**, каталог
  параметров **645 / 121 / 119 / 22**, Settings **472**, миграции
  **47 / max 47**, DDL **0**; новых флагов, миграций, composer, промптов,
  моделей, агентов, эндпоинтов и планировщиков нет; `pg_settings` не
  тронуты; `deploy_v2.9.2.py` не изменялся.

## Гейты (фактические прогоны, cwd = release worktree, content tip)

| Гейт | Результат |
|---|---|
| Обязательный pytest (M4A/M2/M2.1 + f8 + mca23 + webapp JS unit), 24 файла | **386 passed, 0 failed** |
| W2b node-юнит (B1+B2+B3) | **348 проверок OK** |
| W2a node-юнит | **141 проверка OK** |
| `routing_test.js` | **JS-UNIT-OK** |
| `round1025_f5_workspace_route_test.js` | **MODULE-WORKSPACE-OK** (карты вкладок Саммари/Случайности обновлены под B3) |
| W11/W12 guard-тесты | **2 passed** |
| `tests/test_webapp_*.py` (64 файла) | 33 failed / 1455 passed — **те же 33 pre-existing** (тот же список node id воспроизведён на базе `34c25d09`), новых нет |
| Полный `tests/js/*.js` (121, без fixture) | **117 passed**, те же 4 pre-existing fail |
| Playwright e2e, 5 viewport | **failures=0**, rc 0, 5 viewports (1440/1280/768/390/320), **113 flows** (20 B3), 0 pageerrors |
| `node --check web/app.js` | rc 0 |
| `git diff --check 34c25d09..2b57443a` | rc 0 |

### B3 e2e-факты (1280×800 и 390×844)

- summary: bare URL → активная вкладка `settings` (history **не** дефолт);
  `/overview` → 1 блок `data-summary-runs`, «Сейчас» + 5 событий, 5 ссылок
  деталей, первая ссылка `srun-2` (строка «Сейчас» не дублируется),
  один ряд чипов, дублей 0.
- summary/history → 6 строк (`srun-1…6`), 6 ссылок деталей, 5 опций
  фильтра, `failed` → 2 строки, сброс → 6.
- деталь: клик по ссылке → hash `#/oversight?view=runs&run_id=srun-1`,
  запрос `?run_id=` выполнен, панель истории с экрана ушла.
- random: `/overview` → 1 блок `data-random-runs`, 2 события + «Сейчас»;
  `/history` → 3 строки (`rrun-1…3`), строки сводок не подмешаны.
- состояния summary: `[] → empty`, `403 → denied`, `503 → off`,
  `available:false → off`; random `403 → denied` — вкладки нет, причина
  честная, «0 событий» не печатается.
- deep link `#/modules/summary/history` при `[]` → bare
  `#/modules/summary`, пустой панели нет.
- один фетч: **1 → 1 → 1** (открытие, клик по вкладке, простой) — поллера нет.
- A→B→A (1280 и 390): каждая область делает ровно 1 свой запрос, строки
  A (`srun-1`) и B (`srun-B`) не смешиваются, возврат в A показывает свои
  строки; 390: `scrollWidth=390`, строки 12px.

## Manifest (dry-run на чистом дереве content tip)

`python tools/release_manifest.py --dry-run` при реконструированном
документированном состоянии прода 2.58.213 (deployed `34c25d09…`,
previous manifest branch `release/mod-acl-w2b2-2.58.213`; production не
читался):

version **2.58.214**, deployed_sha **2b57443ad0b08195c07822a0c2c5b7eb13ee5d71**,
previous_sha **34c25d0949f3d29edd6f8230fa27913608719526**, previous_version
2.58.213, release_branch **release/mod-acl-w2b3-2.58.214**, dirty_tracked
**false**, effect deploy, schema 1. `.deploy` создан только для
реконструкции и удалён после прогона; дерево чистое до и после. Полный
JSON — `manifest-dry-run.json`. Dry-run снят на content tip `2b57443a`;
последующий evidence-коммит продукт/версию не меняет. Если production
выкатит более поздний docs/evidence-only коммит этой ветки, честный
deploy-time манифест запишет фактический checkout SHA (продуктовые байты
идентичны, отличается только evidence).

## Откат

Цель `34c25d0949f3d29edd6f8230fa27913608719526` (2.58.213), схема 47,
DDL 0, данные/настройки не меняются; состояние истории —
in-memory/client-side (`historyMeta`/`moduleRuns` в JS и id вкладки в
localStorage), серверных данных для отката нет. См. `rollback.json`.

## Evidence

- `assembly.md` (этот файл), `tests-2.58.214.json`,
  `manifest-dry-run.json`, `rollback.json`, `limitations.md`;
- W2b B3 RED/мутации: `evidence/m4a/w2b3/red-34c25d09.txt`;
- B2 baseline: `evidence/release-2.58.213/`; B1 — `release-2.58.212/`;
  W2a — `release-2.58.211/`.

## Что этот релиз не делает

Не деплоит, не заявляет VERIFIED, не включает W2c (NAV/LAY/WF) и W3
(живые 403/503/stale/disabled), M4B/M4C; не расширяет ACL и не добавляет
фильтр прогонов по чату (W2c/W3). Строки `MAC-S5-TAB-01`, `MAC-S5-TAB-06`,
`MAC-S5-EMPTY-01`, `MAC-AC-07` закрывает PM после review/deploy, не Builder.
