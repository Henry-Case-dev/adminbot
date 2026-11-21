# M4C C1 — routes byte-freeze re-pin (REL-229-PIN-01)

- Candidate: `4618a3be2` (`feat/mod-acl-m4c1`), product unchanged since
  `eb305b6fe`; base `374dc6060` (2.58.228).
- Rule: **L-F11S-1** — `web/api/routes.py` под byte-freeze; осознанное
  изменение файла требует re-pin + rationale.
- Причина Δ: MOD-ACL-UX-01 M4C C1 добавил в `web/api/routes.py` **+12
  строк**: три honest 503-guard'а в существующих GET `roles`/`admins`/
  `roles/tree` для случая «пустой RAM-кэш + `pg_available=false`».
  Это не рефакторинг, не новый endpoint, не новое поле/флаг и не DDL;
  routes-инвентарь `tests/fixtures/round1025/f8_baseline.json` не менялся.

## Пин

| | Значение |
|---|---|
| Старый `ROUTES_SHA256_F11` | `4faa0a5379a9943d7b0f11403a051777eb779a033c3bc069a1b3300cb7392ee7` |
| Фактический `sha256(web/api/routes.py)` | `70875819c728e9da618194476a6d063cc291de375935ae1cc64f405b94cf56c2` |
| Новый пин | `70875819c728e9da618194476a6d063cc291de375935ae1cc64f405b94cf56c2` |

Обновлены оба места (единый источник истины + зеркало):

- `tests/test_round1025_f8_registry.py` — канон `ROUTES_SHA256_F11`;
- `tests/test_mca23_planned_vs_actual.py` — зеркало `ROUTES_SHA256_F11`.

В обоих добавлен rationale-комментарий про три C1 503-guard'а и L-F11S-1.
`tools/_pins_258152_reissue_routes.py --check` → `CHECK OK` (оба пина
совпадают с фактическим хешем).

## Проверки

- Два целевых pin-теста: **2 passed**
  (`test_mca17c_invariants_round1047.py::test_routes_py_byte_freeze_pin_intact`,
  `test_round1025_f8_registry.py::TestFrozenInvariants::test_routes_file_unchanged`).
- Полный pin-guard (24 Python-файла release-набора):
  **856 passed / 4 failed**, те же 4 pre-existing node-id, что и на базе:
  `test_tool_coordinator_round1026::TestBounds::{test_forbidden_paths_out_of_diff,
  test_canon_twelve_tools}`,
  `test_unified_image_request_round1026::TestToolDescriptionU21::test_canon_unchanged`,
  `TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`.
- Подтверждение, что re-pin ничего не сломал:
  C1 Playwright PASS 0; Python focused 320/1 (pre-existing
  `test_r4_custom_modules_removed`); B1 138/0, B2 92/0, B3 131/131;
  node `tests/js/*.js` 128/131 (3 pre-existing); `node --check`/`py_compile`
  OK.
- `f8_baseline` routes-инвентарь не менялся; новых endpoint'ов/полей/флагов/
  DDL нет; `APP_VERSION` = 2.58.228.
