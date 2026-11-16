# Release 2.58.211 — MOD-ACL-UX-01 M4A W2a (сборка, REVIEW)

| Поле | Значение |
|---|---|
| Дата сборки | 2026-11-17 |
| Ветка | `release/mod-acl-w2a-2.58.211` |
| База (предыдущий релиз / откат) | `4f8d7007efc4e6546f390f5fef147e8fbd2e8f86` (2.58.210) |
| Approved candidate | `db7c16b56226d1b164e30806f1cbef2ed9b74507` (W2a, Reviewer: Approved for 2.58.211 release preparation) |
| Test-gap (review Low) | `f5168def3b479b66e9994651197fb0ff8075c565` — только тест, продукт не менялся |
| Content tip (bump) | `1e41afd559da04162c57112175e1cbd5a604fb03` |
| Версия | 2.58.211 |
| Статус | **REVIEW** (не деплой, не VERIFIED) |
| Деплой | не выполнялся; production не затронут |

## Состав

| Блок | Файлов | Строк |
|---|---|---|
| W2a candidate (`4f8d7007efc4e6546f390f5fef147e8fbd2e8f86..db7c16b56226d1b164e30806f1cbef2ed9b74507`) | 7 | +1379 / -27 |
| Test-gap (`db7c16b56226d1b164e30806f1cbef2ed9b74507..f5168def3b479b66e9994651197fb0ff8075c565`) | 1 | +72 / -0 |
| Bump 2.58.210→2.58.211 (`f5168def3b479b66e9994651197fb0ff8075c565..1e41afd559da04162c57112175e1cbd5a604fb03`) | 30 | +31 / -31 |
| **Итого от базы** (`4f8d7007efc4e6546f390f5fef147e8fbd2e8f86..1e41afd559da04162c57112175e1cbd5a604fb03`) | **37** | **+1482 / -58** |

W2a-файлы: `web/app.js`, `web/index.html`, `web/static/app.css`,
`tests/js/mod_acl_ux_m4a_w2a_tabs_freshness_test.js`,
`tests/js/round1025_f5_workspace_route_test.js`,
`tests/js/mod_acl_ux_m4_module_params_test.js`,
`tools/ui_mod_acl_m4_catalog_e2e.py`. Продуктовых файлов сверх W2a и bump нет.

## Bump (30 файлов / 31 строка)

- `config/settings.py`: `APP_VERSION = "2.58.211"` + changelog с
  «Prior 2.58.210» (BOM/CRLF сохранены, единственная LF-строка APP_VERSION
  осталась LF).
- `plans/docs/param-registry-round1025.meta.md`: APP_VERSION.
- 24 py-пина + 4 JS-пина в escaped-форме `2\.58\.211`.
- Инварианты: каталог параметров **645 / 121 / 119 / 22**, Settings **472**,
  миграции **47/47**, DDL **0**; новых флагов, миграций, composer, промптов,
  моделей, агентов и эндпоинтов нет; `deploy_v2.9.2.py` не изменялся.

## Гейты (фактические прогоны, cwd = release worktree)

| Гейт | Результат |
|---|---|
| Обязательный pytest (M4A/M2/M2.1 + f8 + mca23 + webapp JS unit), 24 файла | **386 passed, 0 failed** |
| 24 bumped py-файла (пины) | 856 passed, **4 failed** — те же pre-existing epic-scope guards, воспроизведены на `4f8d7007` |
| W2a node-юнит | **138 проверок OK** |
| `round1025_f5_workspace_route_test.js` (route + test-gap b4) | **MODULE-WORKSPACE-OK** |
| `mod_acl_ux_m4_module_params_test.js` | **64 проверки OK** |
| `mod_acl_ux_m4_catalog_test.js` | **207 проверок OK** |
| Полный `tests/js/*.js` (121 файл) | те же **4 pre-existing fail**: `asap6_wave2_ux_tabs`, `evol_cog_scene`, `round1025_ia_routing`, `ur_ui_settings` |
| Playwright e2e, 5 viewport | **failures=0**, flows=43 |
| `node --check web/app.js` | rc 0 |
| `git diff --check 4f8d7007..1e41afd5` | rc 0 |

Test-gap дискриминационность: удаление записи памяти в валидной ветке
`applyRoute` валит блок (b4) — проверено временной мутацией, продукт откатан
(`git status` clean).

## Manifest (dry-run на чистом дереве content tip)

`python tools/release_manifest.py --dry-run` при реконструированном
документированном состоянии прода 2.58.210 (deployed `4f8d7007efc4e6546f390f5fef147e8fbd2e8f86`, previous
`37f6c76f`, branch `release/mod-acl-m4a-2.58.210`; production не читался):
version **2.58.211**, deployed_sha **1e41afd559da04162c57112175e1cbd5a604fb03**, previous_sha **4f8d7007efc4e6546f390f5fef147e8fbd2e8f86**,
previous_version 2.58.210, release_branch **release/mod-acl-w2a-2.58.211**,
dirty_tracked **false**, effect deploy, schema 1. `.deploy` удалён после
прогона; дерево чистое до и после. Полный JSON — `manifest-dry-run.json`.

## Откат

Цель `4f8d7007efc4e6546f390f5fef147e8fbd2e8f86` (2.58.210), схема 47, DDL 0, данные/настройки не меняются;
M4A wave-1 UI и M2.1 per-chat rows остаются (см. `rollback.json`).

## Evidence

- `assembly.md` (этот файл), `tests-2.58.211.json`,
  `manifest-dry-run.json`, `rollback.json`, `limitations.md`;
- W2a RED/мутации/скриншоты: `evidence/m4a/w2a/` (`red-4f8d7007.txt`,
  `w2a-verification.md`, `shots/`).

## Что этот релиз не делает

Не деплоит, не заявляет VERIFIED, не расширяет scope W2b/W2c, не регистрирует
провайдер активности, не закрывает «живые permissions» (`MAC-AC-08` UI-часть;
наблюдение — W3/`MAC-S10-16`). QA/наблюдение — задача агентов, не владельца.
