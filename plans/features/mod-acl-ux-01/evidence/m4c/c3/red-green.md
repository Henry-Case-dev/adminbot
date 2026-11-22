# C3 — RED/GREEN и discriminating assertions

## RED (до C3 — воспроизводимые дефекты base `f232a3a`)

| # | Сценарий RED | Что падает без C3 |
|---|---|---|
| R1 | `GET /api/roles` не содержит `revision`; повторный `POST` после удаления роли **пересоздаёт** её | `test_get_roles_has_revision`, `test_expected_revision_does_not_recreate_absent_role`: ключ `revision`/409 `role_absent` отсутствует |
| R2 | Матрица пишет на каждый клик; `GET` не отдаёт `updated_at`; PUT/DELETE не имеют CAS | `test_get_includes_fresh_updated_at`, `test_cas_mismatch_conflict`, `test_delete_stale_absent_and_404` |
| R3 | Чатовый override: read-merge-write без токена; нет DELETE; нет профиля → 409 с `null`, а не 404 | `TestChatOverride::test_cas_conflict_only_key_no_values`, `test_delete_reset_only_key`, `test_delete_404_key_and_profile` |
| R4 | Нет durable audit (только client-строка «в этой сессии»), нет `GET /api/access/audit` | `TestAuditRead`, `test_role_mutation_rolls_back`, `test_global_param_rolls_back`, `test_chat_override_rolls_back` |
| R5 | Retry `_write_chat_overrides_with_retry` пишет без re-check (docstring base прямо: «пере-проверка не нужна») | `test_retry_recheck_denies_before_second_write`, `test_post_config_recheck_denies_403_no_second_write`, `test_meme_settings_recheck_own_gate` |
| R6 | `field='access'` отсутствует в CHECK; lore/oversight отдают любые строки истории | `test_migration_idempotent_and_rollback_compatible`, `test_history_excludes_access_in_sql`, call-site inspect |
| R7 | UI: toggle/reset делают API сразу; savebar/409/audit-панели/reset в `#/access/local` нет | `mod_acl_ux_m4c3_write_test.js`: `toggle` не содержит `this.api(`; сохранение N с токенами; 409/reapply; audit 50→200; local reset |

## GREEN (фактические прогоны)

- 71 Python C3-теста (audit + write safety + inventory, вкл. C3.1 B01/N01) — PASS.
- 17 C1 / 124 C2 / 63 hardening — PASS; 576 focused — PASS.
- Node C1/C2/C3/M3 — PASS; e2e C3 + C1 + C2 + B1/B2/B3 — PASS.
- Pin guard 856/4 — 4 падения идентичны базе (pre-existing, не C3).
- Browser Use: реальный Chrome, desktop 1440 и 390; h-scroll 0, тач 44.

## Discriminating counterexamples (не тавтологии)

1. **Audit fail-closed:** fake-БД `fail_audit=True` → mutation POST/PUT → `503`,
   состояние строки не изменилось. Если audit писать после commit/в отдельной
   транзакции, тест даёт 200 и изменённую строку.
2. **Recheck deny:** fake `set_chat_params` бросает `ChatParamsConflict` один раз;
   `access_for` на recheck возвращает `role_chat=None` → API 403, `set_chat_params`
   вызван **ровно один раз** (второй записи нет).
3. **role_absent:** POST с `expected_revision` для отсутствующей роли → 409,
   `deleted_role not in db.roles` и 0 audit-строк (не пересоздаёт).
4. **chat reset scope:** DELETE снимает только `perm_overrides[key]`; тест
   проверяет, что `overrides`, `param_permissions` и роли не изменились.
5. **No-op:** повторная запись той же матрицы/прав → 200 `unchanged`, `updated_at`
   не сдвинут, audit не добавлен.
6. **No-secret:** sentinel prompt/значение/last4/сырой секрет отсутствуют в JSON
   audit; `parse_event` отбрасывает extra-поля.
