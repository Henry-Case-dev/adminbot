# C3 — тесты и фактические результаты

Дата: 2026-11-22. Все прогоны — в worktree `feat/mod-acl-m4c3` (база `f232a3a3`),
Python `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, Node `v24.16.0`.
Локальный стенд, **не live TMA**. Скриншоты — `c3/shots/`.

## Python

| Прогон | Результат |
|---|---|
| `pytest tests/test_acl_audit.py tests/test_webapp_access_write_safety.py tests/test_acl_legacy_inventory.py -q` | **63 passed, 0 failed** |
| C1 `tests/test_webapp_access_matrix_read.py` | **17 passed, 0 failed** |
| C2 `tests/test_webapp_access_effective.py` | **124 passed, 0 failed** |
| Hardening `tests/test_mod_acl_ux_m4c_acl_hardening.py` | **63 passed, 0 failed** |
| Focused C3a: `test_acl_audit` + `test_webapp_access_write_safety` + `test_webapp_access_effective` + `test_webapp_api` + `test_config_cache` + `test_roles_admin` + `test_permissions` + `test_diagnostic_policy` + `test_webapp_deps` + `test_webapp_access_matrix_read` + F8 | **568 passed, 0 failed** (36.6 s) |
| Pin guard, 24 version-pin файла | **856 passed, 4 failed** (73.9 s); те же 4 node-id падают на базе `f232a3a` (pre-existing, не C3): `test_tool_coordinator_round1026.py::TestBounds::{test_forbidden_paths_out_of_diff,test_canon_twelve_tools}`, `test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`, `::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` |
| S8-524 backend | `TestEmbeddingsGuard`: 401 без initData; 403 local_admin-grant/moderator/user; 200 admin (5 тестов) |

`py_compile` изменённых Python-файлов — rc=0; `git diff --check` — clean.

## Node

| Файл | Результат |
|---|---|
| `tests/js/mod_acl_ux_m4c3_write_test.js` | `MOD-ACL-UX-M4C3-WRITE-OK` |
| `tests/js/mod_acl_ux_m4c1_roles_page_test.js` | `MOD-ACL-UX-M4C1-ROLES-PAGE-OK` |
| `tests/js/mod_acl_ux_m4c1_editor_preserve_test.js` | `MOD-ACL-UX-M4C1-EDITOR-PRESERVE-OK` |
| `tests/js/mod_acl_ux_m4c2_preview_test.js` | `MOD-ACL-UX-M4C2-PREVIEW-OK` |
| `tests/js/mod_acl_ux_m4c2_admins_seed_test.js` | `MOD-ACL-UX-M4C2-ADMINS-SEED-OK` |
| `tests/js/mod_acl_ux_m3_module_routes_test.js` | OK — 235 проверок (UI-состояние 403 embeddings) |

## Playwright / Browser Use

| Прогон | Результат |
|---|---|
| `tools/ui_mod_acl_m4c3_write_e2e.py` | **PASS 0 failures**; viewports 1440/1280/768/390/320; h-scroll 0; save PUT/409/reapply/audit/local reset; 403/503 карточки; `e2e-report.json` |
| `tools/ui_mod_acl_m4c1_roles_e2e.py` | **PASS 0 failure(s)** |
| `tools/ui_mod_acl_m4c2_preview_e2e.py` | **PASS 0 failure(s)** |
| `tools/ui_mod_acl_m4b_status_e2e.py` (B1) | `{"ok": true, "checks": 138, "failures": []}` |
| `tools/ui_mod_acl_m4b2_status_e2e.py` (B2) | `{"ok": true, "checks": 92, "failures": []}` |
| `tools/ui_mod_acl_m4b3_status_e2e.py` (B3) | `{"ok": true, "checks": 131, "failures": [], "screenshots": 8}` |
| Browser Use (реальный Chrome, Code Mode) | `#/access/roles` 1440×900 + 390×844, `#/access/local` 390×844; `sw=innerWidth`, dirty/savebar, reset-блок; `c3-bu-*.png` |

## Ограничения

- Натуральный двухоконный 409 и натуральный долгий запрос с отзывом прав — RFL
  (детерминированные тесты recheck/409 обязательны и выполнены; live TMA не запускался).
- Реальный local_admin TMA-сеанс — RFL; backend/UI-матрица 403 проверена детерминированно.
- DDL/constraint на реальном PostgreSQL проверены исходником и идемпотентным
  DROP/ADD; production-миграция — при деплое 2.58.234 (вне C3).
