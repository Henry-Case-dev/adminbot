# Audit Backlog

<!-- Format: one item per line, `- [ ]` = pending, `- [x]` = done -->
<!-- High-priority (git-changed) files go on top; no code-change files this run. -->

## Round 10.3 scan (2026-09-10) — all scanned
- [x] plans/features/tma-chat-selector-fixes/ (spec)
- [x] plans/features/dm-user-settings/ (spec)
- [x] plans/features/direct-sandbox-budget-investigation/ (spec)
- [x] services/access.py (DM-ветки can_access_chat/eligible_type/can_edit_param)
- [x] services/roles.py (is_dm_owner/DM_OWNER_PRESET/access_for DM-ветка)
- [x] services/chat_params.py (is_dm_scope/ensure_scope_profile/get_chat_param_defaulted/chat_summary_enabled)
- [x] services/llm_client.py (NoApiKeyForChat.details, BYOK-фоллбэк, usage-учёт)
- [x] services/direct_chat_service.py (S2-гейт, sandbox WARNING details)
- [x] services/summary_memory.py (S1-гейт, _mask_llm_raw, fallback-парсер, ретрай)
- [x] services/summary_scheduler.py (S3: skip chat_id>0)
- [x] services/chat_lore_store.py (П.2: chat_id<0)
- [x] services/oversight.py (П.4: chat_id<0)
- [x] web/api/routes.py (DM-гейты GET/POST/keys/delete/status)
- [x] web/api/access.py (DM-строка, фильтр <0)
- [x] web/api/gates.py (DM read/403 write)
- [x] web/api/chat_lore.py (DM→404)
- [x] web/app.js (canViewTab/canEditConfig/isDmCtx/configError/setActiveChat/closeApp)
- [x] web/index.html (селектор, template v-for/v-if, бейдж, z-index 45, баннер)
- [x] tests/test_dm_access.py, test_webapp_dm_ui.py + обновлённые тест-файлы (4831 passed)

## High priority (git working tree)
- [x] plans/MEMORY.md (untracked, doc-only)

## Root files
- [x] bot.py
- [x] manage.py
- [x] conftest.py
- [x] deploy_v2.9.2.py
- [x] check_remote_bot.py
- [x] debug_remote.py
- [x] docker-compose.yml
- [x] requirements.txt
- [x] pytest.ini
- [x] .gitignore
- [x] .env.example
- [x] info_text.md

## config/
- [x] config/settings.py
- [x] config/__init__.py

## handlers/
- [x] handlers/__init__.py
- [x] handlers/common.py
- [x] handlers/menu.py
- [x] handlers/media_common.py
- [x] handlers/info.py
- [x] handlers/search.py
- [x] handlers/admin_commands.py
- [x] handlers/alan.py
- [x] handlers/alan_greeting.py
- [x] handlers/kostik.py
- [x] handlers/slavik.py
- [x] handlers/slava_presence.py
- [x] handlers/olya.py
- [x] handlers/vasya.py
- [x] handlers/dead_page_trigger.py
- [x] handlers/dead_page_delete.py
- [x] handlers/war_alert.py
- [x] handlers/chat_lifecycle.py
- [x] handlers/direct_chat.py
- [x] handlers/factcheck.py
- [x] handlers/summary.py
- [x] handlers/video_download.py
- [x] handlers/voice_transcription.py
- [x] handlers/web.py
- [x] handlers/youtube.py
- [x] handlers/checkup.py
- [x] handlers/debug_config.py

## filters/
- [x] filters/__init__.py
- [x] filters/admin_word.py
- [x] filters/danger_word.py
- [x] filters/kucha_word.py
- [x] filters/olya_video.py
- [x] filters/otboy_word.py
- [x] filters/selfdev_word.py
- [x] filters/target_channel.py
- [x] filters/user_id.py
- [x] filters/vasya_name.py
- [x] filters/word_lists.py
- [x] filters/work_word.py

