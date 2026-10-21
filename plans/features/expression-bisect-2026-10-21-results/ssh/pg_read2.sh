#!/usr/bin/env bash
# EXPRESSION-BISECT: попытка #2 (последний коннект) — read-only PG snapshot.
cd /var/www/admin_bot || exit 9
set -a; . ./.env 2>/dev/null; set +a
echo "== env80 =="
sed -n '80p' .env | cut -d= -f1
echo "== db_set =="
[ -n "$DATABASE_URL" ] && echo "DATABASE_URL set" || echo "DATABASE_URL EMPTY"
DBU=$(echo "$DATABASE_URL" | sed -nE 's|.*://([^:/@]+):[^@]+@.*|\1|p')
DBN=$(echo "$DATABASE_URL" | sed -nE 's|.*@[^:/]+[:0-9]*/([A-Za-z0-9_]+).*|\1|p')
echo "db_user=$DBU db_name=$DBN"
PSQL=""
if command -v psql >/dev/null 2>&1; then PSQL="psql"; fi
if [ -z "$PSQL" ]; then
  for b in /usr/lib/postgresql/*/bin/psql /usr/pgsql-*/bin/psql /usr/local/bin/psql; do
    [ -x "$b" ] && PSQL="$b" && break
  done
fi
if [ -z "$PSQL" ] && command -v docker >/dev/null 2>&1; then
  CTR=$(docker ps --format '{{.Names}} {{.Image}}' 2>/dev/null | awk 'tolower($0) ~ /postgres/ {print $1; exit}')
  if [ -n "$CTR" ]; then
    echo "docker_ctr=$CTR"
    PSQL="docker exec -i $CTR psql -X -q -A -t"
    PSQL_ARGS=""
  fi
fi
if [ -z "$PSQL" ]; then echo "NO_PSQL_PATH"; exit 8; fi
echo "== psql =="
case "$PSQL" in
  docker*) Q() { $PSQL -U "${DBU:-postgres}" -d "${DBN:-postgres}" -c "$1"; } ;;
  *) Q() { "$PSQL" "$DATABASE_URL" -X -q -A -t -c "$1"; } ;;
esac
echo "== prompts_list =="
Q "SELECT key||' | '||length(value::text) FROM bot_settings WHERE key LIKE 'prompts.%' ORDER BY key;" || echo PGERR
echo "== prompts_json =="
Q "SELECT coalesce(json_agg(json_build_object('k',key,'v',value::text))::text,'[]') FROM bot_settings WHERE key IN ('prompts.direct_chat_verbalizer_system_prompt','prompts.direct_chat_system_prompt','prompts.direct_l1_planner_system_prompt','prompts.verbilizer_default_mode','prompts.verbilizer_mode_casual','prompts.verbilizer_mode_serious','prompts.verbilizer_mode_deep_research');" || echo PGERR
echo "== settings_json =="
Q "SELECT coalesce(json_agg(json_build_object('k',key,'v',value::text))::text,'[]') FROM bot_settings WHERE key IN ('style.policy','character.expression','character.core','flags.unified_composer_enabled','flags.humor_craft_enabled','flags.humor_library_enabled','flags.response_plan_enabled','flags.smart_verbalizer_modes_enabled','flags.persona_enabled','flags.character_layers_enabled','flags.character_speech_enabled','flags.style_scope_enabled','chat.temperature_preset_default') ORDER BY key;" || echo PGERR
echo "== chat_overrides_json =="
Q "SELECT coalesce(json_agg(json_build_object('chat_id',chat_id,'ov',chat_params->'overrides'))::text,'[]') FROM chat_profiles WHERE chat_id IN (-1002661910336,-1004482340693);" || echo PGERR
echo "== personas_json =="
Q "SELECT coalesce(json_agg(json_build_object('chat_id',chat_id,'is_global',is_global,'name',name,'biography',biography,'spo',system_prompt_overrides,'aware',is_aware_ai))::text,'[]') FROM personas WHERE is_global=true OR chat_id IN (-1002661910336,-1004482340693);" || echo PGERR
echo "== traits_json =="
Q "SELECT coalesce(json_agg(json_build_object('trait',trait,'src',source))::text,'[]') FROM (SELECT trait, source FROM persona_traits ORDER BY created_at DESC, id DESC LIMIT 50) t;" || echo PGERR
echo "== done =="
