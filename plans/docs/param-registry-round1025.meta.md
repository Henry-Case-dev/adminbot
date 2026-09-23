# F8 — `param-registry-round1025` — провенанс `.meta.md`

- **APP_VERSION:** `2.58.25`
- **HEAD (short):** `e3ea608`
- **Источник:** `services/param_catalog.py` (REGISTRY/GROUPS/_TAB_BY_GROUP/TAB_RULES) + `inventory.tsv` (10.14) для дельты.
- **Счётчики каталога:** REGISTRY **469** / GROUPS **100** / `_TAB_BY_GROUP` **98** / TAB_RULES **21**.
- **Реестр:** 469 строк == REGISTRY.
- **inventory.tsv (10.14):** 411 baseline-ключей.
- **Дельта 411 → 469 = 58** новых ключей (`status=new`).
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

## Дельта 411 → 469 = 58 (ключи, отсутствовавшие в inventory.tsv)

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
- `flags.image_generation_module_enabled`
- `flags.lore_compiler_enabled`
- `flags.summary_filter_enabled`
- `flags.summary_filter_reply_context_enabled`
- `info_text_file`
- `keys.image_api_key`
- `limits.anticliche_max_patterns`
- `limits.chat_timezone`
- `limits.factcheck_context_after`
- `limits.factcheck_context_before`
- `limits.import_history_retention_days`
- `limits.summary_filter_burst_window_seconds`
- `limits.summary_filter_context_max_messages`
- `limits.summary_filter_context_neighbors`
- `limits.summary_filter_min_burst_density`
- `limits.summary_filter_min_weight`
- `limits.summary_filter_min_words_for_bonus`
- `local_bot_api_url`
- `log_ring_max_entries`
- `logtail_source_token`
- `media_base`
- `models.image_base_url`
- `models.image_get_mode`
- `models.image_model`
- `postgres_db`
- `postgres_dsn`
- `postgres_password`
- `postgres_user`
- `prompts.direct_chat_synthesizer_system_prompt`
- `prompts.direct_chat_verbalizer_system_prompt`
- `prompts.factcheck_analyst_system_prompt`
- `prompts.factcheck_verbalizer_system_prompt`
- `prompts.summary_cover_style`
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
