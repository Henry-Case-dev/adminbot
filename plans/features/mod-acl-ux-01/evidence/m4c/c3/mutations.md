# C3 — mutation / fail-closed проверки

Цель — доказать, что тесты падают при удалении механизма, а не только
«зеленеют рядом с кодом».

| Мутация (мысленная/фактическая) | Ожидаемое падение | Фактический GREEN-тест |
|---|---|---|
| `config_cache._write_audit` не вызывается / audit после commit | мутация роли/админа остаётся при ошибке audit (200 вместо 503) | `TestAuditFailClosed::test_role_mutation_rolls_back` (503, роль не изменена) |
| `insert_access_audit` вызывается вне транзакции | глобальный override остаётся при ошибке audit | `TestAuditFailClosed::test_global_param_rolls_back` |
| chat override audit после commit | ключ/значение остаются при 503 | `TestAuditFailClosed::test_chat_override_rolls_back` |
| Убрать `recheck()` из retry | вторая запись проходит после отзыва прав | `test_retry_recheck_denies_before_second_write` (1 вызов, исключение) |
| Убрать recheck из POST /api/config | 200/вторая запись вместо 403 | `test_post_config_recheck_denies_403_no_second_write` |
| Вернуть 409 с `null` для отсутствующего профиля | нет 404 `chat_profile_absent` | `test_post_profile_absent_404`, `test_delete_404_key_and_profile` |
| Игнорировать `expected_revision` при отсутствии роли | роль пересоздаётся | `test_expected_revision_does_not_recreate_absent_role` |
| Снимать весь `perm_overrides` вместо ключа | теряются другие перекрытия | `test_delete_reset_only_key` |
| Писать `chat_params` root (prompt/значения) в audit | sentinel появляется в JSON | `test_no_secret_or_prompt_in_audit`, `test_param_event_has_no_values_or_prompts` |
| UI toggle пишет напрямую | `this.api(` в `matrixRoleToggle` | `tests/js/mod_acl_ux_m4c3_write_test.js` статический assert + runtime 0 запросов |
| UI save без токена | PUT body без `expected_updated_at` | node: `bodies[1].expected_updated_at == ts` |
| UI не блокирует save после 409 | save кнопка enabled | node: `saveDisabled === true` |

Фактические запуски: `pytest tests/test_webapp_access_write_safety.py -q`
(все fail-closed/recheck/409/404 секции), `pytest tests/test_acl_audit.py -q`,
`node tests/js/mod_acl_ux_m4c3_write_test.js` — PASS. Скриншоты 409/reapply:
`c3/shots/c3-matrix-conflict-1440.png`, `c3-role-conflict-1440.png`.
