#!/bin/bash
# ACCEPTANCE-96 — read-only журнальная волна (после живого набора ADD-EXP Ф6).
# Запуск: sh /tmp/accept96_journal.sh "<wave_since>"  (root/venv-доступен)
SINCE="$1"
OUT=/tmp/accept96b/journal.txt
echo "=== NOW ==="
date -u '+%Y-%m-%dT%H:%M:%SZ'
journalctl -u admin_bot --since "$SINCE" --no-pager > "$OUT" 2>/dev/null
echo "WAVE_SINCE=[$SINCE]"
echo "=== SERVICE ==="
systemctl show admin_bot -p MainPID -p NRestarts -p ExecMainStartTimestamp \
  -p ExecMainStatus -p ActiveState -p SubState --no-pager
curl -s http://127.0.0.1:8000/healthz; echo
curl -s https://admin-bot.duckdns.org/healthz; echo
echo "=== COUNTS (wave) ==="
echo ERR=$(grep -cE 'ERROR|CRITICAL|Traceback' "$OUT")
echo E402=$(grep -c '402' "$OUT")
echo SKIPS=$(grep -c 'maximum number of running instances' "$OUT")
echo RUNTIMEWARN=$(grep -c 'RuntimeWarning' "$OUT")
echo DBLOCKED=$(grep -c 'database is locked' "$OUT")
echo EXPR_DIAG=$(grep -c 'expression_diag' "$OUT")
echo EXPR_RESOLVE_FAIL=$(grep -c 'expression resolve failed' "$OUT")
echo PROMPT_LAYERS=$(grep -c 'mca_event=prompt_layers' "$OUT")
echo DIRECT_REPLY_SENT=$(grep -c '\[direct\] reply sent' "$OUT")
echo L2WRITER=$(grep -c 'l2 writer' "$OUT")
echo LOCALBOTAPI=$(grep -c '\[local-bot-api\]' "$OUT")
echo "=== expression-related lines (tail 25) ==="
grep -E 'expression|Expression_Settings|Expression_Examples' "$OUT" | tail -25
echo "=== ERR lines (first 30) ==="
grep -E 'ERROR|CRITICAL|Traceback' "$OUT" | head -30
echo "=== sqlite read-only probe ==="
cd /var/www/admin_bot && ./venv/bin/python - <<'PY'
import json
import os
import sqlite3
import sys
sys.path.insert(0, "/var/www/admin_bot")
try:
    from config.settings import settings
    path = str(getattr(settings, "DB_PATH", "") or "local_database.db")
    if not os.path.isabs(path):
        path = os.path.join("/var/www/admin_bot", path)
except Exception:
    path = "/var/www/admin_bot/local_database.db"
con = sqlite3.connect(path, timeout=20)
con.row_factory = sqlite3.Row
def q(sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]
print(json.dumps({
    "db_path": path,
    "user_version": q("PRAGMA user_version"),
    "analyses": q("SELECT status, COUNT(*) n FROM mca_media_analyses "
                  "GROUP BY status"),
    "expr_diag_recent": q("SELECT ts, event_name, outcome, status, "
                          "reason_code, chat_id FROM mca_events WHERE "
                          "event_name='expression_diag' ORDER BY ts DESC "
                          "LIMIT 15"),
    "expr_samples": q("SELECT technique, owner_approved, status, "
                      "COUNT(*) n FROM humor_samples WHERE "
                      "technique='expression_register' GROUP BY 1,2,3"),
    "prompt_layers_expr_recent": q("SELECT ts, status, reason_code, "
                                   "chat_id FROM mca_events WHERE "
                                   "event_name='prompt_layers' AND "
                                   "status LIKE 'expression%' ORDER BY ts "
                                   "DESC LIMIT 15"),
}, ensure_ascii=False, default=str))
PY
echo "=== DONE ==="

