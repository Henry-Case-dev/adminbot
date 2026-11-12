set -u
cd /var/www/admin_bot
echo "UTC=$(date -u +%FT%TZ)"
echo "ACTIVE=$(systemctl is-active admin_bot)"
echo "INV=$(systemctl show admin_bot -p InvocationID --value)"
echo "NRestarts=$(systemctl show admin_bot -p NRestarts --value)"
echo "ENTERED=$(systemctl show admin_bot -p ActiveEnterTimestamp --value)"
echo "HEAD=$(git rev-parse HEAD) BRANCH=$(git rev-parse --abbrev-ref HEAD)"
echo "DIRTY=$(git status --porcelain --untracked-files=no | wc -l)"
echo "--- since restart 2026-11-12 10:28:40Z ---"
journalctl -u admin_bot --since '2026-11-12 10:28:40' --no-pager -o cat | awk 'BEGIN{tb=0;er=0;cr=0;wr=0;n=0} {n++} /Traceback/{tb++} /ERROR/{er++} /CRITICAL/{cr++} /WARNING/{wr++} END{printf "LINES=%d TB=%d ERR=%d CRIT=%d WARN=%d\n",n,tb,er,cr,wr}'
journalctl -u admin_bot --since '2026-11-12 10:28:40' --no-pager -o cat | grep -m1 'config_cache. initialized' || true
echo "--- backup ---"
ls -l /root/adminbot_backup_self-diag-01/
sha256sum /root/adminbot_backup_self-diag-01/bot_settings_betterstack_2026-11-12.json /root/adminbot_backup_self-diag-01/restore_bot_settings_betterstack.py
echo "--- env betterstack flags (names only) ---"
for k in BETTERSTACK_HOST LOGTAIL_SOURCE_TOKEN; do echo "ENV_${k}=$(grep -c "^${k}=" .env || true)"; done
