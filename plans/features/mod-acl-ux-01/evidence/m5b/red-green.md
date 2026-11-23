# RED / GREEN / mutations — M5B MAC-EXP-08

## Initial RED (base `f40402660`)

Detached worktree, новый test file (6 тестов на тот момент):

```
FAILED tests/test_mod_acl_ux_m5b_shared_review.py::test_global_on_chat_off_no_lessons_from_existing_episodes
assert lessons.get(-100, 0) == 0
assert 1 == 0
1 failed, 5 passed in 15.57s
```

Причина: `_propose_batch` создаёт урок из explicit-эпизодов выключенного
чата; `_resume_incomplete` аналогично не проверял scope.

## R1 F01 RED (tip `4b79360c7`, до fix)

4 новых discriminating теста:

```
FAILED test_global_on_chat_off_preference_not_created
FAILED test_global_off_chat_on_preference_only_for_enabled_chat
FAILED test_validate_and_activate_defense_in_depth_off_chat
PASSED test_resume_off_candidate_not_activated
3 failed, 1 passed, 7 deselected in 3.79s
```

Причина F01: P3 preference-цикл не проверял `learning_enabled_for_chat`;
`_propose_preference` создавал `social_preference`, а
`_validate_and_activate` активировал его в том же тике. Resume-тест
проходил, потому что gate в `_resume_incomplete` уже был.

## GREEN (R1 candidate)

```
pytest tests/test_mod_acl_ux_m5b_shared_review.py -q
11 passed in 4.68s

pytest tests/test_mod_acl_ux_m5b_shared_review.py \
  tests/test_mod_acl_ux_m2_resolver.py \
  tests/test_mod_acl_ux_m2_consumers.py \
  tests/test_mod_acl_ux_m2_capability_state.py \
  tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py -q
66 passed in 9.03s

pytest <18 related experience files + M5B> -q \
  -k "not deep_sleep_not_mixed_with_lessons"
310 passed, 1 deselected in 36.35s
```

## Mutations

1. Удалить P2-gate в `_propose_batch` (первичный fix) →
   `test_global_on_chat_off_no_lessons_from_existing_episodes` падает:
   `{-200: 1, -100: 1}` вместо `{-200: 1}`.
2. Удалить P3-gate (R1 F01) → падают оба preference-теста:
   `test_global_on_chat_off_preference_not_created`,
   `test_global_off_chat_on_preference_only_for_enabled_chat`
   (`2 failed, 9 deselected`).
3. Удалить defense-in-depth в `_validate_and_activate` (R1 F01) → падает
   `test_validate_and_activate_defense_in_depth_off_chat`
   (`assert 1 == 0`); preference-тесты при этом проходят, то есть мутация
   различает именно защитный слой.
4. После восстановления: 11 passed, `git diff --check` exit 0.

## Static

```
python -m py_compile services/mca_experience_jobs.py tests/test_mod_acl_ux_m5b_shared_review.py
exit 0
git diff --check
exit 0
plan gate (canonical checkout):
stage=plan inventory=279 manual=102 scoped=0 errors=0
```
