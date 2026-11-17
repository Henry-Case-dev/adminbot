# Release 2.58.212 — MOD-ACL-UX-01 M4A W2b B1 (сборка, REVIEW)

| Поле | Значение |
|---|---|
| Дата сборки | 2026-11-17 |
| Ветка | `release/mod-acl-w2b-2.58.212` |
| База (предыдущий релиз / откат) | `9de44231cd773951fb53670bf94cb626ffd7c1bb` (2.58.211) |
| Approved candidate | `71d055fc130aedd38369f5f8f20e44c0c355cad5` (W2b B1, Reviewer: **Approved for 2.58.212 release preparation**) |
| Candidate commits | `fae3eab2`, `b5e22245`, `18ced316`, `71d055fc` (только W2b B1/тесты/evidence) |
| Content tip (bump) | `f7e61eb05b448c92a30f316dedc7fb96c4767062` |
| Версия | 2.58.212 |
| Статус | **REVIEW** (не деплой, не VERIFIED) |
| Деплой | не выполнялся; production не затронут |

## Состав

| Блок | Файлов | Строк |
|---|---|---|
| W2b B1 candidate (`9de44231..71d055fc`) | 9 | +1924 / -42 |
| Bump 2.58.211→2.58.212 (`71d055fc..f7e61eb0`) | 30 | +31 / -31 |
| **Итого от базы** (`9de44231..f7e61eb0`) | **39** | **+1955 / -73** |

W2b B1-файлы: `web/app.js`, `web/index.html`, `web/static/app.css`,
`tests/js/mod_acl_ux_m4a_w2b_history_test.js`,
`tests/js/mod_acl_ux_m4a_w2a_tabs_freshness_test.js`,
`tools/ui_mod_acl_m4_catalog_e2e.py`, три evidence-файла `evidence/m4a/w2b/`.
Продуктовых файлов сверх W2b B1 и bump нет; `services/`, `web/api/`,
`database/`, `deploy_v2.9.2.py` не изменялись.

## Bump (30 файлов / 31 строка)

- `config/settings.py`: `APP_VERSION = "2.58.212"` + changelog
  «Prior 2.58.211» (BOM/CRLF сохранены, единственная LF-строка APP_VERSION
  осталась LF).
- `plans/docs/param-registry-round1025.meta.md`: APP_VERSION.
- 24 py-пина + 4 JS-пина в escaped-форме `2\.58\.212` (29 замен в 28 файлах;
  `test_webapp_round1026_polygon.py` содержит 2 пина).
- Инварианты: каталог параметров **645 / 121 / 119 / 22**, Settings **472**,
  миграции **47/47**, DDL **0**; новых флагов, миграций, composer, промптов,
  моделей, агентов и эндпоинтов нет; `deploy_v2.9.2.py` не изменялся.

## Гейты (фактические прогоны, cwd = release worktree, content tip)

| Гейт | Результат |
|---|---|
| Обязательный pytest (M4A/M2/M2.1 + f8 + mca23 + webapp JS unit), 24 файла | **386 passed, 0 failed** |
| 24 bumped py-файла (пины) | 856 passed, **4 failed** — те же pre-existing epic-scope guards, воспроизведены на базе |
| W2b B1 node-юнит | **126 проверок OK** |
| W2a node-юнит | **141 проверка OK** |
| `routing_test.js` | **JS-UNIT-OK** |
| W11/W12 guard-тесты | **2 passed** |
| Полный `tests/js/*.js` | **117 passed**, те же 4 pre-existing fail |
| Playwright e2e, 5 viewport | **failures=0**, 5 viewports, 63 flows |
| W2b computed sizes (1280/390) | row **12px**, title **14px**, filter **12px** на обеих поверхностях |
| `node --check web/app.js` | rc 0 |
| `git diff --check 9de44231..f7e61eb0` | rc 0 |
| `tests/test_webapp_*.py` (64 файла) | 33 failed / 1455 passed — **те же 33 pre-existing**, новых нет |

## Manifest (dry-run на чистом дереве content tip)

`python tools/release_manifest.py --dry-run` при реконструированном
документированном состоянии прода 2.58.211 (deployed
`9de44231cd773951fb53670bf94cb626ffd7c1bb`, previous manifest branch
`release/mod-acl-w2a-2.58.211`; production не читался):

version **2.58.212**, deployed_sha **f7e61eb05b448c92a30f316dedc7fb96c4767062**,
previous_sha **9de44231cd773951fb53670bf94cb626ffd7c1bb**, previous_version
2.58.211, release_branch **release/mod-acl-w2b-2.58.212**, dirty_tracked
**false**, effect deploy, schema 1. `.deploy` создан только для реконструкции
и удалён после прогона; дерево чистое до и после. Полный JSON —
`manifest-dry-run.json`.

## Откат

Цель `9de44231cd773951fb53670bf94cb626ffd7c1bb` (2.58.211), схема 47, DDL 0,
данные/настройки не меняются; состояние истории — in-memory/client-side
(`historyMeta` в JS и id вкладки в localStorage), серверных данных для отката
нет. См. `rollback.json`.

## Evidence

- `assembly.md` (этот файл), `tests-2.58.212.json`,
  `manifest-dry-run.json`, `rollback.json`, `limitations.md`;
- W2b RED/мутации/F1-F4/F1-B: `evidence/m4a/w2b/`
  (`red-9de44231.txt`, `fix-review-f1-f4-red-fae3eab2.txt`,
  `fix-review-f1b-red-18ced316.txt`);
- W2a baseline evidence: `evidence/release-2.58.211/`.

## Что этот релиз не делает

Не деплоит, не заявляет VERIFIED, не включает B2/B3/W2c/W3, не расширяет scope
на factcheck/experience/oversight history, не меняет backend/ACL/storage.
