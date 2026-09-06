# Prod Params Audit — 06.09.2026

Статус: **read-only аудит прода**. Ничего не менялось. Источник: `bot_settings` (владелец, TMA).

## 1. TL;DR

- 341 ключ `bot_settings` (flags 51, limits 168, memory 32, models 29, prompts 10, reactions 38, content 1, keys 12 — секреты не выводились).
- Новые AGI-фичи на проде **ВКЛЮЧЕНЫ** (владелец включил в TMA):
  - `memory.dream_enabled=true`, `memory.nostalgia_enabled=true` (слои A+B)
  - `flags.dig_enabled=true`, `flags.dig_pre_gate_enabled=true`
  - `memory.infinite_retention=true`
  - `limits.smartmodule_concurrency_per_chat=3`
- **ВЫКЛЮЧЕНО**:
  - `flags.relations_tone_enabled=false` (механика отношений активна, влияние на тон выключено)
  - mimic/mimic_forwards=false
  - memory_commands_user_enabled=false
  - summary_streaming_enabled=false
  - alan_replies_enabled=false
  - olya_always_send=false
  - common_work_media_enabled=false
  - dead_page_post_on_join=false
  - summary_admin_only=false

## 2. Таблицы

> Дамп покрывает 4 группы: flags (51) + memory (32) + limits (168) + models (29) = 280 строк.
> prompts (10), reactions (38), content (1), keys (12) в дампе отсутствуют (секреты не выводились).
> Все значения вставлены дословно (`key = value`).

### (а) flags — 51

```text
flags.alan_replies_enabled=false
flags.chat_context_budgets_enabled=true
flags.chat_dedup_enabled=true
flags.chat_importance_keep_enabled=true
flags.chat_mood_enabled=true
flags.chat_rag_rerank_enabled=true
flags.chat_running_summary_enabled=true
flags.chat_silence_enabled=true
flags.chat_style_anchors_enabled=true
flags.checkup_memory_metrics_enabled=true
flags.common_media_enabled=true
flags.common_work_media_enabled=false
flags.db_wal_checkpoint_enabled=true
flags.dead_page_post_on_join=false
flags.dig_enabled=true
flags.dig_pre_gate_enabled=true
flags.direct_chat_botword_enabled=true
flags.download_enabled=true
flags.embed_cache_enabled=true
flags.enable_voice_transcription=true
flags.graph_dedup_enabled=true
flags.graph_episode_merge_enabled=true
flags.graph_fact_touch_enabled=true
flags.graph_mmr_enabled=true
flags.graph_rag_enabled=true
flags.graph_review_enabled=true
flags.graph_time_decay_enabled=true
flags.graph_user_quota_enabled=true
flags.llm_cb_enabled=true
flags.lore_auto_enabled=true
flags.lore_inject_enabled=true
flags.lore_worker_enabled=true
flags.memory_backup_enabled=true
flags.memory_commands_user_enabled=false
flags.mimic_enabled=false
flags.mimic_forwards_enabled=false
flags.olya_always_send=false
flags.olya_caption_enabled=true
flags.olya_caption_mention_enabled=true
flags.olya_enabled=true
flags.olya_repost_enabled=true
flags.relations_tone_enabled=false
flags.search_rerank_enabled=true
flags.smart_cache_enabled=true
flags.summary_admin_only=false
flags.summary_enabled=true
flags.summary_streaming_enabled=false
flags.throttle_persistent_enabled=true
flags.typing_indicator_enabled=true
flags.vec_int8_enabled=true
flags.ytdlp_for_youtube=true
```

### (б) memory — 32

```text
memory.dream_cluster_overlap_tokens=2
memory.dream_distillations_per_day=30
memory.dream_enabled=true
memory.dream_importance_sum_threshold=12
memory.dream_initial_window_hours=168
memory.dream_max_chats_per_run=10
memory.dream_max_clusters_per_run=5
memory.dream_min_new_facts_per_chat=5
memory.dream_quiet_check_minutes=30
memory.dream_repeat_threshold=3
memory.dream_tick_minutes=60
memory.dream_tokens_per_day=60000
memory.dream_window_end_hour=6
memory.dream_window_start_hour=4
memory.infinite_retention=true
memory.nostalgia_aggressiveness=0.3
memory.nostalgia_cooldown_hours=12
memory.nostalgia_enabled=true
memory.nostalgia_golden_min_days=60
memory.nostalgia_golden_min_importance=5
memory.nostalgia_hint_max_chars=300
memory.nostalgia_layer_a_enabled=true
memory.nostalgia_layer_a_max_hints=1
memory.nostalgia_max_per_day=3
memory.nostalgia_max_send_chars=400
memory.nostalgia_min_silence_minutes=45
memory.nostalgia_pause_hours=24
memory.nostalgia_quiet_end_hour=8
memory.nostalgia_quiet_start_hour=23
memory.nostalgia_tick_minutes=60
memory.nostalgia_unanswered_max=2
memory.nostalgia_year_back_days_window=2
```

### (в) limits — 168

