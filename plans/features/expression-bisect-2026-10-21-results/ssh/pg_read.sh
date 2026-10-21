#!/usr/bin/env bash
# EXPRESSION-BISECT: read-only PG/env snapshot. Никаких UPDATE/INSERT/DELETE.
cd /var/www/admin_bot || exit 9
echo "== healthz =="
curl -s --max-time 5 http://127.0.0.1:8000/healthz; echo
echo "== model_env =="
grep -E "^LLM_MODEL_NAME" .env
echo "== toggle_env =="
grep -E "^(COMPOSER_LAYER_BUDGET_TOKENS|UNIFIED_COMPOSER_ENABLED|HUMOR_CRAFT_ENABLED|HUMOR_LIBRARY_ENABLED|SPEECH_STYLE_POLICY_ENABLED|CHARACTER_CORE_ENABLED|CHARACTER_LAYERS_ENABLED|EXPRESSION_EXAMPLES_ENABLED|RESPONSE_PLAN_ENABLED|SMART_VERBALIZER_MODES_ENABLED|PERSONA_ENABLED|CHAT_TEMPERATURE_PRESET_DEFAULT|CHAT_TEMPERATURE_BALANCED)" .env || echo "(none)"
set -a; . ./.env; set +a
PSQL() { if command -v psql >/dev/null 2>&1; then psql "$@"; else sudo -n -u postgres psql "$@"; fi; }
echo "== prompts_list =="
PSQL "$DATABASE_URL" -At -c "SELECT key||' | '||length(value::text) FROM bot_settings WHERE key LIKE 'prompts.%' ORDER BY key;" || echo "PGERR"
echo "== prompts_json =="
PSQL "$DATABASE_URL" -At -c "SELECT coalesce(json_agg(json_build_object('k',key,'v',value::text))::text,'[]') FROM bot_settings WHERE key IN ('prompts.direct_chat_verbalizer_system_prompt','prompts.direct_chat_system_prompt','prompts.direct_l1_planner_system_prompt','prompts.verbilizer_default_mode','prompts.verbilizer_mode_casual','prompts.verbilizer_mode_serious','prompts.verbilizer_mode_deep_research');" || echo "PGERR"
echo "== settings_json =="
PSQL "$DATABASE_URL" -At -c "SELECT coalesce(json_agg(json_build_object('k',key,'v',value::text))::text,'[]') FROM bot_settings WHERE key IN ('style.policy','character.expression','character.core','flags.unified_composer_enabled','flags.humor_craft_enabled','flags.humor_library_enabled','flags.response_plan_enabled','flags.smart_verbalizer_modes_enabled','flags.persona_enabled','flags.character_layers_enabled','flags.character_speech_enabled','flags.style_scope_enabled','chat.temperature_preset_default') ORDER BY key;" || echo "PGERR"
echo "== chat_overrides_json =="
PSQL "$DATABASE_URL" -At -c "SELECT coalesce(json_agg(json_build_object('chat_id',chat_id,'ov',chat_params->'overrides'))::text,'[]') FROM chat_profiles WHERE chat_id IN (-1002661910336,-1004482340693);" || echo "PGERR"
echo "== personas_json =="
PSQL "$DATABASE_URL" -At -c "SELECT coalesce(json_agg(json_build_object('chat_id',chat_id,'is_global',is_global,'name',name,'biography',biography,'spo',system_prompt_overrides,'aware',is_aware_ai))::text,'[]') FROM personas WHERE is_global=true OR chat_id IN (-1002661910336,-1004482340693);" || echo "PGERR"
echo "== traits_json =="
PSQL "$DATABASE_URL" -At -c "SELECT coalesce(json_agg(json_build_object('trait',trait,'src',source))::text,'[]') FROM (SELECT trait, source FROM persona_traits ORDER BY created_at DESC, id DESC LIMIT 50) t;" || echo "PGERR"
echo "== done =="
