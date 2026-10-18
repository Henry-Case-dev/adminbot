#!/bin/bash
# ACCEPTANCE-90 — журнальная фаза приёмки 2.58.90 (T0 = деплой+рестарт).
# READ-ONLY: journalctl + sqlite (mode=ro). В прод ничего не пишет.
# Запуск под sudo: sudo sh /tmp/acc90_journal.sh "2026-10-18T13:34:23Z"
# T0 — строго RFC3339/UTC (суффикс Z): journalctl и SQL-порог считаются в UTC.
T0="${1:-2026-10-18T13:34:23Z}"
APP=/var/www/admin_bot
TMP=/tmp/acc90_journal.txt
T0E=$(TZ=UTC date -d "$T0" +%s)
export T0E
echo "=== NOW ==="; date -u '+%Y-%m-%dT%H:%M:%SZ'
echo "=== T0 ==="; echo "T0_ARG=$T0"; echo "T0_EPOCH=$T0E"
echo "=== NODE/HEALTH ==="
cd "$APP" && echo HEAD=$(git rev-parse HEAD) && echo BRANCH=$(git rev-parse --abbrev-ref HEAD)
curl -s --max-time 5 http://127.0.0.1:8000/healthz; echo
systemctl show admin_bot -p MainPID -p NRestarts -p ExecMainStatus -p ActiveState -p ExecMainStartTimestamp | tr '\n' ' '; echo
echo "=== JOURNAL dumped to $TMP ==="
journalctl -u admin_bot --since "$T0" --no-pager > "$TMP" 2>/dev/null
echo "JOURNAL_LINES=$(wc -l < "$TMP")"
echo "=== JOURNAL COUNTS since T0 ==="
echo "ERR=$(grep -cE 'ERROR|CRITICAL|Traceback' "$TMP" || true)"
echo "CRITICAL=$(grep -c 'CRITICAL' "$TMP" || true)"
echo "TRACEBACK=$(grep -c 'Traceback' "$TMP" || true)"
echo "WARN_NOSTALGIA=$(grep -c '\[nostalgia\] WARNING' "$TMP" || true)"
echo "WARN_B01=$(grep -c '\[b01\]' "$TMP" || true)"
echo "SPEECH_WARN=$(grep -c '\[speech\]' "$TMP" || true)"
echo "STYLE_WARN=$(grep -c '\[style_policy\]' "$TMP" || true)"
echo "=== NOSTALGIA JOURNAL LINES since T0 (tail 40) ==="
grep -E '\[nostalgia\]' "$TMP" | tail -40
echo "=== NOSTALGIA COUNTERS since T0 ==="
echo "NOST_SCEN_A=$(grep -c 'scenario=A' "$TMP" || true)"
echo "NOST_SKIP=$(grep -c '\[nostalgia\] skip' "$TMP" || true)"
echo "NOST_SENT=$(grep -c '\[nostalgia\] sent' "$TMP" || true)"
echo "NOST_GATE_SKIP=$(grep -c 'gate nostalgia' "$TMP" || true)"
echo "NOST_TICK_NOOP=$(grep -c 'no-op (hot-включение' "$TMP" || true)"
echo "NOST_TICK_LINES=$(grep -c '\[nostalgia\] tick' "$TMP" || true)"
echo "=== ACCEPTANCE-WINDOW SPEECH STEPS (не ERROR, а факт правок) ==="
grep -E 'document saved|chat override reset|expression write|core meta|gates\] set|learning action|humor craft' "$TMP" | tail -15
echo "=== MCA_EVENTS + NOSTALGIA_LOG (sqlite, mode=ro) ==="
cd "$APP" || exit 3
if [ ! -x ./venv/bin/python ]; then echo "NO_VENV_PYTHON"; echo "=== DONE ==="; exit 0; fi
./venv/bin/python - <<'PY'
import json
import os
import sqlite3

t0 = int(os.environ["T0E"])
db = sqlite3.connect("file:/var/www/admin_bot/local_database.db?mode=ro",
                     uri=True)
db.row_factory = sqlite3.Row
out = {"t0_epoch": t0}
cur = db.execute(
    "SELECT COUNT(*) AS c FROM mca_events WHERE ts >= ? "
    "AND event_name IN ('nostalgia_run','initiative_observer_scan',"
    "'initiative_opportunity','initiative_decided',"
    "'initiative_writer_generated','initiative_recheck_passed',"
    "'initiative_sent','initiative_observer_diagnostic')", (t0,))
out["initiative_events_total_since_t0"] = int(cur.fetchone()["c"])
cur = db.execute(
    "SELECT event_name, COUNT(*) AS c FROM mca_events WHERE ts >= ? "
    "AND (event_name LIKE 'nostalgia%' OR event_name LIKE 'initiative%') "
    "GROUP BY event_name", (t0,))
out["events_by_name"] = {r["event_name"]: int(r["c"]) for r in cur.fetchall()}
cur = db.execute(
    "SELECT COUNT(*) AS c FROM mca_events WHERE ts >= ? "
    "AND event_name = 'initiative_observer_scan' AND stage = 'anchored'",
    (t0,))
out["scan_anchored_events_since_t0"] = int(cur.fetchone()["c"])
cur = db.execute(
    "SELECT ts, event_name, outcome, stage, reason_code, chat_id "
    "FROM mca_events WHERE ts >= ? AND (event_name LIKE 'nostalgia%' OR "
    "event_name = 'initiative_observer_scan') ORDER BY ts DESC LIMIT 40",
    (t0,))
out["recent_rows"] = [dict(r) for r in cur.fetchall()]
cur = db.execute(
    "SELECT id, ts, chat_id, kind, status, meta FROM nostalgia_log "
    "WHERE ts >= ? ORDER BY id DESC LIMIT 20", (t0,))
rows = []
for r in cur.fetchall():
    row = dict(r)
    try:
        meta = json.loads(row.get("meta") or "{}")
    except Exception:
        meta = {"_raw": str(row.get("meta"))[:120]}
    if isinstance(meta, dict) and "candidate_text" in meta:
        meta["candidate_text"] = "[%d chars]" % len(
            str(meta.get("candidate_text") or ""))
    row["meta"] = meta
    rows.append(row)
out["nostalgia_log_since_t0"] = rows
cur = db.execute("SELECT COUNT(*) AS c FROM nostalgia_log WHERE ts >= ?",
                 (t0,))
out["nostalgia_log_count_since_t0"] = int(cur.fetchone()["c"])
print("MCA90_JSON " + json.dumps(out, ensure_ascii=False))
PY
echo "=== DONE ==="
