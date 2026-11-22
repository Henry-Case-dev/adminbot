# C3.1 — C3-R1-B01 / N01 (RED → GREEN)

База фикса: `7b242bde1` (`feat/mod-acl-m4c3`). Изменены только
`web/api/routes.py` (тело recheck), `tests/test_webapp_access_write_safety.py`
(регрессии) и F8-пин (routes hash). DDL/C2/embedding/hardening не менялись;
`access_preview.py` байт-идентичен.

## B01 — partial override давал ложный 403 в recheck

**Причина:** request-time guard считает `effective_matrix` по RAW
(`db_override_map`), а recheck — по нормализованному `snapshot.value`.
Partial override (legacy only-view / hidden-only / new-form только
`view_roles`) терял унаследованный `edit_roles` → `can_edit_param=False` →
403 «права изменены во время сохранения» при неизменных правах, вторая
запись не выполнялась.

**Fix:** recheck использует `entry["raw_value"]` (тот же raw, что GET матрицы
после `7b242bde1`); effective_matrix снова наследует missing-поля из дефолта.

**RED на `7b242bde1`** (`pytest -k c31`):
```
FAILED ...::test_c31_partial_override_no_false_403[partial0]  # view_min_role
FAILED ...::test_c31_partial_override_no_false_403[partial1]  # view_roles only
FAILED ...::test_c31_partial_override_no_false_403[partial2]  # hidden_from_local
4 failed, 4 passed
```
Фактический ответ RED: `403 {"detail":{"code":"denied","keys":[PARTIAL_KEY]}}`,
`set_chat_params` вызван 1 раз.

**GREEN:** все 3 partial-формы → `200`, ровно 2 вызова (conflict → recheck →
retry), `expected_updated_at=None` на второй записи.

## N01 — inherit-only retry без recheck

**Причина:** `recheck` передавался только при `settings_overrides`;
inherit-only (`mode="inherit"`, `settings_overrides` пуст) после конфликта
делал вторую запись без пере-проверки прав.

**Fix:** recheck передаётся при `settings_overrides or inherit_keys`;
recheck проверяет `can_edit_param` и для inherit-ключей (не только value-keys).

**RED на `7b242bde1`**:
```
FAILED ...::test_c31_inherit_retry_rechecks_rights
E  assert 200 == 403
```
(2 записи при отозванных правах; `updated`/`inherit` в ответе).

**GREEN:** revoke → `403 {"code":"denied","keys":[KEY]}`, ровно 1 вызов;
неизменные права → `200`, 2 вызова (retry один раз).

## Тесты

- `pytest tests/test_webapp_access_write_safety.py -k "c31 or recheck" -q`
  → **13 passed**.
- C3 полный: **71 passed** (было 63 + 8 регрессий).
- C1 17 + C2 124 + hardening 63 → **204 passed**.
- Focused (11 файлов + F8) → **576 passed**, 0 failed.
- Pin guard 24 файла → **856 passed, 4 failed** (те же 4 pre-existing).
- C3 e2e 5 viewport → **PASS 0 failures**; C1/C2 e2e PASS; B1 138/0, B2 92/0,
  B3 131/131.
- `node --check web/app.js`, `py_compile` — rc=0; `git diff --check` — clean.

## Diff

`web/api/routes.py` (+14/−4), `tests/test_webapp_access_write_safety.py`
(+161), `tests/test_round1025_f8_registry.py` (re-pin routes hash с NOTE).
Новых ACL/store/DDL/route нет; route-set не менялся.
