# W1 — прогоны тестов (кандидат: рабочее дерево поверх 3b60887c)

Окружение: venv Python 3.12, Windows, офлайн (0 Telegram, 0 LLM-вызовов, 0 платных).

## Полный набор (финал)

`pytest tests/ -q` → **15180 passed, 39 skipped, 7 failed**.

Все 7 failed — до-существующий долг схем БД, НЕ связан с W1 (stash-проба на HEAD без изменений W1 — те же падения; локальная схема БД v37 против пинов v32–v35 — чужой слайс поднял версию, тесты не переутверждены):
- tests/test_asap7_direct_settings.py::test_migration_v35_idempotent_twice
- tests/test_asap7_direct_settings.py::test_backup_guard_fires_before_pending_step
- tests/test_t5150_startup_migrations_round1046.py::test_a/b/d/e/e2 (5 шт.)

## Родственный (focused) набор W1 — 26 файлов, зелёный

`pytest <26 related files> -q` → **699 passed** (сырой вывод: `OPENCODE_WORKFLOW_SCRATCH/asap-w1/related-run.txt`).

Включая:
- НОВЫЙ §9.1 чек-лист: tests/test_asap_w1_semantics.py — 21 passed (CONTRACT owner=ASAP-W1 P0-A..P0-G).
- Контракт-тесты канонов (байт-сверки): test_direct_chat_prompts (44), test_soul1_core_doc_text (8, v3-контракт + PREV-цепочка v1/v2 + superseded), test_prompt_migrations (лестницы/rollback), test_expression_isolation_followup, test_add_exp_expression, test_cfg07_backstage_contract, test_verbilizer_response_modes_round1023, test_mca23_response_plan.
- Suppress/known-canon/withheld: test_soul1_registry_legacy_removal, test_soul1_registry_completeness, test_cfg07a_f1_custom_suppress.
- OFF-паритет сборки по НОВОМУ дампу: test_soul1_composer_parity_off (P1/P2/P3/P4/P5a/P5b; артефакт `direct-runtime-assembly-w1.txt`, прежний артефакт soul-1 не правился).
- Initiative L1D-контракты: test_direct_l1_l1d_contract, test_direct_l1_corrective_r1, test_asap8_initreply_binding.
- Прочие затронутые: test_de_robotization_round1021, test_outgoing_guard_round1022, test_payload_builder, test_cfg07_egress_dictionary, test_soul1_core_composer_integration, test_soul1_factory_defaults, test_soul1_composer_layers, test_soul1_core_registry_api, test_soul1_w6_speech_ui.

## Байт-верификация канонов против первоисточника

`OPENCODE_WORKFLOW_SCRATCH/asap-w1/verify_bytes.py` (§3.1+адаптация/3.2/3.3/3.4 header+footer+3 режима/3.6/3.7 == константы; PREV_*_W1 sha12 == W0-прод-хешам d98e72ec7926/e0529832ba7c/d0ef0d376fc3/0fe9680ba280/ace6246bd360) → ALL OK. Те же сверки зашиты в tests (читают снапшот напрямую).
