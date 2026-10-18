# -*- coding: utf-8 -*-
"""ACCEPTANCE-90 — журнальный срез через HTTPS log-viewer (`/api/status/logs`).

Ring-буфер процесса (bounded) даёт точные числа по уровням + строки
WARNING/ERROR/CRITICAL в своём окне; это независимая от journalctl витрина
(секреты маскируются буфером до выдачи).

Запуск: python probe_logs_ring_25890.py
Результат: logs-ring-25890.json
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlencode

def _find_root(start: str) -> str:
    cur = os.path.abspath(start)
    while cur and cur != os.path.dirname(cur):
        if os.path.isfile(os.path.join(cur, "config", "settings.py")):
            return cur
        cur = os.path.dirname(cur)
    raise RuntimeError("repo root not found")


ROOT = _find_root(os.path.dirname(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config.settings import settings          # noqa: E402

BASE = "https://admin-bot.duckdns.org"
UID = 5885953495
OUT = os.path.join(os.path.dirname(__file__), "logs-ring-25890.json")


def init_data() -> str:
    data = {"auth_date": str(int(time.time())),
            "user": json.dumps({"id": UID, "first_name": "Acc90"},
                               separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", settings.API_TOKEN.encode(),
                      hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def get(path: str):
    req = urllib.request.Request(BASE + path, method="GET",
                                 headers={"X-Telegram-Init-Data": init_data()})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return {"_http": exc.code,
                "_body": exc.read().decode("utf-8", "replace")[:300]}
    except Exception as exc:                                  # noqa: BLE001
        return {"_error": f"{type(exc).__name__}: {exc}"}


def when(ts):
    try:
        if isinstance(ts, (int, float)):
            return dt.datetime.fromtimestamp(float(ts),
                                             dt.timezone.utc).isoformat()
        return str(ts)[:32] if ts is not None else ""
    except Exception:                                         # noqa: BLE001
        return str(ts)


def main() -> int:
    report = {
        "probe": "logs-ring-25890",
        "lane": "ACCEPTANCE-90",
        "now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "t0_utc": "2026-10-18T13:34:23Z",
        "source": "GET /api/status/logs (ring-buffer, bounded)",
        "note": ("ring-буфер ограничен по объёму: числа/строки относятся к его "
                 "текущему окну, а не ко всему окну приёмки; полное окно — "
                 "journal-25890-phase*.txt (SSH, read-only)"),
    }
    for lvl in ("ERROR+WARNING", "ERROR", "ALL"):
        data = get("/api/status/logs?level=%s&limit=1000"
                   % urllib.parse.quote(lvl))
        key = lvl.replace("+", "_")
        entries = data.get("logs") or []
        interesting = []
        for e in entries:
            level = str(e.get("level") or "")
            if level in ("ERROR", "CRITICAL", "WARNING"):
                interesting.append({
                    "level": level,
                    "when": when(e.get("ts") or e.get("timestamp")
                                 or e.get("created_at")),
                    "logger": str(e.get("logger") or e.get("name") or "")[:60],
                    "message": str(e.get("message") or "")[:300],
                })
        report[key] = {"counts": data.get("counts"),
                       "returned": data.get("count"),
                       "entries_total": len(entries),
                       "warning_error_entries": interesting}
        print("[%s] counts=%s returned=%s warn+err=%d"
              % (lvl, json.dumps(data.get("counts"), ensure_ascii=False),
                 data.get("count"), len(interesting)))
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print("[done] -> %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