#### (в-1) chat/контекст — 38

```text
limits.chat_branch_context_hops=3
limits.chat_budget_anchors_ratio=0.05
limits.chat_budget_branch_ratio=0.03
limits.chat_budget_global_ratio=0.3
limits.chat_budget_map_ratio=0.05
limits.chat_budget_rag_ratio=0.15
limits.chat_budget_reserve_ratio=0.1
limits.chat_budget_response_ratio=0.2
limits.chat_budget_target_ratio=0.05
limits.chat_budget_thread_ratio=0.2
limits.chat_burst_limit=3
limits.chat_context_budget_tokens=24000
limits.chat_context_fill_ratio=0.8
limits.chat_cooldown_seconds=300.0
limits.chat_current_question_max_chars=800
limits.chat_dedup_ttl_seconds=300
limits.chat_direct_reply_ttl_days=30
limits.chat_global_context_limit=200
limits.chat_global_context_max_chars=4000
limits.chat_global_context_max_tokens=null
limits.chat_level2_max_chars=1500
limits.chat_level2_min_raw_count=250
limits.chat_lock_max_entries=256
limits.chat_lock_wait_seconds=60.0
limits.chat_map_participants_cap=150
limits.chat_map_participants_hours=24
limits.chat_rag_dedup_overlap_ratio=0.8
limits.chat_running_summary_tail=30
limits.chat_silence_after_cooldowns=5
limits.chat_style_anchor_max_chars=400
limits.chat_style_anchors_count=20
limits.chat_temperature_balanced=0.7
limits.chat_temperature_chatty=1.0
limits.chat_temperature_precise=0.0
limits.chat_temperature_preset_default="balanced"
limits.chat_thread_max_chars=2000
limits.chat_thread_max_depth=6
limits.chat_thread_max_tokens=null
```

#### (в-2) graph/RAG/память — 39

```text
limits.graph_compression_log_retention_days=90
limits.graph_dedup_similarity_high=0.95
limits.graph_dedup_similarity_low=0.85
limits.graph_dedup_weight_bonus=0.1
limits.graph_edge_weight_increment=1
limits.graph_episode_merge_batch=20
limits.graph_episode_merge_interval_days=7
limits.graph_episode_merge_max_facts_per_cluster=5
limits.graph_extract_max_triplets=50
limits.graph_fact_touch_extend_days=7
limits.graph_fact_ttl_days=14
limits.graph_fact_weight_archive=0.4
limits.graph_fact_weight_direct=0.7
limits.graph_facts_per_user_quota=50
limits.graph_memorize_batch_retry_backoff=2.0
limits.graph_memorize_max_batch_retries=2
limits.graph_mmr_fetch_k=20
limits.graph_mmr_lambda=0.6
limits.graph_purge_protect_days=3
limits.graph_purge_protect_weight=0.8
limits.graph_rag_context_max_chars=2000
limits.graph_rag_facts_limit=10
limits.graph_review_interval_days=3
limits.graph_time_decay_floor=0.1
limits.graph_time_decay_half_life_days=60.0
limits.graph_top_edges_limit=5
limits.graph_unconfirmed_retention_days=14
limits.archive_memory_retention_days=90
limits.full_memory_retention_days=30
limits.embed_cache_max_rows=20000
limits.embed_cache_ttl_days=30
limits.smart_cache_max_rows=1000
limits.smart_cache_ttl_seconds=1800
limits.memory_backup_hour="05:00"
limits.memory_backup_keep=7
limits.memory_commands_remember_ttl_days=365
limits.search_context_messages=6
limits.search_cooldown_seconds=300.0
limits.search_max_symbols=8000
```

#### (в-3) summary — 17

```text
limits.summary_aliases={41 алиас}
limits.summary_chunk_delay=2.0
limits.summary_compress_batch=100
limits.summary_max_context_chars=30000
limits.summary_max_context_tokens=60000
limits.summary_max_message_chars=2000
limits.summary_max_window_messages=2000
limits.summary_rag_l2_limit=10
limits.summary_rag_l3_limit=10
limits.summary_retry_once_pause=5.0
limits.summary_stream_edit_interval_group=3.0
limits.summary_stream_edit_interval_private=1.0
limits.summary_throttle_seconds=300.0
limits.summary_timezone="Asia/Yekaterinburg"
limits.summary_window_hours=6.0
limits.max_summary_parts=1
limits.running_summary_ttl_minutes=60
```

#### (в-4) relations — 14

```text
limits.relations_acquaintance_min_days=7
limits.relations_acquaintance_min_msg=10
limits.relations_api_max_users=150
limits.relations_decay_half_life_days=14
limits.relations_downgrade_msg_30d=10
limits.relations_hold_absent_days=60
limits.relations_inject_max_chars=600
limits.relations_recalc_ttl_minutes=5
limits.relations_regular_min_days=90
limits.relations_regular_min_msg=200
limits.relations_scan_max_rows=50000
limits.relations_stage_change_min_days=30
limits.relations_veteran_min_days=365
limits.relations_veteran_min_msg=1000
```

