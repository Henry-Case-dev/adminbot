# M5B / MAC-EXP-08 — shared review при GLOBAL OFF + CHAT ON

Base: production 2.58.237 `f40402660`. Branch `feat/m5b-exp-08`.
Write scope: `services/mca_experience_jobs.py`, M5B tests/evidence.
M5A 3 REVIEW (`experience_diagnostics.py`) и ACL/UI/embedding/DDL не
затрагивались; `progress_scope.json`/`workflow_state.md` не изменялись.
Deploy/SSH/LLM/prod не выполнялись.

## 1. Контракт (map `MAC-EXP-08`)

- GLOBAL — наследуемый default, не запрет: **GLOBAL OFF + явный CHAT ON**
  обрабатывается shared review-worker'ом.
- **GLOBAL ON + CHAT OFF** — только этот чат выключен; worker/индекс живы.
- `review_enabled()` не блокирует job до выбора чата; аварийные env-оси
  K1/K3 остаются отдельными.
- Capture, detector, semantic, proposal/resume используют единый
  `learning_enabled_for_chat`; stored overrides не переписываются.
- M5B не является полным M5: `MAC-M5-01` остаётся PENDING (M5C/native
  question), live_required `MAC-EXP-08` — RFL до production-проверки.

## 2. Что уже было (M2/M2.1/M5A)

- `review_enabled()` уже не зависит от глобальной продуктовой настройки
  (только env K1/K3); `tick`/`run` не отбрасывают job при GLOBAL OFF.
- `_capture_feedback`, `_capture_tool_events`, `_detect_chat_feedback`,
  `_semantic_window` уже проверяют `learning_enabled_for_chat`.
- `learning_enabled_for_chat` — существующий M2.1 resolver
  `chat_params.resolve_param_capability`; M5B не создаёт второй resolver.

## 3. Фактический gap и fix

Первичный gap: `_propose_batch` (P1 technical / P2 explicit / P3 preference)
и `_resume_incomplete` (candidate/validated) не проверяли per-chat learning:
при GLOBAL ON + CHAT OFF общий worker мог создать/активировать урок из уже
накопленных эпизодов/кандидатов выключенного чата.

Fix — `services/mca_experience_jobs.py`:

- в циклах P1/P2/P3 перед `_lesson_exists`/`_reconfirm_existing`/
  `propose`/`_propose_preference`: `if not await
  learning_enabled_for_chat(chat_id): continue`;
- в `_resume_incomplete` перед validate/activate: `scope_chat_id`
  проверяется тем же resolver; durable candidate не удаляется, просто не
  активируется;
- **R1 F01 (P3)**: preference-цикл получил gate до `_lesson_exists`,
  `_reconfirm_existing` и `_propose_preference`; ранее gate стоял только в
  P4, поэтому `social_preference` создавался и активировался в том же тике
  для выключенного чата;
- **R1 F01 (defense-in-depth)**: `_validate_and_activate` перед
  validate/activate читает `scope_chat_id` урока (или `pref_chat_id`
  кандидата) и пропускает выключенный scope; durable candidate
  сохраняется.

Других изменений кода нет. M5A semantic stage (completed/partial/
unavailable) и E-TRUNC/E-LAG (heartbeat/fencing, counters, bounded retry,
fresh lane) сохранены.

## 4. RED / GREEN

Первичный RED на `f40402660` (detached worktree, 6 тестов):

```
FAILED test_global_on_chat_off_no_lessons_from_existing_episodes
  assert lessons.get(-100, 0) == 0
  assert 1 == 0   # урок выключенного чата создан
1 failed, 5 passed
```

R1 F01 RED на tip `4b79360c7` (4 новых теста):

```
FAILED test_global_on_chat_off_preference_not_created
FAILED test_global_off_chat_on_preference_only_for_enabled_chat
FAILED test_validate_and_activate_defense_in_depth_off_chat
1 passed: test_resume_off_candidate_not_activated (resume-gate уже был)
3 failed, 1 passed
```

GREEN после R1:

```
pytest tests/test_mod_acl_ux_m5b_shared_review.py -q
11 passed

pytest <M5B + M2 resolver/consumers/capability + M5A> -q
66 passed

pytest <18 related experience files + M5B> -q \
  -k "not deep_sleep_not_mixed_with_lessons"
310 passed, 1 deselected
```

Мутации:

- удаление P3-gate → падают оба preference-теста (2 failed);
- удаление defense-in-depth → падает
  `test_validate_and_activate_defense_in_depth_off_chat`;
- после восстановления 11 passed, `git diff --check` 0.

## 5. Тесты (11)

1. `review_enabled` не блокируется GLOBAL OFF; job ставится и выполняется.
2. GLOBAL OFF + CHAT ON: capture/detector/semantic только для ON-чата;
   LLM prompt не содержит OFF-чат; cursor OFF-чата drained без обучения.
3. GLOBAL ON + CHAT OFF: уроки/LLM только для ON-чата, worker completed.
4. GLOBAL OFF, все INHERIT: worker completed, LLM 0, feedback 0.
5. GLOBAL ON + CHAT OFF: существующие explicit-эпизоды не создают урок
   выключенному чату (RED→GREEN).
6. GLOBAL ON + CHAT OFF: preference-feedback OFF-чата не создаёт
   `social_preference` (R1 F01).
7. GLOBAL OFF + CHAT ON: preference-feedback создаёт урок только ON-чату
   (R1 F01).
8. GLOBAL ON + CHAT OFF: durable preference-candidate OFF-чата остаётся
   candidate и не активируется (resume).
9. `_validate_and_activate` defense-in-depth не активирует candidate
   выключенного чата (R1 F01).
10. GLOBAL OFF + CHAT ON: активный урок ON-чата возвращается
    `select_for_context`; у OFF-чата уроков нет (retrieval-контур жив).
11. GLOBAL OFF + CHAT ON: валидный semantic candidate принимается только
    для ON-чата.

## 6. RFL / blockers

- `MAC-EXP-08` live_required: реальная пара GLOBAL OFF + CHAT ON и
  GLOBAL ON + CHAT OFF на production не измерялась → **REVIEW/RFL**, не
  VERIFIED.
- Retrieval-контур (`direct_chat_service`/`mca_experience.select_for_context`)
  не менялся: positive retrieval ON-чата проверен. Per-chat гейт для уже
  существующих уроков OFF-чата относится к consumer-adapter `MAC-M2-01`
  (PENDING) и вне write scope этого кандидата; live/consumer-проверка
  остаётся RFL.
- `MAC-M5-01` PENDING: M5C/native question.
