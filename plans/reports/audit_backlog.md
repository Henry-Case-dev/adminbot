# Audit Backlog

<!-- Format: one item per line, `- [ ]` = pending, `- [x]` = done -->
<!-- High-priority (git-changed) files go on top; no code-change files this run. -->

## Round 10.7 scan (2026-09-11) — all scanned
- [x] web/app.js (scope* → computed 6 шт; ICONS −6 мёртвых; fmtLogTime; copyText
      finally-remove + preventScroll + boolean execCommand; copyLogRow + copiedIndex;
      copyAllLogs self.logText)
- [x] web/index.html (1b `header.header-sticky`+env safe-area; 1c компактный user block;
      1d nav-label keep-all/2-line clamp/0.625rem; 2a scoped `.keys-avail` fixed+ellipsis;
      3a `.clipboard-ghost` opacity/contain strict без visibility:hidden; 3b log-колонки;
      3c `log-copied`/`copyLogRow`)
- [x] services/status_service.py (2b `_bucketize` gap-fill 'down' до now_slot;
      `last_heartbeat` = последний 'up'/None)
- [x] tests/test_webapp_round107_ui.py (NEW: маркеры 1b/1c/1d/2a/3a/3b/3c)
- [x] tests/js/routing_test.js (стаб document/navigator/execCommand; 3a ghost-removed,
      DEF-2 false-execCommand, 3c copyLogRow, 1a computed)
- [x] tests/test_status_service.py (gap-fill up/down/down/up, trailing downtime,
      last_heartbeat None/truthy)
- [x] tests/test_font_subset.py (R106-5: `\ue887` help вместо `\ue850`)
- [x] tests/test_webapp_avatars_ui.py (`_Static.body` — regex определения функции)
- [x] tests/test_webapp_back_button.py (1a: 6 scope* в computed, не methods)
- [x] tests/test_webapp_tma_fixes_ui.py (3c: `copyLogRow(log,i)` + `log-copied`)
- [x] plans/backlog.md, plans/features/admin-ui-bugfixes-round107/ (spec/tasks)
- [x] plans/reports/round10.7_scanner_audit.md (итоговый отчёт — 0 блокеров/0 major,
      1 minor + 3 info + 1 nit; R10.6-5 закрыт)

## Round 10.6 scan (2026-09-11) — all scanned
- [x] config/settings.py (5 master-флагов FACTCHECK/SEARCH/VIDEO_SUMMARY/WEBPAGE/CHECKUP_ENABLED, default True)
- [x] services/param_catalog.py (GROUPS 91/REGISTRY 392/Settings 364/mapped 89; расщепления
      limits_media→4, limits_persons→2, limits_youtube_web→2, limits_cooldowns→0,
      flags_modules→7, flags_chat_behavior→7, reactions_kostik NEW, limits_rag NEW;
      _FLAGS +TAB_RULES/CONFIG_TAB_TITLES 19;_TAB_BY_GROUP 89, DDL-free)
- [x] services/llm_probe.py (NEW: _safe_base SSRF-минимум, sanitize_error R17,
      KNOWN_BLOCKS, probe_block/_probe_search, per-field search_keys:tavily/exa)
- [x] web/api/routes.py (POST /api/llm/test: requires_global_admin, rate-limit 5с/ttl-прунинг,
      LlmTestRequest; reset_llm_test_rate_limit — тест-точка)
- [x] handlers/factcheck.py, search.py, web.py, checkup.py, youtube.py
      (5 master-гейтов hot.get→UNHANDLED; youtube — только mode=="summary")
- [x] web/app.js (MODULES 11, PROVIDER_BLOCKS 9, accessOpen-аккордеон, scope/route-алиасы,
      activeModule-модалка, Esc/back-закрытие, canEditConfig DM per_chat R10.5-2,
      initBackButton ready R10.5-1, TAB_SECTION_ORDER 19, emoji→Material)
- [x] web/index.html (sidebar/☰/MENU_ORDER удалены, nav-label, scroll-модель,
      модуль-карточки+модалка, prov-блоки+test-кнопка, аккордеон, iconGlyph help/matrix)
- [x] tests/test_round106_gates.py (NEW: OFF→UNHANDLED ×5 + default ON)
- [x] tests/test_round106_ia_smoke.py (NEW: каталог-инвариант, nav, IA, llm_probe, SSRF)
- [x] tests/test_frontend_tab_mapping.py, test_param_catalog.py, test_webapp_api.py
      (POST /api/llm/test 403/200/429/R17), test_webapp_nav_disclosure_ui.py,
      test_webapp_hubs_matrix_ui.py, test_webapp_parity_smoke.py, test_webapp_dm_ui.py,
      test_webapp_agi_ui.py, test_webapp_back_button.py, test_webapp_lore_ui.py,
      test_webapp_avatars_ui.py, tests/js/routing_test.js (маркеры новой IA)
- [x] plans/features/tma-ia-modules-rework/ (spec v2, design-project v2, tasks)
- [x] plans/backlog.md (doc-only)
- [x] plans/reports/round10.6_scanner_audit.md (итоговый отчёт — 0 блокеров/0 major,
      3 minor + 3 info)

