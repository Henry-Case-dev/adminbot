# RED / GREEN / mutations — M5B MAC-EXP-08

## RED (base f40402660)

Detached worktree, новый test file:

```
FAILED tests/test_mod_acl_ux_m5b_shared_review.py::test_global_on_chat_off_no_lessons_from_existing_episodes
assert lessons.get(-100, 0) == 0
assert 1 == 0
1 failed, 5 passed in 15.57s
```

Причина: `_propose_batch` создаёт урок из explicit-эпизодов выключенного
чата; `_resume_incomplete` аналогично не проверял scope.

## GREEN (candidate)

```
pytest tests/test_mod_acl_ux_m5b_shared_review.py -q
7 passed in 6.28s

pytest tests/test_mod_acl_ux_m5b_shared_review.py \
  tests/test_mod_acl_ux_m2_resolver.py \
  tests/test_mod_acl_ux_m2_consumers.py \
  tests/test_mod_acl_ux_m2_capability_state.py \
  tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py -q
62 passed in 10.82s

pytest <18 related experience files> -q \
  -k "not deep_sleep_not_mixed_with_lessons"
299 passed, 1 deselected in 33.51s
```

## Mutations

1. Удалить P2-gate в `_propose_batch` (`if not await
   learning_enabled_for_chat(chat_id): continue`) →
   `test_global_on_chat_off_no_lessons_from_existing_episodes` падает:
   `{-200: 1, -100: 1}` вместо `{-200: 1}`.
2. После восстановления: 7 passed, `git diff --check` exit 0.

## Static

```
python -m py_compile services/mca_experience_jobs.py tests/test_mod_acl_ux_m5b_shared_review.py
exit 0
git diff --check
exit 0
plan gate (canonical checkout):
stage=plan inventory=279 manual=102 scoped=0 errors=0
```
