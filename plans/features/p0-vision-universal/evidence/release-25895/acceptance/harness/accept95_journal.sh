#!/bin/bash
# ACCEPTANCE-95 — read-only journal/health wave (prod 2.58.95).
# Run under sudo. No writes, no secrets.
# Usage: sh accept95_journal.sh "2026-10-19 13:07:43"   (T0 deploy; optional)
#        sh accept95_journal.sh ""                        (skip deploy-T0 part)
WAVE_SINCE="$1"
APP=/var/www/admin_bot
T0="2026-10-19 13:07:43"     # deploy T0 of 2.58.95 (fixed, from deploy evidence)
jw() { journalctl -u admin_bot --since "$WAVE_SINCE" --no-pager; }
jt() { journalctl -u admin_bot --since "$T0" --no-pager; }
echo "=== NOW ==="; date -u '+%Y-%m-%dT%H:%M:%SZ'; echo "WAVE_SINCE=[$WAVE_SINCE] DEPLOY_T0=[$T0]"
echo "=== SERVICE ==="
systemctl show admin_bot -p MainPID -p NRestarts -p ActiveState -p SubState -p ExecMainStatus -p ExecMainStartTimestamp --no-pager | tr '\n' ' '; echo
echo USER=$(ps -o user= -p $(systemctl show admin_bot -p MainPID --value) 2>/dev/null)
curl -s --max-time 5 http://127.0.0.1:8000/healthz; echo
curl -s --max-time 8 https://admin-bot.duckdns.org/healthz; echo
echo "=== WAVE WINDOW: ERR/CRIT/TB/402/SKIPS ==="
echo WAVE_ERR=$(jw | grep -cE 'ERROR|CRITICAL|Traceback' || true)
echo WAVE_E402=$(jw | grep -c ' 402 ' || true)
echo WAVE_SKIPS=$(jw | grep -c 'maximum number of running instances' || true)
echo WAVE_RUNTIMEWARN=$(jw | grep -ciE 'RuntimeWarning|never awaited' || true)
echo WAVE_DB_LOCKED=$(jw | grep -c 'database is locked' || true)
echo "--- wave ERROR/CRITICAL/Traceback lines (first 20) ---"
jw | grep -E 'ERROR|CRITICAL|Traceback' | head -20
echo "=== WAVE: VISION-ADAPT / POSTGEN markers ==="
echo VA_ADAPT_LOG=$(jw | grep -c '\[vision\] adapt | strategy=' || true)
echo VA_NORMALIZE_LOG=$(jw | grep -c '\[vision\] normalize' || true)
echo VA_PREP_LOG=$(jw | grep -c '\[vision\] adapt | in=' || true)
echo VA_EVENTS=$(jw | grep -c 'mca_event=vision_adapt' || true)
echo PGD_POSTGEN_LOG=$(jw | grep -c '\[vision\] postgen |' || true)
echo PGD_EVENTS=$(jw | grep -c 'mca_event=image_postgen_vision' || true)
echo IMG_GENERATED=$(jw | grep -c '\[image\] generated |' || true)
echo IMG_RESERVE_DENIED=$(jw | grep -c '\[image\] reserve denied' || true)
echo IMG_RESERVE_REPLAY=$(jw | grep -c '\[image\] reserve replay' || true)
echo VISION_DL_STAGE=$(jw | grep -c 'stage=download' || true)
echo VISION_READABLE_RESCUE=$(jw | grep -c 'unreadable rescued via normalization' || true)
echo "--- [vision] adapt lines (full, wave) ---"
jw | grep '\[vision\] adapt' | head -20
echo "--- [vision] postgen lines (full, wave) ---"
jw | grep '\[vision\] postgen' | head -10
echo "--- [vision] normalize lines (wave) ---"
jw | grep '\[vision\] normalize' | head -10
echo "--- vision_media events (wave, tail 20) ---"
jw | grep 'mca_event=vision_media' | tail -20
echo "--- vision_adapt events (wave, tail 10) ---"
jw | grep 'mca_event=vision_adapt' | tail -10
echo "--- image_postgen_vision events (wave, tail 10) ---"
jw | grep 'mca_event=image_postgen_vision' | tail -10
echo "--- [image] lines (wave, tail 20) ---"
jw | grep '\[image\]' | tail -20
echo "=== DEPLOY T0 baseline (ERR/402/SKIPS since 2.58.95 T0) ==="
echo T0_ERR=$(jt | grep -cE 'ERROR|CRITICAL|Traceback' || true)
echo T0_E402=$(jt | grep -c ' 402 ' || true)
echo T0_SKIPS=$(jt | grep -c 'maximum number of running instances' || true)
echo T0_RUNTIMEWARN=$(jt | grep -ciE 'RuntimeWarning|never awaited' || true)
echo "--- T0 ERR lines (first 12) ---"
jt | grep -E 'ERROR|CRITICAL|Traceback' | head -12
echo "=== MIGRATIONS (wave) ==="
jw | grep -E 'migration|user_version' | tail -6
echo "=== SQLITE READ-ONLY PROBE ==="
cd $APP && ./venv/bin/python /tmp/accept95_dbcheck.py
echo "=== DONE ==="
