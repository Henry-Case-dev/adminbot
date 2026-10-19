#!/bin/bash
# ACCEPTANCE-92 — read-only journal/health checks since T0 (deploy 2.58.92).
# Run under sudo. No writes, no secrets.
T0=1792365948
APP=/var/www/admin_bot
JC="journalctl -u admin_bot --since @${T0} --no-pager"
echo "=== NOW ==="; date -u '+%Y-%m-%dT%H:%M:%SZ'
echo "=== WORKER TICK (FIX2: SKIPS must be 0) ==="
echo SKIPS=$($JC | grep -c 'maximum number of running instances' || true)
echo CLAIM_SLOW=$($JC | grep -c 'claim sweep slow' || true)
echo CLAIM_TIMEOUT=$($JC | grep -c 'claim sweep timeout' || true)
echo MAINT_TIMEOUT=$($JC | grep -c 'maintenance stage timeout' || true)
echo VISION_LINES=$($JC | grep -cE '\[vision\]' || true)
echo "=== CLAIM_SLOW samples (last 8) ==="
$JC | grep 'claim sweep slow' | tail -8
echo "=== last [vision] lines ==="
$JC | grep -E '\[vision\]' | tail -12
echo "=== last vision tick timestamp ==="
$JC | grep -E 'VisionMediaWorker._tick|\[vision\]' | tail -1 | cut -c1-120
echo "=== ERR/CRIT/TB/402 since T0 ==="
echo ERR=$($JC | grep -cE 'ERROR|CRITICAL|Traceback' || true)
echo E402=$($JC | grep -c ' 402 ' || true)
echo RUNTIMEWARN=$($JC | grep -ciE 'RuntimeWarning|never awaited' || true)
echo DB_LOCKED=$($JC | grep -c 'database is locked' || true)
echo VISION_RL=$($JC | grep -c 'vision_rate_limited' || true)
echo "=== raw ERROR/CRITICAL/Traceback sample (first 10) ==="
$JC | grep -E 'ERROR|CRITICAL|Traceback' | head -10
echo "=== MIGRATIONS since T0 ==="
$JC | grep -E 'migration|user_version|backup-guard' | tail -8
echo "=== SERVICE ==="
systemctl show admin_bot -p MainPID -p NRestarts -p ActiveState -p SubState -p ExecMainStatus --no-pager
curl -s --max-time 5 http://127.0.0.1:8000/healthz; echo
echo "=== HTTPS ==="
curl -s --max-time 8 https://admin-bot.duckdns.org/healthz; echo
echo "=== ROUTES (https) ==="
for u in /healthz /web/ /static/app.css; do echo "ROUTE $u $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 https://admin-bot.duckdns.org$u)"; done
echo "=== SQLITE READ-ONLY ==="
cd $APP && ./venv/bin/python /tmp/accept92_dbcheck.py
echo "=== DONE ==="
