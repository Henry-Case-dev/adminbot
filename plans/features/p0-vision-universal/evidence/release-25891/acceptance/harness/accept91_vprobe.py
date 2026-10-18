# -*- coding: utf-8 -*-
"""ACCEPTANCE-91 / scenario 2: live POST /api/vision/test (prod 2.58.91).

Real provider call through the deployed web app (loopback). Records only
R17-safe fields: no keys, no endpoints echoed beyond provider host, no bytes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse

APP = "/var/www/admin_bot"
os.chdir(APP)
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ADMIN_ID = 5885953495


def info(tag, text):
    print("VP %s | %s" % (tag, text), flush=True)


def make_init_data(user_id: int = ADMIN_ID) -> str:
    from config.settings import settings
    token = settings.API_TOKEN or ""
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHaccept91vision",
        "user": json.dumps({"id": user_id, "first_name": "Accept91",
                            "username": "accept91"},
                           separators=(",", ":")),
    }
    data_check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


def main() -> int:
    import httpx
    info("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    headers = {"X-Telegram-Init-Data": make_init_data(),
               "X-Chat-Id": "-1002661910336"}
    client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=180.0)
    try:
        t0 = time.monotonic()
        r = client.post("/api/vision/test", headers=headers, json={})
        dt = time.monotonic() - t0
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:400]}
        safe = {
            "http_status": r.status_code,
            "latency_ms": int(dt * 1000),
            "ok": body.get("ok"),
            "capability": body.get("capability"),
            "image_input": body.get("image_input"),
            "reason": body.get("reason"),
            "detail": body.get("detail"),
            "visible_reason": body.get("visible_reason"),
            "provider": body.get("provider"),
            "api_type": body.get("api_type"),
            "source": body.get("source"),
            "model": body.get("model"),
            "state": body.get("state"),
        }
        info("TEST", json.dumps(safe, ensure_ascii=False))
        r2 = client.get("/api/vision/state", headers=headers)
        try:
            st = r2.json()
        except Exception:
            st = {"raw": r2.text[:300]}
        info("STATE", json.dumps(st, ensure_ascii=False)[:3000])
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print("VP FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]))
        raise SystemExit(4)