## services/
- [x] services/__init__.py
- [x] services/access.py
- [x] services/betterstack_handler.py
- [x] services/bot_commands.py
- [x] services/chat_access.py
- [x] services/chat_context.py
- [x] services/chat_keys.py
- [x] services/chat_lore.py
- [x] services/chat_lore_store.py
- [x] services/chat_params.py
- [x] services/chat_prompts.py
- [x] services/chat_usage.py
- [x] services/checkup_prompts.py
- [x] services/checkup_service.py
- [x] services/common_relay.py
- [x] services/config_cache.py
- [x] services/control_service.py
- [x] services/database.py
- [x] services/dead_page_relay.py
- [x] services/debug_config.py
- [x] services/direct_chat_service.py
- [x] services/dream_prompts.py
- [x] services/dream_worker.py
- [x] services/feature_gates.py
- [x] services/goodmorning_captions.py
- [x] services/goodmorning_relay.py
- [x] services/goodmorning_scheduler.py
- [x] services/hot_config.py
- [x] services/info_service.py
- [x] services/llm_circuit_breaker.py
- [x] services/llm_client.py
- [x] services/log_ring.py
- [x] services/lore_cache.py
- [x] services/lore_notify.py
- [x] services/lore_prompts.py
- [x] services/lore_runtime.py
- [x] services/lore_worker.py
- [x] services/media_download.py
- [x] services/media_group_buffer.py
- [x] services/media_picker.py
- [x] services/media_share.py
- [x] services/memory_backup.py
- [x] services/memory_health.py
- [x] services/memory_maintenance.py
- [x] services/message_counter.py
- [x] services/mimic_relay.py
- [x] services/mimic_transform.py
- [x] services/nostalgia_prompts.py
- [x] services/nostalgia_worker.py
- [x] services/olya_relay.py
- [x] services/oversight.py
- [x] services/param_catalog.py
- [x] services/payload_builder.py
- [x] services/permissions.py
- [x] services/permsoc.py
- [x] services/persistent_throttling.py
- [x] services/pg_db.py
- [x] services/progress_reporter.py
- [x] services/prompt_migrations.py
- [x] services/roles.py
- [x] services/sandbox_reply.py
- [x] services/scheduler.py
- [x] services/search_aggregator.py
- [x] services/search_prompts.py
- [x] services/search_service.py
- [x] services/smart_cache.py
- [x] services/smartmodule_concurrency.py
- [x] services/smartmodule_phrases.py
- [x] services/smartmodule_throttling.py
- [x] services/smartmodule_urls.py
- [x] services/smartmodule_utils.py
- [x] services/status_service.py
- [x] services/summary_aliases.py
- [x] services/summary_cleanup.py
- [x] services/summary_generator.py
- [x] services/summary_memory.py
- [x] services/summary_prompts.py
- [x] services/summary_scheduler.py
- [x] services/summary_throttling.py
- [x] services/summary_xml.py
- [x] services/system_logs_fetcher.py
- [x] services/token_counter.py
- [x] services/tool_loop.py
- [x] services/tool_router.py
- [x] services/tool_schemas.py
- [x] services/typing_manager.py
- [x] services/uptime_heartbeat.py
- [x] services/user_relations.py
- [x] services/video_cascade_client.py
- [x] services/web_content_extractor.py
- [x] services/web_prompts.py
- [x] services/web_runtime.py
- [x] services/web_summarizer_service.py
- [x] services/worker_budget.py
- [x] services/youtube_prompts.py
- [x] services/youtube_summarizer_service.py
- [x] services/youtube_transcript_engine.py

## scripts/
- [x] scripts/__init__.py
- [x] scripts/backfill_feature_gates.py
- [x] scripts/backfill_permsoc_gates.py
- [x] scripts/migrate_direct_chat_v2.py
- [x] scripts/migrate_env_to_pg.py
- [x] scripts/migrate_epic60_v3.py
- [x] scripts/migrate_graphrag_v2.py
- [x] scripts/run_golden_questions.py
- [x] scripts/seed_chat_lore.py

## tools/
- [x] tools/__init__.py
- [x] tools/cookies_export.py
- [x] tools/video_downloader.py
- [x] tools/video_download_phrases.py
- [x] tools/history_import/__init__.py

## web/
- [x] web/__init__.py
- [x] web/app.py
- [x] web/app.js
- [x] web/index.html
- [x] web/api/__init__.py
- [x] web/api/access.py
- [x] web/api/admins.py
- [x] web/api/avatars.py
- [x] web/api/chat_lore.py
- [x] web/api/config.py
- [x] web/api/direct_chat.py
- [x] web/api/keys.py
- [x] web/api/logs.py
- [x] web/api/oversight.py
- [x] web/api/params.py
- [x] web/api/permissions.py
- [x] web/api/relations.py
- [x] web/api/roles.py
- [x] web/api/status.py
- [x] web/api/system.py
- [x] web/api/usage.py
- [x] web/api/workers.py

## SmartModule/
- [x] SmartModule/__init__.py
- [x] SmartModule/service.py

## tests/
- [x] tests/__init__.py
- [x] tests/conftest.py
- [x] tests/test_*.py (all test files)