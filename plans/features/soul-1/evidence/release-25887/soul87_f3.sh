#!/bin/bash
# F3_migration_wait (hardened): wait for the NEW process (PID-anchored) to log
# "migrations: complete" since the restart moment T0. Avoids matching stale
# journal lines from previous boots (the 2.58.86 first-attempt nit).
# Usage: sudo sh /tmp/soul87_f3.sh "<T0 'YYYY-MM-DD HH:MM:SS'>"
T0="$1"
APP=/var/www/admin_bot
for i in $(seq 1 60); do
  M=$(systemctl show admin_bot -p MainPID --value)
  if [ -n "$M" ] && [ "$M" != "0" ]; then
    H=$(journalctl -u admin_bot --since "$T0" --no-pager 2>/dev/null | grep -F "python[$M]" | grep -c 'migrations: complete' || true)
    case "$H" in
      0) : ;;
      *) break ;;
    esac
  fi
  sleep 10
done
echo "F3_T0=$T0"
echo "F3_NEW_MAINPID=$(systemctl show admin_bot -p MainPID --value)"
echo "F3_ITER=$i"
journalctl -u admin_bot --since "$T0" --no-pager 2>/dev/null | grep -E 'database\] migration|backup-guard|user_version' | tail -8
M=$(systemctl show admin_bot -p MainPID --value)
H=$(journalctl -u admin_bot --since "$T0" --no-pager 2>/dev/null | grep -F "python[$M]" | grep -c 'migrations: complete' || true)
echo "F3_COMPLETE_LINES=$H"
