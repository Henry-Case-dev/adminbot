#!/usr/bin/env bash
set -u
echo "== anticliche pipeline_step error occurrences, 12h window (time only) =="
journalctl -u admin_bot --since "12 hours ago" --no-pager 2>/dev/null | grep -E "component=anticliche step=fetch status=error" | awk '{print $1, $2, $3, $NF}' | tail -12
echo "COUNT_12H=$(journalctl -u admin_bot --since "12 hours ago" --no-pager 2>/dev/null | grep -c 'component=anticliche step=fetch status=error' || true)"
echo "COUNT_2.58.273_PID=$(journalctl -u admin_bot --since "12 hours ago" --no-pager 2>/dev/null | grep 'component=anticliche step=fetch status=error' | grep -c 'python\[1325247\]' || true)"
echo "== any error/exception lines since restart (excluding anticliche) =="
SINCE=$(systemctl show -p ActiveEnterTimestamp --value admin_bot)
journalctl -u admin_bot --since "$SINCE" --no-pager 2>/dev/null | grep -iE "error|exception|traceback" | grep -v anticliche | cut -c1-180 | tail -10
echo "== DONE =="