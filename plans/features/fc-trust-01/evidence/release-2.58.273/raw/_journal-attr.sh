#!/usr/bin/env bash
# Release 2.58.273 journal attribution (read-only): are tracebacks / 402/403 after the restart?
set -u
SINCE=$(systemctl show -p ActiveEnterTimestamp --value admin_bot)
echo "SINCE_ACTIVE_ENTER=$SINCE"
J=$(journalctl -u admin_bot --since "$SINCE" --no-pager 2>/dev/null)
echo "SINCE_RESTART_LINES=$(printf '%s\n' "$J" | wc -l)"
echo "SINCE_TRACEBACK=$(printf '%s\n' "$J" | grep -ci 'traceback' || true)"
echo "SINCE_SQL_ERR=$(printf '%s\n' "$J" | grep -ciE 'sqlite3\.(Operational|Integrity|Database)Error|asyncpg\.|sqlalchemy\.exc|ProgrammingError' || true)"
echo "SINCE_402_403=$(printf '%s\n' "$J" | grep -cE '\b(402|403)\b' || true)"
echo "== TRACEBACK LINES IN 2H WINDOW =="
journalctl -u admin_bot --since "3 hours ago" --no-pager 2>/dev/null | grep -i -B2 -A6 'traceback' | head -60
echo "== 402/403 LINES IN 2H WINDOW (first field only) =="
journalctl -u admin_bot --since "3 hours ago" --no-pager 2>/dev/null | grep -E '\b(402|403)\b' | cut -c1-220 | head -15
echo "== DONE =="