## Round 10.5 scan (2026-09-10) — all scanned
- [x] .gitignore (relumesite_example/, MaterialSymbolsRounded*.woff2, var/, build/)
- [x] services/key_history.py (NEW: allowlist, атомарный снимок, ring, fail-open)
- [x] services/param_catalog.py (_MODELS_PG_ONLY: +4 PG-only → REGISTRY 387/74/359)
- [x] services/config_cache.py (rename_role/role_usage/_scrub_param_permissions — DML-only)
- [x] services/status_service.py (_resolve/llm_registry module_id|module_title|model_source;
      _build_llm_card → key_history.record; maybe_save)
- [x] services/video_cascade_client.py (base_url hot + инвалидация клиента)
- [x] SmartModule/transcriber/groq_transcriber.py (hot base_url/model)
- [x] SmartModule/transcriber/openrouter_transcriber.py (hot base_url/model)
- [x] web/api/routes.py (roles DELETE + /rename; GET /status/key-history; get_roles role_type)
- [x] web/api/access.py (param_permissions_list: tab/tab_title/group*/title/secret метаданные)
- [x] web/app.py (mount /static — self-host fonts/vendor)
- [x] web/app.js (hash-роутер, navbar/hub, scope-dropdown+a11y, матрица, key-avail,
      role rename/delete, sanitize fail-closed, scopeEpoch-гварды, иконки PUA)
- [x] web/index.html (токены+градиенты, @font-face, navbar/hub, scope-dropdown,
      матрица, key-avail, self-host dompurify, адаптив)
- [x] scripts/build_font_subset.py + scripts/requirements-font.txt (NEW, build-time only)
- [x] web/static/fonts/* (субсет 13 КБ + LICENSE Apache-2.0)
- [x] web/static/vendor/dompurify-3.4.15.min.js (self-host, pinned)
- [x] conftest.py (M6: STATUS_KEY_HISTORY_FILE → temp)
- [x] tests/test_key_availability.py, test_roles_admin.py, test_font_subset.py,
      test_webapp_back_button.py, test_webapp_hubs_matrix_ui.py, test_webapp_js_unit.py,
      test_webapp_key_availability_ui.py, test_webapp_parity_smoke.py, tests/js/routing_test.js (NEW)
- [x] tests/test_menu.py, test_param_catalog.py, test_video_cascade.py, test_webapp_api.py,
      test_webapp_avatars_ui.py, test_webapp_deps.py, test_webapp_dm_ui.py,
      test_webapp_nav_disclosure_ui.py, test_webapp_rbac_ui.py (маркеры обновлены)
- [x] plans/features/tma-relume-redesign/ (spec v3, design-project v5, tasks, reference-analysis)
- [x] plans/MEMORY.md, plans/backlog.md (doc-only)
- [x] plans/reports/round10.5_scanner_audit.md (итоговый отчёт — 0 блокеров/0 major)

## Round 10.4 scan (2026-09-10) — all scanned
- [x] plans/features/* (8 спек: A reorg, B limits-temp-budgets, C memory-sleep-nostalgia,
      D advanced-collapse, E llm-providers-layout, F relations-participants,
      G chat-1002661910336-scaling, H relations-nickname)
- [x] services/param_catalog.py (TAB_RULES/CONFIG_TAB_TITLES/_TAB_BY_GROUP,
      select_options/labels, _MEMORY progressive_level, _ADVANCED_GROUPS)
- [x] services/chat_params.py (_resolve_from_root G-2: _cast_type_ok + isfinite)
- [x] services/direct_chat_service.py (_cp_g-точки, _budget_gate B-2,
      _apply_context_budget(enabled, tokens), _thread_limit, window[-max(1,..)],
      _active_participants, level2 cap, thread depth)
- [x] services/summary_aliases.py (+build_alias_resolver)
- [x] services/summary_generator.py (_chat_limit: rag_l2/max_context_tokens/chars)
- [x] services/summary_memory.py (window/rag/retention/compress/edge_weight per-chat)
- [x] services/user_relations.py (_display_name B-13-limitation, документирование)
- [x] web/api/routes.py (GET select_options/labels; POST валидация — обе ветки)
- [x] web/api/chat_lore.py (list_relations: Semaphore(5) username-всем, photo-топ-50,
      per-chat alias_resolver B-13)
- [x] web/app.js (TABS-зеркало, flatGroupRank, sectionTitle, chatLoreTab/relationsTab,
      setTab-сброс, relChat-гвард, relations-автозагрузка, карточки модулей)
- [x] web/index.html (select-виджет basic+advanced, `:open="expandOpen"`, relations-
      шаблон (участники+конфиг-блок+аккордеон), lore-конфиг-блок, удаление блока
      участников из лора, карточки модулей)
- [x] scripts/backfill_104_chat_flags.py (идемпотентность/безопасность)
- [x] scripts/backfill_104_overrides.py (множители, caps, skip-логика None-дефолтов)
- [x] tests/test_104_backend_additions.py, test_progressive_tab_basic_coverage.py,
      test_frontend_tab_mapping.py + обновлённые маркер-тесты (4860 passed)
- [x] plans/reports/round10.4_review_fixes.md (соответствие реальности: 3 пункта —
      R10.4-3/4/7 расхождения зафиксированы)

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