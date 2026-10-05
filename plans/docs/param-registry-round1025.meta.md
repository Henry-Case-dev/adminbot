# F8 — `param-registry-round1025` — провенанс `.meta.md`

- **APP_VERSION:** `2.58.61`
- **HEAD (short):** `897ce4f`
- **Источник:** `services/param_catalog.py` (REGISTRY/GROUPS/_TAB_BY_GROUP/TAB_RULES) + `inventory.tsv` (10.14) для дельты.
- **Счётчики каталога:** REGISTRY **510** / GROUPS **108** / `_TAB_BY_GROUP` **106** / TAB_RULES **21**.
- **Реестр:** 510 строк == REGISTRY.
- **inventory.tsv (10.14):** 411 baseline-ключей.
- **Дельта 411 → 510 = 99** новых ключей (`status=new`).
- **Команда генерации:** `python tools/gen_param_registry_round1025.py`
- **Проверка (маркер):** `python tools/gen_param_registry_round1025.py --check`

## Схема реестра (TSV)

`internal_key | display_name | description | data_type | current_value | default_value | scope | inheritance | read_api | write_api | validation | permissions | category | group | per_chat | secret | hidden | ui_visibility | widget | storage | runtime_consumer | read_fn | status`

## Семантика (R17-safe)

- `current_value`: `runtime` — значение живёт в bot_settings/scope рантайма и статически не экспортируется; читается через `read_api`.
- `current_value`/`default_value` для `secret=true`/`category=keys`: только `{configured,last4}` (R17); открытое значение НИГДЕ не выводится.
- `default_value`: `code:<module.attr>` для промптов (код-канон) | `-` для прочих (дефолт живёт в `Settings`/PG-сиде и env-зависим, поэтому в committed-артефакт не экспортируется — детерминизм).
- `-` = поле неприменимо/отсутствует (документированное отсутствие).
- `ui_visibility=api-only` — ключ существует (env/каталог), но UI-места нет → **не** считается сохранённым в UI.

## Дельта 411 → 510 = 99 (ключи, отсутствовавшие в inventory.tsv)

- `api_token`
- `betterstack_host`
- `checkup_journalctl_cmd`
- `cobalt_api_url`
- `cobalt_http_proxy`
- `db_path`
- `download_dir`
- `embedding_fallback_max_retries`
- `embedding_fallback_timeout_seconds`
- `flags.budgets_enabled`
- `flags.chat_autonomous_reply_enabled`
- `flags.chat_decision_ignore_trivial_enabled`
- `flags.chat_decision_image_reactions_enabled`
- `flags.chat_decision_reactions_enabled`
- `flags.chat_silent_ack_enabled`
- `flags.image_generation_module_enabled`
- `flags.lore_compiler_enabled`
- `flags.summary_hybrid_l1_repair_enabled`
- `flags.summary_hybrid_l1_retry_enabled`
- `flags.summary_hybrid_l2_enabled`
- `flags.summary_legacy_fallback_enabled`
- `info_text_file`
- `keys.embedding_quota_group_labels`
- `keys.image_api_key`
- `keys.image_style_api_key`
- `keys.random_quantum_api_key`
- `keys.random_quantum_batch_length`
- `keys.random_quantum_buffer_max_values`
- `keys.random_quantum_data_type`
- `keys.random_quantum_endpoint`
- `keys.random_quantum_plan`
- `keys.random_quantum_provider`
- `keys.random_quantum_refill_low_watermark`
- `keys.random_quantum_request_timeout_seconds`
- `keys.summary_l1_api_key`
- `keys.summary_l2_api_key`
- `limits.anticliche_max_patterns`
- `limits.chat_timezone`
- `limits.factcheck_context_after`
- `limits.factcheck_context_before`
- `limits.image_daily_limit`
- `limits.import_history_retention_days`
- `limits.summary_hybrid_context_chars`
- `limits.summary_hybrid_context_tokens`
- `limits.summary_hybrid_max_chars`
- `limits.summary_hybrid_response_mode`
- `limits.summary_hybrid_target_chars`
- `limits.summary_hybrid_target_paragraphs`
- `local_bot_api_url`
- `log_ring_max_entries`
- `logtail_source_token`
- `media_base`
- `memory.experience_learning_enabled`
- `memory.experience_review_cadence`
- `memory.random_exploration_probability`
- `memory.random_fallback_to_pseudorandom`
- `memory.random_sleep_exploration_probability`
- `memory.random_source`
- `memory.random_uses_archive_sample`
- `memory.random_uses_association_pair`
- `memory.random_uses_belief_review`
- `memory.random_uses_conversation_variant`
- `memory.random_uses_memory_recall`
- `memory.random_uses_ui_visualization`
- `models.chat_model_context_window`
- `models.image_base_url`
- `models.image_get_mode`
- `models.image_model`
- `models.image_style_base_url`
- `models.image_style_model`
- `models.summary_l1_base_url`
- `models.summary_l1_model_name`
- `models.summary_l2_base_url`
- `models.summary_l2_model_name`
- `postgres_db`
- `postgres_dsn`
- `postgres_password`
- `postgres_user`
- `prompts.direct_chat_synthesizer_system_prompt`
- `prompts.direct_chat_verbalizer_system_prompt`
- `prompts.factcheck_analyst_system_prompt`
- `prompts.factcheck_verbalizer_system_prompt`
- `prompts.summary_cover_style`
- `prompts.summary_cover_style_id`
- `prompts.summary_editor_system_prompt`
- `prompts.summary_l1_clusterizer_system_prompt`
- `prompts.summary_l2_writer_system_prompt`
- `prompts.summary_narrator_system_prompt`
- `prompts.verbilizer_default_mode`
- `prompts.verbilizer_mode_casual`
- `prompts.verbilizer_mode_deep_research`
- `prompts.verbilizer_mode_serious`
- `sentry_dsn`
- `telegram_api_files_dir`
- `telegram_api_hash`
- `telegram_api_id`
- `uptime_events_retention_hours`
- `web_port`
- `webapp_url`

## Инварианты (Δ=0)

- **Δ каталога = 0:** генератор только читает `param_catalog`.
- **Δ DDL = 0:** БД/схема не затрагиваются.
- **R17:** секреты — только форма `{configured,last4}`.
- **Аддитивность:** артефакты новые, существующие контракты не менялись.