#### (в-5) dream/nostalgia/dig/lore (в limits: dig + lore; dream/nostalgia — в memory (б)) — 13

```text
limits.dig_graph_hop_depth=2
limits.dig_max_facts=5
limits.dig_max_snippets=15
limits.dig_max_symbols=5000
limits.dig_year_back_window_days=2
limits.lore_generate_cooldown=60
limits.lore_inject_max_chars=3000
limits.lore_max_words=150
limits.lore_min_message_chars=20
limits.lore_min_messages=15
limits.lore_tick_minutes=30
limits.lore_window_max_chars=20000
limits.lore_window_max_messages=300
```

#### (в-6) кулдауны/прочее — 47

```text
limits.alan_greeting_cooldown=10
limits.alan_reply_interval=10
limits.alan_silence_greeting_hours=2.0
limits.checkup_cooldown_seconds=300.0
limits.checkup_max_input_symbols=40000
limits.checkup_max_symbols=3000
limits.common_cooldown=0.0
limits.danger_cooldown=60.0
limits.db_wal_checkpoint_hours=6
limits.dead_page_caption_max_chars=1024
limits.dead_page_cooldown=0.0
limits.dead_page_max_forward_retries=5
limits.download_cooldown=300.0
limits.factcheck_context_messages=6
limits.factcheck_cooldown_seconds=300.0
limits.factcheck_max_symbols=8000
limits.gif_interval=5
limits.info_cooldown_seconds=300.0
limits.kostik_reply_probability=0.1
limits.media_share_max_mb=200
limits.media_share_ttl_seconds=900
limits.mimic_cooldown=3600.0
limits.mimic_min_words=5
limits.olya_cooldown=60.0
limits.selfdev_cooldown=300.0
limits.slavic_photo_interval=10
limits.slavik_mimic_cooldown=60.0
limits.slavik_mimic_min_words=5
limits.smartmodule_concurrency_per_chat=3
limits.smartmodule_concurrency_wait_seconds=60.0
limits.stt_groq_max_upload_mb=25
limits.stt_openrouter_max_upload_mb=20
limits.typing_interval_seconds=5.0
limits.video_stt_timeout_seconds=120.0
limits.video_summary_min_chars=100
limits.video_transcribe_max_duration_seconds=600
limits.video_transcribe_max_size_mb=50
limits.voice_max_duration_seconds=600
limits.webpage_cooldown_seconds=300.0
limits.webpage_max_symbols=8000
limits.work_cooldown=300.0
limits.youtube_cooldown_seconds=300.0
limits.youtube_max_symbols=8000
limits.youtube_transcript_proxy_domain="138.0.243.146"
limits.youtube_transcript_proxy_locations="us"
limits.youtube_transcript_proxy_port="8000"
limits.youtube_transcript_proxy_retries=""
```

### (г) models — 29

```text
models.checkup_betterstack_sql_host="https://eu-fsn-3-connect.betterstackdata.com"
models.checkup_betterstack_sql_query=""
models.checkup_betterstack_sql_table="t569218_adminbot_2"
models.embedding_dim=3072
models.embedding_model_name="gemini-embedding-001"
models.groq_max_concurrency=1
models.groq_max_retries=3
models.groq_min_interval=2.0
models.groq_timeout=10.0
models.llm_base_url="https://apinet.cloud/v1"
models.llm_cb_cooldown_seconds=300.0
models.llm_cb_failure_threshold=3
models.llm_fallback_base_url="https://api.deepseek.com"
models.llm_fallback_max_retries=2
models.llm_fallback_model="deepseek-v4-flash"
models.llm_fallback_timeout_seconds=120.0
models.llm_max_retries=2
models.llm_model_name="deepseek-v4-flash"
models.llm_retry_backoff_base=1.0
models.llm_retry_backoff_cap=8.0
models.llm_retry_jitter_max=2.0
models.llm_timeout=30.0
models.llm_total_budget=60.0
models.openrouter_timeout=15.0
models.token_safety_multiplier=0.8
models.tokenizer_encoding="o200k_base"
models.video_fallback_model="minimax/minimax-m3:free"
models.video_primary_model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
models.video_timeout_seconds=120.0
```

## 3. Наблюдения

- **NULL-ключи**: `limits.chat_global_context_max_tokens=null`, `limits.chat_thread_max_tokens=null`.
- **Пустые строки**: `models.checkup_betterstack_sql_query=""`, `limits.youtube_transcript_proxy_retries=""` и др.
- **Кастомные настройки**: timezone `Asia/Yekaterinburg`; youtube-прокси `138.0.243.146:8000` (локация `us`); `chat_context_budget_tokens=24000`; summary-токены `60000`; dream window `04:00–06:00`; backup `05:00`.
- **LLM-стек**: `deepseek-v4-flash` (apinet.cloud) + fallback deepseek; эмбеддинги `gemini-embedding-001` (dim 3072); video — free-модели.

## 4. Примечание

Значения могут быть изменены владельцем в TMA; файл — срез на 06.09.2026.
