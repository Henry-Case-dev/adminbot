#!/usr/bin/env bash
set -u
SINCE=$(systemctl show -p ActiveEnterTimestamp --value admin_bot)
echo "SINCE=$SINCE"
J=$(journalctl -u admin_bot --since "$SINCE" --no-pager 2>/dev/null)
echo "FACTCHECK_LINES=$(printf "%s\n" "$J" | grep -ci factcheck || true)"
echo "FACTCHECK_ERR=$(printf "%s\n" "$J" | grep -i factcheck | grep -ciE "error|failed|exception|traceback" || true)"
printf "%s\n" "$J" | grep -i factcheck | cut -c1-200 | tail -8
echo "TURN_ERRORS=$(printf "%s\n" "$J" | grep -ciE "agent turn failed|pipeline_step .*status=error" || true)"
echo "== DONE =="