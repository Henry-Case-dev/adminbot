# MAC-S7-LIMIT-01 — durable hypotheses, не уроки (M5A-R1-04)

- Строка: `MAC-S7-LIMIT-01` (finding `M5A-R1-04`, low, nonblocking).
- Приёмка: `strategy_success`/`topic_pattern` остаются гипотезами
  (durable candidates), не превращаются в уроки.
- Base: `f40402660` (2.58.237). Кандидат: `0907dbae6`.
- Product code: не потребовался — поведение корректно; добавлен прямой
  durable-assert вместо косвенного `semantic_candidates >= 2`.
- Тест: `tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py::test_strategy_success_topic_pattern_not_promoted_to_lessons`.
- Durable-проверки (реальные строки `mca_experience_feedback`):
  - ровно 2 строки, `source_kind='llm_hypothesis'`;
  - `signal.kind` = `strategy_success` и `topic_pattern`;
  - `signal.semantic is True`, `signal.class='observation'`;
  - темы `weather` и `weekend`;
  - `counters.proposed=0`, `mca_lessons` пуст (гипотеза не урок).
- Мутации:
  - M3 (observation пишется как `participant_correction`) убита:
    `assert 1 == 0` по `proposed` (гипотеза стала кандидатом в урок);
  - M4 (подмена `kind` в signal) убита новым durable-assert:
    `['strategy_success','strategy_success'] != ['strategy_success','topic_pattern']`.
- Граница: `VERIFIED` не присваивается Builder'ом; нужен независимый
  Reviewer. Deploy/SSH/LLM/prod нет.

Evidence: `plans/features/mod-acl-ux-01/evidence/m5a/m5a-review-corrective-2.58.237.md`.
