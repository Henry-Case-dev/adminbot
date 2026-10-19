#!/bin/bash
# ACCEPTANCE-95b — read-only journal wave (prod 2.58.95): 95b markers +
# full traceback blocks of the 95a window (13:47-13:56Z classification).
# Run under sudo. No writes, no secrets.
WAVE_SINCE="$1"
APP=/var/www/admin_bot
jw() { journalctl -u admin_bot --since "$WAVE_SINCE" --no-pager; }
j95a() { journalctl -u admin_bot --since "2026-10-19 13:47:00" \
         --until "2026-10-19 13:56:40" --no-pager; }
echo "=== NOW ==="; date -u '+%Y-%m-%dT%H:%M:%SZ'; echo "WAVE_SINCE=[$WAVE_SINCE]"
echo "=== SERVICE ==="
systemctl show admin_bot -p MainPID -p NRestarts -p ActiveState -p SubState -p ExecMainStatus --no-pager | tr '\n' ' '; echo
curl -s --max-time 5 http://127.0.0.1:8000/healthz; echo
curl -s --max-time 8 https://admin-bot.duckdns.org/healthz; echo
echo "=== 95A WINDOW FULL ERROR BLOCKS (13:47-13:56Z) ==="
echo "--- 'Cause exception while process update' with context ---"
j95a | grep -n -A 30 'Cause exception while process update' | head -120
echo "--- all Traceback headers with 3 lines before ---"
j95a | grep -n -B 3 -A 20 'Traceback (most recent call last)' | head -200
echo "--- 95a window ERR/CRIT count ---"
echo W95A_ERR=$(j95a | grep -cE 'ERROR|CRITICAL|Traceback' || true)
echo "=== 95B WAVE: markers ==="
echo WAVE_ERR=$(jw | grep -cE 'ERROR|CRITICAL|Traceback' || true)
echo WAVE_E402=$(jw | grep -c ' 402 ' || true)
echo WAVE_SKIPS=$(jw | grep -c 'maximum number of running instances' || true)
echo WAVE_RUNTIMEWARN=$(jw | grep -ciE 'RuntimeWarning|never awaited' || true)
echo WAVE_DB_LOCKED=$(jw | grep -c 'database is locked' || true)
echo "--- 95b wave ERROR/CRITICAL/Traceback (first 20) ---"
jw | grep -E 'ERROR|CRITICAL|Traceback' | head -20
echo VA_ADAPT_LOG=$(jw | grep -c '\[vision\] adapt | strategy=' || true)
echo VA_NORMALIZE_LOG=$(jw | grep -c '\[vision\] normalize' || true)
echo VA_EVENTS=$(jw | grep -c 'mca_event=vision_adapt' || true)
echo PGD_POSTGEN_LOG=$(jw | grep -c '\[vision\] postgen |' || true)
echo PGD_EVENTS=$(jw | grep -c 'mca_event=image_postgen_vision' || true)
echo VISION_DL_STAGE=$(jw | grep -c 'stage=download' || true)
echo VISION_READABLE_RESCUE=$(jw | grep -c 'unreadable rescued via normalization' || true)
echo "--- [vision] adapt lines (full, 95b wave) ---"
jw | grep '\[vision\] adapt' | head -20
echo "--- [vision] postgen lines (full, 95b wave) ---"
jw | grep '\[vision\] postgen' | head -10
echo "--- [vision] normalize lines (95b wave) ---"
jw | grep '\[vision\] normalize' | head -10
echo "--- vision_media events (95b wave, tail 25) ---"
jw | grep 'mca_event=vision_media' | tail -25
echo "--- vision_adapt events (95b wave, tail 10) ---"
jw | grep 'mca_event=vision_adapt' | tail -10
echo "--- image_postgen_vision events (95b wave, tail 10) ---"
jw | grep 'mca_event=image_postgen_vision' | tail -10
echo "--- [image] lines (95b wave, tail 20) ---"
jw | grep '\[image\]' | tail -20
echo "--- config updated lines (95b wave, tail 10) ---"
jw | grep -E 'config chat updated' | tail -10
echo "=== MIGRATIONS (95b wave) ==="
jw | grep -E 'migration|user_version' | tail -6
echo "=== SQLITE READ-ONLY PROBE ==="
cd $APP && ./venv/bin/python /tmp/accept95_dbcheck.py
echo "=== DONE ==="
