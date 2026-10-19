#!/bin/bash
# ACCEPTANCE-94 — read-only journal/health checks since T0 (deploy 2.58.94).
# Run under sudo. No writes, no secrets.
# Usage: sh accept94_journal.sh "2026-10-19 08:18:20"
T0="$1"
T0B="$2"
if [ -n "$T0B" ]; then T0="$T0 $T0B"; fi
APP=/var/www/admin_bot
j() { journalctl -u admin_bot --since "$T0" --no-pager; }
echo "=== NOW ==="; date -u '+%Y-%m-%dT%H:%M:%SZ'; echo "T0_ARG=[$T0]"
echo "=== SERVICE ==="
systemctl show admin_bot -p MainPID -p NRestarts -p ActiveState -p SubState -p ExecMainStatus -p ExecMainStartTimestamp --no-pager | tr '\n' ' '; echo
echo USER=$(ps -o user= -p $(systemctl show admin_bot -p MainPID --value) 2>/dev/null)
curl -s --max-time 5 http://127.0.0.1:8000/healthz; echo
curl -s --max-time 8 https://admin-bot.duckdns.org/healthz; echo
echo "=== WORKER TICK (SKIPS must be 0) ==="
echo SKIPS=$(j | grep -c 'maximum number of running instances' || true)
echo CLAIM_SLOW=$(j | grep -c 'claim sweep slow' || true)
echo CLAIM_TIMEOUT=$(j | grep -c 'claim sweep timeout' || true)
echo MAINT_TIMEOUT=$(j | grep -c 'maintenance stage timeout' || true)
echo VISION_TICK=$(j | grep -cE 'vision.*(claim|sweep|tick)' || true)
echo "=== ERR/CRIT/TB/402 since T0 ==="
echo ERR=$(j | grep -cE 'ERROR|CRITICAL|Traceback' || true)
echo E402=$(j | grep -c ' 402 ' || true)
echo RUNTIMEWARN=$(j | grep -ciE 'RuntimeWarning|never awaited' || true)
echo DB_LOCKED=$(j | grep -c 'database is locked' || true)
echo VISION_PROBE_FAIL=$(j | grep -c 'vision_capability_probe failed' || true)
echo "=== raw ERROR/CRITICAL/Traceback sample (first 12) ==="
j | grep -E 'ERROR|CRITICAL|Traceback' | head -12
echo "=== raw 402 sample (first 12) ==="
j | grep ' 402 ' | head -12
echo "=== VISION-DL-FIX journal evidence (since T0) ==="
echo LOCAL_BOT_API_MARKER=$(j | grep -c '\[local-bot-api\] файлы:' || true)
echo LOCAL_BOT_API_WARN=$(j | grep -c '\[local-bot-api\] каталог файлов не читается' || true)
echo VISION_DL_STAGE=$(j | grep -c 'stage=download' || true)
echo VISION_EVENTS=$(j | grep -cE 'VISION_|vision_' || true)
echo "--- [vision] lines (tail 20) ---"
j | grep -E '\[vision\]|vision\.media|VISION_' | tail -20
echo "=== CFG-02C cover journal / image lines since T0 ==="
echo COVER_JOURNAL=$(j | grep -c 'summary_cover' || true)
echo SHARED_BUDGET_DENY=$(j | grep -c 'shared_budget' || true)
echo SUMMARY_TEST_START=$(j | grep -c 'SUMMARY_TEST_START' || true)
echo SUMMARY_TEST_COVER_OK=$(j | grep -c 'SUMMARY_TEST_COVER_OK' || true)
echo SUMMARY_TEST_COVER_FAILED=$(j | grep -c 'SUMMARY_TEST_COVER_FAILED' || true)
echo "--- [image] lines (tail 25) ---"
j | grep -E '\[image\]' | tail -25
echo "--- SUMMARY_TEST lines (tail 12) ---"
j | grep -E 'SUMMARY_TEST' | tail -12
echo "--- config updated lines (tail 10) ---"
j | grep -E 'config chat updated|config updated' | tail -10
echo "=== MIGRATIONS since T0 ==="
j | grep -E 'migration|user_version|backup-guard' | tail -8
echo "=== SQLITE READ-ONLY PROBE ==="
cd $APP && ./venv/bin/python /tmp/accept94_dbcheck.py
echo "=== DONE ==="
